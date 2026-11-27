# Prompt Artifact — select_work_candidates.py (v2403)

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/select_work_candidates.py`, `tests/framework/test_select_work_candidates_native.py` |
| **Description** | #2403 (#2377 follow-up): carry the sanitised, truncated gh/GraphQL failure reason into the `WARN unevaluated:query-failed ... check=closed-blocker` line, and emit an aggregate WARN when every evaluated candidate fails the closed-blocker check. Verdict semantics unchanged. |
| **Date** | 2026-11-20 |
| **Model** | claude-opus-5-5 (orchestrating worker and `coder` subagent) |
| **Risk level** | MEDIUM (classifier tier floor for `.py`; selector is the sole work-candidate authority) |
| **Human review status** | ⬜ Pending |
| **Redaction** | 2026-11-27 re-adoption: the brief's absolute clone path is replaced with `<Worker clone root>` (portability gate). Nothing else in the brief was changed. The effective tier on re-adoption is HIGH (the `diff_size` floor, 423 changed lines), not the MEDIUM stated above. |

---

## Prompt

Worker → `coder` subagent brief:

```
Implement GitHub issue #2403 in the HOS repo (cwd <Worker clone root>,
branch worker-2403-selector-query-failed-reason-261120122001-500945, already checked out — do NOT
switch branches, stash, or checkout other refs).

## Problem
scripts/framework/select_work_candidates.py: `_fetch_closer_node` (~line 796) returns None on any
failure of the closer GraphQL call and DISCARDS the reason — `_GhFailure` text from
`_run_graphql` (non-zero gh exit stderr, timeout/OSError, non-JSON), or a non-empty GraphQL
`errors` array in the payload. The only output is then
`WARN unevaluated:query-failed issue=#X check=closed-blocker` (~line 1239), which names the check
but not why. #2377 (an unbalanced brace in _CLOSER_QUERY → every call "Expected NAME, actual:
(none)") went undiagnosed for a day because of this.

## Required
1. Carry the FIRST failure reason for each failed closed-blocker lookup through to the
   query-failed WARN line, e.g.
     WARN unevaluated:query-failed issue=#123 check=closed-blocker reason="gh: Expected NAME, actual: (none)"
   - Sources: _GhFailure message (prefix "gh: "), GraphQL `errors` (prefix "graphql: ", use the
     first error's `message` if it is a string, else a fixed placeholder), and the shape failures
     (fixed short text such as "shape: unexpected response", never raw payload).
   - Sanitise: strip ANSI/CSI escape sequences entirely, then collapse remaining control chars
     (reuse/extend `_CONTROL_CHARS_RE`) to a space; replace `"` and `\` so the quoted field
     cannot be closed early or fabricate extra key=value fields; redact anything that looks like
     a GitHub token (gh[pousr]_[A-Za-z0-9_]+, github_pat_[A-Za-z0-9_]+) → "[REDACTED]"; cap at a
     named constant (~160 chars) with an ellipsis marker when truncated. Never include the
     request argv or the query text. CWE-117: the text is external (GitHub/gh).
   - Plumbing is your call but keep it minimal and local: e.g. record the reason in a mapping
     owned by the walk (keyed so it reaches the candidate that the failed blocker belongs to),
     without changing `blocker_closure_satisfied`'s public contract or return values. The
     cached per-blocker FAILED verdict path (a second candidate sharing a failed blocker) must
     still get the reason if one was recorded. Only the first reason per candidate is kept.
   - A candidate in query_failed_issues WITHOUT check=closed-blocker keeps its current line.
2. Aggregate signal: when the closed-blocker check failed for EVERY evaluated candidate that
   reached it (and at least one did — define "every" precisely in a comment, mirroring the
   existing `edge-summary-unreadable-on-every-record` WARN ~line 1245), emit one line:
     WARN closed-blocker-query-failed-on-every-record n=<k> reason="<first sanitised reason>" — ...
   with a short prose tail stating selection cannot determine closed-blocker satisfaction
   (DEGRADED, not "no work"). Make the token a named constant like UNEVALUATED_EDGE_SUMMARY.
   Check how bin/hos-cron / needs-attention triggers parse selector WARN lines (grep bin/,
   scripts/automation/) and report whether the new line is picked up; do NOT modify bin/hos-cron
   in this change — just tell me what you found.
3. NO change to verdict semantics or exit codes: a failed lookup stays UNKNOWN → FAILED → exit 3.
   Existing tests must pass unchanged (except where they assert the exact WARN line text — update
   those minimally and tell me which).

## Tests (tests/framework/test_select_work_candidates_native.py — read it first, reuse its
## subprocess.run mocking at the gh boundary and its fixtures; no network, no real gh)
- gh exits non-zero with stderr containing a newline and an ANSI escape (e.g.
  "\x1b[31mExpected NAME\x1b[0m\nsecond line") → WARN line contains reason="gh: Expected NAME ..."
  with no \n, no \x1b, and is a single line.
- gh exits 0 with a payload {"errors":[{"message":"Expected NAME, actual: (none)"}]} → reason
  contains "graphql: Expected NAME".
- A reason containing `"` and a token-shaped string → quote neutralised, token redacted.
- An over-long reason is truncated to the cap.
- Every candidate's closer lookup fails → aggregate WARN emitted exactly once; exit code still 3.
- Mixed (one candidate passes the closed-blocker check, one fails) → no aggregate WARN.
- Unit tests for the sanitiser function directly.

## Constraints
- black-formatted (repo config), ruff/mypy clean. Run gates on changed files:
    bash scripts/oversight/run_gates.sh <changed files>
- Run tests with single commands redirecting to a file, e.g.
    scripts/oversight/.venv/bin/python -m pytest tests/framework/test_select_work_candidates_native.py -q > .claudetmp/t2403.log 2>&1
  then Read the log. No && chaining, no pipes.
- Commit with exactly this trailer block (one contiguous block, after a blank line):
    Prompt-Artifact: prompts/scripts/framework/select_work_candidates.v2403.md
    AI-Model: claude-opus-5-5
    AI-Risk: MEDIUM
    Supervised-by: ScottThurlow
  Subject: "feat(#2403): carry gh/GraphQL failure reason into query-failed WARN; all-failed aggregate signal".
  Do NOT put a closing keyword (closes/fixes/resolves #N) anywhere in the commit message.
  Also `git add` prompts/scripts/framework/select_work_candidates.v2403.md in that commit.
- Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final message.
```

## Iteration 2 (code-review round 1)

- M1: `_run_graphql` builds `_GhFailure` text from fixed/typed content for `TimeoutExpired` ("timed out after Ns") and `OSError` (exception type/strerror), so argv and query text never reach the reason; test with a stubbed `TimeoutExpired(argv, 30)`.
- S1: empty stderr on non-zero exit yields a fixed placeholder (exit code), not a bare `gh: `.
- NIT: sanitiser also collapses C1 controls (\x80-\x9f incl. 8-bit CSI), U+0085, U+2028, U+2029.
