# SPEC-219 — Evaluator: Verify Second-Review Reviewed Range

**Issue:** #219
**Status:** REVISED (pass 4) — ready for architect re-review
**Family:** #204 commit-range machinery
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

The cross-vendor second review (`run_second_review.sh`) is the pipeline's mandatory
independence check at MEDIUM+ tier. It operates on the diff at the time it runs. The
evaluator (`oversight-evaluator.md`) already verifies that the second review *happened*
and that its verdict is parseable, but it does not verify *which commits* the review
covered.

This creates a window for a silent scope mismatch: if `run_second_review.sh` was
invoked with a stale diff or a truncated range — whether by accident or by an agent
re-ordering steps — the review runs successfully and produces a `verdict: approve`, but
it reviewed commits that are not the same set the evaluator has established as the step's
canonical `base_sha..head_sha`. The evaluator currently has no way to detect this, and
the review's `approve` verdict is accepted as valid.

The step register already carries `base_sha` and `head_sha` (written by the evaluator
in Phase 1). The second review output header already carries a machine-readable `verdict`
field. Adding a parallel `reviewed_range` field to the output header, and verifying it
in Phase 1, closes the scope-mismatch hole without changing anything the review checks.

---

## 2. Scope

**In scope:**
- `run_second_review.sh`: emit `reviewed_range: BASE_SHA..HEAD_SHA` in the output
  header of every generated report file.
- `oversight-evaluator.md` Phase 1 second-review compliance check: read
  `reviewed_range` from the report and compare it to the register's
  `base_sha..head_sha`. COMPLIANCE WARN when absent; COMPLIANCE FAIL when present
  but mismatched.

**Out of scope:**
- What the second review checks, scores, or reports. This spec does not change the
  review's logic, prompts, vendor selection, or verdict taxonomy.
- `run_panel.sh`. The panel is post-PR and has a different range-tracking story;
  that is out of scope for this issue.
- The `risk-assessor` range check (already specified in the existing evaluator text
  under "Risk-assessment scope + blocking findings (#204)"). This spec adds a
  parallel check for the second-review artifact only.
- Retroactive re-validation of already-generated second-review reports.

---

## 3. Requirements

### R1 — `run_second_review.sh`: emit `reviewed_range` in every report header

Every report file written to `.claudetmp/second-review/step{N}-*.md` must include a
`reviewed_range:` field in its machine-readable header section, adjacent to the existing
`verdict:` field.

The value must be the literal string `BASE_SHA..HEAD_SHA` where `BASE_SHA` and
`HEAD_SHA` are the SHAs the script used to derive the diff it passed to the reviewer.
The script must capture these values at diff-derivation time — before invoking the
vendor — so the recorded range is the range the reviewer actually saw, not a
post-hoc re-derivation.

Format:
```
reviewed_range: abc1234..def5678
```

Both SHAs must be the full 40-character hex. Abbreviated SHAs are not acceptable because
the evaluator must perform an exact string comparison against the register's
`base_sha`/`head_sha` values, which are also full SHAs.

This requirement applies to all report files: agy reviews, codex reviews, fallback
combined reviews, and reports with `verdict: skipped` or `verdict: error`. A
`verdict: skipped` (score-below-threshold) report records the range that *would have*
been reviewed (the diff at invocation time). A `verdict: error` report records the range
the script attempted. Absence of `reviewed_range` in any of these cases is the condition
that triggers COMPLIANCE WARN in R3.

**Dirty-worktree path (BC-219-3).** When the diff was derived from Path 3
(HEAD-vs-worktree, i.e. `--files ...` or no `--diff` argument) and the worktree
contains uncommitted changes, the report must record:

```
reviewed_range: UNCOMMITTED
```

The literal string `UNCOMMITTED` (not a SHA pair) signals to the evaluator that the
second review ran against uncommitted state. Running the second review against a dirty
worktree is structurally wrong: the review sees changes that are not in any commit the
evaluator can verify. The evaluator's R3 must treat `reviewed_range: UNCOMMITTED` as a
COMPLIANCE FAIL (see R3 disposition table).

**No-diff-content sentinel (BC-219-4).** When the script exits early because no diff
content was detected (the `verdict: skipped` / `reason: no diff content detected`
sentinel written at line ~205 of the current script), there is no range to record.
The report must record:

```
reviewed_range: none
```

The literal string `none` is the explicit absent-range marker. The evaluator's R3
must treat `reviewed_range: none` as the absent→WARN case (not a FAIL).

### R2 — `run_second_review.sh`: derive range from invocation arguments (three paths)

The `BASE_SHA` and `HEAD_SHA` written to `reviewed_range` must be derived from the
script's own invocation arguments, not re-read from the register or any other file.
The script has three diff derivation paths; each path has its own derivation rule:

