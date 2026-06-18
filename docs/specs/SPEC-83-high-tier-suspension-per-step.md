# SPEC-83: HIGH-Tier Security/Privacy Suspension Requires Per-Step Human Authorization

**Status:** REVISED — pending architect override-file schema before technical-design can begin
**Issue:** #83
**Author:** pm-agent
**Date:** 2026-06-17

---

## 1. Problem Statement

The current evaluator Phase 1 gate for HIGH-tier security/privacy suspension uses a single blanket acknowledgment field (`security-suspension-acknowledged: yes`) in `contract/gate-suspension.md`. A project that sets this field once covers every subsequent HIGH-tier step for as long as the suspension file is in place, regardless of what those steps touch.

This is too coarse. A blanket acknowledgment made during initial brownfield onboarding may have been reasonable at the time but does not constitute considered human authorization for a later step that modifies authentication code, payment flows, or other security-relevant surfaces. The acknowledgment covers the decision to suspend, not the risk of any individual step proceeding without a security review.

The specific gap: `oversight-evaluator.md` Phase 1 currently states — "If `security-suspension-acknowledged: yes` is present, record as WAIVED (acknowledged) — no additional warning needed." A blanket field satisfies this check for all HIGH-tier steps permanently, even when the step's code surface makes the missing review materially significant.

The consequence is that an engineer who set `security-suspension-acknowledged: yes` during week-one brownfield onboarding can ship auth-touching HIGH-tier changes weeks later without any fresh human authorization. The oversight value of the HIGH-tier warning path is eroded to zero.

---

## 2. Scope

This spec covers:

1. **`contract/gate-suspension.template.md` schema**: addition of a `per_step_scope` boolean field and a companion `steps:` list field.
2. **`oversight-evaluator.md` Phase 1 HIGH-tier check**: the evaluator must distinguish per-step-scoped suspensions from blanket suspensions when a HIGH-tier step touches security-relevant surfaces, and require either a per-step-scoped suspension or a per-step human-tier-override artifact.
3. **Grandfathering rule for existing blanket suspensions**: existing `gate-suspension.md` files that use the blanket pattern must emit a COMPLIANCE WARN (not FAIL) for a defined transition period.

This spec does NOT cover:

- LOW or MEDIUM tier suspension behavior — those paths are not changed.
- CRITICAL-tier steps — those are already covered by the absolute suspension prohibition in the evaluator ("Gate suspension may NOT waive any role on a step where the effective human gate fires"). CRITICAL is not in scope here.
- The `human-tier-override.md` file format beyond specifying what the evaluator must look for — the technical design of that artifact is owned by the architect.
- Automatic re-enable or expiry of per-step scopes — suspension management automation is not changed.
- Adding new reviewer roles to the security-relevant surfaces definition — the surfaces listed in R2 are derived from the existing `change_classifier.py` tier-floor rules and are not expanded here.

---

## 3. Requirements

### R1 — gate-suspension.md gains per_step_scope and steps fields

**R1.1** `contract/gate-suspension.template.md` must add a `per_step_scope` boolean field. The default value when the field is absent is `false` (blanket suspension — backward compatible with all existing files).

**R1.2** `contract/gate-suspension.template.md` must add a `steps:` list field, which is required when `per_step_scope: true`. Each entry in `steps:` names a specific build step (by step ID matching `contract/step-manifest.yaml` step identifiers). When `per_step_scope: true`, the suspension applies only to the steps listed in `steps:`. A step not listed is not covered.

**R1.3** When `per_step_scope: false` (or the field is absent), `steps:` is ignored. The suspension remains blanket as today — the change is additive and does not alter existing behavior for blanket suspensions at LOW or MEDIUM tier.

**R1.6** When `per_step_scope: true` and `steps:` is absent or empty, the evaluator must emit **COMPLIANCE FAIL** with the message: "Malformed authorization: `per_step_scope: true` requires a non-empty `steps:` list. No steps are covered by this suspension entry." This is a distinct failure from R2's blanket-suspension FAIL and must not be silently treated as "nothing covered → proceed to R2 check." The malformed-authorization FAIL takes precedence and halts Phase 1 processing for the step.

**R1.4** `per_step_scope` and `steps:` are placed under the existing `security-suspension-acknowledged` comment in the template, annotated with a comment making clear they are required when per-step scoping is needed for HIGH-tier steps.

