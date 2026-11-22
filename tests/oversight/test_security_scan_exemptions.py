"""security_scan: time-boxed, visible advisory exemptions that fail closed (#1776).

`dependency_audit.sh` blocks on any pip-audit advisory, which made it permanently
red on advisories in tools HOS cannot yet upgrade (black x2, and mcp, opentelemetry-api
and wcmatch via semgrep's pins; PyJWT is handled by the requirements.txt floor alone, with no exemption).
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
HOS source repo) and X5 (a dated cliff — from 2027-01-01 the three mcp #2194
records are expired, and from 2027-02-01 the rest, and the required `tests` check
turns red until a human renews or removes them; that is the forcing function,
#1776 H3).

The gate half of this module moved from `security_scan.sh` to `dependency_audit.sh`
in #1605 (AD-22); the logic module and the roster are untouched.
"""

from __future__ import annotations

import ast
import datetime
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_module_from_path

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "oversight" / "gates" / "dependency_audit.sh"
_BANDIT_GATE = _REPO / "scripts" / "oversight" / "gates" / "security_scan.sh"
_LOGIC_PATH = _REPO / "scripts" / "oversight" / "security_scan_logic.py"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

sl = load_module_from_path("security_scan_logic_1776", _LOGIC_PATH)

_ACTIVE = sl.RosterMode(True, "HOS source repository: test")
_INACTIVE = sl.RosterMode(False, "installed tree: .hos-release present")
_TODAY = datetime.date(2026, 10, 6)
_EXPIRES = datetime.date(2027, 1, 31)
_EXPIRES_MCP_2194 = datetime.date(2026, 12, 31)

_needs_gate = pytest.mark.skipif(
    shutil.which("bash") is None or not (_VENV_BIN / "python3").exists(),
    reason="oversight venv python3 or bash unavailable",
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
_BLACK_114134 = _vuln("CVE-2026-114134", ("26.10.1",), ("GHSA-cg8m-r9f2-5wm2",))
_PYJWT_4146 = _vuln("PYSEC-2026-4146")
_MCP_59951 = _vuln("CVE-2026-59951", ("1.30.0", "2.2.0"), ("GHSA-84m7-p3x7-pcfv",))
_OTEL_114603 = _vuln("CVE-2026-114603", ("1.45.1",))
_OTEL_126360 = _vuln("CVE-2026-126360", ("1.45.2",))
_WCMATCH_132276 = _vuln("CVE-2026-132276", ("11.2",), ("GHSA-53pm-wgxf-c6qf",))
_MCP_115563 = _vuln("CVE-2026-115563", ("1.30.0", "2.2.0"), ("GHSA-qx49-fqc8-xw99",))
_MCP_2194 = (
    _vuln("CVE-2026-116684", ("1.30.0", "2.2.0"), ("GHSA-w4fh-qvv9-3v23",)),
    _vuln("CVE-2026-116685", ("1.30.0", "2.2.0"), ("GHSA-5h93-6whr-6q8j",)),
    _vuln("CVE-2026-116686", ("1.30.0", "2.2.0"), ("GHSA-rwrf-2pqf-9j8j",)),
)

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


def test_r1_roster_is_exactly_the_eleven_authorized_records():
    got = [
        (r.package, r.advisory_id, r.fixed_in, r.expires, r.tracking_issue) for r in sl.SUPPRESSIONS
    ]
    assert got == [
        ("black", "PYSEC-2026-2120", "26.3.0", _EXPIRES, 1961),
        ("black", "PYSEC-2026-2121", "26.3.1", _EXPIRES, 1961),
        ("black", "CVE-2026-114134", "26.10.1", _EXPIRES, 1961),
        ("mcp", "CVE-2026-59951", "1.30.0", _EXPIRES, 2120),
        ("mcp", "CVE-2026-116684", "1.30.0", _EXPIRES_MCP_2194, 2120),
        ("mcp", "CVE-2026-116685", "1.30.0", _EXPIRES_MCP_2194, 2120),
        ("mcp", "CVE-2026-116686", "1.30.0", _EXPIRES_MCP_2194, 2120),
        ("mcp", "CVE-2026-115563", "1.30.0", _EXPIRES_MCP_2194, 2120),
        ("opentelemetry-api", "CVE-2026-114603", "1.45.1", _EXPIRES, 2179),
        ("opentelemetry-api", "CVE-2026-126360", "1.45.2", _EXPIRES, 2179),
        ("wcmatch", "CVE-2026-132276", "11.2", _EXPIRES_MCP_2194, 2120),
    ]


def test_r2_shipped_roster_is_valid():
    assert sl.validate_exemptions(sl.SUPPRESSIONS) == []


def test_r3_no_shipped_pyjwt_record_the_floor_handles_all_of_it():
    assert [r for r in sl.SUPPRESSIONS if r.package == "pyjwt"] == []


def test_r3b_requirements_declare_the_filelock_floor():
    from packaging.requirements import Requirement
    from packaging.version import Version

    reqs = [
        Requirement(line.split("#")[0].strip())
        for line in (_REPO / "scripts" / "oversight" / "requirements.txt").read_text().splitlines()
        if line.split("#")[0].strip()
    ]
    floors = [
        Version(spec.version)
        for r in reqs
        if r.name == "filelock"
        for spec in r.specifier
        if spec.operator == ">="
    ]
    assert floors and max(floors) >= Version("4.2.1")


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


def test_s2d_black_114134_is_suppressed_at_24_10_0_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("black", "24.10.0", _BLACK_114134)))
    assert status == 0
    assert "black 24.10.0 [CVE-2026-114134]" in out
    out, _, status = _run(_audit(_dep("black", "26.10.1", _BLACK_114134)))
    assert status == 1
    assert "black 26.10.1 [CVE-2026-114134]" in out


def test_s2c_mcp_59951_is_suppressed_at_1_29_0_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("mcp", "1.29.0", _MCP_59951)))
    assert status == 0, out
    assert "mcp 1.29.0 [CVE-2026-59951]" in out
    assert "exempt until 2027-01-31 (#2120)" in out
    out, _, status = _run(_audit(_dep("mcp", "1.30.0", _MCP_59951)))
    assert status == 1
    assert "PREMISE BROKEN" in out


@pytest.mark.parametrize("vuln", _MCP_2194, ids=[v["id"] for v in _MCP_2194])
def test_s2f_mcp_2194_is_suppressed_at_1_29_0_and_kept_once_fixed(vuln):
    out, _, status = _run(_audit(_dep("mcp", "1.29.0", vuln)))
    assert status == 0
    line = next(ln for ln in out.splitlines() if f"mcp 1.29.0 [{vuln['id']}]" in ln)
    assert "exempt until 2026-12-31 (#2120)" in line
    out, _, status = _run(_audit(_dep("mcp", "1.30.0", vuln)))
    assert status == 1
    assert f"mcp 1.30.0 [{vuln['id']}]" in out


def test_s2h_mcp_115563_is_suppressed_at_1_29_0_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("mcp", "1.29.0", _MCP_115563)))
    assert status == 0, out
    line = next(ln for ln in out.splitlines() if "mcp 1.29.0 [CVE-2026-115563]" in ln)
    assert "exempt until 2026-12-31 (#2120)" in line
    out, _, status = _run(_audit(_dep("mcp", "1.30.0", _MCP_115563)))
    assert status == 1
    assert "mcp 1.30.0 [CVE-2026-115563]" in out


def test_s2i_wcmatch_132276_is_suppressed_at_8_5_2_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("wcmatch", "8.5.2", _WCMATCH_132276)))
    assert status == 0, out
    line = next(ln for ln in out.splitlines() if "wcmatch 8.5.2 [CVE-2026-132276]" in ln)
    assert "exempt until 2026-12-31 (#2120)" in line
    out, _, status = _run(_audit(_dep("wcmatch", "11.2", _WCMATCH_132276)))
    assert status == 1
    assert "wcmatch 11.2 [CVE-2026-132276]" in out


def test_s2e_otel_114603_is_suppressed_at_1_37_0_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("opentelemetry-api", "1.37.0", _OTEL_114603)))
    assert status == 0, out
    assert "opentelemetry-api 1.37.0 [CVE-2026-114603]" in out
    assert "exempt until 2027-01-31 (#2179)" in out
    out, _, status = _run(_audit(_dep("opentelemetry-api", "1.45.1", _OTEL_114603)))
    assert status == 1
    assert "PREMISE BROKEN" in out


def test_s2g_otel_126360_is_suppressed_at_1_37_0_and_kept_once_fixed():
    out, _, status = _run(_audit(_dep("opentelemetry-api", "1.37.0", _OTEL_126360)))
    assert status == 0, out
    assert "opentelemetry-api 1.37.0 [CVE-2026-126360]" in out
    assert "exempt until 2027-01-31 (#2179)" in out
    out, _, status = _run(_audit(_dep("opentelemetry-api", "1.45.2", _OTEL_126360)))
    assert status == 1
    assert "PREMISE BROKEN" in out


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
        for p in sorted((_REPO / ".github").rglob("*"))
        if p.is_file() and "psf/black" in p.read_text(errors="replace").lower()
    ]
    assert not bad, f"{bad} reference psf/black: {_PREMISE_2120}"