**Path 1 — `--diff <ref>` (single ref, e.g. `HEAD~1`).**
The script runs `git diff <ref>`, which compares `<ref>` to the working tree (or HEAD
when the tree is clean). BASE_SHA = `git rev-parse <ref>`, HEAD_SHA = `git rev-parse HEAD`.
Both calls must be made at diff-derivation time. These are new calls — they do not
exist in the current script; the script discards the resolved SHAs after building the
diff. R2 requires that they be captured and recorded.

**Path 2 — `--diff <A>..<B>` (range form).**
Parse `A` and `B` from the argument. BASE_SHA = `git rev-parse <A>`,
HEAD_SHA = `git rev-parse <B>`. Both must be full 40-character SHAs.

**Path 3 — `--files ...` or no `--diff` argument (HEAD-vs-worktree).**
The script runs `git diff HEAD`, which diffs the index/worktree against HEAD.
This is an uncommitted-state path. See R1 for how the `reviewed_range` field must
be recorded in this case (BC-219-3).

**`--step N` path.**
Uses the canonical step-range derivation defined in SPEC-220 (shared helper in
`scripts/oversight/lib/step_range.sh` or equivalent). Do not restate the derivation
here; SPEC-220 is the authoritative source. The BASE_SHA and HEAD_SHA produced by
that helper are recorded as `reviewed_range`.

This is a recording requirement, not a new derivation: the script was already computing
this range to build the diff. R2 requires that it capture and record what it computed
rather than discarding it.

The helper has two edge-case outputs that `run_second_review.sh` must handle before
recording:

- **Empty string** (step N has no event in the log): `run_second_review.sh` must record
  `reviewed_range: none`. The evaluator treats this as the absent-range WARN case (same
  as the no-diff-content sentinel). Do not attempt to run the diff or invoke the reviewer.

- **Leading-empty base (`..HEAD_SHA`)** (step N-1 has no event, which is normal for
  step 1): `run_second_review.sh` must apply the merge-base fallback before recording.
  Derive BASE with:
  ```
  BASE=$(git merge-base HEAD $(git rev-parse HEAD~1 2>/dev/null || echo HEAD))
  ```
  then record `BASE..HEAD_SHA`. This mirrors the merge-base fallback the evaluator uses
  for step 1 (SPEC-220 R2). The helper's contract comment explicitly delegates this
  fallback to the caller ("the caller owns the merge-base fallback for an empty base").

### R3 — `oversight-evaluator.md` Phase 1: verify `reviewed_range` matches register

The second-review compliance check (the block headed "Second-review compliance (MEDIUM+
steps)" in Phase 1) must, after establishing that a present report has an actionable
verdict (`approve`, `request_changes`, `unparseable`), also verify the range:

1. **Parse `reviewed_range`** from the report header. Extract `BASE_SHA` and `HEAD_SHA`
   as the two colon-separated SHA tokens.

2. **Compare to the register.** The register's `base_sha` and `head_sha` were written
   by the evaluator earlier in Phase 1. Compare with exact full-SHA string equality.
   Partial match, prefix match, and abbreviated-SHA match are all treated as mismatch.

3. **Disposition table — all verdicts (BC-219-5).**

   The following table is exhaustive. Every verdict the second-review script can emit
   has an explicit range-check disposition.

   | `verdict` value | `reviewed_range` value | Range check disposition |
   |---|---|---|
   | `approve` | absent | COMPLIANCE WARN — "second review report for step {N} does not record `reviewed_range`; cannot confirm the review covered the step's canonical commit range." Add to conditional items. The review ran and produced a verdict; missing field is an instrumentation gap. |
   | `approve` | `UNCOMMITTED` | COMPLIANCE FAIL — dirty-worktree second review; see below. |
   | `approve` | `none` | COMPLIANCE WARN — no-diff-content sentinel; see below. |
   | `approve` | present, mismatched | COMPLIANCE FAIL — range mismatch; see below. |
   | `approve` | present, matching | Pass silently. |
   | `request_changes` | (same rules as `approve` above, row for row) | Same as `approve`. |
   | `unparseable` | (same rules as `approve` above, row for row) | Same as `approve`. |
   | `skipped` (score-below-threshold) | absent | COMPLIANCE WARN — same instrumentation-gap message as `approve`/absent. |
   | `skipped` (score-below-threshold) | present, any value | Range check applies: same mismatch/match/UNCOMMITTED rules as `approve`. |
   | `skipped` (no-diff-content) | `none` | COMPLIANCE WARN — "second review skipped: no diff content; cannot verify range." Add to conditional items. This is not a fail: absence of diff content is a legitimate early exit. |
   | `skipped` (no-diff-content) | absent or any other value | COMPLIANCE WARN — unexpected sentinel format; treat as instrumentation gap. |
   | (any) | empty string | COMPLIANCE WARN — same as absent; missing range data, not a scope violation. Treat identically to the `none` sentinel: "second review report for step {N} does not record a usable `reviewed_range`; cannot confirm the review covered the step's canonical commit range." Add to conditional items. |
   | `error` | any | Range check **skipped** — an errored run produces no judgment to accept or reject. The error itself is already a COMPLIANCE FAIL per existing rules. Emit COMPLIANCE WARN only if `reviewed_range` is absent, to note the instrumentation gap (does not change the existing FAIL outcome). |
   | `pending` | any | Range check **skipped** — a `pending` verdict should not reach the evaluator. Evaluator emits COMPLIANCE WARN: "second review report for step {N} has `verdict: pending`; review did not complete." |
   | `UNCOMMITTED` (literal) | — | **COMPLIANCE FAIL** — "second review for step {N} ran against uncommitted worktree state (`reviewed_range: UNCOMMITTED`). Second review must run on committed state. Re-commit the changes and re-run `run_second_review.sh`." A dirty-worktree review is structurally wrong: the reviewer saw changes not in any verifiable commit. This is a hard fail regardless of the verdict. |

   **COMPLIANCE FAIL — range mismatch (present but mismatched):** "second review
   `reviewed_range` `{report_base}..{report_head}` does not match register
   `{reg_base}..{reg_head}` for step {N}. The independent review covered a different
   commit set than this step. Re-run `run_second_review.sh` scoped to the correct
   range." A mismatched range means the `approve` verdict was issued against commits
   that are not this step's diff; accepting it would defeat the independence requirement.

