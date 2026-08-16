"""Tests for scripts/framework/gen_sandbox_config.py (#1221) and its
bootstrap/validate_setup.sh currency hook (AD-6).

`tests/framework/fixtures/sandbox/pre-existing-live-human.json` is a
SYNTHETIC reconstruction, not a capture of any real machine's
`.claude/settings.local.json` — see its own header and
`tests/framework/fixtures/sandbox/README.md` (§0.2 of the technical design).
Tests 9/10/36 below compute their assertions from that fixture plus the
currently-committed template; they do not assert against production state.

Conventions (matching tests/framework/test_require_human_approval.py):
`importlib` module loading, `tmp_path` for every filesystem test,
`mod.main([...])` for exit-code assertions. No `slow`/`integration` markers —
this file runs in the inner loop.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "framework" / "gen_sandbox_config.py"
_SPEC = importlib.util.spec_from_file_location("gen_sandbox_config", _MOD_PATH)
gsc = importlib.util.module_from_spec(_SPEC)
# Registered in sys.modules before exec: gsc's @dataclass(frozen=True)
# Divergence needs its defining module resolvable via sys.modules for
# postponed (`from __future__ import annotations`) type-hint evaluation.
sys.modules["gen_sandbox_config"] = gsc
_SPEC.loader.exec_module(gsc)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sandbox"
VALIDATE_SETUP = REPO_ROOT / "bootstrap" / "validate_setup.sh"
REAL_TEMPLATE_PATH = REPO_ROOT / "contract" / "sandbox-policy.template.json"


# ── Shared fixtures/helpers (TD §10) ────────────────────────────────────────


def _fixture_values() -> dict:
    """The §7.2 fixture placeholder values — deliberately non-production."""
    return {
        "ROLE": "human",
        "HOS_ROOT": "/srv/hos",
        "PROJECT_ROOT": "/srv/hos/Human",
        "CONFIG_DIR": "/srv/hos/.config/hos",
        "HOME": "/home/hosuser",
        "HANDOFF_DIR": "/srv/hos/handoff/human",
        "CLAUDE_PROJECT_STATE": "/home/hosuser/.claude/projects/-srv-hos-Human",
    }


def _clone(tmp_path: Path) -> Path:
    clone = tmp_path / "clone"
    (clone / ".claude").mkdir(parents=True)
    return clone


def _gen_args(clone: Path, check: bool = False, **overrides) -> list:
    args = ["--role", "human", "--clone-dir", str(clone)]
    if check:
        args.append("--check")
    else:
        args += [
            "--handoff-dir",
            overrides.pop("handoff_dir", "/srv/hos/handoff/human"),
            "--claude-project-state",
            overrides.pop("claude_project_state", "/home/hosuser/.claude/projects/-srv-hos-Human"),
        ]
    for key, value in overrides.items():
        args += ["--" + key.replace("_", "-"), value]
    return args


def _write_template(monkeypatch, tmp_path: Path, text: str) -> Path:
    """Points gsc.TEMPLATE_PATH at a throwaway file for the duration of one
    test — never writes to the real, committed template."""
    path = tmp_path / "template.json"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(gsc, "TEMPLATE_PATH", path)
    return path


def _render_with_fixture_values() -> str:
    template_text = REAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    return gsc.render(template_text, _fixture_values())


def _preflight_tree(tmp_path: Path, config_dir: Path) -> Path:
    """A tmp repo satisfying validate_setup.sh's four pre-existing sections."""
    repo = tmp_path / "repo"
    agents_dir = repo / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    for agent in (
        "architect",
        "pm-agent",
        "technical-design",
        "coder",
        "code-reviewer",
        "security-reviewer",
        "oversight-evaluator",
        "worker",
        "overseer",
    ):
        (agents_dir / f"{agent}.md").write_text("# stub\n")

    bootstrap_dir = repo / "bootstrap"
    bootstrap_dir.mkdir()
    token_script = bootstrap_dir / "get_app_token.sh"
    token_script.write_text("#!/usr/bin/env bash\necho stub\n")
    token_script.chmod(0o755)

    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "apps.env").write_text("# stub\n")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/repo.git"],
        cwd=repo,
        check=True,
    )
    return repo


