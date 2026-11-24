"""#2357 S1b: bin/lib/osr_phase.py, the helper behind the overseer second-review phase of
bin/hos-cron (TD-2357-S1b sections 3.2, 4, 5 and 6; tests T-PH-01..23).

The helper is stdlib-only and loaded by path, as bin/hos-cron runs it (`python3 -I`). Every
test drives `main()` in-process against real files under pytest's tmp_path: the runner's
result line is written to a file, `ingest` reads it, and the rendered block is read back.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.automation.lib import overseer_second_review as osr
from tests.tmp_hygiene import child_env

HELPER = Path(__file__).resolve().parents[2] / "bin" / "lib" / "osr_phase.py"

_spec = importlib.util.spec_from_file_location("hos_osr_phase_under_test", HELPER)
assert _spec and _spec.loader
ph = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ph)

HEAD = "1" * 40
HEAD2 = "4" * 40
BASE = "2" * 40
PR = 7

# The line grammar exactly as TD-2357-S1b 5.2 states it, kept apart from the helper's own copy.
TD_LINE_RE = re.compile(
    r"^OSR pr=#[1-9][0-9]{0,6} head=([0-9a-f]{40}|-) base=([0-9a-f]{40}|-) "
    r"tier=(LOW|MEDIUM|HIGH|CRITICAL|-) vendors=(none|agy|agy\+codex|-) "
    r"verdict=(approve|request_changes|not-required|hold|pending|skipped-held) "
    r"reason=[a-z0-9:-]{1,64} findings_file=(/[A-Za-z0-9._/+-]{1,512}|-) "
    r"reused=(true|false) persisted=(true|false|-) count=([1-9][0-9]{0,5}|-) "
    r"last_reason=([a-z0-9:-]{1,64}|-) label=(applied|failed|existing|-)$"
)


class Phase:
    """A state dir, a scratch dir and a runs dir laid out as the phase lays them out."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.state = tmp_path / "state"
        self.scratch = tmp_path / "scratch"
        self.second_review = (
            tmp_path / "repo" / ".claudetmp" / "overseer-authority" / "second-review"
        )
        self.runs = self.second_review / "runs"
        self.records = self.second_review / "records"
        for d in (self.state, self.scratch, self.runs, self.records):
            d.mkdir(parents=True, mode=0o700, exist_ok=True)

    # -- runner results ------------------------------------------------------------
    def record_path(self, pr=PR, head=HEAD, vendorset="agy"):
        return str(self.records / f"pr{pr}-{head}-{vendorset}.json")

    def findings_path(self, pr=PR):
        run_dir = self.runs / f"pr{pr}-111111111111-20261118T120000Z-abc"
        run_dir.mkdir(exist_ok=True)
        return str(run_dir / "findings.json")

    def approve(self, pr=PR, **over):
        result = {
            "check": "second-review",
            "schema": 1,
            "pr": pr,
            "head_sha": HEAD,
            "base_sha": BASE,
            "range": f"{BASE}..{HEAD}",
            "tier": "MEDIUM",
            "vendors": "agy",
            "verdict": "approve",
            "status": "final",
            "reason": "ok",
            "reused": False,
            "findings_file": None,
            "record": self.record_path(pr),
            "hold_label_applied": None,
            "pending_count": None,
            "pending_last_reason": None,
        }
        result.update(over)
        return result

    def request_changes(self, pr=PR, **over):
        return self.approve(
            pr,
            **{
                "verdict": "request_changes",
                "reason": "findings",
                "findings_file": self.findings_path(pr),
                **over,
            },
        )

    def hold(self, reason="unparseable", pr=PR, **over):
        return self.approve(
            pr,
            **{
                "verdict": "hold",
                "status": "hold",
                "reason": reason,
                "hold_label_applied": False,
                **over,
            },
        )

    def pending(self, reason, pr=PR, **over):
        return self.approve(
            pr,
            **{
                "verdict": "pending",
                "status": None,
                "reason": reason,
                "record": None,
                **over,
            },
        )

    # -- running the helper --------------------------------------------------------
    def run(self, capsys, *argv):
        capsys.readouterr()
        code = ph.main([str(a) for a in argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def ingest(self, capsys, payload, *, pr=PR, rc=0, cache_only=0, held=0):
        """(stdout words, line fields, stderr). `payload` is a dict (JSON-encoded) or bytes."""
        out = self.root / f"pr{pr}.out"
        err = self.root / f"pr{pr}.err"
        out.write_bytes(
            payload if isinstance(payload, bytes) else (json.dumps(payload) + "\n").encode()
        )
        err.write_text("runner stderr\n")
        code, stdout, stderr = self.run(
            capsys,
            "ingest",
            "--state-dir",
            self.state,
            "--runs-dir",
            self.runs,
            "--pr",
            pr,
            "--rc",
            rc,
            "--cache-only",
            cache_only,
            "--held",
            held,
            "--out",
            out,
            "--err",
            err,
            "--scratch",
            self.scratch,
        )
        assert code == 0, stderr
        match = re.fullmatch(r"ACTION=(label|none) UNCACHED=([01])\n", stdout)
        assert match, stdout
        return (match.group(1), match.group(2)), self.line(pr), stderr

    def synthetic(self, capsys, reason, *, pr=PR):
        code, stdout, stderr = self.run(
            capsys,
            "ingest",
            "--state-dir",
            self.state,
            "--pr",
            pr,
            "--synthetic",
            reason,
            "--scratch",
            self.scratch,
        )
        assert code == 0, stderr
        match = re.fullmatch(r"ACTION=(label|none) UNCACHED=([01])\n", stdout)
        assert match, stdout
        return (match.group(1), match.group(2)), self.line(pr)

    def line(self, pr=PR):
        return json.loads((self.scratch / f"pr{pr}.line.json").read_text())

    def render(self, capsys, prs, held=()):
        code, stdout, stderr = self.run(
            capsys,
            "render",
            "--scratch",
            self.scratch,
            "--prs",
            " ".join(str(n) for n in prs),
            "--held",
            " ".join(str(n) for n in held),
        )
        assert code == 0, stderr
        return stdout.splitlines()

    def osr_line(self, capsys, pr=PR):
        lines = self.render(capsys, [pr])
        assert lines[0] == "[hos-cron overseer second review (#2357)]" and lines[-1] == "---"
        assert len(lines) == 3
        return lines[1]

    def strike_file(self, pr=PR):
        return self.state / "strikes" / f"pr{pr}.json"


@pytest.fixture
def phase(tmp_path):
    return Phase(tmp_path)


# =============================================================================
# T-PH-01 .. 09: validating the runner's line and rendering it
# =============================================================================


def test_ph01_a_valid_approve_renders_the_exact_line(phase, capsys):
    action, line, _ = phase.ingest(capsys, phase.approve())
    assert action == ("none", "1")
    rendered = phase.osr_line(capsys)
    assert rendered == (
        f"OSR pr=#7 head={HEAD} base={BASE} tier=MEDIUM vendors=agy verdict=approve reason=ok "
        "findings_file=- reused=false persisted=true count=- last_reason=- label=-"
    )
    assert TD_LINE_RE.match(rendered)
    assert line["head"] == HEAD and line["base"] == BASE and line["tier"] == "MEDIUM"


@pytest.mark.parametrize(
    "verdict_result, expected",
    [
        (
            lambda p: p.request_changes(reused=True, tier="HIGH", vendors="agy+codex"),
            "tier=HIGH vendors=agy+codex verdict=request_changes reason=findings "
            "findings_file={findings} reused=true persisted=true count=- last_reason=- label=-",
        ),
        (
            lambda p: p.approve(
                tier="LOW", vendors="none", verdict="not-required", reason="tier-below-medium"
            ),
            "tier=LOW vendors=none verdict=not-required reason=tier-below-medium "
            "findings_file=- reused=false persisted=true count=- last_reason=- label=-",
        ),
        (
            lambda p: p.hold("vendor-timeout:agy", tier="CRITICAL", vendors="agy+codex"),
            "tier=CRITICAL vendors=agy+codex verdict=hold reason=vendor-timeout:agy "
            "findings_file=- reused=false persisted=true count=- last_reason=- label=-",
        ),
    ],
)
def test_ph01_every_runner_field_reaches_the_rendered_line(phase, capsys, verdict_result, expected):
    result = verdict_result(phase)
    phase.ingest(capsys, result)
    rendered = phase.osr_line(capsys)
    prefix = f"OSR pr=#7 head={HEAD} base={BASE} "
    assert rendered == prefix + expected.format(findings=result["findings_file"])
    assert TD_LINE_RE.match(rendered)


@pytest.mark.parametrize("key", sorted(ph.RESULT_KEYS))
def test_ph02_a_missing_key_is_an_invalid_line_strike(phase, capsys, key):
    result = phase.approve()
    del result[key]
    action, line, err = phase.ingest(capsys, result)
    assert action == ("none", "1")
    assert (line["verdict"], line["reason"], line["count"]) == ("pending", "invalid-line", 1)
    assert "rejected (keys)" in err


def test_ph02_an_extra_key_is_an_invalid_line_strike(phase, capsys):
    _, line, _ = phase.ingest(capsys, phase.approve(surprise=1))
    assert (line["verdict"], line["reason"], line["last_reason"]) == (
        "pending",
        "invalid-line",
        "invalid-line",
    )


@pytest.mark.parametrize(
    "over",
    [
        {"pr": 8},
        {"pr": True},
        {"check": "other"},
        {"schema": 2},
        {"schema": True},
    ],
)
def test_ph03_a_result_for_another_pr_or_schema_is_invalid(phase, capsys, over):
    _, line, _ = phase.ingest(capsys, phase.approve(**over))
    assert line["reason"] == "invalid-line"


@pytest.mark.parametrize(
    "over",
    [
        {"range": f"{HEAD}..{BASE}"},
        {"range": "main..head"},
        {"base_sha": None},
        {"head_sha": "xyz"},
        {"base_sha": "A" * 40},
        {"head_sha": None},
    ],
)
def test_ph04_a_range_that_is_not_base_dot_dot_head_is_invalid(phase, capsys, over):
    _, line, _ = phase.ingest(capsys, phase.approve(**over))
    assert line["reason"] == "invalid-line"


def test_ph04_a_null_range_with_null_base_is_accepted(phase, capsys):
    stuck = phase.hold(
        "pending-stuck",
        base_sha=None,
        range=None,
        record=None,
        hold_label_applied=None,
        pending_count=3,
        pending_last_reason="review-failed",
    )
    phase.ingest(capsys, stuck)
    assert phase.line()["reason"] == "pending-stuck"
    assert phase.line()["base"] is None


@pytest.mark.parametrize(
    "over",
    [
        {"vendors": None},
        {"tier": "SAFE"},
        {"tier": "medium"},
        {"vendors": "codex"},
        {"vendors": ["agy"]},
    ],
)
def test_ph05_a_tier_or_vendor_set_outside_the_vocabulary_is_invalid(phase, capsys, over):
    _, line, _ = phase.ingest(capsys, phase.approve(**over))
    assert line["reason"] == "invalid-line"


def test_ph05_a_null_tier_renders_dashes_for_tier_and_vendors(phase, capsys):
    # A hold written before the tier was known carries a placeholder vendor set (S1b 7.2).
    result = phase.hold(
        "pending-stuck",
        tier=None,
        vendors="agy+codex",
        base_sha=None,
        range=None,
        pending_count=3,
        pending_last_reason="review-failed",
    )
    phase.ingest(capsys, result)
    rendered = phase.osr_line(capsys)
    assert "tier=- vendors=- verdict=hold reason=pending-stuck" in rendered
    assert TD_LINE_RE.match(rendered)


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.approve(findings_file=p.findings_path()),
        lambda p: p.request_changes(findings_file=None),
        lambda p: p.request_changes(findings_file="/tmp/elsewhere/findings.json"),
        lambda p: p.request_changes(findings_file=str(p.runs) + "/../records/x.json"),
        lambda p: p.request_changes(findings_file=str(p.runs) + "/has space/findings.json"),
        lambda p: p.request_changes(findings_file="relative/findings.json"),
    ],
)
def test_ph06_findings_file_belongs_to_request_changes_under_runs_only(phase, capsys, result_of):
    _, line, _ = phase.ingest(capsys, result_of(phase))
    assert line["reason"] == "invalid-line"


