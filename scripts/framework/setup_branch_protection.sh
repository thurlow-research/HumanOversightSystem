#!/usr/bin/env bash
# setup_branch_protection.sh — Apply HOS §9 branch protection rules via gh api.
#
# Implements the tiered-approval gate from AGENT-IDENTITY.md §9:
#   SAFE/LOW/MEDIUM, non-protected, non-security → overseer may approve + merge
#   Any protected surface → human approval required (CODEOWNERS + status check)
#   HIGH/CRITICAL / security-relevant → human approval required
#
# Consumer-facing: parameterised by owner/repo; works for any HOS-installed project.
# Run once after the two bot accounts are created and added as collaborators.
#
# Usage:
#   ./setup_branch_protection.sh <owner/repo>         # apply rules to main
#   ./setup_branch_protection.sh <owner/repo> --branch <name>  # different branch
#   ./setup_branch_protection.sh <owner/repo> --dry-run        # show what would be set
#   ./setup_branch_protection.sh --help
#
# Prerequisites:
#   - gh authenticated as ScottThurlow (human admin) — NOT as a bot
#   - Both bots added as collaborators (provision_agent_account.sh)
#   - CODEOWNERS already generated (gen_codeowners.sh)
#
# What this sets (§9):
#   Required PR reviews: ≥1 approving review, CODEOWNERS enforcement,
#   dismiss stale on push, NO bypass actors for bots.
#   Required status checks: a CORE set of three consumer-shipped contexts
#   (require-overseer-approval, require-human-approval, require-tier-ceiling),
#   plus any HOS-repo-only contexts listed in hos_required_contexts.txt (read
#   if present next to this script; never shipped to consumers, #1981). The
#   effective list is printed by --dry-run.
#   Enforce admins: OFF — you (admin) retain bypass ability when needed.
#   Restrictions: only bots + humans who are collaborators may push.

set -euo pipefail

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
skip() { echo -e "  ${YELLOW}–${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }
die()  { err "$*"; exit 1; }
header() { echo -e "\n${BOLD}$*${RESET}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/machine-accounts.env"
[ -f "$ENV_FILE" ] || die "machine-accounts.env not found at $ENV_FILE"
# shellcheck source=./machine-accounts.env
source "$ENV_FILE"

# ── Args ──────────────────────────────────────────────────────────────────────
REPO_SLUG=""
BRANCH="main"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) shift; BRANCH="${1:-main}"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    */*)  REPO_SLUG="$1"; shift ;;
    *) die "Unknown option: $1  (try --help)" ;;
  esac
done

[ -n "$REPO_SLUG" ] || die "<owner/repo> required  (try --help)"

OWNER="${REPO_SLUG%%/*}"
REPO="${REPO_SLUG##*/}"
API_BASE="repos/${OWNER}/${REPO}/branches/${BRANCH}/protection"

header "HOS Branch Protection Setup"
echo ""
info "Repo   : $OWNER/$REPO"
info "Branch : $BRANCH"
info "Mode   : $([ "$DRY_RUN" = true ] && echo 'DRY RUN (no changes)' || echo 'APPLY')"
echo ""

# ── HOS-only required contexts (#1981) ────────────────────────────────────────
# Read and validated BEFORE any API call so a malformed file can neither inject
# JSON into the payload nor leave a half-applied state. Absent file → nothing
# appended (the consumer case).
HOS_CONTEXTS=()
HOS_CONTEXTS_FILE="${SCRIPT_DIR}/hos_required_contexts.txt"
HOS_CONTEXTS_JSON=""
if [ -f "$HOS_CONTEXTS_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" =~ ^[A-Za-z0-9._-]+$ ]] \
      || die "Invalid context name in ${HOS_CONTEXTS_FILE}: '${line}' (must match ^[A-Za-z0-9._-]+\$)"
    HOS_CONTEXTS+=("$line")
    HOS_CONTEXTS_JSON+=", \"${line}\""
  done < "$HOS_CONTEXTS_FILE"
fi

