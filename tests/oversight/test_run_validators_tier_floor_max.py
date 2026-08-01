"""#1052 regression: summary.json's tier_floor must be the MAX across validators,
not the first non-null one in glob-sorted filename order.

Multiple validators can emit `tier_floor` (`rn_calculator.py` via the task-class
floor, #373; `static_analysis.py` via the HIGH-bandit backstop, #997). Because
`risk_number.json` sorts before `static_analysis.json` ('r' < 's'), the old
first-wins loop picked up rn_calculator's lower floor and broke before ever
reading static_analysis's higher one — silently under-reporting risk on exactly
the changes the #997 backstop exists to catch.
"""

from __future__ import annotations

import json
import shutil

import pytest

from tests.oversight.run_validators_harness import (
    OUT_REL,
    commit_files,
    hermetic_run,
    init_repo,
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)

_PY_ONLY = {"pkg/mod.py": "def f(x):\n    return x + 1\n"}


def _repo(tmp_path):
    init_repo(tmp_path)
    commit_files(tmp_path, _PY_ONLY, subject="add python module")


def test_tier_floor_is_max_not_first_alphabetical(tmp_path):
    _repo(tmp_path)

    # rn_calculator.py ("risk_number.json") sorts before static_analysis.py
    # ("static_analysis.json") — pin a LOWER floor on the alphabetically-first
    # validator and a HIGHER floor on the alphabetically-later one, so a
    # first-wins bug and a max-wins fix disagree on the result.
    extra_env = {
        "HOS_SHIM_EXTRA_FIELDS": json.dumps(
            {
                "rn_calculator.py": {"tier_floor": "MEDIUM"},
                "static_analysis.py": {"tier_floor": "HIGH"},
            }
        )
    }

    proc = hermetic_run(tmp_path, "pkg/mod.py", extra_env=extra_env)
    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"

    summary = json.loads((tmp_path / OUT_REL / "summary.json").read_text())
    assert summary["tier_floor"] == "HIGH", (
        "tier_floor hoisted the alphabetically-first non-null value instead of "
        f"the max across validators.\nsummary: {summary}"
    )


def test_tier_floor_absent_when_no_validator_emits_one(tmp_path):
    _repo(tmp_path)

    proc = hermetic_run(tmp_path, "pkg/mod.py")
    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"

    summary = json.loads((tmp_path / OUT_REL / "summary.json").read_text())
    assert "tier_floor" not in summary
