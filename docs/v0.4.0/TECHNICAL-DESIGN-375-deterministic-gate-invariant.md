# Technical Design — SPEC-375 Deterministic Gate Non-Override Invariant

**Spec:** `docs/specs/SPEC-375-deterministic-gate-invariant.md` (#375, APPROVED 2026-06-16)
**Document type:** Technical design (implementation contract for the coder)
**Status:** DRAFT — awaiting architect review (iteration 1)
**Author:** technical-design

---

## HOS self-flag

```
RISK: MEDIUM
CONFIDENCE: 72%
BLAST RADIUS: oversight-evaluator Phase 1 (governance gate), a new gate-runner
  script, OVERSIGHT-CONTRACT.md §1/§6a/§7, plus two test files. No application
  code. The change tightens a human-facing oversight gate (fail-closed direction
  only) and adds a deterministic CRITICAL surfacing path.
```

**Change classification:** `additive` for the contract text and the new gate-runner
script (new artifact, new compliance row); `structural` for REQ-GATE-NN-17 — it
introduces a *new deterministic CRITICAL trigger* (composite ≥ 0.78 forces a
COMPLIANCE FAIL regardless of `blocking_findings:`) that did not previously gate
the pipeline. A new pipeline-blocking condition is a structural change.

## Human Review Required

> **Structural change — escalate before the coder is dispatched.**
> REQ-GATE-NN-17 adds a deterministic CRITICAL gate (composite ≥ 0.78 → COMPLIANCE
> FAIL) that can block a PR the evaluator previously would have passed. Per the
> authoring contract a `structural` design change is escalated to a human before
> writing. The spec itself is human-APPROVED and the architect resolved
> OQ-375-ARCH-01/02, so the *decision* is settled; this flag records that the
> resulting design carries a new blocking condition the human should be aware of
> when it lands. **OQ-TD-375-01 below (no central gate runner exists) is the open
> item that must reach the architect before coding.**

---

## 1. Problem restatement (the contract this design fixes)

A deterministic gate (`scripts/oversight/gates/*.sh`) or validator can exit
non-zero on a real finding, an LLM reviewer can approve the same code, and the
synthesis layer can treat the LLM's silence/approval as resolving the
deterministic failure — burying it before the human sees it. This design makes
two things true:

1. **The record of what gates ran and how they exited is captured deterministically**
   in a `gate-results.json` artifact (today nothing writes gate exit codes
   anywhere the evaluator can read — §3 below).
2. **The oversight-evaluator independently re-derives the deterministic verdict**
   from `gate-results.json` and `summary.json` and fails closed when a
   deterministic failure is not surfaced unresolved to the human (§4).

This design covers spec items 1–5 from the work order: the gate-results write
path, the REQ-GATE-NN-08 compliance check, the REQ-GATE-NN-17 composite
cross-check, the contract artifact-list update, and the two tests.

---

## 2. Component map

| # | Component | File | Change | Owner role |
|---|---|---|---|---|
| C1 | Gate runner (NEW) | `scripts/oversight/run_gates.sh` | New central invoker that runs each gate and writes `gate-results.json` | coder |
| C2 | gate-results writer | inside C1 (`append_gate_result` bash fn) | Append one JSON record per gate | coder |
| C3 | Evaluator Phase 1 — gate-results compliance | `.claude/agents/oversight-evaluator.md` | REQ-GATE-NN-08 + REQ-GATE-NN-16 fail-closed | technical-design (this doc authors the prompt contract; coder edits the file) |
| C4 | Evaluator Phase 1 — composite cross-check | `.claude/agents/oversight-evaluator.md` | REQ-GATE-NN-17 | as C3 |
| C5 | Evaluator audit emit | `.claude/agents/oversight-evaluator.md` | REQ-GATE-NN-09 `gate-deterministic-suppressed` event | as C3 |
| C6 | Contract — filesystem protocol | `contract/OVERSIGHT-CONTRACT.md` §1 | Add `gate-results.json` to the `.claudetmp/oversight/validators/` block | coder |
| C7 | Contract — §6a catalog | `contract/OVERSIGHT-CONTRACT.md` §6a | Add `gate-deterministic-suppressed` event row | coder |
| C8 | Contract — §7 invariant | `contract/OVERSIGHT-CONTRACT.md` §7 | Add REQ-GATE-NN three-part text (REQ-GATE-NN-07) | coder |
| C9 | Test — absent gate-results | `scripts/oversight/tests/test_gate_results_compliance.py` (or bats) | AC-375-11 | unit-test |
| C10 | Test — composite cross-check | same file | AC-375-12 | unit-test |

> Spec items 1–5 map to C1/C2 (item 1), C3+C5 (item 2), C4 (item 3), C6 (item 4),
> C9/C10 (item 5). REQ-GATE-NN-11/12 (orchestrator handoff/panel-context) are in
> the spec's §11 artifact table but are **out of scope for this work order** — they
> are noted in §8 as a follow-on for the orchestrator agent.

---

## 3. Component C1/C2 — `scripts/oversight/run_gates.sh` (gate runner)

### 3.1 Why a new script (OQ-375-ARCH-01 is RESOLVED; this is the consequence)

There is **no central gate runner today.** Each gate in `scripts/oversight/gates/`
is a standalone script invoked individually (today: by humans, by
`review_self.sh`, and — once it exists — by the worker pipeline). `run_validators.sh`
orchestrates *validators only* and the architect explicitly ruled (OQ-375-ARCH-01)
it must not be extended to write gate results. Therefore the gate runner the spec
refers to in REQ-GATE-NN-15 ("the pipeline step that invokes `gates/*.sh`") does
not exist as a single artifact and must be created as `scripts/oversight/run_gates.sh`.

### 3.2 Contract (what the script must do)

**Invocation surface:**
```
scripts/oversight/run_gates.sh [--staged | --all | <file> ...]
```
- Mirror `run_validators.sh`'s argument handling for the file set (the file list
  is passed through to each gate; `--staged`/`--all` are passed through verbatim
  to gates that accept them).
