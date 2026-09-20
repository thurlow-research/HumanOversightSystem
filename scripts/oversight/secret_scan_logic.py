#!/usr/bin/env python3
"""secret_scan_logic.py — finding-level suppression for the secret-scan gate (#1754).

`signoffs/validators/step{N}/summary.json` is a **required** committed artifact:
`overseer.md` step 3b fail-closes to HUMAN_REQUIRED without it, and checks its
`head_sha` against the artifact commit's parent. That `head_sha` is a 40-hex git
SHA, which detect-secrets reports as a `Hex High Entropy String` — so the gate
failed on an artifact the pipeline itself demands. It is not branch-specific:
`signoffs/validators/step1/summary.json` has been on `main` for months and trips
the identical gate. Every MEDIUM+ PR was blocked by it.

WHY THIS IS FINDING-LEVEL, NOT A WHOLE-FILE SKIP
------------------------------------------------
`secret_scan.sh` already skips `scripts/framework/validation-stamps/*.stamp`
whole-file for the same underlying reason (#1572, a 64-hex content fingerprint).
That is proportionate there: a stamp is a handful of short, fixed fields, so
skipping it forgoes almost no coverage.

A validator summary is not that. It runs to ~2,000 lines and embeds file paths
and code-evidence snippets lifted from the changeset — somewhere a real
credential could plausibly land. Skipping it whole-file would trade a blocked
pipeline for a blind spot in the one artifact that quotes source code.

So the suppression here is keyed on all three of:

  1. the file path matching a known artifact glob,
  2. the detector type being the one the known-benign shape provokes, and
  3. the flagged LINE actually being that shape — a `*_sha` field whose value is
     a bare 40-hex git SHA.

Every other detector (AWS keys, private keys, JWTs, base64 high entropy) still
runs against the artifact, and a 40-hex string anywhere other than a `*_sha`
field is still reported. Condition 3 is what makes this narrower than a
`(path, type)` filter: planting `"aws_key": "<40 hex>"` in the artifact does not
inherit the exemption.

VISIBILITY
----------
Suppression is never silent (#1754 AC-3, and the whole point of #1643/#1750:
a gate must not quietly decline to do its job). Every suppressed finding is
printed with its path, line and the rule that suppressed it, and the count is
repeated in the gate's summary line.

PURITY
------
`partition_findings` performs no I/O — the caller supplies a `line_reader`. Only
the CLI shim at the bottom reads stdin and the filesystem.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from typing import Callable, Iterable, NamedTuple

# A bare 40-hex git object name as the whole value of a `*_sha` JSON field.
# Anchored on the field name so a high-entropy value under any other key keeps
# its finding. `base_sha`/`head_sha` are the two the artifacts carry today; the
# pattern admits the family rather than enumerating it, because a new range
# field would otherwise silently re-block the pipeline.
_SHA_FIELD_RE = re.compile(r'"\w*_?sha"\s*:\s*"[0-9a-f]{40}"', re.IGNORECASE)


class Suppression(NamedTuple):
    """One narrowly-scoped exemption. All three conditions must hold."""

    path_glob: str
    finding_type: str
    line_predicate: Callable[[str], bool]
    reason: str


def _is_sha_field_line(line: str) -> bool:
    return bool(_SHA_FIELD_RE.search(line))


SUPPRESSIONS: tuple[Suppression, ...] = (
    Suppression(
        path_glob="signoffs/validators/*/summary.json",
        finding_type="Hex High Entropy String",
        line_predicate=_is_sha_field_line,
        reason=(
            "committed validator artifact: a git SHA in a `*_sha` field is an "
            "artifact fingerprint the overseer verifies (#555, #1754), not a secret"
        ),
    ),
)


class Finding(NamedTuple):
    path: str
    line_number: int
    type: str


class Suppressed(NamedTuple):
    finding: Finding
    reason: str


def _normalize(path: str) -> str:
    """Strip a leading `./` so the full-project scan's paths match the globs."""
    return path[2:] if path.startswith("./") else path


