# ADR-1644: Stage-per-cycle. The worker advances one declared stage per cron cycle, code decides which stage and whether it may run, and GitHub is the only state

**Status:** ACCEPTED FOR DESIGN. Binds `technical-design`. **Two items are held for the human and block
named slices only** (§6: ARCH-ESC-1 blocks T3.0b, ARCH-ESC-2 blocks the go-live of T3.7b). **Five items
are human confirmations of readings I have already bound, using the stricter reading** (§6: ARCH-ESC-3
to ARCH-ESC-7). Everything else below is **BINDING**.
**Date:** 2026-09-30
**Author:** architect
**Inputs:**
- `docs/v0.7.0/REQUIREMENTS-1644-AMENDMENT-1-stage-per-cycle.md` (pm-agent, merged in PR #1880), §3 to §5,
  which is the primary input.
- `docs/v0.7.0/REQUIREMENTS-1643-1644-deterministic-agent-invocation.md`: the Q1 to Q8 rulings, with
  Q4+Q6 (stage-per-cycle) and Q7 carrying the load.
- `docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md` §2 (AD-1 to AD-16) and the §4 seam. It is not
  amended here (§4).
- The human's ESC-5 ruling (2026-09-14): a PROJECT may disable a *binding*, never an *entry*.
- The human's **ESC-1 to ESC-9 rulings** (#1644, 2026-09-30T07:47:38Z), the separate **ESC-8 comment**
  (07:21:22Z), and the **ESC-6 addendum** (07:56:12Z).
- The cross-ADR constraints I am bound by: `ADR-1604` AD-7 to AD-11 (the self-split), and
  `ADR-1540-AMENDMENT-1` AM-10 (sub-issue authorization is derived from the parent and never marked).
- My own re-verification against this worktree at `7e37e2f70`, together with live read-only GitHub
  probes (§0).

**Provenance of the rulings.** All three 2026-09-30 ruling comments were posted by `scottthurlow-claude[bot]`,
the human-proxy identity, and each is headed "(human, 2026-09-30)". The amendment's own convention
(§0: "recorded by the human-proxy identity as human rulings") accepts that form, and I accept it for
**rulings**. The same identity's **acts** (applying labels, closing issues) are never human acts in this
design, for the same reason S2 already excludes them (`docs/LABELS.md`, authorizing act item 3). §6
ARCH-ESC-6 records the consequence.

**The brief omitted one ruling. I found it and incorporated it.** The ESC-6 addendum (07:56:12Z) is not
in the task brief. It permits a human-authorized **full round-counter reset** in addition to the base
grant, and it says in bold that the AI never resets its own counter. AD-C8 implements it, and ARCH-ESC-5
records one reading question it raises.

**Consumers:** `technical-design` comes next, then the issues decomposed from §5.
**Explicitly does NOT re-litigate:** Q1 to Q8, ESC-1 to ESC-9, and the ESC-6 addendum. Nor does it
re-litigate ADR-1643's primitive, result document, classifier, postures or AD-12 (two runners, one schema
family), or ADR-1540 S2's existing trust categories other than the one addition ESC-2 orders (AD-C16).
**Does NOT design:** field names, file-internal layout, or prompt text. Those belong to `technical-design`.
Where I name a file or a label, the name is binding and its internals are not.

---

## 0. Verification findings, re-derived against `7e37e2f70` and live GitHub

I re-read every file:line the amendment relies on. Line numbers moved since pm-agent wrote it, so I cite
symbols as well.

### Confirming the amendment where I depend on it

- **VF-C1 CONFIRMED.** `select_work_candidates.py` (790 lines) applies D1/D2 in `_apply_free_filters`
  from the list record's `labels` (`_label_names`). Its docstring says it "never reads an issue's body".
  `requester_verdict` reads only `user.login`, `user.type` and `title` ("never the body, never a label").
