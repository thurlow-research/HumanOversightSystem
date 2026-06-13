#!/usr/bin/env bash
# hos_install.sh — Human Oversight System — PROJECT installer.
#
# Installs the HOS framework into a target repository FROM A VALIDATED RELEASE.
# Does NOT install machine prerequisites or need sudo — run hos_bootstrap.sh
# (in this same bootstrap/ folder) once per machine first. This script only
# fetches a release and scaffolds files; it verifies prerequisites are present
# and points you to hos_bootstrap.sh if they are not.
#
# Usage:
#   ./hos_install.sh                      # scaffold CWD from the LATEST release
#   ./hos_install.sh /path/to/project     # scaffold given dir from the latest release
#   ./hos_install.sh --release v0.3.0 DIR # scaffold a SPECIFIC release into DIR
#   ./hos_install.sh --local [DIR]        # scaffold from the local working copy
#                                         #   (dev only; unvalidated — not a release)
#   ./hos_install.sh --dry-run [DIR]      # show what would be done, no writes
#   ./hos_install.sh --force [DIR]        # overwrite existing files in target
#   ./hos_install.sh --skip-clis          # skip the agy/codex presence check
#   ./hos_install.sh --help
#
# Release vs. local source:
#   By default the framework FILES come from a fetched, validated release (latest
#   GitHub release, or --release <tag>), NOT from the local working copy — with
#   batched validation the local copy is not guaranteed shippable, so a release
#   is the reproducible, known-good artifact. Use --local only for development.
#   The installed release tag is recorded in the target at .hos-release.
#
# What it scaffolds into the target project:
#   .claude/agents/   — HOS oversight agents
#   .claude/settings.json — required permissions (merged, not overwritten)
#   scripts/          — run_panel.sh, run_second_review.sh, run_red_team.sh, etc.
#   scripts/oversight/ — validators, gates, token_tracker
#   AGENTS.md         — Layer 1 self-flagging protocol
#   contract/         — step-manifest.template.yaml
#   audit/            — committed audit trail directory
#   .ai-local/        — per-project runtime (SQC sampling salt)
#   .github/          — CODEOWNERS, PR template
#   .gitignore        — ensures .claudetmp/ present, audit/ not ignored

set -euo pipefail

# ── Resolve locations ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives in bootstrap/. The repo root (used for --local and the
# git-archive fast path) is its parent — unless run truly standalone, in which
# case release mode fetches the tarball and the repo root is never needed.
HOS_REPO_ROOT="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd || echo "$SCRIPT_DIR")"

# ── Defaults ──────────────────────────────────────────────────────────────────
TARGET_REPO="$(pwd)"
DRY_RUN=false
FORCE=false
SKIP_CLIS=false
RELEASE_REF=""        # specific release tag to install (empty = latest release)
LOCAL_SOURCE=false    # install from the local working copy instead of a release

# ── Args ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)       DRY_RUN=true; shift ;;
    --force)         FORCE=true; shift ;;
    --skip-clis)     SKIP_CLIS=true; shift ;;
    --release)       RELEASE_REF="${2:?--release needs a tag, e.g. v0.3.0}"; shift 2 ;;
    --release=*)     RELEASE_REF="${1#*=}"; shift ;;
    --local)         LOCAL_SOURCE=true; shift ;;
    --help|-h)       sed -n '2,43p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)              echo "Unknown option: $1  (try --help)"; exit 1 ;;
    *)               TARGET_REPO="$1"; shift ;;
  esac
done

