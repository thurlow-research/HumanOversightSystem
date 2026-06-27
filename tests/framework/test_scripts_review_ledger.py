"""Tests for the COMMITTED scripts-review dedup ledger (issue #686).

Unlike the agents-review ledger (which stays ephemeral under .claudetmp/), the
scripts-review ledger is committed in-repo at
scripts/framework/scripts-review-ledger.jsonl so dispositions accumulate across
machines and releases instead of resetting on every fresh clone — the #686
convergence failure. These tests pin the user-facing contract via subprocess:

  * --record / --reset write/clear the ledger at the path given by
    HOS_SCRIPTS_REVIEW_LEDGER (the env override exists precisely so a test never
    touches the real committed baseline);
  * --reset TRUNCATES the tracked file (keeps it in place) rather than deleting
    it, because the file is committed;
  * the committed default ledger exists and is a valid (possibly empty) JSONL.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "framework" / "validate_scripts.sh"
COMMITTED_LEDGER = REPO_ROOT / "scripts" / "framework" / "scripts-review-ledger.jsonl"


def _run(args, ledger_path, cwd):
    env = {**os.environ, "HOS_SCRIPTS_REVIEW_LEDGER": str(ledger_path)}
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True
    )


# ── committed baseline ────────────────────────────────────────────────────────
def test_committed_ledger_exists_and_is_valid_jsonl():
    """The in-repo ledger must exist (committed) and every non-blank line must be
    valid JSON — an empty file is allowed (empty seen-set == old behavior)."""
    assert COMMITTED_LEDGER.exists(), "committed scripts-review ledger missing"
    for line in COMMITTED_LEDGER.read_text().splitlines():
        if line.strip():
            json.loads(line)  # raises if a committed line is malformed


# ── --record / --reset subprocess contract ───────────────────────────────────
def test_record_appends_to_override_path(tmp_path):
    ledger = tmp_path / "scripts-review-ledger.jsonl"
    r = _run(["--record", "a.sh,b.sh", "fail-open", "filed:#686"], ledger, tmp_path)
    assert r.returncode == 0, r.stderr
    assert ledger.exists()
    entry = json.loads(ledger.read_text().strip())
    assert entry["files"] == ["a.sh", "b.sh"]
    assert entry["class"] == "fail-open"
    assert entry["disposition"] == "filed:#686"


def test_record_does_not_touch_committed_ledger(tmp_path):
    """The env override must redirect writes away from the real committed file."""
    before = COMMITTED_LEDGER.read_text()
    _run(["--record", "x.sh", "bash", "noise"], tmp_path / "led.jsonl", tmp_path)
    assert COMMITTED_LEDGER.read_text() == before


def test_reset_truncates_but_keeps_the_tracked_file(tmp_path):
    ledger = tmp_path / "scripts-review-ledger.jsonl"
    ledger.write_text('{"files":["x.sh"],"class":"c","disposition":"noise"}\n')
    counter = tmp_path / ".claudetmp" / "framework" / "scripts-review-pass-count"
    counter.parent.mkdir(parents=True)
    counter.write_text("2")

    r = _run(["--reset"], ledger, tmp_path)
    assert r.returncode == 0, r.stderr
    # File stays (committed/tracked) but is emptied → empty seen-set.
    assert ledger.exists()
    assert ledger.read_text() == ""
    # Pass counter is removed.
    assert not counter.exists()
