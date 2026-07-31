# SPEC-033 — Dual-Lens Spec-Review Gate (adversarial + completeness)

**Issue:** #1059 (origin) → v0.6.0 work item
**Status:** FINAL — human-approved. Consumed by `ADR-033-dual-lens-spec-review-gate.md` and
`TECHNICAL-DESIGN-033-dual-lens-spec-review-gate.md`.
**Change classification:** structural (new required gate, new decision points, new overseer capability)
**Research basis:** Session #1059 empirical result (adversarial vs. completeness catch disjoint
defect classes); IEEE 1012 verification & validation vocabulary (see §1a of ADR-033)
**Date:** 2026-07-31
**Author:** pm-agent

> **Why this document exists (provenance note).** ADR-033 and TECHNICAL-DESIGN-033 cite FR1–FR8
> and the FR2 classification test as a citable artifact, and AD-6 requires FR2's classification
> test be transcribed **verbatim from the requirements**. The requirements had been finalized
> conversationally but never written to a file (ESC-1 / TD-VF-4). This document is that artifact —
> the finalized requirements, unchanged in substance, with the three post-final decisions folded
> in (FR2 union, IEEE 1012 terminology, hold-point binding) and the open questions marked resolved
> with pointers to the ADR decisions that resolved them. This is the same defect family the gate
> itself exists to catch: a governing artifact cited as real that did not exist on disk.

---

## 1. Problem Statement

