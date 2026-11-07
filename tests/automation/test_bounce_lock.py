"""#2227: the bounce critical section is serialized under a per-(repo, cid) flock."""

from __future__ import annotations

import errno
import fcntl
import os
import threading
import time
from unittest.mock import patch

import pytest

from scripts.automation.lib.github import GitHubError
from scripts.automation.lib.merge_authority import (
    BOUNCE_CAP,
    BounceLockTimeout,
    BounceLockUnavailable,
    RepairReadError,
    _bounce_lock,
    bounce_count,
    bounce_events,
    record_pr_bounce,
    repair_bounce_finalize,
)
from tests.automation.test_bounce_gate import HEAD, MA, OWNER, REPO, _f, _gh_stub, _post


def _call(tmp_path, findings, results, **kw):
    try:
        results.append(
            record_pr_bounce(
                OWNER,
                REPO,
                123,
                cid="cid-1",
                reason_category="MERITS_FINDING",
                summary="s",
                repo_root=str(tmp_path),
                head_sha=HEAD,
                findings=findings,
                **kw,
            )
        )
    except Exception as exc:  # surfaced by the test body
        results.append(exc)


def _slow_post(bodies, delay=0.3):
    inner = _post(bodies)

    def fake(*a, **k):
        time.sleep(delay)
        return inner(*a, **k)

    return fake


