# ADR-033 — Dual-lens spec-review gate (adversarial + completeness)

**Status:** ACCEPTED — **REVISION 8, 2026-07-31.** Every decision binds; zero open questions.
`technical-design`'s design is reviewed and its five escalations are ruled in **§4a**, which also
carries errata to this ADR (AD-8's `pr_readiness.py` citation was wrong; summary row 7 was stale;
AD-12 item 4 named a withdrawn compensation). The #972–#1002 attribution is **resolved** — Fable
found, opus-4-8 filed — which strengthens AD-3's evidence base. **`coder` is cleared to build**
against the design's four-PR plan, subject to ESC-1 with `pm-agent` (which blocks one sign-off,
not the build).
**Date:** 2026-07-31 (rev 1 and rev 2 same day)
**Author:** architect
**Inputs:** pm-agent finalized requirements FR1–FR8 (human-approved); three human decisions
(rev 1); the revised independence rule + class ordering + outage posture (rev 2)
**Consumers:** `technical-design` (next), then a `needs-ai` issue to the autonomous `worker`
**Amends:** `DECISIONS.md` D4 / D16 — the amendment text is specified in AD-12 and must be
appended as a new dated entry, never edited in place (`CLAUDE.md`: DECISIONS.md is append-only).

> **Revision 8 changelog (2026-07-31).** (a) **§4a** rules `technical-design`'s five escalations:
> ESC-2 approved with a new class-fallback rule; **ESC-3 retain the codex fallback** — *never
> remove an independent participant to satisfy a purity constraint*; **ESC-4 hold points confirmed**
> (HP-1/2/3) with a required "applies when" column and **WP-1 Copilot as a witness point**, which
> converts AD-11b's prose exception into a named structural fact; ESC-1 → `pm-agent`, with AD-6's
> "verbatim" amended because the FR document is not in the repository. (b) **Three errata to this
> ADR**, all found by `technical-design` and all mine: AD-8 cited `pr_readiness.py`, which **does
> not exist** (a *fourth* instance of the VF-1/VF-2/VF-3 family → **ISSUE-9** for the missing
> systemic control); summary row 7 was stale rev-2 text; AD-12 item 4 named the **withdrawn**
> AD-11a as a compensating tightening. (c) **AD-14 would have shipped inert** — `run_review_chain.sh`
> short-circuits below MEDIUM — and TD-VF-6 narrows AD-14's asymmetry claim to the structural
> boundary. (d) **#972–#1002 attribution resolved: Fable found, opus-4-8 filed**; AD-3's n=1 caveat
> **softened, not deleted** (code vs spec-bundle transfer is assumed, not shown), and the tracker's
> provenance lines are recorded as **unreliable for model attribution**.

> **Revision 7 changelog (2026-07-31) — final.** (a) **AD-13 ACCEPTED and BOUND**: *"decision" ≡
> "hold point"*. Rule (2) reads: *at every hold point at least one independent reviewer must
> participate; routine work is unconstrained beyond the peer-review guardrails.* No implementation
> change — but `technical-design` must **enumerate the hold points in the contract**, or an
> enumerable predicate that is never enumerated degrades back into a semantic one. (b) **The
> retroactive-remediation batch is verified — #972–#1002, 31 issues, 30 closed, 2026-07-14** — and
> replaces the weaker testimony-only claim; **its model attribution is contested and must not be
> stated as settled** in either direction. (c) AD-3 gains a note that, if the attribution resolves
> to `opus-4-8`, the evidence argues **against** rank 4 specifically while strengthening the
> class-differential mechanism. **This ADR has zero open questions.**

> **Revision 6 changelog (2026-07-31).** (a) **AD-11a permanently WITHDRAWN** — the human resolved
> the prohibition clause on the **agent-instance** reading, so `code-reviewer` stays rank 2 on the
> merits rather than by deferral. (b) **AD-11a(b) is the more consequential half**: same-model-
> different-instance does **not** discharge a **hold point**, which confirms AD-10 with direct
> human authority and yields the canonical formulation — *a fable-class lens alone at a hold point
> is non-compliant at any rank; the spec panel's hold point is discharged by agy.* (c) **AD-13 has
> a proposed closure** — if "decision" means "hold point", it closes by construction with no
> implementation change; put to the human, not bound. (d) **CP-5 endorsed** by the human on the
> rev-5 disposition. (e) **Fable citation set fixed and scope-corrected** (#1078, #1079, #1082 +
> the design-chain artifact): remediation occurred, but it was a design-chain check over one epic,
> **not** a comprehensive audit, and **no issue enumeration may be attached to it.**
> **AD-13 is now the only open question on this ADR, and it blocks nothing.**

> **Revision 5 changelog (2026-07-31).** The rev-4 budget premise is **withdrawn** — the pass that
> "consumed the weekly budget" was a full-codebase audit, not a routine per-bundle pass; real
> utilization is ~9%. **CP-5 withdrawn; AD-3 rank 4 BINDS** as *the demonstrated configuration
> pending better evidence*, with the n=1 qualifier and per-bundle consumption instrumentation
> attached. The rev-4 reframe is retained and promoted: because the lens is peer review at every
> rank, a later step-down is a **quality** decision the operator may take with no governance
> change. AD-11a stays suspended, with an added note that my permission-clause reading does **not**
> refute the prohibition clause. §4's cost characterization corrected.

> **Revision 4 changelog (2026-07-31).** (a) **AD-15 CONFIRMED** — the spec panel is a hold
> point, by explicit human decision with a recorded rework-avoidance rationale; no longer
> emergent, no longer pending. (b) **§1a citations verified and upgraded** (IEEE 1012 regulator
> adoption; ASME NQA-1 Req. 10–11 and Section III "H"/"W" points), and **AD-16** adds a
> `research/findings/` note as a deliverable, with a mandatory divergence disclosure. (c) **AD-3
> is COST-UNVALIDATED and partially unbound** — a single retroactive fable-class pass consumed
> the entire weekly budget into overage, so rank-4-at-FR2-frequency does not bind; the lens
> becomes rank-parameterized and the policy goes to the human as **CP-5**. (d) **AD-11a is
> SUSPENDED** — under rev 3's taxonomy it over-applies rule (1) to a peer lane; suspending costs
> nothing and opens no coverage hole. (e) §4's retroactive-exposure record **corrected**: the
> human did remediate, and the fable pass's filed issues are real artifacts.

> **Revision 3 changelog (2026-07-31).** Two further binding human decisions. (a) **AD-14** —
> independent review is triggered by **change classification**, never by a self-assessed risk
> tier; `run_second_review.sh` moves from tier-gated to classification-triggered, with tier
> retained only to scale intensity. I bind this as a **union** with the existing tier trigger,
> not a replacement — see AD-14 for why a literal replacement would have *removed* independent
> review from high-risk bug fixes. (b) **Terminology** — the ADR now uses the established
> IEEE 1012 / IV&V vocabulary (peer review, independent review, hold point, witness point,
> graduated independence) throughout, replacing rev-2's coined "qualifying voice"; see §1a.
> **AD-15** records the hold-point-vs-witness-point question as pending human confirmation.
> CP-4's second bullet is resolved by AD-14.

> **Revision 2 changelog.** The blanket rule "no Claude model can be the independent check"
> (D4:27, D16:80) is replaced by two narrower rules — **class-differential permitted within
> family** and **never sole**. This reopened AD-3 (rewritten), rewrote AD-7 (outage posture),
> and added AD-10 (independence taxonomy + class ordering), AD-11 (**the inner-loop blast
> radius — the largest consequence of the change and the reason this revision matters more
> outside the spec panel than inside it**), AD-12 (the governance amendment), and AD-13
> (pending). CP-1 and CP-2 from revision 1 are **resolved and withdrawn**; one new checkpoint
> replaces them.

---

## 0. Verification findings — requirement premises that do not match the repo

I re-verified every load-bearing claim against the files. pm-agent was correct on the two
conflicting taxonomies (`spec-red-team.md:83` vs `:105`) and on the truncation
(`head -200` / `head -100` at `:69` / `:72`). Eight further findings change the design and are
resolved by the decisions below rather than designed around.

