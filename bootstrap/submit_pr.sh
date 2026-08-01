#!/usr/bin/env bash
# bootstrap/submit_pr.sh — canonical wrapper for pushing a branch and opening
# a PR under a HOS bot identity (#1085)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> `git
# push` (token embedded in the remote URL for that ONE push only — never
# written to .git/config, which is write-protected under the Human sandbox
# and must not carry a lingering credential anyway) -> `gh pr create` ->
# revoke the token. One script invocation, no loops or substitution at the
# call site — see CLAUDE.md "Shell usage under the sandbox".
#
# Usage:
#   bash bootstrap/submit_pr.sh --title <text> --body-file <path> --base <branch> \
#     [--head <branch>] --app <worker|overseer|human> [--confirmed]
#
# --head defaults to the current branch.
#
# --app human requires --confirmed: per docs/AGENT-IDENTITY.md, a human-proxy
# PR is only appropriate in the stuck-worker exception, with explicit
# per-instance human authorization, always via PR + overseer review, never
# self-merge. --confirmed asserts a human has actually approved THIS push for
# THIS instance — it is not a standing config flag a session can set once and
# forget. --app worker / --app overseer (the autonomous pipeline's own
# identities) don't require it.
#
# --body-file only, never inline --body <text> (same reasoning as
# create_issue.sh: newlines/quotes in an inline body are exactly the
# unallowlistable $(...)/quoted-shell pattern these scripts exist to
# eliminate).
#
# Requires: bootstrap/get_app_token.sh, gh, git (push + to resolve owner/repo
# from the 'origin' remote), curl (token revocation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

TITLE=""
BODY_FILE=""
BASE=""
HEAD=""
APP_ROLE=""
CONFIRMED="false"

while [[ $# -gt 0 ]]; do
    case $1 in
        --title)     TITLE="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --base)      BASE="$2"; shift 2 ;;
        --head)      HEAD="$2"; shift 2 ;;
        --app)       APP_ROLE="$2"; shift 2 ;;
        --confirmed) CONFIRMED="true"; shift ;;
        --body)      err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *)           err "Usage: $0 --title <text> --body-file <path> --base <branch> [--head <branch>] --app <worker|overseer|human> [--confirmed]" ;;
    esac
done

[[ -n "$TITLE" ]]     || err "--title required"
[[ -n "$BODY_FILE" ]] || err "--body-file required"
[[ -f "$BODY_FILE" ]] || err "--body-file not found: $BODY_FILE"
[[ -n "$BASE" ]]      || err "--base required"
[[ -n "$APP_ROLE" ]]  || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac

if [[ "$APP_ROLE" == "human" && "$CONFIRMED" != "true" ]]; then
    err "--app human requires --confirmed: a human-proxy PR is only appropriate with explicit per-instance human authorization (docs/AGENT-IDENTITY.md, stuck-worker exception). Confirm a human has approved THIS push, then pass --confirmed."
fi

[[ -n "$HEAD" ]] || HEAD="$(git -C "$SCRIPT_DIR/.." rev-parse --abbrev-ref HEAD)"
[[ "$HEAD" != "HEAD" ]] || err "Could not determine current branch (detached HEAD) — pass --head <branch>"

# ── Merge from base before pushing (#1162) ─────────────────────────────────────
# A branch built on a stale base doesn't just miss the work that landed on
# main while it was being built — its PR proposes *reverting* that work, and
# the diff looks entirely normal until inspected. Fetch the base and merge it
# in here, before anything else touches the network, so a stale base can never
# reach `gh pr create`. Read-only (fetch + local merge); no token required.
git -C "$SCRIPT_DIR/.." fetch origin "$BASE" \
    || err "Could not fetch origin/${BASE} — resolve network/auth before opening a PR"

BEHIND_COUNT="$(git -C "$SCRIPT_DIR/.." rev-list --count "HEAD..origin/${BASE}")"
if [[ "$BEHIND_COUNT" -gt 0 ]]; then
    warn "${HEAD} is ${BEHIND_COUNT} commit(s) behind origin/${BASE} — merging base in before push"
    if ! git -C "$SCRIPT_DIR/.." merge --no-edit "origin/${BASE}"; then
        git -C "$SCRIPT_DIR/.." merge --abort 2>/dev/null || true
        err "Merging origin/${BASE} into ${HEAD} produced conflicts — resolve manually (git fetch origin ${BASE} && git merge origin/${BASE}, fix conflicts, commit), then retry submit_pr.sh. Never push a branch built on a stale base: its PR would silently propose reverting the commits it's missing (#1162)."
    fi
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

# Token lives in the URL only for this one push, never in .git/config or any
# remote name — passed directly as the push destination.
PUSH_URL="https://x-access-token:${GH_TOKEN}@github.com/${REPO_SLUG}.git"
if ! git -C "$SCRIPT_DIR/.." push "$PUSH_URL" "HEAD:refs/heads/${HEAD}"; then
    revoke_token
    err "git push failed"
fi
PUSH_URL=""

if ! PR_URL="$(gh pr create --repo "$REPO_SLUG" --title "$TITLE" --body-file "$BODY_FILE" --base "$BASE" --head "$HEAD")"; then
    revoke_token
    err "gh pr create failed"
fi

revoke_token
echo "$PR_URL"