def _run_two(tmp_path, first, second, **kw):
    results: list = []
    threads = [
        threading.Thread(target=_call, args=(tmp_path, f, results), kwargs=kw)
        for f in (first, second)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 2 and not any(isinstance(r, Exception) for r in results), results
    return results


def test_concurrent_same_findings_post_once(tmp_path):
    bodies: list = []
    findings = [_f()]
    with (
        patch(f"{MA}.post_comment", side_effect=_slow_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        results = _run_two(tmp_path, findings, findings)
    assert len(bodies) == 1
    assert len(bounce_events("cid-1", repo_root=str(tmp_path))) == 1
    assert sorted(r.skipped for r in results) == [False, True]


def test_concurrent_different_findings_at_cap_minus_one_post_once(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_slow_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        # One earlier bounce (another head) leaves the budget at cap - 1.
        first = []
        _call(tmp_path, [_f(key="MERITS:z.py:z", path="z.py")], first)
        assert not isinstance(first[0], Exception), first
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == BOUNCE_CAP - 1
        del bodies[:]
        results = _run_two(
            tmp_path,
            [_f(key="MERITS:a.py:a", path="a.py")],
            [_f(key="MERITS:b.py:b", path="b.py")],
            cap=BOUNCE_CAP,
            epoch_since=None,
        )
    assert len(bodies) == 1
    assert sorted(r.at_cap for r in results) == [False, True]
    assert bounce_count("cid-1", repo_root=str(tmp_path)) == BOUNCE_CAP


def _hold(tmp_path):
    from hashlib import sha256

    digest = sha256(f"{OWNER}/{REPO}\0cid-1".encode()).hexdigest()[:24]
    path = tmp_path / ".claudetmp" / "locks" / f"bounce-{digest}.lock"
    return path


def test_lock_file_modes_and_timeout(tmp_path):
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
        path = _hold(tmp_path)
        assert path.exists() and (path.stat().st_mode & 0o777) == 0o600
        assert (path.parent.stat().st_mode & 0o777) == 0o700
        with pytest.raises(BounceLockTimeout):
            with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
                pass
    # a different cid is not blocked
    with _bounce_lock(OWNER, REPO, "cid-2", repo_root=str(tmp_path), timeout=0.2):
        pass


def test_record_pr_bounce_times_out_without_posting(tmp_path):
    bodies: list = []
    real = _bounce_lock

    def quick(*a, **k):
        k["timeout"] = 0.2
        return real(*a, **k)

    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
        with (
            patch(f"{MA}.post_comment", side_effect=_post(bodies)),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._bounce_lock", side_effect=quick),
        ):
            results: list = []
            _call(tmp_path, [_f()], results)
    assert isinstance(results[0], BounceLockTimeout)
    assert not isinstance(results[0], GitHubError)
    assert bodies == []
    assert bounce_events("cid-1", repo_root=str(tmp_path)) == []


def test_lock_is_released_after_an_exception_in_the_section(tmp_path):
    with (
        patch(f"{MA}.post_comment", side_effect=GitHubError("boom", status_code=500)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
    ):
        results: list = []
        _call(tmp_path, [_f()], results)
    assert isinstance(results[0], GitHubError)
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
        pass


def test_lock_released_and_fd_closed_on_normal_exit(tmp_path):
    before = len(os.listdir("/proc/self/fd"))
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
        pass
    assert len(os.listdir("/proc/self/fd")) == before
    fd = os.open(_hold(tmp_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def test_cap_none_keeps_existing_behavior(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        results = _run_two(
            tmp_path, [_f(key="MERITS:a.py:a", path="a.py")], [_f(key="MERITS:b.py:b", path="b.py")]
        )
    assert len(bodies) == 2 and not any(r.at_cap for r in results)


def test_in_lock_dedup_numbers_and_keys_only_the_fresh_findings(tmp_path):
    bodies: list = []
    a = _f(key="MERITS:a.py:a", path="a.py")
    b = _f(key="MERITS:b.py:b", path="b.py")
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        first: list = []
        _call(tmp_path, [a], first)
        second: list = []
        _call(tmp_path, [a, b], second)
    result = second[0]
    assert len(bodies) == 2
    assert result.finding_keys == [b.key]
    assert result.finding_ids == [f"{HEAD[:12]}-F2"]
    assert f"{HEAD[:12]}-F2" in bodies[1] and f"{HEAD[:12]}-F1" not in bodies[1]


def _quick_lock(timeout=0.2):
    real = _bounce_lock

    def quick(*a, **k):
        k["timeout"] = timeout
        return real(*a, **k)

    return quick


def test_repair_bounce_finalize_times_out_before_any_read_or_write(tmp_path):
    calls: list = []
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
        with (
            patch(f"{MA}._run_gh", side_effect=_gh_stub(calls=calls)),
            patch(f"{MA}._add_label") as add_label,
            patch(f"{MA}._convert_pr_to_draft") as to_draft,
            patch(f"{MA}._bounce_lock", side_effect=_quick_lock()),
        ):
            with pytest.raises(BounceLockTimeout):
                repair_bounce_finalize(
                    OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path)
                )
    assert calls == []
    add_label.assert_not_called()
    to_draft.assert_not_called()


def test_repair_bounce_finalize_holds_the_lock_while_it_runs(tmp_path):
    seen: list = []

    def probe(args, *a, **k):
        # While repair runs, another acquirer must time out.
        try:
            with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
                seen.append("acquired")
        except BounceLockTimeout:
            seen.append("blocked")
        return {"draft": True, "labels": [{"name": "needs-ai"}]}

    with patch(f"{MA}._run_gh", side_effect=probe):
        assert (
            repair_bounce_finalize(
                OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path)
            )
            == []
        )
    assert seen == ["blocked"]
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
        pass


def _legacy(tmp_path, results, failures, **kw):
    try:
        results.append(
            record_pr_bounce(
                OWNER,
                REPO,
                123,
                cid="cid-1",
                reason_category="MERITS_FINDING",
                summary="s",
                repo_root=str(tmp_path),
                head_sha=HEAD,
                failures=failures,
                **kw,
            )
        )
    except Exception as exc:
        results.append(exc)


def test_legacy_failures_path_at_cap_posts_and_writes_nothing(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft") as to_draft,
    ):
        first: list = []
        _legacy(tmp_path, first, ["tok-a"])
        assert first[0].skipped is False
        del bodies[:]
        second: list = []
        _legacy(tmp_path, second, ["tok-b"], cap=1)
    result = second[0]
    assert result.skipped and result.at_cap
    assert result.comment_url is None and result.bounce_number == 1
    assert bodies == []
    assert len(bounce_events("cid-1", repo_root=str(tmp_path))) == 1
    assert to_draft.call_count == 1  # only the first bounce finalized


def test_legacy_failures_path_below_cap_still_posts(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        results: list = []
        _legacy(tmp_path, results, ["tok-a"], cap=1)
    assert results[0].at_cap is False and results[0].bounce_number == 1
    assert len(bodies) == 1


def test_legacy_repeat_failures_are_skipped_not_at_cap_even_when_cap_reached(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        _legacy(tmp_path, [], ["tok-a"])
        second: list = []
        _legacy(tmp_path, second, ["tok-a"], cap=1)
    assert second[0].skipped is True and second[0].at_cap is False
    assert len(bodies) == 1


def test_empty_findings_is_not_treated_as_a_repeat(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        results: list = []
        _call(tmp_path, [], results)
    result = results[0]
    assert not isinstance(result, Exception), result
    assert result.skipped is False
    assert result.finding_ids == [] and result.finding_keys == []
    assert len(bodies) == 1
    events = bounce_events("cid-1", repo_root=str(tmp_path))
    assert len(events) == 1 and events[0]["failures"] == [] and events[0]["findings"] == []


def test_empty_findings_still_respects_cap(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        _call(tmp_path, [_f()], [])
        del bodies[:]
        results: list = []
        _call(tmp_path, [], results, cap=1)
    assert results[0].at_cap is True and bodies == []


def test_lock_file_open_oserror_becomes_lock_unavailable_before_any_write(tmp_path):
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}.os.open", side_effect=PermissionError(13, "denied")),
    ):
        results: list = []
        _call(tmp_path, [_f()], results)
    assert isinstance(results[0], BounceLockUnavailable)
    assert isinstance(results[0].__cause__, PermissionError)
    assert "bounce-" in str(results[0]) and "13" in str(results[0])
    assert not isinstance(results[0], BounceLockTimeout)
    assert bodies == []
    assert bounce_events("cid-1", repo_root=str(tmp_path)) == []


def test_lock_dir_uncreatable_oserror_becomes_lock_unavailable(tmp_path):
    (tmp_path / ".claudetmp").write_text("a file, not a directory")
    with pytest.raises(BounceLockUnavailable) as info:
        with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
            pytest.fail("must not enter the critical section")
    assert isinstance(info.value.__cause__, OSError)


def test_flock_oserror_other_than_contention_closes_fd_and_is_lock_unavailable(tmp_path):
    before = len(os.listdir("/proc/self/fd"))
    with patch(f"{MA}.fcntl.flock", side_effect=OSError(errno.ENOLCK, "no locks")):
        with pytest.raises(BounceLockUnavailable) as info:
            with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path)):
                pytest.fail("must not enter the critical section")
    assert isinstance(info.value.__cause__, OSError)
    assert not isinstance(info.value, BounceLockTimeout)
    assert len(os.listdir("/proc/self/fd")) == before


def test_repair_read_failures_raise_before_any_write_under_the_lock(tmp_path):
    with (
        patch(f"{MA}._run_gh", side_effect=GitHubError("down", status_code=502)),
        patch(f"{MA}._add_label") as add_label,
    ):
        with pytest.raises(RepairReadError):
            repair_bounce_finalize(
                OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path)
            )
    with patch(f"{MA}._run_gh", return_value=None), patch(f"{MA}._add_label") as add_label:
        with pytest.raises(RepairReadError):
            repair_bounce_finalize(
                OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path)
            )
    add_label.assert_not_called()
    with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
        pass


def test_repair_write_failures_are_collected_not_raised(tmp_path):
    errors: list = []
    with (
        patch(f"{MA}._run_gh", return_value={"draft": False, "labels": []}),
        patch(f"{MA}._github.list_issue_events", return_value=[]),
        patch(f"{MA}._add_label", side_effect=GitHubError("l", status_code=500)),
        patch(f"{MA}._convert_pr_to_draft", side_effect=GitHubError("d", status_code=500)),
    ):
        repaired = repair_bounce_finalize(
            OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path), errors=errors
        )
    assert repaired == []
    assert len(errors) == 2 and errors[0].startswith("label failed")
    assert errors[1].startswith("convert-to-draft failed")


def test_repeat_bounce_repairs_unfinished_finalize_under_one_lock(tmp_path):
    bodies: list = []
    findings = [_f()]
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub(draft=True, labels=("needs-ai",))),
        patch(f"{MA}._convert_pr_to_draft"),
    ):
        _call(tmp_path, findings, [])
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub(draft=False, labels=())),
        patch(f"{MA}._github.list_issue_events", return_value=[]),
        patch(f"{MA}._add_label") as add_label,
        patch(f"{MA}._convert_pr_to_draft") as to_draft,
    ):
        results: list = []
        _call(tmp_path, findings, results)
    assert results[0].skipped and not results[0].at_cap
    assert sorted(results[0].finalize_repaired) == ["draft", "label"]
    add_label.assert_called_once()
    to_draft.assert_called_once()
    assert len(bodies) == 1


