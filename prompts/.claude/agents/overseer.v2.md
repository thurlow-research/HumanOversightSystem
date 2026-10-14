# Prompt Artifact — overseer.md

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md` |
| **Description** | #1557 PROPOSE_ONLY applies no needs-ai label |
| **Date** | 2026-10-14 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Autonomous worker cycle; source is issue #1557 (no human-authored prompt).
The worker took the issue's suggested fix option 1 and wrote the edit
directly (agent-definition edits in the HOS source repo are made by the
top-level session, not `coder` — CLAUDE.md, #1347):

```
In .claude/agents/overseer.md step 6, the PROPOSE_ONLY disposition bullet
must stop instructing `Label needs-ai` / `edit_issue.sh --add-label needs-ai`.
PROPOSE_ONLY's Expected action is NO ACTION, and bin/hos-cron routes any open
non-draft bot PR with needs-ai and no needs-human to needs-fix. That gives the
worker a false "fix and push" directive. Replace the instruction with an
explicit "apply no label" and say why. Add a regression test pinning the
prose bullet (tests/framework/test_overseer_verdict_artifact.py).
```

## Constraints Specified

- Narrow stopgap only, in the same spirit as #1526. Do not attempt the #1520
  label-taxonomy rename.
- Do not change `bin/hos-cron` routing (option 2 was rejected because it is a
  larger protected-surface change, and option 1 removes the producer).
- `merge_authority.py` already returns no labels for PROPOSE_ONLY. The prose
  must match the code, not the other way round.
- Must NOT: change any other disposition's labelling, the verdict event
  (`comment` stays mandatory), or the Expected-action mapping.

## Refinement History

v1: also added a `labels_to_add` assertion to
`tests/automation/test_phase_b.py`. Dropped, because that file carries
pre-existing lint, secret-scan and mypy debt unrelated to #1557, and the code
path it pinned was already correct.

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
3. Compare key logic paths against `.claude/agents/overseer.md`
4. Note any drift in a new version artifact (`overseer.v3.md`)
