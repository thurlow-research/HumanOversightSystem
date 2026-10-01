"""Tests for bootstrap/edit_issue_edges.sh (#1644 T3.3a, T-EW1..T-EW24).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH, per
docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.3a-edge-tooling.md section 8.1. The gh stub is a Python
program that serves a MUTABLE issue graph from a JSON state file (POST/DELETE change it, so the
script's read-back observes real effects), requires --include, prints
"HTTP/2.0 <code> ...\\r\\n<headers>\\r\\n\\r\\n<body>" and exits 1 on non-2xx like real gh, and
takes per-call injected faults. Issue ids are deliberately different from numbers
(id = 5000000000 + number), so a number/id mix-up fails. Nothing here reaches GitHub.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SRC = REPO_ROOT / "bootstrap" / "edit_issue_edges.sh"

API = "https://api.github.com/repos/test-owner/test-repo"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "MINT $*" >> "$CAPTURE_FILE"
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='hos-worker-hos[bot]'\\n"
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
state_path = os.environ["STATE_FILE"]
st = json.load(open(state_path))
args = sys.argv[1:]
if not args or args[0] != "api":
    sys.exit(1)
args = args[1:]
method, has_include, has_input, pos = "GET", False, False, []
i = 0
while i < len(args):
    if args[i] == "--include":
        has_include = True; i += 1
    elif args[i] == "--method":
        method = args[i + 1]; i += 2
    elif args[i] == "--input":
        has_input = True; i += 2
    else:
        pos.append(args[i]); i += 1
if not has_include:
    sys.exit(97)
path = pos[0]
body = json.loads(sys.stdin.read()) if has_input else None
rest = re.sub(r"^repos/[^/]+/[^/]+/", "", path)
key = f"{method} {rest}"
with open(os.environ["CALLS_FILE"], "a") as f:
    f.write(key + "\n")
if body is not None:
    with open(os.environ["BODIES_FILE"], "a") as f:
        f.write(json.dumps({"key": key, "body": body}) + "\n")
n_prev = sum(1 for line in open(os.environ["CALLS_FILE"]).read().splitlines() if line == key)
API = "https://api.github.com/repos/test-owner/test-repo"

fault = None
for fl in st.get("faults", []):
    if fl["match"] == key and fl.get("nth", n_prev) == n_prev:
        fault = fl
        break

def find_by_id(i):
    for rec in st["issues"].values():
        if rec.get("id") == i:
            return rec
    return None

def mutate():
    m = re.fullmatch(r"POST issues/(\d+)/sub_issues", key)
    if m:
        child = find_by_id(body["sub_issue_id"])
        if child is not None:
            child["parent_issue_url"] = f"{API}/issues/{m.group(1)}"
        return
    m = re.fullmatch(r"DELETE issues/(\d+)/sub_issue", key)
    if m:
        child = find_by_id(body["sub_issue_id"])
        if child is not None and child.get("parent_issue_url") == f"{API}/issues/{m.group(1)}":
            del child["parent_issue_url"]
        return
    m = re.fullmatch(r"POST issues/(\d+)/dependencies/blocked_by", key)
    if m:
        blocker = find_by_id(body["issue_id"])
        lst = st["blocked_by"].setdefault(m.group(1), [])
        if blocker is not None and all(x["id"] != blocker["id"] for x in lst):
            lst.append(dict(blocker))
        return
    m = re.fullmatch(r"DELETE issues/(\d+)/dependencies/blocked_by/(\d+)", key)
    if m:
        lst = st["blocked_by"].get(m.group(1), [])
        st["blocked_by"][m.group(1)] = [x for x in lst if x["id"] != int(m.group(2))]

def save():
    json.dump(st, open(state_path, "w"))

TEXT = {200: "OK", 201: "Created", 403: "Forbidden", 404: "Not Found", 422: "Unprocessable Entity",
        500: "Internal Server Error", 502: "Bad Gateway"}

def respond(code, payload, headers=()):
    save()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    sys.stdout.write(f"HTTP/2.0 {code} {TEXT.get(code, 'X')}\r\n")
    for h in headers:
        sys.stdout.write(h + "\r\n")
    sys.stdout.write("\r\n" + text)
    sys.exit(0 if 200 <= code < 300 else 1)

def normal_read():
    m = re.fullmatch(r"GET issues/(\d+)", key)
    if m:
        rec = st["issues"].get(m.group(1))
        if rec is None:
            return 404, {"message": "Not Found"}
        return 200, rec
    m = re.fullmatch(r"GET issues/(\d+)/dependencies/blocked_by\?per_page=100&page=(\d+)", key)
    if m:
        lst = st["blocked_by"].get(m.group(1), [])
        p = int(m.group(2))
        return 200, lst[(p - 1) * 100 : p * 100]
    return 404, {"message": "Not Found"}

if fault and fault.get("set_parent"):
    sp = fault["set_parent"]
    st["issues"][str(sp["child"])]["parent_issue_url"] = f"{API}/issues/{sp['parent']}"

if fault and fault.get("no_response"):
    if fault.get("apply"):
        mutate()
    save()
    sys.exit(1)

if method == "GET":
    if fault and not (200 <= fault.get("status", 200) < 300):
        respond(fault["status"], fault.get("body", {"message": "err"}), fault.get("headers", ()))
    code, payload = normal_read()
    if fault and fault.get("malformed"):
        respond(200, "this is not json")
    if fault and fault.get("patch") and isinstance(payload, dict):
        payload = dict(payload)
        payload.update(fault["patch"])
    respond(code, payload)

code = 201 if method == "POST" else 200
if fault:
    code = fault.get("status", code)
    ok = 200 <= code < 300
    if (ok and not fault.get("no_apply")) or (not ok and fault.get("apply")):
        mutate()
    respond(code, fault.get("body", {}), fault.get("headers", ()))
mutate()
respond(code, {})
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def issue_rec(number, **extra):
    r = {
        "number": number,
        "id": 5000000000 + number,
        "state": "open",
        "title": f"secret title {number}",
        "repository_url": API,
    }
    r.update(extra)
    return r


def other_repo_blocker(number, ident):
    return {
        "number": number,
        "id": ident,
        "repository_url": "https://api.github.com/repos/other/repo",
    }


AUDIT_KEYS = {
    "event",
    "kind",
    "op",
    "issue",
    "other",
    "outcome",
    "http_status",
    "app",
    "actor",
    "timestamp",
}


class Harness:
    def __init__(self, tmp_path: Path, with_audit=True):
        self.tmp = tmp_path
        bdir = tmp_path / "bootstrap"
        bdir.mkdir()
        self.script = bdir / "edit_issue_edges.sh"
        shutil.copy(SCRIPT_SRC, self.script)
        self.script.chmod(0o755)
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
        for f in (self.capture, self.calls, self.bodies, self.audit):
            f.write_text("")
        self.state_path = tmp_path / "state.json"
        self.st = {
            "issues": {str(n): issue_rec(n) for n in (10, 20, 30)},
            "blocked_by": {},
            "faults": [],
        }

    def fault(self, match, **kw):
        self.st["faults"].append({"match": match, **kw})

    def issue(self, n):
        return self.st["issues"][str(n)]

    def run(self, *args):
        self.state_path.write_text(json.dumps(self.st))
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture),
            "CALLS_FILE": str(self.calls),
            "BODIES_FILE": str(self.bodies),
            "AUDIT_FILE": str(self.audit),
            "STATE_FILE": str(self.state_path),
            "HOME": str(self.tmp / "home"),
        }
        return subprocess.run(
            [BASH, str(self.script), *[str(a) for a in args]],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def edge(self, op, other, number=10, app="worker"):
        return self.run("--number", number, "--app", app, op, other)

    def call_log(self):
        return [c for c in self.calls.read_text().splitlines() if c]

    def writes(self):
        return [c for c in self.call_log() if not c.startswith("GET ")]

    def bodies_sent(self):
        return [json.loads(x) for x in self.bodies.read_text().splitlines() if x]

    def audits(self):
        return [json.loads(x) for x in self.audit.read_text().splitlines() if x]

    def minted(self):
        return "MINT" in self.capture.read_text()

    def revoked(self):
        return "-X DELETE" in self.capture.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def assert_no_effect(h):
    assert not h.minted()
    assert h.call_log() == []


# ── T-EW1..T-EW6: pre-mint refusals ──────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [
        ["--app", "worker", "--add-parent", "20"],
        ["--number", "10", "--add-parent", "20"],
        ["--number", "10", "--app", "worker"],
    ],
)
def test_ew1_missing_required_flag(h, args):
    r = h.run(*args)
    assert r.returncode == 2
    assert_no_effect(h)


@pytest.mark.parametrize(
    "ops",
    [[], ["--add-parent", "20", "--add-blocked-by", "30"]],
)
def test_ew2_exactly_one_op(h, ops):
    r = h.run("--number", 10, "--app", "worker", *ops)
    assert r.returncode == 2
    assert "exactly one of" in r.stderr
    assert_no_effect(h)


@pytest.mark.parametrize(
    "args",
    [
        ["--number", "10", "--app", "worker", "--add-blocked-by", "5", "--add-blocked-by", "6"],
        ["--number", "10", "--number", "11", "--app", "worker", "--add-parent", "5"],
        ["--number", "10", "--app", "worker", "--app", "human", "--add-parent", "5"],
    ],
)
def test_ew3_repeated_flag_is_an_error(h, args):
    r = h.run(*args)
    assert r.returncode == 2
    assert "given more than once" in r.stderr
    assert_no_effect(h)


@pytest.mark.parametrize("val", ["0", "-1", "05", "1,2", "abc"])
def test_ew4_bad_values_are_usage(h, val):
    r = h.edge("--add-parent", val)
    assert r.returncode == 2
    assert "usage:" in r.stderr
    assert_no_effect(h)


@pytest.mark.parametrize("val", ["#5", "o/r#5", "https://github.com/o/r/issues/5"])
def test_ew4_qualified_references(h, val):
    r = h.edge("--add-parent", val)
    assert r.returncode == 2
    assert "qualified-reference-unsupported" in r.stderr
    assert_no_effect(h)


@pytest.mark.parametrize(
    "op", ["--add-parent", "--remove-parent", "--add-blocked-by", "--remove-blocked-by"]
)
def test_ew5_self_reference(h, op):
    r = h.edge(op, 10)
    assert r.returncode == 2
    assert "self-reference" in r.stderr
    assert_no_effect(h)


@pytest.mark.parametrize(
    "args",
    [
        ["--body", "x"],
        ["--body-file", "f"],
    ],
)
def test_ew6_free_text_rejected(h, args):
    r = h.run("--number", 10, "--app", "worker", "--add-parent", 20, *args)
    assert r.returncode == 2
    assert "not applicable" in r.stderr
    assert_no_effect(h)


def test_ew6_bad_app(h):
    r = h.edge("--add-parent", 20, app="nobody")
    assert r.returncode == 2
    assert_no_effect(h)


# ── add / remove parent ──────────────────────────────────────────────────────


def test_ew7_add_parent_happy(h):
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0, r.stderr
    assert h.call_log() == [
        "GET issues/10",
        "GET issues/20",
        "POST issues/20/sub_issues",
        "GET issues/10",
    ]
    sent = h.bodies_sent()
    assert [b["body"] for b in sent] == [{"sub_issue_id": 5000000010}]
    assert type(sent[0]["body"]["sub_issue_id"]) is int
    assert r.stdout == "edge kind=sub-issue op=add parent=#20 child=#10 outcome=added\n"
    assert [a["outcome"] for a in h.audits()] == ["added"]


def test_ew8_add_parent_already_present(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/20"
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0
    assert "outcome=already-present" in r.stdout
    assert h.call_log() == ["GET issues/10", "GET issues/20"]
    assert h.audits() == []


def test_ew9_add_parent_conflicts(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/30"
    r = h.edge("--add-parent", 20)
    assert r.returncode == 6
    assert "has-other-parent" in r.stderr and "current=#30" in r.stderr
    assert h.writes() == []


def test_ew9_cross_repo_parent_is_a_conflict(h):
    h.issue(10)["parent_issue_url"] = "https://api.github.com/repos/other/repo/issues/7"
    r = h.edge("--add-parent", 20)
    assert r.returncode == 6
    assert "current=other/repo#7" in r.stderr
    assert h.writes() == []


def test_ew9_null_parent_is_absent(h):
    h.issue(10)["parent_issue_url"] = None
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0, r.stderr
    assert "outcome=added" in r.stdout


def test_ew9_integer_parent_is_undeterminable(h):
    h.issue(10)["parent_issue_url"] = 5
    r = h.edge("--add-parent", 20)
    assert r.returncode == 6
    assert "parent-undeterminable" in r.stderr
    assert h.writes() == []


def test_ew10_remove_parent_happy(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/20"
    r = h.edge("--remove-parent", 20)
    assert r.returncode == 0, r.stderr
    assert h.call_log() == [
        "GET issues/10",
        "GET issues/20",
        "DELETE issues/20/sub_issue",
        "GET issues/10",
    ]
    assert [b["body"] for b in h.bodies_sent()] == [{"sub_issue_id": 5000000010}]
    assert "outcome=removed" in r.stdout


def test_ew11_remove_parent_absent_and_mismatch(h):
    r = h.edge("--remove-parent", 20)
    assert r.returncode == 0
    assert "outcome=already-absent" in r.stdout
    assert h.call_log() == ["GET issues/10", "GET issues/20"]


def test_ew11_remove_parent_mismatch(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/30"
    r = h.edge("--remove-parent", 20)
    assert r.returncode == 6
    assert "parent-mismatch" in r.stderr
    assert h.writes() == []


# ── add / remove blocked-by ──────────────────────────────────────────────────

BB = "issues/10/dependencies/blocked_by?per_page=100&page=1"


def test_ew12_add_blocked_by_happy(h):
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 0, r.stderr
    assert h.call_log() == [
        "GET issues/10",
        "GET issues/20",
        f"GET {BB}",
        "POST issues/10/dependencies/blocked_by",
        f"GET {BB}",
    ]
    assert [b["body"] for b in h.bodies_sent()] == [{"issue_id": 5000000020}]
    assert r.stdout == "edge kind=blocked-by op=add issue=#10 blocked_by=#20 outcome=added\n"


def test_ew13_add_blocked_by_present_and_membership_is_by_id(h):
    h.st["blocked_by"]["10"] = [issue_rec(20)]
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 0
    assert "outcome=already-present" in r.stdout
    assert len(h.call_log()) == 3
    assert h.writes() == []


def test_ew13_same_number_different_id_does_not_count(tmp_path):
    h = Harness(tmp_path)
    h.st["blocked_by"]["10"] = [other_repo_blocker(20, 7000000020)]
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 0, r.stderr
    assert "outcome=added" in r.stdout
    assert h.writes() == ["POST issues/10/dependencies/blocked_by"]


def test_ew14_remove_blocked_by_uses_the_id_in_the_path(h):
    h.st["blocked_by"]["10"] = [issue_rec(20)]
    r = h.edge("--remove-blocked-by", 20)
    assert r.returncode == 0, r.stderr
    assert h.writes() == ["DELETE issues/10/dependencies/blocked_by/5000000020"]
    assert h.bodies_sent() == []
    assert "outcome=removed" in r.stdout


def test_ew14_remove_blocked_by_absent(h):
    r = h.edge("--remove-blocked-by", 20)
    assert r.returncode == 0
    assert "outcome=already-absent" in r.stdout
    assert len(h.call_log()) == 3


def test_ew15_pagination_finds_blocker_on_page_2(h):
    h.st["blocked_by"]["10"] = [other_repo_blocker(i, 9000000000 + i) for i in range(100)] + [
        issue_rec(20),
        issue_rec(21),
        issue_rec(22),
    ]
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 0, r.stderr
    assert "already-present" in r.stdout
    gets = [c for c in h.call_log() if "dependencies" in c]
    assert gets == [
        "GET issues/10/dependencies/blocked_by?per_page=100&page=1",
        "GET issues/10/dependencies/blocked_by?per_page=100&page=2",
    ]


def test_ew15_ten_full_pages_are_undeterminable(h):
    h.st["blocked_by"]["10"] = [other_repo_blocker(i, 9000000000 + i) for i in range(1000)]
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 6
    assert "edges-undeterminable" in r.stderr
    assert h.writes() == []
    assert len([c for c in h.call_log() if "dependencies" in c]) == 10


# ── T-EW16: resolution failures, never a write ───────────────────────────────


def _case(name, setup, code, token):
    return pytest.param(setup, code, token, id=name)


def _f(match, **kw):
    return lambda h: h.fault(match, **kw)


def _patch_issue(n, **kw):
    return lambda h: h.issue(n).update(kw)


def _drop_id(h):
    del h.issue(10)["id"]


RESOLUTION_CASES = [
    _case("r1-404", _f("GET issues/10", status=404), 2, "issue-not-found|issue=#10"),
    _case("r2-404", _f("GET issues/20", status=404), 2, "issue-not-found|issue=#20"),
    _case("r1-500", _f("GET issues/10", status=500), 1, "read-failed"),
    _case("r1-403", _f("GET issues/10", status=403), 2, "read-rejected"),
    _case(
        "r1-403-retry-after",
        _f("GET issues/10", status=403, headers=["Retry-After: 30"]),
        1,
        "read-failed",
    ),
    _case("r1-no-response", _f("GET issues/10", no_response=True), 1, "read-failed"),
    _case("id-missing", _drop_id, 1, "read-malformed"),
    _case("id-string", _patch_issue(10, id="5"), 1, "read-malformed"),
    _case("r1-pr", _patch_issue(10, pull_request={"url": "x"}), 2, "target-is-pull-request"),
    _case("r2-pr", _patch_issue(20, pull_request={"url": "x"}), 2, "target-is-pull-request"),
    _case("number-mismatch", _patch_issue(10, number=99), 2, "issue-moved"),
    _case(
        "foreign-repo",
        _patch_issue(20, repository_url="https://api.github.com/repos/x/y"),
        2,
        "issue-moved",
    ),
]


@pytest.mark.parametrize("setup,code,token", RESOLUTION_CASES)
@pytest.mark.parametrize("op", ["--add-parent", "--add-blocked-by"])
def test_ew16_resolution_failures(h, op, setup, code, token):
    setup(h)
    r = h.edge(op, 20)
    assert r.returncode == code, r.stderr
    for part in token.split("|"):
        assert part in r.stderr
    assert h.writes() == []


def test_ew16_r1_404_makes_no_r2_call(h):
    h.fault("GET issues/10", status=404)
    h.edge("--add-parent", 20)
    assert h.call_log() == ["GET issues/10"]


def test_ew16_blocked_by_list_404_is_exit_6(h):
    h.fault(f"GET {BB}", status=404)
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 6
    assert "edges-undeterminable" in r.stderr and "http=404" in r.stderr
    assert h.writes() == []


# ── T-EW17..T-EW20: writes judged by the observed state ──────────────────────


def test_ew17_write_rejected_strips_control_characters(h):
    h.fault("POST issues/20/sub_issues", status=422, body={"message": "bad\u0007thing"})
    r = h.edge("--add-parent", 20)
    assert r.returncode == 2
    assert "write-rejected" in r.stderr
    assert "http=422 message=badthing" in r.stderr
    assert [a["outcome"] for a in h.audits()] == ["write-rejected"]


@pytest.mark.parametrize("status", [502, 422])
def test_ew18_lost_response_but_state_landed_is_success(h, status):
    h.fault("POST issues/20/sub_issues", status=status, apply=True)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0, r.stderr
    assert "outcome=added" in r.stdout


def test_ew19_write_failed_variants(h):
    h.fault("POST issues/20/sub_issues", status=502)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 4
    assert "write-failed" in r.stderr and "http=502" in r.stderr


def test_ew19_rate_limited_write(h):
    h.fault("POST issues/20/sub_issues", status=403, headers=["Retry-After: 30"])
    r = h.edge("--add-parent", 20)
    assert r.returncode == 4
    assert "write-failed" in r.stderr


def test_ew19_no_response_write(h):
    h.fault("POST issues/20/sub_issues", no_response=True)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 4
    assert "write-failed" in r.stderr and "http=none" in r.stderr


def test_ew19_2xx_not_applied_is_unverified(h):
    h.fault("POST issues/20/sub_issues", status=201, no_apply=True)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 4
    assert "unverified" in r.stderr and "http=201" in r.stderr


@pytest.mark.parametrize(
    "fault",
    [
        {"status": 500},
        {"status": 404},
        {"patch": {"parent_issue_url": 5}},
        {"malformed": True},
    ],
)
def test_ew19_verify_read_failures_are_exit_4(h, fault):
    h.fault("GET issues/10", nth=2, **fault)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 4
    assert "unverified" in r.stderr and "verify-read-failed" in r.stderr


def test_ew19_verify_walk_failure_is_exit_4(h):
    h.fault(f"GET {BB}", nth=2, status=500)
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 4
    assert "verify-read-failed" in r.stderr


def test_ew19_remove_with_unreadable_verify_is_not_misread_as_removed(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/20"
    h.fault("GET issues/10", nth=2, status=404)
    r = h.edge("--remove-parent", 20)
    assert r.returncode == 4


def test_ew20_race_on_add_parent(h):
    h.fault(
        "POST issues/20/sub_issues",
        status=422,
        set_parent={"child": 10, "parent": 30},
    )
    r = h.edge("--add-parent", 20)
    assert r.returncode == 6
    assert "has-other-parent" in r.stderr and "current=#30" in r.stderr


# ── T-EW21: static ───────────────────────────────────────────────────────────


def _code_lines():
    return [
        ln
        for ln in re.sub(r"\\\n\s*", " ", SCRIPT_SRC.read_text()).splitlines()
        if not ln.lstrip().startswith("#")
    ]


def test_ew21_static_shape():
    text = "\n".join(_code_lines())
    for banned in (
        "--paginate",
        "--field",
        "--raw-field",
        "--jq",
        "gh issue",
        "replace_parent",
        "body=@",
    ):
        assert banned not in text, banned
    gh_lines = [ln for ln in _code_lines() if "gh api" in ln]
    assert gh_lines
    for ln in gh_lines:
        assert "--include" in ln, ln
        assert not re.search(r"(^|\s)-[fF](\s|$)", ln), ln


# ── T-EW22: request budget and sequence ──────────────────────────────────────


def _setup_parent_present(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/20"


def _setup_blocker_present(h):
    h.st["blocked_by"]["10"] = [issue_rec(20)]


def _nothing(h):
    pass


BUDGETS = [
    (
        "--add-parent",
        _nothing,
        ["GET issues/10", "GET issues/20", "POST issues/20/sub_issues", "GET issues/10"],
    ),
    ("--add-parent", _setup_parent_present, ["GET issues/10", "GET issues/20"]),
    (
        "--remove-parent",
        _setup_parent_present,
        ["GET issues/10", "GET issues/20", "DELETE issues/20/sub_issue", "GET issues/10"],
    ),
    ("--remove-parent", _nothing, ["GET issues/10", "GET issues/20"]),
    (
        "--add-blocked-by",
        _nothing,
        [
            "GET issues/10",
            "GET issues/20",
            f"GET {BB}",
            "POST issues/10/dependencies/blocked_by",
            f"GET {BB}",
        ],
    ),
    ("--add-blocked-by", _setup_blocker_present, ["GET issues/10", "GET issues/20", f"GET {BB}"]),
    (
        "--remove-blocked-by",
        _setup_blocker_present,
        [
            "GET issues/10",
            "GET issues/20",
            f"GET {BB}",
            "DELETE issues/10/dependencies/blocked_by/5000000020",
            f"GET {BB}",
        ],
    ),
    ("--remove-blocked-by", _nothing, ["GET issues/10", "GET issues/20", f"GET {BB}"]),
]


@pytest.mark.parametrize("op,setup,expected", BUDGETS)
def test_ew22_request_budget(h, op, setup, expected):
    setup(h)
    r = h.edge(op, 20)
    assert r.returncode == 0, r.stderr
    assert h.call_log() == expected


# ── T-EW23: audit and revoke ─────────────────────────────────────────────────


def test_ew23_audit_event_shape(h):
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0
    (ev,) = h.audits()
    assert set(ev) == AUDIT_KEYS
    assert ev["event"] == "issue-edge-changed"
    assert ev["kind"] == "sub-issue" and ev["op"] == "add"
    assert ev["issue"] == 10 and ev["other"] == 20
    assert ev["http_status"] == 201
    assert ev["actor"] == "hos-worker-hos[bot]" and ev["app"] == "worker"


def test_ew23_missing_audit_lib_does_not_change_exit(tmp_path):
    h = Harness(tmp_path, with_audit=False)
    r = h.edge("--add-parent", 20)
    assert r.returncode == 0
    assert "audit event not written" in r.stderr


def test_ew23_audit_only_when_a_write_was_attempted(h):
    h.fault("GET issues/10", status=500)
    h.edge("--add-parent", 20)
    assert h.audits() == []


def _ex_0(h):
    pass


def _ex_1(h):
    h.fault("GET issues/10", status=500)


def _ex_2(h):
    h.fault("GET issues/10", status=404)


def _ex_4(h):
    h.fault("POST issues/20/sub_issues", status=502)


def _ex_6(h):
    h.issue(10)["parent_issue_url"] = f"{API}/issues/30"


@pytest.mark.parametrize("setup,code", [(_ex_0, 0), (_ex_1, 1), (_ex_2, 2), (_ex_4, 4), (_ex_6, 6)])
def test_ew23_token_revoked_on_every_post_mint_exit(h, setup, code):
    setup(h)
    r = h.edge("--add-parent", 20)
    assert r.returncode == code, r.stderr
    assert h.minted()
    assert h.revoked()


def test_ew23_no_issue_title_is_ever_printed(h):
    h.fault("POST issues/20/sub_issues", status=422, body={"message": "nope"})
    r = h.edge("--add-parent", 20)
    assert "secret title" not in r.stdout + r.stderr


# ── T-EW24: state is not a refusal criterion ─────────────────────────────────


@pytest.mark.parametrize("closed", [10, 20])
def test_ew24_closed_issues_are_accepted(h, closed):
    h.issue(closed)["state"] = "closed"
    r = h.edge("--add-blocked-by", 20)
    assert r.returncode == 0, r.stderr
    assert "outcome=added" in r.stdout


# ── gh calls are bounded (reliability MUST_FIX) ──────────────────────────────

SLEEPY_GH = """#!/usr/bin/env bash
if [[ "$*" == *"$HANG_ON"* ]]; then sleep 8; exit 0; fi
exec "$REAL_GH" "$@"
"""


def _make_sleepy(h, hang_on):
    real = h.stub_bin / "gh_real"
    shutil.move(h.stub_bin / "gh", real)
    _write_exec(h.stub_bin / "gh", SLEEPY_GH)
    return {"HANG_ON": hang_on, "REAL_GH": str(real), "HOS_EDGE_GH_TIMEOUT": "1"}


def _run_with_env(h, extra_env, *args):
    h.state_path.write_text(json.dumps(h.st))
    env = {
        "PATH": f"{h.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "CAPTURE_FILE": str(h.capture),
        "CALLS_FILE": str(h.calls),
        "BODIES_FILE": str(h.bodies),
        "AUDIT_FILE": str(h.audit),
        "STATE_FILE": str(h.state_path),
        "HOME": str(h.tmp / "home"),
        **extra_env,
    }
    return subprocess.run(
        [BASH, str(h.script), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.mark.skipif(
    not (shutil.which("timeout") or shutil.which("gtimeout")), reason="needs timeout"
)
def test_hung_read_is_transient_exit_1(h):
    env = _make_sleepy(h, "issues/10")
    r = _run_with_env(h, env, "--number", 10, "--app", "worker", "--add-parent", 20)
    assert r.returncode == 1
    assert "read-failed" in r.stderr and "http=none" in r.stderr
    assert h.revoked()


@pytest.mark.skipif(
    not (shutil.which("timeout") or shutil.which("gtimeout")), reason="needs timeout"
)
def test_hung_write_is_exit_4_after_readback(h):
    env = _make_sleepy(h, "POST")
    r = _run_with_env(h, env, "--number", 10, "--app", "worker", "--add-parent", 20)
    assert r.returncode == 4
    assert "write-failed" in r.stderr and "http=none" in r.stderr
    assert h.call_log()[-1] == "GET issues/10"  # read-back still ran
