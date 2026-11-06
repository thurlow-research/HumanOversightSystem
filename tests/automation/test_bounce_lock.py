"""#2227: the bounce critical section is serialized under a per-(repo, cid) flock."""

from __future__ import annotations

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
    _bounce_lock,
    bounce_count,
    bounce_events,
    record_pr_bounce,
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
