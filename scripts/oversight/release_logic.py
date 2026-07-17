#!/usr/bin/env python3
"""release_logic.py — semver bump, authored-notes gate, asset verification.

SPEC-335 / Issue #335. `scripts/framework/cut_release.sh` (the release-cut gate)
previously made three correctness-sensitive decisions in inline shell:

  1. SEMVER BUMP — split the latest tag on '.', increment a field, rebuild. This
     had a known coercion bug: a pre-release tag like "v0.3.0-rc1" set PA="0-rc1",
     and `PA=$((PA+1))` silently coerced it to 1 (#314 / spec §1).
  2. AUTHORED-NOTES GATE — `grep -cv '^[[:space:]]*$'` counted non-blank lines and
     required >= 5; the -cv flag combo is easy to misread and the 5 is a magic const.
  3. ASSET VERIFICATION — a list-membership test over `gh`-reported asset names
     done with a space-delimited `case " $got " in *" $n "*` pattern match.

All three are deterministic rule logic (#314 policy: prefer Python for logic, shell
for launch). This module extracts them into named, importable, unit-testable
functions so a bug in version arithmetic, threshold comparison, or set-membership is
caught without running the full shell script, `git`, or `gh`.

A later addition (R4, #999) keeps the same discipline: resolve_release_target
decides WHICH SHA a release tag may point at (the pushed remote tip, never a
local-only commit), as pure rule logic fed git-resolved SHAs from the shell.

PURITY (architect binding 6 / spec R5):
  - bump_version, verify_assets_present, and resolve_release_target perform NO
    subprocess, network, or file I/O — purely computational, unit-testable with
    synthetic inputs.
  - check_authored_notes reads ONE local file by path (its only I/O) and is kept as
    a separately named I/O function. It performs no subprocess or network call.
  - Python NEVER spawns `git` or `gh` (binding 4): the shell runs `gh` and passes
    asset names as argv to verify-assets.
Only the `__main__` CLI shim reads argv and writes stdout / sets exit codes.

SHELL INTEGRATION (architect binding 2): stdout capture, not a wrapper.
  - bump-version   prints the new version string to stdout.
  - check-notes    communicates via EXIT CODE (0 = pass, 1 = fail); no stdout.
  - verify-assets  prints missing asset names, one per line; empty output = all present.

NO BEHAVIOR CHANGE (spec §5) except the spec-sanctioned correction of the
pre-release coercion bug (binding 3: strip suffix, then increment).
"""

from __future__ import annotations

import argparse
import re
import sys

# Optional leading 'v', three integer fields, and an optional -<prerelease> suffix
# that is matched but DISCARDED (binding 3 — strip suffix before arithmetic).
# Anchored both ends so a corrupted tag fails the match.
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
_BUMP_TYPES = {"major", "minor", "patch"}
_DEFAULT_MIN_CONTENT_LINES = 5


# --------------------------------------------------------------------------- #
# R1 — semver bump                                                            #
# --------------------------------------------------------------------------- #
def bump_version(tag: str, bump_type: str) -> str:
    """Compute the next version string from a latest tag and a bump type.

    Returns "vMAJOR.MINOR.PATCH" with non-negative integer fields.

    - tag: most recent release tag ("v0.3.0", "v0.3.0-rc1", or "" if none). An
      empty/whitespace tag is treated as "v0.0.0" (spec R1).
    - bump_type: "major" | "minor" | "patch", case-insensitive.

    A pre-release suffix is STRIPPED before arithmetic (binding 3), so
    bump_version("v0.3.0-rc1", "patch") == "v0.3.1" — via a clean parse, NOT via the
    old bash coercion of "0-rc1"+1.

    Raises ValueError (the named exception, spec R1/AC4) if bump_type is not one of
    major/minor/patch, or if a non-empty tag cannot be parsed as vX.Y.Z[-suffix].
    Never silently coerces a malformed field. Pure: no git/gh/file I/O.
    """
    bt = bump_type.strip().lower()
    if bt not in _BUMP_TYPES:
        raise ValueError(f"invalid bump type: {bump_type!r}")

    if not tag or not tag.strip():
        tag = "v0.0.0"

    m = _SEMVER_RE.match(tag.strip())
    if not m:
        raise ValueError(f"unparseable tag: {tag!r}")

    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))

    if bt == "major":
        major, minor, patch = major + 1, 0, 0
    elif bt == "minor":
        minor, patch = minor + 1, 0
    else:  # patch
        patch = patch + 1

    return f"v{major}.{minor}.{patch}"


