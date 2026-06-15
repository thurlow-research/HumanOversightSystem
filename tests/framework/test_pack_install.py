"""Install-path tests for the pack selection/composition mechanism.

These tests drive ``bootstrap/hos_install.sh --local`` against throwaway
git-initialised target repos using the REAL HOS source tree (the local
working copy, which ``--local`` always selects as HOS_SOURCE).

Design §5.2: the install-path tests assert the *wiring* — that the pack
resolution block, the A1b injection, the config.sh recording, and the
manifest rows all behave as specified.  The per-region merge logic
(REFRESH/HARDSTOP/DROP) is already covered by ``test_plan_upgrade.py``;
these tests confirm that the wiring reaches those paths.

The fixture pack ``packs/testpack/`` lives in the HOS repo root so the
installer finds it at ``$HOS_SOURCE/packs/testpack/``.

``HOS_NO_CONFIG=1`` suppresses the interactive config sub-invocation.
"""

import os
import shutil
import subprocess
from pathlib import Path

import regions
from regions import parse, region_sha

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "bootstrap" / "hos_install.sh"
PACK_AGENT = "security-reviewer"  # the agent testpack deepens


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _run_installer(
    target: Path,
    extra_args: list[str],
) -> subprocess.CompletedProcess:
    """Run hos_install.sh --local against a git-initialised target.

    HOS_NO_CONFIG=1 skips the interactive config tool delegation.
    """
    cmd = [
        "bash",
        str(INSTALL_SH),
        "--local",
        str(target),
        *extra_args,
    ]
    env = {**os.environ, "HOS_NO_CONFIG": "1"}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input="\n",  # non-interactive stdin so pack-resolution R2 hits the CI path
    )


def _git_init_target(base: Path) -> Path:
    """Create and git-initialise a fresh target directory."""
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


def _assert_pack_body(target: Path, pack_name: str) -> bytes:
    """Return the body bytes of the PACK:<name> region for PACK_AGENT."""
    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    assert agent_file.exists(), f"agent file not written: {agent_file}"
    parsed = parse(agent_file.read_bytes())
    pack_reg = next(
        (r for r in parsed.regions if r.id == f"PACK:{pack_name}"),
        None,
    )
    assert pack_reg is not None, f"PACK:{pack_name} not found in {[r.id for r in parsed.regions]}"
    return pack_reg.body


# --------------------------------------------------------------------------- #
# mutual exclusion
# --------------------------------------------------------------------------- #


def test_install_pack_mutual_exclusion(tmp_path):
    """--pack and --no-pack together → usage error exit 1 before any work."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack", "--no-pack"])
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "mutually exclusive" in combined


# --------------------------------------------------------------------------- #
# unknown pack → hard error, nothing written
# --------------------------------------------------------------------------- #


def test_install_unknown_pack_hard_error(tmp_path):
    """An unknown pack name → non-zero exit; message names the pack; agents dir empty."""
    target = _git_init_target(tmp_path)
    agents_dir = target / ".claude" / "agents"

    r = _run_installer(target, ["--pack", "nope-no-such-pack"])
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "unknown pack" in combined
    assert "nope-no-such-pack" in combined
    # Nothing written to the agents dir.
    assert not agents_dir.exists() or list(agents_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# no-pack decision tree
# --------------------------------------------------------------------------- #


def test_install_no_pack_interactive_errors(tmp_path):
    """No --pack, no --no-pack → non-zero exit; message names --pack/--no-pack."""
    target = _git_init_target(tmp_path)
    # stdin from subprocess is never a tty → non-interactive path fires.
    r = _run_installer(target, [])
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "--pack" in combined or "--no-pack" in combined


def test_install_no_pack_core_only_warn(tmp_path):
    """--no-pack → exit 0; PACK_AGENT gets CORE+PROJECT only; bare-core WARN."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--no-pack"])
    assert r.returncode == 0, r.stdout + r.stderr

    combined = r.stdout + r.stderr
    # The #237 bare-core warn must appear.
    assert "bare core" in combined.lower() or "no pack" in combined.lower()

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    assert agent_file.exists(), "agent file not written"
    parsed = parse(agent_file.read_bytes())
    ids = [reg.id for reg in parsed.regions]
    assert not any(i.startswith("PACK:") for i in ids), f"unexpected PACK region: {ids}"


