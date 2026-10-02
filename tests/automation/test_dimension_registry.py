"""
Tests for scripts/automation/lib/dimension_registry.py — the schema-parametric
registry loader (ADR-1643 TD §7 as amended by Amendment C; W5a slice).

All fixtures are tmp_path registries; none depends on the real
contract/dimensions/core.yaml (that ships in a later W5 slice).

Test IDs follow TD §9.5 / §C.2.12. TD numbering note: the TD's TD-D21 prose
calls determinism "T5.9", but §9.5's list and §C.2.12 assign T5.9 to rule L9
(kind_mismatch) and determinism to T5.29; this file follows the list.

Deferred to later W5 slices (need real contract/ files, the installer, or
the sweep script): T5.28, T5.30, T5.31, T5.33, T5.44, T5.47, T5.48.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import types
from pathlib import Path

import pytest
import yaml

from scripts.automation.lib import dimension_registry as dr
from scripts.automation.lib.dimension_registry import RegistryError

SCHEMA = dr.DIMENSIONS_SCHEMA

_SETTINGS = {
    "permissions": {
        "defaultMode": "manual",
        "disableBypassPermissionsMode": "disable",
        "allow": ["Read", "Grep", "Glob", "Bash(git diff *)"],
        "deny": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Bash(gh *)"],
    }
}
_SIDECAR = {
    "schema": "hos.invocation-posture",
    "schema_version": 1,
    "id": "review-read-only",
    "permission_mode": "manual",
    "allowed_tools": ["Read", "Grep", "Glob"],
    "disallowed_tools": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"],
}


def judgment(bid: str, entry: str, include: list[str], **over) -> dict:
    b = {
        "id": bid,
        "entry": entry,
        "kind": "judgment",
        "agent": "code-reviewer" if entry != "ui" else "ui-reviewer",
        "posture": "review-read-only",
        "timeout_seconds": 300,
        "prompt_template": "contract/dimensions/prompts/p.md",
        "predicate": {"include": include},
    }
    b.update(over)
    return b


def deterministic(bid: str, entry: str, include: list[str], **over) -> dict:
    b = {
        "id": bid,
        "entry": entry,
        "kind": "deterministic",
        "tool": "scripts/gates/lint.sh",
        "timeout_seconds": 300,
        "predicate": {"include": include},
    }
    b.update(over)
    return b


def default_docs() -> dict[str, dict]:
    head = {"schema": SCHEMA, "schema_version": 1}
    return {
        "core": {
            **head,
            "owner": "core",
            "entries": [
                {"id": "code-review", "kind": "judgment", "title": "Code review"},
                {"id": "lint", "kind": "deterministic", "title": "Lint"},
                {"id": "ui", "kind": "judgment", "title": "UI"},
            ],
            "bindings": [
                judgment(
                    "core:code-review/code",
                    "code-review",
                    [r"\.py$"],
                    predicate={"include": [r"\.py$"], "exclude": ["^tests/"]},
                ),
                deterministic("core:lint/all", "lint", [".*"]),
                judgment("core:ui/markup", "ui", [r"\.html$"]),
            ],
        },
        "pack-django": {
            **head,
            "owner": "pack",
            "pack": "django",
            "bindings": [
                judgment("pack-django:code-review/app", "code-review", [r"manage\.py$"]),
                deterministic("pack-django:lint/django", "lint", [r"\.py$"]),
            ],
        },
        "project": {
            **head,
            "owner": "project",
            "bindings": [judgment("project:code-review/docs", "code-review", ["^docs/"])],
        },
    }


def write_repo(
    root: Path,
    docs: dict[str, dict | str | None] | None = None,
    *,
    packs: list[str] | None = ("django",),  # type: ignore[assignment]
) -> Path:
    """Write a fixture registry. A docs value of None skips the file; a str is
    written verbatim. `packs=None` writes no resolved-packs.txt."""
    docs = default_docs() if docs is None else docs
    d = root / "contract" / "dimensions"
    d.mkdir(parents=True, exist_ok=True)
    for stem, data in docs.items():
        if data is None:
            continue
        text = data if isinstance(data, str) else yaml.safe_dump(data)
        (d / f"{stem}.yaml").write_text(text)
    if packs is not None:
        (root / "contract" / "resolved-packs.txt").write_text(
            "# generated\n" + "".join(f"{p}\n" for p in packs)
        )
    for agent in ("code-reviewer", "ui-reviewer"):
        a = root / ".claude" / "agents" / f"{agent}.md"
        a.parent.mkdir(parents=True, exist_ok=True)
        a.write_text(f"---\nname: {agent}\n---\nbody\n")
    prompt = d / "prompts" / "p.md"
    prompt.parent.mkdir(exist_ok=True)
    prompt.write_text("prompt")
    tool = root / "scripts" / "gates" / "lint.sh"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    pdir = d / "postures"
    pdir.mkdir(exist_ok=True)
    (pdir / "review-read-only.settings.json").write_text(json.dumps(_SETTINGS))
    (pdir / "review-read-only.hos.json").write_text(json.dumps(_SIDECAR))
    return root


def code_of(root: Path, **kw) -> str:
    with pytest.raises(RegistryError) as exc:
        dr.load(root, **kw)
    return exc.value.code


def docs_with(mutate) -> dict:
    docs = default_docs()
    mutate(docs)
    return docs


def binding(docs: dict, doc: str, bid: str) -> dict:
    return next(b for b in docs[doc]["bindings"] if b["id"] == bid)


# --- T5.1-T5.21: one test per loader rule --------------------------------


def test_T5_1_core_missing(tmp_path):
    """T5.1 L1: core.yaml absent -> core_missing."""
    write_repo(tmp_path, {"core": None})
    assert code_of(tmp_path) == "core_missing"


def test_T5_2_yaml_unavailable(tmp_path, monkeypatch):
    """T5.2 L2: PyYAML not importable -> yaml_unavailable."""
    write_repo(tmp_path)
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert code_of(tmp_path) == "yaml_unavailable"


def test_T5_3a_bad_schema(tmp_path):
    """T5.3a L3a: not a mapping / schema absent / a stage-schema file in contract/dimensions/."""
    write_repo(tmp_path, {"core": "- a\n- list\n"})
    assert code_of(tmp_path) == "bad_schema"
    write_repo(tmp_path, docs_with(lambda d: d["core"].pop("schema")))
    assert code_of(tmp_path) == "bad_schema"
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(schema="hos.stage-graph")))
    assert code_of(tmp_path) == "bad_schema"
    write_repo(tmp_path, {"core": "key: [unclosed"})
    assert code_of(tmp_path) == "bad_schema"


def test_T5_3b_bad_schema_version(tmp_path):
    """T5.3b L3b: schema_version != 1 -> bad_schema_version."""
    for bad in (2, "1", True):
        write_repo(tmp_path, docs_with(lambda d, bad=bad: d["core"].update(schema_version=bad)))
        assert code_of(tmp_path) == "bad_schema_version"


def test_T5_4_owner_mismatch(tmp_path):
    """T5.4 L4: owner absent / not matching the filename / pack != filename slug."""
    write_repo(tmp_path, docs_with(lambda d: d["core"].pop("owner")))
    assert code_of(tmp_path) == "owner_mismatch"
    write_repo(tmp_path, docs_with(lambda d: d["project"].update(owner="core")))
    assert code_of(tmp_path) == "owner_mismatch"
    write_repo(tmp_path, docs_with(lambda d: d["pack-django"].update(pack="astro")))
    assert code_of(tmp_path) == "owner_mismatch"


def test_T5_5_core_only_key(tmp_path):
    """T5.5 L5: `entries:` outside core.yaml -> core_only_key (renamed code)."""
    write_repo(tmp_path, docs_with(lambda d: d["pack-django"].update(entries=[])))
    assert code_of(tmp_path) == "core_only_key"


def test_T5_6_duplicate_id(tmp_path):
    """T5.6 L6: duplicate entry id, and duplicate binding id across files."""
    write_repo(
        tmp_path,
        docs_with(lambda d: d["core"]["entries"].append(dict(d["core"]["entries"][0]))),
    )
    assert code_of(tmp_path) == "duplicate_id"

    def dup_binding(d):
        b = judgment("core:code-review/code", "code-review", ["x"])
        d["pack-django"]["bindings"].append(b)

    write_repo(tmp_path, docs_with(dup_binding))
    assert code_of(tmp_path) == "duplicate_id"


def test_T5_7_binding_namespace(tmp_path):
    """T5.7 L7: binding id namespace must equal the owner."""
    write_repo(
        tmp_path,
        docs_with(
            lambda d: binding(d, "pack-django", "pack-django:lint/django").update(id="core:x")
        ),
    )
    assert code_of(tmp_path) == "binding_namespace"
    write_repo(
        tmp_path,
        docs_with(
            lambda d: binding(d, "pack-django", "pack-django:lint/django").update(id="pack-astro:x")
        ),
    )
    assert code_of(tmp_path) == "binding_namespace"


def test_T5_8_unknown_entry(tmp_path):
    """T5.8 L8: a binding references an unknown entry."""
    write_repo(
        tmp_path,
        docs_with(lambda d: binding(d, "project", "project:code-review/docs").update(entry="nope")),
    )
    assert code_of(tmp_path) == "unknown_entry"


def test_T5_9_kind_mismatch(tmp_path):
    """T5.9 L9: binding kind != entry kind."""
    write_repo(
        tmp_path,
        docs_with(
            lambda d: binding(d, "project", "project:code-review/docs").update(kind="deterministic")
        ),
    )
    assert code_of(tmp_path) == "kind_mismatch"


def test_T5_10_agent_missing(tmp_path):
    """T5.10 L10: judgment binding's agent file absent."""
    write_repo(
        tmp_path,
        docs_with(
            lambda d: binding(d, "project", "project:code-review/docs").update(agent="ghost")
        ),
    )
    assert code_of(tmp_path) == "agent_missing"


