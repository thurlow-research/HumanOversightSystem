#!/usr/bin/env python3
"""gen_sandbox_config.py — generate or check a clone's sandbox policy (#1221).

Turns the tracked `contract/sandbox-policy.template.json` into a clone's live
`.claude/settings.local.json`, and separately checks whether a clone's live
policy still matches a fresh generation from the template.

THE PURITY INVARIANT (AD-1, restated by ADDENDUM-1221 §3.6 — binding):
    No byte that generate mode writes may depend on the content of the live
    file or of the values sidecar. `render(template_text, values)` takes no
    path parameter of any kind; generate mode's only contact with the live
    file is a post-render classification (`classify_live`) that may influence
    only *whether* a write happens and *what* is printed — never the bytes.
    `--check` is the only mode that reads the live file to compare it.

NEVER-OVERWRITE (2026-08-15 human ruling on #1221 — supersedes the original
FR-7 "refuse without --force" design; see docs/v0.6.0/ADDENDUM-1221-…md):
    `generate` NEVER modifies an existing `settings.local.json`. There is no
    `--force` flag and no flag that reinstates overwriting. A present,
    parseable file is left untouched (an informational advisory is printed);
    a present, unparseable/corrupt file is reported and left untouched. The
    operator's own hand — `mv <live> <live>.bak-<UTC>` — is the only way to
    clear a file out of the way, and the tool prints that exact command.

ENROLLMENT (2026-08-16 human ruling on #1221 — resolves the "remaining
scope" item 2 raised against the ruling above): a present, parseable
`settings.local.json` with no values sidecar yet is a hand-maintained clone
that has never been enrolled. `generate` in that case writes ONLY the
`.claude/hos-sandbox.values` sidecar, adopting the existing live file as this
clone's baseline — `settings.local.json` itself is still never touched. This
is what lets `--check` compare going forward instead of returning
`EXIT_NOT_ENROLLED` forever. If the sidecar already exists, generate is a
true no-op in this branch (nothing written, matching the invariant above).

Usage:
    # Generate (writes only into a clone with no existing sandbox policy):
    python3 scripts/framework/gen_sandbox_config.py \\
        --role human --clone-dir /srv/hos/Human \\
        --handoff-dir /srv/hos/handoff/human \\
        --claude-project-state /home/hosuser/.claude/projects/-srv-hos-Human

    # Check (compare only; never writes):
    python3 scripts/framework/gen_sandbox_config.py \\
        --role human --clone-dir /srv/hos/Human --check

Exit codes (all seven are pairwise distinct; `1` is reserved for divergence
alone — an unhandled exception must never leak Python's default bare `1`):

    0  EXIT_OK                 generate: file written, or an existing usable
                                file left untouched. check: live matches a
                                fresh generation.
    1  EXIT_DIVERGENT          check only: live file diverges (incl. missing,
                                unparseable, or a surviving __NAME__).
    2  EXIT_USAGE              bad/missing/conflicting flags, bad --clone-dir,
                                an invalid value.
    3  EXIT_UNSUPPORTED_ROLE   --role worker / --role overseer — refused,
                                naming #1146. Occurs before any filesystem
                                access.
    4  EXIT_UNUSABLE_EXISTING  generate only: an existing live file is
                                present but unparseable/empty/unreadable.
                                Nothing written, nothing clobbered.
    5  EXIT_HARD_FAIL          surviving placeholder, malformed template,
                                corrupt/incomplete/wrong-version values
                                sidecar, or any unexpected internal error.
    6  EXIT_NOT_ENROLLED       check only: no values sidecar — this clone's
                                policy was never generated; it is
                                hand-maintained. Distinct from divergence.

`--role worker` and `--role overseer` are refused (FR-5): per-role sandbox
rule content is #1146's work, not this generator's.
"""

