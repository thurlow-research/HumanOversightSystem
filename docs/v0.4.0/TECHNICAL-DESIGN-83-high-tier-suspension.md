# Technical Design — SPEC-83: HIGH-Tier Security/Privacy Suspension Requires Per-Step Human Authorization

**Issue:** #83
**Spec:** `docs/specs/SPEC-83-high-tier-suspension-per-step.md`
**Architect ruling:** GO (2026-06-17) — schema bindings applied below
**Author:** technical-design
**Date:** 2026-06-17
**Status:** READY FOR IMPLEMENTATION

---

## 0. Architect bindings (authoritative — design conforms to these)

1. Override file location: `contract/tier-overrides/step{N}-human-tier-override.md` (committed, human-only, outside `.claudetmp/`).
2. Override file required fields: `step`, `role`, `authorized_by`, `date` (YYYY-MM-DD), `head_sha`, `reason`.
3. `head_sha` in the override **must equal the evaluated HEAD** — the override is bound to a specific commit.
4. `grandfathered_until: YYYY-MM-DD` field added to `gate-suspension.md`, parsed with the `suspension_manager.py` `review-by:` date idiom. Absent = no grandfathering = FAIL applies. Future date = WARN + CONDITIONAL_PROCEED. Past date = FAIL.
5. Malformed steps: `per_step_scope: true` with empty/absent `steps:` → COMPLIANCE FAIL with a distinct message (R1.6).
6. Fail-closed when the classifier is unavailable: assume the security-relevant surface is present (R2.1).
7. CRITICAL invariant: a `steps:` entry naming a CRITICAL-tier step → FAIL, never authorization (R2.6).
8. New `human-tier-override` audit event in `audit/oversight-log.jsonl` when an override is accepted.
9. `contract/tier-overrides/` must be marked "HUMAN ONLY — agents must not create/modify" in `OVERSIGHT-CONTRACT.md`.

This design is the contract for the coder. It describes **what each component must do**, not its line-level implementation.

---

## 1. Component map

| # | Component | File | Change |
|---|---|---|---|
| 1 | Suspension template schema | `contract/gate-suspension.template.md` | Add `per_step_scope:`, `steps:`, `grandfathered_until:` fields (additive, commented) |
| 2 | Suspension manager parsing | `scripts/oversight/suspension_manager.py` | Add `validate_per_step_scope()` and `check_grandfathered_until()` functions (+ a step-coverage helper) |
| 3 | Evaluator Phase 1 check | `.claude/agents/oversight-evaluator.md` | Add a new HIGH-tier per-step authorization condition, inserted after condition 11 (renumber the structural-modification check to condition 15) |
| 4 | Contract documentation | `contract/OVERSIGHT-CONTRACT.md` | Document `tier-overrides/` human-only invariant, per-step scope fields, `grandfathered_until`, and the new `human-tier-override` audit event |

No application/migration files are created. The `contract/tier-overrides/` directory is created only by a human placing an override file; the implementation never creates it.

---

## 2. Data model / schema contracts

### 2.1 `contract/gate-suspension.template.md` — new fields

Three new fields are added under the existing `security-suspension-acknowledged` comment block. All are **human-set**; agents must not create or modify `gate-suspension.md` (existing invariant, unchanged).

| Field | Type | Required when | Default (absent) | Meaning |
|---|---|---|---|---|
| `per_step_scope` | boolean (`true`/`false`) | optional | `false` (blanket — backward compatible) | When `true`, the security/privacy suspension applies **only** to steps listed in `steps:`. |
| `steps` | YAML-style list of step IDs | required when `per_step_scope: true` | empty | Each entry is a build-step ID matching `contract/step-manifest.yaml` `id` fields. Exact string match. |
| `grandfathered_until` | date `YYYY-MM-DD` | optional | absent → no grandfathering | A human-set transition deadline. Future = WARN path; past = FAIL; absent = FAIL (no grandfathering). |

