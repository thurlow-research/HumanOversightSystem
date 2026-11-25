"""Tests for the time-boxed dep-mapper LOW suspension (#2214).

Covers suspension_manager.py (grammar, status classifier, CLI, trace validator,
resolution check) and pr_readiness.py REQ-W-18. A fixed clock and stubbed issue
events are used throughout: no network access, and nothing is written outside
pytest's tmp_path.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.automation.lib import github, merge_config, pr_readiness
from scripts.automation.lib.github import ListTruncatedError
from tests.conftest import load_module_from_path

REPO = Path(__file__).resolve().parents[2]
sm = load_module_from_path(
    "suspension_manager_timebox", REPO / "scripts/oversight/suspension_manager.py"
)

LINE = "SUSPENDED: dep-mapper expires: 2026-12-31 until-closed: #2162"
TODAY = "2026-11-06"
STEP = "s1"
OPEN: tuple[str, str | None, list[str | None]] = ("open", None, [])


def susp_text(line: str = LINE) -> str:
    return (
        f"Authorized by: Test Human\nreason_category: OTHER\n\n## Currently suspended\n\n{line}\n"
    )


class Stub:
    """issue_state stub that records its calls."""

    def __init__(self, value=OPEN, exc=None):
        self.value, self.exc, self.calls = value, exc, []

    def __call__(self, n, repo_root=None):
        self.calls.append(n)
        if self.exc:
            raise self.exc
        return self.value


def status(line=LINE, today=TODAY, stub=None, gate="dep-mapper"):
    stub = stub or Stub()
    return sm.suspension_status(susp_text(line), gate, today=today, issue_state=stub), stub


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def make_trace(step, base, head, files, result="pass"):
    rows = "\n".join(f"| {f} | callers | grep | {result} |" for f in files)
    return (
        f"# dep-mapper manual trace — step {step}\n\n"
        f"Range: {base}..{head}\n"
        "dep-mapper result: Data confidence: LOW (no callers resolved)\n"
        "Date: 2026-11-06\n\n"
        "## Callers / readers checked\n\n"
        "| Changed file | Callers / readers | Check | Result |\n|---|---|---|---|\n"
        f"{rows}\n\n"
        "## Items dep-mapper left untraced\n\n- wiring item X, checked by grep\n\n"
        "## Conclusion\n\nResult: PASS\nAll callers checked.\n"
    )


def make_risk(base, head, validated="HIGH", source="dep-mapper", resolution=None, step=STEP):
    resolution = resolution or (
        f"suspended: dep-mapper (trace: {sm.dep_trace_path(step)})  # inline note"
    )
    vt = f"validated_tier: {validated}\n" if validated else ""
    return (
        f"# Risk Assessment — Step {step}\n{vt}composite_score: 0.50\n"
        f"base_sha: {base}\nhead_sha: {head}\nfiles_assessed:\n  - scripts/foo.py\n\n"
        "blocking_findings:\n"
        "  # comment\n"
        "  - id: dep-low\n"
        f"    source: {source}\n"
        "    description: LOW confidence\n"
        f"    resolution: {resolution}\n\n## Body\n"
    )


HEADING = "## dep-mapper LOW disclosure (suspended blocker)"
AI_HEADING = "## 🤖 AI-Submitted Pull Request"
CALLERS_H = "## Callers / readers checked"
ITEMS_H = "## Items dep-mapper left untraced"
# The fixed AI-Submitted block (shape of the oversight-orchestrator template), then a blank
# line before the disclosure heading (P7, P9).
AI_BLOCK = [
    AI_HEADING,
    "",
    "This PR was **created and submitted by an AI agent**. A human did not manually",
    "write or submit this PR. All supporting review artifacts are automated.",
    "",
    "| | |",
    "|---|---|",
    "| **Agent** | `oversight-orchestrator` |",
    "| **Model** | `claude-opus-5-5` |",
    "| **Step / context** | Step s1 — internal review chain approved; tier: HIGH. |",
    "",
    "Human approval is required before merge for **MEDIUM+ risk** (`AGENT-IDENTITY.md §9.0`).",
    "",
    "---",
    "",
]
SUFFIX = ["# Handoff — Step s1", "Validated tier: HIGH  |  Composite score: 0.5"]


def _copied_section(trace, heading):
    """The trace's section copied unchanged: heading, its lines, then one blank line."""
    lines = trace.split("\n")
    out = [heading]
    for ln in lines[lines.index(heading) + 1 :]:
        if ln.startswith("## "):
            break
        out.append(ln)
    while not out[-1].strip():
        out.pop()
    return out + [""]


def disclosure_lines(step, trace, susp):
    """The section template of TD 5.3 filled from a trace and a suspension file."""
    by = re.search(r"^Authorized by:\s*(.*?)\s*$", susp, re.M).group(1)
    sus = next(x for x in sm.parse_suspensions(susp) if x.gate == "dep-mapper")
    exp = sus.expires or "none"
    uc = f"issue {sus.until_closed}" if sus.until_closed is not None else "none"
    return [
        HEADING,
        "",
        "dep-mapper reported Data confidence: LOW on this step. Per contract/gate-suspension.md",
        f"(Authorized by: {by}; expires: {exp}; until-closed: {uc})",
        "it is not blocking while the suspension is active.",
        f"Manual trace: {sm.dep_trace_path(step)}",
        "",
        *_copied_section(trace, CALLERS_H),
        *_copied_section(trace, ITEMS_H),
        "Result: PASS",
        "",
    ]


def make_handoff(step=STEP, drop=None, trace=None, susp=None, suffix=None):
    """A faithful handoff (D-21): AI block, the filled section placed per D-20, suffix."""
    trace = trace if trace is not None else make_trace(step, BASE, HEAD, FILES)
    susp = susp if susp is not None else susp_text()
    suffix = SUFFIX if suffix is None else suffix
    lines = AI_BLOCK + disclosure_lines(step, trace, susp) + suffix
    return "\n".join(ln for ln in lines if not (drop and drop in ln)) + "\n"


FILES = ["scripts/foo.py"]
BASE, HEAD = "a" * 40, "b" * 40


def run_check(**over):
    """Pure-function call with an all-valid default; override any argument."""
    args = dict(
        risk_text=make_risk(BASE, HEAD),
        step=STEP,
        base_sha=BASE,
        head_sha=HEAD,
        tier="HIGH",
        human_gate_required=False,
        changed_files=FILES,
        main_suspension_text=susp_text(),
        worktree_suspension_text=susp_text(),
        handoff_text=None,
        require_disclosure=False,
        today=TODAY,
        issue_state=Stub(),
        read_text=lambda p: make_trace(STEP, BASE, HEAD, FILES),
        main_suspension_error=None,
        human_gate_error=None,
    )
    args.update(over)
    return sm.check_suspended_resolutions(**args)


def errors_of(res):
    return res["errors"] + [e for f in res["findings"] for e in f["errors"]]


# ---------------------------------------------------------------------------
# (c) status classifier
# ---------------------------------------------------------------------------


def test_c1_expiry_date_is_inclusive():
    res, _ = status(today="2026-12-31")
    assert res["status"] == "active"
    assert res["expires"] == "2026-12-31" and res["until_closed"] == 2162


def test_c2_expired_date_never_calls_stub():
    res, stub = status(today="2027-01-01")
    assert res["status"] == "expired"
    assert "2027-01-01" in res["detail"]
    assert stub.calls == []


def test_c3_closed_completed_expires():
    res, _ = status(stub=Stub(("closed", "completed", ["completed"])))
    assert res["status"] == "expired"


def test_c4_closed_not_planned_stays_active():
    res, _ = status(stub=Stub(("closed", "not_planned", ["not_planned"])))
    assert res["status"] == "active"


@pytest.mark.parametrize(
    "stub",
    [
        Stub(exc=RuntimeError("boom")),
        Stub(("closed", None)),
        Stub(("weird", None, [])),
        Stub(("open", None, "x")),
    ],
)
def test_c5_lookup_failure_or_bad_shape_is_unknown(stub):
    res, _ = status(stub=stub)
    assert res["status"] == "unknown"


@pytest.mark.parametrize(
    "line",
    [
        "SUSPENDED: dep-mapper expires: 2026-12-31 bogus-flag",
        "SUSPENDED: dep-mapper expires: 2026-13-45",
        "SUSPENDED: dep-mapper expires: 2026-12-31 expires: 2026-12-30",
        "SUSPENDED: dep-mapper until-closed: #1 until-closed: #2",
        LINE + "\n" + LINE,
    ],
)
def test_c6_malformed(line):
    res, stub = status(line=line)
    assert res["status"] == "malformed"
    assert stub.calls == []


def test_c6_absent():
    assert status(line="SUSPENDED: lint")[0]["status"] == "absent"
    assert sm.suspension_status("", "dep-mapper")["status"] == "absent"


def test_c7_cmd_is_suspended_active_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract/gate-suspension.md").write_text(susp_text())
    monkeypatch.setattr(sm, "_today", lambda: TODAY)
    monkeypatch.setattr(sm, "_default_issue_state", Stub())
    assert sm.cmd_is_suspended("dep-mapper") == 0
    monkeypatch.setattr(sm, "_today", lambda: "2027-01-01")
    assert sm.cmd_is_suspended("dep-mapper") == 1  # expired
    monkeypatch.setattr(sm, "_today", lambda: TODAY)
    monkeypatch.setattr(sm, "_default_issue_state", Stub(exc=RuntimeError()))
    assert sm.cmd_is_suspended("dep-mapper") == 1  # unknown
    (tmp_path / "contract/gate-suspension.md").write_text(susp_text("SUSPENDED: dep-mapper zzz"))
    assert sm.cmd_is_suspended("dep-mapper") == 1  # malformed


def test_c8_backward_compat_lines_make_no_calls():
    stub = Stub()
    text = "SUSPENDED: lint\nSUSPENDED: types [pinned]\nSUSPENDED: sec review-by: 2020-01-01\n"
    for gate in ("lint", "types", "sec"):
        assert sm.suspension_status(text, gate, today=TODAY, issue_state=stub)["status"] == "active"
    assert stub.calls == []
    parsed = {s.gate: s for s in sm.parse_suspensions(text)}
    assert parsed["types"].pinned and not parsed["lint"].pinned
    assert parsed["sec"].review_by == "2020-01-01"
    assert all(
        s.expires is None and s.until_closed is None and not s.malformed for s in parsed.values()
    )


def test_c9_census_never_calls_stub_and_flags_expired(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sm, "_today", lambda: "2027-01-01")
    monkeypatch.setattr(sm, "_default_issue_state", Stub(exc=AssertionError("network!")))
    text = susp_text(LINE + "\nSUSPENDED: lint\nSUSPENDED: types bogus")
    sm.cmd_census(sm.parse_suspensions(text), text=text)
    out = capsys.readouterr().out
    assert "Active suspensions: 1" in out
    assert "EXPIRED" in out and "MALFORMED" in out
    monkeypatch.setattr(sm, "_today", lambda: TODAY)
    sm.cmd_census(sm.parse_suspensions(susp_text()), text=susp_text())
    assert "not checked by census" in capsys.readouterr().out


def test_c10_auto_remove_never_removes_dep_mapper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for _ in range(99):
        sm.record_check("dep-mapper", True)
    text = susp_text()
    assert sm.cmd_auto_remove(text, sm.parse_suspensions(text)) == text


def test_c11_no_clock_or_file_override_flags(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sm", "--suspension-status", "dep-mapper", "--today", "x"])
    with pytest.raises(SystemExit) as exc:
        sm.main()
    assert exc.value.code == 2
    other = tmp_path / "other.md"
    other.write_text(susp_text("SUSPENDED: dep-mapper"))
    monkeypatch.setattr(
        sys, "argv", ["sm", "--suspension-status", "dep-mapper", "--suspension-file", str(other)]
    )
    assert sm.main() == 1  # real file absent; --suspension-file is ignored
    assert "STATUS=absent" in capsys.readouterr().out


def test_status_cli_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "contract").mkdir()
    path = tmp_path / "contract/gate-suspension.md"
    cases = [
        (LINE, TODAY, OPEN, 0, "active"),
        (LINE, "2027-01-01", OPEN, 3, "expired"),
        ("SUSPENDED: dep-mapper junk", TODAY, OPEN, 4, "malformed"),
        (LINE, TODAY, None, 5, "unknown"),
        ("SUSPENDED: lint", TODAY, OPEN, 1, "absent"),
    ]
    for line, today, state, code, name in cases:
        path.write_text(susp_text(line))
        monkeypatch.setattr(sm, "_today", lambda today=today: today)
        monkeypatch.setattr(
            sm, "_default_issue_state", Stub(state) if state else Stub(exc=OSError())
        )
        monkeypatch.setattr(sys, "argv", ["sm", "--suspension-status", "dep-mapper"])
        assert sm.main() == code
        out = capsys.readouterr().out
        assert f"STATUS={name}" in out and "GATE=dep-mapper" in out


def test_c12_shipped_suspension_file():
    path = REPO / "contract/gate-suspension.md"
    if not path.exists():
        pytest.skip("contract/gate-suspension.md is authored by the worker session")
    text = path.read_text()
    (s,) = [x for x in sm.parse_suspensions(text) if x.gate == "dep-mapper"]
    assert (s.expires, s.until_closed) == ("2026-12-31", 2162)
    assert sm._read_reason_category(str(path)) == "OTHER"
    assert (
        sm.suspension_status(text, "dep-mapper", today=TODAY, issue_state=Stub())["status"]
        == "active"
    )


def test_c13_reopened_issue_does_not_revive():
    assert status(stub=Stub(("open", None, ["completed"])))[0]["status"] == "expired"
    assert status(stub=Stub(("open", None, [None])))[0]["status"] == "expired"
    assert status(stub=Stub(("open", None, ["not_planned"])))[0]["status"] == "active"
    assert status(stub=Stub(exc=ListTruncatedError("trunc")))[0]["status"] == "unknown"


def test_default_issue_state_uses_github_helpers(monkeypatch):
    monkeypatch.setattr(merge_config, "resolve_repo_slug", lambda root: "o/r")
    monkeypatch.setattr(
        github, "get_issue", lambda o, r, n: {"state": "open", "state_reason": "reopened"}
    )
    monkeypatch.setattr(
        github,
        "list_issue_events",
        lambda o, r, n: [{"event": "closed", "state_reason": "completed"}, {"event": "labeled"}],
    )
    assert sm._default_issue_state(2162) == ("open", "reopened", ["completed"])
    monkeypatch.setattr(github, "get_issue", lambda o, r, n: None)
    with pytest.raises(LookupError):
        sm._default_issue_state(2162)


# ---------------------------------------------------------------------------
# (b) trace validator and resolution check
# ---------------------------------------------------------------------------


def validate(text, files=FILES):
    return sm.validate_dep_trace(text, STEP, BASE, HEAD, files)


def test_a3_valid_trace_validates():
    assert validate(make_trace(STEP, BASE, HEAD, FILES)) == {"valid": True, "errors": []}


def test_trace_coverage_boundaries_and_exemptions():
    good = make_trace(STEP, BASE, HEAD, ["bootstrap/a.md, bootstrap/overseer-cron-prompt.md"])
    files = ["bootstrap/a.md", "bootstrap/overseer-cron-prompt.md", "tests/x.py", "audit/y.json"]
    assert validate(good, files)["valid"]
    prefixed = make_trace(STEP, BASE, HEAD, ["xscripts/foo.py"])
    assert not validate(prefixed)["valid"]
    assert not validate(make_trace(STEP, BASE, HEAD, FILES), FILES + ["scripts/deleted.py"])[
        "valid"
    ]


def _mutations():
    t = make_trace(STEP, BASE, HEAD, FILES)
    return {
        "V1": t.replace("step s1", "step s9"),
        "V2": t.replace(f"Range: {BASE}", "Range: " + "c" * 40),
        "V3": t.replace("Data confidence: LOW", "Data confidence: HIGH"),
        "V4": t.replace("| Changed file", "| File"),
        "V5": make_trace(STEP, BASE, HEAD, ["other.py"]),
        "V6": make_trace(STEP, BASE, HEAD, FILES, result="fail"),
        "V6b": make_trace(STEP, BASE, HEAD, FILES, result="maybe"),
        "V7": t.replace("- wiring item X, checked by grep\n", ""),
        "V8": t.replace("Result: PASS", "Result: FAIL"),
    }


@pytest.mark.parametrize("code", ["V1", "V2", "V3", "V4", "V5", "V6", "V6b", "V7", "V8"])
def test_b2_each_trace_rule_violated_separately(code):
    res = validate(_mutations()[code])
    assert not res["valid"]
    assert any(e.startswith(code[:2] + ":") for e in res["errors"])


def test_b2_v4_empty_table_and_collects_all_errors():
    t = make_trace(STEP, BASE, HEAD, []).replace("Range: " + BASE, "Range: zzz")
    res = validate(t)
    assert any(e.startswith("V4") for e in res["errors"])
    assert any(e.startswith("V2") for e in res["errors"])
    assert any(e.startswith("V5") for e in res["errors"])


def test_a1_pure_ok():
    stub = Stub()
    res = run_check(issue_state=stub)
    assert res["applies"] and res["ok"], errors_of(res)
    assert stub.calls == [2162]


def test_not_applicable_without_findings():
    res = run_check(risk_text="# x\nbase_sha: a\nblocking_findings: []\n")
    assert res == {"applies": False, "ok": True, "findings": [], "errors": []}


def test_b1_trace_absent():
    res = run_check(read_text=lambda p: None)
    assert not res["ok"] and any("S5: manual trace absent" in e for e in errors_of(res))


def test_b3_disclosure_only_required_when_asked():
    assert run_check(handoff_text=None, require_disclosure=False)["ok"]
    assert not run_check(handoff_text=None, require_disclosure=True)["ok"]
    assert run_check(handoff_text=make_handoff(), require_disclosure=True)["ok"]
    for token in (
        "Data confidence: LOW",
        "contract/gate-suspension.md",
        "| Changed file",
        "Result: PASS",
        "dep-mapper-trace.md",
    ):
        res = run_check(handoff_text=make_handoff(drop=token), require_disclosure=True)
        assert not res["ok"], token
    no_heading = make_handoff().replace(
        "## dep-mapper LOW disclosure (suspended blocker)", "## other"
    )
    assert not run_check(handoff_text=no_heading, require_disclosure=True)["ok"]


@pytest.mark.parametrize(
    "kw",
    [{"tier": "CRITICAL"}, {"human_gate_required": True}],
)
def test_b4_human_gate_blocks(kw):
    res = run_check(**kw)
    assert not res["ok"] and any("S3" in e for e in errors_of(res))


def test_b5_non_dep_mapper_source_rejected():
    res = run_check(risk_text=make_risk(BASE, HEAD, source="risk-assessor"))
    assert not res["ok"] and any("S1" in e for e in errors_of(res))


def test_b6_non_convention_trace_path_rejected():
    res = run_check(
        risk_text=make_risk(BASE, HEAD, resolution="suspended: dep-mapper (trace: /tmp/x.md)")
    )
    assert not res["ok"] and any("S2" in e for e in errors_of(res))


def test_c14_closed_with_empty_history_follows_current_reason():
    res, _ = status(stub=Stub(("closed", "completed", [])))
    assert res["status"] == "expired" and "completed" in res["detail"]
    assert status(stub=Stub(("closed", "not_planned", [])))[0]["status"] == "active"


def test_c15_expires_only_line_never_calls_lookup():
    line = "SUSPENDED: dep-mapper expires: 2026-12-31"
    for today in ("2026-11-06", "2026-12-30", "2026-12-31"):
        res, stub = status(line=line, today=today)
        assert res["status"] == "active" and res["until_closed"] is None
        assert stub.calls == []
    res, stub = status(line=line, today="2027-01-01")
    assert res["status"] == "expired" and "2027-01-01" in res["detail"]
    assert stub.calls == []


def test_c16_until_closed_only_line_uses_lookup():
    line = "SUSPENDED: dep-mapper until-closed: #2162"
    res, stub = status(line=line, today="2099-01-01")  # no date: clock irrelevant
    assert res["status"] == "active" and res["expires"] is None
    assert stub.calls == [2162]
    res, _ = status(line=line, stub=Stub(("closed", "completed", ["completed"])))
    assert res["status"] == "expired"


def test_c17_day_before_expiry_is_active():
    res, stub = status(today="2026-12-30")
    assert res["status"] == "active" and res["detail"] == "active"
    assert stub.calls == [2162]


def test_b8_default_branch_guard():
    assert not run_check(main_suspension_text=None)["ok"]
    changed = susp_text("SUSPENDED: dep-mapper expires: 2027-12-31 until-closed: #2162")
    res = run_check(worktree_suspension_text=changed)
    assert not res["ok"] and any("modified on this branch" in e for e in errors_of(res))
    expired_main = run_check(today="2027-01-01")
    assert not expired_main["ok"] and any("expired" in e for e in errors_of(expired_main))


def test_b9_free_text_resolved_banned_for_dep_mapper():
    res = run_check(
        risk_text=make_risk(BASE, HEAD, resolution="resolved: suspended per gate-suspension.md")
    )
    assert res["applies"] and not res["ok"]
    assert any("S7" in e for e in errors_of(res))


def test_b10_parser_miss_is_a_failure():
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\nblocking_findings:\n"
        "stray_key: ends the block\n"
        "  - id: x\n    source: dep-mapper\n"
        f"    resolution: suspended: dep-mapper (trace: {sm.dep_trace_path(STEP)})\n"
    )
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"] and any("S0" in e for e in res["errors"])


def test_b11_validated_tier_rederived():
    for risk in (
        make_risk(BASE, HEAD, validated="CRITICAL"),
        make_risk(BASE, HEAD, validated=""),
        make_risk(BASE, HEAD, validated="bogus"),
    ):
        res = run_check(tier="HIGH", risk_text=risk)
        assert not res["ok"]
        assert any(e.startswith("S3:") for e in errors_of(res))


def test_b12_range_must_match():
    for over in ({"base_sha": "c" * 40}, {"head_sha": "c" * 40}):
        res = run_check(**over)
        assert not res["ok"]
        assert any(e.startswith("S0: risk-assessment range") for e in res["errors"])


def test_parse_blocking_findings_forms():
    assert sm.parse_blocking_findings("blocking_findings: []\n") == []
    assert sm.parse_blocking_findings("nothing here") == []
    (f,) = sm.parse_blocking_findings(make_risk(BASE, HEAD))
    assert f["id"] == "dep-low" and f["source"] == "dep-mapper"
    assert f["resolution"] == f"suspended: dep-mapper (trace: {sm.dep_trace_path(STEP)})"


# ---------------------------------------------------------------------------
# CLI + REQ-W-18 on a real tmp git repo
# ---------------------------------------------------------------------------


def _git(cwd, *args):
    subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _rev(cwd):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class _ReclaimingFactory:
    """tmp_path_factory.mktemp dirs live outside the test's own tmp_path, so pytest's
    tmp_path_retention_policy never reclaims them for passing tests and they pile up
    against the suite's tmp budget. Remove them on teardown regardless of outcome
    (failing-test debuggability is traded for the budget)."""

    def __init__(self, factory):
        self._factory = factory
        self.made = []

    def mktemp(self, basename, numbered=True):
        path = self._factory.mktemp(basename, numbered=numbered)
        self.made.append(path)
        return path


@pytest.fixture
def scratch_factory(tmp_path_factory):
    factory = _ReclaimingFactory(tmp_path_factory)
    yield factory
    for path in factory.made:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def repo(tmp_path, monkeypatch, scratch_factory):
    """base commit has the suspension file and is origin/main of a local bare origin whose
    HEAD is main; head adds scripts/foo.py. No test touches the network."""
    origin = scratch_factory.mktemp("origin") / "origin.git"
    _git(origin.parent, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract/gate-suspension.md").write_text(susp_text())
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _rev(tmp_path)
    _git(tmp_path, "remote", "add", "origin", str(origin))
    _git(tmp_path, "push", "-q", "origin", "main")
    _git(tmp_path, "fetch", "-q", "origin")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/foo.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_foo.py").write_text("y = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "head")
    head = _rev(tmp_path)
    oversight = tmp_path / ".claudetmp/oversight"
    (oversight / "validators").mkdir(parents=True)
    (oversight / "validators/risk-assessment.md").write_text(make_risk(base, head))
    (oversight / f"step{STEP}-dep-mapper-trace.md").write_text(make_trace(STEP, base, head, FILES))
    (oversight / f"step{STEP}-handoff.md").write_text(make_handoff())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sm, "_today", lambda: TODAY)
    monkeypatch.setattr(sm, "_default_issue_state", Stub())
    return SimpleNamespace(
        root=tmp_path,
        base=base,
        head=head,
        oversight=oversight,
        origin=origin,
        factory=scratch_factory,
    )


MANIFEST_TRUE = f"steps:\n  - id: {STEP}\n    human_gate_required: true\n"
MANIFEST_FALSE = f"steps:\n  - id: {STEP}\n    human_gate_required: false\n"
MANIFEST_PATH = "contract/step-manifest.yaml"


def regen(repo, base_manifest=None, head_manifest=None):
    """Rebuild the fixture history with the step manifest committed at base (which is also
    origin/main) and/or at head (None = absent there), then regenerate the assessment, trace
    and handoff for the new head. The working tree is left equal to head."""
    root = repo.root
    _git(root, "reset", "-q", "--hard", "HEAD~1")
    _git(root, "rm", "-q", "-f", "--ignore-unmatch", MANIFEST_PATH)
    (root / "contract").mkdir(exist_ok=True)
    if base_manifest is not None:
        (root / MANIFEST_PATH).write_text(base_manifest)
        _git(root, "add", MANIFEST_PATH)
    _git(root, "commit", "-q", "--allow-empty", "--amend", "-m", "base")
    repo.base = _rev(root)
    _git(root, "push", "-q", "--force", "origin", "main")
    _git(root, "fetch", "-q", "origin")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/foo.py").write_text("x = 1\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_foo.py").write_text("y = 1\n")
    if head_manifest is None:
        _git(root, "rm", "-q", "-f", "--ignore-unmatch", MANIFEST_PATH)
    else:
        (root / MANIFEST_PATH).write_text(head_manifest)
    _git(root, "add", "scripts", "tests", "contract")
    _git(root, "commit", "-q", "--allow-empty", "-m", "head")
    repo.head = _rev(root)
    (repo.oversight / "validators/risk-assessment.md").write_text(make_risk(repo.base, repo.head))
    (repo.oversight / f"step{STEP}-dep-mapper-trace.md").write_text(
        make_trace(STEP, repo.base, repo.head, FILES)
    )


