"""Tests for bootstrap/merge_authority.sh token handling (#2117).

Runs the real wrapper and the real bootstrap/revoke_app_token.sh against a
tmp repo tree with a stubbed get_app_token.sh, a stubbed
scripts/automation/merge_authority_cli.py and a stubbed curl on PATH. The
wrapper must revoke only a token it minted itself: an installation token
inherited from the caller (e.g. the cron cycle's own) is never revoked, and a
failed mint never falls back to the inherited identity. No network access.
"""

import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
MERGE_AUTHORITY_SH = REPO_ROOT / "bootstrap" / "merge_authority.sh"

INHERITED_TOKEN = "inherited-token-must-survive"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
"""

# Stands in for the real CLI: prints exactly one JSON object, exits with
# CLI_EXIT, and records whether GH_TOKEN / HOS_BOT_LOGIN reached it.
CLI_STUB = """import json
import os
import sys
import time

cfg = os.environ.get("GH_CONFIG_DIR")
with open(os.environ["CAPTURE_FILE"], "a") as f:
    f.write("CLI_GH_TOKEN:" + os.environ.get("GH_TOKEN", "<unset>") + "\\n")
    f.write("CLI_HOS_BOT_LOGIN:" + os.environ.get("HOS_BOT_LOGIN", "<unset>") + "\\n")
    f.write("CLI_GH_CONFIG_DIR:" + (cfg or "<unset>") + "\\n")
    if cfg and os.path.isdir(cfg):
        f.write("CLI_GH_CONFIG_DIR_ENTRIES:" + str(len(os.listdir(cfg))) + "\\n")
