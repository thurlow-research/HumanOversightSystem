#!/usr/bin/env bash
# bootstrap/hos_setup_partner.sh — guided per-project HOS credential setup
#
# Run from the PROJECT PARENT directory (e.g. cd ~/Code/CPS), not from inside
# a clone. All paths are derived from $(pwd) — no --project-dir parameter.
#
# Usage:
#   cd ~/Code/CPS
#   bootstrap/hos_setup_partner.sh \
#     --repo-owner thurlow-research \
#     --worker-app-id 4090164 \
#     --worker-pem ~/Downloads/worker.pem \
#     --worker-bot-login 'hos-worker-hos[bot]' \
#     --overseer-app-id 4090678 \
#     --overseer-pem ~/Downloads/overseer.pem \
#     --overseer-bot-login 'hos-overseer-hos[bot]' \
#     --human-reviewer ScottThurlow \
#     [--overseer-ceiling LOW|MEDIUM|HIGH]   # default: LOW
#     [--force]                              # overwrite existing apps.env
#
# What it does:
#   1. Validates all parameters
#   2. Creates <project>/.config/hos/ (0700)
#   3. Copies PEM files with chmod 600
#   4. Writes .config/hos/apps.env from template
#   5. Verifies the written file by sourcing it
#   6. Runs validate_setup.sh on Worker/ and Overseer/ if present
#   7. Prints suggested crontab entries

set -euo pipefail

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { printf "  ${GREEN}✔${RESET}  %s\n" "$*"; }
info() { printf "  ${CYAN}→${RESET}  %s\n" "$*"; }
warn() { printf "  ${YELLOW}⚠${RESET}  %s\n" "$*" >&2; }
err()  { printf "  ${RED}✘${RESET}  %s\n" "$*" >&2; exit 1; }

# ── Must run from project parent (not inside a clone) ─────────────────────────
PROJECT_DIR="$(pwd)"
if git rev-parse --git-dir &>/dev/null 2>&1; then
  err "Run this from the project parent directory (e.g. ~/Code/CPS), not inside a git repo."
fi

# ── Resolve the HOS install dir from this script's own location (#689) ─────────
# The cron scripts live in the HOS clones (Worker/ and Overseer/), which may be
# installed in a separate directory from the partner project. Deriving their
# paths from $(pwd) is wrong whenever HOS lives elsewhere. Resolve from the
# script's location instead — correct in both colocated and separate-clone
# layouts, since this script ships inside the Worker clone.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"   # the Worker clone (holds this script)
HOS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"   # parent of Worker/ and Overseer/
OVERSEER_DIR="$HOS_DIR/Overseer"             # sibling clone (may not exist yet)

CONFIG_DIR="$PROJECT_DIR/.config/hos"

# ── Args ──────────────────────────────────────────────────────────────────────
REPO_OWNER="" WORKER_APP_ID="" WORKER_PEM="" WORKER_BOT_LOGIN=""
OVERSEER_APP_ID="" OVERSEER_PEM="" OVERSEER_BOT_LOGIN=""
HUMAN_REVIEWER="" OVERSEER_CEILING="LOW" FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-owner)         REPO_OWNER="$2";         shift 2 ;;
    --worker-app-id)      WORKER_APP_ID="$2";      shift 2 ;;
    --worker-pem)         WORKER_PEM="$2";          shift 2 ;;
    --worker-bot-login)   WORKER_BOT_LOGIN="$2";   shift 2 ;;
    --overseer-app-id)    OVERSEER_APP_ID="$2";    shift 2 ;;
    --overseer-pem)       OVERSEER_PEM="$2";        shift 2 ;;
    --overseer-bot-login) OVERSEER_BOT_LOGIN="$2"; shift 2 ;;
    --human-reviewer)     HUMAN_REVIEWER="$2";      shift 2 ;;
    --overseer-ceiling)   OVERSEER_CEILING="$2";   shift 2 ;;
    --force)              FORCE=true;               shift ;;
    --help|-h)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) err "Unknown option: $1 (try --help)" ;;
  esac
done

