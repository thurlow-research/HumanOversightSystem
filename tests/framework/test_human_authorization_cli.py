"""CLI / exit-contract / audit / import-graph tests for human_authorization
(TD-2101 §7.5, T-CLI-*). In-process `main(argv)` with the three seams faked;
one subprocess smoke test; real git only where a test needs a real binding."""

from __future__ import annotations

import ast
import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.framework import human_authorization as ha
from scripts.framework.human_authorization import Binding, VerifierError, fingerprint, render_form
from tests.framework.test_human_authorization_binding import init, step_branch

ROOT = Path(__file__).resolve().parents[2]
_REAL_AUDIT = ha._audit_write  # captured before any fixture patches the seam
REPO = "o/r"
HEAD = "c" * 40
B = "patch:" + "a" * 40
FILES = ("docs/y.md", "scripts/x.py")
BINDING = Binding(B, "b" * 40, HEAD, "b" * 40, FILES)
T1, T2 = "2026-10-20T10:00:00Z", "2026-10-20T11:00:00Z"
LOCAL_ENV = 'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\nCOPILOT_BOT_LOGIN="copilot[bot]"\n'
REMOTE_ENV = 'BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"\n'

JSON_KEYS = {
    "schema",
    "verdict",
    "exit_code",
    "verification_id",
    "verified_at",
    "consumer",
    "repo",
    "step",
    "issue",
    "pr",
    "base",
    "base_sha",
    "head",
    "merge_base",
    "binding",
    "required",
    "covered",
    "unmet",
    "act",
    "overlap",
    "refusals",
    "error",
    "audit",
}
COMMON = {
    "event",
    "timestamp",
    "verified_at",
    "verification_id",
    "consumer",
    "repo",
    "step",
    "issue",
    "pr",
    "source",
    "binding",
    "head_sha",
    "base_sha",
    "merge_base",
}
ACCEPT_EXTRA = {
    "artifact",
    "authorized_by",
    "content_sha256",
    "decision",
    "comment_id",
    "url",
    "comment_issue",
    "actor_type",
    "covered",
    "unmet",
    "reviewed_files",
    "overlap",
}
REFUSED_EXTRA = {
    "comment_id",
    "url",
    "comment_issue",
    "login",
    "actor_type",
    "content_sha256",
    "reason",
    "detail",
}


def _b64(text: str | bytes) -> str:
    raw = text.encode() if isinstance(text, str) else text
    return base64.b64encode(raw).decode()


def _file(text) -> dict:
    return {"type": "file", "encoding": "base64", "content": _b64(text)}


def _raw(cid, login="scottthurlow", body="", created=T1, updated=None, utype="User"):
    return {
        "id": cid,
        "html_url": f"https://github.com/o/r/issues/1#issuecomment-{cid}",
        "body": body,
        "created_at": created,
        "updated_at": updated or created,
        "user": {"login": login, "type": utype},
    }


def _form(items=("C7",), binding=B, step=5):
    return render_form(step, binding, items, FILES)


