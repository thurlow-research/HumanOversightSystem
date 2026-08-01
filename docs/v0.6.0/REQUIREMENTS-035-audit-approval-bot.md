# REQUIREMENTS-035 — Deterministic audit-approval bot: audit-log commits reach `main` through a real, checked PR with no bypass actor

**Status:** DRAFT for architect. Seven product decisions escalated to the human (§5); architect may
proceed on the settled requirements but MUST NOT bind the escalated points until the human rules
them. One change is **structural** (it supersedes a standing `DECISIONS.md` entry and adds an
exception to a protected-surface CI gate) and requires explicit human sign-off before `architect`
binds it.
**Date:** 2026-08-01
**Author:** pm-agent
**Source issues:** #1151 (open, Backlog — the design as currently captured, primary source);
#1095 (open, critical — the interim broken direct-commit path); #873 (closed — the "nobody direct
to main, ever" ruling and the audit-record carve-out).
**Target:** a `needs-ai` issue in the **v0.7.0 — Quality** milestone once the design chain
(pm-agent → architect → technical-design) completes. The human has asked to promote this out of
Backlog and schedule it.
**Consumers:** `architect` (next), then `technical-design`.
**Scope note:** This document says WHAT and WHY only. No code, function signatures, file layout,
GitHub-App permission scopes, or workflow mechanics are specified here — those belong to `architect`
and `technical-design`. Every cadence/threshold *value* below is a recommended default with a stated
floor; the binding values are the human's (§5).

> **Correction note — 2026-08-01 (post-ADR-035 Revision 3 / AD-16).** ADR-035's Revision 3 ruling
> **AD-16** found **FR2 factually wrong.** The overseer authors no PRs today —
> `origin/main:.claude/agents/overseer.md:7`: *"Never opens branches or PRs; only evaluates and acts on
> artifacts the worker produced"* (re-verified this session) — so FR2's premise *"no change from how
> overseer authors records today"* is false, and as written FR2 would require the overseer to violate
> its own charter. Per **AD-16 (binding, not re-litigated here)** the **worker** identity authors the
> audit PR (charter-consistent — `docs/AGENT-IDENTITY.md` line 86: the worker class *"opens PRs, never
> approves"*); the deterministic auditsync bot still approves (AD-3, unchanged — it keys on
> qualify + auditsync-approval, never on the author). The corrected FR2 reading, the confirmation that
> this creates no new self-review conflict, and the full whole-document sweep for this premise are in
> the dated note appended to **FR2** in §2. Original text throughout is left intact per append-only
> correction discipline.

---

## 0. Verification findings — where the design-as-described meets the repo

I verified every load-bearing claim in the #1151 design against `origin/main` (this session's working
tree is ~10 commits behind, so all citations are `git show origin/main:<path>`). Seven findings
change the design rather than merely confirm it. Two of them contradict the premise as stated.

**Verification gap (stated up front).** `gh` is unauthenticated in this sandboxed session, so I could
**not** independently hit the live ruleset API (`repos/.../rulesets/18044233`) to confirm the
"zero bypass actors" state, and could **not** read the bodies of #873, #1095, or #1151. Those three
facts are taken as given from the task brief. This matters because VF-2 below shows the *committed
setup documentation* asserts the opposite (a bypass actor exists by instruction), so the live-vs-doc
divergence is itself a finding, not a settled fact. GitHub's API-level rejection of self-approval is
a platform behavior also taken as given.

**VF-1 — CONFIRMED: the three required checks behave as the design needs, but require-tier-ceiling's
stated reason is wrong (and the correct reason is stronger).**
- `require-human-approval` (`require_human_approval.py`) is path-based and re-derived from the diff.
  `audit/**` is **not** in `scripts/framework/protected_surfaces.txt` (verified — the list is
  `.claude/agents/**`, `contract/**`, `scripts/framework/**`, `bootstrap/**`, workflows, release
  artifacts, etc., with no `audit/` entry). So a pure audit-log diff auto-passes this gate. **Confirmed.**
