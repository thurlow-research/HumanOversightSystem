#!/usr/bin/env bash
# hos_bootstrap.sh — Human Oversight System — MACHINE bootstrap.
#
# Sets up a machine to run HOS. Run ONCE per machine. Installs system-level
# prerequisites and the agent CLIs. Does NOT touch any project — see
# hos_install.sh for installing the framework into a target repo.
#
# Separation of concerns (machine vs. project):
#   hos_bootstrap.sh  → once per MACHINE: Python, ScanCode, gh, pip pkgs, CLIs.
#                       May need sudo (system packages).
#   hos_install.sh    → once per PROJECT: fetches a validated release and
#                       scaffolds it into a target repo. No sudo, no installs.
#
# Usage:
#   ./hos_bootstrap.sh                # install all machine prerequisites
#   ./hos_bootstrap.sh --dry-run      # show what would be done, no writes
#   ./hos_bootstrap.sh --skip-clis    # skip agent CLI (agy/codex) setup
#   ./hos_bootstrap.sh --no-sudo      # skip steps that require sudo
#   ./hos_bootstrap.sh --help
#
# What it installs on the machine:
#   Python 3.10+, pip, the Python analysis packages (radon, bandit, flake8,
#   black, isort, mypy), ScanCode Toolkit (IP/license detection), gh CLI, and
#   — via setup_clis.sh (sibling in bootstrap/) — the agent CLIs + Node.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Defaults ──────────────────────────────────────────────────────────────────
DRY_RUN=false
SKIP_CLIS=false
NO_SUDO=false

# ── Args ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   DRY_RUN=true; shift ;;
    --skip-clis) SKIP_CLIS=true; shift ;;
    --no-sudo)   NO_SUDO=true; shift ;;
    --help|-h)   sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)          echo "Unknown option: $1  (try --help)"; exit 1 ;;
    *)           echo "Unexpected argument: $1  (try --help)"; exit 1 ;;
  esac
done

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
run() { if $DRY_RUN; then dry_run "$@"; else eval "$@"; fi; }

ERRORS=0
fail() { err "$*"; ERRORS=$((ERRORS + 1)); }

# ── Platform detection ────────────────────────────────────────────────────────
OS="unknown"; PKG_MGR="none"; SUDO=""
detect_platform() {
  case "$(uname -s)" in
    Darwin)
      OS="macos"
      command -v brew &>/dev/null && PKG_MGR="brew" || PKG_MGR="none" ;;
    Linux)
      OS="linux"
      if   command -v apt-get &>/dev/null; then PKG_MGR="apt"
      elif command -v dnf     &>/dev/null; then PKG_MGR="dnf"
      elif command -v yum     &>/dev/null; then PKG_MGR="yum"
      elif command -v pacman  &>/dev/null; then PKG_MGR="pacman"
      fi ;;
  esac
  if ! $NO_SUDO && command -v sudo &>/dev/null; then SUDO="sudo"; fi
}
detect_platform

echo ""
echo -e "${BOLD}Human Oversight System — machine bootstrap${RESET}"
echo "  Platform: $OS  ($PKG_MGR)"
$DRY_RUN && echo -e "  ${YELLOW}DRY RUN — no changes will be made${RESET}"
echo ""

# ── 1. Python 3.10+ ───────────────────────────────────────────────────────────
header "1. Python 3.10+"
install_python() {
  local min_minor=10
  if command -v python3 &>/dev/null; then
    local ver major minor
    ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    major=$(echo "$ver" | cut -d. -f1); minor=$(echo "$ver" | cut -d. -f2)
    if [[ "$major" -ge 3 && "$minor" -ge "$min_minor" ]]; then ok "python3 $ver"; return; fi
    warn "python3 $ver found but need 3.${min_minor}+ — upgrading"
  fi
  case "$OS-$PKG_MGR" in
    macos-brew)   info "Installing Python 3.12 via brew...";  run "brew install python@3.12"; run "brew link --force python@3.12 2>/dev/null || true" ;;
    linux-apt)    info "Installing Python 3 via apt...";      run "$SUDO apt-get update -qq"; run "$SUDO apt-get install -y python3 python3-pip python3-venv python3-dev" ;;
    linux-dnf)    info "Installing Python 3 via dnf...";      run "$SUDO dnf install -y python3 python3-pip python3-devel" ;;
    linux-yum)    info "Installing Python 3 via yum...";      run "$SUDO yum install -y python3 python3-pip" ;;
    linux-pacman) info "Installing Python 3 via pacman...";   run "$SUDO pacman -Sy --noconfirm python python-pip" ;;
    macos-none)   fail "brew not found. Install Homebrew first: https://brew.sh, then re-run." ;;
    *)            fail "No supported package manager (brew/apt/dnf/yum/pacman). Install Python 3.10+ manually." ;;
  esac
  if command -v python3 &>/dev/null; then ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"; else fail "python3 not found after install attempt"; fi
}
install_python

if python3 -m pip --version &>/dev/null 2>&1; then
  ok "pip $(python3 -m pip --version | awk '{print $2}')"
else
  warn "pip not found — attempting to install..."
  case "$OS-$PKG_MGR" in
    linux-apt) run "$SUDO apt-get install -y python3-pip" ;;
    linux-dnf) run "$SUDO dnf install -y python3-pip" ;;
    linux-yum) run "$SUDO yum install -y python3-pip" ;;
    *)         run "python3 -m ensurepip --upgrade" ;;
  esac
fi

