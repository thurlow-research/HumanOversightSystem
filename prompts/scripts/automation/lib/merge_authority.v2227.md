# Prompt artifact — #2227 (serialize the bounce critical section)

- **Issue:** #2227 (CWE-362 found by the codex second review of #2209 S1a)
- **Source files:** `scripts/automation/lib/merge_authority.py`, `scripts/automation/merge_authority_cli.py`, `tests/automation/test_bounce_gate.py`, `tests/automation/test_bounce_lock.py`, `tests/automation/test_merge_authority_cli.py`
- **Design:** the issue's "Required" list; the #2209 S1a design `docs/v0.7.0/TECHNICAL-DESIGN-2209-s1-route-bounce.md` (§3.16 error classes) stays the contract for everything else
- **Model:** claude-opus-5-5[1m] (worker, autonomous cycle worker-hos-261106202002-3749041)
- **Date:** 2026-11-06
- **Risk tier:** HIGH (protected surface: `scripts/automation/lib/merge_authority.py`)
- **Human review status:** none yet; CODEOWNER review applies at merge.

## Prompt (as dispatched to `coder`)

Fix issue #2227. Today `record_pr_bounce` (and `repair_bounce_finalize`) in `scripts/automation/lib/merge_authority.py` run read-prior-events → dedup → id allocation → comment post → audit append with no lock, and the bounce-budget check happens earlier, in `merge_authority_cli.py` (`_bounce`: `count >= BOUNCE_CAP`; `_route`: `route_pr(epoch_bounce_count=...)`). Two concurrent callers for the same PR and head can both post a comment and both append a `pr-bounced` event, which duplicates finding ids and burns two bounces for one rejection.

Required design (stop and report if any part is impossible as stated):

1. **Lock primitive.** Add a private context manager in `merge_authority.py`, for example `_bounce_lock(owner, repo, cid, *, repo_root, timeout=BOUNCE_LOCK_TIMEOUT_SECONDS)`.
   - Use `fcntl.flock(LOCK_EX | LOCK_NB)` on a lock file, polled every ~0.1 s until `timeout` (module constant, 60 s). Do **not** use a PID-file or mkdir mutex. flock is released by the kernel when the process dies, so a crashed holder can never leave a stale lock. That matters because PID liveness checks fail across sandbox PID namespaces (#1616).
   - Lock file: `<repo_root>/.claudetmp/locks/bounce-<first 24 hex of sha256("<owner>/<repo>\0<cid>")>.lock`. Create the parent directory with mode 0o700 and the file with 0o600. The audit log the lock protects lives under `repo_root`, so the lock is scoped to the same `repo_root`, and is independent of `bin/hos-cron`'s role lock. Never delete the lock file (unlinking a flock file races).
   - On timeout, raise a new `BounceLockTimeout` exception (subclass `RuntimeError`, not `GitHubError`) before any write. Always release the lock and close the fd, including when an exception is raised.
2. **Critical section in `record_pr_bounce`.** Everything from reading prior events (`bounced_on_head`) through the audit `write_event` runs inside the lock. Inside the lock:
   - Re-read prior events, then drop any finding already bounced on this head. Use the **same identity comparison the CLI uses** in `_bounce` (`f.identity` against `{p.identity for p in prior}`) for `findings`, and keep the existing key comparison for legacy `failures`. If nothing new remains, take the existing skip/repair path, unchanged.
   - Add a keyword-only parameter `cap: Optional[int] = None`. When `cap` is given and something new remains, compute `bounce_count(cid, since=epoch_since)` inside the lock. If it is `>= cap`, post nothing, write nothing, and return a `BounceResult` with `skipped=True` and a new field `at_cap: bool = False` set to True. `cap=None` keeps today's behavior, so existing callers keep working.
   - Allocate finding ids and the bounce number, post the comment, and append the event inside the lock.
   - The label and convert-to-draft finalize steps may run after the lock is released. They are idempotent and best-effort.
3. **`repair_bounce_finalize`.** The public function takes the same lock. Split out an unlocked internal helper, and have `record_pr_bounce`'s skip path call that helper while it already holds the lock. A second flock on a fresh fd in the same process would deadlock.
4. **CLI (`merge_authority_cli.py`).** `_write_bounce` passes `cap=merge_authority.BOUNCE_CAP`. `_bounce` maps an `at_cap` result to `done(False, "at-cap", at_cap=True, ...)`. `_route` includes `at_cap` in the `bounce` payload when the lock-time cap check refused, and adds a reason saying the cap was reached under the lock. `BounceLockTimeout` (from either the write or the repair path) becomes a `_Fail` with `error_code` `bounce_lock_timeout` and `error_class` `transient`, using §3.16's existing transient exit code. Keep the CLI's pre-lock checks as a fast path. The lock is the authority.
5. **Tests** (hermetic, no network, temp only through pytest `tmp_path`; the suite enforces zero leaked temp entries):
   - Two concurrent `record_pr_bounce` calls (threads, each opening its own fd) on one PR, head and cid, with the same findings and `post_comment` mocked to be slow, produce exactly one comment post and one `pr-bounced` event. The second call returns `skipped=True`.
   - Two concurrent calls with **different** new findings at `bounce_count == cap - 1` produce one post. The other returns `at_cap=True`.
   - Lock timeout: hold the lock from the test, call with a tiny timeout, and get `BounceLockTimeout` with nothing posted or written.
   - The lock is released after an exception inside the section (for example `post_comment` raising `GitHubError`): a following call acquires it.
   - CLI: `bounce` maps `at_cap` and `bounce_lock_timeout` as above.
   - Existing tests stay green unchanged, except where they must accept the new `at_cap` field.

Rules:
- Edit only `scripts/automation/lib/merge_authority.py`, `scripts/automation/merge_authority_cli.py`, `tests/automation/test_bounce_gate.py` and `tests/automation/test_merge_authority_cli.py`, plus a new test file if that is cleaner. If you need any other file, stop and ask. Do not edit `.claude/agents/**`, the contract, or SCRIPTS-INDEX.md.
- Never run `git stash`, `git checkout` or `git reset`.
- Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS).
- Run `scripts/oversight/.venv/bin/python -m pytest tests/automation -q` and make it pass. Then run `bash scripts/framework/run_tests_inner_loop.sh` and report the result.
- Commit when green: one commit including this prompt artifact, message `fix(merge-authority): serialize the bounce critical section under a per-cid flock; enforce the cap inside it (#2227)`. End it with one contiguous trailer block, with no blank line inside it: `Prompt-Artifact: prompts/scripts/automation/lib/merge_authority.v2227.md`, `AI-Model: claude-opus-5-5[1m]`, `AI-Risk: HIGH`, `Supervised-by: ScottThurlow`, `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never write a closing keyword (closes/fixes/resolves) in the message.
- Report: the files changed, the test results, the commit SHA, your self-flag, and any deviation from this brief, with the reason.

## Refinement iterations

1. Commit 6131d3af7: `record_pr_bounce` returns `finding_keys` so the CLI keys finding ids to the findings the lock kept.
2. Code-review SHOULD_FIX-1: `_route` now reports a lock-time cap as ESCALATE / rule 6d / trigger `bounce-cap` and a lock-time all-duplicate result as NOOP / rule 6c / reason `no-new-keys`, matching the pre-lock decisions. `to_bounce` is cleared in both. NIT-1: `record_pr_bounce` docstring notes that finalize runs after the lock and is idempotent via repair. Tests added in `test_merge_authority_cli.py`.
