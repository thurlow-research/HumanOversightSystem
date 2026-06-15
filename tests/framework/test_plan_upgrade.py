"""Tests for the pure upgrade planner + flat migration + manifest assembler.

Covers docs/v0.3.0/TECHNICAL-DESIGN.md §4.5 (plan_upgrade — the per-file
two-phase decide-then-act core), §5/§5.3 (migrate_flat provenance gate, D3) and
§1.1/D5.6 (assemble_manifest — schema header + sorted rows).

Each scenario drives a realistic 3-region agent (CORE + PACK:django + PROJECT)
through one decision row:

  - KEEP      template CORE unchanged vs disk (base==disk==incoming)
  - REFRESH   HOS changed a CORE (base==disk, disk!=incoming)
  - HARDSTOP  consumer-edited CORE, HOS also differs, no squash → blocked
  - squash    that same drift with squash=True → REFRESH, unblocked
  - DROP      a region in base_shas but absent from the template → removed sweep
  - first_install  no PROJECT on disk → empty PROJECT stub seeded

The PROJECT-never-written invariant (§4.4) is asserted across EVERY non-blocked
path, including squash: the on-disk PROJECT body's region_sha is byte-identical
before and after planning.

regions is importable bare because tests/conftest.py puts the validators dir on
sys.path (same pattern as the other validator tests).
"""

import pytest
from regions import (
    Action,
    assemble_manifest,
    migrate_flat,
    migrate_flat_introduced_core,
    parse,
    plan_upgrade,
    region_sha,
)

# --------------------------------------------------------------------------- #
# helpers — build a well-formed 3-region agent and read its shas
# --------------------------------------------------------------------------- #


def _agent(core="core body", pack="django rules", project="my project rules", front=True):
    """A realistic 3-region agent: CORE + PACK:django + PROJECT."""
    parts = []
    if front:
        parts.append("---\nname: security-reviewer\ndispatches: [code-reviewer]\n---")
    parts.append(f"<!-- HOS:CORE:START -->\n{core}\n<!-- HOS:CORE:END -->")
    parts.append(f"<!-- HOS:PACK:django:START -->\n{pack}\n<!-- HOS:PACK:django:END -->")
    parts.append(f"<!-- HOS:PROJECT:START -->\n{project}\n<!-- HOS:PROJECT:END -->")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def _shas(bytes_):
    return {r.id: region_sha(r.body) for r in parse(bytes_).regions}


def _action(plan, region_id):
    return dict(plan.actions)[region_id]


def _project_sha(bytes_):
    return _shas(bytes_)["PROJECT"]


# --------------------------------------------------------------------------- #
# KEEP — template CORE identical to disk (base == disk == incoming)
# --------------------------------------------------------------------------- #


def test_keep_unchanged_core():
    disk = _agent(core="core body")
    template = _agent(core="core body", project="HOS STUB IGNORED")
    base = _shas(disk)

    plan = plan_upgrade(disk, template, base)

    assert not plan.blocked
    assert _action(plan, "CORE") == Action.KEEP
    assert _action(plan, "PACK:django") == Action.KEEP
    assert _action(plan, "PROJECT") == Action.SKIP_PROJECT
    # KEEP re-stamps base_sha = incoming; for an unchanged region that equals the
    # on-disk sha, so the manifest row is the disk sha.
    assert _project_sha(plan.new_bytes) == _project_sha(disk)


# --------------------------------------------------------------------------- #
# REFRESH — HOS changed a CORE (base == disk, disk != incoming)
# --------------------------------------------------------------------------- #


def test_refresh_hos_changed_core():
    disk = _agent(core="old core")
    template = _agent(core="NEW core from HOS")
    base = _shas(disk)  # base == disk (consumer never edited)

    plan = plan_upgrade(disk, template, base)

    assert not plan.blocked
    assert _action(plan, "CORE") == Action.REFRESH
    # The composed CORE body is HOS's new template body.
    assert _shas(plan.new_bytes)["CORE"] == _shas(template)["CORE"]
    # Manifest CORE row re-stamped to incoming (the new template sha).
    rows = dict(r.split("\t") for r in plan.new_manifest_rows)
    assert rows["CORE"] == _shas(template)["CORE"]


# --------------------------------------------------------------------------- #
# HARDSTOP — consumer-edited CORE + HOS also differs, no squash → blocked
# --------------------------------------------------------------------------- #


def test_hardstop_drift_blocks_whole_file():
    disk = _agent(core="consumer EDITED this core")
    template = _agent(core="HOS's different core")
    # base != disk: pretend HOS last wrote a third value.
    base = dict(_shas(_agent(core="original HOS core")))

    plan = plan_upgrade(disk, template, base)

    assert plan.blocked is True
    assert plan.new_bytes is None
    assert plan.new_manifest_rows is None
    assert _action(plan, "CORE") == Action.HARDSTOP
    # The drift report names the region + offers the two remedies (§4.3).
    region_ids = [rid for rid, _ in plan.hardstops]
    assert "CORE" in region_ids
    reason = dict(plan.hardstops)["CORE"]
    assert "--squash" in reason
    assert "PROJECT" in reason


