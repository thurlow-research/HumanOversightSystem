"""security_scan: time-boxed, visible advisory exemptions that fail closed (#1776).

`security_scan.sh` blocks on any pip-audit advisory, which made it permanently
red on advisories in tools HOS cannot yet upgrade (black x2; PyJWT is handled by
the requirements.txt floor alone, with no exemption).
The exemptions live in `scripts/oversight/security_scan_logic.py`; these tests
pin the roster (a roster edit must force a visible test edit), the narrowness of
the match (AC-2), the visibility of every suppression (AC-3), and the
fail-closed behaviour on anything unreadable (AC-5).

Logic tests are hermetic: they pass `today` explicitly and never touch the
network or depend on the live venv's package versions. A live pip-audit run is
landing evidence, not a test — a required check that queried a live advisory
feed would go red on the next unrelated CVE, which is the disease this cures.
The gate tests drive the real shell path through the `HOS_PIP_AUDIT_BIN` stub
seam and skip when the oversight venv is absent.

Two tests are deliberately environment- or date-sensitive: M5 (this repo is the
HOS source repo) and X5 (a dated cliff — from 2027-02-01 the shipped records are
expired and the required `tests` check turns red until a human renews or removes
them; that is the forcing function, #1776 H3).
"""

from __future__ import annotations

import datetime
import io
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_module_from_path

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "oversight" / "gates" / "security_scan.sh"
_LOGIC_PATH = _REPO / "scripts" / "oversight" / "security_scan_logic.py"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

sl = load_module_from_path("security_scan_logic_1776", _LOGIC_PATH)

_ACTIVE = sl.RosterMode(True, "HOS source repository: test")
_INACTIVE = sl.RosterMode(False, "installed tree: .hos-release present")
_TODAY = datetime.date(2026, 10, 6)
_EXPIRES = datetime.date(2027, 1, 31)

_needs_gate = pytest.mark.skipif(
    shutil.which("bash") is None
    or not (_VENV_BIN / "python3").exists()
    or not (_VENV_BIN / "bandit").exists(),
    reason="oversight venv (python3 + bandit) or bash unavailable",
)


def _vuln(vid: str, fixes: tuple[str, ...] = (), aliases: tuple[str, ...] = ()) -> dict:
    return {"id": vid, "fix_versions": list(fixes), "aliases": list(aliases), "description": "d"}


def _dep(name: str, version: str, *vulns: dict) -> dict:
    return {"name": name, "version": version, "vulns": list(vulns)}


def _audit(*deps: object) -> dict:
    return {"dependencies": list(deps), "fixes": []}


def _run(
    document: object,
    *,
    today: datetime.date = _TODAY,
    mode: Any = _ACTIVE,
    rules: tuple | None = None,
) -> tuple[str, str, int]:
    if rules is None:
        rules = sl.SUPPRESSIONS if mode.active else ()
    out, err, status = sl.run_filter(json.dumps(document), rules, mode, today)
    return "\n".join(out), "\n".join(err), status


_BLACK_2120 = _vuln("PYSEC-2026-2120", ("26.3.0",))
_BLACK_2121 = _vuln("PYSEC-2026-2121", ("26.3.1",))
_PYJWT_4146 = _vuln("PYSEC-2026-4146")

# Test-only no-fix record. It is NEVER in SUPPRESSIONS: it exists so the no-fix
# key (TD-D2b), which no shipped record uses, stays covered.
_NOFIX = sl.Exemption(
    "pyjwt",
    "PYSEC-2026-4146",
    None,
    _EXPIRES,
    "Test-only no-fix record exercising the fixed_in=None key; never shipped.",
    4242,
)


# ── Roster pins ─────────────────────────────────────────────────────────────


def test_r1_roster_is_exactly_the_two_ruled_records():
    got = [
        (r.package, r.advisory_id, r.fixed_in, r.expires, r.tracking_issue) for r in sl.SUPPRESSIONS
    ]
    assert got == [
        ("black", "PYSEC-2026-2120", "26.3.0", _EXPIRES, 1961),
        ("black", "PYSEC-2026-2121", "26.3.1", _EXPIRES, 1961),
    ]


