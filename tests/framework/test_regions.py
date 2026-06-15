"""Tests for the region mechanism (scripts/oversight/validators/regions.py).

Covers the binding invariants from docs/v0.3.0/TECHNICAL-DESIGN.md §2 and the
spec §4 / §11/§11a decisions the module must honor:

  - round-trip identity: region_sha(parse(compose(x))) == region_sha(x), incl.
    the full ordered region-id list across a two-pack round-trip (B2)
  - validate() fail-closed cases (no CORE, two CORE, unbalanced, duplicate
    PACK, nesting, duplicate PROJECT, malformed/indented marker, and
    E_LITERAL_MARKER_IN_BODY — no literal marker line inside a body, B1)
  - a dogfood guard: no shipped agent/rubric file trips E_LITERAL_MARKER_IN_BODY
  - flat (marker-less) file -> implicit single CORE
  - D7 placeholder-free CORE/PACK check (--placeholder-keys)
  - compose() canonical re-ordering (CORE -> PACK alpha -> PROJECT)
  - line-ending + trailing-newline normalization (LF/CRLF/CR invariant; compose
    writes LF only; the D1 substitution-before-sha identity)

regions is importable bare because tests/conftest.py puts the validators dir on
sys.path (same pattern as the other validator tests).
"""

import subprocess
import sys
from pathlib import Path

import pytest
import regions
from regions import (
    compose,
    manifest_rows,
    parse,
    region_sha,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]
REGIONS_PY = ROOT / "scripts" / "oversight" / "validators" / "regions.py"
FIXTURE = Path(__file__).parent / "fixtures" / "sample_agent_three_region.md"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _agent(core="core body", packs=None, project=None, front=True):
    """Build a well-formed agent .md as bytes from parts."""
    parts = []
    if front:
        parts.append("---\nname: demo\ndispatches: []\n---")
    parts.append(f"<!-- HOS:CORE:START -->\n{core}\n<!-- HOS:CORE:END -->")
    for name, body in (packs or {}).items():
        parts.append(f"<!-- HOS:PACK:{name}:START -->\n{body}\n<!-- HOS:PACK:{name}:END -->")
    if project is not None:
        parts.append(f"<!-- HOS:PROJECT:START -->\n{project}\n<!-- HOS:PROJECT:END -->")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def _shas(parsed):
    return {r.id: region_sha(r.body) for r in parsed.regions}


# --------------------------------------------------------------------------- #
# parse
# --------------------------------------------------------------------------- #


def test_parse_three_regions_in_order():
    parsed = parse(FIXTURE.read_bytes())
    ids = [r.id for r in parsed.regions]
    assert ids == ["CORE", "PACK:django", "PROJECT"]
    assert parsed.front_matter.startswith(b"---\n")
    assert b"name: security-reviewer" in parsed.front_matter


def test_parse_pack_name_extracted():
    parsed = parse(_agent(packs={"django": "x"}))
    pack = [r for r in parsed.regions if r.id.startswith("PACK:")][0]
    assert pack.name == "django"


def test_parse_markers_excluded_from_body():
    parsed = parse(_agent(core="hello"))
    core = parsed.regions[0]
    assert b"HOS:CORE" not in core.body
    assert core.body.strip() == b"hello"


def test_parse_flat_file_no_regions():
    parsed = parse(b"just some prose, no markers at all\n")
    assert parsed.regions == []


def test_parse_end_without_start_raises():
    # S6: assert the structured fields, not just the type — the actionable-error
    # contract is that ParseError carries a precise line + kind.
    with pytest.raises(regions.ParseError) as exc:
        parse(b"<!-- HOS:CORE:END -->\n")
    assert exc.value.kind == "END_WITHOUT_START"
    assert exc.value.line == 1


def test_parse_eof_inside_region_raises():
    # S6: assert line + kind, not just that something raised.
    with pytest.raises(regions.ParseError) as exc:
        parse(b"<!-- HOS:CORE:START -->\nbody never closed\n")
    assert exc.value.kind == "EOF_IN_REGION"
    assert exc.value.line == 1  # points at the unterminated START


