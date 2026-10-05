"""Tests for D2b of scripts/framework/select_work_candidates.py — the native
blocker / parent free filter (#1644 slice T3.0a, ADR-1644 AD-C4, AD-C6).

Covers §7.1 and §7.2 of
docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0a-no-idle-selection.md: the T-NB*
predicate and report tests, the T-EX* contract-preservation tests, the ESC-8
tests T-NS1..T-NS4, and the in-process zero-added-request proofs T-ZC1, T-ZC3
and T-ZC4 (T-ZC2, the PATH-level fake `gh`, lives in
test_select_work_candidates_ghshim.py).

The fixtures below are duplicated from test_select_work_candidates.py rather
than imported: tests/framework is not a package, so a sibling import would
depend on how pytest resolves rootdir.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

import pytest

from scripts.framework import requester_trust as rt
from scripts.framework import select_work_candidates as swc

PREFIX = "select_work_candidates: "

_ZERO_DEPS = {"blocked_by": 0, "blocking": 0, "total_blocked_by": 0, "total_blocking": 0}
_ZERO_SUBS = {"total": 0, "completed": 0, "percent_completed": 0}
_BLOCKED = {"blocked_by": 1, "blocking": 0, "total_blocked_by": 1, "total_blocking": 0}
_CLOSED_BLOCKER = {"blocked_by": 0, "blocking": 0, "total_blocked_by": 1, "total_blocking": 0}
_OMIT = object()  # sentinel: drop the summary key entirely

_BOT = {"user": "outside-contributor", "user_type": "User"}


# ---------------------------------------------------------------------------
# Fixtures and helpers (duplicated, see the module docstring)
# ---------------------------------------------------------------------------


@pytest.fixture
def gate_repo(tmp_path, monkeypatch):
    root = tmp_path
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text("* @ScottThurlow\n")
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True)
    (fw / "machine-accounts.env").write_text(
        'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\n'
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
        'BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"\n'
        'COPILOT_BOT_LOGIN="copilot[bot]"\n'
    )
    monkeypatch.setattr(swc, "_REPO_ROOT", root)
    return root


def _issue(
    number: int,
    *labels: str,
    user: str = "ScottThurlow",
    user_type: str = "User",
    deps: Optional[dict] = _ZERO_DEPS,
    subs: Optional[dict] = _ZERO_SUBS,
) -> dict:
    record = {
        "number": number,
        "title": f"issue {number}",
        "labels": [{"name": n} for n in ["needs-ai", *labels]],
        "user": {"login": user, "type": user_type},
        "pull_request": None,
    }
    if deps is not _OMIT:
        record["issue_dependencies_summary"] = deps
    if subs is not _OMIT:
        record["sub_issues_summary"] = subs
    return record


def _labeled_event(actor: str) -> dict:
    return {
        "event": "labeled",
        "label": {"name": "needs-ai"},
        "actor": {"login": actor, "type": "User"},
    }


class GhStub:
    def __init__(self):
        self.calls: list[str] = []
        self.issue_pages: dict[int, list] = {}
        self.events_pages: dict[int, dict[int, list]] = {}
        self.events_fail_pages: dict[int, set[int]] = {}

    def __call__(self, endpoint: str):
        self.calls.append(endpoint)
        m = re.search(r"issues/(\d+)/events\?.*page=(\d+)", endpoint)
        if m:
            issue_num, page = int(m.group(1)), int(m.group(2))
            if page in self.events_fail_pages.get(issue_num, set()):
                raise swc._GhFailure("simulated transport failure")
            return self.events_pages.get(issue_num, {}).get(page, [])
        m = re.search(r"/issues\?.*page=(\d+)", endpoint)
        if m:
            return self.issue_pages.get(int(m.group(1)), [])
        raise AssertionError(f"GhStub: unrecognised endpoint {endpoint!r}")


@pytest.fixture
def stub(monkeypatch):
    s = GhStub()
    monkeypatch.setattr(swc, "_run_gh", s)
    # No fixture here lists a tier, so `fetch_collaborators` must never run;
    # fail loudly rather than fall through to a real `gh` subprocess.
    monkeypatch.setattr(
        rt,
        "_run_gh_get",
        lambda endpoint: (_ for _ in ()).throw(AssertionError(f"unexpected {endpoint!r}")),
    )
    return s


def _numbers(lines: list[str]) -> list[int]:
    return [int(ln.split()[0].lstrip("#")) for ln in lines]


def run_gate(capsys, *args: str) -> tuple[int, list[str], list[str]]:
    rc = swc.main(["--repo", "owner/repo", "--milestone", "5", *args])
    captured = capsys.readouterr()
    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    return rc, out_lines, err_lines


def _fields(err: list[str]) -> dict:
    """Integer `key=value` fields of the UNEVALUATED and summary lines only."""
    fields: dict = {}
    for ln in err:
        if ln.startswith(PREFIX + "UNEVALUATED") or ln.startswith(PREFIX + "repo="):
            fields.update({k: int(v) for k, v in re.findall(r"([\w:-]+)=(\d+)", ln)})
    return fields


def _pr_records(count: int) -> list[dict]:
    return [
        {
            "number": 9000 + i,
            "title": "pr",
            "labels": [],
            "pull_request": {"url": "x"},
            "issue_dependencies_summary": None,
            "sub_issues_summary": None,
            "user": {"login": "ScottThurlow", "type": "User"},
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# T-NB: the predicate and its report
# ---------------------------------------------------------------------------


class TestNativeExclusion:
    def test_nb1_open_blocker_is_excluded_and_reported(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(10, deps=_BLOCKED), _issue(11)]
        rc, out, err = run_gate(capsys)
        assert rc == 0
        assert _numbers(out) == [11]
        assert (
            PREFIX + "EXCLUDED 1 in-milestone issues are not actionable (not counted in scanned): "
            "blocked-by-open-issue=1 blocker-closed-unverified=0 untracked-parent=0"
        ) in err
        assert PREFIX + "EXCLUDED issues: #10(blocked-by-open-issue)" in err
        joined = " ".join(err)
        assert "complete=yes" in joined
        assert "scanned=1 " in joined

    def test_nb2_closed_blocker_is_excluded_as_unverified(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err
        assert (
            PREFIX + "WARN blocker-closed-unverified issue=#20 — a closed blocker does not "
            "unblock until the T3.3 satisfaction check exists; a CODEOWNER may remove the "
            "dependency edge if the blocker is satisfied"
        ) in err

    @pytest.mark.parametrize(
        "malformed",
        [
            pytest.param(_OMIT, id="absent"),
            pytest.param(None, id="none"),
            pytest.param([], id="list"),
            pytest.param("x", id="string"),
        ],
    )
    @pytest.mark.parametrize("limb", ["dependencies", "sub-issues"])
    def test_nb3_unreadable_summary_is_unevaluated_not_clear(
        self, gate_repo, stub, capsys, limb, malformed
    ):
        self._assert_unreadable(stub, capsys, limb, malformed)

    @pytest.mark.parametrize(
        ("limb", "malformed"),
        [
            ("dependencies", {"blocked_by": 0, "blocking": 0, "total_blocking": 0}),
            ("dependencies", {**_ZERO_DEPS, "blocked_by": True}),
            ("dependencies", {**_ZERO_DEPS, "total_blocked_by": True}),
            ("dependencies", {**_ZERO_DEPS, "blocked_by": -1}),
            ("dependencies", {**_ZERO_DEPS, "total_blocked_by": 1.0}),
            ("dependencies", {**_ZERO_DEPS, "blocked_by": 2, "total_blocked_by": 1}),
            ("sub-issues", {"completed": 0, "percent_completed": 0}),
            ("sub-issues", {**_ZERO_SUBS, "total": True}),
            ("sub-issues", {**_ZERO_SUBS, "total": -1}),
            ("sub-issues", {**_ZERO_SUBS, "total": 0.0}),
        ],
    )
    def test_nb3_malformed_field_is_unevaluated_not_clear(
        self, gate_repo, stub, capsys, limb, malformed
    ):
        self._assert_unreadable(stub, capsys, limb, malformed)

    @staticmethod
    def _assert_unreadable(stub, capsys, limb, malformed):
        kwargs = {"deps": malformed} if limb == "dependencies" else {"subs": malformed}
        stub.issue_pages[1] = [_issue(5, **kwargs), _issue(99)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [99]
        assert rc == 0
        assert _fields(err)["unevaluated:edge-summary-unreadable"] == 1
        assert PREFIX + f"WARN unevaluated:edge-summary-unreadable issue=#5 limb={limb}" in err
        assert "complete=no" in " ".join(err)

    def test_nb3_both_limbs_unreadable_names_both(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(5, deps=_OMIT, subs=None), _issue(99)]
        rc, out, err = run_gate(capsys)
        assert PREFIX + "WARN unevaluated:edge-summary-unreadable issue=#5 limb=both" in err

    def test_nb4_only_record_unreadable_is_degraded_not_no_work(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1, deps=_OMIT)]
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 3
        fields = _fields(err)
        assert fields["unevaluated"] == 1
        assert fields["unevaluated:edge-summary-unreadable"] == 1
        assert "complete=no" in " ".join(err)
        assert any(
            ln.startswith(PREFIX + "WARN edge-summary-unreadable-on-every-record n=1") for ln in err
        )

    def test_nb5_unreadable_critical_does_not_block_a_clear_low(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(30, "priority:critical", deps=_OMIT), _issue(31)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [31]
        assert rc == 0
        assert "complete=no" in " ".join(err)
        assert (
            PREFIX + "WARN unevaluated:edge-summary-unreadable issue=#30 limb=dependencies" in err
        )
        assert not any(
            ln.startswith(PREFIX + "WARN edge-summary-unreadable-on-every") for ln in err
        )

    def test_nb6_parent_is_excluded_open_or_closed_children(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(40, subs={"total": 2, "completed": 0, "percent_completed": 0}),
            _issue(41, subs={"total": 1, "completed": 1, "percent_completed": 100}),
            _issue(42),
        ]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [42]
        assert PREFIX + "EXCLUDED issues: #40(untracked-parent) #41(untracked-parent)" in err

    def test_nb7_graph_contradiction_is_reported_as_blocked_and_stage_labels_are_inert(
        self, gate_repo, stub, capsys
    ):
        """#50 (`stage:code` while blocked) is reported under the blocker
        reason only; no stage token exists in T3.0a. The #51 limb pins T3.0a's
        SCOPE BOUNDARY, not an ADR property: a `stage:tracking` issue is emitted
        here because stage labels are inert until T3.2, which inverts this
        (`stage:tracking` then means excluded with `tracking-parent`, AD-C4)."""
        stub.issue_pages[1] = [
            _issue(50, "stage:code", deps=_BLOCKED),
            _issue(51, "stage:tracking"),
        ]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [51]
        assert PREFIX + "EXCLUDED issues: #50(blocked-by-open-issue)" in err
        joined = " ".join(err)
        assert "stage-malformed" not in joined
        assert "tracking-parent" not in joined

    def test_nb8_exclusion_runs_before_ranking(self, gate_repo, stub, capsys, monkeypatch):
        seen = []
        original = swc._rank

        def _spy(record):
            seen.append(record.get("number"))
            return original(record)

        monkeypatch.setattr(swc, "_rank", _spy)
        stub.issue_pages[1] = [
            _issue(60, "priority:critical", deps=_BLOCKED),
            _issue(61, "priority:critical", subs={"total": 1}),
            _issue(62, "priority:critical", deps=_OMIT),
            _issue(63, "priority:critical"),
        ]
        run_gate(capsys)
        assert seen == [63]

    def test_nb9_exclusion_wins_over_an_unreadable_limb(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(70, deps=_OMIT, subs={"total": 1})]
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 0
        assert PREFIX + "EXCLUDED issues: #70(untracked-parent)" in err
        assert "complete=yes" in " ".join(err)
        assert "unevaluated:edge-summary-unreadable" not in " ".join(err)

    @pytest.mark.parametrize(
        ("blocked", "total"), [(b, t) for t in range(0, 4) for b in range(0, t + 1)]
    )
    def test_nb10_excluded_iff_any_blocking_edge_whichever_count_means_open(self, blocked, total):
        verdict = swc._native_verdict(
            {
                "issue_dependencies_summary": {"blocked_by": blocked, "total_blocked_by": total},
                "sub_issues_summary": {"total": 0},
            }
        )
        assert (verdict.outcome == "excluded") == (total > 0)
        if total > 0:
            expected = "blocked-by-open-issue" if blocked > 0 else "blocker-closed-unverified"
            assert verdict.reason == expected

    def test_nb11_pr_records_with_null_summaries_are_not_misread(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [*_pr_records(2), _issue(1)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [1]
        joined = " ".join(err)
        assert "complete=yes" in joined
        assert "unevaluated=0" in joined
        assert not any("WARN" in ln for ln in err)

    def test_nb12_needs_human_wins_over_an_unreadable_summary(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(80, "needs-human", deps=_OMIT)]
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 0
        joined = " ".join(err)
        assert "complete=yes" in joined
        assert "EXCLUDED" not in joined
        assert "edge-summary-unreadable" not in joined

    def test_nb13_the_predicate_reads_only_the_two_summaries(self):
        class _Hostile(dict):
            def get(self, key, default=None):
                if key == "issue_dependencies_summary":
                    return _ZERO_DEPS
                if key == "sub_issues_summary":
                    return _ZERO_SUBS
                raise AssertionError(f"_native_verdict touched {key!r}")

            def __getitem__(self, key):
                raise AssertionError(f"_native_verdict indexed {key!r}")

        assert swc._native_verdict(_Hostile()) == swc._NativeVerdict("clear", "")


# ---------------------------------------------------------------------------
# T-EX: the S2 report / exit contract is preserved
# ---------------------------------------------------------------------------


class TestContractPreserved:
    def test_ex1_stdout_and_summary_shape_are_unchanged(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(10, deps=_BLOCKED), _issue(11)]
        rc, out, err = run_gate(capsys)
        assert out
        assert all(re.match(r"^#\d+ \[(critical|high|medium|low)\] ", ln) for ln in out)
        summary = err[-1]
        assert summary.startswith(PREFIX + "repo=")
        keys = [tok.split("=")[0] for tok in summary[len(PREFIX) :].split()]
        assert keys == [
            "repo",
            "milestone",
            "scanned",
            "evaluated",
            "eligible",
            "authorized",
            "gated",
            "unevaluated",
            "api_requests",
            "complete",
        ]

    def test_ex2_excluded_records_are_not_counted_as_gated(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(90, user=_BOT["user"], user_type=_BOT["user_type"]),
            _issue(91, deps=_BLOCKED),
        ]
        stub.events_pages[90] = {1: []}
        rc, out, err = run_gate(capsys)
        assert out == []
        assert (
            PREFIX
            + "ALL-CANDIDATES-GATED 1 of 1 in-milestone issues are held for human authorization"
            in err
        )
        assert PREFIX + "ALL-CANDIDATES-GATED reasons: no-codeowner-actor=1" in err
        gated_lines = [ln for ln in err if "ALL-CANDIDATES-GATED" in ln]
        assert not any("#91" in ln for ln in gated_lines)
        assert PREFIX + "EXCLUDED issues: #91(blocked-by-open-issue)" in err

    def test_ex3_all_excluded_is_a_complete_empty_determination(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(1, deps=_BLOCKED),
            _issue(2, subs={"total": 3}),
            _issue(3, deps=_CLOSED_BLOCKER),
        ]
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 0
        joined = " ".join(err)
        assert "complete=yes" in joined
        assert "scanned=0 " in joined
        assert "ALL-CANDIDATES-GATED" not in joined

    def test_ex4_counting_identities_hold_on_a_mixed_run(self, gate_repo, stub, capsys):
        """506 query-failed, 505 gated, 504/503 eligible, then the sufficiency
        stop leaves 502/501 unevaluated; 600 is unreadable, 601 excluded."""
        stub.issue_pages[1] = [
            _issue(506, user=_BOT["user"], user_type=_BOT["user_type"]),
            _issue(505, user=_BOT["user"], user_type=_BOT["user_type"]),
            _issue(504),
            _issue(503),
            _issue(502),
            _issue(501),
            _issue(600, deps=_OMIT),
            _issue(601, deps=_BLOCKED),
        ]
        stub.events_fail_pages[506] = {1}
        rc, out, err = run_gate(capsys, "--max-candidates", "2")
        f = _fields(err)
        assert f["scanned"] == 7
        assert f["scanned"] == f["evaluated"] + f["unevaluated"]
        assert f["evaluated"] == f["eligible"] + f["gated"]
        assert f["unevaluated"] == (
            f["unevaluated:sufficient"]
            + f["unevaluated:cost-ceiling"]
            + f["unevaluated:query-failed"]
            + f["unevaluated:edge-summary-unreadable"]
        )
        assert (f["unevaluated:sufficient"], f["unevaluated:query-failed"]) == (2, 1)
        assert f["unevaluated:edge-summary-unreadable"] == 1
        assert (f["eligible"], f["gated"]) == (2, 1)

    def test_ex7_stderr_lines_follow_the_td_3_2_emission_order(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(1),
            _issue(2, deps=_OMIT),
            _issue(3, deps=_BLOCKED),
            _issue(4, deps=_CLOSED_BLOCKER),
        ]
        rc, out, err = run_gate(capsys)

        def index(prefix: str) -> int:
            return next(i for i, ln in enumerate(err) if ln.startswith(PREFIX + prefix))

        order = [
            index("UNEVALUATED"),
            index("WARN unevaluated:edge-summary-unreadable issue=#2"),
            index("EXCLUDED 2 in-milestone"),
            index("EXCLUDED issues:"),
            index("WARN blocker-closed-unverified issue=#4"),
            index("repo="),
        ]
        assert order == sorted(order)
        assert len(set(order)) == len(order)

    def test_ex5_refused_list_page_does_not_double_count(self, gate_repo, stub, capsys):
        """A full page 1 with the ceiling at 1 refuses page 2. D2b still ran
        (it is free): only `kept` records are cost-ceiling."""
        page = [
            _issue(1),
            _issue(2),
            _issue(3),
            _issue(4, deps=_OMIT),
            _issue(5, subs=None),
            _issue(6, deps=_BLOCKED),
        ]
        stub.issue_pages[1] = page + _pr_records(100 - len(page))
        rc, out, err = run_gate(capsys, "--max-api-requests", "1")
        assert out == []
        assert rc == 3
        f = _fields(err)
        assert f["unevaluated:cost-ceiling"] == 3
        assert f["unevaluated:edge-summary-unreadable"] == 2
        assert f["scanned"] == 5
        assert f["scanned"] == f["evaluated"] + f["unevaluated"]
        assert f["unevaluated"] == 5
        assert PREFIX + "EXCLUDED issues: #6(blocked-by-open-issue)" in err
        assert f["api_requests"] == 1

    def test_ex6_unreadable_warns_are_capped_at_twenty(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(100 + i, deps=_OMIT) for i in range(25)]
        rc, out, err = run_gate(capsys)
        assert rc == 3
        per_record = [
            ln
            for ln in err
            if ln.startswith(PREFIX + "WARN unevaluated:edge-summary-unreadable issue=#")
        ]
        assert len(per_record) == 20
        assert PREFIX + "WARN unevaluated:edge-summary-unreadable (+5 more)" in err
        assert any(
            ln.startswith(PREFIX + "WARN edge-summary-unreadable-on-every-record n=25")
            for ln in err
        )


# ---------------------------------------------------------------------------
# T-NS: the ESC-8 tests (ADR-1644 AD-C6, Erratum 1)
# ---------------------------------------------------------------------------


class TestNoIdleSelection:
    def test_ns1_a_human_blocked_or_blocked_critical_never_beats_a_free_low(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [
            _issue(1, "priority:critical", "stage:architecture", "needs-human"),
            _issue(2, "priority:critical", "stage:code", deps=_BLOCKED),
            _issue(3, "priority:low"),
        ]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [3]
        assert PREFIX + "EXCLUDED issues: #2(blocked-by-open-issue)" in err

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="in-flight ordering is T3.2's gate (ADR-1644 Erratum 1, E1)",
    )
    def test_ns2_in_flight_low_beats_a_new_critical(self, gate_repo, stub, capsys):
        """Needs the stage parse and in-flight ordering, which are T3.2's.
        `raises=AssertionError` keeps a fixture or harness error from counting
        as the expected failure."""
        stub.issue_pages[1] = [
            _issue(10, "priority:low", "stage:design"),
            _issue(11, "priority:critical"),
        ]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [10, 11]

    def test_ns3a_exclusion_precedes_the_sufficiency_cut(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            *[_issue(200 + i, "priority:critical", "needs-human") for i in range(3)],
            *[_issue(210 + i, "priority:critical", deps=_BLOCKED) for i in range(3)],
            _issue(300, "priority:low"),
        ]
        rc, out, err = run_gate(capsys, "--max-candidates", "5")
        assert _numbers(out) == [300]
        joined = " ".join(err)
        assert "unevaluated=0" in joined
        assert not re.search(r"unevaluated:sufficient=[1-9]", joined)

    def test_ns3b_exclusion_precedes_the_paid_walk(self, gate_repo, stub, capsys):
        """Fails if exclusion ever moves after D5: the six untrusted blocked
        records must cost zero `/events` requests."""
        stub.issue_pages[1] = [
            *[
                _issue(
                    200 + i,
                    "priority:critical",
                    "needs-human",
                    user=_BOT["user"],
                    user_type=_BOT["user_type"],
                )
                for i in range(3)
            ],
            *[
                _issue(
                    210 + i,
                    "priority:critical",
                    deps=_BLOCKED,
                    user=_BOT["user"],
                    user_type=_BOT["user_type"],
                )
                for i in range(3)
            ],
            _issue(300, "priority:low"),
        ]
        rc, out, err = run_gate(capsys, "--max-candidates", "5")
        assert _numbers(out) == [300]
        assert not any("/events" in c for c in stub.calls)

    @staticmethod
    def _replay(carrier: bool) -> list:
        return [
            _issue(
                1643,
                "priority:critical",
                "bug",
                "process-gap",
                *(["needs-human"] if carrier else []),
            ),
            _issue(
                1644,
                "priority:high",
                "enhancement",
                "process-gap",
                deps=_BLOCKED if carrier else _ZERO_DEPS,
            ),
            _issue(1700, "priority:high"),
            _issue(1701, "priority:medium"),
            _issue(1702, "priority:low"),
        ]

    def test_ns4a_replay_of_2026_09_30_with_a_carrier_selects_real_work(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = self._replay(carrier=True)
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [1700, 1701, 1702]
        assert out[0].startswith("#1700")

    def test_ns4b_a_prose_only_wait_is_invisible_to_the_selector(self, gate_repo, stub, capsys):
        """Negative control, and it pins the H5 limit: with NO carrier on
        #1643/#1644 (their live state) the selector cannot see that they wait
        on a human, so #1643 is selected first. This is why
        `escalate_to_human.sh` exists; do not read T-NS4a as covering prose."""
        stub.issue_pages[1] = self._replay(carrier=False)
        rc, out, err = run_gate(capsys)
        assert out[0].startswith("#1643")


# ---------------------------------------------------------------------------
# T-ZC: zero added requests (in-process; T-ZC2 is in the ghshim module)
# ---------------------------------------------------------------------------

_LIST_P1 = "repos/owner/repo/issues?state=open&milestone=5&labels=needs-ai&per_page=100&page=1"


def _f0(stub, *, blocked_5: bool = False, parent_4: bool = False) -> None:
    """Fixture F0: #1-#3 trusted, #4 untrusted and authorized, #5 untrusted
    and gated. Walk order is (rank, number DESC), so #5 is walked before #4."""
    stub.issue_pages[1] = [
        _issue(1),
        _issue(2),
        _issue(3),
        _issue(
            4,
            subs={"total": 1} if parent_4 else _ZERO_SUBS,
            user=_BOT["user"],
            user_type=_BOT["user_type"],
        ),
        _issue(
            5,
            deps=_BLOCKED if blocked_5 else _ZERO_DEPS,
            user=_BOT["user"],
            user_type=_BOT["user_type"],
        ),
    ]
    stub.events_pages[4] = {1: [_labeled_event("ScottThurlow")]}
    stub.events_pages[5] = {1: []}