def _copy_generator_and_template(repo: Path) -> None:
    dst_script_dir = repo / "scripts" / "framework"
    dst_script_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_MOD_PATH, dst_script_dir / "gen_sandbox_config.py")
    dst_contract_dir = repo / "contract"
    dst_contract_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REAL_TEMPLATE_PATH, dst_contract_dir / "sandbox-policy.template.json")


def _run_validate_setup(repo: Path, config_dir: Path, role: str | None = None):
    env = dict(os.environ)
    env["HOS_CONFIG_DIR"] = str(config_dir)
    cmd = ["bash", str(VALIDATE_SETUP), "--repo", str(repo)]
    if role:
        cmd += ["--role", role]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


# ── 1. Check detects divergence, then passes after generate (amended) ──────


def test_check_detects_divergence_then_passes_after_generate(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK

    live = clone / ".claude" / "settings.local.json"
    doc = json.loads(live.read_text())
    doc["permissions"]["deny"].pop()
    live.write_text(json.dumps(doc, indent=2) + "\n")

    assert gsc.main(_gen_args(clone, check=True)) == gsc.EXIT_DIVERGENT

    # No --force exists (2026-08-15 ruling) — move the stale file aside by hand.
    live.rename(clone / ".claude" / "settings.local.json.bak-test")
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    assert gsc.main(_gen_args(clone, check=True)) == gsc.EXIT_OK


# ── 2-5. Role gating ─────────────────────────────────────────────────────────


def test_role_worker_refused_naming_1146(tmp_path, capsys):
    clone = _clone(tmp_path)
    rc = gsc.main(["--role", "worker", "--clone-dir", str(clone)])
    out = capsys.readouterr()
    assert rc == gsc.EXIT_UNSUPPORTED_ROLE
    assert "#1146" in (out.out + out.err)


def test_role_overseer_refused_naming_1146(tmp_path, capsys):
    clone = _clone(tmp_path)
    rc = gsc.main(["--role", "overseer", "--clone-dir", str(clone)])
    out = capsys.readouterr()
    assert rc == gsc.EXIT_UNSUPPORTED_ROLE
    assert "#1146" in (out.out + out.err)


def test_unsupported_role_exits_before_any_filesystem_access(tmp_path, monkeypatch):
    opened = []
    real_open = open

    def spy_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)
    nonexistent = tmp_path / "does-not-exist"
    rc = gsc.main(["--role", "worker", "--clone-dir", str(nonexistent)])
    assert rc == gsc.EXIT_UNSUPPORTED_ROLE
    assert opened == []


def test_unknown_role_is_usage_error_not_unsupported_role(tmp_path):
    clone = _clone(tmp_path)
    rc = gsc.main(["--role", "admin", "--clone-dir", str(clone)])
    assert rc == gsc.EXIT_USAGE
    assert rc != gsc.EXIT_UNSUPPORTED_ROLE


# ── 6-8. Hard-fail / usage-error write-nothing guarantees ──────────────────


def test_surviving_placeholder_hard_fails_and_writes_nothing(tmp_path, monkeypatch):
    clone = _clone(tmp_path)
    bad_template = json.dumps({"permissions": {"deny": ["__HANDOF_DIR__"], "allow": []}})
    _write_template(monkeypatch, tmp_path, bad_template)

    rc = gsc.main(_gen_args(clone))
    assert rc == gsc.EXIT_HARD_FAIL

    claude_dir = clone / ".claude"
    assert not (claude_dir / "settings.local.json").exists()
    assert not (claude_dir / "hos-sandbox.values").exists()
    assert list(claude_dir.glob(".tmp-hos-sandbox-*")) == []


