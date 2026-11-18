"""Fault-injection tests for human_authorization.fetch (TD-2101 §7.4, T-F-*).

`_run_gh_get` and `_run_gh_graphql` are replaced by recording fakes; nothing touches the network."""

from __future__ import annotations

import ast
import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.framework import human_authorization as ha
from scripts.framework.human_authorization import VerifierError, fetch

REPO = "o/r"
_REAL_GQL = ha._run_gh_graphql  # captured before any fixture replaces the seam


def _b64(text: str | bytes) -> str:
    raw = text.encode() if isinstance(text, str) else text
    b = base64.b64encode(raw).decode()
    return "\n".join(b[i : i + 60] for i in range(0, len(b), 60)) + "\n"


def _file(text: str | bytes) -> dict:
    return {"type": "file", "encoding": "base64", "content": _b64(text), "sha": "x", "size": 1}


def _raw(cid, created="2026-10-20T10:00:00Z", updated=None, login="scottthurlow", **over):
    obj = {
        "id": cid,
        "html_url": f"https://github.com/o/r/issues/1#issuecomment-{cid}",
        "body": "hi",
        "created_at": created,
        "updated_at": updated or created,
        "user": {"login": login, "type": "User"},
    }
    obj.update(over)
    return obj


def _resp(n, nodes=(), fc=None, has_next=False, cursor=None, typename="Issue"):
    """A DELETIONS_QUERY response for source `n`."""
    return {
        "data": {
            "repository": {
                "issueOrPullRequest": {
                    "__typename": typename,
                    "number": n,
                    "timelineItems": {
                        "filteredCount": len(nodes) if fc is None else fc,
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": list(nodes),
                    },
                }
            }
        }
    }


def _node(did=901, at="2026-10-20T12:00:00Z", author="ScottThurlow"):
    return {
        "__typename": "CommentDeletedEvent",
        "databaseId": did,
        "createdAt": at,
        "deletedCommentAuthor": None if author is None else {"login": author},
    }


class Gql:
    """Recording fake for `_run_gh_graphql`. Key (number, after) -> response or Exception.

    A missing key answers the empty happy response, so tests that do not care about
    deletions keep their meaning."""

    def __init__(self, table=None, events=None):
        self.calls: list[tuple] = []
        self.timeouts: list[Any] = []
        self.table = table or {}
        self.events = events if events is not None else []

    def __call__(self, owner, name, number, after, timeout=None):
        self.timeouts.append(timeout)
        self.calls.append((owner, name, number, after))
        self.events.append(("gql", number, after))
        val = self.table.get((number, after), _resp(number))
        if isinstance(val, Exception):
            raise val
        return val


class Gh:
    """Maps endpoint -> response; an Exception value is raised."""

    def __init__(self, comments=None, **overrides):
        self.calls: list[str] = []
        self.timeouts: list[Any] = []
        self.events: list[tuple] = []
        self.comments = comments or {}
        self.table = {
            f"repos/{REPO}": {"default_branch": "main"},
            f"repos/{REPO}/contents/.github/CODEOWNERS?ref=refs%2Fheads%2Fmain": _file(
                "* @ScottThurlow\n"
            ),
            f"repos/{REPO}/contents/scripts/framework/machine-accounts.env?ref=refs%2Fheads%2Fmain": _file(
                'BOT_WORKER_USERNAME="w[bot]"\n'
            ),
        }
        self.table.update(overrides)

    def __call__(self, endpoint: str, timeout=None):
        self.timeouts.append(timeout)
        self.calls.append(endpoint)
        self.events.append(("get", endpoint))
        if endpoint in self.table:
            val = self.table[endpoint]
        elif "/comments?per_page=100&page=" in endpoint:
            base, _, page = endpoint.partition("?per_page=100&page=")
            val = self.comments.get((base, int(page)), [])
        else:
            raise VerifierError("api-error", "unexpected endpoint")
        if isinstance(val, Exception):
            raise val
        return val


@pytest.fixture(autouse=True)
def _no_real_graphql(monkeypatch):
    """Nothing in this file may reach the real GraphQL seam unless it patches subprocess.run."""
    monkeypatch.setattr(ha, "_run_gh_graphql", Gql())


