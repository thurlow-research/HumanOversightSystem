"""
dimension_registry.py — the schema-parametric registry loader (ADR-1643 AD-9,
TD §7 as amended by Amendment C; ADR-1644 SEAM-1).

L1 module. One engine, one ownership model, one static per-schema `KINDS`
table. The engine does everything that is the same for every kind (locating
files, the resolved pack set, YAML parsing, the generic rules, building the
ordered layer tuple) and then makes exactly one call, `handler.resolve(docs,
ctx)`. The dimensions kind is the only kind registered here; its handler lives
in this module (TD-D25). A future kind adds one `KINDS` row and one handler
module, and changes nothing else in the engine (§C.2.9).

The loader fails closed, always: every defect raises exactly one
`RegistryError`, and the first failure in TD-D28's fixed order wins.

Pure module: no argparse, no `__main__`, no `sys.argv`, no `os.environ`, no
network, no subprocess. PyYAML is imported lazily inside `load_registry` so a
missing dependency is always reachable as a `RegistryError` (L2).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from scripts.automation.lib import posture as _posture

DIMENSIONS_SCHEMA = "hos.dimension-registry"
RESOLVED_PACKS_PATH = "contract/resolved-packs.txt"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PACK_FILE_RE = re.compile(r"^pack-([^/]+)\.yaml$")
_BINDING_KINDS = frozenset({"judgment", "deterministic"})
_MIN_TIMEOUT_S = 30
_MAX_TIMEOUT_S = 1800


# ---------------------------------------------------------------------------
# Shared data shapes
# ---------------------------------------------------------------------------


class RegistryError(Exception):
    """A registry load failure. `code` is machine-stable (§C.2.6)."""

    def __init__(self, code: str, message: str, path: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


@dataclass(frozen=True)
class KindSpec:
    schema: str
    schema_version: int
    directory: str
    pack_source: str
    handler_module: str
    top_level_keys: Mapping[str, frozenset[str]]
    core_only_keys: frozenset[str]
    project_only_keys: frozenset[str]


@dataclass(frozen=True)
class LayerDoc:
    path: str
    owner: str
    pack: str | None
    data: Mapping[str, object]


@dataclass(frozen=True)
class LoadContext:
    repo_root: Path
    kind: KindSpec
    packs: tuple[str, ...]
    runtime: Mapping[str, object]


# Static, literal, reviewed table (§C.2.4). No runtime registration: "which
# kinds exist" must not depend on import order.
KINDS: Mapping[str, KindSpec] = MappingProxyType(
    {
        DIMENSIONS_SCHEMA: KindSpec(
            schema=DIMENSIONS_SCHEMA,
            schema_version=1,
            directory="contract/dimensions",
            pack_source="dimensions.yaml",
            handler_module="scripts.automation.lib.dimension_registry",
            top_level_keys={
                "core": frozenset({"schema", "schema_version", "owner", "entries", "bindings"}),
                "pack": frozenset({"schema", "schema_version", "owner", "pack", "bindings"}),
                "project": frozenset({"schema", "schema_version", "owner", "bindings", "suppress"}),
            },
            core_only_keys=frozenset({"entries"}),
            project_only_keys=frozenset({"suppress"}),
        ),
    }
)


# ---------------------------------------------------------------------------
# Engine (kind-generic)
# ---------------------------------------------------------------------------


def registered_schemas() -> tuple[str, ...]:
    return tuple(sorted(KINDS))


def _validate_pack_slugs(packs: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    for slug in packs:
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            raise RegistryError("bad_pack_set", f"invalid pack slug: {slug!r}")
        if slug in seen:
            raise RegistryError("bad_pack_set", f"duplicate pack slug: {slug!r}")
        seen.add(slug)
    return tuple(packs)


def read_resolved_packs(repo_root: str | Path) -> tuple[str, ...]:
    """§C.2.5's parser. Absent, unreadable or malformed ⟹ L24."""
    path = Path(repo_root) / RESOLVED_PACKS_PATH
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RegistryError(
            "bad_pack_set", f"cannot read resolved pack set: {exc}", RESOLVED_PACKS_PATH
        ) from None
    slugs: list[str] = []
    for line in text.split("\n"):
        if line == "" or line.startswith("#"):
            continue
        slugs.append(line)
    try:
        return _validate_pack_slugs(slugs)
    except RegistryError as exc:
        raise RegistryError("bad_pack_set", exc.message, RESOLVED_PACKS_PATH) from None