# --------------------------------------------------------------------------- #
# validate — happy path + fail-closed cases
# --------------------------------------------------------------------------- #


def test_validate_ok_on_fixture():
    parsed = parse(FIXTURE.read_bytes())
    assert validate(parsed).ok


def test_validate_ok_minimal_core_only():
    assert validate(parse(_agent())).ok


def test_validate_no_core():
    # A file with only a PACK region, no CORE.
    text = b"<!-- HOS:PACK:django:START -->\nx\n<!-- HOS:PACK:django:END -->\n"
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_NO_CORE" for _, code, _ in res.errors)


def test_validate_two_cores():
    text = _agent() + _agent(front=False)  # two CORE blocks
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_DUP_CORE" for _, code, _ in res.errors)


def test_parse_stray_end_after_close_raises():
    # A stray END with no open region is a structurally impossible read:
    # parse() rejects it fail-closed as END_WITHOUT_START (it never reaches
    # validate). This is the same fail-closed guarantee, one layer earlier.
    text = _agent() + b"\n<!-- HOS:PROJECT:END -->\n"
    with pytest.raises(regions.ParseError):
        parse(text)


def test_validate_unbalanced_mismatched_end():
    # parse() pairs by stack position and stays tolerant; validate() catches the
    # mismatched-id close as E_UNBALANCED (a CORE opened, closed by a PROJECT END).
    text = b"<!-- HOS:CORE:START -->\nbody\n<!-- HOS:PROJECT:END -->\n"
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_UNBALANCED" for _, code, _ in res.errors)


def test_validate_nested_markers():
    text = (
        b"<!-- HOS:CORE:START -->\n"
        b"<!-- HOS:PACK:django:START -->\n"
        b"inner\n"
        b"<!-- HOS:PACK:django:END -->\n"
        b"<!-- HOS:CORE:END -->\n"
    )
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_NESTED" for _, code, _ in res.errors)


def test_validate_duplicate_pack():
    parsed = parse(
        _agent(packs={"django": "a"})
        + b"<!-- HOS:PACK:django:START -->\nb\n<!-- HOS:PACK:django:END -->\n"
    )
    res = validate(parsed)
    assert not res.ok
    assert any(code == "E_DUP_PACK" for _, code, _ in res.errors)


def test_validate_duplicate_project():
    parsed = parse(
        _agent(project="a") + b"<!-- HOS:PROJECT:START -->\nb\n<!-- HOS:PROJECT:END -->\n"
    )
    res = validate(parsed)
    assert not res.ok
    assert any(code == "E_DUP_PROJECT" for _, code, _ in res.errors)


def test_validate_malformed_marker():
    # Looks marker-ish (HOS:) but wrong case -> not a strict marker -> flagged.
    text = b"<!-- HOS:CORE:START -->\nbody\n<!-- HOS:CORE:END -->\n" b"<!-- hos:project:start -->\n"
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_MALFORMED_MARKER" for _, code, _ in res.errors)


def test_validate_does_not_enforce_order():
    # PROJECT before CORE is structurally valid; compose() reorders, validate
    # does not reject (TD §2.4).
    text = (
        b"<!-- HOS:PROJECT:START -->\np\n<!-- HOS:PROJECT:END -->\n\n"
        b"<!-- HOS:CORE:START -->\nc\n<!-- HOS:CORE:END -->\n"
    )
    assert validate(parse(text)).ok


def test_validate_indented_marker_is_malformed():
    # S4: an indented marker (leading whitespace) is NOT a strict marker but DOES
    # match the loose probe -> E_MALFORMED_MARKER. Pins the intentional
    # fail-closed pairing (a marker that "looks right" but isn't column-0 must
    # never silently become body text).
    text = b"<!-- HOS:CORE:START -->\nbody\n<!-- HOS:CORE:END -->\n" b"  <!-- HOS:CORE:START -->\n"
    res = validate(parse(text))
    assert not res.ok
    assert any(code == "E_MALFORMED_MARKER" for _, code, _ in res.errors)


