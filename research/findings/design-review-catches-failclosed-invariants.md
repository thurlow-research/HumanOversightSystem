# Finding: Adversarial *Design-Stage* Review Catches Whole-System Fail-Closed Invariant Bugs That Per-File Code Review Doesn't Naturally Surface

**Role:** oversight-mechanism — empirical justification for keeping the design↔architect loop (a distinct layer from gates and from code-stage review).

**First observed:** 2026-06-15, building the HOS v0.3.0 pack-install mechanism *with* HOS (the #176 dogfood). Pipeline: architect ADR-031 → technical-design draft → **adversarial architect review of the design** → designer revision → architect re-verify (APPROVE) → coder → gates → code-review + security-review.

---

## The Finding

The adversarial **architect review of the *design*** (before the inner-loop code reviewers ran) found **two blocking bugs plus a latent pre-existing third — all of the same class: whole-system fail-closed / atomicity invariant violations:**

- **B1** — `--no-pack` was silently ignored when `config.sh` already recorded a `PACK=` (the resolution order read the recorded pack first, starving the no-pack arm). A *flag the user passed did nothing.*
- **B2** — an `inject-pack` failure on one agent let the installer write **all the other agents + the manifest + the release stamp** before exiting non-zero — a **partial install**, violating the "nothing written on failure" decide-all-then-act invariant. (The drift path gated correctly *before* the write; the new inject path didn't.)
- **A4 (pre-existing)** — the architect noticed the existing `plan`-failure path had the *same* half-write defect, predating this change.

Then the coder implemented, gates passed (lint/type/153 tests), and the inner-loop **code-review and security-review both APPROVED with zero blocking findings** — only three minor hardening suggestions (a test assertion, a validate-before-read swap, a defense-in-depth slug check).

## Why This Is a Distinct Layer

These three bugs are **invariant violations across the whole install control flow**, not local code defects:
- At the **code** level they look like *correct code* — B2 is valid bash that runs cleanly; the half-write only manifests as a property of the *whole* Phase-A→Phase-B sequence ("does a failure on agent #7 leave agents #1–6 + the manifest written?"). A per-file or per-function code review reads the `fail; continue` and sees nothing wrong locally.
- They are **fail-closed / atomicity** properties: "this flag must win," "nothing is written unless everything validates." You catch them by reasoning about the *contract* and *control flow as a whole* — which is what an adversarial **design** review does, walking edge-case scenarios (pack switch, `--no-pack`-over-recorded-pack, failure-on-agent-k) against the invariant.

The code-review/security-review APPROVING clean afterward is **not** evidence they were redundant — it's evidence the design review had already removed the bugs that were hardest to see at their layer. Each layer caught what it's shaped to catch:
- **design review** → whole-system invariants (fail-closed, atomicity, "this flag must win"), edge-case control flow, contract faithfulness;
- **code review** → local correctness, `set -e` footguns, test vacuity, byte-handling;
- **security review** → path traversal, injection, trust boundaries;
- **deterministic gates** → type soundness, lint, secrets.

No single layer subsumes the others. This is the same "complementary layers" result as `gates-and-review-are-complementary.md`, one rung up: **adversarial design review and code-stage review are themselves complementary**, split along the local-vs-whole-system axis.

## The process moment that proved it

The human had initially said "to the coder" (skip the design↔architect loop), then reversed: *"I'd keep designer↔architect loop. Lets flush out as many bugs as we can."* That reversal is exactly what caught B1/B2/A4 — at the design stage, with precise fixes, **before** committing the buggy version. Had we skipped it, B1/B2 would have gone to the inner-loop reviewers as live code; they *might* have caught them, but the whole-system invariant class is precisely what a per-file reviewer is weakest on, and the latent A4 twin (in code the change didn't touch) would not have been in the code reviewer's diff at all. The design review found it because it reasoned about the invariant, not the diff.

## Cost note

The loop cost two extra agent rounds (design revise + architect re-verify) and a targeted coder fix-round. Cheap relative to shipping a partial-install installer — the failure mode B2 describes is a consumer's `.claude/agents/` left half-upgraded with a stale manifest, which the whole layering/sha model exists to prevent.

## Related findings

- `gates-and-review-are-complementary.md` — the deterministic-vs-agent-review split; this is the design-review-vs-code-review split one layer up.
- `reviewer-overapplies-quality-rule-scope.md` — the inverse caution: verify a reviewer's *citations*; here the architect's findings were verified against the live code before acting (and confirmed real — they were already in the coder's implementation).
- `hos-ports-human-best-practices.md` — design review before implementation review is standard human practice (design docs / RFCs reviewed before code), ported.
