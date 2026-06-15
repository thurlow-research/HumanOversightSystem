# v0.3.0 — Layering Installer: Implementation Technical Design

**Status:** implementation contract for the region/layering mechanism. Derived from `docs/specs/v0.3.0-base-agents-spec.md` (§4, §5/§5a, §7, §11 ADR) and `docs/v0.3.0/CORE-PACK-PROJECT-rubric.md`. Binding inputs are the architect ADR §11 decisions **D1–D5**.

This is a **design** — exact signatures, formats, schemas, control flow, and invariants. It is not code. Where the ADR/spec leaves a real technical gap, it is listed at the end under **Flags for the architect** — those are *not* resolved here.

**Scope.** This design covers the on-disk region mechanism: the `.hos-manifest` schema, the standalone region module, placeholder/sha handling, the three-way per-region merge, flat-file migration, the `dispatches:`/completeness gate, and where each hooks into `bootstrap/hos_install.sh`. It does **not** cover authoring the 13 base agents (Phase 0b/2), nor the `--pr`-default flip (deferred per ADR D5.2/5.4 — §7 below records the deferral only).

---

## 0. Terms & naming (used throughout)

| Term | Meaning |
|---|---|
| **region** | A marker-delimited span inside an agent `.md`: `CORE`, `PACK:<name>`, or `PROJECT`. |
| **whole-file** | The hash unit for non-agent framework files (scripts, validators, AGENTS.md) — no markers, the entire file's bytes. |
| **region id** | The canonical string naming a region: `CORE` \| `PACK:<name>` \| `PROJECT` \| the literal `WHOLE` for whole-file rows. |
| **region body** | The raw bytes **strictly between** the START and END marker lines (marker lines themselves excluded), trailing newline normalized to exactly one. |
| **`base_sha`** | The sha256 HOS last wrote to disk for a region/file — **post-substitution** bytes (D1). Stored in `.hos-manifest`. |
| **`disk_sha`** | The sha256 of the region/file **currently on disk** (post-substitution, as it sits). |
| **`incoming`** | The sha256 of the region HOS *would write this upgrade*: `sha(new template region body ⊕ current config.sh)` (D1). For CORE/PACK this equals `sha(new template region body)` because CORE/PACK carry no placeholders. |
| **HOS-owned region** | `CORE` or `PACK:<name>`. Refreshable; subject to the three-way merge. |
| **consumer-owned region** | `PROJECT`. **Never written.** |
| **provenance oracle** | `scripts/framework/consumer_agents.txt` — the authoritative list of agent slugs HOS ships (D3). |

New code lives in a single module: `scripts/oversight/validators/regions.py` (sibling of `schema.py`, per the architect's "schema.py is the right home/pattern"). The installer (bash) shells out to it. Rationale: byte-exact region parsing, sha, and three-way logic must be deterministic and unit-testable; bash cannot do this safely.

---

## 1. The `.hos-manifest` schema

### 1.1 File format

Plain text, LF-terminated, one record per line. **First non-blank line is the schema-version marker** (ADR D5.6):

```
# hos-manifest-schema: 2
<path>\t<region>\t<sha256>
<path>\t<region>\t<sha256>
...
```

- `\t` is a literal TAB (`0x09`). Exactly one TAB between each of the three columns when a row is 3-column.
- `<path>` is repo-root-relative, forward-slash, no leading `./` (e.g. `.claude/agents/security-reviewer.md`).
- `<region>` is a **region id** (§0): `CORE` | `PACK:<name>` | `PROJECT` | `WHOLE`.
- `<sha256>` is the lowercase hex sha256 of the region body (§0) — for `WHOLE`, of the entire file's bytes (unchanged from today's `_sha256`).
- Rows are sorted by `LC_ALL=C sort` on the full line for stable diffs. The schema-version comment line is written **first** and is exempt from the sort (the writer emits it, then the sorted body).
- Blank lines and lines beginning with `#` are ignored by the reader (so the schema marker is itself a `#` comment — readers skip it for data purposes but the writer/migrator inspect it; see 1.3).

### 1.2 Region naming rules

- `CORE` — exactly one per agent file (validator enforces; §2.2).
- `PACK:<name>` — zero or more. `<name>` matches `[a-z0-9][a-z0-9-]*` (lowercase pack slug, e.g. `django`, `hos-dev`). Multiple `PACK:` rows for one path are allowed (multi-pack, untested per spec §10.1) and MUST be emitted in alphabetical `<name>` order.
- `PROJECT` — at most one per agent file. **A `PROJECT` row is recorded in the manifest for boundary-tracking but its sha is informational only** — the upgrade path never compares or refreshes it (the never-written invariant, §4.4). Recording it lets the installer locate the PROJECT boundary on the next run without re-parsing assumptions.
- `WHOLE` — used for every non-agent framework file (scripts, validators, `AGENTS.md`, `METHODOLOGY.md`). These have no regions; the row is the whole-file sha exactly as the current `enumerate_framework_files` produces, with the region column added.

### 1.3 Two-column back-compat read (D5.6 migration detection)

