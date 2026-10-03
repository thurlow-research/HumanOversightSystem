"""
Tests for the registry-loader hardening slice (ADR-1643 TD Amendment E):
duplicate keys / core integrity (#1937: L29, L30, L31), tool trust (#1932: L32
and the `tools:` extensions to L6/L11/L27/L28), predicate bounds (#1931: L33,
PL1), and the amended rule order (T5.64).

Test IDs follow TD §E.7. T5.63 (the real-tree `tools:` pin) is in
test_dimension_registry_data.py. All fixtures here are tmp_path registries.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import pytest
import yaml

from scripts.automation import dimension_registry_cli as cli
from scripts.automation.lib import dimension_registry as dr
from scripts.automation.lib.dimension_registry import RegistryError
from tests.automation.test_dimension_registry import (
    binding,
    code_of,
    default_docs,
    deterministic,
    docs_with,
    judgment,
    write_repo,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_REGIONS_SPEC = importlib.util.spec_from_file_location(
    "regions_for_t5_57", REPO_ROOT / "scripts" / "oversight" / "validators" / "regions.py"
)
assert _REGIONS_SPEC is not None and _REGIONS_SPEC.loader is not None
regions = importlib.util.module_from_spec(_REGIONS_SPEC)
sys.modules[_REGIONS_SPEC.name] = regions  # @dataclass resolves its module via sys.modules
_REGIONS_SPEC.loader.exec_module(regions)

CORE = "contract/dimensions/core.yaml"
PACK = "contract/dimensions/pack-django.yaml"
RESOLVED = "contract/resolved-packs.txt"
PACK_HEADER = "schema: hos.dimension-registry\nschema_version: 1\nowner: pack\npack: django\n"


def message_of(root: Path, **kw) -> str:
    with pytest.raises(RegistryError) as exc:
        dr.load(root, **kw)
    return exc.value.message


def path_of(root: Path, **kw) -> str | None:
    with pytest.raises(RegistryError) as exc:
        dr.load(root, **kw)
    return exc.value.path


def sha(root: Path, rel: str) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def install(root: Path, docs=None, *, packs=("django",), extra_rows: tuple[str, ...] = ()) -> Path:
    """An installed-shaped tree: a fixture registry, `.hos-release`, and a v2
    `.hos-manifest` with a WHOLE row for every HOS-owned registry input."""
    write_repo(root, docs, packs=packs)
    paths = [RESOLVED, CORE] + [f"contract/dimensions/pack-{s}.yaml" for s in packs]
    rows = [f"{p}\tWHOLE\t{sha(root, p)}" for p in paths if (root / p).exists()]
    (root / ".hos-release").write_text("v0.0.0\n")
    (root / ".hos-manifest").write_text(
        "# hos-manifest-schema: 2\n" + "".join(r + "\n" for r in (*rows, *extra_rows))
    )
    return root


def write_manifest_rows(root: Path, rows: list[str]) -> None:
    (root / ".hos-manifest").write_text("".join(r + "\n" for r in rows))


def make_tool(root: Path, rel: str, mode: int = 0o755) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n")
    p.chmod(mode)


def with_pattern(pattern: str):
    def mut(d):
        d["project"]["bindings"][0]["predicate"]["include"] = [pattern]

    return docs_with(mut)


# --- T5.54 — L29 duplicate_key ---------------------------------------------


def test_t5_54_duplicate_bindings_key_in_pack_file(tmp_path):
    """T5.54: a duplicated top-level `bindings:` is duplicate_key, naming key and line."""
    docs = default_docs()
    docs["pack-django"] = PACK_HEADER + "bindings: []\nbindings: []\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "duplicate_key"
    msg = message_of(tmp_path)
    assert "'bindings'" in msg and "line 6" in msg
    assert path_of(tmp_path) == PACK


def test_t5_54_duplicate_nested_predicate_key(tmp_path):
    """T5.54: a duplicated key inside a binding is duplicate_key (every depth)."""
    docs = default_docs()
    docs["pack-django"] = (
        PACK_HEADER
        + "bindings:\n  - id: pack-django:lint/x\n    predicate: {include: ['a']}\n"
        + "    predicate: {include: ['b']}\n"
    )
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "duplicate_key"
    msg = message_of(tmp_path)
    assert "'predicate'" in msg and "line 8" in msg


def test_t5_54_merge_key_repeated_explicitly(tmp_path):
    """T5.54: a key supplied by `<<:` and again explicitly is a duplicate."""
    docs = default_docs()
    docs["pack-django"] = PACK_HEADER + "base: &b {k: 1}\nmerged:\n  <<: *b\n  k: 2\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "duplicate_key"
    assert "'k'" in message_of(tmp_path)


def test_t5_54_unhashable_complex_key_is_bad_schema_not_handler_failure(tmp_path):
    """T5.54 (architect, round 1): `? [a, b]` is L3a bad_schema, never kind_handler_failed."""
    docs = default_docs()
    docs["pack-django"] = PACK_HEADER + "? [a, b]\n: 1\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "bad_schema"


def test_t5_54_deeply_nested_yaml_is_bad_schema(tmp_path):
    """L3a: a RecursionError from nesting depth maps to bad_schema, not a traceback."""
    docs = default_docs()
    docs["pack-django"] = PACK_HEADER + "x: " + "[" * 3000 + "]" * 3000 + "\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "bad_schema"
    assert "too deep" in message_of(tmp_path)


# --- T5.55 — L30 core_empty ------------------------------------------------


@pytest.mark.parametrize("how", ["absent", "null", "empty"])
def test_t5_55_core_empty(tmp_path, how):
    """T5.55: entries absent, null or [] is core_empty."""

    def mut(d):
        if how == "absent":
            del d["core"]["entries"]
        else:
            d["core"]["entries"] = None if how == "null" else []

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "core_empty"


def test_t5_55_non_list_entries_is_l28(tmp_path):
    """T5.55: `entries: "x"` falls through to L28, so L30 never hides a shape error."""
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(entries="x")))
    assert code_of(tmp_path) == "unknown_item_key"


# --- T5.56 — L31 installed_drift -------------------------------------------


def test_t5_56_skipped_without_release_marker(tmp_path):
    """T5.56: no `.hos-release` -> L31 is skipped, even beside a garbage manifest."""
    write_repo(tmp_path)
    (tmp_path / ".hos-manifest").write_bytes(b"\xff\xfe garbage\n\x00")
    assert dr.load(tmp_path).packs == ("django",)


def test_t5_56_installed_and_matching_is_green(tmp_path):
    """T5.56: all rows matching (v2) loads green."""
    assert dr.load(install(tmp_path)).packs == ("django",)


def test_t5_56_v1_rows_are_green(tmp_path):
    """T5.56: legacy 2-field rows are WHOLE."""
    install(tmp_path)
    rows = [f"{p}\t{sha(tmp_path, p)}" for p in (RESOLVED, CORE, PACK)]
    write_manifest_rows(tmp_path, rows)
    assert dr.load(tmp_path).packs == ("django",)


def test_t5_56_malformed_row_for_unrelated_path_is_ignored(tmp_path):
    """T5.56: a malformed row for another path never fails the load."""
    install(tmp_path, extra_rows=("other/path\tonly\tthree\tfour\tfive", "lonely-field"))
    assert dr.load(tmp_path).packs == ("django",)


def test_t5_56_explicit_packs_skips_resolved_packs_check(tmp_path):
    """T5.56: an explicit packs= does not check resolved-packs.txt."""
    install(tmp_path)
    (tmp_path / RESOLVED).write_text("django\nnode\n")
    assert dr.load(tmp_path, packs=["django"]).packs == ("django",)
    assert code_of(tmp_path) == "installed_drift"


def test_t5_56_no_manifest(tmp_path):
    """T5.56: `.hos-release` with no `.hos-manifest` is installed_drift."""
    install(tmp_path)
    (tmp_path / ".hos-manifest").unlink()
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == RESOLVED


def test_t5_56_dangling_release_symlink_counts(tmp_path):
    """T5.56: `.hos-release` is tested with lexists, so a dangling symlink counts."""
    write_repo(tmp_path)
    (tmp_path / ".hos-release").symlink_to(tmp_path / "nowhere")
    assert code_of(tmp_path) == "installed_drift"


def test_t5_56_no_core_row(tmp_path):
    """T5.56: no manifest row for core.yaml."""
    install(tmp_path)
    write_manifest_rows(tmp_path, [f"{p}\tWHOLE\t{sha(tmp_path, p)}" for p in (RESOLVED, PACK)])
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == CORE


def test_t5_56_two_core_rows(tmp_path):
    """T5.56: two manifest rows for core.yaml."""
    install(tmp_path)
    row = f"{CORE}\tWHOLE\t{sha(tmp_path, CORE)}"
    write_manifest_rows(
        tmp_path,
        [f"{RESOLVED}\tWHOLE\t{sha(tmp_path, RESOLVED)}", row, row],
    )
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == CORE


def test_t5_56_non_whole_core_row(tmp_path):
    """T5.56: a core row that is not WHOLE."""
    install(tmp_path)
    write_manifest_rows(
        tmp_path,
        [
            f"{RESOLVED}\tWHOLE\t{sha(tmp_path, RESOLVED)}",
            f"{CORE}\tREGION:x\t{sha(tmp_path, CORE)}",
        ],
    )
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == CORE


def test_t5_56_malformed_sha(tmp_path):
    """T5.56: a sha that is not 64 lowercase hex digits."""
    install(tmp_path)
    write_manifest_rows(
        tmp_path,
        [
            f"{RESOLVED}\tWHOLE\t{sha(tmp_path, RESOLVED)}",
            f"{CORE}\tWHOLE\t{sha(tmp_path, CORE).upper()}",
        ],
    )
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == CORE


def test_t5_56_core_trimmed_to_one_entry(tmp_path):
    """T5.56 (architect's case): a core trimmed to one entry passes L30 but not L31."""
    install(tmp_path)
    trimmed = default_docs()["core"]
    trimmed["entries"] = trimmed["entries"][:1]
    trimmed["bindings"] = [b for b in trimmed["bindings"] if b["entry"] == "code-review"]
    (tmp_path / CORE).write_text(yaml.safe_dump(trimmed))
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == CORE


def test_t5_56_edited_pack_file(tmp_path):
    """T5.56: an edited pack-django.yaml."""
    install(tmp_path)
    (tmp_path / PACK).write_text((tmp_path / PACK).read_text() + "\n# local edit\n")
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == PACK


def test_t5_56_edited_resolved_packs_with_packs_none(tmp_path):
    """T5.56: an edited resolved-packs.txt (packs=None)."""
    install(tmp_path)
    (tmp_path / RESOLVED).write_text("django\nnode\n")
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == RESOLVED


def test_t5_56_dropped_slug_is_drift_not_stale_pack_file(tmp_path):
    """T5.56 (architect, round 1): L31 runs before L20."""
    install(tmp_path)
    (tmp_path / RESOLVED).write_text("# generated\n")
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == RESOLVED


def test_t5_56_deleted_pack_file_with_row_is_drift_absent(tmp_path):
    """T5.56 (architect, round 1): a deleted pack file whose row and slug remain."""
    install(tmp_path)
    (tmp_path / PACK).unlink()
    assert code_of(tmp_path) == "installed_drift"
    assert path_of(tmp_path) == PACK
    assert "absent" in message_of(tmp_path)


def test_t5_56_pack_without_file_or_row_is_skipped(tmp_path):
    """T5.56 / TD-D37: a pack that ships no dimensions file has neither file nor row."""
    install(tmp_path, packs=("django", "node"))
    assert dr.load(tmp_path).packs == ("django", "node")


# --- T5.57 — manifest-row parity with regions.parse_manifest_line -----------


@pytest.mark.parametrize(
    "form",
    ["v2", "v1", "comment", "blank", "whitespace", "marker", "four-field", "non-whole"],
)
def test_t5_57_row_lookup_parity_with_parse_manifest_line(tmp_path, form):
    """T5.57: the loader accepts the core row iff regions.parse_manifest_line yields
    (core, WHOLE, sha); where the parser raises ValueError the loader reports drift."""
    install(tmp_path)
    digest = sha(tmp_path, CORE)
    line = {
        "v2": f"{CORE}\tWHOLE\t{digest}",
        "v1": f"{CORE}\t{digest}",
        "comment": f"# {CORE}\tWHOLE\t{digest}",
        "blank": "",
        "whitespace": "  \t ",
        "marker": "# hos-manifest-schema: 2",
        "four-field": f"{CORE}\tWHOLE\t{digest}\textra",
        "non-whole": f"{CORE}\tREGION:x\t{digest}",
    }[form]
    try:
        parsed = regions.parse_manifest_line(line)
    except ValueError:
        parsed = None
    accepts = parsed == (CORE, "WHOLE", digest)
    write_manifest_rows(
        tmp_path,
        [
            f"{RESOLVED}\tWHOLE\t{sha(tmp_path, RESOLVED)}",
            line,
            f"{PACK}\tWHOLE\t{sha(tmp_path, PACK)}",
        ],
    )
    if accepts:
        assert dr.load(tmp_path).packs == ("django",)
    else:
        assert code_of(tmp_path) == "installed_drift"


def test_t5_57_whitespace_only_line_between_rows_is_skipped(tmp_path):
    """T5.57 (architect, round 1): whitespace-only lines are blank, as the parser treats them."""
    install(tmp_path)
    text = (tmp_path / ".hos-manifest").read_text()
    (tmp_path / ".hos-manifest").write_text("   \t \n" + text + "  \n")
    assert dr.load(tmp_path).packs == ("django",)


def test_t5_57_crlf_manifest_row_is_drift_naming_crlf(tmp_path):
    """T5.56/T5.57: a CRLF row is not rewritten before hashing; it fails closed as
    installed_drift and the message says why."""
    install(tmp_path)
    rows = [
        f"{RESOLVED}\tWHOLE\t{sha(tmp_path, RESOLVED)}\n",
        f"{CORE}\tWHOLE\t{sha(tmp_path, CORE)}\r\n",
        f"{PACK}\tWHOLE\t{sha(tmp_path, PACK)}\n",
    ]
    (tmp_path / ".hos-manifest").write_bytes("".join(rows).encode())
    assert code_of(tmp_path) == "installed_drift"
    assert "CRLF" in message_of(tmp_path)


def test_t5_57_crlf_comment_line_is_skipped(tmp_path):
    """T5.57: a CRLF `#` comment line is skipped like any comment."""
    install(tmp_path)
    data = (tmp_path / ".hos-manifest").read_bytes()
    (tmp_path / ".hos-manifest").write_bytes(b"# a comment\r\n" + data)
    assert dr.load(tmp_path).packs == ("django",)


# --- T5.58 — L32 and the `tools:` extensions --------------------------------


def _bind_tool(docs: dict, where: str, tool: str) -> None:
    if where == "pack-django":
        binding(docs, "pack-django", "pack-django:lint/django")["tool"] = tool
    else:
        docs["project"]["bindings"].append(
            deterministic("project:lint/mine", "lint", [r"\.py$"], tool=tool)
        )


@pytest.mark.parametrize("where", ["pack-django", "project"])
@pytest.mark.parametrize("tool", ["scripts/gates/stub.sh", "./scripts/gates/lint.sh"])
def test_t5_58_unlisted_executable_is_tool_untrusted(tmp_path, where, tool):
    """T5.58: an executable tool not listed in CORE's tools: is tool_untrusted, in any layer;
    a `./` spelling of a listed tool is not exact equality."""
    docs = default_docs()
    _bind_tool(docs, where, tool)
    write_repo(tmp_path, docs)
    make_tool(tmp_path, "scripts/gates/stub.sh")
    assert code_of(tmp_path) == "tool_untrusted"


def test_t5_58_listed_tool_in_pack_and_project_is_green(tmp_path):
    """T5.58: a listed tool loads green."""
    docs = default_docs()
    _bind_tool(docs, "project", "scripts/gates/lint.sh")
    write_repo(tmp_path, docs)
    assert "project:lint/mine" in dr.load(tmp_path).bindings


def test_t5_58_tools_in_pack_file_is_core_only_key(tmp_path):
    """T5.58: `tools:` outside core.yaml fails L5."""
    docs = docs_with(lambda d: d["pack-django"].update(tools=["scripts/gates/lint.sh"]))
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "core_only_key"


@pytest.mark.parametrize(
    "bad",
    ["x", {"a": 1}, [1], [""], ["scripts//gates/lint.sh"], ["./scripts/gates/lint.sh"], ["a/"]],
)
def test_t5_58_bad_tools_shape_is_unknown_item_key(tmp_path, bad):
    """T5.58 (L28): non-list, non-string, empty and non-normal-form entries."""
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(tools=bad)))
    assert code_of(tmp_path) == "unknown_item_key"


