"""Tests for brownfield.py — consumer-pack brownfield classifier (#275).

Covers:
- similarity algorithm (max denominator, not union denominator)
- STOCK_CORE / PROJECT_CUSTOMIZATION / mixed classification thresholds
- Frontmatter exclusion (REQ-D-09)
- Heading-less flat file fallback (O-2)
- No-CORE-template case (REQ-D-08)
- Section matching (REQ-D-01)
- Result dict shape (REQ-D-07 superset + task-brief buckets)
"""
import sys
from pathlib import Path
import importlib.util

# Load brownfield.py directly (venv-less, consistent with how the installer calls it)
_BF_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "validators"
    / "brownfield.py"
)
_spec = importlib.util.spec_from_file_location("brownfield", _BF_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

brownfield_classify = _mod.brownfield_classify
_strip_frontmatter = _mod._strip_frontmatter
_split_sections = _mod._split_sections
_section_similarity = _mod._section_similarity
_classify_similarity = _mod._classify_similarity
_brownfield_detect = _mod._brownfield_detect


# ── Helper: write temp files ───────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── _section_similarity: max denominator, not union ───────────────────────────

def test_similarity_identical_content():
    lines = ["line A\n", "line B\n", "line C\n"]
    assert _section_similarity(lines, lines) == 1.0


def test_similarity_no_overlap():
    a = ["only in A\n"]
    b = ["only in B\n"]
    # common=0, max(1,1)=1 → 0.0
    assert _section_similarity(a, b) == 0.0


def test_similarity_max_denominator_vs_union():
    # Consumer has 4 lines, core has 2 lines, 2 in common.
    # max(4, 2) = 4 → 2/4 = 0.5
    # union would be 4 → same here, but with asymmetric overlap they differ.
    consumer = ["A\n", "B\n", "C\n", "D\n"]
    core = ["A\n", "B\n"]
    result = _section_similarity(consumer, core)
    # common=2 (A,B), max(4,2)=4 → 0.5
    assert abs(result - 0.5) < 1e-9


def test_similarity_larger_core():
    # Core larger than consumer: 1 common, max(1,3)=3 → 1/3 ≈ 0.333
    consumer = ["A\n"]
    core = ["A\n", "B\n", "C\n"]
    result = _section_similarity(consumer, core)
    assert abs(result - (1 / 3)) < 1e-9


def test_similarity_empty_lines_ignored():
    # Blank lines dropped before set construction
    consumer = ["A\n", "\n", "  \n", "B\n"]
    core = ["A\n", "B\n"]
    # Both produce {A, B} → common=2, max(2,2)=2 → 1.0
    assert _section_similarity(consumer, core) == 1.0


def test_similarity_both_empty_is_zero():
    assert _section_similarity([], []) == 0.0


def test_similarity_strip_applied():
    # Whitespace-stripped lines must match even with surrounding whitespace
    consumer = ["  line one  \n"]
    core = ["line one\n"]
    assert _section_similarity(consumer, core) == 1.0


# ── Classification thresholds ─────────────────────────────────────────────────

def test_classify_stock_core_at_threshold():
    cls, mixed = _classify_similarity(0.90)
    assert cls == "STOCK_CORE"
    assert mixed is False


def test_classify_stock_core_above_threshold():
    cls, mixed = _classify_similarity(1.0)
    assert cls == "STOCK_CORE"
    assert mixed is False


def test_classify_mixed_lower_bound():
    # 0.45 is mixed
    cls, mixed = _classify_similarity(0.45)
    assert cls == "PROJECT_CUSTOMIZATION"
    assert mixed is True


def test_classify_mixed_upper_exclusive():
    # 0.899 is mixed (< 0.90)
    cls, mixed = _classify_similarity(0.899)
    assert cls == "PROJECT_CUSTOMIZATION"
    assert mixed is True


def test_classify_project_custom_below_mixed():
    # 0.44 → PROJECT_CUSTOMIZATION, not mixed
    cls, mixed = _classify_similarity(0.44)
    assert cls == "PROJECT_CUSTOMIZATION"
    assert mixed is False


def test_classify_zero_similarity():
    cls, mixed = _classify_similarity(0.0)
    assert cls == "PROJECT_CUSTOMIZATION"
    assert mixed is False


# ── Frontmatter exclusion (REQ-D-09) ─────────────────────────────────────────

def test_frontmatter_stripped():
    text = "---\nname: foo\nmodel: bar\n---\n\n## Section\ncontent here\n"
    body = _strip_frontmatter(text)
    assert "name: foo" not in body
    assert "## Section" in body


def test_no_frontmatter_unchanged():
    text = "## Section\ncontent here\n"
    assert _strip_frontmatter(text) == text


def test_frontmatter_not_present_when_no_leading_dashes():
    text = "Some content\n---\nThis is not frontmatter (not leading)\n"
    result = _strip_frontmatter(text)
    assert result == text


def test_frontmatter_excluded_from_classification(tmp_path):
    # An agent file with frontmatter — the frontmatter content must not affect
    # similarity or classification
    agent_text = "---\nname: test-agent\nmodel: claude\n---\n\n## Section\nsome unique content\n"
    core_text = "---\nname: test-agent\nmodel: claude\n---\n\n## Section\ncompletely different words\n"
    agent_file = _write(tmp_path, "agent.md", agent_text)
    core_file = _write(tmp_path, "core.md", core_text)
    result = brownfield_classify(agent_file, core_file)
    # Only the body content is compared, not the frontmatter
    # "some unique content" vs "completely different words" → similarity 0.0 → PROJECT
    assert any(
        s["classification"] == "PROJECT_CUSTOMIZATION"
        for s in result["sections"]
        if s["heading"].lower() == "section"
    )


# ── brownfield_classify: result shape ────────────────────────────────────────

def test_result_has_required_keys(tmp_path):
    agent = _write(tmp_path, "myagent.md", "## Intro\nhello world\n")
    core = _write(tmp_path, "core.md", "## Intro\nhello world\n")
    r = brownfield_classify(agent, core)
    assert "agent" in r
    assert "core_template" in r
    assert "similarity" in r
    assert "sections" in r
    assert "stock_core" in r
    assert "project_custom" in r
    assert "mixed" in r


def test_result_agent_name(tmp_path):
    agent = _write(tmp_path, "code-reviewer.md", "## Intro\nfoo\n")
    core = _write(tmp_path, "core.md", "## Intro\nfoo\n")
    r = brownfield_classify(agent, core)
    assert r["agent"] == "code-reviewer.md"


def test_identical_content_is_stock_core(tmp_path):
    content = "## Role\nYou review code carefully.\n\n## Process\nStep 1.\nStep 2.\n"
    agent = _write(tmp_path, "reviewer.md", content)
    core = _write(tmp_path, "core-reviewer.md", content)
    r = brownfield_classify(agent, core)
    # All sections identical → all STOCK_CORE
    assert all(s["classification"] == "STOCK_CORE" for s in r["sections"])
    assert r["similarity"] == 1.0


def test_completely_different_is_project_custom(tmp_path):
    agent_text = "## MySection\nunique consumer content A B C D E\n"
    core_text = "## OtherSection\ncompletely unrelated X Y Z W V\n"
    agent = _write(tmp_path, "a.md", agent_text)
    core = _write(tmp_path, "c.md", core_text)
    r = brownfield_classify(agent, core)
    # No heading match → PROJECT_CUSTOMIZATION
    assert all(s["classification"] == "PROJECT_CUSTOMIZATION" for s in r["sections"])


def test_mixed_section_flagged(tmp_path):
    # Build a case where similarity is in [0.45, 0.90)
    # Consumer has 10 lines, core has 10 lines, 6 in common → 6/10 = 0.6 → mixed
    consumer_lines = "\n".join([f"line{i}" for i in range(10)])
    core_lines = "\n".join([f"line{i}" for i in range(6)] + [f"extra{i}" for i in range(4)])
    agent_text = f"## Process\n{consumer_lines}\n"
    core_text = f"## Process\n{core_lines}\n"
    agent = _write(tmp_path, "a.md", agent_text)
    core = _write(tmp_path, "c.md", core_text)
    r = brownfield_classify(agent, core)
    process_sections = [s for s in r["sections"] if s["heading"].lower() == "process"]
    assert len(process_sections) == 1
    s = process_sections[0]
    assert s["classification"] == "PROJECT_CUSTOMIZATION"
    assert s["mixed"] is True
    assert s["heading"] in r["mixed"]


def test_stock_core_in_bucket(tmp_path):
    content = "## Role\n" + "\n".join([f"word{i}" for i in range(20)]) + "\n"
    agent = _write(tmp_path, "a.md", content)
    core = _write(tmp_path, "c.md", content)
    r = brownfield_classify(agent, core)
    assert "Role" in r["stock_core"]
    assert "Role" not in r["project_custom"]
    assert "Role" not in r["mixed"]


# ── No-CORE-template case (REQ-D-08) ─────────────────────────────────────────

def test_no_core_template_all_project_custom(tmp_path):
    agent_text = "## Custom\nsome project-specific content\n"
    agent = _write(tmp_path, "custom-agent.md", agent_text)
    r = brownfield_classify(agent, None)
    assert r["core_template"] is False
    assert all(s["classification"] == "PROJECT_CUSTOMIZATION" for s in r["sections"])
    assert all(s["similarity"] == 0.0 for s in r["sections"])
    assert all(s["mixed"] is False for s in r["sections"])


def test_no_core_template_similarity_zero(tmp_path):
    agent = _write(tmp_path, "a.md", "## Intro\nfoo bar baz\n")
    r = brownfield_classify(agent, None)
    assert r["similarity"] == 0.0


# ── Heading-less fallback (O-2, spec §2.3) ────────────────────────────────────

def test_headingless_file_treated_as_one_section(tmp_path):
    agent_text = "This is some flat content.\nNo headings here.\n"
    core_text = "This is some flat content.\nNo headings here.\n"
    agent = _write(tmp_path, "a.md", agent_text)
    core = _write(tmp_path, "c.md", core_text)
    r = brownfield_classify(agent, core)
    assert len(r["sections"]) == 1
    assert r["sections"][0]["heading"] == ""


def test_headingless_identical_is_stock_core(tmp_path):
    content = "identical content here across both files\n"
    agent = _write(tmp_path, "a.md", content)
    core = _write(tmp_path, "c.md", content)
    r = brownfield_classify(agent, core)
    assert r["sections"][0]["classification"] == "STOCK_CORE"
    assert r["similarity"] == 1.0


def test_headingless_no_core_is_project_custom(tmp_path):
    agent = _write(tmp_path, "a.md", "flat file content\n")
    r = brownfield_classify(agent, None)
    assert r["sections"][0]["classification"] == "PROJECT_CUSTOMIZATION"


# ── _brownfield_detect ────────────────────────────────────────────────────────

def test_detect_true_when_flat_agents_no_manifest(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "some-agent.md").write_text("flat content no markers\n")
    assert _brownfield_detect(str(tmp_path)) is True


def test_detect_false_when_manifest_present(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "some-agent.md").write_text("flat content\n")
    (tmp_path / ".hos-manifest").write_text("# hos-manifest-schema: 2\n")
    assert _brownfield_detect(str(tmp_path)) is False


def test_detect_false_when_all_agents_marked(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "marked.md").write_text(
        "<!-- HOS:CORE:START -->\ncontent\n<!-- HOS:CORE:END -->\n"
        "<!-- HOS:PROJECT:START -->\n<!-- HOS:PROJECT:END -->\n"
    )
    assert _brownfield_detect(str(tmp_path)) is False


def test_detect_false_when_no_agents(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    assert _brownfield_detect(str(tmp_path)) is False


def test_detect_false_when_no_agents_dir(tmp_path):
    assert _brownfield_detect(str(tmp_path)) is False


# ── Multi-section agent ───────────────────────────────────────────────────────

def test_multi_section_mixed_classifications(tmp_path):
    # Section A: identical → STOCK_CORE
    # Section B: completely different → PROJECT_CUSTOMIZATION (no match in core)
    agent_text = (
        "## Introduction\n"
        "This is the introduction content that will match core.\n"
        "\n"
        "## MyCustomSection\n"
        "This is unique project content not in the core template.\n"
    )
    core_text = (
        "## Introduction\n"
        "This is the introduction content that will match core.\n"
    )
    agent = _write(tmp_path, "a.md", agent_text)
    core = _write(tmp_path, "c.md", core_text)
    r = brownfield_classify(agent, core)

    sections_by_heading = {s["heading"].lower(): s for s in r["sections"]}
    assert sections_by_heading["introduction"]["classification"] == "STOCK_CORE"
    assert sections_by_heading["mycustomsection"]["classification"] == "PROJECT_CUSTOMIZATION"
    assert "Introduction" in r["stock_core"]
    assert "MyCustomSection" in r["project_custom"]


def test_section_lines_preserved_in_result(tmp_path):
    agent_text = "## Intro\nline one\nline two\n"
    core_text = "## Intro\ndifferent content entirely\n"
    agent = _write(tmp_path, "a.md", agent_text)
    core = _write(tmp_path, "c.md", core_text)
    r = brownfield_classify(agent, core)
    intro_sections = [s for s in r["sections"] if s["heading"].lower() == "intro"]
    assert len(intro_sections) == 1
    # Lines must include the original section body
    all_lines = "".join(intro_sections[0]["lines"])
    assert "line one" in all_lines or "Intro" in all_lines
