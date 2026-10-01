#!/usr/bin/env bash
# bootstrap/edit_issue_edges.sh — canonical write path for sub-issue links and blocked_by dependency edges (#1352 slice, #1644 T3.3a, ADR-1644 AD-C14)
#
# Makes ONE native edge between two issues of THIS repository exist or not exist, then
# reads the live graph back and exits on what it OBSERVED, never on what it assumed.
# Callers pass issue NUMBERS; the script resolves each to GitHub's internal id (the
# sub-issue and dependency APIs take the id, not the number). Exactly one edge mutation
# per invocation, so the exit code describes exactly one edge.
#
# Usage:
#   bash bootstrap/edit_issue_edges.sh --number <N> --app <worker|overseer|human> \
#     ( --add-parent <P> | --remove-parent <P> | --add-blocked-by <B> | --remove-blocked-by <B> )
#
#   --number is the SUBJECT: the child for the parent flags, the blocked issue for the
#   blocked-by flags. Every value is a bare issue number (^[1-9][0-9]*$); qualified,
#   cross-repo and comma-list forms are refused. A flag given twice is a usage error
#   (never last-wins). Removal must NAME the exact edge: the script never removes
#   "whatever parent N has". It never re-parents, never reorders, never checks cycles
#   (T3.3's job), and takes no free text (--body/--body-file are refused).
#
# Reads of the same edges: bootstrap/query_issues.sh --parent-of / --sub-issues-of /
# --blockers-of / --dependents-of.
#
# CAUTION: removal can UNBLOCK work (--remove-blocked-by frees the subject,
# --remove-parent can free the parent). Until T3.3's edge check lands, no autonomous
# caller may use the remove flags.
#
# Exit codes (3 and 5 are deliberately unused):
#   0  the requested edge state holds and was observed (added | removed | already-present |
#      already-absent). One stdout line.
#   1  transient: mint, slug, or a pre-write read failed or was malformed. No writes.
#      Retry unchanged.
#   2  refused: usage, self-reference, qualified reference, not found, a pull request,
#      moved issue, read-rejected, or write-rejected (GitHub refused the write and the
#      read-back confirms it did not land). Fix the input; do not retry unchanged.
#   4  write-failed / unverified: a write was attempted and the requested state was not
#      observed or could not be read back. Retry the identical command (idempotent).
#   6  conflict or undeterminable: has-other-parent, parent-mismatch,
#      parent-undeterminable, edges-undeterminable. Do not retry; a human or the
#      tracking-block reconcile decides.
#
# Every gh call is bounded to 30s with `timeout` (or `gtimeout`, as on macOS with
# coreutils); a timed-out call has no status line and so classifies as transient (exit 1
# before the write, exit 4 after it, with the read-back still running). With neither
# binary present gh runs unbounded and one warning is printed. HOS_EDGE_GH_TIMEOUT
# (whole seconds, default 30) overrides the bound; it exists for tests.
#
# Requires: bootstrap/get_app_token.sh, gh, git, jq, curl.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

BLOCKER_PAGE_BOUND=10

# refuse <message>: exit 2 before anything is written (the siblings' err exits 1).
refuse() {
    echo "edit_issue_edges: $*" >&2
    exit 2
}

# printable <value>: printable ASCII only, capped, for echoing a rejected value.
printable() {
    printf '%s' "$1" | LC_ALL=C tr -cd ' -~' | cut -c1-40
}

NUMBER=""
APP_ROLE=""
OP_FLAG=""
OP_COUNT=0
OTHER=""
SEEN_NUMBER=0
SEEN_APP=0
SEEN_OPS=" "

