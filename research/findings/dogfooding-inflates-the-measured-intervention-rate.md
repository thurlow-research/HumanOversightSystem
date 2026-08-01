# Finding: Dogfooding an oversight framework on itself systematically inflates the measured human-intervention rate

**Role:** research-validity — a confound in HOS's own empirical data, not a defect in the system

**First observed:** 2026-08-01, articulated while triaging why nearly every HOS PR routes to `HUMAN_REQUIRED` (issue #1042)

---

## The Finding

HOS routes a PR to `HUMAN_REQUIRED` when its diff touches a **protected surface** — the control-defining files listed in `scripts/framework/protected_surfaces.txt`: `.claude/agents/**`, `contract/**`, `bootstrap/**`, `scripts/framework/**`, `.github/workflows/**`, the governance and kill-switch files.

Those files **are HOS itself**. So developing HOS means editing protected surfaces on nearly every substantive change, and nearly every substantive PR escalates to a human.

A consumer project has the inverse profile. It installs those same files as HOS-owned vendor artifacts and does its actual work in application code — `src/`, templates, tests — none of which is on the protected list. The identical policy produces a far lower intervention rate.

**The intervention rate observed while dogfooding is therefore not an estimate of the intervention rate a user would experience.** It is an artifact of the test bed being the framework's own machinery. The two differ structurally, not by degree.

## Evidence

- `protected_surfaces.txt` enumerates the framework's own machinery by design — it exists to protect the controls from being loosened on the controls' own say-so. That is correct policy; the measurement consequence is incidental.
- Directly observed on 2026-08-01: a docs-only PR adding a shell-usage discipline section (PR #1145) routed to `HUMAN_REQUIRED` solely because the same prose was mirrored into `CLAUDE.md`, `worker.md`, and `overseer.md` — three protected surfaces. No code, no behavior change, still escalated. Correct under policy; unrepresentative of a consumer edit.
- Across one working session, seven human-proxy PRs all required human approval, and the practical merge path was human approval plus an admin override of the overseer gate.
- Issue #1042 (`[hos-dev]`, v0.7.0) diagnoses the same effect independently and names it a self-hosting artifact.

## Why It Matters

This repo is simultaneously a deployable framework and a research instrument. Any claim of the form *"an AI oversight pipeline requires human intervention at rate R"* that is measured here **inherits this bias**, and R is biased **upward** — potentially by a large factor, since the difference is categorical (every change vs. rarely any) rather than proportional.

Two distinct consequences:

1. **For research reporting.** Intervention-rate figures derived from HOS's own development must carry the caveat, or they overstate the human cost of AI oversight and understate the framework's autonomy. This is a threat to external validity: the sample is drawn from an unrepresentative population of changes.
2. **For product decisions.** Optimizing the policy to reduce *observed* friction risks optimizing for the dogfooding case at the expense of the consumer case — loosening protections that a real user rarely trips, to fix pain that is mostly self-inflicted by the test bed. #1042 explicitly guards against this by requiring human-led design.

The generalizable point is that **a self-hosted safety mechanism does not sample its own target population.** Any framework whose protections cover its own source will find its most-protected files are precisely the ones its developers edit most, so self-hosted friction metrics are systematically pessimistic. This is not unique to HOS — it applies to any linter, policy engine, or CI gate developed under its own enforcement.

## Implications for Research

Intervention-rate metrics from HOS-on-HOS need either a stated caveat or a correction derived from a consumer deployment. The CPS pilot is the natural comparison case: measuring the same rate there against the same policy would quantify the gap directly and turn this caveat into a measured correction factor rather than a qualitative warning.

Worth separating in any future measurement: escalations caused by **protected-surface matches** (self-hosting-biased) from escalations caused by **computed risk tier** (representative). The second is a meaningful signal about AI-generated code; the first mostly measures which repo you ran the experiment in.

## Related findings

- `three-tier-review-cost-model.md` — cost modelling that this bias would distort if used uncorrected
- `self-governance-recursion.md` — the value side of self-hosting; this finding is its measurement-side cost
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — a CPS-pilot observation, i.e. the unbiased comparison population
