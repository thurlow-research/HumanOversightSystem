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

_OUTSIDER = {"user": "outside-contributor", "user_type": "User"}


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
    # The throwaway tree is not a git repo; pin the started signal to "none started".
    monkeypatch.setattr(swc, "_started_stages", lambda *_a, **_k: {})
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


def _blocker(number: int, reason: Optional[str] = "completed", state: str = "closed") -> dict:
    return {
        "number": number,
        "repository_url": "https://api.github.com/repos/owner/repo",
        "state": state,
        "state_reason": reason,
    }


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
        self.blockers: dict[int, list] = {}  # dependent number -> blocker issue objects
        self.blockers_fail: set[int] = set()

    def __call__(self, endpoint: str):
        self.calls.append(endpoint)
        m = re.search(r"issues/(\d+)/dependencies/blocked_by\?.*page=(\d+)", endpoint)
        if m:
            dependent = int(m.group(1))
            if dependent in self.blockers_fail:
                raise swc._GhFailure("simulated transport failure")
            return self.blockers.get(dependent, []) if int(m.group(2)) == 1 else []
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

    def test_nb2_unsatisfied_closed_blocker_is_excluded_as_unverified(
        self, gate_repo, stub, capsys
    ):
        """#2173: was 'a closed blocker is always excluded'; now it is excluded
        only when the paid satisfaction check fails (here: not_planned)."""
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21)]
        stub.blockers[20] = [_blocker(900, "not_planned")]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err
        assert (
            PREFIX + "WARN blocker-closed-unverified issue=#20 — no closed blocker is "
            "satisfied by a merge to the default branch or a CODEOWNER close; a CODEOWNER "
            "may remove the dependency edge if the blocker is satisfied"
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
    def test_nb10_open_blocker_is_final_closed_only_owes_the_paid_check(self, blocked, total):
        verdict = swc._native_verdict(
            {
                "issue_dependencies_summary": {"blocked_by": blocked, "total_blocked_by": total},
                "sub_issues_summary": {"total": 0},
            }
        )
        if blocked > 0:
            assert verdict == swc._NativeVerdict("excluded", "blocked-by-open-issue")
        elif total > 0:
            assert verdict == swc._NativeVerdict("check", "blocker-closed-unverified")
        else:
            assert verdict == swc._NativeVerdict("clear", "")

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

    def test_pk1_parked_is_excluded_and_reported_with_its_own_reason(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(70, "parked"), _issue(71)]
        rc, out, err = run_gate(capsys)
        assert rc == 0
        assert _numbers(out) == [71]
        assert (
            PREFIX + "EXCLUDED 1 in-milestone issues are not actionable (not counted in scanned): "
            "blocked-by-open-issue=0 blocker-closed-unverified=0 untracked-parent=0 parked=1"
        ) in err
        assert PREFIX + "EXCLUDED issues: #70(parked)" in err
        assert "scanned=1 " in " ".join(err)

    def test_pk2_parked_wins_over_a_native_reason(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(72, "parked", deps=_BLOCKED)]
        rc, out, err = run_gate(capsys)
        assert PREFIX + "EXCLUDED issues: #72(parked)" in err

    def test_pk3_needs_human_wins_over_parked_silently(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(73, "needs-human", "parked")]
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 0
        assert "EXCLUDED" not in " ".join(err)

    def test_pk4_parked_does_not_change_completeness_or_exit_code(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(74)]
        rc_without, out_without, err_without = run_gate(capsys)
        stub.issue_pages[1] = [_issue(74), _issue(75, "parked")]
        rc_with, out_with, err_with = run_gate(capsys)
        assert (rc_with, out_with) == (rc_without, out_without)
        assert "complete=yes" in " ".join(err_with)
        assert "unevaluated=0" in " ".join(err_with)

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
            _issue(90, user=_OUTSIDER["user"], user_type=_OUTSIDER["user_type"]),
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
        stub.blockers[3] = [_blocker(900, "not_planned")]
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
            _issue(506, user=_OUTSIDER["user"], user_type=_OUTSIDER["user_type"]),
            _issue(505, user=_OUTSIDER["user"], user_type=_OUTSIDER["user_type"]),
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
        stub.blockers[4] = [_blocker(900, "not_planned")]
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
                    user=_OUTSIDER["user"],
                    user_type=_OUTSIDER["user_type"],
                )
                for i in range(3)
            ],
            *[
                _issue(
                    210 + i,
                    "priority:critical",
                    deps=_BLOCKED,
                    user=_OUTSIDER["user"],
                    user_type=_OUTSIDER["user_type"],
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
            user=_OUTSIDER["user"],
            user_type=_OUTSIDER["user_type"],
        ),
        _issue(
            5,
            deps=_BLOCKED if blocked_5 else _ZERO_DEPS,
            user=_OUTSIDER["user"],
            user_type=_OUTSIDER["user_type"],
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

        forbidden = ("/sub_issues", "/timeline", "parent_issue", "graphql")
        functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        # #2173 ruling: `_run_graphql` is the ONE sanctioned GraphQL transport (the
        # closer lookup); the word "graphql" may appear nowhere outside it.
        gql_fn = functions["_run_graphql"]
        gql_span = range(gql_fn.lineno, gql_fn.end_lineno + 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for needle in forbidden:
                    if needle == "graphql" and node.lineno in gql_span:
                        continue
                    assert needle not in node.value, (needle, node.value[:60])
                # #2173: the closed-blocker check is the ONE sanctioned dependencies read.
                if "/dependencies" in node.value:
                    assert "/dependencies/blocked_by?" in node.value, node.value[:60]

        run_gh = functions["_run_gh"]
        # `_git` (#2155's started signal) shells out to LOCAL git only -- zero
        # API requests -- so it is the one other sanctioned subprocess site.
        git_fn = functions["_git"]
        span = [
            *range(run_gh.lineno, run_gh.end_lineno + 1),
            *range(git_fn.lineno, git_fn.end_lineno + 1),
            *gql_span,
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "subprocess":
                assert (
                    node.lineno in span
                ), f"subprocess referenced outside _run_gh/_git/_run_graphql: {node.lineno}"

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


# ---------------------------------------------------------------------------
# T-CB: the paid closed-blocker satisfaction check (#2173, thin T3.3)
# ---------------------------------------------------------------------------

_MERGE_SHA = "7ada70a3ee" + "0" * 30
_T_CLOSE = "2026-10-25T23:43:49Z"
_CODEOWNER = {"login": "ScottThurlow", "type": "User"}
_BOT = {"login": "hos-worker-hos[bot]", "type": "Bot"}


def _closed_event(actor=_CODEOWNER, commit_id=None, at=_T_CLOSE) -> dict:
    return {"event": "closed", "actor": actor, "commit_id": commit_id, "created_at": at}


def _referenced_event(commit_id=_MERGE_SHA, at=_T_CLOSE) -> dict:
    return {"event": "referenced", "actor": _BOT, "commit_id": commit_id, "created_at": at}


def _always(_sha) -> bool:
    return True


def _never(_sha) -> bool:
    return False


def _pr_closer(
    merged=True, base="main", repo="owner/repo", sha=_MERGE_SHA, typename="PullRequest"
) -> dict:
    return {
        "__typename": typename,
        "number": 7,
        "merged": merged,
        "mergedAt": "2026-10-25T23:43:46Z",
        "baseRefName": base,
        "baseRepository": {"nameWithOwner": repo},
        "mergeCommit": {"oid": sha},
    }


def _node(closer, at=_T_CLOSE) -> dict:
    return {"createdAt": at, "stateReason": "COMPLETED", "closer": closer}


class _Lookup:
    """A fake closer lookup recording how often the predicate called it."""

    def __init__(self, node):
        self.node = node
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.node


CODEOWNERS = {"scottthurlow"}
BOTS = {"hos-worker-hos[bot]"}
REPO = "owner/repo"


def _satisfied(events, is_ancestor, lookup):
    return swc.blocker_closure_satisfied(events, CODEOWNERS, BOTS, is_ancestor, lookup, REPO)


class TestSatisfactionPredicate:
    def test_bot_merged_pr_closer_is_merge(self):
        lookup = _Lookup(_node(_pr_closer()))
        assert _satisfied([_closed_event(_BOT)], _always, lookup) == "merge"
        assert lookup.calls == 1

    def test_same_second_referenced_commit_is_never_attribution(self):
        """The codex CWE-863 scenario: a manual close (closer null) with a
        coincident same-second `referenced` ancestor commit."""
        stranger = {"login": "issue-author", "type": "User"}
        events = [_closed_event(stranger), _referenced_event()]
        assert _satisfied(events, _always, _Lookup(_node(None))) is None

    @pytest.mark.parametrize(
        "closer",
        [
            _pr_closer(merged=False),
            _pr_closer(base="release"),
            _pr_closer(repo="other/fork"),
            {"__typename": "Issue", "number": 3},
            None,
        ],
    )
    def test_closer_failing_any_condition_is_unsatisfied(self, closer):
        assert _satisfied([_closed_event(_BOT)], _always, _Lookup(_node(closer))) is None

    def test_repo_comparison_is_case_insensitive(self):
        lookup = _Lookup(_node(_pr_closer(repo="Owner/Repo")))
        assert _satisfied([_closed_event(_BOT)], _always, lookup) == "merge"

    def test_merge_commit_not_ancestor_is_unsatisfied_unknown_is_unknown(self):
        events = [_closed_event(_BOT)]
        lookup = _Lookup(_node(_pr_closer()))
        assert _satisfied(events, _never, lookup) is None
        assert _satisfied(events, lambda _s: None, lookup) == swc._UNKNOWN

    def test_closer_commit_ancestor_and_not(self):
        lookup = _Lookup(_node({"__typename": "Commit", "oid": _MERGE_SHA}))
        events = [_closed_event(_BOT)]
        assert _satisfied(events, _always, lookup) == "merge"
        assert _satisfied(events, _never, lookup) is None

    def test_node_created_at_must_match_the_rest_closed_event(self):
        lookup = _Lookup(_node(_pr_closer(), at="2026-10-25T23:43:50Z"))
        assert _satisfied([_closed_event(_BOT)], _always, lookup) == swc._UNKNOWN

    def test_failed_lookup_is_unknown(self):
        assert _satisfied([_closed_event(_BOT)], _always, _Lookup(None)) == swc._UNKNOWN

    def test_codeowner_closer_never_calls_the_lookup(self):
        lookup = _Lookup(None)
        assert _satisfied([_closed_event(_CODEOWNER)], _never, lookup) == "codeowner"
        assert lookup.calls == 0

    def test_failed_lookup_with_codeowner_closer_is_still_codeowner(self):
        assert _satisfied([_closed_event(_CODEOWNER)], _never, _Lookup(None)) == "codeowner"

    def test_commit_id_on_the_closed_event_is_merge_with_no_lookup(self):
        seen = []
        lookup = _Lookup(None)
        events = [_closed_event(_BOT, commit_id=_MERGE_SHA)]
        got = _satisfied(events, lambda sha: seen.append(sha) or True, lookup)
        assert got == "merge"
        assert seen == [_MERGE_SHA]
        assert lookup.calls == 0

    def test_commit_id_not_ancestor_is_decided_without_lookup(self):
        lookup = _Lookup(_node(_pr_closer()))
        events = [_closed_event(_BOT, commit_id=_MERGE_SHA)]
        assert _satisfied(events, _never, lookup) is None
        assert _satisfied(events, lambda _s: None, lookup) == swc._UNKNOWN
        assert lookup.calls == 0

    def test_budget_refusal_propagates_from_the_lookup(self):
        def _refused():
            raise swc._BudgetRefused

        with pytest.raises(swc._BudgetRefused):
            _satisfied([_closed_event(_BOT)], _always, _refused)

    @pytest.mark.parametrize(
        "actor",
        [
            {"login": "random-person", "type": "User"},
            {"login": "hos-worker-hos[bot]", "type": "Bot"},
            {"login": "scottthurlow", "type": "Bot"},  # a bot-typed account is never a human
            {},
        ],
    )
    def test_unverified_closer_with_null_closer_is_unsatisfied(self, actor):
        assert _satisfied([_closed_event(actor)], _never, _Lookup(_node(None))) is None

    def test_uses_the_last_closed_event(self):
        events = [_closed_event(_CODEOWNER, at="2026-01-01T00:00:00Z"), _closed_event(_BOT)]
        assert _satisfied(events, _never, _Lookup(_node(None))) is None

    @pytest.mark.parametrize("events", [None, {}, "x", [], [{"event": "reopened"}], ["junk"]])
    def test_no_closed_event_is_unsatisfied(self, events):
        assert _satisfied(events, _always, _Lookup(None)) is None


class TestCloserTransport:
    def _ok(self, nodes):
        return {"data": {"repository": {"issue": {"timelineItems": {"nodes": nodes}}}}}

    def test_query_is_a_literal_and_variables_reach_gh_only_as_arguments(self, monkeypatch):
        import subprocess

        captured = {}

        def _run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, '{"data": null}', "")

        monkeypatch.setattr(swc.subprocess, "run", _run)
        swc._run_graphql("owner", "repo", 1666)
        argv = captured["argv"]
        assert argv[:3] == ["gh", "api", "graphql"]
        assert f"query={swc._CLOSER_QUERY}" in argv
        assert "1666" not in swc._CLOSER_QUERY
        assert "$owner" in swc._CLOSER_QUERY and "$number" in swc._CLOSER_QUERY
        assert argv.count("-f") + argv.count("-F") == 4
        assert "number=1666" in argv and "owner=owner" in argv and "name=repo" in argv
        assert argv[argv.index("number=1666") - 1] == "-F"
        assert "{" not in "".join(a for a in argv if a.startswith(("owner=", "name=", "number=")))

    def test_one_request_per_lookup_counted_on_success_and_failure(self, monkeypatch):
        budget = swc._Budget(10)
        monkeypatch.setattr(swc, "_run_graphql", lambda *a: self._ok([{"x": 1}]))
        assert swc._fetch_closer_node("o/r", 5, budget) == {"x": 1}
        assert budget.spent == 1

        def _boom(*a):
            raise swc._GhFailure("exit 1")

        monkeypatch.setattr(swc, "_run_graphql", _boom)
        assert swc._fetch_closer_node("o/r", 5, budget) is None
        assert budget.spent == 2

    def test_refused_when_ceiling_reached_and_nothing_is_spent(self, monkeypatch):
        budget = swc._Budget(1)
        budget.record()
        monkeypatch.setattr(
            swc, "_run_graphql", lambda *a: (_ for _ in ()).throw(AssertionError("called"))
        )
        with pytest.raises(swc._BudgetRefused):
            swc._fetch_closer_node("o/r", 5, budget)
        assert budget.spent == 1

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            "x",
            {"errors": [{"message": "boom"}], "data": None},
            {"data": None},
            {"data": {"repository": None}},
            {"data": {"repository": {"issue": None}}},
            {"data": {"repository": {"issue": {"timelineItems": {"nodes": []}}}}},
            {"data": {"repository": {"issue": {"timelineItems": {"nodes": [{}, {}]}}}}},
            {"data": {"repository": {"issue": {"timelineItems": {"nodes": ["x"]}}}}},
        ],
    )
    def test_wrong_shape_or_errors_is_unknown(self, monkeypatch, payload):
        monkeypatch.setattr(swc, "_run_graphql", lambda *a: payload)
        assert swc._fetch_closer_node("o/r", 5, swc._Budget(10)) is None

    @pytest.mark.parametrize("repo", ["", "owner", "/name", "owner/"])
    def test_malformed_repo_spends_nothing(self, repo):
        budget = swc._Budget(10)
        assert swc._fetch_closer_node(repo, 5, budget) is None
        assert budget.spent == 0

    def test_default_branch_name_derives_from_the_ref_constant(self):
        assert swc._DEFAULT_BRANCH_REF.endswith("/" + swc._DEFAULT_BRANCH_NAME)


class TestAncestry:
    def test_malformed_sha_never_reaches_git(self, monkeypatch):
        monkeypatch.setattr(
            swc, "_git", lambda *a, **k: (_ for _ in ()).throw(AssertionError("git called"))
        )
        for bad in (None, "", "abc", "--upload-pack=x", "g" * 40, "a" * 41, 7):
            assert swc._is_default_branch_ancestor("/x", bad) is False

    def test_ancestor_yes_no_and_git_failure(self, monkeypatch):
        sha = "a" * 40
        monkeypatch.setattr(swc, "_git", lambda *a, **k: sha + "\n")
        assert swc._is_default_branch_ancestor("/x", sha) is True
        monkeypatch.setattr(swc, "_git", lambda *a, **k: "b" * 40 + "\n")
        assert swc._is_default_branch_ancestor("/x", sha) is False
        monkeypatch.setattr(swc, "_git", lambda *a, **k: "")
        assert swc._is_default_branch_ancestor("/x", sha) is False

        def _unknown(*a, **k):
            raise swc._GitFailure("exit 128: unknown object")

        monkeypatch.setattr(swc, "_git", _unknown)
        assert swc._is_default_branch_ancestor("/x", sha) is None

        def _boom(*a, **k):
            raise swc._GitFailure("unknown object")

        monkeypatch.setattr(swc, "_git", _boom)
        assert swc._is_default_branch_ancestor("/x", sha) is None


class TestClosedBlockerWalk:
    @pytest.fixture(autouse=True)
    def _ancestry(self, monkeypatch):
        self.on_main = {_MERGE_SHA}
        monkeypatch.setattr(swc, "_is_default_branch_ancestor", lambda _r, sha: sha in self.on_main)

    @pytest.fixture(autouse=True)
    def _graphql(self, monkeypatch):
        self.gql_calls = []
        self.closers = {}  # blocker number -> closer dict | None | "FAIL"

        def _fake(owner, name, number):
            self.gql_calls.append((owner, name, number))
            closer = self.closers.get(number)
            if closer == "FAIL":
                raise swc._GhFailure("simulated")
            return {
                "data": {"repository": {"issue": {"timelineItems": {"nodes": [_node(closer)]}}}}
            }

        monkeypatch.setattr(swc, "_run_graphql", _fake)

    def _events(self, stub, blocker, *events):
        stub.events_pages[blocker] = {1: list(events)}

    def test_bot_merged_pr_closer_unblocks(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_BOT))
        self.closers[900] = _pr_closer()
        rc, out, err = run_gate(capsys)
        assert (rc, _numbers(out)) == (0, [20])
        assert PREFIX + "blocker-satisfied issue=#20 blocker=#900 by=merge" in err
        assert "EXCLUDED" not in " ".join(err)
        assert "complete=yes" in " ".join(err)
        assert _fields(err)["api_requests"] == 4  # list + blockers + events + closer
        assert self.gql_calls == [("owner", "repo", 900)]

    def test_codex_scenario_same_second_reference_with_manual_close_is_excluded(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        author = {"login": "issue-author", "type": "User"}
        self._events(stub, 900, _closed_event(author), _referenced_event())
        self.closers[900] = None
        rc, out, err = run_gate(capsys)
        assert out == []
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err

    def test_codeowner_close_and_commit_id_spend_no_closer_request(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        stub.blockers[21] = [_blocker(901)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        self._events(stub, 901, _closed_event(_BOT, commit_id=_MERGE_SHA))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20, 21]
        assert self.gql_calls == []

    def test_failed_closer_lookup_is_unevaluated_not_excluded(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_BOT))
        self.closers[900] = "FAIL"
        rc, out, err = run_gate(capsys)
        assert (out, rc) == ([], 3)
        assert "EXCLUDED" not in " ".join(err)
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err

    def test_budget_exhausted_at_the_closer_lookup_is_refused(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_BOT))
        self.closers[900] = _pr_closer()
        # ceiling 3: list + blockers + events spent; the closer request is refused
        rc, out, err = run_gate(capsys, "--max-api-requests", "3")
        assert (out, rc) == ([], 3)
        joined = " ".join(err)
        assert "EXCLUDED" not in joined
        assert self.gql_calls == []
        assert _fields(err)["api_requests"] == 3
        assert _fields(err)["unevaluated:cost-ceiling"] == 1
        assert PREFIX + "unevaluated:cost-ceiling issue=#20" in err

    @pytest.mark.parametrize(
        "bad",
        [
            "junk",
            None,
            [],
            {"number": True},
            {"number": 0},
            {"number": -3},
            {"number": "12"},
            {"number": None},
            {},
        ],
    )
    def test_malformed_blocker_record_fails_closed_with_no_events_fetch(
        self, gate_repo, stub, capsys, bad
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        good = _blocker(900)
        stub.blockers[20] = [good, bad]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        rc, out, err = run_gate(capsys)
        assert (out, rc) == ([], 3)
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err
        assert "EXCLUDED" not in " ".join(err)
        assert not any("/events" in c for c in stub.calls)

    def test_malformed_record_next_to_an_open_blocker_is_failed_not_unsatisfied(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900, state="open"), "junk"]
        rc, out, err = run_gate(capsys)
        assert "EXCLUDED" not in " ".join(err)
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err

    def test_commit_id_on_closed_event_unblocks(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_BOT, commit_id=_MERGE_SHA))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20]

    def test_codeowner_close_unblocks(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20]
        assert PREFIX + "blocker-satisfied issue=#20 blocker=#900 by=codeowner" in err

    @pytest.mark.parametrize("reason", ["not_planned", "duplicate", None, "reopened"])
    def test_non_completed_closure_is_excluded_without_events_cost(
        self, gate_repo, stub, capsys, reason
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21)]
        stub.blockers[20] = [_blocker(900, reason)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err
        assert not any("/events" in c for c in stub.calls)
        f = _fields(err)
        assert f["scanned"] == 1 and f["scanned"] == f["evaluated"] + f["unevaluated"]

    @pytest.mark.parametrize("actor", [_BOT, {"login": "stranger", "type": "User"}])
    def test_completed_by_unverified_actor_without_merge_is_excluded(
        self, gate_repo, stub, capsys, actor
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(actor))
        rc, out, err = run_gate(capsys)
        assert out == []
        assert rc == 0
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err
        assert "complete=yes" in " ".join(err)
        assert "blocker-satisfied" not in " ".join(err)

    def test_merge_commit_off_main_is_excluded_unless_codeowner(self, gate_repo, stub, capsys):
        self.on_main = set()
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        stub.blockers[21] = [_blocker(901)]
        self._events(stub, 900, _closed_event(_BOT))
        self._events(stub, 901, _closed_event(_CODEOWNER))
        self.closers[900] = _pr_closer()
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err

    @pytest.mark.parametrize(
        "repository_url",
        [
            "https://api.github.com/repos/other/repo",
            "https://api.github.com/repos/owner/repo-evil",
            "https://api.github.com/repos/x/repos/owner/repo",
            "",
            None,
            7,
            "MISSING",
        ],
    )
    def test_foreign_or_unknown_repo_blocker_is_never_satisfied(
        self, gate_repo, stub, capsys, repository_url
    ):
        """A foreign closed-completed blocker whose number collides with a
        locally satisfied issue must not be judged on THIS repo's events."""
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21)]
        blocker = _blocker(57)
        if repository_url == "MISSING":
            del blocker["repository_url"]
        else:
            blocker["repository_url"] = repository_url
        stub.blockers[20] = [blocker]
        self._events(stub, 57, _closed_event(_CODEOWNER))  # local #57 WOULD satisfy
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err
        assert not any("/events" in c for c in stub.calls)

    def test_repository_url_match_is_case_insensitive_and_host_agnostic(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        blocker = _blocker(900)
        blocker["repository_url"] = "https://ghe.example.com/api/v3/repos/Owner/Repo"
        stub.blockers[20] = [blocker]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20]

    def test_open_plus_closed_blocker_stays_open_blocked_with_zero_added_requests(
        self, gate_repo, stub, capsys
    ):
        both = {"blocked_by": 1, "blocking": 0, "total_blocked_by": 2, "total_blocking": 0}
        stub.issue_pages[1] = [_issue(20, deps=both), _issue(21)]
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "EXCLUDED issues: #20(blocked-by-open-issue)" in err
        assert stub.calls == [_LIST_P1]

    def test_two_closed_blockers_one_unsatisfied_is_excluded(self, gate_repo, stub, capsys):
        two = {"blocked_by": 0, "blocking": 0, "total_blocked_by": 2, "total_blocking": 0}
        stub.issue_pages[1] = [_issue(20, deps=two)]
        stub.blockers[20] = [_blocker(900), _blocker(901)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        self._events(stub, 901, _closed_event(_BOT))
        rc, out, err = run_gate(capsys)
        assert out == []
        assert PREFIX + "EXCLUDED issues: #20(blocker-closed-unverified)" in err

    def test_two_closed_blockers_both_satisfied_is_selectable(self, gate_repo, stub, capsys):
        two = {"blocked_by": 0, "blocking": 0, "total_blocked_by": 2, "total_blocking": 0}
        stub.issue_pages[1] = [_issue(20, deps=two)]
        stub.blockers[20] = [_blocker(900), _blocker(901)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        self._events(stub, 901, _closed_event(_BOT))
        self.closers[901] = _pr_closer()
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20]

    def test_shared_blocker_is_paid_for_once(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        stub.blockers[21] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20, 21]
        assert sum("issues/900/events" in c for c in stub.calls) == 1

    def test_unsatisfied_record_is_excluded_not_gated_and_costs_no_trust_events(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [
            _issue(
                20,
                deps=_CLOSED_BLOCKER,
                user=_OUTSIDER["user"],
                user_type=_OUTSIDER["user_type"],
            )
        ]
        stub.blockers[20] = [_blocker(900, "not_planned")]
        rc, out, err = run_gate(capsys)
        assert rc == 0
        assert not any("issues/20/events" in c for c in stub.calls)
        assert "ALL-CANDIDATES-GATED" not in " ".join(err)

    def test_satisfied_untrusted_record_still_faces_the_trust_gate(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(
                20,
                deps=_CLOSED_BLOCKER,
                user=_OUTSIDER["user"],
                user_type=_OUTSIDER["user_type"],
            )
        ]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        stub.events_pages[20] = {1: []}
        rc, out, err = run_gate(capsys)
        assert out == []
        assert PREFIX + "ALL-CANDIDATES-GATED reasons: no-codeowner-actor=1" in err

    def test_budget_exhausted_during_check_is_degraded_not_pass_not_exclusion(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        # ceiling 2: list + blockers fetched, the events fetch is refused
        rc, out, err = run_gate(capsys, "--max-api-requests", "2")
        assert out == []
        assert rc == 3
        joined = " ".join(err)
        assert "complete=no" in joined
        assert "EXCLUDED" not in joined
        assert _fields(err)["unevaluated:cost-ceiling"] == 1
        assert PREFIX + "unevaluated:cost-ceiling issue=#20" in err
        assert _fields(err)["api_requests"] == 2

    def test_budget_exhausted_before_the_check_starts_is_degraded(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "1")
        assert (out, rc) == ([], 3)
        assert "EXCLUDED" not in " ".join(err)
        assert not any("unevaluated:cost-ceiling issue=" in ln for ln in err)

    def test_failed_blockers_fetch_is_unevaluated_not_pass(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER), _issue(21)]
        stub.blockers_fail.add(20)
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [21]
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err
        assert "complete=no" in " ".join(err)

    def test_failed_events_fetch_is_unevaluated_not_pass(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        stub.events_fail_pages[900] = {1}
        rc, out, err = run_gate(capsys)
        assert (out, rc) == ([], 3)
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err

    def test_unknown_ancestry_is_unevaluated_not_excluded_and_not_cached(
        self, gate_repo, stub, capsys, monkeypatch
    ):
        monkeypatch.setattr(swc, "_is_default_branch_ancestor", lambda _r, _sha: None)
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_BOT))
        self.closers[900] = _pr_closer()
        rc, out, err = run_gate(capsys)
        assert (out, rc) == ([], 3)
        assert "EXCLUDED" not in " ".join(err)
        assert PREFIX + "WARN unevaluated:query-failed issue=#20 check=closed-blocker" in err

    def test_unknown_ancestry_with_codeowner_closer_is_satisfied(
        self, gate_repo, stub, capsys, monkeypatch
    ):
        monkeypatch.setattr(swc, "_is_default_branch_ancestor", lambda _r, _sha: None)
        stub.issue_pages[1] = [_issue(20, deps=_CLOSED_BLOCKER)]
        stub.blockers[20] = [_blocker(900)]
        self._events(stub, 900, _closed_event(_CODEOWNER))
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [20]
        assert PREFIX + "blocker-satisfied issue=#20 blocker=#900 by=codeowner" in err

    def test_failed_shared_blocker_is_not_refetched_for_later_dependents(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [
            _issue(20, deps=_CLOSED_BLOCKER),
            _issue(21, deps=_CLOSED_BLOCKER),
            _issue(22, deps=_CLOSED_BLOCKER),
        ]
        for n in (20, 21, 22):
            stub.blockers[n] = [_blocker(900)]
        stub.events_fail_pages[900] = {1}
        rc, out, err = run_gate(capsys)
        assert (out, rc) == ([], 3)
        assert sum("issues/900/events" in c for c in stub.calls) == 1
        assert _fields(err)["unevaluated:query-failed"] == 3
        for n in (20, 21, 22):
            assert PREFIX + f"WARN unevaluated:query-failed issue=#{n} check=closed-blocker" in err

    def test_d5_query_failure_line_format_is_unchanged(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(30, user=_OUTSIDER["user"], user_type=_OUTSIDER["user_type"])]
        stub.events_fail_pages[30] = {1}
        rc, out, err = run_gate(capsys)
        assert PREFIX + "WARN unevaluated:query-failed issue=#30" in err

    def test_no_closed_blocker_means_no_new_requests(self, gate_repo, stub, capsys):
        _f0(stub)
        run_gate(capsys)
        assert not any("/dependencies" in c for c in stub.calls)
        assert len(stub.calls) == 3
