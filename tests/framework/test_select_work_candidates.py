"""Tests for scripts/framework/select_work_candidates.py — the deterministic,
author-trust-gated work-selection gate (S2 of #1540, fix path for #1539).

Covers §6.2 of docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md
(revision 8): ordering parity ported from the deleted `next_candidates.jq`
suite, trust/authorization, the three bounds and their interactions, the
`complete=yes` invariant, AM-31's quarantine, AM-32's caller contract, AM-24's
authorization lines, AM-13 visibility, and the anti-knob sweep.
"""

from __future__ import annotations

import re

import pytest

from scripts.framework import select_work_candidates as swc

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def gate_repo(tmp_path, monkeypatch):
    """A throwaway repo tree with a working CODEOWNERS + machine-accounts.env,
    with `select_work_candidates._REPO_ROOT` monkeypatched to point at it."""
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
    number: int, *labels: str, title: str = "", user: str = "ScottThurlow", user_type: str = "User"
) -> dict:
    names = ["needs-ai", *labels]
    return {
        "number": number,
        "title": title or f"issue {number}",
        "labels": [{"name": n} for n in names],
        "user": {"login": user, "type": user_type},
        "pull_request": None,
    }


def _labeled_event(actor: str, label: str = "needs-ai", actor_type: str = "User") -> dict:
    return {
        "event": "labeled",
        "label": {"name": label},
        "actor": {"login": actor, "type": actor_type},
    }


class GhStub:
    """A scripted `gh api` double. Registered per data source, dispatched by
    regex over the endpoint string select_work_candidates builds."""

    def __init__(self):
        self.calls: list[str] = []
        self.issue_pages: dict[int, list] = {}
        self.events_pages: dict[int, dict[int, list]] = {}
        self.events_fail_pages: dict[int, set[int]] = {}
        self.collaborator_pages: dict[int, list] = {}
        self.fail_issue_pages: set[int] = set()
        self.fail_collaborator_pages: set[int] = set()

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
            page = int(m.group(1))
            if page in self.fail_issue_pages:
                raise swc._GhFailure("simulated transport failure")
            return self.issue_pages.get(page, [])
        m = re.search(r"/collaborators\?.*page=(\d+)", endpoint)
        if m:
            page = int(m.group(1))
            if page in self.fail_collaborator_pages:
                raise swc._GhFailure("simulated transport failure")
            return self.collaborator_pages.get(page, [])
        raise AssertionError(f"GhStub: unrecognised endpoint {endpoint!r}")


@pytest.fixture
def stub(monkeypatch):
    s = GhStub()
    monkeypatch.setattr(swc, "_run_gh", s)
    return s


def _numbers(lines: list[str]) -> list[int]:
    return [int(ln.split()[0].lstrip("#")) for ln in lines]


def run_gate(capsys, *args: str) -> tuple[int, list[str], list[str]]:
    argv = ["--repo", "owner/repo", "--milestone", "5", *args]
    rc = swc.main(argv)
    captured = capsys.readouterr()
    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    return rc, out_lines, err_lines


# ---------------------------------------------------------------------------
# Ordering parity — ported 1:1 from tests/automation/test_next_candidates.py
# (§4.2), each fixture given a trusted (CODEOWNER) author so ordering is
# tested in isolation from trust.
# ---------------------------------------------------------------------------


