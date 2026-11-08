"""Shared fixture for tests that run check_agents_static.sh inside a tmp_path tree.

Section 10 of that script (#2276) runs scripts/framework/check_role_writability.py,
which needs the contract, the step-manifest template, risk-assessor.md and each
mapped agent file. This adds a minimal, self-consistent set so a scaffold that
is otherwise unrelated to section 10 still runs clean. The mapped agent is
pm-agent because it is not a D53 peer-review lane (section 8).
"""

import shutil
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "framework" / "check_role_writability.py"


def add_role_writability_fixture(root: Path) -> None:
    """Copy the checker into root and write a minimal consistent role set."""
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True, exist_ok=True)
    shutil.copy(MODULE, fw / MODULE.name)
    (root / "contract").mkdir(exist_ok=True)
    (root / "contract" / "OVERSIGHT-CONTRACT.md").write_text(
        "**Roles** (the HOS checks for these roles):\n\n| Role key | Meaning |\n|---|---|\n"
        "| `process` | PM |\n\nrole_mappings:\n  process:        pm-agent\n"
    )
    (root / "contract" / "step-manifest.template.yaml").write_text(
        "role_mappings:\n  process:        pm-agent\n"
    )
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "risk-assessor.md").write_text(
        "---\nname: risk-assessor\ndescription: fixture\nmodel: sonnet\n---\n"
        "## Phase 6: Required reviewers\n- HIGH adds `process` if not listed\n"
    )
    (agents / "pm-agent.md").write_text(
        "---\nname: pm-agent\ndescription: fixture\nmodel: sonnet\n---\nWrites requirements.\n"
    )
