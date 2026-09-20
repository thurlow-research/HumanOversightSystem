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

  1. the path matching `signoffs/validators/step<N>/summary.json` exactly
     (an anchored regex — an fnmatch glob's `*` would cross `/`),
  2. the detector type being the one the known-benign shape provokes, and
  3. the flagged LINE being nothing but the artifact's top-level `head_sha`
     property, and
  4. that value resolving to a real commit object in this repository.

Every other detector (AWS keys, private keys, JWTs, base64 high entropy) still
runs against the artifact, and a 40-hex string anywhere other than an
allowlisted SHA field is still reported. Condition 3 is what makes this narrower
than a `(path, type)` filter: planting `"aws_key": "<40 hex>"` in the artifact
does not inherit the exemption — and because detect-secrets reports per LINE
rather than per token, the line must contain the SHA property and nothing else,
or a leaked credential sharing that line would ride along on it.

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
import json
import re
import subprocess
import sys
from typing import Callable, Iterable, NamedTuple

# The invariant being exempted is narrow and specific: **the top-level
# `head_sha`/`base_sha` metadata field of a committed validator artifact**. Each
# tightening below came from this change's own cross-vendor second review
# (codex, CWE-693), and each closed a real bypass in the version before it:
#
#   1. A substring match for a `*_sha` field. detect-secrets reports findings
#      per LINE, not per token, so this could not tell WHICH value on the line
#      was flagged: `"head_sha": "<sha>", "api_token": "<40 hex>"` on one
#      physical line suppressed the leaked token.
#   2. An anchored whole-line match, still with a `\w*_?sha` family pattern.
#      A family pattern was chosen so a future range field would not re-block
#      the pipeline — a backwards trade. An unlisted field fails as a VISIBLE
#      gate failure someone then fixes in SUPPRESSIONS; a loose pattern is a
#      silent bypass.
#   3. An anchored whole-line match against an explicit field allowlist. Still
#      only a PROXY for the invariant: a 40-hex secret placed under a NESTED
#      key that happens to be named `head_sha` — anywhere in a ~2,000-line
#      artifact that embeds changeset-derived content — inherited the
#      exemption.
#
# So the check now binds to the invariant directly: parse the artifact, find
# which lines its TOP-LEVEL SHA fields occupy, and suppress only findings on
# exactly those lines, only when the value on the line is the one the parsed
# document carries. Nesting depth is computed from the raw text (string-aware),
# because the exemption is about a line number and `json.load` discards them.
#   4. An allowlist of `head_sha`, `base_sha`, `merge_base_sha`, with no check
#      that the value is a real git object. `head_sha` is the only field
#      `run_validators.sh` actually writes; the other two were speculative
#      future-proofing, i.e. two extra author-controlled hiding places bought
#      for a problem nobody has. And "the overseer verifies this field" was
#      doing the security work while THIS gate verified nothing — so the value
#      is now checked against real git state here, where it is relied on.
_SHA_FIELDS = ("head_sha",)
_SHA_LINE_RE = re.compile(
    r'^\s*"(?P<field>' + "|".join(_SHA_FIELDS) + r')"\s*:\s*"(?P<value>[0-9a-f]{40})"\s*,?\s*$'
)


def _line_depths(text: str) -> list[int]:
    """Depth of the JSON container each line OPENS in, ignoring braces in strings.

    Returns one entry per line; `1` marks a line sitting directly inside the
    document's root object. Written by hand because `json` discards positions
    and the exemption is fundamentally about a line number.
    """
    depths: list[int] = []
    depth = 0
    in_string = False
    escaped = False
    for line in text.splitlines():
        depths.append(depth)
        for ch in line:
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_string:
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string and ch in "{[":
                depth += 1
            elif not in_string and ch in "}]":
                depth -= 1
        escaped = False
    return depths


def top_level_sha_lines(text: str) -> dict[int, tuple[str, str]]:
    """Map 1-indexed line number → (field name, value) for top-level SHA fields.

    Empty (so: nothing suppressible) unless ALL of the following hold, because
    a suppression that applies when its own evidence is missing is a fail-open:

      * the text parses as JSON and its root is an object,
      * the line sits at depth 1 — directly inside that root object,
      * the line is nothing but one allowlisted SHA property, and
      * the value on the line is exactly what the parsed document holds for
        that key, so a duplicate key deeper in the file cannot stand in for it.

    Pure: takes text, returns a mapping.
    """
    try:
        document = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(document, dict):
        return {}

    depths = _line_depths(text)
    found: dict[int, tuple[str, str]] = {}
    for index, line in enumerate(text.splitlines()):
        if depths[index] != 1:
            continue
        match = _SHA_LINE_RE.match(line)
        if match is None:
            continue
        field = match.group("field")
        if document.get(field) != match.group("value"):
            continue
        found[index + 1] = (field, match.group("value"))
    return found


class Suppression(NamedTuple):
    """One narrowly-scoped exemption. Every condition must hold."""

    # An anchored regex, NOT an fnmatch glob: fnmatch's `*` matches `/` too, so
    # `signoffs/validators/*/summary.json` would also admit
    # `signoffs/validators/a/b/summary.json` — a wider surface than the one
    # artifact path this exempts (codex, CWE-693).
    path_re: "re.Pattern[str]"
    finding_type: str
    # text → {line number: (field, value)}. Receives the whole file because
    # the invariant is a document-structure property, not a line-local one.
    exempt_lines: Callable[[str], dict[int, tuple[str, str]]]
    reason: str


SUPPRESSIONS: tuple[Suppression, ...] = (
    Suppression(
        path_re=re.compile(r"^signoffs/validators/step[0-9]+/summary\.json$"),
        finding_type="Hex High Entropy String",
        exempt_lines=top_level_sha_lines,
        reason=(
            "committed validator artifact: the top-level `{field}` resolves to a "
            "real commit in this repository, so it is an artifact fingerprint "
            "(#555, #1754), not a secret"
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
    """Strip a leading `./` so the full-project scan's paths match the rules."""
    return path[2:] if path.startswith("./") else path


def _suppression_for(
    finding: Finding,
    text: str | None,
    rules: Iterable[Suppression],
    sha_verifier: Callable[[str], bool] | None,
) -> tuple[Suppression, str] | None:
    """Return (rule, field) when every condition holds, else None."""
    path = _normalize(finding.path)
    for rule in rules:
        if not rule.path_re.match(path):
            continue
        if finding.type != rule.finding_type:
            continue
        # Fail CLOSED on an unreadable file: without the evidence we cannot
        # confirm the flagged line is the benign shape, so the finding stands.
        if text is None:
            continue
        entry = rule.exempt_lines(text).get(finding.line_number)
        if entry is None:
            continue
        field, value = entry
        # The last proxy: "it is shaped like a git SHA" is not "it IS one".
        # Without this, an author could park a 40-hex credential in the one
        # top-level field the gate exempts, and the exemption's justification
        # ("the overseer verifies it") would be a claim this gate never checks.
        # No verifier configured is treated as unverifiable, not as verified.
        if sha_verifier is None or not sha_verifier(value):
            continue
        return rule, field
    return None


def partition_findings(
    results: dict,
    text_reader: Callable[[str], str | None],
    rules: Iterable[Suppression] = SUPPRESSIONS,
    sha_verifier: Callable[[str], bool] | None = None,
) -> tuple[list[Finding], list[Suppressed]]:
    """Split detect-secrets `results` into (kept, suppressed).

    `results` is the `results` object of a detect-secrets scan: a mapping of
    path → list of finding dicts. `text_reader(path)` returns that file's full
    text, or None when it cannot be read; it is called at most once per path.
    `sha_verifier(value)` says whether a candidate SHA resolves to a real commit
    in this repository; omitting it suppresses NOTHING, since an unverifiable
    value must not be exempted.

    Pure apart from whatever the two callables do. A malformed finding entry is
    KEPT rather than dropped — the gate must not lose a finding it cannot parse.
    """
    kept: list[Finding] = []
    suppressed: list[Suppressed] = []

    for path, findings in sorted((results or {}).items()):
        text: str | None = None
        text_read = False

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

            if not text_read:
                text = text_reader(path)
                text_read = True

            match = _suppression_for(finding, text, rules, sha_verifier)
            if match is None:
                kept.append(finding)
            else:
                rule, field = match
                suppressed.append(Suppressed(finding, rule.reason.format(field=field)))

    return kept, suppressed


# --------------------------------------------------------------------------- #
# CLI shim — the only place that reads stdin or the filesystem.               #
# --------------------------------------------------------------------------- #


def _file_text_reader(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _git_commit_exists(sha: str) -> bool:
    """True when `sha` names a commit object in this repository.

    A leaked credential is not going to be one. Fails closed on every error
    path — git missing, not a repository, timeout, or the object simply being
    absent (a shallow clone) — because "we could not check" must never read as
    "we checked and it was fine". The cost of that is a visible gate failure on
    a real artifact in a shallow checkout, which is the safe direction and is
    fixable by fetching.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return False
    try:
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


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

    kept, suppressed = partition_findings(
        results, _file_text_reader, sha_verifier=_git_commit_exists
    )

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