- The canonical gate set and names are exactly the spec §3.1 table. The runner
  invokes, in this order, the gates that exist on disk (skip-if-absent, same as
  `run_validators.sh` does for validators):

  | Gate script | Canonical name (the `gate` field value) |
  |---|---|
  | `lint_check.sh` | `lint` |
  | `security_scan.sh` | `security` |
  | `secret_scan.sh` | `secrets` |
  | `type_check.sh` | `types` |
  | `template_refs_check.sh` | `template-refs` |
  | `portability_check.sh` | `portability` |
  | `django_check.sh` | `django` |
  | `collection_integrity.sh` | `collection-integrity` |
  | `expensive_gates_stub.sh` | `expensive-gates` |

  `check_suspension.sh` is NEVER invoked as a gate (it is a sourced helper) — the
  runner must exclude it by name.

**Output artifact:** `.claphtmp` — write to `.claudetmp/oversight/validators/gate-results.json`.
The file is a JSON **array** of records. The runner:
1. `mkdir -p .claudetmp/oversight/validators`
2. **Truncates/initializes** `gate-results.json` to `[]` at the start of the run
   (same staleness reasoning as `run_validators.sh` clearing `*.json`). Stale gate
   records from a prior run must never contaminate the current evaluation.
3. After each gate exits, appends one record.

**Record schema** (exactly the spec §8 REQ-GATE-NN-15 shape, plus a timestamp the
work order requires):
```json
{
  "gate": "<canonical-name>",
  "exit_code": <int>,
  "suspended": <bool>,
  "script": "<relative path to the gate script>",
  "ts": "<ISO-8601 UTC>"
}
```

**Determining `suspended`:** a gate reports suspension by exiting 0 after printing
the suspended banner (see `check_suspension.sh`: `is_suspended … && { print_suspended; exit 0; }`).
The runner cannot distinguish "passed" from "suspended" by exit code alone — both
are 0. Therefore the runner must consult the suspension manifest **itself**, using
the same grammar the gates use:
- Source `scripts/oversight/gates/check_suspension.sh` and call `is_suspended "<name>"`
  for each gate before/after the run; set `suspended: true` when it returns 0.
