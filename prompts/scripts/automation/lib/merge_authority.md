# Prompt Artifact — merge_authority.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/merge_authority.py` (also `scripts/automation/lib/github.py`, `tests/automation/test_required_checks_gate.py`, `tests/automation/test_github.py`) |
| **Description** | Step-4c required-checks gate: read rulesets + classic protection, degrade on 403 (#1731, #1588) |
| **Date** | 2026-10-06 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (diff_size tier floor: 457 changed lines > 400; composite MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` subagent (abridged
only where it repeated standard constraints: no branch ops, no commit, no
issues/comments/labels, nothing under `.claude/agents/`).

```
## Problem (issues #1731 + #1588)

check_required_content_checks() in scripts/automation/lib/merge_authority.py
is the overseer's step-4c gate: if a PR's required, worker-fixable CI check
is red, bounce the PR to the worker instead of escalating to needs-human.
It is dead in this repo, for two reasons:

1. It reads required contexts only from classic branch protection. The
   overseer App gets HTTP 403 on that endpoint; _run_gh maps any 403 to
   RateLimitError (a GitHubError subclass) and the function doesn't catch
   it, so it crashes (#1588).
2. This repo's required checks come from repository rulesets
   (GET /repos/{o}/{r}/rules/branches/{branch}, rules with
   type == "required_status_checks" carry
   parameters.required_status_checks[].context). Step 2a (#1971/#1987)
   already reads the union of rulesets + classic for this reason.

## Required changes

A. github.py: add get_ruleset_required_checks(owner, repo, branch) -> list[str]
   (paginated, 404 -> [], dedupe preserving order, GitHubError propagates).
B. check_required_content_checks: read BOTH sources, each in its own
   try/except GitHubError (mirror detect_server_side_gate()); required set =
   union (classic first, dedupe); if BOTH reads raised, return
   bounce_required=False with a diagnostic summary and logger.warning (fail
   open on this gate only — the protected-surface/CODEOWNERS gates that run
   next still fail closed). Latest run per name = highest id, not list
   position; a run with a missing id loses. Update the docstring; fix the
   stale bounce_count() docstring (4b retired; 4a and 4c share the counter).
C. Tests: patch get_ruleset_required_checks in every gate test; add the
   classic-403-plus-rulesets bounce case, classic-error-empty-rulesets,
   both-fail, union dedupe, meta checks via rulesets only, latest-by-id both
   orders; helper tests for 404, mixed rule types, dedupe, pagination.
```

## Constraints Specified

- Python, existing `scripts/automation/lib` module conventions; all GitHub I/O through `_run_gh`.
- Must NOT remove or weaken any human-approval gate: step 4c may only add a bounce opportunity.
- Fail open on this gate only when no required-check source is usable; all downstream gates unchanged.
- Must NOT edit `.claude/agents/**` (protected surface; agent-definition edits are not the coder's).
- No network in tests: every test patches both config reads and the check-run read.

## Refinement History

v1 (dea2381c8): initial implementation per the prompt above.
v2 (6fe2ab04e): code review round 1. MUST_FIX: a non-list ruleset payload raised AttributeError past `except GitHubError`, so the shape is now validated and raises GitHubError. Also: `get_branch_protection(retries=...)` kwarg, with the gate passing `retries=0` to avoid ~7s of backoff on the permanent 403; real sleep removed from a test; two vacuous no-bounce tests fixed.
v3 (cb6d7effb): reliability review. A ruleset failure with no classic contexts is now treated like both-failed (warning + summary) instead of a silent "nothing required". Contexts must be non-empty str. Pagination is capped at 10 pages. Classic extraction, check-run entries and ids are type-guarded.
vFinal (9dd88876c): reliability re-review MUST_FIX. A non-dict `parameters` value raised AttributeError; it is now guarded.

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
3. Compare key logic paths against `scripts/automation/lib/merge_authority.py`
4. Note any drift in a new version artifact (`merge_authority.v3.md`)
