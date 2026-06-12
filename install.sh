#!/usr/bin/env bash
# install.sh — Human Oversight System — unified installer
#
# Installs all prerequisites and scaffolds the HOS framework into a target
# repository. Detects macOS vs Linux and uses the right package manager.
# Safe to re-run — idempotent throughout.
#
# Usage:
#   ./install.sh                      # prereqs + scaffold current directory
#   ./install.sh /path/to/project     # prereqs + scaffold given directory
#   ./install.sh --machine-only       # prereqs only (Python, gh, pip packages)
#   ./install.sh --project-only [DIR] # scaffold only, skip machine prereqs
#   ./install.sh --dry-run [DIR]      # show what would be done, no writes
#   ./install.sh --force [DIR]        # overwrite existing files in target
#   ./install.sh --skip-clis          # skip agy/codex auth checks
#   ./install.sh --no-sudo            # skip steps that require sudo
#   ./install.sh --help
#
# What it installs on the machine:
#   Python 3.10+, pip, gh CLI, Python analysis packages (radon, bandit, etc.)
#   Then guides you through agy + codex setup (requires ./scripts/setup_clis.sh)
#
# What it scaffolds into the target project:
#   .claude/agents/   — 6 HOS oversight agents
#   .claude/settings.json — required permissions (merged, not overwritten)
#   scripts/          — run_panel.sh, run_second_review.sh, run_red_team.sh, etc.
#   scripts/oversight/ — validators, gates, token_tracker
#   AGENTS.md         — Layer 1 self-flagging protocol
#   contract/         — step-manifest.template.yaml
#   audit/            — committed audit trail directory
#   .github/          — CODEOWNERS, PR template
#   .gitignore        — ensures .claudetmp/ present, audit/ not ignored

set -euo pipefail

# ── Resolve HOS root from script location ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOS_ROOT="$SCRIPT_DIR"   # install.sh lives at the repo root

# ── Defaults ──────────────────────────────────────────────────────────────────
TARGET_REPO="$(pwd)"
MACHINE_ONLY=false
PROJECT_ONLY=false
DRY_RUN=false
FORCE=false
SKIP_CLIS=false
NO_SUDO=false

# ── Args ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --machine-only)  MACHINE_ONLY=true; shift ;;
    --project-only)  PROJECT_ONLY=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    --force)         FORCE=true; shift ;;
    --skip-clis)     SKIP_CLIS=true; shift ;;
    --no-sudo)       NO_SUDO=true; shift ;;
    --help|-h)       sed -n '2,35p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
SUDO=""

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
  if ! $NO_SUDO && command -v sudo &>/dev/null; then
    SUDO="sudo"
  fi
}

detect_platform
echo ""
echo -e "${BOLD}Human Oversight System — installer${RESET}"
echo "  Platform:    $OS  ($PKG_MGR)"
echo "  HOS root:    $HOS_ROOT"
echo "  Target repo: $TARGET_REPO"
$DRY_RUN && echo -e "  ${YELLOW}DRY RUN — no changes will be made${RESET}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# MACHINE SETUP
# ══════════════════════════════════════════════════════════════════════════════

if ! $PROJECT_ONLY; then

header "1. Python 3.10+"

install_python() {
  local min_minor=10

  # Check if a suitable python3 is already present
  if command -v python3 &>/dev/null; then
    local ver major minor
    ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [[ "$major" -ge 3 && "$minor" -ge "$min_minor" ]]; then
      ok "python3 $ver"
      return
    fi
    warn "python3 $ver found but need 3.${min_minor}+ — upgrading"
  fi

  case "$OS-$PKG_MGR" in
    macos-brew)
      info "Installing Python 3.12 via brew..."
      run "brew install python@3.12"
      # brew python may not be on PATH immediately
      run "brew link --force python@3.12 2>/dev/null || true"
      ;;
    linux-apt)
      info "Installing Python 3 via apt..."
      run "$SUDO apt-get update -qq"
      run "$SUDO apt-get install -y python3 python3-pip python3-venv python3-dev"
      ;;
    linux-dnf)
      info "Installing Python 3 via dnf..."
      run "$SUDO dnf install -y python3 python3-pip python3-devel"
      ;;
    linux-yum)
      info "Installing Python 3 via yum..."
      run "$SUDO yum install -y python3 python3-pip"
      ;;
    linux-pacman)
      info "Installing Python 3 via pacman..."
      run "$SUDO pacman -Sy --noconfirm python python-pip"
      ;;
    macos-none)
      fail "brew not found. Install Homebrew first: https://brew.sh"
      fail "Then re-run this script."
      ;;
    *)
      fail "No supported package manager detected (brew/apt/dnf/yum/pacman)."
      fail "Install Python 3.10+ manually, then re-run with --project-only."
      ;;
  esac

  if command -v python3 &>/dev/null; then
    ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"
  else
    fail "python3 not found after install attempt"
  fi
}

