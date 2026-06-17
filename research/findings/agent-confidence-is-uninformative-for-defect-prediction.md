# Finding: Agent Self-Reported Confidence Is Uninformative for Defect Prediction

**Role:** oversight-mechanism — preventing confidence-based routing shortcuts

**First observed:** 2026-06-16, SLR full-text read (Ferdous et al. 2026)

---

## The Finding

Agent-reported confidence does not predict defect rates in agent-authored PRs. Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610) analyzed a large corpus of agent PRs and found:

- **99.9% of agent PRs self-report confidence levels of 8–10** (on a 10-point scale). The distribution is saturated at the ceiling.
- **Defect rates are flat across confidence levels 8–10:** 3.16–3.96% breaking-change rate, with no statistically meaningful trend.

Confidence is not merely a weak predictor — it is **saturated and therefore uninformative as a routing signal.** A signal that takes the same value in 99.9% of cases carries no discriminative information in that population. Using it as an input to routing decisions imports noise at best and a systematically false signal at worst.

## Why This Matters for Scalable Oversight

Risk-stratified oversight works by routing human attention to the cases where it is most needed. Any routing signal that correlates with actual risk is valuable; any signal that is independent of risk is harmless noise; but a signal that *appears* to correlate with risk while being empirically independent of it is dangerous — it creates a false sense of discrimination and can actively lower scrutiny for high-risk cases that happened to declare high confidence.

The practical failure mode: an oversight pipeline that uses high-declared-confidence as a reason to apply lighter review will, empirically, apply lighter review uniformly (since almost everything is rated 8–10) — not lighter review on the genuinely lower-risk cases. The routing is noise, the appearance of discrimination is not.

## The Asymmetry Rule

The empirical finding motivates a **one-directional use rule** for confidence:

- **Low confidence may raise scrutiny.** An agent rating itself 5–7 is sufficiently unusual to be a meaningful signal: it is operating outside the saturated ceiling range and the deviation from the norm warrants attention.
- **High confidence may never lower scrutiny.** Given that 99.9% of PRs are 8–10 and defect rates do not decrease in that range, a high confidence rating provides no evidence that a lower scrutiny tier is appropriate.

Stated equivalently: confidence is a **calibration prior for the human reader** ("this agent reports uncertainty") but not an input to automated routing. A pipeline that uses it for routing in either direction (high→lighter, low→heavier) is using confidence as if it were informative in the downward direction, which the empirical record does not support.

## Implications for Automated Routing

1. **No confidence-based tier downgrade.** A change declared MEDIUM by deterministic signals may not be routed to LOW treatment because the authoring agent declared confidence 9. The tier floor is set by deterministic signals; confidence cannot lower it.
2. **Confidence-floor escalation is permitted as a conservative enhancement.** If a system chooses to treat an unusually low confidence rating as a trigger for escalation, this is consistent with the asymmetry rule (raising scrutiny, never lowering it). But the payoff is limited by the rarity of low-confidence ratings.
3. **Do not report confidence as a quality signal to downstream consumers.** Displaying agent confidence to a human reviewer in a way that implies it carries predictive weight is misleading — it anchors the human on a signal that is empirically uninformative about defect probability.

## Evidence

- Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610): confidence saturation (99.9% at 8–10) and flat defect rates (3.16–3.96%) across the saturated range.

## Related Findings

- `reviewer-agents-file-confident-non-reproducing-reports.md` — the reviewer-side analog: confident, well-evidenced AI reports do not reliably reproduce. Confidence is uninformative on both the authoring side (this finding) and the reviewing side.