def test_ph06_a_findings_path_through_a_symlink_out_of_runs_is_invalid(phase, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = phase.runs / "linked"
    link.symlink_to(outside)
    result = phase.request_changes(findings_file=str(link / "findings.json"))
    _, line, _ = phase.ingest(capsys, result)
    assert line["reason"] == "invalid-line"


def test_ph06_a_findings_file_under_runs_is_accepted(phase, capsys):
    phase.ingest(capsys, phase.request_changes())
    assert phase.line()["verdict"] == "request_changes"


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.approve(record=None),
        lambda p: p.hold("unparseable", record=None),
        lambda p: p.pending("fetch-failed", record=p.record_path()),
        lambda p: p.approve(record="relative.json"),
        lambda p: p.approve(record="/tmp/elsewhere/pr7.json"),
        lambda p: p.approve(record=str(p.records) + "/../x.json"),
    ],
)
def test_ph07_record_is_a_path_under_records_except_where_it_may_be_null(phase, capsys, result_of):
    _, line, _ = phase.ingest(capsys, result_of(phase))
    assert line["reason"] == "invalid-line"


def test_ph07_a_pending_stuck_hold_may_have_no_record(phase, capsys):
    result = phase.hold(
        "pending-stuck",
        record=None,
        hold_label_applied=None,
        pending_count=3,
        pending_last_reason="review-failed",
    )
    action, line, _ = phase.ingest(capsys, result)
    assert action == ("label", "1")
    assert (line["verdict"], line["reason"], line["persisted"]) == ("hold", "pending-stuck", False)


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.hold("unparseable", hold_label_applied=None),
        lambda p: p.hold("unparseable", hold_label_applied="yes"),
        lambda p: p.hold("unparseable", hold_label_applied=1),
        lambda p: p.approve(hold_label_applied=True),
        lambda p: p.pending("fetch-failed", hold_label_applied=False),
    ],
)
def test_ph08_hold_label_applied_is_a_bool_exactly_when_a_hold_has_a_record(
    phase, capsys, result_of
):
    _, line, _ = phase.ingest(capsys, result_of(phase))
    assert line["reason"] == "invalid-line"


