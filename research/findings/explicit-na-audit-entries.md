# Finding: Skipped Reviewers Leave No Audit Trail — N/A Entries Must Be Explicit

**First observed:** 2026-06-13, discussion of infra-reviewer dependency on code-reviewer  
**Trigger:** Question of whether code-reviewer should run on infra-only diffs and say "nothing to review"

---

## The Finding

When a reviewer is not invoked because its domain has no changes in the current diff, the sign-off register contains no entry for that reviewer. A future reader of the register — human or automated — cannot distinguish between:

1. The reviewer ran and found nothing (explicitly N/A)
2. The reviewer was never invoked (implicitly absent)
3. The reviewer was supposed to run but was skipped due to a bug or misconfiguration

All three states produce the same observable result: no register entry. This is an audit trail gap.

The immediate trigger: should `code-reviewer` run on an infra-only diff (only `docker-compose.yml` changed) and log "N/A — no application code in diff"? The answer is yes, for exactly this reason. A complete audit trail for a build step should show what every reviewer did, including the ones that had nothing to do.

---

## The Full Inventory of Skipped Cases

Every reviewer that participates in the formal sign-off register has one or more conditions under which it would currently not be invoked — and leave no trace:

| Reviewer | Currently skipped when | Explicit N/A entry? |
|---|---|---|
| `code-review` | Infrastructure-only diff | No |
| `security` | No `.py` files, or docs-only change | No (post-change-sweep logs SKIPPED in advisory output only) |
| `privacy` | No PII-adjacent paths in diff | No |
| `ui` | No template files changed | No |
| `a11y` | No template files changed | No |
| `infra` | No infrastructure files changed | No |
| `ops` | No ops complexity in diff, or TELEMETRY-SPEC.md absent | No |
| `reliability` | No outbound connections in diff | Partially (agent says "state N/A" but not as a register entry) |
| `test-unit` | No test files changed | No |
| `test-system` | `system_test_applicable: false` in step manifest | No |
| `process` | `system_test_applicable: false` | No (oversight-evaluator treats as absent) |

None currently write formal N/A entries to the sign-off register.

---

## Why This Matters

**Audit completeness.** The sign-off register is the primary artifact the oversight-evaluator uses to assess compliance. A register with gaps cannot be definitively read — the evaluator must distinguish "required but missing" from "not applicable" from "was this even considered?" Currently only the first is caught; the other two are silent.

**Regression detection.** If `ui-reviewer` is supposed to run on a step that modifies templates, and it doesn't, the register looks identical to a step where templates weren't touched. The oversight-evaluator has no way to detect the regression.

**Research auditability.** For the dissertation, the sign-off register is a data source for studying oversight patterns — how often each reviewer fires, what patterns correlate with escaped defects, etc. Silent skips make the dataset incomplete.

**Human reviewability.** A human reading a PR should be able to look at the sign-off register and see exactly what happened at each review stage — not infer what probably didn't happen from absences.

---

## The Principle

> **Every reviewer that is in scope for a build step should produce an explicit register entry, even if that entry is N/A.**

The distinction between "N/A" and "APPROVED" matters. N/A means: "this reviewer was considered, determined to have no applicable changes in this diff, and explicitly noted as such." APPROVED means: "this reviewer ran, found no blocking issues, and signed off."

A register with explicit N/A entries tells a complete story. A register with gaps tells an ambiguous one.

---

## Proposed Implementation Pattern

Two options:

**Option A — Agent-produced N/A entries:** Each reviewer, when invoked but finding nothing in its domain, writes an N/A entry to the register before exiting. This requires every reviewer to be invoked regardless of whether there's work for it.

**Option B — Orchestrator-produced N/A entries:** post-change-sweep writes N/A entries on behalf of agents it decides not to invoke. Agents only need to handle their domain-applicable case.

**Option B is better** for two reasons: (1) invoking every agent on every diff wastes token budget, (2) post-change-sweep already categorizes the diff by domain and knows which agents are not applicable — it can write the N/A entries cheaply without AI invocation.

The exception: `code-reviewer` should always be invoked (not N/A'd by the orchestrator) because the question "is there application code in this diff?" is itself a judgment call the reviewer should make, and the explicit "nothing to review" entry is more trustworthy coming from the reviewer than from the orchestrator.

---

## Cases Where This Changes Current Behavior

The highest-impact case: **code-reviewer on infra-only diffs.** Currently code-reviewer is gated before other reviewers and would block infra-reviewer if it's skipped. The fix: code-reviewer always runs, explicitly produces N/A when there's no application code, and infra-reviewer runs independently in parallel — not gated on code-reviewer approval when code-reviewer returned N/A.

Second-highest: **privacy-reviewer and security-reviewer on non-sensitive diffs.** Currently silently absent. With explicit N/A entries, a step that touched only UI templates would show: `security: N/A (no .py files)`, `privacy: N/A (no PII-adjacent paths)` — making it clear the decision was considered, not accidentally omitted.

---

## Implications for Research

1. **Audit completeness as a first-class requirement.** An oversight system whose audit trail has systematic gaps cannot be the basis for empirical claims about oversight effectiveness. The sign-off register must be complete to be a valid research instrument.

2. **The absence problem in audit trails.** Distinguishing "reviewer ran and found nothing" from "reviewer was never invoked" from "reviewer was supposed to run but didn't" is a general problem in audit systems. The N/A entry pattern is one solution; cryptographic commitments (proving a reviewer was at least invoked) are a stronger solution for high-assurance contexts.

3. **Orchestrator responsibility for completeness.** When an orchestrator (post-change-sweep) decides not to invoke an agent, it inherits responsibility for recording that decision. Passing the responsibility back to agents that weren't invoked is incoherent.

---

## Related findings

- `issue-vs-pr-thread-routing.md` — the routing heuristic also affects what gets logged; silent skips and routing to wrong artifacts both degrade the audit trail
- `brownfield-governance-adoption.md` — silent skips compound in brownfield contexts where gates are being re-enabled; you can't tell whether a gate was intentionally suspended or accidentally omitted
