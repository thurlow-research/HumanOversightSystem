#!/usr/bin/env python3
"""
complexity_metrics_js.py — cyclomatic complexity for JS/TS via tree-sitter.

JS/TS/JSX/TSX/Astro sibling of complexity_metrics.py (ADR-032 D4). Emits the
same `dimension="complexity"` string and `weight=WEIGHTS["cyclomatic"]` as the
Python validator, but writes to a distinct outfile (complexity_js.json, via
the `complexity_js` NAME in run_validators.sh) so the two never collide and
the Python-only byte-identical regression guard (AC-2) holds.

No maintainability-index equivalent is computed — tree-sitter gives no MI
signal, unlike radon. raw_value shape is dimension-specific; only
dimension/weight parity is required (AC-3).

Usage: python complexity_metrics_js.py file.ts [file2.tsx ...]
"""

from __future__ import annotations

import json
import pathlib as _hos_pl
import re

# self-bootstrap: ensure this file's dir (with schema.py) is importable
# regardless of caller cwd/PYTHONPATH (run_validators, run_panel, direct).
import sys
import sys as _hos_sys
from pathlib import Path

_hos_sys.path.insert(0, str(_hos_pl.Path(__file__).resolve().parent))
from schema import WEIGHTS, make_finding, make_result, normalize  # noqa: E402

# Thresholds for score normalization — shared with the Python sibling so
# JS and Python complexity scores stay comparable.
_CC_HIGH = 15  # cyclomatic complexity ≥15 → score 1.0

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".astro", ".mjs", ".cjs")

try:
    import tree_sitter_typescript as _ts_ts
    from tree_sitter import Language as _TSLanguage
    from tree_sitter import Parser as _TSParser

    _TS_LANGUAGE = _TSLanguage(_ts_ts.language_typescript())
    _TSX_LANGUAGE = _TSLanguage(_ts_ts.language_tsx())
    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False

# Function-like nodes scored as independent units (mirrors radon's
# per-function/method scoring — module-level code is not scored).
_FUNCTION_TYPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "generator_function_declaration",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)

# Decision-point node types that each add one independent execution path.
# switch_default is deliberately excluded (fallthrough, not a decision test).
_DECISION_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",  # covers both for-in and for-of
        "while_statement",
        "do_statement",
        "catch_clause",
        "ternary_expression",
        "switch_case",
    }
)

_SHORT_CIRCUIT_OPS = (b"&&", b"||", b"??")


def _astro_segments(text: str) -> list[tuple[int, bytes]]:
    """Extract the frontmatter fence + <script> blocks from an .astro SFC
    (D5) — the rest is template markup tree-sitter-typescript can't parse.
    Returns (line_offset, source_bytes) pairs so reported line numbers map
    back to the original file."""
    segments: list[tuple[int, bytes]] = []
    fm = re.match(r"^---\r?\n(.*?\r?\n)---", text, re.DOTALL)
    if fm:
        line_offset = text.count("\n", 0, fm.start(1))
        segments.append((line_offset, fm.group(1).encode("utf-8")))
    for sm in re.finditer(r"<script\b[^>]*>(.*?)</script>", text, re.DOTALL | re.IGNORECASE):
        line_offset = text.count("\n", 0, sm.start(1))
        segments.append((line_offset, sm.group(1).encode("utf-8")))
    return segments


def _segments_for_file(path: str, text: str) -> list[tuple[int, bytes]]:
    if path.endswith(".astro"):
        return _astro_segments(text)
    return [(0, text.encode("utf-8"))]


def _language_for(path: str):
    return _TSX_LANGUAGE if path.endswith((".tsx", ".jsx")) else _TS_LANGUAGE


def _count_decision_points(node) -> int:
    count = 0
    for child in node.children:
        if child.type in _FUNCTION_TYPES:
            # Nested functions are scored as their own entries, not folded
            # into the enclosing function's complexity.
            continue
        if child.type in _DECISION_TYPES:
            count += 1
        elif child.type == "binary_expression":
            op = child.child_by_field_name("operator")
            if op is not None and op.text in _SHORT_CIRCUIT_OPS:
                count += 1
        count += _count_decision_points(child)
    return count


def _function_name(node) -> str:
    name_field = node.child_by_field_name("name")
    if name_field is not None:
        return name_field.text.decode("utf-8", "replace")
    parent = node.parent
    if parent is not None:
        for field in ("name", "key"):
            f = parent.child_by_field_name(field)
            if f is not None:
                return f.text.decode("utf-8", "replace")
    return "<anonymous>"


