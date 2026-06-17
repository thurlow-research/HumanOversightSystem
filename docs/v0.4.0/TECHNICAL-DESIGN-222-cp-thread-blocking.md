# Technical Design — SPEC-222: CONDITIONAL_PROCEED Thread Blocking

**Spec:** `docs/specs/SPEC-222-conditional-proceed-thread-blocking.md`
**Issue:** #222 (with product-boundary clearance tracked in #399)
**Architect ruling:** GO
**Author:** technical-design
**Date:** 2026-06-17
**Status:** DESIGN — partial implementation (parts gated on #399 and on R1.5 API verification are deferred)

---

## 0. Scope of THIS implementation (read first)

SPEC-222 has four requirement clusters (R1–R4). This design and the accompanying
implementation deliberately ship only the parts that do **not** require human
clearance (#399) and do **not** require empirical GitHub-API verification (R1.5).
The remainder is specified here but explicitly deferred so the contract is
unambiguous for the follow-up step.

| Req | Description | This change? | Gate |
|---|---|---|---|
| R1 (R1.1–R1.4) | Post one PR review thread per conditional item | **DEFERRED** | R1.5 API verification must complete first |
| R1.5 | Empirically verify which GitHub API creates a `required_conversation_resolution`-resolvable thread | **DEFERRED** | Must be done before any R1 implementation |
| R2 (R2.1–R2.3) | Branch-protection flip + runtime warning | **DEFERRED** | #399 human clearance (merge-gate default change for ALL PRs) |
| R3.1 | Evaluator WARN/FAIL logic for thread existence vs ledger | **IMPLEMENT (stub)** | none — logic added now, no-op until R1 exists |
| R3.2 | Evaluator must not FAIL on all-resolved threads (ledger-contradiction tamper FAIL is the #399-gated half) | **DEFERRED** | #399 (the tamper-FAIL contradiction check is part of #399 scope) |
| R3.3 | Evaluator check: did orchestrator post a review request to the human reviewer? | **IMPLEMENT** | none |
| R3.4 | Evaluator check: `conditional_threads_opened` field present in process record | **IMPLEMENT** | none |
| R4.1 | Orchestrator requests human-reviewer review | **IMPLEMENT** | none |
| R4.2 | Orchestrator posts worker summary comment | **DEFERRED** | couples to R1 (thread count) — defer with R1 |
| R4.3 | Orchestrator records `conditional_threads_opened: N` in process record | **IMPLEMENT (N=0)** | none — seeds the evaluator check; N=0 until R1 posts threads |

Net of THIS change: the evaluator gains three compliance checks (R3.1 stub,
R3.3, R3.4) and the orchestrator gains a ledger field write (R4.3, N=0) plus an
explicit human-reviewer review request (R4.1). No threads are posted yet (R1),
no branch protection is changed (R2), and the tamper-contradiction FAIL (R3.2's
companion) is not armed.

**Why N=0 is correct and not a bug:** R1 is not built, so the orchestrator
posts zero threads. Recording `conditional_threads_opened: 0` is the truthful
count. It also means the evaluator's R3.1 logic resolves to the WARN branch
(threads absent AND ledger=0 → ambiguous WARN), never the FAIL branch
(ledger>0 AND no threads → tamper). The FAIL branch is unreachable until R1
posts threads and writes a non-zero count — which is exactly the intended
no-op-until-R1 behavior.

---

## 1. The "ledger" / "process record" — concrete binding

SPEC-222 refers to a "ledger" and a "process record." In this codebase that is
the append-only audit log `audit/oversight-log.jsonl` (see contract §6a). The
"process record for the step" is the orchestrator's per-step disposition event
in that log.

**Contract gap closed by this design:** the orchestrator does **not** currently
emit any `conditional_proceed` event, and §6a does not catalog one. The audit
script `scripts/oversight/audit_conditional_proceed.sh` already *reads* a
`conditional_proceed` event case-insensitively, so the producer side has been
missing. This design defines that producer event as the carrier for
`conditional_threads_opened`.

### Event contract: `conditional_proceed`

Emitted by `oversight-orchestrator` on the CONDITIONAL_PROCEED path, **after**
the PR is opened (so a PR number exists) and the review request is sent.

```json
{
  "event": "conditional_proceed",
  "step": N,
  "pr": <PR_NUMBER>,
  "conditional_items": <integer count of items in the evaluator's list>,
  "conditional_threads_opened": <integer count of threads actually posted>,
  "review_requested": "<HUMAN_REVIEWER login>",
  "timestamp": "<ISO-8601 UTC>"
}
```

Field semantics:
- `conditional_items` — how many items the evaluator's CONDITIONAL_PROCEED
  verdict listed. Source of truth for "how many threads *should* exist."
- `conditional_threads_opened` — how many threads the orchestrator successfully
  posted. **In THIS change it is always `0`** (R1 not built). When R1 ships it
  becomes the true posted count, and the invariant `conditional_threads_opened
  == conditional_items` (or a halt) is enforced by R1.4.
- `review_requested` — the login passed to `gh pr edit --add-reviewer`
  (R4.1). For this codebase that is `ScottThurlow` (the `HUMAN_REVIEWER` for
  the framework repo). Consumers read it from `machine-accounts.env:HUMAN_REVIEWER`.

This event is the single process record the evaluator reads in R3.1 and R3.4.
It is append-only; it is never mutated.

---

## 2. R4 — Orchestrator changes (oversight-orchestrator.md, CONDITIONAL_PROCEED path)

### 2.1 R4.1 — Review request (IMPLEMENT)

After opening the PR, the orchestrator must request a review from the human
reviewer so GitHub notifies them:

```bash
gh pr edit "$PR_NUMBER" --add-reviewer ScottThurlow
```

Boundary / contract:
- This must run **only** on the CONDITIONAL_PROCEED path (PROCEED and ESCALATE
  are unchanged — ESCALATE opens no PR; PROCEED relies on the panel, not a
  direct human review request).
- The reviewer login is the framework's `HUMAN_REVIEWER` (`ScottThurlow`).
  Consumer installs read it from `machine-accounts.env`; the agent text names
  `ScottThurlow` as the framework default and points to `HUMAN_REVIEWER` as the
  source of truth.
- It must not block PR opening on failure of the add-reviewer call, but it must
  surface the failure (print it) — a missing review request is the R3.3 WARN
  signal, and the evaluator catches it downstream.

### 2.2 R4.3 — Ledger field (IMPLEMENT, N=0)

After opening the PR and sending the review request, append the
`conditional_proceed` event (§1) to `audit/oversight-log.jsonl` with
`conditional_threads_opened: 0` (R1 not yet built):

```bash
printf '{"event":"conditional_proceed","step":%s,"pr":%s,"conditional_items":%s,"conditional_threads_opened":%s,"review_requested":"%s","timestamp":"%s"}\n' \
  "$N" "$PR_NUMBER" "$ITEM_COUNT" 0 "ScottThurlow" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  >> audit/oversight-log.jsonl
```

`$ITEM_COUNT` is the number of numbered items in the "Human Review Required
Before Merge" section the orchestrator already builds. `conditional_threads_opened`
is hard-`0` until R1 ships — at which point it becomes the posted-thread count
and the R1.4 assertion guarantees it equals `$ITEM_COUNT` or halts.

Boundary:
- The orchestrator's input-validation already permits `audit/oversight-log.jsonl`
  as a non-"dirty-source" write (the staleness check at lines 41–51 explicitly
  excludes `audit/`), so appending this event does not trip its own clean-tree
  guard.

### 2.3 Deferred orchestrator parts (DO NOT IMPLEMENT)

- **R1.1–R1.4** thread posting — deferred pending R1.5 API verification.
- **R4.2** worker summary comment — its body states the thread count and the
  no-close/no-push instruction; that count is meaningless at N=0, and the
  comment is logically part of the R1 thread-posting flow. Defer with R1.

---

## 3. R3 — Evaluator changes (oversight-evaluator.md, Phase 1)

All three checks fire **only** when the step's recommendation is
CONDITIONAL_PROCEED. They are added as a new Phase 1 compliance block
("CONDITIONAL_PROCEED thread compliance"). They run after the existing sign-off
and gate checks. None of them is a hard ESCALATE in this change — the armed
outcomes are WARN (and one FAIL branch that is unreachable until R1 ships).

The evaluator reads the step's `conditional_proceed` process record by scanning
`audit/oversight-log.jsonl` for the newest line with `"event":"conditional_proceed"`
and matching `"step": N`. If no such line exists, see R3.4.

### 3.1 R3.4 — Ledger field presence (IMPLEMENT)

If the recommendation is CONDITIONAL_PROCEED:
- If no `conditional_proceed` event exists for step N in the log, OR the event
  exists but has no `conditional_threads_opened` field → **COMPLIANCE WARN**:
  "CONDITIONAL_PROCEED step {N} has no `conditional_threads_opened` field in its
  process record (`audit/oversight-log.jsonl`) — cannot verify thread posting."
- Otherwise record the field's integer value for use by R3.1.

This is a WARN, not a FAIL: a missing field is an instrumentation gap, not a
tamper signal. The tamper FAIL is R3.2's companion (deferred, #399).

### 3.2 R3.1 — Thread existence vs ledger (IMPLEMENT as stub)

Applicable only when a PR number is available (R3.4 of the spec — if no PR
number, skip and note "no PR context; thread-existence check N/A"). The
evaluator queries the PR's review threads (e.g. `gh pr view <PR> --json reviews`
or the GraphQL review-threads query) and counts unresolved orchestrator-posted
conditional threads.

Outcomes (let `L` = `conditional_threads_opened` from the ledger, `U` = count of
unresolved orchestrator conditional threads observed, `Rv` = resolved-thread
evidence present):

- **COMPLIANCE WARN** — `U == 0` AND `L == 0`. Ambiguous: threads may have been
  resolved already, or were never posted. State: items listed by the verdict,
  `U == 0` observed, `L == 0` recorded. **This is the branch THIS change always
  hits** (because R4.3 always writes `L == 0` until R1 ships).
- **COMPLIANCE FAIL (tampering signal)** — `L > 0` AND `U == 0` AND `Rv` is
  empty (no resolution events from any account). Threads were reportedly posted
  but vanished with no resolution record. Escalate with COMPLIANCE FAIL, state
  the discrepancy, halt evaluation. **Unreachable until R1 writes `L > 0`** —
  this is the no-op-until-R1 property by construction.

The check must NOT fail on unresolved threads (R3.3 of spec — unresolved is the
human's gate, not the evaluator's) and must NOT fail on all-resolved threads
(R3.2 of spec — resolved threads did their job; note "conditional items
resolved"). The all-resolved happy path and the contradiction tamper-FAIL that
*pairs with* it are part of #399 scope; the WARN/FAIL skeleton is what ships now.

**Why this is a safe stub:** with R1 absent, every CONDITIONAL_PROCEED step
records `L == 0` and posts `U == 0` threads, so R3.1 deterministically resolves
to WARN. No false FAIL is possible. When R1 ships and starts writing `L > 0`,
the FAIL branch arms automatically with no further evaluator change.

### 3.3 R3.3 (spec) — Review-request posted (IMPLEMENT)

If the recommendation is CONDITIONAL_PROCEED, the evaluator verifies the
orchestrator requested a review from the human reviewer:
- Read `review_requested` from the `conditional_proceed` process record; if the
  field is absent OR empty → **COMPLIANCE WARN**: "CONDITIONAL_PROCEED step {N}
  has no recorded human-reviewer review request — verify `ScottThurlow` was
  added as a reviewer."
- If a PR number is available, the evaluator MAY cross-check against
  `gh pr view <PR> --json reviewRequests`; a recorded `review_requested` that
  does not appear among the PR's requested reviewers is also a WARN. (Cross-check
  is best-effort; the recorded field is the primary signal.)

WARN, not FAIL: a missing review request is a notification gap the human can
still recover from (the PR is open and visible), not a merge-gate breach.

### 3.4 Output

The evaluator's Phase 1 output gains a "CONDITIONAL_PROCEED thread compliance"
subsection listing each of the three checks and its WARN/FAIL/PASS/N-A result.
A WARN here does not change the overall recommendation (CONDITIONAL_PROCEED
stays CONDITIONAL_PROCEED); it is surfaced in the conditional items so a human
sees it. A FAIL (R3.1 tamper branch, when armed) flips the recommendation to
ESCALATE per the existing "any hard compliance check fails → ESCALATE" rule.

---

## 4. Affected artifacts (this change only)

| Artifact | Change | Status |
|---|---|---|
| `.claude/agents/oversight-orchestrator.md` | CONDITIONAL_PROCEED path: add R4.1 review request + R4.3 ledger `conditional_proceed` event (N=0) | IMPLEMENT |
| `.claude/agents/oversight-evaluator.md` | Phase 1: add CONDITIONAL_PROCEED thread-compliance block (R3.1 stub, R3.3, R3.4) | IMPLEMENT |
| `contract/OVERSIGHT-CONTRACT.md` §6a | Catalog the `conditional_proceed` audit event | IMPLEMENT |
| `scripts/framework/setup_branch_protection.sh` | flip `required_conversation_resolution` | **DEFERRED — #399** |
| `docs/MACHINE-ACCOUNTS-SETUP.md` | branch-protection setup step | DEFERRED (pairs with R2/#399) |

No new files. No contract version bump (additive-only, contract §8). The
`conditional_proceed` event is additive to the §6a catalog.

---

## 5. Self-flag (HOS authoring contract)

RISK: LOW
CONFIDENCE: HIGH

Classification: **additive**. This change adds evaluator checks and one
orchestrator ledger field + review request; it does not change any existing
merge gate, does not post threads, does not flip any default, and does not alter
the PROCEED/ESCALATE paths. The one FAIL branch introduced (R3.1 tamper) is
provably unreachable until R1 ships. No structural change → no human gate beyond
the architect GO already on record. Parts that ARE structural (R2 branch-protection
flip, R3.2 contradiction FAIL) are explicitly excluded pending #399.

This is not a startup-artifact-gap for the implemented slice: the evaluator
checks and ledger field are new instrumentation, not a correction to a contract
that prior code was already built against. (The branch-protection default IS a
startup-artifact-gap, tracked in #399, and is excluded here.)
