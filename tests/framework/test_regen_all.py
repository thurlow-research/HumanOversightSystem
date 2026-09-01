"""Tests for scripts/framework/regen_all.sh (#1414).

regen_all.sh is the single canonical entry point wrapping the two
self-heal-safe generators (gen_scripts_index.sh, gen_codeowners.sh). Mirrors
the sandboxing technique already proven in test_scripts_index.py and
test_codeowners_current.py: an isolated temp repo layout so nothing here ever
touches the real committed SCRIPTS-INDEX.md or .github/CODEOWNERS.
"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGEN_ALL = ROOT / "scripts" / "framework" / "regen_all.sh"
GEN_INDEX = ROOT / "scripts" / "framework" / "gen_scripts_index.sh"
GEN_CODEOWNERS = ROOT / "scripts" / "framework" / "gen_codeowners.sh"
SURFACES = ROOT / "scripts" / "framework" / "protected_surfaces.txt"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
INDEX = ROOT / "SCRIPTS-INDEX.md"

_IGNORE_DIRS = shutil.ignore_patterns(".venv", "__pycache__", ".git")


def _committed_owner() -> str:
    match = re.search(r"^# Owner: (@\S+)$", CODEOWNERS.read_text(), flags=re.MULTILINE)
    assert match, "committed CODEOWNERS has no '# Owner: @X' line"
    return match.group(1)


def _build_sandbox(tmp_path: Path) -> Path:
    """Copy the on-disk layout regen_all.sh and its generators depend on — the
    bin/, bootstrap/, scripts/ trees gen_scripts_index.sh scans, plus .github/
    and SCRIPTS-INDEX.md itself — into an isolated directory. No git repo yet:
    self-heal tests need to commit a *stale* baseline first (see
    _git_commit_baseline) so regen_all.sh's `git diff --quiet` change-detection
    has something meaningful to diff the fix against."""
    sandbox = tmp_path / "repo"
    sandbox.mkdir()
    for d in ("bin", "bootstrap", "scripts"):
        shutil.copytree(ROOT / d, sandbox / d, ignore=_IGNORE_DIRS)
    shutil.copytree(ROOT / ".github", sandbox / ".github")
    shutil.copy(INDEX, sandbox / "SCRIPTS-INDEX.md")
    return sandbox


def _git_commit_baseline(sandbox: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=sandbox, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.local", "-c", "user.name=test", "add", "-A"],
        cwd=sandbox, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@test.local", "-c", "user.name=test",
         "commit", "-q", "-m", "sandbox baseline"],
        cwd=sandbox, check=True,
    )


def test_check_mode_reports_current_against_real_repo():
    result = subprocess.run(
        ["bash", str(REGEN_ALL), "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All generated artifacts are current." in result.stdout


def test_check_mode_detects_staleness(tmp_path):
    sandbox = _build_sandbox(tmp_path)
    stale_index = sandbox / "SCRIPTS-INDEX.md"
    stale_index.write_text(stale_index.read_text() + "\nstale line injected by test\n")

    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / "framework" / "regen_all.sh"), "--check"],
        cwd=sandbox, capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SCRIPTS-INDEX.md is stale" in result.stdout
    assert "gen_scripts_index.sh" in result.stdout


def test_self_heal_mode_fixes_stale_index(tmp_path):
    sandbox = _build_sandbox(tmp_path)
    stale_index = sandbox / "SCRIPTS-INDEX.md"
    stale_index.write_text(stale_index.read_text() + "\nstale line injected by test\n")
    _git_commit_baseline(sandbox)

    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / "framework" / "regen_all.sh")],
        cwd=sandbox, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    expected_out = tmp_path / "expected-SCRIPTS-INDEX.md"
    subprocess.run(
        ["bash", str(sandbox / "scripts" / "framework" / "gen_scripts_index.sh"), str(expected_out)],
        cwd=sandbox, check=True, capture_output=True, text=True,
    )
    assert stale_index.read_text() == expected_out.read_text()
    assert "regenerated" in result.stdout


def test_self_heal_mode_fixes_stale_codeowners(tmp_path):
    sandbox = _build_sandbox(tmp_path)
    owner = _committed_owner()
    stale_codeowners = sandbox / ".github" / "CODEOWNERS"
    original = stale_codeowners.read_text()
    stale_codeowners.write_text(original.replace("/bin/", "/bin-stale/"))
    _git_commit_baseline(sandbox)

    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / "framework" / "regen_all.sh")],
        cwd=sandbox, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert stale_codeowners.read_text() == original
    assert "regenerated" in result.stdout