# ── Validate required params ───────────────────────────────────────────────────
[[ -n "$REPO_OWNER" ]]         || err "--repo-owner required"
[[ -n "$WORKER_APP_ID" ]]      || err "--worker-app-id required"
[[ -n "$WORKER_PEM" ]]         || err "--worker-pem required"
[[ -n "$WORKER_BOT_LOGIN" ]]   || err "--worker-bot-login required"
[[ -n "$OVERSEER_APP_ID" ]]    || err "--overseer-app-id required"
[[ -n "$OVERSEER_PEM" ]]       || err "--overseer-pem required"
[[ -n "$OVERSEER_BOT_LOGIN" ]] || err "--overseer-bot-login required"
[[ -n "$HUMAN_REVIEWER" ]]     || err "--human-reviewer required"

[[ "$WORKER_APP_ID" =~ ^[0-9]+$ ]]   || err "--worker-app-id must be numeric"
[[ "$OVERSEER_APP_ID" =~ ^[0-9]+$ ]] || err "--overseer-app-id must be numeric"
[[ "$OVERSEER_CEILING" =~ ^(LOW|MEDIUM|HIGH)$ ]] \
  || err "--overseer-ceiling must be LOW, MEDIUM, or HIGH"
[[ -f "$WORKER_PEM" ]]   || err "Worker PEM not found: $WORKER_PEM"
[[ -f "$OVERSEER_PEM" ]] || err "Overseer PEM not found: $OVERSEER_PEM"

# #665: validate string params for shell metacharacters before heredoc embedding.
# Newlines, quotes, or backslashes allow heredoc injection → code execution on source.
_safe_param() {
  local name="$1" val="$2"
  [[ "$val" =~ ^[a-zA-Z0-9_./@-]+(\[[a-zA-Z]+\])?$ ]] \
    || err "$name contains unsafe characters (alphanumeric, .-_/@[] only): $val"
}
_safe_param "--repo-owner"         "$REPO_OWNER"
_safe_param "--worker-bot-login"   "$WORKER_BOT_LOGIN"
_safe_param "--overseer-bot-login" "$OVERSEER_BOT_LOGIN"
_safe_param "--human-reviewer"     "$HUMAN_REVIEWER"

# ── Guard: don't overwrite without --force ────────────────────────────────────
APPS_ENV="$CONFIG_DIR/apps.env"
if [[ -f "$APPS_ENV" ]] && ! $FORCE; then
  err "$APPS_ENV already exists. Use --force to overwrite."
fi

printf "\n${BOLD}HOS partner setup — %s${RESET}\n" "$PROJECT_DIR"
printf "  Repo owner:        %s\n" "$REPO_OWNER"
printf "  Worker App ID:     %s  bot: %s\n" "$WORKER_APP_ID" "$WORKER_BOT_LOGIN"
printf "  Overseer App ID:   %s  bot: %s\n" "$OVERSEER_APP_ID" "$OVERSEER_BOT_LOGIN"
printf "  Human reviewer:    %s\n" "$HUMAN_REVIEWER"
printf "  Overseer ceiling:  %s\n\n" "$OVERSEER_CEILING"

# ── 1. Create config directory ─────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
ok "Created $CONFIG_DIR (0700)"

# ── 2. Copy PEM files ──────────────────────────────────────────────────────────
WORKER_PEM_DEST="$CONFIG_DIR/worker.pem"
OVERSEER_PEM_DEST="$CONFIG_DIR/overseer.pem"

# #666: resolve source paths to catch symlink traversal before copying
WORKER_PEM_RESOLVED=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$WORKER_PEM")   || err "Cannot resolve worker PEM path: $WORKER_PEM"
OVERSEER_PEM_RESOLVED=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$OVERSEER_PEM")   || err "Cannot resolve overseer PEM path: $OVERSEER_PEM"

cp "$WORKER_PEM_RESOLVED" "$WORKER_PEM_DEST"
chmod 600 "$WORKER_PEM_DEST"
ok "Worker PEM → $WORKER_PEM_DEST (0600)"

cp "$OVERSEER_PEM_RESOLVED" "$OVERSEER_PEM_DEST"
chmod 600 "$OVERSEER_PEM_DEST"
ok "Overseer PEM → $OVERSEER_PEM_DEST (0600)"

