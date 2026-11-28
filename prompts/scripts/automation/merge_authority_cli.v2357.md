# Prompt Artifact — merge_authority_cli.py route head-carry + bounce check marker (#2357 S1c)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/merge_authority_cli.py` (M), `scripts/automation/lib/merge_authority.py` (M), `scripts/automation/lib/overseer_second_review.py` (M), `scripts/automation/pr_review_cli.py` (M), `bootstrap/overseer-cron-prompt.md` (M), `tests/automation/test_merge_authority_cli.py` (M), `tests/automation/test_pr_review_resolution.py` (M) |
| **Description** | Slice S1c of #2357: `route` carries the runner's `reviewed_head` and refuses any other head (AD-10); every CLI bounce comment ends with the `hos-overseer-check` marker, `bounced=true` when an `sr-` finding is in it (AD-4); one marker grammar, one reader (`parse_check_marker`); D-4 refuses any mention of the marker's name; carry items 1, 2, 3, 7 and 11 of the S1b review; the cron prompt's interim worktree exception removed. |
| **Date** | 2026-11-28 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (verbatim
except for whitespace):

```
Implement #2357 slice S1c exactly as specified in
docs/v0.7.0/TD-2357-S1c-route-head-carry.md, which is architect-approved and binding.
Amendments AC1-AC13 are in section 12 and override earlier sections where they differ.
Work on the already-checked-out branch, at head 3b6649c9c.

Your files, from TD section 2:
1. scripts/automation/merge_authority_cli.py
2. scripts/automation/lib/merge_authority.py
3. scripts/automation/lib/overseer_second_review.py
4. scripts/automation/pr_review_cli.py
5. tests/automation/test_merge_authority_cli.py
6. tests/automation/test_pr_review_resolution.py
8. bootstrap/overseer-cron-prompt.md: the section 4.6 text, verbatim.
11. New: prompts/scripts/automation/merge_authority_cli.v2357.md, the prompt artifact.

Do not touch .claude/agents/*, either TD, or the ADR; the worker session owns those. Touch
no other file. Do not change any module docstring's first line.

Rules: no git stash, checkout, reset or rebase. Throwaway temp in a mktemp -d dir. Use the
oversight venv for Python tooling. Commit in the TD section 2 order, as at most 6 commits,
each ending in one contiguous trailer block (Prompt-Artifact, AI-Model, AI-Risk,
Supervised-by). Run bash scripts/oversight/run_gates.sh on the changed files and fix what it
flags. Run the targeted tests (test_merge_authority_cli, test_pr_review_resolution,
test_merge_authority_wrapper, test_route_pr, test_overseer_merge_cli and the
overseer_second_review tests); they must pass unchanged. Finally run
bash scripts/framework/run_tests_inner_loop.sh and bash scripts/framework/regen_all.sh --check;
both must be green. If the TD is ambiguous or wrong against the code, stop and report the
specific question; do not improvise. Report commits, files changed, test counts, gate results
and any deviation from the TD with its reason; each deviation needs architect ratification.
```

## Intent

- **AD-10 head-carry.** The runner's findings file names the head the review covered
  (`reviewed_head`). `route` pops it before canonicalization, checks it is a 40-hex lowercase
  string before any fetch, compares it with the head it fetches itself right after the first
  `get_pull`, and refuses a mismatch with `head_moved` (transient) on every PR. The field can
  only refuse. An `sr-` finding without the field is `findings_file_invalid`.
- **AD-4 bounce marker.** `record_pr_bounce` takes `check_marker`, validated against
  `merge_authority.CHECK_MARKER_RE` for the same PR and head before any GitHub call or lock,
  and appends it as the comment's final line in both renderings and every truncation branch.
  `_write_bounce` builds it from the runner's record (`marker_record`) and fails closed with
  `check_marker_unavailable` rather than posting an unmarked bounce.
- **One grammar, one reader.** The regex lives in `merge_authority` (import direction).
  `check_marker` self-checks against it; `parse_check_marker` reads only the exact final line.
- **Carry items.** D-4 NFKC+casefold refusal (1); `check_marker` type and `fullmatch` guard (2);
  `marker_record` refuses a tiered record when the base cannot be pinned (3); test hardening
  (7, 11). Item 9 is deferred to #2431.
- **Not done here.** The `overseer.md` prose and its prose test (T-DOC-01) are authored by the
  top-level session (#1347); the TD files and ADR note are the worker's.
