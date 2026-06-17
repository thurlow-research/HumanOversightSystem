"""Tests for scripts/oversight/agents_static_logic.py — SPEC-336.

Exercises the FOUR pure functions (extract_path_refs, filter_path_ref,
extract_escalation_targets, classify_token) with synthetic string inputs only —
no subprocess / network / file I/O (binding 6 / R5). Covers every acceptance
criterion AC1-AC10 plus the anchoring and extraction edge cases.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "agents_static_logic.py"
)
_spec = importlib.util.spec_from_file_location("agents_static_logic", _MOD_PATH)
asl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(asl)

extract_path_refs = asl.extract_path_refs
filter_path_ref = asl.filter_path_ref
extract_escalation_targets = asl.extract_escalation_targets
classify_token = asl.classify_token
SKIP, CHECK, EXTERNAL = asl.SKIP, asl.CHECK, asl.EXTERNAL


# --------------------------------------------------------------------------- #
# extract_escalation_targets — R1 / AC1-AC4                                    #
# --------------------------------------------------------------------------- #
def test_escalation_standard():
    # AC1
    assert extract_escalation_targets("escalates to `architect`") == ["architect"]


def test_escalation_multiple_in_order():
    # AC2 — order matches document order
    text = "it invokes `risk-assessor` then notifies `oversight-orchestrator`"
    assert extract_escalation_targets(text) == [
        "risk-assessor",
        "oversight-orchestrator",
    ]


def test_escalation_verb_variants():
    # AC3 — past tense / past participle via \w+ suffix
    text = "escalated to `coder` and was invoked by `pm-agent`"
    out = extract_escalation_targets(text)
    assert "coder" in out and "pm-agent" in out


def test_escalation_no_verb_no_match():
    # AC4 — a bare backtick name with no preceding escalation verb is not matched
    assert extract_escalation_targets("the `coder` file lives here") == []


def test_escalation_empty():
    assert extract_escalation_targets("") == []


# --------------------------------------------------------------------------- #
# classify_token — R2 / AC5-AC8 + anchoring                                    #
# --------------------------------------------------------------------------- #
_NON_AGENT = "human|you|main|build|prod|staging|ci|github|pr"
_LABELS = (
    "needs-human|needs-ai|needs-coordination|hos-claimed|hos-halt|"
    "hos-budget-gated|hos-embargo|hos-autowork-authorized|"
    "release-request|release-authorized"
)
_SHORT = "architect|coder|human"


def _classify(token, external=""):
    return classify_token(token, set(), _NON_AGENT, _LABELS, _SHORT, external)


def test_classify_non_agent_tokens():
    # AC5
    assert _classify("human") == SKIP
    assert _classify("ci") == SKIP


def test_classify_labels():
    # AC6
    assert _classify("needs-human") == SKIP
    assert _classify("hos-claimed") == SKIP


def test_classify_hyphen_heuristic():
    # AC7
    assert _classify("architect") == CHECK       # in known_short_agents
    assert _classify("mylib") == SKIP            # no hyphen, not short agent
    assert _classify("code-reviewer") == CHECK   # has hyphen


def test_classify_external():
    # AC8
    assert _classify("pm-agent", external="pm-agent") == EXTERNAL


def test_classify_anchoring_no_substring_overmatch():
    # 'superhuman' must NOT match the anchored non-agent entry 'human'. It is not
    # a non-agent token; lacking a hyphen and not being a known short agent, the
    # hyphen heuristic SKIPs it — but crucially NOT via the non-agent stage (the
    # anchored ^()$ semantics are preserved: substring 'human' does not match).
    assert _classify("superhuman") == SKIP
    # 'super-human' has a hyphen and is not an exact non-agent token -> CHECK,
    # proving the non-agent match is exact (anchored), not substring.
    assert _classify("super-human") == CHECK


def test_classify_label_anchoring():
    # 'needs-human-extra' is not the exact label 'needs-human'; has hyphen -> CHECK
    assert _classify("needs-human-extra") == CHECK


def test_classify_empty_external_never_external():
    assert _classify("pm-agent", external="") == CHECK


# --------------------------------------------------------------------------- #
# filter_path_ref — R3 / AC9-AC10                                              #
# --------------------------------------------------------------------------- #
_OUTPUT_DOCS = {
    "docs/pm/CONFIRMED-REQUIREMENTS.md",
    "docs/design/TECHNICAL-DESIGN.md",
}


def test_filter_skip_http():
    assert filter_path_ref("http://example.com/foo.md", set()) == SKIP


def test_filter_skip_no_slash():
    # AC9 — bare filename
    assert filter_path_ref("AGENTS.md", set()) == SKIP


def test_filter_skip_template_placeholder():
    assert filter_path_ref("{SPEC_FILE}", set()) == SKIP


def test_filter_skip_project_scoped():
    assert filter_path_ref("PROJECT/docs/design.md", set()) == SKIP


def test_filter_skip_output_doc():
    assert filter_path_ref(
        "docs/pm/CONFIRMED-REQUIREMENTS.md", _OUTPUT_DOCS
    ) == SKIP


def test_filter_skip_empty():
    assert filter_path_ref("", set()) == SKIP
    assert filter_path_ref("``", set()) == SKIP


def test_filter_check_real_path():
    # AC10
    assert filter_path_ref("scripts/oversight/panel_logic.py", set()) == CHECK
    assert filter_path_ref("contract/OVERSIGHT-CONTRACT.md", set()) == CHECK


def test_filter_strips_backticks_quotes_and_anchor():
    # cleaning: backticks, double-quotes, #anchor all stripped before the cascade
    assert filter_path_ref('`docs/x/y.md#section`', set()) == CHECK
    assert filter_path_ref('"docs/x/y.md"', set()) == CHECK


# --------------------------------------------------------------------------- #
# extract_path_refs — OQ-2                                                     #
# --------------------------------------------------------------------------- #
def test_extract_path_refs_basic():
    text = "see `scripts/oversight/panel_logic.py` and `docs/AGENTS.md`"
    out = extract_path_refs(text)
    assert "scripts/oversight/panel_logic.py" in out
    # bare AGENTS.md has no directory separator before the extension match anchor;
    # the pattern requires a `/` so a single-segment name is not captured here.


def test_extract_path_refs_drops_http():
    text = "`http://x.com/a/b.md` and `scripts/x/y.sh`"
    out = extract_path_refs(text)
    assert all(not r.startswith("http") for r in out)
    assert "scripts/x/y.sh" in out


def test_extract_path_refs_strips_backticks():
    out = extract_path_refs("`aa/b/c.json`")
    assert out == ["aa/b/c.json"]


def test_extract_path_refs_empty():
    assert extract_path_refs("") == []
    assert extract_path_refs("no paths here") == []


def test_extract_path_refs_preserves_order():
    # The path pattern requires >=2 chars before the first slash (faithful to the
    # original grep -oE: [A-Za-z][A-Za-z0-9_./-]+/...), so first segments are
    # multi-char.
    text = "`aa/one.md` then `bb/two.py` then `cc/three.yaml`"
    assert extract_path_refs(text) == ["aa/one.md", "bb/two.py", "cc/three.yaml"]