def test_T5_11_tool_missing(tmp_path):
    """T5.11 L11: deterministic tool absent, nonexistent, or not executable."""
    write_repo(tmp_path, docs_with(lambda d: binding(d, "core", "core:lint/all").pop("tool")))
    assert code_of(tmp_path) == "tool_missing"
    write_repo(
        tmp_path,
        docs_with(lambda d: binding(d, "core", "core:lint/all").update(tool="scripts/none.sh")),
    )
    assert code_of(tmp_path) == "tool_missing"
    write_repo(tmp_path)
    os.chmod(tmp_path / "scripts/gates/lint.sh", 0o644)
    assert code_of(tmp_path) == "tool_missing"


def test_T5_12_posture_invalid(tmp_path):
    """T5.12 L12: posture absent or invalid -> posture_invalid, rule id in the message."""
    write_repo(tmp_path, docs_with(lambda d: binding(d, "core", "core:ui/markup").pop("posture")))
    assert code_of(tmp_path) == "posture_invalid"
    write_repo(tmp_path)
    (tmp_path / "contract/dimensions/postures/review-read-only.hos.json").unlink()
    with pytest.raises(RegistryError) as exc:
        dr.load(tmp_path)
    assert exc.value.code == "posture_invalid" and "V2" in exc.value.message
    write_repo(
        tmp_path,
        docs_with(lambda d: binding(d, "core", "core:ui/markup").update(posture="unknown")),
    )
    with pytest.raises(RegistryError) as exc:
        dr.load(tmp_path)
    assert exc.value.code == "posture_invalid" and "V1" in exc.value.message


