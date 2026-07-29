#!/usr/bin/env python3
"""
hallucination_surface_js.py — npm-ecosystem version-sensitive API detection +
package.json dependency-existence check (S7, ADR-032, epic #1029).

JS/TS/JSX/TSX/Astro sibling of hallucination_surface.py. Emits the same
`dimension="hallucination_surface"` string and `weight=WEIGHTS["hallucination_surface"]`
as the Python validator, but writes to a distinct outfile
(hallucination_js.json, via the `hallucination_js` NAME in run_validators.sh)
so the two never collide and the Python-only byte-identical regression guard
(AC-2) holds.

Two independent signals, combined into one score:

1. Version-sensitive API usage — a tree-sitter scan (same parse scaffold as
   complexity_metrics_js.py/function_metrics_js.py) for Astro major-version
   APIs, Vite config surface, and Node built-ins known to have been renamed,
   deprecated, or removed across versions. Same first-pass-heuristic caveat
   as the Python sibling's _KNOWN_RISKY list: grow it as new cases surface.

2. package.json dependency-existence check — for each declared dependency,
   confirm it actually exists on the npm registry. This is flagged in the
   issue spec as the highest-value AI-specific signal for JS: an LLM can
   confidently hallucinate a package name (or produce something close to a
   real one, i.e. a typosquat-shaped name) that was never published. A
   confirmed-absent package weighs _MISSING_PACKAGE_WEIGHT times a plain API
   finding in the composite count — mirroring static_analysis_js.py's
   ERROR:WARNING 3:1 ratio for "this signal matters more than the others".

Network calls are best-effort: a 404 from the registry is treated as
evidence the package does not exist; any other network/registry failure is
"unresolved" (never scored as risk, only surfaced for manual verification) —
a flaky connection must never manufacture a false hallucination finding.

Usage: python hallucination_surface_js.py file.ts [file2.tsx ...] [package.json ...]
"""

from __future__ import annotations

import json
import pathlib as _hos_pl
import re
import urllib.error
import urllib.request

# self-bootstrap: ensure this file's dir (with schema.py) is importable
# regardless of caller cwd/PYTHONPATH (run_validators, run_panel, direct).
import sys
import sys as _hos_sys
from pathlib import Path

_hos_sys.path.insert(0, str(_hos_pl.Path(__file__).resolve().parent))
from schema import WEIGHTS, make_finding, make_result, normalize  # noqa: E402

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".astro", ".mjs", ".cjs")

try:
    import tree_sitter_typescript as _ts_ts
    from tree_sitter import Language as _TSLanguage
    from tree_sitter import Parser as _TSParser

    _TS_LANGUAGE = _TSLanguage(_ts_ts.language_typescript())
    _TSX_LANGUAGE = _TSLanguage(_ts_ts.language_tsx())
    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False


# ── Known-risky npm-ecosystem API table ──────────────────────────────────────
# First-pass heuristic, same discipline as the Python sibling's _KNOWN_RISKY —
# grow this over time as new version-sensitivity cases are discovered.

# Modules that are risky to import/require regardless of which name is pulled
# from them (module_pattern, reason).
_KNOWN_RISKY_MODULES: list[tuple[str, str]] = [
    (
        "punycode",
        "Node's userland punycode module is deprecated (DEP0040) and slated "
        "for removal — verify a maintained npm replacement is used instead",
    ),
    (
        "node:punycode",
        "Node's userland punycode module is deprecated (DEP0040) and slated "
        "for removal — verify a maintained npm replacement is used instead",
    ),
    ("domain", "Node's domain module is deprecated (DEP0058) — avoid in new code"),
    ("node:domain", "Node's domain module is deprecated (DEP0058) — avoid in new code"),
    (
        "@astrojs/image",
        "the @astrojs/image integration was removed in Astro 3.0 — replaced "
        "by the built-in astro:assets image()",
    ),
]

