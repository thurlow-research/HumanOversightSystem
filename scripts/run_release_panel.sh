#!/usr/bin/env bash
# scripts/run_release_panel.sh — thin entry point for the release panel
# (ADR-1340 AD-1 / TECHNICAL-DESIGN-1340-release-panel.md §2).
#
# Owns exactly four things and NO review logic: range derivation (AD-2), the
# verdict contract (AD-4), --verify (AD-7), and delegation to
# `scripts/run_panel.sh --release-range`. The panel engine itself (chunking,
# fan-out, arbiter, corroboration ranking) lives entirely in run_panel.sh and
# is never re-implemented here (D41).
#
# Usage:
#   scripts/run_release_panel.sh --issue <n> [--dry-run]
#   scripts/run_release_panel.sh --verify --issue <n> [--author <login>]
#   scripts/run_release_panel.sh --help
#
# --issue <n>    Required in both modes. Execute: the release-request issue
#                the verdict comment is posted to. Verify: the issue whose
#                comments are searched for a posted verdict.
# --verify       Verification mode. NEVER invokes run_panel.sh, NEVER invokes
#                agy/codex/claude. Recomputes everything it can (AD-7) rather
#                than trusting the posted claim.
# --dry-run      Execute mode only. Runs the panel, composes the verdict,
#                prints the comment body to stdout, POSTS NOTHING.
# --author <l>   Verify mode only. Resolution order: --author, then
#                $HOS_EXPECTED_BOT_LOGIN, then BOT_WORKER_USERNAME from
#                scripts/framework/machine-accounts.env. Unresolvable -> exit
#                1 (fail-closed — never "accept any author", which would
#                discard AD-7's only identity bound).
#
# Exit codes (the R2 contract — published, do not renumber):
#   0  PASS                                                        (both)
#   1  usage error / missing prerequisite / author-unresolved      (both)
#   2  range-derivation-failed: shallow clone                      (both)
#   3  range-derivation-failed: no tag reachable from HEAD         (both)
#   4  NO-CONTENT: zero files after exclusions                     (both)
#   5  operational failure (panel-artifact-missing / post-failed /
#      comments-unreadable)                                        (both)
#   6  verdict composed and posted, result = FAIL                  (execute)
#   7  verdict-missing — no block matched author + head SHA        (verify)
#   8  a verdict check failed — reason names which                 (verify)
#
# The last line of stdout in both modes is machine-greppable and stable:
#   release-panel: <execute|verify> <PASS|FAIL|NO-CONTENT|REFUSED> reason=<slug> base=<sha12> head=<sha12> files_reviewed=<n>
#
# This entry point is PR 1 of ADR-1340 (AD-9) — deliberately inert. Nothing in
# this repository invokes it yet; PR 2 arms it in worker.md's R2.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[31m"; YELLOW="\033[33m"; GREEN="\033[32m"; CYAN="\033[36m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }

RELEASE_LOGIC="$SCRIPT_DIR/oversight/release_panel_logic.py"
EXCLUSIONS="$SCRIPT_DIR/oversight/release_panel_exclusions.txt"
PANEL_SH="$SCRIPT_DIR/run_panel.sh"
POST_COMMENT_SH="$REPO_ROOT/bootstrap/post_comment.sh"
QUERY_ISSUES_SH="$REPO_ROOT/bootstrap/query_issues.sh"
MACHINE_ACCOUNTS_ENV="$REPO_ROOT/scripts/framework/machine-accounts.env"

usage() { sed -n '2,46p' "$0" | sed 's/^# \{0,1\}//'; }

sha12() { [[ -n "${1:-}" && "$1" != "null" ]] && printf '%s' "${1:0:12}" || printf 'none'; }

emit_last_line() {  # $1=mode $2=status $3=reason $4=base12 $5=head12 $6=files_reviewed
  printf 'release-panel: %s %s reason=%s base=%s head=%s files_reviewed=%s\n' \
    "$1" "$2" "${3:-none}" "$4" "$5" "${6:-0}"
}

