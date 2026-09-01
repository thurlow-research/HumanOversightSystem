"""Regression guard for #972 / #1299: gate workflows must pin checkout to the
base SHA, and review-triggered re-evaluation must happen out-of-band via the
rerun-gate-checks dispatcher rather than a second trigger on the gates.

The three server-side gates (require-human-approval, require-tier-ceiling,
require-overseer-approval) trigger on pull_request_target ONLY. They used to
ALSO trigger on pull_request_review, where GITHUB_REF is the PR's MERGE ref
(base+head) — a bare `actions/checkout@v4` there would run the PR's own copy
of the gate script, making the gate self-bypassable (a worker PR could neuter
its own gate, then the pull_request_review run triggered by the overseer's
approval reports the neutered result as green). That second trigger also
produced a SECOND check run of the same job name, leaving a stale FAILURE from
the first run blocking merge even after an approval landed (#1299).

Review-triggered re-evaluation now happens via
.github/workflows/rerun-gate-checks.yml, which reruns each gate's EXISTING
workflow run in place (POST /actions/runs/{id}/rerun) instead of creating a
new check run. This file also guards the dispatcher's own security invariants
(same-repo-only, base-pinned checkout, no cancel-in-progress) and the
capability-containment property that it is the ONLY workflow with
`actions: write`.

These tests fail in the inner loop if a checkout step in one of these
workflows loses its explicit `ref: base.sha` pin, if a gate regains a
pull_request_review trigger, or if `actions: write` leaks to any workflow
other than the dispatcher.
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

_DISPATCHER_WORKFLOW = "rerun-gate-checks.yml"

_EXPECTED_REF = "${{ github.event.pull_request.base.sha }}"


def _load(workflow_file: str) -> dict:
    return yaml.safe_load((_WORKFLOWS_DIR / workflow_file).read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # YAML parses the bare `on:` key as the boolean True.
    return data.get(True) or data.get("on") or {}


def _checkout_steps(workflow_file: str):
    data = _load(workflow_file)
    for job in (data.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("uses", "").startswith("actions/checkout@"):
                yield step


def _has_actions_write(data: dict) -> bool:
    top = (data.get("permissions") or {})
    if top.get("actions") == "write":
        return True
    for job in (data.get("jobs") or {}).values():
        job_perms = (job or {}).get("permissions") or {}
        if job_perms.get("actions") == "write":
            return True
    return False


def test_gate_workflows_exist():
    for wf in _GATE_WORKFLOWS:
        assert (_WORKFLOWS_DIR / wf).is_file(), f"missing {wf}"


def test_gate_workflows_trigger_on_pull_request_target_only():
    """Gates trigger on pull_request_target only — NOT pull_request_review.

    A second trigger there produced a duplicate check run of the same job name
    (#1299): review-triggered re-evaluation now happens via the
    rerun-gate-checks dispatcher instead.
    """
    for wf in _GATE_WORKFLOWS:
        on = _on(_load(wf))
        assert "pull_request_target" in on, f"{wf} no longer triggers on pull_request_target"
        assert "pull_request_review" not in on, (
            f"{wf} regained a pull_request_review trigger — this produces a "
            "SECOND check run of the same job name instead of updating the "
            "existing one (#1299). Review-triggered re-evaluation belongs in "
            "rerun-gate-checks.yml, not here."
        )


def test_gate_checkout_pins_base_sha():
    """Every checkout step in a gate workflow must explicitly pin base.sha.

    Without this pin, a non-target trigger could check out the PR's own
    (possibly neutered) copy of the gate script — the #972 self-bypass.
    """
    for wf in _GATE_WORKFLOWS:
        steps = list(_checkout_steps(wf))
        assert steps, f"{wf} has no actions/checkout step"
        for step in steps:
            ref = (step.get("with") or {}).get("ref")
            assert ref == _EXPECTED_REF, (
                f"{wf}: checkout step must pin `ref: {_EXPECTED_REF}` "
                f"(found {ref!r}) — an unpinned checkout is self-bypassable "
                "under a non-target trigger (#972)"
            )


def test_dispatcher_workflow_exists():
    assert (_WORKFLOWS_DIR / _DISPATCHER_WORKFLOW).is_file(), f"missing {_DISPATCHER_WORKFLOW}"


def test_dispatcher_triggers_on_pull_request_review_only():
    on = _on(_load(_DISPATCHER_WORKFLOW))
    assert "pull_request_review" in on, f"{_DISPATCHER_WORKFLOW} must trigger on pull_request_review"
    review = on["pull_request_review"] or {}
    assert set(review.get("types") or []) == {"submitted", "dismissed"}
    assert "pull_request_target" not in on, (
        f"{_DISPATCHER_WORKFLOW} must not trigger on pull_request_target — "
        "it only reruns EXISTING gate workflow runs on review events"
    )
    assert "pull_request" not in on, (
        f"{_DISPATCHER_WORKFLOW} must not trigger on pull_request"
    )


def test_dispatcher_checkout_pins_base_and_no_credentials():
    steps = list(_checkout_steps(_DISPATCHER_WORKFLOW))
    assert steps, f"{_DISPATCHER_WORKFLOW} has no actions/checkout step"
    for step in steps:
        with_block = step.get("with") or {}
        assert with_block.get("ref") == _EXPECTED_REF, (
            f"{_DISPATCHER_WORKFLOW}: checkout must pin `ref: {_EXPECTED_REF}`"
        )
        assert with_block.get("persist-credentials") is False, (
            f"{_DISPATCHER_WORKFLOW}: checkout must set "
            "`persist-credentials: false` (actual YAML boolean, not a string) "
            "— this job holds `actions: write`"
        )


def test_actions_write_scoped_to_dispatcher_only():
    """Capability-containment regression guard: across ALL workflows, the set
    of files granting `actions: write` (top-level or job-level) must be
    exactly the dispatcher — nothing else in the repo may hold this token."""
    granting = set()
    for wf in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        if _has_actions_write(data):
            granting.add(wf.name)
    assert granting == {_DISPATCHER_WORKFLOW}, (
        f"`actions: write` must be granted to exactly {{'{_DISPATCHER_WORKFLOW}'}}, "
        f"found: {granting}"
    )


def test_gate_workflows_have_no_actions_write():
    for wf in _GATE_WORKFLOWS:
        data = _load(wf)
        assert not _has_actions_write(data), f"{wf} must not hold `actions: write`"


def test_dispatcher_concurrency_does_not_cancel_in_progress():
    data = _load(_DISPATCHER_WORKFLOW)
    concurrency = data.get("concurrency") or {}
    assert concurrency.get("cancel-in-progress") is False, (
        "cancel-in-progress must be the literal boolean false — cancelling a "
        "dispatcher mid-poll would leave a stale check run un-rerun (#795 / #1299)"
    )


def test_dispatcher_job_restricted_to_same_repo_prs():
    data = _load(_DISPATCHER_WORKFLOW)
    jobs = data.get("jobs") or {}
    job = jobs.get("rerun-gate-checks")
    assert job is not None, "rerun-gate-checks job not found"
    condition = job.get("if", "")
    assert "head.repo.full_name == github.repository" in condition, (
        "dispatcher job must be restricted to same-repo PRs so its "
        "`actions: write` token is never exercised on fork-authored PRs"
    )
