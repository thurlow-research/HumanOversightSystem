"""
Unit tests for activation.py — repo-id slug derivation and activation gate (R13.4).
"""

import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.automation.lib.activation import (
    _normalize_remote_url,
    activate,
    check_activation,
    deactivate,
    derive_repo_id,
)


# ---------------------------------------------------------------------------
# _normalize_remote_url
# ---------------------------------------------------------------------------

class TestNormalizeRemoteUrl:
    def test_https_with_git_suffix(self):
        owner, repo = _normalize_remote_url(
            "https://github.com/thurlow-research/HumanOversightSystem.git"
        )
        assert owner == "thurlow-research"
        assert repo == "humanoversightsystem"

    def test_https_without_git_suffix(self):
        owner, repo = _normalize_remote_url(
            "https://github.com/thurlow-research/HumanOversightSystem"
        )
        assert owner == "thurlow-research"
        assert repo == "humanoversightsystem"

    def test_ssh_form(self):
        owner, repo = _normalize_remote_url(
            "git@github.com:thurlow-research/HumanOversightSystem.git"
        )
        assert owner == "thurlow-research"
        assert repo == "humanoversightsystem"

    def test_uppercase_normalized(self):
        owner, repo = _normalize_remote_url(
            "https://github.com/ScottThurlow/HumanOversightSystem.git"
        )
        assert owner == "scottthurlow"
        assert repo == "humanoversightsystem"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            _normalize_remote_url("not-a-github-url")


class TestDeriveRepoId:
    def test_produces_owner_dash_repo(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/thurlow-research/HumanOversightSystem.git\n",
            )
            repo_id = derive_repo_id()
        assert repo_id == "thurlow-research-humanoversightsystem"

    def test_ssh_remote(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="git@github.com:thurlow-research/HOS.git\n",
            )
            repo_id = derive_repo_id()
        assert repo_id == "thurlow-research-hos"

    def test_git_failure_raises(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")
            with pytest.raises(RuntimeError):
                derive_repo_id()


# ---------------------------------------------------------------------------
# check_activation (fail-closed by design)
# ---------------------------------------------------------------------------

class TestCheckActivation:
    REPO_ID = "thurlow-research-humanoversightsystem"

    def _patch_repo_id(self, repo_id=None):
        return patch(
            "scripts.automation.lib.activation.derive_repo_id",
            return_value=repo_id or self.REPO_ID,
        )

    def _patch_hostname(self, name="testhost.local"):
        return patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stdout=f"{name}\n"),
        )

    def test_off_when_active_file_absent(self, tmp_path):
        with self._patch_repo_id():
            with patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path):
                assert check_activation() is False

    def test_active_when_token_matches_hostname(self, tmp_path):
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text("testhost.local\n")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout="testhost.local\n"),
            ),
        ):
            assert check_activation() is True

    def test_off_when_token_mismatches_hostname(self, tmp_path):
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text("other-host.local\n")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout="testhost.local\n"),
            ),
        ):
            assert check_activation() is False

    def test_off_when_active_file_empty(self, tmp_path):
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text("")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            assert check_activation() is False

    def test_active_with_uuid_token(self, tmp_path):
        token = str(uuid.uuid4())
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text(token + "\n")
        (hos_dir / "MACHINE-TOKEN").write_text(token + "\n")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            assert check_activation() is True

    def test_off_when_machine_token_empty(self, tmp_path):
        """Empty MACHINE-TOKEN → OFF even if ACTIVE has a UUID."""
        token = str(uuid.uuid4())
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text(token + "\n")
        (hos_dir / "MACHINE-TOKEN").write_text("")  # empty → OFF

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            assert check_activation() is False

    def test_off_on_derive_repo_id_failure(self):
        with patch(
            "scripts.automation.lib.activation.derive_repo_id",
            side_effect=RuntimeError("no git remote"),
        ):
            assert check_activation() is False

    def test_no_try_hostname_if_machine_token_exists_but_empty(self, tmp_path):
        """
        Machine-token exists but is empty → OFF immediately.
        Must NOT fall back to hostname comparison.
        """
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        (hos_dir / "ACTIVE").write_text("testhost.local\n")
        (hos_dir / "MACHINE-TOKEN").write_text("")  # empty → fail-closed, no fallback

        hostname_called = []

        def mock_run(args, **kwargs):
            if args[0] == "hostname":
                hostname_called.append(True)
            return MagicMock(returncode=0, stdout="testhost.local\n")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch("subprocess.run", side_effect=mock_run),
        ):
            result = check_activation()

        assert result is False
        assert hostname_called == [], (
            "Should not call hostname when MACHINE-TOKEN exists but is empty"
        )


# ---------------------------------------------------------------------------
# activate / deactivate helpers
# ---------------------------------------------------------------------------

class TestActivateDeactivate:
    REPO_ID = "thurlow-research-humanoversightsystem"

    def _patch_repo_id(self):
        return patch(
            "scripts.automation.lib.activation.derive_repo_id",
            return_value=self.REPO_ID,
        )

    def test_activate_writes_hostname_to_active(self, tmp_path):
        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout="myhost.local\n"),
            ),
        ):
            repo_id = activate()

        assert repo_id == self.REPO_ID
        active = (tmp_path / ".hos" / self.REPO_ID / "ACTIVE").read_text().strip()
        assert active == "myhost.local"
        assert not (tmp_path / ".hos" / self.REPO_ID / "MACHINE-TOKEN").exists()

    def test_activate_uuid_writes_both_files(self, tmp_path):
        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            activate(use_uuid=True)

        active = (tmp_path / ".hos" / self.REPO_ID / "ACTIVE").read_text().strip()
        mt = (tmp_path / ".hos" / self.REPO_ID / "MACHINE-TOKEN").read_text().strip()
        assert active == mt
        # Must be a valid UUID.
        uuid.UUID(active)

    def test_deactivate_removes_active(self, tmp_path):
        hos_dir = tmp_path / ".hos" / self.REPO_ID
        hos_dir.mkdir(parents=True)
        active_path = hos_dir / "ACTIVE"
        active_path.write_text("myhost\n")

        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            deactivate()

        assert not active_path.exists()

    def test_deactivate_idempotent_when_already_absent(self, tmp_path):
        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
        ):
            deactivate()  # Must not raise.

    def test_activate_raises_when_orchestrator_missing(self, tmp_path):
        """verify_orchestrator=True and no orchestrator → RuntimeError before writing ACTIVE."""
        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="myhost.local\n")),
        ):
            with pytest.raises(RuntimeError, match="hos_orchestrator.sh not found"):
                activate(repo_root=str(tmp_path), verify_orchestrator=True)
        # ACTIVE must not have been written
        assert not (tmp_path / ".hos" / self.REPO_ID / "ACTIVE").exists()

    def test_activate_succeeds_when_verify_false(self, tmp_path):
        """verify_orchestrator=False skips the check even with no orchestrator."""
        with (
            self._patch_repo_id(),
            patch("scripts.automation.lib.activation.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="myhost.local\n")),
        ):
            repo_id = activate(repo_root=str(tmp_path), verify_orchestrator=False)
        assert repo_id == self.REPO_ID