def test_finalize_failures_after_the_lock_are_recorded_not_raised(tmp_path):
    with (
        patch(f"{MA}.post_comment", side_effect=_post([])),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._add_label", side_effect=GitHubError("l", status_code=500)),
        patch(f"{MA}._convert_pr_to_draft", side_effect=GitHubError("d", status_code=500)),
    ):
        results: list = []
        _call(tmp_path, [_f()], results)
        # the lock was already released when finalize ran
        with _bounce_lock(OWNER, REPO, "cid-1", repo_root=str(tmp_path), timeout=0.2):
            pass
    assert len(results[0].finalize_errors) == 2
    assert len(bounce_events("cid-1", repo_root=str(tmp_path))) == 1


def test_findings_with_failures_or_without_head_are_rejected(tmp_path):
    kw = dict(cid="cid-1", reason_category="MERITS_FINDING", summary="s", repo_root=str(tmp_path))
    with pytest.raises(ValueError):
        record_pr_bounce(OWNER, REPO, 1, findings=[_f()], failures=["x"], head_sha=HEAD, **kw)
    with pytest.raises(ValueError):
        record_pr_bounce(OWNER, REPO, 1, findings=[_f()], **kw)
    with pytest.raises(ValueError):
        record_pr_bounce(OWNER, REPO, 1, **{**kw, "reason_category": "BOGUS"})
    assert not (tmp_path / ".claudetmp" / "locks").exists()


