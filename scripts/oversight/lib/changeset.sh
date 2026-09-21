#!/usr/bin/env bash
# changeset.sh — shared changeset-resolution library (#1759).
#
# One argument grammar for run_gates.sh and every file-list gate. Before this
# library, run_gates.sh forwarded its own argv verbatim to each gate script,
# so `run_gates.sh --diff origin/main` pushed the literal strings "--diff" and
# "origin/main" into each gate's own FILES array as bogus filenames — the gate
# scanned zero real files and reported PASS/SKIP having checked nothing
# (docs/v0.7.0/TECHNICAL-DESIGN-1759-run-gates-diff-parsing.md).
#
# Sourced library, NOT an executable entry point.
#   - No `set -e`/`set -u`, no top-level side effects — safe to source
#     repeatedly (same contract as lib/step_range.sh).
#   - Never calls `exit`. Fatal cases return 1 and set HOS_CHANGESET_EXIT so
#     the caller can write its own artifact before exiting.
#   - bash 3.2 compatible: no `mapfile`, no `declare -A`; every array
#     expansion is guarded as `${arr[@]+"${arr[@]}"}`.
#
# Public surface (§4.2 of the design):
#   hos_changeset_parse <label> [arg ...]     — parse argv, resolve the
#                                                changeset, populate the
#                                                globals below.
#   hos_changeset_summary <label>             — print the one-line summary.
#   hos_changeset_not_checked <label>         — print the case-2 NOT CHECKED
#                                                line.
#   hos_changeset_skip_kind <label> <kind> <n> — print the zero-of-kind SKIP
#                                                 line.
#   hos_changeset_usage <label>               — print the usage block.
#
# Globals set by hos_changeset_parse (§4.3), reset at the top of every call:
#   HOS_CHANGESET_STATUS     ok | unscoped | all | empty — the SOLE authority
#                             on scope intent (INV-SELECTOR). No code path may
#                             infer scope from ${#FILES[@]}.
#   HOS_CHANGESET_MODE       none | all | explicit | diff | step | staged |
#                             empty-changeset
#   HOS_CHANGESET_FILES      array — existing, repo-root-relative paths.
#                             Empty unless STATUS=ok.
#   HOS_CHANGESET_RAW_COUNT  paths the selector produced before the existence
#                             filter
#   HOS_CHANGESET_DROPPED    paths dropped because they are not on disk
#   HOS_CHANGESET_DELETED    paths excluded by --diff-filter=ACMRT
#                             (diff/step/staged only)
#   HOS_CHANGESET_REF        raw --diff ref / resolved BASE..HEAD / empty
#   HOS_CHANGESET_STEP       the --step value, or empty
#   HOS_CHANGESET_SOURCE     human-readable selector description
#   HOS_CHANGESET_EXIT       set only on a fatal: 2 (usage) or 3 (resolution)

# shellcheck source=step_range.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/step_range.sh"

_HCS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_HCS_CLASSIFIER="$_HCS_LIB_DIR/../changeset_logic.py"

# ── Internal helpers ──────────────────────────────────────────────────────────

# Human-readable name for a selector, used only in conflict messages.
_hcs_selector_name() {
    case "$1" in
        all) printf -- '--all' ;;
        staged) printf -- '--staged' ;;
        empty-changeset) printf -- '--empty-changeset' ;;
        diff) printf -- '--diff' ;;
        explicit) printf 'explicit path(s)' ;;
        step) printf -- '--step' ;;
        *) printf '%s' "$1" ;;
    esac
}

# _hcs_fatal <label> <code> <message> — record a fatal: print the diagnostic
# and usage to stderr, set HOS_CHANGESET_EXIT. Caller must `return 1` itself.
_hcs_fatal() {
    local label="$1" code="$2" msg="$3"
    echo "${label}: ${msg}" >&2
    hos_changeset_usage "$label" >&2
    HOS_CHANGESET_EXIT="$code"
}

