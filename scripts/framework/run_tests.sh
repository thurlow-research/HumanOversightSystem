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
#   Coverage : ≥ 78% (ratcheted from the measured baseline after #1256 widened
#                     the measured surface to also include scripts/framework;
#                     raise as gaps close, never lower without a recorded decision)
#   Mutant score : ≥ 75% killed
#
# Retry tolerance (#1244 ruling, 2026-09-10): each test gets one immediate
# retry on failure (2 total attempts, via pytest-rerunfailures --reruns 1). A
# test that fails once then passes on retry is flaky by definition and does
# not block; a test that fails both attempts is a real failure and blocks,
# full stop. This is not an override an agent can widen — the only escape
# hatch is the existing audited contract/gate-suspension.md mechanism, same
# as every other gate. No env var toggles this.
#
# Retry-rescue observability (#1244 ruling item 4): tests/conftest.py's
# pytest_terminal_summary hook detects which tests were rescued by the retry
# above and prints a RETRY-RESCUE line for each, plus a best-effort audit-log
# write (see retry_rescue_logic.py). Not going silent about a pass-on-retry
# is the point — see that hook's docstring for what is and isn't covered yet.
#
# New-code gate (#2304): the pytest run records a coverage context per test
# (COVERAGE_CORE=ctrace, --cov-context=test) over the six measured roots, and the
# `new_code_gate meta` step writes coverage-meta.json next to .coverage. The gate's
# measure phase consumes both. See docs/v0.7.0/TECHNICAL-DESIGN-2304-new-code-coverage-mutation-gate.md.
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
COVERAGE_TARGET=78
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
"$VENV_PIP" install --quiet pytest pytest-cov pytest-rerunfailures mutmut 2>/dev/null || true

cd "$REPO_ROOT"

# #2304: pin the context-capable coverage core (--cov-context=test needs ctrace).
# It is already the default on Python 3.12; this guards against a future default change.
export COVERAGE_CORE=ctrace

# ── Phase 1: pytest + coverage ───────────────────────────────────────────────
if ! $MUTATION_ONLY; then
    echo "=== Unit tests + coverage ==="
    echo ""

    # #2304 (AD-14): tests/conftest.py writes each test's wall time here, in milliseconds,
    # for the shard planner. A plain assignment on this one command, nothing conditional.
    # A leftover file from an earlier run is removed first, so a run that dies before the
    # writer runs cannot pair its coverage data with old timings.
    rm -f test-durations.json
    HOS_TEST_DURATIONS_OUT=test-durations.json "$VENV_PYTHON" -m pytest tests/ \
        --reruns 1 \
        --cov=scripts/oversight \
        --cov=scripts/automation/lib \
        --cov=scripts/framework \
        --cov=scripts \
        --cov=bootstrap \
        --cov=bin \
        --cov-context=test \
        --cov-report= \
        -v
    PYTEST_EXIT=$?

    # Suite-wide gate over the three original roots with the old omit list, so
    # the file set and total match the pre-#2304 report (fail_under is never adjusted).
    "$VENV_PYTHON" -m coverage report \
        --include='scripts/oversight/*,scripts/automation/lib/*,scripts/framework/*' \
        --omit='*/test_*,*/__init__.py,*/conftest.py,*/.venv/*,*/__pycache__/*' \
        --show-missing \
        --fail-under=$COVERAGE_TARGET

    # Sidecar describing the coverage data for the new-code gate (#2304).
    # Started through the -I -c wrapper (ADR-2304 2f RV2-1; the text equals
    # ENTRY_SNIPPET in new_code_gate_logic.py, asserted by WF-ENTRY) so no repo-root
    # file can shadow an import in the gate process.
    "$VENV_PYTHON" -I -c "import os, sys, types; r = os.path.realpath(sys.argv[1]); p = types.ModuleType('scripts'); p.__path__ = [os.path.join(r, 'scripts')]; sys.modules['scripts'] = p; from scripts.framework.new_code_gate import main; sys.exit(main(sys.argv[2:]))" \
        "$REPO_ROOT" meta --coverage-file .coverage --out coverage-meta.json --durations test-durations.json

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

    # mutmut 3.x reads paths/runner config from pyproject.toml's [tool.mutmut]
    # (source_paths / pytest_add_cli_args_test_selection) — its `run` command no
    # longer accepts --paths-to-mutate/--runner flags (2.x-era CLI surface).
    "$VENV_PYTHON" -m mutmut run \
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