# ── Template reconciliation notes (FR-11 / FR-12 / AD-8) ───────────────────
#
# contract/sandbox-policy.template.json carries deliberate redundancy that
# this generator does NOT introduce at runtime — it is a one-time, reviewed
# edit to the tracked template (AD-1's corollary: there is no "merge" mode).
# Recorded here because JSON has no comment syntax.
#
# 1. Three `bin/**` deny spellings — relative (`Edit(./bin/**)`, the spelling
#    CLAUDE.md refers to), single-slash absolute (`Edit(__PROJECT_ROOT__/bin/**)`),
#    and double-slash absolute (`Edit(/__PROJECT_ROOT__/bin/**)`, the live,
#    production-proven form). The redundancy is deliberate: Claude Code's
#    permission-glob matching of relative-vs-absolute and single-vs-double-slash
#    is UNVERIFIED (docs/SANDBOX-POLICY.md §4 item 7). It costs zero capability
#    and may be pruned once #1146 verifies the matcher.
#
# 2. Six force-push deny spellings: `Bash(git push* -f*)`, `Bash(git push*--force*)`
#    (the two live-only spellings, now tracked), plus the four already in the
#    template — `Bash(git push * --force*)`, `Bash(git push * -f)`,
#    `Bash(git push -f *)`, and `Bash(git push* +*)` (the `+refspec` form —
#    VF-5/AD-8 required retaining it; a deny is only ever added, never
#    subtracted). `--force-with-lease` matches `*--force*` and is therefore
#    denied — intended, not a regression (VF-11): a lease-guarded force push
#    is still a force push.
#
# 3. Three values-sidecar deny spellings (`.claude/hos-sandbox.values`,
#    relative and both absolute forms) — the sidecar must be non-agent-editable
#    because it steers the generation of the policy itself (AD-5); the same
#    FR-11 redundancy reasoning applies, for a stronger reason: this is a NEW
#    entry under the same unverified glob semantics, guarding the file with the
#    highest leverage in the whole feature.

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Module-level constants (§2.4) ───────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_RELPATH = "contract/sandbox-policy.template.json"
TEMPLATE_PATH = REPO_ROOT / TEMPLATE_RELPATH
LIVE_RELPATH = ".claude/settings.local.json"
VALUES_RELPATH = ".claude/hos-sandbox.values"
VALUES_VERSION = "1"
GENERATOR_RELPATH = "scripts/framework/gen_sandbox_config.py"

KNOWN_ROLES = ("human", "worker", "overseer")
SUPPORTED_ROLES = ("human",)

# The single source of truth for the placeholder set. Flags, sidecar keys,
# echo-back order, and the sidecar-completeness check all derive from this
# tuple — adding an eighth placeholder means editing this plus its flag
# metadata, nothing else.
PLACEHOLDERS = (
    "ROLE",
    "PROJECT_ROOT",
    "HOS_ROOT",
    "CONFIG_DIR",
    "HOME",
    "HANDOFF_DIR",
    "CLAUDE_PROJECT_STATE",
)
REQUIRED_EXPLICIT = ("HANDOFF_DIR", "CLAUDE_PROJECT_STATE")
PATH_PLACEHOLDERS = tuple(name for name in PLACEHOLDERS if name != "ROLE")

PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")

BLOCKING_ISSUE = "#1146"

FLAG_NAMES = {
    "PROJECT_ROOT": "--project-root",
    "HOS_ROOT": "--hos-root",
    "CONFIG_DIR": "--config-dir",
    "HOME": "--home",
    "HANDOFF_DIR": "--handoff-dir",
    "CLAUDE_PROJECT_STATE": "--claude-project-state",
}

EXIT_OK = 0
EXIT_DIVERGENT = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED_ROLE = 3
EXIT_UNUSABLE_EXISTING = 4
EXIT_HARD_FAIL = 5
EXIT_NOT_ENROLLED = 6

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_META_PREFIX = "META_"
_VALUES_HEADER = (
    "# hos-sandbox.values — GENERATED by scripts/framework/gen_sandbox_config.py (#1221)\n"
    "# Machine-local, untracked, not a secret. Records the placeholder values used to\n"
    "# generate .claude/settings.local.json so `--check` can reproduce them.\n"
    "# NEVER sourced by a shell — parsed only. Do not hand-edit; regenerate instead."
)


# ── Exceptions (§2.5) ────────────────────────────────────────────────────────


class UsageError(Exception):
    """Bad/missing/conflicting flags, bad --clone-dir, or an invalid value. Exit 2."""


class UnsupportedRole(Exception):
    """--role worker or --role overseer — refused, naming #1146 (FR-5). Exit 3."""


class HardFailure(Exception):
    """Malformed template, a surviving placeholder, a corrupt/incomplete/wrong-
    version values sidecar, or any other unexpected internal error. Exit 5."""


@dataclass(frozen=True)
class Divergence:
    path: str
    kind: str  # MISSING, EXTRA, CHANGED, MISSING_KEY, EXTRA_KEY
    expected: Any = None
    actual: Any = None