def _matching_rule(
    finding: Finding,
    line: str | None,
    rules: Iterable[Suppression],
) -> Suppression | None:
    path = _normalize(finding.path)
    for rule in rules:
        if not fnmatch.fnmatch(path, rule.path_glob):
            continue
        if finding.type != rule.finding_type:
            continue
        # Fail CLOSED on an unreadable line: if we cannot confirm the flagged
        # text is the benign shape, the finding stands. A suppression that
        # applies when its own evidence is missing is a fail-open.
        if line is None or not rule.line_predicate(line):
            continue
        return rule
    return None


def partition_findings(
    results: dict,
    line_reader: Callable[[str, int], str | None],
    rules: Iterable[Suppression] = SUPPRESSIONS,
) -> tuple[list[Finding], list[Suppressed]]:
    """Split detect-secrets `results` into (kept, suppressed).

    `results` is the `results` object of a detect-secrets scan: a mapping of
    path → list of finding dicts. `line_reader(path, line_number)` returns that
    source line, or None when it cannot be read.

    Pure apart from whatever `line_reader` does. A malformed finding entry is
    KEPT rather than dropped — the gate must not lose a finding it cannot parse.
    """
    kept: list[Finding] = []
    suppressed: list[Suppressed] = []

    for path, findings in sorted((results or {}).items()):
        for raw in findings or []:
            try:
                finding = Finding(
                    path=path,
                    line_number=int(raw["line_number"]),
                    type=str(raw["type"]),
                )
            except (KeyError, TypeError, ValueError):
                kept.append(Finding(path=path, line_number=-1, type=str(raw)[:80]))
                continue

            rule = _matching_rule(finding, line_reader(finding.path, finding.line_number), rules)
            if rule is None:
                kept.append(finding)
            else:
                suppressed.append(Suppressed(finding, rule.reason))

    return kept, suppressed


# --------------------------------------------------------------------------- #
# CLI shim — the only place that reads stdin or the filesystem.               #
# --------------------------------------------------------------------------- #


def _file_line_reader(path: str, line_number: int) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if i == line_number:
                    return line
    except OSError:
        return None
    return None


def _cmd_filter(_args: argparse.Namespace) -> int:
    """Read a detect-secrets baseline on stdin; report kept + suppressed.

    Exit 0 = no findings survive, 1 = at least one does, 2 = the baseline could
    not be parsed. Exit 2 matters: the shell previously swallowed a parse
    failure into `|| echo "0"`, i.e. an unreadable scan reported zero secrets
    and the gate passed. An unreadable scan is now a gate failure.
    """
    raw = sys.stdin.read()
    try:
        baseline = json.loads(raw)
        results = baseline["results"]
        if not isinstance(results, dict):
            raise TypeError(f"results is {type(results).__name__}, expected object")
    except (ValueError, KeyError, TypeError) as exc:
        print(
            f"GATE FAIL: could not parse detect-secrets output "
            f"({type(exc).__name__}: {exc}) — refusing to report a pass on a scan "
            "that cannot be read",
            file=sys.stderr,
        )
        return 2

    kept, suppressed = partition_findings(results, _file_line_reader)

    # Print suppressions FIRST and always — before any pass/fail line, so they
    # are visible on a passing run too, not only when something else fails.
    if suppressed:
        print(f"  {len(suppressed)} finding(s) suppressed by a known-benign-shape rule:")
        for item in suppressed:
            print(
                f"    {item.finding.path}:{item.finding.line_number} — "
                f"{item.finding.type} — {item.reason}"
            )

    if kept:
        print(f"GATE FAIL: {len(kept)} potential secret(s) detected:")
        for finding in kept:
            print(f"  {finding.path}:{finding.line_number} — {finding.type}")
        return 1

    tail = f" ({len(suppressed)} suppressed)" if suppressed else ""
    print(f"OK: no secrets detected{tail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Finding-level suppression for the secret-scan gate (#1754)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_filter = sub.add_parser(
        "filter",
        help="Read a detect-secrets baseline on stdin; print kept and suppressed "
        "findings. Exit 0=clean, 1=findings remain, 2=unparseable.",
    )
    p_filter.set_defaults(func=_cmd_filter)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