_PREMISE_114134 = (
    "the CVE-2026-114134 exemption's premise no longer holds (HOS must never set "
    "black's required-version in [tool.black]) — remove the exemption (upgrade "
    "black, #1961) rather than editing this test"
)


def test_pr3b_pyproject_black_table_never_sets_required_version():
    tomllib = pytest.importorskip("tomllib", reason="tomllib needs Python 3.11+")
    with (_REPO / "pyproject.toml").open("rb") as fh:
        black_cfg = tomllib.load(fh).get("tool", {}).get("black", {})
    found = [k for k in black_cfg if k in ("required-version", "required_version")]
    assert not found, f"{found} set in pyproject.toml [tool.black]: {_PREMISE_114134}"


_PREMISE_59951 = (
    "the CVE-2026-59951 exemption's premise no longer holds (HOS must never serve "
    "MCP) — remove the exemption (upgrade mcp once semgrep unpins it, #2120) "
    "rather than editing this test"
)
_PREMISE_2194 = (
    "the CVE-2026-116684/5/6 and CVE-2026-115563 exemptions' premise no longer holds "
    "(HOS must never import mcp or run an MCP client or server) — remove the "
    "exemptions (upgrade "
    "mcp once semgrep unpins it, #2120) rather than editing this test"
)
_MCP_CLIENT = re.compile(
    r"\b(?:ClientSession|streamablehttp_client|sse_client|mcp\.client\.auth"
    r"|OAuthClientProvider|ClientCredentialsOAuthProvider|PrivateKeyJWTOAuthProvider"
    r"|RFC7523OAuthClientProvider)\b"
)
_MCP_LIST_2197 = load_module_from_path(
    "mcp_policy_logic_2197_exemptions", _REPO / "scripts" / "oversight" / "mcp_policy_logic.py"
).load_list(_REPO / "scripts" / "oversight" / "mcp_approved_list.json")


def _invocation_pattern(pkg: str, sub: str) -> re.Pattern[str]:
    # `(?:py)?` also catches the `pysemgrep` entry point. A static scan cannot see an
    # invocation assembled at runtime (e.g. from variables); that is a known limit.
    return re.compile(
        r"""\b(?:py)?%s\b(?:["',\s]+-{1,2}[\w=.-]+)*["',\s]+%s\b"""
        % (re.escape(pkg), re.escape(sub))
    )


# Built from the approved list (#2197): every `run` entry's forbidden subcommands.
_FORBIDDEN_INVOCATIONS = [
    _invocation_pattern(e.package, sub)
    for e in _MCP_LIST_2197.values()
    if e.mode == "run"
    for sub in e.forbidden_subcommands
]
# Modules HOS must never import: every install-only entry's modules.
_BANNED_MODULES = {
    mod for e in _MCP_LIST_2197.values() if e.mode == "install-only" for mod in e.modules
}


def _tracked_files(*paths: str) -> list[Path]:
    res = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return [_REPO / p for p in res.stdout.split("\0") if p and (_REPO / p).is_file()]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("semgrep mcp", True),
        ("pysemgrep mcp", True),
        ("pysemgrep --quiet mcp", True),
        ("semgrep --quiet mcp", True),
        ("semgrep --metrics=off -v mcp -t streamable-http", True),
        ('["semgrep", "mcp"]', True),
        ('["semgrep", "--quiet", "mcp"]', True),
        ("semgrep pins mcp==1.29.0", False),
        ("semgrep-mcp", False),
        ("semgrep's MCP subcommand", False),
        ("semgrep --config auto --json --quiet file.py", False),
    ],
)
def test_pr4b_serve_mcp_pattern_covers_flag_forms(text, expected):
    assert bool(_invocation_pattern("semgrep", "mcp").search(text)) is expected


def test_pr4_no_tracked_launcher_runs_semgrep_mcp():
    bad, unreadable = [], []
    files = _tracked_files("scripts", "bootstrap", "bin", ".github/workflows")
    assert files, f"scanned no files (path typo?): {_PREMISE_59951}"
    for path in files:
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            unreadable.append(str(path.relative_to(_REPO)))
            continue
        if any(p.search(text) for p in _FORBIDDEN_INVOCATIONS):
            bad.append(str(path.relative_to(_REPO)))
    assert not unreadable, f"cannot scan {unreadable} for `semgrep mcp`: {_PREMISE_59951}"
    assert not bad, f"{bad} run `semgrep mcp`: {_PREMISE_59951}"


def test_pr5_no_tracked_python_file_imports_mcp():
    bad, unparsed = [], []
    files = _tracked_files("*.py")
    assert files, f"scanned no files (path typo?): {_PREMISE_59951}"
    assert _BANNED_MODULES, f"no install-only modules on the approved list: {_PREMISE_59951}"
    for path in files:
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            unparsed.append(str(path.relative_to(_REPO)))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(n == mod or n.startswith(mod + ".") for n in names for mod in _BANNED_MODULES):
                bad.append(str(path.relative_to(_REPO)))
                break
    assert not unparsed, f"cannot parse {unparsed} to check for mcp imports: {_PREMISE_59951}"
    assert not bad, f"{bad} import mcp: {_PREMISE_59951}; also {_PREMISE_2194}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("async with ClientSession(read, write) as s:", True),
        ("from mcp.client.streamable_http import streamablehttp_client", True),
        ("async with sse_client(url) as streams:", True),
        ("MyClientSessionFactory", False),
        ("my_sse_client_helper", False),
        ("an MCP client talks to a server", False),
        ("import mcp.client.auth", True),
        ("auth = OAuthClientProvider(...)", True),
        ("auth = ClientCredentialsOAuthProvider(...)", True),
        ("auth = PrivateKeyJWTOAuthProvider(...)", True),
        ("auth = RFC7523OAuthClientProvider(...)", True),
        ("mcp.client.streamable_http", False),
        ("MyOAuthClientProviderFactory", False),
    ],
)
def test_pr5c_mcp_client_pattern_matches_the_client_entry_points_and_oauth_providers(
    text, expected
):
    assert bool(_MCP_CLIENT.search(text)) is expected


def test_pr5d_list_keeps_mcp_never_run():
    mcp = _MCP_LIST_2197.get("mcp")
    semgrep = _MCP_LIST_2197.get("semgrep")
    assert (
        mcp is not None and mcp.mode == "install-only" and "mcp" in mcp.modules
    ), f"{_PREMISE_59951}; also {_PREMISE_2194}"
    assert (
        semgrep is not None and "mcp" in semgrep.forbidden_subcommands
    ), f"{_PREMISE_59951}; also {_PREMISE_2194}"


def test_pr5b_no_tracked_file_uses_an_mcp_client():
    bad, unreadable, scanned = [], [], 0
    tracked = _tracked_files("scripts", "bootstrap", "bin", "tests", ".github/workflows")
    excluded = (Path(__file__).resolve(), _LOGIC_PATH)
    for ex in excluded:
        assert ex in tracked, f"excluded path {ex} is not tracked: {_PREMISE_2194}"
    for path in tracked:
        if path in excluded:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            unreadable.append(str(path.relative_to(_REPO)))
            continue
        scanned += 1
        if _MCP_CLIENT.search(text):
            bad.append(str(path.relative_to(_REPO)))
    assert scanned, f"scanned no files (path typo?): {_PREMISE_2194}"
    assert not unreadable, f"cannot scan {unreadable} for MCP client use: {_PREMISE_2194}"
    assert not bad, (
        f"{bad} use ClientSession/streamablehttp_client/sse_client or an MCP OAuth "
        f"client provider (mcp.client.auth): {_PREMISE_2194}"
    )


_PREMISE_114603 = (
    "the CVE-2026-114603 exemption's premise no longer holds (HOS must never "
    "import opentelemetry or parse inbound W3C tracestate headers) — remove the "
    "exemption (upgrade opentelemetry-api once semgrep unpins it, #2179) rather "
    "than editing this test"
)
# The only tracked .py files allowed to contain the word: change_classifier.py
# holds it inside a regex string, and the roster itself names the exempted package.
# Neither imports it (the AST walk in PR6 would flag any import).
_OTEL_NAME_ONLY = "scripts/oversight/change_classifier.py"
_OTEL_ROSTER = "scripts/oversight/security_scan_logic.py"
_OTEL_SERVER_USE = re.compile(
    r"propagate\s*\.\s*extract|TraceContextTextMapPropagator|TraceState\b"
    r"|opentelemetry\.instrumentation|opentelemetry-instrument\b"
)


def test_pr6_no_tracked_python_file_imports_opentelemetry():
    bad, unparsed = [], []
    for path in _tracked_files("*.py"):
        if path == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            unparsed.append(str(path.relative_to(_REPO)))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(n == "opentelemetry" or n.startswith("opentelemetry.") for n in names):
                bad.append(str(path.relative_to(_REPO)))
                break
    assert not unparsed, f"cannot parse {unparsed} to check for otel imports: {_PREMISE_114603}"
    assert not bad, f"{bad} import opentelemetry: {_PREMISE_114603}"


