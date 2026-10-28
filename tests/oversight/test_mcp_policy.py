"""Tests for the MCP approved list and its checker (#2197).

Unit tests use synthetic Dist tuples or fake .dist-info dirs under tmp_path;
they never read the real venv.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

from tests.conftest import load_module_from_path

_REPO = Path(__file__).resolve().parents[2]
_OVERSIGHT = _REPO / "scripts" / "oversight"
_LOGIC = _OVERSIGHT / "mcp_policy_logic.py"
_LIST = _OVERSIGHT / "mcp_approved_list.json"
_GATE = _OVERSIGHT / "gates" / "mcp_policy.sh"
_REQ = _OVERSIGHT / "requirements.txt"

m = load_module_from_path("mcp_policy_logic_2197", _LOGIC)
Dist: Any = m.Dist

_GOOD = json.loads(_LIST.read_text())


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def _list_file(tmp_path: Path, doc: object) -> Path:
    return _write(tmp_path, "list.json", doc if isinstance(doc, str) else json.dumps(doc))


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(_LOGIC), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO),
    )


def _approved(semgrep: str = "1.179.0", mcp: str = "1.29.0") -> dict:
    doc = copy.deepcopy(_GOOD)
    doc["entries"][0]["version"] = semgrep
    doc["entries"][1]["version"] = mcp
    return doc


def _approved_obj(**kw: str) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        return m.load_list(_list_file(Path(d), _approved(**kw)))


def _roots(*lines: str) -> list:
    return [(Requirement(ln), "req.txt:1") for ln in lines]


# --- the real list ------------------------------------------------------


def test_real_list_loads_with_ruling_entries():
    entries = m.load_list(_LIST)
    assert sorted(entries) == ["mcp", "semgrep"]
    assert entries["semgrep"].mode == "run"
    assert list(entries["semgrep"].forbidden_subcommands) == ["mcp"]
    assert entries["mcp"].mode == "install-only"
    assert "mcp" in entries["mcp"].modules
    assert all(e.approved_pr > 0 for e in entries.values())


def test_real_requirements_pin_listed_versions():
    entries = m.load_list(_LIST)
    assert m.check_requirements(m.discover_requirement_files(), entries) == []
    lines = [ln.strip() for ln in _REQ.read_text().splitlines()]
    assert f"semgrep=={entries['semgrep'].version}" in lines
    assert f"mcp=={entries['mcp'].version}" in lines


# --- list schema --------------------------------------------------------


def _mut(fn):
    doc = copy.deepcopy(_GOOD)
    fn(doc)
    return doc


_BAD_LISTS = {
    "invalid-json": "{not json",
    "top-not-object": [],
    "extra-top-key": _mut(lambda d: d.update(extra=1)),
    "missing-top-key": {"schema_version": 1},
    "schema-version-2": _mut(lambda d: d.update(schema_version=2)),
    "entries-empty": _mut(lambda d: d.update(entries=[])),
    "entries-not-list": _mut(lambda d: d.update(entries={})),
    "missing-key": _mut(lambda d: d["entries"][0].pop("reason")),
    "unknown-key": _mut(lambda d: d["entries"][0].update(foo=1)),
    "non-canonical-name": _mut(lambda d: d["entries"][0].update(package="Semgrep")),
    "bad-version": _mut(lambda d: d["entries"][0].update(version="not-a-version")),
    "bad-mode": _mut(lambda d: d["entries"][0].update(mode="exec")),
    "blank-reason": _mut(lambda d: d["entries"][0].update(reason="  ")),
    "pr-zero": _mut(lambda d: d["entries"][0].update(approved_pr=0)),
    "pr-bool": _mut(lambda d: d["entries"][0].update(approved_pr=True)),
    "install-only-no-modules": _mut(lambda d: d["entries"][1].pop("modules")),
    "install-only-empty-modules": _mut(lambda d: d["entries"][1].update(modules=[])),
    "install-only-bad-module": _mut(lambda d: d["entries"][1].update(modules=["1bad"])),
    "run-with-modules": _mut(lambda d: d["entries"][0].update(modules=["x"])),
    "bad-forbidden-subcommand": _mut(
        lambda d: d["entries"][0].update(forbidden_subcommands=["Bad Cmd"])
    ),
    "duplicate-package": _mut(lambda d: d["entries"].append(copy.deepcopy(d["entries"][0]))),
}


@pytest.mark.parametrize("case", sorted(_BAD_LISTS))
def test_list_schema_rejects(case, tmp_path):
    path = _list_file(tmp_path, _BAD_LISTS[case])
    with pytest.raises(m.ListError):
        m.load_list(path)
    res = _cli("--list", str(path), "--requirements", str(_REQ))
    assert res.returncode == 2, res.stdout + res.stderr


def test_missing_list_file_is_exit_2(tmp_path):
    res = _cli("--list", str(tmp_path / "nope.json"), "--requirements", str(_REQ))
    assert res.returncode == 2


# --- detection ----------------------------------------------------------


@pytest.mark.parametrize(
    "name,requires,eps,expected",
    [
        ("mcp", [], [], True),
        ("mcp-server-git", [], [], True),
        ("semgrep", ["mcp==1.29.0"], [], True),
        ("foo", ['mcp; extra == "ai"'], [], True),
        ("foo", [], [("console_scripts", "run", "mcp.server:run")], True),
        ("foo", [], [("console_scripts", "my-mcp", "foo:main")], True),
        ("requests", ["urllib3>=1"], [], False),
        ("fastmcp", ["click"], [], False),
        ("smcp", [], [], False),
        ("foo", ["mcpclient>=1"], [], False),
    ],
)
def test_is_mcp_dist(name, requires, eps, expected):
    assert m.is_mcp_dist(name, requires, eps) is expected


# --- static check -------------------------------------------------------


def _static(tmp_path: Path, *lines: str, doc: object | None = None) -> subprocess.CompletedProcess:
    req = _write(tmp_path, "requirements.txt", "\n".join(lines) + "\n")
    lst = _list_file(tmp_path, doc or _GOOD)
    return _cli("--list", str(lst), "--requirements", str(req))


def test_static_clean_pins_pass(tmp_path):
    assert _static(tmp_path, "semgrep==1.179.0  # c", "mcp==1.29.0", "requests>=2").returncode == 0


def test_static_unlisted_mcp_requirement_fails(tmp_path):
    res = _static(tmp_path, "semgrep==1.179.0", "mcp==1.29.0", "mcp-server-git==1.0")
    assert res.returncode == 1
    assert "unlisted MCP package" in res.stdout


@pytest.mark.parametrize(
    "spec", ["semgrep>=1.50", "semgrep", "semgrep==1.*", "semgrep===1.179.0", "semgrep==1.179.0,<2"]
)
def test_static_floating_listed_pin_fails(tmp_path, spec):
    assert _static(tmp_path, spec).returncode == 1


def test_static_semgrep_bump_fails_until_list_updated(tmp_path):
    assert _static(tmp_path, "semgrep==1.181.0").returncode == 1
    updated = _approved(semgrep="1.181.0")
    assert _static(tmp_path, "semgrep==1.181.0", doc=updated).returncode == 0


@pytest.mark.parametrize("lines", [["-r x.txt"], ["not a valid ==== line!!"]])
def test_static_option_line_and_garbage_fail_closed(tmp_path, lines):
    assert _static(tmp_path, *lines).returncode == 2


# --- installed check ----------------------------------------------------


def _mcp_dist(version: str = "1.29.0") -> Dist:
    return Dist("mcp", version, [], [])


def _semgrep(version: str = "1.179.0", mcp_pin: str = "1.29.0") -> Dist:
    return Dist("semgrep", version, [f"mcp=={mcp_pin}"], [])


def test_installed_clean_closure_passes():
    v, notes = m.check_installed(
        [_semgrep(), _mcp_dist()], _roots("semgrep==1.179.0", "mcp==1.29.0"), _approved_obj()
    )
    assert (v, notes) == ([], [])


def test_installed_semgrep_pins_new_mcp_fails():
    dists = [_semgrep("1.181.0", "1.30.0"), _mcp_dist("1.30.0")]
    roots = _roots("semgrep", "mcp")
    v, _ = m.check_installed(dists, roots, _approved_obj())
    assert len(v) == 2
    v, _ = m.check_installed(dists, roots, _approved_obj(semgrep="1.181.0", mcp="1.30.0"))
    assert v == []


def test_installed_transitive_unlisted_fails():
    dists = [Dist("foo", "1", ["bar"], []), Dist("bar", "1", ["mcp"], []), _mcp_dist()]
    v, _ = m.check_installed(dists, _roots("foo"), _approved_obj())
    assert any("bar==1" in x and "foo" in x and "req.txt:1" in x for x in v), v


def test_installed_outside_closure_is_note_only(tmp_path):
    site = tmp_path / "site"
    _dist_info(site, "hosdep", "1.0", [])
    _dist_info(site, "mcp-server-x", "0.1", [])
    req = _write(tmp_path, "requirements.txt", "hosdep==1.0\n")
    res = _cli(
        "--list", str(_LIST), "--requirements", str(req), "--installed", "--site-path", str(site)
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "NOTE (not gated until #2199): mcp-server-x==0.1" in res.stdout


def test_marker_false_edge_not_followed():
    dists = [Dist("foo", "1", ['mcp; python_version < "2"'], []), _mcp_dist("9.9")]
    v, notes = m.check_installed(dists, _roots("foo"), _approved_obj())
    # foo itself is an MCP dist (R3, markers ignored) and is unlisted; mcp is outside the closure.
    assert any("unlisted MCP package foo" in x for x in v)
    assert any("mcp==9.9" in n for n in notes)
    assert not any("mcp==9.9" in x for x in v)


def test_extra_edge_followed_only_when_requested():
    foo = Dist("foo", "1", ['bar; extra == "ai"'], [])
    bar = Dist("bar", "1", ["mcp"], [])
    mcp9 = _mcp_dist("9.9")
    _, notes = m.check_installed([foo, bar, mcp9], _roots("foo"), _approved_obj())
    assert any("bar==1" in n for n in notes)
    v, _ = m.check_installed([foo, bar, mcp9], _roots("foo[ai]"), _approved_obj())
    assert any("bar==1" in x for x in v) and any("mcp==9.9" in x for x in v)


def test_installed_missing_dep_fails_closed():
    with pytest.raises(m.CheckError):
        m.check_installed([Dist("foo", "1", ["bar"], [])], _roots("foo"), _approved_obj())
    with pytest.raises(m.CheckError):
        m.check_installed([], _roots("foo"), _approved_obj())


def test_installed_duplicate_dist_fails_closed():
    with pytest.raises(m.CheckError):
        m.check_installed([Dist("foo", "1", [], []), Dist("Foo", "2", [], [])], [], _approved_obj())


def test_installed_bad_metadata_fails_closed():
    with pytest.raises(m.CheckError):
        m.check_installed([Dist("foo", "1", ["!!bad"], [])], _roots("foo"), _approved_obj())


# --- CLI over fake dist-info -------------------------------------------


def _dist_info(site: Path, name: str, version: str, requires: list[str], eps: str = "") -> None:
    d = site / f"{name.replace('-', '_')}-{version}.dist-info"
    d.mkdir(parents=True)
    meta = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    meta += [f"Requires-Dist: {r}" for r in requires]
    (d / "METADATA").write_text("\n".join(meta) + "\n")
    if eps:
        (d / "entry_points.txt").write_text(eps)


def test_cli_reads_fake_dist_info_dirs(tmp_path):
    site = tmp_path / "site"
    _dist_info(site, "semgrep", "1.179.0", ["mcp==1.29.0"])
    _dist_info(site, "mcp", "1.29.0", [])
    req = _write(tmp_path, "requirements.txt", "semgrep==1.179.0\nmcp==1.29.0\n")
    args = (
        "--list",
        str(_LIST),
        "--requirements",
        str(req),
        "--installed",
        "--site-path",
        str(site),
    )
    assert _cli(*args).returncode == 0
    site2 = tmp_path / "site2"
    _dist_info(site2, "semgrep", "1.179.0", ["mcp==1.29.0"])
    _dist_info(site2, "mcp", "1.30.0", [])
    args2 = (
        "--list",
        str(_LIST),
        "--requirements",
        str(req),
        "--installed",
        "--site-path",
        str(site2),
    )
    res = _cli(*args2)
    assert res.returncode == 1 and "list says ==1.29.0" in res.stdout
    site3 = tmp_path / "site3"
    _dist_info(site3, "foo", "1", [], "[console_scripts]\nrun = mcp.cli:app\n")
    req3 = _write(tmp_path, "r3.txt", "foo==1\n")
    res = _cli(
        "--list", str(_LIST), "--requirements", str(req3), "--installed", "--site-path", str(site3)
    )
    assert res.returncode == 1 and "unlisted MCP package foo" in res.stdout


# --- gate ---------------------------------------------------------------


def test_gate_empty_changeset_not_checked():
    res = subprocess.run(
        ["bash", str(_GATE), "--empty-changeset"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO),
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "NOT CHECKED" in res.stdout


def test_gate_source_invariants():
    text = _GATE.read_text()
    assert " -I " in text
    assert "--site-path" not in text
    assert not re.search(r"\$\{[A-Z_]*(LIST|MCP)[A-Z_]*:-", text), "env override for the list path"
    # every non-zero rc exits 1; the only exit 0 paths are clean/empty/suspended
    case_arms = text[text.index('case "$rc" in') :]
    assert "exit 1" in case_arms.split("*)")[1]
    assert case_arms.count("exit 0") == 1


# --- repo-wide premises -------------------------------------------------


def _tracked(*paths: str) -> list[Path]:
    res = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return [_REPO / p for p in res.stdout.split("\0") if p and (_REPO / p).is_file()]


def test_bootstrap_pip_sites_install_no_mcp():
    files = [f for f in _tracked("bootstrap", "bin", "scripts") if f.suffix == ".sh"]
    assert files
    bad = []
    for f in files:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if "pip install" in line or "pip3 install" in line:
                if any(
                    m._name_is_mcp(tok)
                    for tok in re.findall(r"[A-Za-z0-9_.\-]+", line.split("install", 1)[1])
                ):
                    bad.append(f"{f.relative_to(_REPO)}:{n}")
    assert not bad, f"pip install lines naming MCP packages: {bad}"
    boot = (_REPO / "bootstrap" / "hos_bootstrap.sh").read_text()
    pkgs = re.search(r'^ANALYSIS_PKGS="([^"]*)"', boot, re.M)
    assert pkgs, "ANALYSIS_PKGS not found in hos_bootstrap.sh"
    assert not any(m._name_is_mcp(p) for p in pkgs.group(1).split())


def test_protected_surfaces_cover_list_and_logic():
    text = (_REPO / "scripts" / "framework" / "protected_surfaces.txt").read_text().splitlines()
    assert "scripts/oversight/mcp_approved_list.json" in text
    assert "scripts/oversight/mcp_policy_logic.py" in text


def test_contract_states_mcp_rule():
    text = (_REPO / "contract" / "OVERSIGHT-CONTRACT.md").read_text()
    assert "## 9. MCP software (approved list)" in text
    assert "HOS installs MCP software only if it is on the approved list" in text
