# Requirements Spec — Issue #333: Move Panel JSON Extraction, Finding Aggregation, and Verdict Finalization to Python

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #333
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

`scripts/run_panel.sh` contains three categories of deterministic logic that violate the
#314 policy ("prefer Python for logic, shell for launch — establish testability as a code
review criterion"):

1. **JSON extraction** (`extract_json` bash function, lines 111–134): a bash function
   that reads a reviewer's raw CLI response and attempts to extract the first parseable
   JSON object from it — handling clean JSON, fenced ` ```json ``` ` blocks, and JSON
   embedded in prose. This function is currently called for every reviewer response and
   for the arbiter output. It is not unit-testable without running the shell.

2. **Finding aggregation** (lines 444–462): the per-reviewer loop that calls `extract_json`
   and then uses `jq` to merge findings across reviewer+lens combinations into a single
   `ALL_FINDINGS` JSON array, tagging each finding with its `reviewer` and `lens` fields.
   This is a sequential accumulation step with combinatorial inputs.

3. **Panel verdict finalization** (lines 514–519, 565–619): after the arbiter runs and
   `panel_logic.py` annotates findings, the shell script assembles counts (`TIER1_COUNT`,
   `TIER2_COUNT`, `FCOUNT`) and renders the per-tier finding sections into markdown for
   the PR summary comment. The `render_tier_findings` function (lines 565–570) uses an
   inline `jq` filter to format findings as markdown bullet lines.

All three categories are deterministic transformations on structured data. They are the
exact class that #314 targets for extraction. Bugs in any of these paths affect what the
human sees in the PR: a malformed JSON extraction silently drops a reviewer's findings;
an aggregation error produces wrong finding counts; a rendering error produces a misleading
PR comment.

Note: `panel_logic.py` was seeded by SPEC-376 with `count_corroboration`,
`reconcile_membership`, and `rank_findings`. This spec extends that same module with the
three additional function categories above. The module is not new; this spec adds to it.

---

## 2. Scope

### In scope

- Extract **JSON extraction** (`extract_json`) into a named Python function in
  `scripts/oversight/panel_logic.py`.
- Extract **finding aggregation** (the per-reviewer merge loop) into a named Python
  function in the same module.
- Extract **panel verdict finalization** (tier counts, tier section rendering) into named
  Python functions in the same module.
- The shell script must be updated to call the Python module for these operations; it must
  not re-implement the logic.
- All extracted functions must be unit-testable with synthetic input without running
  `run_panel.sh` or any live model.

### Out of scope

- The model dispatch function (`call_model`) — invokes live CLIs, stays in shell.
- The `build_review_prompt` function — string construction with bash heredoc, stays in
  shell.
- The `post_thread` GitHub API call — network I/O, stays in shell.
- The `UNANCHORED` finding accumulation and fallback summary assembly — sequencing logic
  around `post_thread` calls; stays in shell.
- The arbiter Sonnet call — live model invocation, stays in shell.
- The `log_context_advisory` SPEC-379 advisory — stays in shell.
- The `ip_agent` function — local Python script invocation, stays in shell.
- The CRITICAL blast-radius check and IP stub notice in the summary footer — stays in
  shell.
- `count_corroboration`, `reconcile_membership`, and `rank_findings` — already in
  `panel_logic.py` (SPEC-376), not changed by this spec.

---

## 3. Requirements

### R1 — JSON extraction function