TARGET_REPO="$(cd "$TARGET_REPO" 2>/dev/null && pwd)" || {
  echo "ERROR: target directory not found: $TARGET_REPO"; exit 1; }

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()      { echo -e "  ${GREEN}✔${RESET}  $*"; }
skip()    { echo -e "  ${YELLOW}–${RESET}  $*"; }
info()    { echo -e "  ${CYAN}→${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()     { echo -e "  ${RED}✘${RESET}  $*"; }
header()  { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }
dry_run() { echo -e "  ${YELLOW}[dry]${RESET} $*"; }

run() {
  if $DRY_RUN; then dry_run "$@"; else eval "$@"; fi
}

ERRORS=0
fail() { err "$*"; ERRORS=$((ERRORS + 1)); }

# ── Platform detection ────────────────────────────────────────────────────────
OS="unknown"
PKG_MGR="none"

detect_platform() {
  case "$(uname -s)" in
    Darwin)
      OS="macos"
      command -v brew &>/dev/null && PKG_MGR="brew" || PKG_MGR="none"
      ;;
    Linux)
      OS="linux"
      if command -v apt-get &>/dev/null; then
        PKG_MGR="apt"
      elif command -v dnf &>/dev/null; then
        PKG_MGR="dnf"
      elif command -v yum &>/dev/null; then
        PKG_MGR="yum"
      elif command -v pacman &>/dev/null; then
        PKG_MGR="pacman"
      fi
      ;;
  esac
}

detect_platform

# ── Resolve the framework SOURCE (a release by default, not the local copy) ────
# HOS_SOURCE is where the framework FILES are copied FROM — a fetched, validated
# release by default, so consumers install a known-good pinned version rather
# than whatever is on the local working copy (which, with batched validation, is
# not guaranteed shippable). --local uses the repo working copy (dev only).
HOS_SOURCE="$HOS_REPO_ROOT"   # overridden below unless --local
HOS_REF="(local working copy)"
CLEANUP_DIRS=()
cleanup() { for d in "${CLEANUP_DIRS[@]:-}"; do [[ -n "$d" && -d "$d" ]] && rm -rf "$d"; done; }
trap cleanup EXIT

# Resolve the HOS repo slug (owner/name) for release fetching.
HOS_REPO="${HOS_REPO:-$(git -C "$HOS_REPO_ROOT" remote get-url origin 2>/dev/null \
  | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?$#\1#' || true)}"
[[ -z "${HOS_REPO:-}" ]] && HOS_REPO="ScottThurlow/HumanOversightSystem"

fetch_release_tarball() {  # ref dest_dir -> 0 on success
  local ref="$1" dest="$2" tgz
  tgz="$(mktemp "${TMPDIR:-/tmp}/hos-src-XXXXXX.tar.gz")"
  CLEANUP_DIRS+=("$tgz")
  if command -v gh &>/dev/null; then
    gh api "repos/${HOS_REPO}/tarball/${ref}" > "$tgz" 2>/dev/null || true
  fi
  if [[ ! -s "$tgz" ]] && command -v curl &>/dev/null; then
    curl -fsSL "https://github.com/${HOS_REPO}/archive/refs/tags/${ref}.tar.gz" -o "$tgz" 2>/dev/null || true
  fi
  [[ -s "$tgz" ]] || return 1
  tar -xzf "$tgz" -C "$dest" --strip-components=1 2>/dev/null || return 1
  [[ -n "$(ls -A "$dest" 2>/dev/null)" ]]
}

resolve_hos_source() {
  if $LOCAL_SOURCE; then
    HOS_SOURCE="$HOS_REPO_ROOT"
    HOS_REF="LOCAL (unvalidated working copy)"
    warn "Installing from the LOCAL working copy — this is NOT a validated release."
    warn "Omit --local to install the latest validated release instead."
    return
  fi

  local ref="$RELEASE_REF"
  if [[ -z "$ref" ]]; then            # default: the latest GitHub release
    ref="$(gh release view --repo "$HOS_REPO" --json tagName -q .tagName 2>/dev/null || true)"
    [[ -z "$ref" ]] && ref="$(git -C "$HOS_REPO_ROOT" describe --tags --abbrev=0 2>/dev/null || true)"
  fi

  if [[ -z "$ref" ]]; then
    err "No HOS release found to install."
    echo "    No GitHub release or git tag exists yet. Either:"
    echo "      • create a release first (tag a validated commit + publish a GitHub release), or"
    echo "      • install the unvalidated working copy:  $0 --local${TARGET_REPO:+ $TARGET_REPO}"
    exit 1
  fi
  HOS_REF="$ref"

  if $DRY_RUN; then
    HOS_SOURCE="$HOS_REPO_ROOT"   # dry-run shows file ops against the local tree
    dry_run "Would fetch HOS release $ref from $HOS_REPO and install from it"
    return
  fi

  HOS_SOURCE="$(mktemp -d "${TMPDIR:-/tmp}/hos-release-XXXXXX")"
  CLEANUP_DIRS+=("$HOS_SOURCE")
  info "Fetching HOS release $ref …"

  # Prefer a local git tag export (fast, offline); fall back to the GitHub tarball.
  if git -C "$HOS_REPO_ROOT" rev-parse --git-dir &>/dev/null; then
    git -C "$HOS_REPO_ROOT" fetch --tags --quiet origin 2>/dev/null || true
    if git -C "$HOS_REPO_ROOT" rev-parse -q --verify "refs/tags/${ref}" &>/dev/null; then
      git -C "$HOS_REPO_ROOT" archive --format=tar "$ref" | tar -x -C "$HOS_SOURCE" 2>/dev/null || true
    fi
  fi
  if [[ -z "$(ls -A "$HOS_SOURCE" 2>/dev/null)" ]]; then
    fetch_release_tarball "$ref" "$HOS_SOURCE" || {
      err "Could not fetch release $ref from $HOS_REPO (no local tag, gh, or curl succeeded)."
      echo "    Check the tag exists, or install the working copy with --local."
      exit 1
    }
  fi
  ok "Release $ref staged for install"
}

