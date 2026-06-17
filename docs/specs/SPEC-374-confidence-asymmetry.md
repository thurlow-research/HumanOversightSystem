# Requirements Spec — Issue #374: Confidence Asymmetry Rule

**Document type:** Requirements specification (pre-implementation; authoritative)
**Status:** Approved — ready for implementation
**Issue:** #374
**Date authored:** 2026-06-16
**Author:** pm-agent
**Priority:** P2

---

## 1. Problem Statement

The HOS protocol requires every authoring agent to emit a `CONFIDENCE:` declaration (AGENTS.md §3, contract/OVERSIGHT-CONTRACT.md §2). The protocol specifies the format and instructs agents to "be honest" and treat low confidence as a human signal. It does not specify what downstream actors — orchestrators, risk-assessors, or the oversight-evaluator — may or may not do with a high-confidence declaration.

That gap is exploitable. Without an explicit prohibition, an orchestrator or risk-assessor could reason that a 95% confidence declaration warrants reducing the required reviewer set, lowering a risk tier, or skipping a gate. This would be wrong on both logical and empirical grounds.

**Empirical basis (Ferdous et al. 2026, MSR):** Agent self-reported confidence does not predict defect rates. 99.9% of agent PRs self-report confidence 8–10 on a 10-point scale (equivalent to 80–100%). Defect rates across that band are flat: 3.16–3.96%. A signal that is both saturated (99.9% of cases land in one band) and uncorrelated with outcomes (flat defect rate across the band) is uninformative for routing. Using it to reduce oversight provides no safety benefit and introduces an active manipulation surface — a miscalibrated or adversarial agent could inflate its declared confidence to shed reviewers.

The fix is not to remove the `CONFIDENCE:` field. Low confidence is a useful signal in the upward direction: an agent reporting 40% confidence on HIGH-risk code is a meaningful flag for human attention. The fix is to make the asymmetry explicit and enforced by construction: confidence flows in one direction only.

---

## 2. Scope

### In scope

- The confidence asymmetry rule: its statement, its prohibitions, and where it applies in the framework
- Required changes to `AGENTS.md §3` (Confidence Declaration section)
- Required behavior of `oversight-evaluator` Phase 2 with respect to confidence
- Acceptance criteria that can be verified by a coder, reviewer, or test agent without access to implementation history

### Out of scope

- Architecture of the evaluator's Phase 2 reasoning engine (architect's domain)
- The `CONFIDENCE:` field format or schema (unchanged)
- Routing table implementation details (architect's and technical-design's domain)
- Any change to how agents compute or self-report confidence
- Risk tier assignment logic beyond the single prohibition stated in REQ-374-01

---

## 3. Requirements

### 3.1 The asymmetry rule

**REQ-374-01 (the rule):** Agent-declared confidence is a one-directional signal. Low confidence MAY surface as a Phase 2 quality flag (see REQ-374-08). High confidence MUST NEVER:

- Lower a risk tier below what the risk rubric and deterministic validators assign
- Remove or skip a reviewer from the required sign-off set
- Substitute for a gate, whether deterministic (lint, security scanner, type check) or manual (human authorization)
- Reduce the oversight-evaluator's scrutiny of a finding

**REQ-374-02 (enforced by construction):** Confidence is excluded from all automated routing decisions and tier assignments. No code path in the orchestrator, risk-assessor, or oversight-evaluator may read the `CONFIDENCE:` value and use it to reduce the required sign-off set, lower a risk tier, or suppress a finding.

**REQ-374-03 (human signal only):** Agent confidence is provided solely as a calibration prior for the human reader. Its purpose is to help the human allocate their attention before reading code and review output. The pipeline does not act on it in the risk-lowering direction.

### 3.2 Where the rule applies

**REQ-374-04 (AGENTS.md §3 — Confidence Declaration):** The asymmetry rule must be stated explicitly in the Confidence Declaration section of `AGENTS.md`. The statement must include:

- (a) The prohibition: high confidence may never lower a tier, skip a reviewer, or substitute for a gate
- (b) The enforcement mechanism: confidence is excluded from all automated routing decisions (enforced by construction)
- (c) The empirical basis for the prohibition: Ferdous et al. 2026 — confidence flat at 3.16–3.96% defect rate across self-reported confidence levels 8–10, with 99.9% of agent PRs in that band, making high confidence a saturated and uninformative routing signal
- (d) The directional asymmetry: low confidence remains a valid signal upward (to the human); high confidence carries no routing authority

