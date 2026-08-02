# Finding: A Suspension Conditioned on External State Never Lifts

**Role:** oversight-mechanism — a temporary bypass whose lift-condition is prose referencing another artifact's state has no mechanism to fire when that condition is met

**First observed:** 2026-08-02, session `2026-08-02-ci-execution-and-branch-rule-verification.md`

---

## The Finding

Governance systems suspend controls for good reasons — a gate is too noisy, a redesign is
in flight, a dependency is broken. The suspension is written into the agent's instructions
with a stated lift-condition: *disabled until X ships.*

Nothing evaluates that condition. The instruction is prose; the condition refers to state
held somewhere else entirely (another issue, another repo, another team's release). The
agent reading the instruction has no reason to check whether X shipped — the sentence
reads as a standing order, and standing orders are obeyed, not audited.

**The suspension therefore outlives its justification silently, and the longer it holds the
more it looks like settled policy.** A reader encountering it later sees a documented,
reasoned decision. Nothing marks it as expired.

### The instance

`.claude/agents/overseer.md:391` instructs the autonomous merge-authority agent:

> **Validation stamp checks — DISABLED until v0.5.0 (#552):** The stamp CI gate has too
> many false positives in the concurrent-PR workflow. The gitignore bypass (#561) already
> exits 0 (SKIP) for all stamp checks. Do not re-enable until the content-hash redesign
> (#552) ships.

The reasoning is sound and the lift-condition is precise. **#552 closed 2026-06-28.** The
redesign shipped: `scripts/framework/check_validation_current.sh:4` reads
`# Uses content-hash-based stamps (#552): computes a SHA-256 hash of all`.

Five weeks later the instruction still stands, telling the overseer that every stamp check
is a known false positive to be ignored.

**Precisely what this does and does not cause.** The gate itself is live: the current script
has no gitignore or SKIP branch, a missing or stale stamp is a hard `exit 1`, and the check
was confirmed failing for real on PR #1210 via the check-runs API (#1211). So this is **not**
a bypass that has already occurred. It is a **standing instruction to dismiss a real
failure** — an agent that trusts the note instead of reading live CI state would treat a
genuine stamp failure on a protected surface (`.claude/agents/**`) as noise and merge
through it.

That distinction matters for the class. The damage from a stale suspension is not
necessarily that the control stopped running; it is that the **consumer has been told in
advance to disregard the control's output.** The gate and its reader disagree, and only the
reader's belief is written down.

Two aggravating properties:

- **The condition is satisfiable but unobserved.** This is not a vague condition that can
  never be judged met. It is a closed issue with a date. Nobody looks.
- **The disagreement is invisible from both sides.** From CI, the gate runs and reports
  honestly. From the agent's instructions, the gate is a known-bad signal. Nothing compares
  the two, so neither surface shows a conflict.

## Why this class is hard to detect

The suspension is correct at the moment it is written, which is the only moment anyone
reviews it. Every later reading is a reading of a decision that already has a rationale
attached — and a stated rationale suppresses the question "is this still true?"

Neither party can catch it:

- **The agent** reads a standing instruction. Verifying it would mean querying the state of
  an issue mentioned in prose, which nothing asks it to do.
- **The human** sees a gate that is green in CI and an agent that reports normally. There is
  no surface where "control suspended, condition met 5 weeks ago" is displayed.
- **The issue tracker** shows #552 closed and successful. Closing an issue does not notify
  the places that referenced it while it was open.

Note the direction of the failure: the *fix landing* is what made the instruction wrong.
The system was more correct before #552 shipped than after.

## Implication for research

Distinguish two failure modes for temporary governance relaxations. [`an-override-must-expire-or-it-becomes-the-policy`](an-override-must-expire-or-it-becomes-the-policy.md)
covers overrides with no expiry at all. This is the subtler sibling: the expiry condition
**exists and is precise**, and still never fires, because prose is not an evaluator.

The mechanisable form: a suspension must carry a machine-checkable lift-condition — an
issue reference a linter can query, or a hard expiry date that fails closed — not a
sentence naming one. A periodic audit answering *"for every disabled control, is its stated
re-enable condition now satisfied?"* is cheap and, on this evidence, high-yield.

This bears directly on the credibility of autonomous oversight claims. A system's real
control surface is the set of controls whose suspensions have not silently outlived their
reasons — which is not the set any configuration audit reports.

It also qualifies [`stamp-based-ci-enforcement`](stamp-based-ci-enforcement.md), which
records that a committed stamp makes validation non-bypassable. That holds — the mechanism
is non-bypassable and demonstrably still enforcing. What the suspension reaches is not the
mechanism but its **reader**. A control's effective strength is bounded by whether its
consumer has been told to believe it.

## What changed

- **#1217** — filed against the stale instruction, and against a second defect found
  alongside it (`overseer.md:60` forbids re-running validators as a hard limit while
  `bootstrap/overseer-cron-prompt.md:52` instructs the full validator chain every cycle).
- #1217 carries an acceptance item for the general class: record a decision on whether
  "suspended until #N ships" instructions require an explicit re-check trigger, rather than
  fixing only this instance.
