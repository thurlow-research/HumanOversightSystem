"""Make the autonomous worker's current pick visible (#2157).

  python3 -m scripts.automation.in_progress mark --issue <N> --branch <name>
  python3 -m scripts.automation.in_progress clear

`mark` puts the `hos-in-progress` label on issue N (and removes it from any
other issue, so at most one carries it) and emits one greppable line,
`WORKING ON #<n> <title> branch=<branch>`, to stderr and to the cron cycle log
named by $HOS_CYCLE_LOG. `clear` removes the label everywhere.

The label is informational only: select_work_candidates.py neither excludes nor
ranks by it. Everything here is best-effort — every failure is a warning on
stderr and exit 0; only a usage error exits 2.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.automation.lib import github
from scripts.automation.lib.merge_config import resolve_repo_slug

LABEL = "hos-in-progress"
LABEL_COLOR = "fbca04"
LABEL_DESCRIPTION = "The issue the autonomous worker is currently working on (informational)"
_TITLE_MAX = 100
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _warn(msg: str) -> None:
    print(f"in-progress: WARN: {msg}", file=sys.stderr)


def sanitize_title(title: str) -> str:
    """Single line, control characters stripped, truncated."""
    return _CONTROL_RE.sub(" ", title or "").strip()[:_TITLE_MAX]


def _ensure_label(owner: str, repo: str) -> None:
    if github.get_label(owner, repo, LABEL) is not None:
        return
    try:
        github.create_label(owner, repo, LABEL, LABEL_COLOR, LABEL_DESCRIPTION)
    except github.GitHubError as exc:
        if exc.status_code != 422:  # 422 already_exists: lost a creation race
            raise


def _remove_from_others(owner: str, repo: str, keep: int | None) -> list[int]:
    removed = []
    for item in github.list_issues_with_label(owner, repo, LABEL):
        number = item.get("number")
        if not isinstance(number, int) or number == keep:
            continue
        github.remove_issue_label(owner, repo, number, LABEL)
        removed.append(number)
    return removed


def _emit_line(line: str) -> None:
    print(line, file=sys.stderr)
    log = os.environ.get("HOS_CYCLE_LOG", "")
    if log and Path(log).is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log, "a", encoding="utf-8") as fh:  # append only; never create
            fh.write(f"[{stamp}] {line}\n")


def mark(owner: str, repo: str, issue: int, branch: str) -> None:
    _ensure_label(owner, repo)
    _remove_from_others(owner, repo, keep=issue)
    github.add_issue_label(owner, repo, issue, LABEL)
    data = github.get_issue(owner, repo, issue) or {}
    title = sanitize_title(str(data.get("title", "")))
    _emit_line(f"WORKING ON #{issue} {title} branch={sanitize_title(branch)}")


def clear(owner: str, repo: str) -> str:
    removed = _remove_from_others(owner, repo, keep=None)
    return "in-progress: cleared " + ",".join(f"#{n}" for n in removed) if removed else "in-progress: none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="in_progress", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_mark = sub.add_parser("mark")
    p_mark.add_argument("--issue", type=int, required=True)
    p_mark.add_argument("--branch", required=True)
    sub.add_parser("clear")
    args = parser.parse_args(argv)  # usage errors exit 2

    try:
        slug = resolve_repo_slug(Path.cwd())
        owner, repo = slug.split("/", 1)
        if args.cmd == "mark":
            mark(owner, repo, args.issue, args.branch)
        else:
            print(clear(owner, repo))
    except Exception as exc:  # observability only: never fail the caller
        _warn(f"{args.cmd} failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