def test_pr6b_opentelemetry_name_exclusion_stays_narrow():
    mentions = [
        str(p.relative_to(_REPO))
        for p in _tracked_files("*.py")
        if p != Path(__file__).resolve() and "opentelemetry" in p.read_text(errors="replace")
    ]
    assert mentions == [_OTEL_NAME_ONLY, _OTEL_ROSTER], f"{mentions}: {_PREMISE_114603}"
    lines = [
        ln for ln in (_REPO / _OTEL_NAME_ONLY).read_text().splitlines() if "opentelemetry" in ln
    ]
    assert len(lines) == 1 and re.search(
        r"""\br?["'].*opentelemetry\|""", lines[0]
    ), f"{lines}: {_PREMISE_114603}"


def test_pr7_no_tracked_file_parses_tracestate_or_sets_up_otel_server():
    bad, unreadable = [], []
    for path in _tracked_files("scripts", "bootstrap", "bin", "tests", ".github/workflows"):
        if path == Path(__file__).resolve() or path == _REPO / _OTEL_ROSTER:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            unreadable.append(str(path.relative_to(_REPO)))
            continue
        if _OTEL_SERVER_USE.search(text):
            bad.append(str(path.relative_to(_REPO)))
    assert not unreadable, f"cannot scan {unreadable} for otel server use: {_PREMISE_114603}"
    assert (
        not bad
    ), f"{bad} use propagate.extract/TraceState/otel instrumentation: {_PREMISE_114603}"


_PREMISE_126360 = (
    "the CVE-2026-126360 exemption's premise no longer holds (no opentelemetry "
    "propagator may extract from a network or JSON carrier) — remove the exemption "
    "(upgrade opentelemetry-api once semgrep unpins it, #2179) rather than editing "
    "this test"
)


def test_pr8_installed_semgrep_extracts_only_from_its_own_environment():
    # Premise of #2352: the only propagate.extract call in the installed semgrep
    # builds its traceparent from SEMGREP_TRACE_PARENT_* env vars, so no
    # attacker-controlled carrier reaches TraceContextTextMapPropagator.extract().
    spec = importlib.util.find_spec("semgrep")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("semgrep is not installed in this environment")
    root = Path(next(iter(spec.submodule_search_locations)))
    call = re.compile(r"propagate\s*\.\s*extract\s*\(|TraceContextTextMapPropagator")
    hits = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(errors="replace")
        if call.search(text):
            hits.append(path.relative_to(root).as_posix())
    assert hits == ["telemetry.py"], f"{hits}: {_PREMISE_126360}"
    body = (root / "telemetry.py").read_text(errors="replace")
    assert len(re.findall(r"propagate\s*\.\s*extract\s*\(", body)) == 1, _PREMISE_126360
    assert re.search(
        r'carrier\s*=\s*\{\s*"traceparent"\s*:\s*f"00-\{trace_id\}-\{span_id\}-', body
    ), _PREMISE_126360
    assert "os.getenv(_SEMGREP_TRACE_PARENT_TRACE_ID)" in body, _PREMISE_126360


_PREMISE_132276 = (
    "the CVE-2026-132276 exemption's premise no longer holds (wcmatch must stay "
    "semgrep's path include/exclude matcher only, fed no multi-star pattern) — remove "
    "the exemption (upgrade wcmatch once semgrep unpins it, #2120) rather than "
    "editing this test"
)
_SEMGREP_RULES_DIR = "scripts/oversight/validators/semgrep_rules"
# A semgrep launch: the binary name followed by an option (a quoted list element or
# a shell word). Captures the rest of the line/list so --config/--include/--exclude
# can be read off it. `--version` probes are not scans.
_SEMGREP_LAUNCH = re.compile(r"""\b(?:py)?semgrep["']?[,\s]+["']?(-[^\n\]]*)""")
_SEMGREP_CONFIG = re.compile(r"""--config["']?[,=\s]+["']?([^"',\s\]]+)""")
_SEMGREP_FILTER = re.compile(r"--(?:include|exclude)\b")


def _star_count(pattern: str) -> int:
    return pattern.replace("**", "").count("*")


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("*.html", 1),
        ("**/*.html", 1),
        ("**/*.html/**", 1),
        ("**", 0),
        ("src/**/test_*.py", 1),
        ("*_*_*.csv", 3),
        ("**/*_*.csv/**", 2),
        ("plain.txt", 0),
    ],
)
def test_pr9d_star_count_ignores_globstars(pattern, expected):
    assert _star_count(pattern) == expected


@pytest.mark.parametrize(
    "text,config",
    [
        ('["semgrep", "--config", "p/django", "--json"] + files', "p/django"),
        ("semgrep --config p/django --json x.py", "p/django"),
        ("semgrep --config=auto x.py", "auto"),
        ('["semgrep", "--config", str(_RULESET), "--json"]', "str(_RULESET)"),
        ("pysemgrep --quiet --config r/all .", "r/all"),
    ],
)
def test_pr9e_semgrep_launch_pattern_reads_the_config(text, config):
    launch = _SEMGREP_LAUNCH.search(text)
    assert launch is not None
    found = _SEMGREP_CONFIG.search(launch.group(1))
    assert found is not None and found.group(1) == config


@pytest.mark.parametrize(
    "text,launches",
    [
        ("semgrep --version", True),
        ('["semgrep", "--version"]', True),
        ("semgrep's ERROR severity", False),
        ("semgrep-mcp", False),
        ("the semgrep ruleset", False),
    ],
)
def test_pr9f_semgrep_launch_pattern_needs_an_option(text, launches):
    assert bool(_SEMGREP_LAUNCH.search(text)) is launches


def test_pr9_no_tracked_python_file_imports_wcmatch():
    bad, unparsed = [], []
    for path in _tracked_files("*.py"):
        if path == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            unparsed.append(str(path.relative_to(_REPO)))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(n == "wcmatch" or n.startswith("wcmatch.") for n in names):
                bad.append(str(path.relative_to(_REPO)))
                break
    assert not unparsed, f"cannot parse {unparsed} to check for wcmatch imports: {_PREMISE_132276}"
    assert not bad, f"{bad} import wcmatch: {_PREMISE_132276}"


def test_pr9b_installed_semgrep_uses_wcmatch_only_for_one_globmatch():
    # Premise of #2425: semgrep's only wcmatch use is glob.globmatch() in
    # target_manager.py (rule paths.include/exclude matching); fnmatch is never used.
    spec = importlib.util.find_spec("semgrep")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("semgrep is not installed in this environment")
    root = Path(next(iter(spec.submodule_search_locations)))
    imp = re.compile(r"^\s*(?:from\s+wcmatch\b|import\s+wcmatch\b)", re.MULTILINE)
    hits = []
    for path in sorted(root.rglob("*.py")):
        if imp.search(path.read_text(errors="replace")):
            hits.append(path.relative_to(root).as_posix())
    assert hits == ["target_manager.py"], f"{hits}: {_PREMISE_132276}"
    body = (root / "target_manager.py").read_text(errors="replace")
    assert re.search(r"^\s*from\s+wcmatch\s+import\s+glob\s*$", body, re.MULTILINE), _PREMISE_132276
    assert len(re.findall(r"\bglob\.globmatch\s*\(", body)) == 1, _PREMISE_132276
    assert not re.search(r"\bfnmatch\b", body), _PREMISE_132276


def test_pr9c_semgrep_runs_only_tracked_or_django_rulesets_with_no_multi_star_paths():
    # Premise of #2425: no semgrep scan HOS launches can feed wcmatch a multi-star
    # pattern. A new semgrep call site, a new remote config, any --include/--exclude,
    # a tracked .semgrepignore or a multi-star path pattern in a tracked ruleset fails.
    import yaml

    launches, unreadable = [], []
    for path in _tracked_files("scripts", "bootstrap", "bin", ".github/workflows"):
        if path.suffix not in {".py", ".sh", ".yml", ".yaml", ""}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            unreadable.append(str(path.relative_to(_REPO)))
            continue
        for m in _SEMGREP_LAUNCH.finditer(text):
            rest = m.group(1)
            if rest.startswith("--version"):
                continue
            cfg = _SEMGREP_CONFIG.search(rest)
            launches.append(
                (path.relative_to(_REPO).as_posix(), cfg.group(1) if cfg else None, rest)
            )
    assert not unreadable, f"cannot scan {unreadable} for semgrep calls: {_PREMISE_132276}"
    sites = sorted((f, c) for f, c, _ in launches)
    assert sites == [
        ("scripts/oversight/validators/static_analysis.py", "p/django"),
        ("scripts/oversight/validators/static_analysis_js.py", "str(_RULESET)"),
    ], f"{sites}: {_PREMISE_132276}"
    assert not [f for f, _, rest in launches if _SEMGREP_FILTER.search(rest)], _PREMISE_132276
    js = (_REPO / "scripts/oversight/validators/static_analysis_js.py").read_text()
    assert re.search(
        r'^_RULESET\s*=.*"semgrep_rules"\s*/\s*"js_ts_security\.yaml"', js, re.MULTILINE
    ), _PREMISE_132276
    assert not _tracked_files(".semgrepignore", "**/.semgrepignore"), _PREMISE_132276
    rulesets = _tracked_files(_SEMGREP_RULES_DIR)
    assert rulesets, f"no tracked rulesets under {_SEMGREP_RULES_DIR}: {_PREMISE_132276}"
    bad = []
    for ruleset in rulesets:
        doc = yaml.safe_load(ruleset.read_text())
        for rule in doc.get("rules", []):
            paths = rule.get("paths") or {}
            for key in ("include", "exclude"):
                bad += [
                    (ruleset.name, rule.get("id"), p)
                    for p in paths.get(key, [])
                    if _star_count(str(p)) > 1
                ]
    assert not bad, f"multi-star path patterns {bad}: {_PREMISE_132276}"


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
    assert (
        "GATE PASS: no blocking dependency vulnerabilities (pip-audit binary overridden)"
        in res.stdout
    )


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
    expected = (
        "GATE PASS: no blocking dependency vulnerabilities "
        "(pip-audit binary overridden; pip-audit NOT CHECKED — see above)"
    )
    assert last == expected


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


