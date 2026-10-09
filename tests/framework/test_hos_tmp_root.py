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


@pytest.fixture(autouse=True)
def _private_registry(tmp_path, monkeypatch):
    """Never touch the real ~/.local/state/hos/tmp-roots.json."""
    monkeypatch.setenv("HOS_TMP_REGISTRY_FILE", str(tmp_path / "state" / "hos" / "tmp-roots.json"))


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(_MOD_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=child_env({"HOS_TMP_REGISTRY_FILE": os.environ["HOS_TMP_REGISTRY_FILE"]}),
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


@pytest.mark.parametrize("value", ["..", "../..", "/"])
def test_root_containing_the_clone_is_refused(tmp_path, value):
    """HOS_TMP_ROOT=".." would make the clone itself the role dir (and chmod it)."""
    clone = _clone(tmp_path, f'HOS_TMP_ROOT="{value}"\n')
    r = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "contains the clone" in r.stderr
    assert stat.S_IMODE(clone.stat().st_mode) != 0o700, "the clone must not be chmod-ed"


def test_an_unquoted_value_with_whitespace_is_rejected(tmp_path):
    clone = _clone(tmp_path, "HOS_TMP_ROOT=../a b\n")
    r = _cli("root", "--repo", str(clone))
    assert r.returncode == 3
    assert "whitespace" in r.stderr


def test_a_quoted_value_may_contain_whitespace(tmp_path):
    clone = _clone(tmp_path, 'HOS_TMP_ROOT="../a b"\n')
    assert mod.resolve_root(clone) == Path(os.path.realpath(clone)).parent / "a b"


def test_an_os_error_while_creating_exits_3_with_a_prefixed_line(tmp_path, monkeypatch, capsys):
    clone = _clone(tmp_path)

    def deny(*_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "listdir", deny)
    assert mod.main(["resolve", "--repo", str(clone), "--role", "worker", "--create"]) == 3
    assert capsys.readouterr().err.startswith("hos_tmp_root: ")


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


# ── check-dir (the inner loop's trust check on inherited directories) ───────


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    path.chmod(0o700)
    return path


def test_check_dir_accepts_a_private_dir_outside_the_clone(tmp_path):
    clone = _clone(tmp_path)
    d = _private_dir(tmp_path / "private")
    assert _cli("check-dir", "--repo", str(clone), "--dir", str(d)).returncode == 0


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o707])
def test_check_dir_rejects_an_open_dir(tmp_path, mode):
    clone = _clone(tmp_path)
    d = _private_dir(tmp_path / "open")
    d.chmod(mode)
    r = _cli("check-dir", "--repo", str(clone), "--dir", str(d))
    assert r.returncode == 3 and "0700" in r.stderr


def test_check_dir_rejects_a_symlink_a_file_and_a_missing_path(tmp_path):
    clone = _clone(tmp_path)
    real = _private_dir(tmp_path / "real")
    (tmp_path / "link").symlink_to(real)
    (tmp_path / "file").write_text("x")
    for target in (tmp_path / "link", tmp_path / "file", tmp_path / "missing"):
        r = _cli("check-dir", "--repo", str(clone), "--dir", str(target))
        assert r.returncode == 3, target


def test_check_dir_rejects_a_dir_inside_the_clone_even_via_a_symlink(tmp_path):
    clone = _clone(tmp_path)
    inside = _private_dir(clone / ".claudetmp" / "x")
    (tmp_path / "alias").symlink_to(inside)
    for target in (inside, tmp_path / "alias"):
        r = _cli("check-dir", "--repo", str(clone), "--dir", str(target))
        assert r.returncode == 3 and "inside the clone" in r.stderr, target


# ── Registry: the resolver never adopts or chmods a foreign project (security review) ──
def _worker_clone(tmp_path: Path, root: str | None = None) -> Path:
    return _clone(tmp_path, f'export HOS_TMP_ROOT="{root}"\n' if root else None)


def _registry() -> list[dict]:
    return mod.read_registry(mod.registry_path())


def _registered(role_dir: Path) -> bool:
    return mod.is_registered(role_dir, os.lstat(role_dir))