A **2-column row** `<path>\t<sha256>` (no region column) is the **legacy v1 manifest format** (today's `enumerate_framework_files` output). The reader MUST accept it and interpret it as `region = WHOLE`. Detection is per-row, not per-file:

```
parse_manifest_line(line) -> (path, region, sha)
  if line starts with "#" or is blank: skip (None)
  split on TAB → fields
  if len(fields) == 3: (path, region, sha)          # v2
  if len(fields) == 2: (path, "WHOLE", sha)          # v1 back-compat
  else: error "malformed manifest row"
```

The **schema-version marker** governs *write* behavior and migration messaging, not read tolerance:
- If the marker is absent → manifest is **v1** (legacy). The installer treats this as a one-time upgrade: it reads rows as 2-column WHOLE, performs flat-file migration (§5) where applicable, and **writes back a v2 manifest with the marker**.
- If the marker says `2` → current. Read 3-column.
- If the marker says `N > 2` (a manifest from a *newer* HOS than the installer) → **hard error**: "manifest schema N is newer than this installer supports (max 2) — upgrade HOS or do not downgrade." Exit non-zero, change nothing. (This is the "detectable migration" payoff of D5.6.)

`CURRENT_SCHEMA = 2` is a constant in `regions.py`.

### 1.4 How `enumerate_framework_files` must change

Today (hos_install.sh ~L828–847) it emits `<path>\t<sha256>` for: the consumer agent set (from `consumer_agents.txt`), `scripts/oversight/**`, and a fixed list of top-level scripts + `AGENTS.md`/`METHODOLOGY.md`.

**New behavior — the function emits region rows, not whole-file rows, for agent `.md` files, and is delegated to `regions.py` for those:**

1. **Non-agent files** (`scripts/oversight/**`, runner scripts, `AGENTS.md`, `METHODOLOGY.md`): unchanged except the region column. Emit `<path>\tWHOLE\t<sha256>`. (Same `_sha256` over the whole file.)
2. **Agent files** (each slug in `consumer_agents.txt` that exists as `.claude/agents/<slug>.md`): the installer calls
   ```
   python3 regions.py manifest-rows <path>
   ```
   which parses the file's markers and prints one row **per region present**, in canonical order:
   ```
   <path>\tCORE\t<sha>
   <path>\tPACK:<name>\t<sha>      # alpha order, zero or more
   <path>\tPROJECT\t<sha>          # if a PROJECT region exists
   ```
   A flat (marker-less) agent file yields a single `CORE` row (implicit-CORE rule, §4 spec) **only when the file's provenance is HOS-owned** — but at *enumeration of the HOS source* this is always true (every file enumerated comes from the HOS source tree, which by construction is HOS-owned). Provenance gating applies to the **target's** files during migration (§5), not to source enumeration.
3. The function still pipes everything through `LC_ALL=C sort -u`, then the **writer prepends the schema-version line** (`# hos-manifest-schema: 2`).

The single-source-of-truth coupling with `consumer_agents.txt` is preserved (the manifest can only list agents the copy-loop installs — HOS#225). The only change is that an agent path now contributes N region rows instead of 1 whole-file row.

---

## 2. The region module — `scripts/oversight/validators/regions.py`

Standalone, deterministic, no third-party deps (stdlib `hashlib`, `re`, `sys` only — it must run in the target's venv-less context the same way `_sha256` does today). Mirrors `schema.py`'s "pure functions + a thin CLI" shape.

### 2.1 Marker grammar (exact)

A marker is a **whole line** (after stripping trailing whitespace) matching exactly one of:

```
<!-- HOS:CORE:START -->
<!-- HOS:CORE:END -->
<!-- HOS:PACK:<name>:START -->          <name> ∈ [a-z0-9][a-z0-9-]*
<!-- HOS:PACK:<name>:END -->
<!-- HOS:PROJECT:START -->
<!-- HOS:PROJECT:END -->
```

Regex (anchored, the only accepted marker form):
```
^<!--\s+HOS:(CORE|PACK:[a-z0-9][a-z0-9-]*|PROJECT):(START|END)\s+-->$
```

- Exactly one space-run is canonical (`<!-- ` and ` -->`); the regex tolerates `\s+` so a reflowed file still parses, but `compose()` always **emits the canonical single-space form**.
- A marker line contributes **no bytes** to any region body (markers excluded from the hash, per spec §4 — "a marker-format tweak doesn't churn the sha").
- Anything that looks marker-ish but doesn't match the anchored regex (e.g. `<!-- HOS:CORE -->` with no `:START`, or `HOS:core:start` lowercased) is **not** a marker — it is body text. This is deliberate fail-closed behavior: a malformed marker becomes unbalanced (no matching START/END) and `validate()` rejects the file.

### 2.2 Data model

```
@dataclass(frozen=True)
class Region:
    id: str          # "CORE" | "PACK:<name>" | "PROJECT"
    name: str|None   # pack name for PACK:*, else None
    body: bytes      # bytes strictly between markers, BEFORE newline normalization
    start_line: int  # 1-based line index of the START marker (for error messages)
    end_line: int

# The whole parsed file:
@dataclass
class ParsedAgent:
    front_matter: bytes      # the YAML front-matter block incl. delimiters, or b"" if none
    preamble: bytes          # any bytes between front-matter and the first marker (e.g. a "## Project Extensions" heading) — preserved verbatim, reattached by compose() to the region it precedes
    regions: list[Region]    # in file order as found
    raw: bytes               # the original file bytes (for round-trip / migration)
```

`preamble`/inter-region prose (e.g. the `## Project Extensions (yours…)` heading shown in the spec §4 example) is **not** part of any region body and is **not** hashed. `compose()` reattaches headings to the region they introduce (see 2.5). Heading-to-region association is positional: text immediately preceding a START marker belongs to that region's "lead-in" and travels with it.

### 2.3 `parse(text: bytes) -> ParsedAgent`

- Split into lines preserving exact bytes; classify each line as marker (per 2.1) or body.
- Walk markers maintaining a stack. On `START`, push; on `END`, pop and emit a `Region` whose `body` is the bytes of all lines strictly between the matched START and END.
- Front-matter: if the file begins with a `---\n ... \n---\n` block, capture it as `front_matter`; markers are searched only after it.
- Does **not** validate (that's `validate()`); `parse` is tolerant so `validate` can produce precise diagnostics. `parse` raises only on a structurally impossible read (e.g. an `END` with an empty stack, an EOF inside an open region) — those are returned as a structured `ParseError(line, kind, msg)`.

### 2.4 `validate(parsed: ParsedAgent) -> Result`

Returns `ok` or a precise error (`Result.ok: bool`, `Result.errors: list[(line, code, msg)]`). **Fail-closed** — every violation below is an error, not a warning (spec §4 marker integrity, #236):

Structural invariants (all must hold):
1. **Exactly one `CORE` region.** Zero → `E_NO_CORE`. Two+ → `E_DUP_CORE`.
2. **At most one `PROJECT` region.** Two+ → `E_DUP_PROJECT`.
3. **Balanced markers** — every START has a matching END of the same id; no END without an open START. Violations → `E_UNBALANCED` (with the offending line).
4. **No overlap / proper nesting is *forbidden*** — regions are siblings, never nested. A START encountered while a region is already open → `E_NESTED`.
5. **Unique PACK names** — no two `PACK:<name>` with the same `<name>` → `E_DUP_PACK`.
6. **Marker well-formedness** — any line matching the loose pattern `<!--\s*HOS:` but not the strict regex (2.1) → `E_MALFORMED_MARKER` (catches typo'd markers that would otherwise silently become body and unbalance the file).
7. **No literal marker inside a region body** (B1, spec §4) — marker lines are a reserved whole-line token with **no code-fence exemption**, so a body line matching the strict grammar (2.1) → `E_LITERAL_MARKER_IN_BODY` at the offending line. This is the **direct** diagnostic (names the cause: a marker line inside a body), distinct from the `E_DUP_CORE`/`E_NESTED` symptoms a re-parse of such a body would otherwise produce. Documentation that must show a marker renders it inline in backticks or breaks the column-0 form. `parse()` does **not** change — it stays byte-exact/tolerant; this is a `validate()`-only invariant.

`validate()` does **not** enforce canonical *order* (that's `compose()`'s job — it reorders). It only enforces structural integrity. Order is normalized on write, not rejected on read, so a hand-edited out-of-order file still upgrades cleanly.

### 2.5 `compose(parsed_or_regions, packs_order=None) -> bytes`

Rebuilds the canonical file the installer writes to disk. **This is the only writer.**

- Order: front-matter → (preamble/lead-in for CORE) → **CORE** → each **PACK:<name> in alphabetical name order** → **PROJECT** last (spec §4 — recency precedence). If `PROJECT` absent, it is **not** synthesized by compose (callers that need an empty stub create it explicitly — see installer §7.1).
- Each region is emitted as: canonical START marker line, `\n`, the region body with **trailing newline normalized to exactly one `\n`**, the canonical END marker line, `\n`.
- A single blank line separates regions (matches the spec §4 example). Lead-in headings (e.g. `## Project Extensions`) are emitted immediately before their region's START marker.
- Line-ending + trailing-newline normalization rule (applied to each body before hashing *and* before writing, so the hash matches the on-disk bytes): first normalize **all** line endings to LF (CRLF→LF, then bare CR→LF), then strip all trailing `\n`, then append exactly one trailing `\n`. The body used for sha and the body *written* between the markers are the SAME normalized bytes. **The sha is over the LF-normalized, single-trailing-`\n` body** — defined **once** in `_normalize_body(body)`, used by both `region_sha` and the writer, so disk and manifest never disagree (the D1 "substitution before sha" guarantee, and its line-ending analogue D1(c), depend on this identity). **`compose` writes LF-only bodies, so D1 holds at write time** — the bytes HOS writes equal the bytes it hashes, and a cross-platform (`autocrlf`) checkout does not register as drift.

> **Normalization decision (load-bearing):** `_normalize_body(body)` = `body.replace(b"\r\n", b"\n").replace(b"\r", b"\n").rstrip(b"\n") + b"\n"`. `region_sha` hashes it; `compose` writes exactly those bytes between the markers. Therefore `region_sha(parse(compose(x))) == region_sha(x)` for any well-formed `x`, and the same content authored LF vs CRLF yields equal `region_sha` (the Windows-checkout-upgrade scenario is normalized away, not flagged as drift) — round-trip stable. This is the testable identity the coder must assert.

### 2.6 `region_sha(region_body: bytes) -> str`

```
_normalize_body(body) -> bytes
  return body.replace(b"\r\n", b"\n").replace(b"\r", b"\n").rstrip(b"\n") + b"\n"

region_sha(body) -> hexdigest
  return sha256(_normalize_body(body)).hexdigest()
```

`_normalize_body` is the single shared definition (LF-normalize, strip trailing newlines, append exactly one) called by **both** `region_sha` and `compose`'s per-region body emission, so the manifest sha and the on-disk bytes are always the same bytes.

Lowercase hex. Used for every region row in the manifest and every three-way comparison. (Whole-file rows keep using the installer's existing `_sha256` over raw file bytes — do **not** route whole-file through `region_sha`; they are different units.)

### 2.7 CLI surface (what the installer calls)

`regions.py` exposes a subcommand CLI so bash can drive it without embedding Python:

| Invocation | Output (stdout) | Exit |
|---|---|---|
| `regions.py manifest-rows <file>` | one `path\tregion\tsha` line per region (canonical order); for a flat file, one `CORE` row | 0; non-zero + stderr diagnostic on validate failure |
| `regions.py validate <file>` | nothing on success; `line:CODE:msg` lines on failure | 0 ok / 2 invalid |
| `regions.py region-sha <file> <region-id>` | the sha of that region | 0; 3 if region absent |
| `regions.py compose <file>` | canonical bytes to stdout (used by migration/squash to rewrite) | 0 |
| `regions.py merge <file> <region-id> <base_sha> <incoming_sha> <incoming_body_file>` | the **action token** (see §4) on stdout; writes nothing | per §4 exit codes |
| `regions.py migrate <file> --provenance core\|project` | rewrites a flat file into a single wrapped region (§5); prints the resulting manifest rows | 0; non-zero on dirty/validate failure |

All subcommands that *could* write take an explicit `--in-place` flag; without it they print to stdout (dry-run friendly — the installer's `$DRY_RUN` path uses stdout only).

---

## 3. Placeholder / sha handling (ADR D1)

### 3.1 The substitution-before-sha guarantee

The live mechanism (hos_install.sh L486–551): after copying agent files, `perl -i` substitutes declared placeholders (`scripts/framework/placeholders.manifest` × `config.sh`) **in place** in `.claude/agents/*.md`.

**Binding ordering (D1c):** the per-region sha recorded in `.hos-manifest` MUST be computed **after** placeholder substitution runs. Concretely, in the installer's control flow:

```
1. copy agent files                          (existing copy-loop)
2. perl -i placeholder substitution          (existing, L545–551)
3. region migration (first run only, §5)
4. enumerate_framework_files → manifest-rows  (NEW position: AFTER step 2)
5. write .hos-manifest
```

Today the manifest is written at the very end (L811–919), which is already after substitution — so the ordering is preserved by keeping manifest writing last. The design's only requirement: **manifest writing must never move before the perl substitution block.** Add an assertion/comment at the manifest block: "INVARIANT (D1): runs after placeholder substitution — base_sha is post-substitution."

### 3.2 The template-substituted three-way comparison

On an **upgrade** (target already has a `.hos-manifest`), for each HOS-owned region of each agent file, the installer computes three shas:

- `base_sha` = the sha in the **existing** target manifest for `(path, region)`. (Post-substitution, written by the prior install — by 3.1.)
- `disk_sha` = `region_sha` of the region **currently on disk in the target** (already substituted — it's the live file).
- `incoming` = the sha of the region HOS would write *this* upgrade, computed in **template-substituted space** (D1c):
  ```
  incoming = region_sha( substitute( new_template_region_body, current_target_config ) )
  ```
  where `substitute(...)` applies the same perl substitution the installer applies, using the **target's current `config.sh`**. So a consumer who only changed a `config.sh` *value* (not the region body) is **not** falsely flagged — `incoming` already reflects their config.

**For CORE/PACK this simplifies (D1a/b):** CORE and PACK regions contain **no placeholders** (rubric + D1a — banned). Therefore `substitute(new_template_region_body, config) == new_template_region_body`, and `incoming == region_sha(new_template_region_body)` with no config dependency. The substituted-space machinery exists for correctness/uniformity, but for HOS-owned regions it reduces to a plain template-body hash. **This is the point of D1a:** by banning placeholders from CORE/PACK, the three-way comparison for HOS-owned regions is config-independent and stable across `config.sh` edits.

### 3.3 Where config-derived content goes (the CORE/PACK no-placeholder rule)

Because CORE/PACK carry no `{PLACEHOLDER}` tokens (D1a, rubric §"placeholder rule"):

- Config-specific values (`{SPEC_FILE}`, `{ADR_FILE}`, project paths, names) MUST NOT appear literally in CORE/PACK region bodies.
- Replacement mechanism is **runtime self-direction**: the CORE body instructs the agent to *resolve the value at runtime* — e.g. "read the spec path declared in `scripts/framework/config.sh`" rather than literal `{SPEC_FILE}`. The agent reads config when it runs; the region bytes stay stable across installs.
- Any genuinely unavoidable literal placeholder lives in **PROJECT only** (D1b) — which HOS never hashes for refresh (§4.4), so a substituted token there can never trip a false-edit on upgrade.

**Consequence for the substitution block:** the perl substitution (L545–551) still runs over the whole file, but after authoring it should find **placeholders only inside PROJECT regions** of base agents. The substitution mechanism is unchanged; the *authoring rule* (no placeholders in CORE/PACK) is what makes the sha model sound. The installer does not need to enforce "no placeholder in CORE/PACK" at runtime, but **a Phase-0 dev-pack check SHOULD assert it** (see Flags).

---

## 4. `merge_region` — the three-way decision (spec §5, ADR D2)

### 4.1 Signature

```
merge_region(region_id: str, base_sha: str|None, disk_sha: str, incoming: str) -> Action
```

`Action ∈ { REFRESH, KEEP, HARDSTOP, SKIP_PROJECT, DROP }`. Pure function — decides; does not write. The installer acts on the returned action. (`DROP` added per ADR §11a/D9 — a region HOS removed this release.)

### 4.2 The decision table (EXACTLY — spec §5)

Evaluated per HOS-owned region. `PROJECT` short-circuits before this table (4.4).

| Condition | `base_sha` vs `disk_sha` | `disk_sha` vs `incoming` | Action | Meaning |
|---|---|---|---|---|
| 1 | `base == disk` (unedited) | `disk == incoming` | **KEEP** | HOS made no change to this region this release; disk already matches. No write; re-stamp `base_sha = incoming` (a no-op value). |
| 2 | `base == disk` (unedited) | `disk != incoming` | **REFRESH** | Region untouched by consumer; HOS has a new version → write `incoming` body, record `base_sha = incoming`. |
| 3 | `base != disk` (consumer-edited) | `disk == incoming` | **KEEP** | Consumer edited it *to* exactly what HOS now ships (convergent edit). No write needed; record `base_sha = incoming` (re-aligns the manifest; no longer "drifted"). |
| 4 | `base != disk` (consumer-edited) | `disk != incoming` | **HARDSTOP** (unless `--squash`) | Genuine drift: consumer edited, HOS also differs. Refuse (4.3). With `--squash` → **REFRESH** (take HOS's version). |

**Removed-region rows (ADR §11a/D9) — a `(path, region)` is in the manifest (CORE/PACK) but ABSENT from the new template (HOS retired it).** Detected by a **manifest-side sweep** (4.5), not the template-side loop above (the template can't tell you about a region it no longer has):

| Condition | `base_sha` vs `disk_sha` | Action | Meaning |
|---|---|---|---|
| 5 | region removed by HOS, `base == disk` (**unedited**) | **DROP** | Consumer never touched it; remove the region from the file + its manifest row. Required for cumulative-faithfulness (§5a — the upgrade must reflect HOS's *absences* too). |
| 6 | region removed by HOS, `base != disk` (**edited**) | **HARDSTOP** (unless `--squash`/`--prune`) | Deleting a consumer edit is still a clobber (D2 philosophy). Refuse with the per-region report; `--squash` or `--prune` is the explicit consent to drop → **DROP**. |

`PROJECT` is never in this sweep (HOS never authored it to remove). `DROP` is a write in Phase B (`compose()` omits the region + its manifest row).

- **Row 3 is the "edit matching the new release" case** the spec §5 calls out as the bug in the naïve two-way check. Here it is correctly a KEEP/realign, never a clobber.
- `base_sha is None` (region present on disk but absent from the manifest — e.g. a freshly-introduced region, or a legacy manifest) is treated as **`base != disk`** (unknown provenance ⇒ assume edited ⇒ conservative). It then falls to row 3 or 4. This makes a newly-introduced CORE over a flat file route through migration (§5) rather than silently refreshing.

### 4.3 The D2 hard-stop (drifted HOS-owned region, no `--squash`)

When **any** HOS-owned region across the whole install resolves to **HARDSTOP**:

1. **Refuse the entire upgrade** — not just the one region. (Cumulative-install invariant, §5a/#238: a partial install that stamps a new version is the banned class.)
2. Emit a **precise per-region drift report** to stderr: for each HARDSTOP region, the path, region id, `base_sha`, `disk_sha`, and the two remedies (verbatim from spec §5):
   - re-run with `--squash` to take HOS's complete version (your edit is recoverable in the git diff), or
   - move your edit into the `PROJECT` region of that file, then re-run.
3. **Do NOT write `.hos-release`** and **do NOT write `.hos-manifest`** — the version stamp must reflect a *complete* install only (§5a ban on stamping a version it didn't fully install).
4. **Exit non-zero** (define `EXIT_DRIFT = 3`).
5. Write **nothing to any agent file** in this run (no partial application — collect all actions first, *then* decide; see control flow 4.5).

`--squash` converts every HARDSTOP to REFRESH for CORE/PACK regions **only**; PROJECT is never touched even under `--squash` (4.4). `--squash` is opt-in explicit consent (spec §5).

### 4.4 The PROJECT never-written invariant (testable)

Before the table, PROJECT short-circuits:

```
if region_id == "PROJECT" or region_id startswith "PROJECT":
    return SKIP_PROJECT     # parsed for boundaries, never compared, never written
```

**Testable invariant the coder MUST assert (and a system test MUST cover):**
> For *any* input — including `--squash`, including a drift hard-stop, including first-run migration — the bytes of every `PROJECT` region on disk are **byte-identical before and after** the installer runs. Implementation: capture `region_sha(PROJECT)` of every agent file pre-run; assert unchanged post-run. `--squash` does not exempt this.

`compose()` reattaches the existing on-disk PROJECT region verbatim (its body is carried through from `parse()` of the current disk file, never from the template). The template's PROJECT, if any, is used **only** on a blank/first install to seed an empty stub (§7.1).

### 4.5 Installer control flow for the merge (two-phase: decide-all-then-act)

```
PHASE A (decide — no writes):
  for each agent file in consumer set:
    parsed_disk   = parse(disk file)         ; validate() → fail-closed halt on E_*
    parsed_tmpl   = parse(substituted template)
    for each HOS-owned region in parsed_tmpl:
       base     = manifest[(path, region)]   (or None)
       disk     = region_sha(parsed_disk[region])  (or None if region absent on disk)
       incoming = region_sha(parsed_tmpl[region])
       action   = merge_region(region, base, disk, incoming)
       record (path, region, action)
    # Removed-region sweep (D9): manifest-side, not template-side.
    for each (path, region) in manifest where region ∈ {CORE, PACK:*} and region NOT in parsed_tmpl:
       disk = region_sha(parsed_disk[region])           # present on disk, retired by HOS
       record (path, region, DROP if manifest[base]==disk else HARDSTOP)   # rows 5/6
  if any action == HARDSTOP and not (--squash or --prune):
     emit drift report; exit EXIT_DRIFT      # nothing written, no stamp (4.3)

PHASE B (act — writes, only if Phase A cleared):
  for each agent file:
     compose new file = CORE/PACK from {REFRESH→template body, KEEP→disk body}
                        (DROP regions omitted) + PROJECT verbatim from disk (or empty stub on first install)
     write file (respecting $DRY_RUN)
     update manifest rows: base_sha = incoming for REFRESH/KEEP-realign; PROJECT row informational; DROP → remove the row
  write .hos-manifest (v2, schema marker)
  write .hos-release
```

The decide/act split is what makes 4.3's "refuse the whole upgrade, change nothing" achievable — no file is written until every region has cleared.

---

## 5. Flat-file migration (ADR D3)

First time the layering installer runs against a target whose agent files have **no markers** (Phase-0 flat files, or pre-existing consumer agents). One-time, content-preserving.

### 5.1 Preconditions (D3 / §8)

- **`--dry-run` supported and recommended first** — migration prints exactly which files become CORE vs PROJECT and the resulting manifest rows, writing nothing.
- **Git-clean precondition:** migration (which rewrites files) requires a clean working tree in the target (`git status --porcelain` empty). If dirty → refuse migration with a clear error ("commit or stash before migrating to the region format"), exit non-zero. (Rationale: migration is a bulk rewrite; the consumer must be able to `git diff`/revert it. Mirrors the existing `--pr` clean-tree gate at L394.)
- Migration runs **once** — after it, files have markers and the manifest is v2; subsequent runs take the normal three-way path (§4).

### 5.2 The provenance gate (D3 — the load-bearing rule)

For each flat (marker-less) agent `.md` in the **target**:

```
slug = basename without .md
if slug in consumer_agents.txt (HOS ships this agent):
    → wrap entire body as a single CORE region          (implicit-CORE, legible to upgrade)
else:
    → wrap entire body as a single PROJECT region        (sacred — unknown provenance)
```

- **HOS-owned name → CORE:** the file is (a copy of) an HOS agent; its body becomes CORE so future upgrades can refresh it. `migrate(file, --provenance core)`.
- **Unknown name → PROJECT:** a consumer's own agent. Its body becomes PROJECT so `--squash` can never destroy it (D3: "else `--squash` destroys consumer customizations"). `migrate(file, --provenance project)`. *No CORE is added* — it's purely consumer-owned until/unless HOS later ships that name (next bullet).

### 5.3 Newly-introduced CORE over an existing flat consumer file (D3, redundant-but-safe)

When **this release** introduces an HOS CORE for a name that **already exists as a flat consumer file** in the target (i.e. the slug is *now* in `consumer_agents.txt` but the target's file predates that and has no markers):

```
1. take the existing flat body → wrap as PROJECT region (consumer keeps it, verbatim)
2. PREPEND the fresh HOS CORE region (from the template) above it
3. result: CORE (HOS) → PROJECT (consumer's old body). NO merge of the two bodies.
```

- This is **never a lossy merge** (D3): the consumer's prior content survives intact in PROJECT; HOS's new generic version is added as CORE. Recency precedence (PROJECT last) means the consumer's body still governs where they conflict.
- Detection: the slug is in `consumer_agents.txt` **and** the file has no `CORE` marker on disk **and** there is no manifest row for `(path, CORE)`. (A file that already migrated has a CORE marker; it takes the §4 path, not this one.)
- `region_sha(CORE)` is recorded as `base_sha` so the next upgrade can three-way the CORE; the PROJECT body is recorded informational only.

### 5.4 Migration output & idempotency

- After migration, every migrated file passes `validate()` (fail-closed: if a migrated file somehow fails to validate, halt and report — never leave a half-wrapped file).
- The migrator is idempotent: a file that already has markers is left untouched (it's not flat). Running migration twice is a no-op on the second run.
- Migration emits an `audit/oversight-log.jsonl` event per migrated file: `{"event":"hos-region-migrate","file":...,"provenance":"core|project","sha":...,"release":...,"timestamp":...}` (reusing the existing append pattern at L892).

---

## 6. `dispatches:` front-matter + the completeness gate (spec §7, #234)

### 6.1 Front-matter field format

Each agent `.md` declares dispatches in YAML front-matter (the block the installer already preserves):

```yaml
---
name: security-reviewer
dispatches: [code-reviewer]          # YAML flow sequence of agent slugs
---
```

- Field name: `dispatches`. Value: a YAML **flow sequence** of agent slugs (`[a, b, c]`), or an empty sequence `[]` for an agent that dispatches nothing. Absent field is treated as `[]` **with a lint warning** (Phase-0 retrofit, D5.3, requires the field present on all shipped agents).
- Slugs match agent filenames without `.md`. Conditional/prose dispatch (e.g. `post-change-sweep → framework-validator`) MUST still be declared here — the prose is documentation, the declaration is the contract (#234).
- Parsing: a minimal front-matter reader (no full YAML dep — match `^dispatches:\s*\[(.*)\]` and split on commas, trimming). Living in `regions.py` as `parse_dispatches(front_matter: bytes) -> list[str]`. (Multi-line block-sequence form is **out of scope**; the flow `[...]` form is the required authoring convention — see rubric §"Authoring conventions".)

### 6.2 The gate — two sub-cases (spec §7, #233)

A standalone script `scripts/framework/completeness_gate.sh` (or `regions.py completeness ...`), with two modes:

**Sub-case A — HOS-internal hard-fail (ships in `hos-dev-pack`, runs during HOS dev):**
```
inputs:  all .claude/agents/*.md in the HOS repo
         consumer_agents.txt (the shipped set)
         a dev-only exemption list  →  scripts/framework/dev_only_agents.txt
                                       (framework-validator, doc-validator,
                                        spec-compliance-validator, framework-setup-validator —
                                        the agents consumer_agents.txt §"NOT listed" enumerates)
rule:    for every agent A in the HOS repo, for every slug D in dispatches(A):
            D must be in consumer_agents.txt  OR  in dev_only_agents.txt
fail:    HARD-FAIL (exit non-zero) — D is dispatched but not shipped and not dev-exempt.
                  (This is the v0.2.2 class caught at source.)
```
The **dev-only exemption list** is a new file `scripts/framework/dev_only_agents.txt`, authored to contain exactly the HOS-internal agents `consumer_agents.txt` documents as "NOT listed (deliberately)". Sub-case A reads it so that e.g. `post-change-sweep` dispatching `framework-validator` is *allowed* (framework-validator is dev-only), not a false hard-fail.

**Sub-case B — consumer-facing install-time warn (ships in the core consumer install):**
```
when:    at install/upgrade, after the agent set is written
inputs:  the target's installed agent set (.claude/agents/*.md)
         + the manifest (knows which agents HOS shipped)
rule:    for every installed agent A, for every D in dispatches(A):
            D must exist as a file in the target's .claude/agents/
            (HOS-shipped OR a consumer/base-team agent the manifest/disk knows about)
miss:    WARN (not hard-fail) — "agent A dispatches D, but D is not present in this repo;
                  install the pack that provides it, or add your own."
```
Sub-case B is **non-blocking by design** (spec §7: "warns (not hard-fail)") — a consumer upgrading into a missing-agent state gets a pre-flight signal, not a broken install. It runs in the installer after Phase B (§4.5), reading the just-written agent set.

---

## 7. Installer integration (where each piece hooks in `hos_install.sh`)

Ordered by the installer's existing flow. "MOVES OUT" = logic that leaves bash for `regions.py`.

### 7.1 Blank (first) install — write three regions

At the agent copy-loop (L471–484) and the manifest write (L811+):
- After copying + substituting an agent, on a **blank install** (no prior `.hos-manifest`) the template files already contain `CORE`/`PACK`/`PROJECT` markers (authored that way, Phase 0/2). The installer **validates** each (`regions.py validate`) — fail-closed halt on `E_*` (§2.4) — then writes the manifest rows via `regions.py manifest-rows` (§1.4).
- The chosen `PACK` is selected by which pack the consumer installs (single in-repo pack for the pilot, spec §10.2). Pack selection mechanism is **out of scope for this design** (Flag #1) — this design assumes the template agent files already carry the correct `PACK:<name>` region for the selected pack.
- An **empty `PROJECT` stub** is guaranteed: if a template agent lacks a `PROJECT` region, the installer appends an empty `<!-- HOS:PROJECT:START -->`/`END` pair (via `compose` with a synthesized empty PROJECT) so the consumer has a marked place to add content. Record its `base_sha` informationally.

### 7.2 Upgrade — three-way merge

Replaces a naïve overwrite for agent files. Hooks **between** the substitution block (ends L589) and the settings/scripts sections:
- Detect upgrade = prior `.hos-manifest` exists. Run the Phase-A/Phase-B flow (§4.5).
- The existing **whole-file** sync for `scripts/oversight/**` and runner scripts (L648–679) is **unchanged** — those are `WHOLE` rows, force-overwritten under `--force`/`--squash` exactly as today. Region logic applies to agent `.md` files **only**.

### 7.3 Migration hook

First-run-against-flat-files (§5) runs **before** the three-way merge, at the top of the agent-handling block (after copy, after substitution, before manifest write):
- Gate on git-clean (§5.1); honor `--dry-run`.
- `regions.py migrate` each flat target agent per the provenance gate (§5.2/5.3).
- After migration the files have markers; control falls through to the normal §7.2 path (which will now see `base == disk` for freshly-wrapped CORE and KEEP/REFRESH appropriately).

### 7.4 `enumerate_framework_files` change

Per §1.4: agent rows now come from `regions.py manifest-rows` (N region rows/agent); non-agent files keep whole-file rows with a `WHOLE` region column; the writer prepends `# hos-manifest-schema: 2`. The orphan-detection / `--prune` logic (L856–915) compares the **path column** (`cut -f1`) and is **unaffected** — it already only looks at paths, and a multi-row agent still has one distinct path. (One refinement: de-dup the path column for orphan comparison so an agent's 3 region rows count as one path — `cut -f1 | sort -u`, which the code already does at L863.)

### 7.5 Completeness gate hook

- Sub-case B (§6.2) runs near the end of the installer, after Phase B writes the agent set, before the SUMMARY block (L947). Non-blocking — emits warnings via `warn()`.
- Sub-case A is **not** in the consumer installer — it's a `hos-dev-pack` check run in HOS's own CI/pipeline.

### 7.6 `--squash` flag (new)

Add to the arg parser (alongside `--prune` at L77): `--squash) SQUASH=true; shift ;;`. Semantics: converts HARDSTOP→REFRESH for CORE/PACK (§4.3), never touches PROJECT (§4.4). Document in the `--help` header block (L2–38) and the usage comment.

### 7.7 `--pr`-default deferral (ADR D5.2/5.4 — NOT flipped here)

**Out of scope for this design.** Per ADR D5.2/5.4, the `--pr`-default flip + fallback-ban ship **after** the region model, coupled to machine-account install-PR identity (#152). This design leaves `PR_MODE="off"` default and the existing `--pr` opt-in branch logic (L388–416, L921–944) **unchanged**. The region merge runs *inside* whatever PR/in-place mode is active (Phase-B writes land on the PR branch when `--pr` is on — no special handling needed). A note SHOULD be added at L62 referencing this design as the prerequisite for the later flip.

---

## Flags for the architect (real gaps — not resolved here)

1. **Pack selection mechanism is unspecified.** §7.1 assumes the installer already knows which `PACK:<name>` region belongs in each agent for "the chosen pack," but neither the spec nor the ADR defines *how a consumer selects a pack* at install time (a `--pack django` flag? a `config.sh` key? inferred from a stack probe?). The whole region model presumes a selected pack; the selection UX/mechanism is undefined. **Blocks blank-install authoring.**

2. **Multi-pack composition under untested status (spec §10.1).** The format permits `PACK:a` + `PACK:b`, and `compose()` orders them alphabetically — but the spec says multi-pack is *untested, no support guarantee*. Design question: should the installer **refuse** (hard-error) more than one `PACK:` region in v0.3.0 to prevent shipping an unexercised path, or **permit-but-warn**? I designed for permit (alpha-ordered) per "must not break on it," but a deliberate single-pack guard may be safer for the pilot. **Architect to choose: guard or permit.**

3. **`substitute()` reuse for `incoming` (D1c) duplicates perl logic in Python.** §3.2's `incoming = region_sha(substitute(new_template_region_body, config))` needs the *same* substitution the installer's perl block applies. Either (a) `regions.py` re-implements the placeholders.manifest × config.sh substitution in Python (drift risk vs. the perl path), or (b) the installer substitutes the staged template *before* handing region bodies to `regions.py` (keeps one substitution engine, but means the "template region body" `regions.py` hashes is already substituted). I lean (b) but it changes who owns substitution. **Architect to confirm the substitution boundary.** *(Note: for CORE/PACK this is moot — no placeholders — so the gap only bites if a placeholder ever appears outside PROJECT, which D1a bans. A dev-pack lint asserting "no `{...}` token in CORE/PACK" would close it; see #4.)*

4. **No runtime enforcement that CORE/PACK are placeholder-free (D1a).** The sha model's soundness depends on the authoring rule "no placeholders in CORE/PACK," but nothing *checks* it. Recommend a `hos-dev-pack` lint (`regions.py lint-placeholders <file>` → fail if a `{NAME}` matching a placeholders.manifest key appears in a CORE/PACK region). Designed as a recommendation; **architect to confirm whether it's in v0.3.0 scope or a follow-up.**

5. **Lead-in / inter-region prose hashing boundary (§2.2/2.5).** I specified that prose between regions (e.g. the `## Project Extensions` heading) is *not* hashed and travels positionally with the following region. But if a consumer edits *that heading* (outside any region), it's invisible to the three-way merge and `compose()` would rewrite it to canonical. This is a minor data-loss vector for out-of-region prose. **Architect to confirm:** is all non-region prose HOS-canonical (rewritten freely), or must inter-region consumer prose be preserved? The spec's example implies the heading is HOS-authored boilerplate (safe to rewrite), but it isn't stated.

6. **RESOLVED (ADR §11a/D9).** A region in the manifest but absent from the new template is now rows 5/6 in §4.2: unedited → **DROP**, edited → **HARDSTOP** unless `--squash`/`--prune`. Detected by the manifest-side sweep in §4.5.
