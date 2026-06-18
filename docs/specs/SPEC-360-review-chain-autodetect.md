# Requirements Spec — Issue #360: run_review_chain.sh Auto-Detect Changed Files

**Document type:** Requirements specification
**Status:** Draft — for technical-design
**Issue:** #360
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

`run_review_chain.sh` passes no files to `run_validators.sh` when invoked without explicit
file paths. `run_validators.sh` interprets this as "no files specified," writes a CRITICAL
summary, and exits non-zero. The CRITICAL tier then propagates to the second review, which
runs against a fallback tier rather than one derived from the actual diff. This was observed
during the retroactive v0.3.8 validation run.

The script should resolve the file list automatically from the git diff when no explicit
paths are provided.

---

## 2. Scope

This spec covers only `scripts/run_review_chain.sh`. It does not change the behavior of
`scripts/oversight/run_validators.sh`, `scripts/run_second_review.sh`, or
`scripts/run_panel.sh`. Those scripts receive file lists from `run_review_chain.sh` and
need no change.

---

## 3. Modes (authoritative)

Three mutually exclusive input modes, evaluated in this priority order:

| Priority | Mode | Trigger | Behavior |
|---|---|---|---|
| 1 | Explicit paths | One or more bare positional args after `--` or without a leading `--` | Pass those paths to validators exactly as today (no change to existing behavior) |
| 2 | `--since-main` | Flag is present | Detect via `git diff origin/main..HEAD --name-only` |
| 3 | `--since-tag` | Flag is present, or no paths and no `--since-main` | Detect via `git diff <last-tag>..HEAD --name-only`; fall back to `git diff HEAD~1..HEAD --name-only` if no tag exists |

`--since-tag` is the default when the script is called with no file arguments and no
`--since-main` flag. The operator does not need to pass any flag to get auto-detection.

`--since-tag` and `--since-main` are mutually exclusive. The script must error if both
are passed.

---

## 4. Functional Requirements

**R1 — No-args auto-detect.**
When `run_review_chain.sh` is invoked with no positional file arguments, it must
auto-detect changed files before invoking `run_validators.sh`. The CRITICAL fallback
must not occur due to an empty file list.

**R2 — `--since-tag` behavior.**
`git describe --tags --abbrev=0` is used to find the most recent tag reachable from HEAD.
If a tag is found, the diff range is `<tag>..HEAD`. If no tag exists (new repo or no
releases), the diff range falls back to `HEAD~1..HEAD`. The fallback must be logged as
a warning so the operator knows why a tag was not used.

**R3 — `--since-main` behavior.**
The diff range is `origin/main..HEAD`. If `origin/main` cannot be resolved (e.g., no
remote configured), the script must exit with a clear error message directing the
operator to use explicit paths or `--since-tag` instead.

**R4 — Empty diff handling.**
If the resolved diff is empty (no changed files in range), the script must:
- Log a clear warning stating the diff was empty and the range used.
- Still invoke `run_validators.sh` with no file arguments, retaining the existing
  behavior for that condition.
- Not silently succeed. The operator should know no files were passed.

**R5 — Explicit paths unchanged.**
Explicit positional paths continue to work exactly as before. The auto-detection
logic must not engage when any explicit path is provided.

**R6 — Mutual exclusion.**
Passing both `--since-tag` and `--since-main` must produce an error and exit non-zero
before any validation runs.

**R7 — Source logged.**
The script must log which mode resolved the file list (explicit / since-tag / since-main)
and the exact git command used, using the existing `info()` logging style, consistent
with how tier source is already logged.

**R8 -- Help text updated.**
`--help` output must document all three modes, the default behavior when no args are
given, and the fallback from `--since-tag` when no tags exist.

**R9 — Syntax check.**
`bash -n scripts/run_review_chain.sh` must pass after the change.

---

## 5. Non-Requirements

- This spec does not change how `run_validators.sh` handles its file list.
- This spec does not introduce a new config file or environment variable for the default
  mode. The default is `--since-tag` and is not configurable without code change.
- This spec does not change the idempotency sentinel behavior.

---

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | `./scripts/run_review_chain.sh --tier MEDIUM` with no file args runs without the "no files specified" error |
| AC-2 | The computed tier reflects the actual diff, not a CRITICAL fallback |
| AC-3 | `--since-tag` runs `git diff <last-tag>..HEAD --name-only` when a tag exists |
| AC-4 | `--since-tag` falls back to `HEAD~1..HEAD` and logs a warning when no tag exists |
| AC-5 | `--since-main` runs `git diff origin/main..HEAD --name-only` |
| AC-6 | `--since-main` with no remote configured exits non-zero with a clear message |
| AC-7 | Passing both `--since-tag` and `--since-main` exits non-zero with a clear message |
| AC-8 | Explicit positional file paths are passed through unchanged |
| AC-9 | An empty diff logs a warning and does not silently succeed |
| AC-10 | `--help` documents all three modes and the default |
| AC-11 | `bash -n scripts/run_review_chain.sh` passes |

---

## 7. Open Questions for Architect

**OQ-1 — Git command placement.**
Should the auto-detect run at parse time (before tier resolution) or after tier resolution?
The file list affects validator output, which affects tier. Running before tier resolution
is semantically correct but requires the architect to verify no ordering dependency exists
with `SUMMARY_JSON`.

**OQ-2 — Filtered file types.**
The issue is silent on whether the auto-detected file list should be filtered (e.g., only
`.py`, `.sh`, `.js`) before being passed to validators, or passed raw. Validators may
handle non-applicable files gracefully, but this should be confirmed. If filtering is
needed, the filter definition belongs in technical-design, not this spec.

**OQ-3 — Detached HEAD.**
`git diff origin/main..HEAD` and `git describe` may behave unexpectedly in a detached-HEAD
state (e.g., CI checkout). The architect should specify the behavior in that case.
