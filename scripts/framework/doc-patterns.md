# Known Documentation Bug Patterns

This file records documentation omission patterns discovered during development sessions.
It is read by `validate_docs.sh` to give the AI reviewers explicit pattern guidance —
filling the role that chat history would otherwise play.

**When to add an entry:** When a doc bug is found and fixed during a session, add the
pattern here so future validation runs actively look for recurrences. One entry per
pattern; keep descriptions concrete and reusable.

**Format:**
```
## PATTERN-NNN: [short name]
**Type:** mode-omission | pipeline-omission | stale | scope-narrowing | role-boundary
**Discovered:** YYYY-MM-DD
**Example of the bug:** [exact quote or paraphrase of the broken text]
**Why it's wrong:** [what the agent file actually says]
**Correct form:** [what the doc should say]
**Check:** [what to grep for, or what question to ask, to detect recurrences]
```

---

## PATTERN-001: ux-designer described as reactive-only

**Type:** mode-omission
**Discovered:** 2026-06-12
**Example of the bug:** "Not a step in the pipeline; invoked reactively on demand. When `ui-reviewer` or `a11y-reviewer` finds a design pack gap..."
**Why it's wrong:** `ux-designer` has two modes: (1) proactive — invoked after `pm-agent` at project start to audit the design pack against the full spec and write `docs/design/UX-DESIGN-READINESS.md`; (2) reactive — fills gaps during the build. Any description that only mentions the reactive mode is incomplete.
**Correct form:** Any description of when to invoke ux-designer must cover both modes. Short form: "invoked at project start (proactive audit) and reactively during the build (gap filling)."
**Check:** Search for "ux-designer" in doc files. Any sentence containing "reactive" or "on demand" or "when ui-reviewer" that does NOT also mention "project start" or "initial audit" is suspect.

---

## PATTERN-002: pm-agent described only as a during-build resource

**Type:** mode-omission
**Discovered:** 2026-06-12
**Example of the bug:** "Invoke whenever any agent needs a product/requirements question answered."
**Why it's wrong:** `pm-agent` also has a mandatory project-start role: reads all spec files, surfaces ambiguities, conducts human Q&A, and writes `docs/pm/CONFIRMED-REQUIREMENTS.md`. This is a blocking sequential step, not just a reactive resource.
**Correct form:** Descriptions of pm-agent should mention both: (1) mandatory first step at project start, and (2) reactive spec-question answering during the build.
**Check:** Any description of pm-agent that describes it only as "invoked when..." without mentioning "at project start" or "initial spec review" is suspect.

---
## PATTERN-003: stale loop-round count in technical-design

**Type:** stale
**Discovered:** 2026-06-14
**Example of the bug:** "Iteration with `architect` has a maximum of 3 rounds. After 3 rounds without approval, escalate to human..."
**Why it's wrong:** `technical-design.md` and `architect.md` both define the iteration cap as 5 rounds (CORE ships 5; a project may override in PROJECT). The docs had a stale "3 rounds" figure from an earlier draft.
**Correct form:** "maximum of 5 rounds. After 5 rounds without approval, escalate to human with the iteration count, what each revision changed, and the specific point the architect has not accepted."
**Check:** Search docs for "3 rounds" in context of technical-design or architect iteration. Any reference to a round cap other than 5 (or a configurable override) for these agents is wrong.

---

## PATTERN-004: agent count hardcoded in SETUP.md without reference to consumer_agents.txt

**Type:** stale
**Discovered:** 2026-06-14
**Example of the bug:** "All 26 agent files are present" / "`agents/` ← 26 agent definition files"
**Why it's wrong:** The consumer install copies agents from `consumer_agents.txt`, which defines the shipped set. As of v0.3.0 this is 24 agents. "26" predates the base-team additions. Hardcoding a count creates drift on every release.
**Correct form:** Reference `consumer_agents.txt` rather than hardcoding a number, or say "All consumer agent files are present (see `scripts/framework/consumer_agents.txt`)".
**Check:** Grep docs for any hardcoded agent count (e.g., "26 agent", "29 agent", "24 agent"). Any such count not accompanied by a reference to `consumer_agents.txt` is suspect.

---

## PATTERN-005: AGENTS.md "Quick reference" claims all files are copied including framework-dev validators

**Type:** stale
**Discovered:** 2026-06-14
**Example of the bug:** "All agent files are copied — including the framework agents. Any project using this pipeline will customize agents, and the framework agents validate those customizations."
**Why it's wrong:** The installer uses `consumer_agents.txt`. Framework-dev validators (`framework-validator`, `doc-validator`, `spec-compliance-validator`, `framework-setup-validator`) are explicitly NOT shipped to consumers — they are HOS-internal and belong to the `hos-dev-pack`. CLAUDE.md makes this explicit.
**Correct form:** "The install copies agents from `scripts/framework/consumer_agents.txt`. Framework-dev validators are not shipped to consumer projects."
**Check:** Any statement saying "all agent files are copied" or "including the framework agents" in a consumer-facing doc is wrong if framework-dev validators are part of "framework agents".

---

## PATTERN-006: unit-test and system-test escalation path described as going via technical-design for spec ambiguity

**Type:** role-boundary
**Discovered:** 2026-06-14
**Example of the bug:** "`technical-design` (untestable designs, **and spec ambiguities — via the design chain, not `pm-agent` directly**)"
**Why it's wrong:** `unit-test.md` and `system-test.md` both dispatch directly to `pm-agent` for spec ambiguity (not via technical-design). The agents' `dispatches:` field includes `pm-agent`. The docs overstated the routing restriction.
**Correct form:** "Untestable behavior → `technical-design` (behavior whose contract is ambiguous or unobservable); spec ambiguity (what the product should do) → `pm-agent` directly."
**Check:** Any doc that says unit-test or system-test spec questions route "via the design chain" or "not pm-agent directly" should be checked against the agent file's dispatches field and escalation section.

---
## PATTERN-007: ops-designer described as reactive-only or discretionary

**Type:** mode-omission
**Discovered:** 2026-06-15
**Example of the bug:** "These agents are optional — add them when your project has background jobs..." / Omission of ops-designer from start sequence in AGENTS.md.
**Why it's wrong:** `ops-designer` has a mandatory project-start role when configured for projects with ops complexity. It authors the telemetry spec that `ops-reviewer` enforces; it must not be treated as purely reactive or discretionary.
**Correct form:** "These agents are not needed for projects without ops complexity. If the project has background jobs, external integrations, async task queues, or multi-service architecture, ops-designer is required at project start and ops-reviewer is required for applicable changes."
**Check:** Search for "ops-designer" in docs. Ensure it is shown in the project-start sequence and described as mandatory when configured.

---
<!-- Add new patterns below this line -->