def test_malformed_template_hard_fails_and_writes_nothing(tmp_path, monkeypatch):
    clone = _clone(tmp_path)
    _write_template(monkeypatch, tmp_path, "{not valid json")

    rc = gsc.main(_gen_args(clone))
    assert rc == gsc.EXIT_HARD_FAIL
    assert not (clone / ".claude" / "settings.local.json").exists()


def test_missing_required_value_is_usage_error(tmp_path, capsys):
    clone = _clone(tmp_path)
    args = [
        "--role",
        "human",
        "--clone-dir",
        str(clone),
        "--claude-project-state",
        "/home/hosuser/.claude/projects/-x",
    ]
    rc = gsc.main(args)
    out = capsys.readouterr()
    assert rc == gsc.EXIT_USAGE
    assert "--handoff-dir" in out.err
    assert not (clone / ".claude" / "settings.local.json").exists()


# ── 9-11. AC4: semantic superset, delta table, fixture sanitization ────────


def test_generated_is_semantic_superset_of_pre_existing_live():
    generated = json.loads(_render_with_fixture_values())
    pre_existing = json.loads((FIXTURE_DIR / "pre-existing-live-human.json").read_text())

    gen_deny = set(generated["permissions"]["deny"])
    live_deny = set(pre_existing["permissions"]["deny"])
    assert live_deny <= gen_deny  # no deny is ever removed


def test_delta_table_matches_expected():
    generated = json.loads(_render_with_fixture_values())
    pre_existing = json.loads((FIXTURE_DIR / "pre-existing-live-human.json").read_text())

    gen_deny = set(generated["permissions"]["deny"])
    live_deny = set(pre_existing["permissions"]["deny"])
    gen_allow = set(generated["permissions"]["allow"])
    live_allow = set(pre_existing["permissions"]["allow"])

    added_deny = gen_deny - live_deny
    removed_deny = live_deny - gen_deny
    added_allow = gen_allow - live_allow
    removed_allow = live_allow - gen_allow

    root = _fixture_values()["PROJECT_ROOT"]
    assert added_deny == {
        f"Edit({root}/bin/**)",
        f"Edit(/{root}/bin/**)",
        "Edit(./.claude/hos-sandbox.values)",
        f"Edit({root}/.claude/hos-sandbox.values)",
        f"Edit(/{root}/.claude/hos-sandbox.values)",
    }
    assert removed_deny == set(), "no deny is ever removed (AC4 semantic-superset property)"
    assert added_allow == set(), "FR-13: permissions.allow is not edited"
    assert removed_allow == {"Bash(claude *)"}


def test_fixtures_contain_no_operator_paths():
    banned = ["/home/scott", "HumanOversightSystem"]
    prefixes_file = REPO_ROOT / "scripts" / "framework" / "installer-internal-paths.txt"
    for line in prefixes_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            banned.append(line)

    for path in FIXTURE_DIR.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for token in banned:
                assert token not in text, f"{path} contains banned token {token!r}"


# ── 12-14. Determinism (AC5) ─────────────────────────────────────────────────


def test_generate_twice_is_byte_identical():
    text1 = _render_with_fixture_values()
    text2 = _render_with_fixture_values()
    assert text1 == text2


def test_shuffled_template_key_order_produces_identical_output():
    doc = json.loads(REAL_TEMPLATE_PATH.read_text())

    def shuffle(node):
        if isinstance(node, dict):
            return {k: shuffle(v) for k, v in reversed(list(node.items()))}
        if isinstance(node, list):
            return [shuffle(x) for x in node]
        return node

    shuffled_text = json.dumps(shuffle(doc))
    normal = _render_with_fixture_values()
    shuffled = gsc.render(shuffled_text, _fixture_values())
    assert normal == shuffled


def test_array_order_is_preserved_not_sorted(monkeypatch, tmp_path):
    template = json.dumps({"list": ["zzz", "aaa", "mmm"]})
    _write_template(monkeypatch, tmp_path, template)
    out = json.loads(gsc.render(gsc.TEMPLATE_PATH.read_text(), _fixture_values()))
    assert out["list"] == ["zzz", "aaa", "mmm"]


