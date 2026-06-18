"""gate_compliance.py — deterministic gate non-override invariant helpers (SPEC-375).

Provides pure-Python, stdlib-only helpers that the oversight-evaluator and
any automation layer can call to assert REQ-GATE-NN-08/16/17 compliance
without reading the full JSON detail themselves.

Functions
---------
load_gate_results(repo_root)
    Read .claudetmp/oversight/validators/gate-results.json.
    Returns [] if the file is absent (not an error — the caller decides).

load_composite_score(repo_root)
    Read the composite_score field from summary.json.
    Returns None if absent.

gates_required(step_manifest_path, step)
    Return True when the step manifest declares gates_required: true for step.
    Handles both string and integer step ids.

check_gate_compliance(gate_results, composite_score, step, *, gates_required)
    Return a list of compliance-failure strings.  Empty list = all pass.

CRITICAL threshold: 0.78 (matches schema.TIER_THRESHOLDS["CRITICAL"]).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

# Matches schema.py TIER_THRESHOLDS CRITICAL lower bound (score >= 0.78).
_CRITICAL_THRESHOLD: float = 0.78

_GATE_RESULTS_PATH = ".claudetmp/oversight/validators/gate-results.json"
_SUMMARY_PATH = ".claudetmp/oversight/validators/summary.json"


def load_gate_results(repo_root: Union[str, Path] = ".") -> list[dict]:
    """Read gate-results.json; return [] if the file is absent or unreadable.

    Each record is expected to have the shape produced by run_gates.sh:
      {"gate": str, "exit_code": int, "suspended": bool, "script": str, "ts": str}
    """
    path = Path(repo_root) / _GATE_RESULTS_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def load_composite_score(repo_root: Union[str, Path] = ".") -> float | None:
    """Read composite_score from summary.json; return None if absent or unreadable."""
    path = Path(repo_root) / _SUMMARY_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    val = data.get("composite_score")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def gates_required(step_manifest_path: Union[str, Path], step: Union[str, int]) -> bool:
    """Return True when the step manifest declares gates_required: true for step.

    Reads YAML manually using stdlib to avoid any third-party dependency.
    Supports the subset of YAML used in step-manifest.yaml (no anchors, no
    multi-line strings in the steps block).  Falls back to False on any parse
    or IO error so the caller can decide how to treat an unreadable manifest.

    The step id is matched as both string and integer to handle YAML integer ids
    vs. a string caller argument without requiring type coercion from the caller.
    """
    path = Path(step_manifest_path)
    if not path.exists():
        return False
    try:
        text = path.read_text()
    except OSError:
        return False

    # Simple line-by-line YAML parser for the steps list — avoids PyYAML dep.
    # Strategy: find the steps: block, locate the entry whose id matches, then
    # scan forward for a gates_required: true line until the next entry (id:) or EOF.
    step_str = str(step)
    in_steps = False
    in_target_step = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("steps:"):
            in_steps = True
            continue

        if not in_steps:
            continue

        # A top-level key (no leading spaces) outside the steps block ends it.
        if line and not line[0].isspace() and ":" in line and not stripped.startswith("-"):
            in_steps = False
            in_target_step = False
            continue

        if stripped.startswith("- id:"):
            # New step entry — check if this is ours.
            id_val = stripped[len("- id:"):].strip().strip("\"'")
            in_target_step = id_val == step_str or id_val == str(step)
            continue

        if in_target_step and stripped.startswith("id:"):
            id_val = stripped[len("id:"):].strip().strip("\"'")
            in_target_step = id_val == step_str
            continue

        if in_target_step and stripped.startswith("gates_required:"):
            val = stripped[len("gates_required:"):].strip().strip("\"'").lower()
            return val in ("true", "yes", "1")

    return False


def check_gate_compliance(
    gate_results: list[dict],
    composite_score: float | None,
    step: Union[str, int],
    *,
    gates_required: bool = False,
) -> list[str]:
    """Return a list of compliance-failure strings; empty list means all pass.

    REQ-GATE-NN-16: gate-results.json must be present when gates_required=True.
    REQ-GATE-NN-08: every failed non-suspended gate is a deterministic failure
                    that must appear unresolved in human-facing output.
    REQ-GATE-NN-17: composite_score >= 0.78 is a deterministic CRITICAL regardless
                    of blocking_findings — it must appear in output.
    """
    failures: list[str] = []

    # REQ-GATE-NN-16 — gate-results.json absent when gates are required.
    if gates_required and not gate_results:
        failures.append(
            f"gate-results.json absent for step {step} — "
            "COMPLIANCE FAIL (REQ-GATE-NN-16)"
        )

    # REQ-GATE-NN-08 — failed non-suspended gates.
    for record in gate_results:
        gate = record.get("gate", "<unknown>")
        exit_code = record.get("exit_code", 0)
        suspended = record.get("suspended", False)
        if exit_code != 0 and not suspended:
            failures.append(
                f"Gate {gate} failed (exit {exit_code}) — "
                "deterministic failure must appear unresolved in human-facing output "
                "(REQ-GATE-NN-08)"
            )

    # REQ-GATE-NN-17 — composite score at or above CRITICAL threshold.
    if composite_score is not None and composite_score >= _CRITICAL_THRESHOLD:
        failures.append(
            f"Composite score {composite_score:.3f} ≥ CRITICAL threshold "
            f"{_CRITICAL_THRESHOLD:.2f} — deterministic CRITICAL regardless of "
            "blocking_findings (REQ-GATE-NN-17)"
        )

    return failures
