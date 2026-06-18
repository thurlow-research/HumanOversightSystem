# Technical Design — SPEC-373: Task-Class Deterministic Risk-Tier Floor

**Document type:** Technical design
**Status:** Ready for coder (architect ruling: GO; bindings final)
**Issue:** #373
**Spec:** `docs/specs/SPEC-373-task-class-risk-floor.md`
**Architect bindings:** 8 bindings, all final (incorporated below verbatim where load-bearing)
**Author:** technical-design
**Date:** 2026-06-17

---

## 1. Scope and intent

Add a deterministic risk-tier floor keyed on task class to the RN validator's
emitted result. Maintenance task classes (`refactor`, `chore`) carry empirically
higher breaking-change rates than their structural complexity predicts; the floor
prevents a structurally-LOW maintenance change from being reviewed at LOW intensity.

Exactly two artifacts change:

1. `scripts/oversight/validators/rn_calculator.py` — add a pure floor function and
   a `--task-class` CLI argument. The RN calculation (`analyse_files()`) is **not**
   touched.
2. `scripts/oversight/run_validators.sh` — add the R1a/R1b shell detection pre-step
   and forward the resolved value via `--task-class`.

No change to `schema.py`, the RN formula, validator weights, tier thresholds, or any
other validator. The floor affects only the **RN-local tier** recorded in this
validator's output; it does **not** modify `summary.json`'s composite tier (that
remains the risk-assessor's responsibility, read downstream from `tier_floor`).

---

## 2. Component map

| # | Component | File | Kind |
|---|-----------|------|------|
| 1 | `apply_task_class_floor(result, task_class)` | rn_calculator.py | new pure function |
| 2 | `--task-class` argparse | rn_calculator.py | CLI surface change in `main()` |
| 3 | floor call site | rn_calculator.py | one call in `main()` after `analyse_files()` |
| 4 | R1a/R1b detection pre-step | run_validators.sh | new shell block before RN invocation |
| 5 | `--task-class` forwarding | run_validators.sh | conditional arg append on RN call |

---

## 3. rn_calculator.py — contract

### 3.1 `apply_task_class_floor(result: dict, task_class: str | None) -> dict`

**Signature (binding 1):** pure function. Takes the result dict returned by
`analyse_files()` and the detected task class. Returns a modified result dict. Does
not call `analyse_files()`, does not read git/gh, does not read the environment.

**Inputs:**
- `result` — the envelope from `analyse_files()` (or the no-files envelope). Has
  `result["score"]` (float 0.0–1.0) and `result["raw_value"]` (a dict).
- `task_class` — one of `"feat"`, `"fix"`, `"refactor"`, `"chore"`, or `None`/any
  other string (treated as unknown).

**Algorithm:**

1. **Source label (binding 3):** the function records *what* the class is but the
   detection source is supplied by the caller via the new `--task-class-source`
   handling in `main()` (see 3.2). `apply_task_class_floor` itself receives only the
   class and the source through the result-building in `main()`; to keep the function
   pure and single-responsibility, it sets the five `raw_value` fields and the
   top-level `tier_floor`, and `main()` injects the source string before/after. **Per
   binding 3 the five fields live in `raw_value`, not top-level.**

2. **Known-class set:** `{"feat", "fix", "refactor", "chore"}`. If `task_class` is not
   in this set (None, empty, or any other token) → **fail-open**: set
   `raw_value["task_class"] = None`, `raw_value["task_class_source"] = None`,
   `raw_value["floor_applied"] = False`, `raw_value["pre_floor_tier"] = None`,
   `raw_value["post_floor_tier"] = None`, leave `result["tier_floor"]` as-is (None).
   Return `result` unchanged otherwise. No `error` field is set for an unknown class.

3. **Known class path:** compute `local_tier = score_to_tier(result["score"])` using
   `schema.score_to_tier` (binding 2). This is `pre_floor_tier`.

4. **Floor rule (binding 2):** if `task_class in {"refactor", "chore"}` **and**
   `local_tier == "LOW"` → `floor_applied = True`, `post_floor_tier = "MEDIUM"`.
   Otherwise → `floor_applied = False`, `post_floor_tier = local_tier`.

5. **Write fields into `raw_value` (binding 3):**
   - `task_class` = the class string
   - `task_class_source` = the source (passed in via `main()`)
   - `floor_applied` = bool from step 4
   - `pre_floor_tier` = `local_tier`
   - `post_floor_tier` = from step 4

6. **Top-level `tier_floor` (binding 4):** if `floor_applied` is True →
   `result["tier_floor"] = "MEDIUM"`. Otherwise leave it None (the `make_result`
   default). Use the existing `tier_floor` key (added by SPEC-377; present in
   `make_result`'s envelope).

7. Return `result`.

**Boundary:** the function never mutates `result["score"]` and never changes the
`dimension`. It only adds five `raw_value` keys and conditionally sets `tier_floor`.

**Note on signature vs. source:** to honor binding 1 (`apply_task_class_floor(result,
task_class)` — two args) while still recording `task_class_source` (binding 3), the
function signature stays two-arg and `main()` sets
`raw_value["task_class_source"]` immediately after the call (the source is a
caller-side fact, not a floor-logic fact). Equivalently the function may accept an
optional `source` kwarg with default `None`; the binding fixes the two positional
args, which is preserved either way. The implementation uses an optional `source`
kwarg defaulting to `None` so the call site is a single statement.

### 3.2 `--task-class` CLI argument (binding 5)

`main()` currently hand-parses `sys.argv` for `--files`. Binding 5 requires an
argparse `--task-class`. To avoid breaking the existing positional/`--files` handling,
`main()` pre-extracts `--task-class <value>` (and an internal `--task-class-source
<value>`, see 3.3) from `sys.argv` before the existing file parsing, OR migrates to
argparse with `--files` as `nargs="*"` and positional remainder. The binding says
"add to rn_calculator.py's argparse" — implement a minimal argparse pass that:

- accepts `--task-class` (optional, no default, `type=str`)
- accepts `--task-class-source` (optional, no default, `type=str`) — set by the shell
  pre-step so the source label is accurate; if absent, source defaults to `None`
- collects everything else as files (positional + `--files`)

Unknown classes **fail open** (binding 5 + binding 8): all five new fields null/false,
no `tier_floor`, exit 0, no `error`.

### 3.3 Call site (binding 1, 3)

In `main()`, **after** `result = analyse_files(files)` (and after the no-files
`make_result` branch — the floor fields must be present on every output per AC3a):

```
result = apply_task_class_floor(result, task_class, source=task_class_source)
```

The floor must be applied to the no-files / parse-error result too, so the five fields
are always present (AC3a). For those degenerate results `score` is `0.0` → `local_tier`
is `LOW` → if a maintenance class was supplied, the floor still fires (MEDIUM). This is
acceptable and correct: an unparseable refactor is still a maintenance change.

---

## 4. run_validators.sh — contract

### 4.1 Detection pre-step (binding 6, 7, 8)

Inserted **before** the `run_validator "risk_number" ...` invocation (currently
line 174). Bash 3.2 compatible — no `${var,,}`, use `tr '[:upper:]' '[:lower:]'`.

**R1a — conventional-commit prefix (binding 6):**
```
TASK_CLASS=$(git log -1 --format=%s 2>/dev/null \
    | grep -oE '^(feat|fix|refactor|chore)(\(.+\))?(!)?:' \
    | grep -oE '^(feat|fix|refactor|chore)' \
    | tr '[:upper:]' '[:lower:]' || true)
TASK_CLASS_SOURCE=""
[[ -n "$TASK_CLASS" ]] && TASK_CLASS_SOURCE="commit_prefix"
```

**R1b — issue label fallback (binding 6):** only when `TASK_CLASS` is empty **and**
`ISSUE_NUMBER` is set in the environment. Fail-open with `|| true` everywhere.
```
if [[ -z "$TASK_CLASS" && -n "${ISSUE_NUMBER:-}" ]]; then
    TASK_CLASS=$(gh issue view "$ISSUE_NUMBER" --json labels \
        --jq '.labels[].name | select(test("^(feat|fix|refactor|chore)$"; "i"))' 2>/dev/null \
        | head -1 | tr '[:upper:]' '[:lower:]' || true)
    [[ -n "$TASK_CLASS" ]] && TASK_CLASS_SOURCE="issue_label"
fi
```

**Spec vs binding note:** spec R3 names the source `"github_label"`; architect binding 3
names the enum `"issue_label"`. **The architect binding governs** (it is the later,
final ruling). The emitted `task_class_source` value is `"issue_label"`. (This is a
clarifying divergence from the spec text; recorded here so the test roles assert the
binding value, not the spec value.)

### 4.2 Forwarding (binding 5, 6)

Pass `--task-class` to the RN validator **only if** `TASK_CLASS` is non-empty. Because
`run_validator` takes a fixed 4-positional prefix (`NAME SCRIPT TIMEOUT REQUIRED`) then
`args...`, and the file list must follow, build a small extra-args array:

```
RN_EXTRA=()
if [[ -n "$TASK_CLASS" ]]; then
    RN_EXTRA+=(--task-class "$TASK_CLASS")
    [[ -n "$TASK_CLASS_SOURCE" ]] && RN_EXTRA+=(--task-class-source "$TASK_CLASS_SOURCE")
fi
```

Then the existing RN call becomes (preserving `set -u` empty-array safety — guard the
`RN_EXTRA` expansion the same way the file list and `DS_FILE_LIST` are guarded):

```
if [[ ${#RN_EXTRA[@]} -gt 0 ]]; then
    run_validator "risk_number" "$VALIDATORS_DIR/rn_calculator.py" 60 false \
        "${RN_EXTRA[@]}" "${PY_FILES[@]}"
else
    run_validator "risk_number" "$VALIDATORS_DIR/rn_calculator.py" 60 false \
        "${PY_FILES[@]}"
fi
```

The flags must precede the file list because the validator's file filter accepts
positional file paths; the argparse pre-pass strips the flags regardless of position,
but flag-first keeps it unambiguous and matches the diff_size precedent.

**Boundary:** the pre-step must never abort the run. `set -euo pipefail` is active, so
every command in the pre-step ends in `|| true` (or is inside a `[[ ]]` test) so a
non-zero git/gh exit cannot kill the script. This is binding 8 (total fail-open).

---

## 5. Acceptance-criteria → implementation trace

| AC | Mechanism |
|----|-----------|
| AC1a–c | R1a grep pipeline (4.1) |
| AC1d | `build:` not in alternation → `TASK_CLASS` empty → null |
| AC1e | R1b gh label lookup (4.1), source `issue_label` |
| AC1f | no prefix, no `ISSUE_NUMBER` → null |
| AC1g | `--task-class refactor` passed directly → `main()` argparse, no git/gh |
| AC2a–b | floor rule step 4 (refactor/chore + LOW → MEDIUM) |
| AC2c–d | local_tier MEDIUM/HIGH → floor_applied False, post == pre |
| AC2e–f | feat/fix → floor_applied False even at LOW |
| AC3a | floor applied to every result incl. no-files branch (3.3) |
| AC3b | floor_applied True path sets source/pre/post |
| AC3c | unknown class → all five null/false (3.1 step 2) |
| AC3d | known, no floor → pre==post==local_tier, floor_applied False |
| AC4a–b | total fail-open (4.1 `|| true`, 3.1 step 2), exit 0, no error |
| AC4c | no `--task-class` → unknown path → identical non-floor output |

---

## 6. Boundaries and invariants

- `analyse_files()` is unchanged; RN computation remains testable in isolation.
- No git/gh inside Python (binding 6/7; spec §5).
- No environment variable read inside Python (binding 5; spec §5). `ISSUE_NUMBER` is
  read only by the shell pre-step.
- `result["score"]` is never modified by the floor.
- `summary.json` composite tier is unchanged by this validator; only `tier_floor`
  surfaces (existing SPEC-377 hoist at run_validators.sh lines 306–325 already lifts a
  non-null `tier_floor` to the summary top level — the RN floor will flow through that
  existing path with no change needed there).
- Bash 3.2 compatibility throughout (binding 7).

---

## 7. Human review flag

CONFIDENCE: HIGH
RISK: LOW

Change classification: **additive** — new optional CLI arg, new pure function, new
shell pre-step. No existing contract field changes type or meaning; existing call sites
(no `--task-class`) produce byte-identical output to today on non-floor paths (AC4c).
The one clarifying divergence (`issue_label` vs spec's `github_label`) is recorded in
4.1 and governed by the binding. No structural change → no human gate required at the
design stage.
