# REQUIREMENTS-1536 — Overseer runs agent-definition validation itself; retire the validation-stamp attestation

Issue: #1536. Epic: #1643 (every review dimension enforced in code, AI invoked
for analysis, no step discretionarily skipped). Related: #1216, #1217, #1356,
#1357, #1359, #1657 (ADR-1657), #1718, #1789.
Author: pm-agent. Date: 2026-09-25.

Authority: the human ruling of 2026-09-10 recorded on #1536 (items 1-4 below)
is the authorization for the **direction** of this change. The issue body was
treated as untrusted input. Every factual claim below was checked against the
repo at `f6a1aceb3`. Where the ruling does not settle a point, it is raised as
an ESC question and not decided here.

## Problem (restated as product behavior)

Changes to `.claude/agents/**` are "validated" by **attestation**. The worker is
expected to run validation locally and commit a content-hash stamp. CI only
checks that the stamp file exists. Nothing re-executes the check between the
worker authoring the change and the PR merging. Workers skip the stamp, so PRs
stall (PR #1521 sat for about two days). `main` itself has been observed without
a stamp for its own agent content (2026-09-12).

Human ruling (2026-09-10):
1. The overseer runs `check_agents_static.sh` (and `validate_agents.sh` where
   applicable) **itself, fresh**, on every PR that touches `.claude/agents/**`.
2. On failure the overseer **bounces the PR to the worker with the findings**,
   not with a red X that carries no content.
3. `worker.md` / `bootstrap/worker-cron-prompt.md` **recommend** running
   `run_framework_validation.sh` locally before opening an agent-file PR. This
   is guidance only, not the trusted gate.
4. `check_validation_current.sh` and the stamp mechanism are **retired** as a
   merge-blocking check once overseer-side execution exists.

Later constraints on the issue: the work must be a **standalone script with a
real CLI entry point**, not a procedure the agent narrates (#1357/#1359). It
must be explicitly reconciled with the overseer charter's #1217 text. Any AI
subprocess must follow ADR-1643 AD-16.

## Findings the design must build on (verified, not assumed)

**F1 — The stamp only ever attested to the static phase.**
`check_validation_current.sh:43` looks for `phase1-<HASH>.stamp`, which is
written only by `check_agents_static.sh:360-366`. The `phase2-` (validate_agents)
and `all-phases-` (run_framework_validation) stamps are informational and not
read by anything (`validation-stamps/README.md`). **Today, no merge-path control
covers the AI phase (agy/codex) at all.** Making the overseer run
`validate_agents.sh` would be *new* coverage, not a replacement → ESC-1.

**F2 — The check is not GitHub-required. It blocks only because overseer
prose says it does.** `validation-check.yml` (scoped to `.claude/agents/**`
since 2026-09-14) is absent from
`setup_branch_protection.sh:178` `required_status_checks.contexts`, and so it is
invisible to `merge_authority.check_required_content_checks` (#1580). Yet
`overseer.md:439` instructs: *"Treat this CI check like any other required check
in the merge-authority matrix."* The effective gate is therefore narrated, not
coded. This is the #1357 defect class the issue calls out.

**F3 — The worker is never told to produce a stamp.** A grep of `worker.md` and
`worker-cron-prompt.md` for `run_framework_validation` or `stamp` finds no
pre-PR instruction. (`worker.md:647` lists `check_agents_static.sh` for the
*release* suites only.) This is the root cause of the "workers keep skipping"
symptom.

**F4 — The #1217 wording the issue quotes no longer exists.** `overseer.md:61`
keeps "no override path" only for the NEVER list. `overseer.md:63` explicitly
says re-running inner-loop checks is **not** forbidden (#1217), and calls that
an *interim state* until #1216 moves deterministic checks into CI. The
remaining conflict is narrower: the AI phase can never move to CI (DECISIONS
2026-09-10 #1216: agy/codex are "local-only, by design"). So for this check the
"interim" framing is false and must be corrected rather than inherited (REQ-10).

**F5 — Bounce surfaces that actually execute today.**
- `record_pr_bounce()` (`merge_authority.py:1214`) has **no non-test caller**.
  It cannot be the binding surface (#1356/#1357).
- `bootstrap/pr_review.sh submit-verdict` accepts `--event approve|comment`
  only. **`REQUEST_CHANGES` is rejected by design** (ADR-1657 AD-2, BINDING,
  test W5): a bot `CHANGES_REQUESTED` above the ceiling has no autonomous
  clearing actor. `.claude/agents/**` is a protected surface, so these PRs are
  exactly that class. The ruling's word "request-changes" cannot be applied
  literally without overturning an ACCEPTED ADR → ESC-3.
- What works today: `bootstrap/post_review_thread.sh` (a blocking, resolvable
  thread; clears on resolution via `required_conversation_resolution`, #1207),
  plus the `needs-ai` label on a non-draft PR without `needs-human`. The latter
  routes the worker to `needs-fix` (`bin/hos-cron:1098-1100`), where the
  worker reads the PR's reviews and comments, fixes, and pushes
  (`worker-cron-prompt.md:75`).

**F6 — `validate_agents.sh` is not safe to use as an autonomous gate as-is.**
- *Payload:* in full mode it sends every `.claude/agents/*.md` (currently
  ~478 KB) plus docs in one prompt. agy silently truncates at roughly 270 KB
  and still reports success (#1718). A full-corpus agy verdict on the overseer
  would therefore be unreliable in a way that cannot be detected. (#1789: agy
  may also reply in prose.)
- *Convergence:* the verdict keys on **NEW** findings against a dedup ledger at
  `.claudetmp/framework/external-review-ledger.jsonl`. That ledger is
  gitignored and clone-local. The overseer's clone would start with an empty
  ledger, and vendor output is non-deterministic, so every run would surface
  "new" findings. That is a bounce loop.
- *Silent partial coverage:* if one vendor CLI is absent, the script prints a
  WARN and continues with the other (`:119-127`). It exits 2 only when both
  are absent.
- *Cost/time:* the cap is `AI_REVIEW_TIMEOUT=300` s per vendor, run
  sequentially (≤600 s plus parsing), per PR, per new head. The overseer
  session is capped by `HOS_CRON_MAX_SECONDS` (default 1800 s) and reviews
  several PRs per cycle. The codex reserve is also a shared, limited budget.
- *AD-16:* `validate_agents.sh` has no `claude` call site (ADR-1643 §9.4), so it
  is outside AD-16. `run_framework_validation.sh` phases 1.5/1.6
  (`validate_self.sh`, `validate_scripts.sh`) do invoke Claude.

**F7 — `check_agents_static.sh` executes untrusted input if it is run naively
on PR head.** It `source`s `scripts/framework/config.sh` from the cwd (`:42`)
and is itself under `scripts/framework/**`. Running the PR-head copy lets the
PR rewrite the check that judges it, and runs PR-controlled shell under the
overseer's credentials. It also writes a stamp into the working tree as a side
effect (`:360-366`).

**F8 — Protected surface.** `.claude/agents/**`, `scripts/framework/**`,
`bootstrap/**`, `bin/**` and `.github/workflows/**` are all in
`protected_surfaces.txt`. Every PR in scope already needs human CODEOWNERS
approval, and so does the PR that implements this change. An overseer PASS
is necessary but not sufficient (`overseer.md:55`).

**F9 — Consumer shipping is already inconsistent.**
`framework_consumer_files.txt:45` ships `.github/workflows/validation-check.yml`
to consumers under the heading "required CI status-check producers" (that
heading is stale per F2). The same file lists `check_validation_current.sh` as
internal and not shipped (`:14`). A consumer therefore appears to receive a
workflow that calls a script it does not have. Separately,
`scripts/framework/install.sh:99-106` copies `check_agents_static.sh`,
`validate_agents.sh` and `run_framework_validation.sh` into consumer repos, and
`overseer.md`/`worker.md` ship via `consumer_agents.txt`.

## Requirements

**REQ-01 — One committed entry point with a fixed argv.** Overseer-side agent
validation is a committed script (location and name are for the architect,
OQ-1) that the overseer invokes in a single, statically allowlistable Bash
call. The call has no substitutions, heredocs, loops, or runtime-named paths
(CLAUDE.md "Shell usage under the sandbox"). The overseer prompt never lists
the steps for the agent to carry out itself. Before creating a new script,
search `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` and
record the result (AGENTS.md "Use the Code"). Extending
`run_framework_validation.sh` is an acceptable outcome of that search.

**REQ-02 — Machine-readable result.** The entry point emits exactly one
structured result on stdout. Its exit codes distinguish at least:
`PASS`, `FINDINGS` (the worker can fix it), `TOOL_ERROR` (the validation could
not be completed), and `NOT_APPLICABLE` (the PR does not touch the trigger
paths). The result includes the PR number, head SHA, the phases run, the phases
skipped with reasons, and each finding (check id, file, detail). A skipped phase
is never reported as `PASS`.

**REQ-03 — Scope trigger.** The check runs on every PR whose diff against its
base (three-dot) touches `.claude/agents/**`. Any change to the trigger path
set, for example adding `docs/AGENTS.md` (an input the static check reads), is
OQ-4. For a PR outside the trigger paths the result is `NOT_APPLICABLE` and has
no effect on disposition.

**REQ-04 — Fresh, per head SHA, never attested.** The result is produced by the
overseer's own execution against the PR's **current head SHA**. It never reads
a stamp, a worker comment, a PR-body claim, or any worker-produced artifact as
evidence. A new head SHA always triggers a fresh run. Re-running for an
unchanged head SHA is not required when the overseer holds its own recorded
result for that SHA (OQ-3).

**REQ-05 — The PR cannot judge itself.** The validator code, and any config it
loads, comes from the trusted base (the default branch as the overseer has
synced it). PR-head content is **data only** and is never sourced or executed.
A PR that modifies `check_agents_static.sh`, `config.sh`, or the entry point
itself is validated by the base-branch version (F7).

**REQ-06 — No side effects on the overseer clone.** The run writes no files to
the overseer's tracked working tree (no stamps). It makes no commits or pushes
and does not switch the clone's checked-out branch. The working tree is
byte-identical before and after.

**REQ-07 — Failure bounces with content.** On `FINDINGS` the overseer does not
approve or merge, and within that cycle it:
- posts each finding (or one consolidated thread listing every finding, per
  OQ-5) as a **blocking, resolvable review thread** via
  `bootstrap/post_review_thread.sh`;
- posts its verdict via `bootstrap/pr_review.sh submit-verdict --event comment`.
  The executive summary names agent-definition validation as the failing check;
- applies `needs-ai` (via `bootstrap/edit_issue.sh`) so that `hos-cron` routes
  the worker to `needs-fix`.

This binding is **provisional on ESC-3**. It must not use `REQUEST_CHANGES`,
`record_pr_bounce()`, or a conversation comment as the bounce carrier.

**REQ-08 — A tool error is not a bounce and not a pass (fail closed).** On
`TOOL_ERROR` (script missing, non-zero tooling exit, unparseable output, or a
required vendor unavailable per ESC-2) the overseer does **not** approve or
merge and does **not** apply `needs-ai`, because the worker cannot fix the
overseer's tooling. The verdict names the check under "what this run could not
verify" (`overseer.md:616`). A persistent `TOOL_ERROR` escalates to
`needs-human` after a bounded number of cycles (bound: OQ-6).

**REQ-09 — Bounded bounce loop.** Validation bounces on the same PR are capped,
consistent with steps 4a/4c (fewer than 2 bounces, then escalate). When the cap
is reached the disposition is `HUMAN_REQUIRED` with the still-failing findings
listed. The counter must be one that actually executes today and not the
never-called `record_pr_bounce()` path (OQ-3).

**REQ-10 — Placement and charter reconciliation in `overseer.md`.**
- The new step sits with the content checks (beside 4c, before the
  protected-surface gate and the matrix), and it runs **regardless of
  protected-surface status**. It has to: every in-scope PR is protected.
- The note at `overseer.md:439` that treats the stamp check as required is
  removed or replaced. No remaining normative text refers to a validation stamp.
- The #1217 paragraph (`overseer.md:63`) is amended so that it states, without
  contradiction, that agent-definition validation is a **standing** overseer
  responsibility (the AI phase is CI-incompatible per #1216) and not part of
  the "interim until CI" state. Whether the static phase may later move to CI
  is stated explicitly, one way or the other.
- The NEVER list is unchanged. Running a validator is not an override.
- The step's text states that a PASS is necessary but not sufficient on a
  protected surface. The human CODEOWNERS approval is still required.

**REQ-11 — Worker guidance is advisory and labelled that way.** `worker.md` and
`bootstrap/worker-cron-prompt.md` recommend running
`scripts/framework/run_framework_validation.sh` (at minimum `--static-only`)
before opening a PR that touches `.claude/agents/**`. The text states that this
is **not** the gate, that no stamp or attestation is needed or accepted, and
that the overseer's own run decides. A validation bounce is handled on the
existing `needs-fix` re-entry path. This adds no new worker obligation or step.

**REQ-12 — Retire the stamp mechanism, in order.** After REQ-01…REQ-10 are
merged and have been exercised on at least one real in-scope PR (never
before, so there is no window with neither control):
`.github/workflows/validation-check.yml`, `check_validation_current.sh`,
the stamp writers in `check_agents_static.sh`, `validate_agents.sh` and
`run_framework_validation.sh`, and `scripts/framework/validation-stamps/` are
removed. So are their dependents: the stamp exemption in `secret_scan.sh`,
the stamp comment in `regen_all.sh`, the `framework_consumer_files.txt` entries,
the related tests, and doc references (`CI-EXECUTION-INVENTORY.md`, `README.md`,
regenerated `SCRIPTS-INDEX.md`). Research/history documents are left alone.
Removing the `override_expires` mechanism is subject to ESC-5.

**REQ-13 — Consumer parity.** After this change no consumer install ships a
workflow or doc that references a file the install does not ship. Existing
consumers stop running `validation-check.yml` on upgrade (the mechanism is
OQ-7). Whether the new overseer step is active in consumer projects is ESC-4.

**REQ-14 — Audit trail.** Every run appends one audit event via the existing
audit writer. The event records the PR, head SHA, phases run and skipped,
result, finding count, and the validator's base SHA. That event is also the
record REQ-04's idempotency reads.

**REQ-15 — AI phase constraints (only if ESC-1 puts it in scope).** Any Claude
invocation goes through `bootstrap/invoke_agent.sh` (AD-16). agy/codex go
through `scripts/oversight/lib/vendor_invoke.sh`. A truncated input (#1718), an
empty-envelope reply, or a prose-only reply (#1789) is `TOOL_ERROR`, never
`PASS`. The verdict must not depend on clone-local ledger state (F6). The
per-cycle time and codex spend must fit the overseer's
`HOS_CRON_MAX_SECONDS` budget, and a design that cannot fit must say so.

## Non-goals

- Moving any of this into GitHub CI (#1216 is a separate decision).
- Repairing `record_pr_bounce()` or giving it a CLI surface (#1356/#1357).
- Changing the `require-*` gates, CODEOWNERS, `protected_surfaces.txt`, the
  merge-authority matrix, or `OVERSEER_CEILING`.
- Adding `REQUEST_CHANGES` to `pr_review.sh` (it is an ADR-1657 matter, and
  appears here only as ESC-3).
- The release-gate use of `run_framework_validation.sh` in `cut_release.sh`,
  apart from removing its stamp write.

## Acceptance criteria

- **AC-1** An in-scope PR whose agent content fails `check_agents_static.sh`
  gets, in one overseer cycle, a blocking resolvable thread listing every static
  finding, a `comment` verdict naming the check, and `needs-ai`. No approve and
  no merge. (Test with a PR fixture that references a non-existent agent.)
- **AC-2** An in-scope PR with clean agent content and **no stamp committed**
  is not blocked by agent validation (the PR #1521 regression).
- **AC-3** A PR that edits `check_agents_static.sh` so it always exits 0,
  together with a broken agent file, still gets the AC-1 outcome (REQ-05).
- **AC-4** A PR whose branch `config.sh` contains a side-effecting command: the
  command does not execute in the overseer run (REQ-05).
- **AC-5** `git status --porcelain` in the overseer clone is identical before
  and after a run (REQ-06).
- **AC-6** Validator missing or exiting with a tooling error: no merge, no
  `needs-ai`, and the verdict lists the check as not verified (REQ-08).
- **AC-7** Two validation bounces on the same PR, then a third failing head:
  `HUMAN_REQUIRED`, not a third bounce (REQ-09).
- **AC-8** A second cycle on an unchanged head SHA does not re-post an
  identical thread or verdict. A new head SHA triggers a fresh run (REQ-04).
- **AC-9** A PR that does not touch `.claude/agents/**` gets
  `NOT_APPLICABLE`, and its disposition is unchanged (REQ-03).
- **AC-10** The overseer's invocation is a single literal command matching a
  static allowlist rule. A test pins the argv shape (REQ-01).
- **AC-11** After REQ-12, a grep for `check_validation_current`,
  `validation-stamps` and `validation-stamp-check` outside
  `research/`, `DECISIONS.md`, `docs/releases/` and `audit/` returns nothing.
- **AC-12** A fresh consumer install (`--local`) contains no workflow that
  calls a script absent from the install (REQ-13).
- **AC-13** `overseer.md` contains no statement that agent validation is
  interim-until-CI, and no statement that a stamp check is required (REQ-10).
- **AC-14** `scripts/framework/run_tests_inner_loop.sh` passes.

## Open questions for architect (mechanism, not product)

- **OQ-1** Where the entry point lives and whether it extends
  `run_framework_validation.sh` or wraps it. It must satisfy REQ-01/05/06.
- **OQ-2** How PR-head content is materialized without disturbing the clone
  (a temporary worktree at the head SHA, or `git archive`/`git show` of
  `.claude/agents/**` into a temp dir with the static check pointed at it via
  `--agents-dir`/`--docs`). Also how the base-branch validator is pinned.
- **OQ-3** The idempotency key (head SHA, plus the validator base SHA?) and the
  bounce counter's source of truth. The overseer's audit trail is clone-local
  (`check_pr_reviewed.sh` precedent). Say whether that is acceptable, or read
  the PR's own threads/reviews from GitHub instead.
- **OQ-4** Whether the trigger set should include the static check's other
  inputs (`docs/AGENTS.md`, `scripts/framework/config.sh`). This touches scope,
  so bring any widening back to PM/human.
- **OQ-5** Thread granularity: one thread per finding, or one consolidated
  thread. The trade-off is the number of resolution clicks for the human
  against per-finding traceability.
- **OQ-6** The `TOOL_ERROR` escalation bound (number of cycles or wall-clock).
- **OQ-7** How the installer removes a previously shipped workflow from
  existing consumers (manifest-driven deletion versus a documented manual step).

## Human escalation questions (ESC)

- **ESC-1 — Is the AI phase (`validate_agents.sh`, agy+codex) in the blocking
  gate?** The stamp only ever covered the static phase (F1), so blocking on AI
  findings is new coverage. F6 lists the problems: the full-corpus payload
  exceeds agy's silent-truncation threshold, the clone-local ledger means runs
  will not converge, 300 s per vendor per PR, and spend from the codex reserve.
  Options: (a) static only is blocking, and the AI phase is omitted;
  (b) static is blocking and the AI phase is advisory (findings posted as
  non-blocking comments); (c) both are blocking, gated on #1718 and a
  ledger-independent verdict. PM recommendation: **(b)**, or **(a)** until
  #1718 is fixed. The ruling's "where applicable" does not settle this.
- **ESC-2 — Vendor unavailable.** If the AI phase is in the gate, does one
  missing vendor fail closed (hold, REQ-08), or degrade to a single vendor
  with the skip disclosed? The script today degrades silently. PM
  recommendation: fail closed for any blocking phase.
- **ESC-3 — The meaning of "request-changes".** ADR-1657 AD-2 (ACCEPTED,
  binding, test W5) forbids bot `REQUEST_CHANGES`. PM reads the ruling as asking
  for the *semantics* (bounce back to the worker with findings) and binds
  REQ-07 to blocking thread + `comment` verdict + `needs-ai`. Please confirm.
  Choosing a literal `REQUEST_CHANGES` instead would require a new architect
  ruling and a named non-human clearing actor.
- **ESC-4 — Consumers.** `overseer.md` is CORE and ships to consumers, and so
  do `check_agents_static.sh`/`validate_agents.sh` (via `install.sh`). Should the
  new overseer step be active in consumer projects, or only in HOS? PM
  recommendation: static phase active everywhere, since `overseer.md` is CORE;
  the AI phase follows ESC-1.
- **ESC-5 — Override path.** Retiring stamps removes the human time-boxed
  `override_expires` override. PM proposes that the replacement override is a
  human resolving the blocking thread and approving as CODEOWNER, which that
  human must do anyway on this protected surface, so no new override
  mechanism is needed. Please confirm. Also confirm that deleting the committed
  historical stamp files is acceptable (git history keeps them).

## Change classification

**Structural.** The change removes an existing check, adds a new overseer
responsibility and a new bounce trigger, amends the overseer charter text, and
changes files shipped to consumers. The human ruling authorizes the direction
(items 1-4). REQ-01…REQ-14 implement only what the ruling settles. ESC-1…ESC-5
are the points it does not settle, and they must be answered before the parts
that depend on them are designed (REQ-07's final binding, REQ-12's override
removal, REQ-13's consumer scope, and all of REQ-15).

RISK: HIGH
CONFIDENCE: 80% — the findings F1-F9 are verified against code at `f6a1aceb3`.
The main uncertainties are whether `validation-check.yml` actually fails in
consumer repos (F9 was inferred from the ship lists, not from running an
install) and the real per-PR runtime of `validate_agents.sh` on the overseer
host (only the cap was read, not measured).
BLAST RADIUS: overseer merge disposition for every PR touching
`.claude/agents/**`; `overseer.md`/`worker.md` CORE text shipped to all
consumers; consumer install ship-set; the codex/agy budget if ESC-1 selects (b)
or (c).

## Human Review Required

- **ESC-1 through ESC-5** above, before the architect finalizes the design.
- **`overseer.md` charter edit (REQ-10)**: this is a protected surface and CORE
  governance text. The amended #1217 paragraph needs human review on the PR.
