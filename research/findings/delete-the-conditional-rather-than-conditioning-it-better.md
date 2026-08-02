# Finding: Delete the Conditional Rather Than Conditioning It Better

**Role:** oversight-mechanism — when a control fails because a conditional's premise went stale, improving the evidence for the premise preserves the failure class; removing the conditional eliminates it

**First observed:** 2026-08-02, session `2026-08-02-ci-execution-and-branch-rule-verification.md`

---

## The Finding

Oversight systems accumulate conditionals of the form *skip X if Y already happened*. They
are almost always introduced as optimisations, and they are almost always correct when
written — Y really did happen, and repeating X really was waste.

The failure comes later, when Y stops being reliably true and nothing notices. The natural
remedial instinct is to **strengthen the evidence for Y**: verify it properly, attach an
expiry, add a machine-checkable condition. Every one of those is an improvement, and every
one of them keeps the class alive, because the control still depends on a belief about
something it does not itself observe.

**The move that removes the class is deleting the conditional** — making X unconditional, or
relocating X somewhere it is enforced rather than assumed.

### The instance

`.claude/agents/overseer.md:60` forbade the autonomous merge-authority agent from re-running
inner-loop checks: *"Re-run inner-loop checks (validators, reviewer agents) that the worker
should have run pre-PR — bounce the PR back to the worker instead,"* listed under "These are
hard limits. No override path."

The rule reads as an independence principle. It is not. The stated intent, supplied by the
human when the contradiction was raised:

> The goal was that we wanted worker to run inner loop before submitting and if it did, then
> overseer could skip to save tokens.

So it was a **token-economy optimisation conditioned on the worker having already run the
checks** — and nothing verified that. The same session established that no workflow runs the
test suite, and that the attestation standing in for execution was itself being disregarded
(see [`attestation-displaces-the-execution-it-attests-to`](attestation-displaces-the-execution-it-attests-to.md)).
The conditional's premise had been false for an unknown period.

### The near-miss that produced the finding

The first drafted resolution was: **suspend `§60` pending CI execution, with a
machine-checkable lift condition rather than prose.** That is a real improvement on the
status quo, and it was wrong.

It was wrong because the same session had just documented `overseer.md:391` — a suspension
that named a precise lift condition (*"until the content-hash redesign (#552) ships"*), whose
condition was met on 2026-06-28, and which was still in force five weeks later because prose
has nothing to evaluate it (#1211, and
[`a-suspension-conditioned-on-external-state-never-lifts`](a-suspension-conditioned-on-external-state-never-lifts.md)).

**The proposed fix for a stale-conditional defect was another conditional.** Better
engineered, same class. Caught only because the human rejected the framing outright:

> The correct answer is that now the overseer runs the check. **Period.** We abandon the
> cleverness we attempted at saving tokens.

That is worth recording precisely: the reflex to *manage* a conditional is strong enough to
survive having just written up the failure mode of conditionals.

## Trust versus enforcement

The resolution kept the original intent and changed its implementation. Deterministic work
genuinely should not be repeated by an LLM — that reasoning was sound. What failed was
implementing it as **trust** (assume the worker ran the checks) rather than **enforcement**
(the checks run in CI, exactly once, as a required check).

Stated generally: an optimisation that skips work on the belief that it happened elsewhere is
a **liability**. The same optimisation, where the elsewhere is mechanically verified, is
free. The economics are identical; the failure modes are not.

This reframes a class of "efficiency versus safety" trade-offs as false. The efficient design
and the safe design were the same design, implemented at different points on the
trust/enforcement axis.

## The no-fallback corollary

A migration that moves X into an enforced position while leaving the old execution path as a
fallback has not migrated. The fallback fires exactly when the new mechanism is missing or
broken — which is precisely when its absence should be visible.

Applied in the same session to two mechanisms:

- The overseer must consume CI results with **no** "run them myself if the result looks
  missing" path. A missing required check blocks; it does not trigger a local re-run.
- A generated index must **fail** on divergence from its source, with no regenerate-on-read
  or tolerate-a-hand-edit path. Self-healing hides the drift and removes the only signal that
  the generator is not being run.

Both are the same principle: **a silent recovery path destroys the evidence that the primary
mechanism failed.**

## Implication for research

A useful audit question for agentic oversight systems, distinct from the usual ones: **for
each control, what does it assume without observing?** Conditionals of the *skip-if* form are
the concentrated instances, and their premises are rarely re-checked because they were true
when written.

The remediation hierarchy matters, and the intuitive ordering is backwards:

| Fix | Removes the instance | Removes the class |
|---|---|---|
| Verify the premise better | yes | **no** |
| Attach an expiry or lift condition | yes | **no** |
| Delete the conditional; enforce elsewhere | yes | **yes** |

The first two feel like engineering and the third feels like giving up on an optimisation. On
this evidence the third is usually correct, and often *cheaper* once the elsewhere exists —
after CI owns the checks the overseer runs none of them, and a PR failing a deterministic
check never reaches it at all.

## What changed

- **#1217** — `overseer.md:60`'s prohibition **abandoned, not suspended**; the overseer runs
  the checks unconditionally; both documents restated so they cannot drift apart again.
- **#1216** — scope expanded to move *all* deterministic checks into CI and **remove** the
  overseer's execution paths, with an explicit written classification of every overseer check
  as deterministic or judgment. Judgment work — merge-authority matrix, protected-surface
  determination, human-approval verification, and anything under R9.1.1 requiring live
  re-detection — stays with the overseer by design.
- **#1214** — the same no-fallback requirement applied to the generated script index.