def test_r2_shipped_roster_is_valid():
    assert sl.validate_exemptions(sl.SUPPRESSIONS) == []


def test_r3_no_shipped_pyjwt_record_the_floor_handles_all_of_it():
    assert [r for r in sl.SUPPRESSIONS if r.package == "pyjwt"] == []


def test_r4_no_record_tracks_the_issue_that_closes_on_merge():
    assert all(r.tracking_issue != 1776 for r in sl.SUPPRESSIONS)


# ── Matching (AC-2) ─────────────────────────────────────────────────────────


def test_s1_unlisted_package_is_kept_and_fails():
    out, _, status = _run(_audit(_dep("requests", "2.0.0", _vuln("CVE-2099-0001"))))
    assert status == 1
    assert "requests 2.0.0 [CVE-2099-0001]" in out
    assert "GATE FAIL: 1 dependency advisory(ies) not covered by an exemption" in out


def test_s2_each_record_suppresses_at_its_bounded_version():
    out, _, status = _run(_audit(_dep("black", "24.10.0", _BLACK_2120, _BLACK_2121)))
    assert status == 0, out
    assert "2 advisory(ies) suppressed by a time-boxed exemption" in out


def test_s2b_no_fix_record_suppresses_while_fix_versions_is_empty():
    out, _, status = _run(_audit(_dep("pyjwt", "2.15.1", _PYJWT_4146)), rules=(_NOFIX,))
    assert status == 0, out
    assert "1 advisory(ies) suppressed by a time-boxed exemption" in out


def test_s3_black_2121_at_fixed_version_is_premise_broken():
    out, _, status = _run(_audit(_dep("black", "26.3.1", _BLACK_2121)))
    assert status == 1
    assert "PREMISE BROKEN" in out


def test_s4_other_ids_on_roster_packages_fail_closed():
    out, _, status = _run(
        _audit(
            _dep("pyjwt", "2.13.0", _vuln("PYSEC-2026-4140", ("2.14.0",))),
            _dep("black", "24.10.0", _vuln("PYSEC-2026-9999")),
        )
    )
    assert status == 1
    assert "pyjwt 2.13.0 [PYSEC-2026-4140]" in out
    assert "black 24.10.0 [PYSEC-2026-9999]" in out


def test_s5_canonical_name_variants_match_but_different_names_do_not():
    out, _, status = _run(
        _audit(_dep("Black", "24.10.0", _BLACK_2120), _dep("PyJWT", "2.15.1", _PYJWT_4146)),
        rules=(*sl.SUPPRESSIONS, _NOFIX),
    )
    assert status == 0, out
    out, _, status = _run(_audit(_dep("py_jwt", "2.15.1", _PYJWT_4146)), rules=(_NOFIX,))
    assert status == 1


def test_s6_unparseable_installed_version_is_kept():
    out, _, status = _run(_audit(_dep("black", "not-a-version", _BLACK_2120)))
    assert status == 1
    assert "UNPARSEABLE VERSION" in out


def test_s7_no_fix_record_goes_inert_when_a_fix_is_reported():
    out, _, status = _run(
        _audit(_dep("pyjwt", "2.15.1", _vuln("PYSEC-2026-4146", ("2.16.0",)))), rules=(_NOFIX,)
    )
    assert status == 1
    assert "FIX NOW AVAILABLE" in out
    assert "2.16.0" in out


def test_s8_duplicate_sources_union_fix_versions_so_disagreement_fails_closed():
    out, _, status = _run(
        _audit(
            _dep(
                "pyjwt",
                "2.15.1",
                _vuln("PYSEC-2026-4146", ()),
                _vuln("PYSEC-2026-4146", ("2.16.0",)),
            )
        ),
        rules=(_NOFIX,),
    )
    assert status == 1
    assert "FIX NOW AVAILABLE" in out


