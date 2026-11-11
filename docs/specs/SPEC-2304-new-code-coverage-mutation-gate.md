# Requirements Spec — Issue #2304: CI gate for 80% coverage and 75% mutant score on new files and changed lines

**Document type:** Requirements specification
**Status:** DRAFT. The human rulings of 2026-11-10 on OQ-H1 to OQ-H5 and on the ADR's NQ-1 and NQ-2 are recorded in §2a, and lines changed to apply them carry `[ruled 2026-11-10]`. The rulings of 2026-11-11 on TD-2304 §14 Q4 and Q5 are also in §2a, and their lines carry `[ruled 2026-11-11: Q4]` or `[ruled 2026-11-11: Q5]`. The human confirms them, and approves the §9 structural items, in the PR's CODEOWNER review. Technical design: `docs/v0.7.0/TECHNICAL-DESIGN-2304-new-code-coverage-mutation-gate.md`.
**Issue:** #2304 (milestone v0.7.0 — Quality). Labels stay as they are, `parked` included. This spec changes no labels.
**Sibling (out of scope):** #2305 (v0.7.6, whole-touched-file enforcement, legacy cleanup, converting path-loaded tests). Also related: #1823 (mutmut scope for `scripts/automation/`), #1242 (testability epic), #2219 (verified human ruling mechanism), #1570 (gates are code, not attestation), #1567 (a check is required only once all source passes it), SPEC-375 (deterministic-gate invariant).
**Risk tier (declared for downstream routing):** **HIGH.** This is a new required merge gate. It touches protected surfaces: `.github/workflows/**`, `.claude/agents/**` and `contract/**`.
**Date:** 2026-11-10
**Author:** pm-agent

---

## 1. Problem statement

The HOS unit-test targets are line coverage ≥ 80% and mutant score ≥ 75% (`.claude/agents/unit-test.md:30-31`). Nothing enforces them:

- `.github/workflows/tests.yml` runs `scripts/framework/run_tests.sh` without `--mutation`, so mutation testing never runs in CI.
- Coverage is gated only across the whole suite, at `fail_under = 78` (`pyproject.toml` `[tool.coverage.report]`). It is not checked per file. A new file at 30% passes.
- mutmut's scope is a hand-maintained `source_paths` list. Code outside that list is never mutated.
- Shell has no mutation tool.
- `unit-test.md` and contract §4 accept `Mutant_score_pct: N/A`. Agents have recorded "not run", "N/A (bash)", "N/A (not in source_paths)" and hand-built samples, and those entries passed sign-off.

The human's ruling (2026-11-09): "Stop the bleeding now, fix fully later." From now on, **new code** must meet the targets. A deterministic CI check enforces this, not an agent declaration.

## 2. Binding rulings this spec implements

These rulings were relayed by the human-proxy session as already decided. They are not reopened here. Provenance is noted in §9.

| # | Ruling |
|---|---|
| R1 | Targets are ≥ 80% line coverage and ≥ 75% mutant score. CI code enforces them deterministically; an agent never attests them. There is no N/A path. The only exception is a verified human GitHub ruling that names the file and the reason. Bot or proxy rulings are refused. |
| R2 | Tests for each gated file are selected from coverage contexts (`--cov-context=test`, run under `COVERAGE_CORE=ctrace`) taken from the normal coverage run. Matching on test file names is a fallback only. An empty selection **fails** the gate. |
| R3 | Tests that copy the whole repo (e.g. `tests/automation/test_agent_invoke_wrapper.py`) are never part of a mutation run. The whole suite is never run per mutant. |
| R4 | Path-loaded modules fail closed. If a selected test loads a gated module with `importlib` `spec_from_file_location` under an ad-hoc name, the gate fails. The message names the test file and the fix: convert it to a canonical `scripts....` import in the same PR. There is no exemption list. Converting the existing such tests is #2305. |
| R5 | `mutants/` is deleted before each run, or an equivalent guarantee prevents stale mutants. `.claude/` is never copied. |
| R6 | mutmut 3.8.1: `also_copy` takes directory entries only. The current config (`also_copy=["bootstrap/"]`, plus `retry_rescue_logic.py` and `secret_scan_logic.py` in `source_paths`) is the baseline. |
| R7 | Scope covers new Python files (whole file), changed lines in existing Python files, and files outside `source_paths`. Shell decision logic fails closed. Per-file results go to the check output and the audit log. Cost is bounded by caching and a timeout that fails closed. |
| R8 | `unit-test.md` and the sign-off schema stop accepting "not run" or "N/A" for Python. |