def test_g6_bandit_absent_prints_no_pass_line_statically():
    # #1605 (TD §3 rebase item 4, §15.1.3): a missing bandit is an honest SKIP
    # followed by `exit 0` directly. Nothing names it in a pass line, so no
    # GATE PASS line is reachable from the branch. This tightens #1776's
    # architect A2: no pass line is reachable at all once the lane has moved.
    text = _BANDIT_GATE.read_text()
    skip_idx = text.index('echo "SKIP: bandit not in oversight venv')
    exit_idx = text.index("exit 0", skip_idx)
    assert exit_idx - skip_idx < 120
    assert "NOT_PERFORMED" not in text
    assert "GATE PASS: no blocking security issues (" not in text


def test_g7_security_scan_has_no_pip_audit_lane():
    # TC-S19: the lane moved to dependency_audit.sh, it was not lost (g1-g5 pin
    # it there). security_scan.sh must not carry any of its tokens.
    text = _BANDIT_GATE.read_text()
    for token in (
        "pip-audit",
        "PIP_AUDIT",
        "AUDIT_STATE",
        "AUDIT_STATUS",
        "NOT_PERFORMED",
        "security_scan_logic",
    ):
        assert token not in text, token


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


# --------------------------------------------------------------------------- #
# Direct in-process pins of the logic module (exact outputs, no subprocess).
# These exist so mutation testing of security_scan_logic.py can see the
# parser, validator, decision, renderer and CLI shim, which the shell-driven
# gate tests exercise only out of process.
# --------------------------------------------------------------------------- #
_UNATTR = "<unattributable>"
_HINT_TEXT = sl._HINT


def _mal(pkg: str, version: str, why: str, vid: str = _UNATTR) -> Any:
    return sl.Advisory(pkg, pkg, version, vid, (), (), True, why)


def _adv(
    pkg: str = "black",
    version: str = "24.10.0",
    vid: str = "X-1",
    fixes: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
    key: str | None = None,
) -> Any:
    return sl.Advisory(pkg, key or pkg, version, vid, fixes, aliases, False, None)


def _rule(**fields: object) -> Any:
    base = sl.Exemption("black", "X-1", "2.0", _EXPIRES, "r" * 50, 7)
    return base._replace(**fields)


# ---- _str_tuple / _shown / _malformed ----
@pytest.mark.parametrize(
    "value,expected",
    [
        (["a", "b"], ("a", "b")),
        ([], ()),
        (["a", 1], ()),
        ([1, "a"], ()),
        ("ab", ()),
        (("a",), ()),
        (None, ()),
    ],
)
def test_u_str_tuple_accepts_only_lists_of_strings(value, expected):
    assert sl._str_tuple(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("x", "x"), ("", "fb"), (3, "fb"), (None, "fb"), (["x"], "fb")],
)
def test_u_shown_keeps_only_non_empty_strings(value, expected):
    assert sl._shown(value, "fb") == expected


def test_u_malformed_builds_a_blocking_advisory_with_defaults():
    adv = sl._malformed("p", "1", "why")
    assert adv == sl.Advisory("p", "p", "1", "<unattributable>", (), (), True, "why")
    assert sl._malformed("p", "1", "why", "ID-9").advisory_id == "ID-9"


# ---- _incomplete_fields ----
def test_u_incomplete_fields_complete_entry_is_empty():
    assert sl._incomplete_fields({"name": "a", "version": "1", "vulns": []}) == []


def test_u_incomplete_fields_missing_everything():
    assert sl._incomplete_fields({}) == [
        "'name' missing",
        "'version' missing",
        "'vulns' missing",
    ]


def test_u_incomplete_fields_present_but_wrong():
    entry = {"name": "", "version": 3, "vulns": None}
    assert sl._incomplete_fields(entry) == [
        "'name' empty or not a string",
        "'version' empty or not a string",
        "'vulns' not a list",
    ]


def test_u_incomplete_fields_reports_only_the_bad_field():
    assert sl._incomplete_fields({"name": "a", "version": "1", "vulns": "x"}) == [
        "'vulns' not a list"
    ]
    assert sl._incomplete_fields({"name": "a", "version": None, "vulns": []}) == [
        "'version' empty or not a string"
    ]
    assert sl._incomplete_fields({"version": "1", "vulns": []}) == ["'name' missing"]


# ---- _parse_vulns ----
def test_u_parse_vulns_valid_entry_is_canonicalised_and_complete():
    got = sl._parse_vulns(
        "Foo_Bar", "1.0", [{"id": "V-1", "fix_versions": ["1.1", "1.2"], "aliases": ["CVE-1"]}]
    )
    assert got == [
        sl.Advisory("Foo_Bar", "foo-bar", "1.0", "V-1", ("1.1", "1.2"), ("CVE-1",), False, None)
    ]


def test_u_parse_vulns_empty_fix_versions_and_bad_aliases_are_lenient():
    got = sl._parse_vulns("p", "1", [{"id": "V", "fix_versions": [], "aliases": [1]}])
    assert got == [sl.Advisory("p", "p", "1", "V", (), (), False, None)]
    got = sl._parse_vulns("p", "1", [{"id": "V", "fix_versions": []}])
    assert got[0].aliases == ()


@pytest.mark.parametrize(
    "vulns,name,version",
    [
        (None, "p", "1"),
        ("x", "p", "1"),
        ({}, "p", "1"),
    ],
)
def test_u_parse_vulns_non_list_vulns_is_one_malformed(vulns, name, version):
    got = sl._parse_vulns(name, version, vulns)
    assert got == [_mal("p", "1", f"'vulns' is {type(vulns).__name__}, not a list")]


def test_u_parse_vulns_non_list_vulns_uses_fallback_names():
    assert sl._parse_vulns(None, "", None) == [
        _mal("<unknown>", "?", "'vulns' is NoneType, not a list")
    ]
    assert sl._parse_vulns("", 3, 5) == [_mal("<unknown>", "?", "'vulns' is int, not a list")]


@pytest.mark.parametrize(
    "name,version,shown_name,shown_version",
    [
        (None, "1", "<unknown>", "1"),
        ("", "1", "<unknown>", "1"),
        (3, "1", "<unknown>", "1"),
        ("p", None, "p", "?"),
        ("p", "", "p", "?"),
        ("p", 3, "p", "?"),
    ],
)
def test_u_parse_vulns_bad_name_or_version_marks_every_vuln(
    name, version, shown_name, shown_version
):
    vulns = [{"id": "A", "fix_versions": []}, {"id": "B", "fix_versions": []}, "junk"]
    why = "dependency name/version missing or not a string"
    assert sl._parse_vulns(name, version, vulns) == [_mal(shown_name, shown_version, why)] * 3
    assert sl._parse_vulns(name, version, []) == []


def test_u_parse_vulns_each_malformed_kind_has_its_own_reason_and_id():
    vulns = [
        "str",
        {"fix_versions": []},
        {"id": "", "fix_versions": []},
        {"id": 5, "fix_versions": []},
        {"id": "NOFIX"},
        {"id": "S", "fix_versions": "1.0"},
        {"id": "L", "fix_versions": ["1", 2]},
        {"id": "N", "fix_versions": None},
    ]
    assert sl._parse_vulns("p", "1", vulns) == [
        _mal("p", "1", "vuln entry is not a mapping", "<unknown>"),
        _mal("p", "1", "vuln entry has no usable 'id'", "<unknown>"),
        _mal("p", "1", "vuln entry has no usable 'id'", "<unknown>"),
        _mal("p", "1", "vuln entry has no usable 'id'", "<unknown>"),
        _mal("p", "1", "'fix_versions' is missing", "NOFIX"),
        _mal("p", "1", "'fix_versions' is str, not a list of strings", "S"),
        _mal("p", "1", "'fix_versions' is list, not a list of strings", "L"),
        _mal("p", "1", "'fix_versions' is NoneType, not a list of strings", "N"),
    ]


def test_u_parse_vulns_bad_entry_does_not_stop_later_good_entries():
    vulns = [7, {"id": "G", "fix_versions": ["2"]}]
    got = sl._parse_vulns("p", "1", vulns)
    assert [a.advisory_id for a in got] == ["<unknown>", "G"]
    assert [a.malformed for a in got] == [True, False]
    got = sl._parse_vulns(
        "p", "1", [{"id": "", "fix_versions": []}, {"id": "G", "fix_versions": []}]
    )
    assert [a.advisory_id for a in got] == ["<unknown>", "G"]
    got = sl._parse_vulns("p", "1", [{"id": "N"}, {"id": "G", "fix_versions": []}])
    assert [a.advisory_id for a in got] == ["N", "G"]
    got = sl._parse_vulns(
        "p", "1", [{"id": "N", "fix_versions": 1}, {"id": "G", "fix_versions": []}]
    )
    assert [a.advisory_id for a in got] == ["N", "G"]


