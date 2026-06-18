# Technical Design — Issue #333: Panel JSON Extraction + Finding Aggregation + Verdict Finalization → `panel_logic.py`

**Document type:** Technical design (contract for the coder)
**Status:** For architect review — architect ruling GO
**Issue / Spec:** #333 / `docs/specs/SPEC-333-panel-logic-python.md`
**Architect ruling:** GO (bindings reproduced in §0)
**Depends on:** SPEC-376 (seeded `panel_logic.py`), SPEC-332 (added triage-floor + SQC subcommands)
**Author:** technical-design
**Date:** 2026-06-17

---

## 0. Architect bindings (governing)

1. **EXTEND** `scripts/oversight/panel_logic.py` — do NOT create a new file.
2. **CLI subcommands with stdin for payloads.** Use argparse subcommands
   `extract-json`, `aggregate`, `tier-counts`, `render-tier`. The raw reviewer
   response arrives on **stdin** (NOT argv — content can contain shell-hostile
   characters: quotes, backticks, `$`, newlines).
3. **One-pass aggregation.** The shell collects ALL reviewer responses into a
   single JSON array first, THEN calls `aggregate` once with that array on stdin.
   No incremental per-reviewer Python call.
4. **Partially eliminate jq.** Extract the testable aggregation / counting /
   multi-field-formatting logic to Python. Trivial single-field plucks
   (`.summary // "(no summary)"`, `.title`, `.findings // []`) MAY stay in shell.
5. **Extraction/aggregation subcommands MUST NOT inherit the fail-open exit-0
   posture** of the default `__main__` ranking path. `extract-json` and
   `aggregate` return the `{"findings": []}` fallback on *empty/malformed* input
   but exit **non-zero** on a structural failure (see §4 exit-code contract).
6. **No finding suppression, no new merge gate.** Every finding still surfaces;
   this is a pure parity refactor (Spec §5).

This design is a contract: it specifies *what* each function and shell call must
do. It does not contain the implementation.

---

## 1. Functions to add (pure — no I/O)

All four functions live in `scripts/oversight/panel_logic.py` alongside the
existing SPEC-376/332 functions. All are **pure**: no subprocess, network, or
file I/O; they do not mutate their inputs (binding 6 / Spec R5). Only the
`__main__` CLI shim does I/O.

### 1.1 `extract_json(reviewer_response: str) -> dict` (Spec R1)

Three-strategy best-effort parse of a raw reviewer/arbiter CLI response. Returns
the parsed JSON value, or the fallback `{"findings": []}`. **Never raises.**

| Strategy | Input shape | Action |
|---|---|---|
| 1. Clean JSON | whole string is JSON | `json.loads(raw)` → return on success |
| 2. Fenced block | ` ```json … ``` ` or ` ``` … ``` ` | regex `` ```(?:json)?\s*(.*?)``` `` (`re.S`, case-insensitive on the `json` tag); `json.loads` the captured group |
| 3. Embedded in prose | JSON after leading prose, trailing text after close | scan for first `{` or `[`; `json.JSONDecoder().raw_decode(raw[i:])`; first success wins |
| 4. Fallback | none of the above parse | return `{"findings": []}` |

**Parity anchor:** this MUST reproduce the current `extract_json` bash function
(`run_panel.sh` lines 111–134) exactly — same three strategies, same order, same
regex, same fallback. The function signature names the parameter
`reviewer_response` (matches the task contract); the docstring/spec call it `raw`.

**Boundaries:**
- Return type is annotated `dict` to match the task contract, but a top-level
  JSON **array** (strategy 1 or 3 hitting a `[`) is returned as-is (a `list`) —
  parity with the bash function, which returned whatever parsed. Callers that
  need a dict apply their own `.findings // []` pluck. Do not coerce or wrap.
- Empty string / whitespace-only → fallback `{"findings": []}` (strategies all
  miss). This is **not** a structural failure; it is the documented degrade path.
- `None` is not a valid input (shell always passes a string). The function is
  typed `str`; behavior on non-str is unspecified and untested.

### 1.2 `aggregate_findings(reviewer_responses: list[dict]) -> list[dict]` (Spec R2)

Merge findings from multiple reviewer responses into one flat list, tagging each
finding with its source `reviewer` and `lens`.

**Input:** `reviewer_responses` — a list of dicts, each:
```
{"reviewer": "<vendor>", "lens": "<lens>", "raw": <parsed-JSON-object>}
```
where `raw` is the dict returned by `extract_json` for that reviewer.

