"""Tests for the pure three-way merge decider (regions.merge_region).

Covers the binding decision table from docs/v0.3.0/TECHNICAL-DESIGN.md §4.2 and
spec docs/specs/v0.3.0-base-agents-spec.md §5 + §11a/D9:

  - rows 1-4 (template-side): KEEP / REFRESH / KEEP(convergent) / HARDSTOP
  - rows 5-6 (removed=True, manifest-side sweep): DROP / HARDSTOP
  - PROJECT → SKIP_PROJECT, short-circuiting before any sha comparison
  - base_sha is None → routed as base != disk (assume edited / unknown provenance)
  - --squash: HARDSTOP→REFRESH (row 4) and HARDSTOP→DROP (row 6)
  - a parametrized matrix so the whole table is visible at a glance
  - purity: same inputs → same output, no side effects
  - explicit regression guards: row 3 (convergent edit) must NOT clobber; row 5
    (unedited removed) must DROP, never KEEP.

regions is importable bare because tests/conftest.py puts the validators dir on
sys.path (same pattern as the other validator tests).
"""

import pytest
from regions import Action, merge_region

# Distinct sentinel shas. Real shas are 64-char lowercase hex; the decider only
# compares for equality, so short distinct strings exercise the logic exactly.
A = "a" * 64  # "base"
B = "b" * 64  # a differing value
C = "c" * 64  # a third differing value


# --------------------------------------------------------------------------- #
# rows 1-4: template-side three-way (non-removed, non-PROJECT)
# --------------------------------------------------------------------------- #


def test_row1_unedited_disk_matches_incoming_keep():
    # base == disk (unedited) & disk == incoming → KEEP (HOS made no change).
    assert merge_region("CORE", base_sha=A, disk_sha=A, incoming=A) == Action.KEEP


def test_row2_unedited_hos_has_new_version_refresh():
    # base == disk (unedited) & disk != incoming → REFRESH (take HOS's new body).
    assert merge_region("CORE", base_sha=A, disk_sha=A, incoming=B) == Action.REFRESH


def test_row3_convergent_edit_keep_not_clobber():
    # base != disk (consumer-edited) & disk == incoming → KEEP (convergent edit).
    # REGRESSION GUARD: this must NOT be a REFRESH/clobber — the consumer edited
    # the region to exactly what HOS now ships; rewriting would be a needless
    # write and the naïve two-way check's bug.
    result = merge_region("PACK:django", base_sha=A, disk_sha=B, incoming=B)
    assert result == Action.KEEP
    assert result != Action.REFRESH
    assert result != Action.HARDSTOP


def test_row4_genuine_drift_hardstop():
    # base != disk (edited) & disk != incoming → HARDSTOP (no --squash).
    assert merge_region("CORE", base_sha=A, disk_sha=B, incoming=C) == Action.HARDSTOP


def test_row4_genuine_drift_squash_refresh():
    # row 4 with --squash → REFRESH (take HOS's complete version).
    assert merge_region("CORE", base_sha=A, disk_sha=B, incoming=C, squash=True) == Action.REFRESH


# --------------------------------------------------------------------------- #
# rows 5-6: removed-region sweep (removed=True) — D9
# --------------------------------------------------------------------------- #


def test_row5_unedited_removed_drop_not_keep():
    # removed & base == disk (unedited) → DROP (cumulative-faithfulness).
    # REGRESSION GUARD: an unedited removed region must DROP, never KEEP — KEEPing
    # would leave a region HOS retired, breaking the "upgrade reflects HOS's
    # absences too" invariant (§5a).
    result = merge_region("CORE", base_sha=A, disk_sha=A, incoming=B, removed=True)
    assert result == Action.DROP
    assert result != Action.KEEP


def test_row6_edited_removed_hardstop():
    # removed & base != disk (edited) → HARDSTOP (no --squash/--prune).
    assert (
        merge_region("PACK:django", base_sha=A, disk_sha=B, incoming=C, removed=True)
        == Action.HARDSTOP
    )