# Member/attribute access (object, property) known to be version-sensitive —
# matched regardless of whether the access is called. `object` is matched on
# the exact source text of the member expression's object (so "import.meta"
# matches Vite/ESM's import.meta.* surface as one unit).
_KNOWN_RISKY_MEMBERS: list[tuple[str, str, str]] = [
    (
        "Astro",
        "glob",
        "Astro.glob() is deprecated since Astro 3.0 in favor of "
        "import.meta.glob() — verify against the installed Astro version",
    ),
    (
        "Astro",
        "resolve",
        "Astro.resolve() was removed in Astro 3.0 — use relative import "
        "paths or astro:assets' getImage()",
    ),
    (
        "Astro",
        "fetchContent",
        "Astro.fetchContent() was removed before Astro 1.0 — replaced by "
        "Astro.glob() / content collections",
    ),
    (
        "Astro",
        "canonicalURL",
        "Astro.canonicalURL was removed in Astro 2.0 — use Astro.url",
    ),
    (
        "import.meta",
        "globEager",
        "import.meta.globEager() was removed in Vite 3 — use "
        "import.meta.glob(pattern, { eager: true })",
    ),
    (
        "url",
        "parse",
        "the legacy url.parse() API is deprecated (DEP0169) — use the "
        "WHATWG URL API (new URL())",
    ),
    (
        "crypto",
        "createCipher",
        "crypto.createCipher() was removed in Node 22 — use createCipheriv()",
    ),
    (
        "crypto",
        "createDecipher",
        "crypto.createDecipher() was removed in Node 22 — use createDecipheriv()",
    ),
    (
        "process",
        "binding",
        "process.binding() is a deprecated internal API restricted/removed "
        "in modern Node — verify a public API replacement is used",
    ),
]

# `new X(...)` constructors known to be version-sensitive (constructor_name, reason).
_KNOWN_RISKY_CONSTRUCTORS: list[tuple[str, str]] = [
    (
        "Buffer",
        "new Buffer() is deprecated (DEP0005) — use Buffer.from()/"
        "Buffer.alloc()/Buffer.allocUnsafe()",
    ),
]

# A confirmed-absent npm dependency is a far higher-value hallucination signal
# than a version-sensitive API note — weighted like static_analysis_js.py's
# ERROR:WARNING 3:1 ratio.
_MISSING_PACKAGE_WEIGHT = 3

_DEP_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")

# Specs that do not resolve against the public npm registry at all — local
# paths, workspace links, and git/URL deps. Not checked (false-positive risk).
_NON_REGISTRY_SPEC_RE = re.compile(r"^(file:|link:|workspace:|git\+|git:|https?://|npm:)")

# Bound worst-case network calls per run — a package.json with hundreds of
# deps must not blow the validator timeout. Any drop is logged (checklist),
# never silent.
_MAX_PACKAGES_CHECKED = 40
# Bail out early once the registry looks unreachable rather than burning the
# full timeout on N doomed requests.
_MAX_CONSECUTIVE_NETWORK_ERRORS = 5
_REGISTRY_TIMEOUT = 3.0


def _npm_package_exists(name: str) -> bool | None:
    """
    True if the registry confirms the package exists, False if the registry
    returned 404 (confirmed absent), None if indeterminate (network/registry
    error — never treated as evidence of absence).
    """
    url = f"https://registry.npmjs.org/{name}"
    try:
        with urllib.request.urlopen(url, timeout=_REGISTRY_TIMEOUT) as r:
            r.read(1)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        return None
    except Exception:
        return None


def _check_dependencies_exist(deps: dict[str, tuple[str, str]]) -> dict:
    """
    deps: name -> (spec, source_file).

    Returns a dict with `missing` (confirmed-absent findings), `unresolved`
    (names we could not confirm either way), `checked` (count actually
    queried), and `capped_from` (original dep count if the cap was applied).
    """
    missing: list[dict] = []
    unresolved: list[str] = []
    checked = 0
    consecutive_errors = 0

    items = sorted(deps.items())
    capped_from = len(items) if len(items) > _MAX_PACKAGES_CHECKED else None
    items = items[:_MAX_PACKAGES_CHECKED]

    for name, (spec, source_file) in items:
        if _NON_REGISTRY_SPEC_RE.match(spec.strip()):
            continue
        checked += 1
        exists = _npm_package_exists(name)
        if exists is False:
            missing.append({"name": name, "spec": spec, "file": source_file})
            consecutive_errors = 0
        elif exists is None:
            unresolved.append(name)
            consecutive_errors += 1
            if consecutive_errors >= _MAX_CONSECUTIVE_NETWORK_ERRORS:
                break
        else:
            consecutive_errors = 0

    return {
        "missing": missing,
        "unresolved": unresolved,
        "checked": checked,
        "capped_from": capped_from,
    }


def _dep_items(data: dict) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for field in _DEP_FIELDS:
        section = data.get(field)
        if not isinstance(section, dict):
            continue
        items.extend((n, s) for n, s in section.items() if isinstance(n, str) and isinstance(s, str))
    return items