def test_s9_shipped_roster_keeps_pyjwt_4146_the_floor_not_an_exemption_handles_it():
    out, _, status = _run(_audit(_dep("pyjwt", "2.13.0", _PYJWT_4146)))
    assert status == 1
    assert "pyjwt 2.13.0 [PYSEC-2026-4146]" in out


# ── Expiry ──────────────────────────────────────────────────────────────────

_BLACK_ONLY = _audit(_dep("black", "24.10.0", _BLACK_2120))


def test_x1_valid_through_the_expiry_date_inclusive():
    _, _, status = _run(_BLACK_ONLY, today=_EXPIRES)
    assert status == 0


def test_x2_kept_the_day_after_expiry():
    out, _, status = _run(_BLACK_ONLY, today=_EXPIRES + datetime.timedelta(days=1))
    assert status == 1
    assert "EXEMPTION EXPIRED" in out
    assert "2027-01-31" in out
    assert "#1961" in out


def test_x3_expiring_soon_warning_at_fourteen_days():
    out, _, status = _run(_BLACK_ONLY, today=_EXPIRES - datetime.timedelta(days=14))
    assert status == 0
    assert "EXPIRING SOON: black [PYSEC-2026-2120]" in out
    assert "(14 day(s))" in out


def test_x4_no_warning_at_fifteen_days():
    out, _, status = _run(_BLACK_ONLY, today=_EXPIRES - datetime.timedelta(days=15))
    assert status == 0
    assert "EXPIRING SOON" not in out


def test_x5_dated_cliff_no_shipped_record_is_expired():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    lapsed = [
        f"{r.package} [{r.advisory_id}] (expired {r.expires})"
        for r in sl.SUPPRESSIONS
        if r.expires < today
    ]
    assert not lapsed, (
        "security_scan exemption(s) have lapsed: "
        + "; ".join(lapsed)
        + ". Renewal needs a fresh HUMAN decision (#1776 H3) — fix the dependency "
        "(black: #1961) or get that decision; do not just bump the date."
    )


@pytest.mark.parametrize("bad", ["2027-01-31", datetime.datetime(2027, 1, 31, 0, 0)])
def test_x6_expires_must_be_a_plain_date(bad):
    rule = sl.SUPPRESSIONS[0]._replace(expires=bad)
    errors = sl.validate_exemptions((rule,))
    assert any("expires" in e for e in errors)


# ── Fail closed ─────────────────────────────────────────────────────────────


def test_f1_not_json_is_exit_2():
    out, err, status = _run_text("not json")
    assert status == 2
    assert "JSONDecodeError" in err


def _run_text(text: str) -> tuple[str, str, int]:
    out, err, status = sl.run_filter(text, sl.SUPPRESSIONS, _ACTIVE, _TODAY)
    return "\n".join(out), "\n".join(err), status


@pytest.mark.parametrize(
    "doc",
    [[], {"fixes": []}, {"dependencies": "x"}, {"dependencies": []}],
    ids=["root-list", "missing", "not-list", "empty"],
)
def test_f2_unauditable_shapes_are_exit_2(doc):
    _, err, status = _run(doc)
    assert status == 2
    assert "could not parse pip-audit output" in err


def test_f3_invalid_roster_is_rejected_and_exit_2():
    good = sl.SUPPRESSIONS[0]
    bad_rosters = {
        "short reason": good._replace(reason="too short"),
        "non-canonical package": good._replace(package="Black"),
        "bad fixed_in": good._replace(fixed_in="not-a-version"),
        "tracking_issue bool": good._replace(tracking_issue=True),
    }
    for label, rule in bad_rosters.items():
        assert sl.validate_exemptions((rule,)), label
        _, err, status = _run(_audit(_dep("x", "1")), rules=(rule,))
        assert status == 2, label
        assert "exemption roster invalid" in err, label
    assert any("duplicate" in e for e in sl.validate_exemptions((good, good)))


