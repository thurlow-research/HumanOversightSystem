# Finding: Incremental AI-Assisted Development Requires a Working-State Invariant

**Role:** signal-generation (engineering) — a software-quality invariant, a benefit, not the oversight research subject

**Source:** Peer feedback from a practitioner conducting extensive AI-assisted development, 2026-06-12
**Incorporated:** `METHODOLOGY.md` §6, `templates/AGENTS.md` Working-State Invariant section

---

## The Finding

In incremental AI-assisted development — where a developer issues N sequential prompts to build a feature — the absence of a local verification step between prompts produces a systematic failure mode: accumulated, interlocked errors that are difficult to diagnose and expensive to unwind.

The practitioner described this as a "house of cards": each prompt produces a change that appears syntactically correct in isolation, but the stack of changes collectively builds on a broken foundation. By the time a CI gate catches a failure, the error may have been introduced three or four prompts back, and multiple subsequent changes depend on it. Attributing the root cause requires reverting recent work that appeared correct.

The working-state invariant is the fix: **after every incremental change, verify the codebase is in a working state before issuing the next prompt.** The verify step is: lint + type check + unit tests in scope. If the verify fails, fix it in the current response before the next prompt is issued.

---

## Why This Is Structurally Necessary

AI agents operate without persistent memory of prior changes beyond the current context window. An agent asked to "add X" on a tree where Y is already broken will produce code that looks correct — it adds X appropriately — but the resulting codebase has both X and the pre-existing breakage from Y.

This is different from how humans code. A human developer who breaks a build while working typically knows they broke it, because the build failure is in their immediate environment. An AI agent that produces code in response to a prompt has no persistent awareness of the prior state of the codebase unless the human explicitly provides it.

The consequence: without local verification after each prompt, the AI's model of the codebase drifts from the actual state of the codebase. By prompt N, the agent may be confidently producing code based on a mental model that is several prompts out of sync with reality.

---

## The Current Pipeline's Blind Spot

Prior to this finding, METHODOLOGY.md §6 described the pipeline as:

```
PROMPT → AUTHOR → CAPTURE → COMMIT → PR → CHEAP GATES (CI) → ...
```

This treats a single "PROMPT" as the atomic unit and places cheap gates (lint, types, tests) in CI — after the PR is opened. In practice, a feature involves N prompts before the commit. The CI gates run once on the accumulated diff; they do not run between prompts.

The fix is to recognize two distinct loops:
- **Inner development loop:** `(Prompt → Change → Verify locally)ⁿ` — must maintain working-state invariant
- **Outer merge pipeline:** `Commit → PR → CI → Review → Human gate` — CI gates are a safety net, not the primary error-catching mechanism

The CI cheap gates remain valuable as a safety net and as a diagnostic signal: a CI failure on a gate that the inner loop should have caught is evidence that the inner loop was skipped.

---

## Evidence and Source

This finding came from a peer practitioner who conducts extensive AI-assisted development (vibecoding). Their reported workflow:

> "I usually have the agent run lint after every incremental change, then I run the tests, and then I prompt for the next change. If you just prompt N times for incremental changes without reestablishing the working state of the codebase, the agents can easily build a house of cards which eventually leads to increasingly bogus changes that need to be undone. So there is necessarily a prompt-verify loop as part of the incremental dev process."

This is consistent with an independent observation from the CondoParkShare build sessions: when incremental coder changes were not locally verified before subsequent prompts, the error stack in later review rounds was harder to triage because multiple changes needed unwinding to reach the root cause.

---

## Implications for Research

1. **The unit of analysis matters.** Research on AI code generation quality often treats a single prompt-response pair as the unit. This finding argues the unit should be a session — a sequence of N prompts building toward a feature. The failure mode is not in any single response but in the accumulation.

2. **Working-state verification is a process control mechanism, not a testing strategy.** It does not replace CI or code review. Its function is to prevent error accumulation during development so that later review is tractable. It is the AI-assisted development analog of "compile after every change" discipline in traditional development.

3. **Agent tool access determines feasibility.** The working-state invariant requires the agent to run lint and tests autonomously after each change. This requires the agent to have shell/bash tool access in the development environment. Agents that can only read and write files but cannot execute commands cannot implement this invariant — the verification step falls back to the human.

4. **The invariant reveals a category of agent capability gap.** An agent that produces syntactically valid but semantically broken code and reports success is exhibiting a failure mode that only the verify step catches. Measuring the rate at which the verify step catches failures (vs. the rate it passes) is a proxy metric for agent code quality.

5. **"House of cards" as a distinct failure class.** Existing AI code generation literature focuses on single-response quality (correctness, security, style). The house-of-cards failure is a multi-response phenomenon. It requires process-level research methodology — tracking failure attribution across sequential prompts — rather than single-response evaluation.

---

## Related findings

- `cross-vendor-review-finds-real-bugs.md` — the outer pipeline's role in catching what the inner loop misses
- `chat-history-as-unreliable-artifact.md` — the agent's limited cross-prompt memory is the root cause of why the invariant is necessary