def _install(monkeypatch, gh, gql=None):
    monkeypatch.setattr(ha, "_run_gh_get", gh)
    monkeypatch.setattr(ha, "_run_gh_graphql", gql if gql is not None else Gql(events=gh.events))
    return gh


def _code(monkeypatch, gh, issue=1, pr=None, gql=None):
    _install(monkeypatch, gh, gql)
    with pytest.raises(VerifierError) as e:
        fetch(REPO, issue, pr)
    return e.value.code


def test_t_f_1_happy_path_endpoints(monkeypatch):
    gh = _install(monkeypatch, Gh({(f"repos/{REPO}/issues/1/comments", 1): [_raw(11)]}))
    f = fetch(REPO, 1, None)
    assert gh.calls == [
        f"repos/{REPO}",
        f"repos/{REPO}/contents/.github/CODEOWNERS?ref=refs%2Fheads%2Fmain",
        f"repos/{REPO}/contents/scripts/framework/machine-accounts.env?ref=refs%2Fheads%2Fmain",
        f"repos/{REPO}/issues/1/comments?per_page=100&page=1",
    ]
    assert f.default_branch == "main"
    assert f.codeowners_text == "* @ScottThurlow\n"
    assert 'BOT_WORKER_USERNAME="w[bot]"' in f.machine_env_text
    assert [c.id for c in f.comments] == [11] and f.comments[0].issue_number == 1
    assert f.deletions == ()


def test_t_f_1_ref_is_url_quoted(monkeypatch):
    gh = Gh()
    gh.table[f"repos/{REPO}"] = {"default_branch": "release/1 x"}
    q = "refs%2Fheads%2Frelease%2F1%20x"
    gh.table[f"repos/{REPO}/contents/.github/CODEOWNERS?ref={q}"] = _file("* @a\n")
    gh.table[f"repos/{REPO}/contents/scripts/framework/machine-accounts.env?ref={q}"] = _file("")
    _install(monkeypatch, gh)
    assert fetch(REPO, 1, None).default_branch == "release/1 x"


def test_t_f_1_real_seam_argv_is_a_single_plain_get(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = list(argv), kw
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    assert ha._run_gh_get("repos/o/r/issues/1/comments?per_page=100&page=1") == {}
    assert seen["argv"] == ["gh", "api", "repos/o/r/issues/1/comments?per_page=100&page=1"]
    assert seen["kw"]["timeout"] == ha.GH_TIMEOUT_SECONDS
    for banned in ("--paginate", "-f", "-F", "--method", "--input"):
        assert banned not in seen["argv"]


def test_t_f_2_only_issue_and_pr_are_read(monkeypatch):
    gh = _install(monkeypatch, Gh({(f"repos/{REPO}/issues/99/comments", 1): [_raw(1)]}))
    f = fetch(REPO, 1, 2)
    assert f.comments == ()
    comment_calls = [c for c in gh.calls if "/comments" in c]
    assert comment_calls == [
        f"repos/{REPO}/issues/1/comments?per_page=100&page=1",
        f"repos/{REPO}/issues/2/comments?per_page=100&page=1",
    ]


def test_pr_comments_are_tagged_with_their_own_number(monkeypatch):
    _install(
        monkeypatch,
        Gh(
            {
                (f"repos/{REPO}/issues/1/comments", 1): [_raw(1)],
                (f"repos/{REPO}/issues/2/comments", 1): [_raw(2)],
            }
        ),
    )
    assert {c.id: c.issue_number for c in fetch(REPO, 1, 2).comments} == {1: 1, 2: 2}


def test_t_f_3_nonzero_exit_does_not_parse_stdout(monkeypatch):
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 1, stdout='{"message":"Not Found"}', stderr="gh: Not Found (HTTP 404)"
        )

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "api-error"


def test_t_f_4_timeout(monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 30)

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "timeout"


def test_t_f_5_gh_missing(monkeypatch):
    def fake_run(argv, **kw):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "api-error"


