"""Tests for the #621 server-side overseer-approval gate.

Covers env-file parsing (load_env), the pure approval-matching logic
(overseer_has_approved), and main()'s exit-code contract via a stubbed
_gh so no real `gh` binary or network access is required.

Also covers the #2174 head-bound interim sign-off (which replaced the #1426
above-ceiling bypass): a marked overseer COMMENTED verdict on the current head
plus a designated human APPROVED on that head passes. A human approval alone
(no overseer verdict on the head) never passes (the #621 property).
"""

import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "require_overseer_approval",
    Path(__file__).resolve().parents[2] / "scripts" / "framework" / "require_overseer_approval.py",
)
assert _SPEC is not None and _SPEC.loader is not None
roa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(roa)


# ── load_env ─────────────────────────────────────────────────────────────────
def test_load_env_parses_quoted_values(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text('BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"  # comment\n')
    result = roa.load_env(env_file)
    assert result["BOT_OVERSEER_USERNAME"] == "hos-overseer-hos[bot]"


def test_load_env_skips_blank_and_comment_lines(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text("\n# a comment\nFOO=bar\n\n# another\nBAZ=qux\n")
    result = roa.load_env(env_file)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_skips_lines_without_equals(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text("not_an_assignment\nFOO=bar\n")
    result = roa.load_env(env_file)
    assert result == {"FOO": "bar"}


def test_load_env_expands_variable_references(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text('WORKER="hos-worker-hos[bot]"\nALL="${WORKER} extra"\n')
    result = roa.load_env(env_file)
    assert result["ALL"] == "hos-worker-hos[bot] extra"


def test_load_env_missing_file_exits_2(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    try:
        roa.load_env(missing)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert e.code == 2


# ── overseer_has_approved ────────────────────────────────────────────────────
def test_overseer_approved_matches_login_case_insensitively():
    reviews = [{"state": "APPROVED", "user": {"login": "Hos-Overseer-Hos[bot]"}}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is True


def test_overseer_not_approved_when_only_other_user_approved():
    reviews = [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


def test_overseer_non_approved_states_ignored():
    reviews = [
        {"state": "COMMENTED", "user": {"login": "hos-overseer-hos[bot]"}},
        {"state": "CHANGES_REQUESTED", "user": {"login": "hos-overseer-hos[bot]"}},
        {"state": "DISMISSED", "user": {"login": "hos-overseer-hos[bot]"}},
    ]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


def test_overseer_empty_reviews_list():
    assert roa.overseer_has_approved([], "hos-overseer-hos[bot]") is False


def test_overseer_missing_user_field_does_not_crash():
    reviews = [{"state": "APPROVED"}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


# ── get_reviews JSON handling ─────────────────────────────────────────────────
def test_get_reviews_empty_output_returns_empty_list(monkeypatch):
    monkeypatch.setattr(roa, "_gh", lambda *a: "")
    assert roa.get_reviews("owner/repo", "1") == []


def test_get_reviews_single_object_wrapped_in_list(monkeypatch):
    monkeypatch.setattr(roa, "_gh", lambda *a: json.dumps({"state": "APPROVED"}))
    assert roa.get_reviews("owner/repo", "1") == [{"state": "APPROVED"}]


def test_get_reviews_paginated_concatenated_arrays(monkeypatch):
    # gh --paginate may emit "][" (or with whitespace) between page arrays.
    monkeypatch.setattr(roa, "_gh", lambda *a: '[{"state": "APPROVED"}][{"state": "COMMENTED"}]')
    result = roa.get_reviews("owner/repo", "1")
    assert result == [{"state": "APPROVED"}, {"state": "COMMENTED"}]


# ── main() exit-code contract ─────────────────────────────────────────────────
HEAD = "a" * 40
OLD = "b" * 40


def _run_main(monkeypatch, tmp_path, argv, env_contents, gh_reviews, head=HEAD, codeowners=None):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text(env_contents)
    monkeypatch.setattr(roa, "ENV_FILE", env_file)
    if codeowners is not None:
        (tmp_path / ".github").mkdir(exist_ok=True)
        (tmp_path / ".github" / "CODEOWNERS").write_text(codeowners)
    monkeypatch.setattr(roa, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    def _fake_gh(*a):
        if "--jq" in a:
            return head + "\n"
        return json.dumps(gh_reviews)

    monkeypatch.setattr(roa, "_gh", _fake_gh)
    monkeypatch.setattr(sys, "argv", ["require_overseer_approval.py"] + argv)
    return roa.main()


def test_main_exits_0_when_overseer_approved(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "hos-overseer-hos[bot]"}}],
    )
    assert rc == 0


def test_main_exits_1_when_overseer_has_not_approved(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}],
    )
    assert rc == 1


def test_main_exits_2_when_bot_overseer_username_unset(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        "SOME_OTHER_KEY=value\n",
        [],
    )
    assert rc == 2


def test_main_exits_2_when_no_repo_available(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [],
    )
    assert rc == 2


def test_main_uses_github_repository_env_when_repo_flag_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "hos-overseer-hos[bot]"}}],
    )
    assert rc == 0


