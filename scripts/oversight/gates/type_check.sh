#!/usr/bin/env bash
# type_check.sh — static type checking gate (blocking).
#
# Runs mypy on Python files. Requires mypy and django-stubs for Django projects.
# Also runs `tsc --noEmit` (whole-project, via tsconfig.json) when a
# tsconfig.json is present — resolved discover-only (D2, ADR-032), never
# installed. DEFERS (SKIP) when an Astro project is detected: astro_check.sh
# (S12) owns type-checking for Astro projects instead (ADR-032 D9). No-op
# when neither a tsconfig.json nor Python files apply.
# Exit 0 = type-clean. Exit 1 = type errors found.
#
# Usage: ./type_check.sh file.py [file2.py ...]
#        ./type_check.sh --all
#
# Note: mypy may surface false positives on Django ORM code without
# django-stubs installed. Configure per-project in mypy.ini or pyproject.toml.

set -euo pipefail

GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/ensure_venv.sh
source "$GATES_DIR/../ensure_venv.sh"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$GATES_DIR/check_suspension.sh"
# shellcheck source=scripts/oversight/lib/resolve_node_tool.sh
source "$GATES_DIR/../lib/resolve_node_tool.sh"
is_suspended "types" && { print_suspended "types"; exit 0; }

# Same marker check as detect_stack.sh's _detect_astro_marker_present
# (duplicated, not sourced — same _js-sibling independence convention used
# elsewhere in ADR-032, e.g. lint_check.sh's _eslint_config_present).
_astro_marker_present() {
    if [[ -f "package.json" ]] && grep -q '"astro"' package.json 2>/dev/null; then
        return 0
    fi
    if find . -name '*.astro' -not -path './node_modules/*' -not -path './.git/*' \
        -print -quit 2>/dev/null | grep -q .; then
        return 0
    fi
    return 1
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
    # bash 3.2 (macOS default) has no `mapfile` — use a portable read loop.
    FILES=()
    while IFS= read -r _f; do
        [[ -n "$_f" ]] && FILES+=("$_f")
    done < <(find . -name "*.py" -not -path "./.venv/*" \
        -not -path "*/migrations/*" -not -path "./.git/*")
fi

if [[ ${#FILES[@]} -eq 0 ]] && ! $CHECK_ALL; then
    # No files specified and --all not set: default to scanning all Python files
    # rather than silently passing (a no-op pass is indistinguishable from a real pass).
    echo "type_check: no files specified — defaulting to --all (full project scan)"
    while IFS= read -r line; do FILES+=("$line"); done < <(find . -name "*.py" \
        -not -path "./.venv/*" -not -path "./scripts/oversight/.venv/*" \
        -not -path "./node_modules/*" -not -path "./.git/*")
fi

# Filter to Python files only — FILES may include non-.py paths when passed
# individually (run_gates.sh forwards the whole changeset to every gate).
# Mirrors lint_check.sh's PY_FILES/JS_FILES split (#1096).
PY_FILES=()
for f in "${FILES[@]}"; do
    case "$f" in
        *.py) PY_FILES+=("$f") ;;
    esac
done

ERRORS=0

echo "=== mypy ==="
if [[ ${#PY_FILES[@]} -eq 0 ]]; then
    echo "SKIP: no Python files found in project"
elif [[ ! -x "$VENV_BIN/mypy" ]]; then
    echo "SKIP: mypy not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
elif "$VENV_BIN/mypy" --ignore-missing-imports --no-error-summary "${PY_FILES[@]}"; then
    echo "OK: no type errors"
else
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "=== tsc --noEmit ==="
if [[ ! -f "tsconfig.json" ]]; then
    echo "SKIP: no tsconfig.json (not a TS project)"
elif _astro_marker_present; then
    echo "SKIP: Astro project detected — astro_check.sh (S12) owns type-checking here (ADR-032 D9)"
elif tsc_cmd=$(resolve_node_tool tsc); then
    if $tsc_cmd --noEmit; then
        echo "OK: no type errors"
    else
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "SKIP: tsc not resolvable (./node_modules/.bin, npx --no-install, or PATH)"
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: type errors found — review before proceeding"
    exit 1
else
    echo "GATE PASS: no type errors"
    exit 0
fi