@pytest.mark.parametrize("entry", [None, 0, "", [], "x"])
def test_f4_falsy_or_non_mapping_dependency_entries_are_kept(entry):
    out, _, status = _run(_audit(entry))
    assert status == 1
    assert "UNATTRIBUTABLE" in out


def test_f5_malformed_vuln_never_rides_an_exemption():
    out, _, status = _run(_audit(_dep("black", "24.10.0", {"fix_versions": ["26.3.0"]})))
    assert status == 1
    assert "UNATTRIBUTABLE" in out


def test_f6_clean_audit_with_broken_roster_is_exit_2():
    rule = sl.SUPPRESSIONS[0]._replace(reason="x")
    _, err, status = _run(_audit(_dep("requests", "2.0.0")), rules=(rule,))
    assert status == 2
    assert "exemption roster invalid" in err


def test_f7_vulns_not_a_list_is_kept():
    out, _, status = _run(_audit({"name": "black", "version": "24.10.0", "vulns": "oops"}))
    assert status == 1
    assert "UNATTRIBUTABLE" in out


def _black_2120_with(**fields: object) -> dict:
    vuln: dict = {"id": "PYSEC-2026-2120", "aliases": [], "description": "d"}
    vuln.update(fields)
    return _audit(_dep("black", "24.10.0", vuln))


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"fix_versions": "26.3.0"},
        {"fix_versions": None},
        {"fix_versions": [26]},
        {"fix_versions": {}},
    ],
    ids=["missing", "string", "none", "list-of-int", "dict"],
)
def test_f9_malformed_fix_versions_is_unattributable_and_never_suppressed(fields):
    out, _, status = _run(_black_2120_with(**fields))
    assert status == 1
    assert "UNATTRIBUTABLE" in out
    assert "PYSEC-2026-2120" in out


@pytest.mark.parametrize("fix_versions", ["none", None], ids=["string", "none"])
def test_f9b_malformed_fix_versions_never_satisfies_the_no_fix_key(fix_versions):
    doc = _audit(_dep("pyjwt", "2.15.1", {"id": "PYSEC-2026-4146", "fix_versions": fix_versions}))
    out, _, status = _run(doc, rules=(_NOFIX,))
    assert status == 1
    assert "UNATTRIBUTABLE" in out


def test_f9c_malformed_aliases_stay_lenient_and_do_not_block_a_suppression():
    out, _, status = _run(_black_2120_with(fix_versions=["26.3.0"], aliases="x"))
    assert status == 0, out


@pytest.mark.parametrize(
    "deps",
    [
        [{}],
        [{"name": "black", "version": "24.10.0"}],
        [{"vulns": []}],
        [_dep("x", "1"), {}],
        [{"name": "", "version": "1", "vulns": []}],
        [{"name": "x", "version": 1, "vulns": []}],
    ],
    ids=["empty", "no-vulns", "no-name-version", "good-plus-empty", "empty-name", "int-version"],
)
def test_f10_structurally_incomplete_entries_are_not_audited(deps):
    out, _, status = _run(_audit(*deps))
    assert status == 1
    assert "UNATTRIBUTABLE" in out
    assert "incomplete" in out


def test_f10b_incomplete_reason_names_the_missing_field():
    out, _, _ = _run(_audit({"name": "black", "version": "24.10.0"}))
    assert "'vulns' missing" in out


def test_f10c_skip_entry_stays_not_checked_and_non_blocking():
    out, _, status = _run(_audit(_dep("x", "1"), {"name": "foo", "skip_reason": "not on PyPI"}))
    assert status == 0, out
    assert "NOT CHECKED" in out
    assert "foo" in out


def test_f8_a_crash_is_exit_2_not_a_pass(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sl, "partition", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_audit(_dep("requests", "1")))))
    assert sl.main(["filter"]) == 2
    assert "crashed" in capsys.readouterr().err


# ── Parsing / report (AC-3) ─────────────────────────────────────────────────


def test_p1_duplicate_advisory_is_counted_once():
    out, _, status = _run(_audit(_dep("black", "24.10.0", _BLACK_2121, _BLACK_2121)))
    assert status == 0
    assert "1 distinct advisory(ies) from 2 raw record(s)" in out


