"""Tests for scripts/oversight/validation_logic.py — dedup fingerprinting +
verdict aggregation (SPEC-334).

These exercise the PURE public interface (extract_json_objects, fingerprint,
compute_verdict, record_ledger_entry) with synthetic content strings and tmp
ledgers — no subprocess, no live model run (binding 8 / spec R6).

Coverage:
  AC-1 — critical is NOT collapsed to blocking (canonical 7-rank ordering).
  AC-2 — a `type`-only finding (codex) matches a ledger entry recorded with the
         same class string; symmetric for `category`-only (agy).
  binding 6 — robust extractor: brace-in-string, escaped quotes, fence-absent.
  binding 7 — empty parse: strict → error, non-strict → approve.
  dedup    — new-vs-seen split; verdict keyed on NEW blocking.
  record   — round-trip: write then read back into the seen set.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "validation_logic.py"
)
_spec = importlib.util.spec_from_file_location("validation_logic", _MOD_PATH)
validation_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation_logic)

extract_json_objects = validation_logic.extract_json_objects
fingerprint = validation_logic.fingerprint
compute_verdict = validation_logic.compute_verdict
record_ledger_entry = validation_logic.record_ledger_entry
load_ledger = validation_logic.load_ledger


def _fenced(obj: dict) -> str:
    return "some prose\n```json\n" + json.dumps(obj) + "\n```\n"


# ── extract_json_objects (binding 6) ──────────────────────────────────────────
def test_extract_from_fence():
    block = {"reviewer": "agy", "findings": [], "verdict": "approve"}
    objs = extract_json_objects(_fenced(block))
    assert objs == [block]


def test_extract_brace_inside_string_not_fooled():
    # A `{` inside a JSON string value must not break balance tracking.
    block = {"findings": [{"severity": "high", "description": "bad {brace} here"}]}
    objs = extract_json_objects(_fenced(block))
    assert objs == [block]


def test_extract_escaped_quote_in_string():
    # A `"` inside a JSON string value (escaped) must not be treated as the end of
    # the string by the brace walker — the object must still parse intact.
    block = {"findings": [{"severity": "low", "description": 'has " quote and { brace'}]}
    objs = extract_json_objects(_fenced(block))
    assert objs == [block]
    assert objs[0]["findings"][0]["description"] == 'has " quote and { brace'


def test_extract_bare_no_fence_fallback():
    # codex/agy may emit bare JSON with no ```json fence.
    block = {"findings": [{"severity": "blocking"}]}
    text = "preamble\n" + json.dumps(block) + "\ntrailer"
    objs = extract_json_objects(text)
    assert objs == [block]


def test_extract_malformed_json_skipped():
    text = "```json\n{not valid json,,,}\n```"
    assert extract_json_objects(text) == []


# ── fingerprint (binding 5 / AC-2) ────────────────────────────────────────────
def test_fingerprint_type_matches_recorded_class():
    # codex emits `type`; ledger records `class`. Same files + same string → match.
    finding = {"files": ["a.sh"], "type": "bash"}
    fp = fingerprint(finding)
    ledger_entry = {"files": ["a.sh"], "class": "bash"}
    assert fp == validation_logic._ledger_fingerprint(ledger_entry)


def test_fingerprint_category_matches_recorded_class():
    # agy emits `category`; symmetric to the codex case.
    finding = {"files": ["a.md"], "category": "schema"}
    fp = fingerprint(finding)
    ledger_entry = {"files": ["a.md"], "class": "schema"}
    assert fp == validation_logic._ledger_fingerprint(ledger_entry)


def test_fingerprint_singular_file_key():
    a = fingerprint({"file": "x.sh", "type": "bash"})
    b = fingerprint({"files": ["x.sh"], "category": "bash"})
    assert a == b


def test_fingerprint_files_order_independent():
    a = fingerprint({"files": ["a", "b"], "type": "x"})
    b = fingerprint({"files": ["b", "a"], "type": "x"})
    assert a == b


# ── compute_verdict: severity ordering (AC-1, binding 2) ──────────────────────
def test_critical_not_collapsed_to_blocking(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"findings": [{"severity": "critical", "files": ["a"], "type": "x"}]}]
    result = compute_verdict(blocks, ledger)
    assert result["highest_severity"] == "critical"


def test_high_not_collapsed_to_blocking(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"findings": [{"severity": "high", "files": ["a"], "type": "x"}]}]
    result = compute_verdict(blocks, ledger)
    assert result["highest_severity"] == "high"


def test_highest_picks_most_severe(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"findings": [
        {"severity": "warning", "files": ["a"], "type": "x"},
        {"severity": "critical", "files": ["b"], "type": "y"},
        {"severity": "low", "files": ["c"], "type": "z"},
    ]}]
    result = compute_verdict(blocks, ledger)
    assert result["highest_severity"] == "critical"


# ── compute_verdict: dedup new-vs-seen split ──────────────────────────────────
def test_new_blocking_drives_request_changes(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"findings": [{"severity": "blocking", "files": ["a"], "type": "x"}]}]
    result = compute_verdict(blocks, ledger)
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1
    assert result["blocking_count"] == 1
    assert result["dedup_count"] == 0


def test_seen_finding_does_not_gate(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"files": ["a"], "class": "x"}) + "\n")
    blocks = [{"findings": [{"severity": "blocking", "files": ["a"], "type": "x"}]}]
    result = compute_verdict(blocks, str(ledger))
    assert result["verdict"] == "approve"
    assert result["blocking_count"] == 1
    assert result["new_blocking_count"] == 0
    assert result["dedup_count"] == 1


def test_attacks_list_also_counted(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"attacks": [{"severity": "high", "files": ["a"], "category": "x"}]}]
    result = compute_verdict(blocks, ledger)
    assert result["new_blocking_count"] == 1


def test_non_blocking_severities_ignored_for_count(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"findings": [
        {"severity": "warning", "files": ["a"], "type": "x"},
        {"severity": "low", "files": ["b"], "type": "y"},
    ]}]
    result = compute_verdict(blocks, ledger)
    assert result["blocking_count"] == 0
    assert result["verdict"] == "approve"
    assert result["highest_severity"] == "warning"


# ── compute_verdict: empty parse (binding 7) ──────────────────────────────────
def test_empty_strict_is_error(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    result = compute_verdict([], ledger, strict_empty=True)
    assert result["verdict"] == "error"


def test_empty_non_strict_is_approve(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    result = compute_verdict([], ledger, strict_empty=False)
    assert result["verdict"] == "approve"
    assert result["new_blocking_count"] == 0


# ── compute_verdict: reviewer error block fails closed (#670) ─────────────────
def test_error_verdict_block_gates(tmp_path):
    # A reviewer timeout emits {"verdict":"error","findings":[]}: zero findings,
    # but it must NOT approve — the reviewer never reviewed.
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"verdict": "error", "findings": []}]
    result = compute_verdict(blocks, ledger)
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1
    assert result["highest_severity"] == "blocking"


def test_error_verdict_block_not_dedup_silenced(tmp_path):
    # An error block has no stable fingerprint, so a populated ledger can never
    # silence it — it always counts as NEW blocking.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"files": [], "class": "", "disposition": "noise"}) + "\n")
    blocks = [{"verdict": "error", "findings": []}]
    result = compute_verdict(blocks, str(ledger))
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1


def test_error_block_alongside_clean_block_still_gates(tmp_path):
    # One reviewer approves cleanly, the other errored out: the aggregate must
    # gate on the error rather than approve on the clean half.
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [
        {"verdict": "approve", "findings": []},
        {"verdict": "error", "findings": []},
    ]
    result = compute_verdict(blocks, ledger)
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1


def test_approve_verdict_block_does_not_gate(tmp_path):
    # A clean block with a non-error verdict and no blocking findings approves —
    # the error gating must not fire on ordinary verdicts.
    ledger = str(tmp_path / "ledger.jsonl")
    blocks = [{"verdict": "approve", "findings": []}]
    result = compute_verdict(blocks, ledger)
    assert result["verdict"] == "approve"
    assert result["new_blocking_count"] == 0


# ── load_ledger tolerance (spec R1) ───────────────────────────────────────────
def test_load_ledger_missing_file(tmp_path):
    assert load_ledger(str(tmp_path / "nope.jsonl")) == set()


def test_load_ledger_skips_malformed_lines(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"files": ["a"], "class": "x"}) + "\n"
        + "not json\n"
        + "\n"
        + json.dumps({"files": ["b"], "class": "y"}) + "\n"
    )
    seen = load_ledger(str(ledger))
    assert len(seen) == 2


# ── record_ledger_entry round-trip (binding 4) ────────────────────────────────
def test_record_then_dedup_round_trip(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    record_ledger_entry(
        {"files": ["a.sh"], "class": "bash", "disposition": "fixed"},
        str(ledger),
    )
    # A subsequent codex finding (type=bash) on the same file must be seen.
    blocks = [{"findings": [{"severity": "high", "files": ["a.sh"], "type": "bash"}]}]
    result = compute_verdict(blocks, str(ledger))
    assert result["new_blocking_count"] == 0
    assert result["verdict"] == "approve"


def test_record_appends_one_line(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    record_ledger_entry({"files": ["a"], "class": "x", "disposition": "noise"}, str(ledger))
    record_ledger_entry({"files": ["b"], "class": "y", "disposition": "fixed"}, str(ledger))
    lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["files"] == ["a"]
    assert entry["class"] == "x"
    assert entry["disposition"] == "noise"
    assert entry["ts"].endswith("Z")


# ── _cmd_process: preserve existing request_changes verdict (#683) ────────────
def test_cmd_process_preserves_request_changes_with_medium_findings(tmp_path):
    """A reviewer's explicit request_changes (medium findings only) must not be
    laundered into approve by compute_verdict's new_blocking_count==0 logic.
    regression test for #683."""
    import importlib.util as _ilu
    import sys as _sys
    vl = validation_logic  # already imported at module level

    ledger = str(tmp_path / "ledger.jsonl")
    # Simulate the second-review output file AFTER second_review_logic.py aggregate
    # has already set verdict: request_changes for a medium-only reviewer response.
    reviewer_json = json.dumps({
        "reviewer": "agy",
        "verdict": "request_changes",
        "findings": [{"severity": "medium", "file": "foo.py", "line": 1,
                      "finding": "medium issue", "why": "why", "suggestion": "fix"}],
    })
    content = (
        "# Second Review — Step 3\n"
        "Score: 0.35 | Timestamp: 20260623T000000\n"
        "verdict: request_changes\n"   # already set by aggregate
        "reviewed_range: abc..def\n"
        "highest_severity: medium\n"
        "unresolved_findings: 0\n"
        "blocking_count: 0\n"
        "new_blocking_count: 0\n"
        "\n"
        "## agy — Correctness + Spec Adherence\n"
        "```json\n" + reviewer_json + "\n```\n"
    )
    outfile = tmp_path / "step3-review.md"
    outfile.write_text(content)

    # Call _cmd_process via the CLI shim (argparse namespace).
    import argparse
    args = argparse.Namespace(
        file=str(outfile),
        ledger=ledger,
        strict_empty=False,
        func=vl._cmd_process,
    )
    rc = vl._cmd_process(args)
    assert rc == 0

    result_text = outfile.read_text()
    # verdict must remain request_changes (not laundered to approve)
    assert "verdict: request_changes" in result_text
    assert "verdict: approve" not in result_text
    # new_blocking_count must be non-zero to signal the blocking intent
    assert "new_blocking_count: 0\n" not in result_text


