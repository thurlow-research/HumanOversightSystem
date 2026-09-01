"""
Tests for the identity-guard inputs produced by bootstrap/get_app_token.sh (#703).

#703: previously the script exported HOS_BOT_LOGIN and HOS_EXPECTED_BOT_LOGIN
from the *same* API-derived value, so the downstream cron identity guard
(HOS_BOT_LOGIN != HOS_EXPECTED_BOT_LOGIN) was a tautology — it could never fail.

The fix sources the two values independently:
  * HOS_BOT_LOGIN          = the API-authoritative slug from GET /app (actual)
  * HOS_EXPECTED_BOT_LOGIN = the operator's apps.env declaration (expected)
and fails closed at the source when they disagree or the declaration is missing.

Strategy
--------
Run the real get_app_token.sh offline:
  * Real openssl/python3/date from the system (JWT signing + JSON parsing).
  * A stub `curl` on PATH that returns canned GitHub API responses; its /app
    response carries a controllable slug so the test can force a match or a
    mismatch against the apps.env-declared login.
  * A real RSA PEM generated under the config dir so JWT signing succeeds and
    the PEM-prefix safety check (#633/#697) passes.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
OPENSSL = shutil.which("openssl")

GET_APP_TOKEN_SH = (
    Path(__file__).parent.parent.parent / "bootstrap" / "get_app_token.sh"
)

OWNER = "test-org"


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class TokenEnv:
    """Controlled environment that runs the real get_app_token.sh offline."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.config_dir = tmp_path / "config" / "hos"
        self.stub_bin = tmp_path / "stub_bin"
        self.config_dir.mkdir(parents=True)
        self.stub_bin.mkdir()

        # Real RSA key so JWT signing works and the PEM resolves under the
        # config base (#633/#697 prefix check).
        self.pem = self.config_dir / "worker.pem"
        subprocess.run(
            [OPENSSL, "genrsa", "-out", str(self.pem), "2048"],
            check=True, capture_output=True,
        )
        self.pem.chmod(0o600)

        # Stub curl: dispatch on the request URL. The /app response slug is
        # controlled via $SHIM_SLUG so a test can force match/mismatch.
        _write_exec(
            self.stub_bin / "curl",
            "#!/usr/bin/env bash\n"
            'url=""\n'
            'for a in "$@"; do case "$a" in https://*) url="$a";; esac; done\n'
            'case "$url" in\n'
            '  *access_tokens) printf \'{"token":"fake-token","expires_at":"2099-01-01T00:00:00Z"}\' ;;\n'
            '  *installations) printf \'[{"account":{"login":"%s"},"id":42}]\' "$SHIM_OWNER" ;;\n'
            '  */app)          printf \'{"slug":"%s"}\' "$SHIM_SLUG" ;;\n'
            '  *) echo "unexpected url: $url" >&2; exit 22 ;;\n'
            'esac\n'
            'exit 0\n',
        )

    def write_apps_env(self, declared_login: str | None) -> None:
        lines = [
            f'HOS_REPO_OWNER="{OWNER}"',
            'HOS_WORKER_APP_ID="123456"',
            f'HOS_WORKER_PEM="{self.pem}"',
        ]
        if declared_login is not None:
            lines.append(f'HOS_WORKER_BOT_LOGIN="{declared_login}"')
        apps_env = self.config_dir / "apps.env"
        apps_env.write_text("\n".join(lines) + "\n")
        apps_env.chmod(0o600)

    def run(self, slug: str) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.tmp / "home"),
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOS_CONFIG_DIR": str(self.config_dir),
            "SHIM_SLUG": slug,
            "SHIM_OWNER": OWNER,
        }
        return subprocess.run(
            [BASH, str(GET_APP_TOKEN_SH), "--app", "worker"],
            capture_output=True, text=True, timeout=60, check=False, env=env,
        )


@pytest.fixture
def token_env(tmp_path):
    if OPENSSL is None:
        pytest.skip("openssl not available")
    return TokenEnv(tmp_path)


def _exports(stdout: str) -> dict:
    out = {}
    for line in stdout.splitlines():
        if line.startswith("export ") and "=" in line:
            key, _, val = line[len("export "):].partition("=")
            out[key] = val.strip().strip("'")
    return out


class TestIdentityExports:
    def test_match_exports_both_from_independent_sources(self, token_env):
        # API slug and apps.env declaration agree → success, both exported.
        token_env.write_apps_env("hos-worker-test[bot]")
        r = token_env.run(slug="hos-worker-test")
        assert r.returncode == 0, r.stdout + r.stderr
        exp = _exports(r.stdout)
        # actual identity comes from the API slug; expected from apps.env.
        assert exp["HOS_BOT_LOGIN"] == "hos-worker-test[bot]"
        assert exp["HOS_EXPECTED_BOT_LOGIN"] == "hos-worker-test[bot]"

    def test_expected_reflects_apps_env_not_the_api_slug(self, token_env):
        # The expected value must track the apps.env declaration. Declaring a
        # value that disagrees with the slug must fail closed (#703) — proving
        # the two sides are no longer the same variable (the old tautology).
        token_env.write_apps_env("imposter[bot]")
        r = token_env.run(slug="hos-worker-test")
        assert r.returncode == 1
        assert "Identity mismatch" in r.stderr
        # No token/identity exports leak on a failed identity check.
        assert "export HOS_BOT_LOGIN" not in r.stdout
        assert "export GH_TOKEN" not in r.stdout

    def test_missing_declaration_fails_closed(self, token_env):
        # apps.env omits HOS_WORKER_BOT_LOGIN → fail closed with guidance,
        # never export an empty expected value.
        token_env.write_apps_env(None)
        r = token_env.run(slug="hos-worker-test")
        assert r.returncode == 1
        assert "HOS_WORKER_BOT_LOGIN not set" in r.stderr
        assert "export HOS_BOT_LOGIN" not in r.stdout