@pytest.mark.parametrize("applied", [True, False])
def test_ph08_a_boolean_hold_label_applied_is_accepted(phase, capsys, applied):
    phase.ingest(capsys, phase.hold("unparseable", hold_label_applied=applied))
    assert phase.line()["reason"] == "unparseable"


def test_ph09_a_counted_pending_surfaces_count_and_last_reason(phase, capsys):
    result = phase.pending(
        "review-failed",
        pending_count=2,
        pending_last_reason="review-failed",
        tier="HIGH",
        vendors="agy+codex",
    )
    action, line, _ = phase.ingest(capsys, result)
    assert action == ("none", "1")
    rendered = phase.osr_line(capsys)
    assert "verdict=pending reason=review-failed" in rendered
    assert "persisted=- count=2 last_reason=review-failed label=-" in rendered
    assert not phase.strike_file().exists()
    assert (line["count"], line["last_reason"]) == (2, "review-failed")


@pytest.mark.parametrize(
    "over",
    [
        {"pending_count": 1, "pending_last_reason": None},
        {"pending_count": None, "pending_last_reason": "review-failed"},
        {"pending_count": 0, "pending_last_reason": "review-failed"},
        {"pending_count": True, "pending_last_reason": "review-failed"},
        {"pending_count": 1, "pending_last_reason": "budget"},
        {"pending_count": 1, "pending_last_reason": "unknown"},
    ],
)
def test_ph09_a_counted_pending_with_inconsistent_counter_keys_is_invalid(phase, capsys, over):
    _, line, _ = phase.ingest(capsys, phase.pending("review-failed", **over))
    assert line["reason"] == "invalid-line"


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.pending("budget", pending_count=1, pending_last_reason="review-failed"),
        lambda p: p.approve(pending_count=3, pending_last_reason="review-failed"),
        lambda p: p.hold("pending-stuck", pending_count=2, pending_last_reason="review-failed"),
        lambda p: p.hold("pending-stuck", pending_count=3, pending_last_reason=None),
        lambda p: p.hold("pending-stuck", pending_count=None, pending_last_reason=None),
    ],
)
def test_ph09_the_counter_keys_are_set_only_where_the_runner_advanced_its_counter(
    phase, capsys, result_of
):
    _, line, _ = phase.ingest(capsys, result_of(phase))
    assert line["reason"] == "invalid-line"


def test_ph09_a_stuck_hold_this_call_wrote_carries_count_and_last_reason(phase, capsys):
    result = phase.hold(
        "pending-stuck", pending_count=3, pending_last_reason="diff-failed", reused=False
    )
    action, _, _ = phase.ingest(capsys, result)
    assert action == ("label", "1")
    rendered = phase.osr_line(capsys)
    assert "verdict=hold reason=pending-stuck" in rendered
    assert "persisted=true count=3 last_reason=diff-failed label=-" in rendered


def test_ph09_a_reused_stuck_hold_carries_no_counter(phase, capsys):
    phase.ingest(capsys, phase.hold("pending-stuck", reused=True))
    assert phase.line()["count"] is None


# =============================================================================
# T-PH-10 .. 13: strikes
# =============================================================================