resolve_hos_source

echo ""
echo -e "${BOLD}Human Oversight System — project installer${RESET}"
echo "  Platform:    $OS  ($PKG_MGR)"
echo "  HOS source:  $HOS_REF"
echo "  Target repo: $TARGET_REPO"
$DRY_RUN && echo -e "  ${YELLOW}DRY RUN — no changes will be made${RESET}"
echo ""

# ── Prerequisite check (install never installs — it points to the bootstrap) ──
# This script does not install machine prerequisites (that is hos_bootstrap.sh's
# job). It verifies they are present and stops with clear guidance if not, so
# the privilege boundary stays clean: the project install never escalates.
header "Prerequisites"
PREREQ_OK=true
check_prereq() {  # cmd  human-name  fatal(true/false)
  if command -v "$1" &>/dev/null; then ok "$2 present"; else
    if $3; then err "$2 missing"; PREREQ_OK=false; else warn "$2 missing (optional)"; fi
  fi
}
# Python 3.10+ specifically
if command -v python3 &>/dev/null && python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
  ok "python3 $(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")') present"
else
  err "python3 3.10+ missing"; PREREQ_OK=false
fi
check_prereq git "git" true
check_prereq gh  "gh CLI" true
if ! $SKIP_CLIS; then
  check_prereq agy   "agy (Gemini reviewer)"  false
  check_prereq codex "codex (OpenAI reviewer)" false
fi
if ! $PREREQ_OK; then
  echo ""
  err "Missing required prerequisites. Run the machine bootstrap first:"
  echo "      bash $(dirname "$0")/hos_bootstrap.sh"
  echo "    Then re-run this installer."
  exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
# PROJECT SETUP
# ══════════════════════════════════════════════════════════════════════════════

header "Project setup: $TARGET_REPO"

# Validate target is a git repo
if [[ ! -d "$TARGET_REPO/.git" ]]; then
  fail "$TARGET_REPO is not a git repository (no .git directory)"
  exit 1
fi

# ── Helper: copy file (skip if exists unless --force) ─────────────────────────
cp_file() {
  local src="$1" dst="$2" label="${3:-}"
  [[ -z "$label" ]] && label="$(basename "$dst")"
  if [[ ! -f "$src" ]]; then
    warn "Source not found: $src — skipping $label"
    return
  fi
  if [[ -f "$dst" ]] && ! $FORCE; then
    skip "$label (exists — use --force to overwrite)"
    return
  fi
  run "mkdir -p '$(dirname "$dst")'"
  run "cp '$src' '$dst'"
  run "chmod +x '$dst'" 2>/dev/null || true  # only works for shell scripts
  $FORCE && ok "$label (updated)" || ok "$label"
}

# ── Helper: ensure line present in file (append if missing) ───────────────────
ensure_line() {
  local file="$1" line="$2" label="${3:-$line}"
  if [[ -f "$file" ]] && grep -qF "$line" "$file" 2>/dev/null; then
    skip ".gitignore: $label already present"
  else
    run "echo '$line' >> '$file'"
    ok ".gitignore: added $label"
  fi
}