# --------------------------------------------------------------------------- #
# R2 — authored-notes gate (the ONLY logic function that does file I/O)       #
# --------------------------------------------------------------------------- #
def check_authored_notes(
    notes_path: str, min_lines: int = _DEFAULT_MIN_CONTENT_LINES
) -> bool:
    """Whether a release-notes file meets the authored-notes requirement.

    Returns True iff the file exists, is readable, and contains at least min_lines
    non-blank lines; False otherwise. A non-blank line is one with at least one
    non-whitespace character (matching `grep -cv '^[[:space:]]*$'`).

    A missing or empty file returns False (matching the shell `[[ ! -s "$path" ]]`
    miss-or-empty test). min_lines defaults to 5 (binding 5 / spec R2).

    This is the only logic function that touches the filesystem (binding 6) — named
    distinctly so its I/O is explicit. No subprocess, no network.
    """
    try:
        with open(notes_path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return False

    non_blank = sum(1 for line in content.splitlines() if line.strip())
    return non_blank >= min_lines


# --------------------------------------------------------------------------- #
# R3 — asset-presence verification                                           #
# --------------------------------------------------------------------------- #
def verify_assets_present(uploaded: list[str], expected: list[str]) -> list[str]:
    """Names from `expected` that are absent from `uploaded`.

    Returns the missing names in the ORDER they appear in `expected`. An empty list
    means all expected assets are present.

    Membership is EXACT string equality (binding 4 / spec R3) — not substring or
    pattern matching — resolving the space-delimited `case " $got " in *" $n "*`
    fragility. Pure: no file I/O, no subprocess, never spawns gh.
    """
    present = set(uploaded)
    return [name for name in expected if name not in present]


# --------------------------------------------------------------------------- #
# R4 — release-target SHA selection (#999)                                    #
# --------------------------------------------------------------------------- #
def resolve_release_target(
    local_head: str, remote_head: str, allow_branch: bool
) -> str:
    """The SHA a release tag should point at.

    A GitHub release tag can only point at a commit that EXISTS ON THE REMOTE;
    `gh release create --target <local-only-sha>` 422s (#999). `main` is protected
    (PRs only), so any local-ahead commit — e.g. the old step-3c stamp-cleanup
    commit — is unpushable by design. Therefore, for a normal on-branch cut we
    target the pushed REMOTE tip, which the in-sync precondition guarantees equals
    local HEAD — but taking it from the remote ref means a stray local commit can
    never poison the target.

    - allow_branch True: a deliberate off-branch / ahead cut (--allow-branch); the
      operator owns pushing their branch. Target local_head as-is (prior behavior
      for that explicit override). Raises ValueError if local_head is empty.
    - allow_branch False: target remote_head. Raises ValueError if remote_head is
      empty (no pushed tip to tag — push the release branch first).

    Pure: no git/gh/file I/O (binding 4/6). The shell resolves both SHAs with git
    and passes them in as argv.
    """
    lh = (local_head or "").strip()
    rh = (remote_head or "").strip()
    if allow_branch:
        if not lh:
            raise ValueError("no local HEAD to target")
        return lh
    if not rh:
        raise ValueError(
            "no origin tip to target — push the release branch to origin first"
        )
    return rh


# --------------------------------------------------------------------------- #
# CLI shim — the ONLY place that reads argv / writes stdout (binding 2).       #
# --------------------------------------------------------------------------- #
def _cmd_bump_version(args: argparse.Namespace) -> int:
    try:
        print(bump_version(args.tag, args.bump))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2  # usage/tooling error — matches shell exit 2 for bad bump/version
    return 0


def _cmd_check_notes(args: argparse.Namespace) -> int:
    # Exit-code transport (binding 2): 0 = pass, 1 = fail. No stdout. The shell
    # emits the user-facing error text and does its own exit 1.
    return 0 if check_authored_notes(args.path, args.min_lines) else 1


def _cmd_verify_assets(args: argparse.Namespace) -> int:
    # Print each missing name on its own line (binding 2). Empty output = all present.
    # Always exit 0: a non-empty missing list is a data result, not a CLI error — the
    # shell decides what to do with it.
    for name in verify_assets_present(args.uploaded, args.expected):
        print(name)
    return 0


def _cmd_resolve_target(args: argparse.Namespace) -> int:
    # Print the target SHA to stdout (binding 2). A ValueError is a real failure —
    # there is no pushable SHA to tag — so exit 2 and let the shell abort the cut.
    try:
        print(resolve_release_target(args.local, args.remote, args.allow_branch))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Release-cut decision logic: semver bump, authored-notes gate, "
        "asset verification (SPEC-335)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bump = sub.add_parser(
        "bump-version",
        help="Compute the next version from the latest tag. Prints vX.Y.Z to stdout.",
    )
    p_bump.add_argument("--tag", default="", help="latest release tag (or empty)")
    p_bump.add_argument(
        "--bump", required=True, help="major | minor | patch (case-insensitive)"
    )
    p_bump.set_defaults(func=_cmd_bump_version)

    p_notes = sub.add_parser(
        "check-notes",
        help="Authored-notes gate. Exit 0 = pass, 1 = fail. No stdout.",
    )
    p_notes.add_argument("--path", required=True, help="release-notes file path")
    p_notes.add_argument(
        "--min-lines",
        type=int,
        default=_DEFAULT_MIN_CONTENT_LINES,
        help="minimum non-blank lines required (default 5)",
    )
    p_notes.set_defaults(func=_cmd_check_notes)

    p_assets = sub.add_parser(
        "verify-assets",
        help="Print missing asset names, one per line. Empty output = all present.",
    )
    p_assets.add_argument(
        "--expected",
        nargs="+",
        required=True,
        help="asset names that must be present",
    )
    p_assets.add_argument(
        "--uploaded",
        nargs="*",
        default=[],
        help="asset names actually present (from gh)",
    )
    p_assets.set_defaults(func=_cmd_verify_assets)

    p_target = sub.add_parser(
        "resolve-target",
        help="Print the release-target SHA (the pushed remote tip, unless "
        "--allow-branch). Exit 2 if no pushable SHA exists.",
    )
    p_target.add_argument("--local", default="", help="local HEAD sha")
    p_target.add_argument(
        "--remote", default="", help="origin/<branch> tip sha (empty if none)"
    )
    p_target.add_argument(
        "--allow-branch",
        action="store_true",
        help="deliberate off-branch/ahead cut: target local HEAD instead",
    )
    p_target.set_defaults(func=_cmd_resolve_target)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