The addition must be contiguous with the existing `CONFIDENCE:` format block so it is read together with the declaration requirement, not in a separate section.

**REQ-374-05 (oversight-evaluator Phase 2):** The oversight-evaluator's Phase 2 quality evaluation logic must treat a finding as a finding regardless of the authoring agent's reported confidence level. Specifically:

- A finding identified by a Phase 2 check (convergence failure, critical finding resolved, confidence gap, second review flag) must not be suppressed or deprioritized because the authoring agent declared high confidence
- A confidence gap flag (CONFIDENCE < 70% on HIGH+ files, per the existing Phase 2 "Confidence gaps" check) must not be dismissed by the evaluator on the basis that a different part of the diff carried high confidence
- The evaluator must not infer reduced human-review urgency from the authoring agent's confidence level

**REQ-374-06 (contract/OVERSIGHT-CONTRACT.md §7 — compliance conditions):** The existing compliance conditions in §7 govern what must be present for a step to advance. The asymmetry rule does not add a new compliance condition to §7. It is a behavioral constraint on how existing conditions are interpreted. No change to the step manifest schema, sign-off register schema, or compliance conditions 1–10 is required.

### 3.3 What the rule does NOT change

**REQ-374-07 (declaration requirement unchanged):** All agents producing code at MEDIUM risk or above must continue to emit the `CONFIDENCE:` declaration in the format specified in AGENTS.md §3 and contract/OVERSIGHT-CONTRACT.md §2. This requirement is not relaxed or removed.

**REQ-374-08 (low confidence remains a signal):** The oversight-evaluator's Phase 2 "Confidence gaps" check (CONFIDENCE < 70% on HIGH+ files not addressed by reviewers) is unchanged and continues to produce a quality flag. Low confidence is still a valid upward signal. The asymmetry rule does not eliminate low-confidence flags; it only prohibits high confidence from reducing oversight.

**REQ-374-09 (computation unchanged):** How agents compute or self-report confidence is unchanged. Agents continue to self-report as a subjective estimate. This spec introduces no new measurement method, calibration requirement, or validation of the declared value's accuracy.

**REQ-374-10 (field placement unchanged):** The `CONFIDENCE:` field remains in the self-flag block alongside `RISK:` and `BLAST RADIUS:`. Removing it would eliminate the human-reader signal. The fix is asymmetric routing exclusion, not field removal.

---

## 4. Acceptance Criteria

These criteria are verifiable without access to implementation history. Each corresponds to a behavioral assertion the coder must satisfy and a reviewer can check.

**AC-374-01 (AGENTS.md text):** The Confidence Declaration section of `AGENTS.md` contains the asymmetry rule. The rule text names: the prohibition (high confidence may never lower a tier, skip a reviewer, or substitute for a gate), the enforcement mechanism (excluded from automated routing), and the empirical basis (Ferdous et al. 2026, confidence flat at 3.16–3.96% across the 8–10 band, 99.9% saturation rate).

**AC-374-02 (routing exclusion — verifiable by static analysis):** A code search or grep over the routing path (orchestrator, risk-assessor, oversight-evaluator) finds no branch that reads the `CONFIDENCE:` field value and uses it to reduce the required sign-off set, remove a reviewer, or lower a risk tier. Confidence may appear in output formatting and in Phase 2 low-confidence flag logic; it must not appear in the risk-lowering routing path.

**AC-374-03 (evaluator Phase 2 finding independence):** The oversight-evaluator Phase 2 logic contains no branch that reads a reported confidence level and either reduces finding severity or suppresses a finding on that basis. Specifically: a finding in the Phase 2 quality checklist (convergence, critical-finding-resolved, second review flag) cannot be discarded because the authoring agent's declared confidence was high.

**AC-374-04 (declaration not removed):** After implementation, agent output at MEDIUM+ risk still includes the `CONFIDENCE:` field. The field is present in the coder's self-flag block. The asymmetry rule did not eliminate the field.

