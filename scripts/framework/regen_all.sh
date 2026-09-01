#!/usr/bin/env bash
# regen_all.sh — single canonical entry point for the self-heal-safe generated
# artifacts (SCRIPTS-INDEX.md, .github/CODEOWNERS). Both are pure functions of
# other committed input with no human judgment required to regenerate, unlike
# scripts/framework/validation-stamps/*.stamp (written only after real review —
# deliberately NOT wired in here; auto-regenerating it would defeat the gate).
#
# Default mode regenerates the real committed files in place (best-effort —
# a forgotten regeneration should self-heal, not halt the worker; #1414, #1413).
# --check mode regenerates into isolated temp locations and reports staleness
# without touching the working tree, for use as a freshness gate.
#
# Usage:
#   ./scripts/framework/regen_all.sh            # self-heal: regenerate in place
#   ./scripts/framework/regen_all.sh --check     # report staleness, exit 1 if stale
#   ./scripts/framework/regen_all.sh --help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

CYAN="\033[36m"
RED="\033[31m"; GREEN="\033[32m"; BOLD="\033[1m"; RESET="\033[0m"

case "${1:-}" in
  --help|-h)
    echo "Usage: $0 [--check]"
    echo ""
    echo "Regenerates (default) or checks (--check) the self-heal-safe generated"
    echo "artifacts: SCRIPTS-INDEX.md and .github/CODEOWNERS."
    echo ""
    echo "Default mode writes the real committed files and reports what changed."
    echo "--check mode never touches the working tree; exits 1 if anything is stale."
    exit 0
    ;;
esac

MODE="self-heal"
[[ "${1:-}" == "--check" ]] && MODE="check"

GEN_INDEX="$SCRIPT_DIR/gen_scripts_index.sh"
GEN_CODEOWNERS="$SCRIPT_DIR/gen_codeowners.sh"
SURFACES="$SCRIPT_DIR/protected_surfaces.txt"
INDEX_OUT="SCRIPTS-INDEX.md"
CODEOWNERS_OUT=".github/CODEOWNERS"

[[ -f "$GEN_INDEX" ]] || { echo "missing $GEN_INDEX" >&2; exit 2; }
[[ -f "$GEN_CODEOWNERS" ]] || { echo "missing $GEN_CODEOWNERS" >&2; exit 2; }
[[ -f "$SURFACES" ]] || { echo "missing $SURFACES" >&2; exit 2; }
[[ -f "$CODEOWNERS_OUT" ]] || { echo "missing committed $CODEOWNERS_OUT — cannot extract owner" >&2; exit 2; }

# Owner comes from the committed file, never `gh` — a network dependency has no
# place in a self-heal path invoked at cycle-start, and silently changing the
# owner would be a human policy decision this script has no authority to make.
OWNER="$(python3 -c '
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"^# Owner: (@\S+)$", text, flags=re.MULTILINE)
if not m:
    sys.exit(1)
print(m.group(1))
' "$CODEOWNERS_OUT")" || { echo "committed $CODEOWNERS_OUT has no '# Owner: @X' line to regenerate against" >&2; exit 2; }

if [[ "$MODE" == "self-heal" ]]; then
  echo -e "${BOLD}Regenerating self-heal-safe artifacts${RESET}"
  echo ""

  bash "$GEN_INDEX" "$INDEX_OUT" >/dev/null
  bash "$GEN_CODEOWNERS" "$OWNER" >/dev/null

  CHANGED=0
  if git diff --quiet -- "$INDEX_OUT"; then
    echo -e "  ${CYAN}→${RESET}  $INDEX_OUT is current"
  else
    echo -e "  ${CYAN}→${RESET}  $INDEX_OUT regenerated — now differs from the committed copy; review and commit the change"
    CHANGED=$((CHANGED + 1))
  fi
  if git diff --quiet -- "$CODEOWNERS_OUT"; then
    echo -e "  ${CYAN}→${RESET}  $CODEOWNERS_OUT is current"
  else
    echo -e "  ${CYAN}→${RESET}  $CODEOWNERS_OUT regenerated — now differs from the committed copy; review and commit the change"
    CHANGED=$((CHANGED + 1))
  fi

  echo ""
  if [[ "$CHANGED" -gt 0 ]]; then
    echo -e "  ${BOLD}⚠  $CHANGED generated artifact(s) regenerated — run 'git diff' and commit before opening a PR.${RESET}"
  else
    echo -e "  ${GREEN}✔${RESET}  no drift — nothing to commit"
  fi
  exit 0
fi

# ── --check mode: isolated regeneration, no working-tree mutation ────────────
TMP_CHECK="$(mktemp -d)"
trap 'rm -rf "$TMP_CHECK"' EXIT

STALE=0

INDEX_TMP="$TMP_CHECK/SCRIPTS-INDEX.md"
bash "$GEN_INDEX" "$INDEX_TMP" >/dev/null
if ! diff -q "$INDEX_TMP" "$INDEX_OUT" >/dev/null 2>&1; then
  echo -e "  ${RED}✘${RESET}  $INDEX_OUT is stale relative to scripts/, bootstrap/, bin/ —"
  echo "     regenerate with: scripts/framework/gen_scripts_index.sh"
  STALE=$((STALE + 1))
fi

CODEOWNERS_TMP_ROOT="$TMP_CHECK/codeowners"
FW_DIR="$CODEOWNERS_TMP_ROOT/scripts/framework"
mkdir -p "$FW_DIR" "$CODEOWNERS_TMP_ROOT/.github"
cp "$GEN_CODEOWNERS" "$FW_DIR/gen_codeowners.sh"
cp "$SURFACES" "$FW_DIR/protected_surfaces.txt"
bash "$FW_DIR/gen_codeowners.sh" "$OWNER" >/dev/null
if ! diff -q "$CODEOWNERS_TMP_ROOT/.github/CODEOWNERS" "$CODEOWNERS_OUT" >/dev/null 2>&1; then
  echo -e "  ${RED}✘${RESET}  $CODEOWNERS_OUT is stale relative to protected_surfaces.txt —"
  echo "     regenerate with: scripts/framework/gen_codeowners.sh $OWNER"
  STALE=$((STALE + 1))
fi

echo ""
if [[ "$STALE" -gt 0 ]]; then
  echo -e "  ${RED}✘${RESET}  $STALE generated artifact(s) are stale."
  exit 1
fi
echo -e "  ${GREEN}✔${RESET}  All generated artifacts are current."
exit 0
