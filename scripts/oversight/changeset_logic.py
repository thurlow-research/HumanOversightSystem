#!/usr/bin/env python3
"""changeset_logic.py — the missing-path classifier (#1759, Ruling I / TD-D15).

`scripts/oversight/lib/changeset.sh` resolves a caller's selector (--diff,
--step, --staged, or explicit paths) to a candidate file list, then filters it
to paths that still exist on disk. This module answers *why* a candidate that
did NOT survive that filter is missing, so the shell can tell a legitimate
deletion from a typo instead of inferring it from the file count (INV-SELECTOR
forbids that inference — see the design's §3 TD-D14).

Four states:
  deleted      git tracks, or has tracked, this path.                -> drop
  fabricated   git has never heard of this path (explicit mode only). -> fatal
  shallow      history is truncated; cannot rule.                     -> degraded drop
  undecidable  git could not be asked, or a ref-mode candidate raced
               away between the diff and the existence check.         -> degraded drop

Resolution tiers, each tried only when the previous cannot answer:

  1. Ref tree lookup (a ref is known: --diff/--step/--staged) — ONE batched
     `git cat-file --batch-check` call, depth-independent (correct even in a
     shallow clone). A path not in the ref's tree is `undecidable`, not
     `fabricated`: a diff/step/staged candidate came from git's own diff, so a
     vanished one is a racing working tree, never a typo (only a human or a
     script can mistype a path; `git diff` cannot). `fabricated` exists solely
     for `explicit` mode, tiers 2-4 below.
  2. Index (git ls-files, one batched call) — catches a staged-then-removed
     addition (`git add f && rm f`) that history alone would misclassify.
  3. History (git log --name-only, one batched call) — the ever-tracked
     subset of the remaining candidates.
  4. Depth check (git_depth.is_shallow_repository, cached, at most once) —
     for paths still unresolved after tier 3: shallow=true -> `shallow`;
     unknown -> `undecidable`; a complete clone that never tracked the path
     -> `fabricated`.

See docs/v0.7.0/TECHNICAL-DESIGN-1759-run-gates-diff-parsing.md §3 TD-D15 and
§13 Detail 2 (the batching/cost argument) and Detail 3 (the index-tier case).

CLI:
  printf 'a.py\\nb.py\\n' | changeset_logic.py classify [--ref REF]

  Reads missing paths on stdin, one per line. Prints '<state>\\t<path>' per
  path, in input order, to stdout. Exit 0 = classified, none fabricated.
  Exit 1 = at least one fabricated. Exit 2 = the module itself could not run
  (the shell then treats every path as undecidable — degraded, never fatal:
  a broken classifier must not become a new way to fail a green PR).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_git_depth():
    """Load the sibling lib/git_depth.py by file path.

    This module runs as a plain script (sys.path[0] = its own dir), so a
    package import is not reliable here — same convention as
    suspension_manager.py's `_load_audit_log()` and secret_scan_logic.py's
    `_load_git_depth()`.
    """
    path = Path(__file__).resolve().parent / "lib" / "git_depth.py"
    spec = importlib.util.spec_from_file_location("hos_git_depth", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GIT_DEPTH = _load_git_depth()

_GIT_TIMEOUT = 30


def _git(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess | None:
    """Run a git command; None when it could not be run at all."""
    try:
        return subprocess.run(
            ["git", *args],
            input=input_text.encode("utf-8") if input_text is not None else None,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _classify_via_ref(paths: list[str], ref: str) -> dict[str, str]:
    """Tier 1 only — one batched `git cat-file --batch-check` call.

    A path present in the ref's tree was deleted since; one absent from the
    ref's tree is a race (the candidate list came from git's own diff), not a
    typo — see the module docstring.
    """
    tokens = [f"{ref}:{p}" for p in paths]
    completed = _git("cat-file", "--batch-check", input_text="\n".join(tokens) + "\n")
    if completed is None or completed.returncode != 0:
        return {p: "undecidable" for p in paths}

    lines = completed.stdout.decode("utf-8", "replace").splitlines()
    states: dict[str, str] = {}
    for path, token, line in zip(paths, tokens, lines):
        states[path] = "undecidable" if line == f"{token} missing" else "deleted"
    # Defensive: git printed fewer lines than tokens (should not happen).
    for path in paths:
        states.setdefault(path, "undecidable")
    return states


def _classify_via_history(paths: list[str]) -> dict[str, str]:
    """Tiers 2-4 — explicit mode only (no ref known)."""
    states: dict[str, str] = {}
    remaining = list(paths)

    # Tier 2 — index (one batched call).
    completed = _git("ls-files", "--", *remaining)
    if completed is not None and completed.returncode == 0:
        tracked = set(completed.stdout.decode("utf-8", "replace").splitlines())
        for path in remaining:
            if path in tracked:
                states[path] = "deleted"
        remaining = [p for p in remaining if p not in states]

    if not remaining:
        return states

    # Tier 3 — history (one batched call).
    completed = _git("log", "--format=", "--name-only", "--", *remaining)
    if completed is not None and completed.returncode == 0:
        ever_tracked = set(completed.stdout.decode("utf-8", "replace").splitlines())
        for path in remaining:
            if path in ever_tracked:
                states[path] = "deleted"
        remaining = [p for p in remaining if p not in states]

    if not remaining:
        return states

    # Tier 4 — depth check (cached, at most once regardless of path count).
    shallow = _GIT_DEPTH.is_shallow_repository()
    for path in remaining:
        if shallow is True:
            states[path] = "shallow"
        elif shallow is None:
            states[path] = "undecidable"
        else:
            states[path] = "fabricated"
    return states


def classify_paths(paths: list[str], ref: str | None) -> dict[str, str]:
    """One state per path. `ref` is `HOS_CHANGESET_REF` when known (diff/step/
    staged); `None` for explicit mode."""
    if not paths:
        return {}
    if ref is not None:
        return _classify_via_ref(paths, ref)
    return _classify_via_history(paths)


def _cmd_classify(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    paths = [line for line in raw.splitlines() if line]
    if not paths:
        return 0

    try:
        states = classify_paths(paths, args.ref)
    except Exception as exc:  # noqa: BLE001 - a module failure is a defined exit code
        print(f"changeset_logic: could not classify missing paths: {exc}", file=sys.stderr)
        return 2

    fabricated = False
    for path in paths:
        state = states.get(path, "undecidable")
        if state == "fabricated":
            fabricated = True
        print(f"{state}\t{path}")

    return 1 if fabricated else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The missing-path classifier for run_gates.sh's changeset "
        "resolution (#1759, Ruling I)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_classify = sub.add_parser(
        "classify",
        help="Read missing paths on stdin (one per line); print '<state>\\t<path>' "
        "per path. Exit 0=classified, 1=at least one fabricated, 2=could not run.",
    )
    p_classify.add_argument(
        "--ref",
        default=None,
        help="The diff/step/staged ref, when known (tier 1, ref-tree lookup). "
        "Omit for explicit mode.",
    )
    p_classify.set_defaults(func=_cmd_classify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
