#!/usr/bin/env bash
# check_agents_static.sh — fast static consistency checker for the agent pipeline.
#
# No AI calls. Checks structural correctness deterministically:
#   1. Every agent named in docs/AGENTS.md has a .claude/agents/*.md file
#   2. Every file path referenced in agent files exists on disk
#   3. Every agent named in an "escalates to" / "invoked by" line resolves to a known agent
#   4. The project-start doc outputs referenced in agent files share a consistent path
#
# Exit codes:
#   0 — clean
#   1 — one or more findings (blocking)
#   2 — usage error or missing required files
#
# Usage:
#   ./scripts/framework/check_agents_static.sh
#   ./scripts/framework/check_agents_static.sh --agents-dir .claude/agents --docs docs/AGENTS.md
#   ./scripts/framework/check_agents_static.sh --quiet   # suppress per-finding output; only print summary

set -euo pipefail

AGENTS_DIR=".claude/agents"
DOCS_AGENTS="docs/AGENTS.md"
QUIET=false
FINDINGS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agents-dir) AGENTS_DIR="$2"; shift 2 ;;
        --docs)       DOCS_AGENTS="$2"; shift 2 ;;
        --quiet)      QUIET=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# Load project config (provides PROJECT_NON_AGENT_TOKENS, EXTERNAL_AGENTS, etc.)
# EXTERNAL_AGENTS: pipe-separated agent names that are valid but intentionally absent
# from .claude/agents/ — e.g. consumer-project agents documented in HOS's docs/AGENTS.md
# but installed only in target projects, not in the framework source itself.
PROJECT_NON_AGENT_TOKENS=""
EXTERNAL_AGENTS=""
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh

fail() { echo "  FAIL: $1"; FINDINGS=$(( FINDINGS + 1 )); }
warn() { $QUIET || echo "  WARN: $1"; }
ok()   { $QUIET || echo "  OK:   $1"; }
section() { $QUIET || echo ""; $QUIET || echo "── $1 ──────────────────────────────────────────"; }

if [[ ! -d "$AGENTS_DIR" ]]; then
    echo "ERROR: agents directory not found: $AGENTS_DIR" >&2; exit 2
fi

# ── 1. Build canonical agent name list from .claude/agents/ ─────────────────
section "1. Agent file inventory"

# Collect names into a newline-separated string (bash 3.2 compatible — no -A)
KNOWN_AGENTS=""
while IFS= read -r -d '' f; do
    name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')
    if [[ -n "$name" ]]; then
        KNOWN_AGENTS="${KNOWN_AGENTS}${name}
"
        ok "$name → $f"
    else
        warn "No 'name:' frontmatter in $f"
    fi
done < <(find "$AGENTS_DIR" -name '*.md' -print0)

# ── 2. Every agent named in docs/AGENTS.md has a file ───────────────────────
section "2. docs/AGENTS.md agent name coverage"

if [[ -f "$DOCS_AGENTS" ]]; then
    # Extract backtick-quoted names on lines starting with ### N. `name`
    while IFS= read -r line; do
        agent=$(echo "$line" | grep -oE '`[a-z][a-z0-9_-]+`' | head -1 | tr -d '`')
        [[ -z "$agent" ]] && continue
        # Skip agents declared as external (live in consumer projects, not locally)
        if [[ -n "$EXTERNAL_AGENTS" ]] && echo "$agent" | grep -qE "^($EXTERNAL_AGENTS)$"; then
            ok "$agent declared as external — exists in consumer projects (skip)"
            continue
        fi
        if echo "$KNOWN_AGENTS" | grep -qx "$agent"; then
            ok "$agent referenced in docs and has agent file"
        else
            fail "$agent referenced in $DOCS_AGENTS but no .claude/agents/$agent.md found"
        fi
    done < <(grep '^### [0-9]' "$DOCS_AGENTS")
else
    warn "$DOCS_AGENTS not found — skipping doc coverage check"
fi

# ── 3. File paths in agent system prompts exist on disk ─────────────────────
section "3. File path references in agent files"

# Only check paths that contain a directory separator — bare filenames like
# `tokens.css` or `TECHNICAL-DESIGN.md` are prose shorthand, not path claims.
# Output documents produced at project-start don't exist yet — exempt them.
# Extraction (grep -oE at the old line 128) and the per-reference SKIP/CHECK
# cascade are now in scripts/oversight/agents_static_logic.py (SPEC-336). The
# shell still iterates files, derives the cleaned path for the existence test +
# display, and runs the [[ -e ]] check; it no longer re-implements the cascade.
LOGIC_PY="scripts/oversight/agents_static_logic.py"
OUTPUT_DOCS="docs/pm/CONFIRMED-REQUIREMENTS.md
docs/design/UX-DESIGN-READINESS.md
docs/architecture/ADR-001-pilot.md
docs/design/TECHNICAL-DESIGN.md
docs/ops/TELEMETRY-SPEC.md
contract/step-manifest.yaml
contract/gate-suspension.md
audit/oversight-log.jsonl
audit/overnight-loop-log.md
scripts/framework/config.sh"

