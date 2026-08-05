"""Tests for the gate re-evaluation dispatcher (rerun_gate_checks.py, #1299).

Fully offline: no real `gh`/network calls. `_gh_api` is replaced with a fake
that matches on (method, path-substring) and returns a configured
(status, payload) per call; `_sleep` is replaced with a no-op recorder so no
test depends on wall-clock time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "framework" / "rerun_gate_checks.py"
_SPEC = importlib.util.spec_from_file_location("rerun_gate_checks", _MODULE_PATH)
rgc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rgc)


# ---------------------------------------------------------------------------
# Fake _gh_api / _sleep harness
# ---------------------------------------------------------------------------

class FakeApi:
    """Substitute for module-level _gh_api.

    `routes` maps a (method, path-substring) key to a list of (status,
    payload) tuples consumed in order; the last entry repeats once exhausted.
    Records every (method, path) call made, in order.
    """

    def __init__(self, routes: dict[tuple[str, str], list]):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, path: str, *, method: str = "GET"):
        self.calls.append((method, path))
        for (m, sub), responses in self.routes.items():
            if m == method and sub in path:
                if len(responses) > 1:
                    return responses.pop(0)
                return responses[0]
        raise AssertionError(f"no fake route for {method} {path}")


class RecordingSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeper(monkeypatch):
    rec = RecordingSleep()
    monkeypatch.setattr(rgc, "_sleep", rec)
    return rec


def _install_api(monkeypatch, routes: dict[tuple[str, str], list]) -> FakeApi:
    fake = FakeApi(routes)
    monkeypatch.setattr(rgc, "_gh_api", fake)
    return fake


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _check_run(id_, name, suite_id, status="completed", conclusion="failure"):
    return {
        "id": id_,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "check_suite": {"id": suite_id},
    }


def _list_payload(runs, total_count=None):
    return 200, {
        "total_count": total_count if total_count is not None else len(runs),
        "check_runs": runs,
    }


def _workflow_run(run_id, path, pull_requests=None):
    return {
        "id": run_id,
        "path": path,
        "pull_requests": pull_requests if pull_requests is not None else [],
    }


def _runs_payload(runs):
    return 200, {"workflow_runs": runs, "total_count": len(runs)}


_HA_PATH = rgc.GATE_WORKFLOWS["require-human-approval"]
_OA_PATH = rgc.GATE_WORKFLOWS["require-overseer-approval"]
_TC_PATH = rgc.GATE_WORKFLOWS["require-tier-ceiling"]


# ---------------------------------------------------------------------------
# 1. GATE_WORKFLOWS constants match real files / job names
# ---------------------------------------------------------------------------

def test_gate_workflow_paths_exist_and_names_match_job_name():
    for name, rel_path in rgc.GATE_WORKFLOWS.items():
        wf_file = _REPO_ROOT / rel_path
        assert wf_file.is_file(), f"{rel_path} does not exist"
        data = yaml.safe_load(wf_file.read_text(encoding="utf-8"))
        job_names = {(job or {}).get("name") for job in (data.get("jobs") or {}).values()}
        assert name in job_names, (
            f"GATE_WORKFLOWS key {name!r} does not match any job `name:` in {rel_path}"
        )


# ---------------------------------------------------------------------------
# 2. list_gate_check_runs request shape
# ---------------------------------------------------------------------------

def test_list_gate_check_runs_uses_filter_all_and_per_page_100(monkeypatch):
    fake = _install_api(monkeypatch, {
        ("GET", "check-runs"): [_list_payload([])],
    })
    rgc.list_gate_check_runs("o/r", "sha1")
    assert fake.calls
    method, path = fake.calls[0]
    assert method == "GET"
    assert "filter=all" in path
    assert "per_page=100" in path


# ---------------------------------------------------------------------------
# 3 / 4. resolve/dedupe -> distinct vs shared run ids
# ---------------------------------------------------------------------------

def test_two_check_runs_different_suites_resolve_to_two_posts(monkeypatch, sleeper):
    runs = [
        _check_run(1, "require-human-approval", suite_id=10),
        _check_run(2, "require-human-approval", suite_id=20),
    ]
    routes = {
        ("GET", "check-runs?"): [_list_payload(runs)],
        ("GET", "check-runs/1"): [(200, runs[0])],
        ("GET", "check-runs/2"): [(200, runs[1])],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("GET", "runs?check_suite_id=20"): [_runs_payload([_workflow_run(200, _HA_PATH)])],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/100"): [(200, {})],
        ("GET", "actions/runs/200"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert attempted == 2
    assert succeeded == 2
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 2


def test_two_check_runs_same_run_id_resolve_to_one_post(monkeypatch, sleeper):
    runs = [
        _check_run(1, "require-human-approval", suite_id=10),
        _check_run(2, "require-human-approval", suite_id=20),
    ]
    routes = {
        ("GET", "check-runs?"): [_list_payload(runs)],
        ("GET", "check-runs/1"): [(200, runs[0])],
        ("GET", "check-runs/2"): [(200, runs[1])],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(999, _HA_PATH)])],
        ("GET", "runs?check_suite_id=20"): [_runs_payload([_workflow_run(999, _HA_PATH)])],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/999"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert attempted == 1
    assert succeeded == 1
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 1


# ---------------------------------------------------------------------------
# 5. Non-gate check runs ignored
# ---------------------------------------------------------------------------

def test_non_gate_check_runs_ignored():
    runs = [
        {"id": 1, "name": "validation-check", "check_suite": {"id": 1}},
        {"id": 2, "name": "CodeQL", "check_suite": {"id": 2}},
    ]
    result = [r for r in runs if r.get("name") in rgc.GATE_NAMES]
    assert result == []


def test_non_gate_check_runs_ignored_end_to_end(monkeypatch, sleeper):
    """No gate-named check runs on head → falls back (per spec), and the
    fallback also finds nothing gate-relevant → zero POSTs either way."""
    runs = [
        {"id": 1, "name": "validation-check", "check_suite": {"id": 1}},
        {"id": 2, "name": "CodeQL", "check_suite": {"id": 2}},
    ]
    routes = {
        ("GET", "check-runs?"): [_list_payload(runs)],
        ("GET", "runs?event=pull_request_target"): [_runs_payload([])],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert attempted == 0
    assert succeeded == 0
    assert not any(c[0] == "POST" for c in fake.calls)


# ---------------------------------------------------------------------------
# 6 / 7. resolve_workflow_run_id path guards
# ---------------------------------------------------------------------------

def test_resolve_returns_none_when_path_not_in_gate_paths(monkeypatch):
    cr = _check_run(1, "require-human-approval", suite_id=10)
    routes = {
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, "some/other.yml")])],
    }
    fake = _install_api(monkeypatch, routes)
    result = rgc.resolve_workflow_run_id("o/r", cr)
    assert result is None
    assert not any(c[0] == "POST" for c in fake.calls)


def test_resolve_returns_none_on_path_mismatch_for_check_run_name(monkeypatch):
    """A run whose path IS a gate path but not the one expected for this
    check-run's name (name/path mismatch) is rejected too."""
    cr = _check_run(1, "require-human-approval", suite_id=10)
    routes = {
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _TC_PATH)])],
    }
    fake = _install_api(monkeypatch, routes)
    result = rgc.resolve_workflow_run_id("o/r", cr)
    assert result is None
    assert not any(c[0] == "POST" for c in fake.calls)


