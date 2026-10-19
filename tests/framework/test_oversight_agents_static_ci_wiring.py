"""Guard for #1606: check_agents_static.sh must run on every PR in CI.

The structural check cross-references file paths repo-wide, so the producing
job must exist, invoke the script, and the workflow must not path-filter PRs.
"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "oversight-gates.yml"
_JOB = "oversight-agents-static"


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_job_exists():
    assert _JOB in _load()["jobs"]


def test_job_runs_check_agents_static():
    steps = _load()["jobs"][_JOB]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert any("scripts/framework/check_agents_static.sh" in r for r in runs)


def test_pull_request_trigger_has_no_paths_filter():
    doc = _load()
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    triggers = doc["on"] if "on" in doc else doc[True]
    pr = triggers["pull_request"]
    assert "paths" not in pr
    assert "paths-ignore" not in pr
