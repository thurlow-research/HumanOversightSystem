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

Neither is NON-suppression, which is the same requirement read the other way.
Condition 4 needs the artifact's commit to be in the local object store, and
`actions/checkout` fetches depth 1 unless told otherwise — so in an ordinary CI
checkout every real artifact SHA fails to resolve and the rule stops applying.
That is fail-closed and therefore safe, but on its own it is invisible: the
gate fails on exactly the required artifact it was changed to stop failing on,
and says only "Hex High Entropy String". `GitShaVerifier` separates "git says
this is not a commit" from "git could not be asked", and the CLI prints the
second with its remedy, so a suppression that stops working announces that it
has.

PURITY
------
`partition_findings` performs no I/O — the caller supplies a `line_reader`. Only
the CLI shim at the bottom reads stdin and the filesystem.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, NamedTuple


def _load_git_depth():
    """Load the sibling lib/git_depth.py by file path.

    This module runs as a plain script (sys.path[0] = its own dir), so a
    package import is not reliable here — same convention as
    suspension_manager.py's `_load_audit_log()`.
    """
    path = Path(__file__).resolve().parent / "lib" / "git_depth.py"
    spec = importlib.util.spec_from_file_location("hos_git_depth", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GIT_DEPTH = _load_git_depth()

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
        # Only open a file some rule could actually exempt. detect-secrets
        # output is TOOL OUTPUT, i.e. data, and a security gate must treat it
        # as hostile: a crafted or compromised baseline naming
        # `../../secrets.env` would otherwise have this gate open it while
        # deciding what to suppress (codex, CWE-22). Nothing is ever printed
        # from the contents, but a protected surface should not be a
        # file-read primitive at all. The candidate rules are also the only
        # ones consulted below, so this is a narrowing, not a second policy.
        candidates = [r for r in rules if r.path_re.match(_normalize(path))]

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

            if not candidates:
                kept.append(finding)
                continue

            if not text_read:
                text = text_reader(path)
                text_read = True

            match = _suppression_for(finding, text, candidates, sha_verifier)
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
    """Read a scanner-reported path, refusing anything outside the repository.

    `partition_findings` already declines to call this for a path no rule
    matches, and every rule's `path_re` is anchored to a repo-relative shape —
    so this containment check is the second of two independent barriers, not
    the only one. It is here because the argument arrives from tool output: an
    absolute path, a `..` traversal, or a symlink pointing out of the tree must
    be refused by the function that does the opening, not only by the caller
    that happens to filter today (codex, CWE-22).
    """
    root = Path.cwd().resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        return None
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    try:
        with open(resolved, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


class Undecided(NamedTuple):
    """One SHA the verifier could not rule on, and why."""

    sha: str
    cause: str


# Keyed by `Undecided.cause`. Each is a remedy for the OPERATOR, because an
# undecidable result is a defect in the environment, not in the artifact.
UNDECIDABLE_REMEDY: dict[str, str] = {
    "shallow": (
        "this clone is SHALLOW, so the artifact's commit object is simply not "
        "here and the exemption cannot be verified. `actions/checkout` fetches "
        "depth 1 unless told otherwise — set `fetch-depth: 0` on the checkout "
        "step (as every job in .github/workflows/oversight-gates.yml already "
        "does), or run `git fetch --unshallow` before the gate."
    ),
    "git-unavailable": (
        "git could not be run here, so no candidate SHA can be verified at all. "
        "Run the gate inside a git working tree, with git on PATH."
    ),
    "unknown-depth": (
        "git could not report whether this clone is shallow, so a genuinely "
        "missing commit cannot be told apart from a shallow checkout. Check "
        "`git rev-parse --is-shallow-repository` in this working tree."
    ),
}


class GitShaVerifier:
    """Does this 40-hex value name a commit in this repository?

    THREE outcomes, not two — collapsing the last two is the defect this class
    exists to prevent:

      verified     git resolved it to a commit object.
      absent       git is healthy, the clone is complete, and no such object
                   exists. The value is SHA-SHAPED but is not a SHA, which is
                   the bypass condition 4 was added to catch.
      undecidable  git could not be asked, or the clone is shallow, so the
                   object is legitimately not present.

    All three decline to suppress: the gate stays fail-closed, and this class
    never widens what is exempted. What changes is what the operator is told.
    `absent` is a finding about the ARTIFACT — someone parked a 40-hex value in
    the one exempted field and it is not a commit. `undecidable` is a finding
    about the ENVIRONMENT, and it carries a one-line remedy.

    That distinction is not cosmetic. `actions/checkout` defaults to
    `fetch-depth: 1`, so a shallow clone is the NORMAL state of a CI checkout,
    and in one every real artifact SHA reads as absent. With both outcomes
    printing the same nothing, #1754's fix appeared to work locally (full
    clone) and silently did not in CI — the gate failed on exactly the required
    artifact it was changed to stop failing on, giving no hint why. A gate that
    quietly stops doing its job is the failure mode #1643/#1750 are about; so
    is one that fails loudly for a reason it declines to name.

    Instances are callable, so this drops straight into `partition_findings`'
    `sha_verifier` slot and that function stays pure.
    """

    _SHA_RE = re.compile(r"[0-9a-f]{40}")

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        # Populated as a side effect of verification; read by the caller after
        # partitioning, so one diagnostic is printed per run rather than per
        # finding. Deduplicated: a ~2,000-line artifact can produce many
        # findings that all turn on the same SHA.
        self.undecidable: list[Undecided] = []
        self._shallow_checked = False
        self._shallow: bool | None = None

    def __call__(self, sha: str) -> bool:
        if not self._SHA_RE.fullmatch(sha):
            return False
        completed = self._git("cat-file", "-e", f"{sha}^{{commit}}")
        if completed is None:
            self._record(sha, "git-unavailable")
            return False
        if completed.returncode == 0:
            return True
        # Non-zero means "not an object HERE", which is not the same as "not an
        # object". Ask what kind of "here" this is before reporting it.
        shallow = self._is_shallow()
        if shallow is None:
            self._record(sha, "unknown-depth")
        elif shallow:
            self._record(sha, "shallow")
        return False

    def _record(self, sha: str, cause: str) -> None:
        entry = Undecided(sha, cause)
        if entry not in self.undecidable:
            self.undecidable.append(entry)

    def _is_shallow(self) -> bool | None:
        """True/False, or None when git would not answer. Asked at most once.

        Delegates to the shared detector (#1759 TD-D15) — one implementation
        of this tri-state, not two. This method keeps its own caching (the
        detector itself is stateless) and its own timeout.
        """
        if self._shallow_checked:
            return self._shallow
        self._shallow_checked = True
        self._shallow = _GIT_DEPTH.is_shallow_repository(timeout=self.timeout)
        return self._shallow

    def _git(self, *args: str) -> subprocess.CompletedProcess | None:
        """Run a git command; None when it could not be run at all."""
        try:
            return subprocess.run(["git", *args], capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError):
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

    verifier = GitShaVerifier()
    kept, suppressed = partition_findings(results, _file_text_reader, sha_verifier=verifier)

    # Print the environment diagnostic FIRST, ahead of the findings it explains.
    # Without it the gate fails on a required artifact naming only the artifact,
    # and the actual cause — a depth-1 CI checkout — is invisible.
    if verifier.undecidable:
        print(
            f"  NOTE: {len(verifier.undecidable)} candidate SHA(s) could not be "
            "verified against git, so the known-benign-shape rule declined to "
            "suppress. Any finding below on a validator artifact's `head_sha` is "
            "UNVERIFIED, not necessarily a secret:"
        )
        for cause in dict.fromkeys(item.cause for item in verifier.undecidable):
            print(f"    - {UNDECIDABLE_REMEDY[cause]}")

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
