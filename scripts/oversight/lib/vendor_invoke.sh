#!/usr/bin/env bash
# vendor_invoke.sh — one bash launch primitive for agy/codex (ADR-1683 D-1/D-2).
#
# Sourced library, NOT an executable entry point. Fixes #1683: passing a large
# review prompt as a single argv element hits Linux's per-argument MAX_ARG_STRLEN
# (131,072 bytes) and dies with a silent E2BIG at execve. Every vendor CLI call
# in this repo must go through here, on stdin, never via argv.
#
# BOUNDARY (ADR-1683 D-7 / ADR-1643 AD-16): this helper's vendor set is agy and
# codex ONLY. `claude` invocations go through ADR-1643's `bootstrap/invoke_agent.sh`
# / `scripts/automation/agent_invoke_cli.py`, which carry agent resolution, posture
# files, and `--settings` — concepts agy/codex do not have. Neither primitive may
# grow a path into the other's vendor set.
#
# Usage (from scripts/*.sh):
#   source "$(dirname "${BASH_SOURCE[0]}")/oversight/lib/vendor_invoke.sh"
#
#   prompt_file=$(vendor_invoke_tmpfile)
#   printf '%s' "$prompt" > "$prompt_file"
#   stdout_file=$(vendor_invoke_tmpfile)
#   if vendor_invoke agy 900 "$prompt_file" "$stdout_file" --sandbox --output-format json; then
#       result=$(cat "$stdout_file")
#   else
#       # $VENDOR_INVOKE_CLASS / $VENDOR_INVOKE_DETAIL / $VENDOR_INVOKE_STDERR /
#       # $VENDOR_INVOKE_RC / $VENDOR_INVOKE_BYTES are set on every call.
#       :
#   fi
#
# vendor_invoke_tmpfile creates a file under this helper's own per-process temp
# directory (D-6), so the EXIT/INT/TERM trap installed on first use cleans it up
# on every exit path, including failure — no per-call rm -f needed by callers.
#
# THE BASE FORMS — the single place in the repo where these live (D-2). Verified
# empirically against the installed binary before this PR opened, per D-2's
# instruction (agy's `-p` flag form was not to be assumed):
#
#   agy --version                                          -> 1.2.3  (2026-09-15)
#   agy --sandbox --output-format json -p < prompt_file     -> rc=2, empty stdout,
#       stderr: "flag needs an argument: -p"  (this build's `-p` requires a value;
#       a bare `-p` with the prompt on stdin, as ADR-1683 originally anticipated
#       trying, does not work on 1.2.3)
#   agy --sandbox --output-format json    < prompt_file     -> rc=0, well-formed
#       JSON envelope, same shape as the pre-#1683 `-p "$prompt"` invocation
#       (non-TTY stdin alone triggers agy's print/non-interactive mode; #1683 had
#       already verified this via `echo … | agy`).
#
# Per the above, the verified fallback (drop `-p` entirely) is what ships:
#
#   agy   -> `agy`        with `< "$prompt_file"`
#   codex -> `codex exec` with `< "$prompt_file"`
#
# Lens flags (e.g. `--sandbox --output-format json`) are the CALLER's — this
# helper owns only the base command and the stdin contract, never prompt content.

# shellcheck disable=SC2034
# The five VENDOR_INVOKE_* globals are this library's public output contract,
# read by the sourcing caller (see `second_review_failure_json` in
# scripts/run_second_review.sh). shellcheck cannot follow a `source` back into
# the consumer, so it reports every one of them as unused. Scoped to the whole
# file deliberately: they are assigned on ~15 lines and a per-line directive on
# each would read as noise rather than as one contract. A genuinely unused
# local in this file still reports normally.

# ── One shared timeout implementation (ADR-1643 AD-5.3) — do not add a second ─
# shellcheck source=scripts/oversight/run_with_retry.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/run_with_retry.sh"

_VENDOR_INVOKE_TMPDIR=""
_VENDOR_INVOKE_TRAP_INSTALLED=""

