# HOS — Enhancement Ideas

Design observations captured during SLR work that are HOS-scope (not SLR-scope).

> Moved into the repo from `../Improvements/ENHANCEMENT_IDEAS.md` on 2026-07-27 so it isn't lost. The detailed SLR-derived candidate set lives in [`SLR-Derived-Improvements.md`](SLR-Derived-Improvements.md).

---

## Slotting decisions — v0.6.0 Astro/JS pack effort (2026-07-27)

Four SLR-derived, generic-but-pack-useful refinements were slotted into the v0.6.0 Astro/JS effort (epic #1029). Each is milestoned v0.6.0, labelled `slr-finding`, and **not yet `needs-ai`** (parked until its wave):

| Item | What | Issue | Where it slots |
|---|---|---|---|
| Reviewer framing | "Find the defect" framing + hand reviewers the test/execution output (SLR highest-pri #2) | **#1037** | node/astro **review-agent** bodies (S14/S17); candidate to promote to CORE later |
| Certification independence | Spec-derived tests, not coder-coverage-derived (SLR high-pri) | **#1038** | node/astro **test-agent** bodies (S15/S18) |
| Fail-honestly check | Deterministic scan for swallowed errors / silent fallback / unawaited rejections — JS-heavy, model-reviewer blind spot (SLR highest-pri #4) | **#1039** | **Wave 2** — semgrep rules in the S6 JS static-analysis validator, or a dedicated JS validator |
| Strip author descriptions | Withhold PR title/description from the security reviewer (SLR highest-pri #3) | **#1040** | CORE panel / second-review (benefits the S2 fail-hard slice); may move to v0.7.0 |

**Deferred (not slotted now):**
- **Supply-chain / provenance for add-on packs + JS dependencies** — genuinely generic and pack-motivated, but a *new capability*; deferred to its own future slice (ScottThurlow, 2026-07-27).
- **"Is the human gate real" measurement** (override-direction tracking + occasionally seeding a known issue) — left on the general **v0.7.0 Quality** track.

Source for all four: [`SLR-Derived-Improvements.md`](SLR-Derived-Improvements.md).

---

## Evidence-chain integrity (assurance artifacts)

**Observed 2026-07-10** (AI House governance talk, noted during SLR Stage-4 SQ6
design): several companies anchor their captured oversight/audit artifacts on a
**blockchain** to get an *immutable, verifiable evidence chain*.

**Where HOS sits today:** HOS captures oversight artifacts by placing them in the
repo under **git version control** — i.e. third-party-demonstrable (shareable,
inspectable) but only *weakly* tamper-evident (history is rewritable; signed
commits help but don't make it immutable).

**The spectrum (integrity of the assurance record):**
`mutable store → version-controlled (git) → cryptographically-signed/append-only → immutable ledger (blockchain/notarized)`

HOS is at the version-controlled point. Stronger points on the same axis:
- **Signed commits + append-only** (e.g. signed tags, transparency-log style) — cheap, no chain.
- **External notarization / transparency log** (e.g. RFC 3161 timestamps, Sigstore/Rekor) — immutability without running a blockchain.
- **Immutable ledger** — the blockchain approach the talk described.

**Why it matters:** two distinct trust properties of assurance evidence —
*verifiability* (can a third party check it?) and *integrity* (can it be altered
after the fact?). HOS has the first; the enhancement axis is the second.
Regulators (e.g. EU AI Act Art. 14 "demonstrable" human oversight) and enterprise
audit care about both.

**Scope note:** in the SLR this is a *supporting-actor* detail — the SLR codes the
assurance *property* (S7 provenance/audit + a `third-party-demonstrable` flag) and
lets immutability/blockchain surface emergently by frequency, not as a first-class
theme. This note keeps the *implementation* idea on the HOS side of the wall.

---

## Oversight-explanation comprehensibility (upleveling the escalation)

**Observed** during SLR Stage-4 triage (corpus anchor: "Explainable automated debugging /
AutoSD", Zotero `7UB2MD8Z`): explanations measurably improve a human's ability to judge
AI-generated patch correctness (5 of 6 bugs in the paper's user study) — *but only if the
explanation is comprehensible.*

**Observed in HOS:** raw model-generated escalation explanations assumed the reader was already
embedded in the code, so they were **unusable to the reviewer being escalated to** — who is pulled
in *precisely because* they are not in the weeds. The generated discussion had to be **upleveled**.

**Fix applied:** explicit instructions to the escalating agent to produce a *decision-ready*
explanation — **(1) context**, **(2) the problem stated plainly**, **(3) the options and their
tradeoffs** — raising the discussion from implementation minutiae to the level at which a
non-embedded human can actually decide.

**Why it matters:** the escalation explanation is the *interface* between the AI's finding and the
human's gate decision. Accurate detection and correct attention-routing are wasted if the handoff
is incomprehensible — this is the "last mile" of scalable oversight.

**Scope note:** in the SLR this is a **first-class theme** (`Emerging_Themes.md` · Theme 2 —
"explanation comprehensibility as the last mile of oversight"). This note keeps the *HOS
implementation lesson* — the explicit context/problem/options-tradeoffs prompt structure — on the
HOS side of the wall.
