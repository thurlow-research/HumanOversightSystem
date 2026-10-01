"""Tests for the edge read modes of bootstrap/query_issues.sh (#1644 T3.3a, T-EQ1..T-EQ11).

--parent-of / --sub-issues-of / --blockers-of / --dependents-of, per
docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.3a-edge-tooling.md section 8.2. The harness is
test_query_issues.py's, duplicated (no import across test modules); its gh stub is a Python
program that serves routes from a JSON config and logs "METHOD PATH" for every call. Nothing
here reaches GitHub.

T-EQ11 is the read-only invariant behind the review-read-only-gh-read posture
(contract/dimensions/postures/review-read-only-gh-read.settings.json grants
Bash(bootstrap/query_issues.sh *) to read-only reviewer sessions): query_issues.sh must never
issue a non-GET request, so edge WRITES can never be added to it.
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
QUERY_ISSUES_SH = REPO_ROOT / "bootstrap" / "query_issues.sh"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "MINT $*" >> "$CAPTURE_FILE"
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
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

GH_STUB = r"""#!/usr/bin/env python3
import json, os, re, subprocess, sys
cfg = json.load(open(os.environ["GH_CFG"]))
args = sys.argv[1:]
if not args or args[0] != "api":
    sys.exit(1)
args = args[1:]
method, jq_expr, pos = "GET", None, []
i = 0
while i < len(args):
    if args[i] == "--method":
        method = args[i + 1]; i += 2
    elif args[i] == "--jq":
        jq_expr = args[i + 1]; i += 2
    else:
        pos.append(args[i]); i += 1
path = pos[0]
with open(os.environ["CALLS_FILE"], "a") as f:
    f.write(f"{method} {path}\n")
rest = re.sub(r"^repos/[^/]+/[^/]+/", "", path)