def cli(
    monkeypatch,
    capsys,
    repo,
    *extra,
    step=STEP,
    tier=("--tier", "HIGH"),
    gate=("--human-gate-required", "false"),
):
    argv = [
        "sm",
        "--check-suspended-resolutions",
        step,
        "--range",
        f"{repo.base}..{repo.head}",
        *tier,
        *gate,
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    code = sm.main()
    return code, capsys.readouterr().out


def test_a1_cli_exit_zero(repo, monkeypatch, capsys):
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 0, out
    assert "APPLIES=yes" in out and "RESULT=ok" in out


def test_c7_cli_fails_once_expired(repo, monkeypatch, capsys):
    monkeypatch.setattr(sm, "_today", lambda: "2027-01-01")
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "RESULT=fail" in out and "ERROR=dep-low: S4" in out


def test_b7_cli_requires_tier_and_gate_flag(repo, monkeypatch, capsys):
    assert cli(monkeypatch, capsys, repo, tier=())[0] == 2
    assert cli(monkeypatch, capsys, repo, gate=())[0] == 2
    assert cli(monkeypatch, capsys, repo, tier=("--tier", "bogus"))[0] == 2


def test_cli_missing_risk_assessment_is_usage_error(repo, monkeypatch, capsys):
    (repo.oversight / "validators/risk-assessment.md").unlink()
    assert cli(monkeypatch, capsys, repo)[0] == 2


def test_cli_bad_range_git_failure_exit_2(repo, monkeypatch, capsys):
    repo.base = "deadbeef" * 5
    code, _ = cli(monkeypatch, capsys, repo)
    assert code == 2
    # the failure is the git-range failure, not a usage error
    argv = ["sm", "--check-suspended-resolutions", STEP, "--range", f"{repo.base}..{repo.head}"]
    monkeypatch.setattr(sys, "argv", argv + ["--tier", "HIGH", "--human-gate-required", "false"])
    assert sm.main() == 2
    assert f"git diff --name-only {repo.base}..{repo.head} failed" in capsys.readouterr().err


def test_cli_not_applicable_exit_zero(repo, monkeypatch, capsys):
    (repo.oversight / "validators/risk-assessment.md").write_text("# R\nblocking_findings: []\n")
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 0 and "APPLIES=no" in out


def test_b8_cli_no_default_branch_blob_exit_4(repo, monkeypatch, capsys):
    _git(repo.root, "update-ref", "-d", "refs/remotes/origin/main")
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "S4" in out


def test_b11_cli_manifest_flag_cannot_be_lowered(repo, monkeypatch, capsys):
    regen(repo, base_manifest=MANIFEST_TRUE, head_manifest=MANIFEST_TRUE)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "S3: step is behind the human gate" in out


def test_cli_require_disclosure(repo, monkeypatch, capsys):
    assert cli(monkeypatch, capsys, repo, "--require-disclosure")[0] == 0
    (repo.oversight / f"step{STEP}-handoff.md").unlink()
    assert cli(monkeypatch, capsys, repo, "--require-disclosure")[0] == 4
    assert cli(monkeypatch, capsys, repo)[0] == 0  # evaluator mode


def test_validate_dep_trace_cli(repo, monkeypatch, capsys):
    argv = ["sm", "--validate-dep-trace", STEP, "--range", f"{repo.base}..{repo.head}"]
    monkeypatch.setattr(sys, "argv", argv)
    assert sm.main() == 0
    assert "TRACE=valid" in capsys.readouterr().out
    trace = repo.oversight / f"step{STEP}-dep-mapper-trace.md"
    trace.write_text(make_trace(STEP, repo.base, repo.head, FILES, result="fail"))
    assert sm.main() == 4
    assert "TRACE=invalid" in capsys.readouterr().out
    trace.unlink()
    assert sm.main() == 1
    assert "TRACE=absent" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["sm", "--validate-dep-trace", STEP])
    assert sm.main() == 2


def req_w18(repo):
    return pr_readiness._check_dep_mapper_suspension(repo.root, STEP, repo.base, repo.head, "HIGH")


@pytest.fixture
def use_sm(monkeypatch):
    monkeypatch.setattr(pr_readiness, "_load_suspension_manager", lambda: sm)


def test_a2_req_w18_pass(repo, use_sm):
    res = req_w18(repo)
    assert res.check_id == "REQ-W-18" and res.passed, res.detail


def test_req_w18_not_applicable_cases(repo, use_sm):
    (repo.oversight / "validators/risk-assessment.md").write_text("# R\nblocking_findings: []\n")
    assert req_w18(repo).passed
    (repo.oversight / "validators/risk-assessment.md").unlink()
    assert req_w18(repo).passed


def test_b1_req_w18_trace_absent_fails(repo, use_sm):
    (repo.oversight / f"step{STEP}-dep-mapper-trace.md").unlink()
    res = req_w18(repo)
    assert not res.passed and "S5" in res.detail


def test_b3_req_w18_disclosure_missing_fails(repo, use_sm):
    (repo.oversight / f"step{STEP}-handoff.md").write_text("no disclosure\n")
    res = req_w18(repo)
    assert not res.passed and "S6" in res.detail


def test_req_w18_bad_git_range_fails(repo, use_sm):
    repo.base = "deadbeef" * 5
    res = req_w18(repo)
    assert not res.passed
    assert res.detail == f"git diff --name-only {repo.base}..{repo.head} failed"


def test_req_w18_load_failure_fails_closed(repo, monkeypatch):
    def boom():
        raise ImportError("nope")

    monkeypatch.setattr(pr_readiness, "_load_suspension_manager", boom)
    res = req_w18(repo)
    assert not res.passed and "cannot load" in res.detail


def test_req_w18_manifest_flag_and_tier_floor(repo, use_sm):
    regen(repo, base_manifest=MANIFEST_TRUE, head_manifest=MANIFEST_TRUE)
    assert "S3: step is behind the human gate" in req_w18(repo).detail
    regen(repo)
    assert req_w18(repo).passed
    res = pr_readiness._check_dep_mapper_suspension(
        repo.root, STEP, repo.base, repo.head, "CRITICAL"
    )
    assert not res.passed and "S3: step is behind the human gate" in res.detail


def test_a4_req_w18_passes_no_overrides(repo, use_sm, monkeypatch):
    clock, lookup = [], []
    monkeypatch.setattr(sm, "_today", lambda: clock.append(1) or "2027-06-01")
    monkeypatch.setattr(sm, "_default_issue_state", lambda n, root=".": lookup.append(n) or OPEN)
    real_ls, remote = sm._default_ls_remote, []
    monkeypatch.setattr(
        sm, "_default_ls_remote", lambda root=".": remote.append(1) or real_ls(root)
    )
    res = req_w18(repo)
    assert remote, "the production origin lookup was not used"
    assert clock, "the production clock was not used"
    # the sentinel clock says 2027-06-01, so a real (un-overridden) check must fail as expired
    assert not res.passed and "expired" in res.detail
    # the date is checked first, so the lookup is skipped; prove it is wired in a second pass
    monkeypatch.setattr(sm, "_today", lambda: clock.append(1) or TODAY)
    assert req_w18(repo).passed
    assert lookup == [2162]


def test_req_w18_runs_in_assess_pr_readiness(repo, use_sm, monkeypatch):
    monkeypatch.setattr(
        pr_readiness,
        "_check_inner_loop_tests",
        lambda root: pr_readiness.CheckResult("REQ-W-01", True, "stub"),
    )
    result = pr_readiness.assess_pr_readiness(
        "cid", repo.base, repo.head, STEP, "HIGH", repo_root=repo.root, write_state=False
    )
    assert "REQ-W-18" in [c.check_id for c in result.checks]
    assert [c for c in result.checks if c.check_id == "REQ-W-18"][0].passed


# ---------------------------------------------------------------------------
# code-review round 1 fixes
# ---------------------------------------------------------------------------


def test_rename_requires_old_and_new_path(repo):
    _git(repo.root, "mv", "scripts/foo.py", "scripts/bar.py")
    _git(repo.root, "commit", "-q", "-m", "rename")
    changed = sm.changed_files_in_range(repo.head, _rev(repo.root), repo.root)
    assert sorted(changed) == ["scripts/bar.py", "scripts/foo.py"]


def test_changed_files_non_ascii_path_is_unquoted(repo):
    (repo.root / "scripts/café.py").write_text("z = 1\n")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-q", "-m", "unicode")
    changed = sm.changed_files_in_range(repo.head, _rev(repo.root), repo.root)
    assert "scripts/café.py" in changed


def test_changed_files_refuses_option_shaped_revision(repo):
    assert sm.changed_files_in_range("--output=x", repo.head, repo.root) is None


@pytest.mark.parametrize("cmd", ["--check-suspended-resolutions", "--validate-dep-trace"])
def test_option_shaped_range_is_usage_error(repo, monkeypatch, cmd):
    argv = ["sm", cmd, STEP, "--range=--output=x..y"]
    if cmd == "--check-suspended-resolutions":
        argv += ["--tier", "HIGH", "--human-gate-required", "false"]
    monkeypatch.setattr(sys, "argv", argv)
    assert sm.main() == 2


def test_default_issue_state_resolves_slug_from_repo_root(monkeypatch):
    seen = []
    monkeypatch.setattr(merge_config, "resolve_repo_slug", lambda root: seen.append(root) or "o/r")
    monkeypatch.setattr(github, "get_issue", lambda o, r, n: {"state": "open"})
    monkeypatch.setattr(github, "list_issue_events", lambda o, r, n: [])
    sm._default_issue_state(2162, "/some/root")
    assert seen == ["/some/root"]


def test_suspension_status_threads_repo_root_to_default_lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(sm, "_default_issue_state", lambda n, root=".": calls.append(root) or OPEN)
    sm.suspension_status(susp_text(), "dep-mapper", today=TODAY, repo_root="/r")
    sm.suspension_status(susp_text(), "dep-mapper", today=TODAY)
    assert calls == ["/r", "."]


def test_req_w18_no_finding_with_broken_range_passes(repo, use_sm):
    (repo.oversight / "validators/risk-assessment.md").write_text("# R\nblocking_findings: []\n")
    assert pr_readiness._check_dep_mapper_suspension(
        repo.root,
        STEP,
        "deadbeef" * 5,
        repo.head,
        "HIGH",
    ).passed


def test_req_w18_unresolved_dep_finding_message_is_not_suspension(repo, use_sm):
    risk = make_risk(repo.base, repo.head, resolution="unresolved")
    (repo.oversight / "validators/risk-assessment.md").write_text(risk)
    res = req_w18(repo)
    assert res.passed
    assert "resolved by active suspension" not in res.detail
    assert "no suspended dep-mapper resolution" in res.detail


@pytest.mark.parametrize("resolution", ["waived", "n/a", "resolved: fine", "escalated:", "other"])
def test_s7_rejects_any_other_dep_mapper_resolution(resolution):
    res = run_check(risk_text=make_risk(BASE, HEAD, resolution=resolution))
    assert res["applies"] and not res["ok"]
    assert any("S7" in e for e in errors_of(res))


@pytest.mark.parametrize("resolution", ["unresolved", "escalated: audit/x.md"])
def test_s7_allows_unresolved_and_escalated(resolution):
    res = run_check(risk_text=make_risk(BASE, HEAD, resolution=resolution))
    assert res["applies"] and res["ok"]


def test_column0_comment_does_not_end_findings_block():
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\nblocking_findings:\n"
        "  - id: a\n    source: security\n    resolution: fixed\n"
        "# column-0 comment\n\n"
        "  - id: dep\n    source: dep-mapper\n    resolution: resolved: nope\n"
    )
    assert [f["id"] for f in sm.parse_blocking_findings(risk)] == ["a", "dep"]
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"] and any("S7" in e for e in errors_of(res))


def test_unattributed_dep_mapper_source_line_fails_closed():
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\nblocking_findings:\n"
        "stray_key: ends the block\n"
        "  - id: dep\n    source: dep-mapper\n    resolution: waived\n"
    )
    assert sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"]
    assert any("S0" in e and "source: dep-mapper" in e for e in res["errors"])


@pytest.mark.parametrize("base,head", [(BASE, "HEAD"), (BASE, "main"), ("abc1234", HEAD)])
def test_symbolic_or_short_sha_fails(base, head):
    risk = make_risk(base, head)
    res = run_check(risk_text=risk, base_sha=base, head_sha=head)
    assert res["applies"] and not res["ok"]
    assert any("40-hex" in e for e in res["errors"])


@pytest.mark.parametrize("head", ["HEAD", "abc1234"])
def test_req_w18_rejects_non_full_sha(repo, use_sm, head):
    res = pr_readiness._check_dep_mapper_suspension(repo.root, STEP, repo.base, head, "HIGH")
    assert not res.passed and "40-hex" in res.detail


def test_cli_range_requires_full_sha(repo, monkeypatch, capsys):
    repo.base = repo.base[:12]
    assert cli(monkeypatch, capsys, repo)[0] == 2


def _manifest(tmp_path, body):
    path = tmp_path / "step-manifest.yaml"
    path.write_text(body)
    return path


M_INLINE_COMMENT = "steps:\n  - id: s1 # note\n    human_gate_required: true\n"
M_QUOTED_ID = "steps:\n  - id: 's1'\n    human_gate_required: false # ok\n"
M_ID_AFTER_KEY = (
    "steps:\n  - name: x\n    human_gate_required: true\n    id: s1\n"
    "  - name: y\n    id: s2\n    human_gate_required: false\n"
)
M_FLAG_LEAK = "steps:\n  - id: s1\n    human_gate_required: true\n  - id: s2\n    name: y\n"
M_NESTED_LIST = (
    "steps:\n  - id: s1\n    required_signoffs:\n      - code-review\n"
    "    human_gate_required: true\n"
)
M_STEP_MISSING = "steps:\n  - id: other\n    human_gate_required: false\n"
M_NO_STEPS = "foo: bar\n"
M_GARBAGE_FLAG = "steps:\n  - id: s1\n    human_gate_required: maybe\n"
M_QUOTED_KEY_TRUE = 'steps:\n  - id: s1\n    "human_gate_required": true\n'
M_QUOTED_KEY_FALSE = "steps:\n  - id: s1\n    'human_gate_required': false\n"
M_NONCANONICAL = [
    "base: &b\n  human_gate_required: false\nsteps:\n  - id: s1\n    <<: *b\n",
    "steps:\n  - id: s1\n    human_gate_required: &g true\n",
    "steps:\n  - id: s1\n    human_gate_required: *g\n",
    "steps:\n  - {id: s1, human_gate_required: true}\n",
    "steps:\n  - id: s1\n    meta: {human_gate_required: true}\n",
    "steps:\n  - id: s1\n    human_gate_required: false\n    human_gate_required: true\n",
    "steps:\n  - id: s1\n    gates:\n      human_gate_required: true\n",
]
M_FLOW_SIGNOFFS = "steps:\n  - id: s1\n    required_signoffs: [code-review, security]\n"
# (text, step) for every test_manifest_* fixture; the tests and the T-G19 oracle both read this.
MANIFEST_FIXTURES = [
    (M_INLINE_COMMENT, "s1"),
    (M_QUOTED_ID, "s1"),
    (M_ID_AFTER_KEY, "s1"),
    (M_ID_AFTER_KEY, "s2"),
    (M_FLAG_LEAK, "s2"),
    (M_NESTED_LIST, "s1"),
    (M_STEP_MISSING, "s1"),
    (M_NO_STEPS, "s1"),
    (M_GARBAGE_FLAG, "s1"),
    (M_QUOTED_KEY_TRUE, "s1"),
    (M_QUOTED_KEY_FALSE, "s1"),
    *[(body, "s1") for body in M_NONCANONICAL],
    (M_FLOW_SIGNOFFS, "s1"),
]


def test_manifest_inline_comment_on_id_still_matches(tmp_path):
    m = _manifest(tmp_path, M_INLINE_COMMENT)
    assert sm.manifest_human_gate_required(m, "s1") is True


def test_manifest_quoted_id_and_flag_comment(tmp_path):
    m = _manifest(tmp_path, M_QUOTED_ID)
    assert sm.manifest_human_gate_required(m, "s1") is False


def test_manifest_id_after_another_key_is_found(tmp_path):
    m = _manifest(tmp_path, M_ID_AFTER_KEY)
    assert sm.manifest_human_gate_required(m, "s1") is True
    assert sm.manifest_human_gate_required(m, "s2") is False


def test_manifest_flag_does_not_leak_to_next_item(tmp_path):
    m = _manifest(tmp_path, M_FLAG_LEAK)
    assert sm.manifest_human_gate_required(m, "s2") is False


def test_manifest_nested_list_does_not_start_a_new_item(tmp_path):
    assert sm.manifest_human_gate_required(_manifest(tmp_path, M_NESTED_LIST), "s1") is True


def test_manifest_step_missing_fails_closed(tmp_path):
    m = _manifest(tmp_path, M_STEP_MISSING)
    assert sm.manifest_human_gate_required(m, "s1") is True


def test_manifest_without_steps_block_fails_closed(tmp_path):
    assert sm.manifest_human_gate_required(_manifest(tmp_path, M_NO_STEPS), "s1") is True


def test_manifest_garbage_flag_fails_closed(tmp_path):
    m = _manifest(tmp_path, M_GARBAGE_FLAG)
    assert sm.manifest_human_gate_required(m, "s1") is True


def test_manifest_absent_is_false(tmp_path):
    assert sm.manifest_human_gate_required(tmp_path / "nope.yaml", "s1") is False


def test_manifest_undecodable_fails_closed(tmp_path):
    path = tmp_path / "step-manifest.yaml"
    path.write_bytes(b"steps:\n  - id: s1\n\xff\xfe\n")
    assert sm.manifest_human_gate_required(path, "s1") is True


@pytest.mark.parametrize("resolution_line", ["", "    resolution:\n", "    resolution: # note\n"])
def test_s7_empty_or_missing_resolution_fails(resolution_line):
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\nblocking_findings:\n"
        "  - id: dep\n    source: dep-mapper\n" + resolution_line
    )
    assert sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"] and any("S7" in e for e in errors_of(res))


# ---------------------------------------------------------------------------
# revision 4: canonical form or fail closed
# ---------------------------------------------------------------------------


def _risk(findings, header=None):
    head = (
        header
        if header is not None
        else (f"validated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n")
    )
    return f"# R\n{head}\nblocking_findings:\n{findings}\n## Body\n"


def test_quoted_source_with_resolved_is_s7():
    risk = _risk('  - id: dep\n    "source": "dep-mapper"\n    "resolution": "resolved: ok"\n')
    assert [f["source"] for f in sm.parse_blocking_findings(risk)] == ["dep-mapper"]
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"] and any("S7" in e for e in errors_of(res))


def test_quoted_suspended_resolution_is_validated():
    risk = _risk(
        "  - id: dep\n    source: dep-mapper\n"
        f'    "resolution": "suspended: dep-mapper (trace: {sm.dep_trace_path(STEP)})"\n'
    )
    res = run_check(risk_text=risk)
    assert res["applies"] and res["ok"]
    bad = _risk(
        "  - id: dep\n    source: security\n"
        f'    "resolution": "suspended: dep-mapper (trace: {sm.dep_trace_path(STEP)})"\n'
    )
    res = run_check(risk_text=bad)
    assert res["applies"] and not res["ok"]


def test_unattributed_quoted_lines_fail_closed():
    risk = _risk(
        "stray_key: x\n  - id: dep\n    'source': 'dep-mapper'\n"
        '    "resolution": "suspended: dep-mapper"\n'
    )
    assert sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert not res["ok"] and sum("S0" in e for e in res["errors"]) >= 2


def test_body_validated_tier_does_not_override_header():
    risk = _risk("  - id: dep\n    source: dep-mapper\n    resolution: unresolved\n")
    risk += "validated_tier: LOW\n"
    assert sm._header_fields(risk)[0]["validated_tier"] == "HIGH"
    risk = _risk(
        f"  - id: dep\n    source: dep-mapper\n    resolution: suspended: dep-mapper "
        f"(trace: {sm.dep_trace_path(STEP)})\n",
        header=f"base_sha: {BASE}\nhead_sha: {HEAD}\n",
    )
    risk += "validated_tier: LOW\n"
    assert not run_check(risk_text=risk)["ok"]  # absent header tier -> CRITICAL


def test_duplicate_header_key_fails():
    header = f"validated_tier: HIGH\nvalidated_tier: LOW\nbase_sha: {BASE}\nhead_sha: {HEAD}\n"
    res = run_check(risk_text=make_risk(BASE, HEAD).replace("validated_tier: HIGH\n", header, 1))
    assert not res["ok"] and any("duplicate header key" in e for e in res["errors"])


def test_quoted_header_values_are_normalised():
    risk = make_risk(BASE, HEAD).replace(f"base_sha: {BASE}", f"base_sha: '{BASE}' # c")
    assert run_check(risk_text=risk)["ok"]


def test_manifest_quoted_human_gate_key_is_read(tmp_path):
    m = _manifest(tmp_path, M_QUOTED_KEY_TRUE)
    assert sm.manifest_human_gate_required(m, "s1") is True
    m = _manifest(tmp_path, M_QUOTED_KEY_FALSE)
    assert sm.manifest_human_gate_required(m, "s1") is False


@pytest.mark.parametrize(
    "body",
    M_NONCANONICAL,
    ids=["merge", "anchor", "alias", "flow-item", "flow-value", "duplicate", "nested"],
)
def test_manifest_noncanonical_forms_fail_closed(tmp_path, body):
    assert sm.manifest_human_gate_required(_manifest(tmp_path, body), "s1") is True


def test_manifest_flow_sequence_of_signoffs_is_fine(tmp_path):
    assert sm.manifest_human_gate_required(_manifest(tmp_path, M_FLOW_SIGNOFFS), "s1") is False


# ---------------------------------------------------------------------------
# #2349: the disclosure must match the validated trace and the suspension
# ---------------------------------------------------------------------------


def disc(handoff, trace=None, susp=None):
    return sm.validate_disclosure(
        handoff,
        STEP,
        trace if trace is not None else make_trace(STEP, BASE, HEAD, FILES),
        susp if susp is not None else susp_text(),
    )


def _errs(res):
    return " | ".join(res["errors"])


def test_2349_faithful_disclosure_passes():
    assert disc(make_handoff())["valid"]


def test_2349_altered_row_result_fails():
    h = make_handoff().replace("| pass |", "| no impact |")
    assert "omits or alters" in _errs(disc(h))


def test_2349_omitted_row_fails():
    trace = make_trace(STEP, BASE, HEAD, FILES + ["scripts/bar.py"])
    res = disc(make_handoff(), trace=trace)
    assert not res["valid"] and "scripts/bar.py" in _errs(res)


def test_2349_extra_row_fails():
    h = make_handoff().replace(
        "| scripts/foo.py | callers | grep | pass |",
        "| scripts/foo.py | callers | grep | pass |\n| scripts/x.py | c | g | pass |",
    )
    assert "not in the trace" in _errs(disc(h))


def test_2349_reordered_rows_fail():
    files = FILES + ["scripts/bar.py"]
    trace = make_trace(STEP, BASE, HEAD, files)
    a, b = (f"| {f} | callers | grep | pass |" for f in files)
    h = make_handoff().replace(a, f"{b}\n{a}")
    res = disc(h, trace=trace)
    assert not res["valid"] and "order" in _errs(res)


def test_2349_header_differs_fails():
    h = make_handoff().replace("| Changed file | Callers / readers |", "| Changed file | Notes |")
    assert "header differs" in _errs(disc(h))


def test_2349_untraced_item_omitted_fails():
    h = make_handoff().replace("- wiring item X, checked by grep\n", "")
    assert "omits untraced item" in _errs(disc(h))


def test_2349_authorizer_with_appended_text_fails():
    h = make_handoff().replace("Authorized by: Test Human;", "Authorized by: Test Human and a bot;")
    assert "Authorized by: Test Human" in _errs(disc(h))


def test_2349_extra_conflicting_authorizer_fails():
    h = make_handoff().replace("Result: PASS", "Authorized by: Someone Else\nResult: PASS")
    assert "Authorized by: Test Human" in _errs(disc(h))


def test_2349_wrong_authorizer_fails():
    h = make_handoff().replace("Authorized by: Test Human", "Authorized by: Someone Else")
    assert "Authorized by: Test Human" in _errs(disc(h))


@pytest.mark.parametrize(
    "old,new",
    [
        ("expires: 2026-12-31", "expires: 2099-01-01"),
        ("until-closed: issue 2162", "until-closed: none"),
    ],
)
def test_2349_wrong_expiry_or_until_closed_fails(old, new):
    assert not disc(make_handoff().replace(old, new))["valid"]


def test_2349_extra_conflicting_expiry_fails():
    h = make_handoff().replace("Result: PASS", "expires: 2099-01-01\nResult: PASS")
    assert "disclosed expiry" in _errs(disc(h))


def test_2349_no_trace_or_suspension_fails_closed():
    assert not sm.validate_disclosure(make_handoff(), STEP, "", susp_text())["valid"]
    assert not sm.validate_disclosure(
        make_handoff(), STEP, make_trace(STEP, BASE, HEAD, FILES), ""
    )["valid"]


def test_2349_check_path_rejects_tampered_disclosure():
    h = make_handoff().replace("| pass |", "| no impact |")
    res = run_check(handoff_text=h, require_disclosure=True)
    assert not res["ok"] and any("S6:" in e for e in errors_of(res))


# ---------------------------------------------------------------------------
# revision 5: flow-style findings and un-anchored raw detection
# ---------------------------------------------------------------------------


def _flow_risk(base, head, item):
    return (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {base}\nhead_sha: {head}\n\n"
        f"blocking_findings:\n  - {item}\n\n## Body\n"
    )


