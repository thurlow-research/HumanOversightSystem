#!/usr/bin/env bash
# check_pr_reviewed.sh — PR-review idempotency precheck (#1524).
#
# Formalizes a check that individual overseer cycles had been reinventing ad
# hoc, and getting wrong: before Step 1 (bootstrap/overseer-cron-prompt.md)
# reviews a PR, has this exact PR# + head_sha already been reviewed? Four
# incidents (#1288/#1286/#1280, #1306, #1512, #1523) produced a duplicate PR
# comment because that ad hoc check grepped the literal file
# `audit/oversight-log.jsonl` — retired by #888 P5 (commit 1d81eeb8), which
# moved the audit trail to per-event records under audit/log/<YYYY>/<MM>/ — so
# the grep silently matched nothing and was misread as "no prior review." One
# instance (#1523) additionally suppressed the grep's stderr, hiding the
# missing-file error entirely.
#
# This script reads (never writes) the real audit trail via the audit_log
# read-shim, so it can never point at a retired path, and never suppresses
# stderr — a wrong root or a malformed record fails loud, not silently.
#
# Usage:
#   scripts/oversight/check_pr_reviewed.sh <pr#> <head_sha> [root]
#
# <root> defaults to "." (the caller's cwd), matching audit_read_stream's own
# default — the overseer cron session's cwd is already the repo root.
#
# Output (stdout, one line, always valid JSON):
#   {"already_reviewed": true,  "event": "human-required", "timestamp": "..."}
#   {"already_reviewed": false, "event": null, "timestamp": null}
#
# Exit code: 0 always for the reporter (the caller decides what "already
# reviewed" means for this cycle — mirrors audit_predicate.py's CLI
# convention); 2 on a usage error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: check_pr_reviewed.sh <pr#> <head_sha> [root]" >&2
    exit 2
fi

PR="$1"
HEAD_SHA="$2"
ROOT="${3:-.}"

if ! [[ "$PR" =~ ^[0-9]+$ ]]; then
    echo "check_pr_reviewed.sh: <pr#> must be numeric, got: $PR" >&2
    exit 2
fi
if [[ -z "$HEAD_SHA" ]]; then
    echo "check_pr_reviewed.sh: <head_sha> must not be empty" >&2
    exit 2
fi

# shellcheck source=scripts/oversight/lib/audit_log.sh
source "$SCRIPT_DIR/lib/audit_log.sh"

audit_read_stream "$ROOT" | PR="$PR" HEAD_SHA="$HEAD_SHA" python3 -c '
import json
import os
import sys

pr = int(os.environ["PR"])
head_sha = os.environ["HEAD_SHA"]

# Event types that record a completed Step 1 disposition for a PR at a
# specific head SHA (#1524): "pr-review" and "human-required" are the two
# review dispositions overseer.md ever appends; "idempotent-skip" is the
# already-correctly-working precheck output a later cycle logs when it
# re-confirms the same head SHA carries no new information.
REVIEWED_EVENTS = {"pr-review", "human-required", "idempotent-skip"}

match = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    record = json.loads(line)
    if record.get("event") not in REVIEWED_EVENTS:
        continue
    if record.get("pr") != pr:
        continue
    # Schema drift across record ages: older records use "headSha", newer
    # ones "head_sha" (#1524) — check both rather than picking one and
    # silently missing the other.
    record_head_sha = record.get("head_sha") or record.get("headSha")
    if record_head_sha != head_sha:
        continue
    match = record

if match is None:
    print(json.dumps({"already_reviewed": False, "event": None, "timestamp": None}))
else:
    print(json.dumps({
        "already_reviewed": True,
        "event": match.get("event"),
        "timestamp": match.get("timestamp"),
    }))
'
