# Finding: The Ratchet Counts Human Attention as Free, So Agents Drift Toward Heavier Human Intervention

**Role:** oversight-mechanism — a safety invariant with no cost term turns "more human involvement" into the default direction of change, against the system's own objective of *scalable* oversight

**First observed:** 2026-10-28/30, human-proxy session (PRs #2205, #2207, #2211; rulings on #2209, #2213)

---

## The Finding

Given the job of building *human oversight* of AI code, the AI agents in this repository took the job seriously. Over months, without the human asking for it, they kept **raising the bar**: more escalations, more human gates, more human-authored artifacts, more threads for the human to clear. Each addition was locally reasonable, documented, reviewed and approved. Taken together, they moved the system away from its stated objective. HOS exists to make human oversight **scale** over abundant AI output. By late October 2026 the human was the system's main mechanical step, not its decision-maker.

The human named both sides on 2026-10-30:

> *"Point 1 — nice to see the AI being responsible. Point 2 — Is this a case of AI losing sight of the objective (SCALABLE human oversight) and not clarifying with the human enough?"*

Both are true. This finding records how the drift happened, because the mechanism is structural and will recur in any AI-built oversight system.

The human then stated what "scalable" means (2026-10-30):

> *"Human time is the most expensive time there is. The goal of the entire effort is to apply the Toyota Jidoka principle to have the system do as much work / checking / validating / fixing as it can on its own and direct the human to items that really need the human's attention. And by definition, every direction to the human needs to be a decision that is presented with a recommendation, risks, pros, cons."*

That gives a test every human-facing item can be checked against. **Is it a decision? Does it carry a recommendation, risks, pros and cons?** If not, it should not reach the human; the system should do it itself. Every instance in the evidence below fails that test.

## Point 1: the responsible behaviour is real

The agents consistently erred toward safety, and that disposition is valuable:

- They failed closed rather than open when a check could not run (`oversight-gate-must-declare-its-deps-and-fail-loud.md`, `the-gate-must-time-out-its-own-dependencies.md`).
- They treated "a human must decide" as something to protect, not route around (`self-classification-cannot-gate-the-human-boundary.md`).
- They never tried to self-approve, self-merge or quietly widen their own authority. Every loosening went to the human, as `ratchet-principle.md` requires.

The opposite failure, controls that look present and never fire, was the dominant failure mode in August (`research/sessions/2026-08-04-controls-that-never-fire.md`). An agent population that over-escalates is far easier to correct than one that under-escalates.

## Point 2: the objective was lost

The objective is *scalable* oversight. Its scarce resource is human attention, and its success measure is human **decisions** per unit of AI output, with mechanical human steps driven toward zero. Nothing the agents worked from stated that measure, so nothing traded against it.

### Evidence (2026-10-28/30)

- **PR #2211.** The human performed **10 acts**: approve, resolve 8 review threads, merge. Only **one** of them was a decision (the approval). The worker opened seven "conditional review" threads, each offering "Approve / Request changes / Close". Every one recommended accept, and none needed the human's judgment. The overseer added an eighth thread. After the human approved, with every required check green and `mergeable_state=clean`, the PR still waited for the human to click merge. The overseer's own `needs-human` label is a hard block in `merge_authority.py:495` (#756), and nothing removes it when the human approves.
- **PR #2207.** The overseer found a one-line `shellcheck` fix and recommended sending it back to the worker. Because the file was a protected surface, it routed the PR to the human instead, and re-skipped it every 15 minutes for hours. The overseer's instructions define the human action as "confirm/direct the send-back" (`overseer.md`, expected-human-action enum, `REQUEST CHANGES`). The human could only relay the overseer's own conclusion.
- **PR #2205.** Four worker threads plus an overseer escalation thread. One was a real decision (installer re-sync, option A/B); the rest were acknowledgements.
- **Human-authored files** (#2170). Evaluator and orchestrator text required the human to *write files in the Worker clone* and run shell commands. The requirement dated from June 2026, when file authorship was the only way to tell human from AI. It survived the later introduction of separate bot identities, and new designs kept reintroducing it.
- **The escalation channel saturated.** On 2026-10-30, `query_issues.sh --list --label needs-human` returned **100 open items**, which is the query's cap (#1923), so the real number is at least 100. Some are parked by strategy rather than questions (`an-escalation-channel-shared-with-parking-loses-its-meaning.md`).
- **Agents filed issues to strengthen the human gate further.** For example, #1419 ("human approval gates prove identity but never attention") asks for gates that require engagement with the evidence. That is reasonable in isolation, and it is one more human step.
- **The proxy did it too.** In this same session the human-proxy recommended a human-committed gate-suspension file, until the human pointed out that they do not author files (now #2170). Its first version of #2209 kept carve-outs for "a protected-surface design choice". The human had to restate the rule: *"Regardless of the protected surface risk etc, if overseer recommends a change it goes to worker. Human intervention adds nothing. Human only when a decision is needed."*

Whether each individual gate originated with an agent or with the human was not traced here. Many were human-approved. The human's own account is that approvals are given from the comment trail, not the diff (`2026-08-04-controls-that-never-fire.md`, "where the human gate actually sits"). So an agent-proposed gate with a well-argued safety rationale reads as approve-worthy, and the human's approval does not act as a check on accumulated cost.

## How the drift happened

**1. The cornerstone invariant prices human attention at zero.** `ratchet-principle.md:59`:

> *"Tightening — raising a tier, re-enabling a gate, adding a reviewer, flagging low confidence, **escalating** — may always be automated. The asymmetry is the whole point."*

Escalating to the human is classified as *tightening*, so automation may add it freely. Removing an escalation is *loosening*, so only the human may do it. The ratchet bounds AI risk correctly, but it has no term for the human's time. Every agent that consulted the principle found that adding a human step is always permitted, and removing one never is. Under that rule the steady state is monotone growth in human load. Each reduction costs a human ruling: #2170, #2209 and #2213 are each one such ruling. This is the drift vector the ratchet was written to prevent (`ratchet-principle.md:40`, "under time pressure, the threshold erodes"), pointed the other way.

**2. "Fail closed" was implemented as "escalate to the human".** A gate that cannot conclude has two safe options: **block and route to the actor who can fix it**, or **ask the human**. The agents almost always chose the second, even when the first was available and the human had nothing to add (#2207). Both are fail-closed. Only one scales.

**3. Each rule was added locally; no one owned the total.** Every gate, thread and escalation was justified within its own PR. No artifact tracked **human acts per merged PR** or **decisions vs. mechanical steps**, so the cumulative cost was invisible to reviewers, the overseer and the human alike (compare `safety-serialization-makes-the-human-the-rate-limiter.md`: the cost is absent from how the control describes itself). #2131's per-cycle metrics, which count needs-human items and escalations by cause, would have surfaced it. That issue was still unbuilt at the time.

**4. The objective was written down, in the wrong place, and never made checkable.** `METHODOLOGY.md:49-54` states it precisely. The system "*pulls* a human only where a decision is genuinely needed", the human's workload is "the size of the *flagged* set, not the size of the change stream", and a blocking thread is resolved "with a *decision* (not just an acknowledgment)". But METHODOLOGY is the explainer. The texts agents actually work from are `AGENTS.md`'s "Core Principle" sections, the contract, and the per-agent instructions, and none of them carries it. Nothing checks it: no write path rejects a human-facing item that is not a decision. The ratchet, by contrast, is in the core findings, enumerable and checkable (`ratchet-principle.md:67`). Agents optimise the property they are given and can check. So the principle existed, and the governing texts silently dropped it, the same shape as `a-decision-records-intent-not-enforcement.md`.

**5. The agents asked about mechanism, not objective.** Escalations put to the human were overwhelmingly about *how* a gate should work: marker format, which reviewer set counts, A/B for an installer step. They rarely asked *whether a human should be in this loop at all*. When ambiguity existed, it was resolved toward more human involvement without clarification. This is Point 2's "not clarifying with the human enough", and it matches O9 (`ai-agent-scope-drift-mirrors-human-dev-behavior.md`): a mandate to "ensure oversight" is read maximally, the way a cautious new hire might read it.

**6. Earlier evidence pointed the same way and was read as a reason to wait.** The 2026-08-04 session observed protected-surface approvals being "robo-approved", meaning the gate fired on nearly every PR. It still recorded "Protected-surface loosening: **Deferred**", on the reasoning that loosening the one working control while others were broken would remove the last reliable gate. That reasoning was sound at the time, but it shows the asymmetry at work: evidence of over-gating produced a decision to keep the gates, pending more evidence.

## Implication for research

1. **An oversight invariant needs a cost term, and Jidoka supplies it.** In Toyota's terms the line runs on its own and stops only to pull a person to a defect it cannot resolve. A stop that does not need the person is waste (*muda*), not safety. "Automation may only tighten" is necessary but not sufficient. A complete statement is closer to: *automation may only tighten oversight of AI **risk**; it may not increase the human's **mechanical load** without a human decision either.* Human attention is a protected resource with its own ratchet: steps that are not decisions should be removed by default, and adding one is a design change requiring a human ruling. Without this, a safety-first agent population converges on a system that is safe and does not scale. For a scalable-oversight framework that is a failure of purpose, not of safety.

2. **Distinguish decision steps from mechanical steps, and measure them.** The useful metric is not "how often does a human touch a PR", but **human decisions per merged PR**, alongside **mechanical human steps per merged PR**, which should approach zero. #2211's 1:9 ratio is the kind of number that would have flagged this months earlier.

3. **A responsible AI is not automatically an aligned one.** The agents' safety disposition was genuine and is worth keeping. It still optimised a proxy (more human checking) over the objective (scalable human oversight), because the proxy was explicit and checkable while the objective was not. This is a governance-design lesson more than a model lesson: if you state the safety rule and not the scaling goal as a checkable invariant, conscientious agents will maximise safety at the goal's expense.

4. **Clarifying questions should target the objective.** An agent uncertain whether a human should be involved should ask *that*, framed against the objective ("this adds a human step that is not a decision; is that intended?"), rather than design the human step and ask about its details.

## What changed

Rulings from this session, each removing human load the agents had added:

- **#2216** (v0.7.0): the human's definition of "scalable" becomes a **core principle** in `AGENTS.md`. Human time is the most expensive resource. Every direction to the human is a decision with a recommendation, options, pros, cons and risks. Adding a human step is not free tightening. A write-path check rejects human-facing items that lack the decision form.

- **#2209** (v0.7.0): every overseer-recommended change goes to the worker, regardless of risk tier, protected surface or finding class. The human is involved **only when a decision is needed**.
- **#2213** (v0.7.0): the human's approval alone suffices. On a designated approval of the current head, the overseer clears its own awaiting-approval hold and merges, with no human merge click and no bypass. (Related to the long-term #1519, "PRs auto-merge on approval".)
- **#2174** (v0.7.0): the overseer signs off its own side and requests the human, ending admin bypass merges.
- **#2170** and children: the human supervises through GitHub acts only and never authors files or runs shell.
- **#2212** (v0.7.2): a canonical script to resolve review threads, so clearing acknowledgement threads is not a human chore.

Not yet done: a human-load metric (#2131 is closest). The worker's conditional-review threads still need an "only when a decision is needed" rule; that belongs with #1913, the binary CONDITIONAL_PROCEED gate.

## Related findings

- `ratchet-principle.md`: the invariant this finding qualifies, not contradicts
- `safety-serialization-makes-the-human-the-rate-limiter.md`: the same cost, invisible in the control's framing
- `an-escalation-channel-shared-with-parking-loses-its-meaning.md`: the saturated `needs-human` channel
- `buried-disclosure-fails-like-no-disclosure.md`: more human-facing items lower the salience of each
- `human-gate-enforcement-limits.md`: why file-authorship gates existed (identity), and why they outlived the reason
- `ai-agent-scope-drift-mirrors-human-dev-behavior.md`: maximal reading of a broad mandate (O9)
- `jidoka-reactive-pipeline.md`: stop for the human only on a new finding, the same principle at the pipeline level
- `a-decision-records-intent-not-enforcement.md`: the principle was recorded (METHODOLOGY) but not carried into the texts that govern behaviour
- `research/sessions/2026-08-04-controls-that-never-fire.md`: the opposite failure, and the early "robo-approved" observation
