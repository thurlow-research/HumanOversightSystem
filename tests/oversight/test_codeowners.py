"""Tests for codeowners.py — SPEC-303b CODEOWNERS-derived HUMAN_REQUIRED gate.

Covers acceptance criteria AC-1..AC-9 and the architect bindings B1..B5.
Pure unit tests — no git, no gh, no network. CODEOWNERS files are written to a
tmp_path repo root.
"""
import pytest

from codeowners import (
    DEFAULT_BOT_ACCOUNTS,
    check_pr_files,
    get_owners_for_path,
    glob_to_regex,
    load_codeowners,
    parse_codeowners,
    requires_human_approval,
)

BOTS = {"HOSOversightTutelare", "HOSWorkerTutelare"}


# ── load_codeowners — file location priority (§2.1) ──────────────────────────


class TestLoadCodeowners:
    def test_none_when_absent(self, tmp_path):
        assert load_codeowners(tmp_path) is None

    def test_github_location_preferred(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "CODEOWNERS").write_text("/a @gh\n")
        (tmp_path / "CODEOWNERS").write_text("/a @root\n")
        assert "@gh" in load_codeowners(tmp_path)

    def test_root_fallback(self, tmp_path):
        (tmp_path / "CODEOWNERS").write_text("/a @root\n")
        assert "@root" in load_codeowners(tmp_path)

    def test_docs_fallback(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "CODEOWNERS").write_text("/a @docs\n")
        assert "@docs" in load_codeowners(tmp_path)

    def test_root_beats_docs(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "CODEOWNERS").write_text("/a @root\n")
        (tmp_path / "docs" / "CODEOWNERS").write_text("/a @docs\n")
        assert "@root" in load_codeowners(tmp_path)


# ── parse_codeowners (§2.2) ──────────────────────────────────────────────────


class TestParse:
    def test_basic(self):
        entries = parse_codeowners("/contract/ @ScottThurlow\n")
        assert entries == [("/contract/", ["@ScottThurlow"])]

    def test_skips_comments_and_blanks(self):
        text = "# header\n\n/a @u1\n   \n# mid\n/b @u2\n"
        assert parse_codeowners(text) == [("/a", ["@u1"]), ("/b", ["@u2"])]

    def test_multiple_owners(self):
        entries = parse_codeowners("/a @u1 @org/team @bot\n")
        assert entries == [("/a", ["@u1", "@org/team", "@bot"])]

    def test_order_preserved(self):
        entries = parse_codeowners("/a @first\n/a @second\n")
        assert entries == [("/a", ["@first"]), ("/a", ["@second"])]

    def test_pattern_with_zero_owners_retained(self):
        # ownership-clearing line
        assert parse_codeowners("/a\n") == [("/a", [])]


# ── glob_to_regex (B4 / §3.1) ────────────────────────────────────────────────


class TestGlobToRegex:
    def test_directory_pattern_matches_nested(self):
        rx = glob_to_regex("/contract/")
        assert rx.match("contract/OVERSIGHT-CONTRACT.md")
        assert rx.match("contract/sub/deep.md")

    def test_directory_pattern_no_match_sibling(self):
        rx = glob_to_regex("/contract/")
        assert not rx.match("contracts.md")

    def test_leading_slash_stripped(self):
        assert glob_to_regex("/docs/x.md").match("docs/x.md")

    def test_single_star_one_segment(self):
        rx = glob_to_regex("/src/*.py")
        assert rx.match("src/a.py")
        assert not rx.match("src/sub/a.py")

    def test_double_star_cross_segment(self):
        rx = glob_to_regex("/src/**")
        assert rx.match("src/sub/deep/a.py")

    def test_bare_name_matches_any_depth(self):
        rx = glob_to_regex("build")
        assert rx.match("build")
        assert rx.match("sub/dir/build")


# ── get_owners_for_path — last-match-wins (§3.1) ─────────────────────────────


class TestGetOwners:
    def test_no_match_empty(self):
        entries = parse_codeowners("/a @u\n")
        assert get_owners_for_path(entries, "b/file.txt") == set()

    def test_match(self):
        entries = parse_codeowners("/contract/ @ScottThurlow\n")
        assert get_owners_for_path(entries, "contract/x.md") == {"@ScottThurlow"}

    def test_last_match_wins(self):
        entries = parse_codeowners("/docs/ @general\n/docs/specs/ @owner\n")
        assert get_owners_for_path(entries, "docs/specs/s.md") == {"@owner"}

    def test_clearing_entry_yields_empty(self):
        entries = parse_codeowners("/docs/ @owner\n/docs/public/\n")
        assert get_owners_for_path(entries, "docs/public/p.md") == set()

    def test_leading_slash_on_path_tolerated(self):
        entries = parse_codeowners("/contract/ @u\n")
        assert get_owners_for_path(entries, "/contract/x.md") == {"@u"}


# ── requires_human_approval (§3.2) ───────────────────────────────────────────


