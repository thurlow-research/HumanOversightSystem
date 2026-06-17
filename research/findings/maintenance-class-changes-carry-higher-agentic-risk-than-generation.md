# Finding: Maintenance-Class Changes Carry Higher Agentic Risk Than Generation

**Role:** oversight-mechanism — risk tier calibration

**First observed:** 2026-06-16, SLR full-text reads (Ferdous et al. 2026; Watanabe et al. 2026)

---

## The Finding

In agent-authored PRs, **refactor and chore task classes have higher breaking-change rates than feat and fix** — the inverse of the pattern observed in human PRs. Ferdous et al. 2026 reports:

| Task class | Breaking-change rate |
|---|---|
| refactor | 6.72% |
| chore | 9.35% |
| feat | 2.89% |
| fix | 2.69% |

Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166) adds the volume dimension: agents perform **24.9% refactoring** across their PR mix, compared to **14.9% for humans**. Agents are doing more of the work in the higher-risk task class, at a higher per-PR breaking-change rate.

## Why This Matters for Scalable Oversight

Standard content-type rubrics for risk calibration classify changes by *what they touch* — authentication code, payment flows, business-critical logic, external APIs. These rubrics are well-motivated for human-authored code, where the human pattern holds: new features and new functionality carry more risk than maintenance and cleanup.

For agent-authored code, the content-type rubric **misidentifies the risk surface.** A refactor that touches no critical-content area still carries a 6.72% breaking-change rate — higher than an agent-authored feature touching a nominally sensitive area (2.89%). The task-class signal is more predictive than the touched-content signal in the agentic setting, but current risk tiers do not incorporate it.

The combination of higher volume (24.9% vs. 14.9%) and higher breaking-change rate per PR means refactor is disproportionately represented in the escaped-defect population. It is the highest-risk agent task class by expected breakage, but it reads as "maintenance" and often receives the lightest scrutiny under content-type rubrics.

## Risk Tier Calibration Implication

The HOS risk tier rubric should incorporate **task class** as an independent signal axis for agent-authored changes:

- `refactor` and `chore` commits in agent PRs should receive a deterministic floor bump relative to the same-content-class `feat`/`fix` commits.
- A pure refactor (no new user-facing surface, no new dependency, no changed permission model) that would be LOW under a content rubric alone should be raised to at least MEDIUM given the empirical breaking-change rate.
- The `change_classifier.py` structural-override signatures (new dependency, new auth state, new route) are necessary but not sufficient: they target `feat`-class additions. The maintenance-class risk is not captured by structural signatures because a refactor that breaks an invariant by *restructuring* existing code adds none of those signatures.

## The Inversion Mechanism (Hypothesis)

The breaking-change rate inversion likely reflects a known limit of LLM code reasoning: agents are better at local generation (write new code from a spec) than at global invariant preservation (restructure existing code while keeping all callers consistent). Refactoring requires a model of the whole codebase's behavioral invariants; generation requires only a model of the new code's spec. The agent's confidence in the refactor is high (the code compiles, tests pass locally against a subset of cases) but the invariant-preservation failure is distributed across callsites the agent did not fully enumerate.

This is consistent with the confidence-uninformative finding: a refactor that breaks a global invariant and a refactor that does not look identical to the agent's self-assessment.

## Evidence

- Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610): breaking-change rates by task class (refactor 6.72%, chore 9.35%, feat 2.89%, fix 2.69%).
- Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166): agent refactoring share 24.9% vs. human 14.9%.

## Related Findings

- `agent-confidence-is-uninformative-for-defect-prediction.md` — confidence does not distinguish a safe refactor from a breaking one; the two signals compound.
- `self-classification-cannot-gate-the-human-boundary.md` — if the agent classifies its own refactor as low-risk, independent re-derivation from the diff is required; the task-class risk inversion is a reason to be especially skeptical of self-classification on maintenance-class changes.
