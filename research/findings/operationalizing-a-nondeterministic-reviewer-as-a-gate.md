# Finding: Operationalizing a non-deterministic reviewer as a release gate — a four-mechanism convergence architecture

**Role:** oversight-mechanism — the complete pattern that makes an adversarial LLM reviewer usable as a hard gate instead of a blocker that's always disabled

**First observed:** 2026-06-13, synthesized while cutting v0.1.1 (the framework gating its own release)

---

## The problem, stated precisely

An LLM reviewer used as a gate has a property no deterministic check has: **on a rich corpus it never reports "nothing."** Run an adversarial self-review (or cross-vendor agy/codex) over a governance-dense codebase and it returns a *different, non-empty* set of real findings every pass. This is not a bug in the reviewer — it is what "adversarial review of a complex artifact" *is*. But it breaks the one thing a gate must do: produce a stable pass/fail. A gate defined as "block until the reviewer finds nothing" **never passes**, so the team disables it (`--skip-validation` every release), and now there is no gate — the worst outcome, dressed as rigor.

Cutting v0.1.1 made this concrete and unavoidable: the framework's own release gate ran its self-review over its own agent files and **surfaced ~14 genuine, distinct governance findings across successive runs** — none of them regressions of the release's diff, several shipped undetected through prior releases. Each was real. The gate was correct to find them and correct to refuse a "clean" verdict. And the release could not ship.

## The insight: convergence is an *architecture*, not a reviewer property

You cannot make a non-deterministic reviewer deterministic. So you stop trying to, and instead build the *system around it* so that "pass" becomes a stable, honest, reachable state. Four mechanisms compose to do this; each is insufficient alone, and the combination is what works.

**1. Redefine "pass" as zero-NEW, not zero (the dedup ledger).**
Fingerprint every finding `(files, finding-class)` with a disposition (`fixed` / `filed:#N` / `residual` / `noise`). The verdict gates only on findings *not* in the ledger. "Pass" = "no un-dispositioned finding exists," not "no finding exists." This is the honest bar — the human's queue of un-triaged risk is empty — and it is reachable, whereas zero-findings is not.
→ `nondeterministic-review-gate-converges-on-zero-new.md`