# ── Helper: ensure line NOT present (warn if it is) ───────────────────────────
ensure_not_ignored() {
  local file="$1" line="$2" label="${3:-$line}"
  # grep -v '^#' strips comment lines before searching — avoids false positives
  if [[ -f "$file" ]] && grep -v '^#' "$file" 2>/dev/null | grep -qF "$line"; then
    warn ".gitignore has '$line' — $label should be committed, not ignored"
    warn "Remove that line from $file"
  fi
}

# ── .gitignore ─────────────────────────────────────────────────────────────────
echo ""
info ".gitignore"
GITIGNORE="$TARGET_REPO/.gitignore"
[[ -f "$GITIGNORE" ]] || run "touch '$GITIGNORE'"

ensure_line     "$GITIGNORE" ".claudetmp/"   ".claudetmp/ (agent ephemeral state)"
ensure_line     "$GITIGNORE" ".ai-local/"    ".ai-local/ (SQC salt + panel cache)"
ensure_line     "$GITIGNORE" "*.salt"        "*.salt (sampling keys)"
ensure_not_ignored "$GITIGNORE" "audit/"     "audit/ (committed audit trail)"
ensure_not_ignored "$GITIGNORE" "AGENTS.md"  "AGENTS.md (governance protocol)"
ensure_not_ignored "$GITIGNORE" "prompts/"   "prompts/ (prompt artifacts)"

# ── .ai-local/ — per-PROJECT runtime (SQC sampling salt) ──────────────────────
# The salt is project state: run_redteam_sample.sh uses it to deterministically
# select which LOW/MEDIUM PRs get a red-team audit. It must persist per project
# and never be regenerated (regenerating reshuffles the sampling history).
echo ""
info ".ai-local/ — per-project runtime (SQC sampling salt)"
run "mkdir -p '$TARGET_REPO/.ai-local/panel'"
SALT_FILE="$TARGET_REPO/.ai-local/sample.salt"
if [[ -f "$SALT_FILE" ]]; then
  skip ".ai-local/sample.salt exists (do not regenerate)"
elif $DRY_RUN; then
  dry_run "Would generate $SALT_FILE"
else
  python3 -c "import secrets; print(secrets.token_hex(32))" > "$SALT_FILE"
  ok "Generated .ai-local/sample.salt (SQC random red-team sampling key)"
fi

# ── .claude/agents/ ────────────────────────────────────────────────────────────
echo ""
info ".claude/agents/ — oversight agents"
run "mkdir -p '$TARGET_REPO/.claude/agents'"

for agent in risk-assessor dep-mapper risk-historian \
             oversight-evaluator oversight-orchestrator spec-red-team; do
  src="$HOS_SOURCE/.claude/agents/${agent}.md"
  dst="$TARGET_REPO/.claude/agents/${agent}.md"
  if [[ ! -f "$src" ]]; then
    warn "Agent not found in HOS: ${agent}.md — skipping"
    continue
  fi
  # dep-mapper: don't overwrite project-specific version
  if [[ "$agent" == "dep-mapper" && -f "$dst" ]] && ! $FORCE; then
    skip "dep-mapper.md (project-specific version preserved — use --force to replace with generic)"
    continue
  fi
  cp_file "$src" "$dst" ".claude/agents/${agent}.md"
done

# ── .claude/settings.json — merge, never overwrite ────────────────────────────
echo ""
info ".claude/settings.json — merging permissions"

SETTINGS_DST="$TARGET_REPO/.claude/settings.json"
REQUIRED_ALLOWS='["Bash(gh repo:*)","Bash(gh pr:*)","Bash(gh issue:*)"]'

if [[ -f "$SETTINGS_DST" ]]; then
  if ! $DRY_RUN; then
    python3 - "$SETTINGS_DST" "$REQUIRED_ALLOWS" <<'PYEOF'
import json, sys
path = sys.argv[1]
required = json.loads(sys.argv[2])
with open(path) as f:
    cfg = json.load(f)
