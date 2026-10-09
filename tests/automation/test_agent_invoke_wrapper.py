"""
Tests for bootstrap/invoke_agent.sh — the L3 wrapper for the deterministic
agent-invocation primitive (#1643 W1).

docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md §3.9 + §9's slice
gate: "All drive main(argv=[...], repo_root=tmp_path) in-process except the
wrapper tests, which shell out." This file shells out to the script, but
against an isolated replica of the repo built once per module (#1910), not
the real checkout. There is no --repo-root flag on this surface — the L2
module resolves its own repo root from `__file__`, and L3 adds nothing of
its own — and every emitted document writes an `agent-invocation` record
under `<repo_root>/audit/log`, so running against the real checkout filled
the committed audit trail with fake records on every test run. The replica
holds real copies (not symlinks, which `Path(__file__).resolve()` would
follow back to the real repo) so those writes land in a throwaway
directory. Tests use `--not-applicable` to avoid any dependency on a real
`claude` binary or network access: no process is launched on that path
(§4.5), so these tests exercise the wrapper's passthrough contract without
needing the vendor CLI installed.

The classifier matrix itself (every AD-4/A1-A9 row) is L2's test obligation,
driven in-process in test_agent_invoke_cli.py. This file only tests what is
specific to the L3 boundary: fixed argv, byte-for-byte passthrough, the
python3-missing operational failure, and that stderr is never suppressed
(#1523).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories the wrapper and the L2 module need at runtime (#1910 replica).
_REPLICA_DIRS = ("bootstrap", "scripts", ".claude", "contract")
_REPLICA_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "node_modules", ".pytest_cache")

# A real shipped agent, guaranteed present in this repo, used only via
# --not-applicable so no `claude` process is ever launched.
REAL_AGENT = "code-reviewer"


_REPLICA: Path | None = None


def _build_replica(root: Path) -> Path:
    """Populate `root` with a replica of the repo pieces the wrapper needs."""
    for name in _REPLICA_DIRS:
        shutil.copytree(REPO_ROOT / name, root / name, ignore=_REPLICA_IGNORE)
    real_venv = REPO_ROOT / "scripts" / "oversight" / ".venv"
    if real_venv.exists():
        # Rung 2 of the interpreter ladder. The interpreter path may be a
        # symlink; only the CLI file path must not resolve to the real repo.
        (root / "scripts" / "oversight" / ".venv").symlink_to(real_venv)
    return root


@pytest.fixture(scope="module")
def replica_root(tmp_path_factory) -> Path:
    """Isolated repo replica so audit writes never reach the real trail (#1910)."""
    return _build_replica(tmp_path_factory.mktemp("invoke-agent-replica"))


@pytest.fixture(autouse=True)
def _bind_replica(replica_root):
    global _REPLICA
    _REPLICA = replica_root


def _run(
    args: list[str], *, env: dict | None = None, root: Path | None = None
) -> subprocess.CompletedProcess:
    root = root or _REPLICA
    assert root is not None, "replica fixture not bound"
    return subprocess.run(
        [BASH, str(root / "bootstrap" / "invoke_agent.sh"), *args],
        cwd=str(root),
        env=env if env is not None else os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_not_applicable_passthrough_exit_0_and_one_json_document():
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "test reason"])
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {result.stdout!r}"
    doc = json.loads(lines[0])
    assert doc["applicability"] == "not_applicable"
    assert doc["applicability_reason"] == "test reason"
    assert doc["agent"] == REAL_AGENT
    assert doc["outcome"] == "completed"
    assert doc["verdict"] == "approve"


def test_forbidden_flag_exit_2_no_stdout_document_stderr_names_flag():
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x", "--settings", "/tmp/x.json"])
    assert result.returncode == 2
    assert result.stdout == ""
    assert "agent_invoke:" in result.stderr
    assert "--settings" in result.stderr


def test_missing_required_flag_exit_2():
    result = _run(["--not-applicable", "x"])  # no --agent
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() != ""


