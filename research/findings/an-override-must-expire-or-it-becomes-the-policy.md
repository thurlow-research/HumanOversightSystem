# Finding: A human-authorized gate override must expire — a permanent override silently becomes the policy

**Role:** oversight-mechanism — the release gate's human-override escape hatch had no time bound, so each deferral was forever

**First observed:** 2026-06-15, the v0.3.0 release cut (the fourth consecutive override)

---

## The finding

The HOS release gate cannot be forced past a failing validation by an agent — only a human can authorize a `HOS_ALLOW_UNVALIDATED` override, with a documented integrity note. That human-only constraint is sound. But the override itself was **permanent**: once a release shipped on it, nothing ever re-asserted the deferred work. v0.3.0 was the *fourth* release in a row (v0.1.1, v0.2.1, v0.2.2, v0.3.0) to ship on a human override for the same reason — the open-ended cross-vendor adversarial review never converges (the [#208] stopping problem). A safety valve used on every release, with no mechanism to ever close it again, has quietly stopped being an *exception* and become the *operating policy* — while still being documented as an exception.

The human caught this directly: *"Overrides should not be permanent so that we don't forget and are forced to resolve."*

## Why it matters for scalable oversight

Every oversight system needs an escape hatch — a way for a human to say "I see the finding, I accept the risk, ship anyway" — or the gate becomes something operators route around entirely. But an escape hatch with no expiry has the same end-state as no gate at all, reached more slowly and less visibly: the deferred findings accumulate in a backlog nobody is forced to revisit, and the integrity note that was meant to record an exception instead documents a routine. The danger isn't the override; it's the **open-ended** override. The deferral is legitimate; the *amnesia* is not.

The distinction the mechanism must encode: there are two honest ways a gate reaches green — **genuine convergence** (the findings are actually resolved) and **time-boxed human acceptance** (a human takes on the findings as a debt). Only the first should be permanent. The second is a *loan against future work*, and a loan without a due date is a gift.

## The mechanism (the fix)

- The validation stamp gained an optional `override_expires:` field (ISO-8601 UTC). A clean-convergence stamp has no such field; an override stamp must carry one.
- `check_validation_current.sh` enforces it **fail-closed**: absent → no override (skip); present-and-future → active, print days-remaining and continue; present-and-past → **FAIL**; malformed/unparseable → **FAIL** (treat as expired). The failure direction is the whole point — any ambiguity must *force* resolution, never silently extend the loan.
- v0.3.0's override expires one week out (2026-06-22). After that instant, any PR to `main` fails CI until the deferred findings (tracked in the recurring-class epic #269) are resolved or a human re-authorizes a *new* time-boxed override. Re-authorization is allowed — but it is a deliberate, dated, human act each time, not a default.

## The trap it avoids

"We'll get to it next release" is not a commitment; it's a permanent override wearing a promise. The first override feels like a one-time exception. The fourth identical override is a policy that no one decided to adopt. The expiry converts the deferral from an open-ended intention into a dated obligation the CI itself enforces — so the question "are we still overriding this?" gets asked automatically, on a clock, instead of never. The discipline is not "don't override"; it is "every override has a due date, and the gate collects."

## Provenance

Observed 2026-06-15 during the v0.3.0 cut. The release gate's static, self-review, and scripts phases converged clean; the cut diff introduced zero findings; but the open-ended agy+codex review surfaced 3 HIGH + 5 medium *pre-existing* governance-completeness findings (prose-only human clearance not backed by enforceable artifacts — the same class as #253, filed as epic #269) and hit the pass cap. The human authorized the override but required it be time-boxed. Mechanism landed in `check_validation_current.sh` + `validation-stamps/README.md`; recorded as DECISIONS.md **D45**. Related: `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` (the override path's integrity), `unenforceable-rules-need-verification-mechanisms.md` (a rule with no enforcement is a suggestion — here, "resolve the deferred findings" with no expiry was exactly that), and the #208 stopping problem (why the adversarial review never converges, making the override recurring rather than one-off).