- `require-overseer-approval` (`require_overseer_approval.py`) passes only when an `APPROVED` review
  exists whose login case-insensitively equals `BOT_OVERSEER_USERNAME` (`hos-overseer-hos[bot]`,
  verified in `machine-accounts.env`). There is **no** audit-only exception today. **Confirmed** —
  and this is the one check the design must amend.
- `require-tier-ceiling` (`require_tier_ceiling.py`): the design says it "floors on code extensions
  (`.py/.js/.ts`) which audit files don't match, so it passes trivially." **This reason is inaccurate.**
  The gate returns `0` at `main()` the moment `overseer_has_approved(...)` is false — *"ceiling gate
  N/A (pass)"* — **before any tier computation or extension logic runs at all.** In this design the
  overseer is the PR *author* and never approves, so the ceiling gate passes trivially for that
  reason, and the extension floor is never reached. The correction matters twice over: (a) it removes
  the design's own "expected (not fully verified)" caveat — the pass is now fully explained and
  verified; and (b) it means the design does **not** depend on audit files having non-code
  extensions. `audit/overnight-loop-log.md` is a `.md` file, and the extension-floor theory would have
  wrongly implied its presence in a diff mattered. It does not.

**VF-2 — CONTRADICTS THE PREMISE: the committed setup docs instruct creating exactly the bypass actor
this work item exists to remove. "Repurpose an idle app" understates the scope — the old design must
be actively deleted.** `DECISIONS.md` (2026-06-23 entry) and `docs/MACHINE-ACCOUNTS-SETUP.md`
(Steps 5–6) are not dormant notes about an "idle/unused" app. They are live, human-facing setup
instructions that say, verbatim: audit logs are *"synced to main via a GitHub Actions workflow …
That workflow pushes directly to main, bypassing the PR requirement"* and *"Bypass list → Add bypass →
search `hos-auditsync-hos` → set mode **Always**."* Anyone following the current onboarding docs
**reintroduces the bypass actor** and the direct-to-main push. The new mechanism therefore does not
merely "repurpose" an idle identity; it must **supersede and remove** a documented setup path that
directly contradicts the #873 ruling. FR16 makes the removal in-scope and load-bearing.

**VF-3 — CONTRADICTS "idle/unused" as "harmless": the 2026-06-23 sync was never wired, and the
aggregate logs never reach `main` at all today.** On `origin/main`: `audit/oversight-log.jsonl` and
`audit/overnight-loop-log.md` are **not tracked**; only the legacy per-event format `audit/log/**`
(and `audit/2026-06-14-self-3p-eval.md`) is committed. There is **no** audit-sync workflow —
`.github/workflows/` contains only `require-human-approval.yml`, `require-overseer-approval.yml`,
`require-tier-ceiling.yml`, `label-swap.yml`, `shellcheck.yml`, `validation-check.yml`. So the
2026-06-23 GitHub Actions sync described in `DECISIONS.md` was **specified but never built**. The
current state is the #1095 broken state: the two aggregate audit logs are produced locally by the
autonomous loop and **do not reach `main`**. This design is therefore superseding a *partially-designed,
never-completed* mechanism, and it must handle the **first-time introduction** of these files to
`main`, not merely their ongoing sync.

**VF-4 — the "gitignored from feature PRs" half of the old design was also never implemented, which
happens to help.** `.gitignore` on `origin/main` contains **no** `audit/` entry (verified). The
2026-06-23 claim that audit logs are "gitignored from feature PRs and synced to main" is not the
current reality. This is convenient for the new design — the overseer can commit audit records into a
PR branch without fighting a gitignore rule — but the design MUST NOT *assume* the old gitignore /
`audit-log`-branch scaffolding exists, because it does not.

**VF-5 — there is already an "audit files are not code" exemption precedent to build on, not invent.**
`overseer.md` (§ around line 208) already enumerates *exempt files (not code)* for its
artifact-staleness check: `audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`, and any path
under `audit/automation/`. So the notion "these specific audit paths are inert records, not code" is
already an established, enumerated concept in the codebase. The new predicate should reconcile with
that existing list rather than coin a competing definition (this is the same single-source-of-truth
discipline VF-6 demands).

