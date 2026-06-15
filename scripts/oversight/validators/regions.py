"""
regions.py — the byte-exact region mechanism for HOS layered agent files.

An agent `.md` is composed of marker-delimited regions:

    <!-- HOS:CORE:START -->      ... generic role ...      <!-- HOS:CORE:END -->
    <!-- HOS:PACK:<name>:START -->  ... stack rules ...    <!-- HOS:PACK:<name>:END -->
    <!-- HOS:PROJECT:START -->    ... consumer's rules ... <!-- HOS:PROJECT:END -->

Canonical order is CORE -> PACK:<name> (alphabetical) -> PROJECT (recency
precedence: the most-specific layer comes last so PROJECT overrides PACK
overrides CORE). `compose()` is the ONLY writer and always emits this order.

This module is standalone and deterministic: stdlib only (hashlib, re, sys,
argparse, dataclasses). It runs in the target's venv-less context exactly the
way the installer's `_sha256` does today, and mirrors `schema.py`'s "pure
functions + a thin CLI" shape.

Binding decisions honored (docs/specs/v0.3.0-base-agents-spec.md §11/§11a):
  D6 — regions.py NEVER substitutes and never reads config.sh /
       placeholders.manifest. It hashes the bytes it is given. The installer's
       perl pass is the only substitution engine.
  D7 — `validate --placeholder-keys <csv>` flags any `{KEY}` token (for a
       passed key) inside a CORE/PACK body -> E_PLACEHOLDER_IN_CORE_PACK.
       regions.py is token-set-agnostic; it is *told* the keys.
  D8 — out-of-region prose is HOS-canonical: compose() owns/regenerates all
       out-of-region prose; only the PROJECT body is verbatim-from-disk.
       validate() does not reject out-of-region prose.

Scope note (Phase 1): this file implements parse / validate / compose /
region_sha + the manifest-rows / validate / region-sha / compose CLI. The
three-way `merge` decision and flat-file `migrate` are later coder passes and
are intentionally NOT implemented here.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field

# Manifest schema version this module reads/writes (TD §1.3).
CURRENT_SCHEMA = 2

# Exit codes used by the CLI (TD §2.7).
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INVALID = 2
EXIT_REGION_ABSENT = 3


# --------------------------------------------------------------------------- #
# Marker grammar (TD §2.1)
# --------------------------------------------------------------------------- #

# Pack slug: lowercase, starts alnum, then alnum or hyphen.
_PACK_SLUG = r"[a-z0-9][a-z0-9-]*"

# The strict, anchored marker form — the ONLY accepted marker. Tolerates a run
# of whitespace where the canonical form uses single spaces, so a reflowed file
# still parses; compose() always re-emits the canonical single-space form.
_MARKER_RE = re.compile(
    r"^<!--\s+HOS:(?P<id>CORE|PACK:" + _PACK_SLUG + r"|PROJECT):(?P<edge>START|END)\s+-->$"
)

# Loose "looks marker-ish" probe — anything matching this but NOT _MARKER_RE is
# a malformed marker (typo'd / wrong case), caught fail-closed by validate()
# (E_MALFORMED_MARKER) rather than silently becoming body text.
_LOOSE_MARKER_RE = re.compile(r"^\s*<!--\s*HOS:", re.IGNORECASE)


def _canonical_start(region_id: str) -> bytes:
    return b"<!-- HOS:" + region_id.encode("utf-8") + b":START -->"


def _canonical_end(region_id: str) -> bytes:
    return b"<!-- HOS:" + region_id.encode("utf-8") + b":END -->"


# --------------------------------------------------------------------------- #
# Data model (TD §2.2)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Region:
    id: str               # "CORE" | "PACK:<name>" | "PROJECT"
    name: str | None      # pack name for PACK:*, else None
    body: bytes           # bytes strictly between markers, BEFORE newline normalization
    start_line: int       # 1-based line index of the START marker (for error messages)
    end_line: int         # 1-based line index of the END marker


@dataclass
class ParsedAgent:
    front_matter: bytes = b""        # YAML front-matter block incl. delimiters, or b""
    regions: list[Region] = field(default_factory=list)  # in file order as found
    raw: bytes = b""                 # original file bytes (round-trip / migration)


class ParseError(Exception):
    """Structurally impossible read (END with empty stack, EOF inside a region)."""

    def __init__(self, line: int, kind: str, msg: str):
        self.line = line
        self.kind = kind
        self.msg = msg
        super().__init__(f"{line}:{kind}:{msg}")


@dataclass
class Result:
    ok: bool
    errors: list[tuple[int, str, str]] = field(default_factory=list)  # (line, CODE, msg)


# --------------------------------------------------------------------------- #
# Marker classification
# --------------------------------------------------------------------------- #

def _classify(line: bytes) -> tuple[str, str] | None:
    """
    Return (region_id, edge) if `line` is a strict marker, else None.

    The line is decoded as UTF-8 (markers are ASCII) and trailing whitespace
    stripped before matching, per TD §2.1 ("a marker is a whole line after
    stripping trailing whitespace").
    """
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.rstrip()
    m = _MARKER_RE.match(text)
    if not m:
        return None
    return m.group("id"), m.group("edge")


def _is_loose_marker(line: bytes) -> bool:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(_LOOSE_MARKER_RE.match(text.rstrip()))


def _region_name(region_id: str) -> str | None:
    if region_id.startswith("PACK:"):
        return region_id.split(":", 1)[1]
    return None


def _split_lines_keepends(data: bytes) -> list[bytes]:
    """Split on '\n' preserving the terminator on every line but the last.

    Unlike bytes.splitlines() this does NOT split on other unicode line
    boundaries (e.g. \\x0b, \\x0c, U+2028) which would corrupt body bytes; it
    only treats LF as a line boundary, matching how the installer reads files.
    """
    return data.splitlines(keepends=True) if data else []


# --------------------------------------------------------------------------- #
# parse (TD §2.3)
# --------------------------------------------------------------------------- #

_FRONT_MATTER_RE = re.compile(rb"^---\n(?:.*?\n)??---\n", re.DOTALL)


def parse(text: bytes) -> ParsedAgent:
    """
    Parse `text` into a ParsedAgent. Tolerant by design — does NOT enforce the
    structural invariants (that is validate()'s job) so validate() can produce
    precise diagnostics. Raises ParseError only on a structurally impossible
    read: an END with an empty stack, or EOF inside an open region.
    """
    if not isinstance(text, (bytes, bytearray)):
        raise TypeError("parse() requires bytes")
    text = bytes(text)

    # Front-matter: a leading ---\n ... \n---\n block. Markers are searched only
    # after it (TD §2.3).
    front_matter = b""
    body_offset = 0
    fm = _FRONT_MATTER_RE.match(text)
    if fm:
        front_matter = fm.group(0)
        body_offset = fm.end()

    body_text = text[body_offset:]
    lines = _split_lines_keepends(body_text)

    # Line numbering is 1-based over the whole file (front-matter counts toward
    # line numbers so error messages point at the real file line).
    fm_line_count = front_matter.count(b"\n") if front_matter else 0

    regions: list[Region] = []
    # Stack of (region_id, name, start_line_1based, body_accumulator_start_index)
    open_stack: list[tuple[str, str | None, int, list[bytes]]] = []

    for idx, raw_line in enumerate(lines):
        line_no = fm_line_count + idx + 1
        classified = _classify(raw_line)
        if classified is not None:
            region_id, edge = classified
            if edge == "START":
                open_stack.append((region_id, _region_name(region_id), line_no, []))
            else:  # END
                if not open_stack:
                    raise ParseError(line_no, "END_WITHOUT_START",
                                     f"END marker for {region_id} with no open region")
                open_id, open_name, start_line, acc = open_stack.pop()
                # Note: a mismatched id (END that does not match the innermost
                # open START) is left for validate() to diagnose precisely as
                # unbalanced; parse stays tolerant and pairs by stack position.
                body = b"".join(acc)
                regions.append(Region(
                    id=open_id,
                    name=open_name,
                    body=body,
                    start_line=start_line,
                    end_line=line_no,
                ))
        else:
            # Body line — append to the innermost open region's accumulator, if
            # any. Out-of-region lines (preamble / inter-region prose) are not
            # captured into any Region (D8 — out-of-region prose is HOS-canonical
            # and regenerated by compose; never hashed).
            if open_stack:
                open_stack[-1][3].append(raw_line)

    if open_stack:
        unterminated = open_stack[-1]
        raise ParseError(unterminated[2], "EOF_IN_REGION",
                         f"end of file while region {unterminated[0]} still open")

    # Preserve file order as found. Because regions are emitted on END (pop),
    # nested regions (which validate() rejects) would emit inner-first; for a
    # well-formed sibling file emission order equals file order. Sort by
    # start_line to guarantee file order regardless.
    regions.sort(key=lambda r: r.start_line)

    return ParsedAgent(front_matter=front_matter, regions=regions, raw=text)


# --------------------------------------------------------------------------- #
# validate (TD §2.4, D7)
# --------------------------------------------------------------------------- #

def validate(parsed: ParsedAgent, placeholder_keys: list[str] | None = None) -> Result:
    """
    Fail-closed structural validation (TD §2.4). Every violation is an error,
    not a warning. Does NOT enforce canonical *order* — compose() reorders on
    write — only structural integrity.

    If `placeholder_keys` is given (D7), additionally flag any `{KEY}` token for
    a passed key appearing inside a CORE or PACK body
    (E_PLACEHOLDER_IN_CORE_PACK). regions.py stays token-set-agnostic: it is
    *told* the keys, never reads config.sh / placeholders.manifest (D6).
    """
    errors: list[tuple[int, str, str]] = []

    # Re-scan the raw bytes for marker integrity so we can diagnose the exact
    # lines independent of parse()'s tolerant pairing. We work on the post-
    # front-matter body to mirror parse()'s view.
    fm = _FRONT_MATTER_RE.match(parsed.raw)
    body_offset = fm.end() if fm else 0
    fm_line_count = parsed.raw[:body_offset].count(b"\n") if fm else 0
    lines = _split_lines_keepends(parsed.raw[body_offset:])

    # --- Invariant 6: marker well-formedness (loose-but-not-strict) ---------- #
    for idx, raw_line in enumerate(lines):
        line_no = fm_line_count + idx + 1
        if _classify(raw_line) is None and _is_loose_marker(raw_line):
            errors.append((line_no, "E_MALFORMED_MARKER",
                           "line looks like an HOS marker but does not match the "
                           "strict grammar (check case, ':START'/':END', spacing)"))

    # --- Invariants 3 & 4: balanced markers + no nesting -------------------- #
    stack: list[tuple[str, int]] = []
    for idx, raw_line in enumerate(lines):
        line_no = fm_line_count + idx + 1
        classified = _classify(raw_line)
        if classified is None:
            continue
        region_id, edge = classified
        if edge == "START":
            if stack:
                # A START while a region is already open -> nesting (forbidden).
                errors.append((line_no, "E_NESTED",
                               f"region {region_id} opened inside still-open "
                               f"region {stack[-1][0]} (regions must be siblings)"))
            stack.append((region_id, line_no))
        else:  # END
            if not stack:
                errors.append((line_no, "E_UNBALANCED",
                               f"END marker for {region_id} with no open START"))
            else:
                open_id, _ = stack.pop()
                if open_id != region_id:
                    errors.append((line_no, "E_UNBALANCED",
                                   f"END marker for {region_id} does not match the "
                                   f"open region {open_id}"))
    for open_id, start_line in stack:
        errors.append((start_line, "E_UNBALANCED",
                       f"region {open_id} opened but never closed"))

    # --- Invariants 1, 2, 5: counts + uniqueness --------------------------- #
    core_count = sum(1 for r in parsed.regions if r.id == "CORE")
    project_count = sum(1 for r in parsed.regions if r.id == "PROJECT")

    if core_count == 0:
        errors.append((0, "E_NO_CORE", "no CORE region (exactly one required)"))
    elif core_count > 1:
        dup = [r for r in parsed.regions if r.id == "CORE"][1]
        errors.append((dup.start_line, "E_DUP_CORE",
                       f"{core_count} CORE regions (exactly one required)"))

    if project_count > 1:
        dup = [r for r in parsed.regions if r.id == "PROJECT"][1]
        errors.append((dup.start_line, "E_DUP_PROJECT",
                       f"{project_count} PROJECT regions (at most one allowed)"))

    seen_packs: dict[str, int] = {}
    for r in parsed.regions:
        if r.id.startswith("PACK:"):
            if r.name in seen_packs:
                errors.append((r.start_line, "E_DUP_PACK",
                               f"duplicate PACK region '{r.name}' (also at line "
                               f"{seen_packs[r.name]})"))
            else:
                seen_packs[r.name] = r.start_line

    # --- D7: placeholder-free CORE/PACK ------------------------------------ #
    if placeholder_keys:
        keys = [k for k in placeholder_keys if k]
        for r in parsed.regions:
            if r.id == "CORE" or r.id.startswith("PACK:"):
                try:
                    body_text = r.body.decode("utf-8", errors="replace")
                except Exception:  # pragma: no cover - decode with replace can't raise
                    continue
                for key in keys:
                    if "{" + key + "}" in body_text:
                        errors.append((r.start_line, "E_PLACEHOLDER_IN_CORE_PACK",
                                       f"placeholder '{{{key}}}' found in {r.id} region — "
                                       f"CORE/PACK must be placeholder-free (D1a/D7); "
                                       f"move it to PROJECT or use runtime self-direction"))

    errors.sort(key=lambda e: (e[0], e[1]))
    return Result(ok=not errors, errors=errors)


# --------------------------------------------------------------------------- #
# region_sha (TD §2.6)
# --------------------------------------------------------------------------- #

def region_sha(region_body: bytes) -> str:
    """
    sha256 over the region body with the trailing newline normalized to exactly
    one '\\n' (TD §2.6). This is the SAME normalization compose() writes between
    the markers, so disk and manifest never disagree:

        normalized = body.rstrip(b"\\r\\n") + b"\\n"

    Lowercase hex. Used for every region row in the manifest and every
    three-way comparison. (Whole-file rows keep the installer's `_sha256` over
    raw file bytes — do NOT route whole-file through region_sha.)
    """
    normalized = region_body.rstrip(b"\r\n") + b"\n"
    return hashlib.sha256(normalized).hexdigest()


# --------------------------------------------------------------------------- #
# compose (TD §2.5) — the ONLY writer
# --------------------------------------------------------------------------- #

def _canonical_order_key(region: Region) -> tuple:
    """Sort key implementing CORE -> PACK(alpha) -> PROJECT."""
    if region.id == "CORE":
        bucket = 0
        name = ""
    elif region.id.startswith("PACK:"):
        bucket = 1
        name = region.name or ""
    elif region.id == "PROJECT":
        bucket = 2
        name = ""
    else:  # pragma: no cover - parse never produces other ids
        bucket = 3
        name = region.id
    return (bucket, name)


def compose(parsed_or_regions: ParsedAgent | list[Region]) -> bytes:
    """
    Rebuild the canonical file (TD §2.5). The ONLY writer.

    Order: front-matter -> CORE -> each PACK:<name> in alphabetical name order
    -> PROJECT last. PROJECT is NOT synthesized if absent (callers that need an
    empty stub create it explicitly — installer §7.1).

    Each region is emitted as:
        <canonical START marker>\\n
        <body, trailing newline normalized to exactly one \\n>
        <canonical END marker>\\n
    with a single blank line separating regions. The body emitted is exactly
    `body.rstrip(b"\\r\\n") + b"\\n"`, the same bytes region_sha hashes — so
    region_sha(parse(compose(x))) == region_sha(x) for well-formed x.

    Out-of-region prose is NOT reproduced here (D8 — compose owns canonical
    output; only region bodies travel). Front-matter is reattached verbatim.
    """
    if isinstance(parsed_or_regions, ParsedAgent):
        front_matter = parsed_or_regions.front_matter
        regions = list(parsed_or_regions.regions)
    else:
        front_matter = b""
        regions = list(parsed_or_regions)

    ordered = sorted(regions, key=_canonical_order_key)

    chunks: list[bytes] = []
    if front_matter:
        chunks.append(front_matter)

    blocks: list[bytes] = []
    for r in ordered:
        normalized_body = r.body.rstrip(b"\r\n") + b"\n"
        block = (
            _canonical_start(r.id) + b"\n"
            + normalized_body
            + _canonical_end(r.id) + b"\n"
        )
        blocks.append(block)

    # A single blank line separates region blocks.
    chunks.append(b"\n".join(blocks))

    return b"".join(chunks)


def make_empty_project_region(start_line: int = 0) -> Region:
    """Synthesize an empty PROJECT region (installer §7.1 empty-stub seeding).

    compose() never creates this implicitly; the installer calls this to seed a
    consumer's marked place to add content on a first install.
    """
    return Region(id="PROJECT", name=None, body=b"", start_line=start_line,
                  end_line=start_line)


# --------------------------------------------------------------------------- #
# manifest-rows helper (TD §1.4 / §2.7)
# --------------------------------------------------------------------------- #

def manifest_rows(path: str, parsed: ParsedAgent) -> list[str]:
    """
    Produce `path\\tregion\\tsha` rows for every region, in canonical order
    (CORE -> PACK(alpha) -> PROJECT). A flat (marker-less) file yields a single
    CORE row (implicit-CORE rule) — the caller is responsible for the
    provenance gate that decides flat-file CORE vs PROJECT at migration time
    (§5); at enumeration of HOS source every file is HOS-owned so CORE is
    correct.
    """
    if not parsed.regions:
        # Implicit single CORE over the whole (marker-less) body.
        sha = region_sha(parsed.raw[len(parsed.front_matter):]
                         if parsed.front_matter else parsed.raw)
        return [f"{path}\tCORE\t{sha}"]

    ordered = sorted(parsed.regions, key=_canonical_order_key)
    rows = []
    for r in ordered:
        rows.append(f"{path}\t{r.id}\t{region_sha(r.body)}")
    return rows


# --------------------------------------------------------------------------- #
# CLI (TD §2.7)
# --------------------------------------------------------------------------- #

def _read_file(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _cmd_manifest_rows(args) -> int:
    data = _read_file(args.file)
    try:
        parsed = parse(data)
    except ParseError as e:
        sys.stderr.write(f"{args.file}: parse error {e}\n")
        return EXIT_INVALID
    result = validate(parsed)
    if not result.ok:
        for line, code, msg in result.errors:
            sys.stderr.write(f"{args.file}:{line}:{code}:{msg}\n")
        return EXIT_INVALID
    for row in manifest_rows(args.file, parsed):
        sys.stdout.write(row + "\n")
    return EXIT_OK


def _cmd_validate(args) -> int:
    data = _read_file(args.file)
    keys = None
    if args.placeholder_keys:
        keys = [k.strip() for k in args.placeholder_keys.split(",") if k.strip()]
    try:
        parsed = parse(data)
    except ParseError as e:
        # A structurally impossible read is itself an invalid file.
        sys.stdout.write(f"{e.line}:{e.kind}:{e.msg}\n")
        return EXIT_INVALID
    result = validate(parsed, placeholder_keys=keys)
    if result.ok:
        return EXIT_OK
    for line, code, msg in result.errors:
        sys.stdout.write(f"{line}:{code}:{msg}\n")
    return EXIT_INVALID


def _cmd_region_sha(args) -> int:
    data = _read_file(args.file)
    try:
        parsed = parse(data)
    except ParseError as e:
        sys.stderr.write(f"{args.file}: parse error {e}\n")
        return EXIT_INVALID
    target = args.region_id
    if not parsed.regions and target == "CORE":
        body = parsed.raw[len(parsed.front_matter):] if parsed.front_matter else parsed.raw
        sys.stdout.write(region_sha(body) + "\n")
        return EXIT_OK
    for r in parsed.regions:
        if r.id == target:
            sys.stdout.write(region_sha(r.body) + "\n")
            return EXIT_OK
    sys.stderr.write(f"{args.file}: region '{target}' not present\n")
    return EXIT_REGION_ABSENT


def _cmd_compose(args) -> int:
    data = _read_file(args.file)
    try:
        parsed = parse(data)
    except ParseError as e:
        sys.stderr.write(f"{args.file}: parse error {e}\n")
        return EXIT_INVALID
    out = compose(parsed)
    sys.stdout.buffer.write(out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="regions.py",
        description="HOS region mechanism: parse/validate/compose/sha for layered agent .md files.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    mr = sub.add_parser("manifest-rows", help="emit path<TAB>region<TAB>sha rows (canonical order)")
    mr.add_argument("file")
    mr.set_defaults(func=_cmd_manifest_rows)

    va = sub.add_parser("validate", help="fail-closed structural validation (exit 2 on invalid)")
    va.add_argument("file")
    va.add_argument("--placeholder-keys", default=None,
                    help="comma-separated keys; flag any {KEY} inside CORE/PACK (D7)")
    va.set_defaults(func=_cmd_validate)

    rs = sub.add_parser("region-sha", help="print the sha of one region (exit 3 if absent)")
    rs.add_argument("file")
    rs.add_argument("region_id", metavar="region-id")
    rs.set_defaults(func=_cmd_region_sha)

    co = sub.add_parser("compose", help="print canonical bytes (the only writer's output)")
    co.add_argument("file")
    co.set_defaults(func=_cmd_compose)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        sys.stderr.write(f"file not found: {e.filename}\n")
        return EXIT_USAGE
    except ParseError as e:  # pragma: no cover - per-command handlers catch first
        sys.stderr.write(f"parse error: {e}\n")
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
