"""Tests for the --worker / --overseer / --human role flags in hos_install.sh.

Static guards assert implementation invariants directly in the source.

Functional tests (run with --dry-run --local --no-pack — no files written, no
network access):

  (a) no role flags → worker+overseer cron-prompt "Would generate" messages,
      no human interactive-session block in output.
  (b) --human alone → neither cron-prompt message, human block (bin/hos-human)
      present, no worker/overseer crontab lines.
  (c) --worker alone → only worker cron-prompt message; no overseer content.
  (d) --worker --human → exit 2 (mutual-exclusion error), no output written.
"""
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "bootstrap" / "hos_install.sh"
_SRC = _INSTALLER.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_init_target(tmp_path: Path) -> Path:
    """Create and git-initialise a throwaway target directory."""
    target = tmp_path / "target"
    target.mkdir()
    _git("init", "--quiet", str(target), cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=target)
    _git("config", "user.name", "Test", cwd=target)
    return target


def _run_installer(target: Path, extra_args: list) -> subprocess.CompletedProcess:
    """Run hos_install.sh --dry-run --local --no-pack against target.

    HOS_NO_CONFIG=1 suppresses the interactive config sub-invocation.
    --dry-run means no files are written.
    --local uses the current working copy as HOS_SOURCE.
    --no-pack skips pack resolution (no config.sh required).
    """
    cmd = [
        "bash",
        str(_INSTALLER),
        "--dry-run",
        "--local",
        "--no-pack",
        str(target),
        *extra_args,
    ]
    env = {**os.environ, "HOS_NO_CONFIG": "1"}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input="\n",
        timeout=120,
    )


# --------------------------------------------------------------------------- #
# static guards — the implementation must exist in the source
# --------------------------------------------------------------------------- #


def test_role_defaults_exist_in_source():
    """Defaults block must declare all three role flags as false."""
    assert "ROLE_WORKER=false" in _SRC, "ROLE_WORKER default missing from hos_install.sh"
    assert "ROLE_OVERSEER=false" in _SRC, "ROLE_OVERSEER default missing from hos_install.sh"
    assert "ROLE_HUMAN=false" in _SRC, "ROLE_HUMAN default missing from hos_install.sh"


def test_role_arg_cases_exist_in_source():
    """Arg-parsing loop must contain cases for all three role flags."""
    assert "--worker)" in _SRC, "--worker) case missing from arg-parsing loop"
    assert "--overseer)" in _SRC, "--overseer) case missing from arg-parsing loop"
    assert "--human)" in _SRC, "--human) case missing from arg-parsing loop"


def test_default_resolution_logic_exists_in_source():
    """The no-flags default (worker+overseer, not human) must be present."""
    assert "ROLE_WORKER=true; ROLE_OVERSEER=true" in _SRC, (
        "default role resolution (no flags → worker+overseer) missing from hos_install.sh"
    )


def test_mutual_exclusion_guard_exists_in_source():
    """--human and --worker/--overseer must be guarded as mutually exclusive."""
    assert "$ROLE_HUMAN && { $ROLE_WORKER || $ROLE_OVERSEER; }" in _SRC, (
        "mutual-exclusion guard (ROLE_HUMAN && ROLE_WORKER/OVERSEER) missing from hos_install.sh"
    )


def test_human_claude_md_guard_exists_in_source():
    """Orchestrator CLAUDE.md block must be gated behind if ! $ROLE_HUMAN."""
    assert "if ! $ROLE_HUMAN" in _SRC, (
        "guard 'if ! $ROLE_HUMAN' around CLAUDE.md orchestrator block missing from hos_install.sh"
    )


def test_role_gated_cron_generation_exists_in_source():
    """Cron-prompt generation must be gated by ROLE_WORKER and ROLE_OVERSEER."""
    assert "if $ROLE_WORKER; then" in _SRC, (
        "ROLE_WORKER gate around worker cron-prompt generation missing"
    )
    assert "if $ROLE_OVERSEER; then" in _SRC, (
        "ROLE_OVERSEER gate around overseer cron-prompt generation missing"
    )


def test_human_next_steps_block_exists_in_source():
    """The human interactive-session next-steps block must point at bin/hos-human."""
    assert "bin/hos-human" in _SRC, (
        "human session launcher (bin/hos-human) missing from human next-steps in hos_install.sh"
    )
    assert "docs/HUMAN-SETUP.md" in _SRC, (
        "HUMAN-SETUP.md reference missing from human next-steps in hos_install.sh"
    )