@pytest.mark.parametrize("rc", [1, 2, 124, 137])
def test_ph10_a_failing_runner_strikes_to_a_hold_on_the_third(phase, capsys, rc):
    outcomes = []
    for _ in range(3):
        action, line, err = phase.ingest(capsys, b"", rc=rc)
        outcomes.append((action[0], line["verdict"], line["reason"], line["count"]))
        assert f"exited {rc}" in err
    assert outcomes == [
        ("none", "pending", "runner-failed", 1),
        ("none", "pending", "runner-failed", 2),
        ("label", "hold", "pending-stuck", 3),
    ]
    assert phase.line()["persisted"] is False
    assert phase.line()["last_reason"] == "runner-failed"
    rendered = phase.osr_line(capsys)
    assert "verdict=hold reason=pending-stuck" in rendered
    assert "persisted=false count=3 last_reason=runner-failed" in rendered
    stored = json.loads(phase.strike_file().read_text())
    assert (stored["count"], stored["last_reason"], stored["pr"]) == (3, "runner-failed", PR)


def test_ph10_a_failed_run_counts_as_an_uncached_review_unless_cache_only(phase, capsys):
    assert phase.ingest(capsys, b"", rc=1)[0] == ("none", "1")
    assert phase.ingest(capsys, b"", rc=1, cache_only=1)[0] == ("none", "0")


def test_ph10_the_runner_stderr_excerpt_is_printable_ascii_only(phase, capsys):
    phase.ingest(capsys, b"", rc=1)
    err = phase.root / f"pr{PR}.err"
    err.write_bytes(b"boom\x1b[31m\nfake log line\x00end")
    code, _, stderr = phase.run(
        capsys,
        "ingest",
        "--state-dir", phase.state, "--runs-dir", phase.runs, "--pr", PR, "--rc", 1,
        "--out", phase.root / f"pr{PR}.out", "--err", err, "--scratch", phase.scratch,
    )  # fmt: skip
    assert code == 0
    assert "\x1b" not in stderr and "\x00" not in stderr
    assert stderr.count("\n") == 1


def test_ph11_a_non_strike_result_deletes_the_strike_file(phase, capsys):
    phase.ingest(capsys, b"", rc=1)
    assert phase.strike_file().exists()
    phase.ingest(capsys, phase.approve())
    assert not phase.strike_file().exists()


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.request_changes(),
        lambda p: p.hold("unparseable"),
        lambda p: p.pending("review-failed", pending_count=1, pending_last_reason="review-failed"),
    ],
)
def test_ph11_every_runner_verdict_other_than_a_strike_resets_the_count(phase, capsys, result_of):
    phase.ingest(capsys, b"", rc=1)
    phase.ingest(capsys, result_of(phase))
    assert not phase.strike_file().exists()
    _, line, _ = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 1


def test_ph11_a_new_head_resets_the_count_but_an_unknown_head_does_not(phase, capsys):
    lock_busy = phase.pending("lock-busy")
    phase.ingest(capsys, lock_busy)
    _, line, _ = phase.ingest(capsys, lock_busy)
    assert line["count"] == 2
    # A strike with no head (a runner crash) keeps counting against the stored head.
    _, line, _ = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 3
    phase.ingest(capsys, phase.pending("lock-busy", head_sha=HEAD2, range=f"{BASE}..{HEAD2}"))
    stored = json.loads(phase.strike_file().read_text())
    assert (stored["count"], stored["head"]) == (1, HEAD2)


def test_ph11_a_stored_null_head_never_resets(phase, capsys):
    phase.ingest(capsys, b"", rc=1)
    phase.ingest(capsys, phase.pending("github-error", head_sha=HEAD, range=f"{BASE}..{HEAD}"))
    stored = json.loads(phase.strike_file().read_text())
    assert (stored["count"], stored["head"]) == (2, HEAD)


def test_ph11_neutral_results_leave_the_strike_untouched(phase, capsys):
    phase.ingest(capsys, b"", rc=1)
    before = phase.strike_file().read_bytes()
    for reason in ("head-moved", "pr-not-found", "pr-not-open", "budget"):
        action, line, _ = phase.ingest(capsys, phase.pending(reason), cache_only=1)
        assert action[0] == "none"
        assert (line["verdict"], line["reason"], line["count"]) == ("pending", reason, None)
    assert phase.strike_file().read_bytes() == before


def test_ph12_a_strike_that_cannot_be_written_holds_state_write_failed(phase, capsys):
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    strikes = phase.state / "strikes"
    strikes.mkdir(mode=0o700)
    strikes.chmod(0o500)
    try:
        action, line, err = phase.ingest(capsys, b"", rc=1)
    finally:
        strikes.chmod(0o700)
    assert action == ("label", "1")
    assert (line["verdict"], line["reason"], line["persisted"]) == (
        "hold",
        "state-write-failed",
        False,
    )
    assert "could not write the strike file" in err
    assert "verdict=hold reason=state-write-failed" in phase.osr_line(capsys)


def _write_strike(phase, count=2, mode=0o600):
    strikes = phase.state / "strikes"
    strikes.mkdir(mode=0o700, exist_ok=True)
    path = strikes / f"pr{PR}.json"
    path.write_text(
        json.dumps(
            {"schema": 1, "pr": PR, "head": None, "count": count, "last_reason": "runner-failed"}
        )
    )
    path.chmod(mode)
    return path


def test_ph13_a_trusted_strike_file_is_counted(phase, capsys):
    _write_strike(phase, count=1)
    _, line, err = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 2 and "untrusted" not in err and "malformed" not in err


def test_ph13_a_strike_file_with_group_access_counts_as_zero_with_a_warning(phase, capsys):
    _write_strike(phase, count=2, mode=0o640)
    _, line, err = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 1
    assert "untrusted state file pr7.json ignored" in err


def test_ph13_a_strike_file_owned_by_another_uid_counts_as_zero(phase, capsys, monkeypatch):
    _write_strike(phase, count=2)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    _, line, err = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 1
    assert "untrusted state file" in err