# ---- _dedup ----
def test_u_dedup_unions_fix_versions_and_aliases_in_first_seen_order():
    a = _adv(fixes=("1", "2"), aliases=("A",))
    b = _adv(fixes=("2", "3"), aliases=("B", "A"))
    c = _adv(fixes=("4",), aliases=())
    got = sl._dedup([a, b, c])
    assert got == [_adv(fixes=("1", "2", "3", "4"), aliases=("A", "B"))]


def test_u_dedup_distinguishes_key_version_and_id_and_keeps_order():
    a = _adv()
    b = _adv(version="24.10.1")
    c = _adv(vid="X-2")
    d = _adv(pkg="other", key="other")
    assert sl._dedup([a, b, c, d, a]) == [a, b, c, d]


def test_u_dedup_dedups_on_canonical_key_not_display_name():
    a = _adv(pkg="Foo_Bar", key="foo-bar")
    b = _adv(pkg="foo.bar", key="foo-bar")
    got = sl._dedup([a, b])
    assert got == [a]


def test_u_dedup_never_merges_malformed_records_and_keeps_position():
    m = _mal("p", "1", "why")
    a = _adv()
    assert sl._dedup([m, a, m, a]) == [m, a, m]
    # a duplicate slot is merged into the FIRST slot, later slots untouched
    b = _adv(pkg="zed", key="zed")
    got = sl._dedup([a, b, _adv(fixes=("9",))])
    assert got == [_adv(fixes=("9",)), b]


# ---- parse_audit ----
@pytest.mark.parametrize(
    "doc,msg",
    [
        ([], "root is list, not a mapping"),
        ("x", "root is str, not a mapping"),
        (None, "root is NoneType, not a mapping"),
        ({}, "'dependencies' is missing or not a list"),
        ({"dependencies": "x"}, "'dependencies' is missing or not a list"),
        ({"dependencies": []}, "'dependencies' is empty — nothing was audited"),
    ],
)
def test_u_parse_audit_rejects_undecidable_roots_with_exact_message(doc, msg):
    with pytest.raises(sl.AuditParseError) as info:
        sl.parse_audit(doc)
    assert str(info.value) == msg


def test_u_parse_audit_clean_document_counts_dependencies():
    doc = sl.parse_audit(_audit(_dep("a", "1"), _dep("b", "2")))
    assert doc == sl.AuditDoc([], [], 0, 0, 2)


def test_u_parse_audit_counts_raw_distinct_and_dependencies():
    v = _vuln("V-1", ("2",))
    doc = sl.parse_audit(_audit(_dep("a", "1", v, v), _dep("a", "1", _vuln("V-2")), _dep("b", "1")))
    assert doc.raw_count == 3
    assert doc.distinct_count == 2
    assert doc.dependency_count == 3
    assert [a.advisory_id for a in doc.advisories] == ["V-1", "V-2"]
    assert doc.skipped == []


def test_u_parse_audit_non_mapping_entry_is_malformed_and_processing_continues():
    doc = sl.parse_audit(_audit("junk", 5, _dep("a", "1", _vuln("V-1"))))
    assert doc.advisories == [
        _mal("<unknown>", "?", "dependency entry is str, not a mapping"),
        _mal("<unknown>", "?", "dependency entry is int, not a mapping"),
        _adv("a", "1", "V-1"),
    ]
    assert (doc.raw_count, doc.distinct_count, doc.dependency_count) == (3, 3, 3)


def test_u_parse_audit_skip_entry_records_stringified_fields_and_is_not_an_advisory():
    doc = sl.parse_audit(
        _audit(
            {"name": "a", "version": "1", "skip_reason": "no index"},
            {"skip_reason": 5},
            {"name": "b", "skip_reason": ["x"]},
        )
    )
    assert doc.skipped == [
        sl.Skipped("a", "1", "no index"),
        sl.Skipped("?", "?", "5"),
        sl.Skipped("b", "?", "['x']"),
    ]
    assert doc.advisories == []
    assert doc.dependency_count == 3


def test_u_parse_audit_skip_entry_with_reported_vulns_still_parses_them():
    doc = sl.parse_audit(
        _audit({"name": "a", "version": "1", "skip_reason": "r", "vulns": [_vuln("V-1")]})
    )
    assert doc.skipped == [sl.Skipped("a", "1", "r")]
    assert doc.advisories == [_adv("a", "1", "V-1")]


def test_u_parse_audit_skip_entry_with_non_list_vulns_is_malformed():
    doc = sl.parse_audit(_audit({"name": "a", "version": "1", "skip_reason": "r", "vulns": "x"}))
    assert doc.advisories == [_mal("a", "1", "'vulns' is str, not a list")]


def test_u_parse_audit_incomplete_entry_is_one_malformed_record_and_not_parsed_further():
    entry = {"name": "p", "version": "", "vulns": [_vuln("V-1")]}
    doc = sl.parse_audit(_audit(entry))
    assert doc.advisories == [
        _mal("p", "?", "dependency entry is incomplete: 'version' empty or not a string")
    ]
    assert doc.raw_count == 1


def test_u_parse_audit_incomplete_entry_joins_all_reasons_with_comma_space():
    doc = sl.parse_audit(_audit({}))
    assert doc.advisories == [
        _mal(
            "<unknown>",
            "?",
            "dependency entry is incomplete: 'name' missing, 'version' missing, 'vulns' missing",
        )
    ]


def test_u_parse_audit_incomplete_entry_shows_name_and_version_when_usable():
    doc = sl.parse_audit(_audit({"name": "p", "version": "3", "vulns": None}))
    assert doc.advisories == [_mal("p", "3", "dependency entry is incomplete: 'vulns' not a list")]


def test_u_parse_audit_vulns_none_in_skip_entry_without_vulns_key_is_ignored():
    doc = sl.parse_audit(_audit({"name": "a", "version": "1", "skip_reason": "r"}))
    assert doc.advisories == []


# ---- validate_exemptions ----
def test_u_validate_accepts_a_good_record():
    assert sl.validate_exemptions([_rule()]) == []
    assert sl.validate_exemptions([_rule(fixed_in=None)]) == []


def test_u_validate_accepts_any_iterable():
    assert sl.validate_exemptions(iter([_rule()])) == []


def test_u_validate_non_canonical_package():
    assert sl.validate_exemptions([_rule(package="Foo_Bar")]) == [
        "Foo_Bar [X-1]: package 'Foo_Bar' is not PEP 503 canonical"
    ]


@pytest.mark.parametrize("pkg", ["", None, 5])
def test_u_validate_package_must_be_non_empty_string(pkg):
    assert sl.validate_exemptions([_rule(package=pkg)]) == [
        "record 0: package must be a non-empty string"
    ]


def test_u_validate_record_index_counts_from_zero_in_the_iteration():
    errs = sl.validate_exemptions([_rule(), _rule(package=""), _rule(advisory_id="a b")])
    assert errs == [
        "record 1: package must be a non-empty string",
        "black [a b]: advisory_id must be a non-empty string without whitespace",
    ]


@pytest.mark.parametrize("aid", ["", "a b", "a\tb", None, 3])
def test_u_validate_advisory_id_rules(aid):
    assert sl.validate_exemptions([_rule(advisory_id=aid)]) == [
        f"black [{aid}]: advisory_id must be a non-empty string without whitespace"
    ]


@pytest.mark.parametrize("fixed", ["bad version", "", 5])
def test_u_validate_fixed_in_must_be_pep440_or_none(fixed):
    assert sl.validate_exemptions([_rule(fixed_in=fixed)]) == [
        f"black [X-1]: fixed_in {fixed!r} is not a PEP 440 version"
    ]


@pytest.mark.parametrize(
    "expires,name",
    [
        ("2027-01-31", "str"),
        (None, "NoneType"),
        (datetime.datetime(2027, 1, 31), "datetime"),
        (20270131, "int"),
    ],
)
def test_u_validate_expires_must_be_a_plain_date(expires, name):
    assert sl.validate_exemptions([_rule(expires=expires)]) == [
        f"black [X-1]: expires must be a datetime.date, got {name}"
    ]


def test_u_validate_reason_length_boundary_is_forty_stripped_characters():
    msg = "black [X-1]: reason must be at least 40 characters"
    assert sl.validate_exemptions([_rule(reason="x" * 39)]) == [msg]
    assert sl.validate_exemptions([_rule(reason="x" * 40)]) == []
    assert sl.validate_exemptions([_rule(reason="   " + "x" * 39 + "   ")]) == [msg]
    assert sl.validate_exemptions([_rule(reason=None)]) == [msg]
    assert sl.validate_exemptions([_rule(reason=b"x" * 80)]) == [msg]


@pytest.mark.parametrize("issue", [0, -1, True, "5", None, 1.5])
def test_u_validate_tracking_issue_must_be_a_positive_int(issue):
    assert sl.validate_exemptions([_rule(tracking_issue=issue)]) == [
        "black [X-1]: tracking_issue must be a positive int"
    ]


def test_u_validate_tracking_issue_one_is_valid():
    assert sl.validate_exemptions([_rule(tracking_issue=1)]) == []