def test_agent_unavailable_is_exit_0_with_a_document_not_a_silent_failure():
    result = _run(["--agent", "no-such-agent-xyz", "--not-applicable", "x"])
    assert result.returncode == 0
    doc = json.loads(result.stdout.splitlines()[0])
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "agent_unavailable"
    assert doc["verdict"] == "error"


def test_no_python3_on_path_still_succeeds_via_the_oversight_venv(tmp_path):
    """T1.50 (Amendment A, ADR-1643 §10.6). **REVERSES** the prior
    expectation of this test (formerly
    `test_python3_missing_is_exit_1_with_stderr_message`, which asserted
    exit 1 whenever PATH carried no `python3`): under TD-D22's three-rung
    ladder, rung 2 (`scripts/oversight/.venv/bin/python`, present in the
    replica via a symlink to the real checkout's venv) resolves an absolute
    interpreter path, so an empty PATH is irrelevant. Do NOT "fix" this back to expecting exit 1 — that
    expectation is what #1720 shipped against and it was wrong."""
    # A PATH carrying no python3 — but the script's own non-ladder line
    # (`dirname` in the SCRIPT_DIR resolution) needs to keep resolving, so
    # the stub only omits python/python3, not every coreutil.
    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    dirname_real = shutil.which("dirname")
    assert dirname_real, "dirname must be on the test host's PATH"
    (stub_bin / "dirname").symlink_to(dirname_real)
    env = os.environ.copy()
    env["PATH"] = str(stub_bin)
    env.pop("INVOKE_AGENT_PYTHON", None)
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x"], env=env)
    assert result.returncode == 0
    doc = json.loads(result.stdout.splitlines()[0])
    assert doc["applicability"] == "not_applicable"


def test_invoke_agent_python_non_executable_override_is_exit_1(tmp_path):
    """T1.51 — a set-but-not-executable override is a hard error, never a
    silent fall-through to rung 2."""
    non_exec = tmp_path / "not-a-real-interpreter"
    non_exec.write_text("not a real interpreter\n")
    env = os.environ.copy()
    env["INVOKE_AGENT_PYTHON"] = str(non_exec)
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x"], env=env)
    assert result.returncode == 1
    assert result.stdout == ""
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) == 1, f"expected exactly one stderr line, got: {result.stderr!r}"
    assert "INVOKE_AGENT_PYTHON" in stderr_lines[0]


def test_invoke_agent_python_without_pyyaml_fails_closed_no_traceback(tmp_path):
    """T1.52 — the test that would have caught #1720. An interpreter that
    can start but cannot import PyYAML must fail via P0 (TD-D23): exit 1,
    empty stdout, one stderr line naming PyYAML, the interpreter path, and
    ensure_venv.sh — never an uncaught ModuleNotFoundError traceback. This
    is the consumer-host contract (§3.9) executed directly: after
    `hos_install.sh`, a consumer host has scripts/oversight/ but no .venv,
    so the ladder lands on rung 3, and an unfit rung-3 interpreter must
    reproduce exactly this."""
    venv_dir = tmp_path / "no-yaml-venv"
    created = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if created.returncode != 0:
        pytest.skip(f"venv creation unavailable in this environment: {created.stderr}")
    interpreter = venv_dir / "bin" / "python"
    if not interpreter.exists():
        pytest.skip("venv interpreter not found after creation")

    env = os.environ.copy()
    env["INVOKE_AGENT_PYTHON"] = str(interpreter)
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x"], env=env)

    assert result.stdout == "", f"expected empty stdout, got: {result.stdout!r}"
    assert result.returncode == 1
    assert result.returncode not in (0, 2, 3)
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) == 1, f"expected exactly one stderr line, got: {result.stderr!r}"
    assert "PyYAML" in stderr_lines[0]
    assert str(interpreter) in stderr_lines[0]
    assert "ensure_venv.sh" in stderr_lines[0]
    assert "Traceback" not in result.stderr