def test_ph13_a_symlinked_strike_file_counts_as_zero(phase, capsys, tmp_path):
    real = tmp_path / "real-strike.json"
    real.write_text("{}")
    (phase.state / "strikes").mkdir(mode=0o700)
    (phase.state / "strikes" / f"pr{PR}.json").symlink_to(real)
    _, line, err = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 1
    assert "cannot open pr7.json" in err


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"schema": 2, "pr": PR, "head": None, "count": 2}),
        json.dumps({"schema": 1, "pr": 8, "head": None, "count": 2}),
        json.dumps({"schema": 1, "pr": PR, "head": None, "count": 0}),
        json.dumps({"schema": 1, "pr": PR, "head": "short", "count": 2}),
        json.dumps({"schema": 1, "pr": PR, "head": None, "count": True}),
    ],
)
def test_ph13_a_malformed_strike_file_counts_as_zero(phase, capsys, content):
    path = _write_strike(phase)
    path.write_text(content)
    _, line, err = phase.ingest(capsys, b"", rc=1)
    assert line["count"] == 1
    assert "WARN" in err


# =============================================================================
# T-PH-14, 15, 23: budget, order, defer
# =============================================================================


@pytest.mark.parametrize(
    "elapsed, ran, expected",
    [
        (0, 1, "RUN"),
        (50, 1, "RUN"),  # elapsed + per_pr == budget
        (51, 1, "CACHE_ONLY"),
        (10_000, 0, "RUN"),  # the first uncached review of a cycle always runs
        (10_000, 1, "CACHE_ONLY"),
        (0, 0, "RUN"),
    ],
)
def test_ph14_ph23_budget_arithmetic(phase, capsys, elapsed, ran, expected):
    code, out, _ = phase.run(
        capsys,
        "budget", "--elapsed", elapsed, "--uncached-ran", ran, "--per-pr", 50, "--budget", 100,
    )  # fmt: skip
    assert (code, out.strip()) == (0, expected)


def test_ph14_budget_rejects_a_non_integer_and_a_bad_flag(phase, capsys):
    with pytest.raises(SystemExit) as info:
        ph.main(
            ["budget", "--elapsed", "x", "--uncached-ran", "1", "--per-pr", "1", "--budget", "1"]
        )
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        ph.main(
            ["budget", "--elapsed", "1", "--uncached-ran", "2", "--per-pr", "1", "--budget", "1"]
        )
    assert info.value.code == 2


def test_ph15_order_puts_deferred_prs_first_then_ascending(phase, capsys):
    code, out, _ = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", "30 12 9 21")
    assert out.split() == ["9", "12", "21", "30"]
    phase.run(capsys, "defer", "--state-dir", phase.state, "--pr", 21)
    phase.run(capsys, "defer", "--state-dir", phase.state, "--pr", 12)
    code, out, _ = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", "30 12 9 21")
    assert out.split() == ["12", "21", "9", "30"]
    # A deferred PR that has left the actionable set is not invented back into the order.
    phase.run(capsys, "defer", "--state-dir", phase.state, "--pr", 99)
    code, out, _ = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", "9 12")
    assert out.split() == ["12", "9"]


def test_ph15_order_ignores_a_corrupt_deferred_file(phase, capsys):
    (phase.state / "deferred.json").write_text("garbage")
    (phase.state / "deferred.json").chmod(0o600)
    code, out, err = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", "5 3")
    assert (code, out.split()) == (0, ["3", "5"])


def test_ph15_a_result_for_a_deferred_pr_clears_its_deferral(phase, capsys):
    phase.run(capsys, "defer", "--state-dir", phase.state, "--pr", PR)
    phase.ingest(capsys, phase.approve())
    code, out, _ = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", f"3 {PR}")
    assert out.split() == ["3", str(PR)]


def test_ph23_a_cache_only_pending_budget_defers_the_pr_to_the_front(phase, capsys):
    action, line, _ = phase.ingest(capsys, phase.pending("budget"), cache_only=1)
    assert action == ("none", "0")
    assert (line["verdict"], line["reason"], line["count"]) == ("pending", "budget", None)
    code, out, _ = phase.run(capsys, "order", "--state-dir", phase.state, "--prs", f"3 {PR}")
    assert out.split() == [str(PR), "3"]
    assert not phase.strike_file().exists()


def test_ph23_a_cached_approve_in_cache_only_mode_is_not_uncached(phase, capsys):
    action, _, _ = phase.ingest(capsys, phase.approve(reused=True), cache_only=1)
    assert action == ("none", "0")


@pytest.mark.parametrize(
    "result_of, expected",
    [
        (lambda p: p.approve(), "1"),
        (lambda p: p.approve(reused=True), "0"),
        (lambda p: p.approve(tier="LOW", vendors="none", verdict="not-required",
                             reason="tier-below-medium"), "0"),
        (lambda p: p.hold("unparseable"), "1"),
        (lambda p: p.hold("binary-unreviewed", reused=True), "0"),
        (lambda p: p.pending("fetch-failed"), "1"),
        (lambda p: p.pending("held-label"), None),
    ],
)  # fmt: skip
def test_ph_uncached_reports_whether_a_vendor_review_may_have_run(
    phase, capsys, result_of, expected
):
    result = result_of(phase)
    if expected is None:
        result = phase.approve(verdict="skipped-held", status=None, reason="held-label",
                               record=None)  # fmt: skip
        expected = "0"
    action, _, _ = phase.ingest(capsys, result)
    assert action[1] == expected


# =============================================================================
# T-PH-16, 17: labels and rendering
# =============================================================================


def test_ph16_label_result_sets_the_label_field(phase, capsys):
    phase.ingest(capsys, phase.hold("unparseable"))
    assert phase.line()["label"] is None
    assert phase.run(capsys, "label-result", "--scratch", phase.scratch, "--pr", PR,
                     "--result", "applied")[0] == 0  # fmt: skip
    assert "label=applied" in phase.osr_line(capsys)
    phase.run(capsys, "label-result", "--scratch", phase.scratch, "--pr", PR, "--result", "failed")
    assert "label=failed" in phase.osr_line(capsys)


def test_ph16_a_hold_is_labelled_unless_the_pr_already_carries_the_label(phase, capsys):
    action, line, _ = phase.ingest(capsys, phase.hold("unparseable"))
    assert action == ("label", "1") and line["label"] is None
    action, line, _ = phase.ingest(capsys, phase.hold("unparseable", reused=True), held=1)
    assert action == ("none", "0")
    assert line["label"] == "existing"
    assert "label=existing" in phase.osr_line(capsys)