def _import_handler(spec: KindSpec):
    try:
        if spec.handler_module == __name__:
            module = sys.modules[__name__]
        else:
            module = importlib.import_module(spec.handler_module)
    except Exception as exc:
        raise RegistryError(
            "kind_handler_failed",
            f"cannot import handler {spec.handler_module}: {type(exc).__name__}: {exc}",
        ) from None
    for attr in ("resolve", "to_json"):
        if not callable(getattr(module, attr, None)):
            raise RegistryError(
                "kind_handler_failed", f"handler {spec.handler_module} lacks callable {attr}"
            )
    return module


def _parse_layer(
    yaml_mod, root: Path, rel: str, owner: str, pack: str | None, spec: KindSpec
) -> LayerDoc:
    """Per-file rules L3a, L3b, L4, L5, L18, L23, in that order."""
    try:
        data = yaml_mod.safe_load((root / rel).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml_mod.YAMLError) as exc:
        raise RegistryError("bad_schema", f"cannot parse YAML: {exc}", rel) from None
    if not isinstance(data, dict):
        raise RegistryError("bad_schema", "file is not a YAML mapping", rel)
    if data.get("schema") != spec.schema:
        raise RegistryError(
            "bad_schema", f"schema is {data.get('schema')!r}, expected {spec.schema!r}", rel
        )
    version = data.get("schema_version")
    if isinstance(version, bool) or version != spec.schema_version:
        raise RegistryError(
            "bad_schema_version",
            f"schema_version is {version!r}, expected {spec.schema_version}",
            rel,
        )
    if data.get("owner") != owner:
        raise RegistryError(
            "owner_mismatch", f"owner is {data.get('owner')!r}, expected {owner!r}", rel
        )
    if owner == "pack" and data.get("pack") != pack:
        raise RegistryError(
            "owner_mismatch", f"pack is {data.get('pack')!r}, expected {pack!r}", rel
        )
    if owner != "core":
        for key in sorted(spec.core_only_keys & data.keys()):
            raise RegistryError("core_only_key", f"{key!r} may only appear in core.yaml", rel)
    if owner != "project":
        for key in sorted(spec.project_only_keys & data.keys()):
            raise RegistryError("project_only_key", f"{key!r} may only appear in project.yaml", rel)
    for key in data:
        if key not in spec.top_level_keys[owner]:
            raise RegistryError("unknown_key", f"unknown top-level key {key!r}", rel)
    return LayerDoc(path=rel, owner=owner, pack=pack, data=data)