def test_p2_fix_version_spelling_differences_are_unioned_and_shown():
    out, _, status = _run(
        _audit(
            _dep(
                "black",
                "24.10.0",
                _vuln("PYSEC-2026-2121", ("26.2",)),
                _vuln("PYSEC-2026-2121", ("26.2.0",)),
            )
        )
    )
    assert status == 0
    assert "26.2, 26.2.0" in out


def test_p3_only_vulnerable_dependencies_are_considered():
    deps = [_dep(f"pkg{i}", "1.0") for i in range(115)]
    deps.append(_dep("black", "24.10.0", _BLACK_2120, _BLACK_2121))
    deps.append({"name": "plain", "version": "1", "vulns": []})
    out, _, status = _run(_audit(*deps))
    assert status == 0
    assert "117 dependencies read" in out
    assert "2 distinct advisory(ies)" in out


def test_p4_skipped_dependency_is_reported_not_checked_but_not_blocking():
    out, _, status = _run(
        _audit(
            _dep("requests", "2.0.0"),
            {"name": "mine", "version": "0.1", "skip_reason": "not on PyPI"},
        )
    )
    assert status == 0
    assert "NOT CHECKED: mine 0.1 was not audited by pip-audit (not on PyPI)" in out
    assert "1 NOT CHECKED" in out


def test_p4b_skip_marker_does_not_hide_reported_vulns():
    entry = {
        "name": "mine",
        "version": "0.1",
        "skip_reason": "not on PyPI",
        "vulns": [_vuln("CVE-2099-0002")],
    }
    out, _, status = _run(_audit(entry))
    assert status == 1
    assert "NOT CHECKED: mine" in out
    assert "mine 0.1 [CVE-2099-0002]" in out


def test_p5_suppression_line_carries_id_reason_expiry_and_issue():
    out, _, _ = _run(_audit(_dep("black", "24.10.0", _BLACK_2120)))
    line = next(
        ln for ln in out.splitlines() if ln.startswith("    black 24.10.0 [PYSEC-2026-2120]")
    )
    assert "fix: 26.3.0" in line
    assert "exempt until 2027-01-31 (#1961)" in line
    assert "GitHub Action" in line


def test_p6_passing_run_prints_mode_roster_and_suppressions():
    out, _, status = _run(_audit(_dep("black", "24.10.0", _BLACK_2120)))
    assert status == 0
    assert "Exemption roster: ACTIVE" in out
    assert "black [PYSEC-2026-2120] fixed_in 26.3.0 — expires 2027-01-31 — APPLIED — #1961" in out
    assert (
        "black [PYSEC-2026-2121] fixed_in 26.3.1 — expires 2027-01-31 — "
        "NOT NEEDED (not reported in this environment) — #1961"
    ) in out
    assert "NOT NEEDED (not reported in this environment)" in out
    assert "OK: no dependency advisories outside the exemption roster (1 suppressed;" in out


# ── Scope (H2) ──────────────────────────────────────────────────────────────


def test_m1_source_repo_layout_is_active(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "hos_install.sh").write_text("#!/bin/sh\n")
    assert sl.roster_mode(tmp_path).active is True


def test_m2_installed_tree_is_inactive(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "hos_install.sh").write_text("#!/bin/sh\n")
    (tmp_path / ".hos-release").write_text("v0.0.0\n")
    mode = sl.roster_mode(tmp_path)
    assert mode.active is False
    assert ".hos-release present" in mode.why


def test_m3_neither_marker_is_inactive(tmp_path):
    mode = sl.roster_mode(tmp_path)
    assert mode.active is False
    assert "not found" in mode.why


def test_m4_inactive_mode_enforces_every_advisory_and_says_so():
    out, _, status = _run(_audit(_dep("black", "24.10.0", _BLACK_2121)), mode=_INACTIVE)
    assert status == 1
    assert "Exemption roster: INACTIVE" in out
    assert "black 24.10.0 [PYSEC-2026-2121]" in out


