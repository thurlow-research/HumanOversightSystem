# SPEC-375 — Deterministic Gate Non-Override Invariant

**Issue:** #375
**Document type:** Requirements specification (authoritative — prior version superseded)
**Status:** APPROVED — 2026-06-16
**Author:** pm-agent
**Priority:** P2 (oversight correctness — directly impacts escaped-defect rate)

---

## 1. Problem Statement

The oversight pipeline uses two categories of signal:

1. **Deterministic gates and validators** — scripts with stable, non-LLM evaluation paths. Same input, same exit code. They exit 0 (pass) or non-zero (fail).
2. **LLM reviewers** — agents that reason probabilistically about the same code and produce verdicts that can vary across runs.

Prior to this spec, the contract prohibited nothing about the interaction between these two signal categories. A deterministic gate could exit non-zero (a real finding), an LLM reviewer could evaluate the same code and produce no finding, and a synthesis layer (the arbiter, the oversight-orchestrator, or the oversight-evaluator) could treat the LLM's silence as resolving the deterministic failure. The defect then escapes to the PR or beyond.

**The masking failure mode in detail:** Gate G exits non-zero for file F. Reviewer R evaluates file F and concludes no issue. The synthesis layer records G's finding as "addressed" (or never surfaces it) on the basis of R's approval. The human never sees G's finding. This is not a theoretical gap: Parris (2026, AIRA) documented this failure in practice.

**Why this matters at scale:** Loker (2025, as reported in Ferdous et al. 2026 MSR) found AI-generated code carries approximately 1.7x more high-severity findings than human-authored code. A synthesis layer that can bury a deterministic signal operates at elevated base-rate risk — the population of high-severity findings is larger and the suppression path remains open.

---

## 2. Scope

This spec covers:

- Definition of a deterministic gate for the purposes of this invariant
- The invariant: what it prohibits, what it permits
- What the arbiter may do with a deterministic finding
- Where the invariant is enforced in the framework (oversight-evaluator Phase 1, contract §7)
- The compliance check: how the evaluator detects a suppression
- Interaction with the evaluator re-derivation work (SPEC-evaluator-re-derivation.md, conditions 11–15)
- Interaction with the existing gate suspension mechanism (OVERSIGHT-CONTRACT.md §3)
- Acceptance criteria

This spec does NOT cover:

- How deterministic gates or validators compute their output internally — that is their own domain
- Architecture of the evaluator re-derivation engine (SPEC-evaluator-re-derivation.md, conditions 11–15) — that is the architect's domain
- The remediation path after a deterministic failure is surfaced to a human — the human decides
- Which gates a project must run — that is the step-manifest's domain

---

## 3. Definitions

### 3.1 Deterministic gate

A **deterministic gate** is any script in `scripts/oversight/gates/` or any validator in `scripts/oversight/validators/` that:

- Takes inputs (files, diffs, or configuration),
- Applies fixed, non-LLM rules, and
- Exits 0 (pass) or non-zero (fail) with the same result for the same input on any run.

The authoritative lists as of this spec's date:

**Gates (`scripts/oversight/gates/`):**

| Script | Canonical gate name |
|---|---|
| `lint_check.sh` | `lint` |
| `security_scan.sh` | `security` |
| `secret_scan.sh` | `secrets` |
| `type_check.sh` | `types` |
| `template_refs_check.sh` | `template-refs` |
| `portability_check.sh` | `portability` |
| `django_check.sh` | `django` |
| `collection_integrity.sh` | `collection-integrity` |
| `expensive_gates_stub.sh` | `expensive-gates` (stub; treated as gate when project-specific logic is installed) |

Note: `check_suspension.sh` is a shared helper sourced by other gates, not a gate itself. It is not a deterministic gate for the purposes of this invariant.

**Validators (`scripts/oversight/validators/`):**

| Script | Dimension |
|---|---|
| `rn_calculator.py` | `risk_number` |
| `complexity_metrics.py` | `cyclomatic`, `cognitive` |
| `function_metrics.py` | `function_metrics` |
| `n1_detector.py` | `n1_queries` |
| `migration_scorer.py` | `migration_risk` |
| `static_analysis.py` | `static_analysis` |
| `ip_check.py` | `ip_check` |
| `prompt_audit_risk.py` | `prompt_ambiguity` |
| `hallucination_surface.py` | `hallucination_surface` |
| `issue_query.py` | `historical_density` |

