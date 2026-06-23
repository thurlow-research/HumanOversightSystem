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
#   ./hos_install.sh --pr [DIR]           # apply the upgrade on a branch + open a PR
#                                         #   (auditable, reversible). Opt-in for now;
#                                         #   default is in-place. --no-pr forces in-place.
#   ./hos_install.sh --prune [DIR]        # archive framework files removed across
#                                         #   versions (move → committed .hos-archive/;
#                                         #   only unmodified files; recoverable).
#   ./hos_install.sh --squash [DIR]       # take HOS's version of any drifted CORE/PACK
#                                         #   region (explicit consent; never touches
#                                         #   PROJECT). Resolves a layering drift hard-stop.
#   ./hos_install.sh --pack <name> [DIR]  # install with a named pack (repeatable for multi-pack)
#   ./hos_install.sh --no-pack [DIR]      # install bare core only (deliberate; see #237)
#   ./hos_install.sh --brownfield [DIR]   # classify flat agent files + migrate safely (#275)
#                                         #   (pre-region-model repos without .hos-manifest)
#   ./hos_install.sh --scaffold-pack <slug> [DIR]
#                                         # extract PROJECT customizations into a consumer
#                                         #   pack (requires --brownfield; slug = pack name)
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
PR_MODE="off"         # off (default — opt-in) | on (--pr) — branch+PR the upgrade (#193).
                      # Opt-in until the live push/PR path is proven on a real upgrade.
PRUNE=false           # --prune: archive framework files removed across versions (#182)
SQUASH=false          # --squash: take HOS's version of a drifted CORE/PACK region (TD §4.3)
NO_PACK=false         # --no-pack: install bare core, no pack (deliberate; #237 WARN)
FULL=false            # --full: bypass version-adjacency hard-stop; install target wholesale (#238)
BROWNFIELD=false      # --brownfield: classify flat agent files, synth a baseline, then merge (#275)
SCAFFOLD_PACK=""      # --scaffold-pack <slug>: extract project_custom into a consumer pack (#275)
_packs=()             # --pack <name> (repeatable). Empty ⇒ resolve from config.sh PACK=.

# ── Args ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)       DRY_RUN=true; shift ;;
    --force)         FORCE=true; shift ;;
    --skip-clis)     SKIP_CLIS=true; shift ;;
    --release)       RELEASE_REF="${2:?--release needs a tag, e.g. v0.3.0}"; shift 2 ;;
    --release=*)     RELEASE_REF="${1#*=}"; shift ;;
    --local)         LOCAL_SOURCE=true; shift ;;
    --pr)            PR_MODE="on"; shift ;;
    --no-pr)         PR_MODE="off"; shift ;;
    --prune)         PRUNE=true; shift ;;
    --squash)        SQUASH=true; shift ;;
    --full)          FULL=true; shift ;;
    --brownfield)    BROWNFIELD=true; shift ;;
    --scaffold-pack) SCAFFOLD_PACK="${2:?--scaffold-pack needs a slug, e.g. --scaffold-pack condoparkshare}"; shift 2 ;;
    --scaffold-pack=*) SCAFFOLD_PACK="${1#*=}"; shift ;;
    --pack)          _packs+=("${2:?--pack needs a name, e.g. --pack django}"); shift 2 ;;
    --pack=*)        _packs+=("${1#*=}"); shift ;;
    --no-pack)       NO_PACK=true; shift ;;
    --help|-h)       sed -n '2,43p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)              echo "Unknown option: $1  (try --help)"; exit 1 ;;
    *)               TARGET_REPO="$1"; shift ;;
  esac
done

TARGET_REPO="$(cd "$TARGET_REPO" 2>/dev/null && pwd)" || {
  echo "ERROR: target directory not found: $TARGET_REPO"; exit 1; }

# Mutual-exclusion: --no-pack and --pack are contradictory.
if $NO_PACK && [[ ${#_packs[@]} -gt 0 ]]; then
  echo "ERROR: --no-pack and --pack are mutually exclusive (try --help)"; exit 1
fi

# REQ-B-01: --brownfield and --squash are mutually exclusive (#275).
if $BROWNFIELD && $SQUASH; then
  echo "ERROR: --brownfield and --squash are mutually exclusive."
  echo "  --brownfield performs its own safe classification before merging."
  echo "  --squash overwrites all CORE/PACK regions without classification."
  echo "  Use --brownfield for pre-region-model repos."
  exit 2
fi

# REQ-CS-07: --scaffold-pack requires --brownfield.
if [[ -n "$SCAFFOLD_PACK" ]] && ! $BROWNFIELD; then
  echo "ERROR: --scaffold-pack requires --brownfield."
  echo "  Consumer pack scaffolding is part of the brownfield migration flow."
  exit 2
fi

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

# Execute a command as argv — never `eval` a built string (a target path with a
# quote or shell metachar would otherwise inject commands). For redirections,
# inline the dry-run check at the call site instead of using run().
run() {
  if $DRY_RUN; then dry_run "$(printf '%q ' "$@")"; else "$@"; fi
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
# The bootstrap scripts normally live INSIDE the TARGET project's git tree (e.g.
# CondoParkShare/hos-bootstrap), so the local `origin` remote is the TARGET's, not
# HOS's. Deriving HOS_REPO from it queried the wrong repo for releases and reported
# "No published HOS release found." Only trust the local remote when it is actually
# the HOS repo or a fork of it (repo name == HumanOversightSystem, any owner);
# otherwise fall back to the canonical repo. Override anytime with HOS_REPO=.
if [[ -z "${HOS_REPO:-}" ]]; then
  _derived="$(git -C "$HOS_REPO_ROOT" remote get-url origin 2>/dev/null \
    | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?$#\1#' || true)"
  [[ "$_derived" == */HumanOversightSystem ]] && HOS_REPO="$_derived"
fi
[[ -z "${HOS_REPO:-}" ]] && HOS_REPO="ScottThurlow/HumanOversightSystem"

# A staged source is only trustworthy if it contains the ESSENTIAL framework
# files — not just a sentinel or two. A truncated/partial archive that happened
# to include AGENTS.md must NOT pass and then silently install an incomplete HOS.
# Every path here is required for a working install; a miss is fatal upstream.
REQUIRED_SOURCE_PATHS=(
  "AGENTS.md"
  "contract/OVERSIGHT-CONTRACT.md"
  "contract/step-manifest.template.yaml"
  ".claude/settings.json"
  ".claude/agents/risk-assessor.md"
  ".claude/agents/oversight-evaluator.md"
  ".claude/agents/oversight-orchestrator.md"
  "scripts/oversight/run_validators.sh"
  "scripts/oversight/requirements.txt"
  "scripts/run_panel.sh"
  ".github/CODEOWNERS"
)
source_looks_valid() {  # dir -> 0 if all required paths present
  local d="$1" miss=0 p
  for p in "${REQUIRED_SOURCE_PATHS[@]}"; do
    [[ -e "$d/$p" ]] || { miss=1; $VERBOSE_SRC_CHECK && warn "  source missing: $p"; }
  done
  [[ "$miss" -eq 0 ]]
}
VERBOSE_SRC_CHECK=false

fetch_release_tarball() {  # ref dest_dir -> 0 on success
  local ref="$1" dest="$2" tmpd tgz
  # mktemp -d with the X-run TRAILING (BSD/macOS only substitutes a trailing run;
  # a "XXXXXX.tar.gz" template would NOT randomize on macOS → fixed predictable
  # path → collisions and stale/planted-file extraction risk).
  tmpd="$(mktemp -d "${TMPDIR:-/tmp}/hos-src.XXXXXX")" || return 1
  CLEANUP_DIRS+=("$tmpd")
  tgz="$tmpd/src.tar.gz"
  if command -v gh &>/dev/null; then
    gh api "repos/${HOS_REPO}/tarball/${ref}" > "$tgz" 2>/dev/null || true
  fi
  if [[ ! -s "$tgz" ]] && command -v curl &>/dev/null; then
    curl -fsSL "https://github.com/${HOS_REPO}/archive/refs/tags/${ref}.tar.gz" -o "$tgz" 2>/dev/null || true
  fi
  [[ -s "$tgz" ]] || return 1
  # Refuse archives with unsafe members before extracting (defence-in-depth even
  # though GitHub's generated archives are well-formed): absolute paths or `..`.
  if tar -tzf "$tgz" 2>/dev/null | grep -qE '^/|(^|/)\.\.(/|$)'; then
    warn "release archive contains unsafe path entries — refusing to extract"
    return 1
  fi
  # Extract into a fresh subdir, validate completeness there, then copy to $dest.
  local x="$tmpd/x"
  mkdir -p "$x"
  tar -xzf "$tgz" -C "$x" --strip-components=1 2>/dev/null || return 1
  source_looks_valid "$x" || return 1
  cp -R "$x/." "$dest/" 2>/dev/null || return 1
  source_looks_valid "$dest"
}

resolve_hos_source() {
  if $LOCAL_SOURCE; then
    HOS_SOURCE="$HOS_REPO_ROOT"
    HOS_REF="LOCAL (unvalidated working copy)"
    warn "Installing from the LOCAL working copy — this is NOT a validated release."
    warn "Omit --local to install the latest validated release instead."
    return
  fi

  # Release mode needs gh to resolve/verify the release — check it FIRST so the
  # failure is "gh missing → run the bootstrap", not a misleading "no release".
  if ! command -v gh &>/dev/null; then
    err "gh CLI is required to resolve a release (not found)."
    echo "      Run the machine bootstrap first:  $(dirname "$0")/hos_bootstrap.sh"
    echo "      …or install a local dev copy:      $0 --local${TARGET_REPO:+ $TARGET_REPO}"
    exit 1
  fi

  local ref="$RELEASE_REF"
  if [[ -z "$ref" ]]; then            # default: the latest PUBLISHED GitHub release
    ref="$(gh release view --repo "$HOS_REPO" --json tagName -q .tagName 2>/dev/null || true)"
  fi
  if [[ -z "$ref" ]]; then
    err "No published HOS release found to install."
    echo "    Either create a release (tag a validated commit + publish a GitHub release), or"
    echo "    install the unvalidated working copy:  $0 --local${TARGET_REPO:+ $TARGET_REPO}"
    exit 1
  fi

  # GATE: the ref must be a PUBLISHED release, not just any tag. This is what
  # makes "install from a validated release" real — a bare local/dev tag, or a
  # tag whose release was deleted because validation failed, must NOT install.
  # (gh is a required prerequisite, so this check is always available.)
  if ! gh release view "$ref" --repo "$HOS_REPO" &>/dev/null; then
    err "'$ref' is not a published GitHub release of $HOS_REPO."
    echo "    Only published (validated) releases install. Use --release <published-tag>, or --local for dev."
    exit 1
  fi
  HOS_REF="$ref"

  if $DRY_RUN; then
    HOS_SOURCE="$HOS_REPO_ROOT"   # dry-run shows file ops against the local tree
    dry_run "Would fetch HOS release $ref from $HOS_REPO and install from it"
    return
  fi

  HOS_SOURCE="$(mktemp -d "${TMPDIR:-/tmp}/hos-release.XXXXXX")"
  CLEANUP_DIRS+=("$HOS_SOURCE")
  info "Fetching HOS release $ref …"

  # Fast path: export the published release's tag from a local clone (offline-ok).
  # Only taken because the ref is confirmed published above. No `|| true` masking —
  # a partial extraction is caught by source_looks_valid and falls through to the
  # authoritative tarball.
  if git -C "$HOS_REPO_ROOT" rev-parse --git-dir &>/dev/null; then
    git -C "$HOS_REPO_ROOT" fetch --tags --quiet origin 2>/dev/null || true
    if git -C "$HOS_REPO_ROOT" rev-parse -q --verify "refs/tags/${ref}" &>/dev/null; then
      git -C "$HOS_REPO_ROOT" archive --format=tar "$ref" 2>/dev/null | tar -x -C "$HOS_SOURCE" 2>/dev/null || true
    fi
  fi
  if ! source_looks_valid "$HOS_SOURCE"; then
    rm -rf "${HOS_SOURCE:?}/." 2>/dev/null || true   # clear any partial export
    fetch_release_tarball "$ref" "$HOS_SOURCE" || {
      err "Could not fetch a complete release $ref from $HOS_REPO (gh/curl failed, or the archive was incomplete)."
      echo "    Check the release exists, or install the working copy with --local."
      exit 1
    }
  fi
  source_looks_valid "$HOS_SOURCE" || { err "Staged release source is incomplete (missing framework sentinels) — refusing to install."; exit 1; }
  ok "Release $ref staged for install"
}

resolve_hos_source

# ── Version-skip detection (REQ-U-01/U-02/U-03, #238) ────────────────────────
# Only relevant for upgrades (existing .hos-release) and non-local installs.
# Fresh installs (no .hos-release) skip the adjacency gate entirely — there is
# no prior version to be adjacent to.  --full bypasses the adjacency hard-stop.
INSTALLED_TAG=""
[[ -f "${TARGET_REPO}/.hos-release" ]] && INSTALLED_TAG="$(tr -d '[:space:]' < "${TARGET_REPO}/.hos-release")"

if [[ -n "$INSTALLED_TAG" ]] && ! $LOCAL_SOURCE && ! $FULL; then
  # Determine the target tag being installed.
  _install_tag="$RELEASE_REF"
  if [[ -z "$_install_tag" ]]; then
    _install_tag="$(gh release view --repo "$HOS_REPO" --json tagName -q .tagName 2>/dev/null || true)"
  fi

  if [[ -n "$_install_tag" && "$INSTALLED_TAG" != "$_install_tag" ]]; then
    # Fetch the ordered release list (newest-first, non-draft only).
    _releases_json="$(gh api "repos/${HOS_REPO}/releases" \
      --jq '[.[] | select(.draft==false) | .tag_name]' 2>/dev/null)" || _releases_json=""

    if [[ -z "$_releases_json" || "$_releases_json" == "null" || "$_releases_json" == "[]" ]]; then
      # Cannot verify upgrade sequence — network or API failure.
      err "cannot verify upgrade sequence — network required (could not fetch release list from ${HOS_REPO})"
      err "To proceed without the adjacency check: re-run with --full"
      exit 1
    fi

    # Find indices of installed and target in the releases list.
    _skip_result="$(python3 - "$_releases_json" "$INSTALLED_TAG" "$_install_tag" <<'PYEOF'
import json, sys
releases = json.loads(sys.argv[1])   # newest-first
installed = sys.argv[2]
target    = sys.argv[3]
try:
    idx_target    = releases.index(target)
    idx_installed = releases.index(installed)
except ValueError as e:
    # One of the tags not found in the release list — treat as non-sequential.
    print("NOT_FOUND:" + str(e))
    sys.exit(0)
# Sequential: installed is immediately after target in newest-first list,
# i.e. installed == releases[idx_target + 1].
if idx_installed == idx_target + 1:
    print("OK")
else:
    # Skipped versions are between target (exclusive) and installed (exclusive)
    # in newest-first order — i.e. releases[idx_target+1 : idx_installed].
    skipped = releases[idx_target + 1 : idx_installed]
    print("SKIP:" + ",".join(skipped))
PYEOF
    )"

    case "$_skip_result" in
      OK)
        # Sequential upgrade — proceed normally.
        ;;
      NOT_FOUND:*)
        warn "Version-skip check: could not find '$INSTALLED_TAG' or '$_install_tag' in the release list — proceeding (treat as non-sequential upgrade at your risk)."
        warn "Re-run with --full to make this explicit."
        ;;
      SKIP:*)
        _skipped="${_skip_result#SKIP:}"
        _skipped_display="${_skipped//,/, }"
        # Build intermediate install command lines (oldest skipped first).
        _inter_cmds=""
        IFS=',' read -ra _sv <<< "$_skipped"
        for _v in "${_sv[@]}"; do
          _inter_cmds+="        ./bootstrap/hos_install.sh --release ${_v} ${TARGET_REPO}"$'\n'
        done
        _inter_cmds+="        ./bootstrap/hos_install.sh --release ${_install_tag} ${TARGET_REPO}"

        echo ""
        err "ERROR: version-skip detected."
        echo "  Installed: ${INSTALLED_TAG}"
        echo "  Target:    ${_install_tag}"
        echo "  Skipped:   ${_skipped_display}"
        echo ""
        echo "  A non-sequential upgrade risks a content-incomplete install."
        echo "  Supported paths:"
        echo "    (a) Re-run with --full to install ${_install_tag} wholesale"
        echo "        (overwrites all CORE and PACK regions; PROJECT regions are preserved)."
        echo "    (b) Apply each intermediate version in sequence:"
        printf '%s' "$_inter_cmds"
        echo ""
        echo "  Run with --full to proceed if you understand the implications."
        exit 1
        ;;
    esac
  fi
