# SPEC-78: Convergence ledger for external and panel reviews

**Status:** REVISED — OQ-2 pending human clearance (#400). C1-C7 applied.
**Issue:** #78
**Date:** 2026-06-17

---

## Architect bindings (applied 2026-06-17)

The following constraints were issued by the architect and are binding on all implementations of this spec. They take precedence over any spec text that conflicts.

**C1 — Import, never reimplement.** Fingerprint and ledger I/O (`load_ledger`, `fingerprint`, `record_ledger_entry`) must be imported from `scripts/oversight/validation_logic.py`. They must never be reimplemented in `panel_logic.py`, `second_review_logic.py`, or any other module.

**C2 — No panel pass counter.** The panel does not adopt a pass counter. The ledger (per R3/R4) is the sole convergence mechanism for the panel. `--reset` on the panel script is a no-op on any counter; it removes only the ledger file. OQ-1 is resolved: no explicit pass counter for the panel.

**C3 — OQ-2 PENDING HUMAN CHECKPOINT (#400).** Suppressing ledgered findings from PR thread posting on panel re-runs is a user-visible behavior change (reviewers and the human will not see re-surfaced threads for already-triaged findings). This behavior is NOT implemented until human clearance is received on issue #400. The implementation in this release omits thread-suppression; `new_blocking_count` gates the exit verdict only.

**C4 — No step-less fallback.** `--step` is required for `run_second_review.sh` (already enforced). The ledger is scoped to step. No fallback ledger path for `--files` or `--diff` invocation modes — those modes require `--step` to be ledger-scoped.

**C5 — Ledger path asymmetry is intentional.** Panel ledger: `.ai-local/panel/pr<N>-ledger.jsonl`. Second-review ledger: `.claudetmp/second-review/step<N>-ledger.jsonl`. The asymmetry mirrors the existing output-file location asymmetry and is by design.

**C6 — `record_ledger_entry` is the only writer.** Both scripts must open their ledger file exclusively via `record_ledger_entry` (append mode). No script or delegate may open the ledger file directly for writing.

**C7 — Fingerprint = (sorted files, category) only.** The fingerprint is `(sorted files, finding-class)` as defined in `validation_logic.py`. No finding TEXT is included. This is already the behavior of `validation_logic.fingerprint()` — implementations must use that function, not a local variant.

---

## 1. Problem statement

The HOS pipeline contains three AI-reviewer loops. Each loop is non-deterministic: the same code, re-reviewed by the same vendor, will produce a different set of findings on successive runs.

**Self-review** (`validate_self.sh`) already solves non-determinism with a convergence ledger. The ledger records the fingerprint — a `(sorted files, category)` pair — of each finding once it is dispositioned (fixed, filed, or noise). Subsequent passes compute a verdict based only on NEW (un-ledgered) blocking findings. When all blocking findings are either fixed or recorded in the ledger, the verdict becomes `approve` and the loop terminates. This is the ratchet: the reviewer cannot cause a re-run by re-raising an already-triaged finding.

**External reviews** (`run_second_review.sh` and `run_panel.sh`) do not have this mechanism. They track a pass counter but have no per-finding ledger. Consequences:

- A finding that was triaged as `residual` or `noise` in a previous run returns on the next pass and re-blocks the verdict, forcing another human decision.
- The pass cap alone does not distinguish between "zero new findings" and "same old findings again" — when the cap is hit, it is ambiguous whether the reviewer found something genuinely new or re-raised something already dispositioned.
- This creates unbudgeted vendor API calls: a re-run that contributes no new signal still costs a full agy or codex invocation.

The self-review convergence ledger (and the Python primitive that implements it in `scripts/oversight/validation_logic.py`) solves exactly this problem. The question this spec answers is: should the same ledger pattern be applied to the external-review loops, and if so, how?

The answer is yes. The rest of this spec defines what that means in concrete behavioral terms.

---

## 2. Scope

This spec covers the following two scripts:

- `scripts/run_second_review.sh` — pre-PR cross-vendor second review (agy/codex). Fires at MEDIUM+ by score or tier floor. Per-step output file in `.claudetmp/second-review/`.
- `scripts/run_panel.sh` — post-PR multi-agent review panel (agy/codex/ipcheck). Fires per open PR. Per-run output in `.ai-local/panel/`.

**Shared primitive:** Both scripts must use the shared ledger functions already implemented in `scripts/oversight/validation_logic.py` (SPEC-334): specifically `load_ledger`, `fingerprint`, `record_ledger_entry`, and the `record` CLI subcommand. No new dedup logic is introduced — this spec wires existing logic to two new call sites.

**Out of scope:**

- `scripts/framework/validate_self.sh` — already has a ledger; not changed.
- `scripts/framework/validate_agents.sh` — has its own ledger (the `external-review-ledger.jsonl`). Not part of this spec.
- `scripts/framework/validate_scripts.sh` — same exclusion.
- Pass caps (`SECOND_REVIEW_MAX_PASSES`, the existing panel iteration limit) — not changed by this spec; the ledger is complementary to, not a replacement for, the cap.
- Reviewer selection logic, threshold values, vendor routing, diff-centric mode — not changed.
- What the vendors review (lenses, prompts, diff content) — not changed.
- The output file format or machine-readable header fields — not changed, except that `new_blocking_count` becomes meaningful in both scripts (previously not tracked).

---

## 3. Ledger locations

Each script manages its own ledger. Ledgers are per-step for second review and per-PR for the panel, so that dispositions from one project step or one PR do not bleed into another.

| Script | Ledger path |
|---|---|
| `run_second_review.sh` | `.claudetmp/second-review/step<N>-ledger.jsonl` |
| `run_panel.sh` | `.ai-local/panel/pr<N>-ledger.jsonl` |

Both paths follow the same scoping convention already used by the corresponding output files (`step<N>-<timestamp>.md` for second review; `pr<N>-<date>/` run directories for the panel).

The ledger file is created on first `--record` write. A missing ledger file is treated as an empty ledger (zero seen fingerprints), which is the existing behavior of `load_ledger` in `validation_logic.py`.

---

## 4. Requirements

**R1 — Shared primitive via `validation_logic.py`.** Both `run_second_review.sh` and `run_panel.sh` must read and write their convergence ledger using the functions already implemented in `scripts/oversight/validation_logic.py`: `load_ledger` (to build the seen-fingerprint set before verdict computation) and `record_ledger_entry` / the `record` CLI subcommand (to append dispositions after triage). No new dedup logic is introduced in either script or in any new module.

**R2 — Second review reads ledger before invocation.** Before invoking agy or codex, `run_second_review.sh` must load the per-step ledger at `.claudetmp/second-review/step<N>-ledger.jsonl`. After the reviewer completes, the script passes the ledger to `validation_logic.py process` when computing the verdict. Findings whose fingerprint is already in the ledger do not count toward `new_blocking_count`. The verdict is `approve` when `new_blocking_count` is zero, regardless of total `blocking_count`.

**R3 — Panel reads ledger before invocation.** Before dispatching reviewers, `run_panel.sh` must load the per-PR ledger at `.ai-local/panel/pr<N>-ledger.jsonl`. After the arbiter completes, the ledger is consulted during verdict computation so that findings already in the ledger do not count as new blocking findings for the panel's exit decision.

**R4 — Convergence verdict: zero NEW un-ledgered blocking findings.** In both scripts, the convergence condition is: `new_blocking_count == 0`. This mirrors the self-review behavior exactly. "Blocking" means a finding with severity `critical`, `high`, or `blocking` in the canonical `validation_logic.py` severity ordering. Previously-ledgered findings do not re-block. The total `blocking_count` (all blocking findings, including ledgered ones) continues to be reported for transparency but does not gate the verdict.

**R5 — `--record` and `--reset` subcommands for both scripts.** Both scripts must accept:
- `--record <files> <class> <disposition>` — appends one entry to the script's own ledger (delegates to `validation_logic.py record`). `disposition` values are: `fixed`, `filed:#<N>`, `residual`, `noise`.
- `--reset` — clears the ledger and (where applicable) the pass counter for the current step/PR scope. Used when starting a review of a genuinely new change set on the same step or PR.

**R6 — Ledger is append-only.** Neither script nor any delegate may truncate or overwrite the ledger. Only `--reset` removes it. This preserves the audit trail of dispositions.

**R7 — New `new_blocking_count` header field.** Both scripts' output files must include `new_blocking_count: <N>` as a machine-readable header field, populated after the verdict is computed. This field is already emitted by `validation_logic.py process`. The oversight-evaluator may use this field; the spec does not require it to do so today but the field must be present and correct.

---

## 5. Triage workflow (unchanged in kind, made explicit)

The following workflow already exists for self-review. This spec applies the same pattern to external reviews.

1. **Reset** (`--reset`) when starting a review of a new change set on the same step or PR. This clears prior dispositions so genuinely new code is not masked by old ledger entries.

2. **Run a pass.** For each NEW (un-ledgered) blocking finding:
   - Fix in place (if the code change is small and contained), or
   - File a GitHub issue (if it needs a human or another agent's attention), then
   - Record it: `<script> --record "<files>" <class> fixed|filed:#N|residual|noise`

3. **Re-run.** The verdict is keyed on NEW findings, so once every blocking finding is either fixed or ledgered, the pass returns `approve`. The model need not return zero findings — it need only return zero UN-LEDGERED blocking ones.

4. **Hard cap.** The existing pass caps (`SECOND_REVIEW_MAX_PASSES` for second review; the panel's own iteration limit) remain. If the cap is hit while `new_blocking_count > 0`, the script exits with the escalation code (exit 3 for second review, following the self-review convention) — a human decides. Automation never loops past the cap.

---

## 6. Non-requirements

The following are explicitly out of scope for this spec:

- **No change to pass caps.** `SECOND_REVIEW_MAX_PASSES` and the panel's iteration limit are not modified. The ledger is complementary to the cap, not a replacement.
- **No change to what vendors review.** Reviewer prompts, lenses, diff-centric mode, reviewer selection thresholds, and the content passed to agy/codex are unchanged.
- **No change to the ledger format.** The JSONL entry format defined in SPEC-334 (`files`, `class`, `disposition`, `ts`) is used as-is.
- **No ledger sharing across steps or PRs.** Each step has its own second-review ledger; each PR has its own panel ledger. Dispositions do not cross boundaries.
- **No change to issue creation logic.** `run_second_review.sh` already creates GitHub issues for critical/high findings; that behavior is unchanged.
- **No change to the oversight-evaluator's interpretation contract.** The evaluator already reads `new_blocking_count` if present; this spec does not add new evaluator requirements.
- **No dedup of the arbiter's merged findings against the ledger.** The ledger deduplicates at the raw-finding fingerprint level. The arbiter's dedup (across reviewers, for corroboration ranking) is a separate operation and is not changed.

---

## 7. Acceptance criteria

**AC-1:** Given a second-review run on step N where a `high`-severity finding was recorded in the ledger in a previous pass with disposition `residual`, a subsequent run that produces the identical fingerprint reports `new_blocking_count: 0` and `verdict: approve`, even though `blocking_count` is 1.

**AC-2:** Given a panel run on PR M where a `critical`-severity finding was recorded with disposition `filed:#42`, a subsequent panel pass that re-raises the same fingerprint reports `new_blocking_count: 0` and `verdict: approve`.

**AC-3:** `run_second_review.sh --record "app/views.py" authorization filed:#99` writes one JSONL entry to `.claudetmp/second-review/step<N>-ledger.jsonl` and exits 0.

**AC-4:** `run_panel.sh --reset` removes the PR-scoped ledger (and pass counter if one exists) and exits 0.

**AC-5:** Both scripts' output files contain a `new_blocking_count: <N>` header field after a completed pass. The value is correct (total blocking findings minus ledgered blocking findings).

---

## 8. Open questions for architect

**OQ-1 (ledger scope for the panel) — RESOLVED (C2):** No pass counter for the panel. The ledger is the sole convergence mechanism. `--reset` removes the ledger file only; no counter to clear. The existing one-invocation model is sufficient.

**OQ-2 (panel verdict vs. thread posting) — PENDING HUMAN CHECKPOINT (#400):** The panel's primary output is PR review threads, not an exit code. The `new_blocking_count` field gates the script's exit verdict but does not currently suppress thread posting. The architect has ruled this a user-visible behavior change: if ledgered findings were suppressed from PR threads on re-runs, reviewers and the human would not see re-surfaced threads for already-triaged findings. This behavior is NOT implemented until human clearance is received on issue #400. Current behavior (all current-run findings posted regardless of ledger status) is preserved.

**OQ-3 (ledger path for multi-step second reviews) — RESOLVED (C4):** No step-less fallback. `--step` is required for ledger-scoped invocations (it is already required by the script). The `--files` and `--diff` modes also require `--step` when a ledger is in use. The script already exits with an error when `--step` is absent; no new behavior is needed.