The module must expose a function that extracts a JSON object or array from a raw string
(a reviewer CLI's response), given:
- `raw: str` — the raw text response from a reviewer or arbiter CLI

The function must return a `dict` or `list` (the parsed JSON value), or a fallback
`{"findings": []}` if no parseable JSON can be found.

The extraction logic must match the current `extract_json` bash function behavior exactly
(lines 111–134):
1. Attempt to parse the whole string as JSON. If that succeeds, return it.
2. If step 1 fails, search for a ` ```json ... ``` ` or ` ``` ... ``` ` fenced block
   (case-insensitive, dot-matches-newline) and attempt to parse its content.
3. If step 2 fails, scan the string character by character for the first `{` or `[`
   and attempt `json.JSONDecoder().raw_decode()` from that position. This handles JSON
   embedded in prose with trailing text after the closing brace.
4. If all three steps fail, return `{"findings": []}`.

### R2 — Finding aggregation function

The module must expose a function that merges findings from multiple reviewer responses
into a single list, given:
- `reviewer_responses: list[dict]` — a list of dicts, each containing:
  - `reviewer: str` — the reviewer name (e.g., `"agy"`, `"codex"`)
  - `lens: str` — the lens name (e.g., `"correctness"`, `"security"`)
  - `raw: dict` — the parsed JSON object from the reviewer's response

The function must return a `list[dict]` — the merged findings from all reviewers, where
each finding has `reviewer` and `lens` fields added (or overwritten) from its source.

The aggregation logic must match the current shell loop behavior exactly (lines 444–462):
- For each reviewer response, extract the `findings` field (defaulting to `[]` if absent).
- Tag each finding with the `reviewer` and `lens` values from its source.
- Concatenate all tagged findings into a single flat list.
- The order of findings in the output must be: all findings from the first reviewer, then
  all findings from the second reviewer, etc. (insertion order matches input order).

### R3 — Panel verdict finalization functions

The module must expose functions that compute the summary statistics and format the per-tier
finding sections for the PR comment, given the ranked findings list (already annotated with
`corroboration_tier` by `rank_findings`):

**R3a — Tier counts:** A function that accepts a `list[dict]` of ranked findings and
returns a dict containing:
- `total: int` — total finding count
- `tier1: int` — count of findings with `corroboration_tier == 1`
- `tier2: int` — count of findings where `corroboration_tier` is absent or `2`

**R3b — Tier section rendering:** A function that accepts a `list[dict]` of ranked findings
and a corroboration tier integer (1 or 2), and returns a `str` — the markdown bullet list
of findings for that tier, formatted as:
```
- **{severity} / {lens}** ({corroborating_reviewers joined by ", "}) — `{file}:{line}` — **{title}** — {detail}
```
If the tier has no findings, the function returns an empty string.

The formatting must match the current `render_tier_findings` jq filter behavior exactly
(lines 565–570 in `run_panel.sh`):
- Findings are filtered to the requested tier only.
- Each finding renders as a single bullet line with the fields listed above.
- `corroborating_reviewers` is a list; if absent, fall back to `[reviewer]` (the single
  reviewer name from the finding), then `["panel"]`.
- File and line default to `"?"` and `0` respectively if absent.

### R4 — Shell calls Python for all three operations

The shell script must invoke the Python module for:
1. JSON extraction: replacing all `extract_json` calls with calls to the R1 function.
2. Finding aggregation: replacing the per-reviewer `jq` merge loop (lines 444–462) with
   a call to the R2 function.
3. Tier counts and rendering: replacing the inline `jq` expressions for `TIER1_COUNT`,
   `TIER2_COUNT`, `FCOUNT`, and the `render_tier_findings` jq filter (lines 514–570) with
   calls to the R3a and R3b functions.

The shell script must not duplicate the logic.

### R5 — Unit-testable without a live model run

All functions introduced by R1, R2, and R3 must perform no subprocess calls, no file I/O,
and no network calls. They must be importable and callable in a Python unit test with
synthetic inputs.

---

## 4. Acceptance Criteria

**AC1 — JSON extraction: clean JSON:** Given `raw='{"findings":[{"file":"a.py","line":5}]}'`,
the R1 function returns the parsed dict directly.

**AC2 — JSON extraction: fenced block:** Given `raw` containing a markdown ` ```json ```
` block wrapping a valid JSON object, the R1 function returns the parsed object from inside
the fence.

**AC3 — JSON extraction: embedded in prose:** Given `raw` = `"I found this: {\"findings\":[]}`
followed by trailing text, the R1 function returns `{"findings": []}` (the embedded object).

**AC4 — JSON extraction: no JSON:** Given `raw` containing no JSON whatsoever, the R1
function returns `{"findings": []}`.

**AC5 — Finding aggregation: tagging:** Given two reviewer responses — agy/correctness with
one finding and codex/security with two findings — the R2 function returns a list of 3
findings where the first has `reviewer="agy", lens="correctness"` and the second and third
have `reviewer="codex", lens="security"`.

**AC6 — Finding aggregation: missing findings field:** Given a reviewer response whose
parsed JSON has no `findings` key, that reviewer contributes 0 findings to the merged
output.

**AC7 — Tier counts:** Given a findings list of 3 items where 1 has `corroboration_tier=1`
and 2 have `corroboration_tier=2`, the R3a function returns `{"total": 3, "tier1": 1, "tier2": 2}`.

**AC8 — Tier rendering: correct format:** Given a tier-1 finding with `severity="tier1"`,
`lens="correctness"`, `corroborating_reviewers=["agy","codex"]`, `file="views.py"`,
`line=42`, `title="Missing guard"`, `detail="Can return null"`, the R3b function (called
with tier=1) returns a string containing `` `views.py:42` `` and `(agy, codex)`.

**AC9 — Tier rendering: empty tier:** Given a findings list with no Tier 1 findings, R3b
called with tier=1 returns an empty string.

**AC10 — Shell integration:** Running `run_panel.sh 42 --dry-run` with a valid PR produces
the same PR comment body as the current script (same sections, same finding counts, same
formatting) after this change. The `extract_json` bash function is removed.

**AC11 — No logic duplication:** After this change, `run_panel.sh` contains no inline `jq`
expressions for finding aggregation or tier rendering, and no `extract_json` bash function.

---

## 5. Non-Requirements

- **No behavior change.** The refactored script must produce the same PR comment content,
  the same `arbiter.json` output, and the same `findings.raw.json` output as the current
  script for all inputs.
- **No new review features.** This spec does not add new reviewer types, new finding
  fields, or new summary sections.
- **Shell still posts threads and comments.** The GitHub API calls (`post_thread`,
  `gh pr comment`) stay in shell.
- **No change to the arbiter prompt.** The Sonnet arbiter call and its prompt string are
  unchanged.
- **No change to the `corroboration_tier` schema.** The fields added by SPEC-376's
  `rank_findings` are the inputs to R3a/R3b; this spec does not change their meaning.

---

## 6. Open Questions

**OQ-1 — CLI shim interface for shell integration**
The current `extract_json` bash function reads from stdin (via a temp file intermediary).
The Python equivalent could be called as: (a) a named subcommand of the `panel_logic.py`
CLI shim (`python3 panel_logic.py extract-json`), (b) a separate one-liner call per
reviewer response, or (c) inline `python3 -c` calls referencing the module. The architect
should rule on the preferred integration pattern, consistent with the precedent set by
SPEC-376's `--raw` CLI interface.

**OQ-2 — Finding aggregation: shell loop vs. single Python call**
The current shell loop (lines 444–462) iterates over the reviewer roster, calls the model,
and accumulates findings one reviewer at a time. The R2 function aggregates pre-collected
responses. The architect should confirm whether the loop structure changes (e.g., the shell
collects all raw responses first, then calls the Python aggregator once) or whether the
Python function is called incrementally inside the shell loop. The latter may require
a different function signature.

**OQ-3 — `jq` dependency reduction**
After extracting R1, R2, and R3, several remaining `jq` invocations in `run_panel.sh`
(e.g., `.findings // []`, `.summary // "(no summary)"`, individual field extractions in
the `post_thread` loop) would still exist. The architect should rule on whether the goal
is to eliminate `jq` from `run_panel.sh` entirely (making Python the exclusive JSON
processor) or only to extract the testable logic. This spec requires only the latter.

**OQ-4 — `panel_logic.py` module size and organization**
SPEC-376 seeded the module with 3 functions (~115 lines). SPEC-332 adds 2 more; this spec
adds at least 4 more. The architect should assess whether all panel logic belongs in one
`panel_logic.py` module or whether a subdirectory (`scripts/oversight/panel/`) with multiple
focused modules is preferable at this scale.

---

## 7. Context for Architect

- The `extract_json` function is at `run_panel.sh` lines 111–134. It is called at line
  455 (per-reviewer), line 488 (arbiter output), and line 300 (Haiku triage output). All
  three call sites must be updated.
- The finding aggregation loop is at lines 444–462. `ALL_FINDINGS` is initialized to `[]`
  and accumulated per reviewer; this feeds `findings.raw.json` and the arbiter prompt.
- `render_tier_findings` is at lines 565–570. It is called twice (tier 1, tier 2) at lines
  571–572 and their outputs are used in the PR summary comment construction.
- `TIER1_COUNT` and `TIER2_COUNT` are computed at lines 518–519 via inline `jq`.
- `panel_logic.py` purity binding (SPEC-376 binding 6 / AC4): the CLI shim at
  `__main__` is the only place that does I/O. New functions added by this spec must be
  pure (no subprocess, network, or file I/O).
- The SPEC-376 module currently exposes: `count_corroboration(deduplicated_finding)`,
  `reconcile_membership(raw_findings, finding)`, `rank_findings(findings)`, and
  `annotate_and_rank(arbiter_obj, raw_findings)`. The new functions from this spec
  are additive; they do not replace or modify any of those.
- Issue #314 is the policy driver. Issue #332 adds triage-floor and SQC sampling to the
  same module. Issue #331 creates a parallel `second_review_logic.py` for the second-
  review script's logic. All three follow the same structural pattern.
