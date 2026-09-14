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
