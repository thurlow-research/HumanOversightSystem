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
import os
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


def _reader(text: str | None):
    """A text_reader that hands back `text` for any path."""
    return lambda _path: text


def _verifier(*known: str):
    """A sha_verifier accepting only `known` SHAs; defaults to the real one."""
    allowed = set(known) or {_SHA}
    return lambda value: value in allowed


def _partition(results, reader, verifier=None):
    """partition_findings with a verifier that accepts the canonical SHA."""
    return ssl_.partition_findings(results, reader, sha_verifier=verifier or _verifier())


def _artifact_text(**fields: object) -> str:
    """A realistic artifact: `head_sha` first, as run_validators.sh writes it."""
    body = {"head_sha": _SHA, "artifact_version": "1", "step": 7}
    body.update(fields)
    return json.dumps(body, indent=2) + "\n"


def _line_of(text: str, needle: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not found")


# --------------------------------------------------------------------------- #
# The exempted invariant: the artifact's TOP-LEVEL SHA metadata field          #
# --------------------------------------------------------------------------- #


def test_top_level_head_sha_is_suppressed():
    text = _artifact_text()
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, "head_sha"), _HEX_TYPE), _reader(text)
    )
    assert kept == []
    assert len(suppressed) == 1
    assert "head_sha" in suppressed[0].reason
    assert "#1754" in suppressed[0].reason


@pytest.mark.parametrize("field", ssl_._SHA_FIELDS)
def test_every_allowlisted_field_is_covered(field):
    text = json.dumps({field: _SHA, "step": 7}, indent=2) + "\n"
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, field), _HEX_TYPE), _reader(text)
    )
    assert kept == [], field
    assert len(suppressed) == 1, field


@pytest.mark.parametrize(
    "field", ["sha", "commit_sha", "parent_sha", "api_token", "base_sha", "merge_base_sha"]
)
def test_unlisted_top_level_fields_are_kept(field):
    """An explicit allowlist, not a `*_sha` family pattern.

    An unlisted field fails as a VISIBLE gate failure someone then fixes in
    SUPPRESSIONS; a loose pattern would be a silent bypass.
    """
    text = json.dumps({field: _SHA, "step": 7}, indent=2) + "\n"
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, field), _HEX_TYPE), _reader(text)
    )
    assert suppressed == [], field
    assert len(kept) == 1, field


def test_same_shape_outside_a_validator_artifact_is_kept():
    """Condition: the path. A config file is not exempt."""
    text = _artifact_text()
    kept, suppressed = _partition(
        _results("config/app.json", _line_of(text, "head_sha"), _HEX_TYPE), _reader(text)
    )
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
    text = _artifact_text()
    kept, suppressed = _partition(
        _results(path, _line_of(text, "head_sha"), _HEX_TYPE), _reader(text)
    )
    assert suppressed == [], path
    assert len(kept) == 1, path


@pytest.mark.parametrize(
    "type_", ["AWS Access Key", "Private Key", "Base64 High Entropy String", "Secret Keyword"]
)
def test_other_detectors_are_never_suppressed(type_):
    """AC-2. Only the one benign detector is in scope, even on the exempt line."""
    text = _artifact_text()
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, "head_sha"), type_), _reader(text)
    )
    assert suppressed == []
    assert len(kept) == 1


def test_findings_on_other_lines_are_kept():
    """A planted credential elsewhere in the artifact keeps its finding."""
    text = _artifact_text(leaked="a5cd90d8ae66c69755dca4cd38b9a417088b32ae")
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, "leaked"), _HEX_TYPE), _reader(text)
    )
    assert suppressed == []
    assert len(kept) == 1


# --------------------------------------------------------------------------- #
# Adversarial cases from this change's own cross-vendor second review          #
# (codex, CWE-693). Each was exploitable in an earlier revision of this file.  #
# --------------------------------------------------------------------------- #