set_op() {
    local flag="$1"
    [[ $# -ge 2 ]] || refuse "usage: ${flag} requires a value"
    [[ "$SEEN_OPS" != *" ${flag} "* ]] || refuse "usage: ${flag} given more than once"
    SEEN_OPS+="${flag} "
    OP_COUNT=$((OP_COUNT + 1))
    OP_FLAG="$flag"
    OTHER="$2"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --number)
            [[ $# -ge 2 ]] || refuse "usage: --number requires a value"
            [[ "$SEEN_NUMBER" -eq 0 ]] || refuse "usage: --number given more than once"
            SEEN_NUMBER=1; NUMBER="$2"; shift 2 ;;
        --app)
            [[ $# -ge 2 ]] || refuse "usage: --app requires a value"
            [[ "$SEEN_APP" -eq 0 ]] || refuse "usage: --app given more than once"
            SEEN_APP=1; APP_ROLE="$2"; shift 2 ;;
        --add-parent|--remove-parent|--add-blocked-by|--remove-blocked-by)
            set_op "$@"; shift 2 ;;
        --body|--body-file)
            refuse "usage: --body/--body-file are not applicable — this script takes no free text" ;;
        *)
            refuse "usage: $0 --number <N> --app <worker|overseer|human> (--add-parent <P> | --remove-parent <P> | --add-blocked-by <B> | --remove-blocked-by <B>)" ;;
    esac
done

# ── Validation: everything here runs before any token is minted ──────────────
[[ -n "$NUMBER" ]]   || refuse "usage: --number required"
[[ -n "$APP_ROLE" ]] || refuse "usage: --app required (worker, overseer, or human)"
[[ "$OP_COUNT" -eq 1 ]] || refuse "usage: exactly one of --add-parent, --remove-parent, --add-blocked-by, --remove-blocked-by is required"
[[ "$NUMBER" =~ ^[1-9][0-9]*$ ]] || refuse "usage: --number must be a positive integer, got: $(printable "$NUMBER")"
if [[ ! "$OTHER" =~ ^[1-9][0-9]*$ ]]; then
    if [[ "$OTHER" == */* || "$OTHER" == *'#'* ]]; then
        refuse "qualified-reference-unsupported: ${OP_FLAG} accepts only this repository's issue numbers, got: $(printable "$OTHER")"
    fi
    refuse "usage: ${OP_FLAG} must be a positive integer, got: $(printable "$OTHER")"
fi
[[ "$NUMBER" != "$OTHER" ]] || refuse "self-reference: --number and ${OP_FLAG} name the same issue (#${NUMBER})"
case "$APP_ROLE" in
    worker|overseer|human) ;;
    *) refuse "usage: --app must be 'worker', 'overseer', or 'human'" ;;
esac

case "$OP_FLAG" in
    --add-parent)         KIND="sub-issue";  OP="add" ;;
    --remove-parent)      KIND="sub-issue";  OP="remove" ;;
    --add-blocked-by)     KIND="blocked-by"; OP="add" ;;
    --remove-blocked-by)  KIND="blocked-by"; OP="remove" ;;
esac

# ── Resolve owner/repo from the origin remote (no auth required) ─────────────
REPO_URL="$(git -C "$SCRIPT_DIR/.." remote get-url origin 2>/dev/null)" \
    || err "issue=#${NUMBER} Could not read git remote 'origin' — run from inside the HOS repo"
REPO_SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^git@github\.com:##; s#^https://github\.com/##; s#\.git$##')"
[[ "$REPO_SLUG" == */* ]] || err "issue=#${NUMBER} Could not parse owner/repo from origin remote: $REPO_URL"
SLUG_LC="$(printf '%s' "$REPO_SLUG" | tr '[:upper:]' '[:lower:]')"

# ── Bound every gh call (resolved once, before the mint) ─────────────────────
GH_BOUND_SECONDS="${HOS_EDGE_GH_TIMEOUT:-30}"
[[ "$GH_BOUND_SECONDS" =~ ^[1-9][0-9]*$ ]] || refuse "usage: HOS_EDGE_GH_TIMEOUT must be a positive integer"
GH_BOUND=()
if command -v timeout >/dev/null 2>&1; then
    GH_BOUND=(timeout "$GH_BOUND_SECONDS")
elif command -v gtimeout >/dev/null 2>&1; then
    GH_BOUND=(gtimeout "$GH_BOUND_SECONDS")
else
    warn "no timeout/gtimeout found — gh calls run unbounded (install coreutils)"
fi

# ── Token: mint once, source, delete the file at once (#549); revoke in an EXIT trap ──
TOKEN_FILE="$(mktemp)"
MINTED=0

revoke_token() {
    curl -sf --connect-timeout 10 --max-time 30 -X DELETE -H "Authorization: token ${GH_TOKEN}" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/installation/token >/dev/null 2>&1 \
        || warn "failed to revoke installation token (it will expire naturally within 1 hour)"
}

cleanup() {
    local rc=$?
    rm -f "$TOKEN_FILE"
    if [[ "$MINTED" -eq 1 ]]; then
        MINTED=0
        revoke_token
    fi
    return "$rc"
}
trap cleanup EXIT

bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE" \
    || { echo "edit_issue_edges: mint-failed kind=${KIND} op=${OP} issue=#${NUMBER} other=#${OTHER}" >&2; exit 1; }
# shellcheck source=/dev/null
source "$TOKEN_FILE"
rm -f "$TOKEN_FILE"
MINTED=1

# ── Audit: best-effort, same shape as escalate_to_human.sh::audit_event ──────
# audit_event <outcome> <http_status|none> ; always returns 0
audit_event() {
    local outcome="$1" http="${2:-none}" ts json http_json="null"
    local audit_lib="$SCRIPT_DIR/../scripts/oversight/lib/audit_log.sh"
    [[ "$http" =~ ^[0-9]+$ ]] && http_json="$http"
    if [[ ! -f "$audit_lib" ]]; then
        warn "audit event not written"
        return 0
    fi
    # shellcheck disable=SC1090
    source "$audit_lib" 2>/dev/null || { warn "audit event not written"; return 0; }
    if ! command -v audit_write_event >/dev/null 2>&1; then
        warn "audit event not written"
        return 0
    fi
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    json="$(jq -nc \
        --arg kind "$KIND" --arg op "$OP" \
        --argjson issue "$NUMBER" --argjson other "$OTHER" \
        --arg outcome "$outcome" --argjson http "$http_json" \
        --arg app "$APP_ROLE" --arg actor "${HOS_BOT_LOGIN:-unknown}" --arg ts "$ts" \
        '{event:"issue-edge-changed", kind:$kind, op:$op, issue:$issue, other:$other,
          outcome:$outcome, http_status:$http, app:$app, actor:$actor, timestamp:$ts}')" \
        || { warn "audit event not written"; return 0; }
    audit_write_event "$json" "$SCRIPT_DIR/.." >/dev/null \
        || warn "audit event not written"
    return 0
}

# die <code> <token> <issue> <other> [extra]: one stderr line, then exit.
die() {
    local code="$1" token="$2" issue="$3" other="$4" extra="${5:-}"
    echo "edit_issue_edges: ${token} kind=${KIND} op=${OP} issue=#${issue} other=#${other}${extra:+ $extra}" >&2
    exit "$code"
}

# ── HTTP: every GitHub call goes through gh_req (§3.5) ───────────────────────
# gh_req <METHOD> <path> [<json>] sets G_STATUS (3 digits or "none"), G_CLASS
# (ok|transient|not-found|rejected), G_BODY. Never trips errexit: gh exits 1 on non-2xx.
G_STATUS="none"; G_CLASS="transient"; G_BODY=""
gh_req() {
    local method="$1" path="$2" json="${3:-}" raw hdr first lc
    if [[ -n "$json" ]]; then
        raw="$(printf '%s' "$json" | ${GH_BOUND[@]+"${GH_BOUND[@]}"} gh api --include --method "$method" "$path" --input - 2>/dev/null)" || true
    else
        raw="$(${GH_BOUND[@]+"${GH_BOUND[@]}"} gh api --include --method "$method" "$path" </dev/null 2>/dev/null)" || true
    fi
    raw="${raw//$'\r'/}"
    if [[ "$raw" == *$'\n\n'* ]]; then
        hdr="${raw%%$'\n\n'*}"
        G_BODY="${raw#*$'\n\n'}"
    else
        hdr="$raw"
        G_BODY=""
    fi
    first="${hdr%%$'\n'*}"
    if [[ ! "$first" =~ ^HTTP/[0-9.]+[[:space:]]+([0-9]{3}) ]]; then
        G_STATUS="none"; G_CLASS="transient"
        return 0
    fi
    G_STATUS="${BASH_REMATCH[1]}"
    lc="$(printf '%s' "$hdr" | tr '[:upper:]' '[:lower:]')"
    case "$G_STATUS" in
        2??) G_CLASS="ok" ;;
        401|429|5??) G_CLASS="transient" ;;
        403)
            if grep -qE '^(retry-after:|x-ratelimit-remaining:[[:space:]]*0[[:space:]]*$)' <<<"$lc"; then
                G_CLASS="transient"
            else
                G_CLASS="rejected"
            fi ;;
        404|410) G_CLASS="not-found" ;;
        *) G_CLASS="rejected" ;;
    esac
    return 0
}

