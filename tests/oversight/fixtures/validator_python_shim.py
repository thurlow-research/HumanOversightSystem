#!/usr/bin/env python3
"""Deterministic stand-in for the oversight venv Python, used by AC-2 tests (#1034).

`run_validators.sh` honours a preset `PYTHON`. Pointing it at this shim makes a
full end-to-end run hermetic: every *validator* invocation returns a canned,
fixed-score envelope instead of shelling out to radon/bandit/ScanCode/`gh`, so
the composite score becomes a pure function of *which validators were dispatched
and with what weights* — exactly the property AC-2 pins.

Dispatch rule (must stay in sync with how run_validators.sh calls Python):
  * argv[1] is a path under `validators/` ending in `.py`  → canned envelope
  * anything else (`-c ...`, `-` heredoc, artifact writer) → exec the real python3

An unrecognised validator basename yields a distinct `unknown_validator`
dimension rather than a silent skip, so a newly dispatched validator shows up as
a golden mismatch instead of vanishing.
"""

from __future__ import annotations

import json
import os
import sys

# basename -> (dimension, score, weight). Scores are arbitrary-but-distinct so a
# dropped/added dimension moves the composite; weights mirror schema.WEIGHTS in
# spirit but are pinned HERE on purpose — this test guards dispatch invariance,
# not weight policy.
_TABLE: dict[str, tuple[str, float, float]] = {
    "rn_calculator.py": ("risk_number", 0.11, 0.15),
    "complexity_metrics.py": ("complexity", 0.22, 0.10),
    "function_metrics.py": ("function_metrics", 0.33, 0.08),
    "n1_detector.py": ("n1_queries", 0.44, 0.10),
    "static_analysis.py": ("static_analysis", 0.55, 0.15),
    "hallucination_surface.py": ("hallucination", 0.66, 0.07),
    "migration_scorer.py": ("migration_risk", 0.12, 0.10),
    "diff_size.py": ("diff_size", 0.23, 0.05),
    "issue_query.py": ("historical_density", 0.34, 0.08),
    "ip_check.py": ("ip_check", 0.45, 0.05),
    "portability_check.py": ("portability", 0.56, 0.05),
    "prompt_audit_risk.py": ("prompt_ambiguity", 0.67, 0.07),
}


def _is_validator(arg: str) -> bool:
    return arg.endswith(".py") and f"{os.sep}validators{os.sep}" in arg


def _record_argv(argv: list[str]) -> None:
    """Append the validator call (basename + args) to $HOS_SHIM_ARGV_LOG, if set.

    Lets a test assert the exact argv each validator was dispatched with — the
    literal form of AC-2's "identical argv" claim, which a canned score alone
    cannot show.
    """
    log = os.environ.get("HOS_SHIM_ARGV_LOG")
    if not log:
        return
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps([os.path.basename(argv[0]), *argv[1:]]) + "\n")


def main() -> None:
    argv = sys.argv[1:]
    if argv and _is_validator(argv[0]):
        _record_argv(argv)
        dimension, score, weight = _TABLE.get(
            os.path.basename(argv[0]), ("unknown_validator", 0.99, 0.99)
        )
        print(
            json.dumps(
                {"dimension": dimension, "score": score, "weight": weight, "error": None}
            )
        )
        return

    # Not a validator call (inline -c, heredoc aggregator, artifact writer):
    # hand off to the real interpreter with stdin/argv intact.
    real = os.environ.get("HOS_SHIM_REAL_PYTHON") or ""
    if not os.path.exists(real):
        real = sys.executable
    os.execv(real, [real, *argv])


if __name__ == "__main__":
    main()
