#!/usr/bin/env bash
# secret_scan.sh — hardcoded secret detection gate (blocking).
#
# Uses detect-secrets to find potential credentials, API keys, tokens, and
# other secrets that should never be committed. Checks both staged files and
# the provided file list.
#
# Exit 0 = no secrets found. Exit 1 = potential secrets detected.
#
# Usage: ./secret_scan.sh file.py [file2.py ...]
#        ./secret_scan.sh --staged    (check staged files via git diff)
#        ./secret_scan.sh --all       (check entire project)

set -euo pipefail

_GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$_GATES_DIR/check_suspension.sh"
is_suspended "secrets" && { print_suspended "secrets"; exit 0; }

# detect-secrets and PyYAML live in the oversight venv, not on the bare PATH.
# Without this, `command -v detect-secrets` fails on a clean machine and the gate
# silently downgrades to the weak grep fallback. (HOS#102)
# shellcheck source=scripts/oversight/ensure_venv.sh
source "$_GATES_DIR/../ensure_venv.sh"

FILES=()
CHECK_STAGED=false
CHECK_ALL=false

for arg in "$@"; do
    if [[ "$arg" == "--staged" ]]; then
        CHECK_STAGED=true
    elif [[ "$arg" == "--all" ]]; then
        CHECK_ALL=true
    else
        FILES+=("$arg")
    fi
done

if $CHECK_STAGED; then
    while IFS= read -r line; do FILES+=("$line"); done < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | \
        grep -E '\.(py|txt|yaml|yml|json|env|cfg|ini|sh)$' || true)
fi