def test_t_f_6_rate_limit_stderr_stays_off_the_error(monkeypatch, capsys):
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="API rate limit exceeded for user"
        )

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "api-error"
    assert "rate limit" not in str(e.value) and "rate limit" not in e.value.detail
    assert "rate limit" not in capsys.readouterr().err


def test_invalid_json_is_payload_shape(monkeypatch):
    monkeypatch.setattr(
        ha.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="not json", stderr=""),
    )
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "payload-shape"


def test_t_f_7_budget_exhausted(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])
    gh = Gh()
    orig = gh.__call__

    def slow(endpoint, timeout=None):
        clock[0] += ha.FETCH_BUDGET_SECONDS + 1
        return orig(endpoint, timeout)

    monkeypatch.setattr(ha, "_run_gh_get", slow)
    with pytest.raises(VerifierError) as e:
        fetch(REPO, 1, None)
    assert e.value.code == "budget-exhausted"


def test_t_f_7b_deadline_is_per_call(monkeypatch):
    t0 = 5_000_000.0
    clock = [t0 + 10 * ha.FETCH_BUDGET_SECONDS]
    monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])
    gh = Gh()

    def ticking(endpoint, timeout=None):
        clock[0] += ha.FETCH_BUDGET_SECONDS / 10
        return gh(endpoint, timeout)

    monkeypatch.setattr(ha, "_run_gh_get", ticking)
    fetch(REPO, 1, None)
    fetch(REPO, 1, None)


def test_t_f_8_pagination_bound_issue_and_pr(monkeypatch):
    pages = {
        (f"repos/{REPO}/issues/1/comments", k): [_raw(k * 1000 + i) for i in range(100)]
        for k in range(1, 11)
    }
    assert _code(monkeypatch, Gh(pages)) == "pagination-bound"
    ok_issue = {(f"repos/{REPO}/issues/1/comments", 1): [_raw(1)]}
    pr_pages = {
        (f"repos/{REPO}/issues/2/comments", k): [_raw(k * 1000 + i + 5000) for i in range(100)]
        for k in range(1, 11)
    }
    assert _code(monkeypatch, Gh({**ok_issue, **pr_pages}), pr=2) == "pagination-bound"


def test_pagination_nine_full_pages_then_short_is_complete(monkeypatch):
    pages = {
        (f"repos/{REPO}/issues/1/comments", k): [_raw(k * 1000 + i) for i in range(100)]
        for k in range(1, 10)
    }
    pages[(f"repos/{REPO}/issues/1/comments", 10)] = [_raw(99999)]
    _install(monkeypatch, Gh(pages))
    assert len(fetch(REPO, 1, None).comments) == 901


def test_t_f_9_page_is_not_a_list(monkeypatch):
    full = [_raw(i) for i in range(1, 101)]
    gh = Gh(
        {
            (f"repos/{REPO}/issues/1/comments", 1): full,
            (f"repos/{REPO}/issues/1/comments", 2): {"message": "x"},
        }
    )
    assert _code(monkeypatch, gh) == "payload-shape"


@pytest.mark.parametrize(
    "bad",
    [
        _raw(1, created="yesterday"),
        _raw(1, updated="2026-10-20 10:00:00"),
        {**_raw(1), "id": "1"},
        {**_raw(1), "id": True},
        {**_raw(1), "id": 0},
        {k: v for k, v in _raw(1).items() if k != "body"},
        _raw(1, body=None),
        _raw(1, user={"login": 5, "type": "User"}),
        _raw(1, user="scott"),
        "not a dict",
    ],
)
def test_t_f_10_bad_comment_records(monkeypatch, bad):
    gh = Gh({(f"repos/{REPO}/issues/1/comments", 1): [bad]})
    assert _code(monkeypatch, gh) == "payload-shape"


def test_t_f_10_duplicate_id_across_sources(monkeypatch):
    gh = Gh(
        {
            (f"repos/{REPO}/issues/1/comments", 1): [_raw(7)],
            (f"repos/{REPO}/issues/2/comments", 1): [_raw(7)],
        }
    )
    assert _code(monkeypatch, gh, pr=2) == "payload-shape"


