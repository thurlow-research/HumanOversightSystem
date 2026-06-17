# SPEC-367 — Risk-Historian Churn Signal: Replace PR Count with Commit Churn

**Issue:** #367
**Status:** Draft
**Date:** 2026-06-17
**Classification:** Additive — replaces a noisy proxy with two clean, independent
signals for behavior that was always implied by the churn-tracking intent

---

## 1. Problem Statement

The `risk-historian` agent and the `issue_query.py` `_git_churn()` function use
commit count (via `git log --oneline --follow --since=90.days`) as a proxy for
file churn. This produces an inaccurate signal for the HOS repo because:

1. **HOS uses PRs for many non-delivery purposes**: backfills, forward-ports,
   spec-only passes, research commits, and doc updates all produce commits that
   touch files without changing their logic. A file can score as high-churn
   because it was included in several forward-port branches, not because its
   logic is unstable.

2. **Churn and bug density are mixed into a single composite score** in
   `analyse_files()`: `score = issue_score * 0.7 + churn_score * 0.3`. This
   means a file with no bugs but high doc-commit activity inflates the score, and
   conversely, a file with many bugs but low recent activity is under-weighted.
   The two signals measure different risk dimensions and should be independently
   observable.

The root cause is that commit count is not a reliable proxy for "how frequently
has the logic in this file changed?" — it conflates logic changes with
housekeeping, documentation, and structural reorganization commits.

---

## 2. Scope

This spec covers:

- **`scripts/oversight/validators/issue_query.py`** — specifically the
  `_git_churn()` function and the `analyse_files()` composite scoring section.
- **`.claude/agents/risk-historian.md`** — the git churn query instructions and
  the output format block.

This spec does not cover:

- `schema.py` weights or the `WEIGHTS["historical_density"]` value.
- The composite risk scoring logic in `risk-assessor` that consumes
  `risk-historian` output.
- How the caller (`run_validators.sh`) or downstream agents weight churn vs.
  bug density in final tier classification.
- The GitHub issues query logic (`_gh_issues_for_files()`) — unchanged.
- Any other validator or agent.

---

## 3. Requirements

### REQ-367-01: Commit churn signal uses `git log --follow -- <file>` count

The churn signal MUST be derived from the count of commits returned by
`git log --follow -- <file>`, scoped to the last 90 days (consistent with the
current window). The `--oneline` flag is retained for efficiency.

The command form is:

```bash
git log --oneline --follow --since=90.days -- <file>
```

This is the same command already in use. The change is in how the result is
filtered before counting (see REQ-367-02).

### REQ-367-02: Exclude documentation and non-logic commits from churn count

Before counting, commit lines whose subject starts with any of the following
prefixes (case-insensitive) MUST be excluded:

- `docs:`
- `spec:`
- `research:`

A commit subject is the first line of the commit message as rendered by
`--oneline` (everything after the short hash). Exclusion is based on prefix
match against the subject text only — the hash prefix is stripped before
matching.

Commits whose subjects do NOT start with an excluded prefix are counted as
logic-change commits.

Rationale: these prefixes identify commits that make no behavioral change to
the file's logic. Excluding them reduces false-positive churn scores on files
that are frequently annotated or documented without their logic changing.

Non-requirement: this spec does not define an exhaustive exclusion list. The
three prefixes above are the only ones specified. Adding further exclusion
prefixes is a future spec change.

### REQ-367-03: Bug density remains a separate score dimension

The bug density signal (GitHub issues with labels `bug`, `regression`, or any
label in the existing `_RISK_LABELS` list that references the file) MUST remain
a fully separate score dimension. It MUST NOT be folded into the churn score.

`analyse_files()` MUST return both values as independent top-level fields in the
`raw_value` dict: `churn` (commit count after exclusion) and `issue_count` (bug
density count). These fields already exist; this requirement formalizes their
independence.

### REQ-367-04: `risk-historian` reports two separate scores

The agent output block in `risk-historian.md` MUST report commit churn and bug
density as two separate labeled lines in the per-file profile. The output format
MUST distinguish:

- `Commits (logic, 90 days): N  [--follow applied, doc/spec/research commits excluded]`
- Issue counts by label (unchanged format)

The agent MUST NOT combine or average these two values in its output. Downstream
interpretation (weighting, tier classification) belongs to `risk-assessor`.

### REQ-367-05: `_git_churn()` returns filtered count only

The `_git_churn()` function in `issue_query.py` MUST return the post-exclusion
count (logic commits only). The raw unfiltered count is not persisted or
returned. The caller (`analyse_files()`) already uses the churn count directly
as the basis for `churn_score`; no interface change is required beyond the
filtering step inside `_git_churn()`.

---

## 4. Non-Requirements

- **No change to composite score weights.** The existing
  `score = issue_score * 0.7 + churn_score * 0.3` formula and the
  `WEIGHTS["historical_density"]` value in `schema.py` are unchanged by this
  spec. Whether the weights should be revisited given the cleaner signal is a
  separate question outside this scope.
- **No change to the 90-day window.** The lookback period for commit churn
  remains 90 days.
- **No new exclusion prefixes.** Only `docs:`, `spec:`, and `research:` are
  specified for exclusion. `chore:`, `refactor:`, `style:`, and similar
  conventional-commit prefixes are deliberately out of scope — their exclusion
  requires a separate spec decision.
- **No change to `_RISK_LABELS`.** The set of GitHub issue labels that
  contribute to bug density is unchanged.
- **No output schema change to `make_result()`.** The `raw_value` dict already
  carries `churn` and `issue_count` as separate keys. No schema.py change is
  required.

---

## 5. Open Questions

**OQ-367-01 — Case sensitivity of prefix matching**
The spec says "case-insensitive." Git commit messages in this repo use lowercase
prefixes consistently. Is case-insensitive matching the correct default, or
should it be case-sensitive (exact `docs:` only)?

Architect ruling needed before implementation.

**OQ-367-02 — Label set for bug density**
The current `_RISK_LABELS` includes `security-finding`, `privacy-finding`,
`design-concern`, `spec-gap`, `test-resistance`, `escaped-defect` — labels that
are not strictly "bugs" or "regressions." Issue #367 says "bug density: GitHub
issues with labels 'bug' or 'regression'." Should the filter be narrowed to
only `bug` and `regression`, or should the existing broader label set be
retained?

Architect ruling needed before implementation.

---

## 6. Out of Scope

- Changes to the fix-commit density query (`git log --grep="fix\|bug\|error\|patch"`)
  in `risk-historian.md` — that is a separate signal and is unchanged.
- Changes to `run_validators.sh` invocation of `issue_query.py`.
- Changes to how `risk-assessor` interprets the historian's output.
- Removing or deprecating the 180-day rename history query in `risk-historian.md`.
