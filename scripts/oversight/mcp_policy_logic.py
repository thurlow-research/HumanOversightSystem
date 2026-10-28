#!/usr/bin/env python3
"""MCP approved-list policy (#2197) — the logic behind gates/mcp_policy.sh.

HOS installs MCP software only if it is on scripts/oversight/mcp_approved_list.json,
at the listed version. This module loads that list, detects MCP distributions, and
checks (a) HOS's own requirement files statically and (b) the installed dependency
closure reachable from them.

Read-only: no network, no file writes, never imports mcp or semgrep.

Exit codes: 0 = clean, 1 = one or more violations, 2 = cannot check (fail closed).
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LIST = Path(__file__).resolve().parent / "mcp_approved_list.json"
_REQ_SEARCH_DIRS = ("scripts", "bootstrap", "bin")
_SKIP_DIRS = {".venv", "node_modules", "__pycache__"}

_MODES = ("install-only", "run")
_TOP_KEYS = {"schema_version", "entries"}
_REQUIRED_KEYS = {"package", "version", "mode", "reason", "approved_pr"}
_OPTIONAL_KEYS = {"modules", "forbidden_subcommands"}
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SUBCMD_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ListError(Exception):
    """The approved list is unreadable or invalid."""


class CheckError(Exception):
    """The policy could not be evaluated."""


class Entry(NamedTuple):
    package: str
    version: str
    mode: str
    reason: str
    approved_pr: int
    modules: tuple[str, ...]
    forbidden_subcommands: tuple[str, ...]


class Dist(NamedTuple):
    name: str
    version: str
    requires: list[str]
    entry_points: list[tuple[str, str, str]]  # (group, name, value)


def canon(name: str) -> str:
    return canonicalize_name(name)


def has_mcp(text: str) -> bool:
    # Substring, not whole-token: a lookalike such as fastmcp, pymcp or mcp2 must not
    # slip past the policy. False positives are cheap (add a list entry); misses are not.
    return "mcp" in text.lower()


def _name_is_mcp(name: str) -> bool:
    return has_mcp(canon(name))


def _parse_req(line: str, where: str) -> Requirement:
    try:
        return Requirement(line)
    except InvalidRequirement as exc:
        raise CheckError(f"unparseable requirement in {where}: {line!r} ({exc})") from exc


def is_mcp_dist(
    name: str, requires: Iterable[str], entry_points: Iterable[tuple[str, str, str]]
) -> bool:
    if _name_is_mcp(name):
        return True
    for line in requires:
        # Any marker or extra counts: deliberately conservative.
        if _name_is_mcp(_parse_req(line, f"Requires-Dist of {name}").name):
            return True
    for _group, ep_name, ep_value in entry_points:
        if has_mcp(ep_name) or has_mcp(ep_value.split(":", 1)[0]):
            return True
    return False


# --- list ---------------------------------------------------------------


def _fail(msg: str) -> ListError:
    return ListError(msg)


def _str_list(value: object, label: str, item_re: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _fail(f"{label} must be a non-empty list")
    for item in value:
        if not isinstance(item, str) or not item_re.match(item):
            raise _fail(f"{label} has an invalid item: {item!r}")
    return tuple(value)


def _parse_entry(raw: object, idx: int) -> Entry:
    where = f"entries[{idx}]"
    if not isinstance(raw, dict):
        raise _fail(f"{where} is not an object")
    missing = _REQUIRED_KEYS - raw.keys()
    unknown = raw.keys() - _REQUIRED_KEYS - _OPTIONAL_KEYS
    if missing:
        raise _fail(f"{where} missing keys: {sorted(missing)}")
    if unknown:
        raise _fail(f"{where} has unknown keys: {sorted(unknown)}")
    pkg, version, mode, reason, pr = (
        raw[k] for k in ("package", "version", "mode", "reason", "approved_pr")
    )
    if not isinstance(pkg, str) or pkg != canon(pkg) or not pkg:
        raise _fail(f"{where} package must be a canonical (PEP 503) name: {pkg!r}")
    try:
        if not isinstance(version, str):
            raise InvalidVersion(str(version))
        Version(version)
    except InvalidVersion as exc:
        raise _fail(f"{where} version is not a valid version: {version!r}") from exc
    if mode not in _MODES:
        raise _fail(f"{where} mode must be one of {_MODES}: {mode!r}")
    if not isinstance(reason, str) or not reason.strip():
        raise _fail(f"{where} reason must be non-empty")
    if isinstance(pr, bool) or not isinstance(pr, int) or pr <= 0:
        raise _fail(f"{where} approved_pr must be an integer > 0: {pr!r}")
    modules: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    if mode == "install-only":
        if "modules" not in raw:
            raise _fail(f"{where} install-only entry needs modules")
        modules = _str_list(raw["modules"], f"{where} modules", _MODULE_RE)
        if "forbidden_subcommands" in raw:
            raise _fail(f"{where} forbidden_subcommands is only valid on a run entry")
    else:
        if "modules" in raw:
            raise _fail(f"{where} modules is only valid on an install-only entry")
        if "forbidden_subcommands" in raw:
            forbidden = _str_list(
                raw["forbidden_subcommands"], f"{where} forbidden_subcommands", _SUBCMD_RE
            )
    return Entry(pkg, version, mode, reason, pr, modules, forbidden)


def load_list(path: Path | str) -> dict[str, Entry]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"cannot read approved list {path}: {exc}") from exc
    if not isinstance(doc, dict) or doc.keys() != _TOP_KEYS:
        raise _fail(f"top level must be an object with exactly keys {sorted(_TOP_KEYS)}")
    sv = doc["schema_version"]
    if isinstance(sv, bool) or sv != 1:
        raise _fail(f"schema_version must be 1: {sv!r}")
    entries = doc["entries"]
    if not isinstance(entries, list) or not entries:
        raise _fail("entries must be a non-empty list")
    out: dict[str, Entry] = {}
    for i, raw in enumerate(entries):
        e = _parse_entry(raw, i)
        if e.package in out:
            raise _fail(f"duplicate package in list: {e.package}")
        out[e.package] = e
    return out


# --- static check -------------------------------------------------------


def discover_requirement_files(root: Path = _REPO_ROOT) -> list[Path]:
    found = [root / "scripts" / "oversight" / "requirements.txt"]
    for top in _REQ_SEARCH_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
            )
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if fn.startswith("requirements") and fn.endswith(".txt") and p not in found:
                    found.append(p)
    return found


def read_requirements(files: Iterable[Path]) -> list[tuple[Requirement, str, int]]:
    """Return (requirement, file, lineno) for every requirement line."""
    out: list[tuple[Requirement, str, int]] = []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CheckError(f"cannot read requirements file {f}: {exc}") from exc
        for n, raw in enumerate(text.splitlines(), 1):
            line = re.sub(r"(^|\s)#.*$", "", raw).strip()
            if not line:
                continue
            where = f"{f}:{n}"
            if line.startswith("-"):
                raise CheckError(
                    f"{where}: option lines are unsupported in HOS requirement files: {line!r}"
                )
            out.append((_parse_req(line, where), str(f), n))
    return out


def check_requirements(files: Iterable[Path], approved: dict[str, Entry]) -> list[str]:
    violations: list[str] = []
    for req, f, n in read_requirements(files):
        c = canon(req.name)
        entry = approved.get(c)
        if entry is not None:
            specs = list(req.specifier)
            ok = False
            if len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version:
                try:
                    ok = Version(specs[0].version) == Version(entry.version)
                except InvalidVersion:
                    ok = False
            if not ok:
                violations.append(
                    f"{f}:{n} {req.name}{req.specifier} — listed version is =={entry.version}"
                )
        elif _name_is_mcp(req.name):
            violations.append(f"{f}:{n} unlisted MCP package {req.name}")
    return violations


# --- installed check ----------------------------------------------------


def _marker_ok(req: Requirement, extras: Iterable[str]) -> bool:
    if req.marker is None:
        return True
    return any(req.marker.evaluate({"extra": e}) for e in set(extras) | {""})


def check_installed(
    dists: Iterable[Dist],
    root_reqs: Iterable[tuple[Requirement, str]],
    approved: dict[str, Entry],
) -> tuple[list[str], list[str]]:
    """Return (violations, notes)."""
    index: dict[str, Dist] = {}
    for d in dists:
        c = canon(d.name)
        if c in index:
            raise CheckError(f"duplicate installed distribution: {c}")
        index[c] = d

    parent: dict[str, str] = {}
    requested: dict[str, set[str]] = {}
    queue: list[tuple[str, set[str]]] = []

    def enqueue(target: Requirement, via: str) -> None:
        c = canon(target.name)
        if c not in index:
            raise CheckError(
                f"venv inconsistent: {via} requires {target.name} but it is not installed"
            )
        extras = {canon(e) for e in target.extras}
        new = extras - requested.get(c, set())
        if c not in requested:
            requested[c] = set()
            parent[c] = via
            queue.append((c, extras))
        elif new:
            queue.append((c, new))
        requested[c] |= extras

    for req, source in root_reqs:
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        enqueue(req, source)

    while queue:
        c, extras = queue.pop()
        d = index[c]
        for line in d.requires:
            r = _parse_req(line, f"Requires-Dist of {d.name}")
            if _marker_ok(r, extras):
                enqueue(r, c)

    def chain(c: str) -> str:
        parts = [c]
        p = parent[c]
        while p in requested:  # parent is set on first visit only, so this is a tree
            parts.append(p)
            p = parent[p]
        return " <- ".join([*parts, p])

    violations: list[str] = []
    notes: list[str] = []
    for c in sorted(index):
        d = index[c]
        if not is_mcp_dist(d.name, d.requires, d.entry_points):
            continue
        try:
            installed = Version(d.version)
        except InvalidVersion as exc:
            raise CheckError(f"{d.name} has an unparseable version {d.version!r}") from exc
        if c not in requested:
            notes.append(
                f"NOTE (not gated until #2199): {c}=={d.version} is an MCP package "
                "outside HOS's dependency closure"
            )
            continue
        entry = approved.get(c)
        if entry is None:
            violations.append(f"unlisted MCP package {c}=={d.version} (via {chain(c)})")
        elif installed != Version(entry.version):
            violations.append(f"{c}=={d.version} installed, list says =={entry.version}")
    return violations, notes


def collect_dists(site_path: str | None = None) -> list[Dist]:
    found = md.distributions(path=[site_path]) if site_path else md.distributions()
    out: list[Dist] = []
    for d in found:
        name = d.metadata["Name"]
        if not name:
            raise CheckError("installed distribution with no Name in its metadata")
        out.append(
            Dist(
                name,
                d.version,
                list(d.requires or []),
                [(ep.group, ep.name, ep.value) for ep in d.entry_points],
            )
        )
    return out


# --- CLI ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HOS MCP approved-list policy check (#2197)")
    ap.add_argument("--list", dest="list_path", default=str(_DEFAULT_LIST))
    ap.add_argument("--requirements", nargs="+", default=None)
    ap.add_argument("--installed", action="store_true")
    ap.add_argument("--site-path", default=None, help="test seam: read distributions from this dir")
    args = ap.parse_args(argv)
    try:
        approved = load_list(args.list_path)
        files = (
            [Path(p) for p in args.requirements]
            if args.requirements
            else discover_requirement_files()
        )
        violations = check_requirements(files, approved)
        notes: list[str] = []
        if args.installed:
            roots = [(r, f"{f}:{n}") for r, f, n in read_requirements(files)]
            v2, notes = check_installed(collect_dists(args.site_path), roots, approved)
            violations += v2
    except (ListError, CheckError) as exc:
        print(f"mcp_policy: cannot check: {exc}", file=sys.stderr)
        return 2
    for note in notes:
        print(note)
    for v in violations:
        print(f"VIOLATION: {v}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
