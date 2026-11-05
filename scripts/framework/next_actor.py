#!/usr/bin/env python3
"""Assign or unassign HUMAN_REVIEWER on an issue or PR as `needs-human` comes and goes (#2224).

The module is the single writer of the assignee field for this mechanism
(ADR-2224, amending ADR-1928 AD-1/AD-3/AD-5). It is notification only: nothing
reads the assignment as authorization, and it never touches labels or comments.
It runs on a bare Actions runner, so it uses only the standard library, `gh`,
and `scripts/framework/requester_trust.py` for config parsing.

Usage (from the checkout root):

    python3 scripts/framework/next_actor.py reconcile-item --repo O/R --number N --ours LOGIN[,LOGIN...]
    python3 scripts/framework/next_actor.py assign         --repo O/R --number N --ours LOGIN
    python3 scripts/framework/next_actor.py unassign       --repo O/R --number N --ours LOGIN

Exit codes: 0 done / skipped / refused by design, 1 transient read failure,
2 usage error, 3 configuration refusal, 4 write failed or read-back did not
verify. One JSON line is printed on stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.framework.requester_trust import (  # noqa: E402
    _machine_accounts_path,
    _parse_env_file,
    load_bot_accounts,
    machine_accounts_file_absent,
)

GH_TIMEOUT_SECONDS = 30
EVENTS_PAGE_SIZE = 100
EVENTS_PAGE_BOUND = 10

_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_OURS_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(\[bot\])?$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

_UNRESOLVED = "next-actor-unresolved"


class ConfigRefusal(Exception):
    """Configuration refusal; the message is the outcome token (exit 3)."""


@dataclass(frozen=True)
class Item:
    state: str
    labels: frozenset
    assignees: frozenset


def _gh(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    """Sole subprocess call site. Returns (http_status, payload); (0, None) on failure."""
    argv = ["gh", "api", "--include"]
    if method != "GET":
        argv += ["--method", method]
    argv.append(path)
    if body is not None:
        argv += ["--input", "-"]
    try:
        proc = subprocess.run(
            argv,
            input=json.dumps(body) if body is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0, None

    out = proc.stdout
    if "\r\n\r\n" in out:
        header_block, _, raw = out.partition("\r\n\r\n")
    else:
        header_block, _, raw = out.partition("\n\n")
    status_line = header_block.splitlines()[0] if header_block else ""
    match = re.match(r"HTTP/\S+\s+(\d+)", status_line)
    if not match:
        return 0, None
    payload = None
    raw = raw.strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
    return int(match.group(1)), payload


def resolve_login(repo_root: Any) -> str:
    """HUMAN_REVIEWER from the trusted checkout's machine-accounts.env only."""
    root = str(repo_root)
    if machine_accounts_file_absent(root):
        raise ConfigRefusal(f"{_UNRESOLVED}:config-absent")
    env = _parse_env_file(_machine_accounts_path(root))
    login = env.get("HUMAN_REVIEWER", "").strip()
    if not login:
        raise ConfigRefusal(f"{_UNRESOLVED}:unset")
    if login.lower().endswith("[bot]"):
        raise ConfigRefusal(f"{_UNRESOLVED}:bot-suffix")
    if not _LOGIN_RE.match(login):
        raise ConfigRefusal(f"{_UNRESOLVED}:bad-login")
    if login.lower() in load_bot_accounts(root):
        raise ConfigRefusal(f"{_UNRESOLVED}:bot-account")
    return login


def check_assignable(repo: str, login: str) -> tuple[str, int] | None:
    """None when assignable; an (outcome, exit) pair for a read failure.

    Raises ConfigRefusal when GitHub says the login cannot be assigned.
    """
    status, _ = _gh("GET", f"repos/{repo}/assignees/{login}")
    if status == 204:
        return None
    if status == 404:
        raise ConfigRefusal(f"{_UNRESOLVED}:not-assignable")
    return "assign-failed:precheck", 1


def read_item(repo: str, number: int) -> Item | None:
    status, payload = _gh("GET", f"repos/{repo}/issues/{number}")
    if status != 200 or not isinstance(payload, dict):
        return None
    labels = set()
    for entry in payload.get("labels") or []:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if isinstance(name, str):
            labels.add(name)
    assignees = set()
    for entry in payload.get("assignees") or []:
        if isinstance(entry, dict) and isinstance(entry.get("login"), str):
            assignees.add(entry["login"].lower())
    return Item(str(payload.get("state", "")), frozenset(labels), frozenset(assignees))


def classify_ours(repo: str, number: int, login: str, ours: Any) -> tuple[bool, str]:
    """Whether the latest `assigned` event for `login` was made by one of `ours`."""
    wanted = login.lower()
    latest: tuple[str, int] | None = None
    latest_assigner = None
    for page in range(1, EVENTS_PAGE_BOUND + 1):
        status, payload = _gh(
            "GET",
            f"repos/{repo}/issues/{number}/events?per_page={EVENTS_PAGE_SIZE}&page={page}",
        )
        if status != 200 or not isinstance(payload, list):
            return False, "events-read-failed"
        for event in payload:
            if not isinstance(event, dict) or event.get("event") != "assigned":
                continue
            assignee = event.get("assignee")
            if not isinstance(assignee, dict) or str(assignee.get("login", "")).lower() != wanted:
                continue
            created = event.get("created_at")
            if not created:
                continue
            key = (str(created), int(event.get("id") or 0))
            if latest is None or key > latest:
                latest = key
                latest_assigner = event.get("assigner")
        if len(payload) < EVENTS_PAGE_SIZE:
            break
    else:
        return False, "events-incomplete"

    if latest is None:
        return False, "no-assigned-event"
    if not isinstance(latest_assigner, dict) or not latest_assigner.get("login"):
        return False, "assigner-null"
    if str(latest_assigner["login"]).lower() not in ours:
        return False, "assigner-not-ours"
    return True, "ours"


