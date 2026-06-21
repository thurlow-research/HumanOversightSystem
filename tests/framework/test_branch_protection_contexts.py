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
"""
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETUP_SCRIPT = _REPO_ROOT / "scripts" / "framework" / "setup_branch_protection.sh"
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"


def _required_contexts() -> list[str]:
    """Extract required_status_checks.contexts from the setup script's payload."""
    text = _SETUP_SCRIPT.read_text(encoding="utf-8")
    # The payload is a JSON heredoc; grab the contexts array line.
    m = re.search(r'"contexts"\s*:\s*\[([^\]]*)\]', text)
    assert m, "could not find required_status_checks.contexts in setup_branch_protection.sh"
    return re.findall(r'"([^"]+)"', m.group(1))


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
    """The two server-side gates the overseer relies on must be required + produced."""
    contexts = set(_required_contexts())
    produced = _workflow_job_names()
    for gate in ("require-human-approval", "require-tier-ceiling"):
        assert gate in contexts, f"{gate} is no longer a required status check"
        assert gate in produced, f"{gate} has no producing workflow job named {gate!r}"