**R1.5** Agents must not create or modify `contract/gate-suspension.md`. This is an existing invariant; R1 does not change it.

### R2 — Evaluator Phase 1 requires per-step authorization for HIGH-tier security-relevant steps

**R2.1** When all of the following are true, the evaluator must require per-step authorization rather than accepting a blanket suspension:

- The validated tier is exactly HIGH (not CRITICAL — that case is already handled by the absolute prohibition and by R2.6).
- `security` or `privacy` is suspended via `contract/gate-suspension.md`.
- The step touches one or more security-relevant surfaces, defined as the same surfaces `change_classifier.py` uses to establish the HIGH tier floor: authentication and authorization paths (`auth/**`, `**/permissions/**`, `**/acl/**`), payment and billing paths, destructive migration operations, and any other path designated a tier-floor trigger in `change_classifier.py` at the time the evaluator runs.

When `change_classifier.py` is unavailable or returns an error, the evaluator must treat the security-relevant-surface condition as **TRUE** (assume the surface is relevant) and proceed as though R2.1 is satisfied. A safety gate that no-ops when its classifier breaks is worse than the status quo. The evaluator must include a note in the Phase 1 output: "NOTE: change_classifier.py unavailable — security-relevant-surface condition assumed TRUE (fail-closed)."

**R2.2** When the three conditions in R2.1 are all true, the evaluator must check whether either of the following forms of per-step authorization is present:

- **(a) Per-step-scoped suspension:** `contract/gate-suspension.md` has `per_step_scope: true` AND the current step's ID appears in its `steps:` list. The presence of `security-suspension-acknowledged: yes` in the same file is still required alongside the scoped entry (R2.3).
- **(b) Per-step human-tier-override:** `contract/tier-overrides/step{N}-human-tier-override.md` exists, is non-empty, and contains a human authorization specifically for the suspension of the security or privacy role on this step. The evaluator reads this file; it may not create it.

  **[SCHEMA RESOLVED: see architect ruling 2026-06-17 — contract/tier-overrides/ is the authoritative location]** The schema and placement for `human-tier-override.md` must ensure it cannot be authored by an AI agent. This requires either a field that carries an out-of-band human signal, or the file must live outside `.claudetmp/` entirely (which is agent-writable). The architect owns the schema for this file. Technical-design must not place the file in agent-writable `.claudetmp/` without that schema in place. This requirement is a blocker for technical-design on the override path.

If neither (a) nor (b) is present, the evaluator must emit **COMPLIANCE FAIL**: "HIGH-tier security-relevant step {N}: `security`/`privacy` is suspended via a blanket suspension (`per_step_scope: false`). A blanket suspension is insufficient for a HIGH-tier step touching security-relevant surfaces. Provide either (a) a per-step-scoped suspension covering step {N}, or (b) a per-step human-tier-override artifact at `contract/tier-overrides/step{N}-human-tier-override.md`."

**R2.3** When per-step-scoped suspension path (a) is satisfied, the existing `security-suspension-acknowledged: yes` field must also be present in `contract/gate-suspension.md`. A per-step-scoped suspension without the blanket acknowledgment is not valid — the acknowledgment confirms the human understood the role was being suspended at all; the scoping confirms which steps were individually authorized.

**R2.4** The per-step-scoped suspension check (R2.2a) uses the step ID from `contract/step-manifest.yaml`. The evaluator must match the current step's `id` field against the `steps:` list using exact string equality.

**R2.5** The evaluator must emit a `gate-suspended` audit event as normal when the suspension is accepted via per-step authorization. The event must include an additional field `per_step_authorized: true` to distinguish per-step authorizations from blanket ones in the audit trail.

**R2.6** The R2 tier==HIGH check is exact. CRITICAL-tier steps never fall through to the "per-step authorization accepted" branch (R2.2(a) or R2.2(b)). A `steps:` list that names a CRITICAL-tier step does not constitute authorization for that step — when tier==CRITICAL and `security` or `privacy` is suspended, the existing absolute prohibition (contract §2a: "Gate suspension may NOT waive any role on a step where the effective human gate fires") takes precedence unconditionally. No per-step authorization — whether via `gate-suspension.md` scoping or a `human-tier-override` artifact — can override that prohibition. The evaluator must detect this condition and emit COMPLIANCE FAIL: "CRITICAL-tier step {N}: per-step suspension authorization is not recognized. The absolute prohibition (contract §2a) applies — security/privacy may not be suspended on CRITICAL-tier steps regardless of authorization." This requirement is stated here for clarity; the underlying prohibition originates from the contract and is not new.

