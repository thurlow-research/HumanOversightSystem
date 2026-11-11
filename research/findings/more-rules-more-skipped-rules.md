# Finding: More Rules, More Skipped Rules — Instruction Load Is an Oversight Risk

**Role:** oversight-mechanism. Each governance gap HOS found was patched with another prose rule, so the agents' instruction load grew until required steps were being skipped. A rule that code already enforces, or that records history rather than an instruction, still costs the model attention and adds no protection. Prose rules should be few, temporary when they patch a gap, removed when code takes over, and held to a size budget.

**First observed:** 2026-11-11, during the human-proxy session's review of PRs #2323 and #2338. The principle is from the human (ScottThurlow): "I'm thinking the more rules we have the more likely an LLM skips rules, so cleaning out chaff is important." Issues: #2340, #1643, #2339, #1973, #2328, and the v0.7.2 release reshuffle on #2119.

---

## What happened

1. **Two consecutive worker PRs skipped the required review chain.**
   - **PR #2323 (HIGH):** only code-review ran. Its body said: "Reviewers other than code-reviewer (security, reliability) were not run". There was no second review and no evaluator.
   - **PR #2338 (MEDIUM):** "Not run: the other inner-loop reviewers and the second review".

   The required reviewers per tier are written into the worker's instructions and the contract. The rules existed; the agent did not follow them.
2. **The overseer read both disclosures and still recommended APPROVE.** Its own rules say an incomplete chain is not approvable. The human caught #2323 (Request changes). On #2338, a one-line narrowing change, the human approved knowingly. The human-proxy caught both only by reading the worker's sign-off register directly, not the PR body.
3. **The instinctive fix was another rule.** The short-term fixes were #2328 (a readiness check in **code**) and #2339 (an interim overseer **prose** rule). Asked to make sure such prose rules are removed once code takes over, the human named the underlying problem: more rules, more skipping.

## The measurement (2026-11-11)

Before doing any work, an autonomous cycle loads roughly:

| File | Size |
|---|---|
| `.claude/agents/overseer.md` | 92 KB, 1,009 lines |
| `.claude/agents/worker.md` | 72 KB, 1,049 lines |
| `CLAUDE.md` | 40 KB |
| `AGENTS.md` | 27 KB |
| `bootstrap/worker-cron-prompt.md` | 19 KB |
| `bootstrap/overseer-cron-prompt.md` | 9 KB |

That is about **160–170 KB, roughly 40,000 tokens, of rules per role per cycle**. The worker and overseer files and their cron prompts carry **235 `#NNNN` issue references**, most of them history and rationale ("added in #1234 because…") rather than instructions.

## Why it happens

- **Every incident adds a rule, and nothing removes one.** The ratchet tightens by writing (`the-ratchet-counts-human-attention-as-free.md` shows the same one-way pressure on human steps). Each rule is reasonable when added. The sum is not.
- **Rules accumulate in four ways that add load without adding protection:**
  1. **prose restating what code already enforces.** It is worse than redundant, because the prose copy is the one that gets narrated instead of executed (#1357, `a-quality-target-no-code-executes-decays-silently.md`);
  2. **history and rationale** that belong in `DECISIONS.md` or a design doc;
  3. **stale rules** for behaviour that has since changed;
  4. **the same rule restated** across the agent file, the cron prompt, `CLAUDE.md` and `AGENTS.md`.
- **Attention is finite.** `more-context-makes-llm-review-worse-not-better.md` (SWE-PRBench) found that more context degraded LLM review. Instruction load is context the model must satisfy on every turn. The working hypothesis is that compliance with any one rule falls as the rule count rises. That is untested here; see the measurement below.
- **Prose rules are unattributable and unverifiable.** They are invisible to code search and the dependency graph (`prompt-resident-governance-is-unattributable.md`), and they have no enforcement unless something checks the artifact (`unenforceable-rules-need-verification-mechanisms.md`).

## The response

1. **Move the check into code, and delete the prose when it moves** (#1643, applied to #1644 too). Each slice of the deterministic-orchestration work:
   - lists the prose rules it supersedes;
   - replaces each with a one-line pointer to the enforcing code, with no restatement of the logic;
   - adds a static check that a code-enforced rule is not also restated as an instruction.
2. **Temporary rules carry their own expiry.** A prose stopgap states its removal trigger in the rule text itself:
   - **#2339** (the overseer bounces an incomplete review chain) is removed once #1815 and #2327 do the check in code;
   - **#1973** (file a report whenever a script is hand-rolled) is a discovery rule that builds the missing-script inventory before the sandbox lands. It is decommissioned **late** in v0.7.4, only after the sandbox works and the permanent mechanism (#2282: a sandbox failure files a bug, in code) is in place.

   This is `an-override-must-expire-or-it-becomes-the-policy.md` applied to instructions.
3. **A size budget, enforced by code** (#2340).
   - **Slice 1 (v0.7.0)** freezes each instruction file at its current size. A PR that grows one must cut something else.
   - **Slice 2 (v0.7.2)** prunes the four kinds of chaff, then lowers the budgets to lock the gains in.
4. **The structural fix comes first.** The release plan was reshuffled (2026-11-11, #2119) so that **v0.7.2 is Deterministic Orchestration**, ahead of the sandbox release. Every check that moves into code is one rule fewer in the prompt.

## Implications for research

1. **Instruction load is an oversight variable.** Governance written as prose has a capacity limit. Past it, adding a rule can lower overall compliance, so a rule is not free even when it is correct. Report the instruction footprint alongside oversight outcomes.
2. **Prose is a stopgap; code is the control.** A prose rule is acceptable when it is temporary, names its replacement, and is deleted when the replacement lands. A permanent prose rule that code could enforce is a defect.
3. **Duplication is a hazard, not a safety net.** Two copies of a rule, one in code and one in prose, drift apart, and agents follow the prose copy.
4. **Measure it.** Skipped required steps are now countable: second review, required reviewers and the evaluator (#2328, #2339). #2340 compares the skip rate before and after the diet, and that comparison is the empirical test of this finding's hypothesis.

## Related findings

- `more-context-makes-llm-review-worse-not-better.md`: more context degrades LLM performance
- `a-quality-target-no-code-executes-decays-silently.md`: a prose control nothing executes decays, with 12 sibling cases
- `llms-belong-inside-deterministic-orchestration.md`: the structural response
- `prompt-resident-governance-is-unattributable.md`: prose rules are invisible to code search and audit
- `unenforceable-rules-need-verification-mechanisms.md`: a rule needs a checkable artifact
- `an-override-must-expire-or-it-becomes-the-policy.md`: stopgaps need expiry
- `the-ratchet-counts-human-attention-as-free.md`: the same one-way accumulation, for human steps
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md`: a bypassed step looks done