# ---------------------------------------------------------------------------
# 8 / 9. wait_for_completion polling
# ---------------------------------------------------------------------------

def test_wait_for_completion_second_poll_completes(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs/5"): [
            (200, {"id": 5, "status": "in_progress"}),
            (200, {"id": 5, "status": "completed", "name": "require-human-approval", "check_suite": {"id": 1}}),
        ],
    }
    fake = _install_api(monkeypatch, routes)
    result = rgc.wait_for_completion("o/r", 5)
    assert result is not None
    assert result["status"] == "completed"
    gets = [c for c in fake.calls if c[0] == "GET"]
    assert len(gets) == 2
    assert len(sleeper.calls) == 1


def test_wait_for_completion_always_in_progress_exhausts_budget(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs/5"): [(200, {"id": 5, "status": "in_progress"})],
    }
    fake = _install_api(monkeypatch, routes)
    result = rgc.wait_for_completion("o/r", 5)
    assert result is None
    gets = [c for c in fake.calls if c[0] == "GET"]
    assert len(gets) == rgc.POLL_ATTEMPTS
    assert len(sleeper.calls) == rgc.POLL_ATTEMPTS - 1


# ---------------------------------------------------------------------------
# 10 / 11 / 12. rerun_workflow_run retry semantics
# ---------------------------------------------------------------------------