MODE="execute"
ISSUE=""
DRY_RUN=0
AUTHOR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue)   [[ $# -ge 2 ]] || { err "--issue needs a value"; exit 1; }
               ISSUE="$2"; shift 2 ;;
    --verify)  MODE="verify"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --author)  [[ $# -ge 2 ]] || { err "--author needs a value"; exit 1; }
               AUTHOR="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *)         err "Unknown option: $1  (try --help)"; exit 1 ;;
  esac
done

case "$ISSUE" in
  ''|*[!0-9]*) err "--issue is required and must be a positive integer"; exit 1 ;;
esac

if [[ "$MODE" == "verify" && "$DRY_RUN" -eq 1 ]]; then
  err "--verify --dry-run is a usage error (verify posts nothing anyway)"
  exit 1
fi

# ── Preflight ────────────────────────────────────────────────────────────────
for bin in git python3 jq; do
  command -v "$bin" >/dev/null 2>&1 || { err "$bin not found — see setup_clis.sh"; exit 1; }
done
for f in "$PANEL_SH" "$RELEASE_LOGIC" "$EXCLUSIONS" "$POST_COMMENT_SH"; do
  [[ -f "$f" ]] || { err "required file missing: $f"; exit 1; }
done

if [[ "$MODE" == "execute" ]]; then
  # ── Step 2: derive the range (AD-2) ─────────────────────────────────────
  RANGE_JSON="$(python3 "$RELEASE_LOGIC" derive-range --exclusions "$EXCLUSIONS" --cwd "$REPO_ROOT")" || true
  RANGE_STATE="$(printf '%s' "$RANGE_JSON" | jq -r '.state // empty')"
  BASE_REF="$(printf '%s' "$RANGE_JSON" | jq -r '.base_ref // empty')"
  BASE_SHA="$(printf '%s' "$RANGE_JSON" | jq -r '.base_sha // empty')"
  HEAD_SHA="$(printf '%s' "$RANGE_JSON" | jq -r '.head_sha // empty')"
  REASON="$(printf '%s' "$RANGE_JSON" | jq -r '.reason // empty')"
  REMEDIATION="$(printf '%s' "$RANGE_JSON" | jq -r '.remediation // empty')"

  case "$RANGE_STATE" in
    SHALLOW)
      err "$REASON"
      [[ -n "$REMEDIATION" ]] && err "remediation: $REMEDIATION"
      emit_last_line execute REFUSED "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
      exit 2 ;;
    NO_TAG)
      err "$REASON"
      emit_last_line execute REFUSED "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
      exit 3 ;;
    NO_CONTENT)
      warn "$REASON"
      emit_last_line execute NO-CONTENT "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
      exit 4 ;;
    OK) ;;
    *) err "unexpected range-derivation state: '$RANGE_STATE'"; exit 1 ;;
  esac

  info "range: ${BASE_REF} (${BASE_SHA:0:12})..${HEAD_SHA:0:12}"

  # ── Step 3: run id + run dir (env-var seam, release mode only — C6) ─────
  RUN_ID="$(python3 "$RELEASE_LOGIC" new-run-id)"
  mkdir -p "$REPO_ROOT/.ai-local/panel/release"
  RUN_DIR="$REPO_ROOT/.ai-local/panel/release/${HEAD_SHA}-$(date -u +%Y%m%d-%H%M%S)"
  mkdir -p "$RUN_DIR"
  export PANEL_RUN_DIR="$RUN_DIR"
  printf '%s' "$RANGE_JSON" > "$RUN_DIR/range.json"

  # ── Step 4: delegate to the engine ──────────────────────────────────────
  PANEL_ARGS=(--release-range "${BASE_SHA}..${HEAD_SHA}")
  [[ "$DRY_RUN" -eq 1 ]] && PANEL_ARGS+=(--dry-run)
  set +e
  bash "$PANEL_SH" "${PANEL_ARGS[@]}"
  PANEL_EXIT=$?
  set -e

  if [[ ! -f "$RUN_DIR/panel-release.json" ]]; then
    err "panel-artifact-missing: $RUN_DIR/panel-release.json was not written (the engine aborted before writing a verdict)"
    emit_last_line execute FAIL panel-artifact-missing "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
    exit 5
  fi

  # ── Step 5: compose ──────────────────────────────────────────────────────
  VERDICT_FILE="$RUN_DIR/verdict.json"
  BODY_FILE="$RUN_DIR/comment-body.md"
  python3 "$RELEASE_LOGIC" compose \
    --range-json "$RUN_DIR/range.json" --panel-json "$RUN_DIR/panel-release.json" \
    --exclusions "$EXCLUSIONS" --run-id "$RUN_ID" --issue "$ISSUE" \
    --panel-exit "$PANEL_EXIT" --out-verdict "$VERDICT_FILE" --out-body "$BODY_FILE" >/dev/null || true

  [[ -f "$VERDICT_FILE" ]] || { err "panel-artifact-missing: compose did not write $VERDICT_FILE"; emit_last_line execute FAIL panel-artifact-missing "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0; exit 5; }

  RESULT="$(jq -r '.result' "$VERDICT_FILE")"
  VERDICT_REASON="$(jq -r '.verdict_reason // empty' "$VERDICT_FILE")"
  FILES_REVIEWED="$(jq -r '.coverage.files_reviewed' "$VERDICT_FILE")"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    warn "dry-run: nothing posted to issue #$ISSUE. Verdict + body in $RUN_DIR"
    echo ""
    cat "$BODY_FILE"
    echo ""
    emit_last_line execute "$RESULT" "$VERDICT_REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" "$FILES_REVIEWED"
    [[ "$RESULT" == "PASS" ]] && exit 0 || exit 6
  fi

  # ── Step 6: post (bootstrap/post_comment.sh only — never gh api -f body=@path, #1155) ─
  if ! bash "$POST_COMMENT_SH" --number "$ISSUE" --body-file "$BODY_FILE" --app worker >/dev/null; then
    err "post-failed: could not post the verdict comment to issue #$ISSUE — the verdict lives only in the gitignored $RUN_DIR and has not crossed the clone boundary"
    emit_last_line execute FAIL post-failed "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" "$FILES_REVIEWED"
    exit 5
  fi
  ok "posted release-panel verdict ($RESULT) to issue #$ISSUE"

  emit_last_line execute "$RESULT" "$VERDICT_REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" "$FILES_REVIEWED"
  [[ "$RESULT" == "PASS" ]] && exit 0 || exit 6
fi

# ── Verify mode (AD-7) — never invokes run_panel.sh or a vendor CLI ────────
[[ -f "$QUERY_ISSUES_SH" ]] || { err "required file missing: $QUERY_ISSUES_SH"; exit 1; }

if [[ -z "$AUTHOR" ]]; then
  AUTHOR="${HOS_EXPECTED_BOT_LOGIN:-}"
fi
if [[ -z "$AUTHOR" && -f "$MACHINE_ACCOUNTS_ENV" ]]; then
  # shellcheck source=/dev/null
  source "$MACHINE_ACCOUNTS_ENV"
  AUTHOR="${BOT_WORKER_USERNAME:-}"
fi
[[ -n "$AUTHOR" ]] || { err "author-unresolved: pass --author, or set HOS_EXPECTED_BOT_LOGIN — never falls back to accepting any author"; exit 1; }

RANGE_JSON="$(python3 "$RELEASE_LOGIC" derive-range --exclusions "$EXCLUSIONS" --cwd "$REPO_ROOT")" || true
RANGE_STATE="$(printf '%s' "$RANGE_JSON" | jq -r '.state // empty')"
BASE_SHA="$(printf '%s' "$RANGE_JSON" | jq -r '.base_sha // empty')"
HEAD_SHA="$(printf '%s' "$RANGE_JSON" | jq -r '.head_sha // empty')"
REASON="$(printf '%s' "$RANGE_JSON" | jq -r '.reason // empty')"
REMEDIATION="$(printf '%s' "$RANGE_JSON" | jq -r '.remediation // empty')"

case "$RANGE_STATE" in
  SHALLOW)
    err "$REASON"
    [[ -n "$REMEDIATION" ]] && err "remediation: $REMEDIATION"
    emit_last_line verify REFUSED "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
    exit 2 ;;
  NO_TAG)
    err "$REASON"
    emit_last_line verify REFUSED "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
    exit 3 ;;
  NO_CONTENT)
    warn "$REASON"
    emit_last_line verify NO-CONTENT "$REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
    exit 4 ;;
  OK) ;;
  *) err "unexpected range-derivation state: '$RANGE_STATE'"; exit 1 ;;