def test_t5_58_large_tools_entry_gives_a_short_message(tmp_path):
    """L28: a huge non-string tools entry is bounded in the error message."""
    big = {"a": "x" * 5000, "b": ["y" * 5000]}
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(tools=[big])))
    assert code_of(tmp_path) == "unknown_item_key"
    assert len(message_of(tmp_path)) < 250


def test_t5_58_duplicate_tools_entry(tmp_path):
    """T5.58 (L6): a repeated tools: path is duplicate_id."""
    tool = "scripts/gates/lint.sh"
    write_repo(tmp_path, docs_with(lambda d: d["core"].update(tools=[tool, tool])))
    assert code_of(tmp_path) == "duplicate_id"


def test_t5_58_listed_unbound_tool_absent_is_tool_missing(tmp_path):
    """T5.58 (L11): a listed tool that no binding names must still exist."""
    docs = docs_with(lambda d: d["core"]["tools"].append("scripts/gates/absent.sh"))
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "tool_missing"


def test_t5_58_listed_unbound_tool_not_executable_is_tool_missing(tmp_path):
    """T5.58 (L11): a listed, unbound, non-executable tool."""
    docs = docs_with(lambda d: d["core"]["tools"].append("scripts/gates/plain.sh"))
    write_repo(tmp_path, docs)
    make_tool(tmp_path, "scripts/gates/plain.sh", 0o644)
    assert code_of(tmp_path) == "tool_missing"


