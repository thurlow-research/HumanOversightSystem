#!/usr/bin/env bash
# bootstrap/revoke_app_token.sh — revoke the GitHub App installation token
# currently held in GH_TOKEN (#1191)
#
# get_app_token.sh mints a token and exports it into the caller's shell as
# GH_TOKEN. Until this script existed, revoking that token meant hand-rolling
# `curl -X DELETE -H "Authorization: token $GH_TOKEN" ...` at the call site —
# a $VAR simple_expansion that CLAUDE.md's "Shell usage under the sandbox"
# flags as structurally unallowlistable (no "Always allow" button; on
# Worker/Overseer, nobody is present to approve it, so it hangs).
#
# This script takes no token argument. It reads GH_TOKEN from the process
# environment it inherits as a child process, so the call site is exactly:
#
#   bash bootstrap/revoke_app_token.sh
#
# No $VAR expansion, no $(...), no heredoc at the call site — statically
# allowlistable.
#
# Idempotent: an absent, empty, or already-revoked token is not an error —
# exits 0 in all three cases. Never prints, logs, or echoes the token value
# (#1086); only a confirmation line on stderr, following get_app_token.sh's
# convention.
#
# Requires: curl
#
# See also: get_app_token.sh (mints the token this script revokes),
# create_issue.sh / submit_pr.sh / post_comment.sh (mint-act-revoke wrappers
# that already inline this pattern for their own call sites).

set -uo pipefail

GREEN="\033[32m"; CYAN="\033[36m"; YELLOW="\033[33m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*" >&2; }
info() { echo -e "  ${CYAN}→${RESET}  $*" >&2; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

if [[ -z "${GH_TOKEN:-}" ]]; then
    info "No GH_TOKEN set — nothing to revoke"
    exit 0
fi

info "Revoking installation token..."
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 30 \
    -X DELETE \
    -H "Authorization: token ${GH_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    https://api.github.com/installation/token)"
CURL_STATUS=$?

if [[ $CURL_STATUS -ne 0 ]]; then
    warn "revoke request failed to reach GitHub (curl exit ${CURL_STATUS}) — token will expire naturally within 1 hour"
    exit 0
fi

case "$HTTP_CODE" in
    204) ok "Token revoked" ;;
    401|403|404) warn "token already invalid or revoked (HTTP ${HTTP_CODE})" ;;
    *)   warn "unexpected response revoking token (HTTP ${HTTP_CODE}) — it will expire naturally within 1 hour" ;;
esac

exit 0