# parent_state <json> sets PK (none|url|bad) and PURL. Absent and null both mean none (TD-E3).
PK="bad"; PURL=""
parent_state() {
    local out
    out="$(jq -r '
        if type != "object" then "bad"
        elif ((has("parent_issue_url") | not) or .parent_issue_url == null) then "none"
        elif (.parent_issue_url | type) == "string" then "url\t" + .parent_issue_url
        else "bad" end' <<<"$1" 2>/dev/null)" || out="bad"
    PK="${out%%$'\t'*}"
    PURL=""
    [[ "$out" == *$'\t'* ]] && PURL="${out#*$'\t'}"
    return 0
}

# parse_parent_url <url> sets PP_SAME (1 if this repo), PP_NUM, PP_REF. Returns 1 if unparseable.
PP_SAME=0; PP_NUM=""; PP_REF=""
parse_parent_url() {
    local owner repo
    if [[ ! "$1" =~ /repos/([^/]+)/([^/]+)/issues/([1-9][0-9]*)$ ]]; then
        return 1
    fi
    owner="${BASH_REMATCH[1]}"; repo="${BASH_REMATCH[2]}"; PP_NUM="${BASH_REMATCH[3]}"
    if [[ "$(printf '%s/%s' "$owner" "$repo" | tr '[:upper:]' '[:lower:]')" == "$SLUG_LC" ]]; then
        PP_SAME=1; PP_REF="#${PP_NUM}"
    else
        PP_SAME=0; PP_REF="${owner}/${repo}#${PP_NUM}"
    fi
    return 0
}

