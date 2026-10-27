#!/usr/bin/env bash
# bootstrap/create_branch.sh — the single sanctioned branch-creation seam for
# the autonomous worker (#967, ADR-037, SPEC-967 R1)
#
# Creates a git branch AND writes a branch-ownership record as ONE operation.
# A path that creates a branch without recording ownership must not exist in
# the worker's autonomous flow. The record is durable, per-cycle-scoped
# state — it is read later in exactly one place (bootstrap/submit_pr.sh's
# --app worker refusal check, P2), never here, and never as a resume or
# completion signal (ADR-037 AD-2 anti-loophole). This script writes the
# record and creates the branch; it never reads the record back to decide
# anything about the branch's contents or review status.
#
# Usage:
#   bash bootstrap/create_branch.sh --issue <N> --slug <text> [--prefix <p>] [--from <ref>]
#
# Branch name (cycle-unique by construction — ADR-037 AD-3):
#   <prefix>-<issue>-<slug>-<HOS_CYCLE_TOKEN>-<pid>
#   e.g. worker-967-branch-ownership-260802191500-111
#
# <pid> is the trailing '-'-delimited field of HOS_CYCLE_ID (the cron
# process's $$), extracted — never re-derived — via
# pid="${HOS_CYCLE_ID##*-}". HOS_CYCLE_TOKEN alone is only second-precision,
# so two cycles minted in the same UTC second would otherwise collide (#1229,
# ADR-037 §6). Binding both the cycle token and the PID into the name makes
# "the rebuilt branch after a crashed cycle collides with the orphan it left
# behind" structurally impossible — a fresh cycle always mints a fresh token
# and PID pair.
#
# Requires HOS_CYCLE_ID, HOS_CYCLE_TOKEN, and HOS_CYCLE_ROLE=worker in the
# environment. These are minted exactly once per invocation by bin/hos-cron
# (ADR-037 AD-5) and are never at this script's discretion. An interactive or
# human-proxy session has none of these — it creates branches directly with
# git and writes no ownership record; this script is not for it.
#
# Base (#1827): without --from, the new branch is cut from the repository's
# DEFAULT branch, never from HEAD. The default branch <D> is resolved as
# bootstrap/hos_repo_sync.sh does, without network calls: origin/HEAD with the
# 'origin/' prefix stripped, else 'main'. The base ref is origin/<D> when an
# 'origin' remote exists, else local <D>. A missing base ref, or tracked
# changes in the working tree, is a refusal (before any ownership record is
# written); the script never falls back to HEAD. Why: a cycle parks on a
# pushed-but-unmerged foreign branch on purpose (#1044 guard), so a HEAD-based
# default would silently cut the new branch from that foreign work.
#
# --from <ref> lets a cycle create ITS OWN branch at the tip of a prior,
# unsubmitted (and therefore foreign — AD-1) branch, adopting its commits under
# new, cycle-owned authority. Adopting commits is NOT adopting their review
# status: whoever adopts via --from MUST re-run the full review chain in this
# cycle before any PR is opened — see .claude/agents/worker.md. Every --from
# use prints that obligation on stderr.
#
# One script invocation, no loops or substitution at the call site — see
# CLAUDE.md "Shell usage under the sandbox".
#
# Requires: bootstrap/lib/branch_ownership.sh, git.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."

# shellcheck source=lib/branch_ownership.sh
source "$SCRIPT_DIR/lib/branch_ownership.sh"

RED="\033[31m"; YELLOW="\033[33m"; GREEN="\033[32m"; RESET="\033[0m"
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }
ok()   { echo -e "  ${GREEN}✔${RESET}  $*" >&2; }

ISSUE=""
SLUG=""
PREFIX="worker"
FROM_REF=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --issue)  ISSUE="$2"; shift 2 ;;
        --slug)   SLUG="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --from)   FROM_REF="$2"; shift 2 ;;
        *)        err "Usage: $0 --issue <N> --slug <text> [--prefix <p>] [--from <ref>]" ;;
    esac
done

[[ -n "$ISSUE" ]] || err "--issue required"
[[ "$ISSUE" =~ ^[0-9]+$ ]] || err "--issue must be digits only, got: '$ISSUE'"
[[ -n "$SLUG" ]] || err "--slug required"
[[ "$PREFIX" =~ ^[a-z][a-z0-9-]{0,15}$ ]] || err "--prefix must match ^[a-z][a-z0-9-]{0,15}\$, got: '$PREFIX'"