Note: `schema.py` and `regions.py` are library modules, not validators that produce findings. They are not deterministic gates for the purposes of this invariant.

### 3.2 Deterministic failure

A **deterministic failure** for a gate is: the gate script exits non-zero on a run that was not suspended via `contract/gate-suspension.md`.

A **deterministic failure** for a validator is: the validator's output JSON contains `"error": null` (the validator ran successfully) AND the output's `score` or findings indicate a blocking finding, OR the validator exits non-zero and `summary.json` records `"error":` for that dimension. The per-validator output is written to `.claudetmp/oversight/validators/<dimension>.json`; the aggregate is written to `.claudetmp/oversight/validators/summary.json`.

**Clarification on "blocking" validator findings:** Not every non-zero validator score constitutes a blocking failure. For the purposes of this invariant, a validator failure that must be surfaced is one that either:

(a) Caused `run_validators.sh` to exit non-zero (i.e., a required validator failed to run or the fail-closed CRITICAL path fired), or
(b) Appears in `risk-assessment.md`'s `blocking_findings:` list with `resolution: unresolved` (contract §7, condition 7b).

A validator that runs successfully and produces a non-zero score is a risk signal fed to the composite — it does not by itself constitute a deterministic failure requiring human surfacing under this invariant. The blocking-findings list in `risk-assessment.md` is the authoritative record of which validator outputs rose to the level of blocking the step.

### 3.3 LLM reviewer

An **LLM reviewer** is any agent whose verdict is produced by a large language model: `code-reviewer`, `security-reviewer`, `privacy-reviewer`, `reliability-reviewer`, `ops-reviewer`, `ui-reviewer`, `a11y-reviewer`, `infra-reviewer`, any second-review agent (agy, codex), the panel arbiter, and the oversight-orchestrator when it synthesizes findings.

### 3.4 Suppression

**Suppression** of a deterministic failure means any action by an LLM reviewer or the arbiter that causes the finding to be absent from, or marked as resolved in, the human-facing output without a human-authorization artifact covering that specific gate. This includes:

- Marking the finding as closed, resolved, or addressed in the sign-off register or handoff.md
- Summarizing the finding as "addressed by reviewer" in the handoff or panel-context
- Absorbing the finding into a general "clean" verdict in the evaluation output
- Treating LLM reviewer silence on the same issue as resolution of the deterministic finding
- Treating LLM reviewer approval of the associated code as resolution of the deterministic finding

---

## 4. The Invariant

### REQ-GATE-NN-01 — Core prohibition

A deterministic gate failure must be surfaced to the human gate verbatim. It cannot be resolved, downgraded, closed, summarized away, or absorbed by an LLM reviewer or the arbiter. LLM reviewer agreement does not resolve a deterministic failure. LLM reviewer silence does not close one. LLM reviewer disagreement is noted as additional context but does not remove the deterministic finding from the human-facing output.

### REQ-GATE-NN-02 — Arbiter permission

The arbiter (oversight-orchestrator, panel arbiter, or any synthesis agent) may add context, corroboration, or additional perspective to a deterministic finding. It may never suppress or outrank the deterministic finding. Adding context means: citing the deterministic finding by name and then appending the LLM reviewer's perspective as a supplementary note. Suppressing means: replacing the deterministic finding entry with an LLM reviewer conclusion or omitting the deterministic finding from the human-facing output.

### REQ-GATE-NN-03 — Independence from LLM verdict

The requirement to surface a deterministic failure holds regardless of the LLM verdict on the same code. The two signal categories are independent; neither can resolve the other. The combination "gate fails, reviewer approves" is not a net-clean result — it is a deterministic failure with an LLM corroborating opinion, which is still a deterministic failure.

### REQ-GATE-NN-04 — Suspended gates are not subject to this invariant

A gate suspended via `contract/gate-suspension.md` is explicitly human-authorized. A suspended gate exits 0; its `gate-suspended` event is recorded in the audit log with `authorized_by`. The invariant does not apply to suspended gates. Suspension is a legitimate human-authorized path; LLM suppression of a non-suspended gate is not.