# fetch_issue <num> <issue> <other>: R1/R2. Sets F_ID, and PK/PURL for the record.
F_ID=""
fetch_issue() {
    local num="$1" issue="$2" other="$3"
    gh_req GET "repos/${REPO_SLUG}/issues/${num}"
    case "$G_CLASS" in
        transient) die 1 "read-failed" "$issue" "$other" "http=${G_STATUS}" ;;
        not-found) die 2 "issue-not-found" "$issue" "$other" "http=${G_STATUS}" ;;
        rejected)  die 2 "read-rejected" "$issue" "$other" "http=${G_STATUS}" ;;
    esac
    jq -e 'type == "object" and (.id | type) == "number" and .id > 0 and .id == (.id | floor)' \
        >/dev/null 2>&1 <<<"$G_BODY" || die 1 "read-malformed" "$issue" "$other"
    jq -e --argjson n "$num" --arg slug "$SLUG_LC" \
        '.number == $n and ((.repository_url // "") | ascii_downcase | endswith("/repos/" + $slug))' \
        >/dev/null 2>&1 <<<"$G_BODY" || die 2 "issue-moved" "$issue" "$other"
    if jq -e 'has("pull_request")' >/dev/null 2>&1 <<<"$G_BODY"; then
        die 2 "target-is-pull-request" "$issue" "$other"
    fi
    F_ID="$(jq -r '.id' <<<"$G_BODY")"
    parent_state "$G_BODY"
}