# _vendor_invoke_init_tmpdir — create the one per-process temp dir (idempotent).
# mktemp -d (not mkdir -p on a $$-suffixed path): mode 0700 regardless of the
# caller's umask, and it never silently reuses a directory another local user
# pre-created at a predictable name — mkdir -p would do both of those wrong.
#
# Called eagerly at the bottom of this file (source time), not only lazily
# from vendor_invoke()/vendor_invoke_tmpfile(). Reason: `prompt_file=$(vendor_invoke_tmpfile)`
# runs in a command-substitution SUBSHELL, and bash's own optimization for a
# subshell whose last command is a plain external command (here, the trailing
# `mktemp` in vendor_invoke_tmpfile) replaces that subshell process via exec()
# instead of forking — so any EXIT/INT/TERM trap installed inside it is never
# run, because the bash instance that would run it is gone. mktemp's name is
# unpredictable per call, so if initialization happened for the first time
# inside such a subshell, each subshell would mint its own directory and none
# of them would ever be cleaned up (verified empirically: two distinct
# directories leaked using the naive lazy-only approach). Initializing once at
# source time — never inside a subshell, since `source` runs in the caller's
# own shell — establishes one directory and one real, live trap before any
# subshell exists; later lazy calls from within subshells then see the
# directory already created and skip straight past both the mktemp and the
# trap-install (the idempotency guards below), so they never attempt to
# install a trap of their own in the first place.
_vendor_invoke_init_tmpdir() {
    if [[ -z "$_VENDOR_INVOKE_TMPDIR" || ! -d "$_VENDOR_INVOKE_TMPDIR" ]]; then
        _VENDOR_INVOKE_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/hos_vendor_invoke.XXXXXX")"
    fi
    _vendor_invoke_install_trap
}

# _vendor_invoke_install_trap — chain onto any existing EXIT/INT/TERM handler
# rather than clobbering it (D-6). Idempotent: installs at most once per
# process, even if the helper is sourced or called more than once.
#
# `trap -p SIG` always prints its command already shell-quoted, e.g.
# `trap -- 'echo '\''hi'\''' EXIT`. Recovering the literal command by stripping
# quotes with a regex breaks the moment the original command itself contains a
# quote (verified: a pre-existing `trap "echo 'hi'" EXIT` produced a
# syntactically broken composed trap under the old sed-based extraction, and
# NEITHER the original handler NOR the new cleanup ran). Instead, strip only
# the fixed `trap -- ` prefix and ` SIG` suffix — both literal, never part of
# the quoted payload — and let the shell itself unquote the remainder via
# `eval printf '%s'`, which is quote-syntax-safe by construction.
#
# KNOWN RESIDUAL CASE (considered, not missed): chaining cannot save a
# pre-existing handler that itself ends in `exit` — the shell leaves before
# reaching `${cleanup}`, and the temp dir survives until the OS reaps /tmp.
# Prepending cleanup instead would merely move the loss to the other handler,
# which is the one the caller wrote and therefore the one that must win. The
# leak is bounded (one dir of prompt/stdout files, mode 0700) and this helper
# is the only writer, so the trade is deliberate.
_vendor_invoke_install_trap() {
    [[ -n "$_VENDOR_INVOKE_TRAP_INSTALLED" ]] && return 0
    _VENDOR_INVOKE_TRAP_INSTALLED=1
    local sig existing_raw existing cleanup="rm -rf \"$_VENDOR_INVOKE_TMPDIR\""
    for sig in EXIT INT TERM; do
        existing_raw="$(trap -p "$sig")"
        if [[ -n "$existing_raw" ]]; then
            existing="${existing_raw#trap -- }"
            existing="${existing%" $sig"}"
            existing="$(eval "printf '%s' $existing")"
            # shellcheck disable=SC2064  # expansion at install time is required,
            # not accidental: $_VENDOR_INVOKE_TMPDIR is per-process and is baked
            # into the handler here so the trap still names the right directory
            # if the variable is later unset or reassigned. Deferring expansion
            # (single quotes) would be the bug.
            trap "${existing}; ${cleanup}" "$sig"
        else
            # shellcheck disable=SC2064  # same rationale as above.
            trap "${cleanup}" "$sig"
        fi
    done
}

