"""
Tests for scripts/framework/run_post_change_sweep.sh — the explain-only sweep
(ADR-1643 Amendment F, TD-D50..TD-D53): T5.30, T5.31, T5.48, T5.65..T5.68.

Each test stages a consumer-shaped tree (W5b's `stage()`), copies in the
registry CLI and the sweep, makes a git commit 0, and shells out to bash.
Not slow-marked.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest
import yaml

from scripts.automation import dimension_registry_cli as cli
from tests.automation.test_dimension_registry_data import REPO_ROOT, stage
from tests.tmp_hygiene import child_env

SWEEP_REL = "scripts/framework/run_post_change_sweep.sh"
SWEEP_SRC = (REPO_ROOT / SWEEP_REL).read_text(encoding="utf-8")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
_COPIES = (
    "scripts/__init__.py",
    "scripts/automation/__init__.py",
    "scripts/automation/lib/__init__.py",
    "scripts/automation/lib/dimension_registry.py",
    "scripts/automation/lib/posture.py",
    "scripts/automation/dimension_registry_cli.py",
    SWEEP_REL,
)


def git(tree: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
        check=True,
    )
    return proc.stdout


def stage_tree(
    tmp: Path,
    packs: list[str],
    project_text: str | None,
    prep: Callable[[Path], None] | None = None,
) -> Path:
    stage(tmp, packs, project_text)
    for rel in _COPIES:
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dest)
    (tmp / SWEEP_REL).chmod(0o755)
    if prep is not None:
        prep(tmp)
    return tmp


def sweep_tree(
    tmp: Path,
    packs: list[str],
    project_text: str | None = None,
    prep: Callable[[Path], None] | None = None,
) -> Path:
    stage_tree(tmp, packs, project_text, prep)
    git(tmp, "init", "-q")
    git(tmp, "add", "-A")
    git(tmp, "commit", "-q", "-m", "commit 0")
    return tmp


def run(
    tree: Path,
    *args: str,
    env: dict[str, str] | None = None,
    python: str | None = sys.executable,
    path: str | None = None,
) -> subprocess.CompletedProcess:
    full = {**os.environ, **_GIT_ENV, "GIT_CEILING_DIRECTORIES": str(tree.parent)}
    full.pop("HOS_REGISTRY_PYTHON", None)
    if python is not None:
        full["HOS_REGISTRY_PYTHON"] = python
    if path is not None:
        full["PATH"] = path
    full.update(env or {})
    return subprocess.run(
        ["/bin/bash", str(tree / SWEEP_REL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(tree),
        env=child_env(full),
        check=False,
    )


def cli_plan_stdout(tree: Path, files: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["plan", *(f"--changed-file={f}" for f in files)], repo_root=tree)
    assert rc == 0
    return buf.getvalue()


def commit_file(tree: Path, name: str, text: str = "x = 1\n") -> None:
    (tree / name).write_text(text, encoding="utf-8")
    git(tree, "add", "--", name)
    git(tree, "commit", "-q", "-m", f"add {name}")


def changed(tree: Path, *args: str) -> list[str]:
    proc = run(tree, "--json", *args)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["changed_files"]


def git_names(tree: Path, *args: str) -> list[str]:
    return sorted(git(tree, "diff", "--name-only", *args).split())


def remove_core(tree: Path) -> None:
    (tree / "contract" / "dimensions" / "core.yaml").unlink()


# ── T5.30 / T5.31 ────────────────────────────────────────────────────────────


def test_t5_30_json_is_the_cli_plan_stdout(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    files = ["myapp/views.py", "templates/base.html", "README.md"]
    proc = run(tree, "--json", *files)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == cli_plan_stdout(tree, files)


def test_t5_31_text_output_has_no_agent_plan_and_source_has_no_categorize(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    proc = run(tree, "myapp/views.py", "templates/base.html", "README.md")
    assert proc.returncode == 0, proc.stderr
    for banned in (
        "invoke the post-change-sweep agent",
        "check if PII-relevant",
        "Track ",
        "To run:",
        "Agents to invoke",
    ):
        assert banned not in proc.stdout
    assert "categorize" not in SWEEP_SRC


# ── T5.48 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def history(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    commit_file(tree, "a.py")
    commit_file(tree, "b.py")
    (tree / "c.py").write_text("y = 2\n")
    git(tree, "add", "c.py")
    (tree / "a.py").write_text("x = 99\n")
    return tree


def test_t5_48_explicit_files(history):
    assert changed(history, "x.py", "y.py") == ["x.py", "y.py"]


def test_t5_48_staged(history):
    assert changed(history, "--staged") == git_names(history, "--cached")


def test_t5_48_head_ref(history):
    assert changed(history, "HEAD~1") == git_names(history, "HEAD~1")


def test_t5_48_no_argument(history):
    assert changed(history) == git_names(history, "HEAD")


def test_t5_48_no_argument_after_stash_falls_back_to_head_minus_one(history):
    git(history, "stash", "-u", "-q")
    assert changed(history) == ["b.py"]


def test_t5_48_clean_root_commit_is_empty_set_exit_0(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    proc = run(tree, "--json")
    assert (proc.returncode, proc.stdout) == (0, "[]\n"), proc.stderr
    text = run(tree)
    assert (text.returncode, text.stdout) == (
        0,
        "No changed files — no review dimension applies.\n",
    )


def test_t5_48_explicit_non_ascii_name(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    assert changed(tree, "café.py") == ["café.py"]


def test_t5_48_no_argument_non_ascii_name_is_not_c_quoted(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    commit_file(tree, "café.py")
    (tree / "café.py").write_text("x = 2\n", encoding="utf-8")
    got = changed(tree)
    assert "café.py" in got
    assert not any(p.startswith('"') for p in got)


def test_t5_48_framework_only_and_unknown_flag_exit_2(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    fw = run(tree, "--framework-only")
    assert fw.returncode == 2
    assert fw.stderr == (
        "run_post_change_sweep.sh: --framework-only was removed by ADR-1643 W5 (AD-11); "
        "the plan now comes from the registry\n"
    )
    assert run(tree, "-x").returncode == 2


def test_t5_48_branch_name_is_rejected_with_head_relative_form(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    git(tree, "branch", "feature")
    proc = run(tree, "feature")
    assert proc.returncode == 2
    assert "HEAD-relative" in proc.stderr
    assert proc.stdout == ""


def test_t5_48_untracked_unknown_name_is_a_file(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    proc = run(tree, "nosuch.py")
    assert proc.returncode == 0, proc.stderr


def test_t5_48_empty_set_still_resolves_the_registry(tmp_path):
    tree = sweep_tree(tmp_path, ["django"], prep=remove_core)
    proc = run(tree)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "dimension_registry: core_missing:" in proc.stderr


def test_t5_48_unsafe_project_predicate_exit_1(tmp_path):
    project = (
        "schema: hos.dimension-registry\nschema_version: 1\nowner: project\nbindings:\n"
        "  - id: project:code-review/redos\n    entry: code-review\n    kind: judgment\n"
        "    agent: code-reviewer\n    posture: review-read-only\n    timeout_seconds: 300\n"
        "    prompt_template: contract/dimensions/prompts/code-review.md\n"
        "    predicate:\n      include: ['(a+)+$']\n"
    )
    tree = sweep_tree(tmp_path, ["django"], project_text=project)
    proc = run(tree, "myapp/views.py")
    assert proc.returncode == 1
    assert "unsafe_pattern" in proc.stderr


def test_t5_48_missing_cli_prints_the_vf21_line(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    (tree / "scripts/automation/dimension_registry_cli.py").unlink()
    proc = run(tree, "myapp/views.py")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert (
        "run_post_change_sweep.sh: scripts/automation/dimension_registry_cli.py is not "
        "installed — the registry is not available in this checkout (ADR-1643 TD-VF-21)"
    ) in proc.stderr


def test_t5_48_interpreter_override_not_executable_exit_1(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    proc = run(tree, "myapp/views.py", python="/nonexistent")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_t5_48_no_interpreter_names_ensure_venv(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    bin_dir = tmp_path.parent / (tmp_path.name + "-bin")
    bin_dir.mkdir()
    for tool in ("dirname", "head", "rm", "mktemp", "cat"):
        found = shutil.which(tool)
        assert found
        (bin_dir / tool).symlink_to(found)
    proc = run(tree, "myapp/views.py", python=None, path=str(bin_dir))
    assert proc.returncode == 1
    assert "ensure_venv.sh" in proc.stderr


def test_t5_48_venv_rung_is_used_when_override_is_unset(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    venv_python = tree / "scripts/oversight/.venv/bin/python"
    venv_python.parent.mkdir(parents=True)
    # A wrapper, not a symlink: a symlink outside the venv loses pyvenv.cfg and PyYAML.
    marker = tmp_path / "venv-rung-used.marker"
    venv_python.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec "{sys.executable}" "$@"\n')
    venv_python.chmod(venv_python.stat().st_mode | stat.S_IXUSR)
    proc = run(tree, "myapp/views.py", python=None)
    assert proc.returncode == 0, proc.stderr
    assert marker.exists(), "rung 2 (venv python) was not used"


def test_t5_48_ladder_rungs_match_invoke_agent_in_order():
    invoke = (REPO_ROOT / "bootstrap/invoke_agent.sh").read_text(encoding="utf-8")
    for src, override in ((SWEEP_SRC, "HOS_REGISTRY_PYTHON"), (invoke, "INVOKE_AGENT_PYTHON")):
        i = src.index(override)
        j = src.index("scripts/oversight/.venv/bin/python", i)
        k = src.index("python3", j)
        assert i < j < k


# ── T5.65 ────────────────────────────────────────────────────────────────────


def test_t5_65_sweep_executes_no_allowlisted_tool(tmp_path):
    core = yaml.safe_load((REPO_ROOT / "contract/dimensions/core.yaml").read_text(encoding="utf-8"))
    tools = core["tools"]
    assert "scripts/run_second_review.sh" in tools

    planted: set[str] = set()

    def plant(tree: Path) -> None:
        for rel in tools:
            target = tree / rel
            if not target.exists():
                continue
            name = Path(rel).name
            target.write_text(f'#!/bin/sh\ntouch "{tree}/SENTINEL-{name}"\n')
            target.chmod(0o755)
            planted.add(rel)

    tree = sweep_tree(tmp_path, ["django"], prep=plant)
    assert planted, "no allowlisted tool was planted; the sentinel check would be vacuous"
    assert {"scripts/oversight/gates/lint_check.sh", "scripts/run_second_review.sh"} <= planted
    assert sorted(p.name for p in tree.glob("SENTINEL-*")) == []
    for extra in ((), ("--json",)):
        proc = run(tree, *extra, "myapp/views.py")
        assert proc.returncode == 0, proc.stderr
    plan = json.loads(run(tree, "--json", "myapp/views.py").stdout)["plan"]
    assert any(i["binding"] == "core:lint/all" and i["applicable"] for i in plan)
    assert sorted(p.name for p in tree.glob("SENTINEL-*")) == []
    assert not re.search(r"\beval\b", SWEEP_SRC)


# ── T5.66 ────────────────────────────────────────────────────────────────────


def _installed(tree: Path) -> None:
    import hashlib

    (tree / ".hos-release").write_text("v0.0.0-test\n")
    rels = [
        "contract/dimensions/core.yaml",
        "contract/dimensions/pack-django.yaml",
        "contract/resolved-packs.txt",
    ]
    rows = "".join(
        f"{rel}\tWHOLE\t{hashlib.sha256((tree / rel).read_bytes()).hexdigest()}\n" for rel in rels
    )
    (tree / ".hos-manifest").write_text("# hos-manifest-schema: 2\n" + rows)


def _drift(tree: Path) -> None:
    _installed(tree)
    with (tree / "contract/resolved-packs.txt").open("a") as fh:
        fh.write("# edited\n")


def test_t5_66_installed_drift_fails_on_both_paths_and_no_pack_flag(tmp_path):
    ok = sweep_tree(tmp_path / "ok", ["django"], prep=_installed)
    assert run(ok, "myapp/views.py").returncode == 0

    for sub, args in (("explicit", ("myapp/views.py",)), ("empty", ())):
        tree = sweep_tree(tmp_path / sub, ["django"], prep=_drift)
        proc = run(tree, *args)
        assert proc.returncode == 1, sub
        assert proc.stdout == ""
        assert "dimension_registry: installed_drift:" in proc.stderr
        assert "contract/resolved-packs.txt" in proc.stderr
    assert "--pack" not in SWEEP_SRC


# ── T5.67 ────────────────────────────────────────────────────────────────────


def test_t5_67_no_git_tree_fails_closed(tmp_path):
    tree = stage_tree(tmp_path, ["django"], None)
    proc = run(tree)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "git diff failed" in proc.stderr


def test_t5_67_no_git_tree_explicit_file_needs_no_repository(tmp_path):
    tree = stage_tree(tmp_path, ["django"], None)
    proc = run(tree, "myapp/views.py")
    assert proc.returncode == 0, proc.stderr


def test_t5_67_unreachable_ref_exits_1(tmp_path):
    tree = sweep_tree(tmp_path, ["django"])
    commit_file(tree, "a.py")
    commit_file(tree, "b.py")
    proc = run(tree, "HEAD~5")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("run_post_change_sweep.sh: git diff failed (")


# ── T5.68 ────────────────────────────────────────────────────────────────────


def test_t5_68_text_rendering(tmp_path):
    tree = sweep_tree(tmp_path, ["django"], project_text=None)
    plan = json.loads(run(tree, "--json", "myapp/views.py").stdout)["plan"]
    proc = run(tree, "myapp/views.py")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.split("\n")
    assert lines[0] == "Changed files (1):"
    assert lines[1] == "  myapp/views.py"
    assert re.fullmatch(
        r"Review dimensions \(registry [0-9a-f]{12}, packs: django\):", lines[3]
    ), lines[3]
    for item in plan:
        head = f"    {'+' if item['applicable'] else '-'} {item['binding']} [{item['kind']}] "
        if item["applicable"]:
            n = len(item["matched_files"])
            assert f"{head}matched {n} file(s): {', '.join(item['matched_files'])}" in lines
        else:
            assert f"{head}{item['reason']}" in lines
    assert re.fullmatch(
        r"\d+ of 17 dimension\(s\) apply; \d+ of 23 binding\(s\) fired\.", lines[-2]
    ), lines[-2]
    assert lines[-1] == ""


def test_t5_68_cli_failure_leaves_stdout_empty_and_one_stderr_line(tmp_path):
    tree = sweep_tree(tmp_path, ["django"], prep=remove_core)
    proc = run(tree, "myapp/views.py")
    assert proc.returncode == 1
    assert proc.stdout == ""
    err_lines = proc.stderr.splitlines()
    assert len(err_lines) == 1
    assert err_lines[0].startswith("dimension_registry: core_missing:")
    assert "Traceback" not in proc.stderr


def test_t5_68_empty_set_text_line(tmp_path):
    tree = sweep_tree(tmp_path, ["django"], project_text=None)
    assert run(tree).stdout == "No changed files — no review dimension applies.\n"
