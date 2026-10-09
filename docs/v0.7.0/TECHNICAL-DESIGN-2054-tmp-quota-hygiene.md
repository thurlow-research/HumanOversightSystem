# Technical Design — #2054 test runs exhaust the per-user /tmp quota

Status: **DRAFT, round 1. Waiting for architect review.** Do not hand this to the coder until the architect approves it.
Issue: #2054 (bug, blocks work). Being fixed in a human-authorized interactive Worker session on 2026-10-09.
Related: #1616 (sandbox PID namespaces break `kill -0`), #1903 (`--failure-log` in literal /tmp), #1910 (wrapper replica), #314 (decision logic belongs in Python), D41 (one invocation site).
Change class: **additive**. This adds new config, a new test plugin, a new script and two new call sites. No existing contract field is removed or renamed. The test-environment change in D4 (the TMPDIR redirect) is the one behavior change; §12 Q2 asks the architect about it.

---

## 1. Problem (restated as a contract gap)

`/tmp` on the dev host is a 1.7 GB tmpfs mounted `usrquota`, and its quota cannot be read (`repquota` needs a block device). Every same-user writer shares it: the worker cron, the overseer cron, interactive Claude sessions (each Bash call writes under /tmp), and `get_app_token.sh`. When the quota is full, every write fails with EDQUOT. Since 2026-10-06 this has broken worker cycle starts at least 12 times.

No contract currently bounds what a test run may leave in /tmp. Three gaps:

1. **Retention.** `[tool.pytest.ini_options]` sets no `tmp_path_retention_*`. pytest therefore uses its defaults, `count=3, policy=all`, which keep **every** test's `tmp_path` for the last three sessions.
2. **Leaks outside pytest's basetemp.** Tests and the subprocesses they launch create `/tmp/tmp*` entries and never remove them.
3. **No cleanup and no guardrail.** No script cleans up after killed runs, and nothing fails when the suite's footprint grows.

### 1.1 Measured consumers (2026-10-09, `/tmp/pytest-of-scott/pytest-129`, a 127 MB partial run)

| Bucket (per-test dir size) | dirs | KB (allocated) |
|---|---|---|
| < 64 KB | 1709 | 17,220 |
| 64–256 KB | 174 | 22,736 |
| 256 KB–1 MB | 38 | 23,400 |
| ≥ 1 MB | 50 | 66,788 |

- Cost by content type: 128 `.git` directories = 39.4 MB (8.2 MB of that is `.git/hooks` samples), and 344 copies of `.claude/agents` = 31.4 MB.
- The largest per-test consumers are the ~45 `test_T6_*` tests in `tests/automation/test_dimension_sweep_cli.py`, at ~1.2 MB each. Each one's `make_repo()` copies `.claude/agents` (~528 KB) and `contract/dimensions` and then `git init` + two commits (~416 KB of objects). Next are `invoke-agent-replica0` (3.6 MB, module-scoped) and `test_wrapper_runs_never_write_*` (3.6 MB) in `tests/automation/test_agent_invoke_wrapper.py`.
- So no single huge file causes the ~306 MB per full run. It comes from **thousands of small dirs, all retained because policy=`all`**, plus ~50 repo-replica fixtures at ~1.2 MB each.

### 1.2 Measured leaks at the /tmp top level (same day)

| Pattern | Count | Producer (root cause) |
|---|---|---|
| `/tmp/tmp.XXXXXXXXXX` regular files (coreutils `mktemp`) | 960 (462 non-empty) | `tests/framework/test_agent_invocation_migration.py:531-532`. The generated script runs `OUTFILE="$(mktemp)"` and `LEDGER="$(mktemp)"` and never removes either. The file contents (`verdict: … / ## opus-self — Adversarial Self-Review`) match `_run_opus_status_block_integration` exactly. That is 2 files per call × 3+ callers per run. |
| `/tmp/tmpXXXXXXXX` **empty** dirs (Python `tempfile.mkdtemp`) | 380 | Tests that call `tempfile.mkdtemp()` and then delete only the file, not the dir. Example: `tests/oversight/test_ip_check.py:124` (`_write`), `tests/oversight/test_hallucination_surface_js.py:62` (`_tmp_pkg_json`), and others in the §7 inventory. |
| `/tmp/tmpXXXXXXXX.py`, `…_migration.py`, `….md` files | 31 | `NamedTemporaryFile(delete=False)` helpers in ~15 test files (for example `tests/oversight/test_validators_integration.py:_tmpfile`) whose callers do not always unlink. |
| `/tmp/hos-inner-loop-*-deadbee-*` | 2 | `tests/automation/test_hos_cron.py:1078`. Removed in fixture teardown, so these leak only when the run is killed. They are out of scope for the reaper (§5.4). |

### 1.3 Root cause of the five run dirs (pytest's default is to keep 3)

Read from the installed pytest 9.1.1 source (`_pytest/pathlib.py`, `_pytest/tmpdir.py`):

1. Each session creates `pytest-N` as `max_existing + 1` and writes `pytest-N/.lock`, which holds its PID. It registers two exit-time callbacks: remove its own `.lock`, and `cleanup_numbered_dir(keep=3)`.
2. `cleanup_numbered_dir` runs **only at normal session exit**. It deletes dirs numbered `≤ max_existing − keep`, and only when `ensure_deletable()` returns true. That requires the dir to have **no `.lock`, or a `.lock` whose mtime is more than `LOCK_TIMEOUT = 3 days` older than the current run's dir**.
3. pytest installs no SIGTERM handler. Python's default SIGTERM action ends the process **without running atexit or exit-stack callbacks**. SIGKILL never runs them either. A run killed by `timeout` / `HOS_CRON_MAX_SECONDS`, by the Claude Bash tool's 120 s/600 s timeouts, by print-mode ending a turn ("background agent killed at 600s"), or by Ctrl-C at the wrong moment therefore:
   - (a) leaves its own `.lock` behind, which makes its dir **undeletable by pytest for 72 hours**, and
   - (b) skips its own exit-time cleanup, so older dirs that it should have reaped stay too.