**Format constraints (parser contract):**
- `per_step_scope:` value is parsed case-insensitively; `true`/`yes`/`1`/`on` → True, everything else → False.
- `steps:` is a YAML-style list — each entry on its own line as `  - {step-id}`, OR an inline `steps: [step-3, step-4]` form. The parser MUST accept both. A step ID is the literal string in the manifest `id:` field (e.g. `step-3`); compared byte-exact, case-sensitive.
- `grandfathered_until:` value matches `\d{4}-\d{2}-\d{2}`, parsed with the same idiom as the `review-by:` annotation (lexicographic `YYYY-MM-DD` string comparison against `_today()`).
- Lines inside HTML comments (`<!-- -->`) are ignored — consistent with `parse_suspensions()` comment handling. The fields are only honored when present outside comment markers (i.e. the human un-commented them).

**Placement (R1.4):** Immediately after the `# security-suspension-acknowledged: yes` comment line, with explanatory comments stating the fields are required when per-step scoping is needed for HIGH-tier steps, and that they are human-set.

### 2.2 `contract/tier-overrides/step{N}-human-tier-override.md` — override artifact (read-only to agents)

Committed, human-only. The evaluator **reads** this file; it must never create, modify, or delete it (same prohibition class as `gate-suspension.md` and `human-authorization.md`).

Required fields (architect binding 2):

| Field | Type | Meaning |
|---|---|---|
| `step` | step ID | The step this override authorizes (must equal the evaluated step). |
| `role` | `security` \| `privacy` | The suspended role this override authorizes for the step. |
| `authorized_by` | string | Name of the authorizing human. |
| `date` | `YYYY-MM-DD` | Date of authorization. |
| `head_sha` | full git SHA | **Must equal the evaluated HEAD_SHA** (binding 3). Binds the override to a specific commit. |
| `reason` | prose | Why the security/privacy review is being waived for this step. |

**Validity contract — the evaluator accepts the override as path (b) only when ALL hold:**
1. File exists at `contract/tier-overrides/step{N}-human-tier-override.md` and is non-empty.
2. `step` field equals the current step ID.
3. `role` field names the role that is suspended (the role being authorized — `security` or `privacy`).
4. `head_sha` field equals the register-header `HEAD_SHA` (the evaluated HEAD). A mismatch → the override is **not valid** (it was authored for a different commit) → treat as path (b) absent.
5. `authorized_by`, `date`, `reason` are present and non-empty.

If any field is absent/empty, or `head_sha` does not match the evaluated HEAD → the override does not satisfy path (b). The evaluator then falls through to the FAIL / grandfathering branch as if no override existed. The evaluator MUST state which validity condition failed in its output (e.g. "override present but head_sha `abc..` ≠ evaluated HEAD `def..` — not accepted").

---

## 3. `suspension_manager.py` — function contracts

