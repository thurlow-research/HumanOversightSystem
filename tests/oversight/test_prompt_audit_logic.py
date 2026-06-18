"""Tests for scripts/oversight/prompt_audit_logic.py — SPEC-338 / #338.

Exercises the PURE public interface (parse_commit_trailers, the counting half of
compute_stats, the format_* helpers) with plain strings/dicts — no git, no
subprocess, no network (R4 / binding 6). File-touching functions use tmp_path.

A single @pytest.mark.integration parity test (binding 5) runs the real launcher
shell against a fixture git repo and asserts its output matches a direct
reproduction of the legacy counting on the same fixture — the gate that licensed
deleting the bash logic.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "prompt_audit_logic.py"
)
_spec = importlib.util.spec_from_file_location("prompt_audit_logic", _MOD_PATH)
pal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pal)

RS = pal.RECORD_SEP
US = pal.FIELD_SEP
PENDING = pal.PENDING_MARKER


def _rec(hash_, date, subject, body=None):
    """Build one git-log record in the RS/US wire format (leading RS per record)."""
    fields = [hash_, date, subject]
    if body is not None:
        fields.append(body)
    return RS + US.join(fields)


# --------------------------------------------------------------------------- #
# parse_commit_trailers — PURE                                                #
# --------------------------------------------------------------------------- #
def test_empty_input_returns_empty_list():
    assert pal.parse_commit_trailers("") == []
    assert pal.parse_commit_trailers(RS) == []  # leading-sep artifact dropped


def test_single_full_record_extracts_all_keys():
    body = "Some message.\n\nAI-Risk: HIGH\nPrompt-Artifact: prompts/x.md\nAI-Model: claude"
    out = pal.parse_commit_trailers(_rec("abc1234", "2026-06-17", "do a thing", body))
    assert len(out) == 1
    c = out[0]
    assert c["hash"] == "abc1234"
    assert c["date"] == "2026-06-17"
    assert c["subject"] == "do a thing"
    assert c["ai_risk"] == "HIGH"
    assert c["prompt_artifact"] == "prompts/x.md"
    assert c["ai_model"] == "claude"


def test_multiple_records():
    s = (
        _rec("h1", "2026-01-01", "first", "AI-Risk: LOW")
        + _rec("h2", "2026-01-02", "second", "AI-Risk: MEDIUM")
    )
    out = pal.parse_commit_trailers(s)
    assert [c["hash"] for c in out] == ["h1", "h2"]
    assert [c["ai_risk"] for c in out] == ["LOW", "MEDIUM"]


def test_missing_trailers_default_empty():
    out = pal.parse_commit_trailers(_rec("h", "d", "s", "no trailers here"))
    assert out[0]["ai_risk"] == ""
    assert out[0]["prompt_artifact"] == ""
    assert out[0]["ai_model"] == ""


def test_filtered_three_field_record_has_empty_trailers():
    # The --risk pass emits only hash/date/subject (no body field).
    out = pal.parse_commit_trailers(_rec("h", "2026-01-01", "subj"))
    assert out[0]["subject"] == "subj"
    assert out[0]["ai_risk"] == ""


def test_trailer_mid_body_with_newlines():
    body = "line one\nline two\n  AI-Risk: CRITICAL  \nline four"
    out = pal.parse_commit_trailers(_rec("h", "d", "s", body))
    assert out[0]["ai_risk"] == "CRITICAL"  # stripped


def test_custom_separators():
    # Use separators that don't collide with the field content.
    s = "|" + "h" + "~" + "d" + "~" + "s" + "~" + "AI-Risk: LOW"
    out = pal.parse_commit_trailers(s, record_sep="|", field_sep="~")
    assert out[0]["hash"] == "h"
    assert out[0]["ai_risk"] == "LOW"


# --------------------------------------------------------------------------- #
# compute_stats — counting half PURE                                          #
# --------------------------------------------------------------------------- #
def test_compute_stats_counts_total_and_by_risk():
    # Counting mirrors legacy `git log --grep` substring semantics over the whole
    # message (subject + body), matching the bash numbers exactly (R5).
    commits = [
        {"subject": "a", "body": "Prompt-Artifact: prompts/a.md\nAI-Risk: LOW"},
        {"subject": "b", "body": "Prompt-Artifact: prompts/b.md\nAI-Risk: HIGH"},
        {"subject": "c", "body": "AI-Risk: HIGH"},  # AI-Risk only, no Prompt-Artifact
    ]
    stats = pal.compute_stats(commits, prompts_dir=None)
    assert stats["total_commits"] == 2  # only messages containing "Prompt-Artifact:"
    assert stats["by_risk"] == {"LOW": 1, "MEDIUM": 0, "HIGH": 2, "CRITICAL": 0}
    assert stats["prompts_present"] is False
    assert stats["total_artifacts"] is None


def test_compute_stats_counts_prose_mention_like_legacy_grep():
    # Legacy `git log --grep` matches the substring ANYWHERE, including prose.
    # A commit mentioning "Prompt-Artifact:" in prose (no real trailer) is counted
    # by legacy, so compute_stats must count it too for parity.
    commits = [
        {"subject": "doc", "body": "- agent reads Prompt-Artifact: git trailers"},
    ]
    stats = pal.compute_stats(commits, prompts_dir=None)
    assert stats["total_commits"] == 1


def test_compute_stats_empty_commit_list():
    stats = pal.compute_stats([], prompts_dir=None)
    assert stats["total_commits"] == 0
    assert stats["by_risk"] == {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}


def test_compute_stats_file_scan(tmp_path):
    (tmp_path / "a.md").write_text(f"header\n{PENDING}\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("APPROVED here\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("nothing special\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text(f"{PENDING}\n", encoding="utf-8")  # non-md
    stats = pal.compute_stats([], prompts_dir=str(tmp_path))
    assert stats["prompts_present"] is True
    assert stats["total_artifacts"] == 3  # *.md only
    assert stats["pending"] == 2  # a.md + notes.txt (grep -rl is not *.md-only)
    assert stats["approved"] == 1


def test_compute_stats_missing_dir_marks_absent():
    stats = pal.compute_stats([], prompts_dir="/nonexistent/dir/xyz")
    assert stats["prompts_present"] is False


# --------------------------------------------------------------------------- #
# find_pending_artifacts — *.md-only directory scan                           #
# --------------------------------------------------------------------------- #
def test_find_pending_artifacts(tmp_path):
    (tmp_path / "p1.md").write_text(f"{PENDING}\n", encoding="utf-8")
    (tmp_path / "p2.md").write_text("done\n", encoding="utf-8")
    (tmp_path / "p3.txt").write_text(f"{PENDING}\n", encoding="utf-8")  # not md
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "p4.md").write_text(f"{PENDING}\n", encoding="utf-8")
    out = pal.find_pending_artifacts(str(tmp_path))
    assert out == sorted([str(tmp_path / "p1.md"), str(sub / "p4.md")])


def test_find_pending_artifacts_missing_dir():
    assert pal.find_pending_artifacts("/nonexistent/xyz") == []


# --------------------------------------------------------------------------- #
# format helpers — PURE                                                       #
# --------------------------------------------------------------------------- #
def test_format_list_with_and_without_risk():
    commits = [
        {"hash": "h1", "date": "2026-01-01", "subject": "s1", "ai_risk": "HIGH"},
        {"hash": "h2", "date": "2026-01-02", "subject": "s2", "ai_risk": ""},
    ]
    out = pal.format_list(commits, limit=60)
    assert out == "h1 2026-01-01 s1\n  AI-Risk: HIGH\nh2 2026-01-02 s2"


def test_format_list_limit():
    commits = [
        {"hash": f"h{i}", "date": "d", "subject": "s", "ai_risk": ""}
        for i in range(5)
    ]
    out = pal.format_list(commits, limit=2)
    assert out.count("\n") == 1  # two lines, one newline


def test_format_stats_with_prompts():
    stats = {
        "total_commits": 3,
        "by_risk": {"LOW": 1, "MEDIUM": 0, "HIGH": 2, "CRITICAL": 0},
        "prompts_present": True,
        "total_artifacts": 5,
        "pending": 2,
        "approved": 1,
    }
    out = pal.format_stats(stats)
    assert "AI-assisted commits (all time): 3" in out
    assert "  HIGH: 2" in out
    assert "Prompt artifacts: 5" in out
    assert "  Pending review: 2" in out


def test_format_stats_no_prompts():
    stats = {
        "total_commits": 0,
        "by_risk": {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
        "prompts_present": False,
        "total_artifacts": None,
        "pending": None,
        "approved": None,
    }
    assert "No prompts/ directory found." in pal.format_stats(stats)


def test_format_pending():
    out = pal.format_pending(["prompts/a.md", "prompts/b.md"])
    assert "  prompts/a.md" in out
    assert "  2 artifact(s) pending review" in out


# --------------------------------------------------------------------------- #
# Integration parity (binding 5) — real launcher vs legacy reproduction       #
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, subject: str, body: str):
    _git(repo, "commit", "--allow-empty", "-m", subject, "-m", body)


@pytest.mark.integration
def test_stats_parity_with_legacy_counting(tmp_path):
    """Run the real prompt_audit.sh --stats on a fixture repo and assert the
    Python-computed numbers match a direct reproduction of the legacy per-pattern
    git-grep counting (binding 5). This is the parity gate.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    # Commit mix mirroring the divergent real-repo case:
    _commit(repo, "feat one", "Prompt-Artifact: prompts/1.md\nAI-Risk: LOW")
    _commit(repo, "feat two", "Prompt-Artifact: prompts/2.md\nAI-Risk: HIGH")
    _commit(repo, "feat three", "Prompt-Artifact: prompts/3.md")  # no AI-Risk
    _commit(repo, "chore", "AI-Risk: MEDIUM")  # no Prompt-Artifact
    _commit(repo, "docs", "explains the Prompt-Artifact: trailer in prose")  # prose
    _commit(repo, "unrelated", "nothing")

    prompts = repo / "prompts"
    prompts.mkdir()
    (prompts / "1.md").write_text(f"{PENDING}\n", encoding="utf-8")
    (prompts / "2.md").write_text("APPROVED\n", encoding="utf-8")
    (prompts / "3.md").write_text("draft\n", encoding="utf-8")

    script = Path(__file__).resolve().parents[2] / "scripts" / "prompt_audit.sh"
    result = subprocess.run(
        ["bash", str(script), "--stats"],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    out = result.stdout

    # Legacy reproduction: count each grep pattern independently (the old logic).
    def grep_count(*grep_args):
        r = subprocess.run(
            ["git", "log", *grep_args, "--oneline"],
            cwd=repo, check=True, capture_output=True, text=True,
        )
        return len([ln for ln in r.stdout.splitlines() if ln.strip()])

    legacy_total = grep_count("--grep=Prompt-Artifact:")
    assert f"AI-assisted commits (all time): {legacy_total}" in out
    # feat one/two/three (real trailers) + the prose "docs" commit — legacy grep
    # matches the substring anywhere, so the prose mention is counted too.
    assert legacy_total == 4

    for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        legacy = grep_count(f"--grep=AI-Risk: {level}")
        assert f"  {level}: {legacy}" in out

    # File metrics parity.
    assert "Prompt artifacts: 3" in out
    assert "  Pending review: 1" in out
    assert "  Approved:       1" in out