# ── #2174 interim sign-off ────────────────────────────────────────────────────
OVS = "hos-overseer-hos[bot]"
_ENV = (
    'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
    'HUMAN_REVIEWER="ScottThurlow"\n'
    'BOT_ACCOUNTS="hos-overseer-hos[bot] hos-worker-hos[bot]"\n'
)
_ARGV = ["--pr", "1", "--repo", "owner/repo"]


def _marker(head=HEAD, disp="HUMAN_REQUIRED", action="APPROVE"):
    return roa.render_interim_marker(disp, action, head)


def _ovs(
    body="narrative\n\n",
    state="COMMENTED",
    head=HEAD,
    at="2026-01-01T00:00:01Z",
    rid=1,
    utype="Bot",
    login=OVS,
    marker=True,
):
    if marker is True:
        body = body + _marker(head)
    return {
        "id": rid,
        "state": state,
        "body": body,
        "commit_id": head,
        "submitted_at": at,
        "user": {"login": login, "type": utype},
    }


def _human(head=HEAD, login="ScottThurlow", rid=50, utype="User"):
    return {
        "id": rid,
        "state": "APPROVED",
        "body": "",
        "commit_id": head,
        "submitted_at": "2026-01-01T00:00:09Z",
        "user": {"login": login, "type": utype},
    }


def _run(monkeypatch, tmp_path, reviews, env=_ENV, **kw):
    return _run_main(monkeypatch, tmp_path, _ARGV, env, reviews, **kw)


def test_marker_roundtrip_and_parse():
    m = roa.render_interim_marker("PROPOSE_ONLY", "DO_NOT_MERGE", HEAD)
    assert roa.parse_interim_marker("x\n" + m + "\n") == ("PROPOSE_ONLY", "DO_NOT_MERGE", HEAD)
    assert roa.parse_interim_marker("no marker") is None
    assert roa.parse_interim_marker(m + "\n" + m) is None  # two markers fail closed
    assert roa.parse_interim_marker("indented " + m) is None  # must be on its own line


def test_render_rejects_bad_inputs():
    import pytest

    for args in (
        ("BAD", "APPROVE", HEAD),
        ("HUMAN_REQUIRED", "NO_ACTION", HEAD),
        ("HUMAN_REQUIRED", "APPROVE", "abc"),
    ):
        with pytest.raises(ValueError):
            roa.render_interim_marker(*args)


def test_latest_verdict_exclusions_and_ordering():
    f = roa.latest_overseer_verdict_on_head
    assert f([_ovs(state="PENDING")], OVS, HEAD) is None
    assert f([_ovs(head=OLD)], OVS, HEAD) is None
    assert f([_ovs(body="", marker=False)], OVS, HEAD) is None
    older = _ovs(at="2026-01-01T00:00:01Z", rid=1)
    newer = _ovs(body="later", marker=False, at="2026-01-01T00:00:02Z", rid=2)
    assert f([newer, older], OVS, HEAD)["id"] == 2
    tie_a = _ovs(at="2026-01-01T00:00:01Z", rid=3)
    tie_b = _ovs(at="2026-01-01T00:00:01Z", rid=4)
    assert f([tie_a, tie_b], OVS, HEAD)["id"] == 4
    assert f([_ovs(state="DISMISSED")], OVS, HEAD)["state"] == "DISMISSED"