**VF-6 — the shared-predicate requirement is correct and is the #1135 duplicate-gate class; make it a
first-class FR, not a note.** The design says the audit-only predicate must be "one shared, tested
function" used by both the bot's approve decision and the `require_overseer_approval.py` exception.
This is right and is load-bearing: two independent copies would reproduce the duplicate-tier-gate
defect already flagged in #1135, and here the two copies would drift into a state where the bot
approves something the CI gate rejects (or worse, the reverse). FR5 elevates this to a hard requirement
with an equivalence test.

**VF-7 — the CI exception must be positively identity-bound, or it opens a hole the design does not
name.** The design describes the exception as recognizing audit-only diffs. Stated loosely — "audit-only
diffs don't need overseer approval" — this would let *any* audit-only PR merge with **zero** review
from anyone. The exception must require **both** (a) the diff qualifies as audit-only under the shared
predicate **and** (b) an `APPROVED` review exists from the *specific* audit-approval identity. A waiver
keyed only on the diff shape is a fail-open. FR10 states this positively.

---

## 1. Context

Overseer records what it decided — merge authorizations, human-required escalations, cycle
outcomes — to append-only audit files (`audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`,
and the legacy per-event `audit/log/**`). The #873 ruling is absolute: **"Nobody does direct to
main. Ever."** The human confirmed one carve-out afterward: audit-log entries are *records*, not
*changes*, and need "a path" that is not the full worker → PR → human-review cycle — because gating
the record of "what overseer decided" on review *before the record exists* is incoherent.

