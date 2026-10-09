"""bin/hos-human exports the per-role disk temp dir (#2054 S2a, TD section 2A.3, L2).

The static test pins the ordering the design requires: the export comes after
the token mint (so the short-lived token temp file stays on the RAM-backed /tmp)
and before ``exec claude``. The behavioural tests run the real launcher in a
throwaway repo with every collaborator stubbed, and read back the environment
the launched ``claude`` sees. That is the evidence that sandboxed Bash gets
``CLAUDE_CODE_TMPDIR`` (Claude Code replaces the exported TMPDIR with it).
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

ROOT = Path(__file__).resolve().parents[2]
HOS_HUMAN = ROOT / "bin" / "hos-human"
RESOLVER = ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"


def _code_only(path: Path) -> str:
    return "\n".join(
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_l2_the_export_comes_after_the_token_mint_and_before_exec():
    code = _code_only(HOS_HUMAN)
    mint = code.index("get_app_token.sh")
    resolve = code.index("hos_tmp_root.py")
    exports = [
        code.index(name) for name in ("export TMPDIR=", "CLAUDE_CODE_TMPDIR=", "HOS_TMP_DIR=")
    ]
    launch = code.index("exec claude")
    assert mint < resolve < min(exports) and max(exports) < launch


def test_l2_the_resolver_is_called_with_the_human_role_and_create():
    code = _code_only(HOS_HUMAN)
    assert "resolve" in code and "--role human" in code and "--create" in code


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class _Launcher:
    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.parent = tmp_path / "hos"
        self.repo = self.parent / "Human"
        self.claude_env = tmp_path / "claude_env.txt"
        self.token_dir = tmp_path / "tokendir"
        self.token_dir.mkdir()
        self.token_listing = tmp_path / "token_listing.txt"
        fakebin = tmp_path / "fakebin"

        (self.repo / "bin").mkdir(parents=True)
        shutil.copy(HOS_HUMAN, self.repo / "bin" / "hos-human")
        (self.repo / "bootstrap" / "lib").mkdir(parents=True)
        shutil.copy(RESOLVER, self.repo / "bootstrap" / "lib" / "hos_tmp_root.py")
        _write_exec(self.repo / "bootstrap" / "validate_setup.sh", "#!/usr/bin/env bash\nexit 0\n")
        _write_exec(
            self.repo / "bootstrap" / "get_app_token.sh",
            "#!/usr/bin/env bash\n"
            'echo "export HOS_BOT_LOGIN=bot[bot]"\n'
            'echo "export HOS_EXPECTED_BOT_LOGIN=bot[bot]"\n'
            'echo "export GH_TOKEN=fake"\n',
        )
        _write_exec(self.repo / "bootstrap" / "hos_repo_sync.sh", "#!/usr/bin/env bash\nexit 0\n")
        (self.parent / ".config" / "hos").mkdir(parents=True)
        (self.parent / ".config" / "hos" / "apps.env").write_text("# stub\n")
        _write_exec(
            fakebin / "claude",
            "#!/usr/bin/env bash\n"
            f'echo "TMPDIR=${{TMPDIR-UNSET}}" > "{self.claude_env}"\n'
            f'echo "CLAUDE_CODE_TMPDIR=${{CLAUDE_CODE_TMPDIR-UNSET}}" >> "{self.claude_env}"\n'
            f'echo "HOS_TMP_DIR=${{HOS_TMP_DIR-UNSET}}" >> "{self.claude_env}"\n'
            f'ls -A "{self.token_dir}" > "{self.token_listing}"\n',
        )
        self.fakebin = fakebin
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def run(self) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.fakebin}:/usr/bin:/bin",
            # hos-human's mktemp (the token file) lands here, before TMPDIR moves.
            "TMPDIR": str(self.token_dir),
        }
        return subprocess.run(
            ["bash", str(self.repo / "bin" / "hos-human")],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=child_env(env),
        )

    def seen(self) -> dict[str, str]:
        out = {}
        for line in self.claude_env.read_text().splitlines():
            key, _, value = line.partition("=")
            out[key] = value
        return out


@pytest.fixture
def launcher(tmp_path):
    return _Launcher(tmp_path)


def test_l2_the_launched_session_gets_all_three_variables(launcher):
    r = launcher.run()
    assert r.returncode == 0, r.stdout + r.stderr
    expected = str(launcher.parent / ".tmp" / "Human")
    assert launcher.seen() == {
        "TMPDIR": expected,
        "CLAUDE_CODE_TMPDIR": expected,
        "HOS_TMP_DIR": expected,
    }
    assert (Path(expected).stat().st_mode & 0o777) == 0o700


def test_l2_a_resolver_failure_warns_and_still_starts_the_session(launcher):
    _write_exec(
        launcher.repo / "bootstrap" / "lib" / "hos_tmp_root.py",
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stderr.write('hos_tmp_root: stubbed failure\\n')\nsys.exit(3)\n",
    )
    r = launcher.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HOS tmp root unusable (stubbed failure)" in r.stderr
    seen = launcher.seen()
    assert seen["CLAUDE_CODE_TMPDIR"] == "UNSET" and seen["HOS_TMP_DIR"] == "UNSET"
    assert not seen["TMPDIR"].endswith("/.tmp/Human")


def test_the_token_file_is_removed_before_claude_starts(launcher):
    """The EXIT trap does not fire across `exec claude`, so the launcher must
    remove the sourced token file itself or it stays in the temp dir."""
    r = launcher.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert launcher.token_listing.read_text() == "", "token temp file left behind"
