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

The worker (top-level session) dispatched the `coder` subagent with this brief, verbatim except that the clone's absolute path is redacted to `<worker-clone>` for the portability gate:

~~~~
Implement **#2357 slice S1c** exactly as specified in `docs/v0.7.0/TD-2357-S1c-route-head-carry.md` (architect-approved; amendments AC1–AC13 in §12 are binding and override earlier sections where they differ). Work in <worker-clone> on the already-checked-out branch `worker-2357-overseer-second-review-s1c-261128043501-1494542` (head 3b6649c9c).

**Your files (TD §2):** 1 `scripts/automation/merge_authority_cli.py`, 2 `scripts/automation/lib/merge_authority.py`, 3 `scripts/automation/lib/overseer_second_review.py`, 4 `scripts/automation/pr_review_cli.py`, 5 `tests/automation/test_merge_authority_cli.py`, 6 `tests/automation/test_pr_review_resolution.py`, 8 `bootstrap/overseer-cron-prompt.md` (§4.6 text verbatim), 11 new `prompts/scripts/automation/merge_authority_cli.v2357.md` (prompt artifact: record the prompt/intent for this slice, following the style of existing `prompts/scripts/automation/lib/overseer_second_review.v2357.md`). Do **not** touch `.claude/agents/*`, either TD, or the ADR — the worker session owns those. Touch no other file. Do not change any module docstring's first line.

**Rules:**
- No git stash / checkout / reset / rebase. For old copies use `git show <rev>:<path> > /tmp/claude/...`. Throwaway temp under a `mktemp -d` dir.
- Use the oversight venv for Python tooling: `scripts/oversight/.venv/bin/python`.
- Commit in the TD §2 order (≤6 commits). Every commit message ends with exactly this contiguous trailer block (no blank line inside):
```
Prompt-Artifact: prompts/scripts/automation/merge_authority_cli.v2357.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow
```
- Run `bash scripts/oversight/run_gates.sh` on the changed files (black/lint etc.) and fix what it flags. Run the targeted tests (`tests/automation/test_merge_authority_cli.py`, `tests/automation/test_pr_review_resolution.py`, and the ones that must pass unchanged: `test_merge_authority_wrapper.py`, `test_route_pr.py`, `test_overseer_merge_cli.py`, overseer_second_review tests), then `bash scripts/framework/run_tests_inner_loop.sh` and `bash scripts/framework/regen_all.sh --check`. All must be green.
- If the TD is ambiguous or wrong against the code, stop and report the specific question rather than improvising.

Report: commits (SHA + subject), files changed, test counts, gate results, and any deviation from the TD with reason (deviations need architect ratification).
~~~~

## Follow-up briefs

- **T-DOC-01, overseer.md half.** After the worker session landed the `overseer.md` prose (7405d67d0), the coder was asked to add the overseer.md half of T-DOC-01 to `tests/automation/test_merge_authority_cli.py`, asserting the new TD section 4.1/4.3/4.4/4.5/4.7/4.8/4.9 text is present and the interim `review_worktree.sh --expect-sha <OSR head>` pre-route steps are gone (`test_s1c_doc_02_overseer_prose_matches_s1c`).
- **Architect-required fixes D2 and D3.** D3: `marker_record` reads `rec.get("tier")` and `rec.get("base_sha")`, keeping the `base is not None` guard, because `load_record` does not guarantee either key; one test covers a tiered record with no `base_sha` key. D2: this artifact carries the exact brief above and the corrected authorship line.

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
- **Authorship.** The doc tests `test_s1c_doc_01` and `test_s1c_doc_02` were written by the coder. Only the `overseer.md` prose and the S1b TD section 6 edits were written by the top-level worker session (#1347); the ADR correction note is the architect's.