def test_u_validate_duplicate_pair_is_reported_on_the_second_only():
    errs = sl.validate_exemptions([_rule(), _rule()])
    assert errs == ["black [X-1]: duplicate (package, advisory_id)"]
    assert sl.validate_exemptions([_rule(), _rule(advisory_id="X-2")]) == []
    assert sl.validate_exemptions([_rule(), _rule(package="other")]) == []
    assert len(sl.validate_exemptions([_rule(), _rule(), _rule()])) == 2


def test_u_validate_reports_every_problem_of_one_record_in_order():
    bad = _rule(
        package="A_B", advisory_id="", fixed_in="x", expires=None, reason="s", tracking_issue=0
    )
    assert sl.validate_exemptions([bad]) == [
        "A_B []: package 'A_B' is not PEP 503 canonical",
        "A_B []: advisory_id must be a non-empty string without whitespace",
        "A_B []: fixed_in 'x' is not a PEP 440 version",
        "A_B []: expires must be a datetime.date, got NoneType",
        "A_B []: reason must be at least 40 characters",
        "A_B []: tracking_issue must be a positive int",
    ]


def test_u_validate_tolerates_objects_missing_every_attribute():
    class Bare:
        pass

    assert sl.validate_exemptions([Bare()]) == [
        "record 0: package must be a non-empty string",
        "record 0: advisory_id must be a non-empty string without whitespace",
        "record 0: expires must be a datetime.date, got NoneType",
        "record 0: reason must be at least 40 characters",
        "record 0: tracking_issue must be a positive int",
    ]


# ---- roster_mode ----
def test_u_roster_mode_source_repo_message(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "hos_install.sh").write_text("")
    assert sl.roster_mode(tmp_path) == sl.RosterMode(
        True, "HOS source repository: bootstrap/hos_install.sh present, no .hos-release"
    )


def test_u_roster_mode_release_marker_wins_over_installer(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "hos_install.sh").write_text("")
    (tmp_path / ".hos-release").write_text("v1")
    assert sl.roster_mode(tmp_path) == sl.RosterMode(False, "installed tree: .hos-release present")


def test_u_roster_mode_dangling_release_symlink_still_counts_as_present(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "hos_install.sh").write_text("")
    os.symlink(tmp_path / "nowhere", tmp_path / ".hos-release")
    assert sl.roster_mode(tmp_path).active is False
    assert sl.roster_mode(tmp_path).why == "installed tree: .hos-release present"


def test_u_roster_mode_missing_installer_is_inactive(tmp_path):
    assert sl.roster_mode(tmp_path) == sl.RosterMode(False, "bootstrap/hos_install.sh not found")


def test_u_roster_mode_installer_directory_is_not_a_file(tmp_path):
    (tmp_path / "bootstrap" / "hos_install.sh").mkdir(parents=True)
    assert sl.roster_mode(tmp_path) == sl.RosterMode(False, "bootstrap/hos_install.sh not found")


def test_u_roster_mode_probe_error_fails_closed_with_cause(tmp_path, monkeypatch):
    def boom(_p):
        raise PermissionError("denied")

    monkeypatch.setattr(sl.os.path, "lexists", boom)
    assert sl.roster_mode(tmp_path) == sl.RosterMode(
        False, "could not determine: PermissionError: denied"
    )


def test_u_roster_mode_is_file_probe_error_fails_closed(tmp_path, monkeypatch):
    def boom(_self):
        raise OSError("io")

    monkeypatch.setattr(Path, "is_file", boom)
    assert sl.roster_mode(tmp_path) == sl.RosterMode(False, "could not determine: OSError: io")


# ---- _kept_by_rule ----
def test_u_kept_by_rule_unparseable_version_comes_first():
    adv = _adv(version="not.a.version")
    expired = _rule(expires=datetime.date(2020, 1, 1))
    assert sl._kept_by_rule(adv, expired, _TODAY) == (
        "UNPARSEABLE VERSION",
        "UNPARSEABLE VERSION: installed version 'not.a.version' is not PEP 440, "
        "so it cannot be bounded by the exemption.",
    )


def test_u_kept_by_rule_installed_at_fixed_in_is_premise_broken():
    adv = _adv(version="2.0")
    assert sl._kept_by_rule(adv, _rule(), _TODAY) == (
        "PREMISE BROKEN",
        "PREMISE BROKEN: the exemption declares fixed_in=2.0, but pip-audit reports "
        "this advisory at installed 2.0 (>= 2.0). Re-check the advisory and update or "
        "remove the record (#7).",
    )


def test_u_kept_by_rule_version_equality_is_numeric_not_textual():
    assert sl._kept_by_rule(_adv(version="2.0.0"), _rule(), _TODAY)[0] == "PREMISE BROKEN"
    assert (
        sl._kept_by_rule(_adv(version="10.0"), _rule(fixed_in="9.0"), _TODAY)[0] == "PREMISE BROKEN"
    )
    assert sl._kept_by_rule(_adv(version="1.9.9"), _rule(), _TODAY) is None
    assert sl._kept_by_rule(_adv(version="2.0.1"), _rule(), _TODAY)[0] == "PREMISE BROKEN"


def test_u_kept_by_rule_premise_broken_outranks_expiry():
    adv = _adv(version="3.0")
    rule = _rule(expires=datetime.date(2020, 1, 1))
    assert sl._kept_by_rule(adv, rule, _TODAY)[0] == "PREMISE BROKEN"


def test_u_kept_by_rule_no_fix_key_goes_inert_when_a_fix_is_reported():
    rule = _rule(fixed_in=None)
    adv = _adv(version="1.0", fixes=("1.1", "1.2"))
    assert sl._kept_by_rule(adv, rule, _TODAY) == (
        "FIX NOW AVAILABLE",
        "FIX NOW AVAILABLE: the exemption was granted because no fix existed, but "
        "pip-audit now reports fix 1.1, 1.2. Raise the floor in "
        "scripts/oversight/requirements.txt and remove the record (#7).",
    )
    assert sl._kept_by_rule(_adv(version="1.0"), rule, _TODAY) is None


def test_u_kept_by_rule_fix_versions_do_not_matter_when_fixed_in_is_set():
    assert sl._kept_by_rule(_adv(version="1.0", fixes=("9",)), _rule(), _TODAY) is None


def test_u_kept_by_rule_fix_now_available_outranks_expiry():
    rule = _rule(fixed_in=None, expires=datetime.date(2020, 1, 1))
    adv = _adv(version="1.0", fixes=("1.1",))
    assert sl._kept_by_rule(adv, rule, _TODAY)[0] == "FIX NOW AVAILABLE"


def test_u_kept_by_rule_expiry_boundary_and_message():
    rule = _rule(expires=datetime.date(2026, 10, 6), reason="because " + "r" * 40)
    adv = _adv(version="1.0")
    assert sl._kept_by_rule(adv, rule, datetime.date(2026, 10, 6)) is None
    assert sl._kept_by_rule(adv, rule, datetime.date(2026, 10, 5)) is None
    got = sl._kept_by_rule(adv, rule, datetime.date(2026, 10, 7))
    assert got == (
        "EXEMPTION EXPIRED",
        "EXEMPTION EXPIRED 2026-10-06 (today 2026-10-07) — #7. It no longer applies; "
        "renew only with a fresh human decision, or fix the dependency. "
        "Original justification: because " + "r" * 40,
    )


# ---- partition ----
def test_u_partition_malformed_is_kept_with_unattributable_note_and_never_matches():
    m = _mal("black", "24.10.0", "why it broke", "X-1")
    dec = sl.partition([m], (_rule(),), _TODAY)
    assert dec.kept == [
        sl.Kept(m, "UNATTRIBUTABLE: why it broke — a malformed audit record is never exempted.")
    ]
    assert dec.suppressed == []
    assert dec.roster == [(_rule(), "NOT NEEDED (not reported in this environment)")]


def test_u_partition_unmatched_advisory_is_kept_without_a_note():
    a = _adv(vid="OTHER")
    dec = sl.partition([a], (_rule(),), _TODAY)
    assert dec.kept == [sl.Kept(a, None)]
    assert dec.suppressed == []


def test_u_partition_requires_both_package_and_id_to_match():
    other_pkg = _adv(pkg="other", key="other", vid="X-1")
    other_id = _adv(vid="X-2")
    dec = sl.partition([other_pkg, other_id], (_rule(),), _TODAY)
    assert dec.kept == [sl.Kept(other_pkg, None), sl.Kept(other_id, None)]


def test_u_partition_matches_on_canonical_key_not_display_name():
    a = _adv(pkg="Black", key="black", version="1.0")
    dec = sl.partition([a], (_rule(),), _TODAY)
    assert dec.suppressed == [sl.Suppressed(a, _rule())]
    b = _adv(pkg="black", key="Black")
    assert sl.partition([b], (_rule(),), _TODAY).kept == [sl.Kept(b, None)]


def test_u_partition_suppresses_applying_rule_and_marks_it_applied():
    a = _adv(version="1.0")
    rule = _rule()
    dec = sl.partition([a], (rule,), _TODAY)
    assert dec.kept == []
    assert dec.suppressed == [sl.Suppressed(a, rule)]
    assert dec.roster == [(rule, "APPLIED")]


