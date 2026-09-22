"""#1770 — pin the linkage between the reviewer schemas `run_second_review.sh`
actually sends and the finding-class the dedup fingerprint keys on.

The defect this guards: `_class_of_finding` asserted a contract ("agy uses
`category`, codex uses `type`") that the caller in this same repository did not
implement. Neither prompt sent either field, so the class resolved to `""` for
every finding the script could produce and the fingerprint silently collapsed
from finding granularity to FILE granularity — one `filed:#N` disposition then
silenced materially different findings in the same file.

Nothing tested the linkage, so the drift was silent. These tests read the
schemas out of the shell script itself, so a future prompt edit that drops the
class field fails here instead of quietly disabling the ledger.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MOD_PATH = _ROOT / "scripts" / "oversight" / "validation_logic.py"
_SCRIPT = _ROOT / "scripts" / "run_second_review.sh"

_spec = importlib.util.spec_from_file_location("validation_logic", _MOD_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load {_MOD_PATH}"
validation_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation_logic)

fingerprint = validation_logic.fingerprint
compute_verdict = validation_logic.compute_verdict
load_ledger = validation_logic.load_ledger
_class_of_finding = validation_logic._class_of_finding
_is_degenerate = validation_logic._is_degenerate
_files_of = validation_logic._files_of

# The keys `_class_of_finding` resolves a class from, in precedence order. If
# this list and the function disagree, the tests below are measuring nothing.
CLASS_KEYS = ("category", "type", "cwe")


def _finding_schema_keys(reviewer: str) -> set[str]:
    """Field names of the per-finding object in `reviewer`'s prompt schema.

    The schemas are embedded in a double-quoted bash string, so every JSON quote
    is backslash-escaped. Locate the reviewer's block by its `\"reviewer\":
    \"<name>\"` line, then take the object inside `\"findings\": [ ... ]`.
    """
    text = _SCRIPT.read_text(encoding="utf-8").replace('\\"', '"')
    marker = f'"reviewer": "{reviewer}"'
    assert marker in text, f"no prompt block found for reviewer {reviewer!r}"
    block = text[text.index(marker) :]
    start = block.index('"findings": [')
    obj = block[start : block.index("]", start)]
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', obj))


def _sample_finding(reviewer: str) -> dict:
    """A finding shaped exactly like the reviewer's schema, with a plausible
    value for each key — the closest a pure test can get to a real response."""
    values = {
        "severity": "high",
        "category": "logic-error",
        "type": "bash",
        "cwe": "CWE-703",
        "file": "scripts/run_second_review.sh",
        "line": 42,
        "finding": "x",
        "why": "y",
        "suggestion": "z",
        "attack_scenario": "a",
    }
    return {k: values[k] for k in _finding_schema_keys(reviewer) if k in values}


# ── the linkage itself ────────────────────────────────────────────────────────
def test_both_schemas_send_a_field_the_fingerprint_keys_on():
    """The root cause: a schema that carries none of CLASS_KEYS makes every
    finding class-less, which is what collapsed the fingerprint to the file."""
    for reviewer in ("agy", "codex"):
        keys = _finding_schema_keys(reviewer)
        assert keys & set(CLASS_KEYS), (
            f"{reviewer}'s finding schema in run_second_review.sh carries none of "
            f"{CLASS_KEYS} — the dedup fingerprint would key on an empty class "
            f"and collapse to file granularity (#1770). Schema keys: {sorted(keys)}"
        )


def test_schema_shaped_findings_produce_a_populated_class():
    """End-to-end on the real schemas: a finding shaped like the prompt asks for
    resolves to a non-empty class, so its fingerprint is not degenerate."""
    for reviewer in ("agy", "codex"):
        f = _sample_finding(reviewer)
        cls = _class_of_finding(f)
        assert cls, f"{reviewer}: class resolved empty from {f!r}"
        assert not _is_degenerate(_files_of(f), cls), f"{reviewer}: degenerate"


def test_class_keys_list_matches_the_implementation():
    """Guards the guard: if `_class_of_finding` grows or drops a key without
    CLASS_KEYS following, the linkage test above silently stops covering it."""
    for key in CLASS_KEYS:
        assert (
            _class_of_finding({key: "probe-value"}) == "probe-value"
        ), f"{key!r} is in CLASS_KEYS but _class_of_finding does not read it"
    assert _class_of_finding({"unrelated_key": "v"}) == ""


# ── the fail-open the linkage break caused ────────────────────────────────────
def test_two_findings_same_file_different_class_do_not_share_a_fingerprint():
    """The motivating case: a CWE-703 and a CWE-20 finding on one file. Under the
    defect both fingerprinted to `[[<file>], ""]`, so dispositioning the first
    silenced the second."""
    doc = "docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md"
    a = {"severity": "high", "file": doc, "cwe": "CWE-703"}
    b = {"severity": "high", "file": doc, "cwe": "CWE-20"}
    assert fingerprint(a) != fingerprint(b)


def test_disposition_does_not_silence_a_different_class_on_the_same_file(tmp_path):
    """Full path through the ledger: record the CWE-703 finding as `filed:#1767`
    and confirm the unrelated CWE-20 finding still counts as NEW blocking."""
    doc = "docs/a.md"
    ledger = tmp_path / "ledger.jsonl"
    validation_logic.record_ledger_entry(
        {"files": [doc], "class": "CWE-703", "disposition": "filed:#1767"},
        str(ledger),
    )
    blocks = [
        {
            "verdict": "request_changes",
            "findings": [
                {"severity": "high", "file": doc, "cwe": "CWE-703"},
                {"severity": "high", "file": doc, "cwe": "CWE-20"},
            ],
        }
    ]
    result = compute_verdict(blocks, str(ledger))
    assert result["blocking_count"] == 2
    assert result["new_blocking_count"] == 1, "the unrelated CWE-20 was silenced"
    assert result["verdict"] == "request_changes"


# ── (b) the widened degeneracy guard ──────────────────────────────────────────
def test_class_less_ledger_entry_contributes_no_silencing_key(tmp_path):
    """A class-less entry WITH files is degenerate now (#1770 widens #983): it
    must not become a file-granular silencing key."""
    ledger = tmp_path / "ledger.jsonl"
    validation_logic.record_ledger_entry(
        {"files": ["docs/a.md"], "class": "", "disposition": "filed:#1767"},
        str(ledger),
    )
    assert load_ledger(str(ledger)) == set()


def test_class_less_finding_is_never_silenced(tmp_path):
    """Symmetric fail-closed on the finding side: a finding with no class counts
    as NEW blocking even against a ledger entry covering the same file."""
    ledger = tmp_path / "ledger.jsonl"
    validation_logic.record_ledger_entry(
        {"files": ["docs/a.md"], "class": "logic-error", "disposition": "fixed"},
        str(ledger),
    )
    blocks = [{"findings": [{"severity": "high", "file": "docs/a.md"}]}]
    assert compute_verdict(blocks, str(ledger))["new_blocking_count"] == 1


def test_file_less_finding_with_a_real_class_still_dedups(tmp_path):
    """Scope check: widening the guard must not disable silencing for a
    file-less but CLASS-ful finding, which #983 left silence-able."""
    ledger = tmp_path / "ledger.jsonl"
    validation_logic.record_ledger_entry(
        {"files": [], "class": "spec-adherence", "disposition": "fixed"}, str(ledger)
    )
    blocks = [{"findings": [{"severity": "high", "category": "spec-adherence"}]}]
    assert compute_verdict(blocks, str(ledger))["new_blocking_count"] == 0


# ── class normalisation (match stability) ─────────────────────────────────────
def test_recorded_class_matches_case_and_spacing_variants():
    """`--record` is typed by hand; codex emits `CWE-703`. These must be one key."""
    base = validation_logic._ledger_fingerprint({"files": ["a.md"], "class": "CWE-703"})
    for variant in ("cwe-703", "CWE-703", " cwe 703 ", "CWE_703"):
        assert fingerprint({"file": "a.md", "cwe": variant}) == base, variant


def test_distinct_cwes_normalise_apart():
    a = fingerprint({"file": "a.md", "cwe": "CWE-703"})
    b = fingerprint({"file": "a.md", "cwe": "CWE-70"})
    assert a != b


# ── the record CLI: argparse `required` does not mean non-empty ───────────────
def test_record_cli_rejects_empty_class(tmp_path, capsys):
    """`--class ""` satisfies argparse's `required=True`. It used to write a
    class-less (file-granular) silencing key — the one path that could still
    produce one. `run_second_review.sh --record` already refused it."""
    ledger = tmp_path / "ledger.jsonl"
    rc = validation_logic.main(
        [
            "record",
            "--ledger",
            str(ledger),
            "--files",
            "docs/a.md",
            "--class",
            "",
            "--disposition",
            "filed:#1767",
        ]
    )
    assert rc == 2
    assert not ledger.exists(), "a rejected record must not touch the ledger"


def test_record_cli_rejects_empty_file_list(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    rc = validation_logic.main(
        [
            "record",
            "--ledger",
            str(ledger),
            "--files",
            " , ",
            "--class",
            "logic-error",
            "--disposition",
            "fixed",
        ]
    )
    assert rc == 2
    assert not ledger.exists()


def test_record_cli_accepts_a_real_class(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    rc = validation_logic.main(
        [
            "record",
            "--ledger",
            str(ledger),
            "--files",
            "docs/a.md",
            "--class",
            "CWE-703",
            "--disposition",
            "filed:#1767",
        ]
    )
    assert rc == 0
    assert load_ledger(str(ledger)) == {'[["docs/a.md"], "cwe-703"]'}
