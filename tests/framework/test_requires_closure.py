"""Install-path tests for the pack `requires`-closure (ADR-032 D3, #1036).

Mirrors ``test_pack_install.py``'s pattern: drive ``bootstrap/hos_install.sh
--local`` against throwaway git-initialised target repos using the REAL HOS
source tree. Fixture packs live permanently under ``packs/`` (same convention
as ``packs/testpack/``):

- ``packs/testpack-dep`` — ``requires = ["testpack"]`` (single dependency).
- ``packs/testcycle-a`` / ``packs/testcycle-b`` — mutual cycle.
"""

import os
import subprocess
from pathlib import Path

import pytest
from regions import parse

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "bootstrap" / "hos_install.sh"
PACK_AGENT = "security-reviewer"


def _run_installer(target: Path, extra_args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["bash", str(INSTALL_SH), "--local", str(target), *extra_args]
    env = {**os.environ, "HOS_NO_CONFIG": "1"}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input="\n",
    )


def _git_init_target(base: Path) -> Path:
    target = base / "target"
    target.mkdir()
    subprocess.run(["git", "init", str(target)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(target), "config", "user.email", "test@example.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(target), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    return target


@pytest.mark.slow
def test_pack_dep_injects_both_regions(tmp_path):
    """--pack testpack-dep → closure pulls in testpack; both PACK regions land."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack-dep"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    assert agent_file.exists()
    ids = [reg.id for reg in parse(agent_file.read_bytes()).regions]
    assert "PACK:testpack" in ids, f"dependency region missing: {ids}"
    assert "PACK:testpack-dep" in ids, f"leaf region missing: {ids}"

    # (R4) single operator-selected leaf → closure expanding to 2 packs must NOT
    # trigger the untested-multi-pack WARN (that warn is leaf-count gated).
    combined = r.stdout + r.stderr
    assert "UNTESTED" not in combined and "untested" not in combined.lower()


@pytest.mark.slow
def test_standalone_leaf_has_no_phantom_deps(tmp_path):
    """--pack testpack (a leaf with requires=[]) → no dependency region injected."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    ids = [reg.id for reg in parse(agent_file.read_bytes()).regions]
    assert ids == ["CORE", "PACK:testpack", "PROJECT"], f"unexpected ids: {ids}"


@pytest.mark.slow
def test_upgrade_reconstructs_closure_from_recorded_leaf(tmp_path):
    """First install --pack testpack-dep records the LEAF only; a flagless
    upgrade re-derives the full closure from config.sh PACK= alone."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack-dep"])
    assert r.returncode == 0, r.stdout + r.stderr

    config_file = target / "scripts" / "framework" / "config.sh"
    assert config_file.exists()
    assert 'PACK="testpack-dep"' in config_file.read_text(), (
        "config.sh must record the LEAF only, not the closure "
        f"(DQ-9): {config_file.read_text()!r}"
    )

    # Flagless re-install (upgrade path): reads config.sh PACK=testpack-dep,
    # must reconstruct the (testpack testpack-dep) closure again.
    r2 = _run_installer(target, [])
    assert r2.returncode == 0, r2.stdout + r2.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    ids = [reg.id for reg in parse(agent_file.read_bytes()).regions]
    assert "PACK:testpack" in ids, f"upgrade did not reconstruct dependency: {ids}"
    assert "PACK:testpack-dep" in ids, f"upgrade did not reconstruct leaf: {ids}"


@pytest.mark.slow
def test_cycle_hard_errors_nothing_written(tmp_path):
    """--pack testcycle-a (mutual cycle with testcycle-b) → hard error, exit
    non-zero, nothing written."""
    target = _git_init_target(tmp_path)
    agents_dir = target / ".claude" / "agents"

    r = _run_installer(target, ["--pack", "testcycle-a"])
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "cycle" in combined.lower()
    assert not agents_dir.exists() or list(agents_dir.iterdir()) == []


@pytest.mark.slow
def test_config_records_leaf_only_not_closure(tmp_path):
    """config.sh PACK= after --pack testpack-dep is the single leaf value,
    never a multi-value closure (R5 unchanged, DQ-9)."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack-dep"])
    assert r.returncode == 0, r.stdout + r.stderr

    config_file = target / "scripts" / "framework" / "config.sh"
    pack_lines = [
        line for line in config_file.read_text().splitlines() if line.startswith("PACK=")
    ]
    assert pack_lines == ['PACK="testpack-dep"'], f"expected single leaf-only PACK= line: {pack_lines}"


@pytest.mark.slow
def test_pack_astro_resolves_node_dependency(tmp_path):
    """The real ``--pack astro`` -> node assertion deferred from S3 (#1036) to
    S16 (#1072), now that packs/astro exists. Mirrors
    test_pack_dep_injects_both_regions but against the real two-layer pack
    the astro/node work exists to serve, on an agent both packs deepen."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "astro"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / "coder.md"
    assert agent_file.exists()
    ids = [reg.id for reg in parse(agent_file.read_bytes()).regions]
    assert "PACK:node" in ids, f"node dependency region missing: {ids}"
    assert "PACK:astro" in ids, f"astro leaf region missing: {ids}"
    # #1080: PACK:node (the dependency astro requires) must compose BEFORE
    # PACK:astro (the dependent/most-specific layer) so recency precedence
    # favors the specialization, not the base it specializes.
    assert ids.index("PACK:node") < ids.index("PACK:astro"), (
        f"node must precede astro for recency precedence: {ids}"
    )

    config_file = target / "scripts" / "framework" / "config.sh"
    pack_lines = [
        line for line in config_file.read_text().splitlines() if line.startswith("PACK=")
    ]
    assert pack_lines == ['PACK="astro"'], f"expected single leaf-only PACK= line: {pack_lines}"


@pytest.mark.slow
def test_pack_astro_test_agent_regions_inject(tmp_path):
    """S18 (#1074): packs/astro/unit-test.md and packs/astro/system-test.md
    (spec-derived test independence + vitest/Container API/Playwright
    conventions) must compose into the installed unit-test/system-test agent
    files alongside PACK:node, the same way coder.md does."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "astro"])
    assert r.returncode == 0, r.stdout + r.stderr

    for agent_name in ("unit-test", "system-test"):
        agent_file = target / ".claude" / "agents" / f"{agent_name}.md"
        assert agent_file.exists()
        ids = [reg.id for reg in parse(agent_file.read_bytes()).regions]
        assert "PACK:node" in ids, f"{agent_name}: node dependency region missing: {ids}"
        assert "PACK:astro" in ids, f"{agent_name}: astro leaf region missing: {ids}"
        # #1080: node (base) must precede astro (dependent) — recency
        # precedence.
        assert ids.index("PACK:node") < ids.index("PACK:astro"), (
            f"{agent_name}: node must precede astro for recency precedence: {ids}"
        )
