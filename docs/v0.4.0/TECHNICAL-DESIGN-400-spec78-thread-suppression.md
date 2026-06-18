# Technical Design — SPEC-78 OQ-2: Thread suppression for ledgered findings on panel re-runs

**Issue:** #400 (human-cleared OQ-2) / #78
**Spec:** `docs/specs/SPEC-78-convergence-ledger-external-reviews.md`
**Scope:** `scripts/run_panel.sh` only.
**Status:** Design for implementation. Architect ruling (option a) is the binding input.
**Date:** 2026-06-18

---

## 1. Background and the cleared decision

SPEC-78 introduced a per-PR convergence ledger for `run_panel.sh` at
`.ai-local/panel/pr<N>-ledger.jsonl`. OQ-2 was held PENDING HUMAN CHECKPOINT (#400, binding C3):
the panel currently posts *every* current-run finding as a PR review thread regardless of ledger
status. The `new_blocking_count` field gates only the script's exit code, not thread posting.

Issue #400 has now been cleared by the human. The architect ruling is:

- **(a) Skip posting.** For a finding whose fingerprint is already in the per-PR ledger, the panel
  does **not** call `gh api` / `gh pr review` to create a PR review thread.
- **Counts must be visible.** The arbiter summary comment must report how many findings were
  suppressed because they were already ledgered, alongside the total — `N suppressed (ledgered)`.
- **`run_panel.sh` only.** This is wiring at the existing thread-posting call site; no Python module
  change, no new dedup logic (binding C1: import, never reimplement).

This is a MEDIUM, **additive-leaning-structural** change: it alters a user-visible behavior (which
threads appear on the PR) but does not change the verdict/exit contract, the ledger format, or the
fingerprint rule. See §7 for the HOS self-flag and §8 for the startup-gap analysis.

---

## 2. Contract (what the code must do, not how)

### 2.1 Fingerprint contract (unchanged — imported)

Per binding C1/C7, the fingerprint is computed by `scripts/oversight/validation_logic.py`'s
`fingerprint(finding)` function and nowhere else. Its rule is `(sorted files, finding-class)`:

- files: `finding["files"]` (list) or singular `finding["file"]`, sorted.
- class: `finding["category"]` or `finding["type"]`.

The panel finding object uses `file` (singular) and `lens` as the panel's closest equivalent of
the finding class. The existing convergence-count code (current `run_panel.sh` lines ~560-585)
already maps `{"file": f["file"], "category": f["lens"]}` into `fingerprint(...)`. The suppression
logic MUST use the **identical mapping** so that a finding suppressed from posting is exactly a
finding that does not count toward `new_blocking_count`. The two must never diverge.

### 2.2 Ledger membership contract (unchanged — imported)

`load_ledger(ledger_path)` returns the set of seen fingerprints. A missing ledger file → empty set
→ nothing is suppressed (first run posts everything). This is the existing, tested behavior; the
suppression path inherits it for free.

### 2.3 Posting suppression contract (new)

In the POST stage, for each arbiter finding, before any `gh api` / `gh pr review` call:

1. Compute the finding's fingerprint via the imported `fingerprint(...)` with the §2.1 mapping.
2. If the fingerprint is in the per-PR ledger set (`load_ledger(PANEL_LEDGER)`):
   - **Do not** call `post_thread` (which issues the `gh api` POST).
   - Increment a `suppressed_count` counter.
   - The finding is not folded into `UNANCHORED` either — a ledgered finding has already been
     triaged; it is silent in the thread surface by design.
3. Otherwise post as today (anchored thread, or fold into `UNANCHORED` if it cannot anchor to a
   diff line — unchanged behavior).

**Boundary — dry-run.** `--dry-run` must honor suppression for an accurate preview: a suppressed
finding prints a `[dry-run] suppressed (ledgered)` line instead of `[dry-run] thread`, so the
operator sees what a real run would post. No `gh` call happens in dry-run regardless; the counter
still increments so the summary preview is correct.

**Boundary — what is NOT suppressed.** Suppression applies to **thread posting only**. It does not:
- change `FCOUNT`, `TIER1_COUNT`, `TIER2_COUNT` (the arbiter's finding inventory is unchanged);
- change `new_blocking_count` (already computed independently; the two share the same fingerprint
  rule but suppression does not re-derive it);
- remove findings from the Tier 1 / Tier 2 markdown sections of the summary (the summary is the
  human's full inventory; suppression affects only whether a *line thread* is created). A ledgered
  finding still appears in the summary body but is annotated as already-reviewed via the count line.
- alter the exit-3 escalation (still keyed on `new_blocking_count > 0`).

### 2.4 Summary count contract (new)

The summary comment's verdict header line must include the suppressed count. Today the line reads:

```
**Findings:** $FCOUNT ($POSTED posted as threads) · tier1=… tier2=…
```

It must become (counts of the same run):

```
**Findings:** $FCOUNT ($POSTED posted as threads · $suppressed_count suppressed (ledgered)) · tier1=… tier2=…
```

The architect's required phrasing `N suppressed (ledgered) · M new` is satisfied by reporting the
suppressed count next to the posted count; `M new` is the posted/non-suppressed total already
present as `$POSTED`. The header therefore conveys both `suppressed (ledgered)` and the new/posted
total in one line.

The terminal "Panel complete" line and `panel-verdict.json` are out of contract for this change but
MAY carry `suppressed_count` for symmetry (additive, optional — see §3).

---

## 3. Implementation plan (file: `scripts/run_panel.sh`)

All changes are in the POST stage and the summary assembly. No Python file changes.

1. **Build the ledger set once, in the POST stage**, reusing the already-resolved `$_VL_PY` and
   `$PANEL_LEDGER`. A single `python3` heredoc emits, for each finding, whether its fingerprint is
   ledgered — OR (simpler and preferred) a per-finding `is_ledgered` lookup done inside the loop via
   one Python call that takes the finding's file+lens and returns `1`/`0`. To avoid N subprocess
   calls, the preferred form is a **single pre-pass**: a Python heredoc reads `arbiter.json` and the
   ledger, and prints a newline-delimited list of `1`/`0` flags in `FINDINGS` iteration order. The
   shell reads that into an array and indexes it inside the existing `while` loop.

   This pre-pass uses the exact §2.1 mapping and `load_ledger` + `fingerprint` imports — identical to
   the existing `new_blocking` heredoc, guaranteeing the suppression set ≡ the ledgered set used for
   the count.

2. **Initialize** `suppressed_count=0` next to `POSTED=0`.

3. **Inside the posting `while` loop**, after extracting the row fields, consult the flag for the
   current index:
   - if ledgered → increment `suppressed_count`, emit an info/skip line, `continue` (no `gh api`,
     no UNANCHORED fold);
   - else → existing posting logic unchanged.

4. **Summary header line** updated per §2.4 to include `$suppressed_count suppressed (ledgered)`.

5. **(Optional, additive)** add `suppressed_count` to the "Panel complete" stdout line and to
   `panel-verdict.json` for downstream symmetry.

### 3.1 Indexing approach (decision)

The posting loop iterates `printf '%s' "$FINDINGS" | jq -c '.[]'`. To pair each row with its
ledgered flag deterministically, the pre-pass MUST iterate the **same** `data["findings"]` array in
the **same order** as `FINDINGS` (which is `RANKED_JSON.findings`, already tier-ordered and written
to `arbiter.json`). Since `FINDINGS` is derived from `arbiter.json` (`.findings`), reading
`arbiter.json` `.findings` in the heredoc yields identical order. The shell tracks a loop index
`fi=0` and reads `FLAGS[$fi]`.

---

## 4. Algorithm (pseudocode — for the coder; not the code)

```
# pre-pass (one python3 call), after RANKED_JSON written to arbiter.json:
LEDGERED_FLAGS = python:
    ledger = load_ledger(PANEL_LEDGER)
    for f in json.load(arbiter.json)["findings"]:
        key = fingerprint({"file": f.get("file",""), "category": f.get("lens","")})
        print(1 if key in ledger else 0)
# → array FLAGS in findings order

suppressed_count = 0
POSTED = 0
fi = 0
for row in FINDINGS:
    ledgered = FLAGS[fi]; fi += 1
    if ledgered:
        suppressed_count += 1
        info "skip (ledgered): file:line [sev/lens] title"
        continue
    ... existing post / unanchored logic ...
```

---

## 5. Boundaries each component must honor

- **No reimplementation (C1).** The shell calls `validation_logic.fingerprint` / `load_ledger`. It
  must not parse the ledger JSONL itself or compute a fingerprint string inline.
- **Suppression set ≡ count set.** The pre-pass mapping (`file`→`file`, `lens`→`category`) must be
  byte-identical to the existing `new_blocking` heredoc mapping. If one is changed, both change.
- **Fail-open on Python error.** If the pre-pass fails (missing `$_VL_PY`, malformed `arbiter.json`),
  it must degrade to "nothing suppressed" — every finding posts, `suppressed_count=0`. A ledger/
  fingerprint failure must never *silently drop* a finding from the PR (that would hide signal). This
  mirrors the existing fail-open of the corroboration-ranking and convergence-count code.
- **No exit-code change.** Suppression does not touch the exit-3 path.

---

## 6. Test / verification expectations

Static + inner-loop only (this is a shell change; no unit-test harness for `run_panel.sh` here):

- `bash -n scripts/run_panel.sh` — parses clean.
- `./scripts/framework/run_tests_inner_loop.sh` — no regression.
- `bash scripts/framework/check_agents_static.sh` — unaffected (no agent edits) but run as a guard.
- **Behavioral (manual / dry-run):** with a ledger containing a finding's `(file, lens)` fingerprint,
  a `--dry-run` re-run prints `suppressed (ledgered)` for that finding and the summary header shows
  `… suppressed (ledgered)`. With an empty/missing ledger, `suppressed_count == 0` and behavior is
  identical to pre-change.

AC coverage: this design realizes the OQ-2 user-visible behavior described in SPEC-78 §8 OQ-2 now
that #400 is cleared. It does not alter AC-1..AC-5 (those govern the verdict/`new_blocking_count`
contract, which is unchanged).

---

## 7. HOS self-flag

RISK: MEDIUM
CONFIDENCE: HIGH

Change class: **additive** (a new suppression branch + a counter at an existing call site; no
existing contract field changes meaning). It edges toward structural because it changes a
user-visible output (threads on the PR), but it is gated behind ledger membership which is empty on
first run — default/first-run behavior is byte-identical to today, and the change is fully reverting
by clearing the ledger (`--reset`). It does not alter the verdict, exit code, ledger format, or
fingerprint rule.

## Human Review Required

- **What changed:** On a panel re-run, findings whose `(sorted files, lens)` fingerprint is already
  in `.ai-local/panel/pr<N>-ledger.jsonl` are no longer posted as new PR review threads; the arbiter
  summary reports the suppressed count next to the posted count.
- **Why it needs eyes:** It is the OQ-2 user-visible behavior change the architect held for human
  clearance (#400). Reviewers/human will no longer see re-surfaced threads for already-triaged
  findings on a re-run. Confirm this is the intended post-clearance behavior.
- **Blast radius:** `scripts/run_panel.sh` POST stage + summary header only. No Python, no other
  script, no agent file.
- **Reversibility:** Full. First run (empty ledger) is unchanged; `--reset` restores re-posting.

## 8. Startup-gap analysis

*"Should this have been settled in the initial technical design, before any code was written?"*

No `startup-artifact-gap` is opened. OQ-2 was **explicitly and deliberately** deferred by the
architect (binding C3) to a human checkpoint (#400); the original SPEC-78 implementation correctly
omitted thread-suppression and shipped `new_blocking_count` as exit-gating only. This change is the
*planned* second phase, not a correction of a missed edge case.

**Affected sign-offs analysis:**
- Prior SPEC-78 sign-offs on the *verdict/count* contract (`new_blocking_count`, exit-3, ledger
  format) **stand** — none of that behavior changes here.
- There is no already-approved code implementing OQ-2 suppression (it was never built), so there is
  no orphaned approval to invalidate. The new suppression branch requires a fresh code-review +
  panel review of `run_panel.sh` against this design.