4. Steady state is therefore *3 retained (policy `all`) + every run killed in the last 72 h + every run currently live*. The observed set was 125–128 at ~306 MB each, plus 129 in progress (128 MB). That is **3 kept + 1 survivor + 1 live**. The survivor is either a killed run's `.lock`-pinned dir or the dir that a killed later run failed to reap. The evidence was hand-deleted, so we cannot tell which. Both are explained by (3).
5. Concurrency among the worker cron, the overseer cron and interactive sessions never *lowers* the count. A finishing run computes `max_existing` including live, later-numbered runs, and every live run is protected by its `.lock`. Concurrency adds the "live" term.

The fix in §3 attacks each term:
- policy=`failed` makes "retained" ≈ 0 on green;
- `count=1` keeps at most the most recent failed dir;
- the reaper (§5) removes killed runs' dirs on a definitive "holder is dead" signal, instead of waiting 72 h.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `tmp_path_retention_policy = "failed"`, `tmp_path_retention_count = "1"` in `pyproject.toml`. | `failed` removes each passing test's `tmp_path` at teardown and removes the whole basetemp at session end when exit status is 0. `count=1` keeps only the newest numbered dir. |
| D2 | **Reject `policy = "none"`.** | `none` forces `keep=0`, and with `keep=0` pytest **creates no `.lock`** (`make_numbered_dir_with_cleanup`: "Only lock the current dir when keep is not 0"). With no lock, a concurrent session's exit-time cleanup sees the live dir as deletable and `rm -rf`s it mid-run. Worker, overseer and interactive runs do overlap (same user, same `pytest-of-<user>`), so `none` would trade a quota bug for a cross-run deletion bug. `count ≥ 1` is load-bearing. |
| D3 | A **liveness flock** per session. A root-conftest session fixture opens `<basetemp>/.hos-live` and holds `fcntl.flock(LOCK_EX)` until `pytest_unconfigure`. It also touches the file at each test start (heartbeat). | Kernel flocks belong to the open file description and the inode. They work across PID namespaces and bind mounts of the same tmpfs, and the kernel releases them when the holder dies, including on SIGKILL. That makes "flock acquirable ⇒ holder dead" definitive, which `kill -0` is not under the sandbox (#1616). |
| D4 | **Session TMPDIR redirect.** The same fixture sets `os.environ["TMPDIR"]` and `tempfile.tempdir` to `<basetemp>/session-tmp` for the whole session. It runs after basetemp is created, so basetemp itself stays under the real tmp root. Both are restored in `pytest_unconfigure`. | Every in-process `tempfile.*` call and every subprocess `mktemp` / `${TMPDIR:-/tmp}` lands in a **single-writer directory owned by this session**. Leaks become attributable and measurable (D6), and they cannot reach the shared /tmp top level. A green run's basetemp removal then also removes them. |
| D5 | **One reaper script**: `scripts/framework/tmp_reaper.py`. It is Python and stdlib-only. Its callers are `run_tests_inner_loop.sh` (before the suite) and `bin/hos-cron` (cycle wrap-up). It is not a scheduler. | Decision logic stays in Python (#314; `shell_logic_check.py` penalizes decision-dense shell). It sits under `scripts/framework/**` because a file-deleting tool that runs from cron should itself be a protected surface. One invocation site (D41). |
| D6 | **Mandatory guardrail inside pytest** (root `tests/conftest.py`). At `pytest_sessionfinish` (tryfirst), on a run that would otherwise pass: (G-leak) any entry left in `<basetemp>/session-tmp` fails the session; (G-budget) the allocated bytes under basetemp fail the session if they exceed **50 MiB**. | It runs on every pytest invocation (inner loop, release, `run_tests.sh`, CI, mutmut), so it is mandatory by construction. It measures a private, single-writer directory, so it is deterministic. See §6.1 for why a `/tmp` before/after delta was rejected. |
| D7 | The budget can be **lowered only** through `HOS_TEST_TMP_BUDGET_MB`. Values above 50, or non-integer values, are ignored with a warning. | Same precedent as #985 and #1718 D3. A raised budget recreates #2054. |
| D8 | Measure **allocated** bytes (`st_blocks × 512`), not apparent size. Count each inode once (hardlinks), and never follow symlinks. | tmpfs quota counts allocated pages. Thousands of tiny files cost ≥ 4 KiB each, so apparent size understates this exact failure mode by about 10×. |
| D9 | Shrink the repo-replica fixtures: a template repo per module plus `git clone --local` per test (§7.2). | Peak footprint and speed. After D1 this is secondary, but it is item 1 of the issue. |
| D10 | Ban direct temp-path creation in tests: `tempfile.mkdtemp`, `tempfile.mkstemp`, `NamedTemporaryFile(…, delete=False)`. A static test enforces it, with a justified allowlist. | This turns the §1.2 leak classes into a deterministic test failure, not just a guardrail hit. `TemporaryDirectory()` stays allowed because it cleans up on exceptions. |

---

## 3. Contract — pytest configuration (`pyproject.toml`) [S1]

Add the following to `[tool.pytest.ini_options]`:

```
tmp_path_retention_count = "1"
tmp_path_retention_policy = "failed"
```

Both values are strings, because pytest declares the count ini as a string. Do **not** set `basetemp`: a fixed basetemp is wiped at session start (`rm_rf(given_basetemp)`), which deletes a concurrent run's dir.

Resulting guarantees, which §10 T1 must test:
- **R-1.** After a green session, that session's `pytest-N` no longer exists.
- **R-2.** After any sequence of completed (not killed) sessions, at most **one** unlocked `pytest-N` remains: the most recent failed one. A green run that follows a red run does not delete the red run's dir. The green run removes its own dir first, so `max_existing` then equals the red run's number and `max_delete = N−2`. This matches "a failing run keeps at most the most recent failed one".
- **R-3.** pytest never deletes a live concurrent session's dir. The `.lock` exists because `count ≥ 1`.

---

## 4. Contract — test-suite hygiene plugin [S1]

### 4.1 Location

- Hooks are declared in the root `tests/conftest.py`. That is the only conftest pytest loads for every run of this suite, and `pytest_plugins` is not allowed in a non-rootdir conftest.
- The hooks delegate to the importable module `tests/tmp_hygiene.py`, which holds all logic. That module is loaded the same way `tests/conftest.py` loads other helpers, so the §10 subprocess tests can load the same module into a throwaway project.

### 4.2 Session fixture `_hos_tmp_hygiene` (scope=session, autouse=True)

The fixture uses the public `tmp_path_factory` fixture, not `config._tmp_path_factory`.

1. `basetemp = tmp_path_factory.getbasetemp()`. This creates `pytest-N` and its `.lock` under the *real* tmp root.
2. Open `basetemp/".hos-live"` (`O_CREAT|O_RDWR`, mode 0600). Call `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. It must succeed, because the dir is new. If it fails, emit a warning and continue: hygiene is best-effort, so never fail the suite here. Write `pid=<pid> start=<epoch>`. Keep the fd in module state.
3. Create `basetemp/"session-tmp"` with mode 0700. Save the original `TMPDIR` (present or absent) and `tempfile.tempdir`. Then set `os.environ["TMPDIR"]` and `tempfile.tempdir` to that path.
4. Record `session_tmp` and `basetemp` in module state for the finish hook.

### 4.3 `pytest_runtest_logstart` (heartbeat)

If a `.hos-live` fd is held, `os.utime` the file. Errors are swallowed.

### 4.4 `pytest_sessionfinish(session, exitstatus)` — `hookimpl(tryfirst=True)`

This hook must run **before** `_pytest.tmpdir.pytest_sessionfinish`, which deletes basetemp on green.

- If module state is empty (the fixture never ran, for example collect-only), do nothing.
- Compute `leaks` = the direct children of `session_tmp`, each with its allocated bytes (D8), minus the `LEAK_ALLOWLIST` (§4.6).
- Compute `footprint` = allocated bytes of the whole basetemp tree, plus the inode count. Collect the top 20 subpaths (depth ≤ 2 under basetemp) by bytes for the report.
- Always print one terminal-summary section, `tmp-hygiene (#2054)`, containing:
  - `TMP_HYGIENE footprint_bytes=<n> inodes=<n> budget_bytes=<n> leaks=<n>`
  - one line per leak
  - the top-20 table, printed only when a gate trips.
- **Enforce only when `exitstatus == 0`.**
  - If `leaks > 0`, print `TMP_HYGIENE FAIL leak` and set `session.exitstatus = pytest.ExitCode.TESTS_FAILED`.
  - If `footprint > budget`, do the same with `FAIL budget`.
- On a red run, report only. The run is already failing, and its retained dir is wanted for inspection.

Note: `_pytest.tmpdir.pytest_sessionfinish` receives the *original* `exitstatus` argument, so on a gate failure it still deletes basetemp. That is accepted, because the report has already named every offending path and size. The coder must not work around it with private attributes.

### 4.5 `pytest_unconfigure`

Restore `TMPDIR` (or unset it if it was absent) and `tempfile.tempdir`, then close the `.hos-live` fd, which releases the flock. Releasing here and not at process exit matters for mutmut, which runs pytest in process repeatedly.

The short window that follows, where `.hos-live` is unlocked but pytest's `.lock` is not yet removed, is safe. The reaper's dead path still needs quiet ≥ `--min-age-hours` (§5.3).

### 4.6 Budget and allowlist

- `BUDGET_BYTES = 50 * 1024 * 1024` is a module constant.
- Env `HOS_TEST_TMP_BUDGET_MB` is honored only if it is a positive integer ≤ 50 (D7).
- `LEAK_ALLOWLIST` is a module-level tuple of `(glob, producer, tracking-issue)` and is **empty by default**. An entry is allowed **only** when the leak's producer is a protected-surface script that S1 may not edit, and only with the S3 tracking issue number. S3 must empty the list, and a test asserts that every entry names an open issue number in the text form `#NNNN`.

### 4.7 Boundaries

- The plugin never deletes anything. Deletion stays with pytest (retention) and the reaper.
- It must not change any test's `tmp_path` contents, and it adds no files under any test's `tmp_path`.
- With pytest-xdist (not installed today), each worker would run the fixture against its own basetemp. Supporting xdist is out of scope. If `PYTEST_XDIST_WORKER` is set, the plugin must skip the gates (report only) and say so.

---

## 5. Contract — `scripts/framework/tmp_reaper.py` [S2]

### 5.1 CLI

```
tmp_reaper.py [--tmp-root DIR] [--dry-run] [--measure] [--summary-only]
              [--min-age-hours H=2] [--legacy-lock-hours H=24]
              [--orphan-min-age-hours H=24] [--max-seconds S=60]
```

- **`--tmp-root`** defaults to `$TMPDIR` if it is set and non-empty, and to `/tmp` otherwise. That is the same root pytest uses (`tempfile.gettempdir()` honors TMPDIR). The root is resolved with `realpath` exactly once (macOS `/tmp → /private/tmp`). It must be an existing directory owned by root or by the current uid, else exit 3. Tests always pass `--tmp-root <tmp_path>`.
- **`--dry-run`** makes every decision exactly as a real run would and prints `WOULD-REAP` lines, but performs **no** unlink, rmdir, rename or rmtree, and acquires no lock that it then acts on.
- **`--measure`** prints only the measurement line in §5.5 and deletes nothing. The coder uses it for the acceptance evidence.
- **`--summary-only`** suppresses per-entry lines except `REAP` and `ERROR`.
- **`--max-seconds`** is a wall-clock budget. When it is exhausted the reaper stops starting new candidates, finishes the current one, and reports `truncated=1`.
- **Exit codes:**
  - `0` = completed, even if entries were skipped or individual entries hit errors;
  - `2` = usage error;
  - `3` = invalid tmp-root.
  - Callers treat **any** non-zero as a warning and never as a failure (§8).
- Stdlib only (`os`, `fcntl`, `re`, `pwd`, `getpass`, `shutil`, `uuid`, `time`, `argparse`). It runs under cron's `python3 -I` with no venv.

### 5.2 Structure (testability)

- `collect_facts(entry) -> Facts` handles all I/O: lstat, the flock probe, /proc scans and child mtimes.
- `decide(facts, now, policy) -> Decision(action, reason)` is a **pure** function with no I/O, so it can be unit-tested with synthetic facts (ownership mismatch, namespace cases, and so on).
- `act(decision)` performs the deletion.

### 5.3 Candidate class P — pytest run dirs

Candidates are the direct children of `<root>/pytest-of-<user>`, where `<user>` comes from `getpass.getuser()`, the same as pytest. Before descending, the reaper requires `pytest-of-<user>` to be a real dir (lstat, not a symlink) owned by the current uid. Otherwise it reaps nothing in class P and prints `SKIP not-owned-or-symlink`.

For each child:

| Child | Rule |
|---|---|
| name `^pytest-\d+$`, real dir, owned by uid | the decision table below |
| name `^garbage-` (pytest's own in-flight deletions) | REAP if quiet ≥ `min-age`; else SKIP fresh |
| `pytest-current` or any symlink | unlink only if dangling (`not os.path.exists`); never follow |
| anything else | SKIP unknown, untouched |

**Quiet age** = `now − max(mtime, ctime)` over the dir itself, `.hos-live` and `.lock` if present, and its **direct** children. No deep walk is done. Per-test dir creation bumps the basetemp mtime, and §4.3 bumps `.hos-live`.

**Positive-live evidence** (Linux only, used only to *keep* a dir): `.lock` contains PID p, `/proc/p` exists, and `/proc/p/cmdline` contains `pytest`. If /proc is absent or unreadable, this evidence is simply unavailable. An absent or unreadable PID is **never** evidence of death (#1616).

**Decision table for `pytest-N`, evaluated in order:**

1. If quiet < `min-age` → **SKIP fresh**. This applies always, whatever the other evidence.
2. If `.hos-live` exists:
   - Probe it with `flock(LOCK_EX|LOCK_NB)`.
   - If the probe fails with EWOULDBLOCK/EAGAIN → **SKIP live-flock**. This is definitive.
   - If the probe fails with any other error → **SKIP unknown** (fail safe).
   - If the probe succeeds → the holder is dead (kernel guarantee) → **REAP dead-flock**. The lock stays held through the rename and delete steps below.
3. If there is no `.hos-live` but `.lock` exists (a legacy or consumer run with no D3 flock):
   - positive-live evidence → **SKIP live-proc**;
   - otherwise, quiet < `legacy-lock-hours` → **SKIP legacy-lock**;
   - otherwise → **REAP legacy-stale**.
4. If neither file exists (pytest exited normally and removed its lock), the dir is a retained failed run:
   - **KEEP newest**: the highest-numbered unlocked dir is kept, to preserve pytest's `count=1` intent of inspecting the last failure;
   - every other such dir → **REAP finished**.

**Deletion procedure for class P**, applied to REAP verdicts:
1. Re-lstat the entry and confirm it is the same `st_ino` and `st_dev` as at decision time.
2. `os.rename(dir, <pytest-of-user>/garbage-<uuid4>)`. This is pytest's own convention, and the rename is atomic, so a concurrent pytest cleanup and this reaper cannot both act on it. If the rename fails with ENOENT, another cleaner won the race → SKIP raced.
3. `shutil.rmtree(garbage)`, using an error handler that records errors and continues. Use `onexc` on Python ≥ 3.12 and `onerror` below that, because the HOS floor is Python 3.10 (`hos_bootstrap.sh`). On Linux, `shutil.rmtree.avoids_symlink_attacks` is true. The reaper never follows a symlink out of the tree.
4. Release the flock last.

A pytest process never reuses an existing number (it creates `max+1`), so a dir cannot become live again between decision and rename.

### 5.4 Candidate class T — top-level orphans in `<root>`

Only **direct children** of `<root>` are considered. Each must match exactly one of:
- `^tmp[a-z0-9_]{8}$` (Python `tempfile`, no suffix);
- `^tmp[a-z0-9_]{8}[A-Za-z0-9_.-]{1,32}$` (Python with a suffix, for example `.py` or `_migration.py`);
- `^tmp\.[A-Za-z0-9]{10}$` (coreutils `mktemp`).

Each must also be **owned by uid** and **not a symlink**.

| Type | Rule |
|---|---|
| empty dir | REAP via `os.rmdir`, which is atomic and fails with ENOTEMPTY if anything appeared, so contents can never be destroyed |
| regular file | REAP via `os.unlink` |
| non-empty dir, socket, fifo, device | **SKIP** (reported). Never recursive in v1 |

Additional conditions:
- **Age.** REAP requires `now − max(mtime, ctime) ≥ orphan-min-age` (24 h). The ctime means a file that was recently linked or chmod-ed counts as fresh.
- **Open-file evidence** (Linux, positive only). If the entry is the target of any visible `/proc/*/fd/*` or `/proc/*/cwd` readlink → SKIP open. The scan runs **once** per invocation and is bounded by `--max-seconds`, and permission errors are ignored.
- **Never touched:** `pytest-of-*`, `claude-*`, `hos-*` (including the #1903 failure logs, which the host sweep owns), `node-compile-cache`, `gh-cli-cache`, `*.sock`, and anything not matching the patterns above. This is an allowlist of patterns, not a denylist. Anything that does not match is untouched by construction.
- **Large-entry warning (report only).** Any user-owned top-level entry larger than 100 MiB that the reaper does not own produces `WARN large-unowned <path> <bytes>`. Example: the 548 MB ad-hoc clone `/tmp/claude/hos1935`. That entry is under `claude/`, so the 100 MiB walk is depth-bounded and time-boxed. The reaper never deletes such entries.

### 5.5 Output (stable, greppable)

```
REAP <class> <reason> <path> <bytes>
WOULD-REAP <class> <reason> <path> <bytes>     (dry-run)
SKIP <reason> <path>
ERROR <errno-name> <path>
WARN large-unowned <path> <bytes>
TMP_REAPER root=<root> reaped=<n> freed_bytes=<n> skipped=<n> errors=<n> truncated=<0|1> user_bytes=<n> pytest_runs=<n> empty_tmp_dirs=<n> dry_run=<0|1>
```

- The last line is always printed and always comes last. `--measure` prints only that line, computing `reaped=0 freed_bytes=0`.
- `user_bytes` is the allocated bytes of every uid-owned direct child of `<root>`, walked without following symlinks and skipping unreadable subtrees. This is the acceptance metric (§9).

### 5.6 Boundaries

- The reaper never acts on an entry whose realpath parent is not `<root>` or `<root>/pytest-of-<user>`.
- It never acts on an entry not owned by the current uid.
- It never runs as root. If `os.geteuid() == 0` it exits 3, so that cron misconfiguration cannot turn it into a cross-user deleter.
- Mtime alone never leads to deletion. Every REAP needs age **and** one non-age signal:
  - dead flock;
  - a lock-free finished dir;
  - a legacy lock past 24 h with no live /proc evidence;
  - emptiness or regular-file type plus no visible open handle;
  - the `garbage-` naming, which marks a dir as already being deleted.

---

## 6. Guardrail measurement — rationale

### 6.1 Rejected: before/after delta of /tmp

`df /tmp` or `du` of user-owned /tmp entries before and after the run was rejected:
- The tmpfs is shared with concurrent same-user writers: the other cron role, interactive sessions, the Claude sandbox's own `/tmp/claude-1000`, and `gh` caches. A delta would attribute their writes to the suite, so the gate would be flaky. A flaky "mandatory" gate gets disabled.
- `repquota` cannot read a tmpfs quota.

### 6.2 Chosen: the session's private basetemp

D4 routes everything that honors TMPDIR into `<basetemp>/session-tmp`, a 0700 directory that only this session writes to. D6 measures that directory, which is deterministic.

The remaining escapes are closed separately:
- (a) Scripts with **literal** `/tmp/...` mktemp templates. S3 converts them to `${TMPDIR:-/tmp}` and adds a static test that bans new ones.
- (b) Tests that scrub `TMPDIR` from a subprocess env. These are rare, and the reaper backstops them.
- (c) Literal `/tmp` by design: the #1903 failure log, and `tests/framework/test_install_sandbox_config.py::clean_root`, which needs a charset-clean path and tears down with `rmtree`. Both are allowlisted in the static tests with their reasons.

### 6.3 The 50 MiB budget

On a green run, after D1 basetemp at session finish holds only:
- session- and module-scoped `tmp_path_factory` dirs (`invoke-agent-replica` 3.6 MB, `t528` 0.7 MB, `tripwire*`, and the `test_install_registry_data.py` install targets);
- the `.hos-live` file;
- leftovers in `session-tmp`, which must be zero.

The coder must record the measured `footprint_bytes` of a full inner-loop run in the PR. If it exceeds 25 MiB (half the budget), say so in the PR. The budget is meant to catch a regression such as a retention revert or a new repo-copy fixture, not today's normal footprint.

---

## 7. Leak inventory and fixture slimming [S1 for tests, S3 for scripts]

### 7.1 Tests: required changes

All of these change only `tests/**`, which is not a protected surface.

| File | Change |
|---|---|
| `tests/framework/test_agent_invocation_migration.py` `_run_opus_status_block_integration` | `OUTFILE` and `LEDGER` become `"$OUT_DIR/outfile.md"` and `"$OUT_DIR/ledger.jsonl"`, both under `tmp_path`. No `mktemp`. **This fixes the 960 files.** |
| `tests/oversight/test_ip_check.py`, `test_prompt_audit_risk.py`, `test_hallucination_surface_js.py`, `test_shell_logic_check.py` (every `tempfile.mkdtemp()` site) | Use the `tmp_path` fixture. Helpers take a `Path` argument. |
| every `tempfile.NamedTemporaryFile(..., delete=False)` site (`test_n1_detector.py`, `test_validators_mocked.py`, `test_rn_calculator.py`, `test_prompt_audit_risk.py`, `test_function_metrics_js.py`, `test_hallucination_surface_js.py`, `test_validators_integration.py`, `test_rn_calculator_js.py`, `test_n1_detector_js.py`, `test_complexity_metrics_js.py`, `test_static_analysis_js.py`, `test_hallucination_surface.py`, `test_function_metrics.py`, `test_shell_logic_check.py`, `test_ip_check.py`) | Write into `tmp_path`. Keep the file names and suffixes, because the validators may key on the suffix (`_migration.py`). |
| new `tests/framework/test_tmp_hygiene_static.py` | **D10.** An AST scan of `tests/**/*.py` fails on calls to `tempfile.mkdtemp`, `tempfile.mkstemp`, and `NamedTemporaryFile` with `delete=False`. It has an explicit allowlist of `(path, reason)` that starts empty. `TemporaryDirectory` is allowed. A second assertion checks that `pyproject.toml` declares exactly the D1 values. |

The coder must re-run the grep in §1.2 and the `mktemp` grep over `tests/` (embedded shell in Python strings) after the edits, and list any other site found in the PR body.

### 7.2 Fixture slimming (D9)

- `tests/automation/test_dimension_sweep_cli.py::make_repo`:
  - Build a **module-scoped template** once via `tmp_path_factory`. It contains the identical base content, the `base` commit and the `BASE` tag.
  - Each test runs `git clone -q --local <template> <tmp_path>/repo`. Objects are hardlinked inside the same tmpfs, and only immutable objects are linked, so tests that rewrite worktree files cannot corrupt the template.
  - Then re-apply `user.email`, `user.name` and `commit.gpgsign=false`, which a clone does not copy.
  - Then write `files` and commit `change`, as now.
  - Tests that need a variant base must still be able to build it from scratch through the existing function signature, which is kept.
  - Target: each `test_T6_*` dir ≤ 0.75 MiB, measured with the §4.4 report.
- `.git/hooks` samples (8.2 MB across 128 repos): every test-side `git init` / `git clone` in the files touched above passes `--template=` with an empty template dir, or `-c init.templateDir=`, so no sample hooks are copied. This is optional for other files.
- `tests/automation/test_agent_invoke_wrapper.py`:
  - `test_wrapper_runs_never_write_*` needs a fresh replica (see its docstring). Keep that, but add `"tests"`, `"*.md"` under `scripts/framework/validation-stamps`, and `"scripts-review-ledger.jsonl"` to `_REPLICA_IGNORE` **only if** the wrapper provably does not read them. If the coder cannot show that, leave the replica unchanged.
  - With D1 this dir is deleted at teardown anyway.

### 7.3 Scripts: signal-path and TMPDIR hardening [S3, protected]

These sites already remove their temp file on the normal path. They leak only when the script is killed between `mktemp` and `rm`, and/or they ignore TMPDIR (literal `/tmp/`), which escapes the D4 redirect:

| Site | Issue | Required |
|---|---|---|
| `scripts/oversight/run_validators.sh:219` (`/tmp/validator_XXXXXX`) | literal /tmp; no trap | `${TMPDIR:-/tmp}`; remove via a function-scope cleanup on RETURN plus the script's existing EXIT path |
| `scripts/oversight/gates/secret_scan.sh:146`; `security_scan.sh:74,114` | literal /tmp; `PIP_AUDIT_TMP` removal not on all paths | same |
| `scripts/framework/validate_agents.sh:296,298,356,357`; `validate_scripts.sh:206` | literal /tmp | `${TMPDIR:-/tmp}`; EXIT trap |
| `bootstrap/hos_install.sh:2030,2062,2077` (`_bf`, `_tmp`, `_human_generated`) | no trap | add to the installer's existing cleanup list/trap |
| new `tests/framework/test_tmp_template_static.py` | — | Fails on any `mktemp` in `scripts/`, `bin/`, `bootstrap/` whose template starts with a literal `/tmp/`. Allowlist: `scripts/framework/run_tests_inner_loop.sh` (#1903 by design). |

Already compliant, with no change needed: `bootstrap/*` TOKEN_FILE (EXIT trap), `bin/hos-human`, `bin/hos-cron:474` (trap), `bin/hos-cron:906` (private `$_HOS_DIR`), `bin/hos-cron:1220,1677`, `regen_all.sh:96`, `run_post_change_sweep.sh:121`, `run_release_panel.sh:235`, `validate_self.sh:337`, `vendor_invoke.sh` (per-process dir and trap), `scripts/dev/commit_onto_base.sh`, `dimension_sweep_cli.py:701` (`finally: unlink`), and the `mkstemp`-in-target-dir writers (`gen_sandbox_config.py`, `overseer_state.py`).

---

## 8. Call sites [S2, protected]

### 8.1 `scripts/framework/run_tests_inner_loop.sh`

- **Placement:** the first statement inside `_run_suite()`, **before** `regen_all.sh`. `regen_all.sh` itself calls `mktemp -d`, so space must be freed before it runs under EDQUOT.
- Run the reaper only if `"$SCRIPT_DIR/tmp_reaper.py"` exists. If it is absent, skip silently. Absence happens only in test replicas, because consumer installs ship the file (§11).
- **Invocation:** `"$PYTHON" -I "$SCRIPT_DIR/tmp_reaper.py" --summary-only`.
- **Best-effort:** a non-zero exit prints one `✘ tmp_reaper failed (rc=N) — continuing` line to stderr and never changes the script's exit code. That includes not tripping `set -e` (use the `|| …` form). Under `--failure-log` its output is teed into the log like everything else.
- The `--help` text gains one line naming the reaper.
- The runner does **not** gate on `user_bytes`. That would be non-deterministic (§6.1). The gate is D6, inside pytest.

### 8.2 `bin/hos-cron`

- **Placement:** after the final `echo "$LOG_PREFIX cycle complete (exit=…)"` line, which is the last statement of the script. That way it runs for every cycle that reached wrap-up **regardless of `_claude_exit`**. Timed-out cycles are exactly the ones that leave debris.
- Bound it with the existing `_UP_BOUND` array (`timeout`/`gtimeout --kill-after`), plus `--max-seconds 60` inside.
- **Invocation:** `python3 -I "$REPO_ROOT/scripts/framework/tmp_reaper.py" --summary-only`. Run it only if the file exists.
- Capture stdout and rc with the `|| _tr_rc=$?` pattern. Echo the output prefixed with `$LOG_PREFIX`.
- `_audit cycle-tmp-reap "rc=<rc>" "summary=<TMP_REAPER line>"` is emitted **only** when rc ≠ 0 or the summary does not contain ` reaped=0 `. This avoids one audit record per idle cycle (#1803).
- Never fatal: the cycle's exit status and the wakeup signal already written are unchanged.
- **Not added to** the early-exit paths (suspended, locked, idle gate, auth fail). The issue scopes the call to wrap-up. Worker cycles also reap at baseline through §8.1. See Q5.

### 8.3 `CLAUDE.md` — "Canonical entry points by task" table

Add one row:

> | Reclaiming per-user /tmp space (stale `pytest-of-$USER/pytest-N`, orphaned empty `tmp*` dirs / `tmp.*` files) — never touches a live run; `--dry-run`, `--measure` | `scripts/framework/tmp_reaper.py` |

Add one sentence after the table: *"The test suite enforces a 50 MiB /tmp budget and zero leaked temp entries per session (`tests/conftest.py`, #2054); a red `TMP_HYGIENE FAIL` is a real failure, not flake."*

### 8.4 Other docs

`docs/CRON-SETUP.md`: one paragraph under cycle wrap-up describing the reaper call and the `cycle-tmp-reap` audit event.

---

## 9. Acceptance procedure (coder records the evidence in the PR)

1. `python3 scripts/framework/tmp_reaper.py --measure` → record `user_bytes`, `pytest_runs` and `empty_tmp_dirs` (M0).
2. `scripts/framework/run_tests_inner_loop.sh`, then `--measure` (M1). Run the suite again, then `--measure` (M2).
3. Pass criteria:
   - `M2.user_bytes − M0.user_bytes ≤ 50 MiB`;
   - `M2.pytest_runs ≤ M0.pytest_runs` (excluding runs that were live concurrently, which the coder names);
   - `M2.empty_tmp_dirs ≤ M0.empty_tmp_dirs`;
   - both runs print `TMP_HYGIENE … leaks=0`.
4. These numbers are not a CI gate (§6.1). The deterministic gates are D6 and the static tests.

---

## 10. Tests

### S1

| ID | Test (file) | Asserts |
|---|---|---|
| T1 | `tests/framework/test_tmp_hygiene_plugin.py` | **Retention.** Generate a mini project in `tmp_path`: a conftest that loads `tests/tmp_hygiene.py` and the D1 ini values read **from the real `pyproject.toml`**. Run `python -m pytest` with `PYTEST_DEBUG_TEMPROOT=<tmp_path>/root`. (a) A green run leaves no `pytest-N`. (b) A red run leaves exactly 1. (c) Red, green, red leaves ≤ 1, and it is the newest. |
| T2 | same file | **Leak gate.** A mini test calling `tempfile.mkdtemp()` gives exit 1 and a `TMP_HYGIENE FAIL leak` line naming the path. The same test calling `subprocess.run(["mktemp"])` is also caught, which proves the redirect reaches subprocesses. |
| T3 | same file | **Budget gate.** `HOS_TEST_TMP_BUDGET_MB=1` plus a session-scoped factory dir holding 2 MiB gives exit 1 with `FAIL budget`. `HOS_TEST_TMP_BUDGET_MB=500` is ignored, with a warning and the budget kept at 50. |
| T4 | same file | **Red run.** A failing test plus a leak gives exit 1 (from the test) and the report, but no `FAIL leak` escalation. |
| T5 | same file | **flock held.** While the mini session is running (a test blocks on a sentinel file), `flock(LOCK_EX|LOCK_NB)` on `.hos-live` from the outer process fails. After exit it succeeds. |
| T6 | same file | `TMPDIR` and `tempfile.tempdir` are restored after `pytest.main()` in process. |
| T7 | `tests/framework/test_tmp_hygiene_static.py` | D10 AST ban; pyproject values; every allowlist entry has a reason. |
| T8 | (existing) full inner loop | green with `leaks=0`; footprint recorded. |

### S2 (`tests/framework/test_tmp_reaper.py`, every test with `--tmp-root <tmp_path>`; no test may touch the real /tmp)

| ID | Asserts |
|---|---|
| R1 | **A live run's dir is never touched.** A child process creates `pytest-of-<user>/pytest-5/.hos-live`, flocks it, writes a ready-file and sleeps. All mtimes are backdated 48 h with `os.utime`. The reaper (real and `--dry-run`) prints `SKIP live-flock` and the tree is byte-identical. After the holder is killed with **SIGKILL**, the next reaper run reaps it. |
| R2 | Legacy `.lock`, no `.hos-live`, quiet 3 h → `SKIP legacy-lock`. Quiet 30 h → REAP. |
| R3 | Legacy `.lock` naming the PID of a live child whose argv contains `pytest`, quiet 30 h → `SKIP live-proc` (skipped if `/proc` is absent). |
| R4 | Quiet < `min-age` beats a dead flock → `SKIP fresh`. |
| R5 | Two lock-free finished dirs → the newest is KEPT and the older is REAPED. |
| R6 | **Symlinks.** `pytest-of-<user>` is a symlink → nothing reaped in class P. `pytest-7` is a symlink to an outside dir → the outside dir is intact. A reaped dir containing a symlink to an outside file → the outside file is intact. A dangling `pytest-current` is removed; a valid one is kept. |
| R7 | `decide()` with synthetic facts: uid mismatch → SKIP; flock probe error ≠ EWOULDBLOCK → SKIP unknown; absent PID → never REAP by itself. |
| R8 | Class T: old empty `tmpabcd1234` → removed. Non-empty → SKIP. Young → SKIP. Old `tmp.AbCdEf1234` file → removed. File held open by a live child → `SKIP open` (Linux). FIFO → SKIP. Non-matching names (`tmux-1000`, `claude-1000`, `hos-inner-loop-…`, `pytest-of-x`, `tmpfoo`) → untouched. |
| R9 | `garbage-*` older than `min-age` → reaped. |
| R10 | `--dry-run` leaves the tree identical (a recursive snapshot of names, inodes and mtimes compared before and after) and prints `WOULD-REAP`. |
| R11 | Two reapers started concurrently on the same tree: both exit 0, every candidate is gone, and no traceback appears. |
| R12 | Root resolution: TMPDIR set → used; unset → `/tmp` (unit-test the resolver only). Missing root → exit 3. `geteuid()==0` (monkeypatched) → exit 3. |
| R13 | The summary line is always last and matches the §5.5 regex. `--measure` deletes nothing. |
| R14 | `--max-seconds 0` → `truncated=1`, exit 0. |
| C1 | `tests/framework/test_run_tests_inner_loop.py`: (new) with `tmp_reaper.py` copied into the replica and a stub that records its argv, the reaper runs before `regen_all.sh` with `-I … --summary-only`. A reaper exit of 1 leaves the suite's exit code unchanged. The existing tests (reaper absent) are unchanged. |
| C2 | `tests/automation/test_hos_cron.py`: with the reaper stub installed in the fake repo, it is invoked once after `cycle complete`, including when `_claude_exit=124`. Stub rc=1 → cycle exit unchanged and `cycle-tmp-reap` audited. Stub output `reaped=0` with rc=0 → no audit record. |
| C3 | `tests/framework/test_consumer_framework_files.py` (existing, extended if needed): `scripts/framework/tmp_reaper.py` is listed and exists. |

### S3

| ID | Asserts |
|---|---|
| T9 | `test_tmp_template_static.py`: no literal-`/tmp/` mktemp templates outside the allowlist. |
| T10 | Existing gate/validator tests stay green. The §4.6 `LEAK_ALLOWLIST` is empty, asserted in T7 after S3. |

---

## 11. Files and slicing

| Slice | Files | Protected? | Merge |
|---|---|---|---|
| **S1: stop the bleeding** | `pyproject.toml`; `tests/conftest.py`; new `tests/tmp_hygiene.py`; new `tests/framework/test_tmp_hygiene_plugin.py`, `tests/framework/test_tmp_hygiene_static.py`; edits to ~18 test files (§7.1); `tests/automation/test_dimension_sweep_cli.py`, `tests/automation/test_agent_invoke_wrapper.py` (§7.2) | **No.** None match `scripts/framework/protected_surfaces.txt`. | Normal overseer path. Its tier is set by the risk-assessor. |
| **S2: reaper and wiring** | new `scripts/framework/tmp_reaper.py`; new `tests/framework/test_tmp_reaper.py`; `scripts/framework/run_tests_inner_loop.sh`; `bin/hos-cron`; `scripts/framework/framework_consumer_files.txt` (ship the reaper); `CLAUDE.md`; `docs/CRON-SETUP.md`; `tests/framework/test_run_tests_inner_loop.py`; `tests/automation/test_hos_cron.py`; regenerated `SCRIPTS-INDEX.md` (via `regen_all.sh`) | **Yes:** `scripts/framework/**`, `bin/**`, `CLAUDE.md` | **Human approval required** (CODEOWNERS). |
| **S3: script hardening** | `scripts/oversight/run_validators.sh`, `scripts/oversight/gates/secret_scan.sh`, `scripts/oversight/gates/security_scan.sh`, `scripts/framework/validate_agents.sh`, `scripts/framework/validate_scripts.sh`, `bootstrap/hos_install.sh`; new `tests/framework/test_tmp_template_static.py` | **Yes:** gates, `run_validators.sh`, `scripts/framework/**`, `bootstrap/**` | **Human approval required.** It may be folded into S2 to save one human review; recommended separate so the cron-touching change stays small. |

- **Order:** S1, then S2, then S3. S1 alone removes ~95% of the bytes: green runs leave nothing and `tmp.*` stops accumulating.
- S2 depends on S1's `.hos-live` contract (§4.2).
- S2 also moves the `allocated_bytes()` walk out of `tests/tmp_hygiene.py` and into `tmp_reaper.py`, and the plugin then imports it via `load_module_from_path`. That gives one implementation (D41). Scripts never import from `tests/`.
- **One-time backlog:** after S1 merges, today's ~1371 leaked top-level entries remain until S2's reaper runs (24 h orphan age), or until a human deletes them with `--dry-run` reviewed first. Never delete them inline from an agent session.

---

## 12. Open questions

| # | For | Question | TD default |
|---|---|---|---|
| Q1 | human | Should class T reap **regular files** (`tmp.XXXXXXXXXX`, `tmpXXXXXXXX.py`) older than 24 h, or only empty dirs? Files could in principle hold a long-lived process's state in another PID namespace, where the open-file check cannot see it. | Reap files at ≥ 24 h. The source leaks are fixed in S1, so this is backstop only. |
| Q2 | architect | Accept the **session-wide TMPDIR redirect** (D4)? Its blast radius is ~3000 tests. Tests that assert literal `/tmp` paths or build a scrubbed env are expected to keep working. The coder must run the full suite and fix only *tests*, never scripts, if anything breaks. | Accept. |
| Q3 | architect | Zero-tolerance leak gate plus a temporary `LEAK_ALLOWLIST`, only for producers on protected surfaces and tied to S3. Acceptable, or should S1 wait for S3? | Allowlist with an issue reference; S3 empties it. |
| Q4 | human | Budget value 50 MiB (lower-only via env). | 50 MiB. |
| Q5 | architect | Also reap on hos-cron early-exit paths (idle gate, lock-held)? Overseer idle cycles never reach wrap-up. | No (the issue scopes it to wrap-up). Revisit if overseer-only hosts accumulate. |
| Q6 | human | Large ad-hoc trees such as `/tmp/claude/hos1935` (548 MB): out of scope for automatic deletion. The reaper only reports them (`WARN large-unowned`). Separate issue? | Report only. |
| Q7 | architect | Legacy `.lock` dirs (consumer or other-repo pytest runs without D3) are reaped after 24 h quiet, overriding pytest's own 72 h `LOCK_TIMEOUT`. | 24 h. |

---

## 13. Self-flag

RISK: HIGH. A scheduled path (`bin/hos-cron` wrap-up) gains a recursive delete under the shared tmp root. Safety rests on the §5.3/§5.4 decision tables, kernel flock semantics, and ownership and pattern allowlists. A wrong rule deletes a live run's working dir, which fails that run but cannot cross users (uid check, root refusal).
CONFIDENCE: MEDIUM-HIGH. The pytest retention and lock behavior was read from the installed 9.1.1 source. The leak producers were traced by file content. Two points are unverified: the exact cause of the fifth dir (the evidence was hand-deleted, §1.3 item 4), and whether the redirect breaks any existing test (Q2).
BLAST RADIUS: every pytest run in this repo (S1); every hos-cron cycle and inner-loop run in this repo and in consumer installs (S2); six gate and validator scripts (S3).

## Human Review Required

- S2 and S3 touch protected surfaces (`bin/**`, `scripts/framework/**`, `scripts/oversight/gates/**`, `scripts/oversight/run_validators.sh`, `bootstrap/**`, `CLAUDE.md`). Human approval is mandatory under CODEOWNERS.
- Q1 and Q4 are product and operations calls for the human. Q2, Q3, Q5 and Q7 go to the architect.

---

## Architect review

*(pending — round 1 not yet requested)*