def test_squash_converts_drift_to_refresh():
    disk = _agent(core="consumer EDITED this core")
    template = _agent(core="HOS's different core")
    base = dict(_shas(_agent(core="original HOS core")))

    plan = plan_upgrade(disk, template, base, squash=True)

    assert not plan.blocked
    assert plan.hardstops == []
    assert _action(plan, "CORE") == Action.REFRESH
    # Squash takes HOS's version.
    assert _shas(plan.new_bytes)["CORE"] == _shas(template)["CORE"]


# --------------------------------------------------------------------------- #
# DROP — a region in base_shas but absent from the template (removed sweep, D9)
# --------------------------------------------------------------------------- #


def test_drop_unedited_removed_region():
    # Disk + base both have a PACK:legacy that the new template no longer ships.
    disk = _agent_with_extra_pack(core="c", legacy="legacy body")
    template = _agent(core="c")  # no PACK:legacy
    base = _shas(disk)  # base == disk for the legacy pack → unedited → DROP

    plan = plan_upgrade(disk, template, base)

    assert not plan.blocked
    assert _action(plan, "PACK:legacy") == Action.DROP
    # The dropped region is gone from the composed file and the manifest.
    assert "PACK:legacy" not in _shas(plan.new_bytes)
    row_regions = [r.split("\t")[0] for r in plan.new_manifest_rows]
    assert "PACK:legacy" not in row_regions


def test_drop_edited_removed_region_hardstops():
    disk = _agent_with_extra_pack(core="c", legacy="consumer EDITED legacy")
    template = _agent(core="c")
    # base has a DIFFERENT legacy sha → base != disk → edited → HARDSTOP.
    base = _shas(_agent_with_extra_pack(core="c", legacy="original legacy"))

    plan = plan_upgrade(disk, template, base)

    assert plan.blocked is True
    assert _action(plan, "PACK:legacy") == Action.HARDSTOP


def test_drop_edited_removed_region_squash_drops():
    disk = _agent_with_extra_pack(core="c", legacy="consumer EDITED legacy")
    template = _agent(core="c")
    base = _shas(_agent_with_extra_pack(core="c", legacy="original legacy"))

    plan = plan_upgrade(disk, template, base, squash=True)

    assert not plan.blocked
    assert _action(plan, "PACK:legacy") == Action.DROP
    assert "PACK:legacy" not in _shas(plan.new_bytes)


