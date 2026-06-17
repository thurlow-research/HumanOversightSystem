"""Tests for scripts/oversight/lib/step_range.sh (SPEC-220 BC-220-5).

The helper is a sourced bash library exporting get_step_range(step_n [, log]).
Each test writes a compact-JSONL fixture log and shells out, sourcing the helper
and calling the function, asserting on stdout.

Key behaviors under test:
  - prefer step-head-final over step-head for the same step
  - portable, step-scoped lookup (step 1 must not match step 12) — BC-220-3
  - empty string (not error) when step N has no event — BC-220-5
  - empty BASE for step 1 (no previous step) -> "..HEAD"
"""
import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "lib" / "step_range.sh"


def _run(log: Path, *args: str) -> str:
    """Source the helper and call get_step_range with the given args."""
    quoted = " ".join(f'"{a}"' for a in args)
    script = f'. "{HELPER}"; get_step_range {quoted}'
    res = subprocess.run(
        ["bash", "-c", script],
        cwd=str(log.parent),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"non-zero exit: {res.stderr}"
    return res.stdout


def _write_log(tmp_path: Path, lines: list[str]) -> Path:
    log = tmp_path / "oversight-log.jsonl"
    log.write_text("".join(l + "\n" for l in lines))
    return log


SHA1 = "1111111111111111111111111111111111111111"
SHA2 = "2222222222222222222222222222222222222222"
SHA3 = "3333333333333333333333333333333333333333"
SHAF = "ffffffffffffffffffffffffffffffffffffffff"


def _sh(event: str, step: int, sha: str) -> str:
    return f'{{"event":"{event}","step":{step},"head_sha":"{sha}","timestamp":"2026-06-17T00:00:00Z"}}'


def test_prefers_step_head_final(tmp_path):
    log = _write_log(tmp_path, [
        _sh("step-head", 1, SHA1),
        _sh("step-head", 2, SHA2),
        _sh("step-head-final", 2, SHAF),
    ])
    # step 2 head should be the final (SHAF), base is step 1's head (SHA1).
    assert _run(log, "2", str(log)).strip() == f"{SHA1}..{SHAF}"


def test_falls_back_to_step_head(tmp_path):
    log = _write_log(tmp_path, [
        _sh("step-head", 1, SHA1),
        _sh("step-head", 2, SHA2),
    ])
    # no final for step 2 -> use step-head; base is step 1.
    assert _run(log, "2", str(log)).strip() == f"{SHA1}..{SHA2}"


def test_step_one_has_empty_base(tmp_path):
    log = _write_log(tmp_path, [_sh("step-head", 1, SHA1)])
    assert _run(log, "1", str(log)).strip() == f"..{SHA1}"


def test_no_event_for_step_returns_empty(tmp_path):
    log = _write_log(tmp_path, [_sh("step-head", 1, SHA1)])
    # step 5 has no event -> empty string (BC-220-5: not an error).
    assert _run(log, "5", str(log)).strip() == ""


def test_step_scope_no_prefix_collision(tmp_path):
    # BC-220-3: step 1 lookup must NOT match step 12.
    log = _write_log(tmp_path, [
        _sh("step-head", 1, SHA1),
        _sh("step-head", 12, SHA2),
    ])
    assert _run(log, "1", str(log)).strip() == f"..{SHA1}"
    # step 12's base is step 11 (absent) -> empty base.
    assert _run(log, "12", str(log)).strip() == f"..{SHA2}"


def test_final_preferred_as_base_for_next_step(tmp_path):
    # AC-4: next step's BASE is the previous step's step-head-final.
    log = _write_log(tmp_path, [
        _sh("step-head", 1, SHA1),
        _sh("step-head-final", 1, SHAF),
        _sh("step-head", 2, SHA2),
    ])
    assert _run(log, "2", str(log)).strip() == f"{SHAF}..{SHA2}"


def test_missing_log_returns_empty(tmp_path):
    missing = tmp_path / "nope.jsonl"
    quoted = f'"2" "{missing}"'
    res = subprocess.run(
        ["bash", "-c", f'. "{HELPER}"; get_step_range {quoted}'],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_last_event_wins(tmp_path):
    # Two step-head-final for the same step -> last one wins (tail -1).
    log = _write_log(tmp_path, [
        _sh("step-head", 1, SHA1),
        _sh("step-head-final", 1, SHA2),
        _sh("step-head-final", 1, SHA3),
    ])
    assert _run(log, "1", str(log)).strip() == f"..{SHA3}"