The tension the design resolves: the record must reach `main` (a) through a **real, checked PR** with
**no bypass actor** anywhere in the path (honoring #873 and the current zero-bypass ruleset), yet
(b) **without** a human in the routine loop and **without** the overseer being able to approve its own
PR (GitHub rejects self-approval, and `require-overseer-approval` demands an approval from the
overseer login specifically — which the overseer, as author, cannot supply).

The resolution is a **separate, dedicated, deterministic identity** — the *audit-approval bot* — that
approves the overseer's audit PR. Because approver ≠ author, there is no self-approval conflict; because
the approver is deterministic Python reviewed by a human (not an LLM), its trust comes from code review
of a small tested function, and it is structurally immune to the adversarial-framing-attack class the
repo has documented against LLM reviewers
(`research/findings/adversarial-framing-attack-on-reviewer-agents.md`). The scope is deliberately
narrow and is **not** a general "deterministic bots may approve PRs" precedent: it is defensible
*only* because audit-log entries are inert data — nothing imported, nothing that changes agent
behavior — so a malformed or malicious audit entry has categorically lower blast radius than any code
change.

---

## 2. Functional requirements

Each FR is testable; the *Verify* line states the acceptance check. "The audit PR" means a
pull request whose diff the shared predicate (FR5) classifies as audit-only-and-well-formed.

### No-bypass, author/approver separation

**FR1 — No bypass actor anywhere in the routine path.** Audit-log entries MUST reach `main` only
through a pull request that satisfies every active branch-protection rule and every required status
check. No ruleset bypass actor, no admin "merge without waiting for requirements" override, and no
direct push MUST be part of the routine audit-to-main path.
*Verify:* with **zero** bypass actors configured on the `main` ruleset, a routine audit record still
reaches `main`; the merge commit's path shows a PR merge passing all required checks, not a bypass.

**FR2 — Overseer authors the audit PR and MUST NOT approve it.** The audit PR is opened under the
overseer's own identity (no change from how overseer authors records today). The overseer identity
MUST NOT be the approving reviewer of its own audit PR, and the mechanism MUST NOT require an
overseer approval to merge an audit PR.
*Verify:* the audit PR author is the overseer bot; no `APPROVED` review from the overseer identity is
present or required on the merged audit PR.

> **Correction — 2026-08-01 (ADR-035 Rev 3 / AD-16; corrects the author identity of FR2 above; original
> FR2 text left intact).**
>
> **What changes.** The audit PR is authored by the **worker** identity, **not** the overseer.
> AD-16 verified against `origin/main:.claude/agents/overseer.md:7` that the overseer *"Never opens
> branches or PRs,"* so FR2's original *"opened under the overseer's own identity (no change from how
> overseer authors records today)"* is doubly false — the overseer authors **no** PRs today, and **no**
> audit records reach `main` today (VF-3). Corrected reading of FR2:
> - The audit PR is opened under the **worker's** identity (charter-consistent —
>   `docs/AGENT-IDENTITY.md` line 86: the worker class *"opens PRs, never approves"*). The overseer is
>   uninvolved in the PR; it only produces the local audit records, which it already does, and each
>   record still names the deciding agent, so nothing is lost by the worker being the git author/transport.
> - The **worker** identity MUST NOT be the approving reviewer of its own audit PR, and the mechanism
>   MUST NOT require a worker approval to merge it.
> - *Verify (corrected):* the audit PR author is the **worker** bot; no `APPROVED` review from the
>   **worker** identity is present or required on the merged audit PR. The approving review comes from
>   the auditsync bot (FR3).
>
> **No new self-review conflict — confirmed.** Approver (the auditsync bot, a distinct fourth identity
> class per AD-16) ≠ author (worker), so there is no self-approval. And the worker **never approves
> anything in this path**: per `docs/AGENT-IDENTITY.md` line 86 the worker class *"opens PRs, never
> approves,"* and here it only authors/transports the audit PR — it approves neither its own nor any
> other PR in this mechanism. Moving authorship overseer→worker therefore introduces **no** self-review
> conflict; it also satisfies FR3, which independently requires the approving identity to be disjoint
> from the worker.
>
> **Why the rest of the FR set is unchanged.** The load-bearing gate behavior does not depend on *who*
> authors: `require_tier_ceiling` still passes trivially because the overseer never approves an audit
> PR (VF-1 — true regardless of author), and `require_overseer_approval` still fails absent an overseer
> approval — exactly what FR10's auditsync-approval exception converts to a pass. The author switch
> changes the *reason* the overseer gate is unsatisfied (the overseer is simply uninvolved, rather than
> being blocked from self-approving), not the *fact*, so FR5/FR10 and the remaining FRs stand.
>
> **Whole-document sweep — where else the "overseer authors" premise appears (per the correction task's
> check of FR1/FR3/FR6/FR9 and elsewhere).** The premise is not confined to FR2:
> - **FR2 *Verify* line** — *"author is the overseer bot"* → read as **worker bot** (corrected above).
> - **FR3** — the parenthetical *"the PR author (overseer)"* names the author as the overseer.
>   Substantively FR3 is **unaffected**: it requires the approving identity to be disjoint from the
>   author, the worker, the overseer, the human-proxy, and the human — and the auditsync approver is
>   disjoint from all of them, including the now-correct author (worker), which FR3 already excludes.
>   Only the parenthetical *example label* is stale — read it as *"the PR author (worker)."* No
>   requirement changes.
> - **§0 VF-1** and **§1 Context** — both narrate the design as *"the overseer is the PR author /
>   the overseer cannot approve its own PR."* Their **conclusions survive** (see "Why the rest of the FR
>   set is unchanged" above); the author attribution in that narration is stale and should be read as
>   worker-authored, with the overseer's non-involvement — not an inability to self-approve — as why
>   `require_overseer_approval` is unsatisfied.
> - **FR1, FR4–FR19 (substance)** — do **not** reference the author identity and are **unaffected.**
>   FR1 (no bypass), FR6 (re-derive from the diff, never an author assertion), FR9 (allowlist), and the
>   rest carry no dependence on who authors. Per the narrow scope of this correction they are left
>   untouched.
>
> **Routing / classification.** Per AD-16 (ADR-035 Rev 3 §5) this FR2 correction and the
> worker-producer / fourth-identity-class changes **fold into the existing STRUCTURAL sign-off already
> routed to the human** in this document's "Human Review Required" block — they create **no new,
> separate human gate.** This is a factual correction into conformance with architect's binding AD-16,
> not a new PM decision. **Change classification: structural-in-substance, already human-gated.**
> **RISK: LOW–MEDIUM** (corrects a factually-impossible requirement; no gate or allowlist is widened;
> the auditsync-exception logic is unchanged). **CONFIDENCE: HIGH** — verified against
> `origin/main:.claude/agents/overseer.md:7` and `docs/AGENT-IDENTITY.md` line 86, and cross-checked
> against AD-3/AD-16/VF-1.

