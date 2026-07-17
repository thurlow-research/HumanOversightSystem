#!/usr/bin/env python3
"""
complexity_metrics.py — cyclomatic complexity via radon.

Cyclomatic (McCabe): measures testability — number of independent execution paths.
High cyclomatic + low test coverage = risky.

Cognitive complexity (Campbell 2018) — an independent readability signal — was
intended as a second dimension but is not currently computed: radon's `cc`
yields cyclomatic only. The emitted `complexity` dimension is scored from
cyclomatic alone (weight `WEIGHTS["cyclomatic"]`). See #1001.

Usage: python complexity_metrics.py file.py [file2.py ...]
"""

from __future__ import annotations

import json
import pathlib as _hos_pl
import subprocess

# self-bootstrap: ensure this file's dir (with schema.py) is importable
# regardless of caller cwd/PYTHONPATH (run_validators, run_panel, direct).
import sys
import sys as _hos_sys
from pathlib import Path

_hos_sys.path.insert(0, str(_hos_pl.Path(__file__).resolve().parent))
from schema import WEIGHTS, make_finding, make_result, normalize  # noqa: E402

# Thresholds for score normalization
_CC_HIGH = 15  # cyclomatic complexity ≥15 → score 1.0


def _run(cmd: list[str]) -> tuple[str, str, int]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def _radon_cc(files: list[str]) -> tuple[list[dict], list[dict]]:
    """Return (functions, parse_errors). radon emits {"bad.py": {"error": ...}}
    for files it cannot parse; that per-file value is a dict, not a list, so we
    record it as a parse error instead of iterating it as entries (which raised
    AttributeError on dict keys and crashed the whole validator). (#979)"""
    stdout, _, rc = _run(["radon", "cc", "-j", "-s"] + files)
    if rc != 0 or not stdout.strip():
        return [], []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return [], []
    functions: list[dict] = []
    errors: list[dict] = []
    for fpath, entries in data.items():
        if isinstance(entries, dict):
            # Per-file failure envelope: {"error": "invalid syntax ..."}.
            errors.append({"file": fpath, "error": entries.get("error", "unparseable")})
            continue
        if not isinstance(entries, list):
            errors.append(
                {"file": fpath, "error": f"unexpected radon output ({type(entries).__name__})"}
            )
            continue
        for entry in entries:
            functions.append(
                {
                    "file": fpath,
                    "name": entry.get("name", "?"),
                    "line": entry.get("lineno", 0),
                    "cyclomatic": entry.get("complexity", 0),
                }
            )
    return functions, errors


def _radon_mi(files: list[str]) -> dict[str, float]:
    """Maintainability index per file (0–100; lower = worse)."""
    stdout, _, rc = _run(["radon", "mi", "-j"] + files)
    if rc != 0 or not stdout.strip():
        return {}
    try:
        data = json.loads(stdout)
        return {k: v.get("mi", 100.0) if isinstance(v, dict) else v for k, v in data.items()}
    except (json.JSONDecodeError, AttributeError):
        return {}


def analyse_files(file_paths: list[str]) -> dict:
    try:
        subprocess.run(["radon", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return make_result(
            "complexity",
            0.0,
            {"error": "radon not installed"},
            weight=WEIGHTS["cyclomatic"],
            error="radon not installed — run: pip install radon",
        )

    cc_funcs, cc_errors = _radon_cc(file_paths)
    mi_map = _radon_mi(file_paths)

    if not cc_funcs:
        # No function could be analysed. If radon reported per-file parse errors
        # for every input, EXCLUDE the dimension (error=) rather than reporting a
        # clean 0.0 — an unparseable file must not read as low-complexity. (#979)
        if cc_errors:
            detail = "; ".join(f"{Path(e['file']).name}: {e['error']}" for e in cc_errors)
            return make_result(
                "complexity",
                0.0,
                {"functions": [], "parse_errors": cc_errors},
                weight=WEIGHTS["cyclomatic"],
                error=f"all files unparseable by radon — cannot assess complexity: {detail}",
            )
        return make_result("complexity", 0.0, {"functions": []}, weight=WEIGHTS["cyclomatic"])

    max_cc = max(f["cyclomatic"] for f in cc_funcs)
    mean_cc = sum(f["cyclomatic"] for f in cc_funcs) / len(cc_funcs)
    high_cc = [f for f in cc_funcs if f["cyclomatic"] >= 10]

    cc_score = normalize(max_cc, 1, _CC_HIGH)

    evidence = [
        make_finding(
            f["file"],
            f["line"],
            f"cyclomatic={f['cyclomatic']} — {f['name']}()",
            severity="high" if f["cyclomatic"] >= 10 else "medium",
        )
        for f in sorted(cc_funcs, key=lambda x: x["cyclomatic"], reverse=True)[:5]
    ]

    checklist = []
    # Some files parsed but others did not: keep the real signal, but flag the
    # unparseable files so a reviewer confirms they hide no complex functions.
    for e in cc_errors:
        checklist.append(
            f"⚠ {Path(e['file']).name} could not be parsed by radon ({e['error']}) — "
            "manually verify it contains no high-complexity functions"
        )
    for f in sorted(cc_funcs, key=lambda x: x["cyclomatic"], reverse=True)[:2]:
        if f["cyclomatic"] >= 10:
            checklist.append(
                f"{f['name']}() — cyclomatic={f['cyclomatic']}: "
                "verify all independent paths have test coverage"
            )

    min_mi = min(mi_map.values()) if mi_map else 100.0
    mi_concern = min_mi < 50

    return make_result(
        dimension="complexity",
        score=cc_score,
        raw_value={
            "max_cyclomatic": max_cc,
            "mean_cyclomatic": round(mean_cc, 2),
            "high_complexity_functions": [f["name"] for f in high_cc],
            "min_maintainability_index": round(min_mi, 1),
            "maintainability_concern": mi_concern,
            "parse_errors": cc_errors,
        },
        weight=WEIGHTS["cyclomatic"],
        evidence=evidence,
        checklist_items=checklist,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(".py") and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "complexity",
                    0.0,
                    {"error": "no Python files"},
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
