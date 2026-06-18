"""
Tests for Phase C modules: breakers, observability, self_review_source,
multi_customer. Shell script syntax checks for orchestrator + worker.
"""

import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── breakers ──────────────────────────────────────────────────────────────────

from scripts.automation.lib.breakers import (
    blast_radius_ok,
    dead_man_triggered,
    failure_count,
    is_poisoned,
    is_shadow_mode,
    record_probe_completion,
    record_task_failure,
    runtime_exceeded,
)


class TestFailureCap:
    def test_increments_and_reads(self, tmp_path):
        record_task_failure("abc", str(tmp_path))
        record_task_failure("abc", str(tmp_path))
        assert failure_count("abc", str(tmp_path)) == 2

    def test_unknown_cid_returns_zero(self, tmp_path):
        assert failure_count("unknown", str(tmp_path)) == 0

    def test_poisoned_at_threshold(self, tmp_path):
        for _ in range(3):
            record_task_failure("cid1", str(tmp_path))
        assert is_poisoned("cid1", max_failures=3, repo_root=str(tmp_path))

    def test_not_poisoned_below_threshold(self, tmp_path):
        record_task_failure("cid2", str(tmp_path))
        assert not is_poisoned("cid2", max_failures=3, repo_root=str(tmp_path))


class TestBlastRadiusOk:
    def test_ok_when_no_activity(self, tmp_path):
        ok, reason = blast_radius_ok("cps", repo_root=str(tmp_path))
        assert ok

    def test_blocked_when_pr_cap_hit(self, tmp_path):
        from scripts.automation.lib.ledger import LedgerWriter
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        for _ in range(5):
            writer.log("merge", "hos-overseer", "merged", prs=1)
        ok, reason = blast_radius_ok("cps", caps={"prs": 5, "issues": 10, "files": 25}, repo_root=str(tmp_path))
        assert not ok
        assert "prs" in reason.lower()