def _agent_with_extra_pack(core="c", legacy="legacy body"):
    """A 4-region agent: CORE + PACK:django + PACK:legacy + PROJECT."""
    parts = [
        "---\nname: demo\ndispatches: []\n---",
        f"<!-- HOS:CORE:START -->\n{core}\n<!-- HOS:CORE:END -->",
        "<!-- HOS:PACK:django:START -->\ndjango rules\n<!-- HOS:PACK:django:END -->",
        f"<!-- HOS:PACK:legacy:START -->\n{legacy}\n<!-- HOS:PACK:legacy:END -->",
        "<!-- HOS:PROJECT:START -->\nproj\n<!-- HOS:PROJECT:END -->",
    ]
    return ("\n\n".join(parts) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# first_install — no PROJECT on disk → empty PROJECT stub seeded (§7.1)
# --------------------------------------------------------------------------- #


def test_first_install_seeds_empty_project_stub():
    # Disk has only CORE + PACK (e.g. a freshly-copied template with no PROJECT).
    disk = (
        b"<!-- HOS:CORE:START -->\nc\n<!-- HOS:CORE:END -->\n\n"
        b"<!-- HOS:PACK:django:START -->\nd\n<!-- HOS:PACK:django:END -->\n"
    )
    template = _agent(core="c", pack="d")
    base = _shas(disk)

    plan = plan_upgrade(disk, template, base, first_install=True)

    assert not plan.blocked
    out_ids = [r.id for r in parse(plan.new_bytes).regions]
    assert "PROJECT" in out_ids
    # The seeded PROJECT is the empty stub.
    proj = [r for r in parse(plan.new_bytes).regions if r.id == "PROJECT"][0]
    assert proj.body.strip() == b""


def test_no_project_no_first_install_omits_project():
    disk = (
        b"<!-- HOS:CORE:START -->\nc\n<!-- HOS:CORE:END -->\n\n"
        b"<!-- HOS:PACK:django:START -->\nd\n<!-- HOS:PACK:django:END -->\n"
    )
    template = _agent(core="c", pack="d")
    base = _shas(disk)

    plan = plan_upgrade(disk, template, base, first_install=False)

    assert not plan.blocked
    assert "PROJECT" not in [r.id for r in parse(plan.new_bytes).regions]


# --------------------------------------------------------------------------- #
# PROJECT-never-written invariant (§4.4) — across every non-blocked path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "core_disk,core_base,core_tmpl,squash",
    [
        ("same", "same", "same", False),  # KEEP   (base==disk==incoming)
        ("old", "old", "new", False),  # REFRESH (base==disk, disk!=incoming)
        ("edited", "orig", "hos-different", True),  # drift → squash REFRESH (base!=disk)
    ],
)
def test_project_bytes_identical_disk_to_new(core_disk, core_base, core_tmpl, squash):
    # The consumer's PROJECT body must be byte-identical disk↔new_bytes on EVERY
    # path, including squash (§4.4 — the never-written invariant).
    disk = _agent(core=core_disk, project="SACRED consumer rules — do not touch")
    template = _agent(core=core_tmpl, project="HOS stub that must be ignored")
    base = _shas(_agent(core=core_base, project="SACRED consumer rules — do not touch"))

    plan = plan_upgrade(disk, template, base, squash=squash)

    assert not plan.blocked
    # region_sha equality is the normalized-byte identity the TD asks us to assert.
    assert _project_sha(plan.new_bytes) == _project_sha(disk)
    # And literally: the PROJECT body bytes are the disk body, never the template.
    disk_proj = [r for r in parse(disk).regions if r.id == "PROJECT"][0].body
    new_proj = [r for r in parse(plan.new_bytes).regions if r.id == "PROJECT"][0].body
    assert region_sha(new_proj) == region_sha(disk_proj)
    # Sanity: the template's PROJECT was genuinely different — invariant non-vacuous.
    tmpl_proj = [r for r in parse(template).regions if r.id == "PROJECT"][0].body
    assert region_sha(tmpl_proj) != region_sha(disk_proj)


def test_project_unchanged_even_when_blocked():
    # On a HARDSTOP block nothing is composed, but the disk file is never touched
    # either — there is simply no new_bytes. Assert the planner returns no bytes
    # so the installer writes nothing (the disk PROJECT is trivially preserved).
    disk = _agent(core="consumer edit", project="SACRED")
    template = _agent(core="hos different")
    base = _shas(_agent(core="orig"))

    plan = plan_upgrade(disk, template, base)

    assert plan.blocked
    assert plan.new_bytes is None


# --------------------------------------------------------------------------- #
# migrate_flat — both provenance branches (D3)
# --------------------------------------------------------------------------- #


def test_migrate_flat_hos_owned_wraps_core():
    flat = b"---\nname: security-reviewer\n---\nthe whole flat body\nsecond line\n"
    out = migrate_flat(flat, hos_ships_agent=True)

    parsed = parse(out)
    assert [r.id for r in parsed.regions] == ["CORE"]
    assert parsed.regions[0].body.strip() == b"the whole flat body\nsecond line"
    # Front-matter preserved.
    assert parsed.front_matter.startswith(b"---\n")
    assert b"name: security-reviewer" in parsed.front_matter


def test_migrate_flat_unknown_wraps_project():
    flat = b"a consumer's own agent body\n"
    out = migrate_flat(flat, hos_ships_agent=False)

    parsed = parse(out)
    assert [r.id for r in parsed.regions] == ["PROJECT"]
    assert parsed.regions[0].body.strip() == b"a consumer's own agent body"


def test_migrate_flat_content_preserving_round_trip():
    # The wrapped body's region_sha equals the flat body's region_sha (no loss).
    flat = b"line one\nline two\nline three\n"
    out_core = migrate_flat(flat, hos_ships_agent=True)
    out_proj = migrate_flat(flat, hos_ships_agent=False)
    body_sha = region_sha(flat)
    assert region_sha(parse(out_core).regions[0].body) == body_sha
    assert region_sha(parse(out_proj).regions[0].body) == body_sha


def test_migrate_flat_result_validates():
    from regions import validate

    flat = b"---\nname: x\n---\nbody\n"
    # HOS-owned → CORE wrap → fully valid (exactly one CORE).
    assert validate(parse(migrate_flat(flat, hos_ships_agent=True))).ok
    # Unknown → PROJECT-only wrap is structurally well-formed (balanced markers,
    # no nesting); it trips only E_NO_CORE, which is correct for a consumer agent
    # HOS doesn't ship — the migration itself produced no structural corruption.
    res = validate(parse(migrate_flat(flat, hos_ships_agent=False)))
    codes = {code for _, code, _ in res.errors}
    assert codes <= {"E_NO_CORE"}


