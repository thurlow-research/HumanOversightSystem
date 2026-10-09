# Technical Design — #2054 test runs exhaust the per-user /tmp quota

Status: **Round 2 revision (2026-10-09). Applied to the body: the architect's round-1 conditions AC-1..AC-16, the human ruling of 2026-10-09, and the later human Q6 ruling that the reaper deletes stale agent scratch trees (class S, D13, §5.7)** (see "Round-2 revision note" at the end). Awaiting the architect's round-2 diff check, which is verification only. The coder gets this after the architect approves. Merging is also gated on the three open human confirmations in §12.1 (AC-16). Coding proceeds on the architect's recommended defaults.
Issue: #2054 (bug, blocks work). Being fixed in a human-authorized interactive Worker session on 2026-10-09.
Related: #1616 (sandbox PID namespaces break `kill -0`), #1903 (`--failure-log` in literal /tmp), #1910 (wrapper replica), #314 (decision logic belongs in Python), D41 (one invocation site).
Change class: **additive**. This adds new config, a new test plugin, a new script and two new call sites. No existing contract field is removed or renamed. There are two behavior changes:
- The test-environment TMPDIR redirect (D4). The architect accepted it (Q2).
- A new scheduled deletion path at cron cycle start (D5, §8.2). Its scope is a merge-time human confirmation (§12.1).

---

## 0. Headline: a test run cleans up after itself; the reaper is only a backstop

**Human ruling (2026-10-09, verbatim):** *"We need to clean up the files. Can we make sure that they are normally cleaned up when the test run completes and have a script that cleans anything over 24h just in case?"*

The design has two layers. The order is deliberate.

### Layer 1: primary, in-run cleanup (S1)

Every pytest run that completes removes what it created. "Completes" means the session reaches `pytest_sessionfinish`: green, red, or interrupted by Ctrl-C that pytest handles. Four mechanisms, all inside pytest:

1. **Retention (D1).** A green run deletes its whole `pytest-N` at session end. A red or interrupted run keeps at most the newest failed dir, for inspection (count=1).
2. **Session TMPDIR redirect (D4).** Anything the run or its subprocesses put in temp space lands inside that run's own `pytest-N`. The same deletion therefore removes it.
3. **Leak fixes at the source (§7.1, §7.3).** These are the producers of the 960 `tmp.*` files, the 380 empty `tmp*` dirs and the 31 `tmp*.py` files.
4. **Mandatory guardrail (D6).** A green run that leaves any temp entry behind, or whose footprint exceeds 50 MiB, **fails**. "Cleans up after itself" is therefore enforced on every run, not hoped for.

### Layer 2: backstop, `scripts/framework/tmp_reaper.py` (S2)

The reaper removes what Layer 1 cannot:
- runs killed by SIGTERM or SIGKILL (cron timeouts, Bash-tool timeouts, ending print mode), where no in-run cleanup code can run;
- leaks from before this fix;
- leaks from other repos of the same user (subject to §12.1(a));
- stale agent scratch trees, such as ad-hoc repo clones under `/tmp/claude/` (for example `/tmp/claude/hos1935`, 548 MB). This is a human ruling that supersedes Q6's "report only": *"We should have the cleanup script zap the large scratch copies if older than 24h"* (D13, §5.7).

It removes **only entries older than 24 h**. That threshold is uniform for every category it removes: pytest run dirs, `tmp*` regular files, empty `tmp*` dirs, and scratch trees, where age is measured over the whole tree (D11). Age is **never sufficient alone**. Every removal also needs a second, non-age signal that the entry is dead (§5.6): a dead flock, no live `/proc` evidence, no open handle. The reaper runs at the start of every cron cycle (§8.2) and before every inner-loop suite run (§8.1).

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
- The largest per-test consumers are the ~45 `test_T6_*` tests in `tests/automation/test_dimension_sweep_cli.py`, at ~1.2 MB each. Each one's `make_repo()` copies `.claude/agents` (~528 KB) and `contract/dimensions` and then runs `git init` plus two commits (~416 KB of objects). Next come `invoke-agent-replica0` (3.6 MB, module-scoped) and `test_wrapper_runs_never_write_*` (3.6 MB) in `tests/automation/test_agent_invoke_wrapper.py`.
- So no single huge file causes the ~306 MB per full run. It comes from **thousands of small dirs, all retained because policy=`all`**, plus ~50 repo-replica fixtures at ~1.2 MB each.

### 1.2 Measured leaks at the /tmp top level (same day)

| Pattern | Count | Producer (root cause) |
|---|---|---|
| `/tmp/tmp.XXXXXXXXXX` regular files (coreutils `mktemp`) | 960 (462 non-empty) | `tests/framework/test_agent_invocation_migration.py:531-532`. The generated script runs `OUTFILE="$(mktemp)"` and `LEDGER="$(mktemp)"` and never removes either. The file contents (`verdict: … / ## opus-self — Adversarial Self-Review`) match `_run_opus_status_block_integration` exactly. That is 2 files per call × 3+ callers per run. |
| `/tmp/tmpXXXXXXXX` **empty** dirs (Python `tempfile.mkdtemp`) | 380 | Tests that call `tempfile.mkdtemp()` and then delete only the file, not the dir. Examples: `tests/oversight/test_ip_check.py:124` (`_write`), `tests/oversight/test_hallucination_surface_js.py:62` (`_tmp_pkg_json`), and others in the §7 inventory. |
| `/tmp/tmpXXXXXXXX.py`, `…_migration.py`, `….md` files | 31 | `NamedTemporaryFile(delete=False)` helpers in ~15 test files (for example `tests/oversight/test_validators_integration.py:_tmpfile`) whose callers do not always unlink. |
| `/tmp/hos-inner-loop-*-deadbee-*` | 2 | `tests/automation/test_hos_cron.py:1078`. Removed in fixture teardown, so these leak only when the run is killed. They are out of scope for the reaper (§5.4). |

### 1.3 Root cause of the five run dirs (pytest's default is to keep 3)

Read from the installed pytest 9.1.1 source (`_pytest/pathlib.py`, `_pytest/tmpdir.py`). The architect's round-1 evidence corrected item 2.

1. Each session creates `pytest-N` as `max_existing + 1` and writes `pytest-N/.lock`, which holds its PID. It registers two cleanup callbacks: remove its own `.lock`, and `cleanup_numbered_dir(keep=count)`.
2. Those callbacks run at **normal session end**: inside the session's exit stack when `pytest_sessionfinish` runs, with atexit only as a fallback. Under `policy=failed`, `tmpdir.pytest_sessionfinish` also rmtrees the basetemp on green, before the exit stack closes.
   - `cleanup_numbered_dir` deletes dirs numbered `≤ max_existing − keep`.
   - It does so only when `ensure_deletable()` returns true. That requires the dir to have **no `.lock`, or a `.lock` whose mtime is more than `LOCK_TIMEOUT = 3 days` older than the current run's dir**.
3. pytest installs no SIGTERM handler. Python's default SIGTERM action ends the process **without unwinding**, so neither the exit stack nor atexit runs. SIGKILL never runs them either. Runs get killed by `timeout` / `HOS_CRON_MAX_SECONDS`, by the Claude Bash tool's 120 s/600 s timeouts, and by print mode ending a turn ("background agent killed at 600s"). A killed run therefore:
   - (a) leaves its own `.lock` behind, which makes its dir **undeletable by pytest for 72 hours**, and
   - (b) skips its own cleanup, so older dirs it should have reaped stay as well.
4. The steady state is therefore *3 retained (policy `all`) + every run killed in the last 72 h + every run currently live*. The observed set was 125–128 at ~306 MB each, plus 129 in progress (128 MB). That is **3 kept + 1 survivor + 1 live**. The survivor is either a killed run's `.lock`-pinned dir or the dir that a killed later run failed to reap. The evidence was hand-deleted, so we cannot tell which. Item (3) explains both.
5. Concurrency among the worker cron, the overseer cron and interactive sessions never *lowers* the count. A finishing run computes `max_existing` including live, later-numbered runs, and every live run is protected by its `.lock`. Concurrency adds the "live" term.