def test_t5_58_listed_escaping_tool_is_path_escape(tmp_path):
    """T5.58 (L27): a listed `../x.sh` is path_escape."""
    docs = docs_with(lambda d: d["core"]["tools"].append("../x.sh"))
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "path_escape"


# --- T5.59 — the digest covers the allowlist --------------------------------


def test_t5_59_tools_change_the_digest_and_json_is_sorted(tmp_path):
    """T5.59: adding a tools: entry changes the digest; to_json()['tools'] is sorted."""
    base = tmp_path / "a"
    write_repo(base)
    first = dr.load(base)
    assert first.tools == ("scripts/gates/lint.sh",)

    other = tmp_path / "b"
    write_repo(other, docs_with(lambda d: d["core"]["tools"].insert(0, "scripts/gates/z.sh")))
    make_tool(other, "scripts/gates/z.sh")
    second = dr.load(other)
    assert second.digest != first.digest
    assert dr.to_json(second)["tools"] == ["scripts/gates/lint.sh", "scripts/gates/z.sh"]


# --- T5.60 — L33 unsafe_pattern ---------------------------------------------

UNSAFE = [
    "(a+)+$",
    "a*a*b",
    "a|b",
    "x{2}",
    ".*?",
    "a^",
    "$a",
    "[[:alpha:]]",
    "(?s)x",
    "a" * 257,
    ".*" + "a" * 17,
    "(?i).*" + "a" * 249 + "b",
    "[]a]",  # empty class (a leading `]` is a literal to re, an empty class to the scanner)
    r"[\d]",  # `\` + non-punctuation inside a class
    r"\B",
    r"\Z",
    r"\x41",
    "a+$b",  # a `$` that is not terminal, after a quantifier
    ".*" + r"\b" * 17,
]
SAFE = [
    r"\bsecret",
    "(?i)pii",
    r"/test_[^/]*\.py$",
    ".*",
    r"\d+",
    ".*" + "a" * 16,
    ".*" + r"\b" * 16,
    "",
    "^docs/",
    r"^src/.*\.ts$",
]


