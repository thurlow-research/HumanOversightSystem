#!/usr/bin/env python3
"""
dimension_registry_cli.py — L2 CLI over lib/dimension_registry.py (ADR-1643
TD §7.10 as amended by Amendment C §C.2.7).

    dimension_registry_cli.py resolve [--schema <s>] [--pack <n> ...]
    dimension_registry_cli.py plan [--base <ref>] [--changed-file <p> ...]

Exit vocabulary (#1641's): 0 answered / 1 loader or operational failure /
2 usage. Exactly one JSON object on stdout in every 0 case. On 1, exactly one
stderr line: `dimension_registry: <code>: <message> [<path>]`.

With no `--pack`, the pack set comes from `contract/resolved-packs.txt`
(TD-D27); `config.sh`'s `PACK=` is never read. `plan` is dimension-only and
takes no `--schema`. With `--base`, the changed files are
`git diff --name-only <base>...HEAD`, unioned with any `--changed-file`; at
least one of the two is required.

Importing this module performs no I/O. PyYAML is not imported here, so a
missing PyYAML surfaces as the loader's `yaml_unavailable` (exit 1), never a
traceback.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from scripts.automation.lib import dimension_registry as dr  # noqa: E402

_GIT_TIMEOUT_S = 60


class _UsageError(Exception):
    pass


class _OperationalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code, message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="dimension_registry_cli.py", add_help=False)
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)
    resolve = sub.add_parser("resolve", add_help=False)
    resolve.add_argument("--schema", default=dr.DIMENSIONS_SCHEMA)
    resolve.add_argument("--pack", action="append", default=None)
    plan = sub.add_parser("plan", add_help=False)
    plan.add_argument("--base")
    plan.add_argument("--changed-file", action="append", default=[])
    return parser


def _git_changed_files(root: Path, base: str) -> list[str]:
    if base.startswith("-"):
        raise _UsageError(f"--base must be a ref, not an option: {base!r}")
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _OperationalError("git_failed", f"git diff could not run: {exc}") from None
    if proc.returncode != 0:
        raise _OperationalError(
            "git_failed", f"git diff exited {proc.returncode}: {proc.stderr.strip()}"
        )
    return [line for line in proc.stdout.split("\n") if line]


def _emit(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def _cmd_resolve(args: argparse.Namespace, root: Path) -> None:
    resolved = dr.load_registry(root, args.schema, packs=args.pack)
    _emit(dr.registry_to_json(args.schema, resolved))


def _cmd_plan(args: argparse.Namespace, root: Path) -> None:
    if args.base is None and not args.changed_file:
        raise _UsageError("plan requires --base and/or at least one --changed-file")
    changed = list(args.changed_file)
    if args.base is not None:
        changed = sorted(set(changed) | set(_git_changed_files(root, args.base)))
    reg = dr.load(root)
    items = dr.resolve_for_diff(reg, changed)
    _emit(
        {
            "schema": reg.schema,
            "digest": reg.digest,
            "packs": list(reg.packs),
            "changed_files": changed,
            "plan": [
                {
                    "binding": item.binding.id,
                    "entry": item.binding.entry,
                    "kind": item.binding.kind,
                    "applicable": item.applicable,
                    "matched_files": list(item.matched_files),
                    "reason": item.reason,
                }
                for item in items
            ],
        }
    )


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
    """`repo_root` is a test-only injection point; argparse never defines it."""
    root = Path(repo_root).resolve() if repo_root is not None else _DEFAULT_REPO_ROOT
    try:
        args = _build_parser().parse_args(argv)
        if args.command is None:
            raise _UsageError("a subcommand is required: resolve | plan")
        {"resolve": _cmd_resolve, "plan": _cmd_plan}[args.command](args, root)
    except _UsageError as exc:
        sys.stderr.write(f"dimension_registry_cli.py: usage: {exc}\n")
        return 2
    except dr.RegistryError as exc:
        suffix = f" [{exc.path}]" if exc.path else ""
        message = " ".join(exc.message.split())  # exactly one stderr line
        sys.stderr.write(f"dimension_registry: {exc.code}: {message}{suffix}\n")
        return 1
    except _OperationalError as exc:
        message = " ".join(exc.message.split())
        sys.stderr.write(f"dimension_registry: {exc.code}: {message}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
