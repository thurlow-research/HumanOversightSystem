# Technical Design — Consumer Pack Scaffolding and Brownfield Migration

**Document type:** Technical design (coder-ready)
**Status:** Draft — awaiting architect review
**Spec:** `docs/specs/SPEC-consumer-pack.md`
**Issue:** #275
**ADR cross-ref:** ADR-031 (pack mechanism / open seams); `SPEC-installer-upgrade.md` §2, §3
**Author:** technical-design
**Date:** 2026-06-16

---

## Self-flag (HOS authoring protocol)

**RISK:** MEDIUM — touches the installer (`hos_install.sh`) pre-merge baseline path and adds a
new classifier consumed by the region merge. The change is *additive* (new flags, new module,
new function) and does not alter the existing three-way merge or the `regions.py` compose/validate
core. The blast radius is the brownfield install path plus one new `regions.py`-adjacent module;
greenfield installs (`--first-install`, normal upgrades) are untouched when `--brownfield` is absent.

**CONFIDENCE:** HIGH on the classifier algorithm and JSON schema (fully specified by the spec);
MEDIUM on the single-pass-vs-re-run scaffolding decision (§3.6 open question O-1) and on the
heading-less-file fallback (§2.3, spec Implementation Note).

**BLAST RADIUS:** `hos_install.sh` (arg parse + brownfield branch), new
`scripts/oversight/validators/brownfield.py`, new installer helper functions, `dep-mapper.md`
PROJECT-region template text, `docs/UPGRADE-PR-REVIEW-CHECKLIST.md`. No change to the runtime
agent pipeline, the panel, or the oversight scripts.

**Change classification:** `additive`. No `structural` change (no contract removal, no change to
an existing region-merge invariant). No human gate required by the authoring protocol beyond the
standard architect review.

### Human Review Required

A reviewer must confirm two design choices before build:
1. **O-1 (§3.6):** scaffolding requires a documented installer re-run (`--pack <slug>`) rather than
   a single-pass scaffold+inject. Confirm this is acceptable vs. the extra complexity of a one-pass path.
2. **O-2 (§2.3):** heading-less flat files are treated as a single whole-file section compared against
   the whole CORE template body. Confirm the fallback is correct for the CPS corpus.

---

## Component map

| Component | Type | New / Changed | Owner section |
|---|---|---|---|
| `brownfield.py` | new Python module (`scripts/oversight/validators/`) | new | §2 |
| `brownfield_classify(agent_file, core_template_file)` | function in `brownfield.py` | new | §2.2 |
| `brownfield classify` CLI subcommand | thin CLI wrapper | new | §2.5 |
| `--brownfield` flag | `hos_install.sh` arg parse | new | §1.1 |
| `--scaffold-pack <slug>` flag | `hos_install.sh` arg parse | new | §3.1 |
| `_brownfield_detect()` | installer helper | new | §1.2 |
| `_brownfield_migrate()` | installer helper (orchestrates §2 → §1.5 baseline) | new | §1.5 |
| `_brownfield_scaffold_pack()` | installer helper | new | §3.2 |
| `_resolve_pack_dir(name)` | installer helper (consumer-local-first) | new | §3.5 |
| Synthetic `.hos-manifest` writer | installer helper | new | §1.4 |
| `dep-mapper.md` PROJECT template text | agent template body | changed | §4 |
| `docs/UPGRADE-PR-REVIEW-CHECKLIST.md` | doc | changed | §4.4 |

Boundary: `brownfield.py` is a **pure classifier + report writer**. It never writes agent files,
never writes `.hos-manifest`, and never mutates `packs/`. All state changes are made by
`hos_install.sh`, which consumes `brownfield.py`'s JSON. This keeps the classifier independently
testable and keeps every disk-mutating decision in the installer (consistent with how `regions.py`
is a pure planner and the installer is the sole writer).

---

## §1 — Brownfield migration flag

### 1.1 Flag parsing — exact location and contract

Add two defaults next to the existing `SQUASH`/`NO_PACK` defaults (`hos_install.sh` ~L70–72):

```
BROWNFIELD=false      # --brownfield: classify flat agent files, synth a baseline, then merge (#275)
SCAFFOLD_PACK=""      # --scaffold-pack <slug>: extract project_custom into a consumer pack (#275)
```

Add two cases to the `while [[ $# -gt 0 ]]` arg loop (after the `--squash` case, ~L86):

```
--brownfield)     BROWNFIELD=true; shift ;;
--scaffold-pack)  SCAFFOLD_PACK="${2:?--scaffold-pack needs a slug, e.g. --scaffold-pack condoparkshare}"; shift 2 ;;
--scaffold-pack=*) SCAFFOLD_PACK="${1#*=}"; shift ;;
```

**Mutual-exclusion and precondition checks** are placed immediately after the `TARGET_REPO`
resolution (~L97) and after the existing `--no-pack`/`--pack` mutual-exclusion block (~L100), so
they fail before any work:

- **REQ-B-01 — `--brownfield` ⊥ `--squash`:** if `$BROWNFIELD && $SQUASH`, print the exact spec
  message and `exit 2`:
  ```
  ERROR: --brownfield and --squash are mutually exclusive.
    --brownfield performs its own safe classification before merging.
    --squash overwrites all CORE/PACK regions without classification.
    Use --brownfield for pre-region-model repos.
  ```
- **REQ-CS-07 — `--scaffold-pack` requires `--brownfield`:** if `-n "$SCAFFOLD_PACK"` and
  `! $BROWNFIELD`, print and `exit 2`:
  ```
  ERROR: --scaffold-pack requires --brownfield.
    Consumer pack scaffolding is part of the brownfield migration flow.
  ```

Exit code: `2` for both (usage error; distinct from the `1` used for unknown options and the `4`
the region merge uses for a drift hard-stop).

Add both flags to the `--help` header block (the `sed -n '2,43p'` range at L90 must be widened to
include the new usage lines, or the new lines must be inserted within the existing range — see §5
build note B-3).

### 1.2 Brownfield-state detection — `_brownfield_detect()`

A helper that classifies the target's `.claude/agents/` directory state. Returns via stdout one of
three tokens and a non-zero/zero exit; the installer reads the token.

**Algorithm (contract):**
1. `_has_manifest`: `[[ -f "$TARGET_REPO/.hos-manifest" ]]`.
2. `_has_agents`: at least one file matching `$TARGET_REPO/.claude/agents/*.md` exists.
3. `_any_flat`: at least one `*.md` agent file contains **no** `<!-- HOS:` marker line
   (`grep -L '<!-- HOS:' "$TARGET_REPO/.claude/agents/"*.md` is non-empty).

**Brownfield state** is defined (per spec §1 Background + REQ-B-02/B-03) as:
`! _has_manifest && _has_agents && _any_flat` — i.e. agent files present, no recorded baseline,
and at least one flat file.

Detection result drives the branch:

| State | `--brownfield` absent | `--brownfield` present |
|---|---|---|
| Brownfield (above) | **hard-stop** (current behavior, unchanged) — see §1.3 | run `_brownfield_migrate()` (§1.5) before the merge |
| Not brownfield (manifest present, or all files marked) | normal three-way merge | `--brownfield` is a **no-op WARN** (§1.6) |

`_brownfield_detect()` is called once, early, immediately before the existing pack-resolution block
(~L599) so its result is known before the agent-install phase. It must run **after**
`TARGET_REPO` is resolved and **before** any staging.

### 1.3 Hard-stop message when `--brownfield` is NOT provided

The current hard-stop originates in the region merge: a flat file with no recorded base-sha produces
`CORE drifted (base_sha=(absent))` and the decide-all-then-act gate refuses the whole upgrade
(`exit 4`). This behavior is **unchanged**. The technical-design requirement here is only to make the
hard-stop *discoverable* by naming the new escape hatch. When `_brownfield_detect()` reports the
brownfield state and `--brownfield` is absent, the installer emits a pre-flight hint **before**
reaching the merge (so the user is not left guessing):

```
ERROR: This looks like a pre-region-model (brownfield) repo:
  no .hos-manifest, and flat agent files in .claude/agents/.
  The standard installer cannot three-way-merge without a recorded baseline.
  Re-run with --brownfield to classify your flat files and migrate safely
  (or --squash to overwrite all CORE/PACK regions — destructive, see --help).
```

Then `exit 4` (the existing drift hard-stop code), without staging or writing anything. This
replaces the bare `CORE drifted (base_sha=(absent))` surface with an actionable message for the
brownfield case; the underlying merge-level hard-stop is the same code path and stays as the
backstop for any flat file that slips past detection.

### 1.4 Synthetic baseline manifest — REQ-B-05

`_brownfield_migrate()` (§1.5) constructs a synthetic `.hos-manifest` so the standard merge has a
valid baseline. Per-flat-file:

