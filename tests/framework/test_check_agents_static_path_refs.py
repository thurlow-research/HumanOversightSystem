"""End-to-end test for the shell-side consumption of path-ref cleaning (#1846).

#1846 fixed a drift bug: `scripts/framework/check_agents_static.sh` section 3
used to re-derive path-reference cleaning inline
(ref_clean=$(echo "$ref" | tr -d '`"' | sed 's/#.*//' | xargs)), which
disagreed with the Python `_clean_ref` classification logic on multi-word
references such as `` `script.sh subcommand` `` — `xargs` collapses the
reference into a single space-joined word instead of taking only the first
shell word, so the existence check ran against the literal two-word string
"script.sh subcommand" rather than the path "script.sh" alone.

The fix made `scripts/oversight/agents_static_logic.py`'s `clean-path-ref`
subcommand the single source of truth; the shell now only consumes its output
(`ref_clean=$(python3 "$LOGIC_PY" clean-path-ref "$ref")`).

Unit tests for `_clean_ref` / the `clean-path-ref` CLI subcommand already
cover the Python side in isolation, but they do not exercise
check_agents_static.sh itself, so they would not catch a regression in the
*shell's consumption* of that output (the actual site of the original bug —
e.g. a future edit reverting the shell line back to the old `xargs` pipeline
while leaving the Python subcommand untouched). This file closes that gap by
running the checker end-to-end (mirrors
tests/framework/test_check_agents_static_dated_model_ids.py's scaffold
pattern) against a fixture agent file with a two-word backticked path
reference (`` `script.sh subcommand` ``), asserting both that a present script
passes and that an absent script's FAIL line names the script path alone, not
the two-word reference.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "framework" / "check_agents_static.sh"
LOGIC = ROOT / "scripts" / "oversight" / "agents_static_logic.py"

AGENT_TEXT_TEMPLATE = (
    "---\nname: fake-agent\ndescription: test fixture\nmodel: sonnet\n---\n\n"
    "Run `scripts/framework/other_tool.sh run-check` before merging.\n"
)


def _scaffold(tmp_path: Path) -> Path:
    """Build the minimal directory layout check_agents_static.sh needs to run
    cleanly: itself, its Python logic dependency, and one agent file whose
    single path reference is the two-word `script.sh subcommand` form that
    pins #1846's cleaning behaviour."""
    (tmp_path / "scripts" / "framework").mkdir(parents=True)
    shutil.copy(CHECKER, tmp_path / "scripts" / "framework" / CHECKER.name)
    (tmp_path / "scripts" / "oversight").mkdir(parents=True)
    shutil.copy(LOGIC, tmp_path / "scripts" / "oversight" / LOGIC.name)

    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "fake-agent.md").write_text(AGENT_TEXT_TEMPLATE)
    return tmp_path


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/framework/check_agents_static.sh", "--quiet"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_two_word_reference_to_existing_script_passes(tmp_path):
    """`script.sh subcommand` where script.sh EXISTS: no FAIL naming it."""
    _scaffold(tmp_path)
    (tmp_path / "scripts" / "framework" / "other_tool.sh").write_text(
        "#!/usr/bin/env bash\necho ok\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "referenced path not found" not in result.stdout


def test_two_word_reference_to_missing_script_names_script_path_only(tmp_path):
    """`script.sh subcommand` where script.sh is ABSENT: the FAIL line names
    the script path alone ("scripts/framework/other_tool.sh"), never the raw
    two-word reference ("scripts/framework/other_tool.sh run-check"). This
    pins the cleaning behaviour precisely: it fails if cleaning reverts to the
    old `xargs`-based collapse (which would leave the two-word string in the
    FAIL line) and it would equally fail if cleaning were changed to strip
    too much (e.g. dropping the extension)."""
    _scaffold(tmp_path)
    # Deliberately do NOT create scripts/framework/other_tool.sh.
    result = _run(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    fail_lines = [
        line for line in result.stdout.splitlines() if "referenced path not found" in line
    ]
    assert fail_lines, result.stdout + result.stderr
    assert any(line.endswith("scripts/framework/other_tool.sh") for line in fail_lines), fail_lines
    assert not any(
        "scripts/framework/other_tool.sh run-check" in line for line in fail_lines
    ), fail_lines
