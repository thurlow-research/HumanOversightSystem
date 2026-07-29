"""Regression guard for #972: gate workflows must pin checkout to the base SHA.

The three server-side gates (require-human-approval, require-tier-ceiling,
require-overseer-approval) trigger on BOTH pull_request_target and
pull_request_review. Under pull_request_target, GITHUB_REF already defaults
to the base branch. But under pull_request_review, GITHUB_REF is the PR's
MERGE ref (base+head) — a bare `actions/checkout@v4` there would run the PR's
own copy of the gate script, making the gate self-bypassable (a worker PR
could neuter its own gate, then the pull_request_review run triggered by the
overseer's approval reports the neutered result as green).

These tests fail in the inner loop if a checkout step in one of these
workflows loses its explicit `ref: base.sha` pin.
"""
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

_GATE_WORKFLOWS = [
    "require-human-approval.yml",
    "require-tier-ceiling.yml",
    "require-overseer-approval.yml",
]

_EXPECTED_REF = "${{ github.event.pull_request.base.sha }}"


def _checkout_steps(workflow_file: str):
    data = yaml.safe_load((_WORKFLOWS_DIR / workflow_file).read_text(encoding="utf-8"))
    for job in (data.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("uses", "").startswith("actions/checkout@"):
                yield step


def test_gate_workflows_exist():
    for wf in _GATE_WORKFLOWS:
        assert (_WORKFLOWS_DIR / wf).is_file(), f"missing {wf}"


def test_gate_workflows_trigger_on_both_target_and_review():
    """Sanity check the premise: these gates re-run on pull_request_review."""
    for wf in _GATE_WORKFLOWS:
        data = yaml.safe_load((_WORKFLOWS_DIR / wf).read_text(encoding="utf-8"))
        on = data.get(True) or data.get("on") or {}
        assert "pull_request_target" in on, f"{wf} no longer triggers on pull_request_target"
        assert "pull_request_review" in on, f"{wf} no longer triggers on pull_request_review"


def test_gate_checkout_pins_base_sha():
    """Every checkout step in a gate workflow must explicitly pin base.sha.

    Without this pin, a pull_request_review-triggered run checks out the PR's
    merge ref instead of the trusted base, and executes the PR's own (possibly
    neutered) copy of the gate script — the exact self-bypass #972 describes.
    """
    for wf in _GATE_WORKFLOWS:
        steps = list(_checkout_steps(wf))
        assert steps, f"{wf} has no actions/checkout step"
        for step in steps:
            ref = (step.get("with") or {}).get("ref")
            assert ref == _EXPECTED_REF, (
                f"{wf}: checkout step must pin `ref: {_EXPECTED_REF}` "
                f"(found {ref!r}) — an unpinned checkout is self-bypassable "
                "under the pull_request_review trigger (#972)"
            )