def _extract_dependencies(pkg_json_path: str) -> tuple[dict[str, str], str | None]:
    """Return (name -> spec, error). error is non-None on unreadable/invalid JSON."""
    try:
        data = json.loads(Path(pkg_json_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return {}, str(e)
    deps: dict[str, str] = {}
    for name, spec in _dep_items(data):
        deps.setdefault(name, spec)
    return deps, None


def _line_for_dependency(pkg_path: str, name: str) -> int:
    """Best-effort line lookup for a dependency key, for evidence quality."""
    try:
        lines = Path(pkg_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    needle = f'"{name}"'
    for i, line in enumerate(lines, start=1):
        if needle in line:
            return i
    return 0


# ── Source-code API scan (tree-sitter) ───────────────────────────────────────


def _astro_segments(text: str) -> list[tuple[int, bytes]]:
    """Extract the frontmatter fence + <script> blocks from an .astro SFC —
    the rest is template markup tree-sitter-typescript can't parse. Same
    approach as function_metrics_js.py's D5 handling."""
    segments: list[tuple[int, bytes]] = []
    fm = re.match(r"^---\r?\n(.*?\r?\n)---", text, re.DOTALL)
    if fm:
        line_offset = text.count("\n", 0, fm.start(1))
        segments.append((line_offset, fm.group(1).encode("utf-8")))
    for sm in re.finditer(r"<script\b[^>]*>(.*?)</script>", text, re.DOTALL | re.IGNORECASE):
        line_offset = text.count("\n", 0, sm.start(1))
        segments.append((line_offset, sm.group(1).encode("utf-8")))
    return segments


def _segments_for_file(path: str, text: str) -> list[tuple[int, bytes]]:
    if path.endswith(".astro"):
        return _astro_segments(text)
    return [(0, text.encode("utf-8"))]


def _language_for(path: str):
    return _TSX_LANGUAGE if path.endswith((".tsx", ".jsx")) else _TS_LANGUAGE


def _module_from_import_source(node) -> str | None:
    """node is the `string` child of an import_statement/export_statement source."""
    for child in node.children:
        if child.type == "string_fragment":
            return child.text.decode("utf-8", "replace")
    return None


def _finding(filename: str, line_offset: int, node, pattern: str, reason: str) -> dict:
    return {
        "file": filename,
        "line": line_offset + node.start_point[0] + 1,
        "pattern": pattern,
        "reason": reason,
        "severity": "medium",
    }


def _match_risky_module(module: str) -> str | None:
    return next((reason for pattern, reason in _KNOWN_RISKY_MODULES if module == pattern), None)


def _match_risky_member(obj_text: str, prop_text: str) -> str | None:
    return next(
        (
            reason
            for obj_pattern, prop_pattern, reason in _KNOWN_RISKY_MEMBERS
            if obj_text == obj_pattern and prop_text == prop_pattern
        ),
        None,
    )


def _match_risky_constructor(ctor_text: str) -> str | None:
    return next((reason for pattern, reason in _KNOWN_RISKY_CONSTRUCTORS if ctor_text == pattern), None)


def _check_import_statement(node, line_offset: int, filename: str) -> dict | None:
    src = node.child_by_field_name("source")
    module = _module_from_import_source(src) if src is not None else None
    reason = _match_risky_module(module) if module is not None else None
    return _finding(filename, line_offset, node, module, reason) if reason else None


def _check_require_call(node, line_offset: int, filename: str) -> dict | None:
    func = node.child_by_field_name("function")
    if func is None or func.type != "identifier" or func.text != b"require":
        return None
    args = node.child_by_field_name("arguments")
    if args is None or args.named_child_count != 1 or args.named_children[0].type != "string":
        return None
    module = _module_from_import_source(args.named_children[0])
    reason = _match_risky_module(module) if module is not None else None
    return _finding(filename, line_offset, node, f"require('{module}')", reason) if reason else None


def _check_member_expression(node, line_offset: int, filename: str) -> dict | None:
    obj = node.child_by_field_name("object")
    prop = node.child_by_field_name("property")
    if obj is None or prop is None:
        return None
    obj_text = obj.text.decode("utf-8", "replace")
    prop_text = prop.text.decode("utf-8", "replace")
    reason = _match_risky_member(obj_text, prop_text)
    return _finding(filename, line_offset, node, f"{obj_text}.{prop_text}", reason) if reason else None


def _check_new_expression(node, line_offset: int, filename: str) -> dict | None:
    ctor = node.child_by_field_name("constructor")
    if ctor is None or ctor.type != "identifier":
        return None
    ctor_text = ctor.text.decode("utf-8", "replace")
    reason = _match_risky_constructor(ctor_text)
    return _finding(filename, line_offset, node, f"new {ctor_text}", reason) if reason else None


# Node-type -> check function, keyed dispatch instead of an if/elif chain to
# keep _collect_api_findings itself shallow (each check owns its own nesting).
_NODE_CHECKS = {
    "import_statement": _check_import_statement,
    "call_expression": _check_require_call,
    "member_expression": _check_member_expression,
    "new_expression": _check_new_expression,
}


def _collect_api_findings(node, line_offset: int, filename: str, out: list[dict]) -> None:
    check = _NODE_CHECKS.get(node.type)
    if check is not None:
        finding = check(node, line_offset, filename)
        if finding is not None:
            out.append(finding)
    for child in node.children:
        _collect_api_findings(child, line_offset, filename, out)


def _analyse_source_file(path: str) -> tuple[list[dict], bool]:
    """Return (findings, had_error) for one file across all its segments."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], True

    parser = _TSParser(_language_for(path))
    findings: list[dict] = []
    had_error = False
    for line_offset, source in _segments_for_file(path, text):
        if not source.strip():
            continue
        tree = parser.parse(source)
        if tree.root_node.has_error:
            had_error = True
        _collect_api_findings(tree.root_node, line_offset, path, findings)
    return findings, had_error


def _scan_source(src_files: list[str]) -> dict:
    """Tree-sitter API scan over the given source files. `fully_failed` is
    True only when NOTHING could be parsed — a genuine assessment failure,
    not just "zero findings"."""
    if not src_files:
        return {"findings": [], "parse_errors": [], "fully_failed": False}
    if not _TREE_SITTER_AVAILABLE:
        return {
            "findings": [],
            "parse_errors": [{"file": f, "error": "tree-sitter not installed"} for f in src_files],
            "fully_failed": True,
        }

    findings: list[dict] = []
    parse_errors: list[dict] = []
    parsed_any = False
    for path in src_files:
        file_findings, had_error = _analyse_source_file(path)
        if had_error:
            parse_errors.append(
                {
                    "file": path,
                    "error": "tree-sitter reported syntax errors or the file could not be read",
                }
            )
        else:
            parsed_any = True
        findings.extend(file_findings)
    return {"findings": findings, "parse_errors": parse_errors, "fully_failed": not parsed_any}


def _scan_package_json(pkg_files: list[str]) -> dict:
    """package.json dependency-existence scan. `fully_failed` is True only
    when every package.json failed to parse, or every declared dependency
    that WAS checked came back unresolved — zero declared deps is a clean
    state, not a failure."""
    empty = {
        "missing": [],
        "unresolved": [],
        "json_errors": [],
        "checked": 0,
        "capped_from": None,
        "fully_failed": False,
    }
    if not pkg_files:
        return empty

    all_deps: dict[str, tuple[str, str]] = {}
    json_errors: list[dict] = []
    any_json_ok = False
    for pf in pkg_files:
        deps, err = _extract_dependencies(pf)
        if err:
            json_errors.append({"file": pf, "error": err})
            continue
        any_json_ok = True
        for name, spec in deps.items():
            all_deps.setdefault(name, (spec, pf))

    if not all_deps:
        return {**empty, "json_errors": json_errors, "fully_failed": not any_json_ok}

    result = _check_dependencies_exist(all_deps)
    for m in result["missing"]:
        m["line"] = _line_for_dependency(m["file"], m["name"])
    fully_failed = result["checked"] > 0 and result["checked"] == len(result["unresolved"])
    return {**result, "json_errors": json_errors, "fully_failed": fully_failed}


def _exclusion_detail(src: dict, pkg: dict) -> str:
    parts = []
    if src["parse_errors"]:
        parts.append(
            "source: "
            + "; ".join(f"{Path(e['file']).name}: {e['error']}" for e in src["parse_errors"][:5])
        )
    if pkg["json_errors"]:
        parts.append(
            "package.json: "
            + "; ".join(f"{Path(e['file']).name}: {e['error']}" for e in pkg["json_errors"])
        )
    if pkg["checked"] and pkg["checked"] == len(pkg["unresolved"]):
        parts.append(f"npm registry unreachable for all {pkg['checked']} declared dependencies checked")
    return "; ".join(parts) or "no signal available"


def _build_evidence(api_findings: list[dict], missing_packages: list[dict]) -> list[dict]:
    evidence = [
        make_finding(f["file"], f["line"], f"⚠ VERIFY: {f['pattern']} — {f['reason']}", "medium")
        for f in api_findings[:10]
    ]
    evidence.extend(
        make_finding(
            m["file"],
            m["line"],
            f"⚠ VERIFY: dependency '{m['name']}' ({m['spec']}) not found on the npm "
            "registry — possible hallucinated or typosquatted package name",
            "high",
        )
        for m in missing_packages[:10]
    )
    return evidence


def _build_checklist(api_findings: list[dict], src: dict, pkg: dict) -> list[str]:
    checklist = [f"⚠ VERIFY: {f['pattern']} — {f['reason']}" for f in api_findings[:5]]
    for m in pkg["missing"][:5]:
        checklist.append(
            f"⚠ VERIFY: dependency '{m['name']}' ({m['spec']}) was not found on the npm "
            "registry — confirm the name is correct and not hallucinated/typosquatted"
        )
    if pkg["unresolved"]:
        shown = ", ".join(pkg["unresolved"][:10])
        more = f" (+{len(pkg['unresolved']) - 10} more)" if len(pkg["unresolved"]) > 10 else ""
        checklist.append(
            f"⚠ could not verify {len(pkg['unresolved'])} dependency(ies) against the npm "
            f"registry due to network/registry errors — manually confirm they exist: {shown}{more}"
        )
    for e in src["parse_errors"][:2]:
        checklist.append(
            f"⚠ {Path(e['file']).name} could not be fully parsed ({e['error']}) — "
            "manually verify it contains no version-sensitive API usage"
        )
    for e in pkg["json_errors"]:
        checklist.append(
            f"⚠ {Path(e['file']).name} could not be parsed ({e['error']}) — manually verify "
            "its declared dependencies"
        )
    if pkg["capped_from"]:
        checklist.append(
            f"⚠ {pkg['capped_from']} dependencies declared — only the first "
            f"{_MAX_PACKAGES_CHECKED} (alphabetically) were checked against the npm registry; "
            "verify the remainder manually"
        )
    return checklist


def analyse_files(file_paths: list[str]) -> dict:
    src_files = [f for f in file_paths if f.endswith(_JS_EXTS)]
    pkg_files = [f for f in file_paths if Path(f).name == "package.json"]

    src = _scan_source(src_files)
    pkg = _scan_package_json(pkg_files)
    api_findings = src["findings"]
    missing_packages = pkg["missing"]

    nothing_assessed = (not src_files or (src["fully_failed"] and not api_findings)) and (
        not pkg_files or (pkg["fully_failed"] and not missing_packages)
    )
    if nothing_assessed and (src_files or pkg_files):
        return make_result(
            "hallucination_surface",
            0.0,
            {
                "findings": [],
                "missing_packages": [],
                "parse_errors": src["parse_errors"],
                "json_errors": pkg["json_errors"],
            },
            weight=WEIGHTS["hallucination_surface"],
            error=f"could not assess JS hallucination surface: {_exclusion_detail(src, pkg)}",
        )

    concern_count = len(api_findings) + _MISSING_PACKAGE_WEIGHT * len(missing_packages)
    score = normalize(concern_count, 0, 6)

    return make_result(
        dimension="hallucination_surface",
        score=score,
        raw_value={
            "version_sensitive_count": len(api_findings),
            "findings": api_findings,
            "missing_package_count": len(missing_packages),
            "missing_packages": missing_packages,
            "checked_dependency_count": pkg["checked"],
            "unresolved_dependency_count": len(pkg["unresolved"]),
            "unresolved_dependencies": pkg["unresolved"],
            "capped_from": pkg["capped_from"],
            "parse_errors": src["parse_errors"],
            "json_errors": pkg["json_errors"],
        },
        weight=WEIGHTS["hallucination_surface"],
        evidence=_build_evidence(api_findings, missing_packages),
        checklist_items=_build_checklist(api_findings, src, pkg),
    )


def main() -> None:
    files = [
        f for f in sys.argv[1:] if Path(f).exists() and (f.endswith(_JS_EXTS) or Path(f).name == "package.json")
    ]
    if not files:
        print(
            json.dumps(
                make_result(
                    "hallucination_surface",
                    0.0,
                    {"error": "no input"},
                    weight=WEIGHTS["hallucination_surface"],
                    error="no input files",
                ),
                indent=2,
            )
        )
        return
    print(json.dumps(analyse_files(files), indent=2))


if __name__ == "__main__":
    main()
