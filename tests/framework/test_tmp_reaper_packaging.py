"""Packaging, invocation sites and docs of the machine temp reaper (#2054, TD 10 C4).

Static checks plus a behavioural run of hos_bootstrap.sh's machine-copy step under a
fake HOME. Nothing here runs the reaper against a real temp dir.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "bootstrap" / "hos_bootstrap.sh"
INSTALL = ROOT / "bootstrap" / "hos_install.sh"


def _bootstrap(home: Path, bundle: Path) -> subprocess.CompletedProcess:
    script = bundle / "hos_bootstrap.sh"
    return subprocess.run(
        ["bash", str(script), "--reaper-only"],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )


def _bundle(tmp_path: Path, with_reaper: bool) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "hos_bootstrap.sh").write_text(BOOTSTRAP.read_text())
    if with_reaper:
        (bundle / "tmp_reaper.py").write_text((ROOT / "bootstrap" / "tmp_reaper.py").read_text())
    return bundle


def test_c4a_hos_cron_runs_the_reaper_only_in_the_low_space_trigger():
    lines = (ROOT / "bin" / "hos-cron").read_text().splitlines()
    code = [ln for ln in lines if "tmp_reaper.py" in ln and not ln.lstrip().startswith("#")]
    invocations = [ln for ln in code if "python3" in ln]
    assert len(invocations) == 1 and "--if-low-space" in invocations[0]
    # the only other reference is the existence guard that wraps that invocation
    assert len(code) == 2 and code[0].lstrip().startswith("if [[ -f")
    assert "tmp_reap_scratch" not in "\n".join(lines)


def test_c4b_cron_recipe_is_machine_copy_bounded_daily_and_logs_off_tmp():
    text = (ROOT / "docs" / "CRON-SETUP.md").read_text()
    recipes = [
        ln for ln in text.splitlines() if re.match(r"^\d+ \d+ ", ln) and "tmp_reaper.py" in ln
    ]
    assert len(recipes) == 1
    line = recipes[0]
    m = re.match(
        r"^(\d+) (\d+) \* \* \*\s+timeout --kill-after=\d+ (\d+) python3 -I \"?([^\" ]+)\"? (.*)$",
        line,
    )
    assert m, line
    _minute, _hour, outer, script, rest = m.groups()
    assert ".local/share/hos/tmp_reaper.py" in script and "Code/" not in script
    assert int(re.search(r"--max-seconds (\d+)", rest).group(1)) < int(outer)
    assert "--root /tmp" in rest and "--hos-tmp-root" in rest
    log = re.search(r">> \"?([^\" ]+)", rest).group(1)
    assert not re.match(r"^/tmp(/|$)", log) and log.startswith("$HOME/.hos/")
    assert "find /tmp/pytest-of-scott" in text and "remove" in text.lower()  # stopgap removal note


def test_c4c_bootstrap_copy_is_idempotent_atomic_and_never_fails(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bundle = _bundle(tmp_path, with_reaper=True)
    dest = home / ".local" / "share" / "hos" / "tmp_reaper.py"
    first = _bootstrap(home, bundle)
    assert first.returncode == 0, first.stderr
    assert dest.read_bytes() == (bundle / "tmp_reaper.py").read_bytes()
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755
    ino, mtime = dest.stat().st_ino, dest.stat().st_mtime_ns
    second = _bootstrap(home, bundle)
    assert second.returncode == 0 and "already current" in second.stdout
    assert (dest.stat().st_ino, dest.stat().st_mtime_ns) == (ino, mtime)
    assert [p.name for p in dest.parent.iterdir()] == ["tmp_reaper.py"]  # no .new leftovers
    (bundle / "tmp_reaper.py").write_text("# newer\n")
    assert _bootstrap(home, bundle).returncode == 0
    assert dest.read_text() == "# newer\n"
    # an old bundle without the file: one WARN, exit 0, nothing installed
    home2 = tmp_path / "home2"
    home2.mkdir()
    old = _bootstrap(home2, _bundle_old(tmp_path))
    assert old.returncode == 0 and "tmp_reaper.py not found" in old.stdout
    assert not (home2 / ".local").exists()


def _bundle_old(tmp_path: Path) -> Path:
    bundle = tmp_path / "oldbundle"
    bundle.mkdir()
    (bundle / "hos_bootstrap.sh").write_text(BOOTSTRAP.read_text())
    return bundle


def test_c4c_install_mentions_the_machine_copy_and_neither_script_invokes_crontab():
    assert ".local/share/hos/tmp_reaper.py" in INSTALL.read_text()
    for script in (BOOTSTRAP, INSTALL):
        for n, ln in enumerate(script.read_text().splitlines(), 1):
            if re.search(r"\bcrontab\b", ln):
                stripped = ln.lstrip()
                assert stripped.startswith("#") or re.match(r"(echo|printf)\b", stripped), (
                    script.name,
                    n,
                    ln,
                )


def test_c4d_claude_md_has_the_entry_point_row():
    text = (ROOT / "CLAUDE.md").read_text()
    row = next(ln for ln in text.splitlines() if ln.startswith("| Reclaiming temp space"))
    assert "`bootstrap/tmp_reaper.py`" in row and "~/.local/share/hos/tmp_reaper.py" in row
    assert "CLAUDE_CODE_TMPDIR" in text and "Environment=CLAUDE_CODE_TMPDIR=" in text


def test_c4e_release_ships_the_reaper():
    text = (ROOT / "scripts" / "framework" / "cut_release.sh").read_text()
    names = re.search(r"^ASSET_NAMES=\(([^)]*)\)", text, re.M).group(1).split()
    assert "tmp_reaper.py" in names
    assert "tmp_reaper.py" in text.split("Get started on a fresh machine")[1]


def test_c3_consumer_files_list_ships_the_reaper_from_bootstrap_only():
    listed = [
        ln.split("#", 1)[0].strip()
        for ln in (ROOT / "scripts" / "framework" / "framework_consumer_files.txt")
        .read_text()
        .splitlines()
    ]
    assert "bootstrap/tmp_reaper.py" in listed
    assert (ROOT / "bootstrap" / "tmp_reaper.py").is_file()
    assert not (ROOT / "scripts" / "framework" / "tmp_reaper.py").exists()
    assert os.access(ROOT / "bootstrap" / "tmp_reaper.py", os.X_OK)


def test_the_stale_stopgap_is_not_in_any_shipped_script():
    for rel in ("bin/hos-cron", "bin/hos-human", "scripts/framework/run_tests_inner_loop.sh"):
        assert "find /tmp/pytest-of" not in (ROOT / rel).read_text()


def test_bootstrap_refuses_a_copy_that_does_not_match_the_bundle_checksums(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bundle = _bundle(tmp_path, with_reaper=True)
    good = subprocess.run(
        ["sha256sum", "tmp_reaper.py"], cwd=bundle, capture_output=True, text=True
    ).stdout
    (bundle / "SHA256SUMS").write_text(good)
    dest = home / ".local" / "share" / "hos" / "tmp_reaper.py"
    assert _bootstrap(home, bundle).returncode == 0 and dest.exists()
    dest.unlink()
    (bundle / "SHA256SUMS").write_text("0" * 64 + "  tmp_reaper.py\n")
    bad = _bootstrap(home, bundle)
    assert bad.returncode != 0 and "corruption check" in bad.stdout and not dest.exists()


def test_bootstrap_reaper_only_fails_when_the_copy_fails_but_not_for_a_missing_source(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".local").write_text("a file, so ~/.local/share/hos cannot be created")
    bundle = _bundle(tmp_path, with_reaper=True)
    failed = _bootstrap(home, bundle)
    assert failed.returncode != 0 and "could not install the temp reaper" in failed.stdout
    home2 = tmp_path / "home2"
    home2.mkdir()
    missing = _bootstrap(home2, _bundle_old(tmp_path))
    assert missing.returncode == 0 and "tmp_reaper.py not found" in missing.stdout


def test_bootstrap_warns_when_run_from_inside_a_git_work_tree(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bundle = _bundle(tmp_path, with_reaper=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    result = _bootstrap(home, bundle)
    assert result.returncode == 0 and "inside a git work tree" in result.stdout


def test_bootstrap_warns_about_a_work_tree_even_when_sha256sums_exists(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bundle = _bundle(tmp_path, with_reaper=True)
    good = subprocess.run(
        ["sha256sum", "tmp_reaper.py"], cwd=bundle, capture_output=True, text=True
    ).stdout
    (bundle / "SHA256SUMS").write_text(good)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    result = _bootstrap(home, bundle)
    assert result.returncode == 0 and "inside a git work tree" in result.stdout


def test_the_sandbox_template_never_grants_the_trust_registry_location():
    """~/.local/state/hos/tmp-roots.json is the registry that decides which role dirs the
    reaper may delete from; it is only unforgeable from a sandbox while nothing grants it. denyRead __HOME__/
    hides it; no allow entry may re-open it (nor ~/.local, nor ~ itself)."""
    import json

    doc = json.loads((ROOT / "contract" / "sandbox-policy.template.json").read_text())
    fs = doc["sandbox"]["filesystem"]
    assert "__HOME__/" in fs["denyRead"]
    entries = [
        *fs.get("allowRead", []),
        *fs.get("allowWrite", []),
        *doc["permissions"].get("additionalDirectories", []),
        *doc["permissions"].get("allow", []),
    ]
    covering = {
        "__HOME__",
        "__HOME__/",
        "__HOME__/.local",
        "__HOME__/.local/",
        "__HOME__/.local/state",
        "__HOME__/.local/state/",
        "__HOME__/.local/state/hos",
        "__HOME__/.local/state/hos/",
        "__HOME__/.local/state/hos/tmp-roots.json",
        "__HOME__/.local/state/hos/tmp-root.nonce",
    }
    for entry in entries:
        bare = entry
        for prefix in ("Read(", "Edit(", "Write("):
            if entry.startswith(prefix):
                bare = entry[len(prefix) : -1]
        bare = bare.removesuffix("/**")
        assert bare not in covering and ".local/state" not in entry, entry
