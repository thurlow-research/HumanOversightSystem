# TECHNICAL DESIGN — ADR-036 audit recording as an extension point

**Status:** DRAFT 1 — awaiting `architect` review. ADR-036 (**ACCEPTED FOR DESIGN**, 2026-08-01, AD-1…AD-12,
Q3 bound) and REQUIREMENTS-036 (FR1–FR18) are the binding inputs. The three held product decisions are now
**human-bound** and this design is written against them: **Q1 = hourly sweep**, **Q2 = visible-proceed on
sink failure (buffering deferred to official release)**, **Q4 = producer identity is `hos-auditsync-hos`,
not the worker.**
**Date:** 2026-08-01
**Author:** technical-design
**Consumes:** `docs/v0.6.0/ADR-036-audit-extension-point.md`, `docs/v0.6.0/REQUIREMENTS-036-audit-extension-point.md`;
carries the deterministic-predicate design, the six panel hardening rules, and the sweeper/producer
mechanics from `docs/v0.6.0/TECHNICAL-DESIGN-035-audit-approval-bot.md` (superseded) and the adversarial
findings in `research/sessions/2026-08-01-audit-approval-bot-adhoc-panel.md` (branch `a03d441`).
**Consumer:** a `needs-ai` issue in the **v0.7.0** milestone. **We are not building this now.** This document
is the implementation contract a future `coder` works from cold; it describes *what the code must do* and
contains no application code.
**Scope note (035 supersession):** ADR-035 / TECHNICAL-DESIGN-035 are superseded, not patched. pm-agent
verified 035 is unmerged (branch `a03d441` only); nothing needs unwinding. **Discarded from 035:** the
approval-identity machinery — the `require_overseer_approval.py` gate exception (035 Component C), the
deterministic *approver* runtime (035 Component E), and the approval-bearing fourth identity class (035
Component M) — because the **overseer now approves**, satisfying `require_overseer_approval.py` natively
(AF-036-1). **Carried:** the deterministic predicate (re-homed as a required *status check*), the six
hardening rules, the producer/sweeper mechanics, and the chunking / self-check / heartbeat discipline.

---

## 0. Verification findings — every load-bearing premise re-checked against `origin/main`

The working tree is behind `origin/main`; all citations are `git show origin/main:<path>`. I re-read the
three CI gate scripts, the step-resolution read-shim (`step_range.sh` + `audit_log.py`),
`protected_surfaces.txt`, the trusted-base workflow, `bin/hos-cron`, `get_app_token.sh`, the config
generator (`scripts/framework/install.sh` + `hos_install.sh`), and the overseer's review flow in full.
**The ADR's AF-036-1 … AF-036-6 all re-verify as stated.** The findings below are numbered `TD-VF-036-n`
to avoid colliding with the ADR's, and they **change or extend the design** — one is HIGH and closes a gap
the ADR's own §0 did not surface.

**Inherited, unclosed gap.** `gh` is unauthenticated in this sandbox (verified: `git ls-remote` and any
`gh api` fail). I could not read the live `main` ruleset, the referenced issues, or confirm "zero bypass
actors." Those are taken as given, exactly as the ADR and REQUIREMENTS flagged. This is why the ruleset
half of AD-6/AD-7 (making the new check *required*) stays a human/admin action (Component J).

### TD-VF-036-1 (severity: HIGH) — "the overseer approves" is not free: the overseer *agent's* review flow fail-closes an audit PR to HUMAN_REQUIRED, so as specified the mechanism never runs unattended. The ADR verified the *status-check gates* but not the *overseer agent*.

AF-036-1 is correct about the three **server-side required status checks** — for an audit-only diff,
`require-tier-ceiling` computes LOW, `require-human-approval` is N/A (`audit/**` not protected), and
`require-overseer-approval` passes **once an `APPROVED` review by the overseer exists**. I re-confirmed all
three by reading the code. **But those checks only gate the merge; they do not cause the overseer to
approve.** The overseer's decision to *submit* the approving review is made by the overseer **agent**
(`.claude/agents/overseer.md`, run by `bin/hos-cron --role overseer`), and I read its review flow
(`overseer.md:190-245`) in full. It fail-closes an audit PR on **three** independent steps:

- **Step 3b (validator-artifact check, #555/#880):** it reads `signoffs/validators/step{N}/summary.json`
  from the PR branch. An audit PR has **no** validator artifact → *"validator artifact missing for step N"*
  → **HUMAN_REQUIRED / GATE_UNSATISFIED.** (The step-3b *exempt-files* list — `audit/oversight-log.jsonl`,
  `audit/overnight-loop-log.md`, `audit/automation/**` — only exempts audit **tail commits on a worker PR**
  from the staleness check; it does **not** admit a PR that has *no* validator artifact at all.)
- **Step 4a (register-completeness bounce):** an audit PR has no `.claudetmp/signoffs/step{N}-register.md`
  → the register-completeness gate bounces it back to the worker.
- **Charter (`overseer.md:7`):** *"only evaluates and acts on artifacts **the worker produced**."* An audit
  PR authored by `hos-auditsync-hos` is not worker-produced, so the overseer's queue-selection may not pick
  it up at all.

**This is the 036 analog of the exact class the 035 panel caught** (a fully-built consumer with the producer
or charter half missing — the "gate documented as executing with nothing executing it" failure). The ADR's
AD-5 asserts *"the overseer approves that PR"* as if that capability exists; **it does not.** As specified,
every audit PR routes to a human — defeating the unattended audit-to-`main` goal.

**Consequence (adds a required component).** `overseer.md` needs an explicit **audit-PR recognition and
approval path** (Component M): when the PR author is the auditsync producer **and** the new audit-shape
required status check (Component I) is green, the overseer approves **on that basis**, skipping the
worker-build artifact matrix (3b/4a/4b) while still honoring `OVERSEER_CEILING` and the protected-surface
rule. `overseer.md:53`'s "never approve a PR you authored or the worker authored under the same credentials"
is **not** violated — auditsync is a distinct identity from the overseer, so the open/approve split holds
(AD-9 constraint 2). This is an **architecture/charter question the ADR did not surface** → escalated to
`architect` (ESC-1): amend the charter to admit the audit-PR class, or declare it a bounded exception.

### TD-VF-036-2 (severity: MEDIUM, closes verification item #1) — hourly batching does NOT automatically fit under the patch-truncation rule. It fits only because audit-of-record is per-event write-once files, PLUS a producer chunking rule I make load-bearing.

The task asked me to confirm the hourly sweep stays under the files-API patch threshold that hardening rule 8
fails closed on, or specify the chunking that keeps it there — **and not to assume it fits.** I verified the
actual shape of the audit-of-record surface in `audit_log.py`:

- The **current** per-event surface (SPEC-888) is **write-once files**, one small JSON object each, sharded
  `audit/log/<YYYY>/<MM>/<ts>-<slug>-<hash>.json` (`audit_log.py:109,126,160-171`). Each file is `status:
  added`, and its `additions` equals its own line count — a handful of lines, orders of magnitude below the
  ~300-line / ~300 KB per-file patch threshold. **So rule 8 (parsed-added-lines == `additions`) cannot trip
  on these files by construction** — the per-file safety is structural, not lucky. Cron fires every 5 minutes
  (verified: `bin/hos-cron:34-35`, `1,6,11,… * * * *`), so an hourly sweep batches ≈12 cycles.
- The **only** monolithic-append target is the legacy `audit/oversight-log.jsonl`. An hourly batch appends
  ≈12 cycles of lines to that **one** file; if its single-file added-line diff ever approaches ~300 lines,
  rule 8 fails the whole PR closed. **The producer MUST therefore chunk appends so any single PR's diff to
  `oversight-log.jsonl` stays under the per-file threshold.**
- Independent of per-file size, an hourly batch is **many files** (events × 12 cycles). The producer MUST
  **also** chunk by per-PR file count and split a large backlog into **multiple sequential audit PRs**, each
  independently qualifying — carried from 035's producer chunking, extended with a file-count dimension.
- I confirmed a large batch does **not** break the native tier pass: `_simplified_tier` only escalates on
  `>10` `.py`/`.sh` files or any `.claude/agents/` path; audit files are `.json`/`.jsonl` and validators do
  not run in CI (`_try_validator_summary()` → `None`), so even a large audit PR computes **LOW ≤ HIGH**.

**Conclusion:** hourly batching is safe **only** because of (a) the write-once per-event file shape and (b)
a two-dimensional producer chunking rule (per-file added-lines for `oversight-log.jsonl`, and per-PR file
count). Both are made load-bearing in the producer contract (Component K, §7). This is *not* an assumption
that it fits — it fits by construction plus an enforced chunk rule.

### TD-VF-036-3 (severity: MEDIUM, closes verification item #2) — the hourly cadence creates a bounded audit-of-record data-loss window; it is distinct from the operational-state durability concern, and it is exactly what the deferred buffer-and-push (Q2) closes.

Under Q1 = hourly, a produced audit-of-record event lives **only** in the local spool (`audit/log/**` /
`oversight-log.jsonl`) for up to ~1 hour before a sweep transports it to `main`. A machine loss in that
window drops **up to ~1 hour of audit history.** This is acceptable for the prototype but MUST be an
explicit accepted-limitation entry (§10, L4).

**The connection the task asked me to make explicit:** the deferred *local-tmp-buffer-then-push* design
(Q2's official-release item) gets records off the machine **promptly** rather than waiting for the hourly
PR, shrinking the window toward zero; a real backend ingesting synchronously eliminates it. So L4 (this
window) and the deferred buffering are the same durability gap seen from two angles — which is why the
deferred item is *required for official release*, not an open question.

**Do not conflate this with AD-2's "sweep must never be the sole copy of operational state."** Those are two
different durability concerns: operational markers (`step-head`) must survive locally so *reads* keep working
(AD-2, §5); audit-of-record is uniquely local *until swept* so its *durability* is at risk (this finding).
The write-only-stub test proves the former; the deferred buffer fixes the latter.

### TD-VF-036-4 (severity: MEDIUM) — the auditsync identity has NO token-minting path. `get_app_token.sh` recognizes only `worker|overseer|human`.

Q4 binds the producer to `hos-auditsync-hos`, but I verified `bootstrap/get_app_token.sh:43-82` accepts only
`--app [worker|overseer|human]` and maps each to `HOS_{ROLE}_APP_ID` / `HOS_{ROLE}_PEM` /
`HOS_{ROLE}_BOT_LOGIN` with a #703 identity-mismatch guard. There is **no `auditsync` case.** The producer
(Component K, run from the cron slice) cannot authenticate as auditsync without one. (The old 2026-06-23
design stored `HOS_AUDIT_SYNC_*` as GitHub Actions secrets — a workflow path — not as a `get_app_token`
role.) **Consequence:** Component N adds the `auditsync` role to `get_app_token.sh` + `apps.env.template`
with the #703 guard extended to `HOS_AUDITSYNC_BOT_LOGIN`. `bootstrap/**` is protected → human-gated. This
is the 036 analog of 035's TD-VF-4, now for the *producer* rather than the discarded approver.

### TD-VF-036-5 (severity: LOW) — the #880 pre-PR audit-file prohibition is the worker's LOCAL gate, not a CI required check, so the 035 conflict does not arise for an auditsync producer — but must be confirmed, not assumed.

`scripts/automation/pre_pr_stale_check.py:check_audit_log_not_committed` (#880) forbids audit files on a
non-`main` branch. I confirmed (grep of `.github/`) it is **not** wired as a CI workflow — it is the worker's
local pre-PR gate (`worker.md:8.9`). The 036 producer is `hos-auditsync-hos` running a dedicated script
(Component K), **not** the worker's build flow, so it does not invoke that gate — the direct conflict 035's
TD-VF-2 found does not recur. **But** the producer must be built to **not** route through the worker pre-PR
gate; if any future wiring makes #880 a CI check, an all-audit-only diff must be exempted (via the shared
allowlist, Component H). Recorded as a boundary the producer honors (§7) and an issue to file (§9, ISSUE-3).

### TD-VF-036-6 (severity: LOW) — the narrowed allowlist moots the 035 `overnight-loop-log.md` validator-reconciliation problem, and the "gitignored" claim in the standing docs is stale.

035's TD-VF-6 flagged that `audit/overnight-loop-log.md`'s record shape is not derivable on `origin/main`.
This design carries 035's **narrowed** allowlist (AD-6c / 035 AD-17b/c): `oversight-log.jsonl` +
`audit/log/**/*.json` + `audit/log/**/*.jsonl` only — both with derivable validators — so the `.md`
reconciliation is out of scope for the default. Separately, `DECISIONS.md:490` and
`docs/MACHINE-ACCOUNTS-SETUP.md:72` both call the audit files *"gitignored"*; 035's TD-VF-3 verified
`.gitignore` has **no** `audit/` entry. The MACHINE-ACCOUNTS rewrite (Component R) corrects this in place;
the new DECISIONS entry (Component Q) notes it (append-only, never edited in place).

---

## 1. Terminology (binding — use these terms, no coined substitutes)

| Term | Meaning in this design |
|---|---|
| **Audit-of-record event** | A record HOS produces *for the record* and never reads back to make a control-flow decision. It is what the swappable backend receives. |
| **Operational control-flow state** | A record HOS reads back to make a decision (`step-head` / `step-head-final`). It stays in the always-present HOS-owned **local tier**; the backend is never queried for it. |
| **The contract** | `contract/AUDIT-RECORDING-CONTRACT.md` — the storage-agnostic normative definition of the record, the `record_event` operation, the failure semantics, and the conformance surface. Protected surface. |
| **Adapter (backend)** | A conforming implementation of the contract, selected by `AUDIT_BACKEND=` in `config.sh`. The swappable part. |
| **Dispatcher** | The single HOS-owned front door — `record_event(event) -> Outcome` — that forwards to the configured adapter. HOS-owned, not swappable. |
| **Default backend** | The prototype adapter: local append → hourly auditsync sweep → PR → overseer approves → merge to protected `main`. Explicitly disposable. |
| **The producer (sweeper)** | The `hos-auditsync-hos`-identity component that batches the local audit-of-record into an audit PR each hour and sweeps open audit PRs for stuck state. Opens PRs; never approves, never merges via bypass, never pushes to `main`. |
| **The predicate** | The deterministic, data-in/data-out shape+author check that runs as a **required status check** on the audit PR. |
| **Audit PR** | A PR authored by the auditsync producer whose diff the predicate returns `qualifies == True` for. |
| **Fail-closed** | Any ambiguity, unreadable input, unknown format, or unclassifiable diff → does not qualify → the audit PR is not auto-mergeable → escalate. Never auto-qualify. |

**The load-bearing tier test (AD-2 — quote verbatim wherever the boundary is documented):**

> *Does HOS read this record back to make a control-flow decision?* **Yes → operational control-flow state**
> (local tier, always present, never delegated to the backend, no query interface on the backend).
> **No → write-only audit-of-record** (the swappable backend receives it; a conforming backend implements
> no read/query capability).

**The scope-boundary sentence (state wherever the default's authority is characterised):**

> The default backend is prototype-grade and expected to be swapped. It is minimally-secure, not secure:
> the overseer self-attests its own records (L1), records share a trust domain with the audited code (L2),
> and it is append-only-by-convention, not WORM (L3). A production deployment brings its own backend.

---

## 2. Component map

The **rigor is asymmetric** (AD-1): Components A–D (the contract, the dispatcher, backend selection, and the
conformance harness whose acceptance test is the write-only stub) are the one part that cannot be cheaply
changed. Components E–S are the disposable default and its bookkeeping.

| # | Artifact | Kind | Binding | Protected? |
|---|---|---|---|---|
| **A** | `contract/AUDIT-RECORDING-CONTRACT.md` | NEW contract | AD-1, AD-3, AD-4 | **yes** (`contract/**`) |
| **B** | `scripts/oversight/lib/audit_record.py` — the `record_event` dispatcher + `Record` + `Outcome` | NEW module + CLI | AD-1, AD-3, AD-4 | no |
| **C** | `AUDIT_BACKEND=` selection: adapter interface/registry + `scripts/framework/install.sh` + `bootstrap/hos_install.sh` | NEW + EDIT | AD-1 (FR6) | yes (`bootstrap/**`, `scripts/framework/**`) |
| **D** | `scripts/oversight/verify_audit_backend.py` + `scripts/oversight/audit_backends/stub.py` (write-only counting stub) | NEW harness + stub | AD-1, AD-2 (acceptance test) | no |
| **E** | `scripts/oversight/audit_backends/default.py` — the default adapter (local append; declares **visible-proceed**) | NEW adapter | AD-4 (Q2), AD-5 | no |
| **F** | Operational-tier partition: the no-prune retention rule + operational-event-type set (a contract clause + a producer selection rule; no new reader) | DESIGN rule | AD-2 | (contract is protected) |
| **G** | `scripts/framework/audit_predicate.py` — deterministic shape+author predicate (carries 035 §3 + six rules) | NEW module + CLI | AD-6 | yes |
| **H** | `scripts/framework/audit_allowlist.txt` — the single audit-surface source (narrowed) | NEW config | AD-6 | yes |
| **I** | `.github/workflows/audit-shape-check.yml` — required-status-check workflow (trusted-base/data-only) | NEW workflow | AD-6, AF-036-4 | yes (`.github/workflows/**`) |
| **J** | `main` **ruleset** change to add Component I as a required check | ADMIN action | AD-6, AD-7 | (server-side; human) |
| **K** | `scripts/framework/audit_sync_producer.py` — the auditsync producer/sweeper (hourly; chunk; self-check; heartbeat; stuck-PR sweep) | NEW module + CLI | AD-5, AD-10, AD-12 | yes |
| **L** | `bin/hos-cron` — hourly auditsync producer slice | EDIT | AD-5, AD-10 | yes (`bin/**`) |
| **M** | `.claude/agents/overseer.md` — the audit-PR recognition/approval path (TD-VF-036-1) | EDIT | AD-5, TD-VF-036-1 | yes (`.claude/agents/**`) |
| **N** | `bootstrap/get_app_token.sh` + `bootstrap/apps.env.template` — the `auditsync` role (TD-VF-036-4) | EDIT | AD-9 | yes (`bootstrap/**`) |
| **O** | `scripts/framework/machine-accounts.env` — auditsync producer login/config | EDIT config | AD-9 | yes |
| **P** | `docs/AGENT-IDENTITY.md` — light non-approving transport-identity reconciliation | EDIT | AD-9 | yes (governance) |
| **Q** | `DECISIONS.md` — new dated entry superseding 2026-06-23 (append-only) | APPEND | AD-11 | no |
| **R** | `docs/MACHINE-ACCOUNTS-SETUP.md` — in-place rewrite of Steps 5–6 + remediation | EDIT | AD-11 | no |
| **S** | `docs/OVERSIGHT-RUNBOOK.md` — Phase 11 direct-commit reconciliation | EDIT | AD-11 | no |
| **T** | `tests/oversight/**`, `tests/framework/**` | NEW tests | §8 | no |

**Explicitly NOT built** (035 machinery discarded): no `require_overseer_approval.py` exception (035 C); no
deterministic *approver* runtime (035 E); no approval-bearing fourth identity class (035 M); no ruleset
bypass actor and no direct-push path anywhere (AD-5/AD-11); no query interface on any backend (AD-2); no
buffering mechanism in the prototype default (Q2 — deferred to official release, §10).

**Protected-surface count: seven** (`contract/**`, `scripts/framework/**`, `.github/workflows/**`, `bin/**`,
`bootstrap/**`, `.claude/agents/**`, `docs/AGENT-IDENTITY.md`) + the `main` ruleset. Per AD-7 the
**implementation** PR is human-approved at merge regardless of computed tier; the **runtime** audit PR
touches only `audit/**` (unprotected) and merges natively.

---

## 3. Components A + B — the contract and the dispatcher (where the rigor goes)

### 3.1 Component A — `contract/AUDIT-RECORDING-CONTRACT.md` (NEW; AD-1/AD-3/AD-4; protected)

A **sibling** of `contract/OVERSIGHT-CONTRACT.md`, referenced from it, not folded in (AD-1: different
consumer — a *backend author*, not an *agent team*). The document is **normative** and its MUST/SHALL text
must be **storage-agnostic (FR7)**: no `git`, `pull request`, `branch`, `JSONL`, directory, or path term may
appear in any normative clause. It defines four things and nothing about how they are stored.

**(a) The record (AD-3 / FR2) — defined as data, no serialization, no path.**

| Field | Req. | Meaning |
|---|---|---|
| **event type** | MUST | A stable identifier for the kind of event (e.g. `cycle-decision`, `overseer-ruling`, `step-head`, `audit-sync`). |
| **UTC timestamp** | MUST | An unambiguous instant. |
| **actor identity** | MUST | Which agent/identity the record is *about* (the deciding overseer, the worker, etc.) — attribution that survives regardless of who **transports** the record. |
| **correlation key** | MUST | Enough to tie the record to the work it describes (build step / cycle / the commit or PR the decision concerns). |
| **payload** | MAY | Event-keyed free-form data. |
| **prior-record linkage** | MAY | A field a backend MAY use to chain records; the contract *permits* but does not *require* chaining (a non-chaining backend still conforms). |

**Excluded from identity:** no mandatory field may be a storage location. "File path," "line number,"
"branch name," "PR number" may appear only inside the optional payload as data, never as the record's
identity. **Well-formedness rule:** a record missing any mandatory field is rejected by the contract's own
rule (testable with no filesystem/git/network present).

**Note on actor vs. transport (Q4-relevant).** The **actor identity** is a *content* field the record
carries; the **transport identity** (who opens the audit PR) is `hos-auditsync-hos`. These are deliberately
distinct: the auditee (worker/overseer) is named in the record as the actor, but the audit record is
transported by a separate, non-approving identity — the audit-domain principle the human bound in Q4. The
contract states this so no future backend collapses "who the record is about" into "who moved it."

**(b) The pass-on operation (AD-3 / FR3) — exactly one.** Producers call one operation, architecturally
`record_event(record) -> Outcome`. Its outcome MUST be observable to the caller. A producer MUST NOT write
to any store by any path that bypasses this operation.

**(c) Failure semantics (AD-4 / FR4) — three expressible outcomes; silent proceed FORBIDDEN.** The contract
MUST be able to express, and the caller MUST be able to observe, each of:

| `Outcome` | Meaning | Who declares it |
|---|---|---|
| `RECORDED` | The adapter accepted the record. | any |
| `BLOCKED` | The adapter refused; the caller MUST halt the cycle (a production audit system typically cannot proceed unrecorded). | a production backend MUST be able to declare this |
| `DEFERRED` | Buffered within a bound; will retry. | a backend MAY declare this |
| `PROCEEDED_UNRECORDED_VISIBLE` | The sink failed; a **visible, logged** marker was emitted; the caller proceeds. | the prototype default (Q2) |

The contract MUST **forbid** a silent proceed-unrecorded (an unobservable swallow). It MUST NOT hard-wire
"proceed unrecorded." **This closes a verified current defect:** `release_artifact_logic.py` today `warn`s
but never fails on audit I/O — a *de facto* silent proceed (REQUIREMENTS-036 VF-036-3); moving failure
semantics into the contract makes that a *chosen, visible* behavior.

**(d) Conformance surface (AD-1 / FR6).** A conforming adapter (i) implements the pass-on operation, (ii)
accepts the record shape, (iii) declares its failure semantic, and (iv) — because AD-2 rules there is **no
mandatory read capability** — needs no query interface. **The decisive acceptance test is the write-only
stub (Component D):** a stub that only *counts* records MUST be a conforming backend. If the stub cannot be
written against the contract, a storage assumption has leaked (FR7) and the contract text is wrong. The
contract document names the stub as the reference conformance artifact.

**Acceptance for Component A:** the record definition instantiates and validates with no filesystem/git/
network; a record missing a mandatory field is rejected; a review of the normative text finds no
git/PR/JSONL/path term; the write-only stub (D) is a conforming backend.

### 3.2 Component B — `scripts/oversight/lib/audit_record.py` (the dispatcher; NEW)

The single HOS-owned front door implementing the operation the contract defines. **High blast radius but not
a path-protected surface** (it sits under `scripts/oversight/lib/**`, which is not in
`protected_surfaces.txt`); it is covered by the mechanism's structural sign-off.

- **`Record`** — a typed record carrying the AD-3 fields; construction validates the mandatory fields
  (raises on a missing one — the contract's well-formedness rule, in code).
- **`Outcome`** — the enum of §3.1(c).
- **`record_event(record: Record) -> Outcome`** — resolves the configured adapter (Component C) once,
  forwards the record, and returns the adapter's `Outcome` **unmodified**. It never inspects storage, never
  names a medium, and never swallows an outcome. On an adapter that raises, it maps to the adapter's declared
  failure semantic (never a silent proceed).
- **Migration of existing producers.** Every current audit emission is re-pointed at `record_event`. The
  default adapter's local append **delegates to the existing `audit_log.write_event`** (so `audit/log/**`
  write-once files are produced exactly as today) — the dispatcher wraps, it does not replace, the verified
  writer. `release_artifact_logic.py`'s best-effort warn-only path is replaced by an explicit `Outcome`
  (default: `PROCEEDED_UNRECORDED_VISIBLE`), closing VF-036-3.
- **CLI:** `python3 -m scripts.oversight.lib.audit_record record --event <type> …` for shell producers;
  JSON in, `Outcome` out; exit 0 on `RECORDED`/`DEFERRED`/`PROCEEDED_UNRECORDED_VISIBLE`, non-zero on
  `BLOCKED` (so a shell caller can honor a production backend's block).

**Header comment must state:** this is the one operation every producer calls; no producer may write to any
store except through it; the adapter behind it is selected by `AUDIT_BACKEND=`; the record type and `Outcome`
enum are HOS-owned, the adapter is swappable; storage assumptions are forbidden here and in the contract.

---

## 4. Component C — backend selection (`AUDIT_BACKEND=`), mirroring `PACK=`

I verified the `PACK=` mechanism end-to-end so `AUDIT_BACKEND=` mirrors it exactly:

- `scripts/framework/install.sh` (the config generator) reads an existing value (`EXISTING_PACK=$(grep
  '^PACK=' …)`, line 144), prompts, and **writes it into `config.sh`** in the Step-5 heredoc
  (`PACK="${NEW_PACK}"`, line 294).
- `bootstrap/hos_install.sh` resolves the pack from `--pack` flags **or** falls back to the recorded
  `config.sh PACK=` on upgrade (the R1 read-path, line 1145).

**`AUDIT_BACKEND=` follows the same three touch-points:**
1. `scripts/framework/install.sh` — add `EXISTING_AUDIT_BACKEND=$(grep '^AUDIT_BACKEND=' …)`, a prompt
   (default `default`), and `AUDIT_BACKEND="${NEW_AUDIT_BACKEND:-default}"` in the Step-5 heredoc.
2. `bootstrap/hos_install.sh` — no re-application logic needed (unlike packs, there is no region to inject),
   but the upgrade path must **preserve** an existing `AUDIT_BACKEND=` (it already preserves consumer
   `config.sh`; confirm no code strips unknown keys).
3. **Runtime resolution (adapter registry).** The dispatcher (B) resolves `AUDIT_BACKEND` to an adapter by
   **name from a known directory**: `scripts/oversight/audit_backends/<name>.py`, each exposing a documented
   adapter interface (`record(record) -> Outcome`, plus a `declares_failure_semantic()` reporter). Default =
   `default`. This is the "discovered by name from a known directory" option AD-1 left to technical-design;
   I choose it over explicit registration because it mirrors the pack-by-name model the human already knows
   and keeps "swap = config edit, no HOS core change" true (FR6).

**Acceptance:** changing `AUDIT_BACKEND=default` → `AUDIT_BACKEND=stub` changes the active backend with a
config edit only; a name with no matching adapter fails **loudly** at resolution (fail-closed, never a silent
no-op that would drop records).

---

## 5. Components D + F — the conformance harness, the write-only stub, and the tier boundary

### 5.1 Component D — `verify_audit_backend.py` + the write-only stub (AD-1/AD-2)

- **`scripts/oversight/audit_backends/stub.py`** — a real, shipped adapter that only **counts** records
  (increments an in-memory/temp counter, returns `RECORDED`), storing nothing. It is the AD-2 acceptance
  test made a conformance artifact, and the AD-1 proof that no storage assumption leaked.
- **`scripts/oversight/verify_audit_backend.py <backend-name>`** — the conformance harness. It (i) feeds the
  adapter well-formed and malformed records and checks the contract's outcomes, (ii) checks the adapter
  declares a failure semantic, (iii) checks the adapter exposes **no** read/query interface (write-mostly),
  and (iv) runs **the decisive tier test**: with the backend swapped to `stub`, exercise every operational
  read (`step_range.sh` base/head resolution, `oversight-evaluator`, `audit_conditional_proceed.sh`) and
  assert they **still succeed** — because they read the local tier, never the backend (§5.2). A backend that
  breaks any operational read has had an operational record leak into the swappable tier and fails the
  harness.

### 5.2 Component F — the tier boundary, made concrete (AD-2, the load-bearing decision)

I verified the read paths myself (the ADR asked me to). `scripts/oversight/lib/step_range.sh:_shr_preferred_head`
calls `audit_read_stream <root>`, which is `audit_log.py:read_stream` globbing **`<root>/audit/log/**/*.json`**
(the local spool) and grepping for `step-head-final` (preferred) / `step-head`;
`oversight-evaluator` and `audit_conditional_proceed.sh` consume the same resolution. **These reads hit the
local filesystem; none queries `main` or any backend.** Decisively, `audit_log.py` writes operational markers
and audit-of-record events into the **same** `audit/log/**` directory — they are physically comingled — so
the tier split cannot be a directory split without moving files; it must be an **event-type partition** over
the shared spool.

**The design (event-type partition + no-prune retention):**

1. **Operational event-type set (HOS-owned).** The contract and the dispatcher declare a fixed set of
   **operational** event types — at minimum `step-head`, `step-head-final`, and any future control-flow
   marker HOS reads back. This set is HOS-owned and closed; adding to it is an HOS change, never a backend
   or config decision.
2. **Reads never leave the local tier.** HOS resolves operational markers **only** from the local
   `audit/log/**` spool, for **every** backend including the default. The read shim (`step_range.sh` /
   `audit_log.read_stream`) is **unchanged** — it already reads local, which is why the write-only stub
   passes. No backend is ever asked to serve an operational marker back.
3. **The sweeper transports only audit-of-record; it MUST NOT be the sole copy of operational state.** The
   producer (K) selects **non-operational** event types to carry to the backend. Operational markers **MAY**
   be mirrored to the backend as inert context (harmless for the default; ignored by a write-only backend),
   but the producer **MUST NOT prune** them from the local spool while any consumer may still read them.
   **Concrete retention rule:** the local spool is **append-only, never pruned** by the sweeper (consistent
   with additions-only and the write-once file model). Operational markers are therefore always present
   locally by construction. (Unbounded local growth is a documented prototype limitation, §10 L5; a real
   backend + local rotation handles it — rotation is out of scope here and must not prune below the
   in-flight-step horizon.)

**Acceptance test (bind it — the whole proof):** with `AUDIT_BACKEND=stub`, per-step base/head-SHA resolution
and every other operational read still succeed (Component D runs exactly this). If any breaks, an operational
record leaked into the swappable tier and must be moved back to the operational set.

**Rejected alternative:** mandating a read/query capability on every backend (REQUIREMENTS-036 FR5 option b).
It would force a WORM/SIEM backend to implement query-back for HOS's build-pipeline convenience — the exact
storage-assumption leak (FR7) this pivot exists to prevent. Bound out by AD-2.

---

## 6. Components G + H + I + J — the predicate as a required status check (AD-6)

Under this design the **overseer is the approver** (an LLM, manipulable per
`research/findings/adversarial-framing-attack-on-reviewer-agents.md`), so the mechanical shape/origin
guarantee moves into CI as a **required status check** — carrying the entire 035 predicate design
(TECHNICAL-DESIGN-035 §3 + §3.5) with the author check re-pointed from *approver* to *producer*.

### 6.1 Component G — `scripts/framework/audit_predicate.py` (NEW; protected)

A **pure, data-in/data-out** module (no subprocess, no network, no `gh`, no model, no filesystem write inside
the classify function — the caller fetches PR file records as DATA and passes them in). Signature and rules
carry from 035 §3.2/§3.5, plus the author check:

```
classify_audit_diff(files, allowlist, base_ref, author, producer_login,
                    protected_branch="main") -> AuditVerdict(qualifies: bool, reason: str)
```

`qualifies == True` only if **every** rule holds; on the first failing rule it returns `False` with a
machine-stable `reason` naming that rule and the offending path (deterministic order):

| # | Rule | Basis |
|---|---|---|
| 0 | `base_ref == protected_branch` (audit PRs target `main` only) | AD-6a / 035 rule 0 |
| 1 | `files` non-empty | 035 rule 1 |
| 2 | every `filename` matches the extension-restricted allowlist (H) | AD-6c / 035 rule 2 |
| 3 | every `status ∈ {added, modified}` (removed/renamed/copied disqualify) | AD-6 additions-only |
| 4 | every `deletions == 0` (no rewrite of an existing record) | AD-6 additions-only |
| 5 | every file with `additions > 0` has a non-`None` `patch` (fail-closed on binary/oversized) | 035 rule 5 |
| 6 | every added line is well-formed per its per-format validator (stateful unified-diff parse; the `+++`-content-line bug fixed) | AD-6e / 035 rule 6 + §3.3 fix |
| 7 | every changed file has `additions > 0` (reject zero-content mode/symlink/type change) | AD-6d / 035 rule 7 |
| 8 | parsed added-line count **equals** the files-API `additions` (patch-truncation fail-closed) | AD-6b / 035 rule 8 |
| **9** | **`author == producer_login`** (the audit PR is authored by the auditsync producer identity) | **AD-6d / FR12 — the must-close** |

- **Rule 9 is the forgery-hole close.** Under a diff-shape-only design, *anyone who can open a PR* could
  craft a well-formed audit append and forge the record of what the overseer decided — the HIGH gap that
  survived 035's entire panel undetected. Binding qualification to the auditsync producer identity closes it.
  **It is a required control, not an accepted limitation** (AD-8). `producer_login` is read from
  `machine-accounts.env` (`BOT_AUDITSYNC_USERNAME`); the compare is case-insensitive (reuse the existing
  login-compare idiom). An empty `producer_login` → rule 9 can never match → fail-closed (no configured
  producer means audit PRs escalate, never auto-qualify) — this doubles as the **kill-switch** (§7.4).
- **Anti-tamper (AD-6/FR14):** no configuration knob may *widen* qualification; knobs may only narrow (mirror
  `run_second_review.sh`'s `min(trusted_baseline, clamp(env,0,1))`). There is simply no widening input.
- **Per-format validators + the `+++` parser fix** are carried verbatim from TECHNICAL-DESIGN-035 §3.3 (the
  stateful `@@`-hunk parse, not `startswith('+++')`); a fixture embeds a `+++`-prefixed content line in a
  well-formed JSONL append and asserts it is validated, not skipped.
- **CLI:** `classify [--files -] [--allowlist …] [--base-ref …] [--author …]` → `{"qualifies":…,
  "reason":…}`; exit 0 reporter, 2 on usage/parse error.

### 6.2 Component H — `scripts/framework/audit_allowlist.txt` (NEW; protected)

The **single audit-surface source**, in the glob syntax `protected_surfaces.txt` already uses. **Narrowed
membership** (carried from 035 AD-17b/c, on the AD-6 fail-closed basis — a path with no derivable validator
can never qualify, so advertising it is misleading):

```
audit/oversight-log.jsonl
audit/log/**/*.json
audit/log/**/*.jsonl
```

This collapses the functional surface to the legacy append log + the write-once per-event JSON files — both
with derivable validators. `audit/overnight-loop-log.md` and `audit/automation/**` are **not** in the
default (no derivable validator; the latter re-adds only with a registered validator + a human membership
ruling, coupled to REQUIREMENTS-034 — §9, deferred). Header comment: every entry is an inert-record path;
adding a path is a protected-surface, human-gated change; the predicate reads from this one file.

### 6.3 Component I — `.github/workflows/audit-shape-check.yml` (NEW; protected)

A **new required-status-check workflow** following the AF-036-4 trusted-base/data-only model I verified in
`require-overseer-approval.yml` (`pull_request_target` [+ `pull_request_review` if it must re-fire on
review], `actions/checkout@v4` pinned to `ref: ${{ github.event.pull_request.base.sha }}`, PR content fetched
as **DATA** via `gh api …/pulls/{pr}/files` and parsed, **never checked out and executed** — safe precisely
because audit records are inert). It loads Component G from the **trusted base**, fetches the PR's file
records + `base.ref` + `author` as data, runs `classify_audit_diff`, and sets a commit status: green iff
`qualifies`. A design that shells out to the PR's own checkout reopens #972 and is forbidden.

### 6.4 Component J — the `main` ruleset change (ADMIN action; AD-6/AD-7)

Making Component I a **required** status check is a change to the `main` **ruleset** — a server-side
GitHub-admin action, **not** a runtime bypass and not a code file. It is the human/admin's action (Component
J), stated so it is not missed. A PR the overseer approves that **fails** the audit-shape check MUST NOT be
mergeable; a well-formed audit-only PR authored by a **non-producer** identity MUST fail the check even with
the overseer's approval (rule 9). `gh` is unauthenticated here so I cannot read or set the live ruleset;
recorded as the human's step.

---

## 7. Components K + L + M — the default backend's producer, cron slice, and overseer path

### 7.1 Component K — `scripts/framework/audit_sync_producer.py` (NEW; protected; the auditsync producer)

The named default-implementation producer (035's Component N, **re-homed from the worker to the auditsync
identity** per Q4). It is the component whose absence made 035's DRAFT-1 inert; a slice that ships the
approve/merge path without it is a half-mechanism and MUST NOT be accepted (AD-12). Each **hourly** run
(Q1) it performs two responsibilities:

**(1) Produce.** Contract — what the code must do:
1. **Select** the local audit-of-record produced since the last successful sync — the write-once
   `audit/log/**/*.json[l]` files and `oversight-log.jsonl` appends not yet on `main`, **excluding the
   operational event-type set** (§5.2; operational markers are not swept as record-of-decision, and are never
   pruned locally). "Last successful sync" is read from the heartbeat the previous run wrote (below).
2. **Chunk (TD-VF-036-2, load-bearing).** Split the selection so (a) any single PR's added-line diff to
   `oversight-log.jsonl` stays under the ~300-line/~300 KB per-file patch threshold (so rule 8 never trips on
   a legitimate backlog), and (b) any single PR's **file count** stays under a conservative bound (recommend
   a few hundred; well under the files-API 3000-file ceiling and any review tooling limit). A backlog larger
   than one chunk becomes **multiple sequential audit PRs**, each independently qualifying.
3. **Create** a deterministic, unique audit branch (e.g. `audit-sync/{ISO-8601-UTC}`) — never `main`.
4. **Commit** only allowlisted (H), additions-only (first-creation or append) paths, so the diff is exactly
   what the predicate (G) qualifies. **Producer-side self-check (fail-closed):** before opening the PR, run
   the same allowlist + additions-only + rule-9-author atom the required check uses (shared source, no second
   copy) against the staged diff; if it would **not** qualify, do **not** open the PR — escalate.
5. **Push** under the auditsync identity to the audit branch (ordinary push to a non-`main` branch, **no
   bypass**). The producer authenticates via `get_app_token.sh --app auditsync` (Component N).
6. **Open the PR with `base = main`** (satisfying rule 0 by construction), authored by
   `hos-auditsync-hos[bot]` (satisfying rule 9), labeled/identifiable as an audit PR for the overseer path
   (M).
7. **Hand off** to the approve/merge path: the overseer approves (M); the merge is an ordinary PR merge that
   satisfies every branch-protection rule and required check, **no bypass actor, no direct push** (AD-5,
   honoring #873).
8. **Write durable records (AD-10/FR17)** through the pass-on operation (Component B), as ordinary
   allowlisted records the **next** run carries to `main`: (i) the producer's own decision record (what it
   selected/committed, head SHA, PR number), and (ii) a **"last successful audit sync" heartbeat** marker.
   Neither depends on runner-local disk.

**(2) Sweep (AD-10, mandatory periodic).** Enumerate **open** audit PRs and escalate any that are stuck — a
required check erroring, checks non-green past a bound, or a merge conflict — to the standard
human-escalation channel, so the backlog is observable, not silent. An event-only trigger cannot satisfy
this (an audit PR that opens green and later wedges fires no event); the hourly cron slice is the mandatory
periodic sweep.

### 7.2 The default backend's failure semantic (Q2 = visible-proceed; buffering deferred)

The default adapter (Component E) **declares `PROCEEDED_UNRECORDED_VISIBLE`** on sink failure: if the
immediate local append fails (disk full, permission), it emits a **loud, logged** visible marker and the
caller proceeds — **never silent** (FR4). It **never** declares `BLOCKED` (the prototype must not halt the
autonomous loop on an audit hiccup) and **does not** implement `DEFERRED` buffering. **The local-tmp-buffer-
then-push mechanism is REQUIRED FOR OFFICIAL RELEASE, not an open question** (§10 L4 + §9 ISSUE-1): it is what
shrinks the TD-VF-036-3 data-loss window. Sweep-side failures (backend/PR stuck) are covered separately by
the mandatory sweep + heartbeat + stuck-PR escalation (§7.1(2)); both failure surfaces are "never silent."

### 7.3 Component L — `bin/hos-cron` hourly auditsync slice (EDIT; protected)

Add a producer slice to `bin/hos-cron` that mints the auditsync token (`get_app_token.sh --app auditsync`,
temp-file pattern per CLAUDE.md — never a hand-built JWT) and invokes Component K **hourly** (Q1). The
existing worker/overseer cron cadence is every 5 minutes; the audit producer runs on an hourly schedule (its
own crontab line or an hourly guard within the slice). The producer holds **no** ruleset bypass and **no**
content-write beyond opening PRs (AD-9 constraint 3).

### 7.4 Component M — `.claude/agents/overseer.md` audit-PR recognition path (EDIT; protected; TD-VF-036-1)

**This closes the HIGH gap.** Add an explicit audit-PR branch to the overseer's review flow, evaluated
**before** the worker-build artifact matrix (steps 3b/4a/4b): when the PR author is `BOT_AUDITSYNC_USERNAME`
**and** the audit-shape required status check (I) is green, the overseer:
- **skips** the validator-artifact check (3b), register-completeness bounce (4a), and out-of-scope-commit
  check (4b) — an audit PR legitimately has none of the worker-build artifacts those steps require;
- **still honors** `OVERSEER_CEILING` (LOW ≤ HIGH → approvable; a `SAFE` ceiling correctly fails it closed
  to a human, AF-036-1 caveat) and the protected-surface rule (`audit/**` is not protected → approvable);
- **approves** the PR (the overseer *is* the approver — an LLM attesting "these are genuinely the records").

The open/approve split holds: auditsync **opens**, overseer **approves** — distinct identities, so
`overseer.md:53` ("never approve a PR you authored or the worker authored under the same credentials") is not
engaged (AD-9 constraint 2). The charter line `overseer.md:7` ("only evaluates artifacts the worker
produced") is reconciled to admit the audit-PR class — **ESC-1 to architect**: amend the charter, or declare
the audit-PR path a bounded, enumerated exception. A `tests/framework` assertion checks the audit-PR branch
exists and precedes the worker-build matrix.

---

## 8. Components N + O + P — identity reconciliation (the light, non-approving transport)

Per AD-9 / Q4, the producer identity is **narrow, single-purpose, non-approving** — it opens audit PRs and
appends inert data, nothing else. This is the light reconciliation, explicitly **NOT** the discarded 035
approval-bearing fourth class.

- **Component N — `bootstrap/get_app_token.sh` + `apps.env.template` (EDIT; protected; TD-VF-036-4).** Add an
  `auditsync` role: extend usage to `--app [worker|overseer|human|auditsync]`, add a `case` arm mapping to
  `HOS_AUDITSYNC_APP_ID` / `HOS_AUDITSYNC_PEM` / `HOS_AUDITSYNC_BOT_LOGIN`, with the #703 identity guard
  extended so the authenticated login must equal `HOS_AUDITSYNC_BOT_LOGIN` (`hos-auditsync-hos[bot]`). Add the
  three `HOS_AUDITSYNC_*` variables to `apps.env.template` with the **narrowed** scope documented: **Pull
  requests: Read & write, Contents: Read, Metadata: Read, everything else No access, NO ruleset bypass, NO
  direct push.**
- **Component O — `scripts/framework/machine-accounts.env` (EDIT; protected).** Add
  `BOT_AUDITSYNC_USERNAME="hos-auditsync-hos[bot]"` (read by the predicate for rule 9 and by the overseer
  path M). Append the auditsync login to `BOT_ACCOUNTS` (defense-in-depth so the identity is a recognized
  bot). Comment: producer/transport scope only, **no push/bypass**. Unsetting `BOT_AUDITSYNC_USERNAME` is the
  named **kill-switch** (rule 9 can never match → every audit PR escalates to a human; no records lost).
- **Component P — `docs/AGENT-IDENTITY.md` (EDIT; protected governance).** Reconcile the identity model to
  declare `hos-auditsync-hos` a **non-approving producer/transport** identity: it **opens audit PRs, appends
  inert data, and does nothing else** — it is **not** the overseer (which approves) and **not** the worker
  (whose PRs carry code); it holds **no approval authority, no ruleset bypass, no content-write beyond
  opening PRs.** This is a *lighter* amendment than the discarded 035 fourth *approval-bearing* class (035
  Component M): no approval ceiling, no risk-evaluation role. Update any "three classes" count/rationale to
  reflect a transport role, and record that changes granting or widening this identity's authority are
  protected-surface, human-gated regardless of tier (mirrors AD-7).

---

## 9. Components Q + R + S — supersession bookkeeping (AD-11)

I verified the exact live content of each target on `origin/main`:

- **Component Q — `DECISIONS.md` (APPEND; never edit in place).** The 2026-06-23 entry
  (`DECISIONS.md:488`, *"Audit log sync bot: dedicated hos-auditsync-hos GitHub App"*) records: audit files
  *"gitignored from feature PRs and synced to main via a GitHub Actions workflow"*, the app *"holds the
  Ruleset bypass for direct push to main"*, `Contents: read & write`, cron pushes to an unprotected
  `audit-log` branch, workflow commits to `main`. Append a **new dated entry** at EOF (current tail:
  `## 2026-07-30 — Advisory PACK-conflict detection`, line 568):
  ```
  ## 2026-08-01 — Audit recording becomes an extension point; auditsync re-scoped to non-approving producer (ADR-036)
  ```
  It MUST (i) explicitly supersede the 2026-06-23 entry, naming it; (ii) record that that sync was
  specified-but-never-built (035 verified the `audit-log`-branch push existed but no consumer merged it), so
  there is a documented path to delete, not a live merged mechanism; (iii) record the auditsync identity is
  re-scoped **downward** to a non-approving producer/transport (PR: Read & write, Contents: **Read**, no
  bypass); (iv) record that audit-of-record now reaches `main` via a checked PR the **overseer** approves,
  zero bypass actor (honoring #873); (v) note the 2026-06-23 "gitignored" claim is stale (TD-VF-036-6). Not
  a protected surface, but part of the structural sign-off.
- **Component R — `docs/MACHINE-ACCOUNTS-SETUP.md` (EDIT in place; living doc).** Steps 5–6 carry **live**
  bypass instructions: Step 5 (line 70-80) creates the app with `Contents: Read & write` and *"pushes
  directly to main, bypassing the PR requirement"*; Step 6 (line 97-109) adds `hos-auditsync-hos` to the
  Ruleset **Bypass list** with mode **Always**. Rewrite so the identity is created with the **non-approving
  producer scope** (Pull requests: Read & write, Contents: **Read**, Metadata: Read, **no bypass step, no
  direct-push language**), and correct the stale "gitignored" claim. Add an explicit **consumer-remediation
  step**: *"if you previously added `hos-auditsync-hos` to the `main` ruleset bypass list, remove it; and
  downgrade the app's Contents permission from Read & write to Read."* A forward-only rewrite that leaves
  deployed bypass actors in place does not honor #873.
- **Component S — `docs/OVERSIGHT-RUNBOOK.md` (EDIT in place).** Phase 11 still documents the superseded
  direct-commit path: line 62-63 *"audit decisions land in `audit/oversight-log.jsonl` (synced to the
  `audit-log` branch each cycle)"* and line 640-641 a literal `git add audit/` + `git commit -m "Step N:
  audit log entry — merge PR $PR"`. Reconcile these passages to describe audit-of-record reaching `main` via
  the **checked audit PR** (auditsync producer → overseer approval → ordinary merge); remove the
  `audit-log`-branch "synced each cycle" language and the direct `git commit` of `audit/`.

**Acceptance (AD-11):** a `git grep` across committed docs finds **no** instruction to add a ruleset bypass
actor or to push/commit audit logs directly to `main`; the new dated `DECISIONS.md` entry supersedes the
2026-06-23 entry without editing it; the runtime mechanism contains no `require_overseer_approval.py`
exception and no approval-bearing fourth identity.

---

## 10. Accepted-limitations register (AD-8 / FR16)

Each accepted item carries a **"how a real backend removes this"** line. The cheap-to-close items (rule 9
author-identity, the six hardening rules) are **required controls, NOT accepted** (AD-8 / §6).

| # | Accepted limitation | Why inherent to the prototype default | How a real backend removes it |
|---|---|---|---|
| **L1** | The overseer self-attests its own records; an auditor can produce a false-but-well-formed record. | The producer of the decision is also the attester; the deterministic check bounds *shape and origin*, not *truthfulness of content*. | External, independently-controlled ingestion (SIEM/CloudTrail-style) the recorder cannot alter. |
| **L2** | Records share a trust domain with the audited code (same repo/`main`, same access). | The default stores audit-of-record in the very repo it audits. | A separate-domain WORM store or audit service outside the audited system. |
| **L3** | Append-only-by-convention, not WORM (git history is rewritable by a privileged actor). | Git offers no write-once medium; protection is procedural (the predicate + branch protection), not physical. | True write-once / immutable-ledger storage. |
| **L4** | **Hourly data-loss window (Q1):** audit-of-record lives only in the local spool for up to ~1 hour; a machine loss drops up to ~1 hour of history (TD-VF-036-3). | The hourly sweep is the only transport off the machine; nothing durably ships a record sooner. | **The deferred local-tmp-buffer-then-push design (Q2, required for official release, ISSUE-1)** ships records off-machine promptly, shrinking the window; a real backend ingesting synchronously eliminates it. |
| **L5** | Unbounded local-spool growth (the sweeper never prunes, to guarantee operational markers survive for reads). | The no-prune retention rule (§5.2) is how the write-only-stub invariant is kept cheaply in a prototype. | A real backend + a local rotation that never prunes below the in-flight-step horizon. |

**Q2-BOUND clarification:** the default's *failure semantic* is **visible-proceed** on sink failure (never
silent, never a hard cycle-halt). This is a **declared, chosen** behavior (§7.2), not an accepted limitation
— the accepted limitation is only the *hourly window* (L4), which the deferred buffering closes.

---

## 11. Build order and PR split (for the v0.7.0 issue — nobody builds it yet)

Dependencies are real; this order is not a preference.

| # | Slice | Component(s) | Depends on |
|---|---|---|---|
| S1 | Contract doc | A | — |
| S2 | Dispatcher + `Record` + `Outcome` + tests | B | S1 |
| S3 | `AUDIT_BACKEND=` selection (config generator + install + registry) | C | S2 |
| S4 | Write-only stub + conformance harness + **tier-boundary acceptance test** | D, F | S2, S3 |
| S5 | Default adapter (local append; visible-proceed) + tests | E | S2, S4 |
| S6 | Predicate (+ six rules + rule 9 author) + tests | G | — (consumes H as data) |
| S7 | Allowlist file | H | — |
| S8 | Required-status-check workflow | I | S6, S7 |
| S9 | `main` ruleset change (admin) | J | S8 |
| S10 | auditsync producer (chunk + self-check + heartbeat + sweep) + tests | K | S5, S6, S7, S12 |
| S11 | `bin/hos-cron` hourly auditsync slice | L | S10, S12 |
| S12 | auditsync auth role + machine-accounts + AGENT-IDENTITY | N, O, P | — |
| S13 | overseer.md audit-PR recognition path | M | S6, S7, S8 |
| S14 | Supersession bookkeeping (DECISIONS, MACHINE-ACCOUNTS, RUNBOOK) | Q, R, S | everything above (describe what shipped) |
| S15 | Issues filed (§9 ISSUE-1..3) | — | any time |

**The producer (S10) is the pivot** (AD-12): the minimal functional end-to-end set is **S1–S9 + S10 (producer)
+ S13 (overseer path)**. A build that ships the predicate/workflow/overseer path without the producer, or the
producer without the overseer path (TD-VF-036-1), is inert and MUST NOT be accepted.

**PR-size split (`docs/PR-SIZE-POLICY.md`: >15 files or >10 commits → split; 25 hard ceiling).** This work
touches well over 25 files across seven protected surfaces, so the whole thing is human-gated (AD-7) and
must split. Recommended seams, each independently green:
- **P1 — the contract core:** S1, S2, S3, S4, S5 (contract, dispatcher, selection, write-only stub +
  tier-boundary test, default adapter). *The asymmetric-rigor half; the one that must not drift.*
- **P2 — the predicate + gate:** S6, S7, S8 (+ S9 is the admin ruleset action, tracked with P2 but performed
  server-side).
- **P3 — the producer + cron + identity:** S10, S11, S12 (the auditsync producer, its cron slice, and the
  identity reconciliation). *The producer half 035 lacked entirely.*
- **P4 — the overseer path + bookkeeping:** S13, S14, S15 (the overseer audit-PR recognition, the
  supersession docs, issues).

P3 depends on P1+P2; P4's overseer path depends on P2; P4's DECISIONS entry describes P1–P3.

---

## 12. Test plan

Conventions: pure logic → `tests/oversight/` or `tests/framework/` importing directly; shell/CLI → drive the
real script as a subprocess in `tmp_path`, exercising only paths that short-circuit before any live
model/network/`gh`; framework/registration invariants → `tests/framework/`. **Nothing requires a live model,
network, or authenticated `gh`.**

**T1 — contract + dispatcher (`tests/oversight/test_audit_record.py`, A/B).** A record missing any mandatory
field is rejected. Every `Outcome` is observable to the caller (no swallow). `record_event` forwards to the
configured adapter and returns its `Outcome` unmodified. A production adapter declaring `BLOCKED` makes the
shell CLI exit non-zero. The default adapter's local append produces the same `audit/log/**` write-once files
as `audit_log.write_event` today.

**T2 — the write-only-stub / tier-boundary acceptance test (`tests/oversight/test_audit_backend_stub.py`,
D/F — the AD-2 binding deliverable).** With `AUDIT_BACKEND=stub`: the stub is a conforming backend
(`verify_audit_backend stub` passes); the stub exposes **no** read interface; and **`step_range.sh`
base/head-SHA resolution, `oversight-evaluator`, and `audit_conditional_proceed.sh` all still resolve** from
the local spool (the decisive proof the operational tier never left local). A synthetic operational marker
placed only in the local spool resolves; the stub, asked, cannot serve it (and is never asked).

**T3 — FR7 no-leak (`tests/framework/test_audit_contract_no_storage_leak.py`, A).** A text sweep of the
contract's normative (MUST/SHALL) clauses finds no `git`/`pull request`/`branch`/`JSONL`/directory/path term.
The write-only stub instantiates and records with no filesystem/git/network present.

**T4 — predicate (`tests/framework/test_audit_predicate.py`, G).** Carry 035's suite: empty diff, off-
allowlist path, added/modified/deletion/removed/renamed statuses, patch-unavailable, malformed JSONL, no-
registered-validator, zero-content (rule 7), patch-truncation (rule 8), wrong target branch (rule 0), the
`+++`-content-line regression (rule 6). **Plus rule 9:** a well-formed audit-only diff authored by a
**non-producer** login → `qualifies == False`, reason names the author mismatch; authored by the producer →
qualifies. Empty `producer_login` → fail-closed (kill-switch). A malformed or non-producer diff is **withheld,
never qualified** — the explicit negative.

**T5 — allowlist single-source (`tests/framework/test_audit_allowlist.py`, H).** The file parses under the
shared glob helper; membership is exactly the three narrowed entries; the predicate reads from it.

**T6 — producer (`tests/framework/test_audit_sync_producer.py`, K — hermetic, mocked `gh`).** Chunking:
a backlog exceeding the per-file `oversight-log.jsonl` threshold splits so no single PR's diff to that file
exceeds it; a backlog exceeding the per-PR file-count bound splits into multiple sequential PRs (TD-VF-036-2).
Self-check: a staged diff that would not qualify → the producer does **not** open a PR, it escalates. It
commits only allowlisted, additions-only paths; targets `base = main`; authors as auditsync. It writes a
heartbeat and its own decision record through `record_event`. The stuck-PR sweep escalates a non-green open
audit PR. It contains **no** push-to-`main`, no bypass, no approve call (grep guard).

**T7 — overseer audit-PR path (`tests/framework/test_overseer_audit_pr_path.py`, M).** The audit-PR branch
exists in `overseer.md`, precedes the worker-build matrix (3b/4a/4b), keys on author == `BOT_AUDITSYNC_USERNAME`
+ the green audit-shape check, and still honors `OVERSEER_CEILING` and the protected-surface rule. A grep guard
asserts the branch does not remove or weaken the worker-PR matrix for non-audit PRs.

**T8 — identity (`tests/framework/test_auditsync_identity.py`, N/O/P).** `get_app_token.sh` accepts `--app
auditsync` and maps the `HOS_AUDITSYNC_*` variables with the #703 guard on `HOS_AUDITSYNC_BOT_LOGIN`;
`machine-accounts.env` carries `BOT_AUDITSYNC_USERNAME` and includes it in `BOT_ACCOUNTS`;
`docs/AGENT-IDENTITY.md` declares the non-approving producer/transport role (and does **not** grant it
approval authority or bypass).

**T9 — supersession (`tests/framework/test_audit_supersession_no_bypass.py`, Q/R/S).** A `git grep` across
`DECISIONS.md`, `docs/MACHINE-ACCOUNTS-SETUP.md`, `docs/OVERSIGHT-RUNBOOK.md` finds no instruction to add a
ruleset bypass actor or push/commit audit logs directly to `main`; MACHINE-ACCOUNTS carries the remediation
step and the non-approving scope; the new dated `DECISIONS.md` entry is at EOF and the 2026-06-23 entry is
byte-unchanged.

**T10 — `AUDIT_BACKEND=` selection (`tests/framework/test_audit_backend_selection.py`, C).** The config
generator writes `AUDIT_BACKEND=` (default `default`); an upgrade preserves an existing value; an unknown
backend name fails loudly at resolution (never a silent record-drop).

**T11 — manual / operator (cannot be hermetic).** One real hourly producer run against a real backlog: confirm
one (or, for a large backlog, several sequential) audit PR(s), the overseer approves via the audit-PR path,
the merge is an ordinary PR merge with **zero** bypass actors. One run with the backend swapped to `stub`:
confirm operational reads still work. Confirm the auditsync app's live permissions are exactly PR Read&write +
Contents Read + Metadata, **no bypass** (unverifiable here — `gh` unauthenticated; report, do not work around,
any divergence). Confirm the `main` ruleset requires the audit-shape check (Component J).

---

## 13. Escalations, issues to file, and startup-gap analysis

### 13.1 Escalations (technical-design → other roles)

| id | To | Question | Blocks |
|---|---|---|---|
| **ESC-1** | **architect** | **TD-VF-036-1 (HIGH):** the overseer *agent's* review flow fail-closes an audit PR (no validator artifact / register), and `overseer.md:7`'s "only evaluates artifacts the worker produced" conflicts with "overseer approves the auditsync-produced audit PR." Confirm Component M's audit-PR recognition path (charter amendment vs. a bounded declared exception). This is the 036 analog of the charter contradiction the 035 panel caught; the ADR's §0 verified the *status-check gates* but not the *agent*. | Component M |
| **ESC-2** | **architect** | Confirm the AD-2 tier-boundary factoring is the **event-type partition + no-prune retention** (§5.2) rather than a distinct local-only directory. Both satisfy AD-2; the event-type partition is minimal because the read shim is unchanged. | Component F |
| **ESC-3** | **architect** | Confirm the adapter-discovery mechanism is **by-name from `scripts/oversight/audit_backends/`** (mirroring `PACK=`) vs. explicit registration (AD-1 left this to technical-design). | Component C |
| **ESC-4** | **pm-agent** | Confirm the producer's stuck-PR escalation and heartbeat reuse the existing `oversight-orchestrator`/`cycle_log` channels vs. a new surface (observability question). | Component K wiring |

### 13.2 Issues to file — separately, not folded in (`gh` unauthenticated here; file when reachable)

| id | Title | Basis |
|---|---|---|
| **ISSUE-1** | `[AI: technical-design] official-release: audit backend local-tmp-buffer-then-push to close the hourly data-loss window (Q2 deferred; ADR-036 L4)` | Q2 bound: buffering deferred to official release; L4 is the exposure it closes. **Required for release, not optional.** |
| **ISSUE-2** | `[AI: technical-design] deferred: REQUIREMENTS-034 audit/automation/** ledgers re-add to the audit allowlist requires a registered validator + human membership ruling` | AD-8 addendum / §6.2 narrowed allowlist; couples to REQUIREMENTS-034. |
| **ISSUE-3** | `[AI: technical-design] guard: if pre_pr_stale_check #880 ever becomes a CI required check, exempt an all-audit-only diff via the shared allowlist (TD-VF-036-5)` | The #880 conflict does not recur for the auditsync producer today; file so a future wiring change cannot silently block the mechanism. |

**Carried deferrals (035 lineage, still owed a real issue when the tracker is reachable):** an independent
external cron-loop liveness monitor (consumes the Component K heartbeat; linked to #1151), and a GitHub-App
key-rotation policy across all identities incl. auditsync (linked to the #152 lineage). **No deferral is
silent.**

### 13.3 Startup-gap analysis and affected sign-offs

*Should this have been settled before any code was written against it?* This is a **new mechanism**, not a
correction to already-built work. **ADR-035 / TECHNICAL-DESIGN-035 are unmerged and no design or code
sign-off was ever issued against them** (pm-agent verified: branch `a03d441` only), so **nothing is
orphaned** by the supersession — the clean-pivot case. The one late-correction-shaped item is TD-VF-036-1
(the overseer path): it is a gap in *this* design's own contract, caught here in design before any build, so
**all prior sign-offs stand** and no already-approved code is left unaudited against a changed contract. Two
`startup-artifact-gap`-class defects in existing shipped code that this work exposes get their own issues
rather than being folded in: the stale "gitignored" claims (TD-VF-036-6) and the auditsync-has-no-token-path
gap (TD-VF-036-4) — both closed within this design's components (R and N), but recorded as pre-existing.

---

## Human Review Required

This design authors a new cross-consumer contract and a STRUCTURAL change to the audit-to-`main` mechanism, so
per my role I self-flag.

**RISK: MEDIUM.** The pivot *reduces* runtime risk relative to 035 — no protected-surface gate exception, the
three required status checks pass natively (AF-036-1, code-verified), and the FR12 forgery hole 035's panel
missed is closed as a **required control** (rule 9). Residual risk lives in the **contract**, not the default:
a leaked storage assumption (FR7) or an under-specified failure/read boundary would lock every future backend
into git's shape — which is why the write-only stub is a real conformance artifact whose passing is the
acceptance test (Components A/D/F). The new residual I surfaced is **TD-VF-036-1**: "the overseer approves"
was asserted but not built — the overseer agent fail-closes an audit PR — so Component M is a required, not
optional, part of the mechanism; shipping without it makes the whole thing route to a human every hour. The
default ships with documented, accepted holes by explicit human direction (L1–L5), defensible only because
the cheap-to-close ones (author-identity, the six hardening rules) are *not* among the accepted set.

**CONFIDENCE: HIGH** on the architecture and on the code I read in full this session against `origin/main`:
`step_range.sh` + `audit_log.py` (local-spool read-back, comingled operational + audit-of-record in
`audit/log/**`), `require_tier_ceiling`/`require_overseer_approval`/`require_human_approval` (LOW / native
pass), `protected_surfaces.txt`, the trusted-base workflow, `bin/hos-cron` (5-minute cadence), `get_app_token.sh`
(no auditsync role), the config generator (`PACK=` mechanism), and **`overseer.md`'s review flow (the HIGH
finding)**. **LOWER** on anything downstream of the unread issues and the unverified live-ruleset state — `gh`
is unauthenticated here, the inherited gap — which is why Component J (the ruleset change) and the live-
permission checks stay human/operator actions.

**BLAST RADIUS:** the audit trail's integrity and the audit-to-`main` mechanism on every consumer deployment;
a **new cross-consumer contract** (`contract/AUDIT-RECORDING-CONTRACT.md`) every future audit backend must
honor; the dispatcher (`record_event`) every producer now calls; and the implementation surface — seven
protected surfaces (`contract/**`, `scripts/framework/**`, `.github/workflows/**`, `bin/**`, `bootstrap/**`,
`.claude/agents/**`, `docs/AGENT-IDENTITY.md`) plus the `main` ruleset — so the implementation PR is
human-approved at merge regardless of computed tier.

**Change classification: STRUCTURAL.** It defines a new cross-consumer contract, introduces a storage-backend
extension point, changes the audit-to-`main` mechanism, adds a required status check to the `main` ruleset,
re-scopes the auditsync identity, and supersedes a standing (unmerged) design plus a standing `DECISIONS.md`
bypass entry and its setup docs. Per the CORE product-boundary checkpoint, the structural items require
explicit human sign-off before they bind. **This is a design for a future v0.7.0 build; `coder` is not
cleared, and this document is not the merge-time human approval the implementation PR will require.**

**Next step:** `architect` review of this DRAFT 1 — in particular ESC-1 (the overseer audit-PR path, the one
finding that changes the component set), ESC-2 (the tier factoring), and ESC-3 (adapter discovery) — then a
`needs-ai` issue carrying the build order and PR split (§11) into the v0.7.0 milestone.