**FR3 — A separate, dedicated identity approves.** A distinct machine identity — the audit-approval
bot — submits the approving review. This identity MUST be neither the PR author (overseer) nor any
code-review, worker, or merge-authority role, nor the human's personal account.
*Verify:* the approving review's author equals the designated audit-approval identity and is disjoint
from the overseer, worker, human-proxy, and human identities.

### The decision: deterministic, shared, path-derived

**FR4 — Deterministic, non-LLM decision.** The bot's approve/withhold decision MUST be a
deterministic function of the diff and the entry content, with no runtime model or LLM judgment in
the decision path.
*Verify:* identical input diffs always yield the identical decision; the decision path invokes no
model API.

**FR5 — One shared, tested predicate is the single authority for "audit-only-and-well-formed."**
Whether a diff qualifies MUST be decided by a single shared, tested predicate used identically by
(a) the bot's approve decision and (b) the `require-overseer-approval` CI exception (FR10). Two
divergent implementations are non-compliant (the #1135 duplicate-gate class).
*Verify:* for the same diff, the bot's qualify verdict and the CI gate's qualify verdict are always
equal; a single test suite exercises both callers against the same fixtures.

**FR6 — Qualification is re-derived from the diff, never self-reported.** The predicate MUST determine
qualification from the actual changed paths and content, never from a PR label, title, body, branch
name, or any author assertion.
*Verify:* a PR that declares itself audit-only in its body/title but whose diff touches a
non-allowlisted path does **not** qualify.

**FR7 — Additions-only; audit history is not rewritten.** A qualifying diff MUST only *add* audit
records. Any modification or deletion of existing audit content disqualifies the diff. (This is the
primary blast-radius bound: an erroneous or malicious audit PR that could rewrite the record of what
overseer decided is categorically worse than one that appends a junk line.)
*Verify:* a diff that alters or removes an existing audit line does not qualify and is not approved.

**FR8 — Content well-formedness.** To qualify, added entries MUST be structurally valid for their
format (e.g., each added JSONL line parses as one JSON object; markdown-log appends match the
expected record shape). Malformed content disqualifies.
*Verify:* an audit PR containing a malformed added entry does not qualify.

**FR9 — The audit surface is an explicit allowlist, not "anything under `audit/`."** The set of paths
a diff may touch and still qualify MUST be an explicit, human-reviewable allowlist of audit-record
paths, reconciled with the existing `overseer.md` exempt-files list (VF-5). A new path introduced
under `audit/` that is not on the allowlist MUST NOT qualify until the allowlist is edited (a
protected-surface change — see FR11). The exact membership is a §5 decision.
*Verify:* a file added under `audit/` but absent from the allowlist does not qualify; extending the
allowlist requires a human-approved change.

### The CI-gate exception

**FR10 — The require-overseer-approval exception is narrow and positively identity-bound.** The
`require-overseer-approval` gate MAY treat its requirement as satisfied for an audit PR **only when
both** hold: (a) the diff qualifies under FR5, **and** (b) an `APPROVED` review exists from the
designated audit-approval identity. Absent an overseer approval, a PR that does **not** satisfy both
conditions MUST still FAIL the gate. The exception MUST NOT be a diff-shape-only waiver.
*Verify:* a non-audit PR with no overseer approval still fails `require-overseer-approval` even if the
audit-approval bot approved it; an audit PR passes only with the audit-approval identity's approval.

**FR11 — The gate change is a protected-surface change and stays human-gated.**
`require_overseer_approval.py` lives under `scripts/framework/**`, a protected surface. Introducing the
FR10 exception MUST go through the human-approval gate regardless of computed risk tier, and the
mechanism MUST NOT contain any path by which the gate exception could be introduced or widened without
that human approval.
*Verify:* a PR that edits `require_overseer_approval.py` triggers `require-human-approval` and cannot
merge without a human approver.

**FR12 — No new hole in the human or protected-surface gates.** The audit-approval identity is a bot;
its review MUST NOT count as a human approval and MUST NOT enable merge of any protected-surface or
non-audit change.
*Verify:* an audit-approval-bot `APPROVED` review on a PR touching a protected surface does **not**
satisfy `require-human-approval`.

### Disposition, merge, cadence, escalation

**FR13 — Non-qualifying content: withhold and escalate; never approve, force, close, or rewrite.** If a
PR presented as an audit PR does not qualify (non-allowlisted path, rewrite/deletion, malformed
content, or an unclassifiable diff), the bot MUST withhold approval and route to the repo's standard
human-escalation channel. It MUST NOT approve, MUST NOT force or bypass the merge, MUST NOT close the
PR, and MUST NOT rewrite the content into a qualifying form.
*Verify:* a non-qualifying audit PR receives no approval, a tracked human-addressable escalation is
produced, and the PR is left open for a human.

**FR14 — Routine merge is unattended and bypass-free.** On qualification, audit-approval, and green
required checks, the audit PR MUST merge without human action, using an ordinary PR merge (not a
bypass). Which identity performs the merge, and whether GitHub native auto-merge is used, is a §5
decision — but no option may reintroduce a bypass actor (FR1).
*Verify:* a well-formed audit PR merges end-to-end with no human action and no ruleset bypass.

**FR15 — Bounded freshness; the mechanism never indefinitely blocks a record from `main`.** Audit
entries MUST reach `main` within a bounded lag. Batching (e.g., one audit PR per cron cycle per role)
is permitted, but the batch policy and the maximum lag are bounded; the mechanism MUST NOT leave a
produced audit record unable to ever reach `main`. Exact cadence and lag bound are a §5 decision.
*Verify:* an entry produced in a cycle appears on `main` within the configured bound.

**FR16 — Stuck audit PRs escalate rather than silently accumulate.** If an audit PR cannot merge
(a required check errors, checks stay non-green, or a merge conflict arises) it MUST escalate to a
human after a bound, and the growing backlog of unrecorded audit history MUST be visible, not silent.
*Verify:* an audit PR whose required check errors produces a tracked human escalation; the audit
backlog is observable.

**FR17 — Supersede the 2026-06-23 bypass design and remove its setup instructions; reconcile the
auditsync identity's authority downward.** This mechanism supersedes the `hos-auditsync-hos`
"Ruleset bypass + direct push to main" design (`DECISIONS.md` 2026-06-23; `MACHINE-ACCOUNTS-SETUP.md`
Steps 5–6). The auditsync identity is reconciled to **review-submission authority only** — smaller
than the `Contents: read & write` + "Always" bypass it was originally specified to hold. Every
documented instruction that adds a bypass actor or pushes audit logs directly to `main` MUST be
removed or replaced so no onboarding path reintroduces the bypass, and `DECISIONS.md` MUST carry a
new dated superseding entry (append-only; never edit the 2026-06-23 entry in place).
*Verify:* no committed doc instructs adding a ruleset bypass actor or pushing audit logs directly to
`main`; the auditsync identity's required authority is review-submission scope, not push-to-main.

### Fail-closed integrity, anti-tamper, self-auditability

**FR18 — Fail closed and anti-tamper.** When the predicate cannot classify a diff (unreadable,
ambiguous, or unexpected content) it MUST treat the diff as **not** qualifying — so the normal gate
applies (overseer approval still required) and the PR escalates — never auto-qualify. No environment
variable, label, or configuration knob may widen what counts as audit-only, may disable the overseer
gate, or may turn a non-audit PR into a qualifying one. Any knob may only *narrow* qualification.
*Verify:* a diff the predicate cannot classify does not auto-qualify; no configuration setting causes
a non-audit PR to qualify or the overseer gate to be skipped.

**FR19 — The approver's own actions are auditable.** Each audit-approval decision (qualify-and-approve,
or withhold-and-escalate, with the reason) MUST itself be recorded durably, so the deterministic
approver's behavior is inspectable after the fact. This record MUST NOT itself require the full
mechanism to reach `main` in a way that creates an unbounded regress (it may ride along as metadata on
the same audit path).
*Verify:* an approval decision produces a durable, inspectable record of what qualified (or did not)
and why.