def test_rerun_403_then_201(monkeypatch, sleeper):
    routes = {
        ("POST", "/rerun"): [(403, None), (201, None)],
        ("GET", "actions/runs/1"): [(200, {})],
    }
    fake = _install_api(monkeypatch, routes)
    ok = rgc.rerun_workflow_run("o/r", 1)
    assert ok is True
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 2
    assert sleeper.calls == [rgc.RERUN_BACKOFF_SECONDS[0]]


def test_rerun_403_every_attempt_fails(monkeypatch, sleeper):
    routes = {
        ("POST", "/rerun"): [(403, None)] * rgc.RERUN_ATTEMPTS,
    }
    fake = _install_api(monkeypatch, routes)
    ok = rgc.rerun_workflow_run("o/r", 1)
    assert ok is False
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == rgc.RERUN_ATTEMPTS
    assert sleeper.calls == list(rgc.RERUN_BACKOFF_SECONDS)


def test_rerun_403_every_attempt_main_still_returns_0(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs?"): [_list_payload([_check_run(1, "require-human-approval", suite_id=10)])],
        ("GET", "check-runs/1"): [(200, _check_run(1, "require-human-approval", suite_id=10))],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("POST", "/rerun"): [(403, None)] * rgc.RERUN_ATTEMPTS,
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    _install_api(monkeypatch, routes)
    monkeypatch.setattr(
        sys, "argv",
        ["rerun_gate_checks.py", "--pr", "7", "--head-sha", "sha1",
         "--event-action", "submitted", "--review-state", "APPROVED", "--repo", "o/r"],
    )
    assert rgc.main() == 0


def test_rerun_404_no_retry(monkeypatch, sleeper):
    routes = {("POST", "/rerun"): [(404, None)]}
    fake = _install_api(monkeypatch, routes)
    ok = rgc.rerun_workflow_run("o/r", 1)
    assert ok is False
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 1
    assert sleeper.calls == []


# ---------------------------------------------------------------------------
# 13 / 14. dismissed / submitted regardless of prior conclusion
# ---------------------------------------------------------------------------

def test_dismissed_with_success_conclusion_still_reruns(monkeypatch, sleeper):
    cr = _check_run(1, "require-human-approval", suite_id=10, conclusion="success")
    routes = {
        ("GET", "check-runs?"): [_list_payload([cr])],
        ("GET", "check-runs/1"): [(200, cr)],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/100"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    assert rgc.should_dispatch("dismissed", "APPROVED") is True
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert (attempted, succeeded) == (1, 1)
    assert any(c[0] == "POST" for c in fake.calls)


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", "timed_out", "neutral"])
def test_submitted_reruns_regardless_of_prior_conclusion(monkeypatch, sleeper, conclusion):
    cr = _check_run(1, "require-human-approval", suite_id=10, conclusion=conclusion)
    routes = {
        ("GET", "check-runs?"): [_list_payload([cr])],
        ("GET", "check-runs/1"): [(200, cr)],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/100"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    _install_api(monkeypatch, routes)
    assert rgc.should_dispatch("submitted", "APPROVED") is True
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert (attempted, succeeded) == (1, 1)


# ---------------------------------------------------------------------------
# 15 / 16. should_dispatch
# ---------------------------------------------------------------------------

def test_should_dispatch_commented_submitted_false():
    assert rgc.should_dispatch("submitted", "COMMENTED") is False


def test_should_dispatch_commented_submitted_end_to_end_no_api_calls(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no API call should happen")
    monkeypatch.setattr(rgc, "_gh_api", _boom)
    monkeypatch.setattr(
        sys, "argv",
        ["rerun_gate_checks.py", "--pr", "7", "--head-sha", "sha1",
         "--event-action", "submitted", "--review-state", "COMMENTED", "--repo", "o/r"],
    )
    assert rgc.main() == 0


def test_should_dispatch_dismissed_true_regardless_of_state():
    assert rgc.should_dispatch("dismissed", "COMMENTED") is True
    assert rgc.should_dispatch("dismissed", "APPROVED") is True


# ---------------------------------------------------------------------------
# 17. moved-head abort
# ---------------------------------------------------------------------------

def test_moved_head_aborts_before_any_post(monkeypatch, sleeper):
    cr = _check_run(1, "require-human-approval", suite_id=10)
    routes = {
        ("GET", "check-runs?"): [_list_payload([cr])],
        ("GET", "check-runs/1"): [(200, cr)],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha-NEW"}})],
    }
    fake = _install_api(monkeypatch, routes)
    result = rgc.process_pull_request("o/r", 7, "sha-OLD")
    assert result == (0, 0)
    assert not any(c[0] == "POST" for c in fake.calls)


# ---------------------------------------------------------------------------
# 18 / 19 / 20. fallback path
# ---------------------------------------------------------------------------

def test_zero_head_check_runs_uses_fallback(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs?"): [_list_payload([])],
        ("GET", "runs?event=pull_request_target"): [
            _runs_payload([_workflow_run(500, _HA_PATH, pull_requests=[{"number": 7}])])
        ],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/500"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert (attempted, succeeded) == (1, 1)
    assert any(c[0] == "GET" and "event=pull_request_target" in c[1] for c in fake.calls)


def test_fallback_ignores_other_pr_and_empty_pull_requests(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs?"): [_list_payload([])],
        ("GET", "runs?event=pull_request_target"): [
            _runs_payload([
                _workflow_run(501, _HA_PATH, pull_requests=[{"number": 999}]),  # different PR
                _workflow_run(502, _OA_PATH, pull_requests=[]),  # empty list
            ])
        ],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert (attempted, succeeded) == (0, 0)
    assert not any(c[0] == "POST" for c in fake.calls)


def test_fallback_not_called_when_head_check_runs_found(monkeypatch, sleeper):
    cr = _check_run(1, "require-human-approval", suite_id=10)
    routes = {
        ("GET", "check-runs?"): [_list_payload([cr])],
        ("GET", "check-runs/1"): [(200, cr)],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("POST", "/rerun"): [(201, None)],
        ("GET", "actions/runs/100"): [(200, {})],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    rgc.process_pull_request("o/r", 7, "sha1")
    assert not any("event=pull_request_target" in c[1] for c in fake.calls)


# ---------------------------------------------------------------------------
# 21. dry-run
# ---------------------------------------------------------------------------

def test_dry_run_makes_zero_posts(monkeypatch, sleeper):
    cr = _check_run(1, "require-human-approval", suite_id=10)
    routes = {
        ("GET", "check-runs?"): [_list_payload([cr])],
        ("GET", "check-runs/1"): [(200, cr)],
        ("GET", "runs?check_suite_id=10"): [_runs_payload([_workflow_run(100, _HA_PATH)])],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1", dry_run=True)
    assert attempted == 1
    assert succeeded == 1
    assert not any(c[0] == "POST" for c in fake.calls)


# ---------------------------------------------------------------------------
# 22. missing --repo
# ---------------------------------------------------------------------------

def test_missing_repo_returns_2(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["rerun_gate_checks.py", "--pr", "7", "--head-sha", "sha1",
         "--event-action", "submitted", "--review-state", "APPROVED"],
    )
    assert rgc.main() == 2


# ---------------------------------------------------------------------------
# 23. GhUnavailable
# ---------------------------------------------------------------------------

def test_gh_unavailable_returns_2(monkeypatch):
    def _boom(*a, **k):
        raise rgc.GhUnavailable("gh not found on PATH")
    monkeypatch.setattr(rgc, "_gh_api", _boom)
    monkeypatch.setattr(
        sys, "argv",
        ["rerun_gate_checks.py", "--pr", "7", "--head-sha", "sha1",
         "--event-action", "submitted", "--review-state", "APPROVED", "--repo", "o/r"],
    )
    assert rgc.main() == 2


# ---------------------------------------------------------------------------
# 24. no gate check runs, fallback also empty
# ---------------------------------------------------------------------------

def test_no_gate_runs_and_empty_fallback_main_returns_0(monkeypatch, sleeper):
    routes = {
        ("GET", "check-runs?"): [_list_payload([])],
        ("GET", "runs?event=pull_request_target"): [_runs_payload([])],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    _install_api(monkeypatch, routes)
    monkeypatch.setattr(
        sys, "argv",
        ["rerun_gate_checks.py", "--pr", "7", "--head-sha", "sha1",
         "--event-action", "submitted", "--review-state", "APPROVED", "--repo", "o/r"],
    )
    assert rgc.main() == 0


# ---------------------------------------------------------------------------
# 25. dispatcher's own job name is not a gate name (no-recursion sanity check)
# ---------------------------------------------------------------------------

def test_dispatcher_own_job_name_not_a_gate_name():
    assert "rerun-gate-checks" not in rgc.GATE_NAMES


def test_dispatcher_own_check_run_ignored_end_to_end(monkeypatch, sleeper):
    runs = [{"id": 1, "name": "rerun-gate-checks", "check_suite": {"id": 1}}]
    routes = {
        ("GET", "check-runs?"): [_list_payload(runs)],
        ("GET", "runs?event=pull_request_target"): [_runs_payload([])],
        ("GET", "pulls/7"): [(200, {"head": {"sha": "sha1"}})],
    }
    fake = _install_api(monkeypatch, routes)
    attempted, succeeded = rgc.process_pull_request("o/r", 7, "sha1")
    assert (attempted, succeeded) == (0, 0)
    assert not any(c[0] == "POST" for c in fake.calls)


# ---------------------------------------------------------------------------
# _gh_api status-line parsing / GhUnavailable
# ---------------------------------------------------------------------------

def test_gh_api_raises_gh_unavailable_when_gh_missing(monkeypatch):
    def _fake_run(*a, **k):
        raise FileNotFoundError("gh not found")
    monkeypatch.setattr(rgc.subprocess, "run", _fake_run)
    with pytest.raises(rgc.GhUnavailable):
        rgc._gh_api("repos/o/r/pulls/1")


def test_gh_api_unparseable_status_returns_zero_and_warns(monkeypatch, capsys):
    class _FakeProc:
        stdout = "not a valid http response\n\nsome body"
        stderr = "gh: something went wrong"

    monkeypatch.setattr(rgc.subprocess, "run", lambda *a, **k: _FakeProc())
    status, payload = rgc._gh_api("repos/o/r/pulls/1")
    assert status == 0
    assert payload is None
    captured = capsys.readouterr()
    assert "::warning::" in captured.err