def _collect_functions(node, line_offset: int, out: list[dict]) -> None:
    if node.type in _FUNCTION_TYPES:
        out.append(
            {
                "name": _function_name(node),
                "line": line_offset + node.start_point[0] + 1,
                "cyclomatic": 1 + _count_decision_points(node),
            }
        )
    for child in node.children:
        _collect_functions(child, line_offset, out)


def _analyse_file(path: str) -> tuple[list[dict], bool]:
    """Return (functions, had_error) for one file across all its segments."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], True

    parser = _TSParser(_language_for(path))
    functions: list[dict] = []
    had_error = False
    for line_offset, source in _segments_for_file(path, text):
        if not source.strip():
            continue
        tree = parser.parse(source)
        if tree.root_node.has_error:
            had_error = True
        seg_functions: list[dict] = []
        _collect_functions(tree.root_node, line_offset, seg_functions)
        for f in seg_functions:
            f["file"] = path
        functions.extend(seg_functions)
    return functions, had_error


def analyse_files(file_paths: list[str]) -> dict:
    if not _TREE_SITTER_AVAILABLE:
        return make_result(
            "complexity",
            0.0,
            {"error": "tree-sitter not installed"},
            weight=WEIGHTS["cyclomatic"],
            error="tree-sitter not installed — run: pip install tree-sitter tree-sitter-typescript",
        )

    all_functions: list[dict] = []
    parse_errors: list[dict] = []
    for path in file_paths:
        functions, had_error = _analyse_file(path)
        all_functions.extend(functions)
        if had_error:
            parse_errors.append(
                {"file": path, "error": "tree-sitter reported syntax errors while parsing"}
            )

    if not all_functions:
        # No function could be analysed. If every input file had parse
        # errors, EXCLUDE the dimension (error=) rather than reporting a
        # clean 0.0 — an unparseable file must not read as low-complexity,
        # matching the Python sibling's #979 fix.
        if parse_errors:
            detail = "; ".join(f"{Path(e['file']).name}: {e['error']}" for e in parse_errors)
            return make_result(
                "complexity",
                0.0,
                {"functions": [], "parse_errors": parse_errors},
                weight=WEIGHTS["cyclomatic"],
                error=f"all files unparseable — cannot assess complexity: {detail}",
            )
        return make_result("complexity", 0.0, {"functions": []}, weight=WEIGHTS["cyclomatic"])

    max_cc = max(f["cyclomatic"] for f in all_functions)
    mean_cc = sum(f["cyclomatic"] for f in all_functions) / len(all_functions)
    high_cc = [f for f in all_functions if f["cyclomatic"] >= 10]

    cc_score = normalize(max_cc, 1, _CC_HIGH)

    evidence = [
        make_finding(
            f["file"],
            f["line"],
            f"cyclomatic={f['cyclomatic']} — {f['name']}()",
            severity="high" if f["cyclomatic"] >= 10 else "medium",
        )
        for f in sorted(all_functions, key=lambda x: x["cyclomatic"], reverse=True)[:5]
    ]

    checklist = []
    for e in parse_errors:
        checklist.append(
            f"⚠ {Path(e['file']).name} could not be fully parsed by tree-sitter "
            f"({e['error']}) — manually verify it contains no high-complexity functions"
        )
    for f in sorted(all_functions, key=lambda x: x["cyclomatic"], reverse=True)[:2]:
        if f["cyclomatic"] >= 10:
            checklist.append(
                f"{f['name']}() — cyclomatic={f['cyclomatic']}: "
                "verify all independent paths have test coverage"
            )

    return make_result(
        dimension="complexity",
        score=cc_score,
        raw_value={
            "max_cyclomatic": max_cc,
            "mean_cyclomatic": round(mean_cc, 2),
            "high_complexity_functions": [f["name"] for f in high_cc],
            "parse_errors": parse_errors,
        },
        weight=WEIGHTS["cyclomatic"],
        evidence=evidence,
        checklist_items=checklist,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(_JS_EXTS) and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "complexity",
                    0.0,
                    {"error": "no JS/TS files"},
                    weight=WEIGHTS["cyclomatic"],
                    error="no input files",
                ),
                indent=2,
            )
        )
        return
    print(json.dumps(analyse_files(files), indent=2))


if __name__ == "__main__":
    main()
