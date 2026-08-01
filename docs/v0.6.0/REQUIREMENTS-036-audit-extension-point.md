# REQUIREMENTS-036 — Audit recording as an extension point: a defined record-passing contract with a swappable backend, and a prototype-grade default implementation

**Status:** DRAFT for architect. **Supersedes REQUIREMENTS-035 / ADR-035 / TECHNICAL-DESIGN-035** (the deterministic *audit-approval-bot* design). The 035 bundle is superseded *before it merged* — it lives only on branch `docs/fable-consistency-finding` (commit `a03d441`) and never reached `origin/main` (verified), so there is no merged mechanism to unwind. This pivot is **structural** (it changes the audit-to-`main` mechanism, introduces a storage-backend extension point, and defines a new cross-consumer contract) and requires explicit human sign-off before `architect` binds it. Four product/policy decisions are escalated to the human (§6); architect may proceed on the settled requirements but MUST NOT bind the escalated points until the human rules them.
**Date:** 2026-08-01
**Author:** pm-agent
**Supersedes:** REQUIREMENTS-035 (FR1–FR19), ADR-035 (AD-1…AD-19), TECHNICAL-DESIGN-035. See §5 for the item-by-item carry/discard.
**Source direction:** the human's verbatim pivot direction (§1). Prior verification chain: REQUIREMENTS-035 §0 (VF-1…VF-7), ADR-035 §0 (AF-1…AF-5), and the ad-hoc dual-lens panel (`research/sessions/2026-08-01-audit-approval-bot-adhoc-panel.md`, commit `a03d441`).
**Target:** a `needs-ai` issue in the v0.7.0 milestone once the design chain (pm-agent → architect → technical-design) completes.
**Consumers:** `architect` (next), then `technical-design`.
**Scope note:** This document says WHAT and WHY only. No file layouts, no schema-as-code, no function signatures, no workflow mechanics, no GitHub-App permission scopes. Those belong to `architect` and `technical-design`. The record schema is specified here as *which fields must exist and what they mean*, never as a serialization. Every cadence/threshold value is a recommended default with a stated floor; binding values are the human's (§6).

---

## 0. Verification findings — where this pivot meets the repo

All load-bearing claims re-verified against `origin/main` this session (working tree is behind; citations are `git show origin/main:<path>`). `gh` is unauthenticated, so live-ruleset state and unread issue bodies are taken as given, as in 035.

**VF-036-1 — CONFIRMED: overseer *approving* (not authoring) makes all three required checks pass with no modification to any existing gate.** I read `require_overseer_approval.py` and `require_tier_ceiling.py` in full on `origin/main`.
- `require_overseer_approval.py:overseer_has_approved(...)` returns True whenever an `APPROVED` review exists whose login equals `BOT_OVERSEER_USERNAME`, **regardless of who authored the PR**. Overseer approving the audit PR satisfies this gate **directly** — no audit-only exception, no code change to the gate.
- `require_human_approval.py` — `audit/**` is not in `scripts/framework/protected_surfaces.txt` (035 VF-1, re-relied-upon) → the gate is N/A and passes for a pure audit diff.
- `require_tier_ceiling.py` — this is the gate that *now engages* (it returns early with "N/A (pass)" only when the overseer has **not** approved; here the overseer **has**). For an audit-only diff, `_simplified_tier` finds no `.claude/agents/` path and no `.py`/`.sh` file (audit records are `.jsonl`/`.json`/`.md`), so `code_files` is empty → **LOW**; `compute_tier` finds no validator summary and no `.py` head content to score → returns the LOW structural estimate. With `OVERSEER_CEILING` at its default `HIGH`, `LOW < HIGH` → **passes.**
- **Consequence, stated explicitly (this is the single biggest practical result of the pivot):** because the overseer *approves* rather than *authors*, **no protected-surface CI gate is modified at runtime.** 035's entire structural centrepiece — the FR11/AD-3 exception carved into `require_overseer_approval.py`, its Component C, and the fourth *approval-bearing* identity class (Component M) — is **deleted**, not merely revised. The audit-to-`main` runtime path needs **zero** gate exceptions.
- **One verified dependency (caveat):** the tier-ceiling pass holds only while `OVERSEER_CEILING >= LOW`. A consumer who set the ceiling to `SAFE` would see `LOW > SAFE` and the audit PR would fail-closed to human review. Default HIGH is safe; this is a config edge, not a defect. FR14 records it.

