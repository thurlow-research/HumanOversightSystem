# Finding: An Oversight Pipeline Tuned for Code-Correctness Has a Structural Blind Spot for Documentation/Discoverability — and It's Invisible Precisely Because Every Code Lane Passes

**Role:** oversight-mechanism — a completeness gap in the review-lane set: the pipeline can certify software as correct, secure, and installable while it remains *undiscoverable*.

**First observed:** 2026-06-15, preparing the v0.3.0 cut. The pack feature (`--pack`, the layered base team, 12 django-packs) had cleared: deterministic gates (lint/type/secret/security), code-review (APPROVE), security-review (APPROVE), 153 tests, and a **5-scenario end-to-end real-install verification** — and was documented **nowhere user-facing** (0 mentions across `CLAUDE.md`, `README`, `SETUP`, `CUSTOMIZATION`, `QUICKSTART`, `AGENTS.md`, `METHODOLOGY`). A consumer could install it and have no docs telling them the flag exists.

---

## The Finding

The review pipeline has lanes for correctness, security, privacy, reliability, ops, UI, a11y, infra — every dimension of *the code being right*. It has **no lane for "is this documented / discoverable by the human who has to use it."** So a change can pass the *entire* pipeline — every reviewer green, end-to-end behavior proven — and ship with zero user-facing documentation of its headline feature.

Critically, **the gap is invisible from inside the pipeline**, for a specific structural reason: every lane that *does* exist reports PASS. There is no red signal. The absence of a doc-lane doesn't show up as a failure; it shows up as *nothing at all*. An oversight system that watches N dimensions is, by construction, blind to dimension N+1 — and blind to its own blindness, because the dimensions it watches all look clean.

It took a **human asking a use-oriented question** — "is this installable by CPS yet?" and then "make sure all documentation is up to date" — to surface it. The agent's notion of "verified/done" was *code-complete and behavior-proven*; the human's was *can a person actually adopt and use this*. The two diverged silently, and only the human's framing exposed the divergence.

## Why This Matters

- **"All reviewers passed" ≠ "ready to ship."** The pipeline certifies a *subset* of ship-readiness (correctness) and is silent on the rest (discoverability, docs, migration guidance, changelog). Treating green-across-existing-lanes as ship-readiness is a category error — the same shape as the D41 "looks reviewed, wasn't" family, one level up: here it's "looks *done*, wasn't."
- **Doc-rot is the default, not the exception.** This release churned heavily (mechanism + 12 packs + install changes); the docs silently fell behind because *nothing was watching them*. Without an explicit lane, documentation currency is left to chance + human catch — exactly the kind of thing oversight is supposed to systematize.
- **A framework whose thesis is "scale human oversight" must not let the human-facing layer rot unwatched.** Oversight that ships correct-but-undiscoverable software has optimized the machine-facing half and abandoned the human-facing half.

## The structural fix (filed as #244)

The missing lane is a **doc-currency reviewer** in the base team — checking two classes:
- **omission** — a shipped public surface (flag, command, endpoint, config key) documented nowhere (the gap that bit here);
- **drift** — a doc describing behavior the code no longer has (the D41 / #218 family).

Note the existing `doc-validator` does *not* close this: it is framework-dev-only and **agent-fidelity-scoped** ("do the docs describe the agents accurately") — it would not flag an *entirely-undocumented feature*, and doesn't touch a consumer's *application* docs. The new lane generalizes the omission check to *any* public surface and to consumer docs. Part of it can be a **deterministic gate** (every `--flag` in argparse appears in a doc; every public endpoint has a doc entry) + an **agent** for the semantic drift/completeness judgment — the gates+review split.

## The deeper lesson (for designing oversight lane-sets)

When defining the review dimensions for *any* oversight system, periodically run the **"what's missing" meta-question**: not "did each lane pass?" but "**is there a dimension of done that no lane watches?**" The lanes you have will always look clean; the risk is in the lane you don't have. A standing "completeness critic" — human or agent — whose only job is to ask "what dimension of shippable is unwatched here?" is the antidote to blindness-about-blindness.

## Related findings

- `gates-and-review-are-complementary.md` — the lane-set is the product; a missing lane is a silent hole, not a failing test.
- `design-review-catches-failclosed-invariants.md` and `refactor-to-reusable-is-a-quality-audit.md` — same session; both are "a structured pass surfaces what was otherwise invisible." This one is the inverse: the *absence* of a structured pass leaves a dimension invisible.
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — both are "the cheap/obvious step that no one is assigned to silently doesn't happen."
