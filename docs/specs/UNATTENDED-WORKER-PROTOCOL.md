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

During the CPS field test we hand-rolled a session-only cron (every 20 min) that: polled `hos-coordination`-labelled issues → answered unanswered ones → watched the `feat/audit-healthcheck` review chain → on completion ran the oversight chain and either auto-merged-if-safe or opened a draft PR + `needs-human`. **It worked** — but everything was ad-hoc: NL-scraping to detect "already answered," no locking, no budget gate, no formal envelope, no observability, instance-local state that didn't survive a cold start.

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
- **NG3b** — Autonomous **releases**. Cutting/tagging/publishing a release is always human-approved (R9.4.1); the loop may prepare and escalate one, never cut it.
- **NG4** — Non-GitHub backends (GitLab/ADO). The protocol is GitHub-shaped in v1; the envelope is portable, the transport is not.
- **NG5** — Cross-instance leader election beyond claim-then-verify (no external lock service).

### 1.3 Success metrics

- **M1** — Zero duplicate-work incidents across concurrent instances over a 30-day window (locking correctness). Operational definition: see R6.1 — a duplicate-work incident is two distinct correlation-ids naming the same work item (not two pushes to the same branch, which is the idempotency mechanism working correctly).
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
   cron (15m floor) │  PROBE / DISPATCH  (stateless, short-lived)     │
   ───────────────► │  wakes, probes all repos (round-robin), claims  │
                    │  + dispatches any found work, then EXITS.       │
                    │  Holds no in-memory state; reconstructs         │
                    │  everything from GitHub on each invocation.     │
                    └───────────────┬─────────────────────────────────┘
                                    │ work claimed?  ── no ──► update cadence, exit
                                    │ yes
                                    ▼
                    ┌─────────────────────────────────────────────────┐
   model invoked    │  PER-TASK WORKER  (bounded long-lived)          │
   from here ─────► │  one worker per claimed task; heartbeats while  │
                    │  working; exits on completion or timeout.       │
                    └───┬───────────┬───────────┬───────────┬──────────┘
                        │           │           │           │
                     TRIAGE  (confidence floor + requester allowlist)
                        │  classify: bug | feature | communication |
                        │            security-report | spec-gap | dup |
                        │            invalid         (low-conf → human)
                        │           │           │           │
              communication      bug      security-report  feature / spec-gap
                        │           │           │           │
                        ▼           ▼           ▼           ▼
                   answer via   budget     EMBARGO PATH   QUEUE for
                   envelope     gate →     (human + private  human review
                                build      channel; never    (no auto-build)
                                chain →    public auto-fix)
                                merge
                                authority
                                matrix
