# Prompt Artifact — review_worktree.sh

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/review_worktree.sh`, `tests/automation/test_review_worktree.py` |
| **Description** | Sanctioned way for the overseer to get a PR head locally without creating a branch: fetch `refs/pull/<N>/head` to FETCH_HEAD only, pin to `--expect-sha`, detached worktree under `$TMPDIR`, commit-guarded cleanup (#2287, slice 2 of #2285) |
| **Date** | 2026-11-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surface `bootstrap/**`) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (script scope):

```
Implement the approved technical design
docs/v0.7.0/TECHNICAL-DESIGN-2287-overseer-branch-hygiene.md (Status APPROVED, architect review
round 1; the round-1 resolutions are binding) on the current branch. Do NOT switch branches,
stash, checkout, reset or rebase.

Scope: bootstrap/review_worktree.sh (new) per the TD, including A3 (cleanup refuses moved HEAD,
KEPT-WORKTREE line), A4 (--refmap= and --no-recurse-submodules), A5 (main worktree via
--git-common-dir), A6 (exit 5 for scratch inside the repo or /tmp/claude). Follow
bootstrap/setup_clis.sh conventions (colours, idempotency). Worktrees under $TMPDIR.
Tests: tests/automation/test_review_worktree.py, the TD's C1-C10. Tests must clean up their own
temp. Commit with "Part of #2287".
```

Reference: TD-2287 section 2 (contract for `--pr`, `--cleanup`, `--cleanup-all`) and section 8 (C1-C10).
