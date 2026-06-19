#!/usr/bin/env bash
# bootstrap/get_app_token.sh — generate a GitHub App installation token for HOS bot identities
#
# Usage (source into current shell so GH_TOKEN + HOS_BOT_LOGIN are exported):
#   source <(./bootstrap/get_app_token.sh --app worker)
#   source <(./bootstrap/get_app_token.sh --app overseer)
#
# After sourcing, `gh api` calls in the same shell use the App installation token.
# HOS_BOT_LOGIN is set to the App's bot identity (e.g. "hos-worker-hos[bot]") so
# identity guards don't need a `gh api user` call (which fails for App tokens).
#
# Token lifetime: 1 hour. Re-source before long sessions.
#
# Reads: ~/.config/hos/apps.env  (App IDs, PEM paths — never committed to git)
# Requires: openssl, curl, python3 (all present on macOS by default)

set -euo pipefail

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*" >&2; }
info() { echo -e "  ${CYAN}→${RESET}  $*" >&2; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }

# ── Args ──────────────────────────────────────────────────────────────────────
APP_ROLE=""
APPS_ENV="${HOME}/.config/hos/apps.env"

while [[ $# -gt 0 ]]; do
    case $1 in
        --app) APP_ROLE="$2"; shift 2 ;;
        *)     echo "Usage: $0 --app [worker|overseer]" >&2; exit 1 ;;
    esac
done

[[ -n "$APP_ROLE" ]] || err "--app required (worker or overseer)"
[[ -f "$APPS_ENV" ]] || err "~/.config/hos/apps.env not found — run hos_bootstrap.sh first"

# shellcheck source=/dev/null
source "$APPS_ENV"

case "$APP_ROLE" in
    worker)
        APP_ID="$HOS_WORKER_APP_ID"
        PEM_PATH="$HOS_WORKER_PEM"
        BOT_LOGIN="$HOS_WORKER_BOT_LOGIN"
        ;;
    overseer)
        APP_ID="$HOS_OVERSEER_APP_ID"
        PEM_PATH="$HOS_OVERSEER_PEM"
        BOT_LOGIN="$HOS_OVERSEER_BOT_LOGIN"
        ;;
    *)  err "--app must be 'worker' or 'overseer'" ;;
esac

[[ -f "$PEM_PATH" ]] || err "PEM not found: $PEM_PATH"

# ── JWT generation (RS256 via openssl — no Python crypto dep) ─────────────────
generate_jwt() {
    local app_id="$1" pem_path="$2"
    local now; now=$(date +%s)
    local header payload signing_input signature

    header=$(printf '{"alg":"RS256","typ":"JWT"}' \
        | openssl base64 -A | tr '+/' '-_' | tr -d '=')
    payload=$(printf '{"iat":%d,"exp":%d,"iss":%d}' \
        $((now - 60)) $((now + 600)) "$app_id" \
        | openssl base64 -A | tr '+/' '-_' | tr -d '=')

    signing_input="${header}.${payload}"
    signature=$(printf '%s' "$signing_input" \
        | openssl dgst -sha256 -sign "$pem_path" \
        | openssl base64 -A | tr '+/' '-_' | tr -d '=')

    printf '%s.%s' "$signing_input" "$signature"
}

info "Generating JWT for ${APP_ROLE} (app_id: ${APP_ID})..."
JWT=$(generate_jwt "$APP_ID" "$PEM_PATH")

# ── Get installation ID for HOS_REPO_OWNER ────────────────────────────────────
info "Looking up installation for ${HOS_REPO_OWNER}..."
INSTALL_RESPONSE=$(curl -sf \
    -H "Authorization: Bearer ${JWT}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/app/installations") \
    || err "Failed to reach /app/installations — check App ID and PEM"

INSTALL_ID=$(python3 - <<EOF
import json, sys
installs = json.loads("""${INSTALL_RESPONSE}""")
for i in installs:
    if i.get("account", {}).get("login") == "${HOS_REPO_OWNER}":
        print(i["id"])
        sys.exit(0)
print("")
EOF
)

[[ -n "$INSTALL_ID" ]] || err "No installation found for ${HOS_REPO_OWNER} — install the App on the repo at github.com/settings/apps"

# ── Get installation token ────────────────────────────────────────────────────
info "Fetching installation token (installation: ${INSTALL_ID})..."
TOKEN_RESPONSE=$(curl -sf -X POST \
    -H "Authorization: Bearer ${JWT}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/app/installations/${INSTALL_ID}/access_tokens") \
    || err "Failed to get installation token"

TOKEN=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['token'])" <<< "$TOKEN_RESPONSE")
EXPIRES=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('expires_at','unknown'))" <<< "$TOKEN_RESPONSE")

[[ -n "$TOKEN" ]] || err "Empty token in response"

ok "${APP_ROLE} token obtained (expires: ${EXPIRES})"

# ── Output (sourced into caller's shell) ──────────────────────────────────────
printf 'export GH_TOKEN=%s\n'      "$TOKEN"
printf 'export HOS_BOT_LOGIN=%s\n' "$BOT_LOGIN"
