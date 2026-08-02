# Finding: Governance That Lives in Prompt Text Produces Unattributable Decisions

**Role:** oversight-mechanism — behaviour specified in prompts is real and consequential but invisible to code search, absent from the dependency graph, and unattributable in the audit trail

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

When an agent's decision rules are written in prompt text rather than in code, the resulting decisions are **effective but unattributable**. The behaviour happens; its provenance does not exist anywhere a reader can find it. Standard investigative moves — grep the codebase, follow the call graph, read the audit log — all fail, because none of them index prose.

### The instance

An autonomous worker had been assigning milestones to newly-filed issues. The prior session's handoff recorded this verbatim as:

> Something auto-assigns milestones to newly-created issues — #1183 → `v0.5.1`, #1184 → `v0.7.0`, neither set by the filer. **Mechanism unknown.**

Tracing it consumed a substantial part of the following session. The mechanism was **Step 0 of `bootstrap/worker-cron-prompt.md`** — a block of markdown piped into a headless agent by the cron launcher, instructing it to triage every milestone-less issue on each cycle.

Three properties made it hard to find:

1. **Invisible to code search.** Searching for milestone assignment logic returns nothing, because there is no logic — there is an instruction.
2. **Absent from the dependency graph.** No import, no call site. The only link is `bin/hos-cron` reading `bootstrap/${ROLE}-cron-prompt.md` by constructed filename.
3. **Unattributable in the audit trail.** The issue timeline shows the bot made the change. It does not show *which rule fired*, or *why*. The audit log records that a cycle ran, not what it decided or on what basis.

A fourth property compounded it: the prompt **duplicated** a taxonomy that lived canonically in `docs/planning/README.md`, twice. All copies had drifted out of step with the current release plan — and critically, they **agreed with each other**, so de-duplication alone would have changed no behaviour. The duplication was a maintenance defect; the staleness was the behavioural one. Conflating them would have produced a fix that changed nothing.

## Why this matters beyond findability

The audit trail is the oversight system's primary evidence. When the deciding rule lives in prompt text and the agent is not required to state its reasoning, the trail records *that a decision occurred* but not *what governed it*. For a framework whose purpose is to make AI decision-making reviewable, this is a hole in the substrate rather than an inconvenience.

The cost is concrete and recurring: an operator seeing an unexpected milestone cannot determine whether the agent applied the correct rule to a misjudged issue, applied a stale rule correctly, or ignored the rule. Those demand different responses, and the trail does not distinguish them.

Note that the governance itself was **not wrong to live in a prompt**. Prompt-resident rules are how these systems are steered, and moving all of them into code would trade flexibility for a rigidity that defeats the purpose. The defect is the missing attribution, not the location.

## Implication for research

Two requirements follow, and they are separable:

**Agents must record the rule they applied, at decision time.** Not the decision alone — the criterion matched, and where it came from. This is the general fix and it works regardless of where the rule lives. It also does not depend on anyone maintaining a registry.

**Prompt-resident rules should cite rather than restate canonical documentation.** Duplication between prompt and doc has no mechanism keeping the copies aligned, and nothing detects divergence. But note this is the *weaker* remedy: in this instance every copy agreed, so citation-instead-of-duplication would have prevented nothing. It reduces future drift; it does not address attribution.

Connects to [`unenforceable-rules-need-verification-mechanisms`](unenforceable-rules-need-verification-mechanisms.md): both concern governance whose satisfaction cannot be checked from outside the agent. There, the agent could not verify a rule. Here, an observer cannot verify which rule the agent used.

## What changed

- **#1194** — the worker posts a triage rationale comment recording the milestone assigned, the criterion matched, its source, the priority, and the routing label. Constrained to avoid quoting untrusted issue text back, and required to be idempotent.
- **#1193** — the stale taxonomy corrected at its canonical source, filed separately from the de-duplication precisely because the two are different defects.
