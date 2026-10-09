"""Parity test: the HOS:HUMAN-PROXY block in CLAUDE.md must be byte-identical to
the block in templates/CLAUDE.human.md modulo the __CLONE_ROOT__ placeholder
(ADR-1934 AD-6). The template is the source; there is deliberately no
exemption list. HOS-only text belongs outside the markers.
"""

import difflib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
TEMPLATE = REPO / "templates" / "CLAUDE.human.md"

START = "<!-- HOS:HUMAN-PROXY start -->"
END = "<!-- HOS:HUMAN-PROXY end -->"
PLACEHOLDER = "__CLONE_ROOT__"
_CLONE_ROOT_RE = re.compile(r"running in the Human\s+clone at `([^`]+)`")


def extract_block(text: str) -> str:
    """Return the text from the start marker through the end marker, inclusive."""
    return text[text.index(START) : text.index(END) + len(END)]


def clone_root(claude_md_text: str) -> str:
    match = _CLONE_ROOT_RE.search(extract_block(claude_md_text))
    assert match, "clone-root sentence not found in the CLAUDE.md block"
    return match.group(1)


def compare_blocks(claude_block: str, template_block: str, root: str) -> str:
    """Return '' when the blocks match after substitution, else a unified diff."""
    expected = template_block.replace(PLACEHOLDER, root)
    if claude_block == expected:
        return ""
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            claude_block.splitlines(keepends=True),
            fromfile="templates/CLAUDE.human.md (substituted)",
            tofile="CLAUDE.md",
        )
    )


@pytest.fixture(scope="module")
def texts():
    return CLAUDE_MD.read_text(encoding="utf-8"), TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("marker", [START, END])
@pytest.mark.parametrize("path", [CLAUDE_MD, TEMPLATE], ids=lambda p: p.name)
def test_marker_occurs_exactly_once(path, marker):
    assert path.read_text(encoding="utf-8").count(marker) == 1


@pytest.mark.parametrize("path", [CLAUDE_MD, TEMPLATE], ids=lambda p: p.name)
def test_start_precedes_end(path):
    text = path.read_text(encoding="utf-8")
    assert text.index(START) < text.index(END)


def test_template_uses_placeholder(texts):
    assert PLACEHOLDER in extract_block(texts[1])


def test_blocks_are_identical_after_substitution(texts):
    claude_text, template_text = texts
    diff = compare_blocks(
        extract_block(claude_text), extract_block(template_text), clone_root(claude_text)
    )
    assert diff == "", "HUMAN-PROXY block drift:\n" + diff


def test_one_character_drift_is_reported(texts):
    claude_text, template_text = texts
    block = extract_block(claude_text)
    drifted = block.replace("orchestrate", "orchestrata", 1)
    assert drifted != block
    diff = compare_blocks(drifted, extract_block(template_text), clone_root(claude_text))
    assert diff != ""
    assert "orchestrata" in diff