### REQ-GATE-NN-05 — Human decision authority

The invariant governs what reaches the human, not what the human decides. After reviewing a surfaced deterministic finding, the human may conclude it is a false positive and authorize proceeding. That decision is exercised through a human-authorization artifact (`.claudetmp/oversight/step{N}-human-authorization.md`), which explicitly references the gate by name. The invariant is satisfied once the finding is surfaced and the human has decided.

### REQ-GATE-NN-06 — LLM corroboration is permitted and encouraged

The invariant does not prevent LLM reviewers from commenting on the same issue a deterministic gate flagged. LLM corroboration — "the security reviewer also found this" — or additional context is useful. What is prohibited is the synthesis layer treating LLM silence or LLM approval as resolution of the deterministic finding.

---

## 5. Enforcement Location

### 5.1 OVERSIGHT-CONTRACT.md §7

**REQ-GATE-NN-07:** The invariant must be stated in `OVERSIGHT-CONTRACT.md` §7 (the compliance check section). The contract text must:

(a) Name which gate categories are covered: all scripts in `scripts/oversight/gates/` and all validators in `scripts/oversight/validators/` that exited non-zero.
(b) State what is prohibited: LLM reviewer resolution, summarization, absorption, or silent treatment of a non-suspended gate failure.
(c) State what the arbiter may do: add context or corroboration, never suppress or outrank.
(d) Reference the condition number (REQ-GATE-NN) and the placeholder relationship to condition 16 from SPEC-evaluator-re-derivation.md.

### 5.2 Oversight-evaluator Phase 1 — Compliance check

**REQ-GATE-NN-08:** The oversight-evaluator Phase 1 must check the following condition (label: REQ-GATE-NN) during every per-step build evaluation:

For each gate listed in `summary.json` or each entry in `risk-assessment.md`'s `blocking_findings:` list that is `resolution: unresolved`:

1. Is there a human-authorization artifact (`.claudetmp/oversight/step{N}-human-authorization.md`) that explicitly references that gate or blocking finding by name?
2. If yes: the deterministic finding is covered. Record as covered.
3. If no: check whether the finding appears as unresolved in the human-facing output (handoff.md). If the finding does NOT appear as unresolved in the human-facing output → **COMPLIANCE FAIL** (REQ-GATE-NN): a deterministic failure was suppressed without human authorization. Report the gate name, the recorded failure, and the absence of a covering human-authorization artifact.

**The compliance check does not re-run the gate.** It reads the recorded output in `summary.json` (for composite failures) and `risk-assessment.md` (for blocking findings). The evaluator trusts these artifacts as the record of what ran; condition 7b (scope check from SPEC-evaluator-re-derivation.md) ensures they were scoped to the correct commit range.

**REQ-GATE-NN-09 — Audit event:** When REQ-GATE-NN fires, the evaluator must append a `gate-deterministic-suppressed` event to `audit/oversight-log.jsonl`. Required fields:

```json
{
  "event": "gate-deterministic-suppressed",
  "step": N,
  "gate": "<gate-name or blocking-finding-id>",
  "source": "gates" | "validators",
  "suppression_evidence": "<what was missing from human-facing output>",
  "timestamp": "<ISO-8601>"
}
```

**REQ-GATE-NN-10 — Compliance failure direction:** This check runs in both directions. A deterministic failure is not a "loosening determination" — it cannot be skipped when upstream asked for more review. A gate that exited non-zero is always a compliance issue unless covered by a human-authorization artifact.

### 5.3 Handoff and panel-context output

**REQ-GATE-NN-11:** The oversight-orchestrator, when producing `handoff.md`, must include all unresolved deterministic failures as a distinct section. The section heading must be "Unresolved Deterministic Gate Failures" and must appear before any LLM reviewer summary sections. Each entry must name the gate, the exit code or blocking finding, and state explicitly that it is unresolved and requires human decision.

**REQ-GATE-NN-12:** The oversight-orchestrator, when producing `panel-context.md`, must include unresolved deterministic failures as structural risk signals. The panel sees these as part of the structural risk picture. The panel-context must not omit a gate failure and must not characterize it as resolved on the basis of an LLM reviewer's conclusion.

