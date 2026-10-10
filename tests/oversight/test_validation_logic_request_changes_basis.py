"""compute_verdict fails closed on malformed / basis-less reviewer blocks (#2032).

A block's own `request_changes` verdict used to be ignored unless it was
"error": `_safe_items` coerced a malformed `findings` to `[]`, so the block
aggregated to approve with zero blocking findings.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ORACLE = Path(__file__).resolve().parents[2] / "scripts" / "oversight"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _ORACLE / f"{name}.py")
    assert spec is not None and spec.loader is not None, f"cannot load {name}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validation_logic = _load("validation_logic")
second_review_logic = _load("second_review_logic")
compute_verdict = validation_logic.compute_verdict

_CRIT = {"severity": "critical", "files": ["a"], "type": "x"}


def _ledger(tmp_path) -> str:
    return str(tmp_path / "ledger.jsonl")


@pytest.mark.parametrize(
    "block",
    [
        {"verdict": "request_changes", "findings": None},
        {"verdict": "request_changes", "findings": "x"},
        {"verdict": "request_changes", "findings": 3},
        {"verdict": "request_changes", "findings": {}},
        {"verdict": "request_changes", "attacks": "nope"},
        {"verdict": "request_changes", "findings": []},
        {"verdict": "request_changes"},
        {"verdict": "request_changes", "findings": ["string"]},
        {"verdict": "lgtm", "findings": []},
        {"verdict": "Request_Changes "},
        {"verdict": "approve", "findings": None},
        {"verdict": "request_changes", "findings": [{}]},
        {"verdict": "request_changes", "findings": [{"severity": "Major"}]},
        {"verdict": "request_changes", "findings": [{"severity": ["high"]}]},
        {"verdict": "request_changes", "findings": [{"severity": None}]},
        {"verdict": "request_changes", "attacks": []},
        {"verdict": None, "findings": []},
        {"verdict": 5, "findings": []},
        {"verdict": ["approve"], "findings": []},
        {"verdict": True, "findings": []},
        {"verdict": "", "findings": []},
    ],
)
def test_malformed_or_basisless_block_gates(tmp_path, block):
    result = compute_verdict([block], _ledger(tmp_path))
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1
    assert result["blocking_count"] == 1
    assert result["highest_severity"] == "blocking"


def test_request_changes_with_ledgered_finding_still_converges(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"files": ["a"], "class": "x", "disposition": "fixed"}) + "\n")
    block = {"verdict": "request_changes", "findings": [_CRIT]}
    result = compute_verdict([block], str(ledger))
    assert result["verdict"] == "approve"
    assert result["dedup_count"] == 1


def test_error_block_counts_once(tmp_path):
    result = compute_verdict([{"verdict": "error", "findings": None}], _ledger(tmp_path))
    assert result["blocking_count"] == 1
    assert result["new_blocking_count"] == 1


def test_malformed_block_counts_once_even_with_several_defects(tmp_path):
    block = {"verdict": "lgtm", "findings": None, "attacks": 1}
    assert compute_verdict([block], _ledger(tmp_path))["new_blocking_count"] == 1


def test_absent_verdict_with_empty_findings_is_approve(tmp_path):
    result = compute_verdict([{"findings": []}], _ledger(tmp_path))
    assert result["verdict"] == "approve"
    assert result["blocking_count"] == 0


def test_chunked_approve_blocks_with_one_basisless_request_changes(tmp_path):
    approves = [{"verdict": "approve", "findings": []} for _ in range(4)]
    assert compute_verdict(approves, _ledger(tmp_path))["verdict"] == "approve"
    blocks = approves + [{"verdict": "request_changes", "findings": []}]
    result = compute_verdict(blocks, _ledger(tmp_path))
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1


def test_ad8_rewritten_approve_is_honoured(tmp_path):
    block = {
        "verdict": "approve",
        "routed_from_verdict": "request_changes",
        "context_routed": 2,
        "findings": [
            {"severity": "low", "files": ["a"], "type": "x"},
            {"severity": "low", "files": ["b"], "type": "y"},
        ],
    }
    assert block["context_routed"] > 0  # fixture invariant: AD-8 shape
    result = compute_verdict([block], _ledger(tmp_path))
    assert result["verdict"] == "approve"
    assert result["blocking_count"] == 0


def test_cli_process_null_findings_request_changes(tmp_path):
    reviewer = json.dumps({"reviewer": "codex", "verdict": "request_changes", "findings": None})
    outfile = tmp_path / "step3-review.md"
    outfile.write_text(
        "# Second Review — Step 3\n"
        "Score: 0.70 | Timestamp: 20260716T000000\n"
        "verdict: approve\n"
        "highest_severity: none\n"
        "unresolved_findings: 0\n"
        "blocking_count: 0\n"
        "new_blocking_count: 0\n\n"
        "## codex — Adversarial Security Probe\n```json\n" + reviewer + "\n```\n"
    )
    rc = validation_logic.main(["process", "--file", str(outfile), "--ledger", _ledger(tmp_path)])
    assert rc == 0
    text = outfile.read_text()
    assert "verdict: request_changes" in text
    assert "new_blocking_count: 1" in text


def test_second_review_aggregate_parity_null_findings():
    content = (
        "# Second Review — Step 3\n"
        "Score: 0.67 | Timestamp: 20260617T000000\n"
        "verdict: pending\n"
        "highest_severity: none\n"
        "unresolved_findings: 0\n\n"
        '## codex — Security\n```json\n{"verdict":"request_changes","findings":null}\n```\n\n'
    )
    assert second_review_logic.aggregate_verdicts(content)["verdict"] != "approve"


@pytest.mark.parametrize("sev", ["low", "medium", " Low "])
def test_request_changes_with_explicit_nonblocking_severity_is_a_basis(tmp_path, sev):
    block = {"verdict": "request_changes", "findings": [{"severity": sev, "files": ["a"]}]}
    result = compute_verdict([block], _ledger(tmp_path))
    assert result["verdict"] == "approve"
    assert result["blocking_count"] == 0


def test_attacks_only_request_changes_with_explicit_severity_no_synthetic(tmp_path):
    block = {"verdict": "request_changes", "attacks": [{"severity": "low", "files": ["a"]}]}
    result = compute_verdict([block], _ledger(tmp_path))
    assert result["verdict"] == "approve"
    assert result["blocking_count"] == 0


def test_malformed_block_plus_clean_approve_block_counts_one(tmp_path):
    blocks = [{"verdict": "approve", "findings": []}, {"verdict": "lgtm", "findings": []}]
    result = compute_verdict(blocks, _ledger(tmp_path))
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1


def test_two_malformed_blocks_count_two(tmp_path):
    blocks = [{"findings": None}, {"verdict": "request_changes"}]
    assert compute_verdict(blocks, _ledger(tmp_path))["new_blocking_count"] == 2
