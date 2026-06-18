# Technical Design — SPEC-219 Second-Review Reviewed-Range Verification

**Spec:** `docs/specs/SPEC-219-second-review-range-check.md`
**Issue:** #219
**Family:** #204 commit-range machinery (SPEC-220 sibling)
**Architect ruling:** GO (5 bindings, all incorporated below)
**Author:** technical-design
**Date:** 2026-06-17

---

## 1. Purpose

`run_second_review.sh` runs the mandatory cross-vendor independence check at MEDIUM+,
operating on a diff it derives at invocation time. The evaluator verifies the review
*happened* but not *which commits* it covered. SPEC-219 closes the scope-mismatch hole
by:

1. Having `run_second_review.sh` record a `reviewed_range:` field in every report header,
   captured at diff-derivation time (the exact range the reviewer saw).
2. Having `oversight-evaluator.md` Phase 1 compare that field against the register's
   `base_sha..head_sha` with exact full-SHA string equality, and disposition mismatch,
   absence, and dirty-worktree cases.

This is a **recording + checking** contract. It does not change what the review checks,
its prompts, vendor routing, thresholds, or verdict taxonomy.

---

## 2. Architect bindings (authoritative constraints)

These 5 bindings govern the design. Any implementation choice below that appears to
conflict with a binding is wrong; the binding wins.

- **B1 — Single step-range source.** The `--step N` path derives its range from the
  shared helper `scripts/oversight/lib/step_range.sh` (`get_step_range`). The
  merge-base fallback for a leading-empty base uses
  `BASE=$(git merge-base HEAD $(git rev-parse HEAD~1 2>/dev/null || echo HEAD))` —
  byte-identical to the SPEC-220 evaluator fallback so both resolve BASE identically.
- **B2 — `none` is the only absent-range sentinel.** Three conditions
  (no-diff-content early exit, helper returns empty for `--step`, empty/unusable range)
  all funnel to `reviewed_range: none`. The script never emits an empty
  `reviewed_range:` field.
- **B3 — SHAs captured at diff-derivation time, full 40-char, before vendor invocation.**
  Resolve and store BASE_SHA/HEAD_SHA at the point the diff is built; never re-run
  `git rev-parse` after the diff to re-derive them.
- **B4 — `UNCOMMITTED` and `none` are mutually exclusive.** The dirty-worktree path
  (Path 3) emits `UNCOMMITTED`; the no-content / empty-range paths emit `none`. A single
  report can carry at most one of these — never both.
- **B5 — Evaluator comparison is exact full-SHA string equality.** No abbreviated,
  prefix, or basename matching. `report_base == reg_base AND report_head == reg_head`,
  byte-exact, case-sensitive.

---

## 3. Component map

| Component | File | Change |
|---|---|---|
| Range capture (script) | `scripts/run_second_review.sh` | New `REVIEWED_RANGE` variable computed at the diff-derivation block; emitted in the main header and both early-exit sentinel heredocs |
| Step-range helper | `scripts/oversight/lib/step_range.sh` | **No change** — consumed as-is via `get_step_range` |
| Verdict aggregator | `scripts/oversight/second_review_logic.py` | **No change** — its `re.sub` rewrites only `verdict:`/`highest_severity:`/`unresolved_findings:` lines; the new `reviewed_range:` line is untouched and survives aggregation |
| Range verification (evaluator) | `.claude/agents/oversight-evaluator.md` | New range-check block appended to the "Second-review compliance (MEDIUM+ steps)" section |

The aggregator non-interaction is load-bearing and must be preserved: do **not** make the
`reviewed_range:` line match any of the three `re.sub` patterns (`^verdict: pending$`,
`^highest_severity: none$`, `^unresolved_findings: 0$`).

---

## 4. `run_second_review.sh` — contract

### 4.1 Range derivation (the diff-derivation block, current lines ~192-199)

A single `REVIEWED_RANGE` shell variable is the recorded value. It is computed at the
diff-derivation block — the same place the diff is built — so the recorded range is the
range the reviewer actually saw (B3). The `--step N` path is added to this block; today
it does not derive a range here.