- **VF-C2 CONFIRMED, with moved lines.** `bootstrap/worker-cron-prompt.md:96` is still "**Pick the first
  non-blocked candidate** (#901)". The `bin/hos-cron` echo of it is now at `:1979`, where it was `:1920`.
  A search of `scripts/`, `bootstrap/` and `bin/` for `sub_issues`, `/dependencies`, `blocked_by` and
  `parent_issue` finds nothing outside the vendored `.venv`. No repo code reads or writes an edge.
- **VF-C3 CONFIRMED.** Step 3's classification is at `worker-cron-prompt.md:112-115`. `.claude/agents/worker.md:377-378`
  still says the rule is "absolute and self-enforced", that the mechanical gate "does not yet exist", and
  that "workers repeatedly self-exempted on this basis" (#556).
- **VF-C4 CONFIRMED.** There are zero live `needs-worker`/`needs-overseer` literals in `.py/.sh/.yml/.jq`.
  #1520 is open, `needs-ai`, v0.7.0. `docs/LABELS.md` still records that there is no provisioning path and
  no conformance test.
- **VF-C5 CONFIRMED, with a sharper constraint than the amendment states.** `requester_verdict` returns
  `trusted-app-no-machine-filing-marker` (untrusted) for any HOS App author without a marker, and
  `MACHINE_FILING_MARKERS` is "Closed against sub-issue filing (AM-10/D-7)". The amendment does not cite
  **`ADR-1540-AMENDMENT-1` AM-10**, which already rules that sub-issue filing **MUST NOT** appear in the
  marker table and must be authorized by *live derivation from the parent*. That constraint and the ESC-2
  ruling together fix the design (AD-C16).
- **VF-C6 CONFIRMED.** `bounce_count` is at `merge_authority.py:1132-1149` and counts `pr-bounced` events
  in `audit/log/`. The PR routing block is at `bin/hos-cron:1079-1109`.
- **VF-C8 CONFIRMED.** `validation_logic.fingerprint` is at `:223`, `load_ledger` at `:272`, and
  `self_review_source.fingerprint` at `:33`.
- **VF-C9 CONFIRMED, plus a sanctioned continuation the amendment did not list.** The rules at
  `worker-cron-prompt.md:110` and `:133` stand. Step 1 also states that "Pushing a fix here **updates a
  PR this bot already authored** … it does not make the branch this cycle's to submit (#967)". Pushing a
  new round onto the worker's own open PR is therefore already sanctioned. That is what makes REQ-C20
  satisfiable for code rounds without any structural change to #967 (AD-C13).
- **VF-C10 CONFIRMED, with one fact changed.** The primitive exists (`scripts/automation/agent_invoke_cli.py`,
  `bootstrap/invoke_agent.sh`). `KNOWN_POSTURES = {review-read-only, review-read-only-gh-read}`,
  `DEFAULT_TIMEOUT_S=300` and `MAX_TIMEOUT_S=1800`. **ADR-1643 AD-9's registry loader does not exist:**
  `contract/dimensions/` contains only `postures/`, and nothing references `dimension_registry`. §4
  records the consequence.
- **VF-C12 CONFIRMED live.** #1601, #1602, #1604, #1354, #1520 and #1542 are open. #1352 is open in
  **v0.7.4**.
- **VF-C13 CONFIRMED.** `scripts/run_review_chain.sh:240-244` runs agy at MEDIUM+ and codex at HIGH+,
  and skips second review below MEDIUM. `worker.md:379` (step 8.4) says the same.

### My own findings. These change the design.

**AF-C1 (HIGH: the amendment's open cost question is answered, and blocked-ness is free).** A live probe
of the **list** endpoint (`repos/.../issues?state=open&labels=needs-ai&per_page=3`) shows that every list
record carries `issue_dependencies_summary: {blocked_by, blocking, total_blocked_by, total_blocking}` and
`sub_issues_summary: {total, completed, percent_completed}`. The selector already fetches that record.
So "has an open blocker" (`blocked_by > 0`) and "is a parent" (`sub_issues_summary.total > 0`) cost
**zero** added requests. REQ-C11's zero-cost rule holds for the common case without any design effort.
Two caveats bind the design:
1. `blocked_by` counts **open** blockers. A blocker closed as `not_planned` drops out of it, which is not
   ESC-3's "merged to main". Whenever `total_blocked_by > blocked_by`, satisfaction must be verified with
   a paid check (AD-C14).
2. These fields are GitHub API surface that HOS has never depended on. If they are absent or malformed,
   the result is **DEGRADED** ("unknown"). It is never "not blocked" (AD-C4).

**AF-C2 (HIGH: ESC-8's exception cannot be met without touching #1198's serialization).** `bin/hos-cron`
blocks **all** new work whenever the worker has any open PR in `awaiting-merge` (approved, waiting for a
*human* merge) or `needs-attention`. The routing is at `:1113-1128`, and any open worker PR makes the
directive print `NEW WORK: BLOCKED` at `:1949`. #1847, which is open, adds that a HUMAN_REQUIRED overseer verdict is
misrouted to `needs-attention`. A PR waiting on a human therefore idles the worker today, which is the
exact behavior ESC-8's exception prohibits. #1198's body says why the rule exists ("a cheap, blunt defence
against the stale-base failure … **Do not simply remove the serialization**") and names #1162 as the
prerequisite for relaxing it. #1162's merge-from-base guard is now present (`bootstrap/submit_pr.sh:185-202`).
Relaxing the rule is a product and safety tradeoff that the ruling implies but does not state, so it goes
to the human (**ARCH-ESC-1**).

**AF-C3 (HIGH: the pending-actor label is the cheapest possible "waiting" signal).** The selector queries
`labels=<pending-actor>` (`list_endpoint` in `main`). An issue that is not in the worker's court never
appears in the query, so it costs nothing to exclude. Moving an issue into the overseer's or the human's
court is therefore how "waiting" becomes invisible to selection at zero cost. That supports REQ-C10 as a
mechanism, not only as tidiness.

**AF-C4 (HIGH, security: under the ESC-7 stopgap, the worker's model session holds the same identity
REQ-C15 trusts).** The worker session runs as `"$CLAUDE_BIN" --print --permission-mode bypassPermissions`
(`bin/hos-cron:1849`) and can mint the worker App token (`bootstrap/get_app_token.sh`). REQ-C15 trusts
routing state "written by the HOS worker identity". That identity cannot distinguish the deterministic
executor from the model session running under it. A model session could therefore write a round record
or a stage label that code would accept. AD-C13 binds a detective control, and **ARCH-ESC-2** asks the
human to accept the residual until #1542.

**AF-C5 (MEDIUM: `diff_size.py` cannot be a pre-code trigger).** The module takes only diff metadata
flags and performs "NO git calls and NO filesystem/content reads" (docstring). Its R1 floor is
`changed_lines > 400 OR changed_files > 15` (`_DEFAULT_DIFF_SIZE_FLOOR`, `_DEFAULT_FILE_COUNT_FLOOR`), and
both can be raised by environment variable. Three consequences:
1. It can fire only after a diff exists.
2. It is a trigger, not a safety floor, because configuration can quiet it.
3. Design documents routinely exceed 400 lines, so it must be scoped to code rounds.

AD-C15 is built around all three.

**AF-C6 (MEDIUM: draft PRs are the right code-round carrier, but the canonical path to them is
missing).** The overseer's pre-filter skips drafts (`HOS_ACTIONABLE_PRS | skipped (conflicting/draft)`,
`bin/hos-cron`). `merge_authority.py` already opens draft PRs (`open_draft_pr`, `:750`) and converts PRs
to draft through GraphQL (`_convert_pr_to_draft`, `:1176`), because "No REST endpoint supports this".
`bootstrap/submit_pr.sh` has no `--draft`, and no canonical script marks a PR ready for review.

**AF-C7 (MEDIUM: the base ESC-6 ruling and its addendum describe the base grant differently).** The base
ruling says "grants a fresh round budget". The addendum calls the base case "one more round" and adds a
broader "full reset". AD-C8 binds the tighter reading. ARCH-ESC-5 asks the human to confirm it.

**AF-C8 (MEDIUM).** `worker-cron-prompt.md:104` permits batching several issues in one unit ("≤15
files/10 commits"). That cannot coexist with one stage of one issue per cycle. T3.9 retires it for staged
work.

**AF-C9 (LOW, but it is the ESC-3 addendum's motivating case).** #1880 is closed, merged, and still
carries `needs-human`. The label was present and forced nothing. A label on a merged PR is not a forcing
signal, which is why AD-C10 files a *separate* question issue and blocks on it.

### Measurement taken this session

`audit/log/2026/09/` holds 1,709 `cycle-start` records from filename timestamps, for all roles in this
clone. The median interval is **602s**, n=1,698 intervals under 2h, minimum 534s. There are 5
`cycle-claude-timeout` records (about 0.3%). This matches ADR-1643 §0's 601s, and §3's latency arithmetic
uses it. The records show zero overseer `cycle-start`s, as expected: the overseer runs in its own clone.

### Verification gaps I could not close. `technical-design` must probe these before binding the named AD.

- **How to resolve a sub-issue's parent, and whether `parent_issue_url` appears on a child's list
  record.** No sub-issue exists in the last 100 issues, so there was nothing to probe. Affects AD-C16.
- **Timeline event types, and their actors, for adding and removing dependency edges and sub-issue
  links.** Not probed. Affects AD-C5 and AD-C14. AD-C14's asymmetry argument is written so that the
  design is safe even if those events are unavailable.
- **Whether a reaction moves a comment's `updated_at`.** AD-C7 treats an edited record as untrusted. If
  reactions bump `updated_at`, the edit test needs a body-hash check instead.
- **Whether a plan-stage agent that attempts `Write` under `review-read-only` trips AD-4's A5
  (`permission_denials`) and fails closed.** `pm-agent`, `architect` and `technical-design` all have CORE
  text that tells them to write documents. AD-C12 depends on this, and T3.7a's first act is to measure it.
- **No behavior was run under `bin/hos-cron`.** Every cycle-shape claim in this ADR comes from reading
  source.

---

## 1. Context: what is actually being decided

The Q4+Q6 ruling turned #1644 from "a script that loops" into "a queue that advances one step per cycle",
and ADR-1643 AD-12 already drew the line: the worker gets its **own runner** and its **own registry
file**, sharing only the format, ownership model and loader. So this ADR is not about loops. It decides
four things:

1. **Where each fact lives** so that the next cycle can read it cheaply and trust it. The fact is the
   stage, the court (worker, overseer or human), a blocker, a round, or a human grant.
2. **Who may write each fact.** This is the trust boundary, and AF-C4 shows it is weaker than REQ-C15
   assumes.
3. **In what order a cycle reads and acts**, so that the worker never idles on a human and never runs the
   wrong stage.
4. **What the worst case costs**, stated as numbers.

The governing constraint is inherited from ADR-1643 §1 and from Q1: every fail-open becomes either a
stalled queue or an unreviewed change. So every "unknown" in this design resolves to one of two outcomes:
DEGRADED (reported, and nothing runs) or escalation. It never resolves to "not blocked", "round 1" or
"stage complete".

---

## 2. Decisions (BINDING on `technical-design`)

### AD-C1: The stage vocabulary and graph are declared data in `contract/stages/`, on ADR-1643 AD-9's loader. (REQ-C9, REQ-C10(c), REQ-C7(a); ESC-1, ESC-5 of 2026-09-14.)

**Vocabulary.** These names are binding, the label namespace is `stage:`, and it matches `priority:`.

| Stage | Agent binding (CORE) | Runs as | Exit 0 goes to | Exit 1 goes to | Notes |
|---|---|---|---|---|---|
| `plan` | `pm-agent` | primitive, `review-read-only` | `requirements` / `code` (direct, AD-C12 floor) / `tracking` (children) / `code` slice 1 (slice plan) | — | **Entry.** ESC-1: an issue with **no** stage label is treated as `plan`. |
| `requirements` | `pm-agent` | primitive | `architecture` after merge | — | Artifact PR goes to the overseer's court. |
| `architecture` | `architect` | primitive | `design` after merge | back edge to `requirements` | |
| `design` | `technical-design` | primitive | `code` after merge | back edge to `architecture` or `requirements` | |
| `code` | `coder` (session), then `code-reviewer` (primitive) | launcher session under ESC-7, then primitive | `converge` or `handoff` (AD-C11) | `code` in a later cycle | One round per cycle (ESC-4). |
| `converge` | cross-vendor second review | `run_second_review.sh` | `handoff` | `code` (a rejection is a round result) | Only when AD-C11 requires it. |
| `handoff` | none (a code transition) | executor | the overseer's court | — | Resume marker for bounces. |
| `tracking` | none | executor | — (non-selectable) | — | Parent of worker-filed children (REQ-C17(c)). |

The table's "Exit 0/1" columns are REQ-C6's outcomes. `3` means escalate (AD-C10) from any stage. A
closed issue is terminal. Back edges belong to one plan-phase loop per issue (the "design-chain loop"),
counted under AD-C8.

- **File layout mirrors AD-9.** `contract/stages/core.yaml` is CORE and installer-owned,
  `pack-<name>.yaml` is PACK, and `project.yaml` is PROJECT and consumer-owned. `contract/**` is already a
  protected surface.
- **The ESC-5 (2026-09-14) rule applied to a graph:** only CORE declares stages and transitions. A PACK or
  PROJECT file may **rebind** the one agent that serves a stage, but it must name a shipped agent (AD-3).
  It may lower a cap, add labels to the design-required set (AD-C12), and lower `max_children` and
  `max_slices`. It may never remove a stage, remove a transition, add a transition, or raise any bound.
- **Each stage resolves exactly one agent binding.** Unlike AD-9's fan-out, where every matching binding
  fires, a stage binding replaces the one below it. Suppressing a stage binding without replacing it is a
  **load error**, because a stage with no agent is the required-to-do-nothing trap in graph form.
- **Load-time checks, all fail-closed.** The loader rejects: an unreachable stage; a non-terminal stage
  with no outgoing transition; a PROJECT or PACK file that declares or removes a stage or transition; a cap
  above its documented maximum; and a stage whose declared invocation timeouts plus the declared margin
  exceed the cycle budget (REQ-C7(a)). The cycle budget is runtime configuration
  (`HOS_CRON_MAX_SECONDS`), so the fits-one-cycle check runs **again when the executor starts**, against
  the live value. A failure there stops the stage before any model turn and escalates to the operator.
  It does not start the stage and hope.
- **One loader, not two.** See §4 SEAM-1.

### AD-C2: Three facts, three carriers. The stage is a label on the issue, the court is the pending-actor label, and history lives in worker-authored records. (REQ-C10, REQ-C14; AF-C3; ESC-5.)

- **Court.** The pending-actor label (`needs-ai` today, `needs-worker`/`needs-overseer` after #1520) is
  the **only** eligibility and authorization carrier (REQ-C10(a)). The executor moves an issue into the
  overseer's court when it opens a stage's artifact PR or hands off a converged code PR. It moves the
  issue into the human's court (`needs-human`) whenever it escalates. The human's court is the existing
  `EXCLUDED_LABELS` path.
- **Stage.** Exactly one `stage:*` label, on the **issue**, never on the PR. There is one carrier and so
  nothing to drift.
  - **REQ-C10(b) rule, bound:** the stage label is **kept** when the issue changes court, as the
    "resume here" marker, and it means nothing outside the worker's court.
  - A stage label never makes an issue eligible, never authorizes it, and never overrides `needs-human`.
- **History.** Round and stage records are issue or PR comments written by the executor (AD-C7). **The
  record is authoritative and the label is a cache.** The label exists so the free selector phase can
  route without paying for a comment read. When label and record disagree, AD-C5 decides which wins.
- **Code rounds live on the PR.** Once a code round has a PR, its records go on that PR (REQ-C14). The
  stage label stays on the issue.

### AD-C3: One cycle has one fixed shape: reconcile, classify PRs, select, pre-check, execute exactly one stage, finalize. The executor is protected L2 Python plus L3 bash, called by `bin/hos-cron`. (REQ-C1, REQ-C8, REQ-C11, REQ-C18; ADR-1643 AD-1 tiering; ADR-1604 AD-1.)

- **Location.** L2 is `scripts/framework/stage_executor_cli.py`, which decides eligibility, caps, trust
  and transitions. It therefore lives on the **protected** `scripts/framework/**` surface, beside the S2
  gate it composes with. L3 is `bootstrap/run_stage.sh`, with fixed argv, no logic, and pass-through exit
  codes, following ADR-1643 AD-1/AD-1a. `bin/hos-cron` calls L3 and does not grow the logic in bash.
  - **Cross-ADR note.** ADR-1604 AD-1 placed its reconcile module under `scripts/automation/lib/`, which
    is unprotected. The splitter and reconcile it describes are unified with this one (AD-C15), and the
    trust-relevant parts land under `scripts/framework/`. ADR-1604 is unbuilt, so nothing is orphaned.
    ADR-1604's `technical-design` must read this ADR.
- **The worker cycle, in this order, and the order is part of the contract:**
  1. **Reconcile** (deterministic, no model). For each issue in the overseer's court that carries a
     `stage:*` label, read the PR named by its latest trusted record:
     - PR merged: advance the stage per `next_stage_on`, run the ESC-3 addendum check (AD-C10), and move
       the issue back to the worker's court.
     - PR bounced: move the issue back to the worker's court at `code`.
     - PR closed without merge: escalate.
     - PR still open: do nothing.

     The same sweep also does the ADR-1604 AD-10 tracking-parent close, the AD-C5 grace-period escalation
     of malformed state, and the consumption of human grants (AD-C8). All of it runs within a per-cycle
     request budget, and running out of budget is DEGRADED.
  2. **Classify worker PRs** (T3.0b; AD-C6). The existing bash routing moves into a tested Python
     classifier.
  3. **Select** with `select_work_candidates.py` (AD-C4). Its free phase gains the stage checks.
  4. **Pre-check** candidates in emitted order (AD-C5). The first candidate that passes is this cycle's
     stage. A failure goes to the **next candidate**. It never goes to a model.
  5. **Execute** exactly one stage (AD-C12, AD-C13).
  6. **Finalize**: record first, then labels (AD-C7).
- **One stage per cycle, and nothing else builds.** When a stage has run, the worker's model session is
  launched (if at all) with `NEW WORK: BLOCKED` and does Step 0 triage only. The one exception is the code
  stage, whose session *is* the stage (AD-C13). The cycle cannot run two work items.

### AD-C4: The selector's free phase gains stage parsing, native-blocker and parent exclusion, and in-flight-first ordering, at zero added requests. (REQ-C11, REQ-C12, REQ-C16 fast path, REQ-C18; ESC-1, ESC-8; AF-C1.)

These additions all run in D1/D2, before D-rank and before any paid D5 request. The existing request
budget, the exit-code contract (0/2/3) and the stderr report contract are **unchanged**. The only changes
are new reason tokens and the ordering key.

- **Stage parse.** No `stage:*` label means `plan` (ESC-1) and "new". Exactly one known stage label means
  that stage and "in-flight". More than one stage label, or an unknown `stage:` label, means **excluded**
  with reason `stage-malformed`. A `stage:tracking` label means excluded with `tracking-parent`.
- **Native blockers.**
  - `issue_dependencies_summary.blocked_by > 0`: excluded, `blocked-by-open-issue`.
  - `total_blocked_by > blocked_by`: excluded, `blocker-closed-unverified`, **until T3.3** lands the paid
    satisfaction check. Before T3.3, a closed blocker never unblocks. The probe found no edges in use
    today, so this costs nothing now.
  - The summary is **missing or malformed**: the record is **unevaluated**, which gives `complete=no` and
    DEGRADED when nothing else is emitted. It is never "not blocked".
- **Parents.** `sub_issues_summary.total > 0` without `stage:tracking` means excluded with
  `untracked-parent`. An epic with children is not leaf work, and ADR-1604 AD-10 lets a human opt one in.
- **Graph contradiction** (REQ-C12). A stage at or past `code` while `blocked_by > 0` is already excluded
  by the blocker rule. It is reported under that reason. It is not a separate path.
- **Ordering (REQ-C18, ESC-8).** Both the walk key and the emit key gain a leading in-flight class.
  - WALK becomes `(inflight_class, rank, -number)`. EMIT becomes `(inflight_class, rank, number)`.
    `inflight_class` is 0 for in-flight and 1 for new. The rest of each key is #901's order within the
    class.
  - The walk key must change too. Otherwise the D5 sufficiency stop (`max_candidates`) could fill up on
    new issues before it reaches an in-flight one.
  - **Every exclusion above runs before ranking.** This is what makes ESC-8's exception structural
    (AD-C6).
- **Every emitted candidate carries its stage.** The stdout line becomes `#N [priority] [stage] title`.
  The title is still sanitized.
- **Label-actor verification is NOT done here.** It costs events requests. It runs in the pre-check, for
  the chosen candidate only (AD-C5). That is how REQ-C11's zero-added-cost acceptance criterion and
  REQ-C15's actor rule are both met. pm-agent follow-up PM-2 records the acceptance-criterion wording.

### AD-C5: The pre-check pays for trust on one candidate, just before the stage, and never costs a model turn. (REQ-C2(c)(d), REQ-C13, REQ-C15, REQ-C14 reconciliation.)

For the candidate being considered, and within the cycle's request budget, the pre-check does the
following. **Every check reads live state. Nothing is cached** (FR7 of S2).

1. **Re-reads the live stage label** and confirms it matches the selector's emission (REQ-C13 race).
2. **Verifies the actor** of the current `stage:*` label (REQ-C15). Its latest `labeled` event must come
   from the worker App **and** be corroborated by a worker-authored record naming that transition. The
   alternative is that its actor is a verified individual human CODEOWNER, using the same
   `verify_codeowner_actor` semantics, bot exclusion included.
   - A CODEOWNER re-route **wins over the record**. That is the human back edge #1354 decided. The
     executor writes a record acknowledging it and runs from there.
   - Any other actor, including the human-proxy App, `github-actions[bot]` and any collaborator, makes the
     state **malformed**.
   - Worker-App labels with **no** corroborating record are also malformed (AF-C4, AD-C13).
3. **Parses the round and stage records** (AD-C7) and derives the loop counts and epoch (AD-C8). An
   unreadable, contradictory, edited or unverified record counts as **at cap**, so the issue escalates.
   It never counts as round 1 (REQ-C2(d)).
4. **Checks the declared preconditions.** Code rounds need the input artifacts on `origin/main`, which is
   a local git read at zero API cost. Live native edges must include every edge in the tracking block
   (AD-C14).
5. **Detects "done but unrecorded"** (REQ-C14).
   - An open worker PR whose machine marker names this issue and stage, with no record for it, means the
     stage ran. The executor **writes the record from the PR** and advances. **It does not re-run.**
   - A code PR head that moved past the last recorded head with no round record means the coder ran. The
     executor runs **only** the post-session half (AD-C13) against that head.

**Outcomes.** A pass runs the stage. A mismatch or failed precondition means **no invocation, no branch,
no commit, no label change**, one audit event, and then the next candidate. It is not a round and not a
stage outcome.

**Escalating persistent corruption.** REQ-C13 asks for escalation after N consecutive mismatches. A
durable N would need either an audit read, which ADR-1643 AD-8 and ADR-1604 AD-4 forbid, or a GitHub
write on mismatch, which REQ-C13 forbids. **Binding replacement:** malformed state whose offending event
is older than a **grace period of 2 × the configured cron interval** is escalated, by the pre-check or by
the reconcile sweep. Malformed state younger than that is skipped silently. The time is derived from the
GitHub event timestamp, so it is stateless and survives the loss of any clone. This is equivalent to
REQ-C13's recommended "2 consecutive cycles" and is recorded as pm-agent follow-up PM-3.

### AD-C6: ESC-8's exception holds by construction, because exclusion always precedes ordering, and it is pinned by tests. (ESC-8; REQ-C18; AF-C2.)

**The property.** An item that is waiting on a human is never a candidate. A candidate therefore can
never be one, and in-flight-first ordering can never select one. Each human-blocked shape is excluded
**before** the sufficiency cut:

| Shape | Carrier | Excluded where | Slice |
|---|---|---|---|
| H1: escalated or waiting on an answer | `needs-human` on the issue | D2, free | exists |
| H2: blocked on an open issue, including a question issue (AD-C10) | `blocked_by > 0` | D2, free | T3.0a |
| H3: the stage PR is waiting on a human merge | the issue is in the overseer's court | not listed, free | T3.1/T3.7a |
| H4: a worker PR is waiting on a human (HUMAN_REQUIRED, `needs-human` on the PR, awaiting a human merge) | PR classifier | no longer sets `NEW WORK: BLOCKED` | **T3.0b, gated by ARCH-ESC-1** |
| H5: legacy, prose-only human waits (the 2026-09-30 case) | none today | T3.0a adds `bootstrap/escalate_to_human.sh`, which posts the question and applies `needs-human` in record-first order, so that future waits become H1 | T3.0a |

**Required tests.** These are part of the slice gates named, and "the exception is not incidental" means
they exist and fail if the property breaks.
- **T-NS1:** in-flight issue A (`priority:critical`, `stage:architecture`, `needs-human`), in-flight B
  (`critical`, `stage:code`, `blocked_by=1`), and new C (`low`, no stage). Emitted is exactly `[C]`.
- **T-NS2:** in-flight D (`low`, `stage:design`, actionable) and new E (`critical`). Emitted is `[D, E]`,
  so in-flight beats priority.
- **T-NS3 (the sufficiency cut):** six human-blocked in-flight issues and one new eligible issue at
  `max_candidates=5`. The new issue **is** emitted.
- **T-NS4:** a replay of 2026-09-30. The top two candidates (#1643 and #1644 shapes) are human-blocked,
  the others are eligible, and the first eligible one is emitted.
- **T-NS5 (T3.0b):** the worker has one open PR in each H4 shape plus an eligible issue. The directive is
  `NEW WORK: ALLOWED`. This also closes #1847.
- **T-NS6 (T3.2):** the pre-check rejects candidate 1, and the executor runs candidate 2 in the same
  cycle.

The residual is bounded rather than hidden. A pre-check rejection (AD-C5) is transient, because it
escalates to H1 within the grace period. So the most it can cost is a few cycles in which up to five
malformed in-flight items fill the candidate list. It cannot cost a permanent stall. T-NS3 pins the
steady state.

### AD-C7: Round and stage records are envelope comments written by the executor, trusted by the API-verified author, and invalid once edited. The record is written first, the label last. (REQ-C14, REQ-C2(a), REQ-C15.)

- **Format.** Each record is a `scripts/automation/lib/envelope.py` machine-readable block (`---hos-envelope`)
  with a record type, posted through `bootstrap/post_comment.sh --app worker --body-file`, with
  idempotency from `correlation.py`. Reads go through `bootstrap/query_issues.sh --comments` or
  `scripts/automation/lib/github.py`. **No new mechanism** (ADR-1643 AD-14 precedent).
- **Minimum content (REQ-C14):**
  - issue, stage, and loop identity (loop kind, change/slice id, epoch);
  - round number;
  - the REQ-A8 verdict and outcome;
  - the blocking fingerprint set plus `fingerprint_version` (AD-C9) and the blocking count;
  - artifact identity (PR number plus head SHA, or artifact path plus blob SHA);
  - the `input_digest` of the reviewer invocation, and the trigger for any transition.
- **Trust.** A record counts only if the GitHub API reports its author as the worker App (the
  `envelope.py` header rule) and `updated_at == created_at`. An edited record is untrusted, which means
  escalation (REQ-C15). See the §0 gap on reactions.
- **Write order, which is binding and copies SPEC-378 halt-on-failure:**
  1. push, or open or update the PR, carrying the machine marker;
  2. post the record, and confirm it by reading it back;
  3. change the labels (stage, then court);
  4. write the audit event.

  If step 1 or 2 fails, the cycle halts before step 3. A failure at step 3 is repaired on the next cycle
  from the record (AD-C5.5). **"Done but unrecorded" and "not done" are always distinguishable**, because
  the PR marker precedes the record and the record precedes the label.
- The clone-local audit log may mirror records. **No decision reads it** (ADR-1643 AD-8).

### AD-C8: Caps, epochs and human grants. There is one budget per change, bounces spend it, and only a verified human act refills it. (REQ-C2; ESC-6 and its addendum; AF-C7.)

**Bounds.** Each is CORE, has a documented maximum, and PROJECT may only lower it (minimum 1). There is
no environment variable or flag that can disable any of them.

| Bound | Default = documented maximum | Counts |
|---|---|---|
| `code_round_cap` | **3** | Code rounds per change per epoch. **Bounce re-entries included.** |
| `design_chain_cap` | **3** | Passes through the plan-phase loop per issue per epoch. A back edge, or an overseer bounce of a stage PR, is one pass. |
| `max_children` | **5** | Children per decomposition. |
| `max_slices` | **5** | Code slices in one issue's slice plan (AD-C15). |

- **Reading the count.** The count is derived only from trusted records whose loop identity matches:
  `round = count + 1`. It is read before any model turn (REQ-C2(c)). A loop at cap goes straight to
  escalation, and nothing is invoked.
- **REQ-C2(g) composition, bound.** The worker's `code_round_cap` **subsumes** re-entry after an overseer
  bounce. A bounced change re-enters `code` against the **same** budget. It does not get a fresh loop.
  The overseer's `bounce_count(cid) < 2` is unchanged, independent, and #1643's to own. Whichever runs out
  first escalates.
  - Example: round 1 converges, then bounce, round 2, bounce, round 3, and a third bounce is escalated by
    the overseer.
  - Another: round 1 needs two rounds and a bounce arrives with no budget left. The worker escalates.
- **Epoch and human grants.** ESC-6, its addendum, and "no bot can reset" apply. A grant is valid only as
  a `labeled` event on the issue, **after** the escalation record, whose actor is a verified individual
  human CODEOWNER, checked with the same test as S2 (bot exclusion covers the human-proxy App). Each event
  id is consumed **once**, and the consuming record names it.
  - **Resume** means the CODEOWNER re-applies the pending-actor label after the escalation. It grants
    **one additional round** for the loop that escalated. Stuck detection still compares against the
    prior record. This is the tighter reading of AF-C7; see ARCH-ESC-5.
  - **Reset** means a CODEOWNER applies the dedicated reset label (`hos:round-reset`; the literal is
    `technical-design`'s) together with a resume. It starts a new epoch, which gives a full budget and a
    **fresh stuck baseline**. Prior records are kept and shown in escalations, but they are excluded from
    comparison. This is the addendum's "entire round history was compromised" case.
  - A second exhaustion within an epoch escalates again. **No code path increments an epoch except
    consumption of such an event.** A test asserts that a worker-App or human-proxy-App label applied at
    the same point grants nothing.

### AD-C9: Stuck detection uses exactly `validation_logic.fingerprint()`, never `load_ledger()`, and a fingerprint-version change is treated as unreadable. (REQ-C3, REQ-C4; Q5; ADR-1643 AD-6.)

- **One function.** `scripts/oversight/validation_logic.fingerprint` is used, as ADR-1643 AD-6 already
  binds for the shared layer. `self_review_source.fingerprint` is never imported by the loop.
  - A test asserts that the executor's import graph contains neither `load_ledger` nor
    `self_review_source.fingerprint`. This mirrors TD-1643 T2.8.
- **`fingerprint_version`** is carried in every record. Consecutive records with different versions are
  **unreadable**, so the loop is treated as at cap and escalates. Without this, an upgrade in the middle
  of a loop would make every comparison "different" and silently disable criterion (i). That is exactly
  the fail-open VF-C8 warns about.
- **The criteria, operationalized.** Each compares the current round with the previous trusted record in
  the same epoch:
  - **(i)** any blocking fingerprint recurs;
  - **(ii)** the blocking count does not strictly decrease;
  - **(iii)** the artifact identity changed (head SHA and reviewer `input_digest` both differ), yet the
    verdict **and** the blocking fingerprint set are identical.

  **(iii) is read strictly on purpose.** Read loosely ("the verdict value is unchanged"), it would fire on
  every second round that ends in `request_changes`, which would make the cap 2 in practice. Read
  strictly, it catches a reviewer returning a byte-identical judgment to changed code, which is the
  "reviewer isn't reading the diff" failure. pm-agent follow-up PM-4.
- **Recurrence always wins** (Q5). A finding marked `fixed` anywhere, recurring in round N+1, fires (i).
- A convergence-confirmation rejection (AD-C11) is a round result and feeds the same comparison.
- **T3.5 gets its own TD section and an adversarial review.** This is the highest-subtlety item in the
  set, as the amendment says.

### AD-C10: Escalation is one code path. It applies `needs-human` in the same operation, names its trigger, and links every round. Open questions in a merged document become a blocking question issue. (REQ-C5; ESC-3 addendum.)

- **Every exit-3.** This covers cap, stuck (naming the criterion), invocation failure (Q1), malformed
  state past its grace period, a closed-unmerged stage PR, a second-level split, and a failed planner.
  Each one posts the escalation record, containing the trigger, links to every round record for the loop
  (across epochs, with epochs marked), and what recurred. **Then it applies `needs-human`**, in record-first
  order. A test fails if the trigger or any link is missing (REQ-C5 acceptance criterion). The issue
  leaves the worker's court in the same operation, which is what makes H1 hold (AD-C6).
- **ESC-3 addendum, and where it is enforced.** "Merging is never itself an answer." The enforcement has
  four parts:
  1. **At stage execution.** A plan-phase agent's result carries a structured `open_questions[]` in its
     stage output (§4 SEAM-2). If the list is non-empty, the executor files one **question issue**
     (`create_issue.sh --app worker`, labeled `needs-human`, listing the questions, linking the stage PR),
     adds it as a **native blocker** of the source issue, and renders the question list into the artifact
     as a machine-readable block. The human therefore sees the questions **before** the merge.
  2. **At merge reconciliation (AD-C3 step 1).** The executor re-parses the **merged** artifact's
     question block, which catches questions a human added during review. Any question with no question
     issue gets one, and a blocker, before the stage advances.
  3. **Satisfaction.** A question issue is satisfied **only** when a verified individual human CODEOWNER
     closes it as completed, as shown by the `closed` event's actor. **A merge never satisfies it.** This
     is the addendum's own principle, and it differs deliberately from ESC-3(a)'s rule for spec-issue
     blockers. Closing by the human-proxy App does not count (ARCH-ESC-6).
  4. **Answers.** They reach the next stage only as input-file content assembled by code: the question
     issue's comments by verified CODEOWNER authors. They never arrive as primitive state (REQ-C21).
- **Scope limit, stated.** This covers **staged** artifacts. A document merged outside the stage graph
  (this ADR, for example) is not covered by any mechanism #1644 builds. That coverage needs a REQ id and an
  owner (pm-agent follow-up PM-1). Until then the orchestrator must file the question issue by hand (§10).

### AD-C11: Convergence confirmation. The worker requires it when a loop iterated twice or more, at any tier, or at MEDIUM+ as today. The overseer's threshold is independent configuration that can only be tightened. (REQ-C5b; ESC-9.)

- **Worker side (ESC-9 option (b)).** After an approving round, confirmation is **required** if the rounds
  in this epoch are **≥ 2**, or if the change's tier is **≥ MEDIUM**. The second condition is the existing
  step-8.4 gate, which is kept and not replaced.
  - The tier is computed by code from `run_validators.sh` output on the changed files (the `tier_floor`
    and composite). The risk-assessor may only raise it.
  - If confirmation is required, the next cycle runs `converge`. Otherwise the change goes straight to
    `handoff`.
  - `min_rounds = 2` is a CORE bound. PROJECT may lower it to 1 (every loop), never raise it.
- **Arms.** These are `run_review_chain.sh`'s mapping evaluated at `max(tier, MEDIUM)`: at least agy, and
  codex at HIGH+. All arms run in **one** stage (REQ-C5b).
  - A rejection is a round result: the issue goes back to `code` and the next round counts.
  - An invocation failure is exit 3 (Q1).
  - The verdict is read from the **nested reviewer payload, never the header line** (#1737's defect
    class). A prompt that the vendor path truncates must fail closed. #1718 is open and critical, and
    T3.6 depends on its fix or on an explicit size guard.
- **Overseer side.** There is a new key in `scripts/framework/machine-accounts.env`, loaded and validated
  by `scripts/automation/lib/merge_config.py` beside `OVERSEER_CEILING`: `CROSS_VENDOR_MIN_TIER`, whose
  literal is `technical-design`'s.
  - Allowed values are `LOW` and `MEDIUM`. The default is `MEDIUM`, which is today's behavior.
  - **A value looser than `MEDIUM`, or any unparseable value, is a fail-closed config error.** "Can be set
    higher" is read as *more rigorous*, per the ratchet.
  - It parameterizes ADR-1643 AD-10's `cross-vendor-review` entry on the overseer's runner and is
    independent of the worker-side rule. Implementing it is T3.6b, coordinated with ADR-1643 W7. It does
    not amend ADR-1643.
- **Revisit trigger.** When the Local Inference Lane (v0.7.2) lands, the worker's `min_rounds` default is
  re-evaluated toward 1, per the ruling's own note. That is a named obligation, not a silent default.

### AD-C12: Plan-phase stages run through the primitive, read-only. Code writes every artifact, commit, PR and label. The "skip the design chain" route has a deterministic floor. (REQ-C1, REQ-C8, REQ-C20, REQ-C22; Q3; VF-C3.)

- **Execution.** `plan`, `requirements`, `architecture` and `design` are each **one**
  `bootstrap/invoke_agent.sh` invocation under `review-read-only`.
  - The **input file** is assembled by the executor from the issue body, which is handled as untrusted
    input per the pm-agent CORE rule, and from trusted prior records, prior artifacts on `origin/main`,
    and verified human answers (AD-C10).
  - The agent **returns** its artifact, its routing decision and `open_questions[]` in the strictly parsed
    stage output. **It writes nothing itself.**
  - The executor writes the artifact file, commits on a branch it creates with `create_branch.sh`, opens
    the PR with `submit_pr.sh --app worker` (`Refs #N`, **never** a closing keyword, per #1856), writes the
    record, and moves the issue to the overseer's court.
- **Why read-only is enough.** The agent never needs write authority, because code does every write. That
  makes REQ-C22 fully satisfiable today for plan stages, with no new posture. **T3.7a's first
  deliverable is the §0 measurement:** do these agents' CORE "write the document" instructions trip AD-4
  A5? If they do, the input contract must say "return, do not write", and a persistent A5 is a finding
  for me, not something to work around locally.
- **Back edges.** An upstream-insufficient verdict (`architecture` or `design` rejecting its input) is
  exit 1. The stage moves back per the graph within the design-chain loop, and counts under AD-C8.
- **The direct-code floor (VF-C3; worker.md:377's "when uncertain, treat it as spec/behavioral").** `plan`
  may route directly to `code` **only if** the issue carries a label in the CORE **direct-code allowlist**
  and none in the **design-required set**.
  - The CORE allowlist is `{bug}`. The design-required set is `{enhancement, process-gap, epic}`.
  - PROJECT may add to the design-required set. It may never add to the allowlist.
  - A planner verdict of "direct" on any other issue is overridden by code to `requirements`, and the
    override is recorded.
  - This makes today's model-judged self-exemption (#556) structurally impossible. Its latency cost for
    unlabeled tweaks is **ARCH-ESC-4**.
- **Resuming legacy issues.** `plan` may choose a later entry stage. It is admitted only if that stage's
  artifact preconditions already hold on `origin/main`, which code checks (AD-C5.4). #1644 itself, whose
  requirements have merged, can therefore enter at `architecture`, and nothing can enter at a stage whose
  inputs do not exist.

### AD-C13: The code stage is one round per cycle. The coder runs in the launcher's session under the ESC-7 stopgap, and the executor then judges the round. The carrier across cycles is a draft PR. (REQ-C1, REQ-C19, REQ-C20, REQ-C22; ESC-4, ESC-7; AF-C4, AF-C5, AF-C6.)

**Session half.** The coder runs in the launcher session under the stopgap. `bin/hos-cron`'s existing
`claude --print --permission-mode bypassPermissions` session is launched with a **code-round directive**
computed by the executor. The directive names the issue, the round, the draft PR, and the prior round's
findings, which are assembled by code.
- The session's only permitted work is to dispatch `coder` and push to that PR. It uses Step 1's
  sanctioned "push to a PR this bot already authored" path for round 2 onward (VF-C9), and
  `create_branch.sh` plus `submit_pr.sh --draft` for round 1.
- The `bypassPermissions` use is **recorded as the Q3/ESC-7 stopgap, with its reason**, in the launcher
  comment and in each round record. It is **re-evaluated at v0.7.0's release** and then under #1542, per
  Q3's "reconsidered every time".
- The primitive continues to refuse `bypassPermissions` (ADR-1643 AD-7), and the coder does not go
  through it until a scoped posture exists. **This is the one bound deviation from REQ-C1's "each stage
  is a REQ-A invocation".** It is time-boxed, and it is the half of the round that decides nothing.

**Judged half.** After the session exits, the executor does the following, deterministically:
1. verify that the PR head moved (if it did not, the coder produced nothing, which is REQ-C13's "not
   applicable", so escalate);
2. run `run_validators.sh` and the gates **on the changed files**;
3. apply the **`diff_size` backstop** (AD-C15);
4. invoke `code-reviewer` through the primitive under `review-read-only` on the head SHA;
5. run the inner-loop tests;
6. write the round record.

The round verdict combines the reviewer verdict with gate and test failures. Those failures become
fingerprinted findings, so there is **no separate retry path** (REQ-C19).
- A timed-out session is a #1601 timeout, not a round (REQ-C7(c)). Its pushed commits stay on the draft
  PR. That is the #1602 checkpoint for this stage.
- The budget per ESC-4 is session cap plus reviewer cap plus validators plus margin, which must be ≤ the
  cycle budget. AD-C1's load check enforces it.

**Draft PR as carrier (AF-C6).**
- The PR stays **draft** while it is iterating, so the overseer never sees an unconverged round.
- At `handoff` the executor marks it ready through a canonical script, using the GraphQL
  `markPullRequestReadyForReview` mutation, which mirrors `_convert_pr_to_draft`. That script is new, in
  `bootstrap/`, and there is no REST alternative. The executor then moves the issue to the overseer's
  court.
- `submit_pr.sh` gains `--draft`.
- Only the **final** code PR of an issue, or of its last slice, carries a closing keyword.

**Detective control for AF-C4, bound regardless of how ARCH-ESC-2 is ruled.**
- Before writing a round record, the executor reads the issue's and PR's comments and label events for
  the model session's wall-clock window.
- **Any** worker-App routing write inside that window is treated as **tampering**, and the issue
  escalates. A routing write means a record-typed envelope, a `stage:*` or pending-actor change, or an
  edge change.
- The pre-check (AD-C5.2) separately rejects any worker-App `stage:*` label that has no corroborating
  record, on any issue, whenever it is next considered.

**What this does not stop.** A model session under `bypassPermissions` could still write a *consistent*
record-plus-label pair on a *different* issue, outside the watched window. What that buys it is more
worker rounds. It does not buy a merge: the overseer re-runs its dimensions in its own context (Q2,
ADR-1643 AD-15), and the human gates are untouched. ARCH-ESC-2 asks the human to accept that residual
until #1542 can withhold the App credential from the session.

### AD-C14: Blocking edges are native GitHub dependencies and sub-issue links. The parent's tracking block is the authority. ESC-3 decides satisfaction. (REQ-C16; ESC-3; ESC-5 #1352 pull-forward; AF-C1; ADR-1604 AD-8/AD-10.)

- **Storage.** Ordering uses native issue dependencies (`blocked_by`), and parenthood uses native
  sub-issues. Both are visible in the GitHub UI, and both surface free counters in the list record
  (AF-C1).
  - **The authority is the parent's worker-authored tracking block**, per ADR-1604 AD-8 and AD-10. That
    is one envelope record listing each child slug, number, and both sides of every edge.
  - Native links are the **enforcement mirror** and the child-side fast path. They are never the
    authority (ADR-1604 AD-10).
- **Asymmetry, which is why the design is safe even though edge actors are unverified (§0 gap).**
  - Adding a blocker or a sub-issue link can only **exclude** work. It is fail-safe from any actor.
  - Removing one could **unblock** work. So the pre-check requires live native edges ⊇ the tracking
    block's edges. A missing edge means malformed state, and the issue escalates.
- **Satisfaction (ESC-3(a)).** A blocker edge is satisfied iff the blocker is `closed` with
  `state_reason=completed` **and** its closure is attributable to a merge onto the default branch, or to
  a verified CODEOWNER closure.
  - Merge attribution is the `closed` event carrying a commit or PR reference on the default branch; its
    exact form is `technical-design`'s to probe. The CODEOWNER alternative uses the actor test.
  - `not_planned`, a duplicate closure, or a closure by an unattributable actor means **unsatisfied** and
    is reported. It never unblocks.
  - Question issues follow AD-C10's stricter rule.
  - This is the paid check behind AD-C4's `blocker-closed-unverified`. It is counted against the S2
    request budget, and running out of budget is DEGRADED.
- **Cycles and dangling edges.** A dependency plan is validated as acyclic **before** any write, at
  decomposition time. At pre-check a bounded blocker walk runs, where a cycle means escalate and an
  unresolvable reference means fail-closed with a report (REQ-C16).
- **Tooling. The #1352 slice is pulled forward into v0.7.0 as T3.3a (ESC-5).** Canonical, `--app`-scoped,
  `--body-file`-convention scripts are needed to:
  - add, remove and list a sub-issue link;
  - add, remove and list a `blocked_by` edge.

  Each extends `edit_issue.sh` / `query_issues.sh` or is a sibling of them, and **never** uses a
  hand-rolled `gh api`. The rest of #1352 stays at v0.7.4.
- **Prose retirement.** Once T3.3 lands, "first non-blocked candidate" is deleted from
  `worker-cron-prompt.md:96` and `bin/hos-cron:1979` (T3.9).

### AD-C15: One splitter with three triggers, using the human's decomposition principle. Coupled work becomes slices of one issue, and parallel work becomes children. The depth is one. (REQ-C17; ESC-2 principle; ADR-1604 AD-7 to AD-11; AF-C5.)

- **Triggers.** One assessment mechanism is entered three ways:
  - **(T1)** the `plan` stage, for every new issue;
  - **(T2)** the **`diff_size` backstop**, when a code round's actual diff fires R1 (`tier_floor=HIGH`).
    The round does **not** proceed to review. It exits to `plan` with reason `oversize` and the diff stats
    (AF-C5: it can only be post-hoc, and it applies only to code stages). The draft PR is kept as
    reference and is not merged. This happens once per issue. A second firing escalates.
  - **(T3)** ADR-1604 rung 1: two attributed timeouts.

  All three use the same assessment input contract, the same output type, the same record-first filing
  (ADR-1604 AD-8), and the same reconcile (AD-C3.1). **There is one implementation, which is T3.8,
  unified with ADR-1604 Phases 2 to 4.** ADR-1604 AD-7's default of no split on absent or invalid
  judgment is kept for T3. For T1 and T2, an absent judgment is Q1, so escalate.
- **Outputs.** These implement the human's "what would a human do" principle.

  | Output | When | Shape |
  |---|---|---|
  | `single` | Small and tightly coupled | One issue. The normal graph, even across several passes. |
  | `slices` | Big but tightly coupled: "split along sequential seams" | **One issue** carrying an ordered **slice plan** in its record. `code` runs slice by slice. Each slice is its own change, with its own draft PR and budget. Slice *k+1*'s precondition is slice *k* merged. **No child issues, so no trust question.** |
  | `children` | Genuinely parallelizable (could go to different people) | Up to `max_children` sub-issues. Edges only where a real ordering exists, and **both sides are recorded** (ADR-1604 AD-10). The parent becomes `stage:tracking`. |
  | `escalate` | The planner cannot decide | Exit 3. |

  Using slices for coupled work is my binding reading of "split along sequential seams instead: this is
  what the stage-per-cycle mechanism itself is for". It adds a structure the amendment did not name, so
  it is pm-agent follow-up PM-5.
- **Bounds.** Depth is **one**. A child cannot be split into children or slices, and a slice cannot be
  re-sliced. Each attempt escalates (REQ-C17, ADR-1604 AD-11).
  - Children inherit the parent's milestone. Their priority is **≤** the parent's, enforced by code, so
    that decomposition cannot be used to jump the queue.
  - Each child's entry stage is set by the planner but is subject to AD-C12's floor and precondition
    checks.
  - Children are created **with** their stage label and edges in the one recorded operation (REQ-C17(b)).
- **Size signal.** `diff_size.py`'s `evaluate()` thresholds are reused through its existing CLI. A second
  threshold implementation is not written. Environment overrides can quiet the trigger, and that is
  accepted, because it is a split trigger and not a safety floor (AF-C5).

### AD-C16: The S2 gate gains exactly one new admission path, for **worker-authored children of a currently authorized parent**. Everything else in S2 is unchanged. (ESC-2; ADR-1540-AMENDMENT-1 AM-10; ADR-1604 AD-9. **Security-relevant: this changes the selector's trust boundary.**)

**Today, re-verified.** Take an issue authored by the worker App and carrying no machine-filing marker.
`requester_verdict` returns `trusted-app-no-machine-filing-marker` (untrusted). The D5 walk pays for the
events and admits the issue only if a verified individual human CODEOWNER applied the pending-actor
label. A worker-filed issue is therefore never selectable without a human act.

**ESC-2 ruled** that a child created by the worker itself, "verified structurally (GitHub App
identity)", is trusted and selectable as-is, and that a child from any unknown or external actor is
untrusted, with no exception. **AM-10 already binds** that sub-issue filing never enters
`MACHINE_FILING_MARKERS`, and that a sub-issue is authorized by *live derivation* from a parent that is
authorized *now*. The design is the conjunction of the two.

**The precise change:**
1. **`requester_verdict`** (`scripts/framework/requester_trust.py`). When the author is the worker App,
   meaning `user.login` equals `BOT_WORKER_USERNAME` case-insensitively and `user.type == "Bot"`, and no
   marker matches, it returns a **new** untrusted reason, `worker-app-derivation-required`. It no longer
   returns `trusted-app-no-machine-filing-marker` for that author. Records authored by the overseer and
   human-proxy Apps keep today's reason and path, **unchanged**. `MACHINE_FILING_MARKERS` is
   **unchanged** (AM-10).
2. **D5, for records carrying that reason.** Before the existing events check, pay for a **derivation
   check**. The fetches happen in `select_work_candidates.py`, and the predicate is pure, with no network,
   in `requester_trust.py` (AD-1 of TD-1540). The record is admitted iff **all** of the following hold:
   - (a) it resolves to exactly one parent through its native sub-issue link;
   - (b) the parent's **worker-authored, unedited** tracking block lists this issue;
   - (c) the parent is **authorized now** by the unchanged S2 test: a trusted author, or a verified
     CODEOWNER `labeled` event for the pending-actor label, *and* the parent currently carries that label;
   - (d) the parent does not carry `needs-human` and is not closed.

   Admission reports `AUTHORIZED issue=#N via=derivation parent=#P`. If the derivation fails, the record
   **falls through to today's CODEOWNER events check**, and failing that it is gated with a new reason
   token naming the failed limb.
3. **Budget and exit contract.** Derivation fetches count against the existing ceiling. A refusal part-way
   through a derivation is `unevaluated:cost-ceiling`, exactly like an events fetch. Exit codes 0/2/3 are
   unchanged. **Nothing is cached** (FR7).
4. **The tracking parent** keeps its pending-actor label, so that "authorized now" stays well defined,
   and is excluded from emission by `stage:tracking` (AD-C4). A CODEOWNER revokes every child at once by
   removing the parent's pending-actor label or adding `needs-human`.
5. **Consumer-facing text.** This changes what the human's act means. The docstring's FR29(b) statement
   and `docs/LABELS.md` "The `needs-ai` authorizing act" gain the following sentence: *"applying the
   label also starts autonomous work on any sub-issues the worker files under that issue, for as long as
   the issue stays authorized."*

**What stays gated.** These are the stricter readings, and ARCH-ESC-3 confirms them:
- worker-filed issues that are **not** decomposition children, such as follow-ups and spec-gap filings;
- anything filed by the human-proxy App;
- a child authored by anyone else, even when it is linked into a graph. Per ESC-2, such a child needs a
  CODEOWNER act every time.

**Laundering analysis, which is required because AM-10 exists for exactly this reason.**
- A child's body is composed by an LLM from its parent's content, which may be untrusted even when the
  parent is authorized.
- What the child gains is **selectability without a fresh human act**. It gains no authority the parent
  did not already carry, because the parent was already authorized for autonomous work on that content,
  and its bounds are:
  - **scope and amplification:** at most `max_children` children at depth one;
  - **queue position:** priority ≤ parent, and milestone inherited;
  - **stage skipping:** AD-C12's floor and precondition checks apply to children;
  - **persistence:** the parent must be authorized *now*, so revoking the parent revokes every child;
  - **merge:** every PR still passes the overseer's own dimension runs and every human gate, all
    unchanged.
- **Reading the child's body adds no new injection exposure class.** It is the same exposure as reading
  the parent's.
- **Review requirement (binding).** This slice (T3.8a) gets security-reviewer, cross-vendor second review
  at HIGH+, **and a dual-lens adversarial panel of the same form as `PANEL-1540-S1-S2-*`**, before the
  CODEOWNERS human gate. It is a change to a trust boundary that took six panel runs to settle.

### AD-C17: Stage labels ship in #1520's migration window, under its cutover plan, with one provisioning script and one conformance test. (REQ-C10(c)(d); ESC-5.)

- **One breaking change.** `stage:*` labels, `needs-worker` and `needs-overseer` are introduced in the
  **same** release and under #1520's dual-read or cutover plan. T3.1 and T3.2 are designed **with**
  #1520 and do not ship before it.
- **Filling `docs/LABELS.md`'s two known gaps.** Both are required by this ADR because it adds eight
  labels:
  - one **idempotent provisioning script** that creates every label in the registry;
  - one **conformance test** that ties every label literal in code to a `docs/LABELS.md` row and every row
    to its writers and readers.
  - Every `stage:*` label and `hos:round-reset` gets a row with writer and control-flow-effect columns
    (REQ-C10(c)).
- **Migration safety comes from ESC-1.** An un-migrated consumer's issues carry no stage label, so each
  one starts at `plan`. The queue never goes silently empty because of stage labels. The empty-queue
  risk from the rename itself belongs to #1520's dual-read.

### AD-C18: Timeouts belong to #1601, #1602 and #1604. #1644 adds only the load check. (REQ-C7.)

- A stage's declared invocation timeouts are checked at load and at executor start (AD-C1).
- A killed stage consumes **no** round (REQ-C7(c)) and increments ADR-1604's attributed counter through
  #1601. Two such kills trigger T3, the splitter (AD-C15).
- **Until #1601 lands,** a round that times out repeatedly is bounded only by the existing project-wide
  timeout breaker. That is stated and accepted. The breaker is finite (ADR-1604 AD-6 rung 2).
- #1644 builds no checkpoint. The draft PR is the code stage's durable state, and the record is its
  commit point (AD-C7).

### AD-C19: Every transition emits an audit event for measurement. No decision reads one. (REQ-C23; ADR-1643 AD-8; ADR-1604 AD-4.)

The event carries issue, stage, loop, round, epoch, outcome and a timestamp, so that cycles and elapsed
time per issue can be computed for #1600. There is a test that drives one event through the real write
path and reads it back from a separate process (ADR-1604 AD-4). If measured latency is well beyond about
one interval per stage (§3), that is new evidence for the human. **It is never licence for a worker to
batch stages.**

### AD-C20: The primitive gains nothing. The prose that chose agents and stages is deleted, not left beside the code. (REQ-C21, REQ-C1, REQ-C18.)

- No flag, token, round or stage information is passed to `invoke_agent.sh`. The TD-1643 §3.8 prohibition
  tests stay green unmodified (REQ-C21).
- **T3.9 deletes** the following:
  - "Pick the first non-blocked candidate" (`worker-cron-prompt.md:96`, `bin/hos-cron:1979`);
  - Step 3's classification (`:112-115`);
  - the batching clause (`:104`, AF-C8);
  - `worker.md`'s step-8 prose chain and the "self-enforced" paragraph (`:377-378`), for staged work.

  Leaving the prose in place beside the code would give two decision authorities, and that is how
  VF-C2 happened.

---

## 3. What it costs: latency and worst case, as numbers

**Latency** (median cron interval **602s**, §0). A typical design-chain issue with no back edges, docs
auto-merged within the overseer's ceiling, and a 1 to 2 round code loop takes:
- `plan` (1),
- plus three design stages at about 2 intervals each (execute, then overseer merge),
- plus 1 to 2 code rounds,
- plus `converge` when AD-C11 requires it (0 to 1),
- plus overseer review and merge (at least 1).

That is **about 10 to 12 intervals, or 100 to 120 minutes**, before any human-gated merge wait. A
decomposed issue adds its children's graphs, which run in parallel only when there are no edges between
them. This is the latency class the human accepted in Q4+Q6 (amendment §5). **Measuring it is AD-C19's
job, not an assumption.**

**Worst case per original issue per human epoch.** Everything here is finite, and REQ-C2(g) requires the
numbers to be stated.

| Quantity | Bound | Derivation |
|---|---|---|
| Coder sessions per change | **3** | `code_round_cap`, with bounces included (AD-C8) |
| Changes per original issue | **5** | `max(max_children, max_slices)`. Depth one. The two cannot both occur. |
| Coder sessions per original issue | **15** | 3 × 5 |
| `code-reviewer` invocations | **15** | one per round |
| Confirmation runs | **≤ 15** | at most one per approving round, and a rejection spends the next round |
| Plan-phase invocations | **≤ 46** | 1 `plan` + 5 children × (3 passes × 3 stages) |
| `oversize` re-plans | **1** | AD-C15 T2, once per issue |
| Overseer bounces per change | **2** | unchanged, #1643's |

Timeouts are bounded separately by ADR-1604's ladder. Each human grant adds at most the budget it names:
one round for a resume, a full epoch for a reset.

---

## 4. The ADR-1643 seam, assessed

The brief asked whether ADR-1643's §4 seam is sufficient. **It is, and I amend nothing in ADR-1643.**
Four findings follow. Each is either a coordination requirement on unbuilt ADR-1643 work or a documented
deviation already ruled by the human.

- **SEAM-1: AD-9's loader has not been built** (W5 is outstanding, VF-C10). AD-12 binds "one loader".
  T3.1 therefore **depends on ADR-1643 W5**, and W5's `technical-design` must build the loader
  **schema-parametric**: one loader and one ownership model, with each registry document declaring which
  schema it is (dimensions or stage graph). If W5 slips past T3.1's window, the fix is to pull W5 forward.
  **It is not a second loader.** This is a sequencing constraint and needs no human.
- **SEAM-2: AD-6's result document has no stage-output payload** (artifact bytes, routing decision, slice
  or child plan, `open_questions[]`). AD-6 leaves field names to `technical-design`, requires any
  extension to be additive and legacy-compatible, and requires a strict parse. A namespaced, optional
  `stage_output` object that is strictly validated **per stage** meets all three. It is an extension
  within AD-6's terms, not an amendment. TD-1643's schema owner must accept it at W2's revision point. A
  rejection there comes back to me.
- **SEAM-3: AD-7 refuses `bypassPermissions`,** so `coder` cannot use the primitive until a scoped posture
  exists. ESC-7 (a) ruled the stopgap. AD-C13 records it as the one bound deviation from REQ-C1. The seam
  is not insufficient. The posture is simply not available yet.
- **SEAM-4: AD-8 forbids decisions that read audit data.** It is honored: REQ-C13's counter becomes a
  timestamp grace period (AD-C5), and every count comes from GitHub records (AD-C7, AD-C8).

AD-2 (a stateless one-shot) holds exactly as §4 of ADR-1643 predicted. The executor invokes the primitive
the same way AD-13's sweep does.

---

## 5. Build order: the revised Track 3 (replaces the amendment's §6 list)

Every slice below touches a protected surface and passes the CODEOWNERS human gate. **Do not file
"implement ADR-1644" as one issue.** Each row is an intended issue boundary, with dependencies stated on
both sides.

| # | Slice | Contents | Depends on | Gate |
|---|---|---|---|---|
| **T3.0a** | **No-idle selection, issue side. THIS IS THE THIN FIRST SLICE.** | AD-C4's native-blocker exclusions (`blocked-by-open-issue`, `blocker-closed-unverified`, DEGRADED on a missing summary) and `untracked-parent`; `bootstrap/escalate_to_human.sh` (AD-C6 H5; a search of `bootstrap/` and `scripts/automation/lib/` found no existing helper); ESC-8 tests T-NS1 to T-NS4 against the selector. **No labels, no registry, no executor.** | nothing | Ships alone. Zero added requests, proven by a mocked-`gh` request-count test. |
| **T3.0b** | No-idle selection, PR side | `bin/hos-cron`'s PR routing moves into a tested Python classifier in `scripts/framework/`. Behavior is preserved, except that H4 shapes no longer block new work. Closes #1847. T-NS5. | T3.0a | **Blocked on ARCH-ESC-1.** |
| **T3.1** | Stage registry and labels | AD-C1 and AD-C17: `contract/stages/core.yaml`, load checks, provisioning script, conformance test, `docs/LABELS.md` rows. | ADR-1643 **W5** (SEAM-1), #1520 design (ESC-5) | Designed with #1520. |
| **T3.2** | Stage checks in the selector, plus the pre-check skeleton | AD-C4's stage parse and in-flight ordering; AD-C5 steps 1, 2 and 4; AD-C3 steps 3 and 4. T-NS6. | T3.1 | Keeps the S2 exit and budget contract exactly. |
| **T3.3a** | #1352 slice (ESC-5) | AD-C14 canonical scripts for sub-issue links and `blocked_by` edges. | nothing | Pulled into v0.7.0. |
| **T3.3** | Edge satisfaction | AD-C14 ESC-3 satisfaction (the paid check), cycles and dangling edges, edge ⊇ block. | T3.2, T3.3a | |
| **T3.4** | Records, caps and epochs | AD-C7 and AD-C8. Record format and trust, record-first order, reconciling done-but-unrecorded, REQ-C2(g), resume and reset grants. | ADR-1643 W2, T3.1 | |
| **T3.5** | Stuck detection | AD-C9. **Its own TD section and an adversarial review.** | T3.4 | |
| **T3.6** | Escalation and worker confirmation | AD-C10 (without the question-issue half) and AD-C11 worker side. | T3.5; #1718 fixed or size-guarded | |
| **T3.6b** | Overseer confirmation threshold | AD-C11's `CROSS_VENDOR_MIN_TIER`. | coordinated with ADR-1643 W7 | |
| **T3.7a** | Plan-phase executor | AD-C12, reconcile (AD-C3.1), and the ESC-3 addendum (AD-C10 question issues). **Its first deliverable is the A5 write-attempt measurement (§0).** | T3.2, T3.4, T3.3a | |
| **T3.7b** | Code-phase executor | AD-C13: the session directive, the judged half, the draft carrier, `submit_pr.sh --draft`, the ready-for-review script, and the tamper detector. | T3.5, T3.6, T3.7a | Go-live **blocked on ARCH-ESC-2**. |
| **T3.8** | Splitter, unified with ADR-1604 Phases 2 to 4 | AD-C15, including the `diff_size` backstop. | T3.3, T3.7b; ADR-1604 Phase 0 (#1601) | |
| **T3.8a** | S2 derivation path | AD-C16. **Adversarial panel required.** | T3.3a, T3.8 | Security-relevant. |
| **T3.9** | Prose retirement | AD-C20. | T3.3, T3.7a/b | Last. |

**Why T3.0a is the first slice.** It needs nothing from ADR-1643's unbuilt W5, nothing from #1520, and no
stage label. It pins ESC-8's property in tests from the first release. It closes the "code before its
spec" gap for any edge a human draws today, and it gives future human waits a machine-visible form (H5).
If everything else slips, it still ships and is still worth having.

**Recommended v0.7.0 boundary:** T3.0a, T3.0b (if ARCH-ESC-1 is cleared), T3.1, T3.2, T3.3a, T3.4, T3.7a,
and T3.6's escalation half. That runs the design chain stage-per-cycle, with deterministic routing, a
durable cap and the ESC-3 addendum. It takes on none of the code-round, splitter or S2 risk. T3.3, T3.5,
T3.6, T3.6b, T3.7b, T3.8, T3.8a and T3.9 follow. ESC-7's tie to v0.7.0 means T3.7b's stopgap is
re-evaluated at that release anyway.

---

## 6. Escalations held for the human

### ARCH-ESC-1: Allow new work while worker PRs wait on a human. This relaxes #1198's serialization, which ESC-8's exception requires. (Product boundary: user-visible behavior and safety tradeoff. **Blocks T3.0b only.**)

AF-C2: today any open worker PR that is waiting on a human merge blocks **all** new work, and #1847
mislabels HUMAN_REQUIRED PRs as "not yet reviewed". ESC-8's exception ("blocked on a human → pick up
other work instead of idling") cannot hold on the PR side unless that changes. #1198 kept the
serialization on purpose, as a defence against stale-base PRs, and made #1162 its prerequisite. #1162 is
now in `submit_pr.sh`.

**Recommendation:** clear it, with a bound:
- new work is allowed while **≤ 3** worker PRs are human-pending;
- at 3, new work blocks, so that the human's review queue cannot be flooded;
- overseer-pending PRs (`needs-attention` that is genuinely unreviewed) **keep** blocking new work as
  today, because the ruling's exception names humans, not the overseer.

The cost: more concurrent PRs, more merge conflicts, and more reliance on #1162.

### ARCH-ESC-2: Accept that the worker's own model session can forge its own round state under the ESC-7 stopgap until #1542. (Security posture. **Blocks the go-live of T3.7b only.**)

AF-C4 and AD-C13. I bind a detective control that catches in-window writes and uncorroborated labels. A
model session under `bypassPermissions` holding the worker App credential could still write a consistent
record-plus-label pair outside the window. What it gains is extra worker rounds, which cost money. It
gains no merge: the overseer re-runs its dimensions (Q2) and the human gates are unchanged. The only real
fix is to withhold the credential from the session, which needs #1542.

**Recommendation:** accept for v0.7.0 as part of ESC-7's time-box, with re-evaluation at #1542.

### Confirmations of readings I have bound. Each one binds the **stricter** reading until you rule, so none of them blocks.

- **ARCH-ESC-3 (ESC-2 scope).** Worker authorship makes an issue selectable **only** when it is a child
  with verified derivation from a currently authorized parent. That is AM-10 in conjunction with your
  ruling. Worker-filed follow-ups that are not children, and all human-proxy filings, still need your
  CODEOWNER act. "A human" means the existing trusted-human categories (CODEOWNER, roster, roster tier).
  Any other human is "unknown/external". *Question: is that what you meant, or should worker authorship
  alone suffice?*
- **ARCH-ESC-4 (the direct-code floor).** Only issues labeled `bug`, and none labeled
  `enhancement`/`process-gap`/`epic`, may skip the design chain. Unlabeled tweaks now pay three design
  stages, about 6 intervals or about 1 hour. *Question: widen the allowlist, for example with a
  `tweak`/`docs` label, or keep it?*
- **ARCH-ESC-5 (ESC-6 base grant).** A resume grants **one** more round, per the addendum's "one more
  round, per ESC-6's base case". A **reset** (a separate label) grants a full budget with a fresh stuck
  baseline. *Question: did the base ruling's "fresh round budget" mean a full cap instead?*
- **ARCH-ESC-6 (acts must be yours).** Resume, reset, question-closing and CODEOWNER re-routes count
  **only** from your own GitHub account. Your human-proxy App is a bot identity here, exactly as in S2.
  The friction is one click per act from your account. *Acknowledge.*
- **ARCH-ESC-7 (cost model).** These are the caps and worst-case totals in §3:
  - 3 rounds per change, with bounces included;
  - 5 children or slices;
  - up to 15 coder sessions and 46 plan-phase invocations per original issue per epoch.

  *Acknowledge, or lower any of them.*

---

## 7. Requirements follow-ups for `pm-agent`. These do not block design.

- **PM-1:** give the ESC-3 addendum a REQ id (proposed **REQ-C24**). Decide the owner and mechanism for
  documents merged **outside** the stage graph (AD-C10 scope limit).
- **PM-2:** REQ-C15's acceptance criterion says "non-selectable". Amend it to state that actor
  verification happens at the executor pre-check, so that REQ-C11's zero-added-request acceptance
  criterion holds for the selector (AD-C4, AD-C5).
- **PM-3:** REQ-C13's "N consecutive cycles" becomes a 2 × cron-interval grace period derived from GitHub
  timestamps (AD-C5).
- **PM-4:** adopt AD-C9's strict operationalization of REQ-C3(iii).
- **PM-5:** slice plans (AD-C15) are a structure the amendment did not name. Add them as a REQ-C17
  extension (proposed **REQ-C25**).
- **PM-6:** once ARCH-ESC-1 is ruled, record the PR-side semantics of ESC-8's exception.

---

## 8. Non-goals, with owners

- **The overseer's own re-run of dimensions and its bounce budget** belong to #1643 (ADR-1643 AD-13 and
  AD-15). This ADR adds only the confirmation threshold key (AD-C11).
- **Timeout detection, counting and WIP checkpoints** belong to #1601, #1602 and #1604 (AD-C18).
- **The `needs-ai` → `needs-worker`/`needs-overseer` rename and its dual-read** belong to #1520 (AD-C17
  sequences against it).
- **The remainder of #1352** (everything beyond T3.3a) stays in v0.7.4.
- **A scoped `coder` posture and sandboxing the worker and overseer** belong to #1542 (ESC-7).
- **Enforcing the ESC-3 addendum outside the stage graph** belongs to pm-agent (PM-1).
- **The durability of `bounce_count`,** which is clone-local (VF-C6), belongs to #1643. AD-C8 does not
  depend on it.
- **What any agent looks for** is unchanged. No lens is widened or narrowed.
- **Human gates** are untouched. Nothing here lowers a gate, and AD-C16 and ARCH-ESC-3 only ever require
  *more* evidence.
- **Files written by this pass:** this ADR only. Every change described is a protected-surface edit to be
  authored and human-gated later.

---

## 9. Startup-gap analysis and affected sign-offs

I asked, of each reactive decision here, whether it should have been settled before design or code was
built against it.

- **#1880 merged with nine unanswered escalations (AF-C9, the ESC-3 addendum).** Yes. The requirements
  pipeline has no forcing signal for open questions at merge time, and a `needs-human` label on a PR that
  is about to merge forces nothing. **No sign-off is orphaned.** The document is correct as a
  requirements statement, and its questions are now answered. I recommend a `startup-artifact-gap` issue
  for "a merged document can carry open questions silently". I have not filed it.
- **The S2 gate (AD-C16) changes approved, merged, panel-reviewed code.**
  - **These stand:** every S2 sign-off and panel run for the existing paths. The overseer and
    human-proxy App paths, `MACHINE_FILING_MARKERS`, the budget and exit contract, and the CODEOWNER
    events check are all unchanged.
  - **These are flagged for re-review:** any S2 test whose expectation encodes "*every* worker-App issue
    without a marker is gated". Such a test stays correct for non-child filings and is wrong for
    derivable children. `technical-design` must list those tests by name rather than re-run the suite and
    call it green. The consumer-facing authorizing-act text changes (AD-C16.5), so FR29(b)'s review is
    re-opened for that text.
- **`bin/hos-cron`'s PR routing** (#791, #1198, #1350, #1522, #1526). T3.0b re-implements it in Python,
  preserving behavior except for H4.
  - **These stand:** the #1350, #1522 and #1526 sign-offs, re-pinned against the classifier.
  - **These are flagged:** #1198's serialization sign-off, which ARCH-ESC-1 must clear, and any test
    asserting that `awaiting-merge` produces `NEW WORK: BLOCKED`.
- **ADR-1604** (AD-1 module location, AD-10's "exclusion marker" unblock mechanism). This ADR supersedes
  both in effect: trust-relevant code goes under `scripts/framework/`, and native edges with free list
  counters replace a marker-based unblock. **ADR-1604 is unbuilt, so no sign-off is orphaned.** Its
  `technical-design` must read AD-C3, AD-C14 and AD-C15. I recommend a cross-reference note on ADR-1604,
  which is my own document to amend in a separate pass. This task did not authorize me to edit it.
  ADR-1604's own ESC-2 (may worker-filed sub-issues be selectable?) is **answered** by your 2026-09-30
  ESC-2, as read in AD-C16.
- **ADR-1643.** Nothing is superseded and no sign-off is affected. SEAM-1 places a requirement on W5,
  which is unbuilt: the loader must be schema-parametric.
- **The amendment's §6 Track 3.** It is superseded by §5, which re-orders items, adds T3.0a/b, T3.3a,
  T3.6b and T3.8a, and splits T3.8. Nothing was filed or built against it, so there are no sign-offs.

---

## 10. Open questions carried by this document

Per the ESC-3 addendum, **merging this ADR answers none of these.** When it merges, the orchestrator must
file one `needs-human` issue carrying this list, because AD-C10's mechanism does not yet cover documents
outside the stage graph (PM-1). I have not filed it.

```hos-open-questions
- id: ARCH-ESC-1
  question: Relax #1198 serialization so human-pending worker PRs do not block new work (bound ≤3; overseer-pending still blocks)?
  blocks: T3.0b
- id: ARCH-ESC-2
  question: Accept, until #1542, that the worker's own bypassPermissions session can forge its own round state (cost-only residual; detective control bound)?
  blocks: T3.7b go-live
- id: ARCH-ESC-3
  question: Is ESC-2's worker trust limited to derivable children of a currently-authorized parent (non-child worker filings and human-proxy filings stay CODEOWNER-gated)?
  blocks: none (stricter reading bound)
- id: ARCH-ESC-4
  question: Keep the direct-code allowlist at {bug}, or widen it?
  blocks: none (stricter reading bound)
- id: ARCH-ESC-5
  question: Does an ESC-6 resume grant one more round (bound) or a full cap?
  blocks: none (stricter reading bound)
- id: ARCH-ESC-6
  question: Acknowledge that resume/reset/question-close/re-route acts count only from your own account, not the human-proxy App.
  blocks: none
- id: ARCH-ESC-7
  question: Acknowledge or lower the caps and worst-case totals in §3.
  blocks: none
```

---

## Human Review Required

**Two items block named slices, and five are confirmations of readings bound strictly.** All are in §6.
T3.0a, T3.1 to T3.6, T3.7a and T3.8 are cleared to proceed to `technical-design` without any of these
answers. T3.0b waits on ARCH-ESC-1, and the go-live of T3.7b waits on ARCH-ESC-2.

**RISK: HIGH.** This design:
- changes the trust boundary of the work selector, so the machine can select work it filed itself
  (AD-C16);
- relocates which stage runs, whether it may run, and who counts its rounds from model prose into code
  (AD-C3 to AD-C8);
- adds a new autonomous write surface: decomposition and question issues;
- relaxes a deliberate serialization (ARCH-ESC-1);
- runs a code-writing session under `bypassPermissions` for another release (ESC-7).

The failure mode of getting it wrong is not "slower". It is either a worker that idles on humans (the
2026-09-30 case), or a worker that launders untrusted content into self-selected work, or a cap that
silently resets. Each is closed positively rather than cautioned about:
- exclusion always precedes ordering, and six tests pin it (AD-C6);
- derivation is live, requires a parent authorized *now*, and is bounded in count, depth and priority
  (AD-C16);
- every count comes from API-verified, unedited, version-stamped GitHub records, and only a verified
  human's own act refills a budget (AD-C7 to AD-C9).

**CONFIDENCE: HIGH** on §0. Every citation was re-derived at `7e37e2f70`, and three findings came from
live GitHub probes:
- **AF-C1:** the list record already carries free dependency and sub-issue counters, which turns
  REQ-C16's cost question into a solved problem;
- **AF-C2:** hos-cron's PR serialization makes ESC-8's exception impossible without ARCH-ESC-1;
- **AF-C4:** under the stopgap, REQ-C15's trusted identity is shared with the model session.

**HIGH** on AD-C1 to AD-C8, AD-C10, AD-C12 and AD-C14, which follow from those findings and from rulings
already made. **MEDIUM-HIGH** on AD-C16's derivation predicate: the shape is AM-10's, but the parent
resolution endpoint could not be probed (§0 gap). **MEDIUM** on AD-C9's criterion (iii) and on AD-C13's
detective control. Both are the subtlest parts, and T3.5 and T3.7b carry an adversarial review for that
reason. **LOW** on §3's latency figure as a prediction. It is arithmetic from a measured interval, not an
observation, and AD-C19 exists to replace it.

**BLAST RADIUS:**
- work selection for every worker cycle (`select_work_candidates.py`, `requester_trust.py`);
- `bin/hos-cron`'s worker cycle shape and PR routing;
- `bootstrap/` (new: `run_stage.sh`, `escalate_to_human.sh`, the ready-for-review script, and the edge and
  sub-issue scripts; changed: `submit_pr.sh --draft`);
- `contract/stages/` (new protected configuration family);
- `scripts/framework/machine-accounts.env` and `merge_config.py` (a new key);
- `docs/LABELS.md` and 8 new labels in every consumer repo (in #1520's window);
- `worker.md` and `worker-cron-prompt.md` (prose removed);
- ADR-1604's unbuilt design;
- the subscription quota (§3).

**Change classification: STRUCTURAL.** It adds new decision points (stage routing, blocked-exclusion,
convergence), new state carriers (stage labels, records, question issues, native edges), a changed trust
boundary (AD-C16), a new autonomous write surface (decomposition), and a relaxed serialization
(ARCH-ESC-1). Under the product-boundary checkpoint, ARCH-ESC-1 (user-visible throughput and safety) and
ARCH-ESC-2 (security posture) must be cleared before their slices bind. ARCH-ESC-7 (cost) is presented for
acknowledgement.

**Not done here, deliberately:**
- no sign-off register entry, because that is not the architect's role and nothing is built;
- no issue filed, no comment posted, no label changed;
- ADR-1643 and ADR-1604 are not edited.

---

## Erratum 1 (2026-09-30): T3.0a technical-design review, round 1

Raised by the architect's review of `docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0a-no-idle-selection.md`
(DRAFT-1). **No decision above is rewritten.** Each item below corrects a slice boundary or records a
consequence. Where an item conflicts with the text above, the item governs.

- **E1 (§5 T3.0a and T3.2 rows; AD-C6 required tests).** §5 listed "T-NS1 to T-NS4" in T3.0a. T-NS2
  asserts in-flight-first ordering, which is T3.2's content: it needs AD-C4's stage parse, and that needs
  AD-C1's registry (T3.1). So:
  - **T3.0a's gate is T-NS1, T-NS3 and T-NS4.**
  - **T-NS2 is a T3.2 gate test.**
  - T3.0a ships T-NS2 as `xfail(strict=True, raises=AssertionError)`. T3.2 must remove the marker, and a
    strict XPASS forces it to.
  - T3.2 must also re-run T-NS3 with the six blocked items **in-flight** (carrying stage labels) and the
    eligible item **new**, under the new walk key `(inflight_class, rank, -number)`. In T3.0a, T-NS3 can
    only exercise the cut by priority.
- **E2 (AD-C4, missing summary).** Confirmed consequence: on a host whose list endpoint never returns
  `issue_dependencies_summary`/`sub_issues_summary`, **every** record is unevaluated. The selector is then
  DEGRADED (exit 3) on every cycle, and no new issue work is selected there. This is the intended
  fail-closed outcome. It gets no configuration knob. It is stated in the selector's shipped docstring.
- **E3 (AD-C4, parents).** Confirmed reading: `sub_issues_summary.total` counts closed children, so a
  parent stays excluded (`untracked-parent`) after all its children close. Before T3.2, the human remedy
  is to close the parent or remove its sub-issue links.
- **E4 (T3.6 scope; AD-C10 "one code path").** T3.6 gains the following, and its TD must list every
  issue-side `needs-human` writer and say, for each, whether it migrates or why it does not:
  - migration of the pre-existing **label-first** escalation sites onto `bootstrap/escalate_to_human.sh`:
    `bin/hos-cron:1732-1739` (baseline-repair cap) and `.claude/agents/worker.md:291-295`
    (baseline-repair "cannot determine" step);
  - the `worker.md` instruction that human waits go through that script.

  Out by name:
  - `merge_authority.py::route_embargo` (an embargo, not a question);
  - NG3b R4 step 0b (a `release-request` issue, which the script refuses).

  `worker.md` edits remain top-level-session-authored (#1347).
- **E5 (AD-C7 scope).** AD-C7's "envelope record, no new mechanism" rule governs **round and stage
  records**. `escalate_to_human.sh`'s HTML-comment idempotency marker (`<!-- hos-escalation v=1 … -->`)
  is a write-primitive key, not a record format. It follows the `release_panel_logic.py` marker precedent.
  - The AD-C10 escalation record's format is T3.6's, carried inside the body its caller passes.
  - T3.6 must check `envelope.py`'s `DEFAULT_ACK_PATTERNS` before putting an envelope in a *question*
    body, because `---hos-envelope` is itself an "answer exists" pattern.

**Startup-gap analysis.**
- **E1: yes, and it is minor.** The slice table should have matched the tests to the slice contents.
  Nothing has been built or signed off against the T3.0a row, so **no sign-off is affected**.
- **E2 and E3:** not new decisions. They are consequences of AD-C4 as written. No sign-off is affected.
- **E4 and E5:** they widen or clarify slices that are unbuilt (T3.6) or in design (T3.0a). No sign-off is
  affected.

No `startup-artifact-gap` issue is recommended for this erratum.

---

## Erratum 2 (2026-10-02): T3.0b technical-design review, round 1

Raised by the architect's review of `docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0b-pr-classifier.md`
(DRAFT-1) against `REQUIREMENTS-1644-AMENDMENT-2-esc1-pr-side.md` (PM-6). **No decision above is
rewritten.** Each item below corrects a premise, binds a stricter reading, or records a consequence.
Where an item conflicts with the text above, the item governs.

- **E6 (AF-C2 and §6 ARCH-ESC-1: an incomplete premise; ARCH-ESC-1 is re-opened as ARCH-ESC-1R).**
  AF-C2 and ARCH-ESC-1 say #1198 "made #1162 its prerequisite" and that #1162 "is now in
  `submit_pr.sh`". **That is incomplete, and the human ruled on it.** `DECISIONS.md` (2026-08-09, #1198,
  human-ratified) retained the serialization and deferred any concurrency to **#1313** (open,
  `needs-human`, v0.8.0). #1313 gates concurrency on:
  - P1 (blocking): the force-push bypass of `submit_pr.sh` in `bootstrap/worker-cron-prompt.md:90`;
  - P2 (blocking): branch protection `required_status_checks.strict: true`. It is still `false`
    (`scripts/framework/setup_branch_protection.sh:177`);
  - P4: a named, declared post-merge verification control;
  - P5 (blocking): a field observation of the #1162 guard firing;
  - plus a submit-time file-overlap refusal, predeclared abort criteria with a revert trigger, and a
    narrower shape: N = 2, with the second PR allowed only while the first is approved and awaiting
    merge.

  #1313 also records the `dismiss_stale_reviews: true` hazard: concurrency can *increase* the human's
  work when a sibling merge forces a re-approval. None of this was in front of the human on #1912.

  A human ruling made on a premise that its author has since found incomplete is not cleared for the
  facts it was not shown. Under the product-boundary checkpoint, **ARCH-ESC-1 is re-opened as
  ARCH-ESC-1R** (the text is below). **T3.0b's `coder` handoff is blocked until ARCH-ESC-1R is answered.**
  - ESC-2 to ESC-7 on #1912 are unaffected.
  - T3.0b's design work is not blocked.
- **E6a (threshold wording).** ARCH-ESC-1's "allowed while **≤ 3** … at 3, new work blocks" disagrees with
  itself at *H* = 3. The binding reading is PM-6's: **ALLOWED iff *H* < 3**.
  - A cycle opens at most one PR (`worker-cron-prompt.md:139`, submit then STOP).
  - Overseer-pending and worker-actionable PRs block.
  - So the steady-state maximum is **3 open worker PRs in total**, against today's 1 and #1313's 2.
  - The bounce re-entry can briefly add the bounced draft until it is closed.
- **E7 (AD-C6 T-NS5).** "One open PR in each H4 shape" names three shapes. Read literally, that gives
  *H* = 3, which E6a blocks. The three shapes have **two** carriers, because a HUMAN_REQUIRED verdict
  reaches the PR as `needs-human` (PM-6 VF-P2). So:
  - **T-NS5** is one PR per carrier (*H* = 2) plus an eligible issue, which gives `ALLOWED`;
  - **T-NS5-shapes** is each of the three shapes alone, giving `ALLOWED` with *H* = 1;
  - **T-BD1** is three human-pending PRs, giving `BLOCKED`.
  This is a correction to the test, not to the ruling.
- **E8 (§5 T3.0b row, "behavior is preserved").** There is one deliberate exception: **unknown PR state
  fails closed.** A list read failure, an unparseable list, a list beyond the pagination cap, or a
  classifier crash or invalid output gives `NEW WORK: BLOCKED` (`pr-state-unknown`). Today it gives
  `ALLOWED`.
  - §1's governing constraint ("never resolves to 'not blocked'") governs this module.
  - A bound that a failed read can bypass is not a bound.
  - This is a correction, not a product change that needs routing. It removes a fail-open that no
    ruling authorized. Its only user-visible cost is one cycle without new work per failed read, and
    that cost is audited (`cycle-pr-state-unknown`).
  - The empty-slug path that the TD cited (its TD-F8) is **unreachable**: `bin/hos-cron:913-916` already
    exits the cycle fail-closed on an empty slug (#912).
- **E9 (carrier narrowing, bound strictly).** A PR is human-pending only on a positive read of all the
  following:
  - not draft;
  - no `hos-halt`;
  - both the detail and the reviews read succeeded;
  - **and** either `needs-human` is on the PR, **or** there is an `APPROVED` review whose `commit_id`
    equals `head.sha`, **whose `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`, and whose
    `user.login` does not end in `[bot]`**.

  The author restriction closes a zero-cost path. Without it, any account able to post a review
  (anyone, on a public repository) could turn an overseer-pending PR into a human-pending one and
  release new work. Excluding bot approvals fails toward blocking. Under #1657 the overseer does not
  post `APPROVED` on the PRs that wait on a human anyway. Each narrowing counts *fewer* PRs than the
  ruling would, so none needs routing.
- **E10 (AC-8 and list truncation).** The PR list is read at `per_page=100`, and the classifier follows
  `&page=2` and `&page=3` **only while the previous page was full**. A full third page is DEGRADED.
  - Requests are unchanged for any repository with fewer than 100 open PRs.
  - Without pagination, a consumer with 100 or more open PRs (all authors) would be permanently
    `BLOCKED`. With today's single page of 20, the worker's own PRs on page 2 are invisible (fail-open).
- **E11 (P1, closed inside T3.0b).** `worker-cron-prompt.md:90` tells the fallback path to force-push.
  That contradicts `worker.md:411` ("no `--force`"), and it is #1313's P1.
  - T3.0b deletes the force-push branch. A dirty PR on that path is closed with a comment, and its
    unique commits are re-submitted through `bootstrap/create_branch.sh` and `bootstrap/submit_pr.sh`,
    which is the path's own existing second alternative.
  - This is a fallback-only path, reachable only when the directive is absent. It is stricter, so it is
    bound here rather than routed.
- **E12 (AC-5 over AC-7).** A fixture that today renders `awaiting-merge` but has an unreadable detail or
  reviews read now renders `needs-attention` (fail-closed, PM-6 AC-5). AC-7's byte-identity applies to
  fixtures whose routing today is `none`, `needs-fix`, `needs-fix-bounce` or `needs-attention`. Both
  outcomes are BLOCKED.
- **E13 (forward items).**
  - **T3.7a:** the #1847 visibility notice stays model-posted in T3.0b, which is today's mechanism.
    T3.7a's deterministic finalize step must absorb it, with marker idempotency. Until then, AC-6's
    "exactly once" is pinned only by the deterministic directive and the prompt contract.
  - **T3.7a/T3.7b:** AD-C13's cross-cycle carrier is a draft PR, and the classifier classifies a draft as
    overseer-pending (`draft`), which BLOCKS new work. The T3.7 design must say how a stage-draft PR is
    classified before any stage-draft PR ships. The rule cannot be silently inherited.

**ARCH-ESC-1R (for the human; blocks T3.0b's `coder` handoff).** The text to file as a decision
issue:

> On #1912 you cleared ARCH-ESC-1 (bound 3). The ADR text you ruled on said #1162 was #1198's only
> prerequisite for concurrency. That was incomplete. Your 2026-08-09 ratification of #1198 kept
> serialization and deferred concurrency to **#1313**. #1313 gates it on P1 (the force-push bypass),
> P2 (branch protection `strict: true`), P5 (field evidence the #1162 guard fires), P4 (a named
> post-merge check), a submit-time file-overlap refusal, predeclared abort criteria, and a narrower
> shape: at most 2 PRs, the second only while the first is approved. It also warns that
> `dismiss_stale_reviews` can make you re-approve a PR after its sibling merges.
>
> **The facts as of 2026-10-02:**
> - **P1:** it will be closed inside T3.0b. The architect bound this.
> - **P5:** the guard has fired at least three times (2026-09-14, `stale-base-merged`, behind main by 2
>   to 4 commits). The records exist only in a clone's uncommitted audit log (#1803).
> - **P3:** shipped.
> - **P2:** not done (`strict: false`).
> - **P4:** CI runs only on pull requests. The only post-merge check is the worker's cycle-start test
>   baseline on `main`, which detects within one worker cycle and auto-files a repair issue.
> - **Your ruling** allows at most 3 open worker PRs at once (today: 1; #1313: 2).
> - **Reverting** is one constant: `HUMAN_PENDING_BOUND = 1` reproduces today's serialization exactly.
>
> **Q1. With this in view, does ARCH-ESC-1 stand?**
> - **(a) Yes.** Bound 3 ships in v0.7.0 with the controls in Q2 to Q4. **Recommended.**
> - (b) Narrow to #1313's shape: at most 2 open worker PRs, the second only while the first is
>   approved-awaiting-merge (`needs-human` question PRs keep blocking). This requires a T3.0b design
>   revision.
> - (c) Defer T3.0b to v0.8.0 behind #1313. The worker keeps idling on human-pending PRs in v0.7.0,
>   and ESC-8's exception stays unmet on the PR side.
>
> **Q2 (if 1a). Branch protection `strict`?**
> - **(a) Keep `false`, and accept that two worker PRs can merge without CI on their combined state.**
>   The declared post-merge control is the worker's cycle-start baseline. The abort trigger is a red
>   baseline traced to two worker PRs that both merged without combined CI, or one human approval
>   dismissed because a sibling worker PR merged. Either trigger means setting the bound to 1 by a
>   normal PR. **Recommended.** `strict: true` makes you press "Update branch" before every sibling
>   merge, which works against the throughput this ruling buys. Whether that update also dismisses
>   your approval under `dismiss_stale_reviews` is unverified.
> - (b) Set `strict: true` before T3.0b merges. That is a separate `setup_branch_protection.sh` change,
>   and you accept the per-merge cost.
>
> **Q3. Consumers.** The bound is a literal shipped to every consumer, so their serialization relaxes to
> 3 on upgrade, with no per-project setting.
> - **(a) Accept it, call it out in the release notes, and leave per-project limits to #567.**
>   **Recommended.**
> - (b) Add a per-project setting that can only *lower* the bound. This requires a T3.0b design
>   revision: one config read and its tests.
>
> **Q4. #1313's disposition.**
> - **(a) Keep it open in v0.8.0, re-scoped to what is left:** file-overlap refusal, revisiting `strict`
>   with field data, and the abort-trigger review. **Recommended.**
> - (b) Close it as superseded by ARCH-ESC-1.

**Startup-gap analysis.**
- **E6: yes, and it is the ADR's own verification error.** AF-C2 cited #1198's body but not its
  ratified `DECISIONS.md` outcome or the open #1313 it created. **A `startup-artifact-gap` issue is
  recommended** (the orchestrator files it, not the architect). Affected sign-offs:
  - **These stand:** ESC-2 to ESC-7 on #1912, and PM-6 as a record of the ruled semantics. PM-6 needs a
    revision only under Q1(b) or Q3(b).
  - **This is suspended until ARCH-ESC-1R:** the ARCH-ESC-1 clearance on #1912, and with it the "T3.0b
    is unblocked" line.
  - **None orphaned:** no T3.0b code or review exists.
- **E6a, E7, E12:** corrections to wording and tests. No sign-off is affected.
- **E8 to E11:** stricter bindings in an unbuilt slice. No sign-off is affected.
- **E13:** a forward constraint on unbuilt slices. No sign-off is affected.

## Erratum 3 (2026-10-13): CHANGES_REQUESTED semantics (#1660, #1662) — pointer

Items **E14 to E18** live in `docs/v0.7.0/ADR-1660-1662-changes-requested-semantics.md` §4.1, which
governs where it conflicts with Erratum 2 or the T3.0b TD. In short:
- T3.0b §2.5 R ("any CR", "a full page with a CR is a determination") is withdrawn;
- CR facts come from `scripts/framework/review_state.py`, filtered to trusted humans;
- a PR with outstanding CRs that have all been acted on is `awaiting-human-cr`, never `needs-fix` and never carrier (b);
- whether it is a human-pending carrier (c) waits on **ESC-2b**.

T3.0b `coder` handoff now also requires a TD revision that incorporates E14 to E17.
Re-opened sign-offs: only the T3.0b TD rows E14 to E17 name. No code is orphaned.
