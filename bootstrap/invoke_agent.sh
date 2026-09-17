#!/usr/bin/env bash
# bootstrap/invoke_agent.sh — L3 wrapper for the deterministic agent-invocation
# primitive (#1643 slice W1).
#
# BOUNDARY (ADR-1643 AD-1 + AD-1a, §10.1). This script may contain only
# logic whose inputs are its own location on disk and the host's ability to
# start agent_invoke_cli.py, and whose outputs are only the exec or a
# non-zero exit with one stderr line. Concretely it MAY: resolve its own
# directory and the repo root; select the interpreter (the three-rung
# ladder below); fail with one stderr line when it cannot. It must NEVER:
# read or branch on any element of "$@"; write to stdout; compose or emit
# JSON or re-derive any field (the record schema is agent_invoke_cli.py's
# alone — adding a document field is a change to that module, never to this
# one); validate or default a caller-supplied flag; add a flag of its own;
# grow a `case` statement; mint or revoke a token; or mutate its
# environment (no pip install, no venv build or repair — ensure_venv.sh is
# named in the error message and never invoked here).
#
# The test for any proposed addition: does it read the caller's arguments,
# or produce a value a consumer parses? If either, it belongs in
# agent_invoke_cli.py. The ladder is the maximum this file grows —
# "it is only launch logic" is how a wrapper that must not grow, grows.
#
# INVOKE_AGENT_PYTHON is a diagnostic/test seam only (ADR-1643 §10.3). It
# is deliberately NOT the repo-wide OVERSIGHT_PYTHON; agent_invoke_cli.py
# never reads it; and no committed non-interactive caller may set it.
#
# Fixed argv over scripts/automation/agent_invoke_cli.py: every flag is
# `--name value`, so the argv shape is statically allowlistable as
# `Bash(bash bootstrap/invoke_agent.sh *)` (AD-1). This script does the
# minimum required to make that true and nothing more.
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
# §3.3; this script never computes a document-bearing exit code of its own):
#   0 — the invocation was attempted and a result document was produced
#       (whatever it says)
#   1 — operational failure (no document produced) — either
#       agent_invoke_cli.py's own (§3.3), or one of this script's two
#       interpreter-resolution failures below (§3.9)
#   2 — usage error (no document produced)
#   3 — never produced by this surface; reserved
#
# stdout is exactly one JSON object, always, on the exit-0 path — it is
# agent_invoke_cli.py's, passed through byte-for-byte. On this script's own
# exit-1 paths (interpreter resolution failed) stdout is empty. Never
# suppress this script's stderr (#1523).
#
# Interpreter resolution (TD-D22, ADR-1643 §10) — a fixed three-rung ladder,
# in this order, and no other rung. This is launch, not logic (AD-1a): it
# never reads "$@", writes nothing to stdout, and emits no field.
#   1. $INVOKE_AGENT_PYTHON, when set and non-empty — set-but-not-executable
#      is a hard error, never a silent fall-through to rung 2.
#   2. scripts/oversight/.venv/bin/python, when executable — this repo's
#      established idiom (run_gates.sh, prompt_audit.sh).
#   3. python3 from PATH, when `command -v` finds it — safe as a last rung
#      only because agent_invoke_cli.py's own P0 (TD-D23) fails closed on an
#      interpreter that lacks its module-level runtime dependencies; it is
#      not a silent degradation path.
# None of the three resolvable ⟹ exit 1, one stderr line naming all three
# rungs and pointing at ensure_venv.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
VENV_PYTHON="$REPO_ROOT/scripts/oversight/.venv/bin/python"

PYTHON=""
if [[ -n "${INVOKE_AGENT_PYTHON:-}" ]]; then
    if [[ ! -x "$INVOKE_AGENT_PYTHON" ]]; then
        echo "invoke_agent.sh: error: INVOKE_AGENT_PYTHON is set but not executable: $INVOKE_AGENT_PYTHON" >&2
        exit 1
    fi
    PYTHON="$INVOKE_AGENT_PYTHON"
elif [[ -x "$VENV_PYTHON" ]]; then
    PYTHON="$VENV_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "invoke_agent.sh: error: no interpreter found — checked \$INVOKE_AGENT_PYTHON (unset), $VENV_PYTHON, and python3 on PATH — run: bash scripts/oversight/ensure_venv.sh" >&2
    exit 1
fi

exec "$PYTHON" "$REPO_ROOT/scripts/automation/agent_invoke_cli.py" "$@"
