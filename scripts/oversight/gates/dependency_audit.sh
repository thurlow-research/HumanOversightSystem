#!/usr/bin/env bash
# dependency_audit.sh — repo-scoped dependency vulnerability gate (pip-audit, blocking on findings).
#
# Runs pip-audit against the installed environment and decides the verdict with
# scripts/oversight/security_scan_logic.py and its time-boxed exemption roster
# (#1776). It was split out of security_scan.sh in #1605; the lane below is
# that gate's pip-audit lane, moved unchanged. bandit/HIGH-severity static
# analysis lives in security_scan.sh (#1605).
#
# Repo-scoped: it takes no file arguments and ignores every path argument —
# the django_check.sh / astro_check.sh / collection_integrity.sh precedent.
# Dependency posture is a property of the installed environment, not of a
# changeset. The single exception is the literal --empty-changeset token.
#
# Why --empty-changeset IS honoured (AD-2a, reversing AD-2's unconditional run):
# AD-2 first ruled that the gate must run even on an empty changeset, because
# dependency posture is a property of the installed environment, not of a diff.
# That still holds as an argument against scoping by file list, which is why
# every path argument is ignored. It does not reach the literal --empty-changeset
# token. That token is not a file list. Per TD-D9 (#1759) it is the runner's
# explicit declaration that the whole invocation verifies nothing. Honouring a
# mode signal is not inferring scope from a file count, and it does not bring
# back the file-scoped INV-SELECTOR skip that AD-2 superseded. The reversal was
# forced by the pinned invariant TC-A2 (#1759): a run that checked nothing must
# exit 0. Do not re-add an unconditional run without re-opening AD-2a. On this
# token the gate makes no network call and prints NOT CHECKED, never GATE PASS.
#
# Blocking on findings. The verdict comes from `security_scan_logic.py filter`
# and its exemption roster (#1776). A scan whose output cannot be read, or a
# roster that cannot be decided, is GATE FAIL. An execution failure (timeout or
# network) after retries is NOT CHECKED, named in the GATE PASS line, and is
# non-blocking locally.
#
# Exit 0 = clean, suspended, --empty-changeset, pip-audit not installed (SKIP)
# or NOT CHECKED. Exit 1 = a kept advisory, unparseable output, an undecidable
# roster, or an invalid HOS_PIP_AUDIT_BIN override.
#
# HOS_PIP_AUDIT_BIN: off by default, inert in the real pipeline, present only so
# a test can point this gate at a stub binary (see the seam note below).
#
# Usage: ./dependency_audit.sh
#        (any other argument, except --empty-changeset, is ignored)

set -euo pipefail

_GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$_GATES_DIR/check_suspension.sh"
is_suspended "dependencies" && { print_suspended "dependencies"; exit 0; }

# AD-2a: the runner's explicit "this invocation verifies nothing" signal. The
# message mirrors hos_changeset_not_checked's vocabulary without sourcing
# changeset.sh — this gate parses no changeset (AD-2).
for _arg in "$@"; do
    if [[ "$_arg" == "--empty-changeset" ]]; then
        echo "dependency_audit: NOT CHECKED — empty changeset (nothing was checked; this is not a pass)"
        exit 0
    fi
done

# shellcheck source=scripts/oversight/ensure_venv.sh
source "$_GATES_DIR/../ensure_venv.sh"

