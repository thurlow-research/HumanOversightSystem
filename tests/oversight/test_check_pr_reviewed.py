"""check_pr_reviewed.sh must find real prior-review records, not a retired
file (#1524).

Four incidents (#1288/#1286/#1280, #1306, #1512, #1523) produced a duplicate
overseer PR comment because the ad hoc precheck each cycle reinvented grepped
`audit/oversight-log.jsonl` — retired by #888 P5, moved to per-event records
under audit/log/<YYYY>/<MM>/ — so the grep silently matched nothing. #1523
additionally suppressed stderr, hiding the missing-file error. This script
replaces that ad hoc practice: it reads the real per-entry audit trail via the
audit_log read-shim and never suppresses stderr, so a wrong root fails loud.

The script is driven as a subprocess against a fixture `audit/log/` tree (the
`[root]` argument), never against this repo's own audit trail.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "oversight" / "check_pr_reviewed.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")


def _write_record(root: Path, name: str, record: dict) -> None:
    path = root / "audit" / "log" / "2026" / "09" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_matching_human_required_record_is_found(tmp_path):
    _write_record(
        tmp_path,
        "2026-09-05T201854Z-human-required-a128ad2a5965.json",
        {"event": "human-required", "pr": 1523, "head_sha": "abc123", "timestamp": "2026-09-05T201854Z"},
    )
    res = _run("1523", "abc123", str(tmp_path))
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out == {"already_reviewed": True, "event": "human-required", "timestamp": "2026-09-05T201854Z"}


def test_matching_pr_review_record_is_found(tmp_path):
    _write_record(
        tmp_path,
        "2026-09-09T130815Z-pr-review-f4f2d39040ff.json",
        {"event": "pr-review", "pr": 1527, "head_sha": "f5d902cb", "timestamp": "2026-09-09T130815Z"},
    )
    res = _run("1527", "f5d902cb", str(tmp_path))
    out = json.loads(res.stdout)
    assert out["already_reviewed"] is True
    assert out["event"] == "pr-review"


def test_legacy_camelcase_head_sha_field_is_also_matched(tmp_path):
    # Older records use "headSha", not "head_sha" (schema drift) — the check
    # must not silently miss the older shape.
    _write_record(
        tmp_path,
        "20260905T203712Z-idempotent-skip-pr1512-8c8d265a8fb1.json",
        {"event": "idempotent-skip", "pr": 1512, "headSha": "131f77b", "timestamp": "20260905T203712Z"},
    )
    res = _run("1512", "131f77b", str(tmp_path))
    out = json.loads(res.stdout)
    assert out["already_reviewed"] is True
    assert out["event"] == "idempotent-skip"


def test_different_head_sha_is_not_a_match(tmp_path):
    # A new commit pushed since the last review must not be masked by a
    # stale record at the old head SHA.
    _write_record(
        tmp_path,
        "2026-09-05T201854Z-human-required-a128ad2a5965.json",
        {"event": "human-required", "pr": 1523, "head_sha": "abc123", "timestamp": "2026-09-05T201854Z"},
    )
    res = _run("1523", "def456", str(tmp_path))
    out = json.loads(res.stdout)
    assert out == {"already_reviewed": False, "event": None, "timestamp": None}


def test_different_pr_is_not_a_match(tmp_path):
    _write_record(
        tmp_path,
        "2026-09-05T201854Z-human-required-a128ad2a5965.json",
        {"event": "human-required", "pr": 1523, "head_sha": "abc123", "timestamp": "2026-09-05T201854Z"},
    )
    res = _run("9999", "abc123", str(tmp_path))
    out = json.loads(res.stdout)
    assert out["already_reviewed"] is False


def test_non_review_event_is_not_a_match(tmp_path):
    # A "pr-merged-without-review" or "cycle-start" record for the same PR#
    # must not be misread as a completed review.
    _write_record(
        tmp_path,
        "2026-09-05T201854Z-cycle-start-a128ad2a5965.json",
        {"event": "cycle-start", "pr": 1523, "head_sha": "abc123", "timestamp": "2026-09-05T201854Z"},
    )
    res = _run("1523", "abc123", str(tmp_path))
    out = json.loads(res.stdout)
    assert out["already_reviewed"] is False


def test_empty_audit_log_is_not_an_error(tmp_path):
    res = _run("1", "x", str(tmp_path))
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["already_reviewed"] is False


def test_missing_audit_log_directory_is_not_an_error(tmp_path):
    # No audit/ directory at all under root — must behave like an empty log,
    # not crash (mirrors audit_read_stream's own "missing dir -> empty" contract).
    res = _run("1", "x", str(tmp_path))
    assert res.returncode == 0, res.stderr


def test_usage_error_on_missing_arguments():
    res = _run("1523")
    assert res.returncode == 2
    assert "usage" in res.stderr.lower()


def test_usage_error_on_non_numeric_pr(tmp_path):
    res = _run("not-a-number", "abc123", str(tmp_path))
    assert res.returncode == 2
    assert "numeric" in res.stderr.lower()


def test_usage_error_on_empty_head_sha(tmp_path):
    res = _run("1523", "", str(tmp_path))
    assert res.returncode == 2


def test_stderr_is_never_suppressed_on_malformed_record(tmp_path):
    # The #1523 incident's specific mistake was suppressing stderr around the
    # idempotency grep, which hid the "wrong path" error entirely. A malformed
    # record here must surface visibly on stderr, not be swallowed.
    path = tmp_path / "audit" / "log" / "2026" / "09"
    path.mkdir(parents=True)
    (path / "2026-09-05T000000Z-broken-000000000000.json").write_text("not valid json\n")
    res = _run("1523", "abc123", str(tmp_path))
    assert res.returncode != 0
    assert res.stderr.strip() != ""
