# Technical Design — #2054 test runs exhaust the per-user /tmp quota

Status: **Architect round 3 (2026-10-09): APPROVED WITH CONDITIONS R3-1..R3-6** (see "Architect review (round 3 of 5)" at the end).
- **S2a and S2b are ready for the coder now.** R3-1..R3-6 are binding and fully specified, and **where they conflict with the body, they govern**.
- **R3-1..R3-6 are now folded into the body** (see "Round-3 fold-in note" at the end). The body and the conditions agree.
- technical-design disputes no condition, so no round 4 is required.
- The code-reviewer checks conformance to R3-1..R3-6.
- The R3-2 follow-up is #2056 (milestone v0.7.4, Sandboxing & Isolation).

Previous status: **Round 3 revision (2026-10-09), restructured.**

Applied to the body:
- the architect's round-2 conditions R2-1..R2-8;
- the human's §12.1 rulings ("Yes. Anything older than a day goes."), which override R2-3 and R2-4 and drop R2-1's git veto;
- the human's packaging ruling, which makes the reaper a machine-level `bootstrap/` script that the operator installs in cron;
- the human's **disk-temp ruling**: HOS temp moves off the RAM-backed `/tmp` to a hidden, per-role disk root, `<clone>/../.tmp/<role>`.

The disk-temp ruling moves the design's centre of gravity, so §0 and §2 are restructured and a new §2A is added.

The "Round-3 revision note" at the end maps every change and lists which architect conditions are superseded or amended. Next step: the architect's round-3 diff check.

Coder status:
- **Commit 1 (S1) is unchanged** and remains ready for the coder (see §11).
- Commit 4 (S3, formerly commit 3) is unchanged in content and remains ready.
- Commits 2 (S2a, disk temp root) and 3 (S2b, reaper) go to the coder only after the architect approves round 3.

§12.1 is fully resolved.

Round-2 architect status: **APPROVED WITH CONDITIONS R2-1..R2-8** (see "Architect review (round 2 of 5)").
Earlier status: **Round 2 revision (2026-10-09).** Applied the architect's round-1 conditions AC-1..AC-16 and the human rulings of that date (see "Round-2 revision note").
Issue: #2054 (bug, blocks work). Being fixed in a human-authorized interactive Worker session on 2026-10-09.
Related: #1616 (sandbox PID namespaces break `kill -0`), #1903 (`--failure-log` in literal /tmp), #1910 (wrapper replica), #1221 (sandbox config generation), #1146 (worker/overseer sandbox), #314 (decision logic belongs in Python), D41 (one invocation site).
Change class: **additive**, with three human-ruled behavior changes:
- **Where HOS temp lives.** The launchers export `TMPDIR=<HOS_TMP_ROOT>/<RoleDir>`, a 0700 dir on disk (D14, §2A). The sandbox template grants each role only its own dir.
- **The test-environment TMPDIR redirect** (D4). It now nests under the role dir. The architect accepted it (Q2).
- **A machine-level deletion script**, `bootstrap/tmp_reaper.py` (D5). It runs from:
  - a daily operator-installed crontab entry that HOS documents and never installs;
  - a low-space trigger at `bin/hos-cron` cycle start;
  - the inner-loop pre-run.

---

## 0. Headline: HOS temp lives on disk per role, every test run cleans up after itself, and a reaper backstops both

**Human rulings (2026-10-09, verbatim):**
- *"We need to clean up the files. Can we make sure that they are normally cleaned up when the test run completes and have a script that cleans anything over 24h just in case?"*
- *"RAM for pytest results etc is silly."* (`/tmp` here is a 1.7 GB tmpfs with `usrquota`, on a host with 14 GiB of RAM.)

The design has three layers. The order is deliberate.

### Layer 0: placement. HOS temp is on disk, per role, outside every work tree (S2a, §2A)

- `HOS_TMP_ROOT` is a `config.sh` setting chosen at install time.
  - The default is the hidden `<clone>/../.tmp`, which here is `~/Code/HumanOversightSystem/.tmp`. That matches the sibling `.local/handoff/<role>` and `.config/hos` convention.
  - Each role gets `$HOS_TMP_ROOT/<RoleDir>`, mode 0700.
- `bin/hos-cron` (worker, overseer) and `bin/hos-human` (human) export `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` to that dir (R3-1).
  - `CLAUDE_CODE_TMPDIR` is what reaches **sandboxed** Bash, where Claude Code overrides `TMPDIR`.
  - `run_tests_inner_loop.sh` resolves its own dir in a fixed order (§2A.3).
  - pytest's `pytest-of-<user>`, Python `tempfile` and `mktemp` all follow `TMPDIR`, so pytest results no longer consume RAM or the `/tmp` quota.
- **Role separation (R3-2).** No role's sandbox is granted another role's temp dir, and `.tmp` itself is never granted as a shared writable dir. This is a temp-dir separation, not a role-integrity boundary: the pre-existing cross-clone write grants are out of scope, and are tracked in #2056.
- **What stays on `/tmp`:**
  - small agent draft files in `/tmp/claude/…`, because CLAUDE.md mandates those literal paths for allowlisting;
  - the `${TMPDIR:-/tmp}` fallback, when no root is configured or the session was not started by a launcher.
- **What moves:** in launched sessions, Claude Code's own `claude-<uid>` dir moves into `.tmp/<RoleDir>/`, via `CLAUDE_CODE_TMPDIR` (R3-5).

### Layer 1: primary, in-run cleanup (S1, unchanged)

Every pytest run that completes removes what it created. "Completes" means the session reaches `pytest_sessionfinish`: green, red, or interrupted by a Ctrl-C that pytest handles. There are four mechanisms, all inside pytest, and all now operating inside the role's disk dir:

1. **Retention (D1).** A green run deletes its whole `pytest-N` at session end. A red or interrupted run keeps at most the newest failed dir (count=1).
2. **Session TMPDIR redirect (D4).** Anything the run or its subprocesses put in temp space lands inside that run's own `pytest-N`, which is now under `$HOS_TMP_ROOT/<RoleDir>/pytest-of-<user>/`. The same deletion removes it.
3. **Leak fixes at the source (§7.1, §7.3).**
4. **Mandatory guardrail (D6).** A green run that leaves any temp entry behind, or whose basetemp footprint exceeds 50 MiB, **fails**. The footprint is now measured on the disk root, because basetemp lives there.

### Layer 2: backstop, the machine-level script `bootstrap/tmp_reaper.py` (S2b)

The reaper removes what Layer 1 cannot:
- runs killed by SIGTERM or SIGKILL;
- leaks from before this fix, including the `/tmp` backlog;
- leaks from other repos of the same user (§12.1(a));
- stale class-S trees: agent scratch clones under `/tmp/claude/`, and non-empty `tmp*` dirs (D13, §5.7).

Class S has **no size floor** and does **not** spare unpushed git work (§12.1(d)–(f)). It is **on by default**; `--no-scratch` opts out.

The reaper sweeps `/tmp` **and** every HOS tmp root it is given (`--root`, `--hos-tmp-root`, §5.1). It runs from:
- a **daily** operator-installed crontab entry (§8.2), which HOS documents and never installs;
- a **low-space trigger**: at `bin/hos-cron` cycle start, a write probe of the role's `TMPDIR` and of `/tmp` runs the reaper only when a write fails with EDQUOT/ENOSPC (§8.5). `df` is unreliable under `usrquota`;
- the **inner-loop pre-run**, for classes P and T only (§8.1).

It removes **only entries older than 24 h** (D11), with **no exceptions** (R3-3, human ruling "Anything older than a day goes"). The only window for inspecting a failed run is Layer 1's pytest `count=1` retention, which lasts until the next completed session. Age is **never sufficient alone**. Every removal also needs liveness evidence that the entry is dead (§5.6):
- a dead flock;
- no live process with a cwd, root, exe or open fd under it;
- no held lock;
- for class S, a host view of processes and locks, the session-dir exclusions, and the dev/ino re-checks.

**Residual (human item 8).** On a real disk, the failure mode becomes **disk exhaustion** rather than quota exhaustion. That is a worse blast radius, because the root filesystem has no per-user quota. The D6 guardrail (per session), the daily reaper and the low-space trigger all still apply. See §2A.6.

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

### 1.4 Placement: the fourth gap (round 3, disk-temp ruling)

Gaps 1–3 bound *how much* a run leaves behind. The disk-temp ruling adds a fourth gap: *where* it goes. All HOS test temp lands in a 1.7 GB RAM-backed tmpfs shared with every same-user writer, so even a bounded footprint competes with the token mint and the Claude sessions for one small quota. Layer 0 (§2A) moves HOS temp to a per-role disk dir. After that, the `/tmp` quota carries only:
- drafts and Claude Code's own dirs;
- the legacy backlog;
- consumers or tools that have no `TMPDIR`.