def _codex_item():
    return (
        '{id: dep-low, source: dep-mapper, resolution: "suspended: dep-mapper '
        f'(trace: {sm.dep_trace_path(STEP)})"}}'
    )


def test_flow_mapping_finding_fails_closed_pure():
    risk = _flow_risk(BASE, HEAD, _codex_item())
    assert sm.has_flow_findings(risk) and sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"]
    assert any("flow-style" in e for e in res["errors"])


def test_flow_mapping_finding_fails_req_w18(repo, use_sm):
    (repo.oversight / "validators/risk-assessment.md").write_text(
        _flow_risk(repo.base, repo.head, _codex_item())
    )
    res = req_w18(repo)
    assert not res.passed and "flow-style" in res.detail


def test_flow_mapping_with_resolved_fails():
    risk = _flow_risk(BASE, HEAD, "{id: d, source: dep-mapper, resolution: 'resolved: ok'}")
    res = run_check(risk_text=risk)
    assert res["applies"] and not res["ok"]


def test_inline_flow_value_fails():
    risk = _flow_risk(BASE, HEAD, "id: d\n    source: dep-mapper\n    resolution: [unresolved]")
    assert sm.has_flow_findings(risk)
    assert not run_check(risk_text=risk)["ok"]


def test_inline_nonempty_blocking_findings_collection_fails():
    risk = f"# R\nbase_sha: {BASE}\nhead_sha: {HEAD}\nblocking_findings: [{{source: dep-mapper}}]\n"
    assert sm.suspension_applies(risk) and not run_check(risk_text=risk)["ok"]


def test_unanchored_token_mismatch_fails_even_without_flow_block():
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\n"
        "blocking_findings:\n  - id: a\n    source: security\n    resolution: fixed\n\n"
        '## Body\nsmuggled: {source: "Dep-Mapper", resolution: "suspended: x"}\n'
    )
    assert sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert not res["ok"] and sum("S0" in e for e in res["errors"]) >= 2


def test_empty_blocking_findings_still_passes():
    risk = f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\nblocking_findings: []\n"
    assert sm.parse_blocking_findings(risk) == []
    assert not sm.has_flow_findings(risk) and not sm.suspension_applies(risk)
    res = run_check(risk_text=risk)
    assert not res["applies"] and res["ok"]


def test_commented_template_example_is_not_counted():
    risk = (
        f"# R\nvalidated_tier: HIGH\nbase_sha: {BASE}\nhead_sha: {HEAD}\n\nblocking_findings: []\n"
        "  #   - id: x\n  #     source: dep-mapper\n"
        "  #     resolution: suspended: dep-mapper (trace: t)\n"
    )
    assert not sm.suspension_applies(risk)
    assert not run_check(risk_text=risk)["applies"]


def test_2349_until_closed_none_and_expires_none_match():
    s = susp_text("SUSPENDED: dep-mapper expires: 2026-12-31")
    h = make_handoff().replace("until-closed: issue 2162", "until-closed: none")
    assert disc(h, susp=s)["valid"]
    assert not disc(make_handoff(), susp=s)["valid"]
    s2 = susp_text("SUSPENDED: dep-mapper until-closed: #2162")
    h2 = make_handoff().replace("expires: 2026-12-31", "expires: none")
    assert disc(h2, susp=s2)["valid"]
    assert not disc(make_handoff(), susp=s2)["valid"]


@pytest.mark.parametrize(
    "old", ["Authorized by: Test Human; ", "expires: 2026-12-31; ", "until-closed: issue 2162"]
)
def test_2349_absent_authorizer_expiry_or_until_closed_fails(old):
    assert not disc(make_handoff().replace(old, ""))["valid"]


def test_2349_suspension_line_count_must_be_one():
    assert "line not found" in _errs(disc(make_handoff(), susp=susp_text("")))
    two = LINE + "\nSUSPENDED: dep-mapper expires: 2026-12-31 until-closed: #2162"
    assert "line not found" in _errs(disc(make_handoff(), susp=susp_text(two)))
    no_auth = "## Currently suspended\n\n" + LINE + "\n"
    assert "line not found" in _errs(disc(make_handoff(), susp=no_auth))


def test_2349_other_gate_suspension_line_is_ignored():
    other = LINE + "\nSUSPENDED: other-gate expires: 2099-01-01 until-closed: #9"
    assert disc(make_handoff(), susp=susp_text(other))["valid"]


@pytest.mark.parametrize("token", ["Data confidence: LOW", "contract/gate-suspension.md"])
def test_2349_marker_tokens_required(token):
    h = make_handoff().replace(token, "REDACTED")
    assert token in _errs(disc(h))


def test_2349_result_pass_must_be_whole_line():
    h = make_handoff().replace("Result: PASS", "Result: PASSED later")
    assert "Result: PASS'" in _errs(disc(h))


def test_2349_duplicate_rows_count_must_match():
    row = "| scripts/foo.py | callers | grep | pass |"
    assert "order or count" in _errs(disc(make_handoff().replace(row, row + "\n" + row)))
    t = make_trace(STEP, BASE, HEAD, FILES + FILES)
    assert "order or count" in _errs(disc(make_handoff(), trace=t))


def test_2349_header_missing_or_table_absent_fails():
    h = make_handoff().replace(
        "| Changed file | Callers / readers | Check | Result |\n|---|---|---|---|\n", ""
    )
    assert "header differs" in _errs(disc(h))


def test_2349_trace_without_rows_fails_closed():
    t = make_trace(STEP, BASE, HEAD, [])
    assert "cannot be compared" in _errs(disc(make_handoff(), trace=t))


def test_2349_untraced_whitespace_normalised_blank_ignored_and_empty_section_ok():
    t = make_trace(STEP, BASE, HEAD, FILES).replace(
        "- wiring item X, checked by grep\n", "- wiring   item X,  checked by grep\n\n\n"
    )
    assert disc(make_handoff(), trace=t)["valid"]
    h = make_handoff().replace(
        "- wiring item X, checked by grep", "- wiring item X,   checked  by grep"
    )
    assert disc(h)["valid"]
    empty = make_trace(STEP, BASE, HEAD, FILES).replace("- wiring item X, checked by grep\n", "")
    assert disc(make_handoff().replace("- wiring item X, checked by grep\n", ""), trace=empty)[
        "valid"
    ]
    nosec = empty.replace("## Items dep-mapper left untraced\n\n", "")
    # a trace with no Items section discloses nothing: the standard bullet is an extra line
    assert "not in the trace" in _errs(disc(make_handoff(), trace=nosec))


def test_2349_cell_whitespace_is_normalised():
    h = make_handoff().replace("| callers | grep |", "|  callers   |  grep |")
    assert disc(h)["valid"]


def test_2349_extra_conflicting_until_closed_fails():
    h = make_handoff().replace("Result: PASS", "until-closed: issue 9999\nResult: PASS")
    assert "disclosed until-closed" in _errs(disc(h))


def test_2349_comment_hiding_one_row_still_fails():
    h = make_handoff().replace(
        "| scripts/foo.py | callers | grep | pass |",
        "<!-- | scripts/foo.py | callers | grep | pass | -->",
    )
    assert not disc(h)["valid"]


# ---------------------------------------------------------------------------
# REQ-W-18 / _load_suspension_manager: exact ids, messages and caching (#2214)
# ---------------------------------------------------------------------------


def _fake_sm(**over):
    base = dict(
        suspension_applies=lambda text: True,
        is_full_sha=lambda s: True,
        changed_files_in_range=lambda b, h, root: ["f"],
    )
    base.update(over)
    return SimpleNamespace(**base)


def _w18(tmp_path, monkeypatch, fake, risk_text="risk", base=BASE, head=HEAD):
    monkeypatch.setattr(pr_readiness, "_load_suspension_manager", lambda: fake)
    monkeypatch.setattr(pr_readiness, "_read_text", lambda path: risk_text)
    return pr_readiness._check_dep_mapper_suspension(tmp_path, STEP, base, head, "HIGH")


def test_req_w18_absent_risk_assessment_is_not_applicable(tmp_path, monkeypatch):
    res = _w18(tmp_path, monkeypatch, _fake_sm(), risk_text=None)
    assert res.check_id == "REQ-W-18" and res.passed
    assert res.detail == "not applicable; REQ-W-04 owns risk-assessment absence"


def test_req_w18_no_suspension_passes_with_id(tmp_path, monkeypatch):
    res = _w18(tmp_path, monkeypatch, _fake_sm(suspension_applies=lambda t: False))
    assert res.check_id == "REQ-W-18" and res.passed
    assert res.detail == "no suspended dep-mapper resolution"


@pytest.mark.parametrize("bad", ["base", "head"])
def test_req_w18_non_full_sha_fails_with_message(tmp_path, monkeypatch, bad):
    bad_sha = "abc1234"
    fake = _fake_sm(is_full_sha=lambda s: s != bad_sha)
    kwargs = {bad: bad_sha}
    res = _w18(tmp_path, monkeypatch, fake, **kwargs)
    assert res.check_id == "REQ-W-18" and not res.passed
    b, h = (bad_sha, HEAD) if bad == "base" else (BASE, bad_sha)
    assert res.detail == f"base/head must be full 40-hex SHAs, got {b!r}..{h!r}"


def test_req_w18_changed_files_none_fails(tmp_path, monkeypatch):
    fake = _fake_sm(changed_files_in_range=lambda b, h, root: None)
    res = _w18(tmp_path, monkeypatch, fake)
    assert res.check_id == "REQ-W-18" and not res.passed
    assert res.detail == f"git diff --name-only {BASE}..{HEAD} failed"


def test_req_w18_load_failure_has_id_and_message(tmp_path, monkeypatch):
    def boom():
        raise ImportError("nope")

    monkeypatch.setattr(pr_readiness, "_load_suspension_manager", boom)
    res = pr_readiness._check_dep_mapper_suspension(tmp_path, STEP, BASE, HEAD, "HIGH")
    assert res.check_id == "REQ-W-18" and not res.passed
    assert res.detail == "cannot load suspension_manager: nope"


def test_load_suspension_manager_caches_the_module(monkeypatch):
    monkeypatch.setattr(pr_readiness, "_suspension_manager_module", None)
    first = pr_readiness._load_suspension_manager()
    assert first.__name__ == "hos_suspension_manager"
    assert hasattr(first, "validate_disclosure")
    assert pr_readiness._suspension_manager_module is first
    assert pr_readiness._load_suspension_manager() is first


def test_load_suspension_manager_loader_exception_propagates_then_check_fails_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pr_readiness, "_suspension_manager_module", None)

    def boom(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(pr_readiness.importlib.util, "spec_from_file_location", boom)
    with pytest.raises(OSError):
        pr_readiness._load_suspension_manager()
    assert pr_readiness._suspension_manager_module is None
    res = pr_readiness._check_dep_mapper_suspension(tmp_path, STEP, BASE, HEAD, "HIGH")
    assert not res.passed and "cannot load suspension_manager" in res.detail


def test_2214_table_without_delimiter_row_fails():
    h = make_handoff().replace("|---|---|---|---|\n", "")
    assert "no delimiter row matching its header" in _errs(disc(h))


def test_2214_delimiter_row_with_wrong_column_count_fails():
    h = make_handoff().replace("|---|---|---|---|", "|---|---|")
    assert "no delimiter row matching its header" in _errs(disc(h))


_ALIGNED = [
    "| :--- | :--- | :--- | :--- |",
    "|---:|---:|---:|---:|",
    "| :---: | :---: | :---: | :---: |",
]


@pytest.mark.parametrize("delim", _ALIGNED)
def test_2214_aligned_delimiter_row_is_accepted(delim):
    # R4 exempts delimiter rows: ":---:" is alignment, not an emoji shortcode.
    res = disc(make_handoff().replace("|---|---|---|---|", delim))
    assert res["valid"], res["errors"]
    trace = make_trace(STEP, BASE, HEAD, FILES).replace("|---|---|---|---|", delim)
    assert validate(trace) == {"valid": True, "errors": []}
    h = make_handoff(trace=trace)
    assert disc(h, trace=trace)["valid"]


@pytest.mark.parametrize("variant", ["  {h}", "\t{h}", "{h}\t"])
def test_trace_heading_must_be_at_column_0_with_only_trailing_spaces(variant):
    # A heading that is indented or tab-trailed would pass V1-V9 yet fail as a copy (D-21).
    for heading, rule in ((CALLERS_H, "V4"), (ITEMS_H, "V7")):
        trace = make_trace(STEP, BASE, HEAD, FILES).replace(heading, variant.format(h=heading), 1)
        errs = validate(trace)["errors"]
        assert any(e.startswith(rule + ":") for e in errs), (variant, heading, errs)
    spaced = make_trace(STEP, BASE, HEAD, FILES).replace(CALLERS_H, CALLERS_H + "   ", 1)
    assert validate(spaced)["valid"]


# ---------------------------------------------------------------------------
# AM-1: the disclosure is checked as visible text by an allowlist (TD 10(f), T-D1..T-D17)
# ---------------------------------------------------------------------------

SHIPPED_SUSP = (REPO / "contract/gate-suspension.md").read_text(encoding="utf-8")
_ATTRIBUTION = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
P7_ERR = f'disclosure prefix line 1: the PR body must start with "{AI_HEADING}"'
MISSING_ERR = f"disclosure heading missing: {HEADING}"


def put(handoff, text, where="section"):
    """Insert `text` into the prefix (before the blank line that precedes the disclosure
    heading), into the section's intro paragraph (before the 'Manual trace:' line, outside
    the copied sections), or at the section's "end" (before 'Result: PASS', i.e. under the
    Items list). Returns (handoff, 1-based line number of the first inserted line)."""
    lines = handoff.split("\n")
    if where == "prefix":
        at = lines.index(HEADING) - 1
    elif where == "end":
        at = lines.index("Result: PASS")
    else:
        at = next(i for i, ln in enumerate(lines) if ln.startswith("Manual trace:"))
    lines[at:at] = text.split("\n")
    return "\n".join(lines), at + 1


def lineno(handoff, needle):
    return next(i + 1 for i, ln in enumerate(handoff.split("\n")) if needle in ln)


def has(res, prefix):
    return any(e.startswith(prefix) for e in res["errors"])


def p_err(k, tail):
    return f"disclosure prefix line {k}: {tail}"


def r1_err(k, c):
    shown = c if c.isprintable() else c.encode("unicode_escape").decode("ascii")
    return f'disclosure line {k}: character "{shown}" (U+{ord(c):04X}) is not allowed'


def make_trace_raw(rows, items, step=STEP):
    return (
        f"# dep-mapper manual trace — step {step}\n\nRange: {BASE}..{HEAD}\n"
        "dep-mapper result: Data confidence: LOW (generic mapper)\nDate: 2026-11-06\n\n"
        f"{CALLERS_H}\n\n| Changed file | Callers / readers | Check | Result |\n|---|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\n{ITEMS_H}\n\n"
        + "\n".join(items)
        + "\n\n## Conclusion\n\nResult: PASS\nAll callers checked.\n"
    )


# Shapes of the three real traces (TD 4.5): as they are today (V9 fails) and rewritten per 4.2.
REAL_TRACES = {
    "2171s4": dict(
        files=["scripts/a.sh", "bootstrap/overseer-cron-prompt.md"],
        bad_rows=[
            "| scripts/a.sh | callers in ~1921 lines | grep | pass |",
            "| bootstrap/overseer-cron-prompt.md | read by ~12 tests | grep | pass |",
        ],
        good_rows=[
            "| scripts/a.sh | callers in about 1921 lines | grep | pass |",
            "| bootstrap/overseer-cron-prompt.md | read by about 12 tests | grep | pass |",
        ],
        bad_items=["- **Worker prompt** reads `HOS_X` at runtime", "- **Cron** via `bin/hos-cron`"],
        good_items=["- Worker prompt reads HOS_X at runtime", "- Cron wiring via bin/hos-cron"],
        bad_sections={"callers", "items"},
    ),
    "2255": dict(
        files=["scripts/framework/next_actor.py"],
        bad_rows=[
            "| scripts/framework/next_actor.py | gain `:http-<n>` and *new* ones | t | pass |"
        ],
        good_rows=[
            "| scripts/framework/next_actor.py | gain the token :http-N and new ones | t | pass |"
        ],
        bad_items=[
            "- **Workflow trigger wiring (not greppable):** observed live, issue #2254",
            "  (labeled 2026-11-06T06:05:43Z) show both halves firing; each call is a single",
            "  /approve or /decline gh call with an `|| true`.",
        ],
        good_items=[
            "- Workflow trigger wiring (not greppable): observed live, issue #2254",
            "  (labeled 2026-11-06T06:05:43Z) show both halves firing; each call is a single",
            "  /approve or /decline gh call with a double-pipe true.",
        ],
        bad_sections={"callers", "items"},
    ),
    "2214": dict(
        files=["scripts/oversight/suspension_manager.py", "contract/gate-suspension.md"],
        bad_rows=[
            "| scripts/oversight/suspension_manager.py | `validate_x` callers | g | pass |",
            "| contract/gate-suspension.md | read at ~line 14 | g | no impact |",
        ],
        good_rows=[
            "| scripts/oversight/suspension_manager.py | validate_x callers | g | pass |",
            "| contract/gate-suspension.md | read at about line 14 | g | no impact |",
        ],
        bad_items=["- Agent-prompt references: grepped, none call it"],
        good_items=["- Agent-prompt references: grepped, none call it"],
        bad_sections={"callers"},
    ),
}


def real_trace(name, rewritten):
    d = REAL_TRACES[name]
    return make_trace_raw(
        d["good_rows" if rewritten else "bad_rows"], d["good_items" if rewritten else "bad_items"]
    )


_SPEC82_LINE = (
    "- To verify: `git log --diff-filter=A --format='%h %s' -- contract/gate-suspension.md` "
    "gives the adding PR (`(#<n>)`); `git diff <default>...HEAD -- contract/gate-suspension.md`."
)
SUFFIX_CASES = {
    "spec82-recipe": [*SUFFIX, "", _SPEC82_LINE],
    "hostile": [
        *SUFFIX,
        "`code`, $VAR and $$ math, <details>",
        "<!-- a comment -->",
        "```mermaid",
        "graph TD",
        "```",
        "[a]: /u",
        "[^1]: x",
    ],
    "attribution": [*SUFFIX, "", _ATTRIBUTION],
}


@pytest.mark.parametrize("suffix", list(SUFFIX_CASES))
def test_d1_faithful_copy_with_shipped_suspension_passes(suffix):
    trace = make_trace(STEP, BASE, HEAD, FILES)
    assert validate(trace) == {"valid": True, "errors": []}
    h = make_handoff(trace=trace, susp=SHIPPED_SUSP, suffix=SUFFIX_CASES[suffix])
    res = disc(h, trace=trace, susp=SHIPPED_SUSP)
    assert res["valid"], res["errors"]


@pytest.mark.parametrize("name", list(REAL_TRACES))
@pytest.mark.parametrize("suffix", list(SUFFIX_CASES))
def test_d1_faithful_copy_of_rewritten_real_traces_passes(name, suffix):
    trace = real_trace(name, rewritten=True)
    res_v = validate(trace, REAL_TRACES[name]["files"])
    assert res_v["valid"], res_v["errors"]
    h = make_handoff(trace=trace, susp=SHIPPED_SUSP, suffix=SUFFIX_CASES[suffix])
    res = disc(h, trace=trace, susp=SHIPPED_SUSP)
    assert res["valid"], res["errors"]


def test_d1_crlf_and_lone_cr_line_endings_are_normalised():
    h = make_handoff()
    assert disc(h.replace("\n", "\r\n"))["valid"]
    assert disc(h.replace("\n", "\r"))["valid"]


# --- P1 ---------------------------------------------------------------------------------

_FENCE_PREFIXES = [
    "",
    "- ",
    "* ",
    "+ ",
    "1. ",
    "1) ",
    "> ",
    "> > ",
    "> - ",
    "  - ",
    "   > ",
    "    ",
    "\t",
]


@pytest.mark.parametrize("opener", ["```", "~~~", "```math", "```mermaid"])
@pytest.mark.parametrize("container", _FENCE_PREFIXES)
def test_d2_fence_lines_before_the_heading_fail_p1(container, opener):
    h, k = put(make_handoff(), container + opener, "prefix")
    assert has(disc(h), p_err(k, "code fence before the disclosure heading"))


@pytest.mark.parametrize("line", ["\t```geojson", "- ~~~topojson", "> ```stl"])
def test_d2_nested_rich_render_fences_fail_p1(line):
    h, k = put(make_handoff(), line, "prefix")
    assert has(disc(h), p_err(k, "code fence before the disclosure heading"))


def test_d2_mid_line_mention_of_backticks_is_fine():
    h, _ = put(make_handoff(), "see three backticks here", "prefix")
    assert disc(h)["valid"]


# --- P2 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["$$", "$$\\color{white}", "x $\\color{white}y$", "$`a`$", "$$\nhidden\n$$"]
)
def test_d3_dollar_before_the_heading_fails_p2(line):
    h, k = put(make_handoff(), line, "prefix")
    assert has(disc(h), p_err(k, '"$" before the disclosure heading'))


# --- P3, P4, P5 -------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["<details>", "<!--", "<?x", "<div hidden>"])
def test_d4_html_before_the_heading_fails_p3(line):
    h, k = put(make_handoff(), line, "prefix")
    assert has(disc(h), p_err(k, "raw HTML before the disclosure heading"))


@pytest.mark.parametrize(
    "container", ["", "- ", "* ", "+ ", "1. ", "1) ", "> ", "> > ", "> - ", "- > ", "  - ", "> 1. "]
)
def test_d4_definition_under_any_container_fails_p4(container):
    h, k = put(make_handoff(), f'{container}[x]: /u "', "prefix")
    assert has(disc(h), p_err(k, '"]:" (link-reference definition) before the disclosure heading'))


@pytest.mark.parametrize("line", ['[a](/u "t")', "![i](/u)", "[a][b]"])
def test_d4_title_image_and_reference_link_before_the_heading_fail_p5(line):
    h, k = put(make_handoff(), line, "prefix")
    assert has(disc(h), p_err(k, "link with a title, reference link or image before"))


def test_d4_plain_link_before_the_heading_is_fine():
    h, _ = put(make_handoff(), "see [text](https://x) here", "prefix")
    assert disc(h)["valid"]


# --- P0 and R0 --------------------------------------------------------------------------


@pytest.mark.parametrize("c", ["\u0085", "\u2028", "\x1c"])
def test_d5_control_and_separator_characters_before_the_heading_fail_p0(c):
    h, k = put(make_handoff(), f"a{c}b", "prefix")
    assert has(disc(h), p_err(k, f"control or line-separator character U+{ord(c):04X} before"))


def test_d5_u2028_does_not_create_a_heading_line():
    # splitlines() would put the heading at column 0; "\n"-splitting does not (R0).
    h = make_handoff().replace("\n" + HEADING, "\n\u2028" + HEADING, 1)
    assert disc(h)["errors"] == [MISSING_ERR]


# --- items 1-2, R6 ----------------------------------------------------------------------


def test_d6_heading_must_appear_exactly_once_in_the_whole_body():
    twice = make_handoff() + HEADING + "\n"
    assert disc(twice)["errors"] == ["disclosure heading appears 2 times; exactly one is allowed"]
    in_suffix = make_handoff(suffix=[*SUFFIX, "", HEADING])
    assert disc(in_suffix)["errors"] == [
        "disclosure heading appears 2 times; exactly one is allowed"
    ]


@pytest.mark.parametrize("variant", [" " + HEADING, "    " + HEADING, "> " + HEADING])
def test_d6_indented_or_quoted_heading_is_not_recognised(variant):
    h = make_handoff().replace(HEADING, variant, 1)
    assert disc(h)["errors"] == [MISSING_ERR]


def test_d6_trailing_spaces_on_the_heading_are_ignored():
    assert disc(make_handoff().replace(HEADING, HEADING + "  ", 1))["valid"]


@pytest.mark.parametrize("ender", ["### x", "# x", "##", "###### x"])
def test_d6_column0_heading_ends_the_section_and_fails_closed(ender):
    h = make_handoff().replace(f"{CALLERS_H}\n\n| Changed", f"{CALLERS_H}\n\n{ender}\n| Changed", 1)
    k = h.split("\n").index(ender) + 1
    text = _errs(disc(h))
    assert "disclosure missing the copied trace table ('| Changed file')" in text
    assert "disclosed callers table header differs from the trace" in text
    assert "disclosure missing the copied heading" in text  # the Items heading is cut off too
    assert "disclosure missing 'Result: PASS'" in text
    assert "line must start with" not in text  # not reported through R3
    assert f"disclosure line {k}:" not in text


@pytest.mark.parametrize("line", [" ### x", "#2162 is open"])
def test_d6_indented_hash_and_hash_without_space_do_not_end_the_section(line):
    h, k = put(make_handoff(), line)
    res = disc(h)
    assert res["errors"] == [
        f'disclosure line {k}: line must start with a letter, digit, "(", ".", "/" or a quote, '
        f'or with "- " directly followed by one; found "{line.lstrip(" ")[:3]}"'
    ]


def test_d6_section_ends_at_the_next_heading_and_the_rest_is_not_reported():
    h = make_handoff(suffix=[*SUFFIX, "", "`bad` <b> $x [a]: y"])
    assert disc(h)["valid"]


def test_copied_headings_must_appear_once_and_in_order():
    h = make_handoff().replace("Result: PASS", CALLERS_H + "\nResult: PASS", 1)
    k = h.split("\n").index(CALLERS_H, h.split("\n").index(ITEMS_H)) + 1
    assert has(disc(h), f'disclosure line {k}: copied heading "{CALLERS_H}" repeated or out of')
    swapped = make_handoff().replace(CALLERS_H, "@@", 1).replace(ITEMS_H, CALLERS_H, 1)
    swapped = swapped.replace("@@", ITEMS_H, 1)
    k = lineno(swapped, ITEMS_H)
    assert has(disc(swapped), f'disclosure line {k}: copied heading "{ITEMS_H}" repeated or out of')


