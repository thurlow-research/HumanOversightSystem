"""Tests for scripts/framework/next_actor.py (#2224). Fake gh only; no network."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.framework import next_actor as na

MODULE = Path(na.__file__)
REPO = "o/r"
N = 7
L = "ScottThurlow"
OURS = frozenset({"github-actions[bot]"})
ASSIGNEES = f"repos/{REPO}/issues/{N}/assignees"
ISSUE = f"repos/{REPO}/issues/{N}"
PRECHECK = f"repos/{REPO}/assignees/{L}"


def issue(labels=("needs-human",), assignees=(), state="open"):
    return 200, {
        "state": state,
        "labels": [{"name": n} for n in labels],
        "assignees": [{"login": a} for a in assignees],
    }


class FakeGh:
    def __init__(self, monkeypatch):
        self.routes: dict[tuple[str, str], list] = {}
        self.calls: list[tuple[str, str, object]] = []
        monkeypatch.setattr(na, "_gh", self)

    def queue(self, method, path, *responses):
        self.routes.setdefault((method, path), []).extend(responses)
        return self

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        queue = self.routes.get((method, path))
        assert queue, f"unrouted gh call: {method} {path}"
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def gh(monkeypatch):
    return FakeGh(monkeypatch)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("BOT_ACCOUNTS", raising=False)
    d = tmp_path / "scripts" / "framework"
    d.mkdir(parents=True)
    (d / "machine-accounts.env").write_text(
        'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\nHUMAN_REVIEWER="ScottThurlow"\n'
    )
    monkeypatch.setattr(na, "_REPO_ROOT", tmp_path)
    return tmp_path


def set_env(root, text):
    (root / "scripts" / "framework" / "machine-accounts.env").write_text(text)


def ready(gh, *issue_responses):
    gh.queue("GET", PRECHECK, (204, None))
    gh.queue("GET", ISSUE, *issue_responses)


# --- config ---------------------------------------------------------------


def run_cli(*extra):
    return na.main(
        ["assign", "--repo", REPO, "--number", str(N), "--ours", "github-actions[bot]", *extra]
    )


def test_refuse_config_absent(gh, root):
    (root / "scripts" / "framework" / "machine-accounts.env").unlink()
    assert run_cli() == 3
    assert gh.calls == []


def test_refuse_unset(gh, root, capsys):
    set_env(root, "OTHER=1\n")
    assert run_cli() == 3
    assert "unset" in capsys.readouterr().out
    assert gh.calls == []


def test_refuse_empty(gh, root, capsys):
    set_env(root, 'HUMAN_REVIEWER=""\n')
    assert run_cli() == 3
    assert "unset" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["Scott Thurlow", ",", "-x", "a/b", "a" * 40])
def test_refuse_bad_login(gh, root, bad):
    set_env(root, f'HUMAN_REVIEWER="{bad}"\n')
    assert run_cli() == 3
    assert gh.calls == []


def test_refuse_bot_suffix(gh, root, capsys):
    set_env(root, 'HUMAN_REVIEWER="Someone[BOT]"\n')
    assert run_cli() == 3
    assert "bot-suffix" in capsys.readouterr().out
    assert gh.calls == []


def test_refuse_bot_accounts_member_case_insensitive(gh, root, monkeypatch, capsys):
    monkeypatch.setenv("BOT_ACCOUNTS", "alice")
    set_env(root, 'HUMAN_REVIEWER="Alice"\n')
    assert run_cli() == 3
    assert "bot-account" in capsys.readouterr().out
    assert gh.calls == []


# --- pre-check -------------------------------------------------------------


def test_not_assignable_404_exit3_no_write(gh, root):
    gh.queue("GET", PRECHECK, (404, None))
    assert run_cli() == 3
    assert gh.writes() == []


def test_precheck_500_exit1_no_write(gh, root):
    gh.queue("GET", PRECHECK, (500, None))
    assert run_cli() == 1
    assert gh.writes() == []


# --- assign ---------------------------------------------------------------


def test_assign_call_sequence_exact(gh):
    ready(gh, issue(), issue(assignees=[L]))
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert na.assign(REPO, N, L) == ("assigned", 0)
    assert gh.calls == [
        ("GET", PRECHECK, None),
        ("GET", ISSUE, None),
        ("POST", ASSIGNEES, {"assignees": ["ScottThurlow"]}),
        ("GET", ISSUE, None),
    ]


def test_assign_skip_already_assigned_case_insensitive(gh):
    ready(gh, issue(assignees=[L.lower()]))
    assert na.assign(REPO, N, L) == ("next-actor-skip:already-assigned", 0)
    assert gh.writes() == []


def test_assign_skip_closed(gh):
    ready(gh, issue(state="closed"))
    assert na.assign(REPO, N, L) == ("next-actor-skip:closed", 0)
    assert gh.writes() == []


def test_assign_skip_label_absent(gh):
    ready(gh, issue(labels=()))
    assert na.assign(REPO, N, L) == ("next-actor-skip:label-absent", 0)
    assert gh.writes() == []


def test_assign_refuse_release_request_no_assignee_call(gh):
    ready(gh, issue(labels=("needs-human", "release-request")))
    assert na.assign(REPO, N, L) == ("next-actor-refused:release-request", 0)
    assert gh.writes() == []


def test_assign_unverified_when_login_dropped(gh):
    ready(gh, issue(), issue())
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert na.assign(REPO, N, L) == ("assign-unverified", 4)


def test_assign_write_non2xx_exit4(gh):
    ready(gh, issue())
    gh.queue("POST", ASSIGNEES, (422, {}))
    assert na.assign(REPO, N, L) == ("assign-failed:write", 4)


def test_assign_reread_failure_exit1(gh):
    ready(gh, (500, None))
    assert na.assign(REPO, N, L) == ("read-failed", 1)
    assert gh.writes() == []


def test_post_write_release_request_undo_one_delete(gh):
    racing = issue(labels=("needs-human", "release-request"), assignees=[L])
    ready(gh, issue(), racing, issue(labels=("needs-human", "release-request")))
    gh.queue("POST", ASSIGNEES, (201, {}))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.assign(REPO, N, L) == ("ng3b-race-undone", 0)
    assert gh.calls[-2:] == [("DELETE", ASSIGNEES, {"assignees": [L]}), ("GET", ISSUE, None)]
    assert [c[0] for c in gh.writes()] == ["POST", "DELETE"]


def test_post_write_undo_failure_exit4(gh):
    racing = issue(labels=("needs-human", "release-request"), assignees=[L])
    ready(gh, issue(), racing, racing)
    gh.queue("POST", ASSIGNEES, (201, {}))
    gh.queue("DELETE", ASSIGNEES, (500, {}))
    assert na.assign(REPO, N, L) == ("ng3b-race-undo-failed", 4)


# --- unassign -------------------------------------------------------------


def events_for(assigner, assignee=L, created="2026-01-01T00:00:00Z", eid=1, **extra):
    event = {
        "event": "assigned",
        "id": eid,
        "created_at": created,
        "assignee": {"login": assignee},
        "assigner": assigner,
    }
    event.update(extra)
    return event


def events_path(page=1):
    return f"repos/{REPO}/issues/{N}/events?per_page=100&page={page}"


OURS_EVENT = events_for({"login": "github-actions[bot]"})


def test_unassign_ours_deletes_only_L(gh):
    gh.queue(
        "GET",
        ISSUE,
        issue(labels=(), assignees=[L, "other"]),
        issue(labels=(), assignees=["other"]),
    )
    gh.queue("GET", events_path(), (200, [OURS_EVENT]))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.unassign(REPO, N, L, OURS) == ("unassigned", 0)
    assert gh.writes() == [("DELETE", ASSIGNEES, {"assignees": [L]})]


def test_unassign_refuse_release_request_no_events_no_assignee_call(gh):
    gh.queue("GET", ISSUE, issue(labels=("release-request",), assignees=[L]))
    assert na.unassign(REPO, N, L, OURS) == ("next-actor-refused:release-request", 0)
    assert gh.calls == [("GET", ISSUE, None)]


def test_unassign_skip_label_present(gh):
    gh.queue("GET", ISSUE, issue(assignees=[L]))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-skip:label-present", 0)


def test_unassign_skip_not_assigned(gh):
    gh.queue("GET", ISSUE, issue(labels=(), assignees=["other"]))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-skip:not-assigned", 0)


def test_unassign_proceeds_when_closed(gh):
    gh.queue(
        "GET",
        ISSUE,
        issue(labels=(), assignees=[L], state="closed"),
        issue(labels=(), state="closed"),
    )
    gh.queue("GET", events_path(), (200, [OURS_EVENT]))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.unassign(REPO, N, L, OURS) == ("unassigned", 0)


def test_unassign_unverified_exit4(gh):
    gh.queue("GET", ISSUE, issue(labels=(), assignees=[L]))
    gh.queue("GET", events_path(), (200, [OURS_EVENT]))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-unverified", 4)


def test_unassign_events_read_failure_exit1_no_write(gh):
    gh.queue("GET", ISSUE, issue(labels=(), assignees=[L]))
    gh.queue("GET", events_path(), (500, None))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-skip:events-read-failed", 1)
    assert gh.writes() == []


# --- classification -------------------------------------------------------


def classify(gh, events):
    gh.queue("GET", events_path(), (200, events))
    return na.classify_ours(REPO, N, L, OURS)


@pytest.mark.parametrize(
    "events,expected",
    [
        ([events_for({"login": "github-actions[bot]"})], (True, "ours")),
        ([events_for({"login": "ScottThurlow"})], (False, "assigner-not-ours")),
        ([events_for({"login": "hos-worker-hos[bot]"})], (False, "assigner-not-ours")),
        ([events_for(None)], (False, "assigner-null")),
        (
            [{k: v for k, v in events_for(None).items() if k != "assigner"}],
            (False, "assigner-null"),
        ),
        (
            [events_for({"login": "ScottThurlow"}, actor={"login": "github-actions[bot]"})],
            (False, "assigner-not-ours"),
        ),
        (
            [
                events_for({"login": "github-actions[bot]"}, created="2026-01-01T00:00:00Z", eid=1),
                events_for({"login": "ScottThurlow"}, created="2026-01-02T00:00:00Z", eid=2),
            ],
            (False, "assigner-not-ours"),
        ),
        (
            [
                events_for({"login": "ScottThurlow"}, created="2026-01-01T00:00:00Z", eid=1),
                events_for({"login": "github-actions[bot]"}, created="2026-01-02T00:00:00Z", eid=2),
            ],
            (True, "ours"),
        ),
        (
            [
                events_for({"login": "github-actions[bot]"}, created="2026-01-01T00:00:00Z", eid=1),
                events_for(
                    {"login": "ScottThurlow"},
                    assignee="someone",
                    created="2026-01-02T00:00:00Z",
                    eid=2,
                ),
            ],
            (True, "ours"),
        ),
        ([], (False, "no-assigned-event")),
    ],
    ids=[
        "ours",
        "human",
        "other-bot",
        "null",
        "key-absent",
        "actor-ignored",
        "newer-human",
        "newer-ours",
        "other-assignee-ignored",
        "none",
    ],
)
def test_classify_ours(gh, events, expected):
    assert classify(gh, events) == expected


def test_events_complete_across_two_pages(gh):
    filler = [{"event": "labeled", "id": i} for i in range(100)]
    gh.queue("GET", events_path(1), (200, filler))
    gh.queue("GET", events_path(2), (200, [OURS_EVENT] + filler[:4]))
    assert na.classify_ours(REPO, N, L, OURS) == (True, "ours")


def test_events_bound_reached_not_ours_no_delete(gh):
    filler = [{"event": "labeled", "id": i} for i in range(100)]
    for page in range(1, 11):
        gh.queue("GET", events_path(page), (200, filler))
    gh.queue("GET", ISSUE, issue(labels=(), assignees=[L]))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-skip:not-ours:events-incomplete", 0)
    assert len([c for c in gh.calls if "/events" in c[1]]) == 10
    assert gh.writes() == []


# --- reconcile ------------------------------------------------------------


def test_reconcile_open_labelled_assigns(gh):
    gh.queue("GET", ISSUE, issue(), issue(), issue(assignees=[L]))
    gh.queue("GET", PRECHECK, (204, None))
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert na.reconcile_item(REPO, N, L, OURS) == ("assigned", 0)


def test_reconcile_label_absent_unassigns(gh):
    gh.queue(
        "GET",
        ISSUE,
        issue(labels=(), assignees=[L]),
        issue(labels=(), assignees=[L]),
        issue(labels=()),
    )
    gh.queue("GET", events_path(), (200, [OURS_EVENT]))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.reconcile_item(REPO, N, L, OURS) == ("unassigned", 0)


def test_reconcile_closed_labelled_noop(gh):
    gh.queue("GET", ISSUE, issue(state="closed"))
    assert na.reconcile_item(REPO, N, L, OURS) == ("reconcile-noop:closed", 0)
    assert gh.calls == [("GET", ISSUE, None)]


def test_reconcile_release_request_labelled_noop_no_assignee_call(gh):
    gh.queue("GET", ISSUE, issue(labels=("needs-human", "release-request")))
    assert na.reconcile_item(REPO, N, L, OURS) == ("reconcile-noop:release-request", 0)
    assert gh.calls == [("GET", ISSUE, None)]


def test_reconcile_second_run_zero_writes(gh):
    gh.queue("GET", ISSUE, issue(assignees=[L]))
    gh.queue("GET", PRECHECK, (204, None))
    assert na.reconcile_item(REPO, N, L, OURS) == ("next-actor-skip:already-assigned", 0)
    assert gh.writes() == []


def test_direct_function_calls_refuse_release_request(gh):
    ready(gh, issue(labels=("needs-human", "release-request"), assignees=[L]))
    assert na.assign(REPO, N, L)[0] == "next-actor-refused:release-request"
    assert na.unassign(REPO, N, L, OURS)[0] == "next-actor-refused:release-request"
    assert gh.writes() == []


# --- CLI and _gh ----------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["assign", "--repo", REPO, "--ours", "x"],
        ["assign", "--repo", REPO, "--number", "0", "--ours", "x"],
        ["assign", "--repo", REPO, "--number", "x", "--ours", "x"],
        ["assign", "--repo", "bad repo", "--number", "1", "--ours", "x"],
        ["assign", "--repo", REPO, "--number", "1", "--ours", "bad login!"],
        ["frobnicate", "--repo", REPO, "--number", "1", "--ours", "x"],
    ],
    ids=["missing-number", "zero", "non-int", "bad-repo", "bad-ours", "unknown-subcommand"],
)
def test_cli_usage_exit2(gh, root, argv):
    with pytest.raises(SystemExit) as exc:
        na.main(argv)
    assert exc.value.code == 2
    assert gh.calls == []


def test_assign_without_ours_works(gh, root, capsys):
    ready(gh, issue(), issue(assignees=[L]))
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert na.main(["assign", "--repo", REPO, "--number", str(N)]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "assigned"


@pytest.mark.parametrize("op", ["unassign", "reconcile-item"])
def test_other_subcommands_require_ours(gh, root, op):
    with pytest.raises(SystemExit) as exc:
        na.main([op, "--repo", REPO, "--number", str(N)])
    assert exc.value.code == 2
    assert gh.calls == []


def test_run_by_file_path_from_other_cwd(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(MODULE), "bogus-subcommand"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "ImportError" not in proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr
    assert "invalid choice" in proc.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "bad_id",
    ["missing", None, "", "12", True, 1.5],
    ids=["missing", "none", "empty-string", "numeric-string", "bool", "float"],
)
def test_malformed_event_id_is_read_failure_no_write(gh, bad_id):
    bad = events_for({"login": "github-actions[bot]"})
    if bad_id == "missing":
        del bad["id"]
    else:
        bad["id"] = bad_id
    gh.queue("GET", ISSUE, issue(labels=(), assignees=[L]))
    gh.queue("GET", events_path(), (200, [bad]))
    assert na.unassign(REPO, N, L, OURS) == ("unassign-skip:events-read-failed", 1)
    assert gh.writes() == []


def test_cli_prints_exactly_one_json_line(gh, root, capsys):
    ready(gh, issue(), issue(assignees=[L]))
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert run_cli() == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "op": "assign",
        "repo": REPO,
        "number": N,
        "login": L,
        "outcome": "assigned",
        "exit": 0,
    }
    assert out.err == ""


def _fake_run(monkeypatch, stdout="", exc=None):
    seen = {}

    def run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        if exc:
            raise exc
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(na.subprocess, "run", run)
    return seen


def test_gh_argv_post_uses_input_stdin(monkeypatch):
    seen = _fake_run(monkeypatch, "HTTP/2.0 201 Created\n\n{}")
    body = {"assignees": [L]}
    assert na._gh("POST", "repos/o/r/issues/1/assignees", body) == (201, {})
    assert seen["argv"] == [
        "gh",
        "api",
        "--include",
        "--method",
        "POST",
        "repos/o/r/issues/1/assignees",
        "--input",
        "-",
    ]
    assert seen["kwargs"]["input"] == json.dumps(body)


def test_gh_parses_status_crlf_and_lf(monkeypatch):
    _fake_run(monkeypatch, 'HTTP/2.0 200 OK\r\nX: y\r\n\r\n{"a": 1}')
    assert na._gh("GET", "p") == (200, {"a": 1})
    _fake_run(monkeypatch, "HTTP/1.1 204 No Content\nX: y\n\n")
    assert na._gh("GET", "p") == (204, None)


def test_gh_timeout_returns_zero(monkeypatch):
    _fake_run(monkeypatch, exc=subprocess.TimeoutExpired("gh", 30))
    assert na._gh("GET", "p") == (0, None)


# --- static checks --------------------------------------------------------

SOURCE = MODULE.read_text()
TREE = ast.parse(SOURCE)


def test_single_subprocess_call_site():
    calls = [
        n
        for n in ast.walk(TREE)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run"
    ]
    assert len(calls) == 1


def test_no_patch_anywhere():
    assert "PATCH" not in SOURCE
    assert not any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and "PATCH" in n.value
        for n in ast.walk(TREE)
    )


def test_no_labels_comments_or_write_events_paths():
    for node in ast.walk(TREE):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "_gh"
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value != "GET"
        ):
            path = ast.unparse(node.args[1])
            assert all(seg not in path for seg in ("/labels", "/comments", "/events"))
            assert path.endswith("/assignees'")


def test_no_scripts_automation_import():
    assert "scripts.automation" not in SOURCE
    assert "scripts/automation" not in SOURCE


def test_config_via_requester_trust_only():
    from scripts.framework.requester_trust import _parse_env_file, load_bot_accounts

    assert na._parse_env_file is _parse_env_file
    assert na.load_bot_accounts is load_bot_accounts
    assert 'partition("=")' not in SOURCE and 'split("=")' not in SOURCE


# --- mutation-driven additions (unit-test round 1) -------------------------


def test_classify_event_without_created_at_is_ignored(gh):
    event = events_for({"login": "github-actions[bot]"})
    del event["created_at"]
    assert classify(gh, [event]) == (False, "no-assigned-event")


@pytest.mark.parametrize("assigner", [{}, {"login": ""}, {"login": None}])
def test_classify_assigner_without_login_is_null(gh, assigner):
    assert classify(gh, [events_for(assigner)]) == (False, "assigner-null")


def test_classify_assigner_login_compared_case_insensitively(gh):
    assert classify(gh, [events_for({"login": "GitHub-Actions[BOT]"})]) == (True, "ours")


def test_post_write_release_request_not_assigned_is_noop_no_delete(gh):
    ready(gh, issue(), issue(labels=("needs-human", "release-request")))
    gh.queue("POST", ASSIGNEES, (201, {}))
    assert na.assign(REPO, N, L) == ("ng3b-race-noop", 0)
    assert [c[0] for c in gh.writes()] == ["POST"]


def test_post_write_undo_delete_failed_even_if_reread_shows_removed(gh):
    racing = issue(labels=("needs-human", "release-request"), assignees=[L])
    ready(gh, issue(), racing, issue(labels=("needs-human", "release-request")))
    gh.queue("POST", ASSIGNEES, (201, {}))
    gh.queue("DELETE", ASSIGNEES, (500, {}))
    assert na.assign(REPO, N, L) == ("ng3b-race-undo-failed", 4)


def test_post_write_undo_final_reread_failure_is_undo_failed(gh):
    racing = issue(labels=("needs-human", "release-request"), assignees=[L])
    ready(gh, issue(), racing, (500, None))
    gh.queue("POST", ASSIGNEES, (201, {}))
    gh.queue("DELETE", ASSIGNEES, (200, {}))
    assert na.assign(REPO, N, L) == ("ng3b-race-undo-failed", 4)


def test_classify_latest_by_created_at_before_event_id(gh):
    older_high_id = events_for({"login": "ScottThurlow"}, created="2026-01-01T00:00:00Z", eid=99)
    newer_low_id = events_for(
        {"login": "github-actions[bot]"}, created="2026-01-02T00:00:00Z", eid=1
    )
    assert classify(gh, [older_high_id, newer_low_id]) == (True, "ours")


def test_classify_same_timestamp_higher_event_id_wins(gh):
    ours = events_for({"login": "github-actions[bot]"}, created="2026-01-01T00:00:00Z", eid=1)
    human = events_for({"login": "ScottThurlow"}, created="2026-01-01T00:00:00Z", eid=2)
    assert classify(gh, [human, ours]) == (False, "assigner-not-ours")
