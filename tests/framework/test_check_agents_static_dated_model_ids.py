"""Tests for the dated-model-generation-ID guard in check_agents_static.sh (#1366).

Model references must use class aliases (`opus` / `sonnet` / `haiku`), never a
dated generation ID (`claude-<class>-<n>-<n>`, e.g. `claude-opus-4-8`) — a
dated pin goes stale the moment the model generation moves on and nothing
notices (this already caused a live failure once, fixed under #1362).

Section 9 of check_agents_static.sh greps agent frontmatter, scripts/,
bootstrap/, bin/, and markdown documentation repo-wide for the dated-ID
pattern, while exempting point-in-time records (versioned docs, release
notes, specs, research write-ups, decision logs, the audit trail, prompt
artifacts, ephemeral working state).

Each test copies only the script's own dependencies into an isolated tmp_path
layout (mirrors tests/framework/test_codeowners_current.py) so it never
touches the real repo tree.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "framework" / "check_agents_static.sh"
LOGIC = ROOT / "scripts" / "oversight" / "agents_static_logic.py"


def _scaffold(tmp_path: Path) -> Path:
    """Build the minimal directory layout check_agents_static.sh needs to run
    cleanly: itself, its Python logic dependency, and one valid agent file."""
    (tmp_path / "scripts" / "framework").mkdir(parents=True)
    shutil.copy(CHECKER, tmp_path / "scripts" / "framework" / CHECKER.name)
    (tmp_path / "scripts" / "oversight").mkdir(parents=True)
    shutil.copy(LOGIC, tmp_path / "scripts" / "oversight" / LOGIC.name)

    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "fake-agent.md").write_text(
        "---\nname: fake-agent\ndescription: test fixture\nmodel: sonnet\n---\n\n"
        "You are a test fixture agent.\n"
    )
    return tmp_path


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/framework/check_agents_static.sh", "--quiet"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_clean_repo_passes(tmp_path):
    """A repo with only class-alias model references passes section 9."""
    _scaffold(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dated model generation ID" not in result.stdout


def test_dated_id_in_agent_frontmatter_fails(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / ".claude" / "agents" / "fake-agent.md").write_text(
        "---\nname: fake-agent\ndescription: test fixture\n"
        "model: claude-opus-4-8\n---\n\nYou are a test fixture agent.\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "dated model generation ID" in result.stdout
    assert "fake-agent.md" in result.stdout


def test_dated_id_in_script_fails(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "scripts" / "other_tool.sh").write_text(
        '#!/usr/bin/env bash\nMODEL="claude-sonnet-4-6"\n'
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "dated model generation ID" in result.stdout
    assert "other_tool.sh" in result.stdout


def test_dated_id_in_bootstrap_fails(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "setup.sh").write_text(
        '#!/usr/bin/env bash\nMODEL="claude-haiku-4-5-20251001"\n'
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "dated model generation ID" in result.stdout
    assert "setup.sh" in result.stdout


def test_dated_id_in_bin_fails(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "hos-thing").write_text(
        '#!/usr/bin/env bash\n# uses claude-opus-4-8 for review\n'
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "dated model generation ID" in result.stdout


def test_dated_id_in_current_docs_fails(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "AGENTS.md").write_text(
        "# Agents\n\n**Model:** `claude-sonnet-4-6`\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "dated model generation ID" in result.stdout
    assert "docs/AGENTS.md" in result.stdout


def test_current_alias_model_id_does_not_false_positive(tmp_path):
    """The actual current runtime model ID (single version segment, e.g.
    claude-sonnet-5) must not be flagged — only the old two-segment dated
    format (claude-<class>-<n>-<n>) is the forbidden pattern."""
    _scaffold(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "NOTES.md").write_text(
        "The AI-Model trailer should read `claude-sonnet-5`, the actual "
        "running model ID.\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dated model generation ID" not in result.stdout


@pytest.mark.parametrize(
    "relpath",
    [
        "docs/v0.6.0/ADR-999-example.md",
        "docs/releases/v9.9.9.md",
        "docs/specs/TECHNICAL-DESIGN-999-example.md",
        "research/findings/example.md",
        "audit/2026-01-01.md",
        ".claudetmp/scratch.md",
        "prompts/example.md",
        "DECISIONS.md",
        "scripts/framework/decisions.md",
    ],
)
def test_point_in_time_records_are_exempt(tmp_path, relpath):
    _scaffold(tmp_path)
    target = tmp_path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Historical record. Model at the time: `claude-opus-4-8`.\n")
    result = _run(tmp_path)
    assert result.returncode == 0, (
        f"{relpath} should be exempt but guard failed:\n" + result.stdout + result.stderr
    )
    assert "dated model generation ID" not in result.stdout
