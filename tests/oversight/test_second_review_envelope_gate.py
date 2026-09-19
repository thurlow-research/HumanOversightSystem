"""End-to-end fail-closed regression for #1737: `run_second_review.sh` must not
record `verdict: approve` when agy's raw `--output-format json` output is a
STATUS ENVELOPE carrying a nested `request_changes` review.

These drive the REAL script as a subprocess with a fake `agy` on PATH that
emits captured envelope fixtures verbatim on stdout — the same pattern as
`test_second_review_request_changes_gate.py` and
`test_second_review_vendor_invoke.py`. Hermetic: no real agy/codex, no network.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_second_review.sh"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Real binaries run_second_review.sh / vendor_invoke.sh / run_with_retry.sh
# need on PATH. Built as an explicit minimal stub (symlinks to the real
# binaries) rather than prepending the fake reviewer onto the full system
# PATH: several of these fixtures carry real high/critical-severity findings,
# and `create_finding_issues` shells out to `gh issue create` for exactly
# those — a system PATH with a real, authenticated `gh` on it would file real
# GitHub issues from a test run. Excluding `gh` (and the real agy/codex) from
# this stub makes that call fail with FileNotFoundError, caught and logged by
# the script's own `except Exception` — no network, no real issue, hermetic.
_REQUIRED_BINS = [
    "bash",
    "python3",
    "git",
    "cat",
    "grep",
    "awk",
    "sed",
    "mkdir",
    "date",
    "head",
    "wc",
    "tr",
    "cut",
    "dirname",
    "mktemp",
    "rm",
    "env",
    "tail",
    "find",
    "timeout",
]


def _minimal_stub_path(tmp_path: Path) -> Path:
    resolved = {b: shutil.which(b) for b in _REQUIRED_BINS}
    missing = [b for b, path in resolved.items() if path is None]
    if missing:
        import pytest

        pytest.skip(f"required binaries unavailable: {missing}")
    stub = tmp_path / "stub_bin"
    stub.mkdir(exist_ok=True)
    for b, path in resolved.items():
        assert path is not None  # narrowed by the `missing` guard above
        target = stub / b
        if not target.exists():
            target.symlink_to(path)
    return stub


def _run(tmp_path: Path, agy_stdout: str, score: str = "0.5") -> subprocess.CompletedProcess:
    """Drive the real script with a fake `agy` emitting `agy_stdout` verbatim,
    on a minimal PATH that excludes `gh` and the real agy/codex (see
    `_REQUIRED_BINS` above)."""
    (tmp_path / "target.py").write_text("def f():\n    return 1\n")

    stub = _minimal_stub_path(tmp_path)
    agy = stub / "agy"
    stdout_file = tmp_path / "agy_stdout.json"
    stdout_file.write_text(agy_stdout)
    # cat the fixture rather than embedding it in the heredoc: the fixture
    # contains its own literal 'JSON'-adjacent content and nested quoting that
    # a heredoc would mangle.
    agy.write_text(f"#!/usr/bin/env bash\ncat > /dev/null\ncat {stdout_file}\n")
    agy.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(stub)

    return subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "1737",
            "--tier",
            "MEDIUM",
            "--score",
            score,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _artifact_fields(tmp_path: Path, step: str) -> tuple[dict[str, str], Path]:
    matches = sorted((tmp_path / ".claudetmp" / "second-review").glob(f"step{step}-*.md"))
    assert matches, f"no second-review artifact written for step {step}"
    fields: dict[str, str] = {}
    for line in matches[-1].read_text().splitlines():
        if ": " in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, matches[-1]


def test_w3_envelope_produces_request_changes_header_and_fails_closed(tmp_path):
    """The issue's headline reproduction: the real W3 captured envelope (which
    was recorded as `verdict: approve` in production, twice) must now record
    `request_changes` / `high` and halt the pipeline with a non-zero exit."""
    agy_stdout = (_FIXTURES / "agy_envelope_w3_request_changes_high.json").read_text()
    r = _run(tmp_path, agy_stdout)
    fields, artifact = _artifact_fields(tmp_path, "1737")

    assert fields.get("verdict") == "request_changes", (fields, artifact.read_text())
    assert fields.get("highest_severity") == "high", fields
    assert int(fields.get("unresolved_findings", "0")) >= 1, fields
    # Fail-closed exit code distinct from 0 (approve) and 1 (reviewer error) —
    # #986's blocking-verdict exit.
    assert r.returncode == 2, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "FAIL-CLOSED" in r.stderr, r.stderr
    assert "verdict: approve" not in artifact.read_text()


def test_w1_envelope_produces_request_changes_not_approve(tmp_path):
    """The W1 fixture (medium/low findings only, no high) must still gate as
    request_changes rather than laundering to approve."""
    agy_stdout = (_FIXTURES / "agy_envelope_w1_request_changes.json").read_text()
    r = _run(tmp_path, agy_stdout)
    fields, artifact = _artifact_fields(tmp_path, "1737")

    assert fields.get("verdict") == "request_changes", (fields, artifact.read_text())
    assert r.returncode == 2, f"stdout={r.stdout}\nstderr={r.stderr}"


def test_non_success_envelope_status_does_not_yield_a_review(tmp_path):
    """An envelope whose own `status` is not SUCCESS must not be read as a
    review, even though its nested `response` parses cleanly into one. This
    must not silently pass — the reviewer's invocation failed."""
    envelope = json.dumps(
        {
            "conversation_id": "x",
            "status": "ERROR",
            "response": json.dumps({"reviewer": "agy", "verdict": "approve", "findings": []}),
            "usage": {},
        }
    )
    r = _run(tmp_path, envelope)
    fields, artifact = _artifact_fields(tmp_path, "1737")

    assert fields.get("verdict") != "approve", (fields, artifact.read_text())
    assert r.returncode != 0, f"stdout={r.stdout}\nstderr={r.stderr}"