time.sleep(float(os.environ.get("CLI_SLEEP", "0")))
print(json.dumps({"stub": True, "argv": sys.argv[1:]}))
sys.exit(int(os.environ.get("CLI_EXIT", "0")))
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
printf '204'
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.repo_root = tmp_path / "repo"
        bdir = self.repo_root / "bootstrap"
        bdir.mkdir(parents=True)
        shutil.copy(MERGE_AUTHORITY_SH, bdir / "merge_authority.sh")
        shutil.copy(REPO_ROOT / "bootstrap" / "revoke_app_token.sh", bdir / "revoke_app_token.sh")
        _write_exec(bdir / "get_app_token.sh", GET_APP_TOKEN_STUB)

        cli_dir = self.repo_root / "scripts" / "automation"
        cli_dir.mkdir(parents=True)
        (cli_dir / "merge_authority_cli.py").write_text(CLI_STUB)

        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

    def run(self, args, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [BASH, str(self.repo_root / "bootstrap" / "merge_authority.sh"), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=child_env(env),
        )

    def capture(self) -> str:
        return self.capture_file.read_text()

    def revoke_calls(self) -> list:
        return [
            line
            for line in self.capture().splitlines()
            if line.startswith("CURL_CALLED_WITH") and "installation/token" in line
        ]


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_inherited_token_not_revoked_on_local_only_subcommand(h):
    result = h.run(
        ["register", "--app", "overseer", "--step", "3"],
        env_overrides={"GH_TOKEN": INHERITED_TOKEN},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert h.revoke_calls() == []
    # Non-minting invocations leave the inherited environment untouched.
    assert f"CLI_GH_TOKEN:{INHERITED_TOKEN}" in cap


def test_inherited_token_not_revoked_on_non_minting_app(h):
    result = h.run(
        ["gate", "--app", "bogus"],
        env_overrides={"GH_TOKEN": INHERITED_TOKEN},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert h.revoke_calls() == []
    assert f"CLI_GH_TOKEN:{INHERITED_TOKEN}" in cap


def test_failed_mint_neither_revokes_nor_exposes_inherited_identity(h):
    result = h.run(
        ["gate", "--app", "overseer"],
        env_overrides={
            "FAIL_TOKEN_MINT": "1",
            "GH_TOKEN": INHERITED_TOKEN,
            "HOS_BOT_LOGIN": "inherited-bot[bot]",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "failed to mint" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    assert h.revoke_calls() == []
    assert "CLI_GH_TOKEN:<unset>" in cap
    assert "CLI_HOS_BOT_LOGIN:<unset>" in cap
    assert INHERITED_TOKEN not in cap
    # gh must not fall back to the host's stored login: it gets an empty
    # config dir, which the wrapper removes on exit.
    dirs = {
        line.split(":", 1)[1] for line in cap.splitlines() if line.startswith("CLI_GH_CONFIG_DIR:")
    }
    assert len(dirs) == 1 and "<unset>" not in dirs, cap
    assert "CLI_GH_CONFIG_DIR_ENTRIES:0" in cap
    assert not Path(dirs.pop()).exists()


def test_successful_mint_revokes_exactly_the_minted_token(h):
    result = h.run(
        ["gate", "--app", "overseer"],
        env_overrides={"GH_TOKEN": INHERITED_TOKEN},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    calls = h.revoke_calls()
    assert len(calls) == 1, cap
    # Through revoke_app_token.sh, not an inline `curl -sf -X DELETE`.
    assert "-o /dev/null -w %{http_code}" in calls[0]
    assert "Authorization: token fake-token-overseer" in calls[0]
    assert INHERITED_TOKEN not in cap
    assert "CLI_GH_TOKEN:fake-token-overseer" in cap
    assert "CLI_GH_CONFIG_DIR:<unset>" in cap


def test_sigterm_mid_flight_revokes_minted_token_exactly_once(h):
    env = {
        "PATH": f"{h.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "CAPTURE_FILE": str(h.capture_file),
        "HOME": str(h.tmp / "home"),
        "CLI_SLEEP": "5",
    }
    proc = subprocess.Popen(
        [BASH, str(h.repo_root / "bootstrap" / "merge_authority.sh"), "gate", "--app", "overseer"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env(env),
        start_new_session=True,
    )
    try:
        waited = 0.0
        while waited < 10.0:
            if "CLI_GH_TOKEN:" in h.capture():
                break
            time.sleep(0.1)
            waited += 0.1
        else:
            proc.kill()
            pytest.fail("CLI never started within the poll deadline")
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert proc.returncode == -signal.SIGTERM, (proc.returncode, proc.stderr.read())
    calls = h.revoke_calls()
    assert len(calls) == 1, h.capture()
    assert "Authorization: token fake-token-overseer" in calls[0]


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_stdout_and_exit_code_pass_through_unchanged(h, exit_code):
    result = h.run(
        ["gate", "--app", "overseer", "--repo", "o/r"],
        env_overrides={"CLI_EXIT": str(exit_code)},
    )
    assert result.returncode == exit_code, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    assert json.loads(lines[0]) == {
        "stub": True,
        "argv": ["gate", "--app", "overseer", "--repo", "o/r"],
    }


# ── #2209 S1a x #2213 union: mint policy pinned against the CLI ─────────────

_NETWORK_SUBCOMMANDS = (
    "gate",
    "human-approval",
    "hold-directive",
    "protected-surface",
    "security-surface",
    "codeowners",
    "approval-merge",
    "merge-provenance",
)


def _wrapper_mint_arms() -> set:
    """Subcommand tokens named in the wrapper's mint `case` arms."""
    import re

    text = MERGE_AUTHORITY_SH.read_text()
    block = text.split("MINT_TOKEN=false", 1)[1].split("esac\n", 3)
    body = "".join(block[:3])
    arms = set()
    for m in re.finditer(r"^\s{4}([a-z|-]+)\)\s*$", body, re.M):
        arms.update(m.group(1).split("|"))
    return arms


def test_wrapper_mint_arms_equal_cli_network_subcommands():
    from scripts.automation import merge_authority_cli as cli

    arms = _wrapper_mint_arms()
    assert arms == set(cli.NETWORK_SUBCOMMANDS), (arms ^ set(cli.NETWORK_SUBCOMMANDS))


@pytest.mark.parametrize("sub", ["register", "bounce-count"])
def test_local_only_subcommands_never_mint(h, sub):
    h.run([sub, "--app", "overseer"])
    assert "GET_APP_TOKEN_CALLED_WITH" not in h.capture()


@pytest.mark.parametrize("sub", _NETWORK_SUBCOMMANDS)
@pytest.mark.parametrize("role", ["worker", "overseer", "human"])
def test_read_subcommands_mint_for_every_known_role(h, sub, role):
    h.run([sub, "--app", role])
    assert f"GET_APP_TOKEN_CALLED_WITH:--app {role}" in h.capture()


@pytest.mark.parametrize("sub", ["route", "bounce"])
def test_mutation_subcommands_mint_only_for_overseer(h, sub):
    h.run([sub, "--app", "overseer"])
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in h.capture()


@pytest.mark.parametrize("sub", ["route", "bounce"])
@pytest.mark.parametrize("role", ["worker", "human", "bogus"])
def test_mutation_subcommands_do_not_mint_for_other_roles(h, sub, role):
    h.run([sub, "--app", role])
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert h.revoke_calls() == []


@pytest.mark.parametrize("sub", ["route", "bounce", "gate"])
def test_equals_form_app_mints_like_space_form(h, sub):
    h.run([sub, "--app=overseer"])
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    assert len(h.revoke_calls()) == 1, cap


def test_equals_form_non_overseer_mutation_does_not_mint(h):
    h.run(["route", "--app=worker"])
    assert "GET_APP_TOKEN_CALLED_WITH" not in h.capture()


def test_repeated_app_last_value_wins_for_minting(h):
    h.run(["route", "--app", "worker", "--app", "overseer"])
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in h.capture()
    (h.tmp / "second").mkdir()
    h2 = Harness(h.tmp / "second")
    h2.run(["route", "--app", "overseer", "--app=worker"])
    assert "GET_APP_TOKEN_CALLED_WITH" not in h2.capture()
