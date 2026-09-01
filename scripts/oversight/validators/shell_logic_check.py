#!/usr/bin/env python3
"""
shell_logic_check.py — detect decision logic (branching/looping constructs)
embedded in shell scripts, where coverage/mutation tooling does not reach.

Shell scripts in this repo are meant to be launchers, not logic containers
(#1241): a branch or loop written in `.sh` is untested code sitting in front
of tested Python. This validator is a heuristic line scanner, like
portability_check.py — it does not parse shell syntax, so it can be fooled by
constructs split unusually across lines or embedded in strings/heredocs. That
is an accepted limitation; the goal is a directional signal for reviewers,
not a certified count.

Checks (only files whose path ends in .sh):
  1. Strip comments/blank lines (heuristic — no real shell parser).
  2. Track `if`/`elif`/`else`/`fi`/`case`/`esac`/`while`/`until`/`for`/`done`
     tokens (whole word, anywhere on a non-comment line — not just line-start,
     so single-line `if cond; then ...; fi` forms are matched too) with a
     small open/close stack, so nesting is resolved structurally rather than
     line-by-line. A construct is only eligible to be COUNTED at all if the
     keyword that opens it is the first word of its (stripped) line — that
     stays true to the original per-line heuristic for what "counts".
  3. Guard-clause exemption: an `if`/`elif` construct is exempt (does not
     count) when its own chain (the `if` and any `elif`s up to the matching
     `fi`, at the same nesting depth) has no `else` and no *further* `elif`
     after it — i.e. "run this one thing, or skip it" with no real second
     outcome. An `if`/`elif` construct counts only when something follows it
     in the chain (another `elif`, or an `else`) — a genuine fork where more
     than one arm does real work. `case`/`while`/`until` are unaffected by
     this exemption (see code-reviewer.md's testability criterion, #1241).
  4. Exempt the canonical fixed-shape flag-parsing loop used throughout this
     repo's bootstrap/*.sh entry points:
         while [[ $# -gt 0 ]]; do
             case "$1" in
                 ...
             esac
         done
     Only the `while [[ $# -gt 0 ]]` line and its closest-following `case
     "$1"`/`case $1` line are exempted — not the whole block, since other
     decision constructs can legitimately nest inside a flag-parsing loop and
     should still count.
  5. Hard exclusion: any file whose path (after normalizing backslashes to
     forward slashes) ends with `bootstrap/hos_bootstrap.sh` — the machine
     bootstrap that installs Python itself, exempt by policy (#1241).

Usage: python shell_logic_check.py file.sh [file2.sh ...]
"""

from __future__ import annotations

import pathlib as _hos_pl
import re

# self-bootstrap: ensure this file's dir (with schema.py) is importable
# regardless of caller cwd/PYTHONPATH (run_validators, run_panel, direct).
import sys
import sys as _hos_sys
from pathlib import Path

_hos_sys.path.insert(0, str(_hos_pl.Path(__file__).resolve().parent))
from schema import WEIGHTS, make_finding, make_result  # noqa: E402

DIMENSION = "shell_logic"

_HARD_EXEMPT_SUFFIX = "bootstrap/hos_bootstrap.sh"

_TOKEN_RE = re.compile(r"\b(if|elif|else|fi|case|esac|while|until|for|done)\b")
_FLAG_PARSE_WHILE_RE = re.compile(r"^while\s*\[\[\s*\$#\s*-gt\s*0\s*\]\]")
_FLAG_PARSE_CASE_RE = re.compile(r'^case\s+"?\$1"?\s+in\b')