Two new public functions plus one small helper. **Stdlib only** (the module's existing constraint). Both reuse the existing `_today()` and the `\d{4}-\d{2}-\d{2}` date idiom. No function in this module ever writes a SUSPENDED line or an override file (the RATCHET — these are read/validate-only).

### 3.1 `parse_per_step_scope(text: str) -> tuple[bool, list[str]]`

Parses the suspension-file text and returns `(per_step_scope, steps)`.
- `per_step_scope`: True iff a non-commented `per_step_scope:` line has a truthy value (`true`/`yes`/`1`/`on`, case-insensitive). Absent → False.
- `steps`: the parsed list of step IDs (empty when absent). Accept both block-list (`  - step-3`) and inline (`steps: [step-3, step-4]`) forms.
- HTML-commented lines are ignored (reuse the comment-tracking loop shape from `parse_suspensions()`; factor a shared `_iter_noncomment_lines(text)` helper if convenient — not required).

### 3.2 `validate_per_step_scope(text: str, step_id: str) -> dict`

The core authorization classifier for the per-step-scoped path (R2.2a / R1.6). Returns a dict the evaluator consumes:

```
{
  "per_step_scope": bool,        # parsed value
  "malformed": bool,             # True when per_step_scope is True but steps is empty/absent (R1.6)
  "covers_step": bool,           # True when per_step_scope is True, not malformed, and step_id ∈ steps
  "steps": [str, ...],           # parsed steps list (for diagnostics)
}
```

Contract:
- `per_step_scope == False` (blanket / absent) → `{per_step_scope: False, malformed: False, covers_step: False, steps: [...]}`. Blanket path; the evaluator handles it via grandfathering/FAIL.
- `per_step_scope == True` AND `steps` empty/absent → `malformed: True` (R1.6 — distinct FAIL precedence; the evaluator must emit the malformed message and NOT fall through to the blanket FAIL).
- `per_step_scope == True` AND `steps` non-empty → `covers_step = (step_id in steps)` using exact string equality (R2.4).

This function does **not** know the tier and does **not** check `security-suspension-acknowledged` — those remain the evaluator's responsibility (R2.3). It is a pure classifier of the scope fields against a step ID.

### 3.3 `check_grandfathered_until(text: str, today: str | None = None) -> dict`

Implements R3's date logic. `today` defaults to `_today()` (injectable for tests).

```
{
  "present": bool,        # a non-commented grandfathered_until: YYYY-MM-DD line exists
  "date": str | None,     # the parsed date string, or None
  "status": str,          # one of: "absent", "future", "expired", "malformed"
}
```

Contract (reuses the `review-by:` lexicographic comparison idiom — `date < today` means past):
- No `grandfathered_until:` line (or only commented) → `{present: False, date: None, status: "absent"}`. **No grandfathering** → evaluator applies R2 FAIL.
- Present, value matches `\d{4}-\d{2}-\d{2}`, `date > today` (strictly future) → `status: "future"`. WARN path (R3).
- Present, value matches, `date <= today` (today or past) → `status: "expired"`. FAIL path (R3.1) — name the date.
- Present but value does not match the date regex → `status: "malformed"`. Treat as **expired/FAIL** (fail-closed — a human set a deadline the parser can't read; the safe direction is to deny grandfathering). The evaluator names the malformed value.

> Boundary note: `date == today` is treated as **expired** (`<=`), matching the spec's "the date specified is in the future relative to today's date" — equality is not "in the future". This is the conservative (fail-applies) direction.

### 3.4 No CLI surface required

These functions are consumed by the evaluator agent via inline `python3 -c` invocation (the same pattern condition 11 / gate-compliance use), or by future callers. No new argparse flags are mandated by this spec. If the coder adds a thin `--validate-per-step` CLI for testability, that is acceptable but optional — the unit tests import the functions directly (matching `test_suspension_manager.py`'s `importlib` pattern).

---

## 4. Evaluator Phase 1 — new condition (the algorithm)

### 4.1 Placement and relationship to the existing HIGH-tier warning

The existing **"Warning — HIGH-tier security/privacy suspension"** block (evaluator lines ~105–113) handles the blanket-acknowledgment case generically. SPEC-83 **interposes a stricter check** for the security-relevant-surface sub-case. The design:

- Insert a new condition, **Condition 12 — HIGH-tier per-step suspension authorization (SPEC-83)**, immediately after Condition 11 (tier-floor) and before the current structural-modification check (which becomes Condition 15; the gate-results / second-review checks keep their positions but are referenced after this new block per the existing flow). Use the next free condition number in the file; the exact integer is the file's existing sequence — the binding is "between condition 11 and the next condition."
- The existing HIGH-tier warning block at lines 105–113 is **amended** so that when the new Condition 12 fires (HIGH tier + security/privacy suspended + security-relevant surface), the generic blanket-acknowledgment "record WAIVED, no warning" path does **not** silently apply — Condition 12 governs that sub-case. For HIGH-tier security/privacy suspensions on **non**-security-relevant surfaces, the existing block is unchanged (AC5).

### 4.2 Condition 12 — gating predicate (when it runs)

Condition 12 runs only when **all three** are true (R2.1):
1. Validated tier is **exactly HIGH** (not CRITICAL — CRITICAL is handled by R2.6 / the absolute prohibition, which wins).
2. `security` OR `privacy` appears as `SUSPENDED: {role}` in `contract/gate-suspension.md`.
3. The step touches a **security-relevant surface**.

**Security-relevant-surface determination (R2.1, fail-closed):**
Run the existing tier-floor classifier over the step's range and inspect its evidence:
```bash
python3 scripts/oversight/change_classifier.py --tier-floor --base "$BASE_SHA" --head "$HEAD_SHA"
```
The surface is **security-relevant** iff the `evidence` array contains at least one entry whose `rule` names a security-relevant floor pattern: `auth/session path`, `payment/financial path`, `migration file`, `privacy/PII path`, `PCI/financial API`, or `PII field` (these are exactly the `change_classifier.py` tier-floor rule labels that establish the HIGH/CRITICAL floor — the spec's R2.1 "same surfaces `change_classifier.py` uses").

**Fail-closed (architect binding 6 / R2.1):** if the classifier is **unavailable or errors** (non-zero exit, unparseable JSON, missing file), the evaluator treats the surface condition as **TRUE** and proceeds as though R2.1 is satisfied, and emits the note:
`"NOTE: change_classifier.py unavailable — security-relevant-surface condition assumed TRUE (fail-closed)."`

If the classifier runs cleanly and finds **no** security-relevant evidence → the surface is not relevant → Condition 12 does **not** fire → the existing blanket HIGH-tier warning behavior applies unchanged (AC5).

### 4.3 Condition 12 — CRITICAL precedence (R2.6)

Although the gating predicate requires tier == HIGH, the evaluator must **also** guard the CRITICAL case explicitly: if validated tier == CRITICAL AND (`security` or `privacy` suspended), and a `steps:` list or override names this CRITICAL step, the evaluator emits:
> `COMPLIANCE FAIL: CRITICAL-tier step {N}: per-step suspension authorization is not recognized. The absolute prohibition (contract §2a) applies — security/privacy may not be suspended on CRITICAL-tier steps regardless of authorization.`

This is already covered by the pre-existing "effective human gate overrides suspension" rule (lines 103); Condition 12 restates it so a `steps:` entry naming a CRITICAL step is never mistaken for authorization. No per-step authorization (scoping or override) can override the prohibition. This guard is evaluated **before** the malformed/scope branches below so it takes precedence.

### 4.4 Condition 12 — authorization decision tree (when it fires)

When the gating predicate (4.2) holds (tier == HIGH, role suspended, surface relevant), evaluate in this exact order:

**Step A — malformed-authorization check (R1.6, highest precedence after CRITICAL guard).**
Call `validate_per_step_scope(text, step_id)`. If `malformed == True`:
> `COMPLIANCE FAIL: Malformed authorization: per_step_scope: true requires a non-empty steps: list. No steps are covered by this suspension entry.`

Halt Condition 12 processing for the step (do not fall through to grandfathering or the blanket FAIL). Recommendation → ESCALATE.

**Step B — per-step-scoped suspension (path a, R2.2a + R2.3).**
If `per_step_scope == True` AND `covers_step == True`:
- Require `security-suspension-acknowledged: yes` in the same file (R2.3). If absent → COMPLIANCE FAIL: a per-step scope without the blanket acknowledgment is invalid:
  > `COMPLIANCE FAIL: HIGH-tier security-relevant step {N}: per-step-scoped suspension covers this step but security-suspension-acknowledged: yes is missing. Both are required.`
- If acknowledgment present → **record the role as WAIVED (per-step acknowledged), no warning.** Emit the `gate-suspended` audit event with the additional field `per_step_authorized: true` (R2.5). Condition 12 passes for this step.

**Step C — per-step human-tier-override (path b, R2.2b).**
Else (not covered by scoping), check `contract/tier-overrides/step{N}-human-tier-override.md` against the validity contract in §2.2 (exists, non-empty, `step` matches, `role` matches the suspended role, `head_sha == evaluated HEAD`, required fields present):
- If **valid** → **record the role as WAIVED (per-step human override), no warning.** Emit a new `human-tier-override` audit event (§5). Also emit the `gate-suspended` event with `per_step_authorized: true`. Condition 12 passes for this step.
- If present but **invalid** (e.g. head_sha mismatch) → state the failing validity condition and fall through to Step D (treated as override absent).

**Step D — grandfathering / FAIL (R2.2 neither path, R3).**
Neither scoping (B) nor a valid override (C) covers the step. Call `check_grandfathered_until(text)`:
- `status == "future"` → **COMPLIANCE WARN** (not FAIL), and force **CONDITIONAL_PROCEED** (R3.2/R3.3):
  > `COMPLIANCE WARN: HIGH-tier security-relevant step {N} is proceeding under a blanket suspension. Blanket suspensions for HIGH-tier security-relevant surfaces are deprecated; this step is grandfathered until {date}. Add per-step scoping (R1) or a per-step human-tier-override to remove this warning.`
- `status == "expired"` → **COMPLIANCE FAIL** (R3.1), name the date:
  > `COMPLIANCE FAIL: Grandfathering period expired ({date}): HIGH-tier security-relevant step {N} must now comply with per-step authorization requirements (R1, R2).`
- `status == "malformed"` → **COMPLIANCE FAIL** (fail-closed), name the unparseable value (same message as expired with the value).
- `status == "absent"` → **COMPLIANCE FAIL** (R2.2, AC4b):
  > `COMPLIANCE FAIL: HIGH-tier security-relevant step {N}: security/privacy is suspended via a blanket suspension (per_step_scope: false). A blanket suspension is insufficient for a HIGH-tier step touching security-relevant surfaces. Provide either (a) a per-step-scoped suspension covering step {N}, or (b) a per-step human-tier-override artifact at contract/tier-overrides/step{N}-human-tier-override.md.`

### 4.5 Decision-tree summary (precedence, top wins)

```
1. tier == CRITICAL + role suspended + (steps/override names step)  → FAIL (R2.6 absolute prohibition)
2. gating predicate false (tier≠HIGH, role not suspended, surface not relevant) → Condition 12 N/A (existing behavior)
   [classifier unavailable → surface assumed TRUE, predicate may hold]
3. malformed (per_step_scope:true + empty steps)                    → FAIL (R1.6)
4. per_step_scope covers step + acknowledged:yes                    → WAIVED (per-step), gate-suspended{per_step_authorized:true}
   per_step_scope covers step + acknowledged missing                → FAIL (R2.3)
5. valid override (step+role+head_sha match)                        → WAIVED (override), human-tier-override event
6. grandfathered_until future                                       → WARN + CONDITIONAL_PROCEED (R3)
7. grandfathered_until expired/malformed                            → FAIL (R3.1)
8. grandfathered_until absent                                       → FAIL (R2.2 / AC4b)
```

A Condition-12 hard FAIL flips the recommendation to ESCALATE per the existing end-of-Phase-1 rule. A Condition-12 WARN forces CONDITIONAL_PROCEED.

---

## 5. Audit events

### 5.1 `gate-suspended` — extended (R2.5)

When the suspension is accepted via per-step authorization (Step B or C), the existing `gate-suspended` event gains the field `per_step_authorized: true`:
```json
{"event":"gate-suspended","gate":"security","step":N,"authorized_by":"{name}","suspension_file":"contract/gate-suspension.md","reason_category":"...","per_step_authorized":true,"timestamp":"..."}
```
Blanket/grandfathered acceptances keep the existing shape (no `per_step_authorized` field, or `false`).

### 5.2 `human-tier-override` — new event (architect binding 8)

Emitted when an override artifact is accepted (Step C valid):
```json
{"event":"human-tier-override","step":N,"role":"security","artifact":"contract/tier-overrides/stepN-human-tier-override.md","authorized_by":"{name}","head_sha":"{evaluated HEAD}","timestamp":"..."}
```
Catalogued in `OVERSIGHT-CONTRACT.md §6a`. Emitted by oversight-evaluator. This records that a committed, commit-bound human override waived a HIGH-tier security/privacy review for a specific step.

---

## 6. Acceptance-criteria → component map

| AC | Verified by |
|---|---|
| AC1 (blanket + security surface, no grandfather → FAIL) | Condition 12 Step D, `status: absent` |
| AC2 (per-step scope + acknowledged → pass, `per_step_authorized:true`) | Condition 12 Step B + §5.1 |
| AC3 (override → pass) | Condition 12 Step C + §2.2 validity + §5.2 |
| AC4 (valid future grandfather → WARN + CONDITIONAL_PROCEED) | Condition 12 Step D `status: future` |
| AC4b (no grandfather → FAIL) | Condition 12 Step D `status: absent` |
| AC4c (expired grandfather → FAIL, names date) | Condition 12 Step D `status: expired` |
| AC5 (HIGH but non-security surface → unchanged) | Gating predicate 4.2 false → existing warning block |
| AC6 (LOW/MEDIUM unchanged) | Gating predicate requires tier == HIGH |
| AC7 (scope covers step N not M) | `validate_per_step_scope` exact-match `covers_step` |

---

## 7. Boundaries (what each component must honor / must not assume)

- **`suspension_manager.py` functions** must remain stdlib-only, must never write a SUSPENDED line or any override/suspension file, and must treat all I/O as read/parse-only. They do not know the tier and do not read `change_classifier.py` — they classify only the scope/date fields against an input step ID. They must ignore HTML-commented lines (template examples).
- **The evaluator** must never create, modify, or delete `contract/gate-suspension.md` or any file under `contract/tier-overrides/` (human-only — §484-488 prohibition extended to `tier-overrides/`). On a missing override it reports the FAIL state; it never authors the file to unblock.
- **The evaluator** must fail-closed when the classifier is unavailable (surface assumed relevant) — it must not silently no-op Condition 12 on a classifier error.
- **Override validity** is commit-bound: an override authored for a different HEAD is not honored. The evaluator must not accept an override whose `head_sha` ≠ evaluated HEAD even if all other fields match.
- **CRITICAL precedence** is absolute: no `steps:` entry and no override can authorize a CRITICAL-step suspension. This must be checked before the scope/override branches.
- This change is **additive** for all existing behavior: blanket suspensions at LOW/MEDIUM, HIGH-tier non-security-surface suspensions, and the auto-removal/census machinery are unchanged (NR1, NR4, NR5).

---

## 8. Test plan (for unit-test / system-test)

Unit tests (extend `tests/oversight/test_suspension_manager.py`, import via existing `importlib` pattern):
- `parse_per_step_scope`: absent → `(False, [])`; block-list and inline forms both parse; commented lines ignored; truthy variants of `per_step_scope`.
- `validate_per_step_scope`: blanket → not malformed, not covering; `per_step_scope:true` + empty steps → `malformed:True`; covers exact step; does NOT cover a different step (AC7); exact-string match (no prefix/substring).
- `check_grandfathered_until`: absent → `absent`; future date → `future`; past date → `expired`; today → `expired` (boundary); malformed value → `malformed`. Inject `today` for determinism.

The evaluator-side decision tree (Condition 12) is an agent-prose behavior; its acceptance is verified by the AC walkthrough in §6 and by system-test scenarios that stage a `gate-suspension.md` + classifier output and assert the evaluator's recommendation. The deterministic parsing/validation logic that the evaluator depends on lives in the two Python functions and is unit-tested.

---

## Human Review Required

**`scripts/oversight/suspension_manager.py` — `check_grandfathered_until` boundary (`date == today` → expired):** the design treats today's date as "not in the future" → FAIL. Confirm this matches the intended transition semantics (a grandfather period ending today is over today, not tomorrow).

**`.claude/agents/oversight-evaluator.md` Condition 12 fail-closed branch:** when `change_classifier.py` is unavailable the evaluator assumes the surface is security-relevant and demands per-step authorization. On a project with a frequently-unavailable classifier this converts HIGH-tier blanket suspensions into FAILs. This is the spec-mandated safe direction (R2.1), but a human should confirm the operational impact is acceptable for brownfield onboarding.

RISK: MEDIUM
CONFIDENCE: 85% — confident in the schema and decision-tree contract (directly traced to spec ACs + architect bindings); less certain about the exact pre-existing condition-number sequence in the evaluator file, which the coder resolves at edit time by inserting after condition 11.

Change classification: **additive** — new fields, new functions, a new evaluator condition; no existing required field renamed or removed, no existing behavior path altered for out-of-scope tiers/surfaces.