- This keeps one grammar across the runner, the gates, and `suspension_manager.py`
  (the HOS#105 "two parsers, one grammar" rule). Do not re-implement the regex.

**`append_gate_result` bash function (C2) — signature and behavior:**
```
append_gate_result <gate_name> <exit_code> <suspended_bool> <script_path>
```
- Builds one record and appends it to the in-memory array, then rewrites
  `gate-results.json` as a well-formed array. Use the oversight venv Python
  (`$OVERSIGHT_PYTHON`, same bootstrap as `run_validators.sh`) to serialize JSON —
  do **not** hand-concatenate JSON in bash (the contract's audit log has been
  bitten by exactly this; #387). The function reads the existing array, appends,
  and writes back, so a crash mid-run still leaves a valid (shorter) array.
- `ts` is `date -u +%Y-%m-%dT%H:%M:%SZ`.

**Exit semantics:** `run_gates.sh` exits non-zero if any non-suspended gate exited
non-zero (so a CI/worker caller can see the aggregate), but **the artifact is the
contract**, not the exit code — the evaluator reads `gate-results.json`, never the
runner's exit code. The runner must always finish writing the artifact even when a
gate fails (no `set -e` early-exit before the artifact is complete; trap-on-EXIT to
flush is acceptable).

### 3.3 What the runner must NOT do
- Must not write to `summary.json` (REQ-GATE-NN-15 — `summary.json` stays the
  validator-composite artifact; `gate_failures` must not be added to it).
- Must not re-run validators.
- Must not interpret or resolve a gate failure — it records exit codes verbatim.

---

## 4. Component C3/C4/C5 — oversight-evaluator Phase 1 additions

These are **prompt-contract additions** to `.claude/agents/oversight-evaluator.md`.
They slot into Phase 1, after the existing "Risk-assessment scope + blocking
findings (#204)" block and before "If any hard compliance check fails: …". The
evaluator already reads `summary.json` and `risk-assessment.md`; this adds
`gate-results.json` as a third deterministic input.

### 4.1 REQ-GATE-NN-16 — fail-closed on absent gate-results.json (runs first)

Add an input bullet to the evaluator's **Inputs** list:
> `.claudetmp/oversight/validators/gate-results.json` — deterministic record of
> which gates ran and their exit codes (written by `scripts/oversight/run_gates.sh`).

Phase 1 logic (exact behavior the prompt must specify):
1. Determine whether gates were required for this step. Gates are required on every
   per-step build evaluation **unless** the step manifest marks `gates_required: false`
   for the step. (If the manifest has no such key, gates are required — fail-closed
   default, mirroring the `risk-assessment.md` rule in §7a.)
2. If gates are required and `gate-results.json` is **absent or unparseable** →
   **COMPLIANCE FAIL** (REQ-GATE-NN-16). The failure message must state:
   "gate-results.json absent on a step that requires gates — cannot verify no
   deterministic gate failed. Run scripts/oversight/run_gates.sh." Absence is NEVER
   read as "no gates failed." Do not proceed to PROCEED/CONDITIONAL_PROCEED.

This parallels the existing §7a fail-closed rule for a missing `risk-assessment.md`.

### 4.2 REQ-GATE-NN-08 — gate suppression compliance check

For the parsed `gate-results.json` array, plus the `blocking_findings:` list already
parsed from `risk-assessment.md`, build the set of **deterministic failures**:
- From `gate-results.json`: every record where `exit_code != 0` **and** `suspended == false`.
- (Validator/blocking-finding failures are already handled by the existing #204
  block; REQ-GATE-NN extends them with the suppression angle — see AC-375-07.)

For each deterministic failure `<gate>`:
1. **Suspension skip (§6.3):** if `<gate>` appears as `SUSPENDED: <gate>` in
   `contract/gate-suspension.md`, skip it (REQ-GATE-NN-04). (Belt-and-suspenders:
   the runner already set `suspended: true` for these, but the evaluator re-checks
   the manifest itself so a stale/forged `suspended:false` cannot defeat the skip
   logic — re-derive, don't trust.)
2. **Human-authorization coverage (REQ-GATE-NN-13):** check
   `.claudetmp/oversight/step{N}-human-authorization.md` for an explicit by-name
   reference to `<gate>` (e.g. the literal gate name `security` appears in the
   decision text). A general "proceed" without naming the gate does **not** cover it.
   - If covered → record as **covered**; add the REQ-GATE-NN-14 annotation row to
     the Phase 1 compliance table: `Gate: <name> — covered by human-authorization
     artifact dated <date>.`
3. **Surfaced-unresolved check:** if not covered, the finding must appear as
   *unresolved* in the human-facing output (`.claudetmp/oversight/step{N}-handoff.md`).
   - If `handoff.md` exists and contains the gate name under an unresolved section
     → satisfied (the human will see it).
   - If `handoff.md` is absent at evaluator time (the orchestrator runs after the
     evaluator), the evaluator cannot yet confirm surfacing — so it must instead
     **emit the finding into its own evaluation output as an ESCALATE item** naming
     the gate, and fail REQ-GATE-NN closed. The evaluator's verdict is the gate;
     it does not rely on a downstream artifact that may not exist yet.
   - If not surfaced and not covered → **COMPLIANCE FAIL (REQ-GATE-NN)**, naming
     the gate, its exit code, and the absence of a covering human-authorization
     artifact. Recommendation = ESCALATE.

**Independence from LLM verdict (REQ-GATE-NN-03):** the check must not consider any
reviewer's APPROVED status when deciding whether a gate failure is resolved. A
`security` sign-off `Status: APPROVED` next to a `security` gate `exit_code: 1` is
"deterministic failure + corroborating LLM opinion" — still a failure. The prompt
must state this explicitly so the model does not net them out.

### 4.3 REQ-GATE-NN-09 — audit event

When REQ-GATE-NN fires for a gate, append to `audit/oversight-log.jsonl`:
```json
{
  "event": "gate-deterministic-suppressed",
  "step": N,
  "gate": "<gate-name or blocking-finding-id>",
  "source": "gates" | "validators",
  "suppression_evidence": "<what was missing from the human-facing output>",
  "timestamp": "<ISO-8601>"
}
```
`source` is `gates` when the failure came from `gate-results.json`, `validators`
when it came from a `blocking_findings:` entry. Emit one event per suppressed gate.

### 4.4 REQ-GATE-NN-17 — composite cross-check (the structural addition)

After reading `summary.json`:
1. Read `composite_score` (float).
2. Import the threshold from the single source of truth — `schema.py`
   `TIER_THRESHOLDS["CRITICAL"]` lower bound = **0.78**. The prompt must cite the
   value as `0.78 (schema.py TIER_THRESHOLDS CRITICAL lower bound)` so a future
   threshold change in `schema.py` is the thing to update, not a hard-coded literal
   in the prompt. (The evaluator is an agent; it reads the number from the spec/
   schema reference, it does not import Python — but the prompt must name the
   canonical source so drift is auditable.)
3. If `composite_score >= 0.78` → this is a **deterministic CRITICAL failure
   regardless of `blocking_findings:` content.** Surface it as a COMPLIANCE FAIL
   (REQ-GATE-NN-17) citing the score against the 0.78 threshold, even when
   `blocking_findings:` is empty. Recommendation = ESCALATE. Emit a
   `gate-deterministic-suppressed` event with `source: "validators"`,
   `gate: "composite-critical"`, `suppression_evidence: "composite_score=<x> ≥ 0.78
   but not reflected as CRITICAL in blocking_findings"`.

This closes the gap where the LLM risk-assessor could omit a finding the composite
already reflects as CRITICAL. The composite is deterministic; an empty
`blocking_findings:` cannot resolve it.

### 4.5 Boundaries (what the evaluator must NOT do for this check)
- Must NOT re-run any gate (AC-375-09). It reads only `gate-results.json`,
  `summary.json`, `risk-assessment.md`, `contract/gate-suspension.md`, and the
  human-authorization directory.
- Must NOT lower a tier or create/modify any human-authored artifact (existing
  prohibition in the agent — unchanged).
- The two-direction rule (REQ-GATE-NN-10): a deterministic failure is always a
  compliance issue unless human-covered; it is never skipped because upstream
  "asked for more review."

---

## 5. Component C6/C7/C8 — OVERSIGHT-CONTRACT.md edits

### 5.1 §1 filesystem protocol (C6) — work-order item 4

In the `.claudetmp/oversight/validators/` block (contract lines 28–33), add a line
directly under the `risk-assessment.md` entry:
```
      gate-results.json          ← deterministic record of gate exit codes
                                    (JSON array; written by run_gates.sh, read by
                                    oversight-evaluator). Separate from summary.json;
                                    gate_failures are NOT added to summary.json.
```

### 5.2 §6a audit catalog (C7)

Add one row to the §6a event table:
```
| `gate-deterministic-suppressed` | A deterministic gate/validator failure was not
  surfaced unresolved to the human and is not covered by a human-authorization
  artifact (REQ-GATE-NN) | oversight-evaluator | `step`, `gate`, `source`
  (gates\|validators), `suppression_evidence` |
```

### 5.3 §7 invariant text (C8) — REQ-GATE-NN-07, three-part structure

Add a named-invariant subsection to §7 (alongside, not numbered into, conditions
11–16 per spec §6.2). The text must contain all three parts (AC-375-08):

> **REQ-GATE-NN — Deterministic gate non-override invariant.**
> *Covered:* every script in `scripts/oversight/gates/` and every validator in
> `scripts/oversight/validators/` that exited non-zero on a non-suspended run.
> *Prohibited:* an LLM reviewer or arbiter resolving, downgrading, closing,
> summarizing away, absorbing, or silently treating such a failure as resolved.
> LLM agreement does not resolve a deterministic failure; LLM silence does not
> close one. A `composite_score ≥ 0.78` (schema.py CRITICAL threshold) is itself a
> deterministic CRITICAL failure regardless of `blocking_findings:` content
> (REQ-GATE-NN-17). *Arbiter permission:* the arbiter may add context or
> corroboration to a deterministic finding (cite it by name, append the LLM
> perspective as a supplementary note); it may never suppress or outrank it. The
> only resolution path is a human-authorization artifact that names the gate
> (REQ-GATE-NN-13). This invariant sits alongside the numbered evaluator
> re-derivation conditions 11–16 (SPEC-evaluator-re-derivation.md) and reserves no
> number (condition 16 is the step-head timing correction, #220).

---

## 6. Function / interface signatures (exact)

**`run_gates.sh` (C1):**
```
# Entry
scripts/oversight/run_gates.sh [--staged | --all | <file> ...]
# Internal
append_gate_result <gate_name:str> <exit_code:int> <suspended:0|1> <script_path:str>
#   → appends one record to .claudetmp/oversight/validators/gate-results.json
```

**Artifact: `.claudetmp/oversight/validators/gate-results.json`** — JSON array of:
```json
{"gate": "string", "exit_code": 0, "suspended": false, "script": "scripts/oversight/gates/lint_check.sh", "ts": "2026-06-16T00:00:00Z"}
```

**Audit event (C5):** `gate-deterministic-suppressed` — fields per §4.3.

---

## 7. Tests (C9/C10) — work-order item 5

Place in `scripts/oversight/tests/` (the existing test home for oversight Python).
Each test drives the evaluator's *logic*, not the LLM — i.e. they test the
deterministic preconditions and the artifact contract the evaluator depends on.
Because the evaluator is an agent prompt, the tests assert on the **artifacts and
the documented decision rule**, fixturing inputs and asserting the required
verdict per the AC. The test author (unit-test role) implements these as the
deterministic harness around the gate-results/summary contract.

### 7.1 Test A — absent gate-results.json → COMPLIANCE FAIL (AC-375-11)
- **Arrange:** a step fixture where the step manifest requires gates, a valid
  `risk-assessment.md` and `summary.json` exist, but `gate-results.json` is absent.
- **Assert:** the evaluator's REQ-GATE-NN-16 rule yields COMPLIANCE FAIL (not
  PROCEED/CONDITIONAL_PROCEED), and the failure message names the absent file.

### 7.2 Test B — composite ≥ 0.78 with empty blocking_findings → COMPLIANCE FAIL (AC-375-12)
- **Arrange:** `summary.json` with `composite_score: 0.82`; `risk-assessment.md`
  with `blocking_findings: []`; `gate-results.json` present with all `exit_code: 0`.
- **Assert:** REQ-GATE-NN-17 yields a deterministic CRITICAL COMPLIANCE FAIL citing
  the 0.82 score against 0.78; the empty `blocking_findings:` does not suppress it;
  a `gate-deterministic-suppressed` event with `gate: "composite-critical"` is emitted.

> **Test boundary note for unit-test/system-test:** if the evaluator's decision rule
> is not directly unit-testable as Python (it lives in a prompt), the deterministic
> portion that IS testable is the **gate-results/summary contract and the
> precondition evaluation** — extract the threshold comparison and the
> required/absent logic into a tiny pure helper the evaluator's prompt references,
> or test via the agent harness. **This is OQ-TD-375-02 for the architect** (see §9).

---

## 8. Out of scope for this work order (tracked, not built here)

- **REQ-GATE-NN-11/12** (orchestrator `handoff.md` "Unresolved Deterministic Gate
  Failures" section + `panel-context.md` structural signal) — the spec §11 table
  assigns these to `oversight-orchestrator.md`. They are not in this work order's
  five items. Flagged for a follow-on orchestrator design. The §4.2 surfaced-check
  is written to not depend on `handoff.md` existing yet, so this design is correct
  without them; they make the human-facing surfacing complete.

---

## 9. Open questions for the architect

**OQ-TD-375-01 — gate runner does not exist; who invokes `run_gates.sh`? (BLOCKING)**
The spec (REQ-GATE-NN-15) assumes "the pipeline step that invokes `gates/*.sh`"
exists. It does not — there is no central gate runner today, and the worker
pipeline that would call it (`hos_worker.sh`/`hos_orchestrator.sh`) is itself
specified-but-unimplemented (`UNATTENDED-WORKER-TECH-DESIGN.md` build phase B11).
This design creates `scripts/oversight/run_gates.sh` as the artifact, but **the
caller is unresolved**: today gates are run ad hoc. Without a guaranteed caller,
`gate-results.json` may simply be absent on every step — which, per REQ-GATE-NN-16,
is a COMPLIANCE FAIL on every step (fail-closed, correct, but it blocks the whole
pipeline until the caller is wired). Architect must confirm: (a) is `run_gates.sh`
wired into the worker chain now, or (b) is REQ-GATE-NN-16's "required" predicate
gated on a manifest flag that defaults to *not required* until the worker pipeline
ships? The spec's fail-closed intent argues for (a); pipeline reality may force a
staged (b). **This is the gating question for the coder.**

**OQ-TD-375-02 — testability of an agent-prompt decision rule.**
AC-375-11/12 require tests of evaluator behavior, but the evaluator is an LLM agent
prompt, not a Python function. Architect: confirm whether the deterministic
precondition logic (required-and-absent; composite ≥ 0.78) should be extracted into
a small pure Python helper (e.g. `scripts/oversight/gate_compliance.py`) that both
the evaluator references and the tests call directly — which would make AC-375-11/12
real unit tests rather than agent-harness assertions. This is the cleaner,
more-deterministic design and I recommend it, but it adds a component (C-extra) the
spec did not name, so it needs the architect's sign-off.

**OQ-TD-375-03 — carries OQ-375-ARCH-03 forward (validator determinism).**
The spec left OQ-375-ARCH-03 open: do `prompt_audit_risk.py` /
`hallucination_surface.py` pattern-set updates disqualify them from the
deterministic category? This design treats all validators uniformly via
`blocking_findings:` (so the answer does not change C1–C10), but the architect
should close OQ-375-ARCH-03 so REQ-GATE-NN's "covered" set is unambiguous.

---

## 10. Architect review requested

This design is ready for architect review. The blocking item is **OQ-TD-375-01**
(the gate runner's caller). I will not hand this to the coder until the architect
resolves OQ-TD-375-01 and rules on OQ-TD-375-02 (the extract-a-helper question),
because both change what the coder builds (a wired caller and possibly a new
Python helper component).
