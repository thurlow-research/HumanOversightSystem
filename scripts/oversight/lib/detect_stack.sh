#!/usr/bin/env bash
# detect_stack.sh — repo-marker tool detection + fail-hard preflight (D1, ADR-032).
#
# Sourced lib, two functions:
#
#   detect_required_tools()
#       Prints the required-tool keys (one per line, deduped) for the project
#       at cwd, derived from repo MARKERS — never lone file extensions:
#         tsconfig.json                                  -> tsc
#         "astro" in package.json deps, or any .astro file -> astro, astro-check
#         an eslint config file                          -> eslint
#         any of the above (a JS/Astro project)           -> node-floor (Node >= 22)
#       Python venv tools are NOT listed here — ensure_venv.sh already
#       hard-fails when the venv can't build, so they are guaranteed present.
#
#   tool_preflight_or_fail()
#       Resolves every required tool (via resolve_node_tool) plus the Node
#       floor. On any miss: writes a structured, actionable message to stderr
#       and returns 1. No-op (returns 0 immediately) when detect_required_tools
#       finds nothing to require (AC-4: no-op outside a JS/Astro project).
#       Honors the audited `is_suspended "tools"` escape hatch (returns 0) and
#       the non-default `HOS_REQUIRE_TOOLS=warn` downgrade (prints the same
#       message but returns 0). Default mode is `enforce` (D1: ratified,
#       no warn-grace) — a missing depended-on tool hard-fails.
#
# Usage:
#   source ".../lib/detect_stack.sh"
#   tool_preflight_or_fail || exit 1

_DETECT_STACK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/lib/resolve_node_tool.sh
source "$_DETECT_STACK_LIB_DIR/resolve_node_tool.sh"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$_DETECT_STACK_LIB_DIR/../gates/check_suspension.sh"

# Node floor (D1, ratified). Overridable only for tests — not a documented
# consumer-facing escape hatch.
HOS_NODE_FLOOR_MAJOR="${HOS_NODE_FLOOR_MAJOR:-22}"

_detect_eslint_config_present() {
    local cfg
    for cfg in .eslintrc .eslintrc.js .eslintrc.cjs .eslintrc.mjs .eslintrc.json \
               .eslintrc.yaml .eslintrc.yml \
               eslint.config.js eslint.config.cjs eslint.config.mjs eslint.config.ts; do
        [[ -f "$cfg" ]] && return 0
    done
    return 1
}

_detect_astro_marker_present() {
    # "astro" in package.json deps ...
    if [[ -f "package.json" ]] && grep -q '"astro"' package.json 2>/dev/null; then
        return 0
    fi
    # ... or any .astro file in the project (excluding node_modules/.git).
    if find . -name '*.astro' -not -path './node_modules/*' -not -path './.git/*' \
        -print -quit 2>/dev/null | grep -q .; then
        return 0
    fi
    return 1
}

detect_required_tools() {
    local -a keys=()
    local is_js_project=false

    if [[ -f "tsconfig.json" ]]; then
        keys+=("tsc")
        is_js_project=true
    fi

    if _detect_astro_marker_present; then
        keys+=("astro" "astro-check")
        is_js_project=true
    fi

    if _detect_eslint_config_present; then
        keys+=("eslint")
        is_js_project=true
    fi

    if $is_js_project; then
        keys+=("node-floor")
    fi

    [[ ${#keys[@]} -eq 0 ]] && return 0
    printf '%s\n' "${keys[@]}"
}

_node_version_or_absent() {
    if command -v node &>/dev/null; then
        node --version 2>/dev/null || echo "unknown"
    else
        echo "absent"
    fi
}

_node_floor_ok() {
    command -v node &>/dev/null || return 1
    local v major
    v="$(node --version 2>/dev/null)" || return 1
    major="${v#v}"
    major="${major%%.*}"
    [[ "$major" =~ ^[0-9]+$ ]] || return 1
    [[ "$major" -ge "$HOS_NODE_FLOOR_MAJOR" ]]
}

tool_preflight_or_fail() {
    # Audited escape hatch — SUSPENDED: tools in contract/gate-suspension.md.
    if is_suspended "tools"; then
        print_suspended "tools"
        return 0
    fi

    local mode="${HOS_REQUIRE_TOOLS:-enforce}"

    local -a required=()
    while IFS= read -r key; do
        [[ -n "$key" ]] && required+=("$key")
    done < <(detect_required_tools)

    [[ ${#required[@]} -eq 0 ]] && return 0

    local -a missing=()
    local key
    for key in "${required[@]}"; do
        case "$key" in
            node-floor)
                _node_floor_ok || missing+=("node (>= ${HOS_NODE_FLOOR_MAJOR}; found: $(_node_version_or_absent))")
                ;;
            *)
                resolve_node_tool "$key" >/dev/null 2>&1 || missing+=("$key")
                ;;
        esac
    done

    [[ ${#missing[@]} -eq 0 ]] && return 0

    {
        echo "tool_preflight: required tool(s) missing for this project (ADR-032, D1):"
        for key in "${missing[@]}"; do
            echo "  - $key"
        done
        echo ""
        echo "HOS detected a JS/Astro project and these tools are depended-on but not"
        echo "resolvable via ./node_modules/.bin, 'npx --no-install', or PATH. HOS never"
        echo "installs tooling (D2) — install the missing tool(s) in the consumer"
        echo "project, then re-run."
        echo ""
        echo "Escape hatches (audited):"
        echo "  - HOS_REQUIRE_TOOLS=warn   downgrade this run to a non-fatal warning"
        echo "  - SUSPENDED: tools         in contract/gate-suspension.md (human-authorized)"
    } >&2

    if [[ "$mode" == "warn" ]]; then
        echo "tool_preflight: WARN mode (HOS_REQUIRE_TOOLS=warn) — continuing despite missing tools" >&2
        return 0
    fi

    return 1
}
