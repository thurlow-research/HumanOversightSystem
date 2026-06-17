# SPEC — Worker Operational Reliability (v0.4.0, Pass 3)

**Status:** draft — for technical-design
**Issues:** #54, #157, #309, #311, #312, #316, #325
**Depends on:** `UNATTENDED-WORKER-PROTOCOL.md`, `worker.md` CORE section
**Written by:** pm-agent · 2026-06-16

---

## Purpose

This spec closes seven operational gaps surfaced during the v0.3.x CPS field test
and the v0.4.0 worker build session. Each section maps to one or more open issues,
states numbered requirements, and gives the acceptance criterion the system-test
role will verify.

Sections are independent — technical-design may sequence them across build steps
as it sees fit.

---

## §1 — Prompt-capture auto-hooking at install time (#54)

### Background

`capture_prompt.sh` and `capture_session.sh` are currently invoked manually.
Engineers forget to run them before MEDIUM+ commits. The absence is detected at
the gate, not prevented. The install script (`install.sh`) is the correct place
to make this decision once and wire the automation.

### Requirements

**R1.1 — Install-time prompt.**
During `install.sh` setup, after the project config questions, present:

```
Enable prompt artifact capture for MEDIUM+ changes?
This installs a Claude Code hook that logs session turns automatically
and reminds you to run capture_prompt.sh before committing MEDIUM+ changes.
[Y/n]:
```

**R1.2 — "Yes" path: hook wiring.**
When the operator selects Y, `install.sh` writes or updates `.claude/settings.json`
with two hooks:

- `PostToolUse` on `Edit` or `Write` tool calls → invoke
  `capture_session.sh --log {file} "{description}"` where `{file}` is the path
  of the file just written/edited.
- `Stop` → if any file touched in the session since the last `capture_prompt.sh`
  run is tracked as MEDIUM+ risk, emit a reminder: "One or more MEDIUM+ files were
  changed this session. Run capture_prompt.sh before your next commit."

The `Stop` hook reminder is advisory only — it does not block the session.

**R1.3 — "No" path: explicit suspension.**
When the operator selects N, `install.sh` appends to `contract/gate-suspension.md`:

```
## SUSPENDED: prompt-capture
Authorized at: {ISO-8601 install timestamp}
Authorizing operator: {git config user.email or $USER}
Reason: opted out at install time
Re-enable: re-run install.sh and select Y, then run capture_prompt.sh --re-enable
```

The entry is subject to the brownfield re-enable invariant: once suspended, the
record is permanent in git history even after re-enabling.

**R1.4 — Audit trail per pipeline run.**
Every pipeline run (inner loop and transition gate) must emit exactly one of these
events regarding prompt-capture:

- `gate-suspended` — prompt-capture is in `gate-suspension.md`; no artifact is
  expected for this run.
- `gate-na` — the step's risk tier is LOW; prompt artifact is not required
  regardless of capture status.
- `artifact: <path>` — the prompt artifact exists at the given path; the gate
  passed.

These events are written to `audit/oversight-log.jsonl` as
`"event": "prompt-capture-status"` with the appropriate value.

**R1.5 — No silent miss.**
If prompt-capture is active (not suspended) and the step tier is MEDIUM or higher
and no artifact path is recorded, the transition gate fails with a clear message:
"Prompt artifact required for MEDIUM+ step — run capture_prompt.sh or check hook
wiring."

### Acceptance criteria

- AC1.1: An install run with Y selected results in `.claude/settings.json`
  containing both hooks. A subsequent Edit tool use during a session triggers
  `capture_session.sh`.
- AC1.2: An install run with N selected results in `gate-suspension.md` containing
  the `SUSPENDED: prompt-capture` entry. The transition gate emits `gate-suspended`
  for that install.
- AC1.3: A LOW-tier step emits `gate-na` in the audit log, regardless of
  prompt-capture status.
- AC1.4: A MEDIUM+ step with active capture and no artifact causes the transition
  gate to fail (non-zero exit). The failure message identifies which step and that
  the artifact is missing.

### Open questions

