"""Regression test for #1978: the worker cron prompt must scope the validators.

An unscoped `run_validators.sh` (no files) fail-closes CRITICAL every time, so
the Step 4 HARD GATE would be red regardless of the change.
"""

from __future__ import annotations

import re
from pathlib import Path

CRON_PROMPT = Path(__file__).resolve().parents[2] / "bootstrap" / "worker-cron-prompt.md"
BARE_INVOCATION = re.compile(r"^\s*bash scripts/oversight/run_validators\.sh\s*$", re.MULTILINE)


def test_no_bare_unscoped_validator_invocation():
    assert not BARE_INVOCATION.search(CRON_PROMPT.read_text(encoding="utf-8"))


def test_step4_scopes_validators_with_diff():
    text = CRON_PROMPT.read_text(encoding="utf-8")
    assert "bash scripts/oversight/run_validators.sh --diff origin/main...HEAD" in text