Two independent review passes on the same body of work (formalizing a "Human" role, #1059)
surfaced two disjoint classes of defect that no single pass caught:

1. **Adversarial / self-consistency** (existing `spec-red-team`, agy/cross-vendor) caught a
   CRITICAL contradiction *within* a technical design: two writers unconditionally targeting the
   same file (`CLAUDE.md`) under conflicting conditions. Cost of catching it at spec time: a design
   revision. Cost if shipped: an installer silently corrupting the wrong content into a file.

2. **Completeness / coverage** (a second pass, a different model, an explicit "what's missing?"
   framing) caught four gaps the adversarial pass structurally *could not*, because they were not
   contradictions in the artifact — they were entire unaddressed scope areas: (a) a generated
   output file inert/unusable in the common case; (b) an instance of the very rule being formalized
   that never got migrated; (c) no day-to-day launcher/credential-lifecycle story for a new
   interactive session model; (d) existing repo documentation the new design silently contradicted
   (an account-count claim).

**Adversarial review checks a spec against itself (self-consistency); completeness review checks a
spec against everything it should address but never mentions (coverage). Neither subsumes the
other.** The gate is therefore a **pair**, not a choice.

The capability does not exist today as a required gate: `spec-red-team` reviews a single build
step's technical design, is agy-only by charter ("Do not invoke codex"), truncates its inputs
(`head -200`/`head -100`), and has no completeness framing anywhere. `METHODOLOGY.md`'s SPEC PHASE
is a single `spec-red-team` node. (ADR-033 §0 additionally found that `spec-red-team` has **no
caller at all** — the SPEC PHASE has never actually executed; wiring the gate is therefore in
scope and is the highest-value part of the work item.)

---

## 2. Scope

**In scope**
- The SPEC PHASE gate: adversarial lens + new completeness lens as one paired, required gate.
- `spec-red-team` charter and a new sibling completeness-review agent.
- The spec-gap issue schema (taxonomy reconciliation + a new `missing-scope` type + `Lens:` field).
- The FR2 trigger (change-classification based, with a tier-floor union for independent-review coverage).
- Routing of both lenses' findings to `pm-agent`; the coder/worker start gate.
- A new `overseer` backstop that rejects/escalates PRs that should have had a spec but did not.
- `METHODOLOGY.md` SPEC PHASE prose + diagram, and the pipeline enumeration in `CLAUDE.md` /
  `contract/OVERSIGHT-CONTRACT.md`.

**Out of scope**
- Outer-loop PR review (unchanged).
- The deterministic validator suite (unchanged).
- Migrating the other region-marker-less agents; extending `TIER_FLOOR_*` to `.md`; the worker
  sandboxing initiative (each a separately tracked item — see ADR-033 AD-11c, VF-7).

---

## 3. Terminology (IEEE 1012-grounded)

This SPEC uses the vocabulary bound in ADR-033 §1a. Positional/coined language ("the deep pass",
"the second model", "qualifying voice") is not used.

| Term | Meaning as used here |
|---|---|
| **Peer review** | Review by the **same model family** as the author, any class. Routine, cost-optimized. |
| **Independent review** | Review by a **different vendor family**, or by the human. Technical independence. |
| **Hold point** | A mandatory verification point beyond which **work cannot proceed** without sign-off by the designated authority. |
| **Witness point** | The designated party must be notified and may attend, but work may proceed if they do not. |
| **Graduated independence** | Independence **coverage unconditional**; independence **intensity scaled** by integrity level/tier. |

**The dual-lens spec panel is a HOLD POINT** (human-confirmed; ADR-033 AD-15): verification is
mandatory at the phase boundary and coding **stops** until it clears. The rationale is rework
avoidance — *"Work could be invalidated, so don't start until we know specs [are] good."* The
rejected alternative (witness point: run the panel but let the coder proceed in parallel) was
considered and declined; that trade is exactly the CP-3 cycle-time pressure recorded in §8.

---

## 4. Functional Requirements

### FR1 — Dual-lens is unconditional whenever the spec phase runs
There is **no standalone adversarial-only mode.** Whenever the SPEC PHASE runs, both lenses run —
they are a single paired gate ("the dual-lens spec-review panel"). The former lightweight
single-lens mode is removed: work that would have qualified for it is, by FR2's definition,
`clarifying` (defect correction / non-behavioral refinement) and skips the spec phase entirely, so
it needs neither lens. FR1 — not the independence rule — is what keeps both lenses mandatory for
this gate (ADR-033 AD-9): if the completeness lens is absent, the panel cannot report a valid
dual-lens verdict even though an independent voice (agy) may still be present.

### FR2 — Trigger

FR2 governs two coupled but distinct gates. The distinction is load-bearing and must not be
collapsed: the authoring phase is classification-triggered; independent-review *coverage* is the
union with the deterministic tier floor, so a high-risk bugfix that skips the authoring phase still
receives an independent voice.

#### FR2a — Spec phase + dual-lens panel (the hold point) — **classification-triggered**

> **[VERBATIM — load-bearing; transcribe exactly. ADR-033 AD-6 requires this text quoted verbatim.]**
>
> A work item requires the spec phase (pm-agent → architect → technical-design) **plus the
> dual-lens spec-review panel iff its change classification is `additive` or `structural`** — i.e.,
> iff it introduces, alters, or removes any observable behavior, requirement, interface,
> gate/routing rule, permission, flow step, or configuration surface beyond what an approved
> artifact already requires.
>
> **Operational citation test:** if you cannot point to the approved artifact text that already
> requires the post-change behavior — or to a defect report / failing test showing current behavior
> *violates* that text — the change needs a spec. When in doubt, it needs a spec.
>
> **Exhaustive exceptions** (exempt only if one holds AND the citation is recorded in the
> issue/PR):
> 1. **Defect correction** — restores behavior an approved artifact already requires, cited by
>    section / issue / failing-test.
> 2. **Non-behavioral refinement** — comments, formatting, pure refactors with test-verified
>    behavior preservation, docs corrected toward their authoritative source.
>
> **Explicitly NOT exemptions:** "it's small," "it's LOW risk," "it only tightens governance,"
> "high confidence."

`additive` is included deliberately (not only `structural`): additive changes write down behavior
for the first time — exactly what spec review exists to scrutinize — and excluding them would open
a mislabel-to-`additive` escape hatch, since `structural` already forces a human gate. The trigger
is evaluated at the intake-triage classification rule; that rule must be **mode-independent**
(bind on both INTERACTIVE and AUTONOMOUS worker modes), not restated per mode, and must not be
grafted onto `triage.py` (which classifies for a different purpose). See ADR-033 AD-6.

**Why classification, not risk tier, gates the authoring phase:** risk tiers measure surface
hazard (auth, persistence), not behavioral novelty. Tier-only would under-trigger on a new LOW-risk
UI feature that plainly needs a spec, and over-trigger on a one-line HIGH-risk auth bugfix that
should get full code review but not a pm→architect→technical-design authoring cycle.

#### FR2b — Independent-review coverage — **union with the deterministic tier floor**

> **Independent review fires iff** `classification ∈ {additive, structural}` **OR**
> `deterministic tier floor ≥ MEDIUM`.
> **Intensity** then scales with the deterministic tier floor: agy whenever it fires; codex
> additionally at HIGH+.

This is a **union, not a replacement** (ADR-033 AD-14). A pure classification trigger would have
*removed* independent review from high-risk defect fixes — a `clarifying` HIGH-risk auth fix is
exempt from FR2a but must still receive an independent voice. Both are floors; neither vetoes the
other. The principle: **independence coverage is triggered by phase boundary and change
classification; a self-assessed risk tier may scale independence *intensity* but may never reduce
independence *coverage* to zero.** The union is sound because change classification has an
independent mechanical re-derivation (`change_classifier.py` §2a structural-override signatures;
evaluator condition 10; AD-5 merge-time audit), whereas a self-assessed tier is effectively
unaudited on `.md` artifacts (the tier floor's path rules cover code, not prose).

### FR3 — The completeness lens
- **Model independence:** runs on a model that is neither agy (reserved for the adversarial lens)
  nor an instance sharing context with the primary orchestration Claude. #1059 used a fable-class
  model. The binding requirement is a **genuinely separate, class-differential perspective over the
  Opus-authored bundle**; the concrete model is an operator/architecture decision (ADR-033 AD-3/AD-10).
  Note the independence taxonomy: a same-family higher-class check is *class-differential peer
  review* (depth), which is **not** independent review (decorrelation) and never substitutes for it
  — the panel's independent review is agy.
- **Framing:** an explicit coverage prompt — *"What should this spec bundle address but never
  mentions? What entire scope areas, downstream artifacts, lifecycle stories, or existing repo
  documents does it silently leave unaddressed or contradict?"* — deliberately distinct from the
  adversarial framing.
- **Inputs (untruncated):** the **full** pm requirements spec + full ADR + full technical-design
  doc, as a bundle, plus enough surrounding-repo context to detect silent contradictions with
  existing docs (the #1059 account-count class). The `head -200`/`head -100` truncation must not
  apply to this lens.
- **Outputs:** spec-gap issues via the **same issue mechanism** as `spec-red-team` (FR4/FR5).

### FR4 — Gap taxonomy
Reconcile the two conflicting taxonomies already in `spec-red-team.md` (line 83 vs line 105) into
one canonical set, owned by the contract (a shared schema does not live inside one of its
consumers). Add **`missing-scope`** (an entire area the bundle never addresses) as distinct from
the existing **`missing-requirement`** (a specific requirement absent within an area the bundle
*does* address). The boundary test — **"is the area addressed at all?"** — must appear verbatim in
both agent files. Every spec-gap issue carries a **`Lens: adversarial | completeness`** field (one
value, never both) so finding provenance — and the disjointness that is the research value of the
pair — is measurable. See ADR-033 AD-4 for the canonical value table.

### FR5 — Routing to pm-agent and the coder gate (single uniform gate)
Both lenses route findings to **pm-agent** via the existing spec-gap issue flow. pm-agent resolves
each (update spec, set change classification, obtain human approval for `structural`). The existing
**`Ready for coder: YES`** field is the single, uniform gate: **coder/worker MUST NOT start until
every open spec-gap issue from *both* lenses is `Ready for coder: YES`.** No parallel mechanism is
introduced. (ADR-033 AD-8 notes the field today has no *enforcer* — the gate must be made
executable, not prose. A spec-gap issue pm-agent judges technical/architectural in scope requires
`architect` confirmation before resolution; `missing-scope` findings will frequently be
architectural.)

### FR6 — Invocation (worker runs the panel directly)
`worker` has full model-invocation capability in both INTERACTIVE and AUTONOMOUS modes. Whenever
FR2a triggers, `worker` runs the dual-lens panel directly (the same way the #1059 interactive
session did). There is no "escalate because worker cannot invoke a completeness-lens model" branch
— that was based on an incorrect assumption.

**Forward constraint (record, do not solve here):** the future worker-sandboxing initiative MUST
preserve the worker's ability to invoke the panel and the underlying vendor CLIs. Stripping
model-invocation capability would silently disable this gate.

### FR7 — Pipeline documentation
`METHODOLOGY.md` SPEC PHASE prose and diagram must show the dual-lens paired hold point and the
FR2 trigger. The gate must be reflected wherever the SPEC PHASE is enumerated (`CLAUDE.md` pipeline
section; `contract/OVERSIGHT-CONTRACT.md`). The **set of hold points must be written down
explicitly in the contract** (ADR-033 AD-13) — an enumerable predicate that is never enumerated
degrades back into a semantic one.

### FR8 — Overseer retroactively rejects PRs that should have had a spec but did not
A recurrence-prevention control for the mislabel-to-skip-the-spec failure mode that already
happened in this repo (`worker.md` line 228: "v0.4.0 #556: workers repeatedly self-exempted").

1. **Structural-override + missing-artifact check.** Run `change_classifier.py` on the PR diff. If
   it trips a structural-override signature (§2a) **AND** no spec-phase artifact exists for that
   step (the dual-lens panel output artifact, technical-design doc, or spec-gap issues) → overseer
   **escalates** (never auto-approves/auto-merges). Absence of the panel artifact is the detectable
   condition; a technical-design doc alone is not sufficient evidence the panel ran.
2. **Exemption audit.** If the PR claims an FR2 exemption (`fix:`/`chore:` framing), overseer audits
   that the cited artifact/issue exists, predates the branch, and the diff's scope stays inside what
   the citation covers. Behavior beyond the cited scope invalidates the exemption.
3. **Mislabel as a loggable finding.** A `fix:`-framed PR whose diff adds behavior is recorded as a
   specific, auditable finding (mirroring how prompt-fidelity / the P9 framing guard flag
   description-vs-diff mismatches), so mislabeling is measurable, not merely blocked.

The detection machinery (`change_classifier.py` §2a; the evaluator's pre-PR condition-10
re-derivation) already exists; FR8's new parts are the **enforcement point at overseer/merge time**
(a backstop for PRs that reached merge without passing the evaluator) and the **spec-phase-artifact
existence** check. Consistent with overseer's "errs toward escalation, never toward auto-merge"
invariant, FR8 escalates to a human — it does not auto-reject-and-close. ADR-033 AD-5 binds FR8 as
an overseer bounce condition (step 4a), **not** as an oversight-evaluator Phase-1 extension; do not
duplicate detection.

---

## 5. Cross-Cutting Corrections (X-1, X-2)

> These two items are cross-cutting corrections carried by the finalized requirements alongside
> FR1–FR8. (Naming: the coordinator referenced "X-1/X-2"; the labels are assigned here to the two
> substantive premise-corrections below. If the coordinator intended a different mapping, this
> section is the place to re-bind them.)

**X-1 — `spec-red-team.md` must be repaired as part of this work, not merely extended.** The file
currently carries **two conflicting gap taxonomies** — the `gh issue create` body (line 83) uses
`gaming-vector|contradiction|implicit-assumption|missing-edge-case`, while the required-fields block
(line 105) uses `ambiguity | missing requirement | contradiction | implicit assumption` — and it
**truncates its inputs** (`head -200` at line 69, `head -100` at line 72). Adding a third consumer
(the completeness lens) on top of two conflicting lists, and asking a completeness lens to judge
coverage from the first 200 lines of a document, would be negligent. Both must be fixed as part of
this work item. (Adopted as ADR-033 AD-4; the truncation removal is required for the completeness
lens by FR3.)

**X-2 — The worker sandboxing forward-constraint.** The future worker-sandboxing initiative
(separately tracked) MUST NOT incidentally strip the worker's panel/model-invocation capability;
doing so would silently disable this gate. This is recorded as a tracked constraint for that future
work, not solved here. (Adopted as the ADR-033 AD-6 forward constraint; see FR6.)

---

## 6. Acceptance Criteria

1. **Trigger is precise.** A `clarifying` change (defect correction or non-behavioral refinement,
   citation recorded) skips the spec phase and the panel (FR2a). Any `additive` or `structural`
   change runs pm→architect→technical-design + the dual-lens panel. A `clarifying` change whose
   deterministic tier floor is ≥ MEDIUM still fires independent review (FR2b). The exhaustive
   exceptions and the "not exemptions" list are documented and testable; the #1059 work classifies
   as gate-required.
2. **Completeness lens I/O is concrete.** Reads the full untruncated bundle + surrounding-repo
   context; runs on a class-differential, non-agy, non-shared-context model with the coverage
   framing; produces `Lens: completeness` spec-gap issues (default type `missing-scope`).
3. **Uniform routing + single gate.** Findings from both lenses are spec-gap issues routed to
   pm-agent; coder/worker is blocked (executably, not by prose) until all such issues across both
   lenses are `Ready for coder: YES`. No second gate mechanism exists.
4. **Worker runs the panel directly.** In both modes, when FR2a triggers, `worker` invokes the
   panel itself. The sandboxing forward-constraint (X-2) is recorded for future work.
5. **Overseer backstop works.** Given a PR whose diff trips a structural-override signature with no
   corresponding spec-phase artifact, overseer escalates (never auto-merges); a `fix:`-framed PR
   that adds out-of-citation-scope behavior is rejected and logged as a finding.
6. **Gate actually executes.** The panel is wired to a caller and produces a machine-readable
   artifact whose presence is verifiable (closing the "documented stage with no caller" gap the
   original SPEC PHASE had). Absence of the artifact is a detectable, blocking condition.

---

## 7. Resolved Open Questions

All open questions the requirements flagged for architect have been resolved by ADR-033 and are
recorded here with pointers (not left open):

| Original open question | Resolution | Pointer |
|---|---|---|
| Extend `spec-red-team` vs. new sibling agent | **New sibling** `spec-completeness-review`; do not extend `spec-red-team` (four independent reasons: vendor prohibition, opposite context rules, differing failure/independence semantics, one-agent-one-lens precedent). | ADR-033 AD-1 |
| FR8 placement: overseer vs. oversight-evaluator | **Overseer** step 4a bounce condition, not an evaluator Phase-1 extension; reuse existing detection, do not duplicate. | ADR-033 AD-5 |
| Completeness-lens model identity (pin "fable" vs. "distinct from agy/primary Claude") | Reference by **class alias / rank**, never a model ID; rank set by policy, rank 4 where budget permits; requirement is genuine class-differential independence, recorded and instrumented, not a pinned vendor. | ADR-033 AD-3, AD-10 |
| Is taxonomy reconciliation in scope? | **Yes** — one canonical set owned by the contract; both `spec-red-team.md` lists rewritten. | ADR-033 AD-4 |
| Whether the panel is a hold point or witness point | **Hold point** — human-confirmed; coding stops until `Ready for coder: YES`. | ADR-033 AD-15, AD-13 |

---

## 8. CP-3 — Cycle-Time / Serialized-Latency Consequence (pm-agent confirmation)

**Status: CONFIRMED as a product fact, not a defect.** The aggressive FR2a trigger means every
`additive` or `structural` change now runs pm-agent → architect → technical-design → the two-lens
panel → spec-gap resolution **before a line of code**, and because the panel is a hold point
(AD-15) this is **serialized**, not parallel. That is a real increase in per-change cycle time.

The human accepted the frequency increase in principle ("There is real value in leaning in on
getting good specs to avoid downstream issues... Shift left"), and the hold-point rationale is
explicitly rework-avoidance: the serialized stop is justified by the expected waste of coding
against an unvalidated spec, whose downstream cost is unbounded, versus the bounded cost of
stopping. **pm-agent confirms this serialized-latency consequence is understood and intended — it
is a product fact of the shift-left decision, not a defect to be optimized away later by
re-narrowing FR2.** The legitimate lever if latency becomes a problem is not to weaken the trigger
but to reduce panel turnaround (e.g. lens parallelism within the panel) while preserving the hold
point; re-narrowing FR2 to reduce latency would reintroduce exactly the escaped-defect risk this
gate exists to remove.

This confirmation is a checkpoint disposition, not a gate. The witness-point alternative (let the
coder proceed in parallel with the panel) was considered and declined (AD-15).

---

## 9. Self-Flag

RISK: MEDIUM
Change classification: **structural** — new required gate, new decision points (FR2a/FR2b trigger),
new overseer rejection capability (FR8). Human-approved (per ADR-033 inputs); this document
persists the approved requirements and folds in the three post-final decisions.

CONFIDENCE: 85%
Basis: High confidence FR1–FR8, the FR2a verbatim classification test, the FR2b union, the IEEE
1012 terminology, and the hold-point binding faithfully reflect the finalized requirements and the
binding ADR-033 decisions they were checked against. Residual uncertainty: the X-1/X-2 label
mapping (§5) is my inference from the coordinator's shorthand — the content is load-bearing and
correct, but the specific labels should be confirmed.