def assign(repo: str, number: int, login: str) -> tuple[str, int]:
    failure = check_assignable(repo, login)
    if failure:
        return failure
    item = read_item(repo, number)
    if item is None:
        return "read-failed", 1
    if "release-request" in item.labels:
        return "next-actor-refused:release-request", 0
    if item.state != "open":
        return "next-actor-skip:closed", 0
    if "needs-human" not in item.labels:
        return "next-actor-skip:label-absent", 0
    if login.lower() in item.assignees:
        return "next-actor-skip:already-assigned", 0

    status, _ = _gh("POST", f"repos/{repo}/issues/{number}/assignees", {"assignees": [login]})
    if not 200 <= status < 300:
        return "assign-failed:write", 4

    after = read_item(repo, number)
    if after is None:
        return "assign-unverified", 4
    assigned = login.lower() in after.assignees
    if "release-request" in after.labels:
        if not assigned:
            return "ng3b-race-noop", 0
        del_status, _ = _gh(
            "DELETE", f"repos/{repo}/issues/{number}/assignees", {"assignees": [login]}
        )
        final = read_item(repo, number)
        if 200 <= del_status < 300 and final is not None and login.lower() not in final.assignees:
            return "ng3b-race-undone", 0
        return "ng3b-race-undo-failed", 4
    if not assigned:
        return "assign-unverified", 4
    return "assigned", 0


def unassign(repo: str, number: int, login: str, ours: Any) -> tuple[str, int]:
    item = read_item(repo, number)
    if item is None:
        return "read-failed", 1
    if "release-request" in item.labels:
        return "next-actor-refused:release-request", 0
    if "needs-human" in item.labels:
        return "unassign-skip:label-present", 0
    if login.lower() not in item.assignees:
        return "unassign-skip:not-assigned", 0

    is_ours, reason = classify_ours(repo, number, login, ours)
    if reason == "events-read-failed":
        return "unassign-skip:events-read-failed", 1
    if not is_ours:
        return f"unassign-skip:not-ours:{reason}", 0

    status, _ = _gh("DELETE", f"repos/{repo}/issues/{number}/assignees", {"assignees": [login]})
    if not 200 <= status < 300:
        return "unassign-failed:write", 4
    after = read_item(repo, number)
    if after is None or login.lower() in after.assignees:
        return "unassign-unverified", 4
    return "unassigned", 0


def reconcile_item(repo: str, number: int, login: str, ours: Any) -> tuple[str, int]:
    item = read_item(repo, number)
    if item is None:
        return "read-failed", 1
    if (
        item.state == "open"
        and "needs-human" in item.labels
        and "release-request" not in item.labels
    ):
        return assign(repo, number, login)
    if "needs-human" not in item.labels:
        return unassign(repo, number, login, ours)
    reason = "closed" if item.state != "open" else "release-request"
    return f"reconcile-noop:{reason}", 0


def _repo_arg(value: str) -> str:
    if not _REPO_RE.match(value):
        raise argparse.ArgumentTypeError(f"invalid repo: {value!r}")
    return value


def _number_arg(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("number must be >= 1")
    return number


def _ours_arg(value: str) -> frozenset:
    entries = [part.strip() for part in value.split(",")]
    if not entries or any(not _OURS_RE.match(part) for part in entries):
        raise argparse.ArgumentTypeError(f"invalid --ours: {value!r}")
    return frozenset(part.lower() for part in entries)


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, type=_repo_arg)
    common.add_argument("--number", required=True, type=_number_arg)
    common.add_argument("--ours", required=True, type=_ours_arg)
    parser = argparse.ArgumentParser(prog="next_actor.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="op", required=True)
    for name in ("reconcile-item", "assign", "unassign"):
        sub.add_parser(name, parents=[common])
    return parser


def _emit(op: str, repo: str, number: int, login: str | None, outcome: str, code: int) -> int:
    print(
        json.dumps(
            {"op": op, "repo": repo, "number": number, "login": login, "outcome": outcome, "exit": code},
            separators=(",", ":"),
        )
    )
    if code != 0 or outcome == "ng3b-race-undone":
        print(f"::warning::next_actor {outcome} #{number}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    login: str | None = None
    try:
        login = resolve_login(_REPO_ROOT)
        if args.op == "assign":
            outcome, code = assign(args.repo, args.number, login)
        elif args.op == "unassign":
            outcome, code = unassign(args.repo, args.number, login, args.ours)
        else:
            outcome, code = reconcile_item(args.repo, args.number, login, args.ours)
    except ConfigRefusal as refusal:
        outcome, code = str(refusal), 3
    return _emit(args.op, args.repo, args.number, login, outcome, code)


if __name__ == "__main__":
    sys.exit(main())
