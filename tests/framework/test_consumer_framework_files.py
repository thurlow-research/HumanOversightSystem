"""Guards the consumer framework files list (#769).

The install copy-loop and the .hos-manifest enumerator must read the SAME list
(scripts/framework/framework_consumer_files.txt) so the manifest can never
declare a file the install didn't ship. These tests fail if:
  - the file is missing or empty
  - a listed file is absent from the HOS source repo
  - the installer stops reading the list on either side (copy OR manifest)
  - HOS-dev-only tools leak into the consumer set
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "scripts" / "framework" / "framework_consumer_files.txt"
INSTALLER = ROOT / "bootstrap" / "hos_install.sh"

# Tools that belong only in HOS dev tooling — must never ship to consumers.
_HOS_DEV_ONLY = {
    "cut_release.sh",
    "validate_scripts.sh",
    "validate_agents.sh",
    "validate_self.sh",
    "validate_docs.sh",
    "validate_spec_compliance.sh",
    "run_framework_validation.sh",
    "run_tests_release.sh",
    "check_agents_static.sh",
    "check_validation_current.sh",
    "strip_internal_paths.sh",
}


def _consumer_files() -> list[str]:
    out = []
    for line in LIST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def test_list_exists_and_nonempty():
    assert LIST.is_file()
    assert _consumer_files(), "framework_consumer_files.txt has no entries"


def test_every_listed_file_exists_in_source():
    for f in _consumer_files():
        assert (ROOT / f).is_file(), (
            f"framework_consumer_files.txt lists {f} but {ROOT / f} is missing from source"
        )


def test_bin_lib_git_credentials_present():
    """bin/lib/git-credentials.sh is the critical missing dep (#769 CRITICAL)."""
    assert "bin/lib/git-credentials.sh" in set(_consumer_files()), (
        "bin/lib/git-credentials.sh must be in the consumer ship-set — "
        "bin/hos-cron sources it at startup; without it the cron launcher fails"
    )


def test_required_branch_protection_workflows_present():
    """The three branch-protection status-check producers must ship to consumers."""
    files = set(_consumer_files())
    for wf in (
        ".github/workflows/require-human-approval.yml",
        ".github/workflows/require-overseer-approval.yml",
        ".github/workflows/require-tier-ceiling.yml",
    ):
        assert wf in files, (
            f"{wf} must be in the consumer ship-set — it produces a required "
            "status-check context; without it branch protection bricks every PR"
        )


def test_consumer_governance_tools_present():
    """Consumer-facing scripts/framework/ tools must ship to enable governance setup."""
    files = set(_consumer_files())
    for tool in (
        "scripts/framework/setup_branch_protection.sh",
        "scripts/framework/gen_codeowners.sh",
        "scripts/framework/protected_surfaces.txt",
    ):
        assert tool in files, f"{tool} must be in the consumer ship-set (#769)"


def test_hos_dev_only_tools_excluded():
    """HOS internal tools must not leak into the consumer ship-set."""
    files = set(_consumer_files())
    leaked = {p for p in files if Path(p).name in _HOS_DEV_ONLY}
    assert not leaked, f"HOS-dev-only tools must not ship to consumers: {leaked}"


def test_installer_reads_list_on_both_sides():
    """Both the copy-loop and the manifest enumerator must read the canonical list."""
    text = INSTALLER.read_text()
    assert text.count("framework_consumer_files.txt") >= 2, (
        "hos_install.sh must reference framework_consumer_files.txt in BOTH the "
        "copy-loop and enumerate_framework_files (the manifest enumerator)"
    )
