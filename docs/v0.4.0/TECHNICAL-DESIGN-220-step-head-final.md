# Technical Design — SPEC-220: `step-head-final` event + shared `step_range.sh` helper

**Issue:** #220
**Spec:** `docs/specs/SPEC-220-step-head-final-event.md`
**Architect ruling:** GO (5 bindings BC-220-1..5 + cross-spec binding to SPEC-219)
**Status:** For implementation
**Date:** 2026-06-17
**Author:** technical-design

---

## 1. Overview

`step-head` (written by the evaluator at Phase 7) records HEAD *before* the panel
phase. Panel-fix commits land after it, so they fall outside the next step's
`base_sha..head_sha` window. This design adds a second, authoritative event —
`step-head-final`, written by the **orchestrator** after the PR merges (or after a
Phase-10 ESCALATE/no-PR close) — and updates the evaluator's `BASE_SHA` derivation
to prefer it. The shared range logic is extracted into a sourced bash helper
(`scripts/oversight/lib/step_range.sh`) consumed by both the evaluator and SPEC-219.

This is a contract + agent-prompt + helper-script change. It produces **no
application code**; the agent prompts are the contract for the orchestrator/evaluator
behavior, and the helper is a deterministic bash function.

---

## 2. Components and contracts

### 2.1 `scripts/oversight/lib/step_range.sh` (new — shared helper)

**Contract — the file is a sourced library, not an executable entry point.** It MUST
NOT run anything at source time (no top-level side effects, no `set -e` leakage that
would change the caller's shell options). It exports exactly one function.

```
get_step_range <step_n> [log_path]
```

- **Inputs:**
  - `step_n` — integer step number whose committed range is wanted.
  - `log_path` — optional path to the audit log; defaults to
    `audit/oversight-log.jsonl` relative to the caller's CWD. (Parameterized so
    tests can point at a fixture without a real repo.)
- **Output:** prints a single line `BASE_SHA..HEAD_SHA` to stdout, where:
  - `HEAD_SHA` = the `head_sha` of the **preferred** event for step `step_n`:
    `step-head-final` if one exists for that step, else `step-head`.
  - `BASE_SHA` = the preferred `head_sha` for step `step_n - 1` (same
    final-over-plain preference). When `step_n - 1` has no event (e.g. step 1),
    `BASE_SHA` is the empty string and the output is `..HEAD_SHA`. The caller owns
    the merge-base fallback for the empty-base case (the helper does not invent a
    base — it only reads the log; see §2.3 boundary note).
  - When step `step_n` itself has **no** event at all → print the **empty string**
    (not an error, exit 0). BC-220-5 mandates empty-string-not-error.
- **Lookup rule (the reusable primitive):** an internal helper resolves the preferred
  `head_sha` for a single step N:
  1. `grep` `step-head-final` events scoped to step N (portable pattern, BC-220-3);
     take the **last** match (`tail -1`); extract `head_sha`.
  2. If empty, `grep` `step-head` events scoped to step N; take last; extract.
  3. If still empty, print nothing.
- **Portable grep (BC-220-3):** step scoping uses `grep -E '"step":'"$N"'[,}]'`.
  The `[,}]` field-delimiter after the step number is BSD/macOS-safe and avoids
  prefix collisions (step 1 must not match step 12). **No `\b`.** Note the audit log
  also carries non-integer step values (`"step":"A"`); the `[,}]` delimiter still
  matches correctly for integer N and a string step never equals an integer N pattern.
- **SHA extraction:** `sed -n 's/.*"head_sha":"\([0-9a-f]*\)".*/\1/p'` on the matched
  line. Compact JSONL (BC-220-4) guarantees `"head_sha":"<sha>"` with no internal
  spaces, so this regex is stable.
- **Boundaries the helper MUST honor:**
  - It reads the log only. It does not call `git`, does not resolve refs, does not
    write anything.
  - Missing log file → treated as "no events" → empty output, exit 0 (a fresh repo
    must not error).
  - It must be idempotent and safe to source multiple times (guard against
    re-definition is optional but the function definition must be deterministic).

### 2.2 `oversight-evaluator.md` — Phase 1 BASE_SHA derivation (R2)

**Contract change:** the BASE_SHA block (currently lines ~44–51) is replaced to:
- Source `scripts/oversight/lib/step_range.sh`.
- Derive `PREV_HEAD` = preferred `head_sha` for step `N-1` via the helper's internal
  lookup (final-over-plain), **step-scoped** (fixes the existing
  unfiltered-`tail -1` correctness bug called out in R2 / AC-6).
- `BASE_SHA = PREV_HEAD` if non-empty, else the merge-base fallback (step 1 / older
  steps with no event — AC-5 backward compatibility).
- `HEAD_SHA = git rev-parse HEAD` (unchanged — the evaluator still records its own
  Phase-7 HEAD in the register header and the `step-head` event).
- The evaluator still writes the `step-head` event (unchanged). It does **not** write
  `step-head-final` — that is the orchestrator's job (out of scope to move it).
- Fallback when the helper file is absent (older install / dogfood drift): the
  evaluator falls back to an inline portable grep with the same final-over-plain,
  step-scoped logic. This keeps the evaluator self-contained and never fails closed on
  a missing helper.

**Boundary:** the evaluator must use the **same step number `N`** it is evaluating;
the previous-step lookup is `N-1`. For non-integer step ids (`"A"`), the helper's
integer grep yields nothing and the merge-base fallback applies — acceptable, matches
current behavior for lettered steps.