# ── 2. Python analysis packages ───────────────────────────────────────────────
header "2. Python analysis packages"
# These are the validator/gate dependencies. Bootstrap installs them machine-
# wide; hos_install.sh's per-project venv (ensure_venv.sh) pins exact versions
# from the installed release's requirements.txt.
ANALYSIS_PKGS="radon bandit flake8 black isort mypy"
if ! $DRY_RUN; then
  python3 -m pip install --quiet --upgrade pip 2>/dev/null || true
  # shellcheck disable=SC2086
  python3 -m pip install --quiet $ANALYSIS_PKGS 2>/dev/null || \
  # shellcheck disable=SC2086
  python3 -m pip install --quiet --user $ANALYSIS_PKGS 2>/dev/null || \
    warn "Some packages failed to install — try: pip install $ANALYSIS_PKGS"
else
  dry_run "Would pip install: $ANALYSIS_PKGS"
fi
for pkg in $ANALYSIS_PKGS; do
  if python3 -c "import $pkg" &>/dev/null 2>&1 || command -v "$pkg" &>/dev/null; then ok "$pkg"; else warn "$pkg not importable (may still work via CLI)"; fi
done
for opt_pkg in semgrep detect-secrets; do
  command -v "$opt_pkg" &>/dev/null && ok "$opt_pkg (optional)" || skip "$opt_pkg not installed (optional: pip install $opt_pkg)"
done

# ── 2a. IP tooling — ScanCode Toolkit ─────────────────────────────────────────
header "2a. IP tooling — ScanCode Toolkit"
# ScanCode provides full license-text detection (Level 1 IP agent). Without it,
# ip_check.py falls back to PyPI/npm API lookups (less thorough).
install_scancode() {
  if command -v scancode &>/dev/null; then ok "scancode $(scancode --version 2>/dev/null | head -1 | tr -d '\n')"; return; fi
  info "Installing ScanCode Toolkit (IP/license detection)..."
  case "$OS-$PKG_MGR" in
    linux-apt) info "Installing libmagic (ScanCode dependency)..."; run "$SUDO apt-get install -y libmagic-dev libmagic1 2>/dev/null || true" ;;
    linux-dnf) run "$SUDO dnf install -y file-libs file-devel 2>/dev/null || true" ;;
    linux-yum) run "$SUDO yum install -y file-libs file-devel 2>/dev/null || true" ;;
    macos-brew) command -v file &>/dev/null || run "brew install libmagic 2>/dev/null || true" ;;
  esac
  if ! $DRY_RUN; then
    python3 -m pip install --quiet scancode-toolkit 2>/dev/null || \
    python3 -m pip install --quiet --user scancode-toolkit 2>/dev/null || {
      warn "ScanCode install failed — ip_check.py will use PyPI API fallback"
      warn "Try manually: pip install scancode-toolkit"
      return
    }
  else
    dry_run "Would install scancode-toolkit via pip"; return
  fi
  command -v scancode &>/dev/null && ok "scancode installed" || warn "scancode installed but not on PATH — open a new shell and check: scancode --version"
  echo ""
  skip "ai-gen-code-search (Level 3 regurgitation lens — requires backend services; not a pip install)"
}
install_scancode

# ── 3. GitHub CLI (gh) ────────────────────────────────────────────────────────
header "3. GitHub CLI (gh)"
if command -v gh &>/dev/null; then
  ok "gh $(gh --version | head -1 | awk '{print $3}')"
  if gh auth status &>/dev/null 2>&1; then ok "gh authenticated"; else warn "gh not authenticated — run: gh auth login"; fi
else
  case "$OS-$PKG_MGR" in
    macos-brew) info "Installing gh via brew..."; run "brew install gh"; ok "gh installed" ;;
    linux-apt)
      info "Installing gh via apt..."
      if ! $DRY_RUN; then
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | $SUDO dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | $SUDO tee /etc/apt/sources.list.d/github-cli.list >/dev/null
        $SUDO apt-get update -qq && $SUDO apt-get install -y gh && ok "gh installed"
      else dry_run "Would install gh via apt"; fi ;;
    linux-dnf|linux-yum)
      info "Installing gh via $PKG_MGR..."
      run "$SUDO $PKG_MGR install -y 'dnf-command(config-manager)' 2>/dev/null || true"
      run "$SUDO $PKG_MGR config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo 2>/dev/null || true"
      run "$SUDO $PKG_MGR install -y gh" ;;
    *) warn "Cannot auto-install gh on $OS/$PKG_MGR — install from https://cli.github.com" ;;
  esac
fi

# ── 4. AI agent CLIs (claude + agy + codex) ───────────────────────────────────
header "4. AI agent CLIs (claude + agy + codex)"
if $SKIP_CLIS; then
  skip "Agent CLI setup skipped (--skip-clis)"
elif [[ -f "$SCRIPT_DIR/setup_clis.sh" ]]; then
  info "Delegating to scripts/setup_clis.sh (installs Node + agent CLIs, drives browser auth)..."
  if $DRY_RUN; then
    dry_run "Would run: bash setup_clis.sh install"
  else
    bash "$SCRIPT_DIR/setup_clis.sh" install || warn "setup_clis.sh reported issues — review its output"
    echo "  Then authenticate each CLI:  bash bootstrap/setup_clis.sh auth"
  fi
else
  warn "scripts/setup_clis.sh not found alongside this script."
  echo "       Get setup_clis.sh (it is repo-independent) and run: bash setup_clis.sh install && bash setup_clis.sh auth"
  for c in agy codex; do command -v "$c" &>/dev/null && ok "$c present" || warn "$c not installed"; done
fi

# ── Summary ───────────────────────────────────────────────────────────────────
header "Done"
echo ""
if [[ $ERRORS -gt 0 ]]; then
  err "$ERRORS error(s) — address the above before installing HOS into a project"
  exit 1
fi
ok "Machine bootstrap complete."
echo ""
echo -e "  ${BOLD}Next:${RESET} install HOS into a project from a validated release:"
echo "      ./hos_install.sh /path/to/your/project"
echo ""