class TestZeroAddedRequests:
    def test_zc1_golden_calls_and_differential_against_pre_t3_0a_behavior(
        self, gate_repo, stub, capsys, monkeypatch
    ):
        _f0(stub)
        rc, out, err = run_gate(capsys)
        golden = [
            _LIST_P1,
            "repos/owner/repo/issues/5/events?per_page=100&page=1",
            "repos/owner/repo/issues/4/events?per_page=100&page=1",
        ]
        assert stub.calls == golden
        assert _fields(err)["api_requests"] == 3

        stub.calls.clear()
        monkeypatch.setattr(swc, "_native_verdict", lambda r: swc._NativeVerdict("clear", ""))
        run_gate(capsys)
        assert stub.calls == golden

    def test_zc3_exclusion_only_removes_requests(self, gate_repo, stub, capsys):
        _f0(stub, blocked_5=True, parent_4=True)
        rc, out, err = run_gate(capsys)
        assert stub.calls == [_LIST_P1]
        assert _fields(err)["api_requests"] == 1
        assert _numbers(out) == [1, 2, 3]

    def test_zc4_no_new_request_path_exists_in_the_module(self):
        path = Path(swc.__file__)
        tree = ast.parse(path.read_text())

        forbidden = ("/dependencies", "/sub_issues", "/timeline", "parent_issue", "graphql")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for needle in forbidden:
                    assert needle not in node.value, (needle, node.value[:60])

        functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        run_gh = functions["_run_gh"]
        span = range(run_gh.lineno, run_gh.end_lineno + 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "subprocess":
                assert node.lineno in span, f"subprocess referenced outside _run_gh: {node.lineno}"

        for name in ("_native_verdict", "_dependency_counts", "_sub_issue_total"):
            for node in ast.walk(functions[name]):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    assert func.id not in {"_run_gh", "_fetch_pages"}, name
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    assert func.value.id != "subprocess", name

        banned = {
            "urllib.request",
            "http.client",
            "http",
            "requests",
            "socket",
            "scripts.automation.lib.github",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
        assert not (imported & banned), imported & banned