def _is_hard_exempt(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(_HARD_EXEMPT_SUFFIX)


def _scan_file(path: str) -> tuple[int, int | None]:
    """Return (decision_construct_count, first_construct_lineno).

    Walks a small open/close stack over structural tokens so `if`/`elif`
    guard-clause exemption (no `else`, no further `elif` in the same chain)
    can be resolved correctly even across nested blocks, while `case`/
    `while`/`until` counting (and the fixed-flag-parsing exemption) works
    exactly as before. Malformed/unbalanced shell (a heuristic scanner can't
    fully verify) fails soft: unmatched closers are ignored, and any frame
    left open at EOF is simply never counted — undercounting is the safe
    direction for a signal-not-block validator.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, None

    stack: list[dict] = []
    decisions: list[int] = []
    # True right after an exempted flag-parse `while` — consumed by the very
    # next line-start decision-construct-opening token, whether or not it
    # turns out to be the matching `case "$1" in`.
    awaiting_flag_parse_case = False

    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for m in _TOKEN_RE.finditer(stripped):
            kw = m.group(1)
            line_start = m.start() == 0

            if kw == "if":
                stack.append({"type": "if", "chain": [], "has_else": False})
                if line_start:
                    stack[-1]["chain"].append(lineno)
                    awaiting_flag_parse_case = False
            elif kw == "elif":
                if stack and stack[-1]["type"] == "if" and line_start:
                    stack[-1]["chain"].append(lineno)
                    awaiting_flag_parse_case = False
            elif kw == "else":
                if stack and stack[-1]["type"] == "if":
                    stack[-1]["has_else"] = True
            elif kw == "fi":
                if stack and stack[-1]["type"] == "if":
                    frame = stack.pop()
                    chain = frame["chain"]
                    n = len(chain)
                    for idx, ln in enumerate(chain):
                        # Counts iff something follows it in the chain (a
                        # further elif, or an else) — a real fork. The last
                        # (or only) member of a chain with no else is a
                        # single-outcome guard clause: exempt.
                        if idx < n - 1 or frame["has_else"]:
                            decisions.append(ln)
            elif kw == "case":
                exempt = False
                if line_start:
                    if awaiting_flag_parse_case and _FLAG_PARSE_CASE_RE.match(stripped):
                        exempt = True
                    awaiting_flag_parse_case = False
                stack.append(
                    {"type": "case", "lineno": lineno, "line_start": line_start, "exempt": exempt}
                )
            elif kw == "esac":
                if stack and stack[-1]["type"] == "case":
                    frame = stack.pop()
                    if frame["line_start"] and not frame["exempt"]:
                        decisions.append(frame["lineno"])
            elif kw in ("while", "until"):
                exempt = False
                if line_start:
                    if kw == "while" and _FLAG_PARSE_WHILE_RE.match(stripped):
                        exempt = True
                        awaiting_flag_parse_case = True
                    else:
                        awaiting_flag_parse_case = False
                stack.append(
                    {"type": kw, "lineno": lineno, "line_start": line_start, "exempt": exempt}
                )
            elif kw == "for":
                stack.append({"type": "for"})
            elif kw == "done":
                if stack and stack[-1]["type"] in ("while", "until", "for"):
                    frame = stack.pop()
                    if (
                        frame["type"] in ("while", "until")
                        and frame.get("line_start")
                        and not frame.get("exempt")
                    ):
                        decisions.append(frame["lineno"])

    first_lineno = min(decisions) if decisions else None
    return len(decisions), first_lineno


# Score: step function on the exempted decision-construct count.
# 0 → clean thin launcher. 1-3 → some logic, flag for review. 4-7 → should
# likely be extracted. 8+ → this file is doing real program logic in shell.
def _score_for_count(count: int) -> float:
    if count == 0:
        return 0.0
    if count <= 3:
        return 0.3
    if count <= 7:
        return 0.6
    return 0.9


def main(files: list[str]) -> dict:
    per_file_counts: dict[str, int] = {}
    exempted_files: list[str] = []
    all_findings: list[dict] = []

    for f in files:
        if _is_hard_exempt(f):
            exempted_files.append(f)
            continue

        count, first_lineno = _scan_file(f)
        per_file_counts[f] = count
        if count > 0:
            severity = "medium" if count <= 3 else "high"
            all_findings.append(
                make_finding(
                    file=f,
                    line=first_lineno or 1,
                    message=(
                        f"{count} decision construct(s) in this file after "
                        "excluding fixed-flag-parsing — extraction to a "
                        "tested module recommended"
                    ),
                    severity=severity,
                )
            )

    total_count = sum(per_file_counts.values())
    score = _score_for_count(total_count)

    checklist = []
    if all_findings:
        checklist = [
            "Is this decision (conditional, retry, transform) better "
            "expressed in a language inside the test regime, with the shell "
            "reduced to a thin invoker?",
            "If this is genuinely fixed-shape flag parsing or a "
            "single-outcome guard clause, is that clear from the code, or "
            "should it be simplified to read that way?",
        ]

    return make_result(
        dimension=DIMENSION,
        score=score,
        raw_value={
            "decision_construct_count": total_count,
            "per_file_counts": per_file_counts,
            "exempted_files": exempted_files,
        },
        weight=WEIGHTS.get(DIMENSION, 0.05),
        evidence=all_findings,
        checklist_items=checklist,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('{"error": "no files provided"}')
        sys.exit(1)

    result = main(sys.argv[1:])
    import json

    print(json.dumps(result, indent=2))
