#!/usr/bin/env bash
# astro_check.sh — Astro project sanity gate (blocking on errors).
#
# Runs `astro sync` then `astro check` — the Astro analog to django_check.sh's
# `manage.py check` (ADR-032 D9). `astro sync` regenerates the content-collection
# and env types that `astro check` depends on, so it must run first. Explicitly
# not `astro build`, which is a heavier build-verification step out of scope here.
#
# No-op when the project is not an Astro project (no "astro" in package.json
# deps, no .astro files) — same marker convention as type_check.sh's
# _astro_marker_present / detect_stack.sh's _detect_astro_marker_present.
#
# astro is resolved discover-only (D2, ADR-032) via resolve_node_tool.sh —
# never installed. A depended-on-but-missing astro CLI is hard-failed earlier
# by tool_preflight_or_fail (D1); this gate SKIPs rather than duplicating that
# failure, matching lint_check.sh/type_check.sh's not-resolvable convention.
#
# Exit 0 = check passed, not an Astro project, or astro not resolvable.
# Exit 1 = astro sync or astro check reported errors.
#
# Usage: ./astro_check.sh

set -euo pipefail

GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$GATES_DIR/check_suspension.sh"
# shellcheck source=scripts/oversight/lib/resolve_node_tool.sh
source "$GATES_DIR/../lib/resolve_node_tool.sh"
is_suspended "astro" && { print_suspended "astro"; exit 0; }

# Same marker check as detect_stack.sh's _detect_astro_marker_present and
# type_check.sh's _astro_marker_present (duplicated, not sourced — same
# _js-sibling independence convention used elsewhere in ADR-032).
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

echo "=== astro sync && astro check ==="

if ! _astro_marker_present; then
    echo "SKIP: not an Astro project (no \"astro\" in package.json, no .astro files)"
    exit 0
fi

if ! astro_cmd=$(resolve_node_tool astro); then
    echo "SKIP: astro not resolvable (./node_modules/.bin, npx --no-install, or PATH)"
    exit 0
fi

echo "astro: $astro_cmd"

if ! $astro_cmd sync; then
    echo ""
    echo "GATE FAIL: astro sync failed — content-collection types could not be generated"
    exit 1
fi

if $astro_cmd check; then
    echo "GATE PASS: astro check clean"
    exit 0
else
    echo ""
    echo "GATE FAIL: astro check reported errors"
    exit 1
fi
