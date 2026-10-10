"""Tests for bootstrap/escalate_to_human.sh (#1644 T3.0a, ADR-1644 AD-C6 H5 / AD-C10).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH. The gh stub
is a small Python program that serves issue / comments / events / comment-by-id from a
JSON config, logs "METHOD PATH" per call in order, and captures stdin bodies. Test IDs
T-ESC1..T-ESC23 follow docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0a-no-idle-selection.md 7.3.
Nothing here ever reaches GitHub.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SRC = REPO_ROOT / "bootstrap" / "escalate_to_human.sh"
CFC_SRC = REPO_ROOT / "bootstrap" / "lib" / "comment_format_check.sh"

BOT = "hos-worker-hos[bot]"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "MINT $*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
if [[ "${EMPTY_LOGIN:-}" == "1" ]]; then
  printf "export HOS_BOT_LOGIN=''\\n"
else
  printf "export HOS_BOT_LOGIN='hos-worker-hos[bot]'\\n"
fi
"""

GIT_STUB = """#!/usr/bin/env bash
i=0
if [[ "$1" == "-C" ]]; then i=2; fi
sub="${@:$((i+1)):1}"
case "$sub" in
  remote) echo "https://github.com/test-owner/test-repo.git" ;;
esac
exit 0
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL $*" >> "$CAPTURE_FILE"
exit 0
"""

AUDIT_LIB_STUB = """#!/usr/bin/env bash
audit_write_event() {
    printf '%s\\n' "$1" >> "$AUDIT_FILE"
}
"""

