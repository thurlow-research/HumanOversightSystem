#!/usr/bin/env bash
# bootstrap/invoke_agent.sh — L3 wrapper for the deterministic agent-invocation
# primitive (#1643 slice W1).
#
# Fixed argv over scripts/automation/agent_invoke_cli.py: every flag is
# `--name value`, so the argv shape is statically allowlistable as
# `Bash(bash bootstrap/invoke_agent.sh *)` (AD-1). This script does the
# minimum required to make that true and nothing more.
#
# This script must NEVER grow a JSON literal, a printf/echo to stdout, or any
# re-derivation of a field — the record schema is agent_invoke_cli.py's alone
# (ADR-1643 AD-1; docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md
# §3.9). Adding a document field is a change to that module only, never to
# this one. It also must never grow a `case` statement, a flag of its own, or
# any validation/default/re-derivation of a caller-supplied flag.
#
# Usage:
#   bash bootstrap/invoke_agent.sh --agent <name> --input-file <path> \
#       --posture <name> [--dimension <id>] [--binding <id>] [--lens <name>] \
#       [--timeout <seconds>] [--grace <seconds>] [--model <alias>] \
#       [--step <string>] [--head-sha <sha>] [--base-sha <sha>] \
#       [--matched-file <path> ...] [--prompt-template-version <str>] \
#       [--output-file <path>] [--not-applicable <reason>] [--require-env-auth]
#
# Mints NO token: this surface performs no GitHub I/O (AD-1). Composes no
# JSON: the prompt/context is a file the caller writes and passes via
# --input-file; this script never touches its contents.
#
# --require-env-auth is MANDATORY for every non-interactive caller (ADR-1643
# Amendment 1 §9.3) — bin/hos-cron in either role, the sweep runner, and any
# script a cron cycle executes. It is optional only for a human at a terminal
# or an agent session invoking this wrapper by hand. This script does not
# enforce the flag itself (that would be re-derivation of a caller
# obligation); it is documented here so the obligation travels with the
# canonical entry point.
#
# Exit codes (owned entirely by agent_invoke_cli.py — see its module
# docstring and docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md
# §3.3; this script never computes one of its own):
#   0 — the invocation was attempted and a result document was produced
#       (whatever it says)
#   1 — operational failure of the primitive itself (no document produced)
#   2 — usage error (no document produced)
#   3 — never produced by this surface; reserved
#
# stdout is exactly one JSON object, always — it is agent_invoke_cli.py's,
# passed through byte-for-byte. Never suppress this script's stderr (#1523).
#
# Requires: python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

if ! command -v python3 >/dev/null 2>&1; then
    echo "invoke_agent.sh: error: python3 not found on PATH" >&2
    exit 1
fi

exec python3 "$REPO_ROOT/scripts/automation/agent_invoke_cli.py" "$@"
