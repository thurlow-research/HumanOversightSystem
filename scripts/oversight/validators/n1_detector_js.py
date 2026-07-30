#!/usr/bin/env python3
"""
n1_detector_js.py — JS/TS N+1 analog via tree-sitter (S9, ADR-032 D8).

JS/TS/Astro sibling of n1_detector.py. There is no single dominant ORM in the
JS ecosystem to pattern-match on (unlike Django's `.objects.filter()`), so
per ADR-032 D8 this is a deliberately lighter heuristic than the Python
version: an `await` expression, or a call to `fetch(...)`, inside a loop body
(`for`/`for-in`/`for-of`/`while`/`do-while`, or an array-iteration callback —
`.forEach()`/`.map()`/`.filter()`) is flagged as a candidate sequential-call
site — the JS shape of the same "one DB/network round-trip per iteration"
problem. Emits the same `dimension="n1_queries"` string and
`weight=WEIGHTS["n1_queries"]` as the Python validator, but writes to a
distinct outfile (n1_queries_js.json, via the `n1_queries_js` NAME in
run_validators.sh).

Marked provisional in raw_value (ADR-032 D8): this dimension is additive
insurance on top of an already-met AC-1, lowest priority, and may degrade to
explicit N/A (error=) later if it proves too noisy in dogfooding.

Usage: python n1_detector_js.py file.ts [file2.tsx ...]
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

# Loop constructs whose `body` field runs once per iteration (mirrors the
# Python sibling only visiting node.body, not node.iter, at incremented depth).
_LOOP_STATEMENT_TYPES = frozenset(
    {
        "for_statement",
        "for_in_statement",  # covers both for-in and for-of
        "while_statement",
        "do_statement",
    }
)

# Array-iteration methods whose callback argument runs once per element —
# the JS analog of a `for` body (explicit set per ADR-032 D8, not exhaustive).
_ARRAY_ITERATION_METHODS = frozenset({"forEach", "map", "filter"})


def _astro_segments(text: str) -> list[tuple[int, bytes]]:
    """Extract the frontmatter fence + <script> blocks from an .astro SFC
    (mirrors function_metrics_js.py/D5) — the rest is template markup
    tree-sitter-typescript can't parse."""
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


def _record(findings: list[dict], node, line_offset: int, depth: int, kind: str) -> None:
    line = line_offset + node.start_point[0] + 1
    if any(f["line"] == line for f in findings):
        return
    findings.append({"line": line, "loop_depth": depth, "kind": kind})


def _walk(node, depth: int, line_offset: int, findings: list[dict]) -> None:
    node_type = node.type

    if node_type in _LOOP_STATEMENT_TYPES:
        body = node.child_by_field_name("body")
        for child in node.children:
            # tree-sitter's Python bindings return a fresh wrapper object per
            # access, so identity (`is`) never matches — compare by node id.
            _walk(child, depth + 1 if body is not None and child.id == body.id else depth,
                  line_offset, findings)
        return

    if node_type == "call_expression":
        func = node.child_by_field_name("function")
        prop_name = None
        if func is not None and func.type == "member_expression":
            prop = func.child_by_field_name("property")
            if prop is not None:
                prop_name = prop.text.decode("utf-8", "replace")
        if depth > 0 and func is not None and func.type == "identifier":
            if func.text.decode("utf-8", "replace") == "fetch":
                _record(findings, node, line_offset, depth, "fetch(...)")
        if prop_name in _ARRAY_ITERATION_METHODS:
            args = node.child_by_field_name("arguments")
            for child in node.children:
                _walk(child, depth + 1 if args is not None and child.id == args.id else depth,
                      line_offset, findings)
            return

    if node_type == "await_expression" and depth > 0:
        _record(findings, node, line_offset, depth, "await")

    for child in node.children:
        _walk(child, depth, line_offset, findings)


def _analyse_file(path: str) -> tuple[list[dict], bool]:
    """Return (findings, had_error) for one file across all its segments."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], True

    parser = _TSParser(_language_for(path))
    findings: list[dict] = []
    had_error = False
    for line_offset, source in _segments_for_file(path, text):
        if not source.strip():
            continue
        tree = parser.parse(source)
        if tree.root_node.has_error:
            had_error = True
        seg_findings: list[dict] = []
        _walk(tree.root_node, 0, line_offset, seg_findings)
        for f in seg_findings:
            f["file"] = path
        findings.extend(seg_findings)
    return findings, had_error


def analyse_files(file_paths: list[str]) -> dict:
    if not _TREE_SITTER_AVAILABLE:
        return make_result(
            "n1_queries",
            0.0,
            {"error": "tree-sitter not installed", "heuristic": "provisional"},
            weight=WEIGHTS["n1_queries"],
            error="tree-sitter not installed — run: pip install tree-sitter tree-sitter-typescript",
        )

    all_findings: list[dict] = []
    parse_errors: list[dict] = []

    for path in file_paths:
        findings, had_error = _analyse_file(path)
        all_findings.extend(findings)
        if had_error:
            parse_errors.append(
                {"file": path, "error": "tree-sitter reported syntax errors while parsing"}
            )

    # No N+1 candidate found anywhere AND at least one file was unparseable →
    # cannot tell "clean" from "hidden by a parse error". Exclude the
    # dimension via error= rather than reporting a clean 0.0 (mirrors #979 /
    # the Python sibling and function_metrics_js.py's identical gate).
    if not all_findings and parse_errors:
        detail = "; ".join(f"{Path(pe['file']).name}: {pe['error']}" for pe in parse_errors)
        return make_result(
            "n1_queries",
            0.0,
            {
                "candidate_count": 0,
                "locations": [],
                "parse_errors": parse_errors,
                "heuristic": "provisional",
            },
            weight=WEIGHTS["n1_queries"],
            error=f"all files unparseable — cannot assess N+1 risk: {detail}",
        )

    count = len(all_findings)
    score = normalize(count, 0, 8)

    evidence = [
        make_finding(
            f["file"],
            f["line"],
            f"potential N+1: {f['kind']} inside loop (depth={f['loop_depth']})",
            severity="medium",
        )
        for f in all_findings[:10]
    ]

    checklist = []
    for pe in parse_errors:
        checklist.append(
            f"⚠ {Path(pe['file']).name} could not be fully parsed by tree-sitter "
            f"({pe['error']}) — manually verify it contains no N+1-shaped loops"
        )
    if all_findings:
        checklist.append(
            "N+1 candidates found — verify each await/fetch inside a loop isn't "
            "issuing one sequential round-trip per iteration (consider "
            "Promise.all/batching)."
        )
        for f in all_findings[:3]:
            checklist.append(
                f"  {Path(f['file']).name}:{f['line']} — {f['kind']} inside loop: "
                "can this be batched outside the loop?"
            )

    return make_result(
        dimension="n1_queries",
        score=score,
        raw_value={
            "candidate_count": count,
            "locations": all_findings[:20],
            "parse_errors": parse_errors,
            "heuristic": "provisional",
        },
        weight=WEIGHTS["n1_queries"],
        evidence=evidence,
        checklist_items=checklist,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(_JS_EXTS) and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "n1_queries",
                    0.0,
                    {"error": "no JS/TS files", "heuristic": "provisional"},
                    weight=WEIGHTS["n1_queries"],
                    error="no input files",
                ),
                indent=2,
            )
        )
        return
    print(json.dumps(analyse_files(files), indent=2))


if __name__ == "__main__":
    main()
