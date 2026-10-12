"""second_review_logic parity with the fail-closed extractor (#2062)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "second_review_logic.py"
_spec = importlib.util.spec_from_file_location("second_review_logic_2062", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
srl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srl)

A = '{"verdict":"approve","findings":[]}'
DUP = '{"verdict":"request_changes","verdict":"approve","findings":[]}'
DUP_RC = (
    '{"verdict":"request_changes","verdict":"approve",'
    '"findings":[{"severity":"critical","files":["a"],"type":"x"}]}'
)
TRUNC_RC = '{"verdict":"request_changes","findings":[{"sev'
NESTED_RC = '{"result":{"verdict":"request_changes","findings":null}}'


def test_salvage_dup_key_alone_is_none():
    assert srl.salvage_review_json(DUP) is None


def test_salvage_approve_plus_dup_rc_errors():
    found = srl.salvage_review_json(A + "\n" + DUP_RC)
    assert found is not None and found["verdict"] == "error"


def test_salvage_approve_plus_truncated_rc_errors():
    found = srl.salvage_review_json(A + "\n" + TRUNC_RC)
    assert found is not None and found["verdict"] == "error"


def test_salvage_approve_plus_nested_rc_errors():
    found = srl.salvage_review_json(A + "\n" + NESTED_RC)
    assert found is not None and found["verdict"] == "error"


def test_envelope_response_approve_plus_truncated_rc_errors():
    raw = json.dumps({"status": "SUCCESS", "response": A + "\n" + TRUNC_RC})
    found = srl.salvage_review_json(raw)
    assert found is not None and found["verdict"] == "error"


def test_aggregate_dup_key_body_is_error_not_prose():
    content = "verdict: pending\n\n## agy\n```json\n" + DUP + "\n```\n"
    assert srl.aggregate_verdicts(content)["verdict"] == "error"


def test_plain_and_fenced_review_unchanged():
    assert srl.salvage_review_json(A) == json.loads(A)
    assert srl.salvage_review_json("```json\n" + A + "\n```") == json.loads(A)


DEEP = '{"verdict":"request_changes","findings":' + "[" * 100_000 + "]" * 100_000 + "}"


def test_aggregate_recursion_deep_body_is_error_not_prose():
    body = '{"verdict":"approve","findings":' + "[" * 100_000 + "]" * 100_000 + "}"
    content = "verdict: pending\n\n## agy\n```json\n" + body + "\n```\n"
    assert srl.aggregate_verdicts(content)["verdict"] == "error"


def test_salvage_approve_plus_deep_rc_cannot_soft_pass():
    found = srl.salvage_review_json(A + "\n" + DEEP)
    assert found is None or found["verdict"] != "approve"


def test_envelope_response_approve_plus_deep_rc_cannot_soft_pass():
    raw = json.dumps({"status": "SUCCESS", "response": A + "\n" + DEEP})
    found = srl.salvage_review_json(raw)
    assert found is None or found["verdict"] != "approve"
