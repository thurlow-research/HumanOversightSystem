# Finding: an escalation channel shared with parking loses its meaning, and a label summons nobody

**Role:** oversight-mechanism. The design of the channel that summons the human is part of the oversight loop, separate from whether any single escalation is correct or well placed.

**Source:** HOS sessions, 2026-10-15 and 2026-10-20, `thurlow-research/HumanOversightSystem` #1928, #2102, #2119, #2124, #2125

---

## The finding

HOS escalates to the human with one mechanism: the `needs-human` label on an issue, plus a comment that carries an `hos-escalation` marker. The work-selection gate excludes any issue that has the label, so the label does two jobs at once: **"a question for you"** and **"do not work on this."**

Over time, people and agents also used it for the second job alone. Issues were labelled to keep the worker off them (deferred design chains, items waiting on another issue, strategy decisions). By 2026-10-15 the open `needs-human` list had passed **100 items**. That is the cap of the tool the human-proxy used to read it (#1923), so the true count was invisible too. Inside that list:

- The autonomous worker had sat **idle for about 9 days** with nothing eligible to select, because the issues it could have worked were all labelled. Nothing told the human.
- Real, time-critical questions (for example #1776, whose resolution unblocked the whole pipeline) were in the same undifferentiated list as items deliberately set aside.

On 2026-10-15 the human cleared 23 labels that were not actionable. On 2026-10-20, to focus the worker on core work, the human-proxy then **added the same label to 24 more issues** to park them, because no other parking mechanism existed. The channel the human had just cleaned out was being refilled with things that were explicitly *not* questions.

The label also produced **no notification**. GitHub does not notify anyone when a label is applied, and the Apps that raise escalations cannot be issue assignees. An escalation was recorded, but it did not summon anyone. The human learned of waits only by asking, or from the human-proxy's session-start check, which was itself a working rule and not a mechanism (#2102).

## Why it matters for scalable oversight

`buried-disclosure-fails-like-no-disclosure.md` showed that a correct escalation fails when it is placed where the human will not read it. This is the same failure one level up, at the **channel**, not the document:

- **Signal-to-noise collapse.** When "needs your answer" and "parked on purpose" share one channel, its base rate of true positives falls, and every item in it reads as background. This is the alert-fatigue precondition, created by how the channel is *used*, not by its volume of real alerts.
- **Recording is not summoning.** An audit trail that shows an escalation was raised satisfies "the system disclosed it," but not "the human was reached." For an autonomous loop the difference is liveness: a pipeline whose only call for help is a label can wait indefinitely while appearing compliant.
- **Overloading a gate input corrupts the gate.** Because work selection keys on the same label, every parking use made the selector's view of "eligible work" wrong, which is how the worker came to be idle.

## The mechanism for HOS

Ruled on 2026-10-20 (plan decisions D-2 and D-3):

- **A dedicated `parked` label (#2124),** excluded by work selection. `needs-human` goes back to meaning only "a human must act."
- **Escalation tiers.** Tier 0 records (label plus marker). Tier 1 summons through GitHub: a human assignee (#1928), staleness re-pings, and a session-start digest (#2102). Tier 2 is a narrow, deduplicated, rate-limited push "help" channel, implemented as a direct Pushover call from the cron cycle (#2125). It fires only on a short list of triggers: the pipeline-blocked breaker, a critical wait with no response for more than 24 h, a cycle that cannot start, and a worker that is idle while unparked work exists. It never fires on parked items.
- **The push path deliberately has no dependency on the monitoring stack**, so it still works when that stack is down.

## The trap it avoids

The tempting fix is "add push notifications to `needs-human`." With the channel still overloaded, that would page the human for every parked item. It would train them to ignore the pager, recreating the same failure on a louder channel. The channel's semantics have to be repaired before it can safely be given more reach.

## Provenance

HOS human-proxy sessions 2026-10-15 and 2026-10-20 (session log `../sessions/2026-10-20-core-first-unblock-and-escalation-redesign.md`). Related: `buried-disclosure-fails-like-no-disclosure.md` (placement within a document; this finding is about the channel), `attention-guarantees-not-fix-mandates.md`, `safety-serialization-makes-the-human-the-rate-limiter.md`.