# ── CLI (§3, AD-4, amended by ADDENDUM §4.3 — no --force) ──────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gen_sandbox_config.py",
        description=(
            "Generate or check a clone's .claude/settings.local.json from "
            "contract/sandbox-policy.template.json. Never overwrites an "
            "existing usable policy file."
        ),
    )
    parser.add_argument("--role", required=True, choices=KNOWN_ROLES)
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--project-root")
    parser.add_argument("--hos-root")
    parser.add_argument("--config-dir")
    parser.add_argument("--home")
    parser.add_argument("--handoff-dir")
    parser.add_argument("--claude-project-state")
    return parser


def gate_role(role: str) -> None:
    """AD-4's explicit gate: separates "unknown role" (argparse usage error,
    exit 2) from "known but unsupported role" (this gate, exit 3, #1146).

    Performs no I/O. Must be the first call in main() after argument parsing
    so that AC2's "neither writes any file" is structural, not incidental.
    """
    if role not in SUPPORTED_ROLES:
        raise UnsupportedRole(
            f"--role {role!r} is not yet supported. Per-role sandbox policy "
            f"generation for roles other than 'human' is blocked on {BLOCKING_ISSUE} "
            "(per-role rule content is that issue's work, not this generator's). "
            "No file was read or written."
        )


def validate_clone_dir(raw: str) -> Path:
    """§3.1: realpath-resolved; must exist; must be a directory; must contain
    a `.claude/` directory. This generator never creates `.claude/`."""
    resolved = Path(raw).resolve()
    if not resolved.exists():
        raise UsageError(f"--clone-dir {raw!r} does not exist (resolved to {resolved})")
    if not resolved.is_dir():
        raise UsageError(f"--clone-dir {raw!r} is not a directory (resolved to {resolved})")
    claude_dir = resolved / ".claude"
    if not claude_dir.is_dir():
        raise UsageError(
            f"--clone-dir {raw!r} has no .claude/ directory (resolved to {resolved}); "
            "this generator never creates .claude/ — the clone must already have one"
        )
    return resolved


_GLOB_METACHARS = ("*", "?", "[", "]")
# Printable ASCII plus the values this generator's own values are known to
# need (none — paths are plain). Anything below 0x20 (control chars, tab, the
# ESC that begins an ANSI escape sequence) or DEL (0x7f) is rejected outright:
# these values are echoed back verbatim to the operator by echo_values(),
# format_divergences(), and regenerate_command(), and a control/escape
# character in one could visually spoof that output (cf. #1114).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_path(raw: str, flag_name: str) -> str:
    """§3.3: applied identically to derived, env-sourced, flag-supplied, and
    sidecar-read values. A value is used literally: no ~ expansion, no
    environment expansion, no relative-path resolution."""
    if raw is None or "\n" in raw:
        raise UsageError(f"{flag_name} must not be empty or contain a newline")
    if raw in ("", "/"):
        raise UsageError(f"{flag_name} must be an absolute path, not {raw!r}")
    if not raw.startswith("/"):
        raise UsageError(f"{flag_name} must be an absolute path (got {raw!r})")
    if raw.startswith("//"):
        raise UsageError(
            f"{flag_name} must not begin with a double slash (got {raw!r}); the "
            "template's own double-slash spellings are built from a single-slash "
            "value plus a leading placeholder slash"
        )
    if PLACEHOLDER_RE.search(raw):
        raise UsageError(
            f"{flag_name} value {raw!r} itself contains a __PLACEHOLDER__ token — "
            "this is a usage error, not a template defect"
        )
    if any(ch in raw for ch in _GLOB_METACHARS):
        raise UsageError(
            f"{flag_name} value {raw!r} contains a glob metacharacter "
            f"({', '.join(_GLOB_METACHARS)!s}); these values are substituted "
            "directly into Claude Code permission-glob strings and a "
            "metacharacter would silently broaden the resulting glob's "
            "match scope"
        )
    if _CONTROL_CHAR_RE.search(raw):
        raise UsageError(
            f"{flag_name} value {raw!r} contains a non-printable or control "
            "character (including ANSI escapes); these values are echoed back "
            "to the operator and a control character could spoof that output"
        )
    return raw.rstrip("/")


