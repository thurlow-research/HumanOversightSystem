"""The temp-location rules block must be identical in its three homes (#2054, TD 8.6, P1-P5).

contract/OVERSIGHT-CONTRACT.md section 1 is the normative source; CLAUDE.md and AGENTS.md
carry byte-identical copies between non-"HOS:" markers (so the installer's region parser
never mistakes them for a region). docs/SANDBOX-POLICY.md only cross-references.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOMES = ("contract/OVERSIGHT-CONTRACT.md", "CLAUDE.md", "AGENTS.md")
BLOCK_RE = re.compile(r"<!-- TEMP-RULES:BEGIN.*?<!-- TEMP-RULES:END -->", re.S)


def _blocks(rel: str) -> list[str]:
    return BLOCK_RE.findall((ROOT / rel).read_text())


def _norm(block: str) -> str:
    return "\n".join(ln.rstrip() for ln in block.strip().splitlines())


def test_p1_each_home_has_exactly_one_identical_block():
    found = {}
    for rel in HOMES:
        blocks = _blocks(rel)
        assert len(blocks) == 1, f"{rel} must contain exactly one TEMP-RULES block"
        assert (ROOT / rel).read_text().count("TEMP-RULES:BEGIN") == 1
        found[rel] = _norm(blocks[0])
    assert len(set(found.values())) == 1, "the three TEMP-RULES blocks differ"


def test_p2_block_carries_the_required_tokens_and_four_rules():
    block = _blocks(HOMES[0])[0]
    for token in (
        "$TMPDIR",
        "$HOS_TMP_ROOT/<RoleDir>",
        ".claudetmp/",
        "never reaped",
        "/tmp/claude/",
        "24 h",
    ):
        assert token in block, token
    assert [ln[:2] for ln in block.splitlines() if re.match(r"^\d\. ", ln)] == [
        "1.",
        "2.",
        "3.",
        "4.",
    ]


def test_p3_sandbox_policy_cross_references_without_a_fourth_copy():
    text = (ROOT / "docs" / "SANDBOX-POLICY.md").read_text()
    assert "Temp and working-state locations" in text and "OVERSIGHT-CONTRACT.md" in text
    assert "TEMP-RULES:BEGIN" not in text


def test_p4_claudetmp_is_no_longer_called_ephemeral():
    contract = (ROOT / HOMES[0]).read_text()
    tree_line = next(ln for ln in contract.splitlines() if ln.startswith(".claudetmp/"))
    assert "ephemeral" not in tree_line and "never reaped" in tree_line
    for rel in ("CLAUDE.md", HOMES[2]):
        for ln in (ROOT / rel).read_text().splitlines():
            assert not (".claudetmp/" in ln and "ephemeral" in ln), (rel, ln)
    claude = (ROOT / "CLAUDE.md").read_text()
    assert ".claudetmp/` is ephemeral" not in re.sub(r"\s+", " ", claude)


def test_p5_no_marker_starts_with_the_installer_region_prefix():
    for rel in HOMES:
        for marker in re.findall(r"<!--\s*([A-Za-z0-9_:-]+)", "\n".join(_blocks(rel))):
            assert not marker.startswith("HOS:"), (rel, marker)