class Env:
    """One CLI run's world: repo root, fake GitHub, fake audit writer."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.mp = monkeypatch
        self.root = tmp_path / "root"
        (self.root / "scripts" / "framework").mkdir(parents=True)
        (self.root / "scripts" / "framework" / "machine-accounts.env").write_text(LOCAL_ENV)
        self.comments: list[dict] = []
        self.codeowners: str | dict = "* @ScottThurlow\n"
        self.remote_env: str | dict = REMOTE_ENV
        self.events: list[dict] = []
        self.audit_ok = lambda event: True
        self.gh_calls: list[str] = []
        self.deletions: list[dict] = []  # CommentDeletedEvent nodes returned for issue 1
        self.gql_error: Exception | None = None  # both gql kinds
        self.edits_error: Exception | None = None  # read 7 only
        self.edited_at: dict[int, str] = {}  # comment id -> GraphQL lastEditedAt
        self.extra_probe_ids: list[int] = []  # probe-only ids for issue 1 (TD-2101 §10.5.5 R1)
        monkeypatch.delenv("BOT_ACCOUNTS", raising=False)
        monkeypatch.setattr(ha, "compute_binding", lambda *a, **k: BINDING)
        monkeypatch.setattr(ha, "_run_gh_get", self._gh)
        monkeypatch.setattr(ha, "_run_gh_graphql", self._gql)
        monkeypatch.setattr(ha, "_audit_write", self._audit)

    def _gh(self, endpoint, timeout=None):
        self.gh_calls.append(endpoint)
        if endpoint == f"repos/{REPO}":
            return {"default_branch": "main"}
        if endpoint.startswith(f"repos/{REPO}/contents/.github/CODEOWNERS"):
            return self.codeowners if isinstance(self.codeowners, dict) else _file(self.codeowners)
        if "machine-accounts.env" in endpoint:
            return self.remote_env if isinstance(self.remote_env, dict) else _file(self.remote_env)
        if "/comments?" in endpoint:
            return list(self.comments) if "/issues/1/" in endpoint else []
        raise VerifierError("api-error", "unexpected")

    def _gql(self, kind, owner, name, number, after, timeout=None):
        if self.gql_error is not None:
            raise self.gql_error
        if kind == "edits":
            if self.edits_error is not None:
                raise self.edits_error
            nodes = (
                [
                    {"fullDatabaseId": str(c["id"]), "lastEditedAt": self.edited_at.get(c["id"])}
                    for c in self.comments
                ]
                + [{"fullDatabaseId": str(i), "lastEditedAt": None} for i in self.extra_probe_ids]
                if number == 1
                else []
            )
            conn_key, count_key = "comments", "totalCount"
        else:
            nodes = list(self.deletions) if number == 1 else []
            conn_key, count_key = "timelineItems", "filteredCount"
        return {
            "data": {
                "repository": {
                    "issueOrPullRequest": {
                        "__typename": "Issue",
                        "number": number,
                        conn_key: {
                            count_key: len(nodes),
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": nodes,
                        },
                    }
                }
            }
        }

    def _audit(self, event, audit_root):
        if self.audit_ok(event):
            self.events.append(event)
            return True
        return False

    def argv(self, *extra, consumer="evaluator", require=("C7",), json_out=True):
        a = [
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
            HEAD,
            "--consumer",
            consumer,
            "--repo-root",
            str(self.root),
        ]
        for r in require:
            a += ["--require", r]
        if json_out:
            a.append("--json")
        return a + list(extra)

    def run(self, capsys, *extra, **kw):
        rc = ha.main(self.argv(*extra, **kw))
        out = capsys.readouterr()
        text = out.out.strip()
        return rc, (json.loads(text) if text.startswith("{") else text), out.err


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def test_t_cli_1_no_args_is_exit_2_with_empty_stdout():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.framework.human_authorization", "verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2 and r.stdout == ""
    assert r.stderr.startswith("human_authorization: usage:")


USAGE_CASES = {
    "bad-repo": lambda a: a.__setitem__(a.index("--repo") + 1, "no-slash"),
    "dot-owner": lambda a: a.__setitem__(a.index("--repo") + 1, "./r"),
    "dotdot-owner": lambda a: a.__setitem__(a.index("--repo") + 1, "../r"),
    "dot-name": lambda a: a.__setitem__(a.index("--repo") + 1, "o/."),
    "dotdot-name": lambda a: a.__setitem__(a.index("--repo") + 1, "o/.."),
    "bad-step": lambda a: a.__setitem__(a.index("--step") + 1, "0"),
    "bad-issue": lambda a: a.__setitem__(a.index("--issue") + 1, "x"),
    "bad-head": lambda a: a.__setitem__(a.index("--head") + 1, "abc"),
    "upper-head": lambda a: a.__setitem__(a.index("--head") + 1, "C" * 40),
    "dash-base": lambda a: a.__setitem__(a.index("--base") + 1, "-x"),
    "bad-base": lambda a: a.__setitem__(a.index("--base") + 1, "a b"),
    "bad-item": lambda a: a.__setitem__(a.index("--require") + 1, "c7"),
    "item-too-long": lambda a: a.__setitem__(a.index("--require") + 1, "BF:" + "a" * 80),
    "bad-consumer": lambda a: a.__setitem__(a.index("--consumer") + 1, "human"),
    "pr-equals-issue": lambda a: a.extend(["--pr", "1"]),
    "bad-pr": lambda a: a.extend(["--pr", "07"]),
    "audit-on-change-evaluator": lambda a: a.append("--audit-on-change"),
    "unknown-flag": lambda a: a.append("--nope"),
    "missing-require": lambda a: [a.pop(a.index("--require")), a.pop(a.index("C7"))],
    "unknown-subcommand": lambda a: a.__setitem__(0, "frobnicate"),
}


@pytest.mark.parametrize("name", sorted(USAGE_CASES))
def test_t_cli_2_usage_errors(env, capsys, name):
    argv = env.argv()
    USAGE_CASES[name](argv)
    assert ha.main(argv) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.startswith("human_authorization: usage:")
    assert env.events == [] and env.gh_calls == []


def test_t_cli_3_exit_0_authorized(env, capsys):
    env.comments = [_raw(10, body=_form())]
    rc, js, _ = env.run(capsys)
    assert rc == 0 and set(js) == JSON_KEYS
    assert js["schema"] == ha.SCHEMA and js["verdict"] == "authorized" and js["exit_code"] == 0
    assert js["covered"] == ["C7"] and js["unmet"] == [] and js["binding"] == B
    assert js["act"]["decision"] == "authorize" and js["act"]["login"] == "scottthurlow"
    assert js["overlap"] == list(FILES) and js["error"] is None
    assert js["audit"] == {"written": 1, "failed": 0, "suppressed": False}
    assert len(js["verification_id"]) == 32 and ha.TS_RE.match(js["verified_at"])
    assert [e["event"] for e in env.events] == ["human-authorization"]


def test_text_summary_line(env, capsys):
    env.comments = [_raw(10, body=_form())]
    rc, text, _ = env.run(capsys, json_out=False)
    assert rc == 0
    assert (
        text
        == f"human_authorization: verdict=authorized step=5 binding={B} covered=C7 unmet=- refusals=0 error=none"
    )


def test_t_cli_4_exit_1_decline(env, capsys):
    env.comments = [_raw(10, body="/hos decline step=5")]
    rc, js, _ = env.run(capsys)
    assert rc == 1 and js["verdict"] == "not-authorized" and js["covered"] == []
    assert js["act"]["decision"] == "decline"
    assert [r["reason"] for r in js["refusals"]] == ["declined"]
    assert [e["event"] for e in env.events] == ["human-authorization-refused"]
    assert env.events[0]["reason"] == "declined"


def test_no_act_is_exit_1_with_no_events(env, capsys):
    rc, js, _ = env.run(capsys)
    assert rc == 1 and js["act"] is None and js["unmet"] == ["C7"] and env.events == []


EXIT3_CODES = sorted(ha.ERROR_CODES)
GIT_CODES = {
    "git-failure",
    "ambiguous-merge-base",
    "empty-diff",
    "unrepresentable-path",
    "unsupported-object-format",
    "patch-too-large",
}


@pytest.mark.parametrize("code", EXIT3_CODES)
def test_t_cli_5_every_error_code_is_exit_3(env, capsys, monkeypatch, code):
    env.comments = [_raw(10, body=_form())]  # a valid act that must NOT leak into the verdict
    err = VerifierError(code, "boom")
    if code in GIT_CODES:
        monkeypatch.setattr(ha, "compute_binding", lambda *a, **k: (_ for _ in ()).throw(err))
    else:
        monkeypatch.setattr(ha, "fetch", lambda *a, **k: (_ for _ in ()).throw(err))
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["verdict"] == "undetermined" and js["exit_code"] == 3
    assert js["error"]["code"] == code
    assert (
        js["covered"] == [] and js["unmet"] == ["C7"] and js["refusals"] == [] and js["act"] is None
    )
    assert js["overlap"] == []
    assert len(env.events) == 1
    ev = env.events[0]
    assert (
        ev["event"] == "human-authorization-refused"
        and ev["reason"] == "api-failure"
        and ev["detail"] == code
    )
    assert "comment_id" not in ev
    assert js["binding"] == (None if code in GIT_CODES else B)


def test_t_cli_5_binding_phase_budget_exhausted_is_exit_3(env, capsys, monkeypatch):
    env.comments = [_raw(10, body=_form())]
    err = VerifierError("budget-exhausted", "binding budget exceeded")
    monkeypatch.setattr(ha, "compute_binding", lambda *a, **k: (_ for _ in ()).throw(err))
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["error"]["code"] == "budget-exhausted" and js["binding"] is None
    assert js["covered"] == [] and js["refusals"] == []
    assert [e["detail"] for e in env.events] == ["budget-exhausted"]


def test_t_cli_6_local_machine_accounts_absent(env, capsys):
    (env.root / "scripts" / "framework" / "machine-accounts.env").unlink()
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["error"]["code"] == "machine-accounts-unreadable" and js["binding"] == B


def test_t_cli_6_local_machine_accounts_unreadable(env, capsys):
    path = env.root / "scripts" / "framework" / "machine-accounts.env"
    path.chmod(0o000)
    try:
        rc, js, _ = env.run(capsys)
    finally:
        path.chmod(0o644)
    assert rc == 3 and js["error"]["code"] == "machine-accounts-unreadable"


def test_t_cli_6_local_machine_accounts_undecodable(env, capsys):
    (env.root / "scripts" / "framework" / "machine-accounts.env").write_bytes(b"\xff\xfe\x00bad")
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["error"]["code"] == "machine-accounts-unreadable"


def test_t_cli_7_bot_set_empty(env, capsys):
    (env.root / "scripts" / "framework" / "machine-accounts.env").write_text("OTHER=1\n")
    env.remote_env = "OTHER=2\n"
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["error"]["code"] == "bot-accounts-empty"


def test_t_cli_8_codeowners_with_only_teams(env, capsys):
    env.codeowners = "* @org/team\n# c\n"
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["error"]["code"] == "codeowners-empty"


def test_t_cli_9_working_tree_codeowners_is_never_read(env, capsys):
    (env.root / ".github").mkdir()
    (env.root / ".github" / "CODEOWNERS").write_text("* @alice @ScottThurlow\n")
    env.comments = [_raw(10, login="alice", body=_form())]
    rc, js, _ = env.run(capsys)
    assert rc == 1 and [r["reason"] for r in js["refusals"]] == ["not-codeowner"]
    # And a login only in the working-tree file is not rescued even when it is the sole human.
    env.comments = [_raw(11, login="scottthurlow", body=_form())]
    env.codeowners = "* @someone-else\n"
    rc, js, _ = env.run(capsys)
    assert rc == 1 and [r["reason"] for r in js["refusals"]] == ["not-codeowner"]


def test_remote_machine_accounts_baseline_is_unioned(env, capsys):
    env.comments = [_raw(10, login="scottthurlow-claude[bot]", utype="User", body=_form())]
    env.codeowners = "* @ScottThurlow @scottthurlow-claude[bot]\n"
    rc, js, _ = env.run(capsys)
    assert rc == 1 and [r["reason"] for r in js["refusals"]] == ["bot-actor"]


def test_t_cli_10_events_have_exactly_the_specified_fields_and_order(
    env, capsys, tmp_path, monkeypatch
):
    audit_root = tmp_path / "audit-root"
    audit_root.mkdir()
    env.comments = [
        _raw(5, login="alice", body=_form(), created="2026-10-20T09:00:00Z"),
        _raw(
            6,
            login="scottthurlow",
            body="/hos authorize step=5 binding=patch:zz\ncovers: C7",
            created="2026-10-20T09:30:00Z",
        ),
        _raw(7, login="scottthurlow", body=_form(), created=T1),
    ]
    monkeypatch.setattr(ha, "_audit_write", _REAL_AUDIT)
    rc, js, _ = env.run(capsys, "--audit-root", str(audit_root))
    assert rc == 0 and js["audit"]["written"] == 3 and js["audit"]["failed"] == 0
    records = sorted((audit_root / "audit" / "log").rglob("*.json"))
    events = [json.loads(p.read_text()) for p in records]
    assert len(events) == 3
    by_comment = {e["comment_id"]: e for e in events}
    assert set(by_comment) == {5, 6, 7}
    assert (
        set(by_comment[5]) == COMMON | REFUSED_EXTRA and by_comment[5]["reason"] == "not-codeowner"
    )
    assert set(by_comment[6]) == COMMON | REFUSED_EXTRA and by_comment[6]["detail"] == "bad-binding"
    assert by_comment[6]["reason"] == "malformed"
    assert (
        set(by_comment[7]) == COMMON | ACCEPT_EXTRA
        and by_comment[7]["event"] == "human-authorization"
    )
    assert by_comment[7]["covered"] == ["C7"] and by_comment[7]["reviewed_files"] == list(FILES)
    assert by_comment[7]["artifact"] == by_comment[7]["url"]
    assert len({e["verification_id"] for e in events}) == 1 and {e["source"] for e in events} == {
        "issue-comment"
    }


def test_t_cli_10_events_are_written_in_created_then_id_order(env, capsys):
    env.comments = [
        _raw(9, login="alice", body=_form(), created=T2),
        _raw(3, login="alice", body=_form(), created=T1),
        _raw(2, login="alice", body=_form(), created=T1),
    ]
    env.run(capsys)
    assert [e["comment_id"] for e in env.events] == [2, 3, 9]


def test_t_cli_11_acceptance_write_failure_is_exit_4(env, capsys):
    env.comments = [_raw(10, body=_form())]
    env.audit_ok = lambda e: e["event"] != "human-authorization"
    rc, js, err = env.run(capsys)
    assert rc == 4 and js["verdict"] == "audit-failed" and js["exit_code"] == 4
    assert js["covered"] == [] and js["unmet"] == ["C7"] and js["audit"]["failed"] == 1
    assert "WARN audit-write-failed event=human-authorization comment_id=10" in err


def test_t_cli_11_refusal_write_failure_keeps_the_exit(env, capsys):
    env.comments = [
        _raw(5, login="alice", body=_form(), created="2026-10-20T09:00:00Z"),
        _raw(10, body=_form()),
    ]
    env.audit_ok = lambda e: e["event"] == "human-authorization"
    rc, js, err = env.run(capsys)
    assert rc == 0 and js["audit"] == {"written": 1, "failed": 1, "suppressed": False}
    assert "WARN audit-write-failed event=human-authorization-refused comment_id=5" in err


def test_t_cli_12_partial_coverage_with_failed_acceptance_write_covers_nothing(env, capsys):
    env.comments = [_raw(10, body=_form(items=("C7",)))]
    env.audit_ok = lambda e: e["event"] != "human-authorization"
    rc, js, _ = env.run(capsys, require=("C7", "BF:x"))
    assert rc == 4 and js["covered"] == [] and js["unmet"] == ["C7", "BF:x"]


def test_t_cli_12_partial_coverage_is_exit_1_with_covered_when_written(env, capsys):
    env.comments = [_raw(10, body=_form(items=("C7",)))]
    rc, js, _ = env.run(capsys, require=("C7", "BF:x"))
    assert rc == 1 and js["covered"] == ["C7"] and js["unmet"] == ["BF:x"]
    assert [e["event"] for e in env.events] == ["human-authorization"]
    assert env.events[0]["unmet"] == ["BF:x"]


def test_t_cli_13_audit_on_change(env, capsys):
    env.comments = [_raw(5, login="alice", body=_form(), created="2026-10-20T09:00:00Z")]
    kw = dict(consumer="overseer")
    rc1, js1, _ = env.run(capsys, "--audit-on-change", **kw)
    assert rc1 == 1 and js1["audit"] == {"written": 1, "failed": 0, "suppressed": False}
    record = env.root / ".claudetmp" / "human-authorization" / "audit-on-change.json"
    assert record.is_file()
    rc2, js2, _ = env.run(capsys, "--audit-on-change", **kw)
    assert rc2 == 1 and js2["audit"] == {"written": 0, "failed": 0, "suppressed": True}
    assert len(env.events) == 1
    env.comments.append(_raw(6, login="bob", body=_form(), created=T1))
    rc3, js3, _ = env.run(capsys, "--audit-on-change", **kw)
    assert js3["audit"]["suppressed"] is False and js3["audit"]["written"] == 2
    assert len(env.events) == 3


def test_t_cli_13_failed_write_does_not_update_the_record(env, capsys):
    env.comments = [_raw(5, login="alice", body=_form())]
    record = env.root / ".claudetmp" / "human-authorization" / "audit-on-change.json"
    env.audit_ok = lambda e: False
    env.run(capsys, "--audit-on-change", consumer="overseer")
    assert not record.exists()
    env.audit_ok = lambda e: True
    rc, js, _ = env.run(capsys, "--audit-on-change", consumer="overseer")
    assert js["audit"]["written"] == 1 and js["audit"]["suppressed"] is False and record.exists()


def test_t_cli_13_authorized_verdict_stays_exit_0_when_suppressed(env, capsys):
    env.comments = [_raw(10, body=_form())]
    assert env.run(capsys, "--audit-on-change", consumer="overseer")[0] == 0
    rc, js, _ = env.run(capsys, "--audit-on-change", consumer="overseer")
    assert rc == 0 and js["audit"]["suppressed"] is True and js["covered"] == ["C7"]


def test_t_cli_13_corrupt_record_is_treated_as_absent(env, capsys):
    env.comments = [_raw(5, login="alice", body=_form())]
    record = env.root / ".claudetmp" / "human-authorization" / "audit-on-change.json"
    record.parent.mkdir(parents=True)
    record.write_text("{not json")
    rc, js, _ = env.run(capsys, "--audit-on-change", consumer="overseer")
    assert js["audit"]["written"] == 1 and json.loads(record.read_text())["v"] == 1


def test_t_cli_14_forged_record_cannot_change_the_verdict(env, capsys):
    env.comments = [_raw(10, body="/hos decline step=5")]
    record = env.root / ".claudetmp" / "human-authorization" / "audit-on-change.json"
    record.parent.mkdir(parents=True)
    forged = fingerprint(0, ("C7",), (), 10, "authorize", [], None)
    record.write_text(json.dumps({"v": 1, "entries": {f"{REPO}#5#{B}": forged}}))
    rc, js, _ = env.run(capsys, "--audit-on-change", consumer="overseer")
    assert rc == 1 and js["verdict"] == "not-authorized" and js["covered"] == []
    assert js["audit"]["suppressed"] is False and js["audit"]["written"] == 1


def test_t_cli_14_record_never_makes_an_unauthorized_step_authorized(env, capsys):
    record = env.root / ".claudetmp" / "human-authorization" / "audit-on-change.json"
    record.parent.mkdir(parents=True)
    fp = fingerprint(1, (), ("C7",), None, None, [], None)
    record.write_text(json.dumps({"v": 1, "entries": {f"{REPO}#5#{B}": fp}}))
    rc, js, _ = env.run(capsys, "--audit-on-change", consumer="overseer")
    assert rc == 1 and js["audit"]["suppressed"] is True and js["covered"] == []


def test_t_cli_15_binding_subcommand_matches_compute_binding(tmp_path, capsys, monkeypatch):
    monkeypatch.undo()
    repo = init(tmp_path)
    head = step_branch(repo)
    want = ha.compute_binding(repo, "main", head)
    assert ha.main(["binding", "--repo-root", str(repo), "--base", "main", "--head", head]) == 0
    assert capsys.readouterr().out.strip() == want.binding
    assert (
        ha.main(["binding", "--repo-root", str(repo), "--base", "main", "--head", head, "--json"])
        == 0
    )
    got = json.loads(capsys.readouterr().out)
    assert got == {
        "binding": want.binding,
        "base_sha": want.base_sha,
        "head": head,
        "merge_base": want.merge_base,
        "diff_files": list(want.diff_files),
    }
    assert ha.main(["binding", "--repo-root", str(repo), "--base", "nope", "--head", head]) == 3


def test_t_cli_15_render_request_with_verdict_file(tmp_path, capsys):
    repo = init(tmp_path)
    head = step_branch(repo)
    verdict = tmp_path / "verdict.json"
    verdict.write_text(
        json.dumps(
            {
                "refusals": [
                    {"reason": "malformed-latest", "url": "https://x/c/1", "detail": "bad-binding"}
                ]
            }
        )
    )
    findings = tmp_path / "findings.json"
    findings.write_text(
        json.dumps([{"id": "dep-mapper-low", "source": "dep-mapper", "description": "LOW blast"}])
    )
    argv = [
        "render-request",
        "--repo-root",
        str(repo),
        "--repo",
        REPO,
        "--step",
        "5",
        "--issue",
        "1",
        "--pr",
        "2",
        "--base",
        "main",
        "--head",
        head,
        "--require",
        "C7,BF:dep-mapper-low",
    ]
    assert ha.main(argv + ["--verdict-file", str(verdict), "--findings-file", str(findings)]) == 0
    out = capsys.readouterr().out
    assert "https://github.com/o/r/issues/1" in out and "https://github.com/o/r/pull/2" in out
    assert "(https://x/c/1) could not be read (bad-binding)" in out
    assert "- BF:dep-mapper-low — dep-mapper: LOW blast" in out
    b = ha.compute_binding(repo, "main", head)
    assert render_form(5, b.binding, ("C7", "BF:dep-mapper-low"), b.diff_files) in out


@pytest.mark.parametrize("content", ["not json", json.dumps([1]), json.dumps({"refusals": "x"})])
def test_render_request_bad_verdict_file_is_usage_error(tmp_path, capsys, content):
    repo = init(tmp_path)
    head = step_branch(repo)
    bad = tmp_path / "v.json"
    bad.write_text(content)
    argv = [
        "render-request",
        "--repo-root",
        str(repo),
        "--repo",
        REPO,
        "--step",
        "5",
        "--issue",
        "1",
        "--base",
        "main",
        "--head",
        head,
        "--require",
        "C7",
        "--verdict-file",
        str(bad),
    ]
    assert ha.main(argv) == 2
    assert ha.main(argv[:-2] + ["--findings-file", str(tmp_path / "missing.json")]) == 2


def test_render_request_does_no_network_and_no_audit(tmp_path, monkeypatch, capsys):
    repo = init(tmp_path)
    head = step_branch(repo)
    for seam in ("_run_gh_get", "_audit_write"):
        monkeypatch.setattr(ha, seam, lambda *a, **k: pytest.fail("seam used"))
    argv = [
        "render-request",
        "--repo-root",
        str(repo),
        "--repo",
        REPO,
        "--step",
        "5",
        "--issue",
        "1",
        "--base",
        "main",
        "--head",
        head,
        "--require",
        "C7",
    ]
    assert ha.main(argv) == 0


def test_t_cli_16_import_graph():
    tree = ast.parse(
        (ROOT / "scripts" / "framework" / "human_authorization.py").read_text(encoding="utf-8")
    )
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.append(node.module or "")
    allowed_framework = {
        "scripts.framework.require_human_approval",
        "scripts.framework.requester_trust",
    }
    for name in names:
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names or name in allowed_framework, name
        assert not name.startswith(("scripts.automation", "scripts.oversight")), name
    assert allowed_framework <= set(names)
    src = (ROOT / "scripts" / "framework" / "human_authorization.py").read_text(encoding="utf-8")
    code = src.split("from __future__ import annotations", 1)[1]
    for ln in code.splitlines():
        if "scripts.oversight" in ln:
            assert '"scripts.oversight.lib.audit_log"' in ln, ln
        assert "scripts.automation" not in ln, ln


def test_t_cli_17_determinism(env, capsys):
    env.comments = [_raw(5, login="alice", body=_form()), _raw(10, body=_form())]

    def strip(js):
        return {k: v for k, v in js.items() if k not in {"verification_id", "verified_at"}}

    _, a, _ = env.run(capsys)
    _, b, _ = env.run(capsys)
    assert strip(a) == strip(b) and a["verification_id"] != b["verification_id"]


def test_json_is_one_compact_sorted_line(env, capsys):
    env.comments = [_raw(10, body=_form())]
    ha.main(env.argv())
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and ", " not in out and ": " not in out
    keys = list(json.loads(out))
    assert keys == sorted(keys)


def test_comment_body_never_reaches_events_or_stdout(env, capsys):
    secret = "SECRET-xyz"  # pragma: allowlist secret
    env.comments = [
        _raw(5, body=f"/hos authorize step=5 binding={B} {secret}=1"),
        _raw(6, login="alice", body=_form() + f"\n---\n{secret}"),
    ]
    rc, js, err = env.run(capsys)
    dumped = json.dumps(js) + err + json.dumps(env.events)
    assert secret not in dumped
    assert rc == 1


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--step", "5\n"),
        ("--issue", "1\n"),
        ("--head", "c" * 40 + "\n"),
        ("--base", "main\n"),
        ("--repo", "o/r\n"),
    ],
)
def test_trailing_newline_is_rejected_as_usage(env, capsys, flag, value):
    argv = env.argv()
    argv[argv.index(flag) + 1] = value
    assert ha.main(argv) == 2
    assert env.gh_calls == []


def test_trailing_newline_is_rejected_by_item_and_binding_validators():
    assert ha.main(["verify"]) == 2
    for rx, ok in (
        (ha.NUM_RE, "5"),
        (ha.SHA_RE, "a" * 40),
        (ha.BINDING_RE, "patch:" + "a" * 40),
        (ha.ITEM_RE, "C7"),
    ):
        assert rx.fullmatch(ok) and not rx.fullmatch(ok + "\n")
    assert not ha._valid_item("C7\n")
    with pytest.raises(ValueError):
        ha.compute_binding(".", "main", "a" * 40 + "\n")
    assert (
        ha.parse_act("/hos authorize step=5 binding=patch:" + "a" * 40 + "\ncovers: C7\n")
        is not None
    )


def test_unexpected_exception_in_verification_is_exit_3_never_1(env, capsys, monkeypatch):
    env.comments = [_raw(10, body=_form())]

    def boom(*a, **k):
        raise KeyError("surprise")

    monkeypatch.setattr(ha, "decide", boom)
    rc, js, err = env.run(capsys)
    assert rc == 3 and js["verdict"] == "undetermined" and js["error"]["code"] == "api-error"
    assert js["covered"] == [] and js["unmet"] == ["C7"] and js["refusals"] == []
    assert "internal-error type=KeyError" in err and "surprise" not in err
    assert [e["reason"] for e in env.events] == ["api-failure"]


def test_unexpected_exception_outside_verification_is_exit_3(env, capsys, monkeypatch):
    env.comments = [_raw(10, body=_form())]
    monkeypatch.setattr(
        ha, "_store_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    rc = ha.main(env.argv("--audit-on-change", consumer="overseer"))
    assert rc == 3
    assert "internal-error type=RuntimeError" in capsys.readouterr().err


def test_refusal_writes_are_abandoned_after_the_first_failure(env, capsys):
    env.comments = [
        _raw(1, login="alice", body=_form(), created="2026-10-20T09:00:00Z"),
        _raw(2, login="bob", body=_form(), created="2026-10-20T09:01:00Z"),
        _raw(3, login="carol", body=_form(), created="2026-10-20T09:02:00Z"),
        _raw(10, body=_form()),
    ]
    attempts: list[str] = []

    def audit_ok(event):
        attempts.append(event["event"])
        return event["event"] == "human-authorization"

    env.audit_ok = audit_ok
    rc, js, err = env.run(capsys)
    assert rc == 0
    assert attempts == ["human-authorization-refused", "human-authorization"]
    assert err.count("WARN audit-write-failed") == 1
    assert js["audit"] == {"written": 1, "failed": 3, "suppressed": False}


def test_acceptance_failure_still_exit_4_after_refusal_writes_abandoned(env, capsys):
    env.comments = [
        _raw(1, login="alice", body=_form(), created="2026-10-20T09:00:00Z"),
        _raw(10, body=_form()),
    ]
    env.audit_ok = lambda e: False
    rc, js, err = env.run(capsys)
    assert rc == 4 and js["covered"] == []
    assert err.count("WARN audit-write-failed") == 2


def test_t_cli_18_deleted_newer_decline_end_to_end(env, capsys):
    env.comments = [_raw(10, body=_form())]
    env.deletions = [
        {
            "__typename": "CommentDeletedEvent",
            "databaseId": 901,
            "createdAt": "2026-10-20T12:00:00Z",
            "deletedCommentAuthor": {"login": "ScottThurlow"},
        }
    ]
    rc, js, _ = env.run(capsys)
    assert rc == 1 and js["verdict"] == "not-authorized" and js["covered"] == []
    assert js["act"]["decision"] == "authorize"
    assert [(r["reason"], r["detail"]) for r in js["refusals"]] == [("deleted-later", "event:901")]
    assert [e["event"] for e in env.events] == ["human-authorization-refused"]
    assert env.events[0]["reason"] == "deleted-later" and env.events[0]["detail"] == "event:901"


def test_t_cli_19_decide_receives_the_fetched_deletions(env, capsys, monkeypatch):
    env.comments = [_raw(10, body=_form())]
    seen = {}
    real_fetch = ha.fetch

    def spy_fetch(*a, **k):
        seen["fetched"] = real_fetch(*a, **k)
        return seen["fetched"]

    real_decide = ha.decide

    def spy_decide(*a, **k):
        seen["deletions"] = k["deletions"]
        return real_decide(*a, **k)

    monkeypatch.setattr(ha, "fetch", spy_fetch)
    monkeypatch.setattr(ha, "decide", spy_decide)
    rc, _, _ = env.run(capsys)
    assert rc == 0
    assert seen["deletions"] is seen["fetched"].deletions


def test_t_cli_20_unreadable_deletions_are_exit_3_not_a_decision(env, capsys):
    env.comments = [_raw(10, body=_form())]
    env.gql_error = VerifierError("api-error", "gh api exit 1")
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["verdict"] == "undetermined" and js["covered"] == []
    assert js["error"]["code"] == "api-error" and js["act"] is None and js["refusals"] == []
    assert [(e["event"], e["detail"]) for e in env.events] == [
        ("human-authorization-refused", "api-error")
    ]


def test_t_cli_21_same_second_edit_is_refused_end_to_end(env, capsys):
    env.comments = [_raw(10, body=_form(), created=T1, updated=T1)]
    env.edited_at = {10: T1}
    rc, js, _ = env.run(capsys)
    assert rc == 1 and js["verdict"] == "not-authorized" and js["covered"] == []
    assert [r["reason"] for r in js["refusals"]] == ["edited"]


def test_t_cli_22_unreadable_edit_probe_is_exit_3_not_a_decision(env, capsys):
    env.comments = [_raw(10, body=_form())]
    env.edits_error = VerifierError("api-error", "gh api exit 1")
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["verdict"] == "undetermined" and js["covered"] == []
    assert js["error"]["code"] == "api-error" and js["act"] is None and js["refusals"] == []
    assert [(e["event"], e["detail"]) for e in env.events] == [
        ("human-authorization-refused", "api-error")
    ]


def test_t_cli_23_probe_only_comment_is_exit_3_not_a_decision(env, capsys):
    env.comments = [_raw(10, body=_form())]
    env.extra_probe_ids = [99]
    rc, js, _ = env.run(capsys)
    assert rc == 3 and js["verdict"] == "undetermined" and js["covered"] == []
    assert js["error"]["code"] == "payload-shape" and js["act"] is None
    assert [(e["event"], e["detail"]) for e in env.events] == [
        ("human-authorization-refused", "payload-shape")
    ]


@pytest.mark.parametrize("repo", ["o/r", "o/.github", "a.b/c..d", "o/..."])
def test_t_cli_24_valid_repo_accepts(repo):
    assert ha._valid_repo(repo) is True


@pytest.mark.parametrize("repo", ["./r", "../r", "o/.", "o/..", "o/r/x"])
def test_t_cli_24_valid_repo_rejects(repo):
    assert ha._valid_repo(repo) is False


def test_t_cli_24_fetch_rejects_a_dot_segment_before_any_call(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(ha, "_run_gh_get", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(ha, "_run_gh_graphql", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError):
        ha.fetch("o/..", 1, None)
    assert calls == []
