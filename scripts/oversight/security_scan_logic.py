#!/usr/bin/env python3
"""security_scan_logic.py — advisory-level exemptions for the pip-audit gate (#1776).

`security_scan.sh` runs pip-audit against the oversight venv and blocks on any
reported advisory. That made the gate permanently red: advisories sit in
tools HOS uses but cannot yet upgrade (black x2, and mcp via semgrep's pin),
and a gate that is always red stops carrying information (DECISIONS.md:787
recorded it as accepted debt; #1776 is the ruling that ends it).

THE RULINGS
-----------
  * 2026-10-02 (#1776): time-boxed, individually-justified, VISIBLE exemptions
    in the #1754 shape; anything new fails closed.
  * 2026-10-03 (#1776): black is exempted on a timebox (its upgrade is the
    117-file reformat tracked in #1961, blocked by the deliberate `black<25`
    pin of #103); PyJWT is handled by a version floor in requirements.txt
    (`pyjwt>=2.15.0`) alone. The floor clears all 13 of its advisories:
    PYSEC-2026-4146 affects 2.11.0-2.13.0 only (OSV last_affected 2.13.0), so no
    PyJWT exemption is shipped (architect ruling, design doc section 15 B1).
  * 2026-10-20 (#1776, Option M): mcp 1.29.0 CVE-2026-59951 is exempted on the
    same 2027-01-31 timebox as black. mcp is reachable only as a dependency of
    semgrep, which hard-pins mcp==1.29.0 (so no fixed combination is
    installable); the upgrade is tracked in #2120.

WHY ADVISORY-LEVEL, NOT A pip-audit SKIP
----------------------------------------
`pip-audit --ignore-vuln ID` or skipping a package would silence the advisory
without printing it. Here the audit runs in full, every reported advisory is
considered, and only an advisory matching a roster record on ALL of (canonical
package name, advisory id, version bound, expiry) is moved from "kept" to
"suppressed". Everything else — a new package, a NEW id on black or PyJWT, an
installed version at or above the record's `fixed_in` — is kept and fails the
gate.

THE NO-FIX KEY
--------------
A record with `fixed_in=None` says "no fix exists" (no shipped record currently
uses this key; it stays, covered by tests, for the next genuine no-fix case).
It therefore matches only while the deduplicated advisory's `fix_versions` is
EMPTY. The moment any source reports a fix, the record goes inert, the advisory
is kept, and the note says `FIX NOW AVAILABLE` with the remedy. No upper version
bound is used: a justification of non-reachability does not vary with the
package version; expiry is the box.
`fix_versions` strings are otherwise display-only, because the same advisory
arrives as `26.2` from one source and `26.2.0` from another.

SCOPE (H2)
----------
The roster is active ONLY in the HOS source repository, by a positive check
(`roster_mode`): `.hos-release` absent AND `bootstrap/hos_install.sh` present,
rooted at this module's own repository. Anything else — an installed consumer
tree, a probe error, an ambiguous layout — means an EMPTY roster, which is
exactly the behaviour before #1776. Known fail-closed edge: if HOS ever
self-installs (writing `.hos-release` into the source repo) the roster turns
inactive and the gate goes red; whoever lands that must revisit the predicate.

VISIBILITY
----------
Nothing is silent. Every run prints the roster mode; in the source repo it also
prints every record with its status, an `EXPIRING SOON` warning inside 14 days
of expiry, and each suppressed advisory with its id, reason, expiry and tracking
issue. A pip-audit dependency that was skipped is printed `NOT CHECKED`.

EXPIRY
------
Records are valid through their `expires` date inclusive and are kept with
`EXEMPTION EXPIRED` from the next day. There is deliberately no `--today` flag
and no environment override for the clock: the pure functions take `today` as a
parameter (tests pass it), and `main` reads the UTC clock exactly once.

EXIT CODES
----------
0 = nothing kept; 1 = at least one advisory kept; 2 = could not decide
(unreadable audit, invalid roster, missing `packaging`, any crash). Every
failure to decide is 2 — never a pass.

PURITY
------
Every function except `roster_mode` (filesystem probes only) and `main` is pure:
no I/O and no clock. Only the CLI shim reads stdin.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

try:
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version

    _IMPORT_ERROR: str | None = None
# The real ImportError needs `packaging` absent, but this suite runs in the venv
# that requires it, so the path cannot be reproduced in-suite.
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

_UNATTRIBUTABLE = "<unattributable>"
_UNKNOWN_ID = "<unknown>"
_EXPIRY_WARNING_DAYS = 14
_MIN_REASON_CHARS = 40

_HINT = (
    "  HINT: if scripts/oversight/requirements.txt declares a floor above an "
    "installed version listed here, this venv predates it — run: "
    "scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt "
    "(no --upgrade). Otherwise the advisory is new: upgrade the package, or get "
    "a human ruling before adding an exemption."
)


class Advisory(NamedTuple):
    package: str
    key: str
    version: str
    advisory_id: str
    fix_versions: tuple[str, ...]
    aliases: tuple[str, ...]
    malformed: bool
    malformed_why: str | None


class Exemption(NamedTuple):
    package: str
    advisory_id: str
    fixed_in: str | None
    expires: datetime.date
    reason: str
    tracking_issue: int


class Skipped(NamedTuple):
    name: str
    version: str
    reason: str


class AuditDoc(NamedTuple):
    advisories: list[Advisory]
    skipped: list[Skipped]
    raw_count: int
    distinct_count: int
    dependency_count: int


class RosterMode(NamedTuple):
    active: bool
    why: str


class Kept(NamedTuple):
    advisory: Advisory
    note: str | None


class Suppressed(NamedTuple):
    advisory: Advisory
    exemption: Exemption


class Decision(NamedTuple):
    kept: list[Kept]
    suppressed: list[Suppressed]
    roster: list[tuple[Exemption, str]]


class AuditParseError(Exception):
    """The audit document has a shape from which nothing can be decided."""


# --------------------------------------------------------------------------- #
# Roster. Each record answers: what is the vulnerability, how does the package
# reach HOS, why is it unreachable here. Changing a record is a protected-surface
# change and needs a human decision (#1776).
# --------------------------------------------------------------------------- #
SUPPRESSIONS: tuple[Exemption, ...] = (
    Exemption(
        package="black",
        advisory_id="PYSEC-2026-2120",
        fixed_in="26.3.0",
        expires=datetime.date(2027, 1, 31),
        tracking_issue=1961,
        # What: Black's GitHub Action with `use_pyproject: true` reads the Black
        # version from pyproject.toml, so a malicious PR could point it at a
        # malicious package and execute code inside the Action.
        reason=(
            "Black's GitHub Action with use_pyproject: true reads the Black version "
            "from pyproject.toml, so a malicious PR could point it at a malicious "
            "package and execute code in the Action. HOS never uses the Black GitHub "
            "Action (no workflow references psf/black); black runs only as a local "
            "formatter checker (lint_check.sh: black --check --diff --quiet <files>). "
            "The fix (26.3.0) is blocked by the deliberate black>=24.0,<25.0 pin "
            "(#103); the upgrade plus the 117-file reformat is #1961. "
            "The no-Action premise is enforced by tests PR3 (and PR1/PR2). "
            "Human ruling #1776, 2026-10-03."
        ),
    ),
    Exemption(
        package="black",
        advisory_id="PYSEC-2026-2121",
        fixed_in="26.3.1",
        expires=datetime.date(2027, 1, 31),
        tracking_issue=1961,
        # What: the cache-file name is built from formatting options and embeds
        # the --python-cell-magics value unsanitised (arbitrary-path cache write).
        # pip-audit reports this advisory twice; dedup collapses it to one.
        reason=(
            "Black builds its cache-file name from formatting options and placed the "
            "--python-cell-magics value in it unsanitised, letting whoever controls "
            "that option write cache files to arbitrary paths. HOS never passes "
            "--python-cell-magics: lint_check.sh invokes black --check --diff --quiet "
            "<files> and pyproject.toml [tool.black] sets only line-length and "
            "target-version. The fix (26.3.1) is blocked by the #103 pin; tracked in "
            "#1961. The never-set premise is enforced by tests PR1 and PR2. "
            "Human ruling #1776, 2026-10-03."
        ),
    ),
    Exemption(
        package="mcp",
        advisory_id="CVE-2026-59951",
        fixed_in="1.30.0",
        expires=datetime.date(2027, 1, 31),
        tracking_issue=2120,
        # What: a Streamable HTTP MCP *server* in stateful mode (FastMCP 1.x default,
        # StreamableHTTPSessionManager) never reclaims session state, so any client
        # that can reach the endpoint grows server memory without bound. stdio/SSE
        # transports and stateless_http=True are not affected. Fixed in 1.30.0 / 2.2.0;
        # the 2.x fix is irrelevant here because semgrep pins the 1.x line.
        reason=(
            "A Streamable HTTP MCP server in stateful mode never reclaims session "
            "state, so a client that can reach the endpoint grows server memory "
            "without bound; only serving MCP over Streamable HTTP is affected. HOS "
            "never imports mcp directly and never starts an MCP server (never launches "
            "semgrep's MCP subcommand, never uses FastMCP, mcp.server or streamable_http_app); "
            "mcp is loaded only as an import side effect of semgrep's CLI "
            "(static_analysis.py, static_analysis_js.py), which does not start a "
            "Streamable HTTP server. semgrep pins mcp==1.29.0 (1.181.0 is the latest), "
            "so no fixed combination is installable; upgrade mcp once semgrep unpins "
            "it, tracked in #2120. The no-server premise is enforced by tests PR4 "
            "and PR5. Human ruling #1776, 2026-10-20."
        ),
    ),
)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _malformed(
    package: str, version: str, why: str, advisory_id: str = _UNATTRIBUTABLE
) -> Advisory:
    return Advisory(package, package, version, advisory_id, (), (), True, why)


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    return ()


def _shown(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _incomplete_fields(entry: dict) -> list[str]:
    """Describe the fields that stop a non-skip entry counting as audited."""
    missing: list[str] = []
    for field in ("name", "version"):
        value = entry.get(field)
        if not (isinstance(value, str) and value):
            state = "missing" if field not in entry else "empty or not a string"
            missing.append(f"'{field}' {state}")
    if not isinstance(entry.get("vulns"), list):
        state = "missing" if "vulns" not in entry else "not a list"
        missing.append(f"'vulns' {state}")
    return missing


def _parse_vulns(name: object, version: object, vulns: object) -> list[Advisory]:
    shown_name = name if isinstance(name, str) and name else "<unknown>"
    shown_version = version if isinstance(version, str) and version else "?"
    if not isinstance(vulns, list):
        return [
            _malformed(shown_name, shown_version, f"'vulns' is {type(vulns).__name__}, not a list")
        ]
    if not (isinstance(name, str) and name and isinstance(version, str) and version):
        return [
            _malformed(shown_name, shown_version, "dependency name/version missing or not a string")
            for _ in vulns
        ]
    out: list[Advisory] = []
    for vuln in vulns:
        if not isinstance(vuln, dict):
            out.append(_malformed(name, version, "vuln entry is not a mapping", _UNKNOWN_ID))
            continue
        vid = vuln.get("id")
        if not isinstance(vid, str) or not vid:
            out.append(_malformed(name, version, "vuln entry has no usable 'id'", _UNKNOWN_ID))
            continue
        if "fix_versions" not in vuln:
            out.append(_malformed(name, version, "'fix_versions' is missing", vid))
            continue
        fixes = vuln["fix_versions"]
        if not (isinstance(fixes, list) and all(isinstance(v, str) for v in fixes)):
            out.append(
                _malformed(
                    name,
                    version,
                    f"'fix_versions' is {type(fixes).__name__}, not a list of strings",
                    vid,
                )
            )
            continue
        out.append(
            Advisory(
                package=name,
                key=canonicalize_name(name),
                version=version,
                advisory_id=vid,
                fix_versions=tuple(fixes),
                aliases=_str_tuple(vuln.get("aliases")),
                malformed=False,
                malformed_why=None,
            )
        )
    return out


def _dedup(advisories: list[Advisory]) -> list[Advisory]:
    """Collapse duplicates on (key, version, id), unioning fix_versions/aliases."""
    slots: list[Advisory] = []
    index: dict[tuple[str, str, str], int] = {}
    for adv in advisories:
        if adv.malformed:
            slots.append(adv)
            continue
        ident = (adv.key, adv.version, adv.advisory_id)
        if ident not in index:
            index[ident] = len(slots)
            slots.append(adv)
            continue
        first = slots[index[ident]]
        slots[index[ident]] = first._replace(
            fix_versions=tuple(dict.fromkeys(first.fix_versions + adv.fix_versions)),
            aliases=tuple(dict.fromkeys(first.aliases + adv.aliases)),
        )
    return slots


def parse_audit(document: object) -> AuditDoc:
    if not isinstance(document, dict):
        raise AuditParseError(f"root is {type(document).__name__}, not a mapping")
    deps = document.get("dependencies")
    if not isinstance(deps, list):
        raise AuditParseError("'dependencies' is missing or not a list")
    if not deps:
        raise AuditParseError("'dependencies' is empty — nothing was audited")
    advisories: list[Advisory] = []
    skipped: list[Skipped] = []
    for entry in deps:
        if not isinstance(entry, dict):
            advisories.append(
                _malformed(
                    "<unknown>", "?", f"dependency entry is {type(entry).__name__}, not a mapping"
                )
            )
            continue
        if "skip_reason" in entry:
            skipped.append(
                Skipped(
                    str(entry.get("name", "?")),
                    str(entry.get("version", "?")),
                    str(entry["skip_reason"]),
                )
            )
        else:
            # A real pip-audit entry is {name, version, vulns:list}. Anything less
            # was not demonstrably audited, so it must not count as clean.
            missing = _incomplete_fields(entry)
            if missing:
                advisories.append(
                    _malformed(
                        _shown(entry.get("name"), "<unknown>"),
                        _shown(entry.get("version"), "?"),
                        f"dependency entry is incomplete: {', '.join(missing)}",
                    )
                )
                continue
        if "vulns" not in entry:
            continue
        vulns = entry["vulns"]
        if isinstance(vulns, list) and not vulns:
            continue
        advisories.extend(_parse_vulns(entry.get("name"), entry.get("version"), vulns))
    distinct = _dedup(advisories)
    return AuditDoc(distinct, skipped, len(advisories), len(distinct), len(deps))


# --------------------------------------------------------------------------- #
# Roster validation and scope
# --------------------------------------------------------------------------- #
def validate_exemptions(rules: Iterable[Exemption]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[object, object]] = set()
    for i, rec in enumerate(rules):
        tag = f"record {i}"
        pkg = getattr(rec, "package", None)
        aid = getattr(rec, "advisory_id", None)
        if isinstance(pkg, str) and pkg:
            tag = f"{pkg} [{aid}]"
            if canonicalize_name(pkg) != pkg:
                errors.append(f"{tag}: package {pkg!r} is not PEP 503 canonical")
        else:
            errors.append(f"{tag}: package must be a non-empty string")
        if not isinstance(aid, str) or not aid or any(c.isspace() for c in aid):
            errors.append(f"{tag}: advisory_id must be a non-empty string without whitespace")
        fixed_in = getattr(rec, "fixed_in", None)
        if fixed_in is not None:
            try:
                Version(fixed_in)
            except (InvalidVersion, TypeError):
                errors.append(f"{tag}: fixed_in {fixed_in!r} is not a PEP 440 version")
        expires = getattr(rec, "expires", None)
        if not isinstance(expires, datetime.date) or isinstance(expires, datetime.datetime):
            errors.append(f"{tag}: expires must be a datetime.date, got {type(expires).__name__}")
        reason = getattr(rec, "reason", None)
        if not isinstance(reason, str) or len(reason.strip()) < _MIN_REASON_CHARS:
            errors.append(f"{tag}: reason must be at least {_MIN_REASON_CHARS} characters")
        issue = getattr(rec, "tracking_issue", None)
        if isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0:
            errors.append(f"{tag}: tracking_issue must be a positive int")
        ident = (pkg, aid)
        if ident in seen:
            errors.append(f"{tag}: duplicate (package, advisory_id)")
        seen.add(ident)
    return errors


def roster_mode(root: Path) -> RosterMode:
    try:
        if os.path.lexists(root / ".hos-release"):
            return RosterMode(False, "installed tree: .hos-release present")
        if not (root / "bootstrap" / "hos_install.sh").is_file():
            return RosterMode(False, "bootstrap/hos_install.sh not found")
    except OSError as exc:
        return RosterMode(False, f"could not determine: {type(exc).__name__}: {exc}")
    return RosterMode(
        True, "HOS source repository: bootstrap/hos_install.sh present, no .hos-release"
    )


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
def _kept_by_rule(adv: Advisory, rule: Exemption, today: datetime.date) -> tuple[str, str] | None:
    """Return (keyword, note) when a matching rule does NOT apply, else None."""
    try:
        installed = Version(adv.version)
    except InvalidVersion:
        return (
            "UNPARSEABLE VERSION",
            f"UNPARSEABLE VERSION: installed version {adv.version!r} is not PEP 440, "
            "so it cannot be bounded by the exemption.",
        )
    issue = rule.tracking_issue
    if rule.fixed_in is not None and installed >= Version(rule.fixed_in):
        return (
            "PREMISE BROKEN",
            f"PREMISE BROKEN: the exemption declares fixed_in={rule.fixed_in}, but "
            f"pip-audit reports this advisory at installed {adv.version} "
            f"(>= {rule.fixed_in}). Re-check the advisory and update or remove the "
            f"record (#{issue}).",
        )
    if rule.fixed_in is None and adv.fix_versions:
        return (
            "FIX NOW AVAILABLE",
            "FIX NOW AVAILABLE: the exemption was granted because no fix existed, but "
            f"pip-audit now reports fix {', '.join(adv.fix_versions)}. Raise the floor in "
            f"scripts/oversight/requirements.txt and remove the record (#{issue}).",
        )
    if today > rule.expires:
        return (
            "EXEMPTION EXPIRED",
            f"EXEMPTION EXPIRED {rule.expires} (today {today}) — #{issue}. It no longer "
            "applies; renew only with a fresh human decision, or fix the dependency. "
            f"Original justification: {rule.reason}",
        )
    return None


def partition(
    advisories: list[Advisory], rules: tuple[Exemption, ...], today: datetime.date
) -> Decision:
    kept: list[Kept] = []
    suppressed: list[Suppressed] = []
    applied: set[int] = set()
    not_applied: dict[int, str] = {}
    for adv in advisories:
        if adv.malformed:
            kept.append(
                Kept(
                    adv,
                    f"UNATTRIBUTABLE: {adv.malformed_why} — a malformed audit record is "
                    "never exempted.",
                )
            )
            continue
        idx = next(
            (
                i
                for i, r in enumerate(rules)
                if r.package == adv.key and r.advisory_id == adv.advisory_id
            ),
            None,
        )
        if idx is None:
            kept.append(Kept(adv, None))
            continue
        verdict = _kept_by_rule(adv, rules[idx], today)
        if verdict is None:
            suppressed.append(Suppressed(adv, rules[idx]))
            applied.add(idx)
        else:
            kept.append(Kept(adv, verdict[1]))
            not_applied.setdefault(idx, verdict[0])
    roster: list[tuple[Exemption, str]] = []
    for i, rule in enumerate(rules):
        if i in applied:
            status = "APPLIED"
        elif i in not_applied:
            status = f"NOT APPLIED: {not_applied[i]}"
        else:
            status = "NOT NEEDED (not reported in this environment)"
        roster.append((rule, status))
    return Decision(kept, suppressed, roster)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _fixes(adv: Advisory) -> str:
    return ", ".join(adv.fix_versions) or "none"


def render(
    doc: AuditDoc,
    decision: Decision,
    mode: RosterMode,
    rules: tuple[Exemption, ...],
    today: datetime.date,
) -> tuple[list[str], int]:
    out: list[str] = []
    if mode.active:
        out.append(f"  Exemption roster: ACTIVE ({mode.why}) — {len(rules)} record(s), #1776")
        for rule, status in decision.roster:
            out.append(
                f"    {rule.package} [{rule.advisory_id}] fixed_in "
                f"{rule.fixed_in or 'none published'} — expires {rule.expires} — "
                f"{status} — #{rule.tracking_issue}"
            )
        for rule in rules:
            days = (rule.expires - today).days
            if 0 <= days <= _EXPIRY_WARNING_DAYS:
                out.append(
                    f"  EXPIRING SOON: {rule.package} [{rule.advisory_id}] exemption "
                    f"expires {rule.expires} ({days} day(s)) — renew only with a fresh "
                    f"human decision, or fix the dependency (#{rule.tracking_issue})"
                )
    else:
        out.append(
            f"  Exemption roster: INACTIVE ({mode.why}) — every advisory is enforced; "
            "a consumer-owned roster is not yet supported (#1776 H2)"
        )
    for skip in doc.skipped:
        out.append(
            f"  NOT CHECKED: {skip.name} {skip.version} was not audited by pip-audit "
            f"({skip.reason})"
        )
    if decision.suppressed:
        out.append(
            f"  {len(decision.suppressed)} advisory(ies) suppressed by a time-boxed exemption:"
        )
        for sup in decision.suppressed:
            adv, rule = sup.advisory, sup.exemption
            out.append(
                f"    {adv.package} {adv.version} [{adv.advisory_id}] fix: {_fixes(adv)} — "
                f"exempt until {rule.expires} (#{rule.tracking_issue}): {rule.reason}"
            )
    if decision.kept:
        out.append(
            f"GATE FAIL: {len(decision.kept)} dependency advisory(ies) not covered by an exemption:"
        )
        for item in decision.kept:
            adv = item.advisory
            out.append(f"  {adv.package} {adv.version} [{adv.advisory_id}] fix: {_fixes(adv)}")
            if item.note:
                out.append(f"    {item.note}")
        out.append(_HINT)
        return out, 1
    unchecked = f", {len(doc.skipped)} NOT CHECKED" if doc.skipped else ""
    out.append(
        "OK: no dependency advisories outside the exemption roster "
        f"({len(decision.suppressed)} suppressed; {doc.distinct_count} distinct "
        f"advisory(ies) from {doc.raw_count} raw record(s); "
        f"{doc.dependency_count} dependencies read{unchecked})"
    )
    return out, 0


def run_filter(
    stdin_text: str, rules: tuple[Exemption, ...], mode: RosterMode, today: datetime.date
) -> tuple[list[str], list[str], int]:
    refusal = "refusing to report a pass on an audit that cannot be read"
    try:
        document = json.loads(stdin_text)
        doc = parse_audit(document)
    except (json.JSONDecodeError, AuditParseError) as exc:
        return (
            [],
            [
                f"GATE FAIL: could not parse pip-audit output ({type(exc).__name__}: {exc}) — {refusal}"
            ],
            2,
        )
    # H2 is enforced here, not left to the caller: an inactive mode has no roster.
    effective_rules = rules if mode.active else ()
    if mode.active:
        errors = validate_exemptions(effective_rules)
        if errors:
            return [], [f"GATE FAIL: exemption roster invalid — {e}" for e in errors], 2
    decision = partition(doc.advisories, effective_rules, today)
    lines, status = render(doc, decision, mode, effective_rules, today)
    return lines, [], status


# --------------------------------------------------------------------------- #
# CLI shim
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pip-audit advisory exemption filter (#1776)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("filter", help="read pip-audit JSON on stdin, print the verdict")
    parser.parse_args(argv)
    if _IMPORT_ERROR is not None:
        print(
            f"GATE FAIL: security_scan_logic could not import 'packaging' ({_IMPORT_ERROR}) "
            "— nothing was decided",
            file=sys.stderr,
        )
        return 2
    try:
        mode = roster_mode(Path(__file__).resolve().parents[2])
        rules = SUPPRESSIONS if mode.active else ()
        today = datetime.datetime.now(datetime.timezone.utc).date()
        out, err, status = run_filter(sys.stdin.read(), rules, mode, today)
    except Exception as exc:  # noqa: BLE001 — any crash must be exit 2, never a pass
        print(
            f"GATE FAIL: security_scan_logic crashed ({type(exc).__name__}: {exc}) "
            "— nothing was decided",
            file=sys.stderr,
        )
        return 2
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
