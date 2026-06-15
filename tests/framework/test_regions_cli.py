"""Subprocess-driven tests for the installer-facing `plan` / `migrate` CLI.

These are the THIN bash-wiring entry points (TD §2.7) — they wrap the already-
tested pure functions `plan_upgrade` / `migrate_flat`, so these tests only assert
the CLI contract the installer depends on: the JSON shape, the drift exit code,
base64 round-trip of `new_bytes`, and the provenance branch of `migrate`. The
decision logic itself is covered by test_plan_upgrade.py.

Matches the subprocess style of the CLI tests in test_regions.py (drive
regions.py as a child process, assert on stdout + returncode).
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

import regions
from regions import parse, region_sha

ROOT = Path(__file__).resolve().parents[2]
REGIONS_PY = ROOT / "scripts" / "oversight" / "validators" / "regions.py"


# --------------------------------------------------------------------------- #
# helpers — mirror test_plan_upgrade.py's 3-region agent builder
# --------------------------------------------------------------------------- #


def _agent(core="core body", pack="django rules", project="my project rules", front=True):
    parts = []
    if front:
        parts.append("---\nname: security-reviewer\ndispatches: [code-reviewer]\n---")
    parts.append(f"<!-- HOS:CORE:START -->\n{core}\n<!-- HOS:CORE:END -->")
    parts.append(f"<!-- HOS:PACK:django:START -->\n{pack}\n<!-- HOS:PACK:django:END -->")
    parts.append(f"<!-- HOS:PROJECT:START -->\n{project}\n<!-- HOS:PROJECT:END -->")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def _shas(bytes_):
    return {r.id: region_sha(r.body) for r in parse(bytes_).regions}


def _run(*args, **kw):
    return subprocess.run(
        [sys.executable, str(REGIONS_PY), *args], capture_output=True, text=True, **kw
    )


def _write(tmp_path, name, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# --------------------------------------------------------------------------- #
# plan — not blocked (KEEP path) — exit 0, well-formed JSON
# --------------------------------------------------------------------------- #


def test_cli_plan_not_blocked_exit_zero(tmp_path):
    disk = _agent(core="core body")
    template = _agent(core="core body", project="HOS STUB IGNORED")
    base = json.dumps(_shas(disk))

    disk_f = _write(tmp_path, "disk.md", disk)
    tmpl_f = _write(tmp_path, "tmpl.md", template)

    r = _run("plan", disk_f, tmpl_f, "--base-shas", base)
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr

    payload = json.loads(r.stdout)
    assert payload["blocked"] is False
    assert payload["hardstops"] == []
    actions = dict(tuple(a) for a in payload["actions"])
    assert actions["CORE"] == "KEEP"
    assert actions["PROJECT"] == "SKIP_PROJECT"

    # new_bytes_b64 decodes to a composed file whose PROJECT survives byte-exact.
    new_bytes = base64.b64decode(payload["new_bytes_b64"])
    assert _shas(new_bytes)["PROJECT"] == _shas(disk)["PROJECT"]
    assert payload["new_manifest_rows"] is not None


# --------------------------------------------------------------------------- #
# plan — drift HARDSTOP, no squash → blocked → EXIT_DRIFT, new_bytes null
# --------------------------------------------------------------------------- #


def test_cli_plan_blocked_exit_drift(tmp_path):
    # base != disk (consumer edited) AND disk != incoming (HOS also differs) → row 4.
    original = _agent(core="hos original")
    disk = _agent(core="consumer edited this")
    template = _agent(core="hos new version")
    base = json.dumps(_shas(original))

    disk_f = _write(tmp_path, "disk.md", disk)
    tmpl_f = _write(tmp_path, "tmpl.md", template)

    r = _run("plan", disk_f, tmpl_f, "--base-shas", base)
    assert r.returncode == regions.EXIT_DRIFT, r.stdout + r.stderr

    payload = json.loads(r.stdout)
    assert payload["blocked"] is True
    assert payload["new_bytes_b64"] is None
    assert payload["new_manifest_rows"] is None
    hardstop_regions = [h[0] for h in payload["hardstops"]]
    assert "CORE" in hardstop_regions


def test_cli_plan_squash_unblocks_drift(tmp_path):
    original = _agent(core="hos original")
    disk = _agent(core="consumer edited this")
    template = _agent(core="hos new version")
    base = json.dumps(_shas(original))

    disk_f = _write(tmp_path, "disk.md", disk)
    tmpl_f = _write(tmp_path, "tmpl.md", template)

    r = _run("plan", disk_f, tmpl_f, "--base-shas", base, "--squash")
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["blocked"] is False
    assert dict(tuple(a) for a in payload["actions"])["CORE"] == "REFRESH"
    # squash took HOS's version; PROJECT still untouched.
    new_bytes = base64.b64decode(payload["new_bytes_b64"])
    assert _shas(new_bytes)["PROJECT"] == _shas(disk)["PROJECT"]


def test_cli_plan_bad_base_shas_json(tmp_path):
    disk_f = _write(tmp_path, "disk.md", _agent())
    tmpl_f = _write(tmp_path, "tmpl.md", _agent())
    r = _run("plan", disk_f, tmpl_f, "--base-shas", "{not json")
    assert r.returncode == regions.EXIT_USAGE
    assert "not valid JSON" in r.stderr


# --------------------------------------------------------------------------- #
# migrate — both provenance branches
# --------------------------------------------------------------------------- #


def test_cli_migrate_ships_yes_wraps_core(tmp_path):
    flat = b"---\nname: foo\n---\njust a flat body, no markers\n"
    flat_f = _write(tmp_path, "flat.md", flat)

    r = _run("migrate", flat_f, "--ships", "yes")
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    out = r.stdout.encode("utf-8")
    ids = [reg.id for reg in parse(out).regions]
    assert ids == ["CORE"]
    assert b"just a flat body" in out


def test_cli_migrate_ships_no_wraps_project(tmp_path):
    flat = b"---\nname: bar\n---\nconsumer's own agent body\n"
    flat_f = _write(tmp_path, "flat.md", flat)

    r = _run("migrate", flat_f, "--ships", "no")
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    out = r.stdout.encode("utf-8")
    ids = [reg.id for reg in parse(out).regions]
    assert ids == ["PROJECT"]
    assert b"consumer's own agent body" in out


def test_cli_migrate_in_place_rewrites(tmp_path):
    flat = b"flat body no front matter\n"
    flat_f = _write(tmp_path, "flat.md", flat)

    r = _run("migrate", flat_f, "--ships", "yes", "--in-place")
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    assert r.stdout == ""
    rewritten = Path(flat_f).read_bytes()
    assert [reg.id for reg in parse(rewritten).regions] == ["CORE"]


# --------------------------------------------------------------------------- #
# base-shas — extract one path's prior base-shas (installer feeds plan)
# --------------------------------------------------------------------------- #


def test_cli_base_shas_extracts_one_path(tmp_path):
    manifest = (
        "# hos-manifest-schema: 2\n"
        ".claude/agents/a.md\tCORE\taaa\n"
        ".claude/agents/a.md\tPROJECT\tppp\n"
        ".claude/agents/b.md\tCORE\tbbb\n"
        "AGENTS.md\tWHOLE\twww\n"
    )
    mf = _write(tmp_path, ".hos-manifest", manifest.encode("utf-8"))
    r = _run("base-shas", mf, ".claude/agents/a.md")
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    assert json.loads(r.stdout) == {"CORE": "aaa", "PROJECT": "ppp"}


def test_cli_base_shas_missing_manifest_is_empty(tmp_path):
    r = _run("base-shas", str(tmp_path / "nope.manifest"), ".claude/agents/a.md")
    assert r.returncode == regions.EXIT_OK
    assert json.loads(r.stdout) == {}


def test_cli_base_shas_v1_whole_row_skipped(tmp_path):
    # A legacy 2-column (v1) agent row → WHOLE → skipped → empty (conservative).
    manifest = ".claude/agents/a.md\tdeadbeef\n"
    mf = _write(tmp_path, ".hos-manifest", manifest.encode("utf-8"))
    r = _run("base-shas", mf, ".claude/agents/a.md")
    assert r.returncode == regions.EXIT_OK
    assert json.loads(r.stdout) == {}


# --------------------------------------------------------------------------- #
# assemble-manifest — full schema-v2 manifest from a {path: [rows]} spec
# --------------------------------------------------------------------------- #


def test_cli_assemble_manifest_from_spec(tmp_path):
    spec = {
        ".claude/agents/a.md": ["CORE\taaa", "PROJECT\tppp"],
        "AGENTS.md": ["AGENTS.md\tWHOLE\twww"],  # already path-bearing — used as-is
    }
    sf = _write(tmp_path, "spec.json", json.dumps(spec).encode("utf-8"))
    r = _run("assemble-manifest", "--spec", sf)
    assert r.returncode == regions.EXIT_OK, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "# hos-manifest-schema: 2"
    body = lines[1:]
    assert ".claude/agents/a.md\tCORE\taaa" in body
    assert ".claude/agents/a.md\tPROJECT\tppp" in body
    assert "AGENTS.md\tWHOLE\twww" in body
    # body is LC_ALL=C-sorted (codepoint order) — stable diffs.
    assert body == sorted(body)


# --------------------------------------------------------------------------- #
# inject-pack — the one new write verb (TD-pack §1; ADR-031 §3.2)
# --------------------------------------------------------------------------- #


def _core_project_agent(core="core body", project="project body", front=True):
    """A two-region CORE+PROJECT template (no PACK) — the injection target."""
    parts = []
    if front:
        parts.append("---\nname: security-reviewer\ndispatches: [code-reviewer]\n---")
    parts.append(f"<!-- HOS:CORE:START -->\n{core}\n<!-- HOS:CORE:END -->")
    parts.append(f"<!-- HOS:PROJECT:START -->\n{project}\n<!-- HOS:PROJECT:END -->")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def test_inject_pack_happy_path(tmp_path):
    """inject-pack --in-place → CORE+PACK:django+PROJECT; sha identity holds."""
    staged = _write(tmp_path, "staged.md", _core_project_agent())
    body_bytes = b"django depth\n"
    body_f = _write(tmp_path, "django.md", body_bytes)

    r = _run("inject-pack", staged, "--name", "django", "--body-file", body_f, "--in-place")
    assert r.returncode == regions.EXIT_OK, r.stderr

    rewritten = Path(staged).read_bytes()
    parsed = parse(rewritten)
    ids = [reg.id for reg in parsed.regions]
    assert ids == ["CORE", "PACK:django", "PROJECT"]

    pack_reg = next(reg for reg in parsed.regions if reg.id == "PACK:django")
    assert region_sha(pack_reg.body) == region_sha(body_bytes)


def test_inject_pack_stdout_default(tmp_path):
    """Without --in-place, output goes to stdout; the on-disk file is unchanged."""
    original = _core_project_agent()
    staged = _write(tmp_path, "staged.md", original)
    body_f = _write(tmp_path, "body.md", b"pack content\n")

    r = _run("inject-pack", staged, "--name", "mypack", "--body-file", body_f)
    assert r.returncode == regions.EXIT_OK, r.stderr

    # stdout is the composed result
    out = r.stdout.encode("utf-8")
    ids = [reg.id for reg in parse(out).regions]
    assert ids == ["CORE", "PACK:mypack", "PROJECT"]

    # on-disk file is unchanged
    assert Path(staged).read_bytes() == original


def test_inject_pack_alpha_order_with_existing(tmp_path):
    """Two successive injections produce alphabetical PACK order regardless of
    injection order (compose re-sorts)."""
    staged = _write(tmp_path, "staged.md", _core_project_agent())
    body_f = _write(tmp_path, "body.md", b"pack body\n")

    # inject flask first
    r = _run("inject-pack", staged, "--name", "flask", "--body-file", body_f, "--in-place")
    assert r.returncode == regions.EXIT_OK, r.stderr

    # inject apache second
    r = _run("inject-pack", staged, "--name", "apache", "--body-file", body_f, "--in-place")
    assert r.returncode == regions.EXIT_OK, r.stderr

    final = Path(staged).read_bytes()
    ids = [reg.id for reg in parse(final).regions]
    assert ids == ["CORE", "PACK:apache", "PACK:flask", "PROJECT"]


def test_inject_pack_duplicate_rejected(tmp_path):
    """Injecting the same pack name twice → EXIT_INVALID with E_DUP_PACK in stderr."""
    # Build a staged file that already has PACK:django
    staged_bytes = _agent(core="core body", pack="django rules", project="proj")
    staged = _write(tmp_path, "staged.md", staged_bytes)
    body_f = _write(tmp_path, "body.md", b"new django depth\n")

    r = _run("inject-pack", staged, "--name", "django", "--body-file", body_f)
    assert r.returncode == regions.EXIT_INVALID
    assert "E_DUP_PACK" in r.stderr


def test_inject_pack_idempotent_fixedpoint(tmp_path):
    """compose of the inject-pack result is a fixed point (round-trip stable)."""
    staged = _write(tmp_path, "staged.md", _core_project_agent())
    body_f = _write(tmp_path, "body.md", b"django depth\n")

    r = _run("inject-pack", staged, "--name", "django", "--body-file", body_f)
    assert r.returncode == regions.EXIT_OK, r.stderr
    out1 = r.stdout.encode("utf-8")

    # Write out1 to a file and run compose on it
    composed_f = _write(tmp_path, "composed.md", out1)
    r2 = _run("compose", composed_f)
    assert r2.returncode == regions.EXIT_OK, r2.stderr
    out2 = r2.stdout.encode("utf-8")

    assert out2 == out1


def test_inject_pack_invalid_slug(tmp_path):
    """An invalid --name slug → EXIT_INVALID; stderr names the slug grammar."""
    staged = _write(tmp_path, "staged.md", _core_project_agent())
    body_f = _write(tmp_path, "body.md", b"body\n")

    r = _run("inject-pack", staged, "--name", "Django!", "--body-file", body_f)
    assert r.returncode == regions.EXIT_INVALID
    assert "[a-z0-9]" in r.stderr


def test_inject_pack_missing_body_file(tmp_path):
    """A non-existent --body-file → EXIT_USAGE; stderr contains 'file not found'."""
    staged = _write(tmp_path, "staged.md", _core_project_agent())

    r = _run(
        "inject-pack",
        staged,
        "--name",
        "django",
        "--body-file",
        str(tmp_path / "nonexistent.md"),
    )
    assert r.returncode == regions.EXIT_USAGE
    assert "file not found" in r.stderr


def test_inject_pack_literal_marker_in_body(tmp_path):
    """A body file containing a balanced literal HOS marker pair → EXIT_INVALID
    and E_LITERAL_MARKER_IN_BODY from re-validate (D2.2 / §1.3 note).

    The body must be balanced so parse(compose_output) succeeds and validate()
    can run its raw scan (an unbalanced marker causes ParseError before validate
    can emit E_LITERAL_MARKER_IN_BODY).  Both paths exit EXIT_INVALID.
    """
    staged = _write(tmp_path, "staged.md", _core_project_agent())
    # Balanced nested CORE pair in the body — parse() tolerates nesting but
    # validate()'s raw scan catches it as E_LITERAL_MARKER_IN_BODY.
    bad_body = (
        b"good line\n" b"<!-- HOS:CORE:START -->\n" b"bad inner line\n" b"<!-- HOS:CORE:END -->\n"
    )
    body_f = _write(tmp_path, "bad_body.md", bad_body)

    r = _run("inject-pack", staged, "--name", "django", "--body-file", body_f)
    assert r.returncode == regions.EXIT_INVALID
    assert "E_LITERAL_MARKER_IN_BODY" in r.stderr