def load_registry(
    repo_root: str | Path,
    schema: str,
    *,
    packs: Sequence[str] | None = None,
    runtime: Mapping[str, object] | None = None,
) -> object:
    """Run TD-D28's order and return the schema handler's resolved object.

    packs=None reads contract/resolved-packs.txt (L24 on absent/malformed);
    an explicit sequence is used verbatim after the slug/duplicate check. The
    pack set is never read from config.sh's PACK= (TD-VF-16)."""
    # Step 1 — engine, before any file is parsed: L22, L2, L26, L24, L1, L25, L20.
    spec = KINDS.get(schema)
    if spec is None:
        raise RegistryError("unknown_kind", f"unregistered schema {schema!r}")
    try:
        import yaml as yaml_mod
    except ImportError as exc:
        raise RegistryError("yaml_unavailable", f"PyYAML is not importable: {exc}") from None
    handler = _import_handler(spec)

    root = Path(repo_root).resolve()
    pack_set = read_resolved_packs(root) if packs is None else _validate_pack_slugs(packs)

    directory = root / spec.directory
    core_rel = f"{spec.directory}/core.yaml"
    try:
        (root / core_rel).read_bytes()
    except OSError as exc:
        raise RegistryError("core_missing", f"cannot read core registry: {exc}", core_rel) from None

    allowed_names = {"core.yaml", "project.yaml", "project.yaml.template"}
    stale: str | None = None
    for child in sorted(directory.iterdir()):
        name = child.name
        if name.startswith(".") or not child.is_file():
            continue
        pack_match = _PACK_FILE_RE.match(name)
        if pack_match is not None and _SLUG_RE.match(pack_match.group(1)):
            if pack_match.group(1) not in pack_set and stale is None:
                stale = f"{spec.directory}/{name}"
            continue
        if name not in allowed_names:
            raise RegistryError(
                "unexpected_file", f"unexpected file {name!r}", f"{spec.directory}/{name}"
            )
    if stale is not None:
        raise RegistryError(
            "stale_pack_file", "pack file whose pack is not in the resolved pack set", stale
        )

    # Step 2 — per file, merge order core -> pack-* (closure order) -> project.
    docs = [_parse_layer(yaml_mod, root, core_rel, "core", None, spec)]
    for slug in pack_set:
        rel = f"{spec.directory}/pack-{slug}.yaml"
        if (root / rel).is_file():
            docs.append(_parse_layer(yaml_mod, root, rel, "pack", slug, spec))
    project_rel = f"{spec.directory}/project.yaml"
    if (root / project_rel).is_file():
        docs.append(_parse_layer(yaml_mod, root, project_rel, "project", None, spec))

    # Steps 3/4 — the handler, with any non-RegistryError made fail-closed (L26).
    ctx = LoadContext(
        repo_root=root, kind=spec, packs=pack_set, runtime=MappingProxyType(dict(runtime or {}))
    )
    try:
        return handler.resolve(tuple(docs), ctx)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError(
            "kind_handler_failed", f"handler raised {type(exc).__name__}: {exc}"
        ) from None


def registry_to_json(schema: str, resolved: object) -> dict:
    """Dispatch to the schema handler's `to_json`."""
    spec = KINDS.get(schema)
    if spec is None:
        raise RegistryError("unknown_kind", f"unregistered schema {schema!r}")
    handler = _import_handler(spec)
    try:
        return handler.to_json(resolved)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError(
            "kind_handler_failed", f"to_json raised {type(exc).__name__}: {exc}"
        ) from None


# ---------------------------------------------------------------------------
# Dimensions kind
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    title: str
    source: str


@dataclass(frozen=True)
class Predicate:
    include: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class Binding:
    id: str
    entry: str
    kind: str
    owner: str
    source: str
    agent: str | None
    tool: str | None
    posture: str | None
    timeout_seconds: int
    prompt_template: str | None
    predicate: Predicate


@dataclass(frozen=True)
class ResolvedRegistry:
    schema: str
    packs: tuple[str, ...]
    entries: Mapping[str, Entry]
    bindings: Mapping[str, Binding]  # suppressed bindings are ABSENT
    suppressions: Mapping[str, str]
    source_files: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class PlanItem:
    binding: Binding
    applicable: bool
    matched_files: tuple[str, ...]
    reason: str  # ALWAYS non-empty, in both states


_ENTRY_KEYS = frozenset({"id", "kind", "title"})
_BINDING_KEYS = frozenset(
    {
        "id",
        "entry",
        "kind",
        "agent",
        "tool",
        "posture",
        "timeout_seconds",
        "prompt_template",
        "predicate",
    }
)
_PREDICATE_KEYS = frozenset({"include", "exclude"})
_SUPPRESS_KEYS = frozenset({"binding", "reason"})


def _items(doc: LayerDoc, key: str) -> list[dict[str, Any]]:
    """The items of a top-level list. Shape errors belong to L28 and are raised
    by `_check_item_grammar` before this is reached."""
    return list(doc.data.get(key) or [])  # type: ignore[call-overload]


