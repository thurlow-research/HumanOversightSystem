#!/usr/bin/env bash
# cut_release.sh — cut a validated HOS release.
#
# A release is a PINNED, VALIDATED point that consumers deploy from (never
# main-HEAD, which with batched validation is an integration trunk). This script
# is the release gate: it runs the full validation suite, and only on a clean
# result does it tag the commit, publish a GitHub release, and upload the
# bootstrap scripts as release ASSETS at the well-known location
#   https://github.com/<repo>/releases/latest/download/<script>
# so a fresh machine can `curl` them without cloning. Those scripts then fetch
# the full framework from this same release (see bootstrap/hos_install.sh).
#
# Usage:
#   ./scripts/framework/cut_release.sh                 # bump patch, validate, tag, publish
#   ./scripts/framework/cut_release.sh --version v0.3.0
#   ./scripts/framework/cut_release.sh --bump minor    # patch|minor|major (default patch)
#   ./scripts/framework/cut_release.sh --dry-run       # show what would happen, no writes
#   ./scripts/framework/cut_release.sh --prerelease    # mark the GitHub release as pre-release
#   ./scripts/framework/cut_release.sh --notes FILE    # release notes from FILE (else auto)
#   ./scripts/framework/cut_release.sh --skip-validation   # DANGER: cut without the gate
#   ./scripts/framework/cut_release.sh --allow-dirty --allow-branch   # relax preconditions
#   Extra args after `--` pass through to run_framework_validation.sh
#   (e.g. `-- --skip-codex`).
#
# Exit: 0 released | 1 precondition/validation failure | 2 usage/tooling error
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"; RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✘${RESET}  $*"; }
hdr()  { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

# ── Defaults / args ───────────────────────────────────────────────────────────
VERSION=""
BUMP="patch"
DRY_RUN=false
PRERELEASE=false
SKIP_VALIDATION=false
ALLOW_DIRTY=false
ALLOW_BRANCH=false
NOTES_FILE=""
VALIDATION_ARGS=()
RELEASE_BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)         VERSION="${2:?--version needs vX.Y.Z}"; shift 2 ;;
    --bump)            BUMP="${2:?--bump needs patch|minor|major}"; shift 2 ;;
    --dry-run)         DRY_RUN=true; shift ;;
    --prerelease)      PRERELEASE=true; shift ;;
    --skip-validation) SKIP_VALIDATION=true; shift ;;
    --allow-dirty)     ALLOW_DIRTY=true; shift ;;
    --allow-branch)    ALLOW_BRANCH=true; shift ;;
    --notes)           NOTES_FILE="${2:?--notes needs a file}"; shift 2 ;;
    --)                shift; VALIDATION_ARGS=("$@"); break ;;
    -h|--help)         sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                 err "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
done

command -v gh  &>/dev/null || { err "gh CLI required"; exit 2; }
command -v git &>/dev/null || { err "git required"; exit 2; }

REPO_SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
[[ -z "$REPO_SLUG" ]] && { err "could not resolve repo (gh repo view)"; exit 2; }

hdr "HOS release cut — $REPO_SLUG"

# ── Preconditions ─────────────────────────────────────────────────────────────
hdr "1. Preconditions"
CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CUR_BRANCH" != "$RELEASE_BRANCH" ]] && ! $ALLOW_BRANCH; then
  err "not on $RELEASE_BRANCH (on '$CUR_BRANCH'). Cut releases from $RELEASE_BRANCH, or pass --allow-branch."
  exit 1
fi
ok "branch: $CUR_BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
  if $ALLOW_DIRTY; then
    warn "working tree is dirty (allowed via --allow-dirty)"
  else
    err "working tree is dirty. Commit/stash, or pass --allow-dirty."
    exit 1
  fi
else
  ok "working tree clean"
fi

git fetch --tags --quiet origin 2>/dev/null || warn "could not fetch from origin (offline?)"
if git rev-parse "origin/$RELEASE_BRANCH" &>/dev/null; then
  LOCAL_HEAD="$(git rev-parse HEAD)"; REMOTE_HEAD="$(git rev-parse "origin/$RELEASE_BRANCH")"
  if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]] && ! $ALLOW_BRANCH; then
    err "HEAD is not in sync with origin/$RELEASE_BRANCH. Pull/push first, or --allow-branch."
    exit 1
  fi
  ok "in sync with origin/$RELEASE_BRANCH"
fi

# ── Resolve version ───────────────────────────────────────────────────────────
hdr "2. Version"
LATEST_TAG="$(git tag -l 'v*' --sort=-v:refname | head -1 || true)"
info "latest tag: ${LATEST_TAG:-<none>}"