# --------------------------------------------------------------------------- #
# pack installs — composition, manifest, config recording
# --------------------------------------------------------------------------- #


def test_install_with_pack_composes_three_regions(tmp_path):
    """--pack testpack → PACK_AGENT has CORE+PACK:testpack+PROJECT."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    assert agent_file.exists()
    parsed = parse(agent_file.read_bytes())
    ids = [reg.id for reg in parsed.regions]
    assert ids == ["CORE", "PACK:testpack", "PROJECT"], f"unexpected ids: {ids}"


def test_install_pack_manifest_rows(tmp_path):
    """--pack testpack → .hos-manifest has PACK:testpack row with correct sha."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    manifest_file = target / ".hos-manifest"
    assert manifest_file.exists(), ".hos-manifest not written"
    manifest_text = manifest_file.read_text()

    pack_rows = [
        line
        for line in manifest_text.splitlines()
        if "PACK:testpack" in line and PACK_AGENT in line
    ]
    assert len(pack_rows) == 1, f"expected one PACK:testpack row, got: {pack_rows}"

    body_bytes = (ROOT / "packs" / "testpack" / f"{PACK_AGENT}.md").read_bytes()
    expected_sha = region_sha(body_bytes)
    assert (
        expected_sha in pack_rows[0]
    ), f"manifest sha mismatch: expected {expected_sha!r} in {pack_rows[0]!r}"


def test_install_pack_records_config(tmp_path):
    """--pack testpack → scripts/framework/config.sh contains PACK=\"testpack\"."""
    target = _git_init_target(tmp_path)
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    config_file = target / "scripts" / "framework" / "config.sh"
    assert config_file.exists(), "config.sh not written"
    assert 'PACK="testpack"' in config_file.read_text()


# --------------------------------------------------------------------------- #
# multi-pack
# --------------------------------------------------------------------------- #


def test_install_multipack_warns(tmp_path):
    """--pack testpack --pack testpack2 → multi-pack WARN fires; both packs listed."""
    target = _git_init_target(tmp_path)

    # Create testpack2 temporarily in the repo root (no agent body — no injection).
    testpack2_dir = ROOT / "packs" / "testpack2"
    testpack2_dir.mkdir(exist_ok=True)
    (testpack2_dir / "pack.toml").write_text(
        'name = "testpack2"\ndescription = "multi-pack test"\nversion = "0.1.0"\nrequires = []\n'
    )
    try:
        r = _run_installer(target, ["--pack", "testpack", "--pack", "testpack2"])
        assert r.returncode == 0, r.stdout + r.stderr
        combined = r.stdout + r.stderr
        assert "UNTESTED" in combined or "untested" in combined
        assert "testpack" in combined and "testpack2" in combined
    finally:
        shutil.rmtree(str(testpack2_dir), ignore_errors=True)


# --------------------------------------------------------------------------- #
# upgrade paths
# --------------------------------------------------------------------------- #


def test_upgrade_pack_version_bump_refresh(tmp_path):
    """Install testpack, bump the body in a tmp copy, re-install → PACK REFRESHed."""
    target = _git_init_target(tmp_path)

    # First install.
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    original_body = _assert_pack_body(target, "testpack")
    original_sha = region_sha(original_body)

    # Bump the pack body by writing a modified version to a tmp packs dir,
    # then swap it in for the duration of the test.
    real_body = ROOT / "packs" / "testpack" / f"{PACK_AGENT}.md"
    backup = real_body.read_bytes()
    real_body.write_bytes(b"Bumped testpack depth v2.\n")
    try:
        r2 = _run_installer(target, ["--pack", "testpack"])
        assert r2.returncode == 0, r2.stdout + r2.stderr
        new_body = _assert_pack_body(target, "testpack")
        assert region_sha(new_body) != original_sha, "PACK region was not refreshed"
        assert b"v2" in new_body
    finally:
        real_body.write_bytes(backup)