class TokenEnvHuman:
    """Controlled environment that runs get_app_token.sh offline with --app human."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.config_dir = tmp_path / "config" / "hos"
        self.stub_bin = tmp_path / "stub_bin"
        self.config_dir.mkdir(parents=True)
        self.stub_bin.mkdir()

        # Real RSA key so JWT signing works.
        self.pem = self.config_dir / "human.pem"
        subprocess.run(
            [OPENSSL, "genrsa", "-out", str(self.pem), "2048"],
            check=True, capture_output=True,
        )
        self.pem.chmod(0o600)

        # Stub curl — same dispatch pattern as TokenEnv.
        _write_exec(
            self.stub_bin / "curl",
            "#!/usr/bin/env bash\n"
            'url=""\n'
            'for a in "$@"; do case "$a" in https://*) url="$a";; esac; done\n'
            'case "$url" in\n'
            '  *access_tokens) printf \'{"token":"fake-token","expires_at":"2099-01-01T00:00:00Z"}\' ;;\n'
            '  *installations) printf \'[{"account":{"login":"%s"},"id":42}]\' "$SHIM_OWNER" ;;\n'
            '  */app)          printf \'{"slug":"%s"}\' "$SHIM_SLUG" ;;\n'
            '  *) echo "unexpected url: $url" >&2; exit 22 ;;\n'
            'esac\n'
            'exit 0\n',
        )

    def write_apps_env(self, declared_login: str | None) -> None:
        lines = [
            f'HOS_REPO_OWNER="{OWNER}"',
            'HOS_HUMAN_APP_ID="999999"',
            f'HOS_HUMAN_PEM="{self.pem}"',
        ]
        if declared_login is not None:
            lines.append(f'HOS_HUMAN_BOT_LOGIN="{declared_login}"')
        apps_env = self.config_dir / "apps.env"
        apps_env.write_text("\n".join(lines) + "\n")
        apps_env.chmod(0o600)

    def run(self, slug: str) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.tmp / "home"),
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOS_CONFIG_DIR": str(self.config_dir),
            "SHIM_SLUG": slug,
            "SHIM_OWNER": OWNER,
        }
        return subprocess.run(
            [BASH, str(GET_APP_TOKEN_SH), "--app", "human"],
            capture_output=True, text=True, timeout=60, check=False, env=env,
        )


@pytest.fixture
def human_env(tmp_path):
    if OPENSSL is None:
        pytest.skip("openssl not available")
    return TokenEnvHuman(tmp_path)


class TestHumanIdentityExports:
    """--app human uses HOS_HUMAN_* vars; identity guard behaves identically."""

    def test_match_exports_both_from_independent_sources(self, human_env):
        # API slug and apps.env declaration agree → success, both exported.
        human_env.write_apps_env("myname-claude[bot]")
        r = human_env.run(slug="myname-claude")
        assert r.returncode == 0, r.stdout + r.stderr
        exp = _exports(r.stdout)
        assert exp["HOS_BOT_LOGIN"] == "myname-claude[bot]"
        assert exp["HOS_EXPECTED_BOT_LOGIN"] == "myname-claude[bot]"

    def test_mismatch_fails_closed(self, human_env):
        # Declared login disagrees with API slug → fail closed, no token exported.
        human_env.write_apps_env("imposter[bot]")
        r = human_env.run(slug="myname-claude")
        assert r.returncode == 1
        assert "Identity mismatch" in r.stderr
        assert "export HOS_BOT_LOGIN" not in r.stdout
        assert "export GH_TOKEN" not in r.stdout

    def test_missing_declaration_fails_closed(self, human_env):
        # apps.env omits HOS_HUMAN_BOT_LOGIN → fail closed with guidance.
        human_env.write_apps_env(None)
        r = human_env.run(slug="myname-claude")
        assert r.returncode == 1
        assert "HOS_HUMAN_BOT_LOGIN not set" in r.stderr
        assert "export HOS_BOT_LOGIN" not in r.stdout

    def test_human_login_need_not_follow_hos_naming_pattern(self, human_env):
        # The Human App login does not follow the hos-<role>-hos[bot] pattern.
        # Any slug is valid as long as apps.env matches the API value.
        human_env.write_apps_env("scottthurlow-claude[bot]")
        r = human_env.run(slug="scottthurlow-claude")
        assert r.returncode == 0, r.stdout + r.stderr
        exp = _exports(r.stdout)
        assert exp["HOS_BOT_LOGIN"] == "scottthurlow-claude[bot]"
