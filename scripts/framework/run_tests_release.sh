#!/usr/bin/env bash
# run_tests_release.sh — Run the full test suite (required for release).
#
# Includes all tests: inner-loop + @pytest.mark.slow + @pytest.mark.integration.
# Must pass before cutting a release or merging to main.
# Expected runtime: 2–5 min (dominated by pack install tests ~12s each).
#
# Usage:
#   ./scripts/framework/run_tests_release.sh            # full suite
#   ./scripts/framework/run_tests_release.sh --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"

case "${1:-}" in
  --help|-h)
    echo "Usage: $0 [pytest-args...]"
    echo ""
    echo "Runs the full test suite including @pytest.mark.slow and"
    echo "@pytest.mark.integration tests. Required before cutting a release."
    echo ""
    echo "For the faster PR suite: ./scripts/framework/run_tests_inner_loop.sh"
    exit 0
    ;;
esac

echo -e "${BOLD}HOS Release Tests${RESET} (full suite — all tiers)"
echo -e "  ${CYAN}→${RESET}  Including: @slow, @integration"
echo -e "  ${CYAN}→${RESET}  Repo: $REPO_ROOT"
echo ""

VENV="$REPO_ROOT/scripts/oversight/.venv"
if [ -f "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo -e "  ${RED}✘${RESET}  python not found — run: ./bootstrap/hos_bootstrap.sh"
  exit 1
fi

cd "$REPO_ROOT"
"$PYTHON" -m pytest "$@"
