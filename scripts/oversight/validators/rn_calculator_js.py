#!/usr/bin/env python3
"""
rn_calculator_js.py — Dai et al. (2024) Risk Number for JS/TS via tree-sitter.

JS/TS/JSX/TSX/Astro sibling of rn_calculator.py (S8, ADR-032 D7). Emits the
same `dimension="risk_number"` string and `weight=WEIGHTS["risk_number"]` as
the Python validator, but writes to a distinct outfile (risk_number_js.json,
via the `risk_number_js` NAME in run_validators.sh) so the two never collide
and the Python-only byte-identical regression guard (AC-2) holds.

**Calibration is PROVISIONAL** — the nesting-increment table below is the
same Dai et al. regression fit used by rn_calculator.py, derived entirely
from Python bug data. No JS-specific calibration data exists yet for this
project. `raw_value["calibration"]` is always set to
"provisional-js-reuses-python-weights" so this flag is visible to the
risk-assessor's inspection brief without inspecting source. Do not treat the
resulting score as equally validated to the Python dimension until a JS
recalibration lands (ADR-032 D7 follow-up).

Depth-tracking limitation (documented, not a bug): unlike the Python AST
visitor — which recurses only into a flow-break node's *body*, keeping
condition/test expressions at the enclosing depth — this walker recurses
into all of a flow-break node's children uniformly (consistent with the
existing decision-point/nesting-depth walkers in complexity_metrics_js.py
and function_metrics_js.py). This slightly over-counts nesting depth for
conditions containing nested control flow (rare) and treats each `else if`
link and trailing `else` as one extra nesting level rather than a sibling —
an intentional simplification for a provisional heuristic.

Usage:
  python rn_calculator_js.py file.ts [file2.tsx ...]
  python rn_calculator_js.py --files file1.ts file2.tsx
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
from schema import (  # noqa: E402
    WEIGHTS,
    make_finding,
    make_result,
    normalize,
    score_to_tier,
)

_CALIBRATION = "provisional-js-reuses-python-weights"

# Nesting increment table — identical to rn_calculator.py's Dai et al. fit
# (duplicated, not imported, matching the existing complexity_metrics_js.py /
# function_metrics_js.py sibling convention of full independence from the
# Python validator).
_NESTING_TABLE: dict[int, float] = {
    0: 0.0,
    1: 1.0,
    2: 3.0,
    3: 4.8,
    4: 7.1,
}
_NESTING_W: float = 2.01
_NESTING_B: float = -1.05

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


def nesting_increment(depth: int) -> float:
    """Return calibrated nesting increment for the given nesting depth."""
    if depth in _NESTING_TABLE:
        return _NESTING_TABLE[depth]
    return round(max(0.0, _NESTING_W * depth + _NESTING_B), 1)


# Function-like nodes scored as independent units (mirrors complexity_metrics_js.py
# and function_metrics_js.py — module-level code is not scored).
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

# Node types that are flow-break structures (contribute judgment + nesting
# increments) — the JS analog of rn_calculator.py's _FLOW_BREAK.
_FLOW_BREAK = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",  # covers both for-in and for-of
        "while_statement",
        "do_statement",
        "catch_clause",
        "switch_statement",
    }
)

# Node types that carry a `condition` field worth scanning for logical
# operators (mirrors rn_calculator.py's _count_logical_ops: only If/While
# have a `.test` in Python — for/catch/switch have no boolean condition).
_CONDITION_FIELD = {
    "if_statement": "condition",
    "while_statement": "condition",
    "do_statement": "condition",
}

_SHORT_CIRCUIT_OPS = (b"&&", b"||", b"??")


def _count_logical_ops(node) -> int:
    """Count &&/||/?? operators and ternaries in a flow-break node's condition."""
    field = _CONDITION_FIELD.get(node.type)
    if field is None:
        return 0
    condition = node.child_by_field_name(field)
    if condition is None:
        return 0

    count = 0
    stack = [condition]
    while stack:
        n = stack.pop()
        if n.type == "binary_expression":
            op = n.child_by_field_name("operator")
            if op is not None and op.text in _SHORT_CIRCUIT_OPS:
                count += 1
        elif n.type == "ternary_expression":
            count += 1
        stack.extend(n.children)
    return count