def emit(obj):
    text = json.dumps(obj)
    if jq_expr:
        r = subprocess.run(["jq", "-r", jq_expr], input=text, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.exit(r.returncode)
    print(text)
    sys.exit(0)

if rest in cfg.get("fail", []):
    sys.exit(1)
m = re.match(r"^(.*)\?per_page=100&page=(\d+)$", rest)
if m and m.group(1) in cfg.get("paged", {}):
    pages = cfg["paged"][m.group(1)]
    idx = int(m.group(2)) - 1
    if idx < len(pages):
        emit(pages[idx])
    if cfg.get("paged_default") is not None:
        emit(cfg["paged_default"])
    emit([])
if rest in cfg.get("routes", {}):
    emit(cfg["routes"][rest])
sys.exit(1)
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def rec(number, repo="test-owner/test-repo", state="open", **extra):
    r = {
        "number": number,
        "title": f"Title {number}",
        "state": state,
        "milestone": {"title": "v0.7.0 — Quality"},
        "labels": [{"name": "needs-ai"}, {"name": "x"}],
        "repository_url": f"https://api.github.com/repos/{repo}",
    }
    r.update(extra)
    return r


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        bdir = tmp_path / "bootstrap"
        bdir.mkdir()
        self.script = bdir / "query_issues.sh"
        shutil.copy(QUERY_ISSUES_SH, self.script)
        self.script.chmod(0o755)
        _write_exec(bdir / "get_app_token.sh", GET_APP_TOKEN_STUB)
        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        self.capture = tmp_path / "capture.log"
        self.calls = tmp_path / "calls.log"
        self.capture.write_text("")
        self.calls.write_text("")
        self.cfg: dict = {"routes": {}, "paged": {}, "fail": []}
        self.cfg_path = tmp_path / "gh_cfg.json"

    def run(self, args):
        self.cfg_path.write_text(json.dumps(self.cfg))
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture),
            "CALLS_FILE": str(self.calls),
            "GH_CFG": str(self.cfg_path),
            "HOME": str(self.tmp / "home"),
        }
        return subprocess.run(
            [BASH, str(self.script), "--app", "worker", *args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def call_log(self):
        return [
            re.sub(r"repos/test-owner/test-repo/", "", c)
            for c in self.calls.read_text().splitlines()
            if c
        ]

    def minted(self):
        return "MINT" in self.capture.read_text()

    def revoked(self):
        return "-X DELETE" in self.capture.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_eq1_parent_of_child(h):
    h.cfg["routes"]["issues/1351"] = rec(
        1351,
        state="closed",
        parent_issue_url="https://api.github.com/repos/test-owner/test-repo/issues/1349",
    )
    h.cfg["routes"]["issues/1351/parent"] = rec(1349, state="closed")
    r = h.run(["--parent-of", "1351"])
    assert r.returncode == 0, r.stderr
    assert h.call_log() == ["GET issues/1351", "GET issues/1351/parent"]
    assert (
        r.stdout == "#1349 milestone=v0.7.0 — Quality state=closed labels=needs-ai,x Title 1349\n"
    )
    assert h.revoked()


@pytest.mark.parametrize("bad", [5, ""])
def test_eq2_parent_of_undeterminable_is_exit_1(h, bad):
    h.cfg["routes"]["issues/10"] = rec(10, parent_issue_url=bad)
    r = h.run(["--parent-of", "10"])
    assert r.returncode == 1
    assert r.stdout == ""
    assert h.call_log() == ["GET issues/10"]


@pytest.mark.parametrize("variant", ["absent", "null"])
def test_eq2_parent_of_non_child_is_empty_exit_0(h, variant):
    record = rec(10)
    if variant == "null":
        record["parent_issue_url"] = None
    h.cfg["routes"]["issues/10"] = record
    r = h.run(["--parent-of", "10"])
    assert r.returncode == 0
    assert r.stdout == ""
    assert h.call_log() == ["GET issues/10"]  # /parent is never consulted (TD-E2)


def test_eq3_parent_of_cross_repo_parent_is_qualified(h):
    h.cfg["routes"]["issues/10"] = rec(
        10, parent_issue_url="https://api.github.com/repos/other-owner/other-repo/issues/7"
    )
    h.cfg["routes"]["issues/10/parent"] = rec(7, repo="other-owner/other-repo")
    r = h.run(["--parent-of", "10"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("other-owner/other-repo#7 milestone=")


def test_eq4_sub_issues_order_format_and_no_pr_filter(h):
    records = [rec(30), rec(10), rec(20, pull_request={"url": "x"})]
    h.cfg["paged"]["issues/1358/sub_issues"] = [records]
    r = h.run(["--sub-issues-of", "1358"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert [ln.split(" ")[0] for ln in lines] == ["#30", "#10", "#20"]
    # byte-identical to --list for the same same-repo record
    h.cfg["routes"]["issues?per_page=100&state=open"] = [rec(30), rec(10)]
    listed = h.run(["--list"])
    assert listed.returncode == 0, listed.stderr
    for ln in listed.stdout.splitlines():
        assert ln in lines


def _page(start, n):
    return [rec(start + i) for i in range(n)]


def test_eq5_pagination_walks_pages(h):
    h.cfg["paged"]["issues/5/sub_issues"] = [_page(1000, 100), _page(2000, 3)]
    r = h.run(["--sub-issues-of", "5"])
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 103
    assert h.call_log() == [
        "GET issues/5/sub_issues?per_page=100&page=1",
        "GET issues/5/sub_issues?per_page=100&page=2",
    ]


def test_eq5_ten_full_pages_refuse_to_print(h):
    h.cfg["paged"]["issues/5/sub_issues"] = [_page(1000 * (i + 1), 100) for i in range(10)]
    r = h.run(["--sub-issues-of", "5"])
    assert r.returncode == 1
    assert r.stdout == ""
    assert "refusing to print a truncated list" in r.stderr


def test_eq5_non_array_page_fails_with_no_stdout(h):
    h.cfg["paged"]["issues/5/sub_issues"] = [_page(1000, 100), {"message": "oops"}]
    r = h.run(["--sub-issues-of", "5"])
    assert r.returncode == 1
    assert r.stdout == ""


def test_eq6_direction_pin(h):
    h.cfg["paged"]["issues/10/dependencies/blocked_by"] = [[rec(1)]]
    h.cfg["paged"]["issues/10/dependencies/blocking"] = [[rec(2)]]
    r = h.run(["--blockers-of", "10"])
    assert r.returncode == 0 and r.stdout.startswith("#1 ")
    assert h.call_log() == ["GET issues/10/dependencies/blocked_by?per_page=100&page=1"]
    h.calls.write_text("")
    r = h.run(["--dependents-of", "10"])
    assert r.returncode == 0 and r.stdout.startswith("#2 ")
    assert h.call_log() == ["GET issues/10/dependencies/blocking?per_page=100&page=1"]


def test_eq7_cross_repo_and_unknown_repo(h):
    no_repo = rec(6)
    del no_repo["repository_url"]
    h.cfg["paged"]["issues/10/dependencies/blocked_by"] = [
        [rec(5, repo="o/r"), no_repo, rec(7, repo="Test-Owner/TEST-REPO")]
    ]
    r = h.run(["--blockers-of", "10"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].startswith("o/r#5 ")
    assert lines[1].startswith("unknown-repo#6 ")
    assert lines[2].startswith("#7 ")  # same repo, compared case-insensitively


@pytest.mark.parametrize(
    "args,msg",
    [
        (["--sub-issues-of", "1,2"], "positive integer"),
        (["--sub-issues-of", "05"], "positive integer"),
        (["--sub-issues-of", "1", "--sub-issues-of", "2"], "given more than once"),
        (["--sub-issues-of", "1", "--list"], "exactly one of"),
        (["--sub-issues-of", "1", "--issue", "2"], "exactly one of"),
        (["--sub-issues-of", "1", "--blockers-of", "2"], "exactly one of"),
        (["--sub-issues-of", "1", "--milestone", "v"], "not supported with edge modes"),
        (["--sub-issues-of", "1", "--milestone-less"], "not supported with edge modes"),
        (["--sub-issues-of", "1", "--label", "x"], "not supported with edge modes"),
        (["--sub-issues-of", "1", "--state", "open"], "not supported with edge modes"),
        (["--sub-issues-of", "1", "--full"], "not supported with edge modes"),
    ],
)
def test_eq8_usage_errors_never_mint(h, args, msg):
    r = h.run(args)
    assert r.returncode == 1
    assert msg in r.stderr
    assert not h.minted()
    assert h.call_log() == []


@pytest.mark.parametrize(
    "mode,endpoint",
    [
        ("--parent-of", "issues/10"),
        ("--sub-issues-of", "issues/10/sub_issues?per_page=100&page=1"),
        ("--blockers-of", "issues/10/dependencies/blocked_by?per_page=100&page=1"),
        ("--dependents-of", "issues/10/dependencies/blocking?per_page=100&page=1"),
    ],
)
def test_eq9_read_failure_exit_1_no_stdout_and_revoke(h, mode, endpoint):
    h.cfg["fail"].append(endpoint)
    r = h.run([mode, "10"])
    assert r.returncode == 1
    assert r.stdout == ""
    assert h.revoked()


def test_eq10_issue_line_format_is_frozen(h):
    h.cfg["routes"]["issues/1351"] = rec(
        1351,
        state="closed",
        parent_issue_url="https://api.github.com/repos/test-owner/test-repo/issues/1349",
        sub_issues_summary={"total": 3, "completed": 1, "percent_completed": 33},
        issue_dependencies_summary={
            "blocked_by": 1,
            "total_blocked_by": 1,
            "blocking": 0,
            "total_blocking": 0,
        },
    )
    r = h.run(["--issue", "1351"])
    assert r.returncode == 0, r.stderr
    assert (
        r.stdout == "#1351 milestone=v0.7.0 — Quality state=closed labels=needs-ai,x Title 1351\n"
    )


def _logical_lines():
    text = QUERY_ISSUES_SH.read_text()
    text = re.sub(r"\\\n\s*", " ", text)
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_eq11_static_no_write_request_in_script():
    lines = _logical_lines()
    for ln in lines:
        if "gh api" in ln:
            assert not re.search(r"--method|(^|\s)-X(\s|$)|--input", ln), ln
    x_lines = [ln for ln in lines if re.search(r"(^|\s)-X(\s|$)", ln)]
    assert len(x_lines) == 1
    assert "curl" in x_lines[0] and "installation/token" in x_lines[0]


def test_eq11_behavioural_edge_modes_only_issue_gets(h):
    h.cfg["routes"]["issues/10"] = rec(
        10, parent_issue_url="https://api.github.com/repos/test-owner/test-repo/issues/9"
    )
    h.cfg["routes"]["issues/10/parent"] = rec(9)
    for base in ("sub_issues", "dependencies/blocked_by", "dependencies/blocking"):
        h.cfg["paged"][f"issues/10/{base}"] = [[rec(1)]]
    for mode in ("--parent-of", "--sub-issues-of", "--blockers-of", "--dependents-of"):
        assert h.run([mode, "10"]).returncode == 0
    assert h.call_log()
    assert all(c.startswith("GET ") for c in h.call_log())