def _check_item_grammar(docs: tuple[LayerDoc, ...]) -> None:
    """L28 — closed item grammar (and required string keys)."""

    def check(
        item: object, allowed: frozenset[str], required: tuple[str, ...], what: str, path: str
    ) -> None:
        if not isinstance(item, dict):
            raise RegistryError("unknown_item_key", f"{what} is not a mapping", path)
        for key in item:
            if key not in allowed:
                raise RegistryError("unknown_item_key", f"{what} has unknown key {key!r}", path)
        for key in required:
            value = item.get(key)
            if not isinstance(value, str) or not value:
                raise RegistryError(
                    "unknown_item_key", f"{what} requires a non-empty string {key!r}", path
                )

    for doc in docs:
        for key, allowed, required, what in (
            ("entries", _ENTRY_KEYS, ("id", "kind", "title"), "entry"),
            ("bindings", _BINDING_KEYS, ("id", "entry", "kind"), "binding"),
            ("suppress", _SUPPRESS_KEYS, (), "suppress item"),
        ):
            raw = doc.data.get(key)
            if raw is None:
                continue
            if not isinstance(raw, list):
                raise RegistryError("unknown_item_key", f"{key!r} must be a list", doc.path)
            for item in raw:
                check(item, allowed, required, what, doc.path)
                if key == "bindings" and isinstance(item.get("predicate"), dict):
                    for pkey in item["predicate"]:
                        if pkey not in _PREDICATE_KEYS:
                            raise RegistryError(
                                "unknown_item_key", f"predicate has unknown key {pkey!r}", doc.path
                            )


def _namespace(doc: LayerDoc) -> str:
    return f"pack-{doc.pack}" if doc.owner == "pack" else doc.owner


def _path_escapes(root: Path, rel: str) -> str | None:
    """L27 — returns a reason string if `rel` escapes the repo, else None."""
    if rel.startswith("/") or PurePosixPath(rel).is_absolute():
        return "absolute path"
    if ".." in PurePosixPath(rel).parts:
        return "'..' path segment"
    candidate = root / rel
    if candidate.exists():
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            return "resolves outside the repository"
    return None