# ── Verify caller is human (not a bot) ────────────────────────────────────────
header "Pre-flight: verify caller identity"
CALLER="$(gh api user --jq .login 2>/dev/null)" || die "gh not authenticated — run: gh auth login"
if printf '%s' "$BOT_ACCOUNTS" | grep -qw "$CALLER" 2>/dev/null; then
  die "Caller is a bot account ($CALLER). Run this as the human admin (ScottThurlow)."
fi
ok "Caller: $CALLER (human)"

# ── Verify CODEOWNERS exists ───────────────────────────────────────────────────
header "Pre-flight: CODEOWNERS"
if gh api "repos/${OWNER}/${REPO}/contents/.github/CODEOWNERS" &>/dev/null; then
  ok ".github/CODEOWNERS found"
else
  warn ".github/CODEOWNERS not found — generate with: ./scripts/framework/gen_codeowners.sh"
  warn "Proceeding anyway; CODEOWNERS enforcement will warn until the file is present."
fi

# ── Build protection payload ───────────────────────────────────────────────────
# Construct the JSON payload for PUT /repos/{o}/{r}/branches/{b}/protection.
#
# Key design decisions (AGENT-IDENTITY.md §9):
#   - required_approving_review_count: 1  (one approver needed, bot or human)
#   - require_code_owner_reviews: true    (protected paths require human CODEOWNER)
#   - dismiss_stale_reviews: true         (new commit voids prior approval)
#   - enforce_admins: false               (human admin retains bypass for emergencies)
#   - No bypass_pull_request_allowances   (bots are NOT bypass actors)
#   - Required status check: require-human-approval (the CI gate from workflows/)
#
# CODEOWNERS model (#329): require_code_owner_reviews: true ensures protected
# surfaces (scripts/framework/protected_surfaces.txt) require @ScottThurlow.
# Non-protected paths have NO CODEOWNERS entry — so any collaborator (including
# hos-overseer-hos[bot] with Maintainer role) can satisfy the code-owner
# requirement for those paths. The catch-all `* @ScottThurlow` must NEVER be
# added; it would block the overseer from merging any PR.
#
# STATUS-CHECK CONTEXTS (#737): each string in required_status_checks.contexts
# below MUST equal a workflow job `name:` — that is the string GitHub reports as
# the status-check context, NOT the workflow's top-level display name. If they
# drift, the required context never appears, stays permanently "expected", and
# every merge returns HTTP 405 even though the gates run green.
#
# Consumer-safe split (#1981): this script ships to consumers
# (framework_consumer_files.txt), so the literal array below holds ONLY the
# three contexts whose producing workflows also ship to consumers. Requiring a
# context nothing in the consumer repo produces would block every consumer PR
# forever (the #737 failure mode). Core producers:
#   require-overseer-approval ← .github/workflows/require-overseer-approval.yml
#   require-human-approval    ← .github/workflows/require-human-approval.yml
#   require-tier-ceiling      ← .github/workflows/require-tier-ceiling.yml
#
# HOS-only (hos_required_contexts.txt): contexts produced only by HOS-repo
# workflows (tests, oversight-gate-*, oversight-validator-*) live in
# scripts/framework/hos_required_contexts.txt, which is read if present and
# appended inside the array via HOS_CONTEXTS_JSON. That file is deliberately
# not shipped to consumers, so absence narrows the list to the core three. Each
# name's producer and promotion rationale is recorded next to it in that file.
# tests/framework/test_branch_protection_contexts.py enforces this invariant
# for both lists, and that every core context has a consumer-shipped producer.

PAYLOAD="$(cat <<JSON
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["require-overseer-approval", "require-human-approval", "require-tier-ceiling"${HOS_CONTEXTS_JSON}]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "require_last_push_approval": false,
    "bypass_pull_request_allowances": {
      "users": [],
      "teams": [],
      "apps": []
    }
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
)"

