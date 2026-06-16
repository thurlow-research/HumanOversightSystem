# Technical Design — Issue #317: Worker Pre-PR Readiness Gate and Overseer Bounce-Back Rule

**Status:** Implemented — commit feat(#317)
**Step:** v0.4.0
**Author:** technical-design agent
**Architect sign-off:** GO — all 6 open questions resolved; 5 binding conditions
**Date:** 2026-06-16

RISK: MEDIUM | CONFIDENCE: HIGH | Change class: additive

---

## Architect rulings (binding)

| Question | Decision |
|---|---|
| Q1 — CONDITIONAL_PROCEED | Surface conditional items as `## Conditional items` section in PR body; matrix already routes to HUMAN_REQUIRED |
| Q2 — Bounce routing | Leave PR open; assign to HOSWorkerTutelare; label needs-ai; post bounce comment; convert to draft (HOSOversightTutelare is maintainer — reliable, not best-effort); do NOT close |
| Q3 — Gate timing | Autonomous sequence: 8=build chain, 8.5=evaluator dispatch, 8.9=deterministic gate, 9=PR |
| Q4 — Interactive | Gate AND human confirmation, in that order; failing gate → no "open anyway" |
| Q5 — Failure cap | Verified: record_task_failure() is sole increment path; bounce path never calls it; regression test added |
| Q6 — Register currency | Commit-range scoping (base_sha..HEAD) sufficient; full timestamp ordering is future work |

**Five binding conditions (code-reviewer must verify):**
1. Marker head_sha staleness guard — mismatch = FAIL
2. Missing/malformed marker = FAIL (fail-closed)
3. session-state.md write failure = hard FAIL; claim-envelope failure = warn + audit event (asymmetric)
4. Draft-conversion upgraded to required (maintain role); retain transient-error handling
5. record_pr_bounce must never call record_task_failure

---

## Component map

| # | Artifact | Type | Branch |
|---|---|---|---|
| A | `scripts/automation/lib/pr_readiness.py` | new Python module | impl |
| B | bounce functions in `scripts/automation/lib/merge_authority.py` | additions | impl |
| C | `worker.md` CORE steps 8.5, 8.9, re-entry | agent contract edit | release |
| D | `overseer.md` CORE step 4a | agent contract edit | release |
| E | `contract/OVERSIGHT-CONTRACT.md` §6a, §7 | contract edit | release |
| F | `METHODOLOGY.md` pipeline diagram | doc edit | release |
| G | `tests/automation/test_phase_c.py` 15 new tests | test | impl |

---

## pr_readiness.py — key design decisions

**Entry point:** `assess_pr_readiness(cid, base_sha, head_sha, *, repo_root, step, risk_tier, system_test_applicable, write_state) -> ReadinessResult`

**Check ordering:** all 14 checks run even after a FAIL (full result always produced)

**Marker staleness (checks 1–2):** gate reads markers worker writes after completing step 8:
- `.claudetmp/oversight/inner-loop-result.json` — `{exit_code, head_sha}`
- `.claudetmp/oversight/gates-result.json`
- head_sha comparison is REQUIRED (architect binding 1)
- Missing = FAIL always (architect binding 2)

**session-state.md write:** hard FAIL if write fails (authoritative store). Claim-envelope write is best-effort — failure emits structured audit event, does not FAIL the gate (architect binding 3, asymmetric).

**Tier comparison:** `_tier_gte()` using SAFE < LOW < MEDIUM < HIGH < CRITICAL from schema.py (never hardcoded).

**CLI:** `python -m scripts.automation.lib.pr_readiness --cid C --base-sha B --head-sha H`
Exit 0 = PASS, 1 = FAIL, 2 = operational error.

---

## merge_authority.py additions

**bounce_count(cid, repo_root) → int:** counts pr-bounced events in audit/oversight-log.jsonl where event["cid"] == cid. Independent of failure-cap store (architect binding 5).

**check_register_completeness(pr_number, cid, *, repo_root) → BounceDecision**

**record_pr_bounce(pr_number, cid, failures, *, repo_root, worker_account) → None:**
Sequence: comment POST → assign POST → label POST → draft-convert PATCH (transient errors non-blocking per binding 4) → audit event append. Audit event only written after first 3 succeed.

**Bounce comment machine-parseable format:**
`### Specific failures` section: one `- [<CHECK-ID>] <detail>` per line. Trailing `<!-- hos-bounce: cid=... bounce_number=... -->` for programmatic parsing.

---

## pr-bounced audit event schema

```json
{"event":"pr-bounced","pr":318,"cid":"a1b2c3d4","bounce_number":1,"failures":["REQ-W-05","REQ-W-13"],"assigned_to":"HOSWorkerTutelare","repo":"thurlow-research/HOS","timestamp":"2026-06-16T19:04:11Z"}
```
Appended with compact JSON separators. File created if absent.

---

## Q5 verification finding

Confirmed on feat/254-unattended-worker-impl: record_task_failure() (breakers.py:52) is the sole writer of the per-cid failure counter. Full-tree search returns only definition and tests; no production code path calls it from bounce. No breakers.py change required — invariant holds by construction.

---

## Startup-artifact-gap

Worker.md and overseer.md CORE contracts were approved without a pre-PR gate; they assumed the build chain always produced a complete register. #317 closes that assumption gap. Affected sign-offs: worker.md and overseer.md re-review scoped to the new sections only. Merge-authority matrix unchanged — its prior sign-off stands. breakers.py — prior sign-off stands.
