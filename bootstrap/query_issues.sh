#!/usr/bin/env bash
# bootstrap/query_issues.sh — canonical read-side wrapper for GitHub issue and
# PR queries under a HOS bot identity (#1192, consolidated by #1204)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> one
# `gh api` read -> revoke the token. One script invocation, no loops or
# substitution at the call site — see CLAUDE.md "Shell usage under the
# sandbox" for why that matters on Worker/Overseer (an unallowlistable
# command hangs with nobody present to approve it).
#
# Usage (exactly one query mode per invocation):
#   bash bootstrap/query_issues.sh --app <worker|overseer|human> --issue <N[,N,...]> [--full]
#   bash bootstrap/query_issues.sh --app <worker|overseer|human> --list [--milestone <title-prefix>|--milestone-less] [--label <l>] [--state <s>]
#   bash bootstrap/query_issues.sh --app <worker|overseer|human> --comments <N>
#   bash bootstrap/query_issues.sh --app <worker|overseer|human> --assignable-users
#
# --full (--issue only) appends the raw issue body after the summary line, so
# a caller can grep it for a `Decision:` block (#1277) without a hand-rolled
# `gh api` read. Omitted by default so existing callers and their output
# parsing are unaffected.
#
# REST only (GITHUB API — REST only rule in bootstrap/worker-cron-prompt.md):
# no `gh issue list`, no `gh pr view --json`. The REST issues endpoints return
# both issues and PRs, so every listing mode here filters out PRs
# (`.pull_request == null`) before printing.
#
# Milestone titles in this repo are full strings with an em dash (e.g.
# "v0.6.0 — Astro & JS Support"), so --milestone matches by PREFIX and
# resolves to a numeric id before being sent to the REST API. An issue with
# no milestone renders as "NONE", never an empty field.
#
# Requires: bootstrap/get_app_token.sh, gh, git (to resolve owner/repo from
# the 'origin' remote), curl (token revocation), jq (filtering/formatting).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

APP_ROLE=""
ISSUE_NUMBERS=""
FULL_MODE=0
LIST_MODE=0
MILESTONE_ARG=""
MILESTONE_LESS=0
LABEL_FILTER=""
STATE_FILTER=""
COMMENTS_NUMBER=""
ASSIGNABLE_USERS=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --app)              APP_ROLE="$2"; shift 2 ;;
        --issue)            ISSUE_NUMBERS="$2"; shift 2 ;;
        --full)             FULL_MODE=1; shift ;;
        --list)             LIST_MODE=1; shift ;;
        --milestone)        MILESTONE_ARG="$2"; shift 2 ;;
        --milestone-less)   MILESTONE_LESS=1; shift ;;
        --label)            LABEL_FILTER="$2"; shift 2 ;;
        --state)            STATE_FILTER="$2"; shift 2 ;;
        --comments)         COMMENTS_NUMBER="$2"; shift 2 ;;
        --assignable-users) ASSIGNABLE_USERS=1; shift ;;
        *) err "Usage: $0 --app <worker|overseer|human> (--issue <N[,N,...]> [--full] | --list [--milestone <prefix>|--milestone-less] [--label <l>] [--state <s>] | --comments <N> | --assignable-users)" ;;
    esac
done

[[ -n "$APP_ROLE" ]] || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac

MODE_COUNT=0
[[ -n "$ISSUE_NUMBERS" ]] && MODE_COUNT=$((MODE_COUNT + 1))
[[ "$LIST_MODE" -eq 1 ]] && MODE_COUNT=$((MODE_COUNT + 1))
[[ -n "$COMMENTS_NUMBER" ]] && MODE_COUNT=$((MODE_COUNT + 1))
[[ "$ASSIGNABLE_USERS" -eq 1 ]] && MODE_COUNT=$((MODE_COUNT + 1))
[[ "$MODE_COUNT" -eq 1 ]] || err "exactly one of --issue, --list, --comments, --assignable-users is required"

if [[ -n "$MILESTONE_ARG" && "$MILESTONE_LESS" -eq 1 ]]; then
    err "--milestone and --milestone-less are mutually exclusive"