def test_upgrade_consumer_edited_pack_hardstop(tmp_path):
    """Consumer-edited PACK region + bumped body → HARDSTOP exit 4, nothing written."""
    target = _git_init_target(tmp_path)

    # First install.
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    original_bytes = agent_file.read_bytes()

    # Hand-edit the PACK:testpack region (consumer drift).
    edited = original_bytes.replace(b"Testpack depth", b"CONSUMER EDITED testpack depth")
    assert edited != original_bytes, "edit had no effect — check fixture body text"
    agent_file.write_bytes(edited)

    # Snapshot .hos-manifest before the blocked second install.
    manifest_file = target / ".hos-manifest"
    assert manifest_file.exists(), ".hos-manifest should exist after first install"
    manifest_snapshot = manifest_file.read_bytes()

    # Bump the pack body in the real source.
    real_body = ROOT / "packs" / "testpack" / f"{PACK_AGENT}.md"
    backup = real_body.read_bytes()
    real_body.write_bytes(b"Bumped testpack depth v2.\n")
    try:
        r2 = _run_installer(target, ["--pack", "testpack"])
        assert (
            r2.returncode == regions.EXIT_DRIFT
        ), f"expected EXIT_DRIFT(4), got {r2.returncode}\n{r2.stdout}\n{r2.stderr}"
        combined = r2.stdout + r2.stderr
        assert "PACK:testpack" in combined
        # Nothing written — agent file unchanged.
        assert agent_file.read_bytes() == edited
        # .hos-manifest must not be re-written on HARDSTOP (nothing written invariant).
        assert (
            manifest_file.read_bytes() == manifest_snapshot
        ), ".hos-manifest was re-written on a HARDSTOP — nothing-written invariant violated"
    finally:
        real_body.write_bytes(backup)


def test_pack_switch_drops_old_region(tmp_path):
    """Install testpack (unedited), switch to testpack2 → PACK:testpack dropped."""
    target = _git_init_target(tmp_path)

    testpack2_dir = ROOT / "packs" / "testpack2"
    testpack2_dir.mkdir(exist_ok=True)
    (testpack2_dir / "pack.toml").write_text(
        'name = "testpack2"\ndescription = "switch test"\nversion = "0.1.0"\nrequires = []\n'
    )
    pack2_body = testpack2_dir / f"{PACK_AGENT}.md"
    pack2_body.write_text("Testpack2 depth for security-reviewer.\n")

    try:
        # First install with testpack.
        r = _run_installer(target, ["--pack", "testpack"])
        assert r.returncode == 0, r.stdout + r.stderr

        # Switch to testpack2.
        r2 = _run_installer(target, ["--pack", "testpack2"])
        assert r2.returncode == 0, r2.stdout + r2.stderr

        agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
        parsed = parse(agent_file.read_bytes())
        ids = [reg.id for reg in parsed.regions]
        assert "PACK:testpack" not in ids, f"old pack not dropped; ids={ids}"
        assert "PACK:testpack2" in ids, f"new pack not introduced; ids={ids}"

        config_text = (target / "scripts" / "framework" / "config.sh").read_text()
        assert 'PACK="testpack2"' in config_text
    finally:
        shutil.rmtree(str(testpack2_dir), ignore_errors=True)


# --------------------------------------------------------------------------- #
# B1: --no-pack must win over recorded config.sh PACK= (drops PACK region)
# --------------------------------------------------------------------------- #


