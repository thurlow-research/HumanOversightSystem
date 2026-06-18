# TECHNICAL-DESIGN-78: Convergence ledger for external reviews

**Status:** Ready for implementation
**Spec:** SPEC-78-convergence-ledger-external-reviews.md
**Issue:** #78
**Date:** 2026-06-17
**Architect bindings:** C1-C7 applied (OQ-2 / thread-suppression excluded pending #400)

---

## 1. Problem

`run_second_review.sh` and `run_panel.sh` track a pass counter but have no
per-finding ledger. A finding triaged as `residual` or `noise` on one pass re-blocks
the verdict on the next pass, forcing another human decision. The self-review loop
already solves this with `validation_logic.py`; this design wires the same primitive
to both external-review scripts.

---

## 2. Scope

### In scope

- `scripts/run_second_review.sh` — load ledger before invocation, record new
  blocking findings after, pass ledger path to verdict computation so
  `new_blocking_count` is ledger-aware.
- `scripts/run_panel.sh` — load panel ledger, record new findings, update
  convergence verdict field (`new_blocking_count`).
- Both scripts gain `--record` and `--reset` subcommands.

### Out of scope (C3 / OQ-2 pending #400)

Thread-suppression on the panel: ledgered findings continue to be posted as PR
threads. `new_blocking_count` gates the exit verdict only.

### Unchanged

- `scripts/oversight/validation_logic.py` — imported as-is; no changes.
- `scripts/oversight/second_review_logic.py` — `aggregate` subcommand is unchanged;
  its output file now carries the `new_blocking_count` header field that
  `validation_logic.py process` already handles.
- `scripts/oversight/panel_logic.py` — not changed.
- Pass caps, reviewer selection, output format, all other behavior.

---

## 3. Architecture

### 3.1 Import contract (C1)

All fingerprinting and ledger I/O is provided by `scripts/oversight/validation_logic.py`.
The two shell scripts call this module via its CLI subcommands:

| subcommand | purpose |
|---|---|
| `validation_logic.py process --file F --ledger L` | Read output file F, compute verdict against ledger L, rewrite header fields including `new_blocking_count` |
| `validation_logic.py record --ledger L --files F1,F2 --class C --disposition D` | Append one JSONL entry to ledger L |

`load_ledger` and `fingerprint` are called internally by `process`; the shell never
calls them directly.

### 3.2 Ledger paths (C5)

| Script | Ledger path |
|---|---|
| `run_second_review.sh` | `.claudetmp/second-review/step<N>-ledger.jsonl` |
| `run_panel.sh` | `.ai-local/panel/pr<N>-ledger.jsonl` |

The asymmetry is intentional: second-review output lives in `.claudetmp` (ephemeral,
gitignored); panel ledger lives in `.ai-local` (persistent across runs, gitignored).

### 3.3 Fingerprint definition (C7)

`fingerprint(finding) = json.dumps([sorted_files, finding_class])` as implemented
in `validation_logic.py`. No finding text is included. The shell never constructs a
fingerprint directly.

### 3.4 `record_ledger_entry` as sole writer (C6)

Both scripts call `validation_logic.py record` (which delegates to
`record_ledger_entry`) for all ledger writes. No script opens the ledger file
directly for writing.

### 3.5 No panel pass counter (C2)

`--reset` on `run_panel.sh` removes `pr<N>-ledger.jsonl` only. There is no pass
counter variable to clear.

---

## 4. Changes to `run_second_review.sh`

### 4.1 Ledger path variable

Add near the top of the variable block:

```bash
LEDGER_FILE=""   # resolved after STEP is confirmed non-empty
```

After the `--step` guard (line 107-110), set:

```bash
LEDGER_FILE="${OUT_DIR}/step${STEP}-ledger.jsonl"
```

### 4.2 `--record` and `--reset` subcommand handling

Add to the `while [[ $# -gt 0 ]]` arg-parse loop BEFORE the existing cases, so
these subcommands short-circuit before the rest of the script runs:

```bash
--record)
    # --record <files> <class> <disposition>
    # Delegates entirely to validation_logic.py record.
    # --step must be set; we parse it from earlier args OR check it was passed.
    _rec_files="${2:-}"; _rec_class="${3:-}"; _rec_disp="${4:-}"
    [[ -z "$STEP" ]] && { echo "Error: --record requires --step <N>" >&2; exit 1; }
    [[ -z "$_rec_files" || -z "$_rec_class" || -z "$_rec_disp" ]] && {
        echo "Usage: --record <files> <class> <disposition>" >&2; exit 1; }
    mkdir -p "$OUT_DIR"
    LEDGER_FILE="${OUT_DIR}/step${STEP}-ledger.jsonl"
    python3 "$(dirname "$0")/oversight/validation_logic.py" record \
        --ledger "$LEDGER_FILE" \
        --files "$_rec_files" \
        --class "$_rec_class" \
        --disposition "$_rec_disp"
    exit $?
    ;;
--reset)
    [[ -z "$STEP" ]] && { echo "Error: --reset requires --step <N>" >&2; exit 1; }
    LEDGER_FILE="${OUT_DIR}/step${STEP}-ledger.jsonl"
    rm -f "$LEDGER_FILE"
    echo "reset: removed ledger for step ${STEP} (${LEDGER_FILE})"
    exit 0
    ;;
```

**Note on arg-parse ordering:** `--step` must be parsed before `--record`/`--reset`
can reference `$STEP`. The implementation does a two-pass parse: a minimal first
pass extracts `--step`, then the main loop handles all other args. Alternatively,
require `--step` to appear before `--record`/`--reset` on the command line (document
this constraint) and do single-pass processing.

The simplest approach (single-pass) is chosen: `--step` is always the first
meaningful flag in documented usage, and the existing loop assigns it immediately.
The `--record`/`--reset` handlers check `$STEP` after the loop completes — i.e.,
they are handled as a post-parse dispatch, not as in-loop early exits.

### 4.3 Post-parse `--record`/`--reset` dispatch

After the `while` loop ends and after the `--step` guard, add:

```bash
LEDGER_FILE="${OUT_DIR}/step${STEP}-ledger.jsonl"

# Post-parse dispatch for --record and --reset (require --step to be set first).
if [[ "${_SUBCMD:-}" == "record" ]]; then
    mkdir -p "$OUT_DIR"
    python3 "$(dirname "$0")/oversight/validation_logic.py" record \
        --ledger "$LEDGER_FILE" \
        --files "${_REC_FILES}" \
        --class "${_REC_CLASS}" \
        --disposition "${_REC_DISP}"
    exit $?
fi
if [[ "${_SUBCMD:-}" == "reset" ]]; then
    rm -f "$LEDGER_FILE"
    echo "reset: removed ledger for step ${STEP} (${LEDGER_FILE})"
    exit 0
fi
```

The arg-parse loop sets `_SUBCMD`, `_REC_FILES`, `_REC_CLASS`, `_REC_DISP` when
`--record`/`--reset` is encountered. This keeps `--step` already parsed.

### 4.4 Header field: `new_blocking_count`

Add `new_blocking_count: 0` to the initial header block written to `$OUTFILE` (line 300-311 in current file):

```bash
printf "new_blocking_count: 0\n"
```

### 4.5 Verdict aggregation: replace `second_review_logic aggregate` with `validation_logic process`

**Current** (line 669):

```bash
python3 "$(dirname "$0")/oversight/second_review_logic.py" aggregate --file "$OUTFILE"
```

**New:**

```bash
python3 "$(dirname "$0")/oversight/second_review_logic.py" aggregate --file "$OUTFILE"
python3 "$(dirname "$0")/oversight/validation_logic.py" process \
    --file "$OUTFILE" --ledger "$LEDGER_FILE"
```

`second_review_logic aggregate` still runs first — it rewrites `verdict`,
`highest_severity`, and `unresolved_findings` (its existing header fields).
`validation_logic process` then runs second and rewrites `new_blocking_count` (and
re-writes `verdict` to be ledger-aware: `approve` when `new_blocking_count == 0`).

**Why two calls?** `second_review_logic.py` owns prose-vs-JSON classification and
the `unresolved_findings` count. `validation_logic.py` owns the ledger-aware verdict.
Merging them into one call would violate C1 (reimplementing logic that belongs in
`validation_logic.py`) and violate the existing SPEC-331 architectural boundary.
The two-call sequence is correct and intentional.

---

## 5. Changes to `run_panel.sh`

### 5.1 Ledger path variable

Add near the top, after `PR` is resolved (after line 206):

```bash
PANEL_LEDGER=".ai-local/panel/pr${PR}-ledger.jsonl"
```

### 5.2 `--record` and `--reset` subcommand handling

Add to the `while [[ $# -gt 0 ]]` arg-parse loop (before the `--dry-run` case):

```bash
--record)
    _rec_files="${2:-}"; _rec_class="${3:-}"; _rec_disp="${4:-}"; shift 4 || shift
    _PANEL_SUBCMD="record"
    _REC_FILES="$_rec_files"; _REC_CLASS="$_rec_class"; _REC_DISP="$_rec_disp"
    ;;
--reset)
    _PANEL_SUBCMD="reset"; shift
    ;;
```

Post-parse dispatch (after `PR` and `PANEL_LEDGER` are resolved):

```bash
if [[ "${_PANEL_SUBCMD:-}" == "record" ]]; then
    mkdir -p ".ai-local/panel"
    python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/oversight/validation_logic.py" record \
        --ledger "$PANEL_LEDGER" \
        --files "${_REC_FILES}" \
        --class "${_REC_CLASS}" \
        --disposition "${_REC_DISP}"
    exit $?
fi
if [[ "${_PANEL_SUBCMD:-}" == "reset" ]]; then
    rm -f "$PANEL_LEDGER"
    echo "reset: removed panel ledger for PR #${PR} (${PANEL_LEDGER})"
    exit 0
fi
```

**Note on path resolution:** `run_panel.sh` resolves `$PANEL_LOGIC` via
`"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/oversight/panel_logic.py"`
when run from the project root. `validation_logic.py` sits at the same level and
uses the same resolution pattern.

### 5.3 `new_blocking_count` verdict field

After the arbiter/corroboration ranking section (after line 502 where `arbiter.json`
is written), add a ledger-aware verdict computation:

```bash
# ── Ledger-aware convergence verdict (SPEC-78) ──────────────────────────────
# new_blocking_count: how many tier1 findings are NOT already in the ledger.
# This gates the panel's exit verdict; it does NOT suppress thread posting
# (OQ-2 / C3 pending human clearance on #400).
PANEL_VERDICT_FILE="$RUN_DIR/panel-verdict.json"
TIER1_BLOCKING=$(printf '%s' "$FINDINGS" \
    | jq '[.[] | select(.severity == "tier1")] | length' 2>/dev/null || echo 0)

if [[ -f "$(dirname "${BASH_SOURCE[0]}")/scripts/oversight/validation_logic.py" ]]; then
    VL_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/oversight/validation_logic.py"
elif [[ -f "scripts/oversight/validation_logic.py" ]]; then
    VL_PY="scripts/oversight/validation_logic.py"
else
    VL_PY=""
fi

NEW_BLOCKING_COUNT="$TIER1_BLOCKING"
if [[ -n "$VL_PY" ]]; then
    # Write a synthetic second-review-style output that validation_logic can process.
    # The panel does not use the second-review output format, so we compute
    # new_blocking_count directly from the ledger using load_ledger + fingerprint.
    NEW_BLOCKING_COUNT=$(python3 - <<PYEOF
import json, sys
sys.path.insert(0, "$(dirname "$VL_PY")")
from validation_logic import load_ledger, fingerprint, BLOCKING_SEVERITIES

ledger = load_ledger("$PANEL_LEDGER")

# Map panel severity tiers to blocking severity names for ledger lookup.
# tier1 findings are treated as blocking for convergence purposes.
PANEL_BLOCKING_TIERS = {"tier1"}

findings_raw = "$RUN_DIR/arbiter.json"
try:
    with open(findings_raw) as fh:
        data = json.load(fh)
    findings = data.get("findings", [])
except Exception:
    print(0)
    sys.exit(0)

new_blocking = 0
for f in findings:
    sev = f.get("severity", "")
    if sev not in PANEL_BLOCKING_TIERS:
        continue
    # Build a finding dict compatible with validation_logic.fingerprint:
    # uses 'file' (singular) and 'category'/'type' for the class.
    fp_finding = {
        "file": f.get("file", ""),
        "category": f.get("lens", ""),   # panel uses lens as the class proxy
    }
    fp = fingerprint(fp_finding)
    if fp not in ledger:
        new_blocking += 1

print(new_blocking)
PYEOF
    ) || NEW_BLOCKING_COUNT="$TIER1_BLOCKING"
fi

info "convergence: tier1=$TIER1_COUNT new_blocking=${NEW_BLOCKING_COUNT} (ledger: $PANEL_LEDGER)"
```

**Note on panel finding structure vs. `validation_logic.fingerprint`:**
Panel findings use `file`, `lens` (reviewer lens), and `reviewer`. The
`fingerprint()` function uses `(sorted files, category/type)`. The lens is the
closest equivalent to a finding category for the panel context. The Python inline
above maps `lens` to `category` for fingerprinting, which is consistent with C7.

### 5.4 Panel exit verdict

After the "Panel complete" echo at the end, add:

```bash
# Exit code reflects convergence (SPEC-78 R4).
# new_blocking_count > 0 on a non-dry-run → exit 3 (escalation, matches second-review convention).
if [[ $DRY_RUN -eq 0 && "${NEW_BLOCKING_COUNT:-0}" -gt 0 ]]; then
    echo "Panel verdict: ESCALATE — ${NEW_BLOCKING_COUNT} new blocking finding(s) (un-ledgered tier1)"
    exit 3
fi
```

---

## 6. Output file changes

### `run_second_review.sh`

Add `new_blocking_count: 0` to the initial header block. `validation_logic process`
rewrites it after the verdict is computed.

### `run_panel.sh`

The panel does not produce a second-review-style output file. The
`new_blocking_count` is logged to stdout and drives the exit code. It is also
written to `$RUN_DIR/panel-verdict.json` for the oversight-evaluator:

```json
{
  "new_blocking_count": <N>,
  "tier1_count": <M>,
  "ledger": "<path>",
  "pr": <PR>
}
```

---

## 7. Acceptance criteria mapping

| AC | Covered by |
|---|---|
| AC-1: second-review ledgered `high` → `new_blocking_count: 0` + `approve` | §4.5 — `validation_logic process` reads ledger |
| AC-2: panel ledgered `critical` → `new_blocking_count: 0` + `approve` | §5.3 — inline Python reads ledger |
| AC-3: `run_second_review.sh --record "app/views.py" authorization filed:#99` writes one JSONL entry | §4.3 — delegates to `validation_logic.py record` |
| AC-4: `run_panel.sh --reset` removes the PR-scoped ledger | §5.2 — `rm -f "$PANEL_LEDGER"` |
| AC-5: both scripts' output files contain `new_blocking_count: <N>` | §4.4 (second-review header) + §5.3 (panel verdict JSON) |

---

## 8. Files changed

| File | Change |
|---|---|
| `scripts/run_second_review.sh` | Add `LEDGER_FILE`, `--record`/`--reset` dispatch, `new_blocking_count` header field, second `validation_logic process` call after `second_review_logic aggregate` |
| `scripts/run_panel.sh` | Add `PANEL_LEDGER`, `--record`/`--reset` dispatch, inline Python ledger-aware `new_blocking_count` computation, exit-3 on new blocking findings |
| `scripts/oversight/validation_logic.py` | No changes |
| `scripts/oversight/second_review_logic.py` | No changes |
| `scripts/oversight/panel_logic.py` | No changes |

---

## 9. Not implemented (pending human clearance)

OQ-2 / C3: suppression of ledgered findings from PR thread posting on panel re-runs.
Tracked on GitHub issue #400. Implementation deferred until human approves the
user-visible behavior change.
