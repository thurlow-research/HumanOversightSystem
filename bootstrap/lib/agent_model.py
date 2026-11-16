#!/usr/bin/env python3
"""agent_model.py -- read the ``model:`` of a role's agent file for bin/hos-cron (#2359).

``bin/hos-cron`` launches each cycle as a top-level headless claude session. The
``model:`` frontmatter in ``.claude/agents/<role>.md`` only applies when that file is
dispatched as a subagent, so the launcher resolves it here and passes ``--model`` itself.
The agent file stays the single source of truth; there is no default and no override.

Usage:
    agent_model.py resolve --agent-file <path>
        prints the top-level frontmatter ``model:`` value. Exit 1 with a one-line
        stderr message naming the file when the file is missing/unreadable, has no
        frontmatter, has no top-level ``model:`` key, the value is empty, or the value
        is unsafe to pass as an argv word.

Why this does not reuse ``scripts.automation.agent_invoke_cli._parse_frontmatter``: that
parser needs PyYAML, which exists only in the oversight venv. The launcher runs on the
system ``python3 -I`` before any venv is available, so this module is stdlib-only and
reads just the one scalar it needs (the same pattern as ``hos_tmp_root.py``).
"""

from __future__ import annotations

import argparse
import re
import sys

_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]*$")
_MODEL_LINE = re.compile(r"^model:(.*)$")


class ModelError(Exception):
    """The model could not be resolved from the agent file."""


def resolve_model(agent_file: str) -> str:
    try:
        with open(agent_file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ModelError(f"{agent_file}: unreadable ({type(exc).__name__})") from exc
    if not lines or lines[0].strip() != "---":
        raise ModelError(f"{agent_file}: no YAML frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ModelError(f"{agent_file}: unterminated YAML frontmatter") from None
    found = [m for m in (_MODEL_LINE.match(ln) for ln in lines[1:end]) if m]  # top-level only
    if len(found) > 1:
        raise ModelError(f"{agent_file}: duplicate top-level model: keys (ambiguous)")
    for match in found:
        value = re.sub(r"\s+#.*$", "", match.group(1)).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        if not value:
            raise ModelError(f"{agent_file}: model is empty")
        if value.lower() == "inherit":
            raise ModelError(
                f"{agent_file}: model 'inherit' is valid for subagents but not for claude --model"
            )
        if not _SAFE_MODEL.match(value):
            raise ModelError(f"{agent_file}: model value is not a safe model name")
        return value
    raise ModelError(f"{agent_file}: no top-level model: key")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_model.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    res = sub.add_parser("resolve")
    res.add_argument("--agent-file", required=True)
    args = parser.parse_args(argv)
    try:
        print(resolve_model(args.agent_file))
    except ModelError as exc:
        print(f"agent_model: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
