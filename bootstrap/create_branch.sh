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
# --from <ref> (default: current HEAD) lets a cycle create ITS OWN branch at
# the tip of a prior, unsubmitted (and therefore foreign — AD-1) branch,
# adopting its commits under new, cycle-owned authority. Adopting commits is
# NOT adopting their review status: whoever adopts via --from MUST re-run the
# full review chain in this cycle before any PR is opened — see
# .claude/agents/worker.md.
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
if [[ -z "${HOS_CYCLE_ID:-}" || -z "${HOS_CYCLE_TOKEN:-}" || "${HOS_CYCLE_ROLE:-}" != "worker" ]]; then
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

# ── Step 3 — idempotent re-entry within this cycle, or refuse (never adopt) ──
if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
    if hos_bo_verify "$REPO_DIR" "$BRANCH_NAME"; then
        git -C "$REPO_DIR" checkout --quiet "$BRANCH_NAME" \
            || err "Branch '${BRANCH_NAME}' has a valid ownership record for this cycle, but 'git checkout' failed."
        ok "re-entered existing branch '${BRANCH_NAME}' (already owned by this cycle)"
        echo "${BRANCH_NAME}"
        exit 0
    fi
    err "Branch '${BRANCH_NAME}' already exists locally but its ownership record is not valid for this cycle (reason: ${HOS_BO_REASON:-unknown}). This script never adopts an existing branch (#967, ADR-037 AD-3) — the branch name is cycle-unique, so this indicates a name collision outside the ownership model; investigate before retrying."
fi

# ── Step 4 — write the ownership record BEFORE creating the branch ──────────
# Record-first, not branch-first: a record with no branch is inert (nothing
# can be pushed); a branch with no record is a confusing fail-closed refusal
# later. §5.2.
if ! hos_bo_write_record "$REPO_DIR" "$BRANCH_NAME"; then
    err "Could not write branch-ownership record for '${BRANCH_NAME}' (reason: ${HOS_BO_REASON:-unknown})."
fi

# ── Step 5 — create the branch; roll back the record on failure ─────────────
CHECKOUT_FROM="${FROM_REF:-HEAD}"
if ! git -C "$REPO_DIR" checkout --quiet -b "$BRANCH_NAME" "$CHECKOUT_FROM"; then
    RECORD_PATH="$(hos_bo_record_path "$REPO_DIR" "$BRANCH_NAME" 2>/dev/null || true)"
    if [[ -n "$RECORD_PATH" ]]; then
        rm -f "$RECORD_PATH" 2>/dev/null || true
    fi
    err "'git checkout -b ${BRANCH_NAME} ${CHECKOUT_FROM}' failed — ownership record removed to keep the store coherent."
fi

# ── Step 6 — the branch name is the ONLY stdout line ─────────────────────────
ok "created branch '${BRANCH_NAME}' from '${CHECKOUT_FROM}', ownership recorded for cycle ${HOS_CYCLE_ID}"
echo "${BRANCH_NAME}"
