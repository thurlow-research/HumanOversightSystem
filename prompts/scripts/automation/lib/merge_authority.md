# Prompt Artifact — merge_authority.py (human hold-directive gate, #902)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/merge_authority.py` (+ `tests/automation/test_phase_b.py`, `.claude/agents/overseer.md`) |
| **Description** | Add a human bounce-back/hold-directive gate to the merge-authority matrix |
| **Date** | 2026-06-29 |
| **Model** | claude-sonnet-4-6 |
| **Risk level** | MEDIUM (governance / merge-authority logic) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Close the #902 process gap: the overseer review chain can post an APPROVED review
after an explicit human directive to bounce a PR back (observed on #900 — human
said "Bounce back to worker" at 15:46Z; a prior overseer cycle posted APPROVED at
15:49Z, blind to the directive).

Plumb the rule into the authoritative matrix rather than ad-hoc cron logic:

1. In scripts/automation/lib/merge_authority.py add a pure detection helper
   detect_human_hold_directive(comments, human_reviewer="ScottThurlow",
   head_committed_at=None) that scans issue/PR comments for a comment authored by
   the human reviewer whose body matches a bounce-back / hold / do-not-merge
   pattern. Only count directives posted AFTER the current head was pushed — a
   newer worker push supersedes an earlier bounce-back, mirroring the stale-approval
   rule (#741). If head_committed_at is None or a comment timestamp is unparseable,
   fail safe and count the directive (withhold approval). Return the most recent
   matching comment or None.

2. Add a human_hold_directive: bool = False parameter to decide_merge_authority()
   and a guard that returns HUMAN_REQUIRED (label needs-human, reason cites #902)
   when True. It must fire alongside the #756 label and #761 reviewer guards —
   BEFORE the worker-class / verdict / ceiling guards — so a held PR escalates to
   the human instead of silently downgrading to PROPOSE_ONLY. The change is
   additive-restrictive only: it can turn AUTO_MERGE into HUMAN_REQUIRED, never the
   reverse.

3. Update .claude/agents/overseer.md so the overseer computes human_hold_directive
   via the helper (reusing the existing prior_overseer_decision comments fetch),
   passes it to decide_merge_authority(), withholds the APPROVE review when set, and
   dismisses any standing bot approval that stands against the directive.

4. Add unit tests mirroring the existing #761 tests: detection pattern coverage,
   head-push supersession, fail-safe on unknown push time, and matrix-guard
   behavior (blocks auto-merge, outranks worker-class, default False is a no-op).

Constraints: REST-only API guidance in prose; match surrounding code/test idiom;
do not weaken any existing guard; the new guard may only ever be more conservative.
```

## Constraints Specified

- **Placement / ordering:** the new guard fires before worker-class, verdict, ceiling guards (grouped with #756/#761 human-intent guards).
- **Safety direction:** additive-restrictive only — can never enable a merge that was not already enabled.
- **Supersession semantics:** a directive is "addressed" once a newer head push lands after it (parallels stale-approval rule #741).
- **Fail-safe:** unknown head-push time or unparseable comment timestamp ⇒ count the directive (withhold).
- **Authoritative matrix owns the rule:** detection is a pure, unit-tested helper; the LLM overseer only computes the boolean and honors the return.
- **API:** REST-only guidance in agent prose.

## Refinement History

First attempt — design taken directly from the issue's suggested fix (plumb
`human_hold_directive` into `decide_merge_authority()`).

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by:
     - Date reviewed:
     - Findings:
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/automation/lib/merge_authority.py`
   (`detect_human_hold_directive`, the `human_hold_directive` guard) and the
   `#902` tests in `tests/automation/test_phase_b.py`
4. Note any drift in a new version artifact (`merge_authority.v2.md`)
