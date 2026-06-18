# Technical Design — Issue #376: Arbiter Corroboration Ranking

**Document type:** Technical design specification
**Status:** For architect review → coder implementation
**Issue:** #376
**Spec:** `docs/specs/SPEC-376-arbiter-corroboration-ranking.md`
**Author:** technical-design
**Date:** 2026-06-17
**Architect ruling:** GO (bindings below are binding on this design)

---

## 0. Scope of this design

This design specifies the *contract* for ranking deduplicated panel findings by
cross-vendor corroboration strength. It covers a new pure-Python module
(`scripts/oversight/panel_logic.py`) and the integration points in
`scripts/run_panel.sh`. It does not change reviewer fan-out, the dedup pass
itself (Sonnet remains authoritative for clustering), merge-block semantics, or
finding suppression.

The architect's bindings supersede the spec's R4 interface sketch and OQ-1
default where they differ; this design implements the bindings.

---

## 1. Data model

### 1.1 Raw finding (input — unchanged, produced by REVIEWERS stage)

Each element of `findings.raw.json`, as written today at `run_panel.sh:463`:

| Field | Type | Notes |
|---|---|---|
| `file` | string | path; may be absent/empty |
| `line` | int | 1-based; may be 0 if unanchored |
| `end_line` | int | optional |
| `severity` | string | `tier1`\|`tier2`\|`tier3`\|`tier4` (severity scale, NOT corroboration tier) |
| `title` | string | short |
| `detail` | string | rationale |
| `suggestion` | string | optional fix |
| `reviewer` | string | vendor CLI tag, e.g. `agy`, `codex` (added at `:460`) |
| `lens` | string | review lens, e.g. `correctness`, `security`, `adversary`, `ip` (added at `:460`) |

**Vendor identity:** `reviewer` is the vendor key. The same vendor under two
lenses (`codex:security`, `codex:adversary`) shares `reviewer == "codex"` and
collapses to one independent source (R1 / binding 3).

### 1.2 Deduplicated finding (arbiter output — extended)

Each element of the `findings` array in `arbiter.json`. The arbiter (Sonnet)
emits the existing fields **plus** a new membership field; the Python module
adds the three corroboration fields (binding 4).

| Field | Type | Source | Notes |
|---|---|---|---|
| `file`, `line`, `end_line`, `severity`, `title`, `detail`, `suggestion`, `lens`, `reviewer` | — | Sonnet | as today |
| `merged_from` | array of `{reviewer, lens}` | **Sonnet (new)** | membership list: which raw findings this dedup cluster absorbed (binding 2) |
| `corroborated_by` | int (≥1) | **panel_logic.py** | count of *unique vendors* in membership |
| `corroborating_reviewers` | array of string | **panel_logic.py** | sorted unique vendor list |
| `corroboration_tier` | int (1 or 2) | **panel_logic.py** | 1 if `corroborated_by >= 2` else 2 |

**Invariants:**
- `corroborated_by >= 1` always (fail-open floor, binding 7).
- `corroboration_tier == 1` iff `corroborated_by >= 2`; else `2` (binding 4).
- `len(corroborating_reviewers) == corroborated_by`.
- `corroborating_reviewers` is sorted (deterministic output).
- These fields are distinct from `severity`: `severity` is the four-level
  must-fix scale; `corroboration_tier` is the two-level corroboration scale.

---

## 2. Module contract — `scripts/oversight/panel_logic.py`

Pure module. **No subprocess, no network, no file I/O** in `count_corroboration`
and `rank_findings` (binding 6 / AC4). `reconcile_membership` is also pure (it
only reads two in-memory lists). The module is importable and unit-testable
without invoking `run_panel.sh`.

### 2.1 `count_corroboration(deduplicated_finding) -> tuple[int, list[str]]`

```python
def count_corroboration(deduplicated_finding: dict) -> tuple[int, list[str]]:
```

