"""Tests for the --human sandbox-policy generation wiring in hos_install.sh
and its supporting library, bootstrap/lib/sandbox_paths.sh (#1221, item 1).

Two layers:

  (a) Library unit tests — call the two pure helper functions
      (_hos_claude_project_state, _hos_path_is_ancestor_or_equal) directly by
      sourcing bootstrap/lib/sandbox_paths.sh in a bash subshell (mirrors the
      pattern in tests/automation/test_branch_ownership.py's `_verify`).

  (b) Install-wiring tests — drive `bootstrap/hos_install.sh --local` against
      throwaway git-initialised target repos (mirrors
      tests/framework/test_install_role_flags.py / test_pack_install.py).

The install-wiring tests that exercise the charset-sensitive path derivation
(_hos_claude_project_state's `[A-Za-z0-9/-]` guard) use a target root built
with tempfile.mkdtemp() directly under /tmp (letters/digits only — no
underscore, no dot) rather than pytest's default tmp_path, whose per-test
directory names contain underscores from the test function name and would
otherwise make --claude-project-state fail to derive for reasons unrelated to
what each test is checking.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "bootstrap" / "hos_install.sh"
LIB = REPO_ROOT / "bootstrap" / "lib" / "sandbox_paths.sh"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _call_lib_func(func: str, *args: str) -> subprocess.CompletedProcess:
    """Source the library and call one function with the given args, printing
    its stdout followed by `rc=<code>` on the next line."""
    quoted = " ".join(f'"{a}"' for a in args)
    script = (
        f'source "{LIB}"\n'
        f"out=$({func} {quoted})\n"
        "rc=$?\n"
        'printf "%s\\n" "$out"\n'
        'printf "rc=%s\\n" "$rc"\n'
    )
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, timeout=10, check=False,
    )


def _git(repo: Path, *args, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, check=check,
    )


def _git_init_target(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root.parent, "init", "--quiet", str(root))
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    return root


def _run_installer(
    target: Path,
    extra_args: list,
    env_overrides: dict | None = None,
    input_str: str = "\n",
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    """Run hos_install.sh --local --no-pack against target.

    HOS_NO_CONFIG=1 suppresses the interactive config sub-invocation and
    (elsewhere in the installer) other interactive prompts; the sandbox-policy
    block itself gates its own prompt on stdin being a tty, which a subprocess
    never is, so passing HOS_NO_CONFIG=1 is belt-and-braces consistency with
    the other install-wiring test files, not load-bearing for this block.
    """
    cmd = [
        "bash",
        str(INSTALLER),
        "--local",
        "--no-pack",
        str(target),
        *extra_args,
    ]
    env = {**os.environ, "HOS_NO_CONFIG": "1"}
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input=input_str,
        timeout=timeout,
    )


@pytest.fixture
def clean_root():
    """A temp root under /tmp built with letters/digits only (no underscore,
    no dot) so paths derived under it satisfy sandbox_paths.sh's
    [A-Za-z0-9/-] charset guard. Removed on teardown.

    tempfile.mkdtemp()'s own random suffix draws from
    "abcdefghijklmnopqrstuvwxyz0123456789_" — it includes the underscore this
    fixture exists to avoid, so it cannot be used directly here (it produced
    a ~1-in-5 flaky failure in exactly this suite before this fix). Build the
    suffix from a letters+digits-only alphabet instead.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    suffix = "".join(secrets.choice(alphabet) for _ in range(12))
    d = Path("/tmp") / f"hossbx{suffix}"
    d.mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# (a) library unit tests
# --------------------------------------------------------------------------- #