class _FunctionRNVisitor:
    """
    Walks a single function's body (tree-sitter node), tracking nesting depth
    and computing per-statement Risk Numbers. Does NOT recurse into nested
    function nodes (those are analysed separately as top-level functions).
    """

    def __init__(self, filename: str, func_name: str, start_line: int):
        self.filename = filename
        self.func_name = func_name
        self.start_line = start_line
        self.depth = 0
        self.total_rn: float = 0.0
        self.statements: list[dict] = []

    def _record(self, node, rn: float) -> None:
        self.total_rn += rn
        self.statements.append(
            {
                "line": node.start_point[0] + 1,
                "type": node.type,
                "rn": rn,
                "nesting_depth": self.depth,
            }
        )

    def visit(self, node) -> None:
        for child in node.children:
            if child.type in _FUNCTION_TYPES:
                # Nested function — skip; it is analysed as its own entry.
                continue
            if child.type in _FLOW_BREAK:
                self._visit_flow_break(child)
            else:
                self.visit(child)

    def _visit_flow_break(self, node) -> None:
        j_inc = 1 + _count_logical_ops(node)
        n_inc = nesting_increment(self.depth)
        self._record(node, n_inc + j_inc)
        self.depth += 1
        self.visit(node)
        self.depth -= 1


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


def _collect_functions(node, line_offset: int, filename: str, out: list[dict]) -> None:
    if node.type in _FUNCTION_TYPES:
        name = _function_name(node)
        start_line = line_offset + node.start_point[0] + 1
        visitor = _FunctionRNVisitor(filename, name, start_line)
        visitor.visit(node)
        out.append(
            {
                "name": name,
                "file": filename,
                "start_line": start_line,
                "risk_number": round(visitor.total_rn, 1),
                "statements": visitor.statements,
            }
        )
    for child in node.children:
        _collect_functions(child, line_offset, filename, out)


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
        _collect_functions(tree.root_node, line_offset, path, functions)
    return functions, had_error


def _checklist_items(func: dict) -> list[str]:
    """Produce Dai CID-style checklist items for the highest-RN statements."""
    items = []
    top = sorted(func["statements"], key=lambda s: s["rn"], reverse=True)[:3]
    for s in top:
        if s["rn"] == 0:
            continue
        node_type = s["type"]
        line = s["line"]
        fn = func["name"]
        if node_type == "if_statement":
            items.append(f"{fn}:{line} — can this condition be both true and false as expected?")
            items.append(f"{fn}:{line} — are all branches (including implicit else) handled?")
        elif node_type in ("for_statement", "for_in_statement"):
            items.append(f"{fn}:{line} — is the loop bound correct and termination guaranteed?")
            items.append(
                f"{fn}:{line} — is anything mutated inside the loop that affects the iterator?"
            )
        elif node_type in ("while_statement", "do_statement"):
            items.append(
                f"{fn}:{line} — can the loop condition become false? Is the loop variable updated?"
            )
        elif node_type == "catch_clause":
            items.append(
                f"{fn}:{line} — is the exception caught at the right granularity "
                f"(not a bare/blanket catch)?"
            )
        elif node_type == "switch_statement":
            items.append(f"{fn}:{line} — are all cases handled, including a default/fallthrough?")
    return items


# Score thresholds — identical to rn_calculator.py so JS and Python RN scores
# stay comparable (the "reuses Python weights" half of the D7 provisional flag).
_SCORE_HIGH_THRESHOLD = 20.0