---

## 3. Reconciliation with the existing design and with #1095

| Existing artifact | Disposition under this design |
|---|---|
| `DECISIONS.md` 2026-06-23 — auditsync app holds a **Ruleset bypass**, pushes audit logs **directly to main** | **Superseded** (FR17). New dated `DECISIONS.md` entry required; 2026-06-23 entry left intact (append-only). |
| `MACHINE-ACCOUNTS-SETUP.md` Steps 5–6 — instruct adding `hos-auditsync-hos` to the bypass list at mode **Always**, `Contents: read & write`, direct push | **Removed / rewritten** (FR17). These are the exact instructions that reintroduce the bypass; they must not survive. Auditsync's documented authority drops to review-submission scope. |
| `overseer.md` exempt-files list (`oversight-log.jsonl`, `overnight-loop-log.md`, `audit/automation/**`) | **Reconciled** (VF-5, FR9). Becomes an input to, or is unified with, the single audit-surface allowlist rather than a competing definition. |
| Legacy `audit/log/**` (tracked on main) and `audit/automation/**` (REQUIREMENTS-034 relies on these) | Allowlist membership is a §5 decision (Q2). |

**Relationship to #1095 (open, critical) — a decision, not something I can settle.** I could not read
#1095's body this session (verification gap). Two coherent orderings exist and the human/architect must
pick one: **(A)** this design lands directly and *closes #1095* by making the checked-PR path the only
path (no interim step); or **(B)** #1095's interim migration to a sync-branch pattern is delivered
first as a stopgap so audit history stops being lost *now*, with this design as the durable
replacement. My recommendation is **(A)** — the interim direct-commit/sync-branch pattern is a second
mechanism to build and then retire, and VF-3 shows the aggregate logs are *already* not reaching main,
so there is no regression to protect against by shipping a stopgap first. But if delivery lead time for
the full mechanism is long and losing audit history in the interim is unacceptable, (B) is defensible.
Flagged as Q5.