# --------------------------------------------------------------------------- #
# B1 — no literal marker line inside a region body (E_LITERAL_MARKER_IN_BODY)
# --------------------------------------------------------------------------- #


def test_validate_rejects_literal_marker_in_body():
    # A CORE body containing a fenced example with bare column-0 PACK markers.
    # PACK:django is used (not CORE/PROJECT) so the literal lines do NOT also
    # trip E_DUP_CORE / E_NESTED — they are pure body bytes that happen to match
    # the marker grammar. parse() stays tolerant (treats them as body); validate
    # rejects them with the direct diagnostic.
    body = (
        "Here is an example region:\n"
        "```\n"
        "<!-- HOS:PACK:django:START -->\n"
        "stack rules\n"
        "<!-- HOS:PACK:django:END -->\n"
        "```"
    )
    parsed = parse(_agent(core=body))
    res = validate(parsed)
    assert res.ok is False
    assert any(code == "E_LITERAL_MARKER_IN_BODY" for _, code, _ in res.errors)


def test_dogfood_shipped_files_have_no_literal_marker_in_body():
    # Every shipped agent .md and the rubric must survive validate() WITHOUT
    # emitting E_LITERAL_MARKER_IN_BODY (other codes, e.g. E_NO_CORE on a flat
    # file, are irrelevant to this guard). Docs that show markers must use inline
    # backtick spans / broken column-0 forms.
    targets = sorted((ROOT / ".claude" / "agents").glob("*.md"))
    targets.append(ROOT / "docs" / "v0.3.0" / "CORE-PACK-PROJECT-rubric.md")
    offenders = []
    for path in targets:
        parsed = parse(path.read_bytes())
        res = validate(parsed)
        if any(code == "E_LITERAL_MARKER_IN_BODY" for _, code, _ in res.errors):
            offenders.append(path.name)
    assert offenders == [], f"literal marker(s) in body of: {offenders}"


# --------------------------------------------------------------------------- #
# D7 — placeholder-free CORE/PACK
# --------------------------------------------------------------------------- #


def test_placeholder_in_core_flagged():
    parsed = parse(_agent(core="read {SPEC_FILE} now"))
    res = validate(parsed, placeholder_keys=["SPEC_FILE"])
    assert not res.ok
    assert any(code == "E_PLACEHOLDER_IN_CORE_PACK" for _, code, _ in res.errors)


def test_placeholder_in_pack_flagged():
    parsed = parse(_agent(packs={"django": "use {ADR_FILE}"}))
    res = validate(parsed, placeholder_keys=["ADR_FILE"])
    assert any(code == "E_PLACEHOLDER_IN_CORE_PACK" for _, code, _ in res.errors)


def test_placeholder_in_project_allowed():
    # Placeholders are permitted in PROJECT (D1b) — must NOT be flagged.
    parsed = parse(_agent(project="my path is {SPEC_FILE}"))
    res = validate(parsed, placeholder_keys=["SPEC_FILE"])
    assert res.ok


def test_placeholder_key_not_passed_not_flagged():
    # regions.py is token-set-agnostic (D6) — only flags keys it is TOLD about.
    parsed = parse(_agent(core="read {SPEC_FILE} now"))
    assert validate(parsed, placeholder_keys=["OTHER_KEY"]).ok
    assert validate(parsed).ok  # no keys passed at all


# --------------------------------------------------------------------------- #
# region_sha + trailing-newline normalization
# --------------------------------------------------------------------------- #


def test_region_sha_trailing_newline_normalized():
    # Zero, one, and many trailing newlines all hash identically.
    assert region_sha(b"abc") == region_sha(b"abc\n") == region_sha(b"abc\n\n\n")


def test_region_sha_crlf_trailing_normalized():
    assert region_sha(b"abc\r\n") == region_sha(b"abc")