class TestRequiresHumanApproval:
    def test_no_entry(self):  # AC-1
        entries = parse_codeowners("/a @u\n")
        req, reason = requires_human_approval("b/x.txt", entries, BOTS)
        assert req is False
        assert reason == "no CODEOWNERS entry"

    def test_human_owner(self):  # AC-2
        entries = parse_codeowners("/contract/ @ScottThurlow\n")
        req, reason = requires_human_approval("contract/x.md", entries, BOTS)
        assert req is True
        assert reason == "human CODEOWNERS owner: @ScottThurlow"

    def test_bot_only(self):  # AC-3
        entries = parse_codeowners("/auto/ @HOSWorkerTutelare\n")
        req, reason = requires_human_approval("auto/x.txt", entries, BOTS)
        assert req is False
        assert reason == "bot-only CODEOWNERS entry"

    def test_team_owner(self):  # AC-9 / B1
        entries = parse_codeowners("/infra/ @org/platform\n")
        req, reason = requires_human_approval("infra/x.tf", entries, BOTS)
        assert req is True
        assert reason == "team-owned path: @org/platform"

    def test_team_checked_before_human_and_bot(self):
        # mixed bot + team → team gate fires
        entries = parse_codeowners("/x/ @HOSWorkerTutelare @org/team\n")
        req, reason = requires_human_approval("x/f", entries, BOTS)
        assert req is True
        assert reason.startswith("team-owned path:")

    def test_mixed_human_and_bot_gates_on_human(self):
        entries = parse_codeowners("/x/ @HOSWorkerTutelare @alice\n")
        req, reason = requires_human_approval("x/f", entries, BOTS)
        assert req is True
        assert reason == "human CODEOWNERS owner: @alice"

    def test_email_owner_is_human(self):
        entries = parse_codeowners("/x/ dev@example.com\n")
        req, reason = requires_human_approval("x/f", entries, BOTS)
        assert req is True
        assert "human CODEOWNERS owner" in reason

    def test_empty_bot_set_treats_all_as_human(self):
        # AC-6 degradation: no known bots → every owner is human
        entries = parse_codeowners("/x/ @HOSWorkerTutelare\n")
        req, _ = requires_human_approval("x/f", entries, set())
        assert req is True


# ── check_pr_files (§3.3) ────────────────────────────────────────────────────


def _write_codeowners(tmp_path, text):
    (tmp_path / ".github").mkdir(exist_ok=True)
    (tmp_path / ".github" / "CODEOWNERS").write_text(text)


class TestCheckPrFiles:
    def test_no_codeowners_file(self, tmp_path):  # AC-5
        req, matched, reason = check_pr_files(["a.txt"], tmp_path, BOTS)
        assert req is False
        assert matched == []
        assert reason == "no CODEOWNERS file"

    def test_non_codeowners_path(self, tmp_path):  # AC-1
        _write_codeowners(tmp_path, "/contract/ @ScottThurlow\n")
        req, matched, _ = check_pr_files(["README.md"], tmp_path, BOTS)
        assert req is False
        assert matched == []

    def test_human_owned_match(self, tmp_path):  # AC-2 / AC-7
        _write_codeowners(tmp_path, "/contract/ @ScottThurlow\n")
        req, matched, reason = check_pr_files(
            ["contract/OVERSIGHT-CONTRACT.md", "README.md"], tmp_path, BOTS
        )
        assert req is True
        assert matched == ["contract/OVERSIGHT-CONTRACT.md"]
        # AC-7: reason names triggering file + owning entry
        assert "contract/OVERSIGHT-CONTRACT.md" in reason
        assert "@ScottThurlow" in reason

    def test_bot_only_not_flagged(self, tmp_path):  # AC-3
        _write_codeowners(tmp_path, "/auto/ @HOSWorkerTutelare\n")
        req, matched, _ = check_pr_files(["auto/x.txt"], tmp_path, BOTS)
        assert req is False
        assert matched == []

    def test_team_owned_match(self, tmp_path):  # AC-9
        _write_codeowners(tmp_path, "/infra/ @org/platform\n")
        req, matched, reason = check_pr_files(["infra/main.tf"], tmp_path, BOTS)
        assert req is True
        assert matched == ["infra/main.tf"]
        assert "@org/platform" in reason

    def test_blank_entries_ignored(self, tmp_path):
        _write_codeowners(tmp_path, "/contract/ @alice\n")
        req, matched, _ = check_pr_files(["contract/x", "", "  "], tmp_path, BOTS)
        assert matched == ["contract/x"]

    def test_bot_accounts_from_env_default(self, tmp_path, monkeypatch):  # AC-6
        monkeypatch.delenv("BOT_ACCOUNTS", raising=False)
        _write_codeowners(tmp_path, "/auto/ @HOSWorkerTutelare\n")
        # default bots include HOSWorkerTutelare → bot-only → not flagged
        req, matched, _ = check_pr_files(["auto/x"], tmp_path, bot_accounts=None)
        assert req is False
        assert set(DEFAULT_BOT_ACCOUNTS) == BOTS

    def test_bot_accounts_from_env_override(self, tmp_path, monkeypatch):  # AC-6
        monkeypatch.setenv("BOT_ACCOUNTS", "somebot")
        _write_codeowners(tmp_path, "/auto/ @HOSWorkerTutelare\n")
        # HOSWorkerTutelare is no longer a bot → treated as human → flagged
        req, _, _ = check_pr_files(["auto/x"], tmp_path, bot_accounts=None)
        assert req is True

    def test_reread_each_call_no_cache(self, tmp_path):  # B3
        _write_codeowners(tmp_path, "/x/ @HOSWorkerTutelare\n")
        req1, _, _ = check_pr_files(["x/f"], tmp_path, BOTS)
        assert req1 is False
        # mutate CODEOWNERS between calls — must be re-read
        _write_codeowners(tmp_path, "/x/ @alice\n")
        req2, _, _ = check_pr_files(["x/f"], tmp_path, BOTS)
        assert req2 is True

    def test_protected_surface_path_also_human_owned(self, tmp_path):  # AC-4
        # A path that is both on a (hypothetical) protected surface and CODEOWNERS-human
        # owned: this gate fires independently and returns a single verdict.
        _write_codeowners(tmp_path, "/scripts/framework/ @ScottThurlow\n")
        req, matched, _ = check_pr_files(
            ["scripts/framework/machine-accounts.env"], tmp_path, BOTS
        )
        assert req is True
        assert matched == ["scripts/framework/machine-accounts.env"]
