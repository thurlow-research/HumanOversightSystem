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
| **Dependency on #152 (machine accounts)** | **Hard prerequisite for the *whole system* — two levels.** (1) **Global:** the entire unattended worker requires #152 to land first — the loop runs under the **worker/overseer machine accounts**, not the human, so without machine-account identity there is no compliant actor to run it. (2) **Per-repo:** auto-merge is additionally enabled only where server-side branch protection is **detected** active; otherwise that repo runs **PROPOSE_ONLY**. | The loop *being* an AI actor distinct from the human is the foundation (#152 / `AGENT-IDENTITY.md`), and auto-merge-≤MEDIUM is only a *boundary* if a bot can't bypass it. "Detected, not assumed" applies fail-closed / re-derive-don't-trust (DECISIONS D33/D37/D41). #152 ships first; then CPS joins in PROPOSE_ONLY and graduates when *its own* gate flips. |
| **Multi-customer scope** | **v1.** Per-customer budgets, round-robin, isolation, protocol versioning are in scope from the start. | CPS is the first real participant; retrofitting fairness/isolation onto a single-tenant loop is the expensive path. |
| **Fold in #131** (scheduled self-review backlog job) | **Subsumed** as a **scheduled self-review work source** (§3.2), not a standalone cron. | #131's "daily full self-review → file NEW ledger-deduped findings as issues" is the same shape as the unattended loop (cron, no-model-unless-work, budget-gated, ledger-deduped). Folding it in lets it inherit this loop's budget gate, observability, and kill switch instead of re-implementing them. **#131 closed as a duplicate of #254.** |

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
- **M6** — **Self-review finding burndown** (#131): the count of open model-produced findings trends *down* over time. A rising open-finding count is itself an alert signal, not just a number.

---

## 2. Personas & actors

| Actor | Identity | Role in the loop |
|---|---|---|
| **The worker loop** | machine-user **worker** (#152) | Opens PRs/branches, posts coordination replies, runs the build chain. **Never approves/merges.** |
| **The overseer** | machine-user **overseer** (#152) | Runs reviews, approves+merges SAFE/LOW–MEDIUM non-protected PRs *where server-side-gated*. Recommends-only above ceiling. |
| **The human (operator)** | `ScottThurlow` (admin) | Authorizes significant work, resolves features, handles embargoed security, holds the only `--admin` bypass + kill switch. |
| **The customer project** | its own repo + machine accounts | Files reports/questions, watches PR comments, receives release notifications. May be HOS itself (HOS dogfoods the protocol on its own repo). |

> **Identity is load-bearing, not cosmetic.** The whole merge-authority model rests on worker ≠ overseer ≠ human being *server-side distinguishable* (#152, `docs/AGENT-IDENTITY.md`). This PRD consumes that model; it does not re-specify it.

> **This protocol is the runtime for the Faberix maintainer roles (`docs/FABERIX-ROLES.md`, #167 — subsumed).** Faberix is the named autonomous HOS maintainer running under the **overseer** machine account; its three roles map directly onto sections here, so #254 is the implementation of #167 rather than a parallel design:
> - **R1 — validator tech-debt paydown** → the scheduled self-review work source (§3.2) with the three dispositions **fix / won't-fix+suppress / escalate** (R3.2.5).
> - **R2 — incoming-item triage** → triage (§5) + severity + benefit-≫-risk gate (§5.3). *The overnight loop was R2's prototype — now generalized and given the cost gate it lacked.*
> - **R3 — PR review** → the merge-authority matrix (§9.1): approve/merge what it may, escalate the rest.
>
> #167's bounding principles are already first-class here: #152 hard-prereq (§9.1, R13 detection), cost-gating (§1/§10), and machine-account accountability (§2). Its won't-fix→suppression mechanism is added below.

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

### 3.2 Work sources — inbound *and* scheduled self-review **[subsumes #131]**

The PROBE finds two kinds of work, both feeding the same triage + gate machinery:

1. **Inbound** — new/updated issues, PR comments, and coordination envelopes on the watched repos (the main flow above). This is *consuming* work others filed.

2. **Scheduled self-review** — HOS runs its own **full-corpus adversarial self-review** (`validate_self`, optionally cross-vendor) on a cadence and **files each NEW finding as a tracked issue**, which then re-enters triage like any other inbound work. This is *producing* work — continuous governance improvement decoupled from the release gate. **This work source is the whole of #131**, generalized into the unattended loop rather than a standalone cron.

   **Goal: burn the model-produced finding backlog toward zero.** The models keep surfacing real governance holes; the point of this source is to *drive that open set down*, not to generate noise. Two consequences: (a) self-review runs **sparingly** — it is expensive *and* noisy, so a tight cadence is counterproductive (see R3.2.2); and (b) the loop tracks the **open-findings count as a burndown metric** (M6) so progress toward zero is visible and a *rising* count is itself a signal.

- **R3.2.1 — Finding-fingerprint dedup is non-negotiable.** A self-review finding is filed **only if its fingerprint is not already in the ledger**. Reuse the existing disposition ledger keyed on `(sorted files, finding-class)` with a `filed:#N | fixed | noise` disposition; a finding whose fingerprint is already present is **never re-filed**. Without this the job files duplicates every run (the #131 critical requirement). The auto-file path records `filed:#N` the moment it files, so the same finding never re-surfaces.
- **R3.2.2 — Budget-gated, configurable cadence, default weekly.** Self-review is expensive *and* noisy, so its cadence is a **configurable knob (`self_review_cadence`) defaulting to weekly** — deliberately far slower than the token-free inbound probe (§10). It is **budget-gated like all model work (§8)**. The inbound-probe cadence and the self-review cadence are independent knobs. (Daily was considered and rejected as too expensive/noisy for the burndown goal; weekly is the v1 default, tunable per repo.)
- **R3.2.3 — Findings flow through normal triage.** A filed finding is triaged (`bug` / `spec-gap` / …) and handled by the same rules — including "no fix without a reproducing test" (R3.1.1) and the merge-authority matrix (§9.1). Self-review does not get a privileged fast path.
- **R3.2.4 — Governance issues are human-to-close.** The loop **files** findings autonomously but does **not auto-close** a filed governance finding when it stops reproducing — close is human-only (a finding can vanish from a fuzzed re-run without being genuinely resolved; see O6).
- **R3.2.5 — Three dispositions, and won't-fix → suppression ledger** *(Faberix R1, implements #133, subsumes #167)*. Every validator/self-review finding resolves to exactly one of **fix · won't-fix+suppress · escalate**. A **won't-fix** ruling writes a **scoped, accountable entry to a suppression ledger** so the validator/self-review **stops re-reporting it** — keyed like the dedup fingerprint `(sorted files, finding-class)`, with author + rationale + timestamp. This is what makes the M6 burndown actually *converge*: without suppression, won't-fix findings resurface every run and the open set never reaches zero. Suppression is **distinct from `scanner-fp`** (which fixes the heuristic) and from `noise` — it is an accountable *accepted-risk* record. **Won't-fix on certain classes is human-only** (security / privacy / license — see O10); the loop may suppress only the classes it is permitted to rule on, and escalates the rest.

This is the §0 "fold #131 in" decision: #131's standalone-cron design becomes one work source of the unattended worker, inheriting the loop's budget gate, ledger, observability, and kill switch instead of re-implementing them. **#167 (Faberix maintainer roles) folds in the same way** — its R1/R2/R3 are the §3.2 / §5 / §9.1 machinery, and its won't-fix→suppression mechanism is R3.2.5.

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

### 5.3 Severity triage & the benefit-≫-risk gate

Every actionable work item is severity-triaged, and every proposed change must clear a value/risk bar before the loop acts autonomously.

- **R5.3.1 — Severity on *every* actionable item.** Triage assigns a severity (`P0`–`P3`) to **every** bug, **feature request**, *and* self-review finding (#131) — not just bugs. Severity is recorded on the issue (label + envelope `priority`).
- **R5.3.2 — Priority-ordered handling.** Work is handled **highest-severity-first** within each customer. Bug fixing, the #131 burndown (M6), and feature queuing all draw from the same severity ordering. Severity also feeds the cadence priority-pin (§10.4): an open `P0` pins the probe to the floor.
- **R5.3.3 — Benefit-≫-risk gate.** The loop acts autonomously on a change **only when its expected benefit substantially outweighs the risk of the change** (benefit ≫ risk). "Risk of change" is the risk-assessor tier + blast radius + security-relevance (§9.1); "benefit" is severity + scope of what it fixes/adds. A high-severity fix with a small, low-risk diff clears easily; a low-severity / cosmetic change touching a high-risk or security-relevant surface does **not** — the risk of *making the change* can exceed the benefit of the change itself.
- **R5.3.4 — A benefit-≫-risk *rejection* goes to a human to finalize.** When the gate **rejects** a change (benefit does not clearly exceed risk), the loop does **not** silently drop or auto-close it. It routes the item to **human review to finalize** the rejection — labeled `needs_human`, carrying the full §8.2 escalation contract (problem + risk + background, the benefit-vs-risk analysis, options, and the loop's recommendation to *not* proceed). The human makes the final call; the loop never unilaterally buries valid work under a "not worth it" judgment.

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

**Config is layered so the shipped framework source is always *unconfigured*.** Three layers, resolved at load time (later overlays earlier):

1. **Shipped defaults (HOS-owned, in source).** A `hos-coordination.defaults.yaml` ships with the framework carrying **only defaults** — `enabled: false`, the §8.3 threshold profile, cadence bounds. It is **inert**: it turns nothing on. This is the layer that lives in the framework repo / a release.
2. **Live per-deployment config (NOT in the framework source).** Each deployment supplies its own config in a location **outside** the shipped source tree — the consumer repo's own PROJECT-owned area, or a local, **gitignored** path (the existing `.ai-local/` convention; never committed to the framework). This is where `enabled: true` and any real values live.
3. **Runtime overrides** — env / kill-switch / `enabled:false` short-circuit (R13.2).

**HOS's own dogfood config is layer 2, not layer 1** — it lives in HOS's deployment location (e.g. `.ai-local/hos-coordination.yaml`, gitignored), **never in the committed framework source**. Consequence: a `git grep 'enabled: *true'` over the framework source returns nothing, and a cut release never carries HOS's (or anyone's) live enablement. The source ships unconfigured-and-disabled; configuration is an act each deployment performs separately.

The schema (shown here as the shipped **defaults** — note `enabled: false`):

```yaml
customer: cps
enabled: false                          # OPT-IN, OFF BY DEFAULT — customer must explicitly turn it on (R13.2)
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
self-review: { cadence: weekly, cross-vendor: true }   # #131 burndown source (§3.2); expensive+noisy → sparing
severity-triage: { scheme: P0-P3, fix-order: highest-first }   # §5.3
claim: { timeout: 45m, heartbeat: 15m }
breakers: { per-issue-failures: 3, blast-radius: { prs: 5, issues: 10, files: 25 }, dead-man: 6h }
```

- **R13.1 — `mode` can only be narrowed by config, never widened.** Config may force `propose-only` on a server-side-gated repo, but config **cannot** force `autonomous` on a repo where the gate isn't detected.
- **R13.2 — Opt-in, disabled by default.** The unattended worker and the customer↔HOS coordination protocol are **off by default** for every repo, including HOS's own. `enabled: false` is the shipped default; a **customer must explicitly opt in** (set `enabled: true`) before any autonomous probe, triage, claim, or coordination action runs against their repo. Absence/ambiguity of the flag is read as **disabled** (fail-closed). Disable is always immediate (it composes with the §8.4 kill switch: kill-switch is the emergency stop, `enabled: false` is the steady-state default).
- **R13.3 — Source ships unconfigured; live config lives elsewhere.** The framework **source carries defaults only** (layer 1); all live configuration — including HOS's own dogfood enablement — lives in a **per-deployment location outside the shipped source** (layer 2: consumer PROJECT area or a gitignored `.ai-local/` path). The framework repo must never contain a committed `enabled: true` or any deployment's real config. This keeps releases inert (a fresh install is disabled until its operator configures it) and keeps each deployment's posture out of the shared source. Mirrors the existing CORE/PACK (HOS-owned, shipped) vs PROJECT (consumer-owned, never overwritten) layering.

---

## 14. Phasing

| Phase | Contents | Gate to ship |
|---|---|---|
| **v1.0** | Probe + adaptive cadence (15m/24h), triage w/ confidence floor + allowlist, envelope v1.0, GitHub-as-DB + cold-start recovery, claim-then-verify + heartbeat, budget gates + default-deny, merge-authority matrix (PROPOSE_ONLY default; auto-merge where detected), embargo *routing*, circuit breakers, run ledger + shadow mode, multi-customer fairness, **scheduled self-review work source (#131)** — exact-key ledger dedup, auto-file findings, **weekly (configurable)**, human-only close; **severity triage + priority-ordered fix (§5.3)**. | Cold-start drill (M4) + a shadow-mode run on HOS's own repo + #152 server-side gate live on at least HOS. |
| **v2** | Cryptographic envelope signing, embargo-fix *automation*, external lock primitive (if claim-then-verify proves insufficient), non-GitHub transports, finer adaptive cadence (sub-hour where a customer opts in). | — |

---

## 15. Open items for the design phase

- **O1** — *(direction set by R13.3)* Config home: layered — shipped `hos-coordination.defaults.yaml` (defaults only) + a per-deployment live config outside the source (consumer PROJECT area or gitignored `.ai-local/`). Remaining design detail: the exact live-config path + the resolution/merge order with `config.sh`, not *whether* to separate them.
- **O2** — Instance-id scheme for the claim tiebreak (§7.1): hostname+pid is racy across machines; prefer a per-instance UUID minted at boot and carried in the claim envelope.
- **O3** — Exact server-side-gate detection probe (§9.1.1): protection-API read vs an active no-op-rejection canary. The canary is stronger (proves enforcement, not just configuration) but noisier.
- **O4** — Where the run ledger lives relative to `audit/oversight-log.jsonl`: same file, sibling file, or per-customer.
- **O5** — *(direction set, #254 feedback)* Token-estimation method (R8.1): a **cheap heuristic** from issue/diff size, changed-file count, blast radius, and historical cost of similar tasks — **no model pre-pass**, must itself be ~free. **Estimation error is acceptable** (err high; R8.6 re-asks on mid-flight overrun). Remaining design work is only *which* signals and the calibration constants, not whether to use a model.
- **O6** — *(from #131)* **Fingerprint fuzz** on self-review findings (R3.2.1): the same logical finding can return with a slightly different file set / class wording → fingerprint miss → duplicate issue. Need a fuzzy-match step or a periodic human de-dup pass (relates to #78 cross-vendor fingerprint reconciliation). The exact-key ledger is the v1 floor; fuzzy-match is the hardening.
- **O7** — *(from #131)* **Auto-close policy** for filed governance findings: a finding whose underlying file changed such that it no longer reproduces — does its issue auto-close? v1 answer is **no** (R3.2.4, human-only close); O7 is whether a *suggested*-close signal (not an actual close) is worth adding later.
- **O8** — **Execution model** (flagged in review): is an "instance" a long-running process that heartbeats while working (§7.2), or a short-lived cron invocation that exits between polls? The 45m claim-timeout / 15m heartbeat assumes the former; the weekly self-review (§3.2) is naturally the latter. The loop likely needs **both** — a short-lived probe-and-dispatch invocation plus longer-lived per-task workers that heartbeat — which the §7 locking model must accommodate.
- **O9** — *(from #167(a))* **Suppression ledger scope** (R3.2.5): per-repo or shared across consumers? A shared ledger lets HOS suppress a known framework-level false positive once for everyone; a per-repo ledger keeps consumer accepted-risk decisions local. Likely both: a HOS-shipped baseline + a per-repo overlay.
- **O10** — *(from #167(b))* **Won't-fix human-only classes** (R3.2.5): which finding classes may the loop *never* autonomously won't-fix? Proposed floor: **security / privacy / license** are human-ruled-only (the loop escalates, never self-suppresses them). Confirm the list.
- **O11** — *(from #167(c))* **R3 auto-approve ceiling reconciliation.** #167 proposed Faberix R3 auto-approve at **LOW only**; #254 decision #1 locked the auto-merge ceiling at **≤MEDIUM** (§9.1). The PRD treats **§9.1 (≤MEDIUM, non-security, server-side-gated, benefit-≫-risk) as the governing answer**, superseding the more conservative #167 LOW-only proposal — but this is flagged for explicit human confirmation, since #167(c) was an open question pending review.

---

## 16. Traceability to #254

| #254 element | Where addressed |
|---|---|
| Periodic check, model only on work | G1, §3, §10 |
| Token-burn estimation + significance gate | §8 (estimate-then-gate), O5 |
| Human-escalation context contract (#257) | §8.2 |
| Scheduled self-review → file findings, ledger-dedup (#131, subsumed) | §3.2, R3.2.1, O6, O7 |
| Faberix maintainer roles R1/R2/R3 + won't-fix→suppression (#167, #133, subsumed) | §2 (Faberix note), R3.2.5, O9, O10, O11 |
| Bidirectional comms protocol | G3, §4 |
| Issue triage {bug, feature, communication} | §5 |
| Bug handling (prioritize, fix in order) | §5.1, §5.3, §7 |
| Severity triage on all classes + benefit-≫-risk gate + reject→human | §5.3 |
| Locking + claim timeout | §7 |
| PR authorization by risk level | §9.1 |
| Decision #1 (≤MEDIUM auto-merge; security orthogonal) | §9.1 |
| Decision #2 (security embargo path) | §9.2 |
| Open Q: adaptive polling | §0, §10 |
| Open Q: spec home/format | §0 |
| Open Q: concrete defaults | §8.3 |
| Considerations #1–#11 | §3.1, §9.2, §6, §7, §8, §4, §5, §11, §11.2, §12, §10 (mapped inline) |

---

## 17. Implementation task list

The work breakdown for building v1. Tracks the §14 phasing into concrete deliverables. **Opt-in / disabled-by-default (R13.2) is a cross-cutting constraint on every item below — nothing runs against a customer repo until they explicitly enable it.**

### 17.1 Documentation & control (the enable/disable surface)

- [ ] **T1 — Agent instructions for the customer↔HOS communication protocol.** Author the agent-facing spec (in `AGENTS.md` and/or the relevant `.claude/agents/` files) describing how agents participate in the protocol: the envelope format (§4), how to read/write `correlation-id`/`in-reply-to`, the triage classes (§5), claim-then-verify + heartbeat (§7), the escalation contract (§8.2), and the merge-authority boundaries (§9.1). This is the contract any compliant agent team implements to speak the protocol.
- [ ] **T2 — Control mechanism (enable/disable) + layered config.** Implement the opt-in switch (R13.2): the `enabled` flag + its fail-closed default, and the §8.4 kill switch. **Build the layered config resolver (R13.3):** shipped `*.defaults.yaml` (layer 1, unconfigured) overlaid by a per-deployment live config outside the source (layer 2, gitignored `.ai-local/` or consumer PROJECT area). Ensure the framework source stays free of any `enabled: true`; disable is immediate and unambiguous; absence = disabled.
- [ ] **T3 — Human-facing doc in `docs/`.** A new doc in the human docs section (e.g. `docs/UNATTENDED-WORKER.md` / `docs/COORDINATION-PROTOCOL.md`) so a human knows the subsystem exists, understands what it does autonomously, and can **enable/disable** it. **Must state plainly: off by default; the customer opts in; here is how to turn it on, how to turn it off, and how to hit the kill switch.** Cross-link from `docs/SETUP.md` and the runbook.

### 17.2 Core loop

- [ ] **T4 — Probe + adaptive cadence (§10)** — token-free GitHub poll, 15m/24h bounds, back-off, priority-pin; per-customer round-robin (§12).
- [ ] **T5 — Coordination envelope (§4)** — parse/emit, threading DAG, at-least-once idempotency, protocol-version negotiation, requester allowlist.
- [ ] **T6 — Triage (§5)** — classifier with confidence floor + asymmetric security detection; **severity triage P0–P3 (§5.3)**; benefit-≫-risk gate with reject→human.
- [ ] **T7 — State model & idempotent recovery (§6)** — GitHub-as-DB, labels/assignees/ledger; cold-start drill (M4).
- [ ] **T8 — Locking (§7)** — claim-then-verify, heartbeat, claim timeout, terminal-state release. *(Resolve O8 execution model first.)*
- [ ] **T9 — Budget & significance gates (§8)** — estimate-then-gate, per-task + per-window, default-deny, mid-flight overrun re-ask; wire to existing pager (R8.5).
- [ ] **T10 — Merge authority (§9.1)** — server-side-gate detection ("detected, not assumed"), the orthogonal tier × security matrix, PROPOSE_ONLY default.
- [ ] **T11 — Security embargo routing (§9.2)** — ack + route + `hos-embargo`; no public branch/PR/test.

### 17.3 Work sources & safety

- [ ] **T12 — Scheduled self-review source (§3.2, #131)** — `validate_self` auto-file mode, exact-key ledger dedup, weekly default cadence, human-only close, burndown metric (M6).
- [ ] **T13 — Circuit breakers (§11.1)** — per-issue failure cap, blast-radius caps, rate-limit backoff, max runtime, dead-man's-switch.
- [ ] **T14 — Observability (§11.2)** — run ledger (who/what/when/why/cost) + dry-run/shadow mode (default for a newly-opted-in customer).
- [ ] **T15 — Multi-customer fairness (§12)** — per-customer budgets, round-robin, isolation, global + per-repo kill switch.

> **Ship gate (§14):** the cold-start drill (M4) passes, a shadow-mode run on HOS's own repo looks correct, and #152 server-side enforcement is live on at least HOS — all before any repo flips `enabled: true` out of shadow mode.
