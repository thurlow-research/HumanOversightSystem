"""Tests for #291 — PROJECT-governs enumerated non-overridable carve-out.

Asserts the carve-out contract for every layered (CORE-region) agent file:

  * every CORE-region agent carries the canonical clause verbatim,
  * the clause is inside the CORE region (not PROJECT / PACK),
  * the OQ-291-A item-2/item-3 split is preserved (5 numbered items),
  * the old unconditional "PROJECT governs" sentence is gone, and
  * the check_agents_static.sh §6 predicate rejects the old unconditional form.

The in-scope file list is regenerated at runtime via glob (OQ-291-D); no
filename list or count is hardcoded.  The negative case (5.3a in the technical
design) encodes the §6 predicate directly and is intentionally coupled to it:
if §6's anchor string changes, this test must change too.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# §6 anchor — unique to the conditional clause, absent from the old unconditional form.
ANCHOR = "PROJECT may NEVER"
OLD_UNCONDITIONAL = "conflicts with anything above, PROJECT governs"

CORE_START = "<!-- HOS:CORE:START -->"
CORE_END = "<!-- HOS:CORE:END -->"
PROJECT_START = "<!-- HOS:PROJECT:START -->"

CANONICAL_AGENT = AGENTS_DIR / "coder.md"  # authoritative source of the clause


# ── helpers ──────────────────────────────────────────────────────────────────
def _core_region_files():
    """In-scope = layered agent files carrying a CORE region. Regenerated at runtime."""
    return sorted(
        p for p in AGENTS_DIR.glob("*.md")
        if CORE_START in p.read_text(encoding="utf-8")
    )


def _extract_clause(text: str) -> str:
    """Return the canonical clause block: the EXTEND line through 'never looser.'."""
    m = re.search(
        r"^The PROJECT section below may EXTEND.*?never looser\.\s*$",
        text,
        re.DOTALL | re.MULTILINE,
    )
    return m.group(0) if m else ""


def _section_six_predicate(text: str) -> bool:
    """Mirror of check_agents_static.sh §6: a CORE-region file is conformant
    iff it carries the anchor. Returns True when conformant (would PASS)."""
    if CORE_START not in text:
        return True  # §6 skips non-layered files
    return ANCHOR in text


CANONICAL_CLAUSE = _extract_clause(CANONICAL_AGENT.read_text(encoding="utf-8"))


# ── sanity on the fixtures themselves ────────────────────────────────────────
def test_canonical_clause_extractable():
    assert CANONICAL_CLAUSE, "could not extract canonical clause from coder.md"
    assert ANCHOR in CANONICAL_CLAUSE


def test_in_scope_set_non_empty():
    # Guards against a glob/path regression silently passing zero files (5.4).
    assert _core_region_files(), "no CORE-region agent files found — glob/path regression?"


# ── AC-291-01 / AC-291-06 : every CORE agent carries the clause ──────────────
def test_canonical_clause_in_every_core_agent():
    missing = [p.name for p in _core_region_files() if ANCHOR not in p.read_text(encoding="utf-8")]
    assert not missing, f"CORE-region agents missing carve-out clause: {missing}"


# ── AC-291-01 (verbatim) ─────────────────────────────────────────────────────
def test_clause_is_verbatim():
    bad = []
    for p in _core_region_files():
        if _extract_clause(p.read_text(encoding="utf-8")) != CANONICAL_CLAUSE:
            bad.append(p.name)
    assert not bad, f"clause not verbatim against coder.md in: {bad}"


# ── AC-291-07 / OQ-291-A : five items, item-2/item-3 split preserved ─────────
def test_clause_has_five_items_split_preserved():
    items = re.findall(r"^\s*([1-5])\.\s", CANONICAL_CLAUSE, re.MULTILINE)
    assert items == ["1", "2", "3", "4", "5"], f"expected items 1..5, got {items}"
    # Item 2 = risk-tier thresholds + required sign-offs/reviewer set.
    assert "Risk-tier thresholds" in CANONICAL_CLAUSE
    # Item 3 = reviewer independence / cross-vendor second review — distinct from item 2.
    assert "Reviewer independence" in CANONICAL_CLAUSE
    assert "cross-vendor" in CANONICAL_CLAUSE


# ── AC-291-03 : clause lives in the CORE region, not PROJECT / PACK ──────────
def test_clause_inside_core_region():
    offenders = []
    for p in _core_region_files():
        text = p.read_text(encoding="utf-8")
        anchor_at = text.find(ANCHOR)
        core_start = text.find(CORE_START)
        core_end = text.find(CORE_END)
        if not (core_start < anchor_at < core_end):
            offenders.append((p.name, "anchor outside CORE region"))
            continue
        # Anchor must not also appear in the PROJECT region.
        proj_start = text.find(PROJECT_START)
        if proj_start != -1 and ANCHOR in text[proj_start:]:
            offenders.append((p.name, "anchor present in PROJECT region"))
    assert not offenders, f"clause-location violations: {offenders}"


# ── AC-291-02 : no file retains the old unconditional clause ─────────────────
def test_no_unconditional_clause_remains():
    offenders = [p.name for p in AGENTS_DIR.glob("*.md")
                 if OLD_UNCONDITIONAL in p.read_text(encoding="utf-8")]
    assert not offenders, f"old unconditional 'PROJECT governs' clause still present in: {offenders}"


# ── AC-291-05 : validator §6 predicate rejects the old unconditional form ────
def test_validator_rejects_old_unconditional_clause():
    # A CORE-region file with the old unconditional clause but no anchor must FAIL §6.
    old_form = (
        f"{CORE_START}\n"
        "You are some agent.\n"
        "Where the PROJECT section below conflicts with anything above, PROJECT governs.\n"
        f"{CORE_END}\n"
    )
    assert _section_six_predicate(old_form) is False, "§6 must reject the old unconditional clause"
    # The canonical clause must PASS §6.
    good_form = f"{CORE_START}\n{CANONICAL_CLAUSE}\n{CORE_END}\n"
    assert _section_six_predicate(good_form) is True, "§6 must accept the canonical clause"
    # A non-layered file (no CORE region) is out of scope and must PASS (skip).
    assert _section_six_predicate("just an unlayered oversight agent, no markers") is True
