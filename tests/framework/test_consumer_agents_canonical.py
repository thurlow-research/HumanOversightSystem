"""Guards the canonical consumer-agent list (HOS#225).

The install copy-loop and the .hos-manifest enumerator must read the SAME list
(scripts/framework/consumer_agents.txt) so the manifest can never declare an
agent the install didn't ship. These tests fail if either side stops reading the
list, or if a framework-dev validator leaks into the consumer set.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "scripts" / "framework" / "consumer_agents.txt"
INSTALLER = ROOT / "bootstrap" / "hos_install.sh"

VALIDATORS = {
    "framework-validator",
    "framework-setup-validator",
    "doc-validator",
    "spec-compliance-validator",
}


def _agents() -> list[str]:
    out = []
    for line in LIST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def test_list_exists_and_nonempty():
    assert LIST.is_file()
    assert _agents(), "consumer_agents.txt has no agents"


def test_core_oversight_agents_present():
    agents = set(_agents())
    for a in ["risk-assessor", "oversight-evaluator", "oversight-orchestrator",
              "risk-historian", "dep-mapper", "spec-red-team", "prompt-fidelity"]:
        assert a in agents, f"{a} missing from canonical consumer set"


def test_framework_dev_validators_excluded():
    leaked = VALIDATORS & set(_agents())
    assert not leaked, f"framework-dev validators must not ship to consumers: {leaked}"


def test_every_listed_agent_exists_in_source():
    for a in _agents():
        assert (ROOT / ".claude" / "agents" / f"{a}.md").is_file(), \
            f"consumer_agents.txt lists {a} but .claude/agents/{a}.md is missing"


def test_installer_reads_list_on_both_sides():
    """Both the copy-loop and the manifest enumerator must read the canonical
    list — the whole point is that they cannot drift (HOS#225)."""
    text = INSTALLER.read_text()
    assert text.count("consumer_agents.txt") >= 2, \
        "hos_install.sh must reference consumer_agents.txt in BOTH the copy-loop and enumerate_framework_files"
    # The manifest enumerator must NOT fall back to `find .claude/agents` (the bug).
    assert "find .claude/agents" not in text, \
        "manifest enumeration must not `find` all agents — it declares uninstalled ones (#225)"