def test_row6_edited_removed_squash_drop():
    # row 6 with --squash → DROP (explicit consent to drop the edit).
    assert (
        merge_region("CORE", base_sha=A, disk_sha=B, incoming=C, removed=True, squash=True)
        == Action.DROP
    )


# `incoming` is irrelevant in the removed sweep — only base-vs-disk decides.
def test_removed_ignores_incoming():
    # Same base/disk, wildly different incoming values → same DROP decision.
    assert merge_region("CORE", base_sha=A, disk_sha=A, incoming=B, removed=True) == Action.DROP
    assert merge_region("CORE", base_sha=A, disk_sha=A, incoming=C, removed=True) == Action.DROP
    # Non-vacuous guard (review): incoming == disk must NOT leak a row-1/2 read
    # into the removed sweep. unedited → DROP, edited → HARDSTOP, even when
    # disk == incoming.
    assert (
        merge_region("CORE", base_sha=A, disk_sha=A, incoming=A, removed=True) == Action.DROP
    )  # row 5, disk==incoming
    assert (
        merge_region("CORE", base_sha=A, disk_sha=B, incoming=B, removed=True) == Action.HARDSTOP
    )  # row 6, disk==incoming
    # None base + removed + disk==incoming must still HARDSTOP (assume-edited).
    assert (
        merge_region("CORE", base_sha=None, disk_sha=A, incoming=A, removed=True) == Action.HARDSTOP
    )


# --------------------------------------------------------------------------- #
# PROJECT short-circuit (TD §4.4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "base,disk,incoming",
    [
        (A, A, A),  # would otherwise be KEEP
        (A, A, B),  # would otherwise be REFRESH
        (A, B, C),  # would otherwise be HARDSTOP
        (None, B, C),  # None base
    ],
)
def test_project_always_skip(base, disk, incoming):
    # PROJECT is never compared/written regardless of shas, squash, or removed.
    assert merge_region("PROJECT", base, disk, incoming) == Action.SKIP_PROJECT
    assert merge_region("PROJECT", base, disk, incoming, squash=True) == Action.SKIP_PROJECT
    assert merge_region("PROJECT", base, disk, incoming, removed=True) == Action.SKIP_PROJECT
    assert (
        merge_region("PROJECT", base, disk, incoming, squash=True, removed=True)
        == Action.SKIP_PROJECT
    )


# --------------------------------------------------------------------------- #
# base_sha is None → treated as base != disk (TD §4.2 note)
# --------------------------------------------------------------------------- #


def test_none_base_disk_equals_incoming_routes_to_keep():
    # None base ⇒ base != disk; disk == incoming → row 3 KEEP (convergent realign).
    assert merge_region("CORE", base_sha=None, disk_sha=B, incoming=B) == Action.KEEP


def test_none_base_disk_differs_incoming_routes_to_hardstop():
    # None base ⇒ base != disk; disk != incoming → row 4 HARDSTOP.
    assert merge_region("CORE", base_sha=None, disk_sha=B, incoming=C) == Action.HARDSTOP


def test_none_base_never_keeps_as_row1():
    # Even when disk == base-value-would-be and == incoming, a None base must not
    # be read as row-1 KEEP-because-unedited; with all three "equal" it is row 3
    # (convergent), still KEEP, but for the row-3 reason, never row 1/2 unedited.
    # The observable contract: None base with disk != incoming is HARDSTOP, which
    # a base==disk (row 2) reading would wrongly make REFRESH.
    assert merge_region("CORE", base_sha=None, disk_sha=A, incoming=B) == Action.HARDSTOP


def test_none_base_removed_unedited_path_is_hardstop():
    # removed & None base ⇒ base != disk → row 6 HARDSTOP (not DROP) without squash.
    assert (
        merge_region("CORE", base_sha=None, disk_sha=A, incoming=B, removed=True) == Action.HARDSTOP
    )