install_python

# ── pip ───────────────────────────────────────────────────────────────────────
if python3 -m pip --version &>/dev/null 2>&1; then
  ok "pip $(python3 -m pip --version | awk '{print $2}')"
else
  warn "pip not found — attempting to install..."
  case "$OS-$PKG_MGR" in
    linux-apt) run "$SUDO apt-get install -y python3-pip" ;;
    linux-dnf) run "$SUDO dnf install -y python3-pip" ;;
    linux-yum) run "$SUDO yum install -y python3-pip" ;;
    *) run "python3 -m ensurepip --upgrade" ;;
  esac
fi

header "2. Python analysis packages"

REQUIREMENTS="$HOS_ROOT/scripts/oversight/requirements.txt"
if [[ -f "$REQUIREMENTS" ]]; then
  info "Installing from requirements.txt..."
  # Use --user to avoid permission issues outside a venv
  if ! $DRY_RUN; then
    python3 -m pip install --quiet --upgrade pip 2>/dev/null || true
    python3 -m pip install --quiet -r "$REQUIREMENTS" 2>/dev/null || \
      python3 -m pip install --quiet --user -r "$REQUIREMENTS" 2>/dev/null || \
      warn "Some packages failed to install — try manually: pip install -r $REQUIREMENTS"
  fi
  for pkg in radon bandit flake8 black isort mypy; do
    if python3 -c "import $pkg" &>/dev/null 2>&1 || python3 -m "$pkg" --version &>/dev/null 2>&1; then
      ok "$pkg"
    else
      warn "$pkg not importable after install (may still work via CLI)"
    fi
  done
  for tool in radon bandit flake8 black isort mypy; do
    command -v "$tool" &>/dev/null && ok "$tool (CLI)" || true
  done
else
  warn "requirements.txt not found at $REQUIREMENTS — skipping"
fi

# Optional tools
for opt_pkg in semgrep detect-secrets; do
  if command -v "$opt_pkg" &>/dev/null; then
    ok "$opt_pkg (optional)"
  else
    skip "$opt_pkg not installed (optional — install: pip install $opt_pkg)"
  fi
done

header "2a. IP tooling — ScanCode Toolkit"
# ScanCode provides full license-text detection (Level 1 IP agent).
# Without it, ip_check.py falls back to PyPI/npm API lookups (less thorough).
# ai-gen-code-search (Level 3 regurgitation lens) is listed separately below —
# it requires building a FOSS code index and is not auto-installed.
#
# ScanCode may need system libraries (libmagic) on some platforms.

