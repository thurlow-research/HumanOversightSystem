# Cleanroom SQC and Lean Principles Applied to Consumer Projects via HOS

**Sources:**
- Cobb, R.H. & Mills, H.D. (1990). Engineering software under statistical quality control. *IEEE Software*, 7(6), 44-54.
- Poppendieck, M. & Cusumano, M.A. (2012). Lean software development: A tutorial. *IEEE Software*, 29(5), 26-32.

**Session:** 2026-06-18 (v0.5.0 planning)

## Core insight: HOS should deliver these capabilities to consumers, not just apply them to itself

HOS currently provides deterministic validators, reviewer agents, and a human gate. These papers suggest four additional capabilities that should flow through HOS to any consumer project.

## From Cobb & Mills (1990) — Cleanroom/SQC

**Usage-profile-weighted testing:** Test cases drawn from actual usage distribution are 21x more cost-effective than coverage testing (Adams study). The rarest failures represent 34% of fixes but eliminate only 2.9% of user-observed failures.

**MTTF certification with B-factor:** B = MTTF_{n+1}/MTTF_n; if B < 1, quality is regressing. Cleanroom projects achieved 2 orders of magnitude improvement in reliability (e.g., 560-year MTTF on 4th increment of one project).

**Separation of development and certification:** HOS already implements specification (pm-agent), development (coder), and certification (reviewers + overseer). The gap: certification currently runs the coder's own tests, not independent usage-based tests.

## From Poppendieck & Cusumano (2012) — Lean

Seven lean principles applied to HOS consumers:
1. **Optimize the whole** — measure end-to-end cycle time, not just per-gate metrics
2. **Eliminate waste** — audit log captures timestamps; lean waste report surfaces where cycle time goes
3. **Build quality in** — verification by logical argument scales; the triage agents prove scope before running validators
4. **Decide at the last responsible moment** — domain-aware diff partitioning (#496)
5. **Deliver fast** — WIP limits (one PR at a time) are a lean pull-system
6. **Engage everyone** — human approval gate is the value-delivery confirmation, not overhead
7. **Keep getting better** — B-factor/MTTF ratchet is the quantitative kaizen implementation

## Issues filed
- #514: MTTF/B-factor certification gate (v0.5.0, Governance)
- #515: Usage-profile-weighted test requirements (v0.5.0, Governance)
- #516: Lean waste report from audit log (v0.5.0, Observability)
- #517: Quality ratchet — monotonically improving defect density (v0.5.0, Governance)
- #518: Configurable WIP limits for consumer pipeline (v0.6.0, design needed)

## Related HOS findings
- `three-tier-review-cost-model.md`
- `corroboration-ranked-review-reduces-noise-without-losing-coverage.md`
- `nondeterministic-review-gate-converges-on-zero-new.md`