# --------------------------------------------------------------------------- #
# AC4 — the codex path, confirmed (not assumed) to be unaffected/unenveloped  #
# --------------------------------------------------------------------------- #
def test_codex_plain_json_review_is_unaffected_by_envelope_unwrapping(tmp_path):
    """codex's real captured output (`.claudetmp/second-review/*.md`, e.g.
    `step1643-W1-20260915T041031.md`) is plain reviewer JSON with no envelope
    — `run_codex_review` doesn't pass `--output-format json`, and this is
    confirmed against a genuine plain-JSON `request_changes` codex response
    routed through the SAME `salvage_review_json()` call sites the agy fix
    touches. AGY is deliberately absent from PATH (a HIGH-tier step forces
    both reviewers; agy's absence exercises the "codex takes the correctness
    lens too" fallback, so this drives codex through the real script rather
    than only unit-testing the shared salvage function)."""
    (tmp_path / "target.py").write_text("def f():\n    return 1\n")

    stub = _minimal_stub_path(tmp_path)

    codex_json = (
        '{"reviewer":"codex","lens":"security-adversarial","findings":'
        '[{"severity":"critical","cwe":"CWE-89","file":"a.py","line":1,'
        '"attack_scenario":"x","finding":"sql injection","suggestion":"parameterize"}],'
        '"verdict":"request_changes","summary":"one critical finding"}'
    )
    codex_stub = stub / "codex"
    codex_stub.write_text(
        f"#!/usr/bin/env bash\ncat > /dev/null\ncat <<'JSON'\n{codex_json}\nJSON\n"
    )
    codex_stub.chmod(codex_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["PATH"] = str(stub)  # no agy anywhere on PATH

    r = subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "1737codex",
            "--tier",
            "HIGH",
            "--score",
            "0.9",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    fields, artifact = _artifact_fields(tmp_path, "1737codex")

    assert fields.get("verdict") == "request_changes", (fields, artifact.read_text())
    assert fields.get("highest_severity") == "critical", fields
    assert r.returncode == 2, f"stdout={r.stdout}\nstderr={r.stderr}"


# --------------------------------------------------------------------------- #
# #1718 regression: envelope unwrapping must not discard `usage` (actual      #
# token counts) — that is the documented defence against agy silently        #
# truncating an oversized prompt while still reporting `status: SUCCESS`.    #
# --------------------------------------------------------------------------- #
def _last_usage_entry(tmp_path: Path, vendor: str = "agy") -> dict:
    log = tmp_path / ".claudetmp" / "oversight" / "token-usage.jsonl"
    assert log.exists(), "token_tracker.py never wrote a usage log"
    entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    matching = [e for e in entries if e.get("vendor") == vendor]
    assert matching, f"no {vendor} usage entry recorded: {entries}"
    return matching[-1]


def test_agy_envelope_records_actual_token_counts_not_estimate(tmp_path):
    """The W3 fixture's envelope carries `usage: {input_tokens: 42766,
    output_tokens: 49754, total_tokens: 92520}`. After #1737's envelope
    unwrap, the salvaged review handed to the aggregator no longer carries
    that field — it must still reach token_tracker.py via the #1718 metadata
    side-channel, with the SAME values a pre-#1737 (accidentally-working, via
    the raw envelope) run would have recorded, and flagged `estimated: false`
    (actual), not a char-based guess. This is the auditable proof #1718's own
    W1 status comment relied on (`55,365 input tokens`) — it must never
    silently become impossible to produce."""
    agy_stdout = (_FIXTURES / "agy_envelope_w3_request_changes_high.json").read_text()
    _run(tmp_path, agy_stdout)

    entry = _last_usage_entry(tmp_path, "agy")
    assert entry["prompt_tokens"] == 42766, entry
    assert entry["output_tokens"] == 49754, entry
    assert entry["total_tokens"] == 92520, entry
    assert entry["estimated"] is False, entry


def test_agy_prose_fallback_still_degrades_to_estimate(tmp_path):
    """Regression guard on the #1718 fix itself: when agy returns genuine
    prose (no envelope, no JSON at all — salvage fails outright), there is no
    actual usage to report and the tracker must fall back to the pre-existing
    char-based estimate, exactly as it did before both the #1737 and #1718
    fixes touched this path."""
    r = _run(tmp_path, "Looks fine overall, no concerns to report here at all.")
    assert (
        r.returncode == 1
    ), f"stdout={r.stdout}\nstderr={r.stderr}"  # verdict=error, no JSON at all

    entry = _last_usage_entry(tmp_path, "agy")
    assert entry["estimated"] is True, entry
    assert entry["prompt_tokens"] > 0, entry  # char estimate of the assembled prompt, not zero


def test_truncated_response_with_intact_usage_still_records_actual_tokens(tmp_path):
    """reliability-reviewer follow-up (#1737): an agy envelope with `status:
    SUCCESS` and fully intact `usage`, but a `response` string truncated
    mid-JSON, must still surface its real token counts through the full
    pipeline (run_second_review.sh -> salvage CLI --metadata-file ->
    token_tracker.py), not silently degrade to the char-based estimate just
    because no review could be extracted from the broken response. No review
    means the run is treated as an operational failure (retried, then
    verdict=error), but the CONSUMPTION signal must not be a casualty of that
    failure — it is the one thing #1718 needs to diagnose what happened."""
    truncated_envelope = json.dumps(
        {
            "conversation_id": "trunc-e2e",
            "status": "SUCCESS",
            "response": '{"verdict": "request_changes", "findings": [{"sev',
            "usage": {"input_tokens": 55365, "output_tokens": 900, "total_tokens": 56265},
        }
    )
    r = _run(tmp_path, truncated_envelope)
    # No review was extractable -> retried, then treated as an operational
    # failure (verdict=error), never a silent approve.
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"

    entry = _last_usage_entry(tmp_path, "agy")
    assert entry["prompt_tokens"] == 55365, entry
    assert entry["output_tokens"] == 900, entry
    assert entry["estimated"] is False, entry


def test_codex_path_still_always_estimates_never_actual(tmp_path):
    """codex's real output never carried a `usage` field (confirmed against
    captured fixtures in .claudetmp/second-review/*.md) and
    `run_second_review.sh` never passes `--actual-*-tokens` on the codex
    call — untouched by this fix. Pin it so a future change doesn't
    accidentally start claiming actual counts for a vendor that never
    reported them."""
    codex_json = (
        '{"reviewer":"codex","lens":"security-adversarial","findings":[],'
        '"verdict":"approve","summary":"clean"}'
    )
    (tmp_path / "target.py").write_text("def f():\n    return 1\n")
    stub = _minimal_stub_path(tmp_path)
    codex_stub = stub / "codex"
    codex_stub.write_text(
        f"#!/usr/bin/env bash\ncat > /dev/null\ncat <<'JSON'\n{codex_json}\nJSON\n"
    )
    codex_stub.chmod(codex_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["PATH"] = str(stub)  # no agy on PATH

    subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "1737codexusage",
            "--tier",
            "HIGH",
            "--score",
            "0.9",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    entry = _last_usage_entry(tmp_path, "codex")
    assert entry["estimated"] is True, entry
