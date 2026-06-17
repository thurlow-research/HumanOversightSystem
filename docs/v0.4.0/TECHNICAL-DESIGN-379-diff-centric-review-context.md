# Technical Design — SPEC-379 Diff-Centric Review Context

**Issue:** #379
**Spec:** `docs/specs/SPEC-379-diff-centric-review-context.md`
**Architect ruling:** GO (bindings recorded below)
**Author:** technical-design agent
**Date:** 2026-06-17
**Change class:** additive (makes an implied quality obligation explicit and enforceable)

---

## 0. Self-flag

`RISK: low` — additive prompt-layer constraint plus two new opt-out flags whose
default reproduces the evidence-based safe behavior. No change to verdict logic,
exit codes, sign-off schema, or independence handling.

`CONFIDENCE: high` — the diff is the existing primary input for both scripts
already (both build `DIFF_CONTENT` from `git diff`); this design adds a default-on
flag, an advisory signal, and a verbatim prompt block. No new control flow on the
hot path.

This is a MEDIUM-or-below change to authored artifacts (agent CORE regions + two
scripts). No `## Human Review Required` block is required at this tier. No
`structural` change: the region boundaries, exit-code contract, and verdict
schema are all unchanged.

---

## 1. Scope and binding constraints

This design implements the architect bindings verbatim. Where the spec left an
open question (OQ-379-1 default-on vs opt-in; OQ-379-2 detection mechanism), the
architect's ruling governs:

1. `--diff-only` **default ON** in both `run_second_review.sh` and `run_panel.sh`.
2. Diff derivation: `git diff origin/main..HEAD`, the **same** approach as SPEC-360,
   with the SPEC-360 fallback chain — origin/main → last tag → `HEAD~1`. No second
   diff-derivation path is invented.
3. The diff-centric instruction block lives in the **CORE** region of all 8 reviewer
   files, under the Inputs/preamble heading, carrying a carve-out note.
4. The instruction block text is **verbatim** (see §3) across all 8 files.
5. The advisory pattern list (R4) lives in **one named, commented location per script**.
6. `--no-diff-only` disables (startup warning citing Kumar 2026); `--diff-only`
   explicitly opts in (same behavior as default).
7. `bash -n` clean; usage/help documents the flag.
8. The 8 reviewer files: `code-reviewer`, `security-reviewer`, `privacy-reviewer`,
   `reliability-reviewer`, `ops-reviewer`, `ui-reviewer`, `a11y-reviewer`,
   `infra-reviewer` (all `.claude/agents/`).
9. **Do not change** `spec-red-team`, `risk-assessor`, validators, `prompt-fidelity`.

---

## 2. Component map

| # | Component | Contract |
|---|---|---|
| 1 | 8 reviewer CORE regions | Add the verbatim diff-centric block under the Inputs/preamble heading, with carve-out clause. |
| 2 | `run_second_review.sh` | `--diff-only` (default on) + `--no-diff-only` (warn) + advisory on context-request detection. |
| 3 | `run_panel.sh` | `--diff-only` (default on) + `--no-diff-only` (warn) + advisory on context-request detection. |

---

## 3. Reviewer CORE block — exact contract

Each of the 8 reviewer files MUST contain, immediately after the preamble heading
that introduces inputs (`## Inputs`, `## When you run`, or `## Before you review`,
whichever that file uses), the following block **verbatim and identical** across all
8 files:

```
> **REVIEW INPUT (DIFF-CENTRIC — DO NOT CIRCUMVENT):**
> Your primary input is the git diff provided. Do not request full-repository context.
> If you need a specific type definition or import, name it explicitly — do not ask for
> all files in a directory or the full file tree. Providing unrequested broad context
> bloats LLM context and empirically worsens detection rates (SWE-PRBench; Kumar 2026).
> PROJECT may NEVER override, weaken, or remove this constraint.
```

