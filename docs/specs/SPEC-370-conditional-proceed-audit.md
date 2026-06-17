# Requirements Spec — Issue #370: Startup Artifact Gap — CONDITIONAL_PROCEED PR Audit

**Document type:** Requirements specification
**Status:** Draft — for technical-design
**Issue:** #370
**Depends on:** `SPEC-overseer-merge-authority.md` §1 (CONDITIONAL_PROCEED threading — must ship first)
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

Before `SPEC-overseer-merge-authority.md` §1 ships, the overseer placed CONDITIONAL_PROCEED
items as prose in the PR body rather than as unresolved GitHub review threads. Branch
protection could not mechanically block merge on prose items. PRs carrying a
CONDITIONAL_PROCEED evaluator verdict could be merged without the human explicitly
actioning each conditional item.

After §1 ships, future CONDITIONAL_PROCEED PRs are mechanically enforced. But PRs merged
before that point under the prose-only mechanism cannot be retroactively re-gated. This
audit identifies those PRs and flags any where evidence of human actioning is absent, so
findings can be filed as individual issues for remediation.

---

## 2. Scope

This spec covers one new script: `scripts/oversight/audit_conditional_proceed.sh`.

The script is a one-time audit tool run manually by the human operator after
`SPEC-overseer-merge-authority.md` §1 ships. It is not part of the ongoing
inner-loop or transition pipeline. It does not modify any files, reopen PRs, or take
automated corrective action.

---

## 3. Inputs

| Input | Source | Required |
|---|---|---|
| Audit log | `audit/oversight-log.jsonl` in the repo root | Yes — exit with clear error if absent |
| GitHub API | Via `gh` CLI (authenticated) | Yes — exit with clear error if `gh auth status` fails |
| Repo | Current git repo (auto-detected from `git rev-parse --show-toplevel`) | Yes |

The script does not accept a log file path argument in v1. It always reads
`audit/oversight-log.jsonl` relative to the repo root. (Open question OQ-1 below.)

---

## 4. Processing Pipeline

The script executes these steps in order. Each step that fails for a specific PR is logged
as a WARNING for that PR; processing continues with the next PR.

### Step A — Parse CONDITIONAL_PROCEED events

Read `audit/oversight-log.jsonl` line by line. Select lines where:
- `event` field equals `CONDITIONAL_PROCEED` (case-insensitive match acceptable)
- `pr_number` field is present and non-empty

Each matching line produces one audit candidate: `{pr_number, timestamp, conditional_items}`.

If `conditional_items` is absent or empty in a matching line, note it but still include the
PR in the candidate list — the PR carried the verdict even if items were not logged.

### Step B — Check merged status

For each candidate PR, call the GitHub API (via `gh api`) to check whether the PR was
merged. A PR that was not merged (open, closed-without-merge, or not found) is excluded
from further processing and noted in the output as SKIPPED — NOT MERGED.

### Step C — Check for human actioning (heuristic)

For each merged candidate PR, determine whether a human explicitly actioned the conditional
items. This is a heuristic check, not a definitive determination.

**Heuristic definition:** A non-bot reply exists in the PR conversation on or after the
earliest timestamp of the CONDITIONAL_PROCEED event for that PR.

Non-bot is defined as: the comment author is not the overseer account (as named by
`OVERSIGHT_ACCOUNT` env variable, defaulting to `HOSOversightTutelare`) and not the
worker account (`WORKER_ACCOUNT` env variable, defaulting to `HOSWorkerTutelare`).

The heuristic may produce false negatives (human replied to something else, not the
conditional items) and false positives (human replied with a dismissal comment, not an
actioning confirmation). The output must label this column "Heuristic: human reply after
CP verdict" and include a note that manual verification is required for flagged PRs.

A PR where no qualifying non-bot comment is found after the CONDITIONAL_PROCEED event
timestamp is flagged as NEEDS_REVIEW.

A PR where at least one qualifying non-bot comment is found is flagged as LIKELY_ACTIONED.

### Step D — Output report

Write a structured report to stdout. Also write the report to
`.claudetmp/audit/conditional_proceed_audit_<ISO-8601-date>.txt` (create the directory
if it does not exist).

Report format (plain text, human-readable):