# --- #2263 residual 1: lock errno classification ---------------------------------


def _unavailable(code):
    exc = BounceLockUnavailable("x")
    exc.__cause__ = OSError(code, os.strerror(code)) if code is not None else None
    return exc


@pytest.mark.parametrize("code", [errno.EINTR, errno.EAGAIN, errno.ENOLCK, errno.EMFILE])
def test_lock_unavailable_transient_errnos(code):
    assert _unavailable(code).classification == "transient"
    assert _unavailable(code).errno == code


@pytest.mark.parametrize("code", [errno.EACCES, errno.EROFS, errno.ENOTDIR, errno.EPERM])
def test_lock_unavailable_persistent_errnos_are_deterministic(code):
    assert _unavailable(code).classification == "deterministic"


def test_lock_unavailable_without_a_cause_or_errno_is_deterministic():
    assert BounceLockUnavailable("x").classification == "deterministic"
    assert BounceLockUnavailable("x").errno is None
    assert _unavailable(None).classification == "deterministic"
    exc = BounceLockUnavailable("x")
    exc.__cause__ = OSError("no errno")
    assert exc.classification == "deterministic"


# --- #2263 residual 3: retry after an audit-write failure -------------------------

BOT = "hos-overseer[bot]"


def _comment(cid_id, body, login=BOT):
    return {
        "id": cid_id,
        "body": body,
        "user": {"login": login},
        "html_url": f"https://example/pr/123#comment-{cid_id}",
        "created_at": "2026-10-31T02:00:00Z",
    }


