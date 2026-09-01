#!/usr/bin/env bash
# lint_check.sh — style and formatting gate (blocking).
#
# Runs flake8, black (check mode), and isort (check mode) on Python files.
# Runs eslint on JS/TS/JSX/TSX/Astro files when eslint resolves for the
# consumer project (ADR-032, #1029 S10) — never installed, discover-only (D2).
# Exit 0 = all pass. Exit 1 = any failure; diff/output is printed for the human.
#
# Usage: ./lint_check.sh file.py [file2.ts ...]
#        ./lint_check.sh --all        (check entire project)
#
# Part of the oversight pipeline cheap-gates stage (DECISIONS.md §D7).
# Run before risk assessment — no point scoring code that fails style checks.

set -euo pipefail

GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/ensure_venv.sh
source "$GATES_DIR/../ensure_venv.sh"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$GATES_DIR/check_suspension.sh"
# shellcheck source=scripts/oversight/lib/resolve_node_tool.sh
source "$GATES_DIR/../lib/resolve_node_tool.sh"
is_suspended "lint" && { print_suspended "lint"; exit 0; }

PASS=0
FAIL=1

# Same extension set as run_validators.sh's JS_FILES lane (ADR-032, #1034).
JS_NAME_MATCH=(-name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" \
    -o -name "*.astro" -o -name "*.mjs" -o -name "*.cjs")

# Same config-file list as detect_stack.sh's _detect_eslint_config_present
# (duplicated, not sourced — same _js-sibling independence convention used
# elsewhere in ADR-032, e.g. rn_calculator_js.py). A resolvable eslint binary
# with no project config isn't "configured" — running it anyway would fail
# every JS project that hasn't opted into eslint (ESLint exits non-zero with
# "couldn't find a configuration file"), which is not a real lint violation.
_eslint_config_present() {
    local cfg
    for cfg in .eslintrc .eslintrc.js .eslintrc.cjs .eslintrc.mjs .eslintrc.json \
               .eslintrc.yaml .eslintrc.yml \
               eslint.config.js eslint.config.cjs eslint.config.mjs eslint.config.ts; do
        [[ -f "$cfg" ]] && return 0
    done
    return 1
}

_collect_all_files() {
    FILES=()
    while IFS= read -r line; do FILES+=("$line"); done < <(find . \
        -not -path "./.venv/*" -not -path "./scripts/oversight/.venv/*" \
        -not -path "./node_modules/*" -not -path "./.git/*" \
        \( -name "*.py" -o "${JS_NAME_MATCH[@]}" \))
}

FILES=()
CHECK_ALL=false

for arg in "$@"; do
    if [[ "$arg" == "--all" ]]; then
        CHECK_ALL=true
    else
        FILES+=("$arg")
    fi
done

if $CHECK_ALL; then
    _collect_all_files
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    # No files specified and --all not set: default to scanning all Python and
    # JS/TS files rather than silently passing (a no-op pass is
    # indistinguishable from a real pass).
    echo "lint_check: no files specified — defaulting to --all (full project scan)"
    _collect_all_files
    if [[ ${#FILES[@]} -eq 0 ]]; then
        echo "lint_check: no Python or JS/TS files found in project — SKIP"
        exit $PASS
    fi
fi

PY_FILES=()
JS_FILES=()
for f in "${FILES[@]}"; do
    case "$f" in
        *.py) PY_FILES+=("$f") ;;
        *.ts|*.tsx|*.js|*.jsx|*.astro|*.mjs|*.cjs) JS_FILES+=("$f") ;;
    esac
done

ERRORS=0

if [[ ${#PY_FILES[@]} -eq 0 && ${#JS_FILES[@]} -eq 0 ]]; then
    echo "lint_check: no Python or JS/TS files in changeset — SKIP"
    exit $PASS
fi

if [[ ${#PY_FILES[@]} -gt 0 ]]; then
    echo "=== flake8 ==="
    if [[ -x "$VENV_BIN/flake8" ]]; then
        if ! "$VENV_BIN/flake8" --max-line-length=120 --extend-ignore=E203,W503 "${PY_FILES[@]}"; then
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "SKIP: flake8 not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    fi

    echo ""
    echo "=== black (format check) ==="
    if [[ -x "$VENV_BIN/black" ]]; then
        if ! "$VENV_BIN/black" --check --diff --quiet "${PY_FILES[@]}"; then
            ERRORS=$((ERRORS + 1))
            echo "Run: $VENV_BIN/black ${PY_FILES[*]}"
        else
            echo "OK"
        fi
    else
        echo "SKIP: black not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    fi

    echo ""
    echo "=== isort (import order check) ==="
    if [[ -x "$VENV_BIN/isort" ]]; then
        if ! "$VENV_BIN/isort" --check-only --diff "${PY_FILES[@]}"; then
            ERRORS=$((ERRORS + 1))
            echo "Run: $VENV_BIN/isort ${PY_FILES[*]}"
        else
            echo "OK"
        fi
    else
        echo "SKIP: isort not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    fi
fi

if [[ ${#JS_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "=== eslint ==="
    if ! _eslint_config_present; then
        echo "SKIP: no eslint config in project — nothing configured to lint against"
    # Discover-only resolution (D2, ADR-032) — never installed. detect_stack.sh's
    # tool_preflight_or_fail is the hard-fail authority when a config IS present
    # but eslint itself is missing; this gate does not duplicate that — it just
    # SKIPs so a real lint violation is never masked as a pass.
    elif eslint_cmd=$(resolve_node_tool eslint); then
        if ! $eslint_cmd "${JS_FILES[@]}"; then
            ERRORS=$((ERRORS + 1))
            echo "Run: $eslint_cmd --fix ${JS_FILES[*]}"
        else
            echo "OK"
        fi
    else
        echo "SKIP: eslint not resolvable (./node_modules/.bin, npx --no-install, or PATH)"
    fi
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: $ERRORS lint check(s) failed — fix before risk assessment"
    exit $FAIL
else
    echo "GATE PASS: all lint checks clean"
    exit $PASS
fi
