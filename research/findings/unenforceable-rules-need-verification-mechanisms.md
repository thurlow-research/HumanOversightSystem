# Finding: Governance Rules Without Verification Mechanisms Are Unenforceable

**Role:** oversight-mechanism — a rule without a verification mechanism is advisory

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

## Second instance: AI disclosure requirement (2026-06-12)

A second clear instance of this pattern was observed when CondoParkShare's Claude submitted PRs without the required AI disclosure statement (`[AI: agent-name]` title prefix + `## 🤖 AI-Submitted Pull Request` block). The rule existed in `oversight-orchestrator.md` but was:
- Invisible to other PR-creation paths (Claude Code sessions, coder agent, direct `gh pr create` calls)
- Not mechanically checked — no gate, no template field, no artifact to verify

The agent did not maliciously skip the disclosure; it simply did not encounter the rule at the moment it was opening a PR. This is the same failure mode as the risk-tier rule: the rule existed in prose but had no observable check.

**Fix:** Three-layer enforcement — the requirement was added to the PR template (visible to any agent using `gh pr create`), to `docs/AGENTS.md` as a universal rule, and as a non-negotiable constraint in `oversight-orchestrator.md`. The template is the mechanism: it surfaces the requirement at the point of action.

**Updated examples table:**

| Rule | Artifact | Path | Default behavior |
|---|---|---|---|
| Human concurrence to lower risk tier | `human-tier-override.md` | `.claudetmp/oversight/step{N}-human-tier-override.md` | Do not lower tier |
| Human authorization for CRITICAL step | `human-authorization.md` | `.claudetmp/oversight/step{N}-human-authorization.md` | Block PR from opening |
| AI disclosure on PR submission | PR template + docs/AGENTS.md universal rule | `.github/PULL_REQUEST_TEMPLATE.md` | Rule visible at PR creation point |

The third row is a weaker enforcement mechanism than the first two — the template can be bypassed if an agent constructs a PR body without using it. The stronger form would be a CI check that verifies the disclosure is present. This is tracked as an open improvement.

---

## Third instance — the recursion: the corpus's own principles are themselves unenforced rules (2026-06-27)

The sharpest instance is self-referential. A sequential full-codebase governance audit ahead of the v0.5.0 cut found **26 adversarially-verified bugs**, of which **21 were fail-open or governance-bypass** — and nearly every one violated a principle *already written down in this very corpus*:

- `a-guard-that-doesnt-halt-is-not-a-guard.md` — a milestone red-team checkpoint that exits 0 with zero reviewers (#911); a halt kill-switch that defaults to "not halted" on a transient API error (#912).
- `a-gate-must-not-confuse-unreadable-with-unsafe.md` — validators scoring an unparseable/tool-absent input as a clean 0.0 instead of excluding it (#917).
- `an-override-must-expire-or-it-becomes-the-policy.md` — a stamp gate bypassed by a hardcoded disabled-until date (folded into #552).
- `self-classification-cannot-gate-the-human-boundary.md` — a `--risk` override that lowers a CRITICAL floor to skip the whole panel (#910).

The lesson recurses one level up from where this finding started. The original instance was an **agent rule** in prose with no artifact the agent could check. This is the identical failure at the **codebase** level: a documented *finding* — a principle the team has explicitly learned and written — is, with no executable check asserting it, exactly as advisory as a prose rule with no flag file. Knowing the principle did not prevent 21 fresh violations from shipping; the principles were load-bearing in the prose and absent from the build. The gap was never knowledge — it was enforcement.

**The fix shape generalizes accordingly:** the highest-value principles in this corpus need to become mechanical assertions, not just findings — a lint that rejects `|| echo "0"` / `|| true` defaulting on a governance gate's status read, a check that every validator returns `error=` (not a clean score) when its tool is absent or its input unparseable, a test that every `--risk` / override path can only *raise* a deterministic floor. **A principle without a verification mechanism is unenforceable whether its subject is an *agent* or the *oversight code itself*.** (Audit filed as #703, #910–#925; reinforces O4.)

---

## Related findings

- `self-governance-recursion.md` — context in which this finding was discovered
- `cross-vendor-review-finds-real-bugs.md` — this finding was surfaced by the agy review
