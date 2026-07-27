#!/usr/bin/env bash
# resolve_node_tool.sh — discover-only consumer JS toolchain resolver (D2, ADR-032).
#
# Sourced lib, one function: `resolve_node_tool <tool>`. Prints an invocable
# command for <tool> to stdout and returns 0 when found; prints nothing and
# returns 1 when not found. NEVER installs anything, NEVER ships node_modules,
# NEVER triggers a network fetch — a consumer's missing tool is the consumer's
# to install (D1: HOS never installs).
#
# Resolution order (D2):
#   1. ./node_modules/.bin/<tool>   — project-local install, highest priority
#   2. `npx --no-install <tool>`    — probed with `--version` (no install prompt,
#                                      no network); accepted for the current tool
#                                      set {eslint, tsc, astro, astro-check} which
#                                      all support --version (DQ-6). Do not add a
#                                      tool lacking --version without revisiting.
#   3. PATH                         — command -v <tool>
#
# Safe under a caller running `set -euo pipefail`: every fallible command sits
# inside an `if`/`&&` test, so a "not found" result returns normally (rc1)
# rather than aborting the caller's shell.
#
# Usage:
#   source ".../lib/resolve_node_tool.sh"
#   if cmd=$(resolve_node_tool eslint); then
#       $cmd --version
#   fi

resolve_node_tool() {
    local tool="$1"

    if [[ -x "./node_modules/.bin/${tool}" ]]; then
        printf '%s\n' "./node_modules/.bin/${tool}"
        return 0
    fi

    if command -v npx &>/dev/null; then
        if npx --no-install "$tool" --version &>/dev/null; then
            printf 'npx --no-install %s\n' "$tool"
            return 0
        fi
    fi

    if command -v "$tool" &>/dev/null; then
        printf '%s\n' "$tool"
        return 0
    fi

    return 1
}
