# Prompt Artifact — pr_review_cli.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/pr_review_cli.py` |
| **Description** | Per-action interim sign-off sentence (#2245 S1) |
| **Date** | 2026-11-06 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Coder dispatch (summary of the exact instructions given):
Implement slice S1 of #2245. `_with_interim_signoff` appends `_SIGNOFF_SENTENCE_OTHER`
("the overseer recommends against merging it as it stands") for every non-APPROVE
action; on PR #2244 that contradicted a DECIDE verdict recommending approval.
Choose the sentence per action via an explicit mapping:
- APPROVE: existing text, unchanged.
- REQUEST_CHANGES, DO_NOT_MERGE: existing "recommends against merging" text, unchanged.
- DECIDE: recommendation stated above, the decision is yours; approval of commit
  `{sha12}` after resolving threads makes the PR mergeable. No "against"/"overrides".
- OTHER: neutral; what the overseer asks is stated above.
An action with no entry must fail loudly (no fallback). Marker, ordering and the
function signature unchanged. Add a parametrized end-to-end test over all five
reachable actions and a unit test for the unknown-action failure and table
coverage. Update TD-2174 sentence list citing #2245.
```

## Constraints Specified

- Must NOT change the machine-readable interim marker grammar or the APPROVE /
  against-merging sentence bytes.
- Must NOT fall back to a default sentence for an unmapped action.
- Must NOT edit `.claude/agents/**`; no branch/stash/checkout/push.

## Refinement History

First attempt accepted.

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
3. Compare key logic paths against `scripts/automation/pr_review_cli.py`
4. Note any drift in a new version artifact (`pr_review_cli.v1.md`)