def test_T5_13_bad_timeout(tmp_path):
    """T5.13 L13: timeout absent, non-int, < 30, > 1800."""
    for bad in (None, "300", 29, 1801, True):

        def mut(d, bad=bad):
            b = binding(d, "core", "core:lint/all")
            b.pop("timeout_seconds")
            if bad is not None:
                b["timeout_seconds"] = bad

        write_repo(tmp_path, docs_with(mut))
        assert code_of(tmp_path) == "bad_timeout", bad


def test_T5_14_bad_predicate(tmp_path):
    """T5.14 L14: predicate absent, include empty/absent, or a bad regex."""
    for pred in (
        None,
        {"include": []},
        {"exclude": ["a"]},
        {"include": ["("]},
        {"include": ["a"], "exclude": ["["]},
    ):

        def mut(d, pred=pred):
            b = binding(d, "core", "core:lint/all")
            b.pop("predicate")
            if pred is not None:
                b["predicate"] = pred

        write_repo(tmp_path, docs_with(mut))
        assert code_of(tmp_path) == "bad_predicate", pred


def _suppress(d: dict, target: str, reason: str | None = "because") -> None:
    item = {"binding": target}
    if reason is not None:
        item["reason"] = reason
    d["project"]["suppress"] = [item]


def test_T5_15_suppress_unknown(tmp_path):
    """T5.15 L15: suppress names an unknown binding."""
    write_repo(tmp_path, docs_with(lambda d: _suppress(d, "pack-django:nope")))
    assert code_of(tmp_path) == "suppress_unknown"