---

## 6. Interaction with Existing Protocol

### 6.1 Relation to conditions 11–15 (SPEC-evaluator-re-derivation.md)

Conditions 11–15 (from SPEC-evaluator-re-derivation.md) are independent re-derivation checks: they re-derive tier floors, warranted reviewer lanes, document modification coverage, spec-change behavior deltas, and subagent compliance from the diff. Those conditions are additive Phase 1 gates.

The deterministic gate non-override invariant (REQ-GATE-NN) is conceptually separate: it governs what happens to deterministic gate output after it is recorded — specifically whether an LLM reviewer can suppress it. REQ-GATE-NN applies ON TOP of conditions 11–15. A step that passes conditions 11–15 can still fail REQ-GATE-NN if a gate failure was suppressed.

### 6.2 Condition 16 from SPEC-evaluator-re-derivation.md

The SPEC-evaluator-re-derivation.md marks condition 16 as reserved for the step-head timing correction (#220). REQ-GATE-NN does not occupy condition 16 in the numbered sequence. This spec uses the label REQ-GATE-NN (avoiding a number) specifically to avoid a conflict with the numbered conditions 11–16 from that spec. The contract text should introduce REQ-GATE-NN as a named invariant condition that sits alongside the numbered conditions, not as a numbered condition in that sequence.

### 6.3 Relation to gate suspension (OVERSIGHT-CONTRACT.md §3)

Gate suspension via `contract/gate-suspension.md` is the legitimate human-authorized path for deferring a deterministic gate. The invariant does not apply to suspended gates. The compliance check (REQ-GATE-NN-08) must consult `contract/gate-suspension.md` (same as the existing suspension check in Phase 1) and skip any gate whose name appears as `SUSPENDED: <gate>` before checking for suppression.

### 6.4 Relation to confidence asymmetry rule (SPEC-374)

Both SPEC-374 and this spec instantiate the same underlying principle: a non-deterministic signal (LLM confidence or reviewer verdict) must not suppress a more reliable signal (risk tier from the rubric, or a deterministic gate exit code). The mechanisms are distinct and enforced separately. A step that passes SPEC-374 may still fail REQ-GATE-NN and vice versa.

### 6.5 Relation to second-review compliance (OVERSIGHT-CONTRACT.md §7, MEDIUM fail-closed)

The second-review compliance check (contract §7, MEDIUM fail-closed section) governs whether a cross-vendor independent review ran and produced a valid verdict. REQ-GATE-NN is separate: it governs whether a deterministic gate failure was subsequently suppressed by any LLM actor (including the second-review agents). A second-review `verdict: approve` does not resolve a deterministic failure; REQ-GATE-NN still applies.

---

## 7. Human-Authorization Path

**REQ-GATE-NN-13:** A deterministic finding may be resolved only by a human-authorization artifact. The artifact (`.claudetmp/oversight/step{N}-human-authorization.md`) must:

- Be created by a human (agents may not create or modify it — the same prohibition that applies to all human-authorization artifacts in the contract)
- Explicitly name the gate or blocking finding being authorized: e.g., "Gate `security` (bandit HIGH: SQL injection in views.py:42) reviewed and assessed as false positive — proceed"
- Include a date and a decision text (same format as existing human-authorization artifacts)

An artifact that does not explicitly name the gate it covers does not satisfy REQ-GATE-NN-08. A general "proceed" authorization without gate identification does not constitute coverage.

**REQ-GATE-NN-14:** The oversight-evaluator, when recording a covered deterministic finding, must include the authorization in the Phase 1 compliance table (the existing role/status table) as an additional row or annotation: "Gate: `<name>` — covered by human-authorization artifact dated `<date>`."

---

## 8. Gate Results Artifact

**REQ-GATE-NN-15:** The gate runner — the pipeline step that invokes `gates/*.sh` — writes a `gate-results.json` file to `.claudetmp/oversight/validators/`. `run_validators.sh` does not write gate exit codes and does not orchestrate gate execution; it is the validator-composite script only. Each gate appends its record to `gate-results.json` as it runs:

```json
{
  "gate": "<gate-name>",
  "exit_code": <int>,
  "suspended": <bool>,
  "script": "<path>"
}
```

The oversight-evaluator reads `gate-results.json` alongside `summary.json` during the REQ-GATE-NN-08 compliance check. `gate-results.json` is a separate artifact from `summary.json`; `gate_failures` must NOT be added to `summary.json`, which remains the validator-composite artifact only.

**REQ-GATE-NN-16 — Fail-closed on missing gate-results.json:** If `gate-results.json` is absent on a step where gates were required to run, the oversight-evaluator must treat this as a COMPLIANCE FAIL. Absence of the file must never be read as "no gates failed." This parallels the existing fail-closed rule for a missing `risk-assessment.md`: the absence of the required artifact is itself the compliance failure. The evaluator must not proceed to PROCEED or CONDITIONAL_PROCEED when `gate-results.json` is absent and the step manifest requires gates.

**REQ-GATE-NN-17 — Composite cross-check:** The oversight-evaluator must independently check `summary.json`'s `composite_score` against the CRITICAL threshold (≥ 0.78, per `schema.py` `TIER_THRESHOLDS`). When the composite score meets or exceeds 0.78, the evaluator must surface a deterministic CRITICAL failure — regardless of what the LLM-authored `blocking_findings:` list in `risk-assessment.md` records. This closes the gap where the risk-assessor agent (which is LLM-based) could omit a finding from `blocking_findings:` that the composite score already reflects as CRITICAL. A CRITICAL composite score is a deterministic signal; it cannot be resolved by `blocking_findings:` being silent.

---

## 9. Acceptance Criteria

**AC-375-01:** Gate G exits non-zero for step N. The sign-off register contains a `security` entry with `Status: APPROVED`. No human-authorization artifact exists for step N. The oversight-evaluator Phase 1 produces COMPLIANCE FAIL (REQ-GATE-NN), not PROCEED or CONDITIONAL_PROCEED. The compliance failure names gate G explicitly.

**AC-375-02:** Gate G exits non-zero for step N. A human-authorization artifact exists at `.claudetmp/oversight/step{N}-human-authorization.md` that explicitly names gate G. The oversight-evaluator Phase 1 records gate G as covered and does not fail REQ-GATE-NN.

**AC-375-03:** Gate G is listed as `SUSPENDED: G` in `contract/gate-suspension.md`. Gate G is not checked under REQ-GATE-NN. The existing `gate-suspended` audit event and compliance behavior continue to apply.

**AC-375-04:** `handoff.md` for a step with an unresolved gate failure contains a section "Unresolved Deterministic Gate Failures" that names the gate. The section appears before any LLM reviewer summary. The section does not say the finding was addressed or resolved.

**AC-375-05:** `panel-context.md` for a step with an unresolved gate failure includes that gate failure as a structural risk signal. The panel-context does not characterize the failure as resolved on the basis of an LLM verdict.

**AC-375-06:** The `gate-deterministic-suppressed` audit event is written to `audit/oversight-log.jsonl` when REQ-GATE-NN fires. The event contains the `gate`, `source`, `suppression_evidence`, and `timestamp` fields.

**AC-375-07:** A blocking finding in `risk-assessment.md` with `resolution: unresolved` and no covering human-authorization artifact produces a COMPLIANCE FAIL on two conditions: condition 7b (existing, for blocking findings generally) and REQ-GATE-NN (for the suppression angle). The evaluator may report both in the same compliance failure output; it must not suppress one to avoid redundancy.

**AC-375-08:** `OVERSIGHT-CONTRACT.md §7` contains explicit text prohibiting LLM suppression of deterministic gate failures, using the three-part structure required by REQ-GATE-NN-07: what is covered, what is prohibited, what the arbiter may do.

**AC-375-09:** The compliance check does not re-run any gate. It reads only from `gate-results.json`, `summary.json`, `risk-assessment.md`, and the human-authorization artifact directory. Re-running gates is not within the evaluator's scope.

**AC-375-10:** The invariant applies to the validators listed in §3.1. A validator that produces a non-zero composite score (i.e., a risk signal) but does not appear in `blocking_findings:` and did not cause `run_validators.sh` to exit non-zero is not a deterministic failure requiring REQ-GATE-NN enforcement. The invariant does not apply to risk signals that did not rise to the blocking-finding level — except that a composite_score ≥ 0.78 is always a deterministic CRITICAL failure regardless of blocking_findings: content (REQ-GATE-NN-17).

**AC-375-11:** `gate-results.json` is absent for a step that required gates to run. The oversight-evaluator produces COMPLIANCE FAIL, not PROCEED or CONDITIONAL_PROCEED. The failure message states that gate-results.json was absent.

**AC-375-12:** `summary.json` for a step shows `composite_score: 0.82`. `risk-assessment.md`'s `blocking_findings:` list is empty. The oversight-evaluator surfaces a deterministic CRITICAL failure citing the composite score against the 0.78 threshold. The empty blocking_findings: list does not suppress this failure.

---

## 10. Open Questions for Architect

**OQ-375-ARCH-01 — RESOLVED (2026-06-16):** The architect ruled that `run_validators.sh` does not orchestrate gates and must not be extended to write gate results to `summary.json`. A separate gate runner (the pipeline step invoking `gates/*.sh`) writes `gate-results.json` to `.claudetmp/oversight/validators/`. The evaluator reads this file alongside `summary.json`. `gate_failures` must not be added to `summary.json`. Reflected in REQ-GATE-NN-15 and the §11 artifacts table.

**OQ-375-ARCH-02 — RESOLVED (2026-06-16):** The architect confirmed the compliance check must cross-check `summary.json`'s `composite_score` against the CRITICAL threshold (≥ 0.78 per `schema.py` `TIER_THRESHOLDS`) independently of what `blocking_findings:` records. A CRITICAL composite score is a deterministic signal that cannot be suppressed by LLM-authored omission from `blocking_findings:`. Reflected in REQ-GATE-NN-17 and AC-375-12.

**OQ-375-ARCH-03 — prompt_audit_risk.py and hallucination_surface.py determinism:** These validators use heuristic pattern matching (no LLM call). The spec's working definition (same input → same exit code) classifies them as deterministic. However, their outputs vary when the pattern set is updated (a change to the script itself changes results). Confirm with the architect whether pattern-set updates disqualify them from the deterministic category or whether the definition should be anchored to "same script + same input → same output" (which is stable between script updates). This affects whether their `blocking_findings` are subject to REQ-GATE-NN.

---

## 11. Artifacts to Update

The following artifacts must be updated by technical-design and implementation:

| Artifact | Change |
|---|---|
| `contract/OVERSIGHT-CONTRACT.md` | Add REQ-GATE-NN invariant to §7; add `gate-deterministic-suppressed` event to §6a audit catalog; add `gate-results.json` to required artifact list |
| `.claude/agents/oversight-evaluator.md` | Add REQ-GATE-NN-08 compliance check to Phase 1 (reads `gate-results.json`); add REQ-GATE-NN-09 audit event emit; add REQ-GATE-NN-14 coverage annotation to the compliance table; add REQ-GATE-NN-16 fail-closed check for absent `gate-results.json`; add REQ-GATE-NN-17 composite cross-check against CRITICAL threshold |
| `.claude/agents/oversight-orchestrator.md` | Add REQ-GATE-NN-11 "Unresolved Deterministic Gate Failures" section requirement in handoff.md output; add REQ-GATE-NN-12 requirement for panel-context.md |
| Gate runner (the pipeline step invoking `gates/*.sh`) | Write `gate-results.json` to `.claudetmp/oversight/validators/` (REQ-GATE-NN-15); each gate appends its record as it runs |
| `audit/oversight-log.jsonl` event catalog (in contract) | Add `gate-deterministic-suppressed` event |

---

## 12. Evidence

Parris (2026, AIRA): Documented an LLM reviewer masking a failure that a deterministic scanner had correctly caught, producing false assurance. The synthetic scenario is directly reproducible and generalizes to any pipeline where LLM verdict and deterministic output feed a shared synthesis layer.

Loker (2025, CodeRabbit, as reported in Ferdous et al. 2026 MSR): AI-generated code carries approximately 1.7x more high-severity findings than human-authored code. A synthesis layer that can suppress deterministic signal therefore operates at elevated base-rate risk when the codebase under review is AI-generated.