def test_designated_humans_combines_and_filters():
    owners = {"alice", "bob", "dev@example.com", "#"}
    got = roa.designated_humans({"HUMAN_REVIEWER": "Scott"}, owners)
    assert got == frozenset({"scott", "alice", "bob"})
    assert roa.designated_humans({"HUMAN_REVIEWER": "Scott"}, set()) == frozenset({"scott"})
    assert roa.designated_humans({}, set()) == frozenset()


def test_codeowners_individual_owners_uses_shared_parser_and_drops_teams(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text(
        "# comment @ignored\n/a/ @Alice @org/team\n\n/b/ @bob\n"
    )
    assert roa.codeowners_individual_owners(tmp_path) == {"alice", "bob"}
    empty = tmp_path / "none"
    empty.mkdir()
    assert roa.codeowners_individual_owners(empty) == set()


def test_eligible_humans_filters():
    d = frozenset({"scottthurlow"})
    f = roa.eligible_human_approvals_on_head
    bots = {OVS}
    assert f([_human()], bots, d, HEAD) == ["ScottThurlow"]
    assert f([_human(head=OLD)], bots, d, HEAD) == []
    assert f([_human(login="Other")], bots, d, HEAD) == []
    assert f([_human(login="scottthurlow", utype="Bot")], bots, d, HEAD) == []


def _human_at(state, at, rid, head=HEAD, login="ScottThurlow"):
    r = _human(head=head, login=login, rid=rid)
    r.update({"state": state, "submitted_at": at})
    return r


_D = frozenset({"scottthurlow"})


def test_eligible_approved_then_changes_requested_not_eligible(monkeypatch, tmp_path, capsys):
    approved = _human_at("APPROVED", "2026-01-01T00:00:09Z", 50)
    withdrawn = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:10Z", 51)
    f = roa.eligible_human_approvals_on_head
    assert f([approved, withdrawn], {OVS}, _D, HEAD) == []
    reviews = [_ovs(), approved, withdrawn, _human(login="Collab", rid=60)]
    assert _run(monkeypatch, tmp_path, reviews) == 1
    assert "Approve the PR on GitHub" in capsys.readouterr().err


def test_eligible_changes_requested_then_approved(monkeypatch, tmp_path):
    cr = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:09Z", 50)
    ok = _human_at("APPROVED", "2026-01-01T00:00:10Z", 51)
    assert roa.eligible_human_approvals_on_head([cr, ok], {OVS}, _D, HEAD) == ["ScottThurlow"]
    assert _run(monkeypatch, tmp_path, [_ovs(), cr, ok]) == 0


def test_eligible_approved_then_commented_still_eligible():
    ok = _human_at("APPROVED", "2026-01-01T00:00:09Z", 50)
    note = _human_at("COMMENTED", "2026-01-01T00:00:10Z", 51)
    assert roa.eligible_human_approvals_on_head([ok, note], {OVS}, _D, HEAD) == ["ScottThurlow"]


def test_eligible_approved_then_dismissed_not_eligible():
    ok = _human_at("APPROVED", "2026-01-01T00:00:09Z", 50)
    gone = _human_at("DISMISSED", "2026-01-01T00:00:10Z", 51)
    assert roa.eligible_human_approvals_on_head([ok, gone], {OVS}, _D, HEAD) == []


def test_eligible_changes_requested_on_older_commit_is_ignored():
    cr = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:01Z", 40, head=OLD)
    ok = _human_at("APPROVED", "2026-01-01T00:00:10Z", 51)
    assert roa.eligible_human_approvals_on_head([cr, ok], {OVS}, _D, HEAD) == ["ScottThurlow"]


def test_eligible_ordering_uses_submitted_at_and_id_not_list_position():
    f = roa.eligible_human_approvals_on_head
    ok = _human_at("APPROVED", "2026-01-01T00:00:09Z", 50)
    cr = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:10Z", 51)
    assert f([cr, ok], {OVS}, _D, HEAD) == []
    cr_first = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:09Z", 50)
    ok_later = _human_at("APPROVED", "2026-01-01T00:00:10Z", 51)
    assert f([ok_later, cr_first], {OVS}, _D, HEAD) == ["ScottThurlow"]
    tie_ok = _human_at("APPROVED", "2026-01-01T00:00:09Z", 70)
    tie_cr = _human_at("CHANGES_REQUESTED", "2026-01-01T00:00:09Z", 71)
    assert f([tie_cr, tie_ok], {OVS}, _D, HEAD) == []


def test_g_hr_1_signoff_plus_designated_human_passes(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()]) == 0
    assert "signed off" in capsys.readouterr().out