Everything in §1.1–§1.3 still applies inside the disk dir, so Layers 1 and 2 are unchanged in purpose.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `tmp_path_retention_policy = "failed"` and `tmp_path_retention_count = "1"` in `pyproject.toml`. | `failed` removes each passing test's `tmp_path` at teardown. It removes the whole basetemp at session end when the exit status is 0. `count=1` keeps only the newest numbered dir. |
| D2 | **Reject `policy = "none"`.** | `none` forces `keep=0`, and with `keep=0` pytest **creates no `.lock`** (architect verified this). A concurrent session's cleanup would then see a live dir as deletable and `rm -rf` it mid-run. Worker, overseer and interactive runs overlap, so `count ≥ 1` is load-bearing. |
| D3 | A **liveness flock** per session. A root-conftest session fixture opens `<basetemp>/.hos-live`, holds `fcntl.flock(LOCK_EX)` until `pytest_unconfigure`, and records `pid`, `start`, `dev` and `ino` (AC-4). It touches the file at each test start (heartbeat). All per-session state lives in `config.stash` (AC-5). | Kernel flocks belong to the open file description and the inode. They work across PID namespaces and bind mounts of the same tmpfs, and the kernel releases them on holder death, SIGKILL included. The architect verified this in both directions, host↔bwrap and bwrap↔bwrap. The recorded `dev`/`ino` turns the bind-mount assumption into a checked fact. |
| D4 | **Session TMPDIR redirect.** The fixture sets `os.environ["TMPDIR"]` and `tempfile.tempdir` to `<basetemp>/session-tmp`. Both are restored **inside the tryfirst `pytest_sessionfinish`, right after measuring** (AC-6). `pytest_unconfigure` restores only as a fallback. | Every in-process `tempfile.*` call and every subprocess `mktemp` / `${TMPDIR:-/tmp}` lands in a single-writer dir owned by this session. A completed green run deletes it with basetemp, which is Layer 1. Restoring before pytest deletes the dir means no later hook ever sees a dangling TMPDIR. |
| D5 | **One machine-level reaper script**, `bootstrap/tmp_reaper.py`, shipped with HOS. It is Python and stdlib-only, and it is **not** a scheduler and **not** a per-project cycle step (human ruling 2026-10-09: *"The script will be a script per machine, so it should be shipped with HOS and consumer can install it in cron if needed."*). It has exactly three invocation paths:<br>(1) a **daily operator-installed per-machine crontab entry** (§8.2), documented but **never auto-installed**;<br>(2) `run_tests_inner_loop.sh` before the suite, bounded and best-effort, with `--no-scratch` (§8.1);<br>(3) the **low-space trigger** in `bin/hos-cron` at cycle start, which reaps only when a write probe fails (§8.5, disk-temp ruling).<br>`bin/hos-cron` has no unconditional reap. | Decision logic stays in Python (#314).<br>**Why `bootstrap/`:** it is the repo's copy-to-machine bundle (CLAUDE.md: "the only thing you copy to a machine"), home of the machine-scope tools `hos_bootstrap.sh` and `setup_clis.sh`. `scripts/framework/` holds per-project pipeline and framework-dev tooling, and `bin/` holds the per-project cron launchers. `bootstrap/**` is a protected surface, so a file-deleting tool stays human-gated. It already has a section in `framework_consumer_files.txt`, so consumers receive it.<br>This supersedes the issue's "call it from cron-cycle wrap-up, not as a new scheduler", and AC-8's cycle-start placement: the human wants an operator-installed machine cron entry. A per-machine tool also fits a per-user tmpfs quota, which is machine-wide, better than N per-project cycle hooks. |
| D6 | **Mandatory guardrail inside pytest** (root `tests/conftest.py`). At `pytest_sessionfinish` (tryfirst), on a run that would otherwise pass: (G-leak) any entry left in `<basetemp>/session-tmp` fails the session; (G-budget) allocated bytes under basetemp above **50 MiB** fail the session. `gc.collect()` runs before measuring. There is no retry, no xfail and no sleep or poll (AC-7). | It runs on every pytest invocation, so it is mandatory by construction. It measures a private single-writer dir, so it is deterministic. The human confirmed 50 MiB (Q4). |
| D7 | The budget can be **lowered only**, through `HOS_TEST_TMP_BUDGET_MB`. Values above 50, or non-integer values, are ignored with a warning. | Same precedent as #985 and #1718 D3. Raising the budget would recreate #2054. |
| D8 | Measure **allocated** bytes (`st_blocks × 512`), not apparent size. Count each inode once (hardlinks), and never follow symlinks. | The tmpfs quota counts allocated pages. |
| D9 | Shrink the repo-replica fixtures: a template repo per module plus `git clone --local` per test (§7.2). | Peak footprint and speed. |
| D10 | Ban direct temp-path creation in tests: `tempfile.mkdtemp`, `tempfile.mkstemp`, and `NamedTemporaryFile(…, delete=False)`. The ban covers every import and alias form (AC-14). A static test enforces it. | This turns the §1.2 leak classes into a deterministic failure. `TemporaryDirectory()` stays allowed. |
| D11 | **The reaper uses one uniform age threshold: 24 h** (`--min-age-hours`, default 24, **raise-only**; a value < 24 is a usage error). It applies to every category the reaper removes: pytest run dirs (dead-flock, legacy-lock, finished), `garbage-*` dirs, `tmp*` regular files, empty `tmp*` dirs, and class-S scratch trees, where age is taken over the whole tree (D13). **Age is never sufficient alone.** Every removal also needs a non-age signal (§5.6), and a live-process veto applies to all of them (AC-3). | This is the human ruling ("anything over 24h"). It replaces round 1's 2 h `min-age` and its separate `legacy-lock` / `orphan-min-age` knobs. One threshold means one rule to review. Making it raise-only stops a caller from turning the backstop into an aggressive deleter. |
| D12 | **Class T reaps leaked regular files**, not only empty dirs (Q1, human: YES). | The ~960 `/tmp/tmp.XXXXXXXXXX` files are exactly the backlog the human asked to remove. The source leaks are fixed in S1, so in steady state this is backstop only. The residual risk that the architect noted, a file held open in a namespace the reaper cannot see, is accepted by the ruling and is narrowed by the 24 h age. |
| D13 | **Class S: stale trees are deleted whole** (human rulings: Q6, and §12.1(d)/(e): *"Anything older than a day goes."*). There are two eligible shapes (§5.7.2): directory children of the fixed scratch roots (`<root>/claude/*`, in practice `/tmp/claude/*`), and **non-empty** `tmp*` dirs directly under each reaped root. There is no size floor, and git state is not inspected.<br>A tree is removed only if **every** §5.7 liveness condition holds:<br>(1) the newest `max(mtime, ctime)` *anywhere in the tree* is ≥ 24 h old, from a bounded walk that skips the tree if truncated;<br>(2) every entry is uid-owned and on the same device, and no symlink is followed;<br>(3) no readable process has a `cwd`, `root`, `exe` or open fd under the tree;<br>(4) no lock inside the tree is held;<br>(5) the tree is not, and does not contain, a Claude Code session dir or the reaper's own cwd/TMPDIR;<br>(6) the walked dev/ino identity is unchanged at removal.<br>Class S is **on by default** (`--no-scratch` opts out). It runs only when the reaper has the host PID-namespace view. | This is the most destructive operation in the script: a recursive delete of a tree no test created. "Older than a day" relaxes only the *age and scope* rules; every *liveness* check stays. The host-view requirement is load-bearing, because `/proc/locks` is namespace-filtered. A per-machine crontab runs unsandboxed and has that view. A sandboxed call does not, so class S refuses there. |
| D14 | **HOS temp moves to disk, per role** (human ruling, 2026-10-09: *"RAM for pytest results etc is silly."*).<br>• `HOS_TMP_ROOT` is a `config.sh` setting chosen at install time. Its default is the hidden `<clone>/../.tmp`.<br>• Each role uses `$HOS_TMP_ROOT/<RoleDir>` with mode 0700. `<RoleDir>` is the **capitalised** dir name for the role (human ruling: match the clone dir names): `worker` → `Worker`, `overseer` → `Overseer`, `human` → `Human`, `local` → `Local`.<br>• The launchers export `TMPDIR` to that dir (§2A). | `/tmp` is a 1.7 GB RAM-backed tmpfs with `usrquota`, which is the root cause of #2054's EDQUOT. Moving pytest, `tempfile` and `mktemp` output to disk removes HOS test temp from the quota entirely. Layers 1 and 2 still bound growth. Per-role dirs keep the overseer's inputs separate from the worker's outputs. |
| D15 | **One new *derived* token `__ROLE_DIR__`, and no new root placeholder.**<br>• The template grants `__HOS_ROOT__/.tmp/__ROLE_DIR__`, which renders to `<HOS_ROOT>/.tmp/Human` for the human role. That is the capitalised shape the human is adding by hand.<br>• **`__ROLE_DIR__` instead of literal per-role entries.** The single template is rendered per role. Literal entries copying the `__HOS_ROOT__/Human` pattern (`.tmp/Human`, `.tmp/Worker`, `.tmp/Overseer`) would grant **every** role **all three** temp dirs, which reproduces exactly the cross-clone over-grant that R3-2 flagged (#2056) and defeats the separation. `__ROLE__` is lowercase, so a derived token is the only way to grant the role's own capitalised dir and nothing else.<br>• `__ROLE_DIR__` is **derived**, not configured. The generator computes it from `--role` via a fixed map, `ROLE_DIRS = {"human": "Human", "worker": "Worker", "overseer": "Overseer"}`. It has no flag, no sidecar key and no sidecar version bump (§2A.4).<br>• `config.sh` *can* move the root (single-clone fallback or operator override). The sandbox generator therefore **fails closed** when the clone's resolved `HOS_TMP_ROOT` is not `__HOS_ROOT__/.tmp`, or when `__HOS_ROOT__` is not under `__HOME__` (§2A.4).<br>• A placeholder (`__HOS_TMP_ROOT__`) can be added later, by a separate issue, if a sandboxed layout ever needs a moved root. | Today only the `human` role is generatable (#1221; worker and overseer are gated on #1146), and only in the multi-clone layout, where the default is always the right path. A new placeholder would mean a sidecar schema change and migration for no current user. Failing closed means a mismatch can never produce a sandbox that grants the wrong dir. |
| D16 | **`HOS_TMP_ROOT` is never inside a git work tree, nor inside the clone.** Two places check this:<br>• the resolver (`bootstrap/lib/hos_tmp_root.py`), on every launch; a failed check makes the launcher fall back to `/tmp` with a warning;<br>• `install.sh`, at install time; it refuses the value. | `pytest-of-*` trees hold repo replicas with their own `.git`. Inside a work tree they would be walked by `rg`, `find`, validators, ScanCode and `git status`, and could be self-copied by replica fixtures. Outside every work tree, none of those hazards exist. The check is static (`.git` lookup up the ancestor chain), so the resolver never executes git. |

---

## 2A. Contract: per-role disk temp root (`HOS_TMP_ROOT`) [S2a]

The human's facts and ruling: `/tmp` here is `tmpfs size=1735952k nr_inodes=1048576 usrquota`, on a host with 14 GiB of RAM and 31 GiB of swap. *"RAM for pytest results etc is silly."* The human approved a hidden, per-role disk temp root beside the sibling clones: `~/Code/HumanOversightSystem/.tmp/{Worker,Overseer,Human}`.

### 2A.1 `config.sh` setting

- Key: `HOS_TMP_ROOT`, in `scripts/framework/config.sh`.
- **Value grammar** (the value is parsed statically and never sourced or executed):
  - empty or absent → `../.tmp`;
  - a relative path → resolved against the clone root (`realpath(<repo>)`);
  - `~/…` → `$HOME/…`, using `pwd.getpwuid(os.getuid()).pw_dir`;
  - an absolute path.

  A value containing `$`, a backtick, `;`, a newline or a glob metacharacter is a configuration error.
- **This repo:** commit `export HOS_TMP_ROOT="../.tmp"`, with a comment pointing to §2A. The file is committed and shared by the Human, Worker and Overseer clones; a relative value makes it machine-independent.
- **Consumer installs (`scripts/framework/install.sh`).** The installer prompts for the value with a computed default:
  - **Multi-clone layout:** `projects.conf` registers a `<project>_worker_root` or `<project>_overseer_root` whose parent equals the target's parent. Default: `../.tmp`.
  - **Single-clone layout** (anything else). Default: `~/.local/state/hos/tmp/<project-slug>`. `<project-slug>` is `PROJECT_NAME` lower-cased, with every character outside `[a-z0-9._-]` replaced by `-`.
    - Why not `../.tmp` here: a lone clone's parent is typically a shared directory such as `~/src`. A hidden `~/src/.tmp/Worker` would be shared by every single-clone HOS project under it, mixing their temp files, and `~/src` itself may be a work tree.
    - `~/.local/state` (XDG state) is per-user, on disk, outside any work tree, and **not** in the sandbox's `__HOME__` re-allow list, unlike `~/.cache`, which every role may write.
  - The installer refuses a value that §2A.5 rejects. Interactive mode re-prompts. Non-interactive mode exits non-zero with the reason.

### 2A.2 Resolver: `bootstrap/lib/hos_tmp_root.py` (one implementation, D41)

This is stdlib Python under `bootstrap/` (machine-level, protected). It never spawns a process.

- **`resolve --repo <clone> --role <role> [--create]`** prints one line: the absolute per-role dir `<root>/<RoleDir>`.
- **`root --repo <clone>`** prints the root.
- `<role>` is the lowercase role name that the launchers already use (`$ROLE` in `hos-cron`). It must match `^(worker|overseer|human|local)$`. `local` covers direct terminal runs of the inner loop that no launcher started.
- **Dir name (human ruling: capitalised, matching the clone dirs).** `<RoleDir>` = `ROLE_DIRS[<role>]`, with `ROLE_DIRS = {"worker": "Worker", "overseer": "Overseer", "human": "Human", "local": "Local"}`.
  - This is an explicit map, not `str.capitalize()`, so the names cannot drift from the clone dir names.
  - The resolver module is the single source of the map. `gen_sandbox_config.py` imports it, minus `local`, which is never sandbox-generated.
  - The resolver never creates or accepts a lowercase sibling (`.tmp/worker`). On a case-insensitive filesystem (macOS), the lstat of `Worker` resolves either way, so the check is by realpath basename equality.

Steps:
1. Parse the **last** `^\s*(export\s+)?HOS_TMP_ROOT=` line of `<repo>/scripts/framework/config.sh` per §2A.1. Strip one pair of matching quotes. If the file or key is missing, use `../.tmp`.
2. Expand and normalise the value to an absolute path (`os.path.normpath`, without resolving symlinks yet).
3. Validate per §2A.5.
4. With `--create`:
   - Create any missing components of the root with mode 0700.
   - Require the root, by lstat, to be a real directory (not a symlink) owned by uid.
   - Create `<root>/<RoleDir>` with mode 0700 and require the same of it.
   - If an existing role dir has any group or other bits set, `chmod` it to 0700, since it is the user's own dir.
   - The root dir itself may hold other roles' dirs; it is not chmod-ed beyond creation.
5. **Exit codes:** `0` OK; `2` usage error; `3` invalid or unusable, with one `hos_tmp_root: <reason>` line on stderr.

The same module exposes `resolve_root(repo) -> Path` and `check_outside_work_tree(path) -> None | str` for in-process use. Those callers are `gen_sandbox_config.py` (§2A.4) and `install.sh`, via `python3 -I … root`.

### 2A.3 Launchers export `TMPDIR`

| Launcher | Placement | Behaviour |
|---|---|---|
| `bin/hos-cron` (worker, overseer) | Immediately after the `_audit()` helper definition. That is after the overlap lock and cycle-identity minting, and before the §8.5 low-space trigger, the usage-pause gate, preflight and auth. | `_hos_tmp_dir="$(python3 -I "$REPO_ROOT/bootstrap/lib/hos_tmp_root.py" resolve --repo "$REPO_ROOT" --role "$ROLE" --create)"`. On rc 0, export **three** variables, each set to the role dir (R3-1): `export TMPDIR="$_hos_tmp_dir" CLAUDE_CODE_TMPDIR="$_hos_tmp_dir" HOS_TMP_DIR="$_hos_tmp_dir"`. Also set `HOS_TMP_ROOT_RESOLVED="$(dirname "$_hos_tmp_dir")"`. On failure: one `$LOG_PREFIX WARN: HOS tmp root unusable (<reason>) — TMPDIR left as-is` line, plus `_audit cycle-tmp-root-fallback "reason=<reason>"`, and the cycle continues with none of the three exported. **Never fatal.** The launched Claude session, the inner-loop baseline and every child inherit them. |
| `bin/hos-human` (human) | After the token mint, identity guard and repo sync, immediately before `exec claude`. | Same resolve call with `--role human`. On success, the same three exports: `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` (R3-1). On failure, a warning on stderr, nothing exported, and the session still starts. Placing it **after** the token mint keeps `get_app_token.sh`'s short-lived token temp file on the RAM-backed `/tmp`, as today, rather than on disk. |
| `scripts/framework/run_tests_inner_loop.sh` | Top of the script, after `REPO_ROOT`. | **Resolution order (R3-1)**, first match wins, and the result is exported as `TMPDIR`:<br>1. `HOS_TMP_DIR`, if set and an existing writable dir (a launcher chose);<br>2. otherwise `resolve --repo "$REPO_ROOT" --role local --create`, if it succeeds and the dir is writable;<br>3. otherwise the inherited non-empty `TMPDIR`;<br>4. otherwise unset, i.e. `/tmp`.<br>Steps 2→3 and 3→4 each print one WARN line on stderr. Blindly inheriting a non-empty `TMPDIR` is **not** allowed: in a sandboxed ad-hoc session it is Claude Code's `/tmp/claude`, which would put pytest back on the RAM tmpfs, inside the class-S scratch root. |

S1 needs no change: pytest's `pytest-of-<user>`, the D4 `session-tmp` redirect and the D6 basetemp measurement all follow `TMPDIR`.

**Why `CLAUDE_CODE_TMPDIR` (R3-1; architect evidence from the installed CLI 2.1.295).**
- In **sandboxed** Bash, Claude Code sets the child `TMPDIR` to `CLAUDE_CODE_TMPDIR || CLAUDE_TMPDIR || "/tmp/claude"`. That **replaces** any launcher-exported `TMPDIR`.
- Claude Code's own dir is `<CLAUDE_CODE_TMPDIR || os.tmpdir()>/claude-<uid>`.
- Exporting `CLAUDE_CODE_TMPDIR` therefore puts both sandboxed Bash children and `claude-<uid>` inside the role's granted `.tmp/<RoleDir>`.
- `HOS_TMP_DIR` is the HOS-owned marker that the inner loop trusts (step 1 above). Claude Code never rewrites it.

**Residual (R3-1).** A sandboxed session that no launcher started (for example a plain `claude` in a worktree) cannot write `.tmp/Local`. Step 2 fails, so it falls to step 3, `/tmp/claude`.
- R2-7's `SKIP other-class` keeps class S off its `pytest-of-*`.
- The inner-loop pre-run (`--root "$TMPDIR"`) reaps it as class P.
- §8.3's CLAUDE.md text tells interactive users to start sessions through `bin/hos-human`, or to export `CLAUDE_CODE_TMPDIR`.

**Coder verification item (replaces the round-3 open question).** In a session launched by `bin/hos-human`, a sandboxed Bash `echo $TMPDIR` must print `<HOS_ROOT>/.tmp/Human`. Record the output in the PR.

### 2A.4 Sandbox template: per-role temp-dir separation (`contract/sandbox-policy.template.json`, protected)

Add exactly these entries. They use `__HOS_ROOT__` plus the derived `__ROLE_DIR__` token (D15). The rendered shape, for example `<HOS_ROOT>/.tmp/Human`, is the capitalised shape the human is adding by hand to the live `settings.local.json`:

| Location | Added entry |
|---|---|
| `permissions.additionalDirectories` | `"__HOS_ROOT__/.tmp/__ROLE_DIR__"` |
| `permissions.allow` | `"Read(__HOS_ROOT__/.tmp/__ROLE_DIR__/**)"`, `"Edit(__HOS_ROOT__/.tmp/__ROLE_DIR__/**)"` |
| `permissions.allow` | `"Bash(quota *)"`, `"Bash(findmnt *)"`, for quota and free-space checks. `df`, `du` and `stat` are already allowed. |
| `sandbox.filesystem.allowRead` | `"__HOS_ROOT__/.tmp/__ROLE_DIR__"` |
| `sandbox.filesystem.allowWrite` | `"__HOS_ROOT__/.tmp/__ROLE_DIR__"` |

Unchanged:
- every `/tmp` entry (`additionalDirectories` `/tmp/claude` and `/tmp`; `Read`/`Edit`/`Write(//tmp/**)`; `allowWrite` `/tmp`). Drafts in `/tmp/claude`, Claude Code's `/tmp/claude-<uid>` and the `${TMPDIR:-/tmp}` fallback still need them.
- `denyRead` `"__HOME__/"`. It already hides the *other* roles' `.tmp/<RoleDir>` dirs, because `__HOS_ROOT__` is under `__HOME__` and only the own-role subdir is re-allowed.
- Every `__HOME__/.local/share` entry. It is readable but not writable from the sandbox, which is why the daily cron runs the reaper copy installed there (§8.2, R3-4).

**The guarantee, stated precisely (R3-2): no role's sandbox is granted another role's temp dir.** No entry grants `__HOS_ROOT__/.tmp` itself or a sibling role's dir. The grant **does not widen any existing access**: `.tmp` lies outside every clone, and `denyRead __HOME__/` hides the sibling role dirs.
- This is a **temp-dir separation, not a role-integrity boundary.** Every role's sandbox can already write all three clones (`allowWrite` `__HOS_ROOT__/{Human,Worker,Overseer}`). That includes another clone's `scripts/framework/config.sh`, which sets that role's `HOS_TMP_ROOT`, and its `bin/hos-cron`. So this design gives no protection against a role that tampers with another clone.
- That cross-clone write grant is pre-existing and out of scope here. Narrowing it per role is tracked in **#2056** (milestone v0.7.4, Sandboxing & Isolation), alongside #1146.

**The cross-role janitor (R3-6).** The §8.5 low-space trigger and the daily reaper (§8.2) act on **every** role's dir, as **unsandboxed machine processes**. That is outside the per-role sandbox grants by design. Per-role isolation governs agent sessions; the reaper is a machine janitor, not an agent.

`scripts/framework/gen_sandbox_config.py` adds a guard before rendering (D15). It fails closed with `EXIT_USAGE` and a message naming the fix in these cases:
- `resolve_root(--clone-dir)` ≠ `<HOS_ROOT>/.tmp`, compared as realpath, or by string when the path does not exist yet;
- `HOS_ROOT` is not under `HOME`. Without that, `denyRead __HOME__/` would not hide sibling role dirs.

**`__ROLE_DIR__` in the generator (D15).** `gen_sandbox_config.py` changes in four ways:
- It adds `ROLE_DIR` to the substitution values, computed as `ROLE_DIRS[values["ROLE"]]`, with the map imported from `bootstrap/lib/hos_tmp_root.py`.
- `ROLE_DIR` is **not** added to `PATH_PLACEHOLDERS`, to `FLAG_NAMES` or to the sidecar keys. It is derived exactly as `ROLE` is supplied, and is echoed back alongside `ROLE` with source `derived`.
- The surviving-placeholder check covers it automatically, because it is a `__NAME__` token.
- An unknown role cannot reach rendering: the existing role gate already fails closed for anything except `human`.

The values sidecar is unchanged: no new key, no version bump. Check mode against a live file that does not yet carry the new entries reports them as divergences, which is the intended prompt to update.

**Scope of enforcement, stated plainly.** Only the `human` role is generatable today. Worker and overseer are gated on #1146; `docs/SANDBOX-POLICY.md` §2 records that the autonomous cron roles currently run without a sandbox. For those roles, the per-role dirs give *separation by construction* (each launcher writes only its own dir), and *enforcement* arrives with #1146 through the same template entries.

**`docs/SANDBOX-POLICY.md` updates:**
- §3 `sandbox.filesystem` gains a paragraph covering:
  - the per-role `.tmp/__ROLE_DIR__` grant;
  - why the dir is never shared across roles (the overseer must not read or write worker scratch through a common dir);
  - why `/tmp` stays;
  - why `denyRead __HOME__/` is what hides sibling role dirs;
  - the R3-2 wording: temp-dir separation, not a role-integrity boundary, with a pointer to #2056;
  - the R3-6 note on the cross-role janitor;
  - `CLAUDE_CODE_TMPDIR` (R3-1).
- §3 `permissions` notes `quota` and `findmnt`.
- §5 gains a table row for `__ROLE_DIR__`: "capitalised dir name for `__ROLE__` (`human` → `Human`, `worker` → `Worker`, `overseer` → `Overseer`), matching the clone dirs; derived from `--role`, with no flag of its own and no sidecar key". §5 also gains a note under the table: the root `.tmp` is derived from `__HOS_ROOT__` and needs no placeholder of its own, and the generator refuses a clone whose `HOS_TMP_ROOT` is not `__HOS_ROOT__/.tmp` (D15).

### 2A.5 Never inside a git work tree (human item 7)

The resolver and the installer both reject a root that:
- is inside a git work tree. Walk from the root path (or its nearest existing ancestor) up to `/`. Any ancestor, or the path itself, with an lstat-visible `.git` entry (dir or file) means rejection. This is a static check that never runs git. It also catches a dotfiles repo at `$HOME`, which the operator must then avoid with an explicit value;
- equals, or is under, `realpath(<repo>)`;
- is not absolute after expansion.

This replaces any reliance on `.gitignore`: an ignored in-repo dir is still walked by tools.

### 2A.6 Residual: disk exhaustion (human item 8)

On ext4 (`/` here: 501 GB, 354 GB free) the failure mode changes from a 1.7 GB per-user quota to filling the **root filesystem**. That has no per-user limit, so it is a worse blast radius, though one much further away.

Bounds:
- D6 caps each green session at 50 MiB retained;
- retention (D1) removes green runs;
- the daily reaper and the low-space trigger remove stale debris after 24 h.

The low-space probe (§8.5) catches ENOSPC on the disk root as well as EDQUOT on `/tmp`. There is no automatic size cap on the root beyond these. `quota` and `findmnt` are allowed in the sandbox for diagnosis.

**Claude Code's own dir on disk (R3-5, accepted residual).** With `CLAUDE_CODE_TMPDIR` exported, `claude-<uid>` lives in `.tmp/<RoleDir>/` on disk, so a reboot no longer clears it. Claude Code manages that dir itself; it is 124 KB today. The reaper never deletes any `claude-*` entry. Under `--measure`, a `claude-<uid>` entry over 100 MiB in any root is reported as `WARN large-unowned` (§5.4), for visibility only.

### 2A.7 Tests (S2a)

| ID | Asserts |
|---|---|
| H1 | `tests/framework/test_hos_tmp_root.py`: config.sh missing or empty → `<repo>/../.tmp`. Relative, `~/` and absolute values resolve as specified. A value with `$`, a backtick, `;` or `*` → exit 3. The last `HOS_TMP_ROOT=` line wins. **This repo's committed `scripts/framework/config.sh` line parses to `../.tmp`** (architect ruling 7). That guards against an edit the shell accepts but the resolver rejects. |
| H2 | Root inside a work tree: `.git` dir in an ancestor, and `.git` *file* in an ancestor → exit 3. Root equal to or under the repo → exit 3. |
| H5 | **Capitalised dir names (human ruling).** `--role worker`, `overseer`, `human` and `local` print `<root>/Worker`, `Overseer`, `Human` and `Local` respectively. `--create` never creates a lowercase sibling. `--role Worker` (a capitalised *role arg*) → exit 2. |
| H3 | `--create`: creates root and role dir with 0700. Tightens an existing 0755 role dir to 0700. A symlinked root or role dir → exit 3. A role outside the set → exit 2. |
| H4 | No subprocess: `subprocess` and `os.exec*` are monkeypatched to raise, and resolution succeeds. |
| G1 | `tests/framework/test_gen_sandbox_config.py`: a rendered `human` config contains exactly the five §2A.4 locations' new entries, with `__ROLE_DIR__` rendered as **`Human`**. It contains no `.tmp/Worker`, `.tmp/Overseer`, lowercase `.tmp/human` or bare `.tmp` grant. No `__ROLE_DIR__` token survives rendering. The values sidecar has no `ROLE_DIR` key. The `/tmp` entries are unchanged. A unit test asserts `ROLE_DIRS` maps `human`, `worker` and `overseer` to `Human`, `Worker` and `Overseer`. |
| G2 | The generator fails closed (`EXIT_USAGE`) when the clone's config.sh moves `HOS_TMP_ROOT` elsewhere, and when `--hos-root` is not under `--home`. |
| L1 | `tests/automation/test_hos_cron.py`: the launched session's environment has `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` all equal to `<fake parent>/.tmp/Worker`, and that dir exists with mode 0700. With the resolver stubbed to fail: one WARN line, a `cycle-tmp-root-fallback` audit event, none of the three exported, and the cycle continues. |
| L2 | `tests/framework/test_hos_human_launcher.py` (static order check): in `bin/hos-human`, the resolver call and the export of `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` come after the `get_app_token.sh` call and before `exec claude`. |
| L3 | `tests/framework/test_run_tests_inner_loop.py`, all four R3-1 branches: (1) `HOS_TMP_DIR` set to a writable dir → used, even with a different `TMPDIR` inherited; (2) no `HOS_TMP_DIR`, inherited `TMPDIR=/tmp/claude`-equivalent, and `.tmp/Local` creatable → **`.tmp/Local` wins**; (3) `.tmp/Local` not creatable (resolver stubbed to fail) with an inherited `TMPDIR` → inherited value kept, plus a WARN; (4) nothing usable → `TMPDIR` unset, plus a WARN. |
| I1 | `tests/framework/test_install*.py`: the default is `../.tmp` for a multi-clone registry fixture and `~/.local/state/hos/tmp/<slug>` otherwise. A value inside a work tree is refused (non-interactive: non-zero exit). |

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

## 5. Contract: `bootstrap/tmp_reaper.py` (machine-level Layer 2 backstop) [S2b]

### 5.1 CLI

```
tmp_reaper.py [--root DIR]... [--hos-tmp-root DIR]... [--if-low-space]
              [--dry-run] [--measure] [--summary-only] [--no-scratch]
              [--min-age-hours H=24] [--max-seconds S=20]
```

- **Roots (disk-temp ruling; replaces round 2's single `--tmp-root`).** The reaper sweeps a *set* of temp roots. Each root is a directory in the `TMPDIR` sense: it holds `pytest-of-<user>/`, `tmp*` entries and, optionally, a `claude/` scratch root.
  - **`--root DIR`** (repeatable) adds one root.
  - **`--hos-tmp-root DIR`** (repeatable) adds every direct child of `DIR` named `^(Worker|Overseer|Human|Local)$` (the capitalised role dirs, §2A.2) that lstats as a real directory owned by uid. Any other child is ignored (`SKIP not-a-role-dir`). `DIR` itself is never a root and never a candidate. This is how an HOS disk temp root (§2A) is swept: one flag covers all its roles.
  - **No root flag** → one root: `$TMPDIR` if it is set and non-empty, else `/tmp`. This is the round-2 behaviour.
  - Every root is resolved with `realpath` once and de-duplicated. Each must be an existing directory owned by root or by the current uid. An invalid root is skipped with `SKIP root-invalid <path>`. If **no** valid root remains, exit 3.
  - Roots are learned **only from flags**. There is no `config.sh` or `projects.conf` discovery, which keeps the tool simple and keeps it from executing project files. The crontab line lists them (§8.2), and `bin/hos-cron` passes its own (§8.5).
- **`--if-low-space`** (the low-space trigger, §8.5) probes every root before doing anything else.
  - **Probe:** create `<root>/.hos-space-probe.<pid>.<8 hex>` with `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW|O_CLOEXEC`, mode 0600. Write 64 KiB, `fsync`, close, and unlink in a `finally`. Any `OSError` during the probe, including EDQUOT, ENOSPC and EIO, marks that root **low**. `df` is not consulted, because it is unreliable under `usrquota`.
  - **Output:** one line, `TMP_REAPER_PROBE ok` or `TMP_REAPER_PROBE low roots=<comma-separated low roots>`.
  - All roots OK → no reaping. Print the summary line with `reaped=0` (listing counts still computed) and exit 0.
  - Any root low → run a normal reap over **all** given roots. That is still the full 24 h rule plus vetoes, and the age threshold is never lowered.
  - Probe files start with `.`, so they never match a class-T or class-S pattern. A probe file orphaned by a SIGKILL is a 64 KiB dotfile; it is accepted and never reaped.

- **Class S is on by default** (human ruling §12.1(b); machine policy lives in the script's defaults and flags, not in per-project config).
  - **`--no-scratch`** disables class S entirely: no walk and no output, and `scratch_trees=-` in the summary.
  - The per-machine opt-out is simply `--no-scratch` on the operator's crontab line. **No env var and no config file.** The crontab line is already the per-machine configuration, and it is visible where the schedule is defined. An env-var knob would be invisible in `crontab -l`, and a config file would be a second source of truth.
  - `run_tests_inner_loop.sh` always passes `--no-scratch` (§8.1).
- **Clock injection (testability).** `main(argv, *, clock=time.time) -> int` is the importable entry point, and `__main__` calls it with the real clock. Every age computation uses `clock()`. Tests run the reaper in process with `clock = lambda: time.time() + 48*3600` to make real-ctime entries "old" without lowering the threshold. A "recent" entry is created by `os.utime`-ing it to `fake_now − 1 h`.

- Tests always pass explicit `--root`/`--hos-tmp-root` values under `tmp_path`.
- **`--min-age-hours`** is the single age threshold (D11). It must be a number ≥ 24, else exit 2. There are no other age knobs; round 1's `--legacy-lock-hours` and `--orphan-min-age-hours` are removed. Tests satisfy the threshold by backdating mtimes and ctimes, never by lowering it. ctime cannot be set directly, so a test that needs an old ctime injects `now` through `decide()` (R7) or monkeypatches the clock in-process.
- **`--dry-run`** makes every decision exactly as a real run would and prints `WOULD-REAP`. It performs **no** unlink, rmdir, rename or rmtree.
- **`--measure`** deletes nothing. It prints only the summary line, with `user_bytes` computed, plus `WARN large-unowned` lines (AC-10).
- **`--summary-only`** suppresses per-entry lines except `REAP` and `ERROR`.
- **`--max-seconds`** is a wall-clock budget covering the `/proc` scan and all candidates. When it is exhausted, the reaper starts no new candidates, finishes the current one, and reports `truncated=1`. The default is 20.
  - The inner loop passes 20 explicitly (§8.1).
  - The daily crontab recipe passes 540, inside an outer `timeout --kill-after=10 600` (§8.2).
  - The `bin/hos-cron` low-space trigger passes 20, inside `_TR_BOUND` = `timeout --kill-after=5 30` (§8.5).
  - The inner budget is always strictly less than the outer bound. This is AC-9, restated for each caller.
  - `--measure` users pass a larger value (§9).
- **Exit codes:**
  - `0` = completed, including skips, per-entry errors and truncation;
  - `2` = usage error;
  - `3` = no valid root, or running as root.
  - Callers treat any non-zero as a warning, never as a failure.
- Stdlib only. It runs under `python3 -I` with no venv. The Python floor is 3.10.

### 5.2 Structure (testability)

- `collect_facts(entry, proc_index) -> Facts` performs all I/O: lstat, the safe `.hos-live` open and probe (§5.3.1), and child mtimes.
- `scan_proc() -> ProcIndex` (§5.3.3) runs at most once per invocation, and **lazily**: only when at least one candidate reaches a pre-veto REAP verdict. Idle cycles therefore cost one directory listing.
- `decide(facts, now, policy) -> Decision(action, reason)` is **pure**. Class S has its own pure `decide_scratch(tree_facts, now, policy)`; its I/O (the §5.7.4 walk) lives in `collect_scratch_facts()`. A further pure parser, `parse_proc_locks(text) -> set[(major, minor, ino)]`, raises on any unparseable line (R2-5) and is unit-tested directly. No git parsing exists (§12.1 ruling).
- **Class order:** P, then T, then S (R2-7). Within each class, roots are taken in the order given. The `--max-seconds` budget is shared across all roots. In §5.3–§5.7, `<root>` means each root in turn.
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

1. quiet < AGE → **SKIP fresh**. This applies always.
2. `.hos-live` exists → run the §5.3.1 probe.
   - SKIP verdicts stand.
   - On a successful probe:
     - `.lock` **present** → the run was killed → candidate **REAP dead-flock**;
     - `.lock` **absent** → the run finished normally (§4.5 released the flock) → go to rule 4 (AC-1).
3. No `.hos-live` and `.lock` exists (a legacy, consumer or other-repo run without D3) → candidate **REAP legacy-stale**. AGE is already satisfied by rule 1, and the veto still applies.
4. No `.lock` (a finished run, with or without an unlocked `.hos-live`):
   - → candidate **REAP finished** (AC-2: quiet ≥ AGE, which is 24 h, plus the veto).
   - **No KEEP-newest exception (R3-3, human ruling: "Anything older than a day goes").** The inspection window is Layer 1: pytest's `count=1` keeps the newest failed dir until the next completed session (§3 R-2). The reaper adds no window of its own.
   - AC-1's routing of a successful probe with no `.lock` to this rule, rather than to `dead-flock`, is kept. It now affects only the reason label.
5. **Live-process veto (AC-3)**, applied to *every* candidate REAP in class P (rules 2, 3 and 4, and `garbage-*`). This is stricter than AC-3's "rules 3 and 4": adding rule 2 costs nothing and covers a killed pytest whose own child is still running in the dir. The veto checks, in order:
   - `.lock` names PID p, `/proc/p` exists, and `/proc/p/cmdline` contains `pytest` → **SKIP live-proc**;
   - any visible process's `cwd`, `root` or open fd resolves to a path at or under the candidate → **SKIP live-proc**;
   - the `/proc` scan was truncated by `--max-seconds` → **SKIP proc-scan-incomplete**;
   - `/proc` is absent or unreadable (macOS, or a restricted sandbox) → no evidence, and the candidate stands. Absence is never evidence of death; it simply removes the veto. Safety then rests on the flock and the 24 h age (accepted residual).
   - Otherwise → **REAP** with the candidate's reason.

#### 5.3.3 `/proc` index

`scan_proc()` iterates `/proc/[0-9]*`. For each PID it records `readlink` of `cwd`, `root`, `exe` and every `fd/*`, plus `cmdline`, ignoring EACCES/ENOENT/ESRCH. It is built lazily (§5.2), except when class S is enabled (the default; not `--no-scratch`), where §5.7.1 requires it up front. It builds a set of resolved target paths.

- "At or under the candidate" is a string-prefix test on resolved paths with a trailing `/`.
- Class T (§5.4) uses the same index for exact-path matches.
- The scan checks the time budget after each PID. Running out marks the index `complete=False`. That is the **only** thing `complete` means (R2-6).
- Per-process `EACCES`/`ENOENT`/`ESRCH` errors are tolerated and counted in `n_unreadable`. They never make the index incomplete.

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
| non-empty dir | Not decided by class T, which is never recursive. It is **handed to class S** as a shape-2 candidate (§5.7.2) and judged there by the full whole-tree procedure (human ruling §12.1(d)). With `--no-scratch`, or with class S disabled for the run → `SKIP non-empty`. |
| socket, fifo, device | **SKIP** (reported). |

- **Age.** `now − max(mtime, ctime) ≥ AGE`.
- **Open-handle veto.** If the entry is an exact target of any `cwd`, `root` or fd in the §5.3.3 index → **SKIP open**. If the index is incomplete → **SKIP proc-scan-incomplete**. If `/proc` is absent → no veto (accepted residual, D12).
- **Never touched:** `pytest-of-*`, `claude-*`, `hos-*` (including the #1903 failure logs), `node-compile-cache`, `gh-cli-cache`, `*.sock`, and anything not matching the patterns. This is an allowlist of patterns.
- **Non-empty `tmp*` dirs are deleted only through class S** (human ruling §12.1(d): "Anything older than a day goes"). They are never deleted by an age-only rule. The class-S procedure applies in full: newest-timestamp-in-tree age, ownership, same device, no symlink traversal, host view, the process and lock vetoes, session exclusions, and the rename plus dev/ino re-check.
- **Large-entry warning (AC-10: `--measure` only).** Under `--measure`, any user-owned top-level entry larger than 100 MiB that no class covers produces `WARN large-unowned <path> <bytes>`. This explicitly includes a **`claude-<uid>` entry in any root**, which `CLAUDE_CODE_TMPDIR` now places in `.tmp/<RoleDir>/` (R3-5). That is visibility only: `claude-*` is never deleted. The walk is depth-bounded and time-boxed, and **never runs** in default or `--summary-only` mode. Deletion of large *agent scratch trees*, such as `/tmp/claude/hos1935` (548 MB), is no longer report-only. The human rulings that supersede Q6 move them to class S (§5.7). Class S is on unless `--no-scratch` is given, and deletes them only when every §5.7 liveness condition holds. Large entries that are not class-S candidates stay report-only.

### 5.5 Output (stable, greppable)

```
TMP_REAPER_RUN ts=<ISO-8601 UTC> pid=<pid> roots=<realpaths, comma-separated>     (always first)
TMP_REAPER_PROBE ok | TMP_REAPER_PROBE low roots=<…>     (--if-low-space only; second line)
REAP <class> <reason> <path> <bytes>
WOULD-REAP <class> <reason> <path> <bytes>     (dry-run)
SKIP <reason> <path>
ERROR <errno-name> <path>
WARN large-unowned <path> <bytes>              (--measure only)
TMP_REAPER roots=<n> reaped=<n> freed_bytes=<n> skipped=<n> errors=<n> truncated=<0|1> user_bytes=<n|-> pytest_runs=<n> empty_tmp_dirs=<n> tmp_files=<n> scratch_trees=<n|-> dry_run=<0|1>
```

`<class>` is one of `P`, `T` or `S`.

- `<bytes>` on `REAP` lines covers the candidate itself only. For a class-P dir it is that dir's allocated bytes, which the `act` step measures just before rename (AC-10). For a class-S tree it is the allocated total from the §5.7 walk, so no second walk is needed.
- `scratch_trees` is the number of class-S candidates (both §5.7.2 shapes) **remaining** after acting, excluding `garbage-hos-*`. It is `-` when `--no-scratch` is given or class S was disabled for the run (§5.7.1).
- `roots` in the summary is the number of valid roots swept. Every count (`pytest_runs`, `empty_tmp_dirs`, `tmp_files`, `scratch_trees`, `user_bytes`) is summed over all roots.
- `user_bytes` is computed **only under `--measure`**. Otherwise it is `-`. Under `--measure` it is `-` if the walk was truncated.
- `pytest_runs`, `empty_tmp_dirs` and `tmp_files` are counts of entries **remaining** after acting: `pytest-N` children, class-T empty dirs, and class-T regular files. They come from listings, which are cheap in every mode.
- The summary line always prints, always last, and matches:
  `^TMP_REAPER roots=\d+ reaped=\d+ freed_bytes=\d+ skipped=\d+ errors=\d+ truncated=[01] user_bytes=(\d+|-) pytest_runs=\d+ empty_tmp_dirs=\d+ tmp_files=\d+ scratch_trees=(\d+|-) dry_run=[01]$`

### 5.6 Boundaries

- The reaper acts only on an entry whose realpath parent is `<root>`, `<root>/pytest-of-<user>`, or a §5.7.2 scratch root.
- It never acts on an entry that the current uid does not own.
- It never runs as root: `os.geteuid() == 0` → exit 3.
- It never spawns a subprocess or calls `exec*` (R2-1, kept). It never runs `git`, and it reads no git metadata.
- **Age alone never deletes.** "Older than a day" is the age rule. Every REAP needs age ≥ 24 h **and** a non-age liveness signal **and** must survive the live-process veto. The non-age signals are:
  - a dead flock on a verified inode, with `.lock` present (killed run);
  - a legacy `.lock` with no `.hos-live`;
  - a lock-free finished dir;
  - `garbage-` naming;
  - a class-T empty dir or regular file;
  - class S, which needs all of:
    - a whole-tree walk that completed, with every entry ≥ 24 h old, uid-owned and on the same device;
    - no held lock (parsed completely from the host-view `/proc/locks`);
    - no session marker;
    - an unchanged walked identity;
    - a host-view `/proc` index that was not cut short (§5.7).

    Class S keeps every liveness check even under "anything older than a day goes". It has **no size floor** and **no git-state check** (human rulings §12.1(d)/(e)). For class S, absence of evidence is not enough: a missing host view, an unparseable `/proc/locks`, or a truncated `/proc` scan disables class S.

### 5.7 Candidate class S: stale trees, deleted whole (on by default; `--no-scratch` opts out)

Human rulings:
- Q6: *"We should have the cleanup script zap the large scratch copies if older than 24h."*
- §12.1(d)/(e): *"Yes. Anything older than a day goes."*

The targets are ad-hoc repo clones and similar trees that agents create in a shared scratch location (for example `/tmp/claude/hos1935`, 548 MB), and non-empty leaked top-level `tmp*` dirs. Neither size nor git state matters: a stale tree with unpushed commits is deleted once it is 24 h old. **Every liveness check is kept.** "Older than a day" relaxes the age and scope rules, not the safety rules.

Class S is evaluated unless `--no-scratch` is given. When the reaper lacks the host view, class S refuses on its own (§5.7.1). That is the normal outcome for any sandboxed invocation.

**Evaluation order (R2-7).** The reaper evaluates the classes in the order **P, then T, then S**, so a long class-S walk that exhausts `--max-seconds` only defers class S. Class T hands its non-empty `tmp*` dirs to class S rather than deciding them itself. A tree that ends in `SKIP walk-truncated` is re-walked on every run. That cost is accepted and is visible in the log.

#### 5.7.1 Run-level preconditions (evaluated in this order; any failure disables class S for the whole run)

On any failure, print one `SKIP scratch-disabled <reason>` line and set `scratch_trees=-`.

1. `/proc` is readable. Reason `no-proc`.
2. **Host PID namespace.** The `NSpid:` line of `/proc/self/status` has exactly one field, **and** `/proc/1/comm` is readable and is not `bwrap`. Reason `no-host-view`.
   - This check is **load-bearing**. The architect verified that `/proc/locks` is filtered by PID namespace, so without a host view the lock veto would pass silently.
   - A per-machine crontab (§8.2) runs unsandboxed and passes. A sandboxed invocation, such as an inner loop run inside bwrap, fails here.
   - It is evaluated **before** `/proc/locks` is read (R2-5).
3. **`/proc/locks` parses completely (R2-5).**
   - Each line's `major:minor:inode` field is parsed with **major and minor in hex** and the **inode in decimal**. Example: `00:26:12345` is `st_dev` major 0, minor 0x26 = 38, inode 12345.
   - Entries are stored as `(major, minor, ino)`. A walked entry matches when `(os.major(st_dev), os.minor(st_dev), st_ino)` equals a stored triple.
   - If the file is unreadable → reason `no-locks-view`.
   - If **any** line cannot be parsed → reason `locks-unparseable`. That line is never skipped while the rest are kept.
4. **The §5.3.3 index is complete (R2-6).** The index is built eagerly when class S is enabled.
   - `complete=True` means exactly this: the scan was **not cut short by `--max-seconds`**.
   - A per-process `EACCES`/`ENOENT`/`ESRCH` is tolerated and counted as `n_unreadable`. When n > 0, print one informational line `SKIP proc-unreadable <n>`.
   - If the scan was cut short → reason `proc-scan-incomplete`.

#### 5.7.2 Eligible candidates (explicit, closed list; two shapes)

**Shape 1: scratch-root children.**
- `SCRATCH_ROOTS` is a module constant naming paths relative to `<root>`. In v1 it holds exactly `("claude",)`, i.e. `/tmp/claude/`, the agent scratch convention in `CLAUDE.md`. Adding a root is a code change to a protected surface and needs a test. There is no CLI or env override.
- A scratch root is used only if, by lstat, it is a real directory (not a symlink), owned by uid, with `st_dev` equal to `<root>`'s, and its `realpath` equals `<root>/<name>` exactly. Otherwise → `SKIP scratch-root-invalid <path>`.
- Candidates are the **direct children** of a scratch root that lstat as real directories. Regular files, symlinks and special files directly in a scratch root are never touched. That includes the ~37 agent draft files in `/tmp/claude` today.
- **Other classes' entries are excluded (R2-7).** A scratch-root child named `^pytest-of-`, `^garbage-` (except `^garbage-hos-`, which step 9 handles), `^tmp` or `^hos-` → `SKIP other-class`.

**Shape 2: non-empty top-level `tmp*` dirs (human ruling §12.1(d)).**
- Candidates are direct children of `<root>` that match a class-T pattern (§5.4), are uid-owned real directories (not symlinks), and are **non-empty**. Class T hands these to class S.
- Every name class T never touches (`pytest-of-*`, `claude-*`, `hos-*` and the rest of the §5.4 never-touched list) can never be a shape-2 candidate, because none of them matches a class-T pattern.

**Never eligible:** any other `/tmp` content.

#### 5.7.3 Claude Code session dirs: how they are recognised and excluded

Claude Code keeps per-user session state, task output and scratchpads under `<root>/claude-<uid>/…`, for example `/tmp/claude-1000/<project-slug>/<session-uuid>/scratchpad`. Exclusion is layered, and any one layer is enough:

1. **By root.** `<root>/claude-<digits>` is never a scratch root, and it never matches a shape-2 pattern. The §5.7.2 realpath-equality check stops a `claude` symlink or bind redirect from pointing class S at it.
2. **By name.** A scratch-root child named `^claude-\d+$` → `SKIP session-dir`.
3. **By marker (fail safe, during the walk).** Either of these → `SKIP session-like` for the whole tree. A false positive only keeps a tree.
   - any directory named `scratchpad`;
   - any entry at depth ≤ 3 whose name matches a UUID: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`.
4. **Self.** If the tree equals or contains the realpath of the reaper's own `os.getcwd()`, of `$TMPDIR`, or of any absolute-path environment variable value under a candidate parent → `SKIP self`.
5. **Live session.** If a running Claude Code session, or any other readable process, has its `cwd`, `root`, `exe` or an open fd at or under the tree → `SKIP live-proc` (§5.7.4 step 4).

#### 5.7.4 Per-tree decision, in order (cheap checks first)

1. **Identity (captured once; R2-2).** The candidate must lstat as a real dir, owned by uid, with `st_dev` equal to its parent's. It must not be `garbage-hos-*`; step 9 handles those.
   - Otherwise → `SKIP not-owned-or-foreign-dev`.
   - Record `walked_id = (st_dev, st_ino)` from **this** lstat. Every later identity check compares against it.
2. **Exclusions.** The §5.7.2 other-class names, then §5.7.3 layers 2 and 4.
3. **Top-level pre-filter.** If the dir's own `max(mtime, ctime)` is younger than AGE → `SKIP fresh`. This step can only skip a tree, never approve one.
4. **Live-process veto.** If any index entry (`cwd`, `root`, `exe`, `fd/*`) is at or under the tree → `SKIP live-proc`.
5. **Bounded whole-tree walk.** Use iterative `os.scandir` with `follow_symlinks=False`, and `lstat` every entry. The walk stops with a SKIP at the first failing entry:
   - **Age.** An entry whose `max(mtime, ctime)` is younger than AGE → `SKIP fresh-deep`. Age is **the newest timestamp anywhere in the tree**. Exiting early keeps active trees cheap.
   - **Owner.** `st_uid ≠ uid` → `SKIP foreign-owned`.
   - **Device.** `st_dev ≠` the tree's dev, i.e. a mount point inside → `SKIP cross-device`.
   - **Special files.** A socket, FIFO or device → `SKIP special`.
   - **Readability.** A directory that cannot be read (EACCES/EPERM) → `SKIP unreadable`.
   - **Session marker.** A §5.7.3 layer-3 marker → `SKIP session-like`.
   - **Held lock, kernel view.** The entry's `(major, minor, ino)` is in the §5.7.1 lock set → `SKIP held-lock`.
   - **Held lock, probe.** For a regular file named `*.lock`, `*.lck`, `.hos-live`, `LOCK` or `lock`, probe as in §5.3.1: open with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, call `flock(LOCK_EX|LOCK_NB)`, and release immediately.
     - EWOULDBLOCK → `SKIP held-lock`.
     - Any other error → `SKIP unknown`.
   - **Symlinks** are counted for age and ownership through `lstat`. They are **never followed or descended**.
   - **Git.** A `.git` entry is an ordinary dir or file to the walk. Nothing in it is parsed, and git is never run (§12.1 ruling; R2-1's no-exec rule is kept).
   - **Bounds.** At most `SCRATCH_MAX_INODES = 1_000_000` entries per tree, within the global `--max-seconds` budget. Hitting either → `SKIP walk-truncated`. A tree is never partly judged and never partly deleted.
   - **Size.** The walk sums allocated bytes (D8) for the REAP line only. There is **no size floor** (human ruling §12.1(e); R2-3 is withdrawn).
6. *(Removed: the R2-3 size floor, withdrawn by human ruling §12.1(e).)*
7. If the tree reaches this point with no SKIP → candidate **REAP scratch-stale**.
8. **Removal** (the same path as class P, §5.3.4):
   - (a) lstat the tree path again. If its `(st_dev, st_ino)` differs from `walked_id` → **`SKIP raced`, and no rename** (R2-2).
   - (b) `os.rename(tree, <parent>/garbage-hos-<uuid4>)`, where `<parent>` is the scratch root (shape 1) or `<root>` (shape 2). ENOENT → `SKIP raced`.
   - (c) lstat the garbage path and require `(st_dev, st_ino)` to equal `walked_id`. A mismatch → `ERROR identity-changed`, **no rmtree**, and the tree is left for a human.
   - (d) `shutil.rmtree` with the recording error handler. It is symlink-safe and never follows a link out of the tree.
   - Under `--dry-run`, print `WOULD-REAP S scratch-stale <path> <bytes>` and stop before (b).
9. **`garbage-hos-*` entries** in a scratch root or in `<root>` (left by an interrupted removal): REAP `garbage` when the top-level quiet time is ≥ AGE and the live-process veto passes. Apply steps 8(c)–(d) directly, with `walked_id` taken from this entry's own lstat. (Class T never touches `hos-*` names, so these belong to class S alone.)

**Never executes anything (R2-1, kept).** The reaper spawns no subprocess and calls no `exec*`. A machine crontab runs it **unsandboxed**. Running `git` inside a tree that a **sandboxed** agent wrote would execute repo-local `.git/config` hooks (`core.fsmonitor`, `core.pager`, …) on the host, which is a sandbox escape. RS12 enforces this rule.

**Accepted residuals (class S, under the human's "anything older than a day goes"):**
- **Unpushed git work is deleted.** A clone with local commits not on any remote is deleted once every file in it is ≥ 24 h old. This follows from human ruling §12.1. It is not a liveness question.
- **Uncommitted working-tree edits** in an idle tree are deleted.
- **Linked-worktree registrations.** If the deleted tree was the main repo of linked worktrees elsewhere, those worktrees lose their repo. If the deleted tree was itself a linked worktree, its main repo keeps a stale registration, which `git worktree prune` clears.
- **Small agent draft dirs** idle for more than 24 h are deleted. Draft *files* directly in `/tmp/claude` are never touched.
- **A narrow race.** A process could `chdir` into the tree in the milliseconds between the step-8(a) recheck and the rename.
- **Invisible processes.** A non-dumpable same-uid process (R2-6) is invisible to the veto. In practice these are system and session daemons, not agent tools.

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

## 8. Invocation, packaging and docs [S2b, protected; §2A.3 launcher exports are S2a]

### 8.1 `scripts/framework/run_tests_inner_loop.sh`: pre-run call (kept)

- **Placement:** the first statement inside `_run_suite()`, **before** `regen_all.sh`, which itself calls `mktemp -d`. A test run can therefore free space before it starts.
- Run the reaper only if `"$REPO_ROOT/bootstrap/tmp_reaper.py"` exists. `REPO_ROOT` is the script's existing repo-root variable. The file is absent only in test replicas.
- **Invocation:** `"$PYTHON" -I "$REPO_ROOT/bootstrap/tmp_reaper.py" --summary-only --no-scratch --max-seconds 20 --root "${TMPDIR:-/tmp}" --root /tmp`.
  - `TMPDIR` has already been inherited or resolved by §2A.3. If it is unset, both flags name `/tmp`, and the reaper de-duplicates them.
  - The run sweeps the role's own disk dir and `/tmp`, so the `/tmp` backlog of classes P and T shrinks even before an operator installs the crontab.
- **Why `--no-scratch` is explicit:** a test run frees only test-run debris (classes P and T).
  - Inside the sandbox, class S would refuse anyway, because it has no host view (§5.7.1).
  - Unsandboxed, for example a consumer developer or CI running the inner loop directly, a test run must not delete agent scratch trees as a side effect. Deleting those is machine policy, and it belongs to the operator's crontab (§8.2).
  - The flag makes the behaviour deterministic either way.
- **Best-effort:**
  - A non-zero exit prints one `✘ tmp_reaper failed (rc=N) — continuing` line to stderr and never changes the script's exit code. Use the `|| …` form so `set -e` does not trip.
  - The 20 s inner budget is the bound. No outer `timeout` is added here, matching the script's other best-effort steps.
  - Under `--failure-log` the output is teed into the log.
- `--help` gains one line naming the reaper.
- The runner does **not** gate on reaper output. The gate is D6.

### 8.2 Per-machine crontab: operator-installed, documented, never auto-installed

**Human ruling (2026-10-09, verbatim):** *"The script will be a script per machine, so it should be shipped with HOS and consumer can install it in cron if needed."*

This supersedes two earlier positions:
- the issue's "call it from cron-cycle wrap-up, not as a new scheduler";
- AC-8's unconditional cycle-start call site.

`bin/hos-cron` makes **no unconditional reap**. It has only the **conditional low-space trigger** (§8.5), which a later disk-temp ruling added. There is no `${PROJECT}_tmp_reap_scratch` key. Machine policy lives in the script's own defaults and flags (§5.1).

**Recipe** (goes into `docs/CRON-SETUP.md`; see §8.4). There is one entry per machine, in the **user's own** crontab (`crontab -e`) and never root's. The reaper refuses to run as root (exit 3).

**The entry runs the machine copy at `~/.local/share/hos/tmp_reaper.py`, never a clone's `bootstrap/tmp_reaper.py` (R3-4).** The worker cron checks out arbitrary branches in its clone, and every role's sandbox can write every clone. An **unsandboxed** daily job with recursive-delete power must not run whatever is checked out there, or whatever a sandboxed agent wrote. `~/.local/share` is readable but **not writable** from every sandbox. `bootstrap/hos_bootstrap.sh` installs the copy (see "Machine copy" below).

```cron
# HOS per-machine temp reaper (#2054). Daily. Create the log dir once: mkdir -p ~/.hos/logs
# One --hos-tmp-root per HOS disk temp root on this machine (python3 bootstrap/lib/hos_tmp_root.py root --repo <clone> prints it).
17 3 * * *  timeout --kill-after=10 600 python3 -I "$HOME/.local/share/hos/tmp_reaper.py" --summary-only --max-seconds 540 --root /tmp --hos-tmp-root "$HOME/Code/HumanOversightSystem/.tmp" >> "$HOME/.hos/logs/tmp-reaper.log" 2>&1
```

Rules for the recipe, each restated from an architect condition:
- **Roots.** Pass `--root /tmp` (the RAM-backed tmpfs: drafts, the legacy backlog, `/tmp/claude` scratch clones) **and** one `--hos-tmp-root` for each HOS disk temp root on the machine. The roots are explicit on the line. There is no discovery (§5.1).
- **AC-9, restated: inner budget below outer bound.** `--max-seconds 540` is strictly less than `timeout 600`, and `--kill-after=10` guarantees termination. On macOS use `gtimeout` (coreutils), as `bin/hos-cron` already does.
- **Log path is not under `/tmp`.** It goes under `~/.hos/`, the existing HOS state dir (`_HOS_DIR` in `bin/hos-cron`). The log must survive a full quota, and a full quota is exactly when the log is needed. With `--summary-only`, growth is a few MB a year. `bin/hos-trim-logs` only trims `/tmp/hos-*.log`, so the doc tells the operator to rotate the reaper log with `logrotate` if they want to.
- **Class S is on by default** (§12.1(b)). The per-machine opt-out is `--no-scratch` on this line (§5.1).
- **No sandbox.** User crontab jobs run unsandboxed, so class S has the host view it requires (§5.7.1). The doc says that if the line is ever run inside a sandbox, class S reports `scratch-disabled no-host-view` and does nothing.
- **Daily is enough** (the human asked, and the answer is yes). In-run cleanup (Layer 1) removes green runs immediately, and the §8.5 low-space trigger covers a sudden squeeze between daily runs. With the uniform 24 h age, a daily run leaves debris at most about 48 h old. Scheduling stays the operator's choice.
- **Concurrency is safe.** Concurrent reapers converge without harm (R11), so an overlapping inner-loop pre-run call is harmless.
- **Record line.** To make the log readable without the `hos-cron` prefix, the reaper prints a first line before anything else: `TMP_REAPER_RUN ts=<ISO-8601 UTC> pid=<pid> roots=<comma-separated realpaths>` (§5.5).

**Machine copy (R3-4): a file copy, not a crontab install.** `bootstrap/hos_bootstrap.sh` is the machine setup, and it runs from the validated release bundle. It **idempotently** copies `tmp_reaper.py` from its own directory (`$(dirname "$0")/tmp_reaper.py`) to `~/.local/share/hos/tmp_reaper.py`:
- create `~/.local/share/hos` if it is missing;
- if the destination is byte-identical (`cmp -s`), do nothing;
- otherwise write `tmp_reaper.py.new.<pid>` in the same directory, `chmod 0755`, and `mv -f` it into place (atomic replace);
- print one line naming the destination;
- if the source is absent (an old bundle), print one WARN line saying how to fetch it, and **do not fail** the bootstrap.

Re-running `hos_bootstrap.sh` from a newer release bundle is the documented way to update the machine copy. The never-auto-install ruling holds: `hos_bootstrap.sh` copies a file and never touches the crontab.

**Discoverability, with no auto-install:**
- `bootstrap/hos_bootstrap.sh`, at the end of its machine-setup summary, prints a short informational block. It says that the per-machine temp reaper is installed at `~/.local/share/hos/tmp_reaper.py`, that HOS does not schedule it, and where the crontab recipe is in `docs/CRON-SETUP.md`.
- `bootstrap/hos_install.sh`, in its end-of-install summary, prints one line pointing to the same doc and to the machine copy. It does not point to `<target>/bootstrap/tmp_reaper.py`.
- Neither script invokes `crontab` (C4).
- The `bin/hos-cron` low-space trigger (§8.5) keeps running `$REPO_ROOT/bootstrap/tmp_reaper.py`. That copy is at the same trust level as `bin/hos-cron` itself, so this is not a new exposure (R3-4).

**Packaging:**
- `bootstrap/tmp_reaper.py` is listed in `scripts/framework/framework_consumer_files.txt`, in its `bootstrap/` section, with a `# #2054` comment. The install copy loop and `.hos-manifest` therefore ship and track it in every consumer install.
- **It is added to the release-asset list in `scripts/framework/cut_release.sh`** (`ASSET_NAMES`, alongside `hos_install.sh`, `hos_bootstrap.sh` and `setup_clis.sh`). The bundle-download loop that `cut_release.sh` prints gains `tmp_reaper.py`. This reverses the round-3 position, and it follows from R3-4: `hos_bootstrap.sh` runs from the release bundle and copies the reaper from its own directory, so the reaper must be in the bundle. That copy is the validated release artifact, never a mutable clone.
- The file is executable (`chmod +x`), with a `#!/usr/bin/env python3` shebang. The recipe still calls it through `python3 -I`, so that `-I` isolation applies.

### 8.3 `CLAUDE.md`

In the **"Canonical entry points by task"** table, add one row:

> | Reclaiming temp space (machine-level backstop) in `/tmp` and the HOS disk temp roots (`<clone>/../.tmp/<RoleDir>`): stale `pytest-of-$USER/pytest-N` dirs, orphaned `tmp*` files/dirs, and agent scratch trees under `/tmp/claude/` whose newest file is older than 24 h. Never touches a live process's files, a held lock, or Claude Code session dirs. `hos_bootstrap.sh` installs a machine copy at `~/.local/share/hos/tmp_reaper.py`. The operator schedules **that copy**, never a clone's, as a daily entry in their own crontab, using the recipe in `docs/CRON-SETUP.md` (HOS never installs the crontab entry); `--root`, `--hos-tmp-root`, `--no-scratch`, `--dry-run`, `--measure` | `bootstrap/tmp_reaper.py` (source); `~/.local/share/hos/tmp_reaper.py` (machine copy) |
>
> | Resolving this clone's per-role disk temp dir (`HOS_TMP_ROOT`, `TMPDIR`) | `bootstrap/lib/hos_tmp_root.py` |

After the table, add these sentences: *"HOS temp lives on disk in `<clone>/../.tmp/<RoleDir>` (`HOS_TMP_ROOT` in `config.sh`). The launchers export `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` there. Start interactive sessions through `bin/hos-human`, or export `CLAUDE_CODE_TMPDIR` yourself; otherwise sandboxed Bash puts temp in the RAM-backed `/tmp/claude`. `/tmp/claude/` remains the place for small draft files such as PR and issue bodies. Test runs clean up their own temp files when they complete. The suite enforces zero leaked temp entries and a 50 MiB budget per session (`tests/conftest.py`, #2054), and a red `TMP_HYGIENE FAIL` is a real failure, not flake."*

In the **Repo layout** block, under `bootstrap/`, add one line: `tmp_reaper.py  MACHINE /tmp reaper (#2054); operator installs it in their own crontab`.

`bootstrap/README.md` gets the same one-line entry.

### 8.4 `docs/CRON-SETUP.md`

Add a new section, "HOS temp on disk and the per-machine reaper". It contains:
- **Where temp lives.** `HOS_TMP_ROOT` (§2A), the per-role `TMPDIR`/`CLAUDE_CODE_TMPDIR`/`HOS_TMP_DIR` the launchers export, the 0700 dirs, the temp-dir separation (not a role-integrity boundary, #2056), the cross-role janitor (R3-6), the advice to start interactive sessions through `bin/hos-human`, and why `/tmp/claude` drafts stay on `/tmp`.
- **The daily recipe** (§8.2) and its rules: user crontab only, explicit roots, a log path outside `/tmp`, an inner budget below the outer bound, and `gtimeout` on macOS.
- **The low-space trigger** (§8.5). A `bin/hos-cron` cycle reaps on its own only when a write probe fails, and that event is audited as `cycle-tmp-reap`.
- What the reaper removes and what it never touches.
- That class S is on by default and is disabled with `--no-scratch`.
- That HOS never installs the crontab entry.

The section also states that it supersedes the issue's original "cron-cycle wrap-up" placement, by human ruling.

### 8.5 `bin/hos-cron`: low-space trigger (disk-temp ruling; AC-8 and AC-9 restored, amended)

**Human ruling (2026-10-09).** At cycle start, `bin/hos-cron` runs a small write probe of its `TMPDIR` and of `/tmp`, catching EDQUOT/ENOSPC. On failure it runs the reaper, bounded, before preflight and auth, with the same 24 h rule.

- **Placement.** Exactly one call site, immediately after the §2A.3 `TMPDIR` export. That is:
  - after the overlap lock and the `_audit()` helper;
  - before the usage-pause gate, `validate_setup`, `get_app_token.sh` and all other preflight.

  This is AC-8's placement. It is the only cron site that can recover from a full quota, because a full quota kills the cycle at auth. Consequences:
  - it runs once per **lock-acquiring** cycle, for both roles, including cycles that later pause or fail preflight or auth;
  - it does **not** run on the suspended exit or the lock-held exit.
- **Dedicated bound (AC-9).** `_TR_BOUND` is `timeout --kill-after=5 30`, or `gtimeout --kill-after=5 30`, or empty if neither exists. Its numbers are named constants beside the array, never shared with `_UP_BOUND`. The inner `--max-seconds 20` is less than 30.
- **Invocation.** Only if `"$REPO_ROOT/bootstrap/tmp_reaper.py"` exists:
  `${_TR_BOUND[@]+"${_TR_BOUND[@]}"} python3 -I "$REPO_ROOT/bootstrap/tmp_reaper.py" --if-low-space --summary-only --max-seconds 20 --root /tmp ${_tr_hos_root_arg[@]+"${_tr_hos_root_arg[@]}"}`
  - `_tr_hos_root_arg=(--hos-tmp-root "$HOS_TMP_ROOT_RESOLVED")` is set only when §2A.3 resolved the root. Otherwise it is empty, and only `/tmp` is probed.
  - Class S stays on (the default). A scheduled `hos-cron` runs unsandboxed and has the host view. If it ever does not, class S refuses on its own (§5.7.1).
  - Capture stdout and rc with `|| _tr_rc=$?`. Echo each line prefixed with `$LOG_PREFIX`.
- **The probe is the decision.** All shell-side decision logic stays out of `hos-cron` (#314). The probe, the low/ok verdict and the reap all live in `tmp_reaper.py --if-low-space` (§5.1).
- **Audit.** Emit `_audit cycle-tmp-reap "rc=<rc>" "probe=<TMP_REAPER_PROBE line or ->" "summary=<TMP_REAPER line or ->"` **only** when rc ≠ 0 or the output contains `TMP_REAPER_PROBE low`. Healthy cycles add no record (#1803). A timeout (rc 124 or 137) is therefore always audited.
- **Never fatal.** Whatever the rc, the cycle continues to the usage-pause gate. Nothing later reads the trigger's output or rc.
- **Cost on a healthy cycle.** Two 64 KiB writes plus fsyncs, one listing per root, and no `/proc` scan, because the reap does not run.

---

## 9. Acceptance procedure (the coder records the evidence in the PR)

1. Run `python3 bootstrap/tmp_reaper.py --measure --max-seconds 600 --root /tmp --hos-tmp-root <HOS_TMP_ROOT>`. Record `user_bytes`, `pytest_runs`, `empty_tmp_dirs` and `tmp_files` (M0).
   - The coder also records `findmnt -no FSTYPE -T <HOS_TMP_ROOT>` (expected: a disk filesystem, not `tmpfs`).
   - The coder confirms that `pytest-of-<user>` for the inner-loop run appears under `<HOS_TMP_ROOT>/<RoleDir>/`, not under `/tmp`.
2. Run `scripts/framework/run_tests_inner_loop.sh`, then `--measure` (M1). Run the suite again, then `--measure` (M2).
3. Pass criteria. These are the **Layer 1 evidence** that the runs cleaned up after themselves:
   - `M2.user_bytes − M0.user_bytes ≤ 50 MiB`;
   - `M2.pytest_runs ≤ M0.pytest_runs`, excluding concurrently live runs, which the coder names;
   - `M2.empty_tmp_dirs ≤ M0.empty_tmp_dirs`;
   - `M2.tmp_files ≤ M0.tmp_files`;
   - both runs print `TMP_HYGIENE … leaks=0`.
   
   The inner loop runs the reaper first (§8.1, classes P/T), so M1 and M2 may also show backlog removal. Record the reaper's `REAP` count from each run's log separately.
4. **Layer 2 evidence.** The human runs `python3 bootstrap/tmp_reaper.py --dry-run --root /tmp --hos-tmp-root <HOS_TMP_ROOT>` (class S on by default) in an unsandboxed shell. Inside the sandbox, class S reports `scratch-disabled no-host-view`.
   - Record the `WOULD-REAP` counts by class and reason, and each `WOULD-REAP S` path.
   - Confirm that no `WOULD-REAP` names a path younger than 24 h.
   - Never run a real reap of the dev-host backlog from an agent session (§11).
5. These numbers are not a CI gate (§6.1). The deterministic gates are D6 and the static tests.

---

## 10. Tests

### S1

| ID | Test (file) | Asserts |
|---|---|---|
| T1 | `tests/framework/test_tmp_hygiene_plugin.py` | **Retention, sequential only (AC-11).** Generate a mini project in `tmp_path`. Its conftest loads `tests/tmp_hygiene.py`, and its D1 ini values are read **from the real `pyproject.toml`**. Run `python -m pytest` with `PYTEST_DEBUG_TEMPROOT=<tmp_path>/root`. (a) Green → no `pytest-N`. (b) Red → exactly 1. (c) Red, green, red → ≤ 1, and it is the newest. There is no concurrent-retention assertion. |
| T2 | same | **Leak gate.** A mini test calling `tempfile.mkdtemp()` gives exit 1 and a `TMP_HYGIENE FAIL leak` line naming the path. The `subprocess.run(["mktemp"])` variant is also caught. A leak reachable only through a `TemporaryDirectory` held in a reference cycle is *not* reported, which proves `gc.collect()` runs (AC-7). |
| T3 | same | **Budget gate.** `HOS_TEST_TMP_BUDGET_MB=1` plus a 2 MiB session-scoped dir gives exit 1 with `FAIL budget`. `=500` is ignored with a warning, and the budget stays 50. |
| T4 | same | **Red run.** A failing test plus a leak gives exit 1 and the report, with no `FAIL leak` escalation. |
| T5 | same | **flock and record.** While a mini session runs, `flock(LOCK_EX\|LOCK_NB)` on `.hos-live` from the outer process fails. After exit it succeeds. The record's `dev`/`ino` equal `os.stat(.hos-live)` (AC-4). |
| T6 | same | **In-process nesting and restore (AC-5, AC-6).** Inside an outer test session, run an inner `pytest.main([... , "--basetemp", <tmp_path>/inner])`. Afterwards the outer stash state (fd, paths) is unchanged, `TMPDIR` and `tempfile.tempdir` equal the outer `session-tmp`, and the outer flock is still held (a fresh fd's `LOCK_NB` probe fails). In a standalone mini session, a `trylast` session-finish hook sees `TMPDIR` and `tempfile.tempdir` already restored. |
| T7 | `tests/framework/test_tmp_hygiene_static.py` | **D10/AC-14.** An AST scan of `tests/**/*.py` fails on `tempfile.mkdtemp`, `tempfile.mkstemp`, and `NamedTemporaryFile` with the keyword `delete=False`. It resolves aliases: `import tempfile as t`, `from tempfile import mkdtemp as m`, and `from tempfile import NamedTemporaryFile`. Its own `(path, reason)` allowlist starts empty. It also asserts: (i) the `pyproject.toml` D1 values; (ii) `LEAK_ALLOWLIST` is empty, unconditionally (AC-13); (iii) no test sets `TMPDIR` to the literal `"/tmp"` via `monkeypatch.setenv` or `os.environ` (§4.9). |
| T8 | (existing) full inner loop | Green with `leaks=0`; footprint recorded. |
| T11 | `tests/framework/test_tmp_hygiene_plugin.py` | `child_env` adds `TMPDIR` when absent and never overrides a caller-set `TMPDIR` (AC-12). |

### S2b (`tests/framework/test_tmp_reaper.py`, every test with `--root`/`--hos-tmp-root` under `tmp_path`; no test touches the real /tmp or a real HOS tmp root)

"Old" means mtimes backdated ≥ 48 h. Where ctime matters, the test uses the pure `decide()` or the injected clock (§5.1). Class-S tests run in process, with the §5.7.1 host-view preconditions monkeypatched to pass, except where a row says otherwise. They therefore also run inside the sandbox.

| ID | Asserts |
|---|---|
| R1 | **A live run is never touched.** A child creates `pytest-of-<user>/pytest-5/.hos-live` with a valid record, plus `.lock`, flocks it, and sleeps. With the dir old, the real and `--dry-run` reapers both print `SKIP live-flock`, and the tree is byte-identical. After the holder gets **SIGKILL** → `REAP dead-flock`. |
| R2 | Legacy `.lock`, no `.hos-live`: quiet 3 h → `SKIP fresh`; quiet 23 h → `SKIP fresh`; old → `REAP legacy-stale` (uniform 24 h, D11). |
| R3 | Legacy `.lock` naming a live child whose argv contains `pytest`, old → `SKIP live-proc` (skipped if `/proc` is absent). |
| R4 | Quiet < 24 h beats a dead flock → `SKIP fresh`. |
| R5 | Two old lock-free finished dirs → **both** are REAPED (R3-3: no keep-newest). |
| R6 | **Symlinks.** `pytest-of-<user>` is a symlink → nothing reaped in class P. `pytest-7` is a symlink to an outside dir → the outside dir is intact. A reaped dir containing a symlink to an outside file → the outside file is intact. A dangling `pytest-current` is removed; a valid one is kept. |
| R7 | `decide()` with synthetic facts: uid mismatch → SKIP; probe error ≠ EWOULDBLOCK → SKIP unknown; absent PID → never REAP by itself; index `complete=False` → SKIP proc-scan-incomplete; a `/proc`-absent index removes the veto but never creates a REAP on its own. |
| R8 | Class T: old empty `tmpabcd1234` → removed. Non-empty → handed to class S (RS16), and with `--no-scratch` → `SKIP non-empty`. 23 h → SKIP. Old `tmp.AbCdEf1234` file → removed (D12). Old `tmpabcd1234.py` file → removed. File held open by a live child → `SKIP open` (Linux). FIFO → SKIP. Non-matching names untouched. |
| R9 | Old `garbage-*` → reaped; 23 h → SKIP. |
| R10 | `--dry-run` leaves the tree identical (names, inodes, mtimes) and prints `WOULD-REAP`. |
| R11 | Two concurrent reapers: both exit 0, every candidate is gone, no traceback. |
| R12 | Root resolution with no flags: TMPDIR set → used; unset → `/tmp` (unit-test the resolver only). All given roots missing → exit 3; one of two missing → `SKIP root-invalid` and the other is swept. `geteuid()==0` (monkeypatched) → exit 3. |
| R13 | The `TMP_REAPER_RUN` line is first. The summary line is last and matches the §5.5 regex. `--measure` deletes nothing and prints a numeric `user_bytes`. |
| R14 | `--max-seconds 0` → `truncated=1`, exit 0, and nothing reaped. |
| R15 | **AC-1 routing (R3-3).** An old **finished red** dir (unlocked `.hos-live`, no `.lock`) → `REAP finished`, **not** `dead-flock`. An old dir with an unlocked `.hos-live` **and** a `.lock` → `REAP dead-flock`. |
| R16 | **AC-4.** `.hos-live` whose record `dev`/`ino` mismatch → `SKIP unknown`. A FIFO named `.hos-live` → `SKIP unknown`, and the reaper returns within the test timeout (no hang). A symlink named `.hos-live` → `SKIP unknown` (`O_NOFOLLOW`). |
| R17 | **AC-3.** An old lock-free finished dir that is the `cwd` of a live child → `SKIP live-proc` (Linux). The same holds for an old dead-flock dir (the stricter rule-2 veto). |
| R18 | **D11.** `--min-age-hours 2` → exit 2. `--min-age-hours 48` is accepted. |
| R19 | **AC-10.** Default and `--summary-only` runs print `user_bytes=-` and no `WARN` line. They never call the size-walk function, asserted in process by monkeypatching the walk to raise. Under `--measure`, with the large-entry threshold monkeypatched down to a small value, a user-owned non-candidate tree above it produces one `WARN large-unowned`. **R3-5:** so does a `claude-1000` dir above the threshold in an `--hos-tmp-root` role dir, and that dir is never reaped in any mode. |
| RS1 | **Class S: a stale tree is removed.** In process, with default flags (class S on) and `clock = real + 48 h`, the tree holding `<tmp_path>/claude/clone1/a/b/c.txt` → `REAP S scratch-stale`. The tree is gone and no `garbage-hos-*` is left. |
| RS2 | **One recent deep file keeps the tree.** As RS1, but `a/b/c.txt` is `os.utime`-d to `fake_now − 1 h` → `SKIP fresh-deep`, and the tree is byte-identical. |
| RS3 | **A tree that is some process's cwd is kept.** A child process `chdir`s into `<tmp_path>/claude/clone2/sub` and sleeps → `SKIP live-proc` (Linux; skipped if `/proc` is absent). After the child is killed → `REAP`. |
| RS4 | **A held flock keeps the tree.** A child holds `flock(LOCK_EX)` on `<tmp_path>/claude/clone3/x/index.lock` → `SKIP held-lock`. A second variant holds an `fcntl.lockf` POSIX lock on a file **not** named like a lock (`data.bin`), which proves the `/proc/locks` path → `SKIP held-lock`. That variant also asserts, via a spy on `parse_proc_locks`, that the matched triple came from the **hex** `major:minor` parse (R2-5). After release → `REAP`. The `/proc/locks` variant reads the real file, so it is skipped where the reader lacks the holder's PID namespace. The pure parser tests (RS15) always run. |
| RS5 | Symlinks: a scratch child that is a symlink → untouched. A tree containing a symlink to an outside dir → reaped, and the outside dir is intact. A `claude` scratch root that is a symlink → `SKIP scratch-root-invalid`, nothing reaped. |
| RS6 | Session-dir exclusion: `<tmp_path>/claude-1000/...` is never evaluated. A scratch child named `claude-1000` → `SKIP session-dir`. A tree containing a `scratchpad` dir, or a UUID-named dir at depth ≤ 3 → `SKIP session-like`. A tree containing the reaper's cwd (in-process `monkeypatch.chdir`) → `SKIP self`. |
| RS7 | Fail-safe walk: `SCRATCH_MAX_INODES` monkeypatched to 2 → `SKIP walk-truncated`, tree intact. A `chmod 000` subdir → `SKIP unreadable` (skipped as root). A FIFO inside → `SKIP special`. |
| RS8 | Run-level gating: `--no-scratch` → no class-S output, `scratch_trees=-`. With the real preconditions **not** monkeypatched and the NSpid/`bwrap` check made to fail, or `/proc/locks` unreadable, or an incomplete index (each monkeypatched at its source) → one `SKIP scratch-disabled <reason>`, and nothing in class S is deleted. |
| RS9 | Removal identity (R2-2): (i) between the walk and the rename, swap the tree for a different dir at the same path (a test hook between steps 7 and 8) → `SKIP raced`, `os.rename` never called (spy), and both dirs intact; (ii) monkeypatch `os.lstat` so the post-rename `(st_dev, st_ino)` differs from `walked_id` → `ERROR identity-changed`, `shutil.rmtree` never called (spy), and `garbage-hos-*` remains; (iii) `--dry-run` → `WOULD-REAP S` and no rename. |
| RS10 | `decide_scratch()` (pure) with synthetic facts: foreign uid, cross-device entry, held-lock hit, fresh-deep, session marker and other-class name each give the named SKIP. Only the all-clear fact set yields REAP. Size and git facts are not inputs. |
| RS11 | **Git state is not a veto (human ruling §12.1).** The test builds repos under `tmp_path`; the test may run git, the reaper may not. All are old: (a) a clone with an unpushed local commit, (b) a detached unpushed `HEAD`, (c) a linked worktree whose `.git` is a file, and its main repo, (d) a repo with `refs/stash`. Each → `REAP S scratch-stale`. A spy on `open` shows that no file under any `.git` was opened, except lock-name probe targets. |
| RS12 | **Never executes (R2-1, kept).** Monkeypatch `subprocess.Popen`, `subprocess.run`, `os.system`, `os.posix_spawn`, `os.posix_spawnp`, `os.fork` and every `os.exec*` to raise, then run a full default reap over the RS11 fixtures in process → exit 0, with the expected verdicts and no raise. A static assertion checks that `bootstrap/tmp_reaper.py` imports neither `subprocess` nor `pty`. |
| RS13 | **No size floor (human ruling §12.1(e)).** A stale tree holding one 4 KiB file → REAP. A stale 1 MiB tree → REAP. |
| RS14 | **Other classes and order (R2-7).** Scratch-root children `pytest-of-x`, `garbage-abc`, `tmpabcd1234` and `hos-foo`, all old → `SKIP other-class`, untouched. `garbage-hos-…` is still handled by step 9. With an old class-P candidate, an old class-T file and a class-S tree, and `--max-seconds` exhausted by a deliberately slow class-S walk (injected clock), P and T are reaped and the S tree reports `SKIP walk-truncated`. |
| RS15 | **Preconditions (R2-5, R2-6).** Pure `parse_proc_locks`: `"1: FLOCK  ADVISORY  WRITE 1234 00:26:12345 0 EOF"` → `{(0, 38, 12345)}`. A malformed line anywhere → raises, and a run fed that text prints `SKIP scratch-disabled locks-unparseable`. The NSpid check runs before `/proc/locks` is opened (call-order spy). An index with `n_unreadable=3` and `complete=True` → class S runs and prints `SKIP proc-unreadable 3`. `complete=False` → `scratch-disabled proc-scan-incomplete`. |
| RS16 | **Shape 2: non-empty top-level `tmp*` dirs (human ruling §12.1(d)).** An old `<tmp_path>/tmpabcd1234/x/y.txt` → `REAP S scratch-stale`, removed via `<tmp_path>/garbage-hos-*`. With one deep file at `fake_now − 1 h` → `SKIP fresh-deep`. With a held flock inside → `SKIP held-lock`. As a live child's cwd → `SKIP live-proc`. With `--no-scratch` → `SKIP non-empty` (class T), intact. A leftover old `<tmp_path>/garbage-hos-…` → reaped by step 9. |
| RS17 | **Multiple roots (disk-temp ruling).** `--hos-tmp-root <tmp_path>/.tmp` with children `Worker/`, `Overseer/`, `Human/`, `Local/`, a lowercase `worker/`, `junk/`, a file `notes`, and a symlink `evil -> /elsewhere`. Only the four **capitalised** role dirs are swept. The others get `SKIP not-a-role-dir`, including lowercase `worker/` (skipped on case-sensitive filesystems). The `.tmp` dir itself is never a candidate. Old killed-run `pytest-N` dirs under `Worker/pytest-of-<user>/` and `/tmp`-equivalent `--root` are both reaped in one run. Duplicate roots, given as the same path twice or through a symlinked alias, are swept once. |
| RS18 | **`--if-low-space`.** (a) Both roots writable → `TMP_REAPER_PROBE ok`, nothing reaped even with old candidates present, exit 0. (b) Monkeypatch `os.write` to raise `OSError(EDQUOT)` for one root's probe fd → `TMP_REAPER_PROBE low roots=<that root>`, then a normal reap over **all** roots: old candidates go, young ones stay. (c) `ENOSPC` is handled the same way. (d) In every case no `.hos-space-probe.*` file remains, and a pre-existing orphan probe dotfile is never reaped. (e) The 24 h rule is unchanged: a 23 h candidate survives a low-space reap. |
| C1 | `tests/framework/test_run_tests_inner_loop.py`: with the reaper stub placed at `bootstrap/tmp_reaper.py` in the replica, it runs before `regen_all.sh` with `-I … --summary-only --no-scratch --max-seconds 20 --root <TMPDIR> --root /tmp`. Reaper rc=1 → the suite's exit code is unchanged. Existing tests (reaper absent) are unchanged. |
| C2 | **Low-space trigger, AC-8 restored as amended** (`tests/automation/test_hos_cron.py`, reaper stub installed): (a) invoked **exactly once** per lock-acquiring cycle, with `--if-low-space --summary-only --max-seconds 20 --root /tmp --hos-tmp-root <fake parent>/.tmp`; (b) the `--hos-tmp-root` pair is absent when the §2A.3 resolver is stubbed to fail; (c) still invoked once when the `get_app_token.sh` stub fails; (d) **not** invoked when suspended or lock-held; (e) invoked after `TMPDIR` is exported and before the usage-pause helper (shared stub log); (f) stub output `TMP_REAPER_PROBE ok` with rc 0 → no audit record; (g) stub output `TMP_REAPER_PROBE low …`, or rc 1 → one `cycle-tmp-reap` record, and the cycle exit is unchanged; (h) a stub that sleeps past the bound is killed and the cycle continues (if `timeout` exists). |
| C4 | **Packaging, static** (new `tests/framework/test_tmp_reaper_packaging.py`): (a) `bin/hos-cron` references `tmp_reaper.py` exactly once, on a line containing `--if-low-space`, and never `tmp_reap_scratch`; (b) `docs/CRON-SETUP.md` contains a recipe line that invokes `tmp_reaper.py` through `timeout --kill-after=`, **at a script path that contains `.local/share/hos/` and is not under `Code/` or any clone path (R3-4)**, whose `--max-seconds` value is strictly less than its timeout value, whose `>>` log target does not start with `/tmp`, which passes `--root /tmp` and at least one `--hos-tmp-root`, and which is scheduled daily (numeric minute and hour fields, `*` day fields); (c) `bootstrap/hos_bootstrap.sh` copies `tmp_reaper.py` to `~/.local/share/hos/tmp_reaper.py` with mode 0755 and idempotently. This is asserted behaviourally, by running the copy step twice under a fake `HOME`: the second run is a no-op, and a missing source gives a WARN and exit 0. `bootstrap/hos_install.sh` mentions the machine copy. Neither script *invokes* `crontab`: every occurrence of the word is in a comment, or inside an `echo`/`printf` argument or heredoc message (R3-4); (d) `CLAUDE.md` has the §8.3 row pointing at `bootstrap/tmp_reaper.py` and the machine copy; (e) `scripts/framework/cut_release.sh` `ASSET_NAMES` includes `tmp_reaper.py`. |
| C3 | `tests/framework/test_consumer_framework_files.py`: `bootstrap/tmp_reaper.py` is listed in `framework_consumer_files.txt` and exists, and `scripts/framework/tmp_reaper.py` does not exist. |

### S3

| ID | Asserts |
|---|---|
| T9 | `test_tmp_template_static.py`: none of the AC-14 literal-`/tmp` mktemp forms appear outside the allowlist. A self-test feeds each form (`/tmp/x.XXXX`, `-p /tmp`, `-p/tmp`, `--tmpdir=/tmp`, `--tmpdir /tmp`, `-t /tmp/x.XXXX`) through the matcher. |
| T10 | Existing gate and validator tests stay green. The inner loop stays green with G-leak covering the converted scripts. |

---

## 11. Files and slicing: one PR, four ordered commits (AC-15, amended by the disk-temp ruling)

One PR. Each commit must pass the inner loop on its own, so the human can review commit by commit, and S1 can be cherry-picked out without a redesign. AC-15 approved three commits. The disk-temp ruling splits round 2's S2 into **S2a** (where temp lives) and **S2b** (the reaper), because the reaper's roots and trigger depend on S2a.

| Commit | Files | Protected? |
|---|---|---|
| **1. S1: tests only (Layer 1). UNCHANGED by every round-3 ruling.** | `pyproject.toml` (pytest ini); `tests/conftest.py`; new `tests/tmp_hygiene.py`; new `tests/framework/test_tmp_hygiene_plugin.py` and `tests/framework/test_tmp_hygiene_static.py`; the ~18 test files of §7.1; the §4.8 `child_env` sites; `tests/automation/test_dimension_sweep_cli.py` and `tests/automation/test_agent_invoke_wrapper.py` (§7.2) | No. **Sole permitted exception:** a script fix that §4.9 requires to keep this commit green. It is limited to TMPDIR correctness or a cleanup trap, and is named in the commit message and the PR body. |
| **2. S2a: disk temp root (Layer 0)** | new `bootstrap/lib/hos_tmp_root.py`; `scripts/framework/config.sh` (`HOS_TMP_ROOT="../.tmp"`); `scripts/framework/install.sh` (prompt, default, refusal); `bin/hos-cron` (§2A.3 export only); `bin/hos-human`; `scripts/framework/run_tests_inner_loop.sh` (§2A.3 `TMPDIR` inherit/derive); `contract/sandbox-policy.template.json` (§2A.4); `scripts/framework/gen_sandbox_config.py` (D15 guard); `docs/SANDBOX-POLICY.md`; `scripts/framework/framework_consumer_files.txt` (ship `bootstrap/lib/hos_tmp_root.py`); new `tests/framework/test_hos_tmp_root.py` and `tests/framework/test_hos_human_launcher.py`; `tests/framework/test_gen_sandbox_config.py`; `tests/automation/test_hos_cron.py` (L1); `tests/framework/test_run_tests_inner_loop.py` (L3); `tests/framework/test_install*.py` (I1) | Yes |
| **3. S2b: machine reaper, triggers and docs (Layer 2)** | new `bootstrap/tmp_reaper.py`; new `tests/framework/test_tmp_reaper.py` and `tests/framework/test_tmp_reaper_packaging.py`; `scripts/framework/run_tests_inner_loop.sh` (§8.1 pre-run); `bin/hos-cron` (§8.5 low-space trigger); `scripts/framework/framework_consumer_files.txt`; `bootstrap/hos_bootstrap.sh` (idempotent machine copy to `~/.local/share/hos/`, plus an informational note; R3-4); `bootstrap/hos_install.sh` (informational note only); `scripts/framework/cut_release.sh` (`ASSET_NAMES` + printed bundle loop gain `tmp_reaper.py`; R3-4); `bootstrap/README.md`; `CLAUDE.md`; `docs/CRON-SETUP.md`; `tests/framework/test_run_tests_inner_loop.py` (C1); `tests/automation/test_hos_cron.py` (C2); `tests/framework/test_consumer_framework_files.py`; `SCRIPTS-INDEX.md` and CODEOWNERS regenerated via `regen_all.sh` | Yes |
| **4. S3: literal-/tmp script fixes. UNCHANGED in content** (all sites become `"${TMPDIR:-/tmp}"`, human item 5) | `scripts/oversight/run_validators.sh`, `scripts/oversight/gates/secret_scan.sh`, `scripts/oversight/gates/security_scan.sh`, `scripts/framework/validate_agents.sh`, `scripts/framework/validate_scripts.sh`, `bootstrap/hos_install.sh` (traps); new `tests/framework/test_tmp_template_static.py` | Yes |

- **The PR as a whole** touches protected surfaces and needs human approval (CODEOWNERS). The combined risk tier is HIGH, for two reasons: a recursive delete, and a change to the shipped sandbox template and every launcher's `TMPDIR`. Second review runs at HIGH (agy + codex) over the full diff, with an explicit `--tier HIGH`.
- In commit 3, the `allocated_bytes()` walk moves from `tests/tmp_hygiene.py` into `bootstrap/tmp_reaper.py`. The plugin then loads it via `load_module_from_path` (one implementation, D41). Scripts never import from `tests/`.
- **S1 coder note.** Nothing in S1 changes. S1 must pass whether `TMPDIR` is unset (`/tmp`) or set to a disk role dir, because every S1 mechanism follows `TMPDIR`. T1 and the other mini-project tests already pin `PYTEST_DEBUG_TEMPROOT` under `tmp_path`.
- **One-time backlog.**
  - The `/tmp` backlog of class T entries and class P dirs is removed by the first inner-loop run after merge (`--root /tmp`, §8.1), for every entry older than 24 h.
  - Class S trees are removed by the daily crontab entry once the operator installs it, or by a low-space trigger.
  - A human may run `--dry-run` first.
  - **Never delete the backlog inline from an agent session.**

---

## 12. Open questions: resolved

| # | For | Question | Resolution |
|---|---|---|---|
| Q1 | human | Should class T reap regular files older than 24 h? | **YES** (human ruling, 2026-10-09). D12, §5.4. |
| Q2 | architect | Session-wide TMPDIR redirect? | **ACCEPTED** with AC-5/6/7/12. Breakage policy in §4.9. It now nests under the role's disk dir (§2A). |
| Q3 | architect | Leak allowlist, or hold S1? | **Moot under a single PR.** `LEAK_ALLOWLIST` is empty at merge (AC-13). |
| Q4 | human | Budget value? | **50 MiB** (human, 2026-10-09). It can only be lowered, via env. It is measured on basetemp, which now lives on the disk root. |
| Q5 | architect | Reap on hos-cron early-exit paths? | AC-8 moved the call to cycle start. The packaging ruling removed the unconditional call. The disk-temp ruling **restored a conditional call** at the AC-8 placement: the low-space trigger (§8.5). It still does not run on the suspended or lock-held exits. |
| Q6 | human | Large ad-hoc trees such as `/tmp/claude/hos1935`? | **Superseded: DELETE when stale** (human rulings, 2026-10-09: *"We should have the cleanup script zap the large scratch copies if older than 24h"* and *"Anything older than a day goes."*). Class S (D13, §5.7) is on by default, has no size floor, and applies the full liveness bar. |
| Q7 | architect | Legacy `.lock` threshold? | **24 h ACCEPTED.** It is now the uniform D11 threshold. |

### 12.1 Human rulings, 2026-10-09: all RESOLVED

The human's words, verbatim:
- *"Yes. Anything older than a day goes."*
- *"The script will be a script per machine, so it should be shipped with HOS and consumer can install it in cron if needed."*
- *"RAM for pytest results etc is silly."*, with the hidden per-role disk root `<clone>/../.tmp/<RoleDir>` approved.

| # | Question | Human ruling | Where applied |
|---|---|---|---|
| (a) | Reap **all** of the user's `pytest-of-<user>` runs, `tmp*` orphans and class-S trees, including other repos'? | **YES.** | §5.3, §5.4, §5.7. Safety comes from the liveness checks, not from repo scoping. |
| (b) | Ship enabled to consumers? | **YES.** Class S is **on by default**, which overrides R2-4's per-host opt-in. The script ships in every consumer install. The per-machine opt-out is `--no-scratch`. There is no per-project key. | §5.1, §8.2–§8.4 |
| (c) | Reap at cron cycle start? | **YES, then reshaped.** The packaging ruling removed the unconditional call. The disk-temp ruling restored a *conditional* one, the low-space trigger. The routine sweep is the daily operator crontab. | §8.2, §8.5; Q5 |
| (d) | Delete non-empty `tmp*` dirs older than 24 h? | **YES**, through the full class-S procedure only. | §5.4, §5.7.2 shape 2, RS16 |
| (e) | 10 MiB size floor (R2-3)? | **NO.** Anything older than a day goes, whatever its size. | §5.7.4 step 6 removed; RS13 inverted |
| (f) | Unpushed-git-work veto (R2-1)? | **Dropped.** R2-1's **never-execute-git** rule is **kept**, and no git metadata is read. | §5.6, §5.7.4; RS11 inverted; RS12 kept |
| (g) | Where does HOS temp live? | **On disk, per role**: `HOS_TMP_ROOT` in `config.sh`, default the hidden `<clone>/../.tmp`, dirs `.tmp/{Worker,Overseer,Human}` at mode 0700. Each role's sandbox gets only its own dir. `/tmp/claude` drafts and `/tmp/claude-<uid>` stay on `/tmp`. | D14–D16, §2A |
| (h) | How often does the daily cron run, and is a trigger needed? | **Daily** is enough, given in-run cleanup. A **low-space trigger** at `hos-cron` cycle start covers a squeeze between runs. | §8.2, §8.5 |

The PR body records these rulings verbatim. Nothing in §12.1 remains open.

---

## 13. Self-flag

RISK: HIGH. Four things change:
1. Where every HOS role writes temp: the launchers' `TMPDIR`, the shipped sandbox template and the sandbox generator all change.
2. HOS ships a machine-level script that recursively deletes trees under `/tmp` and under every HOS disk temp root. By default that includes whole agent scratch trees (class S), with **no** size floor and **no** git-state protection, as the human ruled.
3. Three things run that script: a daily operator crontab (unsandboxed, class S active), a low-space trigger in `bin/hos-cron` (unsandboxed, class S active), and the inner-loop pre-run (`--no-scratch`).
4. On disk, a runaway now fills the root filesystem instead of hitting a per-user quota (§2A.6).

Safety rests on the following, all kept in full:
- the uniform 24 h age, taken over the whole tree for class S;
- the host-view requirement and a completely parsed `/proc/locks`;
- the live-process and held-lock vetoes;
- kernel flock semantics on a dev/ino-verified inode;
- the session-dir exclusions;
- the walked-identity re-checks;
- the ownership, device and pattern allowlists;
- explicit roots only, with role-named children only under `--hos-tmp-root`;
- refusal to run as root;
- no subprocess or exec;
- a 0700 per-role temp dir outside every work tree, granted to that role's sandbox only. This is a temp-dir separation, not a role-integrity boundary: every sandbox can already write every clone, a pre-existing grant tracked in #2056 (R3-2);
- an unsandboxed daily job that runs only the release-installed machine copy in `~/.local/share/hos`, never a mutable clone (R3-4).

A wrong rule could delete a live run's working dir or an idle agent's scratch work. A wrong sandbox entry could deny a role its own temp dir; that is fail closed, and the launchers fall back to `/tmp`. Neither failure can cross users.

CONFIDENCE: MEDIUM.
- Verified: the pytest behaviour (read from source and re-verified by the architect), and the cross-namespace flock behaviour and `/proc/locks` filtering (by experiment).
- Unverified: whether Claude Code honours `TMPDIR` for its own `claude-<uid>` dir (§2A.3 verification item), and the full-suite effect of a disk `TMPDIR` (the coder verifies it).
- The fifth-dir cause (§1.3 item 4) remains unknown.

BLAST RADIUS:
- S1: every pytest run in this repo.
- S2a: every HOS launcher invocation (worker, overseer, human); every inner-loop run; the shipped sandbox template and generator; consumer installs via `install.sh` and `config.sh`.
- S2b: every inner-loop run (classes P and T), every `hos-cron` cycle (the probe; a reap only when low), and every machine whose operator installs the daily entry (all classes).
- S3: six gate, validator and installer scripts.

Change classification (this revision): **structural**. The temp location, sandbox grants and slicing all change. Every structural element is **human-ruled** (the disk-temp, packaging and §12.1 rulings), so the CORE rule that "every structural change escalates to a human before writing" is satisfied by those rulings. The architect's round-3 check is still required. No code has been approved against any earlier body. S1, which the coder is building now, is explicitly unchanged, and S3 is unchanged in content. No sign-off is orphaned.

## Human Review Required

- The PR touches these protected surfaces: `bin/**` (`hos-cron`, `hos-human`), `bootstrap/**`, `contract/sandbox-policy.template.json`, `scripts/framework/**` (including `config.sh`, `install.sh` and `gen_sandbox_config.py`), `scripts/oversight/gates/**`, `scripts/oversight/run_validators.sh`, `docs/SANDBOX-POLICY.md` and `CLAUDE.md`. Human approval is mandatory under CODEOWNERS.
- §12.1 is fully resolved by the human rulings of 2026-10-09.
- The human is already adding the §2A.4 entries to the live Human `settings.local.json` by hand. After merge, `gen_sandbox_config.py --check` must report no divergence for that clone. If it does, the template and the hand edit disagree, and the template wins.

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

---

## Architect review (round 2 of 5, 2026-10-09)

**Verdict: APPROVED WITH CONDITIONS R2-1..R2-8.**
- Every round-1 condition, AC-1 through AC-16, is applied correctly. I checked each one against the body, not just against the mapping table.
- The human rulings (a)–(e) are applied faithfully.
- All of the remaining conditions are in **class S** (§5.7) and its call site.
- **Commit 1 (S1) and commit 3 (S3) are ready for the coder now**, because no R2 condition touches them. **Commit 2 (S2)** waits for technical-design to apply R2-1..R2-8 and for my round-3 diff check.

### Evidence gathered this round

- **`/proc/locks` is filtered by PID namespace. Verified** (scratchpad `flk/locks.sh`):
  - A flock held inside bwrap appears in the **host's** `/proc/locks`, with its host PID.
  - It is **absent** from `/proc/locks` read inside a second PID namespace.
  - So the §5.7.1 host-view precondition is load-bearing, not defence in depth. Without it, the lock veto silently passes inside a sandbox.
  - The device field is **hex** `major:minor`: `00:26` for `st_dev` 38.
- **Own-uid processes with unreadable `/proc` entries exist on this host:** `systemd --user`, `(sd-pam)` and `sshd-session`, which are non-dumpable (`EACCES` on `cwd`/`fd`).
  - "Index complete" must not mean "every process readable", or class S would never run.
  - See R2-6.
- **What `/tmp/claude` holds today:**
  - About 37 small agent draft files: PR bodies, commit messages and probes, the CLAUDE.md `--body-file` convention.
  - One small, fresh draft dir (`adr2033`).
  - `hos1935` is already gone.
  - The draft-dir case is why the size floor (R2-3) matters: idle drafts for an issue that is waiting on a human for more than 24 h would otherwise be deleted.
- **No own-uid process sets `TMPDIR` under `/tmp/claude`.** One process sets `TMPDIR=/tmp`. So `pytest-of-*` does not currently appear as a scratch child, but nothing prevents it. See R2-7.

### Rulings on technical-design's judgment calls

1. **Cron-only `--scratch` with refusal without a host view: APPROVED.** It is required, given the `/proc/locks` evidence above. R2-4 adds a configuration gate on top of it.
2. **No size floor: REJECTED.**
   - The human's words were "the **large** scratch copies".
   - Small trees contribute nothing to the quota, and they are exactly the agent draft dirs whose loss costs work.
   - Size is not a *safety* signal, but it is the *scope* signal the human used. See R2-3.
3. **§12.1(d): non-empty top-level `tmp*` dirs are report-only: APPROVED as the default.**
   - If the human answers "yes", these dirs must go through the class-S per-tree procedure: host view, whole-tree walk, lock and process vetoes, git check (R2-1) and floor.
   - That would be a second class-S root of a different shape, never a new age-only rule.
4. **`/proc` veto also on rule 2 and `garbage-*`: APPROVED.** It is strictly more conservative and costs nothing.
5. **The newest finished failed run is kept beyond 24 h: APPROVED.**
   - It is bounded to one dir, and the next completed session's own pytest cleanup supersedes it.
   - §0's "only entries older than 24 h" must name this single exception.
6. **S1 may carry a TMPDIR-correctness script fix: APPROVED.** This is consistent with Q2. If it is used, commit 1 touches a protected file, so "cherry-pick S1 out" also needs human review. That is harmless, because the whole PR is human-gated anyway.

### Binding conditions (round 2)

- **R2-1: class S must not destroy unpushed git work, and must never execute git.**
  - Ad-hoc clones are the main target, and a clone can hold the only copy of local commits.
  - Running `git` from the **unsandboxed** cron inside a tree that a **sandboxed** agent wrote would be a sandbox escape: repo-local `.git/config` keys such as `core.fsmonitor` or `core.pager` would execute on the host. So the check is **static file parsing only**.
  - For every `.git` entry found during the §5.7.4 walk:
    - (i) `.git` is a **file** (a linked worktree) → `SKIP git-worktree`. Deleting the dir would leave a registered worktree that blocks checking out that branch elsewhere.
    - (ii) `.git` is a dir → read `HEAD`, `refs/heads/**`, `refs/remotes/**`, `packed-refs` and `refs/stash`, with a byte cap on each.
      - Any local branch head, or a detached `HEAD` SHA, that does not equal some `refs/remotes/**` SHA → `SKIP git-unpushed`.
      - `refs/stash` present → `SKIP git-stash`.
      - Unparseable refs → `SKIP unknown`.
  - Uncommitted working-tree edits cannot be detected without git. Losing them after 24 h idle is within the human ruling, and is an accepted residual.
  - Add tests RS11 (unpushed branch kept; detached unpushed HEAD kept; worktree `.git` file kept; stash kept; pushed clone reaped) and RS12 (no subprocess is ever spawned: monkeypatch `subprocess` and `os.exec*` to raise).
- **R2-2: removal identity must be the walked identity.**
  - §5.7.4 step 7(a) records `(st_dev, st_ino)` at removal time, so a dir renamed into place after the walk would be deleted unverified.
  - Instead, compare against the identity captured at **step 1**, before the walk. A mismatch → `SKIP raced`, with no rename.
  - Keep the post-rename check at 7(c).
  - Extend RS9 to cover the case where the identity is swapped between the walk and the rename.
- **R2-3: size floor.**
  - `SCRATCH_MIN_BYTES = 10 * 1024 * 1024`, of allocated bytes from the walk. It is a protected constant with no CLI or env override.
  - A tree below the floor → `SKIP small`. The walk may stop early once it is clear that the tree is old, but the size total must be complete before REAP.
  - Add §12.1(e) as a merge-time human confirmation of the value.
  - Add test RS13: a stale 1 MiB tree is kept, and a stale tree above the floor is reaped.
- **R2-4: consumer default is off. Class S is opt-in per host.**
  - `bin/hos-cron` passes `--scratch` only when `projects.conf` has `${PROJECT}_tmp_reap_scratch=1`, read the same way `${PROJECT}_max_seconds` is. It is absent or `0` by default.
  - A destructive behaviour whose consumer scope is an unanswered human question (§12.1(b)) must ship with the safe default. The human's ruling then takes effect on this host by adding one host-config line, outside the repo. The PR body must say so.
  - Extend C2 so that `--scratch` is present only when the key is `1`.
  - §12.1(b) narrows to classes P and T, which ship on by default.
- **R2-5: `/proc/locks` parsing contract.**
  - Parse the `major:minor:inode` field with major and minor in **hex** and the inode in decimal. Match it against `os.major(st_dev)`, `os.minor(st_dev)` and `st_ino`.
  - Any line in the file that cannot be parsed → class S is disabled for the run (`SKIP scratch-disabled locks-unparseable`). Do not skip the line.
  - Evaluate the §5.7.1 NSpid host-view check **before** reading `/proc/locks`.
  - In RS4's POSIX-lock variant, assert that the matched entry came from the hex parse.
- **R2-6: define "complete index".**
  - `complete=True` means the scan was not cut short by `--max-seconds`.
  - Per-process `EACCES`/`ENOENT`/`ESRCH` is tolerated and counted. Print one `SKIP proc-unreadable <n>` informational line when n > 0 under `--scratch`.
  - Requiring every process to be readable would disable class S permanently on this host (non-dumpable session daemons).
  - Record this as an accepted residual: a non-dumpable same-uid process whose cwd is inside a stale scratch tree is invisible to the veto. Such processes are system and session daemons, not agent tools.
- **R2-7: class S must not swallow other classes' entries, and runs last.**
  - A scratch-root child named `pytest-of-*`, `garbage-*` (other than `garbage-hos-*`), `tmp*` or `hos-*` → `SKIP other-class`. This covers a future session that sets `TMPDIR=/tmp/claude`, whose `pytest-of-<user>` would otherwise be judged by whole-tree age, ignoring class P's keep-newest and flock rules.
  - Evaluate classes in the order **P, T, then S**, so that a long class-S walk exhausting `--max-seconds` only defers S.
  - A tree that hits `SKIP walk-truncated` is re-walked every cycle. That is an accepted cost, visible in the log.
- **R2-8: §0 accuracy.**
  - §0 Layer 2 must state the R2-3 floor and the R2-4 per-host opt-in for class S.
  - It must name the single exception to "only entries older than 24 h" (judgment call 5).
  - The CLAUDE.md row (§8.3) and the CRON-SETUP paragraph (§8.4) must state that class S runs only when the host enables it.

### What still could go wrong (accepted residuals, class S)

- Uncommitted working-tree edits in a pushed clone that has been idle for more than 24 h are deleted. This is within the human ruling, and is the reason R2-1 exists for committed work.
- A process could `chdir` into a tree in the milliseconds between the walk and the rename. This is narrowed by R2-2 and the complete-index requirement.
- A non-dumpable same-uid process is invisible to the veto (R2-6).

**Affected sign-offs:** none. No design or code has been approved against the round-2 body. R2-1..R2-8 touch only §0, §5.7, §8.2–§8.4, §10 (RS/C2) and §12.1, so S1/S3 work started now is not orphaned.

---

## Round-3 revision note (technical-design, 2026-10-09)

This revision applies, in order:
1. the architect's R2-1..R2-8;
2. the human's §12.1 answers: *"Yes. Anything older than a day goes."*;
3. the packaging ruling: *"The script will be a script per machine, so it should be shipped with HOS and consumer can install it in cron if needed."*;
4. the **disk-temp ruling**: *"RAM for pytest results etc is silly."*, with the hidden per-role root `<clone>/../.tmp/<role>` and the exact sandbox entry shape.

**Restructured, not just amended.** The disk-temp ruling moves the design's centre of gravity, from cleaning a RAM tmpfs to placing HOS temp on disk. These sections are therefore rewritten:
- §0 now has three layers, with **Layer 0: placement**;
- new §1.4 and §2A;
- new decisions D14–D16;
- §5.1, the roots model;
- §8.2 and the new §8.5;
- §10 S2a and S2b;
- §11, now four commits;
- §12.1 and §13.

**Change classification: structural.** Every structural element is human-ruled.

**Affected sign-offs.** None exist against the earlier bodies.
- **S1 is unchanged.** The S1 coder working in parallel needs no change.
- **S3 is unchanged in content.**

**Startup-artifact-gap check.** Should placement have been settled in the initial design? Arguably yes: the TD treated `/tmp`'s tmpfs nature as a given rather than as a decision. That gap was caught before any S2 code existed, and the S1 contract is placement-agnostic. No approved code is orphaned, so no `startup-artifact-gap` issue is needed. The coordinator may file one for the record if it wishes.

### R2 conditions

| Condition | Status | Applied in |
|---|---|---|
| **R2-1**: no destruction of unpushed git work; never execute git | **Split by human ruling.** The **git-state veto is dropped** (§12.1(f)): it is not a liveness check. The **never-execute** rule is **kept**, and no git metadata is read at all. | §5.6, §5.7.4 (git bullet), the §5.7 residuals; RS11 inverted (unpushed, stash and worktree trees are reaped, and no `.git` content is opened); RS12 kept |
| **R2-2**: removal identity = walked identity | **Applied.** `walked_id` is captured at step 1. Step 8(a) re-checks it before the rename (mismatch → `SKIP raced`, no rename), and 8(c) re-checks after the rename. | §5.7.4 steps 1 and 8; RS9(i) |
| **R2-3**: 10 MiB size floor | **Withdrawn by human ruling** (§12.1(e): "anything older than a day goes"). | §5.7.4 step 6 marked removed; RS13 inverted (stale 4 KiB and 1 MiB trees are reaped) |
| **R2-4**: class S opt-in per host via `projects.conf` | **Overridden by human ruling** (§12.1(b)). Class S is on by default; the opt-out is `--no-scratch` on the crontab line. The packaging ruling removed the per-project key entirely. | §5.1, §8.2; the C2 key tests are dropped |
| **R2-5**: `/proc/locks` parsing contract | **Applied.** Hex major:minor and decimal inode. Any unparseable line disables class S. The NSpid check runs first. | §5.7.1 items 2–3; RS4 hex-spy variant; RS15 |
| **R2-6**: definition of "complete index" | **Applied.** Complete means "not cut short by `--max-seconds`". Per-process EACCES/ENOENT/ESRCH errors are counted, and `SKIP proc-unreadable <n>` is printed. Non-dumpable daemons are an accepted residual. | §5.3.3, §5.7.1 item 4, §5.7 residuals; RS15 |
| **R2-7**: class S must not swallow other classes' entries, and runs last | **Applied.** Order is P, then T, then S, with a shared budget across roots. Scratch-root children named `pytest-of-*`, `garbage-*` (except `garbage-hos-*`), `tmp*` or `hos-*` → `SKIP other-class`. Truncated walks repeat; that cost is accepted. | §5.2, §5.7 intro, §5.7.2; RS14 |
| **R2-8**: §0 accuracy | **Applied, then re-stated** for the later rulings. §0 names the single over-24 h exception (newest finished failed run), says class S is on by default (no floor), names the three invocation paths, and names the disk-exhaustion residual. The §8.3 CLAUDE.md row and the §8.4 CRON-SETUP section state the machine-cron, explicit-roots and `--no-scratch` facts. | §0, §8.3, §8.4 |

### Earlier architect conditions superseded or amended by the round-3 human rulings (for the round-3 check)

| Condition | Effect | Where |
|---|---|---|
| **AC-8** (single cycle-start call site, not on suspended or lock-held exits) | **Amended twice.** The packaging ruling removed the *unconditional* call. The disk-temp ruling restored a *conditional* call at exactly AC-8's placement: the low-space trigger, which reaps only on a failed write probe. AC-8's "after lock and `_audit`, before usage-pause, preflight and auth; not on suspended or lock-held" holds unchanged for that call. The routine sweep is the daily operator crontab. | §8.2, §8.5; Q5 |
| **AC-9** (dedicated bound, inner < outer) | **Restated per caller.** The trigger uses `_TR_BOUND` `timeout --kill-after=5 30` with `--max-seconds 20`. The daily cron uses `timeout --kill-after=10 600` with `--max-seconds 540`. The inner loop uses `--max-seconds 20`, unwrapped (best-effort). | §5.1, §8.1, §8.2, §8.5 |
| **C2** (cron test) | **Restated.** C2 now tests the low-space trigger (placement, args, auth-failure case, suspended and lock-held, audit-only-when-low, bound). The static packaging assertions moved to the new **C4**. The `TMPDIR` export test is **L1**. | §10 |
| **AC-15** (one PR, three ordered commits) | **Amended: four commits.** S2 splits into S2a (disk temp root) and S2b (reaper and triggers), because S2b's roots and trigger depend on S2a. S1 and S3 are unchanged. | §11 |
| **AC-10** (per-cycle cost; `user_bytes` only under `--measure`) | **Kept; extended to multiple roots.** Counts are summed over roots. The summary field `root=` becomes `roots=<n>`, and the §5.5 regex is updated. The trigger's healthy-cycle cost is two 64 KiB probes plus listings, with no `/proc` scan. | §5.5, §8.5 |
| **AC-16** (merge-time human confirmations) | **Resolved** by the human. | §12.1 (a)–(h) |
| **§5.1 `--tmp-root`** (round 1) | **Replaced** by repeatable `--root` and `--hos-tmp-root`. The no-flag default is unchanged (`$TMPDIR` or `/tmp`). | §5.1; R12, RS17 |
| **D4 / D6 / Q4** (redirect, guardrail, 50 MiB) | **Unchanged in contract.** They now operate on the disk role dir, because basetemp follows `TMPDIR`. | §0, §2A.3, §12 |

### Disk-temp ruling (human, 2026-10-09; amended to the hidden `.tmp`)

| Requirement | Applied in |
|---|---|
| 1. `HOS_TMP_ROOT` in `config.sh`, chosen at install. Default `<clone>/../.tmp`. Single-clone fallback, justified. Per-role dir `$HOS_TMP_ROOT/<role>`. | D14; §2A.1. The fallback is `~/.local/state/hos/tmp/<slug>`: it avoids a shared `~/src/.tmp` mixing projects, and stays out of the sandbox's `~/.cache` re-allow. §2A.2 adds the resolver, which parses the value statically and never sources config. |
| 2. Launchers export `TMPDIR` and create it 0700 (`hos-cron`, `hos-human`, inner loop). S1 hygiene is kept, nested under the root. | §2A.3 (`hos-human` exports after the token mint, so the token temp file stays on RAM); L1–L3. S1 is unchanged (§11 note). |
| 3. Role isolation in the sandbox template, with exact entries. | §2A.4: the human's exact shape, `__HOS_ROOT__/.tmp/__ROLE__` in `additionalDirectories`, `allowRead` and `allowWrite`, plus `Read`/`Edit(...)/**` and `Bash(quota *)`/`Bash(findmnt *)`. **No new placeholder** (D15). The generator fails closed if `config.sh` moves the root or if `HOS_ROOT` is not under `HOME`. `/tmp` entries are unchanged. Enforcement for worker and overseer arrives with #1146, which is stated plainly. SANDBOX-POLICY.md §3 and §5 updates are specified. G1, G2. |
| 4. Keep `/tmp/claude` drafts and `/tmp/claude-<uid>` | §0 Layer 0, §2A.4 (the `/tmp` grants are unchanged), §8.3 CLAUDE.md sentence. Verification item: does Claude Code honour `TMPDIR` for its own dir (§2A.3)? |
| 5. S3 fixes use `"${TMPDIR:-/tmp}"` | §7.3 (already so); §11 commit 4 |
| 6. The reaper sweeps `/tmp` and every configured HOS root. Daily cron. Low-space trigger at cycle start. | §5.1 roots, chosen as explicit flags only (no discovery, which keeps the tool simple and non-executing); §8.2 daily recipe with explicit roots; §8.5 trigger via `tmp_reaper.py --if-low-space` (write probe catching EDQUOT/ENOSPC; `df` is not used); RS17, RS18, C2. |
| 7. `$HOS_TMP_ROOT` is never inside a git work tree; refuse at install. | D16; §2A.5 (static `.git` ancestor walk, plus not-inside-the-clone); the resolver falls back to `/tmp` and warns; `install.sh` refuses; H2, I1. |
| 8. Residual: disk exhaustion | §0, §2A.6, §13 |

### Choices beyond the rulings, flagged for the architect

- `local` is a fourth role name, for inner-loop runs that no launcher started. It is not granted in any sandbox template; the template is for launcher roles only.
- The inner loop's pre-run sweeps `--root "${TMPDIR:-/tmp}" --root /tmp`, so it also clears the `/tmp` class-P/T backlog.
- The trigger reaps **all** roots when **any** probe is low, because one quota or disk is shared.
- `TMP_REAPER_RUN` first line, and `roots=<n>` in the summary.

Requesting the architect's round-3 diff check (round 3 of 5).

---

## Architect review (round 3 of 5, 2026-10-09)

**Verdict: APPROVED WITH CONDITIONS R3-1..R3-6.**
- R2-2, R2-5, R2-6, R2-7 and R2-8 are applied correctly.
- R2-1 (git veto), R2-3 and R2-4 are correctly withdrawn or overridden by the human's rulings, and never-execute is kept.
- The disk-temp, packaging and §12.1 rulings are applied faithfully.
- Class S safety is unchanged from round 2 apart from the human-ruled scope widening (shape 2, no floor, no git veto). Every liveness check stands.
- **S2a and S2b are ready for the coder now.** R3-1..R3-6 below are fully specified and govern where they conflict with the body. technical-design folds them in. No round 4 is needed unless a condition is disputed.

### Evidence gathered this round

- **Claude Code overrides `TMPDIR` in sandboxed Bash.** Read from the installed CLI 2.1.295; see scratchpad `flk/cc_tmp.py`.
  - In sandboxed Bash commands, the child environment gets `TMPDIR = CLAUDE_CODE_TMPDIR || CLAUDE_TMPDIR || "/tmp/claude"`. That **replaces whatever `TMPDIR` the launcher exported**.
  - Claude Code's own dir is `join(Og(), "claude-<uid>")`, where `Og() = CLAUDE_CODE_TMPDIR || os.tmpdir()`. `os.tmpdir()` honours `TMPDIR`.
  - So: (a) exporting `TMPDIR` alone **does** move `claude-<uid>` into `.tmp/<role>/`. (b) Exporting `TMPDIR` alone does **not** reach sandboxed Bash children. In every sandboxed session (Human today; worker and overseer after #1146), tests would still land in `/tmp/claude`, which is RAM-backed **and** is the class-S scratch root. Layer 0 would silently fail exactly where it matters. See R3-1.
- **Sandbox template cross-role reach.** Every role's sandbox has `allowWrite` on `__HOS_ROOT__/{Human,Worker,Overseer}` and on `/tmp`. `__HOME__/.local/share` and `~/.hos` are readable but **not** writable from the sandbox. See R3-2 and R3-4.
- **No git work tree above the default root.** Neither `~/Code/HumanOversightSystem`, `~/Code` nor `$HOME` has a `.git`, so the default `../.tmp` passes D16 on this host.
- **`get_app_token.sh` creates no temp files.** The only token temp file is the caller's: `mktemp` in `hos-human` (honours `TMPDIR`) and `mktemp -p ~/.hos` in `hos-cron` (already on disk). The `hos-human` ordering is therefore sound, and the cron difference is harmless.

### Rulings on technical-design's open calls

1. **Fourth role `local`: APPROVED**, with the R3-1 resolution order. `local` is reached only when no launcher chose a dir. Inside a sandbox it is not writable, so the run falls back. That is a documented residual, not an error.
2. **Inner loop also sweeps `/tmp` with `--no-scratch`: APPROVED.** It is the only automatic path that drains the `/tmp` class-P/T backlog before an operator installs the crontab.
3. **Trigger sweeps all roots: APPROVED.** One quota or disk is shared, and a low probe on any root justifies the sweep. This crosses role dirs by design: the reaper is a machine janitor running as an unsandboxed process, not an agent. Per-role isolation governs *agent sessions*, so this does not breach it. §2A.4 must say so.
4. **Newest failed run kept past 24 h: OVERRIDDEN by the human's ruling ("Anything older than a day goes").** See R3-3.
   - Layer 1 still keeps the newest failed dir (pytest `count=1`) until the next completed session. That is the inspection window.
   - The reaper applies no KEEP-newest exception.
5. **`hos-human` exports `TMPDIR` only after the token mint: APPROVED.** The minted token's sourced file stays on the RAM-backed `/tmp` and never touches disk. `hos-cron`'s auth file already lives in `~/.hos`; that is pre-existing and unchanged.
6. **Single-clone default `~/.local/state/hos/tmp/<project>`: APPROVED.** Such clones are refused by the D15 generator guard, which is consistent with "only the multi-clone human role is generatable today".
7. **Resolver `bootstrap/lib/hos_tmp_root.py` parses `config.sh` statically: APPROVED.** Never sourcing is the right call for a value read by unsandboxed launchers. Add one test to H1: this repo's committed `config.sh` line parses to `../.tmp`. That guards against an edit that the shell accepts but the resolver rejects.
8. **Four-commit split S1/S2a/S2b/S3: APPROVED.**

### Binding conditions (round 3)

- **R3-1: export `CLAUDE_CODE_TMPDIR`, and fix the inner loop's resolution order.**
  - Every launcher in §2A.3 (`bin/hos-cron`, `bin/hos-human`) exports **three** variables on success: `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR`, each set to the resolved role dir. The placements are unchanged.
  - With `CLAUDE_CODE_TMPDIR` set, Claude Code gives sandboxed Bash children that dir as `TMPDIR`, and puts its own `claude-<uid>` there. Both are inside the role's granted `.tmp/<role>`.
  - `run_tests_inner_loop.sh` resolves its `TMPDIR` in this order:
    1. `HOS_TMP_DIR`, if set and an existing writable dir (a launcher chose);
    2. otherwise `resolve --role local --create`, used if it succeeds and the dir is writable;
    3. otherwise the inherited non-empty `TMPDIR`;
    4. otherwise unset, i.e. `/tmp`.
  - This replaces "inherit any non-empty `TMPDIR`", which in a sandboxed ad-hoc session would inherit Claude's `/tmp/claude` and put pytest back on the tmpfs, inside the class-S scratch root.
  - Residual: a sandboxed session that no launcher started (for example a plain `claude` in a worktree) cannot write `.tmp/local`, so it falls to step 3 (`/tmp/claude`). R2-7's `SKIP other-class` keeps class S off its `pytest-of-*`, and the inner-loop pre-run (`--root "$TMPDIR"`) reaps it as class P. The CLAUDE.md sentence (§8.3) must tell interactive users to start sessions through `bin/hos-human`, or to export `CLAUDE_CODE_TMPDIR`.
  - Tests:
    - L1 and L2 also assert `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR`.
    - L3 covers all four branches, including "inherited `TMPDIR=/tmp/claude` with `.tmp/local` creatable → `.tmp/local` wins".
  - Verification item, replacing the §2A.3 open question: in a launched Human session, a sandboxed Bash `echo $TMPDIR` prints `.tmp/human`. The coder records this in the PR.
- **R3-2: state the isolation guarantee accurately (§2A.4, §13).**
  - The per-role `.tmp/<role>` grant **does not widen any existing access**. `.tmp` lies outside every clone, and `denyRead __HOME__/` hides sibling role dirs.
  - It is a *temp-dir* separation, **not** a role-integrity boundary. Every role's sandbox can already write all three clones, including another clone's `scripts/framework/config.sh`, which sets that role's `HOS_TMP_ROOT`, and its `bin/hos-cron`. That cross-clone write grant is pre-existing and out of scope. Its consequence for this TD is that "the isolation guarantee" must be worded as "no role's sandbox is granted another role's temp dir". It must not be presented as protection against a role that tampers with another clone.
  - File a follow-up issue, worker-pipeline, not this PR: narrow the template's cross-clone `allowWrite` per role. That belongs with #1146.
- **R3-3: no KEEP-newest exception in the reaper (human ruling).**
  - §5.3.2 rule 4 becomes: no `.lock` → candidate **REAP finished**, subject to quiet ≥ AGE and the veto.
  - Delete NEWEST_FINISHED.
  - Keep AC-1's routing: a successful probe with no `.lock` goes to rule 4, not to `dead-flock`. It now matters only for the reason label.
  - §0 removes "the one exception".
  - R5 becomes: both old lock-free finished dirs → REAP.
  - R15 becomes: an old finished red dir with an unlocked `.hos-live` → `REAP finished` (not `dead-flock`).
  - The §3 R-2 and Layer 1 text is unchanged: pytest still keeps one failed dir until the next completed session.
- **R3-4: the daily crontab must not execute a mutable agent working copy.**
  - The §8.2 recipe runs `~/Code/HumanOversightSystem/Worker/bootstrap/tmp_reaper.py`. The worker cron checks out arbitrary branches in that clone, and every sandbox can write it. An **unsandboxed** daily job with recursive-delete power would then run whatever is checked out, or whatever a sandboxed agent wrote there.
  - Fix:
    - `bootstrap/hos_bootstrap.sh` (machine setup; it runs from the validated release bundle) idempotently copies `bootstrap/tmp_reaper.py` to `~/.local/share/hos/tmp_reaper.py`, mode 0755. That path is readable but **not writable** from every sandbox.
    - This is a file copy, **not** a crontab install, so the never-auto-install ruling holds.
    - The recipe invokes that copy.
  - C4(b) additionally asserts that the recipe's script path is not under `Code/` or any clone path, and contains `.local/share/hos/`.
  - C4(c) asserts that `hos_bootstrap.sh` copies the file and still never invokes `crontab`.
  - The `bin/hos-cron` low-space trigger keeps running `$REPO_ROOT/bootstrap/tmp_reaper.py`. That is the same trust level as `bin/hos-cron` itself, so it is not a new exposure.
- **R3-5: Claude Code's own dir on disk.** With R3-1, `claude-<uid>` lives in `.tmp/<role>/` on disk. Reboots no longer clear it, and the reaper never touches `claude-*`.
  - Record this as an accepted residual in §2A.6: Claude Code manages its own dir; it is 124 KB today.
  - Under `--measure`, `WARN large-unowned` must also report a `claude-<uid>` entry over 100 MiB in any root. That is visibility only, never deletion.
  - Extend R19.
- **R3-6: §2A.4 notes the cross-role janitor (ruling 3).** One sentence: the low-space trigger and the daily reaper act on every role's dir, as unsandboxed machine processes, which is outside the per-role sandbox grants by design.

### Accepted residuals (round 3, in addition to earlier rounds)

- A sandboxed session that no launcher started keeps temp on `/tmp/claude` (R3-1).
- Disk exhaustion replaces quota exhaustion (§2A.6), and Claude Code's dir persists across reboots (R3-5).
- Cross-clone write grants make role temp separation non-authoritative against a tampering role (R3-2). This is pre-existing.

**Affected sign-offs:** none. S1 (in progress) is untouched by R3-1..R3-6. S3 is unchanged. No S2a or S2b code exists yet.

---

## Round-3 fold-in note (technical-design, 2026-10-09)

R3-1..R3-6 are folded into the body. **No condition is disputed.** Change classification: clarifying + additive. Every element is architect-specified.

**Affected sign-offs.** None:
- S1 is untouched.
- S3 is unchanged.
- No S2a or S2b code had been approved.

**Startup-artifact-gap check.** The `CLAUDE_CODE_TMPDIR` override (R3-1) is the kind of fact the initial design should have verified. It was caught before any S2a code existed, so no issue is needed.

| Condition | Folded into |
|---|---|
| **R3-1**: export `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR`; inner-loop resolution order | §0 Layer 0. §2A.3: three exports in `hos-cron` and `hos-human`; the four-step inner-loop order replaces "inherit any non-empty `TMPDIR`"; the why paragraph; the no-launcher residual; the new verification item, `echo $TMPDIR` → `.tmp/Human`, capitalised per the later human ruling. §8.3 CLAUDE.md text tells users to start sessions through `bin/hos-human` or export `CLAUDE_CODE_TMPDIR`. L1, L2 and L3 (all four branches). |
| **R3-2**: accurate isolation wording; follow-up issue | §0 Layer 0, renamed "Role separation". §2A.4 heading and guarantee are reworded: "no role's sandbox is granted another role's temp dir"; this is a temp-dir separation, not a role-integrity boundary; the cross-clone write grant is pre-existing and tracked in **#2056** (v0.7.4). The SANDBOX-POLICY.md bullets and §13 are updated. |
| **R3-3**: no KEEP-newest in the reaper | §0 ("no exceptions"). §5.3.2: NEWEST_FINISHED deleted, rule 4 always gives `REAP finished`, and AC-1 routing is kept for the reason label. §5.6. R5 (both reaped), R15 (`REAP finished`, not `dead-flock`), R17. §3 R-2 and Layer 1 are unchanged. |
| **R3-4**: the daily cron never executes a mutable clone | §8.2: the recipe runs `~/.local/share/hos/tmp_reaper.py`. A new "Machine copy" paragraph has `hos_bootstrap.sh` copy the file idempotently and atomically, with mode 0755, from its own directory, with a WARN and no failure if the source is absent. The `hos-cron` trigger keeps the `$REPO_ROOT` copy, at the same trust level. §2A.4 notes that `.local/share` is read-only from sandboxes. §8.3 row. C4(b) checks the path contains `.local/share/hos/` and is not under `Code/`. C4(c) checks the copy behaviour and that `crontab` is never invoked. §13. **Implementation consequence (not a dispute):** `hos_bootstrap.sh` runs from the release bundle, so `tmp_reaper.py` must be in it. It is added to `cut_release.sh` `ASSET_NAMES` and the printed bundle loop, which reverses round 3's "not a release asset" (§8.2 Packaging, §11 S2b, C4(e)). |
| **R3-5**: Claude Code's dir on disk | §0 Layer 0 ("What moves"). §2A.6 accepted residual (persists across reboot, 124 KB today, never reaped). §5.4: `WARN large-unowned` covers `claude-<uid>` over 100 MiB in any root, under `--measure` only. R19 extended. |
| **R3-6**: the cross-role janitor | §2A.4: one paragraph saying the trigger and the daily reaper act on every role's dir, as unsandboxed machine processes, outside the per-role sandbox grants by design. Also in the SANDBOX-POLICY.md bullets. |
| Ruling 7: H1 test | H1 now asserts that this repo's committed `config.sh` line parses to `../.tmp`. |

**Human ruling (2026-10-09): capitalised per-role dir names.** Per-role temp dirs match the clone dir names: `<HOS_ROOT>/.tmp/Human`, `.tmp/Worker` and `.tmp/Overseer`. Direct inner-loop runs use `.tmp/Local`. In the body, the notation `<RoleDir>` stands for the capitalised dir and `<role>` for the lowercase role name. Applied as follows:
- **Mapping.** One explicit map, `ROLE_DIRS`, in `bootstrap/lib/hos_tmp_root.py` (§2A.2). It is not `str.capitalize()`.
- **Interfaces stay lowercase.** The resolver's `--role` argument and the launchers' `$ROLE` stay lowercase. Only the dir name is capitalised.
- **Launchers' exports.** §2A.3, L1–L3 and the verification item (`.tmp/Human`).
- **Sandbox template.** It uses a new **derived** token, `__ROLE_DIR__`, rather than literal per-role entries (D15, §2A.4).
  - Literal entries in the `__HOS_ROOT__/Human` style would give every role all three temp dirs. That is the same over-grant R3-2 flagged (#2056), and it would defeat the separation.
  - The generator derives `__ROLE_DIR__` from `--role`. It adds no flag, no sidecar key and no version bump.
  - G1 asserts that the token renders as `Human`, and that no lowercase or sibling grant appears.
- **SANDBOX-POLICY.md.** §5 gains a `__ROLE_DIR__` row (§2A.4).
- **CLAUDE.md row.** §8.3 now reads `.tmp/<RoleDir>`.
- **Reaper roots.** `--hos-tmp-root` sweeps only children named `^(Worker|Overseer|Human|Local)$` (§5.1). RS17 includes a lowercase decoy.
- **Resolver tests.** New H5.

This rename stays inside S2a and S2b. **S1 is unaffected.**
