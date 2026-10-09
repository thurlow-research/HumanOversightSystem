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
    hos_tmp_root.py mark --repo <clone> --role <role> --reviewed
        marks an existing role dir after a human reviewed its contents
    hos_tmp_root.py root --repo <clone>
        prints the root
    hos_tmp_root.py validate --repo <clone> --value <value>
        exit 0 if <value> would be accepted as HOS_TMP_ROOT for <clone>
    hos_tmp_root.py check-dir --repo <clone> --dir <path>
        exit 0 if <path> is an acceptable temp dir for a run in <clone>: a real
        (non-symlink) directory owned by the user with no group/other access,
        not inside the clone
    hos_tmp_root.py install-default --target <clone> --project-name <name>
        prints the install-time default (multi-clone: ../.tmp; else a
        per-project dir under ~/.local/state/hos/tmp)

``<role>`` is one of worker|overseer|human|local (lowercase). ``local`` covers
direct terminal runs of the inner loop that no launcher started.

``config.sh`` is parsed statically. It is never sourced or executed, because
the value is read by unsandboxed launchers. This module never spawns a process.

Trust registry (delete authority, #2054 security review). ``resolve --create`` records
each role dir it creates or adopts in ``~/.local/state/hos/tmp-roots.json`` as
{path, role, repo, st_dev, st_ino} (0600 in a 0700 dir, atomic write under an flock),
keyed by (repo realpath, role): a registration replaces that key's entry, entries for
vanished or replaced dirs are pruned, re-pointing a key at a different live path needs
``mark --reviewed``, and at 256 entries a new key is refused with ``registry-full``. That
location is never granted to a sandbox, so a sandboxed agent can neither read nor edit
it; bootstrap/tmp_reaper.py reaps from a role dir only if that exact directory (path,
role AND inode) is registered, and nothing in the dir (not the marker, not its
contents) is consulted at reap time. The in-dir ``.hos-tmp-root`` marker
(``hos-tmp-root v3 role=<RoleDir>``) is informational only and holds no secret.
An already-registered dir is accepted whatever it holds. An unregistered pre-existing
dir is adopted, and registered, only if it is empty or holds HOS-only content: entries
named pytest-of-*, tmp*, claude, claude-*, srt-*, hos-*, garbage-hos-* or .hos-*, none of
them a directory that directly contains .git, .claude or scripts. Anything else is
refused with exit 3 BEFORE any chmod, with a one-line remedy; ``mark --reviewed`` is the
explicit human step that registers a reviewed dir. An agent-writable config.sh pointing
HOS_TMP_ROOT at a foreign project therefore can neither change that project's modes nor
get anything in it reaped. HOS_TMP_REGISTRY_FILE overrides the registry path for tests
only (the reaper has no override).

Exit codes: 0 OK; 2 usage error; 3 invalid or unusable (one
``hos_tmp_root: <reason>`` line on stderr).
"""

from __future__ import annotations

import argparse
import fcntl
import json
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
MARKER = ".hos-tmp-root"
# Names an HOS role dir may already hold when it is adopted without a marker.
HOS_ONLY_RE = re.compile(
    r"^(pytest-of-.+|tmp.*|claude(-.*)?|srt-.*|hos-.*|garbage-hos-.*|\.hos-.*)$"
)
_PROJECT_NAMES = (".git", ".claude", "scripts")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID = 3

_LINE_RE = re.compile(r"^\s*(?:export\s+)?HOS_TMP_ROOT=(.*)$")
_FORBIDDEN_CHARS = ("$", "`", ";", "\n", "\r", "*", "?", "[", "]", "{", "}")


class TmpRootError(Exception):
    """The configured root is invalid or unusable (exit 3)."""


def _strip_value(raw: str) -> str:
    """One shell assignment value, without sourcing it: a matching quote pair
    wraps the value, or the value is unquoted. A trailing ``# comment`` is
    dropped from an unquoted value, and an unquoted value that still contains
    whitespace is rejected (the shell would split it)."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end == -1:
            raise TmpRootError(f"HOS_TMP_ROOT has an unterminated quote: {raw!r}")
        return raw[1:end]
    value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
    if re.search(r"\s", value):
        raise TmpRootError(f"HOS_TMP_ROOT unquoted value contains whitespace: {value!r}")
    return value


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


def resolve_existing_prefix(path: str) -> str:
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
    current = resolve_existing_prefix(os.path.normpath(os.fspath(path)))
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


def _is_within(inner: str, outer: str) -> bool:
    """True when ``inner`` equals ``outer`` or is below it (both normalised)."""
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


def validate(path: str, repo: Path) -> None:
    if not os.path.isabs(path):
        raise TmpRootError(f"HOS_TMP_ROOT {path!r} is not absolute")
    resolved = resolve_existing_prefix(path)
    repo_real = os.path.realpath(repo)
    if _is_within(resolved, repo_real):
        raise TmpRootError(f"HOS_TMP_ROOT {path} is inside the clone {repo_real}")
    if _is_within(repo_real, resolved):
        raise TmpRootError(
            f"HOS_TMP_ROOT {path} contains the clone {repo_real}; the role dir "
            "would be the clone itself or a parent of it"
        )
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


REGISTRY_RELPATH = ".local/state/hos/tmp-roots.json"
REGISTRY_MAX_BYTES = 1 << 20


def registry_path() -> str:
    """The trust registry. It lives under ~/.local/state, which the sandbox template
    never grants (denyRead __HOME__/ applies), so a sandboxed agent can neither read nor
    edit it. HOS_TMP_REGISTRY_FILE overrides the path for TESTS ONLY; the reaper has no
    such override and always reads the passwd-derived path."""
    return os.environ.get("HOS_TMP_REGISTRY_FILE") or os.path.join(_home(), REGISTRY_RELPATH)


def read_registry(path: str) -> list[dict] | None:
    """The registered role dirs, [] if the file does not exist yet. Raises TmpRootError
    if it exists but is not a private regular file we own with well-formed content (it is
    never overwritten in that case)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise TmpRootError(f"cannot read the temp-root registry {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TmpRootError(f"the registry {path} must be a private regular file we own")
        raw = os.read(fd, REGISTRY_MAX_BYTES)
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw)
        entries = doc["entries"]
        assert doc["version"] == 1 and isinstance(entries, list)
        for e in entries:
            assert isinstance(e["path"], str) and e["path"].startswith("/")
            assert isinstance(e["role"], str) and isinstance(e["st_dev"], int)
            assert isinstance(e["st_ino"], int)
            assert isinstance(e.get("repo", ""), str)
    except (ValueError, KeyError, TypeError, AssertionError) as exc:
        raise TmpRootError(f"the registry {path} is malformed") from exc
    return entries


def is_registered(role_dir: Path, info: os.stat_result) -> bool:
    """True if this exact directory (path, role name AND device/inode) is registered."""
    try:
        entries = read_registry(registry_path())
    except TmpRootError:
        return False
    real = os.path.realpath(role_dir)
    return any(
        e["path"] == real
        and e["role"] == role_dir.name
        and e["st_dev"] == info.st_dev
        and e["st_ino"] == info.st_ino
        for e in entries or []
    )


REGISTRY_MAX_ENTRIES = 256


class RegistryFullError(TmpRootError):
    """The registry already holds REGISTRY_MAX_ENTRIES entries (exit 3, 'registry-full')."""


def _live(entry: dict) -> bool:
    """An entry is live while its repo dir exists and its path is still the very directory
    registered."""
    repo = entry.get("repo")
    if repo is not None and not os.path.isdir(repo):
        return False  # a stale worktree key that shared a still-live role dir
    try:
        info = os.lstat(entry["path"])
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
        entry["st_dev"],
        entry["st_ino"],
    )


def _repoint_conflict(
    entries: list[dict], repo_real: str, role_name: str, new_path: str
) -> dict | None:
    """The live entry that registers (repo, role) at a DIFFERENT path, if any."""
    for e in entries:
        if (
            e.get("repo") == repo_real
            and e["role"] == role_name
            and e["path"] != new_path
            and _live(e)
        ):
            return e
    return None


def _repoint_message(conflict: dict, new_path: str, repo: str | os.PathLike[str], role: str) -> str:
    script = os.path.abspath(__file__)
    return (
        f"refusing to re-point {conflict['repo']}'s {conflict['role']} temp dir from "
        f"{conflict['path']} to {new_path}: a config.sh edit must not silently move the "
        f"trusted root. Remedy: if the change is intended, run: python3 {script} mark "
        f"--repo {repo} --role {role} --reviewed"
    )


def register(
    role_dir: Path,
    repo: str | os.PathLike[str],
    role: str,
    *,
    reviewed: bool = False,
) -> None:
    """Record this role dir, keyed by (repo realpath, role): the entry for that key is
    REPLACED, never accumulated. Under the flock, entries whose directory is gone or was
    replaced are pruned, and a legacy entry (no ``repo``) at the same path is migrated.
    Re-pointing a key at a different live path needs ``reviewed`` (``mark --reviewed``).
    At REGISTRY_MAX_ENTRIES a new key is refused with the distinct RegistryFullError.
    Atomic (temp file + rename in the same dir), so concurrent resolvers cannot lose or
    corrupt entries."""
    path = registry_path()
    directory = Path(os.path.dirname(path))
    _make_dirs_0700(directory)
    _require_private_dir(directory, tighten=False)
    info = os.lstat(role_dir)
    repo_real = os.path.realpath(repo)
    entry = {
        "path": os.path.realpath(role_dir),
        "role": role_dir.name,
        "repo": repo_real,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }
    try:
        lock_fd = os.open(
            path + ".lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    except OSError as exc:
        raise TmpRootError(f"cannot lock the temp-root registry {path}: {exc}") from exc
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        entries = [e for e in (read_registry(path) or []) if _live(e)]
        if not reviewed:
            new_path, role_name = os.path.realpath(role_dir), role_dir.name
            conflict = _repoint_conflict(entries, repo_real, role_name, new_path)
            if conflict:
                raise TmpRootError(_repoint_message(conflict, new_path, repo, role))
        kept = [
            e
            for e in entries
            if not (e.get("repo") == repo_real and e["role"] == entry["role"])
            and not (e.get("repo") is None and e["path"] == entry["path"])
        ]
        if len(kept) >= REGISTRY_MAX_ENTRIES:
            raise RegistryFullError(
                f"registry-full: {path} already holds {len(kept)} live temp roots "
                f"(limit {REGISTRY_MAX_ENTRIES}); not registering {entry['path']}. Remedy: "
                "delete role dirs you no longer use (their entries are pruned on the next "
                "registration) or remove stale entries from the registry file by hand"
            )
        kept.append(entry)
        tmp = f"{path}.new.{os.getpid()}"
        payload = json.dumps({"version": 1, "entries": kept}, indent=1).encode()
        if len(payload) > REGISTRY_MAX_BYTES:
            # Writing it would make every reader (resolver and reaper) treat it as malformed.
            raise RegistryFullError(
                f"registry-full: {path} would exceed {REGISTRY_MAX_BYTES} bytes with "
                f"{len(kept)} entries; not registering {entry['path']}. Remedy: delete role "
                "dirs you no longer use (their entries are pruned on the next registration) "
                "or remove stale entries from the registry file by hand"
            )
        try:
            fd = os.open(
                tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
            )
        except OSError as exc:
            raise TmpRootError(f"cannot write the temp-root registry {path}: {exc}") from exc
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(tmp, path)
    finally:
        os.close(lock_fd)  # also releases the flock


def _marker_text(role_dir_name: str) -> bytes:
    return f"hos-tmp-root v3 role={role_dir_name}\n".encode()


def write_info_marker(role_dir: Path) -> None:
    """The in-dir marker is INFORMATIONAL only (it holds no secret and grants nothing; the
    registry is the authority). Written if absent; anything already at that name is left
    alone."""
    try:
        fd = os.open(
            role_dir / MARKER,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    except OSError:
        return
    try:
        os.write(fd, _marker_text(role_dir.name))
    finally:
        os.close(fd)


def adoption_problems(role_dir: Path) -> list[str]:
    """Every entry that stops a marker-less role dir being adopted (empty list: adopt)."""
    try:
        names = sorted(os.listdir(role_dir))
    except OSError as exc:
        return [f"an unreadable listing ({exc})"]
    blockers = []
    for name in names:
        if not HOS_ONLY_RE.match(name):
            blockers.append(repr(name))
            continue
        try:
            info = os.lstat(role_dir / name)
        except OSError:
            continue
        if stat.S_ISDIR(info.st_mode) and any(
            os.path.lexists(role_dir / name / project) for project in _PROJECT_NAMES
        ):
            blockers.append(f"{name!r} (it contains project files)")
    return blockers


def _remedy(role_dir: Path, role: str, repo: str | os.PathLike[str], blockers: list[str]) -> str:
    shown = ", ".join(blockers[:5]) + (
        f" and {len(blockers) - 5} more" if len(blockers) > 5 else ""
    )
    script = os.path.abspath(__file__)
    return (
        f"refusing to adopt or chmod {role_dir}: it is not a registered HOS temp dir and holds "
        f"{shown} (is HOS_TMP_ROOT pointing at another project?). Remedy: move those entries "
        f"out of it, or after reviewing it run: python3 {script} mark --repo {repo} "
        f"--role {role} --reviewed"
    )


def resolve_role_dir(
    repo: str | os.PathLike[str], role: str, *, create: bool = False, force_mark: bool = False
) -> Path:
    if role not in ROLE_DIRS:
        raise ValueError(f"unknown role {role!r}")
    root = resolve_root(repo)
    role_dir = root / ROLE_DIRS[role]
    if create:
        repo_real = os.path.realpath(repo)
        if not force_mark:
            # Before creating or chmod-ing anything at a NEW path.
            try:
                known = read_registry(registry_path()) or []
            except TmpRootError:
                known = []
            conflict = _repoint_conflict(
                known, repo_real, role_dir.name, os.path.realpath(role_dir)
            )
            if conflict:
                raise TmpRootError(_repoint_message(conflict, str(role_dir), repo, role))
        _make_dirs_0700(root)
        _require_private_dir(root, tighten=False)
        created = False
        try:
            os.mkdir(role_dir, 0o700)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise TmpRootError(f"cannot create {role_dir}: {exc}") from exc
        _require_private_dir(role_dir, tighten=False)
        if created:
            register(role_dir, repo, role, reviewed=force_mark)
        elif not is_registered(role_dir, os.lstat(role_dir)):
            # First adoption of an unregistered dir: the content checks apply here only.
            blockers = [] if force_mark else adoption_problems(role_dir)
            if blockers:
                raise TmpRootError(_remedy(role_dir, role, repo, blockers))
            register(role_dir, repo, role, reviewed=force_mark)
        # An already-registered dir is accepted whatever it holds (an agent that deletes
        # its marker or adds children cannot lock its role out); the marker is only
        # re-written for the human reader.
        write_info_marker(role_dir)
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


def check_dir(repo: str | os.PathLike[str], path: str) -> None:
    """Raises TmpRootError unless ``path`` is an acceptable temp dir for a run in
    ``repo``. The inner loop uses it on an inherited HOS_TMP_DIR, which this
    module did not necessarily create."""
    if _is_within(os.path.realpath(path), os.path.realpath(repo)):
        raise TmpRootError(f"{path} is inside the clone")
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
    if info.st_mode & 0o077:
        raise TmpRootError(f"{path} is accessible to group or other (not mode 0700)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve", help="print the per-role dir")
    res.add_argument("--repo", required=True)
    res.add_argument("--role", required=True, choices=sorted(ROLE_DIRS))
    res.add_argument("--create", action="store_true")
    mk = sub.add_parser(
        "mark", help="mark an existing role dir as HOS temp AFTER you reviewed its contents"
    )
    mk.add_argument("--repo", required=True)
    mk.add_argument("--role", required=True, choices=sorted(ROLE_DIRS))
    mk.add_argument("--reviewed", action="store_true", required=True)
    rt = sub.add_parser("root", help="print the root")
    rt.add_argument("--repo", required=True)
    val = sub.add_parser("validate", help="check a candidate HOS_TMP_ROOT value")
    val.add_argument("--repo", required=True)
    val.add_argument("--value", required=True)
    chk = sub.add_parser("check-dir", help="check an inherited temp dir")
    chk.add_argument("--repo", required=True)
    chk.add_argument("--dir", required=True)
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
        elif args.command == "check-dir":
            check_dir(args.repo, args.dir)
        elif args.command == "install-default":
            conf = args.projects_conf or os.path.join(
                os.environ.get("HOME") or _home(), ".config", "hos", "projects.conf"
            )
            print(install_default(args.target, args.project_name, Path(conf)))
        elif args.command == "mark":
            print(resolve_role_dir(args.repo, args.role, create=True, force_mark=True))
        else:
            print(resolve_role_dir(args.repo, args.role, create=args.create))
    except TmpRootError as exc:
        print(f"hos_tmp_root: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except OSError as exc:
        print(f"hos_tmp_root: {exc}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