# ── Slug sanitization (§5.2): lowercase, non-[a-z0-9] -> '-', collapse repeats,
# strip leading/trailing '-', truncate to 40 chars, refuse if empty ──────────
SLUG_SANITIZED="$(printf '%s' "$SLUG" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9' '-' | tr -s '-')"
SLUG_SANITIZED="${SLUG_SANITIZED#-}"
SLUG_SANITIZED="${SLUG_SANITIZED%-}"
SLUG_SANITIZED="${SLUG_SANITIZED:0:40}"
[[ -n "$SLUG_SANITIZED" ]] \
    || err "--slug '$SLUG' is empty after sanitization (lowercased, [a-z0-9] only, leading/trailing '-' stripped)"

# ── Step 1 — refuse without cycle identity ───────────────────────────────────
# This script is for autonomous worker cycles launched by bin/hos-cron only.
# A cycle that reaches here without identity (#1265) is audited the same way
# submit_pr.sh's own P2 no_cycle_id refusal already is — best-effort, via the
# shared hos_bo_audit_refusal helper — so the gap is visible in the audit
# trail instead of only in an ephemeral cron log nobody is watching.
if [[ -z "${HOS_CYCLE_ID:-}" || -z "${HOS_CYCLE_TOKEN:-}" || "${HOS_CYCLE_ROLE:-}" != "worker" ]]; then
    hos_bo_audit_refusal "$REPO_DIR" "" "no_cycle_id"
    err "HOS_CYCLE_ID / HOS_CYCLE_TOKEN / HOS_CYCLE_ROLE=worker are not set in this environment. bootstrap/create_branch.sh is for autonomous worker cycles launched by bin/hos-cron only (#967) — an interactive session creates a branch directly with git and never writes an ownership record."
fi

# ── Step 2 — compute the cycle-unique branch name (ADR-037 AD-3, §6) ────────
# HOS_CYCLE_TOKEN alone is second-precision; the trailing PID segment of
# HOS_CYCLE_ID closes the same-second collision window (#1229). Extracted,
# never re-derived — a fresh $$ here would be this script's own PID, not the
# cron process's.
[[ "$HOS_CYCLE_ID" == *-* ]] \
    || err "HOS_CYCLE_ID '$HOS_CYCLE_ID' contains no '-' — cannot extract the trailing PID segment required for the branch name (expected grammar \${ROLE}-\${PROJECT}-\${ts}-\$\$)."
pid="${HOS_CYCLE_ID##*-}"
[[ "$pid" =~ ^[0-9]+$ ]] \
    || err "HOS_CYCLE_ID '$HOS_CYCLE_ID' trailing field '$pid' is not purely numeric — expected the cron process PID as the last '-'-delimited segment."

BRANCH_NAME="${PREFIX}-${ISSUE}-${SLUG_SANITIZED}-${HOS_CYCLE_TOKEN}-${pid}"

# #2157: label the issue hos-in-progress and log "WORKING ON #<n>". Best-effort
# observability; stdout goes to stderr so the branch name stays the only stdout line.
_hos_mark_in_progress() {
    [[ "$PREFIX" == "worker" ]] || return 0
    # HOS-repo-only for now: scripts/automation/ is not shipped to consumer installs.
    [[ -f "$REPO_DIR/scripts/automation/in_progress.py" ]] || return 0
    local _tb=""
    command -v timeout &>/dev/null && _tb="timeout"
    [[ -n "$_tb" ]] || { command -v gtimeout &>/dev/null && _tb="gtimeout"; }
    (cd "$REPO_DIR" && ${_tb:+"$_tb" 60} python3 -m scripts.automation.in_progress mark --issue "$ISSUE" --branch "$BRANCH_NAME") >&2 \
        || warn "could not mark issue #${ISSUE} hos-in-progress (non-fatal, #2157)"
}

# ── Step 3 — idempotent re-entry within this cycle, or refuse (never adopt) ──
if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
    if hos_bo_verify "$REPO_DIR" "$BRANCH_NAME"; then
        git -C "$REPO_DIR" checkout --quiet "$BRANCH_NAME" \
            || err "Branch '${BRANCH_NAME}' has a valid ownership record for this cycle, but 'git checkout' failed."
        ok "re-entered existing branch '${BRANCH_NAME}' (already owned by this cycle)"
        _hos_mark_in_progress
        echo "${BRANCH_NAME}"
        exit 0
    fi
    err "Branch '${BRANCH_NAME}' already exists locally but its ownership record is not valid for this cycle (reason: ${HOS_BO_REASON:-unknown}). This script never adopts an existing branch (#967, ADR-037 AD-3) — the branch name is cycle-unique, so this indicates a name collision outside the ownership model; investigate before retrying."
fi