# ── Show what will be applied ──────────────────────────────────────────────────
header "Protection rules to apply"
echo ""
echo "  Required PR reviews:"
echo "    required_approving_review_count : 1"
echo "    require_code_owner_reviews      : true   (protected paths → human CODEOWNER)"
echo "    dismiss_stale_reviews           : true"
echo "    bypass_pull_request_allowances  : []     (bots are NOT bypass actors)"
echo ""
# Derived from the payload itself so the listing cannot drift from what is sent.
mapfile -t EFFECTIVE_CONTEXTS < <(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
print("\n".join(json.load(sys.stdin)["required_status_checks"]["contexts"]))')
CORE_COUNT=$(( ${#EFFECTIVE_CONTEXTS[@]} - ${#HOS_CONTEXTS[@]} ))
echo "  Required status checks (${#EFFECTIVE_CONTEXTS[@]}):"
for i in "${!EFFECTIVE_CONTEXTS[@]}"; do
  if [ "$i" -lt "$CORE_COUNT" ]; then
    echo "    ${EFFECTIVE_CONTEXTS[$i]}"
  else
    echo "    ${EFFECTIVE_CONTEXTS[$i]}   (from hos_required_contexts.txt)"
  fi
done
echo "  enforce_admins                    : false  (admin/human retains emergency bypass)"
echo "  allow_force_pushes                : false"
echo "  allow_deletions                   : false"
echo ""

if [ "$DRY_RUN" = true ]; then
  warn "DRY RUN — no changes made."
  echo ""
  info "To apply: re-run without --dry-run"
  exit 0
fi

# ── Apply ──────────────────────────────────────────────────────────────────────
header "Applying branch protection"
echo ""

RESPONSE="$(gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "$API_BASE" \
  --input - <<< "$PAYLOAD" 2>&1)" || {
  err "gh api call failed:"
  printf '%s\n' "$RESPONSE" | sed 's/^/  /'
  die "Branch protection update failed."
}

ok "Branch protection applied to $BRANCH on $OWNER/$REPO"

# ── Verify the key fields in the response ─────────────────────────────────────
header "Verification"
echo ""

# Re-read the live protection state.
LIVE="$(gh api "$API_BASE" 2>/dev/null)" || { warn "Could not re-read protection state for verification."; exit 0; }

_check() {
  local label="$1" query="$2" expected="$3"
  local actual
  actual="$(printf '%s' "$LIVE" | gh api --method GET /repos/"$OWNER"/"$REPO"/branches/"$BRANCH"/protection --jq "$query" 2>/dev/null || echo "?")"
  # Use gh's jq on the already-fetched response via process substitution isn't ideal;
  # pipe through python for a dependency-free jq fallback.
  actual="$(printf '%s' "$LIVE" | python3 -c "
import json,sys
data=json.load(sys.stdin)
keys='$query'.lstrip('.')
for k in keys.split('.'):
    data=data.get(k,{}) if isinstance(data,dict) else data
print(str(data).lower() if isinstance(data,bool) else data)
" 2>/dev/null || echo "?")"
  if [ "$actual" = "$expected" ]; then
    ok "$label: $actual"
  else
    warn "$label: expected '$expected', got '$actual'"
  fi
}

_check "dismiss_stale_reviews" \
  "required_pull_request_reviews.dismiss_stale_reviews" "true"
_check "require_code_owner_reviews" \
  "required_pull_request_reviews.require_code_owner_reviews" "true"
_check "required_approving_review_count" \
  "required_pull_request_reviews.required_approving_review_count" "1"
# required_conversation_resolution is a top-level field (not nested under
# required_pull_request_reviews). Verifies the SPEC-222 R2 thread-blocking gate is live —
# CONDITIONAL_PROCEED review threads only block merge when this is true.
_check "required_conversation_resolution" \
  "required_conversation_resolution" "true"

echo ""
ok "Branch protection setup complete."
echo ""
info "Next: verify with  gh api $API_BASE | jq ."
info "Then: enable 'Require status checks to pass' in the GitHub UI for any of"
info "       the contexts below that are not yet showing (each CI check must run"
info "       at least once before GitHub will enforce it):"
for ctx in "${EFFECTIVE_CONTEXTS[@]}"; do
  info "         $ctx"
done
