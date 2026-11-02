#!/usr/bin/env bash
# write_pr_review_event.sh — canonical writer for PR-review audit events (#1699).
#
# The reader (check_pr_reviewed.sh, #1524) matches a closed set of event names.
# Overseer cycles used to hand-compose `audit_write_event '{"event":...}'` JSON,
# so the name drifted (`pr-reviewed`, `pr-review-skipped-idempotent`) and the
# precheck missed real review records. This is the one allowlistable command that
# writes them: the vocabulary lives in lib/review_events.py, shared with the
# reader, and the writer refuses legacy aliases and unknown names.
#
# Usage:
#   bash scripts/oversight/write_pr_review_event.sh --pr <n> --head-sha <40-hex> \
#       --event <pr-review|idempotent-skip> \
#       [--decision <s>] [--tier <s>] [--comment-url <url>] [--reason <s>] \
#       [--root <dir>]
#
# `human-required` is refused: it carries SPEC-378 fields this writer does not
# model, so it stays on audit_write_event (overseer.md § Halt-on-failure ordering).
#
# --root defaults to "." (the caller's cwd). Prints the record path relative to
# audit/log on stdout.
#
# Exit code: 0 on success; 2 on a usage error (bad pr/sha, alias, unknown event).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Isolated mode (-I) keeps the caller's cwd and PYTHONPATH off sys.path, so a
# planted scripts/ package in the cwd cannot shadow the trusted one (CWE-426).
# The repo root is inserted explicitly; cwd is unchanged, so a relative --root
# still resolves against the caller's directory.
exec python3 -I -c '
import sys
sys.path.insert(0, sys.argv[1])
from scripts.oversight.lib.review_events import _main
sys.exit(_main(["write", *sys.argv[2:]]))
' "$REPO_ROOT" "$@"