def test_install_no_pack_over_recorded_pack_drops_region(tmp_path):
    """First install --pack testpack (records PACK= + writes PACK region), then
    re-install --no-pack: assert --no-pack WINS over the recorded PACK=django,
    the PACK:testpack region is DROPped, config.sh PACK= is cleared, and the
    bare-core #237 WARN fires.  Guards B1 (--no-pack silent no-op when config
    carries PACK=).
    """
    target = _git_init_target(tmp_path)

    # First install — records PACK="testpack" in config.sh and injects PACK region.
    r = _run_installer(target, ["--pack", "testpack"])
    assert r.returncode == 0, r.stdout + r.stderr

    agent_file = target / ".claude" / "agents" / f"{PACK_AGENT}.md"
    assert agent_file.exists()
    ids_after_first = [reg.id for reg in parse(agent_file.read_bytes()).regions]
    assert (
        "PACK:testpack" in ids_after_first
    ), f"first install missing PACK region: {ids_after_first}"

    config_file = target / "scripts" / "framework" / "config.sh"
    assert config_file.exists()
    assert (
        'PACK="testpack"' in config_file.read_text()
    ), "config.sh should have PACK= after first install"

    # Second install — explicit --no-pack, no --pack flag.  config.sh still has
    # PACK="testpack" but --no-pack must override it (B1 fix: `! $NO_PACK` gate).
    r2 = _run_installer(target, ["--no-pack"])
    assert r2.returncode == 0, r2.stdout + r2.stderr

    # --no-pack wins: PACK region stripped from agent file.
    parsed2 = parse(agent_file.read_bytes())
    ids2 = [reg.id for reg in parsed2.regions]
    assert not any(
        i.startswith("PACK:") for i in ids2
    ), f"PACK region not dropped after --no-pack: {ids2}"

    # config.sh PACK= is cleared (R2a fix: perl strip).
    config_text2 = config_file.read_text()
    assert (
        "PACK=" not in config_text2
    ), f"config.sh PACK= not cleared after --no-pack: {config_text2!r}"

    # Bare-core #237 WARN must fire.
    combined = r2.stdout + r2.stderr
    assert (
        "bare core" in combined.lower() or "no pack" in combined.lower()
    ), f"bare-core WARN not found in output: {combined!r}"


# --------------------------------------------------------------------------- #
# B2: inject failure → nothing written (fail-closed invariant)
# --------------------------------------------------------------------------- #


def test_install_inject_failure_writes_nothing(tmp_path):
    """A malformed pack body (column-0 literal HOS marker) → inject-pack fails →
    the install exits non-zero AND no agent file is written AND .hos-manifest /
    .hos-release are NOT stamped.  Guards B2 (half-write bug: prior code fell
    through to Phase B even when inject failed for one agent).
    """
    target = _git_init_target(tmp_path)
    agents_dir = target / ".claude" / "agents"

    # Seed a malformed testpack body directly in the real packs tree so the
    # installer finds it.  The body contains a column-0 literal HOS marker
    # (<!-- HOS:CORE:START -->) which inject-pack's re-validate rejects with
    # E_LITERAL_MARKER_IN_BODY → non-zero exit.
    real_body = ROOT / "packs" / "testpack" / f"{PACK_AGENT}.md"
    backup = real_body.read_bytes()
    malformed = b"good line\n<!-- HOS:CORE:START -->\nbad\n<!-- HOS:CORE:END -->\n"
    real_body.write_bytes(malformed)

    try:
        r = _run_installer(target, ["--pack", "testpack"])

        # Install must exit non-zero (pre-Phase-B abort gate, exit 4).
        assert (
            r.returncode != 0
        ), f"expected non-zero exit on inject failure, got 0\n{r.stdout}\n{r.stderr}"

        # Nothing written to .claude/agents/ — agents dir must be absent or empty.
        assert (
            not agents_dir.exists() or list(agents_dir.iterdir()) == []
        ), f"agents dir should be empty on inject failure: {list(agents_dir.iterdir())}"

        # .hos-manifest must NOT be written (no partial manifest).
        manifest_file = target / ".hos-manifest"
        assert not manifest_file.exists(), ".hos-manifest must not be written on inject failure"

        # .hos-release must NOT be stamped.
        release_file = target / ".hos-release"
        assert not release_file.exists(), ".hos-release must not be stamped on inject failure"

    finally:
        real_body.write_bytes(backup)