def resolve(docs: tuple[LayerDoc, ...], ctx: LoadContext) -> ResolvedRegistry:
    """The dimensions-kind handler: rules L28, L6-L9, L13, L14, L27, L10-L12,
    L21, L15-L17, L19, in TD-D28 step 3's order."""
    root = ctx.repo_root
    _check_item_grammar(docs)

    entries_raw = [(e, d) for d in docs for e in _items(d, "entries")]
    bindings_raw = [(b, d) for d in docs for b in _items(d, "bindings")]
    suppress_raw = [(s, d) for d in docs for s in _items(d, "suppress")]

    # L6 — duplicate ids.
    seen_entries: set[str] = set()
    for e, d in entries_raw:
        if e["id"] in seen_entries:
            raise RegistryError("duplicate_id", f"duplicate entry id {e['id']!r}", d.path)
        seen_entries.add(e["id"])
    seen_bindings: set[str] = set()
    for b, d in bindings_raw:
        if b["id"] in seen_bindings:
            raise RegistryError("duplicate_id", f"duplicate binding id {b['id']!r}", d.path)
        seen_bindings.add(b["id"])

    # L7 — binding id namespace must equal the owner.
    for b, d in bindings_raw:
        if not b["id"].startswith(f"{_namespace(d)}:"):
            raise RegistryError(
                "binding_namespace",
                f"binding id {b['id']!r} must start with {_namespace(d) + ':'!r}",
                d.path,
            )

    # L8 — unknown entry.
    entry_kind = {e["id"]: e["kind"] for e, _ in entries_raw}
    for b, d in bindings_raw:
        if b["entry"] not in entry_kind:
            raise RegistryError(
                "unknown_entry",
                f"binding {b['id']!r} references unknown entry {b['entry']!r}",
                d.path,
            )

    # L9 — kind vocabulary and binding kind == entry kind.
    for e, d in entries_raw:
        if e["kind"] not in _BINDING_KINDS:
            raise RegistryError(
                "kind_mismatch", f"entry {e['id']!r} has unknown kind {e['kind']!r}", d.path
            )
    for b, d in bindings_raw:
        if b["kind"] != entry_kind[b["entry"]]:
            raise RegistryError(
                "kind_mismatch",
                f"binding {b['id']!r} kind {b['kind']!r} != entry kind {entry_kind[b['entry']]!r}",
                d.path,
            )

    # L13 — timeout.
    for b, d in bindings_raw:
        t = b.get("timeout_seconds")
        if (
            isinstance(t, bool)
            or not isinstance(t, int)
            or not (_MIN_TIMEOUT_S <= t <= _MAX_TIMEOUT_S)
        ):
            raise RegistryError(
                "bad_timeout",
                f"binding {b['id']!r} timeout_seconds must be an int in "
                f"[{_MIN_TIMEOUT_S}, {_MAX_TIMEOUT_S}]",
                d.path,
            )

    # L14 — predicate.
    for b, d in bindings_raw:
        pred = b.get("predicate")
        if not isinstance(pred, dict):
            raise RegistryError("bad_predicate", f"binding {b['id']!r} has no predicate", d.path)
        include = pred.get("include")
        exclude = pred.get("exclude", [])
        if not isinstance(include, list) or not include:
            raise RegistryError(
                "bad_predicate", f"binding {b['id']!r} predicate.include is empty", d.path
            )
        if not isinstance(exclude, list):
            raise RegistryError(
                "bad_predicate", f"binding {b['id']!r} predicate.exclude is not a list", d.path
            )
        for pattern in (*include, *exclude):
            try:
                if not isinstance(pattern, str):
                    raise TypeError("pattern is not a string")
                re.compile(pattern)
            except (re.error, TypeError) as exc:
                raise RegistryError(
                    "bad_predicate", f"binding {b['id']!r} has a bad pattern: {exc}", d.path
                ) from None

    # L27 — path escape, before any filesystem existence check.
    for b, d in bindings_raw:
        candidates = [
            ("tool", b.get("tool")),
            ("prompt_template", b.get("prompt_template")),
            (
                "agent",
                f".claude/agents/{b['agent']}.md" if isinstance(b.get("agent"), str) else None,
            ),
        ]
        for field_name, rel in candidates:
            if isinstance(rel, str):
                reason = _path_escapes(root, rel)
                if reason is not None:
                    raise RegistryError(
                        "path_escape", f"binding {b['id']!r} {field_name}: {reason}", d.path
                    )

    # L10 — judgment agent file.
    for b, d in bindings_raw:
        if b["kind"] == "judgment":
            agent = b.get("agent")
            if (
                not isinstance(agent, str)
                or not (root / ".claude" / "agents" / f"{agent}.md").is_file()
            ):
                raise RegistryError(
                    "agent_missing", f"binding {b['id']!r} agent file is absent", d.path
                )

    # L11 — deterministic tool, present and executable.
    for b, d in bindings_raw:
        if b["kind"] == "deterministic":
            tool = b.get("tool")
            if not isinstance(tool, str) or not (
                (root / tool).is_file() and os.access(root / tool, os.X_OK)
            ):
                raise RegistryError(
                    "tool_missing", f"binding {b['id']!r} tool is absent or not executable", d.path
                )

    # L12 — posture (V1-V14 via the shared L1 module).
    for b, d in bindings_raw:
        if b["kind"] == "judgment":
            name = b.get("posture")
            if not isinstance(name, str):
                raise RegistryError(
                    "posture_invalid", f"binding {b['id']!r} has no posture", d.path
                )
            try:
                _posture.load_posture(root, name)
            except _posture.PostureError as exc:
                raise RegistryError(
                    "posture_invalid",
                    f"binding {b['id']!r} posture {name!r} failed {exc.rule}",
                    d.path,
                ) from None

    # L21 — prompt template.
    for b, d in bindings_raw:
        if b["kind"] == "judgment":
            tmpl = b.get("prompt_template")
            if not isinstance(tmpl, str) or not (root / tmpl).is_file():
                raise RegistryError(
                    "prompt_missing", f"binding {b['id']!r} prompt_template is absent", d.path
                )

    # L15 / L16 / L17 — suppressions, one pass each.
    for s, d in suppress_raw:
        if s.get("binding") not in seen_bindings:
            raise RegistryError(
                "suppress_unknown", f"suppress names unknown binding {s.get('binding')!r}", d.path
            )
    for s, d in suppress_raw:
        if s["binding"].startswith("core:"):
            raise RegistryError(
                "suppress_core", f"core binding {s['binding']!r} cannot be suppressed", d.path
            )
    for s, d in suppress_raw:
        reason = s.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RegistryError(
                "suppress_no_reason", f"suppression of {s['binding']!r} has no reason", d.path
            )
    suppressions = {s["binding"]: s["reason"] for s, _ in suppress_raw}

    # L19 — every entry keeps at least one unsuppressed binding.
    live_entries = {b["entry"] for b, _ in bindings_raw if b["id"] not in suppressions}
    for e, d in entries_raw:
        if e["id"] not in live_entries:
            raise RegistryError(
                "entry_unbound", f"entry {e['id']!r} has no unsuppressed binding", d.path
            )

    entries = {e["id"]: Entry(e["id"], e["kind"], e["title"], d.path) for e, d in entries_raw}
    bindings: dict[str, Binding] = {}
    for b, d in bindings_raw:
        if b["id"] in suppressions:
            continue
        pred = b["predicate"]
        bindings[b["id"]] = Binding(
            id=b["id"],
            entry=b["entry"],
            kind=b["kind"],
            owner=d.owner,
            source=d.path,
            agent=b.get("agent") if b["kind"] == "judgment" else None,
            tool=b.get("tool") if b["kind"] == "deterministic" else None,
            posture=b.get("posture") if b["kind"] == "judgment" else None,
            timeout_seconds=b["timeout_seconds"],
            prompt_template=b.get("prompt_template") if b["kind"] == "judgment" else None,
            predicate=Predicate(tuple(pred["include"]), tuple(pred.get("exclude", []))),
        )
    partial = ResolvedRegistry(
        schema=ctx.kind.schema,
        packs=ctx.packs,
        entries=MappingProxyType(entries),
        bindings=MappingProxyType(bindings),
        suppressions=MappingProxyType(suppressions),
        source_files=tuple(d.path for d in docs),
        digest="",
    )
    digest = hashlib.sha256(_canonical(_body(partial)).encode("utf-8")).hexdigest()
    return replace(partial, digest=digest)


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _body(reg: ResolvedRegistry) -> dict:
    return {
        "schema": reg.schema,
        "packs": list(reg.packs),
        "source_files": list(reg.source_files),
        "entries": [
            {"id": e.id, "kind": e.kind, "title": e.title, "source": e.source}
            for e in sorted(reg.entries.values(), key=lambda x: x.id)
        ],
        "bindings": [
            {
                "id": b.id,
                "entry": b.entry,
                "kind": b.kind,
                "owner": b.owner,
                "source": b.source,
                "agent": b.agent,
                "tool": b.tool,
                "posture": b.posture,
                "timeout_seconds": b.timeout_seconds,
                "prompt_template": b.prompt_template,
                "predicate": {
                    "include": list(b.predicate.include),
                    "exclude": list(b.predicate.exclude),
                },
            }
            for b in sorted(reg.bindings.values(), key=lambda x: x.id)
        ],
        "suppressions": dict(sorted(reg.suppressions.items())),
    }


