# Prompt Artifact — AGENTS.md

| Field | Value |
|---|---|
| **Generated file** | `AGENTS.md` (+ `templates/AGENTS.md`, `README.md`, `docs/OVERSIGHT-RUNBOOK.md`, `bootstrap/worker-cron-prompt.md`, `.claude/agents/oversight-orchestrator.md`, `scripts/capture_prompt.sh`, `templates/capture_prompt.sh`) |
| **Description** | Fix AI-Model commit trailer to report actual runtime model, not hardcoded example (#1317) |
| **Date** | 2026-08-11 |
| **Model** | claude-sonnet-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Autonomous HOS worker cron cycle. Step 2 selected issue #1317 (priority:medium, needs-ai,
v0.6.0) — "AI-Model commit-trailer field reports a hardcoded example value, not the actual
runtime model".

The issue: AGENTS.md's Git Commit Trailer Convention template hardcodes the literal example
`AI-Model: claude-sonnet-4-6`. Every other file that documents or generates this trailer
(templates/AGENTS.md, README.md, docs/OVERSIGHT-RUNBOOK.md, bootstrap/worker-cron-prompt.md,
scripts/capture_prompt.sh, templates/capture_prompt.sh, .claude/agents/oversight-orchestrator.md's
PR-body Model field) copies or reproduces the same literal string instead of instructing the
agent to substitute its own actual model ID. Agents appear to copy the example verbatim into
real commits and PR metadata rather than reporting the truth — observed on a same-day PR that
still showed the stale model string.

Fix, per the issue's own proposal:
1. Reword AGENTS.md's (and templates/AGENTS.md's) instruction to state explicitly that
   `AI-Model:` must be the model actually running the session (available from the agent's own
   system context) and must never be copied from the example literally.
2. Replace the example value itself with an obviously-non-literal placeholder
   (`<actual-model-id-running-this-session>`) so a literal copy is visibly wrong rather than a
   plausible-looking real model string.
3. Sweep every other file carrying the same literal string for the same problem, excluding
   files that were out of scope: ARCHITECTURE.md and docs/CUSTOMIZATION.md's `model:` frontmatter
   examples are model *assignment* (a different, already-fixed problem per #1141/#1308, and
   explicitly distinguished from this issue in its own text); prompts/**/*.md artifacts,
   research/**, and scripts/framework/decisions.md are historical/audit records and must not be
   rewritten retroactively.
4. scripts/capture_prompt.sh and templates/capture_prompt.sh had a deeper version of the same
   bug: `MODEL="${AI_MODEL:-claude-sonnet-4-6}"` silently defaulted to the stale model whenever
   the caller forgot to set `AI_MODEL`. Since there is no way for a shell script to introspect
   the actual runtime model, changed this to fail loudly (exit 1 with a clear message) rather
   than silently emit false provenance data.

Run scripts/framework/run_tests_inner_loop.sh and scripts/oversight/run_validators.sh before
opening the PR (HOS hard gate).
```

## Constraints Specified

- Do not touch ARCHITECTURE.md's or docs/CUSTOMIZATION.md's `model:` frontmatter examples —
  those are the model-*assignment* problem (#1141/#1308), not this issue.
- Do not retroactively edit historical prompt artifacts (`prompts/**`), research notes
  (`research/**`), or the append-only `scripts/framework/decisions.md` — they are records of
  what happened, not live instructions.
- File/commit budget: ≤15 files, ≤10 commits (Step 5 batching limit).

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `AGENTS.md`
4. Note any drift in a new version artifact (`AGENTS.v1.md`)