# --------------------------------------------------------------------------- #
# full matrix — table-driven so the whole decision surface is visible
# --------------------------------------------------------------------------- #

# (region_id, base, disk, incoming, squash, removed) -> expected Action
_MATRIX = [
    # rows 1-4, no squash
    ("CORE", A, A, A, False, False, Action.KEEP),  # row 1
    ("CORE", A, A, B, False, False, Action.REFRESH),  # row 2
    ("CORE", A, B, B, False, False, Action.KEEP),  # row 3 convergent
    ("CORE", A, B, C, False, False, Action.HARDSTOP),  # row 4 drift
    # rows 1-4, squash (only row 4 changes)
    ("CORE", A, A, A, True, False, Action.KEEP),  # row 1 unchanged
    ("CORE", A, A, B, True, False, Action.REFRESH),  # row 2 unchanged
    ("CORE", A, B, B, True, False, Action.KEEP),  # row 3 unchanged
    ("CORE", A, B, C, True, False, Action.REFRESH),  # row 4 → REFRESH
    # rows 5-6, no squash
    ("CORE", A, A, B, False, True, Action.DROP),  # row 5 unedited removed
    ("CORE", A, B, C, False, True, Action.HARDSTOP),  # row 6 edited removed
    # rows 5-6, squash (only row 6 changes)
    ("CORE", A, A, B, True, True, Action.DROP),  # row 5 unchanged
    ("CORE", A, B, C, True, True, Action.DROP),  # row 6 → DROP
    # PACK regions take the same template-side path as CORE
    ("PACK:django", A, B, B, False, False, Action.KEEP),  # row 3 on a PACK
    ("PACK:django", A, B, C, False, False, Action.HARDSTOP),
    # None base ⇒ base != disk
    ("CORE", None, B, B, False, False, Action.KEEP),  # → row 3
    ("CORE", None, B, C, False, False, Action.HARDSTOP),  # → row 4
    # PROJECT short-circuit, any combination
    ("PROJECT", A, B, C, False, False, Action.SKIP_PROJECT),
    ("PROJECT", A, B, C, True, True, Action.SKIP_PROJECT),
]


@pytest.mark.parametrize("region_id,base,disk,incoming,squash,removed,expected", _MATRIX)
def test_decision_matrix(region_id, base, disk, incoming, squash, removed, expected):
    assert merge_region(region_id, base, disk, incoming, squash=squash, removed=removed) == expected


# --------------------------------------------------------------------------- #
# purity — same inputs → same output, no observable side effects
# --------------------------------------------------------------------------- #


def test_pure_deterministic():
    # Same inputs yield the same output every time.
    for _ in range(5):
        assert merge_region("CORE", A, B, C) == Action.HARDSTOP
        assert merge_region("CORE", A, A, B) == Action.REFRESH


def test_pure_no_mutation_of_inputs():
    # The function must not mutate its arguments (strings are immutable, but
    # guard against any future accidental container args).
    base, disk, incoming = A, B, C
    merge_region("CORE", base, disk, incoming, squash=True, removed=True)
    assert (base, disk, incoming) == (A, B, C)


def test_pure_no_filesystem_writes(tmp_path, monkeypatch):
    # A pure decider must never open/write files. Chdir into an empty tmp dir and
    # assert nothing appears after a representative sweep of calls.
    monkeypatch.chdir(tmp_path)
    for region in ("CORE", "PACK:x", "PROJECT"):
        for removed in (False, True):
            for squash in (False, True):
                merge_region(region, A, B, C, squash=squash, removed=removed)
    assert list(tmp_path.iterdir()) == []


def test_action_is_str_token():
    # Action is a str-backed enum: members double as their stdout token (TD §2.7).
    assert Action.KEEP == "KEEP"
    assert str(Action.HARDSTOP) == "HARDSTOP"
    assert Action.DROP.value == "DROP"
    assert {a.value for a in Action} == {"REFRESH", "KEEP", "HARDSTOP", "SKIP_PROJECT", "DROP"}