---

## 4. Non-Requirements

- This spec does not require the second review to re-derive or re-validate its own range
  against the register. The review runs before the register's header is written; it
  cannot consult it. Recording and checking are separated by design.
- This spec does not add a `reviewed_range` field to `run_panel.sh` output.
- This spec does not change the threshold logic, vendor routing, or fallback behavior of
  `run_second_review.sh`.
- This spec does not require the evaluator to re-run the second review if the range
  matches but the SHAs are not in the current branch's history. Range verification is
  a string comparison, not a git-object existence check.
- This spec does not require abbreviated SHA support. Full SHAs only.

---

## 5. Acceptance Criteria

AC-1. A second-review report generated after this spec ships always contains a
      `reviewed_range: FULL_SHA..FULL_SHA` line in its header.

AC-2. A report generated with `--diff HEAD~1..HEAD` records a `reviewed_range`
      that resolves to the same two full SHAs as `git rev-parse HEAD~1` and
      `git rev-parse HEAD`.

AC-3. When the evaluator reads a report whose `reviewed_range` matches the register
      exactly, the range check passes without adding any compliance note.

AC-4. When the evaluator reads a report with no `reviewed_range` field, Phase 1
      records a COMPLIANCE WARN and adds a conditional item; the step does not
      automatically escalate on this basis alone.

AC-5. When the evaluator reads a report whose `reviewed_range` does not match the
      register's `base_sha..head_sha`, Phase 1 records a COMPLIANCE FAIL and the
      recommendation is ESCALATE.

AC-6. A report from Path 3 (HEAD-vs-worktree) where the worktree is dirty records
      `reviewed_range: UNCOMMITTED` (not a SHA pair), and the evaluator issues a
      COMPLIANCE FAIL on that report regardless of verdict.

AC-7. A `verdict: skipped` / `reason: no diff content detected` sentinel records
      `reviewed_range: none`, and the evaluator issues a COMPLIANCE WARN (not FAIL)
      on that report.

AC-8. Reports with `verdict: error` include a `reviewed_range` field where possible;
      the evaluator does not perform the range comparison on `verdict: error` reports
      (the error itself is already a COMPLIANCE FAIL per existing rules).

AC-9. Reports with `verdict: pending` cause the evaluator to emit a COMPLIANCE WARN;
      the range check is skipped for `pending` reports.

AC-10. The `--step N` range derivation delegates entirely to the shared helper defined
       in SPEC-220; the script does not re-implement the step-range lookup.

AC-11. For step 1 (or any step where `get_step_range` returns `..HEAD_SHA` because the
       previous step has no log event): `run_second_review.sh` applies the merge-base
       fallback and records `MERGEBASE..HEAD_SHA`, not `..HEAD_SHA`. The evaluator
       compares this against the register's `base_sha..head_sha` (which was derived by
       the same merge-base logic in SPEC-220 R2) and finds a match; no compliance event
       is emitted.

AC-12. For any step where `get_step_range` returns empty string (step N has no event in
       the log): `run_second_review.sh` records `reviewed_range: none` and does not
       invoke the reviewer. The evaluator reads `reviewed_range: none` and emits
       COMPLIANCE WARN (not FAIL), adding a conditional item.