class TestOrderingParity:
    def test_high_beats_low_across_number_inversion(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(894), _issue(901, "priority:high")]
        rc, out, _ = run_gate(capsys)
        assert rc == 0
        assert _numbers(out) == [901, 894]

    def test_full_priority_ladder(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(700, "priority:low"),
            _issue(600, "priority:medium"),
            _issue(950, "priority:critical"),
            _issue(880, "priority:high"),
        ]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [950, 880, 600, 700]

    def test_tie_break_is_lowest_number_within_band(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(901, "priority:high"),
            _issue(880, "priority:high"),
            _issue(890, "priority:high"),
        ]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [880, 890, 901]

    def test_no_priority_label_defaults_to_low(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            _issue(894),
            _issue(700, "priority:low"),
            _issue(800, "priority:medium"),
        ]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [800, 700, 894]

    def test_default_low_label_rendered_as_low(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(894)]
        rc, out, _ = run_gate(capsys)
        assert out == ["#894 [low] issue 894"]

    def test_needs_human_is_excluded(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(500, "priority:high", "needs-human"), _issue(894)]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [894]

    def test_empty_input_yields_no_lines(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = []
        rc, out, _ = run_gate(capsys)
        assert out == []
        assert rc == 0  # complete=yes, empty milestone

    def test_all_blocked_yields_no_lines(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1, "needs-human")]
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_missing_or_null_labels_does_not_crash(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [
            {
                "number": 10,
                "title": "no labels key",
                "user": {"login": "ScottThurlow", "type": "User"},
            },
            {
                "number": 20,
                "title": "null labels",
                "labels": None,
                "user": {"login": "ScottThurlow", "type": "User"},
            },
            _issue(5, "priority:high"),
        ]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [5, 10, 20]

    def test_candidates_on_list_page_two_are_ranked_with_page_one(self, gate_repo, stub, capsys):
        """#1805's two-page fixture (§4.2 TestPaginationGlobalSort, ported).
        Page 1 padded to 100 raw records with PR records (dropped free by D1)
        so page 1 is FULL and page 2 is fetched (§1.4's per-page rule)."""
        page1 = [
            _issue(1643, "priority:critical"),
            _issue(1604, "priority:high"),
            _issue(1744, "priority:low"),
        ]
        page1 += [
            {
                "number": 9000 + i,
                "title": "pr",
                "labels": [],
                "pull_request": {"url": "x"},
                "user": {"login": "ScottThurlow", "type": "User"},
            }
            for i in range(97)
        ]
        assert len(page1) == 100
        page2 = [_issue(1340, "priority:high"), _issue(1357, "priority:high")]
        stub.issue_pages[1] = page1
        stub.issue_pages[2] = page2
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [1643, 1340, 1357, 1604, 1744]
        assert 1357 in _numbers(out)
        list_calls = [c for c in stub.calls if "/issues?" in c]
        assert len(list_calls) == 2


# ---------------------------------------------------------------------------
# Trust and authorization
# ---------------------------------------------------------------------------


class TestTrustAndAuthorization:
    def test_untrusted_author_with_worker_applied_needs_ai_is_not_a_candidate(
        self, gate_repo, stub, capsys
    ):
        """The core #1539 fix (VF-3's exact shape)."""
        stub.issue_pages[1] = [
            _issue(1539, "priority:critical", user="hos-worker-hos[bot]", user_type="Bot")
        ]
        stub.events_pages[1539] = {1: [_labeled_event("hos-worker-hos[bot]", actor_type="Bot")]}
        rc, out, err = run_gate(capsys)
        assert out == []
        assert "gated=1" in " ".join(err)

    def test_untrusted_author_with_codeowner_applied_label_is_a_candidate(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [_issue(1643, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1643] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [1643]
        assert any("AUTHORIZED issue=#1643 actor=ScottThurlow via=labeled" in ln for ln in err)

    def test_untrusted_author_with_codeowner_applied_milestone_is_not_a_candidate(
        self, gate_repo, stub, capsys
    ):
        """AR-7: a `milestoned` event, even by a verified CODEOWNER, never
        authorizes. The gate-level twin of test_milestoned_event_never_authorizes."""
        stub.issue_pages[1] = [_issue(1643, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1643] = {
            1: [{"event": "milestoned", "actor": {"login": "ScottThurlow", "type": "User"}}]
        }
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_no_fixture_produces_via_milestoned(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1643, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1643] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        assert not any("via=milestoned" in ln for ln in err)

    def test_human_proxy_bot_authored_issue_is_gated_without_marker(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1539, user="scottthurlow-claude[bot]", user_type="Bot")]
        stub.events_pages[1539] = {1: []}
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_human_proxy_bot_labelling_does_not_authorize(self, gate_repo, stub, capsys):
        """AD-6's named asymmetry: the human-proxy App applied needs-ai on an
        untrusted-authored issue -> still gated."""
        stub.issue_pages[1] = [_issue(9001, user="random-stranger", user_type="User")]
        stub.events_pages[9001] = {
            1: [_labeled_event("scottthurlow-claude[bot]", actor_type="Bot")]
        }
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_worker_self_labelled_worker_authored_issue_is_rejected(self, gate_repo, stub, capsys):
        """#1678's shape."""
        stub.issue_pages[1] = [
            _issue(1678, "priority:critical", user="hos-worker-hos[bot]", user_type="Bot")
        ]
        stub.events_pages[1678] = {1: [_labeled_event("hos-worker-hos[bot]", actor_type="Bot")]}
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_baseline_repair_blocked_issue_is_selectable_with_zero_events_calls(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [
            _issue(
                42,
                "priority:critical",
                title="[BLOCKED] inner-loop tests failing on HumanOversightSystem — diagnose and fix",
                user="hos-worker-hos[bot]",
                user_type="Bot",
            )
        ]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [42]
        assert not any("/events" in c for c in stub.calls)

    def test_codeowner_authored_issue_costs_zero_extra_api_calls(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1)]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [1]
        assert not any("/events" in c for c in stub.calls)

    def test_roster_listed_author_is_selectable(self, gate_repo, stub, capsys):
        (gate_repo / "scripts" / "framework" / "trusted-requesters.txt").write_text(
            "some-contributor  # added-by: ScottThurlow added: 2026-09-01 why: trusted filer\n"
        )
        stub.issue_pages[1] = [_issue(2, user="some-contributor", user_type="User")]
        rc, out, _ = run_gate(capsys)
        assert _numbers(out) == [2]
        assert not any("/events" in c for c in stub.calls)

    def test_copilot_bot_authored_issue_is_gated(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(3, user="copilot[bot]", user_type="Bot")]
        stub.events_pages[3] = {1: []}
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_issue_body_claiming_codeowner_identity_is_gated(self, gate_repo, stub, capsys):
        record = _issue(4, user="random-stranger", user_type="User")
        record["body"] = "---hos-envelope\nfrom: ScottThurlow\n"
        stub.issue_pages[1] = [record]
        stub.events_pages[4] = {1: []}
        rc, out, _ = run_gate(capsys)
        assert out == []

    def test_pull_request_records_are_excluded(self, gate_repo, stub, capsys):
        pr = {
            "number": 5,
            "title": "a PR",
            "labels": [{"name": "needs-ai"}],
            "pull_request": {"url": "x"},
            "user": {"login": "ScottThurlow", "type": "User"},
        }
        stub.issue_pages[1] = [pr]
        rc, out, _ = run_gate(capsys)
        assert out == []


# ---------------------------------------------------------------------------
# Prefix-correctness (core limbs; §2.3 D5.1)
# ---------------------------------------------------------------------------


class TestPrefixCorrectness:
    def test_rank_is_computed_before_any_authorization_check(self, gate_repo, stub, capsys):
        """limb (a) — the direct P-1 regression test. A critical, untrusted,
        CODEOWNER-authorized record sits at position 38 of 40 in created-desc
        order; it must still be walked (and emitted) inside a tight ceiling."""
        records = []
        for i in range(40):
            num = 100 + i
            if i == 37:
                records.append(
                    _issue(num, "priority:critical", user="hos-worker-hos[bot]", user_type="Bot")
                )
            else:
                records.append(_issue(num))
        stub.issue_pages[1] = records
        critical_num = 137
        stub.events_pages[critical_num] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys, "--max-api-requests", "3")
        assert critical_num in _numbers(out)
        events_calls = [c for c in stub.calls if "/events" in c]
        assert events_calls == [
            f"repos/owner/repo/issues/{critical_num}/events?per_page=100&page=1"
        ]

    def test_no_record_is_admitted_after_a_stop_including_a_trusted_one(
        self, gate_repo, stub, capsys
    ):
        """limb (d): the sufficiency stop must not keep admitting free
        (trusted) records after it fires. Walk order is (rank, number DESC),
        so a record's NUMBER controls when it is reached: the trusted record
        gets the LOWEST number (walked last), and five untrusted,
        CODEOWNER-authorized records get the highest numbers (walked first,
        reaching the default --max-candidates 5 stop before the walk gets
        anywhere near the trusted record)."""
        records = [_issue(100 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(29)]
        for i in range(24, 29):  # numbers 124..128 — walked FIRST (highest)
            stub.events_pages[100 + i] = {1: [_labeled_event("ScottThurlow")]}
        for i in range(0, 24):  # numbers 100..123 — walked after the stop
            stub.events_pages[100 + i] = {1: []}
        trusted_num = 50  # lowest number -> walked LAST
        records.append(_issue(trusted_num))  # trusted author, would be admitted free
        stub.issue_pages[1] = records
        rc, out, err = run_gate(capsys, "--max-candidates", "5")
        assert trusted_num not in _numbers(out)
        assert len(out) == 5
        # All five admitted records share one rank band (no priority label),
        # so Step E's emission order — (rank, number ASC), #901's
        # FIFO-within-band — is the exact ascending sequence here.
        assert _numbers(out) == [124, 125, 126, 127, 128]
        assert not any(f"/issues/{trusted_num}/events" in c for c in stub.calls)

    def test_early_exit_stops_at_max_candidates_and_admits_nothing_after(
        self, gate_repo, stub, capsys
    ):
        records = [_issue(300 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(20)]
        for i in range(20):
            stub.events_pages[300 + i] = {1: [_labeled_event("ScottThurlow")]}
        stub.issue_pages[1] = records
        rc, out, err = run_gate(capsys, "--max-candidates", "5")
        assert len(out) == 5
        assert any("unevaluated:sufficient=15" in ln for ln in err)
        assert not any("WARN" in ln and "sufficient" in ln for ln in err)


# ---------------------------------------------------------------------------
# The three bounds and their interactions (AM-22/AM-30/AM-31)
# ---------------------------------------------------------------------------


class TestBounds:
    def test_step_c_paginates_one_request_per_page_no_paginate_flag(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(i) for i in range(100)]
        stub.issue_pages[2] = [_issue(200)]
        rc, out, err = run_gate(capsys)
        list_calls = [c for c in stub.calls if "/issues?" in c]
        assert list_calls == [
            "repos/owner/repo/issues?state=open&milestone=5&labels=needs-ai&per_page=100&page=1",
            "repos/owner/repo/issues?state=open&milestone=5&labels=needs-ai&per_page=100&page=2",
        ]
        assert "api_requests=2" in " ".join(err)

    def test_list_page_bound_truncates_loudly(self, gate_repo, stub, capsys):
        for p in range(1, 7):
            stub.issue_pages[p] = [_issue(1000 * p + i) for i in range(100)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "100")
        list_calls = [c for c in stub.calls if "/issues?" in c]
        assert len(list_calls) == 5  # LIST_PAGE_BOUND
        assert any("WARN candidate-list-truncated" in ln for ln in err)
        assert any("unevaluated:list-truncated=yes" in ln for ln in err)
        assert "complete=no" in " ".join(err)

    def test_list_truncation_does_not_state_a_count_it_cannot_derive(self, gate_repo, stub, capsys):
        for p in range(1, 6):
            stub.issue_pages[p] = [_issue(1000 * p + i) for i in range(100)]
        rc, out, err = run_gate(capsys)
        line = next(ln for ln in err if "candidate-list-truncated" in ln)
        assert "at least" in line and "500" in line and "UNKNOWN" in line
        assert "records=500" not in line

    def test_request_ceiling_stops_the_walk_quietly(self, gate_repo, stub, capsys):
        records = [_issue(400 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(5)]
        for i in range(5):
            stub.events_pages[400 + i] = {1: []}
        stub.issue_pages[1] = records
        rc, out, err = run_gate(capsys, "--max-api-requests", "2")
        assert "complete=no" in " ".join(err)
        assert not any("WARN" in ln for ln in err)

    def test_api_requests_never_exceeds_the_ceiling(self, gate_repo, stub, capsys):
        records = [_issue(500 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(10)]
        for i in range(10):
            stub.events_pages[500 + i] = {1: []}
        stub.issue_pages[1] = records
        for ceiling in (0, 1, 2, 3, 5, 100):
            stub.calls.clear()
            run_gate(capsys, "--max-api-requests", str(ceiling))
            assert len(stub.calls) <= ceiling

    def test_early_exit_is_quiet_but_reported(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(600 + i) for i in range(10)]
        rc, out, err = run_gate(capsys, "--max-candidates", "3")
        assert len(out) == 3
        assert any("unevaluated:sufficient=7" in ln for ln in err)
        assert not any("WARN" in ln for ln in err)
        # Whole-suite assertion (code-reviewer finding): the literal
        # `UNEVALUATED` breakdown line must actually be emitted whenever
        # U > 0 — no test in this file previously asserted that string at
        # all, only its individual `unevaluated:<reason>=<n>` fields.
        assert any(ln.startswith("select_work_candidates: UNEVALUATED") for ln in err)

    def test_the_gate_keeps_no_resume_cursor(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(700)]
        rc1, out1, _ = run_gate(capsys)
        rc2, out2, _ = run_gate(capsys)
        assert out1 == out2 == ["#700 [low] issue 700"]

    def test_max_api_requests_can_only_lower(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "10000")
        assert "complete=yes" in " ".join(err)  # clamps to 100, plenty for 1 free record

    def test_max_api_requests_zero_is_legal(self, gate_repo, stub, capsys):
        rc, out, err = run_gate(capsys, "--max-api-requests", "0")
        assert rc == 3
        assert out == []
        assert not stub.calls


# ---------------------------------------------------------------------------
# F38 — panel condition C1: a Step C page refused by the ceiling
# ---------------------------------------------------------------------------


class TestF38StepCRefusedByCeiling:
    def test_two_full_pages_served_ceiling_two_refuses_third(self, gate_repo, stub, capsys):
        for p in (1, 2, 3):
            stub.issue_pages[p] = [_issue(1000 * p + i) for i in range(100)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "2")
        list_calls = [c for c in stub.calls if "/issues?" in c]
        assert len(list_calls) == 2
        assert not any("/events" in c for c in stub.calls)
        assert out == []
        assert rc == 3
        joined = " ".join(err)
        assert "evaluated=0" in joined
        assert "unevaluated:cost-ceiling=200" in joined
        assert not any(ln.startswith("select_work_candidates: AUTHORIZED") for ln in err)
        # CL6-6: at N=200, U=200 (all cost-ceiling), the UNEVALUATED
        # breakdown line MUST fire — U > 0 (TD §2.3 Step F: "when U > 0 OR
        # list-truncated=yes").
        assert any(ln.startswith("select_work_candidates: UNEVALUATED") for ln in err)
        assert any("unevaluated:cost-ceiling=200" in ln for ln in err if "UNEVALUATED" in ln)

    def test_ceiling_zero_refuses_immediately(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "0")
        assert not stub.calls
        assert out == []
        joined = " ".join(err)
        assert "complete=no" in joined
        assert rc == 3
        # CL6-6: at N=0 the UNEVALUATED line is ABSENT — U=0 (nothing was
        # fetched to be "not evaluated"; a refused Step C page forces
        # complete=no directly, per §2.3 Step C's REFUSED state, and it is
        # NOT summed into U per §1.2 consequence 6/TP-3). The exit-3 status
        # plus the summary's own complete=no already carry the "the gate
        # could not finish looking" signal at N=0; the UNEVALUATED line only
        # ever enumerates records the walk reached-but-could-not-place, and
        # there are none to enumerate here.
        assert not any(ln.startswith("select_work_candidates: UNEVALUATED") for ln in err)

    def test_complete_sweep_includes_a_refused_step_c_page(self, gate_repo, stub, capsys):
        """The `complete` sweep must cover a refused Step C page, not only
        the walk-side stops (sufficiency, cost-ceiling mid-walk, list
        truncation, quarantine)."""
        for p in (1, 2):
            stub.issue_pages[p] = [_issue(1000 * p + i) for i in range(100)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "1")
        assert "complete=no" in " ".join(err)


# ---------------------------------------------------------------------------
# The complete=yes invariant, budget clamp, and quarantine (AM-20/AM-31)
# ---------------------------------------------------------------------------


class TestCompleteInvariantAndClamp:
    def test_budget_clamp_that_bites_is_unevaluated_not_gated_and_stops_the_walk(
        self, gate_repo, stub, capsys
    ):
        """RUN4's counterexample 1. Same rank: #30 untrusted with its
        authorizing event on events page 2 (page 1 FULL, no match); #20
        trusted-authored; #10 untrusted and authorized on page 1. Walk order
        (rank, number DESC) = [#30, #20, #10]. A short list page 1 (3
        records) costs 1 request, leaving exactly 1 for the walk."""
        stub.issue_pages[1] = [
            _issue(30, user="hos-worker-hos[bot]", user_type="Bot"),
            _issue(20),
            _issue(10, user="hos-worker-hos[bot]", user_type="Bot"),
        ]
        stub.events_pages[30] = {
            1: [
                {
                    "event": "labeled",
                    "label": {"name": "other"},
                    "actor": {"login": "x", "type": "User"},
                }
            ]
            * 100,
            2: [_labeled_event("ScottThurlow")],
        }
        stub.events_pages[10] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys, "--max-api-requests", "2")
        joined = "\n".join(err)
        assert "unevaluated:cost-ceiling issue=#30" in joined
        assert "budget-clamped-events-fetch issue=#30" in joined
        assert not any("WARN" in ln for ln in err)
        assert not any("events-page-bound-reached" in ln for ln in err)
        assert not any("issues/30/events?per_page=100&page=2" in c for c in stub.calls)
        assert out == []  # #20 not emitted although free; #10 not reached
        assert "gated=0" in joined
        assert "eligible=0" in joined
        assert rc == 3
        assert "api_requests=2" in joined

    def test_a_quarantine_hole_may_outrank_an_admitted_record_and_is_named(
        self, gate_repo, stub, capsys
    ):
        stub.issue_pages[1] = [
            _issue(1678, "priority:critical", user="hos-worker-hos[bot]", user_type="Bot"),
            _issue(1600, "priority:medium", user="hos-worker-hos[bot]", user_type="Bot"),
        ]
        stub.events_fail_pages[1678] = {1}
        stub.events_pages[1600] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        assert _numbers(out) == [1600]
        joined = " ".join(err)
        assert "WARN unevaluated:query-failed issue=#1678" in joined
        assert "complete=no" in joined
        assert rc == 0

    def test_failed_events_query_quarantines_one_record_and_the_walk_continues(
        self, gate_repo, stub, capsys
    ):
        # --max-candidates clamps to 5 (may only lower): 6 same-rank records,
        # #2003 quarantined, the other 5 all authorized — the walk must reach
        # and admit all 5 despite the failure in the middle.
        records = [_issue(2000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(6)]
        stub.issue_pages[1] = records
        stub.events_fail_pages[2003] = {1}
        for i in range(6):
            if i != 3:
                stub.events_pages[2000 + i] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        assert 2003 not in _numbers(out)
        assert len(out) == 5
        assert rc == 0

    def test_every_events_query_failing_yields_exit_3_not_exit_2(self, gate_repo, stub, capsys):
        records = [_issue(2100 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(5)]
        stub.issue_pages[1] = records
        for i in range(5):
            stub.events_fail_pages[2100 + i] = {1}
        rc, out, err = run_gate(capsys)
        assert rc == 3
        joined = " ".join(err)
        assert "eligible=0" in joined
        assert "complete=no" in joined

    def test_exit_3_requires_both_incomplete_and_empty(self, gate_repo, stub, capsys):
        # complete=no (list-truncated) WITH candidates -> exit 0.
        for p in range(1, 6):
            stub.issue_pages[p] = [_issue(1000 * p + i) for i in range(100)]
        rc, out, err = run_gate(capsys)
        assert "complete=no" in " ".join(err)
        assert out
        assert rc == 0

    def test_complete_is_yes_only_when_nothing_was_skipped(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1)]
        rc, out, err = run_gate(capsys)
        assert "complete=yes" in " ".join(err)


# ---------------------------------------------------------------------------
# AM-13 visibility (F30) and AM-24 authorization lines
# ---------------------------------------------------------------------------


class TestVisibilityAndAuthorizationLines:
    def test_all_gated_emits_the_distinct_held_line(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1539, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1539] = {1: []}
        rc, out, err = run_gate(capsys)
        joined = " ".join(err)
        assert "ALL-CANDIDATES-GATED 1 of 1" in joined
        assert "ALL-CANDIDATES-GATED reasons:" in joined
        assert "ALL-CANDIDATES-GATED issues: #1539" in joined

    def test_empty_milestone_does_not_emit_the_held_line(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = []
        rc, out, err = run_gate(capsys)
        assert not any("ALL-CANDIDATES-GATED" in ln for ln in err)

    def test_held_line_issue_list_is_bounded(self, gate_repo, stub, capsys):
        records = [_issue(3000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(25)]
        stub.issue_pages[1] = records
        for i in range(25):
            stub.events_pages[3000 + i] = {1: []}
        rc, out, err = run_gate(capsys)
        line = next(ln for ln in err if "ALL-CANDIDATES-GATED issues:" in ln)
        assert "(+5 more)" in line

    def test_all_gated_exit_follows_the_exit_3_rule(self, gate_repo, stub, capsys):
        # complete=yes case
        stub.issue_pages[1] = [_issue(1, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1] = {1: []}
        rc, out, err = run_gate(capsys)
        assert rc == 0
        assert "complete=yes" in " ".join(err)
        assert not any("INCOMPLETE" in ln for ln in err)

        # complete=no case: a fully-gated walk stopped by the ceiling
        records = [_issue(4000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(5)]
        stub.issue_pages[1] = records
        for i in range(5):
            stub.events_pages[4000 + i] = {1: []}
        rc2, out2, err2 = run_gate(capsys, "--max-api-requests", "3")
        assert rc2 == 3
        joined2 = " ".join(err2)
        assert "complete=no" in joined2
        assert "INCOMPLETE" in joined2

    def test_gate_never_creates_an_issue(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1)]
        run_gate(capsys)
        assert not any("POST" in c for c in stub.calls)

    def test_authorized_count_distinguishes_d5_from_d4(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1), _issue(2, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[2] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        joined = " ".join(err)
        assert "eligible=2" in joined
        assert "authorized=1" in joined

    def test_each_d5_authorized_candidate_emits_its_actor(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1643, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1643] = {1: [_labeled_event("ScottThurlow")]}
        rc, out, err = run_gate(capsys)
        assert (
            "select_work_candidates: AUTHORIZED issue=#1643 actor=ScottThurlow via=labeled" in err
        )

    def test_unevaluated_tokens_never_appear_in_the_gated_reasons_breakdown(
        self, gate_repo, stub, capsys
    ):
        records = [_issue(5000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(3)]
        stub.issue_pages[1] = records
        stub.events_pages[5000] = {1: []}
        stub.events_fail_pages[5001] = {1}
        rc, out, err = run_gate(capsys, "--max-api-requests", "2")
        reasons_line = next((ln for ln in err if "ALL-CANDIDATES-GATED reasons:" in ln), "")
        for token in (
            "unevaluated:sufficient",
            "unevaluated:cost-ceiling",
            "unevaluated:query-failed",
        ):
            assert token not in reasons_line

    def test_unevaluated_records_are_not_counted_as_gated(self, gate_repo, stub, capsys):
        records = [_issue(6000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(45)]
        stub.issue_pages[1] = records
        for i in range(5):
            stub.events_pages[6000 + i] = {1: []}
        rc, out, err = run_gate(capsys, "--max-api-requests", "6")
        joined = " ".join(err)
        assert "gated=5" in joined
        assert "unevaluated=40" in joined


# ---------------------------------------------------------------------------
# Summary invariants, over every fixture above (spot-checked)
# ---------------------------------------------------------------------------


class TestSummaryInvariants:
    def test_summary_counts_are_internally_consistent(self, gate_repo, stub, capsys):
        records = [_issue(7000 + i, user="hos-worker-hos[bot]", user_type="Bot") for i in range(6)]
        stub.issue_pages[1] = records
        stub.events_pages[7000] = {1: [_labeled_event("ScottThurlow")]}
        stub.events_pages[7001] = {1: []}
        stub.events_fail_pages[7002] = {1}
        stub.events_pages[7003] = {1: []}
        stub.events_pages[7004] = {1: []}
        stub.events_pages[7005] = {1: []}
        rc, out, err = run_gate(capsys)
        joined = " ".join(err)
        fields = dict(
            tok.split("=") for tok in joined.split() if "=" in tok and not tok.startswith("issue")
        )
        scanned = int(fields["scanned"])
        evaluated = int(fields["evaluated"])
        eligible = int(fields["eligible"])
        gated = int(fields["gated"])
        unevaluated = int(fields["unevaluated"])
        authorized = int(fields["authorized"])
        assert scanned == evaluated + unevaluated
        assert evaluated == eligible + gated
        assert authorized <= eligible


# ---------------------------------------------------------------------------
# Fail-closed matrix (§3) — one test per live configuration row
# ---------------------------------------------------------------------------


class TestFailClosedConfiguration:
    def test_codeowners_file_absent(self, gate_repo, stub, capsys):
        (gate_repo / ".github" / "CODEOWNERS").unlink()
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert out == []
        assert any("codeowners-file-absent" in ln for ln in err)

    def test_codeowners_no_individual_human(self, gate_repo, stub, capsys):
        (gate_repo / ".github" / "CODEOWNERS").write_text("* @org/core-devs\n")
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert any("codeowners-no-individual-human" in ln for ln in err)
        assert any("team handles" in ln for ln in err)

    def test_machine_accounts_file_absent(self, gate_repo, stub, capsys):
        (gate_repo / "scripts" / "framework" / "machine-accounts.env").unlink()
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert any("machine-accounts-file-absent" in ln for ln in err)

    def test_bot_accounts_empty_after_union(self, gate_repo, stub, capsys, monkeypatch):
        (gate_repo / "scripts" / "framework" / "machine-accounts.env").write_text("")
        monkeypatch.delenv("BOT_ACCOUNTS", raising=False)
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert any("bot-accounts-empty" in ln for ln in err)

    def test_trusted_apps_empty(self, gate_repo, stub, capsys, monkeypatch):
        # File present (not absent) but names none of the three App roles;
        # BOT_ACCOUNTS supplies a non-empty bot set via the env union so B1
        # (bots) passes and B3 (apps) is the row that fails.
        (gate_repo / "scripts" / "framework" / "machine-accounts.env").write_text("")
        monkeypatch.setenv("BOT_ACCOUNTS", "some-other-bot[bot]")
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert any("trusted-apps-empty" in ln for ln in err)

    def test_milestone_non_numeric_fails_closed(self, gate_repo, stub, capsys):
        rc = swc.main(["--repo", "owner/repo", "--milestone", "@@MILESTONE_NUMBER@@"])
        assert rc == 2

    def test_repo_malformed_fails_closed(self, gate_repo, stub, capsys):
        rc = swc.main(["--repo", "not-a-slug", "--milestone", "5"])
        assert rc == 2

    def test_list_query_failed(self, gate_repo, stub, capsys):
        stub.fail_issue_pages.add(1)
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert any("list-query-failed" in ln for ln in err)

    def test_roster_unreadable_fails_closed(self, gate_repo, stub, capsys):
        """F7: `load_trusted_requesters` raising a non-`FileNotFoundError`
        `OSError` (here: the roster file exists but is unreadable, so
        `Path.read_text()` raises `PermissionError`) must exit 2
        `roster-unreadable` — never degrade to an empty, permissive roster."""
        roster_path = gate_repo / "scripts" / "framework" / "trusted-requesters.txt"
        roster_path.write_text("some-contributor  # added-by: x added: 2026-09-01 why: y\n")
        roster_path.chmod(0o000)
        stub.issue_pages[1] = [_issue(1)]
        try:
            rc, out, err = run_gate(capsys)
        finally:
            roster_path.chmod(0o644)  # restore so tmp_path cleanup can remove it
        assert rc == 2
        assert out == []
        assert any("roster-unreadable" in ln for ln in err)

    def test_config_error_on_an_unanticipated_exception(self, gate_repo, stub, capsys):
        """Step B's own catch-all (§2.3 Step B item 7): an exception no
        specific loader-failure branch anticipates — here, invalid UTF-8 in
        `machine-accounts.env`, which `_parse_env_file`'s `read_text(encoding
        ="utf-8")` raises as `UnicodeDecodeError`, NOT an `OSError` — must
        still exit 2 `config-error` rather than propagate a traceback or
        silently continue with a partial/incorrect trusted set."""
        (gate_repo / "scripts" / "framework" / "machine-accounts.env").write_bytes(
            b"BOT_WORKER_USERNAME=\xff\xfebad\n"
        )
        stub.issue_pages[1] = [_issue(1)]
        rc, out, err = run_gate(capsys)
        assert rc == 2
        assert out == []
        assert any("config-error" in ln for ln in err)


# ---------------------------------------------------------------------------
# Anti-knob sweep (AD-13)
# ---------------------------------------------------------------------------


class TestAntiKnob:
    def test_parser_exposes_exactly_five_flags(self):
        parser = swc._build_parser()
        opts = {a.option_strings[0] for a in parser._actions if a.option_strings} - {"-h", "--help"}
        assert opts == {
            "--repo",
            "--milestone",
            "--label",
            "--max-candidates",
            "--max-api-requests",
        }

    def test_max_candidates_can_only_lower_and_never_to_zero(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(i) for i in range(20)]
        rc, out, err = run_gate(capsys, "--max-candidates", "10000")
        assert len(out) == 5  # clamps to 5
        stub.calls.clear()
        rc, out, err = run_gate(capsys, "--max-candidates", "0")
        assert len(out) == 1  # clamps to 1, never 0

    def test_label_flag_cannot_widen_trust(self, gate_repo, stub, capsys):
        stub.issue_pages[1] = [_issue(1, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1] = {1: []}
        rc, out, err = run_gate(capsys, "--label", "anything")
        assert out == []


# ---------------------------------------------------------------------------
# Panel condition C2 (PANEL-1540-S1-S2 run 6): fetch_collaborators is wired
# to the gate's shared request budget, and a ceiling refusal during tier
# resolution is quiet (no WARN), never a security-affecting failure.
# ---------------------------------------------------------------------------


class TestTierResolutionCeilingWiring:
    def test_ceiling_refusal_during_tier_resolution_is_quiet(self, gate_repo, stub, capsys):
        (gate_repo / "scripts" / "framework" / "trusted-requesters.txt").write_text(
            "tier:write  # added-by: ScottThurlow added: 2026-09-01 why: write access implies trust\n"
        )
        # A full collaborators page 1 (100 records) so the resolver's own
        # loop attempts page 2 and is refused by the shared ceiling — proving
        # fetch_collaborators consults the SAME budget the gate's other
        # fetches spend from (RP6-2 / condition C2), not a private one.
        stub.collaborator_pages[1] = [
            {"login": f"collab-{i}", "type": "User", "role_name": "write"} for i in range(100)
        ]
        stub.issue_pages[1] = [_issue(1)]
        rc, out, err = run_gate(capsys, "--max-api-requests", "1")
        joined = " ".join(err)
        assert not any("WARN" in ln for ln in err)
        assert "complete=no" in joined
        # The collaborator fetch itself consumed the whole ceiling, so Step
        # C's own list page is refused too (N=0) -> exit 3, empty stdout.
        assert rc == 3
        assert out == []


# ---------------------------------------------------------------------------
# Panel condition C4 (carry-over): every bounded fetch pins per_page=100
# literally, in the endpoint string, never --paginate and never -f/-F.
# ---------------------------------------------------------------------------


class TestC4EveryFetchPinsPerPageLiterally:
    def test_no_endpoint_ever_uses_paginate_or_field_flags(self, gate_repo, stub, capsys):
        (gate_repo / "scripts" / "framework" / "trusted-requesters.txt").write_text(
            "tier:write  # added-by: ScottThurlow added: 2026-09-01 why: write access implies trust\n"
        )
        stub.collaborator_pages[1] = [{"login": "collab-1", "type": "User", "role_name": "write"}]
        stub.issue_pages[1] = [_issue(1, user="hos-worker-hos[bot]", user_type="Bot")]
        stub.events_pages[1] = {1: [_labeled_event("ScottThurlow")]}
        run_gate(capsys)
        assert stub.calls  # sanity: fetches actually happened
        for endpoint in stub.calls:
            assert "--paginate" not in endpoint
            assert re.search(r"per_page=100&page=\d+", endpoint), endpoint
        # gh api's own -f/-F flags are never passed as separate argv tokens by
        # this module — every endpoint call here is a single string argument.
        assert all(isinstance(c, str) for c in stub.calls)
