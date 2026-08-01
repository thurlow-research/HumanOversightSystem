#!/usr/bin/env python3
"""
static_analysis.py — bandit security findings as a risk score.

In the normal path HIGH severity bandit findings are blocked upstream by the
gate script (security_scan.sh). But that gate can be human-suspended
(``SUSPENDED: security`` in contract/gate-suspension.md) or skipped on an empty
file list — legitimate states where the gate exits 0 without blocking. So this
validator scores HIGH findings too (weighted 3× a MEDIUM) AND raises a discrete
``tier_floor="HIGH"`` the risk-assessor reads independently of the numeric
score, so a HIGH bandit finding can never contribute 0.0 to the highest-weight
security dimension. Belt-and-braces: the gate still blocks first in the normal
path; this is the backstop when it doesn't. (#997, #917)

MEDIUM findings feed the composite score without blocking the pipeline.

Optionally runs semgrep with Django security rules if available.

Usage: python static_analysis.py file.py [file2.py ...]
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


def _run_bandit(files: list[str]) -> tuple[list[dict], str | None]:
    """
    Run bandit and return (results, error).

    error is non-None when bandit could not produce a usable result — the tool
    is missing or its output was unparseable. Callers must propagate this as a
    validator-level ``error=`` so the aggregator EXCLUDES the highest-weight
    security dimension rather than scoring a clean 0.0 (fail-open). (#917)
    """
    try:
        result = subprocess.run(
            ["bandit", "-f", "json", "-ll", "-ii"] + files,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "bandit not installed — run: pip install bandit"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "bandit output unparseable — scan failed, cannot assess security risk"
    return data.get("results", []), None


def _run_semgrep(files: list[str]) -> tuple[list[dict], str, str | None]:
    """
    Run semgrep and return (results, status, error).

    Unlike bandit, semgrep is an optional additive signal here — its absence
    must not exclude the whole static_analysis dimension. But "semgrep isn't
    installed" and "semgrep is installed and a scan attempt failed" both used
    to collapse to the same empty `[]`, making a broken scan indistinguishable
    from a clean one (#1087). status distinguishes the two: "not_installed"
    (expected/accepted degraded mode, callers stay silent) vs "error" (semgrep
    ran but produced no usable output — a timeout or an output-format break —
    which callers must surface, not silently score as clean).
    """
    try:
        subprocess.run(["semgrep", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [], "not_installed", None
    try:
        result = subprocess.run(
            ["semgrep", "--config", "p/django", "--json", "--quiet"] + files,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return [], "error", "semgrep scan timed out after 60s — cannot assess this signal"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "error", "semgrep output unparseable — scan failed, cannot assess this signal"
    return data.get("results", []), "ok", None


# A HIGH bandit finding weighs this many MEDIUM findings toward the numeric
# score. HIGH is the more severe signal, so it should raise the score faster
# than a MEDIUM does (the pre-#997 code scored HIGH as exactly 0.0). (#997)
_HIGH_FINDING_WEIGHT = 3


def analyse_files(file_paths: list[str]) -> dict:
    bandit_results, bandit_error = _run_bandit(file_paths)
    if bandit_error is not None:
        # Bandit is the primary security tool here. If it cannot run, this
        # dimension has no signal — exclude it from the composite rather than
        # reporting a clean 0.0 that drags the score toward LOW. (#917)
        return make_result(
            dimension="static_analysis",
            score=0.0,
            raw_value={"error": bandit_error},
            weight=WEIGHTS["static_analysis"],
            error=bandit_error,
        )

    semgrep_results, semgrep_status, semgrep_error = _run_semgrep(file_paths)

    # Score HIGH as well as MEDIUM. HIGH is normally blocked upstream, but when
    # the gate is suspended or skipped it reaches here and must not score 0.0.
    high_findings = [r for r in bandit_results if r.get("issue_severity", "LOW") == "HIGH"]
    medium_findings = [r for r in bandit_results if r.get("issue_severity", "LOW") == "MEDIUM"]

    def _finding_evidence(r: dict, severity: str) -> dict:
        return make_finding(
            r.get("filename", "?"),
            r.get("line_number", 0),
            f"[{r.get('test_id', '?')}] {r.get('issue_text', '')} "
            f"(conf={r.get('issue_confidence', '?')})",
            severity=severity,
        )

    evidence = [_finding_evidence(r, "high") for r in high_findings[:10]]
    evidence += [_finding_evidence(r, "medium") for r in medium_findings[:10]]

    for r in semgrep_results[:5]:
        loc = r.get("start", {})
        evidence.append(
            make_finding(
                r.get("path", "?"),
                loc.get("line", 0),
                f"[semgrep:{r.get('check_id', '?')}] {r.get('extra', {}).get('message', '')}",
                severity="medium",
            )
        )

    weighted_findings = (
        _HIGH_FINDING_WEIGHT * len(high_findings)
        + len(medium_findings)
        + len(semgrep_results)
    )
    score = normalize(weighted_findings, 0, 10)

    checklist = []
    seen_ids: set[str] = set()
    # HIGH first — the more severe findings lead the reviewer checklist.
    for r in high_findings[:3] + medium_findings[:3]:
        test_id = r.get("test_id", "")
        if test_id not in seen_ids:
            seen_ids.add(test_id)
            checklist.append(
                f"{r.get('filename', '?')}:{r.get('line_number', 0)} "
                f"[{test_id}] — {r.get('issue_text', '')}"
            )
    if semgrep_status == "error":
        # A failed scan must not read the same as "semgrep ran clean" (#1087) —
        # flag it on the checklist so a reviewer knows the semgrep_count above
        # reflects a broken tool, not a swept file.
        checklist.append(f"⚠ semgrep did not complete ({semgrep_error}) — semgrep_count above is not a clean scan result; verify manually")

    raw_value = {
        "bandit_high_count": len(high_findings),
        "bandit_medium_count": len(medium_findings),
        "semgrep_count": len(semgrep_results),
        "semgrep_status": semgrep_status,
    }
    if semgrep_error is not None:
        raw_value["semgrep_error"] = semgrep_error

    return make_result(
        dimension="static_analysis",
        score=score,
        raw_value=raw_value,
        weight=WEIGHTS["static_analysis"],
        evidence=evidence,
        checklist_items=checklist,
        # Discrete tier promotion the risk-assessor reads even if the gate that
        # normally blocks HIGH was suspended/skipped. (#997)
        tier_floor="HIGH" if high_findings else None,
    )


def main() -> None:
    files = [f for f in sys.argv[1:] if f.endswith(".py") and Path(f).exists()]
    if not files:
        print(
            json.dumps(
                make_result(
                    "static_analysis",
                    0.0,
                    {"error": "no input"},
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
