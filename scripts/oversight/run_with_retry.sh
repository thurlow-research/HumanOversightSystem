#!/usr/bin/env bash
# run_with_retry.sh — shared timeout + retry wrapper for validators and gates.
#
# Source this file to get run_with_retry(). Do not execute directly.
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/run_with_retry.sh"
#   run_with_retry LABEL TIMEOUT_SEC MAX_RETRIES REQUIRED cmd [args...]
#
# Arguments:
#   LABEL        Human-readable name for log output (e.g. "ip_check", "lint")
#   TIMEOUT_SEC  Kill process after this many seconds (0 = no timeout)
#   MAX_RETRIES  Total attempts = MAX_RETRIES + 1 (0 = try once, no retry)
#   REQUIRED     "true" | "false" — whether failure aborts the pipeline
#   cmd [args]   The command to run
#
# Return codes:
#   0  success
#   1  exhausted retries on a REQUIRED step  → caller should fail the job
#   2  exhausted retries on an OPTIONAL step → caller should log and skip
#
# Logging:
#   Per-attempt:  ⟳ label attempt N/MAX — reason (timeout|crash|exit N)
#   Final:        ✔ succeeded on attempt N  |  ⏸ SKIPPED  |  ✘ FAILED
#   Audit log:    appends to audit/oversight-log.jsonl on exhaustion

# ── Detect timeout binary (macOS uses gtimeout from brew, Linux uses timeout) ──
_TIMEOUT_BIN=""
if command -v timeout &>/dev/null; then
    _TIMEOUT_BIN="timeout"
elif command -v gtimeout &>/dev/null; then
    _TIMEOUT_BIN="gtimeout"
fi

run_with_retry() {
    local label="$1"
    local timeout_sec="$2"
    local max_retries="$3"
    local required="$4"
    shift 4

    local total_attempts=$(( max_retries + 1 ))
    local attempt=0
    local last_error=""
    local exit_code=0

    while [[ $attempt -lt $total_attempts ]]; do
        attempt=$(( attempt + 1 ))

        if [[ $attempt -gt 1 ]]; then
            printf "  \033[33m⟳\033[0m  %-28s attempt %d/%d — %s\n" \
                "$label" "$attempt" "$total_attempts" "$last_error"
            sleep 1  # brief pause before retry
        fi

        # Run with optional timeout
        if [[ -n "$_TIMEOUT_BIN" && "$timeout_sec" -gt 0 ]]; then
            "$_TIMEOUT_BIN" "$timeout_sec" "$@"
            exit_code=$?
        else
            "$@"
            exit_code=$?
        fi

        if [[ $exit_code -eq 0 ]]; then
            if [[ $attempt -gt 1 ]]; then
                printf "  \033[32m✔\033[0m  %-28s succeeded on attempt %d/%d\n" \
                    "$label" "$attempt" "$total_attempts"
            fi
            return 0
        elif [[ $exit_code -eq 124 ]]; then
            last_error="timeout after ${timeout_sec}s"
        else
            last_error="exit ${exit_code}"
        fi
    done

    # All attempts exhausted
    local outcome
    if [[ "$required" == "true" ]]; then
        printf "  \033[31m✘\033[0m  %-28s FAILED after %d attempt(s) (required — job fails)\n" \
            "$label" "$total_attempts"
        outcome="failed"
    else
        printf "  \033[33m⏸\033[0m  %-28s SKIPPED after %d attempt(s) (optional)\n" \
            "$label" "$total_attempts"
        outcome="skipped"
    fi

    # Append to audit log if it exists
    local audit_log="audit/oversight-log.jsonl"
    if [[ -f "$audit_log" || -d "audit" ]]; then
        local ts
        ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ")
        echo "{\"event\":\"validator-failure\",\"validator\":\"${label}\",\"required\":${required},\"attempts\":${total_attempts},\"final_outcome\":\"${outcome}\",\"last_error\":\"${last_error}\",\"timestamp\":\"${ts}\"}" \
            >> "$audit_log" 2>/dev/null || true
    fi

    if [[ "$required" == "true" ]]; then
        return 1  # caller should fail the job
    else
        return 2  # caller should log and skip
    fi
}