install_scancode() {
  if command -v scancode &>/dev/null; then
    ok "scancode $(scancode --version 2>/dev/null | head -1 | tr -d '\n')"
    return
  fi

  info "Installing ScanCode Toolkit (IP/license detection)..."

  # Install system dependencies that ScanCode may need
  case "$OS-$PKG_MGR" in
    linux-apt)
      info "Installing libmagic (ScanCode system dependency)..."
      run "$SUDO apt-get install -y libmagic-dev libmagic1 2>/dev/null || true"
      ;;
    linux-dnf)
      run "$SUDO dnf install -y file-libs file-devel 2>/dev/null || true"
      ;;
    linux-yum)
      run "$SUDO yum install -y file-libs file-devel 2>/dev/null || true"
      ;;
    macos-brew)
      # libmagic is usually present via brew coreutils; install explicitly if missing
      command -v file &>/dev/null || run "brew install libmagic 2>/dev/null || true"
      ;;
  esac

  # Install ScanCode — try system-wide first, then user install
  if ! $DRY_RUN; then
    python3 -m pip install --quiet scancode-toolkit 2>/dev/null || \
    python3 -m pip install --quiet --user scancode-toolkit 2>/dev/null || {
      warn "ScanCode install failed — ip_check.py will use PyPI API fallback"
      warn "Try manually: pip install scancode-toolkit"
      warn "Docs: https://scancode-toolkit.readthedocs.io/en/stable/getting-started/install.html"
      return
    }
  else
    dry_run "Would install scancode-toolkit via pip"
    return
  fi

  if command -v scancode &>/dev/null; then
    ok "scancode installed ($(scancode --version 2>/dev/null | head -1 | tr -d '\n'))"
  else
    # Might be installed as a user package not yet on PATH
    SCANCODE_PATH="$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>/dev/null)/scancode"
    USER_SCANCODE="$(python3 -m site --user-base 2>/dev/null)/bin/scancode"
    if [[ -x "$SCANCODE_PATH" ]] || [[ -x "$USER_SCANCODE" ]]; then
      ok "scancode installed (may need to add $(dirname "${USER_SCANCODE}") to PATH)"
    else
      warn "scancode installed but not on PATH — open a new shell and re-run: scancode --version"
    fi
  fi

  echo ""
  skip "ai-gen-code-search (Level 3 regurgitation lens — requires backend services)"
  echo "       NOT a standalone pip install. Requires PurlDB + MatchCode + ScanCode.io"
  echo "       service stack deployment, OR research API access from AboutCode."
  echo "       Contact: hello@aboutcode.org for evaluation access."
  echo "       Docs: https://github.com/aboutcode-org/ai-gen-code-search"
}

install_scancode

header "3. GitHub CLI (gh)"

if command -v gh &>/dev/null; then
  ok "gh $(gh --version | head -1 | awk '{print $3}')"
  if gh auth status &>/dev/null 2>&1; then
    ok "gh authenticated"
  else
    warn "gh not authenticated — run: gh auth login"
  fi
else
  case "$OS-$PKG_MGR" in
    macos-brew)
      info "Installing gh via brew..."
      run "brew install gh"
      ok "gh installed"
      ;;
    linux-apt)
      info "Installing gh via apt..."
      if ! $DRY_RUN; then
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
          | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
          | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
        sudo apt-get update -qq && sudo apt-get install -y gh
        ok "gh installed"
      else
        dry_run "Would install gh via apt"
      fi
      ;;
    linux-dnf|linux-yum)
      info "Installing gh via dnf/yum..."
      run "$SUDO $PKG_MGR install -y 'dnf-command(config-manager)' 2>/dev/null || true"
      run "$SUDO $PKG_MGR config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo 2>/dev/null || true"
      run "$SUDO $PKG_MGR install -y gh"
      ;;
    *)
      warn "Cannot auto-install gh on $OS/$PKG_MGR"
      warn "Install from: https://cli.github.com"
      ;;
  esac
fi

header "4. AI agent CLIs (agy + codex)"

if $SKIP_CLIS; then
  skip "CLI checks skipped (--skip-clis)"
else
  echo "  These require interactive browser authentication."
  echo "  For full CLI install + auth, run: ./scripts/setup_clis.sh"
  echo ""
  if command -v agy &>/dev/null; then
    ok "agy $(agy --version 2>/dev/null | head -1 | tr -d '\n') — Gemini (conditional screening)"
  else
    warn "agy not installed — Gemini reviewer unavailable"
    echo "       Install: ./scripts/setup_clis.sh install"
    echo "       Auth:    ./scripts/setup_clis.sh auth"
  fi
  if command -v codex &>/dev/null; then
    ok "codex — OpenAI (reserve adversarial reviewer)"
  else
    warn "codex not installed — OpenAI reserve reviewer unavailable"
    echo "       Install: ./scripts/setup_clis.sh install"
  fi
fi

header "5. Local runtime directories"

AI_LOCAL="$HOS_ROOT/.ai-local"
run "mkdir -p '$AI_LOCAL/panel'"
ok ".ai-local/panel/"

SALT_FILE="$AI_LOCAL/sample.salt"
if [[ -f "$SALT_FILE" ]]; then
  skip ".ai-local/sample.salt exists (SQC sampling key — do not regenerate)"
else
  run "python3 -c \"import secrets; print(secrets.token_hex(32))\" > '$SALT_FILE'"
  ok "Generated .ai-local/sample.salt (SQC random red-team sampling key)"
fi

