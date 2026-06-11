#!/usr/bin/env bash
# lint_check.sh — style and formatting gate (blocking).
#
# Runs flake8, black (check mode), and isort (check mode) on Python files.
# Exit 0 = all pass. Exit 1 = any failure; diff is printed for the human.
#
# Usage: ./lint_check.sh file.py [file2.py ...]
#        ./lint_check.sh --all        (check entire project)
#
# Part of the oversight pipeline cheap-gates stage (DECISIONS.md §D7).
# Run before risk assessment — no point scoring code that fails style checks.

set -euo pipefail

PASS=0
FAIL=1

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
    mapfile -t FILES < <(find . -name "*.py" -not -path "./.venv/*" \
        -not -path "./node_modules/*" -not -path "./.git/*")
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "lint_check: no Python files to check"
    exit $PASS
fi

ERRORS=0

echo "=== flake8 ==="
if command -v flake8 &>/dev/null; then
    if ! flake8 --max-line-length=120 --extend-ignore=E203,W503 "${FILES[@]}"; then
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "SKIP: flake8 not installed (pip install flake8)"
fi

echo ""
echo "=== black (format check) ==="
if command -v black &>/dev/null; then
    if ! black --check --diff --quiet "${FILES[@]}"; then
        ERRORS=$((ERRORS + 1))
        echo "Run: black ${FILES[*]}"
    else
        echo "OK"
    fi
else
    echo "SKIP: black not installed (pip install black)"
fi

echo ""
echo "=== isort (import order check) ==="
if command -v isort &>/dev/null; then
    if ! isort --check-only --diff "${FILES[@]}"; then
        ERRORS=$((ERRORS + 1))
        echo "Run: isort ${FILES[*]}"
    else
        echo "OK"
    fi
else
    echo "SKIP: isort not installed (pip install isort)"
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: $ERRORS lint check(s) failed — fix before risk assessment"
    exit $FAIL
else
    echo "GATE PASS: all lint checks clean"
    exit $PASS
fi