**Contract (binding 3):**
- Read `deduplicated_finding["merged_from"]`, a list of `{"reviewer", "lens"}`
  dicts.
- Collect the set of distinct `reviewer` values (the vendor key). Same-vendor /
  different-lens collapses: `codex:security` + `codex:adversary` → `{codex}` → 1.
- Return `(count, sorted_unique_reviewers)` where `count == len(set)`.
- **Fail-open (binding 7):** if `merged_from` is missing, empty, not a list, or
  yields zero usable reviewers, return `(1, [reviewer_of_finding_or_"unknown"])`.
  A finding always counts as corroborated by at least itself (≥1), never 0.
- Entries in `merged_from` with a missing/blank `reviewer` are skipped; if all
  are skipped, the fail-open floor applies.
- **Must NOT** call `reconcile_membership` itself, mutate the input, or perform
  I/O.

This function does **not** read `raw_findings`; membership comes from the
arbiter's `merged_from` (binding 2 — Sonnet dedup is authoritative for
clustering). This is the deliberate divergence from the spec R4 sketch.

### 2.2 `reconcile_membership(raw_findings, finding) -> list`

```python
def reconcile_membership(raw_findings: list, finding: dict) -> list:
```

**Contract (binding 3, fallback only):**
- Invoked **only** when `finding["merged_from"]` is missing or empty — the
  Python fallback for a degraded arbiter response that omitted membership.
- Match each raw finding to `finding` by **file + line proximity** (OQ-1
  default, ratified): same `file` (exact string match) AND
  `abs(raw.line - finding.line) <= 5`.
- Return a list of `{"reviewer", "lens"}` dicts (the reconstructed membership),
  one per matched raw finding, suitable to assign to `finding["merged_from"]`.