def test_u_partition_non_applying_rule_keeps_with_verdict_note_and_status():
    a = _adv(version="2.0")
    rule = _rule()
    dec = sl.partition([a], (rule,), _TODAY)
    note = sl._kept_by_rule(a, rule, _TODAY)[1]
    assert dec.kept == [sl.Kept(a, note)]
    assert dec.suppressed == []
    assert dec.roster == [(rule, "NOT APPLIED: PREMISE BROKEN")]


def test_u_partition_first_verdict_wins_the_status_and_applied_outranks_it():
    rule = _rule()
    bad_version = _adv(version="zzz")
    broken = _adv(version="3.0")
    fine = _adv(version="1.0")
    dec = sl.partition([bad_version, broken], (rule,), _TODAY)
    assert dec.roster == [(rule, "NOT APPLIED: UNPARSEABLE VERSION")]
    dec = sl.partition([broken, bad_version], (rule,), _TODAY)
    assert dec.roster == [(rule, "NOT APPLIED: PREMISE BROKEN")]
    dec = sl.partition([broken, fine], (rule,), _TODAY)
    assert dec.roster == [(rule, "APPLIED")]
    assert len(dec.kept) == 1 and len(dec.suppressed) == 1


def test_u_partition_uses_the_first_matching_rule_and_statuses_are_per_rule():
    first = _rule(reason="first " + "r" * 50)
    second = _rule(reason="second " + "r" * 50)
    unrelated = _rule(advisory_id="X-9")
    a = _adv(version="1.0")
    dec = sl.partition([a], (unrelated, first, second), _TODAY)
    assert dec.suppressed == [sl.Suppressed(a, first)]
    assert [s for _r, s in dec.roster] == [
        "NOT NEEDED (not reported in this environment)",
        "APPLIED",
        "NOT NEEDED (not reported in this environment)",
    ]
    assert [r for r, _s in dec.roster] == [unrelated, first, second]


def test_u_partition_empty_inputs():
    assert sl.partition([], (), _TODAY) == sl.Decision([], [], [])


def test_u_partition_expiry_uses_the_supplied_today():
    a = _adv(version="1.0")
    rule = _rule(expires=datetime.date(2026, 10, 6))
    assert sl.partition([a], (rule,), datetime.date(2026, 10, 6)).suppressed
    dec = sl.partition([a], (rule,), datetime.date(2026, 10, 7))
    assert dec.suppressed == []
    assert dec.roster[0][1] == "NOT APPLIED: EXEMPTION EXPIRED"


# ---- _fixes ----
def test_u_fixes_joins_with_comma_space_or_says_none():
    assert sl._fixes(_adv(fixes=("1", "2"))) == "1, 2"
    assert sl._fixes(_adv(fixes=("1",))) == "1"
    assert sl._fixes(_adv()) == "none"


# ---- render ----
def _doc(skipped=(), raw=0, distinct=0, deps=0):
    return sl.AuditDoc([], list(skipped), raw, distinct, deps)


def test_u_render_active_lists_every_roster_record_with_status():
    rules = (_rule(), _rule(advisory_id="X-2", fixed_in=None, tracking_issue=8))
    dec = sl.Decision([], [], [(rules[0], "APPLIED"), (rules[1], "NOT NEEDED")])
    lines, rc = sl.render(_doc(deps=3), dec, _ACTIVE, rules, _TODAY)
    assert rc == 0
    assert lines == [
        "  Exemption roster: ACTIVE (HOS source repository: test) — 2 record(s), #1776",
        "    black [X-1] fixed_in 2.0 — expires 2027-01-31 — APPLIED — #7",
        "    black [X-2] fixed_in none published — expires 2027-01-31 — NOT NEEDED — #8",
        "OK: no dependency advisories outside the exemption roster (0 suppressed; "
        "0 distinct advisory(ies) from 0 raw record(s); 3 dependencies read)",
    ]


def test_u_render_inactive_says_so_and_prints_no_roster_lines():
    rules = (_rule(expires=_TODAY),)
    dec = sl.Decision([], [], [(rules[0], "APPLIED")])
    lines, rc = sl.render(_doc(deps=1), dec, _INACTIVE, rules, _TODAY)
    assert rc == 0
    assert lines[0] == (
        "  Exemption roster: INACTIVE (installed tree: .hos-release present) — every "
        "advisory is enforced; a consumer-owned roster is not yet supported (#1776 H2)"
    )
    assert len(lines) == 2 and lines[1].startswith("OK: ")


def test_u_render_expiring_soon_window_is_zero_through_fourteen_days_inclusive():
    rules = (_rule(expires=datetime.date(2026, 10, 20)),)
    dec = sl.Decision([], [], [(rules[0], "APPLIED")])

    def warns(day: int) -> list[str]:
        lines, _ = sl.render(_doc(), dec, _ACTIVE, rules, datetime.date(2026, 10, day))
        return [ln for ln in lines if "EXPIRING SOON" in ln]

    assert warns(6) == [
        "  EXPIRING SOON: black [X-1] exemption expires 2026-10-20 (14 day(s)) — renew "
        "only with a fresh human decision, or fix the dependency (#7)"
    ]
    assert warns(7) != [] and warns(19) != []
    assert warns(20) == [
        "  EXPIRING SOON: black [X-1] exemption expires 2026-10-20 (0 day(s)) — renew "
        "only with a fresh human decision, or fix the dependency (#7)"
    ]
    assert warns(5) == []  # 15 days out
    assert warns(21) == []  # already expired


def test_u_render_expiring_soon_is_checked_for_every_rule_not_just_the_first():
    far = _rule(advisory_id="X-0")
    near = _rule(expires=datetime.date(2026, 10, 8))
    dec = sl.Decision([], [], [(far, "APPLIED"), (near, "APPLIED")])
    lines, _ = sl.render(_doc(), dec, _ACTIVE, (far, near), _TODAY)
    assert [ln for ln in lines if "EXPIRING SOON" in ln] == [
        "  EXPIRING SOON: black [X-1] exemption expires 2026-10-08 (2 day(s)) — renew "
        "only with a fresh human decision, or fix the dependency (#7)"
    ]


def test_u_render_not_checked_line_and_ok_suffix():
    doc = _doc(skipped=[sl.Skipped("a", "1", "no index")], raw=5, distinct=3, deps=7)
    lines, rc = sl.render(doc, sl.Decision([], [], []), _INACTIVE, (), _TODAY)
    assert rc == 0
    assert lines[1] == "  NOT CHECKED: a 1 was not audited by pip-audit (no index)"
    assert lines[2] == (
        "OK: no dependency advisories outside the exemption roster (0 suppressed; "
        "3 distinct advisory(ies) from 5 raw record(s); 7 dependencies read, 1 NOT CHECKED)"
    )


def test_u_render_ok_line_counts_suppressed_and_lists_each_with_reason():
    a = _adv(version="1.0", fixes=("2.0", "2.1"))
    b = _adv(version="1.0", vid="X-3")
    r1, r3 = _rule(reason="why one " + "r" * 40), _rule(advisory_id="X-3", tracking_issue=9)
    dec = sl.Decision([], [sl.Suppressed(a, r1), sl.Suppressed(b, r3)], [])
    lines, rc = sl.render(_doc(raw=2, distinct=2, deps=2), dec, _INACTIVE, (), _TODAY)
    assert rc == 0
    assert lines[1:] == [
        "  2 advisory(ies) suppressed by a time-boxed exemption:",
        "    black 1.0 [X-1] fix: 2.0, 2.1 — exempt until 2027-01-31 (#7): why one " + "r" * 40,
        "    black 1.0 [X-3] fix: none — exempt until 2027-01-31 (#9): " + "r" * 50,
        "OK: no dependency advisories outside the exemption roster (2 suppressed; "
        "2 distinct advisory(ies) from 2 raw record(s); 2 dependencies read)",
    ]


def test_u_render_kept_advisories_fail_with_notes_and_hint():
    a = _adv(version="1.0", fixes=("2",))
    b = _adv(pkg="zed", key="zed", version="3", vid="Z-1")
    dec = sl.Decision([sl.Kept(a, "NOTE A"), sl.Kept(b, None)], [], [])
    lines, rc = sl.render(_doc(skipped=[sl.Skipped("s", "0", "r")]), dec, _INACTIVE, (), _TODAY)
    assert rc == 1
    assert lines[2:] == [
        "GATE FAIL: 2 dependency advisory(ies) not covered by an exemption:",
        "  black 1.0 [X-1] fix: 2",
        "    NOTE A",
        "  zed 3 [Z-1] fix: none",
        _HINT_TEXT,
    ]
    assert not any(ln.startswith("OK:") for ln in lines)


def test_u_render_suppressed_and_kept_together_still_fail():
    a = _adv(version="1.0")
    dec = sl.Decision([sl.Kept(_adv(vid="N"), None)], [sl.Suppressed(a, _rule())], [])
    lines, rc = sl.render(_doc(), dec, _INACTIVE, (), _TODAY)
    assert rc == 1
    assert lines[1].startswith("  1 advisory(ies) suppressed")
    assert lines[3].startswith("GATE FAIL: 1 dependency")


# ---- run_filter ----
_REFUSAL = "refusing to report a pass on an audit that cannot be read"