### R3 — Grandfathering: existing blanket suspensions emit COMPLIANCE WARN, not FAIL

**R3.1** The grandfathering rule is opt-in and explicit. A `gate-suspension.md` that satisfies the blanket acknowledgment pattern (`security-suspension-acknowledged: yes` with `per_step_scope: false` or `per_step_scope` absent) but does not satisfy the per-step requirements of R2 is grandfathered — and therefore emits COMPLIANCE WARN rather than FAIL — **only when** a `grandfathered_until: YYYY-MM-DD` field is present in the file AND the date specified is in the future relative to today's date. The evaluator must compare this date using the same date-parsing idiom as the `review-by:` annotation in `suspension_manager.py`. When `grandfathered_until` is absent, no grandfathering applies — the evaluator applies R2 normally (FAIL on blanket suspension). When `grandfathered_until` is present but the date has passed, the transition period is over — the evaluator must emit COMPLIANCE FAIL, not WARN: "Grandfathering period expired ({date}): HIGH-tier security-relevant step {N} must now comply with per-step authorization requirements (R1, R2)."

**R3.2** The COMPLIANCE WARN text must clearly state what the gap is and what action is required to resolve it: "COMPLIANCE WARN: HIGH-tier security-relevant step {N} is proceeding under a blanket suspension. Blanket suspensions for HIGH-tier security-relevant surfaces are deprecated; this step is grandfathered until {grandfathered_until date}. Add per-step scoping (R1) or a per-step human-tier-override to remove this warning."

**R3.3** A step emitting this COMPLIANCE WARN must automatically trigger **CONDITIONAL_PROCEED** (not ESCALATE and not clean PROCEED), so the warning appears in the PR body and the human sees it before merge.

**R3.4** The `grandfathered_until` field is human-set. Agents must not create or modify it. Its presence and value are evidence of a deliberate human decision to allow the transition period. The field is placed in `contract/gate-suspension.md` alongside `security-suspension-acknowledged`. The architect will specify the exact field placement and comment text in the template.

**R3.5** *(Removed — commit-date grandfathering replaced by explicit `grandfathered_until` field per architect correction 2026-06-17. A `gate-suspension.md` without `grandfathered_until` present receives no grandfathering regardless of when it was created.)*

---

## 4. Acceptance Criteria

**AC1 — Blanket suspension on a HIGH-tier security-surface step without grandfathering fails compliance.**
Given `contract/gate-suspension.md` exists with `security-suspension-acknowledged: yes`, `per_step_scope: false` (or absent), and the file was created after this spec ships, and the current step is validated HIGH tier and touches `auth/**`, when the evaluator runs Phase 1, then it emits COMPLIANCE FAIL naming the step and the two paths to resolution.

**AC2 — Per-step-scoped suspension on a HIGH-tier security-surface step passes compliance.**
Given `contract/gate-suspension.md` has `security-suspension-acknowledged: yes`, `per_step_scope: true`, and `steps:` includes the current step's ID, when the evaluator runs Phase 1 on that HIGH-tier security-surface step, then it records the role as WAIVED (per-step acknowledged) with no warning. The `gate-suspended` audit event includes `per_step_authorized: true`.

**AC3 — Per-step human-tier-override on a HIGH-tier security-surface step passes compliance.**
Given `contract/tier-overrides/step{N}-human-tier-override.md` exists, is non-empty, and authorizes the suspension of `security` for step N, and the suspension file has `security-suspension-acknowledged: yes`, when the evaluator runs Phase 1, then it records the role as WAIVED (per-step human override) with no warning.

**AC4 — Blanket suspension with a valid `grandfathered_until` date emits WARN not FAIL.**
Given `contract/gate-suspension.md` has `security-suspension-acknowledged: yes`, no `per_step_scope: true` entry for the current step, and `grandfathered_until: YYYY-MM-DD` set to a future date, when the evaluator runs Phase 1 on a HIGH-tier security-surface step, then it emits exactly one COMPLIANCE WARN (not FAIL) and triggers CONDITIONAL_PROCEED.

**AC4b — Blanket suspension without `grandfathered_until` fails compliance.**
Given `contract/gate-suspension.md` has `security-suspension-acknowledged: yes` and `per_step_scope: false` (or absent), and no `grandfathered_until` field is present, when the evaluator runs Phase 1 on a HIGH-tier security-surface step, then it emits COMPLIANCE FAIL (not WARN).