**2. Feed the reviewer its own known-issues list (proactive dedup).**
The ledger alone *loses a race*: the reviewer spends its entire budget re-deriving already-filed issues, so every run still surfaces "new" blocking findings (genuine-new mixed with not-yet-fingerprinted variants of known ones). Inject the open issue tracker into the review prompt — *"these are tracked; report only what's new."* The reviewer stops generating known-issue noise; its output becomes genuinely-new findings by construction. Measured: 2–3 new/run → 1 new/run, immediately. This is exactly how a human reviewer is briefed.
→ `feed-the-reviewer-its-own-issue-tracker.md` (#134)

**3. Triage with an *accept* disposition (stop fixing what isn't worth fixing).**
Not every real finding should be fixed. Editing a dense governance file to fix a minor finding (a) risks introducing a worse bug and (b) re-enters the file into review, where the reviewer surfaces the *next* subtlety — fixing *spawns* findings. The disposition set must include **residual/accept**: minor + fix-churn-risk > finding-severity → record and move on. Convergence = "every finding *dispositioned*," and accept is a disposition. Guardrail: accept is a *loosening*, so it requires human concurrence (the ratchet) — the AI must not downgrade a real finding to "accept" to unblock itself.
→ #133

**4. Match validation blast-radius to release blast-radius (scope by release type).**
A full-corpus adversarial sweep is the right bar for a **major** release and the wrong bar for a **patch**. Scope the gate's review to the *release diff* for minor/patch (`--changed-only --base <last tag>`), and reserve the full sweep for major. The correct convergence bar for a patch is "zero-new *since the diff*," not "zero in the corpus."
→ #130 / `DECISIONS.md` D39

**The full sweep doesn't vanish — it moves off the critical path.** A continuous, always-on job (daily, on a server, not a laptop) runs the full-corpus review and files NEW findings as tracked issues, ledger-deduped so it never re-files. The never-ending review becomes a *managed governance backlog* instead of a *release blocker*.
→ #131

## Why the composition is the contribution

Each mechanism patches a different failure of the naive gate, and removing any one breaks it:

- Without (1) the gate never passes (zero-findings is unreachable).
- Without (2) the gate churns (the reviewer re-reports known issues faster than you can fix them).
- Without (3) the loop never terminates (fixing spawns findings; some findings shouldn't be fixed).
- Without (4) a patch is held hostage to the whole corpus (the wrong bar for the blast radius).
- Without the async sweep, you've quietly stopped doing full-corpus review (you only ever look at diffs).

Together they convert *"an adversarial reviewer that never says 'nothing left' blocks every release"* into *"a continuous triage funnel that ships patches on their own diff, audits the full corpus as background work, and keeps a human-owned backlog of accepted/tracked risk."* That funnel — not any single reviewer — is what makes a non-deterministic gate shippable.

## The unifying lens: we are re-implementing human-review best practices

The striking thing about all four mechanisms is that **none of them is new** — every one is a long-standing best practice of *human* review processes, which we are now porting to an AI reviewer because the AI reviewer reproduces the *human* reviewer's failure modes:

| Convergence mechanism (for the AI reviewer) | The human-review practice it re-implements |
|---|---|
| Feed the reviewer the known-issues list (#134) | Brief a reviewer: *"here's the open-issues list; tell us what's new"* — you never ask a human to re-find every known bug from scratch |
| Dedup ledger / zero-NEW bar | A bug tracker: don't re-file duplicates; "resolved" means triaged, not "no bugs exist" |
| Triage with an *accept* disposition (#133) | "Won't fix" / "accepted risk" — mature teams *decide not to fix* minor issues when the fix costs more than the bug |
| Scope by release blast-radius (#130) | Full security audit for a major launch; a focused diff review for a hotfix |
| Continuous off-path full sweep (#131) | A standing periodic audit / red-team cadence, separate from the release |
| Human-gated *loosening* of any disposition | Sign-off authority: a junior reviewer can flag, only a lead can wave something through |

This is the deeper claim of the whole project restated from a new angle: **scaling AI oversight is, in large part, the work of re-discovering and porting the accumulated coping mechanisms of human review.** Those mechanisms exist because human reviewers have always faced exactly these constraints — finite attention, a never-empty findings queue, duplicate reports, the temptation to over-fix, audit cost that must be rationed. We reached for an LLM reviewer expecting a clean machine oracle, got a tireless-but-non-deterministic *colleague* instead, and the fix was to manage it the way good organizations have always managed review: brief it, dedupe it, triage it, scope it, and run a standing audit beside it. The novelty is not the practices — it is recognizing that an AI reviewer needs them *for the same reasons a human does*, and building them into the pipeline as code rather than leaving them as tribal process knowledge.

## The general principle

This generalizes beyond this framework to **any oversight gate built on an LLM (or any non-deterministic) reviewer**: code review, security review, policy review, content moderation at scale. The reviewer's job is to *surface*, never to *certify clean*. The system's job is to make "pass" mean "every surfaced risk is dispositioned" — via proactive known-context, a dedup ledger, an explicit accept/triage step with a human-gated loosening guardrail, blast-radius-matched scope, and a continuous off-path full sweep. Build those, and a reviewer that by design never stops finding things becomes a gate you can actually keep turned on. And the design heuristic for *what to build next* turns out to be simple: **ask how a well-run human review organization handles this failure, and implement that.**

## Provenance

Synthesized 2026-06-13 while the Human Oversight System cut its own first patch release (v0.1.1) and its self-review refused to converge on the full corpus. The four mechanisms were built in sequence under real pressure: the ledger (earlier), then release-type scoping (#130/D39), the triage/accept step (#133), feeding the reviewer its known issues (#134), and the daily async sweep on an always-on host (#131). Component findings: `nondeterministic-review-gate-converges-on-zero-new.md`, `feed-the-reviewer-its-own-issue-tracker.md`. The recursion is not lost on us: the framework discovered this architecture by being subjected to its own gate.
