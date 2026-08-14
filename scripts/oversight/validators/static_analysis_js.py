#!/usr/bin/env python3
"""
static_analysis_js.py — semgrep JS/TS security findings as a risk score.

JS/TS/JSX/TSX/Astro sibling of static_analysis.py (ADR-032 D6). Unlike the
Python validator — where bandit is the primary tool and semgrep is only an
optional additive signal — semgrep IS the primary (and only) static-analysis
tool for JS/TS, so its unavailability EXCLUDES this dimension the same way a
missing bandit does for Python (#917 precedent). Emits the same
`dimension="static_analysis"` string and `weight=WEIGHTS["static_analysis"]`
as the Python sibling, but writes to a distinct outfile
(static_analysis_js.json, via the `static_analysis_js` NAME in
run_validators.sh) so the two never collide and the Python-only
byte-identical regression guard (AC-2) holds.

Runs against a ruleset vendored in this repo (semgrep_rules/js_ts_security.yaml)
rather than a registry config (`p/...`) so scores are reproducible offline and
never drift when an upstream registry ruleset changes underfoot (ADR-032 D6:
"Pin semgrep + a vendored ruleset version — rule drift changes scores").

semgrep's ERROR severity is scored like bandit's HIGH (3x weight, raises a
discrete tier_floor); WARNING is scored like bandit's MEDIUM. The vendored
ruleset has no INFO-severity rules, so every finding here clears the
"MEDIUM+" bar (ADR-032 D6).

Usage: python static_analysis_js.py file.ts [file2.tsx ...]
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

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".astro", ".mjs", ".cjs")

_RULESET = _hos_pl.Path(__file__).resolve().parent / "semgrep_rules" / "js_ts_security.yaml"

# An ERROR-severity semgrep finding weighs this many WARNING findings toward
# the numeric score — mirrors the Python sibling's HIGH:MEDIUM 3:1 ratio (#997).
_ERROR_FINDING_WEIGHT = 3


def _run_semgrep(files: list[str]) -> tuple[list[dict], str | None]:
    """
    Run semgrep against the vendored ruleset and return (results, error).

    error is non-None when semgrep could not produce a usable result — the
    tool is missing, the vendored ruleset is missing, its output was
    unparseable, it exited with a failure code, or it reported partial-scan
    errors in its own output. Callers must propagate this as a validator-level
    ``error=`` so the aggregator EXCLUDES the highest-weight security
    dimension rather than scoring a clean 0.0 (fail-open), matching the Python
    sibling's #917 fix and its #1369 returncode/errors-array follow-up.
    """
    if not _RULESET.exists():
        return [], f"vendored semgrep ruleset missing: {_RULESET}"
    try:
        result = subprocess.run(
            ["semgrep", "--config", str(_RULESET), "--json", "--quiet"] + files,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "semgrep not installed — run: pip install semgrep"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "semgrep output unparseable — scan failed, cannot assess security risk"
    # semgrep exit codes: 0 = clean scan, 1 = scan ran and found findings (also
    # success). Anything else is a scan failure — the returncode was never
    # checked, so a broken scan that still emitted a valid-but-empty JSON
    # document read as "ran clean" (#1369).
    if result.returncode not in (0, 1):
        return [], f"semgrep exited {result.returncode} — scan failed, cannot assess security risk"
    scan_errors = data.get("errors", [])
    if scan_errors:
        return [], (
            f"semgrep reported {len(scan_errors)} scan error(s) — partial scan, "
            "cannot assess security risk"
        )
    return data.get("results", []), None


def _severity(r: dict) -> str:
    return r.get("extra", {}).get("severity", "INFO").upper()


def _message(r: dict) -> str:
    return r.get("extra", {}).get("message", "")


def analyse_files(file_paths: list[str]) -> dict:
    results, error = _run_semgrep(file_paths)
    if error is not None:
        return make_result(
            dimension="static_analysis",
            score=0.0,
            raw_value={"error": error},
            weight=WEIGHTS["static_analysis"],
            error=error,
        )

    error_findings = [r for r in results if _severity(r) == "ERROR"]
    warning_findings = [r for r in results if _severity(r) == "WARNING"]
    # Anything else (e.g. INFO) is below the MEDIUM+ bar (ADR-032 D6) and is
    # not scored — the vendored ruleset does not currently emit INFO rules.

    def _finding_evidence(r: dict, severity: str) -> dict:
        loc = r.get("start", {})
        return make_finding(
            r.get("path", "?"),
            loc.get("line", 0),
            f"[{r.get('check_id', '?')}] {_message(r)}",
            severity=severity,
        )

    evidence = [_finding_evidence(r, "high") for r in error_findings[:10]]
    evidence += [_finding_evidence(r, "medium") for r in warning_findings[:10]]

    weighted_findings = _ERROR_FINDING_WEIGHT * len(error_findings) + len(warning_findings)
    score = normalize(weighted_findings, 0, 10)

    checklist = []
    seen_ids: set[str] = set()
    # ERROR first — the more severe findings lead the reviewer checklist.
    for r in error_findings[:3] + warning_findings[:3]:
        check_id = r.get("check_id", "")
        if check_id not in seen_ids:
            seen_ids.add(check_id)
            loc = r.get("start", {})
            checklist.append(
                f"{r.get('path', '?')}:{loc.get('line', 0)} [{check_id}] — {_message(r)}"
            )

    return make_result(
        dimension="static_analysis",
        score=score,
        raw_value={
            "semgrep_error_count": len(error_findings),
            "semgrep_warning_count": len(warning_findings),
        },
        weight=WEIGHTS["static_analysis"],
        evidence=evidence,
        checklist_items=checklist,
        # Discrete tier promotion the risk-assessor reads independently of
        # the numeric score, mirroring the Python sibling's #997 fix.
        tier_floor="HIGH" if error_findings else None,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(_JS_EXTS) and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "static_analysis",
                    0.0,
                    {"error": "no JS/TS files"},
                    weight=WEIGHTS["static_analysis"],
                    error="no input files",
                ),
                indent=2,
            )
        )
        return
    print(json.dumps(analyse_files(files), indent=2))


if __name__ == "__main__":
    main()
