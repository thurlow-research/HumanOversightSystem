"""JS/TS/Astro routing in `run_validators.sh` (#1034, epic #1029 S1).

Before S1 every Python validator was gated on `PY_FILES`, so an all-`.astro`/
`.ts`/`.js` changeset left 8 of 12 scoring dimensions dark and the composite risk
signal was mostly noise. S1 adds a parallel `JS_FILES` lane that routes those
files to `*_js.py` validators (landing in S4–S9).

These tests pin the routing itself — which files reach which lane, and that a
JS-only changeset still completes cleanly while most `*_js.py` scripts do not yet
exist (each is SKIPped, not fatal, so S1 ships green ahead of S4–S9;
`complexity_metrics_js.py` landed in S4 and is dispatched for real).

The Python-side non-regression guard is `test_run_validators_byte_identical.py`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.oversight.run_validators_harness import (
    OUT_REL,
    commit_files,
    filelist_split,
    hermetic_run,
    init_repo,
    install_node_tool_stub,
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)

# The seven extensions ADR-032 routes to the JS lane.
_JS_EXTS = ("ts", "tsx", "js", "jsx", "astro", "mjs", "cjs")


def test_all_seven_js_extensions_route_to_js_files(tmp_path: Path):
    init_repo(tmp_path)
    files = {f"src/app.{ext}": f"// {ext}\n" for ext in _JS_EXTS}
    commit_files(tmp_path, files, subject="add js sources")

    split = filelist_split(tmp_path, "--diff", "HEAD~1")

    assert sorted(split["JS_FILES"]) == sorted(files)
    assert split["PY_FILES"] == []
    assert sorted(split["ALL_FILES"]) == sorted(files)


def test_mixed_diff_splits_lanes_without_disturbing_py_files(tmp_path: Path):
    """A mixed changeset feeds both lanes; neither steals from the other."""
    init_repo(tmp_path)
    commit_files(
        tmp_path,
        {
            "pkg/mod.py": "x = 1\n",
            "src/page.astro": "---\n---\n<p>hi</p>\n",
            "src/lib.ts": "export const a = 1;\n",
            "package.json": "{}\n",
            "README.md": "docs\n",
        },
        subject="mixed changeset",
    )

    split = filelist_split(tmp_path, "--diff", "HEAD~1")

    assert split["PY_FILES"] == ["pkg/mod.py"]
    assert sorted(split["JS_FILES"]) == ["src/lib.ts", "src/page.astro"]
    # Manifests and docs stay in ALL_FILES only — package.json is NOT a JS source.
    assert "package.json" in split["ALL_FILES"]
    assert "package.json" not in split["JS_FILES"]
    assert "README.md" not in split["JS_FILES"]
    assert "pkg/mod.py" not in split["JS_FILES"]


def test_non_js_and_uppercase_extensions_stay_out_of_js_files(tmp_path: Path):
    """Lowercase-only match (DQ-1), and near-miss extensions must not route."""
    init_repo(tmp_path)
    commit_files(
        tmp_path,
        {
            "src/App.TS": "// upper\n",
            "src/style.css": "a{}\n",
            "src/data.json": "{}\n",
            "notes.jsx.md": "# not jsx\n",
        },
        subject="near misses",
    )

    split = filelist_split(tmp_path, "--diff", "HEAD~1")

    assert split["JS_FILES"] == []


def test_deleted_js_file_is_not_routed(tmp_path: Path):
    """`-f` existence check: a deleted path reaches ALL_FILES but not JS_FILES."""
    init_repo(tmp_path)
    commit_files(tmp_path, {"src/gone.ts": "export const x = 1;\n"}, subject="add ts")
    (tmp_path / "src" / "gone.ts").unlink()
    import subprocess

    subprocess.run(
        ["git", "commit", "-q", "-am", "delete ts"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    split = filelist_split(tmp_path, "--diff", "HEAD~1")

    assert "src/gone.ts" in split["ALL_FILES"]
    assert split["JS_FILES"] == []


def test_js_only_run_exits_zero_and_is_not_critical(tmp_path: Path):
    """JS-only changeset with the full S4-S9 `*_js.py` set must not fail closed.

    All six JS validators (S4-S9) now exist, so the dispatch block is fully
    live: the run still exits 0 and the composite stays out of the
    fail-closed CRITICAL branch.
    """
    init_repo(tmp_path)
    commit_files(
        tmp_path,
        {"src/page.astro": "---\n---\n<p>hi</p>\n", "src/lib.ts": "export const a = 1;\n"},
        subject="astro page",
    )
    # The .astro file is itself an astro/astro-check tool marker (S2, ADR-032
    # D1) — stub both so the new tool preflight passes and this test keeps
    # exercising JS *validator* routing/dispatch, not tool availability.
    install_node_tool_stub(tmp_path, "astro")
    install_node_tool_stub(tmp_path, "astro-check")

    proc = hermetic_run(tmp_path, "src/page.astro", "src/lib.ts")

    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"
    summary = json.loads((tmp_path / OUT_REL / "summary.json").read_text())
    assert summary["tier"] != "CRITICAL"
    assert summary["successful_validators"] > 0
    assert "error" not in summary
    assert (tmp_path / OUT_REL / "complexity_js.json").exists()
    assert (tmp_path / OUT_REL / "function_metrics_js.json").exists()
    assert (tmp_path / OUT_REL / "n1_queries_js.json").exists()


def test_js_only_run_ungates_prompt_ambiguity(tmp_path: Path):
    """S1.4: the stack-neutral prompt dimension now scores on a JS-only diff.

    Pre-S1 this dimension was gated on `PY_FILES`, so it went dark exactly when a
    JS changeset most needed prompt-provenance signal.
    """
    init_repo(tmp_path)
    commit_files(tmp_path, {"src/lib.ts": "export const a = 1;\n"}, subject="ts only")

    proc = hermetic_run(tmp_path, "src/lib.ts")

    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"
    result = json.loads((tmp_path / OUT_REL / "prompt_ambiguity.json").read_text())
    assert result["dimension"] == "prompt_ambiguity"
    assert result.get("error") is None
    # portability stays Python-gated until S19 — it is stack-specific.
    assert not (tmp_path / OUT_REL / "portability.json").exists()


def test_js_dispatch_targets_the_expected_js_validators(tmp_path: Path):
    """The six JS dimensions must be attempted (and reported) by name."""
    init_repo(tmp_path)
    commit_files(tmp_path, {"src/lib.ts": "export const a = 1;\n"}, subject="ts only")

    proc = hermetic_run(tmp_path, "src/lib.ts")

    for name in (
        "risk_number_js",
        "complexity_js",
        "function_metrics_js",
        "n1_queries_js",
        "static_analysis_js",
        "hallucination_js",
    ):
        assert name in proc.stdout, f"{name} was not dispatched:\n{proc.stdout}"