def resolve_values(
    args: argparse.Namespace,
    env: dict[str, str],
    sidecar: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (values, sources) keyed by PLACEHOLDERS. Precedence: flag >
    sidecar (check mode only — caller supplies `sidecar`) > derived/env
    default > required-error. Pure w.r.t. the filesystem: the caller supplies
    `sidecar`; this function never touches disk."""
    clone_dir = Path(args.clone_dir)
    values: dict[str, str] = {"ROLE": args.role}
    sources: dict[str, str] = {"ROLE": "flag"}

    flag_values = {
        "PROJECT_ROOT": args.project_root,
        "HOS_ROOT": args.hos_root,
        "CONFIG_DIR": args.config_dir,
        "HOME": args.home,
        "HANDOFF_DIR": args.handoff_dir,
        "CLAUDE_PROJECT_STATE": args.claude_project_state,
    }
    home_env = env.get("HOME", "")

    def derived_default(name: str) -> tuple[str, str] | None:
        if name == "PROJECT_ROOT":
            return str(clone_dir), "derived"
        if name == "HOS_ROOT":
            return str(clone_dir.parent), "derived"
        if name == "HOME":
            return (home_env, "env") if home_env else None
        if name == "CONFIG_DIR":
            hos_config_dir = env.get("HOS_CONFIG_DIR", "")
            if hos_config_dir:
                return hos_config_dir, "env"
            return (f"{home_env}/.config/hos", "env") if home_env else None
        return None  # HANDOFF_DIR, CLAUDE_PROJECT_STATE: no default, ever (§0.1)

    for name in PATH_PLACEHOLDERS:
        flag_value = flag_values[name]
        if flag_value is not None:
            values[name] = normalize_path(flag_value, FLAG_NAMES[name])
            sources[name] = "flag"
            continue
        if sidecar is not None and name in sidecar:
            # Already normalized when the sidecar was parsed (§5.2 rule 9).
            values[name] = sidecar[name]
            sources[name] = "values-file"
            continue
        default = derived_default(name)
        if default is None:
            if name in REQUIRED_EXPLICIT:
                raise UsageError(
                    f"{FLAG_NAMES[name]} is required and has no default (§0.1 — "
                    "ask the operator for the correct production value; never guess)"
                )
            raise UsageError(
                f"{FLAG_NAMES[name]} could not be derived because HOME is unset or "
                f"empty in the environment — supply --home or {FLAG_NAMES[name]} explicitly"
            )
        value, source = default
        values[name] = normalize_path(value, FLAG_NAMES[name])
        sources[name] = source

    return values, sources


# ── The pure core (§2.1, §6 rows 6-9) ───────────────────────────────────────


def load_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HardFailure(f"cannot read template {path}: {exc}") from exc


def substitute(node: Any, values: dict[str, str]) -> Any:
    """Recursive walk of the parsed document. Replaces __NAME__ in every
    string, keys and values alike. Lists and dicts are rebuilt, not mutated
    in place."""
    if isinstance(node, str):
        for name, value in values.items():
            node = node.replace(f"__{name}__", value)
        return node
    if isinstance(node, dict):
        return {substitute(k, values): substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute(item, values) for item in node]
    return node


def find_surviving_placeholders(s: str) -> list[str]:
    """Run on the serialized output string (AD-3), so it catches placeholders
    anywhere — including inside the SessionStart hook command, which a
    per-key walk would miss."""
    return sorted(set(PLACEHOLDER_RE.findall(s)))


def render(template_text: str, values: dict[str, str]) -> str:
    """The pure core (AD-1). Takes no path parameter of any kind — there is
    no parameter through which the live file, the clone directory, or the
    values sidecar could enter."""
    try:
        doc = json.loads(template_text)
    except json.JSONDecodeError as exc:
        raise HardFailure(f"template is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise HardFailure("template's top level is not a JSON object")

    doc = substitute(doc, values)
    output = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    surviving = find_surviving_placeholders(output)
    if surviving:
        raise HardFailure(
            "template rendering left unsubstituted placeholder(s): "
            + ", ".join(surviving)
            + " — this is the #1114 failure class; no file was written"
        )
    return output


# ── Comparison (§6.4, §6.5) ─────────────────────────────────────────────────


def canonicalize(node: Any) -> Any:
    """Comparison-only normal form. Never used to produce output. Recursively
    sorts dict keys; converts a list whose elements are all strings into a
    sorted multiset representation (duplicates preserved); leaves lists
    containing objects positional."""
    if isinstance(node, dict):
        return {k: canonicalize(node[k]) for k in sorted(node)}
    if isinstance(node, list):
        if all(isinstance(item, str) for item in node):
            return sorted(node)
        return [canonicalize(item) for item in node]
    return node


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _compare_nodes(path: str, generated: Any, live: Any) -> list[Divergence]:
    findings: list[Divergence] = []

    if isinstance(generated, dict) and isinstance(live, dict):
        for key in sorted(set(generated) - set(live)):
            findings.append(Divergence(_join(path, key), "MISSING_KEY", generated[key], None))
        for key in sorted(set(live) - set(generated)):
            findings.append(Divergence(_join(path, key), "EXTRA_KEY", None, live[key]))
        for key in sorted(set(generated) & set(live)):
            findings.extend(_compare_nodes(_join(path, key), generated[key], live[key]))
        return findings

    if isinstance(generated, list) and isinstance(live, list):
        if all(isinstance(x, str) for x in generated) and all(isinstance(x, str) for x in live):
            for item in sorted(set(generated) - set(live)):
                findings.append(Divergence(path, "MISSING", item, None))
            for item in sorted(set(live) - set(generated)):
                findings.append(Divergence(path, "EXTRA", None, item))
            return findings
        # Arrays containing non-string elements (e.g. hooks.SessionStart) are
        # ordered JSON values and are compared positionally, canonicalizing
        # each element first so a nested string-array reorder does not itself
        # read as a divergence.
        for idx in range(max(len(generated), len(live))):
            item_path = f"{path}[{idx}]"
            if idx >= len(live):
                findings.append(Divergence(item_path, "MISSING", generated[idx], None))
            elif idx >= len(generated):
                findings.append(Divergence(item_path, "EXTRA", None, live[idx]))
            elif canonicalize(generated[idx]) != canonicalize(live[idx]):
                findings.append(Divergence(item_path, "CHANGED", generated[idx], live[idx]))
        return findings

    if canonicalize(generated) != canonicalize(live):
        findings.append(Divergence(path, "CHANGED", generated, live))
    return findings


def compare(generated_text: str, live_text: str) -> list[Divergence]:
    """The FR-8 rule-level comparison. Both sides are parsed with
    `json.loads`. Order-insensitive for string arrays; positional for arrays
    of objects."""
    return _compare_nodes("", json.loads(generated_text), json.loads(live_text))


def format_divergences(findings: list[Divergence], ctx: dict[str, Any]) -> str:
    """Grouped by JSON path, rule-level, never a raw byte diff. Always ends
    with the regenerate command."""
    lines = ["SANDBOX POLICY DIVERGENT"]
    lines.append(f"  clone:    {ctx['clone_dir']}")
    lines.append(f"  live:     {ctx['live_path']}")
    lines.append(f"  template: {TEMPLATE_RELPATH} ({ctx['provenance']})")
    lines.append("")

    if ctx.get("note"):
        lines.append(f"  {ctx['note']}")
        lines.append("")

    if ctx.get("surviving_placeholders"):
        names = ", ".join(ctx["surviving_placeholders"])
        lines.append(f"  live file contains unsubstituted placeholder(s): {names} — see #1114")
        lines.append("")

    grouped: dict[str, list[Divergence]] = {}
    for f in findings:
        grouped.setdefault(f.path, []).append(f)

    for path in sorted(grouped):
        entries = grouped[path]
        missing = [e for e in entries if e.kind in ("MISSING", "MISSING_KEY")]
        extra = [e for e in entries if e.kind in ("EXTRA", "EXTRA_KEY")]
        changed = [e for e in entries if e.kind == "CHANGED"]
        if missing:
            noun = "entry" if len(missing) == 1 else "entries"
            lines.append(f"  {path} — {len(missing)} expected {noun} missing from live:")
            for e in missing:
                lines.append(f"      - {e.expected}")
        if extra:
            lines.append(
                f"  {path} — {len(extra)} entr{'y' if len(extra) == 1 else 'ies'} "
                "in live that the template does not define:"
            )
            for e in extra:
                lines.append(f"      + {e.actual}")
        for e in changed:
            lines.append(f"  {path} — value differs: expected {e.expected!r}, live {e.actual!r}")
        lines.append("")

    lines.append("  Regenerate:")
    lines.append(f"    {ctx['regenerate_command']}")
    return "\n".join(lines) + "\n"


def format_advisory(findings: list[Divergence], live_path: Path) -> str:
    """§3.3: filters to MISSING / MISSING_KEY only — entries the generated
    document defines that the live file lacks. Never reports EXTRA/EXTRA_KEY/
    CHANGED: operator additions are legitimate by construction under the
    never-overwrite ruling."""
    missing = [f for f in findings if f.kind in ("MISSING", "MISSING_KEY")]
    lines = [
        "ADVISORY — informational only; nothing was changed.",
        f"  live file: {live_path}",
    ]
    if missing:
        lines.append("  entries the template defines that this file does not have:")
        for f in missing:
            lines.append(f"    {f.path}: {f.expected!r}")
    else:
        lines.append("  the existing file already carries every managed entry.")
    lines.append("  Run --check for the full, symmetric comparison.")
    return "\n".join(lines) + "\n"


# ── Values sidecar (§5, AD-5) ────────────────────────────────────────────────


def read_values_file(path: Path) -> dict[str, str] | None:
    """`None` iff the file does not exist. Otherwise the strict §5.2 parse;
    raises HardFailure on any corruption. Never read by generate mode."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HardFailure(f"cannot read values sidecar {path}: {exc}") from exc

    seen: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise HardFailure(f"{path}:{lineno}: no '=' in line {line!r}")
        key, _, value = line.partition("=")
        if not _KEY_RE.match(key):
            raise HardFailure(f"{path}:{lineno}: invalid key {key!r}")
        if key in seen:
            raise HardFailure(f"{path}:{lineno}: duplicate key {key!r}")
        seen[key] = value

    version = seen.get("META_VALUES_VERSION")
    if version != VALUES_VERSION:
        raise HardFailure(
            f"{path}: META_VALUES_VERSION={version!r}, expected {VALUES_VERSION!r} — regenerate"
        )

    result: dict[str, str] = {}
    for key, value in seen.items():
        if key.startswith(_META_PREFIX):
            continue
        if key not in PLACEHOLDERS:
            raise HardFailure(
                f"{path}: unrecognized key {key!r} (not a META_ key and not a known placeholder)"
            )
        result[key] = value

    missing = [name for name in PLACEHOLDERS if name not in result]
    if missing:
        raise HardFailure(
            f"{path}: values file is incomplete — missing {', '.join(missing)} — regenerate"
        )

    for name in PATH_PLACEHOLDERS:
        try:
            result[name] = normalize_path(result[name], f"values-file:{name}")
        except UsageError as exc:
            raise HardFailure(f"{path}: {exc}") from exc

    return result


def write_values_file(path: Path, values: dict[str, str], meta: dict[str, str]) -> None:
    """Write order: header comment block, then META_* keys sorted
    alphabetically, then the seven placeholder keys in PLACEHOLDERS order."""
    lines = [_VALUES_HEADER]
    for key in sorted(meta):
        lines.append(f"{key}={meta[key]}")
    for name in PLACEHOLDERS:
        lines.append(f"{name}={values[name]}")
    write_atomic(path, "\n".join(lines) + "\n")


def write_atomic(path: Path, content: str) -> None:
    """tempfile.mkstemp in the target's own directory (never /tmp — os.replace
    is not atomic across filesystems); flush + fsync; then os.replace."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-hos-sandbox-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)  # mkstemp already creates 0o600; explicit guard, not a widening
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Live-file classification (ADDENDUM-1221 §3.1, §4.4) ────────────────────


def classify_live(live: Path) -> tuple[str, str, str | None]:
    """Never raises for a bad file — a bad file is data, not an error. Reads
    `live` at most once."""
    if not live.exists():
        return "ABSENT", "", None
    if live.is_dir():
        return "UNUSABLE", "is a directory", None
    try:
        text = live.read_text(encoding="utf-8")
    except OSError as exc:
        return "UNUSABLE", f"not readable: {exc}", None
    if text == "":
        return "UNUSABLE", "zero-length", text
    if not text.strip():
        return "UNUSABLE", "whitespace-only", text
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        return "UNUSABLE", f"not valid JSON: {exc}", text
    if not isinstance(doc, dict):
        return "UNUSABLE", "top level is not a JSON object", text
    return "USABLE", "", text


# ── Provenance (AD-7) ────────────────────────────────────────────────────────


def template_provenance(repo_root: Path) -> tuple[str | None, bool | None]:
    """(blob_sha, dirty); (None, None) when git is unavailable. Never raises —
    git failures are non-fatal and must never change an exit code."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", f"HEAD:{TEMPLATE_RELPATH}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", TEMPLATE_RELPATH],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if sha.returncode != 0 or status.returncode != 0:
        return None, None
    blob = sha.stdout.strip()
    if not blob:
        return None, None
    return blob, bool(status.stdout.strip())