def test_attribution_literal_is_allowed_in_the_section_and_a_variant_is_not():
    assert disc(make_handoff(suffix=[_ATTRIBUTION]))["valid"]
    near = _ATTRIBUTION.replace("claude-code", "claude-codes")
    assert not disc(make_handoff(suffix=[near]))["valid"]


# --- R1 ---------------------------------------------------------------------------------

_BAD_CHARS = ["`", "$", "\\", "&", "[", "]", "<", ">", "*", "~", "\t"]
_BAD_CHARS += ["\u200b", "\u202e", "\u00a0", "\u0430"]


@pytest.mark.parametrize("c", _BAD_CHARS)
@pytest.mark.parametrize("shape", ["prose", "bullet", "cell"])
def test_d7_characters_outside_the_allowlist_fail_r1(c, shape):
    if shape == "cell":
        h = make_handoff().replace("| callers | grep |", f"| callers | g{c}p |", 1)
        k = lineno(h, "| scripts/foo.py")
    else:
        text = f"see {c} here" if shape == "prose" else f"- see {c} here"
        h, k = put(make_handoff(), text)
    assert has(disc(h), r1_err(k, c))


def test_d7_pipe_is_only_allowed_in_table_rows():
    h, k = put(make_handoff(), "see a | b here")
    assert has(disc(h), r1_err(k, "|"))


def test_d7_allowed_punctuation_and_symbols_pass():
    h, _ = put(make_handoff(), "see #2162, @name, {N}, a — b → c § d; (e) 1/2 x_y 50% =+!?^'\"")
    assert disc(h)["valid"]


# --- R2, R3 -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["    four", "      six"])
def test_d8_four_or_more_leading_spaces_fail_r2(text):
    h, k = put(make_handoff(), text)
    assert has(
        disc(h),
        f"disclosure line {k}: indented 4 or more spaces (GitHub renders it as code); "
        "use at most 3",
    )


@pytest.mark.parametrize(
    "text", ["(x", ".x", "/x", '"x', "1. x", "- x", "- none", "  continuation", "  - nested"]
)
def test_d8_allowed_line_starts_pass(text):
    h, _ = put(make_handoff(), text)
    assert disc(h)["valid"]


@pytest.mark.parametrize(
    "text",
    [" # x", "+ x", "---", "___", "===", ":x", "-", "- ", "-     x", "-  x", "- - x"],
)
def test_d8_block_openers_fail_r3(text):
    h, k = put(make_handoff(), text)
    assert has(disc(h), f"disclosure line {k}: line must start with a letter, digit")


@pytest.mark.parametrize("text", [">", "> x", "* x", "***"])
def test_d8_markers_outside_the_character_set_fail_r1_before_r3(text):
    # R1 runs first, and only the first rule a line breaks is reported.
    h, k = put(make_handoff(), text)
    assert has(disc(h), f"disclosure line {k}: character")
    assert "line must start with" not in _errs(disc(h))


def test_d8_task_item_fails_r1_first():
    h, k = put(make_handoff(), "- [ ] task")
    assert has(disc(h), r1_err(k, "["))


# --- R4 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["white_check_mark", "x", "X", "White_Check_Mark", "+1", "-1", "smile"]
)
def test_d9_emoji_shortcodes_fail_r4(name):
    h, k = put(make_handoff(), f"see :{name}: here")
    assert has(disc(h), f'disclosure line {k}: ":{name}:" may render as an emoji')


@pytest.mark.parametrize(
    "text", ["at 06:05:43Z", "file.py:12:34 ok", "see :100: here", "https://x", "Result: PASS"]
)
def test_d9_timestamps_locations_and_all_digit_forms_pass(text):
    h, _ = put(make_handoff(), text)
    assert "may render as an emoji" not in _errs(disc(h))


# --- R5 ---------------------------------------------------------------------------------

_ROW = "| scripts/foo.py | callers | grep | pass |"
_DELIM = "|---|---|---|---|"
_NO_DELIM = "disclosure callers table has no delimiter row matching its header"


@pytest.mark.parametrize(
    "delim", [None, "---|---|---|---", "|---\\|---|---|---|", "|---|---|", "|---|---|---|---|---|"]
)
def test_d10_missing_or_mismatched_delimiter_row_fails(delim):
    h = make_handoff()
    h = h.replace(_DELIM + "\n", "" if delim is None else delim + "\n", 1)
    assert _NO_DELIM in disc(h)["errors"]


@pytest.mark.parametrize(
    "row,cells",
    [(_ROW[:-1] + " | extra |", 5), ("| scripts/foo.py | callers | pass |", 3)],
)
def test_d10_row_with_wrong_cell_count_fails(row, cells):
    h = make_handoff().replace(_ROW, row, 1)
    k = lineno(h, "| scripts/foo.py")
    assert f"disclosure line {k}: table row has {cells} cells, header has 4" in disc(h)["errors"]


def test_d10_row_without_closing_pipe_fails():
    h = make_handoff().replace(_ROW, _ROW[:-2], 1)
    k = lineno(h, "| scripts/foo.py")
    assert f'disclosure line {k}: table row must start and end with "|"' in disc(h)["errors"]


def test_d10_second_table_block_fails():
    h, k = put(make_handoff(), "| a | b |\n", "end")
    assert f"disclosure section has more than one table (line {k})" in disc(h)["errors"]


_BLANK_ERR = "table must have a blank line or section heading before it and a blank line after it"


def test_d10_table_directly_after_a_prose_line_fails():
    h = make_handoff().replace(
        f"{CALLERS_H}\n\n| Changed", f"{CALLERS_H}\n\nsome prose\n| Changed", 1
    )
    k = lineno(h, "| Changed file")
    assert f"disclosure line {k}: {_BLANK_ERR}" in disc(h)["errors"]


def test_d10_prose_line_directly_after_the_last_row_fails():
    h = make_handoff().replace(_ROW + "\n", _ROW + "\nprose after\n", 1)
    k = lineno(h, "prose after")
    assert f"disclosure line {k}: {_BLANK_ERR}" in disc(h)["errors"]


def test_d10_table_directly_under_its_heading_is_valid():
    h = make_handoff().replace(f"{CALLERS_H}\n\n| Changed", f"{CALLERS_H}\n| Changed", 1)
    assert disc(h)["valid"]


def test_d10_table_under_items_heading_or_above_callers_heading_fails_r5e():
    err = 'the table must be the copied callers table, under "## Callers / readers checked"'
    swapped = make_handoff().replace(CALLERS_H, "@@", 1).replace(ITEMS_H, CALLERS_H, 1)
    swapped = swapped.replace("@@", ITEMS_H, 1)
    k = lineno(swapped, "| Changed file")
    assert f"disclosure line {k}: {err}" in disc(swapped)["errors"]
    above = make_handoff().replace(f"{CALLERS_H}\n\n", "", 1)
    above = above.replace(_ROW + "\n", _ROW + f"\n\n{CALLERS_H}\n", 1)
    assert f"disclosure line {lineno(above, '| Changed file')}: {err}" in disc(above)["errors"]


# --- fifth-bypass regression ------------------------------------------------------------


def test_d11_dollar_wrapper_fails_inside_the_section_and_before_the_heading():
    inside = (
        make_handoff()
        .replace(CALLERS_H, "$$\\color{white}\n" + CALLERS_H, 1)
        .replace("Result: PASS", "$$\nResult: PASS", 1)
    )
    k = lineno(inside, "$$\\color")
    assert has(disc(inside), r1_err(k, "$"))
    before, k = put(make_handoff(), "$$\\color{white}", "prefix")
    before += "$$\n"
    assert has(disc(before), p_err(k, '"$" before the disclosure heading'))


def test_d11_list_item_fence_wrapper_fails_inside_the_section_and_before_the_heading():
    inside = (
        make_handoff()
        .replace(CALLERS_H, "- ```mermaid\n" + CALLERS_H, 1)
        .replace("Result: PASS", "```\nResult: PASS", 1)
    )
    k = lineno(inside, "- ```mermaid")
    assert has(disc(inside), r1_err(k, "`"))
    before, k = put(make_handoff(), "- ```mermaid", "prefix")
    assert has(disc(before), p_err(k, "code fence before the disclosure heading"))


# --- V9 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(REAL_TRACES))
def test_d12_real_traces_as_they_are_today_fail_v9_naming_section_and_line(name):
    d = REAL_TRACES[name]
    trace = real_trace(name, rewritten=False)
    res = validate(trace, d["files"])
    assert not res["valid"]
    v9 = [e for e in res["errors"] if e.startswith("V9: ")]
    for sec, heading in (("callers", CALLERS_H), ("items", ITEMS_H)):
        found = any(e.startswith(f"V9: {heading} line ") for e in v9)
        assert found == (sec in d["bad_sections"]), (name, sec, v9)
    # the line number is the trace file's own
    lines = trace.split("\n")
    for e in v9:
        k = int(re.search(r" line (\d+): ", e).group(1))
        assert 1 <= k <= len(lines)
        assert lines[k - 1].strip()
    assert all(e.startswith(("V9: ## Callers", "V9: ## Items")) for e in v9)


@pytest.mark.parametrize("name", list(REAL_TRACES))
def test_d12_real_traces_rewritten_pass_v9(name):
    res = validate(real_trace(name, rewritten=True), REAL_TRACES[name]["files"])
    assert res == {"valid": True, "errors": []}


def test_d12_v9_error_carries_the_trace_line_number():
    trace = make_trace(STEP, BASE, HEAD, ["scripts/foo~.py"])
    k = lineno(trace, "foo~")
    errs = validate(trace, ["scripts/foo~.py"])["errors"]
    assert any(e.startswith(f'V9: {CALLERS_H} line {k}: character "~" (U+007E)') for e in errs)


def test_d12_v9_trace_table_needs_a_delimiter_row():
    trace = make_trace(STEP, BASE, HEAD, FILES).replace("|---|---|---|---|\n", "")
    assert (
        f"V9: {CALLERS_H}: callers table has no delimiter row matching its header"
        in validate(trace)["errors"]
    )


# --- item 5 fail-closed -----------------------------------------------------------------


@pytest.mark.parametrize("value", ["Test <email>", "Test & Co", "Test :smile:"])
def test_d13_authorized_by_value_the_section_cannot_carry_fails_closed(value):
    susp = susp_text().replace("Authorized by: Test Human", f"Authorized by: {value}")
    h = make_handoff(susp=susp)  # copies the value exactly
    assert (
        'suspension "Authorized by:" value contains characters the disclosure section cannot '
        "carry; a human must change contract/gate-suspension.md"
    ) in disc(h, susp=susp)["errors"]


# --- D-20: the suffix is not checked ----------------------------------------------------


def test_d14_nothing_after_the_section_is_checked():
    suffix = [
        *SUFFIX,
        "<!-- -->",
        "x ]: y",
        "$$",
        "```",
        "unclosed fence",
        "[^1]: x",
        "<details>",
    ]
    assert disc(make_handoff(suffix=suffix))["valid"]


def test_d14_footnote_inside_the_section_fails_r1():
    h, k = put(make_handoff(), "see [^1] here")
    assert has(disc(h), r1_err(k, "["))


def test_comment_or_html_prefix_and_section_still_fail():
    h, k = put(make_handoff(), "<!-- note -->", "prefix")
    assert has(disc(h), p_err(k, "raw HTML before the disclosure heading"))
    h, k = put(make_handoff(), "<!-- note -->")
    assert has(disc(h), r1_err(k, "<"))
    h, k = put(make_handoff(), "Note: see &lt;n&gt;")
    assert has(disc(h), r1_err(k, "&"))


@pytest.mark.parametrize(
    "wrapper",
    ["<div hidden>", "<style>", "<details><summary>x</summary>", "<?x", "`<n>` in a code span"],
)
def test_html_wrappers_inside_the_section_fail_r1(wrapper):
    h, k = put(make_handoff(), wrapper)
    assert any(e.startswith(f"disclosure line {k}: character") for e in disc(h)["errors"])


@pytest.mark.parametrize(
    "bad",
    [
        '[a]: /u\n"Data confidence: LOW"',
        '- [x]: /u "',
        '[x](u "t")',
        "[a][b]",
        "![i](u)",
        "- [x] done",
        "See [text](https://x) here",
        _ATTRIBUTION.replace("claude-code", "x"),
    ],
)
def test_links_and_definitions_inside_the_section_fail_r1(bad):
    h, k = put(make_handoff(), bad)
    assert any(e.startswith(f"disclosure line {k}: character") for e in disc(h)["errors"])


def test_links_in_the_prefix_and_suffix_stay_valid():
    h = make_handoff(suffix=[*SUFFIX, "", "See [text](https://x) and - [x] done", _ATTRIBUTION])
    assert disc(h)["valid"]
    h, _ = put(h, "see [text](https://x)", "prefix")
    assert disc(h)["valid"]


def test_a_section_hidden_behind_a_comment_or_fence_fails_through_the_prefix_rules():
    body = make_handoff()
    for opener, closer, prefix_err in (
        ("<!--", "-->", "raw HTML before"),
        ("```", "```", "code fence before"),
        ("~~~", "~~~", "code fence before"),
    ):
        res = disc(f"{opener}\n{body}{closer}\n")
        assert has(res, P7_ERR)
        assert has(res, "disclosure prefix line 1: " + prefix_err)


def test_a_definition_or_tag_before_the_heading_cannot_swallow_the_disclosure():
    for pre, err in (('[a]: /u "', '"]:"'), ("<div hidden>", "raw HTML")):
        h = f"{pre}\n" + make_handoff() + '"\n'
        res = disc(h)
        assert not res["valid"] and has(res, "disclosure prefix line 1: " + err)


# --- P7, P8, P9 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    ["# Handoff — Step N", "", "---", "## AI-Submitted Pull Request"],
)
def test_d15_line_one_must_be_the_ai_submitted_heading(first):
    h = make_handoff().replace(AI_HEADING, first, 1)
    assert P7_ERR in disc(h)["errors"]


def test_d15_trailing_spaces_on_line_one_are_fine():
    assert disc(make_handoff().replace(AI_HEADING, AI_HEADING + "   ", 1))["valid"]


def test_d15_heading_as_line_one_reports_p7_only():
    lines = disclosure_lines(STEP, make_trace(STEP, BASE, HEAD, FILES), susp_text())
    assert disc("\n".join(lines))["errors"] == [P7_ERR]


@pytest.mark.parametrize("line", ["### x", "# Handoff — Step N", "##"])
def test_d15_any_other_prefix_heading_fails_p8(line):
    h, k = put(make_handoff(), line, "prefix")
    assert has(disc(h), p_err(k, "heading before the disclosure heading"))


@pytest.mark.parametrize("before", ["a paragraph line", "| a | b |", "- item", '[a](/u "'])
def test_d15_line_before_the_heading_must_be_blank_p9(before):
    lines = make_handoff().split("\n")
    h = lines.index(HEADING)
    lines[h - 1] = before
    res = disc("\n".join(lines))
    assert p_err(h, "the line before the disclosure heading must be blank") in res["errors"]
    if before.startswith("[a]"):
        assert has(res, p_err(h, "link with a title"))


