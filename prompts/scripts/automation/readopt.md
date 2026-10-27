# Prompt Artifact — readopt.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/readopt.py` (also `scripts/automation/lib/github.py` `get_issue` + `list_pulls` head encoding, `tests/automation/test_readopt.py`, `tests/automation/test_github.py`, the `bin/hos-cron` reap-landed hook, the `bootstrap/worker-cron-prompt.md` Step 2 bullet; `.claude/agents/worker.md` was authored by the worker session, not this prompt) |
| **Description** | Stalled-branch re-adoption tooling: D-7 review-path rule, post-merge reap, duplicate prune (#2126) |
| **Date** | 2026-10-24 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH (diff_size tier floor: 4 domains) |
| **Human review status** | ⬜ Pending |

---

## Prompt

The autonomous worker (top-level session) dispatched the `coder` subagent with this brief
(context paragraphs condensed; the Build section is as sent):

```
You are implementing issue #2126 ... branch worker-2126-readoption-protocol-... is already
checked out — stay on it. Do NOT edit .claude/agents/** (the worker session edits worker.md
itself). Do NOT git add -A — stage only your files explicitly.

Context: the worker re-adopts stalled, already-reviewed local branches onto current main via
bootstrap/create_branch.sh --from <stalled-branch>. Human rulings:
- D-7: full re-review when the merge from main touched any file in the reviewed set OR new
  (non-merge) commits were added beyond the originally reviewed head; otherwise delta.
- D-8: after the PR merges, delete the local branch and its ownership record. Duplicate or
  superseded attempts for the same issue are deleted without adoption, keeping the newest (or
  an explicitly named head). A branch whose issue is closed is deleted.
Reuse (do not duplicate): bin/hos-cron zero-commit reaper (300s grace keyed on record mtime),
bootstrap/lib/branch_ownership.sh, select_work_candidates._branch_has_unlanded_work,
scripts/automation/lib/github.py, pre_pr_stale_check.py CLI style, tests/automation fixtures.

Build
1. scripts/automation/readopt.py (python3 -m scripts.automation.readopt <subcommand>):
   - decide_review_path(reviewed_files, merge_touched_files, added_commits) -> (path, reason);
     full iff reviewed ∩ merge-touched non-empty or added_commits non-empty.
   - review-path --original-head <ref> --merged-head <ref> [--base origin/main]; prints
     REVIEW_PATH= and REASON=; exit 2 on git error (callers treat error as full).
   - reap-landed [--dry-run] [--grace-secs 300]: iterate ownership records only (never touch an
     unrecorded branch — the ~300 leftovers need a separate human-authorized cleanup). Landed iff
     tip is an ancestor of origin/main, OR a merged PR from that branch has head.sha == local
     tip. Landed -> git branch -D + remove record. API failure -> skip, WARN (never delete on
     uncertainty).
   - prune-attempts --issue <N> [--keep <branch>] [--issue-closed] [--dry-run]: --issue-closed
     deletes all worker-<N>-* attempts; else keep --keep or the newest tip, delete the rest.
     Never delete the checked-out branch. Remove records for deleted branches.
   Git runner and PR lookup injectable for tests.
2. Wire reap-landed into bin/hos-cron worker preamble after the existing reaper, fail-open,
   ROLE=worker only; audit cycle-branch-reap per reaped branch.
3. tests/automation/test_readopt.py: decision rule (touched-reviewed-file -> full; added commit
   -> full; neither -> delta); review-path on a temp repo; reap-landed after a simulated merge
   (ancestor and injected merged-PR paths) removes branch + record, keeps young-record and
   unrecorded branches, keeps on lookup failure; prune-attempts deletes duplicates and keeps
   newest, honors --keep, --issue-closed deletes all.
4. Update bootstrap/worker-cron-prompt.md Step 2 [started:branch] bullet minimally to point at
   worker.md §"Re-adopting a stalled branch" and the readopt subcommands.
5. Regenerate SCRIPTS-INDEX.md; 6. run the inner-loop suite green; 7. commit with trailers.
```

## Constraints Specified

- Stdlib + existing repo libs only; no new dependencies.
- Must NOT delete any branch lacking an ownership record, the checked-out branch, a branch whose
  record is inside the grace window, or any branch when git/API state is uncertain.
- Must NOT edit agent definition files; must NOT stage unrelated working-tree files.
- hos-cron integration is fail-open.
- Added in refinement: `--issue-closed` fails closed unless GitHub reports the issue closed;
  PR lookups are capped per run (default 20) and chosen at random; 2 consecutive lookup
  failures abort further lookups; the hos-cron step is bounded by `timeout 120`.

## Refinement History

The brief above produced v1 (d1d506e0e after `black`). Later rounds were sent to the same
coder as follow-up messages, each driven by a recorded finding (see the step register):

- 093398c19 (risk-assessor brief): server-verified `--issue-closed` via new `github.get_issue`;
  WARN when no `--keep`; `--max-lookups` cap; `timeout --kill-after=10 120` around the hook;
  review-path catches unexpected exceptions (exit 2).
- a79117bb7 (code-review suggestion): review-path tests where the original head already merged
  an older main.
- 3c0a2c1bd (security/reliability/ops advisories): circuit breaker after 2 consecutive lookup
  failures; hook processes output on both paths with `python3 -u`, WARN carries rc/timeout;
  `REAP-FAILED` → `cycle-branch-reap-failed` audit; `SUMMARY` line; `git branch -D --`;
  option-like record names skipped; `list_pulls` URL-encodes `head`.
- 564c25ce7 (worker's live dry run: newest-first ordering starved 94 of 114 records under the
  cap): two-phase reap — local checks for all records, then shuffled capped lookups (injectable
  seed); one collapsed cap WARN line.
- b3d871df0 (security CWE-117 + reliability, delta round): exception text single-lined; hook
  audits only lines matching an anchored regex; ancestry reaps run before PR lookups.
- cfde98b6a (cross-vendor second review): review-path fails closed unless the merge from base is
  done and counts base's changes since the fork (catches `--ours` resolutions); deletion is an
  atomic `update-ref -d <branch> <verified-tip>` compare-and-delete, worktree-aware; the cron
  prompt adopts via `create_branch.sh --from`, never cherry-pick.
- 7b18c4c57 (codex CWE-693): review-path recomputes the merge with `git merge-tree --write-tree`;
  conflicts or any tree difference from the independent merge mean `full`.

Pasting only the brief into a fresh session reproduces v1, not the final code; the follow-ups
above are needed as well.

## Human Review Notes

<!-- pending -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above as written
3. Compare key logic paths against `scripts/automation/readopt.py`
4. Note any drift in a new version artifact (`readopt.v1.md`)