def test_cmd_process_does_not_preserve_approve_when_compute_agrees(tmp_path):
    """When aggregate set verdict: approve and compute_verdict also approves,
    the approve verdict is preserved unchanged (#683 — no regression on clean path)."""
    vl = validation_logic
    ledger = str(tmp_path / "ledger.jsonl")
    reviewer_json = json.dumps({
        "reviewer": "agy",
        "verdict": "approve",
        "findings": [],
    })
    content = (
        "# Second Review — Step 3\n"
        "Score: 0.35 | Timestamp: 20260623T000000\n"
        "verdict: approve\n"
        "reviewed_range: abc..def\n"
        "highest_severity: none\n"
        "unresolved_findings: 0\n"
        "blocking_count: 0\n"
        "new_blocking_count: 0\n"
        "\n"
        "## agy — Correctness + Spec Adherence\n"
        "```json\n" + reviewer_json + "\n```\n"
    )
    outfile = tmp_path / "step3-review.md"
    outfile.write_text(content)
    import argparse
    args = argparse.Namespace(
        file=str(outfile), ledger=ledger, strict_empty=False, func=vl._cmd_process,
    )
    rc = vl._cmd_process(args)
    assert rc == 0
    result_text = outfile.read_text()
    assert "verdict: approve" in result_text
    assert "verdict: request_changes" not in result_text