**Resolution order (first match wins):**

1. **`--step N` provided** (`$STEP` is set to a step number used as a range source — see
   note below on the existing `--step` semantics):
   - Source `scripts/oversight/lib/step_range.sh`; call `get_step_range "$STEP"`.
   - If the helper returns **empty string** → `REVIEWED_RANGE="none"`; do **not** build a
     diff and do **not** invoke a reviewer for a range source — fall through to the
     no-content sentinel path (B2). (See §4.4.)
   - If the helper returns **`..HEAD_SHA`** (leading-empty base, normal for step 1) →
     apply the B1 merge-base fallback:
     `BASE=$(git merge-base HEAD $(git rev-parse HEAD~1 2>/dev/null || echo HEAD))`,
     then `REVIEWED_RANGE="${BASE}..${HEAD_SHA}"` where `HEAD_SHA` is the helper's head.
   - Otherwise (`BASE..HEAD`) → `REVIEWED_RANGE="${BASE}..${HEAD}"` from the helper output.
   - All SHAs from the helper are already full 40-char (it extracts full `head_sha`
     fields from the log). No re-derivation (B3).

2. **`--diff <ref>` single ref** (`$DIFF_REF` set, no `..`):
   - `BASE_SHA=$(git rev-parse "$DIFF_REF")`, `HEAD_SHA=$(git rev-parse HEAD)`.
   - These are **new** calls at diff-derivation time (the script currently discards them).
   - `REVIEWED_RANGE="${BASE_SHA}..${HEAD_SHA}"`.

3. **`--diff <A>..<B>` range form** (`$DIFF_REF` contains `..`):
   - Parse `A=${DIFF_REF%%..*}`, `B=${DIFF_REF##*..}`.
   - `BASE_SHA=$(git rev-parse "$A")`, `HEAD_SHA=$(git rev-parse "$B")`.
   - `REVIEWED_RANGE="${BASE_SHA}..${HEAD_SHA}"`.

4. **`--files ...` or no `--diff` (Path 3, HEAD-vs-worktree):**
   - The diff is `git diff HEAD` (worktree/index against HEAD).
   - If the worktree is **dirty** (uncommitted changes in tracked files exist for the
     reviewed set) → `REVIEWED_RANGE="UNCOMMITTED"` (B4). Detected with
     `git diff --quiet HEAD` (or `git diff --quiet HEAD -- "${FILES[@]}"` when files are
     scoped): a non-zero exit means uncommitted changes are present.
   - If the worktree is **clean** at HEAD (no uncommitted changes — the diff content, if
     any, came from a clean HEAD) the range is `HEAD..HEAD`; record
     `REVIEWED_RANGE="$(git rev-parse HEAD)..$(git rev-parse HEAD)"`. In practice a clean
     Path-3 invocation yields no diff content and exits at the no-content sentinel
     (`none`), so the dirty branch is the live case; the clean branch exists only so the
     field is never empty (B2).