def test_null_user_is_empty_login(monkeypatch):
    _install(monkeypatch, Gh({(f"repos/{REPO}/issues/1/comments", 1): [_raw(1, user=None)]}))
    c = fetch(REPO, 1, None).comments[0]
    assert (c.login, c.user_type) == ("", "")


@pytest.mark.parametrize("meta", [{}, {"default_branch": ""}, {"default_branch": 5}, [], "x"])
def test_t_f_11_default_branch_unreadable(monkeypatch, meta):
    assert _code(monkeypatch, Gh(**{f"repos/{REPO}": meta})) == "default-branch-unreadable"


CO_KEY = f"repos/{REPO}/contents/.github/CODEOWNERS?ref=refs%2Fheads%2Fmain"
MA_KEY = f"repos/{REPO}/contents/scripts/framework/machine-accounts.env?ref=refs%2Fheads%2Fmain"


@pytest.mark.parametrize(
    "val",
    [
        VerifierError("api-error", "404"),
        {**_file("x"), "encoding": "none"},
        _file(b"\xff\xfe\x00bad"),
        {"type": "dir"},
        {**_file("x"), "content": 5},
        "oops",
    ],
)
def test_t_f_12_codeowners_unreadable(monkeypatch, val):
    assert _code(monkeypatch, Gh(**{CO_KEY: val})) == "codeowners-unreadable"


def test_t_f_13_machine_accounts_unreadable(monkeypatch):
    assert (
        _code(monkeypatch, Gh(**{MA_KEY: VerifierError("api-error", "404")}))
        == "machine-accounts-unreadable"
    )
    assert _code(monkeypatch, Gh(**{MA_KEY: _file(b"\xff\xfe")})) == "machine-accounts-unreadable"


def test_timeouts_keep_their_own_code_on_file_reads(monkeypatch):
    assert _code(monkeypatch, Gh(**{CO_KEY: VerifierError("timeout", "slow")})) == "timeout"


def test_t_f_14_no_partial_decision(monkeypatch, tmp_path):
    """Every fetch failure surfaces as VerifierError before decide() can run."""
    called = []
    monkeypatch.setattr(ha, "decide", lambda *a, **k: called.append(1))
    monkeypatch.setattr(
        ha,
        "compute_binding",
        lambda *a, **k: ha.Binding("patch:" + "a" * 40, "b" * 40, "c" * 40, "b" * 40, ("a",)),
    )
    monkeypatch.setattr(ha, "_audit_write", lambda e, r: True)
    bad = [
        Gh(**{CO_KEY: VerifierError("api-error", "404")}),
        Gh(**{MA_KEY: VerifierError("api-error", "404")}),
        Gh(**{f"repos/{REPO}": {}}),
        Gh({(f"repos/{REPO}/issues/1/comments", 1): [{"bad": 1}]}),
    ]
    for gh in bad:
        monkeypatch.setattr(ha, "_run_gh_get", gh)
        rc = ha.main(
            [
                "verify",
                "--repo",
                REPO,
                "--step",
                "5",
                "--issue",
                "1",
                "--base",
                "main",
                "--head",
                "a" * 40,
                "--require",
                "C7",
                "--consumer",
                "evaluator",
                "--repo-root",
                str(tmp_path),
                "--json",
            ]
        )
        assert rc == 3
    assert called == []


def test_non_utf8_gh_output_is_payload_shape(monkeypatch):
    def fake_run(argv, **kw):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "payload-shape"


def test_deeply_nested_json_is_payload_shape(monkeypatch):
    deep = "[" * 100000 + "]" * 100000
    monkeypatch.setattr(
        ha.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=deep, stderr=""),
    )
    with pytest.raises(VerifierError) as e:
        ha._run_gh_get("repos/o/r")
    assert e.value.code == "payload-shape"


def test_contents_ref_is_the_branch_head_not_a_bare_name(monkeypatch):
    gh = _install(monkeypatch, Gh())
    fetch(REPO, 1, None)
    contents = [c for c in gh.calls if "/contents/" in c]
    assert contents and all(c.endswith("?ref=refs%2Fheads%2Fmain") for c in contents)


