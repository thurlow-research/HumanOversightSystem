"""Shell smoke tests for scripts/run_release_panel.sh and the
--release-range argument handling in scripts/run_panel.sh (ADR-1340;
docs/v0.7.0/TECHNICAL-DESIGN-1340-release-panel.md §5.4).

Mirrors this repo's existing pytest-drives-bash idiom (see
tests/oversight/test_red_team_fail_closed.py): the real scripts are driven as
real subprocesses, hermetically — a temp dir is used as the script's own
REPO_ROOT (never this clone), and any GitHub/vendor-CLI touchpoint is either
unreachable by construction (argument-parsing failures fire before any
network code runs) or stubbed to a script that refuses to be a real call.

The verify-mode tests need `scripts/run_release_panel.sh`'s OWN notion of its
repo root (computed from `dirname "${BASH_SOURCE[0]}"`) to point at a
throwaway git repo we fully control — never this clone's real tags/history.
We do that by symlinking the real, unmodified implementation files into a
tmp_path tree and `git init`-ing tmp_path itself:

  <tmp>/scripts/run_release_panel.sh          -> real (symlink)
  <tmp>/scripts/run_panel.sh                  -> real (symlink) or a fail-stub
  <tmp>/scripts/oversight/release_panel_logic.py       -> real (symlink)
  <tmp>/scripts/oversight/release_panel_exclusions.txt -> real (symlink)
  <tmp>/bootstrap/post_comment.sh             -> stub (never invoked by the
                                                  cases below; only its
                                                  existence is preflight-checked)
  <tmp>/bootstrap/query_issues.sh             -> stub that `cat`s a fixture
                                                  NDJSON comments file
  <tmp>/.git                                  -> a real, local, throwaway repo

`release_panel_logic.py`'s own `sys.path` bootstrap (`Path(__file__).resolve()`)
follows the symlink back to this clone's real `scripts/framework/` package for
imports — harmless, since that package is read-only stdlib-only code and is
not what these tests are pinning.

Coverage (TD §5.4 IDs):
  T-S-1   verify PASS against a fixture that matches the temp repo
  T-S-2   verify with a MUTATED head_sha in the posted verdict — see the
          docstring on that test for a discovered TD/code divergence
  T-S-3   verify with no verdict block -> verdict-missing
  T-S-4   verify invokes no vendor CLI / run_panel.sh (AD-7's hard prohibition)
  T-S-5   run_panel.sh --release-range + a PR# -> mutual exclusivity (AD-1)
  T-S-6   run_panel.sh --release-range with an abbreviated/symbolic range
  T-S-7   run_panel.sh --release-range + --record -> ledger is PR-mode only
  T-S-8   run_release_panel.sh in a shallow repo -> exit 2, remediation printed
  T-S-9   --verify --dry-run -> usage error
  T-S-10  --verify with no resolvable author -> exit 1, author-unresolved
  T-S-11  every exit code in TD §2.5 is documented in --help (+ reachability)

Not covered here (TD §5.5): a PR-mode regression test for run_panel.sh is
deliberately NOT written — run_panel.sh's PR mode has never executed in this
repository, so there is no baseline to assert against.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_RELEASE_PANEL = _REPO_ROOT / "scripts" / "run_release_panel.sh"
_RUN_PANEL = _REPO_ROOT / "scripts" / "run_panel.sh"
_RELEASE_LOGIC = _REPO_ROOT / "scripts" / "oversight" / "release_panel_logic.py"
_EXCLUSIONS = _REPO_ROOT / "scripts" / "oversight" / "release_panel_exclusions.txt"

sys.path.insert(0, str(_REPO_ROOT / "scripts" / "oversight"))
import release_panel_logic as rpl  # noqa: E402  (path set up above)

_AUTHOR = "hos-worker-hos[bot]"


# --------------------------------------------------------------------------- #
# Tree-building helpers                                                       #
# --------------------------------------------------------------------------- #
def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_release_tree(root: Path, *, panel_stub_fails: bool = False) -> None:
    (root / "scripts" / "oversight").mkdir(parents=True)
    (root / "bootstrap").mkdir(parents=True)

    (root / "scripts" / "run_release_panel.sh").symlink_to(_RUN_RELEASE_PANEL)
    (root / "scripts" / "oversight" / "release_panel_logic.py").symlink_to(_RELEASE_LOGIC)
    (root / "scripts" / "oversight" / "release_panel_exclusions.txt").symlink_to(_EXCLUSIONS)

    if panel_stub_fails:
        _write_exec(
            root / "scripts" / "run_panel.sh",
            "#!/usr/bin/env bash\n"
            'echo "FAIL-ON-CALL: run_panel.sh must never be invoked in --verify mode" >&2\n'
            "exit 99\n",
        )
    else:
        (root / "scripts" / "run_panel.sh").symlink_to(_RUN_PANEL)

    # Preflight only checks existence; never invoked by any case in this file.
    _write_exec(root / "bootstrap" / "post_comment.sh", "#!/usr/bin/env bash\nexit 0\n")


def _init_tagged_repo(root: Path) -> None:
    """A real, local, non-shallow repo with one tag and one commit past it."""
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("base\n")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "base", cwd=root)
    _git("tag", "v1.0.0", cwd=root)
    (root / "app.py").write_text("print('release candidate')\n")
    _git("add", "app.py", cwd=root)
    _git("commit", "-q", "-m", "release candidate", cwd=root)


def _init_shallow_repo(tmp_path: Path, dest: Path) -> None:
    """A real, local, SHALLOW clone (git clone --depth 1) — no network."""
    src = tmp_path / "_src"
    src.mkdir()
    _init_tagged_repo(src)
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{src}", str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )


def _derive(root: Path) -> rpl.RangeResult:
    return rpl.derive_range(
        cwd=str(root),
        exclusions_path=str(root / "scripts" / "oversight" / "release_panel_exclusions.txt"),
    )


def _build_pass_body(
    root: Path, *, author: str = _AUTHOR, head_sha: str | None = None
) -> tuple[rpl.RangeResult, dict, str]:
    """Derive the real range for `root`'s temp repo, compose a genuine PASS
    verdict for it, and render the comment body extract_verdicts/select_verdict
    will parse — the same functions the shell CLI itself calls, so the fixture
    is guaranteed consistent with what a real run would produce."""
    rr = _derive(root)
    panel = {
        "chunks_attempted": 1,
        "chunks_completed": 1,
        "findings": {"total": 0, "tier1": 0, "tier2": 0, "tier1_undispositioned": 0},
        "arbiter_salvaged": False,
        "effective_tier": "MEDIUM",
        "deterministic_floor": "MEDIUM",
        "validator_tier": "MEDIUM",
        "sqc": {"sampled": False, "rate": 0, "advisory": True},
        "roster": [{"reviewer": "agy", "lens": "correctness", "status": "ok"}],
        "run_dir": str(root),
        "arbiter_sha256": "a" * 64,
        "findings_raw_sha256": "b" * 64,
    }
    verdict = rpl.compose_verdict(
        range_result=rr,
        panel=panel,
        exclusions_path=str(root / "scripts" / "oversight" / "release_panel_exclusions.txt"),
        run_id="test-run-id",
        issue=1,
        panel_exit_code=0,
    )
    if head_sha is not None:
        verdict["range"]["head_sha"] = head_sha
    body = rpl.render_comment_body(verdict=verdict, panel_summary_md="panel summary body")
    return rr, verdict, body


def _write_query_issues_stub(root: Path, fixture: Path) -> None:
    _write_exec(
        root / "bootstrap" / "query_issues.sh",
        f"#!/usr/bin/env bash\ncat {fixture}\n",
    )


def _write_query_issues_fail_stub(root: Path) -> None:
    _write_exec(
        root / "bootstrap" / "query_issues.sh",
        "#!/usr/bin/env bash\n"
        'echo "FAIL-ON-CALL: query_issues.sh must never be invoked (T-S-9/T-S-10 usage errors fire before it)" >&2\n'
        "exit 98\n",
    )


def _ndjson(entries: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in entries) + "\n"


def _run(
    root: Path, *args: str, extra_path: Path | None = None, env_overrides: dict | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("HOS_EXPECTED_BOT_LOGIN", None)
    if extra_path is not None:
        env["PATH"] = os.pathsep.join([str(extra_path), env.get("PATH", "")])
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(root / "scripts" / "run_release_panel.sh"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _last_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# --------------------------------------------------------------------------- #
# T-S-1 — verify PASS against a fixture matching the temp repo                #
# --------------------------------------------------------------------------- #
def test_ts1_verify_pass_against_matching_fixture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root)
    _init_tagged_repo(root)

    _, verdict, body = _build_pass_body(root)
    fixture = tmp_path / "comments.ndjson"
    fixture.write_text(
        _ndjson([{"user": _AUTHOR, "created_at": "2026-01-01T00:00:01Z", "body": body}])
    )
    _write_query_issues_stub(root, fixture)

    result = _run(root, "--verify", "--issue", "1", "--author", _AUTHOR)
    assert result.returncode == 0, result.stdout + result.stderr
    last = _last_line(result.stdout)
    assert last.startswith("release-panel: verify PASS reason=none"), result.stdout
    assert verdict["result"] == "PASS"


# --------------------------------------------------------------------------- #
# T-S-2 — a mutated head_sha in the posted verdict                            #
# --------------------------------------------------------------------------- #
def test_ts2_mutated_head_sha_in_posted_verdict(tmp_path):
    """TD §5.4 T-S-2 specifies this case as "exit 8, reason=head-sha-mismatch"
    (i.e. AD-7 check 2 failing). That is NOT what the shipped `--verify` CLI
    does, and this test pins the ACTUAL behaviour rather than fabricating an
    assertion that doesn't match the code (see this file's module docstring
    and the unit-test agent's final report for the full analysis):

    `_cmd_verify` calls `select_verdict(candidates, head_sha=range_result.head_sha,
    author=...)` BEFORE it ever calls `verify_verdict`. `select_verdict`
    filters candidates on `verdict["range"]["head_sha"] == head_sha` (AD-7 §3
    step 2) — a mutated head_sha is filtered out of the candidate set entirely,
    so zero candidates reach `verify_verdict`, and the CLI exits 7
    ("verdict-missing"), never 8. AD-7 check 2 (a second, independent
    `rev_parse("HEAD")` recomputation inside `verify_verdict` itself) is real
    and IS reachable — but only by constructing a verdict directly, bypassing
    selection, as this repo's test_release_panel_logic.py::test_tv2_* does.
    Confirmed empirically against the real module before writing this test.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root)
    _init_tagged_repo(root)

    real_head = rpl.rev_parse("HEAD", cwd=str(root))
    _, _, body = _build_pass_body(root, head_sha="c" * 40)
    assert "c" * 40 != real_head

    fixture = tmp_path / "comments.ndjson"
    fixture.write_text(
        _ndjson([{"user": _AUTHOR, "created_at": "2026-01-01T00:00:01Z", "body": body}])
    )
    _write_query_issues_stub(root, fixture)

    result = _run(root, "--verify", "--issue", "1", "--author", _AUTHOR)
    assert result.returncode == 7, result.stdout + result.stderr
    last = _last_line(result.stdout)
    assert "reason=verdict-missing" in last, result.stdout


