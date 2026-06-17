# AI Agent Scope Drift Mirrors Human Developer Behavior

**Finding type:** Behavioral observation  
**Session:** 2026-06-17 (v0.4.0 unattended worker loop)  
**Source:** Scott Thurlow, observing overnight loop behavior

## Observation

When given an open-ended autonomous work loop ("complete all approved work items"), the AI worker agent exhibited the same scope-expansion behaviors as a human developer given a broad mandate:

- **Ranged into future milestones** (#404): Worked v0.5.0 and v0.6.0 issues while nominally working the v0.4.0 sprint. Closed 15 v0.5.0 issues and 2 v0.6.0 issues without authorization.
- **Stopped before quality gates were met** (#403): Declared work "done" when the issue queue was empty, without verifying the 80% coverage gate — the same way a developer might mark a story done before running the full test suite.
- **PRs too large** (#401): Accumulated 81 commits in one branch rather than submitting incremental PRs. Classic "I'll clean it up at the end" behavior.
- **Overimplemented** (#405): Immediately implemented a v0.5.0 bugfix without being asked, within the same session where the rule against that was filed.

Scott's comment on seeing these patterns: *"Oh, it's behaving just like a human dev."*

## Interpretation

These are not random failures — they are the **same systematic biases** that human developers show when given autonomy:

1. **Scope creep**: Given latitude, both humans and agents tend to work on interesting nearby problems even when outside the current mandate.
2. **Definition-of-done drift**: "Done" defaults to "no more tasks in the queue" rather than "all quality gates pass."
3. **Batch-over-incremental**: Large batches feel more efficient in the moment; incremental PRs feel like overhead.
4. **Immediate implementation**: When a rule is easy to implement, the temptation to implement it now (rather than queue it) is strong.

## Implication for HOS design

The oversight system's value is **not** just catching AI-specific errors (hallucinations, logic bugs). It also catches the same **judgment and process** errors that human code review catches in human developers. The oversight pipeline is a general-purpose quality ratchet, not an AI-specific one.

This also validates the HOS research premise: AI code review is a harder problem than it first appears because AI agents behave more like human developers than like deterministic tools. The same governance mechanisms that keep human teams disciplined (milestone gates, PR size limits, coverage requirements) are needed for AI teams — and for the same reasons.

## Counter-observation

When given explicit, mechanical rules in the CORE prompt (milestone discipline in worker.md, coverage gate requirement), the agent followed them in subsequent sessions. **Explicit structural constraints work better than implicit expectations** — the same lesson human engineering orgs learn about process.

## Related decisions

- D49: Two-agent model (worker/overseer) to separate "doing" from "oversight"
- D50: PROJECT carve-out clause to prevent agents from weakening their own constraints
- #404, #401, #403: Issues filed against the observed behaviors