def test_flags_pass_through_unaltered_dimension_and_binding():
    result = _run(
        [
            "--agent",
            REAL_AGENT,
            "--not-applicable",
            "x",
            "--dimension",
            "security",
            "--binding",
            "core:security/code",
        ]
    )
    assert result.returncode == 0
    doc = json.loads(result.stdout.splitlines()[0])
    assert doc["dimension"] == "security"
    assert doc["binding"] == "core:security/code"
    assert doc["lens"] == "security"


def test_stderr_is_never_suppressed_on_a_usage_error():
    # #1523 — invoke_agent.sh must never redirect or swallow the child's
    # stderr, even on the exit-2 path.
    result = _run(["--agent", "NOT-VALID-NAME", "--not-applicable", "x"])
    assert result.returncode == 2
    assert result.stderr.strip() != ""


def test_stdout_is_byte_identical_to_direct_module_invocation():
    """Both sides MUST run under the same interpreter (Amendment A,
    ADR-1643 §10.6): the prior version of this test shelled the wrapper
    (whatever `python3` rung it happened to resolve) against a bare
    `python3` on the direct side — two different interpreters, which is
    why it was a second casualty of #1720. Pinning both sides to
    `sys.executable` via `INVOKE_AGENT_PYTHON` tests L3's passthrough
    contract, not the host's PATH."""
    env = os.environ.copy()
    env["INVOKE_AGENT_PYTHON"] = sys.executable
    wrapper = _run(["--agent", REAL_AGENT, "--not-applicable", "byte-identity check"], env=env)
    direct = subprocess.run(
        [
            sys.executable,
            str(_REPLICA / "scripts" / "automation" / "agent_invoke_cli.py"),
            "--agent",
            REAL_AGENT,
            "--not-applicable",
            "byte-identity check",
        ],
        cwd=str(_REPLICA),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrapper.returncode == direct.returncode
    wrapper_doc = json.loads(wrapper.stdout.splitlines()[0])
    direct_doc = json.loads(direct.stdout.splitlines()[0])
    # started_at/ended_at timestamps can legitimately differ by a tick
    # between the two subprocess launches; everything else must match.
    # observability.audit_record is the per-invocation audit record's path,
    # which embeds the write-time second and a content hash (the record
    # includes the timestamp) — the same tick-straddling legitimacy as
    # started_at/ended_at applies. Assert its shape before nulling it so
    # normalization can't hide a real regression (e.g. a missing record).
    audit_record_re = re.compile(
        r"^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}T\d{6}Z-agent-invocation-[0-9a-f]{12}\.json$"
    )
    for doc in (wrapper_doc, direct_doc):
        doc["invocation"]["started_at"] = None
        doc["invocation"]["ended_at"] = None
        audit_record = doc["observability"]["audit_record"]
        assert audit_record is None or audit_record_re.match(audit_record)
        doc["observability"]["audit_record"] = None
    assert wrapper_doc == direct_doc


def _agent_invocation_records(root: Path) -> set[Path]:
    return set((root / "audit" / "log").rglob("*agent-invocation*"))


def test_wrapper_runs_never_write_agent_invocation_records_to_the_real_audit_log(tmp_path):
    """#1910 regression: the wrapper tests must write their audit records to
    the replica, never the committed trail under the real REPO_ROOT. Uses its
    own fresh replica (zero records at start) so the non-empty assertion is
    deterministic: record filenames are second-granular plus a content hash
    and writes are idempotent, so a shared replica could add no new file. The
    real-log equality check could false-fail if a concurrent real agent
    invocation writes to this checkout's log mid-test (accepted)."""
    fresh = _build_replica(tmp_path / "replica")
    before_real = _agent_invocation_records(REPO_ROOT)
    assert not _agent_invocation_records(fresh)
    for args in (
        ["--agent", "no-such-agent-xyz", "--not-applicable", "isolation check"],
        ["--agent", REAL_AGENT, "--not-applicable", "isolation check"],
    ):
        assert _run(args, root=fresh).returncode == 0
    assert _agent_invocation_records(REPO_ROOT) == before_real
    assert _agent_invocation_records(fresh)