def test_ph16_a_held_pr_renders_skipped_held_without_a_label(phase, capsys):
    lines = phase.render(capsys, [PR], held=[PR])
    assert lines[1] == (
        f"OSR pr=#{PR} head=- base=- tier=- vendors=- verdict=skipped-held reason=held-label "
        "findings_file=- reused=false persisted=- count=- last_reason=- label=-"
    )
    assert TD_LINE_RE.match(lines[1])


def test_ph16_mark_args_names_the_head_only_for_a_persisted_hold(phase, capsys):
    phase.ingest(capsys, phase.hold("unparseable"))
    code, out, _ = phase.run(capsys, "mark-args", "--scratch", phase.scratch, "--pr", PR)
    assert out.strip() == f"MARK={HEAD}"
    phase.ingest(capsys, phase.hold("pending-stuck", record=None, hold_label_applied=None,
                                    pending_count=3, pending_last_reason="review-failed"))  # fmt: skip
    code, out, _ = phase.run(capsys, "mark-args", "--scratch", phase.scratch, "--pr", PR)
    assert out.strip() == "MARK=none"


def test_ph17_render_has_the_header_one_line_per_pr_in_order_and_the_terminator(phase, capsys):
    phase.ingest(capsys, phase.approve(pr=30), pr=30)
    phase.ingest(capsys, phase.hold("unparseable", pr=12), pr=12)
    lines = phase.render(capsys, [30, 99, 12], held=[99])
    assert lines[0] == "[hos-cron overseer second review (#2357)]"
    assert lines[-1] == "---"
    assert [line.split()[1] for line in lines[1:-1]] == ["pr=#30", "pr=#99", "pr=#12"]
    assert all(TD_LINE_RE.match(line) for line in lines[1:-1])


def test_ph17_render_fails_for_a_pr_with_no_line_and_for_a_corrupt_line(phase, capsys):
    code, _, err = phase.run(capsys, "render", "--scratch", phase.scratch, "--prs", "5")
    assert code == 1 and "FileNotFoundError" in err
    (phase.scratch / "pr5.line.json").write_text(
        json.dumps({"pr": 5, "verdict": "hold; rm -rf /", "reason": "x"})
    )
    code, _, err = phase.run(capsys, "render", "--scratch", phase.scratch, "--prs", "5")
    assert code == 1 and "does not match the OSR grammar" in err
    (phase.scratch / "pr5.line.json").write_text(json.dumps({"pr": 6}))
    code, _, err = phase.run(capsys, "render", "--scratch", phase.scratch, "--prs", "5")
    assert code == 1


def test_ph17_the_bash_rendered_phase_error_line_matches_the_grammar():
    line = (
        "OSR pr=#12 head=- base=- tier=- vendors=- verdict=pending reason=phase-error "
        "findings_file=- reused=false persisted=- count=- last_reason=- label=-"
    )
    assert TD_LINE_RE.match(line) and ph.LINE_RE.match(line)


def test_ph17_a_helper_hold_phase_error_line_renders(phase, capsys):
    (phase.scratch / "pr12.line.json").write_text(
        '{"pr":12,"head":null,"base":null,"tier":null,"vendors":null,"verdict":"hold",'
        '"reason":"phase-error","findings_file":null,"reused":false,"persisted":false,'
        '"count":null,"last_reason":null,"label":null}\n'
    )
    assert phase.render(capsys, [12])[1] == (
        "OSR pr=#12 head=- base=- tier=- vendors=- verdict=hold reason=phase-error "
        "findings_file=- reused=false persisted=false count=- last_reason=- label=-"
    )


# =============================================================================
# T-PH-18: what the runner's stdout may look like
# =============================================================================


def _good_bytes(phase):
    return (json.dumps(phase.approve()) + "\n").encode()


@pytest.mark.parametrize(
    "payload_of",
    [
        lambda p: _good_bytes(p) * 2,
        lambda p: b'{"pr": 7}' + b" " * ph.MAX_RUNNER_STDOUT + b"\n",
        lambda p: b"not json\n",
        lambda p: b"[1, 2]\n",
        lambda p: b"\n",
        lambda p: b"",
        lambda p: b"\xff\xfe\n",
        lambda p: _good_bytes(p).replace(b'"pr": 7', b'"pr": 7, "pr": 7'),
        lambda p: _good_bytes(p).rstrip(b"\n") + b"\r\n",
        lambda p: b"preamble\n" + _good_bytes(p),
    ],
)
def test_ph18_anything_but_one_json_object_line_is_an_invalid_line(phase, capsys, payload_of):
    action, line, err = phase.ingest(capsys, payload_of(phase))
    assert (line["verdict"], line["reason"]) == ("pending", "invalid-line")
    assert "rejected" in err


def test_ph18_a_missing_stdout_file_is_an_invalid_line(phase, capsys):
    out = phase.root / "absent.out"
    code, stdout, _ = phase.run(
        capsys, "ingest", "--state-dir", phase.state, "--runs-dir", phase.runs, "--pr", PR,
        "--rc", 0, "--out", out, "--err", phase.root / "absent.err", "--scratch", phase.scratch,
    )  # fmt: skip
    assert code == 0
    assert phase.line()["reason"] == "invalid-line"


def test_ph18_a_line_without_a_trailing_newline_is_accepted(phase, capsys):
    phase.ingest(capsys, json.dumps(phase.approve()).encode())
    assert phase.line()["verdict"] == "approve"


def test_ph18_exactly_64_kib_is_not_oversize(phase, capsys):
    body = json.dumps(phase.approve()).encode()
    padded = body + b" " * (ph.MAX_RUNNER_STDOUT - len(body) - 1) + b"\n"
    assert len(padded) == ph.MAX_RUNNER_STDOUT
    phase.ingest(capsys, padded)
    assert phase.line()["verdict"] == "approve"


@pytest.mark.parametrize(
    "over",
    [
        {"verdict": "bogus"},
        {"verdict": ["approve"]},
        {"status": "hold"},
        {"reason": "findings"},
        {"reused": "false"},
        {"reused": 0},
        {"head_sha": 7},
        {"pr": "7"},
    ],
)
def test_ph18_a_field_of_the_wrong_value_or_type_is_invalid(phase, capsys, over):
    _, line, _ = phase.ingest(capsys, phase.approve(**over))
    assert line["reason"] == "invalid-line"


