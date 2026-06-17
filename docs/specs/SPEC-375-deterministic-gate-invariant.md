# Requirements Spec — Issue #375: Deterministic Gate Non-Override Invariant

**Document type:** Requirements specification
**Status:** Implemented — invariant added to OVERSIGHT-CONTRACT.md §7 (post-condition 15, pre-condition 16 placeholder)
**Issue:** #375
**Date:** 2026-06-16
**Author:** pm-agent
**Priority:** P3

---

## 1. Problem Statement

The oversight pipeline uses both deterministic validators (scripts that produce a binary pass/fail from static analysis, dependency scanning, license checks, etc.) and non-deterministic LLM reviewers (agents that reason about the same code). The contract previously specified compliance checks for sign-off presence and format, but it did not prohibit an LLM reviewer from resolving, downgrading, or closing a finding that a deterministic gate had already raised.

This creates a masking path: a deterministic scanner correctly catches a defect, an LLM reviewer independently evaluates the same code and finds no issue, and a synthesis layer (the arbiter, the evaluator, or an orchestrator) treats the LLM's silence as resolving the scanner's finding. The defect escapes.

Parris 2026 (AIRA) documented this failure mode in practice: an LLM reviewer masked a deterministic scanner finding, producing false assurance. With AI-generated code carrying approximately 1.7x more high-severity findings than human-authored code (Loker 2025, as reported in Ferdous et al. 2026), a synthesis layer that can suppress deterministic signal is a direct path to escaped defects at scale.

---

## 2. Scope

This spec covers:

- The invariant itself: what it forbids and what it permits
- Where it applies in the framework: `OVERSIGHT-CONTRACT.md` §7, `oversight-evaluator` Phase 1
- How it interacts with the evaluator re-derivation work (#94): the invariant is layered on top of conditions 11–15; condition 16 is its placeholder
- What constitutes a deterministic gate for the purposes of this invariant

This spec does NOT cover:

- Architecture of the evaluator re-derivation engine (#94) — that is the architect's domain
- How deterministic validators compute their findings internally
- The remediation path once a deterministic failure is surfaced to a human (the human decides)

---

## 3. The Invariant

### 3.1 Statement

**REQ-375-01:** A deterministic gate failure — any script in `scripts/oversight/gates/` or `scripts/oversight/validators/` that exits non-zero — must be surfaced to the human gate verbatim. It cannot be:

- Resolved, downgraded, or marked closed by an LLM reviewer or the arbiter
- Summarized away or absorbed into a panel verdict
- Treated as "addressed" because a subsequent LLM reviewer did not independently flag the same issue

**REQ-375-02:** The arbiter (oversight-orchestrator, panel arbiter, or any synthesis agent) may add context, corroboration, or an additional perspective to a deterministic finding. It may never suppress or outrank the deterministic finding.

**REQ-375-03:** The requirement to surface a deterministic failure to the human gate holds regardless of what any LLM reviewer concluded about the same code. LLM reviewer agreement does not resolve a deterministic failure; LLM reviewer silence does not close one; LLM reviewer disagreement is noted as context but does not remove the deterministic finding from the human-facing output.

### 3.2 Scope of "deterministic gate"

For the purposes of this invariant, a deterministic gate is any script with a stable, non-LLM evaluation path: it takes inputs, applies fixed rules, and exits zero (pass) or non-zero (fail). This covers:

- All scripts in `scripts/oversight/gates/` (lint, security-HIGH, secrets, types, template-refs, portability, django)
- All validators in `scripts/oversight/validators/` that produce a scored or binary output (rn_calculator.py, complexity_metrics.py, function_metrics.py, n1_detector.py, migration_scorer.py, static_analysis.py, ip_check.py, prompt_audit_risk.py, hallucination_surface.py, issue_query.py)

An LLM-assisted script is not deterministic for the purposes of this invariant. The distinction is: if running the same script twice on the same input always produces the same exit code, it is deterministic.

### 3.3 What the invariant does NOT prohibit

**REQ-375-04:** The invariant does not prohibit a human from deciding, after reviewing the surfaced finding, that it is a false positive and does not block the step. The invariant governs what reaches the human — not what the human decides.

**REQ-375-05:** The invariant does not prohibit gate suspension via `contract/gate-suspension.md` (the existing brownfield mechanism). A suspended gate is explicitly human-authorized and audited (`gate-suspended` event). Suspension is a legitimate path; LLM suppression of a non-suspended gate is not.

**REQ-375-06:** The invariant does not require that LLM reviewers be prevented from commenting on the same issue a deterministic gate flagged. LLM corroboration or context is useful. What is prohibited is the synthesis layer treating LLM silence or LLM approval as resolution of the deterministic finding.

---

## 4. Where the Invariant Applies

### 4.1 OVERSIGHT-CONTRACT.md §7

**REQ-375-07:** The invariant must be stated in `OVERSIGHT-CONTRACT.md` §7 (compliance check section). The statement must name: (a) which gate categories are covered (gates/ and validators/); (b) what is prohibited (LLM resolution, summarization, absorption, silent treatment); (c) what the arbiter may do (add context, never suppress or outrank).

**REQ-375-08:** The OVERSIGHT-CONTRACT.md text must reference the evaluator re-derivation work (#94) context: the invariant applies ON TOP of conditions 11–15. The placeholder for condition 16 shall assert that no deterministic FAIL was closed by a non-deterministic actor — to be enforced once the evaluator re-derivation work lands.

### 4.2 Oversight-evaluator Phase 1

**REQ-375-09:** Phase 1 compliance evaluation shall check that no deterministic gate failure recorded in `.claudetmp/oversight/validators/summary.json` was marked resolved or closed without a covering human-authorization artifact. If a gate is recorded as failed in `summary.json` and no `human-authorization.md` artifact references that gate explicitly, the step is non-compliant.

**REQ-375-10 (condition 16 placeholder):** Once the evaluator re-derivation work (#94) lands and the evaluator can compare gate output against reviewer conclusions, condition 16 shall assert: if gate G exited non-zero, no LLM reviewer verdict may appear in the register as the resolution of G's finding without a human-authorization artifact. The evaluator shall emit a `gate-deterministic-suppressed` audit event when it detects this pattern.

---

## 5. Acceptance Criteria

**AC-375-01:** If gate G exits non-zero for a step, the human-facing output for that step (handoff.md, panel-context.md, or escalation notice) must contain an unresolved finding referencing gate G by name. This must hold regardless of what any LLM reviewer said about the same issue.

**AC-375-02:** `OVERSIGHT-CONTRACT.md §7` contains the deterministic gate non-override invariant with explicit statements of what is prohibited and what is permitted.

**AC-375-03:** Phase 1 compliance fails when `validators/summary.json` records a gate failure and no covering human-authorization artifact exists for that gate. Compliance must not pass on the basis that an LLM reviewer approved the associated code.

**AC-375-04:** The arbiter (oversight-orchestrator) produces no output that would cause a downstream reader to conclude a deterministic finding was resolved by an LLM verdict. The panel-context.md output for any step with a deterministic failure must list that failure as unresolved until a human-authorization artifact exists.

**AC-375-05:** Gate suspension (via `contract/gate-suspension.md`) continues to function as the legitimate human-authorized path for deferring a deterministic gate. The invariant applies only to non-suspended gates.

**AC-375-06 (condition 16 — deferred):** Once #94 lands, the evaluator emits `gate-deterministic-suppressed` when a non-zero gate result was present but no corresponding finding appears in the human-facing output. This acceptance criterion is blocked on #94 and will be verified in that work's sign-off.

---

## 6. Interaction with Existing Protocol

### 6.1 Relation to evaluator re-derivation work (#94)

The evaluator re-derivation work (conditions 11–15) establishes that the evaluator independently re-derives tier floors, warranted reviewer lanes, and document modification coverage from the diff — rather than trusting self-reported values. The deterministic gate non-override invariant is conceptually parallel: it prevents a non-deterministic actor from overriding a deterministic actor's output. Condition 16 is the formal hook.

The invariant applies now, before #94 lands, as a behavioral constraint on the arbiter and orchestrator. Condition 16 adds the evaluator's mechanical enforcement. The two are complementary; neither is a prerequisite for the other.

### 6.2 Relation to gate suspension (OVERSIGHT-CONTRACT.md §3)

Gate suspension via `contract/gate-suspension.md` is a human-authorized path. A suspended gate exits 0; its `gate-suspended` event is recorded in the audit log with `authorized_by`. The invariant is not triggered for suspended gates. The invariant applies only when a gate runs and exits non-zero — suppression by an LLM in that case is the failure mode.

### 6.3 Relation to confidence asymmetry rule (SPEC-374)

Both SPEC-374 and SPEC-375 instantiate the same underlying principle: a non-deterministic signal (confidence or LLM reviewer verdict) must not suppress a more reliable signal (risk tier from the rubric, or a deterministic gate exit code). The mechanisms are distinct; the principle is the same.

---

## 7. Open Questions for Architect

**OQ-375-01:** The condition 16 placeholder references "once the evaluator re-derivation work lands." What is the commit range or PR number that constitutes "landed"? The spec needs a pointer to avoid ambiguity about when AC-375-06 becomes verifiable.

**OQ-375-02:** `prompt_audit_risk.py` and `hallucination_surface.py` use heuristic pattern matching but do not call an LLM. Are they deterministic for the purposes of this invariant? The spec's current definition (same input → same exit code) suggests yes, but confirm with the architect since their output varies with pattern set updates.

**OQ-375-03:** The `gate-deterministic-suppressed` audit event in condition 16 requires the evaluator to compare gate output (in `summary.json`) against reviewer register entries. This comparison assumes `summary.json` records findings at enough granularity to match against register entries. Confirm the schema supports this before condition 16 implementation.

---

## 8. Evidence

Parris 2026 (AIRA): Documented an LLM reviewer masking a failure that a deterministic scanner had correctly caught, producing false assurance. The synthetic scenario is directly reproducible and generalizes to any pipeline where LLM verdict and deterministic output feed a shared synthesis layer.

Loker 2025 (CodeRabbit, as reported in Ferdous et al. 2026 MSR): AI-generated code carries approximately 1.7x more high-severity findings than human-authored code. A synthesis layer that can suppress deterministic signal therefore operates at elevated base-rate risk.