# Temp files this script creates; removed on every exit path, including a kill
# (#2054 S3). The TERM/INT/HUP handlers turn a signal into an exit so the EXIT
# trap runs.
_TMP_CLEANUP=()
_cleanup_tmp() { [[ ${#_TMP_CLEANUP[@]} -gt 0 ]] && rm -rf "${_TMP_CLEANUP[@]}"; return 0; }
trap _cleanup_tmp EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

ERRORS=0
# Checks that did not run. A pass line that omits these would read as a clean
# result when it is a failure to check (#1776, architect A2).
NOT_PERFORMED=()
GATE_TIMEOUT="${GATE_TIMEOUT:-120}"   # seconds per tool invocation
GATE_RETRIES="${GATE_RETRIES:-2}"     # retries on crash/timeout

echo "=== pip-audit (dependency vulnerabilities) ==="
echo "dependency_audit: repo-scoped — dependency posture is a property of the installed environment, not of a changeset; any arguments given (other than --empty-changeset) are ignored."
# --- pip-audit: dependency vulnerabilities (network-dependent — optional if it hangs) ---
# The verdict is decided by security_scan_logic.py: it applies the time-boxed
# exemption roster (#1776) and fails closed on anything it cannot read. The shell
# only runs pip-audit and checks that a completed scan produced parseable JSON.
AUDIT_STATE="not-run"
AUDIT_STATUS=0
# HOS_PIP_AUDIT_BIN overrides the resolution below — off by default, inert in the
# real pipeline, present only so a test can point this gate at a stub binary
# (same seam as HOS_DETECT_SECRETS_BIN in secret_scan.sh). There is deliberately
# no way to override the audit PAYLOAD. An override that is not an executable file
# FAILS the gate: an env var must never be a route to silently disabling the
# dependency audit (the SKIP branch below is reserved for the unset default).
PIP_AUDIT="${HOS_PIP_AUDIT_BIN:-$VENV_BIN/pip-audit}"
if [[ -n "${HOS_PIP_AUDIT_BIN:-}" ]]; then
    echo "NOTE: pip-audit binary overridden by HOS_PIP_AUDIT_BIN=$HOS_PIP_AUDIT_BIN"
    NOT_PERFORMED+=("pip-audit binary overridden")
fi
if [[ -f "$PIP_AUDIT" && -x "$PIP_AUDIT" ]]; then
    PIP_AUDIT_TMP=$(mktemp "${TMPDIR:-/tmp}/pip_audit_XXXXXX")
    _TMP_CLEANUP+=("$PIP_AUDIT_TMP")
    # Unit of work: run pip-audit under the configured timeout, capture JSON.
    # pip-audit exits 1 when it FINDS vulnerabilities — that is a SUCCESSFUL scan
    # for us, NOT an execution failure (#672). We must separate the two:
    #   • completed scan (rc 0 or 1 AND parseable JSON) → hand to the logic module
    #   • timeout / network error (no parseable JSON)    → retry, then NOT CHECKED
    # Without this split, run_with_retry treats the vulns-found rc=1 as a crash,
    # exhausts retries, and — required=false — fails OPEN (gate exits 0 with real
    # vulnerabilities present). Mirrors the bandit unit-of-work above.
    # Sticky across attempts: set once ANY attempt completes with unreadable output
    # and never reset, so a later timeout cannot erase that evidence (CWE-636).
    _PIP_AUDIT_UNPARSEABLE=0
    _run_pip_audit() {
        with_timeout "$GATE_TIMEOUT" "$PIP_AUDIT" --progress-spinner off \
            --format json > "$PIP_AUDIT_TMP" 2>/dev/null
        local prc=$?
        # A completed scan emits parseable JSON regardless of rc 0/1. Require both
        # an expected rc and valid JSON before declaring the attempt a success.
        if [[ $prc -eq 0 || $prc -eq 1 ]] && PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c \
            "import json,sys; json.load(open(sys.argv[1]))" "$PIP_AUDIT_TMP" 2>/dev/null; then
            return 0
        fi
        # Preserve a timeout rc so run_with_retry logs "timeout"; otherwise surface
        # the execution failure rc (network error, resolver crash, …).
        # rc 0/1 with unparseable output is a corrupt scan: return non-zero so it is
        # retried (returning prc=0 here would be read as success).
        [[ $prc -eq 124 ]] && return 124
        if [[ $prc -eq 0 || $prc -eq 1 ]]; then
            _PIP_AUDIT_UNPARSEABLE=1
            return 1
        fi
        return "$prc"
    }
    if run_with_retry "pip-audit" "$GATE_RETRIES" "false" _run_pip_audit; then
        # $OVERSIGHT_PYTHON is the venv interpreter: system python lacks `packaging`
        # and would turn a healthy run into a spurious exit 2.
        PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" "$_GATES_DIR/../security_scan_logic.py" filter \
            < "$PIP_AUDIT_TMP" || AUDIT_STATUS=$?
        AUDIT_STATE="checked"
        if [[ $AUDIT_STATUS -ne 0 ]]; then
            ERRORS=$((ERRORS + 1))
        fi
    elif [[ $_PIP_AUDIT_UNPARSEABLE -eq 1 ]]; then
        # At least one attempt COMPLETED (rc 0/1) with unreadable output and none
        # produced a readable scan: a corrupt result is never a pass (CWE-636),
        # unlike a pure timeout/execution failure below.
        echo "GATE FAIL: pip-audit completed at least once but its output could not be parsed, and no attempt produced a readable scan ($((GATE_RETRIES + 1)) attempt(s)) — a scan whose result cannot be read is never treated as a pass."
        AUDIT_STATE="unparseable"
        ERRORS=$((ERRORS + 1))
    else
        # pip-audit exhausted retries on a genuine execution failure (timeout /
        # network) — required=false so the gate does not block, but it SAYS the
        # audit did not happen. This branch is NOT reached when vulnerabilities
        # are found; those exit cleanly above.
        echo "NOT CHECKED: pip-audit did not complete after retries — the dependency audit was NOT performed. This is a failure to check, not a clean result."
        AUDIT_STATE="not-checked"
    fi
    rm -f "$PIP_AUDIT_TMP"
    unset -f _run_pip_audit
    unset _PIP_AUDIT_UNPARSEABLE
elif [[ -n "${HOS_PIP_AUDIT_BIN:-}" ]]; then
    echo "GATE FAIL: HOS_PIP_AUDIT_BIN=$HOS_PIP_AUDIT_BIN is not an executable file — an override that disables the dependency audit is never a pass."
    AUDIT_STATE="override-invalid"
    ERRORS=$((ERRORS + 1))
else
    echo "SKIP: pip-audit not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    AUDIT_STATE="skipped"
fi
case "$AUDIT_STATE" in
    not-checked) NOT_PERFORMED+=("pip-audit NOT CHECKED — see above") ;;
    skipped)     NOT_PERFORMED+=("pip-audit SKIPPED — not installed") ;;
esac

echo ""
if [[ $AUDIT_STATUS -ne 0 && $AUDIT_STATUS -ne 1 ]]; then
    echo "GATE FAIL: the dependency audit could not be read or decided — see the error above. Nothing was decided; this is a failure to check, not a clean result."
fi
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: dependency audit failed"
    exit 1
else
    if [[ ${#NOT_PERFORMED[@]} -gt 0 ]]; then
        NOT_PERFORMED_TEXT=""
        for entry in "${NOT_PERFORMED[@]}"; do
            NOT_PERFORMED_TEXT+="${NOT_PERFORMED_TEXT:+; }$entry"
        done
        echo "GATE PASS: no blocking dependency vulnerabilities ($NOT_PERFORMED_TEXT)"
    else
        echo "GATE PASS: no blocking dependency vulnerabilities"
    fi
    exit 0
fi