## 2a. Human rulings, 2026-11-10 (FINAL)

These rulings were relayed by the human-proxy session as the human's (ScottThurlow) final rulings. They resolve §10's human questions and the ADR's NQ-1 and NQ-2. Where they conflict with earlier text, they win.

| # | Ruling |
|---|---|
| H1 (OQ-H1) | Shell decision logic fails closed with "move decision logic into tested Python". There is no shell harness. |
| H2 (OQ-H2) | No `# pragma: no cover`, `# pragma: no mutate` or "documented equivalent" added in the PR reduces the counts. The 25% headroom covers real equivalent mutants. `unit-test.md` changes to match. |
| H3 (OQ-H3) | A per-mutant test timeout counts as **killed**. The whole-gate CI timeout still fails closed. |
| H4 (OQ-H4) | Every existing `shell_logic_check.py` exemption applies, including the file-level `bootstrap/hos_bootstrap.sh` exclusion. An edited `if` line counts as added logic. |
| H5 (OQ-H5) | A verified human ruling covers only a named file's coverage and mutation **thresholds**. It does not cover path-load, shell or timeout failures. It is bound to the file's **content** (blob hash), not the head SHA, and is void if the file changes after the ruling. There is no in-gate exception path until S5 (which depends on #2101). A human admin merge is the only override. `contract/gate-suspension.md` does not apply to this gate. |
| NQ-1 | A file with zero gated mutants and gated coverage ≥ 80% needs no test selection, but only if its gated lines contain no decision logic (AST `If`/`For`/`While`/`Try`/`BoolOp`/`Compare`/`IfExp`, or a comprehension with an `if`). Otherwise it fails with "move logic into a function so it can be mutated". Every other empty selection fails. |
| NQ-2 | Unmutatable gated lines (decorated functions, enums) are reported as `unmutatable_gated_lines`. They pass on coverage only if they contain no decision logic, under the same AST definition. Otherwise the file fails with "move the logic into an undecorated helper so it can be mutated". |
| TD-Q4 (2026-11-11) [ruled 2026-11-11: Q4] | `Match` statements count as decision logic. |
| TD-Q5 (2026-11-11) [ruled 2026-11-11: Q5] | Module-level or class-level decision logic on gated lines is **not** coverage-only. It fails with "move the logic into a function so it can be mutated", using the same mechanism and AST definition as NQ-1 and NQ-2. Narrow carve-outs only, and nothing else: (a) `if __name__ == "__main__":` whose body is only a call (e.g. `sys.exit(main())`); (b) `try: import X` / `except ImportError:` fallbacks (import-only `try` bodies and `ImportError` handlers); (c) `if TYPE_CHECKING:`. |

## 3. Definitions

- **PR diff:** the three-dot diff `merge-base(base, head)...head` for the PR's base branch, with git's default rename detection.
- **New Python file:** a `.py` path added by the PR diff that is not a pure rename.
- **Changed lines:** lines added or modified on the head side of the PR diff, in an existing (non-new) `.py` file. Deleted lines are not gated.
- **Gated lines:**
  - for a new file, every executable statement line in the file;
  - for a changed file, the changed lines that are executable statement lines, as coverage.py's statement analysis defines them. Comments, blank lines and docstrings are not executable.
- **Gated file:** any tracked `.py` file with at least one gated line. Excluded paths are `tests/**`, `**/conftest.py`, `mutants/**` and virtualenv directories. This applies **whatever** `[tool.coverage.run] source` and `[tool.mutmut] source_paths` say (R7).
- **Line coverage of a gated file:** executed gated lines ÷ gated lines, measured from the full-suite run on the PR head.
- **Mutant score of a gated file:** killed ÷ total, counting only mutants whose mutated location lies on a gated line. "Killed" means a selected test detected the mutant. A per-mutant timeout also counts as killed (H3) [ruled 2026-11-10]. Every other outcome counts as not killed. That includes survived, no tests, suspicious, skipped and not checked.
- **Gated shell file:** a `.sh` file added or changed by the PR diff.
- **Shell decision logic:** a decision construct that `scripts/oversight/validators/shell_logic_check.py` counts. The gate uses that definition unchanged, including all of its existing exemptions: guard clauses, the flag-parsing loop and the file-level `bootstrap/hos_bootstrap.sh` exclusion. An added or modified line on which a counted construct opens counts as added decision logic, and that includes an edited `if` condition (H4) [ruled 2026-11-10].
- **Verified human ruling:** a GitHub comment or review on the PR that meets all of these:
  - its author is not in `BOT_ACCOUNTS` and is a human CODEOWNER for the file;
  - it names the file path and gives a reason;
  - the gate verified it mechanically.

  This uses the #2219/#2101 mechanism once it lands (slice S5). Until then there is **no** in-gate exception path, and a human admin merge is the only override. A ruling covers only the named file's coverage and mutant-score thresholds. It is bound to that file's content (git blob) at the time of the ruling, and it is void if the file changes afterwards (H5) [ruled 2026-11-10].

## 4. Requirements

### 4.1 Gate identity and enforcement

- **REQ-1.** The gate is deterministic CI code that runs on every `pull_request` to `main` and `release/v*`. The same inputs give the same pass or fail result. No agent output, register entry or LLM verdict feeds into the result.
- **REQ-2.** The gate reports as a single named status-check context, and that context is added to `scripts/framework/hos_required_contexts.txt`. Making it live in branch protection still requires a human to re-run `setup_branch_protection.sh`. This spec does not change that.
- **REQ-3.** The gate has one entry point, shared by CI and local runs, so an agent can run exactly what CI runs before opening a PR. CI must not use a separate code path.
- **REQ-4.** The gate fails closed on every internal error. Examples:
  - the diff cannot be computed;
  - coverage or context data is missing;
  - mutmut exits with an error;
  - results cannot be parsed;
  - an exception verification lookup fails.

  The failure message names the cause. An internal error is never reported as a pass.

### 4.2 Coverage

- **REQ-5.** Each new Python file must have line coverage ≥ 80% across the whole file.
- **REQ-6.** For each changed file, the gated (changed) lines must have line coverage ≥ 80%.
- **REQ-7.** Coverage is measured for every gated file, including files outside `[tool.coverage.run] source`, such as top-level `scripts/automation/*.py` and `bootstrap/*.py`.
- **REQ-8.** The existing suite-wide `fail_under = 78` is not changed. This gate is added alongside it.

### 4.3 Mutation

- **REQ-9.** Each new Python file must have a mutant score ≥ 75% across all mutants in the file.
- **REQ-10.** For each changed file, the mutants on the gated lines must score ≥ 75%. Surviving mutants above 25% fail the gate.
- **REQ-11.** Every gated file is mutated, whether or not it is in `[tool.mutmut] source_paths`. The gate builds its own target list from the PR diff. "Not in scope" is never a pass.
- **REQ-12.** A file whose gated lines produce zero mutants passes only if mutmut ran without error and reported zero mutants on those lines. The record says `mutation_ran: true, total: 0`. Gated lines in code mutmut never mutates (decorated functions, enums) are listed as `unmutatable_gated_lines`. They pass on coverage only if they contain no decision logic. Otherwise the file fails with "move the logic into an undecorated helper so it can be mutated" (NQ-2) [ruled 2026-11-10]. Decision logic on gated module-level or class-level lines fails with "move the logic into a function so it can be mutated". This applies whatever the file's mutant count or selection is. The only exceptions are the three TD-Q5 carve-outs in §2a [ruled 2026-11-11: Q5].

### 4.4 Test selection

- **REQ-13.** For each gated file, the gate selects tests that executed at least one gated line, taken from the coverage-context data of the full-suite run on the PR head (`--cov-context=test`, `COVERAGE_CORE=ctrace`).
- **REQ-14.** Name matching (`test_<module>.py`) is used only when the context selection for that file is empty. The record shows which method produced the selection (`context` or `name_fallback`).
- **REQ-15.** Repo-copying tests are removed from every selection (R3). The record lists which tests were removed. The architect defines how these tests are identified (OQ-A4).
- **REQ-16.** If the selection for a gated file is still empty after REQ-13 to REQ-15, the gate **fails** for that file. The message says no test exercises its gated lines. The one exception (NQ-1) [ruled 2026-11-10]: a file with zero gated mutants and gated coverage ≥ 80% passes without a selection if its gated lines contain no decision logic. If they do contain it, the file fails with "move logic into a function so it can be mutated".
- **REQ-17.** A mutation run never executes the whole suite per mutant. It executes only the selected tests for the file whose mutant is under test.

### 4.5 Path-loaded modules and mutmut hygiene

- **REQ-18.** If a selected test loads a gated module by file path (`importlib.util.spec_from_file_location` or an equivalent loader) instead of by its canonical `scripts....` import, the gate fails for that file. The message names:
  - the test file;
  - the module it loads by path;
  - the fix: "convert to a canonical `scripts....` import in this PR".

  This also covers the mutmut error "tests recorded trampoline hits but none match any mutant key". The gate must turn that error into the same named message, never a raw error and never a pass. There is no exemption list (R4).
- **REQ-19.** Before each mutation run, the gate guarantees that no mutant from an earlier run can affect the result. Either it deletes `mutants/`, or it uses an equivalent mechanism that the architect justifies.
- **REQ-20.** A mutation run never copies `.claude/`.

### 4.6 Shell

- **REQ-21.** If a gated shell file contains shell decision logic that opens on an added or modified line, or its count of shell decision logic is higher at head than at base, the gate fails. The message says "move decision logic into tested Python". Python under `scripts/automation/lib` is the recommended home. There is no shell mutation harness (H1) [ruled 2026-11-10].

### 4.7 Exceptions

- **REQ-22.** The only way past a failing gated file is a verified human ruling (§3) that names that file and a reason. The gate verifies it mechanically and refuses rulings whose author is a bot (including `scottthurlow-claude[bot]` and every `BOT_ACCOUNTS` entry), is not a CODEOWNER, or did not name the file. No other input can suppress a failure:
  - env vars, labels, config flags, or pragmas and "documented equivalent" claims added in the PR (H2) [ruled 2026-11-10];
  - register entries;
  - agent text.

  [ruled 2026-11-10, H5] A ruling applies only to the coverage and mutant-score thresholds. Path-load, shell, timeout and internal-error failures cannot be excepted. A ruling is bound to the named file's content (its git blob), not the head SHA, and is void if the file changes afterwards. Until slice S5 (which depends on #2101) the gate has no exception path at all, and a human admin merge is the only override. `contract/gate-suspension.md` does not apply to this gate.
- **REQ-23.** A file that passes by exception is still measured and recorded in full, along with the ruling's URL and author. "Excepted" is reported as its own outcome, never as "pass".

### 4.8 Records

- **REQ-24.** For each gated file, the gate writes a record containing:
  - path and kind (`new` / `changed` / `shell`);
  - gated line count and coverage % (covered/gated);
  - `mutation_ran` (true/false, with the reason if false);
  - killed/total and mutant score %;
  - selection method and selected test count;
  - removed repo-copying tests;
  - path-load findings;
  - exception (ruling URL or none);
  - outcome (`pass` / `fail` / `excepted`).

  The record also carries PR number, base SHA, head SHA and gate version.
- **REQ-25.** The records are shown in the PR's check output as a per-file table.
- **REQ-26.** The records reach the committed audit log (`audit/log/…`) for every PR the gate evaluated, at least every merged PR. The CI job has `contents: read`, so it cannot commit. The write-back route is OQ-A1. Check output alone does not satisfy this requirement.

### 4.9 Cost bound

- **REQ-27.** Mutation is limited to gated files and gated lines (REQ-9 to REQ-11) and runs only the selected tests (REQ-17).
- **REQ-28.** Results may be cached between runs. A cache hit is allowed only if the gated file's content, every selected test's content and the gate/mutmut version are all unchanged (REQ-19). A cache can never turn a fail into a pass.
- **REQ-29.** The gate has a wall-clock budget below the CI job timeout. On a timeout or budget overrun the gate **fails**. Files that did not finish are recorded with `mutation_ran: false, reason: timeout`, and the message suggests splitting the PR. If the job timeout itself is hit, the context is non-success. Either way, a timeout is never a pass. A per-mutant test timeout is not a gate timeout: it counts as a killed mutant (H3) [ruled 2026-11-10].

### 4.10 Agent definitions and sign-off schema

- **REQ-30.** In `unit-test.md` CORE, for Python:
  - `Mutant_score_pct` must be a number taken from the gate's output;
  - "not run", "N/A", sampled and hand-computed values are not accepted;
  - equivalent mutants are not removed from the denominator, because the 25% headroom absorbs them (H2) [ruled 2026-11-10];
  - `Thresholds_met: true` is allowed only when the gate passed on the current head.

  The PACK-disabled N/A wording stays only for stacks that have no mutation framework, and Python is not one of them.
- **REQ-31.** Contract §4 (test declaration schema), `templates/base-agent-register-examples.md` and `docs/v0.3.0/BASE-AGENTS-SPEC.md` (wherever they show `Mutant_score_pct`) change to match REQ-30.
- **REQ-32.** The oversight-evaluator's Phase 1 `test-unit` check returns COMPLIANCE FAIL if a step that changes Python has a non-numeric `Mutant_score_pct` or `Coverage_pct`.
- **REQ-33.** The worker's unit-test ↔ coder loop iterates against this gate, using the REQ-3 entry point, until it passes. The existing 5-round cap and `test-resistance` escalation are unchanged and stay binding.
- **REQ-34.** Edits to `.claude/agents/**` are written by the top-level session, not the `coder` subagent (CLAUDE.md, #1347). Edits to `.github/workflows/**`, `.claude/agents/**` and `contract/**` get human CODEOWNERS review.

### 4.11 Day-one requirement

- **REQ-35.** The gate only looks at new and changed code, so it passes on `main` by construction. It is marked required from the PR that introduces it (#1567). Its own new Python files must pass it in that PR.

## 5. Acceptance criteria (one test each)

Each AC maps to one automated test in the gate's own test suite. Where a test needs a git repo, it uses a fixture repo it builds itself, never a copy of the real repo.

| AC | Requirement | Test asserts |
|---|---|---|
| AC-1 | REQ-5 | New file at 79% coverage → fail; the same file at 80% → coverage passes (boundary). |
| AC-2 | REQ-6 | Changed lines at 79% → fail, even when the whole file is above 80%. |
| AC-3 | REQ-6 | Changed lines at ≥ 80% → pass, even when the whole file is below 80% (legacy debt is not gated). |
| AC-4 | REQ-9 | New file with a mutant score of 74% → fail; 75% → pass (boundary). |
| AC-5 | REQ-10 | Changed lines whose mutants survive at 26% → fail; survivors on unchanged lines do not count. |
| AC-6 | REQ-11 | New file outside `source_paths` with low kill → fail (it is mutated anyway). |
| AC-7 | REQ-7 | New file outside `[tool.coverage.run] source` is measured; low coverage → fail. |
| AC-8 | REQ-21 | New `.sh` file with an `if/else` → fail, with the "move to Python" message. A new `.sh` file containing only a guard clause or the flag-parsing loop → no shell failure. |
| AC-9 | REQ-21 | Changed `.sh` file adding a `case` → fail; a changed `.sh` file whose diff touches no decision logic → no shell failure. |
| AC-10 | REQ-29 | Mutation budget exceeded → fail; the record shows `mutation_ran: false, reason: timeout`. |
| AC-11 | REQ-16 | Gated file with no executing tests and no name-fallback match → fail ("no test exercises"). |
| AC-12 | REQ-14 | Context selection empty but `test_<module>.py` exists → name fallback is used and recorded as `name_fallback`. |
| AC-13 | REQ-13 | Selection includes only tests whose contexts executed gated lines. A test that never touches the file is not selected. |
| AC-14 | REQ-15 | A repo-copying test that covers the file is removed and listed. If it was the only test → fail (via REQ-16). |
| AC-15 | REQ-17 | During a mutation run, the tests executed are exactly the selected set. The full suite is not run. |
| AC-16 | REQ-18 | Selected test loads the module with `spec_from_file_location` → fail; the message names the test file, the module and the canonical-import fix. |
| AC-17 | REQ-18 | mutmut "trampoline hits but none match any mutant key" output → translated into the AC-16 message, not a raw error or a pass. |
| AC-18 | REQ-19 | A stale `mutants/` tree from an earlier run, with different source, does not affect the result. |
| AC-19 | REQ-20 | The mutation workspace contains no `.claude/` path. |
| AC-20 | REQ-22 | Ruling from a CODEOWNER human naming the file and a reason → `excepted`. The same ruling from a bot, from a non-CODEOWNER, or without the file name → still fail. |
| AC-21 | REQ-22 | An env var, label or config flag added by the PR cannot turn a failing file into a pass. |
| AC-22 | REQ-23, REQ-24 | Each record contains every REQ-24 field. An excepted file is recorded with its ruling URL and outcome `excepted`. |
| AC-23 | REQ-25 | Check output contains a per-file table with coverage, score and killed/total. |
| AC-24 | REQ-26 | The audit-log record for an evaluated PR has the REQ-24 fields. The route is set by OQ-A1. |
| AC-25 | REQ-28 | A cache hit when the selected test changed → re-run, not reuse. A cache can never produce a pass for content that previously failed. |
| AC-26 | REQ-4 | Each injected internal error (missing coverage data, mutmut crash, unparseable results, failed ruling lookup) → fail with the cause named. |
| AC-27 | REQ-12 | Gated lines that produce zero mutants after a clean mutmut run → pass, recorded `total: 0`. A mutmut error → fail. |
| AC-28 | all | A PR meeting every target → the gate passes. |
| AC-29 | REQ-1 | Running twice on identical inputs gives the same outcome and records (apart from timestamps and durations). |
| AC-30 | REQ-3 | The CI workflow invokes the same entry point as the local run (static test on the workflow file). |
| AC-31 | REQ-2 | The gate's context name is in `hos_required_contexts.txt` and equals a workflow job `name:` (extends `test_branch_protection_contexts.py`). |
| AC-32 | REQ-30, REQ-31 | `unit-test.md` CORE and contract §4 contain no wording that allows "not run" or N/A for Python (static test). |
| AC-33 | REQ-32 | An evaluator fixture register with `Mutant_score_pct: not run` on a Python step → COMPLIANCE FAIL (static or behavioural check on `oversight-evaluator.md`, per the existing agent static-test pattern). |
| AC-34 | REQ-35 | The gate run on the introducing PR's own new files passes. On a no-op diff, the gate passes with zero gated files. |

## 6. Out of scope

- Whole-touched-file enforcement, legacy coverage and mutation cleanup, raising the suite-wide `fail_under`, and measuring defect escape against mutant score: **#2305**.
- Converting the existing test files that path-load modules to canonical imports: **#2305**. Until that happens, a PR that changes a module tested only that way must convert those tests in the same PR (REQ-18).
- Widening `[tool.mutmut] source_paths` for `scripts/automation/` (#1823). The gate does not depend on it (REQ-11).
- Building a shell mutation harness. Shell decision logic simply fails closed (REQ-21, OQ-H1).
- Shipping this gate to consumer projects through `hos_install.sh` or packs. This is a HOS-repo required context only. The CORE `unit-test.md` and contract §4 wording changes do ship, because they are CORE.
- The general #2219 human-ruling mechanism itself. This gate only uses it.
- Re-running `setup_branch_protection.sh`, which is a human action.
- Changing the labels on #2304.

## 7. Constraints carried from the repo

- mutmut is pinned at 3.8.1. `also_copy` takes directories only.
- The full suite takes about 15 minutes. The existing `tests` job has `timeout-minutes: 30`.
- The `pull_request` trigger uses a read-only token. The project-requirements install stays skipped (`HOS_SKIP_PROJECT_REQUIREMENTS=1`, #1380).
- SPEC-375 applies: no synthesis layer may treat an LLM verdict as resolving this gate's failure.

## 8. Self-flag

```
RISK: HIGH — new required merge gate; edits CORE agent text and the contract schema; protected surfaces.
CONFIDENCE: MEDIUM — requirements trace to the issue and the relayed rulings; §10 lists the remaining gaps that change pass/fail behaviour.
Change classification: structural (new required gate; removes the N/A option for Python from CORE unit-test.md and contract §4).
```

## Human Review Required

- §9: confirm the provenance of R1–R8 and approve the structural changes (REQ-30 to REQ-32 remove an existing allowed value from CORE and the contract).
- §10 OQ-H1 to OQ-H5 change pass/fail behaviour and need human rulings.

## 9. Approval and provenance

R1–R8 reached pm-agent through the human-proxy session, which described them as binding human rulings. The issue body records the 2026-11-09 "stop the bleeding" ruling attributed to the human. Under pm-agent CORE, an agent message is not human approval. This spec therefore stays **DRAFT** until the human confirms R1–R8 and approves the structural items. No spec or agent file other than this new document has been edited.

## 10. Open questions

### For the human (these change pass/fail; pm-agent does not decide them)

> **All five are RULED 2026-11-10.** See §2a: OQ-H1 → H1 (move to Python), OQ-H2 → H2 (no pragma or equivalent reduces the counts), OQ-H3 → H3 (timeout = killed), OQ-H4 → H4 (every exemption applies; an edited `if` counts), OQ-H5 → H5 (thresholds only; blob-bound; no exception path until S5; admin merge only; gate-suspension does not apply). The questions below are kept as history.

- **OQ-H1 — Shell path.** Decide between "move to Python" and a shell mutation harness. Recommendation: Python. Until it is decided, REQ-21 fails closed.
- **OQ-H2 — Exclusion pragmas.** Can `# pragma: no cover` or `# pragma: no mutate` on gated lines remove those lines from the coverage or mutant counts?
  - pm-agent's reading of R1 ("no N/A path") is that pragmas added in the PR on gated lines must be ignored, and only a verified ruling excludes code.
  - Pre-existing pragmas on unchanged lines are unaffected.
  - The same applies to `unit-test.md`'s "documented equivalent mutant" exclusion: the gate cannot verify equivalence, so is the denominator all mutants (the 25% slack absorbs equivalents), or is there a ruling-backed path?
- **OQ-H3 — Per-mutant timeouts.** Does a mutant that makes the tests time out count as killed (mutmut's convention) or not killed? This spec currently leaves it undefined.
- **OQ-H4 — Shell scope details.**
  - Confirm that the existing `shell_logic_check.py` exemptions (guard clause, flag-parse loop, `hos_bootstrap.sh`) apply to this gate.
  - Confirm whether *editing* an existing decision line (e.g. changing an `if` condition, with no new construct) counts as "adding decision logic". REQ-21 as drafted fails it.
- **OQ-H5 — Exception scope.**
  - Does a verified human ruling (REQ-22) also apply to the path-load (REQ-18), shell (REQ-21) and timeout (REQ-29) failures, or only to the coverage and score thresholds? R4 says "no exemption list"; this spec applies the per-file ruling to all of them.
  - Does the existing `contract/gate-suspension.md` mechanism apply to this gate? The current `tests` job names it as that gate's only override.
  - Is a ruling tied to a head SHA, or does it survive later pushes?

### For the architect (how, not what)

- **OQ-A1 — Audit write-back.** The CI job has `contents: read` and cannot commit. How do the REQ-24 records reach `audit/log/`? For example, as a CI artifact that the overseer or the merge path ingests. The same gap is already noted for retry-rescue events in `tests.yml`.
- **OQ-A2 — Workflow placement.** Should this gate extend the `tests` job, reusing its full-suite run with contexts enabled, or be a separate job that consumes that run's coverage data? Note the ~15 min suite, the 30 min job timeout, and that `ctrace` is slower than `sysmon`.
- **OQ-A3 — Mapping mutants to lines.** How are mutmut 3.x mutant keys mapped to source lines, so that mutants can be restricted to gated lines and files outside `source_paths` can be targeted without editing `pyproject.toml` per PR?
- **OQ-A4 — Repo-copying tests.** How are they identified deterministically (a reviewed marker or list, or detection)? Who maintains it, and does it count as a protected surface?
- **OQ-A5 — Path-load detection.** Should it be static, by scanning selected tests for path loaders that target gated files, or rely on mutmut's error, or both? REQ-18 requires the named message in either case.
- **OQ-A6 — Mutant cleanup and cache.** Choose between deleting `mutants/` and an equivalent guarantee, and design a cache key that satisfies REQ-19 and REQ-28 together.
- **OQ-A7 — Ruling verification.** How does CI verify rulings: reuse `scripts/oversight/codeowners.py` and `BOT_ACCOUNTS`, and what read permissions does the workflow need? How does it switch over to #2219 when that lands?
- **OQ-A8 — Wall-clock budget.** What is the concrete REQ-29 budget, and how does it relate to the job's `timeout-minutes`?