def test_T5_16_T5_26_suppress_core(tmp_path):
    """T5.16 / T5.26 L16: suppressing a core: binding -> suppress_core."""
    write_repo(tmp_path, docs_with(lambda d: _suppress(d, "core:lint/all")))
    assert code_of(tmp_path) == "suppress_core"


def test_T5_17_suppress_no_reason(tmp_path):
    """T5.17 L17: suppress reason absent, empty, or whitespace-only."""
    for reason in (None, "", "   \n"):
        write_repo(
            tmp_path, docs_with(lambda d, r=reason: _suppress(d, "pack-django:lint/django", r))
        )
        assert code_of(tmp_path) == "suppress_no_reason", reason


def test_T5_18_project_only_key(tmp_path):
    """T5.18 L18: `suppress:` outside project.yaml -> project_only_key (renamed code)."""
    write_repo(
        tmp_path,
        docs_with(lambda d: d["pack-django"].update(suppress=[{"binding": "x", "reason": "y"}])),
    )
    assert code_of(tmp_path) == "project_only_key"


def test_T5_19_entry_unbound(tmp_path):
    """T5.19 L19: an entry whose every binding is suppressed -> entry_unbound."""

    def mut(d):
        d["core"]["bindings"] = [b for b in d["core"]["bindings"] if b["id"] != "core:ui/markup"]
        d["pack-django"]["bindings"].append(judgment("pack-django:ui/t", "ui", [r"\.html$"]))
        _suppress(d, "pack-django:ui/t")

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "entry_unbound"
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(bindings=[])))
    assert code_of(tmp_path) == "entry_unbound"


def test_T5_20_stale_pack_file(tmp_path):
    """T5.20 L20: pack-<n>.yaml whose pack is not in the resolved set."""
    write_repo(tmp_path, packs=[])
    assert code_of(tmp_path) == "stale_pack_file"


def test_T5_21_prompt_missing(tmp_path):
    """T5.21 L21: judgment prompt_template absent or file missing."""
    write_repo(
        tmp_path, docs_with(lambda d: binding(d, "core", "core:ui/markup").pop("prompt_template"))
    )
    assert code_of(tmp_path) == "prompt_missing"
    write_repo(
        tmp_path,
        docs_with(lambda d: binding(d, "core", "core:ui/markup").update(prompt_template="nope.md")),
    )
    assert code_of(tmp_path) == "prompt_missing"


# --- T5.22-T5.27, T5.29: resolution --------------------------------------


def test_T5_22_three_layer_resolves(tmp_path):
    """T5.22: core + pack-django + project resolves to the expected binding set."""
    write_repo(tmp_path)
    reg = dr.load(tmp_path)
    assert set(reg.bindings) == {
        "core:code-review/code",
        "core:lint/all",
        "core:ui/markup",
        "pack-django:code-review/app",
        "pack-django:lint/django",
        "project:code-review/docs",
    }
    assert reg.packs == ("django",) and reg.schema == SCHEMA
    assert reg.source_files == (
        "contract/dimensions/core.yaml",
        "contract/dimensions/pack-django.yaml",
        "contract/dimensions/project.yaml",
    )
    assert {b.owner for b in reg.bindings.values()} == {"core", "pack", "project"}


def _two_packs() -> dict:
    d = default_docs()
    d["pack-astro"] = {
        "schema": SCHEMA,
        "schema_version": 1,
        "owner": "pack",
        "pack": "astro",
        "bindings": [
            judgment("pack-astro:code-review/astro", "code-review", [r"\.astro$"]),
            deterministic("pack-astro:lint/astro", "lint", [r"\.astro$"]),
        ],
    }
    return d


def test_T5_23_both_packs_both_bindings(tmp_path):
    """T5.23: django + astro both bind the shared lint/code-review entries with own predicates."""
    write_repo(tmp_path, _two_packs(), packs=["django", "astro"])
    reg = dr.load(tmp_path)
    for bid, pat in (("pack-django:lint/django", r"\.py$"), ("pack-astro:lint/astro", r"\.astro$")):
        assert reg.bindings[bid].predicate.include == (pat,)
    assert reg.packs == ("django", "astro")
    assert "pack-astro:code-review/astro" in reg.bindings


