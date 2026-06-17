# TECHNICAL DESIGN — SPEC-121: Structural-Override Modification Detection

**Issue:** #121
**Spec:** `docs/specs/SPEC-121-structural-override-modifications.md`
**Architect ruling:** GO (bindings 1–6, recorded below)
**Status:** For architect review → coder
**Author:** technical-design | 2026-06-17

---

## 0. Scope of this design

This document is the implementation contract for the two artifacts SPEC-121 changes:

1. `scripts/oversight/change_classifier.py` — extend `collect_diff` to a 3-tuple, add
   `detect_structural_modifications()`, add the `--modifications-only` CLI flag.
2. `.claude/agents/oversight-evaluator.md` — add Phase-1 compliance **condition 14** after
   condition 11 (SPEC-94 structural-override block).

The contract / event-catalog edits named in the spec's Artifact-Changes table are **not** in
this build slice (the architect bindings enumerate only the two artifacts above). They remain
the spec's responsibility and are out of scope here.

It describes *what the code must do*, not the code itself.

---

## 1. Architect bindings (governing constraints)

| # | Binding | Where honored in this design |
|---|---|---|
| 1 | `collect_diff` returns `(name_status, added, removed)` 3-tuple; fix `main()` unpack; AC test: default JSON byte-stable when `removed` unused | §2, §6 (AC-1, AC-6) |
| 2 | `detect_structural_modifications(name_status, added, removed)` — Cat A auth/perm decorator mod; Cat B doc section mod with explicit `--unified=0` attribution mechanism, no global unified widening | §3, §4 |
| 3 | Category A reuses the **existing** `FRAMEWORK_TOOLING` constant (no copy) | §3.1 |
| 4 | Evaluator condition 14 after condition 11; `--modifications-only`; FAIL if modification signal uncovered by `human-tier-override.md` | §5 |
| 5 | `--modifications-only` CLI flag emits JSON with detected modification signals | §4 |
| 6 | Existing `--structural-only` output byte-stable; new signals only in `--modifications-only` | §4, §6 (AC-5) |

A binding is a hard constraint. Any deviation must be escalated to `architect`, not silently
resolved.

---

## 2. `collect_diff` — 3-tuple contract

### 2.1 Signature

```python
def collect_diff(base: str, head: str) -> tuple[
    list[tuple[str, str]],   # name_status
    dict[str, list[str]],    # added_lines_by_file
    dict[str, list[str]],    # removed_lines_by_file
]:
```

### 2.2 Behavior

- `name_status` — unchanged: list of `(status_letter, path)` from `git diff --name-status`.
- `added_lines_by_file` — unchanged: path → list of added content lines (leading `+` stripped),
  parsed from `git diff --unified=0`.
- `removed_lines_by_file` — **new**: path → list of removed content lines, leading `-` stripped.
  A removed line is a line beginning with `-` in `--unified=0` output **excluding** the `--- a/`
  file-header line. The current parser already skips `+++` for the added channel; the removed
  channel must symmetrically skip `--- ` headers.

### 2.3 Parser invariant

The single `git diff --unified=0` pass that currently fills `added` must, in the same loop,
fill `removed`:
- `+++ b/<path>` → set `current`, init `added[current]` **and** `removed[current]` to `[]`.
- `--- ` (any line starting `--- `, which is the old-file header) → ignored for the removed
  channel (it is a header, not content). Note `+++ ` already starts with `+` handling; the
  parser must test the 3-char `--- ` / `+++ ` headers **before** the 1-char `+` / `-` content
  tests so a header is never miscounted as content.
- A line starting with `-` and not `--- ` → append `line[1:]` to `removed[current]`.

### 2.4 Caller updates (binding 1)

Every in-repo caller of `collect_diff` must unpack the 3-tuple. The known callers are:
- `main()` at approximately line 295: `name_status, added = collect_diff(...)` →
  `name_status, added, removed = collect_diff(...)`. **CRITICAL** — without this fix `main()`
  raises `ValueError: too many values to unpack`, breaking every CLI mode including the
  byte-stable ones (AC-1).