if [[ -z "$VERSION" ]]; then
  base="${LATEST_TAG:-v0.0.0}"; base="${base#v}"
  IFS='.' read -r MA MI PA <<<"$base"
  MA="${MA:-0}"; MI="${MI:-0}"; PA="${PA:-0}"
  case "$BUMP" in
    major) MA=$((MA+1)); MI=0; PA=0 ;;
    minor) MI=$((MI+1)); PA=0 ;;
    patch) PA=$((PA+1)) ;;
    *) err "invalid --bump: $BUMP"; exit 2 ;;
  esac
  VERSION="v${MA}.${MI}.${PA}"
fi
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { err "version must be semver vX.Y.Z: got '$VERSION'"; exit 2; }
if git rev-parse "$VERSION" &>/dev/null; then err "tag $VERSION already exists"; exit 1; fi
ok "release version: ${BOLD}$VERSION${RESET}"

# ── Validation gate ───────────────────────────────────────────────────────────
hdr "3. Validation gate"
if $SKIP_VALIDATION; then
  warn "VALIDATION SKIPPED (--skip-validation) — this release is NOT gated. Use only for emergencies."
else
  info "running full validation suite (static → self → external → docs → compliance)..."
  if $DRY_RUN; then
    info "[dry] would run: scripts/framework/run_framework_validation.sh ${VALIDATION_ARGS[*]:-}"
  else
    if ! bash scripts/framework/run_framework_validation.sh "${VALIDATION_ARGS[@]:-}"; then
      err "validation did NOT pass — refusing to cut a release. Fix findings (or converge the"
      err "external-review ledger), then re-run. Override only with --skip-validation."
      exit 1
    fi
    ok "validation passed — clear to release"
  fi
fi

# ── Release notes ─────────────────────────────────────────────────────────────
NOTES_ARG=()
if [[ -n "$NOTES_FILE" ]]; then
  [[ -f "$NOTES_FILE" ]] || { err "notes file not found: $NOTES_FILE"; exit 2; }
  NOTES_ARG=(--notes-file "$NOTES_FILE")
else
  NOTES_ARG=(--generate-notes)
fi

# ── Tag + publish + assets ────────────────────────────────────────────────────
hdr "4. Tag, publish, and upload bootstrap assets"
ASSETS=(bootstrap/hos_install.sh bootstrap/hos_bootstrap.sh bootstrap/setup_clis.sh)
for a in "${ASSETS[@]}"; do [[ -f "$a" ]] || { err "asset missing: $a"; exit 2; }; done

if $DRY_RUN; then
  info "[dry] git tag -a $VERSION -m \"HOS $VERSION\""
  info "[dry] git push origin $VERSION"
  info "[dry] gh release create $VERSION ${PRERELEASE:+--prerelease} ${NOTES_ARG[*]} <assets>"
  for a in "${ASSETS[@]}"; do info "[dry]   asset: $a"; done
else
  git tag -a "$VERSION" -m "HOS $VERSION"
  git push origin "$VERSION"
  ok "tagged + pushed $VERSION"

  PRE_FLAG=(); $PRERELEASE && PRE_FLAG=(--prerelease)
  gh release create "$VERSION" \
    --title "HOS $VERSION" \
    "${PRE_FLAG[@]}" "${NOTES_ARG[@]}" \
    --target "$(git rev-parse HEAD)" \
    "${ASSETS[@]}"
  ok "published GitHub release $VERSION with bootstrap assets"
fi

# ── Summary — the well-known URLs ─────────────────────────────────────────────
hdr "Done"
BASE="https://github.com/${REPO_SLUG}/releases"
echo ""
echo "  Release:        ${BASE}/tag/${VERSION}"
echo "  Latest assets (always newest release):"
echo "    ${BASE}/latest/download/hos_install.sh"
echo "    ${BASE}/latest/download/hos_bootstrap.sh"
echo "    ${BASE}/latest/download/setup_clis.sh"
echo ""
echo "  Get started on a fresh machine:"
echo "    mkdir -p hos-bootstrap && cd hos-bootstrap"
echo "    for f in hos_bootstrap.sh setup_clis.sh hos_install.sh; do"
echo "      curl -fsSLO ${BASE}/latest/download/\$f; done && chmod +x *.sh"
echo "    ./hos_bootstrap.sh                 # once per machine"
echo "    ./hos_install.sh /path/to/project  # installs ${VERSION} (the latest release)"
echo ""
$DRY_RUN && warn "DRY RUN — nothing was tagged or published."