# The Python filter is called WITHOUT the output-doc list so that an output-doc
# reference returns CHECK (not SKIP); the shell then emits the distinct
# "(output doc — existence not required)" OK line, preserving the original
# OK/WARN output verbatim (spec §5: no behavior change). Pure skip cases (http,
# empty, bare filename, {template}, PROJECT/) are decided entirely in Python.
while IFS= read -r -d '' f; do
    agent_name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')
    while IFS= read -r ref; do
        verdict=$(python3 "$LOGIC_PY" filter-path-ref "$ref")
        [[ "$verdict" == SKIP ]] && continue
        # CHECK: derive the cleaned path (display + existence test only — the
        # classification decision already happened in Python).
        ref_clean=$(echo "$ref" | tr -d '`"' | sed 's/#.*//' | xargs)
        # Exempt project-start output docs — written during the build, not before.
        if echo "$OUTPUT_DOCS" | grep -qx "$ref_clean"; then
            ok "[$agent_name] $ref_clean (output doc — existence not required)"
            continue
        fi
        if [[ -e "$ref_clean" ]]; then
            ok "[$agent_name] $ref_clean"
        else
            fail "[$agent_name] referenced path not found: $ref_clean"
        fi
    done < <(python3 "$LOGIC_PY" extract-path-refs < "$f" || true)
done < <(find "$AGENTS_DIR" -name '*.md' -print0)

# ── 4. Escalation targets resolve to known agents ────────────────────────────
section "4. Escalation target resolution"

# Escalation-target extraction (formerly an inline python heredoc) and the
# three-stage exclusion cascade now live in scripts/oversight/agents_static_logic.py
# (SPEC-336). The shell assembles the token lists (binding 4: config.sh stays in
# shell), passes the per-file content on stdin (no `open('$f')` quoting hazard),
# classifies each token, and runs the final KNOWN_AGENTS existence test for CHECK.

# Generic tokens that appear in escalation-like phrases but are never agent names.
# Do NOT add project-specific hostnames or service names here — those belong in
# scripts/framework/config.sh as PROJECT_NON_AGENT_TOKENS.
NON_AGENT_TOKENS="human|you|main|build|prod|staging|ci|github|pr"
NON_AGENT_TOKENS="${NON_AGENT_TOKENS}${PROJECT_NON_AGENT_TOKENS:+|$PROJECT_NON_AGENT_TOKENS}"
# Agent names either contain a hyphen (e.g. code-reviewer, pm-agent) or are single
# known short names. Skip library names, types, and status values.
KNOWN_SHORT_AGENTS="architect|coder|human"
# GitHub labels and HOS workflow tokens are not agent names — skip them.
KNOWN_LABELS="needs-human|needs-ai|needs-coordination|hos-claimed|hos-halt|hos-budget-gated|hos-embargo|hos-autowork-authorized|release-request|release-authorized"

# KNOWN_AGENTS is a newline-separated string; the classifier takes a pipe-joined
# alternation, so join once (trim the trailing pipe).
KNOWN_AGENTS_PIPE=$(echo "$KNOWN_AGENTS" | grep -v '^$' | tr '\n' '|' | sed 's/|$//')

while IFS= read -r -d '' f; do
    agent_name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')
    while IFS= read -r target; do
        [[ -z "$target" ]] && continue
        verdict=$(python3 "$LOGIC_PY" classify-token \
            "$target" "$KNOWN_AGENTS_PIPE" "$NON_AGENT_TOKENS" \
            "$KNOWN_LABELS" "$KNOWN_SHORT_AGENTS" "$EXTERNAL_AGENTS")
        case "$verdict" in
            SKIP) continue ;;
            EXTERNAL)
                ok "[$agent_name] → $target (external — lives in consumer projects)"
                continue ;;
        esac
        # CHECK: existence test against the canonical agent set stays in shell.
        if echo "$KNOWN_AGENTS" | grep -qx "$target"; then
            ok "[$agent_name] → $target resolves"
        else
            fail "[$agent_name] escalates/notifies '$target' but no agent file found for it"
        fi
    done < <(python3 "$LOGIC_PY" extract-escalation-targets < "$f" || true)
done < <(find "$AGENTS_DIR" -name '*.md' -print0)

# ── 5. Project-start output doc paths are consistent ────────────────────────
section "5. Project-start output document path consistency"