def test_g_hr_1_signoff_without_human_fails_m3(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, [_ovs()]) == 1
    err = capsys.readouterr().err
    assert "Approve the PR on GitHub" in err
    assert "ScottThurlow".lower() in err.lower()
    assert "do not count" in err


def test_g_po_1_propose_only_passes(monkeypatch, tmp_path):
    rv = _ovs(body="n\n", marker=False)
    rv["body"] += roa.render_interim_marker("PROPOSE_ONLY", "APPROVE", HEAD)
    assert _run(monkeypatch, tmp_path, [rv, _human()]) == 0


def test_g_merge_1_ceiling_gate_agrees(monkeypatch, tmp_path):
    """require-tier-ceiling only fails an overseer APPROVED above ceiling; a
    marked COMMENTED verdict is not one, so both gates can be green."""
    rtc = roa._load_sibling_module("require_tier_ceiling.py")
    assert not any(
        r["state"] == "APPROVED" and r["user"]["login"] == OVS for r in [_ovs(), _human()]
    )
    assert rtc is not None
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()]) == 0


def test_g_621_1_human_alone_fails_m1(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, [_human()]) == 1
    assert "has not reviewed" in capsys.readouterr().err


def test_g_621_2_marked_review_on_older_commit_fails(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_ovs(head=OLD), _human()]) == 1


def test_g_621_3_old_1426_shape_now_fails(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_ovs(marker=False), _human()]) == 1


def test_g_forge_1_marker_by_wrong_identity_ignored(monkeypatch, tmp_path):
    for who in (
        {"login": "ScottThurlow", "utype": "User"},
        {"login": "hos-worker-hos[bot]", "utype": "Bot"},
        {"login": OVS, "utype": "User"},
    ):
        assert _run(monkeypatch, tmp_path, [_ovs(**who), _human()]) == 1


def test_g_forge_2_two_markers_fail_closed(monkeypatch, tmp_path):
    rv = _ovs()
    rv["body"] += "\n" + _marker()
    assert _run(monkeypatch, tmp_path, [rv, _human()]) == 1


def test_g_forge_3_marker_head_differs_from_commit(monkeypatch, tmp_path):
    rv = _ovs()
    rv["body"] = "n\n\n" + _marker(head=OLD)
    assert _run(monkeypatch, tmp_path, [rv, _human()]) == 1


def test_g_forge_4_missing_user_type_not_a_verdict(monkeypatch, tmp_path):
    rv = _ovs()
    del rv["user"]["type"]
    assert _run(monkeypatch, tmp_path, [rv, _human()]) == 1


def test_g_revoke_1_later_unmarked_verdict_revokes(monkeypatch, tmp_path, capsys):
    later = _ovs(body="changed my mind", marker=False, at="2026-01-01T00:00:05Z", rid=9)
    assert _run(monkeypatch, tmp_path, [_ovs(), later, _human()]) == 1
    assert "not a sign-off" in capsys.readouterr().err


