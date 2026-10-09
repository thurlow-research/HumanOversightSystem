"""Closing-keyword guard for PR titles, bodies, and commit messages (#1856).

A GitHub closing keyword followed by an issue reference ("closes #N") in a PR
title/body or in a commit message that reaches the default branch closes that
issue on merge -- even when the sentence is a quotation of a ruling. This
module finds every such reference so bootstrap/submit_pr.sh can refuse the PR
unless the caller declared the issue with --closes.

Stdlib only. Grammar and exit codes: docs/v0.7.0/TECHNICAL-DESIGN-1856-closing-keyword-guard.md
(section 3 grammar, section 4 CLI, section 6 refusal report).

Exit codes of the CLI:
  0  every closing reference is declared
  1  at least one undeclared closing reference (stdout: sorted keys, one line)
  2  usage error, invalid --closes item, unreadable body file, git failure
"""

import argparse
import bisect
import re
import subprocess
import sys
from typing import NamedTuple, NoReturn

_KEYWORD = (
    r"(?<![A-Za-z0-9_])"
    r"(?:closes|closed|close|fixes|fixed|fix|resolves|resolved|resolve)"
    r"(?![A-Za-z0-9_])"
)
_REF = (
    r"(?P<ref>"
    r"https?://github\.com/(?P<uo>[^/\s]+)/(?P<ur>[^/\s]+)/(?:issues|pull)/(?P<un>\d+)"
    r"|(?P<ro>[A-Za-z0-9._-]+)/(?P<rr>[A-Za-z0-9._-]+)#(?P<rn>\d+)"
    r"|GH-(?P<gn>\d+)"
    r"|#(?P<hn>\d+)"
    r")"
)
_MAIN = re.compile(_KEYWORD + r"\s*(?::\s*)?" + _REF, re.IGNORECASE)
_CHAIN = re.compile(r"\s*(?:,(?:\s*and\b)?|&|\band\b)\s*" + _REF, re.IGNORECASE)

_DECLARED_ITEM = re.compile(r"^(?:\d+|[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\d+)$")
_SNIPPET_MAX = 120


class Match(NamedTuple):
    key: str
    line: int
    snippet: str


def _normalize(owner: str, repo: str, number: str, repo_slug: str) -> str:
    n = str(int(number))
    if f"{owner}/{repo}".lower() == repo_slug.lower():
        return n
    return f"{owner}/{repo}#{n}".lower()


def _key_from(m: "re.Match[str]", repo_slug: str) -> str:
    if m.group("un"):
        return _normalize(m.group("uo"), m.group("ur"), m.group("un"), repo_slug)
    if m.group("rn"):
        return _normalize(m.group("ro"), m.group("rr"), m.group("rn"), repo_slug)
    return str(int(m.group("gn") or m.group("hn")))


def find_closing_refs(text: str, repo_slug: str) -> list[Match]:
    """Return every closing reference in text, in order of appearance."""
    lines = text.split("\n")
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)
    found: list[Match] = []

    def emit(m: "re.Match[str]", at: int) -> None:
        line = bisect.bisect_right(starts, at)
        found.append(Match(_key_from(m, repo_slug), line, lines[line - 1].strip()[:_SNIPPET_MAX]))

    pos = 0
    while (m := _MAIN.search(text, pos)) is not None:
        emit(m, m.start())
        end = m.end()
        while (c := _CHAIN.match(text, end)) is not None:
            emit(c, c.start("ref"))
            end = c.end()
        pos = end
    return found


def parse_declared(values: list[str], repo_slug: str) -> set[str]:
    """Normalize --closes values (each comma-separated). Raises ValueError."""
    declared: set[str] = set()
    for value in values:
        for item in value.split(","):
            if not _DECLARED_ITEM.match(item):
                raise ValueError(f"invalid --closes item: {item!r}")
            if "#" in item:
                slug, num = item.split("#")
                owner, repo = slug.split("/")
                declared.add(_normalize(owner, repo, num, repo_slug))
            else:
                declared.add(str(int(item)))
    return declared


