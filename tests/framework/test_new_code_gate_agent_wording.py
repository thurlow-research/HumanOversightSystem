"""Static checks of the S4 agent, contract and template wording (#2304, TD section 6, AC-32, AC-33).

The unit-test.md, oversight-evaluator.md and CLAUDE.md edits are authored by the top-level session
(protected surfaces); the checks on those files stay red until that commit lands.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT_TEST_AGENT = ROOT / ".claude" / "agents" / "unit-test.md"
EVALUATOR_AGENT = ROOT / ".claude" / "agents" / "oversight-evaluator.md"
CONTRACT = ROOT / "contract" / "OVERSIGHT-CONTRACT.md"
TEMPLATE = ROOT / "templates" / "base-agent-register-examples.md"
SPEC = ROOT / "docs" / "v0.3.0" / "BASE-AGENTS-SPEC.md"
DJANGO_PACK = ROOT / "packs" / "django" / "unit-test.md"
CLAUDE_MD = ROOT / "CLAUDE.md"

PACK_NA_UNQUALIFIED = "N/A (disabled in PACK)"
GATE_ROW = (
    "| Running the new-code coverage + mutation gate locally on HEAD "
    "(needs a clean-tree run_tests.sh sidecar first) | "
    "`scripts/oversight/.venv/bin/python -m scripts.framework.new_code_gate run` |"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", _text(path))


def _core_region(path: Path) -> str:
    text = _text(path)
    start = text.index("<!-- HOS:CORE:START -->")
    end = text.index("<!-- HOS:CORE:END -->")
    return text[start:end]


def test_unit_test_core_and_contract_disallow_na_for_python():
    core = _core_region(UNIT_TEST_AGENT)
    for text in (core, _text(CONTRACT), _text(TEMPLATE)):
        assert "non-equivalent" not in text
        assert "Equivalents_documented" not in text
    assert PACK_NA_UNQUALIFIED not in core
    flat = re.sub(r"\s+", " ", core)
    assert "for Python, mutation is never disabled and `Mutant_score_pct` is never N/A" in flat
    assert "N/A only when the PACK disabled mutation for a non-Python stack" in flat
    assert "Equivalent mutants are **not** removed from the denominator" in flat
    assert "**Measured, never declared.**" in flat
    assert "a `test-resistance` escalation, never a declaration" in flat


def test_unit_test_core_names_no_mutation_tool():
    core = _core_region(UNIT_TEST_AGENT).lower()
    for tool in ("mutmut", "cosmic-ray", "stryker", "new_code_gate"):
        assert tool not in core


def test_evaluator_phase1_numeric_mutant_score_rule():
    flat = _flat(EVALUATOR_AGENT)
    assert (
        "If the step's diff (`base_sha..head_sha`) changes any `.py` file, `Coverage_pct` and "
        "`Mutant_score_pct` must each be a bare number (integer or decimal, optionally followed by `%`)"
    ) in flat
    assert "`N/A`, `not run`, `sampled`, a range, prose, or an absent field" in flat
    assert (
        "The PACK N/A form is accepted only when the step changes no `.py` file. (#2304 REQ-32)"
        in flat
    )


def test_contract_register_example_and_note():
    text = _text(CONTRACT)
    assert "Coverage_pct: 83" in text
    assert "Mutant_score_pct: 77" in text
    assert "Surviving_equivalents: 2   # informational; never subtracted" in text
    assert "Equivalents_documented" not in text
    flat = _flat(CONTRACT)
    assert (
        "`N/A` is allowed only where a PACK disabled mutation for a non-Python stack. "
        "Equivalent mutants are not excluded from the denominator."
    ) in flat


def test_contract_compliance_condition_4a_follows_condition_4():
    text = _text(CONTRACT)
    cond4 = text.index("4. `test-unit` declaration is missing `Thresholds_met: true`")
    cond4a = text.index("4a. `test-unit` declaration on a step whose diff changes a `.py` file")
    cond5 = text.index("5. `test-system` declaration is missing")
    assert cond4 < cond4a < cond5
    assert "non-numeric `Coverage_pct` or `Mutant_score_pct` → COMPLIANCE FAIL (#2304)." in text


def test_template_register_example_matches_contract():
    text = _text(TEMPLATE)
    assert "Mutant_score_pct: 77" in text
    assert "Surviving_equivalents: 2   # informational; never subtracted" in text
    assert "Equivalents_documented" not in text


def test_base_agents_spec_field_list_and_python_sentences():
    text = _text(SPEC)
    assert "Equivalents_documented" not in text
    assert (
        "`Mutant_score_pct` is measured; N/A only for PACK-disabled non-Python stacks, #2304"
    ) in text
    sentence = (
        "Python has a mutation framework, so a PACK may not disable mutation for Python (#2304)."
    )
    assert text.count(sentence) == 2


def test_django_pack_denominator_includes_equivalent_mutants():
    text = _text(DJANGO_PACK)
    assert "non-equivalent" not in text
    assert (
        "total mutants (equivalent mutants are not excluded; the 25% headroom absorbs them — #2304)"
    ) in text


def test_claude_md_canonical_entry_point_row_present_after_test_suite_row():
    text = _text(CLAUDE_MD)
    assert GATE_ROW in text
    suite_row = text.index("| Running the PR-required test suite |")
    assert text.index(GATE_ROW) > suite_row
    assert text.index(GATE_ROW) < text.index("| Running blocking pre-review gates |")