perms = cfg.setdefault("permissions", {})
allows = perms.setdefault("allow", [])
added = []
for a in required:
    if a not in allows:
        allows.append(a)
        added.append(a)
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
if added:
    print(f"  Added to permissions.allow: {', '.join(added)}")
else:
    print("  All required permissions already present")
PYEOF
    ok "settings.json merged"
  else
    dry_run "Would merge $REQUIRED_ALLOWS into $SETTINGS_DST"
  fi
else
  # No existing settings — create from HOS template
  SETTINGS_SRC="$HOS_SOURCE/.claude/settings.json"
  cp_file "$SETTINGS_SRC" "$SETTINGS_DST" ".claude/settings.json"
fi

# ── scripts/ — HOS runner scripts ─────────────────────────────────────────────
echo ""
info "scripts/ — HOS runner scripts"
run "mkdir -p '$TARGET_REPO/scripts'"

# Runner scripts only — NOT the installers/bootstrap. setup_clis.sh is a MACHINE
# tool (now in bootstrap/, run once per machine); setup_oversight.sh is the
# legacy project installer that hos_install.sh supersedes. Neither belongs in a
# target project's scripts/.
for script in run_panel.sh run_second_review.sh run_red_team.sh \
              review_self.sh reverify_self.sh \
              capture_prompt.sh prompt_audit.sh; do
  src="$HOS_SOURCE/scripts/$script"
  [[ ! -f "$src" ]] && src="$HOS_SOURCE/templates/$script"   # fallback to templates/
  cp_file "$src" "$TARGET_REPO/scripts/$script"
done

# ── scripts/oversight/ — validators + gates ───────────────────────────────────
echo ""
info "scripts/oversight/ — validators and gates"
if ! $DRY_RUN; then
  run "mkdir -p '$TARGET_REPO/scripts/oversight/validators' \
                '$TARGET_REPO/scripts/oversight/gates'"
  rsync -a ${FORCE:+--ignore-times} ${FORCE:+--checksum} \
    $( $FORCE || echo "--ignore-existing" ) \
    "$HOS_SOURCE/scripts/oversight/" \
    "$TARGET_REPO/scripts/oversight/" 2>/dev/null || \
  cp -rn "$HOS_SOURCE/scripts/oversight/." "$TARGET_REPO/scripts/oversight/"
  ok "scripts/oversight/ synced"
else
  dry_run "Would sync $HOS_SOURCE/scripts/oversight/ → $TARGET_REPO/scripts/oversight/"
fi

# ── AGENTS.md — Layer 1 protocol ──────────────────────────────────────────────
echo ""
info "Core governance documents"
cp_file "$HOS_SOURCE/AGENTS.md"     "$TARGET_REPO/AGENTS.md"
cp_file "$HOS_SOURCE/METHODOLOGY.md" "$TARGET_REPO/METHODOLOGY.md" \
  2>/dev/null || true  # optional

# ── contract/ — step manifest template ────────────────────────────────────────
run "mkdir -p '$TARGET_REPO/contract'"
if [[ ! -f "$TARGET_REPO/contract/step-manifest.yaml" ]]; then
  cp_file "$HOS_SOURCE/contract/step-manifest.template.yaml" \
          "$TARGET_REPO/contract/step-manifest.yaml" \
          "contract/step-manifest.yaml"
  warn "Edit $TARGET_REPO/contract/step-manifest.yaml to define your build steps"
else
  skip "contract/step-manifest.yaml (exists — not overwritten)"
fi

# ── audit/ — committed audit trail ────────────────────────────────────────────
echo ""
info "audit/ — committed audit trail"
if [[ ! -d "$TARGET_REPO/audit" ]]; then
  run "mkdir -p '$TARGET_REPO/audit/escalations' '$TARGET_REPO/audit/panel-runs'"
  if ! $DRY_RUN; then
    cat > "$TARGET_REPO/audit/oversight-log.jsonl" <<'JSONL'