def _provenance_str(blob_sha: str | None, dirty: bool | None) -> str:
    if blob_sha is None:
        return "UNAVAILABLE (git: repo state could not be queried)"
    if dirty:
        return f"blob {blob_sha[:7]}, DIRTY — not the reviewed committed template"
    return f"blob {blob_sha[:7]}, clean"


# ── Reporting helpers (AD-4) ─────────────────────────────────────────────────


def echo_values(
    values: dict[str, str],
    sources: dict[str, str],
    role: str,
    clone_dir: Path,
    out: Any,
) -> None:
    """Mandatory, both modes, before any write. Silent substitution of a
    wrong path is the #1114 failure class this feature exists to end."""
    print(f"Resolved values (role={role}, clone={clone_dir}):", file=out)
    for name in PLACEHOLDERS:
        print(f"  {name:<22}= {values[name]:<40} [{sources[name]}]", file=out)


def regenerate_command(values: dict[str, str], clone_dir: Path) -> str:
    """The copy-pasteable command line that reproduces this generation. No
    `--force` tail — the flag does not exist (ADDENDUM §4.1)."""
    parts = [
        "python3 scripts/framework/gen_sandbox_config.py",
        f"--role {values['ROLE']}",
        f"--clone-dir {clone_dir}",
        f"--handoff-dir {values['HANDOFF_DIR']}",
        f"--claude-project-state {values['CLAUDE_PROJECT_STATE']}",
    ]
    return " \\\n      ".join(parts)


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _not_enrolled_message(role: str, clone_dir: Path) -> str:
    return (
        "SANDBOX POLICY: NOT ENROLLED — this clone's sandbox policy was never "
        f"generated; it is hand-maintained (no {VALUES_RELPATH}).\n"
        "  Enroll with:\n"
        f"    python3 scripts/framework/gen_sandbox_config.py --role {role} "
        f"--clone-dir {clone_dir} --handoff-dir <path> --claude-project-state <path>"
    )


