"""
Tests for Phase B modules: ledger, budget, envelope, probe, claim, triage,
codeowners, merge_authority matrix.
"""

import json
import re
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── ledger ──────────────────────────────────────────────────────────────────

from scripts.automation.lib.ledger import (
    LedgerWriter,
    last_k_median_cost,
    make_record,
    sum_window_blast_radius,
    sum_window_tokens,
)


class TestLedgerWriter:
    def test_creates_run_file_on_first_log(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("triage", "hos-worker", "classified as bug", cid="abc123def456")
        files = list((tmp_path / "audit" / "automation" / "cps" / "runs").glob("*.jsonl"))
        assert len(files) == 1
        records = [json.loads(l) for l in files[0].read_text().splitlines()]
        assert records[0]["event"] == "triage"

    def test_manifest_entry_written(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("triage", "hos-worker", "test")
        manifest = (tmp_path / "audit" / "automation" / "cps" / "manifest.jsonl").read_text()
        assert "instance_id" in manifest

    def test_append_only(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("triage", "hos-worker", "first")
        writer.log("merge", "hos-overseer", "merged")
        run_dir = tmp_path / "audit" / "automation" / "cps" / "runs"
        records = [json.loads(l) for f in run_dir.glob("*.jsonl") for l in f.read_text().splitlines()]
        assert len(records) == 2

    def test_token_cost_recorded(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("gate-end", "hos-worker", "done", token_cost=42000)
        run_dir = tmp_path / "audit" / "automation" / "cps" / "runs"
        records = [json.loads(l) for f in run_dir.glob("*.jsonl") for l in f.read_text().splitlines()]
        assert records[0]["token_cost"] == 42000


class TestSumWindowTokens:
    def test_sums_within_window(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("gate-end", "hos-worker", "done", token_cost=10000)
        writer.log("gate-end", "hos-worker", "done", token_cost=5000)
        total = sum_window_tokens("cps", window_hours=1.0, repo_root=str(tmp_path))
        assert total == 15000

    def test_returns_zero_for_empty_ledger(self, tmp_path):
        assert sum_window_tokens("cps", repo_root=str(tmp_path)) == 0


class TestSumWindowBlastRadius:
    def test_sums_prs_and_issues(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("merge", "hos-overseer", "merged", prs=1, issues=0, files_touched=3)
        writer.log("escalate", "hos-worker", "escalated", prs=0, issues=2, files_touched=0)
        blast = sum_window_blast_radius("cps", window_hours=24.0, repo_root=str(tmp_path))
        assert blast["prs"] == 1
        assert blast["issues"] == 2
        assert blast["files"] == 3


# ── budget ───────────────────────────────────────────────────────────────────

from scripts.automation.lib.budget import (
    BASE_COST,
    BudgetGate,
    EstimationSignals,
    HISTORICAL_FLOOR_MULTIPLIER,
    WorkClass,
    estimate_tokens,
)


class TestEstimateTokens:
    def test_bug_base_cost(self, tmp_path):
        signals = EstimationSignals(triage_class="bug")
        est = estimate_tokens(signals, "cps", repo_root=str(tmp_path))
        assert est >= BASE_COST["bug"]

    def test_larger_issue_body_increases_estimate(self, tmp_path):
        small = estimate_tokens(EstimationSignals(issue_body_chars=100), "cps", str(tmp_path))
        large = estimate_tokens(EstimationSignals(issue_body_chars=5000), "cps", str(tmp_path))
        assert large > small

    def test_deterministic_formula(self, tmp_path):
        signals = EstimationSignals(
            triage_class="bug",
            issue_body_chars=1000,
            changed_file_count=3,
            total_diff_lines=50,
            blast_radius=2,
        )
        est1 = estimate_tokens(signals, "cps", str(tmp_path))
        est2 = estimate_tokens(signals, "cps", str(tmp_path))
        assert est1 == est2

    def test_historical_floor_applied(self, tmp_path):
        # Write a historical record with high cost
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        for _ in range(5):
            writer.log("gate-end", "hos-worker", "bug task", token_cost=200_000)
        signals = EstimationSignals(triage_class="bug")
        est = estimate_tokens(signals, "cps", str(tmp_path))
        # Should be at least historical_median * floor_multiplier
        assert est >= 200_000 * HISTORICAL_FLOOR_MULTIPLIER


class TestBudgetGate:
    def test_ungated_always_allowed(self, tmp_path):
        gate = BudgetGate(150_000, 1_500_000, "cps", str(tmp_path))
        result = gate.evaluate("triage", estimate=0)
        assert result.allowed
        assert result.work_class == WorkClass.UNGATED

    def test_per_task_threshold_blocks(self, tmp_path):
        gate = BudgetGate(per_task_threshold=100, window_budget=1_000_000, customer="cps", repo_root=str(tmp_path))
        result = gate.evaluate("spawn", estimate=200)
        assert not result.allowed
        assert "threshold" in result.reason.lower()

    def test_window_budget_blocks(self, tmp_path):
        # Pre-fill window with spend
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("gate-end", "hos-worker", "done", token_cost=900_000)
        gate = BudgetGate(per_task_threshold=1_000_000, window_budget=1_000_000, customer="cps", repo_root=str(tmp_path))
        result = gate.evaluate("spawn", estimate=200_000)
        assert not result.allowed
        assert "budget" in result.reason.lower()

    def test_within_budget_allowed(self, tmp_path):
        gate = BudgetGate(150_000, 1_500_000, "cps", str(tmp_path))
        result = gate.evaluate("spawn", estimate=50_000)
        assert result.allowed

    def test_escalation_body_contains_required_fields(self, tmp_path):
        gate = BudgetGate(100, 1_000_000, "cps", str(tmp_path))
        dec = gate.evaluate("spawn", estimate=200)
        body = gate.escalation_body(dec, "3 files", "2026-06-20T00:00:00Z")
        assert "token estimate" in body.lower()
        assert "blast radius" in body.lower()
        assert "default-deny" in body.lower()


# ── envelope ─────────────────────────────────────────────────────────────────

from scripts.automation.lib.envelope import (
    Envelope,
    already_answered,
    author_is_allowed,
    make_claim_envelope,
    make_heartbeat_envelope,
    negotiate_version,
    parse_envelope,
)


class TestEnvelope:
    def test_roundtrip_parse_emit(self):
        env = make_claim_envelope("abc123def456", "hos-worker", str(uuid.uuid4()))
        body = env.to_comment_body("Working on this.")
        parsed = parse_envelope(body)
        assert parsed is not None
        assert parsed.type == "claim"
        assert parsed.correlation_id == "abc123def456"

    def test_parse_returns_none_on_missing_envelope(self):
        assert parse_envelope("just some text, no envelope here") is None

    def test_parse_returns_none_on_missing_cid(self):
        text = "---hos-envelope\ntype: claim\n---"
        assert parse_envelope(text) is None

    def test_in_reply_to_preserved(self):
        env = Envelope(
            type="answer",
            correlation_id="aabbccddeeff",
            in_reply_to="112233445566",
        )
        body = env.to_comment_body()
        parsed = parse_envelope(body)
        assert parsed.in_reply_to == "112233445566"

    def test_is_reply_to(self):
        env = Envelope(type="answer", correlation_id="aaa", in_reply_to="bbb")
        assert env.is_reply_to("bbb")
        assert not env.is_reply_to("ccc")


class TestAlreadyAnswered:
    def test_detects_structural_envelope_match(self):
        cid = "abc123def456"
        reply_env = Envelope(type="answer", correlation_id="xyz", in_reply_to=cid)
        comments = [reply_env.to_comment_body()]
        assert already_answered(comments, cid)

    def test_detects_same_cid_envelope(self):
        cid = "abc123def456"
        env = Envelope(type="answer", correlation_id=cid)
        comments = [env.to_comment_body()]
        assert already_answered(comments, cid)

    def test_no_match_returns_false(self):
        assert not already_answered(["no envelope here", "random text"], "abc123def456")

    def test_wrong_cid_does_not_match(self):
        env = Envelope(type="answer", correlation_id="wrong000cid0")
        assert not already_answered([env.to_comment_body()], "abc123def456")


class TestAuthorIsAllowed:
    def test_allowed_login(self):
        assert author_is_allowed("ScottThurlow", ["ScottThurlow", "bot"])

    def test_case_insensitive(self):
        assert author_is_allowed("scottthurlow", ["ScottThurlow"])

    def test_empty_allowlist_blocks(self):
        assert not author_is_allowed("anyone", [])

    def test_not_in_list_blocked(self):
        assert not author_is_allowed("stranger", ["ScottThurlow"])


class TestNegotiateVersion:
    def test_same_version_accepted(self):
        assert negotiate_version("1.0") == "1.0"

    def test_incompatible_major_rejected(self):
        assert negotiate_version("2.0") is None

    def test_older_minor_accepted(self):
        # 1.0 ≤ current (1.0) — accept their version
        result = negotiate_version("1.0")
        assert result is not None


# ── triage ───────────────────────────────────────────────────────────────────

from scripts.automation.lib.triage import (
    TriageClass,
    TriageResult,
    benefit_exceeds_risk,
    infer_severity,
    triage,
    Severity,
)


class TestTriage:
    def test_security_pattern_triggers_embargo(self):
        result = triage("RCE vulnerability in auth flow", "Critical security flaw found")
        assert result.triage_class == TriageClass.SECURITY_REPORT
        assert result.embargo
        assert not result.autonomous

    def test_bug_label_fast_path(self):
        result = triage("something broken", "", labels=["bug"])
        assert result.triage_class == TriageClass.BUG
        assert result.confidence >= 0.9

    def test_feature_label_fast_path(self):
        result = triage("new feature", "", labels=["enhancement"])
        assert result.triage_class == TriageClass.FEATURE
        assert not result.autonomous

    def test_low_confidence_escalates(self):
        result = triage("", "", confidence_floor=0.99)
        assert not result.autonomous

    def test_bug_content_signal(self):
        result = triage("Crash in login flow", "The app crashes when user logs in with OAuth")
        assert result.triage_class == TriageClass.BUG

    def test_communication_content_signal(self):
        result = triage("Status update on PR #123", "Can you explain the current status?")
        assert result.triage_class == TriageClass.COMMUNICATION


class TestInferSeverity:
    def test_critical_keywords(self):
        assert infer_severity("CRITICAL: production down", "") == Severity.P0

    def test_high_priority(self):
        assert infer_severity("P1: urgent fix needed", "") == Severity.P1

    def test_default_p3(self):
        assert infer_severity("minor style fix", "") == Severity.P3


class TestBenefitExceedsRisk:
    def test_bug_within_ceiling_allowed(self):
        result = triage("login broken", "users can't log in", labels=["bug"])
        assert benefit_exceeds_risk(result, security_sensitive=False, tier_estimate="LOW")

    def test_feature_always_blocked(self):
        result = triage("add feature", "", labels=["enhancement"])
        assert not benefit_exceeds_risk(result)

    def test_security_sensitive_high_tier_blocked(self):
        result = triage("cache bug", "caching layer returns wrong results", labels=["bug"])
        assert not benefit_exceeds_risk(result, security_sensitive=True, tier_estimate="HIGH")


# ── codeowners ───────────────────────────────────────────────────────────────

from scripts.automation.lib.codeowners import find_owners, actor_is_codeowner


def test_no_cross_import_from_oversight_codeowners():
    """Enforce the architect's ruling (#559): automation must NOT import from oversight.

    Importing scripts.oversight.codeowners into the automation library would
    invert the worker→overseer trust direction. This test fails if that import
    is ever introduced, making the boundary machine-enforceable. (#617)
    """
    import importlib
    import scripts.automation.lib.codeowners as automation_mod

    source = importlib.util.find_spec("scripts.automation.lib.codeowners").origin
    with open(source) as f:
        source_text = f.read()

    assert "scripts.oversight" not in source_text, (
        "scripts/automation/lib/codeowners.py must not import from scripts/oversight/. "
        "Doing so inverts the worker→overseer trust direction — see architect ruling on #559."
    )
    assert "oversight.codeowners" not in source_text, (
        "scripts/automation/lib/codeowners.py must not import oversight.codeowners. "
        "See architect ruling on #559 and research finding on trust-direction split."
    )


class TestFindOwners:
    def _write_codeowners(self, tmp_path, content: str) -> Path:
        path = tmp_path / "CODEOWNERS"
        path.write_text(content)
        return path

    def test_last_match_wins(self, tmp_path):
        path = self._write_codeowners(tmp_path, "* @alice\n*.py @bob\n")
        owners = find_owners("foo.py", path)
        assert "@bob" in owners

    def test_no_match_returns_empty(self, tmp_path):
        path = self._write_codeowners(tmp_path, "docs/ @alice\n")
        owners = find_owners("src/main.py", path)
        assert owners == []

    def test_directory_pattern_matches_contents(self, tmp_path):
        path = self._write_codeowners(tmp_path, "scripts/ @scott\n")
        owners = find_owners("scripts/framework/tool.sh", path)
        assert "@scott" in owners

    def test_missing_file_returns_empty(self, tmp_path):
        owners = find_owners("anything.py", tmp_path / "nonexistent")
        assert owners == []


class TestActorIsCodeowner:
    def _write_codeowners(self, tmp_path, content: str) -> Path:
        path = tmp_path / "CODEOWNERS"
        path.write_text(content)
        return path

    def test_owner_is_recognized(self, tmp_path):
        path = self._write_codeowners(tmp_path, "* @ScottThurlow\n")
        assert actor_is_codeowner("ScottThurlow", "any/file.py", path)

    def test_non_owner_rejected(self, tmp_path):
        path = self._write_codeowners(tmp_path, "* @alice\n")
        assert not actor_is_codeowner("bob", "any/file.py", path)

    def test_uncovered_path_fail_closed(self, tmp_path):
        path = self._write_codeowners(tmp_path, "docs/ @alice\n")
        assert not actor_is_codeowner("alice", "src/main.py", path)


class TestKnownDivergenceFromOversightCodeowners:
    """KNOWN-DIVERGENCE characterization tests (architect ruling #559, 2026-06-19).

    These tests PIN the three real behavioral divergences between this module
    (scripts/automation/lib/codeowners.py) and scripts/oversight/codeowners.py.
    They must NOT be deleted or "fixed" — they document an intentional design
    split: opposite fail directions for different security contexts.

    If these tests start failing, the glob matcher was changed — alert the
    architect before proceeding.
    """

    def _write(self, tmp_path, content: str) -> Path:
        p = tmp_path / "CODEOWNERS"
        p.write_text(content)
        return p

    def test_star_does_not_cross_segments(self, tmp_path):
        # DIVERGENCE ROW 1: `*` in this module does NOT cross path segments.
        # oversight/codeowners.py `*` also does not cross segments (same here).
        # Both agree on this case — pinned to confirm no regression.
        path = self._write(tmp_path, "src/*.py @alice\n")
        assert actor_is_codeowner("alice", "src/main.py", path)
        assert not actor_is_codeowner("alice", "src/sub/main.py", path)

    def test_bare_name_does_not_match_at_depth(self, tmp_path):
        # DIVERGENCE ROW 2: bare name (no slash, no glob) in THIS module does
        # NOT match the name at arbitrary depth. oversight/codeowners.py DOES
        # match (bare name → `**/name` expansion). Fail-closed is correct here:
        # failing to recognize a codeowner does not grant authorization.
        path = self._write(tmp_path, "contract @alice\n")
        # Direct match still works
        assert actor_is_codeowner("alice", "contract", path)
        # Depth match is absent in this module (diverges from oversight)
        assert not actor_is_codeowner("alice", "deep/nested/contract", path)

    def test_no_trailing_slash_does_not_over_match_sibling(self, tmp_path):
        # DIVERGENCE ROW 3: pattern without trailing slash in THIS module uses
        # re.fullmatch with `(/.*)?$` suffix — this means `scripts/oversight`
        # would match `scripts/oversight-adjacent/foo.py` as a directory.
        # oversight/codeowners.py does NOT match it (no trailing slash → not
        # treated as directory). Pinned to detect if this module's behavior
        # changes — over-match here would grant unearned authorization.
        path = self._write(tmp_path, "scripts/oversight @alice\n")
        assert actor_is_codeowner("alice", "scripts/oversight/tool.py", path)
        # The architect's analysis predicted an over-match here; empirical test
        # shows this module does NOT over-match (result is False). Both modules
        # agree on this case. Pinned to detect any future regression.
        result = actor_is_codeowner("alice", "scripts/oversight-adjacent/foo.py", path)
        assert result is False  # No over-match — same behavior as oversight


# ── merge_authority matrix ────────────────────────────────────────────────────

from scripts.automation.lib.merge_authority import (
    MergeDecision,
    RiskTier,
    decide_merge_authority,
    detect_server_side_gate,
    route_embargo,
)


def _patch_gate(capable: bool):
    from scripts.automation.lib.merge_authority import GateDetectionResult
    return patch(
        "scripts.automation.lib.merge_authority.detect_server_side_gate",
        return_value=GateDetectionResult(autonomous_capable=capable, reason="test"),
    )


class TestDecideMergeAuthority:
    BASE = dict(
        owner="o", repo="r", pr_number=1,
        risk_tier=RiskTier.LOW,
        oversight_verdict="PROCEED",
        changed_files=["src/foo.py"],
        pr_title="fix: something small",
        pr_author="hos-worker-hos[bot]",
        agent_class="overseer",
        overseer_ceiling=RiskTier.LOW,
    )

    def test_worker_class_always_propose_only(self):
        with _patch_gate(True):
            result = decide_merge_authority(**{**self.BASE, "agent_class": "worker"})
        assert result.decision == MergeDecision.PROPOSE_ONLY

    def test_auto_merge_when_all_conditions_met(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(**self.BASE, repo_root=str(tmp_path))
        assert result.decision == MergeDecision.AUTO_MERGE

    def test_high_tier_requires_human(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "risk_tier": RiskTier.HIGH},
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED

    def test_security_relevant_requires_human(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(
                **self.BASE, security_relevant=True,
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED

    def test_propose_only_when_gate_absent(self, tmp_path):
        with _patch_gate(False):
            result = decide_merge_authority(**self.BASE, repo_root=str(tmp_path))
        assert result.decision == MergeDecision.PROPOSE_ONLY

    def test_escalate_verdict_requires_human(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "oversight_verdict": "ESCALATE"},
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED
        assert "needs-human" in result.labels_to_add

    def test_release_pr_always_human(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "pr_title": "chore: cut release v1.0.0"},
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED
        assert result.is_release

    def test_self_approval_blocked(self, tmp_path):
        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "pr_author": "hos-overseer-hos[bot]"},
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED

    def test_protected_surface_without_human_approval(self, tmp_path):
        # Create protected_surfaces.txt to mark .claude/agents/worker.md as protected
        surfaces_path = tmp_path / "scripts" / "framework" / "protected_surfaces.txt"
        surfaces_path.parent.mkdir(parents=True, exist_ok=True)
        surfaces_path.write_text(".claude/agents/worker.md\n")

        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "changed_files": [".claude/agents/worker.md"]},
                repo_root=str(tmp_path),
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED
        assert "needs-human" in result.labels_to_add

    def test_protected_surface_with_human_approval_allows_auto_merge(self, tmp_path):
        # Create protected_surfaces.txt
        surfaces_path = tmp_path / "scripts" / "framework" / "protected_surfaces.txt"
        surfaces_path.parent.mkdir(parents=True, exist_ok=True)
        surfaces_path.write_text(".claude/agents/worker.md\n")

        # Human approval review
        human_review = [
            {
                "state": "APPROVED",
                "user": {"login": "ScottThurlow"},
            }
        ]

        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "changed_files": [".claude/agents/worker.md"]},
                repo_root=str(tmp_path),
                reviews=human_review,
            )
        assert result.decision == MergeDecision.AUTO_MERGE

    def test_protected_surface_ignores_non_human_approvals(self, tmp_path):
        # Create protected_surfaces.txt
        surfaces_path = tmp_path / "scripts" / "framework" / "protected_surfaces.txt"
        surfaces_path.parent.mkdir(parents=True, exist_ok=True)
        surfaces_path.write_text(".claude/agents/worker.md\n")

        # Approval from a bot, not the human
        bot_review = [
            {
                "state": "APPROVED",
                "user": {"login": "hos-overseer-hos[bot]"},
            }
        ]

        with _patch_gate(True):
            result = decide_merge_authority(
                **{**self.BASE, "changed_files": [".claude/agents/worker.md"]},
                repo_root=str(tmp_path),
                reviews=bot_review,
            )
        assert result.decision == MergeDecision.HUMAN_REQUIRED


class TestRiskTierEnum:
    def test_ordering(self):
        assert RiskTier.LOW.value < RiskTier.MEDIUM.value < RiskTier.HIGH.value

    def test_from_str(self):
        assert RiskTier.from_str("medium") == RiskTier.MEDIUM