# vendor_invoke_tmpfile — mktemp a file under the shared per-process dir.
vendor_invoke_tmpfile() {
    _vendor_invoke_init_tmpdir
    mktemp "$_VENDOR_INVOKE_TMPDIR/vi.XXXXXX"
}

# _vendor_invoke_process_stderr RAW_TEXT — D-5: last 10 lines -> collapse all
# whitespace runs to single spaces -> redact known secret patterns -> truncate
# to 500 bytes with a trailing ellipsis. Order matters: truncating before
# redacting can split a token into something the patterns no longer match.
_vendor_invoke_process_stderr() {
    local raw="$1" tail
    [[ -z "$raw" ]] && return 0
    tail="$(printf '%s' "$raw" | tail -n 10 | tr -s '[:space:]' ' ')"
    tail="$(printf '%s' "$tail" | sed -E \
        -e 's/gh[pousr]_[A-Za-z0-9]{20,}/[REDACTED]/g' \
        -e 's/github_pat_[A-Za-z0-9_]{20,}/[REDACTED]/g' \
        -e 's/sk-[A-Za-z0-9_-]{20,}/[REDACTED]/g' \
        -e 's/AKIA[0-9A-Z]{16}/[REDACTED]/g' \
        -e 's/ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\./[REDACTED]/g' \
        -e 's/[Bb]earer +[A-Za-z0-9._-]{12,}/[REDACTED]/g')"
    tail="${tail//$HOME/~}"
    if [[ ${#tail} -gt 500 ]]; then
        tail="${tail:0:499}…"
    fi
    printf '%s' "$tail"
}

# _vendor_invoke_is_arg_parse_error TEXT — narrow, bounded signature match for
# "the CLI rejected its own flags" (ADR-1683 gap in the rc-classification
# table: a Go-style flag package returns rc=2 with EMPTY stdout on a bad flag,
# which the ADR's literal rule would otherwise misclassify as `vendor`). Only
# fires alongside rc=2 AND empty stdout (checked by the caller) — this is not a
# general stderr-sniffing heuristic.
_vendor_invoke_is_arg_parse_error() {
    printf '%s' "$1" | grep -qE 'flag needs an argument|flag provided but not defined|^Usage of '
}

# vendor_invoke <vendor> <timeout_sec> <prompt_file> <stdout_file> [extra argv...]
#
# Returns 0 iff the child exited 0 AND stdout_file is non-empty. Always sets
# (on every call, success or failure):
#   VENDOR_INVOKE_RC       raw child exit status ("" if never launched)
#   VENDOR_INVOKE_CLASS    ok | harness | vendor
#   VENDOR_INVOKE_DETAIL   ok | unknown_vendor | binary_not_found | not_executable |
#                          exec_failed | argv_content_detected | vendor_nonzero_exit |
#                          timeout | empty_output | arg_parse_failed
#   VENDOR_INVOKE_STDERR   redacted, single-line, <=500-byte tail (D-5)
#   VENDOR_INVOKE_BYTES    byte size of <prompt_file>
vendor_invoke() {
    local vendor="$1" timeout_sec="$2" prompt_file="$3" stdout_file="$4"
    shift 4
    local extra=("$@")

    _vendor_invoke_init_tmpdir

    VENDOR_INVOKE_RC=""
    VENDOR_INVOKE_CLASS=""
    VENDOR_INVOKE_DETAIL=""
    VENDOR_INVOKE_STDERR=""
    VENDOR_INVOKE_BYTES=0
    : > "$stdout_file"

    if [[ -f "$prompt_file" ]]; then
        VENDOR_INVOKE_BYTES="$(wc -c < "$prompt_file" | tr -d '[:space:]')"
    fi

    # D-2 runtime guard: no prompt content may ever reach argv through this
    # function. This makes REINTRODUCING #1683 through this path impossible,
    # not merely detectable — checked before any launch, regardless of vendor.
    local a
    for a in "${extra[@]}"; do
        if [[ ${#a} -gt 4096 ]]; then
            VENDOR_INVOKE_CLASS="harness"
            VENDOR_INVOKE_DETAIL="argv_content_detected"
            echo "vendor_invoke: refused — an extra argv element for '${vendor}' exceeds 4096 bytes (looks like prompt content in argv, not a lens flag)" >&2
            return 1
        fi
    done

    local base=()
    case "$vendor" in
        agy)   base=(agy) ;;
        codex) base=(codex exec) ;;
        *)
            VENDOR_INVOKE_CLASS="harness"
            VENDOR_INVOKE_DETAIL="unknown_vendor"
            echo "vendor_invoke: unknown vendor '${vendor}' (must be agy or codex)" >&2
            return 1
            ;;
    esac

    if ! command -v "${base[0]}" &>/dev/null; then
        VENDOR_INVOKE_CLASS="harness"
        VENDOR_INVOKE_DETAIL="binary_not_found"
        echo "vendor_invoke: '${base[0]}' not found on PATH — harness defect, not a vendor failure" >&2
        return 1
    fi

    local stderr_file rc=0 raw_stderr stdout_bytes=0
    stderr_file="$(mktemp "$_VENDOR_INVOKE_TMPDIR/vi.XXXXXX")"
    with_timeout "$timeout_sec" "${base[@]}" "${extra[@]}" \
        < "$prompt_file" > "$stdout_file" 2> "$stderr_file" || rc=$?
    VENDOR_INVOKE_RC="$rc"

    raw_stderr="$(cat "$stderr_file" 2>/dev/null || true)"
    VENDOR_INVOKE_STDERR="$(_vendor_invoke_process_stderr "$raw_stderr")"
    rm -f "$stderr_file"

    [[ -s "$stdout_file" ]] && stdout_bytes="$(wc -c < "$stdout_file" | tr -d '[:space:]')"

    if [[ "$rc" -eq 126 ]]; then
        VENDOR_INVOKE_CLASS="harness"; VENDOR_INVOKE_DETAIL="not_executable"
    elif [[ "$rc" -eq 127 ]]; then
        VENDOR_INVOKE_CLASS="harness"; VENDOR_INVOKE_DETAIL="exec_failed"
    elif [[ "$rc" -eq 124 ]]; then
        # Deliberately `vendor`, though the cause is genuinely ambiguous: a real
        # vendor stall and a SECOND_REVIEW_VENDOR_TIMEOUT set too low are
        # indistinguishable from here. `vendor` is the useful default because the
        # timeout value is this repo's own constant and visible to whoever reads
        # the record, whereas a hung vendor is not. The `timeout` detail is what
        # actually routes the operator; the class is the coarser hint.
        VENDOR_INVOKE_CLASS="vendor"; VENDOR_INVOKE_DETAIL="timeout"
    elif [[ "$rc" -eq 2 && "$stdout_bytes" -eq 0 ]] && _vendor_invoke_is_arg_parse_error "$raw_stderr"; then
        # ADR-1683 gap fix: an argument-parse failure (wrong flags shipped in
        # THIS repo) is a harness defect, not a vendor-side failure — despite
        # rc!=0, sending an operator to check the vendor's auth/quota here
        # would be exactly the misdiagnosis this ADR exists to remove.
        VENDOR_INVOKE_CLASS="harness"; VENDOR_INVOKE_DETAIL="arg_parse_failed"
        echo "vendor_invoke: '${base[0]}' rejected its own invocation flags (arg_parse_failed, rc=2) — fix the flags shipped in this repo; this is not a vendor-side failure" >&2
    elif [[ "$rc" -ne 0 ]]; then
        VENDOR_INVOKE_CLASS="vendor"; VENDOR_INVOKE_DETAIL="vendor_nonzero_exit"
    elif [[ "$stdout_bytes" -eq 0 ]]; then
        VENDOR_INVOKE_CLASS="vendor"; VENDOR_INVOKE_DETAIL="empty_output"
    else
        VENDOR_INVOKE_CLASS="ok"; VENDOR_INVOKE_DETAIL="ok"
    fi

    [[ "$rc" -eq 0 && "$stdout_bytes" -gt 0 ]]
}

# Eager, source-time initialization — see the comment on
# _vendor_invoke_init_tmpdir above for why this must not be left purely lazy.
_vendor_invoke_init_tmpdir
