# Finding: Continuous Autonomous Oversight Requires Decoupling Cheap Work-Detection From Expensive Model Invocation

**Role:** oversight-mechanism — deployment viability of standing autonomous oversight

**First observed:** 2026-06-13, session `2026-06-13-cps-pilot-triage-and-backlog.md` (overnight maintenance loop + Faberix roles spec, `docs/FABERIX-ROLES.md`, issue #167)

---

## The Finding

A scheduled autonomous maintainer that **wakes a full model session on every tick** to check whether there is work imposes cost proportional to *schedule frequency × idle rate* — **independent of how much real work exists.** An hourly loop that spins a model session each hour pays for ~24 model sessions/day even on a day with zero actionable items.

Viable continuous oversight therefore requires a **two-stage design**:
1. **A cheap deterministic trigger (no model):** a pure `git`/`gh`/file-read precheck that answers "is there work?" at ~zero cost.
2. **Expensive model work only when stage 1 returns work.**

If stage 1 finds nothing, the loop exits before any model/CLI call, leaving only a one-line heartbeat. The work-detection oracle **must be deterministic** (no model) to be a real gate — if you ask the model whether there is work, you have already paid.

## Why This Matters

The economics decide whether always-on AI oversight is *deployable*, not just whether it is *correct*. A session-per-tick loop is acceptable as a one-night prototype and untenable as a standing maintainer; the human running this project drew exactly that line ("OK for tonight, not OK for the long run"). Cost-gating is thus a **first-class design constraint** for autonomous oversight components, on par with correctness and safety — an oversight loop that is correct but uneconomical will simply be turned off.

This reframes a piece of the oversight problem as an *operations* problem: the limiting resource for continuous AI oversight is not model capability but **the cost of keeping a model on call**, and the engineering answer is a deterministic "is there work" gate in front of every model invocation.

## Evidence

- The overnight prototype loop (this session, `cron 98204cb6`) wakes a model session hourly and checks for work *inside* the session — it spends tokens on idle ticks. Documented honestly as a temporary prototype.
- `docs/FABERIX-ROLES.md §2` specifies the two-stage design; issue #167 records cost-gating as a **blocking go-live acceptance criterion**, with a definition-of-done requiring a test that proves an idle run makes **no** model/CLI call.

## Implications for Research

1. **Cost-gating belongs in the methodology, not just the ops runbook.** Any claim that continuous AI oversight is practical must account for idle-time cost; a deterministic work-detection gate is the mechanism that makes the claim hold.
2. **Determinism of the trigger is the crux.** The gate only works if "is there work?" is answerable cheaply and deterministically (issue counts, diffs, open-PR lists). Where work-detection itself requires judgment, the cost model breaks — a useful boundary to characterize.
3. **A measurable efficiency metric.** Model-invocations-per-unit-work (vs. per-unit-time) is a concrete efficiency measure for autonomous oversight systems, and a target the two-stage design optimizes directly.

## Related findings

- `nondeterministic-review-gate-converges-on-zero-new.md` — the convergence story the maintainer is driving; cost-gating is what makes *running it continuously* affordable.
- `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` — operational framing of a reviewer-as-gate; this adds the cost dimension.