def test_region_sha_marker_whitespace_does_not_churn():
    # A reflowed marker (extra spaces) parses; the body sha is unchanged because
    # markers contribute no bytes to the body.
    tight = parse(_agent(core="hello"))
    loose = parse(
        _agent(core="hello").replace(b"<!-- HOS:CORE:START -->", b"<!--   HOS:CORE:START   -->")
    )
    assert region_sha(tight.regions[0].body) == region_sha(loose.regions[0].body)


def test_region_sha_line_ending_invariant():
    # S1: LF, CRLF, and bare-CR renderings of the same content hash identically.
    assert region_sha(b"a\nb\nc\n") == region_sha(b"a\r\nb\r\nc\r\n") == region_sha(b"a\rb\rc\r")


def test_round_trip_stable_across_crlf():
    # The Windows-checkout-upgrade scenario: the same content authored LF vs
    # CRLF yields equal region_sha (normalized away, NOT registered as drift).
    lf = parse(_agent(core="line one\nline two"))
    crlf = parse(_agent(core="line one\nline two").replace(b"\n", b"\r\n"))
    assert region_sha(_region(lf, "CORE").body) == region_sha(_region(crlf, "CORE").body)


# --------------------------------------------------------------------------- #
# compose — round-trip identity + canonical reordering
# --------------------------------------------------------------------------- #


def test_roundtrip_identity_on_fixture():
    x = parse(FIXTURE.read_bytes())
    y = parse(compose(x))
    assert _shas(y) == _shas(x)


def test_roundtrip_identity_generated():
    x = parse(_agent(core="c", packs={"django": "d"}, project="p"))
    y = parse(compose(x))
    for rid in ("CORE", "PACK:django", "PROJECT"):
        assert region_sha(_region(x, rid).body) == region_sha(_region(y, rid).body)


def test_roundtrip_is_fixpoint():
    # compose is idempotent: composing twice yields identical bytes.
    x = parse(FIXTURE.read_bytes())
    once = compose(x)
    twice = compose(parse(once))
    assert once == twice


def test_compose_reorders_to_canonical():
    # Author out of order: PROJECT, then PACK:beta, PACK:alpha, then CORE.
    text = (
        b"<!-- HOS:PROJECT:START -->\np\n<!-- HOS:PROJECT:END -->\n\n"
        b"<!-- HOS:PACK:beta:START -->\nb\n<!-- HOS:PACK:beta:END -->\n\n"
        b"<!-- HOS:PACK:alpha:START -->\na\n<!-- HOS:PACK:alpha:END -->\n\n"
        b"<!-- HOS:CORE:START -->\nc\n<!-- HOS:CORE:END -->\n"
    )
    out = parse(compose(parse(text)))
    assert [r.id for r in out.regions] == ["CORE", "PACK:alpha", "PACK:beta", "PROJECT"]


def test_compose_preserves_front_matter():
    out = compose(parse(_agent()))
    assert out.startswith(b"---\nname: demo\n")


def test_compose_emits_canonical_marker_form():
    # A reflowed input marker is normalized to single-space canonical on write.
    src = _agent(core="hi").replace(b"<!-- HOS:CORE:START -->", b"<!--   HOS:CORE:START   -->")
    out = compose(parse(src))
    assert b"<!-- HOS:CORE:START -->" in out
    assert b"<!--   HOS:CORE:START   -->" not in out


def test_compose_writes_lf_only():
    # S1: a region authored with internal CRLF is written LF-only (D1 holds at
    # write time — compose writes the same LF bytes region_sha hashes).
    src = _agent(core="alpha\nbeta\ngamma").replace(b"\n", b"\r\n")
    out = compose(parse(src))
    assert b"\r" not in out