def test_nested_key_named_head_sha_is_not_exempt():
    """The invariant is the TOP-LEVEL field, not any line that looks like one.

    A validator summary embeds changeset-derived content, so a 40-hex value
    could reach a nested key. Round 2 of the review found that a line-shape
    check suppressed it.
    """
    text = (
        json.dumps(
            {
                "head_sha": _SHA,
                "results": [{"head_sha": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae"}],
            },
            indent=2,
        )
        + "\n"
    )
    nested_line = _line_of(text, "a5cd90d8")
    kept, suppressed = _partition(_results(_ARTIFACT, nested_line, _HEX_TYPE), _reader(text))
    assert suppressed == []
    assert len(kept) == 1


def test_duplicate_key_deeper_in_the_file_cannot_stand_in():
    """Only the line whose value matches the PARSED document is exempt.

    With a duplicate top-level key, `json` keeps the last; the earlier line
    must not be exempted on the strength of the later one.
    """
    text = (
        '{\n  "head_sha": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae",\n  "head_sha": "%s"\n}\n'
        % _SHA
    )
    kept, suppressed = _partition(_results(_ARTIFACT, 2, _HEX_TYPE), _reader(text))
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    "text",
    [
        '{"head_sha": "%s", "api_token": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae"}\n' % _SHA,
        '{"api_token": "a5cd90d8ae66c69755dca4cd38b9a417088b32ae", "head_sha": "%s"}\n' % _SHA,
    ],
)
def test_mixed_line_is_never_suppressed(text):
    """detect-secrets reports per LINE, not per token.

    A rule that matched a `head_sha` substring could not tell WHICH value on
    the line was flagged, and dropped a leaked credential sharing that line.
    """
    kept, suppressed = _partition(_results(_ARTIFACT, 1, _HEX_TYPE), _reader(text))
    assert suppressed == []
    assert len(kept) == 1


def test_braces_inside_strings_do_not_confuse_depth_tracking():
    """Evidence snippets in the artifact contain code, and code contains braces."""
    text = json.dumps({"note": "def f() { return '{'; }", "head_sha": _SHA}, indent=2) + "\n"
    kept, suppressed = _partition(
        _results(_ARTIFACT, _line_of(text, "head_sha"), _HEX_TYPE), _reader(text)
    )
    assert kept == []
    assert len(suppressed) == 1


@pytest.mark.parametrize(
    "text", ["not json at all\n", "[]\n", '"a string"\n', '{"head_sha": "short"}\n', ""]
)
def test_unparseable_or_unexpected_document_suppresses_nothing(text):
    """No confirmable evidence → no exemption."""
    kept, suppressed = _partition(_results(_ARTIFACT, 1, _HEX_TYPE), _reader(text))
    assert suppressed == []
    assert len(kept) == 1


def test_unreadable_file_fails_closed():
    kept, suppressed = _partition(_results(_ARTIFACT, 2, _HEX_TYPE), _reader(None))
    assert suppressed == []
    assert len(kept) == 1


def test_malformed_finding_is_kept_not_dropped():
    """The gate must never lose a finding it cannot parse."""
    kept, suppressed = _partition({_ARTIFACT: [{"type": _HEX_TYPE}]}, _reader(_artifact_text()))
    assert suppressed == []
    assert len(kept) == 1


def test_leading_dot_slash_paths_match():
    """The full-project scan emits `./`-prefixed paths; the rule must still hit."""
    text = _artifact_text()
    kept, suppressed = _partition(
        _results(f"./{_ARTIFACT}", _line_of(text, "head_sha"), _HEX_TYPE), _reader(text)
    )
    assert kept == []
    assert len(suppressed) == 1


def test_file_is_read_once_per_path():
    """The artifact is ~2,000 lines; re-reading it per finding is wasteful."""
    text = _artifact_text(leaked="a5cd90d8ae66c69755dca4cd38b9a417088b32ae")
    calls: list[str] = []

    def reader(path: str) -> str:
        calls.append(path)
        return text

    results = {
        _ARTIFACT: [
            {"type": _HEX_TYPE, "line_number": _line_of(text, "head_sha")},
            {"type": _HEX_TYPE, "line_number": _line_of(text, "leaked")},
        ]
    }
    kept, suppressed = _partition(results, reader)
    assert calls == [_ARTIFACT]
    assert len(kept) == 1 and len(suppressed) == 1


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
    head = _init_repo(tmp_path)
    artifact = tmp_path / _ARTIFACT
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{\n  "head_sha": "%s"\n}\n' % head)

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


def _init_repo(tmp_path: Path) -> str:
    """A throwaway repo with one commit; returns its SHA.

    The gate verifies a candidate `head_sha` against real git state, so these
    end-to-end tests need a real object to point at — a hardcoded SHA would
    (correctly) fail to resolve and suppress nothing.
    """
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    run = lambda *a: subprocess.run(  # noqa: E731
        a, cwd=str(tmp_path), check=True, capture_output=True, env=env, timeout=60
    )
    run("git", "init", "-q")
    (tmp_path / "seed.txt").write_text("seed\n")
    run("git", "add", "seed.txt")
    run("git", "commit", "-qm", "seed")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()


def _fixture_artifact(tmp_path: Path, head: str, extra: dict | None = None) -> Path:
    artifact = tmp_path / _ARTIFACT
    artifact.parent.mkdir(parents=True, exist_ok=True)
    body = {"head_sha": head, "artifact_version": "1", "step": 7, "tier": "LOW"}
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
    _fixture_artifact(tmp_path, _init_repo(tmp_path))
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GATE PASS" in result.stdout
    assert "suppressed" in result.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_still_fails_on_a_planted_key_in_the_same_artifact(tmp_path):
    """AC-2 end to end — the file stays in the scan, it is not skipped."""
    head = _init_repo(tmp_path)
    _fixture_artifact(
        tmp_path, head, {"leaked": "AKIAIOSFODNN7EXAMPLE"}
    )  # pragma: allowlist secret
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "GATE FAIL" in result.stdout
    # The benign one is still reported as suppressed alongside the real failure.
    assert "suppressed" in result.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_rejects_a_head_sha_that_is_not_a_real_commit(tmp_path):
    """The last proxy closed: SHA-shaped is not the same as being a SHA.

    A 40-hex credential parked in the one exempted field must still fail,
    because the gate now checks the value against git rather than trusting
    that some other stage verified it.
    """
    _init_repo(tmp_path)
    _fixture_artifact(tmp_path, "a5cd90d8ae66c69755dca4cd38b9a417088b32ae")
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "suppressed" not in result.stdout


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