def test_creating_a_role_dir_registers_it_and_writes_the_informational_marker(tmp_path):
    clone = _worker_clone(tmp_path)
    role_dir = mod.resolve_role_dir(clone, "worker", create=True)
    assert _registered(role_dir)
    (entry,) = _registry()
    info = os.lstat(role_dir)
    assert entry == {
        "path": os.path.realpath(role_dir),
        "role": "Worker",
        "repo": os.path.realpath(clone),
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }
    reg = Path(mod.registry_path())
    assert stat.S_IMODE(reg.stat().st_mode) == 0o600 and reg.stat().st_uid == os.getuid()
    assert stat.S_IMODE(reg.parent.stat().st_mode) == 0o700
    marker = role_dir / ".hos-tmp-root"
    assert marker.read_text() == "hos-tmp-root v3 role=Worker\n", "informational, no secret"
    mod.resolve_role_dir(clone, "worker", create=True)
    assert len(_registry()) == 1, "idempotent"


def test_the_marker_holds_no_secret_and_the_nonce_code_is_gone():
    text = _MOD_PATH.read_text()
    assert "nonce" not in text.lower().split("exit codes: 0 ok")[1]
    assert not hasattr(mod, "ensure_nonce") and not hasattr(mod, "nonce_path")


def test_an_existing_empty_role_dir_is_adopted_chmodded_and_registered(tmp_path):
    clone = _worker_clone(tmp_path)
    root = tmp_path / "hos" / ".tmp"
    (root / "Worker").mkdir(parents=True, mode=0o755)
    os.chmod(root / "Worker", 0o755)
    mod.resolve_role_dir(clone, "worker", create=True)
    assert stat.S_IMODE((root / "Worker").stat().st_mode) == 0o700
    assert _registered(root / "Worker")


def test_an_existing_hos_only_role_dir_is_adopted(tmp_path):
    clone = _worker_clone(tmp_path)
    role = tmp_path / "hos" / ".tmp" / "Human"
    for name in (
        "pytest-of-scott",
        "tmpab12cd34",
        "claude-1000",
        "claude-http-77ed.sock",
        "srt-mux-1-0.sock",
        "garbage-hos-1234",
        "hos-inner-loop-x",
    ):
        (role / name).mkdir(parents=True)
    os.chmod(role, 0o755)
    mod.resolve_role_dir(clone, "human", create=True)
    assert _registered(role) and stat.S_IMODE(role.stat().st_mode) == 0o700


def test_b1_a_registered_role_dir_is_accepted_whatever_it_holds(tmp_path):
    """B1 PoC: the agent deletes its marker and keeps a non-HOS child. Re-resolve works and
    re-writes the marker; nothing about the dir's contents matters once it is registered."""
    clone = _worker_clone(tmp_path)
    role = mod.resolve_role_dir(clone, "worker", create=True)
    (role / ".hos-tmp-root").unlink()
    (role / "hog").mkdir()
    (role / ".git").mkdir()
    again = mod.resolve_role_dir(clone, "worker", create=True)
    assert again == role and (role / ".hos-tmp-root").exists()
    assert (role / "hog").is_dir()


def test_a_replaced_role_dir_must_pass_adoption_again(tmp_path):
    clone = _worker_clone(tmp_path)
    role = mod.resolve_role_dir(clone, "worker", create=True)
    role.rename(str(role) + ".old")  # keep the old inode alive so the new one differs
    role.mkdir(mode=0o700)
    (role / "src").mkdir()
    assert not _registered(role), "a new inode at the same path is not the registered dir"
    with pytest.raises(mod.TmpRootError, match="refusing to adopt"):
        mod.resolve_role_dir(clone, "worker", create=True)