- `tests/oversight/test_change_classifier.py::test_collect_diff_parses_added_lines` unpacks a
  2-tuple at line 132 — it must be updated to the 3-tuple (test is in-repo "caller").

There are no other `collect_diff` callers (`detect_domains` / `detect_structural` receive
`name_status, added` as already-unpacked arguments and are unchanged).

### 2.5 Backward compatibility

`removed` is **additive at the function level** and **unused at the CLI level** for existing
modes. `--domains-only`, `--structural-only`, `--explain`, and the default JSON output must not
read `removed`; their output is byte-for-byte identical to before this change (AC-1, AC-5, AC-6).

---

## 3. `detect_structural_modifications` — algorithm contract

### Signature

```python
def detect_structural_modifications(
    name_status: list[tuple[str, str]],
    added: dict[str, list[str]],
    removed: dict[str, list[str]],
) -> list[dict]:
    """Return list of {signal, file, section, evidence} modification signals."""
```

Each returned dict has exactly the keys `signal`, `file`, `section`, `evidence`. `section` is
`None` for Category A and a section label string for Category B. This is a **reporter**: it never
raises on a malformed diff; absent keys in `added`/`removed` are treated as empty lists.

### 3.1 Category A — auth/permission decorator modification

Signal name: `modified-permission-or-auth-state`.

For each file present in **both** `added` and `removed` (a file with both an added and a removed
line — i.e. a true modification, not a pure add or pure delete):

1. **FRAMEWORK_TOOLING exemption (binding 3).** If `FRAMEWORK_TOOLING.search(file)` matches, skip
   the file entirely for Category A. Reuse the **existing module-level constant**
   `FRAMEWORK_TOOLING` (regex `(^|/)scripts/(oversight|framework)/.*\.py$`). Do **not** define a
   new copy. Rationale: same HOS#117 self-match hazard the additive scan already avoids.
2. Compile the **`new-permission-or-auth-state`** pattern from `ADDED_LINE_SIGNATURES` (look it up
   by its signal name — do not hard-code a second copy of the regex). Call it `AUTH_RX`.
3. Let `removed_auth = [r for r in removed[file] if AUTH_RX.search(r)]` and
   `added_auth = [a for a in added[file] if AUTH_RX.search(a)]`.
4. A modification is detected when **all** hold:
   - `removed_auth` is non-empty (an existing auth/permission line was removed), AND
   - `added_auth` is non-empty (an auth/permission line was added), AND
   - the change is **not a pure move**: there exists at least one `(removed_line, added_line)`
     pair from `removed_auth × added_auth` whose **stripped** contents differ. Concretely: if
     `set(s.strip() for s in removed_auth) != set(s.strip() for s in added_auth)` → modification.
     If the two stripped sets are identical, the decorator block was only re-ordered/moved →
     **no signal** (per spec R2 Category A bullet 3).
5. On detection, emit one signal per file:
   ```python
   {
     "signal": "modified-permission-or-auth-state",
     "file": file,
     "section": None,
     "evidence": f"-{first_changed_removed.strip()[:80]} | +{first_changed_added.strip()[:80]}",
   }
   ```
   `first_changed_removed` / `first_changed_added` are the first lines from `removed_auth` /
   `added_auth` that participate in the differing set (deterministic: first in diff order). One
   signal per file is sufficient to force the human gate (mirrors `detect_structural`'s
   one-per-file-per-signal rule).

### 3.2 Category B — structural-section modification in tracked documents

Signal name: `modified-doc-structural-section`.

**Tracked-document patterns and structural-section keyword sets** (from spec R2 Category B table)
are encoded as a module-level list of `(file_pattern_regex, section_keyword_regex)` pairs:

| File pattern | Section keywords (case-insensitive) |
|---|---|
| `docs/specs/SPEC-*.md`, `docs/v*/SPEC-*.md` | `permission`, `authorization`, `auth`, `approval`, `gate`, `required`, `must`, `shall`, `deny`, `block`, `restrict` |
| `docs/v*/TECHNICAL-DESIGN-*.md`, `TECHNICAL-DESIGN-*.md` | `permission`, `authorization`, `auth`, `gate`, `access control`, `security`, `input validation`, `sanitiz` |
| `docs/v*/DESIGN*.md`, `DESIGN.md` | `permission`, `authorization`, `auth`, `gate`, `access control` |
| `TELEMETRY-SPEC.md`, `docs/ops/TELEMETRY-SPEC.md` | *(match-all — every section is structural)* |

**Detection** — for each file in both `added` and `removed`, against the **first** tracked-document
pattern that matches the path:

1. Determine the **section label** of the modification via the section-attribution mechanism in
   §3.3.
2. The file qualifies if it both adds at least one line and removes at least one line (already
   guaranteed by "present in both `added` and `removed`"). A purely-additive change does **not**
   reach this function for the doc (a file with no removed lines is not in `removed` with content);
   such changes are condition-10's job (spec R2 Category B final paragraph).
3. The section is **structural** when either:
   - the document's keyword set is *match-all* (TELEMETRY-SPEC), OR
   - the resolved section label matches the document's section-keyword regex (case-insensitive),
     OR
   - **fallback over-detect:** if the section label is the file-level fallback (no parseable
     header, §3.3), test the keyword regex against the **changed lines themselves** (added +
     removed content). This preserves the over-detect bias for docs whose hunk headers carry no
     section context — a permission-bearing edit is caught even when attribution fell back to the
     file. (TELEMETRY-SPEC match-all needs no keyword test.)
4. On a structural-section modification, emit one signal **per (file, section)**:
   ```python
   {
     "signal": "modified-doc-structural-section",
     "file": file,
     "section": section_label,   # e.g. "## Authorization" or the file path on fallback
     "evidence": f"-{first_removed.strip()[:80]} | +{first_added.strip()[:80]}",
   }
   ```

### 3.3 Section attribution under `--unified=0` (binding 2, explicit mechanism)

This is the load-bearing mechanism the architect required stated exactly. **We do not widen the
global `--unified` setting** (R2; HOS keeps `--unified=0` for the added/removed parse). Section
attribution therefore reads the **optional section text git appends to a hunk header**:

```
@@ -5 +5 @@ ## Authorization
                ^^^^^^^^^^^^^^^ — the "section heading" git emits when a funcname/xfuncname
                                 driver is configured for the file type.
```

**Mechanism, in precedence order, per hunk:**

