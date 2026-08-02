# Finding: Safety Serialization Silently Makes the Human the Rate Limiter

**Role:** oversight-mechanism — the control that bounds AI risk also bounds AI throughput, and the trade is invisible in the control's own framing

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

Safety controls in AI-assisted pipelines frequently take the form of **serialisation** — permit only one unit of work in flight, so there is no concurrency to reason about. Serialisation is cheap, blunt, and effective. It is also a throughput cap, and the cap lands on whichever actor closes the loop. Where that actor is the human, the system's entire output rate becomes the human's response rate.

The concrete instance: the HOS worker cannot begin new work while it holds **any** open pull request. This is enforced twice, independently:

1. `bin/hos-cron` (#791) exits before invoking the agent when all open bot PRs are approved and awaiting human merge — `_audit cycle-skip reason=awaiting-merge`.
2. `bootstrap/worker-cron-prompt.md` Step 1 instructs: *"All approved/clean → STOP. No open PRs → Step 2."* Step 2 is "pick next issue."

So the worker reaches new work only with **zero** open PRs. One approved-but-unmerged PR idles it completely. The overseer cannot clear the block: bot accounts are excluded from the human-approval gate by design, so anything routed `HUMAN_REQUIRED` waits for a specific person.

Effective throughput equals the human's merge cadence, serialised to one PR at a time — in a system whose stated purpose is *scaling* human oversight over abundant AI output.

## The control is correct; the framing hides its cost

This is not a defect. It is a deliberate defence against a stale-base failure previously observed in this repository: a branch built while other PRs were merging produced a pull request proposing **6,114 deletions** across four already-merged PRs, while appearing entirely normal in review. With one PR in flight there is no moving base to go stale against.

What makes it a finding is that **the cost is absent from how the control describes itself**. #791 is documented as avoiding wasted AI turns — a cost optimisation. Nothing in the launcher, the prompt, or the audit event names the throughput ceiling it imposes. An operator watching an idle worker sees `cycle-skip reason=awaiting-merge` and reads "nothing to do", not "blocked on you."

A separate issue (#1196) was filed to remove a polling backoff on the grounds that it delayed work — and would have been implemented before anyone noticed that the worker exits *earlier in the same file*, for a reason that dominates by orders of magnitude. Optimising the visible constraint while the binding one stays unnamed is the practical consequence.

## Implication for research

Two claims worth carrying into the thesis.

**First:** in agentic pipelines the human bottleneck is often not review *capacity* but review *latency in a serialised loop*. Adding reviewer throughput does not help if the architecture permits only one item in flight. The remedy is concurrency plus a mechanical guarantee against whatever hazard the serialisation was substituting for — here, stale-base detection (#1162) — not more human availability.

**Second:** safety-throughput trades should be **declared at the control**. A control that caps throughput should say so where it is defined and where it fires, so the cap is attributable when someone asks why the system is slow.

This is direct field corroboration of the SLR's reviewer-capacity cluster: reviewer capacity is the binding constraint, reviewer abandonment is the top agent-PR failure mode (Ehsani et al., 2026, `NZJST99D`), and OSS projects are adopting per-contributor open-PR caps (Yang et al., 2026, `XJAXB98T`). Observed here as an *architecturally imposed* cap of exactly one — stricter than any policy those projects adopted, and arrived at without anyone choosing it as a throughput policy.

Note also the direction of the coupling: coordination cost rises >10× from 2 to 4 concurrent agents (Kim & Yegge, 2025, `RPHK78A9`), so relaxing serialisation is not free. The finding is not "parallelise", it is "know that you have serialised, and on whom."

## What changed

- **#1198** — filed as a design decision for the architect rather than a patch, with #1162 (mechanical stale-base enforcement) named as a prerequisite for relaxing the constraint.
- **#1195** — the operator dashboard must distinguish *"worker idle: blocked on N PRs awaiting your merge"* from *"worker idle: no work"*. Today both are silence, and they mean opposite things.