def test_source_login_param_in_subst_prompt():
    """_subst_prompt must use source_login parameter (not the old role keyword)."""
    assert "source_login" in _SRC, (
        "_subst_prompt no longer uses 'source_login' — was the rename reverted?"
    )
    # The old pattern hardcoded the role-based login construction; it must be gone.
    assert '"hos-${role}-hos[bot]"' not in _SRC, (
        '"hos-${role}-hos[bot]" still present — 4.3 rename did not apply cleanly'
    )


# --------------------------------------------------------------------------- #
# functional tests — run the installer with --dry-run
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_no_role_flags_defaults_to_worker_and_overseer(tmp_path):
    """No role flags → worker+overseer cron messages, no human block."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, [])
    assert r.returncode == 0, f"installer failed:\n{r.stdout}\n{r.stderr}"
    combined = r.stdout + r.stderr

    # Both cron-prompt generation messages must appear.
    assert "worker-cron-prompt.md" in combined, (
        "worker-cron-prompt.md 'Would generate' message missing (no-flags default)"
    )
    assert "overseer-cron-prompt.md" in combined, (
        "overseer-cron-prompt.md 'Would generate' message missing (no-flags default)"
    )

    # The human next-steps block must NOT appear.
    assert "hos-human" not in combined, (
        "bin/hos-human shown in next-steps when --human was not passed"
    )
    assert "HUMAN-SETUP.md" not in combined, (
        "HUMAN-SETUP.md shown when --human was not passed"
    )


@pytest.mark.slow
def test_human_only_no_cron_prompts_and_human_block_present(tmp_path):
    """--human alone → no cron-prompt messages, no crontab lines, human block present."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--human"])
    assert r.returncode == 0, f"installer failed:\n{r.stdout}\n{r.stderr}"
    combined = r.stdout + r.stderr

    # Neither cron-prompt generation message must appear.
    assert "worker-cron-prompt.md" not in combined, (
        "worker-cron-prompt.md message shown when --human-only (no --worker)"
    )
    assert "overseer-cron-prompt.md" not in combined, (
        "overseer-cron-prompt.md message shown when --human-only (no --overseer)"
    )

    # No worker or overseer crontab lines.
    assert "hos-cron --role worker" not in combined, (
        "worker crontab line shown when --human only"
    )
    assert "hos-cron --role overseer" not in combined, (
        "overseer crontab line shown when --human only"
    )

    # The human block must appear — bin/hos-human in the next-steps echo.
    assert "hos-human" in combined, (
        "bin/hos-human missing from next-steps when --human passed"
    )
    assert "HUMAN-SETUP.md" in combined, (
        "HUMAN-SETUP.md reference missing from next-steps when --human passed"
    )


@pytest.mark.slow
def test_worker_only_generates_worker_cron_prompt_only(tmp_path):
    """--worker alone → only worker cron-prompt message; no overseer content."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--worker"])
    assert r.returncode == 0, f"installer failed:\n{r.stdout}\n{r.stderr}"
    combined = r.stdout + r.stderr

    # Worker cron-prompt message must appear.
    assert "worker-cron-prompt.md" in combined, (
        "worker-cron-prompt.md message missing when --worker passed"
    )

    # Overseer cron-prompt message must NOT appear.
    assert "overseer-cron-prompt.md" not in combined, (
        "overseer-cron-prompt.md message shown when only --worker passed"
    )

    # Worker crontab line must appear; overseer must not.
    assert "hos-cron --role worker" in combined, (
        "worker crontab line missing when --worker passed"
    )
    assert "hos-cron --role overseer" not in combined, (
        "overseer crontab line shown when only --worker passed"
    )

    # No human block.
    assert "hos-human" not in combined, (
        "bin/hos-human shown in next-steps when --human was not passed"
    )


@pytest.mark.slow
def test_worker_and_human_mutual_exclusion_exits_2(tmp_path):
    """--worker --human must exit 2 with a clear mutual-exclusion error."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--worker", "--human"])
    assert r.returncode == 2, (
        f"expected exit 2 (mutual exclusion), got {r.returncode}:\n{r.stdout}\n{r.stderr}"
    )
    combined = r.stdout + r.stderr
    assert "mutually exclusive" in combined.lower(), (
        "mutual-exclusion error message missing from --worker --human output"
    )


@pytest.mark.slow
def test_overseer_and_human_mutual_exclusion_exits_2(tmp_path):
    """--overseer --human must also exit 2 (not just --worker --human)."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--overseer", "--human"])
    assert r.returncode == 2, (
        f"expected exit 2 (mutual exclusion), got {r.returncode}:\n{r.stdout}\n{r.stderr}"
    )
    assert "mutually exclusive" in (r.stdout + r.stderr).lower(), (
        "mutual-exclusion error missing from --overseer --human output"
    )