# ── 15-17. Never-overwrite (ADDENDUM §5.2 — replaces the old --force tests) ─


def test_present_usable_file_is_left_untouched_and_exits_zero(tmp_path, capsys):
    clone = _clone(tmp_path)
    live = clone / ".claude" / "settings.local.json"
    content = (
        json.dumps({"hand": "edited", "permissions": {"allow": [], "deny": []}}, indent=2) + "\n"
    )
    live.write_text(content)
    before_mtime = live.stat().st_mtime_ns
    before_bytes = live.read_bytes()

    rc = gsc.main(_gen_args(clone))
    out = capsys.readouterr()

    assert rc == gsc.EXIT_OK
    assert live.read_bytes() == before_bytes
    assert live.stat().st_mtime_ns == before_mtime
    assert "already exists" in out.out
    assert "LEFT UNCHANGED" in out.out


def test_present_usable_unenrolled_file_gets_sidecar_written_live_untouched(tmp_path, capsys):
    """2026-08-16 enrollment ruling: a hand-maintained (present, no sidecar)
    clone gets ONLY the values sidecar written, adopting the live file as
    baseline — settings.local.json itself is still never touched."""
    clone = _clone(tmp_path)
    live = clone / ".claude" / "settings.local.json"
    content = (
        json.dumps({"hand": "edited", "permissions": {"allow": [], "deny": []}}, indent=2) + "\n"
    )
    live.write_text(content)
    before_bytes = live.read_bytes()

    rc = gsc.main(_gen_args(clone))
    out = capsys.readouterr()

    assert rc == gsc.EXIT_OK
    assert live.read_bytes() == before_bytes
    sidecar = clone / ".claude" / "hos-sandbox.values"
    assert sidecar.exists()
    assert "Enrolled this clone" in out.out

    # Enrollment unblocks --check instead of reporting NOT ENROLLED forever.
    check_rc = gsc.main(_gen_args(clone, check=True))
    assert check_rc != gsc.EXIT_NOT_ENROLLED


def test_present_usable_already_enrolled_file_leaves_sidecar_untouched(tmp_path):
    clone = _clone(tmp_path)
    live = clone / ".claude" / "settings.local.json"
    content = (
        json.dumps({"hand": "edited", "permissions": {"allow": [], "deny": []}}, indent=2) + "\n"
    )
    live.write_text(content)

    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK  # enrolls: writes the sidecar
    sidecar = clone / ".claude" / "hos-sandbox.values"
    before = sidecar.read_bytes()

    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK  # already enrolled: no-op
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize("content", ["", "   \n\t  ", "{not json", "[1, 2, 3]"])
def test_present_unusable_file_is_reported_and_never_clobbered(tmp_path, content, capsys):
    clone = _clone(tmp_path)
    live = clone / ".claude" / "settings.local.json"
    live.write_text(content)
    before = live.read_bytes()

    rc = gsc.main(_gen_args(clone))
    out = capsys.readouterr()

    assert rc == gsc.EXIT_UNUSABLE_EXISTING
    assert live.read_bytes() == before
    assert str(live) in out.err
    assert "mv " in out.err
    assert not (clone / ".claude" / "hos-sandbox.values").exists()


def test_force_flag_is_not_accepted(tmp_path):
    clone = _clone(tmp_path)
    rc = gsc.main(["--role", "human", "--clone-dir", str(clone), "--force"])
    assert rc == gsc.EXIT_USAGE


# ── 18-20. AD-1 purity ───────────────────────────────────────────────────────


def test_render_has_no_live_path_parameter():
    params = list(inspect.signature(gsc.render).parameters)
    assert params == ["template_text", "values"]