def test_gh_seam_has_no_stdin_and_no_prompts(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    ha._run_gh_get("repos/o/r")
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["env"]["GH_PROMPT_DISABLED"] == "1"


@pytest.mark.parametrize(
    "stderr,want",
    [
        ("gh: Not Found (HTTP 404)", "gh api exit=1 HTTP 404"),
        ("secret-token-abc leaked here", "gh api exit=1"),
        ("", "gh api exit=1"),
    ],
)
def test_gh_failure_diag_is_status_only(monkeypatch, capsys, stderr, want):
    monkeypatch.setattr(
        ha.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr=stderr),
    )
    with pytest.raises(VerifierError):
        ha._run_gh_get("repos/o/r")
    err = capsys.readouterr().err
    assert err.strip() == f"human_authorization: {want}"
    assert "secret-token" not in err


# ---------------------------------------------------------------------------
# S1b (#2151, TD-2101 §10.4.4): read 6, the GraphQL deletion read
# ---------------------------------------------------------------------------

_GQL_HEAD = ["gh", "api", "graphql", "-f", "query=" + ha.DELETIONS_QUERY]


def _real_gql_run(monkeypatch, handler):
    seen: list[dict] = []

    def fake_run(argv, **kw):
        seen.append({"argv": list(argv), **kw})
        return handler(list(argv), **kw)

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    return seen


def test_t_f_15_happy_path_with_pr_and_real_seam_argv(monkeypatch):
    gh = Gh()
    monkeypatch.setattr(ha, "_run_gh_get", gh)
    monkeypatch.setattr(ha, "_run_gh_graphql", _REAL_GQL)

    def handler(argv, **kw):
        n = int(argv[argv.index("-F") + 1].split("=")[1])
        nodes = [_node()] if n == 2 else []
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(_resp(n, nodes)), stderr="")

    seen = _real_gql_run(monkeypatch, handler)
    f = fetch(REPO, 1, 2)
    assert f.deletions == (ha.Deletion(901, "2026-10-20T12:00:00Z", "ScottThurlow", 2),)
    assert [c["argv"] for c in seen] == [
        _GQL_HEAD + ["-f", "owner=o", "-f", "name=r", "-F", "number=1"],
        _GQL_HEAD + ["-f", "owner=o", "-f", "name=r", "-F", "number=2"],
    ]
    for c in seen:
        for banned in ("--paginate", "--input", "--method", "-X"):
            assert banned not in c["argv"]
        assert c["timeout"] == ha.GH_TIMEOUT_SECONDS
        assert c["stdin"] == subprocess.DEVNULL
        assert c["env"]["GH_PROMPT_DISABLED"] == "1"


def test_t_f_15_null_author_is_unknown(monkeypatch):
    gql = Gql({(1, None): _resp(1, [_node(author=None)])})
    _install(monkeypatch, Gh(), gql)
    assert fetch(REPO, 1, None).deletions == (ha.Deletion(901, "2026-10-20T12:00:00Z", None, 1),)


def test_t_f_16_deletions_are_read_after_every_comment_read(monkeypatch):
    gh = Gh({(f"repos/{REPO}/issues/1/comments", 1): [_raw(1)]})
    _install(monkeypatch, gh)
    fetch(REPO, 1, 2)
    kinds = [e[0] for e in gh.events]
    assert kinds == ["get"] * (len(kinds) - 2) + ["gql", "gql"]
    assert [e[1] for e in gh.events[-2:]] == [1, 2]
    last_comment = max(i for i, e in enumerate(gh.events) if e[0] == "get" and "/comments" in e[1])
    assert last_comment < kinds.index("gql")


@pytest.mark.parametrize(
    "exc,code",
    [
        (VerifierError("api-error", "x"), "api-error"),
        (VerifierError("timeout", "x"), "timeout"),
    ],
)
def test_t_f_17_seam_errors_propagate(monkeypatch, exc, code):
    gql = Gql({(1, None): exc})
    assert _code(monkeypatch, Gh(), gql=gql) == code