@pytest.mark.parametrize("pattern", UNSAFE, ids=lambda p: p[:24])
def test_t5_60_unsafe_pattern(tmp_path, pattern):
    """T5.60: patterns outside the closed single-quantifier subset."""
    write_repo(tmp_path, with_pattern(pattern))
    assert code_of(tmp_path) == "unsafe_pattern"


@pytest.mark.parametrize("pattern", [r"\1", r"\b*"])
def test_t5_60_outside_the_subset_but_uncompilable_is_caught_by_l14_first(tmp_path, pattern):
    """T5.60: `\\1` and `\\b*` are outside TD-D44's subset, but Python cannot compile
    them, so through load() L14 reports bad_predicate before L33 can run. The scanner
    itself still rejects them."""
    assert dr._unsafe_pattern(pattern) is not None
    write_repo(tmp_path, with_pattern(pattern))
    assert code_of(tmp_path) == "bad_predicate"


@pytest.mark.parametrize(
    ("pattern", "fragment"),
    [
        ("a" * 257, "longer than 256 characters"),
        ("a|b", "unsupported construct '|'"),
        ("a+$b", "'$' is only allowed at the end"),
        (r"\B", "unsupported escape '\\B'"),
        (r"\x41", "unsupported escape '\\x'"),
        ("[a[b]", "nested '[' in a character class"),
        ("[]a]", "empty or unterminated character class"),
        ("[ab", "empty or unterminated character class"),
        (r"[\d]", "unsupported escape in a character class"),
        (r"\b*", "'\\b' cannot be quantified"),
        (".*" + r"\b" * 17, "more than 16 pieces after the quantifier"),
        ("a**", "more than one quantifier"),
        ("a*b*", "more than one quantifier"),
        (".*" + "a" * 17, "more than 16 pieces after the quantifier"),
    ],
)
def test_t5_60_scanner_branch_messages(pattern, fragment):
    """T5.60: one representative per scanner branch names its reason."""
    assert fragment in (dr._unsafe_pattern(pattern) or "")


