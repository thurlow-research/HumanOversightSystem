"""extract_json_objects fails closed on review text it cannot read (#2062).

Three masking shapes let a reviewer's blocking verdict read as approve: duplicate
keys (last wins), a fence-first scan that never looked past an approve block, and
a review nested in a wrapper object. One scan plus a residue rule closes all three.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ORACLE = Path(__file__).resolve().parents[2] / "scripts" / "oversight"
_spec = importlib.util.spec_from_file_location("validation_logic", _ORACLE / "validation_logic.py")
assert _spec is not None and _spec.loader is not None
vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vl)

A = '{"verdict":"approve","findings":[]}'
RC = '{"verdict":"request_changes","findings":[{"severity":"critical","files":["a"],"type":"x"}]}'
DUP = '{"verdict":"request_changes","verdict":"approve","findings":[]}'
TRUNC_RC = '{"verdict":"request_changes","findings":[{"sev'
UNPARSEABLE_RC = '{"verdict":"request_changes",}'


def _fence(block: str) -> str:
    return f"```json\n{block}\n```"


def _verdict(tmp_path, text: str) -> dict:
    ledger = str(tmp_path / "ledger.jsonl")
    return vl.compute_verdict(vl.extract_json_objects(text), ledger)


def _errors(blocks: list[dict]) -> list[dict]:
    return [b for b in blocks if "extraction_error" in b]


def test_dup_key_verdict_blocks(tmp_path):
    blocks = vl.extract_json_objects(DUP)
    assert len(_errors(blocks)) == 1
    result = _verdict(tmp_path, DUP)
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] == 1


def test_dup_key_inside_finding_blocks(tmp_path):
    text = (
        '{"verdict":"request_changes","findings":'
        '[{"severity":"high","severity":"low","files":["a"],"type":"x"}]}'
    )
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_dup_key_non_review_object_ignored(tmp_path):
    text = '{"a":1,"a":2}\n' + _fence(A)
    assert _verdict(tmp_path, text)["verdict"] == "approve"


def test_loads_strict_rejects_nested_dup():
    with pytest.raises(vl.DuplicateKeyError):
        vl.loads_strict('{"x":{"k":1,"k":2}}')


def test_bare_rc_outside_fence_counts(tmp_path):
    text = _fence(A) + "\nafterwards: " + RC
    assert len(vl.extract_json_objects(text)) == 2
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_truncated_rc_after_fenced_approve(tmp_path):
    text = _fence(A) + "\n" + TRUNC_RC
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_unparseable_rc_after_fenced_approve(tmp_path):
    text = _fence(A) + "\n" + UNPARSEABLE_RC
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_nested_envelope_alone(tmp_path):
    text = '{"result":{"verdict":"request_changes","findings":null}}'
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_nested_envelope_plus_approve(tmp_path):
    text = _fence(A) + '\n{"result":{"verdict":"request_changes","findings":null}}'
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_nested_approve_alone_not_lifted(tmp_path):
    text = '{"result":' + A + "}"
    blocks = vl.extract_json_objects(text)
    assert [b for b in blocks if b.get("verdict") == "approve"] == []
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_stray_unbalanced_brace_before_fence(tmp_path):
    text = "prose { oops\n" + _fence(A)
    assert _verdict(tmp_path, text)["verdict"] == "approve"


def test_prose_braces_without_keys(tmp_path):
    text = "use `${HOME}` and {x}\n" + _fence(A)
    assert _verdict(tmp_path, text)["verdict"] == "approve"


def test_escaped_key_in_string_value(tmp_path):
    text = _fence(
        json.dumps({"verdict": "approve", "findings": [], "summary": 'say "verdict": no'})
    )
    assert _verdict(tmp_path, text)["verdict"] == "approve"


def test_schema_echo_fails_closed(tmp_path):
    echo = '{"verdict":"approve|request_changes","findings":[{"severity":"high"}]}'
    assert _verdict(tmp_path, _fence(A) + "\nSchema: " + echo)["verdict"] == "request_changes"


def test_one_synthetic_block_per_text():
    text = "\n".join([DUP, TRUNC_RC, UNPARSEABLE_RC])
    assert len(_errors(vl.extract_json_objects(text))) == 1


def test_scan_budget_fails_closed(tmp_path):
    text = "{" * 200_000 + "\n" + _fence(A)
    blocks = vl.extract_json_objects(text)
    errs = _errors(blocks)
    assert len(errs) == 1
    assert "scan-budget-exceeded" in errs[0]["extraction_error"]
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_chunked_adr2033_multi_block(tmp_path):
    coverage = "```\n[COVERAGE] files reviewed: a.py, b.py {chunk 2 of 4}\n```"
    text = "\n".join(_fence(A) for _ in range(4)) + "\n" + coverage
    assert len(vl.extract_json_objects(text)) == 4
    assert _verdict(tmp_path, text)["verdict"] == "approve"
    assert _verdict(tmp_path, text + "\n" + _fence(RC))["verdict"] == "request_changes"


def test_ledgered_rc_still_converges(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    vl.record_ledger_entry({"files": ["a"], "class": "x", "disposition": "fixed"}, str(ledger))
    result = vl.compute_verdict(vl.extract_json_objects(_fence(RC)), str(ledger))
    assert result["verdict"] == "approve"


def test_cli_process_strict_empty_dup_key(tmp_path):
    out = tmp_path / "out.md"
    out.write_text(
        "verdict: pending\nhighest_severity: none\nblocking_count: 0\n\n" + _fence(DUP) + "\n"
    )
    ledger = tmp_path / "ledger.jsonl"
    rc = vl.main(["process", "--file", str(out), "--ledger", str(ledger), "--strict-empty"])
    assert rc == 0
    assert "verdict: request_changes" in out.read_text()


def test_validate_self_single_doc_unchanged():
    doc = {
        "verdict": "approve",
        "findings": [],
        "input": {"prompt": "p", "files": ["a"]},
        "observability": {"tokens": {"in": 1, "out": 2}},
    }
    blocks = vl.extract_json_objects(json.dumps(doc))
    assert len(blocks) == 1
    assert "extraction_error" not in blocks[0]


def test_nested_rc_inside_accepted_approve_blocks(tmp_path):
    text = '{"verdict":"approve","findings":[],' '"x":{"verdict":"request_changes","findings":[]}}'
    errs = _errors(vl.extract_json_objects(text))
    assert len(errs) == 1
    assert "nested-review-object" in errs[0]["extraction_error"]
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_nested_review_in_findings_list_blocks(tmp_path):
    text = json.dumps({"verdict": "approve", "findings": [{"severity": "low", "verdict": "x"}]})
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_unicode_escaped_key_residue_blocks(tmp_path):
    escaped = '{"\\u0076erdict":"request_changes",}'
    text = _fence(A) + "\n" + escaped
    assert vl.review_text_unreadable(text)
    assert _verdict(tmp_path, text)["verdict"] == "request_changes"


def test_extraction_error_has_offset_no_excerpt():
    marker = "SECRETMARKER"
    text = _fence(A) + '\n{"verdict":"request_changes","note":"' + marker + '",}'
    errs = _errors(vl.extract_json_objects(text))
    assert len(errs) == 1
    reason = errs[0]["extraction_error"]
    assert "offset" in reason
    assert marker not in reason
