#!/usr/bin/env bash
# bootstrap/post_comment.sh — canonical wrapper for posting a GitHub issue/PR
# comment under a HOS bot identity (#1155)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> `gh
# issue comment --body-file` -> revoke the token. One script invocation, no
# loops or substitution at the call site — see CLAUDE.md "Shell usage under
# the sandbox" for why that matters on Worker/Overseer (an unallowlistable
# command hangs with nobody present to approve it).
#
# Usage:
#   bash bootstrap/post_comment.sh --number <N> --body-file <path> --app <worker|overseer|human>
#
# --number accepts either an issue number or a PR number — PRs are issues in
# GitHub's data model, so `gh issue comment` posts to the same
# issues/{n}/comments thread that PR conversation comments live in.
#
# --body-file only, never inline --body <text>: comment bodies are markdown,
# routinely contain newlines/quotes, and are frequently written to a scratch
# file first — exactly the unallowlistable $(...)/heredoc shell pattern this
# script exists to eliminate. It is ALSO the only safe way to post
# file-derived content: a raw `gh api --field body=@path` (or `-f`/
# `--raw-field`) silently posts the LITERAL string "@path" instead of the
# file's contents, because gh's `--field` type coercion only expands `@path`
# for flags actually documented to do so (`--body-file` here), not for
# `-f`/`--field` on arbitrary endpoints. That exact trap produced a
# delivered-nothing PR review comment in #1155.
#
# Requires: bootstrap/get_app_token.sh, gh, git (to resolve owner/repo from
# the 'origin' remote), curl (token revocation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

NUMBER=""
BODY_FILE=""
APP_ROLE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --number)    NUMBER="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --app)       APP_ROLE="$2"; shift 2 ;;
        --body)      err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *)           err "Usage: $0 --number <N> --body-file <path> --app <worker|overseer|human>" ;;
    esac
done

[[ -n "$NUMBER" ]]    || err "--number required"
[[ -n "$BODY_FILE" ]] || err "--body-file required"
[[ -f "$BODY_FILE" ]] || err "--body-file not found: $BODY_FILE"
[[ -n "$APP_ROLE" ]]  || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac
case "$NUMBER" in
    ''|*[!0-9]*) err "--number must be a positive integer, got: $NUMBER" ;;
esac

# Guard the exact #1155 failure mode: a body file that is itself an @path
# literal (e.g. produced upstream by a mis-composed `gh api --field
# body=@path` call) rather than real comment content.
if [[ "$(head -c 2 -- "$BODY_FILE" 2>/dev/null)" == "@/" ]]; then
    err "--body-file content starts with '@/' — looks like an @path literal was written instead of comment content (#1155)"
fi

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

if ! COMMENT_URL="$(gh issue comment "$NUMBER" --repo "$REPO_SLUG" --body-file "$BODY_FILE")"; then
    revoke_token
    err "gh issue comment failed"
fi

revoke_token
echo "$COMMENT_URL"
