# Productivity Case Study: Building HOS + CPS With AI Assistance

*A self-critical mini-paper. Status: internal research note. Date: 2026-06-14.*

## Abstract

Over four days (2026-06-11 to 2026-06-14), one expert human directing AI agents
produced two non-trivial software artifacts in parallel: the Human Oversight
System (HOS), a portable framework for scaling human oversight of AI-generated
code, and CondoParkShare (CPS), a moderately complex Django SaaS application. The
combined measured output is roughly **60,000 lines of code and ~360 pages of
documentation in ~50–60 self-reported human-hours.** Naive cost models imply a
large compression versus traditional, no-AI development — we land on a **hedged,
order-of-magnitude range of roughly 5×–20×, plausibly wider at either end** — but
that multiplier is the *least* interesting and least defensible claim here. The
load-bearing finding is the opposite of the usual hype: **this speed did not come
from skipping rigor.** The same ~60k lines passed a full oversight pipeline — code
review, security review, design↔architect review, deterministic gates, 150+ tests,
a committed audit trail, and a release gate that caught a real governance
gaming-hole (#248) the entire inner loop had passed. The defensible claim for the
dissertation is therefore: *AI compresses the labor; a structured oversight system
is the enabling condition that makes the compressed labor trustworthy.* Read every
number below as an estimate with the caveats attached — an overclaim here would
discredit the research it supports.

---

## 1. What was built (measured scope)

Both artifacts are real, exercised systems, not demos. Qualitatively:

**HOS — the oversight framework.** A three-way-merge install/upgrade engine
(tested against fresh-install, re-install-preserves-PROJECT, CORE-drift-fail-closed,
and pack-strip scenarios — see `docs/v0.3.0/PACK-INSTALL-VERIFICATION.md`); 11
deterministic risk validators; a multi-agent review pipeline (risk-assessor,
reviewers, evaluator, orchestrator); a cross-vendor panel and release gate; and a
committed append-only audit trail.

**CPS — the Django application.** Two-factor authentication, multi-tenancy, a
booking system with database-level overlap constraints, an audit subsystem, and
both operator and HOA consoles.

Measured output (tracked files only; figures are the project's canonical counts,
spot-checked against `git ls-files | wc -l` and confirmed to within a few percent):

| Artifact | Code (LOC) | Docs |
|---|---|---|
| HOS | ~24,300 (agent + pack region defs 4,831 · Python 9,526 · shell 9,945) | ~270 pp / 137k words |
| CPS | ~35,900 (app Python 23,172 excl. migrations · templates 4,143 · shell 4,854 · agent defs 2,594 · CSS 519) | ~92 pp / 46k words |
| **Combined** | **~60,000** | **~362 pp / ~183k words** |

LOC is a contested proxy (see §7); it is used here only because it is the unit the
traditional-cost literature is expressed in.

---

## 2. The four days

The work was a genuine four-day greenfield sprint, not a project spread over
months and back-dated:

- The idea ("the muse") struck at **2am Thursday, 2026-06-11**. The human opened a
  conversation in the Claude *app*, then moved to Claude *Code* that morning.
- **HOS:** first commit 2026-06-11 14:56; **all 283 commits fall within
  June 11–14.**
- **CPS:** **64 of 73 commits fall within June 11–14.** The 9 earlier commits
  (late March, late May, June 1) are an **abandoned PHP-on-Plesk implementation**,
  explicitly wiped by the commit *"Fresh start: remove PHP ParkShare app and docs"*
  (2026-06-01). The current code is **pure Django with zero `.php` files tracked.**
  The PHP attempt matters twice over: it is evidence the app is non-trivial (a prior
  hand-built attempt existed), and it is itself a prior *failure* worth counting
  honestly (see §7).
- **Acceleration:** HOS commit velocity rose across the four days —
  **33 → 62 → 92 → 96 commits/day** — consistent with the framework bootstrapping
  itself (each day's better agents and tooling accelerating the next). This is
  suggestive, not proof; commit count is a coarse and gameable velocity proxy, so
  read it as one weak signal, not a growth law.

---

## 3. The effort

**~4 days × 12–15h ≈ ~50–60 human-hours** (human-supplied; self-reported — treat
as an estimate, not an instrumented measurement). Critically, these were **not
hours of passive prompting.** They were high-leverage director hours: architecture
decisions, steering, reviewing agent output, resolving escalations, and exercising
gate-override authority. The human was the bottleneck and the value-add; the agents
supplied throughput. Any productivity reading must hold this fixed — the result is
"what one expert director plus an agent fleet produced," not "what AI produced."

---

## 4. Traditional-cost estimate (no-AI baseline)

We triangulate two independent methods and report a range. Both are estimates.

**Method A — LOC-based.** Sustained, fully-loaded production output (amortizing
design, code, test, review, docs, debugging, and overhead) is famously low for
quality production systems — commonly cited around **~10–50 LOC/day/developer**;
raw greenfield prototyping runs higher. Applying this band to ~60,000 LOC:

- At 20 LOC/day/dev: ~3,000 dev-days ≈ **~14 person-years**.
- At 50 LOC/day/dev: ~1,200 dev-days ≈ **~5.5 person-years**.
- At a generous greenfield 100 LOC/day/dev: ~600 dev-days ≈ **~2.7 person-years**.

The spread is enormous and deliberately *not* cherry-picked to the low end. LOC/day
figures vary by an order of magnitude across the literature; this method alone
cannot pin the answer and is shown mainly to be sanity-checked against Method B.

**Method B — scope/feature-based.** Estimate independently, in person-months, what
a small traditional team would need to design, build, test, and document each
artifact:

- *An oversight framework of HOS's scope* (a tested merge/upgrade engine, 11
  validators, a multi-agent pipeline, a release gate, 270 pages of docs): plausibly
  **~6–18 person-months.**
- *A moderately complex Django SaaS app of CPS's scope* (2FA, multi-tenancy,
  constraint-backed booking, audit subsystem, two consoles, 92 pages of docs):
  plausibly **~6–15 person-months.** The prior PHP attempt corroborates that this
  is not a weekend app.