fi

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
# Use cp_file for CONSUMER-owned files that should not be silently overwritten.
# Use cp_framework_file for HOS-owned (WHOLE) files that must always be refreshed
# on upgrade — the whole point of a framework install (#351).
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
  run mkdir -p "$(dirname "$dst")"
  run cp "$src" "$dst"
  # chmod +x only sensible for shell scripts; harmless on others, suppress noise
  case "$dst" in *.sh) run chmod +x "$dst" 2>/dev/null || true ;; esac
  $FORCE && ok "$label (updated)" || ok "$label"
}

# ── Helper: copy a framework-owned file — always overwrites on upgrade (#351) ──
# Framework files (AGENTS.md, OVERSIGHT-CONTRACT.md, runner scripts, etc.) are
# HOS-owned WHOLE files. Overwriting them on upgrade IS the intended behaviour;
# skipping them defeats the purpose of running an upgrade. --force is NOT
# required. Consumer PROJECT files (step-manifest.yaml, config.sh) must NEVER
# use this helper — they stay with cp_file or their own explicit guard.
cp_framework_file() {
  local src="$1" dst="$2" label="${3:-}"
  [[ -z "$label" ]] && label="$(basename "$dst")"
  if [[ ! -f "$src" ]]; then
    warn "Source not found: $src — skipping $label"
    return
  fi
  run mkdir -p "$(dirname "$dst")"
  run cp "$src" "$dst"
  case "$dst" in *.sh) run chmod +x "$dst" 2>/dev/null || true ;; esac
  ok "$label (framework — updated)"
}

# ── Helper: ensure line present in file (append if missing) ───────────────────
ensure_line() {
  local file="$1" line="$2"
  local label="${3:-$line}"
  if [[ -f "$file" ]] && grep -qF "$line" "$file" 2>/dev/null; then
    skip ".gitignore: $label already present"
  else
    # redirection — inline the dry-run check rather than route through run()
    if $DRY_RUN; then dry_run "echo $(printf '%q' "$line") >> $file"; else printf '%s\n' "$line" >> "$file"; fi
    ok ".gitignore: added $label"
  fi
}

# ── Helper: ensure line NOT present (warn if it is) ───────────────────────────
ensure_not_ignored() {
  local file="$1" line="$2"
  local label="${3:-$line}"
  # grep -v '^#' strips comment lines before searching — avoids false positives
  if [[ -f "$file" ]] && grep -v '^#' "$file" 2>/dev/null | grep -qF "$line"; then
    warn ".gitignore has '$line' — $label should be committed, not ignored"
    warn "Remove that line from $file"
  fi
}

# ── Install-via-PR: apply the upgrade on a branch for an auditable, reversible artifact (#193) ──
# When eligible (a clean git repo with an 'origin' remote + gh), create a branch
# BEFORE scaffolding so all changes land there; we commit + open a PR after, and
# return the consumer to their original branch. Degrades gracefully to in-place
# when not eligible (fresh repo, no remote, dirty tree). --pr requires it; --no-pr
# forces in-place.
PR_ACTIVE=false
PR_ORIG_BRANCH=""
PR_BRANCH=""
if [[ "$PR_MODE" != "off" ]] && ! $DRY_RUN; then
  _pr_ok=true; _pr_why=""
  git -C "$TARGET_REPO" rev-parse --git-dir >/dev/null 2>&1 || { _pr_ok=false; _pr_why="not a git repo"; }
  $_pr_ok && [[ -n "$(git -C "$TARGET_REPO" status --porcelain 2>/dev/null)" ]] && { _pr_ok=false; _pr_why="working tree not clean (commit or stash first)"; }
  $_pr_ok && ! git -C "$TARGET_REPO" remote get-url origin >/dev/null 2>&1 && { _pr_ok=false; _pr_why="no 'origin' remote"; }
  $_pr_ok && ! command -v gh >/dev/null 2>&1 && { _pr_ok=false; _pr_why="gh not available"; }
  if $_pr_ok; then
    PR_ORIG_BRANCH="$(git -C "$TARGET_REPO" symbolic-ref --short HEAD 2>/dev/null || true)"
    [[ -z "$PR_ORIG_BRANCH" ]] && { _pr_ok=false; _pr_why="detached HEAD"; }
  fi
  if $_pr_ok; then
    _slug="$(printf '%s' "$HOS_REF" | tr -cs 'A-Za-z0-9._-' '-' | sed 's/^-*//; s/-*$//')"
    PR_BRANCH="hos-upgrade/${_slug:-update}"
    if git -C "$TARGET_REPO" checkout -b "$PR_BRANCH" >/dev/null 2>&1; then
      PR_ACTIVE=true
      header "Install-via-PR"
      info "Applying the upgrade on branch '$PR_BRANCH' (was on '$PR_ORIG_BRANCH') — it'll become a PR you review."
    elif [[ "$PR_MODE" == "on" ]]; then
      # --pr means PR-or-nothing. A branch-creation failure must NOT silently
      # degrade to an in-place upgrade of the consumer's tree (#272). Hard-stop
      # here, BEFORE any scaffolding — nothing is written.
      err "--pr requested but branch '$PR_BRANCH' could not be created (it may already exist)."
      err "Refusing to fall back to an in-place upgrade — nothing was changed."
      err "Delete or rename the existing branch and retry, or use --no-pr to install in place."
      exit 1
    else
      warn "Could not create branch '$PR_BRANCH' — applying in place."
    fi
  elif [[ "$PR_MODE" == "on" ]]; then
    # Eligibility failed under an explicit --pr. fail() does NOT exit — it only
    # records an error the end-of-run check reports AFTER the in-place scaffolding
    # has already mutated the tree (#272). Hard-stop here so nothing is written.
    err "--pr requested but not possible: $_pr_why."
    err "Refusing to fall back to an in-place upgrade — nothing was changed."
    err "Resolve the above (commit/stash, add an 'origin' remote, install gh, etc.), or use --no-pr to install in place deliberately."
    exit 1
  else
    info "Install-via-PR not used ($_pr_why) — applying in place. (Pass --pr to require it.)"
  fi
fi

# #274: --pr under --dry-run is silently inert (the PR block above is gated on
# `! $DRY_RUN`). Say so, so the operator doesn't read the in-place-looking dry-run
# output as evidence that --pr was honored.
if [[ "$PR_MODE" == "on" ]] && $DRY_RUN; then
  warn "--pr + --dry-run: PR-mode is NOT simulated in a dry run — no branch or PR is created, and the preview below reflects an in-place apply. Re-run without --dry-run to produce the PR."
fi

# ── .gitignore ─────────────────────────────────────────────────────────────────
echo ""
info ".gitignore"
GITIGNORE="$TARGET_REPO/.gitignore"
[[ -f "$GITIGNORE" ]] || run touch "$GITIGNORE"

ensure_line     "$GITIGNORE" ".claudetmp/"      ".claudetmp/ (agent ephemeral state)"
ensure_line     "$GITIGNORE" ".ai-local/"     ".ai-local/ (SQC salt + panel cache)"
ensure_line     "$GITIGNORE" "*.salt"         "*.salt (sampling keys)"
ensure_line     "$GITIGNORE" ".hos-brownfield/" ".hos-brownfield/ (brownfield migration scratch — not committed, #275)"
ensure_not_ignored "$GITIGNORE" "audit/"     "audit/ (committed audit trail)"
ensure_not_ignored "$GITIGNORE" "AGENTS.md"  "AGENTS.md (governance protocol)"
ensure_not_ignored "$GITIGNORE" "prompts/"   "prompts/ (prompt artifacts)"

# ── .ai-local/ — per-PROJECT runtime (SQC sampling salt) ──────────────────────
# The salt is project state: run_redteam_sample.sh uses it to deterministically
# select which LOW/MEDIUM PRs get a red-team audit. It must persist per project
# and never be regenerated (regenerating reshuffles the sampling history).
echo ""
info ".ai-local/ — per-project runtime (SQC sampling salt)"
run mkdir -p "$TARGET_REPO/.ai-local/panel"
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
run mkdir -p "$TARGET_REPO/.claude/agents"

# Canonical consumer agent set — the SINGLE SOURCE OF TRUTH shared with the
# .hos-manifest enumeration below, so the install and the manifest can never
# drift (HOS#225: the old hardcoded 6-agent loop fell behind as agents were added,
# while the manifest `find`-ed all of them, declaring agents that were never
# installed). Falls back to the full set if the list isn't in this release.
_agents_list="$HOS_SOURCE/scripts/framework/consumer_agents.txt"
_consumer_agents=()
if [[ -f "$_agents_list" ]]; then
  while IFS= read -r _a; do
    _a="${_a%%#*}"; _a="$(echo "$_a" | xargs || true)"
    [[ -n "$_a" ]] && _consumer_agents+=("$_a")
  done < "$_agents_list"
else
  warn "consumer_agents.txt not in release — using built-in core agent set"
  _consumer_agents=(risk-assessor dep-mapper risk-historian oversight-evaluator \
    oversight-orchestrator spec-red-team prompt-fidelity ops-designer ops-reviewer \
    reliability-reviewer post-change-sweep ux-designer)
