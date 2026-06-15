# PRD — Unattended Worker & Customer↔HOS Coordination Protocol

**Issue:** #254 · **Status:** draft PRD for review · **Author:** Claude (HOS-side), from the Scott↔CPS-Claude design discussion captured in #254 (2026-06-15)

**One-line:** A configurable HOS subsystem that lets HOS and its customer projects work **unattended** — a low-frequency cron that polls many repos for work, invokes a model **only when there is work**, runs all found work through the *existing* oversight gates, and auto-merges only what is provably safe — with a machine-readable bidirectional coordination protocol between HOS and each customer.

> **Relationship to the issue.** #254 is a structured starting point, not a spec. This PRD resolves its three open questions, pins concrete defaults, and elevates its design considerations to numbered requirements. Where #254 *locked* a decision, this PRD carries it forward verbatim and marks it **[locked in #254]**.

---

## 0. Resolved open questions (the four design forks)

| Question | Resolution | Rationale |
|---|---|---|
| **Spec home/format** | **Full PRD** at `docs/specs/UNATTENDED-WORKER-PROTOCOL.md` | A multi-release product line (v1 → adaptive/multi-customer → embargo automation), not a one-shot subsystem. PRD ceremony earns its keep. |
| **Adaptive polling — v1 or v2?** | **Adaptive in v1**, probe floor **15 min**, ceiling **daily** | The cron **probe** is GitHub API calls with **no model invocation** — cheap enough to fire every 15 min, and **the model sleeps unless the probe finds work** (#254 consideration #11). What we throttle is *model spend* (gated by work-found **and** the §8 budget), not the probe. Adaptive back-off (toward daily) exists only to spare **API quota** on dormant repos when one HOS watches many. |
| **Merge-gate dependency on #152** | **Hard prerequisite, per-repo.** Auto-merge enabled only where server-side branch protection is **detected** active; otherwise that repo runs **PROPOSE_ONLY**. | Auto-merge-≤MEDIUM is only a *boundary* if a bot can't bypass it. "Detected, not assumed" applies the fail-closed / re-derive-don't-trust principle (DECISIONS D33/D37/D41) to the merge gate. Lets CPS join in PROPOSE_ONLY day one and graduate when *its own* gate flips. |
| **Multi-customer scope** | **v1.** Per-customer budgets, round-robin, isolation, protocol versioning are in scope from the start. | CPS is the first real participant; retrofitting fairness/isolation onto a single-tenant loop is the expensive path. |

---

## 1. Problem & motivation

During the CPS field test we hand-rolled a session-only cron (every 20 min) that: polled `hos-coordination`-labelled issues → answered unanswered ones → watched the `feat/audit-healthcheck` review chain → on completion ran the oversight chain and either auto-merged-if-safe or opened a draft PR + `needs_human`. **It worked** — but everything was ad-hoc: NL-scraping to detect "already answered," no locking, no budget gate, no formal envelope, no observability, instance-local state that didn't survive a cold start.

This PRD generalizes that proven behaviour into a first-class, configurable HOS subsystem with the safety properties the hand-rolled version lacked.

### 1.1 Goals

- **G1** — Periodic, **token-free** "is there work?" probe across N customer repos; model invoked only when work exists.
- **G2** — Every autonomous change flows through the **existing** gates (risk-assessor → review chain → oversight-evaluator), identical to a human-initiated change. Autonomy is in *initiating and shepherding*, never in *shortcutting*.
- **G3** — A **machine-readable bidirectional protocol** (HOS ↔ customer): reports, questions, release notifications, PR-comment responses — with reliable threading and at-least-once idempotency.
- **G4** — **Risk-gated merge autonomy**: auto-merge only what is provably safe (≤MEDIUM, not security-relevant, full PROCEED), and only where the gate is server-side enforced.
- **G5** — **Budget-bounded** and **human-permissioned**: per-task and per-window token gates, default-deny on approval timeout, hard kill switch.
- **G6** — **Cold-start-safe**: GitHub is the only state store; any instance reconstructs full state from issues/labels/PRs.
- **G7** — **Multi-customer fair**: one HOS serves many repos without one noisy customer starving the rest.
- **G8** — **Observable & stoppable**: a forensic run ledger ("what did it do at 3am and why") and a dry-run/shadow mode.

### 1.2 Non-goals (v1)

- **NG1** — Near-real-time response. The 15-min probe floor + claim/budget-gate cycle makes this a sweeper, not a live responder; sub-15-minute SLAs are out of scope.
- **NG2** — Fully-automated security disclosure. Security reports are *routed to the embargo path* (a human + private channel), not auto-fixed in public. Embargo *automation* is a later release.
- **NG3** — Autonomous **feature** delivery. Features are triaged and **queued for human review**, never auto-built.
- **NG4** — Non-GitHub backends (GitLab/ADO). The protocol is GitHub-shaped in v1; the envelope is portable, the transport is not.
- **NG5** — Cross-instance leader election beyond claim-then-verify (no external lock service).

### 1.3 Success metrics

- **M1** — Zero duplicate-work incidents across concurrent instances over a 30-day window (locking correctness).
- **M2** — Zero token spend on idle cycles (probe-only runs invoke no model).
- **M3** — 100% of autonomous merges are ≤MEDIUM, non-security-relevant, full-PROCEED, in a server-side-gated repo (audit the ledger; any exception is a P0 bug).
- **M4** — Every autonomous action is reconstructable from GitHub alone after an instance is destroyed mid-run (cold-start drill passes).
- **M5** — Mean human-approval-request quality: each significance-gated request carries a token estimate, a blast-radius summary, and a default-deny deadline.

---

## 2. Personas & actors

| Actor | Identity | Role in the loop |
|---|---|---|
| **The worker loop** | machine-user **worker** (#152) | Opens PRs/branches, posts coordination replies, runs the build chain. **Never approves/merges.** |
| **The overseer** | machine-user **overseer** (#152) | Runs reviews, approves+merges SAFE/LOW–MEDIUM non-protected PRs *where server-side-gated*. Recommends-only above ceiling. |
| **The human (operator)** | `ScottThurlow` (admin) | Authorizes significant work, resolves features, handles embargoed security, holds the only `--admin` bypass + kill switch. |
| **The customer project** | its own repo + machine accounts | Files reports/questions, watches PR comments, receives release notifications. May be HOS itself (HOS dogfoods the protocol on its own repo). |

> **Identity is load-bearing, not cosmetic.** The whole merge-authority model rests on worker ≠ overseer ≠ human being *server-side distinguishable* (#152, `docs/AGENT-IDENTITY.md`). This PRD consumes that model; it does not re-specify it.

---

## 3. System architecture

```
                    ┌─────────────────────────────────────────────────┐
   cron (15m floor) │  PROBE  (no model)                              │
   ───────────────► │  for each customer repo, round-robin:          │
                    │    GitHub API: new/updated issues, PR comments, │
                    │    review-chain state, coordination envelopes    │
                    └───────────────┬─────────────────────────────────┘
                                    │ work found?  ── no ──► update cadence, sleep
                                    │ yes
                                    ▼
                    ┌─────────────────────────────────────────────────┐
   model invoked    │  TRIAGE  (confidence floor + requester allowlist)│
   from here ─────► │  classify: bug | feature | communication |       │
                    │            security-report | spec-gap | dup |    │
                    │            invalid         (low-conf → human)     │
                    └───┬───────────┬───────────┬───────────┬──────────┘
                        │           │           │           │
              communication      bug      security-report  feature / spec-gap
                        │           │           │           │
                        ▼           ▼           ▼           ▼
                   answer via   CLAIM →    EMBARGO PATH   QUEUE for
                   envelope     budget     (human + private  human review
                                gate →     channel; never    (no auto-build)
                                build      public auto-fix)
                                chain →
                                merge
                                authority
                                matrix
```

### 3.1 The pipeline is an orchestrator *into* the gates, never a bypass — **[locked in #254 #1]**

An autonomous bug fix is exactly: **claim → branch → reproducing test (red) → coder → risk-assessor → review chain → oversight-evaluator → merge-authority decision**. Identical to a human-initiated change. The loop adds *initiation and shepherding*; it removes nothing.

- **R3.1.1** — **No fix without a reproducing test first.** The loop must produce a test that *fails* against the bug before any fix, and *passes* after. A fix branch without a red→green test artifact is a hard reject (the loop reopens the issue with a `needs_human` note rather than merging).
- **R3.1.2** — The loop never calls a gate with relaxed parameters. It uses the same `run_validators.sh`, `run_second_review.sh`, and `oversight-evaluator` invocations a human would.

---

## 4. The coordination envelope — **[#254 consideration #6]**

NL-scraping ("have I already answered this?") was the single biggest pain in the field test. v1 replaces it with a **machine-readable envelope**: a fenced YAML block in the issue/comment body, plus a signature marker line.

### 4.1 Format

````
```hos-envelope
protocol-version: "1.0"
type: report | question | answer | release-notification | claim | heartbeat | ack
from: hos-overseer | hos-worker | cps-worker | human
to: hos | cps | <repo-slug>
correlation-id: "<uuid of the originating message>"
in-reply-to: "<correlation-id this responds to>"   # omit on originators
priority: P0 | P1 | P2 | P3
signature: "<marker — see §4.3>"
```
<!-- 🤖 [AI: claude] hos-envelope v1.0 -->
````

- **R4.1.1** — Every autonomous message HOS posts carries an envelope. A human-authored message *may* omit it; the loop treats envelope-less inbound as `from: human, type: question` by default and routes to triage.
- **R4.1.2** — `correlation-id` + `in-reply-to` give a threading DAG. "Already answered?" becomes: *does an `answer` envelope exist whose `in-reply-to` equals this message's `correlation-id`?* — a deterministic lookup, never NL inference.
- **R4.1.3** — **At-least-once idempotency.** Cron polling *will* double-deliver. Every consumer keys on `correlation-id`; processing the same id twice is a no-op. (GitHub is the dedup store — see §6.)

### 4.2 Protocol versioning — **[#254 consideration #10]**

- **R4.2.1** — `protocol-version` is mandatory. HOS and a given customer may run different releases. A consumer that receives a `protocol-version` it doesn't support posts a `type: ack` with an `unsupported-version` error and routes to human — it never silently mis-parses.
- **R4.2.2** — Version negotiation is **floor-based**: both sides operate at `min(supported)`. Major-version mismatch (`2.x` ↔ `1.x`) → human.

### 4.3 Authentication & the requester allowlist — **[#254 consideration #7]**

- **R4.3.1** — On a public repo, a random account must not be able to drive the loop. The loop honors envelopes/commands only from a **per-repo requester allowlist** (the customer's machine accounts + named human operators). Off-allowlist inbound is acknowledged and routed to human, never actioned autonomously.
- **R4.3.2** — The `signature` marker is an integrity hint, **not** a cryptographic guarantee in v1 (GitHub identity is the actual authn). It exists so a malformed/spoofed body fails the allowlist check loudly. (Signed commits/cryptographic envelope signing is a v2 hardening.)

---

## 5. Triage — **[#254 consideration #7]**

The **first** action on any found work. Misclassifying a feature as a bug and auto-"fixing" it is the expensive failure, so triage fails toward the human.

### 5.1 Classes

`bug` · `feature` · `communication` · `security-report` · `spec-gap` · `duplicate` · `invalid`

| Class | Autonomous handling |
|---|---|
| **bug** | Prioritize → claim → fix in priority order (§3.1, §7). |
| **communication** | Answer via envelope (§4); orchestrate analysis agents if needed. |
| **security-report** | **Embargo path only** (§9). Never public auto-fix. |
| **feature** | **Queue for human review.** No auto-build. |
| **spec-gap** | File/route to human as a spec issue (the spec-red-team flow); no auto-build. |
| **duplicate** | Link to canonical, close with envelope; no work. |
| **invalid** | Acknowledge, request clarification or close per policy; no work. |

### 5.2 Confidence floor

- **R5.2.1** — Triage emits a confidence score. **Below the floor (default 0.75) → route to human.** A low-confidence classification is never actioned autonomously.
- **R5.2.2** — `security-report` detection is **asymmetric**: any signal of a vulnerability (even low-confidence) forces the embargo path. False-positive embargo (a human glances and waves it through) is cheap; false-negative public auto-fix is catastrophic.

---

## 6. State model — GitHub *is* the database — **[#254 consideration #3]**

No hidden instance-local state. Claims, the token ledger, conversation threads, and done/not-done all live in issues/labels/PRs, so any instance reconstructs from a cold start.

- **R6.1** — **Idempotent recovery.** Before doing work, an instance checks "does a branch / draft-PR / answer-envelope already exist for this `correlation-id`?" If yes, it resumes/skips rather than redoing. This is what makes a reaped-mid-work claim safe to re-pick-up.
- **R6.2** — **No external datastore in v1.** Labels (`hos-claimed`, `hos-in-progress`, `needs_human`, `hos-budget-gated`, `hos-embargo`), assignees, issue/PR bodies, and a committed run-ledger file are the entire persistence layer.
- **R6.3** — **Cold-start drill (M4)** is a release gate: destroy an instance mid-task; a fresh instance must reach a correct, non-duplicating state from GitHub alone.

---

## 7. Locking, claims & heartbeat — **[#254 consideration #4]**

The lock is racy on a polled medium: two instances polling the same window can both "claim." v1 uses **claim-then-verify** plus a **heartbeat**.

- **R7.1 — Claim-then-verify.** To claim: post a `type: claim` envelope (tag `hos-claimed` + self-assign) → wait a **jittered delay** (default 30–90s) → re-read. If multiple claims exist, **lowest instance-id wins**; losers release immediately. (Self-assignment is the closest GitHub-atomic-ish primitive and is used as the tiebreak anchor.)
- **R7.2 — Heartbeat.** A live claim is refreshed by a periodic `type: heartbeat` envelope (default every **15 min**). The timeout reaps *silent* claims, not slow-but-progressing ones.
- **R7.3 — Claim timeout.** A claim with no heartbeat for **45 min** (3 missed beats) is **stale** and may be re-picked-up by any instance (which first runs the §6.1 idempotency check). Default: `claim_timeout = 45m`, `heartbeat_interval = 15m`.
- **R7.4 — Release on terminal state.** Merge, escalation, or per-issue failure-cap hit all release the claim (remove `hos-claimed`, unassign) and record the outcome in the ledger.

---

## 8. Significance & budget gates — **[#254 consideration #5]**

"Significant" is **two-dimensional**: a per-task estimate *and* a cumulative per-window budget (a quiet night of many small tasks adds up). Both gated; plus a hard kill switch.

> **Estimate-then-gate, never burn-then-discover.** The failure mode we are designing *out* is: a single task quietly consumes the whole budget, then everything else grinds to a halt with no warning. So the estimate is computed **before** any significant model work and the permission ask happens **up front**. The estimate is a cheap guardrail, **not** precise accounting — **estimation error is acceptable** (we err high and re-ask if a task blows past its estimate mid-flight; see R8.6). A rough-but-early number that prevents a runaway beats a precise one that arrives after the tokens are gone.

- **R8.1 — Per-task estimate, computed first.** Before invoking *any* significant model work on a unit, the loop estimates token burn from cheap signals (issue/diff size, changed-file count, blast radius, historical cost of similar tasks — itself ~free, no model pre-pass required; see O5). If `estimate > per_task_threshold` → **create a human-permission request** (an issue/comment envelope, `type: question`, the §8.2 escalation-comms contract) and **block that task** until approved. The estimate gate runs *ahead of* the spend, never after.
- **R8.2 — Per-window budget.** A cumulative ledger per `(customer, window)`. When cumulative spend would exceed `window_budget`, **all further significant work in the window is gated**, even individually-small tasks.
- **R8.3 — Default-deny on timeout.** Silence ≠ yes. An unanswered permission request past its deadline (default **12h**) is **denied**; the task is left for the human with a `needs_human` label. (Tunable, but never defaults to auto-approve.)
- **R8.4 — Hard kill switch.** A single human-flippable control (a repo-level label/file, e.g. `hos-halt`, checked at the top of every cycle) stops all autonomous action immediately. Probe may continue; *action* halts.
- **R8.5 — Wire to existing alerting.** Cost-runaway / budget-exceeded / kill-switch events fire the existing SMS pager / alerting path, not just the ledger.
- **R8.6 — Mid-flight overrun re-ask.** Because the estimate is deliberately rough (R8.1), a task that exceeds its estimate *while running* is **paused at the next gate boundary** and re-submitted for permission with the revised number — it does not silently run past its approved budget. Erring high on the initial estimate makes this the exception, not the rule.

### 8.2 Escalation communication contract — **[#257]**

The human reviewing an escalation **often lacks context**. Every escalation, permission request, and `needs_human` hand-off the loop produces — §8 budget asks, §9 PROPOSE_ONLY / HIGH-tier escalations, embargo routing (§9.2), default-deny notifications (R8.3) — **must** carry, in this order:

1. **Problem + risk + background.** What the situation is and the risks that need addressing. **Do not assume the human is an expert or has full context** — provide the relevant background to understand the decision cold.
2. **Options with pros/cons.** The viable ways to resolve it, each with its trade-offs.
3. **Recommendation + justification.** A specific recommended option and *why*.

- **R8.2.1** — An escalation missing any of the three elements is a **malformed escalation** and is itself a bug (the loop self-rejects and emits a complete one). A bare "needs human review" with no problem/options/recommendation is non-compliant.
- **R8.2.2** — The token estimate (R8.1) and blast-radius summary (§11.2) are part of element 1's risk picture for spend/merge escalations.

### 8.3 Default thresholds (v1)

| Knob | Default | Notes |
|---|---|---|
| `per_task_threshold` | **150k tokens** | Above → human permission request. |
| `window_budget` (per customer/day) | **1.5M tokens** | Cumulative gate; the "quiet night adds up" cap. |
| `approval_timeout` | **12h** | Default-deny on expiry. |
| `poll_floor` / `poll_ceiling` | **15m / 24h** | Probe cadence bounds (§10); probe is token-free. |
| `claim_timeout` / `heartbeat_interval` | **45m / 15m** | §7. |
| `triage_confidence_floor` | **0.75** | Below → human. |
| `per_issue_failure_cap` | **3** | §11. |
| `per_run_blast_radius` | **5 PRs / 10 issues / 25 files** | §11. |

> All knobs are **per-customer configurable**; the table is the shipped default profile.

---

## 9. Merge authority & the security embargo path

### 9.1 Merge-authority matrix — **[#254 #1]**

Two **orthogonal** gates. Auto-merge **iff** `(tier ≤ MEDIUM) AND (not security-relevant) AND (full PROCEED) AND (server-side gate detected active for this repo)`. The security override and the server-side requirement each independently beat the tier ceiling.

| Risk tier | Security-relevant? | Server-side gate? | Outcome |
|---|---|---|---|
| SAFE / LOW / MEDIUM | no | **yes** | **Auto-merge** (overseer) |
| SAFE / LOW / MEDIUM | no | no | **PROPOSE_ONLY** — draft PR + `needs_human` |
| SAFE / LOW / MEDIUM | **yes** | any | **Human** — touches a security subsystem (the audit-healthcheck field-test case) |
| HIGH / CRITICAL | any | any | **Human** — escalate, never auto-merge |
| any | any | gate **not detected** | **PROPOSE_ONLY** (capability detected, not assumed) |

- **R9.1.1 — Capability is detected, not assumed.** Per repo, the loop probes that server-side branch protection is genuinely active (read the protection API *and* confirm the overseer account lacks the standing to bypass it) before enabling auto-merge. A config flag alone never enables merge.
- **R9.1.2 — "security-relevant" is a property of the change, not the tier.** Touching `audit/`, auth, secrets, the gate scripts themselves, or any path on the per-repo security-sensitive list forces the human gate regardless of tier.

### 9.2 Security embargo path — **[locked in #254 #2]**

A publicly-filed vulnerability must **never** get a public auto-fix — a public PR telegraphs the exploit before it's patched.

- **R9.2.1** — `security-report` triage → **acknowledge** (envelope, no detail) → **route to a human + private channel** → fix under **embargo** with coordinated disclosure. No public branch, no public PR, no public test that reveals the vector.
- **R9.2.2** — The loop's *only* autonomous action on a security report is the ack + route + `hos-embargo` label. Everything else is human-driven in v1.

---

## 10. Adaptive polling — **[#254 consideration #11]**

The probe is a couple of GitHub API calls with **no model invocation** — cadence costs API quota, not tokens. **Cadence governs latency + API spend; the budget gate governs token spend — two independent knobs.** The cron fires the probe at the floor; **the model only wakes when the probe finds work**, so a tight probe cadence is cheap.

- **R10.1 — Bounds.** `floor = 15m`, `ceiling = 24h` (daily). The probe runs as often as every 15 min on an active repo; back-off only stretches the *probe* interval for dormant repos to save API quota — it never delays a model response to found work below the budget gate.
- **R10.2 — Back-off.** A repo with no recent issue/PR/comment activity backs off exponentially from floor toward ceiling.
- **R10.3 — Reset.** **Any inbound event** (new issue/PR/comment, new envelope) resets that repo to the floor, so latency stays low when it matters.
- **R10.4 — Priority pin.** An open **P0**, an **unanswered coordination** message, or an **embargoed-security** item pins cadence to the floor until resolved (overrides back-off).
- **R10.5 — Per-customer cadence.** Each repo has independent cadence state (stored in GitHub / the ledger, not instance-local).

---

## 11. Circuit breakers & observability — **[#254 considerations #8, #9]**

### 11.1 Circuit breakers

- **R11.1 — Per-issue failure cap.** Default **3**. A poison-pill issue that keeps failing is stopped (labeled `needs_human`) rather than burning tokens forever.
- **R11.2 — Per-run blast-radius caps.** Max **5 PRs / 10 issues / 25 files** touched per run; exceeding any cap halts the run and pages.
- **R11.3 — GitHub rate-limit backoff.** Honor `X-RateLimit-*`; exponential backoff, never hammer.
- **R11.4 — Max runtime per task.** A task exceeding its wall-clock budget is abandoned (claim released, `needs_human`).
- **R11.5 — Dead-man's-switch.** If no healthy cycle completes in **X** (default 6h), page a human — the loop being silently dead is itself an incident.

### 11.2 Observability

- **R11.6 — Run ledger.** Every autonomous action records **who / what / when / why / token-cost** to a committed, append-only ledger (mirrors `audit/oversight-log.jsonl`). Must answer "what did it do at 3am and why."
- **R11.7 — Dry-run / shadow mode.** A mode that runs the full loop — triage, claim-eval, build-plan — and **records what it *would* do** without acting. Mandatory for testing the loop on a live repo without risk, and the default for a newly-onboarded customer.

---

## 12. Multi-customer fairness — **[#254 consideration #10]**

One HOS polls many customer repos.

- **R12.1 — Per-customer budgets.** §8 budgets are per `(customer, window)`; one customer's spend never draws down another's.
- **R12.2 — Round-robin.** Probe + work scheduling rotates across customers so a noisy repo can't starve the rest. A single customer's per-run blast-radius cap (§11.2) bounds its share of any cycle.
- **R12.3 — Isolation.** A failure (poison-pill, rate-limit, kill-switch) in one customer's processing must not halt the others. Kill-switch is per-repo *and* global (a global `hos-halt` stops everything).
- **R12.4 — Per-customer capability.** Auto-merge, allowlist, thresholds, cadence, and PROPOSE_ONLY/AUTONOMOUS mode are all per-customer (§9.1, §8.3).

---

## 13. Configuration surface

A per-customer profile (home TBD in design — likely `config.sh` keys or a `hos-coordination.yaml` in the customer repo):

```yaml
customer: cps
protocol-version: "1.0"
mode: autonomous | propose-only        # auto-detected from server-side gate, overridable downward only
requester-allowlist: [cps-worker, cps-overseer, ScottThurlow]
security-sensitive-paths: ["audit/**", "**/auth/**", "scripts/oversight/gates/**"]
thresholds:
  per-task-tokens: 150000
  window-budget-tokens: 1500000
  approval-timeout: 12h
  triage-confidence-floor: 0.75
cadence: { floor: 15m, ceiling: 24h }    # probe cadence; model-gated by work + §8 budget
claim: { timeout: 45m, heartbeat: 15m }
breakers: { per-issue-failures: 3, blast-radius: { prs: 5, issues: 10, files: 25 }, dead-man: 6h }
```

- **R13.1 — `mode` can only be narrowed by config, never widened.** Config may force `propose-only` on a server-side-gated repo, but config **cannot** force `autonomous` on a repo where the gate isn't detected.

---

## 14. Phasing

| Phase | Contents | Gate to ship |
|---|---|---|
| **v1.0** | Probe + adaptive cadence (15m/24h), triage w/ confidence floor + allowlist, envelope v1.0, GitHub-as-DB + cold-start recovery, claim-then-verify + heartbeat, budget gates + default-deny, merge-authority matrix (PROPOSE_ONLY default; auto-merge where detected), embargo *routing*, circuit breakers, run ledger + shadow mode, multi-customer fairness. | Cold-start drill (M4) + a shadow-mode run on HOS's own repo + #152 server-side gate live on at least HOS. |
| **v2** | Cryptographic envelope signing, embargo-fix *automation*, external lock primitive (if claim-then-verify proves insufficient), non-GitHub transports, finer adaptive cadence (sub-hour where a customer opts in). | — |

---

## 15. Open items for the design phase

- **O1** — Config home: `config.sh` keys vs a dedicated `hos-coordination.yaml` per customer repo. (Leaning: in-repo YAML, so the customer owns its own profile and HOS reads it — consistent with "GitHub is the database.")
- **O2** — Instance-id scheme for the claim tiebreak (§7.1): hostname+pid is racy across machines; prefer a per-instance UUID minted at boot and carried in the claim envelope.
- **O3** — Exact server-side-gate detection probe (§9.1.1): protection-API read vs an active no-op-rejection canary. The canary is stronger (proves enforcement, not just configuration) but noisier.
- **O4** — Where the run ledger lives relative to `audit/oversight-log.jsonl`: same file, sibling file, or per-customer.
- **O5** — *(direction set, #254 feedback)* Token-estimation method (R8.1): a **cheap heuristic** from issue/diff size, changed-file count, blast radius, and historical cost of similar tasks — **no model pre-pass**, must itself be ~free. **Estimation error is acceptable** (err high; R8.6 re-asks on mid-flight overrun). Remaining design work is only *which* signals and the calibration constants, not whether to use a model.

---

## 16. Traceability to #254

| #254 element | Where addressed |
|---|---|
| Periodic check, model only on work | G1, §3, §10 |
| Token-burn estimation + significance gate | §8 (estimate-then-gate), O5 |
| Human-escalation context contract (#257) | §8.2 |
| Bidirectional comms protocol | G3, §4 |
| Issue triage {bug, feature, communication} | §5 |
| Bug handling (prioritize, fix in order) | §5.1, §7 |
| Locking + claim timeout | §7 |
| PR authorization by risk level | §9.1 |
| Decision #1 (≤MEDIUM auto-merge; security orthogonal) | §9.1 |
| Decision #2 (security embargo path) | §9.2 |
| Open Q: adaptive polling | §0, §10 |
| Open Q: spec home/format | §0 |
| Open Q: concrete defaults | §8.3 |
| Considerations #1–#11 | §3.1, §9.2, §6, §7, §8, §4, §5, §11, §11.2, §12, §10 (mapped inline) |