**Note on `--diff` vs `--step` precedence.** The current script requires `--step` always
(it names the output file) and treats `--diff`/`--files` as the *diff source* when present.
The range-source precedence must mirror the diff-source precedence the script already uses:
when `--diff` or `--files` is supplied, that argument is the range source (paths 2/3/4
above) even though `--step N` is also present for output naming; the `get_step_range` path
(path 1) is used only when **no** `--diff`/`--files` argument narrows the diff, i.e. the
invocation is relying on the step's canonical range. Concretely: derive `REVIEWED_RANGE`
inside the **same `if/elif/else` that derives `DIFF_CONTENT`**, so range source and diff
source are always the same branch and can never disagree (B3, and structurally enforces
B4's mutual exclusion — only one branch runs).

### 4.2 Capture timing (B3)

`REVIEWED_RANGE` (and any BASE_SHA/HEAD_SHA it is built from) is fully resolved inside the
diff-derivation `if/elif/else` block, **before** any vendor (`agy`/`codex`) is invoked and
before the header is written. No `git rev-parse` for range purposes runs after this block.

### 4.3 Header emission

Add one line to the machine-readable header written at the top of `$OUTFILE`
(current lines ~232-239), adjacent to `verdict:`:

```
reviewed_range: ${REVIEWED_RANGE}
```

`REVIEWED_RANGE` is one of: `FULL_SHA..FULL_SHA`, `UNCOMMITTED`, or `none`. It is **never**
empty (B2) — `${REVIEWED_RANGE}` must always be set before the header write. Initialize
`REVIEWED_RANGE="none"` at the top of the script (default) so any unforeseen path still
emits a valid sentinel rather than an empty field.

### 4.4 Sentinel / early-exit paths — every report carries the field

The field appears in **every** report the script writes, including:

- **Skipped (below threshold)** heredoc (current lines ~139-147): the score-below-both
  sentinel is written **before** the diff-derivation block, so no range has been derived.
  Record `reviewed_range: none` (B2). This is the "score below threshold" skip; the
  evaluator dispositions it as the absent→WARN case (this report is only valid on a
  below-MEDIUM tier anyway).
- **No-diff-content** heredoc (current lines ~205-212): record `reviewed_range: none`
  (B2). This is also where the `--step` empty-helper case (path 1, empty) lands — set
  `REVIEWED_RANGE="none"` and route to this sentinel without invoking a reviewer.
- **Error** reports: the aggregator may set `verdict: error` after vendor runs. Because
  `reviewed_range:` is written into the header at OUTFILE-creation time (§4.3) and the
  aggregator never touches that line, an errored run still carries the range it attempted.

The skipped-below-threshold heredoc fires before the diff block, so it cannot reuse a
computed `REVIEWED_RANGE`; it hardcodes `reviewed_range: none` in its own heredoc body.

### 4.5 Invariants

- Exactly one `reviewed_range:` line per report.
- `UNCOMMITTED` and `none` never co-occur in one report (B4 — structurally guaranteed by
  the single-branch derivation in §4.1).
- SHAs are full 40-char hex (B3) — guaranteed because every SHA comes from `git rev-parse`
  (full) or `get_step_range` (full `head_sha` fields).

---

## 5. `oversight-evaluator.md` — Phase 1 range-check contract

Append a range-verification block to the existing "Second-review compliance (MEDIUM+
steps)" section. It runs **after** the verdict has been classified (the existing bullets)
and uses the `BASE_SHA`/`HEAD_SHA` already written to the register header earlier in
Phase 1.

### 5.1 Read inputs

- `reviewed_range` from the second-review report header (the present `step{N}-*.md` file).
- `base_sha` and `head_sha` from the register header (`.claudetmp/signoffs/step{N}-register.md`)
  — already established earlier in Phase 1.

Parse `reviewed_range`. If it is the literal `UNCOMMITTED` or `none`, handle per the
disposition table without splitting on `..`. Otherwise split on `..` into
`report_base` and `report_head`.

### 5.2 Disposition (mirrors SPEC-219 R3 table)

| `reviewed_range` value | Disposition |
|---|---|
| `UNCOMMITTED` | **COMPLIANCE FAIL** regardless of verdict — second review ran against uncommitted worktree state; reviewer saw changes not in any verifiable commit. Re-commit and re-run. |
| `none` | **COMPLIANCE WARN** — no usable range; cannot confirm coverage. Add a conditional item. Not a FAIL. |
| absent (no `reviewed_range:` line) | **COMPLIANCE WARN** — instrumentation gap; cannot confirm coverage. Add a conditional item. |
| empty string after the colon | **COMPLIANCE WARN** — treat identically to `none`. |
| present, `report_base..report_head` **matches** register (B5 exact equality) | **Pass silently** — no compliance note. |
| present, **mismatches** register | **COMPLIANCE FAIL** — the independent review covered a different commit set than this step's `base_sha..head_sha`. Re-run scoped to the correct range. |

**Verdict interaction (from R3 table):**
- The range check applies to `approve`, `request_changes`, `unparseable`, and
  score-below-threshold `skipped` reports.
