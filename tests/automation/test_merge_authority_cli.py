"""
Tests for scripts/automation/merge_authority_cli.py — the L2 read-only
primitive surface (#1357 slice 1).

T1-T6 per docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md §10.
Calls `main(argv=[...], repo_root=<fixture>)` in-process with `github.py`'s
read helpers patched — the same mocking model the 157 pre-existing library
tests already use — never a subprocess, never real `gh`.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

import scripts.automation.merge_authority_cli as cli
from scripts.automation.lib import github as gh
from scripts.automation.lib import merge_authority

_ENV = {
    "BOT_WORKER_USERNAME": "hos-worker-hos[bot]",
    "BOT_OVERSEER_USERNAME": "hos-overseer-hos[bot]",
    "BOT_ACCOUNTS": "hos-worker-hos[bot] hos-overseer-hos[bot] scottthurlow-claude[bot]",
    "OVERSEER_CEILING": "HIGH",
    "TIER_CEILING_CHECK_NAME": "require-tier-ceiling",
    "HUMAN_REVIEWER": "ScottThurlow",
}


def _write_config(root: Path, env: dict | None = None) -> None:
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True, exist_ok=True)
    values = dict(_ENV)
    if env:
        values.update(env)
    lines = [f'{k}="{v}"' for k, v in values.items()]
    (fw / "machine-accounts.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_surfaces_file(root: Path, relpath: str, patterns: list[str]) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(patterns) + "\n", encoding="utf-8")


def _add_manifest(root: Path, step: str, required_signoffs: list[str]) -> None:
    p = root / "contract" / "step-manifest.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    entries = ", ".join(required_signoffs)
    p.write_text(
        f'steps:\n  - id: "{step}"\n    required_signoffs: [{entries}]\n',
        encoding="utf-8",
    )


def _add_register(root: Path, step: str, role: str, status: str = "APPROVED") -> None:
    p = root / ".claudetmp" / "signoffs" / f"step{step}-register.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## {role}",
        f"Status: {status}",
        "Agent: some-agent",
        "Artifact: some-artifact",
        "Iterations: 1",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_codeowners(root: Path, lines: list[str]) -> None:
    p = root / ".github" / "CODEOWNERS"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def repo_root(tmp_path) -> Path:
    root = tmp_path / "repo"
    _write_config(root)
    return root


@pytest.fixture
def mocked_github(monkeypatch):
    """Default successful stubs for all four new github.py helpers plus the
    two `gate` reads — the same mocking model the 157 pre-existing tests use
    for github.py. Individual tests override one attribute for a corner case."""
    monkeypatch.setattr(gh, "get_pull", lambda o, r, n: {"head": {"sha": "abc123"}})
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: [{"filename": "some/file.py"}])
    monkeypatch.setattr(
        gh,
        "get_commit",
        lambda o, r, ref: {"commit": {"committer": {"date": "2026-09-01T00:00:00Z"}}},
    )
    monkeypatch.setattr(gh, "list_issue_comments", lambda o, r, n: [])
    monkeypatch.setattr(gh, "get_repo", lambda o, r: {"default_branch": "main"})
    monkeypatch.setattr(
        gh,
        "get_branch_protection",
        lambda o, r, b: {"required_status_checks": {"contexts": ["require-tier-ceiling"]}},
    )
    return gh


def _record(capsys) -> dict:
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {out!r}"
    return json.loads(lines[0])


# --------------------------------------------------------------------------- #
# T1 — argv contract
# --------------------------------------------------------------------------- #

_ALL_ARGVS = {
    "gate": ["gate", "--app", "overseer", "--repo", "o/r"],
    "register": ["register", "--app", "overseer", "--step", "1"],
    "bounce-count": ["bounce-count", "--app", "overseer", "--cid", "abc"],
    "human-approval": ["human-approval", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
    "hold-directive": ["hold-directive", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
    "protected-surface": ["protected-surface", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
    "security-surface": ["security-surface", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
    "codeowners": ["codeowners", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
}


@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t1_1_every_subcommand_parses_and_dispatches(subcommand, repo_root, mocked_github, capsys):
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0, record
    assert record["subcommand"] == subcommand


def test_t1_2_unknown_flag_exits_2(repo_root, capsys):
    rc = cli.main(["gate", "--app", "overseer", "--bogus", "x"], repo_root=str(repo_root))
    assert rc == 2
    record = _record(capsys)
    assert record["error"] is not None


@pytest.mark.parametrize(
    "argv",
    [
        ["gate", "--ap", "overseer"],
        ["route", "--ap", "overseer", "--pr", "1", "--step", "issue-1", "--findings-file", "f"],
    ],
)
def test_t1_2_abbreviated_flag_exits_2(argv, repo_root, capsys):
    rc = cli.main(argv, repo_root=str(repo_root))
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_2_unknown_subcommand_exits_2(repo_root, capsys):
    rc = cli.main(["not-a-subcommand", "--app", "overseer"], repo_root=str(repo_root))
    assert rc == 2
    record = _record(capsys)
    assert record["error"] is not None


def test_t1_3_non_numeric_pr_exits_2(repo_root, capsys):
    rc = cli.main(
        ["human-approval", "--app", "overseer", "--pr", "abc", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_3_missing_pr_on_pr_subcommand_exits_2(repo_root, capsys):
    rc = cli.main(
        ["human-approval", "--app", "overseer", "--repo", "o/r"], repo_root=str(repo_root)
    )
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_4_missing_app_exits_2(repo_root, capsys):
    rc = cli.main(["gate", "--repo", "o/r"], repo_root=str(repo_root))
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_4_invalid_app_exits_2(repo_root, capsys):
    rc = cli.main(["gate", "--app", "bogus", "--repo", "o/r"], repo_root=str(repo_root))
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_5_malformed_step_exits_2(repo_root, capsys):
    rc = cli.main(
        ["register", "--app", "overseer", "--step", "not valid!"], repo_root=str(repo_root)
    )
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_5_malformed_cid_exits_2(repo_root, capsys):
    rc = cli.main(
        ["bounce-count", "--app", "overseer", "--cid", "not valid!"], repo_root=str(repo_root)
    )
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_5_empty_cid_exits_2(repo_root, capsys):
    rc = cli.main(["bounce-count", "--app", "overseer", "--cid", ""], repo_root=str(repo_root))
    assert rc == 2
    assert _record(capsys)["error"] is not None


def test_t1_6_every_exit_2_path_prints_one_parseable_envelope(repo_root, capsys):
    rc = cli.main(["gate", "--app", "bogus"], repo_root=str(repo_root))
    assert rc == 2
    record = _record(capsys)
    assert record["schema_version"] == 1
    assert record["error"] is not None
    assert "not_verified" in record
    assert isinstance(record["not_verified"], list)


_WIDENING_FLAGS = (
    "--force",
    "--skip-checks",
    "--no-verify",
    "--config",
    "--head-sha",
    "--manifest",
    "--repo-root",
)


@pytest.mark.parametrize("flag", _WIDENING_FLAGS)
@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t1_7_no_widening_or_policy_source_flag_on_any_subcommand(
    subcommand, flag, repo_root, capsys
):
    argv = list(_ALL_ARGVS[subcommand]) + [flag, "x"]
    rc = cli.main(argv, repo_root=str(repo_root))
    assert rc == 2, f"{flag} on {subcommand} did not exit 2"


def test_t1_8_repo_root_injection_not_reachable_from_argv(repo_root, capsys):
    # In-process injection works.
    rc = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    assert rc == 0
    _record(capsys)

    # The identical value on the command line is rejected (unrecognised flag).
    rc2 = cli.main(
        ["register", "--app", "overseer", "--step", "1", "--repo-root", str(repo_root)],
        repo_root=str(repo_root),
    )
    assert rc2 == 2
    _record(capsys)


def test_t1_8_main_signature_keyword_only_repo_root_not_populated_by_dunder_main():
    import inspect

    sig = inspect.signature(cli.main)
    assert sig.parameters["repo_root"].kind == inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------- #
# T2 — fetch -> call marshalling
# --------------------------------------------------------------------------- #


def test_t2_1_human_approval_passes_real_head_sha(repo_root, mocked_github, monkeypatch, capsys):
    captured = {}

    def fake_has_approval(reviews, human_reviewer, head_sha):
        captured["head_sha"] = head_sha
        return False

    monkeypatch.setattr(merge_authority, "has_human_approval", fake_has_approval)
    monkeypatch.setattr(merge_authority, "_find_human_approval", lambda *a, **k: None)

    rc = cli.main(
        ["human-approval", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 0
    _record(capsys)
    assert captured["head_sha"] == "abc123"
    assert captured["head_sha"] is not None


def test_t2_2_missing_head_sha_exits_1(repo_root, mocked_github, monkeypatch, capsys):
    monkeypatch.setattr(gh, "get_pull", lambda o, r, n: {"head": {"sha": ""}})
    rc = cli.main(
        ["human-approval", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 1
    record = _record(capsys)
    assert record["error"] is not None


def test_t2_3_has_approval_follows_decision_not_evidence(
    repo_root, mocked_github, monkeypatch, capsys
):
    # Evidence filter would match (an APPROVED review from the reviewer at the
    # head sha), but the decision function says False — the disagreement must
    # be detected as an internal inconsistency, exit 1.
    monkeypatch.setattr(
        gh,
        "list_pull_reviews",
        lambda o, r, n: [
            {"state": "APPROVED", "user": {"login": "ScottThurlow"}, "commit_id": "abc123"}
        ],
    )
    monkeypatch.setattr(merge_authority, "has_human_approval", lambda *a, **k: False)

    rc = cli.main(
        ["human-approval", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 1
    record = _record(capsys)
    assert "disagree" in record["error"]


def test_t2_4_hold_directive_passes_fetched_commit_date(
    repo_root, mocked_github, monkeypatch, capsys
):
    captured = {}

    def fake_detect(comments, human_reviewer, head_committed_at):
        captured["head_committed_at"] = head_committed_at
        return None

    monkeypatch.setattr(merge_authority, "detect_human_hold_directive", fake_detect)
    rc = cli.main(
        ["hold-directive", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 0
    record = _record(capsys)
    assert captured["head_committed_at"] == "2026-09-01T00:00:00Z"
    assert record["not_verified"] == []


def test_t2_4_hold_directive_commit_read_failure_passes_none_and_discloses(
    repo_root, mocked_github, monkeypatch, capsys
):
    monkeypatch.setattr(
        gh, "get_commit", lambda o, r, ref: (_ for _ in ()).throw(gh.GitHubError("boom"))
    )
    captured = {}

    def fake_detect(comments, human_reviewer, head_committed_at):
        captured["head_committed_at"] = head_committed_at
        return None

    monkeypatch.setattr(merge_authority, "detect_human_hold_directive", fake_detect)
    rc = cli.main(
        ["hold-directive", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 0
    record = _record(capsys)
    assert captured["head_committed_at"] is None
    assert any("head_committed_at" in nv for nv in record["not_verified"])


def test_t2_5_protected_surface_matched_paths_only_l1_matches(
    repo_root, mocked_github, monkeypatch, capsys
):
    _add_surfaces_file(repo_root, "scripts/framework/protected_surfaces.txt", ["bootstrap/*"])
    monkeypatch.setattr(
        gh,
        "list_pull_files",
        lambda o, r, n: [{"filename": "bootstrap/x.sh"}, {"filename": "docs/y.md"}],
    )
    rc = cli.main(
        ["protected-surface", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 0
    record = _record(capsys)
    assert record["touches"] is True
    assert record["matched_paths"] == ["bootstrap/x.sh"]


def test_t2_6_codeowners_passes_resolved_bot_accounts(
    repo_root, mocked_github, monkeypatch, capsys
):
    captured = {}
    real_check_pr_files = None

    def fake_load_codeowners_module():
        import types

        def fake_check_pr_files(file_list, repo_root, bot_accounts):
            captured["bot_accounts"] = bot_accounts
            return (False, [], "no CODEOWNERS-human-owned path matched")

        mod = types.SimpleNamespace(check_pr_files=fake_check_pr_files)
        return mod

    monkeypatch.setattr(cli, "_load_codeowners_module", fake_load_codeowners_module)
    rc = cli.main(
        ["codeowners", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 0
    _record(capsys)
    assert captured["bot_accounts"] is not None
    assert captured["bot_accounts"] == {
        "hos-worker-hos[bot]",
        "hos-overseer-hos[bot]",
        "scottthurlow-claude[bot]",
    }
    del real_check_pr_files


def test_t2_6_codeowners_missing_bot_accounts_exits_1(repo_root, mocked_github, capsys):
    lines = [
        line
        for line in (repo_root / "scripts" / "framework" / "machine-accounts.env")
        .read_text()
        .splitlines()
        if not line.startswith("BOT_ACCOUNTS=")
    ]
    (repo_root / "scripts" / "framework" / "machine-accounts.env").write_text(
        "\n".join(lines) + "\n"
    )
    rc = cli.main(
        ["codeowners", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    assert rc == 1
    record = _record(capsys)
    assert record["error"] is not None


def test_t2_7_gate_passes_resolved_overseer_handle(repo_root, mocked_github, monkeypatch, capsys):
    captured = {}

    def fake_detect(owner, repo, branch, overseer_handle):
        captured["overseer_handle"] = overseer_handle
        return merge_authority.GateDetectionResult(autonomous_capable=False, reason="stub")

    monkeypatch.setattr(merge_authority, "detect_server_side_gate", fake_detect)
    rc = cli.main(["gate", "--app", "overseer", "--repo", "o/r"], repo_root=str(repo_root))
    assert rc == 0
    _record(capsys)
    assert captured["overseer_handle"] == "hos-overseer-hos[bot]"
    assert (
        captured["overseer_handle"] != merge_authority.DEFAULT_OVERSEER_HANDLE or True
    )  # documented value used


def test_t2_8_bounce_count_calls_library_once_no_direct_audit_read(repo_root, monkeypatch, capsys):
    calls = []

    def fake_bounce_count(cid, *, repo_root):
        calls.append(cid)
        return 3

    monkeypatch.setattr(merge_authority, "bounce_count", fake_bounce_count)

    def fail_read_stream(*a, **k):
        raise AssertionError("CLI must never read audit/log/** itself")

    monkeypatch.setattr(merge_authority._AUDIT_LOG, "read_stream", fail_read_stream)

    rc = cli.main(["bounce-count", "--app", "overseer", "--cid", "abc"], repo_root=str(repo_root))
    assert rc == 0
    record = _record(capsys)
    assert calls == ["abc"]
    assert record["count"] == 3


# --------------------------------------------------------------------------- #
# T4 — record schema
# --------------------------------------------------------------------------- #

_PAYLOAD_KEYS = {
    "gate": {
        "autonomous_capable",
        "reason",
        "branch",
        "branch_source",
        "checked_contexts",
        "tier_ceiling_check_name",
        "tier_ceiling_check_required",
        "overseer_handle",
    },
    "register": {
        "step",
        "bounce_required",
        "failures",
        "reason_category",
        "summary",
        "register_path",
        "manifest_path",
        "required_signoffs",
        "required_roles_resolved",
        "gate_evaluable",
    },
    "bounce-count": {"cid", "count", "cap", "at_cap", "cap_source", "query"},
    "human-approval": {
        "head_sha",
        "human_reviewer",
        "has_approval",
        "approver",
        "approved_sha",
        "approved_at",
        "stale_approvals",
        "reviews_scanned",
    },
    "hold-directive": {
        "head_sha",
        "head_committed_at",
        "hold_active",
        "comment_url",
        "created_at",
        "matched_phrase",
        "human_reviewer",
        "comments_scanned",
    },
    "protected-surface": {
        "touches",
        "matched_paths",
        "changed_file_count",
        "surfaces_file",
        "surfaces_file_present",
    },
    "security-surface": {
        "touches",
        "matched_paths",
        "changed_file_count",
        "surfaces_file",
        "surfaces_file_present",
    },
    "codeowners": {
        "required",
        "matched_paths",
        "reason",
        "changed_file_count",
        "codeowners_path",
        "codeowners_present",
        "bot_accounts",
    },
}

_ENVELOPE_KEYS = {
    "schema_version",
    "subcommand",
    "computed_at",
    "repo",
    "repo_root",
    "pr",
    "config_source",
    "app_role",
    "not_verified",
    "error",
}


@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t4_1_envelope_present_on_every_subcommand(subcommand, repo_root, mocked_github, capsys):
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["schema_version"] == 1
    assert _ENVELOPE_KEYS.issubset(record.keys())
    assert isinstance(record["not_verified"], list)


@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t4_2_documented_payload_keys_present(subcommand, repo_root, mocked_github, capsys):
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert _PAYLOAD_KEYS[subcommand].issubset(record.keys())


def test_t4_3_register_reason_category_closed_enum(repo_root, capsys):
    _add_manifest(repo_root, "1", ["code-review"])
    rc = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["reason_category"] in (
        None,
        "REGISTER_GAP",
        "COMPLIANCE_FAILURE",
        "SPEC_AMBIGUITY",
        "OTHER",
    )


def test_t4_4_degraded_evidence_fetch_exit_0_null_field_not_verified(
    repo_root, mocked_github, monkeypatch, capsys
):
    monkeypatch.setattr(
        gh, "get_branch_protection", lambda o, r, b: (_ for _ in ()).throw(gh.GitHubError("boom"))
    )
    rc = cli.main(["gate", "--app", "overseer", "--repo", "o/r"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["checked_contexts"] is None
    assert any("checked_contexts" in nv for nv in record["not_verified"])


def test_t4_5_failed_required_fetch_exit_1_envelope_only(
    repo_root, mocked_github, monkeypatch, capsys
):
    monkeypatch.setattr(
        gh, "get_pull", lambda o, r, n: (_ for _ in ()).throw(gh.GitHubError("boom"))
    )
    rc = cli.main(
        ["human-approval", "--app", "overseer", "--pr", "42", "--repo", "o/r"],
        repo_root=str(repo_root),
    )
    record = _record(capsys)
    assert rc == 1
    assert record["error"] is not None
    assert "has_approval" not in record


def test_t4_6_gate_result_verbatim_and_tier_ceiling_does_not_influence_decision(
    repo_root, mocked_github, monkeypatch, capsys
):
    monkeypatch.setattr(
        merge_authority,
        "detect_server_side_gate",
        lambda *a, **k: merge_authority.GateDetectionResult(
            autonomous_capable=True, reason="exact reason text"
        ),
    )

    monkeypatch.setattr(
        gh,
        "get_branch_protection",
        lambda o, r, b: {"required_status_checks": {"contexts": ["require-tier-ceiling"]}},
    )
    rc = cli.main(["gate", "--app", "overseer", "--repo", "o/r"], repo_root=str(repo_root))
    record_true_ctx = _record(capsys)

    monkeypatch.setattr(
        gh, "get_branch_protection", lambda o, r, b: {"required_status_checks": {"contexts": []}}
    )
    rc2 = cli.main(["gate", "--app", "overseer", "--repo", "o/r"], repo_root=str(repo_root))
    record_false_ctx = _record(capsys)

    assert rc == 0 and rc2 == 0
    assert record_true_ctx["reason"] == "exact reason text"
    assert record_false_ctx["reason"] == "exact reason text"
    assert record_true_ctx["autonomous_capable"] is True
    assert record_false_ctx["autonomous_capable"] is True
    assert record_true_ctx["tier_ceiling_check_required"] is True
    assert record_false_ctx["tier_ceiling_check_required"] is False


@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t4_7_no_subcommand_ever_exits_3(subcommand, repo_root, mocked_github, capsys):
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    assert rc != 3


@pytest.mark.parametrize("subcommand", sorted(_ALL_ARGVS))
def test_t4_8_envelope_identifies_the_tree_and_app_role(
    subcommand, repo_root, mocked_github, capsys
):
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["repo_root"] == str(repo_root.resolve())
    assert Path(record["repo_root"]).is_absolute()
    assert record["app_role"] == "overseer"


# --------------------------------------------------------------------------- #
# T6 — the unevaluable-gate rule (§3.4.0 Rule B, and ARCH-5)
# --------------------------------------------------------------------------- #


def test_t6_1_absent_manifest_vs_complete_register_are_distinguishable(repo_root, capsys):
    # (a) complete register, manifest present with a required role satisfied.
    _add_manifest(repo_root, "1", ["code-review"])
    _add_register(repo_root, "1", "code-review")
    rc_a = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record_a = _record(capsys)
    assert rc_a == 0
    assert record_a["bounce_required"] is False
    assert record_a["gate_evaluable"] is True
    assert record_a["required_roles_resolved"] > 0
    assert record_a["not_verified"] == []

    # (b) absent manifest entirely, different step so it starts fresh.
    (repo_root / "contract" / "step-manifest.yaml").unlink()
    rc_b = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record_b = _record(capsys)
    assert rc_b == 0
    assert record_b["bounce_required"] is False
    assert record_b["gate_evaluable"] is False
    assert record_b["required_roles_resolved"] == 0
    assert any("register gate not evaluable" in nv for nv in record_b["not_verified"])


def test_t6_2_malformed_manifest_and_no_entry_for_step_both_flagged(repo_root, capsys):
    manifest = repo_root / "contract" / "step-manifest.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)

    manifest.write_text("not: valid: yaml: at: all: [[[", encoding="utf-8")
    rc = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["gate_evaluable"] is False
    assert record["bounce_required"] is False

    _add_manifest(repo_root, "2", ["code-review"])  # only step 2 has an entry
    rc2 = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record2 = _record(capsys)
    assert rc2 == 0
    assert record2["gate_evaluable"] is False
    assert record2["bounce_required"] is False


def test_t6_3_required_signoffs_matches_library_parser(repo_root, capsys):
    _add_manifest(repo_root, "1", ["code-review", "security"])
    rc = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    expected = merge_authority._required_signoffs_for_step(
        repo_root / "contract" / "step-manifest.yaml", "1"
    )
    assert record["required_signoffs"] == expected


def test_t6_4_both_register_calls_use_the_same_manifest_path(repo_root, monkeypatch, capsys):
    _add_manifest(repo_root, "1", ["code-review"])
    captured = {}

    real_check = merge_authority.check_register_completeness

    def spy_check(step, *, repo_root, manifest_path):
        captured["decision_path"] = manifest_path
        return real_check(step, repo_root=repo_root, manifest_path=manifest_path)

    real_signoffs = merge_authority._required_signoffs_for_step

    def spy_signoffs(manifest_path, step):
        captured["evidence_path"] = str(manifest_path)
        return real_signoffs(manifest_path, step)

    monkeypatch.setattr(merge_authority, "check_register_completeness", spy_check)
    monkeypatch.setattr(merge_authority, "_required_signoffs_for_step", spy_signoffs)

    rc = cli.main(["register", "--app", "overseer", "--step", "1"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    expected_path = str(repo_root / "contract" / "step-manifest.yaml")
    assert captured["decision_path"] == expected_path
    assert captured["evidence_path"] == expected_path
    assert record["manifest_path"] == str((repo_root / "contract" / "step-manifest.yaml"))


def test_t6_5_protected_and_security_surface_no_file_present(repo_root, mocked_github, capsys):
    for sub in ("protected-surface", "security-surface"):
        rc = cli.main(_ALL_ARGVS[sub], repo_root=str(repo_root))
        record = _record(capsys)
        assert rc == 0
        assert record["touches"] is False
        assert record["surfaces_file_present"] is False
        assert record["not_verified"] != []


def test_t6_6_codeowners_no_file_present(repo_root, mocked_github, capsys):
    rc = cli.main(_ALL_ARGVS["codeowners"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["required"] is False
    assert record["codeowners_present"] is False
    assert record["not_verified"] != []


def test_t6_7_populated_policy_files_yield_no_not_verified(repo_root, mocked_github, capsys):
    _add_surfaces_file(repo_root, "scripts/framework/protected_surfaces.txt", ["bootstrap/*"])
    _add_surfaces_file(
        repo_root, "scripts/framework/security_surfaces.txt", ["scripts/framework/*"]
    )
    _add_codeowners(repo_root, ["* @octocat"])
    _add_manifest(repo_root, "1", ["code-review"])
    _add_register(repo_root, "1", "code-review")

    rc_p = cli.main(_ALL_ARGVS["protected-surface"], repo_root=str(repo_root))
    record_p = _record(capsys)
    assert rc_p == 0
    assert record_p["surfaces_file_present"] is True
    assert record_p["not_verified"] == []

    rc_s = cli.main(_ALL_ARGVS["security-surface"], repo_root=str(repo_root))
    record_s = _record(capsys)
    assert rc_s == 0
    assert record_s["surfaces_file_present"] is True
    assert record_s["not_verified"] == []

    rc_c = cli.main(_ALL_ARGVS["codeowners"], repo_root=str(repo_root))
    record_c = _record(capsys)
    assert rc_c == 0
    assert record_c["codeowners_present"] is True
    assert record_c["not_verified"] == []

    rc_r = cli.main(_ALL_ARGVS["register"], repo_root=str(repo_root))
    record_r = _record(capsys)
    assert rc_r == 0
    assert record_r["gate_evaluable"] is True
    assert record_r["not_verified"] == []


@pytest.mark.parametrize("subcommand", ["protected-surface", "security-surface", "codeowners"])
def test_t6_8_empty_changed_files_list_discloses_and_does_not_flip_decision(
    subcommand, repo_root, mocked_github, monkeypatch, capsys
):
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: [])
    rc = cli.main(_ALL_ARGVS[subcommand], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["changed_file_count"] == 0
    decision_field = "required" if subcommand == "codeowners" else "touches"
    assert record[decision_field] is False
    assert any(
        "changed_file_count" in nv or "0 changed files" in nv for nv in record["not_verified"]
    )


# --------------------------------------------------------------------------- #
# T5 — the promotion
# --------------------------------------------------------------------------- #


def test_t5_touches_security_surface_is_public_and_callable():
    assert callable(merge_authority.touches_security_surface)
    assert merge_authority.touches_security_surface([], ".") is False


def test_t5_private_alias_no_longer_exists():
    assert not hasattr(merge_authority, "_touches_security_surface")


def test_t5_bounce_cap_is_2_and_bounce_count_reads_it(repo_root, capsys):
    assert merge_authority.BOUNCE_CAP == 2
    rc = cli.main(["bounce-count", "--app", "overseer", "--cid", "abc"], repo_root=str(repo_root))
    record = _record(capsys)
    assert rc == 0
    assert record["cap"] == 2
    assert record["cap_source"] == "merge_authority.BOUNCE_CAP"


# --------------------------------------------------------------------------- #
# #2209 S1a — route / bounce (T-CLI-1 .. T-CLI-9)
# --------------------------------------------------------------------------- #

import base64  # noqa: E402

_REAL_LIST_ISSUE_EVENTS = gh.list_issue_events
_OVERSEER = "hos-overseer-hos[bot]"
_WORKER = "hos-worker-hos[bot]"
_HEAD = "c" * 40

_MUTATION_ARGVS = {
    "route": [
        "route",
        "--app",
        "overseer",
        "--pr",
        "42",
        "--step",
        "1",
        "--findings-file",
        "FINDINGS",
        "--repo",
        "o/r",
    ],
    "bounce": ["bounce", "--app", "overseer", "--pr", "42", "--step", "1", "--repo", "o/r"],
}


class _World:
    """A mutable stand-in for GitHub: one healthy open worker PR."""

    def __init__(self):
        self.pr = {
            "number": 42,
            "state": "open",
            "changed_files": 1,
            "commits": 1,
            "created_at": "2026-10-31T00:00:00Z",
            "user": {"login": _WORKER, "type": "Bot"},
            "head": {"sha": _HEAD, "ref": "worker-9-thing", "repo": {"full_name": "o/r"}},
            "base": {"sha": "b" * 40, "ref": "main", "repo": {"full_name": "o/r"}},
        }
        self.pulls = {}
        self.files = [{"filename": "a.py"}]
        self.posts = []
        self.calls = []
        self.codeowners = "* @carol\n"
        self.pull_reads = 0

    def get_pull(self, o, r, n):
        if n in self.pulls:
            return self.pulls[n]
        self.pull_reads += 1
        return self.pr


@pytest.fixture
def world(repo_root, tmp_path, monkeypatch):
    w = _World()
    w.root = repo_root
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps({"findings": []}))
    w.findings = findings
    monkeypatch.setenv("HOS_BOT_LOGIN", _OVERSEER)
    monkeypatch.setattr(gh, "get_pull", w.get_pull)
    monkeypatch.setattr(gh, "get_issue", lambda o, r, n: {"number": n, "state": "open"})
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: w.files)
    monkeypatch.setattr(gh, "list_check_runs_for_ref", lambda o, r, ref: [{"name": "tests"}])
    monkeypatch.setattr(gh, "list_check_suites_for_ref", lambda o, r, ref, **k: [])
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])
    monkeypatch.setattr(gh, "list_issue_comments", lambda o, r, n: [])
    monkeypatch.setattr(gh, "list_issue_events", lambda o, r, n, **k: [])
    monkeypatch.setattr(
        gh, "get_commit", lambda o, r, ref: {"commit": {"committer": {"date": None}}}
    )
    monkeypatch.setattr(
        merge_authority,
        "get_contents",
        lambda o, r, p, *, ref: (
            {"encoding": "base64", "content": base64.b64encode(w.codeowners.encode()).decode()}
            if p == ".github/CODEOWNERS"
            else None
        ),
    )
    monkeypatch.setattr(
        merge_authority,
        "check_required_content_checks",
        lambda *a, **k: merge_authority.RequiredChecksResult(bounce_required=False),
    )

    def post(o, r, n, body, **k):
        w.posts.append(body)
        return {"id": len(w.posts), "html_url": "https://x/c", "created_at": "2026-10-31T01:00:00Z"}

    def run_gh(args, *a, **k):
        w.calls.append(args[0])
        return {"draft": True, "labels": [{"name": "needs-ai"}], "head": {"sha": _HEAD}}

    monkeypatch.setattr(merge_authority, "post_comment", post)
    monkeypatch.setattr(merge_authority, "_run_gh", run_gh)
    monkeypatch.setattr(merge_authority, "_convert_pr_to_draft", lambda o, r, n: None)
    return w


def _run_mut(world, name, capsys, **argv_edits):
    argv = [world.findings.as_posix() if a == "FINDINGS" else a for a in _MUTATION_ARGVS[name]]
    rc = cli.main(argv, repo_root=str(world.root))
    return rc, _record(capsys)


def _write_findings(world, entries):
    world.findings.write_text(json.dumps({"findings": entries}))


@pytest.mark.parametrize("name", sorted(_MUTATION_ARGVS))
@pytest.mark.parametrize("app", ["worker", "human", "bogus"])
def test_t_cli_1_only_the_overseer_may_run_route_and_bounce(name, app, world, capsys):
    argv = list(_MUTATION_ARGVS[name])
    argv[argv.index("--app") + 1] = app
    rc = cli.main(argv, repo_root=str(world.root))
    record = _record(capsys)
    assert rc == 2 and record["error_class"] is None


@pytest.mark.parametrize("flag", _WIDENING_FLAGS)
@pytest.mark.parametrize("name", sorted(_MUTATION_ARGVS))
def test_t_cli_1_no_widening_flag_on_route_or_bounce(name, flag, world, capsys):
    rc = cli.main(list(_MUTATION_ARGVS[name]) + [flag, "x"], repo_root=str(world.root))
    assert rc == 2
    _record(capsys)


@pytest.mark.parametrize("name", sorted(_MUTATION_ARGVS))
@pytest.mark.parametrize("login", [None, "", "someone-else[bot]", "scottthurlow-claude[bot]"])
def test_t_cli_2_acting_identity_must_be_the_overseer_before_any_fetch(
    name, login, world, monkeypatch, capsys
):
    if login is None:
        monkeypatch.delenv("HOS_BOT_LOGIN")
    else:
        monkeypatch.setenv("HOS_BOT_LOGIN", login)

    def boom(*a, **k):
        raise AssertionError("fetched before the identity check")

    monkeypatch.setattr(gh, "get_pull", boom)
    rc, record = _run_mut(world, name, capsys)
    assert (rc, record["error_code"], record["error_class"]) == (
        1,
        "acting_identity_not_overseer",
        "deterministic",
    )
    assert world.posts == []


def test_t_cli_2_identity_compare_is_case_insensitive(world, monkeypatch, capsys):
    monkeypatch.setenv("HOS_BOT_LOGIN", _OVERSEER.upper())
    rc, record = _run_mut(world, "bounce", capsys)
    assert rc == 0, record


def test_t_cli_5_non_worker_pr_is_legacy_and_fetches_nothing_more(world, monkeypatch, capsys):
    world.pr["user"] = {"login": "scott", "type": "User"}

    def boom(*a, **k):
        raise AssertionError("fetched past the non-worker early return")

    monkeypatch.setattr(gh, "list_pull_files", boom)
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0
    assert (record["disposition"], record["rule"], record["reasons"]) == (
        "LEGACY",
        "1",
        ["non-worker-pr"],
    )
    assert record["worker_authored"] is False and record["error_class"] is None
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"]) == (0, False, "non-worker-pr")


def test_malformed_findings_file_fails_even_for_non_worker_pr_without_network(
    world, monkeypatch, capsys
):
    world.pr["user"] = {"login": "scott", "type": "User"}
    world.findings.write_text("{not json")

    def boom(*a, **k):
        raise AssertionError("network call before the findings file was parsed")

    for name in ("get_pull", "list_pull_files", "list_check_runs_for_ref"):
        monkeypatch.setattr(gh, name, boom)
    rc, record = _run_mut(world, "route", capsys)
    assert rc != 0
    assert record["error_code"] == "findings_file_invalid"


def test_t_cli_6_route_never_proceeds_in_s1a(world, capsys):
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, record
    assert (record["disposition"], record["rule"], record["reasons"]) == (
        "HOLD",
        "8",
        ["collectors-incomplete"],
    )
    assert record["disposition"] != "PROCEED"
    joined = " ".join(record["not_verified"])
    assert "collectors_complete=false" in joined and "s1b inputs stubbed" in joined
    assert record["s1b_inputs_stubbed"] == [
        "blocks",
        "pending_rulings",
        "upheld_unescalated",
        "withdrawn_on_head",
        "veto",
    ]
    assert record["collectors"]["validator_artifact"] == "not-implemented-s1a"
    assert world.posts == []


def test_t_cli_6_route_bounces_an_llm_finding_and_a_repeat_is_a_noop(world, capsys):
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, record
    assert (record["disposition"], record["rule"], record["cid"]) == ("BOUNCE", "6e", "issue-9")
    assert record["bounce"]["finding_ids"] == [f"{_HEAD[:12]}-F1"]
    assert record["findings"][0]["id"] == f"{_HEAD[:12]}-F1"
    assert len(world.posts) == 1
    rc, record = _run_mut(world, "route", capsys)
    assert (record["disposition"], record["rule"]) == ("NOOP", "6c") and len(world.posts) == 1


def test_t_cli_6_cid_fallback_is_disclosed(world, monkeypatch, capsys):
    monkeypatch.setattr(gh, "get_issue", lambda o, r, n: None)
    rc, record = _run_mut(world, "route", capsys)
    assert record["cid"] == "pr-42" and record["cid_source"] == "pr-fallback"
    assert any("pr-42 fallback (issue-not-found)" in n for n in record["not_verified"])


def test_t_cli_7_bounce_paths(world, capsys, monkeypatch):
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"]) == (0, False, "clean")

    monkeypatch.setattr(
        merge_authority,
        "check_required_content_checks",
        lambda *a, **k: merge_authority.RequiredChecksResult(
            bounce_required=True,
            failures=["check-failing:tests"],
            reason_category="COMPLIANCE_FAILURE",
        ),
    )
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"], record["at_cap"]) == (
        0,
        True,
        "bounced",
        False,
    )
    assert record["findings"][0]["id"] == f"{_HEAD[:12]}-F1" and len(world.posts) == 1
    assert record["bounce"]["skipped"] is False

    rc, record = _run_mut(world, "bounce", capsys)  # same head, same keys
    assert (rc, record["bounced"], record["reason"]) == (0, False, "same-head")
    assert record["bounce"]["skipped"] is True and len(world.posts) == 1

    world.pr["head"]["sha"] = "d" * 40  # a new head, budget used 1 of 2: bounces again
    rc, record = _run_mut(world, "bounce", capsys)
    assert (record["bounced"], record["bounce"]["bounce_number"]) == (True, 2)

    world.pr["head"]["sha"] = "e" * 40  # a third head: at the cap
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"], record["at_cap"]) == (0, False, "at-cap", True)
    assert len(world.posts) == 2


@pytest.mark.parametrize("name", sorted(_MUTATION_ARGVS))
def test_t_cli_8_documented_payload_keys_present(name, world, capsys):
    rc, record = _run_mut(world, name, capsys)
    assert rc == 0
    assert set(cli._PAYLOAD_KEYS[name]) <= set(record)
    assert record["error_code"] is None and record["error_class"] is None


@pytest.mark.parametrize("name", sorted(_MUTATION_ARGVS))
def test_t_cli_8_exit_zero_never_exits_3_in_s1a(name, world, capsys):
    rc, _ = _run_mut(world, name, capsys)
    assert rc != 3


# --- T-CLI-3 / T-CLI-4 / T-CLI-9: every exit-1 row of TD §3.16 ----------------


def _gh_error(status):
    return gh.GitHubError(f"http {status}", status_code=status)


def _setup_sibling(world, monkeypatch, pr_state):
    from scripts.oversight.lib import audit_log

    audit_log.write_event(
        {
            "event": "pr-bounced",
            "cid": "issue-9",
            "pr": 99,
            "bounce_number": 1,
            "timestamp": "2026-10-30T00:00:00Z",
        },
        root=str(world.root),
    )
    world.pulls[99] = pr_state


def _f_findings_invalid(world, mp, capsys):
    world.findings.write_text("{not json")


def _f_findings_missing(world, mp, capsys):
    world.findings.unlink()


def _f_findings_oversize(world, mp, capsys):
    world.findings.write_text(" " * (merge_authority.FINDINGS_FILE_MAX_BYTES + 5))


def _f_findings_schema(world, mp, capsys):
    _write_findings(world, [{"class": "PROCEDURAL", "summary": "x"}])


def _f_pr_none(world, mp, capsys):
    mp.setattr(gh, "get_pull", lambda o, r, n: None)


def _f_pr_closed(world, mp, capsys):
    world.pr["state"] = "closed"


def _f_read_transient(world, mp, capsys):
    def boom(*a, **k):
        raise _gh_error(502)

    mp.setattr(gh, "list_pull_reviews", boom)


def _f_read_deterministic(world, mp, capsys):
    def boom(*a, **k):
        raise _gh_error(422)

    mp.setattr(gh, "list_pull_reviews", boom)


def _f_rate_limit(world, mp, capsys):
    def boom(*a, **k):
        raise gh.RateLimitError("limited", status_code=403)

    mp.setattr(gh, "list_pull_reviews", boom)


def _f_timeout(world, mp, capsys):
    def boom(*a, **k):
        raise gh.GitHubError("timed out")

    mp.setattr(gh, "list_pull_reviews", boom)


def _f_issue_lookup(world, mp, capsys):
    def boom(*a, **k):
        raise _gh_error(500)

    mp.setattr(gh, "get_issue", boom)


def _f_files_mismatch(world, mp, capsys):
    world.pr["changed_files"] = 2


def _f_files_truncated(world, mp, capsys):
    world.files = [{"filename": f"f{i}.py"} for i in range(3000)]
    world.pr["changed_files"] = 3000


def _f_codeowners_unreadable(world, mp, capsys):
    mp.setattr(
        merge_authority,
        "get_contents",
        lambda o, r, p, *, ref: {"encoding": "none", "content": "x"},
    )


def _f_codeowners_read(world, mp, capsys):
    def boom(*a, **k):
        raise _gh_error(503)

    mp.setattr(merge_authority, "get_contents", boom)


def _f_drift(world, mp, capsys):
    mp.setattr(
        merge_authority,
        "resolve_reviewer_from_text",
        lambda *a, **k: merge_authority.ReviewerResolution("ghost", "codeowners", (), None),
    )


def _f_siblings_exceeded(world, mp, capsys):
    mp.setattr(merge_authority, "_EPOCH_MAX_SIBLING_PRS", 0)
    _setup_sibling(world, mp, {"number": 99, "state": "open"})


def _f_sibling_missing(world, mp, capsys):
    _setup_sibling(world, mp, None)


def _f_sibling_events_truncated(world, mp, capsys):
    _setup_sibling(world, mp, {"number": 99, "state": "closed", "merged_at": None})

    def boom(*a, **k):
        raise gh.ListTruncatedError("too many events")

    mp.setattr(gh, "list_issue_events", boom)


def _f_audit_unreadable(world, mp, capsys):
    bad = world.root / "audit" / "log" / "2026" / "10" / "2026-10-30T000000Z-x-000000000000.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{broken")


def _f_head_moved(world, mp, capsys):
    reads = {"n": 0}

    def moving(o, r, n):
        reads["n"] += 1
        if reads["n"] == 1:
            return world.pr
        return {**world.pr, "head": {**world.pr["head"], "sha": "f" * 40}}

    mp.setattr(gh, "get_pull", moving)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )


def _f_comment_failed(world, mp, capsys):
    def boom(*a, **k):
        raise _gh_error(502)

    mp.setattr(merge_authority, "post_comment", boom)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )


def _f_audit_write_failed(world, mp, capsys):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    mp.setattr(merge_authority._AUDIT_LOG, "write_event", boom)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )


def _f_sibling_no_closed_event(world, mp, capsys):
    _setup_sibling(world, mp, {"number": 99, "state": "closed", "merged_at": None})
    mp.setattr(
        gh, "list_issue_events", lambda o, r, n, **k: [{"event": "labeled", "created_at": "x"}]
    )


def _f_sibling_events_404(world, mp, capsys):
    _setup_sibling(world, mp, {"number": 99, "state": "closed", "merged_at": None})
    mp.setattr(gh, "list_issue_events", _REAL_LIST_ISSUE_EVENTS)
    mp.setattr(gh, "_run_gh", lambda args, **k: None)


def _f_latest_act_events_404(world, mp, capsys):
    from scripts.oversight.lib import audit_log

    audit_log.write_event(
        {
            "event": "human-required",
            "cid": "issue-9",
            "pr": 42,
            "head_sha": _HEAD,
            "trigger": "bounce-cap",
            "escalation_created_at": "2026-10-31T00:30:00Z",
            "timestamp": "2026-10-31T00:30:01Z",
        },
        root=str(world.root),
    )
    mp.setattr(gh, "list_issue_events", _REAL_LIST_ISSUE_EVENTS)
    mp.setattr(gh, "_run_gh", lambda args, **k: None)


def _f_no_base_sha(world, mp, capsys):
    world.pr["base"] = {"ref": "main", "repo": {"full_name": "o/r"}}

    def boom(*a, **k):
        raise AssertionError("read after a missing base.sha")

    mp.setattr(gh, "list_pull_files", boom)


def _f_audit_write_value_error(world, mp, capsys):
    def boom(*a, **k):
        raise ValueError("bad record")

    mp.setattr(merge_authority._AUDIT_LOG, "write_event", boom)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )


def _f_unexpected(world, mp, capsys):
    def boom(*a, **k):
        raise KeyError("surprise")

    mp.setattr(merge_authority, "next_finding_index", boom)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )


def _f_sibling_closed_no_actor(world, mp, capsys):
    _setup_sibling(world, mp, {"number": 99, "state": "closed", "merged_at": None})
    mp.setattr(
        gh,
        "list_issue_events",
        lambda o, r, n, **k: [
            {"event": "closed", "created_at": "2026-10-30T01:00:00Z", "actor": None}
        ],
    )


def _f_sibling_closed_actor_no_login(world, mp, capsys):
    _setup_sibling(world, mp, {"number": 99, "state": "closed", "merged_at": None})
    mp.setattr(
        gh,
        "list_issue_events",
        lambda o, r, n, **k: [
            {"event": "closed", "created_at": "2026-10-30T01:00:00Z", "actor": {"type": "Bot"}}
        ],
    )


def _f_sibling_merged_no_login(world, mp, capsys):
    _setup_sibling(
        world,
        mp,
        {"number": 99, "state": "closed", "merged_at": "2026-10-30T01:00:00Z", "merged_by": None},
    )


# (id, arrange, subcommands that hit it, error_code, error_class, extra payload)
_FAILURES = [
    (
        "findings-invalid",
        _f_findings_invalid,
        ["route"],
        "findings_file_invalid",
        "deterministic",
        {},
    ),
    (
        "findings-missing",
        _f_findings_missing,
        ["route"],
        "findings_file_invalid",
        "deterministic",
        {},
    ),
    (
        "findings-oversize",
        _f_findings_oversize,
        ["route"],
        "findings_file_invalid",
        "deterministic",
        {},
    ),
    ("findings-schema", _f_findings_schema, ["route"], "findings_schema", "deterministic", {}),
    ("pr-none", _f_pr_none, ["route", "bounce"], "pr_not_found", "deterministic", {}),
    ("pr-closed", _f_pr_closed, ["route", "bounce"], "pr_not_open", "deterministic", {}),
    ("read-502", _f_read_transient, ["route"], "github_read_failed", "transient", {}),
    ("read-422", _f_read_deterministic, ["route"], "github_read_failed", "deterministic", {}),
    ("read-rate-limit", _f_rate_limit, ["route"], "github_read_failed", "transient", {}),
    ("read-timeout", _f_timeout, ["route"], "github_read_failed", "transient", {}),
    (
        "issue-lookup-500",
        _f_issue_lookup,
        ["route", "bounce"],
        "github_read_failed",
        "transient",
        {},
    ),
    (
        "files-mismatch",
        _f_files_mismatch,
        ["route", "bounce"],
        "changed_files_mismatch",
        "transient",
        {},
    ),
    (
        "files-truncated",
        _f_files_truncated,
        ["route", "bounce"],
        "changed_files_truncated",
        "deterministic",
        {},
    ),
    (
        "codeowners-unreadable",
        _f_codeowners_unreadable,
        ["route"],
        "codeowners_unreadable",
        "deterministic",
        {},
    ),
    ("codeowners-503", _f_codeowners_read, ["route"], "github_read_failed", "transient", {}),
    ("codeowners-drift", _f_drift, ["route"], "codeowners_resolution_drift", "deterministic", {}),
    (
        "siblings-exceeded",
        _f_siblings_exceeded,
        ["route", "bounce"],
        "epoch_siblings_exceeded",
        "deterministic",
        {},
    ),
    (
        "sibling-missing",
        _f_sibling_missing,
        ["route", "bounce"],
        "epoch_sibling_missing",
        "deterministic",
        {},
    ),
    (
        "sibling-events-truncated",
        _f_sibling_events_truncated,
        ["route", "bounce"],
        "issue_events_truncated",
        "deterministic",
        {},
    ),
    (
        "audit-unreadable",
        _f_audit_unreadable,
        ["route", "bounce"],
        "audit_unreadable",
        "deterministic",
        {},
    ),
    (
        "sibling-no-closed-event",
        _f_sibling_no_closed_event,
        ["route", "bounce"],
        "epoch_sibling_missing",
        "deterministic",
        {},
    ),
    (
        "sibling-events-404",
        _f_sibling_events_404,
        ["route", "bounce"],
        "github_read_failed",
        "deterministic",
        {},
    ),
    (
        "latest-act-events-404",
        _f_latest_act_events_404,
        ["route"],
        "github_read_failed",
        "deterministic",
        {},
    ),
    ("no-base-sha", _f_no_base_sha, ["route"], "pr_not_found", "deterministic", {}),
    (
        "audit-write-value-error",
        _f_audit_write_value_error,
        ["route"],
        "bounce_audit_write_failed",
        "deterministic",
        {"comment_posted": True},
    ),
    (
        "unexpected-error",
        _f_unexpected,
        ["route"],
        "bounce_unexpected_error",
        "deterministic",
        {"comment_posted": None},
    ),
    ("head-moved", _f_head_moved, ["route"], "head_moved", "transient", {}),
    (
        "comment-failed",
        _f_comment_failed,
        ["route"],
        "bounce_comment_failed",
        "transient",
        {"comment_posted": False},
    ),
    (
        "audit-write-failed",
        _f_audit_write_failed,
        ["route"],
        "bounce_audit_write_failed",
        "deterministic",
        {"comment_posted": True},
    ),
]
_FAILURE_CASES = [(f, sub) for f in _FAILURES for sub in f[2]]


@pytest.mark.parametrize(
    "failure,name", _FAILURE_CASES, ids=[f"{f[0]}-{sub}" for f, sub in _FAILURE_CASES]
)
def test_t_cli_3_9_every_exit_1_row(failure, name, world, monkeypatch, capsys):
    _, arrange, _, code, klass, extra = failure
    arrange(world, monkeypatch, capsys)
    rc, record = _run_mut(world, name, capsys)
    assert rc == 1, record
    assert (record["error_code"], record["error_class"]) == (code, klass)
    for key, value in extra.items():
        assert record[key] is value
    assert record["error"]
    if code not in ("bounce_audit_write_failed",):
        assert world.posts == []  # nothing is posted before a failure
    if code in ("head_moved",):
        assert world.calls == []


def test_t_cli_3_bounce_failure_rows_via_the_bounce_subcommand(world, monkeypatch, capsys):
    monkeypatch.setattr(
        merge_authority,
        "check_required_content_checks",
        lambda *a, **k: merge_authority.RequiredChecksResult(
            bounce_required=True,
            failures=["check-failing:tests"],
            reason_category="COMPLIANCE_FAILURE",
        ),
    )
    monkeypatch.setattr(
        merge_authority, "post_comment", lambda *a, **k: (_ for _ in ()).throw(_gh_error(404))
    )
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["error_code"], record["error_class"], record["comment_posted"]) == (
        1,
        "bounce_comment_failed",
        "deterministic",
        False,
    )


def test_t_cli_9_repo_unresolved(world, capsys):
    argv = [a for a in _MUTATION_ARGVS["bounce"] if a not in ("--repo", "o/r")]
    rc = cli.main(argv, repo_root=str(world.root))
    record = _record(capsys)
    assert (rc, record["error_code"], record["error_class"]) == (
        1,
        "repo_unresolved",
        "deterministic",
    )


def test_t_cli_9_config_unresolved(world, tmp_path, capsys):
    rc = cli.main(
        [a.replace("FINDINGS", str(world.findings)) for a in _MUTATION_ARGVS["route"]],
        repo_root=str(tmp_path / "no-config"),
    )
    record = _record(capsys)
    assert (rc, record["error_code"], record["error_class"]) == (
        1,
        "config_unresolved",
        "deterministic",
    )


def test_t_cli_9_classify_github_error():
    c = merge_authority.classify_github_error
    assert c(gh.RateLimitError("x", status_code=429)) == "transient"
    assert c(gh.GitHubError("timeout")) == "transient"
    assert c(gh.GitHubError("bad gateway", status_code=502)) == "transient"
    assert c(gh.GitHubError("missing", status_code=404)) == "deterministic"
    assert c(gh.GitHubError("unprocessable", status_code=422)) == "deterministic"
    assert c(gh.GitHubError("forbidden", status_code=403)) == "deterministic"


def test_t_cli_9_list_truncated_error_is_deterministic():
    exc = gh.ListTruncatedError("list truncated")
    assert getattr(exc, "status_code", None) is None
    assert merge_authority.classify_github_error(exc) == "deterministic"


def test_t_cli_4_head_pin_writes_nothing(world, monkeypatch, capsys):
    _f_head_moved(world, monkeypatch, capsys)
    rc, record = _run_mut(world, "route", capsys)
    assert (rc, record["error_code"]) == (1, "head_moved")
    assert world.posts == [] and world.calls == []
    assert not (world.root / "audit" / "log").exists()


def test_t_cli_7_bounce_partial_overlap_bounces_only_new_findings(world, monkeypatch, capsys):
    failing = {"names": ["check-failing:tests"]}
    monkeypatch.setattr(
        merge_authority,
        "check_required_content_checks",
        lambda *a, **k: merge_authority.RequiredChecksResult(
            bounce_required=True,
            failures=list(failing["names"]),
            reason_category="COMPLIANCE_FAILURE",
        ),
    )
    rc, record = _run_mut(world, "bounce", capsys)
    assert record["bounced"] is True and len(world.posts) == 1
    failing["names"] = ["check-failing:tests", "check-failing:lint"]
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"]) == (0, True, "bounced")
    assert record["bounce"]["finding_ids"] == [f"{_HEAD[:12]}-F2"]
    ids = {f["key"]: f.get("id") for f in record["findings"]}
    assert ids == {
        "REQUIRED_CHECK:check-failing:tests": None,
        "REQUIRED_CHECK:check-failing:lint": f"{_HEAD[:12]}-F2",
    }
    assert "Required check lint" in world.posts[1] and "Required check tests" not in world.posts[1]
    assert "-F2]" in world.posts[1]


# --- T-CLI-10: route repairs an unfinished finalize on a rule-6c NOOP ----------


def _bounced_world(world, capsys):
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )
    rc, record = _run_mut(world, "route", capsys)
    assert record["disposition"] == "BOUNCE" and len(world.posts) == 1


def _stale_pr_state(world, monkeypatch, events):
    """The earlier bounce left the PR not draft, without needs-ai."""
    calls, drafts = [], []

    def run_gh(args, *a, **k):
        calls.append(args[0])
        if args[0].endswith("/pulls/42"):
            return {"draft": False, "labels": []}
        return {}

    monkeypatch.setattr(merge_authority, "_run_gh", run_gh)
    monkeypatch.setattr(merge_authority, "_convert_pr_to_draft", lambda o, r, n: drafts.append(n))
    monkeypatch.setattr(gh, "list_issue_events", events)
    return calls, drafts


def test_t_cli_10_noop_repairs_both_failed_finalize(world, monkeypatch, capsys):
    _bounced_world(world, capsys)
    calls, drafts = _stale_pr_state(world, monkeypatch, lambda o, r, n, **k: [])
    audit_files = sorted((world.root / "audit").rglob("*.json"))
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, record
    assert (record["disposition"], record["rule"]) == ("NOOP", "6c")
    assert record["actions"] == ["repair-finalize"]
    assert record["bounce"] == {
        "skipped": True,
        "finalize_repaired": ["label", "draft"],
        "finalize_errors": [],
    }
    assert any(c.endswith("/labels") for c in calls) and drafts == [42]
    assert len(world.posts) == 1
    assert sorted((world.root / "audit").rglob("*.json")) == audit_files  # no new event


def test_t_cli_10_deliberate_ready_does_nothing(world, monkeypatch, capsys):
    _bounced_world(world, capsys)
    event = {
        "event": "ready_for_review",
        "created_at": "2026-10-31T02:00:00Z",
        "actor": {"login": "x"},
    }
    calls, drafts = _stale_pr_state(world, monkeypatch, lambda o, r, n, **k: [event])
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0 and record["bounce"]["finalize_repaired"] == []
    assert not any(c.endswith("/labels") for c in calls) and drafts == []


@pytest.mark.parametrize(
    "exc,code",
    [
        (gh.GitHubError("down", status_code=502), "github_read_failed"),
        (gh.ListTruncatedError("too many"), "issue_events_truncated"),
    ],
)
def test_t_cli_10_events_read_failure_is_exit_1_and_writes_nothing(
    world, monkeypatch, capsys, exc, code
):
    _bounced_world(world, capsys)

    def boom(*a, **k):
        raise exc

    calls, drafts = _stale_pr_state(world, monkeypatch, boom)
    rc, record = _run_mut(world, "route", capsys)
    assert (rc, record["error_code"]) == (1, code)
    assert not any(c.endswith("/labels") for c in calls) and drafts == []


# --- #2227: the lock-time cap and lock timeout reach the CLI ---------------------


def _require_failing_check(monkeypatch):
    monkeypatch.setattr(
        merge_authority,
        "check_required_content_checks",
        lambda *a, **k: merge_authority.RequiredChecksResult(
            bounce_required=True,
            failures=["check-failing:tests"],
            reason_category="COMPLIANCE_FAILURE",
        ),
    )


def test_t_cli_2227_bounce_maps_lock_time_at_cap(world, monkeypatch, capsys):
    _require_failing_check(monkeypatch)
    seen = {}

    def refuse(*a, **k):
        seen.update(k)
        return merge_authority.BounceResult(
            comment_url=None, audit_relpath="", bounce_number=2, skipped=True, at_cap=True
        )

    monkeypatch.setattr(merge_authority, "record_pr_bounce", refuse)
    rc, record = _run_mut(world, "bounce", capsys)
    assert (rc, record["bounced"], record["reason"], record["at_cap"]) == (0, False, "at-cap", True)
    assert record["bounce"]["at_cap"] is True
    assert seen["cap"] == merge_authority.BOUNCE_CAP


def test_t_cli_2227_route_reports_lock_time_at_cap(world, monkeypatch, capsys):
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )
    monkeypatch.setattr(
        merge_authority,
        "record_pr_bounce",
        lambda *a, **k: merge_authority.BounceResult(
            comment_url=None, audit_relpath="", bounce_number=2, skipped=True, at_cap=True
        ),
    )
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0 and record["bounce"]["at_cap"] is True
    assert any("cap was reached under the bounce lock" in r for r in record["reasons"])


@pytest.mark.parametrize("name", ["bounce", "route"])
def test_t_cli_2227_lock_timeout_is_a_transient_failure(name, world, monkeypatch, capsys):
    _require_failing_check(monkeypatch)
    _write_findings(
        world, [{"class": "MERITS", "summary": "bad", "path": "a.py", "slug": "bad-thing"}]
    )

    def timeout(*a, **k):
        raise merge_authority.BounceLockTimeout("held")

    monkeypatch.setattr(merge_authority, "record_pr_bounce", timeout)
    rc, record = _run_mut(world, name, capsys)
    assert rc == 1
    assert (record["error_code"], record["error_class"]) == ("bounce_lock_timeout", "transient")
    assert world.posts == []


def test_t_cli_2227_repair_lock_timeout_is_a_transient_failure(world, monkeypatch, capsys):
    def timeout(*a, **k):
        raise merge_authority.BounceLockTimeout("held")

    monkeypatch.setattr(merge_authority, "repair_bounce_finalize", timeout)
    with pytest.raises(cli._Fail) as info:
        cli._repair_finalize(
            "o", "r", 42, "issue-9", _HEAD, types.SimpleNamespace(repo_root=world.root), []
        )
    assert (info.value.code, info.value.klass) == ("bounce_lock_timeout", "transient")


def test_t_cli_2227_ids_follow_the_findings_the_lock_kept(world, monkeypatch, capsys):
    a = {"class": "MERITS", "summary": "first", "path": "a.py", "slug": "first-thing"}
    b = {"class": "MERITS", "summary": "second", "path": "b.py", "slug": "second-thing"}
    world.files = [{"filename": "a.py"}, {"filename": "b.py"}]
    world.pr["changed_files"] = 2
    _write_findings(world, [a])
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0 and len(world.posts) == 1
    # Hide the prior bounce from the CLI's pre-lock view only, as a race would.
    monkeypatch.setattr(cli, "_prior_on_head", lambda *args, **kw: ())
    _write_findings(world, [a, b])
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, (record.get("error_code"), record.get("error"))
    assert record["disposition"] == "BOUNCE"
    by_path = {row["path"]: row for row in record["findings"]}
    assert len(world.posts) == 2
    assert record["bounce"]["finding_ids"] == [f"{_HEAD[:12]}-F2"]
    assert by_path["b.py"]["id"] == f"{_HEAD[:12]}-F2"
    assert "id" not in by_path["a.py"]
    assert record["bounce"]["finding_keys"] == [by_path["b.py"]["key"]]


def test_t_cli_2227_lock_time_cap_routes_as_6d(world, monkeypatch, capsys):
    a = {"class": "MERITS", "summary": "first", "path": "a.py", "slug": "first-thing"}
    b = {"class": "MERITS", "summary": "second", "path": "b.py", "slug": "second-thing"}
    world.files = [{"filename": "a.py"}, {"filename": "b.py"}]
    world.pr["changed_files"] = 2
    _write_findings(world, [a])
    rc, _ = _run_mut(world, "route", capsys)
    assert rc == 0 and len(world.posts) == 1
    # Hide the prior bounce and the epoch count from the pre-lock view only, and
    # lower the cap so the lock-time re-read finds it reached.
    monkeypatch.setattr(cli, "_prior_on_head", lambda *args, **kw: ())
    monkeypatch.setattr(cli, "_epoch", lambda *args, **kw: (None, 0))
    monkeypatch.setattr(cli.merge_authority, "BOUNCE_CAP", 1)
    _write_findings(world, [a, b])
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, (record.get("error_code"), record.get("error"))
    assert (record["disposition"], record["rule"], record["trigger"]) == (
        "ESCALATE",
        "6d",
        "bounce-cap",
    )
    assert len(world.posts) == 1
    assert record["bounce"]["at_cap"] is True
    assert any("bounce cap was reached" in r for r in record["reasons"])


def test_t_cli_2227_lock_time_all_duplicates_route_as_6c(world, monkeypatch, capsys):
    a = {"class": "MERITS", "summary": "first", "path": "a.py", "slug": "first-thing"}
    _write_findings(world, [a])
    rc, _ = _run_mut(world, "route", capsys)
    assert rc == 0 and len(world.posts) == 1
    monkeypatch.setattr(cli, "_prior_on_head", lambda *args, **kw: ())
    rc, record = _run_mut(world, "route", capsys)
    assert rc == 0, (record.get("error_code"), record.get("error"))
    assert (record["disposition"], record["rule"]) == ("NOOP", "6c")
    assert "no-new-keys" in record["reasons"]
    assert len(world.posts) == 1
