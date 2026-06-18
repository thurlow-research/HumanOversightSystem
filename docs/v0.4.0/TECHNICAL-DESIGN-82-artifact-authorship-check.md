# Technical Design — SPEC-82: Governance-Artifact Authorship Check

**Spec:** `docs/specs/SPEC-82-governance-artifact-authorship-check.md`
**Issue:** #82
**ADR / Architect ruling:** GO (bindings recorded below)
**Author:** technical-design
**Date:** 2026-06-17
**Status:** For architect review

---

## 0. Architect bindings (authoritative constraints)

These bindings from the architect's GO ruling govern the design. Where the spec and a
binding could be read differently, **the binding wins**.

1. **Source bot emails from `BOT_WORKER_EMAIL` and `BOT_OVERSEER_EMAIL`** in
   `scripts/framework/machine-accounts.env`. Comparison is **case-insensitive** against
   the author email of the most-recent commit, resolved by
   `git log --follow --format="%ae" -- {path} | head -1`.
2. **Fail-open when both email fields are absent/empty** — skip the authorship check
   entirely for the run and emit a note. No compliance item.
3. **Severity is COMPLIANCE WARN, never FAIL** — both for a bot-committed artifact and
   for an untracked artifact. A WARN forces CONDITIONAL_PROCEED.
4. **Exactly four artifacts are checked:**
   - `.claudetmp/oversight/step{N}-human-authorization.md`
   - `contract/tier-overrides/step{N}-human-tier-override.md`
   - `contract/gate-suspension.md`
   - `.claudetmp/oversight/step{N}-human-tier-override.md` (legacy path — checked only
     if it still exists on disk)
5. **The authorship check runs AFTER the existing field-validation checks** (the
   Condition-12 area, after the per-artifact existence/field checks).
6. **Two new audit events:** `governance-artifact-bot-commit` and
   `governance-artifact-untracked`.

### 0.1 Reconciliation note (binding 4 vs spec R2.1) — for architect confirmation

The spec's R2.1 table lists `.claudetmp/oversight/human-tier-override.md` (no step
prefix — the current canonical override path used by Condition 11) as one of the four
artifacts. The architect's binding-4 list **replaces** that entry with the
step-prefixed **legacy** path `.claudetmp/oversight/step{N}-human-tier-override.md`.

This design implements the **architect's** four-artifact list verbatim (bindings win).
Consequence: the canonical non-step override file `.claudetmp/oversight/human-tier-override.md`
is **not** authorship-checked by this spec. This is a deliberate scope choice recorded
here so it is auditable. If the architect intended the canonical override path to also
be covered, that is a one-line addition to the artifact list (§3.1) and should be
raised before merge. **RISK:** a bot-authored canonical `human-tier-override.md` would
not be flagged by this check — but Condition 11 already only *reads* that file and an
agent is already prohibited from creating it; the authorship check is a supplementary
tamper-evidence layer, not the primary guard. CONFIDENCE: 80%.

---

## 1. Problem restated (contract terms)

Four governance artifacts are **human-only**: an agent may read them but must never
create or modify them. The evaluator's Phase 1 already checks their *existence* and
*required fields* (contract §7 conditions 7, 11, 12). It does **not** check *who*
authored the most recent commit touching them. Under the shared-identity worker setup,
named bot accounts (`hos_worker@…`, `hos_oversight@…`) have known commit emails. A
commit by one of those accounts touching a human-only artifact is a credible tampering
signal, surfaced as **COMPLIANCE WARN → CONDITIONAL_PROCEED** (accountability +
tamper-evidence, not cryptographic forge-proofing).

This is a **detection** feature only. It changes no access controls and does not alter
what agents may create (NR4).

---

## 2. Data / config contract

### 2.1 New `machine-accounts.env` fields (additive)

Two fields are read by the evaluator. They carry the **commit author email addresses**
(`git log %ae` form) of the two bot accounts — distinct from the existing
`BOT_*_USERNAME` (GitHub handles) and `BOT_ACCOUNTS` (handle set used by
`require_human_approval.py`).

| Field | Type | Meaning | Absent/empty behavior |
|---|---|---|---|
| `BOT_WORKER_EMAIL` | string (single email) | commit author email of the worker bot | contributes nothing to the known-bot set |
| `BOT_OVERSEER_EMAIL` | string (single email) | commit author email of the overseer bot | contributes nothing to the known-bot set |

**Invariant (R1.2/R1.3):** the known-bot email set = the non-empty subset of
`{BOT_WORKER_EMAIL, BOT_OVERSEER_EMAIL}`. If that set is **empty** (both unset/empty),
the entire authorship check is **skipped** for the run (fail-open, binding 2).

**Boundary:** the evaluator must NOT fall back to `BOT_ACCOUNTS` usernames for the
email comparison — `git log %ae` yields emails, not handles (R1.4). Usernames are not a
valid substitute and using them would produce a never-matching comparison (silent
no-op), which is worse than the explicit skip.

