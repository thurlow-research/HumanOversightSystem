"""run_gates.sh changeset resolution (#1759).

Before this fix, run_gates.sh forwarded its own argv verbatim to every gate
script (`GATE_ARGS=("$@")`), so `run_gates.sh --diff origin/main` pushed the
literal tokens "--diff" and "origin/main" into each gate's own FILES array as
bogus filenames — every gate scanned zero real files and reported PASS/SKIP
having checked nothing.

These tests drive the real script through RUN_GATES_RESOLVE_ONLY (modelled on
run_validators.sh's RUN_VALIDATORS_FILELIST_ONLY seam, #981), which prints the
resolved MODE/STATUS/SOURCE/FILE/FORWARD block and exits before the tool
preflight and before any gate runs — so resolution is pinned deterministically,
without external tooling. A resolution FAILURE (exit 2/3) happens inside
hos_changeset_parse, before the seam is ever reached, so those cases are
exercised through the real script directly (with or without the seam set —
it makes no difference for a fatal).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "oversight" / "run_gates.sh"
_AUDIT_LOG_SH = _REPO / "scripts" / "oversight" / "lib" / "audit_log.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(cwd: Path) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git(cwd, "add", "seed.txt")
    _git(cwd, "commit", "-q", "-m", "base")


def _run(cwd: Path, *args: str, resolve_only: bool = True, env_extra: dict | None = None):
    env = {**os.environ}
    if resolve_only:
        env["RUN_GATES_RESOLVE_ONLY"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def _parse_block(stdout: str) -> dict:
    parsed: dict = {"FILE": [], "FORWARD": []}
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        key, _, val = line.partition("\t")
        if key in ("FILE", "FORWARD"):
            parsed[key].append(val)
        else:
            parsed[key] = val
    return parsed


def _gate_results(cwd: Path) -> list:
    path = cwd / ".claudetmp" / "oversight" / "validators" / "gate-results.json"
    return json.loads(path.read_text())


# ── TC-R1/TC-R2 — AC-1 structural parity ───────────────────────────────────────


def test_diff_resolves_changed_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a\n")
    (tmp_path / "b.py").write_text("b\n")
    (tmp_path / "c.py").write_text("c\n")
    _git(tmp_path, "add", "a.py", "b.py", "c.py")
    _git(tmp_path, "commit", "-q", "-m", "add three")

    res = _run(tmp_path, "--diff", "HEAD~1")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["MODE"] == "diff"
    assert block["STATUS"] == "ok"
    assert sorted(block["FILE"]) == ["a.py", "b.py", "c.py"]


def test_diff_forward_matches_explicit_forward_ac1(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a\n")
    (tmp_path / "b.py").write_text("b\n")
    _git(tmp_path, "add", "a.py", "b.py")
    _git(tmp_path, "commit", "-q", "-m", "add two")

    diff_res = _run(tmp_path, "--diff", "HEAD~1")
    explicit_res = _run(tmp_path, "a.py", "b.py")
    assert diff_res.returncode == 0
    assert explicit_res.returncode == 0
    diff_block = _parse_block(diff_res.stdout)
    explicit_block = _parse_block(explicit_res.stdout)
    assert diff_block["FORWARD"] == explicit_block["FORWARD"]


# ── TC-R3 — deletions excluded, counted ────────────────────────────────────────


def test_diff_deletion_excluded_and_counted(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "keep.py").write_text("keep\n")
    _git(tmp_path, "add", "keep.py")
    _git(tmp_path, "commit", "-q", "-m", "add keep")
    _git(tmp_path, "rm", "-q", "seed.txt")
    _git(tmp_path, "commit", "-q", "-m", "delete seed")

    res = _run(tmp_path, "--diff", "HEAD~1")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert "seed.txt" not in block["FILE"]
    assert "1 deletion(s) excluded" in res.stdout


# ── TC-R4 — selector resolves to zero (case 2) ─────────────────────────────────


def test_diff_clean_tree_is_empty_status(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "HEAD")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "empty"
    assert block["FORWARD"] == ["--empty-changeset"]


# ── TC-R5 — resolution failure (case 3) ────────────────────────────────────────


def test_diff_bad_ref_fails_closed(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "nosuchref", resolve_only=False)
    assert res.returncode == 3
    assert "fatal:" in res.stderr
    assert _gate_results(tmp_path) == []


# ── TC-R6/R7/R8 — usage errors ─────────────────────────────────────────────────


@pytest.mark.parametrize("bad_args", [["--dif", "HEAD"], ["--diff-ref", "X"], ["-x"]])
def test_unknown_flag_shaped_token_is_usage_error(tmp_path, bad_args):
    _init_repo(tmp_path)
    res = _run(tmp_path, *bad_args, resolve_only=False)
    assert res.returncode == 2
    assert "unknown option" in res.stderr


def test_diff_missing_value_is_usage_error(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", resolve_only=False)
    assert res.returncode == 2


def test_diff_flag_shaped_value_is_usage_error(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "--all", resolve_only=False)
    assert res.returncode == 2


# ── TC-R9/R10/R11 — case 1, --all, explicit ────────────────────────────────────


def test_no_args_is_unscoped_with_empty_forward(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path)
    assert res.returncode == 0
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "unscoped"
    assert block["FORWARD"] == []


def test_all_forwards_all_flag(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--all")
    assert res.returncode == 0
    block = _parse_block(res.stdout)
    assert block["FORWARD"] == ["--all"]


def test_explicit_existing_paths_forwarded_verbatim(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "x.py").write_text("x\n")
    (tmp_path / "y.py").write_text("y\n")
    res = _run(tmp_path, "x.py", "y.py")
    assert res.returncode == 0
    block = _parse_block(res.stdout)
    assert block["FORWARD"] == ["x.py", "y.py"]


# ── TC-R12/R13 — fabricated paths (Ruling I) ───────────────────────────────────


def test_explicit_all_fabricated_is_fatal(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "nosuch1.py", "nosuch2.py", resolve_only=False)
    assert res.returncode == 3
    assert "git has never tracked" in res.stderr


def test_explicit_one_fabricated_among_live_fails_immediately(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "live.py").write_text("x\n")
    res = _run(tmp_path, "live.py", "nosuch.py", resolve_only=False)
    assert res.returncode == 3
    assert "git has never tracked" in res.stderr


# ── TC-R14/R15 — deletions classify as case 2, never fatal (RISK-1) ────────────


def test_explicit_one_deleted_one_live(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "live.py").write_text("x\n")
    _git(tmp_path, "add", "live.py")
    _git(tmp_path, "commit", "-q", "-m", "add live")
    _git(tmp_path, "rm", "-q", "seed.txt")
    _git(tmp_path, "commit", "-q", "-m", "delete seed")

    res = _run(tmp_path, "live.py", "seed.txt")
    assert res.returncode == 0, res.stderr
    assert "(deleted)" in res.stderr
    assert "1 path(s) not on disk" in res.stdout


def test_explicit_all_deleted_is_case2_not_fatal(tmp_path):
    """RISK-1 regression guard: a deletion-only changeset must never be rc 3."""
    _init_repo(tmp_path)
    _git(tmp_path, "rm", "-q", "seed.txt")
    _git(tmp_path, "commit", "-q", "-m", "delete seed")

    res = _run(tmp_path, "seed.txt")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "empty"
    assert block["FORWARD"] == ["--empty-changeset"]


def test_explicit_staged_then_removed_classifies_deleted_via_index(tmp_path):
    """A staged addition removed from the working tree (git add f && rm f) must
    classify as `deleted` via the index tier, not `fabricated` (detail 3)."""
    _init_repo(tmp_path)
    (tmp_path / "staged.py").write_text("x\n")
    _git(tmp_path, "add", "staged.py")
    (tmp_path / "staged.py").unlink()

    res = _run(tmp_path, "staged.py")
    assert res.returncode == 0, res.stderr
    assert "(deleted)" in res.stderr


# ── TC-R16/R17 — --step resolution failures ────────────────────────────────────


def test_step_with_no_audit_events_is_fatal(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--step", "3", resolve_only=False)
    assert res.returncode == 3
    assert "no step-head audit event" in res.stderr


def test_step_with_no_base_commit_is_fatal(tmp_path):
    _init_repo(tmp_path)
    head_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    env = {**os.environ}
    result = subprocess.run(
        ["bash", "-c", f'source "{_AUDIT_LOG_SH}" && audit_write_event "$1" "$2"',
         "_", f'{{"event":"step-head","step":1,"head_sha":"{head_sha}"}}', str(tmp_path)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr

    res = _run(tmp_path, "--step", "1", resolve_only=False)
    assert res.returncode == 3
    assert "has no base commit" in res.stderr


def test_step_non_numeric_is_usage_error(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--step", "abc", resolve_only=False)
    assert res.returncode == 2


# ── TC-R18 — --step resolves a real range; TC-R18b pins the explicit root ──────


def _write_step_event(repo: Path, step: int, head_sha: str) -> None:
    result = subprocess.run(
        ["bash", "-c", 'source "$1" && audit_write_event "$2" "$3"',
         "_", str(_AUDIT_LOG_SH), f'{{"event":"step-head","step":{step},"head_sha":"{head_sha}"}}', str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_step_resolves_range_from_synthetic_events(tmp_path):
    _init_repo(tmp_path)
    base_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "changed.py").write_text("x\n")
    _git(tmp_path, "add", "changed.py")
    _git(tmp_path, "commit", "-q", "-m", "step 2 commit")
    head_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    _write_step_event(tmp_path, 1, base_sha)
    _write_step_event(tmp_path, 2, head_sha)

    res = _run(tmp_path, "--step", "2")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "ok"
    assert block["SOURCE"] == f"--step 2 ({base_sha}..{head_sha})"
    assert block["FILE"] == ["changed.py"]


def test_step_uses_fixture_root_not_the_hos_repo(tmp_path):
    """TD-VF-10 guard: get_step_range must be passed the fixture's own
    toplevel, not the HOS repo containing lib/audit_log.py. The fixture's
    step-head SHAs exist ONLY in the fixture's own history; this repo's own
    audit/log/ (thousands of real events) does not know them. A regression
    that drops the explicit root argument would resolve against THIS repo's
    audit log instead — a range built from different (or absent) SHAs — so
    this test's exact-SHA assertion would fail rather than passing by
    accident."""
    _init_repo(tmp_path)
    base_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "changed.py").write_text("y\n")
    _git(tmp_path, "add", "changed.py")
    _git(tmp_path, "commit", "-q", "-m", "fixture-only commit")
    head_sha = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    _write_step_event(tmp_path, 1, base_sha)
    _write_step_event(tmp_path, 2, head_sha)

    res = _run(tmp_path, "--step", "2")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["SOURCE"] == f"--step 2 ({base_sha}..{head_sha})"
    # This SHA pair cannot be resolved from the real HOS repo's audit log
    # (it was never written there) — a dropped-root bug reading that log
    # instead would produce a different range or none at all.
    assert base_sha != head_sha


def test_diff_and_step_together_step_is_metadata_only(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-q", "-m", "add a")

    res = _run(tmp_path, "--diff", "HEAD~1", "--step", "3")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["MODE"] == "diff"


# ── TC-R19/R20 — git preconditions ─────────────────────────────────────────────


def test_diff_outside_git_repo_is_fatal(tmp_path):
    res = _run(tmp_path, "--diff", "HEAD", resolve_only=False)
    assert res.returncode == 3
    assert "require a git repository" in res.stderr


def test_diff_from_subdirectory_is_fatal(tmp_path):
    _init_repo(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    res = _run(sub, "--diff", "HEAD", resolve_only=False)
    assert res.returncode == 3
    assert "must be run from the repository root" in res.stderr


# ── TC-R21 — --staged ───────────────────────────────────────────────────────────


def test_staged_resolves_staged_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "staged.py").write_text("x\n")
    _git(tmp_path, "add", "staged.py")

    res = _run(tmp_path, "--staged")
    assert res.returncode == 0, res.stderr
    block = _parse_block(res.stdout)
    assert block["MODE"] == "staged"
    assert block["FILE"] == ["staged.py"]


# ── TC-R22 — --help ──────────────────────────────────────────────────────────────


def test_help_exits_zero_no_artifact(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--help", resolve_only=False)
    assert res.returncode == 0
    assert "Usage:" in res.stdout
    assert not (tmp_path / ".claudetmp" / "oversight" / "validators" / "gate-results.json").exists()


# ── TC-R23 — mutually exclusive selectors (Ruling F) ────────────────────────────


def test_all_with_explicit_path_is_usage_error(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "extra.py").write_text("x\n")
    res = _run(tmp_path, "--all", "extra.py", resolve_only=False)
    assert res.returncode == 2


# ── §9.2 three-case tests — the runner side ────────────────────────────────────


def test_case1_no_selector_forwards_nothing(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path)
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "unscoped"
    assert block["FORWARD"] == []


def test_case2_selector_zero_files_is_distinguishable_from_case1(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "HEAD")
    block = _parse_block(res.stdout)
    assert block["STATUS"] == "empty"
    assert block["FORWARD"] == ["--empty-changeset"]


def test_case3_resolution_failed_writes_empty_artifact(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "nosuchref", resolve_only=False)
    assert res.returncode == 3
    assert _gate_results(tmp_path) == []