def test_a_foreign_project_in_the_role_dir_is_refused_with_a_remedy_before_any_chmod(tmp_path):
    """The reviewer's PoC: config.sh points HOS_TMP_ROOT at another project."""
    foreign = tmp_path / "otherproj"
    for sub in (".git", "src", "docs"):
        (foreign / "Human" / sub).mkdir(parents=True)
    os.chmod(foreign / "Human", 0o755)
    clone = _worker_clone(tmp_path, str(foreign))
    result = _cli("resolve", "--repo", str(clone), "--role", "human", "--create")
    assert result.returncode == 3, result.stdout + result.stderr
    err = result.stderr
    assert "refusing to adopt" in err and "'.git'" in err and "'src'" in err and "'docs'" in err
    assert "Remedy:" in err and "move those entries out" in err and " mark --repo " in err
    assert "--reviewed" in err and len(err.strip().splitlines()) == 1, "one line, for the cron log"
    assert stat.S_IMODE((foreign / "Human").stat().st_mode) == 0o755, "no chmod"
    assert not (foreign / "Human" / ".hos-tmp-root").exists()
    assert not Path(mod.registry_path()).exists(), "nothing was registered"


def test_mark_reviewed_is_the_explicit_human_step(tmp_path):
    foreign = tmp_path / "otherproj"
    (foreign / "Human" / "src").mkdir(parents=True)
    clone = _worker_clone(tmp_path, str(foreign))
    assert _cli("mark", "--repo", str(clone), "--role", "human").returncode == 2  # needs --reviewed
    done = _cli("mark", "--repo", str(clone), "--role", "human", "--reviewed")
    assert done.returncode == 0, done.stderr
    assert _registered(foreign / "Human")


def test_an_hos_named_dir_that_holds_project_files_blocks_first_adoption(tmp_path):
    clone = _worker_clone(tmp_path)
    role = tmp_path / "hos" / ".tmp" / "Worker"
    (role / "tmp-project" / ".git").mkdir(parents=True)
    with pytest.raises(mod.TmpRootError, match="project files"):
        mod.resolve_role_dir(clone, "worker", create=True)
    assert not (role / ".hos-tmp-root").exists() and not Path(mod.registry_path()).exists()


def test_an_informational_marker_that_is_a_symlink_is_left_alone_and_grants_nothing(tmp_path):
    clone = _worker_clone(tmp_path)
    role = tmp_path / "hos" / ".tmp" / "Worker"
    role.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_text("keep\n")
    (role / ".hos-tmp-root").symlink_to(target)
    mod.resolve_role_dir(clone, "worker", create=True)
    assert (role / ".hos-tmp-root").is_symlink() and target.read_text() == "keep\n"
    assert _registered(role)


@pytest.mark.parametrize("breakage", ["symlink", "loose-mode", "malformed", "fifo"])
def test_an_unusable_registry_is_refused_not_replaced(tmp_path, breakage):
    clone = _worker_clone(tmp_path)
    reg = Path(mod.registry_path())
    reg.parent.mkdir(parents=True, mode=0o700)
    if breakage == "symlink":
        real = tmp_path / "real.json"
        real.write_text('{"version": 1, "entries": []}')
        os.chmod(real, 0o600)
        reg.symlink_to(real)
    elif breakage == "loose-mode":
        reg.write_text('{"version": 1, "entries": []}')
        os.chmod(reg, 0o644)
    elif breakage == "malformed":
        reg.write_text("{")
        os.chmod(reg, 0o600)
    else:
        os.mkfifo(reg)
    with pytest.raises(mod.TmpRootError):
        mod.resolve_role_dir(clone, "worker", create=True)
    assert not reg.is_file() or reg.read_text() in ("{", '{"version": 1, "entries": []}')


def test_concurrent_resolvers_never_corrupt_the_registry(tmp_path):
    clones = []
    for i in range(8):
        clone = tmp_path / f"c{i}" / "Worker"
        (clone / "scripts" / "framework").mkdir(parents=True)
        (clone / "scripts" / "framework" / "config.sh").write_text(
            f'export HOS_TMP_ROOT="{tmp_path}/root{i}"\n'
        )
        clones.append(clone)
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(_MOD_PATH),
                "resolve",
                "--repo",
                str(c),
                "--role",
                "worker",
                "--create",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env({"HOS_TMP_REGISTRY_FILE": os.environ["HOS_TMP_REGISTRY_FILE"]}),
        )
        for c in clones
    ]
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    entries = _registry()
    assert sorted(e["path"] for e in entries) == sorted(
        os.path.realpath(tmp_path / f"root{i}" / "Worker") for i in range(8)
    )
    assert not list(Path(mod.registry_path()).parent.glob("*.new.*")), "no temp files left"


