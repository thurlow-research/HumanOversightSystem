# Prompt Artifact — bin/hos-cron (#2287 overseer branch hygiene wiring)

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (overseer `reap-orphans` block, cycle-end review-worktree sweep), `tests/automation/test_hos_cron.py` (`TestOverseerBranchHygiene`, H1-H6) |
| **Description** | Daily, dry-run-by-default, local-only overseer branch reap and a fail-open cycle-end sweep of stale review worktrees (#2287, slice 2 of #2285) |
| **Date** | 2026-11-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surface `bin/hos-cron`) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (wiring scope):

```
Implement the approved technical design
docs/v0.7.0/TECHNICAL-DESIGN-2287-overseer-branch-hygiene.md (Status APPROVED, architect review
round 1; the round-1 resolutions are binding) on the current branch. Do NOT switch branches,
stash, checkout, reset or rebase.

Scope: bin/hos-cron - overseer-cycle reap wiring (daily cadence, 300 s bound, --local-only,
--max-deletions 100, default dry-run mode gated by a config value that a human sets to on,
audit lines incl. after timeout per A10) and the cycle-end worktree cleanup safety net that runs
even when the Claude run fails. Tests: tests/automation/test_hos_cron.py, the TD's H1-H6.
Tests must clean up their own temp. Commit with "Part of #2287".
```

Reference: TD-2287 section 6 (6.1 placement, 6.2 mode/cadence/bound/output, 6.3 safety net) and
section 8 (H1-H6); architect findings A2, A10, A14.