@pytest.mark.parametrize(
    "outcome,code",
    [
        (("rc", 1, json.dumps({"data": None, "errors": [{"message": "x"}]})), "api-error"),
        (("raise", subprocess.TimeoutExpired(["gh"], 30)), "timeout"),
        (("raise", FileNotFoundError("gh")), "api-error"),
        (("rc", 0, "not json"), "payload-shape"),
        (("raise", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")), "payload-shape"),
    ],
)
def test_t_f_17_real_seam_transport_faults(monkeypatch, outcome, code):
    def handler(argv, **kw):
        if outcome[0] == "raise":
            raise outcome[1]
        return subprocess.CompletedProcess(argv, outcome[1], stdout=outcome[2], stderr="")

    _real_gql_run(monkeypatch, handler)
    with pytest.raises(VerifierError) as e:
        _REAL_GQL("o", "r", 1, None)
    assert e.value.code == code


def test_t_f_17_real_seam_does_not_echo_stderr(monkeypatch, capsys):
    _real_gql_run(
        monkeypatch,
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="secret-token-abc HTTP 502"
        ),
    )
    with pytest.raises(VerifierError):
        _REAL_GQL("o", "r", 1, None)
    err = capsys.readouterr().err
    assert err.strip() == "human_authorization: gh api exit=1 HTTP 502"


def _bad_cases():
    ok = _node()
    cases = {
        "errors-key": {**_resp(1, [ok]), "errors": [{"message": "x"}]},
        "target-null": {"data": {"repository": {"issueOrPullRequest": None}}},
        "number-mismatch": _resp(7, [ok]),
        "typename-discussion": _resp(1, [ok], typename="Discussion"),
        "node-typename": _resp(1, [{**ok, "__typename": "IssueComment"}]),
        "id-true": _resp(1, [{**ok, "databaseId": True}]),
        "id-zero": _resp(1, [{**ok, "databaseId": 0}]),
        "id-str": _resp(1, [{**ok, "databaseId": "901"}]),
        "created-bad": _resp(1, [{**ok, "createdAt": "2026-10-20 12:00"}]),
        "author-empty-login": _resp(1, [{**ok, "deletedCommentAuthor": {"login": ""}}]),
        "author-int-login": _resp(1, [{**ok, "deletedCommentAuthor": {"login": 5}}]),
        "author-str": _resp(1, [{**ok, "deletedCommentAuthor": "x"}]),
        "count-mismatch": _resp(1, [ok], fc=2),
        "next-no-cursor": _resp(1, [ok], has_next=True, cursor=None),
        "next-bad-cursor": _resp(1, [ok], has_next=True, cursor="a b"),
        "null-node": _resp(1, [None], fc=1),
        "timeline-null": {
            "data": {
                "repository": {
                    "issueOrPullRequest": {
                        "__typename": "Issue",
                        "number": 1,
                        "timelineItems": None,
                    }
                }
            }
        },
        "not-a-dict": [],
    }
    return list(cases.items())


@pytest.mark.parametrize("name,resp", _bad_cases(), ids=[n for n, _ in _bad_cases()])
def test_t_f_18_shape_violations(monkeypatch, name, resp):
    assert _code(monkeypatch, Gh(), gql=Gql({(1, None): resp})) == "payload-shape"


def test_t_f_18_one_database_id_on_both_sources(monkeypatch):
    gql = Gql({(1, None): _resp(1, [_node(901)]), (2, None): _resp(2, [_node(901)])})
    assert _code(monkeypatch, Gh(), pr=2, gql=gql) == "payload-shape"


def test_t_f_19_pagination_follows_the_cursor(monkeypatch):
    gql = Gql(
        {
            (1, None): _resp(1, [_node(901)], fc=2, has_next=True, cursor="Y3Vy"),
            (1, "Y3Vy"): _resp(1, [_node(902)], fc=2),
        }
    )
    _install(monkeypatch, Gh(), gql)
    f = fetch(REPO, 1, None)
    assert [d.event_id for d in f.deletions] == [901, 902]
    assert [c[3] for c in gql.calls] == [None, "Y3Vy"]


def test_t_f_19_real_seam_carries_after(monkeypatch):
    seen = _real_gql_run(
        monkeypatch,
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(_resp(1)), stderr=""
        ),
    )
    _REAL_GQL("o", "r", 1, "Y3Vy")
    assert seen[0]["argv"][-2:] == ["-f", "after=Y3Vy"]