def test_m5_this_repo_is_the_source_repo():
    assert sl.roster_mode(_REPO).active is True


def test_m6_inactive_mode_ignores_a_roster_passed_by_the_caller():
    out, _, status = _run(
        _audit(_dep("black", "24.10.0", _BLACK_2121)), mode=_INACTIVE, rules=sl.SUPPRESSIONS
    )
    assert status == 1
    assert "Exemption roster: INACTIVE" in out
    assert "black 24.10.0 [PYSEC-2026-2121]" in out


# ── Exemption premises (PYSEC-2026-2120 / -2121) ────────────────────────────
_PREMISE_2121 = (
    "the PYSEC-2026-2121 exemption's premise no longer holds (HOS must never set "
    "black's python-cell-magics) — remove the exemption (upgrade black, #1961) "
    "rather than editing this test"
)
_PREMISE_2120 = (
    "the PYSEC-2026-2120 exemption's premise no longer holds (HOS must not use the "
    "Black GitHub Action) — remove the exemption (upgrade black, #1961) rather "
    "than editing this test"
)


def test_pr1_pyproject_black_table_never_sets_python_cell_magics():
    tomllib = pytest.importorskip("tomllib", reason="tomllib needs Python 3.11+")
    with (_REPO / "pyproject.toml").open("rb") as fh:
        black_cfg = tomllib.load(fh).get("tool", {}).get("black", {})
    found = [k for k in black_cfg if k in ("python-cell-magics", "python_cell_magics")]
    assert not found, f"{found} set in pyproject.toml [tool.black]: {_PREMISE_2121}"


def test_pr2_lint_check_never_passes_python_cell_magics_to_black():
    lines = (_REPO / "scripts/oversight/gates/lint_check.sh").read_text().splitlines()
    bad = [ln for ln in lines if "black" in ln and "python-cell-magics" in ln]
    assert not bad, f"{bad}: {_PREMISE_2121}"


def test_pr3_no_workflow_references_the_black_github_action():
    bad = [
        str(p.relative_to(_REPO))
        for p in sorted((_REPO / ".github" / "workflows").glob("*"))
        if p.is_file() and "psf/black" in p.read_text()
    ]
    assert not bad, f"{bad} reference psf/black: {_PREMISE_2120}"


# ── Gate (shell path, via the HOS_PIP_AUDIT_BIN stub seam) ──────────────────


def _stub(tmp_path: Path, body: str, rc: int) -> Path:
    payload = tmp_path / "payload.txt"
    payload.write_text(body)
    stub = tmp_path / "pip-audit-stub"
    stub.write_text(f"#!/usr/bin/env bash\ncat '{payload}'\nexit {rc}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def _gate(tmp_path: Path, *args: str, stub: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GATE_TIMEOUT": "30", "GATE_RETRIES": "0"}
    if stub is not None:
        env["HOS_PIP_AUDIT_BIN"] = str(stub)
    return subprocess.run(
        ["bash", str(_GATE), *args],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )


def _clean_py(tmp_path: Path) -> str:
    (tmp_path / "ok.py").write_text("x = 1\n")
    return "ok.py"


@_needs_gate
def test_g1_new_vulnerable_package_fails_the_gate(tmp_path):
    body = json.dumps(_audit(_dep("requests", "2.0.0", _vuln("CVE-2099-0001"))))
    res = _gate(tmp_path, _clean_py(tmp_path), stub=_stub(tmp_path, body, 1))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "requests 2.0.0 [CVE-2099-0001]" in res.stdout


@_needs_gate
def test_g2_only_roster_advisories_pass_with_visible_suppressions(tmp_path):
    body = json.dumps(_audit(_dep("black", "24.10.0", _BLACK_2120, _BLACK_2121, _BLACK_2121)))
    res = _gate(tmp_path, _clean_py(tmp_path), stub=_stub(tmp_path, body, 1))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Exemption roster: ACTIVE" in res.stdout
    assert "2 advisory(ies) suppressed by a time-boxed exemption" in res.stdout
    assert "GATE PASS: no blocking security issues (pip-audit binary overridden)" in res.stdout