- OQ1.1: Should the `Stop` hook MEDIUM+ reminder check against the risk-assessor's
  cached output (if available) or use a static file-extension heuristic? The static
  heuristic is simpler and avoids a dependency on risk-assessor output that may not
  exist yet. **Escalating to technical-design** to choose the implementation; the
  spec requires the behavior but not the mechanism.

---

## §2 — Collection-integrity gate (#157)

### Background

A CPS field test PR deleted a module and orphaned five unit tests and three system
tests that imported from it. The test suite has errored on collection since that PR
merged. Nothing in the oversight pipeline caught it — the inner-loop gates do not
run the full suite, and the unit-test reviewer measures coverage on changed files
only.

### Requirements

**R2.1 — Gate definition.**
A collection-integrity gate runs `pytest --collect-only -q` against the full test
suite and fails (non-zero exit) on any collection error. Collection errors include:
`ImportError`, `ModuleNotFoundError`, and any other error that prevents pytest from
loading a test module.

**R2.2 — Trigger condition.**
The gate runs on any diff that touches at least one `*.py` file. It does not run
on diffs that touch only non-Python files.

**R2.3 — Pipeline position.**
The collection-integrity gate is a transition gate (Phase 5, before sign-off).
It runs after the inner-loop gates and before the oversight-evaluator. A collection
error is a gate failure — the build step does not advance to sign-off until the
error is resolved.

**R2.4 — Unit-test role assertion.**
The `unit-test` agent must include in its sign-off entry the assertion:
"0 collection errors in the full suite." This is a required field in the sign-off
register for any build step that touches Python files. A sign-off that omits this
field or records a non-zero collection error count fails oversight-evaluator Phase 1
compliance.

**R2.5 — Error output.**
When the gate fails, it prints the full `pytest --collect-only -q` output so the
developer sees exactly which test files failed to import and why.

### Acceptance criteria

- AC2.1: A commit that deletes a Python module and breaks an import in a test file
  causes the collection-integrity gate to exit non-zero. The gate output identifies
  the failing test file and the missing module.
- AC2.2: A commit that touches only non-Python files does not trigger the collection-
  integrity gate.
- AC2.3: The unit-test sign-off register entry for any Python-touching step includes
  the "0 collection errors" assertion. The oversight-evaluator rejects a sign-off
  that omits it.

---

## §3 — Session-state artifact (#309)

### Background

Resuming a coding session currently requires 5–10 turns of archaeology. The v0.4.0
build session started with ~10 turns of context reconstruction before any code was
written. A structured, cheap-to-write artifact eliminates this.

### Requirements

**R3.1 — Artifact location and lifecycle.**
The session-state artifact lives at `.claudetmp/session-state.md`. It is gitignored.
It is overwritten (not appended) at the end of each session turn that makes
significant progress. "Significant progress" means: a commit landed, a build step
completed, a blocker was identified or resolved, or the active branch changed.

**R3.2 — Format.**
The file uses this exact template:

```markdown
# Session State — {ISO-8601 date}

## Active work
- Branch: {branch name}
- Build step: {step label, e.g. "B11 (hos_orchestrator.sh)"}
- PR: {PR number or "none yet"}

## Done this session
- {brief bulleted list — one line per item}

## Next
- {brief bulleted list — one line per item}

## Open blockers
- {issue number and one-line description, or "none"}
```

No other fields are required. Additional fields are permitted but must not replace
these five sections. The file must be human-readable without tooling.

**R3.3 — Write trigger (interactive mode).**
`worker.md` interactive mode writes or updates the session-state file at the end of
any turn that meets the "significant progress" threshold (R3.1). The write is not
deferred to session end — it happens immediately after the progress event so that
a session crash does not lose the state.

**R3.4 — Read trigger (session start).**
On session start, the interactive-mode worker checks whether `.claudetmp/session-state.md`
exists. If it does, the worker reads it and includes a summary in its first
response to the human before asking what's next. The summary must not exceed 3
sentences. If the file does not exist, the worker orients itself from git state
(branch, recent commits) instead.

**R3.5 — Template file.**
A template is shipped at `templates/session-state.template.md` with the format
from R3.2 and placeholder values. The template is the canonical definition of the
format; if R3.2 and the template conflict, the template governs.

