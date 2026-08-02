# shellcheck shell=bash
# bootstrap/lib/branch_ownership.sh — the branch-ownership record (#967, ADR-037)
#
# Sourced library, NOT an executable entry point. Defines functions only, has
# NO top-level side effects (no `set -e`, no execution at source time), and is
# safe to source multiple times. This is the ONLY place the store location,
# the filename encoding, and the record grammar are defined — the writer
# (bootstrap/create_branch.sh) and the checker (bootstrap/submit_pr.sh, P2) both
# go through it, so they cannot drift apart.
#
# Why this exists
# ----------------
# #967: the worker inferred "this branch is my finished work" from the fact
# that a branch/commit existed. This record replaces that inference with a
# recorded, per-cycle ownership FACT. It is a NECESSARY precondition for
# opening a PR, never a SUFFICIENT one, and never evidence that work is
# finished — it is read in exactly one place in the whole codebase (the
# refusal predicate in submit_pr.sh's --app worker path, P2), and nowhere
# else. In particular it is never read for resume/completion/control-flow
# (ADR-037 AD-2 anti-loophole) — this library does not do that, and nothing
# that calls it should either.
#
# Storage (§4.1)
# ---------------
# <git-common-dir>/hos/branch-ownership/<encoded-branch>.rec
#
# Nothing under a repository's own git directory is a tracked file — it can
# never appear in a PR diff (R8/T7 by construction), and one store exists per
# clone (a record written for branch B in one clone is unreachable from
# another clone with the same branch name — AD-7's key shape, by
# construction, no slug hashing or path agreement required). HOS_STATE_DIR is
# deliberately NOT consulted here and there is no store-location override —
# R5 forbids environment escape hatches.
#
# Record format (§4.3)
# ---------------------
# Strict `key=value` text, one pair per line, LF-terminated, no comments, no
# blank lines, no quoting:
#
#   schema=1
#   branch=<exact branch name, verbatim>
#   cycle_id=<HOS_CYCLE_ID>
#   role=<HOS_CYCLE_ROLE>
#   created_at=<UTC, date -u +%Y-%m-%dT%H:%M:%SZ>
#
# Validity (hos_bo_verify) requires ALL of: store resolvable; HOS_CYCLE_ID set
# in the checking process; the record file exists, is a regular file <= 4096
# bytes, and is readable; every line matches key=value grammar with each
# required key appearing exactly once; schema == 1; branch == B byte-for-byte;
# cycle_id == the checking process's HOS_CYCLE_ID; role == "worker". There is
# no override flag, no environment escape, and no "open anyway" path.
#
# Functions
# ---------
#   hos_bo_store_dir   <repo_dir>
#   hos_bo_encode       <branch>
#   hos_bo_record_path <repo_dir> <branch>
#   hos_bo_write_record <repo_dir> <branch>
#   hos_bo_verify       <repo_dir> <branch>
#   hos_bo_audit_refusal <repo_dir> <branch> <reason>
#
# HOS_BO_REASON is the single out-parameter set by hos_bo_verify and
# hos_bo_write_record on failure — exactly one of: no_store, no_cycle_id,
# no_record, unreadable, malformed, wrong_branch, wrong_cycle, wrong_role,
# foreign_record.
#
# Nothing in this file is `eval`'d, and nothing is sourced from a record file.

# _hos_bo_stat_size <path>
# Portable file size in bytes. Uses stat, not `wc -c`, so it works even when
# the file itself is unreadable (chmod 000) — size and readability are
# distinct validity conditions (§4.3 conditions 3 and 4) and must not be
# conflated by a helper that needs read access to answer either question.
_hos_bo_stat_size() {
    stat -c %s "$1" 2>/dev/null || stat -f %z "$1" 2>/dev/null || echo ""
}

