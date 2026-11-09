# Prompt Artifact — readopt.py (#2293 reap-orphans recovery archive refs)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/readopt.py` (archive-before-delete for rule D2, `--list-archives`), `tests/automation/test_readopt.py` |
| **Description** | `reap-orphans` writes a durable recovery ref `refs/archive/reap/<branch>@<tip-short>` (local, and pushed to origin for remote heads) before deleting any unlanded branch; fail closed (`KEEP archive-failed`) when the ref cannot be written; `--list-archives` lists archives with age, and never prunes them (#2293, PR #2292 follow-up) |
| **Date** | 2026-11-09 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief:

```
Issue #2293 (bug fix to the #2286 reap-orphans engine; no separate design doc — the issue
body is the spec). Branch: worker-2293-reap-archive-refs-261109190501-2583567 (already
checked out; do NOT create/switch branches, do NOT git stash/checkout other refs).

Files you may edit: scripts/automation/readopt.py, tests/automation/test_readopt.py ONLY.
(.claude/agents/worker.md is edited by the worker itself — do not touch it.)

Context: readopt.reap_orphans() (scripts/automation/readopt.py ~L935-1330) builds
_Decision objects and then deletes in phase C. Of the reap reasons, exactly one deletes a
tip that is neither on origin/main nor contained in a PR's head (refs/pull/N/head): rule
D2, reason "issue-closed" (_decide_rest). pr-merged / pr-closed / review-pr-done /
review-stale are covered by a PR head (_covers); landed-ancestor / landed-content are on
main. Once a never-pushed branch is deleted, git gc can prune its tip, so the deletion is
effectively irreversible.

Required:
1. Define the set of reap reasons that need an archive as a module constant
   (ARCHIVE_REASONS = frozenset({"issue-closed"})) with a comment stating the rule:
   "any reap reason whose tip is not on base and not contained in a PR head". Decide by
   reason, so a future unlanded rule is added there explicitly.
2. Archive ref name: refs/archive/reap/<branch>@<tip[:12]>. It lives outside refs/heads, so
   for-each-ref refs/heads/... selectors never see it. Validate it with
   `git check-ref-format` (branch names already pass _SAFE_NAME_RE); an invalid name is
   an archive failure.
3. LOCAL deletion of an ARCHIVE_REASONS decision: before _delete_branch, create the ref
   with compare-and-create semantics: `git update-ref <archive> <tip> ""`, where the empty
   old-value means "must not already exist". If it already exists AND points at the same
   tip, treat that as success (idempotent re-run). If it exists at a different sha, or
   update-ref fails, or a read-back `git rev-parse <archive>` != tip: print
   _fmt("KEEP", d, reason="archive-failed") (or an equivalent line containing
   "kept reason=archive-failed" — match the issue's log wording; keep output format
   consistent with the existing REAPED/REAP-FAILED lines), count it in kept (not failed),
   and do NOT delete. On success, the REAPED line gains an appended field
   archive=<archive-ref>.
4. REMOTE deletion of an ARCHIVE_REASONS decision (ref.where == "remote"): before the
   batched remote_delete, push the archive ref to origin:
   `<tip>:refs/archive/reap/<branch>@<tip[:12]>`, through the same token-env remote runner
   _push_delete uses (never put the token in argv/URL; reuse make_git_remote/_remote_ops
   plumbing and _redact). Add an injectable `remote_archive` callable parameter to
   reap_orphans (same style as remote_delete: [(branch, sha)] -> {branch: True|False|
   PUSH_TIMEOUT}) so tests do not hit the network. Only refs whose archive push returned
   True stay in the delete batch; the others print KEEP ... reason=archive-failed (a
   timeout is also archive-failed, fail closed). Also write the local archive ref for a
   remote D2 decision when the tip commit is present locally (it is: phase A keeps
   remote-tip-not-local), so recovery works from this clone too. A remote archive push
   that returns True is enough to proceed even if the local write fails? NO: require the
   remote push; the local write for remote refs is best-effort WARN only.
5. Dry run: WOULD-REAP lines for ARCHIVE_REASONS decisions gain archive=<ref> (the name
   that WOULD be written). Write nothing in dry run.
6. --max-deletions budget: an archive-failed decision does not consume budget (it was
   never attempted as a delete) — decide and keep it consistent; document in a comment.
7. New CLI mode `reap-orphans --list-archives [--archive-age-days N]` (default 90): lists
   local refs/archive/reap/* with one line each:
   `ARCHIVE ref=<ref> tip=<sha> age_days=<n> [older-than=<N>d]` using the tip committer
   date via for-each-ref %(committerdate:unix) — note in a comment that git has no ref
   creation time, so age is the tip commit's age (same accepted limitation as the
   remote-head grace). Then `ARCHIVES total=<n> older=<m> threshold_days=<N>`. Exit 0.
   It NEVER deletes anything and performs no GitHub/network call; it is mutually
   exclusive with the deletion flags (argparse error if combined with --dry-run is NOT
   needed — just ignore other flags; simplest: run list mode and return). Pruning
   archives is a separate human-authorized step: say so in the help text.
8. Docstring: update the module docstring Usage + Safety sections: archive-before-delete
   rule, archive-failed fail-closed, --list-archives, and the RESTORE PATH:
   `git branch <name> refs/archive/reap/<name>@<tip12>` (from origin first:
   `git fetch origin refs/archive/reap/<name>@<tip12>:refs/archive/reap/<name>@<tip12>`).
   Also note: on the remote side, closed-PR and merged heads are deleted without an
   archive because a closed PR's commits remain in refs/pull/N/head.
9. SUMMARY line: APPEND (never reorder) a field archived=<n> counting archive refs
   successfully written (remote pushes + local writes for local refs).

Tests (tests/automation/test_readopt.py; follow the existing reap_orphans test helpers —
the _run helper ~L850, _FakeRemote ~L1177; real temp git repos under tmp_path, no
network):
 a. a local D2 deletion leaves refs/archive/reap/<branch>@<tip12> pointing at the old tip,
    and REAPED line carries archive=;
 b. an archive-write failure blocks the local deletion (e.g. pre-create the archive ref at
    a different sha, and separately a failing-git injection on update-ref of refs/archive)
    -> branch still exists, line has archive-failed, SUMMARY kept counts it;
 c. idempotent: archive already at the same tip -> deletion proceeds;
 d. remote D2: remote_archive called before remote_delete with the right pairs; archive
    False or PUSH_TIMEOUT -> that ref is not in the delete batch and is KEEP archive-failed;
 e. non-archive reasons (pr-merged, landed-ancestor, pr-closed) write no archive ref;
 f. selectors ignore refs/archive/**: after a D2 reap, a second reap_orphans run and
    prune_attempts' for-each-ref refs/heads/worker-<N>-* see nothing for the branch, and
    scripts.framework.select_work_candidates' local-branch listing does not either if it
    is cheap to call its branch-listing helper directly (grep for how it lists
    worker-* branches; if it uses refs/heads, assert on that helper; skip if not
    callable in isolation and say so);
 g. restore: `git branch <name> <archive>` recreates the branch at the old tip;
 h. dry run writes no archive ref and prints archive=;
 i. --list-archives: lists refs, flags older-than threshold, deletes nothing, makes no
    GitHub call (assert github.gh_call_count unchanged or pulls not called).

Run: scripts/oversight/.venv/bin/python -m pytest tests/automation/test_readopt.py -q
then the full inner loop: bash scripts/framework/run_tests_inner_loop.sh
Commit with explicit paths (git add scripts/automation/readopt.py
tests/automation/test_readopt.py prompts/scripts/automation/readopt.v2293.md) — never
git add -A. Commit message: "fix(2293): reap-orphans writes refs/archive/reap/* before
deleting unlanded work; --list-archives (Part of #2293)" with trailers as ONE contiguous
block at the end:
Prompt-Artifact: prompts/scripts/automation/readopt.v2293.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

Self-flag per AGENTS.md (RISK/CONFIDENCE/BLAST RADIUS) in your final report, plus the
test counts and the commit SHA.
```

## Scope note

`prune-attempts` can also delete unlanded duplicate attempts. It is out of this slice
(issue title scopes reap-orphans; #2286 slice 2's cron wiring runs reap-orphans), and is
recorded as a follow-up in the PR.