# walk_blockers: pages through N's blocked_by list. Sets WALK (ok|transient|not-found|
# rejected|malformed|bound), WALK_STATUS and WALK_IDS (one id per line).
WALK="ok"; WALK_STATUS="none"; WALK_IDS=""
walk_blockers() {
    local page=1 ids count
    WALK="ok"; WALK_IDS=""; WALK_STATUS="none"
    while (( page <= BLOCKER_PAGE_BOUND )); do
        gh_req GET "repos/${REPO_SLUG}/issues/${NUMBER}/dependencies/blocked_by?per_page=100&page=${page}"
        WALK_STATUS="$G_STATUS"
        if [[ "$G_CLASS" != "ok" ]]; then
            WALK="$G_CLASS"
            return 0
        fi
        if ! ids="$(jq -r 'if type == "array" and all(.[]; type == "object" and (.id | type) == "number")
                           then .[].id else error("bad") end' <<<"$G_BODY" 2>/dev/null)"; then
            WALK="malformed"
            return 0
        fi
        count="$(jq 'length' <<<"$G_BODY")"
        [[ -n "$ids" ]] && WALK_IDS+="${ids}"$'\n'
        if (( count < 100 )); then
            return 0
        fi
        page=$((page + 1))
    done
    WALK="bound"
    return 0
}

in_blockers() {
    grep -qx -- "$1" <<<"$WALK_IDS"
}

# ── Reads (nothing written yet) ──────────────────────────────────────────────
fetch_issue "$NUMBER" "$NUMBER" "$OTHER"
ID_N="$F_ID"; PK_N="$PK"; PURL_N="$PURL"
fetch_issue "$OTHER" "$OTHER" "$NUMBER"
ID_M="$F_ID"

if [[ "$KIND" == "blocked-by" ]]; then
    walk_blockers
    case "$WALK" in
        transient) die 1 "read-failed" "$NUMBER" "$OTHER" "http=${WALK_STATUS}" ;;
        malformed) die 1 "read-malformed" "$NUMBER" "$OTHER" ;;
        rejected)  die 2 "read-rejected" "$NUMBER" "$OTHER" "http=${WALK_STATUS}" ;;
        not-found) die 6 "edges-undeterminable" "$NUMBER" "$OTHER" "http=${WALK_STATUS}" ;;
        bound)     die 6 "edges-undeterminable" "$NUMBER" "$OTHER" "page-bound" ;;
    esac
fi

# ── Decision ─────────────────────────────────────────────────────────────────
emit_ok() {
    local outcome="$1"
    if [[ "$KIND" == "sub-issue" ]]; then
        echo "edge kind=sub-issue op=${OP} parent=#${OTHER} child=#${NUMBER} outcome=${outcome}"
    else
        echo "edge kind=blocked-by op=${OP} issue=#${NUMBER} blocked_by=#${OTHER} outcome=${outcome}"
    fi
    exit 0
}

NEED_WRITE=0
if [[ "$KIND" == "sub-issue" ]]; then
    case "$PK_N" in
        none)
            if [[ "$OP" == "add" ]]; then NEED_WRITE=1; else emit_ok "already-absent"; fi ;;
        url)
            if ! parse_parent_url "$PURL_N"; then
                die 6 "parent-undeterminable" "$NUMBER" "$OTHER"
            fi
            if [[ "$PP_SAME" -eq 1 && "$PP_NUM" == "$OTHER" ]]; then
                if [[ "$OP" == "add" ]]; then emit_ok "already-present"; else NEED_WRITE=1; fi
            elif [[ "$OP" == "add" ]]; then
                die 6 "has-other-parent" "$NUMBER" "$OTHER" "current=${PP_REF}"
            else
                die 6 "parent-mismatch" "$NUMBER" "$OTHER" "current=${PP_REF}"
            fi ;;
        *) die 6 "parent-undeterminable" "$NUMBER" "$OTHER" ;;
    esac
else
    if in_blockers "$ID_M"; then
        if [[ "$OP" == "add" ]]; then emit_ok "already-present"; else NEED_WRITE=1; fi
    else
        if [[ "$OP" == "add" ]]; then NEED_WRITE=1; else emit_ok "already-absent"; fi
    fi
fi