Combined Method B: **~12–33 person-months ≈ ~1–2.7 person-years**, with most of the
mass around 1–2 person-years.

**Reconciliation.** Method B sits at the *low* end of Method A's band. We therefore
weight toward the conservative figure and take the traditional baseline as
**roughly 1–3 person-years of fully-loaded effort** — explicitly *not* the
14-person-year upper tail, which we regard as an artifact of the lowest LOC/day
assumption rather than a credible estimate for greenfield work of this kind.

---

## 5. The multiplier (range, hedged)

Comparing a **~1–3 person-year** traditional baseline against **~50–60 human-hours**
(≈ 0.03–0.04 person-years at a 1,800h/year basis):

- Lower bound (1 person-year vs 60h): **~30×**.
- Upper bound (3 person-years vs 50h): **~100×+**.

Those figures look spectacular *and that is exactly why we distrust them.* They
inherit the full uncertainty of both inputs — a soft traditional baseline and
self-reported hours — and multiply it. **Stripping the optimism, we report a
deliberately conservative headline range of ~5×–20×, while acknowledging the
arithmetic supports higher.** We round *down*, hard, on purpose: a 30×–100× claim
asserted as fact would be indefensible, whereas "at least several-fold, plausibly
an order of magnitude, with oversight intact" survives scrutiny.

**The three load-bearing assumptions** (move any one and the multiplier swings):

1. **The traditional baseline is ~1–3 person-years.** If the true figure is
   smaller (much of the LOC is generated/boilerplate — §7), the multiplier shrinks
   proportionally.
2. **The ~50–60 human-hours are accurate and complete.** Self-reported; excludes
   prior thinking, the PHP attempt, and accumulated expertise. If real engaged
   hours are higher, the multiplier shrinks.
3. **LOC and feature-scope are valid effort proxies, and the artifact mix is
   comparable to a traditional team's output.** It is not exactly — see §7. The
   compression is real in direction; its precise magnitude is genuinely arguable
   either way.

---

## 6. The crux — speed *with* oversight, not despite it

This is where the case study earns its place in a research record.

The compression above would be unremarkable — and untrustworthy — if it had been
bought by skipping review. **It was not.** The same ~60,000 lines went through a
full oversight pipeline: deterministic gates (lint, type, secret, security, license),
11 risk validators, a risk-assessor inspection brief, code/security/design review,
150+ tests, a committed `audit/oversight-log.jsonl`, a cross-vendor second review,
and a final release gate.

That pipeline **demonstrably caught real defects throughout** — it was active
oversight, not decorative. The synthesized observations in
[`research/OBSERVATIONS.md`](../research/OBSERVATIONS.md) document the pattern with
corpus evidence:

- **O1 — "AI can do the work but cannot self-certify it."** Agents produced
  confident, well-evidenced reports that did not reproduce, applied real rules out
  of scope, and re-derived their own risk tier downward. Self-certification is
  structurally void; an independent step must verify.
- **O2 — "Oversight is a layered system."** Each layer catches a defect class the
  others structurally miss — and the system is blind to any dimension it has no
  layer for.
- **O8 — "The last-line gate catches what the inner loop missed."** The v0.3.0
  release gate caught **a real governance gaming-hole (#248) that code review,
  security review, doc validation, and the design↔architect loop had all passed.**
  A gaming-hole is the characteristic catch of a final, decorrelated, whole-system
  gate: the defect that games the very oversight that just approved it.

End-to-end install/upgrade behavior was separately verified against a real
installer in [`docs/v0.3.0/PACK-INSTALL-VERIFICATION.md`](v0.3.0/PACK-INSTALL-VERIFICATION.md)
(fresh install, PROJECT-preserved re-install, CORE-drift fail-closed, pack-strip) —
i.e., the headline behavior was proven, not asserted.

**The reflexive point.** The framework that made the speed safe (HOS) was *itself*
one of the two artifacts built in the four days, and it **oversaw — and caught bugs
in — its own construction.** The instrument and the experiment were built together.
This is methodologically double-edged: it is strong evidence the oversight is real
(it bites even on its authors), and it is a confound for any clean productivity
measurement (the tooling improved mid-build, §2's acceleration).

**The dissertation claim, stated precisely:** *AI compresses the labor; a structured
oversight system is the enabling condition that makes the compressed labor
trustworthy.* The speed is the headline; the oversight is the contribution.

---

## 7. Threats to validity

We hold ourselves to the standard that an overclaim here discredits the research.

1. **Generated/boilerplate LOC.** Migrations, repetitive validators, and agent
   templates are not all "hard" lines. A large share of the 60k may be low-difficulty
   or structurally repetitive, inflating any LOC-based compression. This is the
   single biggest deflator.
2. **Self-reported human-hours.** The 50–60h is an estimate with no time-tracking
   instrumentation; it excludes ideation, the prior PHP attempt, and the years of
   expertise the director brought.
3. **LOC is a contested proxy.** It correlates weakly with value and is gameable;
   we use it only because the baseline literature is expressed in it.
4. **Artifact-mix mismatch.** The AI output skews toward docs and agent definitions;
   a traditional team's output mix would differ, so like-for-like comparison is
   imperfect.
5. **Survivorship.** This is one project that *succeeded*. The wiped PHP attempt is
   a prior *failure* on the same problem — counting only the win overstates the
   method's reliability. We have an n of effectively one success.
6. **Expert director.** The result depends on a skilled human exercising
   architecture, steering, and override judgment. It does not generalize to a novice
   driver, and likely not to a less expert one.
7. **The traditional estimate is itself an estimate.** Both Method A and Method B
   are judgment calls with wide error bars; §5's multiplier inherits all of it.
8. **Reflexive confound.** The tooling improved during the build (§2, §6), so the
   four days are not a stationary process — early and late hours were not equally
   productive, which muddies any single multiplier.

---

## 8. Conclusion

In four days, one expert director and an agent fleet produced ~60,000 lines of code
and ~360 pages of documentation across two real systems, in ~50–60 self-reported
human-hours. Against a triangulated traditional baseline of ~1–3 person-years, this
implies a compression we report conservatively as **~5×–20× (arithmetic supports
higher; we round down on purpose)** — a range, not a hero number, and arguable in
both directions.

The number is not the point. The point is that the compressed labor went through a
full oversight pipeline that **demonstrably caught real defects — including a
governance gaming-hole the entire inner loop missed (§6, O8/#248).** The speed came
*with* oversight intact, not by sacrificing it. And the oversight system that made
the speed trustworthy was itself one of the two things built in the four days,
overseeing its own construction. **AI compresses the labor; structured oversight is
what makes the compressed labor safe to ship.** That conditional — not the
multiplier — is the claim worth defending.

---

*Cross-references: [`research/OBSERVATIONS.md`](../research/OBSERVATIONS.md) ·
[`docs/v0.3.0/PACK-INSTALL-VERIFICATION.md`](v0.3.0/PACK-INSTALL-VERIFICATION.md)*
