#!/usr/bin/env bash
# run_tests.sh — run unit tests and optionally mutation tests for HOS validators.
#
# Uses the oversight venv (scripts/oversight/.venv) which must already be
# set up via scripts/oversight/ensure_venv.sh.
#
# Usage:
#   ./scripts/framework/run_tests.sh              # pytest + coverage only (fast)
#   ./scripts/framework/run_tests.sh --mutation    # pytest + coverage + mutmut
#   ./scripts/framework/run_tests.sh --mutation-only  # mutmut only (skip pytest run)
#
# Targets (from unit-test agent):
#   Coverage : ≥ 80%
#   Mutant score : ≥ 75% killed
#
# Exit codes:
#   0 — all targets met
#   1 — coverage or mutant score below target
#   2 — venv not found or pytest not installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$REPO_ROOT/scripts/oversight/.venv"
VENV_PYTHON="$VENV/bin/python"
VENV_PIP="$VENV/bin/pip"

MUTATION=false
MUTATION_ONLY=false
COVERAGE_TARGET=80
MUTANT_TARGET=75

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mutation)      MUTATION=true;      shift ;;
        --mutation-only) MUTATION_ONLY=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ── Check venv ────────────────────────────────────────────────────────────────
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "ERROR: oversight venv not found at $VENV" >&2
    echo "Run: bash scripts/oversight/ensure_venv.sh" >&2
    exit 2
fi

# Ensure test dependencies are installed
"$VENV_PIP" install --quiet pytest pytest-cov mutmut 2>/dev/null || true

cd "$REPO_ROOT"

# ── Phase 1: pytest + coverage ───────────────────────────────────────────────
if ! $MUTATION_ONLY; then
    echo "=== Unit tests + coverage ==="
    echo ""

    "$VENV_PYTHON" -m pytest tests/ \
        --cov=scripts/oversight/validators \
        --cov=scripts/oversight/token_tracker \
        --cov-report=term-missing \
        --cov-fail-under=$COVERAGE_TARGET \
        -v
    PYTEST_EXIT=$?

    if [[ $PYTEST_EXIT -ne 0 ]]; then
        echo ""
        echo "════════════════════════════════════════════"
        echo "  FAIL — tests failed or coverage < ${COVERAGE_TARGET}%"
        echo "════════════════════════════════════════════"
        exit 1
    fi

    echo ""
    echo "════════════════════════════════════════════"
    echo "  PASS — tests green, coverage ≥ ${COVERAGE_TARGET}%"
    echo "════════════════════════════════════════════"
fi

# ── Phase 2: mutmut mutation testing ─────────────────────────────────────────
if $MUTATION || $MUTATION_ONLY; then
    echo ""
    echo "=== Mutation testing (mutmut) ==="
    echo "  Target: ≥ ${MUTANT_TARGET}% killed"
    echo "  This runs the full test suite against each mutant — may take several minutes."
    echo ""

    "$VENV_PYTHON" -m mutmut run \
        --paths-to-mutate scripts/oversight/validators/ \
        --runner "\"$VENV_PYTHON\" -m pytest tests/ -x -q --no-header" \
        2>&1 || true  # mutmut exits non-zero even on partial success

    echo ""
    echo "=== Mutmut results ==="
    "$VENV_PYTHON" -m mutmut results 2>&1 || true

    # Compute kill rate
    KILL_RATE=$("$VENV_PYTHON" -c "
import subprocess, re, sys
result = subprocess.run(
    ['$VENV_PYTHON', '-m', 'mutmut', 'results'],
    capture_output=True, text=True
)
output = result.stdout + result.stderr
killed = len(re.findall(r'Killed', output))
survived = len(re.findall(r'Survived|Suspicious', output))
total = killed + survived
if total == 0:
    print('0')
else:
    print(str(round(killed / total * 100)))
" 2>/dev/null || echo "0")

    echo ""
    if [[ "$KILL_RATE" -ge "$MUTANT_TARGET" ]]; then
        echo "════════════════════════════════════════════"
        echo "  PASS — mutant kill rate: ${KILL_RATE}% (target ≥ ${MUTANT_TARGET}%)"
        echo "════════════════════════════════════════════"
    else
        echo "════════════════════════════════════════════"
        echo "  FAIL — mutant kill rate: ${KILL_RATE}% (target ≥ ${MUTANT_TARGET}%)"
        echo "  Run: bash scripts/framework/run_tests.sh --mutation"
        echo "  Review survivors: python -m mutmut show <id>"
        echo "════════════════════════════════════════════"
        exit 1
    fi
fi

exit 0