class TestRuntimeExceeded:
    def test_not_exceeded_for_recent_start(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert not runtime_exceeded(now, max_runtime_hours=4.0)

    def test_exceeded_for_old_start(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert runtime_exceeded(old, max_runtime_hours=4.0)

    def test_invalid_timestamp_fails_closed(self):
        assert runtime_exceeded("not-a-timestamp")


class TestDeadManSwitch:
    def test_triggers_when_never_probed(self, tmp_path):
        assert dead_man_triggered("cps", threshold_hours=6.0, repo_root=str(tmp_path))

    def test_does_not_trigger_after_recent_probe(self, tmp_path):
        record_probe_completion("cps", str(tmp_path))
        assert not dead_man_triggered("cps", threshold_hours=6.0, repo_root=str(tmp_path))

    def test_triggers_after_old_probe(self, tmp_path):
        # Write an old timestamp directly
        path = Path(str(tmp_path)) / ".ai-local" / "hos-automation" / "deadman-last-probe.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        old = (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps({"cps": old}))
        assert dead_man_triggered("cps", threshold_hours=6.0, repo_root=str(tmp_path))


class TestShadowMode:
    def test_propose_only_is_shadow(self):
        assert is_shadow_mode("propose-only")

    def test_autonomous_is_not_shadow(self):
        assert not is_shadow_mode("autonomous")


# ── observability ─────────────────────────────────────────────────────────────

from scripts.automation.lib.observability import (
    activity_report,
    append_to_markdown_log,
    regenerate_markdown_log,
    summarize_run,
)
from scripts.automation.lib.ledger import LedgerWriter, make_record


class TestMarkdownLog:
    def test_regenerate_creates_file(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("triage", "hos-worker", "classified")
        regenerate_markdown_log("cps", str(tmp_path))
        log = (tmp_path / "audit" / "automation" / "cps" / "automation-log.md").read_text()
        assert "triage" in log
        assert "hos-worker" in log

    def test_append_creates_header_if_missing(self, tmp_path):
        rec = make_record("inst1", "abc", "cps", "merge", "hos-overseer", "merged")
        append_to_markdown_log("cps", rec, str(tmp_path))
        log = (tmp_path / "audit" / "automation" / "cps" / "automation-log.md").read_text()
        assert "merge" in log

    def test_summarize_run_returns_string(self, tmp_path):
        writer = LedgerWriter("cps", repo_root=str(tmp_path))
        writer.log("triage", "hos-worker", "classified")
        summary = summarize_run("cps", writer.instance_id, str(tmp_path))
        assert "instance_id" in summary.lower() or writer.instance_id in summary

    def test_activity_report_empty(self, tmp_path):
        report = activity_report("cps", window_hours=1.0, repo_root=str(tmp_path))
        assert "No activity" in report


# ── self_review_source ───────────────────────────────────────────────────────

from scripts.automation.lib.self_review_source import (
    HUMAN_ONLY_SUPPRESSION_CLASSES,
    SelfReviewFinding,
    burndown_count,
    fingerprint,
    is_suppressed,
    suppress,
)


class TestFingerprint:
    def test_deterministic(self):
        fp1 = fingerprint(["a.py", "b.py"], "bug")
        fp2 = fingerprint(["b.py", "a.py"], "bug")  # order-invariant
        assert fp1 == fp2

    def test_different_class_different_fp(self):
        assert fingerprint(["a.py"], "bug") != fingerprint(["a.py"], "style")

    def test_length_16_hex(self):
        fp = fingerprint(["a.py"], "bug")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)


class TestSuppression:
    def test_suppress_and_detect(self, tmp_path):
        fp = fingerprint(["a.py"], "style")
        suppress(fp, "won't fix", "style", "raw text", repo_root=str(tmp_path))
        assert is_suppressed(fp, str(tmp_path))

    def test_unknown_fp_not_suppressed(self, tmp_path):
        assert not is_suppressed("deadbeef00000000", str(tmp_path))

    def test_human_only_class_raises(self, tmp_path):
        fp = fingerprint(["auth.py"], "security")
        with pytest.raises(ValueError, match="HUMAN_ONLY"):
            suppress(fp, "won't fix", "security", "raw", repo_root=str(tmp_path))

    def test_human_only_classes_defined(self):
        assert "security" in HUMAN_ONLY_SUPPRESSION_CLASSES
        assert "privacy" in HUMAN_ONLY_SUPPRESSION_CLASSES
        assert "license" in HUMAN_ONLY_SUPPRESSION_CLASSES


class TestBurndown:
    def test_empty_returns_zero_counts(self, tmp_path):
        counts = burndown_count(str(tmp_path))
        assert counts["total_filed"] == 0


# ── multi_customer ────────────────────────────────────────────────────────────

from scripts.automation.lib.multi_customer import (
    global_kill_active,
    next_customer_order,
    probe_with_isolation,
)


class TestGlobalKillActive:
    def test_inactive_when_no_halt_file(self, tmp_path):
        assert not global_kill_active(str(tmp_path))

    def test_active_when_halt_file_present(self, tmp_path):
        halt = tmp_path / "PROJECT" / "hos-halt"
        halt.parent.mkdir(parents=True)
        halt.write_text("halted\n")
        assert global_kill_active(str(tmp_path))

    def test_not_active_when_halt_file_empty(self, tmp_path):
        halt = tmp_path / ".hos-halt"
        halt.write_text("")  # empty file — not active
        assert not global_kill_active(str(tmp_path))


class TestNextCustomerOrder:
    def test_empty_list_returns_empty(self, tmp_path):
        assert next_customer_order([], repo_root=str(tmp_path)) == []

    def test_returns_all_customers(self, tmp_path):
        customers = [
            {"owner": "a", "repo": "r1"},
            {"owner": "b", "repo": "r2"},
        ]
        result = next_customer_order(customers, repo_root=str(tmp_path))
        assert len(result) == 2

    def test_rotates_on_second_call(self, tmp_path):
        customers = [
            {"owner": "a", "repo": "r1"},
            {"owner": "b", "repo": "r2"},
            {"owner": "c", "repo": "r3"},
        ]
        first = next_customer_order(customers, repo_root=str(tmp_path))[0]
        second = next_customer_order(customers, repo_root=str(tmp_path))[0]
        # Second call should start from the next index
        assert first != second or len(customers) == 1


class TestProbeWithIsolation:
    def test_failure_returns_empty_not_raises(self, tmp_path):
        # probe_repo is imported inside the function body, so patch at the source module
        with patch(
            "scripts.automation.lib.probe.probe_repo",
            side_effect=RuntimeError("network error"),
        ):
            result = probe_with_isolation("o", "r", "o-r", [], repo_root=str(tmp_path))
        assert result == []


# ── Shell script syntax checks ────────────────────────────────────────────────

ORCHESTRATOR = Path(__file__).parent.parent.parent / "scripts" / "automation" / "hos_orchestrator.sh"
WORKER = Path(__file__).parent.parent.parent / "scripts" / "automation" / "hos_worker.sh"


class TestShellSyntax:
    def test_orchestrator_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ORCHESTRATOR)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_worker_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(WORKER)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_orchestrator_requires_class_arg(self):
        result = subprocess.run(
            ["bash", str(ORCHESTRATOR), "hos-orchestrator"],
            capture_output=True, text=True, timeout=5,
            env={"HOME": "/tmp", "PATH": "/usr/bin:/bin"},
        )
        # Should exit with error (missing --class)
        assert result.returncode != 0 or "class" in result.stderr.lower()

    def test_orchestrator_contains_gate_order_markers(self):
        """Orchestrator script contains all required gate-order steps (§11)."""
        content = ORCHESTRATOR.read_text()
        for marker in [
            "step 0",          # git pull (#300)
            "step 1",          # activation check
            "step 2",          # hos-halt check
            "step 3",          # machine lock
            "step 4",          # config resolve
            "step 5",          # probe
            "hos-orchestrator", # O18 argv marker
            "--class",         # two-cronjob class flag
        ]:
            assert marker in content, f"Missing gate marker: {marker!r}"

    def test_worker_contains_heartbeat_recheck(self):
        """Worker script rechecks activation + halt at every heartbeat."""
        content = WORKER.read_text()
        assert "_check_still_active" in content
        assert "hos-halt" in content
        assert "heartbeat" in content.lower()
