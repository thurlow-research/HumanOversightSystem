# Prompt Artifact — readopt.py (#2287 reap-orphans extensions)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/readopt.py` (rule D4 `REVIEW_RE`, N2a, N6 `_audit_guard`), `tests/automation/test_readopt.py` (R1-R8, R10, R11) |
| **Description** | Overseer branch hygiene engine rules: reap local copies of PR heads (`pr-N`, `prN-check`, ...) only when the PR head contains the tip; never reap `chore/audit-overseer-cycle-*` / `chore/overseer-audit-*`; never reap an unlanded branch that carries audit records (#2287, slice 2 of #2285) |
| **Date** | 2026-11-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with this brief (engine scope
only for this artifact; the other files are in the sibling artifacts):

```
Implement the approved technical design
docs/v0.7.0/TECHNICAL-DESIGN-2287-overseer-branch-hygiene.md (Status APPROVED, architect review
round 1 at commit af735ef65; the round-1 resolutions are binding and folded into the body) on the
current branch. Do NOT switch branches, stash, checkout, reset or rebase.

Scope: scripts/automation/readopt.py - reap-orphans extensions per the TD (D4 pr-N/prN rule with
the A1 guard, N2a protected chore/ audit patterns, N6 audit-record keep inserted before the D1'
and D2 early returns per A12, REAPED line format/regex compatibility per A10). The audit-branches
subcommand is CUT (A9) - do not implement it. Tests: tests/automation/test_readopt.py, the TD's
R-list minus R9. Tests must clean up their own temp. Commit with "Part of #2287".
```

Reference: TD-2287 sections 3 (D4), 4 (N2a, N6), 8 (R1-R11) and architect findings A1, A10, A12.
