#!/usr/bin/env python3
"""hos_tmp_root.py -- resolve the per-role disk temp dir for HOS (#2054, S2a).

HOS temp lives on disk, not on the RAM-backed /tmp, in
``<HOS_TMP_ROOT>/<RoleDir>`` (mode 0700). ``HOS_TMP_ROOT`` is a ``config.sh``
setting. The launchers (bin/hos-cron, bin/hos-human) and the inner-loop runner
call this module so there is exactly one implementation of the grammar, the
validation and the directory creation (D41).

Usage:
    hos_tmp_root.py resolve --repo <clone> --role <role> [--create]
        prints the absolute per-role dir ``<root>/<RoleDir>``
    hos_tmp_root.py root --repo <clone>
        prints the root
    hos_tmp_root.py validate --repo <clone> --value <value>
        exit 0 if <value> would be accepted as HOS_TMP_ROOT for <clone>
    hos_tmp_root.py install-default --target <clone> --project-name <name>
        prints the install-time default (multi-clone: ../.tmp; else a
        per-project dir under ~/.local/state/hos/tmp)

``<role>`` is one of worker|overseer|human|local (lowercase). ``local`` covers
direct terminal runs of the inner loop that no launcher started.

``config.sh`` is parsed statically. It is never sourced or executed, because
the value is read by unsandboxed launchers. This module never spawns a process.

Exit codes: 0 OK; 2 usage error; 3 invalid or unusable (one
``hos_tmp_root: <reason>`` line on stderr).
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import sys
from pathlib import Path

# Explicit map, not str.capitalize(): the names must not drift from the clone
# directory names. gen_sandbox_config.py imports this and drops "local".
ROLE_DIRS = {
    "worker": "Worker",
    "overseer": "Overseer",
    "human": "Human",
    "local": "Local",
}

CONFIG_RELPATH = "scripts/framework/config.sh"
DEFAULT_VALUE = "../.tmp"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID = 3

_LINE_RE = re.compile(r"^\s*(?:export\s+)?HOS_TMP_ROOT=(.*)$")
_FORBIDDEN_CHARS = ("$", "`", ";", "\n", "\r", "*", "?", "[", "]", "{", "}")


class TmpRootError(Exception):
    """The configured root is invalid or unusable (exit 3)."""


def _strip_value(raw: str) -> str:
    """One shell assignment value, without sourcing it: a matching quote pair
    wraps the value; an unquoted value ends at whitespace (a trailing comment
    is dropped)."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end == -1:
            raise TmpRootError(f"HOS_TMP_ROOT has an unterminated quote: {raw!r}")
        return raw[1:end]
    return raw.split("#", 1)[0].strip()


