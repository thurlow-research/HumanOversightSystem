"""Tests for scripts/oversight/second_review_logic.py — second-review logic (SPEC-331).

These exercise the PURE public interface (select_reviewers, classify_prose,
aggregate_verdicts) with synthetic content strings — no subprocess, network, or
file I/O, and no live model run (architect binding 5/6).

Coverage:
  AC1 — reviewer selection (score-only, tier-floor, below-both, boundary equality).
  AC2 — verdict aggregation (approve + request_changes/high → request_changes/high/1).
  AC3 — prose classification (must-fix, no-issues, unrecognizable).
  AC4 — error precedence + empty reviewer list → error (binding 4).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "second_review_logic.py"
_spec = importlib.util.spec_from_file_location("second_review_logic", _MOD_PATH)
# spec_from_file_location returns ModuleSpec | None, and .loader is Loader | None;
# both are None only if the module is missing or unloadable, which is a broken
# checkout rather than a test failure — assert so mypy sees the narrowing and the
# failure mode names itself instead of surfacing as an AttributeError.
assert _spec is not None and _spec.loader is not None, f"cannot load {_MOD_PATH}"
second_review_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(second_review_logic)

select_reviewers = second_review_logic.select_reviewers
classify_prose = second_review_logic.classify_prose
aggregate_verdicts = second_review_logic.aggregate_verdicts
digest_validators = second_review_logic.digest_validators


# Convenience: a valid second-review output-file header (the "## " sections are
# what get parsed; the header lines are ignored by aggregation but present in
# real files).
_HEADER = (
    "# Second Review — Step 3\n"
    "Score: 0.67 | Timestamp: 20260617T000000\n"
    "verdict: pending\n"
    "highest_severity: none\n"
    "unresolved_findings: 0\n"
    "agy_threshold: 0.30 | codex_threshold: 0.55\n\n"
)


def _section(name: str, payload: str) -> str:
    """Render one reviewer section with a fenced JSON (or prose) body."""
    return f"## {name}\n```json\n{payload}\n```\n\n"


# --------------------------------------------------------------------------- #
# AC1 — reviewer selection                                                    #
# --------------------------------------------------------------------------- #
def test_ac1a_score_only_agy_fires():
    assert select_reviewers(0.45, "", 0.30, 0.55) == (True, False)


def test_ac1b_high_tier_forces_both():
    assert select_reviewers(0.20, "HIGH", 0.30, 0.55) == (True, True)


def test_ac1c_low_tier_below_thresholds_neither():
    assert select_reviewers(0.20, "LOW", 0.30, 0.55) == (False, False)


def test_medium_tier_floor_forces_agy_only():
    assert select_reviewers(0.0, "medium", 0.30, 0.55) == (True, False)


def test_critical_tier_floor_forces_both():
    assert select_reviewers(0.0, "CRITICAL", 0.30, 0.55) == (True, True)


def test_threshold_boundary_is_inclusive():
    # score == agy_threshold fires agy (>= is inclusive).
    assert select_reviewers(0.30, "", 0.30, 0.55) == (True, False)
    assert select_reviewers(0.55, "", 0.30, 0.55) == (True, True)


def test_tier_whitespace_and_case_tolerated():
    assert select_reviewers(0.0, "  high  ", 0.30, 0.55) == (True, True)


# --------------------------------------------------------------------------- #
# AC3 — prose classification                                                  #
# --------------------------------------------------------------------------- #
def test_ac3a_must_fix_is_request_changes():
    assert classify_prose("This has a must-fix problem in the handler.") == "request_changes"


def test_ac3b_no_issues_found_is_approve():
    assert classify_prose("Reviewed the diff: no issues found.") == "approve"


def test_ac3c_unrecognizable_is_unparseable():
    assert classify_prose("The weather today is pleasant and sunny.") == "unparseable"


def test_prose_branch_order_critical_beats_approve():
    # Body with both "critical" and "approve" → request_changes (risk/blocking
    # checks precede the approve check).
    assert classify_prose("A critical bug here, but otherwise I approve.") == "request_changes"


def test_prose_risk_low_is_approve():
    assert classify_prose("Risk: low — minor nit only.") == "approve"


def test_prose_risk_high_is_request_changes():
    assert classify_prose("Risk: high — auth bypass.") == "request_changes"


# --------------------------------------------------------------------------- #
# AC2 — verdict aggregation                                                    #
# --------------------------------------------------------------------------- #
def test_ac2_approve_plus_request_changes_high():
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","findings":[],"verdict":"approve"}')
        + _section(
            "codex — Security",
            '{"reviewer":"codex","verdict":"request_changes",'
            '"findings":[{"severity":"high","finding":"x"}]}',
        )
    )
    result = aggregate_verdicts(content)
    assert result == {
        "verdict": "request_changes",
        "highest_severity": "high",
        "unresolved_findings": 1,
    }


# --------------------------------------------------------------------------- #
# AC4 — error precedence + empty reviewer list                                #
# --------------------------------------------------------------------------- #
def test_ac4_error_precedence_over_request_changes():
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","verdict":"error","findings":[]}')
        + _section(
            "codex — Security",
            '{"reviewer":"codex","verdict":"request_changes",'
            '"findings":[{"severity":"critical","finding":"x"}]}',
        )
    )
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_empty_reviewer_list_is_error():
    # Only the header, no ## agy / ## codex sections.
    assert aggregate_verdicts(_HEADER) == {
        "verdict": "error",
        "highest_severity": "none",
        "unresolved_findings": 0,
    }


def test_skipped_section_ignored():
    content = (
        _HEADER
        + "## agy — SKIPPED\n\n"
        + _section("codex — Security", '{"reviewer":"codex","findings":[],"verdict":"approve"}')
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


def test_unparseable_precedence_below_error_above_approve():
    content = (
        _HEADER
        + _section("agy — Correctness", "The weather is sunny and pleasant today.")
        + _section("codex — Security", '{"reviewer":"codex","findings":[],"verdict":"approve"}')
    )
    assert aggregate_verdicts(content)["verdict"] == "unparseable"


def test_severity_walk_counts_critical_and_high():
    content = _HEADER + _section(
        "agy — Correctness",
        '{"reviewer":"agy","verdict":"request_changes","findings":['
        '{"severity":"critical","finding":"a"},{"severity":"critical","finding":"b"}]}',
    )
    result = aggregate_verdicts(content)
    assert result["unresolved_findings"] == 2
    assert result["highest_severity"] == "critical"


def test_empty_body_section_is_error():
    # A reviewer section with an empty fenced body → error ("empty" branch).
    content = _HEADER + "## agy — Correctness\n```json\n\n```\n\n"
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_fenced_body_json_parses():
    content = _HEADER + _section(
        "codex — Security",
        '{"reviewer":"codex","verdict":"approve","findings":[]}',
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


# --------------------------------------------------------------------------- #
# #1737 — a verdict-less JSON body must never default to approve             #
# --------------------------------------------------------------------------- #
def test_verdict_less_review_shaped_body_is_unparseable_not_approve():
    """A JSON body that parses and carries findings but no recognizable
    `verdict` key answered the review — just not in the exact expected shape.
    That is `unparseable` (preserved for a human), never a silent `approve`."""
    content = _HEADER + _section(
        "agy — Correctness",
        '{"reviewer":"agy","findings":[{"severity":"medium","finding":"x"}]}',
    )
    result = aggregate_verdicts(content)
    assert result["verdict"] == "unparseable"
    assert result["highest_severity"] == "medium"


def test_verdict_less_non_review_shaped_body_is_error_not_approve():
    """A JSON body that parses but has neither `verdict` nor `findings`/
    `attacks` is exactly the shape of an unsalvaged agy status envelope
    (conversation_id/status/response/usage). Defense-in-depth: even fed
    directly here (bypassing salvage_review_json entirely), this must never
    read as a clean pass."""
    content = _HEADER + _section(
        "agy — Correctness",
        '{"conversation_id":"x","status":"SUCCESS","response":"{}","usage":{}}',
    )
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_unsalvaged_envelope_fed_directly_is_error_not_approve():
    """The exact real-world envelope shape (#1737) — if it ever reached this
    layer unsalvaged — must aggregate to `error`, never `approve`."""
    import json as _json

    envelope = _json.dumps(
        {
            "conversation_id": "abc",
            "status": "SUCCESS",
            "response": _json.dumps({"verdict": "request_changes", "findings": []}),
            "duration_seconds": 1.0,
            "num_turns": 1,
            "usage": {},
        }
    )
    content = _HEADER + _section("agy — Correctness", envelope)
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_recognized_approve_verdict_still_approves():
    """Regression: a well-formed `{"verdict":"approve", ...}` body is
    unaffected by the #1737 tightening."""
    content = _HEADER + _section(
        "agy — Correctness", '{"reviewer":"agy","verdict":"approve","findings":[]}'
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


# --------------------------------------------------------------------------- #
# #1737 test-unit review — severity value edge cases (unexpected casing/type) #
# --------------------------------------------------------------------------- #
def test_mixed_case_severity_is_normalized():
    """A finding severity of 'HIGH' (uppercase — a real vendor formatting
    variance, not just 'high') must still be recognized as high, not silently
    treated as an unrecognized/low severity."""
    content = _HEADER + _section(
        "agy — Correctness",
        json.dumps(
            {"verdict": "request_changes", "findings": [{"severity": "HIGH", "finding": "x"}]}
        ),
    )
    result = aggregate_verdicts(content)
    assert result["highest_severity"] == "high"
    assert result["unresolved_findings"] == 1


def test_non_string_severity_does_not_crash_and_is_not_treated_as_high():
    """A finding whose `severity` is a non-string (e.g. an integer some
    malformed reviewer output could produce) must not crash the aggregator —
    it degrades safely to an unrecognized/`none` severity rather than raising,
    since `_SEV_RANK` only recognizes canonical string severities."""
    content = _HEADER + _section(
        "agy — Correctness",
        json.dumps({"verdict": "request_changes", "findings": [{"severity": 5, "finding": "x"}]}),
    )
    result = aggregate_verdicts(content)  # must not raise
    assert result["verdict"] == "request_changes"
    assert result["highest_severity"] == "none"
    assert result["unresolved_findings"] == 0


# --------------------------------------------------------------------------- #
# #1737 security review — severity/verdict whitespace normalization (Medium) #
# --------------------------------------------------------------------------- #
def test_leading_whitespace_severity_is_normalized():
    """A finding severity of ' critical' (leading space — a real vendor
    formatting variance) must still rank as critical, not fall to
    unrecognized/'none' — an un-.strip()'d comparison let this through
    create_finding_issues's `sev not in ("critical","high")` check too,
    silently skipping issue creation for a real critical finding."""
    content = _HEADER + _section(
        "agy — Correctness",
        json.dumps(
            {"verdict": "request_changes", "findings": [{"severity": " critical", "finding": "x"}]}
        ),
    )
    result = aggregate_verdicts(content)
    assert result["highest_severity"] == "critical"
    assert result["unresolved_findings"] == 1


def test_verdict_casing_and_whitespace_is_normalized():
    """`"Request_Changes"` (mixed case) and `" request_changes "` (padded)
    must both still be recognized as the canonical `request_changes` verdict.
    An exact-match comparison downgraded a hard block (exit 2) to a soft
    `unparseable` warning (exit 0) purely on casing/whitespace."""
    for raw_verdict in ("Request_Changes", " request_changes ", "REQUEST_CHANGES"):
        content = _HEADER + _section(
            "agy — Correctness", json.dumps({"verdict": raw_verdict, "findings": []})
        )
        result = aggregate_verdicts(content)
        assert result["verdict"] == "request_changes", f"raw_verdict={raw_verdict!r}"


def test_verdict_approve_casing_is_normalized():
    content = _HEADER + _section(
        "agy — Correctness", json.dumps({"verdict": " Approve ", "findings": []})
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


# --------------------------------------------------------------------------- #
# #1737 security review — malformed findings must not crash (Low)           #
# --------------------------------------------------------------------------- #
def test_non_dict_finding_entry_does_not_crash():
    """A bare string in the findings list (`["not a dict"]`) must not raise
    AttributeError out of `_aggregate_full` — it degrades to unknown severity
    and is never counted as a NEW critical/high finding."""
    content = _HEADER + _section(
        "agy — Correctness",
        json.dumps({"verdict": "request_changes", "findings": ["not a dict"]}),
    )
    result = aggregate_verdicts(content)  # must not raise
    assert result["verdict"] == "request_changes"
    assert result["highest_severity"] == "none"
    assert result["unresolved_findings"] == 0


def test_null_findings_does_not_crash():
    content = _HEADER + _section(
        "agy — Correctness", json.dumps({"verdict": "request_changes", "findings": None})
    )
    result = aggregate_verdicts(content)  # must not raise
    assert result["verdict"] == "request_changes"
    assert result["unresolved_findings"] == 0


def test_non_list_findings_does_not_crash():
    content = _HEADER + _section(
        "agy — Correctness", json.dumps({"verdict": "request_changes", "findings": "oops"})
    )
    result = aggregate_verdicts(content)  # must not raise
    assert result["verdict"] == "request_changes"
    assert result["unresolved_findings"] == 0


def test_mixed_valid_and_malformed_findings_still_counts_the_valid_one():
    """Fail-closed direction: a malformed entry must not suppress a genuine
    critical/high finding sitting alongside it in the same list."""
    content = _HEADER + _section(
        "agy — Correctness",
        json.dumps(
            {
                "verdict": "request_changes",
                "findings": ["not a dict", {"severity": "critical", "finding": "real one"}, None],
            }
        ),
    )
    result = aggregate_verdicts(content)
    assert result["highest_severity"] == "critical"
    assert result["unresolved_findings"] == 1


# --------------------------------------------------------------------------- #
# #1737 security review — an aggregation crash must write `error`, never    #
# leave the artifact at its `verdict: pending` default (Low, defence-in-depth)#
# --------------------------------------------------------------------------- #
def test_cmd_aggregate_crash_writes_error_verdict_not_pending(tmp_path, monkeypatch):
    def _boom(content):
        raise RuntimeError("synthetic aggregation crash")

    monkeypatch.setattr(second_review_logic, "_aggregate_full", _boom)
    f = tmp_path / "out.md"
    f.write_text(_HEADER)
    rc = second_review_logic.main(["aggregate", "--file", str(f)])
    assert rc == 0
    text = f.read_text()
    assert "verdict: error" in text
    assert "verdict: pending" not in text


# --------------------------------------------------------------------------- #
# #982 — prose reviewer report with its own "## " headings must not truncate  #
# --------------------------------------------------------------------------- #
def test_prose_report_with_internal_headings_not_truncated():
    """A prose reviewer report (agy returned markdown, not JSON) whose body has
    its own '## ' headings must be classified in full — the must-fix content
    below the model's first heading must NOT be silently dropped (#982, the #113
    degradation path). Previously the naïve '^## ' split truncated the reviewer
    section at '## Critical Issues', leaving only the 'Looks good' preamble →
    approve."""
    prose = "Looks good overall.\n" "## Critical Issues\n" "- must-fix: SQL injection in views.py\n"
    content = _HEADER + _section("agy — Correctness", prose)
    result = aggregate_verdicts(content)
    assert result["verdict"] == "request_changes"
    assert result["highest_severity"] == "critical"


def test_advisory_block_after_reviewer_does_not_corrupt_json():
    """A '## [ADVISORY]' block the shell appends AFTER a reviewer section (a
    top-level, outside-fence header) is not a reviewer and must not be pulled
    into the preceding reviewer's fenced JSON body (fence-aware split guard for
    the #982 fix — greedy fence extraction must still see only the reviewer's
    own JSON)."""
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","verdict":"approve","findings":[]}')
        + "## [ADVISORY] Full-context request — diff-centric mode (SPEC-379)\n"
        + "```\n[ADVISORY] Reviewer requested full-repository context.\n```\n\n"
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


# --------------------------------------------------------------------------- #
# ADR-1683 D-3 — validator-summary digest (three-tier degradation)            #
# --------------------------------------------------------------------------- #
def _make_summary(n_results: int, raw_value_len: int = 0, error_len: int = 0) -> dict:
    """A synthetic validators/summary.json shaped like the real thing (13
    dimensions in production; arbitrary count here to control serialized
    size). `raw_value_len` / `error_len` pad specific fields to force a
    tier to exceed the 16,384-byte cap."""
    results = []
    for i in range(n_results):
        results.append(
            {
                "dimension": f"dim{i}",
                "score": 0.5,
                "weight": 0.1,
                "tier_floor": None,
                "error": ("e" * error_len) if error_len else None,
                "raw_value": {"blob": "x" * raw_value_len} if raw_value_len else {"ok": True},
                "evidence": [{"file": "a.py", "line": 1, "message": "m", "severity": "low"}] * 2,
                "findings": [{"severity": "low", "file": "a.py", "line": 1, "message": "m"}],
                "checklist_items": ["c1", "c2"],
            }
        )
    return {
        "composite_score": 0.42,
        "tier": "MEDIUM",
        "validator_count": n_results,
        "successful_validators": n_results,
        "results": results,
    }


def test_digest_tier1_used_when_within_cap():
    """A small summary fits tier 1 (full per-validator scores/weights/floors +
    evidence/finding/checklist COUNTS) with no degradation and no stderr line."""
    digest, stderr_lines = digest_validators(_make_summary(3, raw_value_len=50))
    assert digest["_digest_tier"] == 1
    assert stderr_lines == []
    assert digest["results"][0]["raw_value"] == {"blob": "x" * 50}
    assert digest["results"][0]["evidence_count"] == 2
    assert digest["results"][0]["finding_count"] == 1
    assert digest["results"][0]["checklist_count"] == 2
    json.loads(json.dumps(digest))


def test_digest_degrades_to_tier2_at_the_16384_byte_boundary():
    """Tier 1 exceeds the cap (large `raw_value`s) -> tier 2 drops `raw_value`
    per validator and fits; exactly one degradation line is printed."""
    digest, stderr_lines = digest_validators(_make_summary(10, raw_value_len=3000))
    assert digest["_digest_tier"] == 2
    assert len(stderr_lines) == 1
    assert "tier 2" in stderr_lines[0]
    assert "16384" in stderr_lines[0]
    assert "raw_value" not in digest["results"][0]
    assert digest["results"][0]["dimension"] == "dim0"
    json.loads(json.dumps(digest))


def test_digest_degrades_to_tier3_when_tier2_also_exceeds_cap():
    """Even with `raw_value` dropped, enough validators (large `error` text)
    still exceed the cap -> tier 3 drops all per-validator detail down to a
    bare `dimension: score` map. Two degradation lines are printed (2, then 3)."""
    digest, stderr_lines = digest_validators(_make_summary(120, error_len=250))
    assert digest["_digest_tier"] == 3
    assert len(stderr_lines) == 2
    assert "tier 2" in stderr_lines[0]
    assert "tier 3" in stderr_lines[1]
    assert "results" not in digest
    assert digest["scores"] == {f"dim{i}": 0.5 for i in range(120)}
    json.loads(json.dumps(digest))


def test_digest_never_carries_evidence_findings_or_checklist_arrays():
    """D-3's whole point: the anchoring content (evidence/findings/checklist
    arrays — file:line:message pointers) must never survive into the prompt,
    at ANY tier — only aggregate counts (tier 1/2) or nothing (tier 3)."""
    for summary, expect_tier in (
        (_make_summary(3, raw_value_len=10), 1),
        (_make_summary(10, raw_value_len=3000), 2),
        (_make_summary(120, error_len=250), 3),
    ):
        digest, _ = digest_validators(summary)
        assert digest["_digest_tier"] == expect_tier
        blob = json.dumps(digest)
        assert '"evidence"' not in blob, blob
        assert '"findings"' not in blob, blob
        assert '"checklist_items"' not in blob, blob


def test_digest_carries_tier_and_note_and_is_valid_json_at_every_tier():
    for summary in (
        _make_summary(3, raw_value_len=10),
        _make_summary(10, raw_value_len=3000),
        _make_summary(120, error_len=250),
    ):
        digest, _ = digest_validators(summary)
        assert digest["_digest_tier"] in (1, 2, 3)
        assert digest["_digest_note"]
        json.loads(json.dumps(digest))


# ── digest-validators CLI shim: never take run_second_review.sh down with it ──


def _run_digest_cli(tmp_path, raw_text, capsys):
    """Invoke the `digest-validators` subcommand against a file holding
    `raw_text`, returning (exit_code, stdout, stderr)."""
    f = tmp_path / "summary.json"
    f.write_text(raw_text, encoding="utf-8")
    rc = second_review_logic.main(["digest-validators", "--file", str(f)])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_digest_cli_exits_zero_on_json_that_parses_but_is_not_an_object(tmp_path, capsys):
    """A summary.json that is valid JSON but not an object (a list, or `null`)
    must not reach _digest_tier1's .get() and raise. The shell assigns this via
    VALIDATOR_DIGEST=$(python3 ...) under `set -euo pipefail`, so a non-zero
    exit here kills the whole second review — the exact silent-disable class
    #1683 exists to remove. Degrade to an empty digest instead, as a missing
    file already did."""
    for payload in ("[]", '["a", "b"]', "null", '"a string"', "42"):
        rc, out, _ = _run_digest_cli(tmp_path, payload, capsys)
        assert rc == 0, f"payload={payload!r} exited {rc}"
        assert out == "", f"payload={payload!r} printed {out!r}"


def test_digest_cli_exits_zero_on_unparseable_and_missing_input(tmp_path, capsys):
    """The pre-existing read/parse guard still holds."""
    rc, out, _ = _run_digest_cli(tmp_path, "{not json", capsys)
    assert rc == 0 and out == ""

    rc = second_review_logic.main(["digest-validators", "--file", str(tmp_path / "absent.json")])
    assert rc == 0 and capsys.readouterr().out == ""


def test_digest_cli_prints_a_digest_for_a_well_formed_object(tmp_path, capsys):
    """The guard must not swallow the happy path."""
    rc, out, err = _run_digest_cli(tmp_path, json.dumps(_make_summary(3, raw_value_len=50)), capsys)
    assert rc == 0
    assert json.loads(out)["_digest_tier"] == 1
    assert err == "", "the happy path must not emit a degradation line"


def test_digest_cli_names_the_cause_on_stderr_when_input_is_not_an_object(tmp_path, capsys):
    """Exiting 0 must not mean degrading silently. The non-dict branch drops the
    entire validator digest from the reviewer prompt; without a stderr line that
    loss is invisible, which is the same silent-loss-of-review-context class
    #1683 exists to remove, arriving by a third route. Also keeps true the claim
    run_second_review.sh makes in its own comment above the call."""
    for payload, typename in (("[]", "list"), ("null", "NoneType"), ("42", "int")):
        rc, out, err = _run_digest_cli(tmp_path, payload, capsys)
        assert rc == 0 and out == ""
        assert err.strip(), f"payload={payload!r} degraded silently"
        assert typename in err, f"payload={payload!r} stderr did not name the type: {err!r}"
        assert "empty validator summary" in err, err


def test_digest_cli_names_the_cause_on_stderr_when_input_cannot_be_read(tmp_path, capsys):
    """Same guarantee for the read/parse branch — and for any future bug inside
    digest_validators(), which now sits inside this try and would otherwise
    degrade to silent-empty."""
    rc, out, err = _run_digest_cli(tmp_path, "{not json", capsys)
    assert rc == 0 and out == ""
    assert "JSONDecodeError" in err or "ValueError" in err, err
    assert "empty validator summary" in err, err

    rc = second_review_logic.main(["digest-validators", "--file", str(tmp_path / "absent.json")])
    captured = capsys.readouterr()
    assert rc == 0 and captured.out == ""
    assert "FileNotFoundError" in captured.err, captured.err


def test_degradation_lines_name_the_artifact_they_actually_measured():
    """The tier-2/tier-3 stderr lines report the size of the tier-1/tier-2
    DIGEST, not of the full summary. Calling either 'full summary' makes an
    operator under-read the real overage on a path the ADR added specifically
    to be trustworthy."""
    _, lines = digest_validators(_make_summary(120, error_len=250))
    assert "tier 1 digest" in lines[0], lines[0]
    assert "tier 2 digest" in lines[1], lines[1]
    assert "full summary" not in " ".join(lines)


# ── #1718 — assess_consumption ───────────────────────────────────────────────

assess_consumption = second_review_logic.assess_consumption
_T = 6.0


def _meta(input_tokens, cache=None, num_turns=None):
    usage = {"input_tokens": input_tokens}
    if cache is not None:
        usage["cache_read_tokens"] = cache
    meta = {"usage": usage}
    if num_turns is not None:
        meta["num_turns"] = num_turns
    return meta


def test_consumption_verified_at_four_bytes_per_token():
    r = assess_consumption(400_000, _meta(100_000), _T)
    assert r["status"] == "verified"
    assert r["bytes_per_token"] == 4.0
    assert set(r) == {
        "status",
        "prompt_bytes",
        "input_tokens",
        "cache_read_tokens",
        "consumed_tokens",
        "bytes_per_token",
        "threshold",
        "num_turns",
        "reason",
    }


def test_consumption_not_consumed_for_the_measured_1718_case():
    r = assess_consumption(793_000, _meta(68_000), _T)
    assert r["status"] == "not_consumed"
    assert round(r["bytes_per_token"], 1) == 11.7


def test_consumption_threshold_boundary():
    assert assess_consumption(600, _meta(100), _T)["status"] == "verified"
    assert assess_consumption(60_001, _meta(10_000), _T)["status"] == "not_consumed"


def test_consumption_cache_both_readings_over_is_not_consumed():
    r = assess_consumption(1_000_000, _meta(100_000, cache=50_000), _T)
    assert r["status"] == "not_consumed"
    assert r["consumed_tokens"] == 150_000


def test_consumption_cache_readings_disagree_is_unverified():
    # generous 900k/150k = 6.0 (<= T) but input-only 900k/100k = 9.0 (> T)
    r = assess_consumption(900_000, _meta(100_000, cache=50_000), _T)
    assert r["status"] == "unverified"
    assert r["reason"] == "cache_semantics_unmeasured"


def test_consumption_cache_both_readings_under_is_verified():
    assert assess_consumption(400_000, _meta(100_000, cache=50_000), _T)["status"] == "verified"


def test_consumption_multi_turn_under_threshold_is_unverified():
    r = assess_consumption(400_000, _meta(100_000, num_turns=3), _T)
    assert r["status"] == "unverified" and r["reason"] == "multi_turn"


def test_consumption_multi_turn_over_threshold_is_still_not_consumed():
    assert assess_consumption(793_000, _meta(68_000, num_turns=3), _T)["status"] == "not_consumed"


def test_consumption_bool_num_turns_is_ignored():
    assert assess_consumption(400_000, _meta(100_000, num_turns=True), _T)["status"] == "verified"


def test_consumption_invalid_input_tokens_fail_closed():
    for bad in (0, True, "68000", -4, 1.5):
        assert assess_consumption(400_000, _meta(bad), _T)["status"] == "invalid_usage", bad


def test_consumption_negative_or_garbage_cache_is_invalid():
    assert assess_consumption(400_000, _meta(100_000, cache=-1), _T)["status"] == "invalid_usage"
    assert assess_consumption(400_000, _meta(100_000, cache="x"), _T)["status"] == "invalid_usage"


def test_consumption_no_usage_is_unverified():
    for meta in ({}, {"usage": None}, {"usage": {"output_tokens": 5}}, {"usage": []}):
        r = assess_consumption(400_000, meta, _T)
        assert r["status"] == "unverified" and r["reason"] == "no_usage", meta


def test_consumption_threshold_clamp_is_lower_only():
    resolve = second_review_logic.resolve_threshold
    assert resolve("9.0")[0] == 6.0 and resolve("9.0")[1]
    assert resolve("3.0") == (3.0, "")
    assert resolve("")[0] == 6.0 and resolve("")[1] == ""
    for bad in ("abc", "nan", "inf", "1.0", "-3"):
        assert resolve(bad)[0] == 6.0 and resolve(bad)[1], bad


def _run_consumption_cli(tmp_path, capsys, meta_text, prompt_bytes, extra=()):
    meta = tmp_path / "meta.json"
    if meta_text is not None:
        meta.write_text(meta_text)
    rc = second_review_logic.main(
        ["consumption", "--prompt-bytes", str(prompt_bytes), "--metadata-file", str(meta), *extra]
    )
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_consumption_cli_exit_codes(tmp_path, capsys):
    rc, r = _run_consumption_cli(tmp_path, capsys, json.dumps(_meta(100_000)), 400_000)
    assert (rc, r["status"]) == (0, "verified")
    rc, r = _run_consumption_cli(tmp_path, capsys, "{}", 400_000)
    assert (rc, r["status"]) == (0, "unverified")
    rc, r = _run_consumption_cli(tmp_path, capsys, json.dumps(_meta(68_000)), 793_000)
    assert (rc, r["status"]) == (1, "not_consumed")
    rc, r = _run_consumption_cli(tmp_path, capsys, json.dumps(_meta(0)), 400_000)
    assert (rc, r["status"]) == (1, "invalid_usage")


def test_consumption_cli_missing_or_garbage_metadata_is_unverified(tmp_path, capsys):
    rc, r = _run_consumption_cli(tmp_path, capsys, None, 400_000)
    assert (rc, r["status"]) == (0, "unverified")
    rc, r = _run_consumption_cli(tmp_path, capsys, "{not json", 400_000)
    assert (rc, r["status"]) == (0, "unverified")
    rc, r = _run_consumption_cli(tmp_path, capsys, "[1,2]", 400_000)
    assert (rc, r["status"]) == (0, "unverified")


def test_consumption_cli_threshold_override(tmp_path, capsys):
    meta = json.dumps(_meta(100_000))
    rc, r = _run_consumption_cli(tmp_path, capsys, meta, 400_000, ("--max-bytes-per-token", "3.0"))
    assert (rc, r["status"], r["threshold"]) == (1, "not_consumed", 3.0)
    rc, r = _run_consumption_cli(tmp_path, capsys, meta, 700_000, ("--max-bytes-per-token", "9.0"))
    assert (rc, r["status"], r["threshold"]) == (1, "not_consumed", 6.0)
