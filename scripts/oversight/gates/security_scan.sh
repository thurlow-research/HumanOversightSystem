#!/usr/bin/env bash
# security_scan.sh — security static analysis gate (blocking on HIGH).
#
# Runs bandit for security issues and pip-audit for dependency vulnerabilities.
#
# HIGH severity bandit findings = gate failure (blocking).
# MEDIUM findings are collected but do NOT block here — they feed into the
# static_analysis.py risk validator score instead.
#
# Exit 0 = no blocking findings. Exit 1 = HIGH findings, dependency advisories not
# covered by the #1776 exemption roster (scripts/oversight/security_scan_logic.py),
# or an unreadable scan.
#
# Usage: ./security_scan.sh file.py [file2.py ...]
#        ./security_scan.sh --diff <ref> | --step <n> | --staged | --all | --help
#
# Argument grammar shared with run_gates.sh and the other file-list gates —
# see scripts/oversight/lib/changeset.sh (#1759).

set -euo pipefail

# Temp files this script creates; removed on every exit path, including a kill
# (#2054 S3). The TERM/INT/HUP handlers turn a signal into an exit so the EXIT
# trap runs.
_TMP_CLEANUP=()
_cleanup_tmp() { [[ ${#_TMP_CLEANUP[@]} -gt 0 ]] && rm -rf "${_TMP_CLEANUP[@]}"; return 0; }
trap _cleanup_tmp EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM


GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/oversight/ensure_venv.sh
source "$GATES_DIR/../ensure_venv.sh"
# shellcheck source=scripts/oversight/gates/check_suspension.sh
source "$GATES_DIR/check_suspension.sh"
is_suspended "security" && { print_suspended "security"; exit 0; }
# shellcheck source=scripts/oversight/lib/changeset.sh
source "$GATES_DIR/../lib/changeset.sh"

hos_changeset_parse security_scan "$@" || exit $HOS_CHANGESET_EXIT
hos_changeset_summary security_scan

FILES=()
# INV-SELECTOR: switch on STATUS, never on ${#FILES[@]} (#1759). STATUS=empty
# skips pip-audit too — nothing changed, so there is nothing to gate, and
# skipping keeps the empty path fast and side-effect-free (network call).
case "$HOS_CHANGESET_STATUS" in
    empty)
        hos_changeset_not_checked security_scan
        exit 0
        ;;
    all|unscoped)
        if [[ "$HOS_CHANGESET_STATUS" == "unscoped" ]]; then
            # No files specified and --all not set: default to scanning all
            # Python files rather than silently skipping bandit and recording
            # GATE PASS (a no-op pass is indistinguishable from a real pass —
            # HIGH-severity findings would go unscanned yet the gate would
            # exit 0). Mirrors lint_check.sh / type_check.sh. (#976)
            echo "security_scan: no files specified — defaulting to --all (full project scan)"
        fi
        FILES=()
        while IFS= read -r line; do FILES+=("$line"); done < <(find . -name "*.py" \
            -not -path "./.venv/*" -not -path "./scripts/oversight/.venv/*" \
            -not -path "./.git/*")
        if [[ ${#FILES[@]} -eq 0 ]]; then
            # A project with zero Python files is an honest bandit skip (not a
            # hidden pass); pip-audit below still runs against the dependency set.
            echo "security_scan: no Python files found in project — bandit SKIP"
        fi
        ;;
    ok)
        FILES=("${HOS_CHANGESET_FILES[@]}")
        ;;
esac

ERRORS=0
# Checks that did not run. A pass line that omits these would read as a clean
# result when it is a failure to check (#1776, architect A2).
NOT_PERFORMED=()
GATE_TIMEOUT="${GATE_TIMEOUT:-120}"   # seconds per tool invocation
GATE_RETRIES="${GATE_RETRIES:-2}"     # retries on crash/timeout

# --- bandit: HIGH severity only (blocking) ---
echo "=== bandit (HIGH severity) ==="
echo "security_scan: bandit received ${#FILES[@]} file(s)"
if [[ -x "$VENV_BIN/bandit" ]]; then
    if [[ ${#FILES[@]} -gt 0 ]]; then
        BANDIT_TMP=$(mktemp "${TMPDIR:-/tmp}/bandit_XXXXXX")
        _TMP_CLEANUP+=("$BANDIT_TMP")
        # Unit of work: run bandit under the configured timeout, capture to temp.
        # bandit exits 1 when it FINDS issues — that is a successful scan for us
        # (we parse the JSON afterward). Only timeout (124) or a bandit error
        # (rc >= 2) counts as a failed attempt worth retrying.
        _run_bandit() {
            with_timeout "$GATE_TIMEOUT" "$VENV_BIN/bandit" -f json -lll "${FILES[@]}" > "$BANDIT_TMP" 2>/dev/null
            local brc=$?
            [[ $brc -eq 0 || $brc -eq 1 ]] && return 0
            return "$brc"
        }
        if run_with_retry "bandit" "$GATE_RETRIES" "true" _run_bandit; then
            BANDIT_OUT=$(cat "$BANDIT_TMP")
            # No zero-default fallback: an unparseable bandit report must not read as zero
            # findings (#1776). The count snippet's stderr stays visible.
            if HIGH_COUNT=$(echo "$BANDIT_OUT" | PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c \
                "import json,sys; d=json.load(sys.stdin); \
                 print(len([r for r in d.get('results',[]) if r.get('issue_severity')=='HIGH']))") \
                && [[ "$HIGH_COUNT" =~ ^[0-9]+$ ]]; then
                if [[ "$HIGH_COUNT" -gt 0 ]]; then
                    echo "GATE FAIL: $HIGH_COUNT HIGH severity bandit finding(s)"
                    echo "$BANDIT_OUT" | PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c \
                        "import json,sys; [print(f\"  {r['filename']}:{r['line_number']} [{r['test_id']}] {r['issue_text']}\") \
                         for r in json.load(sys.stdin).get('results',[]) if r.get('issue_severity')=='HIGH']" 2>/dev/null || true
                    ERRORS=$((ERRORS + 1))
                else
                    echo "OK: no HIGH severity findings"
                fi
            else
                echo "GATE FAIL: bandit output could not be parsed — nothing was decided; this is a failure to check, not a clean result"
                ERRORS=$((ERRORS + 1))
            fi
        else
            echo "GATE FAIL: bandit did not complete after retries"
            ERRORS=$((ERRORS + 1))
        fi
        rm -f "$BANDIT_TMP"
        unset -f _run_bandit
    fi
else
    echo "SKIP: bandit not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    NOT_PERFORMED+=("bandit SKIPPED — not installed")
fi

# --- pip-audit: dependency vulnerabilities (network-dependent — optional if it hangs) ---
# The verdict is decided by security_scan_logic.py: it applies the time-boxed
# exemption roster (#1776) and fails closed on anything it cannot read. The shell
# only runs pip-audit and checks that a completed scan produced parseable JSON.
echo ""
echo "=== pip-audit (dependency vulnerabilities) ==="
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
if [[ -x "$PIP_AUDIT" ]]; then
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
        PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" "$GATES_DIR/../security_scan_logic.py" filter \
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
    echo "GATE FAIL: $ERRORS security check(s) failed"
    exit 1
else
    if [[ ${#NOT_PERFORMED[@]} -gt 0 ]]; then
        NOT_PERFORMED_TEXT=""
        for entry in "${NOT_PERFORMED[@]}"; do
            NOT_PERFORMED_TEXT+="${NOT_PERFORMED_TEXT:+; }$entry"
        done
        echo "GATE PASS: no blocking security issues ($NOT_PERFORMED_TEXT)"
    else
        echo "GATE PASS: no blocking security issues"
    fi
    exit 0
fi
