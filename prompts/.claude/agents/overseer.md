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
   overseer stops deferring and reviews normally, naming the stalled checks in
   the executive summary; branch protection still blocks merge until they
   complete. (Iteration 1 escalated via `escalate_to_human.sh`, but that
   script refuses PR numbers — code-review MUST_FIX.)
5. **Already-red carve-out** — if a terminal required check has already
   failed, proceed so step 4c can bounce immediately rather than after the
   remaining checks finish.
6. **Reads** — `gh api` with `{owner}/{repo}` placeholders (static,
   allowlistable). No wrapper exists for check-run reads
   (`bootstrap/query_issues.sh` has no check-runs mode;
   `merge_authority_cli.py` has no required-checks subcommand) — searched
   `scripts/`, `bootstrap/`, `bin/`, `scripts/automation/lib/`.

## Refinement iterations

1 — initial authoring.
2 — code-review round 1: stall guard reworked (above); null `started_at`
    fallback; protection 404/403 → skip; backslash-free `@tsv` jq; note that
    deferral cannot cost a human-approval merge.
3 — overseer review of PR #1987 (MUST_FIX, human instruction "Worker: Address
    the comments from Overseer"): the overseer App gets 403 on the classic
    branch-protection endpoint in this repo (required checks come from
    rulesets), so the 404/403 → skip branch always fired. Step 2a now reads
    `rules/branches/<default_branch>` (`required_status_checks` rules) as well
    and takes the union; it skips only when both reads give no contexts. The
    cron-prompt pointer matches. Non-blocking finding also applied: the most
    recent run per context is the highest `id`, not list position. The
    `Validation stamps current` failure was an uncommitted stamp; the stamp
    for the final agent content is now committed.
