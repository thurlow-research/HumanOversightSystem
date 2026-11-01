#!/usr/bin/env bash
# bootstrap/overseer_merge.sh — L3 wrapper for the merge-on-human-approval
# primitive (#2213, ADR-2213 AD-6).
#
# Wraps get_app_token.sh: mint a short-lived overseer App installation token ->
# invoke scripts/automation/overseer_merge_cli.py (L2) -> revoke the token. One
# script invocation, no loops or substitution at the call site — see CLAUDE.md
# "Shell usage under the sandbox" for why that matters on the unattended
# overseer (an unallowlistable command is denied outright, silently).
#
# Usage (the subcommand is a positional keyword from a closed enum):
#   bash bootstrap/overseer_merge.sh on-human-approval --app overseer --pr <N>
#
# This is the ONLY HOS script that can merge a PR on a human's approval
# (ADR-1357 AD-1). There is no --repo, --force, --skip-*, --head-sha or
# --dry-run: the repo comes from the clone's origin remote and the decision is
# recomputed inside the CLI on every call.
#
# --app accepts both `--app overseer` and `--app=overseer` forms.
#
# Exit codes (owned entirely by overseer_merge_cli.py; this script never
# computes one of its own):
#   0 — decided: MERGED, DEFER, NOT_ELIGIBLE or UNDETERMINABLE
#   1 — operational failure (config, identity unresolvable, write-ahead audit
#       failure, MERGE_FAILED, MERGE_UNCONFIRMED, an unhandled exception)
#   2 — usage error
#   3 — identity refusal (not the overseer)
#
# stdout is exactly one JSON object, always — it is overseer_merge_cli.py's,
# passed through byte-for-byte. Never suppress this script's stderr (#1523).
#
# The record schema is owned by overseer_merge_cli.py alone. This script must
# never grow a JSON literal, a printf/echo to stdout, or any re-derivation of a
# field.
#
# The CLI additionally requires HOS_OVERSEER_MERGE_TOKEN_MINTED=1, which this
# script exports only after a successful mint (so an argv form this script does
# not recognise as `--app overseer` can never reach the merge on an ambient
# token).
#
# Deviations from pr_review.sh (TD-2213 TD-D18): a token is minted only for
# `on-human-approval` with `--app overseer`; a mint failure exports
# HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1 (the CLI then refuses, it never falls
# back to an ambient token on this irreversible path); and only a token this
# script minted is revoked, never an inherited GH_TOKEN.
#
# Requires: bootstrap/get_app_token.sh, bootstrap/revoke_app_token.sh, python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

YELLOW="\033[33m"; RESET="\033[0m"
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

# ── Extract, do not validate (ARCH-3a) ──────────────────────────────────────
# Read the subcommand token and the --app value to decide whether to mint.
# Nothing is emitted or rejected here: control always reaches
# overseer_merge_cli.py, where argparse alone produces the canonical exit-2
# envelope.
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
    if [[ "$_prev_arg" == "--app" ]]; then APP_ROLE="$_arg"; fi
    _prev_arg="$_arg"
done
unset _prev_arg _arg

MINT_TOKEN=false
case "$SUBCOMMAND" in
    on-human-approval)
        case "$APP_ROLE" in
            overseer) MINT_TOKEN=true ;;
        esac
        ;;
esac

# Positive proof of a wrapper-minted credential: cleared here so an inherited
# value can never satisfy the CLI, exported only after a successful mint.
unset HOS_OVERSEER_MERGE_TOKEN_MINTED

# ── Mint (overseer only) and register revocation ────────────────────────────
TOKEN_FILE=""
_MINTED=0
_HOS_OVERSEER_MERGE_REVOKED=0

revoke_token() {
    # Idempotency guard: the signal trap and the EXIT trap can both reach this
    # function for the same process.
    if [[ "$_HOS_OVERSEER_MERGE_REVOKED" == "1" ]]; then
        return
    fi
    _HOS_OVERSEER_MERGE_REVOKED=1
    if [[ -n "$TOKEN_FILE" ]]; then
        rm -f "$TOKEN_FILE"
    fi
    # Revoke only a token this script minted — never an ambient GH_TOKEN.
    # revoke_app_token.sh reads GH_TOKEN from the environment, is idempotent
    # on an absent token and always exits 0 (the token expires within the hour
    # either way).
    if [[ "$_MINTED" == "1" ]]; then
        bash "$SCRIPT_DIR/revoke_app_token.sh"
    fi
}

# A cron-imposed SIGTERM (or an operator SIGINT) skips EXIT traps. Route
# INT/TERM through revoke_token, then re-raise against the default disposition
# so the parent observes the conventional 128+signal status.
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
    TOKEN_FILE="$(mktemp)"
    if bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE"; then
        # shellcheck source=/dev/null
        source "$TOKEN_FILE"
        _MINTED=1
        export HOS_OVERSEER_MERGE_TOKEN_MINTED=1
        unset HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED
    else
        # A mint failure is an operational condition, not something bash
        # decides the outcome of (ARCH-3a). The CLI refuses before any network
        # call and alone emits the exit-1 envelope naming the cause.
        export HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1
        warn "overseer_merge.sh: warning: failed to mint ${APP_ROLE} token — proceeding without one"
    fi
    rm -f "$TOKEN_FILE"
    TOKEN_FILE=""
fi

# ── Invoke, passing argv through verbatim and unreordered ──────────────────
set +e
python3 "$REPO_ROOT/scripts/automation/overseer_merge_cli.py" "$@"
RC=$?
set -e

# ── Exit with the child's code unmodified; revoke_token fires via the trap ─
exit "$RC"