def test_T5_24_only_astro(tmp_path):
    """T5.24: only astro in the pack set -> only that pack's bindings (a stale django file is L20)."""
    docs = _two_packs()
    docs["pack-django"] = None
    write_repo(tmp_path, docs, packs=["astro"])
    reg = dr.load(tmp_path)
    assert "pack-astro:lint/astro" in reg.bindings
    assert not any(b.startswith("pack-django") for b in reg.bindings)


def test_T5_25_suppress_pack_binding_entry_still_resolves(tmp_path):
    """T5.25: suppressing a pack binding removes it; the entry survives via core and is planned."""
    write_repo(tmp_path, docs_with(lambda d: _suppress(d, "pack-django:lint/django")))
    reg = dr.load(tmp_path)
    assert "pack-django:lint/django" not in reg.bindings
    assert reg.suppressions == {"pack-django:lint/django": "because"}
    assert "lint" in reg.entries
    plan = dr.resolve_for_diff(reg, ["a.py"])
    assert any(p.binding.entry == "lint" and p.applicable for p in plan)


def test_T5_27_plan_reason_always_non_empty(tmp_path):
    """T5.27: resolve_for_diff gives a non-empty reason in both states; re.search semantics."""
    write_repo(tmp_path)
    reg = dr.load(tmp_path)
    plan = dr.resolve_for_diff(reg, ["app/views.py", "tests/test_x.py", "README.md"])
    assert plan and all(p.reason for p in plan)
    by_id = {p.binding.id: p for p in plan}
    code = by_id["core:code-review/code"]
    assert code.applicable and code.matched_files == ("app/views.py",)  # exclude ^tests/
    assert code.reason == "binding core:code-review/code matched 1 changed file(s)"
    ui = by_id["core:ui/markup"]
    assert not ui.applicable and ui.matched_files == () and ui.reason
    assert {p.applicable for p in plan} == {True, False}
    assert [p.reason for p in dr.resolve_for_diff(reg, [])] != [""]


def test_T5_29_deterministic(tmp_path):
    """T5.29: two load() calls give byte-identical to_json(); digest covers schema + packs."""
    write_repo(tmp_path)
    a = json.dumps(dr.to_json(dr.load(tmp_path)))
    b = json.dumps(dr.to_json(dr.load(tmp_path)))
    assert a == b
    other = tmp_path / "other"
    write_repo(other, packs=["django", "astro"], docs=_two_packs())
    assert dr.load(other).digest != dr.load(tmp_path).digest


# --- T5.32, T5.34-T5.43: Amendment C --------------------------------------


def test_T5_32_stale_pack_ignores_config_sh_PACK(tmp_path):
    """T5.32 (re-pointed): a pack file whose pack is absent from resolved-packs.txt is
    stale even when config.sh says PACK=<n> (PACK= is never read)."""
    write_repo(tmp_path, packs=[])
    assert code_of(tmp_path) == "stale_pack_file"
    cfg = tmp_path / "scripts" / "framework" / "config.sh"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('PACK="django"\n')
    assert code_of(tmp_path) == "stale_pack_file"


def test_T5_34_unknown_kind(tmp_path):
    """T5.34 L22: schema argument not a key of KINDS -> unknown_kind."""
    write_repo(tmp_path)
    with pytest.raises(RegistryError) as exc:
        dr.load_registry(tmp_path, "hos.nope")
    assert exc.value.code == "unknown_kind"


def test_T5_35_unknown_key(tmp_path):
    """T5.35 L23: a top-level key outside the closed grammar (a typo is never ignored)."""

    def mut(d):
        d["core"]["binding"] = d["core"].pop("bindings")

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "unknown_key"


def test_T5_36_bad_pack_set(tmp_path):
    """T5.36 L24: absent file, bad slug, duplicate slug, whitespace; explicit duplicate."""
    write_repo(tmp_path, packs=None)
    assert code_of(tmp_path) == "bad_pack_set"
    rp = tmp_path / "contract" / "resolved-packs.txt"
    for text in (
        "Django\n",
        "django\ndjango\n",
        " django\n",
        "django \n",
        "-x\n",
        "a b\n",
        "dj\r\n",
    ):
        rp.write_text(text)
        assert code_of(tmp_path) == "bad_pack_set", repr(text)
    rp.write_bytes(b"\xff\xfe")
    assert code_of(tmp_path) == "bad_pack_set"
    rp.write_text("django\n")
    assert code_of(tmp_path, packs=["django", "django"]) == "bad_pack_set"
    assert code_of(tmp_path, packs=["Bad"]) == "bad_pack_set"
    # Zero slug lines is valid and means "no packs".
    rp.write_text("# only a comment\n\n")
    assert dr.read_resolved_packs(tmp_path) == ()