def test_t_f_19_pagination_bound(monkeypatch):
    page = _resp(1, [], fc=1000, has_next=True, cursor="Y3Vy")
    gql = Gql({(1, None): page, (1, "Y3Vy"): page})
    assert _code(monkeypatch, Gh(), gql=gql) == "pagination-bound"
    assert len(gql.calls) == ha.DELETION_PAGE_BOUND


def test_t_f_19b_count_moving_between_pages_is_payload_shape(monkeypatch):
    gql = Gql(
        {
            (1, None): _resp(1, [], fc=101, has_next=True, cursor="Y3Vy"),
            (1, "Y3Vy"): _resp(1, [], fc=102),
        }
    )
    assert _code(monkeypatch, Gh(), gql=gql) == "payload-shape"


def test_t_f_20_deletion_read_is_inside_the_fetch_deadline(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])
    gh = Gh()

    def after_comments(endpoint, timeout=None):
        out = gh(endpoint, timeout)
        if "/comments" in endpoint:
            clock[0] += ha.FETCH_BUDGET_SECONDS + 1
        return out

    gql = Gql()
    monkeypatch.setattr(ha, "_run_gh_get", after_comments)
    monkeypatch.setattr(ha, "_run_gh_graphql", gql)
    with pytest.raises(VerifierError) as e:
        fetch(REPO, 1, None)
    assert e.value.code == "budget-exhausted"
    assert gql.calls == []


