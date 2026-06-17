# Technical Design — SPEC-94: Evaluator Independent Tier Floor Re-derivation

**Issue:** #94
**Spec:** `docs/specs/SPEC-94-evaluator-tier-floor-rederivation.md` (consolidated: `docs/specs/SPEC-evaluator-re-derivation.md` §1)
**Architect ruling:** GO (bindings reproduced below)
**Author:** technical-design | 2026-06-17
**Status:** For implementation

---

## 1. Purpose and boundary

The evaluator currently trusts the `validated_tier` self-reported by `risk-assessor`
in `risk-assessment.md`. This design adds an **independent, deterministic tier floor**
re-derivation that runs inside the evaluator's Phase 1 compliance check, mirroring the
existing conditions 9–10 anti-gaming pattern (re-derive from the diff, compare to the
self-report, fail only in the loosening direction, escalate to the human on mismatch).

This is **defense-in-depth**, not the primary human gate (`manifest.human_gate_required`).
It catches the case where the manifest tier was set correctly but `risk-assessor`
under-computes the dynamic floor, or the manifest tier was never raised when a step's
scope grew.

**Out of scope (unchanged by this design):** how `risk-assessor` computes the tier; the
composite-score validators (`rn_calculator.py`, `migration_scorer.py`) which remain
separate signals feeding the composite score; the step-manifest schema.

---

## 2. Architect bindings (authoritative constraints)

1. **`detect_tier_floor(changed_files, added_lines_by_file)`** in `change_classifier.py`
   returns a tier string (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`).
2. **Floor patterns stay SEPARATE from `ADDED_LINE_SIGNATURES`** — each new floor pattern
   block carries a comment back-referencing the sibling list in the composite validators
   (ARCH-Q-1 default: keep separate, do not consolidate; re-evaluate after first use).
3. **`FRAMEWORK_TOOLING` exemption applies to added-line checks but NOT to file-path
   checks.** Reuse the existing `FRAMEWORK_TOOLING` regex; do not copy it. A financial path
   in the framework-tooling tree is still a structural pattern worth flagging; a financial
   *literal string inside* a framework-tooling `.py` file is the classifier matching its own
   pattern definitions (HOS#117) and is exempted.
4. **Evaluator condition 11 (new):** after conditions 9/10, invoke
   `change_classifier.py --tier-floor`, compare to `validated_tier` from
   `risk-assessment.md`. COMPLIANCE FAIL if `validated_tier < floor` AND no
   `human-tier-override.md` exists.
5. **Escape valve:** `.claudetmp/oversight/human-tier-override.md` is the human-gated
   override (evaluator.md "Human authorization file integrity" — already enumerated there).
6. **New `tier-floor-mismatch` audit event** written when condition 11 fires.

---

## 3. Component map

| Component | File | Change |
|---|---|---|
| `detect_tier_floor()` | `scripts/oversight/change_classifier.py` | New function (contract below) |
| Tier-floor pattern blocks | `scripts/oversight/change_classifier.py` | New module-level pattern constants, separate from `ADDED_LINE_SIGNATURES` |
| `--tier-floor` CLI flag | `scripts/oversight/change_classifier.py` `main()` | New flag + output branch |
| Condition 11 | `.claude/agents/oversight-evaluator.md` | New Phase 1 check after the structural-override (condition 10) block |
| `tier-floor-mismatch` event | `contract/OVERSIGHT-CONTRACT.md` §6a | New catalog row |
| Condition 11 in §7 | `contract/OVERSIGHT-CONTRACT.md` §7 | New labelled compliance condition |
| Tests | `tests/oversight/test_change_classifier.py` | New `detect_tier_floor` test cases |

---

## 4. `detect_tier_floor` contract

### 4.1 Signature

```python
TIER_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]  # index = severity rank

def detect_tier_floor(
    name_status: list[tuple[str, str]],
    added: dict[str, list[str]],
) -> tuple[str, list[dict]]:
    """Return (tier_floor, evidence).

    tier_floor: one of LOW/MEDIUM/HIGH/CRITICAL — the highest matching tier.
    evidence:   list of {"rule": str, "file": str, "pattern": str} for every
                rule that matched, across all tiers (not only the winning tier).
    """
