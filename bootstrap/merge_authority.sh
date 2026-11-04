#!/usr/bin/env bash
# bootstrap/merge_authority.sh — L3 wrapper for the merge-authority primitive
# surface: read-only queries (#1357) plus the overseer's route and bounce (#2209).
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
#   bash bootstrap/merge_authority.sh route              --app overseer --pr <N> --step <N> --findings-file <path> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh bounce             --app overseer --pr <N> --step <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh approval-merge     --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#   bash bootstrap/merge_authority.sh merge-provenance   --app <worker|overseer|human> --pr <N> [--repo <o/r>]
#
# --app accepts both `--app overseer` and `--app=overseer` forms.
#
# Exit codes (owned entirely by merge_authority_cli.py — see its module
# docstring and docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md
# §3.3; this script never computes one of its own):
#   0 — the question was answered (whatever the answer)
#   1 — operational failure (auth, API error, malformed data, missing config)
#   2 — usage error (unknown subcommand/flag, missing required flag, ...)
#   3 — reserved (S1b)
#
# stdout is exactly one JSON object, always — it is merge_authority_cli.py's,
# passed through byte-for-byte. Never suppress this script's stderr (#1523).
#
# Every subcommand except route and bounce is read-only. route and bounce write
# (a comment, an audit event, a label, the draft state), only with
# `--app overseer`, and neither can merge anything.
#
# The record schema is owned by merge_authority_cli.py alone (#1357 ARCH-3a).
# This script must never grow a JSON literal, a printf/echo to stdout, or any
# re-derivation of a field — adding an envelope field is a change to that
# module only, never to this one.
#
# Requires: bootstrap/get_app_token.sh (minted only for the ten subcommands
# that read from GitHub — register and bounce-count are local-only and never
# mint), bootstrap/revoke_app_token.sh (revokes only a token this script
# minted), python3.

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
    gate|human-approval|hold-directive|protected-surface|security-surface|codeowners|approval-merge|merge-provenance)
        case "$APP_ROLE" in
            worker|overseer|human) MINT_TOKEN=true ;;
        esac
        ;;
    route|bounce)
        # Mutation subcommands: only the overseer mints. Any other role mints
        # nothing and merge_authority_cli.py rejects it with exit 2.
        if [[ "$APP_ROLE" == "overseer" ]]; then
            MINT_TOKEN=true
        fi
        ;;
esac

# ── Mint (only for a recognised network invocation) and register revocation ─
# Revocation of a token THIS script minted is a forced side effect of exiting,
# regardless of the child's exit code (TW.6). A GH_TOKEN inherited from the
# caller (e.g. the cron cycle's own installation token) is not ours to
# revoke: on a non-minting invocation (register / bounce-count / unknown
# --app) or a failed mint it would otherwise be killed mid-cycle (#2117).
# _MINT_ATTEMPTED (set once the mint path starts) gates the revoke call.
TOKEN_FILE=""
_MINT_ATTEMPTED=0
_GH_CONFIG_TMP=""
_MERGE_AUTHORITY_REVOKED=0

revoke_token() {
    # Idempotency guard: the signal trap below and the EXIT trap that follows
    # it can both reach this function for the same process, and this keeps
    # the revoke firing exactly once.
    if [[ "$_MERGE_AUTHORITY_REVOKED" == "1" ]]; then
        return
    fi
    _MERGE_AUTHORITY_REVOKED=1
    if [[ -n "$TOKEN_FILE" ]]; then
        rm -f "$TOKEN_FILE"
    fi
    if [[ -n "$_GH_CONFIG_TMP" ]]; then
        rm -rf "$_GH_CONFIG_TMP"
    fi
    # bootstrap/revoke_app_token.sh (#1191) — never inline the DELETE curl
    # here: it has no timeout, so a network stall inside this EXIT trap would
    # block process exit indefinitely. revoke_app_token.sh bounds the call
    # with --connect-timeout/--max-time, is idempotent, and is fail-open with
    # a warning (the token expires naturally within the hour either way).
    if [[ "$_MINT_ATTEMPTED" == "1" ]]; then
        bash "$SCRIPT_DIR/revoke_app_token.sh"
    fi
}

# A cron-imposed SIGTERM (or an operator SIGINT) kills this script without
# running an EXIT trap, which would leave the minted installation token live
# until its natural expiry. Route INT/TERM through revoke_token, then
# re-raise the signal against the default disposition (after clearing our own
# traps, so the re-raise cannot re-enter this handler) so the parent still
# observes the conventional 128+signal exit status. Mirrors pr_review.sh.
_on_signal() {
    local sig="$1"
    revoke_token
    trap - EXIT INT TERM
    kill -s "$sig" "$$"
}
trap revoke_token EXIT
trap '_on_signal INT' INT
trap '_on_signal TERM' TERM

if $MINT_TOKEN; then
    # Scrub inherited credentials before the mint (#2117; same binding fix as
    # TD-1520-S1 §7.1 step 3a): a failed mint must never proceed under the
    # caller's identity. Non-minting invocations skip this and keep the
    # inherited environment, which the CLI then sees untouched.
    unset GH_TOKEN GITHUB_TOKEN HOS_BOT_LOGIN HOS_EXPECTED_BOT_LOGIN
    # Set before the mint, not after it: a signal landing between the mint
    # and a later assignment (or a `source` failing partway under set -e)
    # would otherwise skip revoking a live token. After the scrub above any
    # GH_TOKEN can only be one this script minted, and on a failed mint it
    # stays empty, where revoke_app_token.sh is a documented no-op ("No
    # GH_TOKEN set — nothing to revoke", exit 0). Gating on "the mint path
    # ran" closes the window without ever touching an inherited token.
    _MINT_ATTEMPTED=1
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
        # Warn first: under set -e a mktemp failure below would otherwise abort
        # before the operator learns the mint failed.
        echo "merge_authority.sh: warning: failed to mint ${APP_ROLE} token — proceeding without credentials (inherited identity scrubbed)" >&2
        # Neutralise gh's fallback to the host's stored login
        # (~/.config/gh/hosts.yml): after the scrub above and a failed mint
        # that would silently run under an unintended identity (#2117). An
        # empty GH_CONFIG_DIR leaves gh with no stored auth, so the fetch
        # fails and the CLI alone emits the exit-1 envelope.
        _GH_CONFIG_TMP="$(mktemp -d)"
        export GH_CONFIG_DIR="$_GH_CONFIG_TMP"
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