@pytest.mark.parametrize(
    "result_of",
    [
        lambda p: p.approve(reason="ok-ish"),
        lambda p: p.request_changes(reason="ok"),
        lambda p: p.approve(verdict="not-required", reason="ok"),
        lambda p: p.hold("fetch-failed"),
        lambda p: p.pending("pending-stuck"),
        lambda p: p.pending("tier-below-medium"),
        lambda p: p.approve(verdict="skipped-held", status=None, reason="ok", record=None),
        lambda p: p.approve(verdict="skipped-held", status="final", reason="held-label",
                            record=None),
        lambda p: p.pending("fetch-failed", status="final"),
        lambda p: p.hold("unparseable", status=None),
    ],
)  # fmt: skip
def test_ph18_reason_and_status_must_agree_with_the_verdict(phase, capsys, result_of):
    _, line, _ = phase.ingest(capsys, result_of(phase))
    assert line["reason"] == "invalid-line"


# =============================================================================
# T-PH-19, 21, 22: synthetic strikes, runner results the phase strikes, held results
# =============================================================================


@pytest.mark.parametrize("reason", ["untrusted-checkout", "runner-unbounded"])
def test_ph19_a_phase_synthesized_strike_counts_to_a_hold(phase, capsys, reason):
    steps = []
    for _ in range(3):
        action, line = phase.synthetic(capsys, reason)
        steps.append((action, line["verdict"], line["reason"], line["count"], line["last_reason"]))
    assert steps == [
        (("none", "0"), "pending", reason, 1, reason),
        (("none", "0"), "pending", reason, 2, reason),
        (("label", "0"), "hold", "pending-stuck", 3, reason),
    ]
    rendered = phase.osr_line(capsys)
    assert "verdict=hold reason=pending-stuck" in rendered
    assert f"persisted=false count=3 last_reason={reason} label=-" in rendered
    assert "head=- base=- tier=- vendors=-" in rendered


def test_ph19_a_synthesized_hold_labels_immediately(phase, capsys):
    for reason in ("config-error", "phase-error"):
        action, line = phase.synthetic(capsys, reason)
        assert action == ("label", "0")
        assert (line["verdict"], line["reason"], line["persisted"]) == ("hold", reason, False)
        assert not phase.strike_file().exists()


def test_ph19_ingest_without_a_runner_result_or_a_synthetic_reason_is_a_usage_error(phase):
    with pytest.raises(SystemExit) as info:
        ph.main(
            [
                "ingest",
                "--state-dir",
                str(phase.state),
                "--pr",
                "7",
                "--scratch",
                str(phase.scratch),
            ]
        )
    assert info.value.code == 2


@pytest.mark.parametrize(
    "reason",
    ["lock-busy", "state-write-failed", "config-error", "github-error", "untrusted-checkout"],
)
def test_ph21_an_uncounted_pending_the_runner_returns_is_struck_by_the_phase(phase, capsys, reason):
    result = phase.pending(reason)
    steps = [phase.ingest(capsys, result) for _ in range(3)]
    assert [(a, ln["verdict"], ln["reason"], ln["count"]) for (a, ln, _) in steps] == [
        (("none", "1"), "pending", reason, 1),
        (("none", "1"), "pending", reason, 2),
        (("label", "1"), "hold", "pending-stuck", 3),
    ]
    assert steps[2][1]["last_reason"] == reason
    rendered = phase.osr_line(capsys)
    assert "verdict=hold reason=pending-stuck" in rendered
    assert f"persisted=false count=3 last_reason={reason}" in rendered
    # The struck line still names the head the runner reported.
    assert f"head={HEAD} base={BASE} tier=MEDIUM vendors=agy" in rendered


@pytest.mark.parametrize("reason", sorted(ph.PENDING_COUNTED))
def test_ph21_a_counted_pending_with_a_null_counter_is_struck_by_the_phase(phase, capsys, reason):
    result = phase.pending(reason, pending_count=None, pending_last_reason=None)
    steps = [phase.ingest(capsys, result) for _ in range(3)]
    assert [ln["reason"] for (_, ln, _) in steps] == [reason, reason, "pending-stuck"]
    assert steps[2][0][0] == "label" and steps[2][1]["last_reason"] == reason


def test_ph21_a_counted_pending_with_a_count_is_never_struck_by_the_phase(phase, capsys):
    result = phase.pending("fetch-failed", pending_count=2, pending_last_reason="fetch-failed")
    for _ in range(4):
        action, line, _ = phase.ingest(capsys, result)
        assert action[0] == "none" and line["verdict"] == "pending" and line["count"] == 2
    assert not phase.strike_file().exists()


def test_ph21_a_runner_pending_stuck_hold_is_labelled(phase, capsys):
    result = phase.hold(
        "pending-stuck", pending_count=3, pending_last_reason="fetch-failed", reused=False
    )
    action, _, _ = phase.ingest(capsys, result)
    assert action[0] == "label"


def test_ph22_the_runner_skipped_held_result_is_no_strike_and_no_label(phase, capsys):
    phase.ingest(capsys, b"", rc=1)
    before = phase.strike_file().read_bytes()
    result = phase.approve(
        verdict="skipped-held",
        status=None,
        reason="held-label",
        record=None,
        tier=None,
        vendors=None,
    )
    action, line, _ = phase.ingest(capsys, result)
    assert action == ("none", "0")
    assert (line["verdict"], line["persisted"], line["label"]) == ("skipped-held", None, None)
    assert phase.strike_file().read_bytes() == before
    rendered = phase.osr_line(capsys)
    assert "verdict=skipped-held reason=held-label" in rendered
    assert "persisted=- count=- last_reason=- label=-" in rendered