# _hcs_git_preconditions <label> — G1/G2. Sets _HCS_TOPLEVEL on success.
_hcs_git_preconditions() {
    local label="$1"
    if ! _HCS_TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)"; then
        _hcs_fatal "$label" 3 "--diff/--step/--staged require a git repository; none found at $(pwd)"
        return 1
    fi
    local top_p cwd_p
    top_p="$(cd "$_HCS_TOPLEVEL" 2>/dev/null && pwd -P)"
    cwd_p="$(pwd -P)"
    if [[ "$top_p" != "$cwd_p" ]]; then
        _hcs_fatal "$label" 3 "must be run from the repository root ($_HCS_TOPLEVEL); cwd is $(pwd)"
        return 1
    fi
    return 0
}

# _hcs_join_comma <part> [part ...] — join with ", " (bash 3.2: IFS join only
# honours the first char of IFS in "$*", so this is a small explicit loop).
_hcs_join_comma() {
    local out="" first=true part
    for part in "$@"; do
        if $first; then
            out="$part"
            first=false
        else
            out="${out}, ${part}"
        fi
    done
    printf '%s' "$out"
}

# _hcs_classify_missing <label> <ref-or-empty> <path ...>
# Runs the Ruling-I classifier once over the whole missing-path batch and acts
# on the result: drops deleted/shallow/undecidable paths (counting them and
# warning once each), and fails fatally, immediately, on any fabricated path
# without waiting for the set to empty (TD-D13/TD-D15).
_hcs_classify_missing() {
    local label="$1" ref="$2"; shift 2
    local missing=("$@")
    local python_bin="${OVERSIGHT_PYTHON:-python3}"

    local hcs_input
    hcs_input="$(printf '%s\n' "${missing[@]}")"

    local output rc=0
    if [[ -n "$ref" ]]; then
        output="$(printf '%s\n' "$hcs_input" | PYTHONSAFEPATH=1 "$python_bin" "$_HCS_CLASSIFIER" classify --ref "$ref" 2>/dev/null)" || rc=$?
    else
        output="$(printf '%s\n' "$hcs_input" | PYTHONSAFEPATH=1 "$python_bin" "$_HCS_CLASSIFIER" classify 2>/dev/null)" || rc=$?
    fi

    if [[ $rc -eq 2 ]]; then
        # The classifier itself could not run — degrade every path to
        # undecidable. A broken classifier must never become a new way to
        # fail a green PR (TD-D15).
        echo "${label}: the missing-path classifier could not run — treating all missing path(s) as undecidable" >&2
        output=""
        local p
        for p in "${missing[@]}"; do
            output="${output}undecidable"$'\t'"${p}"$'\n'
        done
    fi

    local fabricated_paths=() degraded_count=0
    local state path
    while IFS=$'\t' read -r state path; do
        [[ -z "$state" ]] && continue
        case "$state" in
            deleted)
                HOS_CHANGESET_DROPPED=$((HOS_CHANGESET_DROPPED + 1))
                echo "${label}: path not on disk (deleted), excluded: ${path}" >&2
                ;;
            fabricated)
                fabricated_paths+=("$path")
                ;;
            shallow|undecidable)
                HOS_CHANGESET_DROPPED=$((HOS_CHANGESET_DROPPED + 1))
                degraded_count=$((degraded_count + 1))
                echo "${label}: path not on disk and history is truncated (${state}) — cannot tell a deletion from a typo; excluded: ${path}" >&2
                ;;
        esac
    done <<< "$output"

    if [[ ${#fabricated_paths[@]} -gt 0 ]]; then
        _hcs_fatal "$label" 3 "path(s) git has never tracked and which are not on disk: ${fabricated_paths[*]} — refusing to report a result on a file list that names files that do not exist"
        return 1
    fi

    if [[ $degraded_count -gt 0 ]]; then
        echo "${label}: a missing path could not be classified with full confidence — this clone may be shallow (fetch-depth: 1) or its history could not be read. Run 'git fetch --unshallow', or pass --diff/--step so classification uses the ref's tree instead of history." >&2
    fi

    return 0
}

# _hcs_apply_rex <label> <ref-or-empty> <candidate ...>
# The existence filter (§4.4 R-EX), shared by explicit/diff/step/staged.
_hcs_apply_rex() {
    local label="$1" ref="$2"; shift 2
    local candidates=("$@")
    HOS_CHANGESET_RAW_COUNT=${#candidates[@]}
    HOS_CHANGESET_FILES=()

    local missing=() c
    for c in ${candidates[@]+"${candidates[@]}"}; do
        if [[ -e "$c" ]]; then
            HOS_CHANGESET_FILES+=("$c")
        else
            missing+=("$c")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        _hcs_classify_missing "$label" "$ref" "${missing[@]}" || return 1
    fi

    if [[ $HOS_CHANGESET_RAW_COUNT -eq 0 ]]; then
        HOS_CHANGESET_STATUS="empty"
        return 0
    fi

    if [[ ${#HOS_CHANGESET_FILES[@]} -eq 0 ]]; then
        # Every candidate was dropped (deleted/shallow/undecidable), never
        # fabricated (that already returned above). An all-deletions
        # changeset resolved perfectly — the honest answer is case 2, not a
        # resolution failure (Ruling I / RISK-1).
        HOS_CHANGESET_STATUS="empty"
        return 0
    fi

    HOS_CHANGESET_STATUS="ok"
    return 0
}

# _hcs_resolve_via_diff <label> <classify-ref> <diff-arg ...>
# Shared by diff/step/staged: computes the unfiltered count (for the deletion
# tally, TD-D4), the ACMRT-filtered candidate list, then applies R-EX.
# <classify-ref> is what tier 1 of the Ruling-I classifier is told (the raw
# --diff ref, the resolved step range, or HEAD for --staged).
_hcs_resolve_via_diff() {
    local label="$1" classify_ref="$2"; shift 2
    local diff_args=("$@")

    local stderr_file
    stderr_file="$(mktemp)"
    local unfiltered_out rc=0
    unfiltered_out="$(git diff --name-only "${diff_args[@]}" -- 2>"$stderr_file")" || rc=$?
    if [[ $rc -ne 0 ]]; then
        local gstderr
        gstderr="$(cat "$stderr_file" 2>/dev/null)"
        rm -f "$stderr_file"
        _hcs_fatal "$label" 3 "cannot resolve '${diff_args[*]}': ${gstderr}"
        return 1
    fi
    rm -f "$stderr_file"

    local unfiltered_files=() _line
    while IFS= read -r _line; do
        [[ -n "$_line" ]] && unfiltered_files+=("$_line")
    done <<< "$unfiltered_out"

    local candidates_out
    candidates_out="$(git diff --name-only --diff-filter=ACMRT "${diff_args[@]}" -- 2>/dev/null || true)"
    local candidates=()
    while IFS= read -r _line; do
        [[ -n "$_line" ]] && candidates+=("$_line")
    done <<< "$candidates_out"

    HOS_CHANGESET_DELETED=$(( ${#unfiltered_files[@]} - ${#candidates[@]} ))

    _hcs_apply_rex "$label" "$classify_ref" ${candidates[@]+"${candidates[@]}"}
}

# ── Public surface ────────────────────────────────────────────────────────────

hos_changeset_usage() {
    local label="$1"
    cat <<USAGE
Usage: ${label} [--diff <ref> | --step <n> | --staged | --all | <path> ...] [--help]

  --diff <ref>   Resolve the changeset from a two-dot git diff against <ref>
                 (deletions excluded from what is forwarded; <ref> may itself
                 be a range, e.g. "origin/main...HEAD").
  --step <n>     Resolve the changeset from step <n>'s recorded commit range
                 (audit log step-head events). May be combined with another
                 selector as metadata only — it never scopes when one is given.
  --staged       Resolve the changeset from the git index (git diff --cached).
  --all          Enumerate the whole project (this script's own extension set).
  <path> ...     An explicit, space-separated file list.
  --help, -h     Print this usage block and exit 0.

Selectors are mutually exclusive: --diff, --staged, --all, --empty-changeset
and explicit paths cannot be combined with each other.

Exit codes: 0 = ran (or nothing to check); 1 = a blocking finding;
2 = usage error (nothing ran); 3 = the changeset could not be resolved
(nothing ran).
USAGE
}

hos_changeset_not_checked() {
    local label="$1"
    printf '%s: NOT CHECKED — %s resolved to 0 scannable file(s). Nothing was checked; this is not a pass.\n' \
        "$label" "$HOS_CHANGESET_SOURCE"
}

hos_changeset_skip_kind() {
    local label="$1" kind="$2" matched="$3"
    printf '%s: SKIP — %d of %d changeset file(s) are %s (nothing for this gate to check).\n' \
        "$label" "$matched" "${#HOS_CHANGESET_FILES[@]}" "$kind"
}

hos_changeset_summary() {
    local label="$1"
    local parts=()
    if [[ ${HOS_CHANGESET_DELETED:-0} -gt 0 ]]; then
        parts+=("${HOS_CHANGESET_DELETED} deletion(s) excluded")
    fi
    if [[ ${HOS_CHANGESET_DROPPED:-0} -gt 0 ]]; then
        parts+=("${HOS_CHANGESET_DROPPED} path(s) not on disk")
    fi
    local suffix=""
    if [[ ${#parts[@]} -gt 0 ]]; then
        suffix=" ($(_hcs_join_comma "${parts[@]}"))"
    fi
    printf '%s: changeset = %d file(s) from %s%s\n' \
        "$label" "${#HOS_CHANGESET_FILES[@]}" "$HOS_CHANGESET_SOURCE" "$suffix"
}

hos_changeset_parse() {
    local label="$1"; shift

    HOS_CHANGESET_STATUS=""
    HOS_CHANGESET_MODE=""
    HOS_CHANGESET_FILES=()
    HOS_CHANGESET_RAW_COUNT=0
    HOS_CHANGESET_DROPPED=0
    HOS_CHANGESET_DELETED=0
    HOS_CHANGESET_REF=""
    HOS_CHANGESET_STEP=""
    HOS_CHANGESET_SOURCE=""
    HOS_CHANGESET_EXIT=""

    local selector="" diff_ref="" step_val=""
    local diff_seen=false step_seen=false
    local explicit_paths=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                hos_changeset_usage "$label"
                HOS_CHANGESET_EXIT=0
                return 1
                ;;
            --all)
                if [[ -n "$selector" && "$selector" != "all" ]]; then
                    _hcs_fatal "$label" 2 "'--all' and '$(_hcs_selector_name "$selector")' are mutually exclusive selectors"
                    return 1
                fi
                selector="all"
                shift
                ;;
            --staged)
                if [[ -n "$selector" && "$selector" != "staged" ]]; then
                    _hcs_fatal "$label" 2 "'--staged' and '$(_hcs_selector_name "$selector")' are mutually exclusive selectors"
                    return 1
                fi
                selector="staged"
                shift
                ;;
            --empty-changeset)
                if [[ -n "$selector" && "$selector" != "empty-changeset" ]]; then
                    _hcs_fatal "$label" 2 "'--empty-changeset' and '$(_hcs_selector_name "$selector")' are mutually exclusive selectors"
                    return 1
                fi
                selector="empty-changeset"
                shift
                ;;
            --diff)
                if $diff_seen; then
                    _hcs_fatal "$label" 2 "--diff given more than once"
                    return 1
                fi
                if [[ $# -lt 2 || "$2" == -* ]]; then
                    _hcs_fatal "$label" 2 "--diff requires a <ref> argument"
                    return 1
                fi
                if [[ -n "$selector" && "$selector" != "diff" ]]; then
                    _hcs_fatal "$label" 2 "'--diff' and '$(_hcs_selector_name "$selector")' are mutually exclusive selectors"
                    return 1
                fi
                diff_seen=true
                diff_ref="$2"
                selector="diff"
                shift 2
                ;;
            --step)
                if $step_seen; then
                    _hcs_fatal "$label" 2 "--step given more than once"
                    return 1
                fi
                if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ ]]; then
                    _hcs_fatal "$label" 2 "--step requires a non-negative integer"
                    return 1
                fi
                step_seen=true
                step_val="$2"
                shift 2
                ;;
            -*)
                _hcs_fatal "$label" 2 "unknown option '$1' — refusing to treat it as a filename"
                return 1
                ;;
            *)
                if [[ -n "$selector" && "$selector" != "explicit" ]]; then
                    _hcs_fatal "$label" 2 "'$1' and '$(_hcs_selector_name "$selector")' are mutually exclusive selectors"
                    return 1
                fi
                selector="explicit"
                explicit_paths+=("$1")
                shift
                ;;
        esac
    done

    if $step_seen; then
        HOS_CHANGESET_STEP="$step_val"
        if [[ -z "$selector" ]]; then
            selector="step"
        fi
    fi

    case "$selector" in
        "")
            HOS_CHANGESET_STATUS="unscoped"
            HOS_CHANGESET_MODE="none"
            HOS_CHANGESET_SOURCE="no selector (project enumeration)"
            ;;
        all)
            HOS_CHANGESET_STATUS="all"
            HOS_CHANGESET_MODE="all"
            HOS_CHANGESET_SOURCE="--all (project enumeration)"
            ;;
        empty-changeset)
            HOS_CHANGESET_STATUS="empty"
            HOS_CHANGESET_MODE="empty-changeset"
            HOS_CHANGESET_SOURCE="an empty changeset resolved by the runner"
            ;;
        explicit)
            HOS_CHANGESET_MODE="explicit"
            HOS_CHANGESET_SOURCE="${#explicit_paths[@]} explicit path(s)"
            _hcs_apply_rex "$label" "" "${explicit_paths[@]}" || return 1
            ;;
        diff)
            HOS_CHANGESET_MODE="diff"
            HOS_CHANGESET_REF="$diff_ref"
            HOS_CHANGESET_SOURCE="--diff ${diff_ref}"
            _hcs_git_preconditions "$label" || return 1
            _hcs_resolve_via_diff "$label" "$diff_ref" "$diff_ref" || return 1
            ;;
        step)
            _hcs_git_preconditions "$label" || return 1
            local range
            range="$(get_step_range "$step_val" "$_HCS_TOPLEVEL")"
            if [[ -z "$range" ]]; then
                _hcs_fatal "$label" 3 "step ${step_val} has no step-head audit event — cannot scope a changeset; pass --diff <ref>"
                return 1
            fi
            local base="${range%%..*}"
            if [[ -z "$base" ]]; then
                _hcs_fatal "$label" 3 "step ${step_val} has no base commit (range '${range}') — cannot scope a changeset; pass --diff <ref>"
                return 1
            fi
            HOS_CHANGESET_MODE="step"
            HOS_CHANGESET_REF="$range"
            HOS_CHANGESET_SOURCE="--step ${step_val} (${range})"
            _hcs_resolve_via_diff "$label" "$range" "$range" || return 1
            ;;
        staged)
            HOS_CHANGESET_MODE="staged"
            HOS_CHANGESET_SOURCE="--staged"
            _hcs_git_preconditions "$label" || return 1
            _hcs_resolve_via_diff "$label" "HEAD" "--cached" || return 1
            ;;
    esac

    return 0
}
