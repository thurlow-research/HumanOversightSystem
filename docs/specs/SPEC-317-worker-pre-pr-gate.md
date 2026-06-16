# Requirements Spec — Issue #317: Worker Pre-PR Readiness Gate and Overseer Bounce-Back Rule

**Document type:** Requirements specification
**Status:** Implemented — commit feat(#317) on feat/254-unattended-worker-impl and release/v0.3.x
**Issue:** #317
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

The current worker and overseer specs do not clearly assign ownership of the pre-PR validation chain. The worker's AUTONOMOUS mode lists "dispatch reviewers, run inner-loop tests" then "open draft PR" — but there is no explicit requirement that the sign-off register be complete and clean before that PR is opened. Correspondingly, the overseer has no specified bounce-back rule when the register is incomplete. The result: a worker can open a PR with an empty or partial register and the overseer has no defined response path.

The desired behavior mirrors standard engineering practice: a contributor does not open a PR until they believe their work is ready for external review. The overseer adds external review perspective and makes the merge decision — it is not a re-runner of checks the worker should already have passed.

---

## 2. Division of Labor (authoritative)

| Phase | Owner | What happens |
|---|---|---|
| Inner loop (per change) | Worker | Gates, validators, reviewer agents, sign-off entries |
| Transition (pre-PR) | Worker | System tests, second review, oversight-evaluator, self-assessment gate, PR creation |
| PR opening | Worker (on PROCEED) | `gh pr create` with required provenance fields |
| Bounce-back | Overseer | Detects incomplete register; posts structured bounce comment; assigns to worker + needs-ai |
| Outer loop review | Overseer | AI panel (agy/codex/Copilot), merge-authority decision, human escalation |

The overseer does not re-run inner-loop checks. The worker does not open PRs with incomplete registers.

---

## 3. Worker Pre-PR Checklist (ordered, required before gh pr create)

All items must be evaluated; evaluation continues even after a FAIL.

| check_id | Requirement | Tier floor |
|---|---|---|
| REQ-W-01 | inner-loop tests exit 0 (marker-read, staleness-guarded) | all |
| REQ-W-02 | gates pass | all |
| REQ-W-03 | validators ran, summary.json current | all |
| REQ-W-04 | risk-assessment.md scoped to current commit range | all |
| REQ-W-05 | all required reviewer sign-offs present with required fields | all |
| REQ-W-06 | no ESCALATED entry without Human_resolution | all |
| REQ-W-07 | CRITICAL steps need human-authorization file | CRITICAL |
| REQ-W-08 | second-review with non-error verdict | MEDIUM+ |
| REQ-W-09 | N/A only where diff doesn't touch role's domain | all |
| REQ-W-10 | Prompt-Artifact trailers on all commits | MEDIUM+ |
| REQ-W-11 | doc currency — relevant docs updated before PR opens | all |
| REQ-W-12 | system tests if applicable | if applicable |
| REQ-W-13 | evaluator verdict PROCEED or CONDITIONAL_PROCEED (not ESCALATE) | all |
| REQ-W-14 | panel-context.md and handoff.md exist | all |
| REQ-W-15 | deterministic self-assessment gate immediately before gh pr create | all |
| REQ-W-16 | gate is not a judgment call — blocks, no "open anyway" path | all |
| REQ-W-17 | gate result recorded in session-state.md or claim envelope | all |

---

## 4. Overseer Bounce-Back Rule

### 4.1 When to bounce

The overseer must check register completeness before applying the merge-authority matrix. Bounce conditions (any one triggers bounce):
- Register missing or has no entries
- Required role entry absent or missing required fields (Status/Agent/Artifact/Iterations)
- ESCALATED entry without Human_resolution
- Evaluator verdict is ESCALATE or absent
- panel-context.md or handoff.md absent
- risk-assessment.md scope doesn't match PR commit range
- MEDIUM+ step: second-review file absent or verdict error/skipped

### 4.2 Bounce action (REQ-O-06)

On bounce: post structured comment → assign PR to HOSWorkerTutelare → label needs-ai → convert to draft (maintainer role makes this reliable) → append pr-bounced event to audit log.

Do NOT close the PR, close the branch, or increment the failure counter.

### 4.3 Bounce escalation (REQ-O-09)

If the same cid has been bounced >= 2 times: escalate to human (needs-human + §8.2 body) instead of bouncing again.

### 4.4 Bounce comment format (machine-parseable)

```
## PR bounced — register incomplete
### Specific failures
- [REQ-W-05] signoff: role security-reviewer missing
### Required actions
- <remediation per check_id>
### Re-entry
1. Read ### Specific failures (one - [<CHECK-ID>] <detail> per line)
2. Fix gaps; re-run gate (step 8.9) until PASS
3. Open NEW PR referencing this one
<!-- hos-bounce: cid=<cid> bounce_number=<n> -->
```

---

## 5. pr-bounced Audit Event

```json
{"event":"pr-bounced","pr":318,"cid":"a1b2c3d4","bounce_number":1,"failures":["REQ-W-05"],"assigned_to":"HOSWorkerTutelare","repo":"thurlow-research/HOS","timestamp":"2026-06-16T19:04:11Z"}
```

---

## 6. Acceptance Criteria

- AC-01: Worker in autonomous mode cannot call gh pr create without a passing gate
- AC-02: Worker in interactive mode cannot open PR without gate PASS + human confirmation (in that order)
- AC-03: Overseer bounces PRs with incomplete registers; does not apply merge-authority matrix
- AC-04: Overseer with complete+clean register proceeds directly to matrix
- AC-05: After bounce fix, second PR receives normal overseer processing
- AC-06: pr-bounced event in audit log for every bounced PR
- AC-07: Evaluator ESCALATE continues to block PR opening (gate is defense-in-depth)
- AC-08: worker.md CORE updated with steps 8.5, 8.9, re-entry section
- AC-09: overseer.md CORE updated with bounce-back rule at step 4a
- AC-10: OVERSIGHT-CONTRACT.md §6a updated with pr-bounced event type
