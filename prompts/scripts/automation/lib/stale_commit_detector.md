# Prompt Artifact — stale_commit_detector.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/stale_commit_detector.py` (also `scripts/automation/pre_pr_stale_check.py` and their tests under `tests/automation/`) |
| **Description** | #1681 fail-closed open-PR overlap check (OpenPrsUnverifiedError, exit 3) |
| **Date** | 2026-10-13 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (coder self-flag; push-gate behaviour) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` agent, after an `architect`
triage ruled APPROVED WITH CONDITIONS (the conditions are folded into the
design below).

```
Implement the fix for issue #1681 on the already-checked-out branch. Do NOT
create or switch branches, commit, push, file issues, post comments, or apply
labels. Touch ONLY:
- scripts/automation/lib/stale_commit_detector.py
- scripts/automation/pre_pr_stale_check.py
- tests/automation/test_stale_commit_detector.py
- tests/automation/test_pre_pr_stale_check.py
(Do NOT modify scripts/automation/lib/github.py, bootstrap/**, CLAUDE.md, or
.claude/agents/**.)

## Bug
pre_pr_stale_check.py is a HARD GATE (exit 0 = proceed). When the GitHub API
fails (e.g. 401 expired token), find_redundant_in_open_prs logs a warning and
returns {}, so the CLI prints "✔ ... is clean" and exits 0. Per-PR
commit-listing failures are also silently skipped. Additionally, _run_gh
(github.py:135-140) returns None on HTTP 404 and on an empty body, and the
listing loops treat None as an empty page — so a wrong repo or a token without
access also reports clean.

## Architect-approved design (implement exactly)
Library (stale_commit_detector.py):
1. Add class OpenPrsUnverifiedError(Exception) — must NOT subclass
   GitHubError. Carries a human-readable reason.
2. find_redundant_in_open_prs raises OpenPrsUnverifiedError (stop at the FIRST
   failure) when any of these occur, on the open-PR listing (any page) or any
   PR's commit listing (any page):
   - GitHubError raised (includes RateLimitError) — catch only GitHubError;
     let other exceptions propagate.
   - _run_gh returns None (404 / empty body). Only a real [] means "no more
     items".
   - response is not a list.
   - a PR entry is not a dict, or has no number.
   - a commit entry is not a dict, or has no sha (or empty sha).
   Keep a logger.warning for each failure. Keep the current-branch skip and
   pagination behaviour. Empty branch_commit_shas still returns {} without any
   API call.
3. StaleCommitResult gains open_prs_unverified: Optional[str] = None. is_clean
   returns False whenever it is set. all_redundant is unaffected.
4. check_stale_commits catches OpenPrsUnverifiedError, sets
   open_prs_unverified to its reason, keeps the warning, and calls
   log_event("pre-pr-stale-check-unverified", branch=..., base=...,
   reason=...). Keep existing pre-pr-stale-commits event semantics for real
   redundancies.
5. check_open_prs=False and "no commits ahead of base" remain clean.
6. Rewrite docstrings: remove "best-effort" / "silently skipped"; describe
   fail-closed behaviour and cite #1681.

CLI (pre_pr_stale_check.py):
7. New exit code 3 = could not verify open-PR overlap (GitHub API error) — do
   not push. Check result.open_prs_unverified right after the audit-file
   guard, BEFORE the is_clean branch and BEFORE any auto-rebase (never call
   strip_redundant_commits on an unverified result). Apply the same check to
   the post-rebase re-check -> exit 3. Messages to stderr, start with
   "✘ pre-pr-stale-check:", include the reason, say do not push / re-mint the
   token and re-run. No ✔ line on any unverified path.
8. Update the module docstring exit-code list and run_check's docstring.

## Tests
- Library: 401 GitHubError on listing, 403 RateLimitError, page-1 None,
  page-2 None, non-list listing, PR without number, non-dict PR entry,
  GitHubError on one PR's commits, None commit page, non-list commits, commit
  without sha -> each raises OpenPrsUnverifiedError, and check_stale_commits
  returns a result with open_prs_unverified set, is_clean False, and emits the
  unverified audit event.
- Existing tests asserting {} / "skips that PR" on error must be INVERTED
  deliberately; leave a short comment citing #1681.
- Genuine clean, genuine overlap, pagination, current-branch skip tests still
  pass unchanged.
- CLI: unverified first check -> 3, strip_redundant_commits NOT called, no ✔
  in stdout or stderr. Unverified post-rebase re-check -> 3, no ✔. Clean and
  overlap paths unchanged.

Run the two test files and the inner-loop suite; run the lint gate on the
touched files and fix issues. Report files changed, self-flag, test results.
```

## Constraints Specified

- Scope: four files only; `github.py`, `bootstrap/**`, `CLAUDE.md`, `.claude/agents/**` untouched (protected surfaces / shared library).
- Must NOT: suppress the existing warning; rebase on an unverified result; print a success line on any unverified path; subclass `GitHubError` for the new exception.
- Out of scope (architect ruling): minting a token inside the check; updating `bootstrap/worker-cron-prompt.md` Step 4b with an exit-3 line (protected-surface follow-up).

## Refinement History

v1: the prompt above (commit 4bed6c3d0). Approved by code-review, security,
reliability and ops with low/advisory findings only.

v2 (round-2 hardening, same four files): a follow-up prompt to `coder`
folding in the in-file advisory findings:
1. Build the unverified reason from `exc.args[0]` plus HTTP status (no tuple
   repr); collapse whitespace, strip/escape control and ANSI characters,
   truncate to ~300 chars; apply to logger, `log_event` reason and CLI stderr
   (ops advisory 1, security L2 / CWE-117).
2. A PR `number` that is not an `int` (or is a `bool`) is malformed →
   `OpenPrsUnverifiedError` before it reaches an API path (security L3 / CWE-20).
3. The post-rebase exit-3 message states the branch was already rebased
   locally and nothing was pushed; absent on the first-check path
   (reliability F2).
4. Test that a non-dict PR `head` is not treated as the current-branch PR
   (code-review SHOULD_FIX 2).
5. Define the `_unverified` helper before first use (cosmetic).
"Do not change any other behaviour." Out-of-file findings (fork-PR same-ref
skip, unbounded `Retry-After` in `github.py`, exit-3 line in the protected
worker prompt, ambient token freshness) were routed to follow-up issues.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/automation/lib/stale_commit_detector.py`
4. Note any drift in a new version artifact (`stale_commit_detector.v1.md`)