esac

COMMENTS_FILE="$(mktemp)"
trap 'rm -f "$COMMENTS_FILE"' EXIT
if ! bash "$QUERY_ISSUES_SH" --app worker --comments-json "$ISSUE" > "$COMMENTS_FILE"; then
  err "comments-unreadable: could not read comments for issue #$ISSUE"
  emit_last_line verify FAIL comments-unreadable "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
  exit 5
fi

set +e
VERIFY_JSON="$(python3 "$RELEASE_LOGIC" verify \
  --comments-json "$COMMENTS_FILE" --exclusions "$EXCLUSIONS" --author "$AUTHOR" --cwd "$REPO_ROOT")"
VERIFY_EXIT=$?
set -e

VERIFY_RESULT="$(printf '%s' "$VERIFY_JSON" | jq -r '.result // "FAIL"')"
VERIFY_REASON="$(printf '%s' "$VERIFY_JSON" | jq -r '.reason // empty')"

printf '%s' "$VERIFY_JSON" | jq -r \
  '.checks[]? | "  " + (if .ok then "✔" else "✘" end) + "  " + .name + "  expected=" + .expected + " actual=" + .actual'
echo ""
if [[ "$VERIFY_RESULT" == "PASS" ]]; then
  ok "release-panel verify: PASS"
else
  err "release-panel verify: FAIL (${VERIFY_REASON:-unknown})"
fi

emit_last_line verify "$VERIFY_RESULT" "$VERIFY_REASON" "$(sha12 "$BASE_SHA")" "$(sha12 "$HEAD_SHA")" 0
exit "$VERIFY_EXIT"