How the fix handles each term:
- policy=`failed` makes "retained" ≈ 0 on green (Layer 1).
- `count=1` keeps at most the most recent failed dir (Layer 1).
- The reaper (§5) removes killed runs' dirs after 24 h on a definitive "holder is dead" signal, instead of after pytest's 72 h (Layer 2).

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `tmp_path_retention_policy = "failed"` and `tmp_path_retention_count = "1"` in `pyproject.toml`. | `failed` removes each passing test's `tmp_path` at teardown. It removes the whole basetemp at session end when the exit status is 0. `count=1` keeps only the newest numbered dir. |
| D2 | **Reject `policy = "none"`.** | `none` forces `keep=0`, and with `keep=0` pytest **creates no `.lock`** (architect verified this). A concurrent session's cleanup would then see a live dir as deletable and `rm -rf` it mid-run. Worker, overseer and interactive runs overlap, so `count ≥ 1` is load-bearing. |
| D3 | A **liveness flock** per session. A root-conftest session fixture opens `<basetemp>/.hos-live`, holds `fcntl.flock(LOCK_EX)` until `pytest_unconfigure`, and records `pid`, `start`, `dev` and `ino` (AC-4). It touches the file at each test start (heartbeat). All per-session state lives in `config.stash` (AC-5). | Kernel flocks belong to the open file description and the inode. They work across PID namespaces and bind mounts of the same tmpfs, and the kernel releases them on holder death, SIGKILL included. The architect verified this in both directions, host↔bwrap and bwrap↔bwrap. The recorded `dev`/`ino` turns the bind-mount assumption into a checked fact. |
| D4 | **Session TMPDIR redirect.** The fixture sets `os.environ["TMPDIR"]` and `tempfile.tempdir` to `<basetemp>/session-tmp`. Both are restored **inside the tryfirst `pytest_sessionfinish`, right after measuring** (AC-6). `pytest_unconfigure` restores only as a fallback. | Every in-process `tempfile.*` call and every subprocess `mktemp` / `${TMPDIR:-/tmp}` lands in a single-writer dir owned by this session. A completed green run deletes it with basetemp, which is Layer 1. Restoring before pytest deletes the dir means no later hook ever sees a dangling TMPDIR. |
| D5 | **One reaper script**, `scripts/framework/tmp_reaper.py`. It is Python, stdlib-only and **not** a scheduler. It has exactly two callers: `run_tests_inner_loop.sh`, before the suite, and `bin/hos-cron` at **cycle start**, after the overlap lock and before the usage-pause gate, preflight and auth (AC-8). | Decision logic stays in Python (#314). It lives under `scripts/framework/**`, so a file-deleting tool is itself a protected surface. Cycle start is the only cron site that can recover from a full quota, because a full quota kills the cycle at auth, long before wrap-up. |
| D6 | **Mandatory guardrail inside pytest** (root `tests/conftest.py`). At `pytest_sessionfinish` (tryfirst), on a run that would otherwise pass: (G-leak) any entry left in `<basetemp>/session-tmp` fails the session; (G-budget) allocated bytes under basetemp above **50 MiB** fail the session. `gc.collect()` runs before measuring. There is no retry, no xfail and no sleep or poll (AC-7). | It runs on every pytest invocation, so it is mandatory by construction. It measures a private single-writer dir, so it is deterministic. The human confirmed 50 MiB (Q4). |
| D7 | The budget can be **lowered only**, through `HOS_TEST_TMP_BUDGET_MB`. Values above 50, or non-integer values, are ignored with a warning. | Same precedent as #985 and #1718 D3. Raising the budget would recreate #2054. |
| D8 | Measure **allocated** bytes (`st_blocks × 512`), not apparent size. Count each inode once (hardlinks), and never follow symlinks. | The tmpfs quota counts allocated pages. |
| D9 | Shrink the repo-replica fixtures: a template repo per module plus `git clone --local` per test (§7.2). | Peak footprint and speed. |
| D10 | Ban direct temp-path creation in tests: `tempfile.mkdtemp`, `tempfile.mkstemp`, and `NamedTemporaryFile(…, delete=False)`. The ban covers every import and alias form (AC-14). A static test enforces it. | This turns the §1.2 leak classes into a deterministic failure. `TemporaryDirectory()` stays allowed. |
| D11 | **The reaper uses one uniform age threshold: 24 h** (`--min-age-hours`, default 24, **raise-only**; a value < 24 is a usage error). It applies to every category the reaper removes: pytest run dirs (dead-flock, legacy-lock, finished), `garbage-*` dirs, `tmp*` regular files, empty `tmp*` dirs, and class-S scratch trees, where age is taken over the whole tree (D13). **Age is never sufficient alone.** Every removal also needs a non-age signal (§5.6), and a live-process veto applies to all of them (AC-3). | This is the human ruling ("anything over 24h"). It replaces round 1's 2 h `min-age` and its separate `legacy-lock` / `orphan-min-age` knobs. One threshold means one rule to review. Making it raise-only stops a caller from turning the backstop into an aggressive deleter. |
| D12 | **Class T reaps leaked regular files**, not only empty dirs (Q1, human: YES). | The ~960 `/tmp/tmp.XXXXXXXXXX` files are exactly the backlog the human asked to remove. The source leaks are fixed in S1, so in steady state this is backstop only. The residual risk that the architect noted, a file held open in a namespace the reaper cannot see, is accepted by the ruling and is narrowed by the 24 h age. |
| D13 | **Class S: stale agent scratch trees are deleted** (human ruling, supersedes Q6 report-only). Scope is limited to directory children of the fixed scratch roots in §5.7. A tree is removed only if **every** §5.7 condition holds: (1) the newest `max(mtime, ctime)` *anywhere in the tree* is ≥ 24 h old, from a bounded walk that skips the tree if truncated; (2) every entry is uid-owned and on the same device, and no symlink is followed; (3) no visible process has a `cwd`, `root` or open fd under the tree; (4) no lock inside the tree is held; (5) the tree is not, and does not contain, a Claude Code session dir or the reaper's own cwd/TMPDIR. Class S runs only when the caller passes `--scratch` (only `bin/hos-cron` does) and the reaper can see the host PID namespace. | The human ruled that large scratch copies must be zapped after 24 h. This is the most destructive operation in the script, a recursive delete of a tree no test created, so it carries the strictest gate: whole-tree age, positive verification that `/proc` is complete (not just an absence of evidence), lock detection, and an explicit caller opt-in. The inner loop may run inside the bwrap sandbox, where host processes are invisible, so it never runs class S. |

---

## 3. Contract: pytest configuration (`pyproject.toml`) [S1]

Add to `[tool.pytest.ini_options]`:

```
tmp_path_retention_count = "1"
tmp_path_retention_policy = "failed"
```

Both values are strings. Do **not** set `basetemp`: a fixed basetemp is wiped at session start, which would delete a concurrent run's dir.

Resulting guarantees (§10 T1 tests them):
- **R-1.** After a green session completes, that session's `pytest-N` no longer exists.
- **R-2 (sequential sessions only, AC-11).** Take any sequence of **non-overlapping** completed (not killed) sessions. Afterwards at most **one** unlocked `pytest-N` remains: the most recent failed or interrupted one. A green run that follows a red run does not delete the red run's dir.
  - Under **overlap** this does not hold as a fixed number. Two concurrent red sessions both survive. A later-numbered session's cleanup may delete an earlier finished red dir, which loses that evidence. That is accepted, because the #1903 failure log is the inspection artifact.
  - The count is bounded by the number of overlapping red sessions and converges at the next completed session.
  - No test asserts a concurrent retention invariant.
- **R-3.** pytest never deletes a live concurrent session's dir. The `.lock` exists because `count ≥ 1`.

---

## 4. Contract: test-suite hygiene plugin [S1]

### 4.1 Location

- Hooks are declared in the root `tests/conftest.py`, the only conftest that pytest loads for every run of this suite.
- They delegate to `tests/tmp_hygiene.py`, which holds all logic. `tests/` is a package, so the module is importable as `tests.tmp_hygiene`, the same way existing tests import `tests.*` helpers. The §10 subprocess tests load it into a throwaway project via `load_module_from_path`.

### 4.2 Session fixture `_hos_tmp_hygiene` (scope=session, autouse=True)

All state goes into `request.config.stash` under a module-level `pytest.StashKey[HygieneState]`. Never use module globals (AC-5). `HygieneState` holds:
- `fd`
- `basetemp`
- `session_tmp`
- `saved_tmpdir_env`, either the original value or a sentinel meaning "absent"
- `saved_tempfile_tempdir`
- `restored: bool`
- `report`

Steps:
1. `basetemp = tmp_path_factory.getbasetemp()`, using the public fixture.
2. Open `basetemp/".hos-live"` with `O_CREAT|O_RDWR|O_CLOEXEC`, mode 0600. Call `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. If that fails, emit a warning and continue: hygiene setup never fails the suite. Then `os.fstat(fd)`, truncate, and write exactly one line:
   ```
   pid=<pid> start=<epoch> dev=<st_dev> ino=<st_ino>
   ```
   Both numbers are decimal, taken from the fstat of this fd (AC-4).
3. Create `basetemp/"session-tmp"` with mode 0700. Save the current `TMPDIR` (present or absent) and `tempfile.tempdir` into the state. Then set both to that path.
4. Store the state in `config.stash`.

### 4.3 `pytest_runtest_logstart` (heartbeat)

If the stash holds a state with an open `fd`, `os.utime` the `.hos-live` path. Swallow errors.

### 4.4 `pytest_sessionfinish(session, exitstatus)`, `hookimpl(tryfirst=True)`

This hook must run **before** `_pytest.tmpdir.pytest_sessionfinish`, which deletes basetemp on green. The architect verified that `wrap_session` returns `session.exitstatus` after this hook, so the override below is honored.

1. Look up the state in `session.config.stash`. If there is none (for example collect-only), do nothing.
2. Call `gc.collect()` (AC-7).
3. Measure:
   - `leaks` = direct children of `session_tmp`, each with its allocated bytes (D8), minus `LEAK_ALLOWLIST` (§4.6);
   - `footprint` = allocated bytes and inode count of the basetemp tree;
   - the top 20 subpaths (depth ≤ 2) by bytes.
4. **Restore** `TMPDIR` (or unset it if it was absent) and `tempfile.tempdir` from the saved values, then set `restored = True` (AC-6).
5. Build the report and store it in the state. It always contains:
   - `TMP_HYGIENE footprint_bytes=<n> inodes=<n> budget_bytes=<n> leaks=<n>`
   - one line per leak
   - the top-20 table, only when a gate trips.
6. **Enforce only when `exitstatus == 0`** and `PYTEST_XDIST_WORKER` is unset:
   - if `leaks > 0`, add `TMP_HYGIENE FAIL leak` and set `session.exitstatus = pytest.ExitCode.TESTS_FAILED`;
   - if `footprint > budget`, do the same with `FAIL budget`.
   - On a red run, report only.
7. The report is emitted from the root conftest's existing `pytest_terminal_summary`, as a section titled `tmp-hygiene (#2054)`. The terminal reporter's sessionfinish hookwrapper calls that hook after all `pytest_sessionfinish` implementations. If no terminal reporter is active, write the report to stderr at this step instead.

The gate is never retried, never xfail-ed and never skipped by marker. It has no sleep or poll. Every leak line names a path, so a recurrence is fixed at its producer (AC-7).

`_pytest.tmpdir.pytest_sessionfinish` receives the *original* `exitstatus`, so on a gate failure it still deletes basetemp. That is accepted, because the report already names every offending path and size. Do not work around it with private attributes.

### 4.5 `pytest_unconfigure(config)`

1. If the state exists and `restored` is false (the session never reached finish), restore `TMPDIR` and `tempfile.tempdir` now.
2. Close the `.hos-live` fd, which releases the flock, and clear `fd` in the state.

Releasing here and not at process exit matters for in-process repeated runs (mutmut).

The window after this, where `.hos-live` is unlocked and `.lock` is already gone, is a *finished* run. AC-1 routes that to rule 4, not to a dead-flock reap.

### 4.6 Budget and allowlist

- `BUDGET_BYTES = 50 * 1024 * 1024` (human-confirmed, Q4).
- `HOS_TEST_TMP_BUDGET_MB` is honored only if it is a positive integer ≤ 50 (D7).
- `LEAK_ALLOWLIST` is a module-level tuple of `(glob, producer, reason, issue)` entries (AC-13).
  - An entry is permitted **only** for a deterministic artifact of a **third-party tool** that the test cannot suppress through its environment.
  - Producers in this repo are never allowlisted: a leak from a repo script is fixed in that script, with a trap, in this PR.
  - The list is **empty at merge**, and T7 asserts that unconditionally.
  - Future entries must carry a non-empty `reason` and an `issue` in the form `#NNNN`.

### 4.7 Boundaries

- The plugin never deletes anything. Deletion stays with pytest (retention) and the reaper.
- It does not change any test's `tmp_path` contents, and it adds no files under a test's `tmp_path`.
- **Nested sessions.** A test that runs pytest in process or as a subprocess must give the inner run its own temp root, via `--basetemp=<tmp_path>/…` or `PYTEST_DEBUG_TEMPROOT=<tmp_path>/…`. Otherwise the inner run's `pytest-of-<user>` lands in the outer `session-tmp` and is correctly reported as a leak. No existing test runs nested pytest (grep for `pytester`, `pytest.main(` and `-m pytest` returns nothing); only the new §10 tests do.
- **xdist** (not installed): if `PYTEST_XDIST_WORKER` is set, report only, and say so in the report.

### 4.8 Subprocess envs built from scratch (AC-12)

About 93 `env={…}` / `env = {…}` sites in `tests/` build child environments without `TMPDIR`. Their children write to the real /tmp, which the gate cannot see.

- Add `child_env(env: Mapping[str, str]) -> dict[str, str]` to `tests/tmp_hygiene.py`. It returns a copy of `env`. If `TMPDIR` is set in `os.environ` and absent from `env`, the copy gains it. It never overrides a `TMPDIR` the caller set on purpose.
- The coder audits every such site and wraps it with `child_env(...)` wherever the child may create temp files. The PR body reports the audited count, the converted count and the residual count with reasons.
- This is not a gate. The §9 `empty_tmp_dirs` / `tmp_files` evidence is the backstop.

### 4.9 Redirect breakage policy (Q2 ruling)

- If a **test** breaks under the redirect, fix the test.
- If a **script** breaks only because `TMPDIR` is not `/tmp`, that is a real portability defect. Fix it in this PR, limited to TMPDIR correctness, in the commit that needs it to stay green, and list it in the PR body.
- Never neutralise the redirect for a test (for example `monkeypatch.setenv("TMPDIR", "/tmp")`). The S1 static test (T7) bans that pattern.
- For any other kind of script break: stop and escalate.

---

## 5. Contract: `scripts/framework/tmp_reaper.py` (Layer 2 backstop) [S2]

### 5.1 CLI

```
tmp_reaper.py [--tmp-root DIR] [--dry-run] [--measure] [--summary-only]
              [--scratch] [--min-age-hours H=24] [--max-seconds S=20]
```

- **`--scratch`** enables class S (§5.7). Without it, class S is not evaluated at all: no walk and no output, and `scratch_trees=-` in the summary. Only `bin/hos-cron` passes it (§8.2); the inner loop does not (§8.1).
- **Clock injection (testability).** `main(argv, *, clock=time.time) -> int` is the importable entry point, and `__main__` calls it with the real clock. Every age computation uses `clock()`. Tests run the reaper in process with `clock = lambda: time.time() + 48*3600` to make real-ctime entries "old" without lowering the threshold. A "recent" entry is created by `os.utime`-ing it to `fake_now − 1 h`.

- **`--tmp-root`** defaults to `$TMPDIR` if it is set and non-empty, and to `/tmp` otherwise. It is resolved with `realpath` once. It must be an existing directory owned by root or by the current uid, else exit 3. Tests always pass `--tmp-root <tmp_path>`.
- **`--min-age-hours`** is the single age threshold (D11). It must be a number ≥ 24, else exit 2. There are no other age knobs; round 1's `--legacy-lock-hours` and `--orphan-min-age-hours` are removed. Tests satisfy the threshold by backdating mtimes and ctimes, never by lowering it. ctime cannot be set directly, so a test that needs an old ctime injects `now` through `decide()` (R7) or monkeypatches the clock in-process.
- **`--dry-run`** makes every decision exactly as a real run would and prints `WOULD-REAP`. It performs **no** unlink, rmdir, rename or rmtree.
- **`--measure`** deletes nothing. It prints only the summary line, with `user_bytes` computed, plus `WARN large-unowned` lines (AC-10).
- **`--summary-only`** suppresses per-entry lines except `REAP` and `ERROR`.
- **`--max-seconds`** is a wall-clock budget covering the `/proc` scan and all candidates. When it is exhausted, the reaper starts no new candidates, finishes the current one, and reports `truncated=1`. The default is 20. Both callers pass 20 explicitly, inside a 30 s outer bound in cron (AC-9). `--measure` users pass a larger value (§9).
- **Exit codes:**
  - `0` = completed, including skips, per-entry errors and truncation;
  - `2` = usage error;
  - `3` = invalid tmp-root, or running as root.
  - Callers treat any non-zero as a warning, never as a failure.
- Stdlib only. It runs under `python3 -I` with no venv. The Python floor is 3.10.

### 5.2 Structure (testability)

- `collect_facts(entry, proc_index) -> Facts` performs all I/O: lstat, the safe `.hos-live` open and probe (§5.3.1), and child mtimes.
- `scan_proc() -> ProcIndex` (§5.3.3) runs at most once per invocation, and **lazily**: only when at least one candidate reaches a pre-veto REAP verdict. Idle cycles therefore cost one directory listing.
- `decide(facts, now, policy) -> Decision(action, reason)` is **pure**. Class S has its own pure `decide_scratch(tree_facts, now, policy)`; its I/O (the §5.7.4 walk and the `/proc/locks` parse) lives in `collect_scratch_facts()`.
- `act(decision)` performs the deletion.

### 5.3 Candidate class P: pytest run dirs

Candidates are the direct children of `<root>/pytest-of-<user>`, where `<user>` is `getpass.getuser()`. Before descending, the reaper requires `pytest-of-<user>` to be a real dir (lstat) owned by the current uid. Otherwise it prints `SKIP not-owned-or-symlink` and reaps nothing in class P.

| Child | Rule |
|---|---|
| name `^pytest-\d+$`, real dir, owned by uid | the decision table in §5.3.2 |
| name `^garbage-` | REAP `garbage` if quiet ≥ AGE, subject to the §5.3.3 veto. Otherwise SKIP fresh. |
| `pytest-current` or any symlink | unlink only if dangling; never follow |
| anything else | SKIP unknown |

**AGE** = `--min-age-hours` (24 h). **Quiet age** = `now − max(mtime, ctime)` over the dir itself, `.hos-live` and `.lock` if present, and its direct children. There is no deep walk.

#### 5.3.1 Safe `.hos-live` probe (AC-4)

1. Open with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`. `flock` works on a read-only fd. `O_NONBLOCK` keeps a FIFO from hanging the open.
2. `fstat` the fd. Require all of:
   - `S_ISREG`;
   - `st_uid == getuid()`;
   - the content parses as the §4.2 record, read with a 256-byte cap;
   - the record's `dev`/`ino` equal the fd's `st_dev`/`st_ino`.
   Any failure, or any open/read error → **SKIP unknown** (fail safe). A dev/ino mismatch means the path is not the inode the holder locked (overlay or private tmpfs), so a successful probe would prove nothing.
3. `flock(fd, LOCK_EX|LOCK_NB)`:
   - EWOULDBLOCK/EAGAIN → **SKIP live-flock** (definitive);
   - any other error → **SKIP unknown**;
   - success → holder dead (kernel guarantee). Keep the lock held until the action completes or the dir is kept.

#### 5.3.2 Decision table for `pytest-N`, evaluated in order

Before the table, compute **NEWEST_FINISHED**: the highest-numbered `pytest-N` with **no `.lock`**, over all children and regardless of age.

1. quiet < AGE → **SKIP fresh**. This applies always.
2. `.hos-live` exists → run the §5.3.1 probe.
   - SKIP verdicts stand.
   - On a successful probe:
     - `.lock` **present** → the run was killed → candidate **REAP dead-flock**;
     - `.lock` **absent** → the run finished normally (§4.5 released the flock) → go to rule 4 (AC-1).
3. No `.hos-live` and `.lock` exists (a legacy, consumer or other-repo run without D3) → candidate **REAP legacy-stale**. AGE is already satisfied by rule 1, and the veto still applies.
4. No `.lock` (a finished run, with or without an unlocked `.hos-live`):
   - if this is NEWEST_FINISHED → **KEEP newest**. This preserves count=1's inspection intent; the next completed session's own pytest cleanup supersedes it.
   - otherwise → candidate **REAP finished** (AC-2: quiet ≥ AGE, which is 24 h, plus the veto).
5. **Live-process veto (AC-3)**, applied to *every* candidate REAP in class P (rules 2, 3 and 4, and `garbage-*`). This is stricter than AC-3's "rules 3 and 4": adding rule 2 costs nothing and covers a killed pytest whose own child is still running in the dir. The veto checks, in order:
   - `.lock` names PID p, `/proc/p` exists, and `/proc/p/cmdline` contains `pytest` → **SKIP live-proc**;
   - any visible process's `cwd`, `root` or open fd resolves to a path at or under the candidate → **SKIP live-proc**;
   - the `/proc` scan was truncated by `--max-seconds` → **SKIP proc-scan-incomplete**;
   - `/proc` is absent or unreadable (macOS, or a restricted sandbox) → no evidence, and the candidate stands. Absence is never evidence of death; it simply removes the veto. Safety then rests on the flock and the 24 h age (accepted residual).
   - Otherwise → **REAP** with the candidate's reason.

#### 5.3.3 `/proc` index

`scan_proc()` iterates `/proc/[0-9]*`. For each PID it records `readlink` of `cwd`, `root`, `exe` and every `fd/*`, plus `cmdline`, ignoring EACCES/ENOENT/ESRCH. It is built lazily (§5.2), except under `--scratch`, where §5.7.1 requires it up front. It builds a set of resolved target paths.

- "At or under the candidate" is a string-prefix test on resolved paths with a trailing `/`.
- Class T (§5.4) uses the same index for exact-path matches.
- The scan checks the time budget after each PID. Running out marks the index `complete=False`.

#### 5.3.4 Deletion procedure for class P REAP verdicts

1. Re-lstat the entry and confirm the same `st_ino` and `st_dev` as at decision time.
2. `os.rename(dir, <pytest-of-user>/garbage-<uuid4>)`. ENOENT means a concurrent cleaner won → **SKIP raced**.
3. `shutil.rmtree(garbage)` with an error handler that records errors and continues (`onexc` on ≥ 3.12, `onerror` below). The rmtree never follows a symlink out of the tree.
4. Release the probe flock, if held, last.

pytest never reuses a number, so a dir cannot become live again between decision and rename.

### 5.4 Candidate class T: top-level orphans in `<root>`

Only **direct children** of `<root>` are considered. Each must match exactly one pattern:
- `^tmp[a-z0-9_]{8}$`
- `^tmp[a-z0-9_]{8}[A-Za-z0-9_.-]{1,32}$`
- `^tmp\.[A-Za-z0-9]{10}$`

Each must also be **owned by uid** and **not a symlink**.

| Type | Rule (all require quiet ≥ AGE = 24 h, D11) |
|---|---|
| empty dir | REAP `empty-dir` via `os.rmdir`. This is atomic: ENOTEMPTY if anything appeared, so contents are never destroyed. |
| regular file | REAP `file` via `os.unlink` (Q1, human: YES, D12). Re-lstat immediately before and require the same `st_ino`/`st_dev`. |
| non-empty dir, socket, fifo, device | **SKIP** (reported). Never recursive. |

- **Age.** `now − max(mtime, ctime) ≥ AGE`.
- **Open-handle veto.** If the entry is an exact target of any `cwd`, `root` or fd in the §5.3.3 index → **SKIP open**. If the index is incomplete → **SKIP proc-scan-incomplete**. If `/proc` is absent → no veto (accepted residual, D12).
- **Never touched:** `pytest-of-*`, `claude-*`, `hos-*` (including the #1903 failure logs), `node-compile-cache`, `gh-cli-cache`, `*.sock`, and anything not matching the patterns. This is an allowlist of patterns.
- **Non-empty `tmp*` dirs are not reaped.** No measured leak class produces them. Recursive deletion of an unknown tree on age alone is the riskiest operation this script could perform. The human ruling asks for leaked files to be removed, which D12 does. §12.1(d) records this as a scope confirmation.
- **Large-entry warning (AC-10: `--measure` only).** Under `--measure`, any user-owned top-level entry larger than 100 MiB that no class covers produces `WARN large-unowned <path> <bytes>`. The walk is depth-bounded and time-boxed, and **never runs** in default or `--summary-only` mode. Deletion of large *agent scratch trees*, such as `/tmp/claude/hos1935` (548 MB), is no longer report-only. The human ruling that supersedes Q6 moves them to class S (§5.7), which deletes them only under `--scratch` and only when every §5.7 condition holds. Large entries outside the §5.7 scratch roots stay report-only.

### 5.5 Output (stable, greppable)

```
REAP <class> <reason> <path> <bytes>
WOULD-REAP <class> <reason> <path> <bytes>     (dry-run)
SKIP <reason> <path>
ERROR <errno-name> <path>
WARN large-unowned <path> <bytes>              (--measure only)
TMP_REAPER root=<root> reaped=<n> freed_bytes=<n> skipped=<n> errors=<n> truncated=<0|1> user_bytes=<n|-> pytest_runs=<n> empty_tmp_dirs=<n> tmp_files=<n> scratch_trees=<n|-> dry_run=<0|1>
```

`<class>` is one of `P`, `T` or `S`.

- `<bytes>` on `REAP` lines covers the candidate itself only. For a class-P dir it is that dir's allocated bytes, which the `act` step measures just before rename (AC-10). For a class-S tree it is the allocated total from the §5.7 walk, so there is no second walk.
- `scratch_trees` is the number of directory children of the §5.7 scratch roots **remaining** after acting, excluding `garbage-hos-*`. It is `-` when `--scratch` is not given or class S was disabled for the run (§5.7.1).
- `user_bytes` is computed **only under `--measure`**. Otherwise it is `-`. Under `--measure` it is `-` if the walk was truncated.
- `pytest_runs`, `empty_tmp_dirs` and `tmp_files` are counts of entries **remaining** after acting: `pytest-N` children, class-T empty dirs, and class-T regular files. They come from listings, which are cheap in every mode.
- The summary line always prints, always last, and matches:
  `^TMP_REAPER root=\S+ reaped=\d+ freed_bytes=\d+ skipped=\d+ errors=\d+ truncated=[01] user_bytes=(\d+|-) pytest_runs=\d+ empty_tmp_dirs=\d+ tmp_files=\d+ scratch_trees=(\d+|-) dry_run=[01]$`

### 5.6 Boundaries

- The reaper never acts on an entry whose realpath parent is not `<root>`, `<root>/pytest-of-<user>`, or a §5.7 scratch root.
- It never acts on an entry not owned by the current uid.
- It never runs as root: `os.geteuid() == 0` → exit 3.
- **Age alone never deletes.** Every REAP needs age ≥ 24 h **and** a non-age signal **and** survival of the live-process veto. The non-age signals are:
  - dead flock on a verified inode, with `.lock` present (killed run);
  - legacy `.lock` with no `.hos-live`;
  - lock-free finished dir that is not the newest;
  - `garbage-` naming;
  - class-T empty dir or regular file;
  - class-S: a whole-tree walk that completed, with every entry ≥ 24 h old, uid-owned and on the same device, no held lock, and no session marker, plus a **complete** host-view `/proc` index (§5.7). For class S, absence of evidence is not enough: a missing or incomplete `/proc` disables class S.

### 5.7 Candidate class S: stale agent scratch trees (`--scratch` only; human ruling supersedes Q6)

The human's words: *"We should have the cleanup script zap the large scratch copies if older than 24h."* The target is ad-hoc repo clones and similar trees that agents create in a shared scratch location, for example `/tmp/claude/hos1935` (548 MB). Class S is evaluated only when `--scratch` is given.

#### 5.7.1 Run-level preconditions (any failure disables class S for the whole run)

All of the following must hold. Otherwise print one `SKIP scratch-disabled <reason>` line and set `scratch_trees=-`:
- `/proc` is readable.
- **Host PID namespace.** The `NSpid:` line of `/proc/self/status` has exactly one field, **and** `/proc/1/comm` is readable and is not `bwrap`. This is defence in depth: only the unsandboxed `bin/hos-cron` passes `--scratch`. Reason `no-host-view`.
- `/proc/locks` is readable. Reason `no-locks-view`.
- The §5.3.3 index is built eagerly when `--scratch` is given and is `complete=True`. Reason `proc-scan-incomplete`.

#### 5.7.2 Eligible roots (explicit, closed list)

- `SCRATCH_ROOTS` is a module constant naming paths relative to `<root>`. In v1 it holds exactly `("claude",)`, i.e. `/tmp/claude/`, the agent scratch convention in `CLAUDE.md` (`/tmp/claude/body.md`, ad-hoc clones).
- Adding a root is a code change to a protected surface and needs a test. There is no CLI or env override.
- A scratch root is used only if, by lstat, it is a real directory (not a symlink), owned by uid, with `st_dev` equal to `<root>`'s, and its `realpath` equals `<root>/<name>` exactly. Otherwise: `SKIP scratch-root-invalid <path>`.
- **Candidates** are the **direct children** of a scratch root that lstat as real directories. Regular files, symlinks and special files directly in a scratch root are never touched: no class S, and no class T, which only scans `<root>`. Arbitrary `/tmp` content is never eligible.

#### 5.7.3 Claude Code session dirs: how they are recognised and excluded

Claude Code keeps its per-user session state, task output and scratchpads under `<root>/claude-<uid>/…` (for example `/tmp/claude-1000/<project-slug>/<session-uuid>/scratchpad`). Exclusion is layered, and any one layer suffices:

1. **By root.** `<root>/claude-<digits>` is never a scratch root. The §5.7.2 realpath-equality check also stops a `claude` symlink or bind redirect from pointing class S at it.
2. **By name.** A scratch-root child named `^claude-\d+$` → `SKIP session-dir`.
3. **By marker (fail safe, during the walk).** Any directory named `scratchpad`, or any entry at depth ≤ 3 whose name matches a UUID (`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`), → `SKIP session-like` for the whole tree. A false positive only keeps a tree.
4. **Self.** If the tree equals or contains the realpath of the reaper's own `os.getcwd()`, of `$TMPDIR`, or of any absolute-path environment variable value that lies under a scratch root → `SKIP self`.
5. **Live session.** A running Claude Code session, or any other process, whose `cwd`, `root`, `exe` or open fd is at or under the tree → `SKIP live-proc` (§5.7.4 step 4).

#### 5.7.4 Per-tree decision, in order (cheap checks first)

1. **Identity.** Real dir, uid-owned, `st_dev` equal to the scratch root's, not `garbage-hos-*` (step 8 handles those). Otherwise `SKIP not-owned-or-foreign-dev`.
2. **Exclusions.** §5.7.3 layers 2 and 4.
3. **Top-level pre-filter.** If the dir's own `max(mtime, ctime)` is younger than AGE → `SKIP fresh`. This pre-filter can only skip, never approve.
4. **Live-process veto.** Any index entry (`cwd`, `root`, `exe`, `fd/*`) at or under the tree → `SKIP live-proc`. The index is complete by §5.7.1.
5. **Bounded whole-tree walk.** Iterative `os.scandir` with `follow_symlinks=False`; every entry is `lstat`-ed. The walk stops with a SKIP at the first failing entry:
   - entry `max(mtime, ctime)` younger than AGE (**age = the newest timestamp anywhere in the tree**) → `SKIP fresh-deep`. Exiting early makes active trees cheap.
   - `st_uid ≠ uid` → `SKIP foreign-owned`.
   - `st_dev ≠` the tree's dev (a mount point inside) → `SKIP cross-device`.
   - socket, FIFO or device → `SKIP special`.
   - directory unreadable (EACCES/EPERM) → `SKIP unreadable`. Unverifiable age is not old.
   - §5.7.3 layer 3 marker → `SKIP session-like`.
   - `(st_dev, st_ino)` present in the `/proc/locks` set (flock, POSIX and OFD locks; parsed once per run as `major:minor:inode`) → `SKIP held-lock`.
   - A regular file whose name matches `*.lock`, `*.lck`, `.hos-live`, `LOCK` or `lock`: probe it as in §5.3.1 (`O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, `flock(LOCK_EX|LOCK_NB)`, released immediately). EWOULDBLOCK → `SKIP held-lock`; any other error → `SKIP unknown`. This is a second lock signal alongside `/proc/locks`.
   - Symlinks are counted for age and ownership by `lstat`, but **never followed or descended**.
   - **Bounds.** At most `SCRATCH_MAX_INODES = 1_000_000` entries per tree, plus the global `--max-seconds` budget. Hitting either → `SKIP walk-truncated`. A tree is never partly judged and never partly deleted.
   - The walk sums allocated bytes (D8) for the REAP line.
6. If the walk completes with no SKIP → candidate **REAP scratch-stale**.
7. **Removal** (same path as class P, §5.3.4):
   - (a) lstat the tree, record `(st_dev, st_ino)`;
   - (b) `os.rename(tree, <scratch-root>/garbage-hos-<uuid4>)`, where ENOENT → `SKIP raced`;
   - (c) lstat the garbage path and require the same `(st_dev, st_ino)`. A mismatch → `ERROR identity-changed`, **no rmtree**, left for a human;
   - (d) `shutil.rmtree` with the recording error handler (symlink-safe; never follows out of the tree).
   - Under `--dry-run`, print `WOULD-REAP S scratch-stale <path> <bytes>` and stop before (b).
8. **`garbage-hos-*` children** (a removal that was interrupted): REAP `garbage` if the top-level quiet ≥ AGE and the live-process veto passes. Steps 7(c)–(d) are applied directly.

**Accepted residual.** Between the walk and the rename (milliseconds), a process could start using the tree. After the rename, path-based access fails. A process that `chdir`-ed in during that window keeps its cwd inode until it exits. This is narrower than class P's residual, because the `/proc` index is required to be complete.

---

## 6. Guardrail measurement: rationale

### 6.1 Rejected: before/after delta of /tmp

The tmpfs is shared with concurrent same-user writers, so a delta would be flaky. `repquota` cannot read a tmpfs quota. This rejection stands (architect, AC-7).

### 6.2 Chosen: the session's private basetemp

D4 routes everything that honors TMPDIR into `<basetemp>/session-tmp`, a 0700 dir that only this session writes to. D6 measures it.

Remaining escapes:
- (a) Literal `/tmp/...` mktemp templates in scripts. S3 converts them, and T9 bans new ones (AC-14 forms).
- (b) Subprocess envs built from scratch. §4.8 audits them, and the reaper backstops what remains.
- (c) Literal `/tmp` by design: the #1903 failure log, and `tests/framework/test_install_sandbox_config.py::clean_root`. Both are allowlisted in the static tests with reasons.

S3's conversion of (a) brings those scripts into G-leak's view. Any leak this exposes is fixed with a trap in the same PR, never allowlisted (Q3 ruling).

### 6.3 The 50 MiB budget (human-confirmed, Q4)

On a green run, after D1, basetemp at session finish holds only:
- session- and module-scoped `tmp_path_factory` dirs;
- `.hos-live`;
- leftovers in `session-tmp`, which must be zero.

The coder records the measured `footprint_bytes` of a full inner-loop run in the PR. If it exceeds 25 MiB, the coder says so in the PR.

---

## 7. Leak inventory and fixture slimming [S1 for tests, S3 for scripts]

### 7.1 Tests: required changes

| File | Change |
|---|---|
| `tests/framework/test_agent_invocation_migration.py` `_run_opus_status_block_integration` | `OUTFILE` and `LEDGER` become `"$OUT_DIR/outfile.md"` and `"$OUT_DIR/ledger.jsonl"` under `tmp_path`, with no `mktemp`. **This fixes the 960 files.** |
| `tests/oversight/test_ip_check.py`, `test_prompt_audit_risk.py`, `test_hallucination_surface_js.py`, `test_shell_logic_check.py` (every `tempfile.mkdtemp()` site) | Use `tmp_path`. Helpers take a `Path` argument. |
| every `tempfile.NamedTemporaryFile(..., delete=False)` site (`test_n1_detector.py`, `test_validators_mocked.py`, `test_rn_calculator.py`, `test_prompt_audit_risk.py`, `test_function_metrics_js.py`, `test_hallucination_surface_js.py`, `test_validators_integration.py`, `test_rn_calculator_js.py`, `test_n1_detector_js.py`, `test_complexity_metrics_js.py`, `test_static_analysis_js.py`, `test_hallucination_surface.py`, `test_function_metrics.py`, `test_shell_logic_check.py`, `test_ip_check.py`) | Write into `tmp_path`. Keep the file names and suffixes. |
| scrubbed-env sites (~93) | §4.8 `child_env` audit (AC-12). |
| new `tests/framework/test_tmp_hygiene_static.py` | **D10/AC-14**, see T7. |

The coder re-runs the §1.2 grep and the `mktemp` grep over `tests/` after the edits, and lists any other site found in the PR body.

### 7.2 Fixture slimming (D9)

- `tests/automation/test_dimension_sweep_cli.py::make_repo`:
  - Build a **module-scoped template** via `tmp_path_factory`. It holds the identical base content, the `base` commit and the `BASE` tag.
  - Each test runs `git clone -q --local <template> <tmp_path>/repo`.
  - Then re-apply `user.email`, `user.name` and `commit.gpgsign=false`.
  - Then write `files` and commit `change`.
  - The existing function signature is kept, so variant bases can still be built from scratch.
  - Target: each `test_T6_*` dir ≤ 0.75 MiB.
- `.git/hooks` samples: every test-side `git init` / `git clone` in the files touched above passes `--template=` with an empty template dir, or `-c init.templateDir=`.
- `tests/automation/test_agent_invoke_wrapper.py`: extend `_REPLICA_IGNORE` **only if** the wrapper provably does not read the added paths. Otherwise leave it unchanged.

### 7.3 Scripts: signal-path and TMPDIR hardening [S3, protected]

| Site | Issue | Required |
|---|---|---|
| `scripts/oversight/run_validators.sh:219` (`/tmp/validator_XXXXXX`) | literal /tmp; no trap | `${TMPDIR:-/tmp}`; function-scope cleanup on RETURN plus the existing EXIT path |
| `scripts/oversight/gates/secret_scan.sh:146`; `security_scan.sh:74,114` | literal /tmp; `PIP_AUDIT_TMP` not removed on all paths | same |
| `scripts/framework/validate_agents.sh:296,298,356,357`; `validate_scripts.sh:206` | literal /tmp | `${TMPDIR:-/tmp}`; EXIT trap |
| `bootstrap/hos_install.sh:2030,2062,2077` (`_bf`, `_tmp`, `_human_generated`) | no trap | add to the installer's existing cleanup list/trap |
| new `tests/framework/test_tmp_template_static.py` (T9) | — | Fails on any `mktemp` in `scripts/`, `bin/`, `bootstrap/` (AC-14) that has any of: a template operand beginning with `/tmp/` (including the operand after `-t`); `-p /tmp` or `-p/tmp`; `--tmpdir=/tmp` or `--tmpdir /tmp`. Allowlist: `scripts/framework/run_tests_inner_loop.sh` (#1903 by design), with its reason. |

Already compliant: unchanged from round 1. These are `bootstrap/*` TOKEN_FILE, `bin/hos-human`, `bin/hos-cron:474,906,1220,1677`, `regen_all.sh:96`, `run_post_change_sweep.sh:121`, `run_release_panel.sh:235`, `validate_self.sh:337`, `vendor_invoke.sh`, `scripts/dev/commit_onto_base.sh`, `dimension_sweep_cli.py:701`, and the `mkstemp`-in-target-dir writers.

---

## 8. Call sites [S2, protected]

### 8.1 `scripts/framework/run_tests_inner_loop.sh`

- **Placement:** the first statement inside `_run_suite()`, **before** `regen_all.sh`, which itself calls `mktemp -d`.
- Run the reaper only if `"$SCRIPT_DIR/tmp_reaper.py"` exists. Absence happens only in test replicas.
- **Invocation:** `"$PYTHON" -I "$SCRIPT_DIR/tmp_reaper.py" --summary-only --max-seconds 20` (AC-9). The inner loop does **not** pass `--scratch`, because it may run inside the PID-namespaced sandbox, where live host processes are invisible (D13).
- **Best-effort:** a non-zero exit prints one `✘ tmp_reaper failed (rc=N) — continuing` line to stderr and never changes the script's exit code. Use the `|| …` form so `set -e` does not trip. Under `--failure-log` the output is teed into the log.
- `--help` gains one line naming the reaper.
- The runner does **not** gate on reaper output. The gate is D6.

### 8.2 `bin/hos-cron`: cycle start (AC-8, AC-9)

- **Placement: exactly one call site.** It goes immediately after the `_audit()` helper definition ("Audit helper" block) and before the "Usage-threshold pause gate (#1944 …)" block.
  - That point is after the overlap lock is acquired and its EXIT trap is set, after cycle identity is minted, and before the usage-pause gate, `validate_setup`, `get_app_token.sh` and all other preflight.
  - Consequences:
    - it runs once per **lock-acquiring** cycle, for both roles, including cycles that later pause, fail preflight or fail auth;
    - it does **not** run on the suspended exit (a human said stop), which is earlier in the script;
    - it does **not** run on the lock-held exit (the holder reaps).
- **No wrap-up call.** The round-1 wrap-up site is removed (one site, D41).
- **Dedicated bound (AC-9):** a reaper-owned array, for example `_TR_BOUND`, never `_UP_BOUND`.
  - It is `timeout --kill-after=5 30`, or `gtimeout --kill-after=5 30`, or empty if neither exists.
  - The inner `--max-seconds 20` is strictly less than the outer 30.
  - The numbers are named constants beside the array, in the style of the `_UP_CHECK_*` constants.
- **Invocation:** run only if `"$REPO_ROOT/scripts/framework/tmp_reaper.py"` exists:
  `${_TR_BOUND[@]+"${_TR_BOUND[@]}"} python3 -I "$REPO_ROOT/scripts/framework/tmp_reaper.py" --summary-only --scratch --max-seconds 20`
  (`--scratch` is passed here only: a scheduled `bin/hos-cron` cycle runs unsandboxed, per CLAUDE.md, so it sees host processes.)
  - Capture stdout and rc with `|| _tr_rc=$?`.
  - Echo each output line prefixed with `$LOG_PREFIX`.
- **Audit:** emit `_audit cycle-tmp-reap "rc=<rc>" "summary=<TMP_REAPER line or ->"` **only** when rc ≠ 0 or the summary does not contain ` reaped=0 `. Idle cycles add no record (#1803). A timeout (rc 124/137) is therefore always audited.
- **Never fatal.** The cycle continues to the usage-pause gate whatever the rc. The reaper's output and rc set no variable that later logic reads.

### 8.3 `CLAUDE.md`: "Canonical entry points by task" table

Add one row:

> | Reclaiming per-user /tmp space (backstop): stale `pytest-of-$USER/pytest-N` dirs, orphaned `tmp*` files and empty `tmp*` dirs, and (with `--scratch`) agent scratch trees under `/tmp/claude/` whose newest file is older than 24 h. Never touches a live run, a held lock, or Claude Code session dirs; `--dry-run`, `--measure` | `scripts/framework/tmp_reaper.py` |

Add one sentence after the table: *"Test runs clean up their own temp files when they complete. The suite enforces zero leaked temp entries and a 50 MiB /tmp budget per session (`tests/conftest.py`, #2054). A red `TMP_HYGIENE FAIL` is a real failure, not flake."*

### 8.4 `docs/CRON-SETUP.md`

Add one paragraph to the cycle-start section (AC-8). It says that every lock-acquiring cycle runs the reaper before the usage-pause gate and auth, bounded at 30 s, with the 24 h rule, including `--scratch` deletion of stale `/tmp/claude/*` scratch trees (§5.7). It names the `cycle-tmp-reap` audit event and its emit condition, and says suspended and lock-held exits do not reap.

---

## 9. Acceptance procedure (the coder records the evidence in the PR)

1. `python3 scripts/framework/tmp_reaper.py --measure --max-seconds 600` → record `user_bytes`, `pytest_runs`, `empty_tmp_dirs` and `tmp_files` (M0).
2. Run `scripts/framework/run_tests_inner_loop.sh`, then `--measure` (M1). Run the suite again, then `--measure` (M2).
3. Pass criteria (**Layer 1 evidence**: the runs cleaned up after themselves):
   - `M2.user_bytes − M0.user_bytes ≤ 50 MiB`;
   - `M2.pytest_runs ≤ M0.pytest_runs`, excluding concurrently live runs, which the coder names;
   - `M2.empty_tmp_dirs ≤ M0.empty_tmp_dirs`;
   - `M2.tmp_files ≤ M0.tmp_files`;
   - both runs print `TMP_HYGIENE … leaks=0`.
   - Note: the inner loop invokes the reaper (§8.1), so M1/M2 may also show backlog removal. Record the reaper's `REAP` count from each run's log separately, so Layer 1 and Layer 2 effects can be told apart.
4. **Layer 2 evidence:** `python3 scripts/framework/tmp_reaper.py --dry-run --scratch` on the dev host, run by the human or from an unsandboxed shell; inside the sandbox class S reports `scratch-disabled`. For class S, also record each `WOULD-REAP S` path and the `SKIP` reasons for scratch trees that are kept. Record the `WOULD-REAP` counts by class and reason, and confirm that no `WOULD-REAP` names a path younger than 24 h. Never run a real reap of the dev-host backlog from an agent session (§11).
5. These numbers are not a CI gate (§6.1). The deterministic gates are D6 and the static tests.

---

## 10. Tests

### S1

| ID | Test (file) | Asserts |
|---|---|---|
| T1 | `tests/framework/test_tmp_hygiene_plugin.py` | **Retention, sequential only (AC-11).** Generate a mini project in `tmp_path`, with a conftest that loads `tests/tmp_hygiene.py` and the D1 ini values read **from the real `pyproject.toml`**. Run `python -m pytest` with `PYTEST_DEBUG_TEMPROOT=<tmp_path>/root`. (a) green → no `pytest-N`; (b) red → exactly 1; (c) red, green, red → ≤ 1, and it is the newest. No concurrent-retention assertion. |
| T2 | same | **Leak gate.** A mini test calling `tempfile.mkdtemp()` gives exit 1 and `TMP_HYGIENE FAIL leak` naming the path. The `subprocess.run(["mktemp"])` variant is also caught. A leak reachable only through a `TemporaryDirectory` held in a reference cycle is *not* reported, which proves `gc.collect()` runs (AC-7). |
| T3 | same | **Budget gate.** `HOS_TEST_TMP_BUDGET_MB=1` plus a 2 MiB session-scoped dir gives exit 1 with `FAIL budget`. `=500` is ignored with a warning, and the budget stays 50. |
| T4 | same | **Red run.** A failing test plus a leak gives exit 1 and the report, with no `FAIL leak` escalation. |
| T5 | same | **flock and record.** While a mini session is running, `flock(LOCK_EX\|LOCK_NB)` on `.hos-live` from the outer process fails. After exit it succeeds. The record's `dev`/`ino` equal `os.stat(.hos-live)` (AC-4). |
| T6 | same | **In-process nesting and restore (AC-5, AC-6).** Inside an outer test session, run an inner `pytest.main([... , "--basetemp", <tmp_path>/inner])`. Afterwards: the outer stash state (fd, paths) is unchanged; `TMPDIR` and `tempfile.tempdir` equal the outer `session-tmp`; and the outer flock is still held (a fresh fd's `LOCK_NB` probe fails). In a standalone mini session, a session-finish hook registered `trylast` observes `TMPDIR` and `tempfile.tempdir` already restored. |
| T7 | `tests/framework/test_tmp_hygiene_static.py` | **D10/AC-14.** An AST scan of `tests/**/*.py` fails on `tempfile.mkdtemp`, `tempfile.mkstemp`, and `NamedTemporaryFile` with the keyword `delete=False`. It resolves `import tempfile as t`, `from tempfile import mkdtemp as m`, and `from tempfile import NamedTemporaryFile` aliases. Its own `(path, reason)` allowlist starts empty. It also asserts: (i) the `pyproject.toml` D1 values; (ii) `LEAK_ALLOWLIST` is empty (unconditional, AC-13); (iii) no test sets `TMPDIR` to the literal `"/tmp"` via `monkeypatch.setenv` or `os.environ` (§4.9). |
| T8 | (existing) full inner loop | green with `leaks=0`; footprint recorded. |
| T11 | `tests/framework/test_tmp_hygiene_plugin.py` | `child_env` adds `TMPDIR` when absent and never overrides a caller-set `TMPDIR` (AC-12). |

### S2 (`tests/framework/test_tmp_reaper.py`, every test with `--tmp-root <tmp_path>`; no test touches the real /tmp)

"Old" means mtimes backdated ≥ 48 h. Where ctime matters, the test uses the pure `decide()` or an injected clock (§5.1).

| ID | Asserts |
|---|---|
| R1 | **A live run is never touched.** A child creates `pytest-of-<user>/pytest-5/.hos-live` with a valid record, plus `.lock`, flocks it, and sleeps. With the dir old, the real and `--dry-run` reapers both print `SKIP live-flock` and the tree is byte-identical. After the holder gets **SIGKILL** → `REAP dead-flock`. |
| R2 | Legacy `.lock`, no `.hos-live`: quiet 3 h → `SKIP fresh`; quiet 23 h → `SKIP fresh`; old → `REAP legacy-stale` (uniform 24 h, D11). |
| R3 | Legacy `.lock` naming a live child whose argv contains `pytest`, old → `SKIP live-proc` (skipped if `/proc` is absent). |
| R4 | quiet < 24 h beats a dead flock → `SKIP fresh`. |
| R5 | Two old lock-free finished dirs → the newest is KEPT and the older is REAPED. |
| R6 | **Symlinks.** `pytest-of-<user>` is a symlink → nothing reaped in class P. `pytest-7` is a symlink to an outside dir → the outside dir is intact. A reaped dir containing a symlink to an outside file → the outside file is intact. A dangling `pytest-current` is removed; a valid one is kept. |
| R7 | `decide()` with synthetic facts: uid mismatch → SKIP; probe error ≠ EWOULDBLOCK → SKIP unknown; absent PID → never REAP by itself; index `complete=False` → SKIP proc-scan-incomplete; a `/proc`-absent index removes the veto but never creates a REAP on its own. |
| R8 | Class T: old empty `tmpabcd1234` → removed. Non-empty → SKIP. 23 h → SKIP. Old `tmp.AbCdEf1234` file → removed (D12). Old `tmpabcd1234.py` file → removed. File held open by a live child → `SKIP open` (Linux). FIFO → SKIP. Non-matching names untouched. |
| R9 | Old `garbage-*` → reaped; 23 h → SKIP. |
| R10 | `--dry-run` leaves the tree identical (names, inodes, mtimes) and prints `WOULD-REAP`. |
| R11 | Two concurrent reapers: both exit 0, every candidate is gone, no traceback. |
| R12 | Root resolution: TMPDIR set → used; unset → `/tmp` (unit-test the resolver only). Missing root → exit 3. `geteuid()==0` (monkeypatched) → exit 3. |
| R13 | The summary line is last and matches the §5.5 regex. `--measure` deletes nothing and prints a numeric `user_bytes`. |
| R14 | `--max-seconds 0` → `truncated=1`, exit 0, and nothing reaped. |
| R15 | **AC-1.** An old **finished red** dir (unlocked `.hos-live`, no `.lock`) that is NEWEST_FINISHED → KEEP. An older sibling of the same shape → `REAP finished`. |
| R16 | **AC-4.** `.hos-live` whose record `dev`/`ino` mismatch → `SKIP unknown`. A FIFO named `.hos-live` → `SKIP unknown`, and the reaper returns within the test timeout (no hang). A symlink named `.hos-live` → `SKIP unknown` (`O_NOFOLLOW`). |
| R17 | **AC-3.** An old lock-free non-newest dir that is the `cwd` of a live child → `SKIP live-proc` (Linux). The same holds for an old dead-flock dir (the stricter rule-2 veto). |
| R18 | **D11.** `--min-age-hours 2` → exit 2. `--min-age-hours 48` is accepted. |
| R19 | **AC-10.** Default and `--summary-only` runs print `user_bytes=-` and no `WARN` line, and never call the size-walk function (asserted in process by monkeypatching the walk to raise). Under `--measure`, with the large-entry threshold monkeypatched down to a small value, a user-owned non-candidate tree above it produces one `WARN large-unowned`. |
| RS1 | **Class S: a stale tree is removed.** In process, with `clock = real + 48 h` and `--scratch`, `<tmp_path>/claude/clone1/a/b/c.txt` → `REAP S scratch-stale`, and the tree is gone (no `garbage-hos-*` left). The §5.7.1 host-view preconditions are monkeypatched to pass, so the test also runs where `/proc/1` is `bwrap`. |
| RS2 | **One recent deep file keeps the tree.** As RS1, but `a/b/c.txt` is `os.utime`-d to `fake_now − 1 h` → `SKIP fresh-deep`, and the tree is byte-identical. |
| RS3 | **A tree that is some process's cwd is kept.** A child process `chdir`s into `<tmp_path>/claude/clone2/sub` and sleeps → `SKIP live-proc` (Linux; skipped if `/proc` is absent). After the child is killed → `REAP`. |
| RS4 | **A held flock keeps the tree.** A child holds `flock(LOCK_EX)` on `<tmp_path>/claude/clone3/x/index.lock` → `SKIP held-lock`. A second variant holds an `fcntl.lockf` POSIX lock on a file **not** named like a lock (`data.bin`), which proves the `/proc/locks` path → `SKIP held-lock`. After release → `REAP`. |
| RS5 | Symlinks: a scratch child that is a symlink → untouched. A tree containing a symlink to an outside dir → reaped, and the outside dir is intact. A `claude` scratch root that is a symlink → `SKIP scratch-root-invalid`, nothing reaped. |
| RS6 | Session-dir exclusion: `<tmp_path>/claude-1000/...` is never evaluated; a scratch child named `claude-1000` → `SKIP session-dir`; a tree containing a `scratchpad` dir or a UUID-named dir at depth ≤ 3 → `SKIP session-like`; a tree containing the reaper's cwd (in-process `monkeypatch.chdir`) → `SKIP self`. |
| RS7 | Fail-safe walk: `SCRATCH_MAX_INODES` monkeypatched to 2 → `SKIP walk-truncated`, tree intact. A `chmod 000` subdir → `SKIP unreadable` (skipped as root). A FIFO inside → `SKIP special`. |
| RS8 | Run-level gating: without `--scratch` → no class-S output, `scratch_trees=-`. With `--scratch` but the NSpid/`bwrap` check failing, `/proc/locks` unreadable, or an incomplete index (each monkeypatched) → one `SKIP scratch-disabled <reason>`, nothing in class S deleted. |
| RS9 | Removal identity: monkeypatch `os.lstat` so that the post-rename `(st_dev, st_ino)` differs → `ERROR identity-changed`, `shutil.rmtree` is never called (spy), and `garbage-hos-*` remains. `--dry-run` → `WOULD-REAP S` and no rename. |
| RS10 | `decide_scratch()` (pure) with synthetic facts: foreign uid, cross-device entry, held-lock hit, fresh-deep, and session marker each give the named SKIP. Only the all-clear fact set yields REAP. |
| C1 | `tests/framework/test_run_tests_inner_loop.py`: with the reaper stub, it runs before `regen_all.sh` with `-I … --summary-only --max-seconds 20`, and **without** `--scratch`. Reaper rc=1 → the suite's exit code is unchanged. Existing tests are unchanged. |
| C2 | `tests/automation/test_hos_cron.py` (**AC-8**): with the reaper stub installed: (a) invoked **exactly once** per lock-acquiring cycle, with `--scratch` in its argv; (b) still invoked once when the `get_app_token.sh` stub fails (the cycle exits at AUTH FAILED); (c) **not** invoked when the project is suspended; (d) **not** invoked when the lock is held by a live holder; (e) invoked before the usage-pause helper (ordering via a shared stub log); (f) stub rc=1 → cycle exit unchanged and `cycle-tmp-reap` audited; (g) stub `reaped=0` with rc=0 → no audit record; (h) a stub that sleeps past the bound is killed and the cycle continues, if `timeout` is available. |
| C3 | `tests/framework/test_consumer_framework_files.py`: `scripts/framework/tmp_reaper.py` is listed and exists. |

### S3

| ID | Asserts |
|---|---|
| T9 | `test_tmp_template_static.py`: none of the AC-14 literal-`/tmp` mktemp forms appear outside the allowlist. A self-test feeds each form (`/tmp/x.XXXX`, `-p /tmp`, `-p/tmp`, `--tmpdir=/tmp`, `--tmpdir /tmp`, `-t /tmp/x.XXXX`) through the matcher. |
| T10 | Existing gate and validator tests stay green. The inner loop stays green with G-leak covering the converted scripts. |

---

## 11. Files and slicing: one PR, three ordered commits (AC-15)

One PR. Each commit is green on the inner loop on its own, so the human can review commit by commit, and S1 can be cherry-picked out without a redesign if S2 draws objections.

| Commit | Files | Protected? |
|---|---|---|
| **1. S1: tests only (Layer 1)** | `pyproject.toml` (pytest ini); `tests/conftest.py`; new `tests/tmp_hygiene.py`; new `tests/framework/test_tmp_hygiene_plugin.py`, `tests/framework/test_tmp_hygiene_static.py`; the ~18 test files of §7.1; the §4.8 `child_env` sites; `tests/automation/test_dimension_sweep_cli.py` and `tests/automation/test_agent_invoke_wrapper.py` (§7.2) | No. **Sole permitted exception:** a script fix that §4.9 requires to keep this commit green. It is limited to TMPDIR correctness or a cleanup trap, and is named in the commit message and the PR body. |
| **2. S2: reaper and hooks (Layer 2)** | new `scripts/framework/tmp_reaper.py`; new `tests/framework/test_tmp_reaper.py`; `scripts/framework/run_tests_inner_loop.sh`; `bin/hos-cron` (cycle-start site); `scripts/framework/framework_consumer_files.txt`; `CLAUDE.md`; `docs/CRON-SETUP.md`; `tests/framework/test_run_tests_inner_loop.py`; `tests/automation/test_hos_cron.py`; regenerated `SCRIPTS-INDEX.md` / CODEOWNERS via `regen_all.sh` | Yes |
| **3. S3: literal-/tmp script fixes** | `scripts/oversight/run_validators.sh`, `scripts/oversight/gates/secret_scan.sh`, `scripts/oversight/gates/security_scan.sh`, `scripts/framework/validate_agents.sh`, `scripts/framework/validate_scripts.sh`, `bootstrap/hos_install.sh`; new `tests/framework/test_tmp_template_static.py` | Yes |

- **The PR as a whole** is protected-surface and human-gated (CODEOWNERS). The combined risk tier is HIGH, because of a scheduled recursive delete. Second review runs at HIGH (agy + codex) over the full diff, with an explicit `--tier HIGH`.
- In commit 2, the `allocated_bytes()` walk moves out of `tests/tmp_hygiene.py` into `tmp_reaper.py`. The plugin then loads it via `load_module_from_path` (one implementation, D41). Scripts never import from `tests/`.
- **One-time backlog.** The ~1371 leaked top-level entries on the dev host are removed by the first reaper run after merge, at the next cron cycle start, for every entry older than 24 h. A human may run `--dry-run` first. **Never delete them inline from an agent session.**

---

## 12. Open questions: resolved

| # | For | Question | Resolution |
|---|---|---|---|
| Q1 | human | Should class T reap regular files older than 24 h? | **YES** (human ruling, 2026-10-09). D12, §5.4. |
| Q2 | architect | Session-wide TMPDIR redirect? | **ACCEPTED** with AC-5/6/7/12. Breakage policy in §4.9. |
| Q3 | architect | Leak allowlist vs holding S1? | **Moot under a single PR.** `LEAK_ALLOWLIST` is empty at merge (AC-13). |
| Q4 | human | Budget value? | **50 MiB** (human, 2026-10-09), lower-only via env. |
| Q5 | architect | Reap on hos-cron early-exit paths? | **Moved to cycle start** as the single site (AC-8). Not on the suspended or lock-held exits. |
| Q6 | human | Large ad-hoc trees such as `/tmp/claude/hos1935`? | **Superseded: DELETE when stale** (later human ruling, 2026-10-09: *"We should have the cleanup script zap the large scratch copies if older than 24h"*). Class S (D13, §5.7), cron-only via `--scratch`, under the full §5.7 safety bar. Large entries outside the scratch roots stay report-only (`--measure`, AC-10). |
| Q7 | architect | Legacy `.lock` threshold? | **24 h ACCEPTED.** It is now the uniform D11 threshold. |

### 12.1 Open merge-time human confirmations (AC-16): do not block coding

Coding proceeds on the architect's recommended defaults below. The PR body must carry these as explicit checkboxes, and the human ticks them at merge review. If any is answered "no", the change it names is localized: a §5 policy constant or a §8 call site, with no redesign.

| # | Confirmation | Default implemented |
|---|---|---|
| (a) | The cron reaper acts on **all** of the user's `pytest-of-<user>` runs and `tmp*` orphans in the shared tmp root, and on stale class-S scratch trees under `<root>/claude/`, including other repos and projects of the same user. | Yes, all of the user's entries. Safety comes from §5.6 and §5.7, not from repo scoping. |
| (b) | The reaper ships **default-on to consumers** (`framework_consumer_files.txt` plus the `bin/hos-cron` call with `--scratch`): a new scheduled deletion on every consumer host, including class-S deletion of stale `/tmp/claude/*` trees. | Yes, shipped enabled. The human's class-S ruling was framed for this host; whether consumers get class S on by default is part of this confirmation. |
| (c) | The reaper runs at **cycle start** (AC-8), not at "cron-cycle wrap-up" as the issue says. | Cycle start. |
| (d) | (technical-design addition) Non-empty `tmp*` dirs are reported, never reaped (§5.4), even though the ruling says "anything over 24h". | Report only. |

---

## 13. Self-flag

RISK: HIGH. A scheduled path (`bin/hos-cron` cycle start, every lock-acquiring cycle) gains a recursive delete under the shared tmp root. It also unlinks regular files (D12), and, with `--scratch`, recursively deletes whole agent scratch trees that no test created (D13, the highest-consequence path). Safety rests on:
- the uniform 24 h age;
- a mandatory non-age signal;
- a live-process veto;
- kernel flock semantics on a dev/ino-verified inode;
- ownership and pattern allowlists;
- the refusal to run as root.

A wrong rule could delete a live run's working dir, or a file that a process in an invisible namespace holds open. That fails that run, but it cannot cross users.

CONFIDENCE: MEDIUM-HIGH.
- The pytest behavior was read from source, and the architect re-verified it.
- The cross-namespace flock behavior was verified by experiment.
- Unverified: the cause of the fifth dir (§1.3 item 4), and the full-suite effect of the redirect (Q2, which the coder verifies).

BLAST RADIUS: every pytest run in this repo (S1); every hos-cron cycle and inner-loop run in this repo and in consumer installs (S2); six gate, validator and installer scripts (S3).

Change classification (this revision): **clarifying + additive**. No design or code has been approved against the round-1 body, so no sign-off is orphaned.

## Human Review Required

- The PR touches protected surfaces (`bin/**`, `scripts/framework/**`, `scripts/oversight/gates/**`, `scripts/oversight/run_validators.sh`, `bootstrap/**`, `CLAUDE.md`). Human approval is mandatory under CODEOWNERS.
- Merge-time confirmations §12.1(a)–(d) are open.
- Q1 and Q4 are answered by the human ruling of 2026-10-09. Q6 is answered by the later human ruling (delete stale scratch trees, class S).

---

## Architect review (round 1 of 5, 2026-10-09)

**Verdict: APPROVED WITH CONDITIONS.** The overall approach is sound: D1 retention, D3 flock liveness, D4 private TMPDIR, D6 in-pytest gate, a pure `decide()`, and rename-then-rmtree. The conditions below fix two correctness defects (AC-1, AC-8) and several weaker points. technical-design applies them to the body. Coder handoff waits for that and for the architect's diff check.

### Evidence gathered this round

- **pytest 9.1.1 source** (installed venv). Three findings:
  - `wrap_session` returns `session.exitstatus` *after* `pytest_sessionfinish`, so §4.4's override is honored.
  - `make_numbered_dir_with_cleanup` creates `.lock` only when `keep != 0`. This confirms D2.
  - Under `failed`, `tmpdir.pytest_sessionfinish` rmtrees the basetemp on green **before** `_exit_stack.close()`. So the cleanup and `.lock` removal run inside `pytest_sessionfinish`, with atexit only as a fallback, not "only at exit" as §1.3 says. The effect in §1.3 is unchanged.
- **The flock crosses sandboxes. Verified by experiment** (scratchpad `flk/run.sh`; bwrap `--unshare-pid` with a new mount namespace and `/tmp` bind-mounted):
  - A holder inside bwrap blocks a probe from the host (`EAGAIN`).
  - A holder inside bwrap blocks a probe from a *second* bwrap sandbox.
  - A holder on the host blocks a probe from inside bwrap.
  - All views saw the same `dev=38 ino=…`.
  - SIGKILL of the holder released the lock.
  - A forked child that inherits the fd keeps the lock after its parent is SIGKILLed. That is fail-safe (it keeps the dir).
  - The holder's in-namespace PID was `2`, which confirms #1616 for `.lock` PIDs.
  - The guarantee depends on the sandbox **bind-mounting** the host tmpfs. An overlay or private tmpfs would put a different inode behind the same path. Indirect evidence says it is a bind: sandboxed cron runs appear at the host path `/tmp/pytest-of-scott`. AC-4 turns that assumption into a check.
- **EDQUOT and placement.** Under a full quota `get_app_token.sh` fails, and `bin/hos-cron` exits 0 at "AUTH FAILED" long before wrap-up. That is AC-8.

### Rulings on the open questions

- **Q2 (session TMPDIR redirect): ACCEPTED**, with AC-5, AC-6, AC-7 and AC-12.
  - The coder fixes *tests* when they break.
  - If a **script** breaks only because `TMPDIR` is not `/tmp`, that is a real portability defect, since consumers set TMPDIR. The PR is a protected-surface PR anyway (AC-15), so the coder may fix that script in this PR. The fix must be limited to TMPDIR correctness, and the PR body must list it.
  - The coder must **never** neutralise the redirect for a test (for example `monkeypatch.setenv("TMPDIR", "/tmp")`). Any other kind of script break: stop and escalate.
- **Q3 (leak allowlist vs hold S1): moot under a single PR.**
  - `LEAK_ALLOWLIST` must be **empty at merge**, and T7 asserts that unconditionally. Delete the "temporary, protected-producer, S3-tracked" carve-out (AC-13).
  - Note: today's literal-`/tmp/` scripts *escape* the redirect, so they never trip G-leak. It is S3's conversion to `${TMPDIR:-/tmp}` that brings them into view. Any leak that conversion exposes is fixed with a trap in the same PR, never allowlisted.
- **Q5 (early-exit paths): YES, but as a move, not an addition.**
  - Wrap-up is the wrong site. The quota-full condition kills the cycle at auth, so a wrap-up-only reaper can never recover the state it exists to fix. Reaping at wrap-up also gains nothing, because `--min-age-hours 2` means the next cycle start can reap the same set.
  - Use one cron call site: after the overlap lock is acquired and `_audit` is defined, and before the usage-pause gate, preflight and auth (AC-8).
  - Not on the suspended exit (a human said stop) or the lock-held exit (the holder reaps).
- **Q7 (24 h legacy-lock threshold): ACCEPTED**, with AC-3.
  - After D1, a killed run's dir holds only session-scoped fixtures and the in-flight test. So the 72 h→24 h change matters less for bytes and is mainly about bounding pinned dirs.
  - 24 h is safe given the positive-live evidence that AC-3 extends.

### Binding conditions

- **AC-1: correctness, the §5.3 rule 2/4 conflict.** Under S1, every *finished* red run keeps its `.hos-live`, unlocked, inside its retained basetemp. As written, rule 2 reaps it as `dead-flock` after 2 h, so rule 4's "KEEP newest" never fires for this suite's runs. That defeats count=1's inspection intent.
  - Fix: on a successful probe, REAP `dead-flock` **only if `.lock` is present** (a killed run).
  - If `.lock` is absent, the run finished normally. Go to rule 4.
  - Add a test: a red finished dir with `.hos-live` and no `.lock`, backdated 48 h, newest → KEEP.
- **AC-2: rule 4 threshold.** REAP `finished` needs quiet ≥ `--legacy-lock-hours` (24 h), not `min-age`, plus no positive-live evidence (AC-3). A live run from a non-HOS repo of the same user, running with `policy=none`, has neither `.lock` nor `.hos-live`. At 2 h it would be deleted. pytest's own keep=1 cleanup already handles the common case.
- **AC-3: positive-live evidence, extended.** Reuse the single per-invocation `/proc` scan from §5.4. If any visible process has `cwd`, `root` or an open fd that resolves under a class-P candidate → `SKIP live-proc`. This applies to rules 3 and 4.
  - From the host cron this sees the sandboxed processes as well.
  - From inside a sandbox it is absent. Absence is never evidence of death, which is unchanged.
- **AC-4: inode identity and safe probe.**
  - §4.2 writes `dev=<st_dev> ino=<st_ino>` (from `fstat` of its own fd) into `.hos-live`.
  - The reaper opens `.hos-live` with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` and calls `fstat`. It requires `S_ISREG`, the current uid as owner, and a `dev`/`ino` that match the recorded values.
  - Any mismatch, unreadable content or open error → `SKIP unknown`. This makes the bind-mount assumption a checked fact. Under an overlay the `st_dev` differs.
  - Tests: a mismatched record → SKIP; a FIFO named `.hos-live` → SKIP with no hang.
- **AC-5: per-session plugin state.** Keep all state (`fd`, `session_tmp`, `basetemp`, saved `TMPDIR`/`tempdir`, report) in `config.stash`, never in module globals. In-process nested `pytest.main` (T6, mutmut) would otherwise overwrite the outer session's fd and paths. T6 must assert that the *outer* session's state is intact after an in-process inner run.
- **AC-6: restore timing.** `tmpdir.pytest_sessionfinish` deletes `session-tmp` on green while `TMPDIR` and `tempfile.tempdir` still point at it. Any later hook or plugin that calls `tempfile` would then fail.
  - Restore both inside the tryfirst `pytest_sessionfinish`, immediately after measuring.
  - `pytest_unconfigure` releases the flock, and restores only if the values were not already restored (the fallback for sessions that never reached finish).
  - Update §4.5 and T6.
- **AC-7: gate determinism.** It is mandatory, so flakiness is unacceptable.
  - Call `gc.collect()` before measuring. `TemporaryDirectory` objects reachable only through reference cycles are otherwise cleaned at GC time, and that timing is non-deterministic.
  - The gate is never retried, never marked xfail/flaky, and has no sleep or poll. Every leak line names a path, so any recurrence is fixed at its producer.
  - The private 0700 `session-tmp` is the right design (§6.1's rejection of a /tmp delta stands).
- **AC-8: Q5 placement, correctness.**
  - Replace §8.2's wrap-up placement with a single call site in `bin/hos-cron`: after the overlap lock and the `_audit` helper, and before the usage-pause gate and preflight.
  - Not on the suspended or lock-held exits.
  - Remove the wrap-up call (one site, D41).
  - Rewrite C2:
    - invoked exactly once per lock-acquiring cycle, including when the `get_app_token.sh` stub fails;
    - not invoked when suspended or lock-held;
    - rc≠0 never changes the cycle exit;
    - the audit rule is unchanged.
  - Update §8.4 (`CRON-SETUP.md`) to match.
- **AC-9: dedicated bound.**
  - Do not reuse `_UP_BOUND`, which belongs to the #1944 usage-pause schema block. Its 60 s outer limit equals the proposed inner `--max-seconds 60`, so it is a race.
  - Define a reaper-owned bound: `timeout`/`gtimeout --kill-after=5 30`, with an inner `--max-seconds 20`. Inner must be strictly less than outer.
  - The inner loop uses the same `--max-seconds 20`.
- **AC-10: per-cycle cost.**
  - The `user_bytes` walk and the `WARN large-unowned` walk run **only** under `--measure`. The current trees are 390k inodes, plus `/tmp/claude` at 548 MB, so walking them on every cron fire is unacceptable.
  - Default and `--summary-only` runs print `user_bytes=-`. The §5.5 regex accepts `-`.
  - Byte counts on `REAP` lines cover only the candidate itself.
- **AC-11: restate R-2 honestly.**
  - "At most one unlocked `pytest-N`" holds only for **sequential** sessions.
  - Under overlap, two concurrent red sessions both survive. Also, a later-numbered session's exit cleanup may delete an earlier finished red dir, which loses evidence that someone may have wanted to inspect. That is acceptable, because the #1903 failure log is the inspection artifact.
  - The count is bounded by the number of overlapping red sessions and converges at the next completed session.
  - T1 asserts the sequential cases only. No test asserts a concurrent retention invariant.
- **AC-12: escapes through scrubbed envs.**
  - About 93 `env={…}` / `env = {…}` sites in `tests/` build subprocess environments from scratch, so their children write to the real /tmp, which the gate cannot see.
  - The coder audits them and passes `TMPDIR` through one test helper wherever the child may create temp files. The PR body reports the residual count.
  - This is not a gate. The §9 `empty_tmp_dirs` evidence is the backstop.
- **AC-13: allowlist semantics.** The `LEAK_ALLOWLIST` entry types are `(glob, producer, reason, issue)`. They are permitted only for a deterministic third-party tool artifact that the test cannot suppress through env. The list is empty at merge (Q3).
- **AC-14: static-scan breadth.**
  - D10's AST scan also resolves `from tempfile import mkdtemp/mkstemp/NamedTemporaryFile` aliases.
  - It catches `delete=False` as a keyword.
  - T9 also catches `mktemp -p /tmp`, `mktemp --tmpdir=/tmp` and `-t` forms, as well as templates that begin with `/tmp/`.
- **AC-15: slicing. A single PR is approved.** One PR contains S1, S2 and S3 as **three ordered commits**, each green on the inner loop. The human can then review per commit, and if S2 draws objections, S1 can be cherry-picked out without a redesign.
  - Cost:
    - The whole PR becomes protected-surface and human-gated, so S1 can no longer auto-merge.
    - The combined risk is HIGH (a scheduled recursive delete), so second review runs at HIGH, agy plus codex, over the full diff.
    - The human reviews roughly 30 files once instead of twice.
  - S3 inside the same PR removes the need for any temporary allowlist (Q3).
- **AC-16: product and policy boundary.** This gates merge, not coding. The human must explicitly clear three things now, recorded in the PR body:
  - (a) The cron reaper acts on **all** of the user's `pytest-of-<user>` runs and `tmp*` orphans in the shared tmp root, including runs from other repos and projects of the same user.
  - (b) The reaper ships **default-on to consumers** (`framework_consumer_files.txt` plus the `bin/hos-cron` call). That is a new scheduled-deletion behavior on every consumer host.
  - (c) The cycle-start placement (AC-8) departs from the issue's wording, "cron-cycle wrap-up".
  - Q1, Q4 and Q6 remain human items as the TD states.

### What still could go wrong (accepted residuals)

- A test that leaves a background process writing into `session-tmp` after its own teardown would make G-leak timing-dependent. That is a real test defect. AC-7's named-path report makes it attributable. It is not a design flaw.
- If the reaper runs inside a PID-namespaced sandbox (the inner loop), it cannot see host processes, so AC-3 evidence is absent there. Safety then rests on the flock (rule 2) and the 24 h thresholds (rules 3 and 4), which is fail-safe by construction.
- Q1 (reaping regular class-T files): a file held open in a namespace that the sandboxed reaper cannot see may be unlinked. The holder keeps its data through the fd. This risk is for the human to accept or reject.

**Affected sign-offs:** none. No design or code has been approved against this TD yet.

---

## Round-2 revision note (technical-design, 2026-10-09)

The body above was revised to apply every round-1 condition and the human ruling. The architect review above is kept verbatim as the round-1 record. Change classification for this revision: clarifying + additive. No structural change was made: every contract in the body was refined, not replaced. No sign-off exists against round 1, so none is orphaned.

**Startup-artifact-gap check.** Should this have been settled in the initial design? Yes for AC-1 (rule 2/4 conflict) and AC-8 (wrap-up cannot recover a full quota). Both were caught in architect review before any code was written, so no `startup-artifact-gap` issue is needed and no sign-off needs re-review.

### Human ruling (2026-10-09)

| Ruling item | Applied in |
|---|---|
| Normal cleanup when the run completes is the **primary** mechanism | New §0 headline (Layer 1 = retention + redirect + leak fixes + guardrail); §1.3 tail; §9 split into Layer 1 and Layer 2 evidence |
| A script that cleans anything over 24 h is a **backstop** | §0 Layer 2; D11 makes 24 h the single uniform threshold (`--min-age-hours`, default 24, raise-only, < 24 → exit 2). The 2 h `min-age`, `--legacy-lock-hours` and `--orphan-min-age-hours` are removed. Applies to dead-flock, legacy, finished and `garbage-*` dirs and to class-T files and empty dirs (§5.3.2, §5.4). Tests R2, R8, R9 and R18 |
| Safety checks stay on top of age | §5.6: every REAP needs age **and** a non-age signal **and** survival of the live-process veto. Flock, `.lock` and `/proc` evidence are all kept |
| Q1: reap leaked regular files | D12, §5.4 (`REAP file`, with re-lstat identity check). Test R8 |
| Q4: 50 MiB | D6, §4.6, §6.3 marked human-confirmed |
| ~~Q6: report-only large trees~~ **superseded** | See the "Later human ruling: Q6" section below |
| AC-16 items stay OPEN merge-time confirmations | §12.1 (a)–(c) with the implemented defaults; coding proceeds on them |
| (TD addition) | §12.1(d): non-empty `tmp*` dirs are reported, not reaped. This needs the human's confirmation, because the ruling says "anything over 24h" and recursive deletion on age alone is the riskiest operation |

### Architect conditions

| AC | Applied in |
|---|---|
| AC-1 | §5.3.2 rule 2: a successful probe reaps `dead-flock` only with `.lock` present; with `.lock` absent it goes to rule 4. §4.5 note updated. Test R15 |
| AC-2 | §5.3.2 rule 4: `REAP finished` needs quiet ≥ 24 h (uniform AGE) plus the veto. NEWEST_FINISHED is computed over all lock-free dirs regardless of age, so a young newest dir does not cause an older one to be kept as well |
| AC-3 | §5.3.2 rule 5 and §5.3.3: a single lazy `/proc` index (cwd, root, fds, cmdline). The veto is applied to rules 3 and 4, and also, as a stricter choice, to rule 2 and `garbage-*`. A truncated scan → `SKIP proc-scan-incomplete`; absent `/proc` → no veto. Tests R3, R7 and R17 |
| AC-4 | §4.2 record `pid start dev ino` from fstat; §5.3.1 probe with `O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK\|O_CLOEXEC`, requiring S_ISREG, uid and dev/ino match, else SKIP unknown. Tests T5 and R16 (mismatch, FIFO with no hang, symlink) |
| AC-5 | §4.2: all state in `config.stash` under a `StashKey`, no module globals. Test T6 asserts the outer state, TMPDIR and flock are intact after an in-process inner run. §4.7 adds the nested-session basetemp rule |
| AC-6 | §4.4 step 4 restores immediately after measuring; §4.5 restores only if `restored` is false, then releases the flock. T6 checks the restore from a `trylast` hook |
| AC-7 | D6 and §4.4 step 2 (`gc.collect()`); no retry, xfail, sleep or poll. T2 covers the reference-cycle case |
| AC-8 | D5 and §8.2: one site, after `_audit()` and before the usage-pause gate (so after the overlap lock and before preflight and auth); not on suspended or lock-held exits; wrap-up call removed. C2 rewritten (a)–(h); §8.4 CRON-SETUP updated |
| AC-9 | §8.2: dedicated `_TR_BOUND` (`timeout`/`gtimeout --kill-after=5 30`), inner `--max-seconds 20`; §8.1 inner loop also uses 20; `_UP_BOUND` is not reused. C1 and C2(h) |
| AC-10 | §5.1, §5.4, §5.5: the `user_bytes` and `WARN large-unowned` walks run only under `--measure`; otherwise `user_bytes=-`, and the regex accepts it. REAP byte counts cover the candidate only. Test R19 |
| AC-11 | §3 R-2 restated for sequential sessions only, with the overlap behavior and convergence spelled out. T1 asserts sequential cases only. §1.3 item 2 also corrected per the architect's pytest-source evidence (cleanup runs in sessionfinish/exit stack, atexit as fallback) |
| AC-12 | New §4.8: `tests.tmp_hygiene.child_env()`; audit of the ~93 scrubbed-env sites with audited/converted/residual counts in the PR body; not a gate. Test T11 |
| AC-13 | §4.6: entries are `(glob, producer, reason, issue)`, third-party-tool artifacts only, never repo producers; empty at merge, asserted unconditionally in T7 |
| AC-14 | D10 and T7: alias-aware AST scan, `delete=False` as a keyword. §7.3 and T9: `-p /tmp`, `-p/tmp`, `--tmpdir[=| ]/tmp`, the `-t` operand and `/tmp/` templates, with a matcher self-test |
| AC-15 | §11: one PR, three ordered commits (S1 tests-only with one named exception, S2 reaper + runner/cron hooks + CLAUDE.md + consumer files, S3 literal-/tmp script fixes), each green; whole PR HIGH and human-gated; second review at explicit `--tier HIGH` |
| AC-16 | §12.1 (a)–(c) recorded as open merge-time confirmations with defaults; PR-body checkboxes required |

Also folded in: the Q2 ruling as §4.9, including the T7 ban on `monkeypatch.setenv("TMPDIR", "/tmp")`. Q3, Q5 and Q7 are recorded as resolved in §12.

### Later human ruling: Q6 (2026-10-09). Supersedes the report-only default

Human, verbatim: *"We should have the cleanup script zap the large scratch copies if older than 24h."* The round-2 draft above it had applied Q6 as "report only", and that is now superseded. Applied as follows.

| Requirement (from the ruling as relayed) | Applied in |
|---|---|
| Delete large ad-hoc scratch trees older than 24 h | D13; new class S, §5.7; §0 Layer 2; D11 extended; §5.4 large-entry bullet narrowed to non-scratch entries; §12 Q6 row |
| Age = newest mtime anywhere in the tree; bounded walk; truncated → skip | §5.7.4 step 5. Uses `max(mtime, ctime)`, which is stricter than mtime alone. Early exit on the first fresh entry. Bounds are `SCRATCH_MAX_INODES` and `--max-seconds`; a truncated walk gives `SKIP walk-truncated`. A top-level pre-filter can only skip |
| User-owned, same device, no symlink traversal | §5.7.4 steps 1 and 5 (per-entry uid and `st_dev`; lstat only; symlinks never followed); §5.7.2 scratch-root realpath-equality check |
| No live-process evidence (cwd, root, open files); a held lock inside → live | §5.7.4 step 4 (index of cwd, root, exe and fds; **complete index required**, §5.7.1); step 5 locks via `/proc/locks` (flock, POSIX, OFD) plus a flock probe of lock-named files |
| Never touch Claude Code session dirs or anything under a live session; say how they are recognised | §5.7.3 five layers: the `claude-<uid>` root is never a scratch root; a `claude-\d+` child is skipped; a `scratchpad` dir or UUID-named dir marks a tree as session-like; trees containing the reaper's own cwd or TMPDIR are skipped; the live-process veto |
| Explicitly scoped roots/patterns | §5.7.2 closed `SCRATCH_ROOTS = ("claude",)`, directory children only. Changing it is a code change to a protected surface. Never arbitrary `/tmp` |
| Same rename-to-garbage, dev/ino re-check, symlink-safe rmtree | §5.7.4 step 7: re-check **after** the rename; a mismatch means no rmtree |
| Tests: stale removed; recent deep file kept; cwd kept; held flock kept | RS1, RS2, RS3, RS4 (plus a POSIX-lock variant). Further tests: RS5–RS10 (symlinks, session dirs, truncation, run-level gating, identity re-check, pure decide) |

Design choices that go beyond the ruling, flagged for the architect:
- **Cron-only opt-in.** `--scratch` is passed only by `bin/hos-cron` (§8.1, §8.2), and there is a run-level host-PID-namespace check (§5.7.1). Reason: the inner loop can run inside bwrap, where a live session's processes are invisible. For a recursive delete of non-test trees, absent evidence must never count as dead.
- **Size is not a criterion.** Any stale directory child of a scratch root qualifies, not only "large" ones. Size is not a safety signal, and the safety bar is identical either way. If the human wants a size floor, it is one constant.
- §12.1(a) and (b) are widened to name class S. §12.1(d), non-empty `tmp*` dirs at the `/tmp` top level, is **unchanged and still open**: this ruling covers only the scratch roots.

Requesting the architect's round-2 diff check (round 2 of 5).