def test_d15_orchestrator_template_with_the_section_inserted_has_no_prefix_error():
    text = (REPO / ".claude/agents/oversight-orchestrator.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    i = lines.index(AI_HEADING)
    j = next(n for n in range(i, len(lines)) if lines[n].startswith("# Handoff"))
    trace = make_trace(STEP, BASE, HEAD, FILES)
    section = disclosure_lines(STEP, trace, susp_text())
    res = disc("\n".join(lines[i:j] + section + SUFFIX) + "\n")
    assert res["valid"], res["errors"]


# --- R7 ---------------------------------------------------------------------------------

_R7_ERR = "the line before the heading that ends the disclosure section must be blank"


def test_d16_result_pass_directly_before_the_ending_heading_fails_r7():
    h = make_handoff().replace("Result: PASS\n\n# Handoff", "Result: PASS\n# Handoff", 1)
    assert f"disclosure line {lineno(h, 'Result: PASS')}: {_R7_ERR}" in disc(h)["errors"]


def test_d16_table_directly_before_the_ending_heading_fails_r7_and_r5d():
    h = make_handoff()
    cut = h.index("\n\n" + ITEMS_H)
    h = h[:cut] + "\n" + h[h.index("# Handoff") :]
    errs = disc(h)["errors"]
    k = lineno(h, _ROW)
    assert f"disclosure line {k}: {_R7_ERR}" in errs
    assert f"disclosure line {k + 1}: {_BLANK_ERR}" in errs


def test_d16_section_running_to_eof_needs_no_trailing_blank_line():
    h = make_handoff(suffix=[])
    h = h[: h.index("Result: PASS") + len("Result: PASS")]
    res = disc(h)
    assert res["valid"], res["errors"]


# --- V9 details -------------------------------------------------------------------------


def test_d17_table_in_the_items_section_is_rejected_by_v9():
    table = "| a | b |\n|---|---|\n| c | d |"
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(
        "- wiring item X, checked by grep", table, 1
    )
    k = lineno(trace, "| a | b |")
    msg = (
        f"V9: {ITEMS_H} line {k}: table rows are not allowed here "
        "(the disclosure carries one table, the callers table)"
    )
    assert msg in validate(trace)["errors"]


def test_d17_callers_table_directly_under_its_heading_passes_v9():
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(f"{CALLERS_H}\n\n", f"{CALLERS_H}\n", 1)
    assert validate(trace) == {"valid": True, "errors": []}


def test_d17_table_running_directly_into_the_next_heading_fails_v9():
    # The end of a trace section is not treated as EOF: R5(d) sees the next heading.
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(f"\n\n{ITEMS_H}", f"\n{ITEMS_H}", 1)
    k = lineno(trace, ITEMS_H)
    assert f"V9: {CALLERS_H} line {k}: {_BLANK_ERR}" in validate(trace)["errors"]


@pytest.mark.parametrize("sep", ["\u2028", "\u0085"])
def test_d17_every_v_rule_numbers_lines_by_newline_only(sep):
    trace = make_trace(STEP, BASE, HEAD, FILES)
    trace = trace.replace("Date: 2026-11-06", f"Date: 2026-11-06{sep}x", 1)
    trace = trace.replace("| callers | grep |", "| call~ers | grep |", 1)
    k = lineno(trace, "call~ers")
    assert (
        k == trace.split("\n").index(next(ln for ln in trace.split("\n") if "call~ers" in ln)) + 1
    )
    errs = validate(trace)["errors"]
    assert any(e.startswith(f'V9: {CALLERS_H} line {k}: character "~"') for e in errs)
    # V2 sees the same lines: a Range line that exists only after the separator is no line
    hidden = (
        make_trace(STEP, BASE, HEAD, FILES)
        .replace(f"Range: {BASE}..{HEAD}\n", "", 1)
        .replace("Date: 2026-11-06", f"Date: 2026-11-06{sep}Range: {BASE}..{HEAD}", 1)
    )
    assert "V2: no 'Range:' line" in validate(hidden)["errors"]


@pytest.mark.parametrize(
    "trace,files",
    [
        (make_trace(STEP, BASE, HEAD, FILES), FILES),
        (
            make_trace(STEP, BASE, HEAD, FILES + ["scripts/b.py", "docs/c.md"]),
            FILES + ["scripts/b.py", "docs/c.md"],
        ),
        (
            make_trace(STEP, BASE, HEAD, ["bootstrap/a.md, bootstrap/b.md"]),
            ["bootstrap/a.md", "bootstrap/b.md"],
        ),
    ]
    + [(real_trace(n, rewritten=True), REAL_TRACES[n]["files"]) for n in REAL_TRACES],
)
def test_d17_every_valid_trace_yields_a_valid_faithful_disclosure(trace, files):
    assert validate(trace, files)["valid"]
    res = disc(make_handoff(trace=trace), trace=trace)
    assert res["valid"], res["errors"]


@pytest.mark.parametrize("text", [":100:smile:", ":100: :smile:", ":05::x:"])
def test_d9_all_digit_span_does_not_hide_a_real_shortcode(text):
    h, k = put(make_handoff(), f"see {text} here")
    assert has(disc(h), f'disclosure line {k}: ":')
    assert "may render as an emoji" in _errs(disc(h))


def test_d9_shortcode_scan_is_linear_on_a_long_unclosed_run():
    import time

    h, _ = put(make_handoff(), "x :" + "a" * 65000)
    t0 = time.monotonic()
    res = disc(h)
    assert time.monotonic() - t0 < 1.0
    assert "may render as an emoji" not in _errs(res)


# ---------------------------------------------------------------------------
# AM-2: default-branch freshness (TD 10(g), T-F1..T-F12). A local bare origin, no network.
# ---------------------------------------------------------------------------

SUSP = "contract/gate-suspension.md"


def _origin_commit(repo, files, branch="main", extra_refs=()):
    """Commit `files` on top of origin's default branch from a scratch clone and push the
    result to origin's `branch` (and any `extra_refs`). A value is text, None (delete),
    ("symlink", target) or ("exec", text). Returns the new commit SHA."""
    work = repo.factory.mktemp("clone")
    _git(work, "clone", "-q", str(repo.origin), "w")
    w = work / "w"
    for path, value in files.items():
        target = w / path
        if target.is_symlink() or target.exists():
            target.unlink()
        if value is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, tuple) and value[0] == "symlink":
            target.symlink_to(value[1])
        elif isinstance(value, tuple):
            target.write_text(value[1])
            target.chmod(0o755)
        else:
            target.write_text(value)
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "--allow-empty", "-m", "origin change")
    _git(w, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", *extra_refs)
    return _rev(w)


def _fetch(repo):
    _git(repo.root, "fetch", "-q", "origin")


def _reader(repo):
    return sm.read_default_branch_suspension(repo.root)


def _ef2(reason, d="HEAD"):
    return (
        f"S4: could not confirm origin/{d} is current ({reason}); failing closed. "
        "Check network access and the GitHub token, then re-run"
    )


def _fake_git(monkeypatch, handler):
    """Wrap sm._git: handler(args) returns a CompletedProcess, None (timeout) or NotImplemented
    (run the real command)."""
    real = sm._git
    calls = []

    def wrapper(args, repo_root, env=None):
        calls.append(list(args))
        out = handler(args)
        return real(args, repo_root, env) if out is NotImplemented else out

    monkeypatch.setattr(sm, "_git", wrapper)
    return calls


def _cp(rc=0, out=b"", err=b""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


def test_f1_matching_local_ref_returns_the_blob(repo):
    res = _reader(repo)
    assert res == {"text": susp_text(), "error": None, "sha": repo.base, "branch": "main"}


def test_f1_end_to_end_cli_passes(repo, monkeypatch, capsys):
    assert cli(monkeypatch, capsys, repo)[0] == 0


def test_f1_non_main_default_branch_consults_no_main(repo):
    _git(repo.root, "push", "-q", "origin", "main:trunk")
    _git(repo.origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
    _fetch(repo)
    _git(repo.root, "update-ref", "-d", "refs/remotes/origin/main")
    res = _reader(repo)
    assert res["error"] is None and res["branch"] == "trunk" and res["text"] == susp_text()


def test_f2_stale_local_ref_fails_with_both_shas(repo, monkeypatch, capsys):
    new = _origin_commit(repo, {"README": "x"})
    res = _reader(repo)
    assert res["text"] is None
    assert res["error"] == (
        f"S4: local origin/main is {repo.base[:12]} but origin has {new[:12]}; the "
        "default-branch suspension may have been revoked or changed. "
        "Run 'git fetch origin' and re-run"
    )
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "ERROR=dep-low: S4: local origin/main is " in out
    assert "not on the default branch" not in out


def test_f2_local_ref_ahead_of_origin_fails(repo):
    _git(repo.root, "update-ref", "refs/remotes/origin/main", repo.head)
    err = _reader(repo)["error"]
    assert err.startswith(
        f"S4: local origin/main is {repo.head[:12]} but origin has {repo.base[:12]}"
    )


def test_f3_lookup_failures_are_e_f2(repo, monkeypatch):
    reason = "exit 128: fatal: could not read Username"
    res = sm.read_default_branch_suspension(repo.root, ls_remote=lambda r: (None, None, reason))
    assert res["text"] is None and res["error"] == _ef2(reason)
    _git(repo.root, "remote", "set-url", "origin", str(repo.root / "nonexistent"))
    err = _reader(repo)["error"]
    assert err.startswith("S4: could not confirm origin/HEAD is current (exit ")
    assert err.endswith("failing closed. Check network access and the GitHub token, then re-run")


_SHA = "a" * 40


@pytest.mark.parametrize(
    "stdout,reason",
    [
        (f"{_SHA}\tHEAD\n", 'origin did not report its default branch (no "ref: refs/heads/'),
        (
            f"ref: refs/heads/a\tHEAD\nref: refs/heads/b\tHEAD\n{_SHA}\tHEAD\n",
            "ambiguous or incomplete ls-remote output for HEAD",
        ),
        ("ref: refs/heads/main\tHEAD\n", "ambiguous or incomplete ls-remote output for HEAD"),
        ("ref: refs/heads/main\tHEAD\nabc123\tHEAD\n", "ambiguous or incomplete"),
        (
            f"ref: refs/heads/main\tHEAD\n{_SHA}\tHEAD\n{'b' * 40}\tHEAD\n",
            "ambiguous or incomplete ls-remote output for HEAD",
        ),
        (f"ref: refs/heads/-x\tHEAD\n{_SHA}\tHEAD\n", "unusable default-branch name from origin"),
        (f"ref: refs/heads/a..b\tHEAD\n{_SHA}\tHEAD\n", "unusable default-branch name from origin"),
        (f"ref: refs/heads/a b\tHEAD\n{_SHA}\tHEAD\n", "unusable default-branch name from origin"),
    ],
)
def test_f3_unusable_ls_remote_output_is_rejected_without_a_main_fallback(
    monkeypatch, stdout, reason
):
    _fake_git(monkeypatch, lambda a: _cp(0, stdout.encode()) if a[0] == "ls-remote" else None)
    d, sha, why = sm._default_ls_remote(".")
    assert (d, sha) == (None, None) and why.startswith(reason)


def test_f3_exit_codes_and_line_endings(monkeypatch):
    _fake_git(monkeypatch, lambda a: _cp(2))
    assert sm._default_ls_remote(".") == (None, None, "origin reports no HEAD")
    _fake_git(monkeypatch, lambda a: _cp(128, b"", b"\n  fatal: no\nmore\n"))
    assert sm._default_ls_remote(".") == (None, None, "exit 128: fatal: no")
    out = f"ref: refs/heads/main\tHEAD\r\n{_SHA}\tHEAD\r\n".encode()
    _fake_git(monkeypatch, lambda a: _cp(0, out))
    assert sm._default_ls_remote(".") == ("main", _SHA, None)


def test_f4_timeout_is_e_f2_and_the_call_is_bounded(repo, monkeypatch):
    seen = []

    def fake_run(argv, **kw):
        seen.append((argv, kw))
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(sm.subprocess, "run", fake_run)
    err = _reader(repo)["error"]
    assert "did not complete within 60s" in err and err.startswith(_ef2("")[:30])
    argv, kw = seen[0]
    assert argv == [
        "git",
        "-C",
        str(repo.root),
        "ls-remote",
        "--symref",
        "--exit-code",
        "origin",
        "HEAD",
    ]
    assert kw["timeout"] == 60 and kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert len(seen) == 1


def test_f5_revoked_suspension_with_a_stale_local_ref_fails(repo, monkeypatch, capsys, use_sm):
    _origin_commit(repo, {SUSP: susp_text("")})
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "S4: local origin/main is " in out
    res = req_w18(repo)
    assert not res.passed and "S4: local origin/main is " in res.detail
    _fetch(repo)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "local origin/main is" not in out
    assert "S4: suspension file modified on this branch" in out


def test_f6_missing_local_ref_is_e_f3(repo):
    _git(repo.root, "update-ref", "-d", "refs/remotes/origin/main")
    res = _reader(repo)
    assert res["text"] is None
    assert res["error"] == "S4: local ref origin/main not found; run 'git fetch origin' and re-run"


def test_f7_reads_at_the_verified_sha_not_the_ref(repo, monkeypatch):
    other = _origin_commit(repo, {SUSP: susp_text("SUSPENDED: dep-mapper")}, branch="other")
    _fetch(repo)
    moved = []

    def handler(args):
        if args[0] == "ls-tree" and not moved:
            moved.append(1)
            _git(repo.root, "update-ref", "refs/remotes/origin/main", other)
        return NotImplemented

    _fake_git(monkeypatch, handler)
    res = _reader(repo)
    assert moved and res["error"] is None and res["sha"] == repo.base
    assert res["text"] == susp_text()


def test_f8_main_suspension_error_is_required_and_replaces_the_s4_message():
    with pytest.raises(TypeError):
        sm.check_suspended_resolutions(
            make_risk(BASE, HEAD), STEP, BASE, HEAD, "HIGH", False, FILES, susp_text(), susp_text()
        )
    res = run_check(main_suspension_error="S4: boom", main_suspension_text=None)
    assert not res["ok"]
    s4 = [e for e in errors_of(res) if e.startswith("S4")]
    assert s4 == ["S4: boom"]


def test_f9_other_callers_never_look_at_origin(repo, monkeypatch, capsys):
    argvs = []
    real_run = subprocess.run

    def spy(argv, **kw):
        argvs.append(argv)
        return real_run(argv, **kw)

    def boom(*a, **k):
        raise AssertionError("origin lookup")

    monkeypatch.setattr(sm.subprocess, "run", spy)
    monkeypatch.setattr(sm, "_default_ls_remote", boom)
    monkeypatch.setattr(sm, "_default_issue_state", Stub())
    monkeypatch.setattr(sm, "_today", lambda: TODAY)
    assert sm.cmd_is_suspended("dep-mapper") == 0
    monkeypatch.setattr(sys, "argv", ["sm", "--suspension-status", "dep-mapper"])
    assert sm.main() == 0
    assert not any("ls-remote" in a for a in argvs)


def test_f9_check_suspension_sh_makes_no_ls_remote_call(tmp_path):
    real_git = shutil.which("git")
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "git.log"
    (shim / "git").write_text(f'#!/bin/sh\necho "$@" >> {log}\nexec {real_git} "$@"\n')
    (shim / "git").chmod(0o755)
    proj = tmp_path / "proj"
    (proj / "contract").mkdir(parents=True)
    (proj / SUSP).write_text(susp_text("SUSPENDED: dep-mapper expires: 2099-01-01"))
    _git(proj, "init", "-q")
    env = {
        **os.environ,
        "PATH": f"{shim}:{os.environ['PATH']}",
        "OVERSIGHT_PYTHON": sys.executable,
    }
    script = REPO / "scripts/oversight/gates/check_suspension.sh"
    r = subprocess.run(
        ["bash", "-c", f"source {script}; is_suspended dep-mapper"],
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "ls-remote" not in (log.read_text() if log.exists() else "")


def test_f10_repointed_local_origin_head_is_never_read(repo, monkeypatch, capsys):
    _origin_commit(repo, {SUSP: None}, branch="main")
    evil = susp_text("SUSPENDED: dep-mapper expires: 2099-01-01")
    _origin_commit(repo, {SUSP: evil}, branch="evil")
    _fetch(repo)
    _git(repo.root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/evil")
    (repo.root / SUSP).write_text(evil)
    calls = _fake_git(monkeypatch, lambda a: NotImplemented)
    res = _reader(repo)
    assert res["branch"] == "main" and res["text"] is None and res["error"] is None
    assert not any(c[0] == "symbolic-ref" for c in calls)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "S4: suspension not on the default branch" in out


def test_f11_decoy_refs_are_ignored(repo):
    _origin_commit(
        repo,
        {"README": "x"},
        branch="x/HEAD",
        extra_refs=("HEAD:refs/heads/x/refs/heads/main",),
    )
    raw = subprocess.run(
        ["git", "-C", str(repo.root), "ls-remote", "--symref", "origin", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "refs/heads/x/HEAD" in raw  # the decoy really is in the output
    res = _reader(repo)
    assert res["error"] is None and res["text"] == susp_text() and res["branch"] == "main"


def test_f11_two_exact_head_sha_lines_are_ambiguous(monkeypatch):
    out = f"ref: refs/heads/main\tHEAD\n{_SHA}\tHEAD\n{'b' * 40}\tHEAD\n".encode()
    _fake_git(monkeypatch, lambda a: _cp(0, out))
    res = sm.read_default_branch_suspension(".")
    assert "ambiguous or incomplete ls-remote output for HEAD" in res["error"]


def test_f12_missing_path_at_the_verified_commit_is_not_an_error(repo, monkeypatch, capsys):
    _origin_commit(repo, {SUSP: None})
    _fetch(repo)
    res = _reader(repo)
    assert res["text"] is None and res["error"] is None
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "S4: suspension not on the default branch" in out


def _ef4(why, repo, d="main"):
    return (
        f"S4: could not read {SUSP} at origin/{d} {repo.base[:12]} ({why}); failing closed, re-run"
    )


@pytest.mark.parametrize("cmd", ["ls-tree", "show"])
def test_f12_git_timeout_is_e_f4(repo, monkeypatch, cmd):
    _fake_git(monkeypatch, lambda a: None if a[0] == cmd else NotImplemented)
    res = _reader(repo)
    assert res["text"] is None and res["error"] == _ef4("timeout", repo)


@pytest.mark.parametrize("cmd", ["ls-tree", "show"])
def test_f12_git_error_exit_is_e_f4(repo, monkeypatch, cmd):
    _fake_git(
        monkeypatch, lambda a: _cp(128, b"", b"fatal: bad\n") if a[0] == cmd else NotImplemented
    )
    res = _reader(repo)
    assert res["text"] is None and res["error"] == _ef4("exit 128: fatal: bad", repo)


@pytest.mark.parametrize("value", [("symlink", "elsewhere"), ("exec", susp_text())])
def test_f12_non_regular_file_is_e_f4(repo, value):
    new = _origin_commit(repo, {SUSP: value})
    _fetch(repo)
    res = _reader(repo)
    assert res["text"] is None
    assert res["error"] == (
        f"S4: could not read {SUSP} at origin/main {new[:12]} (not a regular file); "
        "failing closed, re-run"
    )
    assert not run_check(main_suspension_error=res["error"])["ok"]


# --- git replace refs and the lazy origin lookup -----------------------------------------


def _plain_git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def test_replace_ref_cannot_forge_the_default_branch_blob(repo):
    forged = susp_text("SUSPENDED: dep-mapper expires: 2099-12-31")
    fake = _origin_commit(repo, {SUSP: forged}, branch="forged")
    _fetch(repo)
    _git(repo.root, "replace", repo.base, fake)
    # precondition: with replace refs honoured, the real SHA now shows the forged file
    assert "2099-12-31" in _plain_git(repo.root, "show", f"{repo.base}:{SUSP}")
    res = _reader(repo)
    assert res["error"] is None and res["sha"] == repo.base
    assert res["text"] == susp_text() and "2099-12-31" not in res["text"]


def test_replace_ref_cannot_hide_changed_files(repo):
    _git(repo.root, "replace", repo.head, repo.base)
    assert _plain_git(repo.root, "diff", "--name-only", f"{repo.base}..{repo.head}") == ""
    assert sm.changed_files_in_range(repo.base, repo.head, repo.root) == [
        "scripts/foo.py",
        "tests/test_foo.py",
    ]


def test_git_calls_always_disable_replace_objects_and_keep_the_overlay(monkeypatch):
    seen = []
    monkeypatch.setattr(sm.subprocess, "run", lambda argv, **kw: seen.append(kw["env"]))
    sm._git(["status"], ".")
    sm._git(["status"], ".", env={"GIT_TERMINAL_PROMPT": "0"})
    assert seen[0]["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert seen[1]["GIT_NO_REPLACE_OBJECTS"] == "1" and seen[1]["GIT_TERMINAL_PROMPT"] == "0"


def test_cli_makes_no_origin_call_when_no_suspension_applies(repo, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("origin lookup")

    monkeypatch.setattr(sm, "_default_ls_remote", boom)
    (repo.oversight / "validators/risk-assessment.md").write_text("# R\nblocking_findings: []\n")
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 0 and "APPLIES=no" in out


# --- table cells keep empty outer cells; untraced items copied exactly; V5 right boundary ---


def test_table_cells_drop_at_most_one_outer_pipe():
    assert sm._table_cells("|| a | b | pass |") == ["", "a", "b", "pass"]
    assert sm._table_cells("| a | b | pass ||") == ["a", "b", "pass", ""]
    assert sm._table_cells("| a | b |") == ["a", "b"]


def test_trace_row_with_an_empty_first_cell_is_valid_and_copies_faithfully():
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(
        "| scripts/foo.py | callers | grep | pass |",
        "| scripts/foo.py | callers | grep | pass |\n|| callers | grep | pass |",
    )
    assert validate(trace)["valid"]
    assert disc(make_handoff(trace=trace), trace=trace)["valid"]


def test_trace_row_with_an_empty_last_cell_fails_v6():
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(
        "| scripts/foo.py | callers | grep | pass |", "| scripts/foo.py | callers | grep | pass ||"
    )
    errs = validate(trace)["errors"]
    assert any(e.startswith("V6: unrecognised result") for e in errs)


@pytest.mark.parametrize(
    "disclosed",
    ["| callers | grep | pass |", "| scripts/foo.py | callers | grep | pass ||"],
)
def test_disclosure_row_differing_only_in_an_empty_outer_cell_is_altered(disclosed):
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(
        "| scripts/foo.py | callers | grep | pass |",
        "|| callers | grep | pass |" if disclosed.startswith("| call") else _ROW,
    )
    h = make_handoff().replace(_ROW, disclosed)
    assert "omits or alters trace row" in _errs(disc(h, trace=trace))


_TWO_ITEMS = ["- first item", "- second item"]


def _items_trace(items):
    return make_trace(STEP, BASE, HEAD, FILES).replace(
        "- wiring item X, checked by grep", "\n".join(items)
    )


def test_untraced_items_copied_exactly_pass():
    trace = _items_trace(_TWO_ITEMS)
    assert disc(make_handoff(trace=trace), trace=trace)["valid"]


def test_untraced_items_heading_missing_fails():
    h = make_handoff().replace(f"{ITEMS_H}\n", "", 1)
    assert f"disclosure missing the copied heading {ITEMS_H!r}" in disc(h)["errors"]


def test_untraced_items_extra_line_fails():
    trace = _items_trace(_TWO_ITEMS)
    h = make_handoff(trace=trace).replace("- second item", "- second item\n- sneaked in")
    assert (
        f"disclosure has a line under {ITEMS_H!r} that is not in the trace: - sneaked in"
        in disc(h, trace=trace)["errors"]
    )


def test_untraced_items_reordered_fails():
    trace = _items_trace(_TWO_ITEMS)
    h = make_handoff(trace=trace).replace(
        "- first item\n- second item", "- second item\n- first item"
    )
    assert (
        "disclosed untraced items differ from the trace in order or count"
        in disc(h, trace=trace)["errors"]
    )


def test_untraced_items_omitted_line_fails():
    trace = _items_trace(_TWO_ITEMS)
    h = make_handoff(trace=trace).replace("\n- second item", "")
    assert "disclosure omits untraced item: - second item" in disc(h, trace=trace)["errors"]


def test_untraced_items_duplicate_count_must_match():
    trace = _items_trace(["- same", "- same"])
    h = make_handoff(trace=trace).replace("- same\n- same", "- same")
    assert "disclosure omits untraced item: - same" in disc(h, trace=trace)["errors"]


def test_v5_path_in_parentheses_matches():
    trace = make_trace(STEP, BASE, HEAD, FILES).replace(
        "| scripts/foo.py | callers", "| foo (scripts/foo.py) | callers"
    )
    assert validate(trace)["valid"]


# ---------------------------------------------------------------------------
# AM-3: no closing references in the disclosure (TD 10(h), T-K1..T-K4)
# ---------------------------------------------------------------------------

CLOSING = load_module_from_path(
    "closing_keywords_for_tests", REPO / "scripts/automation/closing_keywords.py"
)
GUARD_SLUG = "thurlow-research/HumanOversightSystem"
_OLD_FORM_ERR = (
    'disclosure writes until-closed as "#N"; GitHub\'s closing-keyword guard '
    '(scripts/automation/closing_keywords.py) reads "closed #N" as closing issue N, '
    'so write "until-closed: issue N"'
)


def _section_text(handoff):
    lines = handoff.split("\n")
    start = lines.index(HEADING)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("# ")), len(lines))
    return "\n".join(lines[start:end])


def test_k1_new_form_matches_the_suspension_number_as_an_integer():
    res = disc(make_handoff(susp=SHIPPED_SUSP), susp=SHIPPED_SUSP)
    assert res["valid"], res["errors"]
    assert "until-closed: issue 2162" in make_handoff(susp=SHIPPED_SUSP)


def test_k1_none_matches_a_suspension_without_until_closed():
    susp = susp_text("SUSPENDED: dep-mapper expires: 2026-12-31")
    h = make_handoff(susp=susp)
    assert "until-closed: none" in h and disc(h, susp=susp)["valid"]


def test_k1_a_different_issue_number_is_a_mismatch_naming_the_wanted_issue():
    susp = susp_text("SUSPENDED: dep-mapper expires: 2026-12-31 until-closed: #2163")
    res = disc(make_handoff(), susp=susp)
    assert "disclosed until-closed ['issue 2162'] != suspension 'issue 2163'" in res["errors"]


@pytest.mark.parametrize("old", ["until-closed: #2162", "until-closed: GH-2162"])
def test_k2_old_form_fails_with_its_own_message_and_an_r8_error(old):
    h = make_handoff().replace("until-closed: issue 2162", old)
    res = disc(h)
    assert not res["valid"] and _OLD_FORM_ERR in res["errors"]
    assert any("is a GitHub closing reference to 2162;" in e for e in res["errors"])
    assert "disclosed until-closed absent != suspension 'issue 2162'" in res["errors"]


def test_k2_a_trailing_word_character_after_the_number_is_absent():
    h = make_handoff().replace("until-closed: issue 2162", "until-closed: issue 2162x")
    assert "disclosed until-closed absent != suspension 'issue 2162'" in disc(h)["errors"]


@pytest.mark.parametrize("suffix", list(SUFFIX_CASES), ids=list(SUFFIX_CASES))
def test_k3_faithful_disclosures_have_no_closing_reference_for_the_real_guard(suffix):
    trace = make_trace(STEP, BASE, HEAD, FILES)
    h = make_handoff(trace=trace, susp=SHIPPED_SUSP, suffix=SUFFIX_CASES[suffix])
    assert CLOSING.find_closing_refs(_section_text(h), GUARD_SLUG) == []


def test_k3_real_guard_cli_accepts_a_generated_handoff_without_closes(tmp_path):
    body = tmp_path / "body.md"
    body.write_text(make_handoff(susp=SHIPPED_SUSP), encoding="utf-8")
    cmd = [sys.executable, str(REPO / "scripts/automation/closing_keywords.py"), "check"]
    ok = subprocess.run(
        [*cmd, "--repo-slug", GUARD_SLUG, "--body-file", str(body)], capture_output=True, text=True
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    body.write_text(make_handoff().replace("issue 2162", "#2162"), encoding="utf-8")
    bad = subprocess.run(
        [*cmd, "--repo-slug", GUARD_SLUG, "--body-file", str(body)], capture_output=True, text=True
    )
    assert bad.returncode == 1 and "2162" in bad.stdout  # the defect AM-3 fixes


_CLOSING_CASES = [
    ("fixes #12", "12"),
    ("Resolved: #12", "12"),
    ("closes GH-12", "12"),
    ("fix o/r#12", "o/r#12"),
    ("closed https://github.com/o/r/issues/12", "o/r#12"),
    ("see fixes\n#12", "12"),
]


@pytest.mark.parametrize("text,key", _CLOSING_CASES)
def test_k4_closing_reference_in_a_section_line_is_an_r8_error(text, key):
    h, k = put(make_handoff(), text)
    errs = disc(h)["errors"]
    suffix = f"is a GitHub closing reference to {key}; merging the PR would close it. "
    assert any(
        e.startswith(f'disclosure line {k}: "')
        and suffix + 'Reword it (for example "issue N")' in e
        for e in errs
    ), errs


@pytest.mark.parametrize("text,key", _CLOSING_CASES)
def test_k4_closing_reference_in_a_trace_item_fails_v9(text, key):
    trace = _items_trace([f"- {text}"])
    k = lineno(trace, text.split("\n")[0])
    errs = validate(trace)["errors"]
    assert any(
        e.startswith(f'V9: {ITEMS_H} line {k}: "')
        and f"is a GitHub closing reference to {key};" in e
        for e in errs
    ), errs


@pytest.mark.parametrize("text", ["fixed in commit 1a2b3c", "the closed issue 2162"])
def test_k4_ordinary_words_are_not_closing_references(text):
    h, _ = put(make_handoff(), text)
    assert not any("closing reference" in e for e in disc(h)["errors"])
    assert not any(
        "closing reference" in e for e in validate(_items_trace([f"- {text}"]))["errors"]
    )


def test_k4_unloadable_guard_module_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_CLOSING_KEYWORDS_PATH", tmp_path / "missing.py")
    msg = "cannot be checked for closing references: closing_keywords.py could not be loaded"
    assert f"disclosure {msg}" in disc(make_handoff())["errors"]
    assert f"V9: {CALLERS_H}: {msg}" in validate(make_trace(STEP, BASE, HEAD, FILES))["errors"]


# ---------------------------------------------------------------------------
# Mutation-survivor pins for _stderr_line and _table_block_errors (#2214).
# Each test names the behaviour it pins; the mutants it kills are the mutmut
# ones in these two helpers (see the unit-test sign-off for the measured scores).
# ---------------------------------------------------------------------------

_C = "## Callers / readers checked"
_I = "## Items dep-mapper left untraced"
_START_END = 'table row must start and end with "|"'
_TB_NO_DELIM = "callers table has no delimiter row matching its header"
_BEFORE_AFTER = (
    "table must have a blank line or section heading before it and a blank line after it"
)
_NOT_UNDER_CALLERS = f'the table must be the copied callers table, under "{_C}"'


def tbe(lines, kind_d, mode="disclosure", s=0, e=None):
    return sm._table_block_errors(lines, s, len(lines) if e is None else e, kind_d, mode)


def _stderr(raw: bytes) -> str:
    return sm._stderr_line(SimpleNamespace(stderr=raw))


def test_stderr_line_empty_stderr_gives_empty_string():
    assert _stderr(b"") == ""
    assert _stderr(b" \n\t\n  \n") == ""


def test_stderr_line_returns_first_non_blank_line_stripped():
    assert _stderr(b"\n   \n  fatal: bad thing  \nsecond line\n") == "fatal: bad thing"


def test_stderr_line_is_capped_at_exactly_200_chars():
    assert _stderr(b"x" * 250) == "x" * 200
    assert len(_stderr(b"y" * 201)) == 200
    assert _stderr(b"z" * 200) == "z" * 200


def test_stderr_line_replaces_undecodable_bytes_instead_of_raising():
    assert _stderr(b"bad \xff byte") == "bad � byte"


GOOD = [_C, "", "| A | B |", "|---|---|", "| x | y |", "", _I, "", "- item"]


def test_table_block_well_formed_disclosure_table_has_no_errors():
    assert tbe(GOOD, [2, 3, 4]) == []


def test_table_block_two_char_row_is_valid_but_one_char_row_is_not():
    two = [_C, "", "| A |", "|---|", "||", ""]
    assert tbe(two, [2, 3, 4]) == []
    one = [_C, "", "| A |", "|---|", "|", ""]
    assert tbe(one, [2, 3, 4]) == [(5, _START_END)]


def test_table_block_header_and_delimiter_only_table_is_valid():
    assert tbe([_C, "", "| A |", "|---|", ""], [2, 3]) == []


def test_table_block_trailing_spaces_are_ignored_on_every_line():
    lines = [_C + "  ", "| A | B |  ", "|---|---|  ", "| x | y |  ", "  "]
    assert tbe(lines, [1, 2, 3]) == []
    lines2 = [_C + "  ", "", "| A | B |  ", "|---|---|  ", "| x | y |  ", "   "]
    assert tbe(lines2, [2, 3, 4]) == []


def test_table_block_trailing_tab_is_not_stripped_from_a_data_row():
    lines = [_C, "", "| A |", "|---|", "| x |\t", ""]
    assert tbe(lines, [2, 3, 4]) == [
        (5, _START_END),
        (5, "table row has 2 cells, header has 1"),
    ]


def test_table_block_trailing_tab_is_not_stripped_from_the_header():
    lines = [_C, "", "| A |\t", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [
        (3, _START_END),
        (None, _TB_NO_DELIM),
        (5, "table row has 1 cells, header has 2"),
    ]


def test_table_block_trailing_tab_is_not_stripped_from_the_delimiter():
    lines = [_C, "", "| A |", "|---|\t", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [(4, _START_END), (None, _TB_NO_DELIM)]


def test_table_block_tab_only_line_after_the_table_is_not_blank():
    lines = [_C, "", "| A |", "|---|", "| x |", "\t"]
    assert tbe(lines, [2, 3, 4]) == [(6, _BEFORE_AFTER)]


def test_table_block_tab_only_line_before_the_table_is_not_blank():
    lines = [_C, "\t", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [(3, _BEFORE_AFTER)]


def test_table_block_callers_heading_with_trailing_tab_is_not_the_heading():
    lines = [_C + "\t", "", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [(3, _NOT_UNDER_CALLERS)]


def test_table_block_trailing_x_is_not_stripped_from_a_data_row():
    lines = [_C, "", "| A |", "|---|", "| x |X", ""]
    assert tbe(lines, [2, 3, 4]) == [
        (5, _START_END),
        (5, "table row has 2 cells, header has 1"),
    ]


def test_table_block_trailing_x_is_not_stripped_from_the_header():
    lines = [_C, "", "| A |X", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [
        (3, _START_END),
        (None, _TB_NO_DELIM),
        (5, "table row has 1 cells, header has 2"),
    ]


def test_table_block_trailing_x_is_not_stripped_from_the_delimiter():
    lines = [_C, "", "| A |", "|---|X", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [(4, _START_END), (None, _TB_NO_DELIM)]


def test_table_block_line_after_the_table_that_ends_in_x_is_not_blank():
    lines = [_C, "", "| A |", "|---|", "| x |", "X"]
    assert tbe(lines, [2, 3, 4]) == [(6, _BEFORE_AFTER)]


def test_table_block_line_before_the_table_that_ends_in_x_is_not_a_heading():
    lines = [_C + "X", "| A |", "|---|", "| x |", ""]
    out = tbe(lines, [1, 2, 3])
    assert (2, _BEFORE_AFTER) in out


def test_table_block_callers_heading_ending_in_x_is_not_the_heading():
    lines = [_C + "X", "", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4]) == [(3, _NOT_UNDER_CALLERS)]


def test_table_block_callers_heading_before_the_section_start_is_not_found():
    lines = [_C, "", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [2, 3, 4], s=2, e=6) == [(3, _NOT_UNDER_CALLERS)]


def test_table_block_table_at_end_of_input_needs_no_trailing_blank_line():
    assert tbe([_C, "", "| A |", "|---|", "| x |"], [2, 3, 4]) == []


def test_table_block_head_at_index_zero_has_no_line_before_it():
    lines = ["| A |", "|---|", "| x |", ""]
    out = tbe(lines, [0, 1, 2])
    assert (1, _BEFORE_AFTER) in out


def test_table_block_head_at_index_one_after_a_blank_line_is_valid():
    lines = ["", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [1, 2, 3], mode="callers") == []


def test_table_block_prose_before_a_table_in_disclosure_is_rejected_even_at_section_start():
    lines = ["prose line", "| A |", "|---|", "| x |", ""]
    out = tbe(lines, [1, 2, 3], s=1, e=5)
    assert (2, _BEFORE_AFTER) in out


def test_table_block_callers_mode_table_may_directly_follow_the_section_start_line():
    lines = ["prose line", "| A |", "|---|", "| x |", ""]
    assert tbe(lines, [1, 2, 3], mode="callers", s=1, e=5) == []


def test_table_block_callers_mode_prose_before_a_later_table_is_rejected():
    lines = ["", "prose line", "| A |", "|---|", "| x |", ""]
    out = tbe(lines, [2, 3, 4], mode="callers", s=0, e=6)
    assert (3, _BEFORE_AFTER) in out


# ---------------------------------------------------------------------------
# (i) SHA-pinned human gate (#2392, TD-2214 AM-4)
# ---------------------------------------------------------------------------

S3_GENERIC = "S3: step is behind the human gate"


def _egprefix(repo, detail):
    return (
        "S3: contract/step-manifest.yaml in the working tree does not match head "
        f"{repo.head[:12]} ({detail}); commit or restore it, then re-run"
    )


def _eff(repo, step=STEP, head=None):
    main = sm.read_default_branch_suspension(repo.root)
    return sm.effective_manifest_human_gate(step, head or repo.head, main, repo.root)


def _write_wt(repo, text):
    (repo.root / MANIFEST_PATH).write_text(text)


@pytest.mark.parametrize(
    "committed,edited", [(MANIFEST_TRUE, MANIFEST_FALSE), (MANIFEST_FALSE, MANIFEST_TRUE)]
)
def test_g1_uncommitted_edit_fails_in_either_direction(
    repo, use_sm, monkeypatch, capsys, committed, edited
):
    regen(repo, base_manifest=committed, head_manifest=committed)
    _write_wt(repo, edited)
    res = req_w18(repo)
    assert not res.passed and _egprefix(repo, "modified") in res.detail
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and f"ERROR=dep-low: {_egprefix(repo, 'modified')}" in out


def test_g2_uncommitted_deletion_fails(repo, use_sm, monkeypatch, capsys):
    regen(repo, base_manifest=MANIFEST_TRUE, head_manifest=MANIFEST_TRUE)
    (repo.root / MANIFEST_PATH).unlink()
    assert _egprefix(repo, "deleted") in req_w18(repo).detail
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and f"ERROR=dep-low: {_egprefix(repo, 'deleted')}" in out


def test_g2_untracked_manifest_added_but_not_committed(repo, use_sm, monkeypatch, capsys):
    regen(repo)
    _write_wt(repo, MANIFEST_FALSE)
    assert _egprefix(repo, "added but not committed") in req_w18(repo).detail
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and _egprefix(repo, "added but not committed") in out


def test_g3_committed_loosening_is_overridden_by_default_branch(repo, use_sm, monkeypatch, capsys):
    regen(repo, base_manifest=MANIFEST_TRUE, head_manifest=MANIFEST_FALSE)
    assert S3_GENERIC in req_w18(repo).detail
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and S3_GENERIC in out and "working tree" not in out


def test_g4_committed_tightening_takes_effect_and_controls_pass(repo, use_sm, monkeypatch, capsys):
    for base in (MANIFEST_FALSE, None):
        regen(repo, base_manifest=base, head_manifest=MANIFEST_TRUE)
        assert S3_GENERIC in req_w18(repo).detail
        assert cli(monkeypatch, capsys, repo)[0] == 4
    for both in (MANIFEST_FALSE, None):
        regen(repo, base_manifest=both, head_manifest=both)
        assert req_w18(repo).passed
        assert cli(monkeypatch, capsys, repo)[0] == 0


E_G1 = "S3: human gate not verified: the default-branch read failed (see S4); failing closed"


def test_g5_default_read_failure_is_e_g1_before_any_manifest_read(repo, monkeypatch):
    calls = _fake_git(monkeypatch, lambda args: NotImplemented)
    for dr in (
        {"error": "S4: x", "sha": None, "branch": None, "text": None},
        {"error": None, "sha": None, "branch": "main", "text": None},
        {"error": None, "sha": "-x", "branch": "main", "text": None},
    ):
        assert sm.effective_manifest_human_gate(STEP, repo.head, dr, repo.root) == {
            "flag": True,
            "error": E_G1,
        }
    assert calls == []


def test_g5_cli_prints_both_s4_and_e_g1(repo, monkeypatch, capsys):
    monkeypatch.setattr(sm, "_default_ls_remote", lambda root=".": (None, None, "x"))
    calls = _fake_git(monkeypatch, lambda args: NotImplemented)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4
    assert f"ERROR=dep-low: {_ef2('x')}" in out and f"ERROR=dep-low: {E_G1}" in out
    assert not any(MANIFEST_PATH in a for c in calls for a in c)


def _commit_symlink(repo, target_text="steps:\n"):
    (repo.root / "target.yaml").write_text(target_text)
    (repo.root / MANIFEST_PATH).unlink(missing_ok=True)
    os.symlink("../target.yaml", repo.root / MANIFEST_PATH)
    _git(repo.root, "add", "target.yaml", MANIFEST_PATH)


def test_g6_symlink_at_head_is_e_g3(repo):
    regen(repo)
    _commit_symlink(repo)
    _git(repo.root, "commit", "-q", "-m", "link")
    head = _rev(repo.root)
    res = _eff(repo, head=head)
    assert res == {
        "flag": True,
        "error": f"S3: could not read {MANIFEST_PATH} at head {head[:12]} "
        "(not a regular file); failing closed, re-run",
    }


def test_g6_symlink_at_default_sha_is_e_g3(repo):
    regen(repo)
    _git(repo.root, "reset", "-q", "--hard", "HEAD~1")
    _commit_symlink(repo)
    _git(repo.root, "commit", "-q", "--amend", "-m", "base")
    base = _rev(repo.root)
    _git(repo.root, "push", "-q", "--force", "origin", "main")
    _git(repo.root, "fetch", "-q", "origin")
    _git(repo.root, "rm", "-q", "-f", MANIFEST_PATH)
    _write_wt(repo, MANIFEST_FALSE)
    _git(repo.root, "add", MANIFEST_PATH)
    _git(repo.root, "commit", "-q", "-m", "regular")
    res = _eff(repo, head=_rev(repo.root))
    assert res == {
        "flag": True,
        "error": f"S3: could not read {MANIFEST_PATH} at origin/main {base[:12]} "
        "(not a regular file); failing closed, re-run",
    }


def test_g6_working_tree_symlink_with_identical_bytes_fails(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    (repo.root / MANIFEST_PATH).unlink()
    (repo.root.parent / "same.yaml").write_text(MANIFEST_FALSE)
    os.symlink(repo.root.parent / "same.yaml", repo.root / MANIFEST_PATH)
    assert _eff(repo)["error"] == _egprefix(repo, "not a regular file")


@pytest.mark.parametrize(
    "verb,result,why",
    [
        ("ls-tree", None, "timeout"),
        ("show", None, "timeout"),
        ("show", _cp(128, err=b"fatal: bad object\n"), "exit 128: fatal: bad object"),
    ],
)
def test_g6_git_failures_at_head(repo, monkeypatch, verb, result, why):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    main = sm.read_default_branch_suspension(repo.root)

    def handler(args):
        hit = args[0] == verb and any(MANIFEST_PATH in x for x in args)
        return result if hit else NotImplemented

    _fake_git(monkeypatch, handler)
    res = sm.effective_manifest_human_gate(STEP, repo.head, main, repo.root)
    assert res == {
        "flag": True,
        "error": f"S3: could not read {MANIFEST_PATH} at head {repo.head[:12]} "
        f"({why}); failing closed, re-run",
    }


def test_g6_short_head_sha_is_e_g4(repo):
    main = sm.read_default_branch_suspension(repo.root)
    res = sm.effective_manifest_human_gate(STEP, repo.head[:12], main, repo.root)
    assert res == {
        "flag": True,
        "error": f"S3: head {repo.head[:12]!r} is not a full SHA; cannot pin the step manifest",
    }


def test_g7_absent_everywhere_is_false(repo, use_sm):
    assert _eff(repo) == {"flag": False, "error": None}
    assert req_w18(repo).passed


def _default_flag(repo, default_manifest, head_manifest=MANIFEST_FALSE):
    regen(repo, base_manifest=default_manifest, head_manifest=head_manifest)
    return _eff(repo)


def test_g8_default_lists_only_other_step(repo):
    other = "steps:\n  - id: other-step\n    human_gate_required: true\n"
    assert _default_flag(repo, other) == {"flag": False, "error": None}
    assert _default_flag(repo, other, head_manifest=other)["flag"] is True  # head strict rule


@pytest.mark.parametrize(
    "default",
    [
        f"x: &a 1\nsteps:\n  - id: {STEP}\n    human_gate_required: false\n",
        f"steps:\n  - id: {STEP}\n    human_gate_required: maybe\n",
        "foo: bar\n",
    ],
)
def test_g8_non_canonical_default_is_true(repo, default):
    assert _default_flag(repo, default)["flag"] is True


@pytest.mark.parametrize("unlisted_step", [True, False])
def test_g8_undecodable_bytes_are_true_without_error(repo, unlisted_step):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    (repo.root / MANIFEST_PATH).write_bytes(b"steps:\n  - id: s1\n\xff\xfe\n")
    _git(repo.root, "add", MANIFEST_PATH)
    _git(repo.root, "commit", "-q", "-m", "bad")
    res = sm.read_manifest_gate_at(_rev(repo.root), STEP, repo.root, unlisted_step=unlisted_step)
    assert res["flag"] is True and res["error"] is None


def test_g9_human_gate_error_is_required_and_replaces_s3():
    with pytest.raises(TypeError):
        sm.check_suspended_resolutions(
            make_risk(BASE, HEAD),
            STEP,
            BASE,
            HEAD,
            "HIGH",
            False,
            FILES,
            susp_text(),
            susp_text(),
            main_suspension_error=None,
        )
    res = run_check(human_gate_error="S3: X", human_gate_required=False)
    errs = errors_of(res)
    assert not res["ok"] and "S3: X" in errs
    assert not any("step is behind the human gate" in e for e in errs)


def test_g10_scan_matches_path_function_and_none_maps_to_true(tmp_path):
    bodies = [
        "steps:\n  - id: s1 # note\n    human_gate_required: true\n",
        "steps:\n  - id: 's1'\n    human_gate_required: false # ok\n",
        "steps:\n  - id: other\n    human_gate_required: false\n",
        "foo: bar\n",
        "steps:\n  - id: s1\n    human_gate_required: maybe\n",
        "steps:\n  - id: s1\n    name: y\n",
    ]
    for body in bodies:
        path = _manifest(tmp_path, body)
        scan = sm._manifest_gate_scan(body, "s1")
        assert sm.manifest_human_gate_required(path, "s1") is (True if scan is None else scan)


def test_g10_manifest_override_does_not_reach_req_w18(repo, use_sm, monkeypatch):
    regen(repo, base_manifest=MANIFEST_TRUE, head_manifest=MANIFEST_TRUE)
    other = repo.factory.mktemp("override") / "m.yaml"
    other.write_text(MANIFEST_FALSE)
    monkeypatch.setattr(
        pr_readiness,
        "_check_inner_loop_tests",
        lambda root: pr_readiness.CheckResult("REQ-W-01", True, "stub"),
    )
    result = pr_readiness.assess_pr_readiness(
        "cid",
        repo.base,
        repo.head,
        STEP,
        "HIGH",
        repo_root=repo.root,
        step_manifest_path=other,
        write_state=False,
    )
    (w18,) = [c for c in result.checks if c.check_id == "REQ-W-18"]
    assert not w18.passed and S3_GENERIC in w18.detail


def _spy_run(monkeypatch):
    argvs = []
    real = subprocess.run

    def spy(argv, *a, **k):
        argvs.append(list(argv))
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    return argvs


def test_g11_no_extra_git_when_no_suspension_applies(repo, use_sm, monkeypatch, capsys):
    (repo.oversight / "validators/risk-assessment.md").write_text("# R\nblocking_findings: []\n")
    argvs = _spy_run(monkeypatch)
    assert cli(monkeypatch, capsys, repo)[0] == 0
    assert req_w18(repo).passed
    flat = [a for argv in argvs for a in argv]
    assert "ls-remote" not in flat and not any(MANIFEST_PATH in a for a in flat)


def test_g11_one_ls_remote_and_default_read_by_sha(repo, use_sm, monkeypatch, capsys):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    argvs = _spy_run(monkeypatch)
    assert cli(monkeypatch, capsys, repo)[0] == 0
    assert sum("ls-remote" in argv for argv in argvs) == 1
    trees = [argv[3:] for argv in argvs if "ls-tree" in argv and MANIFEST_PATH in argv]
    assert ["ls-tree", "--full-tree", "-z", repo.head, "--", MANIFEST_PATH] in trees
    assert ["ls-tree", "--full-tree", "-z", repo.base, "--", MANIFEST_PATH] in trees


def test_g12_cli_floor_is_kept(repo, monkeypatch, capsys):
    code, out = cli(monkeypatch, capsys, repo, gate=("--human-gate-required", "true"))
    assert code == 4 and S3_GENERIC in out


FOLDED = f"steps:\n  - id: >-\n      {STEP}\n    human_gate_required: true\n"


G13_DEFAULTS = [
    FOLDED,
    f"  steps:\n    - id: {STEP}\n      human_gate_required: true\n",
    f"steps:\n  - id: other\n\t- id: {STEP}\n",
    'steps:\n  - id: "s\\x31"\n    human_gate_required: true\n',
    f"steps:\n  - id: !!str {STEP}\n    human_gate_required: true\n",
    f"steps:\n  - id: other\n    id: {STEP}\n    human_gate_required: true\n",
    f"steps:\n  - id: other\n    human_gate_required: false\n# {STEP} is gated here\n",
    "foo: bar\n",
]


@pytest.mark.parametrize("default", G13_DEFAULTS)
def test_g13_non_canonical_default_gates_the_step(repo, default):
    assert _default_flag(repo, default) == {"flag": True, "error": None}


def test_g13_scan_without_steps_line_is_true_not_none():
    assert sm._manifest_gate_scan("foo: bar\n", STEP) is True
    assert sm._manifest_gate_scan("steps:\n  - id: other\n", STEP) is None


def test_g13_control_unlisted_and_absent_step_is_false(repo):
    other = "steps:\n  - id: other-step\n    human_gate_required: true\n"
    assert _default_flag(repo, other) == {"flag": False, "error": None}


# --- AM-4 residual branch coverage (unit-test pass, #2392) -------------------


def test_scan_flow_style_steps_line_is_true():
    assert sm._manifest_scan("steps: [a, b]\n", STEP) == (True, [])
    assert sm._manifest_scan("steps: {a: b}\n", STEP) == (True, [])


def test_scan_top_level_key_after_steps_ends_the_block():
    body = (
        f"steps:\n  - id: {STEP}\n    human_gate_required: false\n"
        "other:\n  human_gate_required: true\n"
    )
    assert sm._manifest_scan(body, STEP) == (False, [STEP])


def test_scan_line_before_the_first_item_is_not_canonical():
    body = f"steps:\n  human_gate_required: true\n  - id: {STEP}\n"
    assert sm._manifest_scan(body, STEP) == (True, [])


def test_read_manifest_gate_at_rejects_a_non_sha_without_running_git(repo, monkeypatch):
    calls = _fake_git(monkeypatch, lambda args: NotImplemented)
    for bad in ("abc123", None, "-x" + "a" * 38):
        res = sm.read_manifest_gate_at(bad, STEP, repo.root, unlisted_step=True)
        assert res == {"flag": True, "blob": None, "error": "not a full SHA"}
    assert calls == []


def test_read_manifest_gate_at_ls_tree_nonzero_exit_is_an_error(repo, monkeypatch):
    _fake_git(
        monkeypatch,
        lambda args: _cp(128, err=b"fatal: bad tree\n") if args[0] == "ls-tree" else NotImplemented,
    )
    res = sm.read_manifest_gate_at(repo.head, STEP, repo.root, unlisted_step=True)
    assert res == {"flag": True, "blob": None, "error": "exit 128: fatal: bad tree"}


def test_working_tree_lstat_oserror_is_a_mismatch(repo, monkeypatch):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    real = os.lstat

    def fake(path, *a, **k):
        if str(path).endswith(MANIFEST_PATH):
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **k)

    monkeypatch.setattr(sm.os, "lstat", fake)
    assert _eff(repo) == {"flag": True, "error": _egprefix(repo, "unreadable: Permission denied")}


def test_working_tree_read_oserror_is_a_mismatch(repo, monkeypatch):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    real = sm.Path.read_bytes

    def fake(self):
        if str(self).endswith(MANIFEST_PATH):
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(sm.Path, "read_bytes", fake)
    assert _eff(repo) == {"flag": True, "error": _egprefix(repo, "unreadable: Permission denied")}


# --- AM-4 security round 1 (#2392): numeric-alias ids, --full-tree -----------

CANONICAL_HEAD = f"steps:\n  - id: {STEP}\n    human_gate_required: false\n"


@pytest.mark.parametrize(
    "alias", ["007", "0x7", "0o7", "0b111", "1_0", "+7", "7.0", "1e1", "-1", ".5", "00"]
)
def test_sec_r1_numeric_alias_id_on_default_gates_the_step(repo, alias):
    default = f"steps:\n  - id: {alias}\n    human_gate_required: false\n"
    res = _default_flag(repo, default, head_manifest=CANONICAL_HEAD)
    assert res == {"flag": True, "error": None}


@pytest.mark.parametrize("canonical", ["0", "7", "10"])
def test_sec_r1_canonical_numeric_id_control_stays_false(repo, canonical):
    default = f"steps:\n  - id: {canonical}\n    human_gate_required: true\n"
    res = _default_flag(repo, default, head_manifest=CANONICAL_HEAD)
    assert res == {"flag": False, "error": None}


def test_sec_r1_id_is_canonical_letter_start_unaffected():
    assert sm._id_is_canonical("other-step") and sm._id_is_canonical("v1.2")
    assert not sm._id_is_canonical("0x7") and not sm._id_is_canonical("a b")


def test_sec_r1_manifest_read_from_a_subdirectory_of_the_repo(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    sub = repo.root / "subdir"
    sub.mkdir()
    res = sm.read_manifest_gate_at(repo.head, STEP, sub, unlisted_step=True)
    assert res["error"] is None and res["blob"] is not None and res["flag"] is False


def test_cli_prints_whole_file_s0_errors_and_exits_4(repo, monkeypatch, capsys):
    """Whole-file (S0) failures are printed as bare ERROR= lines (no finding id) and exit 4."""
    stale = "a" * 40
    (repo.oversight / "validators/risk-assessment.md").write_text(make_risk(stale, repo.head))
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and "RESULT=fail" in out
    assert f"ERROR=S0: risk-assessment range {stale!r}.." in out


# --- AM-4 SR (#2392): the scanner is never looser than a YAML parser ---------

G_FALSE_ITEM = "  - id: s1\n    human_gate_required: false\n"
G_TRUE_ITEM = "  - id: s1\n    human_gate_required: true\n"

G14_REPRO = (
    "steps:\n  - id: s1\n    id: s9\n    human_gate_required: false\n"
    '  - id: "s\\x31"\n    human_gate_required: true\n'
)
G14 = {
    "repro": G14_REPRO,
    "duplicate_id_alone": "steps:\n  - id: s1\n    id: s1\n    human_gate_required: false\n",
    "duplicate_flag_in_non_target_item": (
        "steps:\n" + G_FALSE_ITEM + "  - id: other\n    human_gate_required: false\n"
        "    human_gate_required: false\n"
    ),
    "separate_items_same_id_one_true": "steps:\n" + G_FALSE_ITEM + G_TRUE_ITEM,
}
_BLOCK1 = "steps:\n" + G_FALSE_ITEM + "  - id: other\n"
G15 = {
    "second_block_indent4": _BLOCK1
    + "name: x\nsteps:\n    - id: s1\n      human_gate_required: true\n",
    "second_block_indent0": _BLOCK1 + "name: x\nsteps:\n- id: s1\n  human_gate_required: true\n",
    "double_quoted_second": _BLOCK1 + '"steps":\n' + G_TRUE_ITEM,
    "single_quoted_second": _BLOCK1 + "'steps':\n" + G_TRUE_ITEM,
    "space_before_colon_second": _BLOCK1 + "steps :\n" + G_TRUE_ITEM,
    "explicit_key_second": _BLOCK1 + "? steps\n" + G_TRUE_ITEM,
    "only_quoted_steps": '"steps":\n' + G_FALSE_ITEM,
    "marker_after_content": "steps:\n" + G_FALSE_ITEM + "---\nname: x\n",
    "document_end_after_content": "steps:\n" + G_FALSE_ITEM + "...\n",
}
G15B = {
    "adjacent_quoted_steps": _BLOCK1 + '"steps":[a]\n',
    "adjacent_plain_steps": _BLOCK1 + "steps:[a]\n",
    "quoted_steps_with_items": "steps:\n" + G_FALSE_ITEM + '"steps":\n' + G_TRUE_ITEM,
    "leading_tagged_marker": "--- !tag\nsteps:\n" + G_FALSE_ITEM,
    "leading_marker_with_steps": "--- steps: []\n" + G_FALSE_ITEM,
    "leading_document_end": "...\nsteps:\n" + G_FALSE_ITEM,
    "commented_marker_after_content": "steps:\n" + G_FALSE_ITEM + "--- # c\n",
    "two_leading_markers": "---\n---\nsteps:\n" + G_FALSE_ITEM,
}
G15_CONTROLS = {
    "bare_leading_marker": "---\nsteps:\n" + G_FALSE_ITEM,
    "commented_leading_marker": "--- # header comment\nsteps:\n" + G_FALSE_ITEM,
}
G16 = {
    "escaped_flag_key": 'steps:\n  - id: s1\n    "human_gate_\\x72equired": true\n',
    "escaped_flag_key_mid_word": 'steps:\n  - id: s1\n    "human_gate_r\\x65quired": true\n',
    "escaped_id_key": "steps:\n"
    + G_FALSE_ITEM
    + '  - "i\\x64": s1\n    human_gate_required: true\n',
    "tagged_id_key": "steps:\n"
    + G_FALSE_ITEM
    + "  - !!str id: s1\n    human_gate_required: true\n",
    "explicit_key": "steps:\n  - id: s1\n    ? human_gate_required\n    : true\n",
    "single_quote_escape_key": "steps:\n  - id: s1\n    'human''gate': x\n",
}
G16B = {
    "adjacent_colon_id": (
        "steps:\n" + G_FALSE_ITEM + '  - "i\\x64":s1\n    human_gate_required: true\n'
    ),
    "adjacent_colon_flag": 'steps:\n  - id: s1\n    "human_gate_\\x72equired":true\n',
    "unclosed_double": 'steps:\n  - id: s1\n    "human_gate_required: true\n',
    "unclosed_single": "steps:\n" + G_FALSE_ITEM + "  - 'id: s1\n    human_gate_required: true\n",
    "single_quote_escape_in_target": "steps:\n  - id: s1\n    'human''gate': x\n",
}
G17 = {
    "escaped_id_next_to_canonical": (
        "steps:\n" + G_FALSE_ITEM + '  - id: "s\\x31"\n    human_gate_required: true\n'
    ),
    "id_on_next_line": (
        "steps:\n" + G_FALSE_ITEM + "  - id:\n      s1\n    human_gate_required: true\n"
    ),
    "numeric_id_007": "steps:\n" + G_FALSE_ITEM + "  - id: 007\n    human_gate_required: true\n",
    "item_without_id": "steps:\n  - name: x\n" + G_FALSE_ITEM,
}
G20_TRUE = [
    '"false"',
    "'false'",
    "'no'",
    "fAlSe",
    "no",
    "No",
    "NO",
    "off",
    "n",
    "null",
    "~",
    "",
    "!!bool false",
    "0x0",
    "00",
    "0.0",
]
G20_FALSE = ["false", "False", "FALSE", "0", "false # comment", "0 # comment"]
G20 = {f"flag={v!r}": f"steps:\n  - id: s1\n    human_gate_required: {v}\n" for v in G20_TRUE}
G20_CONTROLS = {
    f"flag={v!r}": f"steps:\n  - id: s1\n    human_gate_required: {v}\n" for v in G20_FALSE
}
G19_SEVEN = {
    "007": "steps:\n  - id: 7\n    human_gate_required: false\n"
    "  - id: 007\n    human_gate_required: true\n",
    "0x7": "steps:\n  - id: 7\n    human_gate_required: false\n"
    "  - id: 0x7\n    human_gate_required: true\n",
}


def _sr_pinned(repo, text, step=STEP):
    regen(repo, base_manifest=text, head_manifest=text)
    return [
        sm.read_manifest_gate_at(sha, step, repo.root, unlisted_step=u)
        for sha, u in ((repo.head, True), (repo.base, False))
    ]


def _sr_path(repo, text, step=STEP):
    if not hasattr(repo, "sr_dir"):
        repo.sr_dir = repo.factory.mktemp("sr")
    return sm.manifest_human_gate_required(_manifest(repo.sr_dir, text), step)


def _assert_gated(repo, text, step=STEP):
    assert sm._manifest_gate_scan(text, step) is True
    assert _sr_path(repo, text, step) is True
    for read in _sr_pinned(repo, text, step):
        assert read["error"] is None and read["flag"] is True


def _assert_default_gates(repo, default):
    """The default branch has `default`; head lists s1 canonically false: effective True."""
    regen(repo, base_manifest=default, head_manifest=MANIFEST_FALSE)
    assert _eff(repo) == {"flag": True, "error": None}
    assert S3_GENERIC in req_w18_detail(repo)


def req_w18_detail(repo):
    return req_w18(repo).detail


@pytest.mark.parametrize("text", list(G14.values()), ids=list(G14))
def test_g14_duplicate_key_in_one_item_is_true(repo, text):
    _assert_gated(repo, text)


def test_g14_end_to_end_default_branch_repro(repo, use_sm, monkeypatch, capsys):
    _assert_default_gates(repo, G14_REPRO)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and S3_GENERIC in out


@pytest.mark.parametrize("text", list(G15.values()), ids=list(G15))
def test_g15_second_or_noncanonical_steps_key_is_true(repo, text):
    _assert_gated(repo, text)


@pytest.mark.parametrize("text", list(G15B.values()), ids=list(G15B))
def test_g15b_colon_independent_steps_key_and_document_markers_are_true(repo, text):
    _assert_gated(repo, text)


@pytest.mark.parametrize("text", list(G15_CONTROLS.values()), ids=list(G15_CONTROLS))
def test_g15_control_single_leading_marker_stays_false(repo, text):
    assert sm._manifest_gate_scan(text, STEP) is False
    assert _sr_path(repo, text) is False


@pytest.mark.parametrize("text", list(G16.values()), ids=list(G16))
def test_g16_escaped_tagged_or_explicit_keys_are_true(repo, text):
    _assert_gated(repo, text)


@pytest.mark.parametrize("text", list(G16B.values()), ids=list(G16B))
def test_g16b_quoted_span_at_the_start_of_the_body_is_true(repo, text):
    _assert_gated(repo, text)


@pytest.mark.parametrize(
    "text", [G16["escaped_flag_key"], G16["tagged_id_key"], G16B["unclosed_double"]]
)
def test_g16_end_to_end_default_read_is_true(repo, text):
    _assert_default_gates(repo, text)


def test_g16_controls_quoted_keys_without_escapes_are_unchanged(repo):
    assert (
        sm._manifest_gate_scan('steps:\n  - id: s1\n    "human_gate_required": true\n', STEP)
        is True
    )
    adjacent = 'steps:\n  - id: s1\n    "human_gate_required":true\n'
    assert sm._manifest_gate_scan(adjacent, STEP) is True
    false = "steps:\n  - id: s1\n    'human_gate_required': false\n"
    assert sm._manifest_gate_scan(false, STEP) is False
    assert _sr_path(repo, false) is False


@pytest.mark.parametrize("text", list(G17.values()), ids=list(G17))
def test_g17_noncanonical_id_or_missing_id_is_true(repo, text):
    _assert_gated(repo, text)


def test_g17_repro_scans_true_not_false():
    assert sm._manifest_scan(G17["escaped_id_next_to_canonical"], STEP) == (True, [])


def test_g17_control_quoted_id_with_false_is_false(repo):
    text = "steps:\n  - id: 's1'\n    human_gate_required: false\n"
    assert sm._manifest_gate_scan(text, STEP) is False
    assert _sr_path(repo, text) is False
    assert [r["flag"] for r in _sr_pinned(repo, text)] == [False, False]


def _g18_setup(repo, committed=MANIFEST_TRUE):
    regen(repo, base_manifest=committed, head_manifest=committed)
    sub = repo.root / "sub"
    (sub / "contract").mkdir(parents=True)
    return sub


def _eff_at(repo, root):
    main = sm.read_default_branch_suspension(root)
    return sm.effective_manifest_human_gate(STEP, repo.head, main, root)


def _g18_modified(repo):
    sub = _g18_setup(repo)
    _write_wt(repo, MANIFEST_FALSE)
    (sub / MANIFEST_PATH).write_text(MANIFEST_TRUE)
    return sub


def test_g18_subdirectory_repo_root_compares_the_toplevel_manifest(repo):
    sub = _g18_modified(repo)
    assert _eff_at(repo, sub) == {"flag": True, "error": _egprefix(repo, "modified")}


def test_g18_cli_from_a_subdirectory_compares_the_toplevel_manifest(repo, monkeypatch, capsys):
    sub = _g18_modified(repo)
    shutil.copytree(repo.root / ".claudetmp", sub / ".claudetmp")
    monkeypatch.chdir(sub)
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and f"ERROR=dep-low: {_egprefix(repo, 'modified')}" in out


def test_g18_control_clean_toplevel_reads_the_toplevel_file_not_sub(repo):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    (sub / MANIFEST_PATH).write_text(MANIFEST_TRUE)  # differs from head; must be ignored
    assert _eff_at(repo, sub) == {"flag": False, "error": None}


def _e_g5(sub, why):
    return (
        f"S3: could not resolve the git toplevel from {str(sub)!r} ({why}); failing closed, re-run"
    )


def test_g18_rev_parse_timeout_is_e_g5(repo, monkeypatch):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    _fake_git(
        monkeypatch,
        lambda args: (
            None if args[0] == "rev-parse" and "--show-toplevel" in args else NotImplemented
        ),
    )
    assert _eff_at(repo, sub) == {
        "flag": True,
        "error": _e_g5(sub, "timeout or git could not start"),
    }


@pytest.mark.parametrize(
    "stub,why",
    [
        (b"relative/dir\n", "not an absolute directory"),
        (b"/nonexistent-g18-dir\n", "not an absolute directory"),
        (b"\n", "not an absolute directory"),
        (b"\xff\xfe\n", "not an absolute directory"),
    ],
)
def test_g18_unusable_rev_parse_output_is_e_g5(repo, monkeypatch, stub, why):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    _fake_git(
        monkeypatch,
        lambda args: (
            _cp(0, stub) if args[0] == "rev-parse" and "--show-toplevel" in args else NotImplemented
        ),
    )
    assert _eff_at(repo, sub) == {"flag": True, "error": _e_g5(sub, why)}


def test_g18_outside_any_repo_head_read_error_fires_first(repo, scratch_factory):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    main = sm.read_default_branch_suspension(repo.root)
    outside = scratch_factory.mktemp("outside")
    res = sm.effective_manifest_human_gate(STEP, repo.head, main, outside)
    assert res["flag"] is True
    # the head read fails first when the manifest cannot be read outside a repo
    assert res["error"].startswith("S3: could not read")


def test_g18_bare_repo_is_e_g5_exit_128(repo, monkeypatch):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    main = sm.read_default_branch_suspension(repo.root)
    bare = repo.origin
    real = sm._git

    def wrapper(args, repo_root, env=None):
        # head and default reads still use the working repo; only G4 addresses the bare one
        return real(args, bare if args[0] == "rev-parse" else repo_root, env)

    monkeypatch.setattr(sm, "_git", wrapper)
    res = sm.effective_manifest_human_gate(STEP, repo.head, main, repo.root)
    assert res["flag"] is True
    assert res["error"].startswith(
        f"S3: could not resolve the git toplevel from {str(repo.root)!r} (exit 128: "
    )


def test_g18_rev_parse_runs_after_the_head_read_and_before_lstat(repo, monkeypatch):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    main = sm.read_default_branch_suspension(repo.root)
    events = []
    real_run, real_lstat = subprocess.run, os.lstat

    def spy_run(argv, *a, **k):
        events.append(("git", list(argv)[3:]))
        return real_run(argv, *a, **k)

    def spy_lstat(path, *a, **k):
        if str(path).endswith(MANIFEST_PATH):
            events.append(("lstat", str(path)))
        return real_lstat(path, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(sm.os, "lstat", spy_lstat)
    assert sm.effective_manifest_human_gate(STEP, repo.head, main, repo.root)["error"] is None
    kinds = [
        (
            "tree"
            if e[0] == "git" and e[1][:1] == ["ls-tree"] and repo.head in e[1]
            else (
                "show"
                if e[0] == "git" and e[1][:1] == ["show"] and repo.head in e[1][1]
                else (
                    "toplevel"
                    if e[0] == "git" and e[1] == ["rev-parse", "--show-toplevel"]
                    else "lstat" if e[0] == "lstat" else None
                )
            )
        )
        for e in events
    ]
    order = [k for k in kinds if k]
    assert order == ["tree", "show", "toplevel", "lstat"]


@pytest.mark.parametrize("v", G20_TRUE, ids=[f"flag={v!r}" for v in G20_TRUE])
def test_g20_non_canonical_false_spellings_are_true(repo, v):
    _assert_gated(repo, G20[f"flag={v!r}"])


@pytest.mark.parametrize("v", G20_FALSE, ids=[f"flag={v!r}" for v in G20_FALSE])
def test_g20_canonical_false_spellings_are_false(repo, v):
    text = G20_CONTROLS[f"flag={v!r}"]
    assert sm._manifest_gate_scan(text, STEP) is False
    assert _sr_path(repo, text) is False
    assert [(r["error"], r["flag"]) for r in _sr_pinned(repo, text)] == [(None, False)] * 2


def test_g20_end_to_end_quoted_false_on_default_gates(repo, use_sm, monkeypatch, capsys):
    _assert_default_gates(repo, G20["flag='\"false\"'"])
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and S3_GENERIC in out


# --- AM-4 SR-AL (#2392): the canonical-line allowlist -------------------------------------

UNICODE_WS = [" ", "　", " ", " ", " ", " "]
_HGR = "    human_gate_required: "
_ID_LINE = "  - id: s1\n"


def _g22_fixtures():
    """{name: text}: a Unicode space in each position of an otherwise canonical `false` item."""
    out = {}
    for c in UNICODE_WS:
        tag = f"U+{ord(c):04X}"
        out[f"after_false-{tag}"] = f"steps:\n{_ID_LINE}{_HGR}false{c}\n"
        out[f"after_zero-{tag}"] = f"steps:\n{_ID_LINE}{_HGR}0{c}\n"
        out[f"before_value-{tag}"] = f"steps:\n{_ID_LINE}{_HGR}{c}false\n"
        out[f"before_comment-{tag}"] = f"steps:\n{_ID_LINE}{_HGR}false{c} # c\n"
        out[f"replacing_space-{tag}"] = f"steps:\n{_ID_LINE}{_HGR}false{c}# c\n"
        out[f"in_indent-{tag}"] = f"steps:\n{_ID_LINE}{c}  human_gate_required: false\n"
        out[f"after_dash-{tag}"] = f"steps:\n  -{c}id: s1\n{_HGR}false\n"
        out[f"before_colon-{tag}"] = f"steps:\n{_ID_LINE}    human_gate_required{c}: false\n"
        out[f"after_id-{tag}"] = f"steps:\n  - id: s1{c}\n{_HGR}false\n"
        out[f"only_char_line-{tag}"] = f"steps:\n{_ID_LINE}{c}\n{_HGR}false\n"
    return out


G22 = _g22_fixtures()
G22_CONTROLS = {
    "comment_non_ascii": f"steps:\n{_ID_LINE}{_HGR}false # — note\n",
    "quoted_non_ascii_name": f'steps:\n{_ID_LINE}    name: "a — b"\n{_HGR}false\n',
}
_ITEM_F = f"{_ID_LINE}{_HGR}false\n"
G23 = {
    "flag_continuation_true": f"steps:\n{_ID_LINE}{_HGR}false\n      true\n",
    "flag_continuation_digit": f"steps:\n{_ID_LINE}{_HGR}false\n      5\n",
    "flag_continuation_quote": f'steps:\n{_ID_LINE}{_HGR}false\n      b"\n',
    "id_continuation_s1": f"steps:\n  - id: s1\n      x\n{_HGR}false\n",
    "tier_continuation": f"steps:\n{_ID_LINE}    risk_tier: LOW\n      HIGH\n{_HGR}false\n",
    "nested_signoffs": (
        f"steps:\n{_ID_LINE}    required_signoffs:\n      - code-review\n{_HGR}false\n"
    ),
    "indent_between_item_and_key": f"steps:\n{_ID_LINE}   x: y\n{_HGR}false\n",
    "key_before_first_item": f"steps:\n{_HGR}false\n{_ID_LINE}",
}
G23_ID5 = "steps:\n  - id: 5\n      x\n    human_gate_required: false\n"
G23_CONTROL = f"steps:\n{_ID_LINE}    required_signoffs: [code-review]\n{_HGR}false\n"
_B21 = f"steps:\n{_ITEM_F}"
_S1_TRUE = f"{_ID_LINE}{_HGR}true\n"
G21B = {
    "column0_comment": f"{_B21}# c\n{_S1_TRUE}",
    "column0_blank": f"{_B21}\n{_S1_TRUE}",
    "column0_tab_only": f"{_B21}\t\n{_S1_TRUE}",
    "line_starting_with_nbsp": f"{_B21} foo\n{_S1_TRUE}",
    "line_starting_with_tab": f"{_B21}\tfoo\n{_S1_TRUE}",
    "line_starting_with_ideographic_space": f"{_B21}　foo\n{_S1_TRUE}",
}
G21B_CONTROL = f"{_B21}# c\n\n  - id: other\n    human_gate_required: false\n"
_G25B_HEAD = f"{_B21}"
G25B = {
    "escaped_steps_key": f'{_G25B_HEAD}"st\\x65ps":\n{_S1_TRUE}',
    "tagged_steps_key": f"{_G25B_HEAD}!!str steps:\n{_S1_TRUE}",
    "explicit_steps_key": f"{_G25B_HEAD}? steps\n{_S1_TRUE}",
    "unclosed_steps_key": f'{_G25B_HEAD}"steps\n{_S1_TRUE}',
}
G25B_CONTROL = f'{_G25B_HEAD}"name": x\n'
# T-G26 (AR-AL-4): characters YAML loaders disagree on as line breaks; the whole text is True.
G26_CHARS = ["\u000b", "\u000c", "\u001c", "\u001d", "\u001e", "\u0085", "\u2028", "\u2029"]
G26 = {}
for _c in G26_CHARS:
    _tag = f"U+{ord(_c):04X}"
    G26[f"after_false-{_tag}"] = f"steps:\n{_ID_LINE}{_HGR}false{_c}\n"
    G26[f"in_comment-{_tag}"] = f"steps:\n{_ID_LINE}{_HGR}false # a{_c}b\n"
    G26[f"in_dq_value-{_tag}"] = f'steps:\n{_ID_LINE}    name: "a{_c}b"\n{_HGR}false\n'
G26_CONTROLS = {
    "dq_value_nbsp": f'steps:\n{_ID_LINE}    name: "a\u00a0b"\n{_HGR}false\n',
}
_TEMPLATE_PATH = REPO / "contract/step-manifest.template.yaml"
TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")


G22_POSITIONS = sorted({name.split("-")[0] for name in G22})


@pytest.mark.parametrize("position", G22_POSITIONS)
def test_g22_unicode_whitespace_in_any_position_is_true(repo, position):
    names = [name for name in G22 if name.split("-")[0] == position]
    assert len(names) == len(UNICODE_WS)
    for name in names:
        _assert_gated(repo, G22[name])


def test_g22_end_to_end_nbsp_padded_default_gates(repo, use_sm, monkeypatch, capsys):
    _assert_default_gates(repo, G22["after_false-U+00A0"])
    code, out = cli(monkeypatch, capsys, repo)
    assert code == 4 and S3_GENERIC in out


@pytest.mark.parametrize("name", list(G22_CONTROLS), ids=list(G22_CONTROLS))
def test_g22_control_non_ascii_in_a_comment_or_quoted_value_is_false(repo, name):
    text = G22_CONTROLS[name]
    assert sm._manifest_scan(text, STEP) == (False, [STEP])
    assert _sr_path(repo, text) is False


@pytest.mark.parametrize("name", list(G23), ids=list(G23))
def test_g23_continuation_and_nesting_is_true(repo, name):
    _assert_gated(repo, G23[name])


def test_g23_numeric_id_continuation_is_true_for_step_5(repo):
    assert sm._manifest_gate_scan(G23_ID5, "5") is True
    assert _yaml_says_gated(G23_ID5, "5") is False  # PyYAML reads the id '5 x': no match
    assert sm._manifest_gate_scan(G23_ID5, "5 x") is True


def test_g23_control_flow_list_of_signoffs_is_false(repo):
    assert sm._manifest_scan(G23_CONTROL, STEP) == (False, [STEP])
    assert _sr_path(repo, G23_CONTROL) is False


@pytest.mark.parametrize("name", list(G21B), ids=list(G21B))
def test_g21b_block_does_not_end_at_column0_noise(repo, name):
    _assert_gated(repo, G21B[name])


def test_g21b_control_column0_comment_and_blank_between_different_items(repo):
    assert sm._manifest_scan(G21B_CONTROL, STEP) == (False, [STEP, "other"])
    assert _sr_path(repo, G21B_CONTROL) is False


def test_g21b_a_column0_key_ends_the_block_without_changing_the_result():
    base = sm._manifest_scan(MANIFEST_FALSE, STEP)
    assert base == (False, [STEP])
    assert sm._manifest_scan(MANIFEST_FALSE + "x: 1\n", STEP) == base


@pytest.mark.parametrize("name", list(G25B), ids=list(G25B))
def test_g25b_outside_block_quoted_or_tagged_second_steps_key_is_true(repo, name):
    _assert_gated(repo, G25B[name])


def test_g25b_control_later_plain_quoted_key_has_no_effect(repo):
    assert sm._manifest_scan(G25B_CONTROL, STEP) == (False, [STEP])
    assert _sr_path(repo, G25B_CONTROL) is False


@pytest.mark.parametrize("name", list(G26), ids=list(G26))
def test_g26_line_break_ambiguous_character_scans_true(name):
    assert sm._manifest_scan(G26[name], STEP) == (True, [])


@pytest.mark.parametrize("placement", ["after_false", "in_comment", "in_dq_value"])
def test_g26_path_function_and_both_pinned_reads_are_true(repo, placement):
    # One repo per placement keeps the temp footprint inside the #2054 budget.
    for char in G26_CHARS:
        _assert_gated(repo, G26[f"{placement}-U+{ord(char):04X}"])


def test_g26_u2028_default_with_canonical_head_is_effective_true(repo):
    regen(repo, base_manifest=G26["after_false-U+2028"], head_manifest=MANIFEST_FALSE)
    assert _eff(repo) == {"flag": True, "error": None}


def test_g26_control_nbsp_in_a_closed_dq_value_is_false(repo):
    text = G26_CONTROLS["dq_value_nbsp"]
    assert sm._manifest_scan(text, STEP) == (False, [STEP])
    assert _sr_path(repo, text) is False


def test_g26_control_template_with_u2014_still_scans_false_false_true():
    assert "\u2014" in TEMPLATE
    assert [sm._manifest_gate_scan(TEMPLATE, s) for s in ("1", "2", "3")] == [False, False, True]


def test_g24_template_scans_steps_1_2_3_as_false_false_true():
    assert [sm._manifest_gate_scan(TEMPLATE, s) for s in ("1", "2", "3")] == [False, False, True]


def test_g24_template_committed_as_default_and_head(repo):
    regen(repo, base_manifest=TEMPLATE, head_manifest=TEMPLATE)
    assert _eff(repo, step="3") == {"flag": True, "error": None}
    assert _eff(repo, step="1") == {"flag": False, "error": None}


def test_g24_template_comment_above_steps_names_the_remedy():
    lines = TEMPLATE.splitlines()
    comment = lines[lines.index("steps:") - 1]
    assert comment.startswith("#") and "[a, b]" in comment and "single-line values" in comment


def test_g24_real_manifest_if_present_is_never_looser_than_yaml():
    path = REPO / "contract/step-manifest.yaml"
    if not path.exists():
        return
    _assert_never_looser(path.read_text(encoding="utf-8"))


# --- T-G21: the grammar, one case per form and per rejection -----------------------------

_BLANK = ("blank", 0, None, None)
_ACCEPT = [
    ("", _BLANK),
    ("  \t", ("blank", 3, None, None)),
    ("  # x — y", ("comment", 2, None, None)),
    ("\t# tab comment", ("comment", 1, None, None)),
    ("- id: s1", ("item", 0, "id", "s1")),
    ("  - id: s1", ("item", 2, "id", "s1")),
    ("  -   id: s1", ("item", 2, "id", "s1")),
    ("    name: x", ("key", 4, "name", "x")),
    ("    Xname: x", ("key", 4, "Xname", "x")),
    ("    name: a b-c/d.e", ("key", 4, "name", "a b-c/d.e")),
    ('    name: "a — b"', ("key", 4, "name", "a — b")),
    ('    name: ""', ("key", 4, "name", "")),
    ("    name: 'it''s'", ("key", 4, "name", "it''s")),
    ("    list: []", ("key", 4, "list", "[]")),
    ("    list: [ ]", ("key", 4, "list", "[ ]")),
    ("    list: [a, b-c, d.e]", ("key", 4, "list", "[a, b-c, d.e]")),
    ('    "name": x', ("key", 4, "name", "x")),
    ("    'name': x", ("key", 4, "name", "x")),
    ('    "id": s1', ("key", 4, "id", "s1")),
    ("    'id': s1", ("key", 4, "id", "s1")),
    ("    id: 7", ("key", 4, "id", "7")),
    ("    id: 's1'", ("key", 4, "id", "s1")),
    ('    id: "7"', ("key", 4, "id", "7")),
    ("    id: 'yes'", ("key", 4, "id", "yes")),
    ("    id: s1 # c", ("key", 4, "id", "s1")),
    ("    id: s1\t# c", ("key", 4, "id", "s1")),
    ("    id: s1   ", ("key", 4, "id", "s1")),
    ("    name: x  # —", ("key", 4, "name", "x")),
    *[
        (f"    human_gate_required: {v}", ("key", 4, "human_gate_required", v))
        for v in ("false", "False", "FALSE", "0", "true", "True", "TRUE", "1")
    ],
    ("  - human_gate_required: false", ("item", 2, "human_gate_required", "false")),
]
_REJECT = [
    "\tid: s1",
    "  -\tid: s1",
    "  -",
    "  - ",
    "  - x",
    "  - id:",
    "    id:",
    "    name:",
    "    name: # c",
    "    name:x",
    "    name:\tx",
    '    "na\\x6de": x',
    "    'na''me': x",
    "    'a b': x",
    '    "a b": x',
    "    näme: x",
    "    !!str name: x",
    "    !tag name: x",
    "    ? name",
    "    id: yes",
    "    id: null",
    "    id: On",
    "    id: NO",
    "    id: 007",
    "    id: s1 x",
    "    id: 's1",
    "    id: 's1\"",
    "    id:  s1",
    "    id: s1 ",
    "    name: a  b",
    "    name: a:b",
    "    name: a#b",
    "    name: 'a",
    '    name: "a',
    "    name: [a",
    '    name: "a\\nb"',
    '    name: "a\x07b"',
    "    name: |",
    "    name: >",
    "    name: &a x",
    "    name: *a",
    "    name: !!str x",
    "    name: {a: b}",
    "    name: -x",
    "    name: x ",
    "    human_gate_required: false#x",
    '    human_gate_required: "false"',
    "    human_gate_required: fAlSe",
    "    human_gate_required: no",
    "    human_gate_required: 00",
    "    human_gate_required: false ",
    "    human_gate_required: !!bool false",
    "    name: x",
    " ",
    "　# c",
]


@pytest.mark.parametrize("line,expected", _ACCEPT, ids=[repr(a[0]) for a in _ACCEPT])
def test_g21_classify_accepts_each_canonical_form(line, expected):
    assert sm._classify_steps_line(line) == expected


@pytest.mark.parametrize("line", _REJECT, ids=[repr(r) for r in _REJECT])
def test_g21_classify_rejects_each_non_canonical_form(line):
    assert sm._classify_steps_line(line) is None


@pytest.mark.parametrize(
    "body,expected",
    [
        ('"clean": x', False),
        ('"a b"', False),
        ('"unclosed', True),
        ("'unclosed", True),
        ('"\\x41"', True),
        ('"a\\"b"', True),
        ("'a''b'", True),
        ("'lone'", False),
        ("''", False),
        ('""', False),
        ("'a' ''", False),
        ("plain", False),
        ("", False),
        ('"', True),
        ("'", True),
    ],
)
def test_g21_bad_quoted_span(body, expected):
    assert sm._bad_quoted_span(body) is expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("steps:", True),
        ("steps: # c", True),
        ('"steps":', True),
        ("'steps' :", True),
        ("steps :", True),
        ("? steps", True),
        ("? steps\t", True),
        ("steps:[a:b]", True),
        ("steps:[a]", True),
        ("steps", True),
        ("stepsx:", False),
        ("xsteps:", False),
        ("other: steps", False),
        ("- id: steps", False),
        ("?x steps", False),
        ("name: x", False),
    ],
)
def test_g21_is_steps_key_line(line, expected):
    assert sm._is_steps_key_line(line) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (MANIFEST_FALSE, (False, [STEP])),
        (MANIFEST_TRUE, (True, [STEP])),
        ("steps:\n  - id: other\n", (None, ["other"])),
        ("steps:\n", (None, [])),
        ("foo: bar\n", (True, [])),
        ("steps:\n  - name: x\n", (True, [])),
        ("steps:\n  - id: s1\n    human_gate_required: false\n    - id: s2\n", (True, [])),
        ("steps:\n  - id: s1\n  - id: s2\n   - id: s3\n", (True, [])),
        ("steps:\n  - id: s1\n    name: human_gate_required\n", (True, [STEP])),
        ("steps:\n  - id: s1\n    name: a\n    name: b\n", (True, [])),
        ("steps:\n  - id: s1\n    human_gate_required: 1\n", (True, [STEP])),
        ("steps:\n  - id: s1\n    human_gate_required: TRUE\n", (True, [STEP])),
        ("steps:\n  - id: s1\n    human_gate_required: 0\n", (False, [STEP])),
        ("steps: # c\n  - id: s1\n", (False, [STEP])),
        ("steps:\t# c\n  - id: s1\n", (False, [STEP])),
        ("steps:\n\n  # c\n  - id: s1\n", (False, [STEP])),
        ("a: 1\nsteps:\n  - id: s1\nb: 2\n", (False, [STEP])),
        ("steps:\n  -   id: s1\n      name: x\n", (False, [STEP])),
        (
            "steps:\n  - id: s1\n    name: x\n  - id: s2\n    human_gate_required: true\n",
            (False, ["s1", "s2"]),
        ),
        ("steps:\n  - id: s2\n    name: x\n  - id: s1\n", (False, ["s2", STEP])),
        ("steps:\n- id: s1\n  human_gate_required: false\n", (False, [STEP])),
        ("steps:\n- id: s1\n  human_gate_required: false\n- id: s2\n", (False, [STEP, "s2"])),
        ("steps:\n  - id: s1\n -\n", (True, [])),
    ],
)
def test_g21_manifest_scan_exact_results(text, expected):
    assert sm._manifest_scan(text, STEP) == expected


def test_g21_scan_accepts_integer_step_and_string_step_alike():
    assert sm._manifest_scan("steps:\n  - id: 5\n", 5) == (False, ["5"])
    assert sm._manifest_scan("steps:\n  - id: 5\n", "5") == (False, ["5"])


def test_g21_every_target_item_is_checked_not_just_the_first():
    text = f"steps:\n{_ITEM_F}  - id: s1\n    name: x\n{_ID_LINE}{_HGR}true\n"
    assert sm._manifest_scan(text, STEP) == (True, [STEP, STEP, STEP])


def test_g21_a_target_with_a_stray_flag_token_is_true():
    text = "steps:\n  - id: s1\n    name: human_gate_required\n"
    assert sm._manifest_scan(text, STEP) == (True, [STEP])
    text = "steps:\n  - id: s2\n    name: human_gate_required\n  - id: s1\n"
    assert sm._manifest_scan(text, STEP) == (False, ["s2", STEP])


def test_g21_non_target_flag_token_is_ignored_only_when_grammar_allows():
    text = "steps:\n  - id: s2\n    human_gate_required: true\n  - id: s1\n"
    assert sm._manifest_scan(text, STEP) == (False, ["s2", STEP])
    text = "steps:\n  - id: s2\n    human_gate_required: maybe\n  - id: s1\n"
    assert sm._manifest_scan(text, STEP) == (True, [])


@pytest.mark.parametrize(
    "text",
    [
        "---\n---\nsteps:\n  - id: s1\n",
        "--- steps: []\n",
        "--- !t\nsteps:\n",
        "...\nsteps:\n",
        "steps:\n  - id: s1\n---\n",
        "steps:\n  - id: s1\n...\n",
        "a: 1\n---\nsteps:\n  - id: s1\n",
        "a: &x 1\nsteps:\n  - id: s1\n",
        "a: *x\nsteps:\n  - id: s1\n",
        "<<: x\nsteps:\n  - id: s1\n",
        "!!map\nsteps:\n  - id: s1\n",
        "? a\nsteps:\n  - id: s1\n",
        '"a\\x41": 1\nsteps:\n  - id: s1\n',
        "'a''b': 1\nsteps:\n  - id: s1\n",
        '"a: 1\nsteps:\n  - id: s1\n',
        "'a: 1\nsteps:\n  - id: s1\n",
        "steps:\n  - id: s1\nsteps:\n",
        'steps:\n  - id: s1\n"steps":\n',
    ],
)
def test_g21_outside_block_rules_gate_the_whole_scan(text):
    assert sm._manifest_scan(text, STEP)[0] is True


@pytest.mark.parametrize(
    "text",
    ["---\nsteps:\n  - id: s1\n", "--- # c\nsteps:\n  - id: s1\n", "---\t\nsteps:\n  - id: s1\n"],
)
def test_g21_one_bare_or_commented_leading_marker_is_allowed(text):
    assert sm._manifest_scan(text, STEP) == (False, [STEP])


def test_g21_marker_check_is_ascii_whitespace_only():
    assert sm._DOC_MARKER_RE.match("--- ") is None
    assert sm._DOC_MARKER_RE.match("---\t") is not None
    assert sm._DOC_MARKER_RE.match("...") is not None
    assert sm._DOC_MARKER_RE.match("--x") is None


@pytest.mark.parametrize("first", ["X", "z", "A", "_"])
def test_g21_block_ends_at_every_ascii_printable_first_char_except_dash_and_hash(first):
    # Boundary of the AR-AL-1 end-of-block range ("!".."~" minus "-" and "#"): a plain
    # top-level key after the block must end it, not make the block non-canonical.
    base = sm._manifest_scan(MANIFEST_FALSE, STEP)
    assert base == (False, [STEP])
    assert sm._manifest_scan(MANIFEST_FALSE + f"{first}: 1\n", STEP) == base


@pytest.mark.parametrize("first", ["~", "}"])
def test_g21_block_ending_line_is_held_to_the_outside_allowlist(first):
    # AL-WD: the line that ends the block is an outside line; `~`/`}` are not KEY characters.
    assert sm._manifest_scan(MANIFEST_FALSE + f"{first}: 1\n", STEP) == (True, [])


def test_g21_a_trailing_comment_naming_the_flag_key_is_ignored_by_the_raw_net():
    text = "steps:\n  - id: s1\n    name: x # human_gate_required\n"
    assert sm._manifest_scan(text, STEP) == (False, [STEP])


def test_g21_raw_net_counts_every_flag_token_not_just_one():
    # `name: human_gate_required` is a second token next to the real key: stricter than YAML, True.
    text = "steps:\n  - id: s1\n    name: human_gate_required\n    human_gate_required: false\n"
    assert sm._manifest_scan(text, STEP) == (True, [STEP])


@pytest.mark.parametrize(
    "prefix",
    ["- !x\n", "- ? a\n", "a:\n  ? x\n", "a:\n  !x y\n", "--- \u00a0\n", "--- X\n"],
)
def test_g21_outside_block_tag_or_explicit_key_in_nested_or_dash_body_gates(prefix):
    assert sm._manifest_scan(prefix + MANIFEST_FALSE, STEP)[0] is True


def test_g21_an_indented_steps_word_outside_the_block_is_not_a_second_steps_key():
    text = "a:\n  steps: 1\n" + MANIFEST_FALSE
    assert sm._manifest_scan(text, STEP) == (False, [STEP])


@pytest.mark.parametrize("comment", ["&x", "*x", "<<: x"])
def test_g21_outside_block_anchor_text_in_a_trailing_comment_is_ignored(comment):
    text = f"a: 1 # {comment}\n" + MANIFEST_FALSE
    assert sm._manifest_scan(text, STEP) == (False, [STEP])


# --- T-G25 (AL-6): E-G5 wording ------------------------------------------------------------


def test_g25_rev_parse_oserror_is_e_g5_could_not_start(repo, monkeypatch):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    real = subprocess.run

    def run(argv, *a, **k):
        if "rev-parse" in argv and "--show-toplevel" in argv:
            raise FileNotFoundError("git")
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", run)
    assert _eff_at(repo, sub) == {
        "flag": True,
        "error": _e_g5(sub, "timeout or git could not start"),
    }


def test_g25_exit_128_with_empty_stderr_has_no_trailing_colon(repo, monkeypatch):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    _fake_git(
        monkeypatch,
        lambda args: (
            _cp(128) if args[0] == "rev-parse" and "--show-toplevel" in args else NotImplemented
        ),
    )
    assert _eff_at(repo, sub) == {"flag": True, "error": _e_g5(sub, "exit 128")}


def test_g25_exit_nonzero_with_stderr_keeps_the_first_line(repo, monkeypatch):
    sub = _g18_setup(repo, MANIFEST_FALSE)
    _fake_git(
        monkeypatch,
        lambda args: (
            _cp(1, err=b"boom\nmore\n")
            if args[0] == "rev-parse" and "--show-toplevel" in args
            else NotImplemented
        ),
    )
    assert _eff_at(repo, sub) == {"flag": True, "error": _e_g5(sub, "exit 1: boom")}


def test_g25_e_g3_timeout_wording_is_unchanged(repo, monkeypatch):
    _fake_git(monkeypatch, lambda args: None if args[0] == "ls-tree" else NotImplemented)
    res = sm.read_manifest_gate_at(repo.head, STEP, repo.root, unlisted_step=True)
    assert res == {"flag": True, "blob": None, "error": "timeout"}


def test_g18_real_rev_parse_outside_any_repo_is_e_g5_with_real_stderr(
    repo, monkeypatch, scratch_factory
):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    main = sm.read_default_branch_suspension(repo.root)
    outside = scratch_factory.mktemp("outside_repo")
    real = sm._git

    def wrapper(args, repo_root, env=None):
        return real(args, outside if args[0] == "rev-parse" else repo_root, env)

    monkeypatch.setattr(sm, "_git", wrapper)
    res = sm.effective_manifest_human_gate(STEP, repo.head, main, repo.root)
    assert res["flag"] is True
    assert res["error"].startswith(
        f"S3: could not resolve the git toplevel from {str(repo.root)!r} "
        "(exit 128: fatal: not a git repository"
    )
    assert res["error"].endswith("); failing closed, re-run")


# --- AM-4 AL-WD (#2392): the whole-document canonical-line allowlist ---------------------------

G27_F1 = (
    '  foo: "x\nsteps:\n  - id: s1\n    human_gate_required: false\nx"\n'
    "  steps:\n    - id: s1\n      human_gate_required: true\n"
)
G27_F2 = (
    "\ufeffsteps:\n  - id: s1\n    human_gate_required: true\n"
    'foo: "x\nsteps:\n  - id: s1\n    human_gate_required: false\nx"\n'
)
G27 = {"f1_indented_document": G27_F1, "f2_bom": G27_F2}


def _indent_all(text, n=2):
    return "".join(" " * n + line for line in text.splitlines(keepends=True))


G28_TRUE = {
    "bom_first": "\ufeff" + MANIFEST_FALSE,
    "bom_in_comment": "# a\ufeffb\n" + MANIFEST_FALSE,
    "bom_in_dq_value": 'steps:\n  - id: s1\n    name: "a\ufeffb"\n    human_gate_required: false\n',
    "bom_end_of_line": "foo: 1\ufeff\n" + MANIFEST_FALSE,
    "indent_2": _indent_all(MANIFEST_FALSE, 2),
    "indent_4": _indent_all(MANIFEST_FALSE, 4),
    "tab_first_line": "\tfoo: 1\n" + MANIFEST_FALSE,
    "indented_after_marker": "---\n" + _indent_all(MANIFEST_FALSE),
    "indented_after_comment_and_blank": "# c\n\n" + _indent_all(MANIFEST_FALSE),
}
G28_CONTROLS = {
    "leading_marker": "---\n" + MANIFEST_FALSE,
    "content_after_indented_comments": "  # c\n  # d\n" + MANIFEST_FALSE,
}

G29_FRAGMENTS = {
    "block_scalar_literal": "foo: |\n  text\n",
    "block_scalar_folded": "foo: >-\n  text\n",
    "dq_multiline": 'foo: "a\nb"\n',
    "sq_multiline": "foo: 'a\nb'\n",
    "plain_continuation": "foo: a\n  b\n",
    "nested_block_list": "foo:\n  - a\n",
    "two_level_nesting": "foo:\n  a:\n    b: c\n",
    "sibling_indent_mismatch": "foo:\n  a: 1\n   b: 2\n",
    "indented_under_top": "foo: 1\n  a: 2\n",
    "flow_mapping": "foo: {a: 1}\n",
    "unclosed_flow": "foo: [a, b\n",
    "url_value": "url: https://x.example\n",
    "no_space_after_colon": "foo:bar\n",
    "digit_key": "1: x\n",
    "dotted_key": "a.b: x\n",
    "tilde_key": "~: 1\n",
    "brace_key": "}: 1\n",
    "top_level_sequence": "- x\n",
    "directive": "%YAML 1.2\n",
    "tab_indented_nested": "foo:\n\ta: 1\n",
    "nbsp_indented_nested": "foo:\n\u00a0\u00a0a: 1\n",
    "nbsp_led_key": "\u00a0foo: 1\n",
    "dq_with_backslash": 'foo: "a\\b"\n',
    "tagged_value": "foo: !x y\n",
}
G29 = {}
for _name, _frag in G29_FRAGMENTS.items():
    G29[f"before-{_name}"] = _frag + MANIFEST_FALSE
    G29[f"after-{_name}"] = MANIFEST_FALSE + _frag

_G30_NESTED = "role_mappings:\n  k: v\n  j: w\n"
G30 = {
    "nested_before": _G30_NESTED + MANIFEST_FALSE,
    "nested_after": MANIFEST_FALSE + _G30_NESTED,
    "open_without_nested_before": "role_mappings:\n" + MANIFEST_FALSE,
    "open_without_nested_after": MANIFEST_FALSE + "role_mappings:\n",
    "nested_with_interleaved_comment_and_blank": (
        "role_mappings:\n  k: v\n# c\n\n  j: w\n" + MANIFEST_FALSE
    ),
    "nested_steps_word": "a:\n  steps: 1\n" + MANIFEST_FALSE,
    "dq_non_ascii": 'name: "a \u2014 b"\n' + MANIFEST_FALSE,
    "sq_escaped_quote": "name: 'it''s'\n" + MANIFEST_FALSE,
    "flow_list": "list: [a, b]\n" + MANIFEST_FALSE,
    "trailing_comment_net": "x: 1 # &x *x <<: y\n" + MANIFEST_FALSE,
    "open_with_trailing_spaces": "foo: \n" + MANIFEST_FALSE,
}


def _oracle_step_ids(text):
    """Step ids as a real YAML parser reads them (independent of the scanner under test)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return set()
    steps = doc.get("steps") if isinstance(doc, dict) else None
    if not isinstance(steps, list):
        return set()
    return {str(item.get("id")) for item in steps if isinstance(item, dict) and "id" in item}


def _assert_never_looser(text):
    for step in _oracle_step_ids(text) | set(sm._manifest_scan(text, STEP)[1]):
        if _yaml_says_gated(text, step):
            assert sm._manifest_gate_scan(text, step) is True


@pytest.mark.parametrize("name", list(G27), ids=list(G27))
def test_g27_f1_and_f2_regressions_scan_true(repo, name):
    text = G27[name]
    assert _yaml_says_gated(text, "s1") is True
    assert sm._manifest_scan(text, "s1") == (True, [])
    assert _sr_path(repo, text, "s1") is True
    head, default = _sr_pinned(repo, text, "s1")
    assert head["error"] is None and head["flag"] is True
    assert default["error"] is None and default["flag"] is True


@pytest.mark.parametrize("name", list(G27), ids=list(G27))
def test_g27_default_branch_decoy_with_canonical_head_is_effective_true(repo, name):
    regen(repo, base_manifest=G27[name], head_manifest=MANIFEST_FALSE)
    assert _eff(repo) == {"flag": True, "error": None}


@pytest.mark.parametrize("name", list(G28_TRUE), ids=list(G28_TRUE))
def test_g28_bom_and_indented_first_line_scan_true(name):
    assert sm._manifest_scan(G28_TRUE[name], STEP) == (True, [])


def test_g28_path_function_and_pinned_reads_are_true(repo):
    for text in (G28_TRUE["bom_first"], G28_TRUE["indent_2"]):
        _assert_gated(repo, text)


@pytest.mark.parametrize("name", list(G28_CONTROLS), ids=list(G28_CONTROLS))
def test_g28_controls_stay_false(name):
    assert sm._manifest_scan(G28_CONTROLS[name], STEP) == (False, [STEP])


def test_g28_decode_is_strict_utf8_so_a_bom_reaches_the_scan(tmp_path):
    path = tmp_path / "step-manifest.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + MANIFEST_FALSE.encode())
    assert sm.manifest_human_gate_required(path, STEP) is True


@pytest.mark.parametrize("name", list(G29), ids=list(G29))
def test_g29_outside_constructs_scan_exactly_true_empty(name):
    assert sm._manifest_scan(G29[name], STEP) == (True, [])


def test_g29_path_function_and_pinned_reads_are_true(repo):
    for name in ("before-block_scalar_literal", "after-dq_multiline", "before-nested_block_list"):
        _assert_gated(repo, G29[name])


@pytest.mark.parametrize("name", list(G30), ids=list(G30))
def test_g30_controls_stay_false(repo, name):
    assert sm._manifest_scan(G30[name], STEP) == (False, [STEP])
    assert _sr_path(repo, G30[name]) is False


def test_g30_template_scans_false_false_true_through_both_pinned_reads(repo):
    assert [sm._manifest_gate_scan(TEMPLATE, s) for s in ("1", "2", "3")] == [False, False, True]
    assert [sm._manifest_scan(TEMPLATE, s)[1] for s in ("1", "2", "3")] == [["1", "2", "3"]] * 3
    regen(repo, base_manifest=TEMPLATE, head_manifest=TEMPLATE)
    assert _eff(repo, step="2") == {"flag": False, "error": None}
    assert _eff(repo, step="3") == {"flag": True, "error": None}
    for step, expected in (("1", False), ("2", False), ("3", True)):
        for read in _sr_pinned(repo, TEMPLATE, step):
            assert read["error"] is None and read["flag"] is expected


def test_g30_an_indented_line_under_the_steps_key_stays_in_the_block():
    # `steps:` is never an O-open parent: an indented line after it is governed by the block rules.
    text = "steps:\n  - id: s1\n    human_gate_required: false\n    name: x\n"
    assert sm._manifest_scan(text, STEP) == (False, [STEP])


def _symlink_contract(repo):
    real = repo.root.parent / "contract_real"
    os.rename(repo.root / "contract", real)
    os.symlink(real, repo.root / "contract")


def _contract_as_file(repo):
    shutil.rmtree(repo.root / "contract")
    (repo.root / "contract").write_text(MANIFEST_FALSE)


@pytest.mark.parametrize("how", [_symlink_contract, _contract_as_file])
def test_g32_contract_not_a_real_directory_is_not_a_regular_file(repo, how):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    how(repo)
    assert _eff(repo) == {"flag": True, "error": _egprefix(repo, "not a regular file")}


def test_g32_lstat_oserror_on_the_contract_component_is_unreadable(repo, monkeypatch):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    real = os.lstat
    seen = []

    def fake(path, *a, **k):
        seen.append(str(path))
        if str(path) == str(repo.root / "contract"):
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **k)

    monkeypatch.setattr(sm.os, "lstat", fake)
    assert _eff(repo) == {"flag": True, "error": _egprefix(repo, "unreadable: Permission denied")}
    assert str(repo.root / MANIFEST_PATH) not in seen  # the first failing prefix decides


def test_g32_contract_removed_while_head_has_the_manifest_is_deleted(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    shutil.rmtree(repo.root / "contract")
    assert _eff(repo) == {"flag": True, "error": _egprefix(repo, "deleted")}


def test_g32_contract_removed_with_no_manifest_at_either_sha_is_false(repo):
    regen(repo)
    shutil.rmtree(repo.root / "contract")
    assert _eff(repo) == {"flag": False, "error": None}


def test_g32_control_real_directory_with_a_matching_file_is_unchanged(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    assert _eff(repo) == {"flag": False, "error": None}


def test_g33_oracle_ids_are_independent_of_the_scanner():
    assert _oracle_step_ids(G27_F1) == {"s1"}
    assert sm._manifest_scan(G27_F1, "s1")[1] == []
    assert _oracle_step_ids("a: [") == set()
    assert _oracle_step_ids("steps: 1\n") == set()


@pytest.mark.parametrize("text", [G27_F1, G27_F2, TEMPLATE], ids=["f1", "f2", "template"])
def test_g33_assert_never_looser_passes_on_the_fixed_scanner(text):
    _assert_never_looser(text)


def test_g33_assert_never_looser_catches_a_scanner_that_drops_the_id(monkeypatch):
    monkeypatch.setattr(sm, "_manifest_scan", lambda text, step: (False, []))
    with pytest.raises(AssertionError):
        _assert_never_looser(G27_F1)


def _wd_family():
    """T-G34: decoy / indent / BOM transforms of a gated real block, as (text, step)."""
    out = []
    bases = [(MANIFEST_FALSE, STEP), (G21B["column0_comment"], STEP), (TEMPLATE, "3")]
    for base, step in bases:
        decoy = f"steps:\n  - id: {step}\n    human_gate_required: false\n"
        before_steps = re.sub(r"(?m)^steps:\n", lambda _: "@@\nsteps:\n", base, count=1)
        out += [
            (_indent_all(base), step),
            ("\ufeff" + base, step),
            (before_steps.replace("@@\n", f'foo: "x\n{decoy}x"\n'), step),
            (base + "foo: |\n" + _indent_all(decoy), step),
            (base + "foo: x\n" + _indent_all(decoy), step),
        ]
    return out


G34_FAMILY = _wd_family()
G34_FAMILY_FLOOR = 8

# T-G35: AL-WD-2 / AL-WD-3 forms the inlined outside-line classification must reject or accept.
G35_TRUE = {
    "nested_list_of_maps": "foo:\n  - a: 1\n",
    "top_level_sequence_of_maps": "- a: 1\n",
    "shallower_sibling_by_one": "foo:\n   a: 1\n  b: 2\n",
    "shallower_sibling_to_one": "foo:\n  a: 1\n b: 2\n",
    "indented_after_closed_parent": "foo:\n  a: 1\nbar: 1\n  b: 2\n",
}
G35_CONTROLS = {
    "indent_reset_per_parent": "a:\n  k: 1\nb:\n    j: 2\n",
    "dq_open_key": '"role":\n  k: v\n',
    "sq_open_key": "'role':\n  k: v\n",
}


def _before_and_after(fragments):
    out = {}
    for name, frag in fragments.items():
        out[f"before-{name}"] = frag + MANIFEST_FALSE
        out[f"after-{name}"] = MANIFEST_FALSE + frag
    return out


G35_CASES = _before_and_after(G35_TRUE)
G35_CONTROL_CASES = _before_and_after(G35_CONTROLS)


@pytest.mark.parametrize("name", list(G35_CASES), ids=list(G35_CASES))
def test_g35_outside_forms_scan_exactly_true_empty(name):
    assert sm._manifest_scan(G35_CASES[name], STEP) == (True, [])


@pytest.mark.parametrize("name", list(G35_CONTROL_CASES), ids=list(G35_CONTROL_CASES))
def test_g35_controls_stay_false(name):
    assert sm._manifest_scan(G35_CONTROL_CASES[name], STEP) == (False, [STEP])


def test_g36_prefix_is_addressed_from_the_toplevel_not_repo_root(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    sub = repo.root / "subnc"
    sub.mkdir()
    assert _eff_at(repo, sub) == {"flag": False, "error": None}


def test_g36_symlinked_toplevel_contract_is_seen_from_a_subdirectory_root(repo):
    regen(repo, base_manifest=MANIFEST_FALSE, head_manifest=MANIFEST_FALSE)
    sub = repo.root / "subreal"
    (sub / "contract").mkdir(parents=True)
    real = repo.root.parent / "contract_real_g36"
    os.rename(repo.root / "contract", real)
    os.symlink(real, repo.root / "contract")
    assert _eff_at(repo, sub) == {"flag": True, "error": _egprefix(repo, "not a regular file")}


def test_g37_each_cumulative_prefix_is_checked_outermost_first(repo, monkeypatch):
    monkeypatch.setattr(sm, "_STEP_MANIFEST_PATH", "contract/nested/step-manifest.yaml")
    regen(repo)
    real = repo.root / "contract/real_nested"
    real.mkdir()
    os.symlink(real, repo.root / "contract/nested")
    assert _eff(repo) == {
        "flag": True,
        "error": (
            "S3: contract/nested/step-manifest.yaml in the working tree does not match head "
            f"{repo.head[:12]} (not a regular file); commit or restore it, then re-run"
        ),
    }


def test_g37_control_real_nested_directory_is_unchanged(repo, monkeypatch):
    monkeypatch.setattr(sm, "_STEP_MANIFEST_PATH", "contract/nested/step-manifest.yaml")
    regen(repo)
    (repo.root / "contract/nested").mkdir()
    assert _eff(repo) == {"flag": False, "error": None}


# --- T-G19 (round 3): the differential oracle over every fixture -----------------------------


def _yaml_says_gated(text, step):
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    steps = doc.get("steps") if isinstance(doc, dict) else None
    if not isinstance(steps, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("id")) == str(step)
        and bool(item.get("human_gate_required"))
        for item in steps
    )


def _yaml_accepts(text):
    try:
        yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return True


_G19_TEXTS = [
    *MANIFEST_FIXTURES,
    *[(text, STEP) for text in G13_DEFAULTS],
    *[
        (text, STEP)
        for group in (
            G14,
            G15,
            G15B,
            G15_CONTROLS,
            G16,
            G16B,
            G17,
            G20,
            G20_CONTROLS,
            G21B,
            G22,
            G22_CONTROLS,
            G23,
            G25B,
            G26,
            G26_CONTROLS,
            G27,
            G28_TRUE,
            G28_CONTROLS,
            G29,
            G30,
        )
        for text in group.values()
    ],
    (G21B_CONTROL, STEP),
    (G23_CONTROL, STEP),
    (G25B_CONTROL, STEP),
    (G23_ID5, "5"),
    *[(TEMPLATE, s) for s in ("1", "2", "3")],
    *G34_FAMILY,
    *[(t, "7") for t in G19_SEVEN.values()],
    ("steps:\n  - s1\n", STEP),
]
G19_ACCEPTED_FLOOR = 214
G19_GATED_FLOOR = 83


@pytest.mark.parametrize("text,step", _G19_TEXTS)
def test_g19_scan_is_never_looser_than_a_yaml_parser(text, step):
    if _yaml_says_gated(text, step):
        assert sm._manifest_gate_scan(text, step) is True


@pytest.mark.parametrize("text,step", _G19_TEXTS)
def test_g19_path_function_equals_scan_with_none_as_true(tmp_path, text, step):
    scan = sm._manifest_gate_scan(text, step)
    assert sm.manifest_human_gate_required(_manifest(tmp_path, text), step) is (
        True if scan is None else scan
    )


@pytest.mark.parametrize("text,step", _G19_TEXTS)
def test_g34_every_oracle_step_id_is_never_looser(text, step):
    _assert_never_looser(text)


def test_g34_family_transforms_gate_and_the_oracle_is_not_vacuous():
    assert len(G34_FAMILY) == 15
    live = [(t, s) for t, s in G34_FAMILY if _yaml_accepts(t) and _yaml_says_gated(t, s)]
    assert len(live) >= G34_FAMILY_FLOOR
    for text, step in live:
        assert sm._manifest_gate_scan(text, step) is True


def test_g19_oracle_is_not_vacuous():
    accepted = sum(_yaml_accepts(text) for text, _ in _G19_TEXTS)
    gated = sum(_yaml_says_gated(text, step) for text, step in _G19_TEXTS)
    assert accepted >= G19_ACCEPTED_FLOOR
    assert gated >= G19_GATED_FLOOR


@pytest.mark.parametrize("text", list(G19_SEVEN.values()), ids=list(G19_SEVEN))
def test_g19_numeric_alias_ids_scan_true_for_step_7(text):
    assert _yaml_says_gated(text, "7")
    assert sm._manifest_gate_scan(text, "7") is True


def test_g19_oracle_skips_non_dict_items():
    assert _yaml_says_gated("steps:\n  - s1\n", STEP) is False
    assert sm._manifest_gate_scan("steps:\n  - s1\n", STEP) is True
