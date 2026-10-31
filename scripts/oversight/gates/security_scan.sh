#!/usr/bin/env bash
# security_scan.sh — bandit HIGH-severity static analysis gate (blocking, file-scoped, offline).
#
# HIGH severity bandit findings = gate failure (blocking).
# MEDIUM findings are collected but do NOT block here — they feed into the
# static_analysis.py risk validator score instead.
#
# The bandit verdict is derived from the JSON file bandit writes with -o; its
# stdout is never read, because bandit decorates stdout with a progress bar once
# a scan exceeds ~1s — a DURATION trigger, not a file-count one (#1605, pm-agent
# V-2). A file bandit could not parse is a scan failure, not a clean file
# (#1605, AV-5). Dependency vulnerability auditing moved to dependency_audit.sh
# (#1605) — this gate no longer touches the network.
#
# Exit 0 = no HIGH findings (or bandit absent, or nothing to scan). Exit 1 = HIGH
# findings, an unscannable file, or a scan that did not complete or could not be
# read.
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
PROJECT_WIDE=false
# INV-SELECTOR: switch on STATUS, never on ${#FILES[@]} (#1759).
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
        PROJECT_WIDE=true
        ;;
    ok)
        FILES=("${HOS_CHANGESET_FILES[@]}")
        PROJECT_WIDE=false
        ;;
esac

