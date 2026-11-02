# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` |
| **Description** | #1699 one audit event per disposition, written through write_pr_review_event.sh |
| **Date** | 2026-11-02 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

Autonomous worker cycle; source is issue #1699 (no human-authored prompt).
The paragraph was first written on 2026-10-13 and re-adopted on 2026-11-02
after its blocker (#1776) merged. Agent-definition edits in the HOS source
repo are made by the top-level session, not `coder` (CLAUDE.md, #1347):

```
In .claude/agents/overseer.md step 6, after "Ordering within step 6, and
halt-on-failure", add a paragraph naming exactly one audit event per
disposition: AUTO_MERGE and PROPOSE_ONLY write `pr-review`, an unchanged
head writes `idempotent-skip` (both through
scripts/oversight/write_pr_review_event.sh), HUMAN_REQUIRED keeps
`human-required` via audit_write_event with the SPEC-378 fields, and a
bounce writes `pr-bounced` via record_pr_bounce(). Say that hand-composed
records are forbidden because check_pr_reviewed.sh matches only the
writer's vocabulary.
```

## Constraints Specified

- The writer refuses `human-required`, legacy aliases and unknown names;
  the prose must say so and must not offer a second write path for
  `human-required`.
- The write sits after `submit-verdict` and before any finalize act, and a
  non-zero exit halts like the other step-6 commands.
- Must NOT change any disposition, verdict event or label.

## Refinement History

v4 (re-adoption, 2026-11-02): the 2026-10-13 text said the write came
"before the `needs-ai` label on PROPOSE_ONLY". #1557 (merged after the
branch was built) made PROPOSE_ONLY apply no label, so the clause now says
the write is PROPOSE_ONLY's last act.

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
2. Paste the prompt above unchanged
3. Compare key logic paths against `.claude/agents/overseer.md`
4. Note any drift in a new version artifact (`overseer.v5.md`)
