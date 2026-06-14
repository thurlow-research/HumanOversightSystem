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
NOTE_SUFFIX=""
if $SKIP_VALIDATION; then
  # An ungated release must be a deliberate, audited act — require an explicit
  # env opt-in so a stray flag can't ship one, and STAMP the artifact so the
  # release self-documents that the gate was skipped (the audit trail matters).
  if [[ "${HOS_ALLOW_UNVALIDATED:-}" != "1" ]]; then
    err "--skip-validation refused: this would ship an UNVALIDATED release."
    err "If you truly mean it, re-run with HOS_ALLOW_UNVALIDATED=1 set."
    exit 1
  fi
  warn "VALIDATION SKIPPED (HOS_ALLOW_UNVALIDATED=1) — this release is NOT gated."
  NOTE_SUFFIX=$'\n\n> \xE2\x9A\xA0 VALIDATION SKIPPED — cut with --skip-validation; NOT gated by the validation suite.'
else
  info "running full validation suite (static → self → external → docs → compliance)..."
  if $DRY_RUN; then
    info "[dry] would run: scripts/framework/run_framework_validation.sh ${VALIDATION_ARGS[*]:-}"
  else
    rc=0
    if (( ${#VALIDATION_ARGS[@]} )); then
      bash scripts/framework/run_framework_validation.sh "${VALIDATION_ARGS[@]}" || rc=$?
    else
      bash scripts/framework/run_framework_validation.sh || rc=$?
    fi
    if [[ "$rc" -ne 0 ]]; then
      err "validation did NOT pass (exit $rc) — refusing to cut a release. Fix findings (or"
      err "converge the external-review ledger), then re-run. Override only with --skip-validation."
      exit 1
    fi
    ok "validation passed — clear to release"
  fi
fi

# ── Tag + publish + assets ────────────────────────────────────────────────────
hdr "4. Publish release + upload bootstrap assets"
CLEANUP=()
cleanup() { for f in "${CLEANUP[@]:-}"; do [[ -n "$f" && -e "$f" ]] && rm -rf "$f"; done; }
trap cleanup EXIT

# Release notes (built directly — no mapfile/bash-4-isms; portable to bash 3.2).
# A skipped-validation release MUST carry its stamp, so when NOTE_SUFFIX is set we
# author explicit notes (cannot combine with --generate-notes).
NOTES_ARG=()
if [[ -n "$NOTE_SUFFIX" ]]; then
  NF="$(mktemp "${TMPDIR:-/tmp}/hos-notes.XXXXXX")"; CLEANUP+=("$NF")
  if [[ -n "$NOTES_FILE" ]]; then cat "$NOTES_FILE" > "$NF"; else printf 'Release %s.' "$VERSION" > "$NF"; fi
  printf '%s\n' "$NOTE_SUFFIX" >> "$NF"
  NOTES_ARG=(--notes-file "$NF")
elif [[ -n "$NOTES_FILE" ]]; then
  NOTES_ARG=(--notes-file "$NOTES_FILE")
else
  NOTES_ARG=(--generate-notes)
fi

# Build the assets from the TAGGED COMMIT (HEAD), not the working tree — so the
# published scripts always match the release source even under --allow-dirty, and
# any files validation touched (e.g. stamps) don't leak into the assets.
HEAD_SHA="$(git rev-parse HEAD)"
sha256() { if command -v sha256sum &>/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
ASSET_NAMES=(hos_install.sh hos_bootstrap.sh setup_clis.sh)
ASSET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hos-assets.XXXXXX")"; CLEANUP+=("$ASSET_DIR")
for n in "${ASSET_NAMES[@]}"; do
  git show "$HEAD_SHA:bootstrap/$n" > "$ASSET_DIR/$n" 2>/dev/null \
    || { err "asset bootstrap/$n is not in commit ${HEAD_SHA:0:8} — commit it before releasing"; exit 2; }
done
( cd "$ASSET_DIR" && sha256 "${ASSET_NAMES[@]}" ) > "$ASSET_DIR/SHA256SUMS"
UPLOAD=(); for n in "${ASSET_NAMES[@]}" SHA256SUMS; do UPLOAD+=("$ASSET_DIR/$n"); done

# A pre-release is EXCLUDED from GitHub's /releases/latest/, which is exactly
# what the install command and the docs' /latest/download/ URLs resolve against
# — so a pre-release silently 404s every consumer. Publish a real release as
# --latest; warn loudly when --prerelease is requested. (#97)
PRE_FLAG=(); LATEST_FLAG=(--latest)
if $PRERELEASE; then
  PRE_FLAG=(--prerelease)
  LATEST_FLAG=()
  info "⚠  --prerelease: GitHub excludes pre-releases from /releases/latest/."
  info "⚠  The install command and docs' /latest/download/ URLs will 404 until you promote:"
  info "⚠      gh release edit $VERSION --prerelease=false --latest"
fi

if $DRY_RUN; then
  info "[dry] gh release create $VERSION --draft ${PRE_FLAG[*]} ${NOTES_ARG[*]} --target ${HEAD_SHA:0:8}"
  for n in "${ASSET_NAMES[@]}" SHA256SUMS; do info "[dry]   asset (from commit): $n"; done
  info "[dry] verify assets present, then gh release edit --draft=false ${LATEST_FLAG[*]} (atomic publish)"
else
  # DRAFT first: gh creates the tag + a hidden draft release and uploads assets.
  # A failed upload never leaves a half-published release — we clean it up and
  # the version stays available for a clean re-run (fixes the false-atomicity).
  if ! gh release create "$VERSION" --draft --title "HOS $VERSION" \
        "${PRE_FLAG[@]}" "${NOTES_ARG[@]}" --target "$HEAD_SHA" "${UPLOAD[@]}"; then
    gh release delete "$VERSION" --yes --cleanup-tag 2>/dev/null || true
    err "draft release create/upload failed — cleaned up draft + tag. Re-run."
    exit 1
  fi
  # Verify every expected asset actually uploaded before flipping to published.
  got="$(gh release view "$VERSION" --json assets -q '.assets[].name' 2>/dev/null | tr '\n' ' ')"
  for n in "${ASSET_NAMES[@]}" SHA256SUMS; do
    case " $got " in
      *" $n "*) : ;;
      *) gh release delete "$VERSION" --yes --cleanup-tag 2>/dev/null || true
         err "asset '$n' missing after upload — cleaned up draft + tag. Re-run."; exit 1 ;;
    esac
  done
  # Atomic-ish publish: all assets verified present, now make it visible.
  # --latest (for a non-prerelease) ensures /releases/latest/ resolves to it, so
  # the docs' /latest/download/ install URLs work immediately. (#97)
  if ! gh release edit "$VERSION" --draft=false "${LATEST_FLAG[@]}"; then
    err "assets uploaded but publishing the draft failed. Finish manually:"
    err "    gh release edit $VERSION --draft=false"
    exit 1
  fi
  ok "published GitHub release $VERSION (assets from commit ${HEAD_SHA:0:8}) + SHA256SUMS"
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