def to_json(reg: ResolvedRegistry) -> dict:
    """Canonical JSON-able form; `digest` is the sha256 of everything else."""
    return {**_body(reg), "digest": reg.digest}


def load(repo_root: str | Path, *, packs: Sequence[str] | None = None) -> ResolvedRegistry:
    """Exactly `load_registry(repo_root, DIMENSIONS_SCHEMA, packs=packs)`."""
    return load_registry(repo_root, DIMENSIONS_SCHEMA, packs=packs)  # type: ignore[return-value]


def resolve_for_diff(reg: ResolvedRegistry, changed_files: Sequence[str]) -> list[PlanItem]:
    """§7.5 — the only producer of applicability. `re.search`, not `re.match`
    (the migrated patterns are `grep -E` semantics). `reason` is never empty."""
    plan: list[PlanItem] = []
    for binding in reg.bindings.values():
        include = [re.compile(p) for p in binding.predicate.include]
        exclude = [re.compile(p) for p in binding.predicate.exclude]
        matched = [
            f
            for f in changed_files
            if any(p.search(f) for p in include) and not any(p.search(f) for p in exclude)
        ]
        if matched:
            plan.append(
                PlanItem(
                    binding=binding,
                    applicable=True,
                    matched_files=tuple(sorted(matched)),
                    reason=f"binding {binding.id} matched {len(matched)} changed file(s)",
                )
            )
        else:
            plan.append(
                PlanItem(
                    binding=binding,
                    applicable=False,
                    matched_files=(),
                    reason=f"binding {binding.id} matched no changed file",
                )
            )
    return plan