---

## 4. Explicit non-goals

- **A general "deterministic bots may approve PRs" precedent.** This authority is defensible *only*
  for inert audit-record data with no execution consequence (§1). It MUST NOT be read as licensing a
  deterministic approver for any code, config, spec, or protected surface.
- **Widening what counts as "audit."** The allowlist is deliberately narrow (FR9); this work does not
  reclassify any code or config path as an inert record.
- **Changing what overseer records or when.** This is about the *path to main* for existing audit
  records, not their content, schema, or production cadence.
- **Log rotation / compaction.** Compacting or truncating an audit log is a *modification* of existing
  content (FR7 forbids it for the bot). If ever needed, it is a separate human-gated maintenance
  operation, out of scope here (Q6).
- **Relaxing the sandbox, the ruleset, or any required check.** The mechanism adds one narrow,
  identity-bound, human-gated exception to one check; it does not loosen the gate posture.

---

## 5. Product decisions escalated to the human

Genuine product/policy choices I cannot settle from the spec. Architect MUST NOT bind them until
ruled; a recommended default is given for each.

**Q1 — Cadence: per-entry PRs or batched?** *Recommendation:* one audit PR per cron cycle per role
(worker/overseer), batching all of that cycle's records, with a freshness bound of "reaches main by
the end of the next cycle." Per-entry PRs would flood the PR list and multiply check runs. *Human owns:*
per-entry vs per-cycle, and the maximum acceptable lag (FR15).