def test_u_run_filter_bad_json_is_exit_2_with_the_decoder_message():
    out, err, rc = sl.run_filter("", (), _ACTIVE, _TODAY)
    assert (out, rc) == ([], 2)
    assert err == [
        "GATE FAIL: could not parse pip-audit output (JSONDecodeError: Expecting value: "
        f"line 1 column 1 (char 0)) — {_REFUSAL}"
    ]


def test_u_run_filter_undecidable_audit_is_exit_2_with_the_parse_message():
    out, err, rc = sl.run_filter("[]", (), _ACTIVE, _TODAY)
    assert (out, rc) == ([], 2)
    assert err == [
        "GATE FAIL: could not parse pip-audit output (AuditParseError: root is list, "
        f"not a mapping) — {_REFUSAL}"
    ]
    assert sl.run_filter('{"dependencies": []}', (), _INACTIVE, _TODAY)[2] == 2


def test_u_run_filter_invalid_active_roster_is_exit_2_one_line_per_error():
    bad = (_rule(package="A_B", tracking_issue=0),)
    text = json.dumps(_audit(_dep("a", "1")))
    out, err, rc = sl.run_filter(text, bad, _ACTIVE, _TODAY)
    assert (out, rc) == ([], 2)
    assert err == [
        "GATE FAIL: exemption roster invalid — A_B [X-1]: package 'A_B' is not PEP 503 canonical",
        "GATE FAIL: exemption roster invalid — A_B [X-1]: tracking_issue must be a positive int",
    ]


def test_u_run_filter_inactive_mode_ignores_an_invalid_roster_and_any_exemption():
    bad = (_rule(package="A_B", tracking_issue=0),)
    text = json.dumps(_audit(_dep("black", "1.0", _vuln("X-1", ("2.0",)))))
    out, err, rc = sl.run_filter(text, bad, _INACTIVE, _TODAY)
    assert err == [] and rc == 1
    assert "  black 1.0 [X-1] fix: 2.0" in out
    good = (_rule(),)
    out, err, rc = sl.run_filter(text, good, _INACTIVE, _TODAY)
    assert rc == 1 and not any("suppressed" in ln for ln in out)


def test_u_run_filter_active_mode_applies_the_roster_and_uses_today():
    text = json.dumps(_audit(_dep("black", "1.0", _vuln("X-1", ("2.0",))), _dep("c", "1")))
    out, err, rc = sl.run_filter(text, (_rule(),), _ACTIVE, _TODAY)
    assert (err, rc) == ([], 0)
    assert out[0] == "  Exemption roster: ACTIVE (HOS source repository: test) — 1 record(s), #1776"
    assert out[-1] == (
        "OK: no dependency advisories outside the exemption roster (1 suppressed; "
        "1 distinct advisory(ies) from 1 raw record(s); 2 dependencies read)"
    )
    out, err, rc = sl.run_filter(text, (_rule(),), _ACTIVE, datetime.date(2027, 2, 1))
    assert (err, rc) == ([], 1)
    assert any(ln.startswith("GATE FAIL: 1 dependency") for ln in out)


# ---- main (CLI shim) ----
_REAL_DATE = datetime.date
_REAL_DT = datetime.datetime
_REAL_TZ = datetime.timezone


class _FakeDatetimeModule:
    """Stands in for the `datetime` module inside the logic module (frozen UTC clock)."""

    seen: list = []

    class datetime(_REAL_DT):  # noqa: N801 - mirrors the module attribute
        @classmethod
        def now(cls, tz=None):
            _FakeDatetimeModule.seen.append(tz)
            return _REAL_DT(2026, 10, 6, 23, 59, tzinfo=tz)

    date = _REAL_DATE
    timezone = _REAL_TZ


def _stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr(sl.sys, "stdin", io.StringIO(text))


def test_u_main_requires_the_filter_subcommand(capsys):
    with pytest.raises(SystemExit) as info:
        sl.main([])
    assert info.value.code == 2
    assert "required: command" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        sl.main(["bogus"])
    assert info.value.code == 2


def test_u_main_help_describes_the_filter_command(capsys):
    with pytest.raises(SystemExit) as info:
        sl.main(["-h"])
    assert info.value.code == 0
    text = capsys.readouterr().out
    assert "pip-audit advisory exemption filter (#1776)" in text
    assert "read pip-audit JSON on stdin, print the verdict" in text
    assert "filter" in text


def test_u_main_import_failure_is_exit_2_before_reading_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sl, "_IMPORT_ERROR", "ImportError: no packaging")
    _stdin(monkeypatch, "{}")
    assert sl.main(["filter"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err == (
        "GATE FAIL: security_scan_logic could not import 'packaging' "
        "(ImportError: no packaging) — nothing was decided\n"
    )


def test_u_main_passes_repo_root_rules_clock_and_stdin_to_the_filter(monkeypatch, capsys):
    calls: dict[str, Any] = {}
    root_mode = sl.RosterMode(True, "m")

    def fake_mode(root):
        calls["root"] = root
        return root_mode

    def fake_filter(text, rules, mode, today):
        calls["args"] = (text, rules, mode, today)
        return ["out1", "out2"], ["err1"], 1

    _FakeDatetimeModule.seen = []
    monkeypatch.setattr(sl, "datetime", _FakeDatetimeModule)
    monkeypatch.setattr(sl, "roster_mode", fake_mode)
    monkeypatch.setattr(sl, "run_filter", fake_filter)
    _stdin(monkeypatch, "THE-STDIN")
    assert sl.main(["filter"]) == 1
    cap = capsys.readouterr()
    assert cap.out == "out1\nout2\n"
    assert cap.err == "err1\n"
    root = calls["root"]
    assert root == Path(sl.__file__).resolve().parents[2]
    assert (root / "scripts" / "oversight" / "security_scan_logic.py").is_file()
    text, rules, mode, today = calls["args"]
    assert text == "THE-STDIN"
    assert rules is sl.SUPPRESSIONS
    assert mode is root_mode
    assert today == datetime.date(2026, 10, 6)
    assert type(today) is datetime.date
    assert _FakeDatetimeModule.seen == [datetime.timezone.utc]


def test_u_main_inactive_mode_hands_an_empty_roster_to_the_filter(monkeypatch, capsys):
    seen: dict[str, Any] = {}

    def fake_filter(text, rules, mode, today):
        seen["rules"] = rules
        return [], [], 0

    monkeypatch.setattr(sl, "roster_mode", lambda _root: _INACTIVE)
    monkeypatch.setattr(sl, "run_filter", fake_filter)
    _stdin(monkeypatch, "")
    assert sl.main(["filter"]) == 0
    assert seen["rules"] == ()
    cap = capsys.readouterr()
    assert (cap.out, cap.err) == ("", "")


def test_u_main_a_crash_is_exit_2_with_the_cause_and_nothing_on_stdout(monkeypatch, capsys):
    def boom(*_a):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sl, "roster_mode", lambda _root: _ACTIVE)
    monkeypatch.setattr(sl, "run_filter", boom)
    _stdin(monkeypatch, "{}")
    assert sl.main(["filter"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err == (
        "GATE FAIL: security_scan_logic crashed (RuntimeError: kaboom) — nothing was decided\n"
    )


def test_u_main_stdin_read_failure_is_exit_2(monkeypatch, capsys):
    class Broken:
        def read(self):
            raise OSError("closed")

    monkeypatch.setattr(sl, "roster_mode", lambda _root: _INACTIVE)
    monkeypatch.setattr(sl.sys, "stdin", Broken())
    assert sl.main(["filter"]) == 2
    assert "crashed (OSError: closed)" in capsys.readouterr().err


def test_u_main_active_roster_suppresses_a_shipped_record_end_to_end(monkeypatch, capsys):
    monkeypatch.setattr(sl, "datetime", _FakeDatetimeModule)
    monkeypatch.setattr(sl, "roster_mode", lambda _root: _ACTIVE)
    doc = _audit(_dep("black", "24.10.0", _vuln("PYSEC-2026-2120", ("26.3.0",))))
    _stdin(monkeypatch, json.dumps(doc))
    assert sl.main(["filter"]) == 0
    cap = capsys.readouterr()
    lines = cap.out.splitlines()
    assert cap.err == ""
    assert lines[0] == (
        f"  Exemption roster: ACTIVE (HOS source repository: test) — {len(sl.SUPPRESSIONS)} record(s), #1776"
    )
    assert lines[-1] == (
        "OK: no dependency advisories outside the exemption roster (1 suppressed; "
        "1 distinct advisory(ies) from 1 raw record(s); 1 dependencies read)"
    )


def test_u_main_unexempted_advisory_is_exit_1_on_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sl, "roster_mode", lambda _root: _ACTIVE)
    _stdin(monkeypatch, json.dumps(_audit(_dep("newpkg", "1.0", _vuln("N-1", ("1.1",))))))
    assert sl.main(["filter"]) == 1
    cap = capsys.readouterr()
    assert "  newpkg 1.0 [N-1] fix: 1.1" in cap.out.splitlines()
    assert cap.err == ""


def test_u_main_unreadable_audit_is_exit_2_on_stderr_only(monkeypatch, capsys):
    monkeypatch.setattr(sl, "roster_mode", lambda _root: _ACTIVE)
    _stdin(monkeypatch, "not json")
    assert sl.main(["filter"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.startswith("GATE FAIL: could not parse pip-audit output (JSONDecodeError")