def read_config_value(repo: Path) -> str:
    """The last HOS_TMP_ROOT= assignment in <repo>/scripts/framework/config.sh,
    or the default when the file or the key is missing or the value is empty."""
    try:
        text = (repo / CONFIG_RELPATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return DEFAULT_VALUE
    value = None
    for line in text.splitlines():
        match = _LINE_RE.match(line)
        if match:
            value = _strip_value(match.group(1))
    return value if value else DEFAULT_VALUE


def _home() -> str:
    return pwd.getpwuid(os.getuid()).pw_dir


def expand(value: str, repo: Path) -> str:
    """Grammar of section 2A.1: relative -> against realpath(repo); ~/ -> home;
    absolute as-is. Returns a normalised absolute path (symlinks unresolved)."""
    for char in _FORBIDDEN_CHARS:
        if char in value:
            raise TmpRootError(
                f"HOS_TMP_ROOT value {value!r} contains a forbidden character {char!r}"
            )
    if value == "~" or value.startswith("~/"):
        path = os.path.join(_home(), value[2:])
    elif value.startswith("~"):
        raise TmpRootError(f"HOS_TMP_ROOT value {value!r}: only ~/ is supported")
    elif os.path.isabs(value):
        path = value
    else:
        path = os.path.join(os.path.realpath(repo), value)
    return os.path.normpath(path)


def _resolve_existing_prefix(path: str) -> str:
    """realpath of the nearest existing ancestor, plus the not-yet-existing tail."""
    tail: list[str] = []
    probe = path
    while not os.path.lexists(probe):
        parent, name = os.path.split(probe)
        if parent == probe:
            break
        tail.append(name)
        probe = parent
    return os.path.join(os.path.realpath(probe), *reversed(tail))


def check_outside_work_tree(path: str | os.PathLike[str]) -> str | None:
    """Static check (never runs git): a reason string if any ancestor of
    ``path`` (or the path itself) has an lstat-visible .git entry, else None."""
    current = _resolve_existing_prefix(os.path.normpath(os.fspath(path)))
    while True:
        try:
            os.lstat(os.path.join(current, ".git"))
            return f"{current} is inside a git work tree (has a .git entry)"
        except OSError:
            pass
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def validate(path: str, repo: Path) -> None:
    if not os.path.isabs(path):
        raise TmpRootError(f"HOS_TMP_ROOT {path!r} is not absolute")
    resolved = _resolve_existing_prefix(path)
    repo_real = os.path.realpath(repo)
    if resolved == repo_real or resolved.startswith(repo_real + os.sep):
        raise TmpRootError(f"HOS_TMP_ROOT {path} is inside the clone {repo_real}")
    reason = check_outside_work_tree(path)
    if reason:
        raise TmpRootError(f"HOS_TMP_ROOT {path}: {reason}")


def resolve_root(repo: str | os.PathLike[str]) -> Path:
    """The validated, absolute HOS_TMP_ROOT for a clone. Raises TmpRootError."""
    repo_path = Path(repo)
    path = expand(read_config_value(repo_path), repo_path)
    validate(path, repo_path)
    return Path(path)


def _require_private_dir(path: Path, *, tighten: bool) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TmpRootError(f"cannot stat {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise TmpRootError(f"{path} is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise TmpRootError(f"{path} is not a directory")
    if info.st_uid != os.getuid():
        raise TmpRootError(f"{path} is not owned by the current user")
    if tighten and info.st_mode & 0o077:
        os.chmod(path, 0o700)


def _make_dirs_0700(root: Path) -> None:
    missing: list[Path] = []
    probe = root
    while not os.path.lexists(probe):
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise TmpRootError(f"cannot create {directory}: {exc}") from exc


def resolve_role_dir(repo: str | os.PathLike[str], role: str, *, create: bool = False) -> Path:
    if role not in ROLE_DIRS:
        raise ValueError(f"unknown role {role!r}")
    root = resolve_root(repo)
    role_dir = root / ROLE_DIRS[role]
    if create:
        _make_dirs_0700(root)
        _require_private_dir(root, tighten=False)
        try:
            os.mkdir(role_dir, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise TmpRootError(f"cannot create {role_dir}: {exc}") from exc
        _require_private_dir(role_dir, tighten=True)
        # Case-insensitive filesystems: lstat of "Worker" also finds "worker".
        if ROLE_DIRS[role] not in os.listdir(root):
            raise TmpRootError(f"{role_dir} exists under a different letter case")
    return role_dir


def validate_value(repo: str | os.PathLike[str], value: str) -> None:
    """Raises TmpRootError unless ``value`` is an acceptable HOS_TMP_ROOT."""
    repo_path = Path(repo)
    validate(expand(value, repo_path), repo_path)


_REGISTRY_ROOT_RE = re.compile(r"^[A-Za-z0-9_]+_(?:worker|overseer)_root$")


def _is_multi_clone(target: Path, projects_conf: Path) -> bool:
    """True when projects.conf registers a worker or overseer root that is a
    sibling of ``target`` (same parent directory)."""
    try:
        lines = projects_conf.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    target_parent = os.path.dirname(os.path.realpath(target))
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep or not _REGISTRY_ROOT_RE.match(key.strip()):
            continue
        root = value.strip().rstrip("/")
        if root and os.path.dirname(os.path.realpath(root)) == target_parent:
            return True
    return False


def install_default(target: str | os.PathLike[str], project_name: str, projects_conf: Path) -> str:
    """Section 2A.1 default for a consumer install. A lone clone's parent is
    typically a shared dir such as ~/src, so it gets a per-project XDG state dir
    rather than a hidden ``../.tmp`` that other projects would share."""
    if _is_multi_clone(Path(target), projects_conf):
        return DEFAULT_VALUE
    slug = re.sub(r"[^a-z0-9._-]", "-", project_name.lower()) or "project"
    return f"~/.local/state/hos/tmp/{slug}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve", help="print the per-role dir")
    res.add_argument("--repo", required=True)
    res.add_argument("--role", required=True, choices=sorted(ROLE_DIRS))
    res.add_argument("--create", action="store_true")
    rt = sub.add_parser("root", help="print the root")
    rt.add_argument("--repo", required=True)
    val = sub.add_parser("validate", help="check a candidate HOS_TMP_ROOT value")
    val.add_argument("--repo", required=True)
    val.add_argument("--value", required=True)
    dflt = sub.add_parser("install-default", help="print the install-time default")
    dflt.add_argument("--target", required=True)
    dflt.add_argument("--project-name", default="")
    dflt.add_argument("--projects-conf", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_USAGE
    try:
        if args.command == "root":
            print(resolve_root(args.repo))
        elif args.command == "validate":
            validate_value(args.repo, args.value)
        elif args.command == "install-default":
            conf = args.projects_conf or os.path.join(
                os.environ.get("HOME") or _home(), ".config", "hos", "projects.conf"
            )
            print(install_default(args.target, args.project_name, Path(conf)))
        else:
            print(resolve_role_dir(args.repo, args.role, create=args.create))
    except TmpRootError as exc:
        print(f"hos_tmp_root: {exc}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