**Placement boundary:** the block is inserted between the preamble heading's
introductory sentence(s) and the next `##` heading. It is additive — it replaces no
existing instruction. The carve-out final line uses language consistent with the
existing CORE-footer carve-out ("PROJECT may NEVER override, weaken, or remove …").

**Boundary — what must NOT receive the block:** `spec-red-team.md`,
`risk-assessor.md`, and `prompt-fidelity.md` (AC-379-10 preserves the
spec-red-team non-requirement; adversarial spec review intentionally uses broad
context).

---

## 4. `run_second_review.sh` — contract

### 4.1 Flag surface

- New variable `DIFF_ONLY=1` (default on) declared with the other arg defaults.
- Arg parser accepts:
  - `--diff-only` → `DIFF_ONLY=1` (explicit opt-in; same as default).
  - `--no-diff-only` → `DIFF_ONLY=0`, and emit to **stderr** a startup warning:
    `[WARN] --diff-only disabled: full-file context enabled. Evidence (Kumar 2026 / SWE-PRBench) shows this can reduce reviewer detection rates.`
- Usage/help comment block (lines documenting `Usage:`) gains a `--diff-only` /
  `--no-diff-only` line documenting the default-on behavior.

### 4.2 Diff derivation (unchanged hot path, default behavior preserved)

The existing derivation (`--diff REF`, `--files`, else `git diff HEAD`) is retained.
`--diff-only` does **not** alter which diff is computed — both scripts already pass
only the diff (never the full file tree) to agy/codex. The flag's purpose is (a) the
explicit, documented default-on contract, (b) the advisory detection in §4.3, and
(c) the opt-out warning. When `DIFF_ONLY=0`, behavior is exactly as today (the script
has no full-file-tree path to add; the warning is the observable change), satisfying
R2's "behaves as it does today" requirement.

> Note: the SPEC-360 `origin/main..HEAD` fallback chain is the canonical
> whole-PR diff derivation. `run_second_review.sh` is invoked per-step with an
> explicit `--diff`/`--files`/`HEAD` selector, so it keeps its existing selector;
> it does not re-derive the PR-wide diff. The architect binding's diff-derivation
> clause is satisfied at the PR boundary by `run_panel.sh` (§5), which is the
> whole-PR consumer. `run_second_review.sh` introduces no second derivation path.

### 4.3 Advisory detection (R4)

- One named, commented constant lists the case-insensitive request patterns:
  `full repo`, `all files`, `entire codebase`, `repository context`,
  `all source files`, `project files`.
- After each reviewer response is captured (agy `AGY_OUT`/fallback; codex
  `CODEX_OUT`), when `DIFF_ONLY=1`, scan the response text for any pattern
  (case-insensitive). On a match, append an `[ADVISORY]` block to the run's
  `$OUTFILE` (already in `.claudetmp/second-review/`, the directory the
  oversight-evaluator reads). The advisory records reviewer, matched pattern, and
  the non-fulfillment action.
- The advisory MUST NOT change the exit code and MUST NOT alter the `verdict:` /
  `highest_severity:` / `unresolved_findings:` header fields. It is informational.

### 4.4 Exit-code invariant

No new non-zero exit path. The existing fail-closed paths (verdict=error,
vendor-unavailable) are untouched. AC-379-8 holds by construction: the advisory is a
file append only.

---

## 5. `run_panel.sh` — contract

### 5.1 Flag surface

- New variable `DIFF_ONLY=1` (default on) with the other arg defaults (`PR`,
  `DRY_RUN`, `RISK_OVERRIDE`, `DO_SAMPLE`).
- Arg parser `case` gains:
  - `--diff-only` → `DIFF_ONLY=1`.
  - `--no-diff-only` → `DIFF_ONLY=0` + stderr warning (same text as §4.1, via `warn`).
