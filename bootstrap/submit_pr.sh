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
#   bash bootstrap/submit_pr.sh --update-pr <N> --base <branch> [--head <branch>] \
#     --app worker
#
# --update-pr <N> pushes to an EXISTING PR instead of opening a new one (#967
# AD-4). Requires --app worker; --title/--body-file are rejected (the PR
# already has both). Mode declaration is explicit and caller-declared — this
# script never infers "this PR is mine" from a failed `gh pr create`. It does
# NOT consult the branch-ownership record (that check answers "may I open a
# PR here", not "may I push here"); authority instead comes from a
# server-side check, after the token mint and before the push, that PR #<N>
# is open, has head/base matching --head/--base, and was authored by this
# bot identity. Any mismatch revokes the token and refuses — no --force is
# ever used. In open mode (no --update-pr), an open PR already existing for
# --head is refused with a pointer to --update-pr, so a caller can never
# silently open a second PR for the same branch.
#
# --head names the LOCAL branch to push; it defaults to the current branch
# if omitted. It must already exist as a local branch (refs/heads/<name>) —
# this pushes that branch's actual content, not whatever happens to be
# checked out, so it is safe to pass a branch other than the current one
# (#1166). If that branch is behind --base and isn't the checked-out branch,
# rebuild it onto a fresh base first (scripts/dev/commit_onto_base.sh) rather
# than relying on this script to merge it in place.
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
UPDATE_PR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --title)      TITLE="$2"; shift 2 ;;
        --body-file)  BODY_FILE="$2"; shift 2 ;;
        --base)       BASE="$2"; shift 2 ;;
        --head)       HEAD="$2"; shift 2 ;;
        --app)        APP_ROLE="$2"; shift 2 ;;
        --confirmed)  CONFIRMED="true"; shift ;;
        --update-pr)  UPDATE_PR="$2"; shift 2 ;;
        --body)       err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate." ;;
        *)            err "Usage: $0 --title <text> --body-file <path> --base <branch> [--head <branch>] --app <worker|overseer|human> [--confirmed] | $0 --update-pr <N> --base <branch> [--head <branch>] --app worker" ;;
    esac
done

[[ -n "$BASE" ]]      || err "--base required"
[[ -n "$APP_ROLE" ]]  || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac

if [[ -n "$UPDATE_PR" ]]; then
    [[ "$UPDATE_PR" =~ ^[0-9]+$ ]] || err "--update-pr requires a numeric PR number, got '${UPDATE_PR}'"
    [[ "$APP_ROLE" == "worker" ]]  || err "--update-pr requires --app worker"
    [[ -z "$TITLE" ]]     || err "--title is not accepted with --update-pr — the PR already exists; only its branch content changes"
    [[ -z "$BODY_FILE" ]] || err "--body-file is not accepted with --update-pr — the PR already exists; only its branch content changes"
else
    [[ -n "$TITLE" ]]     || err "--title required"
    [[ -n "$BODY_FILE" ]] || err "--body-file required"
    [[ -f "$BODY_FILE" ]] || err "--body-file not found: $BODY_FILE"
fi

if [[ "$APP_ROLE" == "human" && "$CONFIRMED" != "true" ]]; then
    err "--app human requires --confirmed: a human-proxy PR is only appropriate with explicit per-instance human authorization (docs/AGENT-IDENTITY.md, stuck-worker exception). Confirm a human has approved THIS push, then pass --confirmed."
fi

CURRENT_BRANCH="$(git -C "$SCRIPT_DIR/.." rev-parse --abbrev-ref HEAD)"
[[ -n "$HEAD" ]] || HEAD="$CURRENT_BRANCH"
[[ "$HEAD" != "HEAD" ]] || err "Could not determine current branch (detached HEAD) — pass --head <branch>"