- For each section classified `STOCK_CORE`: record it in the manifest as a CORE region whose
  `base_sha` is derived from **the current HOS CORE template** for that agent (so the three-way
  merge sees it as CORE-needs-refresh and resolves by taking HOS's version). The base-sha is
  produced by the existing `regions.py base-shas`/`region-sha` machinery against the staged HOS
  template — **not** against the consumer's flat content.
- For each section classified `PROJECT_CUSTOMIZATION` (including `[mixed]`): the installer writes
  the section text into a `<!-- HOS:PROJECT:START -->…<!-- HOS:PROJECT:END -->` region **on the
  disk file** before the merge runs (so the merge carries PROJECT through untouched per its
  consumer-owned-never-overwritten rule).

Mechanically, the cleanest construction (reusing existing tools) is:
1. Stage the HOS CORE template for the agent (substituted), exactly as the normal install does.
2. Build the agent's disk image by composing: HOS CORE region (from the staged template) + a
   PROJECT region whose body is the concatenated `project_custom` section text from
   `brownfield.py`'s JSON, in original file order. Use `regions.py migrate --ships yes` on a
   synthesized intermediate, **or** directly emit a CORE+PROJECT-marked file — see build note B-1
   for the chosen mechanism (the recommended path is to write the disk file with CORE + PROJECT
   markers and let `regions.py plan` treat CORE as drift and PROJECT as carry-through).
3. Run `regions.py assemble-manifest` over the resulting disk image to emit the manifest rows for
   that agent.

The synthetic `.hos-manifest` is written with the spec-mandated top comment line:
```
# Synthetic baseline generated by --brownfield on <ISO-8601-date>. Manual review recommended.
```
`<ISO-8601-date>` is `date -u +%FT%TZ`. The manifest must be parseable by `regions.py` (AC-B-05);
the assemble step guarantees this because it is the canonical manifest writer.

**Boundary:** the synthetic manifest is written **before** the existing three-way merge runs and is
the only file the brownfield path adds ahead of the merge. After it is written, REQ-B-06 holds: the
standard merge runs unchanged.

### 1.5 `_brownfield_migrate()` — orchestration contract

Signature (no args; reads `TARGET_REPO`, `HOS_SOURCE`, `DRY_RUN`, `SCAFFOLD_PACK`, the resolved
pack list). Steps:

1. Enumerate `$TARGET_REPO/.claude/agents/*.md`. Partition into **already-marked** (contains
   `<!-- HOS:`) and **flat** (does not). Already-marked files are **not** sent to the classifier
   (REQ-B-04 / AC-B-08) — they flow into the standard merge.
2. For each flat file, resolve the matching CORE template:
   - slug = basename without `.md`.
   - if slug is in `scripts/framework/consumer_agents.txt` → CORE template is
     `$HOS_SOURCE/.claude/agents/<slug>.md` (the shipped template).
   - else (REQ-D-08) → no CORE template; the whole file is `project_custom`.
3. Call `brownfield.py classify <flat_file> <core_template_or_empty>` → per-agent JSON to
   `$TARGET_REPO/.hos-brownfield/<slug>.json` and a human-readable report block to stdout.
4. After all flat files are classified, count agents with ≥1 `project_custom` section → drives the
   §3 scaffold offer.
5. If scaffolding is **not** taken: write the synthetic baseline (§1.4) for each flat file, then
   return so the standard merge proceeds.
6. If scaffolding **is** taken (§3): extract `project_custom` content into `packs/<slug>/`, clear
   the agent PROJECT regions to stubs in the synthetic baseline, then return.
7. Emit the REQ-B-07 summary block.

`.hos-brownfield/` is a working directory the installer writes during migration; the per-agent JSON
under it is the machine-readable handoff between `brownfield.py` and the installer. It is added to
`.gitignore` by the installer's gitignore-management step (build note B-5) — it is migration scratch,
not committed state. The human-readable classification report (REQ-D-06) is written to
`.claudetmp/brownfield-<YYYYMMDD-HHmmss>-report.txt` (a separate artifact, retained for review).

> Note: the spec body uses `.hos-brownfield/<agent>.json` (machine-readable) and
> `.claudetmp/brownfield-<ts>-report.txt` (human-readable). Both are produced. The task brief's
> phrase "JSON per-agent to `.hos-brownfield/<agent>.json`" and the spec REQ-D-07 JSON schema are
> the same artifact.

### 1.6 `--brownfield` on a non-brownfield repo (REQ — derived)

If `--brownfield` is passed but `_brownfield_detect()` does not report the brownfield state (e.g. a
manifest already exists, or every agent file is already marked), the installer emits:
```
[brownfield] --brownfield passed but this repo is not brownfield
  (.hos-manifest present or all agent files already marked) — proceeding with the standard merge.
```
and continues with the normal path. It does **not** error. This keeps `--brownfield` idempotent: a
second run after a successful migration is a clean no-op.

### 1.7 `--dry-run` compatibility — REQ-B-08

Under `--brownfield --dry-run`:
- `brownfield.py classify` runs and writes the `.claudetmp/brownfield-<ts>-report.txt` report and
  the `.hos-brownfield/<slug>.json` files (read-only outputs, not state changes — AC-B-07 permits
  these in dry-run).
- The synthetic baseline is **shown** (`dry_run "Would write .hos-manifest with N rows…"`) but
  **not written**.
- No agent file is modified; no `packs/<slug>/` is created.

The installer's existing `dry_run()` helper gates every write in `_brownfield_migrate()`.

### 1.8 Install-log summary — REQ-B-07

After migration, emit (counts from the partition in §1.5 step 1 and the classification JSON):
```
[brownfield] Migration complete.
  Agents processed:          <N>
  Already-marked (skipped):  <N>
  Flat files classified:     <N>
  PROJECT regions preserved: <N>
  Stock CORE overwritten:    <N>
  Classification report:     .claudetmp/brownfield-<YYYYMMDD-HHmmss>-report.txt
```
- *Agents processed* = total `*.md` in `.claude/agents/`.
- *Already-marked (skipped)* = count not sent to the classifier.
- *Flat files classified* = count sent to the classifier.
- *PROJECT regions preserved* = flat files with ≥1 `project_custom` section.
- *Stock CORE overwritten* = flat files with ≥1 `stock_core` section.

---

## §2 — Duplicate-logic check (`brownfield.py`)

### 2.1 Module placement and interface

New module: `scripts/oversight/validators/brownfield.py`. It lives beside `regions.py` because it is
part of the same install-time toolchain and shares the "pure function + thin CLI wrapper" convention.
It must run venv-less on Python 3.10+ (stdlib only: `re`, `json`, `sys`, `argparse`, `dataclasses`,
`pathlib`, `datetime`) — no third-party deps, consistent with `regions.py`.

### 2.2 `brownfield_classify(agent_file, core_template_file) -> dict`

**Inputs:**
- `agent_file: Path` — the consumer's flat agent file.
- `core_template_file: Path | None` — the HOS CORE template for the same slug, or `None` when HOS
  ships no template for this slug (REQ-D-08).

**Output (dict):** the function returns a structured result. The task brief asks for
`{"stock_core": [...], "project_custom": [...], "mixed": [...], "similarity": float}`; the spec
REQ-D-07 asks for a per-section JSON. These are reconciled as follows — the function returns a
**superset** that satisfies both:

```python
{
  "agent": "<agent-filename>",          # basename, e.g. "code-reviewer.md"
  "core_template": True | False,        # False when core_template_file is None (REQ-D-08)
  "similarity": <float>,                # file-level: mean section similarity, 0.0 when no match
  "sections": [                         # REQ-D-07 per-section detail (ordered as in the flat file)
    {
      "heading": "<heading text>",      # stripped of leading # and whitespace; "" for pre-heading/heading-less
      "classification": "STOCK_CORE" | "PROJECT_CUSTOMIZATION",
      "mixed": True | False,            # True iff 0.45 <= similarity < 0.90 (REQ-D-05)
      "similarity": <float>,            # this section's score, 0.00–1.00
      "lines": ["<raw section line>", ...]   # the section body lines, for the installer to extract
    }
  ],
  # Convenience buckets the installer reads to build PROJECT/pack bodies (task-brief shape):
  "stock_core":     ["<heading>", ...],   # headings classified STOCK_CORE
  "project_custom": ["<heading>", ...],   # headings classified PROJECT_CUSTOMIZATION, not mixed
  "mixed":          ["<heading>", ...]    # headings classified PROJECT_CUSTOMIZATION AND mixed
}
```

The `lines` per section are what the installer concatenates (in section order) to form the PROJECT
region body or the pack body file. `stock_core`/`project_custom`/`mixed` are heading lists for the
report and the threshold count; `sections` is the load-bearing structure.

### 2.3 Algorithm — sectioning, similarity, classification

**Front-matter exclusion (REQ-D-09).** Before sectioning, strip the YAML front-matter: if the file
begins with a `---` line, drop everything up to and including the next `---` line. Front-matter is
never classified, never compared, never preserved (always sourced from HOS).

**Sectioning (REQ-D-01).** Split the remaining body into sections. A section begins at a line
matching `^#{1,6}\s` (a Markdown heading) **or** at the start of the body, and runs to the line
before the next heading (or EOF). Each section's identity is its heading text: the heading line
stripped of leading `#` characters and surrounding whitespace, lowercased, for matching purposes.
The display heading retains original case.

> Spec uses "a line starting with `#`". HOS agent files use ATX headings (`## `, `### `). Match
> `^#{1,6}[ \t]` so a literal `#comment`-style line without a following space is not mistaken for a
> heading. (Build note B-2: confirm no agent CORE body uses `#`-prefixed non-heading lines that
> would mis-section; the CORE bodies are all `## `/`### ` headed.)

**Heading-less fallback (O-2, spec Implementation Note).** If the body contains no heading, treat
the entire body as a single section with `heading=""` and compare it against the **entire CORE
template body** (also stripped of front-matter and treated as one block). This yields one
classification for the whole file.

**Section matching (REQ-D-01).** Match a consumer section to a CORE-template section by
case-insensitive, `#`/whitespace-stripped heading text. A consumer section whose heading has **no**
match in the CORE template is classified `PROJECT_CUSTOMIZATION` by default with `similarity = 0.0`
and `mixed = False` (it is clearly custom — a heading HOS does not ship).

**Similarity (REQ-D-02).** For a matched pair, compute the set-overlap ratio over content-stripped
lines:
```
consumer_lines = { line.strip() for line in consumer_section if line.strip() }
core_lines     = { line.strip() for line in core_section if line.strip() }
common         = len(consumer_lines & core_lines)
similarity     = common / max(len(consumer_lines), len(core_lines))   # 0.0 if both empty
```
This is **set intersection over union-max** (the spec gives `common / max(len_a, len_b)`; the task
brief mentions `intersection / union` — these differ. **The spec REQ-D-02 governs**: denominator is
`max(len(consumer), len(core))`, not `len(union)`. See O-3 in §6 — flag for architect to confirm the
spec's denominator is intended, since `max` and `union` diverge when the two sets have different
sizes but high overlap. Implement the **spec's `max` denominator**; note the divergence.)

Empty-line entries are dropped before set construction (so blank-line count never affects the
ratio). Comparison is exact string match after `.strip()` — no normalization beyond whitespace
trim, no semantic comparison (REQ-D-02 explicitly excludes NLP/embeddings).

**Classification thresholds (REQ-D-03/04/05).**

| Similarity `s` | Classification | `mixed` flag |
|---|---|---|
| `s >= 0.90` | `STOCK_CORE` | `False` |
| `0.45 <= s < 0.90` | `PROJECT_CUSTOMIZATION` | `True` (`[mixed]`) |
| `s < 0.45` | `PROJECT_CUSTOMIZATION` | `False` |
| no CORE match | `PROJECT_CUSTOMIZATION` | `False` |

> Reconciliation note: the task brief states "≥0.90 → stock_core; 0.45–0.89 → mixed;
> <0.45 → project_custom". The spec (REQ-D-04/05) is more precise: everything `< 0.90` is
> `PROJECT_CUSTOMIZATION`; the `[mixed]` *tag* is a sub-label on the `[0.45, 0.90)` band, **not** a
> third classification. The merge consequence is identical for `mixed` and plain
> `project_custom` (both go to PROJECT / pack — never silently dropped, REQ-D-05). The design uses
> the spec's two-classification + mixed-tag model: `classification ∈ {STOCK_CORE,
> PROJECT_CUSTOMIZATION}`, `mixed ∈ {true,false}`. This is the conservative, spec-aligned model.

**No-CORE-template case (REQ-D-08).** When `core_template_file is None`, every section is
`PROJECT_CUSTOMIZATION`, `mixed = False`, `similarity = 0.0`, `core_template = False`. The report
adds a `no CORE template` note (AC-D-07).

### 2.4 Human-readable report — REQ-D-06

`brownfield.py` emits, per processed file, the exact spec format to stdout (the installer captures
it into the aggregate `.claudetmp/brownfield-<ts>-report.txt`):
```
Agent: <agent-filename>
  Section: "<heading text>"
    CORE template match: <yes|no>
    Similarity: <0.00–1.00>
    Classification: STOCK_CORE | PROJECT_CUSTOMIZATION | PROJECT_CUSTOMIZATION [mixed]
  ...
  Summary: <N> sections → <M> stock, <P> customization (<Q> mixed)
```
Where the `Classification` column renders `PROJECT_CUSTOMIZATION [mixed]` when
`classification == PROJECT_CUSTOMIZATION and mixed`. `Similarity` is formatted to two decimals.

### 2.5 CLI subcommand — `brownfield.py classify`

Thin wrapper mirroring `regions.py`'s subcommand convention:
```
python3 brownfield.py classify <agent-file> [<core-template-file>] [--json-out <path>]
```
- Positional `agent-file` (required), positional `core-template-file` (optional; absent → REQ-D-08
  no-template path).
- `--json-out <path>`: write the REQ-D-07 machine-readable JSON to `<path>` (the installer passes
  `.hos-brownfield/<slug>.json`). When absent, JSON is printed to stdout after the human-readable
  block on stderr — but the installer always passes `--json-out` so the two streams never mix.
- Human-readable report (§2.4) always goes to stdout; machine JSON goes to `--json-out` (or, if
  absent, stdout too with a separator — installer path always uses the file).
- Exit codes: `0` success; `2` usage error (missing agent file); the classifier never fails on
  content (it classifies conservatively).

### 2.6 How the installer uses the classification output (REQ-B-05, REQ-CS-04)

The installer reads each `.hos-brownfield/<slug>.json` and:
- **PROJECT region body** = concatenation of `lines` for every section where
  `classification == "PROJECT_CUSTOMIZATION"` (mixed or not), in `sections` order, joined with `\n`,
  with one blank line between sections. This becomes the PROJECT region the synthetic baseline writes
  (§1.4) — or, under scaffolding, the pack body file (§3.4).
- **STOCK_CORE sections** are discarded from the disk file (the merge re-supplies them from HOS CORE).
- The classifier's `core_template: false` flag tells the installer this slug has no HOS CORE; the
  whole file goes to PROJECT (or pack), and the synthetic-manifest CORE row is omitted for it.

---

## §3 — Consumer pack scaffolding

### 3.1 Trigger and offer — REQ-CS-01

After classification (§1.5 step 4), compute `N_custom` = number of flat agents with ≥1
`PROJECT_CUSTOMIZATION` section. Scaffolding is offered iff `N_custom >= 3`.

- **Non-interactive with `--scaffold-pack <slug>`:** proceed directly with that slug (no prompt).
- **Interactive (tty) and no `--scaffold-pack`:** prompt with the **spec's** exact text
  (REQ-CS-01):
  ```
  [brownfield] Found PROJECT customizations in <N> agents.
    These could be extracted into a consumer pack for cleaner versioning.
    Scaffold a consumer pack? (recommended for N >= 3) [y/N]:
  ```
  Default `N`. On `y`/`Y`, prompt for the slug: `Pack slug [a-z][a-z0-9-]*: ` and validate.

  > Reconciliation: the task brief gives prompt text
  > `"Scaffold a consumer pack from your PROJECT customizations? [y/N]: "`. The spec REQ-CS-01 gives
  > the three-line block above. **The spec text governs** (it carries the `N`-count context the
  > brief's one-liner omits). Coder: use the spec's three-line prompt.
- **Non-interactive without `--scaffold-pack`** (CI / `--non-interactive` / stdin not a tty): skip
  scaffolding silently; migration proceeds with PROJECT regions only (REQ-CS-01).

### 3.2 `_brownfield_scaffold_pack(slug)` — contract

**Slug validation (REQ-CS-02):** must match `^[a-z][a-z0-9-]*$`. Reject (exit 2) any slug that
collides with a HOS built-in pack name — i.e. any directory present in `$HOS_SOURCE/packs/`
(currently `django`, `testpack`). Error (AC-CS-09):
```
ERROR: '<slug>' conflicts with a HOS built-in pack name. Choose a different slug.
```

**Creates** in the target repo:
```
packs/<slug>/
  pack.toml
  <agent>.md   (one per agent with non-empty project_custom content)
```

### 3.3 `pack.toml` generation — REQ-CS-03

Write the minimum-viable `pack.toml` with the spec's required fields and the `requires` guidance
comment:
```toml
name = "<slug>"
description = "<consumer-name> — project-specific HOS pack."
version = "0.1.0"
requires = []

# If this pack assumes another pack (e.g. django), add it to requires:
# requires = ["django"]
```
`<consumer-name>` is derived from the target repo's basename (`basename "$TARGET_REPO"`); the human
edits it. `supported_agents` is **not** written — the spec REQ-CS-03 field set is
`name`/`description`/`version`/`requires`.

> Reconciliation: the task brief's minimum `pack.toml` shows
> `supported_agents = ["<list>"]`. The spec REQ-CS-03 specifies `name`/`description`/`version`/
> `requires` and existing `packs/django/pack.toml` uses exactly those four fields with **no**
> `supported_agents` key (the supported-agent set is implicit from which `<agent>.md` body files
> exist in the pack dir). **The spec + existing convention govern: do not emit
> `supported_agents`.** Flag O-4 in §6 records this divergence for the architect; if the architect
> wants an explicit `supported_agents` list it is an additive field, but it is not in the existing
> pack format and `regions.py inject-pack` does not read it.

### 3.4 Agent body files — REQ-CS-04

For each agent with non-empty `project_custom` content (per §2.6), write
`packs/<slug>/<agent>.md` containing **only** that content — the concatenated `lines` of the
`PROJECT_CUSTOMIZATION` sections in original order. The body file MUST NOT contain:
- region markers (`<!-- HOS:… -->`) — body files are marker-free; `regions.py inject-pack` wraps
  them.
- front-matter (already excluded by the classifier, §2.3).
- `STOCK_CORE` content.

If an agent's `project_custom` content is empty after exclusions, **no** body file is created and
the agent does not appear in `packs/<slug>/` (REQ-CS-04).

### 3.5 Consumer-local pack resolution — `_resolve_pack_dir(name)` — REQ-CS-06

A new installer helper that resolves a pack name to a directory, consumer-local-first:
```
_resolve_pack_dir() {  # $1=pack-name → prints abs dir, sets resolution source
  local _n="$1"
  if [[ -d "$TARGET_REPO/packs/$_n" ]]; then
    info "[pack] Resolved $_n from consumer-local packs/ (not HOS-shipped)"
    printf '%s' "$TARGET_REPO/packs/$_n"; return 0
  elif [[ -d "$HOS_SOURCE/packs/$_n" ]]; then
    info "[pack] Resolved $_n from HOS source (HOS-shipped)"
    printf '%s' "$HOS_SOURCE/packs/$_n"; return 0
  fi
  return 1
}
```

This replaces the **direct** `$HOS_SOURCE/packs/$_p` references in the existing pack-validation and
pack-injection blocks (`hos_install.sh` ~L669, L677–678, and the inject-pack body-file path inside
the agent-install phase). The precedence is: consumer-local `packs/<name>/` first, HOS-shipped
second. The existing unknown-pack hard error (R3, ~L669) becomes: *unknown if neither location has
it.* The resolution-source log lines (REQ-CS-06) are emitted from `_resolve_pack_dir`.

**Boundary:** consumer-local resolution applies to **every** `--pack` resolution, not only
scaffolded packs — this is what lets a scaffolded `--pack <slug>` re-run work immediately
(AC-CS-06/07). It does not change which agents a pack injects into; `regions.py inject-pack` still
reads `packs/<name>/<agent>.md` from whichever directory `_resolve_pack_dir` returned.

> Build note B-4: the multi-pack body-file injection loop currently builds
> `$HOS_SOURCE/packs/$_pk/${agent}.md`. Change it to
> `$(_resolve_pack_dir "$_pk")/${agent}.md`. Capture `_resolve_pack_dir`'s stdout into a var; do not
> call it twice (it logs each call).

### 3.6 Scaffold-then-inject is a two-run flow — REQ-CS-05 (Open question O-1)

When scaffolding is taken, the agent files receive **empty PROJECT stubs**
(`<!-- HOS:PROJECT:START -->\n<!-- HOS:PROJECT:END -->`), not the classified content — that content
now lives in `packs/<slug>/`. The installer does **not** inject the just-scaffolded pack in the same
run. It emits the REQ-CS-05 instruction:
```
[brownfield] Consumer pack scaffolded at packs/<slug>/.
  To apply it, re-run the installer with --pack <slug> (and any other packs).
  Example: hos_install.sh --pack django --pack <slug> [DIR]
```

**O-1 (for architect):** The spec Implementation Note asks whether a single-run scaffold+inject is
feasible. This design specifies the **two-run** flow (scaffold this run; human re-runs `--pack
<slug>`) because:
1. The synthetic-baseline + merge has already run this pass against PROJECT-stub agents; injecting a
   brand-new `PACK:<slug>` region in the same pass would require re-staging and re-merging every
   agent after the manifest is written — a second merge cycle inside one install.
2. The two-run flow keeps the scaffold reviewable (REQ-CS-08: not auto-committed) before it is
   injected — the human inspects `packs/<slug>/` and edits `requires`/`description` before applying.

Recommend the two-run flow. Flag for the architect to ratify; if a single-pass path is mandated it
is a larger structural change to the agent-install phase and should be its own design iteration.

### 3.7 Not auto-committed — REQ-CS-08

The installer writes `packs/<slug>/` but never runs `git add`/`stage`/`commit` on it. The
post-scaffold message (§3.6) carries the review-and-commit reminder. Under `--dry-run`, the
`packs/<slug>/` tree is described (`dry_run "Would scaffold packs/<slug>/ with N body file(s)"`) but
not written.

---

## §4 — dep-mapper depth convention

### 4.1 Where the text goes

The convention is **consumer-configurable**, so it lands in the `dep-mapper.md` **PROJECT** region
template text — not CORE. Per the layering rule, CORE/PACK are HOS-owned; this is guidance the
consumer can edit. The text is a comment-style block placed inside the PROJECT region body of the
shipped `dep-mapper.md` so it appears in a fresh install and survives upgrades (PROJECT is never
overwritten).

> Constraint: this edit is to the **PROJECT region body** of `dep-mapper.md`. Per the HOS rule the
> technical-design agent does not write agent CORE/PACK bodies; the PROJECT region is consumer-owned
> template text and the design specifies its *content*, which the coder places. Confirm with the
> architect that supplying default PROJECT-region scaffolding text is in-bounds for this change
> (it is template seed text, not agent logic).

### 4.2 PROJECT-region template text (content the coder inserts)

The PROJECT region of `dep-mapper.md` should seed the three-layer depth model and a placeholder:
```
<!-- dep-mapper depth model (REQ-DM-01..03, #275):
     Three layers of blast-radius tracing depth, innermost wins:
       1. base pack  (e.g. PACK:django)        — generic, stack-aware, project-agnostic
                                                  ORM/signal/cache tracing for any project on
                                                  this stack. Lives in packs/django/dep-mapper.md.
       2. consumer pack (e.g. PACK:<slug>)      — project-specific tracing: custom model
                                                  relationships, non-standard signal patterns,
                                                  project-specific cache keys. Lives in
                                                  packs/<slug>/dep-mapper.md. Injected AFTER the
                                                  base pack; extends/overrides it for the patterns
                                                  it names. No automated conflict resolution —
                                                  the consumer-pack author keeps the layers coherent.
       3. PROJECT region (here)                 — one-off tracing rules until a consumer pack is
                                                  scaffolded. When --scaffold-pack runs, this
                                                  content is extracted into packs/<slug>/dep-mapper.md
                                                  (REQ-DM-03) and this region becomes the empty stub.

     Add consumer-specific tracing rules below.
-->

<!-- PLACEHOLDER: project-specific dep-mapper tracing rules go here.
     e.g. "CPS signal dispatchers: trace cps.signals.* receivers to their
     emitting models; treat cps.cache.key_for(obj) as a blast-radius edge." -->
```

This is comment-form so it never executes as instruction text but documents the layering and gives
the consumer a clear insertion point. (REQ-DM-03: this same content is what `--scaffold-pack`
extracts into `packs/<slug>/dep-mapper.md` via the standard §3.4 body-file path.)

### 4.3 Pack-injection ordering for dep-mapper — REQ-DM-02

No new code: `regions.py compose` already alpha-orders PACK regions by name. When both
`packs/django/dep-mapper.md` and `packs/<slug>/dep-mapper.md` exist and both packs are passed,
`inject-pack` is invoked once per pack and compose emits `PACK:condoparkshare` and `PACK:django`
regions (alpha order ⇒ `condoparkshare` before `django` — see O-5: the spec REQ-DM-02 says "consumer
pack's region is injected **after** the base pack's", but compose's alpha order puts `condoparkshare`
**before** `django`). **Flag O-5 for the architect:** the spec's "after the base pack" ordering
conflicts with `regions.py` compose's deterministic alpha ordering. Either (a) the spec's intent is
satisfied because both regions are present and the agent reads all of them (AC-DM-01 only asserts
both regions exist, not their order), or (b) compose needs a non-alpha ordering hook for dep-mapper.
Recommend (a): AC-DM-01 asserts presence, not order; leave compose's alpha order unchanged and treat
"innermost wins" as a documentation/authoring convention, not a compose-ordering guarantee. The
`--force`/brownfield dep-mapper behavior (REQ-DM-04) is unchanged by this design.

### 4.4 `docs/UPGRADE-PR-REVIEW-CHECKLIST.md` — REQ-DM-05

Add a **"Consumer packs"** section covering the three REQ-DM-05 points:
1. dep-mapper depth resolution (PROJECT region until a consumer pack is scaffolded; pack body file
   after).
2. How to verify a consumer pack was resolved from `consumer-local packs/` (look for the
   `[pack] Resolved <name> from consumer-local packs/` log line, §3.5) and not HOS source.
3. How to confirm both a base pack and a consumer pack inject into dep-mapper (both
   `<!-- HOS:PACK:django:START -->` and `<!-- HOS:PACK:<slug>:START -->` present in the installed
   `dep-mapper.md`, per AC-DM-01).

---

## §5 — Build notes (ordering and gotchas for the coder)

- **B-1 (synthetic baseline mechanism):** prefer composing the disk image as a CORE+PROJECT marked
  file and letting `regions.py plan`/`assemble-manifest` produce the manifest, over hand-rolling
  manifest rows. The CORE base-sha must come from the **HOS** staged template (so the merge refreshes
  CORE), while the PROJECT body is the consumer content. Do not derive any CORE base-sha from the
  consumer flat file.
- **B-2 (sectioning regex):** match `^#{1,6}[ \t]` for headings. Verify against all shipped CORE
  bodies that no non-heading line starts with `#`+space.
- **B-3 (`--help`):** widen/insert the `--brownfield`, `--scaffold-pack` usage lines into the help
  block range so `--help` documents them.
- **B-4 (`_resolve_pack_dir`):** route **all** existing `$HOS_SOURCE/packs/$_p` resolutions through
  it (validation block + inject body-file path). Call once per pack; capture stdout.
- **B-5 (`.gitignore`):** add `.hos-brownfield/` to the installer's gitignore-management step (scratch,
  not committed). `packs/<slug>/` is **not** gitignored (the human commits it — REQ-CS-08).
- **B-6 (dry-run gating):** every disk write in `_brownfield_migrate`/`_brownfield_scaffold_pack`
  goes through the existing `dry_run()` helper; classification + report writes are allowed in
  dry-run (read-only outputs).

---

## §6 — Open questions for the architect

| ID | Question | Recommendation |
|---|---|---|
| O-1 | Two-run scaffold+inject vs. single-pass? (§3.6) | Two-run (scaffold this run; human re-runs `--pack <slug>`). |
| O-2 | Heading-less flat file = one whole-file section vs. CORE whole body? (§2.3) | Yes — single section vs. whole CORE body. |
| O-3 | Similarity denominator: spec says `max(len_a, len_b)`; task brief says `len(union)`. They diverge. (§2.3) | Implement the **spec's `max`** denominator (REQ-D-02 governs); confirm intent. |
| O-4 | `pack.toml`: emit `supported_agents` (task brief) or omit (spec/existing convention)? (§3.3) | Omit — match existing `packs/django/pack.toml` (4 fields, no `supported_agents`). |
| O-5 | dep-mapper region order: spec "consumer after base" vs. compose alpha order (`condoparkshare` < `django`). (§4.3) | Treat AC-DM-01 (presence) as the contract; leave compose alpha order; ordering is a doc convention. |
| O-6 | Is seeding `dep-mapper.md` PROJECT-region template text in-bounds for technical-design? (§4.1) | Believe yes (seed text, not agent logic); confirm. |

**Status:** DRAFT — requesting architect review. Not handed to the coder. Round 1 of 5.
