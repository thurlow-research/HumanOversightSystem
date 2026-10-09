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
    full_env = {"PATH": "/usr/bin:/bin"}
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