# ── Resolve the branch to push (#1166) ──────────────────────────────────────
# --head names the LOCAL branch to push, not "whatever is checked out." Using
# the working-tree HEAD as the push source silently publishes stale content
# under the named branch whenever the two differ — e.g. a branch built without
# a checkout (scripts/dev/commit_onto_base.sh, #1147), which is the required
# pattern for protected-surface edits in the sandboxed Human clone. Resolve
# and push refs/heads/${HEAD} explicitly so the source is always the named
# branch, checked out or not.
git -C "$SCRIPT_DIR/.." rev-parse --verify --quiet "refs/heads/${HEAD}" >/dev/null \
    || err "No local branch named '${HEAD}' (refs/heads/${HEAD} does not exist) — build it first"
HEAD_IS_CHECKED_OUT="false"
[[ "$HEAD" == "$CURRENT_BRANCH" ]] && HEAD_IS_CHECKED_OUT="true"

# ── Branch-ownership enforcement (#967, ADR-037, R4/R5/R6) ─────────────────
# The worker opens a PR only for a branch it created in this cycle; ownership
# is recorded, never inferred. This must run before any network access, token
# mint, or push (R4), and is scoped to --app worker only (R6) — --app human
# and --app overseer see no change in behaviour, output, or exit codes.
# --update-pr is exempt (AD-4, §7): it answers "may I push to an existing PR",
# not "may I open one", and its own server-side authorship check below is a
# stronger recorded fact than the ownership record.
if [[ "$APP_ROLE" == "worker" && -z "$UPDATE_PR" ]]; then
    # shellcheck source=bootstrap/lib/branch_ownership.sh
    source "$SCRIPT_DIR/lib/branch_ownership.sh" \
        || err "branch-ownership library missing (bootstrap/lib/branch_ownership.sh) — refusing to open a PR for '${HEAD}'"
    if ! hos_bo_verify "$SCRIPT_DIR/.." "$HEAD"; then
        hos_bo_audit_refusal "$SCRIPT_DIR/.." "$HEAD" "$HOS_BO_REASON"
        case "$HOS_BO_REASON" in
            no_cycle_id)
                err "HOS_CYCLE_ID is not set in this environment. Branch ownership cannot be verified, so --app worker cannot open a PR for '${HEAD}'. This session was not launched by bin/hos-cron, or the launcher predates #967 (upgrade bin/hos-cron and bootstrap/ together)." ;;
            no_record)
                err "No ownership record for branch '${HEAD}'. The worker opens PRs only for branches it created in this cycle via bootstrap/create_branch.sh. A branch created by another session — whatever its commits or issue label — is never this cycle's to submit (#967)." ;;
            wrong_cycle)
                err "Ownership record for '${HEAD}' was written by a different cycle. Ownership does not decay; authority does not transfer (ADR-037 AD-1). Create this cycle's own branch (bootstrap/create_branch.sh --from ${HEAD}) and submit that." ;;
            *)
                err "Branch-ownership check failed for '${HEAD}' (reason: ${HOS_BO_REASON}). Refusing to open a PR (#967)." ;;
        esac
    fi
fi

# ── Merge from base before pushing (#1162) ─────────────────────────────────────
# A branch built on a stale base doesn't just miss the work that landed on
# main while it was being built — its PR proposes *reverting* that work, and
# the diff looks entirely normal until inspected. Fetch the base and merge it
# in here, before anything else touches the network, so a stale base can never
# reach `gh pr create`. Read-only (fetch + local merge); no token required.
git -C "$SCRIPT_DIR/.." fetch origin "$BASE" \
    || err "Could not fetch origin/${BASE} — resolve network/auth before opening a PR"

BEHIND_COUNT="$(git -C "$SCRIPT_DIR/.." rev-list --count "refs/heads/${HEAD}..origin/${BASE}")"
if [[ "$BEHIND_COUNT" -gt 0 ]]; then
    if [[ "$HEAD_IS_CHECKED_OUT" != "true" ]]; then
        err "${HEAD} is ${BEHIND_COUNT} commit(s) behind origin/${BASE} and is not the checked-out branch, so it cannot be merged here without touching the working tree. Rebuild it onto a fresh base (scripts/dev/commit_onto_base.sh --base origin/${BASE} --branch ${HEAD} ...) and retry."
    fi
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