**AC4c — Expired `grandfathered_until` date fails compliance.**
Given `contract/gate-suspension.md` has `security-suspension-acknowledged: yes`, `per_step_scope: false` (or absent), and `grandfathered_until` set to a date in the past, when the evaluator runs Phase 1 on a HIGH-tier security-surface step, then it emits COMPLIANCE FAIL naming the expired date.

**AC5 — Blanket suspension on a HIGH-tier step that does NOT touch security-relevant surfaces is unchanged.**
Given `contract/gate-suspension.md` has `security-suspension-acknowledged: yes` (blanket), and the current step is HIGH tier but does not touch any security-relevant surfaces (as determined by `change_classifier.py`), when the evaluator runs Phase 1, then it records the role as WAIVED (acknowledged) with the existing warning behavior unchanged. R2 does not fire.

**AC6 — LOW and MEDIUM tier suspension behavior is not changed.**
Given `contract/gate-suspension.md` suspends `security` and the current step is validated MEDIUM or LOW tier, when the evaluator runs Phase 1, then it applies the existing suspension logic without invoking R2. Per-step scoping fields are not required for LOW/MEDIUM steps.

**AC7 — Per-step-scoped suspension covering step N does not cover step M.**
Given `contract/gate-suspension.md` has `per_step_scope: true` and `steps: [step-3]`, and the current step is `step-4` (HIGH tier, security-relevant), when the evaluator runs Phase 1 for step 4, then step 4 is NOT considered covered by the per-step suspension and the evaluator applies R2.2 (either FAIL or grandfathered WARN depending on whether a valid `grandfathered_until` date is present and unexpired).

---

## 5. Non-Requirements

**NR1 — LOW and MEDIUM tier suspension behavior is not changed.** Per-step scoping is required only for HIGH-tier steps touching security-relevant surfaces. LOW and MEDIUM tier suspension acknowledgment continues to use the existing blanket pattern.

**NR2 — CRITICAL tier is not in scope.** CRITICAL-tier steps already cannot have any role suspended — the existing absolute prohibition ("Gate suspension may NOT waive any role on a step where the effective human gate fires") covers CRITICAL. This spec adds nothing to the CRITICAL path.

**NR3 — This spec does not define the human-tier-override file format in full.** The evaluator must recognize and read the file; the full schema (required fields, who may create it, audit trail) is owned by the architect and is an implementation detail.

**NR4 — Suspension management automation is not changed.** `scripts/oversight/suspension_manager.py` auto-removal rules, the `review-by:` annotation, and `[pinned]` behavior are not modified.

**NR5 — The re-enable log table in gate-suspension.md is not changed.** Re-enabling a per-step-scoped suspension follows the same existing process: remove the step from the `steps:` list (or set `per_step_scope: false`) and log the re-enable in the re-enable log table.

**NR6 — Retroactive re-authorization of prior steps is not required.** Steps that already completed under a blanket suspension before this spec ships are not retroactively reviewed.

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/gate-suspension.template.md` | Additive | Add `per_step_scope` boolean field (default false), `steps:` list field, and `grandfathered_until: YYYY-MM-DD` field (human-set, optional; enables R3 WARN path) |
| `.claude/agents/oversight-evaluator.md` Phase 1 | Additive | Replace the simple blanket-acknowledgment check for HIGH-tier security/privacy suspension with the three-condition check (R2.1, including fail-closed classifier fallback), two-path authorization check (R2.2), malformed-authorization FAIL (R1.6), CRITICAL invariant (R2.6), and `grandfathered_until`-based grandfathering WARN path (R3) |
| `contract/OVERSIGHT-CONTRACT.md` | Additive | Document per-step suspension scope fields, `grandfathered_until` field, updated HIGH-tier suspension check behavior, and CRITICAL-tier invariant |
| `human-tier-override.md` schema | PENDING ARCHITECT SCHEMA | Location, required fields, and agent-writability constraint for the per-step human override artifact (R2.2(b)) — owned by architect; blocks technical-design on the override path |

No new files are created by the implementation beyond what the architect schema defines for `human-tier-override.md`. No existing required fields are renamed or removed. The CRITICAL-tier absolute prohibition is not changed — R2.6 makes it explicit in this spec but originates from contract §2a.
