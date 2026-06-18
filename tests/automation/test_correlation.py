"""
Unit tests for correlation.py — the M1 correctness keystone (ADR-2, R6.1).

These tests verify the three properties that make duplicate-work structurally
impossible:
  1. Determinism: same input → same cid, across URL forms, across instances.
  2. Artifact naming: single owner, derived from cid.
  3. Idempotency precheck: returns the correct ResumeState from mock GitHub data.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from scripts.automation.lib.correlation import (
    COLD_START_TABLE,
    ENVELOPE_CID_MARKER,
    ResumeState,
    _normalize_issue_url,
    already_exists,
    branch_name,
    derive_cid,
    envelope_cid_line,
    pr_title,
)


# ---------------------------------------------------------------------------
# cid determinism (ADR-2) — the load-bearing property
# ---------------------------------------------------------------------------

CANONICAL_URL = "https://github.com/thurlow-research/HumanOversightSystem/issues/254"
ISSUE_NUMBER = 254


def _expected_cid(url: str, n: int) -> str:
    normalized = _normalize_issue_url(url, n)
    payload = f"{normalized}#{n}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class TestDeriveCid:
    def test_deterministic_same_input(self):
        """Calling derive_cid twice with the same input must produce the same cid."""
        cid1 = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        cid2 = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        assert cid1 == cid2

    def test_length_12_hex(self):
        cid = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        assert len(cid) == 12
        assert all(c in "0123456789abcdef" for c in cid)

    def test_trailing_slash_stripped(self):
        """Trailing slash on URL must not change the cid."""
        cid_plain = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        cid_slash = derive_cid(CANONICAL_URL + "/", ISSUE_NUMBER)
        assert cid_plain == cid_slash

    def test_host_case_insensitive(self):
        """Uppercase host must produce the same cid (host is lowercased)."""
        upper_url = CANONICAL_URL.replace("github.com", "GITHUB.COM")
        assert derive_cid(upper_url, ISSUE_NUMBER) == derive_cid(CANONICAL_URL, ISSUE_NUMBER)

    def test_different_issues_different_cids(self):
        cid_254 = derive_cid(CANONICAL_URL, 254)
        cid_255 = derive_cid(
            "https://github.com/thurlow-research/HumanOversightSystem/issues/255", 255
        )
        assert cid_254 != cid_255

    def test_url_without_issue_number_appends_it(self):
        """A base repo URL gets /issues/{n} appended before hashing."""
        base_url = "https://github.com/thurlow-research/HumanOversightSystem"
        cid_base = derive_cid(base_url, 254)
        cid_full = derive_cid(CANONICAL_URL, 254)
        assert cid_base == cid_full

    def test_matches_expected_formula(self):
        """Cross-check against the formula from ADR-2."""
        expected = _expected_cid(CANONICAL_URL, ISSUE_NUMBER)
        assert derive_cid(CANONICAL_URL, ISSUE_NUMBER) == expected


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

class TestNormalizeIssueUrl:
    def test_canonical_unchanged(self):
        result = _normalize_issue_url(CANONICAL_URL, ISSUE_NUMBER)
        assert result == CANONICAL_URL

    def test_trailing_slash_removed(self):
        result = _normalize_issue_url(CANONICAL_URL + "/", ISSUE_NUMBER)
        assert result == CANONICAL_URL

    def test_host_lowercased(self):
        result = _normalize_issue_url(
            "https://GitHub.com/thurlow-research/HumanOversightSystem/issues/254",
            ISSUE_NUMBER,
        )
        assert "github.com" in result
        assert "GitHub.com" not in result

    def test_wrong_issue_number_in_url_replaced(self):
        """If the URL contains a different issue number, it is corrected."""
        wrong_url = "https://github.com/thurlow-research/HumanOversightSystem/issues/999"
        result = _normalize_issue_url(wrong_url, 254)
        assert result.endswith("/issues/254")


# ---------------------------------------------------------------------------
# Artifact naming (single owner — no other module may derive these)
# ---------------------------------------------------------------------------

class TestArtifactNames:
    def test_branch_name_prefix(self):
        cid = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        assert branch_name(cid) == f"hos/auto/{cid}"

    def test_pr_title_contains_cid(self):
        cid = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        title = pr_title(cid, "Fix audit healthcheck")
        assert cid in title
        assert "[AI: hos-worker]" in title
        assert "Fix audit healthcheck" in title

    def test_envelope_cid_line_format(self):
        cid = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
        line = envelope_cid_line(cid)
        assert line.startswith(ENVELOPE_CID_MARKER)
        assert cid in line


# ---------------------------------------------------------------------------
# Idempotency precheck (ResumeState) — using mocked GitHub calls
# ---------------------------------------------------------------------------

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"
CID = derive_cid(CANONICAL_URL, ISSUE_NUMBER)
BRANCH = branch_name(CID)


def _mock_get_branch(return_value):
    return patch(
        "scripts.automation.lib.correlation.get_branch",
        return_value=return_value,
    )


def _mock_list_pulls(return_value):
    return patch(
        "scripts.automation.lib.correlation.list_pulls",
        return_value=return_value,
    )


def _mock_list_comments(return_value):
    return patch(
        "scripts.automation.lib.correlation.list_issue_comments",
        return_value=return_value,
    )


class TestAlreadyExists:
    def test_not_started_no_artifacts(self):
        with (
            _mock_get_branch(None),
            _mock_list_pulls([]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.NOT_STARTED

    def test_claim_present_no_branch(self):
        comment_body = f"some text\n{envelope_cid_line(CID)}\nmore text"
        with (
            _mock_get_branch(None),
            _mock_list_pulls([]),
            _mock_list_comments([{"body": comment_body}]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.CLAIM_PRESENT

    def test_branch_exists_no_pr(self):
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.BRANCH_EXISTS

    def test_pr_exists_open(self):
        pr = {"number": 42, "merged_at": None, "mergeable_state": "unknown"}
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([pr]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.PR_EXISTS

    def test_gates_complete_clean_pr(self):
        pr = {"number": 42, "merged_at": None, "mergeable_state": "clean"}
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([pr]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.GATES_COMPLETE

    def test_merged(self):
        pr = {"number": 42, "merged_at": "2026-06-15T10:00:00Z", "mergeable_state": "clean"}
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([pr]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.MERGED

    def test_merged_beats_gates_complete(self):
        """merged_at presence is the highest-priority state."""
        pr = {"number": 42, "merged_at": "2026-06-15T10:00:00Z", "mergeable_state": "clean"}
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([pr]),
            _mock_list_comments([{"body": envelope_cid_line(CID)}]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.MERGED

    def test_pr_beats_branch(self):
        """A PR's existence overrides a bare branch finding."""
        pr = {"number": 42, "merged_at": None, "mergeable_state": "unknown"}
        with (
            _mock_get_branch({"ref": f"refs/heads/{BRANCH}"}),
            _mock_list_pulls([pr]),
            _mock_list_comments([]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.PR_EXISTS

    def test_claim_envelope_only_finds_matching_cid(self):
        """A comment with a different cid does not match."""
        wrong_cid = "aabbccddeeff"
        assert wrong_cid != CID  # sanity
        comment_body = f"{envelope_cid_line(wrong_cid)}"
        with (
            _mock_get_branch(None),
            _mock_list_pulls([]),
            _mock_list_comments([{"body": comment_body}]),
        ):
            state = already_exists(OWNER, REPO, CID, ISSUE_NUMBER)
        assert state == ResumeState.NOT_STARTED


# ---------------------------------------------------------------------------
# Cold-start table completeness
# ---------------------------------------------------------------------------

class TestColdStartTable:
    def test_all_states_have_entry(self):
        for state in ResumeState:
            assert state in COLD_START_TABLE, f"{state} missing from COLD_START_TABLE"

    def test_entries_are_non_empty_strings(self):
        for state, description in COLD_START_TABLE.items():
            assert isinstance(description, str) and description.strip()
