"""Guards for the #2053 (Option A) replacement of the validation-stamp check.

The "Validation stamps current" job (validation-check.yml ->
check_validation_current.sh) is retired. agent-static-check.yml runs
check_agents_static.sh directly on the PR head, as a NON-required, HOS-internal
check, and a clean static run no longer writes a phase1 stamp.
"""

import yaml

# Private helpers are reused deliberately so the fixtures and context parsing stay
# identical to the static-check and branch-protection suites.
from tests.framework.test_branch_protection_contexts import _core_contexts, _hos_only_contexts
from tests.framework.test_check_agents_static_dated_model_ids import _run, _scaffold
from tests.framework.test_consumer_framework_files import LIST, ROOT

WORKFLOW = ROOT / ".github" / "workflows" / "agent-static-check.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_stamp_check_artifacts_are_gone():
    assert not (ROOT / ".github" / "workflows" / "validation-check.yml").exists()
    assert not (ROOT / "scripts" / "framework" / "check_validation_current.sh").exists()


def test_workflow_runs_static_check_without_stamps():
    # Parsed YAML, not raw text: the header comment legitimately names the
    # retired stamp check it replaced.
    wf = _workflow()
    steps = wf["jobs"]["agent-static-check"]["steps"]
    assert "bash scripts/framework/check_agents_static.sh" in [s.get("run") for s in steps]


def test_workflow_is_not_shipped_to_consumers():
    listed = [ln.split("#", 1)[0].strip() for ln in LIST.read_text().splitlines()]
    assert ".github/workflows/agent-static-check.yml" not in listed
    assert ".github/workflows/validation-check.yml" not in listed


def test_job_is_not_a_required_context():
    wf = _workflow()
    job = wf["jobs"]["agent-static-check"]
    required = set(_core_contexts()) | set(_hos_only_contexts())
    assert job["name"] not in required
    assert "agent-static-check" not in required


def test_clean_static_run_writes_no_stamp(tmp_path):
    _scaffold(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "scripts" / "framework" / "validation-stamps").exists()
    assert not list(tmp_path.rglob("*.stamp"))


def test_trigger_has_no_paths_filter():
    # Check 3 can fail on a deletion anywhere in the repo, so no path filter.
    # PyYAML parses the bare key `on` as boolean True.
    wf = _workflow()
    trigger = (wf.get("on") or wf[True])["pull_request"]
    assert trigger["branches"] == ["main"]
    assert "paths" not in trigger
    assert "paths-ignore" not in trigger