def test_migrate_flat_introduced_core_layers_not_merges():
    # §5.3: existing flat consumer body → PROJECT; fresh HOS CORE prepended.
    consumer_flat = b"---\nname: planner\n---\nthe consumer's old hand-written body\n"
    hos_template = (
        b"---\nname: planner\n---\n"
        b"<!-- HOS:CORE:START -->\nfresh generic HOS core\n<!-- HOS:CORE:END -->\n"
    )
    out = migrate_flat_introduced_core(consumer_flat, hos_template)
    parsed = parse(out)
    assert [r.id for r in parsed.regions] == ["CORE", "PROJECT"]
    # CORE is HOS's; PROJECT is the consumer's old body verbatim (never merged).
    core = [r for r in parsed.regions if r.id == "CORE"][0]
    proj = [r for r in parsed.regions if r.id == "PROJECT"][0]
    assert core.body.strip() == b"fresh generic HOS core"
    assert proj.body.strip() == b"the consumer's old hand-written body"


# --------------------------------------------------------------------------- #
# assemble_manifest — schema header + sorted rows (§1.1, D5.6)
# --------------------------------------------------------------------------- #


def test_assemble_manifest_header_and_rows():
    rows_by_file = {
        ".claude/agents/security-reviewer.md": ["CORE\t" + "a" * 64, "PROJECT\t" + "b" * 64],
        ".claude/agents/code-reviewer.md": ["CORE\t" + "c" * 64],
    }
    out = assemble_manifest(rows_by_file)
    lines = out.splitlines()

    # Schema header first, exempt from the sort (§1.1).
    assert lines[0] == "# hos-manifest-schema: 2"
    # Body sorted by LC_ALL=C (codepoint) order; code-reviewer < security-reviewer.
    assert lines[1].startswith(".claude/agents/code-reviewer.md\tCORE\t")
    assert lines[2].startswith(".claude/agents/security-reviewer.md\tCORE\t")
    assert lines[3].startswith(".claude/agents/security-reviewer.md\tPROJECT\t")
    # Trailing newline.
    assert out.endswith("\n")


def test_assemble_manifest_accepts_full_path_rows():
    # A row already carrying its path is used as-is (no double-prefix).
    rows_by_file = {"x": [".claude/agents/a.md\tCORE\t" + "a" * 64]}
    out = assemble_manifest(rows_by_file)
    assert ".claude/agents/a.md\tCORE\t" in out
    assert "x\t.claude/agents/a.md" not in out


def test_assemble_manifest_deterministic():
    rows_by_file = {
        "b.md": ["CORE\t" + "2" * 64],
        "a.md": ["CORE\t" + "1" * 64],
    }
    assert assemble_manifest(rows_by_file) == assemble_manifest(
        dict(reversed(rows_by_file.items()))
    )


# --------------------------------------------------------------------------- #
# plan_upgrade purity — no filesystem writes
# --------------------------------------------------------------------------- #


def test_plan_upgrade_no_filesystem_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    disk = _agent(core="old")
    template = _agent(core="new")
    plan_upgrade(disk, template, _shas(disk))
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- #
# Regression guards (code-review): the dual-loop edge cases
# --------------------------------------------------------------------------- #


def test_template_present_disk_absent_region_refreshes():
    # Consumer deleted the HOS PACK region from disk, but its base_sha still
    # tracks it. plan must RE-ADD it (REFRESH) — it's HOS-owned, not consumer
    # data, so a missing HOS region on disk is restored, not treated as drift.
    disk_no_pack = (
        b"---\nname: security-reviewer\ndispatches: [code-reviewer]\n---\n\n"
        b"<!-- HOS:CORE:START -->\ncore body\n<!-- HOS:CORE:END -->\n\n"
        b"<!-- HOS:PROJECT:START -->\nmy project rules\n<!-- HOS:PROJECT:END -->\n"
    )
    template = _agent()  # CORE + PACK:django + PROJECT
    base = _shas(template)  # base tracks all three, incl PACK:django

    plan = plan_upgrade(disk_no_pack, template, base)

    assert not plan.blocked
    assert _action(plan, "PACK:django") == Action.REFRESH
    assert "PACK:django" in _shas(plan.new_bytes)  # re-added to the composed file


def test_base_region_absent_from_disk_and_template_is_skipped():
    # A region in the manifest but in NEITHER disk nor template (a "ghost" — e.g.
    # a pack the consumer never actually had on disk) is skipped: no action row,
    # no block. Nothing to drop, nothing to refresh.
    disk = _agent()
    template = _agent()
    base = _shas(disk)
    base["PACK:rails"] = "f" * 64  # ghost: absent from both disk and template

    plan = plan_upgrade(disk, template, base)

    assert not plan.blocked
    assert "PACK:rails" not in dict(plan.actions)
