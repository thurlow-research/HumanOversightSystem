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
import re
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
# A second 40-hex value, for the cases that need one which is NOT the
# artifact's top-level `head_sha`. Hoisted to a constant so the
# `# pragma: allowlist secret` has one home: this file is itself scanned by the
# gate it tests, detect-secrets reports every 40-hex literal as a Hex High
# Entropy String, and the pragma must sit on the flagged line — inline in a
# `json.dumps({...})` call it lands wherever black last wrapped the argument.
_NESTED_SHA = "a5cd90d8ae66c69755dca4cd38b9a417088b32ae"  # pragma: allowlist secret


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
    text = _artifact_text(leaked=_NESTED_SHA)
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
                "results": [{"head_sha": _NESTED_SHA}],
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
    text = '{\n  "head_sha": "%s",\n  "head_sha": "%s"\n}\n' % (_NESTED_SHA, _SHA)
    kept, suppressed = _partition(_results(_ARTIFACT, 2, _HEX_TYPE), _reader(text))
    assert suppressed == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    "text",
    [
        '{"head_sha": "%s", "api_token": "%s"}\n' % (_SHA, _NESTED_SHA),
        '{"api_token": "%s", "head_sha": "%s"}\n' % (_NESTED_SHA, _SHA),
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


def test_non_candidate_paths_are_never_opened():
    """A security gate must not become a file-read primitive.

    detect-secrets output is tool output — data. A crafted baseline naming
    `../../secrets.env` must not get this gate to open it while deciding what
    to suppress (codex, CWE-22).
    """
    opened: list[str] = []

    def reader(path: str) -> str | None:
        opened.append(path)
        return None

    results = {
        "../../secrets.env": [{"type": _HEX_TYPE, "line_number": 1}],
        "/etc/shadow": [{"type": _HEX_TYPE, "line_number": 1}],
        "some/other/file.json": [{"type": _HEX_TYPE, "line_number": 1}],
    }
    kept, suppressed = ssl_.partition_findings(results, reader, sha_verifier=_verifier())
    assert opened == []
    assert suppressed == []
    assert len(kept) == 3


@pytest.mark.parametrize(
    "path", ["../../secrets.env", "/etc/passwd", "signoffs/../../../etc/passwd"]
)
def test_reader_refuses_paths_outside_the_repository(tmp_path, monkeypatch, path):
    """The second, independent barrier: the reader contains itself."""
    monkeypatch.chdir(tmp_path)
    assert ssl_._file_text_reader(path) is None


def test_reader_reads_a_contained_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "a" / "b.json"
    target.parent.mkdir()
    target.write_text("hello")
    assert ssl_._file_text_reader("a/b.json") == "hello"


def test_file_is_read_once_per_path():
    """The artifact is ~2,000 lines; re-reading it per finding is wasteful."""
    text = _artifact_text(leaked=_NESTED_SHA)
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


def _git_env() -> dict:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }


def _commit_file(repo: Path, name: str, body: str) -> str:
    """Add one more commit, so a clone can be shallow enough to miss the first."""
    (repo / name).write_text(body + "\n")
    for args in (("add", name), ("commit", "-qm", name)):
        subprocess.run(
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
            env=_git_env(),
            timeout=60,
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()


def _verifier_in(monkeypatch, repo: Path):
    """A `GitShaVerifier` resolving against `repo`.

    Via chdir rather than a cwd argument, because that is how the real thing
    works: the CLI shim runs inside the tree the gate was invoked in.

    Unannotated: `ssl_` is loaded at runtime by path (the module lives in
    scripts/, outside the importable package tree), so mypy cannot resolve a
    type off it.
    """
    monkeypatch.chdir(repo)
    return ssl_.GitShaVerifier()


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
    # Bound to a name first so the pragma stays on the literal's own line.
    # Inline as a third argument, black wrapped the call and carried the
    # trailing comment to the closing-paren line, where detect-secrets — which
    # matches per line — never saw it, and this file tripped its own gate.
    planted = {"leaked": "AKIAIOSFODNN7EXAMPLE"}  # pragma: allowlist secret
    _fixture_artifact(tmp_path, head, planted)
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
    _fixture_artifact(tmp_path, _NESTED_SHA)
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "suppressed" not in result.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_passes_the_artifact_committed_on_main():
    """AC-4 literally: the file that has been failing this gate on `main`.

    Branches on the clone rather than skipping, because a skip here is exactly
    the blind spot that let this ship: the assertion held locally (a complete
    clone) and the CI job ran it in a depth-1 checkout, where the artifact's
    commit is absent, the exemption cannot be verified and the gate correctly
    fails closed. Both are specified behaviour, so both are asserted — and in
    the shallow case what is asserted is that the gate NAMES the reason.
    """
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
    output = result.stdout + result.stderr
    # Branch on the precise condition the gate branches on — whether THIS
    # artifact's commit is in THIS object store. "Shallow" alone is too coarse:
    # a clone can be depth-limited and still hold the commit, which is why the
    # failure reproduced in CI's depth-1 checkout and not in a developer's
    # partially-truncated one.
    head_sha = json.loads(committed.read_text())["head_sha"]
    if _commit_present(_REPO, head_sha):
        assert result.returncode == 0, output
    elif _is_shallow(_REPO):
        assert result.returncode == 1, output
        assert "SHALLOW" in result.stdout, output
        assert "fetch-depth: 0" in result.stdout, output
    else:
        pytest.fail(
            f"{head_sha} names no commit in a complete clone — the committed "
            f"artifact's head_sha is wrong, not the environment:\n{output}"
        )


# --------------------------------------------------------------------------- #
# The clone the gate runs in (#1754 bounce #1)                                 #
#                                                                              #
# Condition 4 resolves the artifact's `head_sha` against the local object      #
# store. `actions/checkout` fetches depth 1 by default, so in an ordinary CI   #
# checkout no artifact SHA resolves and the suppression stops applying. Safe   #
# (fail-closed) but, until this change, silent.                                #
# --------------------------------------------------------------------------- #


def _is_shallow(repo: Path) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        == "true"
    )


def _commit_present(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=str(repo),
            capture_output=True,
            timeout=60,
        ).returncode
        == 0
    )


def _shallow_clone(tmp_path: Path) -> tuple[Path, str]:
    """A depth-1 clone of a two-commit repo, plus the SHA it cannot see.

    The returned SHA is a genuine commit in the source repo and genuinely
    absent from the clone — the exact shape a committed validator artifact has
    in CI, where `head_sha` names an ancestor of the checked-out tip.
    """
    source = tmp_path / "source"
    source.mkdir()
    old = _init_repo(source)
    _commit_file(source, "second.txt", "second")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--depth=1", "--quiet", source.as_uri(), str(clone)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert _is_shallow(clone)
    return clone, old


def test_verifier_confirms_a_real_commit(tmp_path, monkeypatch):
    head = _init_repo(tmp_path)
    verifier = _verifier_in(monkeypatch, tmp_path)
    assert verifier(head) is True
    assert verifier.undecidable == []


def test_verifier_reports_a_missing_commit_without_a_remedy(tmp_path, monkeypatch):
    """A complete clone CAN answer, and the answer is no.

    This is the bypass condition 4 exists to catch — a SHA-shaped value that is
    not a SHA — so it must stay a plain finding about the artifact, with no
    environment remedy attached to soften it.
    """
    _init_repo(tmp_path)
    verifier = _verifier_in(monkeypatch, tmp_path)
    assert verifier(_NESTED_SHA) is False
    assert verifier.undecidable == []


def test_verifier_marks_a_shallow_clone_undecidable(tmp_path, monkeypatch):
    """Same False, different meaning — and the difference is now recorded."""
    clone, unreachable = _shallow_clone(tmp_path)
    verifier = _verifier_in(monkeypatch, clone)
    assert verifier(unreachable) is False
    assert verifier.undecidable == [ssl_.Undecided(unreachable, "shallow")]


