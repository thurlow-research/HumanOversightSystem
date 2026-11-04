"""Tests for the register-completeness bounce gate (#1125, overseer.md step 4a).

Covers the three functions overseer.md's step 4a names but that never existed:
  - check_register_completeness: re-checks contract §7 conditions 1-3 against
    the sign-off register on disk
  - bounce_count: derives the per-cid bounce counter from the audit trail
  - record_pr_bounce: comment -> confirm -> audit event -> finalize, with the
    SPEC-378 R3.3 halt-on-failure ordering
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from scripts.automation.lib import github as ghmod
from scripts.automation.lib.github import GitHubError
from scripts.automation.lib.merge_authority import (
    BounceResult,
    Finding,
    _bounce_comment_body,
    _required_signoffs_for_step,
    bounce_count,
    bounced_on_head,
    check_register_completeness,
    record_pr_bounce,
)

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"


def _write_manifest(tmp_path, roles, *, name="step-manifest.yaml"):
    """Write a manifest at the default path check_register_completeness expects.

    check_register_completeness()'s default manifest_path is
    <repo_root>/contract/step-manifest.yaml, so tests exercising the default
    (no explicit manifest_path) must write there.
    """
    manifest_dir = tmp_path / "contract"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / name
    manifest.write_text("steps:\n" "  - id: 1\n" f"    required_signoffs: [{', '.join(roles)}]\n")
    return manifest


# ---------------------------------------------------------------------------
# _required_signoffs_for_step
# ---------------------------------------------------------------------------


class TestRequiredSignoffsForStep:
    def test_finds_step(self, tmp_path):
        manifest = _write_manifest(tmp_path, ["code-review", "security"])
        assert _required_signoffs_for_step(manifest, 1) == ["code-review", "security"]

    def test_missing_step_returns_empty(self, tmp_path):
        manifest = _write_manifest(tmp_path, ["code-review"])
        assert _required_signoffs_for_step(manifest, 99) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert _required_signoffs_for_step(tmp_path / "nope.yaml", 1) == []


# ---------------------------------------------------------------------------
# check_register_completeness
# ---------------------------------------------------------------------------


class TestCheckRegisterCompleteness:
    def test_register_missing_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-missing"]
        assert result.reason_category == "REGISTER_GAP"

    def test_no_required_roles_passes_even_without_register(self, tmp_path):
        _write_manifest(tmp_path, [])
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False

    def test_complete_register_passes(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n"
            "Status: APPROVED\n"
            "Agent: code-reviewer\n"
            "Artifact: app/views.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False
        assert result.failures == []

    def test_missing_role_entry_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review", "security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n"
            "Status: APPROVED\n"
            "Agent: code-reviewer\n"
            "Artifact: app/views.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-missing-role:security"]
        assert result.reason_category == "REGISTER_GAP"

    def test_missing_required_field_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n" "Status: APPROVED\n" "Agent: code-reviewer\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert "register-missing-fields:code-review:Artifact,Iterations" in result.failures

    def test_unresolved_escalation_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-unresolved-escalation:security"]

    def test_resolved_escalation_with_human_resolution_passes(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 1\n"
            "Human_resolution: Accepted by ScottThurlow 2026-08-01\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False

    def test_later_entry_supersedes_earlier_escalation(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "## security | app/auth.py | T2\n"
            "Status: APPROVED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 2\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False


# ---------------------------------------------------------------------------
# bounce_count
# ---------------------------------------------------------------------------


class TestBounceCount:
    def test_zero_when_no_audit_log(self, tmp_path):
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 0

    def test_counts_only_matching_cid(self, tmp_path):
        from scripts.oversight.lib import audit_log

        audit_log.write_event(
            {"event": "pr-bounced", "cid": "cid-1", "timestamp": "2026-08-01T00:00:00Z"},
            root=str(tmp_path),
        )
        audit_log.write_event(
            {"event": "pr-bounced", "cid": "cid-2", "timestamp": "2026-08-01T00:00:01Z"},
            root=str(tmp_path),
        )
        audit_log.write_event(
            {"event": "human-required", "cid": "cid-1", "timestamp": "2026-08-01T00:00:02Z"},
            root=str(tmp_path),
        )
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1
        assert bounce_count("cid-2", repo_root=str(tmp_path)) == 1
        assert bounce_count("cid-3", repo_root=str(tmp_path)) == 0

    def test_counts_multiple_bounces_same_cid(self, tmp_path):
        from scripts.oversight.lib import audit_log

        for i in range(2):
            audit_log.write_event(
                {
                    "event": "pr-bounced",
                    "cid": "cid-1",
                    "bounce_number": i + 1,
                    "timestamp": f"2026-08-01T00:00:0{i}Z",
                },
                root=str(tmp_path),
            )
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 2


# ---------------------------------------------------------------------------
# record_pr_bounce
# ---------------------------------------------------------------------------

HEAD = "a" * 40
HEAD2 = "b" * 40
MA = "scripts.automation.lib.merge_authority"


def _gh_stub(heads=(HEAD,), draft=True, labels=("needs-ai",), calls=None):
    """A `_run_gh` stand-in: the PR read returns the next head in `heads` (the
    last one repeats), everything else returns an empty dict."""
    state = {"n": 0}

    def fake(args, *a, **k):
        if calls is not None:
            calls.append((args, k))
        url = args[0]
        if re.search(r"/pulls/\d+$", url):
            head = heads[min(state["n"], len(heads) - 1)]
            state["n"] += 1
            return {"head": {"sha": head}, "draft": draft, "labels": [{"name": n} for n in labels]}
        return {}

    return fake


def _post(counter=None):
    n = {"i": 0}

    def fake(owner, repo, number, body, **k):
        n["i"] += 1
        if counter is not None:
            counter.append(body)
        return {
            "id": n["i"],
            "html_url": f"https://example/pr/{number}#comment-{n['i']}",
            "created_at": "2026-10-31T01:00:00Z",
        }

    return fake


def _f(cls="MERITS", key="MERITS:a.py:some-slug", path="a.py", origin="llm", **kw):
    return Finding(
        cls=cls,
        key=key,
        identity=(cls, path or "-") if origin == "llm" else (cls, key),
        origin=origin,
        path=path,
        summary=kw.pop("summary", "A problem"),
        **kw,
    )


def _bounce(tmp_path, *, findings=None, failures=(), head_sha=None, **kw):
    kwargs = dict(
        cid="cid-1",
        reason_category="REGISTER_GAP",
        summary="s",
        repo_root=str(tmp_path),
    )
    kwargs.update(kw)
    if findings is not None:
        kwargs["findings"] = findings
        kwargs["head_sha"] = head_sha or HEAD
    else:
        kwargs["failures"] = list(failures)
        if head_sha:
            kwargs["head_sha"] = head_sha
    return record_pr_bounce(OWNER, REPO, 123, **kwargs)


class TestRecordPrBounce:
    def test_invalid_reason_category_raises(self, tmp_path):
        with pytest.raises(ValueError):
            record_pr_bounce(
                OWNER,
                REPO,
                123,
                cid="cid-1",
                reason_category="NOT_A_CATEGORY",
                summary="x",
                failures=["register-missing"],
                repo_root=str(tmp_path),
            )

    def test_happy_path_posts_comment_writes_audit_event_and_finalizes(self, tmp_path):
        calls = []
        bodies = []
        with (
            patch(f"{MA}.post_comment", side_effect=_post(bodies)) as mock_post,
            patch(f"{MA}._run_gh", side_effect=_gh_stub(calls=calls)),
            patch(f"{MA}._convert_pr_to_draft") as mock_draft,
        ):
            result = record_pr_bounce(
                OWNER,
                REPO,
                123,
                cid="cid-1",
                reason_category="REGISTER_GAP",
                summary="missing security sign-off",
                failures=["register-missing-role:security"],
                repo_root=str(tmp_path),
            )

        assert isinstance(result, BounceResult)
        assert result.bounce_number == 1
        assert result.comment_url == "https://example/pr/123#comment-1"
        assert result.finalize_errors == []
        assert result.skipped is False
        mock_post.assert_called_once()
        assert "**Reason category:** REGISTER_GAP" in bodies[0]
        assert "**Summary:** missing security sign-off" in bodies[0]
        assert "register-missing-role:security" in bodies[0]
        mock_draft.assert_called_once_with(OWNER, REPO, 123)
        label_calls = [c for c in calls if "/labels" in c[0][0]]
        assert len(label_calls) == 1

        # audit event was committed and is counted by bounce_count
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1

        audit_event = json.loads((tmp_path / "audit" / "log" / result.audit_relpath).read_text())
        assert audit_event["assigned_to"] is None

    def test_second_bounce_increments_bounce_number(self, tmp_path):
        # Two different heads, so the same-head skip does not apply.
        with (
            patch(f"{MA}.post_comment", side_effect=_post()),
            patch(f"{MA}._run_gh", side_effect=_gh_stub(heads=(HEAD, HEAD2))),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            _bounce(tmp_path, failures=["register-missing"], summary="first")
            second = _bounce(tmp_path, failures=["register-missing"], summary="second")
        assert second.bounce_number == 2

    def test_comment_post_failure_halts_before_audit_event(self, tmp_path):
        with (
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}.post_comment", side_effect=GitHubError("boom")),
        ):
            with pytest.raises(GitHubError):
                _bounce(tmp_path, failures=["register-missing"], summary="x")
        # No audit event was written -- the halt-on-failure ordering held.
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 0
        assert not (tmp_path / "audit" / "log").exists()

    def test_finalize_step_failure_is_recorded_not_raised(self, tmp_path):
        def failing_gh(args, *a, **k):
            if re.search(r"/pulls/\d+$", args[0]):
                return {"head": {"sha": HEAD}}
            raise GitHubError("label failed")

        with (
            patch(f"{MA}.post_comment", side_effect=_post()),
            patch(f"{MA}._run_gh", side_effect=failing_gh),
            patch(f"{MA}._convert_pr_to_draft", side_effect=GitHubError("draft failed")),
        ):
            result = _bounce(tmp_path, failures=["register-missing"], summary="x")
        # Audit event still committed -- only finalize sub-steps failed.
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1
        assert len(result.finalize_errors) == 2  # label, draft failed

    def test_no_assignee_api_call_is_ever_made(self, tmp_path):
        calls = []
        with (
            patch(f"{MA}.post_comment", side_effect=_post()),
            patch(f"{MA}._run_gh", side_effect=_gh_stub(calls=calls)),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            _bounce(tmp_path, failures=["register-missing"], summary="x")
        for args, _ in calls:
            assert "/assignees" not in args[0]


# ---------------------------------------------------------------------------
# #2209 S1a: renderings, same-head dedup, event shape
# ---------------------------------------------------------------------------

_FORBIDDEN = ("REQUEST CHANGES", "Expected action", "needs-human", "procedural completeness")


class TestBounceRenderings:
    def test_t_bg_1_legacy_rendering(self):
        body = _bounce_comment_body(
            ["register-missing-role:security", "free text"], "REGISTER_GAP", "s", 1, head_sha=HEAD
        )
        assert body.startswith(f"## PR bounced to the worker: 2 finding(s) on {HEAD[:12]}\n")
        assert "### Specific failures" in body
        assert "- [register-missing-role:security] Required sign-off missing: security" in body
        assert "- [item-2] free text" in body
        assert "How to respond" not in body
        assert "procedural completeness" not in body

    def test_t_bg_2_findings_rendering_parses_with_worker_regex(self, tmp_path):
        bodies = []
        findings = [
            _f(path="a.py", key="MERITS:a.py:one", detail="Because."),
            _f(key="MERITS:a.py:two"),
        ]
        with (
            patch(f"{MA}.post_comment", side_effect=_post(bodies)),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            result = _bounce(tmp_path, findings=findings, reason_category="MERITS_FINDING")
        regex = re.compile(
            r"^- \[(?P<id>[0-9a-f]{12}-F\d+)\] \((?P<cls>[A-Z_]+)\) (?P<summary>.+)$"
        )
        rows = [m for m in (regex.match(line) for line in bodies[0].splitlines()) if m]
        assert [m["id"] for m in rows] == [f"{HEAD[:12]}-F1", f"{HEAD[:12]}-F2"]
        assert result.finding_ids == [m["id"] for m in rows]
        assert "A problem. Because." in bodies[0]
        assert "`/hos dispute <finding-id>`" in bodies[0]
        assert "_Bounce #1 for cid-1 (cap: 2 before human escalation)._" in bodies[0]

    def test_t_bg_9_no_forbidden_text_in_either_rendering(self, tmp_path):
        bodies = []
        with (
            patch(f"{MA}.post_comment", side_effect=_post(bodies)),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
            _bounce(tmp_path, failures=["register-missing"], head_sha=HEAD2)
        legacy = _bounce_comment_body(
            ["check-failing:tests"], "COMPLIANCE_FAILURE", "s", 1, head_sha=HEAD
        )
        for body in [*bodies, legacy]:
            for text in _FORBIDDEN:
                assert text not in body


class TestSameHeadDedup:
    def _ctx(self, **gh):
        return (
            patch(f"{MA}.post_comment", side_effect=_post(gh.get("bodies"))),
            patch(f"{MA}._run_gh", side_effect=gh.get("stub") or _gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
        )

    def test_t_bg_3_repeat_on_same_head_posts_nothing(self, tmp_path):
        bodies = []
        a, b, c = self._ctx(bodies=bodies)
        with a, b, c:
            first = _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
            second = _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
        assert first.skipped is False
        assert second.skipped is True
        assert second.comment_url is None
        assert len(bodies) == 1
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1

    def test_t_bg_4_new_key_on_same_head_continues_numbering(self, tmp_path):
        bodies = []
        a, b, c = self._ctx(bodies=bodies)
        with a, b, c:
            _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
            second = _bounce(
                tmp_path,
                findings=[_f(key="MERITS:a.py:other", path="b.py")],
                reason_category="MERITS_FINDING",
            )
        assert second.skipped is False
        assert second.finding_ids == [f"{HEAD[:12]}-F2"]
        assert second.bounce_number == 2
        assert f"[{HEAD[:12]}-F2]" in bodies[1]

    @pytest.mark.parametrize(
        "draft,labels,expect_label,expect_draft,repaired",
        [
            (True, ("needs-ai",), False, False, []),
            (True, (), True, False, ["label"]),
            (False, ("needs-ai",), False, True, ["draft"]),
        ],
    )
    def test_t_bg_5_skip_repairs_unfinished_finalize(
        self, tmp_path, draft, labels, expect_label, expect_draft, repaired
    ):
        a, b, c = self._ctx()
        with a, b, c:
            _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
        calls = []
        stub = _gh_stub(draft=draft, labels=labels, calls=calls)
        with (
            patch(f"{MA}.post_comment") as post,
            patch(f"{MA}._run_gh", side_effect=stub),
            patch(f"{MA}._convert_pr_to_draft") as to_draft,
            patch.object(ghmod, "list_issue_events", return_value=[]),
        ):
            result = _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
        post.assert_not_called()
        assert result.skipped and result.finalize_errors == []
        assert result.finalize_repaired == repaired
        assert any("/labels" in c[0][0] for c in calls) is expect_label
        assert to_draft.called is expect_draft
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1

    def test_t_bg_6_head_is_read_before_posting_and_failure_posts_nothing(self, tmp_path):
        order = []

        def gh(args, *a, **k):
            order.append("gh")
            return _gh_stub()(args)

        def post(*a, **k):
            order.append("post")
            return {"id": 1, "html_url": "u", "created_at": "2026-10-31T01:00:00Z"}

        with (
            patch(f"{MA}.post_comment", side_effect=post),
            patch(f"{MA}._run_gh", side_effect=gh),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            _bounce(tmp_path, failures=["register-missing"])
        assert order[0] == "gh" and order.index("post") > 0

        other = tmp_path / "other"
        with (
            patch(f"{MA}.post_comment") as post_mock,
            patch(f"{MA}._run_gh", side_effect=GitHubError("down")),
        ):
            with pytest.raises(GitHubError):
                _bounce(other, failures=["register-missing"])
        post_mock.assert_not_called()
        assert not (other / "audit" / "log").exists()

    def test_t_bg_8_findings_argument_validation_happens_before_any_io(self, tmp_path):
        with patch(f"{MA}.post_comment") as post, patch(f"{MA}._run_gh") as gh:
            with pytest.raises(ValueError):
                record_pr_bounce(
                    OWNER,
                    REPO,
                    123,
                    cid="c",
                    reason_category="MERITS_FINDING",
                    summary="s",
                    failures=["x"],
                    findings=[_f()],
                    head_sha=HEAD,
                    repo_root=str(tmp_path),
                )
            with pytest.raises(ValueError):
                record_pr_bounce(
                    OWNER,
                    REPO,
                    123,
                    cid="c",
                    reason_category="MERITS_FINDING",
                    summary="s",
                    findings=[_f()],
                    repo_root=str(tmp_path),
                )
        post.assert_not_called()
        gh.assert_not_called()

    def test_t_bg_7_event_shape(self, tmp_path):
        a, b, c = self._ctx()
        with patch.dict("os.environ", {"HOS_BOT_LOGIN": "hos-overseer-hos[bot]"}), a, b, c:
            result = _bounce(
                tmp_path,
                findings=[_f(detail="SECRET-DETAIL-TEXT")],
                reason_category="MERITS_FINDING",
                epoch_since="2026-10-30T00:00:00Z",
            )
        text = (tmp_path / "audit" / "log" / result.audit_relpath).read_text()
        event = json.loads(text)
        assert event["head_sha"] == HEAD
        assert event["findings"] == [
            {
                "id": f"{HEAD[:12]}-F1",
                "class": "MERITS",
                "key": "MERITS:a.py:some-slug",
                "origin": "llm",
                "path": "a.py",
            }
        ]
        assert event["failures"] == ["MERITS:a.py:some-slug"]
        assert event["comment_id"] == 1
        assert event["comment_created_at"] == "2026-10-31T01:00:00Z"
        assert event["epoch_start"] == "2026-10-30T00:00:00Z"
        assert event["actor"] == "hos-overseer-hos[bot]"
        assert "SECRET-DETAIL-TEXT" not in text and "detail" not in event

    def test_t_bg_10_legacy_and_collector_keys_are_one_bounce(self, tmp_path):
        legacy = ["register-missing-role:security", "check-failing:tests"]
        collector = [
            _f("PROCEDURAL", "PROCEDURAL:register-missing-role:security", None, "code"),
            _f("REQUIRED_CHECK", "REQUIRED_CHECK:check-failing:tests", None, "code"),
        ]
        bodies = []
        a, b, c = self._ctx(bodies=bodies)
        with a, b, c:
            first = _bounce(tmp_path, failures=legacy, head_sha=HEAD)
            second = _bounce(tmp_path, findings=collector, reason_category="MIXED")
        assert first.skipped is False and second.skipped is True
        assert len(bodies) == 1
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1

        other = tmp_path / "reverse"
        a, b, c = self._ctx(bodies=bodies)
        with a, b, c:
            one = _bounce(other, findings=collector, reason_category="MIXED")
            two = _bounce(other, failures=legacy, head_sha=HEAD)
        assert one.skipped is False and two.skipped is True

    def test_t_bg_10_unknown_legacy_token_matches_no_collector_key(self, tmp_path):
        a, b, c = self._ctx()
        with a, b, c:
            _bounce(tmp_path, failures=["some-other-token"], head_sha=HEAD)
            prior = bounced_on_head("cid-1", HEAD, repo_root=str(tmp_path))
            second = _bounce(
                tmp_path,
                findings=[_f("PROCEDURAL", "PROCEDURAL:some-other-token", None, "code")],
                reason_category="REGISTER_GAP",
            )
        assert prior[0].cls == "LEGACY" and prior[0].identity == ("LEGACY", "some-other-token")
        assert second.skipped is False


class TestCommentSafety:
    def _render(self, findings):
        from scripts.automation.lib.merge_authority import _bounce_comment_body_findings

        return _bounce_comment_body_findings(
            [(f"{HEAD[:12]}-F{i + 1}", f) for i, f in enumerate(findings)],
            "MERITS_FINDING",
            "s",
            1,
            cid="cid-1",
            head_sha=HEAD,
        )

    def test_oversize_body_is_capped_detail_first(self):
        from scripts.automation.lib.merge_authority import BOUNCE_BODY_MAX_CHARS

        findings = [
            _f(
                key=f"MERITS:a.py:s{i}",
                summary="s" * 200,
                detail="d" * 2000,
                source_url="https://github.com/o/r/" + "u" * 470,
            )
            for i in range(50)
        ]
        body = self._render(findings)
        assert len(body) <= BOUNCE_BODY_MAX_CHARS
        assert "truncated" not in body  # truncating detail was enough
        assert body.count("- [") == 50

    def test_still_oversize_lists_ids_and_summaries_with_a_truncation_line(self):
        from scripts.automation.lib.merge_authority import BOUNCE_BODY_MAX_CHARS

        findings = [_f(key=f"MERITS:a.py:s{i}", summary="s" * 200) for i in range(2000)]
        body = self._render(findings)
        assert len(body) <= BOUNCE_BODY_MAX_CHARS
        assert re.search(r"- \d+ findings truncated; see audit event", body)
        assert "### How to respond" in body and "_Bounce #1" in body

    def test_audit_event_keeps_every_finding_when_the_comment_is_truncated(self, tmp_path):
        findings = [_f(key=f"MERITS:a.py:s{i}", summary="s" * 200) for i in range(400)]
        with (
            patch(f"{MA}.post_comment", side_effect=_post()),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            result = _bounce(tmp_path, findings=findings, reason_category="MERITS_FINDING")
        event = json.loads((tmp_path / "audit" / "log" / result.audit_relpath).read_text())
        assert len(event["findings"]) == 400

    def test_mentions_and_markdown_are_neutralized(self):
        body = self._render(
            [_f(summary="ping @octocat ![x](http://e/x.png)", detail="cc @org/team [a](http://b)")]
        )
        assert "@octocat" not in body and "@\u200bocto" in body
        assert "@org/team" not in body
        assert "![" not in body and "](" not in body

    def test_raw_html_is_escaped(self):
        body = self._render([_f(summary="<img src=http://e/x>", detail="<http://e/auto>")])
        assert "<img" not in body and "<http" not in body and "&lt;img" in body


# --- TD-D9 five-state repair -------------------------------------------------

T_BOUNCE = "2026-10-31T01:00:00Z"  # the stub post's created_at, i.e. T
AFTER, BEFORE = "2026-10-31T01:00:05Z", "2026-10-31T00:59:00Z"


def _ev(kind, at, login="hos-worker-hos[bot]", label=None):
    event = {"event": kind, "created_at": at, "actor": {"login": login}}
    if label:
        event["label"] = {"name": label}
    return event


class TestRepairBounceFinalize:
    def _bounced(self, tmp_path):
        with (
            patch(f"{MA}.post_comment", side_effect=_post()),
            patch(f"{MA}._run_gh", side_effect=_gh_stub()),
            patch(f"{MA}._convert_pr_to_draft"),
        ):
            _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")

    def _repair(self, tmp_path, events, *, draft=False, labels=()):
        from scripts.automation.lib.merge_authority import repair_bounce_finalize

        calls, errors = [], []
        events_fn = events if callable(events) else (lambda *a, **k: events)
        with (
            patch(f"{MA}._run_gh", side_effect=_gh_stub(draft=draft, labels=labels, calls=calls)),
            patch(f"{MA}._convert_pr_to_draft") as to_draft,
            patch.object(ghmod, "list_issue_events", side_effect=events_fn) as ev,
        ):
            try:
                got = repair_bounce_finalize(
                    OWNER,
                    REPO,
                    123,
                    cid="cid-1",
                    head_sha=HEAD,
                    repo_root=str(tmp_path),
                    errors=errors,
                )
            finally:
                self.calls, self.to_draft, self.ev, self.errors = calls, to_draft, ev, errors
        return got

    def _wrote_label(self):
        return any("/labels" in c[0][0] for c in self.calls)

    def test_both_failed_adds_label_and_draft(self, tmp_path):
        self._bounced(tmp_path)
        assert self._repair(tmp_path, []) == ["label", "draft"]
        assert self._wrote_label() and self.to_draft.called
        assert self.ev.call_args.kwargs["max_pages"] == 10

    def test_events_before_t_do_not_make_it_deliberate(self, tmp_path):
        self._bounced(tmp_path)
        events = [_ev("ready_for_review", BEFORE), _ev("unlabeled", BEFORE, label="needs-ai")]
        assert self._repair(tmp_path, events) == ["label", "draft"]

    @pytest.mark.parametrize("login", ["hos-worker-hos[bot]", "ScottThurlow"])
    @pytest.mark.parametrize(
        "event", [_ev("ready_for_review", AFTER), _ev("unlabeled", AFTER, label="needs-ai")]
    )
    def test_deliberate_ready_by_any_actor_does_nothing(self, tmp_path, login, event):
        self._bounced(tmp_path)
        event = {**event, "actor": {"login": login}}
        assert self._repair(tmp_path, [event]) == []
        assert not self._wrote_label() and not self.to_draft.called

    def test_unrelated_events_are_not_deliberate(self, tmp_path):
        self._bounced(tmp_path)
        events = [_ev("unlabeled", AFTER, label="other"), _ev("labeled", AFTER, label="needs-ai")]
        assert self._repair(tmp_path, events) == ["label", "draft"]

    def test_events_read_failure_raises_before_any_write(self, tmp_path):
        from scripts.automation.lib.merge_authority import RepairReadError

        self._bounced(tmp_path)

        def boom(*a, **k):
            raise GitHubError("down", 502)

        with pytest.raises(RepairReadError):
            self._repair(tmp_path, boom)
        assert not self._wrote_label() and not self.to_draft.called

    def test_truncated_events_raise_before_any_write(self, tmp_path):
        from scripts.automation.lib.merge_authority import RepairReadError

        self._bounced(tmp_path)

        def truncated(*a, **k):
            raise ghmod.ListTruncatedError("too many")

        with pytest.raises(RepairReadError) as err:
            self._repair(tmp_path, truncated)
        assert isinstance(err.value.__cause__, ghmod.ListTruncatedError)
        assert not self._wrote_label() and not self.to_draft.called

    def test_pr_read_failure_raises(self, tmp_path):
        from scripts.automation.lib.merge_authority import RepairReadError, repair_bounce_finalize

        with patch(f"{MA}._run_gh", side_effect=GitHubError("down", 500)):
            with pytest.raises(RepairReadError):
                repair_bounce_finalize(
                    OWNER, REPO, 1, cid="c", head_sha=HEAD, repo_root=str(tmp_path)
                )

    def test_write_failures_are_best_effort(self, tmp_path):
        from scripts.automation.lib.merge_authority import repair_bounce_finalize

        self._bounced(tmp_path)
        errors = []

        def gh(args, *a, **k):
            if re.search(r"/pulls/\d+$", args[0]):
                return {"draft": False, "labels": []}
            raise GitHubError("label failed")

        with (
            patch(f"{MA}._run_gh", side_effect=gh),
            patch(f"{MA}._convert_pr_to_draft", side_effect=GitHubError("draft failed")),
            patch.object(ghmod, "list_issue_events", return_value=[]),
        ):
            got = repair_bounce_finalize(
                OWNER, REPO, 123, cid="cid-1", head_sha=HEAD, repo_root=str(tmp_path), errors=errors
            )
        assert got == [] and len(errors) == 2

    def test_legacy_event_uses_timestamp_as_t(self, tmp_path):
        from scripts.oversight.lib import audit_log

        audit_log.write_event(
            {
                "event": "pr-bounced",
                "cid": "cid-1",
                "head_sha": HEAD,
                "failures": ["register-missing"],
                "timestamp": "2026-10-31T02:00:00Z",
            },
            root=str(tmp_path),
        )
        before = [_ev("ready_for_review", "2026-10-31T01:59:00Z")]
        after = [_ev("ready_for_review", "2026-10-31T02:00:30Z")]
        assert self._repair(tmp_path, before) == ["label", "draft"]
        assert self._repair(tmp_path, after) == []

    def test_same_head_skip_runs_the_repair(self, tmp_path):
        self._bounced(tmp_path)
        with (
            patch(f"{MA}._run_gh", side_effect=_gh_stub(draft=False, labels=())),
            patch(f"{MA}._convert_pr_to_draft") as to_draft,
            patch.object(ghmod, "list_issue_events", return_value=[]),
            patch(f"{MA}.post_comment") as post,
        ):
            result = _bounce(tmp_path, findings=[_f()], reason_category="MERITS_FINDING")
        post.assert_not_called()
        assert result.skipped and result.finalize_repaired == ["label", "draft"]
        assert to_draft.called

    # Each repair is suppressed independently by its own deliberate event.

    @pytest.mark.parametrize("login", ["hos-worker-hos[bot]", "ScottThurlow"])
    def test_label_repair_skipped_when_needs_ai_was_removed_deliberately(self, tmp_path, login):
        self._bounced(tmp_path)
        events = [{**_ev("unlabeled", AFTER, label="needs-ai"), "actor": {"login": login}}]
        assert self._repair(tmp_path, events, draft=True, labels=()) == []
        assert not self._wrote_label()

    @pytest.mark.parametrize("login", ["hos-worker-hos[bot]", "ScottThurlow"])
    def test_draft_repair_skipped_when_marked_ready_deliberately(self, tmp_path, login):
        self._bounced(tmp_path)
        events = [{**_ev("ready_for_review", AFTER), "actor": {"login": login}}]
        assert self._repair(tmp_path, events, draft=False, labels=("needs-ai",)) == []
        assert not self.to_draft.called

    def test_label_repair_is_not_suppressed_by_a_ready_event(self, tmp_path):
        self._bounced(tmp_path)
        got = self._repair(tmp_path, [_ev("ready_for_review", AFTER)], draft=True, labels=())
        assert got == ["label"]

    def test_draft_repair_is_not_suppressed_by_an_unlabel_event(self, tmp_path):
        self._bounced(tmp_path)
        events = [_ev("unlabeled", AFTER, label="needs-ai")]
        assert self._repair(tmp_path, events, draft=False, labels=("needs-ai",)) == ["draft"]

    def test_single_missing_failed_steps_are_repaired(self, tmp_path):
        self._bounced(tmp_path)
        assert self._repair(tmp_path, [], draft=True, labels=()) == ["label"]
        assert self._repair(tmp_path, [], draft=False, labels=("needs-ai",)) == ["draft"]
        stale = [_ev("ready_for_review", BEFORE), _ev("unlabeled", BEFORE, label="needs-ai")]
        assert self._repair(tmp_path, stale, draft=True, labels=()) == ["label"]
        assert self._repair(tmp_path, stale, draft=False, labels=("needs-ai",)) == ["draft"]

    @pytest.mark.parametrize("draft,labels", [(True, ()), (False, ("needs-ai",))])
    def test_single_missing_read_failure_raises_before_any_write(self, tmp_path, draft, labels):
        from scripts.automation.lib.merge_authority import RepairReadError

        self._bounced(tmp_path)

        def boom(*a, **k):
            raise ghmod.ListTruncatedError("too many")

        with pytest.raises(RepairReadError):
            self._repair(tmp_path, boom, draft=draft, labels=labels)
        assert not self._wrote_label() and not self.to_draft.called

    def test_healthy_state_reads_nothing(self, tmp_path):
        self._bounced(tmp_path)
        assert self._repair(tmp_path, [], draft=True, labels=("needs-ai",)) == []
        self.ev.assert_not_called()