**VF-1 (severity: HIGH) — `spec-red-team` has no caller. The SPEC PHASE does not execute.**
No script, no agent, and no worker chain step invokes `spec-red-team`. `worker.md` step 8
(line 224) dispatches `pm-agent` + `architect` + `technical-design` for spec/behavioral changes
and then goes to coder; `spec-red-team` is never named. `run_review_chain.sh` /
`run_second_review.sh` do not invoke it. The repo's own 2026-06-14 self/3p eval already recorded
this (`audit/2026-06-14-self-3p-eval.md:24`: *"spec-red-team files spec-gap issues but no agent
consumes them"*). **Consequence:** FR7 asks us to document a paired gate at
`METHODOLOGY.md:174` for a phase that has never run. Formalizing a second lens onto an unwired
phase would ship a second unwired agent. **Wiring the gate is therefore in scope and is the
highest-value part of this work item** (AD-2, AD-6).

**VF-2 (severity: HIGH) — FR5's premise is wrong: `Ready for coder: YES` has no enforcer.**
The string appears in exactly one place in the repository, `spec-red-team.md:112`/`:115` — the
issue-body template. No agent reads it. `pm-agent.md` never mentions it; `coder.md` and
`worker.md` never mention it. FR5 says "the existing `Ready for coder: YES` mechanism is the
single uniform gate" — the *field* exists, the *gate* does not. Resolved by AD-8.

**VF-3 (severity: MEDIUM) — the bounce API cited by `overseer.md` does not exist as code.**
`record_pr_bounce()`, `check_register_completeness()`, and `bounce_count(cid)` are cited as
`merge_authority.py` functions in `overseer.md:228-230,252,441` and
`contract/OVERSIGHT-CONTRACT.md:429,542`, and appear in four v0.4.0 design docs. Repo-wide grep
for those identifiers returns **zero `.py` hits**; `merge_authority.py` contains
`decide_merge_authority`, `detect_server_side_gate`, `detect_human_hold_directive`,
`open_draft_pr`, `route_embargo` and no bounce functions. The bounce is an **agent-executed prose
protocol**, not an API. This does not block FR8 (AD-5 hooks the protocol), but
`technical-design` MUST NOT emit `call record_pr_bounce(...)` as though it were callable.
Pre-existing defect; file separately, do not fix here.

**VF-4 (severity: MEDIUM) — the FR2 trigger point is AUTONOMOUS-mode-only.**
The pipeline-discipline classification rule lives at `worker.md:224`, inside step 8 of the
**autonomous** per-task chain. INTERACTIVE mode (`worker.md:75-148`) has no equivalent — only a
routing bullet ("Design or spec a change → dispatch technical-design / architect"). FR2 says the
trigger is evaluated at "the existing intake-triage point (`worker.md` §8 classification step)"
and FR6 requires both modes. Also note `triage.py:triage` (chain step 6) classifies for
*autonomy/security-report routing*, not change classification — it is not the FR2 trigger point
and must not be made one. Resolved by AD-6.

**VF-5 (severity: HIGH — SUPERSEDED IN REV 2, retained for the record).**
Revision 1 found that FR3's "neither agy nor the primary Claude" was *looser* than
`DECISIONS.md` D4:27 / D16:80 (*"no Claude model can be the independent check"*), and tightened
FR3 to forbid any Claude model on either lens. **The human has since revised D4/D16 itself**
(AD-12), so the conflict is resolved in the other direction and revision 1's AD-3 no longer
follows. The finding is kept because it is the reason AD-3 changed, and because the *shape* of
the reasoning still holds: FR3's phrasing ("not the primary Claude") tracks **which instance**
ran, whereas both the old and new rules turn on **family and class**. "Not the primary Claude" is
not a well-formed independence predicate under either rule and must not survive into the
implementation — AD-10 replaces it with an evaluable one.

**VF-9 (severity: HIGH — new in rev 2) — the spec bundle's authors are Opus-class, which is what
makes the class ordering load-bearing rather than academic.** `pm-agent.md`, `architect.md`, and
`technical-design.md` all pin `claude-opus-4-8`. The bundle the completeness lens reads
(pm requirements + ADR + technical design) is therefore **Opus-authored**. Under revised rule (1)
a same-family checker must be *strictly higher class than the author*, so an Opus-class
completeness lens over this bundle is same-class self-validation — the prohibited case. Only a
class strictly above Opus qualifies. The human's ordering ruling (`haiku < sonnet < opus < fable`)
is what makes a same-family completeness lens possible at all here; without it, AD-3 would have
had to stay cross-vendor and revision 1's CP-1 would still stand.

**VF-10 (severity: HIGH — new in rev 2) — the deterministic tier floor already closes most of the
self-referential tier loophole for *code*, and closes none of it for *prose*.**
`change_classifier.py` `TIER_FLOOR_APP_CODE = re.compile(r"\.(py|js|ts|jsx|tsx)$")` floors any
application-code change at **MEDIUM**, and evaluator condition 11
(`contract/OVERSIGHT-CONTRACT.md:536`) FAILs compliance when the self-reported tier sits below
that floor. Since `run_second_review.sh` fires agy at MEDIUM+ (0.30), a same-family chain
**cannot** talk its way out of the independent review on a `.py`/`.ts` change — the exclusion is
deterministically overridden. But `.md` files match no floor rule and floor at **LOW**. In this
repository the governed product *is* markdown — agent charters, the contract, `AGENTS.md`,
methodology. **So the residual surface of the self-referential loophole is precisely the
artifacts that govern the code**, which is also the subject of the repo's own finding
`research/findings/` → *"the artifacts that govern code get less review than code"* (#1079).
AD-11 rules on this.

**VF-6 (severity: MEDIUM) — the repo's vendor↔lens convention is the inverse of FR3's, in three places.**
`DECISIONS.md` D4: agy = "cross-vendor reviewer + **breadth lens**", codex = "independent
reviewer / **adversary**". `run_second_review.sh:11-21`: agy = correctness + spec adherence,
codex = "adversarial security probe". `validate_agents.sh:15-17`: "agy — consistency +
**completeness** lens; codex — **adversarial** gap-finding lens". `spec-red-team.md` is the sole
inverse (agy = adversarial, codex forbidden), and FR3 codifies that inverse. AD-3 keeps FR3's
assignment for a stated reason, and requires the exception be recorded so a later
"consistency fix" cannot silently swap the lenses.

**VF-7 (severity: LOW, but constrains AD-1) — `spec-red-team.md` carries no region markers.**
Twelve agents lack `HOS:CORE`/`HOS:PROJECT` markers (`spec-red-team`, `oversight-evaluator`,
`risk-assessor`, `prompt-fidelity`, `post-change-sweep`, `dep-mapper`, `risk-historian`,
`oversight-orchestrator` + 4 framework-dev validators), contradicting `CLAUDE.md`'s "every agent
file is layered". Scoped by AD-1: the new agent ships layered; migrating `spec-red-team` is a
separate item.

**VF-8 (severity: LOW) — model frontmatter.** `spec-red-team.md:9` pins `claude-sonnet-4-6`;
all 30 agents pin stale IDs (#1122). AD-3 binds the new agent to a class alias, never an ID.

---

## 1a. Terminology (BINDING — rev 3)

HOS's review scheme is an instance of an established practice, not a novel one. Naming it against
that practice makes the design auditable by anyone who knows the field and stops the vocabulary
drifting. **This vocabulary is binding on every artifact this ADR touches** — the two agent
files, `run_spec_panel.sh`, the contract, and the FR7 documentation updates. Coined or positional
language ("qualifying voice", "the deep pass", "the second model") must not survive into the
implementation.

**Citations are verified** (checked 2026-07-31, not quoted from memory) and are carried into the
AD-16 research note.

| Term | Definition as used in HOS | Grounding |
|---|---|---|
| **Peer review** | Review by the **same model family** as the author, any class. The routine inner loop. Cost-optimized, high-frequency. | Standard software-engineering usage |
| **Independent review** | Review by a **different vendor family**, or by the human. **Technical** independence specifically. | IEEE 1012; IV&V practice (NASA / DoD) |
| **Hold point** | A mandatory verification point beyond which **work cannot proceed** without approval by the designated authority. | ITP practice; **ASME NQA-1 Req. 10–11**; **ASME Section III** ("H" points) |
| **Witness point** | The designated party **must be notified and given opportunity to attend**, but work may proceed if they do not attend within the agreed notice period. | Same ("W" points) |
| **Graduated independence** | Independence **coverage unconditional**, independence **intensity scaled** by integrity level. | IEEE 1012's rigor-scales-with-integrity-level |

**Sources:**
- IEEE 1012 — *IEEE Standard for System, Software, and Hardware Verification and Validation*:
  https://standards.ieee.org/ieee/1012/7324
- US NRC **Regulatory Guide 1.168** (*Verification, Validation, Reviews, and Audits for Digital
  Computer Software in Nuclear Power Plants*), which endorses IEEE 1012:
  https://www.nrc.gov/docs/ML1307/ML13073A210.pdf
- IEEE Spectrum's public table mapping IEEE 1012 integrity levels onto consequence × likelihood:
  https://spectrum.ieee.org/regulating-ai-programs-roadmap/table-1-ieee-1012-standards-map-of-integrity-levels-onto-a-combination-of-consequence-and-likelihood-levels
- Hold/witness point definitions: https://www.qualityengineersguide.com/what-is-witness-point-and-hold-point
  and https://forgedops.com/glossary/quality-planning-itps

**Why the grounding is stronger than "general QA practice":**
- **IEEE 1012 is the de facto verification standard for US critical-systems regulators** — used
  for critical weapon systems (US armed forces), NASA critical missions, FDA life-sustaining
  systems, nuclear power generation, and FAA critical flight systems. The claim "this pattern is
  established practice, not a coinage" is therefore load-bearing rather than rhetorical.
- **Hold points are code-required and explicitly non-discretionary.** In ASME Section III work the
  Authorized Nuclear Inspector must sign off a hold point before the traveller advances. That is a
  far better analogue for `Ready for coder: YES` than a generic "gate": a non-discretionary stop
  with a **named independent signer**, where advancing without the signature invalidates the work
  downstream. This is exactly AD-15's confirmed semantics, and it is why FR5's gate must be
  enforced executably (AD-8) rather than by prose convention — an ITP hold point that the
  traveller can walk past is not a hold point.

**Two things taken from IEEE 1012 explicitly, because both change what this ADR may claim:**

1. **Independence is decomposed, not binary — technical / managerial / financial.** HOS has
   **technical independence only.** It has **no managerial independence**: the same orchestrator
   (`worker`) dispatches the author chain and the reviewers, selects the work, and decides when
   review is complete. It has no financial independence either — one operator, one set of
   subscriptions. **This is a known and accepted limitation and the ADR must not imply
   IV&V-grade independence anywhere.** Any claim of the form "HOS achieves independent
   verification" is false as stated; the true claim is "HOS achieves technical independence of
   the reviewing model, under a common orchestrator." The managerial gap is not incidental —
   an orchestrator that chooses which reviewers fire is exactly the actor a managerial-independence
   requirement exists to constrain, which is why AD-14's "never gated on self-assessment" rule
   is load-bearing rather than fussy.
2. **Rigor scales with integrity level.** AD-11b and AD-14 already do this by tier. Naming it as
   the established pattern means future changes argue against a known baseline instead of
   re-inventing one.

**Peer review's two guardrails (BINDING).** Peer review earns its place only with both, because
without them a same-family reviewer degrades to agreement:
- **No shared memory / no author framing.** The reviewer must not inherit the author's context or
  prose rationale. Already partly implemented as `DECISIONS.md` **D53** (author-supplied NL
  framing is untrusted input) — but D53's anti-framing instruction was added to the CORE regions
  of **only** `code-reviewer`, `security-reviewer`, and `privacy-reviewer`. Extending it to the
  remaining peer-review lanes is a named gap; file it, do not fix it here.
- **Adversarial instruction.** The reviewer is instructed to find fault, not to confirm.
  Defeats motivated leniency.

**What peer review explicitly does NOT do:** defeat correlated priors. Two same-family models
share a training distribution and miss the same class of defect however adversarially they are
instructed. That is the sole job of independent review, and it is why AD-10's rule holds:
**class-differential peer review never substitutes for independent review.**

---

## 1. Context

`spec-red-team` checks a spec **against itself** (contradictions, gaming vectors, implicit
assumptions, missing edge cases). Session #1059 demonstrated that a second, differently-framed
pass on a different model catches a disjoint failure class — **entire unaddressed scope areas**
(`missing-scope`): an inert output file, an unmigrated instance of the rule being formalized, an
absent lifecycle story, and silent contradictions with existing repo docs. Adversarial review
cannot structurally reach these: they are not contradictions *within* the artifact, they are
absences *relative to* everything the artifact should have covered. Neither lens subsumes the
other, so the gate is a **pair**, not a choice.

---

## 2. Decisions

### AD-1 — Sibling agent `spec-completeness-review`; do not extend `spec-red-team`. (BINDING)

Create `.claude/agents/spec-completeness-review.md` as a peer of `spec-red-team`.

**Rationale.** Four independent reasons, any one sufficient:
1. **Vendor prohibition.** `spec-red-team.md:124` states "Do not invoke codex". AD-3 puts the
   completeness lens on codex. Extending the file forces me either to delete a correct
   single-vendor constraint or to write a self-contradicting agent.
2. **Context rules are opposite.** `SPEC-379` deliberately excluded `spec-red-team` from
   diff-centric context (`SPEC-379-diff-centric-review-context.md:46,135,141`;
   `TECHNICAL-DESIGN-379:50,85-87,223` — "MUST NOT modify `spec-red-team`"). FR3 additionally
   requires the completeness lens receive the **full untruncated bundle plus surrounding repo
   context**, while `spec-red-team` truncates at `head -200`/`head -100`. One file would carry
   two contradictory context regimes conditioned on which lens is executing — the exact shape of
   defect the #1059 adversarial pass caught (two writers, one file, conflicting conditions).
3. **Failure semantics and independence obligations differ. (Restated for rev 2 — this reason got
   *stronger*, not weaker.)** Under AD-7 rev 2 the two lenses block for different reasons with
   different owners: agy's absence is a rule-(2) violation (mine), the completeness lens's absence
   is an FR1 violation (pm-agent/human). And under AD-3 rev 2 the completeness lens is same-family
   and must therefore compute a rank differential against the artifact's authors at runtime, an
   obligation the cross-vendor adversarial lens does not have at all. One charter carrying two
   fail rules and two independence regimes, switched on which lens is executing, is how fail-open
   bugs are born.
4. **Precedent.** HOS's established shape is one-agent-one-lens with a shared schema
   (`risk-assessor` + `dep-mapper` + `risk-historian`; the eight reviewer lanes). Nothing here is
   novel.

**Cost accepted:** two agents to invoke and gate. AD-2 removes that cost from the caller by
putting both behind one invocation site.

**Registration surface (exhaustive — `technical-design` must cover all of it, since
`check_agents_static.sh` fails on any name/file mismatch):**
`scripts/framework/consumer_agents.txt` (oversight-layer block) · `bootstrap/hos_install.sh:776`
built-in fallback array · `.claude/agents/framework-setup-validator.md:39` `REQUIRED` list ·
`docs/AGENTS.md` (**append a new numbered section — do not renumber §18+**; also the agent-list
block at `:132`, the diagrams at `:962`/`:1019`, and the oversight-layer roster at `:1052`) ·
`ARCHITECTURE.md:81` table and `:157` mermaid · `METHODOLOGY.md:174` · `CLAUDE.md` agent tables +
pipeline block · `contract/OVERSIGHT-CONTRACT.md` (issue-title convention at `:392`) ·
`docs/OVERSIGHT-RUNBOOK.md:255-259` · `docs/SETUP.md:94` (`SPEC_FILE` consumers).
The new file **must** ship with `HOS:CORE` + `HOS:PROJECT` region markers (VF-7). Migrating the
other twelve marker-less agents is **OUT OF SCOPE** → separate `startup-artifact-gap` issue.

### AD-2 — The paired gate is ONE deterministic invocation site: `scripts/run_spec_panel.sh`. (BINDING)

The two agents own the *prompts and judgment*; a single script owns the *gate*. It runs both
lenses, enforces fail-closed, and writes one machine-readable artifact.

**Rationale.** This is the direct application of `DECISIONS.md` **D41 — "Oversight tooling must
fail honestly and through one invocation site"**, written after both cross-vendor reviewers were
silently non-functional and the release gate returned "zero findings" that were a non-review
(HOS#201). VF-1, VF-2, and VF-3 are all the *same failure mode as D41*: a gate that exists only
as agent prose is a gate that does not run, has no enforcer, and cites an API nobody wrote.
Adding a second prose-only lens to an unwired prose-only phase would be the third instance. A
gate whose execution cannot be verified from an artifact is not a gate.

**Bindings:**
- Path `scripts/run_spec_panel.sh`; modeled structurally on `run_second_review.sh`
  (arg parsing, availability pre-check, per-vendor invocation, machine-readable header,
  non-zero exit on fail-closed).
- Output `.claudetmp/spec-panel/step{N}-{ISO-timestamp}.md`, header at minimum:
  `verdict: pass | findings | error | unparseable`, `step`, `adversarial_cli`,
  `completeness_cli`, `adversarial_model_resolved`, `completeness_model_resolved`,
  `bundle_sha`, `findings_count`, `issues_created`, `timestamp`.
- **`unparseable` is NOT `error` and NOT `pass`** — adopt the HOS#113 distinction already
  binding in `contract/OVERSIGHT-CONTRACT.md:548`: a real review the harness could not structure
  is preserved with a loud "a human must read this" notice; it must never collapse into either
  neighbour.
- The artifact is the object FR8 (AD-5) and AD-8 look for. **Absence of the artifact is the
  detectable condition**; presence of a technical-design doc alone is not sufficient evidence
  the panel ran.
- Anti-tamper: any env-var knob may only *strengthen* the gate, never disable a lens — mirror
  the `min(trusted_baseline, clamp(env,0,1))` rule at `run_second_review.sh:60-80` written for
  HOS#985 (an author committing a threshold to self-skip review).

### AD-10 — Independence taxonomy and the class ordering. (BINDING — rev 2)

The revised rule is only enforceable if "independent", "higher", and "sole" are evaluable
predicates. This decision defines them once; every other decision references them.

**Class ordering (human-ruled, binding):** `haiku(1) < sonnet(2) < opus(3) < fable(4)`.
Recorded as a **rank registry**, not as prose naming models, so the rule stays evaluable when a
new model ships: a single table maps model class → integer rank; agents declare a class alias
(never a model ID, per #1122); the resolved model ID and its rank are written into the run
artifact. An unregistered model has **no rank** and therefore **cannot** satisfy any
class-differential requirement — fail-closed, not "assume highest".

**Two independent properties, never conflated:**

| Property | What it buys | What it does NOT buy |
|---|---|---|
| **Class differential** (rule 1) — a strictly-higher-class same-family checker | Depth: catches errors the lower class lacked the capability or thoroughness to catch | **Nothing against family-correlated blind spots.** Shared training distribution is unchanged by class. |
| **Cross-vendor diversity** (rule 2's "others") | Decorrelation: catches errors rooted in one family's shared priors | Nothing against thoroughness failures that any model makes reading a document as an argument |

This is not my framing; it is the repository's own recorded finding, and it must be quoted rather
than re-derived. `.claudetmp/design/research-findings-draft-2.md:46`: *"Neither substitutes… a
single deep reviewer remains exposed to its own family's blind spots — **which is why
author-exclusion still binds and why Fable must not become a substitute for cross-vendor
votes.**"* And `:52`: *"Reading this finding as 'use the strongest model' would be the wrong
lesson and an expensive one… depth and diversity fail differently, so a panel needs both,
allocated deliberately."* And the honest limitation at `:56`: Fable's demonstrated advantage is
**n=1 and confounded with running last** against a scaffold of seven already-known defects.

**Therefore, binding (restated in the §1a vocabulary — rev 3):** a same-family check at a
strictly higher class is **class-differential peer review**. It is *better peer review*; it is
**not independent review** and may never be recorded, counted, or reported as though it were.
Concretely: **class-differential peer review never substitutes for independent review**, and no
gate may satisfy an independent-review requirement with a same-family model.

**Definitions used throughout (rev 3 — these replace rev 2's "qualifying voice"):**
- **Peer review** of an artifact = a model of the same family as any author of that artifact,
  at any class. Subdivided only by quality: *same-class* peer review (rule (1) prohibits it from
  counting as a validating check) and *class-differential* peer review (rank strictly above the
  highest-ranked author — counts as a validating check, still not independent).
- **Independent review** of an artifact = a model of a **different vendor family** from every
  author, or **the human**. Only this satisfies rule (2)'s "input from others".
- **Deterministic checkers** (validators, gates, `change_classifier.py`) are neither peer nor
  independent review: they make no judgment, so they cannot carry rule (2). They are
  corroborating evidence — decisive for *triggering* review (AD-14), never a substitute for it.
  Where a rule is safety-critical, the strict reading governs.

Rules (1) and (2) are therefore conjunctive and orthogonal: rule (1) governs whether a *peer*
review counts at all; rule (2) governs whether *independent* review is present. Satisfying one
never satisfies the other.

### AD-3 (REV 2 — REPLACES REV 1) — Adversarial lens = `agy`; completeness lens = fable-class same-family. (BINDING)

- **Adversarial lens → `agy`** (cross-vendor). Unchanged in both revisions.
> ### AD-3 STATUS (rev 5): rank 4 **BINDS** — as the demonstrated configuration pending better evidence, not as an established requirement.
>
> **The budget premise is withdrawn (rev 5).** Rev 4 unbound this element on the report that a
> single fable-class pass consumed the weekly budget into overage. That pass was **a comprehensive
> audit of the entire codebase** — an outlier-scale task, not a signal about routine per-bundle
> passes, which are a small fraction of its scope. Actual utilization is **~9% of the weekly
> budget, ~91% headroom.** With the infeasibility premise gone, there is no material cost shift,
> so my CORE product-boundary rule is not engaged and this is mine to close rather than the
> human's. **CP-5 is withdrawn** and rev 4's three-option menu is moot — I record the correction
> in place rather than deleting it, because an ADR that silently erases a withdrawn premise
> teaches the next reader nothing about how the decision moved.
>
> **Bound: the completeness lens runs at rank 4 (`fable`) at FR2 frequency**, restoring the rev-2
> design. Two qualifications travel with it, and both survive the budget correction because
> neither was ever a cost argument:
>
> **(1) The reframe stands, and it is the more important finding.** Under rev 3's taxonomy the
> completeness lens is **peer review at every rank**, because it is same-family at every rank. The
> panel's **independent review is agy** regardless. So the lens's rank is a **peer-review quality**
> question, never an **independence** question — nothing in rule (2), AD-14's coverage guarantee,
> or AD-15's hold point depends on it. **The operational consequence is what matters: if
> utilization climbs later, stepping the lens down to rank 3 degrades quality only, and is an
> operator decision requiring no governance change, no ADR revision, and no human gate.** That is
> what makes this decision safely revisable rather than safety-critical, and it is why binding
> rank 4 now carries no lock-in risk.
>
> **(2) The n=1 caveat stands on its own evidentiary merits.** This was never a budget argument
> and is not dropped now that the budget argument is. The evidence for rank 4 *specifically*
> remains weak: **n=1, confounded with running last** against a scaffold of seven already-known
> defects (`research-findings-draft-2.md:56`), with the repo's own warning that reading it as
> *"use the strongest model"* is *"the wrong lesson and an expensive one"* (`:52`). The **strong**
> evidence is for the *distinct completeness framing* — the coverage prompt that found four
> `missing-scope` gaps — not for the rank of the model running it. **Therefore rank 4 is bound as
> "the demonstrated configuration, pending better evidence", not as an established requirement**,
> and any downstream document that restates it must carry that qualifier.
>
> **(2b) EVIDENCE UPGRADE — RESOLVED IN FAVOUR OF RANK 4 (rev 8).** The human settled the
> attribution of the **#972–#1002** batch: *"Fable did the audit. Opus did the issue filing. Fable
> made a doc that Opus worked from."* **Fable was the finder; opus-4-8 was only the transcriber.**
> Rev 7 laid out both branches in advance and this is the branch that **strengthens** AD-3: a
> **rank-4 same-family pass over sonnet-authored-and-reviewed code, yielding 31 substantive
> defects (self-bypassable CI approval gates, dead-code `require_tier_ceiling`, multiple
> fail-opens, the panel dropping all reviewer findings when the arbiter is unavailable), 30 since
> closed.**
>
> **The n=1 caveat is SOFTENED, not deleted, and the reason matters.** AD-3's evidence base is no
> longer a single confounded design-chain run — but this batch is **supporting rather than
> identical** evidence: it is a rank-4 pass over **code**, whereas AD-3's lens operates over
> **spec bundles**. Depth over code and depth over prose specifications are related but not the
> same task, and the transfer is an assumption rather than a demonstration. So: rank 4 remains
> bound as *the demonstrated configuration*, with materially better support than rev 5 had, and
> still short of a controlled result. The instrumentation in (3) remains the path to settling it.
>
> **Nothing binding moves.** The pass was same-family peer review, so it discharges no hold point —
> AD-11a(b) stands unchanged. This is a quality-evidence upgrade, not a compliance change.
>
> **(3) Instrumentation is a binding deliverable, not a nice-to-have.** Record **actual per-bundle
> completeness-lens consumption** in the AD-2 artifact header alongside the resolved model, rank,
> and `completeness_lens_class_differential` flag. Two questions become empirically answerable on
> real data instead of on extrapolation: *what does a routine pass actually cost?* and *does rank
> actually matter?* Both are currently unanswerable — the first is what produced the withdrawn
> premise above, the second is the n=1 problem. **Recommended operator thresholds** (defaults, not
> gates — adjust freely without touching this ADR): sustained weekly utilization **>50%** →
> consider stepping routine passes down to rank 3; **>80%** → step down and revisit here.

- **Completeness lens → same-family, rank set by policy (see AD-3 STATUS above); rank 4 where budget permits.**
  Permitted by revised rule (1): the bundle's highest-ranked authors are Opus (rank 3, VF-9), so
  rank 4 is a strict differential. Permitted by rule (2): agy participates in the same panel, so
  the completeness lens is never sole. **This reproduces exactly the configuration that produced
  the demonstrated result** — a fable-class completeness pass running alongside agy over an
  Opus-authored bundle (`.claudetmp/design/fable-consistency-check.md`). Revision 1 reassigned
  this lens to codex *only* because the old rule forbade it; with the rule revised, keeping the
  demonstrated configuration is the correct call. ~~and costs nothing to justify~~ — **rev 4
  correction: it does not cost nothing.** That clause was written before the budget evidence and
  is withdrawn — the run is affordable at ~9% weekly utilization, but "costs nothing" was never
  a claim I had evidence for and should not have been written.
- **Rank is computed against the artifact and RECORDED — not used to refuse the run (rev 4).**
  The script computes the highest author rank for the bundle from the agent registry, compares it
  to the lens's resolved rank, and writes the result into the AD-2 artifact header as
  `completeness_lens_class_differential: true|false`. **It does not refuse a same-class run**,
  because AD-3's operator step-down (rank 3 routine completeness under budget pressure) must stay
  available without a code change — a hard refusal would convert a quality decision back into a
  governance one. What it must never do is let a same-class run be
  *counted* as a class-differential validating check: the flag exists precisely so the
  distinction is measurable rather than assumed, and so the research record can later ask whether
  rank actually mattered (which the n=1 evidence cannot currently answer). If
  `pm-agent`/`architect`/`technical-design` are ever promoted, the flag flips automatically — no
  special-casing.
- **Fallback order on completeness-lens unavailability:** cross-vendor `codex` (always satisfies
  both rules), **never** a rank-3-or-lower same-family model. See AD-7 for when the panel may
  proceed at all.
- **Resolves revision 1's CP-1 in full.** codex returns to reserve status: it is no longer fired
  by the spec phase, so the D4/D5 "scarcity is intentional… not a high-frequency tool"
  invariant (`run_second_review.sh:17-21`) stands unamended. The cost-model conflict revision 1
  escalated is withdrawn.
- **Reference vendors and classes by role/alias, never by model ID.** Frontmatter carries a class
  alias; resolved IDs are recorded at runtime in the AD-2 artifact header (#1122). A pinned ID
  here would inherit precisely the staleness defect #1122 exists to remove — and under rev 2 it
  would additionally break the rank computation, since rank is a property of the class.
- **Configurable, one-way:** `OVERSIGHT_SPEC_ADVERSARIAL_CLI` / `OVERSIGHT_SPEC_COMPLETENESS_MODEL`
  may retarget a lens only to a target that still satisfies AD-10 for the artifact at hand. They
  may not set both lenses to the same model, may not disable a lens, and may not select an
  unregistered (rank-less) model. Enforced in `run_spec_panel.sh`, fail-closed, per the
  HOS#985 anti-tamper rule.
- **Still reject the `run_second_review.sh` agy→codex fallback shape.** One model running both
  prompts is not a degraded dual-lens; it is a single-lens gate wearing a dual-lens verdict.
- **VF-6 exception still recorded.** The spec-phase lens↔vendor mapping remains deliberately the
  inverse of D4 / `run_second_review.sh:11-21` / `validate_agents.sh:15-17`; AD-12's DECISIONS
  entry carries the note so a later consistency sweep cannot silently swap the lenses.

### AD-11 — Inner-loop blast radius: `class(code-reviewer) > class(coder)` becomes a checked invariant, and independent-voice coverage becomes unconditional. (BINDING — rev 2)

**This is the largest consequence of the rule change and it lies entirely outside the spec panel.**
Verified: `coder`, `code-reviewer`, `security-reviewer`, `privacy-reviewer`,
`reliability-reviewer`, `ops-reviewer`, `ui-reviewer`, `a11y-reviewer`, `infra-reviewer`,
`unit-test`, `system-test`, and `risk-assessor` all pin `claude-sonnet-4-6`. The author and every
inner-loop reviewer are same family **and** same class — under revised rule (1) the entire
inner-loop chain is same-class self-validation, the prohibited case. It is currently rescued only
where a genuinely independent review exists, and `run_second_review.sh` fires agy only at
MEDIUM+ (0.30) and codex only at HIGH+ (0.55).

**Ruling, in three parts. All three are definition-independent — they hold under any resolution
of AD-13, so they bind now and must not wait on it.**

> ### AD-11a STATUS (rev 6): **PERMANENTLY WITHDRAWN — resolved on the merits.**
>
> **The human settled the prohibition clause (2026-07-31), verbatim:**
> > *"Same agent instance for sure. Different instance (no shared memory) same model good for
> > routine / not hold point work."*
>
> So *"opus can't validate itself"* turns on the **agent instance**, not the model:
> - **Same agent instance validating its own output** → prohibited.
> - **Different instance, no shared memory, same model** → acceptable for **routine peer-review**
>   work.
> - **Not sufficient for hold-point work** — see AD-11a(b) below, which is the load-bearing half.
>
> **AD-11a is withdrawn, not deferred.** `coder` and `code-reviewer` are different instances with
> no shared memory, and code review is routine peer-review work rather than a hold point.
> Therefore **no class differential is required and `code-reviewer` stays rank 2 (`sonnet`)** — a
> positive resolution on the merits. Rev 5's "reinstatement is one line" hedging is dropped, along
> with the caveat that my permission-clause reading did not reach the prohibition clause: the
> human has now reached it directly, and it lands on the same answer.
>
> **AD-11a(b) — the "not hold point work" clause, and why it matters more than the withdrawal.**
> It independently confirms AD-10's cross-vendor rule **with direct human authority rather than as
> my inference.** At a hold point, same-model-different-instance does **not** discharge the
> requirement on its own. Applied to the spec panel — a hold point per AD-15 — this yields the
> sharpest available statement of the rule:
>
> > **The completeness lens is same-family peer review, so it cannot by itself discharge the spec
> > panel's hold point. The hold point is discharged because agy — cross-vendor, genuinely
> > independent — is also present, which AD-7 and AD-14 guarantee. A fable-class lens running
> > alone at a hold point would be NON-COMPLIANT, at any rank.**
>
> This is now the canonical formulation of "class-differential peer review never substitutes for
> independent review" (AD-10) and of "a class-differential voice may never reduce a gate's
> cross-vendor count to zero." `technical-design` should quote *this* sentence in the agent
> charters and the contract, in preference to the more abstract rev-3 phrasing. It also retroactively
> vindicates AD-3's rank decision being safely revisable: since rank never discharges the hold
> point, stepping the lens down to rank 3 cannot break compliance — only quality.
>
> **Rev-4/5 reasoning retained below** because it independently reached the same result from the
> permission clause, and because it explains why `code-reviewer`'s lane was never a coverage risk:
>
> 1. **Rule (1) is phrased as a permission, not a requirement.** The human's words — *"allow same
>    model family but higher model (eg if sonnet did work, opus **can** check)"* — grant that a
>    class-differential same-family check **may count** as a validating check. They do not require
>    every same-family review to carry a differential. Rev 2's AD-11a read the rule as mandatory
>    ("the entire inner-loop chain is the prohibited case") and that reading does not survive
>    contact with rev 3's taxonomy.
> 2. **Under §1a, `code-reviewer` is unambiguously peer review** — the lane the human explicitly
>    designated as same-model-by-design and cost-optimized, guarded by no-shared-memory +
>    adversarial instruction. It never claimed to be the independent check, so it was never
>    substituting for one. Rule (1) was formulated for *validation/decisions*; if it scopes to
>    independent review only, AD-11a dissolves and `code-reviewer` stays rank 2 at **zero cost**.
>
> **(Rev-5 note, now settled.)** The revised rule has a **permission clause** (*"opus can check"*)
> and a **prohibition clause** (*"opus can't validate itself"*). The reasoning above reached only
> the permission clause; the prohibition was resolved separately by the human in rev 6, on the
> instance reading, converging on the same outcome.
>
> **Withdrawal opens no safety hole**: the coverage property is carried entirely by **AD-11b** and
> **AD-14** (independent review triggered by classification ∪ deterministic tier floor), neither
> of which references `code-reviewer`'s class. AD-11a was a peer-lane *quality* improvement, not a
> coverage guarantee — which is precisely why the instance reading can dispose of it without
> weakening anything.
>
> **The ambiguity for the human to settle** — *"opus can't validate itself"* means which?
> (a) the same **model**, or (b) the same **agent instance checking its own output**? `coder` and
> `code-reviewer` are the same model but **separate invocations with no shared context**, which is
> already §1a's no-shared-memory guardrail. If the intended meaning is (b), AD-11a is unnecessary
> and should be formally withdrawn. If (a), AD-11a is reinstated subject to CP-4.
>
> **If the human does want a differential in the peer lane, it must escalate on deterministic
> signals only** — protected-surface touch, deterministic tier floor ≥ MEDIUM, or a convergence
> failure (which `oversight-evaluator` already detects). **Never on reviewer self-confidence.**
> A blind spot produces a *clean* review, so "escalate when the reviewer finds nothing" inverts
> the incentive and rewards shallow reviewing. This is not a new principle here — it is
> `DECISIONS.md` **D51** (agent-declared confidence is excluded from automated routing), and a
> confidence-triggered escalation would contradict it directly.
>
> The text below is **retained as the rev-2 record of what was decided and why**, so a
> reinstatement does not have to re-derive it. It does not bind while suspended.

**AD-11a (SUSPENDED — rev-2 text retained) — `class(code-reviewer) > class(coder)`, enforced statically.** Promote `code-reviewer`
to rank 3 (`opus`) while `coder` is rank 2 (`sonnet`), and encode the *relation* — not the
literal classes — as a static check in `scripts/framework/check_agents_static.sh`, which already
exists to catch exactly this class of drift. Rationale: this is the cheapest change that makes
rule (1) true rather than merely asserted. `code-reviewer` is the one mandatory lane at every
tier, so one promotion covers every step; promoting all eleven reviewers would multiply
inner-loop cost by roughly an order of magnitude for a property only the mandatory lane needs to
carry. The specialist lanes stay at rank 2: they are never sole (code-reviewer plus the
independent review plus deterministic gates always accompany them), and AD-10 already forbids
counting them as satisfying anything. Encoding the *relation* statically is what prevents the
obvious future regression — someone promotes `coder` to Opus for capability reasons and silently
re-creates same-class self-validation. **Fold this into #1122's alias refresh**: it touches the
same frontmatter in the same files, and doing it separately churns 30 agent files twice.
`overseer` (rank 3) already satisfies rule (1) over rank-2-authored code at the merge decision —
note it, do not change it.

**AD-11b — independent-voice coverage must be unconditional, so no same-family judgment can
exclude it.** The sharp failure the coordinator identified is not "LOW risk gets less review";
it is **same-family models deciding they do not need outside input**. The structural fix is to
remove the decision, not to police it: there must exist at least one **independent** voice
(AD-10: different vendor family, or the human) on the path to merge at **every** tier including
LOW, so the question
"does an independent review fire?" has no path that answers *no*.
- At MEDIUM+ this already holds deterministically and is **not** exploitable: any
  `.py`/`.js`/`.ts`/`.jsx`/`.tsx` change floors at MEDIUM via `TIER_FLOOR_APP_CODE`, and
  evaluator condition 11 FAILs a self-reported tier below that floor (VF-10). A same-family chain
  cannot self-declare its way below agy on application code.
- At LOW the independent review is **Copilot**, which D16:79 already designates as the non-Claude
  floor reviewing *every* PR including those the local panel skips (`run_panel.sh:369`). This is
  a legitimate answer, but today it is an **assumption stated in a decision log, not a verified
  precondition**. Bind: *Copilot PR review being enabled on the repository is a checked
  precondition of rule-(2) compliance at LOW.* If it is not enabled, LOW-tier work has **no**
  independent review and violates rule (2) outright. `technical-design` specifies where this check
  lives (the `validate_setup.sh` / framework-setup-validator family is the natural home) and what
  it does on failure.
- **Bounded, documented exception — narrowed by AD-14 (rev 3).** Copilot is post-PR, so an
  inner-loop sign-off in the exception window is peer review only at the moment it is written;
  independent review arrives at PR time. This is acceptable **only** because no merge can occur
  before that point, and it is recorded as an exception with that reasoning rather than left as
  an unstated gap. **AD-14 shrinks the window from "all LOW-tier work" to "LOW-tier `clarifying`
  work only"** — changes that by FR2's definition introduce, alter, or remove no observable
  behavior. Everything `additive` or `structural` now gets local independent review at every
  tier, so the cure CP-4 asked about is no longer needed.

**AD-11c — VF-10's residual surface is prose, and that is this repo's product.** Because
`TIER_FLOOR_APP_CODE` matches only code extensions, `.md` changes floor at LOW — so agent
charters, `contract/OVERSIGHT-CONTRACT.md`, `AGENTS.md`, and methodology docs are exactly the
artifacts on which a same-family chain *can* avoid the independent review. That is the governance
logic of the system governing itself with no outside voice, and it is the same phenomenon the
repo already filed as #1079 (*the artifacts that govern code get less review than code*). I am
**not** ruling a floor change here — extending `TIER_FLOOR_*` to `.md` would raise the tier of
every doc typo and is a change with its own cost profile that belongs to its own work item.
I am ruling that this is a **named, filed gap**: open an issue linked to #1079 and this ADR,
carrying VF-10's evidence. It is also the strongest argument for AD-13 landing on the strict
reading, and `technical-design` should not design as though it will land loosely.

### AD-4 — Taxonomy reconciliation is IN SCOPE. One canonical set; the contract owns it. (BINDING)

Confirmed pm-agent's read. FR4 rewrites that exact schema; leaving two conflicting lists in one
file while adding a third consumer would be negligent.

**Canonical `Gap type` values (single token, kebab-case, machine-parseable):**

| Value | Meaning | Typical lens |
|---|---|---|
| `contradiction` | Two requirements conflict under some condition | adversarial |
| `gaming-vector` | The rules can be exploited without technically being violated | adversarial |
| `implicit-assumption` | Something assumed but never stated | adversarial |
| `missing-edge-case` | A boundary condition inside an addressed area is unhandled | adversarial |
| `ambiguity` | Stated, but admits more than one implementation reading | either |
| `missing-requirement` | A specific requirement absent **within an area the bundle does address** | either |
| `missing-scope` | **An entire area the bundle never addresses at all** (incl. silent contradiction of an existing repo doc, an inert output, an unmigrated instance of the rule being formalized, an absent lifecycle story) | completeness |

`missing-scope` is new and is the #1059 finding class — all four completeness findings were this.
The `missing-requirement` / `missing-scope` boundary is **"is the area addressed at all?"**; that
test must appear verbatim in both agent files, or the two lenses will file the same finding under
two types and the provenance data is worthless.

**Bindings:** the canonical list's single source of truth is
`contract/OVERSIGHT-CONTRACT.md` (both agents and any future consumer reference it — a shared
schema does not live inside one of its consumers). Both `spec-red-team.md:83` (the
`gh issue create` body) and `spec-red-team.md:105` (the required-fields block) are rewritten to
the canonical set; the new agent uses the identical block. Every spec-gap issue additionally
carries **`Lens: adversarial | completeness`** (FR4) — one value, never both; the same finding
independently raised by both lenses is filed once with the first lens recorded and a
`Corroborated-by:` note, so the provenance metric measures *disjointness*, which is the entire
research value of the pair.

### AD-5 — FR8 lands in overseer step 4a as a bounce condition, NOT as an evaluator Phase-1 extension. (BINDING)

**This is the decision that implements human decision 2, and the mechanism already exists.**

`contract/OVERSIGHT-CONTRACT.md:542` and `overseer.md:228-231,277-284,441` define a **pre-merge
bounce**: post a comment with structured rationale → assign to `hos-worker-hos[bot]` → apply
`needs-ai` → convert PR to draft → append a `pr-bounced` audit event; the PR **stays open**, and
it is explicitly **not a task failure** (`worker.md:278`). `worker.md:270-278` already defines
re-entry after a bounce. That is, line for line, the human's requirement: *"Reject means it goes
BACK to worker with explanation and worker gets chance to fix. It is not closing the PR."*

**Rationale for the placement:**
1. **The evaluator has no return-to-worker disposition.** Its verdict vocabulary is
   PROCEED / CONDITIONAL_PROCEED / ESCALATE; every non-proceed path terminates at a human. Putting
   FR8 there produces exactly the outcome the human rejected ("escalation just makes more human
   work and slows things down").
2. **FR8's stated job is a backstop for PRs that reached merge without passing the evaluator.**
   Implementing a backstop *inside the thing being backstopped* is a null change.
3. **Bounce carries the correct non-semantics.** It is distinguishable from close/abandon (PR stays
   open, draft) and from escalate-to-human (assigned to the worker, `needs-ai`, not `needs-human`).
   No new disposition needs inventing — inventing one would create the parallel mechanism FR5
   explicitly forbids.

**Reconciliation with `overseer.md:410` ("errs toward escalation, never toward auto-merge").**
No contradiction, and the invariant is not weakened, for two reasons that must be written into
`overseer.md` rather than left implicit: (a) the invariant governs the *auto-merge* boundary — a
bounce never merges anything, so it never errs toward auto-merge; it is strictly more
conservative than proceeding. (b) A missing-spec-artifact finding is **deterministic and
worker-remediable** (an artifact either exists or does not), whereas escalation is reserved for
**ambiguous risk judgment** that only a human can settle. (c) The existing per-cid cap is
retained unmodified: `bounce_count(cid) >= 2` → HUMAN_REQUIRED (`overseer.md:230,266`). So the
escalation invariant is preserved *through the cap* — a worker that disputes the classification
twice reaches the human automatically, and the worker may escalate immediately at any point if it
disagrees. That cap is the loop-exit; **`technical-design` must not add a separate counter**
(`overseer.md:271` already forbids one for out-of-scope bounces — same rule here).

**Bindings:**
- Add one bounce condition to overseer step 4a with `check_id: SPEC-PHASE-MISSING`.
- **Do not extend the `reason_category` enum.** Use the existing `COMPLIANCE_FAILURE`
  (`contract/OVERSIGHT-CONTRACT.md:429`; enum semantics at `overseer.md:284` — "a concrete
  compliance/register check failure (the specific `check_id`(s) appear in the audit event's
  `failures` field)"). The check_id already carries the specificity; `SPEC_AMBIGUITY` means
  something else entirely and must not be repurposed. Enum extension is a contract schema change
  with unknown downstream parsers — unjustified for zero added information.
- **Detection reuses `change_classifier.py --structural-only`. No detection logic is written.**
  Condition: `structural_signals` non-empty AND no AD-2 spec-panel artifact covering the step.
  Follow the established fail-closed convention when the classifier is unavailable
  (`SPEC-83:64`, `oversight-evaluator.md:303`): assume the condition is TRUE and say so in the
  output.
- **Artifact-existence check (FR8's genuinely new part).** Contract §7 condition 10 checks for a
  *human-authorization* artifact; this checks for a *spec-phase* artifact. Acceptance order:
  (1) the AD-2 panel artifact for the step — the only sufficient evidence, since it proves both
  lenses ran; (2) a technical-design doc **plus** open/closed `spec-gap` issues for the cid —
  accepted only as grandfathering for work predating this ADR's ship commit, mirroring the
  SPEC-267 grandfathering pattern at `contract/OVERSIGHT-CONTRACT.md:534`.
- **Exemption audit (FR8 part 2).** A PR claiming an FR2 exemption (`fix:`/`chore:` framing) must
  cite an artifact or defect report; the overseer verifies the citation **exists**, **predates
  the branch point**, and **covers the diff's scope**. Scope-overlap uses the SPEC-267
  canonicalization rules verbatim (`contract/OVERSIGHT-CONTRACT.md:534`; evaluator steps 1–4):
  exact-match, no prefix/basename/directory-containment matching. Behavior beyond cited scope
  invalidates the exemption → bounce. **Reuse those rules; do not restate them with variations.**
- **Mislabel telemetry (FR8 part 3) is a loggable finding, non-blocking.** New audit event
  `spec-phase-missing` (register it in `contract/OVERSIGHT-CONTRACT.md` §6a alongside
  `structural-override` / `na-invalidated` / `tier-floor-mismatch`), payload:
  `pr`, `cid`, `step`, `structural_signals[]`, `artifact_found` (bool), `claimed_exemption`
  (string|null), `citation_valid` (bool|null), `disposition` (`bounced | passed | mislabel-logged`).
  Emit it **even when `disposition: passed`** — the passed-vs-bounced ratio is the escaped
  mislabel rate, exactly as `structural-override` is emitted when `covered: true`
  (`oversight-evaluator.md`, §6a rationale). Without the passing case there is no denominator and
  the metric is unusable.
- **Ordering is halt-on-failure and mirrors the existing protocol** (`overseer.md:256-260,441`):
  post comment → confirm posted → append audit event → finalize (assign, `needs-ai`, draft).
  Never write an event for a comment that did not post.
- **VF-3 constraint:** the overseer executes this as prose, consistent with the rest of the bounce
  protocol. `technical-design` must not write `record_pr_bounce(...)` as a function call.

### AD-6 — FR2 trigger: hoist the existing classification rule to a mode-independent section. No new triage mechanism. (BINDING)

The FR2 trigger is evaluated by the rule currently at `worker.md:224` — but that rule must move
out of the AUTONOMOUS-only chain (VF-4) into a section binding on **both** modes. `worker.md:63`
("Scope guard (both modes)") is the existing precedent for a mode-independent block; put the
pipeline-discipline + FR2 trigger rule adjacent to it and have both mode sections reference it
rather than restating it. Restating it twice guarantees the two copies diverge.

- FR2's classification test, the operational citation test, and the two exhaustive exceptions are
  transcribed verbatim from the requirements; the explicit non-exemptions ("it's small", "it's
  LOW risk", "it only tightens governance", "high confidence") are retained verbatim — they name
  the #556 failure mode by its actual rationalizations.
- **`triage.py` is not touched.** It classifies for autonomy/security-report routing, a different
  question; making it the FR2 trigger point would be the new mechanism FR2 forbids.
- `worker.md:229`'s "Pre-coder gate (mechanical) … does not yet exist" note is superseded in part
  by AD-8 and must be updated in the same change — leaving a stale "no mechanical gate exists"
  claim next to a mechanical gate is precisely the silent-doc-contradiction class the
  completeness lens was created to catch.
- FR6 (worker runs the panel directly in both modes) follows from AD-2: the worker invokes
  `run_spec_panel.sh`. The **forward constraint** is recorded here for the future
  worker-sandboxing initiative: *any sandboxing of the worker must preserve its ability to invoke
  `run_spec_panel.sh` and the underlying vendor CLIs; stripping model-invocation capability would
  silently disable this gate.* File it as a tracked constraint, do not solve it here.

### AD-7 (REV 2 — REPLACES REV 1) — Outage posture keys on sole-same-family, not on vendor availability. (BINDING)

Human-approved in rev 2, superseding rev 1's blanket "any lens model unavailable → hard failure".
The failure condition is **not** *"is vendor X down?"* but *"would proceeding leave a single
same-family voice deciding alone?"*

- **≥2 independent participants remain** (AD-10: at least one independent reviewer — different
  vendor family, or the human — plus at
  least one other participant) → **proceed**, and record in the artifact header which participant
  was absent and why. Absence is logged, never silent.
- **Proceeding would reduce the decision to a sole same-family voice** → **hard failure**,
  non-zero exit, explicit human bypass required.
- **Runtime errors are treated as absence, not as approval.** Per
  `contract/OVERSIGHT-CONTRACT.md:544-546`, a timeout/rate-limit/crash after a successful
  pre-check must never collapse into `approve`; it either logs as an absent participant (if the
  remaining set still satisfies the rule) or hard-fails (if it does not).
- **Human bypass artifact** (unchanged from rev 1): `.claudetmp/oversight/spec-panel-bypass.md`,
  in the same human-only class as `human-authorization.md` / `human-tier-override.md`
  (`contract/OVERSIGHT-CONTRACT.md:85-93`) — agents may read it, never create or modify it.
  Register it in the contract artifact table (`step`/`cid`, reason, scope, expiry) and emit an
  audit event when a bypass is consumed, so bypasses are countable.

**Two consequences `technical-design` must implement correctly, because the rule reads
differently than it sounds:**

1. **For the spec panel specifically, this is less of a relaxation than it appears.** The panel's
   participants are the adversarial lens (agy, independent), the completeness lens (fable-class,
   *qualifying but not independent* per AD-10), and the Claude resolvers downstream. If **agy** is
   absent, everything remaining is same-family → **hard fail**. If the **completeness lens** is
   absent, agy remains, so rule (2) is satisfied — but **FR1 makes the dual lens unconditional**,
   so the panel still cannot report a valid dual-lens verdict. That is an FR1 failure, not a
   rule-(2) failure, and only the human can re-scope FR1. Net: both lenses remain effectively
   mandatory for this gate. The correct implementation records *which* rule blocked, because the
   two have different owners and different remedies — collapsing them into one "panel failed"
   message destroys that information.
2. **The relaxation is real and valuable elsewhere in the pipeline**, which is where it should be
   applied: e.g. codex absent at HIGH+ while agy is up no longer needs to block, because
   independent review remains present. That is a change to `run_second_review.sh`'s fail-closed
   logic. **Rev-3 revision: this moves back IN scope.** AD-14 already opens that script and
   rewrites the very branch that decides when review is mandatory (`:249-260`). Touching the same
   fail-closed logic twice, in two work items, is how the two rules end up inconsistent — apply
   both in one change. The rule there becomes identical to the one above: an absent vendor is
   logged as an absent participant while independent review remains present, and hard-fails only
   when proceeding would leave peer review alone.

**CP-2 from revision 1 is withdrawn.** It warned that a codex outage would block all feature work.
Under AD-3 (rev 2) codex is no longer on the spec-phase path at all, and under this posture a
single-vendor outage is non-blocking wherever an independent review remains. The concern is
resolved on both axes.

### AD-13 — **"Decision" ≡ "hold point". ACCEPTED BY THE HUMAN (2026-07-31). BINDING.**

Rule (2)'s scope is settled. **A "decision" for the purposes of the never-sole rule is a
hold point** — nothing broader, nothing vaguer.

> **The rule, in final form:** *At every **hold point**, at least one **independent reviewer**
> (different vendor family, or the human) must participate. Routine work is unconstrained beyond
> the peer-review guardrails (§1a: no shared memory / no author framing, plus adversarial
> instruction).*

**Why this closure is better than any definition I could have drafted, and why it should be
defended if someone later proposes to "improve" it:** it makes the predicate **structural rather
than semantic.** A hold point is a *named phase boundary* — enumerable, greppable, checkable by a
script. Every enforcement failure this ADR uncovered came from a semantic gate that nobody could
mechanically check: **VF-1** (an agent documented as a pipeline stage with no caller), **VF-2** (a
gate field with no enforcer), **VF-3** (a bounce API cited in four design docs and never written).
A definition of "decision" phrased as a judgment test — *"any point where an artifact's state
advances past a gate"* — would have joined that list. This one cannot, because you can enumerate
the hold points.

**Implementation impact: none.** AD-14 already enforces exactly this rule mechanically
(independent review fires on classification ∪ deterministic tier floor), and AD-15 already
establishes the spec panel as a hold point. Acceptance deletes an open question rather than adding
work. `technical-design` should, however, ensure the **set of hold points is written down
explicitly** — in `contract/OVERSIGHT-CONTRACT.md` — rather than left implicit across agent
charters. An enumerable predicate that is never actually enumerated degrades straight back into a
semantic one, which would forfeit the entire benefit of this closure.

**Consequential note for the contract:** the spec panel (AD-15) is a hold point. The pre-PR second
review and the merge gate are the other candidates; naming them is a contract-drafting task, not
an architecture question, so `technical-design` proposes the list and I confirm it.

Rule (2) ("a same-family voice may never be the sole input to a decision") cannot be enforced
until "decision" is defined, and the human wants to settle it conversationally. **No part of this
ADR depends on the outcome** — AD-11a/b/c were deliberately constructed to hold under any
resolution — so `technical-design` proceeds without it. Recorded here so the open question is
tracked rather than lost, with the boundaries I can already fix:

- **The panel lenses are not decision points.** They file `spec-gap` issues; they decide nothing.
  Rule (2) does not engage at the lens layer. It engages first at **`pm-agent`'s
  `Ready for coder: YES`** resolution (AD-8), which is a same-family judgment resolving findings
  from both lenses — satisfied while agy participates, violated if agy is absent (which AD-7
  already hard-fails).
- **The strict reading is the one to design toward.** The coordinator's framing — *same-family
  models deciding they do not need outside input* — is the sharpest available statement of what
  rule (2) exists to prevent, and VF-10 shows the loophole is not hypothetical: on `.md`
  artifacts the whole chain is same-family and nothing deterministically forces an independent
  voice. If AD-13 lands near that reading, **tier assignment becomes a governed decision point**,
  not just merge authority. AD-11b is already built for that outcome (it removes the exclusion
  decision rather than policing it), so that landing requires no rework here.
- **A ratchet-only determination is arguably not a rule-(2) decision at all.** A judgment that can
  only move in the oversight-increasing direction and is bounded below by a deterministic floor
  cannot loosen anything, and HOS already spends verification cost *only in the loosening
  direction* (`contract/OVERSIGHT-CONTRACT.md:540`, conditions 9–11). Offered as input to the
  human's discussion: scoping rule (2) to **loosening** decisions would keep it enforceable and
  consistent with existing doctrine. The counterexample the human should weigh is exactly the
  loophole above — *declining to raise* a tier is formally ratchet-compliant yet is the very act
  that excludes the independent review.

### AD-8 — Close the FR5 enforcement hole with a deterministic pre-coder check. (BINDING)

VF-2 means FR5 cannot be satisfied by documentation. The uniform gate stays exactly as FR5
specifies — `Ready for coder: YES` on every open spec-gap issue from both lenses — but it
acquires an enforcer.

- A deterministic check runs immediately before coder dispatch (worker chain step 8, both modes):
  query open `spec-gap` issues for the step/cid; if any lacks `Ready for coder: YES`, **refuse to
  dispatch coder** and report which issues block. Additionally require the AD-2 panel artifact to
  exist with a non-`error` verdict.
- Implement it as **executable code**, not prose — the natural home is the existing pre-dispatch
  gate family (~~`scripts/automation/lib/pr_readiness.py` is the established pattern~~ — **rev 8
  correction: that file DOES NOT EXIST** (TD-VF-1); the real established pattern is
  `scripts/oversight/signoff_gate.py`, and the enforcer is `scripts/oversight/spec_gate.py`.
  Pattern: exit 0 = pass,
  non-zero = do not proceed, `worker.md:8.9`). `technical-design` picks the exact module; the
  binding is that it is executable and returns a non-zero exit, because VF-1/VF-2/VF-3 are three
  independent demonstrations that prose gates in this repo do not run.
- `pm-agent.md` gains the resolver side (it sets `Ready for coder: YES` after resolution, with a
  human approval link required for `structural`) — today `pm-agent.md` never mentions the field.
  Keep the existing `docs/AGENTS.md:277` rule intact: a spec-gap issue pm-agent judges technical
  or architectural in scope requires `architect` confirmation before pm-agent resolves it.
  That rule now covers **both** lenses; `missing-scope` findings will frequently be architectural.

### AD-9 — FR1: removal of the adversarial-only mode. (BINDING, confirmatory)

Accepted as specified. Dual-lens is unconditional whenever the spec phase runs; work that would
have qualified for a lightweight single-lens pass is by definition `clarifying` and skips the
spec phase entirely.

**Architectural consequence, restated for rev 2:** because FR1 admits no single-lens mode, FR1 —
not the independence rule — is what keeps both lenses mandatory for this gate. AD-7's revised
posture would otherwise permit proceeding when the completeness lens is absent (agy still
supplies an independent review). So the two gates are now sourced from different rules with
different owners: **agy absent → rule (2) violation → hard fail (my call, binding); completeness
lens absent → FR1 violation → blocked unless the human re-scopes FR1 (pm-agent/human call).**
Rev 1 recorded this coupling as CP-2, which is now withdrawn — under AD-3 rev 2 the completeness
lens is a Claude-family model, so its "outage" is coextensive with Claude being unavailable, in
which case no agent in the pipeline is running anyway. The scarce-vendor hard dependency that
made CP-2 worth raising no longer exists.

### AD-14 — Independent review is triggered by phase boundary and change classification, never by a self-assessed risk tier. (BINDING — rev 3)

**The governing principle, stated once and binding everywhere:**
> **Independence coverage is triggered by phase boundaries and change classification. A
> self-assessed risk tier may scale independence *intensity*; it may never reduce independence
> *coverage* to zero.**

This is AD-11b's graduated-independence principle applied to the back gate (`run_second_review.sh`)
rather than only the front gate (the spec panel). It closes the last tier-gated independence
point in the pipeline.

**Why the swap is sound — the asymmetry that makes it work.** Change classification has an
**independent mechanical re-derivation**: `change_classifier.py` §2a structural-override
signatures force `structural` regardless of the author's label
(`contract/OVERSIGHT-CONTRACT.md:155-165`), the evaluator re-derives it pre-PR (condition 10), and
AD-5 audits claimed exemptions at merge. Self-assessed tier has no equally strong check where it
matters most: the tier floor's path rules cover code but not prose (VF-10), so at LOW on a `.md`
change a self-assessed tier was effectively unaudited. Trading an audited trigger for an
unaudited one is the whole improvement. **Under the §1a framing this also repairs the managerial-
independence gap where it bites hardest:** the orchestrator can no longer decide, via a
self-assessment, that independent review is unnecessary.

**Mapping — a UNION, not a replacement. This corrects the interpretation forwarded to me.**

> **Independent review fires iff** `classification ∈ {additive, structural}` **OR**
> `deterministic tier floor ≥ MEDIUM`.
> **Intensity** then scales with the deterministic tier floor: agy whenever it fires; codex
> additionally at HIGH+ (`OVERSIGHT_CODEX_THRESHOLD`, unchanged).

The forwarded interpretation ("classification gates *whether*, tier scales *how much*") read
literally would make classification the **sole** trigger — which **removes** independent review
from a case that has it today and must keep it: **a high-risk bug fix.** pm-agent's own FR2
rationale says a "one-line HIGH-risk auth bugfix… should get full code review but skip the spec
phase." Such a change is `clarifying` (defect correction restoring behavior an approved artifact
already requires — FR2 exception 1), so a pure-classification trigger would fire no independent
review on it at all, while today it gets agy at MEDIUM+ and codex at HIGH+. That is a loosening
of a safety-critical rule, which I may not accept. The union preserves every trigger that exists
today and adds the new one. **Classification and tier are both floors; neither may veto the
other.** I am confident this is what was intended — the stated aim was to close a coverage hole,
not open a different one — but it is a substantive correction to the instruction as written and
is flagged for the human accordingly.

**Bindings:**
- The tier input to this decision is the **deterministic** floor
  (`change_classifier.py --tier-floor`, and the `run_validators.sh` composite), **never**
  `risk-assessor`'s self-reported `validated_tier`. That is the literal content of "never by a
  self-assessed risk tier". Where the two disagree, evaluator condition 11 already fails closed.
- The classification input must be the **post-re-derivation** classification (after §2a
  structural-override), never the authoring agent's raw self-label.
- The existing `OVERSIGHT_AGY_THRESHOLD` / `OVERSIGHT_CODEX_THRESHOLD` knobs survive as
  **intensity** controls only. The HOS#985 anti-tamper clamp still applies, and it now needs a
  companion: **no env value may suppress the classification trigger**, or the self-skip attack
  HOS#985 closed reopens through a different door.
- `clarifying` changes below the MEDIUM floor still receive no *local* independent review; the
  independent review for those remains Copilot at PR time (AD-11b). This is the residual
  exception and it is now much narrower than rev 2's — see below.
- Update the `run_second_review.sh` header comment block, which currently documents pure
  tier-gating (`:11-21`, `:249-253`) and would otherwise describe behavior the script no longer
  has.

**Consequences for earlier decisions:**
- **CP-4 bullet 2 is resolved**, and better than either option I offered. I asked whether to
  accept the LOW-tier bounded exception or fund `OVERSIGHT_AGY_THRESHOLD → 0`. The human's
  answer is cheaper than the knob *and* stricter than the exception: agy now fires on every
  `additive`/`structural` change at any tier, while `clarifying` changes below MEDIUM still do
  not pay for it. The residual AD-11b exception narrows from "all LOW-tier work" to "LOW-tier
  `clarifying` work only" — i.e. changes that by FR2's definition introduce, alter, or remove
  **no** observable behavior. That is a defensible remainder.
- **AD-11c (the `.md` tier-floor gap) becomes non-load-bearing for independence but is NOT
  resolved.** A same-family chain self-declaring LOW on a markdown change can no longer thereby
  exclude independent review, because classification now triggers it. The tier floor is still
  wrong for markdown — it under-states risk for every *other* tier-gated consumer (reviewer-set
  selection, human-gate firing, suspension rules). **#1079 stays open; do not close it against
  this ADR.**

### AD-15 — The spec panel is a HOLD POINT. **CONFIRMED BY THE HUMAN (2026-07-31). BINDING.**

The spec panel is a **hold point** in the §1a sense: verification is mandatory at the phase
boundary and work **stops** until it clears. FR5's `Ready for coder: YES` is the sign-off; the
coder is the traveller that cannot advance past it.

**Human's reasoning, recorded verbatim because it is an economic argument and not a procedural
preference** — this is the sentence a future reader should find when they ask why the coder is
blocked rather than merely warned:

> *"Spec panel is hold point. Work could be invalidated, so don't start until we know specs good."*

That is **rework avoidance**: the stop is justified by expected waste, not by process formality.
Coding against an unvalidated spec risks the work being discarded entirely, so the cost of
stopping is bounded and the cost of proceeding is not. It matches the ASME Section III framing in
§1a exactly — a non-discretionary stop with a named signer, where advancing without the sign-off
risks invalidating everything downstream.

**Status change (rev 4):** in rev 3 I recorded this as a hold point but flagged that it was an
*emergent consequence* of FR1 + FR5 rather than a named choice. It is now a **deliberate,
human-confirmed decision**. The rejected alternative is recorded for the ADR's completeness: as a
**witness point** the panel would run, file its `spec-gap` issues, and let the coder proceed in
parallel — trading rework risk for cycle time, which is the CP-3 pressure. That trade was
considered and declined.

### AD-16 — Research-note deliverable, with mandatory divergence disclosure. (BINDING — rev 4)

The human confirmed §1a's definitions with: *"Definitions work. Use them and cite sources in
research notes."* That makes a research note a **deliverable of this work item**, not an optional
extra. Add it to the `needs-ai` issue.

- **Location and style:** `research/findings/`, following the existing style in that directory
  (the sibling notes cited throughout this ADR are the model).
- **Content:** the §1a terminology, the verified citations listed there, and the mapping from each
  borrowed term to the HOS construct it names.
- **Mandatory divergence section — this is the part that must not be softened.** The note must
  state explicitly **where HOS diverges from the precedent**, not only where it matches:
  IEEE 1012 contemplates **technical, managerial, and financial** independence; **HOS satisfies
  technical only.** The note must cite the standard *for the two dimensions HOS does not satisfy*,
  name the reason (a single orchestrator dispatches both the author chain and the reviewers; one
  operator, one set of subscriptions), and state that no claim of IV&V-grade independence follows
  from the borrowed vocabulary.
- **Why this is a hard requirement and not a stylistic preference:** a note that cites IEEE 1012
  to borrow its credibility while quietly omitting two of its three independence dimensions is
  **selective framing** — precisely the description-vs-substance mismatch that this repo's own
  P9 / `prompt-fidelity` rules exist to detect, and that AD-5's FR8 part 3 makes a loggable
  finding for PRs. A framework that logs mislabeling in its subjects and practises it in its own
  research artifacts has a credibility problem larger than any finding in the note.
- **No fabricated references. Cite only what is verified.** The verified citation set for the
  Fable evidence is now fixed (rev 6) and `technical-design` must not extend it by inference:

  | Artifact | Verified content | Use for |
  |---|---|---|
  | `.claudetmp/design/fable-consistency-check.md` | Run **2026-07-29**, a **design-chain consistency check** over ADR-032 → epic spec → corrected decomposition → tickets **#1060–#1074**. Method: given the seven already-known defects, asked what that list *misses*. Findings **B1** (BLOCKER), **M1–M4** (MAJOR), **m1–m3** (MINOR). B1 = the Task-4 action table consistently swaps **#1072** (astro pack mega-ticket) and **#1073** (micro-ticket), so verbatim application would close the mega-ticket as folded and split the tiny one three ways. | The primary evidence for the completeness lens's distinct failure class |
  | **#1078** | The mechanism this ADR formalizes; the artifact self-describes as *"the first real exercise of the mechanism proposed in #1078, run deliberately out of process"* | Provenance of the dual-lens idea |
  | **#1082** | The repo's own contemporaneous comparative record — *"Fable… Found a BLOCKER all three missed, plus four MAJOR findings"*, together with the confound (*"same vendor as the third reviewer, so vendor diversity predicts it should add little"*) and the caveat (*"a single deep reviewer remains exposed to its own family's blind spots… Fable must not become a substitute for cross-vendor votes"*) | **Cite for the n=1 caveat rather than deriving it** — it is the repository's own record, not this ADR's inference |
  | **#1079** | *"the artifacts that govern code get less review than code"* | AD-11c / VF-10 |

- **The retroactive-remediation batch IS verified (rev 7) — but its model attribution is NOT.**
  Rev 6 said no batch could be located; it since has been. **Cite the batch; do not attribute it.**

  **Attribution RESOLVED (rev 8).** The human: *"Fable did the audit. Opus did the issue filing.
  Fable made a doc that Opus worked from."*

  | Fact | Status |
  |---|---|
  | **Issues #972–#1002** — 31 issues, filed **2026-07-14**, all prefixed `[AI: audit]`, **30 of 31 now closed**. Findings: CI approval gates self-bypassable, `require_tier_ceiling` dead code, multiple fail-opens, the panel dropping all reviewer findings when the arbiter is unavailable. | Verified — cite freely |
  | **Fable was the finder. opus-4-8 was the transcriber** that turned Fable's source document into tracker issues. | Settled by the human — cite |
  | The issues' provenance line *"surfaced by an AI code-audit sweep (Claude, opus-4-8) on 2026-07-14"* | **Misleading as written** — it names the *filing* pass, not the *finding* pass. **Must NOT be cited as evidence of the auditing model.** |

  **A live attribution defect in the empirical record — state it in the note (rev 8).** Thirty-one
  tracker issues carry a provenance line naming the wrong model as the finder. In a repository
  whose research value depends on *"which model produced this result"* being a **recorded
  variable**, that is not cosmetic — it is corrupted data in the empirical record, and it is the
  same defect class as the #1082 finding it sits beside (a referential claim that is false while
  every surrounding document is coherent). The note must state that **the tracker's provenance
  lines are unreliable for model attribution**, and that the Fable-authored source document is the
  authoritative record. A separate issue tracks the correction.

  **The source document must be located and probably committed.** *"Fable made a doc that Opus
  worked from"* — that doc is the primary evidence artifact for this batch and has **not** been
  located. It is **not** `.claudetmp/design/fable-consistency-check.md`, which is a distinct and
  later event (the 2026-07-29 design-chain check over #1060–#1074, de-conflated in rev 7). Given
  TD-VF-10 established that `.claudetmp/` is gitignored, if that document exists there it must be
  committed to serve as durable evidence. Until it is located, cite the batch and the human's
  attribution; do not cite a path.

- **Under-claiming is the required direction, and here is the reason that should persuade anyone
  tempted to resolve the ambiguity by guessing:** the defect the design-chain pass itself caught
  was **two swapped issue numbers in an otherwise internally coherent document** (B1). A research
  note that guessed a model attribution wrong, while citing the finding about referential errors
  in coherent documents, would be self-refuting in exactly the same way.

### AD-12 — The governance amendment: a new dated DECISIONS entry, and the four places that cite the old rule. (BINDING — rev 2)

`CLAUDE.md` makes `DECISIONS.md` append-only, so D4 and D16 are **not edited**. Append **D55 —
2026-07-31** (D54 is the current tail), stating:

1. **What is superseded and what survives.** D4's "Opus authors, so Opus never reviews its own
   output" and D16's "no Claude model can be the independent check / Sonnet stays arbiter-only"
   are replaced by two narrower rules: **(1) class-differential permitted within family** — a
   same-family model may validate work authored by a strictly lower class, same-class
   self-validation remains prohibited; **(2) never sole** — a same-family voice may participate
   in a panel but may never constitute it. D4's *author-exclusion* principle survives intact and
   is in fact the special case of rule (1) at equal rank.
2. **The class ordering** `haiku < sonnet < opus < fable` as a rank registry, with the
   fail-closed rule that an unregistered class has no rank.
3. **The AD-10 distinction, stated explicitly**, so the entry cannot be read as "depth replaces
   diversity": class differential buys capability/thoroughness, cross-vendor buys decorrelation,
   neither substitutes, and a same-family voice may never reduce a gate's cross-vendor count to
   zero. Cite the repo's own finding (`research-findings-draft-2.md:46,52`) and its honest
   limitation (`:56` — n=1, confounded with running last).
4. **The direction-of-change disclosure.** Reviewer independence and the cross-vendor requirement
   are a safety-critical class of rule; this amendment **loosens** the predicate. The entry must
   say so plainly, and must record the compensating tightenings that make the net effect at the
   gate level neutral-to-stricter. **Rev-8 correction — ratifying `technical-design`: the
   compensations are AD-14, AD-8+AD-15 and AD-11b. NOT AD-11a, which was permanently withdrawn in
   rev 6.** Writing D55 as originally specified would have recorded a safety-critical loosening
   offset by a decision that does not exist. Correct list, strongest first: **AD-14**
   (independent-review coverage made unconditional via the classification ∪ deterministic-floor
   trigger, replacing a self-assessed tier gate); **AD-8 + AD-15** (the spec-phase hold point given
   an *executable* enforcer where FR5 previously had none — VF-2); **AD-11b** (independent-review
   coverage at LOW made a checked precondition rather than an assumption). A loosening recorded
   without its compensations is how a ratchet quietly reverses; a loosening recorded with a
   **fictitious** compensation is how one reverses while appearing not to.
5. **The VF-6 lens↔vendor exception** for the spec phase (agy=adversarial / same-family=
   completeness, deliberately the inverse of the D4 convention), so a consistency sweep cannot
   swap it back.
6. **Scope of the outage-posture change** (AD-7), applied to `run_second_review.sh` in the same
   change as AD-14 rather than as a follow-up.
7. **(rev 3) The AD-14 trigger principle**, stated as a standing rule and not merely as a change
   to one script: *independence coverage is triggered by phase boundaries and change
   classification; a self-assessed risk tier may scale intensity but may never reduce coverage to
   zero.* Record the union-not-replacement correction and its reason (a pure-classification
   trigger would have removed independent review from high-risk bug fixes).
8. **(rev 3) The §1a terminology and the IEEE 1012 / IV&V grounding**, including the explicit
   statement that HOS has **technical independence only — no managerial and no financial
   independence** — so no future document can claim IV&V-grade independence on the strength of
   this amendment. This is the entry's most important line for anyone reading the framework's
   claims from outside.

**Everything that cites the old rule and now contradicts it** (`technical-design` must update all
four in the same change — a superseded rule left quoted in a live script is the silent
contradiction class this entire ADR exists to catch):

| Location | Current text | Required change |
|---|---|---|
| `scripts/run_second_review.sh:9` | `VENDOR ROLES (DECISIONS.md D4 — no Claude model as independent check)` | Restate against D55. Header comment only; the script's vendor logic is unchanged by this ADR. |
| `scripts/framework/validate_agents.sh:15` | `VENDOR ROLES (mirrors run_second_review.sh DECISIONS.md D4)` | Same restatement. |
| `scripts/run_panel.sh:385` | roster line `Opus authored → excluded` | **Behavioral, not cosmetic.** Author-exclusion is no longer "exclude the Claude family"; it is "exclude same-family models at or below the author's rank". A rank-4 same-family reviewer over rank-3-authored work is now admissible. Whether to actually add it to the panel roster is a separate cost decision — but the *exclusion predicate* must be corrected, or the roster logic encodes a rule that no longer exists. |
| `DECISIONS.md` D16:80 | "no Claude model can be the independent check… Sonnet stays arbiter-only" | Not edited (append-only). D55 must name D16:80 explicitly as superseded, or a reader who greps D16 first gets the old rule with nothing pointing forward. |

Also refresh the rev-1 statement in this ADR's own VF-5 (done) and any restatement in
`README.md` / `METHODOLOGY.md` surfaced during implementation.

---

## 3. Product-boundary checkpoint (rev 2)

**Revision 1's CP-1 and CP-2 are WITHDRAWN — both resolved by the rule change.** CP-1 (codex
leaves reserve status, contradicting `run_second_review.sh:17-21`) is moot: AD-3 rev 2 takes
codex off the spec-phase path entirely. CP-2 (a codex outage blocks all feature work) is moot on
both axes: codex is no longer a spec-phase dependency, and AD-7 rev 2 makes single-vendor outages
non-blocking wherever an independent review remains. **CP-3 stands** (pm-agent confirms the
serialized-latency consequence of FR2's aggressiveness is a product fact, not a defect to be
optimized away by later re-narrowing FR2). One new item:

**CP-4 (human) — the cost of AD-11a and the LOW-tier exception.** Two bounded questions, both
cost, neither technical:
- **AD-11a** promotes `code-reviewer` from rank 2 to rank 3 (`sonnet`→`opus`) on the mandatory
  lane at every step. This is the minimum viable class differential; the alternative (all eleven
  reviewers) is roughly an order of magnitude more and I do not recommend it. Confirm the one-lane
  promotion is funded.
- ~~**AD-11b** — accept the LOW-tier bounded exception, or fund `OVERSIGHT_AGY_THRESHOLD → 0`?~~
  **RESOLVED by AD-14 (rev 3)** and by a better answer than either option offered: agy now fires
  on every `additive`/`structural` change at any tier, while `clarifying` sub-MEDIUM changes
  still do not pay for it. Cheaper than the knob and stricter than the exception. **The residual
  cost question that remains is smaller and worth naming:** agy now fires on LOW-tier additive
  work that previously got nothing, so agy volume rises. D4:30 identifies the agy subscription
  upgrade as the designed lever if that volume exceeds the $20 baseline — no decision needed now,
  but it is the metric to watch first.

**~~CP-5 — completeness-lens rank/frequency policy.~~ WITHDRAWN (rev 5).** Raised in rev 4 on the
report that a single fable-class pass consumed the weekly budget into overage. That pass was a
**full-codebase audit** — outlier scale, not a routine per-bundle pass. Real utilization is **~9%
weekly, ~91% headroom.** With no material cost shift there is no product-boundary trigger, so the
decision returns to me and is closed in AD-3: **rank 4 binds**, with the n=1 qualifier and the
consumption instrumentation attached. Recorded rather than deleted, because the *shape* of this
correction is itself worth keeping — an escalation built on a single unrepresentative measurement
produced a conservative design that the data did not support, which is a failure mode this
framework is supposed to detect in others.

**CP-4 (rev 4 status):** bullet 2 was resolved by AD-14. Bullet 1 (`code-reviewer` → rank 3) is
**moot while AD-11a is suspended**, and returns only if the human reinstates AD-11a.

**CP-5 — human endorsed the final disposition (rev 6):** *"CP-5 architect's recommendation sounds
reasonable."* Read as endorsing the **rev-5 disposition** — rank 4 at FR2 frequency, qualified as
*the demonstrated configuration pending better evidence*, with the consumption instrumentation and
the >50% / >80% operator step-down thresholds — **not** a reversion to the earlier conservative
option-1 menu, which the withdrawn budget premise had made moot. Proceeding on that reading.

**Everything binds. All checkpoints and open questions are closed (rev 7):**
- ~~**AD-13**~~ — **ACCEPTED and BOUND** in rev 7: *"decision" ≡ "hold point"*.
- ~~**AD-11a**~~ — permanently **WITHDRAWN** in rev 6 on the instance reading.
- ~~**CP-5 / AD-3**~~ — closed in rev 5; endorsed by the human in rev 6.
- ~~**AD-15**~~ — CONFIRMED and binding since rev 4.
- ~~**CP-1, CP-2, CP-4**~~ — withdrawn in revs 2–5 as their premises were superseded.
- **CP-3** remains with `pm-agent` (confirm the serialized-latency consequence of FR2 is a product
  fact, not a defect to be optimized away by re-narrowing FR2). It is a confirmation, not a gate.

**The one unresolved item is evidentiary, not architectural:** the model attribution of the
#972–#1002 batch (AD-16). It is deliberately not load-bearing — no decision in this ADR turns on
it, and under either resolution the pass was same-family peer review that would not discharge a
hold point. `technical-design` must not resolve it by inference.

**CP-3 (pm-agent) — cycle-time impact. Carried forward from rev 1, still open.** Every additive
change now runs pm-agent → architect → technical-design → the two-lens panel → spec-gap
resolution before a line of code. Human decision 1 accepted the frequency increase in principle;
pm-agent should confirm the *serialized-latency* consequence is understood as a product fact, not
a defect to be optimized away later by re-narrowing FR2.

Per my CORE contract, an architecture decision that shifts the cost model or adds an operational
obligation routes through pm-agent and the human **before** it binds. In rev 2 that applies only
to CP-3 and CP-4; every other decision here is cost-neutral or cost-reducing relative to rev 1.
AD-1, AD-2, AD-3, AD-4, AD-5, AD-6, AD-7, AD-8, AD-9, AD-10, AD-11c and AD-12 bind now.
**AD-11a and AD-11b bind pending CP-4** (they are funded decisions, not open technical questions —
the *what* is settled, only the *spend* needs clearance). AD-13 is pending the human's own
discussion.

---

## 4. Startup-gap analysis and affected sign-offs

Per my CORE startup-gap rule: *should this have been settled in an initial architecture review?*

- **Yes, for VF-1 and VF-2.** The SPEC PHASE was documented in `METHODOLOGY.md`, `CLAUDE.md`,
  `ARCHITECTURE.md`, `docs/AGENTS.md`, and `docs/OVERSIGHT-RUNBOOK.md` as an executing pipeline
  stage that has never had a caller, and its gate field has never had an enforcer. The repo's own
  2026-06-14 eval recorded half of this and it was not closed. Open a `startup-artifact-gap` issue
  covering VF-1 + VF-2, cross-referenced to this ADR.
- **Affected sign-offs:** **none are invalidated.** Every prior design/code approval was made
  against a pipeline in which the spec phase did not execute; this ADR *adds* a gate on a path
  that was never built rather than *revising* a decision already built against. Under my CORE
  rule ("a decision for a path never built → prior sign-offs stand"), **all prior sign-offs
  stand.** The one boundary to watch: work merged under an FR2-exempt framing *before* this ships
  is grandfathered by the AD-5 acceptance-order rule and must not be retroactively bounced.
- **Separate issues to file (do not fold into this work item):** VF-3 (bounce API cited but never
  implemented); VF-7 (twelve marker-less agent files); the `spec-red-team` region migration;
  **(rev 2)** VF-10 / AD-11c (the `.md` tier-floor gap, linked to #1079 — still open after AD-14);
  **(rev 3)** the D53 anti-framing coverage gap (three reviewer lanes carry the instruction, the
  rest do not) and the peer-review adversarial-instruction guardrail (§1a).

**Rev-2 addendum to the sign-off analysis.** The revised independence rule reaches further back
than this ADR: every sign-off ever written by the inner-loop chain was produced by same-family,
same-class reviewers, which revised rule (1) says is not a validating check. I am **not**
invalidating those sign-offs, for a reason that must be stated rather than assumed: rule (1)
governs whether a same-family check *counts as the independent check*, and for every MEDIUM+ step
an actual independent review (agy, and codex at HIGH+) did run alongside them, so those decisions
were never same-family-sole. The exposure is confined to **LOW-tier steps whose merge predates a
verified-enabled Copilot** — for those, rule (2) may not have held in fact. That set is bounded
and enumerable from the audit log.

**CORRECTION (rev 4) — the rev-2 ruling described a counterfactual that is no longer true.**
Rev 2 ruled "do not retroactively re-review" and recorded the exposure as *"a measured research
datum rather than a remediation backlog."* **That is now factually wrong and must not be carried
forward: the human did in fact remediate it**, via a retroactive fable-class review pass, and the
issues that pass filed are real artifacts in this repository — not a hypothetical backlog. The
rev-2 sentence is superseded, and the ADR states the actual history instead:

- The retroactive pass **happened** and **produced filed issues**. **Rev-5 correction to the
  cost characterization:** rev 4 recorded that it "consumed the entire weekly fable budget into
  overage." That framing is withdrawn — the pass was a **comprehensive full-codebase audit**, an
  outlier-scale task, and real utilization sits at **~9% weekly**. The pass is the remediation
  record; it is **not** a valid cost datum for routine per-bundle passes, and AD-3 no longer
  treats it as one.
- **Rev-7 update — the batch is found, the attribution is not.** The remediation batch is
  **#972–#1002** (31 issues, filed 2026-07-14, `[AI: audit]` prefix, 30 closed), with substantive
  findings including self-bypassable CI approval gates and multiple fail-opens. That firmly
  substantiates "retroactive remediation occurred" — better than testimony, with closure evidence.
  **But the model attribution is contested** (the issues' own provenance line says `opus-4-8`;
  the recollection was fable), asked and unanswered. **Cite the batch; attribute it to no model.**
  Separately, the **design-chain** artifact (`fable-consistency-check.md`, tickets #1060–#1074) is
  a distinct, verified thing and is **not** the same event as this batch — rev 6 conflated the
  absence of the batch with the design-chain check, and that conflation is corrected here.
- The original rev-4 reasoning for declining to invent numbers stands: `gh` is unauthenticated, and
  a plausible-looking but wrong issue number in a research artifact is exactly the referential
  defect class the fable pass itself was celebrated for catching
  (`research-findings-draft-2.md` — the B1 finding was two swapped issue numbers in an otherwise
  internally coherent document). Verified-locally artifacts I *can* cite:
  `.claudetmp/design/fable-consistency-check.md` and `.claudetmp/design/research-findings-draft-2.md`.
- **The forward ruling is unchanged and is now better supported:** no *further* retroactive
  re-review is required. AD-11b makes coverage verifiable going forward, AD-14 makes it
  classification-triggered rather than tier-gated, and the historical exposure has already been
  worked rather than merely recorded.

---

## 4a. Revision 8 — rulings on `technical-design`'s escalations and verification findings

`technical-design`'s design is at
`/home/scott/Code/HumanOversightSystem/Human/docs/v0.6.0/TECHNICAL-DESIGN-033-dual-lens-spec-review-gate.md`.
I verified its load-bearing findings independently before ruling: `pr_readiness.py` absent
(`find` returns nothing), `signoff_gate.py` present, `run_review_chain.sh:235-244` short-circuits
below MEDIUM, `run_second_review.sh:263-274` already fails only when both vendors are absent,
`.gitignore:2` = `.claudetmp/`. All confirmed.

**ESC-2 — `spec-completeness-review`'s `model:` field. APPROVED as designed: `model: opus` +
`model_rank.DEFAULT_COMPLETENESS_CLASS = "fable"`.** Three reasons. (a) `fable` is unverified as a
*frontmatter* alias; the Agent-tool dispatch path accepting it is a different code path, and a
hold-point gate must not rest on an unverified resolution. (b) **D54 makes agent frontmatter
HOS-canonical and consumer-uneditable** — policy that an operator is expected to change must not
live there. (c) It gives AD-3's operator step-down **exactly one place to change**, which AD-3
requires (a step-down must not need a governance change). The indirection is correct whichever way
the alias question resolves.
> **Additional binding this exposes.** Separate the two model roles explicitly in the artifact
> header: the agent's own runtime model, and the *lens* class actually dispatched. And rule the
> failure mode: **an unresolvable completeness class falls back to the next lower registered,
> resolvable class**, recording `class_fallback: true` and `completeness_lens_class_differential`
> accordingly — it does **not** hard-fail. This follows directly from AD-11a(b): rank never
> discharges the hold point, so a rank fallback is a *quality* event. Only a total lens failure
> (no Claude class resolves at all) is an FR1 absence under AD-7.

**ESC-3 — codex combined-review fallback in `run_second_review.sh`. RETAIN. `technical-design` is
right and AD-3's rejection does not reach it.** The two cases are different and the distinction is
principled, not a concession: AD-3 rejects the fallback *at the spec panel* because there one model
running both prompts collapses two deliberately-different framings into one correlated judgment —
a single-lens gate wearing a dual-lens verdict. In `run_second_review.sh` the fallback does the
opposite: codex covering correctness+security is **still cross-vendor independent review**, and
removing it would drop independent review to zero when agy is down at HIGH+. That is a coverage
reduction, which AD-14's union principle forbids and which I may not accept in any case.
> **General rule, binding: never remove an independent participant to satisfy a purity constraint.**
> Retain the fallback with honest header recording (`degraded: one combined review`).
> **Ratifying TD-VF-8:** the real AD-7 delta here is honesty and expressibility, not permission —
> the HIGH+ guard already proceeds when only codex is absent. **K5 must not be advertised as a
> coverage change** in any commit message, PR body, or D55 text.

**ESC-4 — hold-point enumeration. CONFIRMED: HP-1 spec panel, HP-2 pre-PR second review, HP-3
merge gate.** Two required additions before it goes in the contract:
1. **Add an "applies when" column.** As written the table implies LOW-tier `clarifying` work has
   three unsatisfied hold points. It has none — HP-1 does not apply (no spec phase), HP-2 does not
   fire (AD-14's union is false), HP-3 does not apply (not CRITICAL/protected/gated). A hold point
   that does not apply is **not an unsatisfied hold point**, and the contract must say so or the
   first reader will conclude the pipeline is permanently out of compliance.
2. **Add WP-1 — Copilot's every-PR review — as a WITNESS point.** §1a defined the term and this is
   its use: an independent party reviews, work continues, it does not block. This is exactly what
   makes AD-11b's LOW-`clarifying` residue a *bounded exception* rather than a violation — such
   work is covered by a witness point, not by a hold point. Recording it completes the taxonomy
   and converts AD-11b's prose exception into a named structural fact.

**Ratifications (all APPROVED):**
- **TD-VF-1 / pr_readiness.py — a FOURTH instance of the VF-1/VF-2/VF-3 family.** The rebase onto
  `spec_gate.py` modelled on `signoff_gate.py` is correct; my AD-8 citation was wrong and is struck
  in place. **Four instances is a pattern, not a coincidence**, and the systemic control is
  missing: nothing verifies that a script path or function cited in a doc or agent charter exists.
  **File ISSUE-9** — extend `check_agents_static.sh` to verify referenced executables/callables
  resolve. Do **not** fold it into this work item. This also raises the stakes of AD-13's
  enumeration obligation: the hold-point table is only worth writing if its `Enforcer` column is
  machine-checked.
- **TD-VF-2 / AD-14 would have shipped inert.** Serious catch — AD-14 would have been dead for
  exactly the LOW-tier `.md` case it exists to close. Component L approved. The `worker.md:230`
  prose passing `--tier <validated>` must also be fixed: AD-14 forbids the self-reported tier as a
  trigger, and a prose copy of a gate is still a gate.
- **TD-VF-3 / `run_panel.sh:385` is a log string.** My rev-2 instruction to "correct the predicate"
  was wrong — there is no predicate, only a hard-coded roster that happens to contain no Claude
  entry. §7 **creates** `reviewer_admissible()`; behavioural delta nil by construction, value is
  that the invariant becomes code. **Also fix `run_panel.sh:427`**, which tells the reviewer *"The
  author was Claude Opus; you are the independent check"* — false today (`coder` is sonnet). A
  reviewer being fed a factual untruth about its input is a real defect and sits squarely against
  D53's framing guard.
- **TD-VF-6 / AD-14's asymmetry claim was half true.** `change_classifier.py` re-derives only
  `→ structural`, never `clarifying ↔ additive`. The narrowing is accepted: fail-closed defaults,
  `classification_source` in the header, and **a ban on any downstream document claiming the
  classification trigger is fully audited.** This is the AD-16 anti-selective-framing discipline
  applied to my own text, which is the correct outcome.
- **TD-VF-7 / ADR self-contradiction on AD-7 scope.** Rev 3 governs; summary row 7's trailing
  sentence was stale and is struck.
- **TD-VF-10 / gitignored citation.** Approved: quote B1 inline in the research note and label the
  path a local uncommitted artifact. **Additionally: cite #1082 as the durable anchor** for the
  comparative result and treat the local path as provenance only — that closes the durability gap
  properly rather than merely documenting it.
- **TD-VF-5 / agy JSON mode.** ISSUE-6 is the right disposition; D41's "no JSON mode" premise is
  stale but out of scope here.
- **Four PRs per §11.** Approved — `docs/PR-SIZE-POLICY.md` governs.

**ESC-1 routes to `pm-agent`, not to me** (TD-VF-4: the FR1–FR8 document is not in the repository).
But it forces an amendment I must make: **AD-6's "transcribed verbatim from the requirements" is
unsatisfiable against an artifact that does not exist.** Amended: §5's reconstruction from
`worker.md:224-228` governs until `pm-agent` commits the FR document, at which point the verbatim
requirement attaches to the committed text. **The requirements for a human-approved work item
existing only in agent-to-agent messages is itself a governance gap** — it belongs in the same
issue family as VF-1/VF-2/VF-3/TD-VF-1, and `pm-agent` should commit the document regardless of
how ESC-1 resolves.

---

## 5. Summary of bindings for `technical-design`

| # | Binding |
|---|---|
| 1 | New sibling agent `spec-completeness-review`; `spec-red-team`'s charter and vendor are unchanged except for the AD-4 taxonomy block. New agent ships with CORE/PROJECT regions and a `model:` class alias. |
| 2 | `scripts/run_spec_panel.sh` is the single invocation site; machine-readable artifact at `.claudetmp/spec-panel/step{N}-{ts}.md`; `unparseable ≠ error ≠ pass`; env knobs may only strengthen. |
| 3 | **(rev 5)** agy = adversarial; completeness = same-family **rank 4 (`fable`) at FR2 frequency — BINDS**, as *the demonstrated configuration pending better evidence*, not as an established requirement (n=1, confounded — carry the qualifier downstream). Implement **rank-parameterized** so a later step-down needs no redesign; rank computed against the artifact's authors at runtime; fallback on unavailability is cross-vendor `codex`; class aliases only; resolved IDs, rank, `completeness_lens_class_differential`, and **per-bundle consumption** recorded in the artifact header; no single-model dual-lens; VF-6 exception recorded. |
| 3b | **(rev 2, restated rev 3)** AD-10: rank registry `haiku(1) < sonnet(2) < opus(3) < fable(4)`; unregistered class = no rank = fail-closed. **Class-differential peer review never substitutes for independent review** — rules (1) and (2) are conjunctive and orthogonal. Deterministic checkers are corroboration and may trigger review, never constitute it. |
| 3c | **(rev 2)** AD-11a: `class(code-reviewer) > class(coder)` promoted to a real differential (`opus` vs `sonnet`) and encoded as a *relation* in `check_agents_static.sh`; folded into #1122's alias refresh, not a separate churn of the same 30 files. |
| 3d | **(rev 2)** AD-11b: independent-voice coverage unconditional at every tier; Copilot-enabled becomes a **checked precondition** of rule-(2) compliance at LOW, not an assumption; LOW inner-loop sign-offs are a bounded documented exception cured at PR time, with the agy-threshold knob named as the fix. AD-11c: VF-10's prose-floor gap filed against #1079, not fixed here. |
| 4 | One canonical `Gap type` set owned by `contract/OVERSIGHT-CONTRACT.md`; `missing-scope` added; `Lens:` field added; both `spec-red-team.md:83` and `:105` rewritten. |
| 5 | FR8 = one new overseer step-4a bounce condition, `check_id: SPEC-PHASE-MISSING`, `reason_category: COMPLIANCE_FAILURE` (enum unchanged), detection via `change_classifier.py --structural-only`, SPEC-267 scope rules reused verbatim, existing `bounce_count(cid) >= 2 → HUMAN_REQUIRED` cap unchanged and no new counter, new `spec-phase-missing` audit event emitted on pass **and** bounce. |
| 6 | FR2 trigger rule hoisted from `worker.md:224` to a both-modes section; `triage.py` untouched; `worker.md:229` stale-gate note updated; worker-sandboxing forward constraint recorded. |
| 7 | **(rev 2)** Outage posture keys on *"would this leave a sole same-family voice deciding?"*, not on vendor availability: ≥2 independent participants → proceed and log the absence; sole-same-family → hard fail + human bypass. Runtime errors are absence, never approval. For this panel both lenses stay effectively mandatory (agy absent → rule-(2) hard fail; completeness absent → FR1 failure), and the two must be reported distinctly. Bypass artifact unchanged. ~~Applying the new posture to `run_second_review.sh` is a deliberate follow-up, out of scope.~~ **Rev-8 errata (TD-VF-7): that trailing sentence was stale rev-2 text. AD-7 rev 3 and row 12 govern — it is IN scope.** |
| 8 | `Ready for coder: YES` gets an executable pre-coder enforcer (non-zero exit blocks coder dispatch); `pm-agent.md` gains the resolver side; `docs/AGENTS.md:277` architect-confirmation rule extended to both lenses. |
| 9 | FR7 doc updates across `METHODOLOGY.md` (prose + mermaid `:174`), `CLAUDE.md`, `ARCHITECTURE.md`, `contract/OVERSIGHT-CONTRACT.md`, `docs/AGENTS.md`, `docs/OVERSIGHT-RUNBOOK.md` — plus the AD-1 registration surface. **(rev 3)** These documents must adopt the §1a vocabulary — *peer review*, *independent review*, *hold point*, *graduated independence* — replacing coined and positional language, and must state the technical-independence-only limitation wherever they characterize what HOS's review layer achieves. The `METHODOLOGY.md:174` node is labelled a **hold point** (AD-15). |
| 12 | **(rev 3)** AD-14: independent review fires iff `classification ∈ {additive, structural}` **OR** deterministic tier floor ≥ MEDIUM — a **union**, never a replacement. Tier scales intensity only (agy on fire; codex at HIGH+). Both inputs must be the independently re-derived ones, never self-reported. Env knobs may scale intensity but may never suppress the classification trigger. `run_second_review.sh` header block rewritten; AD-7's outage posture applied in the same change. |
| 13 | **(rev 3)** §1a terminology binding on all touched artifacts; peer review requires both guardrails (no author framing — D53, currently only 3 of the reviewer lanes, gap filed; adversarial instruction). |
| 14 | **(rev 4)** AD-15 **CONFIRMED**: the spec panel is a **hold point** — non-discretionary stop, `Ready for coder: YES` is the signature, coder is the traveller. Human rationale recorded verbatim. This is why AD-8's enforcer must be executable: an ITP hold point the traveller can walk past is not a hold point. |
| 15 | **(rev 5, replaces rev 4)** CP-5 **withdrawn** — the infeasibility premise was an outlier-scale measurement (~9% real utilization). Rank 4 binds. **Step-down to rank 3 remains an operator decision needing no governance change**, because the lens is peer review at every rank and the panel's independent review (agy) is unaffected — that reframe is the reason this decision is safely revisable, and it must survive into the implementation notes. Instrument per-bundle consumption; recommended step-down thresholds >50% / >80% weekly utilization (defaults, not gates). |
| 16 | **(rev 6, replaces rev 4)** AD-11a **PERMANENTLY WITHDRAWN** on the merits — the prohibition turns on the **agent instance**, not the model. `coder` and `code-reviewer` are different instances with no shared memory doing routine peer-review work, so **`code-reviewer` stays rank 2**; do not implement the promotion or the static class-relation check. |
| 16b | **(rev 6) — quote this verbatim in the agent charters and the contract.** At a **hold point**, same-model-different-instance does **not** discharge the requirement. The completeness lens is same-family peer review and **cannot by itself discharge the spec panel's hold point**; it is discharged because agy (cross-vendor) is also present, guaranteed by AD-7 + AD-14. **A fable-class lens running alone at a hold point is NON-COMPLIANT at any rank.** This is the canonical form of AD-10 and now carries direct human authority. |
| 17 | **(rev 4)** AD-16: a `research/findings/` note is a **deliverable**, with verified citations and a **mandatory divergence section** stating that HOS has technical independence only, citing IEEE 1012 for the two dimensions it does *not* satisfy. No fabricated issue numbers; resolve the fable-pass issue numbers against the repo at implementation time. |

| 10 | **(rev 2)** AD-12: append `DECISIONS.md` **D55 — 2026-07-31** (never edit D4/D16 in place); it must name D16:80 as superseded, state the loosening plainly alongside its compensating tightenings, and carry the rank registry + the AD-10 distinction. Update the three live citations of the old rule: `run_second_review.sh:9` and `validate_agents.sh:15` (comments), and `run_panel.sh:385` (**behavioral** — the author-exclusion predicate is now rank-relative, not family-blanket). |
| 11 | **(rev 7, replaces rev 2)** AD-13 **BOUND**: *"decision" ≡ "hold point"*. Rule (2) final form — *at every hold point at least one **independent reviewer** must participate; routine work is unconstrained beyond the §1a peer-review guardrails.* No implementation change (AD-14 already enforces it), **but the set of hold points MUST be enumerated explicitly in `contract/OVERSIGHT-CONTRACT.md`** — an enumerable predicate that is never enumerated degrades back into the semantic gates that produced VF-1, VF-2 and VF-3. `technical-design` proposes the list; I confirm it. |
| 17b | **(rev 8, replaces rev 7)** AD-16 / §4: cite the remediation batch as **#972–#1002 (31 issues, 30 closed, 2026-07-14)**. **Attribution RESOLVED — Fable found, opus-4-8 filed.** The issues' provenance line names the *filing* pass and **must not be cited as evidence of the auditing model**. State in the note that **the tracker's provenance lines are unreliable for model attribution** — 31 issues carry the wrong finder, which is corrupted data in a record whose research value depends on model attribution being a recorded variable. The Fable-authored source doc is authoritative, **has not been located**, is **not** `fable-consistency-check.md`, and likely needs committing out of gitignored `.claudetmp/`. |
| 18 | **(rev 8)** All ESC/TD-VF rulings in §4a bind: ESC-2 approved (with the class-fallback rule), ESC-3 retain-the-fallback (**never remove an independent participant to satisfy a purity constraint**; K5 not advertised as coverage), ESC-4 confirmed **plus** an "applies when" column **plus WP-1 Copilot as a witness point**, and the TD-VF-1/2/3/6/7/10 ratifications. **File ISSUE-9**: nothing verifies that script paths and callables cited in docs/charters exist — four instances is a pattern. AD-6's "verbatim" amended pending ESC-1. |

**Explicitly out of scope:** implementing the bounce helpers (VF-3); region-marker migration
(VF-7); the #1122 model-alias sweep across the other 29 agents (AD-11a rides along with it but
does not perform it); extending the `reason_category` enum; extending `TIER_FLOOR_*` to `.md`
(AD-11c — filed, not fixed, and **#1079 does not close against this ADR**); adding a same-family
rank-4 reviewer to the `run_panel.sh` roster (only the exclusion *predicate* is corrected);
extending D53's anti-framing instruction to the peer-review lanes beyond `code-reviewer` /
`security-reviewer` / `privacy-reviewer` (§1a — filed, not fixed).
**Moved INTO scope in rev 3:** applying AD-7's outage posture to `run_second_review.sh`, because
AD-14 already rewrites that script's mandatory-review branch and the two rules must not be
written in separate passes.

**Escalation path from here:** `technical-design` disputes → me. Product/requirements disputes →
`pm-agent`. CP-3 → `pm-agent`; CP-4 → the human. AD-13 → the human (in progress). The checkpoints
gate cost and product consequences only, not the technical decisions above.
