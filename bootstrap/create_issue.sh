#!/usr/bin/env bash
# bootstrap/create_issue.sh — canonical wrapper for creating a GitHub issue
# under a HOS bot identity (#1085)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> `gh
# issue create` -> revoke the token. One script invocation, no loops or
# substitution at the call site — see CLAUDE.md "Shell usage under the
# sandbox" for why that matters on Worker/Overseer (an unallowlistable
# command hangs with nobody present to approve it).
#
# Usage:
#   bash bootstrap/create_issue.sh --title <text> --body-file <path> \
#     --label <labels> --app <worker|overseer|human>
#
#   --label accepts a comma-separated list, e.g. --label "priority:high,needs-ai"
#
# --body-file only, never inline --body <text>: issue bodies contain
# newlines and quotes, which is exactly the unallowlistable $(...)/quoted-
# shell pattern this script exists to eliminate.
#
# Requires: bootstrap/get_app_token.sh, gh, git (to resolve owner/repo from
# the 'origin' remote), curl (token revocation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

TITLE=""
BODY_FILE=""
LABELS=""
APP_ROLE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --title)     TITLE="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --label)     LABELS="$2"; shift 2 ;;
        --app)       APP_ROLE="$2"; shift 2 ;;
        --body)      err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *)           err "Usage: $0 --title <text> --body-file <path> --label <labels> --app <worker|overseer|human>" ;;
    esac
done

[[ -n "$TITLE" ]]     || err "--title required"
[[ -n "$BODY_FILE" ]] || err "--body-file required"
[[ -f "$BODY_FILE" ]] || err "--body-file not found: $BODY_FILE"
[[ -n "$APP_ROLE" ]]  || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac

# ── Resolve owner/repo from the origin remote (no auth required) ──────────────
REPO_URL="$(git -C "$SCRIPT_DIR/.." remote get-url origin 2>/dev/null)" \
    || err "Could not read git remote 'origin' — run from inside the HOS repo"
REPO_SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^git@github\.com:##; s#^https://github\.com/##; s#\.git$##')"
[[ "$REPO_SLUG" == */* ]] || err "Could not parse owner/repo from origin remote: $REPO_URL"

# ── Mint token, source it, then remove the file immediately (#549: don't let
# the token linger on disk any longer than it has to) ─────────────────────────
TOKEN_FILE="$(mktemp)"
trap 'rm -f "$TOKEN_FILE"' EXIT

bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE" || err "Failed to mint ${APP_ROLE} token"
# shellcheck source=/dev/null
source "$TOKEN_FILE"
rm -f "$TOKEN_FILE"

revoke_token() {
    curl -sf -X DELETE -H "Authorization: token ${GH_TOKEN}" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/installation/token >/dev/null 2>&1 \
        || warn "failed to revoke installation token (it will expire naturally within 1 hour)"
}

LABEL_ARGS=()
[[ -n "$LABELS" ]] && LABEL_ARGS=(--label "$LABELS")

if ! ISSUE_URL="$(gh issue create --repo "$REPO_SLUG" --title "$TITLE" --body-file "$BODY_FILE" "${LABEL_ARGS[@]}")"; then
    revoke_token
    err "gh issue create failed"
fi

revoke_token
echo "$ISSUE_URL"