**R3.6 — Self-assessment gate integration.**
The self-assessment gate (`pr_readiness.py`, step 8.9) writes its pass/fail result
as a line in the session-state file under `## Open blockers` on failure or under
`## Done this session` on pass. This is noted in the gate's output but does not
replace the gate's own output file.

### Acceptance criteria

- AC3.1: After a session in which at least one commit lands, `.claudetmp/session-state.md`
  exists and contains all five required sections with non-placeholder values.
- AC3.2: A fresh agent session on the same repo reads the session-state file and
  produces a correct 2–3 sentence orientation summary as its first response. The
  agent begins substantive work by turn 2 without prompting for context that is
  already in the state file. ("Coding within 2 turns" means: the first worker-dispatched
  coder or spec invocation happens no later than turn 2.)
- AC3.3: `templates/session-state.template.md` exists and matches the format in R3.2.

---

## §4 — Triage-threshold calibration, two-phase (#311)

### Background

`triage.py` uses regex pattern matching with a 0.75 confidence floor. For
real-world `hos-coordination` issues — coordination questions, status updates,
ambiguous reports — the regex signal quality may be too weak to reach 0.75
reliably. The result would be a system that escalates nearly everything to human,
making autonomous triage ceremonial (field report O7, #304).

Calibration must precede production triage mode. This spec covers Phase 1 only.
Phase 2 (threshold updates) is deferred until calibration data exists.

### Phase 1 requirements — calibration protocol

**R4.1 — Sample definition.**
The calibration sample is the 50 most recent real `hos-coordination`-labeled issues
from the CPS field test. "Real" means: filed during a live session, not synthetic
test issues. The sample is taken by listing issues with the `hos-coordination` label
sorted by created date descending and taking the first 50.

**R4.2 — Measurements.**
For each issue in the sample, run `triage.py` with the current patterns and floor
and record:

- The assigned class (bug / security / communication / other).
- The confidence score.
- Whether the confidence score reached the 0.75 floor.
- For security-classified issues: a human reviewer confirms or denies that the
  issue is actually a security report (false-positive assessment).

**R4.3 — Aggregate metrics.**
From the per-issue records, compute:

- Fraction of issues that reached the 0.75 floor, by class.
- Overall fraction across all classes.
- False-positive rate for the security class (issues classified as security that
  the human reviewer confirmed are not security reports).

**R4.4 — Decision gate.**
After computing the aggregate metrics, apply this decision gate:

- If fewer than 30% of issues reach the 0.75 floor across all classes:
  lower the floor for communication-class items OR add a lightweight model call
  for triage (to be decided in Phase 2 and recorded in `DECISIONS.md`).
- If more than 5% of security-classified issues are false positives:
  tighten the security patterns (false positives mean non-security issues get
  embargoed, which is an operational harm).
- If more than 50% of issues are misclassified overall: rebuild the signal set.
- If all thresholds are met: no change required; record the result in `DECISIONS.md`
  and proceed to production mode.

Only one of these branches applies per calibration run. Record the chosen branch
and the rationale in `DECISIONS.md` before implementing any change.

**R4.5 — Output artifact.**
The calibration run produces a documented output: a markdown table of the 50
issues with their classification, confidence score, and (for security) the human
reviewer's confirmation. This artifact is committed to `audit/` as
`audit/triage-calibration-{date}.md`. It is the input to Phase 2.

### Phase 2 — threshold update (TBD)

Phase 2 covers: implementing the decision chosen in R4.4 (lower floor, add model
call, tighten patterns, or confirm no change), updating `triage_confidence_floor`
in `hos-coordination.defaults.yaml`, and updating `triage.py` if patterns change.

Phase 2 requirements are deferred. They will be written as an addendum to this
spec or a separate spec after the calibration artifact (R4.5) exists and the
decision gate (R4.4) has been applied. The Phase 2 spec author reads the
calibration artifact and the chosen branch from `DECISIONS.md` before writing.

### Acceptance criteria

- AC4.1 (Phase 1): The calibration protocol runs against the 50-issue sample and
  produces `audit/triage-calibration-{date}.md` with per-issue and aggregate
  results.
- AC4.2 (Phase 1): The decision gate (R4.4) is applied and the chosen branch is
  recorded in `DECISIONS.md` before any `triage.py` change is made.
- AC4.3 (Phase 2, TBD): `triage_confidence_floor` in `hos-coordination.defaults.yaml`
  reflects the calibrated value. `triage.py` reflects any pattern changes.

---

## §5 — Repo scope assertion in interactive mode (#312)

### Background

An HOS worker session was asked to resolve a merge conflict in a different repo
(thurlow-research/condoparkshare) and began acting before the human caught the
mistake. The agent had no mechanism to detect or flag the scope crossing. A scope
crossing undermines the governance model: no triage, no claim, no budget gate ran
for the work, and the audit trail would have been wrong.

Autonomous mode already has implicit scope enforcement (the probe is configured to
specific customer repos). This spec covers interactive mode only.

### Requirements

**R5.1 — Session scope derivation.**
On session start, the interactive-mode worker derives the canonical repo identifier
from `git remote get-url origin` using the same slug algorithm as `activation.py`
(the `<owner>/<repo>` form, normalized to lowercase). This value is the
**session scope** for the duration of the session.

**R5.2 — Scope-crossing detection.**
Before acting on any of the following, the worker checks whether the target resolves
to the session scope:

- A file path (check: does the absolute path resolve to the working tree of the
  session scope repo?).
- A PR number plus an explicit repo hint (e.g., `thurlow-research/condoparkshare#116`).
- An issue URL or issue number plus an explicit repo hint.

If the target resolves to a different repo, trigger the scope-crossing response
(R5.3).

**R5.3 — Scope-crossing response.**
When a scope crossing is detected, the worker responds with this message and does
not proceed:

> "That [file / PR / issue] appears to be in `<other-owner>/<other-repo>`, not
> `<session-owner>/<session-repo>` (my current scope). Work for a different repo
> should go through that repo's worker session."

This response is emitted once. The worker then waits for the human's next message.
There is no override path — if the human confirms the cross-repo request is
intentional, the worker explains again that the correct path is a session scoped
to the target repo and declines to proceed.

**R5.4 — No repeated nags.**
The scope-crossing message is emitted once per detected crossing. The worker does
not repeat it in subsequent turns for the same request.

**R5.5 — worker.md placement.**
The scope guard behavior is specified in the `worker.md` CORE section under
"Scope guard (both modes)" (the section already exists in the current `worker.md`
as of 2026-06-16). Technical-design confirms whether the existing section
satisfies R5.1–R5.4 or requires additions.

**R5.6 — Research finding.**
After the scope-guard behavior is verified as working, file a research finding at
`audit/findings/agent-scope-assertion-prevents-cross-repo-drift.md` documenting
the original incident, the fix, and the test result.

### Acceptance criteria

- AC5.1: In an interactive session scoped to `thurlow-research/HumanOversightSystem`,
  asking the worker to edit a file in `thurlow-research/condoparkshare` (by
  absolute path or explicit repo reference) results in the scope-crossing message
  and no action on the target file.
- AC5.2: The scope-crossing message is emitted once, not repeatedly per turn.
- AC5.3: After the human confirms the cross-repo request is intentional, the worker
  declines and explains the correct path.

---

## §6 — Dead-man switch notification path (#316)

### Background

R11.5 of `UNATTENDED-WORKER-PROTOCOL.md` specifies the dead-man switch: if no
probe-completion event is recorded in GitHub in the last 6 hours, a human must be
paged. The detection logic exists (`breakers.py:dead_man_triggered()`). The
notification path does not exist. The operator guide has a "Not yet implemented"
placeholder. This section specifies the notification path.

### Requirements

**R6.1 — External checker script.**
A standalone script `scripts/automation/check_dead_man.sh` implements the dead-man
checker. It is separate from the orchestrator loop — a dead loop cannot report its
own death, so the checker must run under an independent cron.

**R6.2 — Dead-man condition.**
The checker evaluates the dead-man condition by calling:

```bash
python3 -c "
from scripts.automation.lib.breakers import dead_man_triggered
import sys
customer = sys.argv[1]
sys.exit(0 if not dead_man_triggered(customer) else 1)
" "$CUSTOMER"
```

Exit 0 means no trigger (loop is alive). Exit 1 means the condition is met (no
probe event in 6 hours) — trigger the notification path.

**R6.3 — Configuration keys.**
The following optional keys are read from `machine-accounts.env`:

- `ONCALL_EMAIL` — if set, the checker sends an email to this address using the
  system MTA (`mail -s "HOS dead-man switch: no probe in 6h for $CUSTOMER" "$ONCALL_EMAIL"`).
- `ONCALL_WEBHOOK_URL` — if set, the checker POSTs a JSON payload to this URL:
  `{"event": "dead_man_triggered", "customer": "$CUSTOMER", "triggered_at": "<ISO-8601>"}`.

Both are optional. If neither is set, the checker falls through to the GitHub
issue fallback (R6.4).

**R6.4 — GitHub issue fallback.**
The GitHub issue is the minimum always-available notification path. When the dead-man
condition is triggered, the checker always creates a `needs-human`-labeled issue on
the configured repo regardless of whether `ONCALL_EMAIL` or `ONCALL_WEBHOOK_URL`
is set:

```
Title: Dead-man switch: no probe-completion event in 6h — worker may be down
Body: The dead-man checker (R11.5) detected no probe-completion event for
      customer <CUSTOMER> in the last 6 hours. The worker may be stopped, hung,
      or unable to post to GitHub.
      
      Checker triggered at: <ISO-8601>
      Last known probe event: <timestamp from breakers.py, or "unknown">
      
      Action required: check crontab, orchestrator log, and machine connectivity.
Labels: needs-human
```

The issue is created using the worker machine account credentials configured in
`machine-accounts.env`.

**R6.5 — Notification priority.**
When the dead-man condition triggers, the checker fires all configured notification
paths in this order: (1) `ONCALL_WEBHOOK_URL` if set, (2) `ONCALL_EMAIL` if set,
(3) GitHub issue (always). All configured paths fire; a failure in one path does
not suppress the others.

**R6.6 — Cron installation.**
The operator guide must document a separate cron entry for the dead-man checker,
distinct from the worker and overseer cron entries. The checker cron must not run
on the same schedule as the worker — recommended offset is a different minute (e.g.,
worker at `*/15`, checker at `7,22,37,52`). This ensures the checker fires even
when the worker's scheduled minute is missed.

**R6.7 — Operator guide update.**
Remove the "Not yet implemented" placeholder from
`docs/specs/UNATTENDED-WORKER-OPERATOR-GUIDE.md` under "Dead-man switch." Replace
it with a description of `check_dead_man.sh`, the configuration keys, and the
example cron entry.

**R6.8 — machine-accounts.env documentation.**
`machine-accounts.env` (or its template) must document `ONCALL_EMAIL` and
`ONCALL_WEBHOOK_URL` as optional keys with comments explaining their effect.

### Acceptance criteria

- AC6.1: When `dead_man_triggered()` returns True and `ONCALL_EMAIL` is set, the
  checker sends an email to that address and creates a `needs-human` issue.
- AC6.2: When `dead_man_triggered()` returns True and neither `ONCALL_EMAIL` nor
  `ONCALL_WEBHOOK_URL` is set, the checker creates a `needs-human` issue.
- AC6.3: The `needs-human` issue body contains the customer name, triggered-at
  timestamp, and last-known probe event.
- AC6.4: The operator guide no longer contains the "Not yet implemented" placeholder.
  It documents `check_dead_man.sh` with an example cron entry.
- AC6.5: `machine-accounts.env` (or its template) documents the two optional keys
  with comments.

---

## §7 — Empty-PR guard (#325)

### Background

A CPS oversight session spent a review cycle on a PR with zero commits ahead of
base. The branch had been rebased and all commits dropped ("already upstream").
GitHub reported the PR as mergeable-conflicting but did not prevent the review from
starting. Both the worker (before opening a PR) and the overseer (before running a
review) need a guard.

### Requirements

**R7.1 — Worker pre-open check.**
Before executing `gh pr create`, the worker must verify that the branch has at
least one commit ahead of the target base:

```bash
git log origin/<base>..HEAD --oneline
```

If this command produces no output (empty), the worker must NOT open the PR.
Instead it must:

1. Log: "Branch has zero commits ahead of `<base>` — PR not opened."
2. Post a comment on the originating issue (if one exists) explaining that the
   fix appears to already be upstream.
3. Close the originating issue with label `already-upstream` if the fix is
   confirmed upstream.
4. Write a `## Open blockers` entry in `.claudetmp/session-state.md`:
   "Branch `<branch>` has zero commits ahead of `<base>` — investigate before
   opening PR."

The worker does not self-merge or close the branch — it surfaces the state and
waits for human confirmation.

**R7.2 — Overseer pre-review check.**
Before running a review cycle on any PR, the overseer must verify that the PR has
at least one commit ahead of the base using:

```bash
gh pr diff <PR-number> --name-only
```

or equivalently:

```bash
git log origin/<base>..origin/<head> --oneline
```

If the output is empty (zero commits ahead of base), the overseer must NOT proceed
with a review. Instead it must:

1. Post a structured comment on the PR:
   ```
   [OVERSEER] Empty-PR guard triggered.
   
   This PR has zero commits ahead of base. There is nothing to review.
   
   Possible causes:
   - The branch was rebased and all commits were already upstream.
   - The branch was reset to match the base.
   
   Action required: close this PR and investigate the branch state.
   The oversight review cycle has NOT been run.
   ```
2. Apply the label `needs-human` to the PR.
3. Do NOT write a sign-off register entry (there is nothing to sign off).
4. Do NOT mark the PR as reviewed or approved.

**R7.3 — Post-rebase guard.**
After any `git rebase` operation in either interactive or autonomous mode, the
worker must run:

```bash
git log origin/<base>..HEAD --oneline
```

If the output is empty, the worker must not push the branch. It must surface the
result to the human (interactive) or create a `needs-human` issue (autonomous) with
the message: "Rebase dropped all commits — branch is identical to `<base>`. Verify
the fix is upstream before closing the originating issue."

**R7.4 — Cross-reference.**
`SPEC-overseer-merge-authority.md` (when written) must cross-reference R7.2 of
this spec for the overseer's pre-review obligation. This spec is authoritative for
the empty-PR guard behavior for both roles.

### Acceptance criteria

- AC7.1: In a simulated scenario where a branch has zero commits ahead of base,
  `gh pr create` is not executed. The session-state file contains an "Open blockers"
  entry describing the empty branch.
- AC7.2: In a simulated scenario where the overseer receives a PR with zero commits
  ahead of base, the overseer posts the structured comment, applies `needs-human`,
  and does not write a sign-off register entry.
- AC7.3: After a simulated rebase that drops all commits, the worker does not push
  the branch and surfaces the result.

---

## Cross-references

| This spec | References |
|---|---|
| §1 (prompt capture) | `install.sh`, `capture_session.sh`, `capture_prompt.sh`, `contract/gate-suspension.md` |
| §2 (collection gate) | `contract/OVERSIGHT-CONTRACT.md` §3 (sign-off schema), inner-loop gates |
| §3 (session state) | `worker.md` CORE "Session state" section, `templates/session-state.template.md` |
| §4 (triage calibration) | `scripts/automation/lib/triage.py`, `docs/specs/UNATTENDED-WORKER-PROTOCOL.md §5`, `DECISIONS.md` |
| §5 (repo scope) | `worker.md` CORE "Scope guard" section, `scripts/automation/lib/activation.py` |
| §6 (dead-man notification) | `UNATTENDED-WORKER-PROTOCOL.md R11.5`, `scripts/automation/lib/breakers.py`, `docs/specs/UNATTENDED-WORKER-OPERATOR-GUIDE.md` |
| §7 (empty-PR guard) | `worker.md` CORE step 9, overseer review protocol, `SPEC-overseer-merge-authority.md` |

---

## Open questions requiring human resolution

- OQ1.1 (§1): `Stop` hook MEDIUM+ reminder — static file-extension heuristic or
  risk-assessor cached output? Escalated to technical-design for implementation
  choice; behavioral requirement is fixed.
- OQ4.1 (§4): The calibration sample requires access to CPS `hos-coordination`
  issues. Confirm the worker account has read access to the CPS repo's issue list
  before scheduling the calibration run.