# AD-5 part 1: filter the changeset to Python before bandit ever sees it —
# without this, CI would hand every .md in a docs PR to bandit and the
# unscannable-file branch below would go red on every documentation change.
if $PROJECT_WIDE; then
    if [[ ${#FILES[@]} -eq 0 ]]; then
        # Not a pass: nothing was scanned (same vocabulary as secret_scan.sh).
        echo "security_scan: NOT CHECKED — the project contains no Python file(s); nothing was scanned"
        exit 0
    fi
else
    PY_FILES=()
    for f in "${FILES[@]}"; do
        case "$f" in
            *.py) PY_FILES+=("$f") ;;
        esac
    done
    if [[ ${#PY_FILES[@]} -eq 0 ]]; then
        hos_changeset_skip_kind security_scan "Python" 0
        exit 0
    fi
    FILES=("${PY_FILES[@]}")
fi

ERRORS=0
GATE_TIMEOUT="${GATE_TIMEOUT:-120}"   # seconds per tool invocation
GATE_RETRIES="${GATE_RETRIES:-2}"     # retries on crash/timeout

# --- bandit: HIGH severity only (blocking) ---
echo "=== bandit (HIGH severity) ==="
echo "security_scan: bandit received ${#FILES[@]} file(s)"

# HOS_BANDIT_BIN (closes #1759's D4) — off by default, inert in the real
# pipeline, present only so the fail-closed branches below can be pinned
# deterministically: the real contamination trigger is elapsed scan time
# (#1605, V-2) and cannot be naturally reproduced in a fast test. No PATH
# fallback — this gate is venv-only, and adding one would change what runs in
# the real pipeline (out of scope).
BANDIT_BIN=""
if   [[ -n "${HOS_BANDIT_BIN:-}" ]]; then BANDIT_BIN="$HOS_BANDIT_BIN"
elif [[ -x "$VENV_BIN/bandit"    ]]; then BANDIT_BIN="$VENV_BIN/bandit"
fi

if [[ -z "$BANDIT_BIN" ]]; then
    # An honest skip: no GATE PASS line is reachable from here, so a run that
    # scanned nothing cannot read as a clean result (TD-1605 §3.5).
    echo "SKIP: bandit not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"
    exit 0
fi

# Removed by _cleanup_tmp on every exit path, including the inline exit 1 below.
BANDIT_JSON=$(mktemp "${TMPDIR:-/tmp}/bandit_json_XXXXXX")
_TMP_CLEANUP+=("$BANDIT_JSON")
BANDIT_LOG=$(mktemp "${TMPDIR:-/tmp}/bandit_log_XXXXXX")
_TMP_CLEANUP+=("$BANDIT_LOG")
# bandit's pinned config (COV-2): a gate-owned ini holding exactly `[bandit]`.
# Without --ini, bandit walks every directory target for a `.bandit` file and
# applies it (skips, baseline, recursive, ...) to the WHOLE run, so a committed
# symlink to a directory could suppress a finding. With --ini it performs no
# discovery at all. Written once; bandit never writes to it.
if ! BANDIT_INI=$(mktemp "${TMPDIR:-/tmp}/bandit_ini_XXXXXX"); then
    echo "GATE FAIL: could not create bandit's pinned config — nothing was scanned."
    exit 1
fi
_TMP_CLEANUP+=("$BANDIT_INI")
if ! printf '[bandit]\n' > "$BANDIT_INI"; then
    echo "GATE FAIL: could not create bandit's pinned config — nothing was scanned."
    exit 1
fi
BANDIT_LAST_RC=0
BANDIT_HIGH=""
BANDIT_ERRS=""
BANDIT_SCANNED=""
BANDIT_GIVEN=""

# Unit of work: one bandit attempt. The verdict comes ONLY from the JSON file
# bandit writes via -o — stdout is redirected to /dev/null and is never parsed,
# filtered or regexed (AD-3): bandit decorates stdout with a progress bar once
# a scan exceeds ~1s, and that rendering is TTY/width/locale-sensitive, not a
# channel to read correctness from. Truncate the file FIRST (: >) so a
# timeout-killed attempt N-1's leftover JSON is never read as attempt N's
# result (AV-3). Every option (including --ini) precedes `--`; only file paths follow it, so a
# file named like an option (e.g. --baseline=x.py, which --diff/--step/--staged
# can deliver from git) is never consumed as one (SEC-M2).
_run_bandit() {
    : > "$BANDIT_JSON"
    with_timeout "$GATE_TIMEOUT" "$BANDIT_BIN" -f json -lll --ini "$BANDIT_INI" -o "$BANDIT_JSON" -- "${FILES[@]}" >/dev/null 2>"$BANDIT_LOG"
    BANDIT_LAST_RC=$?
    # rc 1 is a successful scan WITH findings, not a crash (AV-4).
    if [[ "$BANDIT_LAST_RC" -ne 0 && "$BANDIT_LAST_RC" -ne 1 ]]; then
        return "$BANDIT_LAST_RC"
    fi
    # One extraction, not three: a single python call reads the file and prints
    # exactly "high=<int> errors=<int> scanned=<int> given=<int>", raising on any
    # shape deviation rather than emitting a default (AD-3/AD-4). `given` is the
    # number of DISTINCT paths this gate handed bandit (duplicates collapse in
    # bandit's file set); the comparison with `scanned` happens in the shell.
    local extraction
    if ! extraction=$(PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c '
import json, sys
d = json.load(open(sys.argv[1]))
r = d["results"]; m = d["metrics"]; e = d["errors"]          # KeyError -> fail closed
if not isinstance(r, list) or not isinstance(m, dict) or not isinstance(e, list):
    raise SystemExit(1)
h = len([x for x in r if x.get("issue_severity") == "HIGH"])
print("high=%d errors=%d scanned=%d given=%d" % (h, len(e), len(m) - 1, len(set(sys.argv[2:]))))
' "$BANDIT_JSON" "${FILES[@]}" 2>>"$BANDIT_LOG"); then
        BANDIT_LAST_RC=65
        return 65
    fi
    local high_kv errs_kv scan_kv given_kv
    read -r high_kv errs_kv scan_kv given_kv <<< "$extraction"
    BANDIT_HIGH="${high_kv#high=}"
    BANDIT_ERRS="${errs_kv#errors=}"
    BANDIT_SCANNED="${scan_kv#scanned=}"
    BANDIT_GIVEN="${given_kv#given=}"
    # Guard against a silent pass: [[ "" -gt 0 ]] evaluates false, so an empty
    # (or negative — an empty metrics dict yields scanned=-1) capture must fail
    # closed here, not read as zero.
    if [[ ! "$BANDIT_HIGH" =~ ^[0-9]+$ ]] || [[ ! "$BANDIT_ERRS" =~ ^[0-9]+$ ]] || [[ ! "$BANDIT_SCANNED" =~ ^[0-9]+$ ]] || [[ ! "$BANDIT_GIVEN" =~ ^[0-9]+$ ]]; then
        BANDIT_LAST_RC=65
        return 65
    fi
    return 0
}

if run_with_retry "bandit" "$GATE_RETRIES" "true" _run_bandit; then
    if [[ "$BANDIT_HIGH" -gt 0 ]]; then
        echo "GATE FAIL: $BANDIT_HIGH HIGH severity bandit finding(s)"
        PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c '
import json, sys
d = json.load(open(sys.argv[1]))
for r in d["results"]:
    if r.get("issue_severity") == "HIGH":
        print("  %s:%s [%s] %s" % (r["filename"], r["line_number"], r["test_id"], r["issue_text"]))
' "$BANDIT_JSON" || true   # reporting-only: the verdict is already FAIL; a listing failure must not mask it
        ERRORS=$((ERRORS + 1))
    fi
    if [[ "$BANDIT_ERRS" -gt 0 ]]; then
        echo "GATE FAIL: bandit could not scan $BANDIT_ERRS file(s) — these were not checked."
        PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c '
import json, sys
d = json.load(open(sys.argv[1]))
for x in d["errors"]:
    print("  %s: %s" % (x.get("filename", "?"), x.get("reason", "?")))
' "$BANDIT_JSON" || true   # reporting-only: the verdict is already FAIL; a listing failure must not mask it
        ERRORS=$((ERRORS + 1))
    fi
    # Coverage (COV-1): with no errors, bandit must have scanned every distinct
    # path it was given. A directory, a bandit-excluded path or a non-regular file
    # is skipped silently (rc 0, no metrics key, no errors entry), which would
    # otherwise read as a clean scan. Skipped when errors > 0 so no file is
    # reported twice. -ne, not -lt: scanned > given cannot happen, so if it did the
    # accounting is broken and the gate fails closed on that too. Deliberately
    # outside _run_bandit: it is deterministic, so a retry would only repeat it.
    if [[ "$BANDIT_ERRS" -eq 0 && "$BANDIT_SCANNED" -ne "$BANDIT_GIVEN" ]]; then
        echo "GATE FAIL: bandit scanned $BANDIT_SCANNED of $BANDIT_GIVEN file(s) given — the rest were not checked (a directory, a bandit-excluded path, or not a regular file). Zero findings are NOT inferred from files bandit did not scan."
        PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -c '
import json, os, sys
m = json.load(open(sys.argv[1]))["metrics"]
for p in sorted(set(sys.argv[2:])):
    if os.path.join(".", p) not in m and p not in m:
        print("  %s: not scanned by bandit" % p)
' "$BANDIT_JSON" "${FILES[@]}" || true   # reporting-only: the verdict is already FAIL; a listing failure must not mask it
        ERRORS=$((ERRORS + 1))
    fi
    if [[ "$BANDIT_HIGH" -eq 0 && "$BANDIT_ERRS" -eq 0 && "$BANDIT_SCANNED" -eq "$BANDIT_GIVEN" ]]; then
        echo "OK: no HIGH severity findings ($BANDIT_SCANNED file(s) scanned, 0 unscannable)"
    fi
else
    if [[ "$BANDIT_LAST_RC" -eq 2 ]]; then
        echo "GATE FAIL: bandit rejected its arguments (exit 2 — a usage error, not tool flakiness). Nothing was scanned; do not retry."
    elif [[ "$BANDIT_LAST_RC" -eq 65 ]]; then
        echo "GATE FAIL: bandit completed but its JSON output could not be parsed — nothing was verified. Zero findings are NOT inferred from a parse failure."
    else
        echo "GATE FAIL: bandit did not complete after retries"
    fi
    echo "  bandit stderr:"
    tail -n 5 "$BANDIT_LOG"
    # Exit inline (not ERRORS+1): no OK line and no GATE PASS line is reachable
    # after an incomplete scan (AC-4).
    exit 1
fi
unset -f _run_bandit

echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "GATE FAIL: $ERRORS security check(s) failed"
    exit 1
else
    echo "GATE PASS: no blocking security issues"
    exit 0
fi
