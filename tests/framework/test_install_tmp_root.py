"""scripts/framework/install.sh configures HOS_TMP_ROOT (#2054 S2a, TD section 2A.1, I1).

Runs the real install.sh non-interactively against a throwaway target. The
target carries a stub ``check_agents_static.sh`` (install.sh's last step) and a
copy of the real resolver, which install.sh calls for the default and for the
refusal check.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "framework" / "install.sh"
RESOLVER = ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"


def _install(
    target: Path, home: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    (target / "scripts" / "framework").mkdir(parents=True, exist_ok=True)
    stub = target / "scripts" / "framework" / "check_agents_static.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    (target / "bootstrap" / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy(RESOLVER, target / "bootstrap" / "lib" / "hos_tmp_root.py")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin", "PROJECT_NAME": "My App"}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(INSTALL), "--non-interactive", "--target", str(target)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=child_env(env),
    )


def _config_line(target: Path) -> str:
    lines = [
        ln
        for ln in (target / "scripts" / "framework" / "config.sh").read_text().splitlines()
        if ln.startswith("HOS_TMP_ROOT=")
    ]
    assert len(lines) == 1, lines
    return lines[0]


def test_i1_multi_clone_registry_defaults_to_dot_tmp_beside_the_clones(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "hos").mkdir(parents=True)
    target = tmp_path / "proj" / "Human"
    target.mkdir(parents=True)
    (home / ".config" / "hos" / "projects.conf").write_text(
        f"p_config_dir={home}/.config/hos\np_worker_root={tmp_path}/proj/Worker\n"
    )
    r = _install(target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _config_line(target) == 'HOS_TMP_ROOT="../.tmp"'
    # prompt_value must return the bare value, not its own prompt text.
    config = (target / "scripts" / "framework" / "config.sh").read_text()
    assert 'PROJECT_NAME="My App"\n' in config


def test_i1_lone_clone_defaults_to_a_per_project_state_dir(tmp_path):
    spec = importlib.util.spec_from_file_location("hos_tmp_root_i1", RESOLVER)
    resolver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolver)
    if resolver.check_outside_work_tree(resolver._home()):
        pytest.skip("the account home is inside a git work tree")

    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "src" / "MyApp"
    target.mkdir(parents=True)
    r = _install(target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _config_line(target) == 'HOS_TMP_ROOT="~/.local/state/hos/tmp/my-app"'


def test_i1_a_value_inside_a_work_tree_is_refused(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "wt" / ".git").mkdir(parents=True)
    target = tmp_path / "proj" / "Human"
    target.mkdir(parents=True)
    r = _install(target, home, {"HOS_TMP_ROOT": str(tmp_path / "wt" / "tmp")})
    assert r.returncode != 0
    assert "git work tree" in r.stderr
    assert not (target / "scripts" / "framework" / "config.sh").exists()


def test_i1_a_value_inside_the_clone_is_refused(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "proj" / "Human"
    target.mkdir(parents=True)
    r = _install(target, home, {"HOS_TMP_ROOT": "./tmp"})
    assert r.returncode != 0
    assert "inside the clone" in r.stderr


def test_i1_an_existing_value_is_kept_on_reinstall(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "proj" / "Human"
    (target / "scripts" / "framework").mkdir(parents=True)
    (target / "scripts" / "framework" / "config.sh").write_text(
        # Every key install.sh greps for must exist: it aborts on a missing one.
        'PROJECT_NAME="My App"\nPROJECT_STACK=""\nPROJECT_NON_AGENT_TOKENS=""\n'
        'DESIGN_PACK_PATH=""\nEXTRA_REVIEW_FILES=""\nSPEC_FILE=""\nDESIGN_PACK_DIR=""\n'
        'PACK=""\nexport HOS_TMP_ROOT="../custom"\n'
    )
    r = _install(target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _config_line(target) == 'HOS_TMP_ROOT="../custom"'


def test_i1_an_existing_config_without_the_key_does_not_abort_the_upgrade(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "proj" / "Human"
    (target / "scripts" / "framework").mkdir(parents=True)
    (home / ".config" / "hos").mkdir(parents=True)
    (home / ".config" / "hos" / "projects.conf").write_text(
        f"p_worker_root={tmp_path}/proj/Worker\n"
    )
    (target / "scripts" / "framework" / "config.sh").write_text(
        'PROJECT_NAME="My App"\nPROJECT_STACK=""\nPROJECT_NON_AGENT_TOKENS=""\n'
        'DESIGN_PACK_PATH=""\nEXTRA_REVIEW_FILES=""\nSPEC_FILE=""\nDESIGN_PACK_DIR=""\n'
        'PACK=""\n'
    )
    r = _install(target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _config_line(target) == 'HOS_TMP_ROOT="../.tmp"'