def test_generate_output_independent_of_live_file(tmp_path):
    clone = _clone(tmp_path)

    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    live = clone / ".claude" / "settings.local.json"
    sidecar = clone / ".claude" / "hos-sandbox.values"
    bytes_absent_case = live.read_bytes()
    live.unlink()
    sidecar.unlink()

    live.write_text(json.dumps({"extra": "stuff", "permissions": {"allow": [], "deny": []}}))
    live.rename(clone / ".claude" / "settings.local.json.bak-test")
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    bytes_after_divergent_moved_aside = live.read_bytes()

    assert bytes_absent_case == bytes_after_divergent_moved_aside


def test_live_file_content_never_reaches_render(tmp_path, monkeypatch):
    clone = _clone(tmp_path)
    live = clone / ".claude" / "settings.local.json"
    live.write_text(json.dumps({"permissions": {"allow": ["different"], "deny": []}}))
    live.rename(clone / ".claude" / "settings.local.json.bak-test")  # start ABSENT

    call_order = []
    real_render = gsc.render
    real_classify = gsc.classify_live

    def spy_render(*args, **kwargs):
        call_order.append("render")
        return real_render(*args, **kwargs)

    def spy_classify(*args, **kwargs):
        call_order.append("classify_live")
        return real_classify(*args, **kwargs)

    monkeypatch.setattr(gsc, "render", spy_render)
    monkeypatch.setattr(gsc, "classify_live", spy_classify)

    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    assert call_order == ["render", "classify_live"]


# ── 21-25. Values sidecar ────────────────────────────────────────────────────


def test_values_file_absent_is_distinct_from_divergence(tmp_path, capsys):
    clone = _clone(tmp_path)
    rc = gsc.main(_gen_args(clone, check=True))
    out = capsys.readouterr()
    assert rc == gsc.EXIT_NOT_ENROLLED
    assert rc != gsc.EXIT_DIVERGENT
    text = (out.out + out.err).lower()
    assert "never" in text or "hand-maintained" in text


