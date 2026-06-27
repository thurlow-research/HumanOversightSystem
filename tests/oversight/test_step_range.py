"""Tests for scripts/oversight/lib/step_range.sh (SPEC-220 BC-220-5).

The helper is a sourced bash library exporting get_step_range(step_n [, root]).
As of SPEC-888 P3 it reads the event stream through the read-shim
(audit_read_stream), so each test lays down a fixture per-entry audit/log/ tree
under a temp root (via the canonical writer) and shells out, sourcing the helper
and calling the function with that root, asserting on stdout.

Key behaviors under test:
  - prefer step-head-final over step-head for the same step
  - portable, step-scoped lookup (step 1 must not match step 12) — BC-220-3
  - empty string (not error) when step N has no event — BC-220-5
  - empty BASE for step 1 (no previous step) -> "..HEAD"
  - missing audit/log directory -> empty output, exit 0
"""
import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "oversight" / "lib" / "step_range.sh"


def _load_audit_log():
    """Load the canonical per-entry audit-record helper (the writer seam)."""
    path = REPO_ROOT / "scripts" / "oversight" / "lib" / "audit_log.py"
    spec = importlib.util.spec_from_file_location("hos_audit_log_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AUDIT = _load_audit_log()


def _write_records(root: Path, events: list[dict]) -> Path:
    """Lay down a fixture audit/log/ tree under `root` using the canonical writer.

    Each event is stamped with a distinct, monotonically increasing timestamp so
    that lexical record-path order (== read_stream order) matches insertion
    order — i.e. the last event written for a step is the chronologically latest,
    preserving the file-model "last event wins" (tail -1) semantics.
    """
    for i, ev in enumerate(events):
        stamped = {**ev, "timestamp": f"2026-06-17T00:{i // 60:02d}:{i % 60:02d}Z"}
        _AUDIT.write_event(stamped, root=str(root))
    return root


def _run(root: Path, *args: str) -> str:
    """Source the helper and call get_step_range with the given args."""
    quoted = " ".join(f'"{a}"' for a in args)
    script = f'. "{HELPER}"; get_step_range {quoted}'
    res = subprocess.run(
        ["bash", "-c", script],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"non-zero exit: {res.stderr}"
    return res.stdout


SHA1 = "1111111111111111111111111111111111111111"
SHA2 = "2222222222222222222222222222222222222222"
SHA3 = "3333333333333333333333333333333333333333"
SHAF = "ffffffffffffffffffffffffffffffffffffffff"


def _ev(event: str, step: int, sha: str) -> dict:
    return {"event": event, "step": step, "head_sha": sha}


def test_prefers_step_head_final(tmp_path):
    root = _write_records(tmp_path, [
        _ev("step-head", 1, SHA1),
        _ev("step-head", 2, SHA2),
        _ev("step-head-final", 2, SHAF),
    ])
    # step 2 head should be the final (SHAF), base is step 1's head (SHA1).
    assert _run(root, "2", str(root)).strip() == f"{SHA1}..{SHAF}"


def test_falls_back_to_step_head(tmp_path):
    root = _write_records(tmp_path, [
        _ev("step-head", 1, SHA1),
        _ev("step-head", 2, SHA2),
    ])
    # no final for step 2 -> use step-head; base is step 1.
    assert _run(root, "2", str(root)).strip() == f"{SHA1}..{SHA2}"


def test_step_one_has_empty_base(tmp_path):
    root = _write_records(tmp_path, [_ev("step-head", 1, SHA1)])
    assert _run(root, "1", str(root)).strip() == f"..{SHA1}"


def test_no_event_for_step_returns_empty(tmp_path):
    root = _write_records(tmp_path, [_ev("step-head", 1, SHA1)])
    # step 5 has no event -> empty string (BC-220-5: not an error).
    assert _run(root, "5", str(root)).strip() == ""


def test_step_scope_no_prefix_collision(tmp_path):
    # BC-220-3: step 1 lookup must NOT match step 12.
    root = _write_records(tmp_path, [
        _ev("step-head", 1, SHA1),
        _ev("step-head", 12, SHA2),
    ])
    assert _run(root, "1", str(root)).strip() == f"..{SHA1}"
    # step 12's base is step 11 (absent) -> empty base.
    assert _run(root, "12", str(root)).strip() == f"..{SHA2}"


def test_final_preferred_as_base_for_next_step(tmp_path):
    # AC-4: next step's BASE is the previous step's step-head-final.
    root = _write_records(tmp_path, [
        _ev("step-head", 1, SHA1),
        _ev("step-head-final", 1, SHAF),
        _ev("step-head", 2, SHA2),
    ])
    assert _run(root, "2", str(root)).strip() == f"{SHAF}..{SHA2}"


def test_missing_log_returns_empty(tmp_path):
    # A root with no audit/log directory -> empty stream -> empty output, exit 0.
    res = subprocess.run(
        ["bash", "-c", f'. "{HELPER}"; get_step_range "2" "{tmp_path}"'],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_last_event_wins(tmp_path):
    # Two step-head-final for the same step -> latest (last written) wins.
    root = _write_records(tmp_path, [
        _ev("step-head", 1, SHA1),
        _ev("step-head-final", 1, SHA2),
        _ev("step-head-final", 1, SHA3),
    ])
    assert _run(root, "1", str(root)).strip() == f"..{SHA3}"
