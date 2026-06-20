#!/usr/bin/env bash
# machine_lock.sh — Atomic machine-global lock for the HOS automation orchestrator.
#
# Enforces at most ONE orchestrator probe→claim→dispatch(spawn) cycle machine-wide.
# Released immediately after workers are spawned (ADR-3: lock scope = spawn only).
#
# Design constraints:
#   - bash 3.2 compatible (macOS default) — flock(1) FORBIDDEN.
#   - mkdir is the atomic mutex (POSIX, local-fs atomic).
#   - Check-then-create is FORBIDDEN (TOCTOU race).
#   - Lock held for spawn only; per-task worker lifetime is governed by claim+heartbeat.
#
# Usage (source this file, then call acquire_lock / release_lock):
#   source scripts/automation/lib/machine_lock.sh
#   acquire_lock || exit 0          # contention: exit cleanly
#   <probe → claim → dispatch>
#   release_lock                    # called by trap on EXIT too

# ---------------------------------------------------------------------------
# Configuration constants (O17 resolution)
# ---------------------------------------------------------------------------
# Primary and fallback lock paths — machine-global (one path per machine,
# shared across all repos).  Resolution is deterministic: depends only on
# /tmp writability, NOT on repo identity (O17/O18 invariant).
#
HOS_LOCK_PRIMARY="/tmp/hos-worker.lock"
HOS_LOCK_FALLBACK="${HOME}/.hos/worker.lock"

# Orchestrator hang timeout (ADR-3): the machine lock should be held for
# seconds (probe + dispatch), not minutes.  20m is already anomalous.
# This is NOT max_task_runtime (4h), which governs per-task workers.
HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS=1200  # 20 minutes

# The marker token that must appear in the orchestrator's command line.
# The cron invocation should include this as an argv element so ps -o command=
# shows it.  See O18.
HOS_ORCHESTRATOR_MARKER="hos-orchestrator"
HOS_ORCHESTRATOR_SCRIPT="hos_orchestrator.sh"

# Populated by resolve_lock_dir; used by all other functions.
_HOS_LOCK_DIR=""

# ---------------------------------------------------------------------------
# resolve_lock_dir — O17: single canonical path, same result on every repo's cron
# ---------------------------------------------------------------------------
resolve_lock_dir() {
    if [ -w /tmp ]; then
        _HOS_LOCK_DIR="$HOS_LOCK_PRIMARY"
    else
        mkdir -p "$(dirname "$HOS_LOCK_FALLBACK")" 2>/dev/null || true
        _HOS_LOCK_DIR="$HOS_LOCK_FALLBACK"
    fi
}

# ---------------------------------------------------------------------------
# _meta_path, _write_meta, _read_meta_pid, _read_meta_started
# ---------------------------------------------------------------------------
_meta_path() { printf '%s/meta' "$_HOS_LOCK_DIR"; }

_write_meta() {
    local started
    started="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'pid=%d\nstarted=%s\nmarker=%s\n' \
        "$$" "$started" "$HOS_ORCHESTRATOR_MARKER" \
        > "$(_meta_path)" 2>/dev/null
}

_read_meta_field() {
    local field="$1"
    local meta
    meta="$(_meta_path)"
    [ -f "$meta" ] || return 1
    grep "^${field}=" "$meta" | head -1 | cut -d= -f2-
}

_read_meta_pid()     { _read_meta_field pid; }
_read_meta_started() { _read_meta_field started; }

# ---------------------------------------------------------------------------
# _is_holder_alive — alive-AND-command-match (O18; never bare kill -0)
# ---------------------------------------------------------------------------
_is_holder_alive() {
    local pid="$1"
    local cmd
    # ps -o command= prints the full command line for the given PID.
    # On macOS (bash 3.2 target) this works without the -p flag alternative.
    cmd="$(ps -p "$pid" -o command= 2>/dev/null)" || return 1
    [ -z "$cmd" ] && return 1
    # Require BOTH the script name AND the argv marker (O18).
    printf '%s' "$cmd" | grep -q "$HOS_ORCHESTRATOR_SCRIPT" || return 1
    printf '%s' "$cmd" | grep -q "$HOS_ORCHESTRATOR_MARKER" || return 1
    return 0
}

# ---------------------------------------------------------------------------
# _seconds_since_iso — seconds elapsed since an ISO-8601 UTC timestamp
# (bash 3.2 compatible via date)
# ---------------------------------------------------------------------------
_seconds_since_iso() {
    local iso="$1"
    local then_epoch now_epoch
    # macOS date -j -f <format> <value> +%s
    then_epoch="$(date -j -f '%Y-%m-%dT%H:%M:%SZ' "$iso" '+%s' 2>/dev/null)" || return 1
    now_epoch="$(date -u '+%s')"
    echo $(( now_epoch - then_epoch ))
}

