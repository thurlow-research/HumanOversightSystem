"""Tests for scripts/framework/run_tests_inner_loop.sh's opt-in --failure-log
flag (#1903).

Builds a minimal sandboxed repo layout (real run_tests_inner_loop.sh, a stub
regen_all.sh, and a stub python/pytest) so these tests never recurse into the
real inner-loop suite. Mirrors the sandboxing technique in
test_regen_all.py: an isolated temp directory, nothing here touches the real
repo. The log file itself is created in the REAL, literal /tmp (by design —
see the script's own comments), so every test tracks exactly what path it
created (via the `INNER_LOOP_LOG=` marker, or a before/after glob delta for
the no-leftover assertions) and removes it in a `finally`, never leaving
stray `/tmp/hos-inner-loop-*` files behind.
"""

import glob
import re
import shutil
import subprocess
from pathlib import Path

from tests.tmp_hygiene import child_env

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "framework" / "run_tests_inner_loop.sh"

_LOG_GLOB = "/tmp/hos-inner-loop-*"
_LOG_RE = re.compile(r"^/tmp/hos-inner-loop-\d{8}T\d{6}Z-[0-9a-f]{7,40}-[A-Za-z0-9]+$")


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _build_repo(tmp_path: Path) -> Path:
    """A minimal repo: real run_tests_inner_loop.sh + stub regen_all.sh + stub
    venv python (acting as `python -m pytest ...`), initialized as a git repo
    so `git rev-parse --short HEAD` in the script resolves to a real sha."""
    repo = tmp_path / "repo"
    fw = repo / "scripts" / "framework"
    fw.mkdir(parents=True)
    shutil.copy(SCRIPT, fw / "run_tests_inner_loop.sh")
    (fw / "run_tests_inner_loop.sh").chmod(0o755)

    _write_exec(
        fw / "regen_all.sh",
        "#!/usr/bin/env bash\n" 'echo "regen-stub-stdout"\n' 'exit "${REGEN_STUB_EXIT:-0}"\n',
    )
    _write_exec(
        repo / "scripts" / "oversight" / ".venv" / "bin" / "python",
        "#!/usr/bin/env bash\n"
        'echo "pytest-stub-stdout args=$*"\n'
        'echo "pytest-stub-stderr" >&2\n'
        'exit "${PYTEST_STUB_EXIT:-0}"\n',
    )

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.local", "-c", "user.name=test", "add", "-A"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@test.local",
            "-c",
            "user.name=test",
            "commit",
            "-q",
            "-m",
            "sandbox baseline",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def _short_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    # #2054: the resolver's trust registry must never be written in the real home.
    full_env = {
        "PATH": "/usr/bin:/bin",
        "HOS_TMP_REGISTRY_FILE": str(repo.parent / "reg-state" / "hos" / "tmp-roots.json"),
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "framework" / "run_tests_inner_loop.sh"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=child_env(full_env),
    )


def _existing_logs() -> set:
    return set(glob.glob(_LOG_GLOB))


