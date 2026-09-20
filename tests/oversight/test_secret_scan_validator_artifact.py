"""secret_scan must pass the validator artifact it requires, without going blind (#1754).

`signoffs/validators/step{N}/summary.json` is a REQUIRED committed artifact —
`overseer.md` step 3b fail-closes to HUMAN_REQUIRED without it, and checks its
`head_sha` against the artifact commit's parent. That `head_sha` is a 40-hex git
SHA, which detect-secrets reports as a `Hex High Entropy String`, so the gate
failed on a file the pipeline demands. Not branch-specific: the long-committed
`signoffs/validators/step1/summary.json` on `main` trips the identical gate, and
CI runs `secret_scan` over exactly the changed-file list — so every MEDIUM+ PR
that wrote a validator artifact failed `oversight-gate-secret_scan`.

The obvious fix (skip the file, as #1572 does for validation stamps) is too
wide: the artifact runs to ~2,000 lines and quotes file paths and code evidence
from the changeset, which is exactly where a real credential could land. So
suppression is finding-level and requires THREE conditions — path glob,
detector type, AND the flagged line actually being a `*_sha` field holding a
bare 40-hex value.

These tests pin the narrowing (AC-2), not just the unblocking (AC-1/AC-4). The
logic tests are hermetic; the end-to-end gate tests skip when detect-secrets is
absent, matching tests/oversight/test_scan_gates_empty_args.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_module_from_path

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "oversight" / "gates" / "secret_scan.sh"
_LOGIC_PATH = _REPO / "scripts" / "oversight" / "secret_scan_logic.py"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

_DETECT_SECRETS = (_VENV_BIN / "detect-secrets").exists() or shutil.which(
    "detect-secrets"
) is not None

ssl_ = load_module_from_path("secret_scan_logic_1754", _LOGIC_PATH)

_ARTIFACT = "signoffs/validators/step7/summary.json"
_HEX_TYPE = "Hex High Entropy String"
_SHA = "8ed0daac85c1745824acfbddab9f3f77591039f8"  # pragma: allowlist secret


def _results(path: str, line_number: int, type_: str) -> dict:
    return {path: [{"type": type_, "filename": path, "line_number": line_number}]}


def _reader(line: str | None):
    return lambda _path, _line_number: line


# --------------------------------------------------------------------------- #
# The three conditions                                                        #
# --------------------------------------------------------------------------- #


def test_sha_field_in_a_validator_artifact_is_suppressed():
    kept, suppressed = ssl_.partition_findings(
        _results(_ARTIFACT, 2, _HEX_TYPE), _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert kept == []
    assert len(suppressed) == 1
    assert "#1754" in suppressed[0].reason


def test_same_shape_outside_a_validator_artifact_is_kept():
    """Condition 1 — the path glob. A config file is not exempt."""
    kept, suppressed = ssl_.partition_findings(
        _results("config/app.json", 2, _HEX_TYPE), _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    "type_", ["AWS Access Key", "Private Key", "Base64 High Entropy String", "Secret Keyword"]
)
def test_other_detectors_are_never_suppressed(type_):
    """Condition 2 — AC-2. Only the one benign detector is in scope."""
    kept, suppressed = ssl_.partition_findings(
        _results(_ARTIFACT, 2, type_), _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    "line",
    [
        '  "api_token": "8ed0daac85c1745824acfbddab9f3f77591039f8",\n',  # pragma: allowlist secret
        '  "password": "8ed0daac85c1745824acfbddab9f3f77591039f8",\n',  # pragma: allowlist secret
        '  "head_sha_note": "see 8ed0daac85c1745824acfbddab9f3f77591039f8 elsewhere",\n',
        '  "head_sha": "not-a-sha",\n',
    ],
)
def test_hex_under_a_non_sha_field_is_kept(line):
    """Condition 3 — the narrowing a plain (path, type) filter would not give.

    Planting a credential under `api_token` inside the artifact must not
    inherit the exemption just because the file and detector match.
    """
    kept, suppressed = ssl_.partition_findings(_results(_ARTIFACT, 588, _HEX_TYPE), _reader(line))
    assert suppressed == []
    assert len(kept) == 1


def test_unreadable_line_fails_closed():
    """No evidence for the exemption → no exemption."""
    kept, suppressed = ssl_.partition_findings(_results(_ARTIFACT, 2, _HEX_TYPE), _reader(None))
    assert suppressed == []
    assert len(kept) == 1


def test_malformed_finding_is_kept_not_dropped():
    """The gate must never lose a finding it cannot parse."""
    kept, suppressed = ssl_.partition_findings(
        {_ARTIFACT: [{"type": _HEX_TYPE}]}, _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize("field", ssl_._SHA_FIELDS)
def test_every_allowlisted_sha_field_is_covered(field):
    kept, suppressed = ssl_.partition_findings(
        _results(_ARTIFACT, 3, _HEX_TYPE), _reader(f'  "{field}": "{_SHA}",\n')
    )
    assert kept == [], field
    assert len(suppressed) == 1, field


@pytest.mark.parametrize("field", ["sha", "commit_sha", "parent_sha", "sha1"])
def test_unlisted_sha_like_fields_are_kept(field):
    """An explicit allowlist, not a `*_sha` family pattern.

    The family pattern was the first attempt here, on the reasoning that a new
    range field would otherwise re-block the pipeline. That trade is backwards:
    an unlisted field fails as a VISIBLE gate failure someone then fixes in
    SUPPRESSIONS, whereas a too-permissive pattern is a silent bypass.
    """
    kept, suppressed = ssl_.partition_findings(
        _results(_ARTIFACT, 3, _HEX_TYPE), _reader(f'  "{field}": "{_SHA}",\n')
    )
    assert suppressed == [], field
    assert len(kept) == 1, field


# --------------------------------------------------------------------------- #
# Adversarial cases from this change's own cross-vendor second review          #
# (codex, CWE-693). Both were exploitable in the first implementation.         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        # A leaked credential sharing the physical line with a legitimate SHA.
        '  "head_sha": "%s", "api_token": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae",\n' % _SHA,
        '  "api_token": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae", "head_sha": "%s",\n' % _SHA,
        '{"head_sha": "%s", "leaked": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae"}\n' % _SHA,
    ],
)
def test_mixed_line_is_never_suppressed(line):
    """detect-secrets reports per LINE, not per token.

    So a substring match for a `*_sha` field cannot tell WHICH value on the
    line was flagged, and would drop a leaked credential that merely shares a
    line with a legitimate `head_sha`. The predicate therefore requires the
    whole line to be that one property and nothing else.
    """
    kept, suppressed = ssl_.partition_findings(_results(_ARTIFACT, 2, _HEX_TYPE), _reader(line))
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    "path",
    [
        "signoffs/validators/step7/nested/summary.json",
        "signoffs/validators/a/b/summary.json",
        "signoffs/validators/notastep/summary.json",
        "signoffs/validators/step7/summary.json.bak",
        "x/signoffs/validators/step7/summary.json",
    ],
)
def test_paths_outside_the_exact_artifact_shape_are_kept(path):
    """`fnmatch`'s `*` crosses `/`; the rule uses an anchored regex instead.

    A crafted file at a deeper or differently-named path must not inherit the
    exemption just because it sits under signoffs/validators/.
    """
    kept, suppressed = ssl_.partition_findings(
        _results(path, 2, _HEX_TYPE), _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert suppressed == [], path
    assert len(kept) == 1, path


def test_leading_dot_slash_paths_match(monkeypatch, tmp_path):
    """The full-project scan emits `./`-prefixed paths; the glob must still hit."""
    kept, suppressed = ssl_.partition_findings(
        _results(f"./{_ARTIFACT}", 2, _HEX_TYPE), _reader(f'  "head_sha": "{_SHA}",\n')
    )
    assert kept == []
    assert len(suppressed) == 1


# --------------------------------------------------------------------------- #
# CLI contract                                                                #
# --------------------------------------------------------------------------- #


def _run_filter(stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(_LOGIC_PATH), "filter"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=60,
    )


def test_cli_reports_every_suppression(tmp_path):
    """AC-3 — suppression is never silent, including on a passing run."""
    artifact = tmp_path / _ARTIFACT
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{\n  "head_sha": "%s"\n}\n' % _SHA)

    result = _run_filter(json.dumps({"results": _results(_ARTIFACT, 2, _HEX_TYPE)}), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 finding(s) suppressed" in result.stdout
    assert _ARTIFACT in result.stdout
    assert "1 suppressed" in result.stdout


def test_cli_fails_closed_on_unparseable_scan_output(tmp_path):
    """Previously `|| echo "0"` — an unreadable scan reported zero secrets.

    That is the same report-success-having-checked-nothing shape as #1750 and
    #1759, one layer down, so it must be a gate failure rather than a pass.
    """
    for payload in ["not json at all", "[]", '{"no_results_key": 1}', '{"results": []}']:
        result = _run_filter(payload, tmp_path)
        assert result.returncode == 2, f"{payload!r} → {result.returncode}"
        assert "GATE FAIL" in result.stderr


# --------------------------------------------------------------------------- #
# End to end, through the real gate                                           #
# --------------------------------------------------------------------------- #


def _fixture_artifact(tmp_path: Path, extra: dict | None = None) -> Path:
    artifact = tmp_path / _ARTIFACT
    artifact.parent.mkdir(parents=True, exist_ok=True)
    body = {"head_sha": _SHA, "artifact_version": "1", "step": 7, "tier": "LOW"}
    body.update(extra or {})
    artifact.write_text(json.dumps(body, indent=2))
    return artifact


def _run_gate(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_GATE), _ARTIFACT],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_passes_a_clean_validator_artifact(tmp_path):
    """AC-1/AC-4 — the artifact the overseer requires no longer fails the gate."""
    _fixture_artifact(tmp_path)
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GATE PASS" in result.stdout
    assert "suppressed" in result.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_still_fails_on_a_planted_key_in_the_same_artifact(tmp_path):
    """AC-2 end to end — the file stays in the scan, it is not skipped."""
    _fixture_artifact(tmp_path, {"leaked": "AKIAIOSFODNN7EXAMPLE"})  # pragma: allowlist secret
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "GATE FAIL" in result.stdout
    # The benign one is still reported as suppressed alongside the real failure.
    assert "suppressed" in result.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_passes_the_artifact_committed_on_main():
    """AC-4 literally: the file that has been failing this gate on `main`."""
    committed = _REPO / "signoffs" / "validators" / "step1" / "summary.json"
    if not committed.exists():
        pytest.skip("no committed validator artifact in this checkout")
    result = subprocess.run(
        ["bash", str(_GATE), "signoffs/validators/step1/summary.json"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