def test_ph22_a_reused_hold_on_a_held_pr_renders_label_existing_and_needs_no_call(phase, capsys):
    action, line, _ = phase.ingest(capsys, phase.hold("vendor-error:codex", reused=True), held=1)
    assert action[0] == "none" and line["label"] == "existing"
    assert "verdict=hold reason=vendor-error:codex" in phase.osr_line(capsys)
    assert phase.osr_line(capsys).endswith("label=existing")


# =============================================================================
# T-PH-20: the vocabulary duplicated from the runner
# =============================================================================


def test_ph20_the_helper_vocabulary_equals_the_runners():
    assert ph.HOLD_REASONS == osr.HOLD_REASONS
    assert ph.PENDING_COUNTED == osr.PENDING_COUNTED
    assert ph.PENDING_UNCOUNTED == osr.PENDING_UNCOUNTED
    assert set(ph.VENDORSETS) == set(osr.VENDORSETS) and ph.VENDORSETS == osr.VENDORSETS
    assert ph.TIERS == osr.TIERS
    assert ph.RESULT_KEYS == osr.RESULT_KEYS
    assert ph.FINAL_REASON_FOR_VERDICT == osr.FINAL_REASON_FOR_VERDICT
    assert ph.STRIKE_LIMIT == osr.PENDING_STUCK_AT
    assert ph.HELD_LABELS == osr.HELD_LABELS
    # The phase strikes exactly the uncounted reasons that are not neutral, and it never
    # counts a reason the runner counts itself.
    assert ph.RUNNER_STRIKE_REASONS | ph.NEUTRAL_REASONS == osr.PENDING_UNCOUNTED
    assert not ph.RUNNER_STRIKE_REASONS & ph.NEUTRAL_REASONS
    assert not ph.RUNNER_STRIKE_REASONS & osr.PENDING_COUNTED
    assert set(ph.FINAL_VERDICTS) | {"hold", "pending", "skipped-held"} == set(ph.VERDICTS)


def test_ph20_every_result_the_runner_can_emit_is_accepted_by_the_helper(phase, capsys):
    """Each result shape the runner itself builds passes the helper's validator."""
    root = phase.second_review.parent.parent.parent  # the clone root of the state tree
    for number, result in enumerate(_runner_results(root), start=100):
        result["pr"] = number
        assert (
            ph.validate_result(
                result, number, str(root / ".claudetmp/overseer-authority/second-review/runs")
            )
            is None
        ), result


def _runner_results(root):
    head, base, other = HEAD, BASE, "5" * 40
    records = root / ".claudetmp" / "overseer-authority" / "second-review" / "records"
    runs = root / ".claudetmp" / "overseer-authority" / "second-review" / "runs"
    common = {"check": "second-review", "schema": 1, "head_sha": head, "base_sha": base,
              "range": f"{base}..{head}", "tier": "MEDIUM", "vendors": "agy", "reused": False,
              "findings_file": None, "record": None, "hold_label_applied": None,
              "pending_count": None, "pending_last_reason": None}  # fmt: skip
    rec = str(records / f"pr100-{head}-agy.json")
    yield {**common, "verdict": "approve", "status": "final", "reason": "ok", "record": rec}
    yield {**common, "verdict": "request_changes", "status": "final", "reason": "findings",
           "record": rec, "findings_file": str(runs / "pr100-1111/findings.json")}  # fmt: skip
    yield {**common, "verdict": "hold", "status": "hold", "reason": "unparseable", "record": rec,
           "hold_label_applied": False}  # fmt: skip
    # TD-2357-S1a 5.7 step 4d: a hold written before the tier was known.
    yield {**common, "verdict": "hold", "status": "hold", "reason": "pending-stuck", "record": rec,
           "hold_label_applied": False, "tier": None, "base_sha": None, "range": None,
           "vendors": "agy+codex", "pending_count": 3, "pending_last_reason": "review-failed"}  # fmt: skip
    # Step 4c: the non-persisted collision hold.
    yield {**common, "verdict": "hold", "status": "hold", "reason": "pending-stuck", "tier": None,
           "vendors": None, "pending_count": 3, "pending_last_reason": "fetch-failed"}  # fmt: skip
    yield {**common, "verdict": "pending", "status": None, "reason": "budget", "base_sha": other,
           "range": f"{other}..{head}"}  # fmt: skip
    yield {**common, "verdict": "skipped-held", "status": None, "reason": "held-label"}


# =============================================================================
# Invocation as bin/hos-cron makes it
# =============================================================================


def test_the_helper_runs_under_python_dash_i_from_any_cwd(tmp_path):
    env = child_env({"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    done = subprocess.run(
        [sys.executable, "-I", str(HELPER), "budget", "--elapsed", "1", "--uncached-ran", "1",
         "--per-pr", "1", "--budget", "100"],
        cwd=tmp_path, capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert (done.returncode, done.stdout.strip()) == (0, "RUN"), done.stderr


def test_the_helper_does_not_import_the_runner_package():
    assert re.search(r"^\s*(from|import) scripts", HELPER.read_text(), re.M) is None


def test_an_unexpected_failure_exits_one_with_a_traceback(phase, capsys):
    code, _, err = phase.run(
        capsys,
        "label-result", "--scratch", phase.root / "absent", "--pr", PR, "--result", "applied",
    )  # fmt: skip
    assert code == 1 and "Traceback" in err


@pytest.mark.parametrize(
    "detail, expected",
    [
        ({"ms": "clean", "d": False, "labels": []}, "0"),
        ({"labels": ["needs-human"]}, "1"),
        ({"labels": ["x", "hos-halt"]}, "1"),
        ({"labels": ["needs-ai", "parked"]}, "0"),
        ({"ms": "unknown", "d": False}, "0"),
        ({"labels": "needs-human"}, "0"),
        ({"labels": [None, 5, {"name": "needs-human"}]}, "0"),
        (["needs-human"], "0"),
    ],
)
def test_held_reads_the_hold_labels_from_the_pr_detail(detail, expected, monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(detail)))
    assert ph.main(["held"]) == 0
    assert capsys.readouterr().out == expected + "\n"


def test_held_treats_unreadable_detail_as_not_held(monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert ph.main(["held"]) == 0
    assert capsys.readouterr().out == "0\n"
