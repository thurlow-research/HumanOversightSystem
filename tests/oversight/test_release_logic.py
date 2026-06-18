"""Tests for scripts/oversight/release_logic.py — release-cut logic (SPEC-335).

These exercise the public interface (bump_version, check_authored_notes,
verify_assets_present) with synthetic inputs / temp files — no subprocess, network,
git, gh, or live release run (architect binding 6).

Coverage:
  AC1 — patch/minor/major bump from a well-formed tag.
  AC2 — absent/empty latest tag → v0.0.0 base.
  AC3 — pre-release suffix stripped (the coercion-bug correction).
  AC4 — bad bump type raises a named exception.
  AC5 — authored-notes gate (>=5 non-blank, <5, non-existent).
  AC6 — asset verification (one missing, all present).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "release_logic.py"
)
_spec = importlib.util.spec_from_file_location("release_logic", _MOD_PATH)
release_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_logic)

bump_version = release_logic.bump_version
check_authored_notes = release_logic.check_authored_notes
verify_assets_present = release_logic.verify_assets_present


# --------------------------------------------------------------------------- #
# R1 — bump_version                                                          #
# --------------------------------------------------------------------------- #
def test_ac1_patch_minor_major_from_well_formed_tag():
    assert bump_version("v0.3.2", "patch") == "v0.3.3"
    assert bump_version("v0.3.2", "minor") == "v0.4.0"
    assert bump_version("v0.3.2", "major") == "v1.0.0"


def test_ac2_empty_and_zero_tag():
    assert bump_version("", "patch") == "v0.0.1"
    assert bump_version("v0.0.0", "minor") == "v0.1.0"


def test_ac2_whitespace_tag_treated_as_zero():
    assert bump_version("   ", "patch") == "v0.0.1"


def test_ac3_prerelease_suffix_stripped():
    # The corrected mechanism: strip "-rc1", parse clean fields, increment.
    assert bump_version("v0.3.0-rc1", "patch") == "v0.3.1"
    # And NOT the path that would land on the wrong field via coercion.
    assert bump_version("v0.3.0-rc1", "minor") == "v0.4.0"
    assert bump_version("v0.3.0-rc1", "major") == "v1.0.0"


def test_ac4_bad_bump_type_raises():
    with pytest.raises(ValueError):
        bump_version("v0.3.0", "hotfix")


def test_bump_type_case_insensitive():
    assert bump_version("v0.3.2", "Patch") == "v0.3.3"
    assert bump_version("v0.3.2", "MINOR") == "v0.4.0"
    assert bump_version("v0.3.2", "  Major  ") == "v1.0.0"


def test_unparseable_tag_raises():
    for bad in ("garbage", "v1.2", "v1.2.3.4", "1.2", "vx.y.z"):
        with pytest.raises(ValueError):
            bump_version(bad, "patch")


def test_no_leading_v_accepted():
    # _SEMVER_RE makes the leading v optional; output is always normalized with v.
    assert bump_version("0.3.2", "patch") == "v0.3.3"


# --------------------------------------------------------------------------- #
# R2 — check_authored_notes                                                  #
# --------------------------------------------------------------------------- #
def test_ac5_five_nonblank_plus_blank_passes(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("a\nb\n\nc\nd\n\ne\n")  # 5 non-blank, 2 blank
    assert check_authored_notes(str(p)) is True


def test_ac5_four_nonblank_fails(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("a\nb\nc\nd\n")  # 4 non-blank
    assert check_authored_notes(str(p)) is False


def test_ac5_nonexistent_path_fails(tmp_path):
    assert check_authored_notes(str(tmp_path / "nope.md")) is False


def test_empty_file_fails(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("")
    assert check_authored_notes(str(p)) is False


def test_only_blank_lines_fails(tmp_path):
    p = tmp_path / "blanks.md"
    p.write_text("\n   \n\t\n\n")
    assert check_authored_notes(str(p)) is False


def test_custom_min_lines(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("a\nb\nc\n")  # 3 non-blank
    assert check_authored_notes(str(p), min_lines=3) is True
    assert check_authored_notes(str(p), min_lines=4) is False


def test_exactly_min_lines_passes(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("a\nb\nc\nd\ne\n")  # exactly 5
    assert check_authored_notes(str(p)) is True


# --------------------------------------------------------------------------- #
# R3 — verify_assets_present                                                 #
# --------------------------------------------------------------------------- #
def test_ac6_one_missing():
    assert verify_assets_present(
        ["hos_install.sh", "SHA256SUMS"],
        ["hos_install.sh", "hos_bootstrap.sh", "SHA256SUMS"],
    ) == ["hos_bootstrap.sh"]


def test_ac6_all_present():
    assert verify_assets_present(["a", "b", "c"], ["a", "b", "c"]) == []


def test_empty_uploaded_returns_all_expected_in_order():
    assert verify_assets_present([], ["a", "b", "c"]) == ["a", "b", "c"]


def test_missing_order_follows_expected():
    assert verify_assets_present(["b"], ["a", "b", "c"]) == ["a", "c"]


def test_exact_equality_not_substring():
    # A substring match would wrongly treat "hos_install" as present.
    assert verify_assets_present(["hos_install"], ["hos_install.sh"]) == [
        "hos_install.sh"
    ]