def test_round_trip_preserves_full_ordered_region_list():
    # B2: the FULL ordered region-id list must survive a round-trip, with TWO
    # packs present, so a compose path that silently drops or reorders a PACK is
    # caught (a single-region assertion would miss it).
    text = (
        b"<!-- HOS:CORE:START -->\nc\n<!-- HOS:CORE:END -->\n\n"
        b"<!-- HOS:PACK:beta:START -->\nb\n<!-- HOS:PACK:beta:END -->\n\n"
        b"<!-- HOS:PACK:alpha:START -->\na\n<!-- HOS:PACK:alpha:END -->\n\n"
        b"<!-- HOS:PROJECT:START -->\np\n<!-- HOS:PROJECT:END -->\n"
    )
    out = parse(compose(parse(text)))
    assert [r.id for r in out.regions] == [
        "CORE",
        "PACK:alpha",
        "PACK:beta",
        "PROJECT",
    ]


# --------------------------------------------------------------------------- #
# manifest_rows — flat file implicit CORE + canonical order
# --------------------------------------------------------------------------- #


def test_manifest_rows_three_regions_canonical_order():
    parsed = parse(FIXTURE.read_bytes())
    rows = manifest_rows("a.md", parsed)
    cols = [r.split("\t")[1] for r in rows]
    assert cols == ["CORE", "PACK:django", "PROJECT"]
    for r in rows:
        path, region, sha = r.split("\t")
        assert path == "a.md"
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)


def test_manifest_rows_flat_file_implicit_core():
    parsed = parse(b"flat agent body, no markers\n")
    rows = manifest_rows("flat.md", parsed)
    assert len(rows) == 1
    path, region, sha = rows[0].split("\t")
    assert region == "CORE"


# --------------------------------------------------------------------------- #
# CLI surface (TD §2.7)
# --------------------------------------------------------------------------- #


def _run(*args):
    return subprocess.run([sys.executable, str(REGIONS_PY), *args], capture_output=True, text=True)


def test_cli_validate_ok_exit_zero():
    r = _run("validate", str(FIXTURE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == ""


def test_cli_validate_invalid_exit_two():
    bad = FIXTURE.parent / "_tmp_bad.md"
    bad.write_bytes(b"<!-- HOS:PACK:x:START -->\ny\n<!-- HOS:PACK:x:END -->\n")
    try:
        r = _run("validate", str(bad))
        assert r.returncode == 2
        assert "E_NO_CORE" in r.stdout
    finally:
        bad.unlink()


def test_cli_validate_placeholder_keys():
    bad = FIXTURE.parent / "_tmp_ph.md"
    bad.write_bytes(_agent(core="read {SPEC_FILE}"))
    try:
        r = _run("validate", str(bad), "--placeholder-keys", "SPEC_FILE,ADR_FILE")
        assert r.returncode == 2
        assert "E_PLACEHOLDER_IN_CORE_PACK" in r.stdout
    finally:
        bad.unlink()


def test_cli_manifest_rows():
    r = _run("manifest-rows", str(FIXTURE))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.strip().split("\n")
    assert [ln.split("\t")[1] for ln in lines] == ["CORE", "PACK:django", "PROJECT"]


def test_cli_region_sha_present_and_absent():
    r = _run("region-sha", str(FIXTURE), "CORE")
    assert r.returncode == 0
    assert len(r.stdout.strip()) == 64
    r2 = _run("region-sha", str(FIXTURE), "PACK:nonexistent")
    assert r2.returncode == 3


def test_cli_region_sha_matches_library():
    parsed = parse(FIXTURE.read_bytes())
    expected = region_sha([r for r in parsed.regions if r.id == "CORE"][0].body)
    r = _run("region-sha", str(FIXTURE), "CORE")
    assert r.stdout.strip() == expected


def test_cli_compose_roundtrips():
    r = _run("compose", str(FIXTURE))
    assert r.returncode == 0
    composed = r.stdout.encode("utf-8")
    x = _shas(parse(FIXTURE.read_bytes()))
    y = _shas(parse(composed))
    assert x == y


# --------------------------------------------------------------------------- #
# small util
# --------------------------------------------------------------------------- #


def _region(parsed, rid):
    return [r for r in parsed.regions if r.id == rid][0]
