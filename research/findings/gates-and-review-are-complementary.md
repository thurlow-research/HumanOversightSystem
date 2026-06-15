# Finding: Deterministic Gates and Agent Review Catch Different Bug Classes — Neither Subsumes the Other

**Role:** oversight-mechanism — empirical justification for the methodology's two-layer (gates + agent review) design.

**First observed:** 2026-06-15, building HOS v0.3.0 *with* HOS (the #176 self-application / dogfood).

---

## The Finding

While building the v0.3.0 region-layering installer, the framework's own agent pipeline reviewed the new code: a borrowed `architect` produced a binding ADR, `technical-design` an implementation contract, `coder` wrote `regions.py` (parse/validate/compose/region_sha) and the pure `merge_region` decider, and `code-reviewer` reviewed both — **APPROVE** on `merge_region` after an exhaustive 432-combination verification, REQUEST-CHANGES-then-clean on `regions.py`. The agent review was genuinely strong: it caught a fenced-code-block **install-brick** (a marker shown in documentation would unparse the agent), a **vacuous round-trip test**, a CRLF-checkout **drift brick**, and even a *factual error in the architect's own mechanism*.

Then we ran HOS's **deterministic gate inner-loop** (lint / type / security / secret / portability + `run_validators`) on that *same, already-agent-approved* code. It immediately found **three real defects the agent review had missed**:

1. **mypy** — a latent crash: `seen_packs[r.name]` indexing a `dict[str, int]` with a `str | None` key.
2. **flake8-bugbear B042** — `ParseError.__init__` didn't forward its args to `super().__init__()`, making the exception **unsafe to `pickle`/`copy`**.
3. **F401** — unused imports.

None of these were caught by four rounds of capable agent review; all three are exactly the mechanical/type/hygiene class deterministic tools scan for reliably and a reasoning reviewer does not.

## Why This Matters

The two layers are **complementary, not redundant**, and the split is along a clean axis:

- **Agent review** catches *semantic / design / correctness-of-intent* defects — does the logic match the contract, is the test actually proving its claim, does the design contradict itself, would this case lose consumer data. (It found all of those here.)
- **Deterministic gates** catch the *mechanical / type-soundness / format / hygiene* class — a `None` that can't be indexed, an exception that won't round-trip, an unused import, a line over the limit. A reasoning reviewer's attention does **not** reliably enumerate these; a tool does, exhaustively, every time.

Neither subsumes the other. A pipeline with only agent review ships latent type crashes; a pipeline with only gates ships logically-wrong-but-clean code. The methodology requires **both**, and this is the first time we have direct evidence of each catching what the other missed *on the same change*.

## The dogfood angle

This is the self-application test (#176) producing real signal: HOS's gates, run on HOS's *own framework code* (not consumer app code), both **validated the gates** (they work outside the Django-app context they were piloted in) and **found genuine bugs**. The gates are not theater.

## Process correction it forced

We had run the agent pipeline but **skipped the gate inner-loop before review** — treating borrowed-coder output as review-ready when it had not cleared lint/type. The fix (now standard for the v0.3.0 build): **every coder pass runs the gate inner-loop and clears it *before* code-review begins.** This mirrors the contract's own ordering (gates → validators → risk-assessor → review); we had inverted it under the momentum of agent-only iteration. The pull toward "the agents reviewed it, so it's good" is the same default-absorption failure as `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md`, one layer down: the *deterministic* gate is the easy step to skip when capable agents are already in the loop.

## Related findings

- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — the "a capable agent makes the cheaper independent check feel redundant" default, here applied to gates-vs-review.
- `reviewer-agents-file-confident-non-reproducing-reports.md` and `tooling-drift-in-validation-pipelines.md` — the other "a confident review is not sufficient" results.
- `hos-ports-human-best-practices.md` — gates + review = CI-lint + human-PR-review, both standard in human teams precisely because they catch different things.