def test_T5_37_unexpected_file(tmp_path):
    """T5.37 L25: a regular non-dot file that is none of the four allowed names."""
    for name in ("project.yml", "pack-Django.yaml", "notes.txt"):
        write_repo(tmp_path)
        (tmp_path / "contract/dimensions" / name).write_text("x: 1\n")
        assert code_of(tmp_path) == "unexpected_file", name
        (tmp_path / "contract/dimensions" / name).unlink()
    # Allowed: the template, dotfiles, and subdirectories.
    (tmp_path / "contract/dimensions/project.yaml.template").write_text("# x\n")
    (tmp_path / "contract/dimensions/.hidden").write_text("x")
    assert dr.load(tmp_path).entries


def test_T5_38_kind_handler_failed(tmp_path, monkeypatch):
    """T5.38 L26: handler import failure, missing resolve/to_json, or a non-RegistryError raise."""
    write_repo(tmp_path)
    base = dr.KINDS[SCHEMA]
    from dataclasses import replace

    def patched(module: str):
        monkeypatch.setattr(dr, "KINDS", {SCHEMA: replace(base, handler_module=module)})

    patched("scripts.automation.lib.does_not_exist")
    assert code_of(tmp_path) == "kind_handler_failed"
    mod = types.ModuleType("scripts.automation.lib._bad_handler")
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    patched(mod.__name__)
    assert code_of(tmp_path) == "kind_handler_failed"
    mod.to_json = lambda r: {}  # type: ignore[attr-defined]
    mod.resolve = lambda docs, ctx: (_ for _ in ()).throw(KeyError("boom"))  # type: ignore[attr-defined]
    with pytest.raises(RegistryError) as exc:
        dr.load(tmp_path)
    assert exc.value.code == "kind_handler_failed" and "KeyError" in exc.value.message


