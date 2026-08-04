#!/usr/bin/env bash
# run_validators.sh — orchestrate all risk assessment validators for a file set.
#
# Runs every validator in scripts/oversight/validators/ on the provided files,
# collects JSON output, and writes results to .claudetmp/oversight/validators/.
# The risk assessor agent reads those files to synthesize the composite score
# and inspection brief.
#
# Usage:
#   ./scripts/oversight/run_validators.sh file.py [file2.py ...]
#   ./scripts/oversight/run_validators.sh --step 3    (reads step 3 changed files from git)
#   ./scripts/oversight/run_validators.sh --diff HEAD~1
#
# Output:
#   .claudetmp/oversight/validators/<dimension>.json   per-validator results
#   .claudetmp/oversight/validators/summary.json       all results + composite score
#
# The risk assessor agent invokes this, reads the summary, and produces
# the inspection brief + final risk tier.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATORS_DIR="$SCRIPT_DIR/validators"
OUT_DIR=".claudetmp/oversight/validators"

# shellcheck source=scripts/oversight/ensure_venv.sh
source "$SCRIPT_DIR/ensure_venv.sh"
PYTHON="${PYTHON:-$OVERSIGHT_PYTHON}"

# Root-cause of #1266: static_analysis.py/complexity_metrics.py invoke
# bandit/radon via `subprocess.run(["bandit", ...])` — a PATH lookup, not a
# Python import. Validators run as `$PYTHON script.py` (the venv interpreter
# invoked directly, never `source .../activate`), so $VENV_BIN was never on
# PATH and subprocess couldn't find console scripts that ARE pip-installed
# in the oversight venv. Every Python changeset silently dropped
# static_analysis/complexity from the composite score with no visible error.
# Guard against a leading `:` in PATH (treated as cwd by POSIX shells) if
# VENV_BIN were ever empty — not reachable today (ensure_venv.sh always
# derives it as an absolute path) but cheap to make structurally impossible.
[[ -n "$VENV_BIN" ]] && export PATH="$VENV_BIN:$PATH"

# shellcheck source=scripts/oversight/run_with_retry.sh
source "$SCRIPT_DIR/run_with_retry.sh"

# shellcheck source=scripts/oversight/lib/detect_stack.sh
source "$SCRIPT_DIR/lib/detect_stack.sh"

# Configurable defaults (override via env)
VALIDATOR_TIMEOUT="${VALIDATOR_TIMEOUT:-60}"       # seconds per attempt
VALIDATOR_RETRIES="${VALIDATOR_RETRIES:-2}"        # retries after first attempt
NETWORK_TIMEOUT="${NETWORK_TIMEOUT:-30}"           # shorter for network-dependent validators

FILES=()
STEP=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --step)
            STEP="$2"; shift 2
            ;;
        --diff)
            DIFF_REF="$2"; shift 2
            # Collect the FULL changed-file list — NOT just *.py (#981). ALL_FILES
            # drives ip_check (license/provenance gate) and issue_query, whose
            # signals key off dependency manifests (requirements*.txt, pyproject.toml,
            # package.json) that never end in .py. Filtering to .py here blinded the
            # release gate to manifest changes. The .py-only subset is derived below
            # into PY_FILES for the Python-only validators.
            # bash 3.2 (macOS default) has no `mapfile` — use a portable read loop.
            FILES=()
            while IFS= read -r _f; do
                [[ -n "$_f" ]] && FILES+=("$_f")
            done < <(git diff --name-only "$DIFF_REF" 2>/dev/null || true)
            ;;
        *)
            FILES+=("$1"); shift
            ;;
    esac
done