fi
if [[ "$FULL_MODE" -eq 1 && -z "$ISSUE_NUMBERS" ]]; then
    err "--full requires --issue"
fi
if [[ -n "$STATE_FILTER" ]]; then
    case "$STATE_FILTER" in
        open|closed|all) ;;
        *) err "--state must be 'open', 'closed', or 'all'" ;;
    esac
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

fail() {
    revoke_token
    err "$1"
}

resolve_milestone_id() {
    local prefix="$1" milestones matches count
    milestones="$(gh api "repos/${REPO_SLUG}/milestones?state=all&per_page=100")" \
        || fail "failed to list milestones"
    matches="$(printf '%s' "$milestones" | jq -r --arg prefix "$prefix" \
        '.[] | select(.title | startswith($prefix)) | "\(.number)\t\(.title)"')"
    [[ -n "$matches" ]] || fail "no milestone found matching prefix: $prefix"
    count="$(printf '%s\n' "$matches" | wc -l)"
    if [[ "$count" -gt 1 ]]; then
        fail "milestone prefix '$prefix' is ambiguous — matches: $(printf '%s' "$matches" | cut -f2 | tr '\n' '|')"
    fi
    printf '%s' "$matches" | cut -f1
}

ISSUE_LINE_FILTER='"#\(.number) milestone=\(if .milestone then .milestone.title else "NONE" end) state=\(.state) labels=\(.labels | map(.name) | join(",")) \(.title)"'
ISSUE_FULL_FILTER="${ISSUE_LINE_FILTER} + \"\n\n\" + (.body // \"\")"

if [[ -n "$ISSUE_NUMBERS" ]]; then
    ISSUE_FILTER="$ISSUE_LINE_FILTER"
    [[ "$FULL_MODE" -eq 1 ]] && ISSUE_FILTER="$ISSUE_FULL_FILTER"
    IFS=',' read -r -a NUMS <<< "$ISSUE_NUMBERS"
    for n in "${NUMS[@]}"; do
        case "$n" in
            ''|*[!0-9]*) fail "--issue must be a comma-separated list of positive integers, got: $ISSUE_NUMBERS" ;;
        esac
        gh api "repos/${REPO_SLUG}/issues/${n}" --jq "$ISSUE_FILTER" \
            || fail "failed to read issue #${n}"
    done

elif [[ "$LIST_MODE" -eq 1 ]]; then
    QUERY="per_page=100"
    if [[ -n "$MILESTONE_ARG" ]]; then
        MILESTONE_ID="$(resolve_milestone_id "$MILESTONE_ARG")"
        QUERY="${QUERY}&milestone=${MILESTONE_ID}"
    elif [[ "$MILESTONE_LESS" -eq 1 ]]; then
        QUERY="${QUERY}&milestone=none"
    fi
    [[ -n "$LABEL_FILTER" ]] && QUERY="${QUERY}&labels=${LABEL_FILTER}"
    QUERY="${QUERY}&state=${STATE_FILTER:-open}"
    gh api "repos/${REPO_SLUG}/issues?${QUERY}" --jq \
        ".[] | select(.pull_request == null) | ${ISSUE_LINE_FILTER}" \
        || fail "failed to list issues"

elif [[ -n "$COMMENTS_NUMBER" ]]; then
    case "$COMMENTS_NUMBER" in
        ''|*[!0-9]*) fail "--comments must be a positive integer, got: $COMMENTS_NUMBER" ;;
    esac
    gh api "repos/${REPO_SLUG}/issues/${COMMENTS_NUMBER}/comments?per_page=100" --jq \
        '.[] | "--- \(.user.login) @ \(.created_at) ---\n\(.body)\n"' \
        || fail "failed to read comments for issue #${COMMENTS_NUMBER}"

elif [[ "$ASSIGNABLE_USERS" -eq 1 ]]; then
    gh api "repos/${REPO_SLUG}/assignees?per_page=100" --jq '.[].login' \
        || fail "failed to list assignable users"
fi

revoke_token