def test_t5_60_unsafe_pattern_message_is_bounded(tmp_path):
    """L33 messages interpolate the pattern through _short()."""
    write_repo(tmp_path, with_pattern("a" * 257))
    assert len(message_of(tmp_path)) < 250


def test_t5_60_the_256_character_one_quantifier_shape_is_rejected():
    """T5.60 (architect, round 1): the draft grammar admitted this at 4.5 s per pair."""
    pattern = "(?i).*" + "a" * 249 + "b"
    assert len(pattern) == 256
    assert "pieces" in dr._unsafe_pattern(pattern)


@pytest.mark.parametrize("pattern", SAFE, ids=lambda p: p[:24] or "empty")
def test_t5_60_safe_pattern(tmp_path, pattern):
    """T5.60: patterns inside the subset load green."""
    write_repo(tmp_path, with_pattern(pattern))
    assert dr.load(tmp_path).bindings["project:code-review/docs"]


def test_t5_60_uncompilable_pattern_stays_bad_predicate(tmp_path):
    """T5.60: L33 follows L14."""
    write_repo(tmp_path, with_pattern("("))
    assert code_of(tmp_path) == "bad_predicate"


def test_t5_60_exclude_patterns_are_checked(tmp_path):
    """T5.60: L33 covers predicate.exclude as well as include."""

    def mut(d):
        d["project"]["bindings"][0]["predicate"]["exclude"] = ["a|b"]

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "unsafe_pattern"