def test_g_desig_1_non_designated_approval_does_not_count(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, [_ovs(), _human(login="Collab")]) == 1
    assert "Approve the PR on GitHub" in capsys.readouterr().err


def test_g_desig_codeowners_user_counts(monkeypatch, tmp_path):
    assert (
        _run(monkeypatch, tmp_path, [_ovs(), _human(login="Alice")], codeowners="/x/ @alice\n") == 0
    )


def test_g_desig_3_no_codeowners_file_means_only_human_reviewer(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_ovs(), _human(login="Alice")]) == 1
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()]) == 0


def test_g_desig_4_empty_designated_set_exits_2(monkeypatch, tmp_path):
    env = 'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\nBOT_ACCOUNTS="x"\n'
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()], env=env) == 2


def test_g_cfg_1_empty_bot_accounts_exits_2(monkeypatch, tmp_path):
    env = 'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\nHUMAN_REVIEWER="ScottThurlow"\n'
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()], env=env) == 2


def test_g_cfg_2_unresolvable_head_exits_2(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()], head="") == 2
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()], head="XYZ") == 2


def _event(tmp_path, sha):
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"pull_request": {"head": {"sha": sha}}}))
    return p


def _run_with_event(monkeypatch, tmp_path, event_text, reviews):
    _run_main(monkeypatch, tmp_path, _ARGV, _ENV, reviews)  # configure stubs
    ev = tmp_path / "event.json"
    ev.write_text(event_text)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    return roa.main()


def test_g_head_1_event_head_differs_from_live(monkeypatch, tmp_path, capsys):
    ev = json.dumps({"pull_request": {"head": {"sha": OLD}}})
    assert _run_with_event(monkeypatch, tmp_path, ev, [_ovs(), _human()]) == 1
    assert "belongs to commit" in capsys.readouterr().err


def test_g_head_1_event_head_matches_live_passes(monkeypatch, tmp_path):
    ev = json.dumps({"pull_request": {"head": {"sha": HEAD}}})
    assert _run_with_event(monkeypatch, tmp_path, ev, [_ovs(), _human()]) == 0


def test_g_head_2_malformed_event_exits_2(monkeypatch, tmp_path):
    for text in (
        "not json",
        json.dumps({"pull_request": {}}),
        json.dumps({"pull_request": {"head": {"sha": "short"}}}),
    ):
        assert _run_with_event(monkeypatch, tmp_path, text, [_ovs(), _human()]) == 2


def test_g_dismiss_1_dismissed_later_approval_does_not_resurrect(monkeypatch, tmp_path):
    dismissed = _ovs(
        body="approved", marker=False, state="DISMISSED", at="2026-01-01T00:00:05Z", rid=9
    )
    assert _run(monkeypatch, tmp_path, [_ovs(), dismissed, _human()]) == 1


def test_unreadable_code_owners_exits_2_with_message(monkeypatch, tmp_path, capsys):
    def _boom(_root):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(roa, "codeowners_individual_owners", _boom)
    assert _run(monkeypatch, tmp_path, [_ovs(), _human()]) == 2
    err = capsys.readouterr().err
    assert "could not read the code owners" in err
    assert "No action is needed on the PR" in err


def test_code_owners_oserror_and_importerror_exit_2(monkeypatch, tmp_path):
    for exc in (OSError("denied"), ImportError("nope")):

        def _boom(_root, exc=exc):
            raise exc

        monkeypatch.setattr(roa, "codeowners_individual_owners", _boom)
        assert _run(monkeypatch, tmp_path, [_ovs(), _human()]) == 2


def test_gh_timeout_exits_2_with_timeout_passed(monkeypatch, capsys):
    import pytest

    seen = {}

    def _run(args, **kwargs):
        seen.update(kwargs)
        raise roa.subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(roa.subprocess, "run", _run)
    with pytest.raises(SystemExit) as exc:
        roa._gh("api", "repos/o/r/pulls/1")
    assert exc.value.code == 2
    assert seen["timeout"] == roa.GH_SUBPROCESS_TIMEOUT_SECONDS == 30
    assert "timed out" in capsys.readouterr().err
