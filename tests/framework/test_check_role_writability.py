"""Tests for scripts/framework/check_role_writability.py (#2276).

Every test builds a fixture tree under tmp_path; the real-repo test is read-only.
"""

import subprocess
from pathlib import Path

from scripts.framework import check_role_writability as crw
from tests.framework._role_writability_scaffold import add_role_writability_fixture
from tests.framework.test_check_agents_static_dated_model_ids import CHECKER, LOGIC

ROOT = Path(__file__).resolve().parents[2]

CONTRACT = """# Contract
**Roles** (keys):

| Role key | Meaning |
|---|---|
| `code-review` | x |
| `architecture` | x |
| `ops` | x |

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
PRE_FIX = (
    "You do not write a per-step sign-off register entry; your decisions are recorded in the ADR\n"
)


def _tree(tmp_path, contract=CONTRACT, template=TEMPLATE, risk=RISK, agents=None):
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "OVERSIGHT-CONTRACT.md").write_text(contract)
    (tmp_path / "contract" / "step-manifest.template.yaml").write_text(template)
    adir = tmp_path / ".claude" / "agents"
    adir.mkdir(parents=True)
    (adir / "risk-assessor.md").write_text(risk)
    agents = (
        agents
        if agents is not None
        else {
            "code-reviewer": "Reviews code.\n",
            "architect": SCOPED,
            "ops-reviewer": "Reviews ops.\n",
        }
    )
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
        "code-review",
        "architecture",
        "ops",
    ]


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
    root = _tree(
        tmp_path,
        agents={"code-reviewer": "ok\n", "ops-reviewer": "ok\n", "architect": "intro\n" + PRE_FIX},
    )
    rc, out = _run(root, capsys)
    assert rc == 1
    assert ".claude/agents/architect.md:2:" in out.out


def test_scoped_prohibition_passes(tmp_path, capsys):
    scoped = "You do not write a sign-off register entry unless the step requires it.\n"
    root = _tree(
        tmp_path, agents={"code-reviewer": "ok\n", "ops-reviewer": "ok\n", "architect": scoped}
    )
    rc, out = _run(root, capsys)
    assert rc == 0, out


def test_escalation_boilerplate_is_not_a_prohibition(tmp_path):
    line = (
        "stop, do not attempt a 6th round. Escalate and write a `Status: ESCALATED` register entry."
    )
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


def test_markdown_emphasis_does_not_hide_scope(tmp_path):
    line = "You write a register entry **only** when required; do not write one otherwise, register entry.\n"
    f = tmp_path / "a.md"
    f.write_text(line)
    assert crw.find_unscoped_prohibitions(f) == []


def test_real_architect_line_is_scoped():
    arch = ROOT / ".claude" / "agents" / "architect.md"
    line = next(ln for ln in arch.read_text().splitlines() if "`architecture` role" in ln)
    plain = line.replace("*", "").replace("_", "")
    assert crw.SCOPE_RE.search(plain)
    assert crw.find_unscoped_prohibitions(arch) == []


def test_widened_negations_are_caught(tmp_path):
    for neg in (
        "must not write",
        "may not write",
        "cannot write",
        "can't write",
        "shall not write",
        "never writes",
        "does not write",
        "do not ever write",
        "must not be writing",
    ):
        f = tmp_path / "a.md"
        f.write_text(f"You {neg} a sign-off register entry.\n")
        assert len(crw.find_unscoped_prohibitions(f)) == 1, neg


def test_prose_comment_is_not_a_mapping():
    lines = [
        "  # Note: this is optional",
        "  # ops:          ops-reviewer         # uncomment for ops",
        "  # reliability:  reliability-reviewer",
        "  # Example: ops-reviewer is the agent",
    ]
    assert crw._parse_mappings(lines) == {
        "ops": "ops-reviewer",
        "reliability": "reliability-reviewer",
    }


def test_role_missing_from_contract_table_fails(tmp_path, capsys):
    contract = CONTRACT.replace("| `ops` | x |\n", "")
    rc, out = _run(_tree(tmp_path, contract=contract), capsys)
    assert rc == 1
    assert "role `ops` is not in the" in out.out


def test_mapping_key_missing_from_contract_table_fails(tmp_path, capsys):
    contract = CONTRACT.replace("| `architecture` | x |\n", "")
    risk = RISK.replace("adds `architecture`", "adds `code-review`")
    rc, out = _run(_tree(tmp_path, contract=contract, risk=risk), capsys)
    assert rc == 1
    assert "role `architecture` is not in the" in out.out


def test_missing_contract_roles_table_exits_2(tmp_path, capsys):
    contract = CONTRACT.replace("**Roles**", "Roles")
    rc, out = _run(_tree(tmp_path, contract=contract), capsys)
    assert rc == 2
    assert "role table" in out.err


def _static_tree(tmp_path):
    (tmp_path / "scripts" / "framework").mkdir(parents=True)
    (tmp_path / "scripts" / "oversight").mkdir(parents=True)
    import shutil

    shutil.copy(CHECKER, tmp_path / "scripts" / "framework" / CHECKER.name)
    shutil.copy(LOGIC, tmp_path / "scripts" / "oversight" / LOGIC.name)
    adir = tmp_path / ".claude" / "agents"
    adir.mkdir(parents=True)
    (adir / "fake-agent.md").write_text(
        "---\nname: fake-agent\ndescription: t\nmodel: sonnet\n---\n\nFixture.\n"
    )


def _static_run(tmp_path):
    return subprocess.run(
        ["bash", "scripts/framework/check_agents_static.sh"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_static_section_skipped_when_checker_not_installed(tmp_path):
    _static_tree(tmp_path)
    result = _static_run(tmp_path)
    assert "role-writability checker not installed; section skipped" in result.stdout
    assert "FAIL" not in result.stdout, result.stdout
    assert result.returncode == 0, result.stdout + result.stderr


def test_static_section_fails_on_unmapped_emitted_role(tmp_path):
    _static_tree(tmp_path)
    add_role_writability_fixture(tmp_path)
    risk = tmp_path / ".claude" / "agents" / "risk-assessor.md"
    risk.write_text(risk.read_text().replace("adds `process`", "adds `process`, `ghost`"))
    result = _static_run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "role `ghost` emitted by risk-assessor has no role_mappings entry" in result.stdout


def test_static_section_fails_when_contract_missing_but_checker_present(tmp_path):
    _static_tree(tmp_path)
    add_role_writability_fixture(tmp_path)
    (tmp_path / "contract" / "OVERSIGHT-CONTRACT.md").unlink()
    result = _static_run(tmp_path)
    assert result.returncode == 1, result.stdout


def test_template_without_role_mappings_block_exits_2(tmp_path, capsys):
    rc, out = _run(_tree(tmp_path, template="# nothing\n"), capsys)
    assert rc == 2
    assert "step-manifest.template.yaml" in out.err
    assert "no role_mappings block" in out.err


def test_risk_assessor_without_phase6_roles_exits_2(tmp_path, capsys):
    rc, out = _run(_tree(tmp_path, risk="# Risk assessor\n"), capsys)
    assert rc == 2
    assert "no roles found" in out.err


def test_quiet_suppresses_ok_line_on_clean_tree(tmp_path, capsys):
    rc = crw.main(["--repo-root", str(_tree(tmp_path)), "--quiet"])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_cli_entrypoint_exit_codes_on_clean_and_broken_tree(tmp_path):
    script = ROOT / "scripts" / "framework" / "check_role_writability.py"
    clean = _tree(tmp_path / "a") if (tmp_path / "a").mkdir() is None else None
    ok = subprocess.run(
        ["python3", str(script), "--repo-root", str(clean)], capture_output=True, text=True
    )
    assert ok.returncode == 0
    assert ok.stdout.startswith("OK:")
    bad = subprocess.run(
        ["python3", str(script), "--repo-root", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2