# --- T5.61 — ReDoS regression (#1931) ---------------------------------------


def test_t5_61_nested_quantifier_never_reaches_a_plan(tmp_path):
    """T5.61: `(a+)+$` in a project binding fails load()."""
    write_repo(tmp_path, with_pattern("(a+)+$"))
    assert code_of(tmp_path) == "unsafe_pattern"


def test_t5_61_worst_admissible_shape_is_fast_at_the_pl1_bound(tmp_path):
    """T5.61 (architect, round 1): `(?i).*` + 15xa + `b` against a 1024-byte path (~20 ms)."""
    write_repo(tmp_path, with_pattern("(?i).*" + "a" * 15 + "b"))
    reg = dr.load(tmp_path)
    start = time.perf_counter()
    dr.resolve_for_diff(reg, ["a" * 1024])
    assert time.perf_counter() - start < 2.0


# --- T5.62 — PL1 bad_changed_file -------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["a" * 1025, "", "a\nb", "a\x00b", "€" * 342],
    ids=["1025-bytes", "empty", "newline", "nul", "342-three-byte-chars"],
)
def test_t5_62_bad_changed_file(tmp_path, path):
    """T5.62: over 1024 UTF-8 bytes (bytes, not characters), empty, newline, NUL."""
    write_repo(tmp_path)
    reg = dr.load(tmp_path)
    with pytest.raises(RegistryError) as exc:
        dr.resolve_for_diff(reg, ["ok.py", path])
    assert exc.value.code == "bad_changed_file"


def test_t5_62_first_bad_path_wins_in_input_order(tmp_path):
    """T5.62: paths are checked in input order."""
    write_repo(tmp_path)
    reg = dr.load(tmp_path)
    with pytest.raises(RegistryError) as exc:
        dr.resolve_for_diff(reg, ["ok.py", "first\nbad", "x" * 2000])
    assert "first" in exc.value.message


def test_t5_62_1024_byte_path_is_accepted(tmp_path):
    """T5.62: the bound is inclusive."""
    write_repo(tmp_path)
    assert dr.resolve_for_diff(dr.load(tmp_path), ["a" * 1024])


