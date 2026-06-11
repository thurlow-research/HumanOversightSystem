#!/usr/bin/env bash
# install.sh — Human Oversight System bootstrap
#
# Two modes:
#   ./install.sh              Machine setup: install Python packages + check CLIs
#   ./install.sh <repo-path>  Project install: machine setup + scaffold oversight
#                             protocol into the target repo (calls setup_oversight.sh)
#
# What it does:
#   1. Check prerequisites (Python 3.10+, git, pip, Node)
#   2. Install Python analysis packages (radon, bandit, semgrep, etc.)
#   3. Install/verify GitHub CLI (gh)
#   4. Check/guide setup for agy (Gemini) and codex (OpenAI)
#   5. Create local runtime directories + SQC salt
#   6. (If project path given) run setup_oversight.sh against the target
#
# Idempotent: safe to re-run. Already-installed tools are skipped.
# Prerequisites: bash, curl, python3, git

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_REPO=""
SKIP_PROJECT_INSTALL=false

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        --skip-project)
            SKIP_PROJECT_INSTALL=true; shift ;;
        *)
            TARGET_REPO="$1"; shift ;;
    esac
done

# ── Colours (match setup_clis.sh) ─────────────────────────────────────────────
GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()    { echo -e "  ${GREEN}✔${RESET}  $*"; }
skip()  { echo -e "  ${YELLOW}–${RESET}  $*"; }
info()  { echo -e "  ${CYAN}→${RESET}  $*"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()   { echo -e "  ${RED}✘${RESET}  $*"; }
header(){ echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

ERRORS=0
fail() { err "$*"; ERRORS=$((ERRORS+1)); }

# ── Detect platform ───────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

header "Human Oversight System — install"
echo "  Platform: $OS / $ARCH"
echo "  HOS root: $SCRIPT_DIR"
[[ -n "$TARGET_REPO" ]] && echo "  Target:   $TARGET_REPO"
echo ""

# ════════════════════════════════════════════════════════════════════════════════
header "1. Prerequisites"
# ════════════════════════════════════════════════════════════════════════════════

# Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [[ $PY_MAJOR -ge 3 && $PY_MINOR -ge 10 ]]; then
        ok "Python $PY_VER"
    else
        fail "Python $PY_VER — need 3.10+. Install from python.org or brew install python@3.12"
    fi
else
    fail "python3 not found. Install from python.org or: brew install python@3.12"
fi

# pip
if command -v pip3 &>/dev/null || python3 -m pip --version &>/dev/null 2>&1; then
    ok "pip available"
else
    fail "pip not found. Install: python3 -m ensurepip"
fi

# git
if command -v git &>/dev/null; then
    GIT_VER=$(git --version | awk '{print $3}')
    ok "git $GIT_VER"
else
    fail "git not found"
fi

[[ $ERRORS -gt 0 ]] && { err "Fix prerequisite errors above before continuing"; exit 1; }

# ════════════════════════════════════════════════════════════════════════════════
header "2. Python analysis packages"
# ════════════════════════════════════════════════════════════════════════════════

REQUIREMENTS="$SCRIPT_DIR/scripts/oversight/requirements.txt"

info "Installing from $REQUIREMENTS ..."
if python3 -m pip install --quiet -r "$REQUIREMENTS" 2>&1 | grep -v "already satisfied" | grep -v "^$"; then
    :
fi

# Verify key packages
for pkg in radon bandit flake8 black isort mypy; do
    if python3 -m pip show "$pkg" &>/dev/null 2>&1; then
        ok "$pkg"
    else
        warn "$pkg not installed — some validators will be skipped"
    fi
done

# Optional: semgrep (larger install, worth noting separately)
if command -v semgrep &>/dev/null; then
    ok "semgrep $(semgrep --version 2>/dev/null | head -1)"
else
    skip "semgrep not installed (optional, enhances static analysis)"
    echo "       Install: pip install semgrep  OR  brew install semgrep"
fi

# Optional: detect-secrets
if command -v detect-secrets &>/dev/null; then
    ok "detect-secrets"
else
    skip "detect-secrets not installed (optional, enhances secret scanning)"
    echo "       Install: pip install detect-secrets"
fi

# ════════════════════════════════════════════════════════════════════════════════
header "3. GitHub CLI (gh)"
# ════════════════════════════════════════════════════════════════════════════════

if command -v gh &>/dev/null; then
    GH_VER=$(gh --version | head -1 | awk '{print $3}')
    ok "gh $GH_VER"
    if gh auth status &>/dev/null 2>&1; then
        ok "gh authenticated"
    else
        warn "gh not authenticated. Run: gh auth login"
    fi
else
    info "Installing gh ..."
    if [[ "$OS" == "Darwin" ]] && command -v brew &>/dev/null; then
        brew install gh
        ok "gh installed via brew"
    elif [[ "$OS" == "Linux" ]]; then
        # Official install via package manager or binary
        if command -v apt-get &>/dev/null; then
            type -p curl >/dev/null || apt-get install curl -y
            curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
            apt-get update && apt-get install gh -y
            ok "gh installed via apt"
        else
            warn "Could not auto-install gh. Install from: https://cli.github.com"
        fi
    else
        warn "Could not auto-install gh. Install from: https://cli.github.com"
    fi
    echo ""
    info "After install: gh auth login"
fi

# ════════════════════════════════════════════════════════════════════════════════
header "4. Agent CLIs (agy + codex)"
# ════════════════════════════════════════════════════════════════════════════════

echo "  These require interactive browser authentication."
echo "  If not yet installed, run: ./scripts/setup_clis.sh"
echo ""

# agy (Antigravity / Gemini)
if command -v agy &>/dev/null; then
    AGY_VER=$(agy --version 2>/dev/null | head -1 || echo "installed")
    ok "agy $AGY_VER (Gemini — conditional screening reviewer)"
    echo "     Subscription: Gemini Pro \$20/mo → \$100/mo if needed"
    echo "     Threshold:    OVERSIGHT_AGY_THRESHOLD=0.30 (MEDIUM+)"
else
    warn "agy not installed (Gemini — conditional screening reviewer)"
    echo "       Install: ./scripts/setup_clis.sh install"
    echo "       Auth:    ./scripts/setup_clis.sh auth"
    echo "       Subscription needed: Google One AI Premium (\$20/mo)"
fi

echo ""

# codex (OpenAI)
if command -v codex &>/dev/null; then
    ok "codex (OpenAI — reserve adversarial reviewer)"
    echo "     Subscription: ChatGPT Pro \$20/mo (reserve — keep at \$20)"
    echo "     Threshold:    OVERSIGHT_CODEX_THRESHOLD=0.55 (HIGH+)"
else
    warn "codex not installed (OpenAI — reserve adversarial reviewer)"
    echo "       Install: ./scripts/setup_clis.sh install"
    echo "       Auth:    ./scripts/setup_clis.sh auth"
    echo "       Subscription needed: ChatGPT Pro (\$20/mo)"
fi

# ════════════════════════════════════════════════════════════════════════════════
header "5. Local runtime directories"
# ════════════════════════════════════════════════════════════════════════════════

mkdir -p "$SCRIPT_DIR/.ai-local/panel"
ok "Created .ai-local/panel/"

# SQC salt for reproducible random red-team sampling (D17)
SALT_FILE="$SCRIPT_DIR/.ai-local/sample.salt"
if [[ -f "$SALT_FILE" ]]; then
    skip ".ai-local/sample.salt already exists (do not regenerate)"
else
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$SALT_FILE"
    ok "Generated .ai-local/sample.salt (SQC sampling key)"
fi

# Ensure .ai-local is in .gitignore
if grep -q "\.ai-local/" "$SCRIPT_DIR/.gitignore" 2>/dev/null; then
    ok ".ai-local/ in .gitignore"
else
    echo ".ai-local/" >> "$SCRIPT_DIR/.gitignore"
    ok "Added .ai-local/ to .gitignore"
fi

# ════════════════════════════════════════════════════════════════════════════════
header "6. Project install (optional)"
# ════════════════════════════════════════════════════════════════════════════════

if [[ -n "$TARGET_REPO" ]] && ! $SKIP_PROJECT_INSTALL; then
    if [[ ! -d "$TARGET_REPO" ]]; then
        fail "Target repo not found: $TARGET_REPO"
    else
        info "Installing oversight protocol into $TARGET_REPO ..."
        bash "$SCRIPT_DIR/scripts/setup_oversight.sh" "$TARGET_REPO"
        ok "Oversight protocol installed"

        # Copy contract template if not already there
        if [[ ! -f "$TARGET_REPO/contract/step-manifest.yaml" ]]; then
            mkdir -p "$TARGET_REPO/contract"
            cp "$SCRIPT_DIR/contract/step-manifest.template.yaml" \
               "$TARGET_REPO/contract/step-manifest.yaml"
            ok "Copied step-manifest.yaml to $TARGET_REPO/contract/"
            warn "Edit $TARGET_REPO/contract/step-manifest.yaml to define your build steps"
        else
            skip "step-manifest.yaml already exists in target"
        fi

        # Copy oversight agent files to target's .claude/agents/
        if [[ ! -d "$TARGET_REPO/.claude/agents" ]]; then
            mkdir -p "$TARGET_REPO/.claude/agents"
        fi
        for agent in risk-assessor dep-mapper risk-historian oversight-evaluator oversight-orchestrator spec-red-team; do
            SRC="$SCRIPT_DIR/.claude/agents/${agent}.md"
            DST="$TARGET_REPO/.claude/agents/${agent}.md"
            if [[ -f "$SRC" && ! -f "$DST" ]]; then
                cp "$SRC" "$DST"
                ok "Installed .claude/agents/${agent}.md"
            elif [[ -f "$DST" ]]; then
                skip ".claude/agents/${agent}.md already exists in target"
            fi
        done

        # Copy oversight scripts
        mkdir -p "$TARGET_REPO/scripts/oversight/validators" \
                 "$TARGET_REPO/scripts/oversight/gates"
        rsync -a --ignore-existing \
            "$SCRIPT_DIR/scripts/oversight/" \
            "$TARGET_REPO/scripts/oversight/"
        for script in run_panel.sh run_second_review.sh run_red_team.sh capture_prompt.sh prompt_audit.sh; do
            SRC="$SCRIPT_DIR/scripts/$script"
            DST="$TARGET_REPO/scripts/$script"
            if [[ -f "$SRC" && ! -f "$DST" ]]; then
                cp "$SRC" "$DST"
                chmod +x "$DST"
                ok "Installed scripts/$script"
            elif [[ -f "$DST" ]]; then
                skip "scripts/$script already exists in target"
            fi
        done
    fi
else
    skip "No target repo specified — machine-only install"
    echo ""
    echo "  To install into a project:"
    echo "    ./install.sh /path/to/your/project"
    echo ""
    echo "  Or manually:"
    echo "    ./scripts/setup_oversight.sh /path/to/your/project"
fi

# ════════════════════════════════════════════════════════════════════════════════
header "Summary"
# ════════════════════════════════════════════════════════════════════════════════

if [[ $ERRORS -gt 0 ]]; then
    err "$ERRORS error(s) — address above before using the oversight system"
    exit 1
fi

echo ""
ok "Machine setup complete"
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Authenticate CLIs (if not done):"
echo "       ./scripts/setup_clis.sh auth"
echo ""
echo "  2. Install into a project:"
echo "       ./install.sh /path/to/project"
echo ""
echo "  3. Edit the project's step manifest:"
echo "       /path/to/project/contract/step-manifest.yaml"
echo ""
echo "  4. Run the pipeline:"
echo "       Inner loop:  bash scripts/oversight/run_validators.sh [files...]"
echo "       Transition:  bash scripts/run_second_review.sh --step N --score 0.6"
echo "       Outer loop:  bash scripts/run_panel.sh [PR#]"
echo "       Checkpoint:  bash scripts/run_red_team.sh --milestone auth"
echo ""
echo "  Docs:  CLAUDE.md | METHODOLOGY.md | DECISIONS.md"
echo "         contract/OVERSIGHT-CONTRACT.md"
echo ""