These fields are documented in `machine-accounts.env`; the file ships with them
**commented/illustrative** so an unconfigured project hits the fail-open path by
default. (Documentation-only edit to that file is in scope per spec §6; the architect's
required edit set for *this* implementation is the evaluator + contract, so the env-file
prose update is a same-PR additive note, not a behavioral change.)

### 2.2 Two new audit events (contract §6a)

| Event | Emitted when | Required fields |
|---|---|---|
| `governance-artifact-bot-commit` | most-recent commit author email ∈ known-bot set | `step` (int), `artifact` (path), `bot_email`, `bot_name`, `commit_sha` (abbrev), `timestamp` (ISO-8601) |
| `governance-artifact-untracked` | artifact exists on disk but `git log --follow` returns no output | `step` (int), `artifact` (path), `timestamp` (ISO-8601) |

**Invariant (R4.3):** both events are appended to `audit/oversight-log.jsonl`
regardless of the final recommendation. They are research records of the mechanism
firing, separate from the compliance outcome. **One event per affected artifact** — no
merging (R3.4).

---

## 3. Algorithm — the per-artifact authorship check

### 3.0 Placement (binding 5 / R2.6)

The check is a **new Phase 1 block** inserted **after Condition 12** (the last
per-artifact field-validation block) and **before** the "If any hard compliance check
fails: recommendation is ESCALATE" terminal rule. Rationale: it is a *supplementary*
check on artifacts that already exist and already passed field validation. It must not
run on an artifact whose absence is already a COMPLIANCE FAIL, nor on an artifact that
already failed field validation (AC6, AC7) — those artifacts are handled by the prior
conditions and the authorship question is moot.

### 3.1 Resolve the known-bot email set (once per run)

```
Source scripts/framework/machine-accounts.env (if present).
KNOWN_BOT_EMAILS := { lowercase(e) for e in [BOT_WORKER_EMAIL, BOT_OVERSEER_EMAIL] if e non-empty }
If KNOWN_BOT_EMAILS is empty:
    Emit note: "Authorship check skipped — no bot commit emails configured in
    machine-accounts.env (BOT_WORKER_EMAIL and BOT_OVERSEER_EMAIL are unset)."
    SKIP the entire §3.2 loop. No compliance item. (binding 2, R1.3, AC1)
```

If `machine-accounts.env` is absent entirely, treat it as both fields empty → skip
(same fail-open path).

### 3.2 Per-artifact loop

The artifact set (binding 4), with `{N}` = current step:

```
ARTIFACTS := [
  ".claudetmp/oversight/step{N}-human-authorization.md",
  "contract/tier-overrides/step{N}-human-tier-override.md",
  "contract/gate-suspension.md",
  ".claudetmp/oversight/step{N}-human-tier-override.md",   # legacy
]
```

For each `path` in `ARTIFACTS`:

```
1. If NOT exists-on-disk(path):                                  # AC6
       continue   # nothing to check; absence handled by prior conditions

2. If path already produced a field-validation COMPLIANCE FAIL   # AC7
   in a prior condition (7/11/12):
       continue   # the FAIL stands as the primary finding; authorship is moot

3. line := `git log --follow --format="%ae %an %h" -- {path} 2>/dev/null | head -1`

4. If line is empty (no git history → untracked / never committed):   # R2.3, AC4
       Emit COMPLIANCE WARN (untracked message, see §3.3).
       Append governance-artifact-untracked audit event.
       Add conditional item (§3.4).
       continue

5. Parse line → (email, name, short_sha).
   If lowercase(email) ∈ KNOWN_BOT_EMAILS:                           # R2.4, AC3
       Emit COMPLIANCE WARN (bot-commit message, see §3.3).
       Append governance-artifact-bot-commit audit event.
       Add conditional item (§3.4).
   Else:                                                              # R2.5, AC2
       Record pass: "Governance artifact `{path}` — authorship check passed
       (last commit: `{email}`, not a known bot account)." No compliance item.
```

**Boundaries the loop must honor:**
- Most-recent commit only (NR6) — `head -1` of default `git log` order.
- Author **email** only — never commit message, trailer, or intermediate commits
  (NR5, NR6).
- Case-insensitive email comparison (binding 1).
- `--follow` so a renamed artifact still resolves its history.
- Step-2 "already failed field validation" is determined from the evaluator's own
  in-run record of prior-condition failures for that path; the check does not
  re-run field validation.

### 3.3 WARN message templates

**Untracked (R2.3):**
> Governance artifact `{path}` exists but has no git commit history. It may have been
> created without being committed (untracked working-tree file) or may have been added
> to the index but not yet committed. Human-only artifacts must be committed to be
> auditable.

**Bot-commit (R2.4):**
> Governance artifact `{path}` — most recent commit authored by known bot account
> `{bot_email}` (`{name}`). Human-only artifacts must be committed by a human. Flagging
> for human verification. Commit: `{short_sha}`.

### 3.4 Conditional-item generation (R3)

Every authorship WARN forces the recommendation to **at minimum CONDITIONAL_PROCEED**
(R3.1/R3.2) and emits **one conditional item per artifact** (R3.4 — no merging).

