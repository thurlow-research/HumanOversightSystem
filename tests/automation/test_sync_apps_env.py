"""
Tests for bootstrap/sync_apps_env.sh — apps.env gap-fill (#957 ask 3).

Background: a `hos_install.sh --pr` upgrade merges through git cleanly, but
cannot carry gitignored local config (.config/hos/apps.env). A release that
introduces a new apps.env key leaves every existing role checkout silently
missing it until something deep in get_app_token.sh crashes on an unbound
variable. This script fills the gap: any key present in
bootstrap/apps.env.template but absent from the target apps.env gets added —
verbatim if the template value is a real default/computed reference, or
prompted for (interactive) / taken from an identically-named env var
(--non-interactive) if the template value is a "<PLACEHOLDER>".

Strategy
--------
Run the real script via subprocess against a real temp apps.env and the
real bootstrap/apps.env.template shipped in this repo — no stubs needed,
this is pure bash + coreutils.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

BOOTSTRAP_DIR = Path(__file__).parent.parent.parent / "bootstrap"
SCRIPT = BOOTSTRAP_DIR / "sync_apps_env.sh"
TEMPLATE = BOOTSTRAP_DIR / "apps.env.template"


def _run(config_dir, args=(), env_extra=None, input_text=None):
    env = dict(os.environ)
    env["HOME"] = str(config_dir.parent)  # keep unrelated HOME out of the way
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [BASH, str(SCRIPT), "--config-dir", str(config_dir), *args],
        capture_output=True, text=True, timeout=30, check=False,
        env=env, input=input_text,
    )


def _write_apps_env(config_dir: Path, body: str) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    apps_env = config_dir / "apps.env"
    apps_env.write_text(body)
    apps_env.chmod(0o600)
    return apps_env


MINIMAL_BODY = (
    'HOS_REPO_OWNER="my-org"\n'
    'HOS_WORKER_APP_ID="123"\n'
    'HOS_WORKER_PEM="/x/worker.pem"\n'
    'HOS_WORKER_BOT_LOGIN="hos-worker-x[bot]"\n'
)


@pytest.fixture
def config_dir(tmp_path):
    return tmp_path / "config" / "hos"


class TestGapFill:
    def test_missing_file_errors_with_guidance(self, config_dir, tmp_path):
        config_dir.mkdir(parents=True)
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 1
        assert "hos_setup_partner.sh" in r.stderr

    def test_wrong_permissions_rejected(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        apps_env.chmod(0o644)
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 1
        assert "expected 600" in r.stderr

    def test_never_overwrites_an_existing_key(self, config_dir):
        # A pre-existing (even non-default) value for a template key must
        # survive untouched — the script only appends genuinely missing keys.
        body = MINIMAL_BODY + 'OVERSEER_CEILING="HIGH"\n'
        apps_env = _write_apps_env(config_dir, body)
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 0, r.stdout + r.stderr
        text = apps_env.read_text()
        assert text.count("OVERSEER_CEILING=") == 1
        assert 'OVERSEER_CEILING="HIGH"' in text

    def test_real_default_and_computed_values_filled_without_prompting(self, config_dir):
        # Keys whose template value has no "<...>" placeholder (a real
        # default like OVERSEER_CEILING, or a ${VAR} computed reference like
        # BOT_WORKER_USERNAME) are appended verbatim, no interaction needed.
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 0, r.stdout + r.stderr
        text = apps_env.read_text()
        assert 'OVERSEER_CEILING="LOW"' in text
        assert 'COPILOT_BOT_LOGIN="copilot[bot]"' in text
        assert 'TIER_CEILING_CHECK_NAME="require-tier-ceiling"' in text
        # Computed reference carried through unexpanded (resolved later, at
        # the point this file is `source`d, not at gap-fill time).
        assert 'BOT_WORKER_USERNAME="${HOS_WORKER_BOT_LOGIN}"' in text

    def test_placeholder_key_takes_env_var_override_non_interactive(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r = _run(
            config_dir,
            args=["--non-interactive"],
            env_extra={"HUMAN_REVIEWER": "SomeReviewer"},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'HUMAN_REVIEWER="SomeReviewer"' in apps_env.read_text()

    def test_placeholder_key_without_override_stays_an_obvious_placeholder(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 0, r.stdout + r.stderr
        text = apps_env.read_text()
        assert 'HUMAN_REVIEWER="<YOUR_GITHUB_LOGIN>"' in text
        assert "left unresolved" in r.stderr

    def test_interactive_prompt_reads_real_stdin_not_the_template(self, config_dir):
        # The template is read into memory up front (mapfile), not piped into
        # the loop, precisely so an interactive `read -r -p` below reads the
        # value a caller supplies on stdin rather than the next template line.
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r = _run(config_dir, args=[], input_text="ScottExample\n" * 6)
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'HUMAN_REVIEWER="ScottExample"' in apps_env.read_text()

    def test_unsafe_value_rejected_before_writing(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        before = apps_env.read_text()
        r = _run(
            config_dir,
            args=["--non-interactive"],
            env_extra={"HUMAN_REVIEWER": 'x"; rm -rf /'},
        )
        assert r.returncode == 1
        assert "unsafe characters" in r.stderr
        # Reject-before-write: nothing appended when any single value fails.
        assert apps_env.read_text() == before

    def test_dry_run_writes_nothing(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        before = apps_env.read_text()
        r = _run(config_dir, args=["--non-interactive", "--dry-run"])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "would be added" in r.stdout
        assert apps_env.read_text() == before

    def test_idempotent_second_run_adds_nothing(self, config_dir):
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r1 = _run(config_dir, args=["--non-interactive"])
        assert r1.returncode == 0, r1.stdout + r1.stderr
        after_first = apps_env.read_text()
        r2 = _run(config_dir, args=["--non-interactive"])
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "nothing to do" in r2.stdout
        assert apps_env.read_text() == after_first

    def test_already_complete_apps_env_reports_nothing_to_do(self, config_dir):
        # Feed in every key the shipped template defines up front (same
        # extraction regex the script itself uses to walk the template).
        full_body = [
            line for line in TEMPLATE.read_text().splitlines()
            if re.match(r'^[A-Z_][A-Z0-9_]*="', line)
        ]
        apps_env = _write_apps_env(config_dir, "\n".join(full_body) + "\n")
        r = _run(config_dir, args=["--non-interactive"])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to do" in r.stdout

    def test_permissions_400_message_does_not_imply_it_is_wrong(self, config_dir):
        # 400 is an explicitly allowed mode (line above), but the error text
        # used to claim "expected 600" unconditionally — misleading someone
        # troubleshooting a deliberately read-only apps.env.
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        apps_env.chmod(0o644)
        r = _run(config_dir, args=["--non-interactive"])
        assert "expected 600 or 400" in r.stderr

    def test_config_dir_missing_value_errors_cleanly(self, config_dir):
        # `--config-dir` with no following argument must not crash on an
        # unbound `$2` under `set -u` — it should fail with a clear message.
        r = subprocess.run(
            [BASH, str(SCRIPT), "--config-dir"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert r.returncode == 1
        assert "unbound variable" not in r.stderr
        assert "--config-dir requires a value" in r.stderr

    def test_interactive_prompt_eof_leaves_key_unresolved_instead_of_crashing(self, config_dir):
        # EOF on stdin (e.g. piped input running out) makes `read` return
        # non-zero. Under `set -e` that used to kill the whole script instead
        # of being treated like an empty answer.
        apps_env = _write_apps_env(config_dir, MINIMAL_BODY)
        r = _run(config_dir, args=[], input_text="")
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'HUMAN_REVIEWER="<YOUR_GITHUB_LOGIN>"' in apps_env.read_text()
        assert "left unresolved" in r.stderr