def read_commits(repo_dir: str, rev_range: str) -> list[tuple[str, str]]:
    """Return (sha, message) for each commit in rev_range. Raises on git failure."""
    if rev_range.startswith("-"):
        raise RuntimeError(f"invalid revision range: {rev_range!r}")
    proc = subprocess.run(
        ["git", "-C", repo_dir, "log", "-z", "--format=%H%n%B", rev_range],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(
            f"git log failed ({proc.returncode}): {detail[0] if detail else 'no output'}"
        )
    commits: list[tuple[str, str]] = []
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not record.strip():
            continue
        sha, _, message = record.lstrip("\n").partition("\n")
        commits.append((sha.strip(), message))
    return commits


def _display(key: str) -> str:
    return key if "#" in key else f"#{key}"


def _report(undeclared: list[tuple[str, str, Match]], any_commit: bool) -> str:
    out = ["✘ submit_pr.sh: text would close issue(s) not declared with --closes (#1856):"]
    for key, source, match in undeclared:
        out.append(f'  {_display(key):<7} {source}: "{match.snippet}"')
    out.append(
        "Merging this PR would close the issue(s) above. If that is NOT intended, rephrase\n"
        '(e.g. "the fix for #1539", "addresses #1539", or quote as "c-loses #1539"); for\n'
        "commit messages, amend/reword the commit. If it IS intended, pass --closes <n>."
    )
    if any_commit:
        out.append(
            "If the commit is already pushed (an --update-pr branch), it cannot be reworded "
            "without a force-push, which submit_pr.sh never does. Do NOT pass --closes for an "
            "issue you do not intend to close — escalate to a human to rebuild the branch."
        )
    return "\n".join(out)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # one-line usage errors, exit 2
        print(f"closing_keywords: {message}", file=sys.stderr)
        sys.exit(2)


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="closing_keywords.py")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    c = sub.add_parser("check")
    c.add_argument("--repo-slug", required=True)
    c.add_argument("--closes", action="append", default=[])
    c.add_argument("--title")
    c.add_argument("--body-file")
    c.add_argument("--repo-dir")
    c.add_argument("--range", dest="rev_range")
    c.add_argument("--warn-unused", action="store_true")
    return p


def _fail(message: str) -> int:
    print(f"closing_keywords: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if bool(args.repo_dir) != bool(args.rev_range):
        return _fail("--repo-dir and --range must be given together")
    try:
        declared = parse_declared(args.closes, args.repo_slug)
    except ValueError as exc:
        return _fail(str(exc))

    sources: list[tuple[str, str]] = []  # (label prefix, text)
    if args.title is not None:
        sources.append(("title", args.title))
    if args.body_file:
        try:
            with open(args.body_file, encoding="utf-8", errors="replace") as fh:
                sources.append(("body", fh.read()))
        except OSError as exc:
            return _fail(f"cannot read body file: {exc}")
    any_commit = False
    if args.repo_dir:
        try:
            commits = read_commits(args.repo_dir, args.rev_range)
        except (RuntimeError, OSError) as exc:
            return _fail(str(exc))
        for sha, message in commits:
            sources.append((f"commit {sha[:7]}", message))

    undeclared: list[tuple[str, str, Match]] = []
    seen: set[str] = set()
    for label, text in sources:
        for match in find_closing_refs(text, args.repo_slug):
            seen.add(match.key)
            if match.key in declared:
                continue
            where = "title" if label == "title" else f"{label} line {match.line}"
            undeclared.append((match.key, where, match))
            any_commit = any_commit or label.startswith("commit ")

    if args.warn_unused:
        for key in sorted(declared - seen):
            print(
                f"warning: --closes {key} declared but no closing keyword for it found",
                file=sys.stderr,
            )
    if undeclared:
        print(_report(undeclared, any_commit), file=sys.stderr)
        print(",".join(sorted({k for k, _, _ in undeclared})))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