@_needs_gate
def test_g3_wrong_shape_audit_fails_and_says_it_could_not_be_read(tmp_path):
    res = _gate(tmp_path, _clean_py(tmp_path), stub=_stub(tmp_path, '{"dependencies": "x"}', 0))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "could not be read or decided" in res.stdout


@_needs_gate
def test_g4_pip_audit_not_completing_is_named_in_the_pass_line(tmp_path):
    res = _gate(tmp_path, _clean_py(tmp_path), stub=_stub(tmp_path, "not json", 3))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "NOT CHECKED: pip-audit did not complete after retries" in res.stdout
    last = res.stdout.strip().splitlines()[-1]
    assert (
        last
        == "GATE PASS: no blocking security issues (pip-audit binary overridden; pip-audit NOT CHECKED — see above)"
    )


def _counting_stub(tmp_path: Path, script_body: str) -> tuple[Path, Path]:
    marker = tmp_path / "calls"
    stub = tmp_path / "pip-audit-stub"
    stub.write_text(f"#!/usr/bin/env bash\necho x >> '{marker}'\n{script_body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub, marker


def _gate_retries(tmp_path: Path, stub: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GATE_TIMEOUT": "30", "GATE_RETRIES": "1", "HOS_PIP_AUDIT_BIN": str(stub)}
    return subprocess.run(
        ["bash", str(_GATE), _clean_py(tmp_path)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )


@_needs_gate
def test_g4c_corrupt_scan_with_rc_0_is_retried_then_fails_closed(tmp_path):
    stub, marker = _counting_stub(tmp_path, "echo 'not json'\nexit 0")
    res = _gate_retries(tmp_path, stub)
    assert res.returncode != 0, res.stdout + res.stderr
    assert (
        "GATE FAIL: pip-audit completed at least once but its output could not be parsed, "
        "and no attempt produced a readable scan (2 attempt(s))" in res.stdout
    )
    assert "NOT CHECKED" not in res.stdout
    assert len(marker.read_text().splitlines()) >= 2


@_needs_gate
def test_g4d_corrupt_first_attempt_then_clean_retry_passes(tmp_path):
    clean = json.dumps(_audit(_dep("requests", "2.0.0")))
    body = f"if [ \"$(wc -l < '{tmp_path / 'calls'}')\" -le 1 ]; then echo 'not json'; else echo '{clean}'; fi\nexit 0"
    stub, marker = _counting_stub(tmp_path, body)
    res = _gate_retries(tmp_path, stub)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "GATE FAIL" not in res.stdout
    assert len(marker.read_text().splitlines()) == 2


def _mixed_failure(tmp_path: Path, first: str, second: str):
    body = f"if [ \"$(wc -l < '{tmp_path / 'calls'}')\" -le 1 ]; then {first}; else {second}; fi"
    stub, marker = _counting_stub(tmp_path, body)
    return _gate_retries(tmp_path, stub), marker


def _assert_mixed_fails(res, marker):
    assert res.returncode != 0, res.stdout + res.stderr
    assert "GATE FAIL: pip-audit completed at least once" in res.stdout
    assert "NOT CHECKED" not in res.stdout
    assert len(marker.read_text().splitlines()) == 2


@_needs_gate
def test_g4e_unparseable_then_execution_failure_still_fails_closed(tmp_path):
    res, marker = _mixed_failure(tmp_path, "echo 'not json'; exit 0", "exit 3")
    _assert_mixed_fails(res, marker)


@_needs_gate
def test_g4f_unparseable_rc1_then_timeout_still_fails_closed(tmp_path):
    res, marker = _mixed_failure(tmp_path, "echo 'not json'; exit 1", "exit 124")
    _assert_mixed_fails(res, marker)


@_needs_gate
def test_g4b_override_is_noted_and_named_in_the_pass_line(tmp_path):
    body = json.dumps(_audit(_dep("requests", "2.0.0")))
    stub = _stub(tmp_path, body, 0)
    res = _gate(tmp_path, _clean_py(tmp_path), stub=stub)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"NOTE: pip-audit binary overridden by HOS_PIP_AUDIT_BIN={stub}" in res.stdout
    last = res.stdout.strip().splitlines()[-1]
    assert "pip-audit binary overridden" in last


@_needs_gate
def test_g4g_non_executable_override_fails_closed_never_skips(tmp_path):
    missing = tmp_path / "no-such-pip-audit"
    res = _gate(tmp_path, _clean_py(tmp_path), stub=missing)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"GATE FAIL: HOS_PIP_AUDIT_BIN={missing} is not an executable file" in res.stdout
    assert "GATE PASS" not in res.stdout
    assert "SKIP: pip-audit" not in res.stdout


@_needs_gate
def test_g4h_directory_override_fails_closed_never_skips(tmp_path):
    a_dir = tmp_path / "a-dir"
    a_dir.mkdir()
    res = _gate(tmp_path, _clean_py(tmp_path), stub=a_dir)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"GATE FAIL: HOS_PIP_AUDIT_BIN={a_dir} is not an executable file" in res.stdout
    assert "GATE PASS" not in res.stdout
    assert "NOT CHECKED" not in res.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_g5_empty_changeset_never_invokes_pip_audit(tmp_path):
    marker = tmp_path / "invoked"
    stub = tmp_path / "pip-audit-stub"
    stub.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 0\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    res = _gate(tmp_path, "--empty-changeset", stub=stub)
    assert res.returncode == 0, res.stderr
    assert "NOT CHECKED" in res.stdout
    assert not marker.exists()


def test_g6_bandit_skip_is_named_in_the_pass_line_statically():
    text = _GATE.read_text()
    skip_idx = text.index('echo "SKIP: bandit not in oversight venv')
    append = 'NOT_PERFORMED+=("bandit SKIPPED — not installed")'
    assert text.index(append) > skip_idx
    assert text.index(append) - skip_idx < 200
    assert "GATE PASS: no blocking security issues ($NOT_PERFORMED_TEXT)" in text


# ── Static ──────────────────────────────────────────────────────────────────


def test_t1_gate_has_no_fail_open_default_of_zero():
    assert '|| echo "0"' not in _GATE.read_text()


def test_t2_protected_surface_entries_are_exact_not_a_glob():
    rha = load_module_from_path(
        "require_human_approval_1776", _REPO / "scripts" / "framework" / "require_human_approval.py"
    )
    globs = rha.load_globs(_REPO / "scripts" / "framework" / "protected_surfaces.txt")

    def protected(path: str) -> bool:
        return bool(rha.matched_surfaces([path], globs))

    assert protected("scripts/oversight/security_scan_logic.py")
    assert protected("scripts/oversight/secret_scan_logic.py")
    # ADR-1935 N3: these stay unprotected — guards a *_logic.py glob creeping back.
    assert not protected("scripts/oversight/prompt_audit_logic.py")
    assert not protected("scripts/oversight/retry_rescue_logic.py")


def test_t3_identity_doc_and_adr_list_the_new_module():
    identity = (_REPO / "docs" / "AGENT-IDENTITY.md").read_text()
    assert "scripts/oversight/security_scan_logic.py" in identity
    assert "scripts/oversight/secret_scan_logic.py" in identity
    adr = (_REPO / "docs" / "v0.7.0" / "ADR-1935-protected-surface-recalibration.md").read_text()
    assert "scripts/oversight/security_scan_logic.py" in adr


def test_t4_requirements_floors_and_black_pin():
    lines = [
        ln.strip()
        for ln in (_REPO / "scripts" / "oversight" / "requirements.txt").read_text().splitlines()
    ]
    assert "pyjwt>=2.15.0" in lines
    assert any(ln.startswith("packaging>=") for ln in lines)
    assert "black>=24.0,<25.0" in lines  # #103