**Q2 — Exact audit-surface allowlist.** *Recommendation:* the allowlist is exactly
`audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`, `audit/log/**`, and `audit/automation/**`
— reconciled with the `overseer.md` exempt-files list. New audit paths require a human-approved
allowlist edit (a protected-surface change). *Human owns:* the exact membership, especially whether
`audit/automation/**` (which REQUIREMENTS-034's ledgers depend on) is in scope for this bot or handled
separately (FR9).

**Q3 — Merge authority for audit PRs.** *Recommendation:* arm GitHub native auto-merge on the audit PR
(so it merges when the audit-approval review lands and required checks are green), with the
audit-approval identity holding **no** merge-bypass authority. *Human owns:* whether the approver may
also be the merger, or whether merge must be a separate identity/step — and confirmation that no option
reintroduces a bypass (FR1/FR14).

**Q4 — Predicate-fail disposition.** *Recommendation:* withhold approval + file a tracked human
escalation, leave the PR open, never auto-close (FR13). *Human owns:* whether the bot should
additionally submit a `REQUEST_CHANGES` review (louder, but a bot requesting changes has its own
noise/semantics) versus simply not approving.

**Q5 — Ordering relative to #1095.** *Recommendation:* land this design directly and close #1095
without an interim stopgap (§3, option A). *Human owns:* whether an interim sync-branch migration is
still needed first (option B) because full-mechanism lead time is too long to keep losing audit
history. **Verification gap:** I could not read #1095 this session — the human should confirm what
#1095's interim fix actually is before ruling.

**Q6 — Log rotation / compaction.** *Recommendation:* out of scope; treat any future compaction as a
separate human-gated maintenance operation, since it modifies existing content (FR7). *Human owns:*
confirm compaction is not expected to flow through the audit-approval bot.

**Q7 — Coverage of the interactive Human clone.** *Recommendation:* the mechanism covers any
**bot-authored** audit PR (worker/overseer); audit records committed from the human's own interactive
clone are already human-authored and out of scope. *Human owns:* confirm the human clone is excluded,
or specify if its bot-proxy commits should route through the bot too.

---

## Human Review Required

This document authors new requirements (a MEDIUM-or-above spec change), so per my role I self-flag.

**RISK: MEDIUM** — The requirements add a new autonomous approval authority and a narrow exception to a
protected-surface CI gate (`require-overseer-approval`). The blast radius is bounded by design
(inert audit data, additions-only, path-derived, deterministic, human-gated gate change), but a
loosely-specified exception (FR10/FR7) could open a path to merge a non-audit change with no review,
and a mis-scoped allowlist (FR9/Q2) could let a non-inert path ride the audit exception. Those are
exactly the failure modes the FRs are written to close, which is why they are stated positively rather
than as waivers.
**CONFIDENCE: HIGH** on the requirement set, the VF-1 tier-ceiling correction, and the VF-2/VF-3
findings (all verified against `origin/main`). **LOWER** on the seven escalated decisions (§5), which
are correctly the human's, and on anything downstream of the three unread issues (#873/#1095/#1151)
and the unverified live-ruleset state — flagged as verification gaps in §0.
**BLAST RADIUS:** the `main`-branch protection posture and the audit trail's integrity on every
consumer deployment; the change to `require_overseer_approval.py` touches a protected surface.

**Change classification: STRUCTURAL.** This introduces a new machine identity with approval authority,
a new exception to an existing protected-surface gate (a change to existing behavior, not a
clarification), a new agent/mechanism obligation, and it **supersedes a standing `DECISIONS.md` entry
and its setup documentation** (VF-2, FR17). Per my role, the structural change and the seven escalated
policy decisions (§5) require explicit human sign-off before `architect` binds them. Architect may
begin design against FR1–FR19's settled shape, but the cadence, allowlist membership, merge-authority,
predicate-fail disposition, #1095 ordering, compaction, and interactive-clone questions are held for
the human.

> **FR2 author-identity correction — 2026-08-01 (ADR-035 Rev 3 / AD-16).** FR2's *"overseer authors"*
> premise was corrected to **worker authors** (see the dated note at FR2 in §2 and the top-of-document
> pointer). This is a factual correction into conformance with architect's binding AD-16 — the overseer
> authors no PRs per `origin/main:.claude/agents/overseer.md:7` — not a new PM decision; it **folds into
> the STRUCTURAL sign-off already required above** and creates **no new, separate human gate.** The
> whole-document sweep found the stale premise also in FR2's *Verify* line (corrected), FR3's
> parenthetical author example (substance unaffected — read *"(worker)"*), and the §0 VF-1 / §1
> narration (conclusions survive); **FR1 and FR4–FR19 are unaffected.** **Classification:
> structural-in-substance, already human-gated. RISK: LOW–MEDIUM. CONFIDENCE: HIGH.**