fi
# ── Placeholder substitution SETUP (#87 / #99 / #110) — runs BEFORE the agent flow ──
# Install-time placeholders are DECLARED in scripts/framework/placeholders.manifest
# (NOT guessed — agent prompts also contain runtime tokens like {N}/{HEAD_SHA}
# and JSON examples like {role} that must NOT be touched). On EVERY install we:
#   1. ensure the project's config.sh has a key for each declared placeholder,
#      APPENDING missing ones non-destructively (existing values never touched) —
#      so each framework upgrade keeps config complete without clobbering (#110);
#   2. substitute every declared placeholder from env override > config.sh; a
#      value we don't have is left as its literal token, never blanked, so a
#      partial config can't corrupt an agent (#99). perl: cross-platform (D27).
#
# v0.3.0 (TD D6): substitution is the ONLY substitution engine and runs over the
# STAGED template BEFORE regions.py plans it — regions.py never substitutes. So
# we build the perl arg array here and apply it per-staged-template inside the
# Phase-A/B agent flow below, instead of in-place over installed files.
_manifest="$HOS_SOURCE/scripts/framework/placeholders.manifest"
_subst_config="$TARGET_REPO/scripts/framework/config.sh"
_perl_args=()        # populated below; empty ⇒ nothing to substitute
_names=()
_appended=()
if [[ ! -f "$_manifest" ]]; then
  warn "placeholders.manifest not in release — skipping substitution (run scripts/framework/install.sh)"