def test_values_file_written_with_all_seven_keys_and_meta(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    sidecar_path = clone / ".claude" / "hos-sandbox.values"
    parsed = gsc.read_values_file(sidecar_path)
    for name in gsc.PLACEHOLDERS:
        assert name in parsed

    raw = sidecar_path.read_text()
    body_lines = [line for line in raw.splitlines() if line and not line.startswith("#")]
    placeholder_lines = [line for line in body_lines if not line.startswith("META_")]
    keys_in_order = [line.split("=", 1)[0] for line in placeholder_lines]
    assert keys_in_order == list(gsc.PLACEHOLDERS)
    assert "META_VALUES_VERSION=1" in raw


def test_check_needs_no_value_flags(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    rc = gsc.main(["--role", "human", "--clone-dir", str(clone), "--check"])
    assert rc == gsc.EXIT_OK


def test_incomplete_values_file_is_hard_failure_not_not_enrolled(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    sidecar_path = clone / ".claude" / "hos-sandbox.values"
    lines = [line for line in sidecar_path.read_text().splitlines() if not line.startswith("HOME=")]
    sidecar_path.write_text("\n".join(lines) + "\n")

    rc = gsc.main(_gen_args(clone, check=True))
    assert rc == gsc.EXIT_HARD_FAIL
    assert rc != gsc.EXIT_NOT_ENROLLED


def test_values_file_role_mismatch_is_hard_failure(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    sidecar_path = clone / ".claude" / "hos-sandbox.values"
    text = sidecar_path.read_text().replace("ROLE=human", "ROLE=worker")
    sidecar_path.write_text(text)

    rc = gsc.main(_gen_args(clone, check=True))
    assert rc == gsc.EXIT_HARD_FAIL


# ── 26-27. Check-mode divergence special cases ──────────────────────────────


def test_check_reports_live_file_missing_as_divergence(tmp_path, capsys):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    (clone / ".claude" / "settings.local.json").unlink()

    rc = gsc.main(_gen_args(clone, check=True))
    out = capsys.readouterr()
    assert rc == gsc.EXIT_DIVERGENT
    assert "missing entirely" in out.out


def test_check_reports_surviving_placeholder_in_live_file(tmp_path, capsys):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    live = clone / ".claude" / "settings.local.json"
    doc = json.loads(live.read_text())
    doc["stray"] = "__HANDOFF_DIR__"
    live.write_text(json.dumps(doc))

    rc = gsc.main(_gen_args(clone, check=True))
    out = capsys.readouterr()
    assert rc == gsc.EXIT_DIVERGENT
    assert "#1114" in out.out


# ── 28-30. Echo-back and exit-code hygiene ──────────────────────────────────


def test_echo_back_prints_every_placeholder_with_source(tmp_path, capsys):
    clone = _clone(tmp_path)
    gsc.main(_gen_args(clone))
    out = capsys.readouterr().out
    for name in gsc.PLACEHOLDERS:
        assert name in out
    assert "[flag]" in out
    assert "[derived]" in out


def test_exit_codes_are_distinct():
    codes = {
        gsc.EXIT_OK,
        gsc.EXIT_DIVERGENT,
        gsc.EXIT_USAGE,
        gsc.EXIT_UNSUPPORTED_ROLE,
        gsc.EXIT_UNUSABLE_EXISTING,
        gsc.EXIT_HARD_FAIL,
        gsc.EXIT_NOT_ENROLLED,
    }
    assert codes == set(range(7))


def test_module_docstring_documents_exit_codes():
    doc = gsc.__doc__
    for name in (
        "EXIT_OK",
        "EXIT_DIVERGENT",
        "EXIT_USAGE",
        "EXIT_UNSUPPORTED_ROLE",
        "EXIT_UNUSABLE_EXISTING",
        "EXIT_HARD_FAIL",
        "EXIT_NOT_ENROLLED",
    ):
        assert name in doc
    # ADDENDUM §4.4: "--force must not appear in either usage form" — check
    # the two "Usage:" code examples specifically; the surrounding prose is
    # allowed (and expected) to explain that the flag was removed.
    usage_start = doc.index("Usage:")
    usage_block = doc[usage_start : doc.index("Exit codes")]
    assert "--force" not in usage_block


# ── 31-37. Template reconciliation and .gitignore ───────────────────────────


def test_template_has_six_force_push_denies():
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    deny = tmpl["permissions"]["deny"]
    expected = {
        "Bash(git push* -f*)",
        "Bash(git push*--force*)",
        "Bash(git push * --force*)",
        "Bash(git push * -f)",
        "Bash(git push -f *)",
        "Bash(git push* +*)",
    }
    assert {d for d in deny if d in expected} == expected


def test_template_retains_plus_refspec_deny():
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    assert "Bash(git push* +*)" in tmpl["permissions"]["deny"]


def test_template_has_three_bin_deny_spellings():
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    deny = tmpl["permissions"]["deny"]
    assert "Edit(./bin/**)" in deny
    assert "Edit(__PROJECT_ROOT__/bin/**)" in deny
    assert "Edit(/__PROJECT_ROOT__/bin/**)" in deny


def test_template_denies_values_sidecar_all_spellings():
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    deny = tmpl["permissions"]["deny"]
    assert "Edit(./.claude/hos-sandbox.values)" in deny
    assert "Edit(__PROJECT_ROOT__/.claude/hos-sandbox.values)" in deny
    assert "Edit(/__PROJECT_ROOT__/.claude/hos-sandbox.values)" in deny


def test_template_denywrite_covers_values_sidecar():
    # The Edit-tool denies above stop the Edit tool only; a Bash-level write
    # (python3 -c, tee, cp, ...) is allowlisted and would still be able to
    # poison the sidecar without a matching OS-level sandbox.filesystem.denyWrite
    # entry (the same class of gap fixed for bin/** — see the entry above it).
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    deny_write = tmpl["sandbox"]["filesystem"]["denyWrite"]
    assert "__PROJECT_ROOT__/bin" in deny_write
    assert "__PROJECT_ROOT__/.claude/hos-sandbox.values" in deny_write


def test_template_does_not_allow_bash_claude():
    tmpl = json.loads(REAL_TEMPLATE_PATH.read_text())
    assert "Bash(claude *)" not in tmpl["permissions"]["allow"]


def test_template_substitutes_with_no_surviving_placeholders():
    output = _render_with_fixture_values()
    assert gsc.find_surviving_placeholders(output) == []


def test_gitignore_covers_values_file_and_backups():
    text = (REPO_ROOT / ".gitignore").read_text()
    assert ".claude/hos-sandbox.values" in text
    assert ".claude/settings.local.json.bak-*" in text


# ── 38-41. validate_setup.sh hook (AD-6) ────────────────────────────────────


def test_validate_setup_role_human_reports_divergence_and_exits_zero(tmp_path):
    config_dir = tmp_path / "config"
    repo = _preflight_tree(tmp_path, config_dir)
    _copy_generator_and_template(repo)

    assert gsc.main(_gen_args(repo)) == gsc.EXIT_OK
    live = repo / ".claude" / "settings.local.json"
    doc = json.loads(live.read_text())
    doc["permissions"]["deny"].pop()
    live.write_text(json.dumps(doc, indent=2) + "\n")

    result = _run_validate_setup(repo, config_dir, role="human")
    assert result.returncode == 0
    assert "DIVERGENT" in result.stderr


def test_validate_setup_without_role_does_not_run_check(tmp_path):
    config_dir = tmp_path / "config"
    repo = _preflight_tree(tmp_path, config_dir)
    _copy_generator_and_template(repo)

    assert gsc.main(_gen_args(repo)) == gsc.EXIT_OK
    live = repo / ".claude" / "settings.local.json"
    doc = json.loads(live.read_text())
    doc["permissions"]["deny"].pop()
    live.write_text(json.dumps(doc, indent=2) + "\n")

    result = _run_validate_setup(repo, config_dir, role=None)
    assert result.returncode == 0
    assert "DIVERGENT" not in result.stderr
    assert "sandbox" not in result.stderr.lower()


def test_validate_setup_reports_not_enrolled_distinctly(tmp_path):
    """2026-08-16 E-2 ruling: a missing policy (never enrolled) hard-blocks
    the human preflight — distinct from divergence, which stays a warning."""
    config_dir = tmp_path / "config"
    repo = _preflight_tree(tmp_path, config_dir)
    _copy_generator_and_template(repo)
    # No generate call: no live file, no sidecar — never enrolled.

    result = _run_validate_setup(repo, config_dir, role="human")
    assert result.returncode == 1
    combined = (result.stdout + result.stderr).lower()
    assert "never" in combined or "hand-maintained" in combined
    assert "divergent" not in combined
    assert "setup fail" in combined


def test_validate_setup_enrolled_hand_maintained_clone_no_longer_blocks(tmp_path):
    """The sidecar-only enrollment path (generate on a USABLE, unenrolled
    live file) is what turns the hard block back into pass/warn."""
    config_dir = tmp_path / "config"
    repo = _preflight_tree(tmp_path, config_dir)
    _copy_generator_and_template(repo)

    live = repo / ".claude" / "settings.local.json"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(
        json.dumps({"hand": "edited", "permissions": {"allow": [], "deny": []}}, indent=2) + "\n"
    )
    before = live.read_bytes()

    assert gsc.main(_gen_args(repo)) == gsc.EXIT_OK  # enrolls: sidecar only
    assert live.read_bytes() == before  # never touched

    result = _run_validate_setup(repo, config_dir, role="human")
    assert result.returncode == 0
    assert "setup fail" not in (result.stdout + result.stderr).lower()


def test_validate_setup_reports_broken_checker_distinctly(tmp_path):
    config_dir = tmp_path / "config"
    repo = _preflight_tree(tmp_path, config_dir)
    # Deliberately do NOT copy the generator — repo/scripts/framework/
    # gen_sandbox_config.py does not exist.

    result = _run_validate_setup(repo, config_dir, role="human")
    assert result.returncode == 0
    combined = result.stderr.lower()
    assert "unknown" in combined or "failed" in combined
    assert "current" not in combined


# ── New tests (ADDENDUM §5.2) ────────────────────────────────────────────────


def test_absent_file_written_with_no_surviving_placeholders(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    live = clone / ".claude" / "settings.local.json"
    assert gsc.find_surviving_placeholders(live.read_text()) == []


def test_advisory_lists_only_missing_managed_entries(tmp_path, capsys):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    live = clone / ".claude" / "settings.local.json"
    doc = json.loads(live.read_text())
    removed = doc["permissions"]["deny"][:2]
    doc["permissions"]["deny"] = doc["permissions"]["deny"][2:]
    doc["permissions"]["allow"].append("Bash(some-extra-tool *)")
    live.write_text(json.dumps(doc, indent=2) + "\n")

    capsys.readouterr()
    rc = gsc.main(_gen_args(clone))
    out = capsys.readouterr().out
    assert rc == gsc.EXIT_OK
    for entry in removed:
        assert entry in out
    assert "Bash(some-extra-tool *)" not in out


def test_advisory_failure_does_not_change_exit_code(tmp_path, monkeypatch, capsys):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK

    def broken_compare(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gsc, "compare", broken_compare)
    rc = gsc.main(_gen_args(clone))
    out = capsys.readouterr().out
    assert rc == gsc.EXIT_OK
    assert "advisory unavailable" in out


def test_untouched_run_leaves_existing_sidecar_byte_identical(tmp_path):
    clone = _clone(tmp_path)
    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK
    sidecar = clone / ".claude" / "hos-sandbox.values"
    before = sidecar.read_bytes()

    assert gsc.main(_gen_args(clone)) == gsc.EXIT_OK  # USABLE branch this time
    assert sidecar.read_bytes() == before


# ── New tests (#1423 follow-up) ──────────────────────────────────────────────
# _compare_nodes()'s positional/canonicalize() branch (arrays of objects, e.g.
# hooks.SessionStart — the case its own comment cites as motivating) was live,
# reachable code with no direct coverage: the --check CLI tests above only
# cover the missing-live-file and surviving-placeholder cases, and the AC4
# delta-table tests re-derive set differences without calling compare() at
# all. These call gsc.compare() directly against object-array shapes.


def _hook_doc(command: str) -> str:
    return json.dumps(
        {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command}]}]}}
    )