- Help text: `run_panel.sh`'s `--help` prints lines `2,43p` of its own header
  comment. Add a `--diff-only` / `--no-diff-only` usage line inside that header
  comment range so `--help` documents it (AC-379-4).

### 5.2 Diff handling

`run_panel.sh` already fetches **only** the PR diff (`gh pr diff "$PR" > "$DIFF_FILE"`)
and sends only diff chunks to reviewers via `build_review_prompt`. It never sends the
full file tree. `--diff-only` default-on is therefore the documented contract over
existing behavior (AC-379-5). `--no-diff-only` emits the warning; it does not widen
context (the script has no full-tree path), preserving R3's "same startup warning"
requirement without a behavioral regression.

> SPEC-360 note: auto-detect of the diff ref was added to `run_review_chain.sh`,
> NOT to `run_panel.sh`. This design adds only `--diff-only`/`--no-diff-only` to
> `run_panel.sh` and does not touch its `gh pr diff` derivation, so there is no
> conflict with SPEC-360.

### 5.3 Advisory detection (R4)

- One named, commented constant (same pattern list as §4.3) near the top tunables.
- After the reviewer fan-out captures each reviewer's `raw` response (the loop that
  writes `$RUN_DIR/${tool}-${lens}-chunk${ci}.raw.txt`), when `DIFF_ONLY=1` scan
  `raw` for any pattern. On a match, append an `[ADVISORY]` entry to a panel advisory
  file in the run output directory the evaluator reads — `.claudetmp/panel/` per the
  binding. Create `.claudetmp/panel/` if absent and write
  `.claudetmp/panel/advisory-pr${PR}-<timestamp>.md` (or append to a per-run file).
- Advisory MUST NOT change exit code, the arbiter verdict, posted threads, or the
  summary verdict. Informational only (AC-379-8).

### 5.4 Exit-code invariant

No new non-zero path. `--no-diff-only` warns and proceeds. Advisory is file-append
only.

---

## 6. Advisory entry format (both scripts)

```
[ADVISORY] Reviewer requested full-file/full-repository context while --diff-only is on.
Reviewer: <vendor>
Matched pattern: <pattern>
Action: Full-context request not fulfilled. If a specific artifact is needed,
re-invoke with the named file passed as targeted context.
```

Severity is ADVISORY (non-blocking). Surfaces context-bloat as a future
review-quality signal for the oversight-evaluator's Phase 2; it is not a gate.

---

## 7. Acceptance-criteria traceability

| AC | Satisfied by |
|---|---|
| AC-379-1 | §3 — verbatim block in all 8 CORE regions |
| AC-379-2 | §4.1 — `run_second_review.sh` usage documents `--diff-only` |
| AC-379-3 | §4.2 — default passes only diff (existing behavior, now contractual) |
| AC-379-4 | §5.1 — `run_panel.sh` `--help` documents `--diff-only` |
| AC-379-5 | §5.2 — default passes only diff to cross-vendor reviewers |
| AC-379-6 | §4.1 / §5.1 — `--no-diff-only` → stderr startup warning |
| AC-379-7 | §4.3 / §5.3 — ADVISORY entry in the run output directory |
| AC-379-8 | §4.4 / §5.4 — advisory is file-append; no exit-code / verdict change |
| AC-379-9 | `bash -n` clean (verified post-implementation) |
| AC-379-10 | §3 boundary — spec-red-team excluded |

---

## 8. Boundaries (what this design must NOT do)

- MUST NOT modify `spec-red-team`, `risk-assessor`, validators, `prompt-fidelity`.
- MUST NOT change the sign-off register format, independence handling, or the
  `verdict:`/`highest_severity:`/`unresolved_findings:` machine-readable header.
- MUST NOT introduce a hard token/line truncation — the constraint is behavioral
  (diff-first + explicit artifact naming), per spec §5.
- MUST NOT introduce a second diff-derivation path (binding 2).
- The advisory MUST NOT block the pipeline or change any exit code.
```
