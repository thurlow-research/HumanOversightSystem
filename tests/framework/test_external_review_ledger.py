"""Tests for the external-review dedup ledger in validate_agents.sh (issue #78).

The ledger makes the cross-vendor (agy+codex) framework review converge instead
of re-generating ~14 findings every run. These tests cover the user-facing
contract (--record / --reset and the JSON ledger format) via subprocess, and the
vendor-agnostic fingerprint + convergence logic as a pure-Python replica of the
script's finalize step (the finalize is embedded in a bash heredoc; the replica
must stay in lockstep with it).
"""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "framework" / "validate_agents.sh"


# ── --record / --reset subprocess contract ───────────────────────────────────
def _run(args, cwd):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)


def test_record_appends_valid_json_line(tmp_path):
    _run(["--record", "a.md,b.md", "human-gate-bypass", "residual:#82"], tmp_path)
    ledger = tmp_path / ".claudetmp" / "framework" / "external-review-ledger.jsonl"
    assert ledger.exists()
    entry = json.loads(ledger.read_text().strip())
    assert entry["files"] == ["a.md", "b.md"]
    assert entry["class"] == "human-gate-bypass"
    assert entry["disposition"] == "residual:#82"


def test_reset_clears_ledger_and_counter(tmp_path):
    fw = tmp_path / ".claudetmp" / "framework"
    fw.mkdir(parents=True)
    (fw / "external-review-ledger.jsonl").write_text('{"files":["x"],"class":"c"}\n')
    (fw / "external-review-pass-count").write_text("2")
    _run(["--reset"], tmp_path)
    assert not (fw / "external-review-ledger.jsonl").exists()
    assert not (fw / "external-review-pass-count").exists()


# ── fingerprint + convergence logic (replica of the finalize heredoc) ─────────
def _fingerprint(f):
    files = f.get("files") or ([f["file"]] if f.get("file") else [])
    return (tuple(sorted(files)), f.get("category") or f.get("type") or "")


def _blocking(findings):
    return [
        f
        for f in findings
        if str(f.get("severity", "")).lower() in ("critical", "high", "blocking")
    ]


def _new_blocking(findings, ledger):
    seen = {(tuple(sorted(e["files"])), e["class"]) for e in ledger}
    return [f for f in _blocking(findings) if _fingerprint(f) not in seen]


def test_fingerprint_uses_agy_category_and_codex_type():
    agy = {"severity": "blocking", "category": "mismatch", "files": ["a.md"]}
    codex = {"severity": "critical", "type": "human-gate-bypass", "files": ["a.md"]}
    assert _fingerprint(agy) == (("a.md",), "mismatch")
    assert _fingerprint(codex) == (("a.md",), "human-gate-bypass")


def test_fingerprint_is_order_independent_on_files():
    a = {"severity": "high", "type": "contradiction", "files": ["b.md", "a.md"]}
    b = {"severity": "high", "type": "contradiction", "files": ["a.md", "b.md"]}
    assert _fingerprint(a) == _fingerprint(b)


def test_ledgered_findings_are_not_new():
    findings = [
        {"severity": "critical", "type": "human-gate-bypass", "files": ["e.md"]},
        {"severity": "high", "type": "contradiction", "files": ["f.md", "g.md"]},
    ]
    ledger = [
        {"files": ["e.md"], "class": "human-gate-bypass"},
        {"files": ["g.md", "f.md"], "class": "contradiction"},
    ]
    assert _new_blocking(findings, ledger) == []  # all ledgered → converged


def test_unledgered_finding_counts_as_new():
    findings = [
        {"severity": "critical", "type": "human-gate-bypass", "files": ["e.md"]},
        {"severity": "high", "type": "single-point-failure", "files": ["new.md"]},
    ]
    ledger = [{"files": ["e.md"], "class": "human-gate-bypass"}]
    new = _new_blocking(findings, ledger)
    assert len(new) == 1
    assert new[0]["files"] == ["new.md"]


def test_warnings_do_not_count_as_blocking():
    findings = [
        {"severity": "warning", "category": "terminology", "files": ["w.md"]},
        {"severity": "medium", "type": "underspecified", "files": ["m.md"]},
    ]
    assert _blocking(findings) == []
    assert _new_blocking(findings, []) == []