def _audit_failing_once():
    from scripts.automation.lib import merge_authority as ma

    real = ma._AUDIT_LOG.write_event
    state = {"n": 0}

    def fake(event, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("disk full")
        return real(event, **k)

    return fake


def test_retry_after_audit_write_failure_adopts_the_posted_comment(tmp_path, monkeypatch):
    from scripts.automation.lib.merge_authority import BounceAuditWriteError

    monkeypatch.setenv("HOS_BOT_LOGIN", BOT)
    bodies: list = []
    posted: list = []

    def post(owner, repo, number, body, **k):
        posted.append(_comment(900 + len(posted), body))
        return _post(bodies)(owner, repo, number, body, **k) | {"id": 900 + len(posted) - 1}

    with (
        patch(f"{MA}.post_comment", side_effect=post),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
        patch(f"{MA}._github.list_issue_comments", side_effect=lambda *a, **k: list(posted)),
        patch(f"{MA}._AUDIT_LOG.write_event", side_effect=_audit_failing_once()),
    ):
        first: list = []
        _call(tmp_path, [_f()], first)
        assert isinstance(first[0], BounceAuditWriteError)
        assert bounce_events("cid-1", repo_root=str(tmp_path)) == []
        second: list = []
        _call(tmp_path, [_f()], second)
    assert len(posted) == 1
    result = second[0]
    assert not isinstance(result, Exception), result
    assert result.comment_url == "https://example/pr/123#comment-900"
    events = bounce_events("cid-1", repo_root=str(tmp_path))
    assert len(events) == 1 and events[0]["comment_id"] == 900
    assert events[0]["bounce_number"] == 1


def test_comment_read_failure_raises_before_posting(tmp_path, monkeypatch):
    monkeypatch.setenv("HOS_BOT_LOGIN", BOT)
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._github.list_issue_comments", side_effect=GitHubError("boom")),
    ):
        results: list = []
        _call(tmp_path, [_f()], results)
    assert isinstance(results[0], GitHubError)
    assert bodies == []
    assert bounce_events("cid-1", repo_root=str(tmp_path)) == []


def test_marker_for_different_keys_does_not_suppress_posting(tmp_path, monkeypatch):
    from scripts.automation.lib.merge_authority import _bounce_marker

    monkeypatch.setenv("HOS_BOT_LOGIN", BOT)
    other = _comment(7, "x\n" + _bounce_marker("cid-1", HEAD, ["MERITS:other"]) + "\n")
    bodies: list = []
    with (
        patch(f"{MA}.post_comment", side_effect=_post(bodies)),
        patch(f"{MA}._run_gh", side_effect=_gh_stub()),
        patch(f"{MA}._convert_pr_to_draft"),
        patch(f"{MA}._github.list_issue_comments", return_value=[other]),
    ):
        results: list = []
        _call(tmp_path, [_f()], results)
    assert len(bodies) == 1 and not isinstance(results[0], Exception)


def test_marker_from_another_author_or_without_bot_login_is_not_adopted(tmp_path, monkeypatch):
    from scripts.automation.lib.merge_authority import _bounce_marker

    marker = _bounce_marker("cid-1", HEAD, [_f().key])
    forged = _comment(7, marker + "\n", login="someone-else")
    bodies: list = []
    for login in (BOT, None):
        if login:
            monkeypatch.setenv("HOS_BOT_LOGIN", login)
        else:
            monkeypatch.delenv("HOS_BOT_LOGIN", raising=False)
        with (
            patch(f"{MA}.post_comment", side_effect=_post(bodies)),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
            patch(f"{MA}._github.list_issue_comments", return_value=[forged]),
        ):
            _call(tmp_path / (login or "none"), [_f()], [])
    assert len(bodies) == 2


def test_marker_is_in_both_body_forms_and_is_injection_safe():
    from scripts.automation.lib.merge_authority import (
        _bounce_comment_body,
        _bounce_comment_body_findings,
        _bounce_marker,
    )

    marker = _bounce_marker("cid --> <x>", HEAD, ["b", "a"])
    assert marker == _bounce_marker("cid --> <x>", HEAD, ["a", "b"])
    assert marker != _bounce_marker("cid --> <x>", HEAD, ["a"])
    assert marker.count("-->") == 1 and "cid" not in marker
    legacy = _bounce_comment_body(["register-missing"], "REGISTER_GAP", "s", 1, marker=marker)
    findings = _bounce_comment_body_findings(
        [("F1", _f())], "MERITS_FINDING", "s", 1, cid="cid-1", head_sha=HEAD, marker=marker
    )
    assert marker in legacy.splitlines() and marker in findings.splitlines()
