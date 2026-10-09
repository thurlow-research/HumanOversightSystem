"""Tests for bootstrap/lib/hos_tmp_root.py (#2054 S2a, TD section 2A.2/2A.5, H1-H5).

Every test builds its clone and temp root under ``tmp_path``. None touches a
real HOS temp root.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

REPO_ROOT = Path(__file__).resolve().parents[2]
_MOD_PATH = REPO_ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"
_SPEC = importlib.util.spec_from_file_location("hos_tmp_root_under_test", _MOD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def _clone(tmp_path: Path, config: str | None = None) -> Path:
    """tmp_path/hos/Worker, with an optional scripts/framework/config.sh."""
    clone = tmp_path / "hos" / "Worker"
    (clone / "scripts" / "framework").mkdir(parents=True)
    if config is not None:
        (clone / "scripts" / "framework" / "config.sh").write_text(config, encoding="utf-8")
    return clone


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(_MOD_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=child_env({}),
    )


# ── H1: config.sh grammar ───────────────────────────────────────────────────


def test_missing_config_defaults_to_dot_tmp_beside_the_clone(tmp_path):
    clone = tmp_path / "hos" / "Worker"
    clone.mkdir(parents=True)
    assert mod.resolve_root(clone) == Path(os.path.realpath(clone)).parent / ".tmp"


@pytest.mark.parametrize("config", ["", "# nothing\nexport FOO=bar\n", 'HOS_TMP_ROOT=""\n'])
def test_empty_or_absent_key_defaults(tmp_path, config):
    clone = _clone(tmp_path, config)
    assert mod.resolve_root(clone) == Path(os.path.realpath(clone)).parent / ".tmp"


def test_relative_value_resolves_against_the_clone(tmp_path):
    clone = _clone(tmp_path, 'export HOS_TMP_ROOT="../scratch"\n')
    assert mod.resolve_root(clone) == Path(os.path.realpath(clone)).parent / "scratch"


def test_tilde_value_resolves_against_the_account_home(tmp_path):
    clone = _clone(tmp_path, "HOS_TMP_ROOT='~/hos-h1-nonexistent/tmp'\n")
    home = mod._home()
    if mod.check_outside_work_tree(home):
        pytest.skip("the account home is inside a git work tree")
    assert mod.resolve_root(clone) == Path(home) / "hos-h1-nonexistent" / "tmp"


def test_absolute_value_is_used_as_is(tmp_path):
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{tmp_path}/abs/root"\n')
    assert mod.resolve_root(clone) == tmp_path / "abs" / "root"


def test_the_last_assignment_wins_and_a_trailing_comment_is_ignored(tmp_path):
    clone = _clone(
        tmp_path,
        'HOS_TMP_ROOT="../first"\nexport HOS_TMP_ROOT=../second   # comment\n',
    )
    assert mod.resolve_root(clone) == Path(os.path.realpath(clone)).parent / "second"


@pytest.mark.parametrize("value", ["$HOME/x", "`id`", "../a;b", "../a*", "../a?b", "../[a]"])
def test_forbidden_characters_exit_3(tmp_path, value):
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{value}"\n')
    r = _cli("root", "--repo", str(clone))
    assert r.returncode == 3, r.stdout + r.stderr
    assert r.stderr.startswith("hos_tmp_root: ")


def test_this_repos_committed_config_line_parses_to_the_default():
    """Guards an edit that the shell accepts but the resolver rejects."""
    assert mod.read_config_value(REPO_ROOT) == "../.tmp"


# ── H2: never inside a work tree or the clone ───────────────────────────────


def test_root_under_a_dot_git_directory_is_refused(tmp_path):
    (tmp_path / "wt" / ".git").mkdir(parents=True)
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{tmp_path}/wt/sub/tmp"\n')
    r = _cli("root", "--repo", str(clone))
    assert r.returncode == 3
    assert "git work tree" in r.stderr


def test_root_under_a_dot_git_file_is_refused(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: /elsewhere\n")
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{tmp_path}/wt/tmp"\n')
    assert _cli("root", "--repo", str(clone)).returncode == 3


@pytest.mark.parametrize("value", [".", "./tmp", "scripts/x"])
def test_root_equal_to_or_inside_the_clone_is_refused(tmp_path, value):
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{value}"\n')
    r = _cli("root", "--repo", str(clone))
    assert r.returncode == 3
    assert "inside the clone" in r.stderr


def test_root_reached_through_a_symlink_into_a_work_tree_is_refused(tmp_path):
    (tmp_path / "wt" / ".git").mkdir(parents=True)
    (tmp_path / "link").symlink_to(tmp_path / "wt")
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{tmp_path}/link/tmp"\n')
    assert _cli("root", "--repo", str(clone)).returncode == 3


# ── H5: capitalised role dir names ──────────────────────────────────────────


def test_role_dirs_map_is_explicit():
    assert mod.ROLE_DIRS == {
        "worker": "Worker",
        "overseer": "Overseer",
        "human": "Human",
        "local": "Local",
    }


@pytest.mark.parametrize("role,name", sorted(mod.ROLE_DIRS.items()))
def test_resolve_prints_the_capitalised_role_dir(tmp_path, role, name):
    clone = _clone(tmp_path)
    r = _cli("resolve", "--repo", str(clone), "--role", role, "--create")
    assert r.returncode == 0, r.stderr
    root = Path(os.path.realpath(clone)).parent / ".tmp"
    assert r.stdout.strip() == str(root / name)
    assert sorted(p.name for p in root.iterdir()) == [name], "no lowercase sibling"


@pytest.mark.parametrize("role", ["Worker", "WORKER", "root", ""])
def test_a_capitalised_or_unknown_role_argument_is_a_usage_error(tmp_path, role):
    clone = _clone(tmp_path)
    r = _cli("resolve", "--repo", str(clone), "--role", role, "--create")
    assert r.returncode == 2
    assert not (Path(os.path.realpath(clone)).parent / ".tmp").exists()


# ── H3: --create ────────────────────────────────────────────────────────────


def test_create_makes_root_and_role_dir_0700(tmp_path):
    clone = _clone(tmp_path)
    r = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert r.returncode == 0, r.stderr
    role_dir = Path(r.stdout.strip())
    assert stat.S_IMODE(role_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(role_dir.parent.stat().st_mode) == 0o700


def test_resolve_without_create_creates_nothing(tmp_path):
    clone = _clone(tmp_path)
    r = _cli("resolve", "--repo", str(clone), "--role", "worker")
    assert r.returncode == 0
    assert not Path(r.stdout.strip()).parent.exists()


def test_create_tightens_an_open_role_dir_but_leaves_the_root_alone(tmp_path):
    clone = _clone(tmp_path)
    root = Path(os.path.realpath(clone)).parent / ".tmp"
    (root / "Worker").mkdir(parents=True)
    os.chmod(root, 0o755)
    os.chmod(root / "Worker", 0o755)
    assert _cli("resolve", "--repo", str(clone), "--role", "worker", "--create").returncode == 0
    assert stat.S_IMODE((root / "Worker").stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o755


def test_a_symlinked_root_is_refused(tmp_path):
    clone = _clone(tmp_path)
    (tmp_path / "real").mkdir()
    (tmp_path / "hos" / ".tmp").symlink_to(tmp_path / "real")
    r = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert r.returncode == 3
    assert "symlink" in r.stderr


def test_a_symlinked_role_dir_is_refused(tmp_path):
    clone = _clone(tmp_path)
    root = tmp_path / "hos" / ".tmp"
    root.mkdir()
    (tmp_path / "real").mkdir()
    (root / "Worker").symlink_to(tmp_path / "real")
    r = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert r.returncode == 3
    assert "symlink" in r.stderr


def test_a_role_dir_that_is_a_file_is_refused(tmp_path):
    clone = _clone(tmp_path)
    root = tmp_path / "hos" / ".tmp"
    root.mkdir()
    (root / "Worker").write_text("x")
    assert _cli("resolve", "--repo", str(clone), "--role", "worker", "--create").returncode == 3


# ── H4: never spawns a process ──────────────────────────────────────────────


def test_resolution_spawns_no_process(tmp_path, monkeypatch):
    clone = _clone(tmp_path)

    def boom(*_a, **_k):
        raise AssertionError("the resolver must not spawn a process")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    for name in ("system", "execv", "execve", "execvp", "execl", "execlp", "posix_spawn", "fork"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, boom)

    path = mod.resolve_role_dir(clone, "human", create=True)
    assert path.name == "Human" and path.is_dir()
    assert mod.main(["root", "--repo", str(clone)]) == 0
    assert "subprocess" not in vars(mod) and "os.system" not in _MOD_PATH.read_text()


# ── install-time helpers (used by scripts/framework/install.sh, I1) ─────────


def test_install_default_is_dot_tmp_when_a_sibling_clone_is_registered(tmp_path):
    target = tmp_path / "proj" / "Human"
    target.mkdir(parents=True)
    conf = tmp_path / "projects.conf"
    conf.write_text(f"p_config_dir=/x\np_worker_root={tmp_path}/proj/Worker\n")
    assert mod.install_default(target, "My App", conf) == "../.tmp"


def test_install_default_for_a_lone_clone_is_a_per_project_state_dir(tmp_path):
    target = tmp_path / "src" / "MyApp"
    target.mkdir(parents=True)
    conf = tmp_path / "projects.conf"
    conf.write_text(f"p_worker_root={tmp_path}/elsewhere/Worker\n")
    assert mod.install_default(target, "My App/2", conf) == "~/.local/state/hos/tmp/my-app-2"
    assert mod.install_default(target, "", tmp_path / "missing.conf") == (
        "~/.local/state/hos/tmp/project"
    )