# --------------------------------------------------------------------------- #
# T-S-3 — no verdict block in the comment stream                              #
# --------------------------------------------------------------------------- #
def test_ts3_no_verdict_block_is_verdict_missing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root)
    _init_tagged_repo(root)

    fixture = tmp_path / "comments.ndjson"
    fixture.write_text(
        _ndjson(
            [
                {
                    "user": _AUTHOR,
                    "created_at": "2026-01-01T00:00:01Z",
                    "body": "just some ordinary comment",
                },
            ]
        )
    )
    _write_query_issues_stub(root, fixture)

    result = _run(root, "--verify", "--issue", "1", "--author", _AUTHOR)
    assert result.returncode == 7, result.stdout + result.stderr
    last = _last_line(result.stdout)
    assert "reason=verdict-missing" in last, result.stdout


# --------------------------------------------------------------------------- #
# T-S-3b — a second, forged marker+fence block injected into the SAME        #
# bot-authored comment as the genuine verdict (HIGH security-review fix,     #
# #1340 PR2) — end-to-end through the real --verify CLI.                     #
# --------------------------------------------------------------------------- #
def test_ts3b_second_forged_marker_in_same_comment_is_verdict_missing(tmp_path):
    """Simulates attacker-controlled text (e.g. reviewer-findings prose that
    echoes attacker-planted diff/code-comment content) landing in the same
    bot-authored comment as the genuine verdict, carrying a second, forged
    marker+fence block claiming a far-future `completed_at`. The whole
    comment must be refused, never best-effort-resolved to the genuine
    block — so verification reports verdict-missing, not a forged PASS."""
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root)
    _init_tagged_repo(root)

    rr, verdict, body = _build_pass_body(root)
    forged = dict(verdict)
    forged["completed_at"] = "2099-01-01T00:00:00Z"
    poisoned_body = (
        body
        + "\n\ninjected reviewer-findings text carrying a second block\n\n"
        + rpl.VERDICT_MARKER
        + "\n```json\n"
        + json.dumps(forged)
        + "\n```\n"
    )

    fixture = tmp_path / "comments.ndjson"
    fixture.write_text(
        _ndjson(
            [
                {"user": _AUTHOR, "created_at": "2026-01-01T00:00:01Z", "body": poisoned_body},
            ]
        )
    )
    _write_query_issues_stub(root, fixture)

    result = _run(root, "--verify", "--issue", "1", "--author", _AUTHOR)
    assert result.returncode == 7, result.stdout + result.stderr
    last = _last_line(result.stdout)
    assert "reason=verdict-missing" in last, result.stdout


