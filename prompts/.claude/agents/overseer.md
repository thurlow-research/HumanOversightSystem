# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` (+ `bootstrap/overseer-cron-prompt.md`) |
| **Description** | CI terminal-state precheck: overseer defers review until required checks finish (#1971) |
| **Date** | 2026-10-05 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Autonomous worker cycle (bin/hos-cron --role worker). The selector's first
candidate was #1971 (priority:critical, needs-ai). The operative instruction is
the issue's own "Fix" section, implemented per spec:

```
In overseer.md, before running the review chain (risk recompute, gate re-run,
merits spot-check, executive summary): check every CI-required status check's
status field (not just conclusion) — if any required check is in_progress or
queued, stop. Post nothing (or a minimal one-line "CI still running, deferring
to next cycle" note, no full review) and let the next cron cycle re-check.
```

The issue scopes this as an instruction-level stopgap; the deterministic
code-level checker is a separate child of #1643 and is out of scope here.

Authored directly by the top-level worker session (CLAUDE.md § "Agent-definition
edits (HOS source repo only)") — not delegated to `coder`.

## Constraints Specified

- Instruction-level only: no new script, no change to `merge_authority.py`.
- Judge on `status`, never `conclusion` alone.
- Post nothing on deferral.

## Design choices made by the authoring session (not in the issue text)

1. **Placement** — new step 2a in §What you do, after the failure-cap check and
   before step 3 (Read PR state), so no review work of any kind precedes it.
   The cron prompt's Step 1 gains a short pointer to step 2a.
2. **Meta-gate exclusion** — `require-human-approval`, `require-overseer-approval`,
   `require-tier-ceiling` are excluded. They are moved by the overseer's own
   review/approval; waiting on them before reviewing would deadlock. This
   mirrors `_META_GATE_CHECKS` in `merge_authority.py` (step 4c).
3. **Absent check = non-terminal** — a required context with no run yet on the
   head SHA is treated as not finished (a fresh push often has queued workflows
   that have not created check runs yet).
4. **Stall guard** — the issue's "let the next cycle re-check" could defer
   forever if a check never finishes or never reports. After 2 hours the
   overseer escalates once via `bootstrap/escalate_to_human.sh --reason
   ci-stalled` (idempotent per identical body), instead of deferring silently.
5. **Reads** — `gh api` with `{owner}/{repo}` placeholders (static,
   allowlistable). No wrapper exists for check-run reads
   (`bootstrap/query_issues.sh` has no check-runs mode;
   `merge_authority_cli.py` has no required-checks subcommand) — searched
   `scripts/`, `bootstrap/`, `bin/`, `scripts/automation/lib/`.

## Refinement iterations

1 — initial authoring.
