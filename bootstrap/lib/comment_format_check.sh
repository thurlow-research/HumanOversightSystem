# shellcheck shell=bash
# bootstrap/lib/comment_format_check.sh — shared write-path comment validator (#1270)
#
# Sourced library, NOT an executable entry point. Defines functions only, has
# NO top-level side effects, and is safe to source multiple times. Called by
# BOTH bootstrap/post_comment.sh and bootstrap/post_review_thread.sh so the
# two write paths cannot drift apart the way #1099/#1268's rule did: it was
# stated in overseer.md but never checked at either write path, and a 35-PR
# sample found the required executive-summary format present only 37% of the
# time (#1270).
#
# Two independent checks:
#
#   hos_cfc_check_at_path_literal <body_file>
#     The #1155 regression guard, generalised out of both scripts (previously
#     duplicated identically in each). Unconditional — runs for every --app
#     value. Sets HOS_CFC_REASON and returns 1 on violation.
#
#   hos_cfc_check_overseer_format <body_file>
#     The overseer.md "Executive summary" / §8.2 format contract (#1099,
#     extended by #1268). Checks: a leading `**Executive summary:**` heading,
#     exactly one bolded expected-action enum value, and a "not verified"
#     clause. Only meaningful for --app overseer — worker and human post
#     plain narrative comments with no such contract, so callers must gate
#     this check on app_role themselves (hos_cfc_enforce_overseer_format
#     does this).
#
# Neither function prints or exits on its own — the caller (via err/warn)
# decides whether a violation is fatal, and the body file is never modified
# or deleted either way (#1270 design requirement 4: rejection must leave
# the file intact so the agent can edit and retry).
#
# Mode gate (design requirement 3 — advisory ships first):
#   HOS_COMMENT_FORMAT_MODE=advisory (default) — violations are logged via
#     the caller's warn function and the comment is posted anyway.
#   HOS_COMMENT_FORMAT_MODE=enforce — violations block the post.
#   This mirrors the HOS_REQUIRE_TOOLS idiom in
#   scripts/oversight/lib/detect_stack.sh: an env-var escape hatch that is
#   loud in stderr, not silent, so a format-checker bug can never
#   permanently block the oversight path (design requirement 5). When this
#   default eventually flips to enforce (a separate, later change per #1270),
#   HOS_COMMENT_FORMAT_MODE=advisory becomes that flip's own escape hatch.

HOS_CFC_REASON=""

hos_cfc_check_at_path_literal() {
    local body_file="$1"
    if [[ "$(head -c 2 -- "$body_file" 2>/dev/null)" == "@/" ]]; then
        HOS_CFC_REASON="--body-file content starts with '@/' — looks like an @path literal was written instead of comment content (#1155)"
        return 1
    fi
    return 0
}

# Fixed enum from overseer.md "Executive summary" section (#1268) — keep in
# sync with that document; it is the single source of truth for the values.
_HOS_CFC_ENUM_VALUES=("APPROVE" "REQUEST CHANGES" "DECIDE" "DO NOT MERGE" "NO ACTION" "OTHER")

hos_cfc_check_overseer_format() {
    local body_file="$1"
    local full_body
    full_body="$(cat -- "$body_file" 2>/dev/null)"

    # "Leading" — allow only whitespace before the heading (overseer.md: "opens
    # with a single paragraph under the heading **Executive summary:**").
    local prefix="${full_body%%'**Executive summary:**'*}"
    if [[ "$prefix" == "$full_body" ]]; then
        HOS_CFC_REASON="missing the leading **Executive summary:** heading"
        return 1
    fi
    if [[ -n "${prefix//[$'\t\r\n ']/}" ]]; then
        HOS_CFC_REASON="**Executive summary:** must lead the comment — found other content before it"
        return 1
    fi

    local matches=0 value
    for value in "${_HOS_CFC_ENUM_VALUES[@]}"; do
        if [[ "$full_body" == *"**${value}**"* ]]; then
            matches=$((matches + 1))
        fi
    done
    if [[ "$matches" -eq 0 ]]; then
        HOS_CFC_REASON="missing a bolded expected-action enum value (APPROVE | REQUEST CHANGES | DECIDE | DO NOT MERGE | NO ACTION | OTHER)"
        return 1
    elif [[ "$matches" -gt 1 ]]; then
        HOS_CFC_REASON="found ${matches} bolded expected-action enum values — exactly one is required"
        return 1
    fi

    # overseer.md's own worked examples read "Not verified this run: ..."
    # (unbolded prose), not a bolded field — match the phrase, case-insensitive,
    # rather than the issue's illustrative-only "**Not verified:**" sketch.
    shopt -s nocasematch
    local has_not_verified=0
    [[ "$full_body" == *"not verified"* ]] && has_not_verified=1
    shopt -u nocasematch
    if [[ "$has_not_verified" -eq 0 ]]; then
        HOS_CFC_REASON="missing a \"not verified\" clause naming what this run could not check"
        return 1
    fi

    return 0
}

# hos_cfc_enforce_overseer_format <body_file> <app_role> <warn_fn>
# Orchestrates the mode-gated check for the overseer-format contract. Returns
# 0 when the caller may proceed to post (pass, N/A for this app_role, or
# advisory mode after logging), 1 when the caller must refuse (enforce mode,
# violation found — caller should then `err "$HOS_CFC_REASON"`).
hos_cfc_enforce_overseer_format() {
    local body_file="$1" app_role="$2" warn_fn="${3:-}"
    [[ "$app_role" == "overseer" ]] || return 0

    hos_cfc_check_overseer_format "$body_file" && return 0

    local mode="${HOS_COMMENT_FORMAT_MODE:-advisory}"
    if [[ "$mode" == "enforce" ]]; then
        return 1
    fi

    if [[ -n "$warn_fn" ]]; then
        "$warn_fn" "comment format violation (#1270, advisory — posting anyway): ${HOS_CFC_REASON}. Set HOS_COMMENT_FORMAT_MODE=enforce to block instead."
    fi
    return 0
}