```

Architect binding 1 names the parameters `(changed_files, added_lines_by_file)`. The
existing module's detection functions are uniformly `(name_status, added)`; `name_status`
**is** the changed-files channel (list of `(status_letter, path)`) and `added` **is**
`added_lines_by_file`. The function keeps the module-internal `(name_status, added)`
parameter names for consistency with `detect_domains`/`detect_structural`; this satisfies
binding 1 (the two channels — changed file paths, added lines by file — are both present
and used). No call site outside the module relies on the names.

### 4.2 Determinism — highest tier wins

The function evaluates **every** rule and records evidence for each match. The returned
`tier_floor` is the maximum severity (by `TIER_ORDER` index) over all matched rules. The
MEDIUM "any application-code file" rule and the LOW "all other" rule are the catch-all
base: a `.py`/`.js`/`.ts`/`.jsx`/`.tsx` file with no higher match floors at MEDIUM; a diff
with no application-code files and no higher match floors at LOW.

### 4.3 Rule set (exactly the spec R1 table)

Pattern blocks are **module-level constants, separate from `ADDED_LINE_SIGNATURES`**
(binding 2). Each block carries a comment back-referencing the sibling list in the
composite validators (`rn_calculator.py` path globs / `migration_scorer.py`).

**File-path rules (NOT exempted by `FRAMEWORK_TOOLING`, binding 3):**

| Tier | Path regex (case-insensitive, substring on basename or full path) |
|---|---|
| CRITICAL | `payment`, `billing`, `financial`, `checkout`, `subscription`, `invoice`, `stripe`, `braintree`, `paypal` |
| HIGH | `auth`, `login`, `logout`, `session`, `token`, `credential`, `password`, `mfa`, `totp`, `oauth`, `sso`, `jwt` |
| HIGH | migration files: `migrations/00*.py` or `migrations/*.py` (regex `migrations/.*\.py$`) |
| HIGH | `pii`, `gdpr`, `privacy`, `consent` |

The spec uses `**/payment*` glob form; the implementation uses an equivalent
case-insensitive `re.search` on the path. `**/payment*` means "a path component beginning
with `payment`"; the regex form `(^|/)payment` over the path captures this with the
conservative (over-detect) bias the framework ratchet requires. Auth-style HIGH patterns
likewise match `(^|/)<word>`.

**Added-line rules (exempted by `FRAMEWORK_TOOLING`, binding 3):**

| Tier | Added-line regex |
|---|---|
| CRITICAL | `stripe.`, `braintree.`, `PaymentIntent`, `charge(`, `Card(`, `ACH`, `IBAN`, `account_number` |
| HIGH | `EmailField`, `first_name`, `last_name`, `date_of_birth`, `ssn`, `national_id`, `phone_number`, `address`, `personal_data` |

For added-line rules, files whose path matches `FRAMEWORK_TOOLING`
(`(^|/)scripts/(oversight|framework)/.*\.py$`) are **skipped** — the classifier's own
source contains these literals as pattern definitions and would self-match (HOS#117). The
skip applies to the per-file added-line loop only; the file-path rules above scan all
changed paths including the framework tree.

**MEDIUM / LOW catch-all:**

| Tier | Trigger |
|---|---|
| MEDIUM | any changed file with extension `.py`/`.js`/`.ts`/`.jsx`/`.tsx` not covered above |
| LOW | all other changes |

### 4.4 Evidence schema

Each evidence entry: `{"rule": "<short description>", "file": "<path>", "pattern": "<the matched pattern/regex token>"}`.
The `rule` string names the tier and channel (e.g. `"CRITICAL path: payment"`,
`"HIGH added-line: PII field"`, `"MEDIUM application-code file"`). Evidence is collected
for all matches so the evaluator's fail message can list every triggering file/pattern.

### 4.5 Edge cases

- Empty diff → `("LOW", [])`.
- File path matches both CRITICAL and HIGH → CRITICAL (max wins); both evidence rows recorded.
- A CRITICAL financial path inside the framework tree → still CRITICAL (path rule not exempted).
- A CRITICAL financial *literal* added inside `scripts/oversight/foo.py` → not matched
  (added-line rule exempted for framework tree); but if that file's *path* also matched a
  path rule it would still floor on the path rule.

---

## 5. `--tier-floor` CLI flag

In `main()`:

- Add `ap.add_argument("--tier-floor", action="store_true", ...)`.
- When `--tier-floor` is set, the output is **exclusively** the tier-floor object; domains
  and structural signals are NOT emitted (spec R3, R1 final sentence):

```json
{"tier_floor": "<TIER>", "evidence": [{"rule": "...", "file": "...", "pattern": "..."}]}
```

- `--explain` with `--tier-floor` prints a human-readable listing: the floor tier followed
  by one line per evidence entry (acceptance criterion in the consolidated spec).
- `--tier-floor` is mutually independent of `--domains-only`/`--structural-only`; when
  `--tier-floor` is present it takes the whole output (the other flags are ignored for the
  tier-floor invocation, which the evaluator always calls standalone).
- Exit code 0 (reporter contract, unchanged); exit 2 only on git error (existing `_git`).

---

## 6. Evaluator condition 11

Added to `.claude/agents/oversight-evaluator.md` Phase 1, **after** the structural-override
(condition 10) block and **before** the gate-results compliance block, so it sits with the
other diff re-derivation checks.

### 6.1 Algorithm

1. The validated tier is already established earlier in Phase 1 (`validated_tier`,
   the `max(manifest, risk-assessment.md)` floor). `BASE_SHA`/`HEAD_SHA` are already
   resolved in the register-header step.
2. Run:
   ```bash
   python3 scripts/oversight/change_classifier.py --tier-floor \
     --base "$BASE_SHA" --head "$HEAD_SHA"
   ```
3. Parse `tier_floor` and `evidence` from the JSON.
4. Compute severity rank of `validated_tier` and `tier_floor` via the fixed order
   `LOW < MEDIUM < HIGH < CRITICAL`.
5. **If `rank(validated_tier) < rank(tier_floor)`** (loosening direction only):
   - If `.claudetmp/oversight/human-tier-override.md` exists and is non-empty →
     **no action** (human explicitly authorized a lower tier; escape valve, binding 5).
   - Else → **COMPLIANCE FAIL (condition 11)**. The message states: the re-derived floor,
     the self-reported `validated_tier`, and the evidence list (specific files + patterns).
     Recommendation → ESCALATE (per the Phase 1 end-of-section rule).
6. **If `rank(validated_tier) >= rank(tier_floor)`** → no action (upstream asked for the
   same or more oversight; nothing to guard against — the ratchet).

### 6.2 Audit event (binding 6, spec R3)

When condition 11 **fires** (the FAIL branch, override absent), append to
`audit/oversight-log.jsonl`:

```json
{
  "event": "tier-floor-mismatch",
  "step": N,
  "re_derived_floor": "<TIER>",
  "self_reported_tier": "<TIER>",
  "evidence": [{"rule": "...", "file": "...", "pattern": "..."}],
  "timestamp": "<ISO-8601>"
}
```

The event is emitted on the FAIL — the escalation is the compliance outcome; the event is
the research record. (When the override suppresses the FAIL, no `tier-floor-mismatch`
event is emitted: nothing was loosened against policy.)

### 6.3 Human-authored artifact prohibition

`human-tier-override.md` is already enumerated in the evaluator's "Human authorization file
integrity" section as a file the evaluator may not create/modify/delete. No change needed
there; condition 11 only **reads** it.

---

## 7. Contract changes

### 7.1 §6a event catalog

Add one row:

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `tier-floor-mismatch` | The evaluator's independent tier-floor re-derivation exceeded the self-reported `validated_tier` (loosening), with no `human-tier-override.md` | oversight-evaluator | `step`, `re_derived_floor`, `self_reported_tier`, `evidence` |

### 7.2 §7 compliance condition

The §7 list already reuses some numbers (an existing SPEC-378 item is numbered 11). To
avoid collision while honoring the architect binding's "condition 11" name for the
tier-floor check, the new item is added as a **labelled** condition keyed to its concept
(tier-floor), consistent with how the consolidated spec numbers conditions 11–16 by
concept. The evaluator and contract refer to it as "condition 11 (tier-floor)".

Text added to §7:

> **Condition 11 (tier-floor) — independent tier-floor re-derivation (#94):** the evaluator
> runs `change_classifier.py --tier-floor` over the step's `base_sha..head_sha` and compares
> the re-derived floor to the self-reported `validated_tier`. If `validated_tier` is below
> the re-derived floor AND `.claudetmp/oversight/human-tier-override.md` does not exist →
> **COMPLIANCE FAIL** (the message names the floor, the self-reported tier, and the
> triggering files/patterns). Checked **only in the loosening direction**: when
> `validated_tier >= floor`, or when the human tier-override artifact exists, no check is
> performed. Same anti-gaming shape as conditions 9–10. Emits a `tier-floor-mismatch` audit
> event when it fires.

---

## 8. Test plan

Add to `tests/oversight/test_change_classifier.py`:

- Auth path floors HIGH: `app/auth/views.py` → `HIGH`.
- Payment path floors CRITICAL: `shop/payment/charge.py` → `CRITICAL`.
- Migration path floors HIGH: `app/migrations/0007_x.py` → `HIGH`.
- PII added-line floors HIGH: `app/models.py` with `EmailField` → `HIGH`.
- Financial added-line floors CRITICAL: `svc/pay.py` with `stripe.PaymentIntent` → `CRITICAL`.
- Plain `.py` floors MEDIUM: `app/utils.py` with a benign line → `MEDIUM`.
- Non-code (`README.md`) floors LOW.
- Framework-tooling exemption: an added line containing `account_number` inside
  `scripts/oversight/foo.py` does NOT floor CRITICAL on the added-line rule; but a path
  `scripts/oversight/payment_helper.py` DOES floor CRITICAL on the path rule (binding 3).
- Highest-tier-wins: a diff with both an auth path and a payment path → `CRITICAL`.
- Empty diff → `LOW`.
- Evidence shape: each entry has `rule`/`file`/`pattern` keys.

These are pure-function tests feeding synthetic `name_status` + `added`, matching the
existing test style.

---

## 9. Risk and self-flag

RISK: low — additive, read-only re-derivation; fails only in the loosening direction; the
sole escape valve is a human-gated file already protected by the evaluator's integrity
prohibition. No existing behavior changes when `validated_tier >= floor`.
CONFIDENCE: high.
Change classification: **additive** (new function, new flag, new compliance condition, new
audit event; no existing contract/behavior weakened). Not structural — no human gate is
removed or loosened; the change only adds a tighter gate.
