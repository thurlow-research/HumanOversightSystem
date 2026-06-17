#!/usr/bin/env bash
# check_pre_coder_gate.sh <feature-slug>
#
# Mechanical pre-coder gate (#385). Encodes the worker's pre-coder pipeline check
# as a hard, non-rationalizable shell gate. Run before dispatching coder for a slug.
#
# Exit 0: all three conditions met — coder may be dispatched.
# Exit 1: one or more conditions unmet — every failure is listed (no short-circuit).
# Exit 2: usage error (missing/invalid slug, unknown flag, not a git repo).
#
# Conditions (all evaluated relative to the git root):
#   1. SPEC          docs/specs/SPEC-<slug>.md exists AND is committed in HEAD.
#   2. TECH-DESIGN   >=1 docs/v*/TECHNICAL-DESIGN-<slug>.md exists AND is committed in HEAD.
#   3. ARCHITECT     no .claudetmp/design/architect-<slug>-*.md has REQUEST_CHANGES
#                    as its LAST status: line (absence of any such file passes).
#
# Committed-status (OQ-385-D): staged-but-not-committed counts as NOT committed.
# We test membership in HEAD's tree (git ls-tree), not the index (git ls-files),
# because the index includes a staged-only add.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check_pre_coder_gate.sh <feature-slug>

Verifies the pre-coder pipeline gate for <feature-slug>. Exit 0 only if all hold:
  SPEC         docs/specs/SPEC-<slug>.md exists and is committed
  TECH-DESIGN  a docs/v*/TECHNICAL-DESIGN-<slug>.md exists and is committed
  ARCHITECT    no .claudetmp/design/architect-<slug>-*.md ends in status: REQUEST_CHANGES

<feature-slug> must match: ^[a-z0-9]+(-[a-z0-9]+)*$

Exit codes:
  0  all conditions satisfied
  1  one or more conditions unmet (all reported)
  2  usage error (bad args, unknown flag, invalid slug, not a git repo)
EOF
}

# ── Argument & flag handling (REQ-385-07, 08, 02; OQ-385-A) ──────────────────
case "${1:-}" in
  --help|-h)
    usage
    exit 0
    ;;
  -*)
    echo "[USAGE] unknown flag: $1" >&2
    exit 2
    ;;
esac

if [[ $# -ne 1 ]]; then
  echo "[USAGE] expected exactly one <feature-slug> argument" >&2
  exit 2
fi

slug="$1"
if ! [[ "$slug" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  echo "[USAGE] invalid slug '$slug' (must match ^[a-z0-9]+(-[a-z0-9]+)*\$)" >&2
  exit 2
fi

# ── Git root resolution (REQ-385-22, 23; OQ-385-B) ──────────────────────────
if ! ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || [[ -z "$ROOT" ]]; then
  echo "[USAGE] not inside a git repository" >&2
  exit 2
fi
cd "$ROOT"

shopt -s nullglob

# committed-in-HEAD predicate for a LITERAL path: prints the path if it is in HEAD's
# tree, empty otherwise. Captures status so set -e does not abort on an unborn HEAD.
committed_path() {
  git ls-tree -r --name-only HEAD -- "$1" 2>/dev/null || true
}

# committed-in-HEAD predicate for a GLOB: filters the full HEAD tree with an ERE.
# (git ls-tree pathspecs do not support shell-style globbing, so we list and grep.)
committed_glob_match() {
  # $1 = ERE anchored to a committed path. Prints matching committed paths.
  git ls-tree -r --name-only HEAD 2>/dev/null | grep -E "$1" || true
}

failures=()

# ── Condition 1 — Spec committed (REQ-385-09..11) ───────────────────────────
SPEC="docs/specs/SPEC-${slug}.md"
spec_committed="$(committed_path "$SPEC")"
if [[ ! -f "$SPEC" || -z "$spec_committed" ]]; then
  failures+=("[GATE FAIL] SPEC: ${SPEC} not found or not committed")
fi

# ── Condition 2 — Technical design committed (REQ-385-12..14) ───────────────
TD_GLOB="docs/v*/TECHNICAL-DESIGN-${slug}.md"
# shellcheck disable=SC2206  # intentional glob expansion (nullglob set); no mapfile (bash 3.2)
td_disk=( $TD_GLOB )
# Anchored ERE for a committed docs/v*/TECHNICAL-DESIGN-<slug>.md (v* = no nested dir).
# slug is [a-z0-9-] only (validated above), so it needs no ERE escaping; only '.' does.
TD_ERE="^docs/v[^/]*/TECHNICAL-DESIGN-${slug}\.md\$"
td_committed="$(committed_glob_match "$TD_ERE")"
if [[ -z "$td_committed" ]]; then
  if [[ ${#td_disk[@]} -eq 0 ]]; then
    failures+=("[GATE FAIL] TECH-DESIGN: no file matching ${TD_GLOB} (absent)")
  else
    failures+=("[GATE FAIL] TECH-DESIGN: ${TD_GLOB} present on disk but not committed")
  fi
fi

# ── Condition 3 — No open REQUEST_CHANGES (REQ-385-15..19; OQ-385-B) ─────────
AR_GLOB=".claudetmp/design/architect-${slug}-*.md"
# shellcheck disable=SC2206  # intentional glob expansion (nullglob set); no mapfile (bash 3.2)
ar_matches=( $AR_GLOB )
for f in "${ar_matches[@]}"; do
  last_status="$(grep -iE '^[[:space:]]*status:' "$f" | tail -n 1 || true)"
  [[ -z "$last_status" ]] && continue
  # strip key, trim whitespace, lowercase the value
  val="${last_status#*:}"
  val="${val#"${val%%[![:space:]]*}"}"   # ltrim
  val="${val%"${val##*[![:space:]]}"}"   # rtrim
  val="$(printf '%s' "$val" | tr '[:upper:]' '[:lower:]')"   # lowercase (bash 3.2-safe)
  if [[ "$val" == "request_changes" ]]; then
    failures+=("[GATE FAIL] ARCHITECT: ${f} has status: REQUEST_CHANGES")
  fi
done

# ── Result emission & exit (REQ-385-04..06, 20, 21) ─────────────────────────
if [[ ${#failures[@]} -eq 0 ]]; then
  echo "[GATE PASS] pre-coder gate satisfied for slug: ${slug}"
  exit 0
fi

for line in "${failures[@]}"; do
  echo "$line" >&2
done
exit 1