else
  # Declared placeholder names (tab-separated NAME<TAB>description; skip # and blanks).
  while IFS=$'\t' read -r _name _rest; do
    [[ -z "$_name" || "$_name" == \#* ]] && continue
    _names+=("$_name")
  done < "$_manifest"

  # Ensure config.sh exists and carries a key for every declared placeholder.
  # Append missing keys (empty), non-destructively — never rewrite existing lines.
  if ! $DRY_RUN; then
    run mkdir -p "$(dirname "$_subst_config")"
    [[ -f "$_subst_config" ]] || printf '# HOS project config — values substituted into .claude/agents/*.md\n' > "$_subst_config"
  fi
  for _n in "${_names[@]+"${_names[@]}"}"; do
    if [[ -f "$_subst_config" ]] && grep -qE "^${_n}=" "$_subst_config" 2>/dev/null; then continue; fi
    if $DRY_RUN; then dry_run "Would append ${_n}=\"\" to config.sh"; else printf '%s=""\n' "$_n" >> "$_subst_config"; fi
    _appended+=("$_n")
  done

  # Build perl substitutions: env override > config.sh value. Missing → leave token.
  for _n in "${_names[@]+"${_names[@]}"}"; do
    _val="${!_n:-}"
    if [[ -z "$_val" && -f "$_subst_config" ]]; then
      _val=$(grep -E "^${_n}=" "$_subst_config" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//')
    fi
    if [[ -z "$_val" ]]; then continue; fi
    _val=${_val//|/\\|}              # escape the perl s||| delimiter
    _perl_args+=(-e "s|\{${_n}\}|${_val}|g;")
  done
fi

# _substitute_into <src> <dst>: copy the HOS template <src> to <dst>, then apply
# the declared placeholder substitution IN PLACE on <dst> (the staged template).
# This is the D6 substitution boundary — regions.py is handed already-substituted
# bytes and never substitutes itself. No-op copy if perl/args unavailable.
_substitute_into() {
  local _src="$1" _dst="$2"
  cp "$_src" "$_dst"
  if [[ ${#_perl_args[@]} -gt 0 ]] && command -v perl >/dev/null 2>&1; then
    perl -i -p "${_perl_args[@]}" "$_dst" 2>/dev/null || true
  fi
}

# ── Brownfield helpers (#275) ──────────────────────────────────────────────────
# These functions implement the brownfield migration flow specified in the
# TECHNICAL-DESIGN-consumer-pack.md §1.2–1.5, §3.2–3.5.

# Detect brownfield state: returns 0 (true) if the repo has flat agent files
# but no .hos-manifest. Called early, before the agent-install phase.
_brownfield_detect() {
  # Brownfield = ! has_manifest AND has_agents AND any_flat
  [[ -f "$TARGET_REPO/.hos-manifest" ]] && return 1
  local _agents_d="$TARGET_REPO/.claude/agents"
  [[ -d "$_agents_d" ]] || return 1
  # Check that at least one .md exists
  local _any_md
  _any_md="$(ls "$_agents_d"/*.md 2>/dev/null | head -1 || true)"
  [[ -z "$_any_md" ]] && return 1
  # Check that at least one has no <!-- HOS: marker
  local _flat
  _flat="$(grep -rL '<!-- HOS:' "$_agents_d/"*.md 2>/dev/null | head -1 || true)"
  [[ -n "$_flat" ]] && return 0
  return 1
}

# Run the Python brownfield classifier on all flat agent files.
# Writes .hos-brownfield/<slug>.json and the report txt.
_brownfield_migrate() {
  local _BROWNFIELD_PY="$HOS_SOURCE/scripts/oversight/validators/brownfield.py"
  if [[ ! -f "$_BROWNFIELD_PY" ]]; then
    err "brownfield.py not found in HOS source — cannot perform brownfield migration"
    exit 1
  fi

  local _ts; _ts="$(date +%Y%m%d-%H%M%S)"
  local _report_dir="$TARGET_REPO/.claudetmp"
  local _report_file="$_report_dir/brownfield-${_ts}-report.txt"
  local _brownfield_dir="$TARGET_REPO/.hos-brownfield"

  if $DRY_RUN; then
    dry_run "Would run brownfield.py migrate $TARGET_REPO"
    dry_run "Would write .claudetmp/brownfield-${_ts}-report.txt"
    return
  fi

  mkdir -p "$_report_dir" "$_brownfield_dir"

  info "[brownfield] Classifying flat agent files…"

  # Run the Python classifier on all flat agent files
  local _agents_d="$TARGET_REPO/.claude/agents"
  local _any_classified=false
  local _n_total=0 _n_marked=0 _n_flat=0 _n_project=0 _n_stock=0

  for _agent_md in "$_agents_d"/*.md; do
    [[ -f "$_agent_md" ]] || continue
    _n_total=$((_n_total + 1))
    local _slug; _slug="$(basename "$_agent_md" .md)"

    # Skip already-marked files (REQ-B-04 / AC-B-08)
    if grep -q '<!-- HOS:' "$_agent_md" 2>/dev/null; then
      _n_marked=$((_n_marked + 1))
      continue
    fi

    _n_flat=$((_n_flat + 1))
    _any_classified=true

    # Resolve the CORE template for this slug
    local _core_tmpl=""
    if [[ -f "$HOS_SOURCE/.claude/agents/${_slug}.md" ]]; then
      _core_tmpl="$HOS_SOURCE/.claude/agents/${_slug}.md"
    fi

    local _json_out="$_brownfield_dir/${_slug}.json"
    local _classify_args=("$_agent_md")
    [[ -n "$_core_tmpl" ]] && _classify_args+=("$_core_tmpl")
    _classify_args+=(--json-out "$_json_out")

    # Classify: human-readable to report file, JSON to .hos-brownfield/
    if ! python3 "$_BROWNFIELD_PY" classify "${_classify_args[@]}" >> "$_report_file" 2>&1; then
      warn "brownfield classify failed for ${_slug} — treating as project_custom"
    fi

    # Count PROJECT/STOCK from resulting JSON
    if [[ -f "$_json_out" ]]; then
      local _n_pc; _n_pc="$(python3 -c "import json; d=json.load(open('$_json_out')); print(len(d.get('project_custom',[])+d.get('mixed',[])))" 2>/dev/null || echo 0)"
      local _n_sc; _n_sc="$(python3 -c "import json; d=json.load(open('$_json_out')); print(len(d.get('stock_core',[])))" 2>/dev/null || echo 0)"
      [[ "$_n_pc" -gt 0 ]] && _n_project=$((_n_project + 1))
      [[ "$_n_sc" -gt 0 ]] && _n_stock=$((_n_stock + 1))
    fi
  done

  # ── Scaffold-pack offer (§3.1) ────────────────────────────────────────────
  if [[ -n "$SCAFFOLD_PACK" ]] && [[ "$_n_project" -ge 3 ]]; then
    _brownfield_scaffold_pack "$SCAFFOLD_PACK"
  elif [[ -z "$SCAFFOLD_PACK" && "$_n_project" -ge 3 ]]; then
    if [[ -t 0 ]]; then
      echo ""
      info "[brownfield] Found PROJECT customizations in $_n_project agents."
      info "  These could be extracted into a consumer pack for cleaner versioning."
      printf "  Scaffold a consumer pack? (recommended for N >= 3) [y/N]: "
      read -r _scaffold_ans </dev/tty || _scaffold_ans="N"
      if [[ "${_scaffold_ans:-N}" =~ ^[Yy]$ ]]; then
        local _slug_input=""
        while [[ ! "$_slug_input" =~ ^[a-z][a-z0-9-]*$ ]]; do
          printf "  Pack slug [a-z][a-z0-9-]*: "
          read -r _slug_input </dev/tty || _slug_input=""
        done
        _brownfield_scaffold_pack "$_slug_input"
      fi
    fi
    # Non-interactive: skip scaffolding silently (REQ-CS-01)
  fi

  # ── Synthetic baseline construction (§1.4) ───────────────────────────────
  # For each flat file, build a CORE+PROJECT-marked disk image so the standard
  # three-way merge can proceed. Flat files with no CORE template get PROJECT-only.
  _REGIONS_PY_BF="$HOS_SOURCE/scripts/oversight/validators/regions.py"
  for _agent_md in "$_agents_d"/*.md; do
    [[ -f "$_agent_md" ]] || continue
    grep -q '<!-- HOS:' "$_agent_md" 2>/dev/null && continue  # already marked
    local _slug; _slug="$(basename "$_agent_md" .md)"
    local _json_out="$_brownfield_dir/${_slug}.json"

    if [[ ! -f "$_json_out" ]]; then
      warn "[brownfield] Missing JSON for ${_slug} — skipping synthetic baseline for this file"
      continue
    fi

    # Build the PROJECT region body = concatenated PROJECT_CUSTOMIZATION section lines
    local _project_body
    _project_body="$(python3 - "$_json_out" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
parts = []
for s in data.get("sections", []):
    if s.get("classification") == "PROJECT_CUSTOMIZATION":
        lines = s.get("lines", [])
        parts.extend(lines)
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n")
        parts.append("\n")
print("".join(parts).rstrip("\n"), end="")
PYEOF
)"

    # Write the marked disk image: migrate the flat file first, then inject PROJECT body
    if [[ -f "$_REGIONS_PY_BF" ]]; then
      local _marked_tmp; _marked_tmp="$(mktemp "${TMPDIR:-/tmp}/hos-bf.XXXXXX")"
      python3 "$_REGIONS_PY_BF" migrate "$_agent_md" --ships yes > "$_marked_tmp" 2>/dev/null || true
      if [[ -s "$_marked_tmp" ]]; then
        cp "$_marked_tmp" "$_agent_md"
        # If there is PROJECT content, inject it into the PROJECT region
        if [[ -n "$_project_body" ]]; then
          python3 - "$_agent_md" "$_project_body" <<'PYEOF'
import sys, re
path = sys.argv[1]
body = sys.argv[2]
content = open(path).read()
# Replace empty PROJECT region with the classified content
pattern = r'(<!-- HOS:PROJECT:START -->)\s*(<!-- HOS:PROJECT:END -->)'
replacement = f'<!-- HOS:PROJECT:START -->\n{body}\n<!-- HOS:PROJECT:END -->'
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
open(path, 'w').write(new_content)
PYEOF
        fi
      fi
      rm -f "$_marked_tmp"
    fi
  done

  # ── Summary (REQ-B-07) ───────────────────────────────────────────────────
  echo ""
  info "[brownfield] Migration complete."
  info "  Agents processed:          $_n_total"
  info "  Already-marked (skipped):  $_n_marked"
  info "  Flat files classified:     $_n_flat"
  info "  PROJECT regions preserved: $_n_project"
  info "  Stock CORE overwritten:    $_n_stock"
  info "  Classification report:     .claudetmp/brownfield-${_ts}-report.txt"
  echo ""
}

# Scaffold a consumer pack from .hos-brownfield/ classification JSON.
# Delegates to the Python module for the actual file generation.
_brownfield_scaffold_pack() {
  local _slug="$1"
  local _BROWNFIELD_PY="$HOS_SOURCE/scripts/oversight/validators/brownfield.py"

  # Slug validation (REQ-CS-02)
  if [[ ! "$_slug" =~ ^[a-z][a-z0-9-]*$ ]]; then
    err "ERROR: invalid pack slug '$_slug' — must match ^[a-z][a-z0-9-]*$"
    exit 2
  fi

  # Collision check: reject slugs that collide with HOS built-in pack names
  if [[ -d "$HOS_SOURCE/packs/$_slug" ]]; then
    err "ERROR: '$_slug' conflicts with a HOS built-in pack name. Choose a different slug."
    exit 2
  fi

  if $DRY_RUN; then
    dry_run "Would scaffold packs/${_slug}/ from brownfield classification"
    return
  fi

  if ! python3 "$_BROWNFIELD_PY" scaffold-pack "$TARGET_REPO" "$_slug"; then
    warn "[brownfield] scaffold-pack failed for slug '$_slug'"
    return
  fi

  # Count body files written
  local _n_files; _n_files="$(ls "$TARGET_REPO/packs/${_slug}/"*.md 2>/dev/null | wc -l || echo 0)"

  info "[brownfield] Consumer pack scaffolded at packs/${_slug}/."
  info "  To apply it, re-run the installer with --pack ${_slug} (and any other packs)."
  info "  Example: hos_install.sh --pack django --pack ${_slug} [DIR]"
}

# Resolve a pack name to its directory: consumer-local packs/ first, then HOS-shipped.
# REQ-CS-06: consumer-local resolution applies to every --pack resolution.
# Prints the absolute directory path to stdout (only the path, no decoration);
# logs the resolution source to stderr (so callers can capture stdout cleanly).
# Returns 0 on success, 1 if not found.
_resolve_pack_dir() {
  local _n="$1"
  if [[ -d "$TARGET_REPO/packs/$_n" ]]; then
    echo -e "  ${CYAN}→${RESET}  [pack] Resolved $_n from consumer-local packs/ (not HOS-shipped)" >&2
    printf '%s' "$TARGET_REPO/packs/$_n"; return 0
  elif [[ -d "$HOS_SOURCE/packs/$_n" ]]; then
    echo -e "  ${CYAN}→${RESET}  [pack] Resolved $_n from HOS source (HOS-shipped)" >&2
    printf '%s' "$HOS_SOURCE/packs/$_n"; return 0
  fi
  return 1
}

# ── Brownfield-state detection and pre-flight handling (#275) ─────────────────
# Called once after all brownfield helper functions are defined, after TARGET_REPO
# is resolved, and before the agent-install phase (§1.2 contract). With
# --brownfield: run the migration so the standard three-way merge can proceed.
if _brownfield_detect; then
  if $BROWNFIELD; then
    # §1.5: classify + produce synthetic baseline, then let the merge proceed
    _brownfield_migrate
    # After migration the .hos-manifest exists (written by migration) → the standard
    # merge treats the now-marked files correctly (CORE refreshed, PROJECT preserved).
  else
    # §1.3: actionable pre-flight error
    err "This looks like a pre-region-model (brownfield) repo:"
    err "  no .hos-manifest, and flat agent files in .claude/agents/."
    err "  The standard installer cannot three-way-merge without a recorded baseline."
    err "  Re-run with --brownfield to classify your flat files and migrate safely"
    err "  (or --squash to overwrite all CORE/PACK regions — destructive, see --help)."
    exit 4
  fi
elif $BROWNFIELD; then
  # §1.6: --brownfield on a non-brownfield repo → no-op WARN
  warn "[brownfield] --brownfield passed but this repo is not brownfield"
  warn "  (.hos-manifest present or all agent files already marked) — proceeding with the standard merge."
fi

# ── Pack resolution (ADR-031 Decision 1) ─────────────────────────────────────
_resolved_packs=()

# (R1) Source of truth: flags win; else config.sh PACK= (the upgrade read-path).
#      CRITICAL: --no-pack must WIN over a recorded config.sh PACK= — gate the
#      config read on `! $NO_PACK`. Without this gate, a flagless `--no-pack`
#      install reads the recorded PACK=django into _resolved_packs, R2's
#      "${#_resolved_packs[@]} -eq 0" guard is then false, the $NO_PACK arm is
#      never reached, and --no-pack is a SILENT no-op (B1). --no-pack is an
#      explicit operator opt-out; it must override the recorded choice.
if [[ ${#_packs[@]} -gt 0 ]]; then
    _resolved_packs=("${_packs[@]}")               # from --pack (precedence 1)
elif ! $NO_PACK && [[ -f "$_subst_config" ]]; then   # --no-pack suppresses the config read
    # grep returns 1 when no PACK= line exists — mask with || true so set -e
    # does not abort the script on a legitimately absent PACK key.
    _cfg_pack="$(grep -E '^PACK=' "$_subst_config" 2>/dev/null | head -1 \
                  | cut -d= -f2- | sed 's/^"//; s/"$//' || true)"
    [[ -n "$_cfg_pack" ]] && _resolved_packs=("$_cfg_pack")   # precedence 2 (single-value)
fi
# NB: v0.3.0 reads config.sh PACK= as a SINGLE value (ADR-031 "open seams"); the
# space-split multi-value form is a noted-not-built seam. Repeated --pack is the
# only wired multi-pack path.

# (R2) No pack resolved → the no-pack decision tree (ADR-031 §1.3).
if [[ ${#_resolved_packs[@]} -eq 0 ]]; then
    if $NO_PACK; then
        # explicit opt-out → core only, #237 WARN (bare core IS a real install).
        warn "installing bare core with no pack — core enforces generic best"
        warn "practices but is shallow; install a pack before first real use"
        # (R2a) --no-pack must also CLEAR a recorded config.sh PACK= (B1 follow-on).
        # Else the NEXT flagless install reads the stale PACK= and silently re-adds
        # the pack the operator just stripped — a footgun. Remove the row so the
        # recorded state matches the installed state (bare core). The on-disk PACK
        # region is then DROPped by the existing removed-region sweep (§4.2).
        if [[ -f "$_subst_config" ]] && grep -qE '^PACK=' "$_subst_config" 2>/dev/null; then
            _old_pack="$(grep -E '^PACK=' "$_subst_config" | head -1 | cut -d= -f2- \
                          | sed 's/^"//; s/"$//' || true)"
            if $DRY_RUN; then
                dry_run "Would clear config.sh PACK=\"$_old_pack\" (--no-pack strip)"
            else
                perl -i -ne 'print unless /^PACK=/' "$_subst_config"
            fi
            warn "config.sh PACK cleared: $_old_pack → (none) — pack stripped (see removed-region sweep)"
        fi
    elif [[ -t 0 ]]; then
        # interactive, no --no-pack → S1 hard default: don't ship core-only by accident.
        err "no PACK selected — pass --pack <name> (e.g. --pack django), set PACK="
        err "in scripts/framework/config.sh, or pass --no-pack to install the bare"
        err "core deliberately"
        exit 1
    else
        # non-interactive / CI, no --no-pack → CI must be explicit (error path).
        err "no PACK selected and not interactive — CI must pass --pack <name> or"
        err "--no-pack explicitly"
        exit 1
    fi
fi

# (R2b) Slug-validate every resolved pack name before R3/R5 use it.
#       A name that does not match [a-z0-9][a-z0-9-]* must never reach the
#       directory-existence check or the `perl -i -pe "s|^PACK=...|PACK=\"$_pk\"|"`
#       substitution — a '|' in the name would break the perl delimiter.
#       Covers both the --pack flag path and the config.sh PACK= read path.
for _p in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
    if [[ ! "$_p" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
        err "invalid pack name '$_p' — must match [a-z0-9][a-z0-9-]* (lowercase, start alnum, then alnum or hyphen)"
        exit 1
    fi
done

# (R3) Validate each resolved pack exists (consumer-local or HOS-shipped).
#      Uses _resolve_pack_dir (REQ-CS-06): consumer-local packs/ wins over HOS-shipped.
#      Unknown pack (neither location) → hard error, fail-closed.
for _p in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
    _pack_dir="$(_resolve_pack_dir "$_p")" || {
        err "unknown pack '$_p' — no packs/$_p/ in the consumer repo or HOS source ($HOS_REF)"
        err "available (HOS): $(cd "$HOS_SOURCE/packs" 2>/dev/null && ls -d */ 2>/dev/null \
              | tr -d / | tr '\n' ' ' || echo '(none)')"
        err "available (consumer): $(cd "$TARGET_REPO/packs" 2>/dev/null && ls -d */ 2>/dev/null \
              | tr -d / | tr '\n' ' ' || echo '(none)')"
        exit 1
    }
    # pack.toml name/dir sanity (ADR-031 §2.4; mismatch → WARN, not hard error —
    # directory name is authoritative; see TD-pack §6 flag #4).
    _declared="$(grep -E '^[[:space:]]*name[[:space:]]*=' \
                   "$_pack_dir/pack.toml" 2>/dev/null \
                 | head -1 | cut -d= -f2- \
                 | sed 's/[[:space:]]*//g; s/^"//; s/"$//; s/^'\''//; s/'\''$//' || true)"
    if [[ -n "$_declared" && "$_declared" != "$_p" ]]; then
        warn "packs/$_p/pack.toml declares name=\"$_declared\" but the directory is '$_p' — using '$_p'"
        warn "  fix: rename the directory to '$_declared', or correct name= in pack.toml to '$_p'"
    fi
done

# (R4) Multi-pack → permit, but WARN once (Decision 4 — untested composition).
if [[ ${#_resolved_packs[@]} -gt 1 ]]; then
    warn "multiple packs selected (${_resolved_packs[*]}) — multi-pack composition"
    warn "is UNTESTED in v0.3.0 (alphabetical order, no conflict resolution);"
    warn "single-pack is the supported path"
fi

# (R5) Record the choice for upgrade reuse (ADR-031 §1.2). Only when a SINGLE
#      pack came from --pack (config-as-source needs no rewrite). config.sh is
#      consumer-owned and append-only here — overwrite ONLY when PACK= differs.
if [[ ${#_packs[@]} -eq 1 ]]; then
    _pk="${_packs[0]}"
    if [[ ! -f "$_subst_config" ]]; then
        if $DRY_RUN; then dry_run "Would create config.sh with PACK=\"$_pk\""
        else mkdir -p "$(dirname "$_subst_config")"; printf 'PACK="%s"\n' "$_pk" >> "$_subst_config"; fi
    elif grep -qE '^PACK=' "$_subst_config" 2>/dev/null; then
        _cur="$(grep -E '^PACK=' "$_subst_config" | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//' || true)"
        if [[ "$_cur" != "$_pk" ]]; then
            if $DRY_RUN; then dry_run "Would update config.sh PACK=\"$_cur\" → \"$_pk\""
            else perl -i -pe "s|^PACK=.*|PACK=\"$_pk\"|" "$_subst_config"; fi
            warn "config.sh PACK changed: $_cur → $_pk (a pack switch — see removed-region sweep)"
        fi
    else
        if $DRY_RUN; then dry_run "Would append PACK=\"$_pk\" to config.sh"
        else printf 'PACK="%s"\n' "$_pk" >> "$_subst_config"; fi
    fi
fi

# ── .claude/agents/ — Phase A/B layered install (TD §4.5, §7.1–7.3) ───────────
# Per-agent two-phase flow (decide-all-then-act): for each consumer agent we
#   (A) stage + substitute the HOS template, migrate a flat disk file if needed,
#       and call `regions.py plan` (disk vs substituted-template vs prior
#       base-shas) — collecting each file's plan WITHOUT writing;
#   (B) only if NO file's plan is drift-blocked (or --squash consents) do we
#       write each file's composed bytes, then the schema-v2 manifest + release.
# A single drift hard-stop refuses the WHOLE upgrade and writes nothing (§4.3).
echo ""
info ".claude/agents/ — layered install (region merge)"

_REGIONS_PY="$HOS_SOURCE/scripts/oversight/validators/regions.py"
_PRIOR_MANIFEST="$TARGET_REPO/.hos-manifest"
# Is this a first install for the region model? No prior manifest at all.
_first_install=false
[[ ! -f "$_PRIOR_MANIFEST" ]] && _first_install=true

# Phase-A scratch: a temp dir holding each agent's staged template, composed
# output bytes, and manifest rows. Survives until Phase B writes from it.
_AGENT_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/hos-agents.XXXXXX")"
CLEANUP_DIRS+=("$_AGENT_STAGE")

# squash consent maps from BOTH --squash and --prune (the file-orphan symmetry,
# TD §4.5 review note: --prune is consent-to-drop for the removed-region sweep).
_squash_flag=()
if $SQUASH || $PRUNE; then _squash_flag=(--squash); fi

_planned_agents=()       # slugs that produced a writable plan (Phase B writes these)
_blocked_report=""       # aggregated per-file drift report (only set when blocked)
_any_blocked=false
_any_inject_fail=false   # B2: any inject-pack failure → pre-Phase-B abort (§2.4.1)
_any_plan_fail=false     # R-B2: any planning failure → pre-Phase-B abort (§2.4.1)

# ── Pack placeholder substitution helper (§3, #287) ──────────────────────────
# Substitutes {{TOKEN}} (double-brace) in the pack body file BEFORE injection.
# Deliberately distinct from the single-brace {NAME} engine (which runs before
# this, over staged templates). The two engines must never merge — different
# timing, different syntax, different scope (PACK-only for {{}}). (OQ-8)
#
# Reads the four pack-substitution keys from config.sh. If a key is absent or
# empty, leaves the literal {{TOKEN}} and prints a WARNING (AC-S-02).
# Never fails the install on a missing token.
_subst_pack_tokens() {
  local _file="$1" _agent="${2:-<unknown>}"
  local _config="${_subst_config:-$TARGET_REPO/scripts/framework/config.sh}"

  # Map of token names to their config.sh keys.
  local -a _tokens=("PROJECT_ROOT" "PROJECT_SETTINGS_MODULE" "PROJECT_TESTS_DIR" "PROJECT_PACKAGE")
  local _total_substituted=0
  local _any_warning=false

  for _tok in "${_tokens[@]}"; do
    # Read value from env (override) > config.sh.
    local _val="${!_tok:-}"
    if [[ -z "$_val" && -f "$_config" ]]; then
      _val="$(grep -E "^${_tok}=" "$_config" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//' || true)"
    fi

    if [[ -z "$_val" ]]; then
      # Only warn if the token actually appears in the body — no noise for unused tokens.
      if grep -qF "{{${_tok}}}" "$_file" 2>/dev/null; then
        echo "[pack-substitution] WARNING: token {{${_tok}}} has no value in config.sh — left literal in ${_agent}"
        _any_warning=true
      fi
      continue
    fi

    # Count occurrences before substitution for the confirmation log.
    local _count
    _count="$(grep -oF "{{${_tok}}}" "$_file" 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$_count" -gt 0 ]]; then
      # Use perl with $ENV to avoid interpolating the value into the regex/program
      # text — safe even when values contain special characters. (REQ-S-01)
      tok="$_tok" val="$_val" perl -i -pe 's/\{\{\Q$ENV{tok}\E\}\}/$ENV{val}/g' "$_file" 2>/dev/null || true
      _total_substituted=$(( _total_substituted + _count ))
    fi
  done

  if [[ "$_total_substituted" -gt 0 ]] && ! $_any_warning; then
    echo "[pack-substitution] ${_agent}: substituted ${_total_substituted} token(s)"
  fi
}

# Run a regions.py subcommand that has NO expected non-zero exit (migrate on a
# file already confirmed flat; base-shas read). Any non-zero is a CRASH, not a
# result — surface its stderr and FAIL CLOSED before Phase B writes anything
# (#276: a swallowed regions.py crash silently degrades a governance install —
# a region left flat, a raw copy used as the "disk" image, or empty base-shas —
# and the run still prints "Done"). stdout goes to $1 ("-" inherits). Exits 1 on
# crash; on success the caller continues normally.
_regions_strict() {  # _regions_strict <outfile|-> <args...>
  local _out="$1"; shift
  local _err _rc
  _err="$(mktemp "${TMPDIR:-/tmp}/hos-regions.XXXXXX")"
  if [[ "$_out" == "-" ]]; then
    python3 "$_REGIONS_PY" "$@" 2>"$_err"; _rc=$?
  else
    python3 "$_REGIONS_PY" "$@" >"$_out" 2>"$_err"; _rc=$?
  fi
  if [[ $_rc -ne 0 ]]; then
    echo "" >&2
    err "regions.py crashed (exit $_rc) — install aborted, nothing written (#276):"
    err "  call: regions.py $*"
    [[ -s "$_err" ]] && sed 's/^/    /' "$_err" >&2
    err "A regions.py failure means the composed agents and manifest cannot be trusted."
    err "Fix the cause (often a malformed region marker or pack body) and re-run."
    rm -f "$_err"
    exit 1
  fi
  rm -f "$_err"
}

if [[ ! -x "$(command -v python3)" ]]; then
  fail "python3 required for the region install but not found"
elif [[ ! -f "$_REGIONS_PY" ]]; then
  fail "regions.py missing from the HOS source ($_REGIONS_PY) — incomplete release"
else
  for agent in "${_consumer_agents[@]}"; do
    src="$HOS_SOURCE/.claude/agents/${agent}.md"
    dst="$TARGET_REPO/.claude/agents/${agent}.md"
    rel=".claude/agents/${agent}.md"
    if [[ ! -f "$src" ]]; then
      warn "Agent not found in HOS: ${agent}.md — skipping"
      continue
    fi
    # dep-mapper: don't overwrite a project-specific version unless --force.
    if [[ "$agent" == "dep-mapper" && -f "$dst" ]] && ! $FORCE; then
      skip "dep-mapper.md (project-specific version preserved — use --force to replace with generic)"
      continue
    fi

    # (A1) stage + substitute the template (D6 — substitute BEFORE plan).
    _stage="$_AGENT_STAGE/${agent}.tmpl.md"
    _substitute_into "$src" "$_stage"
    # Forward-compat: until the base agents are authored with markers (Phase
    # 0b/2, out of scope here), HOS templates are still FLAT. A flat template
    # would compose to nothing, so wrap it as CORE first (HOS-owned source →
    # CORE). Once templates ship markers this is a no-op (the grep skips it).
    if ! grep -q '<!-- HOS:' "$_stage" 2>/dev/null; then
      _stage_wrapped="$_AGENT_STAGE/${agent}.tmpl.wrapped.md"
      _regions_strict "$_stage_wrapped" migrate "$_stage" --ships yes   # #276: crash → abort, not a silently-unwrapped region
      mv "$_stage_wrapped" "$_stage"
    fi

    # (A1b) Pack injection (ADR-031 §3.1 step 4). For each selected pack that
    # deepens THIS agent (packs/<pack>/<agent>.md exists), inject its PACK:<pack>
    # region into the staged CORE template. compose() (inside inject-pack) re-sorts
    # alphabetically, so injection order is irrelevant. An agent with no pack file
    # stays CORE-only (the absence is the signal — D2.2). Placeholder-free bodies
    # are NEVER substituted (D6) — they are injected raw, post-substitution.
    # _resolve_pack_dir is called once per pack (B-4: never call it twice; it logs).
    for _pk in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
      _pk_dir="$(_resolve_pack_dir "$_pk")" || _pk_dir="$HOS_SOURCE/packs/$_pk"
      _body="$_pk_dir/${agent}.md"
      [[ -f "$_body" ]] || continue
      # (§3, #287) Stage the pack body to a temp copy and substitute {{TOKEN}}
      # placeholders BEFORE injection. PACK-scoped by construction (the body file
      # is 100% PACK content). Separate from the single-brace {NAME} engine.
      _body_sub="$_AGENT_STAGE/${agent}.${_pk}.body.md"
      cp "$_body" "$_body_sub"
      _subst_pack_tokens "$_body_sub" "${agent}.md"
      _inj_err="$_AGENT_STAGE/${agent}.inject.err"
      if ! python3 "$_REGIONS_PY" inject-pack "$_stage" \
            --name "$_pk" --body-file "$_body_sub" --in-place 2>"$_inj_err"; then
        fail "inject-pack $_pk into ${agent} failed — check packs/$_pk/${agent}.md"
        [[ -s "$_inj_err" ]] && sed 's/^/    /' "$_inj_err" >&2   # #276: surface why it died, don't just abort blind
        _any_inject_fail=true   # B2: route through the pre-Phase-B abort gate (§2.4.1)
        continue 2              # skip this agent; an unwritable pack region must not ship half-composed
      fi
    done

    # (A2) prepare the disk file. If a flat (marker-less) file is present, migrate
    # it first (provenance = is the slug HOS-shipped, i.e. in consumer_agents.txt;
    # by construction here it always is → CORE). Absent disk file → first install
    # path for this file (plan with empty base-shas + --first-install).
    _disk="$_AGENT_STAGE/${agent}.disk.md"
    _file_first_install=false
    if [[ -f "$dst" ]]; then
      if grep -q '<!-- HOS:' "$dst" 2>/dev/null; then
        cp "$dst" "$_disk"          # already has markers — three-way as-is (§5.4)
      else
        # Flat consumer/Phase-0 file → migrate to a wrapped region. Provenance =
        # is the slug HOS-shipped (in consumer_agents.txt) → here always yes →
        # CORE (legible to future upgrades, §5.2/D3).
        _regions_strict "$_disk" migrate "$dst" --ships yes   # #276: crash → abort, not a silent raw-copy as the "disk" image
      fi
    else
      _file_first_install=true
      : > "$_disk"   # no disk predecessor → every template region is freshly introduced
    fi

    # (A3) prior base-shas for this path (empty on first install / v1 manifest).
    if [[ -f "$_PRIOR_MANIFEST" ]]; then
      _bs_out="$_AGENT_STAGE/${agent}.base-shas.json"
      _regions_strict "$_bs_out" base-shas "$_PRIOR_MANIFEST" "$rel"   # #276: crash → abort, not a silent {} that mis-detects drift
      _base_shas="$(cat "$_bs_out")"
    else
      _base_shas='{}'
    fi

    # (A4) plan. --first-install when this file has no disk predecessor (seed an
    # empty PROJECT stub, §7.1). Capture JSON + exit code (4 = drift-blocked).
    # NOTE: `plan` exits 4 on a drift hard-stop — an EXPECTED non-zero. A plain
    # `x=$(...)` assignment trips `set -e` on that, so capture without aborting
    # (|| true) and read the real code from PIPESTATUS-free $? via a guarded run.
    _plan_first=()
    if $_file_first_install || $_first_install; then _plan_first=(--first-install); fi
    _plan_json=""
    _plan_rc=0
    _plan_err="$_AGENT_STAGE/${agent}.plan.err"
    _plan_json="$(python3 "$_REGIONS_PY" plan "$_disk" "$_stage" \
        --base-shas "$_base_shas" \
        ${_squash_flag[@]+"${_squash_flag[@]}"} ${_plan_first[@]+"${_plan_first[@]}"} 2>"$_plan_err")" \
      || _plan_rc=$?

    if [[ $_plan_rc -eq 4 ]]; then
      # Drift hard-stop for this file — collect the per-region report, keep going
      # so the aggregated report names EVERY blocked file (§4.3).
      _any_blocked=true
      _hs="$(printf '%s' "$_plan_json" | python3 -c 'import json,sys
try:
    p=json.load(sys.stdin)
except Exception:
    sys.exit(0)
for rid,reason in p.get("hardstops",[]):
    print(f"      {rid}: {reason}")' 2>/dev/null)"
      _blocked_report+="  ${rel}"$'\n'"${_hs}"$'\n'
      continue
    elif [[ $_plan_rc -ne 0 ]]; then
      fail "planning ${rel} failed (regions.py exit $_plan_rc) — check the file's markers"
      [[ -s "$_plan_err" ]] && sed 's/^/    /' "$_plan_err" >&2   # #276: surface the crash, don't suppress it
      _any_plan_fail=true   # R-B2: route through the pre-Phase-B abort gate (§2.4.1)
      continue
    fi

    # (A5) stash the composed bytes + manifest rows for Phase B.
    printf '%s' "$_plan_json" > "$_AGENT_STAGE/${agent}.plan.json"
    _planned_agents+=("$agent")
  done

  # ── Decide-all-then-act gate (§4.3 + B2 + R-B2) ─────────────────────────────
  # Three sentinel conditions — any one aborts the whole install before Phase B
  # writes a single file. Distinct err blocks so the operator gets a precise signal.
  if $_any_blocked || $_any_inject_fail || $_any_plan_fail; then
    echo ""
    if $_any_blocked; then
      err "Layering drift — refusing the whole upgrade (nothing written, no version stamped):"
      printf '%s' "$_blocked_report"
      echo ""
      err "Re-run with --squash to take HOS's version of the drifted region(s), or move"
      err "your edits into each file's PROJECT region, then re-run."
    fi
    if $_any_inject_fail; then
      err "Pack injection failed for one or more agents (see errors above) — refusing the"
      err "whole install (nothing written, no manifest, no version stamped). Fix the named"
      err "packs/<pack>/<agent>.md and re-run."
    fi
    if $_any_plan_fail; then
      err "Planning failed for one or more agents — check region markers (see errors above)."
      err "Nothing written, no manifest, no version stamped. Fix the file's markers and re-run."
    fi
    # exit 4 = the layering/abort hard-stop code (shared with drift). Phase B is
    # BELOW; nothing in .claude/agents/, .hos-manifest, or .hos-release is written.
    exit 4
  fi

  # ── Phase B — act (writes only after Phase A cleared) ───────────────────────
  # Build the manifest spec {path: [rows]} as we write each file's composed bytes.
  _manifest_spec="$_AGENT_STAGE/manifest-spec.json"
  : > "$_manifest_spec"
  for agent in ${_planned_agents[@]+"${_planned_agents[@]}"}; do
    dst="$TARGET_REPO/.claude/agents/${agent}.md"
    rel=".claude/agents/${agent}.md"
    _pj="$_AGENT_STAGE/${agent}.plan.json"
    if $DRY_RUN; then
      _act="$(python3 -c 'import json,sys
p=json.load(open(sys.argv[1]))
print(", ".join(f"{r}:{a}" for r,a in p["actions"]))' "$_pj" 2>/dev/null)"
      dry_run "Would write $rel ($_act)"
    else
      # Decode new_bytes (base64) → the agent file, and record its manifest rows.
      python3 -c 'import base64,json,sys
p=json.load(open(sys.argv[1]))
data=p.get("new_bytes_b64")
if data is None:
    sys.exit(0)
open(sys.argv[2],"wb").write(base64.b64decode(data))' "$_pj" "$dst" \
        || { fail "writing $rel failed"; continue; }
      ok "$rel (layered)"
    fi
  done

  # Aggregate every planned file's rows into one spec, then write the manifest
  # via assemble-manifest (schema-v2 header + LC_ALL=C-sorted body).
  if ! $DRY_RUN; then
    _spec_err="$_AGENT_STAGE/manifest-spec.err"
    if ! python3 -c 'import json,sys
spec={}
import os
stage=sys.argv[1]
for agent in sys.argv[2:]:
    pj=os.path.join(stage, agent + ".plan.json")
    if not os.path.exists(pj):
        continue
    p=json.load(open(pj))
    rows=p.get("new_manifest_rows")
    if rows:
        spec[".claude/agents/%s.md" % agent]=rows
json.dump(spec, open(os.path.join(stage,"manifest-spec.json"),"w"))' \
      "$_AGENT_STAGE" ${_planned_agents[@]+"${_planned_agents[@]}"} 2>"$_spec_err"; then
      # #277: the agents are written, but a crashed spec build would leave a
      # manifest MISSING every agent's region rows — which silently breaks the
      # NEXT upgrade's drift detection. Refuse to stamp a degraded manifest.
      echo "" >&2
      err "manifest-spec assembly crashed — refusing to write a manifest missing agent region rows (#277):"
      [[ -s "$_spec_err" ]] && sed 's/^/    /' "$_spec_err" >&2
      err "The agents were written, but .hos-manifest / .hos-release are NOT stamped. Fix the cause and re-run to complete the install."
      exit 1
    fi
  fi
fi

# ── Project-config follow-up (#87) — unchanged: inspects the installed agents ──
echo ""
info ".claude/agents/ — project placeholder check"
if [[ -f "$_manifest" ]]; then
  # Non-destructive-upgrade signals: newly-added config keys, and any declared
  # placeholder that ACTUALLY remains as a raw token in a scaffolded agent (not
  # merely declared-but-absent — e.g. ADR_FILE only appears in agents this
  # installer doesn't scaffold, so it shouldn't warn here).
  [[ ${#_appended[@]} -gt 0 ]] && warn "Added new placeholder key(s) to config.sh: ${_appended[*]}"
  _remaining=()
  for _n in "${_names[@]+"${_names[@]}"}"; do
    grep -rqE "\{${_n}\}" "$TARGET_REPO/.claude/agents" 2>/dev/null && _remaining+=("$_n")
  done
  if [[ ${#_remaining[@]} -gt 0 ]]; then
    # Delegate the interactive config-gen to scripts/framework/install.sh so one
    # `hos_install.sh` run produces a fully-configured project (#87, option A).
    # install.sh is the config engine (prompts for values, writes config.sh, and
    # substitutes); we invoke it only when interactive — non-interactive/CI keeps
    # the previous behavior (warn + let the operator run it). HOS_NO_CONFIG=1 opts
    # out entirely.
    _install_tool="$TARGET_REPO/scripts/framework/install.sh"
    if $DRY_RUN; then
      dry_run "Would run scripts/framework/install.sh --target $TARGET_REPO to fill: ${_remaining[*]}"
    elif [[ "${HOS_NO_CONFIG:-}" == "1" ]]; then
      warn "Unset placeholders (${_remaining[*]}); HOS_NO_CONFIG=1 → skipping config."
      warn "Run later: bash $_install_tool --target $TARGET_REPO"
    elif [[ -f "$_install_tool" && -t 0 ]]; then
      echo ""
      info "Configuring project values via scripts/framework/install.sh (${_remaining[*]}) …"
      if bash "$_install_tool" --target "$TARGET_REPO"; then
        ok "Project configured"
      else
        warn "Config tool exited non-zero — set values in $_subst_config and re-run --force."
      fi
    else
      warn "Placeholders still present as raw tokens in scaffolded agents: ${_remaining[*]}"
      warn "Set them in $_subst_config (or run: bash $_install_tool --target $TARGET_REPO), then re-run --force."
    fi
  fi
fi

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
run mkdir -p "$TARGET_REPO/scripts"

# Runner scripts only — NOT the installers/bootstrap. setup_clis.sh is a MACHINE
# tool (now in bootstrap/, run once per machine); setup_oversight.sh is the
# legacy project installer that hos_install.sh supersedes. Neither belongs in a
# target project's scripts/.
for script in run_panel.sh run_second_review.sh run_red_team.sh \
              review_self.sh reverify_self.sh \
              capture_prompt.sh prompt_audit.sh; do
  src="$HOS_SOURCE/scripts/$script"
  [[ ! -f "$src" ]] && src="$HOS_SOURCE/templates/$script"   # fallback to templates/
  cp_framework_file "$src" "$TARGET_REPO/scripts/$script"
done

# ── scripts/oversight/ — validators + gates ───────────────────────────────────
echo ""
info "scripts/oversight/ — validators and gates"
if [[ ! -d "$HOS_SOURCE/scripts/oversight" ]]; then
  fail "source scripts/oversight/ missing — incomplete HOS source"
elif ! $DRY_RUN; then
  run mkdir -p "$TARGET_REPO/scripts/oversight/validators" \
               "$TARGET_REPO/scripts/oversight/gates"
  # $FORCE is the string "true"/"false"; ${FORCE:+...} tests emptiness, not
  # truthiness, so build the flag array by actually evaluating $FORCE.
  # NEVER copy the source's Python virtualenv or bytecode caches: a .venv is
  # absolute-path-bound to the HOS source tree and would be broken (and huge) in
  # the target — the target builds its own via ensure_venv.sh. (HOS #self-review)
  # scripts/oversight/ is framework-owned (WHOLE); always overwrite on upgrade (#351).
  # --force additionally forces rsync checksum-level sync (vs mtime), but the
  # default is now always-overwrite, matching cp_framework_file semantics.
  if command -v rsync &>/dev/null; then
    rsync_flags=(-a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc')
    if $FORCE; then rsync_flags+=(--ignore-times --checksum); fi
    rsync "${rsync_flags[@]}" "$HOS_SOURCE/scripts/oversight/" "$TARGET_REPO/scripts/oversight/"
  else
    cp -R "$HOS_SOURCE/scripts/oversight/." "$TARGET_REPO/scripts/oversight/"
    # cp cannot --exclude; strip any source venv/bytecode that came along so the
    # target rebuilds a clean env (the copied .venv would be path-broken anyway).
    rm -rf "$TARGET_REPO/scripts/oversight/.venv"
    find "$TARGET_REPO/scripts/oversight" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  fi
  ok "scripts/oversight/ synced (framework — updated)"
else
  dry_run "Would sync $HOS_SOURCE/scripts/oversight/ → $TARGET_REPO/scripts/oversight/"
fi

# ── bootstrap/ — auth scripts and setup tooling (#653) ───────────────────────
echo ""
info "bootstrap/ — auth and setup scripts"
run mkdir -p "$TARGET_REPO/bootstrap"
cp_framework_file "$HOS_SOURCE/bootstrap/get_app_token.sh"   "$TARGET_REPO/bootstrap/get_app_token.sh"   "bootstrap/get_app_token.sh (GitHub App auth)"
# validate_setup.sh: install if present (added v0.4.0)
[[ -f "$HOS_SOURCE/bootstrap/validate_setup.sh" ]] &&   cp_framework_file "$HOS_SOURCE/bootstrap/validate_setup.sh"     "$TARGET_REPO/bootstrap/validate_setup.sh"     "bootstrap/validate_setup.sh (setup health check)" || true
# apps.env.template: install if present so consumers have a discoverable starting point
[[ -f "$HOS_SOURCE/bootstrap/apps.env.template" ]] &&   cp_file "$HOS_SOURCE/bootstrap/apps.env.template"     "$TARGET_REPO/bootstrap/apps.env.template"     "bootstrap/apps.env.template (credential template — customize to .config/hos/apps.env)" || true

# ── framework consumer files — bin/, .github/workflows/, scripts/framework/ (#769) ──
# Ship-set declared in scripts/framework/framework_consumer_files.txt — the single
# source of truth for BOTH the install copy-loop and .hos-manifest (mirrors the
# consumer_agents.txt pattern for agents). Covers: all of bin/ (incl. bin/lib/),
# .github/workflows/ required-check producers, and consumer-facing scripts/framework/
# tools. Before #769 the bin/lib/ dependency and all workflows were missing from
# consumer installs, breaking the cron launcher on first run.
echo ""
info "bin/ and framework consumer files"
_fc_list="$HOS_SOURCE/scripts/framework/framework_consumer_files.txt"
[[ -f "$_fc_list" ]] || fail "framework_consumer_files.txt missing from source — incomplete HOS release"
while IFS= read -r _fc; do
  _fc="${_fc%%#*}"; _fc="$(echo "$_fc" | xargs || true)"
  [[ -z "$_fc" ]] && continue
  [[ -f "$HOS_SOURCE/$_fc" ]] || { warn "framework_consumer_files.txt: $HOS_SOURCE/$_fc not found — skipping"; continue; }
  cp_framework_file "$HOS_SOURCE/$_fc" "$TARGET_REPO/$_fc" "$_fc"
  # Executables in bin/ without .sh suffix need explicit chmod+x (cp_framework_file
  # only does .sh; hos-cron, hos-trim-logs, and git-credentials.sh all need +x).
  case "$_fc" in
    bin/*) $DRY_RUN || chmod +x "$TARGET_REPO/$_fc" ;;
  esac
done < "$_fc_list"

# Generate prompt files — substitute available values, leave bot logins as placeholders
# #723: use python3 str.replace (not sed) — repo URL may contain | which breaks sed -e "s|...|
_cron_repo_url="$(git -C "$TARGET_REPO" remote get-url origin 2>/dev/null \
  | sed 's|git@github.com:||; s|https://github.com/||; s|\.git$||' || echo "__OWNER__/__REPO__")"
_cron_worker_dir="$TARGET_REPO"
_cron_overseer_dir="$TARGET_REPO"

_subst_prompt() {
  local src="$1" dst="$2" role="$3" dir="$4" bot_placeholder="$5"
  [[ -f "$src" ]] || return 0
  # Derive the source working-directory path from the prompt template itself
  # rather than hardcoding a developer-specific home path (#731). The
  # 'WORKING DIRECTORY:' line is a stable contract at the top of every
  # cron-prompt template; reading it here makes the substitution correct on any
  # contributor's HOS clone and keeps this installer free of machine-specific
  # absolute paths (portability gate). An empty match is guarded in Python so a
  # malformed template degrades to "leave the path unchanged" instead of
  # corrupting the output.
  local from_dir
  from_dir="$(sed -n 's/^WORKING DIRECTORY:[[:space:]]*//p' "$src" | head -n1)"
  python3 - "$src" "$dst" \
    "thurlow-research/HumanOversightSystem" "$_cron_repo_url" \
    "$from_dir" "$dir" \
    "hos-${role}-hos[bot]" "$bot_placeholder" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
pairs = list(zip(sys.argv[3::2], sys.argv[4::2]))
content = open(src).read()
for old, new in pairs:
    if old:
        content = content.replace(old, new)
open(dst, 'w').write(content)
PYEOF
}

if ! $DRY_RUN; then
  _subst_prompt "$HOS_SOURCE/bootstrap/worker-cron-prompt.md" \
    "$TARGET_REPO/bootstrap/worker-cron-prompt.md" \
    "worker" "$_cron_worker_dir" "__WORKER_BOT_LOGIN__" \
    && ok "bootstrap/worker-cron-prompt.md (generated — update __WORKER_BOT_LOGIN__)" \
    || warn "bootstrap/worker-cron-prompt.md — generation failed (python3 unavailable?)"
  _subst_prompt "$HOS_SOURCE/bootstrap/overseer-cron-prompt.md" \
    "$TARGET_REPO/bootstrap/overseer-cron-prompt.md" \
    "overseer" "$_cron_overseer_dir" "__OVERSEER_BOT_LOGIN__" \
    && ok "bootstrap/overseer-cron-prompt.md (generated — update __OVERSEER_BOT_LOGIN__)" \
    || warn "bootstrap/overseer-cron-prompt.md — generation failed (python3 unavailable?)"
else
  dry_run "Would generate bootstrap/worker-cron-prompt.md (repo=$_cron_repo_url)"
  dry_run "Would generate bootstrap/overseer-cron-prompt.md (repo=$_cron_repo_url)"
fi

# ── AGENTS.md — Layer 1 protocol ──────────────────────────────────────────────
echo ""
info "Core governance documents"
cp_framework_file "$HOS_SOURCE/AGENTS.md"     "$TARGET_REPO/AGENTS.md"
# METHODOLOGY.md is optional (not all releases ship it); suppress source-not-found
# by calling cp_framework_file only when the source exists.
[[ -f "$HOS_SOURCE/METHODOLOGY.md" ]] && \
  cp_framework_file "$HOS_SOURCE/METHODOLOGY.md" "$TARGET_REPO/METHODOLOGY.md" || true

# ── CLAUDE.md — wire the orchestrator role into the auto-loaded context ────────
# AGENTS.md holds the protocol, but the main interactive agent only auto-loads
# CLAUDE.md. Without a pointer there, the orchestrator never reads the protocol
# and defaults to doing the work itself (pipeline bypass — the agents go unused).
# Inject an idempotent, marker-delimited managed block: create CLAUDE.md if
# absent, append if our markers aren't present, refresh in place if they are.
# We never touch the consumer's own CLAUDE.md content outside the markers.
_CLAUDE_MD="$TARGET_REPO/CLAUDE.md"
_HOS_BS="<!-- HOS:ORCHESTRATOR start -->"
_HOS_BE="<!-- HOS:ORCHESTRATOR end -->"
read -r -d '' _HOS_BLOCK <<'BLOCK' || true
<!-- HOS:ORCHESTRATOR start -->
## Oversight: you are the orchestrator

This project uses the Human Oversight System (HOS). **Read `AGENTS.md` before any build task.**

**You are the orchestrator, not the worker.** Route each piece of work to the specialized agent that owns it and integrate the results — do **not** author code, run reviews, or make security / privacy / risk determinations yourself. Dispatch the **coder** to write code; **code-reviewer / security-reviewer / privacy-reviewer / risk-assessor** to review; **technical-design / architect** to spec. You triage, sequence, dispatch, carry results between agents, surface the human gates, and keep the sign-off register honest. Before you touch a file, ask *"whose job is this — mine, or an agent's?"* — if an agent owns it, **dispatch, don't absorb.** Doing the work yourself collapses the author≠reviewer independence that is the whole point, and the oversight-evaluator's Phase-1 compliance check will block the step (empty sign-off register). Full protocol: `AGENTS.md` §"Orchestrate, Don't Absorb".
<!-- HOS:ORCHESTRATOR end -->
BLOCK

if $DRY_RUN; then
  dry_run "ensure HOS orchestrator block in CLAUDE.md"
elif [[ ! -f "$_CLAUDE_MD" ]]; then
  printf '%s\n' "$_HOS_BLOCK" > "$_CLAUDE_MD"
  info "CLAUDE.md created with HOS orchestrator block"
elif ! grep -qF "$_HOS_BS" "$_CLAUDE_MD"; then
  printf '\n%s\n' "$_HOS_BLOCK" >> "$_CLAUDE_MD"
  info "CLAUDE.md — HOS orchestrator block appended (your existing content untouched)"
else
  _bf="$(mktemp)"; _tmp="$(mktemp)"
  printf '%s\n' "$_HOS_BLOCK" > "$_bf"
  awk -v s="$_HOS_BS" -v e="$_HOS_BE" -v bf="$_bf" '
    BEGIN { while ((getline line < bf) > 0) block = block line "\n" }
    $0==s { printf "%s", block; skip=1; next }
    $0==e { skip=0; next }
    !skip { print }
  ' "$_CLAUDE_MD" > "$_tmp" && mv "$_tmp" "$_CLAUDE_MD"
  rm -f "$_bf"
  skip "CLAUDE.md — HOS orchestrator block refreshed in place"
fi

# ── contract/ — oversight contract + step manifest template ───────────────────
run mkdir -p "$TARGET_REPO/contract"

# OVERSIGHT-CONTRACT.md — framework-canonical contract the reviewer agents
# enforce against (6 shipped reviewers cite it). Shipped + refreshed like
# AGENTS.md; #283 — it was declared REQUIRED in source but never installed to
# consumers, leaving every consumer install with a dangling contract reference.
cp_framework_file "$HOS_SOURCE/contract/OVERSIGHT-CONTRACT.md" \
        "$TARGET_REPO/contract/OVERSIGHT-CONTRACT.md" \
        "contract/OVERSIGHT-CONTRACT.md"

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
  run mkdir -p "$TARGET_REPO/audit/escalations" "$TARGET_REPO/audit/panel-runs"
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

# Verify audit/ is not accidentally gitignored (ignore commented lines, so a
# "# audit/ ..." comment doesn't trip a false warning).
if [[ -f "$GITIGNORE" ]] && grep -v '^[[:space:]]*#' "$GITIGNORE" 2>/dev/null | grep -qF "audit/"; then
  warn "audit/ is in .gitignore — the audit trail won't be committed!"
  warn "Remove that line from $TARGET_REPO/.gitignore"
fi

# ── .github/ — CODEOWNERS + PR template ───────────────────────────────────────
echo ""
info ".github/ — code owners and PR template"
run mkdir -p "$TARGET_REPO/.github"
cp_framework_file "$HOS_SOURCE/.github/CODEOWNERS"              "$TARGET_REPO/.github/CODEOWNERS"
cp_framework_file "$HOS_SOURCE/.github/pull_request_template.md" "$TARGET_REPO/.github/pull_request_template.md"

# ── prompts/ — prompt artifact directory ──────────────────────────────────────
echo ""
info "prompts/ — prompt artifact directory"
if [[ ! -d "$TARGET_REPO/prompts" ]]; then
  run mkdir -p "$TARGET_REPO/prompts"
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

# NOTE: .hos-release (the version stamp) is written AFTER the manifest block
# below — the version is the COMMIT POINT, stamped only once the agents AND the
# manifest are on disk. So a manifest-assembly failure (#277) can never leave a
# new .hos-release stamped over a stale or missing .hos-manifest.

# ── .hos-manifest — framework inventory, obsolete-file detection + opt-in prune (#182) ──
# Records the framework-OWNED files this release ships, each with its sha256 (so a
# prune can tell a pristine framework file from a consumer-edited one). On an update,
# paths in the PRIOR manifest but absent from this one were REMOVED by the framework —
# a leftover .claude/agents/*.md is the real AI-confusion risk. Detection is always on
# (non-destructive). --prune ARCHIVES them (MOVE, not delete) to a committed,
# quarantined .hos-archive/, and only when the file is unmodified since install.

# Portable sha256 of one file.
_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" 2>/dev/null | awk '{print $1}'
  else shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; fi
}

# Enumerate framework-owned NON-AGENT paths as "<path>\tWHOLE\t<sha256>" (schema
# v2, TD §1.4). Agent .md files are NOT enumerated here — they contribute per-
# REGION rows from the Phase-B plan spec (CORE/PACK/PROJECT), assembled into the
# manifest below. Only files the framework actually ships (not consumer files in
# shared dirs), so a prune can never target the consumer's own work; venv/
# bytecode excluded.
enumerate_framework_files() {
  local src="$1" _f
  ( cd "$src" && {
      [[ -d scripts/oversight ]] && find scripts/oversight -type f \
          ! -path '*/.venv/*' ! -path '*/__pycache__/*' ! -name '*.pyc' 2>/dev/null
      for _f in AGENTS.md METHODOLOGY.md contract/OVERSIGHT-CONTRACT.md \
          .github/CODEOWNERS .github/pull_request_template.md \
          scripts/run_panel.sh scripts/run_second_review.sh scripts/run_red_team.sh \
          scripts/review_self.sh scripts/reverify_self.sh scripts/capture_prompt.sh \
          scripts/prompt_audit.sh; do [[ -f "$_f" ]] && echo "$_f"; done
      # Files listed in framework_consumer_files.txt (bin/, .github/workflows/,
      # scripts/framework/ consumer tools) — single source of truth (#769).
      if [[ -f scripts/framework/framework_consumer_files.txt ]]; then
        while IFS= read -r _fc; do
          _fc="${_fc%%#*}"; _fc="$(echo "$_fc" | xargs || true)"
          [[ -z "$_fc" ]] && continue
          [[ -f "$_fc" ]] && echo "$_fc"
        done < scripts/framework/framework_consumer_files.txt
      fi
    } | LC_ALL=C sort -u | while IFS= read -r _f; do printf '%s\tWHOLE\t%s\n' "$_f" "$(_sha256 "$_f")"; done )
}

echo ""
info ".hos-manifest — framework file inventory"
_manifest_file="$TARGET_REPO/.hos-manifest"
if $DRY_RUN; then
  dry_run "Would write $_manifest_file; check for removed framework files; --prune would archive them"
else
  # Non-agent WHOLE rows (3-column, schema v2).
  _whole_rows="$(enumerate_framework_files "$HOS_SOURCE")"
  # Combine the non-agent WHOLE rows with the agent REGION rows (from the Phase-B
  # spec) into the full schema-v2 manifest via assemble-manifest (schema header +
  # LC_ALL=C-sorted body). The agent spec is keyed by path; the WHOLE rows are
  # already path-bearing 3-column rows, fed under a "" bucket so assemble passes
  # them through unchanged.
  _agent_spec="$_AGENT_STAGE/manifest-spec.json"
  [[ -f "$_agent_spec" ]] || echo '{}' > "$_agent_spec"
  _manifest_err="$_AGENT_STAGE/manifest-assemble.err"
  _assemble_rc=0
  _new_manifest="$(python3 -c 'import json,sys
spec=json.load(open(sys.argv[1]))
# WHOLE rows arrive on stdin as full "<path>\tWHOLE\t<sha>" lines; bucket them
# under "" — assemble_manifest passes already-path-bearing rows through as-is.
whole=[ln for ln in sys.stdin.read().splitlines() if ln.strip()]
if whole:
    spec.setdefault("", []).extend(whole)
sys.path.insert(0, sys.argv[2])
import regions
sys.stdout.write(regions.assemble_manifest(spec))' \
      "$_agent_spec" "$HOS_SOURCE/scripts/oversight/validators" <<< "$_whole_rows" 2>"$_manifest_err")" || _assemble_rc=$?
  if [[ $_assemble_rc -ne 0 || -z "$_new_manifest" ]]; then
    if [[ ! -f "$HOS_SOURCE/scripts/oversight/validators/regions.py" ]]; then
      # regions.py genuinely absent — WHOLE-only is the best-effort fallback, but
      # say so: region drift tracking is degraded until a region-aware install.
      warn ".hos-manifest: regions.py unavailable — writing WHOLE rows only (region drift tracking is degraded until the next region-aware install)."
      _new_manifest="$(printf '# hos-manifest-schema: 2\n%s\n' "$_whole_rows" | LC_ALL=C sort)"
    else
      # #277: regions.py IS present but assembly crashed — do NOT silently stamp a
      # degraded (region-row-less) manifest. The agents are written, but a degraded
      # manifest breaks the next upgrade's drift detection. Refuse to stamp.
      echo "" >&2
      err ".hos-manifest assembly crashed (regions.py present, exit $_assemble_rc) — refusing to write a degraded manifest (#277):"
      [[ -s "$_manifest_err" ]] && sed 's/^/    /' "$_manifest_err" >&2
      err "The agents were written, but .hos-manifest / .hos-release are NOT stamped. Fix the cause and re-run to complete the install."
      exit 1
    fi
  fi
  if [[ -f "$_manifest_file" ]]; then
    # Orphans = paths in the prior manifest but not this one, that still exist.
    # Compare the PATH column only (cut -f1) so a legacy path-only manifest still works.
    _orphans=()
    while IFS= read -r _p; do
      [[ -n "$_p" && -e "$TARGET_REPO/$_p" ]] && _orphans+=("$_p")
    done < <(LC_ALL=C comm -23 \
        <(cut -f1 "$_manifest_file" | LC_ALL=C sort -u) \
        <(printf '%s\n' "$_new_manifest" | cut -f1 | LC_ALL=C sort -u))
    if [[ ${#_orphans[@]} -gt 0 ]]; then
      warn "${#_orphans[@]} framework file(s) were removed in this release but remain in your repo (possibly obsolete):"
      for _p in "${_orphans[@]}"; do
        case "$_p" in
          .claude/agents/*) echo -e "      ${YELLOW}$_p${RESET}  ← stale AGENT definition (the AI may load it — review first)" ;;
          *)                echo "      $_p" ;;
        esac
      done

      # ── Stale agent auto-archive (#350) ────────────────────────────────────
      # Stale .claude/agents/*.md files are an AI-confusion risk: the AI will
      # load every agent in that directory, including ones the framework removed.
      # Unlike non-agent orphans, we act immediately rather than just warn.
      #   Non-interactive / --pr mode → archive automatically to .hos-stale/.
      #   Interactive → prompt the user (Y to archive, n to leave in place).
      # This is separate from --prune (which archives ALL orphans to .hos-archive/).
      _stale_agents=()
      for _p in "${_orphans[@]}"; do
        case "$_p" in .claude/agents/*) _stale_agents+=("$_p") ;; esac
      done

      if [[ ${#_stale_agents[@]} -gt 0 ]]; then
        _do_stale_archive=false
        if ! [[ -t 0 ]] || $PR_ACTIVE; then
          # Non-interactive or PR-mode: auto-archive without prompting (#350).
          _do_stale_archive=true
          warn "Non-interactive mode — archiving ${#_stale_agents[@]} stale agent file(s) to .hos-stale/ automatically (#350)"
        else
          # Interactive: prompt.
          echo ""
          echo -e "  ${YELLOW}⚠${RESET}  ${#_stale_agents[@]} stale agent definition(s) detected."
          echo "     The AI loads every file in .claude/agents/ — stale agents cause confusion."
          printf "     Archive them to .hos-stale/ now? [Y/n] "
          read -r _stale_ans </dev/tty || _stale_ans="Y"
          [[ "${_stale_ans:-Y}" =~ ^[Yy]?$ ]] && _do_stale_archive=true
        fi

        if $_do_stale_archive; then
          _stale_root="$TARGET_REPO/.hos-stale"
          _stale_archived=0; _stale_skipped=0
          for _p in "${_stale_agents[@]}"; do
            _fname="$(basename "$_p")"
            mkdir -p "$_stale_root"
            if mv "$TARGET_REPO/$_p" "$_stale_root/$_fname" 2>/dev/null; then
              _stale_archived=$((_stale_archived+1))
              _stale_sha="$(_sha256 "$_stale_root/$_fname")"
              printf '{"event":"hos-stale-archive","file":"%s","archived_to":".hos-stale/%s","release":"%s","sha256":"%s","timestamp":"%s"}\n' \
                "$_p" "$_fname" "$HOS_REF" "$_stale_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                >> "$TARGET_REPO/audit/oversight-log.jsonl" 2>/dev/null || true
              ok "Archived stale agent: $_p → .hos-stale/$_fname"
            else
              warn "Could not archive $_p — check permissions; remove manually."; _stale_skipped=$((_stale_skipped+1))
            fi
          done
          if [[ $_stale_archived -gt 0 ]]; then
            # Quarantine marker — keep agents/tools from treating stale dir as live.
            cat > "$_stale_root/DO-NOT-USE.md" <<'STALE'
# .hos-stale/ — quarantined stale agent definitions

Agent files here were removed from the HOS framework and auto-archived by
`hos_install.sh` (#350). They are NOT active — Claude will NOT load them here.
To recover one, move it back to `.claude/agents/`. It is also in git history.
STALE
          fi
          [[ $_stale_skipped -gt 0 ]] && warn "$_stale_skipped stale agent(s) left in place (move failed — remove manually)."
        else
          warn "Stale agents left in place — remove or move them manually before using HOS (#350)."
        fi
      fi

      if $PRUNE; then
        # Opt-in archive-prune (destructive → cautious): MOVE each orphan to a committed,
        # quarantined .hos-archive/, but only if it is UNMODIFIED since install (sha256
        # matches the prior manifest). Consumer-edited files are left in place + flagged.
        # Stale agents already handled above — skip them in the --prune pass.
        _ref_slug="$(printf '%s' "$HOS_REF" | tr -cs 'A-Za-z0-9._-' '-' | sed 's/^-*//; s/-*$//')"
        _arch_root="$TARGET_REPO/.hos-archive"; _arch_dir="$_arch_root/removed-in-${_ref_slug:-update}"
        _pruned=0; _skipped=0
        for _p in "${_orphans[@]}"; do
          case "$_p" in .claude/agents/*) continue ;; esac   # already handled by stale-archive
          # #679: schema v2 = path\tWHOLE\tsha256 — sha256 is $3, not $2
          _prior_sha="$(awk -F '\t' -v p="$_p" '$1==p{print $3; exit}' "$_manifest_file")"
          _cur_sha="$(_sha256 "$TARGET_REPO/$_p")"
          if [[ -z "$_prior_sha" ]]; then
            warn "  keep $_p — can't verify it's unmodified (legacy manifest); review/remove manually."; _skipped=$((_skipped+1)); continue
          fi
          if [[ "$_prior_sha" != "$_cur_sha" ]]; then
            warn "  keep $_p — modified since install; left in place (remove manually if intended)."; _skipped=$((_skipped+1)); continue
          fi
          mkdir -p "$_arch_dir/$(dirname "$_p")"
          if mv "$TARGET_REPO/$_p" "$_arch_dir/$_p" 2>/dev/null; then
            _pruned=$((_pruned+1))
            printf '{"event":"hos-prune","file":"%s","archived_to":".hos-archive/removed-in-%s/%s","release":"%s","sha256":"%s","timestamp":"%s"}\n' \
              "$_p" "${_ref_slug:-update}" "$_p" "$HOS_REF" "$_cur_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
              >> "$TARGET_REPO/audit/oversight-log.jsonl" 2>/dev/null || true
          fi
        done
        if [[ $_pruned -gt 0 ]]; then
          # Quarantine marker so agents/tools never treat archived files as live.
          [[ -f "$_arch_root/DO-NOT-USE.md" ]] || cat > "$_arch_root/DO-NOT-USE.md" <<'ARCH'
# .hos-archive/ — quarantined obsolete framework files

Files here were REMOVED from the HOS framework and archived by `hos_install.sh --prune`,
kept only for recovery. **Agents and tools MUST NOT read, load, or act on anything in
this directory** (it is outside the scanned agent/validator trees by design). To recover
one, move it back — it is also in git history and the prior release tag.
ARCH
          ok "Pruned $_pruned obsolete file(s) → .hos-archive/removed-in-${_ref_slug:-update}/ (archived, recoverable)"
          [[ $_skipped -gt 0 ]] && warn "$_skipped left in place (modified/unverifiable — see above)."
          # Retention: keep the 2 most recent archive sets.
          ls -dt "$_arch_root"/removed-in-* 2>/dev/null | tail -n +3 | while IFS= read -r _old; do rm -rf "$_old"; done
        fi
      else
        # Non-agent orphan files: always warn, suggest --prune.
        _non_agent_orphans=()
        for _p in "${_orphans[@]}"; do
          case "$_p" in .claude/agents/*) ;; *) _non_agent_orphans+=("$_p") ;; esac
        done
        [[ ${#_non_agent_orphans[@]} -gt 0 ]] && \
          warn "Review and remove non-agent orphan(s) if unused, or re-run with --prune to archive them safely to .hos-archive/ (#182)."
      fi
    fi
  fi
  printf '%s\n' "$_new_manifest" > "$_manifest_file"
  ok ".hos-manifest written ($(printf '%s\n' "$_new_manifest" | grep -cvE '^(#|[[:space:]]*$)') region/file rows tracked)"
fi

# ── .hos-release — record the installed framework version (the COMMIT POINT) ───
# Written LAST, only after the agents and manifest are on disk — so a failure in
# the manifest block above (#277) never leaves a new version over a bad manifest.
echo ""
info ".hos-release — installed framework version marker"
if $DRY_RUN; then
  dry_run "Would write $TARGET_REPO/.hos-release ($HOS_REF)"
else
  printf "%s\n" "$HOS_REF" > "$TARGET_REPO/.hos-release"
  ok ".hos-release = $HOS_REF"
fi

# ── Install-via-PR: commit the upgrade, open the PR, return to the original branch (#193) ──
if $PR_ACTIVE; then
  header "Install-via-PR — opening the upgrade PR"
  if [[ -z "$(git -C "$TARGET_REPO" status --porcelain 2>/dev/null)" ]]; then
    info "No changes from this upgrade — removing the branch, nothing to review."
    git -C "$TARGET_REPO" checkout "$PR_ORIG_BRANCH" >/dev/null 2>&1 || true
    git -C "$TARGET_REPO" branch -D "$PR_BRANCH" >/dev/null 2>&1 || true
  else
    git -C "$TARGET_REPO" add -A
    if ! git -C "$TARGET_REPO" commit -q -m "chore(hos): upgrade framework to ${HOS_REF}"; then
      # #273: a swallowed commit failure (e.g. a rejecting hook) must NOT fall
      # through to pushing an un-committed branch under a misleading "Committed…"
      # message. Fail-closed; the base branch is untouched (work is on PR_BRANCH).
      fail "Commit failed on '$PR_BRANCH' (e.g. a rejecting hook) — staged changes remain; your base branch is untouched. Resolve and re-run."
    elif git -C "$TARGET_REPO" push -q -u origin "$PR_BRANCH" 2>/dev/null; then
      # #226: disclose that this PR is machine-generated — by a deterministic
      # installer script, not hand-authored (and not LLM-authored). Draft +
      # best-effort needs-human so a human reviews before merge.
      _pr_body="> 🤖 **Automated PR — generated by \`hos_install.sh\`.** Produced by the HOS installer (a deterministic script), not hand-authored. A human must review the diff before merging; it must not be auto-merged.

Automated HOS framework upgrade to **${HOS_REF}**. Review the diff, then **merge to adopt** or **close/revert to roll back** — your \`main\` is untouched until you merge. Any framework files removed this version are visible in the \`.hos-manifest\` diff (#182)."
      _pr_url="$( cd "$TARGET_REPO" && gh pr create \
        --title "🤖 [hos-install] chore(hos): upgrade framework to ${HOS_REF}" \
        --body "$_pr_body" --head "$PR_BRANCH" --draft 2>/dev/null || true )"
      if [[ -n "$_pr_url" ]]; then
        ok "Opened upgrade PR (draft): $_pr_url"
        # The label may not exist in the consumer repo — best-effort; never fail
        # the PR over a missing label (#226).
        ( cd "$TARGET_REPO" && gh pr edit "$_pr_url" --add-label needs-human >/dev/null 2>&1 ) \
          || info "(tip: this PR is flagged for human review — add a 'needs-human' label if your repo uses one)"
      else fail "Pushed '$PR_BRANCH' but PR creation failed — open it manually: gh pr create --draft --head $PR_BRANCH"; fi
    else
      fail "Committed on '$PR_BRANCH' but push failed — push it and open a PR manually. (Your base branch is untouched.)"
    fi
    if git -C "$TARGET_REPO" checkout "$PR_ORIG_BRANCH" >/dev/null 2>&1; then
      info "Back on '$PR_ORIG_BRANCH' — your working state is undisturbed; the upgrade lives in the PR."
    else
      warn "Could not return to '$PR_ORIG_BRANCH' — you are still on '$PR_BRANCH'. Switch back manually (git checkout $PR_ORIG_BRANCH)."
    fi
  fi
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
  echo "  3. Commit the scaffolded files (review with 'git status' first):"
  echo "       cd $TARGET_REPO && git add .claude/ AGENTS.md METHODOLOGY.md audit/ contract/ \\"
  echo "         scripts/ .github/ prompts/ .gitignore .hos-release"
  echo "       git commit -m 'Bootstrap Human Oversight System ($HOS_REF)'"
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
  echo "  6. Set up autonomous cron agents (#715, #717):"
  echo "       a. Edit the generated prompt files and replace __*_BOT_LOGIN__ placeholders:"
  echo "            $TARGET_REPO/bootstrap/worker-cron-prompt.md"
  echo "            $TARGET_REPO/bootstrap/overseer-cron-prompt.md"
  echo "       b. Add your project to ~/.config/hos/projects.conf:"
  echo "            __PROJECT___config_dir=<path-to-your-project>/.config/hos"
  echo "            __PROJECT___worker_root=$TARGET_REPO"
  echo "            __PROJECT___overseer_root=$TARGET_REPO"
  echo "       c. Add to crontab (crontab -e) — adjust schedule and PATH as needed:"
  echo "            # Worker (every 5 min):"
  echo "            1,6,11,16,21,26,31,36,41,46,51,56 * * * *  PATH=~/.local/bin:/usr/local/bin:/usr/bin:/bin $TARGET_REPO/bin/hos-cron --role worker  --project __PROJECT__ >> /tmp/hos-worker-__PROJECT__.log 2>&1"
  echo "            # Overseer (every 5 min, 3 min offset):"
  echo "            4,9,14,19,24,29,34,39,44,49,54,59 * * * *  PATH=~/.local/bin:/usr/local/bin:/usr/bin:/bin $TARGET_REPO/bin/hos-cron --role overseer --project __PROJECT__ >> /tmp/hos-overseer-__PROJECT__.log 2>&1"
  echo "            # Weekly log trim:"
  echo "            0 2 * * 0  $TARGET_REPO/bin/hos-trim-logs"
  echo ""

echo "  Docs: CLAUDE.md · ARCHITECTURE.md · contract/OVERSIGHT-CONTRACT.md"
echo ""
