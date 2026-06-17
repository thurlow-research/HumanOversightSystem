# SPEC-219 — Evaluator: Verify Second-Review Reviewed Range

**Issue:** #219
**Status:** Draft — for architect review
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
`verdict: skipped` report records the range that *would have* been reviewed (the diff
at invocation time); a `verdict: error` report records the range the script attempted.
Absence of `reviewed_range` in any of these cases is the condition that triggers
COMPLIANCE WARN in R3.

### R2 — `run_second_review.sh`: derive range from `--diff` / `--step` arguments

The `BASE_SHA` and `HEAD_SHA` written to `reviewed_range` must be derived from the
script's own invocation arguments, not re-read from the register or any other file.
The script already accepts `--diff BASE..HEAD` and `--step N` arguments. For
`--step N`, the script must resolve the step's base and head using the same
`audit/oversight-log.jsonl` lookup the evaluator uses (grep for the most recent
`step-head` event for step N-1 as base, and `git rev-parse HEAD` as head). For
`--diff BASE..HEAD`, parse the argument directly.

This is a recording requirement, not a new derivation: the script was already computing
this range to build the diff. R2 requires that it record what it computed rather than
discarding it.

### R3 — `oversight-evaluator.md` Phase 1: verify `reviewed_range` matches register

The second-review compliance check (the block headed "Second-review compliance (MEDIUM+
steps)" in Phase 1) must, after establishing that a present report has an actionable
verdict (`approve`, `request_changes`, `unparseable`), also verify the range:

1. **Parse `reviewed_range`** from the report header. Extract `BASE_SHA` and `HEAD_SHA`
   as the two colon-separated SHA tokens.

2. **Compare to the register.** The register's `base_sha` and `head_sha` were written
   by the evaluator earlier in Phase 1. Compare with exact full-SHA string equality.
   Partial match, prefix match, and abbreviated-SHA match are all treated as mismatch.

3. **Disposition:**
   - `reviewed_range` field **absent** from the report: **COMPLIANCE WARN** — "second
     review report for step {N} does not record `reviewed_range`; cannot confirm the
     review covered the step's canonical commit range." Add to conditional items.
     Do not FAIL: the review ran and produced a verdict; the missing field is an
     instrumentation gap, not evidence the wrong range was reviewed.
   - `reviewed_range` field **present but mismatched** (either SHA differs from the
     register): **COMPLIANCE FAIL** — "second review `reviewed_range`
     `{report_base}..{report_head}` does not match register `{reg_base}..{reg_head}` for
     step {N}. The independent review covered a different commit set than this step.
     Re-run `run_second_review.sh` scoped to the correct range." This is a hard fail:
     a mismatched range means the `approve` verdict was issued against commits that are
     not this step's diff; accepting it would defeat the independence requirement.
   - `reviewed_range` field **present and matching**: check passes silently.

The range check applies to every report with a real verdict (`approve`, `request_changes`,
`unparseable`). It does not apply to `verdict: error` reports because an errored run
produces no judgment to accept or reject; the error itself is already a COMPLIANCE FAIL
per existing rules.

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

AC-6. Reports with `verdict: skipped` and `verdict: error` include a `reviewed_range`
      field (AC-1 applies universally); the evaluator does not perform the range
      comparison on `verdict: error` reports (non-requirement above).
