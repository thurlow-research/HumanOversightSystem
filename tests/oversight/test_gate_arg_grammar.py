"""Argument grammar parity across all seven file-list gates (#1759).

Before this fix, every file-list gate parsed its own argv independently, each
recognising only `--all` (plus `--staged` in secret_scan.sh) and treating any
other token as a filename — so `<gate>.sh --diff origin/main` silently scanned
zero real files (`--diff` and `origin/main` both landed in FILES as bogus
paths) and reported PASS/SKIP having checked nothing. These tests drive each
gate directly (the issue's own reproduction shape,
`gates/lint_check.sh --diff origin/main`), pinning that the shared grammar
(scripts/oversight/lib/changeset.sh) behaves identically everywhere it is
adopted.

Assertions here deliberately avoid depending on `pip-audit`'s network/CVE
result for `security_scan.sh` (its own currently-installed dependency set may
or may not carry advisories, independent of anything in this changeset) —
mirroring the existing precedent in test_scan_gates_empty_args.py, which
checks stdout markers rather than the overall exit code for that gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO / "scripts" / "oversight" / "gates"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)

FILE_LIST_GATES = [
    "lint_check",
    "type_check",
    "portability_check",
    "secret_scan",
    "security_scan",
    "bash_check",
    "template_refs_check",
]

# Gates that print the #976 "no files specified — defaulting" string on a
# true no-selector-at-all invocation (TD-VF-4). portability_check,
# bash_check and template_refs_check silently default without that exact
# console line — see the per-gate audit in the design's §6.
DEFAULTING_STRING_GATES = ["lint_check", "type_check", "secret_scan", "security_scan"]

# Gates that filter an explicit changeset to a specific "kind" and emit
# hos_changeset_skip_kind when none match (TC-G5).
KIND_FILTER_GATES = {
    "lint_check": "Python or JS/TS",
    "type_check": "Python",
    "bash_check": ".sh",
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(cwd: Path) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git(cwd, "add", "seed.txt")
    _git(cwd, "commit", "-q", "-m", "base")


def _run(gate: str, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    script = _GATES_DIR / f"{gate}.sh"
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


# ── TC-G1 — unknown flag ─────────────────────────────────────────────────────


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_unknown_option_is_usage_error(tmp_path, gate):
    res = _run(gate, tmp_path, "--nope")
    assert res.returncode == 2, res.stderr
    assert "unknown option" in res.stderr


# ── §9.2 TC-3C-3 (gate side) — resolution failure produces no tool output ───


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_diff_bad_ref_is_resolution_failure_with_no_tool_output(tmp_path, gate):
    _init_repo(tmp_path)
    res = _run(gate, tmp_path, "--diff", "nosuchref")
    assert res.returncode == 3, res.stderr
    assert res.stdout == ""
    assert "fatal:" in res.stderr


# ── TC-G2 — the issue's own reproduction ────────────────────────────────────


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_diff_reproduction_never_misparses_as_usage_error(tmp_path, gate):
    _init_repo(tmp_path)
    (tmp_path / "changed.py").write_text("x = 1\n")
    _git(tmp_path, "add", "changed.py")
    _git(tmp_path, "commit", "-q", "-m", "add changed.py")

    res = _run(gate, tmp_path, "--diff", "HEAD~1")
    assert res.returncode != 2, res.stderr
    assert "changeset = 1 file(s) from --diff HEAD~1" in res.stdout

    if gate == "lint_check":
        assert "no Python or JS/TS files in changeset" not in res.stdout


# ── TC-G3 — the runner's internal empty-changeset token ─────────────────────


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_empty_changeset_token_is_not_checked(tmp_path, gate):
    if gate == "template_refs_check":
        # The manage.py (Django) guard runs before the changeset case switch
        # (§6 row 5 — deliberately unchanged) and would otherwise short-circuit
        # to its own, unrelated "not a Django project" SKIP first.
        (tmp_path / "manage.py").write_text("")
    res = _run(gate, tmp_path, "--empty-changeset")
    assert res.returncode == 0, res.stderr
    assert "NOT CHECKED" in res.stdout
    assert "no files specified — defaulting" not in res.stdout
    assert "GATE PASS" not in res.stdout


# ── TC-G4 — #976 no-selector-at-all guard ───────────────────────────────────


@pytest.mark.parametrize("gate", DEFAULTING_STRING_GATES)
def test_no_args_still_defaults_to_full_project_scan(tmp_path, gate):
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(gate, tmp_path)
    assert "no files specified — defaulting" in res.stdout


# ── TC-G5 — zero-of-kind SKIP wording ────────────────────────────────────────


@pytest.mark.parametrize("gate,kind", KIND_FILTER_GATES.items())
def test_explicit_non_matching_kind_skips(tmp_path, gate, kind):
    (tmp_path / "only.md").write_text("# doc\n")
    res = _run(gate, tmp_path, "only.md")
    assert res.returncode == 0, res.stderr
    assert f"SKIP — 0 of 1 changeset file(s) are {kind}" in res.stdout


# ── TC-G6 — --all unaffected ─────────────────────────────────────────────────


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_all_selector_still_engages_project_enumeration(tmp_path, gate):
    res = _run(gate, tmp_path, "--all")
    assert res.returncode != 2, res.stderr
    assert "--all (project enumeration)" in res.stdout
    assert "no files specified — defaulting" not in res.stdout


# ── TC-G7 — --help / -h ──────────────────────────────────────────────────────


@pytest.mark.parametrize("gate", FILE_LIST_GATES)
def test_help_prints_usage_and_exits_zero(tmp_path, gate):
    res = _run(gate, tmp_path, "-h")
    assert res.returncode == 0, res.stderr
    assert "Usage:" in res.stdout


# ── TC-G8 — collection_integrity's exemption (Ruling G) ─────────────────────
#
# collection_integrity.sh is a no-argument gate (§6 row 10): it takes NO
# changeset argv at all — not even the shared grammar — because it is a
# whole-repo *integrity* check ("does the full suite still import"), so file
# scoping is meaningless for it. Any argv run_gates.sh forwards must be
# silently ignored, never narrowing what it checks.


def _run_collection_integrity(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    script = _GATES_DIR / "collection_integrity.sh"
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_collection_integrity_ignores_explicit_paths(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a = 1\n")
    (tmp_path / "b.py").write_text("b = 1\n")

    baseline = _run_collection_integrity(tmp_path)
    with_paths = _run_collection_integrity(tmp_path, "a.py", "b.py")

    assert with_paths.returncode == baseline.returncode
    assert with_paths.stdout == baseline.stdout


def test_collection_integrity_ignores_diff_flag(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a = 1\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-q", "-m", "add a.py")

    baseline = _run_collection_integrity(tmp_path)
    with_diff = _run_collection_integrity(tmp_path, "--diff", "HEAD~1")

    assert with_diff.returncode == baseline.returncode
    assert with_diff.stdout == baseline.stdout
