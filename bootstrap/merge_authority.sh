#!/usr/bin/env bash
# bootstrap/merge_authority.sh — L3 wrapper for the merge-authority
# read-only primitive surface (#1357 slice 1).
#
# Across the entire recoverable audit history the merge-authority matrix has
# never been invoked — an agent whose only capability is issuing shell
# commands was told to call Python functions directly, which is not a shell
# command, so it narrated the answer instead of computing it. This script
# (and the ones that follow it in later slices) is the fix: a fixed,
# statically-allowlistable argv shape over
# scripts/automation/merge_authority_cli.py, which does the actual fetching
# and deciding.
#
# Usage (subcommand is a positional keyword from a closed enum — it carries
# no content, so the argv shape is fixed end to end):
#   bash bootstrap/merge_authority.sh gate               --app <worker|overseer|human> [--repo <o/r>] [--branch <name>]
#   bash bootstrap/merge_authority.sh register           --app <worker|overseer|human> --step <N>
#   bash bootstrap/merge_authority.sh bounce-count       --app <worker|overseer|human> --cid <cid>
#   bash bootstrap/merge_authority.sh human-approval     --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh hold-directive     --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh protected-surface  --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh security-surface   --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh codeowners         --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#
# --app accepts both `--app overseer` and `--app=overseer` forms.
#
# Exit codes (owned entirely by merge_authority_cli.py — see its module
# docstring and docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md
# §3.3; this script never computes one of its own):
#   0 — the question was answered (whatever the answer)
#   1 — operational failure (auth, API error, malformed data, missing config)
#   2 — usage error (unknown subcommand/flag, missing required flag, ...)
#   3 — never produced by this surface; reserved for the mutation wrappers a
#       later slice adds
#
# stdout is exactly one JSON object, always — it is merge_authority_cli.py's,
# passed through byte-for-byte. Never suppress this script's stderr (#1523).
#
# Read-only: this script performs no GitHub write, applies no label, posts no
# comment, and can merge nothing.
#
# The record schema is owned by merge_authority_cli.py alone (#1357 ARCH-3a).
# This script must never grow a JSON literal, a printf/echo to stdout, or any
# re-derivation of a field — adding an envelope field is a change to that
# module only, never to this one.
#
# Requires: bootstrap/get_app_token.sh (minted only for the six subcommands
# that read from GitHub — register and bounce-count are local-only and never
# mint), python3, curl (token revocation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

# ── Extract, do not validate (ARCH-3a) ──────────────────────────────────────
# Read the two values needed to decide whether to mint a token: the
# subcommand token and the --app value. This step emits no JSON, prints no
# usage text, and rejects nothing. An absent or unrecognised subcommand/app
# simply means no token is minted — control still reaches
# merge_authority_cli.py below, where argparse alone produces the single
# canonical exit-2 envelope. Python is the sole author of the record schema
# (§3.2); adding a field there must never require editing this script.

SUBCOMMAND=""
if [[ $# -gt 0 && "${1:0:1}" != "-" ]]; then
    SUBCOMMAND="$1"
fi

APP_ROLE=""
_prev_arg=""
for _arg in "$@"; do
    case "$_arg" in
        --app=*) APP_ROLE="${_arg#--app=}" ;;
    esac
    if [[ "$_prev_arg" == "--app" ]]; then
        APP_ROLE="$_arg"
    fi
    _prev_arg="$_arg"
done
unset _prev_arg _arg

MINT_TOKEN=false
case "$SUBCOMMAND" in
    gate|human-approval|hold-directive|protected-surface|security-surface|codeowners)
        case "$APP_ROLE" in
            worker|overseer|human) MINT_TOKEN=true ;;
        esac
        ;;
esac

# ── Mint (only for a recognised network invocation) and register revocation ─
# Token revocation is a forced side effect of this script exiting, regardless
# of whether a token was ever actually minted (TOKEN_FILE / GH_TOKEN unset is
# a no-op below) and regardless of the child's exit code (TW.6).
TOKEN_FILE=""

revoke_token() {
    if [[ -n "$TOKEN_FILE" ]]; then
        rm -f "$TOKEN_FILE"
    fi
    if [[ -n "${GH_TOKEN:-}" ]]; then
        curl -sf -X DELETE -H "Authorization: token ${GH_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/installation/token >/dev/null 2>&1 \
            || echo "merge_authority.sh: warning: failed to revoke installation token (it will expire naturally within 1 hour)" >&2
    fi
}
trap revoke_token EXIT

if $MINT_TOKEN; then
    TOKEN_FILE="$(mktemp)"
    if bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE"; then
        # shellcheck source=/dev/null
        source "$TOKEN_FILE"
    else
        # A mint failure is an operational condition, not something bash
        # decides the outcome of (ARCH-3a: no decision reachable only through
        # bash). Proceed without a token: merge_authority_cli.py's own GitHub
        # fetch will then fail and it alone emits the exit-1 envelope naming
        # the cause — the "auth failure escaping a required fetch" row of
        # §3.3's exit-code table — so AD-2 rule 2's "stdout is exactly one
        # JSON object, always" still holds on this path.
        echo "merge_authority.sh: warning: failed to mint ${APP_ROLE} token — proceeding without one" >&2
    fi
    rm -f "$TOKEN_FILE"
    TOKEN_FILE=""
fi

# ── Invoke, passing argv through verbatim and unreordered ──────────────────
# No jq, no capture, no reformatting of the child's stdout — it passes
# straight through so AD-2 rule 2 holds byte-for-byte. Stderr is not
# redirected either.
set +e
python3 "$REPO_ROOT/scripts/automation/merge_authority_cli.py" "$@"
RC=$?
set -e

# ── Exit with the child's code unmodified; revoke_token fires via the trap ─
exit "$RC"