- A raw finding with no `file`, or `file` mismatch, or line delta > 5 does not
  match. A `finding` with no `file`/`line` matches nothing → returns `[]` (and
  the caller's `count_corroboration` then fail-opens to 1, binding 7).
- Pure: reads only the two arguments; no I/O, no mutation of inputs.

### 2.3 `rank_findings(findings) -> list`

```python
def rank_findings(findings: list) -> list:
```

**Contract (binding 3 + 4):**
- Input: findings already annotated with `corroborated_by` and
  `corroboration_tier` (the caller annotates first — see §3 pipeline). If a
  finding lacks these fields, `rank_findings` treats it fail-open as
  `corroborated_by=1`, `corroboration_tier=2` (binding 7) for ordering purposes
  but does not mutate it.
- Output: **a single flat list** (binding 3 says `rank_findings` returns the
  sorted list — note this overrides the spec R4 two-tuple sketch). Sort order:
  1. **Primary:** corroboration tier ascending (tier 1 before tier 2).
  2. **Secondary:** severity ascending by the four-level scale
     (`tier1` severity most severe first, then `tier2`, `tier3`, `tier4`).
  3. **Tertiary (stable tie-break):** `file` then `line` ascending, for
     deterministic output.
- Stable, deterministic: same input list → same output order every call.
- Pure: returns a new list; does not mutate inputs or input order semantics
  beyond producing the sorted copy. No I/O (binding 6).

**Severity ordering key:** `tier1=0, tier2=1, tier3=2, tier4=3` (lower =
more severe = earlier). Unknown/absent severity sorts last (`99`).

### 2.4 Module CLI entry (for shell integration)

The module exposes a `main()` / `if __name__ == "__main__"` block used by
`run_panel.sh` only. This block *is* allowed I/O (it reads stdin, writes
stdout) — the I/O ban is on the three public functions, not the CLI shim.

- **Input (stdin):** the arbiter JSON object `{"summary":..., "findings":[...]}`.
- **Behavior:** for each finding, if `merged_from` missing/empty, no raw-findings
  source is available at this entry (raw reconciliation is invoked only when the
  caller passes raw findings — see below), so fail-open applies; then annotate
  `corroborated_by` / `corroborating_reviewers` / `corroboration_tier` via
  `count_corroboration`; then reorder `findings` via `rank_findings`.
- **Optional arg `--raw <path>`:** path to `findings.raw.json`. When supplied,
  for any finding with empty/missing `merged_from` the CLI calls
  `reconcile_membership(raw, finding)` to repopulate `merged_from` before
  counting. This keeps `reconcile_membership` file-free (the CLI does the read).
- **Output (stdout):** the same object with each finding annotated and the
  `findings` array reordered. `summary` is passed through untouched.
- **Fail-closed-safe:** on any unexpected exception, the CLI prints the input
  object unchanged (so the panel still posts findings — no suppression,
  binding 9) and exits 0. Ranking is an enhancement, never a gate.

---

## 3. Integration in `run_panel.sh`

### 3.1 Arbiter prompt extension (ARBITER stage, ~`:469`–`:482`)

Extend the Sonnet prompt so each emitted finding includes `merged_from`
(binding 2). Add to the task list:

> (4) For each output finding, include `merged_from`: the list of
> `{"reviewer","lens"}` for every raw finding you merged into it (including the
> finding itself). This is the membership list; do not omit it.

Extend the required output shape to include `"merged_from":[{"reviewer":"...","lens":"..."}]`
per finding. The `summary` field is unchanged.

### 3.2 Ranking call (new, after `:490` where `arbiter.json` is written)

After `ARB_JSON` is parsed and `arbiter.json` written, pipe the arbiter object
through the module and overwrite the parsed findings:

```
RANKED_JSON="$(printf '%s' "$ARB_JSON" \
  | python3 "$PANEL_LOGIC" --raw "$RUN_DIR/findings.raw.json" 2>>"$RUN_DIR/errors.log" \
  || printf '%s' "$ARB_JSON")"
printf '%s' "$RANKED_JSON" > "$RUN_DIR/arbiter.json"   # arbiter.json now carries corroboration fields (binding 8)
FINDINGS="$(printf '%s' "$RANKED_JSON" | jq -c '.findings // []')"
```

`$PANEL_LOGIC` is resolved next to the script (same pattern as `ip_script` at
`:196`), with a CWD-relative fallback. The `|| printf '%s' "$ARB_JSON"` fallback
means a module failure degrades to the old un-ranked behavior — never an error
exit (binding 9 / no suppression).

`arbiter.json` is re-written *after* ranking so the persisted artifact carries
the three new fields (binding 8).

### 3.3 POST stage — tiered sections (binding 5)

The `FINDINGS` array is now globally ordered (tier 1 first, severity within
tier). Two changes:

**Line-level threads (`:507`–`:529`):** iterate `FINDINGS` in order (already
tier-1-first), so Tier 1 threads post before Tier 2 (R3 line-level requirement).
Each thread body gains a corroboration label line derived from
`corroboration_tier`:
- tier 1 → `Tier 1 — cross-vendor confirmed (corroborated by N reviewers)`
- tier 2 → `Tier 2 — single reviewer`

**Summary comment (`:531`–`:545`):** replace the single finding rendering with
two labeled sections built from the ranked `FINDINGS`, partitioned by
`corroboration_tier` via `jq`:

```
## Critical Findings (Corroborated by ≥2 Reviewers)
<tier-1 finding lines>

## Additional Findings (Single Reviewer)
<tier-2 finding lines>
```

- Tier 1 section printed **before** Tier 2 (binding 5).
- A section with zero findings is **omitted entirely** — no empty heading
  (binding 5 / R3).
- The existing arbiter `summary` markdown is retained and appears **above** both
  sections (R3).
- Each finding line shows severity, lens, reviewer(s), file:line, title.

### 3.4 `--dry-run` (binding 10 / AC3)

`--dry-run` already suppresses all `gh` calls. Because ranking and section
assembly happen in-process (the module is a local subprocess, not a GitHub
call), dry-run prints the fully tiered summary to the console. AC3 is verified
by asserting both section headings appear in correct order on a mixed-tier
input, and only the Tier 2 heading appears on an all-tier-2 input. No GitHub
API is touched.

---

## 4. Algorithms (exact)

**Corroboration count (count_corroboration):**
1. `mf = finding.get("merged_from")`; if not a non-empty list → fail-open
   `(1, [finding.get("reviewer") or "unknown"])`.
2. `vendors = sorted({ e["reviewer"] for e in mf if isinstance(e, dict) and e.get("reviewer") })`.
3. if `vendors` empty → fail-open as in step 1.
4. return `(len(vendors), vendors)`.

**Tier assignment (caller, post-count):**
`tier = 1 if corroborated_by >= 2 else 2`.

**Proximity match (reconcile_membership):**
For each `r` in `raw_findings`: matches iff
`r.get("file") and r.get("file") == finding.get("file") and
finding.get("line") is not None and r.get("line") is not None and
abs(int(r["line"]) - int(finding["line"])) <= 5`. Collect
`{"reviewer": r.get("reviewer"), "lens": r.get("lens")}` for matches.

**Ranking sort key (rank_findings):**
`key = (corroboration_tier_or_2, severity_rank, file_or_"", line_or_0)`,
ascending. `severity_rank` from `{tier1:0,tier2:1,tier3:2,tier4:3}` default 99.

---

## 5. Boundaries

- The module **must not** re-cluster findings — Sonnet's dedup is authoritative
  (binding 2). The module only counts and orders.
- The module **must not** suppress, drop, or filter any finding — tier 2 still
  surfaces (binding 9 / §5 non-requirements).
- The module **must not** alter merge-block semantics — no new gate (binding 9).
- `run_panel.sh` **must not** re-implement counting/ranking inline (R4 / #314).
- A module failure **must not** fail the panel — degrade to un-ranked, post
  everything (binding 9).
- `corroboration_tier` **must not** be conflated with `severity` in any output
  field name.

---

## 6. Test contract (for unit-test / system-test agents)

Unit tests (`tests/oversight/test_panel_logic.py`, no subprocess — AC4):
- AC1: two distinct vendors in `merged_from` → `(2, [...sorted])`; single
  vendor → `(1, [...])`; same vendor two lenses → `(1, [vendor])`.
- Binding 7: missing/empty/malformed `merged_from` → `(1, ["unknown" or
  finding reviewer])`.
- AC2: `rank_findings` puts all tier-1 before tier-2, severity-ordered within
  tier, deterministic on repeat calls.
- `reconcile_membership`: file+line±5 match/no-match boundaries (delta 5 matches,
  delta 6 does not; different file does not match; missing line → `[]`).
- Purity: no file/network/subprocess (assert by construction — pass plain dicts).

System/dry-run (AC3): `--dry-run` mixed-tier shows both headings in order;
all-tier-2 shows only the Tier 2 heading.

---

## 7. Affected-sign-offs analysis

This is a **new feature on a new module**; no prior sign-off approved code
against a *different* corroboration contract. The only touched existing surface
is `run_panel.sh`'s arbiter prompt and POST stage. The change is **additive**
(new fields, new section structure; no existing field semantics changed, no
finding dropped). Prior `run_panel.sh` sign-offs for unrelated stages (TRIAGE,
REVIEWERS, sampling, SPEC-379 advisory) stand — none of their contracts change.
No startup-artifact-gap: this is greenfield design, settled before code.

**Change classification:** `additive`.
**RISK:** LOW — pure additive module, fail-open everywhere, no gate/suppression,
no merge-semantics change.
**CONFIDENCE:** HIGH — bindings are explicit and fully specified.

No `## Human Review Required` block required (additive, LOW risk).
