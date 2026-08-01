#!/usr/bin/env bash
# bootstrap/sync_apps_env.sh — fill gaps in an EXISTING .config/hos/apps.env
#
# hos_setup_partner.sh does the one-time INITIAL write of apps.env. This
# script is for every release AFTER that: a `hos_install.sh --pr` upgrade can
# introduce new apps.env keys that no existing role checkout's local,
# gitignored apps.env carries. The upgrade PR merges cleanly through git —
# `--pr` has no way to carry gitignored local config — so the gap stays
# silent until something deep in get_app_token.sh crashes on an unbound
# variable with no diagnostic (a 3am crash-loop, not a clear error).
#
# What it does:
#   1. Reads the canonical key list from bootstrap/apps.env.template — this
#      release's full set of expected apps.env keys.
#   2. Any key ALREADY present in the target apps.env is left alone,
#      untouched, always. This script only ever appends; it never edits or
#      removes an existing line.
#   3. For each key the target is MISSING:
#        - if the template's value is a real usable default (no "<...>"
#          placeholder) — e.g. OVERSEER_CEILING="LOW", or a computed
#          reference like BOT_WORKER_USERNAME="${HOS_WORKER_BOT_LOGIN}" —
#          it is appended verbatim, no prompt.
#        - if the template's value is a "<PLACEHOLDER>" — prompts for a real
#          value (or takes it from an identically-named env var under
#          --non-interactive), and appends it. A value left blank is written
#          as the literal placeholder, so the file stays obviously unresolved
#          rather than silently blank.
#
# Usage:
#   bash bootstrap/sync_apps_env.sh                       # interactive
#   bash bootstrap/sync_apps_env.sh --non-interactive      # env-var overrides only
#   bash bootstrap/sync_apps_env.sh --config-dir /path/to/.config/hos
#   bash bootstrap/sync_apps_env.sh --dry-run
#
# Run this once after any `hos_install.sh --pr` upgrade merges to main, on
# every role checkout that points at the target apps.env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/apps.env.template"

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { printf "  ${GREEN}✔${RESET}  %s\n" "$*"; }
info() { printf "  ${CYAN}→${RESET}  %s\n" "$*"; }
warn() { printf "  ${YELLOW}⚠${RESET}  %s\n" "$*" >&2; }
err()  { printf "  ${RED}✘${RESET}  %s\n" "$*" >&2; exit 1; }

CONFIG_DIR="${HOS_CONFIG_DIR:-${HOME}/.config/hos}"
NON_INTERACTIVE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir)       CONFIG_DIR="$2";      shift 2 ;;
    --non-interactive)  NON_INTERACTIVE=true; shift ;;
    --dry-run)          DRY_RUN=true;         shift ;;
    --help|-h)
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
      exit 0 ;;
    *) err "Unknown option: $1 (try --help)" ;;
  esac
done

[[ -f "$TEMPLATE" ]] || err "Template not found: $TEMPLATE"

APPS_ENV="$CONFIG_DIR/apps.env"
[[ -f "$APPS_ENV" ]] \
  || err "$APPS_ENV not found — run hos_setup_partner.sh first (this script only fills gaps in an existing file)."

# ── verify permissions before reading/writing (mirrors get_app_token.sh #633/#645) ──
_env_mode=$(stat -c "%a" "$APPS_ENV" 2>/dev/null || stat -f "%OLp" "$APPS_ENV" 2>/dev/null) \
  || err "Cannot verify apps.env permissions — stat unavailable. Manually confirm: chmod 600 $APPS_ENV"
if [[ "$_env_mode" != "600" && "$_env_mode" != "400" ]]; then
  err "apps.env has permissions $_env_mode (expected 600). Run: chmod 600 $APPS_ENV"
fi

# Reject shell metacharacters before writing a user-supplied value into a file
# that is later `source`d — newlines/quotes/backslashes would allow injection
# on the next source. Mirrors hos_setup_partner.sh's _safe_param (#665).
_safe_value() {
  [[ "$1" =~ ^[a-zA-Z0-9_./@-]+(\[[a-zA-Z]+\])?$ ]]
}

printf "\n${BOLD}HOS apps.env gap-fill — %s${RESET}\n" "$APPS_ENV"
$DRY_RUN && printf "  ${YELLOW}DRY RUN — no changes will be written${RESET}\n"
echo ""

# Read the template into an array (not piped into the loop) so an interactive
# `read -r -p` prompt below reads from the real stdin, not from the template.
mapfile -t TEMPLATE_LINES < "$TEMPLATE"

ADDITIONS=()
SUMMARY=()

for line in "${TEMPLATE_LINES[@]}"; do
  [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=\"(.*)\"$ ]] || continue
  key="${BASH_REMATCH[1]}"
  template_value="${BASH_REMATCH[2]}"

  grep -qE "^${key}=" "$APPS_ENV" && continue   # already declared — never touch it

  if [[ "$template_value" == *"<"* ]]; then
    value=""
    if $NON_INTERACTIVE; then
      value="${!key:-}"
    else
      printf "  %s is new in this release (template default: %s)\n" "$key" "$template_value"
      read -r -p "  Value (Enter to leave unresolved): " value
    fi
    if [[ -z "$value" ]]; then
      warn "$key left unresolved — using placeholder; edit $APPS_ENV before the next run that needs it"
      value="$template_value"
    elif ! _safe_value "$value"; then
      err "$key: unsafe characters in supplied value (alphanumeric, .-_/@[] only)"
    fi
  else
    # A real default or a computed ${VAR} reference — safe to carry verbatim.
    value="$template_value"
  fi

  ADDITIONS+=("$(printf '%s="%s"' "$key" "$value")")
  SUMMARY+=("$key")
done

echo ""
if [[ ${#ADDITIONS[@]} -eq 0 ]]; then
  ok "apps.env already has every key this release's template defines — nothing to do."
elif $DRY_RUN; then
  for a in "${ADDITIONS[@]}"; do info "would add: $a"; done
  ok "${#ADDITIONS[@]} key(s) would be added to $APPS_ENV"
else
  {
    printf '\n# ── Added by sync_apps_env.sh on %s ──\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '%s\n' "${ADDITIONS[@]}"
  } >> "$APPS_ENV"
  chmod 600 "$APPS_ENV"
  for k in "${SUMMARY[@]}"; do ok "added: $k"; done
  ok "${#ADDITIONS[@]} key(s) added to $APPS_ENV"
fi