# ── Step 4a — resolve the base; every refusal happens BEFORE the record (#1827) ─
# The base never depends on where HEAD sits. No network calls: origin/HEAD was
# set by hos_repo_sync.sh at session start and origin is fetched by bin/hos-cron.
BASE_REF=""
if [[ -n "$FROM_REF" ]]; then
    [[ "$FROM_REF" != -* ]] \
        || err "create_branch.sh: --from '${FROM_REF}' starts with '-' and would be parsed as a git option — refusing (#1827)."
    git -C "$REPO_DIR" rev-parse --verify -q "${FROM_REF}^{commit}" >/dev/null 2>&1 \
        || err "create_branch.sh: --from '${FROM_REF}' does not resolve to a commit — refusing (#1827)."
    warn "create_branch.sh: --from '${FROM_REF}' — ADOPTING commits this cycle did not create. Adopted commits carry NO review status: the full review chain MUST be re-run in this cycle before any PR is opened (#967, #1827; see .claude/agents/worker.md)."
else
    DEFAULT_BRANCH="$(git -C "$REPO_DIR" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
    DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
    if git -C "$REPO_DIR" remote get-url origin >/dev/null 2>&1; then
        BASE_REF="refs/remotes/origin/${DEFAULT_BRANCH}"
    else
        BASE_REF="refs/heads/${DEFAULT_BRANCH}"
    fi
    BASE_SHA="$(git -C "$REPO_DIR" rev-parse --verify -q "${BASE_REF}^{commit}" 2>/dev/null || true)"
    [[ -n "$BASE_SHA" ]] \
        || err "create_branch.sh: default base '${BASE_REF}' does not exist — refusing to fall back to HEAD (#1827). Fetch origin, or pass --from <ref> to choose a base deliberately."

    HEAD_SHA="$(git -C "$REPO_DIR" rev-parse --verify -q 'HEAD^{commit}' 2>/dev/null || true)"
    HEAD_DESC="$(git -C "$REPO_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    [[ -n "$HEAD_DESC" ]] || HEAD_DESC="detached @ ${HEAD_SHA:0:12}"

    DIRTY_STATUS="$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" \
        || err "create_branch.sh: 'git status' failed — cannot verify the working tree is clean, refusing (#1827)."
    if [[ -n "$DIRTY_STATUS" ]]; then
        err "create_branch.sh: tracked changes in the working tree would be carried onto the new branch from '${HEAD_DESC}' — refusing (#1827). Commit, stash, or discard them first."
    fi
    if [[ "$HEAD_SHA" != "$BASE_SHA" ]]; then
        warn "create_branch.sh: HEAD is on '${HEAD_DESC}', not the default base — new branch cut from '${BASE_REF}' (#1827). Use --from to adopt other work."
    fi
fi

# ── Step 4 — write the ownership record BEFORE creating the branch ──────────
# Record-first, not branch-first: a record with no branch is inert (nothing
# can be pushed); a branch with no record is a confusing fail-closed refusal
# later. §5.2.
if ! hos_bo_write_record "$REPO_DIR" "$BRANCH_NAME"; then
    err "Could not write branch-ownership record for '${BRANCH_NAME}' (reason: ${HOS_BO_REASON:-unknown})."
fi

# ── Step 5 — create the branch; roll back the record on failure ─────────────
# --no-track on both paths: an upstream of origin/<D> (e.g. --from origin/main)
# would defeat the #1044 guard and make a bare 'git push' target the default
# branch.
if [[ -n "$FROM_REF" ]]; then
    CHECKOUT_FROM="$FROM_REF"
    CHECKOUT_ARGS=(--no-track -b "$BRANCH_NAME" "$FROM_REF")
else
    CHECKOUT_FROM="$BASE_REF"
    CHECKOUT_ARGS=(--no-track -b "$BRANCH_NAME" "$BASE_REF")
fi
if ! git -C "$REPO_DIR" checkout --quiet "${CHECKOUT_ARGS[@]}"; then
    RECORD_PATH="$(hos_bo_record_path "$REPO_DIR" "$BRANCH_NAME" 2>/dev/null || true)"
    if [[ -n "$RECORD_PATH" ]]; then
        rm -f "$RECORD_PATH" 2>/dev/null || true
    fi
    err "'git checkout ${CHECKOUT_ARGS[*]}' failed — ownership record removed to keep the store coherent."
fi

# ── Step 6 — the branch name is the ONLY stdout line ─────────────────────────
ok "created branch '${BRANCH_NAME}' from '${CHECKOUT_FROM}', ownership recorded for cycle ${HOS_CYCLE_ID}"
_hos_mark_in_progress
echo "${BRANCH_NAME}"