# ── run_generate (ADDENDUM-1221 §3.5 — supersedes TD §6.6's run_generate) ──


def run_generate(
    args: argparse.Namespace,
    clone_dir: Path,
    values: dict[str, str],
    rendered: str,
    provenance: tuple[str | None, bool | None],
) -> int:
    live = clone_dir / LIVE_RELPATH
    # The only read of `live` in generate mode, and it happens after
    # `rendered` is already final (AD-1 restated, ADDENDUM §3.6).
    state, reason, live_text = classify_live(live)

    if state == "UNUSABLE":
        aside = f"{live}.bak-{_utc_compact()}"
        print(
            "SANDBOX POLICY: EXISTING FILE UNUSABLE — nothing written, nothing "
            "clobbered.\n"
            f"  path:   {live}\n"
            f"  reason: {reason}\n"
            "  The existing file was not modified.\n"
            "  Remedy — move it aside, then re-run:\n"
            f"    mv {live} {aside}\n"
            f"    {regenerate_command(values, clone_dir)}",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE_EXISTING

    if state == "USABLE":
        values_path = clone_dir / VALUES_RELPATH
        if values_path.exists():
            # Already enrolled — a true no-op, matching the never-overwrite
            # invariant for the sidecar too (ADDENDUM-1221 §3-follow-up,
            # 2026-08-16 ruling).
            print(
                "Sandbox policy: an existing settings.local.json already exists and "
                "was LEFT UNCHANGED — nothing was written by this run."
            )
        else:
            # Not yet enrolled — write only the values sidecar, adopting the
            # existing live file as this clone's baseline (2026-08-16 human
            # ruling: enrollment never writes or modifies settings.local.json).
            blob_sha, _dirty = provenance
            meta = {
                "META_VALUES_VERSION": VALUES_VERSION,
                "META_GENERATED_AT": _now_iso(),
                "META_GENERATOR": GENERATOR_RELPATH,
                "META_TEMPLATE_BLOB_SHA": blob_sha if blob_sha else "unavailable",
            }
            write_values_file(values_path, values, meta)
            print(
                "Sandbox policy: an existing settings.local.json already exists and "
                "was LEFT UNCHANGED — nothing was written to it by this run.\n"
                f"Enrolled this clone: wrote {values_path}, adopting the existing "
                "settings.local.json as its baseline. Future --check runs can now "
                "compare it against the template instead of reporting NOT ENROLLED."
            )
        try:
            findings = compare(rendered, live_text)  # type: ignore[arg-type]
            print(format_advisory(findings, live))
        except Exception as exc:
            # Narrow, deliberate carve-out (ADDENDUM §3.3): a bug in advisory
            # formatting must never convert a correct success into a hard
            # failure. Scoped to this block alone.
            print(f"advisory unavailable ({exc})")
        return EXIT_OK

    # ABSENT
    write_atomic(live, rendered)
    blob_sha, _dirty = provenance
    meta = {
        "META_VALUES_VERSION": VALUES_VERSION,
        "META_GENERATED_AT": _now_iso(),
        "META_GENERATOR": GENERATOR_RELPATH,
        "META_TEMPLATE_BLOB_SHA": blob_sha if blob_sha else "unavailable",
    }
    write_values_file(clone_dir / VALUES_RELPATH, values, meta)  # after the policy write
    print(
        f"Wrote {live}\n"
        f"Wrote {clone_dir / VALUES_RELPATH}\n"
        "Regenerate command:\n"
        f"    {regenerate_command(values, clone_dir)}\n"
        "Restart the session for the new policy to take effect."
    )
    return EXIT_OK


def run_check(
    args: argparse.Namespace,
    clone_dir: Path,
    values: dict[str, str],
    rendered: str,
    provenance: tuple[str | None, bool | None],
    sidecar_found: bool,
) -> int:
    if not sidecar_found:
        print(_not_enrolled_message(args.role, clone_dir))
        return EXIT_NOT_ENROLLED

    live = clone_dir / LIVE_RELPATH
    ctx: dict[str, Any] = {
        "clone_dir": str(clone_dir),
        "live_path": str(live),
        "provenance": _provenance_str(*provenance),
        "regenerate_command": regenerate_command(values, clone_dir),
    }

    if not live.exists():
        note = "policy file is missing entirely although this clone is enrolled"
        print(format_divergences([], {**ctx, "note": note}))
        return EXIT_DIVERGENT

    try:
        live_text = live.read_text(encoding="utf-8")
    except OSError as exc:
        print(format_divergences([], {**ctx, "note": f"live file unreadable: {exc}"}))
        return EXIT_DIVERGENT

    try:
        live_doc = json.loads(live_text)
    except json.JSONDecodeError as exc:
        note = f"live file is not valid JSON — the policy is not in effect as written ({exc})"
        print(format_divergences([], {**ctx, "note": note}))
        return EXIT_DIVERGENT

    if not isinstance(live_doc, dict):
        note = "live file's top level is not a JSON object — the policy is not in effect as written"
        print(format_divergences([], {**ctx, "note": note}))
        return EXIT_DIVERGENT

    surviving = find_surviving_placeholders(live_text)
    if surviving:
        ctx["surviving_placeholders"] = surviving

    findings = compare(rendered, live_text)
    if not findings and not surviving:
        print(f"Sandbox policy current ({TEMPLATE_RELPATH}).")
        return EXIT_OK

    print(format_divergences(findings, ctx))
    return EXIT_DIVERGENT


# ── main() — exact order of operations (§6.6, amended by ADDENDUM §3.5/§4) ──


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        # argparse's own usage errors already exit 2 — normalize to a return
        # value so main() is directly assertable in tests.
        return int(exc.code) if exc.code is not None else EXIT_USAGE

    try:
        gate_role(args.role)  # no I/O — must run before anything else (AC2)

        clone_dir = validate_clone_dir(args.clone_dir)
        args.clone_dir = str(clone_dir)

        provenance = template_provenance(REPO_ROOT)
        blob_sha, dirty = provenance
        print(f"template provenance: {TEMPLATE_RELPATH} ({_provenance_str(blob_sha, dirty)})")
        if dirty:
            print(
                "WARNING: the working-tree template has uncommitted changes — this "
                "run is generating from a template that has not been reviewed "
                "(ADR-1221 AD-7 / N2)."
            )

        sidecar: dict[str, str] | None = None
        if args.check:
            sidecar = read_values_file(clone_dir / VALUES_RELPATH)
            if sidecar is None:
                print(_not_enrolled_message(args.role, clone_dir))
                return EXIT_NOT_ENROLLED
            if sidecar["ROLE"] != args.role:
                raise HardFailure(
                    f"values sidecar was generated for role {sidecar['ROLE']!r}, "
                    f"but --role {args.role!r} was requested"
                )

        values, sources = resolve_values(args, dict(os.environ), sidecar)
        echo_values(values, sources, args.role, clone_dir, sys.stdout)

        template_text = load_template(TEMPLATE_PATH)
        rendered = render(template_text, values)
        # Nothing has been written at this point, in either mode (AD-3): no
        # cleanup path to get wrong, no window with a partial file.

        if args.check:
            return run_check(args, clone_dir, values, rendered, provenance, sidecar_found=True)
        return run_generate(args, clone_dir, values, rendered, provenance)

    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except UnsupportedRole as exc:
        print(f"unsupported role: {exc}", file=sys.stderr)
        return EXIT_UNSUPPORTED_ROLE
    except HardFailure as exc:
        print(f"hard failure: {exc}", file=sys.stderr)
        return EXIT_HARD_FAIL
    except Exception:
        # No path may leak a bare 1 — an unhandled exception is a broken
        # checker, never "divergent".
        traceback.print_exc(file=sys.stderr)
        return EXIT_HARD_FAIL


if __name__ == "__main__":
    sys.exit(main())