def test_T5_39_path_escape(tmp_path):
    """T5.39 L27: absolute, '..', or symlink-escaping tool / prompt_template / agent paths."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.sh").write_text("#!/bin/sh\n")
    os.chmod(outside / "x.sh", 0o755)
    repo = tmp_path / "repo"
    for field, value in (
        ("tool", "/bin/true"),
        ("tool", "../outside/x.sh"),
        ("tool", "scripts/gates/../../../outside/x.sh"),
    ):
        write_repo(
            repo,
            docs_with(
                lambda d, f=field, v=value: binding(d, "core", "core:lint/all").update({f: v})
            ),
        )
        assert code_of(repo) == "path_escape", (field, value)
    write_repo(
        repo,
        docs_with(
            lambda d: binding(d, "core", "core:ui/markup").update(prompt_template="/etc/passwd")
        ),
    )
    assert code_of(repo) == "path_escape"
    write_repo(repo, docs_with(lambda d: binding(d, "core", "core:ui/markup").update(agent="../x")))
    assert code_of(repo) == "path_escape"
    # A symlink inside the repo pointing outside it.
    write_repo(repo)
    (repo / "scripts" / "link.sh").symlink_to(outside / "x.sh")
    write_repo(
        repo,
        docs_with(lambda d: binding(d, "core", "core:lint/all").update(tool="scripts/link.sh")),
    )
    assert code_of(repo) == "path_escape"


def test_T5_40_unknown_item_key(tmp_path):
    """T5.40 L28: a key outside an entry/binding/predicate/suppress grammar -> unknown_item_key."""
    muts = [
        lambda d: d["core"]["entries"][0].update(colour="red"),
        lambda d: binding(d, "core", "core:lint/all").update(timeout="5"),
        lambda d: binding(d, "core", "core:lint/all")["predicate"].update(incldue=["x"]),
        lambda d: d["project"].update(
            suppress=[{"binding": "pack-django:lint/django", "why": "x"}]
        ),
        lambda d: d["core"].update(bindings={"not": "a list"}),
        lambda d: d["core"]["entries"].append("string-entry"),
    ]
    for mut in muts:
        write_repo(tmp_path, docs_with(mut))
        assert code_of(tmp_path) == "unknown_item_key"


def test_T5_41_check_order(tmp_path, monkeypatch):
    """T5.41 / TD-D28: two-defect fixtures at the step boundaries; the earlier code wins."""
    # L20 before L3a: stale pack file AND a bad core schema.
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(schema="x")), packs=[])
    assert code_of(tmp_path) == "stale_pack_file"
    # L5 before L23: `entries:` in project.yaml is also an unknown project key.
    write_repo(tmp_path, docs_with(lambda d: d["project"].update(entries=[])))
    assert code_of(tmp_path) == "core_only_key"
    # L27 before L10: an agent that escapes is also a missing agent file.
    write_repo(
        tmp_path, docs_with(lambda d: binding(d, "core", "core:ui/markup").update(agent="../ghost"))
    )
    assert code_of(tmp_path) == "path_escape"

    # L17 before L19: a reasonless suppression that would also leave `ui` unbound.
    def mut(d):
        d["core"]["bindings"] = [b for b in d["core"]["bindings"] if b["id"] != "core:ui/markup"]
        d["pack-django"]["bindings"].append(judgment("pack-django:ui/t", "ui", [r"\.html$"]))
        _suppress(d, "pack-django:ui/t", "")

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "suppress_no_reason"
    # L2 before L26: missing PyYAML AND a broken handler -> yaml_unavailable.
    from dataclasses import replace

    write_repo(tmp_path)
    monkeypatch.setattr(
        dr,
        "KINDS",
        {SCHEMA: replace(dr.KINDS[SCHEMA], handler_module="scripts.automation.lib.nope")},
    )
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert code_of(tmp_path) == "yaml_unavailable"


def test_T5_42_resolved_closure_not_PACK(tmp_path):
    """T5.42 (TD-VF-16 regression): closure {node, astro} loads cleanly although
    config.sh says PACK="astro"."""
    docs = _two_packs()
    docs["pack-node"] = {
        "schema": SCHEMA,
        "schema_version": 1,
        "owner": "pack",
        "pack": "node",
        "bindings": [deterministic("pack-node:lint/node", "lint", [r"\.js$"])],
    }
    docs["pack-django"] = None
    write_repo(tmp_path, docs, packs=["node", "astro"])
    cfg = tmp_path / "scripts" / "framework" / "config.sh"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('PACK="astro"\n')
    reg = dr.load(tmp_path)
    assert reg.packs == ("node", "astro")
    assert reg.source_files[1:3] == (
        "contract/dimensions/pack-node.yaml",
        "contract/dimensions/pack-astro.yaml",
    )


def test_T5_43_wrapper_equals_engine(tmp_path):
    """T5.43: to_json(load(root)) is byte-identical to registry_to_json(...load_registry(...))."""
    write_repo(tmp_path)
    a = json.dumps(dr.to_json(dr.load(tmp_path)), sort_keys=True)
    b = json.dumps(dr.registry_to_json(SCHEMA, dr.load_registry(tmp_path, SCHEMA)), sort_keys=True)
    assert a == b
    assert dr.registered_schemas() == (SCHEMA,)
    with pytest.raises(RegistryError):
        dr.registry_to_json("hos.nope", object())


# --- T5.45: the seam, proven without a second real kind -------------------


class _SeamHandler:
    seen: list = []

    @staticmethod
    def build(behaviour: str) -> types.ModuleType:
        mod = types.ModuleType("scripts.automation.lib._seam_handler")
        _SeamHandler.seen = []

        def resolve(docs, ctx):
            _SeamHandler.seen.append((docs, ctx))
            if behaviour == "keyerror":
                raise KeyError("boom")
            if behaviour == "registry_error":
                raise dr.RegistryError("seam_own_code", "handler's own error")
            return {"paths": [d.path for d in docs]}

        mod.resolve = resolve  # type: ignore[attr-defined]
        mod.to_json = lambda r: r  # type: ignore[attr-defined]
        return mod


@pytest.fixture
def seam(tmp_path, monkeypatch):
    spec = dr.KindSpec(
        schema="hos.test-kind",
        schema_version=1,
        directory="contract/stages",
        pack_source="stages.yaml",
        handler_module="scripts.automation.lib._seam_handler",
        top_level_keys={
            "core": frozenset({"schema", "schema_version", "owner", "stages"}),
            "pack": frozenset({"schema", "schema_version", "owner", "pack", "extra"}),
            "project": frozenset({"schema", "schema_version", "owner", "tweak"}),
        },
        core_only_keys=frozenset({"stages"}),
        project_only_keys=frozenset({"tweak"}),
    )
    monkeypatch.setattr(dr, "KINDS", {**dr.KINDS, spec.schema: spec})

    def install(behaviour: str = "ok") -> None:
        mod = _SeamHandler.build(behaviour)
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    def write(name: str, **data) -> None:
        d = tmp_path / "contract" / "stages"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(
            yaml.safe_dump({"schema": "hos.test-kind", "schema_version": 1, **data})
        )

    (tmp_path / "contract").mkdir(exist_ok=True)
    (tmp_path / "contract" / "resolved-packs.txt").write_text("alpha\nbeta\n")
    install()
    return tmp_path, write, install


def test_T5_45_seam_generic_rules_fire_for_a_new_kind(seam):
    """T5.45: L1, L3a, L5, L20, L23 fire for a kind that is not dimensions."""
    root, write, _ = seam

    def code() -> str:
        with pytest.raises(RegistryError) as exc:
            dr.load_registry(root, "hos.test-kind")
        return exc.value.code

    assert code() == "core_missing"
    write("core.yaml", owner="core", stages=[])
    (root / "contract/stages/pack-gamma.yaml").write_text("x: 1\n")
    assert code() == "stale_pack_file"
    (root / "contract/stages/pack-gamma.yaml").unlink()
    write("pack-alpha.yaml", owner="pack", pack="alpha", stages=[])
    assert code() == "core_only_key"
    write("pack-alpha.yaml", owner="pack", pack="alpha", bogus=1)
    assert code() == "unknown_key"
    write("pack-alpha.yaml", owner="pack", pack="alpha")
    (root / "contract/stages/pack-alpha.yaml").write_text(
        yaml.safe_dump({"schema": SCHEMA, "schema_version": 1, "owner": "pack", "pack": "alpha"})
    )
    assert code() == "bad_schema"  # a dimensions file dropped into the other kind's directory


def test_T5_45_seam_handler_gets_layers_in_closure_order(seam):
    """T5.45: LayerDocs arrive core, packs in closure order, project; runtime reaches ctx unchanged."""
    root, write, _ = seam
    write("core.yaml", owner="core", stages=[])
    write("pack-beta.yaml", owner="pack", pack="beta")
    write("pack-alpha.yaml", owner="pack", pack="alpha")
    write("project.yaml", owner="project", tweak=1)
    runtime = {"cron_max_seconds": 123}
    out = dr.load_registry(root, "hos.test-kind", runtime=runtime)
    assert out == {
        "paths": [
            "contract/stages/core.yaml",
            "contract/stages/pack-alpha.yaml",
            "contract/stages/pack-beta.yaml",
            "contract/stages/project.yaml",
        ]
    }
    docs, ctx = _SeamHandler.seen[0]
    assert [d.owner for d in docs] == ["core", "pack", "pack", "project"]
    assert [d.pack for d in docs] == [None, "alpha", "beta", None]
    assert dict(ctx.runtime) == runtime and ctx.packs == ("alpha", "beta")
    assert dr.load_registry(root, "hos.test-kind") and dict(_SeamHandler.seen[-1][1].runtime) == {}


def test_T5_45_seam_handler_errors(seam):
    """T5.45: KeyError -> kind_handler_failed; the engine's own RegistryError keeps its code;
    exactly one engine module exists after load()."""
    root, write, install = seam
    write("core.yaml", owner="core", stages=[])
    install("keyerror")
    with pytest.raises(RegistryError) as exc:
        dr.load_registry(root, "hos.test-kind")
    assert exc.value.code == "kind_handler_failed"
    install("registry_error")
    with pytest.raises(RegistryError) as exc:
        dr.load_registry(root, "hos.test-kind")
    assert exc.value.code == "seam_own_code"
    engines = [
        n for n in sys.modules if n.startswith("scripts.") and n.endswith("dimension_registry")
    ]
    assert engines == ["scripts.automation.lib.dimension_registry"]
    assert not any(n in sys.modules for n in ("lib.dimension_registry", "dimension_registry"))
    assert sys.modules[engines[0]] is dr


def test_load_is_pure_of_framework_state(tmp_path):
    """The dimensions kind resolves its own module name to sys.modules without re-importing."""
    write_repo(tmp_path)
    before = sys.modules["scripts.automation.lib.dimension_registry"]
    dr.load(tmp_path)
    assert sys.modules["scripts.automation.lib.dimension_registry"] is before
    reg = dr.load(tmp_path)
    assert copy.deepcopy(dr.to_json(reg)) == dr.to_json(reg)
