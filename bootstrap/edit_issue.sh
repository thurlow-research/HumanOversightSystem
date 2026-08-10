#!/usr/bin/env bash
# bootstrap/edit_issue.sh — canonical wrapper for editing an existing GitHub
# issue or PR's metadata under a HOS bot identity (#1175, consolidated by #1204)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> one or
# more `gh api` metadata edits -> verify + print the resulting state -> revoke
# the token. One script invocation, no loops or substitution at the call
# site — see CLAUDE.md "Shell usage under the sandbox" for why that matters on
# Worker/Overseer (an unallowlistable command hangs with nobody present to
# approve it).
#
# Usage:
#   bash bootstrap/edit_issue.sh --number <N> --app <worker|overseer|human> \
#     [--add-label <a,b>] [--remove-label <a,b>] \
#     [--milestone <title-prefix>|none] [--title <text>] \
#     [--state open|closed] [--assignee <user,user>] [--body-file <path>]
#
# At least one edit flag is required.
#
# Milestone titles in this repo are full strings with an em dash (e.g.
# "v0.6.0 — Astro & JS Support"), so they are matched by PREFIX and resolved
# to a numeric id before being sent to the REST API — `gh issue edit
# --milestone <title>` requires an exact title match and fails on a bare
# "v0.6.0". Pass --milestone none to clear an issue's milestone.
#
# --title only accepts plain text, not a file — issue titles are single-line
# by definition, unlike bodies/comments which get the --body-file-only
# treatment elsewhere in this repo.
#
# --body-file <path>, never inline --body <text> (#1085, #1312): bodies
# routinely contain newlines/quotes, which is exactly the unallowlistable
# $(...)/heredoc shell pattern this repo's write wrappers exist to eliminate.
# The replacement is wholesale, matching `gh issue edit --body-file` itself —
# not a partial patch/append. Callers that want to preserve existing content
# read the current body first (`query_issues.sh --issue <N> --full`, #1310)
# and compose the new version themselves. The body is folded into the same
# PATCH as title/state/milestone via a jq-built JSON object piped through
# `gh api --input -`, never `-f body=@path` — that flag only expands `@path`
# for documented file-accepting flags, not for `-f`/`--field` on arbitrary
# endpoints, and silently posts the literal string instead (the #1155 trap).
#
# Requires: bootstrap/get_app_token.sh, gh, git (to resolve owner/repo from
# the 'origin' remote), curl (token revocation), jq (milestone prefix match,
# PATCH body construction).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

NUMBER=""
APP_ROLE=""
ADD_LABELS=""
REMOVE_LABELS=""
MILESTONE_ARG=""
TITLE=""
STATE=""
ASSIGNEES=""
BODY_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --number)       NUMBER="$2"; shift 2 ;;
        --app)          APP_ROLE="$2"; shift 2 ;;
        --add-label)    ADD_LABELS="$2"; shift 2 ;;
        --remove-label) REMOVE_LABELS="$2"; shift 2 ;;
        --milestone)    MILESTONE_ARG="$2"; shift 2 ;;
        --title)        TITLE="$2"; shift 2 ;;
        --state)        STATE="$2"; shift 2 ;;
        --assignee)     ASSIGNEES="$2"; shift 2 ;;
        --body-file)    BODY_FILE="$2"; shift 2 ;;
        --body)         err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *) err "Usage: $0 --number <N> --app <worker|overseer|human> [--add-label <a,b>] [--remove-label <a,b>] [--milestone <title-prefix>|none] [--title <text>] [--state open|closed] [--assignee <user,user>] [--body-file <path>]" ;;
    esac
done

[[ -n "$NUMBER" ]]   || err "--number required"
case "$NUMBER" in
    ''|*[!0-9]*) err "--number must be a positive integer, got: $NUMBER" ;;
esac
[[ -n "$APP_ROLE" ]] || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac
if [[ -n "$STATE" ]]; then
    case "$STATE" in
        open|closed) ;;
        *) err "--state must be 'open' or 'closed'" ;;
    esac
fi
if [[ -z "$ADD_LABELS$REMOVE_LABELS$MILESTONE_ARG$TITLE$STATE$ASSIGNEES$BODY_FILE" ]]; then
    err "at least one edit flag is required (--add-label, --remove-label, --milestone, --title, --state, --assignee, --body-file)"