**Algorithm (parity with shell lines 444–462):**
1. For each response in input order:
   a. `findings = response["raw"].get("findings", [])` — default `[]` if the key
      is absent or `raw` is not a dict (Spec R2 / AC6).
   b. For each finding (a dict) in that list, produce a **copy** with
      `reviewer` and `lens` set (added or **overwritten**) from the response's
      top-level `reviewer`/`lens`.
2. Concatenate in order: all of reviewer-1's tagged findings, then reviewer-2's,
   etc. Insertion order matches input order (Spec R2 last bullet / AC5).

**Boundaries:**
- Do not mutate the caller's finding dicts — tag on a shallow copy.
- A finding that is not a dict is skipped (cannot tag a non-dict); this matches
  the shell `jq map(. + {…})` which would error on a non-object — but the shell
  guards with `|| echo '[]'`, so dropping non-dict entries is the safe parity.
- `reviewer`/`lens` overwrite is intentional: the source-of-truth for these tags
  is the roster spec, not whatever the model echoed back (Spec R2: "added or
  overwritten").

### 1.3 `count_tiers(findings: list[dict]) -> dict` (Spec R3a)

Compute summary counts over the **ranked** findings (already annotated with
`corroboration_tier` by `rank_findings`).

**Returns:** `{"total": int, "tier1": int, "tier2": int}` where
- `total` = `len(findings)`
- `tier1` = count of findings with `corroboration_tier == 1`
- `tier2` = count of findings where `corroboration_tier` is **absent or 2**
  (parity with shell `(.corroboration_tier // 2) == 2`, line 519)

**Boundaries:**
- `tier1 + tier2` need not equal `total` only if a finding had an unexpected
  `corroboration_tier` value (e.g. 3). Parity with the shell: tier1 selects `==1`,
  tier2 selects `(// 2) == 2`; a stray value is counted in neither. Do not
  normalize — reproduce the shell's two independent filters exactly.
- Non-list input → `{"total": 0, "tier1": 0, "tier2": 0}` (defensive; the shell
  would `jq length` to 0).

### 1.4 `render_tier_section(findings: list[dict], tier: int) -> str` (Spec R3b)

Render the markdown bullet lines for findings of one corroboration tier.

**Filter:** findings where `(corroboration_tier // 2) == tier` — i.e. tier-2
selection includes findings missing the field (parity with shell line 568).

**Per-finding line format** (verbatim from shell `render_tier_findings`, line 569):
```
- **{severity} / {lens}** ({reviewers}) — `{file}:{line}` — **{title}** — {detail}
```
where:
| Field | Source | Default |
|---|---|---|
| `severity` | `finding["severity"]` | `"tier?"` |
| `lens` | `finding["lens"]` | `"?"` |
| `reviewers` | `finding["corroborating_reviewers"]` joined by `", "` | fall back to `[finding["reviewer"]]`, then `["panel"]` |
| `file` | `finding["file"]` | `"?"` |
| `line` | `finding["line"]` | `0` |
| `title` | `finding["title"]` | `""` |
| `detail` | `finding["detail"]` | `""` |

**Returns:** the bullet lines joined by `"\n"`. **Empty string** if no finding
matches the tier (Spec AC9 — the shell `jq … | .[]` emits nothing → empty).

**Boundaries:**
- The `corroborating_reviewers` fallback chain mirrors the shell jq
  `(.corroborating_reviewers // [.reviewer // "panel"] | join(", "))`: use the
  list if present and non-empty; else `[reviewer]` if `reviewer` present; else
  `["panel"]`.
- No trailing newline on the final line (matches `jq -r … | .[]` output that the
  shell captured with `$(...)`, which strips trailing newlines anyway).

---

## 2. CLI subcommands (the ONLY I/O — binding 2)

Four new argparse subparsers on the existing `panel_logic.py` parser. Each reads
its payload from **stdin** and writes its result to **stdout**.

| Subcommand | Stdin | Stdout | Args |
|---|---|---|---|
| `extract-json` | raw reviewer/arbiter response (text) | compact JSON of the extracted value | — |
| `aggregate` | JSON **array** of `{reviewer,lens,raw}` objects | compact JSON array of tagged findings | — |
| `tier-counts` | JSON array of ranked findings | compact JSON `{total,tier1,tier2}` | — |
| `render-tier` | JSON array of ranked findings | markdown bullet lines (text) | `--tier <1\|2>` (required, int) |

**Subcommand handlers** (mirroring the existing `_run_triage_floor` /
`_run_sqc_sample` style):
- `_run_extract_json(args)` — read stdin; `extract_json`; write
  `json.dumps(result)`; return 0. On stdin that is non-empty but parses to the
  fallback, that is a **successful degrade** (exit 0) — the bash function also
  printed `{"findings": []}` and exited 0.
- `_run_aggregate(args)` — read stdin; `json.loads` to a list; `aggregate_findings`;
  write `json.dumps(result)`; return 0.
- `_run_tier_counts(args)` — read stdin; `json.loads` to a list; `count_tiers`;
  write `json.dumps(result)`; return 0.
- `_run_render_tier(args)` — read stdin; `json.loads` to a list;
  `render_tier_section(findings, args.tier)`; write the string (no `json.dumps`);
  return 0.

---

## 3. Exit-code contract (binding 5 — the one behavioral departure)

The default `__main__` ranking path is **fail-open exit-0** (ranking is an
enhancement, never a gate). The four NEW subcommands MUST NOT inherit that posture
for *structural* failures:

| Condition | `extract-json` | `aggregate` / `tier-counts` / `render-tier` |
|---|---|---|
| Empty / whitespace stdin | write `{"findings": []}` (or `[]`/`{}` as documented), exit **0** | write the empty/fallback result, exit **0** |
| Well-formed input | write result, exit **0** | write result, exit **0** |
| Stdin is **malformed JSON** where structured JSON is *required* (`aggregate`/`tier-counts`/`render-tier` expect a JSON array) | n/a (extract-json never requires valid JSON) | write the fallback (`{"findings": []}` for aggregate; `{"total":0,...}` for tier-counts; `""` for render-tier) **AND exit non-zero (2)** |
| Wrong `--tier` value / argparse error | argparse exits 2 | argparse exits 2 |

Rationale: `extract-json` operates on *raw model text* where "no parseable JSON"
is an expected, benign outcome → exit 0 with fallback. The other three operate on
*JSON the shell itself produced* (the aggregated array / ranked findings); if that
is malformed, something upstream broke and the failure must surface non-zero so
`set -euo pipefail` (with explicit handling) can catch it. **In all cases the
fallback value is still written** so no finding path silently drops (binding 6) —
but the non-zero exit makes the structural break visible.

**Shell consumption rule:** the shell calls these without a `|| true` swallow for
`aggregate`/`tier-counts`/`render-tier`, so a non-zero exit propagates under
`set -e`. For `extract-json`, the shell keeps its existing best-effort handling
(it already tolerates the fallback).

---

## 4. Shell integration — `scripts/run_panel.sh` (Spec R4)

`$PANEL_LOGIC` is already resolved (SPEC-332 TRIAGE section). All new calls use
`python3 "$PANEL_LOGIC" <subcommand>` with the payload piped on stdin.

### 4.1 Remove the `extract_json` bash function (lines 111–134)

Delete the entire bash function. Replace its three call sites:

| Call site | Current | Replacement |
|---|---|---|
| Triage (line 298–299) | `… \| extract_json \| jq -r '.risk // empty'` | `… \| python3 "$PANEL_LOGIC" extract-json \| jq -r '.risk // empty'` |
| Per-reviewer (line 457) | `… \| extract_json \| jq -c '.findings // []'` | folded into the one-pass aggregate (§4.2) — the per-chunk raw is collected, extraction happens inside `aggregate` |
| Arbiter (line 490) | `… \| extract_json` | `… \| python3 "$PANEL_LOGIC" extract-json` |

The triage `.risk`/`.reason` and arbiter plucks stay as trivial jq on the
extracted JSON (binding 4 permits single-field plucks).

### 4.2 One-pass finding aggregation (replace lines 444–465)

The current loop calls the model per chunk, extracts per chunk, and jq-merges
incrementally. The new structure (binding 3):

1. For each roster reviewer × chunk: call the model, save the raw `.txt`
   (unchanged), run `log_context_advisory` (unchanged). Instead of extracting +
   merging in jq, **append one JSON object per reviewer** to a shell-built array
   of `{reviewer, lens, raw}` entries, where `raw` is the parsed JSON for that
   reviewer (the union of its chunks).
   - To keep one entry per reviewer (preserving the existing per-reviewer
     `findings.raw.json` semantics and the `ok "$tool/$lens → $n raw finding(s)"`
     log line), the shell still extracts each chunk's JSON via
     `extract-json` and unions a reviewer's chunk-findings into a single
     `raw={"findings":[…]}` object before appending its roster entry. (This keeps
     the chunk-union in shell jq — a trivial `.findings // []` concat — and lets
     Python own the cross-reviewer tag+merge.)
2. After the loop, the shell holds `RESPONSES_JSON` = a JSON array of
   `{reviewer,lens,raw}`. Call **once**:
   ```
   ALL_FINDINGS="$(printf '%s' "$RESPONSES_JSON" | python3 "$PANEL_LOGIC" aggregate)"
   ```
3. `printf '%s' "$ALL_FINDINGS" > "$RUN_DIR/findings.raw.json"` and
   `RAW_COUNT=$(… jq 'length')` — unchanged downstream.

This removes the inline `jq map(. + {reviewer,lens})` and the
`jq -cn '$a + $b'` cross-reviewer accumulator (the testable aggregation),
satisfying AC11. The per-chunk `.findings // []` pluck and per-reviewer count
`jq 'length'` are trivial plucks and may remain.

### 4.3 Tier counts (replace lines 517–519)

```
FCOUNT=$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" tier-counts | jq -r '.total')
TIER1_COUNT=$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" tier-counts | jq -r '.tier1')
TIER2_COUNT=$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" tier-counts | jq -r '.tier2')
```
To avoid three calls, prefer a single call capturing the object then plucking:
```
TIER_COUNTS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" tier-counts)"
FCOUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.total')
TIER1_COUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.tier1')
TIER2_COUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.tier2')
```
The `.total`/`.tier1`/`.tier2` plucks are trivial single-field (binding 4).

### 4.4 Tier section rendering (replace `render_tier_findings`, lines 566–573)

Delete the `render_tier_findings` bash function (the inline jq filter). Replace:
```
TIER1_FINDINGS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" render-tier --tier 1)"
TIER2_FINDINGS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" render-tier --tier 2)"
```

### 4.5 What STAYS in shell (Spec §2 out-of-scope + binding 4)

`call_model`, `build_review_prompt`, `lens_brief`, `post_thread`, the
per-finding jq plucks in the `post_thread` loop (lines 534–544), `log_context_advisory`,
the `SUMMARY` / `.summary` pluck (line 515), the `.findings // []` pluck (line
516), the arbiter prompt + Sonnet call, the SQC salt handling, the CRITICAL
blast-radius footer, and the IP-stub notice. No change to any of these.

---

## 5. Boundaries the coder must honor

- **No behavior change** (Spec §5): the refactored script must produce the same
  PR comment body, `arbiter.json`, and `findings.raw.json` as the current script
  for all inputs. The four functions reproduce the shell logic exactly.
- **Purity** (binding 6): the four new functions do NO I/O and do not mutate
  inputs. Only the CLI shim handlers touch stdin/stdout.
- **No suppression** (binding 6): every finding flows through; aggregation never
  drops a finding except a structurally-invalid non-dict (which the shell jq also
  could not have tagged).
- **Exit-code posture** (binding 5 / §3): the new subcommands surface structural
  failures non-zero; they do not adopt the default path's blanket exit-0.
- **Module size** (Spec OQ-4, architect ruled): single flat `panel_logic.py`, no
  subpackage.

---

## 6. Test contract (for `unit-test`, satisfying Spec §4 AC1–AC9)

New tests append to `tests/oversight/test_panel_logic.py` (importing the four new
symbols). Required cases, one per AC:

| Test | AC | Assertion |
|---|---|---|
| clean JSON | AC1 | `extract_json('{"findings":[{"file":"a.py","line":5}]}')` returns that dict |
| fenced block | AC2 | a ` ```json … ``` ` wrapper returns the inner object |
| embedded in prose | AC3 | leading prose + `{…}` + trailing text returns the embedded object |
| no JSON | AC4 | non-JSON text returns `{"findings": []}` |
| aggregation tagging | AC5 | agy/correctness (1) + codex/security (2) → 3 findings, correctly tagged, in order |
| missing findings key | AC6 | a `raw` with no `findings` contributes 0 |
| tier counts | AC7 | 1×tier1 + 2×tier2 → `{"total":3,"tier1":1,"tier2":2}` |
| render format | AC8 | tier-1 finding renders a line containing `` `views.py:42` `` and `(agy, codex)` |
| render empty tier | AC9 | no tier-1 findings → `render_tier_section(…, 1) == ""` |

Additional parity/boundary cases the coder should add: `aggregate` insertion
order across ≥2 reviewers; `extract_json` returning a top-level array; the
`corroborating_reviewers` fallback chain in `render_tier_section`
(list → `[reviewer]` → `["panel"]`); `count_tiers` on missing-tier findings.

---

## 7. Self-flag (design authoring)

RISK: LOW
CONFIDENCE: HIGH

Change class: **additive** (four new pure functions + four CLI subcommands; the
one behavioral departure — non-zero exit on structural failure for three
subcommands — is an architect binding, not a new design decision, and never
suppresses a finding). No `## Human Review Required` block required: this is a
parity refactor with an explicit architect GO and no structural change.

Affected sign-offs: none invalidated. This extends a module whose prior functions
are unchanged; no previously-approved code is re-contracted.