# oversight-log.jsonl — Human Oversight System audit trail
# Append-only. One JSON event per line. Do not edit or delete existing lines.
# Schema: OVERSIGHT-CONTRACT.md §1 (HumanOversightSystem repo)
# Human-readable summaries: audit/YYYY-MM-DD-step-{N}-{name}-{TIER}.md
JSONL
    touch "$TARGET_REPO/audit/escalations/.gitkeep"
    touch "$TARGET_REPO/audit/panel-runs/.gitkeep"
    # Copy README template
    [[ -f "$HOS_SOURCE/audit/README.md" ]] && \
      cp "$HOS_SOURCE/audit/README.md" "$TARGET_REPO/audit/README.md" || true
  fi
  ok "audit/ scaffolded (committed, not gitignored)"
else
  skip "audit/ already exists"
fi

# Verify audit/ is not accidentally gitignored
if grep -qF "audit/" "$GITIGNORE" 2>/dev/null; then
  warn "audit/ is in .gitignore — the audit trail won't be committed!"
  warn "Remove that line from $TARGET_REPO/.gitignore"
fi

# ── .github/ — CODEOWNERS + PR template ───────────────────────────────────────
echo ""
info ".github/ — code owners and PR template"
run "mkdir -p '$TARGET_REPO/.github'"
cp_file "$HOS_SOURCE/.github/CODEOWNERS"              "$TARGET_REPO/.github/CODEOWNERS"
cp_file "$HOS_SOURCE/.github/pull_request_template.md" "$TARGET_REPO/.github/pull_request_template.md"

# ── prompts/ — prompt artifact directory ──────────────────────────────────────
echo ""
info "prompts/ — prompt artifact directory"
if [[ ! -d "$TARGET_REPO/prompts" ]]; then
  run "mkdir -p '$TARGET_REPO/prompts'"
  if ! $DRY_RUN; then
    cat > "$TARGET_REPO/prompts/README.md" <<'PROMPTS'
# prompts/

Prompt artifacts for AI-generated code at MEDIUM risk or above.
Mirrors the `src/` directory structure. Named to shadow the file they produced.

Example:
  src/auth/middleware.py       ← generated file
  prompts/auth/middleware.md   ← prompt artifact for middleware.py

See AGENTS.md §Prompts-as-Artifact Discipline for the full convention.
PROMPTS
  fi
  ok "prompts/ created"
else
  skip "prompts/ already exists"
fi

# ── .hos-release — record the installed framework version ─────────────────────
echo ""
info ".hos-release — installed framework version marker"
if $DRY_RUN; then
  dry_run "Would write $TARGET_REPO/.hos-release ($HOS_REF)"
else
  printf "%s\n" "$HOS_REF" > "$TARGET_REPO/.hos-release"
  ok ".hos-release = $HOS_REF"
fi


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

header "Done"

if [[ $ERRORS -gt 0 ]]; then
  err "$ERRORS error(s) — address the above before using HOS"
  exit 1
fi

echo ""
  ok "HOS framework installed in: $TARGET_REPO"
  echo ""
  echo -e "  ${BOLD}Next steps:${RESET}"
  echo ""
  echo "  1. Fill in the step manifest:"
  echo "       $TARGET_REPO/contract/step-manifest.yaml"
  echo ""
  echo "  2. Authenticate AI CLIs (if not done):"
  echo "       (machine bootstrap) bash bootstrap/setup_clis.sh auth"
  echo ""
  echo "  3. Commit the scaffolded files:"
  echo "       cd $TARGET_REPO && git add .claude/ AGENTS.md audit/ contract/ scripts/ .gitignore"
  echo "       git commit -m 'Bootstrap Human Oversight System'"
  echo ""
  echo "  4. Run the pipeline:"
  echo "       Inner loop:  bash scripts/oversight/run_validators.sh [files...]"
  echo "       Transition:  bash scripts/run_second_review.sh --step N --score 0.6"
  echo "       Outer loop:  bash scripts/run_panel.sh [PR#]"
  echo "       Checkpoint:  bash scripts/run_red_team.sh --milestone auth"
  echo ""
  echo "  5. Review the audit trail:"
  echo "       cat audit/oversight-log.jsonl | jq 'select(.event==\"sign-off\")'"
  echo ""

echo "  Docs: CLAUDE.md · ARCHITECTURE.md · contract/OVERSIGHT-CONTRACT.md"
echo ""