# ---------------------------------------------------------------------------
# _reclaim_stale_lock — remove the lock dir and retry acquire
# ---------------------------------------------------------------------------
_reclaim_stale_lock() {
    _hos_log "stale-lock-reclaim: removing stale lock at $_HOS_LOCK_DIR"
    rm -rf "$_HOS_LOCK_DIR"
}

# ---------------------------------------------------------------------------
# _hos_log — minimal log line (stdout; callers redirect as needed)
# ---------------------------------------------------------------------------
_hos_log() {
    printf '[hos-lock] %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

# ---------------------------------------------------------------------------
# acquire_lock — returns 0 on success, 1 on legitimate contention (caller exits)
# ---------------------------------------------------------------------------
# Retries once after stale-lock reclaim; no further retry (legitimate
# contention → caller should wait for next cron window).
acquire_lock() {
    resolve_lock_dir

    # Jitter: 0–60s random sleep to spread load across near-simultaneous cron fires.
    # This is load-spreading ONLY — not mutual exclusion.
    # HOS_LOCK_JITTER_MAX=0 disables jitter (used in tests).
    local jitter_max="${HOS_LOCK_JITTER_MAX:-60}"
    local jitter=0
    [ "$jitter_max" -gt 0 ] && jitter=$(( RANDOM % (jitter_max + 1) ))
    [ "$jitter" -gt 0 ] && sleep "$jitter"

    local attempt
    for attempt in 1 2; do
        if mkdir "$_HOS_LOCK_DIR" 2>/dev/null; then
            # Won the lock.
            _write_meta
            _hos_log "acquired lock at $_HOS_LOCK_DIR (pid=$$)"
            return 0
        fi

        # Contention — inspect the holder.
        _handle_contention || return 1
        # _handle_contention returns 0 only after reclaiming a stale lock;
        # retry the mkdir once.
    done

    # Should not be reached (at most 2 attempts).
    _hos_log "lock-contention: could not acquire after reclaim — exiting"
    return 1
}

# _handle_contention — called when mkdir fails.
# Returns 0 if a stale lock was reclaimed (caller should retry mkdir).
# Returns 1 if the holder is alive (legitimate contention).
_handle_contention() {
    local pid started elapsed

    # Read PID from meta; if meta is unreadable, treat as stale.
    pid="$(_read_meta_pid 2>/dev/null)"
    if [ -z "$pid" ]; then
        _reclaim_stale_lock
        return 0
    fi

    # Check for HUNG lock first (ADR-3: orchestrator_lock_timeout = 20m).
    started="$(_read_meta_started 2>/dev/null)"
    if [ -n "$started" ]; then
        elapsed="$(_seconds_since_iso "$started" 2>/dev/null)"
        if [ -n "$elapsed" ] && [ "$elapsed" -ge "$HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS" ]; then
            _hos_log "hung-lock: holder pid=$pid held lock for ${elapsed}s (limit=${HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS}s) — reclaiming + paging"
            _fire_dead_man_switch "hung-lock pid=$pid elapsed=${elapsed}s"
            _reclaim_stale_lock
            return 0
        fi
    fi

    # Liveness + identity check (O18: alive-AND-command-match, never bare kill -0).
    if _is_holder_alive "$pid"; then
        _hos_log "lock-contention: legitimate holder pid=$pid — exiting this run"
        return 1
    else
        # Dead or command-mismatch: stale lock.
        _hos_log "stale-lock: holder pid=$pid is dead or command-mismatch"
        _reclaim_stale_lock
        return 0
    fi
}

# ---------------------------------------------------------------------------
# release_lock — remove the lock dir (called by trap on EXIT)
# ---------------------------------------------------------------------------
release_lock() {
    if [ -n "$_HOS_LOCK_DIR" ] && [ -d "$_HOS_LOCK_DIR" ]; then
        # #677: only the process that won the lock may release it.
        # A loser has _HOS_LOCK_DIR set (from resolve_lock_dir) but never wrote meta,
        # so its EXIT trap must not delete the winner's directory.
        local meta_pid
        meta_pid="$(_read_meta_pid 2>/dev/null)"
        if [ "$meta_pid" = "$$" ]; then
            rm -rf "$_HOS_LOCK_DIR"
            _hos_log "released lock at $_HOS_LOCK_DIR (pid=$$)"
        else
            _hos_log "release_lock: skipped — not owner (owner=$meta_pid, us=$$)"
        fi
    fi
}

# ---------------------------------------------------------------------------
# setup_lock_trap — install EXIT trap so the lock is always released
# ---------------------------------------------------------------------------
setup_lock_trap() {
    trap 'release_lock' EXIT TERM INT
}

# ---------------------------------------------------------------------------
# _fire_dead_man_switch — stub; wired to observability.py / pager in T14
# ---------------------------------------------------------------------------
_fire_dead_man_switch() {
    local reason="$1"
    # In production, this writes to the ledger and triggers the configured
    # pager path.  Placeholder until observability.py (B13) is built.
    _hos_log "DEAD-MAN-SWITCH: $reason"
}