GH_STUB = r"""#!/usr/bin/env python3
import json, os, re, sys
cfg = json.load(open(os.environ["GH_CFG"]))
calls = os.environ["CALLS_FILE"]
bodies = os.environ["BODIES_FILE"]
args = sys.argv[1:]
if not args or args[0] != "api":
    sys.exit(1)
args = args[1:]
method, has_input, pos = "GET", False, []
i = 0
while i < len(args):
    if args[i] == "--method":
        method = args[i + 1]; i += 2
    elif args[i] == "--input":
        has_input = True; i += 2
    else:
        pos.append(args[i]); i += 1
path = pos[0]
stdin = sys.stdin.read() if has_input else None
with open(calls, "a") as f:
    f.write(f"{method} {path}\n")
if stdin is not None:
    with open(bodies, "a") as f:
        f.write(json.dumps({"method": method, "path": path, "body": json.loads(stdin)}) + "\n")

def logged():
    return [line.strip() for line in open(calls)]

def fails(key):
    return key in cfg.get("fail", [])

def out(obj):
    print(json.dumps(obj))
    sys.exit(0)

m = re.match(r"repos/[^/]+/[^/]+/(.*)$", path)
rest = m.group(1)

if method == "POST" and re.fullmatch(r"issues/\d+/comments", rest):
    if fails("POST comment"):
        sys.exit(1)
    if "post_comment_response" in cfg:
        resp = dict(cfg["post_comment_response"])
    else:
        resp = {"id": 555, "html_url": "https://github.com/test-owner/test-repo/issues/7#issuecomment-555"}
    if resp.get("id") is not None:
        with open(os.environ["POSTED_FILE"], "w") as f:
            json.dump({"id": resp["id"], "body": stdin and json.loads(stdin)["body"]}, f)
    out(resp)

if method == "GET" and re.fullmatch(r"issues/comments/\d+", rest):
    if fails("GET readback"):
        sys.exit(1)
    posted = json.load(open(os.environ["POSTED_FILE"]))
    rb = cfg.get("readback", {})
    body = posted["body"]
    if rb.get("strip_marker"):
        body = body.split("<!-- hos-escalation")[0]
    out({"id": posted["id"], "body": body,
         "user": {"login": rb.get("login", "hos-worker-hos[bot]"), "type": rb.get("type", "Bot")},
         "html_url": "x"})

if method == "POST" and re.fullmatch(r"issues/\d+/labels", rest):
    if fails("POST labels"):
        sys.exit(1)
    out([{"name": "needs-human"}])

if method == "GET" and re.fullmatch(r"issues/\d+/comments\?per_page=100&page=\d+", rest):
    if fails("GET comments"):
        sys.exit(1)
    p = re.search(r"&page=(\d+)", rest).group(1)
    out(cfg.get("comments_pages", {}).get(p, []))

if method == "GET" and re.fullmatch(r"issues/\d+/events\?per_page=100&page=\d+", rest):
    if fails("GET events"):
        sys.exit(1)
    p = re.search(r"&page=(\d+)", rest).group(1)
    pages = cfg.get("events_pages", {})
    if "default_full" in pages and p not in pages:
        out([{"event": "labeled", "label": {"name": "other"}, "created_at": "2000-01-01T00:00:00Z"}] * 100)
    out(pages.get(p, []))

if method == "GET" and re.fullmatch(r"issues/\d+", rest):
    n_issue_gets = sum(1 for line in logged() if re.fullmatch(r"GET repos/[^/]+/[^/]+/issues/\d+", line))
    if fails("GET issue") or (n_issue_gets >= 2 and fails("GET issue verify")):
        sys.exit(1)
    issue = json.loads(json.dumps(cfg["issue"]))
    labeled = any(line.startswith("POST ") and line.endswith("/labels") for line in logged())
    if labeled and not cfg.get("label_not_applied"):
        issue["labels"].append({"name": "needs-human"})
    out(issue)

sys.exit(1)
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def expected_key(number, reason, body: bytes) -> str:
    h = hashlib.sha256(
        b"hos-escalation-v1\0" + str(number).encode() + b"\0" + reason.encode() + b"\0" + body
    )
    return h.hexdigest()[:16]


def marker(number, reason, body: bytes) -> str:
    return f"<!-- hos-escalation v=1 reason={reason} key={expected_key(number, reason, body)} -->"


def issue(labels=("needs-ai",), state="open", **extra):
    d = {"number": 7, "state": state, "labels": [{"name": n} for n in labels]}
    d.update(extra)
    return d


def own_comment(
    n=7,
    reason="awaiting-human-answer",
    body=b"Question?\n",
    cid=900,
    login=BOT,
    utype="Bot",
    created="2026-09-30T10:00:00Z",
    updated=None,
):
    return {
        "id": cid,
        "user": {"login": login, "type": utype},
        "created_at": created,
        "updated_at": updated or created,
        "html_url": f"https://github.com/test-owner/test-repo/issues/7#issuecomment-{cid}",
        "body": body.decode() + "\n\n" + marker(n, reason, body) + "\n",
    }


class Harness:
    def __init__(self, tmp_path: Path, with_audit=True):
        self.tmp = tmp_path
        bdir = tmp_path / "bootstrap"
        (bdir / "lib").mkdir(parents=True)
        self.script = bdir / "escalate_to_human.sh"
        shutil.copy(SCRIPT_SRC, self.script)
        self.script.chmod(0o755)
        shutil.copy(CFC_SRC, bdir / "lib" / "comment_format_check.sh")
        _write_exec(bdir / "get_app_token.sh", GET_APP_TOKEN_STUB)
        if with_audit:
            lib = tmp_path / "scripts" / "oversight" / "lib"
            lib.mkdir(parents=True)
            _write_exec(lib / "audit_log.sh", AUDIT_LIB_STUB)
        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        self.capture = tmp_path / "capture.log"
        self.calls = tmp_path / "calls.log"
        self.bodies = tmp_path / "bodies.jsonl"
        self.audit = tmp_path / "audit.jsonl"
        self.posted = tmp_path / "posted.json"
        for f in (self.capture, self.calls, self.bodies, self.audit):
            f.write_text("")
        self.cfg_path = tmp_path / "gh_cfg.json"
        self.cfg = {"issue": issue()}
        self.body_path = tmp_path / "body.md"
        self.body_bytes = b"Need a human decision on X.\n"
        self.body_path.write_bytes(self.body_bytes)

    def set_body(self, data: bytes):
        self.body_bytes = data
        self.body_path.write_bytes(data)

    def run(self, args=None, env=None):
        self.cfg_path.write_text(json.dumps(self.cfg))
        if args is None:
            args = [
                "--number",
                "7",
                "--body-file",
                str(self.body_path),
                "--reason",
                "awaiting-human-answer",
                "--app",
                "worker",
            ]
        e = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture),
            "CALLS_FILE": str(self.calls),
            "BODIES_FILE": str(self.bodies),
            "AUDIT_FILE": str(self.audit),
            "POSTED_FILE": str(self.posted),
            "GH_CFG": str(self.cfg_path),
            "HOME": str(self.tmp / "home"),
        }
        if env:
            e.update(env)
        return subprocess.run(
            [BASH, str(self.script), *args], capture_output=True, text=True, env=child_env(e)
        )

    # -- observations --
    def call_log(self):
        return [line for line in self.calls.read_text().splitlines() if line]

    def posts(self):
        return [c for c in self.call_log() if c.startswith("POST ")]

    def bodies_sent(self):
        return [json.loads(line) for line in self.bodies.read_text().splitlines() if line]

    def audits(self):
        return [json.loads(line) for line in self.audit.read_text().splitlines() if line]

    def capture_text(self):
        return self.capture.read_text()

    def revoked(self):
        return "-X DELETE" in self.capture_text()

    def minted(self):
        return "MINT" in self.capture_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


AUDIT_KEYS = {
    "event",
    "issue",
    "reason",
    "key",
    "outcome",
    "comment_id",
    "app",
    "actor",
    "label_present_before",
    "timestamp",
}


def _short(call):
    return re.sub(r"^(GET|POST) repos/[^/]+/[^/]+/", r"\1 ", call)


# ── T-ESC1..4: validation, before any mint ───────────────────────────────────
@pytest.mark.parametrize("drop", ["--number", "--body-file", "--reason", "--app"])
def test_esc1_each_missing_flag_exits_2(h, drop):
    full = {
        "--number": "7",
        "--body-file": str(h.body_path),
        "--reason": "awaiting-human-answer",
        "--app": "worker",
    }
    args = [x for k, v in full.items() if k != drop for x in (k, v)]
    r = h.run(args)
    assert r.returncode == 2
    assert h.call_log() == [] and not h.minted()


def test_esc2_body_flag_rejected(h):
    r = h.run(
        ["--number", "7", "--body", "hi", "--reason", "awaiting-human-answer", "--app", "worker"]
    )
    assert r.returncode == 2
    assert "--body is not supported" in r.stderr and "--body-file" in r.stderr
    assert not h.minted()


@pytest.mark.parametrize(
    "flag,val",
    [
        ("--app", "robot"),
        ("--number", "abc"),
        ("--number", "0"),
        ("--number", "07"),
        ("--reason", "Bad"),
        ("--reason", "x"),
        ("--reason", "a" * 65),
        ("--reason", "a_b"),
    ],
)
def test_esc3_bad_values_exit_2(h, flag, val):
    args = {
        "--number": "7",
        "--body-file": str(h.body_path),
        "--reason": "awaiting-human-answer",
        "--app": "worker",
    }
    args[flag] = val
    r = h.run([x for k, v in args.items() for x in (k, v)])
    assert r.returncode == 2
    assert not h.minted() and h.call_log() == []


def test_esc3_unknown_flag_exits_2(h):
    assert h.run(["--bogus", "1"]).returncode == 2


@pytest.mark.parametrize(
    "kind", ["missing", "empty", "whitespace", "at-path", "marker", "oversize"]
)
def test_esc4_bad_body_exits_2(h, kind):
    path = h.body_path
    if kind == "missing":
        path = h.tmp / "nope.md"
    elif kind == "empty":
        h.set_body(b"")
    elif kind == "whitespace":
        h.set_body(b" \n\t\n")
    elif kind == "at-path":
        h.set_body(b"@/tmp/foo.md\n")
    elif kind == "marker":
        h.set_body(b"hello\n<!-- hos-escalation v=1 reason=x key=0 -->\n")
    elif kind == "oversize":
        h.set_body(b"a" * 65000)
    r = h.run(
        [
            "--number",
            "7",
            "--body-file",
            str(path),
            "--reason",
            "awaiting-human-answer",
            "--app",
            "worker",
        ]
    )
    assert r.returncode == 2, r.stderr
    assert not h.minted() and h.call_log() == []


def test_esc4_body_at_the_limit_is_accepted(h):
    m = marker(7, "awaiting-human-answer", b"")  # same length as any marker
    h.set_body(b"a" * (65000 - len(m) - 3))
    assert h.run().returncode == 0


# ── T-ESC5: target preconditions ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "target",
    [
        issue(pull_request={"url": "x"}),
        issue(state="closed"),
        issue(labels=("needs-ai", "release-request")),
    ],
)
def test_esc5_refused_targets_make_no_post(h, target):
    h.cfg["issue"] = target
    r = h.run()
    assert r.returncode == 2
    assert h.posts() == []
    assert h.audits() == []


# ── T-ESC6: happy path and ordering ──────────────────────────────────────────
def test_esc6_happy_path_order(h):
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert [_short(c) for c in h.call_log()] == [
        "GET issues/7",
        "GET issues/7/comments?per_page=100&page=1",
        "POST issues/7/comments",
        "GET issues/comments/555",
        "POST issues/7/labels",
        "GET issues/7",
    ]
    log = h.call_log()
    posts = [i for i, c in enumerate(log) if c.startswith("POST ")]
    assert log[posts[0]].endswith("/comments") and log[posts[1]].endswith("/labels")
    sent = h.bodies_sent()
    mk = marker(7, "awaiting-human-answer", h.body_bytes)
    assert sent[0]["body"]["body"] == h.body_bytes.decode() + "\n\n" + mk + "\n"
    assert sent[1]["body"] == {"labels": ["needs-human"]}
    key = expected_key(7, "awaiting-human-answer", h.body_bytes)
    assert r.stdout.strip() == (
        f"escalated issue=#7 outcome=escalated reason=awaiting-human-answer key={key} "
        "comment=https://github.com/test-owner/test-repo/issues/7#issuecomment-555"
    )


# ── T-ESC7: key determinism ──────────────────────────────────────────────────
def _key_of(r):
    return re.search(r"key=([0-9a-f]{16})", r.stdout).group(1)


def test_esc7_key_is_deterministic_and_input_sensitive(tmp_path):
    def run(sub, number="7", reason="awaiting-human-answer", body=b"Q one\n"):
        hh = Harness(tmp_path / sub)
        hh.set_body(body)
        hh.cfg["issue"] = issue()
        hh.cfg["issue"]["number"] = int(number)
        r = hh.run(
            [
                "--number",
                number,
                "--body-file",
                str(hh.body_path),
                "--reason",
                reason,
                "--app",
                "worker",
            ]
        )
        assert r.returncode == 0, r.stderr
        return _key_of(r)

    for d in "abcde":
        (tmp_path / d).mkdir()
    k1, k2 = run("a"), run("b")
    assert k1 == k2 == expected_key(7, "awaiting-human-answer", b"Q one\n")
    assert run("c", body=b"Q onf\n") != k1
    assert run("d", reason="other-reason") != k1
    assert run("e", number="8") != k1


# ── T-ESC8..10: idempotency, repair, supersede ───────────────────────────────
def test_esc8_already_escalated_zero_posts(h):
    h.cfg["issue"] = issue(labels=("needs-ai", "needs-human"))
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.posts() == []
    assert "outcome=already-escalated" in r.stdout and "comment=" in r.stdout
    assert h.audits()[0]["outcome"] == "already-escalated"


def test_esc9_label_repair_posts_only_labels(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    h.cfg["events_pages"] = {"1": []}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert [_short(c) for c in h.posts()] == ["POST issues/7/labels"]
    assert "outcome=label-repaired" in r.stdout


def test_esc10_superseded_exit_6_no_posts(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    h.cfg["events_pages"] = {
        "1": [
            {
                "event": "unlabeled",
                "label": {"name": "needs-human"},
                "created_at": "2026-09-30T11:00:00Z",
            }
        ]
    }
    r = h.run()
    assert r.returncode == 6
    assert h.posts() == []
    assert "superseded" in r.stderr
    assert h.audits()[0]["outcome"] == "superseded"


def test_esc10_earlier_unlabel_does_not_supersede(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    h.cfg["events_pages"] = {
        "1": [
            {
                "event": "unlabeled",
                "label": {"name": "needs-human"},
                "created_at": "2026-09-30T09:00:00Z",
            }
        ]
    }
    assert h.run().returncode == 0


# ── T-ESC11..13: marker authenticity, edits, paging ──────────────────────────
@pytest.mark.parametrize("login,utype", [("someone", "User"), ("hos-overseer-hos[bot]", "Bot")])
def test_esc11_forged_marker_is_ignored(h, login, utype):
    h.cfg["issue"] = issue(labels=("needs-ai", "needs-human"))
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes, login=login, utype=utype)]}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert "outcome=escalated" in r.stdout
    assert any(c.endswith("/comments") for c in h.posts())


def test_esc11_user_typed_with_bot_login_is_ignored(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes, utype="User")]}
    r = h.run()
    assert "outcome=escalated" in r.stdout


def test_esc12_edited_marker_comment_is_reposted(h):
    c = own_comment(body=h.body_bytes, updated="2026-09-30T10:05:00Z")
    h.cfg["comments_pages"] = {"1": [c]}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert "outcome=escalated" in r.stdout
    assert any(p.endswith("/comments") for p in h.posts())


def test_esc13_marker_on_page_2_is_found(h):
    filler = [
        {
            "id": i,
            "user": {"login": "x", "type": "User"},
            "body": "hi",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        for i in range(100)
    ]
    h.cfg["issue"] = issue(labels=("needs-ai", "needs-human"))
    h.cfg["comments_pages"] = {"1": filler, "2": [own_comment(body=h.body_bytes)]}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.posts() == []
    assert "GET repos/test-owner/test-repo/issues/7/comments?per_page=100&page=2" in h.call_log()


def test_esc13_comment_page_bound_warns_and_records(h):
    full = [
        {
            "id": i,
            "user": {"login": "x", "type": "User"},
            "body": "hi",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        for i in range(100)
    ]
    h.cfg["comments_pages"] = {str(p): full for p in range(1, 31)}
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert "comment-page-bound-reached" in r.stderr
    assert any(c.endswith("/comments") for c in h.posts())


# ── T-ESC14..17: halt-on-failure ─────────────────────────────────────────────
def test_esc14_comment_post_failure_exit_4_no_label(h):
    h.cfg["fail"] = ["POST comment"]
    r = h.run()
    assert r.returncode == 4
    assert not any(c.endswith("/labels") for c in h.call_log())
    assert h.audits()[0]["outcome"] == "record-failed"


def test_esc14_response_without_id_exit_4(h):
    h.cfg["post_comment_response"] = {"html_url": "x", "id": None}
    r = h.run()
    assert r.returncode == 4
    assert not any(c.endswith("/labels") for c in h.call_log())


@pytest.mark.parametrize(
    "readback",
    [
        {"login": "intruder"},
        {"type": "User"},
        {"strip_marker": True},
    ],
)
def test_esc15_unconfirmed_readback_exit_4_no_label(h, readback):
    h.cfg["readback"] = readback
    r = h.run()
    assert r.returncode == 4
    assert not any(c.endswith("/labels") for c in h.call_log())
    assert h.audits()[0]["outcome"] == "record-failed"


def test_esc16_label_post_failure_exit_5_with_repair_line(h):
    h.cfg["fail"] = ["POST labels"]
    r = h.run()
    assert r.returncode == 5
    assert (
        "escalate_to_human: REPAIR — re-run the identical command; the question is recorded at "
        "https://github.com/test-owner/test-repo/issues/7#issuecomment-555 but needs-human is NOT "
        "applied, so the issue is still selectable"
    ) in r.stderr
    assert h.audits()[0]["outcome"] == "partial"


def test_esc17_label_not_visible_after_post_exit_5(h):
    h.cfg["label_not_applied"] = True
    r = h.run()
    assert r.returncode == 5
    assert h.audits()[0]["outcome"] == "partial"


# ── T-ESC18: pre-write failures ──────────────────────────────────────────────
@pytest.mark.parametrize("mode", ["mint", "login", "r1", "r2", "r3"])
def test_esc18_pre_write_failure_exit_1(h, mode):
    env = None
    if mode == "mint":
        env = {"FAIL_TOKEN_MINT": "1"}
    elif mode == "login":
        env = {"EMPTY_LOGIN": "1"}
    elif mode == "r1":
        h.cfg["fail"] = ["GET issue"]
    elif mode == "r2":
        h.cfg["fail"] = ["GET comments"]
    elif mode == "r3":
        h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
        h.cfg["fail"] = ["GET events"]
    r = h.run(env=env)
    assert r.returncode == 1, r.stderr
    assert h.posts() == []
    assert h.audits() == []
    if mode in ("mint", "login"):
        assert "issue=#7" in r.stderr


# ── T-ESC19: audit ───────────────────────────────────────────────────────────
def test_esc19_audit_event_shape_on_success(h):
    r = h.run()
    assert r.returncode == 0
    (ev,) = h.audits()
    assert set(ev) == AUDIT_KEYS
    assert ev["event"] == "escalated-to-human"
    assert ev["issue"] == 7 and ev["outcome"] == "escalated" and ev["comment_id"] == 555
    assert ev["reason"] == "awaiting-human-answer" and ev["app"] == "worker" and ev["actor"] == BOT
    assert ev["key"] == expected_key(7, "awaiting-human-answer", h.body_bytes)
    assert ev["label_present_before"] is False
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ev["timestamp"])


def test_esc19_no_audit_on_exit_2(h):
    h.cfg["issue"] = issue(state="closed")
    assert h.run().returncode == 2
    assert h.audits() == []


def test_esc19_missing_audit_lib_warns_and_keeps_exit_0(tmp_path):
    hh = Harness(tmp_path, with_audit=False)
    r = hh.run()
    assert r.returncode == 0, r.stderr
    assert "audit event not written" in r.stderr


# ── T-ESC20: revoke on every post-mint exit path ─────────────────────────────
def test_esc20_revoke_on_exit_0(h):
    assert h.run().returncode == 0 and h.revoked()


def test_esc20_revoke_on_exit_1(h):
    h.cfg["fail"] = ["GET issue"]
    assert h.run().returncode == 1 and h.revoked()


def test_esc20_revoke_on_exit_4(h):
    h.cfg["fail"] = ["POST comment"]
    assert h.run().returncode == 4 and h.revoked()


def test_esc20_revoke_on_exit_5(h):
    h.cfg["fail"] = ["POST labels"]
    assert h.run().returncode == 5 and h.revoked()


def test_esc20_revoke_on_exit_6(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    h.cfg["events_pages"] = {
        "1": [
            {
                "event": "unlabeled",
                "label": {"name": "needs-human"},
                "created_at": "2026-09-30T11:00:00Z",
            }
        ]
    }
    assert h.run().returncode == 6 and h.revoked()


def test_esc20_revoke_has_timeouts(h):
    h.run()
    assert "--connect-timeout 10 --max-time 30" in h.capture_text()


def test_esc19_audit_write_stderr_is_surfaced(h):
    lib = h.tmp / "scripts" / "oversight" / "lib" / "audit_log.sh"
    lib.write_text('audit_write_event() { echo "disk full" >&2; return 1; }\n')
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert "disk full" in r.stderr and "audit event not written" in r.stderr


def test_esc20_no_revoke_when_mint_failed(h):
    r = h.run(env={"FAIL_TOKEN_MINT": "1"})
    assert r.returncode == 1 and not h.revoked()


# ── T-ESC21: static script properties ────────────────────────────────────────
def test_esc21_static_script_properties():
    text = SCRIPT_SRC.read_text()
    assert "--paginate" not in text
    assert "--field" not in text and "--raw-field" not in text
    assert "body=@" not in text
    assert "gh issue edit" not in text and "gh issue comment" not in text
    api_lines = [
        line
        for line in text.splitlines()
        if re.search(r"\bgh api\b", line) and not line.lstrip().startswith("#")
    ]
    assert api_lines
    for line in api_lines:
        assert not re.search(r"\s-[fF]\s", line), line
        if "--method POST" in line:
            assert "--input -" in line, line
    assert os.access(SCRIPT_SRC, os.X_OK)


# ── T-ESC22: label already present on a fresh key ────────────────────────────
def test_esc22_label_already_present_still_records(h):
    h.cfg["issue"] = issue(labels=("needs-ai", "needs-human"))
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert "outcome=escalated" in r.stdout
    assert [_short(c) for c in h.posts()] == ["POST issues/7/comments", "POST issues/7/labels"]
    assert h.audits()[0]["label_present_before"] is True


# ── T-ESC23: R3 page bound ───────────────────────────────────────────────────
def test_esc23_event_page_bound_is_supersede_undeterminable(h):
    h.cfg["comments_pages"] = {"1": [own_comment(body=h.body_bytes)]}
    h.cfg["events_pages"] = {"default_full": True}
    r = h.run()
    assert r.returncode == 6
    assert "supersede-undeterminable" in r.stderr
    assert "events-page-bound-reached" in r.stderr
    assert h.posts() == []
    assert h.audits()[0]["outcome"] == "supersede-undeterminable"
    event_gets = [c for c in h.call_log() if "/events?" in c]
    assert len(event_gets) == 10
