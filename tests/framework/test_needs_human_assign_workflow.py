"""Static pins for needs-human-assign.yml and the label-swap.yml glue (#2224)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ASSIGN_YML = WORKFLOWS / "needs-human-assign.yml"
LABEL_SWAP_YML = WORKFLOWS / "label-swap.yml"
SHIPPED = ROOT / "scripts" / "framework" / "framework_consumer_files.txt"

GLUE_PREFIX = (
    "python3 scripts/framework/next_actor.py reconcile-item "
    '--repo "$GITHUB_REPOSITORY" --number "$ISSUE_NUMBER" --ours \'github-actions[bot]\''
)
NUMBER_EXPR = "${{ github.event.issue.number || github.event.pull_request.number }}"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


DATA = load(ASSIGN_YML)
JOB = DATA["jobs"]["needs-human-assign"]


def test_triggers_exact():
    assert DATA[True] == {
        "issues": {"types": ["opened", "labeled", "unlabeled"]},
        "pull_request_target": {"types": ["opened", "labeled", "unlabeled"]},
    }


def test_job_if_filters_needs_human():
    cond = JOB["if"]
    assert "'needs-human'" in cond
    for action in ("labeled", "unlabeled", "opened"):
        assert f"github.event.action == '{action}'" in cond
    assert "github.event.label.name == 'needs-human'" in cond
    assert "contains(github.event.issue.labels.*.name, 'needs-human')" in cond
    assert "contains(github.event.pull_request.labels.*.name, 'needs-human')" in cond


def test_permissions_exact_and_no_job_permissions():
    assert DATA["permissions"] == {"contents": "read", "issues": "write", "pull-requests": "write"}
    assert "permissions" not in JOB


def test_concurrency_group_and_no_cancel():
    assert DATA["concurrency"] == {
        "group": (
            f"needs-human-assign-{NUMBER_EXPR}" "-${{ github.event.label.name || 'needs-human' }}"
        ),
        "cancel-in-progress": False,
    }


def test_single_checkout_pinned_default_branch_no_credentials():
    checkouts = [s for s in JOB["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkouts[0]["with"]["persist-credentials"] is False
    assert "sparse-checkout" not in checkouts[0]["with"]
    assert len(JOB["steps"]) == 2


def test_no_pr_head_or_merge_ref_in_step_values():
    blob = yaml.safe_dump(JOB["steps"])
    for banned in ("git fetch", "gh pr checkout", "head.sha", "head.ref", "refs/pull/"):
        assert banned not in blob


@pytest.mark.parametrize("name", ["needs-human-assign.yml", "label-swap.yml"])
def test_no_expression_inside_run(name):
    for job in load(WORKFLOWS / name)["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", "")


def test_env_keys_and_values_exact():
    assert JOB["steps"][1]["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
        "ITEM_NUMBER": NUMBER_EXPR,
    }


def test_run_command_exact():
    assert JOB["steps"][1]["run"].strip() == (
        'python3 scripts/framework/next_actor.py reconcile-item --repo "$REPO" '
        "--number \"$ITEM_NUMBER\" --ours 'github-actions[bot]'"
    )
    assert JOB["runs-on"] == "ubuntu-latest"
    assert JOB["timeout-minutes"] == 5


def test_no_other_workflow_writes_assignees():
    allowed = {"needs-human-assign.yml", "label-swap.yml"}
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for token in ("/assignees", "--add-assignee", "--remove-assignee", "--assignee"):
            assert token not in text, f"{path.name} contains {token}"
        assert ("next_actor.py" in text) == (path.name in allowed), path.name


def _branch_slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    return text[start : text.index(end_marker, start)]


def test_label_swap_calls_module_in_decline_and_handoff_best_effort():
    lines = LABEL_SWAP_YML.read_text(encoding="utf-8").splitlines()
    cases = [
        ('--remove-label "needs-human" --add-label "wontfix"', "/decline"),
        ('--remove-label "needs-ai" --add-label "needs-human"', "/handoff"),
    ]
    for edit, branch in cases:
        idx = [i for i, ln in enumerate(lines) if "gh issue edit" in ln and edit in ln]
        assert len(idx) == 1, branch
        glue = lines[idx[0] + 1].strip()
        assert glue.startswith(GLUE_PREFIX), branch
        assert glue.endswith(
            '|| echo "::warning::next_actor reconcile-item exited $?; assignment not updated"'
        )
        assert glue.count("||") == 1
    text = "\n".join(lines)
    assert text.count("next_actor.py") == 2
    decline_at = text.index("/approve|/decline)")
    handoff_at = text.index("/handoff)\n")
    first, second = (i for i, ln in enumerate(lines) if "next_actor.py" in ln)
    offsets = [sum(len(x) + 1 for x in lines[:i]) for i in (first, second)]
    assert decline_at < offsets[0] < handoff_at < offsets[1]


def test_label_swap_permissions_unchanged():
    assert load(LABEL_SWAP_YML)["permissions"] == {"contents": "read", "issues": "write"}


def test_not_shipped():
    listed = SHIPPED.read_text(encoding="utf-8")
    for name in ("needs-human-assign", "next_actor"):
        assert not re.search(name, listed)