**VF-036-2 — CONFIRMED: HOS *reads its own audit log back* for operational control flow, and what it reads is not audit-of-record.** `oversight-evaluator` (its base/head-SHA computation), `scripts/oversight/lib/step_range.sh:_shr_preferred_head`, and `scripts/oversight/audit_conditional_proceed.sh` all reconstruct the event stream via the read-shim (`scripts/oversight/lib/audit_log.py:read_stream` / `audit_log.sh:audit_read_stream`) and grep it for `step-head` / `step-head-final` events to resolve each build step's base and head commit. **These reads are of the LOCAL `audit/log/**` directory, never of `main`.** This is decisive for the contract (§3, FR5): the audit log today is *overloaded* — it carries both (a) **operational control-flow state** that HOS reads back to make decisions, and (b) **write-only audit-of-record**. Only (b) is what the human wants to make swappable. Burdening a swappable WORM/SIEM backend with a query interface for (a) would be exactly the kind of storage-assumption leak this pivot exists to prevent.

**VF-036-3 — CONFIRMED: the current default already "proceeds unrecorded" by accident, and it does so *silently*.** `scripts/oversight/release_artifact_logic.py` writes its audit event best-effort and `warn`s but never fails on audit I/O error ("never fail the release gate on audit I/O"); and 035 VF-3 confirmed the aggregate logs do **not** reach `main` at all today. So HOS's *de facto* failure semantic is "proceed, unrecorded, quietly." This is tolerable in a prototype but is the exact behavior a real audit system must not have — which is why FR4 makes failure semantics an explicit part of the contract and §6-Q2 escalates the default's choice to the human.

**VF-036-4 — the 035 bundle is unmerged.** `research/sessions/2026-08-01-audit-approval-bot-adhoc-panel.md` and all three 035 docs exist only in `a03d441` on this branch, not on `origin/main` (verified). Superseding them costs nothing to unwind; the panel's *findings* (§5) still carry over as hardening requirements because they are true of any well-formed-audit-diff mechanism, including this one.

---

## 1. Context and the pivot

HOS has repeatedly tried to make git do something git is not good at: tamper-evident, role-enforced, WORM-grade audit storage. The 035 chain is the high-water mark of that effort — a deterministic approval bot, a shared predicate, an identity-bound gate exception, three ADR revisions and a dual-lens panel — and it is *still* a git/PR mechanism wearing production-audit clothing. The honest resolution, per the human:

> *"Let's treat audit as something extensible, like packs. The customer can bring their own audit solution that meets their security and integrity needs. We define a common way to pass on records to be recorded. We also provide a default implementation which is appropriate for a prototype system, but a real user would swap out for something more secure."*

> *"We live with security holes in our prototype and those get plugged with a real audit system."*

The design therefore has two clearly separated parts, and the discipline is to invest rigor **asymmetrically**:

- **The contract (§3) is where rigor goes.** It is the one piece that cannot be cheaply changed later — every consumer and every future backend (WORM store, SIEM, CloudTrail-style service, append-only RBAC database) depends on its shape. The failure mode to avoid is letting git's characteristics leak into the interface: if the contract says "records are appended to a JSONL file at path X," nothing else can ever implement it. The contract must be storage-agnostic.
- **The default implementation (§4) is explicitly disposable.** It is scoped as prototype-appropriate, ships with its security holes *documented as accepted* (§4.3), and a real deployment swaps it out. We do not re-litigate its shape (the human already fixed it: local append → sweeper collects into a PR → **overseer approves** → merge to protected `main`, zero bypass actors). We design the *requirements around it* so that it is a faithful, minimally-secure reference implementation of the contract — and so that swapping it out is genuinely possible.

**Why the audit backend is a driver/adapter behind a contract — not a pack (design position, justified, HOW deferred to architect).** The repo already does swappable-behind-a-boundary two ways, and this is neither of them cleanly:
- **Packs** (`packs/<name>/`, `pack.toml`, `PACK=` in `config.sh`) inject **prose regions** into agent `.md` files at install time. That is a documentation/prompt-templating mechanism. An audit backend is a **runtime functional sink** that receives records and stores them; there is no prose to inject. So the audit backend is **not pack-shaped** — "like packs" in the human's direction means *"a customer-swappable extension,"* not *"literally implemented as a pack."* Architect should not implement it as one.
- **`contract/OVERSIGHT-CONTRACT.md`** defines *what any compliant agent team must produce* — interface and artifact specifications. The **record schema, the pass-on operation, the failure semantics, and the read/query boundary belong here** (or in a sibling audit-contract document architect chooses). That part is genuinely contract-shaped.
- The **swappable implementation** (default vs. WORM vs. SIEM) sits *behind* that contract as a configured, conforming **driver/adapter**, selected the way `PACK=` is recorded in config — by configuration, not by editing HOS code. That is the third thing.