def test_no_flag_creates_no_log(tmp_path):
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    try:
        result = _run(repo, "-q")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _existing_logs() - before == set(), "no --failure-log → no log file, ever"
        assert "INNER_LOOP_LOG=" not in result.stdout
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_no_flag_failure_creates_no_log(tmp_path):
    """Byte-for-byte unchanged default behaviour extends to the failure path too."""
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    try:
        result = _run(repo, "-q", env={"PYTEST_STUB_EXIT": "1"})
        assert result.returncode == 1, result.stdout + result.stderr
        assert _existing_logs() - before == set()
        assert "INNER_LOOP_LOG=" not in result.stdout
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_flag_pass_leaves_no_log(tmp_path):
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    try:
        result = _run(repo, "--failure-log", "-q")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _existing_logs() - before == set(), "passing run must delete its own log"
        assert "INNER_LOOP_LOG=" not in result.stdout
        # console output must still show the real run, unaffected by teeing
        assert "pytest-stub-stdout" in result.stdout
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_flag_failure_exit1_keeps_one_log_with_full_output(tmp_path):
    repo = _build_repo(tmp_path)
    sha = _short_sha(repo)
    before = _existing_logs()
    created = []
    try:
        result = _run(repo, "-q", "--failure-log", env={"PYTEST_STUB_EXIT": "1"})
        assert result.returncode == 1, result.stdout + result.stderr

        marker_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("INNER_LOOP_LOG=")]
        assert len(marker_lines) == 1, result.stdout
        log_path = marker_lines[0].split("=", 1)[1]
        created.append(log_path)

        assert _LOG_RE.match(log_path), log_path
        assert f"-{sha}-" in log_path
        assert _existing_logs() - before == {log_path}, "exactly one log must be kept"

        content = Path(log_path).read_text()
        assert "pytest-stub-stdout" in content
        assert "pytest-stub-stderr" in content
        assert "regen-stub-stdout" in content

        # console must show the same content (tee, not silent capture)
        assert "pytest-stub-stdout" in result.stdout
        assert "pytest-stub-stderr" in result.stdout
    finally:
        for p in created:
            Path(p).unlink(missing_ok=True)
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_flag_failure_exit2_preserves_exit_code_and_logs(tmp_path):
    """A non-assertion failure (e.g. pytest exit 2, collection error) must
    preserve that exact exit code — callers classify exit 1 vs other nonzero
    differently — and still capture a log."""
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    created = []
    try:
        result = _run(repo, "-q", "--failure-log", env={"PYTEST_STUB_EXIT": "2"})
        assert result.returncode == 2, result.stdout + result.stderr

        marker_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("INNER_LOOP_LOG=")]
        assert len(marker_lines) == 1, result.stdout
        log_path = marker_lines[0].split("=", 1)[1]
        created.append(log_path)
        assert Path(log_path).exists()
        assert "pytest-stub-stdout" in Path(log_path).read_text()
    finally:
        for p in created:
            Path(p).unlink(missing_ok=True)
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_flag_regen_failure_preserves_exit_code_without_running_pytest(tmp_path):
    """If regen_all.sh itself fails, pytest must never run (matches the
    no-flag behaviour under `set -e`) and the exit code is regen_all.sh's."""
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    created = []
    try:
        result = _run(repo, "-q", "--failure-log", env={"REGEN_STUB_EXIT": "3"})
        assert result.returncode == 3, result.stdout + result.stderr
        assert "pytest-stub-stdout" not in result.stdout

        marker_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("INNER_LOOP_LOG=")]
        assert len(marker_lines) == 1, result.stdout
        log_path = marker_lines[0].split("=", 1)[1]
        created.append(log_path)
        content = Path(log_path).read_text()
        assert "regen-stub-stdout" in content
        assert "pytest-stub-stdout" not in content
    finally:
        for p in created:
            Path(p).unlink(missing_ok=True)
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_flag_is_stripped_before_reaching_pytest(tmp_path):
    """--failure-log must never be forwarded as a pytest arg, regardless of
    where in argv it appears."""
    repo = _build_repo(tmp_path)
    before = _existing_logs()
    try:
        result = _run(repo, "-q", "--failure-log", "-x")
        assert result.returncode == 0, result.stdout + result.stderr
        args_lines = [
            ln for ln in result.stdout.splitlines() if ln.startswith("pytest-stub-stdout args=")
        ]
        assert len(args_lines) == 1, result.stdout
        assert "--failure-log" not in args_lines[0]
        assert "-q" in args_lines[0]
        assert "-x" in args_lines[0]
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_help_documents_failure_log(tmp_path):
    repo = _build_repo(tmp_path)
    result = _run(repo, "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--failure-log" in result.stdout


def test_tee_failure_keeps_no_log_and_preserves_exit_code(tmp_path):
    """If `tee` itself fails (e.g. disk full), PIPESTATUS[0] alone isn't
    enough — a tee failure must not be reported as a successfully kept log
    (which could be empty/truncated). The suite's own exit code is still
    preserved either way; only the logging half degrades. Simulated with a
    `tee` stub that drains stdin (so the upstream pytest stub never sees
    SIGPIPE, matching how a real disk-full tee behaves) then fails."""
    repo = _build_repo(tmp_path)
    fake_bin = tmp_path / "fakebin"
    _write_exec(fake_bin / "tee", "#!/usr/bin/env bash\ncat > /dev/null\nexit 1\n")
    before = _existing_logs()
    try:
        result = _run(
            repo,
            "-q",
            "--failure-log",
            env={"PYTEST_STUB_EXIT": "1", "PATH": f"{fake_bin}:/usr/bin:/bin"},
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "tee failed" in result.stderr
        assert "INNER_LOOP_LOG=" not in result.stdout
        assert _existing_logs() - before == set(), "a failed tee must never leave a kept log"
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


def test_mktemp_failure_degrades_to_unlogged_run(tmp_path, monkeypatch):
    """If mktemp can't create the log (e.g. /tmp unwritable in some exotic
    environment), the run must still complete and exit with the real code —
    never fail the run because logging failed. Simulated here by shadowing
    `mktemp` on PATH with a stub that always fails."""
    repo = _build_repo(tmp_path)
    fake_bin = tmp_path / "fakebin"
    _write_exec(fake_bin / "mktemp", "#!/usr/bin/env bash\nexit 1\n")
    before = _existing_logs()
    try:
        result = _run(
            repo,
            "-q",
            "--failure-log",
            env={"PYTEST_STUB_EXIT": "1", "PATH": f"{fake_bin}:/usr/bin:/bin"},
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "mktemp failed" in result.stderr
        assert "INNER_LOOP_LOG=" not in result.stdout
        assert _existing_logs() - before == set()
    finally:
        for p in _existing_logs() - before:
            Path(p).unlink(missing_ok=True)


# ── #2054 S2a (TD section 2A.3, L3): the run's TMPDIR, four ordered branches ──

_RESOLVER = ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"


def _build_tmpdir_repo(tmp_path: Path, resolver: str = "real") -> Path:
    """_build_repo, with a pytest stub that reports its TMPDIR, and the resolver
    copied in ("real"), made to fail ("failing"), or left out ("absent")."""
    repo = _build_repo(tmp_path)
    _write_exec(
        repo / "scripts" / "oversight" / ".venv" / "bin" / "python",
        '#!/usr/bin/env bash\necho "TMPDIR_SEEN=${TMPDIR-UNSET}"\nexit 0\n',
    )
    lib = repo / "bootstrap" / "lib"
    if resolver == "real":
        lib.mkdir(parents=True)
        shutil.copy(_RESOLVER, lib / "hos_tmp_root.py")
    elif resolver == "failing":
        _write_exec(
            lib / "hos_tmp_root.py",
            "#!/usr/bin/env python3\nimport sys\n"
            "sys.stderr.write('hos_tmp_root: stubbed failure\\n')\nsys.exit(3)\n",
        )
    return repo


def _seen(result: subprocess.CompletedProcess) -> str:
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("TMPDIR_SEEN=")]
    assert len(lines) == 1, result.stdout + result.stderr
    return lines[0].split("=", 1)[1]


def test_l3_1_a_launcher_chosen_dir_wins_over_an_inherited_tmpdir(tmp_path):
    repo = _build_tmpdir_repo(tmp_path)
    chosen = tmp_path / "chosen"
    chosen.mkdir(mode=0o700)
    other = tmp_path / "other"
    other.mkdir()
    result = _run(repo, env={"HOS_TMP_DIR": str(chosen), "TMPDIR": str(other)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _seen(result) == str(chosen)
    assert not (tmp_path / ".tmp").exists(), "branch 1 must not create the local dir"


def test_l3_2_the_local_role_dir_beats_an_inherited_claude_tmpdir(tmp_path):
    repo = _build_tmpdir_repo(tmp_path)
    inherited = tmp_path / "tmp" / "claude"  # what a sandboxed ad-hoc session carries
    inherited.mkdir(parents=True)
    result = _run(repo, env={"TMPDIR": str(inherited)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _seen(result) == str(tmp_path / ".tmp" / "Local")
    assert (tmp_path / ".tmp" / "Local").is_dir()
    assert "WARN" not in result.stderr


def test_l3_2b_an_unusable_hos_tmp_dir_falls_through_to_the_local_dir(tmp_path):
    repo = _build_tmpdir_repo(tmp_path)
    result = _run(repo, env={"HOS_TMP_DIR": str(tmp_path / "missing"), "TMPDIR": ""})
    assert _seen(result) == str(tmp_path / ".tmp" / "Local")


def test_l3_3_a_failing_resolver_keeps_the_inherited_tmpdir_and_warns(tmp_path):
    repo = _build_tmpdir_repo(tmp_path, resolver="failing")
    inherited = tmp_path / "inherited"
    inherited.mkdir()
    result = _run(repo, env={"TMPDIR": str(inherited)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _seen(result) == str(inherited)
    warns = [ln for ln in result.stderr.splitlines() if "WARN" in ln]
    assert len(warns) == 1 and "stubbed failure" in warns[0], result.stderr
    assert str(inherited) in warns[0]


def test_l3_4_nothing_usable_leaves_tmpdir_unset_and_warns(tmp_path):
    repo = _build_tmpdir_repo(tmp_path, resolver="absent")
    result = _run(repo, env={"TMPDIR": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _seen(result) == "UNSET"
    warns = [ln for ln in result.stderr.splitlines() if "WARN" in ln]
    assert len(warns) == 1 and "using /tmp" in warns[0], result.stderr


def test_l3_5_an_inherited_tmpdir_inside_the_clone_is_skipped(tmp_path):
    repo = _build_tmpdir_repo(tmp_path, resolver="failing")
    inside = repo / ".claudetmp" / "x"
    inside.mkdir(parents=True)
    result = _run(repo, env={"TMPDIR": str(inside)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _seen(result) == "UNSET", "a TMPDIR under the clone must not be kept"
    warns = [ln for ln in result.stderr.splitlines() if "WARN" in ln]
    assert len(warns) == 1 and "inside this clone" in warns[0], result.stderr


def test_l3_6_a_symlinked_clone_path_is_still_recognised_as_inside(tmp_path):
    repo = _build_tmpdir_repo(tmp_path, resolver="failing")
    inside = repo / "sub"
    inside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(inside)
    result = _run(repo, env={"TMPDIR": str(alias)})
    assert _seen(result) == "UNSET"


def test_l3_7_an_open_hos_tmp_dir_is_rejected_and_the_local_dir_is_used(tmp_path):
    repo = _build_tmpdir_repo(tmp_path)
    open_dir = tmp_path / "open"
    open_dir.mkdir(mode=0o755)
    open_dir.chmod(0o755)
    result = _run(repo, env={"HOS_TMP_DIR": str(open_dir), "TMPDIR": ""})
    assert _seen(result) == str(tmp_path / ".tmp" / "Local")
    warns = [ln for ln in result.stderr.splitlines() if "ignoring HOS_TMP_DIR" in ln]
    assert len(warns) == 1 and "0700" in warns[0], result.stderr


def test_l3_8_a_symlinked_or_in_clone_hos_tmp_dir_is_rejected(tmp_path):
    repo = _build_tmpdir_repo(tmp_path)
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    inside = repo / ".claudetmp"
    inside.mkdir(mode=0o700)
    for bad in (link, inside):
        result = _run(repo, env={"HOS_TMP_DIR": str(bad), "TMPDIR": ""})
        assert _seen(result) == str(tmp_path / ".tmp" / "Local"), bad
        assert "ignoring HOS_TMP_DIR" in result.stderr, bad


# ───────────── Pre-run temp reaper call (#2054, TD 8.1, test C1) ─────────────
def _build_reaper_repo(tmp_path: Path, reaper_rc: int = 0) -> tuple[Path, Path]:
    """_build_repo plus a bootstrap/tmp_reaper.py stub. The stub venv python tells a
    reaper call (argv starts with -I) from a pytest call, and logs the former."""
    repo = _build_repo(tmp_path)
    calls = tmp_path / "reaper-calls.log"
    _write_exec(
        repo / "scripts" / "oversight" / ".venv" / "bin" / "python",
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "-I" ]]; then\n'
        f'  echo "$*" >> "{calls}"\n'
        '  echo "REAPER-STUB-STDOUT"\n'
        f"  exit {reaper_rc}\n"
        "fi\n"
        'echo "pytest-stub-stdout args=$*"\n'
        "exit 0\n",
    )
    (repo / "bootstrap" / "lib").mkdir(parents=True)
    shutil.copy(_RESOLVER, repo / "bootstrap" / "lib" / "hos_tmp_root.py")
    (repo / "bootstrap" / "tmp_reaper.py").write_text("# stub\n")
    return repo, calls


def test_c1_the_reaper_runs_first_with_no_scratch_and_both_roots(tmp_path):
    repo, calls = _build_reaper_repo(tmp_path)
    chosen = tmp_path / "chosen"
    chosen.mkdir(mode=0o700)
    result = _run(repo, "-q", env={"HOS_TMP_DIR": str(chosen)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text().splitlines() == [
        f"-I {repo}/bootstrap/tmp_reaper.py --summary-only --no-scratch --max-seconds 20 "
        f"--root {chosen} --root /tmp"
    ]
    out = result.stdout
    assert (
        out.index("REAPER-STUB-STDOUT") < out.index("regen-stub-stdout") < out.index("pytest-stub")
    )


def test_c1_a_failing_reaper_never_changes_the_exit_code(tmp_path):
    repo, calls = _build_reaper_repo(tmp_path, reaper_rc=1)
    result = _run(repo, "-q", env={"HOS_TMP_DIR": str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tmp_reaper failed (rc=1)" in result.stderr and "pytest-stub-stdout" in result.stdout
    failing = _run(repo, "-q", env={"HOS_TMP_DIR": str(tmp_path), "REGEN_STUB_EXIT": "3"})
    assert failing.returncode == 3, "the suite's own exit code is unchanged"


def test_c1_without_the_reaper_file_nothing_is_called(tmp_path):
    repo, calls = _build_reaper_repo(tmp_path)
    (repo / "bootstrap" / "tmp_reaper.py").unlink()
    result = _run(repo, "-q", env={"HOS_TMP_DIR": str(tmp_path)})
    assert result.returncode == 0 and not calls.exists()


def test_c1_help_names_the_reaper(tmp_path):
    repo, _ = _build_reaper_repo(tmp_path)
    assert "tmp_reaper.py" in _run(repo, "--help").stdout
