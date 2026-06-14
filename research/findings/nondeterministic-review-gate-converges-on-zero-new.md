# A non-deterministic reviewer cannot be a binary gate — it converges on zero-NEW, never zero

**Role:** oversight-mechanism — defining "pass" for a non-deterministic gate

## The finding

When the validator in a release gate is a large language model, "the gate passed" cannot mean "the reviewer found nothing." Run an LLM reviewer over the same ~20 governance files repeatedly and it returns a *different* set of findings each pass — and on a rich enough corpus it will essentially always surface at least one real, non-trivial issue. Cutting the first `v0.1.0` release made this concrete: the self-review found a genuine governance finding on **every pass** (a self-reported tier floor, a dropped human-review section, a frontmatter/instruction tool mismatch, …) — all real, none a regression, a new one each time. A gate defined as "block until zero findings" would **never** let a release through.

## Why it matters for scalable oversight

The whole appeal of an automated review gate is a clean pass/fail signal a human can trust without re-reading everything. But a non-deterministic reviewer doesn't produce a stable signal — so the gate's *definition of pass* has to change, or the gate is unusable (it either never passes, or you disable it, which is worse). The only coherent bar is:

> **Pass = zero NEW findings** — every finding the reviewer surfaces is one already *dispositioned* (fixed, or filed as a tracked issue). Convergence is on "nothing un-accounted-for," not "nothing found."

This makes "passed the gate" mean something honest and stable: *not* "the reviewer is satisfied there are no issues" (it never will be), but "**no issue exists that a human hasn't already decided what to do about.**" That is exactly the property a human overseer needs — the queue of un-triaged risk is empty — and it is achievable, whereas zero-findings is not.

## The mechanism (and its cost)

- A **dedup ledger**: fingerprint each finding by `(files, finding-class)`; the verdict keys on findings *not* in the ledger. Disposition a finding (fix it, or file an issue and record `filed:#N`) and it stops gating. Convergence = a pass with zero un-ledgered findings.
- A **hard pass cap with human escalation**: because the reviewer is non-deterministic, "keep re-running until zero-new" must be bounded — at the cap, a human decides, automation never loops forever (the ratchet).
- **Cost honesty:** convergence is real work — each pass surfaces items to fix-or-file. On the first release this exposed a backlog of pre-existing, non-regression governance items. The right move was to **disposition them (fix the mechanical ones, file the design ones) and ship the beta with the queue tracked**, not to grind to a mythical zero or to disable the gate. "Zero-new, everything-tracked" *is* the passing state.

## The trap it avoids

Two failure modes sit on either side:
- **Gate-never-passes** → the team disables the gate (or `--skip-validation`s every release), and now there's no gate at all — the worst outcome, dressed as rigor.
- **Gate-passes-on-noise** → if you dedup too aggressively or treat findings as noise, a real new issue gets silently absorbed. The direction guard: a finding may be marked "seen" only after it's *dispositioned* (fixed/filed), never merely because it resembles a prior one.

Between them, "zero-new-tracked" is the narrow, honest target: the reviewer keeps surfacing things, and the gate passes exactly when none of them is a surprise.

## Provenance

Observed 2026-06-13 cutting `v0.1.0`: the self-review returned a real, distinct governance finding on every pass; the release was cut on "zero-new, all-tracked" (findings fixed or filed as #94/#95 and the post-deployment governance queue) rather than zero-findings. Mechanism delivered earlier for self-review (`validate_self.sh` ledger) and framework-external review (`validate_agents.sh` ledger, issue #78). Related: `ratchet-principle.md` (the cap + human escalation), `self-classification-cannot-gate-the-human-boundary.md` (disposition-not-resemblance as the dedup rule).