# ── Registry growth bounds (security review R1) ─────────────────────────────────
def _repoint(clone: Path, root: Path) -> None:
    (clone / "scripts" / "framework").mkdir(parents=True, exist_ok=True)
    (clone / "scripts" / "framework" / "config.sh").write_text(f'export HOS_TMP_ROOT="{root}"\n')


def test_r1_growth_poc_one_repo_and_role_leaves_exactly_one_entry(tmp_path):
    """A prompt-injected cycle that rewrites HOS_TMP_ROOT to a new path every run."""
    clone = _worker_clone(tmp_path)
    for i in range(40):
        _repoint(clone, tmp_path / f"root{i}")
        mod.resolve_role_dir(clone, "worker", create=True, force_mark=True)  # mark --reviewed
    entries = _registry()
    assert len(entries) == 1
    assert entries[0]["path"] == os.path.realpath(tmp_path / "root39" / "Worker")
    assert entries[0]["repo"] == os.path.realpath(clone)


def test_r1_repointing_is_refused_without_reviewed_and_allowed_with_it(tmp_path):
    clone = _worker_clone(tmp_path)
    _repoint(clone, tmp_path / "rootA")
    first = mod.resolve_role_dir(clone, "worker", create=True)
    _repoint(clone, tmp_path / "rootB")
    result = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert result.returncode == 3, result.stdout + result.stderr
    err = result.stderr
    assert "refusing to re-point" in err and str(first) in err and "rootB" in err
    assert "Remedy:" in err and " mark --repo " in err and "--reviewed" in err
    assert len(err.strip().splitlines()) == 1, "one line, for the cron log"
    assert not (tmp_path / "rootB").exists(), "nothing was created at the new path"
    assert [e["path"] for e in _registry()] == [os.path.realpath(first)]
    done = _cli("mark", "--repo", str(clone), "--role", "worker", "--reviewed")
    assert done.returncode == 0, done.stderr
    assert [e["path"] for e in _registry()] == [os.path.realpath(tmp_path / "rootB" / "Worker")]


def test_r1_a_vanished_registered_dir_no_longer_blocks_repointing(tmp_path):
    import shutil

    clone = _worker_clone(tmp_path)
    _repoint(clone, tmp_path / "rootA")
    mod.resolve_role_dir(clone, "worker", create=True)
    shutil.rmtree(tmp_path / "rootA")
    _repoint(clone, tmp_path / "rootB")
    mod.resolve_role_dir(clone, "worker", create=True)  # the stale entry is pruned, not a conflict
    assert [e["path"] for e in _registry()] == [os.path.realpath(tmp_path / "rootB" / "Worker")]


def test_r1_stale_entries_are_pruned_on_each_registration(tmp_path):
    import shutil

    clones = []
    for i in range(3):
        clone = tmp_path / f"c{i}" / "Worker"
        _repoint(clone, tmp_path / f"root{i}")
        mod.resolve_role_dir(clone, "worker", create=True)
        clones.append(clone)
    assert len(_registry()) == 3
    shutil.rmtree(tmp_path / "root0")
    # replace root1's dir: same path, new inode
    (tmp_path / "root1" / "Worker").rename(tmp_path / "root1" / "Worker.old")
    (tmp_path / "root1" / "Worker").mkdir(mode=0o700)
    clone3 = tmp_path / "c3" / "Worker"
    _repoint(clone3, tmp_path / "root3")
    mod.resolve_role_dir(clone3, "worker", create=True)
    assert sorted(e["path"] for e in _registry()) == sorted(
        os.path.realpath(tmp_path / f"root{i}" / "Worker") for i in (2, 3)
    )


def _fill_registry(tmp_path: Path, count: int) -> None:
    entries = []
    for i in range(count):
        d = tmp_path / "full" / f"r{i}" / "Worker"
        d.mkdir(parents=True)
        info = d.stat()
        entries.append(
            {
                "path": os.path.realpath(d),
                "role": "Worker",
                "repo": os.path.realpath(d.parent),
                "st_dev": info.st_dev,
                "st_ino": info.st_ino,
            }
        )
    reg = Path(mod.registry_path())
    reg.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import json

    reg.write_text(json.dumps({"version": 1, "entries": entries}))
    os.chmod(reg, 0o600)


