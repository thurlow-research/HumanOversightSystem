#!/usr/bin/env bash
# bootstrap/delete_branch.sh — canonical way to delete a closed (or merged) PR's
# remote head branch under a HOS bot identity (#2288 item 2).
#
# Wraps get_app_token.sh: mint a short-lived App installation token -> run
# `python3 -m scripts.automation.readopt delete-head --pr <N>` -> revoke the
# token. One invocation, no loops or substitution at the call site — see
# CLAUDE.md "Shell usage under the sandbox".
#
# Usage:
#   bash bootstrap/delete_branch.sh --pr <N> --app <worker|overseer|human>
#
# Scope: REMOTE only, and BY PR NUMBER only. There is no delete-by-name mode:
# a by-name delete has no server-side record of the SHA that should be there,
# so it cannot do a meaningful compare-and-swap. Heads with no PR belong to
# `readopt reap-orphans --remote-scope all`. Local branches are never touched.
#
# Safety rules (open PR, fork, protected name, moved tip, another open PR on
# the same head, CAS delete) live in readopt.delete_head; see
# docs/v0.7.0/TECHNICAL-DESIGN-2288-S2-delete-on-close.md.
#
# bootstrap/edit_issue.sh --state closed calls this script automatically for
# PRs (opt out with --keep-branch there).
#
# Exit codes (the readopt delete-head code, passed through unchanged):
#   0  head is gone (DELETED or ALREADY-GONE; idempotent)
#   2  error or uncertainty; nothing deleted, or outcome unknown (retry is safe).
#      A failed token mint also exits 2.
#   3  refused by a safety rule (KEPT) — a valid outcome, not a failure
#   1  usage error
# The result line is the last stdout line.
#
# Requires: bootstrap/get_app_token.sh, python3, curl (token revocation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

PR=""
APP_ROLE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --pr)  [[ $# -ge 2 ]] || err "--pr requires a value"; PR="$2"; shift 2 ;;
        --app) [[ $# -ge 2 ]] || err "--app requires a value"; APP_ROLE="$2"; shift 2 ;;
        *) err "Usage: $0 --pr <N> --app <worker|overseer|human>" ;;
    esac
done

[[ -n "$PR" ]] || err "--pr required"
[[ "$PR" =~ ^[1-9][0-9]*$ ]] || err "--pr must be a positive integer, got: $PR"
[[ -n "$APP_ROLE" ]] || err "--app required (worker, overseer, or human)"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) err "--app must be 'worker', 'overseer', or 'human'" ;;
esac

# ── Mint token, source it, then remove the file immediately (#549) ───────────
TOKEN_FILE="$(mktemp)"
trap 'rm -f "$TOKEN_FILE"' EXIT

if ! bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE"; then
    echo -e "  ${RED}✘${RESET}  Failed to mint ${APP_ROLE} token" >&2
    exit 2
fi
# shellcheck source=/dev/null
source "$TOKEN_FILE"
rm -f "$TOKEN_FILE"

revoke_token() {
    curl -sf --connect-timeout 10 --max-time 30 -X DELETE -H "Authorization: token ${GH_TOKEN}" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/installation/token >/dev/null 2>&1 \
        || warn "failed to revoke installation token (it will expire naturally within 1 hour)"
}

# JSON string escaping valid for any input: backslash, double quote, \n \r \t, and
# every other C0 control byte (and DEL) as \u00XX.
_json_escape() {
    local s="$1" out="" c i code
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    for ((i = 0; i < ${#s}; i++)); do
        c="${s:i:1}"
        case "$c" in
            $'\n') out+='\n' ;;
            $'\r') out+='\r' ;;
            $'\t') out+='\t' ;;
            *)
                # Numeric test, not a [a-b] range: ranges are locale-dependent.
                printf -v code '%d' "'$c"
                if ((code < 32 || code == 127)); then
                    printf -v c '\\u%04x' "$code"
                fi
                out+="$c"
                ;;
        esac
    done
    printf '%s' "$out"
}

# _field <result-line> <key>: value of "key=" in the readopt result line (or empty).
_field() {
    local line="$1" key="$2" rest
    [[ " $line" == *" $key="* ]] || return 0
    rest="${line#*" $key="}"
    printf '%s' "${rest%% *}"
}

# _reason_of <result-line>: the reason= text (ERROR reasons contain spaces), minus
# any trailing " expected=..." / " tip=..." fields of a KEPT-moved line.
_reason_of() {
    local line="$1" r
    [[ "$line" == *" reason="* ]] || return 0
    r="${line#*" reason="}"
    r="${r%% expected=*}"
    printf '%s' "${r%% tip=*}"
}

# _audit_branch_delete <result-line>
# Best-effort durable audit event for the delete-head outcome (#2288 S2), same
# pattern as _hos_audit_stale_base_merge in submit_pr.sh. Never blocks; returns 0.
_audit_branch_delete() {
    local line="$1"
    local audit_lib="$SCRIPT_DIR/../scripts/oversight/lib/audit_log.sh"
    [[ -f "$audit_lib" ]] || return 0
    # shellcheck disable=SC1090
    source "$audit_lib" 2>/dev/null || return 0
    command -v audit_write_event >/dev/null 2>&1 || return 0

    local outcome="${line%% *}"
    case "$outcome" in
        DELETED|ALREADY-GONE|KEPT|ERROR) ;;
        *) return 0 ;;
    esac
    local branch reason tip ts json
    branch="$(_json_escape "$(_field "$line" branch)")"
    reason="$(_reason_of "$line")"
    reason="$(_json_escape "$reason")"
    tip="$(_json_escape "$(_field "$line" tip)")"
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    json="$(printf '{"event":"branch-delete","pr":%s,"branch":"%s","outcome":"%s","reason":"%s","tip":"%s","actor":"%s","timestamp":"%s"}' \
        "$PR" "$branch" "$outcome" "$reason" "$tip" "$APP_ROLE" "$ts")"
    audit_write_event "$json" "$SCRIPT_DIR/.." >/dev/null 2>&1 || true
    return 0
}

# Capture the rc explicitly: under set -e a bare failure would exit before the revoke.
# stdout goes to a file so the last line can be audited, then is replayed unchanged.
OUT_FILE="$(mktemp)"
trap 'rm -f "$TOKEN_FILE" "$OUT_FILE"' EXIT
rc=0
(cd "$REPO_DIR" && python3 -m scripts.automation.readopt --repo "$REPO_DIR" delete-head --pr "$PR") >"$OUT_FILE" || rc=$?
cat "$OUT_FILE"
_audit_branch_delete "$(tail -n 1 "$OUT_FILE")" || true

revoke_token
exit "$rc"