def test_t5_62_cli_plan_exits_1_naming_the_code(tmp_path, capsys):
    """T5.62: the CLI's RegistryError handler turns PL1 into exit 1."""
    write_repo(tmp_path)
    rc = cli.main(["plan", "--changed-file", "a" * 1025], repo_root=tmp_path)
    err = capsys.readouterr().err
    assert rc == 1 and "bad_changed_file" in err


# --- T5.64 — the amended rule order -----------------------------------------


def test_t5_64_l25_before_l31(tmp_path):
    """T5.64 (L25, L31): an unexpected file beats installed drift."""
    install(tmp_path)
    (tmp_path / CORE).write_text((tmp_path / CORE).read_text() + "\n# edit\n")
    (tmp_path / "contract" / "dimensions" / "project.yml").write_text("x: 1\n")
    assert code_of(tmp_path) == "unexpected_file"


def test_t5_64_l31_before_l20(tmp_path):
    """T5.64 (L31, L20): a dropped slug with its pack file left behind is drift."""
    install(tmp_path)
    (tmp_path / RESOLVED).write_text("")
    assert code_of(tmp_path) == "installed_drift"


def test_t5_64_l31_before_l3a_shape(tmp_path):
    """T5.64 (L31, L3a-shape): drifted core that is not even a mapping is drift."""
    install(tmp_path)
    (tmp_path / CORE).write_text("- a\n- b\n")
    assert code_of(tmp_path) == "installed_drift"


def test_t5_64_l3a_parse_before_l29(tmp_path):
    """T5.64 (L3a-parse, L29): a duplicate before a syntax error is bad_schema."""
    docs = default_docs()
    docs["core"] = "a: 1\na: 2\nb: [unclosed\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "bad_schema"


def test_t5_64_l29_before_l3a_shape(tmp_path):
    """T5.64 (L29, L3a-shape): a duplicate key beats a wrong schema value."""
    docs = default_docs()
    docs["core"] = "schema: wrong\nschema: other\n"
    write_repo(tmp_path, docs)
    assert code_of(tmp_path) == "duplicate_key"


def test_t5_64_l30_before_l28(tmp_path):
    """T5.64 (L30, L28): an empty core beats a malformed tools: list."""

    def mut(d):
        d["core"]["entries"] = []
        d["core"]["tools"] = "x"

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "core_empty"


def test_t5_64_l14_before_l33(tmp_path):
    """T5.64 (L14, L33): an uncompilable pattern in a later binding beats an unsafe earlier one."""

    def mut(d):
        d["project"]["bindings"] = [
            judgment("project:code-review/a", "code-review", ["a|b"]),
            judgment("project:code-review/b", "code-review", ["("]),
        ]

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "bad_predicate"


def test_t5_64_l33_before_l27(tmp_path):
    """T5.64 (L33, L27): an unsafe pattern in a later binding beats an earlier path escape."""

    def mut(d):
        d["project"]["bindings"] = [
            deterministic("project:lint/a", "lint", ["x"], tool="../x.sh"),
            judgment("project:code-review/b", "code-review", ["a|b"]),
        ]

    write_repo(tmp_path, docs_with(mut))
    assert code_of(tmp_path) == "unsafe_pattern"


def test_t5_64_l11_before_l32(tmp_path):
    """T5.64 (L11, L32): an absent tool in a later binding beats an earlier unlisted one."""

    def mut(d):
        d["project"]["bindings"] = [
            deterministic("project:lint/a", "lint", ["x"], tool="scripts/gates/stub.sh"),
            deterministic("project:lint/b", "lint", ["x"], tool="scripts/gates/absent.sh"),
        ]

    write_repo(tmp_path, docs_with(mut))
    make_tool(tmp_path, "scripts/gates/stub.sh")
    assert code_of(tmp_path) == "tool_missing"


def test_t5_64_l27_before_l32(tmp_path):
    """T5.64 (L27, L32): a path escape in a later binding beats an earlier unlisted tool."""

    def mut(d):
        d["project"]["bindings"] = [
            deterministic("project:lint/a", "lint", ["x"], tool="scripts/gates/stub.sh"),
            deterministic("project:lint/b", "lint", ["x"], tool="../x.sh"),
        ]

    write_repo(tmp_path, docs_with(mut))
    make_tool(tmp_path, "scripts/gates/stub.sh")
    assert code_of(tmp_path) == "path_escape"
