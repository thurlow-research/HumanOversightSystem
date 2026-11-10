# Prompt Artifact — readopt.py (#2291 prune-attempts batched-branch guard)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/readopt.py` (`prune_attempts` `base`/`issue_states` params, new `_closed_issue_deletable`), `tests/automation/test_readopt.py` |
| **Description** | `prune-attempts --issue-closed` keeps, with a WARN naming the issue, any attempt whose `origin/main..tip` commit messages reference another issue that is not verified closed (open, unknown, lookup failure, or git error), reusing the `reap-orphans` A2/D2 helpers (#2291, TD-2286 §10 follow-up) |
| **Date** | 2026-11-10 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (verbatim
except for whitespace):

```
You are implementing GitHub issue #2291 in the HOS repo, on the already-checked-out branch
worker-2291-prune-batch-open-guard-261109232001-1172619. Do NOT create, switch or stash
branches. Do NOT edit .claude/agents/worker.md (the orchestrator has already edited it).
Do not file issues, post comments or change labels.

Problem: scripts/automation/readopt.py prune_attempts(..., issue_closed=True) deletes every
local worker-<N>-* attempt once issue N is verified closed. But worker branches are named
after the first issue only: a batched branch can also carry unlanded work for another,
still-open issue M. reap_orphans already guards this (rule D2 in _decide_rest): it deletes
on a closed issue only when EVERY #ref in the branch's commit messages (origin/main..tip,
via _commit_issue_refs) is closed; otherwise KEEP issue-closed-batch-open; git failure on
the scan -> KEEP git-error.

Required change (reuse existing helpers; do not reimplement). In prune_attempts, when
issue_closed is True, before deleting each attempt:
1. Compute refs with _commit_issue_refs(git, base, tip), base a new keyword param
   base: str = "origin/main".
2. None (git error) -> keep, print a WARN naming the branch.
3. Other refs = refs minus {issue}. If non-empty, look up their states with a new
   injectable issue_states: Optional[IssueStatesLookup] = None; default
   _github_issue_states(slug or _slug_from_origin(git)). ONE batched lookup for the union,
   lazily (no lookup when no attempt has other refs). Lookup raising -> keep every attempt
   with other refs, WARN naming branch and reason (via _one_line).
4. Any other ref not exactly "closed" (open, or missing = unknown) -> keep, WARN naming the
   branch and each such #M with its state.
5. Kept attempts are not deleted locally nor remotely (no remote.step), not returned;
   dry-run applies the same check.
6. Update the prune_attempts docstring. Non-issue_closed mode unchanged.
7. CLI needs no new flag.

Tests (tests/automation/test_readopt.py): closed N, attempt references open M -> kept,
WARN names #M, sibling with no other refs still deleted; M closed -> deleted; lookup
raising -> kept with WARN; M unknown -> kept; dry-run -> no WOULD-DELETE for it; no-#ref
case makes no issue_states call; git-error from the commit scan -> kept. Existing tests
must pass.

Process: run the readopt tests and run_tests_inner_loop.sh; self-flag per AGENTS.md;
commit only readopt.py and test_readopt.py with trailers; no closing keywords.
```

### Refinement iterations

1. Lint gate (black) failed on three long lines; the coder was asked to black-format and
   rename `_closed_issue_survivors` to `_closed_issue_deletable` (it returns the deletable
   set). Commit `fcbca8801`.
2. The `unit-test` agent added four tests (batched single lookup over the union with mixed
   outcomes, self-reference only, kept attempt never reaches the remote step, CLI
   plumbing). Commit `59fde6bfc`.

### Trailer note

Commits `e472c57c0`, `6217c2ec4`, `fcbca8801` and `59fde6bfc` carry
`Prompt-Artifact: none (LOW risk)` because the worker's coder brief specified that block
before the tier was validated MEDIUM. This artifact is the record for the whole change;
the commit that adds it names it in its `Prompt-Artifact` trailer.