def test_verifier_marks_an_unusable_git_undecidable(tmp_path, monkeypatch):
    """No git is not evidence the value is bad, and must not read as such."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    verifier = _verifier_in(monkeypatch, tmp_path)
    assert verifier(_SHA) is False
    assert [item.cause for item in verifier.undecidable] == ["git-unavailable"]


def test_verifier_marks_an_unreadable_depth_answer_undecidable(tmp_path, monkeypatch):
    """git ran, and would not say whether the clone is shallow.

    Injected rather than staged: there is no ordinary way to make a healthy git
    answer `--is-shallow-repository` with something other than true/false. Worth
    pinning anyway, because the failure mode if this branch were wrong is the
    exact conflation this change exists to undo — an unanswerable question
    silently reading as "we checked, and the value is not a commit".
    """
    calls: list[tuple] = []

    def fake_run(argv, **kwargs):
        calls.append(tuple(argv))
        if "rev-parse" in argv:
            # Answered, but with something that is neither true nor false.
            return subprocess.CompletedProcess(argv, 0, b"maybe\n", b"")
        return subprocess.CompletedProcess(argv, 1, b"", b"")

    verifier = _verifier_in(monkeypatch, tmp_path)
    monkeypatch.setattr(ssl_.subprocess, "run", fake_run)
    assert verifier(_SHA) is False
    assert [item.cause for item in verifier.undecidable] == ["unknown-depth"]
    # It did ask both questions, in order — the depth question is only reachable
    # once cat-file has already declined.
    assert [argv[1] for argv in calls] == ["cat-file", "rev-parse"]


def test_undecidable_entries_are_deduplicated(tmp_path, monkeypatch):
    """A ~2,000-line artifact can flag one SHA many times; say it once."""
    clone, unreachable = _shallow_clone(tmp_path)
    verifier = _verifier_in(monkeypatch, clone)
    for _ in range(4):
        verifier(unreachable)
    assert len(verifier.undecidable) == 1


def test_every_cause_the_verifier_emits_has_a_remedy():
    """The CLI indexes UNDECIDABLE_REMEDY by cause — a gap would be a KeyError.

    That would turn a gate failure into a crash at the exact moment the gate is
    trying to explain itself, so the two are pinned together here.
    """
    source = Path(ssl_.__file__).read_text()
    emitted = set(re.findall(r'_record\([^,]+, "([a-z-]+)"\)', source))
    assert emitted
    assert emitted <= set(ssl_.UNDECIDABLE_REMEDY)


def test_a_non_sha_shaped_value_is_never_called_undecidable(tmp_path, monkeypatch):
    """Rejected on shape alone — git is never asked, so nothing is unresolved."""
    _init_repo(tmp_path)
    verifier = _verifier_in(monkeypatch, tmp_path)
    assert verifier("not-a-sha") is False
    assert verifier.undecidable == []


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_gate_in_a_shallow_clone_fails_closed_and_says_why(tmp_path):
    """The bounce, end to end: fail-closed is fine; unexplained is not."""
    clone, unreachable = _shallow_clone(tmp_path)
    _fixture_artifact(clone, unreachable)
    result = _run_gate(clone)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "suppressed" not in result.stdout, output
    # Names the cause, not just the symptom, and carries the fix.
    assert "SHALLOW" in result.stdout, output
    assert "fetch-depth: 0" in result.stdout, output
    assert "git fetch --unshallow" in result.stdout, output


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_this_file_passes_the_gate_it_tests():
    """Fixtures for a secret-scan gate get scanned by that gate.

    Both 40-hex values and the planted AWS key here are inert test data, and
    each carries `# pragma: allowlist secret` on its own line — which is the
    only place detect-secrets looks, since it matches per line. That is easy to
    get wrong by accident: black reflows a call and carries the trailing comment
    to the closing-paren line, away from the literal, and the pragma stops
    applying while still reading as if it does. Exactly that shipped in #1778
    and was caught by CI rather than here.
    """
    result = subprocess.run(
        ["bash", str(_GATE), "tests/oversight/test_secret_scan_validator_artifact.py"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tests_workflow_checks_out_full_history():
    """The environment half of the fix, pinned against config drift.

    `.github/workflows/tests.yml` runs this suite, which drives the real gate
    against real repo history. Restoring the actions/checkout default would
    make the test above pass (it branches on shallowness) while the gate it
    guards is broken for every PR — so the workflow is asserted directly.
    """
    workflow = (_REPO / ".github" / "workflows" / "tests.yml").read_text()
    assert "fetch-depth: 0" in workflow