def analyse_files(file_paths: list[str]) -> dict:
    if not _TREE_SITTER_AVAILABLE:
        return make_result(
            "risk_number",
            0.0,
            {"error": "tree-sitter not installed", "calibration": _CALIBRATION},
            weight=WEIGHTS["risk_number"],
            error="tree-sitter not installed — run: pip install tree-sitter tree-sitter-typescript",
        )

    all_functions: list[dict] = []
    parse_errors: list[str] = []
    for path in file_paths:
        functions, had_error = _analyse_file(path)
        all_functions.extend(functions)
        if had_error:
            parse_errors.append(f"{path}: tree-sitter reported syntax errors while parsing")

    if not all_functions:
        return make_result(
            "risk_number",
            0.0,
            {"functions": [], "parse_errors": parse_errors, "calibration": _CALIBRATION},
            weight=WEIGHTS["risk_number"],
            error=("; ".join(parse_errors) if parse_errors else None),
        )

    max_rn = max(f["risk_number"] for f in all_functions)
    mean_rn = sum(f["risk_number"] for f in all_functions) / len(all_functions)
    high_risk = [f for f in all_functions if f["risk_number"] >= 8.0]

    score = normalize(max_rn, 0, _SCORE_HIGH_THRESHOLD)

    evidence = [
        make_finding(
            f["file"],
            f["start_line"],
            f"RN={f['risk_number']} — {f['name']}()",
            severity="high" if f["risk_number"] >= 8 else "medium",
        )
        for f in sorted(all_functions, key=lambda x: x["risk_number"], reverse=True)[:5]
    ]

    checklist: list[str] = []
    for pe in parse_errors:
        checklist.append(
            f"⚠ {pe} — could not be parsed; "
            "manually verify it contains no high-risk (high-RN) functions"
        )
    for f in sorted(all_functions, key=lambda x: x["risk_number"], reverse=True)[:3]:
        checklist.extend(_checklist_items(f))

    return make_result(
        dimension="risk_number",
        score=score,
        raw_value={
            "max_rn": max_rn,
            "mean_rn": round(mean_rn, 2),
            "high_risk_functions": [f["name"] for f in high_risk],
            "function_count": len(all_functions),
            "parse_errors": parse_errors,
            "calibration": _CALIBRATION,
        },
        weight=WEIGHTS["risk_number"],
        evidence=evidence,
        checklist_items=checklist,
        findings=[
            {
                "function": f["name"],
                "file": f["file"],
                "line": f["start_line"],
                "risk_number": f["risk_number"],
                "top_statements": sorted(f["statements"], key=lambda s: s["rn"], reverse=True)[:3],
            }
            for f in sorted(all_functions, key=lambda x: x["risk_number"], reverse=True)
        ],
    )


# Task classes for which a structurally-LOW change is floored to MEDIUM (#373)
# — identical policy to rn_calculator.py, duplicated per sibling convention.
_FLOOR_TASK_CLASSES = ("refactor", "chore")
_KNOWN_TASK_CLASSES = ("feat", "fix", "refactor", "chore")


def apply_task_class_floor(
    result: dict, task_class: str | None, source: str | None = None
) -> dict:
    """
    Apply the SPEC-373 task-class risk-tier floor to a validator result.

    Identical logic to rn_calculator.py's apply_task_class_floor — see that
    docstring for the full contract. Duplicated, not imported, per the
    existing complexity_metrics_js.py / function_metrics_js.py convention.
    """
    raw = result.get("raw_value")
    if not isinstance(raw, dict):
        raw = {} if raw is None else {"_prev_raw_value": raw}
        result["raw_value"] = raw

    if task_class not in _KNOWN_TASK_CLASSES:
        raw["task_class"] = None
        raw["task_class_source"] = None
        raw["floor_applied"] = False
        raw["pre_floor_tier"] = None
        raw["post_floor_tier"] = None
        return result

    local_tier = score_to_tier(result.get("score", 0.0))
    if task_class in _FLOOR_TASK_CLASSES and local_tier == "LOW":
        floor_applied = True
        post_floor_tier = "MEDIUM"
    else:
        floor_applied = False
        post_floor_tier = local_tier

    raw["task_class"] = task_class
    raw["task_class_source"] = source
    raw["floor_applied"] = floor_applied
    raw["pre_floor_tier"] = local_tier
    raw["post_floor_tier"] = post_floor_tier

    if floor_applied:
        result["tier_floor"] = "MEDIUM"

    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task-class", dest="task_class", default=None)
    parser.add_argument("--task-class-source", dest="task_class_source", default=None)
    parser.add_argument("--files", dest="files_flag", nargs="*", default=None)
    parser.add_argument("positional", nargs="*", default=[])
    parsed, _unknown = parser.parse_known_args(sys.argv[1:])

    if parsed.files_flag is not None:
        files = list(parsed.files_flag)
    else:
        files = list(parsed.positional)

    files = [f for f in files if f.endswith(_JS_EXTS) and Path(f).exists()]
    if not files:
        result = make_result(
            "risk_number",
            0.0,
            {"error": "no JS/TS files", "calibration": _CALIBRATION},
            weight=WEIGHTS["risk_number"],
            error="no input files",
        )
    else:
        result = analyse_files(files)

    result = apply_task_class_floor(
        result, parsed.task_class, source=parsed.task_class_source
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
