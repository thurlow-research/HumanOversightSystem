# SPEC-94: Evaluator Independent Tier Floor Re-derivation
**Issue:** #94
**Status:** Draft — for architect review
**Target milestone:** v0.4.0 — Autonomous Worker
**Related spec:** `docs/specs/SPEC-evaluator-re-derivation.md` §1 (consolidated multi-issue treatment; see that document for the full requirement set including acceptance criteria and open architect questions)

---

## Problem Statement

The oversight evaluator reads `risk-assessment.md` to obtain the validated risk tier, then derives the effective human-gate requirement from that tier (contract §7, condition 7). The tier itself is trusted from a self-reported artifact produced by `risk-assessor`. A `risk-assessor` run that under-computes the tier — due to drift, misconfiguration, or a forged or stale artifact — causes the evaluator to derive the wrong human-gate requirement with no independent check.

The specific failure mode: a diff touching auth, payment, or financial paths that deterministically requires a HIGH or CRITICAL floor can arrive at the evaluator with `validated_tier: MEDIUM` in `risk-assessment.md`. The evaluator accepts the tier at face value. The effective human gate does not fire. The mandatory cross-vendor second review for CRITICAL steps is not enforced. The change proceeds under-scrutinized.

This is cited in the Opus/codex review findings as a governance gap: the oversight system independently re-derives N/A waivers and structural-override signals from the diff (conditions 9–10), but the tier — which controls which of those conditions even apply — is exempt from independent re-derivation.

The primary human gate is `manifest.human_gate_required: true`, set by a human. The tier-floor path is defense-in-depth: it catches steps where the manifest tier was set correctly but `risk-assessor` under-computes the dynamic floor, or where the tier was never updated in the manifest for a step whose scope grew.

---

## Scope

This spec covers:

- Extending `change_classifier.py` with a `detect_tier_floor()` function and `--tier-floor` CLI flag that deterministically re-derives the minimum tier from the diff using path and content patterns.
- Extending the oversight evaluator Phase 1 compliance check to run the tier-floor re-derivation and fail when the self-reported validated tier falls below the independently re-derived floor (new compliance condition 11).
- A new `tier-floor-mismatch` audit event in `audit/oversight-log.jsonl`.

This spec does not cover:

- Changes to how `risk-assessor` computes the tier (that is an implementation concern for `risk-assessor`).
- The full composite score validators (`rn_calculator.py`, `migration_scorer.py`) — those remain separate risk signals feeding the composite score; the tier floor here is a path-pattern floor running inside the evaluator, independent of the validator pipeline.
- The consolidation of tier-floor rules with the composite validator rule sets (an open architect question — see ARCH-Q-1 in `SPEC-evaluator-re-derivation.md` §1).

---

## Requirements

**R1 — Tier floor function in `change_classifier.py`.**

`change_classifier.py` must implement a `detect_tier_floor(name_status, added) -> str` function returning one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`. The function applies path and content-pattern rules deterministically. The highest matching tier wins. The rule set is:

| Tier floor | Trigger |
|---|---|
| CRITICAL | Changed file path matching: `**/payment*`, `**/billing*`, `**/financial*`, `**/checkout*`, `**/subscription*`, `**/invoice*`, `**/stripe*`, `**/braintree*`, `**/paypal*` |
| CRITICAL | Added line matching PCI/financial API patterns: `stripe.`, `braintree.`, `PaymentIntent`, `charge(`, `Card(`, `ACH`, `IBAN`, `account_number` |
| HIGH | Changed file path matching: `**/auth*`, `**/login*`, `**/logout*`, `**/session*`, `**/token*`, `**/credential*`, `**/password*`, `**/mfa*`, `**/totp*`, `**/oauth*`, `**/sso*`, `**/jwt*` |
| HIGH | Changed file matching the migration pattern: `**/migrations/00*.py` or `**/migrations/*.py` |
| HIGH | Added line matching PII field patterns: `EmailField`, `first_name`, `last_name`, `date_of_birth`, `ssn`, `national_id`, `phone_number`, `address`, `personal_data` |
| HIGH | Changed file path matching: `**/pii*`, `**/gdpr*`, `**/privacy*`, `**/consent*` |
| MEDIUM | Changed file with extension `.py`, `.js`, `.ts`, `.jsx`, `.tsx` not covered by a higher tier |
| LOW | All other changes |

The function must apply the `FRAMEWORK_TOOLING` exemption already present in `change_classifier.py` to the added-line pattern checks (not to the file-path checks — a financial path in the framework tooling tree is still a structural pattern worth flagging).

The function must accept a `--tier-floor` CLI flag that emits:
```json
{"tier_floor": "<TIER>", "evidence": [{"rule": "<description>", "file": "<path>", "pattern": "<matched pattern>"}]}
```
It must not emit domains or structural signals when `--tier-floor` is used.

**R2 — Evaluator Phase 1 compliance check (condition 11).**

During Phase 1, after establishing the validated tier from `risk-assessment.md`, the evaluator must:

1. Run `change_classifier.py --tier-floor --base <BASE_SHA> --head <HEAD_SHA>` using the register-header commit range.
2. Read `tier_floor` from the result.
3. Compare `tier_floor` to `validated_tier` from `risk-assessment.md`.
4. If `validated_tier` is below `tier_floor` AND `.claudetmp/oversight/human-tier-override.md` does not exist: **COMPLIANCE FAIL** (condition 11). The failure message must state the re-derived floor, the self-reported tier, and the evidence list (specific files and patterns that triggered the floor).

This check runs **only in the loosening direction**: if `validated_tier >= tier_floor`, no action is taken. If `human-tier-override.md` exists (a human explicitly authorized a lower tier), no check is performed regardless of the floor.

**R3 — Audit event `tier-floor-mismatch`.**

When condition 11 fires, the evaluator must append a `tier-floor-mismatch` event to `audit/oversight-log.jsonl`:

```json
{
  "event": "tier-floor-mismatch",
  "step": <N>,
  "re_derived_floor": "<TIER>",
  "self_reported_tier": "<TIER>",
  "evidence": [{"rule": "...", "file": "...", "pattern": "..."}],
  "timestamp": "<ISO-8601>"
}
```

This event is emitted even when the evaluator subsequently escalates (the escalation is the compliance outcome; the event is the research record).

---

## Non-Requirements

- This spec does not define a new tier-computation algorithm. It defines a floor: a deterministic minimum that the evaluator independently checks. Risk-assessor may still compute a higher tier than the floor; the floor is a lower bound only.
- This spec does not require `risk-assessor` to be rewritten. The floor check is an independent layer in the evaluator that re-derives the minimum from the diff regardless of what risk-assessor computed.
- This spec does not cover false-positive tuning of the path patterns. The rule set is deliberately conservative (over-detect bias, per the framework ratchet principle). False positives send a benign change to a human; false negatives are the only real failure.
- This spec does not require changes to the step manifest schema.

---

## Artifact Changes

| Artifact | Required change |
|---|---|
| `scripts/oversight/change_classifier.py` | Add `detect_tier_floor()`, `--tier-floor` CLI flag |
| `.claude/agents/oversight-evaluator.md` | Add Phase 1 condition 11 check (after the existing risk-assessment scope check) |
| `contract/OVERSIGHT-CONTRACT.md` | Add condition 11 to §7; add `tier-floor-mismatch` to the §6a event catalog |

---

*Status: Draft — for architect review*
*Author: pm-agent | 2026-06-17*
