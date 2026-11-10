# Finding: A Quality Target That No Code Executes Decays Silently

**Role:** oversight-mechanism. HOS adopted mutation testing in its first week, with explicit targets. Five months later, mutation testing could not run in the repository **at all**, and nothing had noticed. The cause was not one bug. **The target lived in an agent's instructions, and nothing executed it.** Every breakage that followed was invisible, because no step ever failed when the target was missed. The fix is structural: the target becomes a required, deterministic CI check, run by code. An agent's own run of a check is a rehearsal, never the authority.

**First observed:** 2026-11-09 (the human asked whether there was any evidence the mutation and coverage targets were helping) and 2026-11-10 (the Mutant Builder session's smoke test found mutmut running 0 of 0 mutants). Issues: #2304, #2305, #2310.

---

## What happened

| Date | Event |
|---|---|
| 2026-06-12 | pytest and mutmut added to the repo (`5ef33486b`): 248 tests, 80.37% coverage. |
| 2026-06-14 | The `unit-test` agent ships with the targets **coverage ≥ 80%, mutant score ≥ 75%**. It calls them "gates — the build does not advance until they are met" (`.claude/agents/unit-test.md`). The human set them from professional experience. |
| v0.6.0 | #1083: mutmut **crashed** in both venvs, because pinned config keys no longer matched the drifted mutmut 3.6.0 install. Fixed. |
| v0.6.0 / v0.7.6 | #1174, #1256: the measured surface **silently excluded** the most important modules: `merge_authority.py`, all of `scripts/framework/`, and `require_human_approval.py` at 48%. #1167: shell decision logic escapes coverage and mutation entirely. |
| 2026-09-01 | CI's `tests.yml` lands (#1244). It runs coverage (suite-wide `fail_under = 78`) and **deliberately leaves mutation out**: "mutmut re-runs the full suite per mutant and is far too slow for a per-PR gate". |
| 2026-10-09 / 10-21 | Test-hygiene work (#2061, #2140) makes `tests/conftest.py` and the test-hygiene helpers load `bootstrap/` modules. mutmut copies only its `source_paths` and `tests/`, so test collection now crashes in mutmut's sandbox. **From here on, mutation testing cannot run in this repo.** Nothing fails, because nothing runs it. |
| to 2026-11-09 | **71** `Mutant_score_pct` declarations in the worker's sign-off registers, mostly "not run", "N/A (bash)", "N/A (not in source_paths)", or a hand-built sample ("9/11 hand-built mutants"). One full run (76.8%). Entries below 75%, or never run, **passed sign-off**. No record links a surviving mutant to a code fix. |
| 2026-11-09 | Audit: no evidence either way that the targets help, and no measurement in place. The human rules: "stop the bleeding now, fix fully later". |
| 2026-11-10 | The Mutant smoke test runs mutmut on one small module: **0 of 0 mutants**, `FileNotFoundError` on `bootstrap/lib/hos_tmp_root.py`. Getting it running then exposes the deeper gap: **37 test files load the module they test by file path** (`spec_from_file_location`), and mutmut cannot follow those modules. They include `change_classifier`, `second_review_logic`, `panel_logic`, `validation_logic` and all three merge gates (`require_human_approval`, `require_overseer_approval`, `require_tier_ceiling`). **The code that decides every merge has effectively never been mutation-tested.** |

## Why it went amiss

1. **The target was prose, not a check.** "Mutant score ≥ 75%" was an instruction to an agent, not code that fails a build. An instruction can be met, partly met, or reported as met, and all three look the same downstream.
2. **The agent that ran it also reported it.** `unit-test` decided whether to run mutation, ran it (or a hand-built sample), and wrote the score into the sign-off register. Nothing re-executed it. Self-reporting replaced execution, and the score field accepted "N/A" or "not run" as answers. This is the pattern in `attestation-displaces-the-execution-it-attests-to.md`.
3. **The expensive check was the one left out of CI.** Excluding mutation from `tests.yml` because it was slow was a reasonable local decision. Its effect was that the one place a check runs on every PR never saw the target, so the target had no authority at all.
4. **Nothing executing it meant nothing noticed it break.** The #1083 crash, the scope exclusions, and the October `bootstrap/` dependency each broke or narrowed mutation testing silently. A check that runs on every PR would have gone red the day each one landed. One that runs only when an agent chooses never goes red. It just stops being chosen.
5. **The scope was a hand-kept list.** `[tool.mutmut] source_paths` named files one by one. New code outside the list (#1823: all of `scripts/automation/`) was never in scope, and no step said so.
6. **The tests were written in a way the tool could not follow.** Loading modules by path is a reasonable test technique, but it hides those modules from mutmut. Because mutation never ran, no feedback ever pushed the tests toward standard imports. The most critical modules are the ones written that way.

## How this leads to CI/CD and deterministic orchestration

The human's response, 2026-11-09 and 11-10:
- **The target becomes a required CI gate, run by code (#2304, v0.7.0).**
  - New files must meet 80% coverage and 75% mutant score across the whole file, and changed lines in existing files must meet the same targets.
  - The gate computes its own scope from the diff, so a hand-kept list cannot hide code.
  - There is no N/A path: the only exception is a verified human GitHub ruling naming the file.
  - A timeout, an empty test selection, or a module mutmut cannot follow all **fail closed**.
  - It is scoped to new and changed code, so `main` passes on day one and the gate can be required immediately. That is the deterministic-check transition: exists → all-source clean → required.
- **"Fix fully later" (#2305, v0.7.6):** every touched file must meet the targets across the whole file, the legacy code gets cleaned up (including converting the 37 path-loading test files), and **the targets get measured**: defects that escape after merge, compared with the module's score at merge.
- **"The real testing is CI/CD and overseer" (#2310).** An agent's own test runs exist to avoid needless cycles, and carry no authority. CI and the overseer's independent re-execution are the authorities, and the human's approval comes after them.
- **Deterministic orchestration (`llms-belong-inside-deterministic-orchestration.md`).** The model writes tests and interprets surviving mutants; code decides whether the target was met. The first job of the build session (an interactive session in a dedicated clone, as a deliberate exception to bucket order) was to make mutation run at all. Its smoke test, run before any work, is what surfaced the 0-of-0 result.

## Not an isolated case: the same pattern across HOS

Mutation testing is one instance of a recurring failure: **a control that exists in prose, or is reported by the actor it constrains, instead of being executed by code.** Each case below was fixed the same way, by moving the decision into deterministic code and having a model, at most, interpret the result. AGENTS.md records the general rule ("Use the Code, Don't Roll It Yourself"): every gate implemented as executing code has worked, and every gate specified only in prose has either never fired or fired inconsistently.

| Case | What was prose or self-reported | Finding or issue |
|---|---|---|
| **The merge-authority matrix** | Agents *narrated* `merge_authority.py`'s decision instead of executing it. The matrix had likely never run. | #1357; `llms-belong-inside-deterministic-orchestration.md` |
| **Validation stamps** | CI checked that a local validation *stamp* existed, not that the checks ran. The attestation slot read as the verification slot, so checks that could have run in CI never moved there. | `attestation-displaces-the-execution-it-attests-to.md`, `stamp-based-ci-enforcement.md`; #2053, #1536 |
| **Self-reported reviewer verdicts** | A reviewer's JSON listed blocking findings, but was tagged `approve`, and exited 0. | `gate-on-computed-signal-not-self-reported-verdict.md` |
| **"Second review passed" with no reviewer run** | A skipped verdict read as a pass at HIGH tier. | #1750 |
| **The actor classifying its own change** | Whether a human saw a change was decided by the actor's own classification. | `self-classification-cannot-gate-the-human-boundary.md` |
| **A skipped reviewer** | "Found nothing", "never invoked" and "skipped by a bug" looked identical. | `explicit-na-audit-entries.md` |
| **The orchestrator doing the work itself** | A bypassed pipeline looked reviewed. | `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` |
| **An LLM summary over a scanner** | A plausible "this is fine" masked a deterministic scanner failure. | `llm-reviewer-can-mask-deterministic-scanner-failures.md` |
| **A verification item handed to the human** | The worker's own "verify against real output" item went unrun until the human-proxy executed it, after every lane had approved a gate that failed on real data. | `real-data-not-reviewer-diversity-caught-the-bug.md`; #2268, #2269 |
| **Live-host behaviour** | Environment-dependent checks had no category, so they were optional by construction. | `system-tests-run-on-the-real-host-by-code-not-by-agents.md`; #2289 |
| **An outside contributor's "152 tests pass"** | Tests derived from the issue's own examples passed, and the class broke. | `an-outside-contribution-implements-the-examples-not-the-class.md` |
| **Policy without a mechanical signal** | A closed policy enforced only by remembered discipline. | `shell-as-launcher-not-logic-container.md`, `unenforceable-rules-need-verification-mechanisms.md` |

The shape is the same every time. The control **existed**, a document or field **said it passed**, and nothing **executed** it. The response is also the same every time: code runs the check at a fixed pipeline point, the authority re-executes it independently (CI, the overseer), and the model proposes or interprets but never decides whether the check happened.

## Implications for research

1. **A quality target with no executing check should be counted as absent, not weak.** Five months of declared targets produced no measurement, a silently broken tool, and the most critical code untested. Its stated status ("gate") and its real status ("not run") had diverged completely, and only an audit found it. That makes it a governance hole, not a quality preference.
2. **Expensive checks need a cheap, always-on form, or they end up never run.** Dropping a slow check from CI entirely is the decision that let every later breakage go unnoticed. Scoping it (mutating changed lines only, selecting tests per mutant) keeps it on every PR.
3. **When a check is never run, it breaks without anyone seeing.** Each breakage here (config drift, scope, dependencies, test style) would have been a one-day red build under CI. Under attestation, each one added months of silence.
4. **Self-reported scores must not gate.** This is the test-side instance of `gate-on-computed-signal-not-self-reported-verdict.md`. A sign-off field that accepts "not run" is a field that will say "not run".
5. **Ask for evidence of a check's value, then build the measurement.** The human's question ("do we have data that it helps?") exposed the hole. The answer (no data, because it never ran) is the case for making measurement part of the gate itself.

## Related findings

- `attestation-displaces-the-execution-it-attests-to.md`: self-reported scores replaced execution
- `gate-on-computed-signal-not-self-reported-verdict.md`: the sign-off field accepted "not run"
- `unenforceable-rules-need-verification-mechanisms.md`: a prose target with no verifier
- `a-decision-records-intent-not-enforcement.md`: the targets recorded intent; nothing enforced them
- `tooling-drift-in-validation-pipelines.md`: #1083, config drift broke the tool
- `a-guard-that-doesnt-halt-is-not-a-guard.md`: a "gate" that never stops the build
- `llms-belong-inside-deterministic-orchestration.md`: the structural response
- `system-tests-run-on-the-real-host-by-code-not-by-agents.md`: the same principle for live-host tests
- The cross-referenced cases in "Not an isolated case" above: `stamp-based-ci-enforcement.md`, `self-classification-cannot-gate-the-human-boundary.md`, `explicit-na-audit-entries.md`, `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md`, `llm-reviewer-can-mask-deterministic-scanner-failures.md`, `real-data-not-reviewer-diversity-caught-the-bug.md`, `an-outside-contribution-implements-the-examples-not-the-class.md`, `shell-as-launcher-not-logic-container.md`
