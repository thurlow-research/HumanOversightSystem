#!/usr/bin/env python3
"""
function_metrics_js.py — function-level size/structure metrics for JS/TS via
tree-sitter (S5, ADR-032 D5).

JS/TS/JSX/TSX/Astro sibling of function_metrics.py. Emits the same
`dimension="function_metrics"` string and `weight=WEIGHTS["function_metrics"]`
as the Python validator, but writes to a distinct outfile (function_metrics_js.json,
via the `function_metrics_js` NAME in run_validators.sh) so the two never collide
and the Python-only byte-identical regression guard (AC-2) holds.

Metrics (same tree-sitter AST pass as complexity_metrics_js.py, D4):
  - lines of code (end row - start row + 1)
  - parameter count (excluding a TS `this: Type` parameter)
  - return path count (return + throw statements — throw is the JS analog
    of Python's raise)
  - max nesting depth (deepest if/for/while/do/try/switch nesting)

As in complexity_metrics_js.py, nested functions are scored as their own
independent entries — their returns/nesting/params are not folded into the
enclosing function's metrics.

For `.astro` files: only the frontmatter fence + <script> blocks are scored
(D5) — inline template expressions are not visible to tree-sitter-typescript
and are not scored, a documented limitation.

Usage: python function_metrics_js.py file.ts [file2.tsx ...]
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

# Thresholds shared with the Python sibling so JS and Python function-metrics
# scores stay comparable.
_LONG_FUNC_LINES = 60
_MANY_PARAMS = 6
_MANY_RETURNS = 5
_DEEP_NESTING = 4

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

# Function-like nodes scored as independent units (identical to
# complexity_metrics_js.py's set — module-level code is not scored).
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

# Statement types that introduce one level of nesting depth. Mirrors the
# Python sibling's (If, For, While, With, Try) set; switch_statement is added
# since JS has no direct `with`-equivalent decision but switch commonly nests
# logic the way Python's Try/If do.
_NESTING_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",  # covers both for-in and for-of
        "while_statement",
        "do_statement",
        "try_statement",
        "switch_statement",
    }
)

_RETURN_TYPES = frozenset({"return_statement", "throw_statement"})


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


def _count_params(node) -> int:
    params_node = node.child_by_field_name("parameters")
    if params_node is not None:
        named = params_node.named_children
        if named:
            first_pattern = named[0].child_by_field_name("pattern")
            if first_pattern is not None and first_pattern.type == "this":
                # TS `this: Type` parameter — not a real call-site argument
                # (mirrors the Python sibling excluding self/cls).
                named = named[1:]
        return len(named)
    # Unparenthesized single-param arrow function: `x => ...`.
    return 1 if node.child_by_field_name("parameter") is not None else 0


def _count_returns(node) -> int:
    count = 0
    for child in node.children:
        if child.type in _FUNCTION_TYPES:
            # Nested functions are scored as their own entries.
            continue
        if child.type in _RETURN_TYPES:
            count += 1
        count += _count_returns(child)
    return count


def _max_nesting_depth(node, depth: int = 0) -> int:
    max_d = depth
    for child in node.children:
        if child.type in _FUNCTION_TYPES:
            continue
        child_depth = depth + 1 if child.type in _NESTING_TYPES else depth
        max_d = max(max_d, _max_nesting_depth(child, child_depth))
    return max_d


def _collect_functions(node, line_offset: int, out: list[dict]) -> None:
    if node.type in _FUNCTION_TYPES:
        end_row = node.end_point[0]
        start_row = node.start_point[0]
        out.append(
            {
                "name": _function_name(node),
                "line": line_offset + start_row + 1,
                "lines": end_row - start_row + 1,
                "params": _count_params(node),
                "return_paths": _count_returns(node),
                "max_nesting_depth": _max_nesting_depth(node),
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
            "function_metrics",
            0.0,
            {"error": "tree-sitter not installed"},
            weight=WEIGHTS["function_metrics"],
            error="tree-sitter not installed — run: pip install tree-sitter tree-sitter-typescript",
        )

    all_funcs: list[dict] = []
    parse_errors: list[dict] = []
    for path in file_paths:
        functions, had_error = _analyse_file(path)
        all_funcs.extend(functions)
        if had_error:
            parse_errors.append(
                {"file": path, "error": "tree-sitter reported syntax errors while parsing"}
            )

    if not all_funcs:
        # No function could be analysed. If every input file had parse
        # errors, EXCLUDE the dimension (error=) rather than reporting a
        # clean 0.0 — an unparseable file must not read as low-risk,
        # matching the Python sibling's #979 fix and complexity_metrics_js.py.
        if parse_errors:
            detail = "; ".join(f"{Path(e['file']).name}: {e['error']}" for e in parse_errors)
            return make_result(
                "function_metrics",
                0.0,
                {"functions": [], "parse_errors": parse_errors},
                weight=WEIGHTS["function_metrics"],
                error=f"all files unparseable — cannot assess function metrics: {detail}",
            )
        return make_result(
            "function_metrics", 0.0, {"functions": []}, weight=WEIGHTS["function_metrics"]
        )

    long_funcs = [f for f in all_funcs if f["lines"] > _LONG_FUNC_LINES]
    complex_params = [f for f in all_funcs if f["params"] > _MANY_PARAMS]
    deep_funcs = [f for f in all_funcs if f["max_nesting_depth"] >= _DEEP_NESTING]
    many_returns = [f for f in all_funcs if f["return_paths"] > _MANY_RETURNS]

    concern_count = len(long_funcs) + len(complex_params) + len(deep_funcs) + len(many_returns)
    score = normalize(concern_count, 0, len(all_funcs) * 2)

    evidence = []
    for f in sorted(
        all_funcs,
        key=lambda x: x["lines"] + x["params"] * 5 + x["max_nesting_depth"] * 8,
        reverse=True,
    )[:5]:
        concerns = []
        if f["lines"] > _LONG_FUNC_LINES:
            concerns.append(f"lines={f['lines']}")
        if f["params"] > _MANY_PARAMS:
            concerns.append(f"params={f['params']}")
        if f["max_nesting_depth"] >= _DEEP_NESTING:
            concerns.append(f"nesting={f['max_nesting_depth']}")
        if concerns:
            evidence.append(
                make_finding(
                    f["file"], f["line"], f"{f['name']}(): {', '.join(concerns)}", severity="medium"
                )
            )

    checklist = []
    for e in parse_errors:
        checklist.append(
            f"⚠ {Path(e['file']).name} could not be fully parsed by tree-sitter "
            f"({e['error']}) — manually verify it contains no oversized/deeply-nested functions"
        )
    for f in long_funcs[:2]:
        checklist.append(
            f"{f['name']}() — {f['lines']} lines: can this be decomposed into smaller units?"
        )
    for f in complex_params[:2]:
        checklist.append(
            f"{f['name']}() — {f['params']} params: "
            "is there a missing abstraction (e.g. a config object)?"
        )

    return make_result(
        dimension="function_metrics",
        score=score,
        raw_value={
            "total_functions": len(all_funcs),
            "long_functions": len(long_funcs),
            "high_param_count": len(complex_params),
            "deeply_nested": len(deep_funcs),
            "many_return_paths": len(many_returns),
            "parse_errors": parse_errors,
        },
        weight=WEIGHTS["function_metrics"],
        evidence=evidence,
        checklist_items=checklist,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(_JS_EXTS) and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "function_metrics",
                    0.0,
                    {"error": "no JS/TS files"},
                    weight=WEIGHTS["function_metrics"],
                    error="no input files",
                ),
                indent=2,
            )
        )
        return
    print(json.dumps(analyse_files(files), indent=2))


if __name__ == "__main__":
    main()
