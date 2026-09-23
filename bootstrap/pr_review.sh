#!/usr/bin/env bash
# bootstrap/pr_review.sh — L3 wrapper for the PR-review verdict primitive (#1657)
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> invoke
# scripts/automation/pr_review_cli.py (L2) -> revoke the token. One script
# invocation, no loops or substitution at the call site — see CLAUDE.md
# "Shell usage under the sandbox" for why that matters on Worker/Overseer (an
# unallowlistable command is denied outright, with nobody present to answer
# a prompt — not hung).
#
# Usage (the subcommand is a positional keyword from a closed enum — it
# carries no content, so the argv shape is fixed end to end):
#   bash bootstrap/pr_review.sh submit-verdict    --app <worker|overseer|human> --pr <N> \
#                                                 --event <approve|comment> --tier <SAFE|LOW|MEDIUM|HIGH|CRITICAL> \
#                                                 --body-file <path> [--repo <owner/repo>]
#   bash bootstrap/pr_review.sh request-reviewer  --app <worker|overseer|human> --pr <N> \
#                                                 --tier <SAFE|LOW|MEDIUM|HIGH|CRITICAL> \
#                                                 [--reviewer <login>] [--repo <owner/repo>]
#
# --app accepts both `--app overseer` and `--app=overseer` forms.
#
# --body-file only, never inline --body <text> — same rationale as
# post_comment.sh / post_review_thread.sh: review bodies are markdown,
# routinely contain newlines/quotes, and inline text is exactly the
# unallowlistable $(...)/heredoc shell pattern this script exists to
# eliminate. It is also the only safe way to post file-derived content: a
# raw `gh api --field body=@path` silently posts the literal string "@path"
# instead of the file's contents (#752/#1155).
#
# Every disposition the overseer reaches posts exactly one verdict review
# via `submit-verdict` — never a conversation comment
# (bootstrap/post_comment.sh) and never REQUEST_CHANGES (ADR-1657 AD-2:
# rejected at argument-parsing time by pr_review_cli.py; a bot
# CHANGES_REQUESTED above OVERSEER_CEILING has no autonomous clearing actor.
# Use bootstrap/post_review_thread.sh for a blocking, resolvable finding
# instead).
#
# Exit codes (owned entirely by pr_review_cli.py — see its module docstring
# and docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md §4.0; this
# script never computes one of its own):
#   0 — the requested mutation was performed, or was a verified no-op (skipped: true)
#   1 — operational failure (auth, API error, malformed data, missing config,
#       an unevaluable input)
#   2 — usage error (unknown subcommand/flag, missing required flag, invalid
#       enum value, unreadable --body-file)
#   3 — refusal: the request was well-formed but this wrapper is not
#       permitted to perform it (above-ceiling approve, self-authored
#       approve, no qualifying reviewer trigger). A first-class, expected
#       outcome — never treat a refusal as a bug in the caller.
#
# stdout is exactly one JSON object, always — it is pr_review_cli.py's,
# passed through byte-for-byte. Never suppress this script's stderr (#1523).
#
# Named ARCH-3a deviation (ADR-1357 AMENDMENT-1 §4, AD-7 of ADR-1657): this
# script may refuse from bash, before ever invoking L2, when
# HOS_COMMENT_FORMAT_MODE=enforce and a submit-verdict body fails the #1270
# executive-summary format contract. Reimplementing that contract in Python
# would fork a validator whose entire purpose is that the write paths cannot
# drift apart — one bash implementation with a third caller is the lesser
# evil. This invocation is byte-identical in shape to post_comment.sh:79-86
# and post_review_thread.sh:103-112.
#
# The record schema is owned by pr_review_cli.py alone. This script must
# never grow a JSON literal, a printf/echo to stdout, or any re-derivation
# of a field — adding an envelope field is a change to that module only,
# never to this one.
#
# Requires: bootstrap/get_app_token.sh, bootstrap/revoke_app_token.sh,
# bootstrap/lib/comment_format_check.sh, python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

# shellcheck source=lib/comment_format_check.sh
source "$SCRIPT_DIR/lib/comment_format_check.sh"

# ── Reject inline --body up front, whatever subcommand this is (#1155 class,
# same message post_comment.sh / post_review_thread.sh use) ─────────────────
for _arg in "$@"; do
    if [[ "$_arg" == "--body" ]]; then
        err "--body is not supported — write the body to a file and pass --body-file <path>. Inline text with newlines/quotes is exactly the unallowlistable shell pattern this script exists to eliminate."
    fi
done
unset _arg

# ── Extract, do not validate (ARCH-3a) ──────────────────────────────────────
# Read the three values needed to decide whether to mint a token and
# whether to run the format check: the subcommand token, --app, and
# --body-file. This step emits no JSON, prints no usage text (beyond the
# --body rejection above), and rejects nothing else. An absent or
# unrecognised subcommand/app/body-file simply means the corresponding step
# below is skipped — control still reaches pr_review_cli.py, where argparse
# alone produces the single canonical exit-2 envelope. Python is the sole
# author of the record schema (see header); adding a field there must never
# require editing this script.

