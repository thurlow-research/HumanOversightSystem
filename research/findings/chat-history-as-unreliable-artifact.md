# Finding: Session Chat History Is an Unreliable Governance Artifact

**Role:** oversight-mechanism — provenance of the authorization artifact

**First observed:** 2026-06-12, session `2026-06-12-ux-designer-validation-suite.md`

---

## The Finding

In AI-assisted software development, significant design decisions are made in the course of a chat session. These decisions — which agents have what authority, how escalation chains are wired, what the correct behavior is for edge cases — are often well-reasoned in context but are lost when the session ends. The conversation history is not accessible to the AI in future sessions, not searchable by other team members, and not auditable.

More precisely: validators, static checkers, and review agents work within a closed set of committed files. They cannot query "what was decided in a prior session." Any decision that was made in chat but never committed to a tracked file is effectively non-existent to the governance system.

This was observed concretely in this project:

- The decision to give `ux-designer` both a proactive and reactive mode was made in session. It was correctly implemented in the agent file. But two documentation notes — written shortly after — described only the reactive mode.
- The documentation author (the AI in a later part of the same session) had "forgotten" the proactive decision and defaulted to describing only the behavior that was most recently salient.

This is not an AI-specific failure: it is the same failure that happens when a developer makes a design decision in a standup, correctly implements it, but the docs are written from memory hours later and omit a detail.

---

## Why This Matters

**Governance by conversation is ungovernable.** If the authoritative record of a design decision is "it was discussed in the chat session," then:
- It cannot be audited (the chat is not a structured artifact)
- It cannot be validated (validators work on files, not conversations)
- It cannot be referenced by other team members or future AI sessions
- It will be silently forgotten and potentially re-decided differently in a future session

**The volume problem.** AI-assisted development sessions produce far more decisions per unit time than human-only development. The rate of design decisions outpaces the human's ability to manually capture each one. This means the gap between "decisions made" and "decisions documented" is larger in AI-assisted contexts than in traditional development.

**False confidence from consistency.** A codebase can appear internally consistent (all validators pass, no contradictions between files) while being inconsistent with the actual intent — because the intent was only expressed in the chat and never committed.

---

## The Solution Implemented

Two persistent capture mechanisms were introduced:

1. **`decisions.md`** (in `scripts/framework/`): a structured record of architectural and design decisions made during sessions. Each entry has a verification criterion that `validate_spec_compliance.sh` checks against the implementation files. A decision recorded here is checkable; one not recorded is not.

   The discipline: before a session ends, any decision that changes how the framework behaves must have an entry in `decisions.md`. Decisions not recorded are invisible to future validation.

2. **`doc-patterns.md`** (in `scripts/framework/`): a structured record of documentation omission patterns discovered during sessions. Read by `validate_docs.sh` as explicit pattern guidance. When a class of doc bug is found and fixed, its pattern is recorded so future runs actively check for recurrence.

Both files serve the same function: converting ephemeral session knowledge into durable, checkable artifacts. They are the practical implementation of "prompts as artifacts" applied to design decisions rather than code generation.

---

## Evidence

From `research/sessions/2026-06-12-ux-designer-validation-suite.md` (Meta-observations):

> Several times during the session, a decision made earlier was not reflected in later files. The ux-designer two-mode decision was recorded in the agent file but not propagated to two documentation files. [...] The solution — `decisions.md` and `doc-patterns.md` — acknowledges that chat is ephemeral and that any decision worth preserving must be written to tracked files.

From `decisions.md` (DEC-001):

> **Decision:** ux-designer has two operating modes. [...]
> **Verification:** ux-designer.md must contain both "Initial design audit" and reactive invocation sections. docs/AGENTS.md pipeline diagram must show ux-designer in the START phase. Any description of ux-designer must mention both modes.

---

## Implications for Research

1. **AI-assisted development requires explicit decision-capture rituals.** Just as the "prompts as artifact" discipline requires capturing the prompt that produced code, a "decisions as artifact" discipline requires capturing design decisions before the session ends. Without this discipline, the governance record is incomplete.

2. **The "chat as documentation" antipattern.** Teams using AI pair-programming tools sometimes treat the chat history as documentation. This finding argues that is insufficient: the chat is not searchable by automated tools, not versioned alongside the code, and not accessible to future AI sessions. Decisions must be extracted and committed.

3. **Memory-augmented AI systems change the calculus.** This finding assumes AI sessions have no persistent memory (consistent with current Claude Code behavior). As AI systems gain persistent memory capabilities, this finding may need revision — but the underlying principle (governance artifacts must be in tracked files, not in any memory store controlled by the AI) remains valid for auditability reasons.

4. **Rate-of-decision as a risk multiplier.** The volume of design decisions in an AI-assisted session is higher than in a human-only session. This amplifies the risk from undocumented decisions. Risk scales with both the number of decisions and the per-decision probability of non-capture.

---

## Related findings

- `omission-class-documentation-bugs.md` — the concrete failure mode that non-captured decisions produce
- `self-governance-recursion.md` — the requirement that the governance system itself be subject to these same disciplines