# hos_bo_store_dir <repo_dir>
# Echoes "<git-common-dir>/hos/branch-ownership". Returns 1 if git cannot
# resolve a git-common-dir for repo_dir (not a git repo).
hos_bo_store_dir() {
    local repo_dir="$1" common_dir
    common_dir="$(git -C "$repo_dir" rev-parse --git-common-dir 2>/dev/null)" || return 1
    [[ -n "$common_dir" ]] || return 1
    case "$common_dir" in
        /*) : ;;
        *) common_dir="${repo_dir%/}/$common_dir" ;;
    esac
    printf '%s/hos/branch-ownership\n' "$common_dir"
}

# hos_bo_encode <branch>
# Echoes the encoded filename stem (§4.2: '%' -> '%25', then '/' -> '%2F',
# then validated against ^[A-Za-z0-9._%+-]{1,200}$). Returns 1 if the branch
# name cannot be safely encoded — nothing downstream ever sees a record path
# built from a rejected encoding.
hos_bo_encode() {
    local branch="$1" encoded
    encoded="${branch//%/%25}"
    encoded="${encoded//\//%2F}"
    [[ "$encoded" =~ ^[A-Za-z0-9._%+-]{1,200}$ ]] || return 1
    printf '%s\n' "$encoded"
}

# hos_bo_record_path <repo_dir> <branch>
# Echoes "<store_dir>/<encoded>.rec". Returns 1 if either component fails.
hos_bo_record_path() {
    local repo_dir="$1" branch="$2" store encoded
    store="$(hos_bo_store_dir "$repo_dir")" || return 1
    encoded="$(hos_bo_encode "$branch")" || return 1
    printf '%s/%s.rec\n' "$store" "$encoded"
}

# hos_bo_write_record <repo_dir> <branch>
# Requires HOS_CYCLE_ID and HOS_CYCLE_ROLE non-empty in the calling
# environment (else returns 1, HOS_BO_REASON=no_cycle_id). Writes the record
# atomically (tmp file + mv), then prunes records older than 30 days
# (best-effort; failures ignored — hygiene, not correctness). Overwrites an
# existing record for the same branch ONLY if that record is already valid
# for THIS cycle (an idempotent re-run within one cycle) — it never silently
# adopts another cycle's record; a foreign/stale record at this path is a
# refusal (HOS_BO_REASON=foreign_record), never a clobber.
hos_bo_write_record() {
    local repo_dir="$1" branch="$2"
    HOS_BO_REASON=""

    if [[ -z "${HOS_CYCLE_ID:-}" || -z "${HOS_CYCLE_ROLE:-}" ]]; then
        HOS_BO_REASON="no_cycle_id"
        return 1
    fi

    # Values are single-line by construction (§4.3) — refuse anything that
    # could not round-trip through the key=value grammar.
    if [[ ! "$branch" =~ ^[A-Za-z0-9._/+-]+$ ]] \
        || [[ ! "$HOS_CYCLE_ID" =~ ^[A-Za-z0-9._/+-]+$ ]] \
        || [[ ! "$HOS_CYCLE_ROLE" =~ ^[A-Za-z0-9._/+-]+$ ]]; then
        HOS_BO_REASON="malformed"
        return 1
    fi

    local store path
    store="$(hos_bo_store_dir "$repo_dir")" || { HOS_BO_REASON="no_store"; return 1; }
    path="$(hos_bo_record_path "$repo_dir" "$branch")" || { HOS_BO_REASON="malformed"; return 1; }

    if [[ -e "$path" ]]; then
        if ! hos_bo_verify "$repo_dir" "$branch"; then
            HOS_BO_REASON="foreign_record"
            return 1
        fi
    fi

    mkdir -p "$store" 2>/dev/null || { HOS_BO_REASON="no_store"; return 1; }

    local created_at tmp
    created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    tmp="${path}.tmp.$$"
    if ! {
        printf 'schema=1\n'
        printf 'branch=%s\n' "$branch"
        printf 'cycle_id=%s\n' "$HOS_CYCLE_ID"
        printf 'role=%s\n' "$HOS_CYCLE_ROLE"
        printf 'created_at=%s\n' "$created_at"
    } > "$tmp" 2>/dev/null; then
        rm -f "$tmp" 2>/dev/null
        HOS_BO_REASON="no_store"
        return 1
    fi
    if ! mv -f "$tmp" "$path" 2>/dev/null; then
        rm -f "$tmp" 2>/dev/null
        HOS_BO_REASON="no_store"
        return 1
    fi

    # §4.4 — 30-day prune on write. Can only remove records already invalid
    # under condition 7 (a different/expired cycle_id), so this can never
    # itself create a lockout.
    find "$store" -maxdepth 1 -name '*.rec' -mtime +30 -delete 2>/dev/null || true

    return 0
}

# hos_bo_verify <repo_dir> <branch>
# Evaluates the §4.3 validity conditions in order. Returns 0 on valid. On
# failure returns 1 and sets HOS_BO_REASON to exactly one reason class. Never
# prints to stdout — diagnostics are the caller's job.
hos_bo_verify() {
    local repo_dir="$1" branch="$2"
    HOS_BO_REASON=""

    local store
    store="$(hos_bo_store_dir "$repo_dir")" || { HOS_BO_REASON="no_store"; return 1; }

    if [[ -z "${HOS_CYCLE_ID:-}" ]]; then
        HOS_BO_REASON="no_cycle_id"
        return 1
    fi

    local path
    path="$(hos_bo_record_path "$repo_dir" "$branch")" || { HOS_BO_REASON="malformed"; return 1; }

    if [[ ! -f "$path" ]]; then
        HOS_BO_REASON="no_record"
        return 1
    fi

    local size
    size="$(_hos_bo_stat_size "$path")"
    if [[ -z "$size" || "$size" -gt 4096 ]]; then
        HOS_BO_REASON="no_record"
        return 1
    fi

    if [[ ! -r "$path" ]]; then
        HOS_BO_REASON="unreadable"
        return 1
    fi

    local content
    if ! content="$(cat "$path" 2>/dev/null)"; then
        HOS_BO_REASON="unreadable"
        return 1
    fi

    local line
    while IFS= read -r line; do
        if [[ ! "$line" =~ ^[a-z_]+=.*$ ]]; then
            HOS_BO_REASON="malformed"
            return 1
        fi
    done <<< "$content"

    local key count
    for key in schema branch cycle_id role; do
        count="$(printf '%s\n' "$content" | grep -c "^${key}=")" || true
        if [[ "$count" -ne 1 ]]; then
            HOS_BO_REASON="malformed"
            return 1
        fi
    done

    local schema_v branch_v cycle_v role_v
    schema_v="$(printf '%s\n' "$content" | sed -n 's/^schema=//p')"
    branch_v="$(printf '%s\n' "$content" | sed -n 's/^branch=//p')"
    cycle_v="$(printf '%s\n' "$content" | sed -n 's/^cycle_id=//p')"
    role_v="$(printf '%s\n' "$content" | sed -n 's/^role=//p')"

    if [[ "$schema_v" != "1" ]]; then
        HOS_BO_REASON="malformed"
        return 1
    fi
    if [[ "$branch_v" != "$branch" ]]; then
        HOS_BO_REASON="wrong_branch"
        return 1
    fi
    if [[ "$cycle_v" != "$HOS_CYCLE_ID" ]]; then
        HOS_BO_REASON="wrong_cycle"
        return 1
    fi
    if [[ "$role_v" != "worker" ]]; then
        HOS_BO_REASON="wrong_role"
        return 1
    fi

    return 0
}

# hos_bo_audit_refusal <repo_dir> <branch> <reason>
# Best-effort R9 event, written through the standard audit-log writer (#888)
# via scripts/oversight/lib/audit_log.sh. If that helper is absent or fails,
# this returns 0 WITHOUT output — an audit-sink failure must never convert a
# refusal into a pass, and must never mask the caller's refusal message.
# Always returns 0.
hos_bo_audit_refusal() {
    local repo_dir="$1" branch="$2" reason="$3"
    local audit_lib="$repo_dir/scripts/oversight/lib/audit_log.sh"

    [[ -f "$audit_lib" ]] || return 0
    # shellcheck disable=SC1090
    source "$audit_lib" 2>/dev/null || return 0
    command -v audit_write_event >/dev/null 2>&1 || return 0

    local ts json
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    json="$(printf '{"event":"branch-ownership-refused","branch":"%s","role":"worker","reason":"%s","cycle_id":"%s","timestamp":"%s"}' \
        "$branch" "$reason" "${HOS_CYCLE_ID:-}" "$ts")"
    audit_write_event "$json" "$repo_dir" >/dev/null 2>&1 || true
    return 0
}