# Defensive: if the caller passed every path as ONE whitespace/newline-joined
# argument (a common quoting footgun, e.g. `run_validators.sh "$FILES"` or a
# shell that doesn't word-split), the list would otherwise collapse to a single
# non-existent "file", every per-file validator would no-op, and the run would
# fail-close to a FALSE CRITICAL. Detect that exact shape and re-split.
if [[ ${#FILES[@]} -eq 1 && "${FILES[0]}" =~ [[:space:]] && ! -e "${FILES[0]}" ]]; then
    echo "run_validators: received one whitespace-joined argument — re-splitting into separate paths" >&2
    _joined="${FILES[0]}"
    FILES=()
    for _f in $_joined; do
        [[ -n "$_f" ]] && FILES+=("$_f")
    done
fi

# Filter to existing Python files
PY_FILES=()
ALL_FILES=()
# Parallel JS/TS/Astro lane (#1034, ADR-032). On an all-.astro/.ts/.js changeset
# the PY_FILES gate skipped 8 of 12 scoring dimensions, so the composite signal
# went largely dark. JS_FILES routes those files to the *_js validators without
# touching the Python path: the ALL_FILES/PY_FILES derivation below is unchanged,
# and on a Python-only changeset JS_FILES stays empty, so every downstream
# dispatch and argv is identical (AC-2).
# Lowercase extensions only, mirroring the `*.py` match (DQ-1).
JS_FILES=()
JS_EXTS_RE='\.(ts|tsx|js|jsx|astro|mjs|cjs)$'
# package.json is additive (not part of JS_FILES — it must not reach the
# tree-sitter validators) so hallucination_surface_js.py's dependency-existence
# check (S7, #1063) still fires on a package.json-only bump with no other JS
# touched, without changing JS_FILES membership or JS_EXTS_RE (AC-2 untouched).
PKG_JSON_FILES=()
for f in ${FILES[@]+"${FILES[@]}"}; do  # bash 3.2: unguarded expansion crashes on empty array
    ALL_FILES+=("$f")
    [[ "$f" == *.py && -f "$f" ]] && PY_FILES+=("$f")
    [[ "$f" =~ $JS_EXTS_RE && -f "$f" ]] && JS_FILES+=("$f")
    [[ "$(basename "$f")" == "package.json" && -f "$f" ]] && PKG_JSON_FILES+=("$f")
done

if [[ ${#ALL_FILES[@]} -eq 0 ]]; then
    echo "run_validators: no files specified"
    echo "Usage: $0 file.py [file2.py ...]"
    # Write a durable CRITICAL summary so downstream agents have an artifact to read
    mkdir -p "$OUT_DIR"
    PYTHONSAFEPATH=1 "$PYTHON" -c "
import json; from pathlib import Path
summary = {'composite_score': 1.0, 'tier': 'CRITICAL', 'validator_count': 0,
           'successful_validators': 0,
           'error': 'No files provided to run_validators.sh — defaulting to CRITICAL (fail-closed)'}
Path('$OUT_DIR/summary.json').write_text(json.dumps(summary, indent=2))
print('CRITICAL summary written to $OUT_DIR/summary.json')
" 2>/dev/null || true
    exit 1
fi

# Testability seam (#981): with RUN_VALIDATORS_FILELIST_ONLY set, emit the
# resolved ALL_FILES / PY_FILES split and exit BEFORE any validator runs. Lets
# tests pin the --diff file collection (dependency manifests must reach ALL_FILES,
# and only *.py may reach PY_FILES) without the heavy/network validator run.
# Off by default; no effect on the real pipeline.
# JS_FILES lines are APPENDED after the existing emissions (#1034) so seam
# parsers written against ALL_FILES/PY_FILES are unaffected.
if [[ -n "${RUN_VALIDATORS_FILELIST_ONLY:-}" ]]; then
    for _af in ${ALL_FILES[@]+"${ALL_FILES[@]}"}; do printf 'ALL_FILES\t%s\n' "$_af"; done
    for _pf in ${PY_FILES[@]+"${PY_FILES[@]}"}; do printf 'PY_FILES\t%s\n' "$_pf"; done
    for _jf in ${JS_FILES[@]+"${JS_FILES[@]}"}; do printf 'JS_FILES\t%s\n' "$_jf"; done
    for _kf in ${PKG_JSON_FILES[@]+"${PKG_JSON_FILES[@]}"}; do printf 'PKG_JSON_FILES\t%s\n' "$_kf"; done
    exit 0
fi

# Tool preflight (D1, ADR-032; extended to Python analysis tools by #1266): a
# depended-on-but-missing tool now hard-fails here instead of letting each
# validator/gate silently SKIP. Runs AFTER the RUN_VALIDATORS_FILELIST_ONLY
# seam above, so the byte-identical regression harness in a bare tmp repo
# never triggers a tool check (AC-2), and BEFORE the validator loop so a
# missing tool blocks scoring rather than producing partial/misleading
# signal. No-op outside a JS/Astro project and outside a Python changeset
# (AC-4). bandit/radon are required only when PY_FILES is non-empty — same
# changeset-scoped skip-not-fail semantics as the JS_FILES validator gate
# below, not a repo-wide marker, so a JS-only or docs-only changeset is never
# blocked on a Python toolchain it will never invoke.
HAS_PY_FILES=""
if [[ ${#PY_FILES[@]} -gt 0 ]]; then
    HAS_PY_FILES=1
fi
if ! tool_preflight_or_fail "$HAS_PY_FILES"; then
    mkdir -p "$OUT_DIR"
    PYTHONSAFEPATH=1 "$PYTHON" -c "
import json; from pathlib import Path
summary = {'composite_score': 1.0, 'tier': 'CRITICAL', 'validator_count': 0,
           'successful_validators': 0,
           'error': 'Required tool(s) missing for this project (D1, ADR-032) — see stderr for detail'}
Path('$OUT_DIR/summary.json').write_text(json.dumps(summary, indent=2))
print('CRITICAL summary written to $OUT_DIR/summary.json')
" 2>/dev/null || true
    exit 1
fi

mkdir -p "$OUT_DIR"
# Clear stale validator results from prior runs — old JSON files would contaminate the score.
# Preserve gate-results.json: run_gates.sh runs earlier in the pipeline and writes its record
# here; the oversight-evaluator's REQ-GATE-NN-08/16 checks (via gate_compliance.py) read it.
# A blanket `rm -f *.json` erased that evidence, fail-opening the gate-compliance invariant (#980).
find "$OUT_DIR" -maxdepth 1 -type f -name '*.json' -not -name 'gate-results.json' -delete 2>/dev/null || true

echo "=== Oversight validators: ${#ALL_FILES[@]} file(s) ==="
echo "Output: $OUT_DIR/"
echo ""

RESULTS=()

# Counters for summary line
VALIDATOR_SUCCEEDED=0
VALIDATOR_SKIPPED=0
VALIDATOR_FAILED=0

run_validator() {
    local name="$1"
    local script="$2"
    local timeout="${3:-$VALIDATOR_TIMEOUT}"
    local is_required="${4:-false}"
    shift 4
    local args=("$@")

    local outfile="$OUT_DIR/${name}.json"

    if [[ ! -f "$script" ]]; then
        printf "  \033[33m⏸\033[0m  %-28s SKIP (script not found)\n" "$name"
        VALIDATOR_SKIPPED=$(( VALIDATOR_SKIPPED + 1 ))
        return
    fi

    local tmpout
    tmpout=$(mktemp /tmp/validator_XXXXXX)

    # Unit of work — one attempt. Sees name/script/args/timeout/tmpout via bash
    # dynamic scope (it is called from run_with_retry, which we call from here).
    # PYTHONPATH includes the validators dir so `from schema import` works.
    # with_timeout (from run_with_retry.sh) returns 124 on timeout.
    _validator_unit() {
        PYTHONPATH="$VALIDATORS_DIR${PYTHONPATH:+:$PYTHONPATH}" \
            with_timeout "$timeout" "$PYTHON" "$script" "${args[@]}" > "$tmpout" 2>/dev/null
    }

    local rc=0
    run_with_retry "$name" "$VALIDATOR_RETRIES" "$is_required" _validator_unit && rc=0 || rc=$?

    if [[ $rc -eq 0 ]]; then
        local OUTPUT
        OUTPUT=$(cat "$tmpout")
        echo "$OUTPUT" > "$outfile"
        local SCORE
        SCORE=$(echo "$OUTPUT" | PYTHONSAFEPATH=1 "$PYTHON" -c \
            "import json,sys; d=json.load(sys.stdin); print(f\"{d.get('score',0):.2f}\")" 2>/dev/null || echo "?")
        printf "  %-30s score=%s\n" "$name" "$SCORE"
        RESULTS+=("$name")
        VALIDATOR_SUCCEEDED=$(( VALIDATOR_SUCCEEDED + 1 ))
    else
        # run_with_retry already printed the ✘/⏸ line and emitted the audit event.
        echo '{"dimension":"'"$name"'","score":0,"error":"validator exhausted retries"}' > "$outfile"
        if [[ $rc -eq 1 ]]; then
            VALIDATOR_FAILED=$(( VALIDATOR_FAILED + 1 ))
        else
            VALIDATOR_SKIPPED=$(( VALIDATOR_SKIPPED + 1 ))
        fi
    fi
    rm -f "$tmpout"
}

# Run all validators
#   Signature: run_validator NAME SCRIPT TIMEOUT_SEC REQUIRED [args...]
#   REQUIRED=false: timeout/crash → SKIP (optional); all validators are optional individually
#   Network-dependent validators get shorter timeout; heavy ones get longer

# Task-class detection pre-step (#373). Resolves the conventional-commit task
# class (R1a) and, only as a fallback, the GitHub issue label (R1b). The result
# is forwarded to rn_calculator.py via --task-class, which applies the risk-tier
# floor. Detection lives HERE, never inside the Python validator (binding 6/7).
# Fail-open is total: every command ends in `|| true` or sits in a `[[ ]]` test
# so a non-zero git/gh exit can never abort the run under `set -euo pipefail`
# (binding 8). Bash 3.2 safe: lowercasing via `tr`, never `${var,,}` (binding 7).
TASK_CLASS=""
TASK_CLASS_SOURCE=""
# R1a: conventional-commit prefix in the HEAD subject line.
TASK_CLASS=$(git log -1 --format=%s 2>/dev/null \
    | grep -oE '^(feat|fix|refactor|chore)(\(.+\))?(!)?:' \
    | grep -oE '^(feat|fix|refactor|chore)' \
    | tr '[:upper:]' '[:lower:]' || true)
if [[ -n "$TASK_CLASS" ]]; then
    TASK_CLASS_SOURCE="commit_prefix"
fi
# R1b fallback: GitHub issue label — only when R1a was empty AND ISSUE_NUMBER set.
if [[ -z "$TASK_CLASS" && -n "${ISSUE_NUMBER:-}" ]]; then
    TASK_CLASS=$(gh issue view "$ISSUE_NUMBER" --json labels \
        --jq '.labels[].name | select(test("^(feat|fix|refactor|chore)$"; "i"))' 2>/dev/null \
        | head -1 | tr '[:upper:]' '[:lower:]' || true)
    if [[ -n "$TASK_CLASS" ]]; then
        TASK_CLASS_SOURCE="issue_label"
    fi
fi
# Build the extra-args array forwarded to the RN validator (flags first, then files).
RN_EXTRA=()
if [[ -n "$TASK_CLASS" ]]; then
    RN_EXTRA+=(--task-class "$TASK_CLASS")
    [[ -n "$TASK_CLASS_SOURCE" ]] && RN_EXTRA+=(--task-class-source "$TASK_CLASS_SOURCE")
fi

if [[ ${#PY_FILES[@]} -gt 0 ]]; then
    # bash 3.2 errors on "${arr[@]}" for an empty array under set -u — guard RN_EXTRA.
    if [[ ${#RN_EXTRA[@]} -gt 0 ]]; then
        run_validator "risk_number"  "$VALIDATORS_DIR/rn_calculator.py"         60 false "${RN_EXTRA[@]}" "${PY_FILES[@]}"
    else
        run_validator "risk_number"  "$VALIDATORS_DIR/rn_calculator.py"         60 false "${PY_FILES[@]}"
    fi
    run_validator "complexity"       "$VALIDATORS_DIR/complexity_metrics.py"    60 false "${PY_FILES[@]}"
    run_validator "function_metrics" "$VALIDATORS_DIR/function_metrics.py"      60 false "${PY_FILES[@]}"
    run_validator "n1_queries"       "$VALIDATORS_DIR/n1_detector.py"           60 false "${PY_FILES[@]}"
    run_validator "static_analysis"  "$VALIDATORS_DIR/static_analysis.py"      120 false "${PY_FILES[@]}"
    run_validator "hallucination"    "$VALIDATORS_DIR/hallucination_surface.py" 60 false "${PY_FILES[@]}"
fi

# JS/TS/Astro lane (#1034) — mirrors the Python dispatch above on JS_FILES.
# The `_js` NAME suffix gives each JS validator its own outfile (complexity_js.json),
# so nothing overwrites the Python results and the aggregator — which globs *.json
# and keys off the `dimension` field, not the filename — needs no change (S1.5).
# The *_js.py scripts land in S4–S9; until then run_validator SKIPs each missing
# script cleanly, so this block is inert rather than fatal.
if [[ ${#JS_FILES[@]} -gt 0 ]]; then
    # Same RN_EXTRA guard as the Python call — bash 3.2 errors on "${arr[@]}" for
    # an empty array under set -u.
    if [[ ${#RN_EXTRA[@]} -gt 0 ]]; then
        run_validator "risk_number_js"  "$VALIDATORS_DIR/rn_calculator_js.py"        60 false "${RN_EXTRA[@]}" "${JS_FILES[@]}"
    else
        run_validator "risk_number_js"  "$VALIDATORS_DIR/rn_calculator_js.py"        60 false "${JS_FILES[@]}"
    fi
    run_validator "complexity_js"       "$VALIDATORS_DIR/complexity_metrics_js.py"   60 false "${JS_FILES[@]}"
    run_validator "function_metrics_js" "$VALIDATORS_DIR/function_metrics_js.py"     60 false "${JS_FILES[@]}"
    run_validator "n1_queries_js"       "$VALIDATORS_DIR/n1_detector_js.py"          60 false "${JS_FILES[@]}"
    run_validator "static_analysis_js"  "$VALIDATORS_DIR/static_analysis_js.py"     120 false "${JS_FILES[@]}"
fi

# hallucination_js (S7, #1063) is dispatched independently of the JS_FILES
# gate above: its package.json dependency-existence check must still fire on
# a dependency-only bump with zero .ts/.js/.astro files touched.
if [[ ${#JS_FILES[@]} -gt 0 || ${#PKG_JSON_FILES[@]} -gt 0 ]]; then
    run_validator "hallucination_js" "$VALIDATORS_DIR/hallucination_surface_js.py" 60 false \
        ${JS_FILES[@]+"${JS_FILES[@]}"} ${PKG_JSON_FILES[@]+"${PKG_JSON_FILES[@]}"}
fi

# Migration scorer — all files
run_validator "migration_risk"   "$VALIDATORS_DIR/migration_scorer.py"         60 false "${ALL_FILES[@]}"

# Diff-size floor + multi-purpose split trigger (#377).
# Git runs HERE (not in the validator); the validator receives CLI flags.
# Base ref: same logic as SPEC-360/change_classifier — merge-base with
# origin/main when available, else most-recent tag, else HEAD~1. Any git
# failure → pass 0/0 and empty list so the floor does not fire (data
# unavailable), never a false CRITICAL.
DS_BASE_REF=""
if git rev-parse --verify origin/main >/dev/null 2>&1; then
    DS_BASE_REF="$(git merge-base HEAD origin/main 2>/dev/null || true)"
fi
if [[ -z "$DS_BASE_REF" ]]; then
    DS_BASE_REF="$(git describe --tags --abbrev=0 2>/dev/null || true)"
fi
if [[ -z "$DS_BASE_REF" ]]; then
    DS_BASE_REF="$(git rev-parse --verify HEAD~1 2>/dev/null || true)"
fi

DS_CHANGED_LINES=0
DS_CHANGED_FILES=0
DS_FILE_LIST=()
if [[ -n "$DS_BASE_REF" ]]; then
    # changed_lines = sum of added + deleted (numstat cols 1+2); binary "-" skipped.
    DS_CHANGED_LINES="$(git diff --numstat "$DS_BASE_REF" 2>/dev/null \
        | awk '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { s += $1 + $2 } END { print s + 0 }' \
        || echo 0)"
    while IFS= read -r _df; do
        [[ -n "$_df" ]] && DS_FILE_LIST+=("$_df")
    done < <(git diff --name-only "$DS_BASE_REF" 2>/dev/null || true)
    DS_CHANGED_FILES=${#DS_FILE_LIST[@]}
fi
# Guard against non-numeric awk output.
[[ "$DS_CHANGED_LINES" =~ ^[0-9]+$ ]] || DS_CHANGED_LINES=0

# bash 3.2 (macOS) errors on "${arr[@]}" when the array is empty under set -u;
# only expand the file list when it is non-empty.
if [[ ${#DS_FILE_LIST[@]} -gt 0 ]]; then
    run_validator "diff_size"    "$VALIDATORS_DIR/diff_size.py"                30 false \
        --changed-lines "$DS_CHANGED_LINES" --changed-files "$DS_CHANGED_FILES" \
        --changed-file-list "${DS_FILE_LIST[@]}"
else
    run_validator "diff_size"    "$VALIDATORS_DIR/diff_size.py"                30 false \
        --changed-lines "$DS_CHANGED_LINES" --changed-files "$DS_CHANGED_FILES" \
        --changed-file-list
fi

# Historical density — network-dependent (calls gh + git); shorter timeout
run_validator "historical_density" "$VALIDATORS_DIR/issue_query.py"   \
    "$NETWORK_TIMEOUT" false "${ALL_FILES[@]}"

# IP / provenance — calls ScanCode/PyPI; heavy, longer timeout
run_validator "ip_check"         "$VALIDATORS_DIR/ip_check.py"                120 false \
    --prompts-dir "prompts" "${ALL_FILES[@]}"

# Portability check
if [[ ${#PY_FILES[@]} -gt 0 ]]; then
    run_validator "portability"    "$VALIDATORS_DIR/portability_check.py"       60 false "${PY_FILES[@]}"
fi

# Prompt audit — network-dependent (calls gh for spec-gap count).
# Stack-neutral: it scores the PROMPT artifact and prompt/code proportions, not
# language syntax, so it runs on the PY_FILES ∪ JS_FILES union (#1034, DQ-4
# verified: a JS path is read as text, never parsed as Python). On a Python-only
# changeset JS_FILES is empty, so _PA_FILES == PY_FILES and the argv is identical
# to the pre-#1034 call (AC-2).
if [[ ${#PY_FILES[@]} -gt 0 || ${#JS_FILES[@]} -gt 0 ]]; then
    _PA_FILES=()
    [[ ${#PY_FILES[@]} -gt 0 ]] && _PA_FILES+=("${PY_FILES[@]}")
    [[ ${#JS_FILES[@]} -gt 0 ]] && _PA_FILES+=("${JS_FILES[@]}")
    run_validator "prompt_ambiguity" "$VALIDATORS_DIR/prompt_audit_risk.py"  \
        "$NETWORK_TIMEOUT" false \
        --prompts-dir "prompts" --step "${STEP:-}" "${_PA_FILES[@]}"
fi

echo ""
echo "  Validators: ${VALIDATOR_SUCCEEDED} succeeded, ${VALIDATOR_SKIPPED} skipped (optional), ${VALIDATOR_FAILED} failed (required)"
if [[ $VALIDATOR_FAILED -gt 0 ]]; then
    echo "  ✘ Required validator(s) failed — composite score set to CRITICAL (fail-closed)"
fi
echo ""

# Aggregate into summary.json
PYTHONSAFEPATH=1 "$PYTHON" - <<'EOF'
import json, os, sys
from pathlib import Path

out_dir = Path(".claudetmp/oversight/validators")
# gate-results.json is run_gates.sh's artifact (a JSON list), not a validator
# dimension — exclude it alongside our own summary.json so the composite loop
# below only sees validator result dicts (#980).
_NON_VALIDATOR = {"summary.json", "gate-results.json"}
results = []
for f in sorted(out_dir.glob("*.json")):
    if f.name in _NON_VALIDATOR:
        continue
    try:
        obj = json.loads(f.read_text())
    except Exception:
        continue
    # Defensive: only dict-shaped validator envelopes carry score/weight/error.
    if isinstance(obj, dict):
        results.append(obj)

# Composite score: weighted average
total_w, weighted_sum = 0.0, 0.0
for r in results:
    if r.get("error"):
        continue
    w = r.get("weight", 1.0)
    weighted_sum += r.get("score", 0.0) * w
    total_w += w

# Fail-closed: if no validators produced usable output, treat as CRITICAL.
# Defaulting to LOW on total validator failure would silently pass broken code.
successful = [r for r in results if not r.get("error")]
if total_w == 0 or not successful:
    composite = 1.0
    tier = "CRITICAL"
    summary = {
        "composite_score": composite,
        "tier": tier,
        "validator_count": len(results),
        "successful_validators": 0,
        "error": "All validators failed or produced no output — defaulting to CRITICAL (fail-closed)",
        "results": results,
    }
    out = out_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"ERROR: no validators succeeded → tier: CRITICAL (fail-closed)")
    print(f"Summary: {out}")
    sys.exit(1)

composite = round(weighted_sum / total_w, 4)

TIERS = [("LOW", 0.30), ("MEDIUM", 0.55), ("HIGH", 0.78), ("CRITICAL", 1.01)]
tier = next(t for t, hi in TIERS if composite < hi)

# Hoist the highest non-null tier_floor signal (e.g. from diff_size, #377, or
# the static_analysis HIGH-bandit backstop, #997) to the top level of the
# summary so the risk-assessor reads it without parsing raw_value. Read-only
# surfacing: it does NOT alter composite_score or the derived tier (the
# risk-assessor is the actor that promotes the final tier). Must take the
# MAX across all validators, not the first non-null in glob-sorted filename
# order — multiple validators can emit tier_floor, and first-wins silently
# drops a higher floor emitted by a validator whose filename sorts later
# (#1052: static_analysis's HIGH backstop was masked by rn_calculator's
# earlier-sorting, lower MEDIUM floor).
_TIER_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
tier_floor = None
for r in results:
    tf = r.get("tier_floor")
    if tf and (tier_floor is None or _TIER_RANK.get(tf, -1) > _TIER_RANK.get(tier_floor, -1)):
        tier_floor = tf

summary = {
    "composite_score": composite,
    "tier": tier,
    "validator_count": len(results),
    "successful_validators": len(successful),
    "results": results,
}
if tier_floor is not None:
    summary["tier_floor"] = tier_floor

out = out_dir / "summary.json"
out.write_text(json.dumps(summary, indent=2))
print(f"Composite score: {composite:.4f}  →  tier: {tier}")
print(f"Summary: {out}")
EOF

# ── Committed validator artifact (#555) ───────────────────────────────────────
# When --step is provided (PR pipeline context): write a committed copy of the
# summary at signoffs/validators/step{N}/summary.json so the overseer can verify
# the artifact was produced for the correct PR HEAD commit.
# When --step is absent (developer ad-hoc): no committed artifact written.
if [[ -n "$STEP" ]]; then
    # Resolve head_sha via step_range.sh (architect ruling Q2)
    # shellcheck source=scripts/oversight/lib/step_range.sh
    source "$SCRIPT_DIR/lib/step_range.sh"
    _step_range="$(get_step_range "$STEP" 2>/dev/null || true)"
    if [[ -n "$_step_range" ]]; then
        # split "BASE..HEAD" on ".." and take the HEAD (field 2)
        _committed_head="${_step_range##*..}"
        _head_sha_source="step_range"
    else
        _committed_head="$(git rev-parse HEAD 2>/dev/null || true)"
        _head_sha_source="git_head_fallback"
    fi

    _artifact_dir="signoffs/validators/step${STEP}"
    mkdir -p "$_artifact_dir"
    _artifact_path="$_artifact_dir/summary.json"

    # Atomically write: Python writes to tmp, then mv into final path (#725)
    _artifact_tmp="$(mktemp "${_artifact_dir}/summary.XXXXXX")"
    "$PYTHON" - "$OUT_DIR/summary.json" "$_artifact_tmp" \
        "$_committed_head" "$_head_sha_source" "$STEP" <<'PYEOF'
import json, sys, datetime
src, dst, head_sha, head_sha_source, step = sys.argv[1:]
base = json.loads(open(src).read())
artifact = {
    "head_sha":        head_sha,
    "head_sha_source": head_sha_source,
    "artifact_version": "1",
    "step":            int(step),
    "written_at":      datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    **base,
}
open(dst, "w").write(json.dumps(artifact, indent=2))
PYEOF
    mv "$_artifact_tmp" "$_artifact_path"
    echo "Committed artifact: $_artifact_path (head_sha_source=$_head_sha_source)"
fi