- For `verdict: error` and `verdict: pending`, the range comparison is **skipped** (an
  errored/incomplete run produces no judgment to accept). For `error`, still emit a WARN
  if `reviewed_range` is absent (instrumentation note) — this does not change the existing
  `error`→FAIL outcome. For `pending`, emit the existing WARN.
- The `UNCOMMITTED` FAIL fires **regardless of verdict** (it is a structural fail, not a
  verdict-dependent one).

### 5.3 Comparison rule (B5)

Exact, full-SHA, case-sensitive string equality on both halves:
`report_base == reg_base AND report_head == reg_head`. Any prefix/abbreviated/partial
match counts as **mismatch → FAIL**. This matches the way `base_sha`/`head_sha` are
written (full `git rev-parse` output) and the way `reviewed_range` SHAs are produced
(full). For step 1, the register's `base_sha` was produced by the same B1 merge-base
fallback the script applies, so a correctly-scoped step-1 review matches exactly
(AC-11).

### 5.4 Effect on recommendation

- Any range **FAIL** (`UNCOMMITTED` or mismatch) → Phase 1 compliance fails →
  recommendation **ESCALATE** (consistent with all other Phase 1 hard fails).
- Any range **WARN** (`none`, absent, empty) → does not fail compliance; the WARN text is
  added to the conditional items so the human sees it; recommendation is at least
  CONDITIONAL_PROCEED if it would otherwise be PROCEED only because of this WARN — but the
  WARN alone is an instrumentation note and follows the existing conditional-items
  convention (not an automatic escalate).

---

## 6. Acceptance-criteria traceability

| AC | Covered by |
|---|---|
| AC-1 (`reviewed_range` always present) | §4.3, §4.4 (every report path) |
| AC-2 (`--diff A..B` resolves to rev-parse of A,B) | §4.1 path 3 |
| AC-3 (match → silent pass) | §5.2 match row |
| AC-4 (absent → WARN + conditional) | §5.2 absent row, §5.4 |
| AC-5 (mismatch → FAIL → ESCALATE) | §5.2 mismatch row, §5.4 |
| AC-6 (dirty Path 3 → `UNCOMMITTED` → FAIL any verdict) | §4.1 path 4, §5.2 UNCOMMITTED row |
| AC-7 (no-diff-content → `none` → WARN) | §4.4, §5.2 none row |
| AC-8 (`error` reports carry field; no range comparison) | §4.4 error, §5.2 verdict interaction |
| AC-9 (`pending` → WARN, range check skipped) | §5.2 verdict interaction |
| AC-10 (`--step` delegates to helper, no re-impl) | §4.1 path 1, B1 |
| AC-11 (step-1 merge-base fallback → match) | §4.1 path 1, §5.3 |
| AC-12 (helper empty → `none`, no reviewer) | §4.1 path 1 empty, §4.4 |

---

## 7. Out of scope (per spec §2, §4)

- `run_panel.sh` (post-PR; different range story).
- The risk-assessor scope check (separate, already in the evaluator).
- Retroactive re-validation of already-generated reports.
- Any change to review logic, prompts, vendor routing, thresholds, or verdict taxonomy.
- Abbreviated-SHA support (full SHAs only).
- git-object existence checks (range verification is string comparison only).

---

## 8. Risk / review classification

**RISK:** LOW — additive instrumentation field + a string-equality compliance check.
No change to review logic, vendor routing, or verdict taxonomy. The one interaction risk
(aggregator header rewrite clobbering the new field) is eliminated by design (§3): the
aggregator's `re.sub` patterns do not match `reviewed_range:`.

**CONFIDENCE:** HIGH — the spec is exhaustive (full disposition table), the helper
interface is fixed and reused unchanged (B1), and the capture point is structurally tied
to the existing diff-derivation branch so range source and diff source cannot diverge.

**BLAST RADIUS:** `scripts/run_second_review.sh` (range capture + header), and
`.claude/agents/oversight-evaluator.md` Phase 1 (one new check block). No schema change to
the register or audit log; `step_range.sh` and `second_review_logic.py` unchanged.

**Change classification:** `additive` — adds a recorded field and a new compliance check;
does not alter any existing contract for already-built behavior.