# Ensure .ai-local is gitignored in HOS itself
if ! grep -q "^\.ai-local/" "$HOS_ROOT/.gitignore" 2>/dev/null; then
  run "echo '.ai-local/' >> '$HOS_ROOT/.gitignore'"
  ok "Added .ai-local/ to HOS .gitignore"
fi

fi  # end: if ! $PROJECT_ONLY

# ══════════════════════════════════════════════════════════════════════════════
# PROJECT SETUP
# ══════════════════════════════════════════════════════════════════════════════

if ! $MACHINE_ONLY; then

header "6. Project setup: $TARGET_REPO"

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

# ── .claude/agents/ ────────────────────────────────────────────────────────────
echo ""
info ".claude/agents/ — oversight agents"
run "mkdir -p '$TARGET_REPO/.claude/agents'"

for agent in risk-assessor dep-mapper risk-historian \
             oversight-evaluator oversight-orchestrator spec-red-team; do
  src="$HOS_ROOT/.claude/agents/${agent}.md"
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
  SETTINGS_SRC="$HOS_ROOT/.claude/settings.json"
  cp_file "$SETTINGS_SRC" "$SETTINGS_DST" ".claude/settings.json"
fi

# ── scripts/ — HOS runner scripts ─────────────────────────────────────────────
echo ""
info "scripts/ — HOS runner scripts"
run "mkdir -p '$TARGET_REPO/scripts'"

for script in run_panel.sh run_second_review.sh run_red_team.sh \
              review_self.sh reverify_self.sh \
              capture_prompt.sh prompt_audit.sh \
              setup_clis.sh setup_oversight.sh; do
  src="$HOS_ROOT/scripts/$script"
  [[ ! -f "$src" ]] && src="$HOS_ROOT/templates/$script"   # fallback to templates/
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
    "$HOS_ROOT/scripts/oversight/" \
    "$TARGET_REPO/scripts/oversight/" 2>/dev/null || \
  cp -rn "$HOS_ROOT/scripts/oversight/." "$TARGET_REPO/scripts/oversight/"
  ok "scripts/oversight/ synced"
else
  dry_run "Would sync $HOS_ROOT/scripts/oversight/ → $TARGET_REPO/scripts/oversight/"
fi

# ── AGENTS.md — Layer 1 protocol ──────────────────────────────────────────────
echo ""
info "Core governance documents"
cp_file "$HOS_ROOT/AGENTS.md"     "$TARGET_REPO/AGENTS.md"
cp_file "$HOS_ROOT/METHODOLOGY.md" "$TARGET_REPO/METHODOLOGY.md" \
  2>/dev/null || true  # optional

# ── contract/ — step manifest template ────────────────────────────────────────
run "mkdir -p '$TARGET_REPO/contract'"
if [[ ! -f "$TARGET_REPO/contract/step-manifest.yaml" ]]; then
  cp_file "$HOS_ROOT/contract/step-manifest.template.yaml" \
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
    [[ -f "$HOS_ROOT/audit/README.md" ]] && \
      cp "$HOS_ROOT/audit/README.md" "$TARGET_REPO/audit/README.md" || true
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
cp_file "$HOS_ROOT/.github/CODEOWNERS"              "$TARGET_REPO/.github/CODEOWNERS"
cp_file "$HOS_ROOT/.github/pull_request_template.md" "$TARGET_REPO/.github/pull_request_template.md"

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

fi  # end: if ! $MACHINE_ONLY

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

header "Done"

if [[ $ERRORS -gt 0 ]]; then
  err "$ERRORS error(s) — address the above before using HOS"
  exit 1
fi

echo ""
if ! $MACHINE_ONLY; then
  ok "HOS framework installed in: $TARGET_REPO"
  echo ""
  echo -e "  ${BOLD}Next steps:${RESET}"
  echo ""
  echo "  1. Fill in the step manifest:"
  echo "       $TARGET_REPO/contract/step-manifest.yaml"
  echo ""
  echo "  2. Authenticate AI CLIs (if not done):"
  echo "       bash $HOS_ROOT/scripts/setup_clis.sh auth"
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
else
  ok "Machine prerequisites installed"
  echo ""
  echo "  Install into a project:"
  echo "    ./install.sh /path/to/your/project"
  echo ""
fi

echo "  Docs: CLAUDE.md · ARCHITECTURE.md · contract/OVERSIGHT-CONTRACT.md"
echo ""