class TestClaudeProjectState:
    def test_happy_path(self):
        r = _call_lib_func("_hos_claude_project_state", "/h", "/a/b/c")
        assert "rc=0" in r.stdout
        assert "/h/.claude/projects/-a-b-c" in r.stdout

    def test_trailing_slash_on_both_args(self):
        r = _call_lib_func("_hos_claude_project_state", "/h/", "/a/b/c/")
        assert "rc=0" in r.stdout
        assert "/h/.claude/projects/-a-b-c" in r.stdout

    def test_empty_home_rc1(self):
        r = _call_lib_func("_hos_claude_project_state", "", "/a/b/c")
        assert "rc=1" in r.stdout
        assert "-a-b-c" not in r.stdout

    def test_unset_home_rc1(self):
        script = (
            f'source "{LIB}"\n'
            'unset HOS_TEST_HOME\n'
            'out=$(_hos_claude_project_state "$HOS_TEST_HOME" "/a/b/c")\n'
            'rc=$?\n'
            'printf "%s\\nrc=%s\\n" "$out" "$rc"\n'
        )
        r = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=10)
        assert "rc=1" in r.stdout

    @pytest.mark.parametrize(
        "repo",
        ["/a.b/c", "/a_b/c", "/a b/c"],
        ids=["dot", "underscore", "space"],
    )
    def test_repo_with_disallowed_char_rc1(self, repo):
        r = _call_lib_func("_hos_claude_project_state", "/h", repo)
        assert "rc=1" in r.stdout, f"expected rc=1 for repo={repo!r}, got: {r.stdout!r}"

    def test_relative_repo_rc1(self):
        r = _call_lib_func("_hos_claude_project_state", "/h", "a/b/c")
        assert "rc=1" in r.stdout


class TestPathIsAncestorOrEqual:
    def test_equal_paths(self):
        r = _call_lib_func("_hos_path_is_ancestor_or_equal", "/a/b", "/a/b")
        assert "rc=0" in r.stdout

    def test_true_prefix(self):
        r = _call_lib_func("_hos_path_is_ancestor_or_equal", "/a", "/a/b")
        assert "rc=0" in r.stdout

    def test_non_prefix_similarly_named_sibling(self):
        """/a/bc is NOT an ancestor of /a/b — a naive string-prefix check
        (without the trailing '/') would wrongly say it is."""
        r = _call_lib_func("_hos_path_is_ancestor_or_equal", "/a/bc", "/a/b")
        assert "rc=1" in r.stdout


# --------------------------------------------------------------------------- #
# (b) install-wiring tests
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_dry_run_human_no_files_no_prompt(tmp_path):
    target = _git_init_target(tmp_path / "target")
    r = _run_installer(target, ["--dry-run", "--human"])
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "Would generate" in combined and "settings.local.json" in combined
    assert not (target / ".claude" / "settings.local.json").exists()
    assert not (target / ".claude" / "hos-sandbox.values").exists()
    assert "Handoff directory for this Human clone" not in combined


@pytest.mark.slow
def test_worker_role_sandbox_block_never_appears(tmp_path):
    target = _git_init_target(tmp_path / "target")
    r = _run_installer(target, ["--worker"])
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "sandbox policy" not in combined.lower()
    assert not (target / ".claude" / "settings.local.json").exists()
    assert not (target / ".claude" / "hos-sandbox.values").exists()


@pytest.mark.slow
def test_preexisting_settings_local_left_untouched(tmp_path):
    target = _git_init_target(tmp_path / "target")
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    sentinel = b'{"SENTINEL": "do-not-touch-1221"}\n'
    live = claude_dir / "settings.local.json"
    live.write_bytes(sentinel)

    r = _run_installer(target, ["--human"])
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr

    assert live.read_bytes() == sentinel, "pre-existing settings.local.json was modified"
    assert "left untouched" in combined
    assert "Handoff directory for this Human clone" not in combined
    assert not (claude_dir / "hos-sandbox.values").exists()


@pytest.mark.slow
def test_non_interactive_no_handoff_warns_and_writes_nothing(tmp_path):
    target = _git_init_target(tmp_path / "target")
    r = _run_installer(target, ["--human"])
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr

    assert "Sandbox policy NOT generated" in combined
    assert "gen_sandbox_config.py --role human --clone-dir" in combined
    assert not (target / ".claude" / "settings.local.json").exists()
    assert not (target / ".claude" / "hos-sandbox.values").exists()