So: **contract-shaped at the interface, adapter/driver-shaped at the implementation, not pack-shaped.** FR1/FR6 state this as requirements; architect owns the concrete mechanism.

---

## 2. Functional requirements

Each FR is testable; the *Verify* line states the acceptance check. FRs are grouped: **the contract (FR1–FR7)** is the load-bearing set; **the default implementation (FR8–FR17)** is the disposable reference; **supersession (FR18)** reconciles 035.

### The contract — storage-agnostic record passing (the load-bearing set)

**FR1 — Audit recording is an extension point behind a defined, storage-agnostic interface.** HOS MUST pass records to be recorded through a single, defined boundary. No HOS component that *produces* an audit record, and no HOS component that *consumes* one, may assume the storage medium (file, git, PR, database, remote service) on the far side of that boundary. Swapping the backend MUST be possible without editing any record-producing or record-consuming HOS component.
*Verify:* the storage backend can be replaced with a conforming alternative (even a stub that only counts records) and every HOS component that emits or reads audit records continues to function unchanged; no producer/consumer source file names a concrete storage medium.

**FR2 — The audit record is defined independently of storage: mandatory fields, optional fields, and identity.** The contract MUST define what an audit record *is* as data, with no serialization or path in the definition. At minimum it MUST specify:
- **Mandatory:** a stable **event type**; a **timestamp** (UTC, unambiguous instant); an **actor identity** (which agent/identity produced the record, e.g. the deciding overseer/worker); and a **correlation key** sufficient to tie the record to the work it describes (e.g. the build step, cycle, and/or the commit/PR the decision concerns).
- **Optional / event-specific:** a free-form payload whose shape is keyed by event type; a **prior-record linkage** field where a backend wishes to chain records (the contract *permits* but does not *require* chaining, so a non-chaining backend still conforms).
- **Excluded:** no field may be defined in terms of a storage location (no "file path," "line number," "branch name," or "PR number" as a *mandatory* record field; such values may appear only inside the optional payload as data, never as the record's identity).
*Verify:* the record definition can be instantiated and validated with no filesystem, git, or network present; a record missing any mandatory field is rejected by the contract's own well-formedness rule; the definition names no serialization format as normative.

**FR3 — One pass-on operation; producers never address the store directly.** The contract MUST define exactly one operation by which HOS hands a record to the backend ("record this event"). Producers call only that operation. The operation's outcome MUST be observable to the caller (accepted / deferred / rejected — see FR4); a producer MUST NOT be able to write to the underlying store by any path that bypasses the operation.
*Verify:* every audit-record emission in HOS routes through the one pass-on operation; no producer contains a direct write to a storage medium; a producer receives a definite outcome from each call.

**FR4 — Failure semantics are part of the contract, and "proceed silently unrecorded" is not the contract default.** The contract MUST define what happens when recording cannot complete (backend unreachable, write rejected, capacity/quota, timeout). It MUST define, for each outcome, whether the calling HOS cycle **blocks**, **buffers-and-retries within a bound**, or **proceeds unrecorded** — and it MUST make the choice **explicit and observable**, never a silent side effect. A backend MUST be able to declare *blocking* semantics (a real audit system typically cannot proceed unrecorded); the contract MUST NOT hard-wire "proceed unrecorded." *The behavior the **default** picks is a product decision (§6-Q2); the requirement here is that the contract can express all three and that whatever is chosen is surfaced, not swallowed.*
*Verify:* with a backend configured to reject/blackhole a write, HOS exhibits the contract-declared behavior (block, or buffer-with-bound, or explicit-proceed-with-a-visible-marker) and produces an observable signal; there is no code path in which a recording failure is silently discarded with the cycle proceeding as if recorded.

**FR5 — Separate operational control-flow state from write-only audit-of-record; the swappable backend owns only the latter.** HOS reads its own audit stream back to make control-flow decisions (VF-036-2: `step-head`/`step-head-final` markers drive per-step base/head-SHA resolution in `oversight-evaluator`, `step_range.sh`, `audit_conditional_proceed.sh`). This operational state MUST NOT be delegated to the swappable audit-of-record backend — otherwise swapping in a write-only or remote store breaks step resolution. The contract MUST therefore either (a) keep operational control-flow state in a HOS-owned local tier that is always present regardless of the audit backend, **or** (b) if any operational read is delegated to the backend, define a **mandatory read/query capability** every conforming backend must implement. Option (a) is the recommendation (it keeps the swap cheap: the audit-of-record interface stays write-mostly); the boundary is a §6-Q3 decision.
*Verify:* with the audit-of-record backend swapped for a write-only stub, per-step base/head-SHA resolution and any other operational read still succeed; no HOS control-flow decision depends on querying the swappable backend unless the contract declared a mandatory read capability that the stub also implements.

**FR6 — Backend selection is configuration and conformance, not a code edit.** Which backend is active MUST be selected by configuration (analogous to how `PACK=` is recorded), and any backend MUST satisfy an explicit conformance definition (the FR2 schema, the FR3 pass-on operation, the FR4 failure declaration, and — if applicable — the FR5 read capability). Selecting or replacing a backend MUST NOT require editing HOS's core code.
*Verify:* changing the configured backend (default → alternative) requires only a configuration change; a backend that violates the conformance definition is detectably non-conforming (a conformance check fails) rather than silently mis-storing records.

**FR7 — No storage assumption may leak into the interface.** The contract's normative text (record schema, pass-on operation, failure and read semantics) MUST NOT reference git, pull requests, branches, JSONL, a specific directory, or any other characteristic unique to the default implementation. Any such characteristic that HOS depends on MUST be re-expressed as a storage-agnostic capability the contract requires, or moved into the default implementation where it is disposable.
*Verify:* a review of the contract text finds no git/PR/JSONL/path term in any normative (MUST/SHALL) clause; each capability HOS relies on is stated abstractly and is satisfiable by a non-git backend (demonstrated by at least the write-only stub of FR1/FR5).

### The default (prototype) implementation — the disposable reference

**FR8 — Ship a default backend, explicitly and prominently scoped as prototype-grade.** HOS MUST ship a working default audit backend so the system is usable out of the box, and it MUST be documented — at the point a deployer would configure it — as *appropriate for a prototype and expected to be swapped for a production-grade audit system* (WORM storage, SIEM, an audit service, or an append-only database with real RBAC). Its accepted limitations MUST be enumerated (FR16 / §4.3).
*Verify:* a fresh install has a functioning audit backend; its configuration surface and documentation state prominently that it is prototype-grade and list its accepted limitations with a pointer to how to swap it.

**FR9 — The default mechanism: local append → sweeper collects into a PR → overseer approves → merge to protected `main`, zero bypass actor.** The default backend MUST: (i) have record producers append locally (as they already do); (ii) have a separate **audit-sync sweeper** collect accumulated records into a pull request against the protected branch; (iii) have the **overseer approve** that PR; (iv) merge to `main` through an ordinary PR merge that satisfies every active branch-protection rule and required status check, with **no ruleset bypass actor and no direct push** anywhere in the path (honoring the #873 *"nobody direct to main, ever"* ruling).
*Verify:* with zero bypass actors on the `main` ruleset, a routine audit record reaches `main` via a PR merge that passed all required checks; the merge commit shows a checked-PR path, not a bypass; the approving review is the overseer's.

**FR10 — The three existing required checks pass natively; no existing protected-surface gate is modified.** Because the overseer *approves* (not authors), the default MUST satisfy `require-overseer-approval` (overseer approval present), `require-human-approval` (audit paths are not a protected surface), and `require-tier-ceiling` (an audit-only diff computes to LOW, at or below the default ceiling) **without carving any exception into, or otherwise editing the logic of, those three gates.**
*Verify:* the audit PR passes all three required checks with the checks' source unchanged from `origin/main`; no diff to `require_overseer_approval.py`, `require_human_approval.py`, or `require_tier_ceiling.py` is required for the runtime path.

**FR11 — The deterministic shape-check moves from *approver* to a *required status check*, and it verifies author identity.** The reason 035 used a deterministic (non-LLM) approver was that LLM reviewers are manipulable (`research/findings/adversarial-framing-attack-on-reviewer-agents.md`). Under this design the **overseer is the approver** (an LLM), so that mechanical guarantee MUST NOT be lost: a deterministic predicate MUST run as a **required status check** that independently confirms the audit PR is well-formed-audit-only, additions-only, targets the protected branch, **and is authored by the designated audit-sync/producer identity**. The overseer's approval then means what it should — the auditor attesting *"these are genuinely my records"* — while the machine guarantees the shape and origin. A PR that the overseer approves but that fails the deterministic check MUST NOT be mergeable.
*Verify:* an audit-shaped PR authored by any identity **other than** the designated producer fails the required status check even if the overseer approved it; a PR the overseer approves whose diff is not well-formed-audit-only fails the required check and cannot merge.

**FR12 — Author-identity binding closes the record-forgery hole (a limitation that MUST NOT be filed as accepted).** Under a diff-shape-only design, *anyone who can open a PR* could craft a well-formed audit append and it would qualify — forging the record of "what the overseer decided." (This gap survived 035's entire dual-lens panel undetected.) The mechanism MUST bind qualification to the designated producer identity (FR11), so a well-formed audit diff from a non-producer identity does **not** qualify. This is cheap to close and is therefore a **required control, not an accepted limitation.**
*Verify:* a well-formed audit-only PR opened by a non-producer identity is not approvable/mergeable through the unattended path; the audit trail cannot be appended-to on `main` by any identity other than the designated producer via this mechanism.

**FR13 — Carry over the six panel hardening rules.** The default predicate MUST enforce all six findings the ad-hoc panel produced against 035 (they are true of any well-formed-audit-diff mechanism): (a) **target branch MUST be the protected branch** — an audit PR against any feature/release branch does not qualify; (b) **patch-truncation fails closed** — if the diff/patch for any file with additions is truncated or absent, reject (reconcile parsed added-line count against the additions count); (c) **the audit path glob is extension-restricted** to the known-inert record formats, so a `.py`/`.sh`/dotfile whose bytes parse as JSON cannot qualify; (d) **zero-content changes are rejected** — file-mode, symlink, and file-type changes with no content additions do not qualify; (e) **the diff parser is robust** — a content line beginning with `+++` MUST be treated as added content and validated, never misparsed as a diff header and skipped; (f) **a periodic scheduled sweep is mandatory** — an event-only trigger cannot satisfy stuck-PR escalation (FR15), so a scheduled sweep of open audit PRs MUST exist. Each rule only *narrows* qualification.
*Verify:* one fixture suite exercises all six rules; each fixture that should be rejected is rejected; the scheduled sweep re-evaluates an open audit PR that was not touched by a new event.

**FR14 — Additions-only, well-formed, first-creation-aware, fail-closed.** A qualifying diff MUST only *add* audit records (first-time creation of an as-yet-untracked audit file counts as all-additions and qualifies; any modification or deletion of an existing audit record disqualifies — rewriting the record of what the overseer decided is categorically worse than appending a junk line). Every added entry MUST be structurally valid for its format. Anything the predicate cannot decisively classify MUST be treated as **not** qualifying. No configuration knob may *widen* what qualifies; knobs may only narrow. *Note the verified config edge (VF-036-1): the native tier-ceiling pass depends on `OVERSEER_CEILING >= LOW`; a `SAFE` ceiling correctly fails the audit PR closed to human review rather than opening a hole.*
*Verify:* a diff that modifies or deletes an existing audit line does not qualify; a malformed added entry does not qualify; an unclassifiable diff does not qualify; no env var/label/PR-body setting turns a non-qualifying diff into a qualifying one.

**FR15 — Bounded freshness; stuck audit PRs escalate visibly; never indefinitely blocked.** Audit records MUST reach the backend within a bounded lag (batching per cycle is permitted; the maximum lag is bounded). If an audit PR cannot merge (a check errors, checks stay non-green, or a conflict arises), it MUST escalate to a human after a bound, and the growing backlog of unrecorded audit history MUST be observable, not silent. The mechanism MUST NOT leave a produced record unable to ever reach the backend. Exact cadence and lag bound are a §6 decision (Q1).
*Verify:* a record produced in a cycle appears in the backend within the configured bound; an audit PR whose required check errors produces a tracked human escalation; the backlog is observable.

**FR16 — The default's accepted limitations are documented as accepted, and only the genuinely-inherent ones qualify.** The default backend MUST ship with an explicit **accepted-limitations register** (§4.3). A limitation may be filed as *accepted* only if it is inherent to any prototype-grade, same-trust-domain, git-based store; a limitation that is cheap to close MUST be closed, not accepted. The register MUST state, for each accepted item, that a production audit backend is expected to remove it.
*Verify:* the register exists and enumerates each accepted limitation with a one-line justification of why it is inherent and how a real backend removes it; no item that FR12 (author-identity) or FR13 (the six hardening rules) requires closing appears as "accepted."

**FR17 — The default's self-recording rides the same path; the sweeper/producer is a named component with a durable heartbeat.** The audit-sync sweeper and the local producer are HOS-owned default-implementation components (not part of the contract). The sweeper's own actions (what it collected, approved-and-merged, or escalated, and why) MUST themselves be recorded through the pass-on operation so the default is self-auditable, and the sweeper MUST emit a durable "last successful sync" marker so staleness beyond the FR15 bound is observable. The sweeper MUST NOT depend on the old, never-built `audit-log`-branch bypass scaffolding (035 VF-3/VF-4: it does not exist on `main`).
*Verify:* the sweeper's decisions are themselves recorded via the pass-on operation; a "last successful sync" marker is present and its staleness is observable; the sweeper references no bypass/`audit-log`-branch scaffolding.

### Supersession

**FR18 — Supersede the 035 bundle; carry the hardening and mechanics, discard the approval-identity machinery; reconcile the standing bypass docs.** This document supersedes REQUIREMENTS/ADR/TECHNICAL-DESIGN-035. **Carried:** the deterministic predicate (re-homed as a required status check, FR11), the six panel hardening rules (FR13), additions-only/fail-closed (FR14), the sweeper/producer mechanics and the mandatory scheduled sweep (FR9/FR13f/FR17), and the 035 removal of the `hos-auditsync-hos` *"Ruleset bypass + direct push to main"* setup path (`DECISIONS.md` 2026-06-23; `MACHINE-ACCOUNTS-SETUP.md` Steps 5–6; `OVERSIGHT-RUNBOOK.md` Phase 11) — every documented instruction that adds a bypass actor or pushes audit logs directly to `main` MUST still be removed, with a detect-and-remove step for already-deployed consumers, and `DECISIONS.md` MUST carry a new dated superseding entry (append-only). **Discarded:** the fourth *approval-bearing* identity class and its `AGENT-IDENTITY.md` amendment (Component M), the `require_overseer_approval.py` exception (AD-3 / Component C), and the "overseer authors the PR" premise — because the overseer *approves* (charter-consistent: overseer is the PR review/merge authority) and a distinct producer identity *opens* the PR.
*Verify:* no committed doc instructs adding a ruleset bypass actor or pushing audit logs directly to `main`; a new dated `DECISIONS.md` entry supersedes the 2026-06-23 entry without editing it in place; the runtime mechanism contains no `require_overseer_approval.py` exception and no fourth approval-bearing identity.

---

## 3. The three contract questions the old design never had to answer

Because git was the only answer under 035, these were never surfaced. They are the heart of this document.

**Q-Schema — what an audit record *is* (FR2).** A record is *event type + UTC timestamp + actor identity + correlation key*, plus an optional event-keyed payload and an optional prior-record linkage. Storage location is never part of a record's identity. This is stated so a WORM store, a SIEM event, or a database row can each carry the *same record* — only the serialization differs.

**Q-Failure — what happens when the sink cannot record (FR4).** The contract must be able to express **block**, **buffer-with-bound**, and **explicit-proceed-with-a-visible-marker**, and must forbid *silent* proceed-unrecorded. A production backend will typically declare *block*. The **default's** choice is a genuine product decision (§6-Q2): today HOS proceeds silently (VF-036-3), which is prototype-acceptable but must be a *chosen, visible* behavior, not an accident.

**Q-Read — what reads back, and whether the swappable backend must serve reads (FR5).** Something *does* read: HOS resolves per-step base/head SHAs from `step-head`/`step-head-final` markers in the local audit stream. The correct resolution is **not** to burden the swappable backend with a query interface, but to recognize that these markers are **operational control-flow state overloaded into the audit log**, and to keep that state in a HOS-owned local tier that is always present — leaving the swappable audit-of-record interface write-mostly and therefore cheap to swap. (This is a refinement of the brief's "if something reads, define that too": something reads, but it should be *separated out* rather than pushed into the backend contract. The separation boundary is §6-Q3.)

---

## 4. The default implementation, in one place

### 4.1 Mechanism (FR9–FR15, FR17)
Local producers append records → the audit-sync sweeper batches accumulated records into a PR against protected `main` → the overseer approves → a deterministic **required status check** confirms well-formed-audit-only + additions-only + target-is-`main` + **author-is-the-producer** → ordinary PR merge, zero bypass actor. A scheduled sweep re-checks open audit PRs and escalates stuck ones. The three existing required gates pass natively (FR10).

### 4.2 Why this is minimally-secure, not secure
The overseer (an LLM) attests *authorship of the records*; the deterministic required check (a machine) guarantees *shape and origin*. Neither alone can merge a bad record: a manipulated overseer approval is still blocked by the required check; a well-formed forgery from a non-producer identity is blocked by the author-identity binding. That is the floor a prototype needs. It is **not** WORM, it is **not** cross-trust-domain, and it does **not** make the overseer's *content* trustworthy — see §4.3.

### 4.3 Accepted-limitations register (FR16)

**Inherent to a prototype-grade, same-domain, git-based store — ACCEPT and DOCUMENT (a production backend removes each):**
| # | Accepted limitation | Why inherent here | How a real backend removes it |
|---|---|---|---|
| L1 | **The overseer self-attests its own records.** An auditor can produce a false-but-well-formed record; no git arrangement fixes an auditor lying in its own report. | The producer of the decision is also the attester of the record. The deterministic check bounds *shape and origin*, not *truthfulness of content*. | External, independently-controlled ingestion (SIEM/CloudTrail-style) where the recorder cannot alter what a separate control plane received. |
| L2 | **Records live in the same trust domain as the code being audited.** They sit on the same repo/`main`, under the same access as the system under audit. | The default stores audit-of-record in the very repo it audits. | A separate-domain WORM store or audit service outside the audited system's control. |
| L3 | **Append-only-by-convention, not WORM.** Git history can be rewritten by a sufficiently privileged actor; "additions-only" is enforced at the PR gate, not by the medium. | Git provides no write-once medium; protection is procedural (the predicate + branch protection), not physical. | True write-once (WORM) or immutable-ledger storage. |

**Cheap to close — MUST NOT be filed as accepted (required controls, FR12/FR13):**
- **The missing author-identity check** — closed by FR11/FR12 (bind qualification to the producer identity). *Not accepted.*
- **The six panel hardening rules** (target-branch, patch-truncation, extension-restricted glob, zero-content/mode/symlink rejection, `+++`-parser, mandatory scheduled sweep) — closed by FR13. *Not accepted.*

---

## 5. Item-by-item reconciliation with 035

| 035 item | Disposition here |
|---|---|
| Deterministic predicate (shared, tested) | **Carried**, re-homed from *approver* to a **required status check** (FR11). |
| Six panel hardening rules (AD-17) | **Carried** as FR13. |
| Additions-only / fail-closed / first-creation (AD-6/AD-9) | **Carried** as FR14. |
| Sweeper/producer mechanics + mandatory scheduled sweep (AD-15/AD-18) | **Carried** as FR9/FR13f/FR17. |
| FR17 bypass-doc removal + `DECISIONS.md` supersession + consumer remediation (AD-8/AD-19a) | **Carried** as FR18. |
| Panel artifact (`research/sessions/2026-08-01-…-panel.md`) | **Carried** as evidence (its findings → FR13). |
| `require_overseer_approval.py` exception (FR11/AD-3, Component C) | **Discarded** — overseer approves natively (VF-036-1). |
| Fourth *approval-bearing* identity class + `AGENT-IDENTITY.md` amendment (AD-16, Component M) | **Discarded** — the approver is the existing overseer; the producer is a non-approving identity (see §6-Q4). |
| "Overseer authors the audit PR" (FR2/AD-16 saga) | **Discarded** — overseer approves (charter-consistent); a producer identity opens the PR. |
| Structural sign-off *for the gate exception* | **Discarded as a runtime concern** — no gate is modified. (A structural sign-off is still required for *this pivot's* contract + doc changes; see the self-flag.) |

---

## 6. Product decisions escalated to the human

Genuine product/policy choices I cannot settle from the spec. Architect MUST NOT bind them until ruled; a recommended default is given for each.

**Q1 — Cadence and maximum lag (FR15).** *Recommendation:* one audit PR per cron cycle, batching that cycle's records, with the batch on the backend by end of the next cycle. *Human owns:* per-cycle vs. per-entry, and the maximum acceptable lag.

**Q2 — The default's failure semantic (FR4).** *This is the genuine product decision the brief flagged as likely the human's, and I agree it is.* The contract must express block / buffer-with-bound / explicit-visible-proceed; the **default** must pick one. *Recommendation:* **buffer-locally-with-a-bound and escalate on stuck** (records accumulate locally, the sweeper carries them, and a stuck backlog escalates per FR15) — never silent proceed. A stricter *block-the-cycle* default would halt the autonomous loop on any audit-sync hiccup, which is likely too aggressive for a prototype. *Human owns:* whether the prototype default may proceed-with-a-visible-marker when the backend is unreachable, or must block; and whether a production backend's declared *block* is honored by the same cycle-halting path.

**Q3 — The operational-state / audit-of-record boundary (FR5).** *Recommendation:* keep `step-head`/`step-head-final` and any other control-flow markers in a HOS-owned local tier that is always present, and scope the swappable backend to write-mostly audit-of-record (no mandatory query interface). *Human owns:* confirmation of that split, or a decision to require every backend to implement a read/query capability (more burdensome to swap, but keeps a single store).

**Q4 — The producer identity (FR9/FR11).** The sweeper opens PRs; it never approves. *Recommendation:* run the sweeper under the existing **worker** identity (the worker class *"opens PRs, never approves"*), so no new identity class is introduced and the discarded Component M stays discarded. *Human owns:* whether the audit-sync sweeper is the worker identity or a distinct producer/transport identity — and if distinct, note it still needs a *lighter, non-approval* `AGENT-IDENTITY.md` reconciliation (a producer identity, not the discarded approval-bearing fourth class).

---

## Human Review Required

This document authors new requirements and a new cross-consumer contract (a MEDIUM-or-above spec change), so per my role I self-flag.

**RISK: MEDIUM.** The pivot *reduces* runtime risk relative to 035 (no protected-surface gate exception; the three required checks pass natively — VF-036-1) and closes a real forgery hole 035's panel missed (FR12). The residual risk is in the **contract**, not the default: a contract that leaks a storage assumption (FR7) or under-specifies failure/read semantics (FR4/FR5) would lock every future backend into git's shape — the single most expensive thing to get wrong, because the contract is the one piece that cannot be cheaply changed. Those are exactly the failure modes FR2/FR4/FR5/FR7 are written to close. The default itself ships with documented, accepted security holes by explicit human direction — defensible only because they are enumerated as accepted (FR16 / §4.3) and the cheap-to-close ones are *not* among them.

**CONFIDENCE: HIGH** on the requirement set and on the two load-bearing verifications I did this session against `origin/main`: (VF-036-1) overseer-approves makes all three required checks pass with no gate edit — I read `require_overseer_approval.py` and `require_tier_ceiling.py` in full and traced `_simplified_tier`/`compute_tier` to LOW for an audit-only diff; and (VF-036-2) HOS reads its own audit log back for step-SHA resolution. **LOWER** on the four escalated decisions (§6), which are correctly the human's, and on anything downstream of the still-unread issues (#873/#1095/#1151) and the unverified live-ruleset state — `gh` is unauthenticated here, the same gap 035 flagged.

**BLAST RADIUS:** the audit trail's integrity and the audit-to-`main` mechanism on every consumer deployment, and a new cross-consumer contract that every future audit backend must honor. The default implementation touches `scripts/framework/**` (a new predicate + a new required-check workflow), `machine-accounts.env`, and the bypass-doc reconciliation set — all protected surfaces — so the implementation PR is human-approved at merge regardless of tier (as 035's AD-11 held).

**Change classification: STRUCTURAL.** It changes the audit-to-`main` mechanism, introduces a storage-backend extension point, defines a new cross-consumer contract (record schema, pass-on operation, failure and read semantics), and supersedes a standing (unmerged) design plus a standing `DECISIONS.md` bypass entry and its setup docs. Per my role and the CORE product-boundary checkpoint, the structural change and the four §6 decisions require explicit human sign-off before `architect` binds them. Architect may begin design against the settled shape of FR1–FR18 now (the contract's storage-agnostic interface, the default's mechanism, the carried hardening) but MUST NOT bind the cadence/lag (Q1), the default failure semantic (Q2), the operational/audit-of-record boundary (Q3), or the producer identity (Q4) until the human rules them.