_EXPECTED_QUERY = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
      ... on PullRequest {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
    }
  }
}"""


def test_t_f_21_query_is_byte_pinned_and_minimal():
    q = ha.DELETIONS_QUERY
    assert q == _EXPECTED_QUERY
    assert q.lstrip().startswith("query(")
    assert "mutation" not in q.lower()
    assert "totalCount" not in q
    stripped = q.replace("deletedCommentAuthor", "")
    for word in ("body", "actor", "author"):
        assert word not in stripped.lower(), word


def test_t_f_21_only_two_functions_spawn_gh_and_only_one_names_graphql():
    tree = ast.parse(Path(ha.__file__).read_text(encoding="utf-8"))
    runs_gh, names_graphql = set(), set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)}
        calls_run = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "subprocess"
            for n in ast.walk(fn)
        )
        if calls_run and "gh" in consts:
            runs_gh.add(fn.name)
        if "graphql" in consts:
            names_graphql.add(fn.name)
    assert runs_gh == {"_run_gh_get", "_run_gh_graphql"}
    assert names_graphql == {"_run_gh_graphql"}


# --- S1b mutation-gap tests for _deletion_page (TD-2101 §10.4; unit-test round 1) -------------


def _dpage(**over):
    conn = {
        "filteredCount": 1,
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [
            {
                "__typename": "CommentDeletedEvent",
                "databaseId": 7,
                "createdAt": "2026-10-20T10:00:00Z",
                "deletedCommentAuthor": {"login": "scottthurlow"},
            }
        ],
    }
    node = {"__typename": "Issue", "number": 5, "timelineItems": conn}
    for k, v in over.items():
        if k in ("__typename", "number"):
            node[k] = v
        elif k == "pageInfo":
            conn["pageInfo"] = v
        else:
            conn[k] = v
    return {"data": {"repository": {"issueOrPullRequest": node}}}


def test_deletion_page_accepts_pull_request_target_type():
    count, has_next, cursor, nodes = ha._deletion_page(_dpage(__typename="PullRequest"), 5)
    assert (count, has_next, cursor) == (1, False, None)
    assert nodes == [(7, "2026-10-20T10:00:00Z", "scottthurlow")]


@pytest.mark.parametrize(
    "over,detail",
    [
        ({"__typename": "Repository"}, "deletion target type"),
        ({"__typename": "pullrequest"}, "deletion target type"),
        ({"number": True}, "deletion target number"),
        ({"number": "5"}, "deletion target number"),
        ({"number": 6}, "deletion target number"),
        ({"filteredCount": True}, "deletion filteredCount"),
        ({"filteredCount": "1"}, "deletion filteredCount"),
        ({"filteredCount": -1}, "deletion filteredCount"),
        ({"pageInfo": {"hasNextPage": "no", "endCursor": None}}, "deletion pageInfo"),
        ({"pageInfo": {"hasNextPage": False, "endCursor": 5}}, "deletion pageInfo"),
        ({"pageInfo": {"hasNextPage": 1, "endCursor": 5}}, "deletion pageInfo"),
        ({"pageInfo": {"hasNextPage": "x", "endCursor": "abc"}}, "deletion pageInfo"),
        ({"pageInfo": {"hasNextPage": True, "endCursor": None}}, "deletion cursor"),
        ({"pageInfo": {"hasNextPage": True, "endCursor": "bad cursor!"}}, "deletion cursor"),
        ({"nodes": {}}, "deletion nodes"),
    ],
)
def test_deletion_page_rejects_bad_shape_with_specific_detail(over, detail):
    with pytest.raises(VerifierError) as ei:
        ha._deletion_page(_dpage(**over), 5)
    assert ei.value.code == "payload-shape"
    assert ei.value.detail == detail


@pytest.mark.parametrize(
    "resp,detail",
    [
        ([], "deletion response is not a clean object"),
        ({"errors": []}, "deletion response is not a clean object"),
        ({"data": {"repository": []}}, "deletion target missing"),
        ({"data": {"repository": {"issueOrPullRequest": None}}}, "deletion target missing"),
    ],
)
def test_deletion_page_rejects_bad_envelope_with_specific_detail(resp, detail):
    with pytest.raises(VerifierError) as ei:
        ha._deletion_page(resp, 5)
    assert (ei.value.code, ei.value.detail) == ("payload-shape", detail)


def test_deletion_page_non_dict_intermediate_is_not_indexed():
    # a list at 'data' must be 'missing', not indexed by key
    with pytest.raises(VerifierError) as ei:
        ha._deletion_page({"data": ["x"]}, 5)
    assert ei.value.detail == "deletion target missing"


def test_deletion_page_accepts_valid_cursor_when_has_next():
    page = _dpage(pageInfo={"hasNextPage": True, "endCursor": "Y3Vyc29yOnYy"})
    assert ha._deletion_page(page, 5)[1:3] == (True, "Y3Vyc29yOnYy")


def test_deletion_page_node_errors_have_specific_detail():
    for node, detail in [
        ("x", "deletion node"),
        ({"__typename": "Other"}, "deletion node"),
    ]:
        with pytest.raises(VerifierError) as ei:
            ha._deletion_page(_dpage(nodes=[node]), 5)
        assert ei.value.detail == detail


def test_t_f_22_gh_call_timeout_is_capped_by_remaining_budget(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])
    gh = Gh()
    gql = Gql(events=gh.events)

    def ticking(endpoint, timeout=None):
        out = gh(endpoint, timeout)
        # Leave only 5s of the budget after the first call.
        clock[0] += ha.FETCH_BUDGET_SECONDS - 5 if len(gh.calls) == 1 else 0
        return out

    monkeypatch.setattr(ha, "_run_gh_get", ticking)
    monkeypatch.setattr(ha, "_run_gh_graphql", gql)
    fetch(REPO, 1, None)
    assert gh.timeouts[0] == ha.GH_TIMEOUT_SECONDS
    assert gh.timeouts[1:] and all(t == 5 for t in gh.timeouts[1:])
    assert gql.timeouts == [5]


def test_t_f_22b_seams_pass_timeout_to_subprocess(monkeypatch):
    seen: list[Any] = []

    def fake_run(argv, **kw):
        seen.append(kw["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    ha._run_gh_get("repos/o/r", timeout=7)
    _REAL_GQL("o", "r", 1, None, timeout=9)
    ha._run_gh_get("repos/o/r")
    assert seen == [7, 9, ha.GH_TIMEOUT_SECONDS]
