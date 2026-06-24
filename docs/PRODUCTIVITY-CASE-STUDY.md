# Productivity Case Study: Building HOS + CPS With AI Assistance

*A self-critical mini-paper. Status: internal research note. Originally dated: 2026-06-14. Updated: 2026-06-24.*

## Abstract

Over ~13 days (2026-06-11 to 2026-06-24), one expert human directing AI agents
produced two non-trivial software artifacts in parallel: the Human Oversight
System (HOS), a portable framework for scaling human oversight of AI-generated
code, and CondoParkShare (CPS), a moderately complex Django SaaS application. The
combined measured output is roughly **154,000 lines across three distinct
categories — executable code (~97K), agent definitions (~7K–15K), and project
documentation (~50K) — in an estimated ~150–200 self-reported human-hours.**
Naive cost models imply a large compression versus traditional, no-AI development
— we land on a **hedged, order-of-magnitude range of roughly 10×–25×, plausibly
wider at either end** — but that multiplier is the *least* interesting and least
defensible claim here. The load-bearing finding is the opposite of the usual hype:
**this speed did not come from skipping rigor.** The same output passed a full
oversight pipeline — code review, security review, design↔architect review,
deterministic gates, 150+ tests, a committed audit trail, and a release gate that
caught a real governance gaming-hole (#248) the entire inner loop had passed. The
defensible claim for the dissertation is therefore: *AI compresses the labor; a
structured oversight system is the enabling condition that makes the compressed
labor trustworthy.* Read every number below as an estimate with the caveats
attached — an overclaim here would discredit the research it supports.

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

Measured output (direct filesystem count, June 24 state, **canonical repo per
project only**; figures spot-checked against `git ls-files | wc -l`):

> **Counting note.** Both projects use a three-repo mirror layout (Human/Worker/Overseer),
> where all three repos contain identical file trees for multi-machine deployment.
> All figures below count **one repo per project** to avoid triple-counting.
> CPS agent definitions are copies installed by `hos_install.sh` from the HOS
> release; they are marked separately (†).

### Executable code

| Artifact | Python | Shell | Templates / CSS | Config | **Code total** |
|---|---|---|---|---|---|
| HOS | 34,196 (115 files) | 13,659 (56 files) | — | 1,699 | **49,554** |
| CPS | 33,929 (141 files) | 6,912 (41 files) | 4,666 (50 files) | 2,008 | **47,515** |
| **Combined** | **68,125** | **20,571** | **4,666** | **3,707** | **97,069** |

### Agent definitions

Agent definition files (`.claude/agents/` and `packs/`) specify agent behavior,
escalation paths, tool grants, and role contracts. They are operational
specifications, not narrative prose — closer to code than to documentation.

| Artifact | Files | Lines | Notes |
|---|---|---|---|
| HOS | 43 | 7,053 | Source: 30 agent files + 13 pack region bodies |
| CPS† | 27 | 7,546 | Installed from HOS release; PROJECT regions may add customization |
| **Combined (unique authorship)** | **43** | **7,053** | Counting HOS source only |
| **Combined (deployed)** | **70** | **14,599** | Counting all installed copies |

The honest figure for "new work produced" is **7,053 lines** (HOS source); the
14,599 figure counts each deployment separately. Both are reported; the analysis
below uses the conservative unique-authorship figure.

### Project documentation

Project documentation (.md files outside agent definitions): architecture records,
specs, research findings, runbooks, methodology docs, and design docs.

| Artifact | Files | Lines |
|---|---|---|
| HOS | 222 | 40,698 |
| CPS | 57 | 9,157 |
| **Combined** | **279** | **49,855** |

### Summary

| Category | Lines | Share |
|---|---|---|
| Executable code | 97,069 | 63% |
| Agent definitions (unique) | 7,053 | 5% |
| Project documentation | 49,855 | 32% |
| **Total** | **~154,000** | |

LOC is a contested proxy (see §7); it is used here only because it is the unit the
traditional-cost literature is expressed in.

---

## 2. The sprint (June 11–24)

The work was a genuine ~13-day greenfield sprint, not a project spread over
months and back-dated:

- The idea ("the muse") struck at **2am Thursday, 2026-06-11**. The human opened a
  conversation in the Claude *app*, then moved to Claude *Code* that morning.
- **HOS:** first commit 2026-06-11 14:56; **all 666 commits span June 11–24**
  (~51 commits/day average).
- **CPS:** **107 of 116 commits fall within June 11–21.** The 9 earlier commits
  (late March, late May, June 1) are an **abandoned PHP-on-Plesk implementation**,
  explicitly wiped by the commit *"Fresh start: remove PHP ParkShare app and docs"*
  (2026-06-01). Critically, the new Django rebuild started **June 11** — the same
  morning as HOS. The current code is **pure Django with zero `.php` files tracked.**
  The PHP attempt matters twice over: it is evidence the app is non-trivial (a prior
  hand-built attempt existed), and it is itself a prior *failure* worth counting
  honestly (see §7).
- **Velocity — and why commit count alone misleads.** Commit *count* per day rose
  for HOS across the sprint but *commit size* fell sharply as the codebase and
  tooling matured. Both projects moved from a few **large** early commits to many
  **small** later ones, so commit *size* fell sharply (HOS ~339 → ~119 lines/commit
  in the initial four days; CPS ~1,604 → ~565). Factoring size in **inverts the
  naïve "it accelerated" read**: by *lines changed per day*, HOS was roughly
  **steady** and CPS was **front-loaded** (most of the app landed in the first two
  days as one large initial scaffold, then tapered to refinement). Neither project
  sped up by *output volume*; what changed was **commit granularity** — a workflow
  shift as the codebase and tooling matured, not a growth law. (Per-day line counts
  are churn-inclusive — a rewritten line recounts — so they overstate net-new code
  and are themselves only a coarse proxy. The honest summary: there is no clean
  velocity curve here.)

---

## 3. The effort

**~13 days × ~12–15h ≈ ~150–200 human-hours** (human-supplied; self-reported —
treat as an estimate, not an instrumented measurement). The hours-per-day figure
carries over from the original June 14 estimate (~50–60h over 4 days) and has not
been separately verified for the full sprint; actual hours may differ. Critically,
these were **not hours of passive prompting.** They were high-leverage director
hours: architecture decisions, steering, reviewing agent output, resolving
escalations, and exercising gate-override authority. The human was the bottleneck
and the value-add; the agents supplied throughput. Any productivity reading must
hold this fixed — the result is "what one expert director plus an agent fleet
produced," not "what AI produced."

---

## 4. Traditional-cost estimate (no-AI baseline)

We triangulate two independent methods and report a range. Both are estimates.
Crucially, we now estimate each output category separately, since code, agent
definitions, and documentation carry different productivity norms.

**Method A — line-rate-based.**

*Executable code (~97K lines).* Sustained, fully-loaded production output
(amortizing design, code, test, review, debugging, and overhead) is commonly cited
around **~10–50 LOC/day/developer** for quality production systems; raw greenfield
prototyping runs higher:

- At 20 LOC/day: ~4,850 dev-days ≈ **~22 person-years**
- At 50 LOC/day: ~1,940 dev-days ≈ **~9 person-years**
- At 100 LOC/day (generous greenfield): ~970 dev-days ≈ **~4.4 person-years**

*Agent definitions (~7K lines).* These are operational specifications —
tool grants, escalation paths, role contracts — requiring careful reasoning about
agent behavior. A realistic rate for a senior engineer drafting this class of
specification: **50–100 lines/day**:

- At 50 lines/day: ~140 dev-days ≈ **~0.6 person-years**
- At 100 lines/day: ~70 dev-days ≈ **~0.3 person-years**

*Project documentation (~50K lines).* High-quality technical documentation
(architecture records, methodology, specs, runbooks): **50–150 lines/day**:

- At 50 lines/day: ~1,000 dev-days ≈ **~4.5 person-years**
- At 100 lines/day: ~500 dev-days ≈ **~2.3 person-years**
- At 150 lines/day: ~330 dev-days ≈ **~1.5 person-years**

*Combined Method A range* (conservative greenfield to moderate production):

| Rate assumption | Code | Agent defs | Docs | **Total** |
|---|---|---|---|---|
| Conservative (20/50/50 lines/day) | ~22 yr | ~0.6 yr | ~4.5 yr | **~27 yr** |
| Mid-range (50/100/100 lines/day) | ~9 yr | ~0.3 yr | ~2.3 yr | **~11.6 yr** |
| Generous greenfield (100/100/150 lines/day) | ~4.4 yr | ~0.3 yr | ~1.5 yr | **~6.2 yr** |

Method A's spread is enormous and the lowest LOC/day assumptions are artifacts of
the slowest quality-production contexts; the generous greenfield figure is the more
credible anchor for this kind of work.

**Method B — scope/feature-based.** Estimate independently, in person-months, what
a small traditional team would need to design, build, test, and document each
artifact at its current scope:

*HOS:*
- Code/tooling (install engine, 11 validators, scripts, pipeline): ~6–12 person-months
- Agent definitions (24 agents, full specifications): ~3–6 person-months
- Documentation (methodology, contract, research notes, ADRs): ~3–6 person-months
- **HOS subtotal: ~12–24 person-months**

*CPS:*
- Code (Django app: 2FA, multi-tenancy, booking, audit subsystem, two consoles): ~9–15 person-months
- Documentation (specs, architecture, runbooks): ~2–4 person-months
- **CPS subtotal: ~11–19 person-months**

Combined Method B: **~23–43 person-months ≈ ~1.9–3.6 person-years**, with most of
the mass around 2–3 person-years.

**Reconciliation.** Method B (~2–3.6 person-years) sits at the *low* end of
Method A's mid-range (~11.6 person-years), consistent with the artifact mix
including a large fraction of docs and agent definitions rather than hard
production code. For a conservative but defensible baseline we weight toward
Method B and take **roughly 2–4 person-years of fully-loaded effort**, explicitly
*not* the 27-person-year Method A upper tail.

---

## 5. The multiplier (range, hedged)

Comparing a **~2–4 person-year** traditional baseline against **~150–200
human-hours** (≈ 0.08–0.11 person-years at a 1,800h/year basis):

- Lower bound (2 person-years vs 200h): **~18×**
- Upper bound (4 person-years vs 150h): **~48×**

Those figures look spectacular *and that is exactly why we distrust them.* They
inherit the full uncertainty of both inputs — a soft traditional baseline and
self-reported hours — and multiply it. **Stripping the optimism, we report a
deliberately conservative headline range of ~10×–25×, while acknowledging the
arithmetic supports higher.** We round *down*, hard, on purpose: a 50× claim
asserted as fact would be indefensible, whereas "at least an order of magnitude,
plausibly several times that, with oversight intact" survives scrutiny.

**The compression differs by category.** The three categories do not compress
equally — agent definitions and documentation benefit more from LLM fluency with
structured prose and specification templates, while executable code faces harder
correctness constraints and review friction. A single multiplier masks this
structure; the more defensible claim is directional: *all three categories
compressed substantially, code less so than prose.*

**The three load-bearing assumptions** (move any one and the multiplier swings):

1. **The traditional baseline is ~2–4 person-years.** If the true figure is
   smaller (much of the LOC is generated/boilerplate — §7), the multiplier shrinks
   proportionally.
2. **The ~150–200 human-hours are accurate and complete.** Self-reported and
   extrapolated from the June 14 per-day rate; not separately verified for the
   extended sprint. Excludes prior thinking, the PHP attempt, and accumulated
   expertise. If real engaged hours are higher, the multiplier shrinks.
3. **The artifact mix is comparable to a traditional team's output.** It is not
   exactly — see §7. The compression is real in direction; its precise magnitude
   is genuinely arguable either way.

---

## 6. The crux — speed *with* oversight, not despite it

This is where the case study earns its place in a research record.

The compression above would be unremarkable — and untrustworthy — if it had been
bought by skipping review. **It was not.** The same ~154,000 lines went through a
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
one of the two artifacts built in the sprint, and it **oversaw — and caught bugs
in — its own construction.** The instrument and the experiment were built together.
This is methodologically double-edged: it is strong evidence the oversight is real
(it bites even on its authors), and it is a confound for any clean productivity
measurement (the tooling improved mid-sprint — see §2's velocity discussion).

**The dissertation claim, stated precisely:** *AI compresses the labor; a structured
oversight system is the enabling condition that makes the compressed labor
trustworthy.* The speed is the headline; the oversight is the contribution.

---

## 7. Threats to validity

We hold ourselves to the standard that an overclaim here discredits the research.

1. **Generated/boilerplate LOC.** Migrations, repetitive validators, and agent
   templates are not all "hard" lines. A large fraction of the 154k may be
   low-difficulty or structurally repetitive, inflating any line-rate-based
   compression estimate. This is the single biggest deflator. The three-category
   breakdown (§1) partially addresses this — executable code is held to a stricter
   standard than agent definitions or documentation — but it does not eliminate
   the problem.
2. **Artifact-mix mismatch (code vs prose).** Agent definitions and docs compress
   more easily than code (LLMs are fluent at structured prose and specification
   templates). A traditional team's output would skew more heavily toward code.
   The ~32% doc share inflates any single-multiplier comparison.
3. **Mirror repos, counted once.** Both projects use three-repo mirror layouts for
   deployment; all figures count one canonical repo per project. Prior versions of
   this document erroneously counted all three CPS repos separately, inflating the
   measured total to ~290K lines. The corrected figure is ~154K.
4. **Self-reported human-hours.** The 150–200h is extrapolated from the June 14
   per-day estimate with no independent time-tracking for the extended sprint. It
   excludes ideation, the prior PHP attempt, and the years of expertise the director
   brought.
5. **LOC is a contested proxy.** It correlates weakly with value and is gameable;
   we use it only because the baseline literature is expressed in it.
6. **Survivorship.** This is one project that *succeeded*. The wiped PHP attempt is
   a prior *failure* on the same problem — counting only the win overstates the
   method's reliability. We have an n of effectively one success.
7. **Expert director.** The result depends on a skilled human exercising
   architecture, steering, and override judgment. It does not generalize to a novice
   driver, and likely not to a less expert one.
8. **The traditional estimate is itself an estimate.** Both Method A and Method B
   are judgment calls with wide error bars; §5's multiplier inherits all of it.
9. **Reflexive confound.** The tooling improved during the sprint (§2, §6), so the
   13 days are not a stationary process — early and late hours were not equally
   productive, which muddies any single multiplier.

---

## 8. Conclusion

In ~13 days, one expert director and an agent fleet produced ~154,000 lines across
two real systems — ~97K of executable code, ~7K of agent definitions, and ~50K of
project documentation — in an estimated ~150–200 self-reported human-hours. Against
a triangulated traditional baseline of ~2–4 person-years, this implies a
compression we report conservatively as **~10×–25× (arithmetic supports higher; we
round down on purpose)** — a range, not a hero number, and arguable in both
directions. The compression likely differs by category: documentation and agent
specifications compress more than executable code.

The number is not the point. The point is that the compressed labor went through a
full oversight pipeline that **demonstrably caught real defects — including a
governance gaming-hole the entire inner loop missed (§6, O8/#248).** The speed came
*with* oversight intact, not by sacrificing it. And the oversight system that made
the speed trustworthy was itself one of the two things built in the sprint,
overseeing its own construction. **AI compresses the labor; structured oversight is
what makes the compressed labor safe to ship.** That conditional — not the
multiplier — is the claim worth defending.

---

*Cross-references: [`research/OBSERVATIONS.md`](../research/OBSERVATIONS.md) ·
[`docs/v0.3.0/PACK-INSTALL-VERIFICATION.md`](v0.3.0/PACK-INSTALL-VERIFICATION.md)*
