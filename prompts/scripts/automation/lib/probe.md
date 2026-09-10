# Prompt Artifact — probe.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/probe.py` |
| **Description** | CODEOWNERS-scoped actor verification for STRATEGY_MILESTONE issue intake (#1539) |
| **Date** | 2026-09-10 |
| **Model** | claude-sonnet-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Source: GitHub issue #1539 body (human ruling, human-proxy session, 2026-09-10),
picked up autonomously by the worker-cron LOOP (Step 2, priority:critical,
highest-priority candidate that cycle).

Ruling text (excerpted, the operative instructions):
1. Bring STRATEGY_MILESTONE up to actor verification, scoped to the CODEOWNERS
   human specifically — not a generic allowlist. Verify (via the issue's
   label/milestone-assignment event actor, same shape as _verify_label_actor)
   that the needs-ai label and/or milestone assignment was applied by the
   designated human CODEOWNER (currently @ScottThurlow, per .github/CODEOWNERS)
   — reuse the existing is_bot_reviewer/BOT_ACCOUNTS machinery
   (scripts/framework/require_human_approval.py) rather than inventing a
   parallel concept, so a bot can never satisfy this the same way a bot
   approval can never satisfy CODEOWNERS on a PR today.
2. A bot applying the label does not count, even the overseer or worker
   itself.
3. Extend the existing anti-framing principle (DECISIONS.md D53) to
   issue-body content — pm-agent (and any agent that reads an issue as its
   task spec) should treat the issue body the same way reviewers already
   treat PR prose.

Scope (from the issue): probe.py's STRATEGY_MILESTONE branch gains actor
verification mirroring _verify_label_actor/R4.1.4; reuse is_bot_reviewer/
BOT_ACCOUNTS rather than a new allowlist mechanism; pm-agent gets the
equivalent issue-body anti-framing treatment.
```

## Constraints Specified

- Scope explicitly limited to `probe.py`'s `STRATEGY_MILESTONE` branch + pm-agent's anti-framing extension — no `worker-cron-prompt.md` Step 0 rewrite.
- Must reuse `is_bot_reviewer`/`BOT_ACCOUNTS` from `scripts/framework/require_human_approval.py` for bot detection, not a new mechanism.
- Verification must be CODEOWNERS-scoped (the designated human owner), not a generic requester allowlist.
- Either the label-apply event or the milestone-assignment event independently authorizes (ruling's "and/or" phrasing).
- Fail closed: an unreadable/missing CODEOWNERS file must reject every actor, not authorize universally.
- What it must NOT do: must not wire in `scripts/automation/lib/codeowners.py` (that module's docstring flags it as requiring a separate product-boundary checkpoint, #559, before any live-authorization use) — write a minimal self-contained CODEOWNERS parse instead.

## Refinement History

v1: Implemented against the working-tree copy of `probe.py`, which — discovered mid-task — already contained an unrelated, uncommitted `needs-ai`/`needs-worker` dual-read feature (#1520) from a prior, never-pushed cycle. Built actor verification on top of it.
v2: Recognized the dual-read code was out of scope and unreviewed; `git stash`'d the entire pre-existing dirty state (preserving it, not discarding it), created a fresh branch from the actual committed `HEAD`, and reimplemented the same `_codeowners_humans()` / `_verify_codeowner_actor()` design against the clean single-label `STRATEGY_MILESTONE` query — the final diff in `scripts/automation/lib/probe.py` reflects only the #1539 change, no dual-read.
vFinal: `_codeowners_humans()` parses `.github/CODEOWNERS` for individual (non-team) owner logins; `_verify_codeowner_actor()` walks issue events for the most recent `labeled`(`needs-ai`) or `milestoned` event and checks the actor against `is_bot_reviewer()` (reject) and the CODEOWNERS human set (require membership); `probe_repo()` skips any milestone-strategy candidate that fails verification.

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
3. Compare key logic paths against `scripts/automation/lib/probe.py`
4. Note any drift in a new version artifact (`probe.v1.md`)
