"""#1944 S1: strict JSON envelope parsing (ADR-1944 A2-7, A2-8)."""

import json

from tests.automation.usage_support import fx, sha, up


def test_capture2_fixture_is_verbatim():
    data = fx("capture2-envelope-2026-10-03.json")
    assert len(data) == 1621
    expected = "c72987a8fda5a146cf30b1ca31d0a19b33423d20b4ee58432773b06f250b4de5"  # pragma: allowlist secret
    assert sha(data) == expected


def test_capture2_envelope_ok_reads_three_fields():
    env = up.parse_envelope(fx("capture2-envelope-2026-10-03.json"))
    assert env.ok and env.reason is None
    assert env.result_text.startswith("You are currently using your subscription")
    assert env.cost_usd == 0
    assert dict(env.tokens) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    assert env.read_tokens == 0


def test_extra_fields_ignored():
    base = up.parse_envelope(fx("capture2-envelope-2026-10-03.json"))
    plus = up.parse_envelope(fx("capture2-plus-fields.json"))
    assert plus == base


def test_unknown_usage_fields_ignored():
    doc = json.loads(fx("capture2-plus-fields.json"))
    assert "extra" in doc["usage"]
    del doc["usage"]["output_tokens_details"]
    env = up.parse_envelope(json.dumps(doc).encode())
    assert env.ok and env.read_tokens == 0


def test_live_full_envelope_accepted_unknown_keys_ignored():
    """The first real, unfiltered envelope (20 top-level keys) parses; nothing beyond the TD's six fields is read."""
    data = fx("live-full-envelope-2026-10-03.json")
    doc = json.loads(data)
    assert len(doc) == 20
    env = up.parse_envelope(data)
    assert env.ok
    assert env.cost_usd == 0 and env.read_tokens == 0
    parsed = up.parse_usage(env.result_text)
    assert parsed.ok and (parsed.session_pct, parsed.weekly_all_pct) == (6, 4)
    # Removing every unread key changes nothing.
    slim = {k: doc[k] for k in ("result", "total_cost_usd")}
    slim["usage"] = {k: doc["usage"][k] for k in up._TOKEN_KEYS}
    assert up.parse_envelope(json.dumps(slim).encode()) == env


def test_not_json_envelope_invalid():
    assert up.parse_envelope(fx("envelope-not-json.txt")).reason == "envelope_invalid"


def test_result_missing_envelope_invalid():
    assert up.parse_envelope(fx("envelope-result-missing.json")).reason == "envelope_invalid"


def test_result_not_string_envelope_invalid():
    assert up.parse_envelope(fx("envelope-result-number.json")).reason == "envelope_invalid"


def test_top_level_array_envelope_invalid():
    assert up.parse_envelope(fx("envelope-array.json")).reason == "envelope_invalid"


def test_duplicate_result_key_envelope_invalid():
    assert up.parse_envelope(fx("envelope-duplicate-result.json")).reason == "envelope_invalid"


def test_over_cap_envelope_invalid():
    big = json.dumps({"result": "x" * (up.INPUT_CAP_BYTES + 10)}).encode()
    assert up.parse_envelope(big).reason == "envelope_invalid"


def test_no_fragment_scanning():
    inner = fx("capture2-envelope-2026-10-03.json")
    assert up.parse_envelope(b"warning: banner\n" + inner).reason == "envelope_invalid"


def test_cost_nan_negative_bool_absent():
    assert up.parse_envelope(fx("envelope-nan-cost.json")).reason == "envelope_invalid"
    neg = up.parse_envelope(fx("envelope-negative-cost.json"))
    assert neg.ok and neg.cost_usd is None
    doc = json.loads(fx("capture2-envelope-2026-10-03.json"))
    doc["total_cost_usd"] = True
    assert up.parse_envelope(json.dumps(doc).encode()).cost_usd is None
    doc["total_cost_usd"] = "0"
    assert up.parse_envelope(json.dumps(doc).encode()).cost_usd is None


def test_tokens_partial_sum_absent():
    env = up.parse_envelope(fx("envelope-tokens-partial.json"))
    assert env.ok and len(env.tokens) == 3
    assert env.read_tokens is None


def test_thinking_tokens_not_added():
    doc = json.loads(fx("capture2-envelope-2026-10-03.json"))
    doc["usage"]["output_tokens_details"]["thinking_tokens"] = 99
    env = up.parse_envelope(json.dumps(doc).encode())
    assert env.read_tokens == 0


def test_cost_recorded_on_failed_read():
    for name in ("empty-session-envelope-blank.json", "empty-session-envelope-legacy-text.json"):
        cls = up.classify_read(up.ReadOutcome("exited", 0, None), fx(name), b"")
        assert cls.outcome == "failure" and cls.reason == "empty_session"
        assert cls.envelope.cost_usd == 0 and cls.envelope.read_tokens == 0
        fields = dict(
            up.build_reading(
                run_epoch=5,
                classification=cls,
                diagnostics=None,
                previous=None,
                settings=up.load_settings(up.Path("/nonexistent")),
            )
        )
        assert fields["cost_usd"] == "0" and fields["read_tokens"] == "0"


def _with_cost(literal):
    doc = fx("capture2-envelope-2026-10-03.json").decode()
    return doc.replace('"total_cost_usd": 0', '"total_cost_usd": %s' % literal, 1).encode()


def test_huge_cost_is_absent_and_read_still_succeeds():
    for literal in ("1" + "0" * 400, "1e999", "-1" + "0" * 400):
        env = up.parse_envelope(_with_cost(literal))
        assert env.ok and env.cost_usd is None, literal
        assert up.parse_usage(env.result_text).ok


def test_unbounded_int_literal_is_envelope_invalid_not_a_crash():
    assert up.parse_envelope(_with_cost("1" + "0" * 6000)).reason == "envelope_invalid"


def test_deeply_nested_envelope_is_envelope_invalid():
    assert up.parse_envelope(b"[" * 50000 + b"]" * 50000).reason == "envelope_invalid"
