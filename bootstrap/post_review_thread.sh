#!/usr/bin/env bash
# bootstrap/post_review_thread.sh — canonical wrapper for posting a resolvable
# PR review thread under a HOS bot identity (#1207)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> GraphQL
# addPullRequestReviewThread -> revoke the token. One script invocation, no
# loops or substitution at the call site — see CLAUDE.md "Shell usage under
# the sandbox" for why that matters on Worker/Overseer (an unallowlistable
# command hangs with nobody present to approve it).
#
# Usage:
#   bash bootstrap/post_review_thread.sh --pr <N> --body-file <path> --app <worker|overseer|human>
#
# Why this exists, and why it is NOT the same as post_comment.sh (#1207):
# `post_comment.sh` posts to `/issues/{n}/comments` — the plain PR conversation
# thread. That surface has no `isResolved` state, so a branch-protection rule
# with `required_conversation_resolution` enabled does not block merge on it.
# A comment posted there can sit unaddressed with no gate ever seeing it.
#
# A GraphQL `addPullRequestReviewThread` mutation creates a real
# `PullRequestReviewThread` — it has an `isResolved` state, shows as an
# unresolved conversation in the GitHub UI, and DOES block merge under
# `required_conversation_resolution`. `gh pr review --comment` does NOT
# create one (it posts a review summary body with no `comments[]`, so no
# thread is created) — this was verified empirically before oversight-
# orchestrator's SPEC-222 implementation; see
# docs/v0.4.0/TECHNICAL-DESIGN-222-cp-thread-posting.md §1. This script
# reuses that same verified mutation for overseer's own blocking findings,
# which previously went through post_comment.sh and so were never gated.
#
# Threads must anchor to a file. This script anchors at FILE level on the
# first file in the PR's diff (deterministic, always in-diff, semantically
# neutral) — the same anchor oversight-orchestrator uses. The finding's own
# file/line reference, if any, belongs in the body text, not the anchor.
#
# --body-file only, never inline --body <text> — same rationale as
# post_comment.sh: comment bodies are markdown, routinely contain newlines/
# quotes, and inline text is exactly the unallowlistable shell pattern this
# script exists to eliminate.
#
# Use this script for BLOCKING overseer output — DIRTY-disposition findings,
# HUMAN_REQUIRED §8.2 escalations — anything the overseer means as "must not
# merge until a human addresses this." Use post_comment.sh for narrative-only
# output (status updates, release-gate clearance, worker-facing summaries)
# that does not need a merge-blocking gate.
#
# A bare `addPullRequestReviewThread` call, with no existing
# `pullRequestReviewId` supplied, implicitly creates a new review in PENDING
# state and attaches the thread to it. A PENDING review's comments are
# visible ONLY to the review's own author until the review is explicitly
# submitted — so this script also submits that review as a COMMENT event
# (never APPROVE/REQUEST_CHANGES: it must not assert a verdict on the
# poster's behalf, only make the pending thread visible) (#1248).
#
# Requires: bootstrap/get_app_token.sh, gh, git (to resolve owner/repo from
# the 'origin' remote), curl (token revocation), jq (parse the mutation
# response to find the implicitly-created review's REST id).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

PR_NUMBER=""
BODY_FILE=""
APP_ROLE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --pr)        PR_NUMBER="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --app)       APP_ROLE="$2"; shift 2 ;;
        --body)      err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *)           err "Usage: $0 --pr <N> --body-file <path> --app <worker|overseer|human>" ;;
    esac
done

[[ -n "$PR_NUMBER" ]]  || err "--pr required"
[[ -n "$BODY_FILE" ]]  || err "--body-file required"
[[ -f "$BODY_FILE" ]]  || err "--body-file not found: $BODY_FILE"
[[ -n "$APP_ROLE" ]]   || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac
case "$PR_NUMBER" in
    ''|*[!0-9]*) err "--pr must be a positive integer, got: $PR_NUMBER" ;;
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

fail() {
    revoke_token
    err "$1"
}

PR_NODE_ID="$(gh pr view "$PR_NUMBER" --repo "$REPO_SLUG" --json id --jq '.id')" \
    || fail "failed to resolve PR node id for #${PR_NUMBER}"
[[ -n "$PR_NODE_ID" ]] || fail "PR #${PR_NUMBER} returned an empty node id"

ANCHOR_PATH="$(gh pr view "$PR_NUMBER" --repo "$REPO_SLUG" --json files --jq '.files[0].path')" \
    || fail "failed to resolve an anchor file for PR #${PR_NUMBER}"
[[ -n "$ANCHOR_PATH" ]] || fail "PR #${PR_NUMBER} has no changed files to anchor a review thread to"

# Read the body into a variable and pass it via -f/--raw-field (always a
# literal string, no magic type conversion) — NOT -F/--field, whose
# documented @filename expansion would work here but whose int/bool/null
# auto-coercion is unsafe for arbitrary markdown findings text (e.g. a body
# that happens to read "true" or "123" would be sent as a GraphQL Boolean/Int
# instead of the String the mutation expects). Same pattern already proven
# in scripts/run_panel.sh's post_thread().
BODY_CONTENT="$(cat "$BODY_FILE")"

if ! THREAD_JSON="$(gh api graphql -f query='
  mutation($prId:ID!, $path:String!, $body:String!) {
    addPullRequestReviewThread(input:{
      pullRequestId:$prId, path:$path, subjectType:FILE, body:$body
    }) { thread { id isResolved comments(first: 1) { nodes { pullRequestReview { databaseId } } } } }
  }' -f prId="$PR_NODE_ID" -f path="$ANCHOR_PATH" -f body="$BODY_CONTENT")"; then
    fail "addPullRequestReviewThread mutation failed for PR #${PR_NUMBER}"
fi

# The mutation implicitly created a PENDING review — submit it so the thread
# becomes visible outside the posting bot's own account (#1248). Use the
# REST events endpoint, which takes the review's databaseId (an integer),
# not its GraphQL node id.
#
# `PullRequestReviewThread` has no `pullRequestReview` field (GitHub schema
# drift — #1259, #1272); the review reference lives one level down, on the
# thread's first comment (`PullRequestReviewComment.pullRequestReview`).
REVIEW_ID="$(printf '%s' "$THREAD_JSON" | jq -r '.data.addPullRequestReviewThread.thread.comments.nodes[0].pullRequestReview.databaseId // empty')"
[[ -n "$REVIEW_ID" ]] || fail "mutation succeeded but returned no review id for PR #${PR_NUMBER} — thread was created but remains PENDING and is invisible to the human"

if ! gh api --method POST -H "Accept: application/vnd.github+json" \
    "repos/${REPO_SLUG}/pulls/${PR_NUMBER}/reviews/${REVIEW_ID}/events" \
    -f event=COMMENT >/dev/null; then
    fail "created review thread but failed to submit review ${REVIEW_ID} for PR #${PR_NUMBER} — thread remains PENDING and is invisible to the human"
fi

revoke_token
echo "$THREAD_JSON"