```

> **Execution model (A1):** Two tiers. (1) **Stateless short-lived cron** — the probe/dispatch tier: wakes, probes all customer repos, claims+dispatches any found work, then exits. It holds no in-memory state and reconstructs everything from GitHub on every invocation. (2) **Bounded long-lived per-task workers** — one worker per claimed task: runs the triage→gates→merge chain for that task, heartbeats the claim envelope while running, exits on completion or timeout. The heartbeat mechanism (§7) is designed around this split — staleness is computed from the GitHub-observable claim envelope timestamp, not from process liveness.

### 3.1 The pipeline is an orchestrator *into* the gates, never a bypass — **[locked in #254 #1]**

An autonomous bug fix is exactly: **claim → branch → reproducing test (red) → coder → risk-assessor → review chain → oversight-evaluator → merge-authority decision**. Identical to a human-initiated change. The loop adds *initiation and shepherding*; it removes nothing.

- **R3.1.1** — **No fix without a reproducing test first.** For **software defects with an executable test suite**: the loop must produce a test that *fails* against the bug before any fix, and *passes* after. A fix branch without a red→green test artifact is a hard reject. For **governance / doc / config / spec-gap bug classes** (where a runnable test is not applicable): the loop must produce a defined **evidence-of-fix artifact** — a structured before/after assertion (e.g. a diff showing the old and new state, a validator output pair, or a checklist of the specific items that changed) — before the fix may be merged. The minimum required verification artifact by triage class is: `bug`→red/green test; `spec-gap`→before/after spec diff + human confirmation; `governance`/`config` → before/after structured assertion. Absence of the appropriate artifact for the class is a hard reject equivalent to a missing test.
- **R3.1.2** — The loop never calls a gate with relaxed parameters. It uses the same `run_validators.sh`, `run_second_review.sh`, and `oversight-evaluator` invocations a human would.

### 3.2 Work sources — inbound *and* scheduled self-review **[subsumes #131]**

The PROBE finds two kinds of work, both feeding the same triage + gate machinery:

1. **Inbound** — new/updated issues, PR comments, and coordination envelopes on the watched repos (the main flow above). This is *consuming* work others filed.

2. **Scheduled self-review** — HOS runs its own **full-corpus adversarial self-review** (`validate_self`, optionally cross-vendor) on a cadence and **files each NEW finding as a tracked issue**, which then re-enters triage like any other inbound work. This is *producing* work — continuous governance improvement decoupled from the release gate. **This work source is the whole of #131**, generalized into the unattended loop rather than a standalone cron.

   **Goal: burn the model-produced finding backlog toward zero.** The models keep surfacing real governance holes; the point of this source is to *drive that open set down*, not to generate noise. Two consequences: (a) self-review runs **sparingly** — it is expensive *and* noisy, so a tight cadence is counterproductive (see R3.2.2); and (b) the loop tracks the **open-findings count as a burndown metric** (M6) so progress toward zero is visible and a *rising* count is itself a signal.

- **R3.2.1 — Finding-fingerprint dedup is non-negotiable.** A self-review finding is filed **only if its fingerprint is not already in the ledger**. Reuse the existing disposition ledger keyed on `(sorted files, finding-class)` with a `filed:#N | fixed | noise` disposition; a finding whose fingerprint is already present is **never re-filed**. Without this the job files duplicates every run (the #131 critical requirement). The auto-file path records `filed:#N` the moment it files, so the same finding never re-surfaces.
- **R3.2.2 — Budget-gated, configurable cadence, default weekly, hard floor 24h.** Self-review is expensive *and* noisy, so its cadence is a **configurable knob (`self_review_cadence`) defaulting to weekly** — deliberately far slower than the token-free inbound probe (§10). It is **budget-gated like all model work (§8)**. The inbound-probe cadence and the self-review cadence are independent knobs. (Daily was considered and rejected as too expensive/noisy for the burndown goal; weekly is the v1 default, tunable per repo.) **Hard floor: values below 24h are rejected at config-load with a fatal error** — a sub-daily self-review cadence is always counterproductive and must never be silently accepted.
- **R3.2.3 — Findings flow through normal triage.** A filed finding is triaged (`bug` / `spec-gap` / …) and handled by the same rules — including "no fix without a reproducing test" (R3.1.1) and the merge-authority matrix (§9.1). Self-review does not get a privileged fast path.
- **R3.2.4 — Governance issues are human-to-close.** The loop **files** findings autonomously but does **not auto-close** a filed governance finding when it stops reproducing — close is human-only (a finding can vanish from a fuzzed re-run without being genuinely resolved; see O6).
- **R3.2.5 — Three dispositions, and won't-fix → suppression ledger** *(Faberix R1, implements #133, subsumes #167)*. Every validator/self-review finding resolves to exactly one of **fix · won't-fix+suppress · escalate**. A **won't-fix** ruling writes a **scoped, accountable entry to a suppression ledger** so the validator/self-review **stops re-reporting it** — keyed like the dedup fingerprint `(sorted files, finding-class)`, with author + rationale + timestamp. This is what makes the M6 burndown actually *converge*: without suppression, won't-fix findings resurface every run and the open set never reaches zero. Suppression is **distinct from `scanner-fp`** (which fixes the heuristic) and from `noise` — it is an accountable *accepted-risk* record. **Won't-fix on certain classes is human-only** (security / privacy / license — see O10); the loop may suppress only the classes it is permitted to rule on, and escalates the rest.
- **R3.2.6 — Suppressions are time-bounded, not permanent** *(subsumes #168 suspension lifecycle)*. A suppression entry carries an **explicit approver + timestamp + a review/removal target date**, and is subject to an **active nag** as that date approaches and a **date-triggered auto-removal or escalation** when it passes — at which point the finding **re-surfaces** for a fresh ruling. This keeps the suppression set convergent (accepted-risk decisions expire and get re-examined rather than silently becoming permanent debt). The same lifecycle governs any validator *suspension* the loop relies on: explicit merge-approval, timestamp, target-removal, nag, and date-triggered auto-removal/escalation.

  **Nag mechanism:** N days before the expiry date (configurable, default 14 days), the loop posts a `type: question` envelope on the suppression issue, labeled `needs-human`, carrying: the original suppression rationale, the approver who set it, the expiry date, and a request to renew or let it expire. The `nag` and `suppression-expired` types are added to the envelope `type` vocabulary (§4.1).

  **Expiry handling:** when a suppression passes its expiry date without renewal, the loop files/updates an issue labeled `suppression-expired` with an explicit back-reference (original issue number + rationale + approver + expiry date). The expired suppression is routed **directly to the human review queue** (`needs-human`) — it is **NOT** run through autonomous triage and the loop does **NOT** auto-claim or auto-fix it. The finding re-surfaces as human-assigned work.

This is the §0 "fold #131 in" decision: #131's standalone-cron design becomes one work source of the unattended worker, inheriting the loop's budget gate, ledger, observability, and kill switch instead of re-implementing them. **#167 (Faberix maintainer roles) folds in the same way** — its R1/R2/R3 are the §3.2 / §5 / §9.1 machinery, and its won't-fix→suppression mechanism is R3.2.5.

---

## 4. The coordination envelope — **[#254 consideration #6]**

NL-scraping ("have I already answered this?") was the single biggest pain in the field test. v1 replaces it with a **machine-readable envelope**: a fenced YAML block in the issue/comment body, plus a signature marker line.

### 4.1 Format

````
```hos-envelope
protocol-version: "1.0"
type: report | question | answer | release-notification | claim | heartbeat | ack | nag | suppression-expired
from: hos-overseer | hos-worker | cps-worker | human
to: hos | cps | <repo-slug>
correlation-id: "<uuid of the originating message>"
in-reply-to: "<correlation-id this responds to>"   # omit on originators
priority: P0 | P1 | P2 | P3
signature: "<marker — see §4.3>"
```
<!-- 🤖 [AI: claude] hos-envelope v1.0 -->
````

- **R4.1.1** — Every autonomous message HOS posts carries an envelope. A human-authored message *may* omit it; the loop treats envelope-less inbound as `from: human, type: question` by default and routes to triage. Before routing an envelope-less comment to triage, the loop MUST check: (a) if the issue is in a terminal label state (`needs-human`, `hos-embargo`) or is closed → ignore the envelope-less comment entirely; (b) if the comment matches the configurable acknowledgment-pattern list (e.g. thanks / LGTM / looks good / closing / never mind / no action) → log and do not triage; (c) per-thread, if the loop has already posted one clarification request with no structured response → escalate once and wait, never post a second clarification request. This prevents runaway comment loops and ensures R10.4's priority-pin is not held open by chatter.
- **R4.1.2** — `correlation-id` + `in-reply-to` give a threading DAG. "Already answered?" becomes: *does an `answer` envelope exist whose `in-reply-to` equals this message's `correlation-id`?* — a deterministic lookup, never NL inference.
- **R4.1.3** — **At-least-once idempotency.** Cron polling *will* double-deliver. Every consumer keys on `correlation-id`; processing the same id twice is a no-op. (GitHub is the dedup store — see §6.)
- **R4.1.4 — `hos-coordination` label = the cheap probe flag.** Every issue/comment that carries an `hos-envelope` block is also tagged **`hos-coordination`**. This is what keeps the probe **token-free (§10)**: the probe finds agent-to-agent messages with a *label/search query* (`label:hos-coordination` + `updated:>last-poll`) instead of fetching and parsing every body. The label says "there is a message here"; the envelope (body) carries the routing detail (`type`/`from`/`to`/`correlation-id`). A coordination item is fully processed only when its envelope is parsed, but it is *discovered* by the label. The label is created in every participating repo as part of onboarding (T2). **The loop MUST verify that the `hos-coordination` label was added by an allowlisted account** (read the label event actor from the GitHub API) before parsing the envelope body — a label added by a non-allowlisted actor is skipped and logged. (This adds a small API cost to the probe.)

### 4.2 Protocol versioning — **[#254 consideration #10]**

- **R4.2.1** — `protocol-version` is mandatory. HOS and a given customer may run different releases. A consumer that receives a `protocol-version` it doesn't support posts a `type: ack` with an `unsupported-version` error and routes to human — it never silently mis-parses.
- **R4.2.2** — Version negotiation is **floor-based**: both sides operate at `min(supported)`. Major-version mismatch (`2.x` ↔ `1.x`) → human.

### 4.3 Authentication & the requester allowlist — **[#254 consideration #7]**

- **R4.3.1** — On a public repo, a random account must not be able to drive the loop. The loop honors envelopes/commands only from a **per-repo requester allowlist** (the customer's machine accounts + named human operators). The allowlist check MUST be performed against the **GitHub-API-verified author** (`comment.user.login` / `issue.user.login`) — NOT the envelope `from:` field. The envelope `from:` field is used for **routing only**, and only after the GitHub-author allowlist check has already passed. A message whose GitHub-API-verified author is off-allowlist is acknowledged and routed to human, never actioned autonomously — regardless of what the envelope `from:` field claims.
- **R4.3.2** — The `signature` marker is an integrity hint, **not** a cryptographic guarantee in v1 (GitHub identity via `comment.user.login` is the actual authn). It exists so a malformed/spoofed body fails the allowlist check loudly. (Signed commits/cryptographic envelope signing is a v2 hardening.)

---

## 5. Triage — **[#254 consideration #7]**

The **first** action on any found work. Misclassifying a feature as a bug and auto-"fixing" it is the expensive failure, so triage fails toward the human.

### 5.1 Classes

`bug` · `feature` · `communication` · `security-report` · `spec-gap` · `duplicate` · `invalid`

| Class | Autonomous handling | Minimum verification artifact (R3.1.1) |
|---|---|---|
| **bug** | Prioritize → claim → fix in priority order (§3.1, §7). | Red/green test (executable test suite). |
| **communication** | Answer via envelope (§4); orchestrate analysis agents if needed. | N/A — no code change. |
| **security-report** | **Embargo path only** (§9). Never public auto-fix. | N/A — human-driven. |
| **feature** | **Queue for human review.** No auto-build. | N/A — no autonomous action. |
| **spec-gap** | File/route to human as a spec issue (the spec-red-team flow); no auto-build. | Before/after spec diff + human confirmation. |
| **governance** / **config** | Route to human; no autonomous close. | Structured before/after assertion (diff + validator output pair). |
| **duplicate** | Link to canonical, close with envelope; no work. | N/A — no code change. |
| **invalid** | Acknowledge, request clarification or close per policy; no work. | N/A — no code change. |

### 5.2 Confidence floor

- **R5.2.1** — Triage emits a confidence score. **Below the floor (default 0.75) → route to human.** A low-confidence classification is never actioned autonomously.
- **R5.2.2** — `security-report` detection is **asymmetric**: any signal of a vulnerability (even low-confidence) forces the embargo path. False-positive embargo (a human glances and waves it through) is cheap; false-negative public auto-fix is catastrophic.

### 5.3 Severity triage & the benefit-≫-risk gate

Every actionable work item is severity-triaged, and every proposed change must clear a value/risk bar before the loop acts autonomously.

- **R5.3.1 — Severity on *every* actionable item.** Triage assigns a severity (`P0`–`P3`) to **every** bug, **feature request**, *and* self-review finding (#131) — not just bugs. Severity is recorded on the issue (label + envelope `priority`).
- **R5.3.2 — Priority-ordered handling.** Work is handled **highest-severity-first** within each customer. Bug fixing, the #131 burndown (M6), and feature queuing all draw from the same severity ordering. Severity also feeds the cadence priority-pin (§10.4): an open `P0` pins the probe to the floor.
- **R5.3.3 — Benefit-≫-risk gate (computable).** The loop acts autonomously on a change **only when its expected benefit substantially outweighs the risk of the change**. The gate is computed as a coarse matrix function — unambiguous enough to write a test case against:

  | Severity | Risk tier ≤ MEDIUM | Risk tier HIGH+ |
  |---|---|---|
  | **P0 / P1** (critical/high severity) | **ACT** autonomously (proceed to claim+fix) | **ESCALATE** to human |
  | **P2 / P3** (medium/low severity) | **ACT** autonomously only if blast-radius also ≤MEDIUM | **ESCALATE** to human |

  **Hard overrides (always force ESCALATE/HUMAN regardless of the matrix above):**
  - Security-relevance (any flag → human, per §9.1 and R9.1.2)
  - Protected-surface match (§9.1 R9.1.3 → human)
  - Any triage class other than `bug` or `communication` (feature / spec-gap / security-report → human per §5.1)

  "Blast-radius" for the P2/P3 ≤MEDIUM row: ≤ the per-run caps in §11.2 (5 PRs / 10 issues / 25 files). "Security-relevance" and "protected-surface" are defined in R9.1.2 and R9.1.3 respectively. This matrix is the authoritative definition for test purposes.
- **R5.3.4 — A benefit-≫-risk *rejection* goes to a human to finalize.** When the gate **rejects** a change (benefit does not clearly exceed risk), the loop does **not** silently drop or auto-close it. It routes the item to **human review to finalize** the rejection — labeled `needs-human`, carrying the full §8.2 escalation contract (problem + risk + background, the benefit-vs-risk analysis, options, and the loop's recommendation to *not* proceed). The human makes the final call; the loop never unilaterally buries valid work under a "not worth it" judgment.

---

## 6. State model — GitHub *is* the database — **[#254 consideration #3]**

No hidden instance-local state. Claims, the token ledger, conversation threads, and done/not-done all live in issues/labels/PRs, so any instance reconstructs from a cold start.

- **R6.1** — **Idempotent recovery via correlation-id-keyed artifact naming.** Every artifact a worker produces is named by `correlation-id`: branch name = `hos/auto/<correlation-id>`, draft-PR title and answer-envelope likewise keyed by the same id. Before doing work, an instance checks "does a branch / draft-PR / answer-envelope already exist for this `correlation-id`?" If yes, it resumes/skips rather than redoing. This is what makes a reaped-mid-work claim safe to re-pick-up, and it is the M1 guarantee: a double-dispatch produces **ONE** artifact (second push is a no-op / fast-forward) because both instances produce the same deterministic artifact name. A "duplicate-work incident" (M1) is operationally defined as: two distinct `correlation-id`s naming the same underlying work item (the same issue/PR being worked concurrently under two different ids), observable as two distinct `hos/auto/<id>` branches open against the same source issue. A second push to the same `hos/auto/<correlation-id>` branch (fast-forward) is NOT a duplicate-work incident — it is the idempotency mechanism working correctly.

  **Cold-start recoverable states (M4):** the drill must demonstrate that an instance interrupted at any of these points can be picked up cleanly by a fresh instance:

  | Interrupted at | Recovered state |
  |---|---|
  | After claim posted, before triage | Re-triage from scratch (claim envelope still present) |
  | After triage, before branch created | Re-create branch (idempotent; same correlation-id) |
  | After branch created, before PR opened | Open PR (idempotent; branch already exists) |
  | After PR opened, before gates run | Re-run gates (idempotent; PR already exists) |
  | After gates, before merge decision | Re-read gate results from PR; re-decide |
  | After merge decision, before merge | Re-attempt merge (idempotent if already merged) |
- **R6.2** — **No external datastore in v1.** Labels, assignees, issue/PR bodies, and a committed run-ledger file are the entire persistence layer. The canonical label set (all **hyphen-case**, matching the existing repo convention — the human↔AI labels `needs-ai` / `needs-human` are the *already-defined* repo labels, reused, not new): `hos-coordination` (an envelope is present — §4.1.4), `hos-claimed`, `hos-in-progress`, `hos-budget-gated`, `hos-embargo`, `hos-halt`, `needs-human` (AI→human), `needs-ai` (human→AI go-signal). New `hos-*` labels are created per repo at onboarding (T2); `needs-ai`/`needs-human` already exist.
- **R6.3** — **Cold-start drill (M4)** is a release gate: destroy an instance mid-task; a fresh instance must reach a correct, non-duplicating state from GitHub alone.

---

## 7. Locking, claims & heartbeat — **[#254 consideration #4]**

The lock is racy on a polled medium: two instances polling the same window can both "claim." v1 uses **claim-then-verify** plus a **heartbeat**.

> **Claim-then-verify is a contention-reducer, not mutual exclusion.** GitHub has no atomic test-and-set; search and label indices are not read-your-writes consistent, so two instances can both "claim" and both "verify." The correctness guarantee for M1 (zero duplicate work) does not come from the claim lock — it comes from **R6.1 correlation-id-keyed artifact naming** (branch = `hos/auto/<correlation-id>`, so a double-dispatch produces one artifact, the second push being a no-op). Where correctness depends on read-your-writes consistency, the worker MUST read the authoritative REST object by id — not query the search index.

- **R7.1 — Claim-then-verify.** To claim: each instance generates a **UUIDv4 at startup as its instance-id** (hostname+pid MUST NOT be used — they collide at PID 1 in containers). The instance-id is carried in the `type: claim` envelope. Post the claim (tag `hos-claimed` + self-assign) → wait a **jittered delay** (default 30–90s) → re-read the issue by id (REST, not search). If multiple claims exist, **lowest instance-id wins**; losers release immediately.
- **R7.2 — Heartbeat (claim envelope re-stamp).** A live per-task worker **re-stamps the claim envelope's timestamp every ≤15 min** by posting an updated `type: heartbeat` envelope. Staleness is computed by ANY instance from the claim envelope's `updated_at` — a GitHub-observable timestamp — NOT from process liveness. `claim_timeout = 45m` corresponds to 3 missed re-stamps. A per-task worker MUST post its **first heartbeat within one `heartbeat_interval` of claiming** (< 15 min) — a claim with no first heartbeat within that window is treated as a crash-before-first-heartbeat and is auto-released.
- **R7.3 — Claim timeout.** A claim whose envelope `updated_at` is more than **45 min** old (3 missed beats) is **stale** and may be re-picked-up by any instance (which first runs the §6.1 idempotency check). Default: `claim_timeout = 45m`, `heartbeat_interval = 15m`.
- **R7.4 — Release on terminal state.** Merge, escalation, or per-issue failure-cap hit all release the claim (remove `hos-claimed`, unassign) and record the outcome in the ledger.

---

## 8. Significance & budget gates — **[#254 consideration #5]**

"Significant" is **two-dimensional**: a per-task estimate *and* a cumulative per-window budget (a quiet night of many small tasks adds up). Both gated; plus a hard kill switch.

> **Estimate-then-gate, never burn-then-discover.** The failure mode we are designing *out* is: a single task quietly consumes the whole budget, then everything else grinds to a halt with no warning. So the estimate is computed **before** any significant model work and the permission ask happens **up front**. The estimate is a cheap guardrail, **not** precise accounting — **estimation error is acceptable** (we err high and re-ask if a task blows past its estimate mid-flight; see R8.6). A rough-but-early number that prevents a runaway beats a precise one that arrives after the tokens are gone.

- **R8.1 — Per-task estimate, computed first.** Before invoking *any* significant model work on a unit, the loop estimates token burn from cheap signals (issue/diff size, changed-file count, blast radius, historical cost of similar tasks — itself ~free, no model pre-pass required; see O5). If `estimate > per_task_threshold` → **create a human-permission request** (an issue/comment envelope, `type: question`, the §8.2 escalation-comms contract) and **block that task** until approved. The estimate gate runs *ahead of* the spend, never after.
- **R8.2 — Per-window budget (append-only ledger, conflict-free).** A cumulative ledger per `(customer, window)`. When cumulative spend would exceed `window_budget`, **all further significant work in the window is gated**, even individually-small tasks. **Ledger design:** the token/budget ledger MUST be append-only per-task cost records, each keyed by `correlation-id` (conflict-free — N instances append distinct keys, never mutate a shared counter). The per-(customer, window) total is computed by **summation at read time** across all records in the window. Per-run cost files are named by `<instance-id>-<timestamp>.jsonl` with a manifest file listing them; the budget and blast-radius checks aggregate across all per-run files in the rolling window. This eliminates git write-conflicts on the ledger. The budget ceiling is a **soft ceiling with headroom**: estimation error (R8.1) is explicitly acceptable and the loop errs high; a task that runs slightly over estimate does not become a protocol violation (R8.6 re-asks for the overrun).
- **R8.3 — Default-deny on timeout.** Silence ≠ yes. An unanswered permission request past its deadline (default **12h**) is **denied**; the task is left for the human with a `needs-human` label. (Tunable, but never defaults to auto-approve.)
- **R8.4 — Hard kill switch.** A single human-flippable control (a repo-level label/file, e.g. `hos-halt`, checked at the top of every cycle) stops all autonomous action immediately. Probe may continue; *action* halts.
- **R8.5 — Wire to existing alerting.** Cost-runaway / budget-exceeded / kill-switch events fire the existing SMS pager / alerting path, not just the ledger.
- **R8.6 — Mid-flight overrun re-ask.** Because the estimate is deliberately rough (R8.1), a task that exceeds its estimate *while running* is **paused at the next gate boundary** and re-submitted for permission with the revised number — it does not silently run past its approved budget. Erring high on the initial estimate makes this the exception, not the rule.

- **R8.7 — Definition of "significant model work."** The budget gate (R8.1) applies to **GATED** work; cheap/bounded operations are **UNGATED** and may run even when the budget is exhausted. Classification:

  | Category | Examples | Budget-gated? |
  |---|---|---|
  | **GATED** | Full build-chain execution (coder + risk-assessor + review chain + second review), scheduled self-review run, cross-vendor validation | **Yes** — requires estimate + gate before starting |
  | **UNGATED** (cheap/bounded) | Triage classification, envelope parsing, token estimation, drafting an escalation or `needs-human` message, heartbeat posting, label operations | **No** — a budget-exhausted loop MUST still be able to triage, estimate, and communicate |

  A budget-exhausted loop does not go silent — it continues UNGATED operations so it can inform the human of the situation (R8.2.1) and manage its label/claim state. It simply does not start new GATED work.

### 8.2 Escalation communication contract — **[#257]**

The human reviewing an escalation **often lacks context**. Every escalation, permission request, and `needs-human` hand-off the loop produces — §8 budget asks, §9 PROPOSE_ONLY / HIGH-tier escalations, embargo routing (§9.2), default-deny notifications (R8.3) — **must** carry, in this order:

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

Two **orthogonal** gates. Auto-merge **iff** `(tier ≤ MEDIUM) AND (not security-relevant) AND (not protected-surface) AND (full PROCEED) AND (server-side gate detected active for this repo)`. The security override, the protected-surface override, and the server-side requirement each independently beat the tier ceiling.

| Risk tier | Security-relevant? | Protected surface? | Server-side gate? | Outcome |
|---|---|---|---|---|
| SAFE / LOW / MEDIUM | no | no | **yes** | **Auto-merge** (overseer) |
| SAFE / LOW / MEDIUM | no | no | no | **PROPOSE_ONLY** — draft PR + `needs-human` |
| SAFE / LOW / MEDIUM | **yes** | any | any | **Human** — touches a security subsystem |
| SAFE / LOW / MEDIUM | any | **yes** | any | **Human** — touches a protected governance surface |
| HIGH / CRITICAL | any | any | any | **Human** — escalate, never auto-merge |
| any | any | any | gate **not detected** | **PROPOSE_ONLY** (capability detected, not assumed) |

- **R9.1.1 — Capability is detected, not assumed; re-checked immediately before merge.** Per repo, the loop probes that server-side branch protection is genuinely active (read the protection API *and* confirm the overseer account lacks the standing to bypass it) before enabling auto-merge for that repo's config. The cached detection result enables AUTONOMOUS mode in the config — it does **NOT** substitute for a pre-merge re-check. Branch-protection status AND the overseer account's bypass standing MUST be re-queried from the GitHub API **immediately before each merge attempt**. A failed pre-merge re-check forces immediate downgrade to PROPOSE_ONLY for that merge. Detection MUST also verify that the overseer's approval is actually ACCEPTED as a valid review under the repo's branch-protection rules (required-approvals count, CODEOWNERS, dismiss-stale-on-push) and that the overseer can merge after self-approving; if unverifiable or false → PROPOSE_ONLY.
- **R9.1.2 — "security-relevant" is a property of the change, not the tier.** Touching `audit/`, auth, secrets, the gate scripts themselves, or any path on the per-repo `security-sensitive-paths` config list forces the human gate regardless of tier. This list is per-repo and is NOT the framework-canonical protected-surface list (R9.1.3).
- **R9.1.3 — Framework-canonical protected-surface carve-out (human always, regardless of tier).** A change matching a path in the **framework-canonical protected-surface glob set** from `AGENT-IDENTITY.md §9.0` routes to **HUMAN** regardless of computed risk tier, security-relevance, or any other gate. The framework-canonical set is the source of truth (reproduced here for reference, but `AGENT-IDENTITY.md §9.0` governs):

  ```
  .claude/agents/**          AGENTS.md
  contract/**                docs/AGENTS.md
  docs/AGENT-IDENTITY.md     docs/METHODOLOGY.md
  docs/FABERIX-ROLES.md      docs/CROSS-REPO-CONDUCT.md
  bootstrap/**               scripts/framework/**
  scripts/oversight/gates/** scripts/oversight/run_validators.sh
  scripts/oversight/validators/schema.py
  .github/CODEOWNERS         .github/workflows/**
  ```

  This set is **framework-canonical** — it is NOT the per-repo `security-sensitive-paths` (R9.1.2), and it is **NOT downward-overridable by config** (a deployment operator cannot remove paths from it). The rationale: the self-review work source (§3.2) routinely produces findings that touch governance surfaces. Without this carve-out, the loop could quietly approve and merge changes that weaken its own controls — the specific invariant identified in `AGENT-IDENTITY.md §9.0` and a consequence of #152. This is a #152 §9.0 invariant: the surfaces that define the controls can never be loosened on the controls' own say-so.

### 9.2 Security embargo path — **[locked in #254 #2]**

A publicly-filed vulnerability must **never** get a public auto-fix — a public PR telegraphs the exploit before it's patched.

- **R9.2.1** — `security-report` triage → **acknowledge** (envelope, no detail) → **route to a human + private channel** → fix under **embargo** with coordinated disclosure. No public branch, no public PR, no public test that reveals the vector. **"Private channel" is deployment-configured** (e.g. a private GitHub Security Advisory, a private Slack channel, or a private repo) — the specific channel is specified in the governance config (layer 2a) for each deployment; HOS does not hard-code the channel type.
- **R9.2.2** — The loop's *only* autonomous action on a security report is the ack + route + `hos-embargo` label. Everything else is human-driven in v1.

### 9.3 Human-review queue convention — **[subsumes #156, #203]**

When a change needs human sign-off (PROPOSE_ONLY mode, above-ceiling tier, security-relevant, or a benefit-≫-risk rejection), the loop does not leave **bare commits on a branch** — it presents a reviewable queue:

- **R9.3.1 — Draft PR + `needs-human` tracking issue (the queue).** The loop opens a **draft PR** (reviewable diff + inline threads, not mergeable) and a **`needs-human` tracking issue** referencing it, carrying the §8.2 escalation contract plus an explicit **disposition menu** (approve / request change X / reject). The set of open `needs-human` issues *is* the human review queue. *(#156)*
- **R9.3.2 — `draft` has one meaning: "awaiting human."** Draft status = AI work done and self-validated, awaiting the human. *(Resolves #203 ambiguity #1 — option (b); O12 ratified.)* The loop MUST distinguish its **own** draft PRs (opened by the worker account, carrying an envelope, labeled `hos-coordination`) from human-opened draft PRs. The loop MUST NOT treat a human's in-progress draft PR as "AI work awaiting human" — a human draft is invisible to the queue convention and must not be touched by the loop.
- **R9.3.3 — `needs-ai` is the human's "go" signal.** The human responds by adding **`needs-ai`** to the linked issue with a disposition (and/or GitHub Approve). `needs-human` = AI→human; `needs-ai` = human→AI. The loop never marks a PR ready or merges until `needs-ai` is present. Both labels defined in every participating repo. *(#203)*
- **R9.3.4 — Who merges is governed by §9.1, not by the queue; formal PR approval is required.** On `needs-ai` signal: in **AUTONOMOUS** mode for a change the matrix permits (≤MEDIUM, non-security, non-protected-surface, server-side-gated), the loop MUST verify that a GitHub PR Review in **APPROVED** state exists on the PR, submitted by an allowlisted human account, before marking ready or merging. The `needs-ai` label authorizes the loop to solicit/proceed-with that review — it does NOT substitute for a formal PR approval. No formal PR approval in APPROVED state → the loop requests one and does not merge. In **PROPOSE_ONLY** mode, above the ceiling, or on a security-relevant/protected-surface change, the loop marks ready and **leaves the merge to the human**. *(Resolves #203 question 2.)*
- **R9.3.5 — No "(DRAFT)" in PR titles.** Rely on GitHub's draft badge; a "(DRAFT)" title string goes stale when the PR is readied. *(#203)*

### 9.4 No autonomous releases

- **R9.4.1 — Automation never creates a release without human approval.** Cutting, tagging, or publishing a **release** is **always** human-gated — independent of risk tier, merge mode, or server-side-gate status. Even in full AUTONOMOUS mode with ≤MEDIUM auto-merge, the loop may open/merge change PRs but **must not** run the release-cut path, push a release tag, or publish release notes without explicit human approval. A release bundles many changes and is the highest-blast-radius, hardest-to-reverse, outward-facing action in the system; it sits above the auto-merge ceiling by definition. The loop may *prepare* a release (draft notes, open a release PR) and **escalate it for human approval** (§8.2 contract), but the cut itself is a human act.

---

## 10. Adaptive polling — **[#254 consideration #11]**

The probe is a couple of GitHub API calls with **no model invocation** — cadence costs API quota, not tokens. **Cadence governs latency + API spend; the budget gate governs token spend — two independent knobs.** The cron fires the probe at the floor; **the model only wakes when the probe finds work**, so a tight probe cadence is cheap.

- **R10.1 — Bounds.** `floor = 15m`, `ceiling = 24h` (daily). The probe runs as often as every 15 min on an active repo; back-off only stretches the *probe* interval for dormant repos to save API quota — it never delays a model response to found work below the budget gate.
- **R10.1b — Probe by REST list or batched GraphQL — NOT the Search API.** The token-free hot-path probe runs **only after the R13.4 activation check has passed** — if the activation file is absent or unreadable the cron exits before the probe is ever reached. The probe MUST use REST "list repository issues/events updated since `<timestamp>`" (core API bucket, 5000 requests/hr) or a single batched GraphQL query across repos — **NOT** the GitHub Search API (which is limited to ~30 requests/minute and does not scale past a handful of repos per probe). "Token-free" does not mean "rate-limit-free" — API calls consume GitHub rate-limit quota. Reserve Search API for cold reconciliation only. This is a hard constraint: using the Search API on the hot path would silently degrade to a queue-depth-limited probe as the customer count grows. Envelope parsing (model-free but heavier) happens only on the small set the query returns (R4.1.4).
- **R10.2 — Back-off.** A repo with no recent issue/PR/comment activity backs off exponentially from floor toward ceiling.
- **R10.3 — Reset.** **Any inbound event** (new issue/PR/comment, new envelope) resets that repo to the floor, so latency stays low when it matters.
- **R10.4 — Priority pin (with timeout).** An open **P0**, an **unanswered coordination** message, or an **embargoed-security** item pins cadence to the floor until resolved (overrides back-off). An unanswered coordination pin has a configurable maximum duration (default 72h) after which, if still unresolved, it **deprioritizes to the human queue** (`needs-human`) and the pin is released — the loop does not hold the floor indefinitely on a stalled conversation.
- **R10.5 — Per-customer cadence (soft state, floor-fallback on cold start).** Each repo has independent cadence state. Cadence/back-off level and last-poll timestamp are **soft operational state** — instance-local with a floor-fallback on cold start (a fresh instance that has no cadence history simply starts at the floor). Losing cadence state on a cold start means re-probing at the floor, which is safe and correct. This reconciles the "not instance-local" intent (persisted in GitHub / the ledger when possible) with the cold-start reality (fallback to floor is always safe).

---

## 11. Circuit breakers & observability — **[#254 considerations #8, #9]**

### 11.1 Circuit breakers

- **R11.1 — Per-issue failure cap.** Default **3**. A poison-pill issue that keeps failing is stopped (labeled `needs-human`) rather than burning tokens forever.
- **R11.2 — Per-run blast-radius caps (rolling 24-hour window).** Max **5 PRs / 10 issues / 25 files** touched in the rolling 24-hour window read from the ledger at the start of every probe cycle. These are window caps, not per-invocation caps — a probe cycle that would cause the window total to exceed any cap halts new work for that window and pages. "Run" in this context means a single probe/dispatch invocation (the stateless short-lived tier, §3). The window is evaluated at the start of each probe cycle, before claiming new work.
- **R11.3 — GitHub rate-limit backoff.** Honor `X-RateLimit-*`; exponential backoff, never hammer.
- **R11.4 — Max runtime per task.** A task exceeding its wall-clock budget is abandoned (claim released, `needs-human`).
- **R11.5 — Dead-man's-switch (externally checkable).** The dead-man condition is: **"no probe-completion event landed in GitHub in the last 6h."** A probe-completion event is a label or comment the loop posts at the end of every probe cycle (e.g. a `type: heartbeat` envelope on a designated watchdog issue). The checker MUST NOT be the loop itself — an external monitoring process (e.g. a separate cron, a GitHub Action, or a human) checks for the probe-completion event. If no event in 6h → page a human. The loop being silently dead is itself an incident, and a dead loop cannot report its own death.

### 11.2 Observability

- **R11.6 — Run ledger (machine-readable, per-run files).** Every autonomous action records **who / what / when / why / token-cost** to a committed, append-only **JSONL** run ledger. The ledger is implemented as **per-run files** named `<instance-id>-<timestamp>.jsonl` plus a manifest file listing them — not a single shared JSONL — eliminating git write-conflicts between concurrent instances. Budget and blast-radius checks aggregate across per-run files in the rolling window at read time. This is the structured, queryable forensic record and is the **authoritative source** for all aggregated metrics. The JSONL is **written first**; the Markdown (R11.8) is derived from it.
- **R11.7 — Dry-run / shadow mode.** A mode that runs the full loop — triage, claim-eval, build-plan — and **records what it *would* do** without acting. Mandatory for testing the loop on a live repo without risk, and the default for a newly-onboarded customer.
- **R11.8 — Running activity log (human-readable Markdown, derived).** Alongside the JSONL ledger (R11.6), the loop keeps a **committed Markdown log** (e.g. `audit/automation-log.md`, per-customer) of **what the automated agent has done, in plain-language summaries** — one dated entry per cycle/task: what it picked up, what it decided and why, what it changed/merged/escalated, and the running token cost. A human must be able to **skim the day's automation in narrative form** without parsing JSON. **Write ordering and failure semantics:** the JSONL (R11.6) is written first and is authoritative — if only the JSONL write succeeds, no data is lost. The Markdown is DERIVED from the JSONL and can be regenerated from it at any time. The "never rewrite history" rule applies to JSONL entries; Markdown entries also append (never edited once written). Roll-up summaries (per day/week) are **separate regenerated artifacts**, not in-line rewrites of the append-only log — the roll-up is regenerated/prepended as a separate section, and the entry history below it is never touched.

---

## 12. Multi-customer fairness — **[#254 consideration #10]**

One HOS polls many customer repos.

- **R12.1 — Per-customer budgets (token AND API-call).** §8 budgets are per `(customer, window)`; one customer's spend never draws down another's. In addition to token budgets, each customer has a **per-customer API-call budget** (GitHub REST/GraphQL calls per probe window). GitHub rate limits are per-machine-account, not per-repo, so one noisy customer consuming excessive API calls can starve other customers' probes. The round-robin (R12.2) is quota-aware: a customer that has consumed its API-call budget for the window is skipped until the window resets.
- **R12.2 — Round-robin with staggered start times.** Probe + work scheduling rotates across customers so a noisy repo can't starve the rest. Probe start times across repos are **staggered** (offset by `floor / N_repos`) to avoid a synchronized thundering herd at the top of each probe interval. A single customer's per-run blast-radius cap (§11.2) bounds its share of any cycle. The round-robin is quota-aware (R12.1).
- **R12.3 — Isolation.** A failure (poison-pill, rate-limit, kill-switch) in one customer's processing must not halt the others. Kill-switch is per-repo *and* global (a global `hos-halt` stops everything).
- **R12.4 — Per-customer capability.** Auto-merge, allowlist, thresholds, cadence, and PROPOSE_ONLY/AUTONOMOUS mode are all per-customer (§9.1, §8.3).

---

## 13. Configuration surface

**Config is layered so the shipped framework source is always *unconfigured*.** Four layers, resolved at load time (later overlays earlier):

1. **Shipped defaults (HOS-owned, in source).** A `hos-coordination.defaults.yaml` ships with the framework carrying **only defaults** — `enabled: false`, the §8.3 threshold profile, cadence bounds. It is **inert**: it turns nothing on. This is the layer that lives in the framework repo / a release.
2a. **Governance config (committed in the consumer/deployment repo's PROJECT area, CODEOWNERS-gated).** The security-critical configuration that decides **what the system may do, how much it may spend, and who may drive it**: `enabled`, the budget thresholds (`per-task-tokens`, `window-budget-tokens`, `approval-timeout`), `requester-allowlist`, and the `mode` floor. This layer is **committed in the consumer repo's PROJECT-owned area** (not in `.ai-local/`, not gitignored) and is **CODEOWNERS-gated** — a human-approved commit is required to change it. Rationale: governance config decides what the system may do and spend; putting it in agent-writable gitignored storage would allow the loop to self-enable, self-widen its budget, or self-extend its allowlist with no committed audit trail — the `AGENT-IDENTITY.md §5.1` accountability gap applied to configuration. HOS's own dogfood governance config lives committed + CODEOWNERS-gated in the HOS repo's PROJECT area, NOT in `.ai-local/`. **This layer is repo AUTHORIZATION only — it does NOT control per-machine operator activation (R13.4).**
2b. **Operational soft state (`.ai-local/`, agent-writable, gitignored, ephemeral).** Non-security configuration that tracks transient loop operation: cadence/back-off level, last-poll timestamp, per-run instance state. This layer is in `.ai-local/`, agent-writable, gitignored, and ephemeral — losing it on a cold start is safe (the loop re-probes at the floor). It must NEVER contain `enabled`, thresholds, allowlist, or mode-floor values. **The operator activation file (R13.4) is NOT part of this layer** — it lives outside the repo at `~/.hos/<repo-id>/ACTIVE`, is entirely off the repo's synced/committed surface, and is checked as an independent first-gate AND condition, not as a config overlay.
3. **Runtime overrides** — env / kill-switch / `enabled:false` short-circuit (R13.2).

> **Operator activation is separate from all four config layers.** The local activation file (`~/.hos/<repo-id>/ACTIVE`, R13.4) is not part of the layer-resolution chain — it is an independent AND condition checked **first, before any probe or GitHub API call, on every cron wake**. If the file is absent, unreadable, or ambiguous, the cron exits immediately with at most a single `"inactive — exiting"` log line — no probe, no API calls, no model invocation. It is never read as a config value, never committed, and never synced. A repo can have `enabled: true` in layer 2a (authorized) and still be completely inert if no activation file is present on the running machine.

**HOS's own dogfood config split:** governance config (layer 2a) lives committed + CODEOWNERS-gated in HOS's PROJECT area; operational soft state (layer 2b) lives in `.ai-local/` (gitignored). Neither is in the shipped framework source. Consequence: a `git grep 'enabled: *true'` over the framework source returns nothing, and a cut release never carries HOS's (or anyone's) live enablement. A freshly-cloned HOS repo is fully inert — `enabled: false` default, and no `~/.hos/<repo-id>/ACTIVE` file is present on a new machine.

The schema (shown here as the shipped **defaults** — note `enabled: false`; T2/T3 show the governance vs soft-state split; the local activation file is NOT shown here — it is not a config field):

```yaml
# LAYER 1: shipped defaults (hos-coordination.defaults.yaml — in framework source, inert)
# NOTE: operator-local activation (R13.4) is NOT a field in this config.
#       It is a separate per-machine file (~/.hos/<repo-id>/ACTIVE) checked FIRST,
#       before any probe, on every cron wake. Absent/unreadable/ambiguous = OFF.
#       A repo with enabled: true here is still INERT until an operator creates
#       that file on the machine that will run the worker.
customer: cps
enabled: false                          # REPO AUTHORIZATION (layer 2a governs); OPT-IN, OFF BY DEFAULT
protocol-version: "1.0"
mode: autonomous | propose-only        # auto-detected; overridable downward only
requester-allowlist: []                # GOVERNANCE — must be set in layer 2a (consumer PROJECT, CODEOWNERS-gated)
security-sensitive-paths: ["audit/**", "**/auth/**", "scripts/oversight/gates/**"]
thresholds:                            # GOVERNANCE — override in layer 2a
  per-task-tokens: 150000
  window-budget-tokens: 1500000
  approval-timeout: 12h
  triage-confidence-floor: 0.75
cadence: { floor: 15m, ceiling: 24h }  # floor is governance (layer 2a); current back-off level is soft state (layer 2b)
self-review: { cadence: weekly, cross-vendor: true }   # cadence floor is governance; last-run timestamp is soft state
severity-triage: { scheme: P0-P3, fix-order: highest-first }
claim: { timeout: 45m, heartbeat: 15m }
breakers: { per-issue-failures: 3, blast-radius: { prs: 5, issues: 10, files: 25 }, dead-man: 6h }
```

- **R13.1 — `mode` can only be narrowed by config, never widened; governance config can only narrow `enabled`, thresholds, and allowlist — never widen them.** Config may force `propose-only` on a server-side-gated repo, but config **cannot** force `autonomous` on a repo where the gate isn't detected. Governance config (layer 2a) establishes the maximum permitted scope — it may restrict `enabled`, tighten thresholds, or shrink the allowlist, but an operator cannot use config to grant the loop permissions beyond what the framework's detection and ceiling allow. This "narrow-only" constraint applies to `enabled`, the budget thresholds, the `requester-allowlist`, and the `mode` floor — not just `mode` alone.
- **R13.2 — Opt-in, disabled by default — requires BOTH repo authorization AND operator activation.** The unattended worker runs only when **two independent conditions simultaneously hold** (fail-closed if either is absent or unreadable):

  1. **Repo AUTHORIZATION (existing layer 2a)** — `enabled: true` is present in the committed, CODEOWNERS-gated governance config (layer 2a). This is the existing R13.3/B9 layer. Meaning: "this repo is sanctioned for autonomous work, under these limits." It is agent-unforgeable (requires a human-reviewed commit) and durable (travels with the repo). A fresh clone that sets `enabled: true` in layer 2a is *authorized* but still **inert** until the operator also activates it locally.

  2. **Operator ACTIVATION (new — R13.4)** — the local activation file (`~/.hos/<repo-id>/ACTIVE`) must be present and readable on the machine that will run the worker. Meaning: "a human has turned it on, here, now." See R13.4 for the full activation-file contract.

  **Off by default across both layers:** in a fresh clone neither condition holds (`enabled: false` shipped default, no local activation file present), so the worker does nothing. **ABSENCE, UNREADABILITY, or AMBIGUITY of the activation file is unconditionally read as OFF (fail-closed) — this default is never overridable to "on by assumption."** A fresh clone, a new machine, or an empty/corrupt activation file all result in the worker doing nothing. Disable is always immediate.

  **Three complementary controls — not one:**
  - `enabled: false` in governance config = **POLICY off** — this repo is not sanctioned; auditable, durable, travels with the repo.
  - Missing local activation file = **OPERATOR off / not-running-here** — easy, local, non-propagating; does not require a commit, PR, or review to toggle.
  - `hos-halt` (§8.4) = **EMERGENCY kill** — stops a running, authorized + activated worker immediately on the next cycle.

  These are orthogonal. The POLICY layer (committed `enabled`) and the ACTIVATION layer (local file) are BOTH required — neither alone is sufficient. The local activation file cannot enable the worker on a repo that lacks a committed `enabled: true` authorization, so this does NOT reopen B9's "agent self-enables with no audit trail" hole — the committed, CODEOWNERS-gated authorization remains the anti-forge gate.
- **R13.3 — Source ships unconfigured; governance config lives committed in consumer PROJECT area; soft state lives in `.ai-local/`.** The framework **source carries defaults only** (layer 1); governance configuration (layer 2a) — including HOS's own dogfood enablement — lives committed + CODEOWNERS-gated in the consumer/deployment repo's PROJECT-owned area. Operational soft state (layer 2b) lives in `.ai-local/` (gitignored). The framework repo must never contain a committed `enabled: true` or any deployment's real governance config. This keeps releases inert (a fresh install is disabled until its operator commits a governance config) and keeps each deployment's posture out of the shared source. Mirrors the existing CORE/PACK (HOS-owned, shipped) vs PROJECT (consumer-owned, never overwritten) layering.

- **R13.4 — Operator-local activation file (the second condition of R13.2).** The worker runs only where an operator has explicitly activated it on the specific machine. **The activation-file check is the very first action on every cron wake, before any probe, any GitHub API call, any model invocation, and any other logic.** If the file is absent, unreadable, or its content is ambiguous, the cron exits immediately and does nothing — no probe, no GitHub API calls, no model invocation, nothing beyond at most a single `"inactive — exiting"` log line. "Off" means ZERO activity, not merely "no work performed." The activation file:
  - **Lives outside the repo, under the operator's home directory:** `~/.hos/<repo-id>/ACTIVE`, where `<repo-id>` is a stable slug derived from the remote URL. This is the resolved path (O16 closed). Rationale: applying the B9 principle (a control that gates whether the autonomous worker runs at all should not live among agent-writable, repo-scoped state), an external operator-home path keeps activation on the human-operator side and entirely off the repo's synced or committed surface, and guarantees the capability never travels with a clone. **Honesty note:** the committed-authorization AND-condition (layer 2a) remains the actual anti-forge guarantee — the external location is defense-in-depth plus the "doesn't travel with the repo" property. The external path does NOT make the file agent-unreachable in an absolute sense; it makes accidental sync or commit structurally impossible.
  - **Is NOT committed and NOT synced.** Because the file lives outside the repo, no gitignore entry is needed and it cannot accidentally be committed or cloned. The capability therefore **never travels with the repo**: a fresh clone, a synced checkout, or a CI environment is inert — no operator activation is present — even when `enabled: true` is committed.
  - **Off by default — fail-closed, never overridable to on-by-assumption:** ABSENCE, UNREADABILITY, or AMBIGUITY of the file is unconditionally treated as OFF. A fresh clone, a new machine, or an empty/corrupt file all result in the worker doing nothing. This default is never overridable to "on by assumption."
  - **Easy disable:** deleting `~/.hos/<repo-id>/ACTIVE` turns the worker OFF on the next cron wake (the activation check is the first gate, so the cron exits immediately). No commit, no PR, no review required. This is the fast per-machine on/off switch.
  - **Non-propagating:** because the file is not synced, activating on one machine has no effect on any other machine; another operator who clones or pulls the repo onto a different machine still needs to create their own activation file.
  - **Cannot substitute for repo authorization:** the local activation file alone cannot enable the worker. The committed `enabled: true` authorization (layer 2a) is still required. This preserves B9's agent-unforgeable anti-forge gate: the committed, CODEOWNERS-gated authorization is the audit record that the repo is sanctioned; the local file is only the per-machine on/off switch layered on top.

#### Operational example — relocating the autonomous instance

The canonical motivating scenario for the activation file is a **machine migration**: an operator runs the autonomous worker on one machine today (e.g. their Mac) and later moves it to another (e.g. a host named `faberix`). Both machines hold the same repo clone and therefore both carry the committed `enabled: true` authorization (layer 2a). The `~/.hos/<repo-id>/ACTIVE` file is what decides which machine is actually running the autonomous worker — relocating the instance means moving that file.

**Single-active is operator-managed** for a deliberate sequential move. No lease or system-enforced exclusion is needed in v1 because the §7 claim-then-verify + correlation-id-keyed artifact naming is the safety net if both activation files briefly coexist: two active instances cannot double-do or collide (§7, R6.1), so a brief overlap during migration is safe rather than catastrophic. (A system-enforced single-active lease — where a forgotten second activation file would be automatically inert — is an explicit v2 option, out of scope for v1.)

**Handoff procedure (preserves single-active, fail-closed):**

1. **Remove `~/.hos/<repo-id>/ACTIVE` on the old machine.** The old instance goes inert at its next cron wake — the activation check (R13.4) is the first gate, so the cron exits immediately with no probe, no API calls, no model invocation.
2. **Let the old machine's current cycle finish, or let its claim time out.** Either path is safe: completing normally produces a normal outcome; a stopped machine causes the claim's `updated_at` to go stale after `claim_timeout = 45m` (R7.3), at which point any other instance may re-pick up the work.
3. **Create `~/.hos/<repo-id>/ACTIVE` on the new machine.** It is now the autonomous instance and will pick up work on its next cron wake.

Remove-first guarantees no overlap window; the fail-closed default (an absent activation file = zero activity) makes the brief gap between step 1 and step 3 harmless rather than a service interruption.

**Mid-task safety.** Removing the activation file on the old machine stops it from dispatching NEW tasks immediately (the activation check fires before the probe). Any in-flight per-task worker either completes normally or — if the machine is stopped — its claim ages out (§7 claim timeout, R7.3) and the new machine re-picks up the work via correlation-id-keyed idempotent recovery (§6.1, branch `hos/auto/<correlation-id>`). No work is lost or duplicated across the migration. This is the GitHub-as-DB / cold-start-safe property (§6) applied to a machine-migration event.

---

## 14. Phasing

| Phase | Contents | Gate to ship |
|---|---|---|
| **v1.0** | Probe + adaptive cadence (15m/24h), triage w/ confidence floor + allowlist, envelope v1.0, GitHub-as-DB + cold-start recovery, claim-then-verify + heartbeat, budget gates + default-deny, merge-authority matrix (PROPOSE_ONLY default; auto-merge where detected), embargo *routing*, circuit breakers, run ledger + shadow mode, multi-customer fairness, **scheduled self-review work source (#131)** — exact-key ledger dedup, auto-file findings, **weekly (configurable)**, human-only close; **severity triage + priority-ordered fix (§5.3)**. | Cold-start drill (M4) + a shadow-mode run on HOS's own repo + #152 server-side gate live on at least HOS. |
| **v2** | Cryptographic envelope signing, embargo-fix *automation*, external lock primitive (if claim-then-verify proves insufficient), non-GitHub transports, finer adaptive cadence (sub-hour where a customer opts in). | **v1→v2 gate criterion:** v1 must have operated in production on at least two customer repos for ≥30 days with: (a) M1 = zero confirmed duplicate-work incidents, (b) M3 = 100% of autonomous merges within ceiling, (c) M4 cold-start drill passing, and (d) the dead-man's switch triggering correctly on at least one simulated outage. All four criteria must be met and recorded in the audit ledger before v2 scope begins. |

---

## 15. Open items for the design phase

- **O1** — *(direction set by R13.3)* Config home: layered — shipped `hos-coordination.defaults.yaml` (defaults only, layer 1) + governance config committed in consumer PROJECT area + CODEOWNERS-gated (layer 2a) + operational soft state in `.ai-local/` (layer 2b). Remaining design detail: the exact governance-config path in the consumer PROJECT area + the resolution/merge order with `config.sh`.
- **O2** — ~~Instance-id scheme for the claim tiebreak (§7.1): hostname+pid is racy across machines; prefer a per-instance UUID minted at boot and carried in the claim envelope.~~ **RESOLVED — see R7.1:** each instance generates a UUIDv4 at startup as its instance-id; hostname+pid MUST NOT be used.
- **O3** — Exact server-side-gate detection probe (§9.1.1): protection-API read vs an active no-op-rejection canary. The canary is stronger (proves enforcement, not just configuration) but noisier.
- **O4** — Where the run ledger lives relative to `audit/oversight-log.jsonl`: per-run files (R11.6 mandates the per-run-file structure); the remaining design detail is whether they are per-customer subdirectories or a flat manifest, and how they are referenced from `audit/oversight-log.jsonl`.
- **O5** — *(direction set, #254 feedback)* Token-estimation method (R8.1): a **cheap heuristic** from issue/diff size, changed-file count, blast radius, and historical cost of similar tasks — **no model pre-pass**, must itself be ~free. **Estimation error is acceptable** (err high; R8.6 re-asks on mid-flight overrun). Remaining design work is only *which* signals and the calibration constants, not whether to use a model.
- **O6** — *(from #131)* **Fingerprint fuzz** on self-review findings (R3.2.1): the same logical finding can return with a slightly different file set / class wording → fingerprint miss → duplicate issue. Need a fuzzy-match step or a periodic human de-dup pass (relates to #78 cross-vendor fingerprint reconciliation). The exact-key ledger is the v1 floor; fuzzy-match is the hardening.
- **O7** — *(from #131)* **Auto-close policy** for filed governance findings: a finding whose underlying file changed such that it no longer reproduces — does its issue auto-close? v1 answer is **no** (R3.2.4, human-only close); O7 is whether a *suggested*-close signal (not an actual close) is worth adding later.
- **O8** — ~~**Execution model** (flagged in review).~~ **RESOLVED — see §3 and R7.x:** stateless short-lived cron for the probe/dispatch tier + bounded long-lived per-task workers. Heartbeat (R7.2) re-stamps the claim envelope's `updated_at` every ≤15m; staleness is computed from the GitHub-observable timestamp by any instance.
- **O9** — *(from #167(a))* **Suppression ledger scope** (R3.2.5): per-repo or shared across consumers? A shared ledger lets HOS suppress a known framework-level false positive once for everyone; a per-repo ledger keeps consumer accepted-risk decisions local. Likely both: a HOS-shipped baseline + a per-repo overlay.
- **O10** — *(from #167(b))* **Won't-fix human-only classes** (R3.2.5): which finding classes may the loop *never* autonomously won't-fix? Proposed floor: **security / privacy / license** are human-ruled-only (the loop escalates, never self-suppresses them). Confirm the list.
- **O11** — ~~**R3 auto-approve ceiling reconciliation.** #167 proposed Faberix R3 auto-approve at **LOW only**; #254 decision #1 locked the auto-merge ceiling at **≤MEDIUM** (§9.1).~~ **RESOLVED:** with the protected-surface carve-out in place (R9.1.3), the ≤MEDIUM auto-merge ceiling (§9.1 / #254 decision #1) governs and supersedes #167's LOW-only proposal. The protected-surface carve-out is the mechanism that prevents governance-surface changes from auto-merging at any tier; within the non-protected-surface space, ≤MEDIUM is the ratified ceiling.
- **O12** — ~~**Draft-PR semantics** (needs ratification).~~ **RESOLVED:** `draft = "awaiting human"` (option (b)) is ratified. See R9.3.2. The loop also distinguishes its own draft PRs (worker account + envelope + `hos-coordination` label) from human-opened draft PRs.
- **O13** — *(new — A3)* **Governance config path in consumer PROJECT area:** the exact file path, file name convention, and CODEOWNERS pattern for layer 2a governance config in a consumer repo. Design detail: does it live in `PROJECT/hos-coordination.yaml`, `config/hos-coordination.yaml`, or a convention derived from `config.sh`? Remaining resolution links to O1.
- **O14** — *(new — R4.1.1)* **Acknowledgment-pattern list:** the configurable list of comment patterns (thanks / LGTM / looks good / closing / never mind / no action) used by R4.1.1 to skip envelope-less chatter comments without triage. The exact v1 default list needs confirmation and a test corpus.
- **O15** — *(new — B6/R10.1b)* **Per-customer API-call budget defaults:** what is the v1 default per-customer API-call budget (calls per probe window)? Needs calibration against the REST core bucket (5000/hr) shared across all customers and the stagger interval (R12.2).
- **O16** — ~~*(new — R13.4)* **Activation-file location.**~~ **RESOLVED — chosen path: `~/.hos/<repo-id>/ACTIVE`.** Rationale: applying the B9 principle (a control that gates whether the autonomous worker runs at all should not live among agent-writable, repo-scoped state), the external operator-home path keeps activation entirely off the repo's synced or committed surface and guarantees the capability never travels with a clone. The `.ai-local/worker-active` candidate is dropped. Honesty: the committed-authorization AND-condition (layer 2a) is the actual anti-forge guarantee; the external location is defense-in-depth plus the "doesn't travel with the repo" property — it does not make the file agent-unreachable in an absolute sense. Propagated to: R13.2, R13.4, §13 narrative + YAML comment, T2.

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
| Human-review queue: draft-PR + needs-human/needs-ai (#156, #203, subsumed) | §9.3, O12 |
| Suppression/suspension lifecycle: nag + date-triggered removal (#168, subsumed) | R3.2.6 |
| No autonomous releases (human-approved always) | §9.4, NG3b |
| Open Q: adaptive polling | §0, §10 |
| Open Q: spec home/format | §0 |
| Open Q: concrete defaults | §8.3 |
| Considerations #1–#11 | §3.1, §9.2, §6, §7, §8, §4, §5, §11, §11.2, §12, §10 (mapped inline) |
| **Amendment A1** — execution model (stateless probe/dispatch + bounded long-lived workers) | §3 diagram+caption, R7.1–R7.3, R11.5, O8 resolved |
| **Amendment A2** — protected-surface carve-out (AGENT-IDENTITY.md §9.0, O11 resolved) | R9.1.3 (new), §9.1 matrix, O11 |
| **Amendment A3** — governance config split (layer 2a committed+CODEOWNERS-gated, layer 2b soft state) | §13, R13.1, R13.3, O13 (new) |
| **Amendment A4** — draft = "awaiting human" ratified; own-draft vs human-draft distinction | R9.3.2, O12 resolved |
| **Fix B3** — allowlist checks GitHub-API-verified author, not envelope `from:` | R4.3.1, R4.3.2 |
| **Fix B4** — token/budget ledger append-only per-task records keyed by correlation-id; per-run files | R8.2, R11.6 |
| **Fix B5** — formal GitHub PR Review in APPROVED state required before merge in AUTONOMOUS mode | R9.3.4 |
| **Fix B6** — probe MUST use REST list / batched GraphQL, NOT Search API on hot path | R10.1b |
| **Fix B7** — branch-protection re-queried immediately before each merge; overseer bypass verified | R9.1.1 |
| **Fix B8** — claim lock advisory; M1 guarantee from R6.1 correlation-id artifact naming; UUIDv4 instance-id | R6.1, R7.1, O2 resolved |
| **Fix B10** — blast-radius caps evaluated over rolling 24-hour window from ledger | R11.2 |
| **Fix B11** — comment loop termination: terminal-state check, ack-pattern skip, one-clarification-per-thread | R4.1.1 |
| **C-MF3** — "significant model work" defined (GATED vs UNGATED table) | R8.7 (new) |
| **C-MF2** — reproducing-test / evidence-of-fix per triage class | R3.1.1, §5.1 (table) |
| **C-SRfloor** — hard 24h floor on self-review cadence | R3.2.2 |
| **C-SuppExpiry** — expired suppression → `suppression-expired` issue, human queue, no auto-triage | R3.2.6 |
| **C-LabelAuth** — `hos-coordination` label actor verified against allowlist before envelope parse | R4.1.4 |
| **C-BRgate** — benefit-≫-risk gate as computable severity×tier matrix | R5.3.3 |
| **C-Metrics** — M1 duplicate-work incident operational definition; M4 cold-start state table | R6.1 |
| **C-Logsync** — JSONL written first (authoritative); Markdown derived; roll-up as separate artifact | R11.6, R11.8 |
| **C-Nag** — suppression nag mechanism: `type: question` envelope N days before expiry | R3.2.6 |
| **C-Quota** — per-customer API-call budget; quota-aware round-robin; staggered probe start times | R12.1, R12.2, O15 (new) |
| **C-Cadence** — cadence/back-off as soft state with floor-fallback on cold start | R10.5 |
| **C-minor** — priority-pin timeout (R10.4); "private channel" is deployment-configured (R9.2.1); v1→v2 gate criterion (§14) | R10.4, §14 |
| **Amendment A5** — operator-local activation (two-condition AND model): repo AUTHORIZATION (existing layer 2a) AND per-machine ACTIVATION (new R13.4); three-control comparison (POLICY off / OPERATOR off / EMERGENCY kill); activation file not synced, not committed, easy delete; O16 (activation-file location) | R13.2, R13.4, §13 narrative, §13 YAML, T2, O16 |
| **A5-R1** — activation check is the first gate on every cron wake: if absent/unreadable/ambiguous → exit immediately, zero activity (no probe, no API calls, no model), at most one log line; "off" means ZERO activity; probe (R10.1b) runs only after activation check passes | R13.4, §13 narrative sidebar, T2 |
| **A5-R2** — O16 resolved to external operator-home path `~/.hos/<repo-id>/ACTIVE` (B9 principle + doesn't-travel-with-repo); `.ai-local/worker-active` candidate dropped; honest framing: external location is defense-in-depth, not absolute agent-unreachability; committed-authorization remains the anti-forge guarantee | R13.2, R13.4, §13 narrative + YAML comment, layer-2b description, T2, O16 (closed) |
| **A5-R3** — fail-closed default ironclad: ABSENCE, UNREADABILITY, or AMBIGUITY of the activation file = OFF; never overridable to "on by assumption"; stated explicitly in both R13.2 and R13.4 | R13.2, R13.4 |
| **A5-R4** — operator-managed instance relocation: remove activation file on old machine → let cycle finish or claim time out → create file on new machine; remove-first guarantees no overlap; brief gap is harmless (fail-closed default); mid-task safety via §6 cold-start recovery + §7 claim timeout; v2 option: system-enforced single-active lease | R13.4 (operational example), §6.1, §7 (R7.3) |

---

## 17. Implementation task list

The work breakdown for building v1. Tracks the §14 phasing into concrete deliverables. **Opt-in / disabled-by-default (R13.2) is a cross-cutting constraint on every item below — nothing runs against a customer repo until they explicitly enable it.**

### 17.1 Documentation & control (the enable/disable surface)

> **Doc strategy: this PRD is the *normative* source; the human/agent docs are *derived* from it later.** The workflow, state machine, labels, and conventions live here as the single source of truth (and are largely already specified across §3 / §5 / §7 / §9). The deliverable docs below (T1 agent instructions, T3 operator doc, T16 issue-handling process) are **generated from the spec** during implementation, so they can be regenerated when the spec changes and cannot silently drift. Don't author them as independent narratives now — author the spec, then derive.

- [ ] **T1 — Agent instructions for the customer↔HOS communication protocol.** Author the agent-facing spec (in `AGENTS.md` and/or the relevant `.claude/agents/` files) describing how agents participate in the protocol: the envelope format (§4), how to read/write `correlation-id`/`in-reply-to`, the triage classes (§5), claim-then-verify + heartbeat (§7), the escalation contract (§8.2), and the merge-authority boundaries (§9.1). This is the contract any compliant agent team implements to speak the protocol.
- [ ] **T2 — Control mechanism (enable/disable) + layered config.** Implement the two-condition AND check (R13.2) as **the very first action on every cron wake**, before any probe or GitHub API call: (1) check for the operator activation file at `~/.hos/<repo-id>/ACTIVE` (R13.4 — operator ACTIVATION); if absent, unreadable, or ambiguous, **exit immediately** with at most a single `"inactive — exiting"` log line — no probe, no API calls, no model invocation; (2) only after activation check passes, check `enabled: true` in the committed governance config (layer 2a — repo AUTHORIZATION). ABSENCE, UNREADABILITY, or AMBIGUITY of the activation file is unconditionally OFF; this default is never overridable to "on by assumption." **Build the 4-layer config resolver (R13.3):** layer 1 = shipped `*.defaults.yaml` (inert defaults); layer 2a = governance config committed in the consumer PROJECT area + CODEOWNERS-gated (`enabled`, thresholds, allowlist, mode-floor); layer 2b = operational soft state in gitignored `.ai-local/` (cadence, last-poll timestamp); layer 3 = runtime env overrides. The operator activation file is NOT part of the four-layer resolution chain — it is the first-gate AND condition checked before the resolver runs. The framework source MUST stay free of any `enabled: true`; disable is immediate; absence of either condition = disabled. Reject `self_review_cadence` values below 24h at config-load (R3.2.2 hard floor). **Activation-file path:** `~/.hos/<repo-id>/ACTIVE` (external to the repo, no gitignore entry needed, never synced or committed — O16 resolved). **Provision the canonical label set per repo (R6.2):** create the `hos-*` labels (incl. `hos-coordination`) on opt-in; reuse the existing `needs-ai` / `needs-human` (hyphen-case — do **not** create underscore variants).
- [ ] **T3 — Human-facing doc in `docs/`.** A new doc in the human docs section (e.g. `docs/UNATTENDED-WORKER.md` / `docs/COORDINATION-PROTOCOL.md`) so a human knows the subsystem exists, understands what it does autonomously, and can **enable/disable** it. **Must state plainly: off by default; the customer opts in; here is how to turn it on, how to turn it off, and how to hit the kill switch.** Cross-link from `docs/SETUP.md` and the runbook.
- [ ] **T16 — Issue-handling workflow & process doc (`docs/`).** A derived, human-readable doc describing the **end-to-end issue lifecycle**: how an item is discovered (`hos-coordination` label), triaged (the §5 classes + severity + benefit-≫-risk gate), claimed (§7), worked (the gates), and resolved (merge per §9.1, the draft-PR + `needs-human`/`needs-ai` review queue §9.3, escalation §8.2, embargo §9.2, or won't-fix+suppress §3.2.5). Includes the **label glossary** (R6.2) and the **disposition menu** so a human can drive the queue. Generated from the normative sections above — *not* a separate design surface.

### 17.2 Core loop

- [ ] **T4 — Probe + adaptive cadence (§10)** — token-free GitHub poll, 15m/24h bounds, back-off, priority-pin; per-customer round-robin (§12).
- [ ] **T5 — Coordination envelope (§4)** — parse/emit, threading DAG, at-least-once idempotency, protocol-version negotiation, requester allowlist.
- [ ] **T6 — Triage (§5)** — classifier with confidence floor + asymmetric security detection; **severity triage P0–P3 (§5.3)**; benefit-≫-risk gate with reject→human.
- [ ] **T7 — State model & idempotent recovery (§6)** — GitHub-as-DB, labels/assignees/ledger; cold-start drill (M4).
- [ ] **T8 — Locking (§7)** — claim-then-verify (contention-reducer only; M1 guarantee from R6.1 correlation-id artifact naming), UUIDv4 instance-id (R7.1), heartbeat as claim-envelope re-stamp (R7.2), claim timeout, crash-before-first-heartbeat auto-release, terminal-state release. *(O8 resolved — execution model is stateless probe/dispatch + bounded long-lived per-task workers; see §3.)*
- [ ] **T9 — Budget & significance gates (§8)** — estimate-then-gate, per-task + per-window, default-deny, mid-flight overrun re-ask; wire to existing pager (R8.5).
- [ ] **T10 — Merge authority (§9)** — server-side-gate detection ("detected, not assumed"), the orthogonal tier × security matrix, PROPOSE_ONLY default; **human-review queue convention (§9.3:** draft-PR + `needs-human`/`needs-ai`, disposition menu, no "(DRAFT)" titles); **no-autonomous-release guard (R9.4.1).**
- [ ] **T11 — Security embargo routing (§9.2)** — ack + route + `hos-embargo`; no public branch/PR/test.

### 17.3 Work sources & safety

- [ ] **T12 — Scheduled self-review source (§3.2, #131)** — `validate_self` auto-file mode, exact-key ledger dedup, weekly default cadence, human-only close, burndown metric (M6).
- [ ] **T13 — Circuit breakers (§11.1)** — per-issue failure cap, blast-radius caps, rate-limit backoff, max runtime, dead-man's-switch.
- [ ] **T14 — Observability (§11.2)** — JSONL run ledger (who/what/when/why/cost) **+ human-readable Markdown activity log with plain-language summaries (R11.8, `audit/automation-log.md`)** + dry-run/shadow mode (default for a newly-opted-in customer).
- [ ] **T15 — Multi-customer fairness (§12)** — per-customer budgets, round-robin, isolation, global + per-repo kill switch.

> **Ship gate (§14):** the cold-start drill (M4) passes, a shadow-mode run on HOS's own repo looks correct, and #152 server-side enforcement is live on at least HOS — all before any repo flips `enabled: true` out of shadow mode.
