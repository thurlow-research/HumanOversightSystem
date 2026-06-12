# Finding: Governance Rules Without Verification Mechanisms Are Unenforceable

**First observed:** 2026-06-11, session `2026-06-11-hos-bootstrap-pipeline-hardening.md`

---

## The Finding

An AI agent given a governance rule it cannot verify will either always apply the rule conservatively (blocking legitimate work) or defer to its own judgment about whether the rule has been satisfied (defeating the purpose of the rule). Both outcomes undermine the governance goal. Rules that require verification against an external state — particularly rules that require human action — must provide a concrete mechanism for the agent to check that the required action occurred.

The concrete instance: `risk-assessor.md` contained the rule:

> "You can never lower the risk tier without human concurrence."

This rule is sound in principle — it prevents an AI from deciding, on its own, that a HIGH-risk change should be reclassified as MEDIUM to avoid triggering the more expensive review chain. But the rule provided no mechanism for the agent to determine whether human concurrence had been granted. The agent had no tool, file input, or API call defined for this check.

In practice, this means:
- If the AI interprets the rule strictly: it can never lower any risk tier, regardless of context
- If the AI interprets it loosely: it makes its own judgment about what "human concurrence" means, which is exactly the failure mode the rule was designed to prevent

Neither interpretation serves the governance intent.

**Fix implemented:** A flag-file convention was introduced. Human concurrence is documented by writing `.claudetmp/oversight/human-tier-override.md` with the date, decision, and human's name. The risk-assessor reads this file before any downgrade. If the file doesn't exist, the rule is enforced as written. If it does, the human's explicit decision is on record.

---

## Why This Matters

**Rules without mechanisms are documentation, not enforcement.** A rule that says "require human approval" but doesn't define how to check for it is functionally the same as no rule — the AI will either ignore it or interpret it in whatever way is locally convenient. The rule creates an illusion of governance without the substance.

**This is not an AI-specific problem, but AI amplifies it.** Human governance processes also have unverifiable rules ("no deployment without manager approval"). In human processes, the rule is enforced by social norms, career consequences, and audit. In AI processes, none of these apply. The AI has no career to protect and no social norm internalized. The rule must be checkable by the agent itself through concrete mechanisms.

**The file-as-signal pattern.** The solution — a flag file written by a human and read by the agent — is generalizable. Any rule that requires human action can be implemented as: (1) the agent checks for a specific file, (2) the file can only be written by a human (or a system the human controls), (3) the file contains enough information to audit the decision later. This creates a paper trail that satisfies both enforcement and auditability requirements.

**Verification mechanisms are load-bearing.** The governance system's credibility depends on its rules being verifiable. A rule that an AI can claim to satisfy while actually not satisfying it (because there's no check) is exploitable — not through malice, but through the natural tendency of systems to find paths of least resistance.

---

## Evidence

From `research/sessions/2026-06-11-hos-bootstrap-pipeline-hardening.md`:

> `risk-assessor.md` said "you can only lower the risk tier with human concurrence" but provided no mechanism to check whether human concurrence had been granted. The validator would either always refuse to lower risk (too conservative) or defer to the AI's judgment about what "human concurrence" means (the anti-pattern we're trying to prevent). Fixed by introducing a flag-file convention.

From agy review `review-20260611T165546.md`:

> **[MEDIUM]** Unenforceable "human concurrence" requirement for lowering risk tiers in `risk-assessor.md`. [...] There is no tool or file input defined for the agent to check or verify if the human has actually granted concurrence, making it impossible for the agent to safely lower the tier under any automated condition.

---

## Generalizations

This finding generalizes to a design principle for AI governance rules:

**For every rule that involves human action or judgment:**
1. Define the artifact that proves the action occurred (a file, a commit, a flag)
2. Define where that artifact lives (a well-known path the agent knows to read)
3. Define the minimum content (enough to audit: date, decision, who authorized it)
4. Define the agent's behavior when the artifact is absent (default to the more conservative behavior)

Rules that cannot be expressed in this form may need to be redesigned or reconsidered.

---

## Examples from HOS

| Rule | Artifact | Path | Default behavior |
|---|---|---|---|
| Human concurrence to lower risk tier | `human-tier-override.md` | `.claudetmp/oversight/step{N}-human-tier-override.md` | Do not lower tier |
| Human authorization for CRITICAL step | `human-authorization.md` | `.claudetmp/oversight/step{N}-human-authorization.md` | Block PR from opening |
| Human decision on escalated dispute | Implicit in re-invoking the agent | (agent awaits human to resume session) | Pause, do not proceed |

---

## Implications for Research

1. **Enforceable rules require observable artifacts.** Governance rules in AI systems should be designed around the question "what can the agent observe that proves compliance?" rather than "what should the agent believe is true?"

2. **Auditability and enforceability are linked.** A rule enforced by a file that a human must write is also auditable: the file is in the git history. A rule enforced by AI judgment is neither auditable nor enforceable. The file-as-signal pattern satisfies both requirements simultaneously.

3. **This is a constraint on rule design, not just implementation.** The implication is not just "add more verification mechanisms" but "rules that cannot be verified by observable artifacts should not be included in the governance system." This constrains what kinds of governance are achievable in fully-automated AI pipelines.

---

## Related findings

- `self-governance-recursion.md` — context in which this finding was discovered
- `cross-vendor-review-finds-real-bugs.md` — this finding was surfaced by the agy review