def test_compare_real_template_session_start_hook_is_object_array():
    template = json.loads(REAL_TEMPLATE_PATH.read_text())
    session_start = template["hooks"]["SessionStart"]
    assert isinstance(session_start, list) and session_start
    assert isinstance(session_start[0], dict)


def test_compare_object_array_key_order_is_not_a_divergence():
    generated = json.dumps({"hooks": {"SessionStart": [{"a": 1, "b": 2}]}})
    live = json.dumps({"hooks": {"SessionStart": [{"b": 2, "a": 1}]}})
    assert gsc.compare(generated, live) == []


def test_compare_object_array_element_change_is_positional_changed():
    generated = _hook_doc("echo one")
    live = _hook_doc("echo two")
    findings = gsc.compare(generated, live)
    assert len(findings) == 1
    assert findings[0].kind == "CHANGED"
    assert findings[0].path == "hooks.SessionStart[0]"


def test_compare_object_array_extra_and_missing_elements():
    shorter = json.dumps({"a": [{"x": 1}]})
    longer = json.dumps({"a": [{"x": 1}, {"x": 2}]})

    findings = gsc.compare(shorter, longer)
    assert len(findings) == 1
    assert findings[0].kind == "EXTRA"
    assert findings[0].path == "a[1]"

    findings = gsc.compare(longer, shorter)
    assert len(findings) == 1
    assert findings[0].kind == "MISSING"
    assert findings[0].path == "a[1]"
