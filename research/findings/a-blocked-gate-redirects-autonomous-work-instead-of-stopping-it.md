# Finding: a blocked gate redirects autonomous work instead of stopping it, so throughput looks healthy while the pipeline is stalled

**Role:** oversight-mechanism. An autonomous agent's response to a gate it cannot pass is part of the oversight loop. It decides where the pipeline's effort goes and how much load lands on the human.

**Source:** HOS session, 2026-10-15 to 2026-10-20, `thurlow-research/HumanOversightSystem` #1776, #2119, #2122, #2123

---

## The finding

From about 2026-10-06, the per-PR `security_scan` gate failed on every code change, whatever the change was. The cause had nothing to do with any diff. `pip-audit` audits the **shared tool venv**, so when new advisories were published against dependencies the venv happened to hold (`black` PYSEC-2026-2120/2121, `mcp` CVE-2026-59951, an old `pyjwt` floor), every PR that ran the gate inherited the failure. A code PR therefore could not pass `pr_readiness`.

The autonomous worker did not stop. It is designed to pick the highest-priority eligible issue each cycle and make progress, and it kept doing exactly that. The work it could still finish was design work. Requirements, ADR and technical-design documents go through a different path and do not change code the gate scans. Over 2026-10-14 to 2026-10-20, **13 PRs merged to `main`. Twelve were requirements, ADR, technical-design or governance-text documents. None changed gate or application code.** Meanwhile **about 45 built-and-reviewed code branches across 36 issues** accumulated unpushed in the worker's clone, each waiting on the gate.

Two effects compounded:

1. **The redirected work generated human load.** In this pipeline, every design stage ends in architect escalations (`ESC-n`) that only the human can rule on. Each design PR added a batch of questions. So the human's queue grew fastest exactly when the pipeline's real output, merged code, was zero.
2. **The workaround stalled on its own escalation.** For the gate's own fix (#1776), the worker built a time-boxed exemption. Then it could not open the PR, because the evaluator required a hand-written authorization file. It asked the human to choose between three options (A/B/C). Each stalled branch with a structural signature hit the same wall and would have raised the same question again (#2122).

Nothing in the cycle's own reporting showed a stall. PRs were opening and merging, and the worker reported a selected issue every cycle. The human noticed only by asking why no code had landed.

## Why it matters for scalable oversight

The existing finding `safety-serialization-makes-the-human-the-rate-limiter.md` describes work **queueing** behind a human-shaped bottleneck. This is a different mechanism: work **substitution**. An autonomous agent told to "make progress on the highest-priority eligible item" treats a blocked gate as a filter, not a stop signal. It moves to whatever the gate does not cover. That is locally rational and globally harmful:

- **Goal displacement and Goodhart's law.** "Issues advanced" and "PRs merged" stay high while the quantity they proxy, verified code reaching `main`, drops to zero. The control's failure is hidden by the agent doing its job well.
- **The gate's purpose is inverted.** A per-PR gate meant to keep risky code out ended up keeping *all* code out. It also routed the pipeline's whole capacity into work that generates escalations, the one resource the system is built to conserve.
- **Diff-scoped and environment-scoped checks were not distinguished.** The failing check measured the *environment* (the shared venv's dependency set), not the *change*. Because it was wired as a per-change blocker, an external event, an advisory published upstream, became a pipeline-wide outage.

## The mechanism for HOS

The remedies came from this incident and were ruled on 2026-10-20 (plan decisions D-1 to D-8, tracker #2119):

- **A pipeline-blocked circuit breaker (#2123).** When the same readiness failure recurs on N consecutive cycles, new builds stop. One `pipeline-blocked` event and one escalation are produced, instead of an ever-growing pile of branches.
- **One blocker, one escalation (#2122).** Pre-PR escalations are deduplicated by cause. Each affected issue records a `blocked_by` edge on the root, instead of raising its own A/B question.
- **Environment-scoped checks run on a schedule and alert (D-5, #1605).** Environment-scoped checks no longer block per PR. A scheduled check that finds a new advisory, or that cannot run at all (a "horked" environment), **pauses the pipeline and alerts the human**. Warn-and-skip is forbidden.
- **A core-first strategy (#2119).** The human parked all non-core work so that the worker's selection could only reach the issues unblocking the pipeline.

## The trap it avoids

"The agent is busy and things are merging" is not evidence that the pipeline is healthy. A throughput metric that counts every merged PR equally cannot tell a working pipeline from one that has routed around its own blockage. The measure of an oversight pipeline's health has to include what is **not** moving: parked branches, blocked hours, escalations by root cause. These were added to the v0.7.1 resilience plan as cycle-summary counts.

## Provenance

HOS human-proxy sessions 2026-10-15 and 2026-10-20 (session log `../sessions/2026-10-20-core-first-unblock-and-escalation-redesign.md`). Commit range on `main`: `0f93f3973`..`1b7e2531a`. The gate's own repair is PR #2121 (`4d5b8cff5`). Related: `safety-serialization-makes-the-human-the-rate-limiter.md` (queueing, as opposed to substitution here), `ci-is-blind-to-consumer-environment-failures.md` (environment versus change), `an-override-must-expire-or-it-becomes-the-policy.md` (the exemptions #2121 introduced all expire on 2027-01-31).
