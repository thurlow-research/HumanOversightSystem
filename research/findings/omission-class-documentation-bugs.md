# Finding: Omission-Class Documentation Bugs Are Structurally Invisible to Contradiction Checkers

**Role:** both — a doc-quality signal (doc-validator) feeding the oversight gate

**First observed:** 2026-06-12, session `2026-06-12-ux-designer-validation-suite.md`

---

## The Finding

A distinct class of documentation bug exists that is not caught by consistency checkers: the **omission**. A document describes an agent or system component correctly as far as it goes, but silently omits a mode, role, or behavior that the authoritative source defines. The document is not wrong — it is incomplete in a way that creates a misleading picture.

The canonical example from this project:

- `ux-designer.md` defines two operating modes: (1) a mandatory proactive project-start audit that produces `docs/design/UX-DESIGN-READINESS.md`, and (2) a reactive gap-filling mode invoked during the build
- Two notes in `docs/OVERSIGHT-RUNBOOK.md` described only the reactive mode: *"Not a step in the pipeline; invoked reactively on demand"*
- These notes were not wrong about the reactive mode — they were silent about the proactive mode

Existing validators (which check for contradictions: "A says X, B says not-X") would not flag this. The contradiction checkers were looking for disagreements; the omission contains no disagreement. Both statements are true; only one is complete.

---

## Why This Matters

**Omissions are operationally dangerous.** If a developer reads only the runbook note, they would never invoke `ux-designer` at project start. The proactive audit would be skipped, the design pack would have gaps, and those gaps would surface as repeated reactive invocations during the build — each one potentially blocking work. The error would not be traceable to the missing documentation.

**Contradiction checkers have a structural blind spot.** The standard approach to documentation validation is to check for inconsistencies between documents. This assumes all important information is present somewhere and the task is to ensure the copies agree. Omission-class bugs violate this assumption: the information is present in the authoritative source (the agent file) but absent in the documentation.

**The omission compounds over time.** Each new document that describes the same component and copies from the incomplete source perpetuates the gap. Without a mechanism that compares documentation against the authoritative source rather than against other documentation, omissions accumulate.

**The pattern recurs.** The same class of bug was found for `pm-agent` — described in some places only as a reactive question-answering resource, when it also has a mandatory project-start role. The recurrence suggests this is a structural property of how documentation is written (copying from prior incomplete descriptions) rather than a one-off oversight.

---

## The Solution Implemented

Two mechanisms were built in response:

1. **`doc-validator` agent + `validate_docs.sh`** (Phase 3 of the framework validation suite): compares each document's description of an agent against that agent's own definition file. Checks for mode omissions, pipeline position omissions, and stale claims. The agent file is treated as the authoritative source; documentation is checked against it, not against other documentation.

2. **`doc-patterns.md`**: a structured record of documentation omission patterns discovered during sessions. Read by `validate_docs.sh` to give AI reviewers explicit pattern guidance, so the same class of omission is actively checked in future runs. The ux-designer pattern was recorded as PATTERN-001.

---

## Evidence

From `research/sessions/2026-06-12-ux-designer-validation-suite.md`:

> There's a class of documentation bug that isn't a contradiction — the reactive description was correct as far as it went — but an omission. An agent file says X and Y; documentation says only X. This doesn't trigger the kinds of consistency checks that look for contradictions.

From `doc-patterns.md` (PATTERN-001):

> **Example of the bug:** "Not a step in the pipeline; invoked reactively on demand. When ui-reviewer or a11y-reviewer finds a design pack gap..."
> **Why it's wrong:** ux-designer has two modes: (1) proactive — invoked after pm-agent at project start [...]; (2) reactive [...]. Any description that only mentions the reactive mode is incomplete.
> **Check:** Search for "ux-designer" in doc files. Any sentence containing "reactive" or "on demand" that does NOT also mention "project start" or "initial audit" is suspect.

---

## Implications for Research

1. **Documentation validation is not the same as documentation consistency checking.** Existing tools for documentation quality (linters, link checkers, consistency validators) share the same blind spot: they check the documentation against itself, not against the system being documented. An omission-aware validator requires treating source definitions as ground truth.

2. **Multi-mode components are highest risk.** Components with both a mandatory sequential role and an on-demand role are most likely to be described incompletely — the reactive mode is visible in normal operation; the proactive mode only matters at initialization and is easy to forget when writing descriptions from memory.

3. **Pattern capture is necessary for sustained validity.** Without a persistent record of discovered omission patterns, the same class of bug will recur in every new session because the AI reviewer has no memory of prior sessions. `doc-patterns.md` is the implementation; the principle generalizes to any AI-assisted maintenance process.

---

## Related findings

- `chat-history-as-unreliable-artifact.md` — why patterns must be written to files, not held in session context
- `self-governance-recursion.md` — the broader pattern that a system must be applied to itself