- **Default conditional item (R3.2):** names the artifact path and the suspicious commit
  author, and asks the human to confirm the artifact was not created by an AI agent.
- **Special case — human-authorization file (R3.3, AC5):** when the warned artifact is
  `.claudetmp/oversight/step{N}-human-authorization.md`, the item text MUST additionally
  state that the human-gate requirement for the step may not have been satisfied by a
  human, naming the step number and the artifact path:
  > The CRITICAL step authorization artifact may have been authored by a bot account.
  > The human-gate requirement for step {N} may not have been satisfied. Please confirm
  > you created this file.

### 3.5 Recommendation interaction

- The authorship block can only **raise** the recommendation floor to
  CONDITIONAL_PROCEED (it never produces FAIL/ESCALATE on its own — binding 3).
- If Phase 1 already reached ESCALATE from a hard-FAIL condition, the authorship WARNs
  are still recorded (and their audit events still emitted, R4.3), but ESCALATE stands
  — a WARN cannot lower an ESCALATE.
- An untracked-or-bot artifact that *also* triggered a prior FAIL never reaches the
  authorship block (step-2 `continue`), so there is no double-counting.

---

## 4. Audit-event emission contract

### 4.1 `governance-artifact-bot-commit` (R4.1)

```json
{"event":"governance-artifact-bot-commit","step":N,"artifact":"{path}","bot_email":"{email}","bot_name":"{name}","commit_sha":"{short_sha}","timestamp":"{ISO-8601}"}
```

### 4.2 `governance-artifact-untracked` (R4.2)

```json
{"event":"governance-artifact-untracked","step":N,"artifact":"{path}","timestamp":"{ISO-8601}"}
```

Both appended to `audit/oversight-log.jsonl`, one line each, one per affected artifact,
regardless of final recommendation (R4.3).

---

## 5. Acceptance-criteria → design trace

| AC | Covered by |
|---|---|
| AC1 — no bot emails → skip + note | §3.1 empty-set skip |
| AC2 — human-authored artifact passes | §3.2 step 5 else-branch |
| AC3 — bot artifact → one WARN + CONDITIONAL_PROCEED + audit event | §3.2 step 5, §3.4, §4.1 |
| AC4 — untracked artifact → WARN + untracked event (no bot event) | §3.2 step 4, §4.2 |
| AC5 — bot-authored human-authorization → named conditional item | §3.4 special case |
| AC6 — non-existent artifact → no check | §3.2 step 1 |
| AC7 — field-validation FAIL → no authorship check | §3.2 step 2, §3.0 placement |
| AC8 — multiple bot artifacts → separate WARNs + items | §3.2 loop + §3.4 (no merge) |

---

## 6. Boundaries / non-goals (from spec NR1–NR7)

- No cryptographic signing / out-of-band identity proof (NR1).
- Severity fixed at WARN; no FAIL upgrade (NR2, binding 3).
- No retroactive scan of merged history — current-run artifacts only (NR3).
- No change to what agents may create — detection only (NR4).
- Author email only; no commit-message / trailer inspection (NR5).
- Most-recent commit only; amend/commit-on-top by a human passes (NR6).
- Squash-merge false-positive is **intentional fail-safe** behavior — the bot squash
  author trips the WARN, human confirmation resolves it (NR7). The design does NOT
  special-case squash; suppressing it is out of scope.

---

## 7. Edit set (what the coder changes)

| File | Region | Change |
|---|---|---|
| `.claude/agents/oversight-evaluator.md` | Phase 1, after Condition 12 | New "Governance-artifact authorship check (SPEC-82)" block implementing §3; one-line note added to the "Human authorization file integrity" section that a partial mechanical guard now exists |
| `contract/OVERSIGHT-CONTRACT.md` | §6a catalog | Add `governance-artifact-bot-commit` and `governance-artifact-untracked` rows |
| `scripts/framework/machine-accounts.env` | bot-accounts block | Document `BOT_WORKER_EMAIL` / `BOT_OVERSEER_EMAIL` (additive prose) |

No existing field is renamed or removed. The change is **additive** at every site.

---

## 8. HOS self-flag

**Change classification:** `additive` — a new supplementary Phase 1 check + two new
audit-event types; no existing contract field, condition, or severity is altered. It can
only raise a recommendation from PROCEED to CONDITIONAL_PROCEED, never lower an existing
gate.

**RISK:** LOW-MEDIUM. The check is read-only over git history, fail-open by default, and
WARN-only by binding. The one residual judgment call is the binding-4-vs-R2.1 artifact
reconciliation (§0.1), flagged for architect confirmation.

**CONFIDENCE:** 85%.

## Human Review Required

1. Confirm the binding-4 artifact list is intended to **replace** (not augment) the
   spec's R2.1 list — specifically that the canonical
   `.claudetmp/oversight/human-tier-override.md` (no step prefix) is intentionally
   **out** of the authorship-check set and only the legacy step-prefixed path is in
   (§0.1).

---

*Status: For architect review — author: technical-design | 2026-06-17*
