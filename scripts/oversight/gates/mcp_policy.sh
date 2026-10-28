#!/usr/bin/env bash
# mcp_policy.sh — MCP approved-list gate (blocking, CRITICAL; #2197).
#
# HOS installs MCP software only if it is on scripts/oversight/mcp_approved_list.json
# at the listed version. This gate checks HOS's requirement files and the installed
# dependency closure reachable from them (scripts/oversight/mcp_policy_logic.py).
# It needs no network and no file list: drift can arrive without any diff, so the
# check is never narrowed to the changed files.
#
# There is deliberately no environment override for the list path and no way to
# point the checker at another site directory: an override would be a route to
# disabling the gate.
#
# Exit 0 = clean (or empty changeset, reported as NOT CHECKED). Exit 1 = unapproved
# MCP software, or the policy could not be checked (never a pass).
#
# Usage: ./mcp_policy.sh [--all | --diff <ref> | --step <n> | --staged | --empty-changeset | file ...]
#
# Argument grammar shared with run_gates.sh — see scripts/oversight/lib/changeset.sh.

set -euo pipefail

GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/ensure_venv.sh
source "$GATES_DIR/../ensure_venv.sh"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$GATES_DIR/check_suspension.sh"
is_suspended "mcp_policy" && { print_suspended "mcp_policy"; exit 0; }
# shellcheck source=scripts/oversight/lib/changeset.sh
source "$GATES_DIR/../lib/changeset.sh"

hos_changeset_parse mcp_policy "$@" || exit $HOS_CHANGESET_EXIT
hos_changeset_summary mcp_policy

case "$HOS_CHANGESET_STATUS" in
    empty)
        hos_changeset_not_checked mcp_policy
        exit 0
        ;;
    unscoped|all|ok)
        echo "mcp_policy: dependency-tree check — changeset file list not used"
        ;;
esac

if [[ ! -x "$OVERSIGHT_PYTHON" ]]; then
    echo "GATE FAIL [CRITICAL]: oversight venv unavailable — MCP policy NOT CHECKED (this is not a pass)"
    exit 1
fi

rc=0
PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -I "$GATES_DIR/../mcp_policy_logic.py" \
    --list "$GATES_DIR/../mcp_approved_list.json" --installed || rc=$?

case "$rc" in
    0)
        echo "OK: mcp_policy — all MCP packages in HOS's closure are listed at listed versions"
        exit 0
        ;;
    1)
        echo "GATE FAIL [CRITICAL]: unapproved MCP software — see violations above"
        echo "  Remediation: update the list through a CODEOWNER-approved PR, or re-sync the venv:"
        echo "    scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt"
        exit 1
        ;;
    *)
        echo "GATE FAIL [CRITICAL]: MCP policy could not be checked — failure to check, not a clean result"
        exit 1
        ;;
esac
