"""Tests for scripts/framework/check_role_writability.py (#2276).

Every test builds a fixture tree under tmp_path; the real-repo test is read-only.
"""
from pathlib import Path

from scripts.framework import check_role_writability as crw

ROOT = Path(__file__).resolve().parents[2]

CONTRACT = """# Contract
```yaml
role_mappings:
  code-review:    code-reviewer      # agent name -> role key
  architecture:   architect
```
"""
TEMPLATE = """role_mappings:
  code-review:    code-reviewer
  architecture:   architect
  # ops:          ops-reviewer         # uncomment for ops
"""
RISK = """# Risk assessor
## Phase 6: Required reviewers
- HIGH adds `code-review` if not already listed
- Any tier adds `architecture` if not listed. Never the agent name `architect`.
- HIGH+ adds `ops` if not already listed

## Phase 7: Other
- adds `bogus` here, outside Phase 6
"""
SCOPED = "You write a register entry only when the step requires it.\n"
PRE_FIX = "You do not write a per-step sign-off register entry; your decisions are recorded in the ADR\n"


def _tree(tmp_path, contract=CONTRACT, template=TEMPLATE, risk=RISK, agents=None):
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "OVERSIGHT-CONTRACT.md").write_text(contract)
    (tmp_path / "contract" / "step-manifest.template.yaml").write_text(template)
    adir = tmp_path / ".claude" / "agents"
    adir.mkdir(parents=True)
    (adir / "risk-assessor.md").write_text(risk)
    agents = agents if agents is not None else {
        "code-reviewer": "Reviews code.\n",
        "architect": SCOPED,
        "ops-reviewer": "Reviews ops.\n",
    }
    for name, body in agents.items():
        (adir / f"{name}.md").write_text(body)
    return tmp_path


def _run(root, capsys):
    rc = crw.main(["--repo-root", str(root)])
    return rc, capsys.readouterr()


def test_clean_tree_passes(tmp_path, capsys):
    rc, out = _run(_tree(tmp_path), capsys)
    assert rc == 0, out


def test_unmapped_emitted_role_fails(tmp_path, capsys):
    risk = RISK.replace("adds `ops`", "adds `ops`, `ghost`")
    rc, out = _run(_tree(tmp_path, risk=risk), capsys)
    assert rc == 1
    assert "role `ghost` emitted by risk-assessor has no role_mappings entry" in out.out


def test_roles_outside_phase6_are_ignored(tmp_path):
    assert crw.read_phase6_roles(_tree(tmp_path) / ".claude/agents/risk-assessor.md") == [
        "code-review", "architecture", "ops"]


def test_conflicting_mappings_fail(tmp_path, capsys):
    template = TEMPLATE.replace("architecture:   architect", "architecture:   code-reviewer")
    rc, out = _run(_tree(tmp_path, template=template), capsys)
    assert rc == 1
    assert "role `architecture` maps to `architect`" in out.out


def test_missing_agent_file_fails(tmp_path, capsys):
    root = _tree(tmp_path, agents={"code-reviewer": "x\n", "ops-reviewer": "x\n"})
    rc, out = _run(root, capsys)
    assert rc == 1
    assert "mapped agent `architect` has no" in out.out


def test_unscoped_prohibition_fails_with_file_line(tmp_path, capsys):
    root = _tree(tmp_path, agents={
        "code-reviewer": "ok\n", "ops-reviewer": "ok\n",
        "architect": "intro\n" + PRE_FIX})
    rc, out = _run(root, capsys)
    assert rc == 1
    assert ".claude/agents/architect.md:2:" in out.out


def test_scoped_prohibition_passes(tmp_path, capsys):
    scoped = "You do not write a sign-off register entry unless the step requires it.\n"
    root = _tree(tmp_path, agents={
        "code-reviewer": "ok\n", "ops-reviewer": "ok\n", "architect": scoped})
    rc, out = _run(root, capsys)
    assert rc == 0, out


def test_escalation_boilerplate_is_not_a_prohibition(tmp_path):
    line = "stop, do not attempt a 6th round. Escalate and write a `Status: ESCALATED` register entry."
    f = tmp_path / "a.md"
    f.write_text(line + "\n")
    assert crw.find_unscoped_prohibitions(f) == []


def test_missing_role_mappings_block_exits_2(tmp_path, capsys):
    rc, out = _run(_tree(tmp_path, contract="# no mappings\n"), capsys)
    assert rc == 2
    assert "no role_mappings block" in out.err


def test_missing_required_file_exits_2(tmp_path, capsys):
    rc, out = _run(tmp_path, capsys)
    assert rc == 2


def test_real_repo_is_clean(capsys):
    rc, out = _run(ROOT, capsys)
    assert rc == 0, out
