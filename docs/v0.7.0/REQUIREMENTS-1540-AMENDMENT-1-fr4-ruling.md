# REQUIREMENTS-1540 — AMENDMENT 1: ruling on PANEL-1540 **P-2** — FR4 versus AD-4/D5, and which model governs

**Status:** RULED by `pm-agent` — **binding on `architect`, `technical-design` and `coder` from the moment `architect` adopts it**, and **held for the human's explicit ratification** as a new item on H1 (§5). This document **amends** `docs/v0.7.0/REQUIREMENTS-1540-request-intake-risk-agent.md`; it replaces neither it nor any ADR. Every requirement in the original document (FR1 … FR27, VF-1 … VF-12, Q1 … Q9) stands **except** FR4, which is narrowed by **AR-1/AR-3** below, and FR17, whose S2-era disposition is stated by **AR-6**. Where this document and the original differ, **this document governs**.
**Date:** 2026-09-15
**Author:** pm-agent
**Amends:** **FR4** (narrowed — the prohibition is scoped to the *trust* determination and no longer reaches the *authorization* determination). **Adds:** FR28, FR29. **States, rather than changes:** the S2-era disposition of FR9, FR10, FR17 (AR-6). **Confirms without change:** the document's title, FR1, FR2, FR3, FR5, FR6, FR7, FR8, FR16, FR18 … FR27, §3 seams 1–4, §4's non-goals.
**Inputs:** `docs/v0.7.0/PANEL-1540-S1-S2-dual-lens-adversarial.md` **P-2** and §4's sequencing note; `docs/v0.7.0/REQUIREMENTS-1540-request-intake-risk-agent.md` (title, FR1–FR27, §3, §4, §5); `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md` (`:128`, AD-1 … AD-6, §3 build order incl. `:325`); `ADR-1540-AMENDMENT-1` (AM-1, AM-4, AM-6, AM-8) and `ADR-1540-AMENDMENT-2` (AM-14 … AM-18, AF-5, AF-6, §3(b) H1); `docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md` §2.3 Steps D4/D5, §2.6's worked trace, §2.7.4; **issue #1539's body and its 2026-09-10 human ruling**, read live this session via `bootstrap/query_issues.sh --app worker --issue 1539 --full`.
**Consumers:** `architect` (next — P-1 and the AD-4/AD-5 reconciliation), then `technical-design` (revision 4), then the panel's re-run, then `coder`.
**Scope note:** This document says WHAT and WHY only. It rules a requirements conflict. It contains no algorithm, no file layout, no API shape, and it does not choose between the architect's options on **P-1**, which is not mine.

---

## 0. The question, stated so it can be answered

PANEL-1540 **P-2 (HIGH, blocking)** found two binding statements specifying opposite gates, and a build document that cites neither.

**Side one — the requirements document's title:**

> REQUIREMENTS-1540 — Request-intake risk assessment: **no untrusted-authored request becomes autonomous work without a documented assessment and an explicit CODEOWNER approval**

**Side two — its own FR4 (`:273-280`), restated in the architect's voice at ADR-1540 `:128` and headed BINDING at AD-4:**

> **FR4 — Trust attaches to the request's origin, not to the last actor who touched a label.** … **A subsequent label, milestone, or metadata change by a trusted actor (human *or* bot) MUST NOT convert an untrusted-authored request into a trusted one.**

**And the design (TECHNICAL-DESIGN-1540 §2.3 Step D5) implements the first**: an untrusted-authored record becomes eligible on a verified human CODEOWNER's `labeled`/`milestoned` event. The panel measured that the technical design mentions **FR4 zero times in 1,363 lines**; I re-ran the count this session and confirm it.

The question I am answering is exactly the one the panel put, and no more:

> **Which model governs an untrusted-authored request — origin-trust (nothing a later actor does can make it eligible) or authorization (a designated human CODEOWNER's explicit act on that specific request makes it eligible)?**

The panel deliberately did not pre-judge it. I do, below, and I state what it costs.

---

## 1. AR-1 — THE RULING. **The AUTHORIZATION model governs.** FR4 is **narrowed, not withdrawn**: it governs the **trust** determination (who is exempt from the gate) and does **not** govern the **authorization** determination (who may release a gated request). AD-4 and Step D5 are **compliant with FR4 as amended**. (Amends **FR4**.)

> **An untrusted-authored request MAY become autonomous work, and the only thing that can make it so is an explicit act by a verified individual human CODEOWNER on that specific request. No such act ever makes the request, or its author, trusted.**

Four reasons, in ascending order of weight. The fourth is dispositive on its own.

**1. The requirements document's own §3 already reads FR4 this way, and its worked examples are all bots.** §3 seam 3 is the only place the document explains what FR4 is *for*:

> **Trust flows from origin, not from the last label toucher (FR4)** — this is the rule that keeps #1539's "a bot applying the label does not count" from breaking three live paths that legitimately apply `needs-ai` under a bot identity… Under FR4, a bot-applied label inherits the trust of the *issue's author*: the worker relabelling its own `[BLOCKED]` issue stays trusted; the worker relabelling an anonymous issue does not. **This is the single most important interaction finding in this section.**

Every example is a **bot**. The rule is framed entirely as the answer to *#1539's* question — "who applied the label?" — and its stated purpose is to stop label-laundering while keeping three legitimate bot paths alive. Nothing in §3 contemplates a human CODEOWNER's deliberate act on a specific issue, because that act is not laundering; it is the approval the *title* is about. FR4's parenthetical "(human **or** bot)" reaches past the rule's own stated purpose into a different question, and that over-reach is the whole of P-2.

**2. The title does not actually say what the panel read it as saying, and once read literally the two are not in conflict about *sufficiency*.** The title is a statement of **necessary** conditions — "no X without A and B" — not of sufficiency. It does not say approval *suffices*; it says work must not begin *without* it. FR4, correctly scoped, supplies a further necessary condition in a different dimension: the author is still untrusted, so the request's *content* is still untrusted and the author accrues nothing. Read that way, title and FR4 are two necessary conditions of one gate rather than two incompatible gates. The panel's reading of the title as an authorization model is the right *practical* reading — it is what the mechanism does — but the conflict it exposes lives in FR4's unqualified "MUST NOT convert", not in the title.

**3. FR4 read literally is not a stricter requirement; it is an inoperative one, and I can price it.** Under the literal reading, no act by any actor can make an untrusted-authored request eligible. Then:

- **FR16** (only a human CODEOWNER can approve, via `/approve`), **FR17** (approving without an assessment), **FR18** (declining is a first-class outcome) describe a channel that can never release anything. An approval that cannot change an outcome is not an approval.
- **FR11 – FR15** specify an assessment written for a CODEOWNER to act on. Under the literal reading there is no act available to them but decline.
- The entire mechanism #1540 exists to build — assess, document, approve — collapses to "gate everything from outside the trusted set, forever."

And the price is measured, not argued. The panel's live count of the active milestone, 2026-09-15: **96 open dispatch-labelled non-PR candidates; 4 authored by `ScottThurlow`.** Under the literal FR4 the other **92 are permanently unbuildable**, including **#1539 and #1540 themselves** (both authored by `scottthurlow-claude[bot]`, untrusted by AM-1 option C). A requirement whose faithful implementation makes the `priority:critical` issue it exists to close permanently unbuildable has a defect in it. This also disposes of the panel's third listed option — *"retain FR4 and require author-trust **and** CODEOWNER action, which would narrow D5"* — which is the literal reading wearing a conjunction: it makes the CODEOWNER's approval channel dead for precisely the population it was built for. **Rejected explicitly, so it is not re-proposed.**

**4. Dispositive: the human already ruled the authorization model, and named this exact mechanism.** #1539's 2026-09-10 ruling is the governing product constraint. Its headline is a necessary condition — *"No work happens without approval from the designated human (CODEOWNERS)"* — and its item 1 names the mechanism in terms that are Step D5 word for word:

> **Bring `STRATEGY_MILESTONE` up to actor verification, scoped to the CODEOWNERS human specifically** … Verify (via the issue's label/milestone-assignment event actor, same shape as `_verify_label_actor`) that the `needs-ai` label and/or milestone assignment **was applied by the designated human CODEOWNER** …

That is an authorization model, and the authorizing act it names — *a designated human CODEOWNER applying the label or the milestone* — is exactly the act FR4's literal text says "MUST NOT convert". Item 2 supplies the other half — *"A bot applying the label does not count, even the overseer or worker itself"* — which is FR4's real content and which I retain in full. **I do not have the standing to maintain a requirement that forbids the mechanism the human ruled**, and the honest resolution is not to re-litigate the ruling but to correct the requirement that over-reached past it.

### What I am NOT ruling

- Not that FR4 was wrong. FR4 is correct and load-bearing for the question it was written about; it is wrong only where it was applied to a second question.
- Not that AD-4 or D5 are free of defects. **P-1 is untouched by this ruling and remains blocking**, and the architect's reconciliation of AD-4's header may still need work (§4).
- Not anything about *which channel* (label event, milestone event, comment) may carry an authorization. That is AD-4/AM-6/AM-16 territory and it is the architect's.

---

## 2. AR-2 — What FR4 keeps: the structural barrier, restated so it cannot be quietly lost

The panel's sharpest sentence is a challenge I must answer squarely rather than define away:

> under D5, the only barrier between a stranger's issue body and the build chain is one human's judgement at label-click time. FR4 was the *structural* barrier.

**FR4 was never the barrier against that threat, and it still is not — it is the barrier against a different one.** The gate this requirements set specifies has **four** layers, and FR4 governs the first:

| Layer | What it stops | Requirement | Live in S2? |
|---|---|---|---|
| **1 — trust** | The stranger's request being treated as exempt because a *bot* (or a non-CODEOWNER trusted actor) touched its labels. This is VF-3 and #1539 item 2. | **FR1, FR2, FR3, FR4 (as amended), FR5, FR6** | **Yes** |
| **2 — authorization** | The request proceeding with *no* human decision at all. This is #1539's headline ruling. | **FR7, FR8, FR16, FR28** | **Yes** |
| **3 — assessment** | The human deciding layer 2 **blind** — no documented, public, machine-readable analysis of the request in front of them. | **FR11 – FR15, FR17, FR20, FR21** | **NO — S5** |
| **4 — content** | The issue body being believed once the request is authorized. #1539 item 3; VF-11; FR10. | **FR10, and `pm-agent.md`'s CORE untrusted-input rule** | **Yes (prose)** |

**Layer 1 is intact under this ruling.** A stranger's issue labelled `needs-ai` by the worker bot is still gated (TD F19). Labelled by `scottthurlow-claude[bot]` — still gated (F20). Labelled by a roster contributor who is not a CODEOWNER — still gated (FR2, FR16, AR-3 below). That is everything FR4 was written to do, and none of it moves.

**The panel's sentence is true of the S2 slice, and it is true because layer 3 is in S5 — not because this ruling deletes anything.** That distinction matters enormously for what the human is asked to clear, and it is the substance of my H1 delta (§3). Today, layers 1–4 are *all* absent: the live path has no check of any kind (VF-1, VF-2, VF-3). S2 turns on layers 1, 2 and 4. It does not turn on layer 3, so in the S2 era the human's judgement at label-click time genuinely **is** the only judgement in the loop — informed by no assessment, on an issue whose body is attacker-controlled. **That is a real, stated, time-bounded cost of the slice order, and the human must be told it in those words before they accept the standing obligation.** It is not a reason to prefer the origin-trust model, because the origin-trust model does not add a layer — it removes layer 2's ability to ever conclude, and leaves the repo with today's zero-layer intake for 92 of 96 issues while *looking* maximally strict.

**Six properties that make "authorized" observably weaker than "trusted".** These are not definitional cover; each is testable, and FR28 (AR-3) makes them binding:

1. **Scope.** Trust exempts *every* request from an author, standing, until the roster changes. Authorization releases **one issue, at one content state**. It exempts nothing else and no one else.
2. **No accumulation, ever.** No authorization event moves an author toward trust. The same author's *next* issue is gated identically, with no memory. This is §4's "automatic trust promotion" non-goal, now stated as a positive rule rather than an omission.
3. **Narrower actor set.** *Any* trusted-set member's authorship exempts their own request (FR2). Only a **verified individual human CODEOWNER** may authorize someone else's. A trusted app, a roster contributor, `copilot[bot]`, `github-actions[bot]` (AF-5) and the human-proxy App all may **not**.
4. **Never cached** (FR7). Trust is re-derived from a committed roster; authorization is re-derived live from GitHub-reported events at every selection, every cycle.
5. **Revocable, and it voids on content change** (FR9, FR10, AM-8). Trust is revoked by a human roster edit. An authorization is voided by an edit to the assessed content by any non-trusted actor — including the author. *(Deferred to S3 as a named residual; see AR-6.)*
6. **It is not a credibility claim.** An authorized request is *an untrusted-authored request a human chose to build*, not a trusted one. **#1539 item 3 applies to it unchanged**: its body is untrusted input to `pm-agent`, `architect` and `coder`, evaluated for what it asks, never taken as ground truth. AD-2's corollary already says this for bot-authored requests; FR28 says it for authorized ones.

---

## 3. AR-3 — The amended FR4, and two new requirements

### FR4 — REPLACEMENT TEXT (binding; supersedes `REQUIREMENTS-1540:273-280`)

> **FR4 — Trust attaches to the request's origin, not to the last actor who touched a label.** The trust determination MUST be a function of the **issue author** as reported by the GitHub API. **No label, milestone, or metadata change by any actor — human or bot, trusted or not — may confer trust on an untrusted-authored request or on its author.** In particular, the worker's own Step-0 triage labelling an anonymous issue `needs-ai` (**VF-3**) MUST NOT satisfy the trust test, and no sequence of such acts may ever promote an author into the trusted set (**FR3** is the only way in).
> **This requirement governs trust — exemption from the gate — and does not govern authorization — release from the gate.** A gated request may still be released, for that one request only, by an explicit act of a verified individual human CODEOWNER, under **FR16** and **FR28**. Such a release confers no trust on the request or its author (FR28), and the released request's content remains untrusted input (FR10).
> *Verify:* an issue authored by an untrusted account and labelled `needs-ai` **by the worker bot** remains gated and is not selectable as work; the same issue labelled **by the human-proxy App** remains gated; the same issue labelled **by a roster contributor who is not a CODEOWNER** remains gated; the same issue labelled **by a designated human CODEOWNER from their own account** is selectable — **and its author's next issue is gated exactly as before**; an issue authored by the worker bot itself under an enumerated machine-filing marker is trusted by authorship and is not gated.

**The original FR4 text is preserved verbatim in the requirements document**, marked as superseded with a pointer here. Nothing is rewritten in place.

### FR28 — NEW. Authorization releases one request; it never confers trust, and never accumulates.

> An authorization MUST be **per-request and per-content-state**: it makes exactly one issue, in exactly the title+body state that was authorized, eligible for selection. It MUST NOT make the issue's author trusted, MUST NOT make any other issue eligible, MUST NOT be recorded as a durable grant (**FR7** — it is re-derived live at every selection), and MUST NOT be usable as evidence toward trust in any later determination. The authorizing actor MUST be an individual human CODEOWNER, verified from GitHub-reported identity (**FR16**, **FR5**); no bot identity satisfies it, **including this deployment's own App identities** and including `github-actions[bot]` acting on a human's slash command. An authorized request's body and title remain **untrusted input** to every agent that reads them as a task specification (#1539 item 3, **FR10**).
> *Verify:* authorizing issue X does not make issue Y eligible; authorizing issue X does not make X's author trusted, and their next issue is gated; a static list, cache, flag or file recording "previously authorized" issues is non-compliant (**AD-13**, **FR24**); an agent consuming an authorized issue still treats its body as untrusted input.

### FR29 — NEW. The authorizing act MUST be legible as an authorization to the human performing it.

> Because the authorization is a **human judgement**, and in the S2 era (**AR-6**) the *only* judgement in the loop, every artefact that tells a CODEOWNER how to perform it MUST state plainly (i) that the act authorizes autonomous work to begin on that specific issue, (ii) that this **includes issues the CODEOWNER did not author and whose content they do not control**, and (iii) what the act does *not* do — it does not make the author trusted, and it does not make the issue body trustworthy. It MUST NOT be described only as a routing, triage or visibility action. This binds `docs/LABELS.md`, `docs/OVERSIGHT-RUNBOOK.md` (**panel P-3**), any cutover material (**AM-15**), and any agent instruction that describes the dispatch label.
> *Verify:* a reader of each such artefact can state, without opening another document, that applying the dispatch label from their personal account starts autonomous work on that issue; no such artefact describes the act as routing-only; a conformance test pins the statement in the durable documentation home the architect names (**panel P-6**).

**Why FR29 is the price of AR-1 and not an optional nicety.** Ruling the authorization model governs concentrates the whole gate, for the S2 era, into one human's act. An act the human does not know is an authorization is not a barrier; it is an accident waiting to be recorded as approval. AM-15 already requires the *mechanics* to be written down correctly ("remove, then re-add, from your own account"); FR29 requires the *meaning* to be written down beside them. Panel **P-3** found the operator runbook currently teaching a version of the act that post-S2 does nothing at all — the same class, one document over.

---

## 4. AR-4 / AR-5 — What does **not** change, and what the build document must now cite

### AR-4 — Unchanged by this ruling (stated explicitly, because a narrowing invites over-reading)

- **Step D5 does not narrow.** Its trust logic, its actor test, its bot exclusion, its milestone-title binding (AM-4) and its fail-closed branches are compliant with FR4 as amended. **No change to D5 is required by this ruling.** (D5 may still change for **P-1** — a different finding, the architect's.)
- **§2.7.4's operational act is permitted and unchanged.** The remove-then-re-add of the dispatch label from the CODEOWNER's own account is an **authorization** act, not a trust-conferring act, so FR4 as amended does not touch it. AM-14's lazy drain and single-digit primed head stand. **The human's operational burden is not changed by one act in either direction by this ruling** — which is the plainest evidence that AR-1 is the reading the whole design was already built on.
- **#1539's three ruling items** all stand, unmodified and unweakened. Item 1 is what AR-1 ratifies; item 2 is what FR4-as-amended retains; item 3 is what FR28's closing sentence and FR10 carry.
- **FR1, FR2, FR3, FR5, FR6** (layer 1) and **FR19, FR22, FR24, FR25** (fail-closed and anti-tamper) are untouched.
- **AD-1, AD-2 and its corollary, AD-3, AD-5, AD-13** are untouched. **AD-2's marker narrowing is unaffected**: it narrows *trust*, which is FR4's own dimension.
- **§4's non-goals** are untouched; "automatic trust promotion" is strengthened, being now a positive rule (FR28) rather than an absence.

### AR-5 — Traceability: the build document MUST cite the requirement it implements

P-2's second half is that **`TECHNICAL-DESIGN-1540` mentions FR4 zero times** — the conflict was unreconciled in the one document a `coder` builds from. Correcting FR4 does not fix that; a silent correction would leave the design citing nothing and the next reader re-deriving the same conflict.

> **Binding on `technical-design`:** §2.3's Step D table MUST cite, per step, the requirement each step implements — at minimum **D3/D4 → FR1, FR2, FR4 (as amended by this document), FR5**; **D5 → FR4 (as amended), FR7, FR8, FR16, FR28**; **Step F's gated-count line → FR27**. Where a step implements a requirement only **partially** because of the slice order, it MUST say so and cite AR-6's table rather than omitting the requirement. A design that implements a requirement without naming it is one revision away from implementing its opposite without noticing — which is exactly what P-2 found.

I am not specifying the format, the table shape, or where it lives. That is `technical-design`'s.

### AR-6 — The S2-era requirements baseline: which FRs are in force, and which are deliberately deferred

The requirements document was written for the whole mechanism; the ADR sliced it S1 … S6. **Nothing has ever written down which requirements a merged S2 does and does not satisfy**, which is how the design came to be silently non-compliant with FR17 (every S2 authorization is an approval with no assessment in existence, and it is silent) without any document recording it. This table states it. Rows marked **†** restate `ADR-1540` §3's slice table in FR terms; rows marked **‡** are dispositions this amendment adds because §3's table does not cover them.

| Requirement | In force on S2 merge? | Note |
|---|---|---|
| FR1, FR2, FR3, FR5, FR6 | **Yes** † | S1. |
| **FR4 (as amended), FR28** ‡ | **Yes** | Layer 1 + layer 2's non-accumulation property. |
| FR7, FR8, FR19, FR22 | **Yes** † | S2. |
| **FR29** ‡ | **Yes — shipping condition** | Delivered by AM-15's wording, `docs/LABELS.md`, and P-3's runbook fix. S2 MUST NOT merge without it (same standing as AM-6 point 3). |
| FR9 | **No — S3** † | **Named residual R-1**: an untrusted author may edit the title/body after a CODEOWNER authorizes, and S2 will not notice. `ADR-1540:325` already requires this in the S2 work item. **This ruling raises its weight**: it is now a residual on the *only* live barrier, and it must reach the human (§5). |
| FR10 | **Partly** † | The prose rule (#1539 item 3) is live; the digest binding that makes it mechanical is S3. |
| FR11 – FR15, FR20, FR21 | **No — S5** † | Layer 3. The assessor does not exist in the S2 era. |
| **FR16** ‡ | **In principle yes; its named channel does not work** | FR16 says `/approve` "MUST be reused or extended". **AF-5 proved `/approve` cannot authorize in S2** — the workflow writes as `github-actions[bot]`. The FR16 *property* (individual human CODEOWNER, server-side identity) is satisfied by the event-actor channel; the *channel* is S3's (AD-6, AM-6, AM-16). FR16 is **not** in breach; its implementation is deferred, and the requirement text now carries a pointer. |
| **FR17** ‡ | **No — S5, and this is an explicit deferral, not an omission** | FR17 says approving without an assessment MUST NOT be *silently* possible. In the S2 era **every** authorization is an approval without an assessment, because no assessor exists. That is a deliberate consequence of shipping the deterministic gate first (AF-1), it is strictly better than today's no-check intake, and **it must be ratified by the human rather than inherited by default** (§5). When S5 lands, FR17 binds in full and **Q4** must be answered first. |
| FR18 | **Partly** † | `/decline` exists; its binding to the gate is S3. |
| FR23 | **No — S6** † | Nothing expires into approval; nothing does today either, so no exposure. |
| FR24, FR25 | **Yes** † | Placement under `scripts/framework/**` satisfies FR25 (AF-3). |
| FR26 | **Structurally yes** ‡ | AD-4's rename-survivability property holds in S2; the documentation is S6. |
| FR27 | **Partly** † | Step F's summary and `ALL-CANDIDATES-GATED` lines are the S2 half (AM-13). |

**This table is a statement of the slice's requirement coverage, not a relaxation of any requirement.** Every deferred row is deferred to a named slice with a named closing requirement. A deferral that is written down is a residual; one that is not is a defect, and P-2 is what an undocumented one looks like after three revisions.

---

## 5. Escalation to the human — this ruling is **STRUCTURAL** and I do not treat it as cleared

**I am not authorized to settle this alone and I am not pretending to.** AR-1 narrows an existing MUST NOT and AR-3 adds two requirements including a new obligation on the human; under my role that is **structural**, and structural changes require the human's explicit sign-off. I have written the ruling rather than only proposing it because the panel, the architect and the design chain are all blocked on it and because every downstream document was already built on the model I am ratifying — but **`architect` and `technical-design` may proceed on it only as they proceeded on the original document's settled shape, and `coder` is not cleared by anything here.**

### H1 — the delta (for the **architect** to apply to `ADR-1540-AMENDMENT-2` §3(b)'s replacement text)

Panel §4's sequencing note asks whether P-2's resolution changes what H1 asks. **It does — by addition, not by revision.** H1's four items are **substantively correct as drafted and consistent with AR-1**: item 1 already describes the authorization model ("every request from outside the trusted set now waits for a human decision before any work begins"), and item 2 already describes the authorizing act. **No existing H1 item needs rewriting for P-2.** What is missing is that H1 nowhere tells the human *what they are the only barrier against, and for how long.* I ask the architect to add one item, and I have written it to be quoted verbatim:

> **(5) What your act is standing in for, until S5 ships — NEW.** The gate has four layers: (1) nobody outside the trusted set is exempt; (2) **you** personally authorize each outside request; (3) an assessor agent writes a public analysis of the request for you to read *before* you decide; (4) the request's body is treated as untrusted input by every agent that reads it. **S2 ships layers 1, 2 and 4. Layer 3 arrives in S5.** So in the S2 era your judgement at the moment you apply the label is the **only** judgement in the loop, and you are making it with no assessment in front of you, on an issue whose text was written by someone you do not control. This is still strictly better than today, where **none** of the four layers exists and any stranger's issue can be triaged and built with no check at all — but you should accept it knowing it, not discover it.
> **Two consequences you are being asked to accept with it:**
> - **An author can edit the issue after you authorize it, and S2 will not notice** (residual R-1; closed by S3's digest binding). What you read is not guaranteed to be what gets built.
> - **In the S2 era there is no "approve without an assessment" check**, because there are no assessments yet (FR17 is deferred to S5, `REQUIREMENTS-1540-AMENDMENT-1` AR-6). Every S2 authorization is one.
>
> **"Done" looks like:** an explicit yes/no, alongside items 1–4.

### The ratification question (new, mine — for the human, on #1540 or #1539)

> **Q10 (`pm-agent`, Amendment 1).** REQUIREMENTS-1540's FR4 as originally written forbids *any* actor — human or bot — from making an untrusted-authored request eligible by a label or milestone act. Your 2026-09-10 ruling on #1539 item 1 specifies exactly that act, by the designated human CODEOWNER, as the authorization test. Both were on the books as binding. **I have ruled in favour of your #1539 ruling and narrowed FR4 to the trust question only** (AR-1), keeping every part of it that stops a *bot* — including this deployment's own Apps — from laundering a label into eligibility (#1539 item 2).
> **The alternative I rejected**, and the cost of it: reading FR4 literally makes 92 of the 96 issues currently in the active milestone permanently unbuildable — **#1539 and #1540 among them** — and makes the approval channel this whole design is built around incapable of releasing anything.
> **Confirm the narrowing.** A "no" means the origin-trust model governs, in which case S2's purpose changes fundamentally and the design chain restarts from the ADR.

**Nothing in §3's FR4/FR28/FR29 binds `coder` until the human answers Q10 and H1.** The architect and `technical-design` may build revisions against it, as they have against every other held item in this chain.

---

## 6. Consequences for downstream documents

I have edited **only** `REQUIREMENTS-1540-request-intake-risk-agent.md` (the amendment banner, the FR4 supersession marker and replacement, FR28/FR29, and pointers at §3 seam 3, FR16 and §5). Everything below is for the architect and `technical-design`; I have deliberately not touched the ADR, the design or the panel artefact.

| Document | What this ruling requires of it | Owner |
|---|---|---|
| `ADR-1540` `:128` (the FR4 restatement bullet) | Narrow to match AR-3: "no actor — human or bot — confers **trust** by a metadata act." Today it reads as the literal FR4 and is cited as such. | `architect` |
| `ADR-1540` **AD-4** header — "(BINDING — FR4, FR5, FR7.)" | This is where P-2 began: the header *asserts* FR4 compliance rather than reconciling with it. Under AR-1 it is now true — but it should say **FR4 (as amended by REQUIREMENTS-1540-AMENDMENT-1), FR5, FR7, FR16, FR28**, so the next reader inherits the reconciliation rather than the assertion. | `architect` |
| `ADR-1540` **AD-5** / §3 `:325` (residual R-1) | Unchanged in substance; **weight raised** — R-1 is now a residual on the only live barrier, and it must appear in H1 item 5 and in the S2 work item (panel P-6 notes the S2 work item is still unidentified). | `architect` |
| `ADR-1540` §3 slice table | Reconcile with **AR-6**: the FR17 and FR16 rows are dispositions the slice table does not currently carry. | `architect` |
| `ADR-1540-AMENDMENT-2` §3(b) **H1** | **Add item 5** (§5 above, verbatim). No existing item needs rewriting for P-2. | `architect` |
| `TECHNICAL-DESIGN-1540` §2.3 Step D | **AR-5**: cite the requirement per step. FR4 currently appears zero times in 1,363 lines. | `technical-design` |
| `TECHNICAL-DESIGN-1540` §2.7.4, §2.7.2; `docs/LABELS.md`; `docs/OVERSIGHT-RUNBOOK.md` | **FR29**: the act's *meaning*, beside AM-15's mechanics. This lands in the same edit as panel **P-3** and needs the durable home **P-6** says AM-15's prohibition also lacks. | `technical-design` |
| `PANEL-1540` **P-2** | Answerable as **RULED** once the architect adopts this and applies the four rows above. It is not closed by this document alone: the design must cite the requirement (AR-5) before the defect P-2 names is actually gone. | panel / `architect` |
| `PANEL-1540` **P-1** | **Untouched and still blocking.** Nothing here changes evaluation order or the cap. | `architect` |

---

## Human Review Required

This document rules a conflict between two binding requirements and amends one of them, so per my role I self-flag.

**RISK: HIGH.** It is the one ruling in this chain that decides whether an untrusted-authored request can ever be built, on a public repository. The specific ways it can fail while looking correct: (i) **AR-1 being read as "a CODEOWNER's click makes the request trusted"** — it does not, and FR28's six properties are what stop it; anyone implementing a cache, a grandfathering list, or an author-promotion heuristic off the back of this ruling has inverted it (**AD-13**, **FR24** already forbid all three); (ii) **FR4's narrowing being widened by a later editor** into "metadata acts can confer trust", which re-opens VF-3 completely and is the exact hole #1539 item 2 closes — the amended text is written so the bot cases are stated positively rather than by implication, for this reason; (iii) **FR29 being dropped as documentation polish** — it is the requirement that makes layer 2 a barrier rather than a click, and with layer 3 absent until S5 it is load-bearing, not cosmetic; (iv) **AR-6's table being read as a relaxation** of the deferred requirements rather than a written-down statement of a slice's coverage — every deferred row names the slice that closes it, and a row moved to "deferred" without a closing slice would be a defect; (v) **H1 item 5 not reaching the human**, in which case they ratify a standing obligation without being told that for the S2 era they are the only judgement in the loop, which is precisely the failure AM-17 caught one document up.

**CONFIDENCE: HIGH** on AR-1's direction. It does not rest on my reading of a requirement: it rests on #1539's 2026-09-10 human ruling item 1 naming the label/milestone event actor as the authorization test — read live this session from the issue, not from a quotation — and on the panel's live measurement of 96/4. Both were re-derived rather than inherited. **HIGH** on AR-2's four-layer decomposition and on the claim that FR4 governs layer 1 only; the requirements document's own §3 seam 3 explains FR4 in exclusively bot terms, and that is the document arguing my case rather than me. **HIGH** on AR-4's "D5 does not narrow" — the operational act, the burden, and every row of the design's §2.6 worked trace are identical before and after this ruling, which is the strongest available evidence that I am ratifying the model the chain was already built on rather than choosing a new one. **MEDIUM-HIGH** on AR-6's table: the rows marked † restate the ADR's own slice allocation, but the four ‡ rows (FR4/FR28, FR29, FR16, FR17) are dispositions I am adding, and the FR17 row in particular asserts a deliberate deferral of a requirement **nobody has yet recorded as deferred** — if the architect reads FR17 as already satisfied by some mechanism I have not found, that row is wrong and I would rather be corrected than have it stand. **LOWER**, unchanged, on anything downstream of the uninspected live GitHub repository settings (**ESC-2 / H3**), and on **Q4**, which is unanswered and which FR17 waits on.

**BLAST RADIUS:** requirements documentation and the human-clearance text. Concretely: `REQUIREMENTS-1540` FR4 (narrowed), FR16 and §3 seam 3 (pointers), FR28 and FR29 (new); `ADR-1540` `:128`, AD-4's header, AD-5/§3's residual weighting and §3's slice table; `ADR-1540-AMENDMENT-2` §3(b) H1 (one added item); `TECHNICAL-DESIGN-1540` §2.3's Step D citations and §2.7.2/§2.7.4's wording; `docs/LABELS.md` and `docs/OVERSIGHT-RUNBOOK.md` (FR29, with panel P-3). **No code. No protected-surface file is edited by this document**; FR29's landing sites are documentation, and the five protected surfaces already enumerated in H1 item 4 are unchanged in number and identity by this ruling.

**Change classification: STRUCTURAL.** It narrows an existing MUST NOT, adds two requirements, and adds one item to what the human is asked to clear. Per my role it is escalated — **Q10 and H1 item 5, §5** — and it is **not** treated as cleared by my having written it. `architect` and `technical-design` may build revisions against it; **`coder` is NOT cleared to build S1 or S2**, and this document clears none of the gates that were outstanding before it: §3(a) A19's successor revision, §3(b) **H1** (now five items), §3(b) **H3**, and §3(c) the panel — which returned **DO-NOT-BUILD** and whose **P-1** is untouched here and still blocking.

**Provenance:** `pm-agent`, autonomous worker cycle, 2026-09-15, ruling PANEL-1540 **P-2** at the architect's dispatch. Every quotation above was read from this clone's working tree or from live GitHub this session; no exploit was attempted and no mutating GitHub write was performed.