SUBCOMMAND=""
if [[ $# -gt 0 && "${1:0:1}" != "-" ]]; then
    SUBCOMMAND="$1"
fi

APP_ROLE=""
BODY_FILE=""
_prev_arg=""
for _arg in "$@"; do
    case "$_arg" in
        --app=*)       APP_ROLE="${_arg#--app=}" ;;
        --body-file=*) BODY_FILE="${_arg#--body-file=}" ;;
    esac
    if [[ "$_prev_arg" == "--app" ]]; then APP_ROLE="$_arg"; fi
    if [[ "$_prev_arg" == "--body-file" ]]; then BODY_FILE="$_arg"; fi
    _prev_arg="$_arg"
done
unset _prev_arg _arg

MINT_TOKEN=false
case "$SUBCOMMAND" in
    submit-verdict|request-reviewer)
        case "$APP_ROLE" in
            worker|overseer|human) MINT_TOKEN=true ;;
        esac
        ;;
esac

# ── Comment-format check (submit-verdict only) — named ARCH-3a deviation ───
# Unconditional #1155 @path-literal guard, then the mode-gated (advisory by
# default) #1270 executive-summary contract — byte-identical usage to
# post_comment.sh:79-86 and post_review_thread.sh:103-112. A missing or
# unreadable --body-file is not decided here: it surfaces as
# pr_review_cli.py's own G5 (exit 2) or argparse's exit-2 usage error.
if [[ "$SUBCOMMAND" == "submit-verdict" ]]; then
    hos_cfc_check_at_path_literal "$BODY_FILE" || err "$HOS_CFC_REASON"
    hos_cfc_enforce_overseer_format "$BODY_FILE" "$APP_ROLE" warn \
        || err "comment format violation (#1270): $HOS_CFC_REASON"
fi

# ── Mint (only for a recognised network invocation) and register revocation ─
# Token revocation is a forced side effect of this script exiting, regardless
# of whether a token was ever actually minted (TOKEN_FILE / GH_TOKEN unset is
# a no-op below) and regardless of the child's exit code.
TOKEN_FILE=""

revoke_token() {
    if [[ -n "$TOKEN_FILE" ]]; then
        rm -f "$TOKEN_FILE"
    fi
    # bootstrap/revoke_app_token.sh (#1191) — never inline the DELETE curl
    # here: it has no timeout (a network stall inside this EXIT trap would
    # block process exit indefinitely, after pr_review_cli.py already
    # succeeded and printed its envelope, burning a whole unattended cron
    # cycle — MUST_FIX B, #1657 PR-1 review round 2) and it would pass
    # GH_TOKEN as curl argv, exposing it via /proc/<pid>/cmdline. It reads
    # GH_TOKEN from the inherited environment, is idempotent on an absent
    # token, and always exits 0 (fail-open with a warning — the token
    # expires naturally within the hour either way).
    bash "$SCRIPT_DIR/revoke_app_token.sh"
}
trap revoke_token EXIT

if $MINT_TOKEN; then
    TOKEN_FILE="$(mktemp)"
    if bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE"; then
        # shellcheck source=/dev/null
        source "$TOKEN_FILE"
        # A successful mint is structurally unreachable from the read this
        # guards (gated behind `if not bot_login:`, so a genuine mint
        # success never reaches it) — this is cosmetic, but an ambient
        # HOS_PR_REVIEW_TOKEN_MINT_FAILED=1 inherited from elsewhere in the
        # environment, combined with an unrelated HOS_BOT_LOGIN-unset
        # condition, would otherwise pick the wrong error wording (#1657
        # PR-1 review round 3, NIT).
        unset HOS_PR_REVIEW_TOKEN_MINT_FAILED
    else
        # A mint failure is an operational condition, not something bash
        # decides the outcome of (ARCH-3a). Proceed without a token:
        # pr_review_cli.py's own GitHub fetch will then fail and it alone
        # emits the exit-1 envelope naming the cause, so "stdout is exactly
        # one JSON object, always" still holds on this path.
        #
        # HOS_PR_REVIEW_TOKEN_MINT_FAILED tells L2 the root cause: without
        # it, a mint failure surfaces downstream only as "HOS_BOT_LOGIN is
        # unset" (both HOS_BOT_LOGIN and GH_TOKEN come from the same failed
        # mint), which reads as a config problem and masks a transient auth
        # failure that would very likely succeed on the next cron cycle
        # (SHOULD_FIX F, #1657 PR-1 review round 2).
        export HOS_PR_REVIEW_TOKEN_MINT_FAILED=1
        echo "pr_review.sh: warning: failed to mint ${APP_ROLE} token — proceeding without one" >&2
    fi
    rm -f "$TOKEN_FILE"
    TOKEN_FILE=""
fi

# ── Invoke, passing argv through verbatim and unreordered ──────────────────
# No jq, no capture, no reformatting of the child's stdout — it passes
# straight through so the JSON-envelope contract holds byte-for-byte.
# Stderr is not redirected either.
set +e
python3 "$REPO_ROOT/scripts/automation/pr_review_cli.py" "$@"
RC=$?
set -e

# ── Exit with the child's code unmodified; revoke_token fires via the trap ─
exit "$RC"