```
CONDITIONAL_PROCEED Audit Report
Generated: <ISO-8601 datetime>
Repo: <repo slug>
Log: audit/oversight-log.jsonl (<N> CONDITIONAL_PROCEED events found)

PR      Merged  Heuristic                  Conditional items logged
------  ------  -------------------------  ------------------------
#NNN    yes     NEEDS_REVIEW               <count or "not logged">
#NNN    yes     LIKELY_ACTIONED            <count>
#NNN    no      SKIPPED — NOT MERGED       —
...

Summary
  Total CONDITIONAL_PROCEED events: N
  Merged PRs examined:              N
  NEEDS_REVIEW (file as issues):    N
  LIKELY_ACTIONED (no action req):  N

NOTE: "Heuristic: human reply after CP verdict" is not a definitive determination.
Manually verify each NEEDS_REVIEW PR before filing findings as issues.
```

The report is the only output artifact. The script does not file issues itself — that is
a human action taken after reviewing the report.

---

## 5. Functional Requirements

**R1 — Prerequisite check.**
Before processing, verify: `audit/oversight-log.jsonl` exists; `gh auth status` exits 0.
On failure, print a clear message and exit non-zero. Do not partially run.

**R2 — CONDITIONAL_PROCEED log format tolerance.**
The script must handle log lines where `conditional_items` is absent, null, or an empty
array without crashing. These PRs are included with "not logged" in the items column.

**R3 — Bot account configuration.**
`OVERSIGHT_ACCOUNT` and `WORKER_ACCOUNT` environment variables override the defaults.
The script must print the resolved account names at startup so the operator can verify them.

**R4 — gh API rate limiting.**
The script must not hammer the API. Use a brief delay (configurable via `GH_API_DELAY_MS`,
default 200 ms) between per-PR API calls. On a 429 response, log a warning and skip that
PR rather than crashing.

**R5 — No writes to audit log.**
The script is read-only with respect to `audit/oversight-log.jsonl`. It must not append,
modify, or truncate that file.

**R6 — Exit code.**
Exit 0 if the script ran to completion (even if NEEDS_REVIEW PRs exist — those are
findings for the human, not script failures). Exit non-zero only on a prerequisite failure
(R1) or an unrecoverable error.

**R7 — Idempotent.**
Running the script multiple times is safe. Output file names include the date to avoid
collisions between runs on the same day; a second run on the same day overwrites the
earlier file for that date.

**R8 — bash -n check.**
`bash -n scripts/oversight/audit_conditional_proceed.sh` must pass.

---

## 6. Non-Requirements

- The script does not file GitHub issues. That is a human step.
- The script does not reopen, close, or modify any PR.
- The script does not retroactively post review threads to already-merged PRs.
- The script does not need to handle JSONL files larger than the in-memory capacity of
  a standard shell pipeline (`grep`, `jq`). Extremely large audit logs are out of scope.

---

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | Script exits with a clear error when `audit/oversight-log.jsonl` is absent |
| AC-2 | Script exits with a clear error when `gh auth status` fails |
| AC-3 | Script identifies all CONDITIONAL_PROCEED lines in the log |
| AC-4 | Merged vs. non-merged status is correctly determined via gh API |
| AC-5 | PRs with no non-bot reply after CP verdict are flagged NEEDS_REVIEW |
| AC-6 | PRs with a qualifying non-bot reply are flagged LIKELY_ACTIONED |
| AC-7 | Report is written to stdout and to `.claudetmp/audit/` |
| AC-8 | OVERSIGHT_ACCOUNT and WORKER_ACCOUNT env vars override defaults |
| AC-9 | Script does not modify `audit/oversight-log.jsonl` |
| AC-10 | Exit 0 when NEEDS_REVIEW PRs exist (they are human findings, not errors) |
| AC-11 | `bash -n` passes |

---

## 8. Sequencing Dependency

This script should not be run until `SPEC-overseer-merge-authority.md` §1 (CONDITIONAL_PROCEED
threading) is fully deployed and branch protection is enforcing resolved conversations. Running
it before that point does not produce incorrect output, but the remediation framing ("the
old gate didn't block") is only meaningful once the new gate is in place.

---

## 9. Open Questions for Architect

**OQ-1 — Log file path configurability.**
Should the script accept `--log <path>` for cases where the audit log is not at the repo
root? The issue is silent. Recommended: add `--log` as optional override with
`audit/oversight-log.jsonl` as default, but confirm with architect before implementing.

**OQ-2 — jq dependency.**
The most natural implementation uses `jq` for JSONL parsing. Confirm `jq` is available in
all environments where this script runs, or specify a fallback parsing strategy (pure
`grep`/`python3`).

**OQ-3 — Multi-event PRs.**
A single PR may have multiple CONDITIONAL_PROCEED events in the log (e.g., overseer
re-evaluated after a force-push). The heuristic timestamp anchor should be the earliest
event. Confirm this is the correct anchor or specify the most recent instead.
