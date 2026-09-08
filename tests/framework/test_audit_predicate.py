"""Tests for the ADR-035 shared audit-diff predicate (audit_predicate.py).

Covers the §11.1 test plan (TECHNICAL-DESIGN-035): the twelve base cases plus
fixture coverage for the three Revision-2 AD-17 hardening rules (0, 7, 8) and
the AD-17f unified-diff parser regression. Conventions match
tests/framework/test_require_human_approval.py / test_require_tier_ceiling.py:
the module is loaded by file path, functions are called directly, and the
CLI is exercised as a real subprocess (no live gh/network/model anywhere).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "framework" / "audit_predicate.py"
_SPEC = importlib.util.spec_from_file_location("audit_predicate", _MODULE_PATH)
ap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ap)

ALLOWLIST = ap.load_allowlist(ap.ALLOWLIST_FILE)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fr(
    filename: str, status: str = "added", additions: int = 0, deletions: int = 0, patch=None
) -> dict:
    return {
        "filename": filename,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "patch": patch,
    }


def _jsonl_patch(lines: list[str]) -> str:
    """A synthetic unified-diff patch whose hunk adds each of `lines` as a
    JSONL append (one '+'-prefixed raw line each)."""
    header = f"@@ -0,0 +1,{len(lines)} @@"
    body = "\n".join("+" + line for line in lines)
    return header + "\n" + body


def _json_object_patch(obj) -> tuple[str, int]:
    """A synthetic patch adding a pretty-printed JSON object across multiple
    physical lines (the audit/log/** write-once shape). Returns (patch, N)
    where N is the number of added lines, for callers that need to set
    `additions` consistently (rule 8)."""
    text = json.dumps(obj, indent=2)
    lines = text.splitlines()
    header = f"@@ -0,0 +1,{len(lines)} @@"
    body = "\n".join("+" + line for line in lines)
    return header + "\n" + body, len(lines)


# ---------------------------------------------------------------------------
# §11.1 case 1 — empty diff
# ---------------------------------------------------------------------------


def test_empty_diff():
    verdict = ap.classify_audit_diff([], ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "empty-diff"


# ---------------------------------------------------------------------------
# §11.1 case 2 — non-allowlisted path (AD-4 barrier 1)
# ---------------------------------------------------------------------------


def test_non_allowlisted_path_disqualifies():
    patch = _jsonl_patch(['{"event": "x"}'])
    files = [
        _fr(
            "scripts/framework/require_overseer_approval.py",
            status="modified",
            additions=1,
            patch=patch,
        )
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "non-allowlisted-path:scripts/framework/require_overseer_approval.py"


# ---------------------------------------------------------------------------
# §11.1 case 3 — first-creation (status == "added") qualifies (AF-2)
# ---------------------------------------------------------------------------


def test_first_creation_added_status_qualifies():
    patch = _jsonl_patch(['{"event": "created"}'])
    files = [_fr("audit/oversight-log.jsonl", status="added", additions=1, patch=patch)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is True


# ---------------------------------------------------------------------------
# §11.1 case 4 — modified, additions-only, well-formed appends
# ---------------------------------------------------------------------------


def test_modified_additions_only_qualifies():
    patch = _jsonl_patch(['{"event": "a"}', '{"event": "b"}'])
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=2, deletions=0, patch=patch)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is True
    assert "audit-only additions" in verdict.reason


# ---------------------------------------------------------------------------
# §11.1 case 5 — deletions present disqualifies (FR7)
# ---------------------------------------------------------------------------


def test_deletion_present_disqualifies():
    patch = _jsonl_patch(['{"event": "a"}'])
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=1, deletions=1, patch=patch)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "deletion-present:audit/oversight-log.jsonl"


# ---------------------------------------------------------------------------
# §11.1 case 6 — removed / renamed / copied status disqualifies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["removed", "renamed", "copied"])
def test_disqualifying_status(status):
    files = [_fr("audit/oversight-log.jsonl", status=status, additions=0, deletions=0, patch=None)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == f"disqualifying-status:{status}:audit/oversight-log.jsonl"


# ---------------------------------------------------------------------------
# §11.1 case 7 — patch unavailable with additions > 0 (fail-closed)
# ---------------------------------------------------------------------------


def test_patch_unavailable_disqualifies():
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=5, deletions=0, patch=None)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "patch-unavailable:audit/oversight-log.jsonl"


# ---------------------------------------------------------------------------
# §11.1 case 8 — malformed .jsonl added line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_line", ["[1, 2, 3]", '"just a string"', "not json at all"])
def test_malformed_jsonl_disqualifies(bad_line):
    patch = _jsonl_patch([bad_line])
    files = [_fr("audit/oversight-log.jsonl", status="modified", additions=1, patch=patch)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason.startswith("malformed-jsonl:audit/oversight-log.jsonl:L1")


# ---------------------------------------------------------------------------
# §11.1 case 9 — audit/log/** write-once JSON: valid qualifies, malformed does not
# ---------------------------------------------------------------------------


def test_audit_log_write_once_valid_qualifies():
    patch, n = _json_object_patch({"event": "cycle-start", "id": "abc123"})
    files = [_fr("audit/log/2026/09/evt.json", status="added", additions=n, patch=patch)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is True


def test_audit_log_write_once_malformed_disqualifies():
    patch = _jsonl_patch(["{not valid json"])
    files = [_fr("audit/log/2026/09/evt.json", status="added", additions=1, patch=patch)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "malformed-audit-log-json:audit/log/2026/09/evt.json"


# ---------------------------------------------------------------------------
# §11.1 case 10 — allowlisted path with no registered validator (AD-6 fail-closed)
# ---------------------------------------------------------------------------


def test_no_registered_validator_disqualifies():
    custom_allowlist = ["audit/other/**"]
    patch = _jsonl_patch(["some added text"])
    files = [_fr("audit/other/data.txt", status="added", additions=1, patch=patch)]
    verdict = ap.classify_audit_diff(files, custom_allowlist, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "no-registered-validator:audit/other/data.txt"


# ---------------------------------------------------------------------------
# §11.1 case 11 — malformed/non-audit diffs are withheld (False), never approved
# ---------------------------------------------------------------------------


def _negative_fixtures():
    jsonl_bad_patch = _jsonl_patch(["not json"])
    audit_log_bad_patch = _jsonl_patch(["{not valid json"])
    return [
        # case 2: non-allowlisted path
        (
            [
                _fr(
                    "scripts/framework/require_overseer_approval.py",
                    status="modified",
                    additions=1,
                    patch=_jsonl_patch(['{"event": "x"}']),
                )
            ],
            ALLOWLIST,
        ),
        # case 5: deletion present
        (
            [
                _fr(
                    "audit/oversight-log.jsonl",
                    status="modified",
                    additions=1,
                    deletions=1,
                    patch=_jsonl_patch(['{"event": "a"}']),
                )
            ],
            ALLOWLIST,
        ),
        # case 6: disqualifying status
        ([_fr("audit/oversight-log.jsonl", status="removed")], ALLOWLIST),
        # case 7: patch unavailable
        ([_fr("audit/oversight-log.jsonl", status="modified", additions=5, patch=None)], ALLOWLIST),
        # case 8: malformed jsonl
        (
            [
                _fr(
                    "audit/oversight-log.jsonl",
                    status="modified",
                    additions=1,
                    patch=jsonl_bad_patch,
                )
            ],
            ALLOWLIST,
        ),
        # case 8b: malformed audit/log json
        (
            [
                _fr(
                    "audit/log/2026/09/evt.json",
                    status="added",
                    additions=1,
                    patch=audit_log_bad_patch,
                )
            ],
            ALLOWLIST,
        ),
        # case 10: no registered validator
        (
            [_fr("audit/other/data.txt", status="added", additions=1, patch=_jsonl_patch(["x"]))],
            ["audit/other/**"],
        ),
    ]


@pytest.mark.parametrize("files,allowlist", _negative_fixtures())
def test_negative_cases_are_withheld_never_approved(files, allowlist):
    verdict = ap.classify_audit_diff(files, allowlist, "main")
    assert verdict.qualifies is False


# ---------------------------------------------------------------------------
# §11.1 case 12 — CLI: valid JSON output + exit code contract
# ---------------------------------------------------------------------------


def test_cli_classify_emits_json_and_exit_zero(tmp_path):
    patch = _jsonl_patch(['{"event": "a"}'])
    files = [_fr("audit/oversight-log.jsonl", status="modified", additions=1, patch=patch)]
    files_path = tmp_path / "files.json"
    files_path.write_text(json.dumps(files))

    result = subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            "classify",
            "--files",
            str(files_path),
            "--allowlist",
            str(ap.ALLOWLIST_FILE),
            "--base-ref",
            "main",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["qualifies"] is True


def test_cli_classify_exits_two_on_invalid_json(tmp_path):
    files_path = tmp_path / "files.json"
    files_path.write_text("not json")

    result = subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            "classify",
            "--files",
            str(files_path),
            "--allowlist",
            str(ap.ALLOWLIST_FILE),
            "--base-ref",
            "main",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_cli_missing_required_arg_exits_two(tmp_path):
    files_path = tmp_path / "files.json"
    files_path.write_text("[]")

    # --base-ref omitted: a usage error, handled by argparse's own exit(2).
    result = subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            "classify",
            "--files",
            str(files_path),
            "--allowlist",
            str(ap.ALLOWLIST_FILE),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Revision 2 (AD-17) — rule 0: wrong target branch
# ---------------------------------------------------------------------------


def test_rule0_wrong_target_branch_disqualifies():
    patch = _jsonl_patch(['{"event": "a"}'])
    files = [_fr("audit/oversight-log.jsonl", status="modified", additions=1, patch=patch)]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "release/v0.7")
    assert verdict.qualifies is False
    assert verdict.reason == "wrong-target-branch:release/v0.7"


def test_rule0_empty_base_ref_disqualifies():
    files = [
        _fr(
            "audit/oversight-log.jsonl",
            status="modified",
            additions=1,
            patch=_jsonl_patch(['{"a":1}']),
        )
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "")
    assert verdict.qualifies is False
    assert verdict.reason.startswith("wrong-target-branch:")


def test_rule0_custom_protected_branch():
    patch = _jsonl_patch(['{"event": "a"}'])
    files = [_fr("audit/oversight-log.jsonl", status="modified", additions=1, patch=patch)]
    # A consumer whose protected branch differs from "main" — the check only
    # narrows (it can never widen qualification onto an unprotected branch).
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "trunk", protected_branch="trunk")
    assert verdict.qualifies is True
    verdict2 = ap.classify_audit_diff(files, ALLOWLIST, "main", protected_branch="trunk")
    assert verdict2.qualifies is False
    assert verdict2.reason == "wrong-target-branch:main"


# ---------------------------------------------------------------------------
# Revision 2 (AD-17) — rule 7: zero-content change
# ---------------------------------------------------------------------------


def test_rule7_zero_content_change_disqualifies():
    # additions == 0, deletions == 0, no patch: a mode/symlink/type-only
    # change on an existing allowlisted file. Nothing to validate under
    # rule 6 (trivially passes), so rule 7 is the only thing that catches it.
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=0, deletions=0, patch=None)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "no-content-addition:audit/oversight-log.jsonl"


# ---------------------------------------------------------------------------
# Revision 2 (AD-17) — rule 8: patch-truncation mismatch
# ---------------------------------------------------------------------------


def test_rule8_patch_truncation_mismatch_disqualifies():
    # files-API says 5 lines were added, but the visible patch only shows 3
    # well-formed lines — the classic GitHub large-file truncation case.
    patch = _jsonl_patch(['{"event": "a"}', '{"event": "b"}', '{"event": "c"}'])
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=5, deletions=0, patch=patch)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason == "patch-truncated:audit/oversight-log.jsonl"


def test_rule8_matching_counts_qualifies():
    patch = _jsonl_patch(['{"event": "a"}', '{"event": "b"}'])
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=2, deletions=0, patch=patch)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is True


# ---------------------------------------------------------------------------
# AD-17f — corrected stateful unified-diff hunk parser
# ---------------------------------------------------------------------------


def test_extract_added_lines_does_not_skip_content_starting_with_plus_plus_plus():
    """Direct parser-level regression: an added line whose raw content
    (after the single diff-marker '+' is stripped) itself begins with '++'
    — making the full raw diff line read '+++...' — must still be extracted
    as a legitimate added line, not mistaken for a `+++ b/file` header."""
    patch = "@@ -0,0 +1,2 @@\n" + '+{"event": "a"}\n' + "+++not-a-header-this-is-data"
    added = ap.extract_added_lines(patch)
    assert added == ['{"event": "a"}', "++not-a-header-this-is-data"]


def test_ad17f_regression_malformed_plus_plus_plus_line_is_caught_not_skipped():
    """Integration-level regression (§11.1 AD-17f fixture): a well-formed
    JSONL append whose SECOND added line raw-reads '+++...' (and is not
    valid JSON) must be caught as malformed — not silently dropped from
    validation the way the naive `startswith('+++')` filter would drop it,
    which would have let the diff wrongly qualify (fail-open)."""
    patch = (
        "@@ -0,0 +1,2 @@\n"
        + '+{"event": "well-formed"}\n'
        + "+++this-looks-like-a-header-but-is-a-malformed-added-line"
    )
    files = [
        _fr("audit/oversight-log.jsonl", status="modified", additions=2, deletions=0, patch=patch)
    ]
    verdict = ap.classify_audit_diff(files, ALLOWLIST, "main")
    assert verdict.qualifies is False
    assert verdict.reason.startswith("malformed-jsonl:audit/oversight-log.jsonl:L2")