# ── W: exactly one mutation, no retry ────────────────────────────────────────
if [[ "$KIND" == "sub-issue" ]]; then
    W_JSON="$(jq -nc --argjson id "$ID_N" '{sub_issue_id: $id}')"
    if [[ "$OP" == "add" ]]; then
        gh_req POST "repos/${REPO_SLUG}/issues/${OTHER}/sub_issues" "$W_JSON"
    else
        gh_req DELETE "repos/${REPO_SLUG}/issues/${OTHER}/sub_issue" "$W_JSON"
    fi
elif [[ "$OP" == "add" ]]; then
    W_JSON="$(jq -nc --argjson id "$ID_M" '{issue_id: $id}')"
    gh_req POST "repos/${REPO_SLUG}/issues/${NUMBER}/dependencies/blocked_by" "$W_JSON"
else
    gh_req DELETE "repos/${REPO_SLUG}/issues/${NUMBER}/dependencies/blocked_by/${ID_M}"
fi
W_CLASS="$G_CLASS"; W_STATUS="$G_STATUS"; W_BODY="$G_BODY"

# ── V: read-back, always, whatever W returned ────────────────────────────────
V_OK=0          # the V read succeeded and is interpretable
HOLDS=0         # the requested state holds
OTHER_PARENT="" # add-parent only: the different parent V observed
if [[ "$KIND" == "sub-issue" ]]; then
    gh_req GET "repos/${REPO_SLUG}/issues/${NUMBER}"
    if [[ "$G_CLASS" == "ok" ]]; then
        parent_state "$G_BODY"
        case "$PK" in
            none)
                V_OK=1
                [[ "$OP" == "remove" ]] && HOLDS=1 ;;
            url)
                if parse_parent_url "$PURL"; then
                    V_OK=1
                    if [[ "$PP_SAME" -eq 1 && "$PP_NUM" == "$OTHER" ]]; then
                        [[ "$OP" == "add" ]] && HOLDS=1
                    else
                        [[ "$OP" == "remove" ]] && HOLDS=1
                        [[ "$OP" == "add" ]] && OTHER_PARENT="$PP_REF"
                    fi
                fi ;;
        esac
    fi
else
    walk_blockers
    if [[ "$WALK" == "ok" ]]; then
        V_OK=1
        if in_blockers "$ID_M"; then
            [[ "$OP" == "add" ]] && HOLDS=1
        else
            [[ "$OP" == "remove" ]] && HOLDS=1
        fi
    fi
fi

if [[ "$V_OK" -eq 0 ]]; then
    audit_event "unverified" "$W_STATUS"
    die 4 "unverified" "$NUMBER" "$OTHER" "verify-read-failed http=${W_STATUS}"
fi

if [[ "$HOLDS" -eq 1 ]]; then
    if [[ "$OP" == "add" ]]; then OUTCOME="added"; else OUTCOME="removed"; fi
    audit_event "$OUTCOME" "$W_STATUS"
    emit_ok "$OUTCOME"
fi

if [[ -n "$OTHER_PARENT" ]]; then
    audit_event "has-other-parent" "$W_STATUS"
    die 6 "has-other-parent" "$NUMBER" "$OTHER" "current=${OTHER_PARENT}"
fi

case "$W_CLASS" in
    rejected|not-found)
        MSG="$(jq -r '.message // "-" | tostring' <<<"$W_BODY" 2>/dev/null | head -n 1 | LC_ALL=C tr -cd ' -~' | cut -c1-200)" || MSG=""
        [[ -n "$MSG" ]] || MSG="-"
        audit_event "write-rejected" "$W_STATUS"
        die 2 "write-rejected" "$NUMBER" "$OTHER" "http=${W_STATUS} message=${MSG}" ;;
    transient)
        audit_event "write-failed" "$W_STATUS"
        die 4 "write-failed" "$NUMBER" "$OTHER" "http=${W_STATUS}" ;;
    *)
        audit_event "unverified" "$W_STATUS"
        die 4 "unverified" "$NUMBER" "$OTHER" "http=${W_STATUS}" ;;
esac
