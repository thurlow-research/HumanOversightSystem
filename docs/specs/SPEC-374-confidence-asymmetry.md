# Requirements Spec — Issue #374: Confidence Asymmetry Rule

**Document type:** Requirements specification
**Status:** Implemented — confidence asymmetry rule added to AGENTS.md §3 and enforced by construction in routing logic
**Issue:** #374
**Date:** 2026-06-16
**Author:** pm-agent
**Priority:** P2

---

## 1. Problem Statement

Agent-declared confidence was underspecified as a signal. The protocol required agents to emit a `CONFIDENCE:` declaration but said nothing about how downstream routing and review decisions could use it. This created an unguarded path: an agent or orchestrator could reason that high confidence at the CONFIDENCE field warranted skipping a reviewer or reducing a risk tier, collapsing the oversight pipeline for the exact changes most likely to carry latent defects (high-confidence AI output has a known self-report saturation problem — see §7).

The rule codifies the asymmetry explicitly: confidence is a one-directional input to the human reader only. It may never flow back into routing decisions that weaken oversight.

---

## 2. Scope

This spec covers:

- The confidence asymmetry rule itself (what it says and what it forbids)
- The locations in the framework where the rule applies: `AGENTS.md §3` and `oversight-evaluator` Phase 2 reasoning
- What the rule does NOT change: the confidence declaration requirement and how confidence is computed

This spec does NOT cover:

- Architecture of the evaluator's Phase 2 reasoning engine
- Any change to the `CONFIDENCE:` field format or schema
- Routing table changes (the rule is enforced by exclusion, not by adding a new routing path)

---

## 3. Requirements

### 3.1 The asymmetry rule (what it says)

**REQ-374-01:** Agent-declared confidence is a one-directional signal. Low confidence may raise human attention. High confidence may never:
- Lower a risk tier below what the risk rubric and deterministic validators assign
- Skip a reviewer from the required sign-off set
- Substitute for a gate (deterministic or manual)

**REQ-374-02:** The asymmetry must be enforced by construction: agent confidence is excluded from all automated routing decisions and tier assignments. No code path in the orchestrator, risk-assessor, or oversight-evaluator may read the confidence field and use it to reduce the required sign-off set or lower a risk tier.

**REQ-374-03:** Agent confidence is provided solely as a calibration prior for the human reader. Its purpose is to help the human allocate their attention before reading the code — it is not a signal the pipeline acts on in the risk-lowering direction.

### 3.2 Where the rule applies

**REQ-374-04 (AGENTS.md §3):** The confidence asymmetry rule must be stated in the Confidence Declaration section of `AGENTS.md` alongside the `CONFIDENCE:` format requirement. The statement must name: (a) that high confidence may never lower a tier, skip a reviewer, or substitute for a gate; (b) that the asymmetry is enforced by construction (confidence excluded from routing); and (c) the empirical basis (Ferdous et al. 2026 — confidence flat across levels 8–10 in 99.9% of agent PRs).

**REQ-374-05 (oversight-evaluator Phase 2):** The oversight-evaluator's Phase 2 quality evaluation must not deprioritize or suppress findings on the basis that the authoring agent reported high confidence. A finding remains a finding regardless of the reported confidence level.

### 3.3 What the rule does NOT change

**REQ-374-06:** The confidence declaration requirement is unchanged. All agents producing code at MEDIUM risk or above must still emit `CONFIDENCE: [percentage]` with a one-sentence basis.

**REQ-374-07:** How confidence is computed is unchanged. Agents continue to self-report confidence as a subjective estimate. The spec introduces no new measurement method or calibration mechanism.

**REQ-374-08:** The confidence field remains in the self-flag block. Removing it would eliminate the human-reader signal; the fix is asymmetric routing exclusion, not field removal.

---

## 4. Acceptance Criteria

**AC-374-01:** The `AGENTS.md §3` Confidence Declaration section contains the asymmetry rule stating that high confidence may never lower a tier, skip a reviewer, or substitute for a gate.

**AC-374-02:** A unit-testable assertion exists confirming that no routing code reads the confidence value and uses it to reduce required sign-offs or lower a tier. Confidence must be excluded from all automated routing decisions (verifiable by grep or static analysis on the routing path).

**AC-374-03:** The oversight-evaluator Phase 2 logic contains no branch that reads a reported confidence level and reduces finding severity or suppresses a finding on that basis.

**AC-374-04:** The `AGENTS.md` rule text names the empirical basis: Ferdous et al. 2026, with the specific finding (confidence flat at 3.16–3.96% defect rates across self-reported confidence levels 8–10, with 99.9% of agent PRs self-reporting in that band — making it a saturated, uninformative routing signal).

**AC-374-05:** The confidence field continues to appear in agent output (the declaration requirement is not removed by this change).

---

## 5. Interaction with Existing Protocol

The asymmetry rule is additive to the existing confidence declaration requirement (AGENTS.md §3). It adds a constraint on downstream use without changing the declaration itself.

The rule is consistent with the deterministic gate non-override invariant (SPEC-375): both rules prevent a non-deterministic signal (confidence or LLM reviewer verdict) from suppressing a finding that a more reliable mechanism established. The mechanisms are distinct: SPEC-375 governs deterministic gate output; SPEC-374 governs agent self-declared confidence.

No change to the step manifest schema, sign-off register schema, or oversight contract conditions 1–15 is required by this rule.

---

## 6. Open Questions for Architect

**OQ-374-01:** Should the evaluator actively validate that confidence was not used in routing (e.g. by checking that no `human-tier-override.md` cites confidence as justification), or is exclusion-by-construction sufficient? The current spec relies on construction; an active check would be defense-in-depth but requires defining what "cited confidence as justification" means in a parseable way.

**OQ-374-02:** Should the `CONFIDENCE:` field be present in the oversight-evaluator's own sign-off entries? The evaluator is not an authoring agent, but it does produce assessments. The current spec applies the asymmetry rule only to authoring agents — confirm scope is correct.

---

## 7. Evidence

Ferdous et al. 2026 (MSR): Self-reported agent confidence does not predict defect presence. Defect rates were flat across confidence levels 8–10 (the band that 99.9% of agent PRs self-report), at 3.16–3.96%. A signal that is saturated at the high end and uncorrelated with outcomes is uninformative for routing; using it to lower oversight produces no safety benefit and introduces a manipulation surface.