def test_r1_the_cap_is_a_distinct_error_and_a_full_registry_still_reads(tmp_path):
    _fill_registry(tmp_path, mod.REGISTRY_MAX_ENTRIES)
    assert len(_registry()) == mod.REGISTRY_MAX_ENTRIES, "a full registry is read normally"
    clone = _worker_clone(tmp_path)
    result = _cli("resolve", "--repo", str(clone), "--role", "worker", "--create")
    assert result.returncode == 3
    assert "registry-full" in result.stderr and "malformed" not in result.stderr
    assert "Remedy:" in result.stderr
    with pytest.raises(mod.RegistryFullError):
        mod.resolve_role_dir(clone, "worker", create=True)
    # an already registered dir keeps resolving; only NEW keys are refused
    existing = Path(_registry()[0]["path"])
    assert _registered(existing)


def test_r1_replacing_an_existing_key_works_at_the_cap(tmp_path):
    _fill_registry(tmp_path, mod.REGISTRY_MAX_ENTRIES - 1)
    clone = _worker_clone(tmp_path)
    mod.resolve_role_dir(clone, "worker", create=True)  # the 256th key fits
    assert len(_registry()) == mod.REGISTRY_MAX_ENTRIES
    mod.resolve_role_dir(clone, "worker", create=True)  # same key again: still fine
    assert len(_registry()) == mod.REGISTRY_MAX_ENTRIES


def test_r1_v1_entries_without_repo_are_read_and_migrated_on_the_next_write(tmp_path):
    import json

    clone = _worker_clone(tmp_path)
    role = tmp_path / "hos" / ".tmp" / "Worker"
    role.mkdir(parents=True, mode=0o700)
    info = role.stat()
    reg = Path(mod.registry_path())
    reg.parent.mkdir(parents=True, mode=0o700)
    legacy = {
        "path": os.path.realpath(role),
        "role": "Worker",
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }
    reg.write_text(json.dumps({"version": 1, "entries": [legacy]}))
    os.chmod(reg, 0o600)
    assert _registry() == [legacy] and _registered(role)
    mod.resolve_role_dir(clone, "worker", create=True)  # registered: accepted, no rewrite needed
    mod.register(role, clone, "worker")  # the next write migrates it
    (entry,) = _registry()
    assert entry["repo"] == os.path.realpath(clone) and entry["path"] == legacy["path"]


def test_r1_an_entry_whose_repo_dir_vanished_is_pruned(tmp_path):
    import shutil

    shared = tmp_path / "shared-root"
    stale = tmp_path / "wt1" / "Worker"
    live = tmp_path / "wt2" / "Worker"
    for clone in (stale, live):
        _repoint(clone, shared)
        mod.resolve_role_dir(clone, "worker", create=True, force_mark=True)
    # both worktrees share one live role dir, but each registration replaced the other's key
    assert len(_registry()) == 1
    other = tmp_path / "wt3" / "Overseer"
    _repoint(other, shared)
    mod.resolve_role_dir(other, "overseer", create=True)
    assert len(_registry()) == 2
    shutil.rmtree(tmp_path / "wt3")  # the worktree is gone; its role dir (shared) is not
    newcomer = tmp_path / "wt4" / "Human"
    _repoint(newcomer, shared)
    mod.resolve_role_dir(newcomer, "human", create=True)  # any registration prunes
    assert sorted(e["role"] for e in _registry()) == ["Human", "Worker"], "stale key pruned"


def test_r1_a_write_that_would_exceed_the_read_cap_is_refused_as_registry_full(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mod, "REGISTRY_MAX_BYTES", 900)
    refused = None
    for i in range(10):
        clone = tmp_path / f"c{i}" / "Worker"
        _repoint(clone, tmp_path / f"root{i}")
        try:
            mod.resolve_role_dir(clone, "worker", create=True)
        except mod.RegistryFullError as exc:
            refused = str(exc)
            break
    assert refused and "registry-full" in refused and "would exceed 900 bytes" in refused
    assert "Remedy:" in refused and "malformed" not in refused
    assert 0 < len(_registry()) < 10, "what was written stays readable"