# The four expected project-start output docs (bash 3.2: plain arrays, not associative)
DOC_CANONICALS=(
    "docs/pm/CONFIRMED-REQUIREMENTS.md"
    "docs/design/UX-DESIGN-READINESS.md"
    "docs/architecture/ADR-001-pilot.md"
    "docs/design/TECHNICAL-DESIGN.md"
    "docs/ops/TELEMETRY-SPEC.md"
)

for canonical in "${DOC_CANONICALS[@]}"; do
    basename_only=$(basename "$canonical")
    # Only check agent files — docs use shorthand in prose legitimately.
    # Only flag backtick-quoted references (navigation claims), not prose mentions.
    all_refs=$(grep -rl "$basename_only" "$AGENTS_DIR" 2>/dev/null || true)
    while IFS= read -r ref_file; do
        [[ -z "$ref_file" ]] && continue
        # Find lines with backtick-quoted bare basename (no directory component before it)
        wrong=$(grep -n "\`${basename_only}\`" "$ref_file" \
                | grep -v "$canonical" \
                | grep -v "^\s*#\|^\s*<!--" \
                || true)
        if [[ -n "$wrong" ]]; then
            fail "[$ref_file] uses bare \`$basename_only\` — should be \`$canonical\`:"
            echo "$wrong" | head -3
        else
            ok "[$ref_file] $basename_only path consistent"
        fi
    done <<< "$all_refs"
done

# ── 6. CORE region carve-out clause — #291 ──────────────────────────────────
section "6. CORE region PROJECT carve-out clause (#291)"

# Every agent file that has a HOS:CORE:START region must contain the
# enumerated carve-out clause (Decision D49 hybrid A+B).  A file with
# HOS:CORE:START but not "PROJECT may NEVER" has the unconditional
# "PROJECT governs" form that allows consumers to override safety gates.
CARVE_OUT_FINDINGS=0
while IFS= read -r -d '' f; do
    if grep -q "HOS:CORE:START" "$f"; then
        agent_name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')
        if grep -q "PROJECT may NEVER" "$f"; then
            ok "[$agent_name] CORE carve-out clause present"
        else
            fail "[$agent_name] missing PROJECT carve-out clause — unconditional override still present (#291)"
            CARVE_OUT_FINDINGS=$(( CARVE_OUT_FINDINGS + 1 ))
        fi
    fi
done < <(find "$AGENTS_DIR" -name '*.md' -print0)

# ── 7. Doc update staleness — agent files changed without doc update ─────────
section "7. Agent-to-doc staleness check"

# For each agent file changed in the last commit or uncommitted, check whether
# the key doc files (AGENTS.md, OVERSIGHT-RUNBOOK.md) were also touched.
# This is a heuristic warning — not all agent changes require doc updates,
# but a pattern of agent-only changes suggests docs may be falling behind.

CHANGED_AGENTS=()
while IFS= read -r f; do
    [[ "$f" == .claude/agents/*.md ]] && CHANGED_AGENTS+=("$f")
done < <(git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null)

DOC_FILES_CHANGED=false
while IFS= read -r f; do
    if [[ "$f" == docs/AGENTS.md || "$f" == docs/OVERSIGHT-RUNBOOK.md ]]; then
        DOC_FILES_CHANGED=true
        break
    fi
done < <(git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null)

if [[ ${#CHANGED_AGENTS[@]} -gt 0 && "$DOC_FILES_CHANGED" == "false" ]]; then
    warn "${#CHANGED_AGENTS[@]} agent file(s) changed without corresponding doc update"
    echo "  Changed agents: ${CHANGED_AGENTS[*]}"
    echo "  INFO: if agent behavior changed, consider updating docs/AGENTS.md or docs/OVERSIGHT-RUNBOOK.md"
    echo "  (This is advisory — not a blocking failure. Dismiss if the changes are internal-only.)"
else
    ok "Agent-to-doc staleness: OK"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
if [[ $FINDINGS -eq 0 ]]; then
    echo "  PASS — agent static checks clean (0 findings)"
    echo "═══════════════════════════════════════════════════════"
    # Write content-hash-based validation stamp (#552).
    # Hash is over agent file contents, not timestamps — survives rebase unchanged.
    STAMP_DIR="scripts/framework/validation-stamps"
    mkdir -p "$STAMP_DIR"
    CONTENT_HASH=$(find .claude/agents -name "*.md" | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
    printf "validated_at: %s\nhash: %s\nphase: 1-static\nresult: pass\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$CONTENT_HASH" > "$STAMP_DIR/phase1-${CONTENT_HASH}.stamp"
    exit 0
else
    echo "  FAIL — $FINDINGS finding(s) require attention"
    echo "═══════════════════════════════════════════════════════"
    exit 1
fi
