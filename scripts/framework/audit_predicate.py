#!/usr/bin/env python3
"""audit_predicate.py — the single shared authority for "audit-only-and-well-formed"
(ADR-035 AD-2, TECHNICAL-DESIGN-035 §3).

This module is the *sole* decision of whether a PR's diff is audit-only and
well-formed. Its (planned) importers are the gate exception in
`require_overseer_approval.py` (Component C), the bot runtime in
`audit_approval_bot.py` (Component E), and the `pre_pr_stale_check.py` #880
exemption (Component H) — all three go through this one function; none
re-implements it. Adding a path to the audit surface happens only in
`audit_allowlist.txt` (a protected-surface, human-gated edit — AD-5).

Purity (matches `require_tier_ceiling.py` / `require_human_approval.py`
discipline): `classify_audit_diff` does no subprocess, network, `gh`, model
call, or filesystem write. Callers fetch the PR's file records (via `gh`, at
the head SHA, as DATA — AF-1) and read the allowlist file, then pass both in.

Fail-closed by design (AD-6, FR18): an unclassifiable diff, an absent patch,
an unknown format, or a parse failure never qualifies. There is no env var,
label, branch, or PR-body input that widens qualification — narrowing only.

CLI:
  python3 scripts/framework/audit_predicate.py classify \
      [--files <path|->] [--allowlist <path>] --base-ref <ref> [--protected-branch main]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional, TypedDict

ALLOWLIST_FILE = Path(__file__).with_name("audit_allowlist.txt")

# The exact glob dialect used by require_human_approval.load_globs /
# glob_to_regex (`dir/**` = the dir and everything under it, `*` = one path
# segment, an exact path matches literally). Loaded by file path (matches the
# sibling-module idiom already used in require_overseer_approval.py) rather
# than duplicated, so there is exactly one glob dialect in this repo (AD-2).
import importlib.util  # noqa: E402


def _load_sibling_module(name: str):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rha = _load_sibling_module("require_human_approval.py")
glob_to_regex = _rha.glob_to_regex


class FileRecord(TypedDict, total=False):
    """A documented subset of a `gh api .../pulls/{pr}/files` element (TD-VF-5).

    Unknown extra keys are ignored by every reader of this shape.
    """

    filename: str
    status: str
    additions: int
    deletions: int
    patch: Optional[str]


class AuditVerdict(NamedTuple):
    """`reason` is a short, machine-stable string naming the first
    disqualifying condition (or the qualifying summary) — written into the
    bot's decision record (FR19) and the gate log so the outcome is
    inspectable.
    """

    qualifies: bool
    reason: str


_ALLOWED_STATUSES = {"added", "modified"}

# A unified-diff hunk marker: `@@ -a,b +c,d @@` (optionally with trailing
# funcname/section text). Entering this state is what distinguishes a real
# hunk boundary from a content line that merely starts with '@@'.
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def extract_added_lines(patch: Optional[str]) -> list[str]:
    """Stateful unified-diff parse of a file's `patch` text (AD-17f fix).

    Replaces the naive "line.startswith('+++')" filter, which silently
    skipped any *content* line that itself begins with '+++' (e.g. an audit
    record embedding a diff snippet) by misreading it as a file header — the
    exact regression AD-17f fixes.

    Structure: (1) lines before the first `@@ ... @@` marker are the
    per-file header block (`diff --git`, `index`, `---`, `+++`) and are
    skipped structurally, not by prefix-matching; (2) a hunk-header line
    enters "in hunk" state; (3) inside a hunk, each line is classified by
    its single leading marker — `+` = added (strip exactly one leading `+`;
    a resulting `++foo`/`+++bar` is legitimate added content, not a header),
    `-` = deletion, ` ` = context. Added-line text is inert data parsed as
    strings, never evaluated (AF-1).
    """
    if not patch:
        return []
    added: list[str] = []
    in_hunk = False
    for line in patch.splitlines():
        if _HUNK_HEADER_RE.match(line):
            in_hunk = True
            continue
        if not in_hunk:
            # Pre-hunk file-header block (diff --git/index/---/+++) — inert.
            continue
        if line.startswith("+"):
            added.append(line[1:])
        # '-' (deletion) and ' ' (context) lines are not added content.
    return added


def _validate_jsonl(filename: str, added_lines: list[str]) -> tuple[bool, str]:
    """`.jsonl` append-log convention: each non-blank added line is exactly
    one JSON object."""
    for i, line in enumerate(added_lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return False, f"malformed-jsonl:{filename}:L{i}"
        if not isinstance(obj, dict):
            return False, f"malformed-jsonl:{filename}:L{i}"
    return True, ""


def _validate_audit_log_json(filename: str, added_lines: list[str]) -> tuple[bool, str]:
    """`audit/log/**` per-event write-once files (SPEC-888): the file's
    entire added content parses as one JSON object.

    Empty added content is treated as nothing-to-check here (trivially ok) —
    rejecting a zero-content change is rule 7's job (AD-17d), uniformly
    across formats, not this validator's.
    """
    content = "\n".join(added_lines).strip()
    if not content:
        return True, ""
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        return False, f"malformed-audit-log-json:{filename}"
    if not isinstance(obj, dict):
        return False, f"malformed-audit-log-json:{filename}"
    return True, ""


def _select_validator(filename: str):
    """The per-format validator registry (§3.3). A plain in-module table —
    no env var, label, branch, or PR-body input adds a format or relaxes a
    validator (AD-2 anti-tamper: no widening knob at all).

    `audit/log/**` is checked before the generic `*.jsonl` suffix rule: it is
    the more specific, directory-scoped write-once shape (SPEC-888), not the
    append-log line shape, even when the file itself ends in `.jsonl`.
    """
    if filename.startswith("audit/log/"):
        return _validate_audit_log_json
    if filename.endswith(".jsonl"):
        return _validate_jsonl
    return None


def classify_audit_diff(
    files: list[FileRecord],
    allowlist: list[str],
    base_ref: str,
    protected_branch: str = "main",
) -> AuditVerdict:
    """Returns `qualifies == True` only if every rule below holds, checked in
    this fixed order so `reason` is deterministic (§3.2, extended by §3.5 /
    AD-17). On the first failing rule, returns `qualifies == False` naming
    that rule and the offending path.

    Rule 2 (allowlist) is what makes AD-4 barrier 1 hold: any protected-
    surface or non-audit path fails rule 2, so a diff that touches code can
    never qualify — there is no separate "is it a protected surface" check.
    """
    # Rule 0 (AD-17a): the PR must target the protected branch. Fail-closed
    # on an unreadable/empty base ref (falls through to the same reason).
    if not base_ref or base_ref != protected_branch:
        return AuditVerdict(False, f"wrong-target-branch:{base_ref}")

    # Rule 1: an empty diff is not an audit PR.
    if not files:
        return AuditVerdict(False, "empty-diff")

    compiled = [(g, glob_to_regex(g)) for g in allowlist]

    def _matches_allowlist(filename: str) -> bool:
        return any(rx.match(filename) for _, rx in compiled)

    # Rule 2: every filename matches >=1 allowlist glob.
    for f in files:
        filename = f.get("filename", "")
        if not _matches_allowlist(filename):
            return AuditVerdict(False, f"non-allowlisted-path:{filename}")

    # Rule 3: every status is added/modified. status=="added" is the
    # first-creation case (AF-2/AD-9) and MUST qualify, not be rejected.
    for f in files:
        status = f.get("status", "")
        if status not in _ALLOWED_STATUSES:
            return AuditVerdict(False, f"disqualifying-status:{status}:{f.get('filename', '')}")

    # Rule 4: additions-only bound (FR7) — a rewrite of any existing line
    # shows a deletion in the unified diff; a pure append never does.
    for f in files:
        if f.get("deletions", 0) != 0:
            return AuditVerdict(False, f"deletion-present:{f.get('filename', '')}")

    # Rule 5: every file with additions > 0 must carry a non-None patch
    # (fail-closed on binary/oversized/absent hunk — FR8/FR18).
    for f in files:
        if f.get("additions", 0) > 0 and f.get("patch") is None:
            return AuditVerdict(False, f"patch-unavailable:{f.get('filename', '')}")

    # Rule 6: every added line is well-formed per the format registry.
    # Unregistered format on an allowlisted path -> fail-closed (AD-6).
    for f in files:
        filename = f.get("filename", "")
        validator = _select_validator(filename)
        if validator is None:
            return AuditVerdict(False, f"no-registered-validator:{filename}")
        added_lines = extract_added_lines(f.get("patch"))
        ok, reason = validator(filename, added_lines)
        if not ok:
            return AuditVerdict(False, reason)

    # Rule 7 (AD-17d): reject zero-content changes (file-mode-only, symlink
    # creation, type change) — a file with additions == 0 had nothing
    # actually checked by rules 5/6, yet would otherwise have qualified.
    for f in files:
        if f.get("additions", 0) <= 0:
            return AuditVerdict(False, f"no-content-addition:{f.get('filename', '')}")

    # Rule 8 (AD-17e): detect patch truncation — the GitHub files API
    # truncates `patch` for large files, so a mismatch between the parsed
    # added-line count and the authoritative `additions` field means the
    # unseen tail was never validated. Any mismatch fails closed.
    for f in files:
        filename = f.get("filename", "")
        parsed_count = len(extract_added_lines(f.get("patch")))
        if parsed_count != f.get("additions", 0):
            return AuditVerdict(False, f"patch-truncated:{filename}")

    return AuditVerdict(True, f"audit-only additions to {len(files)} allowlisted file(s)")


def load_allowlist(path: Path) -> list[str]:
    """Mirrors `require_human_approval.load_globs`: reads and strips the
    allowlist file (blank lines and `#`-comments ignored). This is the one
    filesystem read in this module outside the CLI itself."""
    if not path.is_file():
        print(f"audit_predicate: missing {path}", file=sys.stderr)
        sys.exit(2)
    globs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            globs.append(line)
    return globs


def _cli_classify(args: argparse.Namespace) -> int:
    if args.files and args.files != "-":
        text = Path(args.files).read_text()
    else:
        text = sys.stdin.read()
    try:
        files = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"audit_predicate: invalid JSON file records: {e}", file=sys.stderr)
        return 2
    if not isinstance(files, list):
        print("audit_predicate: --files must be a JSON array of file records", file=sys.stderr)
        return 2

    allowlist_path = Path(args.allowlist) if args.allowlist else ALLOWLIST_FILE
    allowlist = load_allowlist(allowlist_path)

    verdict = classify_audit_diff(files, allowlist, args.base_ref, args.protected_branch)
    print(json.dumps({"qualifies": verdict.qualifies, "reason": verdict.reason}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="audit_predicate.py")
    sub = ap.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify", help="classify a JSON array of PR file records")
    classify.add_argument(
        "--files", default="-", help="path to JSON file records, or '-' for stdin"
    )
    classify.add_argument(
        "--allowlist", help="path to the audit allowlist (default: audit_allowlist.txt)"
    )
    classify.add_argument("--base-ref", required=True, help="the PR's base.ref (inert data)")
    classify.add_argument("--protected-branch", default="main")

    args = ap.parse_args()

    if args.command == "classify":
        return _cli_classify(args)

    print(f"audit_predicate: unknown command {args.command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
