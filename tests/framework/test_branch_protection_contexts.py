"""Regression guard for the #737 status-check context mismatch.

GitHub reports a Actions check's status-check *context* under the job's `name:`
field. Branch protection (scripts/framework/setup_branch_protection.sh) requires
a fixed set of contexts. If a required context has no producing workflow job
whose `name:` matches it exactly, that context stays permanently "expected" and
every merge returns HTTP 405 — while the gates themselves run green. That is the
exact failure #737 documents (overseer AUTO_MERGE never completes; all PRs
silently human-merged).

These tests make that drift fail in the inner loop instead of at merge time:
every required context must be produced by some workflow job, by exact name.

#1981: the script ships to consumers, so its literal ("core") list may only
hold contexts whose producing workflow also ships. HOS-repo-only contexts live
in scripts/framework/hos_required_contexts.txt, which never ships.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRAMEWORK_DIR = _REPO_ROOT / "scripts" / "framework"
_SETUP_SCRIPT = _FRAMEWORK_DIR / "setup_branch_protection.sh"
_HOS_CONTEXTS_FILE = _FRAMEWORK_DIR / "hos_required_contexts.txt"
_CONSUMER_FILES = _FRAMEWORK_DIR / "framework_consumer_files.txt"
_INSTALLER = _REPO_ROOT / "bootstrap" / "hos_install.sh"
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _core_contexts() -> list[str]:
    """Extract the literal required_status_checks.contexts from the setup script."""
    text = _SETUP_SCRIPT.read_text(encoding="utf-8")
    # The payload is a JSON heredoc; grab the contexts array line.
    m = re.search(r'"contexts"\s*:\s*\[([^\]]*)\]', text)
    assert m, "could not find required_status_checks.contexts in setup_branch_protection.sh"
    return re.findall(r'"([^"]+)"', m.group(1))


def _parse_context_lines(text: str) -> list[str]:
    """Non-blank, non-comment lines, stripped (the script's own parsing rules)."""
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _hos_only_contexts() -> list[str]:
    """Names from hos_required_contexts.txt (HOS-repo-only; absent in consumers)."""
    return _parse_context_lines(_HOS_CONTEXTS_FILE.read_text(encoding="utf-8"))


def _required_contexts() -> list[str]:
    """Every context the script can require in the HOS repo: core + HOS-only."""
    return _core_contexts() + _hos_only_contexts()


def _consumer_shipped_paths() -> set[str]:
    return set(_parse_context_lines(_CONSUMER_FILES.read_text(encoding="utf-8")))


def _workflow_job_names() -> dict[str, str]:
    """Map every workflow job's reported check context (its `name:`) -> source file."""
    names: dict[str, str] = {}
    for wf in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_id, job in (data.get("jobs") or {}).items():
            # GitHub uses `name:` as the check context; absent name falls back
            # to the job id.
            context = (job or {}).get("name", job_id)
            names[context] = wf.name
    return names


def test_every_core_context_is_produced_by_a_consumer_shipped_workflow():
    """#1981: the literal list ships to consumers, so each of its contexts must be
    produced by a workflow that ships too — else a consumer's PRs wait forever
    on a check nothing in their repo produces (#737)."""
    produced = _workflow_job_names()
    shipped = _consumer_shipped_paths()
    unshipped = {}
    for ctx in _core_contexts():
        wf = produced.get(ctx)
        if wf is None or f".github/workflows/{wf}" not in shipped:
            unshipped[ctx] = wf
    assert not unshipped, (
        f"Core required context(s) {unshipped} have no producing workflow listed "
        "in scripts/framework/framework_consumer_files.txt. Consumers running "
        "setup_branch_protection.sh would be blocked on checks that never report "
        "(#1981, #737). Move HOS-only contexts to hos_required_contexts.txt."
    )


def test_hos_contexts_file_is_not_shipped_to_consumers():
    """T-RP-09: the HOS-only file must stay out of the consumer manifest + installer."""
    rel = "scripts/framework/hos_required_contexts.txt"
    assert (
        rel not in _consumer_shipped_paths()
    ), f"{rel} must not be in framework_consumer_files.txt (#1981)"
    assert "hos_required_contexts" not in _INSTALLER.read_text(encoding="utf-8")


def test_hos_contexts_file_format():
    """Every entry matches the name pattern, is unique, and is disjoint from core."""
    hos = _hos_only_contexts()
    assert hos, "hos_required_contexts.txt declares no contexts"
    bad = [c for c in hos if not _NAME_RE.match(c)]
    assert not bad, f"invalid context names in hos_required_contexts.txt: {bad}"
    assert len(hos) == len(set(hos)), "duplicate names in hos_required_contexts.txt"
    overlap = set(hos) & set(_core_contexts())
    assert not overlap, f"contexts in both core list and hos file: {sorted(overlap)}"


def test_setup_script_exists():
    assert _SETUP_SCRIPT.is_file(), f"missing {_SETUP_SCRIPT}"


def test_required_contexts_are_nonempty():
    contexts = _required_contexts()
    assert contexts, "branch protection declares no required status checks"


def test_every_required_context_has_a_producing_job():
    """Each required context MUST be produced by a workflow job of the same name.

    A required context with no producer is the #737 failure: it stays
    permanently 'expected' and blocks every merge while looking green.
    """
    contexts = _required_contexts()
    produced = _workflow_job_names()
    missing = [c for c in contexts if c not in produced]
    assert not missing, (
        f"Required status-check context(s) {missing} have no producing workflow "
        f"job (by exact `name:`). Produced contexts: {sorted(produced)}. "
        "This is the #737 failure mode — reconcile the job `name:` in "
        ".github/workflows/ with setup_branch_protection.sh."
    )


def test_known_gate_contexts_present():
    """The four server-side gates must be required + produced."""
    contexts = set(_required_contexts())
    produced = _workflow_job_names()
    for gate in (
        "require-overseer-approval",
        "require-human-approval",
        "require-tier-ceiling",
        "tests",
    ):
        assert gate in contexts, f"{gate} is no longer a required status check"
        assert gate in produced, f"{gate} has no producing workflow job named {gate!r}"


def test_rerun_gate_checks_not_a_required_context():
    """The rerun-gate-checks dispatcher (#1299) must NEVER be a required status
    check. It only runs on pull_request_review events, so on a PR with no
    review yet the context would sit permanently "expected" and block every
    merge — the #737 failure mode this repo has already hit once. It reruns
    EXISTING gate workflow runs rather than gating anything itself."""
    contexts = set(_required_contexts())
    assert "rerun-gate-checks" not in contexts, (
        "rerun-gate-checks must not be a required status check — it only "
        "fires on review events, so it would stay permanently 'expected' on "
        "any PR without a review yet and block every merge (#737)."
    )


# ── Behavioural tests of the script (hermetic: stub gh, no network) ───────────

_STUB_GH = """#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
if [ "$1" = "api" ] && [ "$2" = "user" ]; then
  echo "humanadmin"
  exit 0
fi
case "$*" in
  *"--method PUT"*) cat > "$GH_CAPTURE"; echo '{}' ;;
  *) echo '{}' ;;
esac
exit 0
"""


def _run_script(tmp_path: Path, hos_file: str | None, *args: str):
    """Run a copy of the script in an isolated dir with a stub gh on PATH."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    shutil.copy(_SETUP_SCRIPT, script_dir / "setup_branch_protection.sh")
    (script_dir / "machine-accounts.env").write_text('BOT_ACCOUNTS="somebot[bot]"\n')
    if hos_file is not None:
        (script_dir / "hos_required_contexts.txt").write_text(hos_file)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(_STUB_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "gh.log"
    capture = tmp_path / "payload.json"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_CAPTURE": str(capture),
    }
    proc = subprocess.run(
        ["bash", str(script_dir / "setup_branch_protection.sh"), "owner/repo", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc, log, capture


_CORE = ["require-overseer-approval", "require-human-approval", "require-tier-ceiling"]


def test_script_without_hos_file_requires_only_core(tmp_path):
    proc, _, _ = _run_script(tmp_path, None, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    for ctx in _CORE:
        assert ctx in proc.stdout
    assert "Required status checks (3)" in proc.stdout
    assert "hos_required_contexts.txt" not in proc.stdout


def test_script_dry_run_lists_appended_hos_contexts(tmp_path):
    proc, _, _ = _run_script(tmp_path, "# header\n\nalpha-one\r\n  beta.two  \n", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "Required status checks (5)" in proc.stdout
    assert "alpha-one   (from hos_required_contexts.txt)" in proc.stdout
    assert "beta.two   (from hos_required_contexts.txt)" in proc.stdout


def test_script_payload_is_core_then_file_names_in_order(tmp_path):
    proc, _, capture = _run_script(tmp_path, "alpha-one\nbeta.two\n")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(capture.read_text())
    assert payload["required_status_checks"]["contexts"] == _CORE + ["alpha-one", "beta.two"]


@pytest.mark.parametrize("bad_line", ['bad"name', 'x", "y', "has space", "semi;colon"])
def test_script_rejects_invalid_context_before_any_api_call(tmp_path, bad_line):
    proc, log, capture = _run_script(tmp_path, f"good-one\n{bad_line}\n")
    assert proc.returncode != 0
    assert not log.exists() or log.read_text() == "", "gh was invoked before validation"
    assert not capture.exists()