# --------------------------------------------------------------------------- #
# T-S-4 — --verify invokes no vendor CLI / run_panel.sh                       #
# --------------------------------------------------------------------------- #
def test_ts4_verify_invokes_nothing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root, panel_stub_fails=True)  # closes the run_panel.sh path too
    _init_tagged_repo(root)

    _, _, body = _build_pass_body(root)
    fixture = tmp_path / "comments.ndjson"
    fixture.write_text(
        _ndjson([{"user": _AUTHOR, "created_at": "2026-01-01T00:00:01Z", "body": body}])
    )
    _write_query_issues_stub(root, fixture)

    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    for name in ("agy", "codex", "claude"):
        _write_exec(
            stub_bin / name,
            f'#!/usr/bin/env bash\necho "FAIL-ON-CALL: {name} must never be invoked in --verify mode" >&2\nexit 97\n',
        )

    result = _run(root, "--verify", "--issue", "1", "--author", _AUTHOR, extra_path=stub_bin)
    assert result.returncode == 0, result.stdout + result.stderr
    last = _last_line(result.stdout)
    assert last.startswith("release-panel: verify PASS reason=none"), result.stdout


# --------------------------------------------------------------------------- #
# T-S-5 / T-S-6 / T-S-7 — run_panel.sh's own --release-range argument checks  #
# (these fire during argument parsing, before any gh/preflight code — no      #
# tree or repo needed, the real script is invoked directly).                  #
# --------------------------------------------------------------------------- #
def test_ts5_release_range_and_pr_number_mutually_exclusive():
    result = subprocess.run(
        ["bash", str(_RUN_PANEL), "--release-range", "X..Y", "42"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "mutually exclusive" in result.stderr


def test_ts6_abbreviated_or_symbolic_range_rejected():
    result = subprocess.run(
        ["bash", str(_RUN_PANEL), "--release-range", "HEAD~1..HEAD"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "40-hex" in result.stderr


def test_ts7_record_is_pr_mode_only():
    result = subprocess.run(
        ["bash", str(_RUN_PANEL), "--release-range", "X..Y", "--record", "a", "b", "c"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "PR-mode only" in result.stderr


# --------------------------------------------------------------------------- #
# T-S-8 — run_release_panel.sh in a shallow repo                              #
# --------------------------------------------------------------------------- #
def test_ts8_shallow_repo_refuses_with_remediation(tmp_path):
    root = tmp_path / "repo"
    # `git clone` creates `root` itself; the release-panel tree is layered
    # into that same directory afterwards (order matters: clone first).
    _init_shallow_repo(tmp_path, root)
    (root / "scripts" / "oversight").mkdir(parents=True)
    (root / "bootstrap").mkdir(parents=True)
    (root / "scripts" / "run_release_panel.sh").symlink_to(_RUN_RELEASE_PANEL)
    (root / "scripts" / "run_panel.sh").symlink_to(_RUN_PANEL)
    (root / "scripts" / "oversight" / "release_panel_logic.py").symlink_to(_RELEASE_LOGIC)
    (root / "scripts" / "oversight" / "release_panel_exclusions.txt").symlink_to(_EXCLUSIONS)
    _write_exec(root / "bootstrap" / "post_comment.sh", "#!/usr/bin/env bash\nexit 0\n")

    assert rpl.is_shallow(cwd=str(root)) is True  # sanity: genuinely shallow

    result = _run(root, "--issue", "5")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "git fetch --unshallow --tags" in result.stderr


# --------------------------------------------------------------------------- #
# T-S-9 — --verify --dry-run is a usage error                                 #
# --------------------------------------------------------------------------- #
def test_ts9_verify_dry_run_is_usage_error():
    # Fires before any preflight/file-existence check, so the real script can
    # be invoked directly with no tree at all.
    result = subprocess.run(
        ["bash", str(_RUN_RELEASE_PANEL), "--verify", "--dry-run", "--issue", "1"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "--verify --dry-run" in result.stderr


# --------------------------------------------------------------------------- #
# T-S-10 — --verify with no resolvable author                                 #
# --------------------------------------------------------------------------- #
def test_ts10_verify_no_resolvable_author(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_release_tree(root)
    _write_query_issues_fail_stub(root)  # must never even be reached
    _init_tagged_repo(root)

    # No --author, no HOS_EXPECTED_BOT_LOGIN, and no
    # scripts/framework/machine-accounts.env in this tree -> unresolvable.
    result = _run(root, "--verify", "--issue", "1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "author-unresolved" in result.stderr


# --------------------------------------------------------------------------- #
# T-S-11 — every exit code in TD §2.5 is documented in --help and reachable   #
# in the script's own source (static presence, since not every code is       #
# exercised by the cases above — e.g. NO_TAG/operational failures/FAIL-posted #
# are execute-mode paths this PR is deliberately inert for; #1340 PR 1 never  #
# runs live).                                                                 #
# --------------------------------------------------------------------------- #
def test_ts11_help_documents_every_exit_code():
    result = subprocess.run(
        ["bash", str(_RUN_RELEASE_PANEL), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for code in range(9):
        assert re.search(
            rf"(?m)^\s*{code}\s", result.stdout
        ), f"exit code {code} not documented in --help:\n{result.stdout}"


def test_ts11_every_exit_code_reachable_in_source():
    # Codes 0-6 appear as literal `exit N` in run_release_panel.sh. Codes 7/8
    # (verify mode only) are NOT literal in the shell — the script propagates
    # whatever `release_panel_logic.py verify` returned via `exit "$VERIFY_EXIT"`
    # (see run_release_panel.sh's own tail) — so their reachability is pinned
    # in the Python CLI itself (_cmd_verify's own `return 7` / `return 8`)
    # plus the shell's pass-through, rather than a literal grep on this file.
    src = _RUN_RELEASE_PANEL.read_text()
    for code in range(7):
        assert re.search(rf"exit {code}\b", src), f"exit {code} not present in run_release_panel.sh"

    assert (
        'exit "$VERIFY_EXIT"' in src
    ), "run_release_panel.sh must propagate verify's own exit code (7/8) verbatim"
    logic_src = _RELEASE_LOGIC.read_text()
    assert re.search(
        r"return 7\b", logic_src
    ), "exit 7 (verdict-missing) not reachable in release_panel_logic.py"
    assert re.search(
        r"return 8\b", logic_src
    ), "exit 8 (a verify check failed) not reachable in release_panel_logic.py"