### 2.3 `oversight-orchestrator.md` — write `step-head-final` (R1)

Two write sites. Both append a **compact single-line** event (BC-220-4) to
`audit/oversight-log.jsonl`. Both are permitted by the orchestrator's own clean-tree
guard, which already excludes `audit/`.

**Site A — after a successful PR merge (PROCEED / CONDITIONAL_PROCEED merge path).**
Per BC-220-1, the orchestrator must FETCH before reading the final SHA — the local
working copy is not guaranteed to contain the merge/squash commit GitHub created:

```bash
gh pr merge ...            # (existing merge action / confirmation)
git fetch origin           # BC-220-1: pull the merge result locally
# Resolve the post-merge HEAD on the branch that received the merge.
# merge-commit mode: the merge commit; squash mode: the squash commit.
FINAL_SHA=$(git rev-parse origin/"$BRANCH")   # or fast-forward local + git rev-parse HEAD
```

Then append, with `merged: true`:

```
{"event":"step-head-final","step":N,"head_sha":"<FINAL_SHA>","merged":true,"panel_fix_commits":K,"timestamp":"<ISO-8601Z>"}
```

- `head_sha`: full 40-char SHA from the fetched post-merge ref (BC-220-1).
- `merged`: `true` on this path.
- `panel_fix_commits` (K): advisory count = `git rev-list --count <step-head.head_sha>..<FINAL_SHA>`
  for the step's Phase-7 `step-head.head_sha`. Advisory; omit if not cheaply
  computable (spec §3 R1, non-requirement §4). Under squash mode this count reflects
  the pre-squash branch history if computed before squash; treat as best-effort.
- **Squash-merge note (BC-220-1 / AC-2 / AC-3):** under squash merge,
  `step-head-final.head_sha` is the squash commit and will **almost always differ**
  from `step-head.head_sha`. AC-3 ("equals step-head when no panel-fix commits") is
  only reachable in merge-commit mode. The orchestrator records whatever the post-merge
  ref resolves to; it does not assert equality.

**Site B — Phase-10 close with no PR merge (ESCALATE / no-PR / doc-only).**
Per BC-220-2, still write the event so the next step has a continuity anchor, but with
`merged: false`, using the current local HEAD at close time (no fetch needed — nothing
merged):

```
{"event":"step-head-final","step":N,"head_sha":"<git rev-parse HEAD>","merged":false,"timestamp":"<ISO-8601Z>"}
```

The evaluator's R2 still consumes this as the BASE anchor (continuity, BC-220-2); the
unmerged state is recorded via `merged:false` in the audit trail.

**Boundary:** the orchestrator writes this event **after** confirming merge state (or
close); it is a recording action only — it triggers no re-review (spec §4).

### 2.4 `contract/OVERSIGHT-CONTRACT.md` §6a — catalog entry (R3)

Add one row to the §6a event-catalog table and document the fields:

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `step-head-final` | Records a step's post-panel (post-merge, or Phase-10-close) final HEAD SHA — the authoritative base anchor for the next step | oversight-orchestrator | `step`, `head_sha`, `merged`, `panel_fix_commits` (advisory), `timestamp` |

Document: `head_sha` full 40-char; `merged` true on PR-merge path / false on
ESCALATE-no-PR path (BC-220-2); `panel_fix_commits` advisory/optional (spec §4);
compact single-line JSON (BC-220-4).

---

## 3. Cross-spec binding (SPEC-219)

`scripts/oversight/lib/step_range.sh` is the shared helper SPEC-219's `--step N` path
in `run_second_review.sh` consumes to resolve its `base_sha..head_sha` diff window.
SPEC-219 sources this helper and calls `get_step_range "$STEP"`; an empty return means
"no recorded range for this step" and SPEC-219 owns that fallback (e.g. `git diff HEAD`).
This design only guarantees the helper's interface (§2.1); SPEC-219 wires it in.

---

## 4. Acceptance-criteria mapping

| AC | Covered by |
|---|---|
| AC-1 (final event with 40-char sha + ISO ts after merge) | §2.3 Site A |
| AC-2 (differs when panel-fix commits) | §2.3 Site A (+ squash note) |
| AC-3 (equals step-head when none — merge-commit mode only) | §2.3 squash note |
| AC-4 (next step uses final as BASE) | §2.2 + §2.1 final-over-plain |
| AC-5 (falls back to step-head, no error) | §2.2 fallback + §2.1 step 3 |
| AC-6 (step-scoped, not cross-step) | §2.1 portable grep BC-220-3 |
| AC-7 (§6a catalog entry) | §2.4 |

---

## 5. Self-flag

RISK: LOW
CONFIDENCE: 85% — confident in the helper interface, the portable grep, and the
final-over-plain preference; the residual uncertainty is the orchestrator's exact
post-merge SHA resolution under the project's real `gh pr merge` invocation (squash vs
merge-commit), which the spec/BC-220-1 explicitly leave as "resolve from the fetched
ref" — the design records whatever the ref yields rather than asserting a mode.

Change classification: **additive** (new event type, new helper, additive fallback in
evaluator; the only modification to existing behavior is the step-scoping correctness
fix in the evaluator's BASE_SHA grep, which narrows an over-broad lookup — strictly
safer). No structural-override signatures (no new dependency, auth, route, surface, or
state enum).