# ── 3. Write apps.env ─────────────────────────────────────────────────────────
# #664: umask 077 ensures file is created 0600 immediately — no TOCTOU window
(umask 077; cat > "$APPS_ENV" << EOF
# HOS GitHub App credentials — generated by hos_setup_partner.sh
# Project: $PROJECT_DIR
# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# NEVER COMMIT THIS FILE

HOS_REPO_OWNER="$REPO_OWNER"

HOS_WORKER_APP_ID="$WORKER_APP_ID"
HOS_WORKER_PEM="$WORKER_PEM_DEST"
HOS_WORKER_BOT_LOGIN="$WORKER_BOT_LOGIN"

HOS_OVERSEER_APP_ID="$OVERSEER_APP_ID"
HOS_OVERSEER_PEM="$OVERSEER_PEM_DEST"
HOS_OVERSEER_BOT_LOGIN="$OVERSEER_BOT_LOGIN"

BOT_WORKER_USERNAME="\${HOS_WORKER_BOT_LOGIN}"
BOT_OVERSEER_USERNAME="\${HOS_OVERSEER_BOT_LOGIN}"
COPILOT_BOT_LOGIN="copilot[bot]"
BOT_ACCOUNTS="\${BOT_WORKER_USERNAME} \${BOT_OVERSEER_USERNAME} \${COPILOT_BOT_LOGIN}"

OVERSEER_CEILING="$OVERSEER_CEILING"
HUMAN_REVIEWER="$HUMAN_REVIEWER"
TIER_CEILING_CHECK_NAME="require-tier-ceiling"
EOF
)  # end umask subshell — file already created with 0600
ok "Written $APPS_ENV (0600)"

# ── 4. Verify by sourcing ──────────────────────────────────────────────────────
# shellcheck source=/dev/null
source "$APPS_ENV"
[[ -n "${HOS_REPO_OWNER:-}" ]]      || err "apps.env verification failed: HOS_REPO_OWNER empty"
[[ -n "${HOS_WORKER_APP_ID:-}" ]]   || err "apps.env verification failed: HOS_WORKER_APP_ID empty"
[[ -n "${HOS_OVERSEER_APP_ID:-}" ]] || err "apps.env verification failed: HOS_OVERSEER_APP_ID empty"
ok "apps.env verified (all required vars present)"

# ── 5. Run validate_setup.sh on Worker/ and Overseer/ if present ───────────────
for role in Worker Overseer; do
  clone_dir="$PROJECT_DIR/$role"
  validate_script="$clone_dir/bootstrap/validate_setup.sh"
  if [[ -d "$clone_dir" && -f "$validate_script" ]]; then
    info "Running validate_setup.sh on $role/"
    HOS_CONFIG_DIR="$CONFIG_DIR" \
      bash "$validate_script" --repo "$clone_dir" --quiet \
      && ok "$role/ setup: PASS" \
      || warn "$role/ setup: issues found — review output above"
  else
    warn "$role/ not found at $clone_dir — skipping validation"
  fi
done

# ── 6. Print crontab entries ───────────────────────────────────────────────────
# Paths point at the HOS install (where the cron scripts actually live), not the
# partner project dir (#689). Warn if a resolved cron script is missing so the
# user can correct the path before installing the crontab entry.
[[ -x "$WORKER_DIR/bin/hos-worker-cron" ]] \
  || warn "hos-worker-cron not found at $WORKER_DIR/bin/ — adjust the crontab path below"
[[ -x "$OVERSEER_DIR/bin/hos-overseer-cron" ]] \
  || warn "hos-overseer-cron not found at $OVERSEER_DIR/bin/ — adjust the crontab path below"

printf "\n${BOLD}Suggested crontab entries (run: crontab -e)${RESET}\n"
printf "  # HOS Worker\n"
printf "  0,15,30,45 * * * *  %s/bin/hos-worker-cron >> /tmp/hos-worker.log 2>&1\n" "$WORKER_DIR"
printf "  # HOS Overseer\n"
printf "  7,22,37,52 * * * *  %s/bin/hos-overseer-cron >> /tmp/hos-overseer.log 2>&1\n\n" "$OVERSEER_DIR"

printf "${GREEN}${BOLD}Setup complete.${RESET} Apps.env written to:\n"
printf "  %s\n\n" "$APPS_ENV"
printf "Next steps:\n"
printf "  1. Add crontab entries above\n"
printf "  2. Test auth: cd %s && source <(bootstrap/get_app_token.sh --app worker)\n" "$WORKER_DIR"
printf "  3. Start interactive session: cd %s && bin/hos-worker\n\n" "$WORKER_DIR"