if $CHECK_ALL || [[ ${#FILES[@]} -eq 0 ]]; then
    # No files specified (or --all) and --staged not set: default to scanning
    # the whole project rather than printing "No files to scan" and recording
    # GATE PASS — a no-op pass is indistinguishable from a real pass, so
    # hardcoded secrets would go undetected yet the gate would exit 0. Mirrors
    # lint_check.sh. The extension set matches the --staged filter above.
    # (#976, #1571 — --all previously unrecognized, silently mis-scanning the
    # whole working tree including scripts/oversight/.venv/ instead of using
    # this exclusion list)
    echo "secret_scan: no files specified — defaulting to full project scan"
    FILES=()
    while IFS= read -r line; do FILES+=("$line"); done < <(find . -type f \
        \( -name "*.py" -o -name "*.txt" -o -name "*.yaml" -o -name "*.yml" \
           -o -name "*.json" -o -name "*.env" -o -name "*.cfg" -o -name "*.ini" \
           -o -name "*.sh" \) \
        -not -path "./.venv/*" -not -path "./scripts/oversight/.venv/*" \
        -not -path "./.git/*")
fi

# ── Known-benign high-entropy shapes: one policy, two mechanisms ────────────
#
# Some committed artifacts carry hex fingerprints BY DESIGN, and detect-secrets
# reports every one as a Hex High Entropy String. Both cases below are the same
# policy — "a fingerprint the pipeline itself writes and verifies is not a
# secret" — and the mechanism differs only by how much coverage the exemption
# costs.
#
#   1. WHOLE-FILE SKIP (#1572) — scripts/framework/validation-stamps/*.stamp.
#      A stamp is a handful of short, fixed fields built around a 64-hex
#      content fingerprint (verified by check_validation_current.sh). Skipping
#      the file forgoes almost no coverage, so the cheap mechanism is
#      proportionate. Skipped regardless of how it arrived (explicit CI args,
#      --staged, or the full-project default), since CI passes changed files
#      explicitly and bypasses the extension filters above.
#
#   2. FINDING-LEVEL SUPPRESSION (#1754) — signoffs/validators/*/summary.json.
#      This artifact is REQUIRED (overseer.md step 3b fail-closes to
#      HUMAN_REQUIRED without it) and its 40-hex `head_sha` is checked against
#      the artifact commit's parent — so the gate was failing on a file the
#      pipeline demands, and had been for as long as one has been on `main`.
#      A whole-file skip is NOT proportionate here: the artifact runs to ~2,000
#      lines and quotes file paths and code evidence from the changeset, which
#      is exactly where a real credential could land. So the file stays in the
#      scan and only the specific benign finding is dropped — see
#      scripts/oversight/secret_scan_logic.py, which requires the path, the
#      detector type AND the flagged line's shape to match before suppressing,
#      and prints every suppression it makes.
FILTERED_FILES=()
if [[ ${#FILES[@]} -gt 0 ]]; then
    for f in "${FILES[@]}"; do
        if [[ "$f" == scripts/framework/validation-stamps/*.stamp ]]; then
            continue
        fi
        FILTERED_FILES+=("$f")
    done
fi
FILES=("${FILTERED_FILES[@]+"${FILTERED_FILES[@]}"}")

ERRORS=0
GATE_TIMEOUT="${GATE_TIMEOUT:-60}"
GATE_RETRIES="${GATE_RETRIES:-2}"

# Resolve detect-secrets: prefer the oversight venv, fall back to PATH. Same for
# the JSON-parsing interpreter ($OVERSIGHT_PYTHON has stdlib json; bare python3
# may not exist or may be PEP-668-empty). (HOS#102)
DETECT_SECRETS=""
if [[ -x "$VENV_BIN/detect-secrets" ]]; then
    DETECT_SECRETS="$VENV_BIN/detect-secrets"
elif command -v detect-secrets &>/dev/null; then
    DETECT_SECRETS="$(command -v detect-secrets)"
fi
PARSE_PY="${OVERSIGHT_PYTHON:-python3}"

if [[ -n "$DETECT_SECRETS" ]]; then
    echo "=== detect-secrets ==="
    if [[ ${#FILES[@]} -gt 0 ]]; then
        DS_TMP=$(mktemp /tmp/detect_secrets_XXXXXX)
        # Unit of work: detect-secrets under the configured timeout, capture to temp.
        _run_detect_secrets() { with_timeout "$GATE_TIMEOUT" "$DETECT_SECRETS" scan "${FILES[@]}" > "$DS_TMP" 2>/dev/null; }
        if ! run_with_retry "detect-secrets" "$GATE_RETRIES" "true" _run_detect_secrets; then
            echo "GATE FAIL: detect-secrets did not complete after retries"
            rm -f "$DS_TMP"
            exit 1
        fi
        BASELINE=$(cat "$DS_TMP"); rm -f "$DS_TMP"
        # Counting, reporting and known-benign-shape suppression live in a named,
        # unit-testable module (#314 policy: logic in Python, shell for launch).
        # The shell still decides pass/fail, from the module's exit status.
        #
        # Exit 2 = the scan output could not be parsed. That used to be
        # `|| echo "0"` — an unreadable scan counted zero secrets and the gate
        # PASSED, the same report-success-having-checked-nothing shape #1750 and
        # #1759 are about. It is now a gate failure.
        SCAN_FILTER="$_GATES_DIR/../secret_scan_logic.py"
        SCAN_STATUS=0
        echo "$BASELINE" | PYTHONSAFEPATH=1 "$PARSE_PY" "$SCAN_FILTER" filter || SCAN_STATUS=$?
        if [[ "$SCAN_STATUS" -ne 0 ]]; then
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "No files to scan"
    fi
else
    # Fallback: grep for common secret patterns
    echo "=== fallback secret grep (detect-secrets not installed) ==="
    PATTERNS=(
        'password\s*=\s*["\x27][^"\x27]{4,}'
        'api_key\s*=\s*["\x27][^"\x27]{8,}'
        'secret\s*=\s*["\x27][^"\x27]{8,}'
        'token\s*=\s*["\x27][^"\x27]{8,}'
        'AWS_SECRET'
        'private_key'
    )
    for pattern in "${PATTERNS[@]}"; do
        if [[ ${#FILES[@]} -gt 0 ]]; then
            MATCHES=$(grep -rniE "$pattern" "${FILES[@]}" 2>/dev/null || true)
            if [[ -n "$MATCHES" ]]; then
                echo "POTENTIAL SECRET: $MATCHES"
                ERRORS=$((ERRORS + 1))
            fi
        fi
    done
    if [[ $ERRORS -eq 0 ]]; then
        echo "OK (fallback patterns — install detect-secrets for full coverage)"
    fi
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: potential secrets detected — review and remove before commit"
    exit 1
else
    echo "GATE PASS: no secrets detected"
    exit 0
fi