**AC-374-05 (low-confidence flag preserved):** The oversight-evaluator still flags CONFIDENCE < 70% on HIGH+ files not addressed by reviewers as a Phase 2 quality concern. The asymmetry rule did not remove the low-confidence flag path.

---

## 5. Interaction with Existing Framework

**AGENTS.md §3 (Confidence Declaration):** The asymmetry rule is an additive constraint on the existing requirement. The existing requirement says what to emit and how to compute it. This spec adds a rule about what downstream actors may not do with the emitted value. No existing text is removed; the new text is added contiguous with the existing format block.

**oversight-evaluator Phase 2 (Confidence gaps check):** This check already flags low confidence at HIGH+. The asymmetry rule clarifies the one-directionality: flags go upward (to the human), not downward (to reduce oversight). The existing check is unchanged; this spec adds a prohibition on the inverse direction.

**SPEC-375 (deterministic gate invariant):** The two rules are complementary. SPEC-375 prevents a non-deterministic LLM reviewer verdict from suppressing a finding that a deterministic gate established. SPEC-374 prevents an agent's self-declared confidence from suppressing findings or reducing required oversight. Both enforce the same principle — non-deterministic self-assessments cannot override deterministic or externally-required controls — from different directions. The mechanisms are distinct and both are required.

**contract/OVERSIGHT-CONTRACT.md §2 (self-flag format):** The self-flag format is unchanged. No new field is added. The prohibition is on downstream use, not on the declaration itself.

**contract/OVERSIGHT-CONTRACT.md §7 (compliance conditions):** No new compliance condition is added. The asymmetry rule is a behavioral constraint on interpretation of existing conditions, not an independent compliance gate.

---

## 6. Open Questions for Architect

These are questions the spec cannot resolve; the architect must answer them before or during technical design.

**OQ-374-01 (active validation vs. construction):** The spec requires enforcement by construction — no code path reads confidence to reduce oversight. Should the oversight-evaluator also actively validate that confidence was not used as a justification (e.g. by checking that no `human-tier-override.md` cites confidence as the reason for a tier reduction), or is exclusion-by-construction sufficient? An active check would be defense-in-depth but requires defining what "cited confidence as justification" means in a parseable way. The spec does not mandate this; the architect should decide whether the construction guarantee alone is sufficient given the manipulation-surface concern in §1.

**OQ-374-02 (evaluator self-declaration scope):** The asymmetry rule applies to authoring agents. The oversight-evaluator is not an authoring agent; it produces assessments, not code. Should the evaluator emit a `CONFIDENCE:` field in its own sign-off entries? If yes, the asymmetry rule applies to those declarations as well (no downstream actor may use the evaluator's declared confidence to reduce scrutiny). If no, the evaluator's assessments carry no confidence field and the rule does not apply. The spec is silent on this; the architect should confirm scope.

**OQ-374-03 (test verifiability of AC-374-02):** AC-374-02 states that no branch in the routing path reads `CONFIDENCE:` to reduce oversight. This is currently framed as a static-analysis / grep assertion. Should this be a runtime assertion (e.g. a test that exercises the routing path with varying confidence values and asserts the output is identical), or is static analysis sufficient? The answer affects what the unit-test agent must produce for this step.

---

## 7. Evidence Base

**Ferdous et al. 2026 (Mining Software Repositories):** The study analyzed self-reported agent confidence against measured defect rates across a large corpus of agent-submitted PRs. Findings:

- 99.9% of agent PRs self-report confidence in the 8–10 band (on a 10-point scale)
- Defect rates across that band are flat: 3.16% (confidence 8), 3.51% (confidence 9), 3.96% (confidence 10)
- There is no statistically significant relationship between self-reported confidence level and defect presence within the 8–10 band
- A signal that is saturated (nearly all cases land in one value range) and uncorrelated with the outcome variable (defects) has no routing utility — it cannot discriminate high-risk from low-risk output

**Protocol implication:** Using high confidence to reduce oversight produces no safety benefit (the defect rate is unchanged) and introduces a manipulation surface (agents or prompts could be constructed to always report 10/10 confidence to minimize required review). The asymmetry rule eliminates both problems: low confidence (below the saturation band) remains a valid upward signal; high confidence is stripped of routing authority.