# ── PR-authorship / duplicate-PR guard (#967 AD-4) ─────────────────────────
# Runs after the token mint (it needs an authenticated `gh api` call) and
# before the push, so a mismatch is caught before anything is published.
PR_HTML_URL=""
if [[ -n "$UPDATE_PR" ]]; then
    # Update mode: authority comes from server-side PR authorship, not the
    # ownership record — a stronger recorded fact than any caller assertion.
    # Try-create-then-fall-back-on-error is forbidden (AD-4): the mode is
    # caller-declared and verified independently, never inferred from a
    # `gh pr create` failure string.
    if ! PR_FIELDS="$(gh api "repos/${REPO_SLUG}/pulls/${UPDATE_PR}" --jq '[.state, .head.ref, .user.login, .base.ref, .html_url] | @tsv' 2>/dev/null)"; then
        revoke_token
        err "Could not fetch PR #${UPDATE_PR} from ${REPO_SLUG} — refusing to push without verifying authorship (#967 AD-4)"
    fi
    IFS=$'\t' read -r PR_STATE PR_HEAD_REF PR_USER_LOGIN PR_BASE_REF PR_HTML_URL <<< "$PR_FIELDS"
    if [[ "$PR_STATE" != "open" || "$PR_HEAD_REF" != "$HEAD" || "$PR_USER_LOGIN" != "${HOS_BOT_LOGIN:-}" || "$PR_BASE_REF" != "$BASE" || -z "$PR_HTML_URL" ]]; then
        revoke_token
        err "PR #${UPDATE_PR} does not match this push (expected head=${HEAD} base=${BASE} user=${HOS_BOT_LOGIN:-<unset>}; got state=${PR_STATE:-?} head=${PR_HEAD_REF:-?} user=${PR_USER_LOGIN:-?} base=${PR_BASE_REF:-?}) — refusing (#967 AD-4)"
    fi
elif [[ "$APP_ROLE" == "worker" ]]; then
    # Open mode, --app worker: refuse if an open PR already exists for --head
    # — the caller should have used --update-pr. A query failure fails
    # closed, same as every other check in this script. Scoped to worker
    # only, matching R6: --app human and --app overseer see no behaviour
    # change from this issue.
    REPO_OWNER="${REPO_SLUG%%/*}"
    if ! EXISTING_PR_FIELDS="$(gh api "repos/${REPO_SLUG}/pulls?state=open&head=${REPO_OWNER}:${HEAD}" --jq '[length, (.[0].number // "")] | @tsv' 2>/dev/null)"; then
        revoke_token
        err "Could not check for an existing open PR on '${HEAD}' — refusing to open a new one (#967 AD-4)"
    fi
    IFS=$'\t' read -r EXISTING_PR_COUNT EXISTING_PR_NUMBER <<< "$EXISTING_PR_FIELDS"
    [[ "$EXISTING_PR_COUNT" =~ ^[0-9]+$ ]] || { revoke_token; err "Could not parse the open-PR check response for '${HEAD}' — refusing (#967 AD-4)"; }
    if [[ "$EXISTING_PR_COUNT" -gt 0 ]]; then
        revoke_token
        err "An open PR already exists for '${HEAD}' (#${EXISTING_PR_NUMBER}) — use --update-pr ${EXISTING_PR_NUMBER} instead of opening a new one (#967 AD-4)"
    fi
fi

# Token lives in the URL only for this one push, never in .git/config or any
# remote name — passed directly as the push destination. No --force in
# either mode: a non-fast-forward push fails loudly rather than silently
# overwriting a PR head (#967 AD-4).
PUSH_URL="https://x-access-token:${GH_TOKEN}@github.com/${REPO_SLUG}.git"
if ! git -C "$SCRIPT_DIR/.." push "$PUSH_URL" "refs/heads/${HEAD}:refs/heads/${HEAD}"; then
    revoke_token
    err "git push failed"
fi
PUSH_URL=""

if [[ -n "$UPDATE_PR" ]]; then
    revoke_token
    echo "$PR_HTML_URL"
else
    if ! PR_URL="$(gh pr create --repo "$REPO_SLUG" --title "$TITLE" --body-file "$BODY_FILE" --base "$BASE" --head "$HEAD")"; then
        revoke_token
        err "gh pr create failed"
    fi
    revoke_token
    echo "$PR_URL"
fi