1. **Parse the hunk header.** A hunk header matches `^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: (.*))?$`.
   If capture group 1 (the trailing text after the second `@@ `) is non-empty, that string **is**
   the section label for every changed line in this hunk. This is the `@@ ... @@ section` path the
   architect named. It is populated when the repo configures a markdown `xfuncname` diff driver
   (or for code hunks, the language's built-in funcname pattern).
2. **File-level fallback.** If the hunk header carries no trailing section text (the common
   markdown case with no configured driver — verified empirically), the section label is the
   **file path** itself. The `added`/`removed` dicts are populated by the existing single
   `--unified=0` pass; to attribute lines to hunks, `detect_structural_modifications` performs its
   **own** `git diff --unified=0 -- <file>` read (or re-uses a hunk-aware parse) so it can see the
   `@@` headers the added/removed channels discard. The fallback never widens unified; it only
   reads the same zero-context diff and inspects its hunk headers.

   > Implementation note: because the existing `collect_diff` parse drops `@@` lines, Category B
   > needs hunk-boundary information. The contract is: re-run `git diff --unified=0 -- <file>` for
   > each tracked doc that appears in both `added` and `removed`, walk its hunks, and for each
   > changed line record `(section_label_from_hunk_header_or_filepath, line)`. This keeps the
   > primary `collect_diff` API unchanged for all other callers.

3. **No global config dependence.** The mechanism is correct whether or not a driver is configured:
   with a driver → precise section label; without → file-level fallback + over-detect keyword test
   on changed lines (§3.2 step 3). Either way a permission-bearing doc modification is caught.

### 3.4 Over-detect bias (per spec Non-Requirements)

False positives are acceptable; false negatives are the failure mode. Therefore: when in doubt
(ambiguous header, keyword present in changed lines), **emit the signal**. The human gate is the
safe outcome.

---

## 4. `--modifications-only` CLI flag (bindings 5, 6)

### 4.1 Flag

Add `ap.add_argument("--modifications-only", action="store_true", ...)`.

### 4.2 Output contract

When `--modifications-only` is passed, the program computes
`detect_structural_modifications(name_status, added, removed)` and prints **only**:

```json
{
  "structural_modifications": [
    {"signal": "modified-permission-or-auth-state", "file": "...", "section": null, "evidence": "..."},
    {"signal": "modified-doc-structural-section",   "file": "...", "section": "## Authorization", "evidence": "..."}
  ]
}
```

The top-level key is `structural_modifications`. An empty result emits
`{"structural_modifications": []}`. The mode honors `--explain` for human-readable output, mirroring
the existing modes (optional but consistent).

### 4.3 Byte-stability guarantee (binding 6)

- `--modifications-only` is a **distinct, mutually-additive** mode. The default JSON output and the
  `--structural-only` / `--domains-only` outputs **must not gain** a `structural_modifications`
  key. New signals appear **only** in `--modifications-only` output.
- Wiring in `main()`: a new boolean `want_modifications = args.modifications_only`. When set, the
  output dict is the `structural_modifications`-only object above and the existing
  `domains`/`structural` computation is skipped (or its result discarded) so the default-mode
  output is untouched. The existing `want_domains` / `want_structural` flags must remain driven by
  `--structural-only` / `--domains-only` exactly as today.

This boundary is the contract: **no existing mode's bytes change.** AC-5/AC-6 assert it.

---

## 5. Evaluator condition 14 (bindings 4, 6)

Added to `.claude/agents/oversight-evaluator.md` **immediately after** the condition-11 / SPEC-94
structural-override block (the `--structural-only` block ending at the structural-override audit
events).

### 5.1 Contract

**Condition 14 — Structural-override MODIFICATION re-derivation (SPEC-121).**

1. **Invocation.** Run:
   ```bash
   python3 scripts/oversight/change_classifier.py --modifications-only --base "$BASE_SHA" --head "$HEAD_SHA"
   ```
2. **Loosening-direction only.** Like condition 10, condition 14 runs only to catch a *loosening*
   that escaped the human gate. It is **skipped** when the change was already classified
   `structural` by the authoring agent **and** a covering human-authorization artifact exists, and
   when the SPEC-267 `reviewed_files:` enumeration in `step{N}-human-authorization.md` overlaps the
   diff (same skip rule as condition 10).
3. **Covering-artifact check.** For each `structural_modification` signal, a covering
   human-authorization artifact must exist: `.claudetmp/oversight/step{N}-human-authorization.md`,
   the domain structural-auth file (`.claudetmp/oversight/step{N}-spec-structural-auth.md`), **or**
   a covering `.claudetmp/oversight/human-tier-override.md` (binding 4: the modification signal must
   be covered by a `human-tier-override.md` to pass). The artifact set mirrors condition 10 plus
   the tier-override file the architect named.
4. **Disposition.** If any modification signal is **not** covered → **COMPLIANCE FAIL** (condition
   14). The failure message must list, per uncovered signal: the file, the section title or nearest
   header (Category B) or `null` (Category A), the removed-line/added-line evidence, and which
   artifact path(s) were checked.
5. **Artifact prohibition unchanged.** The evaluator may never create
   `human-tier-override.md` / `human-authorization.md` to clear the FAIL (existing absolute
   prohibition at evaluator line ~384 still governs).

### 5.2 Audit event

When condition 14 fires (uncovered modification), append to `audit/oversight-log.jsonl`:
```json
{"event":"doc-modification-uncovered","step":N,"file":"<path>","section":"<title or null>","evidence":"<removed | added>","timestamp":"<ISO-8601>"}
```
(Spec R3 audit-event schema.) As with condition 10, the event is research data; emit it for each
uncovered modification signal.

### 5.3 Boundary

Condition 14 **does not** alter condition 10/11 behavior, the `--structural-only` invocation, or
its audit events. It is an additive Phase-1 check. The two are independent: condition 10 catches
*additions*, condition 14 catches *modifications*.

---

## 6. Acceptance criteria (testable)

| AC | Statement | Verification |
|---|---|---|
| AC-1 | **Default JSON output byte-stable when `removed` unused** (binding 1 explicit). Running the classifier in default mode on a fixed diff before vs. after the change produces byte-identical stdout. `main()` 3-tuple unpack does not raise. | Test feeds a fixed synthetic repo; asserts default-mode JSON has no `structural_modifications` key and `main()` exits 0. |
| AC-2 | `collect_diff` returns a 3-tuple; `removed_lines_by_file` contains removed content lines with `-` stripped, excludes `--- a/` headers. | Integration test on throwaway repo: a line removed appears in `removed[file]`; the `--- a/` header does not. |
| AC-3 | Category A: same file with removed `@require_permission('admin')` and added `@require_permission('user')` → `modified-permission-or-auth-state`. A pure move (identical stripped sets) → no signal. A file under `scripts/oversight/` → exempt (no signal). | Synthetic `detect_structural_modifications` unit tests. |
| AC-4 | Category B: tracked SPEC doc with a removed + added line in an `## Authorization` section → `modified-doc-structural-section` with the section label (driver path) or file-level fallback + keyword over-detect (no-driver path). A non-tracked file → no signal. | Synthetic + integration unit tests covering both attribution paths. |
| AC-5 | `--structural-only` output is **byte-stable** — no `structural_modifications` key; identical bytes to pre-change for the same diff. | Golden-output assertion. |
| AC-6 | `--modifications-only` emits `{"structural_modifications": [...]}` and **no** `domains_touched` / `structural_signals` keys. | Mode-isolation assertion. |

---

## 7. Out-of-scope / boundaries (per spec Non-Requirements)

- No detection of route modifications or dependency-version modifications (deferred).
- No change to `ADDED_LINE_SIGNATURES` patterns or condition-10 enforcement.
- No change to `human-tier-override.md` / `gate-suspension.md` mechanisms.
- No `contract/OVERSIGHT-CONTRACT.md` edits in this build slice (architect bindings name only the
  classifier + evaluator artifacts).
- `--unified` is **not** widened globally.

---

## 8. HOS self-flag

**Change classification:** `additive` — adds a new detection function, a new CLI mode, and a new
evaluator Phase-1 condition; no existing contract for already-built behavior is altered (existing
modes are byte-stable by binding 6, AC-5/AC-6). No prior sign-off is invalidated: condition 10 and
all existing classifier modes are untouched, so code approved against them stands.

**Startup-gap analysis:** Should this have been settled at initial design? No — this is a
deliberate, scoped narrowing of the documented contract §2a "residual coverage gap." It is new
capability, not a correction to an already-built contract, so no prior sign-off is orphaned.

RISK: LOW
CONFIDENCE: HIGH

(No `## Human Review Required` block required: `additive`, LOW risk, no structural change. The
architect ruling is GO and the bindings are fully specified.)

---

*Status: For architect review → coder*
*Author: technical-design | 2026-06-17*