fi
if [[ -n "$BODY_FILE" ]]; then
    [[ -f "$BODY_FILE" ]] || err "--body-file not found: $BODY_FILE"
    # Guard the #1155 failure mode: a body file that is itself an @path
    # literal (e.g. produced upstream by a mis-composed `gh api --field
    # body=@path` call) rather than real issue content.
    if [[ "$(head -c 2 -- "$BODY_FILE" 2>/dev/null)" == "@/" ]]; then
        err "--body-file content starts with '@/' — looks like an @path literal was written instead of issue body content (#1155)"
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

fail() {
    revoke_token
    err "$1"
}

# ── Resolve a milestone title prefix to a numeric id (never an exact-title
# match — see header comment) ──────────────────────────────────────────────────
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

# ── title / state / milestone / body: one PATCH to the issue resource ────────
# Built as a JSON object via jq (not -f/-F args) so --body-file content —
# arbitrary length, newlines, quotes — passes through safely via --rawfile
# rather than risking the -f/-F "@path" literal trap (#1155, see header).
PATCH_JSON='{}'
[[ -n "$TITLE" ]] && PATCH_JSON="$(jq -c --arg v "$TITLE" '. + {title: $v}' <<<"$PATCH_JSON")"
[[ -n "$STATE" ]] && PATCH_JSON="$(jq -c --arg v "$STATE" '. + {state: $v}' <<<"$PATCH_JSON")"
if [[ -n "$MILESTONE_ARG" ]]; then
    if [[ "$MILESTONE_ARG" == "none" ]]; then
        PATCH_JSON="$(jq -c '. + {milestone: null}' <<<"$PATCH_JSON")"
    else
        MILESTONE_ID="$(resolve_milestone_id "$MILESTONE_ARG")"
        PATCH_JSON="$(jq -c --argjson v "$MILESTONE_ID" '. + {milestone: $v}' <<<"$PATCH_JSON")"
    fi
fi
[[ -n "$BODY_FILE" ]] && PATCH_JSON="$(jq -c --rawfile v "$BODY_FILE" '. + {body: $v}' <<<"$PATCH_JSON")"
if [[ "$PATCH_JSON" != '{}' ]]; then
    printf '%s' "$PATCH_JSON" | gh api --method PATCH "repos/${REPO_SLUG}/issues/${NUMBER}" --input - >/dev/null \
        || fail "failed to update issue #${NUMBER} (title/state/milestone/body)"
fi

# ── labels: dedicated add/remove endpoints, never a full replace, so
# concurrent label edits from other agents are never clobbered ───────────────
if [[ -n "$ADD_LABELS" ]]; then
    ADD_JSON="$(printf '%s' "$ADD_LABELS" | tr ',' '\n' | jq -R . | jq -sc '{labels: .}')"
    printf '%s' "$ADD_JSON" | gh api --method POST "repos/${REPO_SLUG}/issues/${NUMBER}/labels" --input - >/dev/null \
        || fail "failed to add label(s) '${ADD_LABELS}' to issue #${NUMBER}"
fi
if [[ -n "$REMOVE_LABELS" ]]; then
    IFS=',' read -r -a REMOVE_ARR <<< "$REMOVE_LABELS"
    for label in "${REMOVE_ARR[@]}"; do
        ENCODED_LABEL="$(printf '%s' "$label" | jq -sRr '@uri')"
        gh api --method DELETE "repos/${REPO_SLUG}/issues/${NUMBER}/labels/${ENCODED_LABEL}" >/dev/null 2>&1 \
            || warn "could not remove label '${label}' from issue #${NUMBER} (already absent, or the request failed)"
    done
fi

# ── assignees: add-only, matching the labels endpoints' non-destructive shape ─
if [[ -n "$ASSIGNEES" ]]; then
    ASSIGNEE_JSON="$(printf '%s' "$ASSIGNEES" | tr ',' '\n' | jq -R . | jq -sc '{assignees: .}')"
    printf '%s' "$ASSIGNEE_JSON" | gh api --method POST "repos/${REPO_SLUG}/issues/${NUMBER}/assignees" --input - >/dev/null \
        || fail "failed to add assignee(s) '${ASSIGNEES}' to issue #${NUMBER}"
fi

# ── verify and print the resulting state — never assume the write took ───────
RESULT="$(gh api "repos/${REPO_SLUG}/issues/${NUMBER}" --jq \
    '"#\(.number) milestone=\(if .milestone then .milestone.title else "NONE" end) state=\(.state) labels=\(.labels | map(.name) | join(",")) assignees=\(.assignees | map(.login) | join(",")) \(.title)"')" \
    || fail "edit(s) applied but failed to verify resulting state for issue #${NUMBER}"

revoke_token
echo "$RESULT"