@pytest.mark.slow
def test_happy_path_generates_policy_and_check_passes(clean_root):
    target = _git_init_target(clean_root / "target")
    home = clean_root / "home"
    handoff = clean_root / "handoff"

    r = _run_installer(
        target,
        ["--human"],
        env_overrides={"HOME": str(home), "HOS_HANDOFF_DIR": str(handoff)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "Sandbox policy generated" in combined

    live = target / ".claude" / "settings.local.json"
    values = target / ".claude" / "hos-sandbox.values"
    assert live.exists(), "settings.local.json not written"
    assert values.exists(), "hos-sandbox.values not written"

    live_text = live.read_text()
    doc = json.loads(live_text)
    assert isinstance(doc, dict)
    surviving = re.findall(r"__[A-Z][A-Z0-9_]*__", live_text)
    assert surviving == [], f"surviving placeholder(s) in generated policy: {surviving}"

    check = subprocess.run(
        [
            "python3", str(REPO_ROOT / "scripts" / "framework" / "gen_sandbox_config.py"),
            "--role", "human", "--clone-dir", str(target), "--check",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.slow
def test_charset_guard_dot_in_target_path_falls_back_to_warn(clean_root):
    target = _git_init_target(clean_root / "tgt.v2")
    home = clean_root / "home"
    handoff = clean_root / "handoff"

    r = _run_installer(
        target,
        ["--human"],
        env_overrides={"HOME": str(home), "HOS_HANDOFF_DIR": str(handoff)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr

    assert "Could not derive --claude-project-state" in combined
    assert "Sandbox policy generated" not in combined
    assert not (target / ".claude" / "settings.local.json").exists()
    assert not (target / ".claude" / "hos-sandbox.values").exists()


@pytest.mark.slow
class TestHandoffValidation:
    def _assert_rejected(self, clean_root, handoff_value):
        target = _git_init_target(clean_root / "target")
        home = clean_root / "home"

        r = _run_installer(
            target,
            ["--human"],
            env_overrides={"HOME": str(home), "HOS_HANDOFF_DIR": handoff_value},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert not (target / ".claude" / "settings.local.json").exists()
        assert not (target / ".claude" / "hos-sandbox.values").exists()
        return r.stdout + r.stderr

    def test_rejects_home(self, clean_root):
        home = clean_root / "home"
        target = _git_init_target(clean_root / "target")
        r = _run_installer(
            target,
            ["--human"],
            env_overrides={"HOME": str(home), "HOS_HANDOFF_DIR": str(home)},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Refusing handoff dir" in (r.stdout + r.stderr)
        assert not (target / ".claude" / "settings.local.json").exists()

    def test_rejects_root(self, clean_root):
        combined = self._assert_rejected(clean_root, "/")
        assert "must be an absolute path" in combined

    def test_rejects_clone_parent_dir(self, clean_root):
        # clean_root itself is the parent of clean_root/target, i.e. HOS_ROOT.
        combined = self._assert_rejected(clean_root, str(clean_root))
        assert "Refusing handoff dir" in combined

    def test_rejects_relative_path(self, clean_root):
        combined = self._assert_rejected(clean_root, "relative/handoff")
        assert "must be an absolute path" in combined


@pytest.mark.slow
def test_failing_generator_does_not_abort_install(clean_root):
    """A generator that fails must not abort the rest of the install — a
    later installer artifact (.hos-release) must still be written. The
    target-first lookup in the sandbox-policy block lets a stub placed at
    <target>/scripts/framework/gen_sandbox_config.py take precedence over the
    real one in HOS_SOURCE, so this needs no changes to the real repo."""
    target = _git_init_target(clean_root / "target")
    home = clean_root / "home"
    handoff = clean_root / "handoff"

    stub_dir = target / "scripts" / "framework"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "gen_sandbox_config.py").write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n"
    )
    contract_dir = target / "contract"
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "sandbox-policy.template.json").write_text("{}\n")

    r = _run_installer(
        target,
        ["--human"],
        env_overrides={"HOME": str(home), "HOS_HANDOFF_DIR": str(handoff)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr

    assert "Sandbox policy generation failed" in combined
    assert not (target / ".claude" / "settings.local.json").exists()
    assert (target / ".hos-release").exists(), (
        "a stub generator failure must not abort the rest of the install"
    )
