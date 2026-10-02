"""
Tests for scripts/automation/dimension_registry_cli.py — the L2 CLI over the
registry loader (ADR-1643 TD §7.10 as amended by §C.2.7; W5a slice).

Drives `main(argv, repo_root=tmp_path)` in-process against tmp_path fixture
registries. Test IDs: T5.30-adjacent `plan` shape, CLI exit vocabulary, the
`--schema` delta, and the L2 -> exit 1 conversion (the registry CLI's
equivalent of TD-D23's P0). T5.30 itself (sweep --json == plan) is deferred
to the W5 slice that rewrites run_post_change_sweep.sh.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from scripts.automation import dimension_registry_cli as cli
from scripts.automation.lib import dimension_registry as dr
from tests.automation.test_dimension_registry import default_docs, write_repo


def run(capsys, root, *argv):
    rc = cli.main(list(argv), repo_root=root)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_resolve_emits_one_json_object(tmp_path, capsys):
    """T5.43 (CLI side): resolve prints exactly one JSON object equal to the engine's to_json."""
    write_repo(tmp_path)
    rc, out, err = run(capsys, tmp_path, "resolve")
    assert rc == 0 and err == ""
    assert json.loads(out) == json.loads(json.dumps(dr.to_json(dr.load(tmp_path))))
    assert out.count("\n") > 1 and json.loads(out)["packs"] == ["django"]


def test_resolve_pack_flag_overrides_resolved_packs_file(tmp_path, capsys):
    """CLI delta: --pack is used verbatim; with none, contract/resolved-packs.txt is read."""
    write_repo(tmp_path)
    rc, out, err = run(capsys, tmp_path, "resolve", "--pack", "django")
    assert rc == 0 and json.loads(out)["packs"] == ["django"]
    rc, out, err = run(capsys, tmp_path, "resolve", "--pack", "astro")
    assert rc == 1 and err.startswith("dimension_registry: stale_pack_file: ")


def test_resolve_absent_resolved_packs_is_exit_1(tmp_path, capsys):
    """L24 through the CLI: no resolved-packs.txt and no --pack -> exit 1, bad_pack_set."""
    write_repo(tmp_path, packs=None)
    rc, out, err = run(capsys, tmp_path, "resolve")
    assert rc == 1 and out == "" and err.startswith("dimension_registry: bad_pack_set: ")
    assert err.count("\n") == 1
    rc, out, _ = run(capsys, tmp_path, "resolve", "--pack", "django")
    assert rc == 0


def test_resolve_unknown_schema_is_exit_1_not_2(tmp_path, capsys):
    """CLI delta: an unknown --schema is checked against data (exit 1, unknown_kind), not the parser."""
    write_repo(tmp_path)
    rc, out, err = run(capsys, tmp_path, "resolve", "--schema", "hos.nope")
    assert rc == 1 and out == "" and "unknown_kind" in err


def test_stderr_line_form_has_code_message_and_path(tmp_path, capsys):
    """§7.10: `dimension_registry: <code>: <message> [<path>]`, one line."""
    docs = default_docs()
    docs["core"]["schema_version"] = 9
    write_repo(tmp_path, docs)
    rc, out, err = run(capsys, tmp_path, "resolve")
    assert rc == 1 and out == ""
    assert err.startswith("dimension_registry: bad_schema_version: ")
    assert err.rstrip("\n").endswith("[contract/dimensions/core.yaml]") and err.count("\n") == 1


def test_yaml_unavailable_is_exit_1_with_no_traceback(tmp_path, capsys, monkeypatch):
    """C.2.7: L2 becomes exit 1 and the standard stderr line, never a traceback."""
    write_repo(tmp_path)
    monkeypatch.setitem(sys.modules, "yaml", None)
    rc, out, err = run(capsys, tmp_path, "resolve")
    assert rc == 1 and err.startswith("dimension_registry: yaml_unavailable: ")
    assert "Traceback" not in err


def test_plan_with_changed_files(tmp_path, capsys):
    """plan --changed-file: one JSON object; every item has a non-empty reason."""
    write_repo(tmp_path)
    rc, out, err = run(
        capsys, tmp_path, "plan", "--changed-file", "app/x.py", "--changed-file", "docs/a.md"
    )
    assert rc == 0 and err == ""
    doc = json.loads(out)
    assert doc["changed_files"] == ["app/x.py", "docs/a.md"]
    assert doc["digest"] == dr.load(tmp_path).digest
    by_binding = {p["binding"]: p for p in doc["plan"]}
    assert by_binding["core:code-review/code"]["applicable"] is True
    assert by_binding["core:code-review/code"]["matched_files"] == ["app/x.py"]
    assert by_binding["project:code-review/docs"]["applicable"] is True
    assert by_binding["core:ui/markup"]["applicable"] is False
    assert all(p["reason"] for p in doc["plan"])


def test_plan_with_base_unions_git_diff_and_explicit_files(tmp_path, capsys):
    """plan --base: changed files are `git diff --name-only <base>...HEAD` plus --changed-file."""
    write_repo(tmp_path)

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    (tmp_path / "changed.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "change")
    rc, out, err = run(capsys, tmp_path, "plan", "--base", "main", "--changed-file", "docs/z.md")
    assert rc == 0, err
    assert json.loads(out)["changed_files"] == ["changed.py", "docs/z.md"]


def test_plan_bad_base_is_exit_1(tmp_path, capsys):
    """An unresolvable --base is an operational failure (exit 1), not a silent empty plan."""
    write_repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    rc, out, err = run(capsys, tmp_path, "plan", "--base", "no-such-ref")
    assert rc == 1 and out == "" and err.startswith("dimension_registry: git_failed: ")


def test_plan_broken_registry_is_exit_1(tmp_path, capsys):
    """plan fails closed on a loader error rather than planning against nothing."""
    write_repo(tmp_path, packs=[])
    rc, out, err = run(capsys, tmp_path, "plan", "--changed-file", "a.py")
    assert rc == 1 and out == "" and "stale_pack_file" in err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["plan"],
        ["plan", "--base", "-x"],
        ["plan", "--schema", "x", "--changed-file", "a"],
        ["resolve", "--nope"],
        ["resolve", "--pack"],
    ],
)
def test_usage_errors_exit_2(tmp_path, capsys, argv):
    """Exit 2 for usage errors: no subcommand, unknown flag, plan with no input, plan --schema."""
    write_repo(tmp_path)
    rc, out, err = run(capsys, tmp_path, *argv)
    assert rc == 2 and out == "" and err.startswith("dimension_registry_cli.py: usage: ")


def test_import_performs_no_yaml_import():
    """The CLI module imports no PyYAML at module level (a missing dependency must stay a RegistryError)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import scripts.automation.dimension_registry_cli; "
            "sys.exit(1 if 'yaml' in sys.modules else 0)",
        ],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
