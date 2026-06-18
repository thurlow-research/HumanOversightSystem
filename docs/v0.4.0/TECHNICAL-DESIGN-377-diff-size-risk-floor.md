# Technical Design — SPEC-377: Diff-Size Risk-Tier Floor and Multi-Purpose Split Trigger

**Document type:** Technical design
**Status:** For architect review
**Issue:** #377
**Spec:** `docs/specs/SPEC-377-diff-size-risk-floor.md`
**Architect ruling:** GO (bindings #1–#10 below are binding)
**Date:** 2026-06-17
**Author:** technical-design

---

## 0. Architect bindings applied

This design implements the architect's ten binding decisions verbatim. Where the spec
left an open question (OQ-377-A through OQ-377-D), the binding governs:

| OQ | Architect binding |
|---|---|
| OQ-377-A | New standalone validator `scripts/oversight/validators/diff_size.py`. The floor logic does **not** live in `rn_calculator.py`. |
| OQ-377-B | `HOS_DOMAIN_MAP` format is `prefix=label;prefix=label;...`. When set, it **replaces** the default map. Malformed → full fallback to default map + stderr warning. |
| OQ-377-C | `make_result()` gains an optional final parameter `tier_floor: str \| None = None`, emitted as a top-level `"tier_floor"` key. `"diff_size": 0.0` added to `WEIGHTS`. No other `schema.py` change. |
| OQ-377-D | Git runs in `run_validators.sh`, not in the validator. The validator receives `--changed-lines N --changed-files N --changed-file-list f1 f2 ...`. |

---

## 1. Component map

| Component | File | Change type |
|---|---|---|
| Diff-size validator | `scripts/oversight/validators/diff_size.py` | **new** |
| Result envelope | `scripts/oversight/validators/schema.py` | additive (2 edits) |
| Validator orchestration | `scripts/oversight/run_validators.sh` | additive (invocation + tier_floor hoist) |

---

## 2. `schema.py` contract changes (binding #2)

### 2.1 `make_result()` signature

Add **one** optional parameter as the **final** positional/keyword argument, after `error`:

```
tier_floor: str | None = None
```

The return dict gains exactly one new key, `"tier_floor": tier_floor`, at the **top level**
of the envelope (sibling of `dimension`, `score`, `weight`, `raw_value`, `error`).

**Boundaries:**
- The parameter is optional and defaults to `None`. Every existing `make_result()` call
  site continues to work unchanged and produces `"tier_floor": null`. This is an additive,
  backward-compatible change — no existing caller is touched.
- `make_result()` performs **no validation or normalization** of `tier_floor`. It stores the
  caller's value as-is. Tier-string correctness is the validator's responsibility.
- The score-clamping, evidence-defaulting, and other existing behavior of `make_result()`
  is unchanged.

### 2.2 `WEIGHTS` dict

Add one entry:

```
"diff_size": 0.0,
```

**Rationale / boundary:** weight `0.0` means the diff-size dimension contributes **nothing**
to the composite weighted average (`composite_score()` multiplies score by weight). This
honors REQ-377-07 / REQ-377-21: the floor is a discrete promotion signal, not a score
contributor. The validator still emits a `score` (set to `0.0`) so the envelope is
well-formed, but that score is mathematically inert in the aggregate.

**Not changed:** `TIER_THRESHOLDS`, `score_to_tier()`, `composite_score()`, `normalize()`,
and all other `WEIGHTS` entries are untouched (Non-Requirement §5: no weight/threshold
boundary changes).

---

## 3. `diff_size.py` — validator contract

### 3.1 CLI interface (binding #3)

```
diff_size.py --changed-lines N --changed-files N --changed-file-list f1 f2 f3 ...
```

| Flag | Type | Semantics |
|---|---|---|
| `--changed-lines` | int ≥ 0 | Total added + deleted lines in the diff. `0` = data unavailable. |
| `--changed-files` | int ≥ 0 | Total count of changed files (all types). `0` = data unavailable. |
| `--changed-file-list` | str* (variadic, trailing) | Zero or more changed file paths. Consumes all remaining args. Empty → split-trigger does not fire. |

**Boundaries:**
- `--changed-file-list` MUST be the last flag, consuming all trailing tokens (binding #3
  shows it last). All paths after it are file-list members.
- Missing `--changed-lines` / `--changed-files` default to `0` (treated as data-unavailable).
- The validator never invokes `git`, never reads the filesystem for diff data, never reads
  file contents. It operates purely on the CLI-supplied integers and path strings (REQ-377-12).
- Non-integer `--changed-lines` / `--changed-files` values: log `[diff-size]` warning to
  stderr and treat as `0` (data unavailable). The validator must not crash on bad numeric
  input; stdout JSON must always be valid (REQ-377-20).

### 3.2 Threshold configuration (binding #8, REQ-377-16/17/18)

Read three env vars at startup; each parses to a **positive** integer else falls back to
default with a `[diff-size]` stderr warning:

| Env var | Default | Applies to |
|---|---|---|
| `HOS_DIFF_SIZE_FLOOR` | `400` | line-count floor |
| `HOS_FILE_COUNT_FLOOR` | `15` | file-count floor |
| `HOS_DOMAIN_SPLIT_THRESHOLD` | `3` | domain split advisory |

Fallback rule (REQ-377-17): value absent → default silently; value present but not a
positive int (e.g. `abc`, `0`, `-5`, `1.5`) → stderr warning + default. A configured
threshold of `0` is invalid and triggers fallback (REQ-377-18 note).

### 3.3 Diff-size floor algorithm R1 (binding #6, REQ-377-04..07)

```
lines_fires  = (changed_lines > 0) and (changed_lines > HOS_DIFF_SIZE_FLOOR)
files_fires  = (changed_files > 0) and (changed_files > HOS_FILE_COUNT_FLOOR)

if lines_fires or files_fires:
    tier_floor = "HIGH"
    floor_rule_fired = "both" if (lines_fires and files_fires)
                       else "changed_lines" if lines_fires
                       else "changed_files"
else:
    tier_floor = None
    floor_rule_fired = None
```

**Boundaries:**
- Comparison is **strictly greater than** (`>`), not `>=`. `changed_lines == HOS_DIFF_SIZE_FLOOR`
  does **not** fire (AC-377-08: floor=10, lines=11 fires; lines=10 would not).
- A zero value for either metric is "data unavailable" and is gated out **before** the
  threshold comparison, regardless of configured threshold (REQ-377-18, AC-377-05).
- The floor only ever promotes to `"HIGH"`. It never sets MEDIUM/CRITICAL and never lowers
  a tier. It does not modify `score` (REQ-377-07).

### 3.4 Domain-detection heuristic (binding #4, #5, REQ-377-12..15)

**Default domain map** (binding #5 — HOS source layout, ordered; first match wins):

| Prefix | Label |
|---|---|
| `scripts/` | `scripts` |
| `.claude/agents/` | `agents` |
| `docs/` | `docs` |
| `packs/` | `packs` |
| `bootstrap/` | `bootstrap` |
| `contract/` | `contract` |
| `audit/` | `audit` |
| (no match) | `other` |

> Note: binding #5 enumerates the seven prefixes above. The spec's REQ-377-13 table also
> lists `templates/=templates`; binding #5 governs the default map for HOS self-governance
> runs and does **not** include `templates/`, so a `templates/...` path falls through to the
> catch-all `other` under the binding. The binding is authoritative here. **(Flagged below
> in §7 as a clarifying divergence from the spec table for architect confirmation.)**

**Matching:** each path is tested against the ordered prefix list; the first prefix that the
path **starts with** assigns the label. A path matching no prefix → `other` (REQ-377-14).
`other` collapses to a single label no matter how many files land there.

`domain_count` = number of **distinct** labels across all changed-file-list paths.
`domains_detected` = the distinct labels, as a list. Order: first-appearance order across
the input file list (deterministic for a given input; AC-377-13 only asserts membership, not
order, so first-appearance is acceptable and stable).

If the changed-file-list is empty: `domain_count = 0`, `domains_detected = []`, split trigger
does not fire (REQ-377-03).

**`HOS_DOMAIN_MAP` override (binding #4, REQ-377-15):**
- Format: `prefix=label;prefix=label;...` — semicolon-separated entries, each `prefix=label`.
- When set and **well-formed**, it **replaces** (not extends) the default map. Order of
  entries in the string is the match order. A catch-all `other` is still applied to any path
  matching none of the override prefixes (the catch-all is implicit and always present).
- **Malformed** (any entry lacking exactly one `=`, empty prefix, or empty label, or the var
  parsing to zero usable entries): log a `[diff-size]` warning to stderr and **fall back
  fully to the default map** (binding #4). No partial application.

### 3.5 Split trigger R2 (binding #7, REQ-377-08..11)

```
if domain_count >= HOS_DOMAIN_SPLIT_THRESHOLD:
    append to checklist_items:
      "Consider splitting into focused PRs: changes span {domain_count} domains "
      "(threshold {HOS_DOMAIN_SPLIT_THRESHOLD}); domains: {comma-joined domains_detected}"
```

**Boundaries (binding #7, REQ-377-10):**
- The advisory goes in `checklist_items` only. It MUST contain the exact phrase
  `Consider splitting into focused PRs` (AC-377-06) and MUST state the detected count and
  threshold (REQ-377-09).
- The split trigger **never** sets `tier_floor` and **never** changes the exit code
  (AC-377-07). It is advisory-only.

### 3.6 stderr logging R4 (REQ-377-19/20)

When the floor fires, emit one line prefixed `[diff-size]` naming the rule, measured value,
and threshold. When the split advisory fires, emit one `[diff-size]` line naming domain_count,
threshold, and domains. stderr output never contaminates stdout; stdout is always exactly one
`make_result`-conformant JSON object (AC-377-11/12, AC-377-20).

### 3.7 Output envelope (REQ-377-21/22)

The validator calls:

```
make_result(
    dimension="diff_size",
    score=0.0,
    raw_value={
        "changed_lines": <int>,
        "changed_files": <int>,
        "floor_rule_fired": <"changed_lines"|"changed_files"|"both"|None>,
        "domain_count": <int>,            # always present; 0 if no file list
        "domains_detected": <list[str]>,  # always present; [] if no file list
        "thresholds": {                   # echo effective thresholds for audit
            "diff_size_floor": <int>,
            "file_count_floor": <int>,
            "domain_split_threshold": <int>,
        },
    },
    weight=WEIGHTS["diff_size"],          # 0.0
    checklist_items=<split advisory list or []>,
    tier_floor=<"HIGH"|None>,             # also top-level via binding #2
)
```

`tier_floor` therefore appears **both** nested under intent in `raw_value`'s sibling fields
(via `floor_rule_fired`) **and** as the dedicated top-level key (REQ-377-22, AC-377-10) that
`run_validators.sh` reads without parsing `raw_value`.

---

## 4. `run_validators.sh` changes (binding #9, #10)

### 4.1 Git-derived inputs (binding #9)

Compute a base ref using the **same logic as SPEC-360 / `change_classifier.py`**:

```
base = merge-base(HEAD, origin/main)  if origin/main verifiable
     else most-recent tag (git describe --tags --abbrev=0)  if available
     else HEAD~1
```

From `base..HEAD` (or `git diff <base>` form consistent with existing `--diff` handling):
- `changed_lines` = sum of added + deleted across `git diff --numstat <base>` (columns 1+2;
  binary files report `-` → skipped).
- file list = `git diff --name-only <base>`.
- `changed_files` = count of that list.

**Fail-safe (binding #9):** if any git step fails (no repo, detached/unknown base, command
error), invoke the validator with `--changed-lines 0 --changed-files 0` and an empty file
list. Zero values mean the floor does not fire — consistent with REQ-377-18 (data unavailable),
never a false CRITICAL.

The new validator runs **unconditionally** (it does not depend on `PY_FILES`), placed with the
all-files validators (alongside `migration_risk`). It uses the standard `run_validator`
wrapper with `required=false` so a crash degrades to SKIP, not a build block (Non-Req §5).

### 4.2 `tier_floor` hoisting into summary.json (binding #10)

After the per-validator pass, the aggregation step (the embedded Python heredoc) must:
- Read each result's top-level `tier_floor` field.
- If `diff_size.json` (or any result) carries a **non-null** `tier_floor`, include a
  top-level `"tier_floor": "<value>"` key in `summary.json`.
- If no result carries a non-null `tier_floor`, omit the key (or set `null`) — the existing
  composite/tier computation is unchanged. The floor does **not** alter `composite_score` or
  the derived `tier`; it is surfaced as a **separate** advisory field the risk-assessor reads.

**Boundary:** hoisting is read-only surfacing. `run_validators.sh` must not let a `tier_floor`
of HIGH change its own exit code or the computed `tier` field (Non-Req §5: floor does not make
the runner exit non-zero). The risk-assessor agent is the actor that promotes the final tier.

---

## 5. Acceptance-criteria traceability

| AC | Covered by |
|---|---|
| AC-377-01..04 | §3.3 floor algorithm (strict `>`, rule-fired derivation) |
| AC-377-05 | §3.3 zero-gating before comparison |
| AC-377-06/07 | §3.5 split advisory (phrase + no tier_floor effect) |
| AC-377-08/09 | §3.2 threshold parse + fallback |
| AC-377-10 | §2.1 + §3.7 top-level `tier_floor` |
| AC-377-11/12 | §3.6 stderr logging, valid stdout JSON |
| AC-377-13 | §3.4 default map matching |
| AC-377-14 | §3.4 `other` catch-all |

---

## 6. Test plan (for unit-test role)

New file `tests/oversight/test_diff_size.py` covering each AC above, plus:
- `HOS_DOMAIN_MAP` well-formed replace, malformed fallback (binding #4).
- `--changed-file-list` empty → domain_count=0, no split, no crash.
- Non-integer CLI numeric input → treated as 0, valid JSON emitted.
- `make_result(tier_floor=...)` top-level key presence; default `None` for existing callers.

---

## 7. HOS self-flag — design change classification

**Change class:** `additive` (new validator + two additive, backward-compatible schema edits;
no existing contract altered, no existing call site changed).

**RISK:** LOW — additive, weight `0.0` keeps the dimension inert in the composite; floor and
split are read-only signals that never block the build or change exit codes.
**CONFIDENCE:** HIGH — bindings are fully specified; the only spec/binding divergence is the
`templates/` prefix omission noted in §3.4, classified `clarifying`.

### Human Review Required

- **§3.4 `templates/` divergence:** Binding #5's default map omits `templates/=templates`
  present in spec REQ-377-13. Per the architect-bindings-govern rule I implement binding #5
  (templates → `other`). This is a `clarifying` divergence surfaced for architect confirmation;
  it does not block implementation and changes no already-approved code (no prior code exists
  against either map). If the architect intends `templates/` to be its own domain, this is a
  one-line addition to the default map with no other impact.
