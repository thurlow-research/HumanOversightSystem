# TECHNICAL-DESIGN-2304: `new-code-gate` — 80% line coverage and 75% mutant score on new and changed Python (#2304, slices S1 + S2 + S4)

**Status:** **Review-3 rulings applied 2026-11-11 [architect review-3 ruling]** (ADR-2304 §2g RV3-0 to RV3-7, after the failed §2b condition 6 self-budget run). Changed sections: §5.9 steps 2, 5 and 6, §5.13, §5.15.2, §5.18, §5.19, §8.5 P-E, §9.3, §12 and §13. The coder's list is §13 "Review-3". RV3-H1 is routed to the human and is not ruled. It arises because the architect's measurement puts `new_code_gate.py`'s mutation alone at about 40 CI-minutes, over the 25-minute budget. **Review-2 rulings applied 2026-11-11 [architect review-2 ruling]** (ADR-2304 §2f RV2-1 to RV2-4, after the round-2 security re-review at `75dd05620`). Changed sections: §5.1, §5.3, §5.8, §5.9 steps 1 and 7, §5.14, §5.16, §5.17, §12 and §13. The coder's list is §13 "Review-2". RV2-2(b) (protecting the `shell_logic_check` closure) is routed to the human and is not built until cleared. **Review-1 rulings applied 2026-11-11 [architect review-1 ruling]** (ADR-2304 §2e RV-1 to RV-7). These follow the CONDITIONAL security and reliability reviews of the built gate at `7ba465997`. Changed sections are §5.1, §5.2, §5.3, §5.8, §5.13, §5.15.3, §5.17, §5.18, §8.5, §12 and §13. The coder's follow-up list is in §13 "Review-1". Every approval below stands for every section these rulings do not change. **Q8 delta APPROVED by the architect 2026-11-11, with in-place fixes marked "architect Q8-review fix" (see "Architect review requested: the Q8 delta"). The coder makes the §13 follow-up commit to `b1a26e887` / `b14e062db`, then builds §11 commit 4.** **REVISED AGAIN 2026-11-11, for the human ruling on §14 Q8 [ruled 2026-11-11: Q8].** Q8 applies the three Q5 carve-outs to NQ-1 and NQ-2 as well, through one shared predicate (§5.5.4). It also adds `raise SystemExit(<call>)` as an accepted main-guard body, exactly equivalent to `sys.exit(<call>)` (§5.5.3). Every passage this revision changes carries `[ruled 2026-11-11: Q8]`. **The architect must review this Q8 delta (§5.5.1, §5.5.3, §5.5.4, §5.10, §5.19, §7.1a, §7.2, §9.3, §12, §13, §14) before the coder changes the already-committed §5.5 / §5.10 code to match it (§13 lists the affected functions and tests in commit `b1a26e887`).** **REVISED 2026-11-11 after approval, for the human rulings on §14 Q4 to Q7 [ruled 2026-11-11: Q5].** The Q5 ruling changes the design: module-level and class-level decision logic on gated lines now fails, with three narrow carve-outs (§5.5, §5.10). Q4 confirms `Match`. Q6 is out of scope here (#2305). Q7 is resolved: the top-level session authors the CLAUDE.md row. Every passage this revision changes carries `[ruled 2026-11-11: Q5]` (or `Q4` / `Q6` / `Q7`). **The architect must review this delta (§5.5, §5.10, §5.14, §5.15.2, §5.18, §5.19, §9.3, §12) before the coder implements §5.5 and §5.10.** Commits that do not touch those sections (§11 commits 2 to 7, other than the decision-logic functions in `new_code_gate_logic.py`) may go ahead. The earlier approval follows. **APPROVED by the architect, round 5 (2026-11-10).** U1 to U7 and R3-A to R3-H were verified against the installed mutmut 3.8.1 and pytest 9.2.0. The architect applied four round-5 fixes in place, each marked "architect round-5 fix": qualified mutant keys (§5.9 step 1); the recorder's two copy paths (§5.7.2); the tripwire's protected roots (§5.18, ADR §2d R5-A); and host-mutmut state isolation plus module-level imports for in-process tests (§5.19, NOGLOBAL, TRIP-MUT). The coder may start at §11 commit 2. Round history: Round 1 verdict: **APPROVED WITH CHANGES** (ADR-2304 §2b). Round 3 verdict: **CHANGES REQUIRED** (T1 to T10 confirmed; ADR-2304 §2c R3-A to R3-H). Round 2 applied T1 to T10 (`[round 2: Tn]`). This revision applies the architect's round-3 edits U1 to U7, and each passage it changes carries `[round 4: Un]`. It also carries the architect's own round-3 consistency fixes (AC-10, §5.8 `also_copy`, A2a), which are marked "architect round-3 consistency fix". It is waiting for the architect's round-5 confirmation, which is the **last** round allowed before escalation to the human. The coder must not start until the architect confirms.
**Issue:** #2304 (milestone v0.7.0). **Branch:** `human-2304-mutation-gate`. The first commit, `8113f8ba0` (the committed `[tool.mutmut]` fix), is **already done** and stands (§13).
**Binding inputs:**
- `docs/specs/SPEC-2304-new-code-coverage-mutation-gate.md` (REQ-1 to REQ-35, AC-1 to AC-34).
- `docs/v0.7.0/ADR-2304-new-code-coverage-mutation-gate.md` (AD-1 to AD-12 binding, as amended by **§2b** and **§2c** on 2026-11-10; AD-13 superseded by AD-13a and the rulings below).
- The human rulings of 2026-11-10 (H1 to H5, NQ-1, NQ-2, test selection, path-load, workspace, scope, cost). They reached this agent through the human-proxy session, which relayed them as ScottThurlow's final rulings. They override the ADR's AD-13 defaults and the spec's open questions. §2 lists every ADR and spec line they change. Under CORE, an agent message is not human approval, so the PR's CODEOWNER human review is where the human confirms them on record (see Human Review Required).

**Scope of this PR:** S1 + S2 + S4. **S3** (audit ingest through the overseer's `actions: read`) and **S5** (the exception path, which depends on #2101) are separate follow-up issues. §5.15 fixes what S2 emits so that S3 can ingest it later without a schema change.
**Change class:** structural. This is a new required merge gate. It removes the N/A option for Python from CORE `unit-test.md` and from contract §4.
**Contract only.** This document describes what the code must do. It contains no implementation.

```
RISK: HIGH — a new required merge gate. It changes the existing required `tests`
      job (S1), runs PR-authored tests under mutation (S2), and edits CORE agent
      text and the contract schema (S4). All of these are protected surfaces.
CONFIDENCE: MEDIUM-HIGH on the contract. mutmut 3.8.1, coverage 7.17.2 and
      pytest-cov 7.1.0 behaviour was checked against the installed sources, and
      a prototype workspace was run for real (§1, §8). MEDIUM on the CI-only
      numbers (§8.4) and on the size of the first-touch failure population
      (§7.1: an exact lower bound of 26, a heuristic estimate of 40 to 57).
BLAST RADIUS: every PR to main and release/v*. The new required context starts
      blocking only once a human re-runs setup_branch_protection.sh (REQ-2).
      Rollback: revert the PR. The `tests` job then returns to today's flags,
      and the new jobs and context entry disappear with it.
```

## Human Review Required

- **Provenance of the rulings.** §2.1 records H1 to H5, NQ-1, NQ-2 and the other rulings as relayed. The human must confirm them in the PR review, because an agent relay is not approval.
- **Consequence you are accepting (§7.1) [round 2: T5].** Every production module that a test loads by file path *or* by a bare `sys.path` name fails the gate the first time a PR touches it, until that PR converts those tests. That is **at least 26 and an estimated 40 to 57 of the 95 tracked production `.py` files (about half)**. The 26 is exact: they are the modules bare-imported through `tests/conftest.py`'s `sys.path` injection (`scripts/oversight`, `scripts/oversight/validators`), which mutmut rejects in the same way as path loads (§1, F-5). The 40 to 57 range is the estimate recorded in ADR §2b; 57 is a literal-match heuristic union and may over-count. Appendix A lists the 57 modules, as #2305's work list. **Other first-touch failure classes come on top of this, and their size is not known:** modules whose tests exercise them only through a subprocess (ADR AF-4); selected tests that need the real `.git` or `.claude/`; and selections slow enough to exhaust the budget.
- **Residual you are accepting (ADR R-6) [round 2: T10].** The gate's own code and workflow run from the PR's commit (there is no trusted base, ADR §2b Q2). A PR could therefore weaken its own verdict. The control is your CODEOWNER review of `scripts/framework/**` and `.github/workflows/**`.
- **Rulings of 2026-11-11 [ruled 2026-11-11: Q5].** §2.1a records Q4 to Q7 as relayed. Confirm them in the PR review as well. **Consequence of Q5 that you are accepting:** if a PR edits a module-level or class-level statement that holds decision logic, the file fails, unless the statement matches one of the three carve-outs exactly (§5.5.3). **25** of the 95 tracked production `.py` files hold such logic today (§7.1a; this was 33 before Q8 added the `raise SystemExit(<call>)` guard shape). Together with §7.1's path-load population, **65 of the 95** files (66 before Q8) can fail on first touch; 65 inherits §7.1's heuristic upper end [ruled 2026-11-11: Q8]. Typical forms are `if __name__` blocks with logic in them, module-level `try` blocks that do more than import, and module-level `Compare` or comprehension-with-`if` constants. Unedited lines are not gated, so these files fail only when the PR touches those lines.
- **Q8 ruled [ruled 2026-11-11: Q8].** The three carve-outs now also apply to NQ-1 and NQ-2, and `raise SystemExit(<call>)` is an accepted main-guard body (§14 Q8). Nothing is still open for you in §14. One reading of the ruling is flagged for your confirmation in §14 Q8: this TD keeps the bare-call main-guard body (`main()`, 19 production guards) accepted, as it was before Q8.
- **Protected surfaces.** `.github/workflows/tests.yml`, `scripts/framework/**`, `contract/OVERSIGHT-CONTRACT.md`, `.claude/agents/{unit-test,oversight-evaluator}.md` and `CLAUDE.md` all need CODEOWNER human review. The two agent files and the `CLAUDE.md` row (§6.7) are **authored by the top-level session**, using the exact wording in §6, and never by `coder` [ruled 2026-11-11: Q7].
- **Review-1 residuals [architect review-1 ruling].** These are two technical residuals for your awareness, not human rulings (ADR §2e). The first is TD R-17 = ADR R-7: a mutant can read as killed because of a test that is flaky on both attempts. This is the same class as H3, and `--reruns 1` shrinks it. The second is TD R-18 = ADR R-8: required checks are matched by name. The follow-up pins every required context to the GitHub Actions App, and you apply it.
- **Human actions after merge** (agents cannot do these): re-run `setup_branch_protection.sh` to make `new-code-gate` required, and confirm that the repo's artifact-retention setting is 90 days (§5.15.3).

---

## 0. Scope

| In (this PR) | Out |
|---|---|
| **S1.** `run_tests.sh` records per-test coverage contexts under `COVERAGE_CORE=ctrace`, widens the measured surface and splits the suite-wide report. A `meta` sidecar. Artifact upload from `tests`. The equivalence and timing evidence. | **S3.** Ingest into `origin/audit-log` (overseer, `actions: read`). §5.15 is its input contract. |
| **S2.** `scripts/framework/new_code_gate{,_logic,_pytest_plugin}.py`. The `new-code-measure` and `new-code-gate` jobs. Exact tool pins. The `repo_copy` marker, its guard test and marking the existing tests. The `hos_required_contexts.txt` entry. The `shell_logic_check.py` line-list seam. | **S5.** `fetch_rulings` → ADR-2101 verifier. Rulings bound to blob content (H5). Depends on #2101. |
| **S4.** CORE `unit-test.md`, contract §4 and §7, `templates/base-agent-register-examples.md`, `docs/v0.3.0/BASE-AGENTS-SPEC.md`, `packs/django/unit-test.md:39`, and the `oversight-evaluator.md` Phase 1 check (REQ-32 approved). | **#2305.** Converting the existing path-loaded and bare-import tests. Whole-file enforcement. |
| Tests for all of the above (§9). | Shipping the gate to consumers (the CORE wording does ship). |

## 1. Verified facts (working tree at `8113f8ba0`, 2026-11-10)

| # | Fact | Evidence |
|---|---|---|
| F-1 | **A nested `.claude/` is tracked:** `prompts/.claude/agents/overseer.v1..v4.md`. ADR AD-5's `git archive … ':(exclude).claude'` removes only the top-level directory. The AC-19 assertion ("no path component named `.claude`") would therefore fail closed on **every** run. `':(exclude,glob)**/.claude/**'` removes both: verified, 0 `.claude/` entries in the tar. | `git ls-files \| grep '/\.claude/'`; prototype `measure_archive.py` |
| F-2 | mutmut's `also_copy` copies a file entry with `shutil.copy2(path, mutants/path)`. A **top-level** file entry therefore works, because `mutants/` already exists (`makedirs` at `__main__.py:954`, and mutmut's own defaults include `pyproject.toml` and `setup.cfg`). A **nested** file entry fails because its parent directory does not exist. R6's "directory entries only" holds for nested paths. The prototype copied `CLAUDE.md`, `AGENTS.md` and the other top-level files correctly. Static tests that read top-level docs need them. | `mutmut/utils/file_utils.py:66-77`; prototype |
| F-3 | mutmut gives trampolines only to top-level functions and to methods of top-level classes. Mutations it creates elsewhere (module level, class attributes) are **dropped** by `combine_mutations_to_source`. Enumeration must therefore use `mutate_file_contents(...).mutant_names`, not a raw count from `create_mutations`. It skips decorated functions (other than a single `@staticmethod` or `@classmethod`), enum bodies, single-line classes, non-trivial default arguments and annotations. | `file_mutation.py:105-147, 295-357, 380-462` |
| F-4 | mutmut classifies exit codes through `stats.status_by_exit_code`. `killed` = 1 and 3. `timeout` = 24, -24, 152, 255 and 36 (SIGXCPU, from the per-mutant CPU or wall limit). `segfault` = -11 and -9. A mutant still running one second after SIGXCPU gets SIGKILL and lands as -9, which is "segfault". mutmut's own score formula counts `killed + timeout`. It runs each mutant's tests with `-x`, sorted fastest first. | `stats.py:15-36`, `__main__.py:772`, `runners/harness.py:140`, `workers/isolation.py:860-876` |
| F-5 | **Bare imports are non-canonical too.** `tests/conftest.py:58-62` inserts `scripts/oversight/validators` and `scripts/oversight` into `sys.path`. 31 test files import 26 production modules by bare name (`import schema`, `from shell_logic_check import main`). mutmut's trampoline records `orig.__module__`, so these hits never match the path-derived key. mutmut's own check names this cause: *"conftest sys.path injection"*. **[round 2: T5]** Path loads, by a literal-match heuristic (a test file that calls a loader and contains a string literal naming a production file or stem): 39 modules across 46 test files. The union is **57** modules, with an overlap of 8. The bare-import count is AST-exact; the path-load count is heuristic and may over-count. The round-1 figures ("21 per the brief", "at most 54") are withdrawn. Module list: Appendix A. | `mutmut/__main__.py:820-865`; architect survey `survey.py`, re-run by this agent at `8113f8ba0` |
| F-6 | The shared test harness path-loads production code for **every** test. `tests/registry_guard.py:31` loads `bootstrap/lib/hos_tmp_root.py`. `tests/tmp_hygiene.py:133` loads `bootstrap/tmp_reaper.py`. `tests/conftest.py:105` bare-imports `retry_rescue_logic`. | source |
| F-7 | `shell_logic_check.py` has exactly three exemptions: (1) the single-outcome guard clause; (2) the fixed flag-parse `while [[ $# -gt 0 ]]` plus its next `case "$1"`; (3) the **file-level** exclusion of any path ending `bootstrap/hos_bootstrap.sh`. There is no other file-level exemption anywhere: no caller passes an exclusion list (`run_validators.sh:126-132,409`). `for` loops are tracked but **never counted**. `_scan_file` returns only `(count, first_lineno)`. The per-line list exists only as the local variable `decisions`. Its test imports it bare (`tests/oversight/test_shell_logic_check.py:13`). | `shell_logic_check.py:23-45, 65-75, 159-172` |
| F-8 | `[tool.coverage.run] omit` contains `*/__init__.py`, so `__init__.py` files are never measured. Under ADR AD-3, a new non-empty `__init__.py` would read as 0%. | `pyproject.toml:29` |
| F-9 | `scripts/oversight/` and `scripts/framework/` have no `__init__.py`. `scripts/` and `scripts/automation{,/lib}` do. coverage.py's unexecuted-file discovery prunes non-package subdirectories below a `source` root. So ADR AD-2's `--cov=.` would discover **fewer** files under the three gated-total directories than today. The suite-wide total could then rise, which loosens it. §4.2 avoids this by keeping the three roots as explicit sources. | coverage `files.find_python_files`; `ls` |
| F-10 | Coverage contexts work as the ADR expects. The format is `<nodeid>\|run`, `\|setup` or `\|teardown`, and the empty collection context is present. Measured on `tests/automation/test_claim.py`: 51 contexts. | `check_contexts.py` |
| F-11 | mutmut applies coverage.py exclusions (`# pragma: no cover`) to mutation **only** when `mutate_only_covered_lines = true`. The generated config sets it false. | `__main__.py:148-152, 229-235` |
| F-12 | Installed versions: mutmut 3.8.1, coverage 7.17.2, pytest-cov 7.1.0, pytest 9.2.0, libcst 1.9.0. Local Python is 3.14, CI is 3.12. `requirements.txt:70-84` floats all of them (`mutmut>=3.6,<4.0`). | `importlib.metadata` |
| F-13 | CI today: the `tests` job runs 13.2 to 15.3 min. "Run test suite" takes 758 to 869 s, checkout 12 to 16 s, venv build 18 to 27 s (runs 42785639395 and 42891583485). Runner: `ubuntu-latest` (4 vCPU for public repos). | public Actions API |
| F-14 | The repo is **public**. GitHub's artifact-retention maximum for a public repo is 90 days, and a workflow's `retention-days` cannot exceed the repo setting. The setting itself needs an authenticated admin read, and the repo has 0 artifacts today, so it could not be checked from here. | `GET /repos/…` → 200; `/actions/artifacts` → 0 |
| F-15 | No code reads `Mutant_score_pct`, `Surviving_equivalents` or `Equivalents_documented`. They appear only in Markdown: `unit-test.md:31,32,54,56,72,74-75`, contract `:253,318-322`, templates `:57-60`, BASE-AGENTS-SPEC `:363,371,456` and `packs/django/unit-test.md:39`. | grep |
| F-16 | 15 test files contain `copytree(`, `git clone`, `worktree add` or `git archive` calls. These are the candidates for `repo_copy` marking. S2's guard decides which of them copy the repo root. | grep (§5.18) |
| F-17 | The last 120 first-parent commits on `main`: 41 touched gated production Python, and 25 touched `.sh`. Gated `.py` files per PR: p75 is 1, p90 is 2, max is 5. Added production `.py` lines in PRs that touch Python: median 89, p75 209, p90 676. Mutant density over all 91 production files is 2.97 mutants per executable statement (median 2.69, p90 4.28). | `pr_shape.py`, `mutant_density.py` |
| F-18 | **[round 2: T1]** `tests.yml` triggers only on `pull_request` (`:39-41`). The `tests` job's `actions/checkout@v4` (`:57`) uses the default ref, which is the synthetic merge commit `refs/pull/<n>/merge` at `github.sha`, **not** `pull_request.head.sha`. Coverage data and its line numbers therefore describe the merge tree (ADR AR-1). | `tests.yml:39-66` |
| F-19 | **[round 2: T2]** mutmut's `config()` caches the loaded config in a module global `_config` on first call (`configuration.py:224, 304-308`), and only `reset_config()` clears it. Any mutmut call made in a long-lived process keeps the first workspace's config. | `configuration.py:224, 304-313` |
| F-20 | **[round 2: T3]** In `_scan_file`, the counting loop is lines 94 to 170. It appends to `decisions` in **close order** (at `fi`, `esac` or `done`), not in line order, and line 171 is `min(decisions) if decisions else None`. | `shell_logic_check.py:77-172` |

The prototype and measurement scripts were run from this session's scratchpad. They are evidence only. None of them is committed or designed in.

## 2. Rulings applied, and the ADR/spec lines they change

### 2.1 The rulings (FINAL, 2026-11-10)

| ID | Ruling | Where it lands in this TD |
|---|---|---|
| H1 | Shell decision logic fails closed with the message "move decision logic into tested Python". No shell harness. | §5.11 |
| H2 | No `# pragma: no cover`, `# pragma: no mutate` or "documented equivalent" added in the PR reduces the counts. The 25% headroom covers real equivalent mutants. `unit-test.md` changes to match. | §5.4, §5.9.3, §6.1 |
| H3 | A per-mutant test timeout counts as **KILLED**. The whole-gate CI timeout still fails closed. | §5.9 step 8, §5.13 |
| H4 | `shell_logic_check.py`'s existing exemptions all apply, the file-level one included. Edited `if` lines count as added logic. | §5.11 |
| H5 | A verified human ruling covers only a named file's coverage and mutation **thresholds**. It does not cover path-load, shell or timeout failures. It is bound to the file's **content** (blob hash), not the head SHA, and is void if that file changes after the ruling. There is **no in-gate exception path until S5**, and a human admin merge is the only override. S5 depends on #2101. | §5.12 |
| NQ-1 | The empty-selection carve-out (zero gated mutants and gated line coverage ≥ 80%) applies only if the gated lines contain no decision logic (§5.5). Otherwise the file fails with "move logic into a function so it can be mutated". Every other empty selection fails. Refined by Q8 (§2.1a): the three Q5 carve-outs are not decision logic for this check [ruled 2026-11-11: Q8]. | §5.10 |
| NQ-2 | Unmutatable gated lines (decorated functions, enums) are reported as `unmutatable_gated_lines`. They pass on coverage only if they contain no decision logic. Otherwise the file fails with "move the logic into an undecorated helper so it can be mutated". Refined by Q8 (§2.1a): it uses the same shared predicate as NQ-1 and Q5 [ruled 2026-11-11: Q8]. | §5.10 |
| SEL | Selection comes from coverage contexts (`--cov-context=test`, `COVERAGE_CORE=ctrace`) of the normal run. Name match (`test_<module>.py`) is a fallback only. An empty selection fails (except under NQ-1). Repo-copying tests never run under mutation. The whole suite never runs per mutant. | §5.6 |
| PL | Path-loaded modules fail closed with a message naming the test file and the fix. There is no exemption list. | §5.7, §7.1 |
| WS | `mutants/` is deleted, or a fresh `git archive` workspace is used, on every run. `.claude/` is never copied. | §5.8 |
| SC | This PR covers S1, S2 and S4. Artifact retention is the maximum. The step summary carries the table. The CI token stays `contents: read`. | §0, §5.15 to §5.17 |
| COST | Report typical added runner-minutes. If the typical figure exceeds about 10 minutes, include a plan to cut it. | §8 |

### 2.1a The rulings of 2026-11-11 (FINAL) [ruled 2026-11-11: Q5]

These came through the human-proxy session as the human's answers to §14 Q4 to Q7. As with §2.1, the PR's CODEOWNER review is where the human confirms them on record.

| ID | Ruling | Where it lands in this TD |
|---|---|---|
| Q4 | Confirmed: `Match` statements count as decision logic. | §5.5.1 |
| Q5 | **This changes the design.** Module-level or class-level decision logic on gated lines is **not** coverage-only. It fails with the message "move the logic into a function so it can be mutated". It uses the same mechanism as NQ-1 and NQ-2, with the same AST decision-logic definition. There are three narrow carve-outs and **nothing else**: (a) `if __name__ == "__main__":` whose body is only a call (for example `sys.exit(main())`); (b) `try: import X` / `except ImportError:` fallbacks (import-only `try` bodies and `ImportError` handlers); (c) `if TYPE_CHECKING:`. | §5.5, §5.10, §5.14, §5.15.2, §9.3, §12 R-2 |
| Q6 | Out of scope for this PR. Tracked in #2305. | §14 Q6, §12 R-13 |
| Q7 | Resolved. The CLAUDE.md row is authored by the top-level session as a protected-surface edit, not by the human. | §6.1, §6.7, §10, §11 |
| Q8 [ruled 2026-11-11: Q8] | Apply the Q5 carve-outs consistently. NQ-1 (the empty-selection rule) and NQ-2 (unmutatable lines) treat the three carved-out shapes as **non**-decision-logic too. So a new `__init__.py` whose only logic is `try: import X` / `except ImportError:` or `if TYPE_CHECKING:` passes NQ-1 under its normal conditions (zero gated mutants and gated line coverage ≥ 80%), and the same holds for NQ-2. Also, `raise SystemExit(main())` is an accepted `if __name__ == "__main__":` body, exactly equivalent to `sys.exit(main())` (11 production modules use it). Carve-out (a) therefore accepts a body of one `sys.exit(<call>)` or `raise SystemExit(<call>)` statement, with the same strictness as before about the shape of the call. Every other near-miss stays strict (`except ModuleNotFoundError`, the `typing.TYPE_CHECKING` attribute form, `else:` branches, extra statements, and the rest of §5.5.3's list). | §5.5.1, §5.5.3, §5.5.4, §5.10, §5.19, §7.1a, §9.3, §12, §14 Q8 |

**Self-flag for the Q8 revision (CORE) [ruled 2026-11-11: Q8]:**

```
RISK: MEDIUM. It loosens two ruled checks (NQ-1, NQ-2) and one carve-out, on the
      human's ruling. It changes code already committed on the branch
      (b1a26e887: _is_main_guard, has_decision_logic, zero_mutant_reason, the
      has_decision_logic field of unmutatable_gated_lines, and their tests; §13).
      No sign-off exists yet against that code.
CONFIDENCE: HIGH on the predicate and the new shape. The survey re-run (§7.1a)
      reproduces the 11 raise-SystemExit guards and moves 8 files out of the Q5
      population. MEDIUM on one reading of the ruling: whether a bare `main()`
      body stays accepted. This TD keeps it, as before Q8 (§14 Q8).
Change classification: clarifying for NQ-2 (the carve-outs exist only on direct
      children of Module.body, and NQ-2 judges only function-region findings, so
      no NQ-2 outcome changes). Additive for carve-out (a) (one new accepted
      shape). Behaviour-loosening for NQ-1, which is the human's ruling, not this
      agent's decision. Not structural: no record field, fail code or schema
      element is added or removed.
```

**Self-flag for the Q4 to Q7 revision (CORE):**

```
RISK: MEDIUM. The revision adds a per-file fail class and two record fields to a
      gate that is not built yet. No built code or sign-off is affected (§13).
CONFIDENCE: HIGH on the region rules. Checked against mutmut 3.8.1's
      OuterFunctionProvider, combine_mutations_to_source and
      _skip_node_and_children (file_mutation.py:150-190, 291-345, 380-447).
      MEDIUM on how narrow the carve-outs should be at their edges (§5.5.3
      lists every excluded near-miss; §14 Q8 has since been ruled).
Change classification: additive. New fail codes, new record fields and two new
      unmutatable reasons. No existing contract element is removed. The behaviour
      change, from coverage-only to fail, is the human's ruling and not this
      agent's decision.
```

### 2.2 ADR-2304 edits applied in this PR (rulings only)

These are applied to `docs/v0.7.0/ADR-2304-new-code-coverage-mutation-gate.md` because they only record the rulings. Each edited line carries a `[ruled 2026-11-10]` tag, and a new **AD-13a** table follows AD-13.

| ADR location | Before | After |
|---|---|---|
| Status line | "AD-13 is PROVISIONAL" | AD-13 is superseded by AD-13a (human rulings, final) |
| AD-4 step 7 | "`timeout` is OQ-H3 (AD-13: not killed, provisionally)" | "`timeout` counts as **killed** (H3)" |
| AD-4 step 8 | "informational only (NQ-2)" | Reported. Decision logic in them fails (NQ-2) |
| AD-6 step 4 | "this holds even for zero-mutant files" | The NQ-1 carve-out, conditioned on no decision logic |
| AD-8 heading | "Scope details are OQ-H4, AD-13" | All three exemptions apply, `hos_bootstrap.sh` included. An edited counted line fails (H4) |
| AD-10 "Binding" bullet | "provisional value … AD-13" | Bound to the gated file's blob at ruling time. Void on any content change (H5) |
| AD-11 "Per-mutant timeouts" bullet | "classification is OQ-H3" | Killed (H3) |
| §3 R-2 | "checked by coverage only (AF-5, NQ-2)" | Decision logic in them fails (NQ-2) |
| §5 item 2, second sub-bullet | "fail under the literal R2 (AF-3, NQ-1)" | They pass under NQ-1 when they contain no decision logic |
| §6 AD-13 table | provisional | a header note pointing to AD-13a |
| AD-13a table (2026-11-11) [ruled 2026-11-11: Q5] | — | Two new rows: Q4 (`Match` counts as decision logic) and Q5 (module-level and class-level decision logic fails, with the three carve-outs) |
| §3 R-2 (2026-11-11) [ruled 2026-11-11: Q5] | decorated-function and enum code only | adds: module-level and class-level decision logic fails (Q5), except for the three carve-outs |

### 2.3 ADR amendments: DECIDED by the architect (ADR-2304 §2b, 2026-11-10) [round 2: T10]

The round-1 TD requested ADR-A1 to A8. The architect decided all of them in round 1 and applied them to the ADR as §2b, with the changed lines tagged `[amended 2026-11-10]`. These are technical corrections, not rulings. This TD now treats them as binding ADR text, and does not edit the ADR itself.

| # | Decision (ADR §2b) | Binding refinement from the architect | Where in this TD |
|---|---|---|---|
| ADR-A1 | Accepted | — | §5.8 |
| ADR-A2 | Accepted | Top-level **file** entries in `also_copy` only; nested file entries stay forbidden (R6) | §5.8 |
| ADR-A3 | Accepted | The S1 equivalence evidence must show the same **file count** as well as the same total to 2 dp | §4.1, §4.4 |
| ADR-A4 | Accepted, with an attribution constraint | A test-caused failure is a per-file fail (exit 1) only when **attributed**; an unattributed clean-run failure is exit 3 | §5.9 step 6 [round 4: renumbered] |
| ADR-A5 | Accepted | The observer is **passive** (always returns `None`), and a static test asserts it | §5.7, §5.18, §9.3 |
| ADR-A6 | Accepted | The plugin directory is a **sibling** of the workspace, and the gate asserts the plugin's `__file__` is outside it | §5.8, §5.18 |
| ADR-A7 | Accepted and extended | Pin **pytest** as well as libcst; `measure` checks the sidecar's tool versions and Python major.minor against its own install | §5.1, §5.2, §5.18 |
| ADR-A8 | Accepted | — | §5.8 |
| A9 | New (from F-3) | Enumerate with `mutate_file_contents(...).mutant_names` in a **per-file subprocess** with cwd = the workspace (F-19) | §5.9 steps 1 and 2 |
| AR-1 | New, **blocking** | Gate the merge commit `github.sha`; diff base `github.sha^1`; guard `github.sha^2` = PR head; records carry `gated_sha` and `pr_head_sha`; H5 `blob_sha` from the gated tree, `pr_head_blob_sha` alongside | §3, §5.1, §5.2, §5.3, §5.15, §5.17 |
| Q2 | Decided: **no trusted base** | The verdict runs from the same commit as the other two jobs. New ADR residual **R-6** | §5.17, §5.19, §12 |
| Permissions | Decided | `new-code-gate` has `contents: read` only in S2; `pull-requests: read` (and `issues: read` if needed) arrives with S5 | §5.17 |
| REQ-35 | Sound under ADR §2b conditions 1 to 7 | Binding on TD and coder | §2.6, §5.19 |

For history, the round-1 request table follows unchanged.

| # | ADR text (round 1) | Requested change (round 1) | Reason |
|---|---|---|---|
| ADR-A1 | AD-5 "`git archive <head> -- . ':(exclude).claude'`" | `':(exclude,glob)**/.claude/**'` | F-1: otherwise every run exits 3 on `prompts/.claude/` |
| ADR-A2 | AD-5 "`also_copy`: every other top-level tracked **directory**, as directory entries only" | Add every top-level tracked **regular file** as a file entry. Nested file entries stay forbidden | F-2. Without them, tests that read `CLAUDE.md`, `AGENTS.md` and similar fail in isolation |
| ADR-A3 | AD-2 "`--cov=.`, and the existing `omit` list is extended" | Keep the three current `--cov=` roots and add `--cov=scripts --cov=bootstrap --cov=bin`. Remove `*/__init__.py`, `*/test_*` and `*/conftest.py` from **run-time** omit and re-apply them at report time | F-8, F-9. Equivalence holds by construction, and new `__init__.py` files get measured |
| ADR-A4 | AD-6 step 5 / F-7 / F-8 "exit 3" for a selected test failing in isolation, or for an unmarked repo copy | The file is `fail` (exit 1) with a named reason. Exit 3 is kept for gate-internal errors | These failures come from the PR's own tests and have a deterministic, named fix. Both exits are non-success. A per-file outcome keeps the other files' results in the table |
| ADR-A5 | AD-12 runtime recorder "wraps the same loaders" | Also install a passive meta-path observer and a `sys.modules` alias scan, so that bare `sys.path` imports are caught | F-5. Bare imports are the larger population |
| ADR-A6 | AD-7 / AD-5 `-p scripts.framework.new_code_gate_pytest_plugin` | Load the plugin from a copy **outside** the workspace, under the private name `_ncg_tripwire` | Otherwise, when the plugin is itself the gated file, mutmut mutates the tripwire that is guarding the run |
| ADR-A7 | AD-4 step 1 pins mutmut, coverage and pytest-cov | Also pin `libcst==1.9.0` and record its version | libcst does the CST mutation. A floating libcst can change the mutant set across runs (AC-29) |
| ADR-A8 | AD-4 step 3 strips `# pragma: no mutate` from gated lines only | Strip every `# pragma: no mutate*` comment token in the workspace copy of the gated file | A pre-existing `no mutate block` pragma on an unchanged line otherwise shields new gated lines beneath it. Stripping everywhere only affects ungated mutants, which are never run or counted, so the result matches the ruling exactly with no scope analysis |

### 2.3a ADR round-3 rulings: DECIDED by the architect (ADR-2304 §2c, 2026-11-10) [round 4]

This TD treats ADR §2c as binding ADR text and does not edit the ADR. Rows U1 to U7 are the architect's required TD edits for round 4.

| # | Decision (ADR §2c) | Where in this TD | TD edit |
|---|---|---|---|
| R3-A | `_enumerate` accepted as a hidden `-P` phase. The child reports its own resolved `__file__`, and `measure` requires it to be under the checkout and not under the workspace (exit 3 otherwise) | §5.9 steps 1 and 7 | applied to `_enumerate` and `_collect` alike |
| R3-B | The mutmut read-back runs in a hidden per-file `_collect` subprocess, never in `measure` | §5.1 Imports, §5.9 step 7, A9a | **U1** |
| R3-C | A selected test failing in isolation first surfaces in mutmut's stats run (`failed to collect stats. runner returned <n>`). Attribution applies to both messages. The "could not find any test case for any mutant" stop records every gated mutant as `no tests` | §5.9 step 6 rules 4 to 6; A4a, A4f, E2E-ISO | **U2** |
| R3-D | `-rfE` passed explicitly; parse scoped to the short-summary section | §5.8 `pytest_add_cli_args`; §5.9 step 6; A4d, A4e | **U3** |
| R3-E | `observer_error` comes before every attribution rule, exit 3 | §5.9 step 5 | moved with U7 |
| R3-F | `also_copy` excludes `setup.cfg` and is computed from the extracted workspace | §5.8; A2a | architect's own edit, kept |
| R3-G | The repo-copy collect-only runs in the checkout, without the tripwire, with `-o addopts=`; exit 5 = empty set. **Supersedes ADR AD-6 step 3's "in the workspace"** | §5.6 step 3 | **U4** |
| R3-H | The plugin reads `NCG_*` once into module state and removes them from `os.environ` | §5.18; §9.1; P-ENV | **U5** |
| — | R-S1b must not need `.git`; no in-process gate test may need the real `.git` or `.claude/` | §9.3 R-S1b; §5.19 | **U6** |
| — | executed ⊆ selected moves up with the integrity checks, before the attribution rules | §5.9 step 5 | **U7** |

### 2.4 SPEC-2304 edits applied in this PR (rulings only)

Applied to `docs/specs/SPEC-2304-new-code-coverage-mutation-gate.md`, with `[ruled 2026-11-10]` tags and a new §2a table.

| Spec location | Change |
|---|---|
| Status line | DRAFT → rulings recorded in §2a. Human confirmation is through the PR CODEOWNER review |
| §3 "Mutant score" | "Per-mutant timeouts are §10 OQ-H3" → a per-mutant timeout counts as killed (H3) |
| §3 "Shell decision logic" | "See OQ-H4" → all three exemptions apply. An added or modified line on which a **counted** construct opens counts as added logic (H4) |
| §3 "Verified human ruling" | Delete "and the evaluator's CODEOWNER-comment rule until then". Add the blob binding and the thresholds-only scope (H5) |
| REQ-12 | Add the NQ-2 `unmutatable_gated_lines` clause |
| REQ-16 | Add the NQ-1 carve-out |
| REQ-21 | Remove "The shell-mutation-harness option stays undecided (OQ-H1), and until it is decided" (H1 decided) |
| REQ-22 | Pragmas and documented-equivalent claims never reduce the counts (H2). Rulings apply to thresholds only. No in-gate exception path until S5, and admin merge is the only override (H5) |
| REQ-29 | Add: "a per-mutant timeout is a kill, not a gate timeout" (H3) |
| REQ-30 | Add: equivalent mutants are not excluded from the denominator (H2) |
| §10 OQ-H1 to OQ-H5 | Each marked **RULED 2026-11-10** with the ruling text |
| §2a table (2026-11-11) [ruled 2026-11-11: Q5] | Two new rows: Q4 and Q5 |
| REQ-12 (2026-11-11) [ruled 2026-11-11: Q5] | Adds: decision logic on gated module-level or class-level lines fails with "move the logic into a function so it can be mutated", except for the three carve-outs (Q5) |

### 2.5 SPEC-2304 amendments requested from pm-agent (not applied; they are not rulings)

ADR §7 D-1, D-4, D-5, D-6 and D-7 still stand and are pm-agent's to apply. On top of those:
- **D-8.** REQ-18 should say "or by a bare module name made importable through `sys.path` injection" (F-5).
- **D-9.** AC-20 and AC-22's excepted case move to S5. AC-24 splits into an S2 part (the artifact contract) and an S3 part (ingest) (§9).

### 2.6 REQ-35 binding conditions (ADR-2304 §2b, binding on TD and coder) [round 2: T10]

| # | Condition (ADR §2b) | How this TD meets it |
|---|---|---|
| 1 | The introducing PR changes only the three new gate modules and `shell_logic_check.py` among production `.py` files. Any other production `.py` change comes back through `technical-design` | §5.19 table and its first bullet; §10 file list |
| 2 | `shell_logic_check.py:94-170` stays byte-identical and in place. `decision_lines` returns sorted line numbers **with duplicates preserved**. `_scan_file` returns `(len(d), min(d) if d else None)`. The PR body attaches the file's `--unified=0` hunk list | §5.11; R-SLC and R-SLC2 (§9.3); §11 commit 10 |
| 3 | `tests/oversight/test_shell_logic_check.py:13` is the only non-canonical importer of `shell_logic_check`, and it is converted in the same PR | §5.19; Appendix A (the only bare importer, no path loader) |
| 4 | `tests/framework/test_new_code_gate_e2e.py` imports no `scripts.framework.new_code_gate*` module in-process, and a static test asserts it | §9.3 S-E2E |
| 5 | `new_code_gate.py` and `new_code_gate_logic.py` import only the stdlib at module level, and a static test asserts it. Any coverage, mutmut or libcst use is a lazy import in the measure path or in the per-file subprocess | §5.1 Imports (mutmut and libcst only in the `_enumerate` and `_collect` subprocesses [round 4: U1]); §9.3 S-STDLIB, A9a |
| 6 | Self-budget evidence before the PR opens. If the projected 4-vCPU CI time exceeds 20 minutes, return to the architect. The budget is not raised, and the gate's files are not exempted | §5.19; §11 commit 10 |
| 7 | The PR's own `new-code-gate` is green on its final head (AC-34), with no exemption | §5.19 |

## 3. Shape of the change

```
tests job (existing, required)            new-code-measure (new, not required)          new-code-gate (new, REQUIRED)
  checkout github.sha (merge commit)
  run_tests.sh                              needs: tests, if: always()                     needs: new-code-measure, if: always()
   ├ pytest … ctrace + --cov-context=test   checkout github.sha (fetch-depth 0, no creds)  checkout github.sha (no creds), setup-python
   ├ coverage report --include … ≥78        build venv; download coverage-contexts         download new-code-records
   └ python -m …new_code_gate meta          python -m scripts.framework.new_code_gate      python -m scripts.framework.new_code_gate
  upload coverage-contexts (7 d)              measure --tests-result <r> …                   verdict --measure-result <r> …
                                            upload new-code-records (90 d, always)         $GITHUB_STEP_SUMMARY table
                                                                                           upload new-code-verdict (90 d, always)
```

Local runs call `python -m scripts.framework.new_code_gate run`, which runs `measure` and then `verdict` in-process through the same functions (REQ-3).

**Which commit is gated (ADR AR-1) [round 2: T1].** In CI all three jobs work on `github.sha`, the `pull_request` merge commit (F-18). The **gated SHA** is `github.sha`. The **diff base** is `github.sha^1`, the base-branch parent, so the gated lines are exactly what the PR adds to the current base. The **guard** is that `github.sha^2` equals `github.event.pull_request.head.sha`; otherwise exit 3. Locally, `run` gates `HEAD` against `merge-base(<base>, HEAD)`, and there is no parent guard.

## 4. S1 — context recording in the `tests` job

### 4.1 `scripts/framework/run_tests.sh`

The script must gain **no counted shell decision construct**, because H1 and H4 apply to its own PR (§5.19). Edits to existing `if` lines are allowed only on guard-clause lines, which are exempt, and S1 does not need any. At `8113f8ba0`, `_scan_file('scripts/framework/run_tests.sh')` returns `(2, 128)`. The heuristic counts the `if`/`else` inside the embedded `python -c` kill-rate string, and the kill-rate `if`/`else`. S1 leaves lines 99 to 147 untouched, so the count and the counted lines' content stay the same; their line numbers shift only by the number of lines S1 adds above line 99 (R-S1b pins `[128 + k, 135 + k]` and the content of both lines) [round 4: U6]. Canonical import of `scripts.oversight.validators.shell_logic_check` was verified to work. No test uses it today.

1. After `cd "$REPO_ROOT"`, set `export COVERAGE_CORE=ctrace`. Use a plain assignment, no conditional, and add a comment citing #2304 and the reason: it pins the context-capable core, it is already the default on 3.12, and it protects against a future default change.
2. The pytest invocation (lines 75 to 82) becomes the following. Every other flag is unchanged.
   - `--cov=scripts/oversight --cov=scripts/automation/lib --cov=scripts/framework --cov=scripts --cov=bootstrap --cov=bin`. The three current roots are kept as explicit sources, so unexecuted-file discovery under them is unchanged (F-9).
   - `--cov-context=test`
   - `--cov-report=` (empty). The terminal report moves to step 3.
   - Remove `--cov-fail-under=$COVERAGE_TARGET` from this line.
3. Directly after it, run the suite-wide report: `"$VENV_PYTHON" -m coverage report --include='scripts/oversight/*,scripts/automation/lib/*,scripts/framework/*' --omit='*/test_*,*/__init__.py,*/conftest.py,*/.venv/*,*/__pycache__/*' --show-missing --fail-under=$COVERAGE_TARGET`. The `--omit` value is today's `[tool.coverage.run] omit`, copied verbatim, so the file set and the total are the same as today's (REQ-8). Under `set -e` a non-zero exit aborts the script with that code. The existing PASS/FAIL banner logic is not touched.
4. After that, run `"$VENV_PYTHON" -m scripts.framework.new_code_gate meta --coverage-file .coverage --out coverage-meta.json` (§5.1). That writes the sidecar.
5. Header comment: add a short paragraph naming the context recording, the sidecar, the gate, and a pointer to this TD. The `--mutation` path (lines 99 to 147) is **not touched**. It stays the developer whole-repo path (ADR AF reuse note).

### 4.2 `pyproject.toml`

- `[tool.coverage.run] omit` becomes `["*/.venv/*", "*/__pycache__/*", "mutants/*"]`. The three removed patterns move to report time (§4.1 step 3). `source` is left alone (`--cov=` overrides it), and so is `branch = true`.
- `[tool.pytest.ini_options] markers` gains `"repo_copy: copies or clones the repository root; never run under the new-code gate's mutation (#2304)"`. `addopts` gains `--strict-markers` (it is absent today). S2 checks that the full suite still collects with it.
- `[tool.mutmut]` is **not changed** (`8113f8ba0` stands). The gate never reads it (§5.8).

### 4.3 `.github/workflows/tests.yml` — the `tests` job

- After the suite step, add an upload step: `actions/upload-artifact@v4`, `name: coverage-contexts`, `path: .coverage` and `coverage-meta.json`, `retention-days: 7`, `if-no-files-found: error`, `include-hidden-files: true` (`.coverage` is a dotfile).
- Job name, timeout (30), permissions and concurrency are unchanged.
- Update the header comment to say that contexts are recorded for the new-code gate and that `--mutation` is still not run per PR.

### 4.4 S1 obligations (evidence the PR must attach)

| Obligation | Local result (this session) | CI-only part |
|---|---|---|
| **Equivalence (REQ-8, ADR AD-2, ADR-A3).** The old command and the new commands report the same suite-wide total to 2 dp **and the same file count** (the number of file rows in the `coverage report` table) over the same file set [round 2: T10] | **Totals equal: 84.81 vs 84.81** over the full suite (§8.2.1). The round-1 run did **not** capture the file count, so that part is still owed: the coder repeats the two-run comparison locally before the PR and records both file counts | Repeat on the PR's own CI run of `main`'s tree: the PR description quotes the old total and file count from the latest `main` `tests` log, and the new total and file count from the PR's `coverage report` output. If either differs, **S1 stops and escalates to the architect**. `fail_under` is never adjusted |
| **Timing (ADR AD-2).** The `tests` job wall time before and after, and the `.coverage` size. Escalate if the job is over 22 min | Full suite +4.8% (includes the sysmon → ctrace switch on 3.14); contexts alone +2.1%; data 1.3 → 28.9 MB (§8.2.1) | The PR's `tests` job wall time against F-13's 13.2 to 15.3 min |

## 5. S2 — the gate

### 5.1 CLI: `python -m scripts.framework.new_code_gate <phase> …`

| Phase | Arguments | Behaviour |
|---|---|---|
| `meta` | `--coverage-file P --out P` | Writes the sidecar: `schema: "new-code-gate-meta/1"`, `head_sha` (`HEAD`, which in CI is the merge commit `github.sha`, F-18), `head_tree` (`HEAD^{tree}`), `checkout_root` (absolute, resolved), `clean` (true iff `git status --porcelain --untracked-files=no` lists no `.py` or `.sh` path), `coverage_core` (the `COVERAGE_CORE` env value), `measured_sources` (the constant `MEASURED_SOURCES` in `new_code_gate_logic`, which lists the six `--cov` roots. Static test R-S1a asserts it equals `run_tests.sh`'s `--cov=` list exactly), `tool_versions` (the installed version of each of the five pinned tools: mutmut, coverage, pytest-cov, libcst, pytest) and `python` (`"<major>.<minor>"` of the running interpreter) [round 2: T4]. It reads versions with `importlib.metadata` only, so it imports none of those tools. Stdlib + git only. Exit 0, or 3 on a git error |
| `measure` | `--gated-sha S --pr-head-sha S --pr N --coverage-file P --meta P --out P [--tests-result R] [--run-id ID --run-attempt N]` [round 2: T1] | §5.2 to §5.13. The diff base is **derived**, never passed: `base_sha = <gated>^1` (§5.2 step 5). Writes the records (no outcomes). Exit 0 when the records are complete, 3 on any internal error (records are still written, carrying `internal_errors`) |
| `verdict` | `--records P --out P --summary P [--measure-result R]`, plus four **required** binding inputs [architect review-1 ruling, ADR §2e RV-7]: this run's gated SHA, PR number, run ID and run attempt (the coder names the flags) | §5.14. Exit 0 / 1 / 3. **Binding checks run first [architect review-1 ruling].** The records path must be a regular file (`lstat`, not a symlink), or exit 3. The records must carry `mode: "ci"`, `gated_sha`, `pr` and `run_id` equal to the binding inputs, and an integer `run_attempt` no greater than the current attempt (a verdict-only re-run reads attempt-1 records). Any failure → exit 3 `records not bound to this run`, after the summary is still rendered. A missing binding flag is exit 2 (usage). Local `run` calls the same binding function in-process with its own values (`mode: "local"`, no run ID) |
| `run` | `[--base REF] [--keep-workspace]` | Local only. `--base` defaults to `origin/main`. Gated = `HEAD`, base = `merge-base(<base>, HEAD)`, `pr_head_sha` = `HEAD`, and there is no parent guard (`mode: "local"` in the records). Refuses with exit 3 if the tracked tree is dirty for `.py`/`.sh`, or if `coverage-meta.json` is missing, names a different head, or has `clean: false`. Then runs measure and verdict in-process, through the same functions as the CLI phases. Prints the summary table to stdout. `--keep-workspace` keeps the workspace directories for debugging and is never used in CI |

- **Invocation form [architect review-2 ruling, ADR §2f RV2-1].** The heading's `python -m` form is for a developer's own tree only. CI (`tests.yml`), `run_tests.sh` and the gate's own child argv must invoke the gate as `<python> -I -c "<ENTRY_SNIPPET>" <checkout root> <phase> <args…>`. `ENTRY_SNIPPET` is a constant in `new_code_gate_logic` whose exact text is fixed in ADR §2f RV2-1. It pre-seeds a `scripts` namespace module whose `__path__` is `<root>/scripts`, so no checkout path is ever on `sys.path` and `scripts/__init__.py` never runs. `main(argv)` is called with `sys.argv[2:]`. `argparse` gets `prog="new_code_gate"`. The module's `if __name__ == "__main__": sys.exit(main())` guard is unchanged (REQ-35).
- **Exit contract (ADR AD-1):** 0 = completed and every file is `pass` (or `excepted`, which needs S5). 1 = a decided fail. 2 = usage error. 3 = could not decide. **Every caller treats non-zero as fail.**
- **`--tests-result` / `--measure-result`:** the workflow passes `${{ needs.<job>.result }}`. Any value other than `success` gives exit 3, `upstream job not successful: <value>`, after `verdict` has rendered whatever records exist. This puts the needs-result check in Python rather than YAML or shell (H1).
- **Imports (ADR §2b condition 5) [round 2: T10]:** at module level, `new_code_gate.py` and `new_code_gate_logic.py` import **only** the stdlib (plus `new_code_gate.py` importing `scripts.framework.new_code_gate_logic`). coverage is imported lazily inside the measure path only. mutmut and libcst are **never** imported in the `measure` process at all, not even lazily: they are used only inside the two hidden per-file subprocesses, `_enumerate` (§5.9 step 1) and `_collect` (§5.9 step 7) [round 4: U1], and inside the `mutmut run` subprocess. That includes `mutmut.stats` and `mutmut.mutation.data`, because importing `mutmut.stats` imports `mutmut.configuration.config` at module level (ADR §2c R3-B). Every mutmut-side value `measure` needs (the `.meta` exit codes and their `status_by_exit_code` names) reaches it as JSON from `_collect`. `meta` and `verdict` run on the stdlib alone, so the verdict job needs no venv. Static test S-STDLIB and test A9a (§9.3) enforce this.

### 5.2 Inputs and guards (measure)

1. **Version guard [round 2: T4].** Read `importlib.metadata.version` for `mutmut`, `coverage`, `pytest-cov`, `libcst` and `pytest`, and compare with the constants `PINNED = {"mutmut": "3.8.1", "coverage": "7.17.2", "pytest-cov": "7.1.0", "libcst": "1.9.0", "pytest": "9.2.0"}` in `new_code_gate_logic`. Any mismatch → exit 3 `tool version mismatch: <name> <found> != <pinned>`. `requirements.txt` pins the same five with `==` (§5.18). A static test asserts the two agree (R-PIN). pytest is pinned because it produces the node IDs on which the coverage contexts and the mutmut selection must agree.
2. **Sidecar equals this environment [round 2: T4].** The `tests` and `new-code-measure` jobs build their venvs independently, minutes apart. So the sidecar's `tool_versions` must equal this process's installed versions for **all five** pinned tools, and the sidecar's `python` must equal this interpreter's `"<major>.<minor>"`. Any difference → exit 3 `sidecar tool versions differ from measure environment: <name> <sidecar> != <installed>` (or `… python …`). This check is separate from step 1: step 1 catches a wrong pin, step 2 catches two jobs that resolved differently.
3. **Sidecar head and the AR-1 guard [round 2: T1].**
   - The sidecar's `head_sha` must equal `--gated-sha`, `clean` must be true, and `coverage_core` must be `ctrace`. Otherwise → exit 3 `coverage data stale or from a dirty tree`.
   - **Run binding [architect review-1 ruling, ADR §2e RV-7].** `meta` writes `run_id` (the `GITHUB_RUN_ID` value, or `null` when unset) into the sidecar. In CI mode `measure` requires sidecar `run_id` = `--run-id` (non-null), or exit 3 with the same message. `--coverage-file` and `--meta` must each be a regular file (`lstat`, not a symlink), or exit 3 `coverage data missing contexts`.
   - In CI mode, `git rev-list --parents -n 1 <gated>` must show **exactly two** parents, and the second parent (`<gated>^2`) must equal `--pr-head-sha`. Otherwise → exit 3 `merge commit does not contain the PR head`.
4. **Coverage data.** It must open, and contexts must be present: `measured_contexts()` is non-empty and contains at least one non-empty context. Otherwise → exit 3 `coverage data missing contexts`.
5. **Diff base [round 2: T1].** In CI mode, `base_sha = git rev-parse <gated>^1`. In local mode (`run`), `base_sha = git merge-base <base> HEAD`. Any git failure → exit 3 `diff could not be computed`. There is no `merge-base` call in CI mode: the merge commit's first parent already is the base the PR merges into.

### 5.3 Gated files and gated statements (ADR AD-3, AF-2)

- **Diff command (fixed argv) [round 2: T1]:** `git -c diff.algorithm=myers -c core.quotePath=true diff --no-ext-diff --no-textconv --no-color -M --unified=0 <base_sha> <gated_sha>`, with `base_sha` from §5.2 step 5. Every "head" blob, line number and statement in §5.3 to §5.11 is read from the **gated** tree (`<gated_sha>`), because that is the tree the coverage data describes (F-18). Use the raw `--name-status` form from the same options to classify each path. `A` = new. `R100` = not gated. `R<100` and `M` = changed. `D` = not gated. `C` is treated as new for the destination path. A type change (`T`) is treated as changed.
- **Python scope:** tracked `.py` at head. Excluded: `tests/**`, `**/conftest.py`, `mutants/**`, and any path with a component that is `.venv`, `venv` or `site-packages`. `source` and `source_paths` play no part.
- **Shell scope:** tracked `.sh` at head (§5.11). Shell without a `.sh` extension (for example `bin/hos-cron`) is out of scope, as in the spec §3. This is TD residual R-13 (§12).
- **Symlinks fail closed [architect review-1 ruling, ADR §2e RV-2].** A path in Python or shell scope whose mode in the gated tree is `120000` gets `fail_reasons: [symlink_not_gateable]` with the message "this path is a symlink; replace it with a regular file, or a module that re-exports the target". That is a per-file decided fail (verdict exit 1), and it is not ruling-eligible. Read the mode from the same pinned diff (`--raw` or `ls-tree` on `<gated_sha>`). The check runs **before** any blob is parsed, so link-target text is never treated as source. A `T` type change to a symlink takes the same path. The file is then skipped for statements, coverage, selection and mutation (`mutation_reason: blocked_by:symlink_not_gateable`). §5.14's non-eligible list gains `symlink_not_gateable`.
- **Mode allow-list [architect review-2 ruling, ADR §2f RV2-4(a)].** In the same place, before any blob read: modes `100644` and `100755` are gateable; `120000` → `symlink_not_gateable` (above); **any other mode** (a gitlink `160000` at a `*.py` / `*.sh` path, or anything unexpected) → `fail_reasons: [mode_not_gateable]`, message "this path is not a regular file in git (mode `<mode>`, for example a submodule); only regular files (100644, 100755) can be gated", with `mutation_reason: blocked_by:mode_not_gateable`. Not ruling-eligible. A path that the diff reports as present at the gated tree but that has no `ls-tree` entry → exit 3 `tree listing and diff disagree: <path>`. Replace `is_symlink_mode` with one function that returns the fail code or `None` for a mode, so that both codes come from one decision.
- **Statements:** use coverage's `PythonParser(text=<gated blob>, exclude=None)` from the pinned version, then `parse_source()`. `statements` is the set of executable first lines. The multiline map (`first_line(n)` for every line of a multi-line statement) gives each changed line its owning statement. **A changed line is gated if `first_line(line)` is in `statements`.** That covers continuation lines and decorator lines (AF-2). A changed comment, blank or docstring line maps to nothing. For a new file, gated = all of `statements`.
- **Pragmas (H2):** `exclude=None`, so `# pragma: no cover` and `exclude_lines` remove nothing. The consequence is that `if TYPE_CHECKING:` bodies and other never-run lines count as uncovered (§7.2).
- **Not measured:** if a gated file's top-level directory is not under any sidecar `measured_sources` root, the file gets `fail_reasons: [not_measured]` with the message "file is outside the measured surface; add its top-level directory to run_tests.sh's --cov list". Never 0%-and-silent.
- **Per-file record fields from this step [round 2: T1]:** `path`, `kind`, `blob_sha` (the blob id of the path in the **gated** merge tree, `git rev-parse <gated_sha>:<path>`; this is what S5 binds a ruling to, ADR §2b "H5 binding under AR-1"), `pr_head_blob_sha` (`git rev-parse <pr_head_sha>:<path>`, or `null` if the path is absent there; equal to `blob_sha` when the base did not touch the file, and always equal in local mode), `gated_statements` (count) and `gated_lines` (sorted statement first lines, capped at 5,000 entries; beyond that `gated_lines_truncated: true`, and the count stays exact).

### 5.4 Coverage (REQ-5 to REQ-7)

- **Data path mapping:** strip the sidecar `checkout_root` prefix from each measured file, then compare repo-relative paths. A gated file with no data and inside the measured surface → 0 executed.
- **Executed:** `CoverageData.lines(file)`, covering all contexts, the empty context included.
- **Threshold, exact integer arithmetic:** pass iff `executed_gated * 100 >= 80 * gated_statements`. `coverage_pct` is reported as `floor(executed*1000/gated)/10`, one decimal, rounded **down**, so a failing 79.96% is never displayed as 80.0. A file with `gated_statements == 0` has no coverage requirement and is recorded as `coverage_pct: null`.
- **Pragmas and "equivalents" (H2):** no input reduces `gated_statements`.

### 5.5 Decision logic: definition, regions and carve-outs (used by NQ-1, NQ-2 and Q5) [ruled 2026-11-11: Q5]

All functions here are pure. They use only `ast` from the stdlib and live in `new_code_gate_logic`. They work on the **gated** blob's source and the file's gated statements (§5.3). There is **one** decision-logic definition (§5.5.1). NQ-1, NQ-2 and Q5 all read the output of one function, `decision_logic_findings` (§5.5.4), **through one predicate**: a finding counts as decision logic if and only if its `carve_out` is `null` (§5.5.4) [ruled 2026-11-11: Q8].

#### 5.5.1 Decision nodes and their owning statement (unchanged from round 5, except that Q4 is now confirmed)

- For each gated statement S (the AST node whose `lineno` is the statement's first line), compute its **own lines**:
  - a simple statement owns `S.lineno..S.end_lineno`;
  - a compound statement (`If`, `For`, `AsyncFor`, `While`, `Try`, `TryStar`, `With`, `AsyncWith`, `FunctionDef`, `AsyncFunctionDef`, `ClassDef`, `Match`) owns its **header**: its decorator lines plus `S.lineno` up to, but not including, the first line of its first body statement. For `Try`/`TryStar` that is each `except`/`else`/`finally` header line.
- A **decision node** is any `If`, `For`, `AsyncFor`, `While`, `Try`, `TryStar` or `Match` node; any `BoolOp`, `Compare` or `IfExp` node; and any comprehension (`ListComp`, `SetComp`, `DictComp`, `GeneratorExp`) with at least one generator whose `ifs` is non-empty.
- A decision node is **gated** if it is a gated statement S itself (the construct types), **or** if its `lineno` lies inside the own lines of a gated statement. Its **owning statement** is the innermost such statement. When two simple statements share a line (`a = x if y else z; b = 1`), the owner is the one whose column range contains the node.
- `has_decision_logic(source, lines)` → bool keeps its signature but **changes meaning** [ruled 2026-11-11: Q8]. It is true if and only if `decision_logic_findings(source, lines)` (§5.5.4) holds at least one finding whose `carve_out` is `null`. A gated decision node that a carve-out excuses (§5.5.3) is **not** decision logic for any rule. Before Q8 the carve-outs were not applied here; that reading is withdrawn.
- The ruled set is If/For/While/Try/BoolOp/Compare/IfExp/comprehension-with-if. `AsyncFor` and `TryStar` are the same constructs in their async and `except*` forms. **`Match` is included, as the human confirmed on 2026-11-11 (§14 Q4) [ruled 2026-11-11: Q4].**

#### 5.5.2 Region of a decision node (by AST containment, not by line)

Each gated decision node N is given a **region** from its AST ancestors. Lines are not used, so a one-line `def f(x=a == b): return x` is still classified correctly.
- **`function`**: some ancestor is a `FunctionDef` or `AsyncFunctionDef`, and N lies inside that def's **`body`** list. A def's `decorator_list`, `args` (defaults included) and `returns` are **not** its body. Code there runs when the def statement runs, in the enclosing scope.
- **`class`**: N is not in any function body, but some ancestor `ClassDef` has N inside its **`body`** list. A class's `bases`, `keywords` and `decorator_list` are not its body.
- **`module`**: everything else.
- `Lambda` does not open a region. A lambda at module level is module-region code, and mutmut does not mutate it.
- In practice: a decorator argument, a non-trivial default or an annotation on a **top-level** function is `module` region. The same on a **method** is `class` region. A class attribute, a class-body `if` or a nested class's body is `class` region. All of these run at import or at class creation, and mutmut 3.8.1 never mutates them: it keeps mutations only inside top-level functions and methods of top-level classes (F-3, `combine_mutations_to_source`), and `_skip_node_and_children` drops decorators, annotations and non-simple defaults (`file_mutation.py:291-345`).

For a `function`-region node, the **unmutatable reason** is the first of the following that applies, in this fixed order, or `null` if none applies. The four reasons from round 5 are unchanged. The two new reasons, marked "new" below, are needed because Q5's fix ("move the logic into a function") only works if the function is one that mutmut actually mutates:
1. `decorated_function`: some def whose body contains N, **at any nesting depth**, has a decorator list other than exactly one bare `staticmethod` or `classmethod`. mutmut skips any decorated `FunctionDef` node and its children wherever it sits (`_skip_node_and_children` is not limited to the top level). So a nested `@functools.wraps(orig) def wrapper(...)` inside a top-level function is unmutatable.
2. `enum_body`: some def whose body contains N is a **direct child of the body of an enum class** and is named `__init__` or `_generate_next_value_`. An enum class is any `ClassDef`, at any depth, with a base that is a `Name`, or an `Attribute` whose `attr`, is in {`Enum`, `IntEnum`, `StrEnum`, `Flag`, `IntFlag`} (`file_mutation.py:38-39, 306-313, 359-361`). Other methods of an enum class are mutated like any method and carry no reason. Enum member values are class-region code (Q5), not this reason (architect delta-review fix).
3. `single_line_class`: never a `function`-region reason, because a single-line class body cannot hold a def. It is used only in `unmutatable_gated_lines`, with `region: class` (§5.10) (architect delta-review fix).
4. `never_mutate_name`: some def whose body contains N, **at any depth**, is named `__getattribute__`, `__setattr__` or `__new__`; **or** N lies inside the arguments of a call whose `func` is a bare `Name` `len` or `isinstance`. mutmut skips both node kinds together with all their children (`file_mutation.py:37, 40, 315-320`). Production example: `len(r.get("evidence") or [])` at `scripts/oversight/second_review_logic.py:990-992`, where the `BoolOp` is never mutated (architect delta-review fix).
5. **`non_top_level_function` (new):** the **outermost** def whose body contains N is neither a direct child of `Module.body` nor a direct child of the body of a `ClassDef` that is itself a direct child of `Module.body` and whose body starts on a later line than the class header. These are the only units mutmut trampolines (`OuterFunctionProvider`, `file_mutation.py:150-178`). A def inside a module-level `if`, `try`, `with` or `except` handler, or a method of a nested class, is not one of those units. (A class decorator does not matter: mutmut still recurses into a decorated top-level class and trampolines its methods, `file_mutation.py:349-354`.)
6. **`definition_time_expression` (new):** N lies, anywhere inside the function body, inside (i) any annotation (argument, return, or `AnnAssign`), (ii) any decorator of a nested def or class, or (iii) a parameter default of a nested def **or lambda** that is not "simple". Simple follows mutmut's `cst.Name` / `cst.BaseNumber` / `cst.BaseString` test: in `ast` terms a `Name`, a `Constant`, or a `JoinedStr` (an f-string default is simple to mutmut, so it is mutated). mutmut skips these nodes and their children even inside an otherwise mutated function (`file_mutation.py:322-335, 349-354`; libcst represents lambda parameters as `cst.Param` too) (architect delta-review fix: AnnAssign, lambda defaults and the f-string case added).

#### 5.5.3 The three Q5 carve-outs (exhaustive; nothing else is carved out)

A carve-out is recognised **only** on a statement that is a **direct child of `Module.body`**. A matching shape anywhere else (inside a class, a function, another `if` or `try`, or another carve-out) is not carved out. Each carve-out excuses **only the nodes named here**. Every other decision node in the statement's body or handlers is judged on its own.

| Carve-out | Exact shape | Nodes excused |
|---|---|---|
| (a) `main_guard` | An `If` whose `test` is `Compare(left=Name(id="__name__"), ops=[Eq()], comparators=[Constant(value="__main__")])`; whose `orelse` is empty; and whose `body` is **exactly one** statement, which is **either** (a1) an `Expr` whose `value` is a `Call` (for example `sys.exit(main())` or `main()`; unchanged from Q5), **or** (a2) [ruled 2026-11-11: Q8] a `Raise` whose `cause` is `None` and whose `exc` is a `Call` with `func` exactly `Name(id="SystemExit")`, exactly one positional argument, no keywords, and that one argument itself a `Call` (for example `raise SystemExit(main())` or `raise SystemExit(_main(sys.argv[1:]))`). (a2) is the `raise` spelling of `sys.exit(<call>)`, and it excuses the same nodes. As under (a1), any decision node inside the call's own arguments is still judged. `cause` is the Python value `None`: `raise … from None` parses as `cause=Constant(value=None)` and is rejected. A `Starred` or `**` argument is rejected (it is not a `Call` in `args`, or it is a keyword). The asymmetry with (a1) is deliberate: (a1) accepts any single `Expr(Call)`, so `sys.exit(1)` is carved, while (a2) needs its one argument to be a `Call`, so `raise SystemExit(1)` is not, because the ruling defined (a2) only as the equivalent of `sys.exit(<call>)`. Do not harmonise the two in either direction without a ruling (architect Q8-review fix) | the `If` node and its `test` `Compare` |
| (b) `import_fallback` | A `Try` (not `TryStar`) whose `body` is non-empty and holds only `Import` / `ImportFrom` statements; which has at least one handler; where every handler's `type` is exactly `Name(id="ImportError")` (an `as` name is allowed); and whose `orelse` and `finalbody` are empty | the `Try` node |
| (c) `type_checking` | An `If` whose `test` is exactly `Name(id="TYPE_CHECKING")` and whose `orelse` is empty | the `If` node |

**Not carved out** (each fails if it holds or is decision logic on a gated line; listed so that the edges are explicit):
- the near-misses of shape (a2) [ruled 2026-11-11: Q8] (before Q8 this list named `raise SystemExit(main())` itself; that shape is now accepted): `raise SystemExit` and `raise SystemExit()` (no call argument); `raise SystemExit(1)` or `raise SystemExit(code)` (the argument is not a `Call`); `raise SystemExit(main() or 1)` (the argument is a `BoolOp`, not a `Call`, so the whole guard is uncarved); `raise SystemExit(main(), 1)` (two arguments); `raise SystemExit(code=main())` (a keyword); `raise SystemExit(main()) from None` (a `cause`); `raise builtins.SystemExit(main())` or any other `func` that is not the bare `Name` `SystemExit`; `raise KeyboardInterrupt(main())` or any other exception name; a bare `raise`;
- a main-guard body of two or more statements;
- a main guard with an `else:`;
- `"__main__" == __name__`, `__name__ != …` or any other test form;
- `except ModuleNotFoundError:`, `except (ImportError, …):`, a bare `except:`, or `except Exception:`;
- a `try` body that holds anything but imports (for example `sys.path.insert(...)` followed by an import);
- `try`/`except ImportError` with an `else:` or `finally:`;
- `if typing.TYPE_CHECKING:`, `if not TYPE_CHECKING:`, or `if TYPE_CHECKING:` with an `else:`;
- any of these shapes inside a class or function body.

Decision logic **inside** a carved-out statement is still judged. Examples: `sys.exit(main() or 1)` in a main guard (the `If` and its `Compare` are carved, and the `BoolOp` fails); `raise SystemExit(main(a if b else c))` (shape (a2) holds, so the `If` and `Compare` are carved, and the `IfExp` fails) [ruled 2026-11-11: Q8]; an `if` inside an `ImportError` handler; a def inside a handler whose body holds an `if` (unmutatable, `non_top_level_function`, so it fails NQ-2).

#### 5.5.4 `decision_logic_findings(source, gated_statements)` → list

The function returns one finding per gated decision node: `{line, node_line, construct, region, unmutatable_reason, carve_out}`.
- `line` is the owning statement's first line, and `node_line` is `N.lineno`.
- `construct` is the AST class name (`If`, `Compare`, `ListComp`, …).
- `region` is one of `module`, `class` or `function`.
- `unmutatable_reason` is `null` or one of the six reasons in §5.5.2, and is always `null` outside the `function` region.
- `carve_out` is `null`, `main_guard`, `import_fallback` or `type_checking`, and is always `null` outside the `module` region.

Findings are sorted by `(line, node_line, construct)`.

**The shared predicate [ruled 2026-11-11: Q8].** A finding **is decision logic** if and only if its `carve_out` is `null`. A carved finding stays in the list and in the record (so the record shows what was excused), but **no rule counts it**. NQ-1, NQ-2, Q5, `has_decision_logic` (§5.5.1) and the `has_decision_logic` field of `unmutatable_gated_lines` (§5.10) all apply this one predicate, and nothing else decides whether a node is decision logic. It is implemented as **one** public function in `new_code_gate_logic`, `is_decision_logic(finding) -> bool` (true if and only if `finding["carve_out"] is None`). `has_decision_logic`, `decision_fail_reasons`, `zero_mutant_reason`, `unmutatable_gated_lines`, commit 4's `selection_reason` caller and the two Q5-SELF subprocess filters (§9.3) call it. No other code reads the `carve_out` key; `decision_logic_findings` only writes it (architect Q8-review fix). The rules read the list as follows:
- **Q5:** a decision-logic finding with `region` `module` or `class` fails the file (§5.10).
- **NQ-2:** a decision-logic finding with `region: function` and a non-`null` `unmutatable_reason` fails the file (§5.10). Because a carve-out is recognised only on a direct child of `Module.body` (§5.5.3), and `carve_out` is always `null` outside the `module` region, no function-region finding is ever carved. So the shared predicate changes **no** NQ-2 outcome; it is applied there so that the definition is the same for every rule.
- A decision-logic finding with `region: function` and `unmutatable_reason: null` is ordinary mutated code. Its decision logic is judged by the mutant score, and the rule adds no reason.
- **NQ-1:** a decision-logic finding of **any** region, among all the file's gated statements, makes NQ-1 fail (§5.10). Carved findings do not.
- A carved finding (`carve_out` non-`null`) has no role: no rule reports it.

Every decision-logic finding gets exactly one of the Q5 / NQ-2 / mutated roles, so a single line is never reported under both Q5 and NQ-2.

### 5.6 Test selection (SEL; ADR AD-6)

Selection runs for each gated Python file, in sorted path order.
1. **Context:** the union over gated statements of `contexts_by_lineno(file)[line]`. Remove the phase suffix with `rpartition("|")`, drop the empty context and sort. `selection_method: context`.
2. **Name fallback**, only if step 1 is empty: every tracked `tests/**/test_<stem>.py`, as whole-module node IDs. `selection_method: name_fallback`. For `__init__.py`, the stem is the package directory name.
3. **Repo-copy removal [round 4: U4; ADR §2c R3-G].** One collect-only run over the union of all files' selections, in the **checkout** (the gated merge tree), never in a workspace: the workspaces do not exist yet at selection time. **This supersedes ADR AD-6 step 3's "in the workspace".**
   - **Exact argv** (a list, no shell): `[<venv python>, "-m", "pytest", "--collect-only", "-q", "-m", "repo_copy", "-o", "addopts=", "-p", "no:cacheprovider", <sorted, de-duplicated union of node IDs…>]`, cwd = the checkout root, `start_new_session=True`, the remaining budget as its timeout (§5.13), and the same scrubbed env as `_enumerate` (no `NCG_*`, no plugin directory on `PYTHONPATH`).
   - **No tripwire.** The argv has no `-p _ncg_tripwire`, and the env carries no `NCG_*`, so the plugin is neither loaded nor active. `-o addopts=` clears the repo's `addopts` (`--tb=short -q`, and `--strict-markers` from §4.2), so the output format depends only on this argv. `-p no:cacheprovider` is the one addition to the ruled list: it stops the run writing `.pytest_cache/` into the checkout, and it changes neither collection nor output.
   - **Exit 0:** parse stdout. The node-ID lines are every line before the first empty line. Each must be non-empty, contain `::`, and start with `tests/`. Any other line in that block → exit 3 `repo_copy collection failed: unparseable output`. A selected ID equal to a collected ID is removed from that file's selection. A collected ID that lies **under** a selected ID (it starts with `<selected ID>::`, which happens for name-fallback whole-module IDs) is recorded but does not remove the container: §5.8's `-m "not repo_copy"` deselects it at run time. Both kinds are listed in the file's `removed_repo_copy`.
   - **Exit 5:** pytest's "no tests collected". The repo-copy set is empty; nothing is removed.
   - **Any other exit code** → exit 3 `repo_copy collection failed: pytest exited <rc>`, with the last 40 lines of output attached. A budget expiry during this run is §5.13's (every Python file gets `mutation_timeout`), never a pass.
4. **Empty after step 3:** the file fails `no_test_exercises` (REQ-16), unless NQ-1 applies (§5.10).
5. **Record:** `selection_method`, `selected_tests_count` and `selected_tests` (capped at 2,000 node IDs, with `selected_tests_truncated`).

### 5.7 Path-loaded and bare-imported modules (PL; ADR AD-12 plus ADR-A5)

The **canonical name** of a gated file is its repo-relative path with `/` → `.` and `.py` removed. For `__init__.py`, it is the package path. The message for every finding is fixed: **`<importer file> loads <gated path> as module '<loaded-as name>' (<via>) instead of the canonical 'import <canonical>' — convert to a canonical scripts.... import in this PR`**.

1. **Static pre-check** (cheap phase, every gated Python file with a non-empty selection). AST-scan each selected test module, every `conftest.py` on its path, and `tests/registry_guard.py`, `tests/tmp_hygiene.py` and `tests/automation/usage_support.py` (the shared loaders, F-6). Look for:
   - calls to `spec_from_file_location`, `SourceFileLoader`, `SourcelessFileLoader`, `runpy.run_path` and the repo helper `load_module_from_path`, where any string-literal or path-segment argument equals the gated file's relative path, filename or stem;
   - `import X` / `from X import …` where `X` (top segment) equals the gated file's stem, and the gated file's directory is one of the `sys.path` directories that `tests/conftest.py` inserts (`scripts/oversight`, `scripts/oversight/validators`). This is the bare-import case. The directory list is a constant in `new_code_gate_logic`, and a static test asserts it equals `conftest.py`'s insertions.

   Each finding is recorded with `via: static:<kind>`. The file fails `path_loaded_module` and is not mutated, which saves budget.
2. **Runtime recorder** (authoritative, inside every mutmut run; §5.18). The plugin records any load of the gated file under a non-canonical name, by three means: wrapping the loaders above; a **passive** `sys.meta_path` observer that resolves the origin of a requested name through `importlib.machinery.PathFinder` and records the requesting frame's file; and a `sys.modules` scan. **Passive means [round 2: T7]:** the observer's `find_spec` **always returns `None`**, on every path, so the real finders still resolve every import exactly as without it. It never raises: any exception inside it is caught and logged as an `observer_error` event (which the gate reports as exit 3, because the recorder can no longer be trusted), and `None` is returned. It never inserts into `sys.modules`. Static and behavioural tests S-PASSIVE (§9.3) enforce this. The `sys.modules` scan runs at session start, after each module's collection and after each test (any module whose resolved `__file__` is the gated file's copy, under a name other than canonical). **"The gated file's copy" means both `<NCG_WORKSPACE>/mutants/<rel>` and `<NCG_WORKSPACE>/<rel>`.** The first is the copy the tests actually import: mutmut copies the tree into `mutants/`, puts `mutants/` first on `sys.path` and removes the workspace root from it (`utils/file_utils.py:50-92`), and runs pytest with `--rootdir=.` inside `mutants/`. A recorder that watched only `<NCG_WORKSPACE>/<rel>` would see no load at all. The same two paths apply to the loader wrappers' "resolves to the gated file" test (architect round-5 fix). Findings carry `via: runtime:<kind>`, the importer file, and the phase (`session`, `collect:<file>` or `test:<nodeid>`). Any finding fails the file `path_loaded_module`, overriding any score.
3. **mutmut's message.** If mutmut prints the exact 3.8.1 string `tests recorded trampoline hits but none match any mutant key`, the file fails `path_loaded_module`. The message names the steps 1 and 2 findings if there are any. Otherwise it names the gated file and lists every selected test module as a candidate. The raw mutmut output is never the message, and it is never a pass (AC-17).
- **No exemption list exists, and none may be added.** A static test asserts that `new_code_gate_logic` contains no path-literal allow-list.

### 5.8 Mutation workspace (WS; ADR AD-5 plus ADR-A1, A2, A6)

For each file to be mutated (§5.9), in sorted order:
- **Layout [round 2: T7].** `run_tmp = tempfile.mkdtemp(dir=$RUNNER_TEMP or $TMPDIR)`. Inside it, two **sibling** directories: `run_tmp/workspace/` and `run_tmp/ncg-plugin/`. Neither is ever inside the other.
- The extract into `run_tmp/workspace/` is `git archive --format=tar <gated_sha> -- . ':(exclude,glob)**/.claude/**'` (ADR-A1; the gated merge tree, AR-1), unpacked with `tarfile` using `filter="data"` (no shell pipe).
- **Assertions:** no path component named `.claude` at any depth (AC-19), and no `mutants/` (AC-18). Either one failing → exit 3 `workspace contaminated: <path>`.
- **Pragma strip (H2, ADR-A8):** in the workspace copy of the gated file only, remove every comment token matching `#\s*pragma:.*no mutate` using `tokenize` (never a regex over source text), keeping the line otherwise byte-identical. Enumeration (§5.9) runs on this stripped text.
- **Generated `pyproject.toml`:** take the head file, remove the `[tool.mutmut]` table, and append the generated table. `tomllib` round-trip: every other table must equal the head's, and `tool.mutmut` must equal the intended dict. A mismatch → exit 3 `generated mutmut config failed round-trip`. The table:

| Key | Value |
|---|---|
| `source_paths` | sorted top-level tracked directories containing `.py` outside `tests/` (today `bin/`, `bootstrap/`, `scripts/`), plus the gated file itself if it is top-level |
| `only_mutate` | `[<gated path>]` |
| `do_not_mutate`, `do_not_mutate_patterns`, `type_check_command`, `cache_invalidation_files` | `[]` |
| `also_copy` | computed from the **extracted workspace's** top level, never from `git ls-files`, so `.claude/` can never be listed (architect round-3 consistency fix): every top-level directory (`dir/`) that is neither in `source_paths` nor `tests/` (mutmut copies those itself), plus every top-level tracked regular file except `pyproject.toml` and `setup.cfg` (ADR-A2; mutmut copies those itself, and none is tracked today). **No nested file entry, ever** (R6). A static logic test asserts every generated entry is either a top-level directory or a top-level file. With today's tree that is `.github/ audit/ contract/ docs/ packs/ prompts/ research/ signoffs/ templates/` plus 14 top-level files (`prompts/` arrives without its nested `.claude/`) |
| `pytest_add_cli_args` | `["--no-header", "-rfE", "--reruns", "1", "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "_ncg_tripwire", "-m", "not repo_copy"]` [architect review-1 ruling, ADR §2e RV-1]. ~~No `--reruns`.~~ **`--reruns 1` matches the `tests` job.** A deterministic kill fails twice and stays exit 1 (`killed`). A single flaky failure in the stats, clean or forced-fail run is absorbed as it is in `tests`. A flaky failure on a surviving mutant now needs two consecutive failures to read as a kill (R-17). The list never contains `--fail-on-flaky` (exit 7 would reintroduce false isolation fails), `--only-rerun`, `--rerun-except`, `--max-suite-reruns`, `--reruns-delay` or `-p no:rerunfailures`. Rerun attempts report outcome `rerun`, not `failed`, so the short-summary parse below and `-x` see only final failures (`-rfE` has no `r`/`R`). Pinned by A4d (updated) **`-rfE` is explicit** [round 4: U3; ADR §2c R3-D]: pytest's `-r` is `action="store"`, and mutmut appends `pytest_add_cli_args` **last** in every pytest argv (`runners/harness.py:128`, `["--rootdir=.", "--tb=native"] + params + pytest_add_cli_args`), so this value wins over any `-r` in the repo's `addopts`. The list never contains `--no-summary`, `-rN`, any other `-r…` / `--report-chars` value, or a second `-q`. mutmut's own `-q` plus `addopts`' `-q` gives verbosity −2, which suppresses pytest's final stats line but **not** the short test summary (`_pytest/terminal.py:1031-1050, 1320-1428`: gated only by `--no-summary` and the report chars). Pinned by A4d |
| `pytest_add_cli_args_test_selection` | the file's selected node IDs |
| `use_git_change_detection` | `false` |
| `mutate_only_covered_lines` | `false` (F-11) |
| `track_dependencies` | `false` (there is no cache, and a fresh workspace has nothing to compare against) |
| `timeout_multiplier`, `timeout_constant` | `15.0`, `1.0` (mutmut defaults, written explicitly) |
| `max_stack_depth` | `-1` |
| `process_isolation` | `"fork"` |
| `debug`, `log_to_file` | `false` |

- **Plugin placement (ADR-A6) [round 2: T7]:** copy `scripts/framework/new_code_gate_pytest_plugin.py` from the **checkout** to `run_tmp/ncg-plugin/_ncg_tripwire.py`, the sibling of the workspace. The mutmut subprocess env gets `PYTHONPATH=run_tmp/ncg-plugin` (prepended), `NCG_GATED_FILE=<rel path>`, `NCG_CANONICAL=<dotted>`, `NCG_WORKSPACE=<abs, resolved>` and `NCG_LOG=run_tmp/ncg-plugin/events.jsonl`. Everything else in the env is inherited, minus `GITHUB_TOKEN`, `GH_TOKEN` and `ACTIONS_*`, and also minus `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_OUTPUT`, `GITHUB_STATE` and `GITHUB_STEP_SUMMARY` [architect review-2 ruling, ADR §2f RV2-3: partial hardening only, residual ADR R-9]. These five names join `STRIPPED_ENV_NAMES`, so every child env built by `scrubbed_env` drops them.
- **Plugin location assertion [round 2: T7].** At `pytest_configure` the plugin logs a `plugin_loaded` event carrying `Path(__file__).resolve()`. After the mutmut run (whatever its exit code), the gate reads `events.jsonl` and requires (a) at least one `plugin_loaded` event, and (b) that every `plugin_loaded` path is **not** inside the resolved workspace (`Path.is_relative_to` is false) and equals the resolved `run_tmp/ncg-plugin/_ncg_tripwire.py`. If either fails → exit 3 `tripwire plugin not loaded from outside the workspace`. This check runs before any other interpretation of the run, because without a trusted tripwire no other result from the run is evidence.
- **Cleanup:** `run_tmp` (the workspace and the plugin directory) is removed in a `finally`, unless `--keep-workspace` was passed (local only). The repo's own `mutants/` is never read, written or deleted.
- **One mutmut invocation per gated file** (REQ-17, AC-15).

### 5.9 Mutants: enumerate, map, run, integrity-check, attribute, read back, classify (ADR AD-4)

Steps 1 and 2 run in the `_enumerate` subprocess, step 4 in the `mutmut run` subprocess and step 7 in the `_collect` subprocess. `measure` itself does steps 3, 5, 6, 8 and 9 on JSON, `events.jsonl` and captured text only [round 4: U1].

1. **Enumerate, in a per-file subprocess (ADR A9) [round 2: T2].** mutmut's `config()` is a process-global cache (F-19), so enumeration **never** runs in the `measure` process. For each file to be mutated, `measure` starts one subprocess: `<venv python> -P -m scripts.framework.new_code_gate _enumerate --file <rel path> --gated-lines-json <path>` (**superseded [architect review-2 ruling, ADR §2f RV2-1]:** the argv is now `[<venv python>, "-I", "-c", ENTRY_SNIPPET, <resolved checkout root>, "_enumerate", "--file", <rel path>, "--gated-lines-json", <path>]` and the env sets **no** `PYTHONPATH`. No checkout path is on the child's `sys.path`, so a root `libcst.py` / `mutmut.py` cannot shadow site-packages. The `gate_file` check below is unchanged; read "`-P` and `PYTHONPATH=<checkout>`" in this step and in step 7 as "the `-I -c ENTRY_SNIPPET` form"), as an argv list, with **cwd = that file's workspace** (`run_tmp/workspace/`) and `PYTHONPATH=<checkout root>`. `-P` stops Python from putting cwd on `sys.path`, so the gate code is imported from the checkout and never from the workspace copy (which, when the gate's own file is gated, is the pragma-stripped copy under test). mutmut reads its config from cwd, which is what A9 needs. The subprocess also gets `start_new_session=True`, the remaining budget as its timeout (§5.13), and the same scrubbed env as the mutmut run (without the `NCG_*` variables and without the plugin path). The child process:
   - calls `mutmut.configuration.reset_config()` first (defence in depth, so that an in-process test of the same function also reads a fresh config), then `mutmut.mutation.file_mutation.mutate_file_contents(rel_path, stripped_source, covered_lines=None, coverage_excluded_lines=None)` on the workspace copy, which is already pragma-stripped (§5.8). Its `mutant_names` is the file's full mutant set (F-3). **Those names are unqualified mangled names** (`x_<func>__mutmut_<n>`, or `xǁ<Class>ǁ<method>__mutmut_<n>`), so the child qualifies each one with `mutmut.utils.format_utils.get_mutant_name(Path(rel_path), name)` before emitting it. That is the key form that `.meta` (`__main__.py:206-207`), the `mutmut run <names…>` filter (`__main__.py:813`) and `_collect` all use, and the drift check compares like with like only in that form. `get_mutant_name` also strips `.__init__.`, so `__init__.py` keys are consistent (architect round-5 fix);
   - performs step 2 (mapping) in the same process;
   - writes one JSON object to stdout: `{schema: "new-code-gate-enum/1", file, gate_file, mutant_names[], gated_mutant_names[], line_map{name: [first lines]}, unmappable[]}`, and exits 0. Any exception → exit 3 with the error on stderr.
   - **`gate_file` (ADR §2c R3-A) [round 4].** The child's own `str(Path(__file__).resolve())` for the `scripts.framework.new_code_gate` module it is running as. `measure` requires `gate_file` to be inside the resolved checkout root (`Path.is_relative_to` true) **and** not inside the resolved workspace (`is_relative_to` false). Otherwise → exit 3 `gate subprocess imported from the workspace: <file>`. This is the runtime proof that `-P` and `PYTHONPATH=<checkout>` did what they are for, so a pragma-stripped or mutated workspace copy of the gate's own code can never run the gate.

   `_enumerate` is an internal phase. It is not part of the CLI contract in §5.1, the workflow never calls it (AC-30's test still asserts the workflow invokes only `measure` and `verdict`), and its argument parser refuses to run unless cwd contains a `pyproject.toml` whose `[tool.mutmut] only_mutate` equals `[--file]` (exit 3 otherwise). `measure` treats a non-zero exit, a timeout, unparseable stdout, a schema mismatch or a `file` that differs from the requested one as exit 3 `mutant enumeration failed: <file>` (and a bad `gate_file` as the R3-A exit 3 above). The JSON is parsed as untrusted data: names are matched against mutmut's key pattern `<module>.x_<func>__mutmut_<n>` (or the method form) and bounded in length. The design requires the enumerated set to equal what `mutmut run` generates. Step 7's drift check is the guard.
2. **Map to lines (inside the step-1 subprocess):** parse `MutatedFile.code` with libcst. For each name, get the mutant function with `mutmut.mutation.diff_apply.read_mutant_function(module, name)`, rename it to the original, `deep_replace` the original function in the original module (in memory, exactly as `apply_mutant` does), `difflib`-diff the two module texts, collect the changed original-side lines, and normalise each to its statement first line (§5.3). A mutant is **gated** iff that set intersects the gated statements. For a new file, every mutant is gated. A mutant whose diff is empty or unmappable → exit 3 `mutant could not be mapped: <name>`.
   **Superseded for cost, same result [architect review-3 ruling, ADR §2g RV3-1].** The whole-module render and diff per mutant is replaced by a **function-scoped** one. Once per file, resolve `WhitespaceInclusivePositionProvider` over the original module through `MetadataWrapper(orig_module, unsafe_skip_copy=True)`. Per mutant, `find_original` finds `target` as before. `orig_text = orig_module.code_for_node(target)` is cached per target. `start = position[target].start.line`. `mut_text = orig_module.code_for_node(read_mutant_function(mutated_module, name))`. The changed lines are `start - 1 + n` for each `n` in `changed_original_lines(orig_text, mut_text)`. Normalisation and the gated test are unchanged. If the scoped result is empty, the whole-module mapping above is computed for that mutant as a fallback, and if that is empty too the result is exit 3 as before. Do not use `PositionProvider`: it starts after the node's leading lines, while `code_for_node` renders them. Equivalence to the whole-module mapping is pinned by EQ-MAP (§9.3). Measured on the installed mutmut 3.8.1: 0.0012 s per mutant instead of 0.11 s.
3. **Pragmas (H2):** handled by §5.8's strip. Equivalence claims are not an input anywhere.
4. **Run:** if there are zero gated mutants, there is no run (§5.10). Otherwise run `<venv python> -m mutmut run <gated names…>` as an argv list, cwd = workspace, `start_new_session=True`, with the remaining budget as the timeout (§5.13). mutmut's own `--max-children` is left at its default (`os.cpu_count()`).
5. **Integrity checks, before anything interprets the run [round 4: U7; ADR §2c R3-E].** After every mutmut run, whatever its exit code, `measure` reads `events.jsonl` and applies these checks in this order. Each failure is exit 3, and when one fails nothing else from the run is used as evidence (no attribution rule, no read-back, no score). A run killed by the gate budget is §5.13's `mutation_timeout` and does not reach steps 5 to 9:
   1. **Plugin location assertion** (§5.8) → exit 3 `tripwire plugin not loaded from outside the workspace`.
   2. **Recorder health:** any `observer_error` event → exit 3 `path-load recorder failed` (§5.7.2). It comes before every attribution rule (R3-E), because a recorder that has failed can neither prove nor disprove a path load.
   3. **Executed ⊆ selected (AC-15)** [round 4: U7; moved up from round 2's step 9]. Every node ID the plugin logged (`pytest_runtest_logstart`, across the stats run, the clean run, the forced-fail run and every per-mutant run) must equal a selected node ID or lie under one (start with `<selected ID>::`, for name-fallback whole-module IDs). Anything else → exit 3 `mutation run executed unselected tests`, naming up to 20 of them. It sits here, ahead of the rules in step 6, so that no test-caused outcome (rules 1, 2, 4 and 5 of step 6) can be decided from a run that executed tests outside the selection.
   4. **Workspace integrity [architect review-3 ruling, ADR §2g RV3-7].** Every regular file under `<workspace>/mutants/` is compared with `<workspace>/<same path>`, by size and then sha256. Excluded: `mutants/<gated rel>`, mutmut's own outputs (`*.meta`, `*.spans`, `mutmut-stats.json`, `__pycache__/`) and the other files that mutmut 3.8.1 generates, which the coder lists from its source and pins in a test. Any other added, removed or changed file → exit 3 `mutation run modified the workspace: <up to 20 paths>`. A corrupted tree can make later mutants fail, and a fail reads as `killed`, so this is a false-pass guard.
6. **mutmut outcome, with attribution (ADR-A4, ADR §2c R3-C, R3-D) [round 2: T6; round 4: U2, U3].** In this order, the first matching rule decides. Rules 1 to 3 apply whatever mutmut's exit code; rules 4 to 7 need a non-zero exit code; rule 8 is exit 0.
   1. **Tripwire event** in `events.jsonl` (`repo_copy`) that names a node ID → the file fails `unmarked_repo_copy`, naming that node ID. Per-file fail (verdict exit 1).
   2. **Runtime path-load event** that names a node ID, a collected module or the session phase (§5.7.2) → the file fails `path_loaded_module`. Per-file fail.
   3. **The trampoline message** → §5.7.3 (`path_loaded_module`). Per-file fail.
   4. **No-test-case stop [round 4: U2; R3-C].** mutmut exits non-zero and its captured output contains the exact 3.8.1 string `Stopping early, because we could not find any test case for any mutant.` (`__main__.py:336-349`; it is printed after a stats run that exited 0, when no selected test reached any trampoline). mutmut ran no mutant, but it has already written `mutants/<rel>.meta` at generation time (`__main__.py:215`). The gate runs the step-7 read-back with `expect_unrun = true`, and then records **every gated mutant as `no tests`**: `mutants_killed: 0`, `mutant_status_counts: {"no tests": <gated count>}`, `mutation_ran: true`, `mutation_reason: null`. That is exactly what a normal run would record for mutants that no test reaches (exit code 33, `__main__.py:1033`). The file is then scored by step 9 as usual, so it fails `mutant_score_below_threshold` at 0.0 (ruling-eligible after S5, like any score fail). It is never `no_test_exercises`, and it is exit 3 only if step 7's read-back itself fails.
   5. **Isolation failure, attributed [round 4: U2; R3-C].** mutmut exits non-zero, its captured output contains **either** `failed to collect stats. runner returned ` (the stats run, `__main__.py:333`, which runs first and is where a selected test that fails alone normally shows up) **or** `Failed to run clean test` (the clean run, `__main__.py:994`), **and** the short-summary parse below yields at least one node ID, **and** every parsed ID is attributable to the file's selection (it equals a selected node ID, lies under one, or is the module part, `<file>.py`, of one) → the file fails `selected_test_fails_in_isolation`, naming the parsed node IDs and the stage (`stats` or `clean`), with the hint "this test fails when run alone in the mutation workspace". Per-file fail. **[architect review-3 ruling, ADR §2g RV3-4(a)]** The file record also gets `isolation_failure: {stage, node_ids[], summary_lines[], output_tail}`. `summary_lines` is the parsed short-summary section, verbatim, at most 20 lines of at most 2,048 characters each. `output_tail` is the last 60 lines of the ANSI-stripped combined output, at most 8 KiB, built by the same helper as `internal_errors`' tail. It is unhashed (§5.15.2), escaped wherever it is rendered, and never read by `decide()`. The check summary shows only `summary_lines[0]`.
   6. **Isolation failure, unattributed.** Either of the two rule-5 messages, but the parse yields no node ID, or any parsed ID is not attributable to the selection → **exit 3**, `internal_errors` entry `{code: "clean_run_unattributed", message: "clean run failed and no selected test could be identified"}` (the code and message are unchanged from round 2 and cover both stages; the entry gains `stage: "stats" | "clean"`), with the last 40 lines of mutmut output attached as a separate bounded field. It is never reported as a test failure, and the message never says "see log".
   7. **Any other non-zero exit** → exit 3 `mutmut exited <rc>`, with the last 40 lines of output in `internal_errors`. This includes mutmut's `FAILED: Unable to force test failures` (`__main__.py:247`), `failed to collect stats, no active tests found` (`:356`) and `Failed to collect list of tests` (`:689`), and a pytest usage error (pytest exit 4 raises `BadTestExecutionCommandsException`, `runners/harness.py:135`).
   8. **Exit 0** → step 7 with `expect_unrun = false`.

   **Short-summary parse (rules 5 and 6) [round 4: U3; R3-D].** The input is mutmut's captured stdout and stderr, combined, with ANSI escape sequences removed. The parse reads **only** pytest's short-summary section: find the **last** line matching `^=+ short test summary info =+$`; the section is the run of consecutive lines directly after it that start with `FAILED ` or `ERROR `, and it ends at the first line that does not. From each section line, the node ID is the text after the prefix up to the first ` - ` (pytest's crash-message separator) or the end of the line. No other line is ever read as a node ID, so mutmut's own `FAILED: Unable to force test failures` line, a `FAILED` inside a captured-output block or traceback, and the FAILURES section's headers are never misread. No section → no IDs → rule 6. The last section is used because pytest prints its real short summary at the end of the session, after any captured output that might imitate one. A forged section in a test's own output can only produce an attributed fail (exit 1), never a pass. The section is present because §5.8 passes `-rfE` explicitly. Because mutmut runs each stage with `-x`, the section normally holds one line. Pinned against the pinned pytest and mutmut versions (§5.2 step 1) by A4d and A4e.

   Rules 1 to 5 are the only per-file fails this step can produce. Rules 1, 2 and 5 are the ADR-A4 "attributed" test-caused classes. Rule 3 is the REQ-18 path (AD-12). Rule 4 is a score result, not a new fail class. None of rules 1, 2, 3 and 5 is ever ruling-eligible (§5.14).
7. **Read-back and cross-check, in a per-file `_collect` subprocess [round 4: U1; ADR §2c R3-B, R3-A].** `mutmut.stats` imports `mutmut.configuration.config` at module level (`stats.py:10-13`), so the read-back **never** runs in the `measure` process (§5.1 Imports). Run only after rule 4 or rule 8 of step 6. `measure` starts one subprocess, set up exactly like `_enumerate` (step 1, including its review-2 argv form [architect review-2 ruling]): `<venv python> -P -m scripts.framework.new_code_gate _collect --file <rel path>`, as an argv list, cwd = that file's workspace, `PYTHONPATH=<checkout root>`, `start_new_session=True`, the remaining budget as its timeout (§5.13), and the same scrubbed env (no `NCG_*`, no plugin directory). The child process:
   - refuses to run unless cwd contains a `pyproject.toml` whose `[tool.mutmut] only_mutate` equals `[--file]` (exit 3), as `_enumerate` does;
   - calls `mutmut.configuration.reset_config()` first;
   - reads `mutants/<rel>.meta` through `mutmut.mutation.data.SourceFileMutationData`, and maps each exit code to its name through `mutmut.stats.status_by_exit_code` exactly as mutmut maps it (`status_by_exit_code[code]`; the table is a `defaultdict` whose default is `suspicious`, so an unlisted code reads as `suspicious`, which is not killed). A `None` exit code is not mapped and stays `null` in both fields;
   - writes one JSON object to stdout: `{schema: "new-code-gate-collect/1", file, gate_file, exit_code_by_key{name: int | null}, status_by_key{name: str | null}}`, and exits 0. Any exception, a missing `.meta` included → exit 3 with the error on stderr.

   `_collect` is an internal phase, like `_enumerate`: not part of the §5.1 CLI contract, never called by the workflow. `measure` parses its stdout as untrusted data, with the same name pattern and length bounds as step 1, and applies, in order (each failure is exit 3):
   - a non-zero exit, a timeout, unparseable stdout, a schema mismatch or a `file` that differs from the requested one → `mutation results could not be read: <file>`;
   - `gate_file` inside the checkout and not inside the workspace (R3-A, as in step 1) → otherwise `gate subprocess imported from the workspace: <file>`;
   - **drift:** the `exit_code_by_key` key set must **equal** the enumerated set (step 1) → otherwise `mutant enumeration drift`;
   - **completeness:** with `expect_unrun = false`, every gated key must have a non-`null` exit code; with `expect_unrun = true` (step 6 rule 4), every gated key must be `null` → otherwise `mutant enumeration drift`.
8. **Classify (H3).** On the `status_by_key` strings from step 7 (or, under step 6 rule 4, `no tests` for every gated key). **Killed = `killed` or `timeout`.** Not killed = `survived`, `no tests`, `suspicious`, `skipped`, `not checked`, `segfault`, `check was interrupted by user`. These names are a constant in `new_code_gate_logic`, so classification needs no mutmut import. `caught by type check` cannot occur because `type_check_command = []`. If it, or any name outside the constant, appears → exit 3 `unexpected mutant status`. `mutant_status_counts` records every status.
9. **Score:** pass iff `killed * 100 >= 75 * total`, where `total` is the number of gated mutants. `mutant_score_pct = floor(killed*1000/total)/10`. Neither the denominator nor the numerator is reduced for any reason (H2).

### 5.10 Zero-mutant, unmutatable, and module-level or class-level code (NQ-1, NQ-2, Q5) [ruled 2026-11-11: Q5]

- **`decision_logic_findings`** (new record field): the §5.5.4 list for the file. It is capped at 5,000 entries; past that, `decision_logic_findings_truncated: true` is set, and the fail decisions below are still made on the full list.
- **`unmutatable_gated_lines`:** gated statements that mutmut will not mutate by construction (F-3). Each entry is `{line, reason, region, has_decision_logic}`. `reason` is one of {`decorated_function`, `enum_body`, `single_line_class`, `never_mutate_name`, `non_top_level_function`, `definition_time_expression`}, and the last two are new (§5.5.2). `region` is the statement's own region, worked out as in §5.5.2. Function-region statements are listed under the §5.5.2 reasons. Enum-body and single-line-class statements stay listed as in round 5, with `region: class`. Other module-level and class-level statements are **not** listed here. They are judged by Q5 instead. An entry's `has_decision_logic` is true if and only if a decision-logic finding (§5.5.4's shared predicate, `carve_out: null`) has that entry's `line` [ruled 2026-11-11: Q8]. Listed entries are function or class region, where `carve_out` is always `null`, so this changes no value today; it fixes the definition.
- **Q5 (new):**
  - If any finding has `region: module` and `carve_out: null`, the file fails **`module_level_decision_logic`**, with the message "module-level decision logic at <path>:<lines> — move the logic into a function so it can be mutated".
  - If any finding has `region: class` (`carve_out` is always `null` there), the file fails **`class_level_decision_logic`**, with the message "class-level decision logic at <path>:<lines> — move the logic into a function so it can be mutated".
  - `<lines>` is the sorted, de-duplicated `line` values of those findings, capped at 50 and then "…and N more".
  - This applies **whatever the file's mutant count or selection is**, which is the case round 5 left coverage-only. It also applies to enum attributes and single-line-class bodies, which are class region.
  - A Q5 fail does **not** stop the mutation run: the file is still enumerated and mutated, and its score is recorded. Like NQ-2, Q5 is decided in the cheap phase (§5.13) from the gated blob alone.
- **NQ-2:** if any decision-logic finding (§5.5.4's shared predicate) has `region: function` and a non-`null` `unmutatable_reason`, the file fails `unmutatable_decision_logic`, with the message "move the logic into an undecorated helper so it can be mutated" and the line numbers. The message is unchanged, including for the two new reasons. Lines in `unmutatable_gated_lines` with no decision logic are judged on coverage, which they are always part of. A carved-out statement is never function region, so Q8 changes no NQ-2 outcome (§5.5.4) [ruled 2026-11-11: Q8].
- **NQ-1 [ruled 2026-11-11: Q8]:** a file with **zero gated mutants** and an **empty selection** (after §5.6 step 3) passes only if its coverage passes (§5.4) **and** `has_decision_logic` over all its gated statements is false, where `has_decision_logic` applies the shared predicate (§5.5.1, §5.5.4). **The three carve-outs are applied here.** A file whose only decision nodes are carved (a carved import fallback, a carved `TYPE_CHECKING` block, a carved main guard) therefore passes NQ-1 if its gated coverage is ≥ 80%. It is recorded as `selection_method: not_required_zero_mutants`, `mutation_ran: true`, `mutants_total: 0`. The `mutation_ran: true` means the enumeration completed cleanly (REQ-12). If it has decision logic (any finding with `carve_out: null`) → fail `zero_mutant_decision_logic`, "move logic into a function so it can be mutated", and the message's `<lines>` lists only those uncarved findings' lines. In such a file, any uncarved module-level or class-level finding also gives its Q5 reason. Both reasons are listed, in §5.14's order. Every other empty selection → `no_test_exercises`.
  - **Coverage still applies (H2).** The carve-out removes only the decision-logic objection. It never makes a never-run line covered (§7.2). A carved file's unexecuted lines (the `except ImportError:` handler body on 3.12, a `TYPE_CHECKING` body, a main guard's body) count against its gated statements, so a **small** file of this kind can still fail `coverage_below_threshold`. That is a coverage fail, ruling-eligible after S5 like any other, and never `zero_mutant_decision_logic`.
- A file with zero gated mutants and a **non-empty** selection: no mutmut run, `mutation_ran: true`, `mutants_total: 0`. It is judged on coverage, Q5, NQ-2 and path-load (static only, because there is no run).

### 5.11 Shell (H1, H4; ADR AD-8)

- **Seam in `shell_logic_check.py`** (the only edit to it) [round 2: T3; ADR §2b condition 2]:
  - **The loop stays byte-identical and in place.** Lines 94 to 170 at `8113f8ba0` (from `stack: list[dict] = []` through the last `decisions.append(frame["lineno"])`) are not edited, re-indented or moved. In a `--unified=0` diff of the file, no hunk may touch any of those lines. So no loop line is gated, and the loop's existing tests remain the evidence for it.
  - **What changes around it.** The lines **above** the loop (today's `def _scan_file(...)` header, its docstring, and the `try`/`read_text`/`except OSError` block at lines 77 to 92) become the header and docstring of `decision_lines(lines: list[str]) -> list[int]`, which takes the already-split lines. The lines **below** the loop (today's 171 and 172) become `return sorted(decisions)`. A new `_scan_file(path)` follows it, with the unchanged signature and docstring sense: it reads the file exactly as today (`OSError` → `(0, None)`), calls `d = decision_lines(lines)`, and returns **`(len(d), min(d) if d else None)`**. (The round-1 text `min(d) or None` was wrong: `min([])` raises, F-20.)
  - **Duplicates preserved.** `decision_lines` returns `sorted(decisions)`: every counted entry, in line order, **with duplicates kept**. It never de-duplicates (no `set`), so `len(decision_lines(x))` equals today's count for every input. Sorting is needed because the loop appends in close order (F-20).
  - The counting, the exemptions and `_is_hard_exempt` are byte-for-byte unchanged. A public `is_hard_exempt(path)` alias is added for the gate.
  - **PR evidence.** The PR body attaches the output of `git diff --unified=0 origin/main...<branch head> -- scripts/oversight/validators/shell_logic_check.py` (the same pinned `-c diff.algorithm=myers` options as §5.3) (the hunk headers and lines), so a reviewer can see that no hunk falls in the loop.
- **Gate rule**, per gated `.sh` file:
  1. If `is_hard_exempt(path)` → no shell check, recorded `shell: {exempt: "hos_bootstrap"}`. The file-level exemption applies (H4).
  2. `head_lines = decision_lines(gated blob)`. `base_lines = decision_lines(base blob)` at `base_sha` (§5.2 step 5), using the old path for a rename and an empty list for a new file.
  3. **Fail** `shell_decision_logic` if any `head_lines` entry is an added or modified head-side line (H4: an edited counted line counts, and every line of a new file counts), **or** if `len(head_lines) > len(base_lines)`.
  4. The message is "shell decision logic at <path>:<lines> — move decision logic into tested Python (recommended home: scripts/automation/lib)" (H1).
- **Consequences of applying the existing definition unchanged (H4):** an edited **guard-clause** `if` (no `else`/`elif`) is not counted, so it passes. `for` loops are never counted (F-7), so they pass. The flag-parse `while`/`case` pair passes. These are recorded in §12 as residual R-7, not as decisions of this TD.
- **No shell exception path:** H5 excludes shell failures from rulings.

### 5.12 Exceptions (H5; ADR AD-10)

- **S2 ships no ruling input.** `fetch_rulings(pr, head, paths)` exists as the single seam and returns `[]` in S2. Every record carries `exception: null` and `exception_path: "unavailable until S5 (#2101 verifier); human admin merge is the only override"`. `decide()` accepts `rulings` but S2 always passes `[]`. No comment, label, env, file or flag is read for exceptions (AC-21).
- **`contract/gate-suspension.md` does not apply** to `new-code-gate` (H5: admin merge is the only override). The comment in `tests.yml` that names gate-suspension for the `tests` job is unchanged, because it is about that job.
- **Contract S5 must honour** (recorded here so S5 is not designed against a moving target): the item is `NCG:<path>`. A ruling is bound to the `blob_sha` of `<path>` **in the gated merge tree** (ADR §2b "H5 binding under AR-1") [round 2: T1] that was current when the act was made. At verdict time, the ruling applies only if the record's `blob_sha` for that path equals the bound blob. Any content change voids it, whether it came from the PR or from the base (H5, aligning with #2219/#2101). `pr_head_blob_sha` is recorded alongside for reviewers and for S3 matching; it is **not** a binding input. A ruling can flip only `coverage_below_threshold` and `mutant_score_below_threshold`. If any other fail reason is present, the outcome stays `fail`. S2 already records both blobs (§5.3), so S5 needs no record change.

### 5.13 Budget and timeouts (ADR AD-11; H3)

- `BUDGET_SECONDS = 1500` (25 min), a constant in `new_code_gate_logic` that is not read from env or config. It is measured from the start of `measure`.
- **Cheap phase first, for every file:** diff, statements, coverage, selection (one collect-only), static path-load, decision logic, shell, then enumeration and mapping (one `_enumerate` subprocess per file, §5.9.1, each in that file's workspace). Then the mutation phase, in sorted order: per file, the `mutmut run` and then (§5.9 step 7) its `_collect` subprocess [round 4: U1]. A file's workspace is created for its `_enumerate` call and reused for its mutmut run and its `_collect` call. The workspace-per-file and `mutants/`-absent assertions (§5.8) are checked before `_enumerate` and before the mutmut run (`_collect` runs after mutmut has created `mutants/`, so the absent check does not apply to it).
- **Per subprocess** (the repo-copy collect, `_enumerate`, `mutmut run` and `_collect`) [round 4]: the timeout is `deadline - now`. On expiry → `os.killpg(SIGTERM)`, wait 10 s, then `killpg(SIGKILL)`. The file in progress and every file not started get `mutation_ran: false, mutation_reason: timeout` and fail `mutation_timeout` ("mutation budget exhausted; split the PR"). The records are still written.
- **Per-mutant timeouts are mutmut's** (F-4) and count as **killed** (H3). A gate-budget kill is never a per-mutant timeout, because it is classified at file level as `mutation_timeout` (fail).
- **The job timeout** (`timeout-minutes: 30` on measure) → no records artifact → the verdict job exits 3.
- **Interrupts [architect review-1 ruling, ADR §2e RV-4].** (a) The real runner handles any `BaseException` raised while it waits on a child (`KeyboardInterrupt`, `SystemExit`) as it handles a timeout: SIGTERM to the child's process group, the grace wait, SIGKILL, and then it re-raises. The M1 fix (no unbounded `communicate()` after the signal) applies to this path too. (b) The `measure` and `run` CLI entry points install a SIGTERM handler that raises `SystemExit(143)`, so the `finally` workspace cleanup and (a) both run. The handler is installed only in those two entry points, never at import and never in `_enumerate` / `_collect`. It writes no records. An interrupted `measure` exits non-zero, and `verdict` then exits 3 on `--measure-result`. Test: INT-1 (a fake child that ignores SIGTERM is SIGKILLed after `KeyboardInterrupt`, and the workspace is gone), INT-2 (SIGTERM to a `measure` process removes its `run_tmp` and leaves no live child group).
- **Enumeration cost (M5) [architect review-1 ruling, ADR §2e RV-3].** `_enumerate` maps each mutant by rendering and diffing the whole module, which is O(mutants × module size). It is not optimised in this PR, because it is already budget-bounded and the worst case is `mutation_timeout`. The records must carry `_enumerate` seconds per file as a separate phase. §8.5 P-E is the trigger. **[architect review-3 ruling, ADR §2g RV3-1]** The trigger fired in the self-budget run (`_enumerate` took 75% to 93% of each gate module's time). The function-scoped mapping (§5.9 step 2) is now required, and it brings `_enumerate` to roughly generation time plus 0.0012 s per mutant. Each file record also carries `workspace_seconds`, `mutmut_seconds` and `collect_seconds` (§5.15.2).
- Durations (`seconds` per file and per phase) are recorded but excluded from `records_sha256` (AC-29).

### 5.14 `verdict`: `decide(records, rulings, thresholds) -> outcomes`

`decide` is pure. It never reads `os.environ` (AC-21 static test).

| Condition (per file) | Outcome / reason |
|---|---|
| any `internal_errors` entry for the file, or a global internal error | `fail`, overall exit 3 |
| `symlink_not_gateable` [architect review-1 ruling], `mode_not_gateable` [architect review-2 ruling], `not_measured`, `path_loaded_module`, `shell_decision_logic`, `selected_test_fails_in_isolation`, `unmarked_repo_copy`, `mutation_timeout`, `no_test_exercises`, `zero_mutant_decision_logic`, `unmutatable_decision_logic`, `module_level_decision_logic`, `class_level_decision_logic` [ruled 2026-11-11: Q5] | `fail` (not ruling-eligible: H5 covers thresholds only) |
| coverage below 80 / score below 75 | `fail` (`coverage_below_threshold` / `mutant_score_below_threshold`, ruling-eligible after S5) |
| a ruling-eligible fail with a matching blob-bound ruling (S5 only) | `excepted` |
| none of the above | `pass` |

- A file can carry several reasons. All of them are listed, in a fixed order (the table order).
- **Overall:** exit 3 if any internal error or an upstream result ≠ success. Otherwise 1 if any file is `fail`. Otherwise 0. **Zero gated files → exit 0** (AC-34).
- **Rendering:** §5.16.

### 5.15 Record schema and artifacts (REQ-24; the S3 ingest contract)

#### 5.15.1 Top level (`schema: "new-code-gate/1"`)

`schema`, `gate_version` (a constant string in `new_code_gate_logic`, bumped on any behaviour change), `phase` (`measure` or `verdict`), `mode` (`ci` or `local`), `pr`, **`gated_sha`** (the commit measured: `github.sha`, the merge commit, in CI; `HEAD` locally), **`pr_head_sha`** (`pull_request.head.sha`, checked equal to `<gated>^2` in CI; `HEAD` locally), **`base_sha`** (`<gated>^1` in CI; the merge base locally), `gated_tree` (`<gated>^{tree}`) [round 2: T1; the round-1 fields `merge_base_sha`, `head_sha` and `head_tree` are removed], `run_id`, `run_attempt`, `tool_versions` (all five pinned tools), `python` (major.minor), `coverage_core`, `budget_seconds`, `thresholds` (`{coverage: 80, mutant_score: 75}`), `files` (sorted by path), `internal_errors` (a list of `{code, message}`), `records_sha256` (sha256 of the canonical JSON of `files` with every `seconds` field removed: `sort_keys`, `separators=(",",":")`, `ensure_ascii`), `started_at`, `finished_at` and `seconds`. The verdict also has `overall` (`pass` or `fail`), `exit_code`, and `measure_records_sha256`, which must equal the measure value; otherwise exit 3.

#### 5.15.2 Per file

`path`, `kind` (`new` / `changed` / `shell`), `blob_sha` (gated tree), `pr_head_blob_sha` [round 2: T1], `gated_statements`, `gated_lines[]`, `gated_lines_truncated`, `executed_gated`, `coverage_pct`, `mutation_ran`, `mutation_reason` (`null` / `timeout` / `path_load` / `selection_empty` / `not_python` / `internal_error` / `blocked_by:<reason>`), `mutants_total`, `mutants_killed`, `mutant_score_pct`, `mutant_status_counts{}`, `unmutatable_gated_lines[]` (`{line, reason, region, has_decision_logic}`; `region` and the reasons `non_top_level_function` and `definition_time_expression` are new [ruled 2026-11-11: Q5]), `decision_logic_findings[]` (`{line, node_line, construct, region, unmutatable_reason, carve_out}`, §5.5.4) and `decision_logic_findings_truncated` [ruled 2026-11-11: Q5], `selection_method` (`context` / `name_fallback` / `not_required_zero_mutants` / `none`), `selected_tests_count`, `selected_tests[]`, `selected_tests_truncated`, `removed_repo_copy[]`, `path_load_findings[]` (`{importer, loaded_as, canonical, via, phase}`), `shell` (`null` or `{exempt, base_count, head_count, counted_on_changed_lines[]}`), `exception` (`null`), `exception_path`, `fail_reasons[]` (`{code, message}`), `outcome` (verdict only: `pass` / `fail` / `excepted`) and `seconds`. **[architect review-3 ruling, ADR §2g RV3-4]** Also: `enumerate_seconds`, `workspace_seconds`, `mutmut_seconds` and `collect_seconds` (each 0.0 when the phase did not run; their sum is ≤ `seconds`), and `isolation_failure` (`null`, or the §5.9 step 6 rule 5 object). These five fields, plus `seconds`, form `UNHASHED_FIELDS` (it replaces `TIMING_FIELDS`), which `records_sha256` removes at any depth (AC-29). All strings are length-bounded (paths ≤ 1024, messages ≤ 2048, node IDs ≤ 1024). Longer values are truncated with a `…[truncated]` suffix. That keeps S3's "bounded fields" check simple.

#### 5.15.3 Artifacts

| Artifact | Job | Content | `retention-days` | `if` |
|---|---|---|---|---|
| `coverage-contexts` | tests | `.coverage`, `coverage-meta.json` | 7 | success |
| `new-code-records` | new-code-measure | `new-code-records.json` | **90** | `always()` |
| `new-code-verdict` | new-code-gate | `new-code-verdict.json`, `new-code-summary.md` | **90** | `always()` |

**Uploads and re-runs [architect review-1 ruling, ADR §2e RV-5, RV-7].**
- All three uploads set `overwrite: true`, so a re-run of a single job does not fail on a same-name artifact from an earlier attempt. `upload-artifact@v4` names are unique per run.
- A same-name artifact pre-uploaded by PR code in `tests` is replaced, or makes the upload fail. Either way it cannot pass: the verdict decides only on a `success` measure result and on run-bound records (§5.1).
- **First-CI-run verification (the PR author records it in the PR body):**
  1. Re-run only `new-code-gate`. It must download the attempt-1 `new-code-records` and upload its verdict without a conflict.
  2. Re-run only `new-code-measure`. Its upload must replace `new-code-records`, and the downstream `new-code-gate` must judge the new records (the new `run_attempt`).
  3. If either fails, escalate to the architect before the context is made required.

**S3 matching [round 2: T1].** S3 matches a merged PR to its verdict on `pr_head_sha` (the merged PR's head), not on `gated_sha`: the merge commit is synthetic and is not the commit that lands on the base. 90 days is GitHub's maximum for a public repository (F-14). A workflow value above the repository setting is silently capped, so **after the first CI run the PR author reads the artifact's `expires_at` from the run's artifact list** (a public read). If it is under 89 days, the human raises **Settings → Actions → Artifact and log retention** to 90. This is a human action and is noted in the PR body. If the repo ever goes private, the maximum becomes 400 days and this value should be revisited. S3 has to ingest within the retention window. Its 14-day sweep (ADR AD-9) is well inside it.

### 5.16 Check output (REQ-25)

`verdict` writes a Markdown table to `--summary`, and the workflow appends that file to `$GITHUB_STEP_SUMMARY`. The columns are `File | Kind | Coverage (covered/gated) | Mutant score (killed/total) | Selection | Outcome | Reasons`, one row per gated file, sorted. That is followed by a totals line and, if there are any, the `internal_errors`. The fixed messages from §5.7 / §5.10 (Q5 included [ruled 2026-11-11: Q5]) / §5.11 appear in full under the table. Pipes and newlines in cell values are escaped. **Escaping, exact [architect review-2 ruling, ADR §2f RV2-4(b)]:** `_cell` applies, in order, `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`, then `\` → `\\`, then a `\` prefix on each of `` | ` [ ] ``, then CR and LF → space. It is used for every table cell and every detail and error line. With zero gated files the table is replaced by the line "No gated files in this PR."

### 5.17 Workflow contract (`.github/workflows/tests.yml`)

The two new jobs go in the same workflow file, so they inherit `on`, `concurrency` and the workflow-level `permissions: contents: read`.

**`new-code-measure`**
- `name: new-code-measure`, `needs: tests`, `if: always()`, `runs-on: ubuntu-latest`, `timeout-minutes: 30`, `permissions: contents: read`.
- **Gated commit (ADR AR-1) [round 2: T1].** All three jobs work on `github.sha`, the `pull_request` merge commit. The `tests` job keeps its default checkout, which resolves to `github.sha` (F-18); the sidecar records it as `head_sha`. Both new jobs pass `ref: ${{ github.sha }}` to `actions/checkout` **explicitly**, so the intent is visible in the YAML. The sidecar-head check (§5.2 step 3) proves that the `tests` job measured the same commit. A static workflow test asserts both explicit `ref:` lines.
- Steps: `actions/checkout@v4` (`ref: ${{ github.sha }}`, `fetch-depth: 0`, `persist-credentials: false`; full history so that `<gated>^1` and `<gated>^2` resolve) → `actions/setup-python@v5` (3.12) → `bash scripts/oversight/ensure_venv.sh` with `HOS_SKIP_PROJECT_REQUIREMENTS: "1"` → `actions/download-artifact@v4` `coverage-contexts` with `continue-on-error: true`, because a missing artifact must surface as exit 3 from the gate rather than as a step error that hides the records → `scripts/oversight/.venv/bin/python -m scripts.framework.new_code_gate measure --gated-sha ${{ github.sha }} --pr-head-sha ${{ github.event.pull_request.head.sha }} --pr ${{ github.event.pull_request.number }} --coverage-file .coverage --meta coverage-meta.json --out new-code-records.json --tests-result ${{ needs.tests.result }} --run-id ${{ github.run_id }} --run-attempt ${{ github.run_attempt }}` → upload `new-code-records` (`if: always()`, `retention-days: 90`, `if-no-files-found: warn`). There is no `--base-sha` argument: the base is `<gated>^1`, derived inside the gate (§5.2 step 5), so `pull_request.base.sha` (which can be older than the merge commit's first parent) is never used.

**`new-code-gate`** (the required context)
- `name: new-code-gate`, `needs: new-code-measure`, `if: always()`, `timeout-minutes: 5`, `permissions: contents: read`. **No `pull-requests: read`** in S2, because nothing reads PR data until S5 (decided, ADR §2b and AD-2) [round 2: T10]. S5 adds `pull-requests: read`, and `issues: read` only if ADR-2101's fetcher needs issue-side acts.
- **No trusted base (decided, ADR §2b Q2; residual ADR R-6) [round 2: T10].** The verdict code runs from the same commit as the other two jobs. A base checkout would defend nothing under a `pull_request` trigger, because the workflow YAML is itself PR-controlled. The control on gate weakening is CODEOWNER review of the protected surfaces.
- Steps: checkout (`ref: ${{ github.sha }}`, `persist-credentials: false`, `fetch-depth: 1`) → setup-python 3.12 → download `new-code-records` (`continue-on-error: true`) → `python -m scripts.framework.new_code_gate verdict --records new-code-records.json --out new-code-verdict.json --summary new-code-summary.md --measure-result ${{ needs.new-code-measure.result }}` → `cat new-code-summary.md >> "$GITHUB_STEP_SUMMARY"` in a step with `if: always()`. This is the only shell line, with no logic, and the file is always written, because verdict writes it before it exits → upload `new-code-verdict` (`if: always()`, 90 days).
- The system `python` is used, not the venv. `verdict` is stdlib-only (§5.1).
- **No secrets, no `actions/cache`, no `pull_request_target`.**

**Workflow edits required by the review-1 rulings [architect review-1 ruling, ADR §2e RV-5, RV-7].** The top-level session makes these edits in `tests.yml`, using the flag names the coder chooses. This is the intended behaviour:
- **`tests`:** the `coverage-contexts` upload gains `overwrite: true`. `run_tests.sh`'s `meta` call is unchanged: `meta` reads `GITHUB_RUN_ID` itself.
- **`new-code-measure`:**
  - The `download-artifact` step gains `path: ${{ runner.temp }}/ncg-in/coverage`. That is a fresh directory outside the checkout.
  - `measure` is passed `--coverage-file ${{ runner.temp }}/ncg-in/coverage/.coverage` and `--meta ${{ runner.temp }}/ncg-in/coverage/coverage-meta.json`, in place of the checkout-relative paths. All other arguments are unchanged, `--run-id` and `--run-attempt` included.
  - The `new-code-records` upload gains `overwrite: true`.
- **`new-code-gate`:**
  - The `download-artifact` step gains `path: ${{ runner.temp }}/ncg-in/records`.
  - `verdict` is passed `--records ${{ runner.temp }}/ncg-in/records/new-code-records.json` and the four binding inputs: `${{ github.sha }}`, `${{ github.event.pull_request.number }}`, `${{ github.run_id }}` and `${{ github.run_attempt }}`.
  - ~~`--out` and `--summary` stay in the checkout, so the summary step and the upload paths are unchanged.~~ Superseded by the review-2 edits below.
  - The `new-code-verdict` upload gains `overwrite: true`.
- **Static workflow tests** extend AR-1d and AC-30. They assert:
  - both `download-artifact` steps set a `path:` under `runner.temp`;
  - no gate input path in `measure` or `verdict` is checkout-relative;
  - `verdict` is passed all four binding values;
  - all three uploads set `overwrite: true`.

**Workflow and shell edits required by the review-2 rulings [architect review-2 ruling, ADR §2f].** The top-level session edits `tests.yml` (protected). The coder edits `run_tests.sh` and writes the tests. `E` stands for `ENTRY_SNIPPET`, written out literally in each place:
- **`new-code-measure` "Measure" step:** `scripts/oversight/.venv/bin/python -I -c "E" ${{ github.workspace }} measure …`. The arguments are unchanged except `--out ${{ runner.temp }}/ncg-out/new-code-records.json`. The records upload `path:` becomes `${{ runner.temp }}/ncg-out/new-code-records.json`.
- **`new-code-gate` "Apply thresholds" step:** `python -I -c "E" ${{ github.workspace }} verdict …`. The arguments are unchanged except `--out ${{ runner.temp }}/ncg-out/new-code-verdict.json --summary ${{ runner.temp }}/ncg-out/new-code-summary.md`.
- **"Publish step summary":** `cat "${{ runner.temp }}/ncg-out/new-code-summary.md" >> "$GITHUB_STEP_SUMMARY"`. **Verdict upload `path:`** is the same two files under `${{ runner.temp }}/ncg-out/`.
- **`run_tests.sh:106` `meta`:** `"$VENV_PYTHON" -I -c "E" <repo root> meta --coverage-file .coverage --out coverage-meta.json`. Use the script's existing resolved root, or `"$PWD"` if the script runs from the root. The `tests` job's paths stay as they are, because PR tests run in that job anyway (AF-8).
- **The gate writes outputs atomically.** It creates the parent directory, writes to a temp file in that directory and calls `os.replace` (`write_json`, the summary writer and the sidecar). It never follows a symlink at the destination.
- **INV-G (ADR §2f).** The `new-code-gate` job's steps are exactly: checkout, setup-python, download-artifact, the verdict step, the publish step and upload-artifact. It gets no venv, no `pip` and no `bash scripts/…`.
- **Static tests (WF-ENTRY, extends AR-1d / AC-30):** every gate invocation in `tests.yml` and `run_tests.sh` matches the wrapper with `ENTRY_SNIPPET` byte-for-byte. No file contains `-m scripts.framework.new_code_gate`. No gate invocation lacks `-I`. The `new-code-gate` step list equals the INV-G whitelist. No `--out` or `--summary` argument, `cat` source or upload `path:` in the two new jobs is checkout-relative.

**Header comment** of `tests.yml`: one paragraph on the two jobs, the required context, `if: always()` (the skipped-means-success trap), and "no override other than a human admin merge (#2304 H5)".

### 5.18 Pins, marker, plugin and guards

- **`scripts/oversight/requirements.txt` [round 2: T4]:** `pytest==9.2.0` (was `pytest>=8.0`), `pytest-cov==7.1.0`, `mutmut==3.8.1`, and the new entries `coverage==7.17.2` and `libcst==1.9.0`. Each gets a comment citing #2304 AF-1 / ADR-A7. ~~`pytest-rerunfailures` is unchanged~~ **`pytest-rerunfailures==16.7`** (was `>=14.0`) [architect review-1 ruling, ADR §2e RV-1]: it is now the sixth entry in `PINNED`, the version guard (§5.2 step 1), the sidecar `tool_versions` and the equality check (§5.2 step 2), and R-PIN. Its rerun semantics decide mutant exit codes. 16.7 requires `pytest>=8.2,!=8.2.2` and Python `>=3.10`. S2 confirms that it installs against `pytest==9.2.0` on 3.12 (a clean `ensure_venv.sh` run in CI is the evidence). `run_tests.sh:66` `pip install … mutmut` stays as it is (it is a no-op when the requirement is satisfied).
- **`repo_copy` marker:** registered in §4.2. S2 marks each test that copies, clones, worktree-adds or archives **the repository root**, at module level (`pytestmark`) or at function level, chosen by the coder for the narrowest correct scope. The candidates are F-16. The guard and tripwire decide which ones.
- **`tests/framework/test_repo_copy_marker_guard.py`:** AST-scans every `tests/**/*.py` for `shutil.copytree(src, …)` and for `subprocess`/`git` argv lists containing `clone`, `worktree add` or `archive`, where `src` or the repo argument is a repo-root expression (`REPO_ROOT`, `_REPO_ROOT`, `repo_root`, `ROOT`, `Path(__file__).resolve().parents[n]`, `Path(__file__).parent.parent`, or the output of `git rev-parse --show-toplevel`). Each such call must sit in a test or module marked `repo_copy`. It is a heuristic and is allowed to miss. The tripwire is the backstop.
- **`new_code_gate_pytest_plugin.py`** (loaded as `_ncg_tripwire`, §5.8).
  - **Env read once, then removed [round 4: U5; ADR §2c R3-H].** The variable names are the constant tuple `NCG_ENV = ("NCG_GATED_FILE", "NCG_CANONICAL", "NCG_WORKSPACE", "NCG_LOG")` in the plugin. At **module import**, and only then, the plugin reads every `NCG_ENV` variable into module state (a frozen record; `None` for an absent variable) and removes each of them from `os.environ` (`os.environ.pop(name, None)`). No other code in the plugin reads `os.environ` for an `NCG_*` name, and a static test asserts it (P-ENV). The consequences: a second, canonically imported copy of the plugin (`scripts.framework.new_code_gate_pytest_plugin`, which the plugin's own tests import inside a mutation run of the plugin file) finds no `NCG_*` in the env and stays inert; no subprocess a test starts inherits them; and a test cannot turn the real tripwire on or off by editing `os.environ` after the session starts.
  - **Inert unless activated.** The plugin is inert unless its module state holds a non-`None` `NCG_WORKSPACE` and `NCG_LOG`. The state is set only by the import-time read. The plugin's tests activate a copy only through an explicit seam that takes a mapping (for example `_load_state(mapping)`), never from the process env.
  - **Shape required by Q5 and NQ-2 (the plugin is a gated new file on its own PR) [ruled 2026-11-11: Q5].**
    - The import-time read is **one** module-level statement, `_STATE = _load_state(os.environ)`: a plain call, with no decision node. `_load_state(mapping)` is an undecorated top-level function that does every `pop` and builds the frozen record, so that logic is mutated.
    - The "is it active" test (`NCG_WORKSPACE` and `NCG_LOG` both non-`None`) lives in an undecorated top-level function. It is never a module-level `if`, `IfExp`, `BoolOp` or `Compare`.
    - `NCG_ENV` and the other module constants are literals, or calls with no decision node.
    - The pytest hooks (`pytest_configure`, `pytest_collectstart` / `pytest_collectreport`, `pytest_runtest_logstart`, `pytest_runtest_teardown` and any others the coder uses) are plain undecorated top-level functions. pytest finds hooks by name. A hook that needs `@pytest.hookimpl(...)` (for example `tryfirst` or `wrapper`) must have a body that is a single delegation to an undecorated top-level helper with no decision node, or it fails NQ-2 (`decorated_function`).
    - The `shutil.copytree` / `subprocess.Popen` / loader wrappers must **not** be declared with `@functools.wraps(orig)`. A decorated nested def is `decorated_function` at any depth (§5.5.2), and the wrappers' path checks are decision logic. Use `functools.update_wrapper(wrapper, orig)` after the def, or keep every check in undecorated top-level helpers that the wrapper calls.
    - The observer class is a top-level class. Its `find_spec` is a plain method, or has exactly one `@staticmethod` / `@classmethod`.
  - **Idempotent wrapping [round 4: U5].** mutmut calls `pytest.main` several times in one process (stats, clean, forced fail, and the forked per-mutant runs), and pytest calls `pytest_configure` on every one of them with the same, already-imported module. So installing the `shutil.copytree` / `subprocess.Popen` wrappers, the `sys.meta_path` observer and the loader wrappers is idempotent: each wrapper carries a marker attribute `__ncg_wrapped__` whose value is a sentinel object created once per plugin **module instance**, and a target whose marker is this instance's sentinel is not wrapped again; the observer is inserted only if no instance of **this module's** observer class is already on `sys.meta_path`. Idempotency is per copy on purpose: a canonically imported copy activated by a test through `_load_state` must still be able to wrap (over the real tripwire's wrapper), or that test would pass in the normal run and fail inside a mutation run. Wrapping twice within one copy would double-log events, and a second observer of the same copy would see its own wrapper's frames. An `uninstall()` function restores every original the copy wrapped and removes its observer; the plugin's tests call it in teardown.

  When active:
  - It wraps `shutil.copytree` and `subprocess.Popen`. **The protected roots are `NCG_WORKSPACE` and `NCG_WORKSPACE/mutants`** (architect round-5 fix; ADR §2d R5-A). Inside a mutation run the tests see `mutants/` as the repository root (`Path(__file__).parents[n]` from `mutants/tests/…` resolves there), and `mutants/` lies *inside* `NCG_WORKSPACE`, so a check against `NCG_WORKSPACE` alone would miss every real repo copy. A copy whose source resolves to, or contains, either protected root, or a git `clone`/`worktree add`/`archive` whose source or `cwd`/`-C` resolves to, or contains, either one, raises `NCGRepoCopyError("<nodeid>: copies the repository; mark it @pytest.mark.repo_copy")` and logs the event.
  - **Importer attribution [architect review-3 ruling, ADR §2g RV3-3(b)].** `importer_file()` walks out of the plugin's own frames and `<frozen importlib…>` frames, and also out of mutmut's trampoline frames: a frame whose `co_filename`, normalised with `os.path.normcase` and `/` separators, ends with `/mutmut/mutation/trampoline.py`. Without this, when the plugin gates itself, every importer reads as mutmut's `trampoline.py`. The event is always recorded; only its `importer` moves to the next frame. Test IMP-TRAMP (§9.3).
  - It records path-load findings (§5.7.2). Its `sys.meta_path` observer is passive: `find_spec` always returns `None` and never raises (§5.7.2, S-PASSIVE) [round 2: T7].
  - It logs a `plugin_loaded` event with its resolved `__file__` at `pytest_configure` (§5.8 location assertion) [round 2: T7].
  - It logs every executed node ID (a `pytest_runtest_logstart` hook).
  - At module level it imports only the stdlib and `pytest`. It imports no `scripts.*` module, because it runs from outside the workspace and must not pull in a gated file.
  - It writes JSON lines with `O_APPEND` to `NCG_LOG`, one line per event, each line under 4 KiB, so the writes are atomic across mutmut's forked children.
  - It never alters a test outcome except by raising the repo-copy error inside the offending test.

### 5.19 REQ-35: how the gate passes its own introducing PR, with no exemption list

The rule binds the gate's own PR. The PR is designed so that every gated file it touches is clean:

| File | Kind | Why it passes |
|---|---|---|
| `scripts/framework/new_code_gate.py`, `new_code_gate_logic.py`, `new_code_gate_pytest_plugin.py` | new | Their tests import them **canonically** (`from scripts.framework import new_code_gate_logic as ncg`). The logic is exercised **in-process** through seams: a `MutationRunner` protocol, a `Clock`, and coverage data built with the `CoverageData` API. The real-mutmut end-to-end tests run the CLI **as a subprocess** on fixture repos (marked `slow`). **What keeps them out of every context selection is that the e2e module imports no `scripts.framework.new_code_gate*` module in-process** (ADR §2b condition 4, static test S-E2E), not the `slow` marker. So real mutmut is never nested inside a per-mutant run, and the e2e tests cannot multiply mutation cost or earn coverage (AF-4) [round 2: T8]. The plugin's tests load it canonically and drive its hooks with `pytester`. The author must meet ≥ 80% / ≥ 75% on these files through the in-process tests alone |
| `scripts/oversight/validators/shell_logic_check.py` | changed | The changed lines are the `decision_lines` header and docstring, its `return sorted(decisions)`, the new `_scan_file` wrapper and the alias (§5.11). Lines 94 to 170 (the loop) are byte-identical and in place, so they are not gated, and the PR body attaches the `--unified=0` hunk list as evidence (ADR §2b condition 2). The PR converts `tests/oversight/test_shell_logic_check.py:13` to `from scripts.oversight.validators.shell_logic_check import main as sl_main, decision_lines`. That is the fix the gate demands, applied in the same PR. No other test imports `shell_logic_check` bare, and none path-loads it (Appendix A: `bare:1`, no path loader; ADR §2b condition 3) |
| `scripts/framework/run_tests.sh` | shell, changed | No counted construct is added or edited (§4.1) |
| Every other touched file | `.yml`, `.toml`, `.txt`, `.md`, `tests/**` | not gated |

- **The PR must not touch any other production `.py` file** (ADR §2b condition 1). If the coder finds it needs to, that is a design change and comes back to technical-design.
- **Q5 on the gate's own files [ruled 2026-11-11: Q5].** All three new modules are gated in full (`kind: new`), so every module-level and class-level statement in them is checked. They pass only if:
  - **`new_code_gate.py`**: the entry point is exactly `if __name__ == "__main__":` followed by one line, with no `else:` (carve-out (a)). That line is **either** `sys.exit(main())` **or** `raise SystemExit(main())`; both are accepted shapes (§5.5.3 (a1), (a2)) [ruled 2026-11-11: Q8]. Argv parsing or dispatch must not sit in the guard, and `main()` takes no argument that holds a decision node. `_enumerate` and `_collect` dispatch through `main()`. There is no module-level `try`, no `sys.version_info` check, and no conditional import. 3.12 has `tomllib`, so no `ImportError` fallback is needed.
  - **`new_code_gate_logic.py`**: every module constant (`PINNED`, `MEASURED_SOURCES`, the status-name sets, `BUDGET_SECONDS`, the bare-import directory list, compiled regexes, `gate_version`) is a literal, a name, a `BinOp` / set operation, or a call with no decision node in its arguments. There is no `X = a if c else b`, no `X = (os.name == "nt")`, and no comprehension with `if` at module level. Dataclass or `NamedTuple` classes hold only annotated fields and literal or `field(...)` defaults. No class body holds a condition. Methods that need logic are plain methods or carry exactly one `@staticmethod` / `@classmethod`. They are never `@property`, `@functools.cache` or `@contextlib.contextmanager` with decision logic inside (NQ-2).
  - **`new_code_gate_pytest_plugin.py`**: the shape in §5.18, "Shape required by Q5 and NQ-2". The module-level `NCG_ENV` read is the call `_STATE = _load_state(os.environ)`, which has no decision node, so it passes Q5.
  - **`shell_logic_check.py`**: the changed lines (§5.11) are the `decision_lines` header and docstring, `return sorted(decisions)`, the new `_scan_file` and the `is_hard_exempt` alias. All of them are function-region code or a plain module-level assignment, so Q5 finds nothing. The existing `if __name__ == "__main__":` block (its body holds an `if len(sys.argv) < 2:`) is **not** a carve-out shape, under Q8 as before (its body is more than one statement) [ruled 2026-11-11: Q8]. It is ungated only because the PR leaves its lines byte-identical; a shift in line numbers does not gate them. **The coder must not edit that block.** Editing it would fail `module_level_decision_logic` on the guard and on the nested `if`.
  - `run_tests.sh` is shell. `tests/**` and every `conftest.py` are outside the Python scope (§5.3), so Q5 does not apply to them, including `tests/conftest.py`'s `sys.path` insertions.
  - A static test, **Q5-SELF** (§9.3), gives the coder the answer before the self-budget run. It runs `decision_logic_findings` over the three new modules, with every statement gated, and asserts that no finding would fail Q5 or NQ-2. For `shell_logic_check.py` it asserts that every finding that would fail Q5 or NQ-2 lies inside the module's final `if __name__ == "__main__":` statement. The PR's `--unified=0` evidence (§5.11) shows that block untouched. The test runs the analysis **in a subprocess** (`sys.executable -c …` with cwd = the test's repo root), so it earns no coverage context and is never picked by a selection. It reads no `.git`, so G-NOGIT holds. It never runs inside a mutation workspace, where the gated file is mutmut's trampolined copy rather than the source.
- **Stdlib-only module level** (condition 5): §5.1 Imports, test S-STDLIB.
- **No in-process gate test needs the real `.git` or `.claude/` [round 4: U6].** Any test that runs gate code in-process (it imports or calls `new_code_gate`, `new_code_gate_logic`, `new_code_gate_pytest_plugin`, or `shell_logic_check`'s `decision_lines` / `_scan_file` / `is_hard_exempt`) will be in some gated file's context selection, so on this PR it runs inside a mutation workspace, which has no `.git` and no `.claude/` (§5.8). Such a test must therefore not read, run `git` against, or resolve any path into the real repository's `.git` or `.claude/`, directly or through a helper. Fixture repositories that a test builds in `tmp_path` with its own `git init` are allowed: they use the `git` binary, not the real `.git`. Tests that need the real `.git` or `.claude/` (for example the §6 wording tests over `.claude/agents/*.md`) must import no gate code, so that no context selection picks them. This is the failure class ADR §2b names ("selected tests that need the real `.git` or `.claude/`"), applied to the gate's own PR. Static test G-NOGIT (§9.3) checks it for the gate's test modules; the self-budget run below is the behavioural proof.
- **No in-process gate test may disturb the host mutmut's global state (architect round-5 fix).** On this PR the stats run and the clean run of `new_code_gate.py`'s mutation execute their tests **inside the mutmut process itself** (`runners/harness.py`: in-process `pytest.main`; only per-mutant runs fork). A test that calls the child-side `_enumerate` or `_collect` code in-process (A9b, A9c, A9d) and runs `mutmut.configuration.reset_config()`, or causes `config()` to load from its `tmp_path` cwd, would replace the host's cached `_config` (`configuration.py:224, 304-313`). The host's later `config()` calls (source walk, per-mutant CPU limits, `__main__.py:1044`) would then read the fixture's config. So every such test uses one shared fixture that saves `mutmut.configuration._config` before the call and restores the **same object** in teardown. It touches no other mutmut global. Test NOGLOBAL (§9.3) pins it. The child-side `reset_config()` call itself stays, because in the real subprocess it is correct. **[architect review-3 ruling, ADR §2g RV3-3(c)]** The stats run's trampoline reads `config()` on **every** call into the gated module (`mutmut/stats.py:150-157`). So no test may set `_config` to anything that is not a real `Config` while it calls gate code. A sentinel that proves reset-and-restore is `copy.copy(mutmut.configuration.config())`, never `object()`. Static test G-MUTSTATE (§9.3) pins it.
- **A test that reads gate source text runs no gate code in-process [architect review-3 ruling, ADR §2g RV3-3(a)].** In a workspace, a gated module's file on disk is mutmut's trampolined copy, and a test whose outcome does not depend on the active mutant can never kill one. So a test that reads the text of a `scripts/framework/new_code_gate*.py` file or of `shell_logic_check.py` (by `read_text`, `open`, `inspect.getsource` or `ast.parse` of a read) must make no in-process call into those modules, which keeps it out of every context selection. Static test G-SRCREAD (§9.3) pins it. There is **no** marker or list that removes tests from a selection other than `repo_copy`. A test that fails in the workspace is fixed, never excluded.
- **Condition 6 needs the full-suite sidecar [architect review-3 ruling, ADR §2g RV3-0].** A sidecar built from a subset of test files changes every selection, so a run on it is diagnostic only and is never condition 6 evidence. The PR body's per-file table gives mutants, `enumerate_seconds`, `workspace_seconds`, `mutmut_seconds`, `collect_seconds` and `seconds`.
- **Gate modules are imported at test-module level** in the gate's own test modules, never first inside a test function. A first import inside a test records the module's top-level statements under that test's context. That pulls the test into the selection, and with it any subprocess check that cannot pass in a workspace, such as S-STDLIB's `-S` case: the trampolined `mutants/` copy imports `mutmut.mutation.trampoline` at module level (`trampoline_templates.py:51-53`).
- **Self-budget evidence before the PR opens (condition 6) [round 2: T9].** On the final branch head, before `submit_pr.sh` is run, the coder runs `python -m scripts.framework.new_code_gate run` locally (after `run_tests.sh` has written a clean-tree sidecar for that head) over every gated file the PR has. The PR body records, per gated file: gated mutants, the file's mutation seconds from the records, and the local core count (`os.cpu_count()`). The **projection** is `Σ local seconds × local cores ÷ 4`, in minutes, for 4-vCPU CI. If the projection exceeds **20 minutes**, the coder stops and the matter **returns to the architect** before the PR opens. The budget is not raised, and the gate's own files are not exempted. The local run must also pass (it is the same gate), so this step doubles as the first local proof of condition 7. If the session's sandbox stops `run_tests.sh` from completing (§8.2.1 saw sandbox-caused test failures), the coder says so plainly and asks the human to run the two commands in their own terminal; the evidence is not estimated and the step is not skipped.
- **First-run proof (AC-34, condition 7):** the PR's own `new-code-gate` check must be green on its final head, with no exemption, and the PR body links the step summary.
- **The workflow runs from the PR's commit** (a `pull_request` trigger), so the introducing PR runs the new jobs. There is no trusted base (decided, ADR §2b Q2; residual ADR R-6).

## 6. S4 — agent and contract wording (exact text)

The `.claude/agents/**` edits (§6.1, §6.2) are **authored by the top-level session**, never by `coder` (CLAUDE.md #1347). The top-level author applies the text below verbatim, or with edits the architect approves. `contract/**` and `templates/**` are protected too, and their author is the top-level session or `coder` under CODEOWNER review. CORE stays stack-neutral and names no tool. "Python" is named as a stack, not a tool.

### 6.1 `.claude/agents/unit-test.md` (CORE)

| Line | Replace | With |
|---|---|---|
| 31 | `- **Mutant score ≥ 75%** (killed mutants / total non-equivalent mutants).` | `- **Mutant score ≥ 75%** (killed mutants / total mutants). Equivalent mutants are **not** removed from the denominator — the 25% headroom absorbs them. No pragma, exclusion comment, or "documented equivalent" claim reduces either count.` |
| 32 | the whole bullet | `- **Mutation testing is required wherever the stack supports it.** CORE names no tool. The installed pack names the coverage and mutation tools for the stack, or — only where the stack has no suitable mutation framework — disables mutation testing for that stack. Python is a stack with a mutation framework: for Python, mutation is never disabled and `Mutant_score_pct` is never N/A. When (and only when) the pack has disabled mutation for a non-Python stack, record that in the declaration (e.g. `Mutant_score_pct: N/A (no mutation framework for stack — disabled in PACK)`); the coverage target still applies.` |
| new paragraph after line 34 | — | `**Measured, never declared.** `Coverage_pct` and `Mutant_score_pct` are numbers copied from a tool run on the current head. "not run", "N/A" (except the PACK-disabled case above), sampled, estimated, or hand-computed values are never acceptable. Where the project runs a deterministic CI gate for these targets on new and changed code, the numbers come from that gate's output, and `Thresholds_met: true` is written only when that gate passed on the current head; iterate against the gate's local entry point (named in the project's CLAUDE.md or canonical entry-point list) until it passes. A gate failure you cannot fix within the round cap is a `test-resistance` escalation, never a declaration.` |
| 50 | `1. Measure coverage and run mutation testing; identify uncovered lines and surviving mutants.` | `1. Measure coverage and run mutation testing (the project's gate, where one exists); identify uncovered lines and surviving mutants.` |
| 54 | the whole paragraph | `A surviving mutant you believe is equivalent (it produces the same observable output as the original) still counts as surviving. Do not add a pragma or exclusion to hide it, and do not remove it from the count; note it in the declaration's `Notes:` if it matters. If equivalent survivors alone keep the score below target, that is a `test-resistance` escalation, not an exclusion.` |
| 56 | `…and any surviving non-equivalent mutants.` | `…and the surviving mutants (marking any you believe equivalent).` |
| 72 | `Mutant_score_pct: {N or N/A (disabled in PACK)}` | `Mutant_score_pct: {N — measured; N/A only when the PACK disabled mutation for a non-Python stack}` |
| 74-75 | `Surviving_equivalents: {N}` / `Equivalents_documented: true \| false` | `Surviving_equivalents: {N — informational only; never subtracted from the score}` (delete `Equivalents_documented`) |

The PROJECT region of `unit-test.md` is **not** edited. HOS's own command is named in CLAUDE.md through the row in §6.7, which the top-level session authors (§14 Q7) [ruled 2026-11-11: Q7].

### 6.2 `.claude/agents/oversight-evaluator.md` (Phase 1, line 145)

Replace `- For `test-unit`: is `Thresholds_met: true` present? If not → **COMPLIANCE FAIL**` with:

```
- For `test-unit`: is `Thresholds_met: true` present? If not → **COMPLIANCE FAIL**. If the step's diff
  (`base_sha..head_sha`) changes any `.py` file, `Coverage_pct` and `Mutant_score_pct` must each be a bare
  number (integer or decimal, optionally followed by `%`); any other value — `N/A`, `not run`, `sampled`,
  a range, prose, or an absent field — → **COMPLIANCE FAIL** (name the field and the value). The PACK
  N/A form is accepted only when the step changes no `.py` file. (#2304 REQ-32)
```

### 6.3 `contract/OVERSIGHT-CONTRACT.md`

- **§4 (lines 314 to 325):** the `test-unit` example keeps `Coverage_pct: 83` and `Mutant_score_pct: 77`. Replace `Surviving_equivalents: 2` / `Equivalents_documented: true` with `Surviving_equivalents: 2   # informational; never subtracted`. After the block, add: `Coverage_pct` and `Mutant_score_pct` are measured numbers. For any step that changes Python they must be numeric, and `N/A`, `not run`, sampled or hand-computed values are non-compliant (§7 condition 4a). `N/A` is allowed only where a PACK disabled mutation for a non-Python stack. Equivalent mutants are not excluded from the denominator.
- **§7:** after condition 4, add **4a.** "`test-unit` declaration on a step whose diff changes a `.py` file has a non-numeric `Coverage_pct` or `Mutant_score_pct` → COMPLIANCE FAIL (#2304)."
- **§3 line 253:** unchanged.

### 6.4 `templates/base-agent-register-examples.md:57-60`

Keep `Mutant_score_pct: 77`. Replace lines 59 and 60 with `Surviving_equivalents: 2   # informational; never subtracted`.

### 6.5 `docs/v0.3.0/BASE-AGENTS-SPEC.md`

- `:363`: drop `Equivalents_documented` from the field list and add "(`Mutant_score_pct` is measured; N/A only for PACK-disabled non-Python stacks, #2304)".
- `:371` and `:456`: append one sentence to each: "Python has a mutation framework, so a PACK may not disable mutation for Python (#2304)."

### 6.6 `packs/django/unit-test.md:39`

Replace `total non-equivalent mutants` with `total mutants (equivalent mutants are not excluded; the 25% headroom absorbs them — #2304)`. This file is shipped PACK text. The edit keeps the pack consistent with CORE.

### 6.7 `CLAUDE.md`: canonical entry-points row [ruled 2026-11-11: Q7]

`CLAUDE.md` is a protected surface (`scripts/framework/protected_surfaces.txt`). The row is **authored by the top-level session**, never by `coder`, and goes through CODEOWNER human review like the §6.1 and §6.2 edits. In the "Canonical entry points by task" table, add this row after "Running the PR-required test suite":

`| Running the new-code coverage + mutation gate locally on HEAD (needs a clean-tree run_tests.sh sidecar first) | scripts/oversight/.venv/bin/python -m scripts.framework.new_code_gate run |`

The command goes in backticks, as in the neighbouring rows. With this row, the CORE sentence in §6.1 ("the gate's local entry point (named in the project's CLAUDE.md or canonical entry-point list)") resolves in this repo. A wording test (`test_new_code_gate_agent_wording.py`) asserts that the row is present.

## 7. Consequences the PR must state

### 7.1 First-touch failures (path-load / bare import, PL) [round 2: T5]

- **Population, as the PR must state it:** "**at least 26 and an estimated 40 to 57 of the 95 tracked production `.py` files (about half)**".
  - **26 (exact lower bound):** modules bare-imported through `tests/conftest.py`'s `sys.path` injection, from 31 test files (F-5, an AST survey; the architect's independent re-count matches).
  - **39 (heuristic):** modules path-loaded by 46 test files, by a literal-match heuristic: a test file that calls a loader (`spec_from_file_location`, `SourceFileLoader`, `run_path`, `load_source` or `load_module_from_path`) and contains a string literal naming the production file or its stem. It can over-count (a literal can name a file the loader does not load) and under-count (a path built without a literal).
  - **57:** the union of the two, with an overlap of 8. The estimate's lower end, 40, is the ADR §2b figure.
  - Method: the architect's `survey.py`, re-run by this agent at `8113f8ba0` with the venv Python under `-I`. The round-1 figures ("21 per the brief", "at most 54") are withdrawn: the first was not computed here, and the second is not a ceiling.
  - **Appendix A** lists all 57 modules, tagged `bare:<n>` and/or `path:<n>` (number of importing test files). It is #2305's work list.
- **Other first-touch failure classes, additional to the above and not quantified:**
  - modules whose tests exercise them only through a subprocess, which earn neither coverage nor kills (ADR AF-4, R-1);
  - selected tests that need the real `.git` or `.claude/`, which fail in the mutation workspace as `selected_test_fails_in_isolation` (§7.2, R-9);
  - selections slow enough to exhaust the 25-minute budget (`mutation_timeout`, §5.13).

  The PR states these alongside the population figure. Their size is unknown, and no figure is given for them.
- **Effect:** the first PR that touches one of these modules fails `path_loaded_module` until it converts every selected test that loads the module non-canonically. The three modules the shared harness loads (F-6: `bootstrap/lib/hos_tmp_root.py`, `bootstrap/tmp_reaper.py`, `scripts/oversight/retry_rescue_logic.py`) need the **harness itself** converted (`tests/registry_guard.py`, `tests/tmp_hygiene.py`, `tests/conftest.py:105`), because every test loads them.
- **No exemption list.** This is intended pressure. #2305 converts the remainder in bulk. The worker meets it as a normal gate failure with a named fix.
- **Recommendation (not designed in):** sequence #2305's conversion of the shared harness and the `scripts/oversight/validators` bare imports early. These are the most frequently touched modules.

### 7.1a Module-level and class-level decision logic (Q5) [ruled 2026-11-11: Q5]

- **Population, as the PR must state it [ruled 2026-11-11: Q8]:** "**25** of the 95 tracked production `.py` files hold module-level or class-level decision logic that no Q5 carve-out covers. The file fails only if a PR edits one of those statements, or if the file is new."
  - **Q8 re-run [ruled 2026-11-11: Q8].** The survey was re-run on 2026-11-11 with carve-out (a2) added (scratchpad `q8_survey.py`, `python3 -I`, evidence only, not committed). It was run on the branch head `b14e062db`, which differs from `8113f8ba0` among production `.py` files only by the two new gate modules (both with no finding) and by `shell_logic_check.py`'s seam, which leaves its main guard unchanged. Without (a2) the same script reproduces the earlier 33 files, so the two runs compare like with like.
  - **Effect of the `raise SystemExit(<call>)` shape:** all 11 `raise SystemExit(main())` guards are now carved. **8 files pass Q5 because of it**, since the guard was their only finding: `scripts/oversight/agents_static_logic.py`, `changeset_logic.py`, `panel_logic.py`, `prompt_audit_logic.py`, `release_logic.py`, `second_review_logic.py`, `secret_scan_logic.py` and `validation_logic.py`. The other 3 (`release_artifact_logic.py`, `release_panel_logic.py`, `security_scan_logic.py`) lose the guard's findings but still fail on other module-level logic (a non-import `try`, a `BoolOp`, or a second `if __name__`-style block). So the population falls from 33 to **25**.
  - What the re-run found in the 25: 18 module-level `If` and 18 `Compare` nodes (mostly `if __name__` guards whose body holds an `if`, a `try` or more than one statement), 14 module-level `Try` nodes that are not import-only, 4 `BoolOp`, 2 `GeneratorExp` and 1 `DictComp` with `if`. It found no class-level findings. (Before Q8: 29 `If`, 29 `Compare`, the rest the same.)
  - Guard shapes in production today: 26 `sys.exit(main())`, 2 `sys.exit(_main(sys.argv[1:]))` (`scripts/oversight/lib/audit_log.py`, `lib/review_events.py`), 19 bare `main()` and, since Q8, 11 `raise SystemExit(main())` guards are carved out (58 of the 64 guards). The other 6, whose body holds an `if` or a `try`, a non-call statement, or more than one statement, are not (architect Q8-review fix: the 2 `sys.exit(_main(...))` guards were not counted).
  - The 25-of-95 figure counts the Q5 population only. The earlier 33-of-95 figure is withdrawn. (Before Q8, the architect re-ran the same classification independently on 2026-11-11, scratchpad script, `python3 -I`, not committed, and got the same 33 of 95 and the same node counts. **After Q8 the architect re-ran it independently again**, with a separately written classifier over the 95 files at `8113f8ba0`, and got the same 25 of 95, the same node counts, the same 8 cleared files, the same 65-of-95 union with Appendix A (17 overlapping, the same 8 Q5-only files), and 39 of 95 under the narrowed (a1) reading (architect Q8-review fix).)
  - **Combined first-touch population, PL plus Q5 [ruled 2026-11-11: Q8].** 17 of the 25 Q5 files are also in Appendix A's 57 (PL). The union is **65 of 95** files that can fail the first time a PR edits the relevant lines (66 before Q8: of the 8 files Q8 clears, 7 are also PL files and still fail on that). The 8 Q5-only files are `scripts/automation/agent_invoke_cli.py`, `dimension_registry_cli.py`, `dimension_sweep_cli.py`, `lib/cycle_log.py`, `lib/merge_authority.py`, `merge_authority_cli.py`, `overseer_merge_cli.py` and `scripts/framework/next_actor.py`. The PL half of this union keeps §7.1's caveat: 57 is a heuristic union that may over-count, so 65 is an upper-end figure, not exact. The difference in kind remains: a PL failure fires whenever any selected test loads the file non-canonically, while a Q5 failure fires only when a PR edits the uncarved statement itself. **The function-region NQ-2 population is separate, and the PR states it too:** 7 of the 95 files hold decision logic that §5.5.2 marks unmutatable: 6 files (30 nodes) under `decorated_function`, and 1 file (`second_review_logic.py`, 3 nodes) under `never_mutate_name` via `len(... or [])`. No production file today has a `non_top_level_function` or `definition_time_expression` finding, so the two new reasons add no first-touch failures at `8113f8ba0` (architect delta-review fix).
- **Effect:** a PR that edits one of these lines fails `module_level_decision_logic` with the named fix. For a guard the fix is to rewrite it as a one-line `sys.exit(main())` or `raise SystemExit(main())`, moving any other logic in the guard into `main()` [ruled 2026-11-11: Q8]. For a non-import `try` or a conditional constant, the fix is to move the logic into a function. There is no exemption list. This adds to §7.1's first-touch population, and the two overlap.

### 7.2 Other user-visible behaviour

- Code exercised only through a subprocess earns neither coverage nor kills (ADR AF-4). Test `main(argv)` in-process.
- `if TYPE_CHECKING:` blocks and other never-run lines count as uncovered (H2, `exclude=None`). The carve-out (§5.5.3 (c)) only stops the `if` itself from failing Q5. It does not make the body covered. A main guard's body line is uncovered in the same way [ruled 2026-11-11: Q5]. The same holds under NQ-1 since Q8: a zero-mutant, empty-selection file whose only logic is carved passes the decision-logic check, but its never-run lines still count, so a small file of this kind can fail `coverage_below_threshold` (§5.10) [ruled 2026-11-11: Q8].
- Decision logic in module-level or class-level code on a gated line fails, except for the three carve-outs (Q5, §5.10). That includes decorator arguments, non-trivial defaults and annotations on top-level functions and methods [ruled 2026-11-11: Q5].
- A selected test that depends on the real repo's `.git` (for example `git ls-files` at the repo root) fails in mutmut's `mutants/` copy. The file then fails `selected_test_fails_in_isolation`, with node IDs. The fix is a self-built fixture repo.
- Large PRs, or PRs whose tests are slow, can exhaust the budget and must be split.
- There is no in-gate exception until S5. A human admin merge is the only override.

## 8. Cost: typical added runner-minutes per PR

### 8.1 Model

Added minutes = `T_ctx` (context overhead on `tests`) + `T_up` (contexts artifact upload) + `T_measure_fixed` + Σ over gated files `T_file` + `T_verdict`. `T_file = T_ws + T_mutmut_setup + 2·T_sel + T_mutants`. `T_sel` is the selected tests' own runtime, run once for stats and once clean. `T_mutants` ≈ (killed × time-to-first-failing-test + survivors × T_set) / cores, where T_set is the selected tests that hit the mutant's function. Killed mutants are cheap: mutmut uses `-x` with tests sorted fastest first (F-4).

### 8.2 Measured (this session; Python 3.14, 16 cores; sandboxed)

| # | Measurement | Result |
|---|---|---|
| A | Subset (`test_claim`, `test_readopt`, `test_triage`, `test_validation_logic`): no coverage / default core / ctrace / ctrace+contexts / widened surface + contexts | 27.1 / 28.3 / 29.0 / 29.6 / 29.5 s. **Contexts on top of ctrace: +0.6 s (+2.1%).** Widening the surface: +0. Data file 115 KB → 377 KB (contexts) → 2.3 MB (widened) |
| B | `git archive` workspace extract, tree minus `.claude` | 1.6 to 1.8 s, 9,005 files (7,928 of them `audit/`) |
| C | Prototype per-file run: `claim.py`, all 225 mutants, selection `tests/automation/test_claim.py` (in-process logic tests) | **3.1 s** mutmut + 1.6 s workspace. 121/225 killed, matching `8113f8ba0`'s figure. The 55.7 s figure there ran without per-file selection |
| D | Prototype per-file run: `readopt.py`, the 315 mutants of `_decide_rest`, selection `tests/automation/test_readopt.py` (259 tests that build git repos; 65 of them hit the function, 3.7 s of runtime) | **246.8 s** (293 killed, 22 survived). About 0.78 s wall per mutant on 16 cores |
| E | Full suite, today's flags vs S1 flags (equivalence and overhead) | see §8.2.1 |

#### 8.2.1 Full-suite equivalence run (`s1_equivalence.py`, local, sandboxed)

| Run | Flags | Wall | Suite-wide total (2 dp, `--include` the three roots, old omit) | `.coverage` size |
|---|---|---|---|---|
| A (today) | three `--cov` roots, `pyproject` omit, default core | 900 s | **84.81** | 1.3 MB |
| B (S1) | six roots, run-time omit without `__init__`/`test_`/`conftest`, `COVERAGE_CORE=ctrace`, `--cov-context=test` | 943 s (**+4.8%**) | **84.81** | **28.9 MB** |

- **Equivalence holds locally:** 84.81 = 84.81 over the same file set. Both runs had the same sandbox-caused failures (`pytest_rc=1`: detect-secrets and `.claude/`-reading tests), so this is a method check, not the CI number. The CI repeat in §4.4 is still required.
- **Overhead:** on 3.14, A ran on coverage's default core (sysmon), so +4.8% includes the switch to ctrace. On CI's 3.12, ctrace is already the default, so the expected delta is the context cost alone (+2.1% in row A). That is roughly 0.3 to 0.7 min on a 12.6 to 14.5 min suite, which keeps the job well under the ADR's 22-min escalation line.
- **Artifact:** about 29 MB, so the upload and download cost roughly 5 to 15 s each.

### 8.3 Typical PR

Sources: F-17 (2.97 mutants per statement; median 89 added lines, about 55 gated statements → **about 160 gated mutants**, 1 gated file) and F-13 (CI fixed costs).

| Component | Estimate on CI (4 vCPU) |
|---|---|
| `T_ctx` + `T_up` | +2% of 12.6 to 14.5 min ≈ **0.3 min**, plus upload ≈ 0.2 min |
| `T_measure_fixed` (setup, checkout 12 to 16 s, venv 18 to 27 s, download, plan, upload) | ≈ **1.0 min** |
| `T_verdict` (checkout, setup-python, verdict, upload) | ≈ **0.4 min** |
| `T_file`, 160 mutants, in-process tests (row C scaled ×4 for cores, ×0.7 for size) | ≈ **0.3 min** |
| `T_file`, 160 mutants, git-heavy tests. Row D is 0.78 s wall per mutant on 16 cores, about 12.5 core-seconds per mutant, so about 3.1 s per mutant on 4 vCPU if CPU-bound. 160 × 3.1 s ≈ 8.3 min is the upper end; I/O-bound git work scales less than linearly with cores | ≈ **4 to 8 min** |

- **PR touching no gated Python** (≈ 66% of PRs, F-17): **≈ 1.9 min** added (0.5 + 1.0 + 0.4).
- **Median Python-touching PR:** **≈ 2.2 min** (in-process tests) to **≈ 6 to 10 min** (git-heavy tests).
- **Weighted over all PRs:** roughly **2.5 to 4.5 min** per PR.
- **p75/p90 Python PR** (370 to 1,200 mutants, 1 to 2 files, git-heavy): 10 to 25 min. That approaches the 25-min budget and fails as "split the PR".
- Public-repo standard runners are free (no billed minutes). The real costs are merge latency and the concurrent-job limit.

**Typical is under 10 min, but git-heavy tests can push it to the line.** That condition triggers the plan in §8.5.

### 8.4 Measurable only in CI

- Real 4-vCPU per-mutant throughput for git/subprocess-heavy tests. Local row D ran on 16 cores inside a bubblewrap sandbox, and the sandbox blocks multiprocessing sockets (mutmut's default `fork` isolation works). The ×4 scaling is an estimate.
- Full-suite context overhead and `.coverage` size on 3.12. The local run is 3.14, and tests that read `.claude/` fail under the sandbox.
- The repo's artifact-retention setting (F-14) and single-job re-run artifact access (ADR AD-2, verified in S2 per the ADR).
- **S2 obligation:** the records carry per-file and per-phase `seconds`. The PR body quotes them for the gate's own files.

### 8.5 Plan to cut cost (with triggers)

| Step | When | What | Soundness |
|---|---|---|---|
| P0 (in S2) | always | Per-file selection (not the whole suite) and only gated mutants. Already the design. Row C vs `8113f8ba0`'s whole-selection run: 3.1 s vs 55.7 s | exact |
| P1 (in S2) | always | Zero-gated-Python PRs skip enumeration, collection and mutmut, and open no coverage data beyond the sidecar check | exact |
| P2 (follow-up issue) | the median added minutes for Python-touching PRs over the first 20 gated PRs exceeds **10 min** (from `seconds` in the 90-day artifacts) | **Line-level narrowing.** Group a file's gated mutants by the set of tests whose contexts executed the mutant's lines. Run one mutmut invocation per group with that group's selection, merging groups whose selections differ by < 10% to bound per-invocation setup (~5 to 15 s) | exact: a test that never ran a mutant's line cannot kill it (ADR §4.1) |
| P3 (needs an ADR amendment; ADR AD-5 rejects a v1 cache) | P2 is insufficient | A per-file result cache keyed on sha256 of: gated blob, gated-line set, selected node IDs, blobs of every file the selected contexts executed in-process (from the coverage data), every `conftest.py` and test module on the path, every non-`.py` file under `tests/`, `pyproject.toml`, `requirements.txt`, tool versions and `gate_version`. Scope is `pull_request`, readable only by the same PR (GitHub cache scoping). Pays off on re-pushes of the same PR, which is the unit-test ↔ coder loop | sound for in-process Python inputs. Residual: data files read from outside `tests/`. Hence an ADR decision, not a TD one |
| P-E [architect review-1 ruling, ADR §2e RV-3] | in the REQ-35 self-budget evidence or any CI run, a file's `_enumerate` time exceeds **60 s**, or exceeds **25%** of that file's mutation-phase seconds | **Function-scoped mapping.** Diff the original function's rendered code against the mutant function's, and offset the result by the function's start line (libcst `PositionProvider`). Do not render and diff the whole module per mutant. Land it with an equivalence test against the whole-module mapping over the gate's own files | exact, if the equivalence test holds. Until then the whole-module mapping stays, and its cost is budget-bounded (a timeout fail, never a pass). **[architect review-3 ruling, ADR §2g RV3-1] Fired** in the self-budget run. It is required in S2, with `WhitespaceInclusivePositionProvider` and EQ-MAP (§5.9 step 2) |
| P4 | never for cost | Matrix sharding by file cuts wall-clock time, not runner-minutes | — |

## 9. Tests

### 9.1 Test files

| File | Kind |
|---|---|
| `tests/framework/test_new_code_gate_logic.py` | pure functions: diff parsing, statement mapping, decision logic (regions, unmutatable reasons, the three carve-outs [ruled 2026-11-11: Q5]), selection, mapping, classify, `decide`, schema, rendering |
| `tests/framework/test_new_code_gate_measure.py` | `measure` in-process on fixture git repos (built in `tmp_path`), fake `MutationRunner`, `CoverageData` built through the API, fake `Clock`. The `MutationRunner` seam covers all four subprocesses (repo-copy collect, `_enumerate`, `mutmut run`, `_collect`) [round 4: U1], so the fake runner returns their JSON and text without importing mutmut |
| `tests/framework/test_new_code_gate_plugin.py` | the plugin through `pytester`: tripwire, alias recorder, executed-node log. **Autouse fixture [round 4: U5; R3-H]:** before every test in the module, for **every** name in the plugin's `NCG_ENV`, it either sets the variable to a value under that test's `tmp_path` (tests that ask for an active plugin) or deletes it (`monkeypatch.delenv(name, raising=False)`, the default). It also resets the canonical copy's module state to inert, and in teardown calls `uninstall()`. So no test in the module can see the gate's real `NCG_*` (already removed by the real tripwire at import), and no test can activate a copy that writes to the gate's real `events.jsonl` or wraps over the real tripwire after the test ends. A test that needs an active copy activates it through `_load_state(mapping)` with `tmp_path` values. P-ENV pins this |
| `tests/framework/test_new_code_gate_e2e.py` (`@pytest.mark.slow`) | the CLI as a **subprocess** on fixture repos with real coverage and real mutmut. A handful of cases |
| `tests/framework/test_new_code_gate_workflow.py` | static checks of `tests.yml`, `run_tests.sh`, `requirements.txt`, `pyproject.toml` and `hos_required_contexts.txt` |
| `tests/framework/test_new_code_gate_agent_wording.py` | static checks of the S4 Markdown |
| `tests/framework/test_repo_copy_marker_guard.py` | §5.18 |
| `tests/framework/test_branch_protection_contexts.py` | extended for AC-31 |
| `tests/oversight/test_shell_logic_check.py` | canonical import, plus `decision_lines` cases. Every existing case must pass unchanged |

Fixture repos are built by the tests themselves and never copied from the real repo. Tests use `tests.tmp_hygiene` helpers (#2054). No network and no `gh`.

### 9.2 Per-AC mapping (34)

| AC | Test (file : name) | Asserts |
|---|---|---|
| AC-1 | logic : `test_new_file_coverage_boundary_79_fails_80_passes` | 79/100 → `coverage_below_threshold`; 80/100 → no coverage reason |
| AC-2 | measure : `test_changed_lines_79_fail_despite_file_above_80` | gated 79% fails while the whole file is 95% |
| AC-3 | measure : `test_changed_lines_80_pass_despite_file_below_80` | legacy debt is not gated |
| AC-4 | logic : `test_new_file_mutant_score_boundary_74_fails_75_passes` | 74/100 → fail; 75/100 → pass |
| AC-5 | measure : `test_changed_lines_survivors_26pct_fail_unchanged_ignored` | only gated mutants count; survivors on ungated lines do not |
| AC-6 | measure : `test_new_file_outside_source_paths_is_mutated` | a file under `bootstrap/` is enumerated and run |
| AC-7 | measure : `test_new_file_outside_coverage_source_measured` | a `bootstrap/` file's data is read; low → fail. Plus `not_measured` for a new top-level dir |
| AC-8 | logic : `test_shell_new_file_if_else_fails_guard_and_flagparse_pass` | exact H1 message; guard-only and flag-parse-only files pass |
| AC-9 | logic : `test_shell_changed_case_fails_untouched_logic_passes` | an added `case` fails; a diff touching only non-decision lines passes |
| AC-10 | measure : `test_budget_exhausted_records_timeout_and_fails` | fake clock; the in-progress and not-started files get `mutation_ran: false, mutation_reason: timeout` (field name per §5.15.2; architect round-3 consistency fix); verdict exit 1; killpg called (fake) |
| AC-11 | measure : `test_no_contexts_no_name_match_fails_no_test_exercises` | |
| AC-12 | measure : `test_empty_context_uses_name_fallback_recorded` | `selection_method: name_fallback` |
| AC-13 | measure : `test_selection_only_tests_executing_gated_lines` | a test that ran only an ungated line is excluded |
| AC-14 | measure : `test_repo_copy_test_removed_and_listed_only_test_fails` + `test_repo_copy_collect_argv_and_exit_codes` [round 4: U4] | the collect argv is exactly §5.6 step 3's list (no `_ncg_tripwire`, `-o addopts=`, cwd = checkout, no `NCG_*` in env); exit 5 → nothing removed; exit 0 → the parsed IDs removed and listed; a container selection keeps its ID and lists the collected child; exit 2 → exit 3 |
| AC-15 | e2e : `test_mutation_run_executes_exactly_selected_tests` + logic : `test_generated_config_selection_equals_selection` | plugin log ⊆ selection, and equals it on the stats run; the suite is never run |
| AC-16 | measure : `test_static_spec_from_file_location_fails_with_named_fix` + `test_bare_sys_path_import_fails_with_named_fix` | exact §5.7 message |
| AC-17 | measure : `test_mutmut_trampoline_message_translated` | fake runner output with the exact 3.8.1 string → `path_loaded_module`, not raw output |
| AC-18 | e2e : `test_stale_mutants_tree_in_checkout_has_no_effect` + measure : `test_tracked_mutants_dir_exits_3` | |
| AC-19 | measure : `test_workspace_has_no_claude_at_any_depth` | the fixture tracks `.claude/x` **and** `prompts/.claude/y` (F-1) |
| AC-20 | logic : `test_no_ruling_input_in_s2_failing_file_stays_fail` | S2 part: `fetch_rulings` → `[]`, `exception_path` text. The full AC-20 is **S5** |
| AC-21 | logic : `test_decide_reads_no_environment` (static: no `os.environ`/`getenv` in `new_code_gate_logic`) + measure : `test_env_label_flag_cannot_turn_fail_to_pass` | sets env vars, creates a `labels.txt`, and passes unknown CLI flags (exit 2) — the outcome is unchanged |
| AC-22 | logic : `test_record_has_every_req24_field` | the excepted case is **S5**. The field list includes `decision_logic_findings`, `decision_logic_findings_truncated` and `unmutatable_gated_lines[].region` [ruled 2026-11-11: Q5] |
| AC-23 | logic : `test_summary_table_per_file_columns` | |
| AC-24 | logic : `test_verdict_artifact_matches_schema_v1_and_sha` | S2 part. Ingest is **S3** |
| AC-25 | workflow : `test_no_cache_in_gate_jobs_or_code` | **N/A while no cache exists** (ADR D-5): no `actions/cache`, no cache directory |
| AC-26 | measure : `test_internal_error_injection_exit_3_with_cause` (parametrized: missing coverage data, sidecar head mismatch, version mismatch, **sidecar-vs-install version mismatch, Python major.minor mismatch, merge commit with one parent, `<gated>^2` ≠ PR head, enumeration subprocess failure / bad JSON, plugin loaded from inside the workspace or not at all, unattributed clean-run failure, observer error** [round 2], **`_collect` subprocess failure / bad JSON, `gate_file` inside the workspace, executed-but-unselected test, repo-copy collect exit other than 0 or 5, unparseable repo-copy collect output** [round 4], mutmut crash, unparseable meta, enumeration drift, config round-trip, diff failure) | |
| AC-27 | measure : `test_zero_mutants_clean_pass_total_0` + `test_mutmut_error_fails` | |
| AC-28 | e2e : `test_pr_meeting_all_targets_passes` | |
| AC-29 | measure : `test_twice_identical_records_sha256` | |
| AC-30 | workflow : `test_ci_invokes_only_measure_and_verdict_entry_points` + `test_new_jobs_if_always` | |
| AC-31 | branch_protection : `test_new_code_gate_context_registered_and_job_named` | |
| AC-32 | wording : `test_unit_test_core_and_contract_disallow_na_for_python` | no "non-equivalent", no `N/A (disabled in PACK)` without the non-Python qualifier, no `Equivalents_documented` |
| AC-33 | wording : `test_evaluator_phase1_numeric_mutant_score_rule` | the §6.2 text present in the CORE region |
| AC-34 | measure : `test_noop_diff_zero_files_pass` + the PR's own CI run (§5.19) | |

### 9.3 Ruling and finding tests (beyond the ACs)

| ID | Test | Asserts |
|---|---|---|
| R-H2a | measure : `test_pragma_no_cover_on_gated_line_still_counted` | |
| R-H2b | measure : `test_pragma_no_mutate_stripped_block_pragma_on_unchanged_line_does_not_shield` | |
| R-H3 | logic : `test_timeout_status_counts_killed_segfault_does_not` | |
| R-H4a | logic : `test_hos_bootstrap_sh_exempt` | |
| R-H4b | logic : `test_edited_counted_if_line_fails_edited_guard_line_passes` | |
| R-H4c | logic : `test_for_loop_not_counted` (pins the inherited residual R-7) | |
| R-H5 | logic : `test_record_carries_blob_sha` | |
| R-NQ1 | measure : `test_zero_mutant_empty_selection_no_logic_passes` / `…_with_logic_fails_move_into_function` | |
| R-NQ2 | measure : `test_decorated_function_decision_logic_fails_undecorated_helper` / `…_without_logic_reported_only` | |
| R-DL | logic : `test_has_decision_logic_each_node_type` (parametrized over the §5.5.1 types, including `Match` (Q4, confirmed [ruled 2026-11-11: Q4]) and the comprehension-with-if) | a comprehension whose generators all have empty `ifs` is not a decision node |
| **Q5-MOD** [ruled 2026-11-11: Q5] | logic : `test_module_level_decision_logic_fails_move_into_function` (parametrized: module-level `if`, `for`, `while`, non-import `try`, `try`/`except*`, `match`, an `Assign` holding a `BoolOp`, a `Compare`, an `IfExp`, a list / set / dict / generator comprehension with `if`, an `IfExp` inside a module-level lambda, and a `with` block whose body holds an `if`) | each case → `module_level_decision_logic`, exact message "module-level decision logic at <path>:<lines> — move the logic into a function so it can be mutated", correct `line`, `node_line` and `construct`. The same source with the statement on an **ungated** line of a changed file → no finding and no reason |
| **Q5-CLS** [ruled 2026-11-11: Q5] | logic : `test_class_level_decision_logic_fails` (parametrized: a class attribute holding an `IfExp`; an `if` in a class body; a `Compare` in an enum member value; a single-line class `class A: x = a or b`; the body of a nested class; a method default `def m(self, x=a == b)`; a method decorator argument `@deco(1 if c else 2)`) | each case → `class_level_decision_logic` with the class-level message, and **not** `unmutatable_decision_logic`. Enum and single-line-class cases still appear in `unmutatable_gated_lines` with `region: class` |
| **Q5-MAIN** [ruled 2026-11-11: Q5; amended Q8] | logic : `test_main_guard_carve_out_exact_shape` | **Pass** (no Q5 reason, finding with `carve_out: main_guard`): `if __name__ == "__main__":` + `sys.exit(main())`; the same + `main()`; the same + `sys.exit(_main(sys.argv[1:]))`; **the same + `raise SystemExit(main())`, and + `raise SystemExit(_main(sys.argv[1:]))` [ruled 2026-11-11: Q8]** (`raise SystemExit(main())` moved here from the fail list). **Fail** `module_level_decision_logic`: two body statements; an `else:` branch; `"__main__" == __name__`; `__name__ != "__main__"`; the guard nested in another module-level `if` or in a class body; the guard body `sys.exit(main() or 1)`, where the `If` is carved but the `BoolOp` fails on the body line |
| **Q5-IMP** [ruled 2026-11-11: Q5] | logic : `test_import_fallback_carve_out_exact_shape` | **Pass**: `try: import x` / `except ImportError: x = None`; `try: from a import b` / `except ImportError as e: b = None`; two handlers, both `ImportError`. **Fail** `module_level_decision_logic`: `except ModuleNotFoundError:`; `except (ImportError, OSError):`; bare `except:`; a `try` body with `sys.path.insert(...)` before the import; an `else:` or `finally:` clause; the same shape inside a function body (function region, judged by mutation, so no Q5 reason) or inside `if TYPE_CHECKING:` (not a direct `Module.body` child, so it fails). **Handler contents still judged**: an `if` in the handler → `module_level_decision_logic` at the `if`'s line; a `def fallback(): if a: …` in the handler → `unmutatable_decision_logic` with reason `non_top_level_function` |
| **Q5-TC** [ruled 2026-11-11: Q5] | logic : `test_type_checking_carve_out_exact_shape` | **Pass**: `if TYPE_CHECKING:` + imports. **Fail**: `if typing.TYPE_CHECKING:`; `if not TYPE_CHECKING:`; `if TYPE_CHECKING:` with `else:`; `if TYPE_CHECKING:` whose body holds `X = a if b else c` (the `If` is carved, and the `IfExp` fails). Coverage of the never-run body is still counted as uncovered (H2) |
| **Q5-DEC** [ruled 2026-11-11: Q5] | logic : `test_decorated_and_unmutatable_interaction_with_regions` | (i) a decorated top-level function whose **body** holds an `if` → `unmutatable_decision_logic`, reason `decorated_function`, and no Q5 reason. (ii) `@retry(times=3 if CI else 1)` on an otherwise logic-free top-level function → `module_level_decision_logic` at the decorator's line, and no NQ-2 reason. (iii) `def f(x=a == b): return x` (single line) → `module_level_decision_logic`, because the `Compare` is in `args.defaults`, not in the body. (iv) an undecorated top-level function, and a method of a top-level class that carries exactly one `@staticmethod`, each with an `if` in its body → no decision reason (mutated code). (v) a nested `@functools.wraps(orig) def wrapper(...)` inside an undecorated top-level function, whose body holds an `if` → `unmutatable_decision_logic`, reason `decorated_function` (any depth). (vi) a def inside a module-level `with` block whose body holds an `if` → `non_top_level_function`. (vii) a nested def inside a top-level function, with a non-simple default `def inner(x=a == b)` → `definition_time_expression`. (viii) a decorated method of a top-level class whose decorator argument holds an `IfExp` → `class_level_decision_logic` for the decorator, and `decorated_function` for any body logic. (ix) `unmutatable_gated_lines` and `decision_logic_findings` agree line by line, and no line carries both a Q5 and an NQ-2 reason. (x) In an undecorated top-level function: `return len(r.get("e") or [])` → `never_mutate_name`; `return isinstance(x, A if c else B)` → `never_mutate_name`; `return len(a) > 0 and b` → no reason (the `Compare` and `BoolOp` sit outside the call). (xi) In a top-level `class E(Enum)`: a method `label(self)` with an `if` → no reason; `__init__` with an `if` → `enum_body`; the same for `class E(enum.IntEnum)`. (xii) In an undecorated top-level function: `x: (A if c else B) = 1` → `definition_time_expression`; `f = lambda y=a == b: y` → `definition_time_expression`; a nested `def inner(x=f"{a if b else c}")` → no reason (simple to mutmut) (architect delta-review fix) |
| **Q5-RUN** [ruled 2026-11-11: Q5] | measure : `test_module_level_logic_fails_file_with_mutants_and_selection` | a changed fixture file with a well-tested top-level function (score and coverage pass) and a new gated module-level `X = A if c else B`. The file fails `module_level_decision_logic` **only**. `mutation_ran: true`, and `mutants_total`, `mutants_killed` and `mutant_score_pct` are recorded (the Q5 fail does not stop the mutation run). Verdict exit 1. This is the case that round 5's R-2 left coverage-only |
| **Q5-RAISE** [ruled 2026-11-11: Q8] | logic : `test_main_guard_raise_systemexit_near_misses_rejected` | each of these guard bodies is **not** carved (the `If` and its `Compare` get `carve_out: null`, and the file fails `module_level_decision_logic`): `raise SystemExit`; `raise SystemExit()`; `raise SystemExit(1)`; `raise SystemExit(code)`; `raise SystemExit(main(), 1)`; `raise SystemExit(code=main())`; `raise SystemExit(main()) from None`; `raise builtins.SystemExit(main())`; `raise KeyboardInterrupt(main())`; a bare `raise`; `raise SystemExit(main())` followed by a second statement; `raise SystemExit(main())` with an `else:` branch; `raise SystemExit(main())` inside a guard nested in a class body or in another module-level `if`. `raise SystemExit(main() or 1)` → not carved (the argument is a `BoolOp`), so the `If`, the `Compare` and the `BoolOp` all fail. `raise SystemExit(main(a if b else c))` → carved (`If` and `Compare` have `carve_out: main_guard`), and the `IfExp` fails on the body line |
| **Q5-NQ1** [ruled 2026-11-11: Q5; rewritten Q8] | measure : `test_nq1_applies_carve_outs` | Every file below is new, has zero gated mutants and an empty selection, and is measured with its import-time lines executed under the empty context only (built with the `CoverageData` API, as AF-3's import-only case). Each "passes" case carries enough plain module-level assignments for gated coverage to reach ≥ 80% with the never-run lines unexecuted; the fixture computes that ratio from `PythonParser.statements` rather than hard-coding it. **Passes, `selection_method: not_required_zero_mutants`, no fail reason, and the carved findings present in `decision_logic_findings` with their `carve_out` values:** (i) an `__init__.py` whose only decision logic is `try: import tomllib` / `except ImportError: tomllib = None`; (ii) an `__init__.py` whose only decision logic is `if TYPE_CHECKING: from .x import Y`; (iii) a module that imports `main` from another fixture module (so it defines no function and has zero mutants) and whose only decision logic is a main guard with body `sys.exit(main())`, and (iv) the same with `raise SystemExit(main())`. **Coverage still applies:** (v) file (i) with no extra assignments, so its unexecuted handler body puts it under 80% → `coverage_below_threshold` only, and **not** `zero_mutant_decision_logic`. **Uncarved logic still fails:** (vi) file (i) plus an uncarved module-level `if` → `zero_mutant_decision_logic` and `module_level_decision_logic`, in §5.14 order, and each message lists only the `if`'s line, never the carved `try`'s; (vii) `try: import x` / `except ModuleNotFoundError: x = None` → both reasons (a near-miss is not carved). (viii) A file with only `X = 1` → passes under NQ-1 |
| **Q8-PRED** [ruled 2026-11-11: Q8] | logic : `test_one_decision_logic_predicate_for_every_rule` | for a fixed set of sources holding carved and uncarved nodes in every region: `has_decision_logic(source, lines)` equals `any(f["carve_out"] is None for f in decision_logic_findings(source, lines))`; the lines named by the NQ-1, Q5 and NQ-2 fail messages, and every `unmutatable_gated_lines` entry's `has_decision_logic`, are computed from findings with `carve_out: null` only; a source holding only carved findings gives `has_decision_logic` false and no NQ-1, NQ-2 or Q5 reason; and no finding outside the `module` region ever has a non-`null` `carve_out` (which is why Q8 changes no NQ-2 outcome). **Static (architect Q8-review fix):** in the AST of `new_code_gate_logic.py`, the string literal `"carve_out"` appears only in `decision_logic_findings` (the writer) and `is_decision_logic`; and both Q5-SELF `SELF_CHECK` programs (`test_new_code_gate_logic.py`, `test_new_code_gate_plugin.py`) call `ncg.is_decision_logic` and contain no `"carve_out"` literal |
| **Q5-SELF** [ruled 2026-11-11: Q5] | workflow : `test_gate_modules_have_no_q5_or_nq2_findings` | the §5.19 self-check, in a subprocess (it calls the same shared predicate, so `new_code_gate.py` may use either entry-point shape, §5.19 [ruled 2026-11-11: Q8]): no Q5 or NQ-2 failing finding in `new_code_gate.py`, `new_code_gate_logic.py` or `new_code_gate_pytest_plugin.py` (all statements gated); in `shell_logic_check.py`, every such finding lies inside the final `if __name__ == "__main__":` statement |
| R-AF2 | logic : `test_continuation_line_edit_is_gated` | |
| R-F8 | measure : `test_new_nonempty_init_measured` | |
| R-PIN | workflow : `test_requirements_pins_equal_logic_constants` | all **five** pins, pytest included [round 2: T4] |
| R-CONF | logic : `test_bare_import_dirs_equal_conftest_insertions` | |
| R-S1a | workflow : `test_run_tests_sets_ctrace_contexts_and_split_report` | the exact flags in §4.1 |
| R-S1b [round 4: U6] | workflow : `test_run_tests_adds_no_counted_shell_construct` | **No git, no base lookup.** The test reads `scripts/framework/run_tests.sh` by a path relative to the test file and asserts `decision_lines(lines) == EXPECTED`, where `EXPECTED` is a **literal list of two line numbers** written into the test. At `8113f8ba0` the list is `[128, 135]` (computed this round from today's loop logic; it matches `_scan_file` = `(2, 128)` in §4.1). S1's edits above line 99 shift both by the same number of lines `k`, so the coder writes the literal `[128 + k, 135 + k]` after editing `run_tests.sh`, and records `k` in the commit message. A second assertion pins the content of each counted line, stripped: `"if total == 0:"` and `'if [[ "$KILL_RATE" -ge "$MUTANT_TARGET" ]]; then'`. So a new counted construct, a removed one or a moved one each fail the test, and the test runs the same in a mutation workspace with no `.git` (§5.19) |
| R-SLC | shell_logic_check : `test_decision_lines_matches_scan_file_count` | across every existing fixture |
| R-SLC2 [round 2: T3] | shell_logic_check : `test_scan_file_empty_returns_zero_none` + `test_decision_lines_sorted_duplicates_preserved` | a file with no counted construct → `(0, None)` with no exception; `decision_lines` output is sorted and its length equals `_scan_file`'s count on a fixture where close order differs from line order |
| AR-1a [round 2: T1] | measure : `test_ci_mode_gates_merge_commit_base_is_first_parent` | on a fixture with a real two-parent merge commit, the gated lines are exactly the PR side's additions relative to `^1`; a change made only on the base side is not gated |
| AR-1b [round 2: T1] | measure : `test_ci_mode_second_parent_must_equal_pr_head` | `^2` ≠ `--pr-head-sha` → exit 3 `merge commit does not contain the PR head`; a one-parent `--gated-sha` → the same exit 3 |
| AR-1c [round 2: T1] | measure : `test_blob_sha_from_gated_tree_pr_head_blob_alongside` | when the base also edited the file, `blob_sha` ≠ `pr_head_blob_sha` and `blob_sha` is the merge-tree blob; when it did not, they are equal |
| AR-1d [round 2: T1] | workflow : `test_new_jobs_checkout_github_sha_and_pass_gated_sha` | both new jobs set `ref: ${{ github.sha }}`; `measure` is passed `--gated-sha ${{ github.sha }}` and `--pr-head-sha ${{ github.event.pull_request.head.sha }}`, and no `--base-sha` |
| A7a [round 2: T4] | measure : `test_sidecar_tool_versions_and_python_must_equal_install` | each of the five tools and the Python major.minor, mutated one at a time in the sidecar → exit 3 naming that tool |
| A9a [round 2: T2; round 4: U1] | measure : `test_enumerate_and_collect_run_in_per_file_subprocesses_with_workspace_cwd` | with two gated files whose workspaces carry different `only_mutate`, each `_enumerate` **and each `_collect`** call receives its own workspace as cwd, `-P`, `PYTHONPATH=<checkout>` and an env with no `NCG_*`. **No mutmut or libcst in `measure`:** for the duration of a full `measure` with a fake runner, every `sys.modules` key equal to or under `mutmut` or `libcst` is removed (`monkeypatch.delitem`, restored afterwards) and a `sys.meta_path` finder that raises `ImportError` for those names is installed first; `measure` completes, and the finder recorded no request. (A plain `"mutmut" not in sys.modules` check is not used: other tests in the same process import mutmut legitimately.) |
| A9c [round 4: U1] | measure : `test_collect_child_reads_meta_and_reports_statuses` | the child-side `_collect` function, called in-process with cwd = a `tmp_path` workspace holding a generated config and a hand-written `mutants/<rel>.meta`: it calls `reset_config()` first, returns `exit_code_by_key` as written, maps 1 → `killed`, 36 → `timeout`, 33 → `no tests`, an unlisted code → `suspicious`, `None` → `null`; it exits 3 on a missing `.meta` and when `only_mutate` ≠ `[--file]` |
| A9d [round 4: R3-A] | measure : `test_gate_file_outside_checkout_or_inside_workspace_exits_3` | fake `_enumerate` and `_collect` JSON whose `gate_file` is inside the workspace, or outside the checkout → exit 3 `gate subprocess imported from the workspace: <file>`; a `gate_file` under the checkout and outside the workspace passes. The child-side functions report `str(Path(new_code_gate.__file__).resolve())` (asserted in-process) |
| A9e [round 4: U1] | measure : `test_collect_drift_and_completeness_exit_3` | `_collect` key set ≠ enumerated set → exit 3 `mutant enumeration drift`; a gated key with `null` exit code after an exit-0 run → the same; a gated key with a non-`null` exit code under the no-test-case stop → the same; non-zero exit, bad JSON or schema mismatch → exit 3 `mutation results could not be read: <file>` |
| A9b [round 2: T2] | logic : `test_enumerate_refuses_when_only_mutate_differs` | `_enumerate` exits 3 when the cwd config's `only_mutate` ≠ `[--file]` |
| A4a [round 2: T6; round 4: U2] | measure : `test_isolation_failure_attributed_is_per_file_fail` (parametrized over the two stages) | fake runner output with a short-summary section holding `FAILED <selected nodeid> - AssertionError`, followed by **either** `failed to collect stats. runner returned 1` (stage `stats`) **or** `Failed to run clean test` (stage `clean`) → `selected_test_fails_in_isolation`, verdict exit 1, the node ID and the stage in the message |
| A4b [round 2: T6; round 4: U2] | measure : `test_isolation_failure_unattributed_exit_3` (parametrized over the two stages) | no parseable ID, **and** separately a parsed ID outside the selection → exit 3, code `clean_run_unattributed`, message exactly "clean run failed and no selected test could be identified", the right `stage`, and no "see log" anywhere in the record |
| A4c [round 2: T6; round 4: U7] | measure : `test_integrity_checks_then_attribution_precedence` | (i) plugin-location failure, `observer_error` and an executed-but-unselected node ID each give exit 3 **even when** a tripwire event, a path-load event and an attributable isolation failure are also present (the integrity checks of §5.9 step 5 come first, in their stated order); (ii) with the integrity checks clean, the step-6 order holds: tripwire, then path-load, then trampoline, then no-test-case stop, then isolation |
| **A4d** [round 4: U3; R3-D] | logic : `test_generated_pytest_args_pin_report_chars` | the generated `pytest_add_cli_args` contains `-rfE` exactly once; contains no `--no-summary`, no other element starting with `-r` (so no `-rN`, `-ra`, `-rfEN`), no `--report-chars…`, and no `-q` (mutmut adds its own); and `-rfE` is a separate list element (not merged into another flag) |
| **A4e** [round 4: U3] | logic : `test_short_summary_parse_reads_only_the_section` | input with mutmut's `FAILED: Unable to force test failures`, a captured-stdout block containing `FAILED tests/x.py::fake`, and a FAILURES section header, but no short-summary header → no IDs. The same input plus a real section (`=== short test summary info ===`, `FAILED tests/a.py::t - msg`, `ERROR tests/b.py`, then `=== warnings summary ===`) → exactly `tests/a.py::t` and `tests/b.py`. ANSI-coloured input parses the same. With two sections, only the last one is read |
| **A4f** [round 4: U2; R3-C] | measure : `test_no_test_case_stop_records_all_gated_no_tests` | fake runner: mutmut exit 1 with the exact 3.8.1 "Stopping early, because we could not find any test case for any mutant." output, and a fake `_collect` whose gated keys are all `null` → every gated mutant `no tests`, `mutants_killed: 0`, `mutant_score_pct: 0.0`, `mutation_ran: true`, fail reason `mutant_score_below_threshold` only (not exit 3, not `no_test_exercises`) |
| **E2E-ISO** [round 4: U2; R3-C] | e2e : `test_real_mutmut_isolation_failure_attributed` | real coverage and real mutmut, the CLI as a subprocess. The fixture repo has one gated function and one test that calls it and also asserts `(Path(__file__).resolve().parents[1] / ".git").is_dir()`. It passes in the fixture's normal run (the fixture has a `.git`) and fails in the workspace (which has none), so the failure first surfaces in mutmut's **stats** run. Asserts: `selected_test_fails_in_isolation` naming that node ID with stage `stats`, verdict exit 1, and no `internal_errors`. This proves the real stats-run output carries a short-summary section under the generated args |
| A6a [round 2: T7] | measure : `test_plugin_dir_is_workspace_sibling_and_location_asserted` | `ncg-plugin/` and `workspace/` share a parent and neither contains the other; a `plugin_loaded` path inside the workspace, or no `plugin_loaded` event, → exit 3 `tripwire plugin not loaded from outside the workspace` |
| A2a [round 2: T10] | logic : `test_also_copy_has_only_top_level_entries` | every generated `also_copy` entry has no `/` other than a trailing one on a directory; no entry is `.claude/`, `pyproject.toml` or `setup.cfg`, including on a fixture workspace that tracks a top-level `setup.cfg` and a top-level `.claude/` before extraction (architect round-3 consistency fix) |
| **S-E2E** [round 2: T8] | workflow : `test_e2e_module_imports_no_gate_module_in_process` | AST of `tests/framework/test_new_code_gate_e2e.py`, at **any** depth (module, function, class): no `Import` / `ImportFrom` whose module is `scripts.framework.new_code_gate`, `scripts.framework.new_code_gate_logic` or `scripts.framework.new_code_gate_pytest_plugin`, and no `from scripts.framework import <any new_code_gate* name>`; no `importlib.import_module(...)` or `__import__(...)` call with a string literal containing `new_code_gate`. ADR §2b condition 4 |
| **S-STDLIB** [round 2: T8] | workflow : `test_gate_modules_import_only_stdlib_at_module_level` | for `new_code_gate.py` and `new_code_gate_logic.py`: every `Import` / `ImportFrom` that is **not** inside a `FunctionDef`, `AsyncFunctionDef` or `ClassDef` body (so module level, including inside module-level `if`/`try`) has a top-level package in `sys.stdlib_module_names` or `{"__future__"}`, except that `new_code_gate.py` may import `scripts.framework.new_code_gate_logic`. A second case runs `python -E -S -c "import scripts.framework.new_code_gate"` in a subprocess with cwd = the repo root (`-S`: no site-packages; `-E`: `PYTHONPATH` ignored, so only the stdlib and the repo are importable) and asserts exit 0. ADR §2b condition 5 |
| **S-PASSIVE** [round 2: T8] | plugin : `test_meta_path_observer_is_passive` | **static:** in the plugin's observer class, every `return` in `find_spec` is `return None` or a bare `return`, and the method has a final `return None`; it contains no `sys.modules[...] =` assignment. **Behavioural:** with the observer installed first on `sys.meta_path`, `find_spec` returns `None` for a stdlib name, a missing name, the canonical gated name and a bare alias; `importlib.util.find_spec(<name>)` gives the same `origin` with and without it; and a `find_spec` made to raise internally (by monkeypatching its resolver) still returns `None` and logs `observer_error` |
| **P-ENV** [round 4: U5; R3-H] | plugin : `test_plugin_reads_ncg_env_once_and_removes_it` + `test_plugin_wrapping_is_idempotent_per_copy` + `test_autouse_fixture_covers_every_ncg_variable` | (a) with all four `NCG_ENV` variables set to `tmp_path` values, `importlib.reload` of the **canonically** imported module (never a file-path load, which §5.7 would flag on the plugin's own PR): its state holds the four values and none of the four is left in `os.environ`; `os.environ` changes made after the reload do not change its state. The autouse fixture's teardown resets the state to inert. (b) Static: the plugin source reads `os.environ` / `os.getenv` only inside `_load_state`. The one exception is the single module-level statement `_STATE = _load_state(os.environ)`, which passes `os.environ` as the argument [ruled 2026-11-11: Q5; §5.18]. Every `NCG_*` string literal in the source is an element of `NCG_ENV`. (c) Calling the plugin's `pytest_configure` three times on one active copy wraps `shutil.copytree` and `subprocess.Popen` once each and leaves one observer of that copy on `sys.meta_path`; when `shutil.copytree` is pre-wrapped by a stand-in "other copy" wrapper (a function whose `__ncg_wrapped__` is a different sentinel object), the copy still wraps over it; `uninstall()` restores exactly what was there before (the stand-in, in that case). (d) Static: the module's autouse fixture iterates the plugin's `NCG_ENV` (not a second hand-written list), so a new variable is covered automatically |
| **NOGLOBAL** [architect round 5] | measure : `test_child_side_calls_restore_host_mutmut_config` | with a sentinel object placed in `mutmut.configuration._config`, each in-process call of the child-side `_enumerate` / `_collect` code under the shared fixture leaves `_config is sentinel` afterwards; a static check asserts every test in the gate's test modules that calls the child-side functions requests that fixture |
| **TRIP-MUT** [architect round 5] | plugin : `test_tripwire_flags_copy_of_mutants_root` | with an active copy whose `NCG_WORKSPACE` is `tmp_path/ws`, `shutil.copytree(tmp_path/ws/mutants, dst)` and `copytree(tmp_path/ws, dst)` each raise `NCGRepoCopyError`; `copytree(tmp_path/ws/mutants/tests/fixtures/x, dst)` does not; a loader call on `tmp_path/ws/mutants/<rel>` under a non-canonical name is recorded |
| **G-NOGIT** [round 4: U6] | workflow : `test_in_process_gate_tests_need_no_real_git_or_claude` | AST of `tests/framework/test_new_code_gate_{logic,measure,plugin,workflow}.py` and `tests/oversight/test_shell_logic_check.py`: no path expression joins a repo-root expression (the §5.18 guard's list) with a `".git"` or `".claude"` segment; no `subprocess` / `git` argv runs `git` with `cwd=` or `-C` set to a repo-root expression; no call to `git rev-parse --show-toplevel`. Fixture repos under `tmp_path` are allowed. It is a heuristic and is allowed to miss; the §5.19 self-budget run (which executes these tests inside real workspaces) is the behavioural proof |
| **EQ-MAP** [architect review-3 ruling, ADR §2g RV3-1] | measure : `test_function_scoped_mapping_equals_whole_module` (`slow`) | run **in a subprocess** (`sys.executable -I -c …`, cwd = a `tmp_path` workspace with its own `pyproject.toml`), never in-process. The scoped mapping equals the whole-module mapping for every mutant of `shell_logic_check.py` and `new_code_gate_pytest_plugin.py`, and for a deterministic sample of ≥ 200 mutants of each of `new_code_gate.py` and `new_code_gate_logic.py` that covers every mutated function and method at least once. Fixtures: a method of a top-level class; two same-named methods in different classes; a leading comment block; a single `@staticmethod`; the last function with no trailing newline; a multi-line statement. Plus: a forced-empty scoped result falls back to the whole-module mapping, and empty-on-both gives exit 3 `mutant could not be mapped` |
| **IMP-TRAMP** [architect review-3 ruling, ADR §2g RV3-3(b)] | plugin : `test_importer_skips_mutmut_trampoline_frames` | a loader call made from a code object compiled with filename `<tmp_path>/mutmut/mutation/trampoline.py`, which is itself called from the test, records `importer` = this test file, and the event is still logged |
| **G-SRCREAD** [architect review-3 ruling, ADR §2g RV3-3(a)] | workflow : `test_source_reading_gate_tests_run_no_gate_code` | AST of the gate's test modules: a test function that reads the text of a `scripts/framework/new_code_gate*.py` path or of `shell_logic_check.py` (`read_text`, `open`, `inspect.getsource`, `ast.parse` of a read) contains no `ast.Attribute` on `ncg`, `gate` or `plugin` and no call to a name imported from those modules. Strings that name them (for example `"ncg.is_decision_logic" in SELF_CHECK`) are allowed |
| **G-MUTSTATE** [architect review-3 ruling, ADR §2g RV3-3(c)] | workflow : `test_no_gate_test_puts_a_non_config_in_mutmut_config` | AST of the gate's test modules: every assignment whose target is an attribute `_config` has a value that is a name bound by `copy.copy(<…>.config())` or the saved original. `object()` or any other literal or call is refused. NOGLOBAL's sentinel becomes such a copy |
| **ISO-DIAG** / **PHASE-SEC** [architect review-3 ruling, ADR §2g RV3-4] | measure : `test_isolation_failure_keeps_summary_and_tail` + `test_phase_seconds_recorded_and_unhashed` | (a) a fake runner's output with a FAILURES block and a short summary gives `isolation_failure` with `stage`, `node_ids`, `summary_lines` (bounded) and `output_tail` (bounded, ANSI-stripped). `records_sha256` is equal with and without the field, and the summary renders only `summary_lines[0]`, escaped. (b) a fake clock gives the four phase fields, their sum is ≤ `seconds`, and the hash ignores them |
| **SLC-1** [architect review-3 ruling, ADR §2g RV3-5] | `tests/oversight/test_shell_logic_check.py` : `test_scan_file_replaces_invalid_utf8` | `_scan_file` on a file holding invalid UTF-8 bytes (for example `b"\xff\xfe\n"`) before a counted construct returns exactly the counted `(count, first line)`. This kills the `errors=None`, `errors`-removed, `"XXreplaceXX"` and `"REPLACE"` mutants. The three `encoding` mutants are equivalent on a UTF-8 locale and stay (H2) |
| **WS-INTEG-1 to 3** [architect review-3 ruling, ADR §2g RV3-7] | measure + workflow | (1) a fake run that alters, adds or removes a file under `mutants/` (other than the gated copy and mutmut's outputs) gives exit 3 and names the path; (2) a clean fake run passes the check, with mutmut's outputs present; (3) static: each gate test module has the autouse `monkeypatch.chdir(tmp_path)` fixture |

## 10. File list

| # | File | Slice | Kind | Author |
|---|---|---|---|---|
| 1 | `scripts/framework/run_tests.sh` | S1 | edit | coder (protected) |
| 2 | `pyproject.toml` | S1/S2 | edit (omit, marker, `--strict-markers`) | coder |
| 3 | `.github/workflows/tests.yml` | S1/S2 | edit (upload, two jobs, header) | coder (protected) |
| 4 | `docs/CI-EXECUTION-INVENTORY.md:85` | S1/S2 | edit (add the two jobs; correct "mutmut … not run per-PR") | coder |
| 5 | `scripts/framework/new_code_gate.py` | S2 | new | coder (protected dir) |
| 6 | `scripts/framework/new_code_gate_logic.py` | S2 | new | coder |
| 7 | `scripts/framework/new_code_gate_pytest_plugin.py` | S2 | new | coder |
| 8 | `scripts/oversight/validators/shell_logic_check.py` | S2 | edit (`decision_lines` seam) | coder |
| 9 | `scripts/oversight/requirements.txt` | S2 | edit (pins) | coder |
| 10 | `scripts/framework/hos_required_contexts.txt` | S2 | edit (`new-code-gate` + provenance comment) | coder (protected) |
| 11 | `tests/framework/test_new_code_gate_{logic,measure,plugin,e2e,workflow,agent_wording}.py` | S2/S4 | new (6) | unit-test / coder |
| 12 | `tests/framework/test_repo_copy_marker_guard.py` | S2 | new | unit-test |
| 13 | `tests/framework/test_branch_protection_contexts.py` | S2 | edit | unit-test |
| 14 | `tests/oversight/test_shell_logic_check.py` | S2 | edit (canonical import, new cases) | unit-test |
| 15 | repo-copying test files (up to 15 candidates, F-16) | S2 | edit (marker only) | unit-test |
| 16 | `.claude/agents/unit-test.md` | S4 | edit (§6.1) | **top-level session** |
| 17 | `.claude/agents/oversight-evaluator.md` | S4 | edit (§6.2) | **top-level session** |
| 18 | `contract/OVERSIGHT-CONTRACT.md` | S4 | edit (§6.3) | top-level or coder (protected) |
| 19 | `templates/base-agent-register-examples.md` | S4 | edit | coder |
| 20 | `docs/v0.3.0/BASE-AGENTS-SPEC.md` | S4 | edit | coder |
| 21 | `packs/django/unit-test.md` | S4 | edit (line 39) | coder |
| 22 | `SCRIPTS-INDEX.md` | S2 | regenerated (`regen_all.sh`) | coder |
| 23 | `DECISIONS.md` | S2 | append (gate required, rulings) | top-level session |
| 24 | this TD, ADR-2304 and SPEC-2304 (ruling edits) | docs | new/edit | technical-design |
| 25 | `CLAUDE.md` (§6.7 row) [ruled 2026-11-11: Q7] | S4 | edit (one table row) | **top-level session** (protected) |

About 25 entries and about 35 to 45 paths, with the repo-copy markers. That is over the ≤ 15-files-per-slice guideline, because three slices ship in one PR by the human's scope ruling. Commits stay per slice (§11). `diff_size` floors at HIGH, which the tier already is.

## 11. Build order (commits on `human-2304-mutation-gate`)

| # | Commit | Content | Gate |
|---|---|---|---|
| 0 | `8113f8ba0` **(done)** | committed `[tool.mutmut]` `also_copy` / `source_paths` fix | stands (§13) |
| 1 | docs | this TD, plus the ADR and spec ruling edits (§2.2, §2.4) | architect approval before commit 2 |
| 2 | S2a: logic | `shell_logic_check.py` seam + `test_shell_logic_check.py` conversion; `new_code_gate_logic.py` + `test_new_code_gate_logic.py` | tests green, in-process. The §5.5 / §5.10 functions wait for the architect's review of the 2026-11-11 delta [ruled 2026-11-11: Q5]. **Committed as `b1a26e887` before Q8 was ruled.** The Q8 changes to it (§13) go in a follow-up commit on the branch after the architect reviews the Q8 delta [ruled 2026-11-11: Q8] |
| 3 | S2b: plugin | `new_code_gate_pytest_plugin.py` + its tests; the `repo_copy` marker, `--strict-markers`, marking, the guard test | full suite collects under `--strict-markers` |
| 4 | S2c: CLI | `new_code_gate.py` (`meta`, `measure`, `verdict`, `run`) + the measure and e2e tests; requirements pins | `run` works locally on the branch (an in-sandbox spot check on `claim`-class files) |
| 5 | S1 | `run_tests.sh`, `pyproject.toml` omit, `tests.yml` `tests` upload | local subset equivalence |
| 6 | S2d: workflow | the two jobs, `hos_required_contexts.txt`, workflow and branch-protection tests, inventory doc, `SCRIPTS-INDEX.md` | — |
| 7 | S4 (coder part) | contract, templates, BASE-AGENTS-SPEC, django pack, wording tests (the tests for §6.1 and §6.2 fail until commit 8) | — |
| 8 | S4 (top-level part) | `unit-test.md` and `oversight-evaluator.md` per §6.1 and §6.2, and the `CLAUDE.md` row per §6.7 [ruled 2026-11-11: Q7] | wording tests green |
| 9 | DECISIONS.md entry | | |
| 10 | **Pre-PR evidence (no commit) [round 2: T9, T10]** | Before `submit_pr.sh`: (a) the self-budget run and projection (§5.19, ADR §2b condition 6); (b) the S1 equivalence repeat with **both total and file count** (§4.4, ADR-A3); (c) the `--unified=0` hunk list for `shell_logic_check.py` (§5.11, condition 2). All three go in the PR body | projection > 20 CI-minutes, or any equivalence difference → **stop and return to the architect**; the PR is not opened |

S1 lands after S2c so that the `meta` subcommand that `run_tests.sh` calls already exists. Every commit leaves the suite green. The review chain (risk-assessor; code, security, reliability and ops reviewers; unit-test) runs on the whole branch. security-reviewer and reliability-reviewer are mandatory (ADR Consumers).

## 12. Risks and residuals

| ID | Risk | Mitigation |
|---|---|---|
| R-1 | Subprocess-only test exercise counts for nothing | stated (§7.2). Test in-process |
| R-2 [ruled 2026-11-11: Q5] | **Narrowed by Q5.** Module-level and class-level decision logic no longer passes on coverage alone: it fails (§5.10). What remains coverage-only is (a) the three carved-out statements, only the nodes §5.5.3 names; (b) module-level and class-level statements with **no** decision node (assignments, calls, imports, `with`, `raise`, `assert`), whose behaviour mutmut never mutates; (c) the bodies of a `TYPE_CHECKING` block and of a main guard, which never run in-process and so count as uncovered. **Since Q8**, (a) also covers NQ-1 and NQ-2, and carve-out (a) also accepts `raise SystemExit(<call>)`. So a zero-mutant, empty-selection file whose only logic is carved now passes on coverage alone, where before Q8 it failed `zero_mutant_decision_logic` [ruled 2026-11-11: Q8] | (a) is the human's explicit carve-out list, extended by Q8. The shapes stay exact (§5.5.3), and every near-miss fails (Q5-MAIN, Q5-RAISE, Q5-IMP, Q5-TC). (b) follows from the ruled AST definition, which does not include `assert`, `with` or calls. (c) already counts against coverage (H2). Pinned by Q5-MOD, Q5-MAIN, Q5-IMP and Q5-TC |
| R-3 | Deletion-only changes are not gated | by design (spec §3) |
| R-4 | Tests written to tamper with measurement | not a security boundary (ADR AF-8). Reviewed in `tests/**` |
| R-5 | A PR near the budget flips between fail and pass on timing | a timing-made pass is impossible (§5.13) |
| R-13 (was TD R-6) | Shell without `.sh` (`bin/hos-cron`, `bin/hos-human`) is not gated | inherited from spec §3 and `shell_logic_check`'s `.sh` scope. Out of scope for this PR and tracked in #2305 (§14 Q6) [ruled 2026-11-11: Q6]. Renumbered in round 2 so it cannot be confused with ADR R-6 |
| R-7 | Shell `for` loops and edited guard clauses are not counted | inherited definition (H4). Pinned by R-H4c |
| R-8 | A first-touch failure wave on at least 26 and an estimated 40 to 57 of 95 modules, plus unquantified other classes | stated (§7.1, Appendix A). #2305 sequencing |
| R-9 | Tests that depend on the real repo's `.git` fail in `mutants/` | a named per-file failure (§7.2) |
| R-10 (= ADR R-6) | The gate's code and workflow run from the PR's own commit, so a PR can weaken its own verdict | **decided: no trusted base** (ADR §2b Q2). CODEOWNER human review of `scripts/framework/**` and `.github/workflows/**` |
| R-11 | Retention silently capped below 90 days | the first-run `expires_at` check (§5.15.3) |
| R-12 | The pinned libcst/mutmut/pytest stop working on a future Python | the version guard fails closed. Bump with this TD's tests |
| R-8a [ruled 2026-11-11: Q5; amended Q8] | Q5 first-touch failures on the **25** of 95 modules (33 before Q8) holding uncarved module-level decision logic (mostly `if __name__` guards whose body holds logic, and non-import module-level `try` blocks), when a PR edits those lines. With §7.1's population, 65 of 95 in all (heuristic upper end) | stated (§7.1a). Each one has a mechanical fix: rewrite the guard to a one-line `sys.exit(main())` or `raise SystemExit(main())`, or move the logic into a function |
| R-16 [ruled 2026-11-11: Q8] | A carved shape can hide behaviour that runs at import: an `ImportError` handler's plain assignments, a `TYPE_CHECKING` body, and a guard's single call are never mutated, and since Q8 that is also true in a zero-mutant, empty-selection file, which nothing else tests | bounded by the exact shapes (§5.5.3): only the carved nodes themselves are excused, any decision node inside a carved statement is still judged, and the never-run lines still count against coverage (H2). Accepted by the human's Q8 ruling |
| R-15 [ruled 2026-11-11: Q5] | §5.5.2's regions and unmutatable reasons copy mutmut 3.8.1's mutation scope by hand. A different mutmut would change what is actually mutated | the five-tool pin and the version guard (§5.2 step 1) fail closed on any other mutmut. Bumping the pin requires re-checking §5.5.2 against the new `file_mutation.py` and re-running Q5-DEC |
| R-14 [round 4: U4] | A name-fallback whole-module selection whose every test is `repo_copy` keeps its container ID (§5.6 step 3), so mutmut's stats run collects nothing (`failed to collect stats. runner returned 5`, no short-summary IDs) | fails closed as exit 3 `clean_run_unattributed` (§5.9 step 6 rule 6), never a pass. The message is less specific than `no_test_exercises`; accepted because it needs a name-fallback file whose matching test module is entirely repo-copying |
| R-17 (= ADR R-7) [architect review-1 ruling] | A test that is flaky on both attempts makes a surviving mutant read as killed | `--reruns 1` (§5.8) reduces it from p to about p². It is the same class as H3. A gate-budget or job timeout still never passes (§5.13) |
| R-18 (= ADR R-8) [architect review-1 ruling] | A required check is matched by name, so another job named `new-code-gate`, or a status posted by an App with `statuses:write`, can satisfy it | The first needs a protected `.github/workflows/**` edit. The second is fixed by a follow-up issue that pins every required context to the GitHub Actions App in `setup_branch_protection.sh` (a human applies it) |
| R-19 [architect review-1 ruling] | Gated symlinks can never pass. A PR that needs one must replace it with a regular file or a re-export module | a named per-file fail (§5.3). 0 tracked symlinks today |

| R-20 (= ADR R-9) [architect review-2 ruling] | PR code inside `new-code-measure` (tests, `ensure_venv.sh`, `requirements.txt`) forges the records via GitHub file-command variables, a `setsid` daemon, or the runtime token | AF-8 class, accepted. The five file-command names are stripped from child envs (partial). Only `new-code-gate` is free of PR-executed code (INV-G). A trusted verifier job is a follow-up |
| R-21 (= ADR R-10) [architect review-2 ruling; conditional] | Unprotected `shell_logic_check.py` / `validators/__init__.py` in the `measure` decision closure | exists only if the human declines ADR §2f RV2-2(b). The `sys.path` restore (RV2-2(a)) is built regardless |
| R-22 (= ADR R-11) [architect review-2 ruling] | `run_git` has no timeout; thin 25/30-minute margin; second signal during `terminate()`; kill-grace vs runner cancel | accepted. The job timeout backstops it, and none can produce a pass |
| R-23 [architect review-3 ruling, ADR §2g RV3-6] | A test that kills the pytest session's own process (a signal to its own group, or `os._exit` in-process) leaves a 0-byte `.coverage`, and every PR's gate then exits 3 | fails closed (`coverage data missing contexts`), so it is an availability risk, never a false pass. Seen in the session sandbox. If the human's out-of-sandbox full run reproduces it, bisect by test directory |

TD residual IDs are local to this TD, except R-10 (ADR R-6), R-17 (ADR R-7), R-18 (ADR R-8), R-20 (ADR R-9), R-21 (ADR R-10) and R-22 (ADR R-11).

## 13. Startup-gap and affected sign-offs

- **Should this have been settled in the initial design?** This **is** the initial technical design for #2304. No code exists against an earlier contract. ADR-A1 to A8, A9 and AR-1 (ADR §2b) correct the ADR, and T1 to T10 correct this TD, before any build, so none of them is a startup-artifact gap against built work [round 2: T10].
- **Review-1: affected sign-offs and built code [architect review-1 ruling, ADR §2e].**
  - *Should this have been settled in the initial design?*
    - **RV-1 (reruns): yes.** The initial ADR AD-5 claimed a flaky test reads as `suspicious`. The installed mutmut maps exit 1 to `killed`.
    - **RV-7 (run binding and fresh-directory downloads): yes, in part.**
    - **RV-2 (symlinks): yes, in part.**
    - These three are a startup-artifact gap. The top-level session opens or annotates a `startup-artifact-gap` issue. RV-3 to RV-6 are refinements.
  - **Sign-offs:** the security and reliability entries in `.claudetmp/signoffs/step2304-register.md` are CONDITIONAL. Both must re-review after the follow-up, with RV-1, RV-2, RV-4 and RV-7 in scope as well as their own findings. No APPROVED sign-off exists, so none is orphaned. The architect's earlier TD approvals stand for every section not listed in the Status line.
  - **Built code at `7ba465997` that no longer matches the contract.** This list is in addition to the coder's in-flight fixes F1 to F5, R100, path components, export attributes, log injection, node-ID validation, M1, M3, M4 and M6.
    1. `new_code_gate_logic`: add `"pytest-rerunfailures": "16.7"` to `PINNED`. Add `--reruns`, `1` to the generated `pytest_add_cli_args`, in the §5.8 order. Add `symlink_not_gateable` to the non-ruling-eligible fail codes, in §5.14 table order (first). Add a `records not bound to this run` binding check function that `verdict` and `run` share.
    2. `scripts/oversight/requirements.txt`: `pytest-rerunfailures==16.7`, with the #2304 RV-1 comment. R-PIN covers six tools.
    3. `new_code_gate.py` `meta`: write `run_id` from `GITHUB_RUN_ID`, or `null`. `measure`: in CI, require sidecar `run_id` = `--run-id`, and require regular-file inputs (§5.2).
    4. `new_code_gate.py` scope: classify mode `120000` paths in scope as `symlink_not_gateable` before any blob read (§5.3).
    5. `new_code_gate.py` `verdict` CLI: four required binding inputs, the regular-file check, and the binding check before `decide` (§5.1).
    6. `SubprocessRunner.run`: kill the child group on `BaseException` and re-raise. `measure` / `run` entry points: a SIGTERM → `SystemExit(143)` handler (§5.13).
    7. Records: a separate `_enumerate` seconds field per file (§5.13, §8.5 P-E).
    8. Tests:
       - A4d: assert `--reruns 1` is present once and none of the forbidden rerun flags is.
       - R-PIN: six tools.
       - SYM-1: a mode-`120000` `.py` in scope gives `symlink_not_gateable`, and no parse.
       - SYM-2: a `T` change to a symlink gives the same.
       - BIND-1 to BIND-4 (verdict): wrong `gated_sha`, `pr` or `run_id`, or a greater `run_attempt`, gives exit 3. An equal or lesser attempt passes the binding check. A symlinked records path gives exit 3.
       - BIND-5 (measure): a sidecar `run_id` mismatch gives exit 3.
       - INT-1 and INT-2 (§5.13).
       - RR-1 (fixture e2e, real mutmut): a mutant whose test fails deterministically is `killed` under `--reruns 1`. A surviving mutant whose test fails only on its first attempt is `survived`.
    9. `tests.yml`: the §5.17 "Workflow edits required by the review-1 rulings" (its "`--out` / `--summary` stay in the checkout" bullet is superseded by review-2). The top-level session makes these, because `.github/workflows/**` is protected and must match the coder's flag names. The coder writes the static workflow tests listed in §5.17, and they must pass against the top-level session's edit.
- **Review-2: the coder's list [architect review-2 ruling, ADR §2f].** This applies to the built code at `75dd05620`. Startup-gap analysis and affected sign-offs are in ADR §2f. The coder must not start until the self-budget evidence run on `75dd05620` has finished. That run's evidence stands. **[architect review-3 ruling]** Superseded: that run failed condition 6, and it is diagnostic only (ADR §2g RV3-0). Condition 6 is redone under "Review-3" item 7.
  1. `new_code_gate_logic.py`:
     - Add the constant `ENTRY_SNIPPET`, with the exact text from ADR §2f RV2-1.
     - Add `mode_not_gateable` to the non-ruling-eligible codes, right after `symlink_not_gateable`, with its message constant.
     - Replace `is_symlink_mode` with a single mode-to-fail-code function: `100644` / `100755` → `None`, `120000` → `symlink_not_gateable`, anything else → `mode_not_gateable`.
     - `_cell`: apply the §5.16 escaping in the stated order.
  2. `new_code_gate.py`:
     - `STRIPPED_ENV_NAMES` += `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_OUTPUT`, `GITHUB_STATE`, `GITHUB_STEP_SUMMARY`.
     - `child_argv` → `[python_exe, "-I", "-c", ENTRY_SNIPPET, str(checkout_root.resolve()), phase, "--file", rel, *extra]`.
     - `child_env` stops setting `PYTHONPATH`. The `gate_file` check is unchanged.
     - Scope classification uses the new mode function. A path the diff reports present but `ls-tree` omits → exit 3 `tree listing and diff disagree: <path>`.
     - The lazy `shell_logic_check` import (`:844`) snapshots `sys.path` and restores it in a `finally`.
     - `write_json`, the summary writer and the `meta` sidecar writer: `mkdir(parents=True, exist_ok=True)` on the parent, then temp file + `os.replace`.
     - `argparse` gets `prog="new_code_gate"`.
     - `main(argv)` stays callable with an explicit list, and the module's `sys.exit(main())` guard is unchanged.
  3. `scripts/framework/run_tests.sh:106`: the `meta` call uses the `-I -c` wrapper (§5.17 review-2).
  4. `tests.yml` (the top-level session, which is protected): the §5.17 review-2 edits.
  5. Tests:
     - WF-ENTRY: static, as in §5.17.
     - SHADOW-1: the literal verdict command from `tests.yml`, run in a fixture with a planted root `json.py`, `argparse.py`, `re.py`, `coverage.py`, `mutmut.py`, `libcst.py`, `sitecustomize.py` and `scripts/__init__.py`. Each planted file writes a marker and calls `os._exit(0)`. Expect exit 1 on bound `fail` records and no marker.
     - SHADOW-CTRL: the `-m` form on the same fixture writes a marker, which proves the fixture bites.
     - SHADOW-2: the `run_tests.sh` `meta` form, and one `child_argv` phase, write no marker.
     - VER-IMPORTS: the verdict child's `sys.modules` holds only stdlib names, `scripts`, `scripts.framework` and the two gate modules.
     - A9a, updated: `-I -c ENTRY_SNIPPET <root>`, and no `PYTHONPATH` key.
     - ENV-STRIP: all five names are dropped.
     - SLC-PATH: `sys.path` is restored after the shell phase.
     - MODE-1: a `160000` gitlink at a `.py` path, built with `git update-index --add --cacheinfo 160000,<sha>,x.py`, gives `mode_not_gateable` with no blob read, and verdict exits 1.
     - MODE-2: a path the diff reports but `ls-tree` omits (a fake runner) gives exit 3.
     - CELL-1: a hostile path and message, `` a|b`c[d](e)<img src=x>&\.py ``, render to the exact expected escaped string.
     - ATOMIC-1: a pre-existing symlink at `--out` is replaced by a regular file, and its target is untouched.
  6. **Only if the human clears ADR §2f RV2-2(b):** add `scripts/oversight/validators/__init__.py` and `scripts/oversight/validators/shell_logic_check.py` to `scripts/framework/protected_surfaces.txt`, run `scripts/framework/regen_all.sh`, and sync `docs/AGENT-IDENTITY.md` §9. If the slice's 15-file cap would be exceeded, this goes in a follow-up PR.
- **Review-3: the coder's list [architect review-3 ruling, ADR §2g].** This list builds on the review-2 commit `756aebe5b`. Startup-gap analysis and affected sign-offs are in ADR §2g.
  1. `new_code_gate.py` `enumerate_child` / `mutant_lines`: the function-scoped mapping with the whole-module fallback (§5.9 step 2). Keep the whole-module function, because the fallback and EQ-MAP use it.
  2. `new_code_gate.py` records:
     - `isolation_failure` on rule 5 (§5.9 step 6);
     - `workspace_seconds`, `mutmut_seconds` and `collect_seconds` beside `enumerate_seconds`.
     `new_code_gate_logic.py`: `TIMING_FIELDS` → `UNHASHED_FIELDS` with the six names, the bounded tail and summary helpers, and the summary rendering of `summary_lines[0]` through `_cell`.
  3. `new_code_gate_pytest_plugin.py` `importer_file()`: skip mutmut trampoline frames (§5.18).
  4. Tests, fixed:
     - (a) Diagnose why `test_only_is_decision_logic_and_findings_builder_read_carve_out` was selected (ADR §2g RV3-3(a)), and report the cause. If a gate call makes it selected, remove that call.
     - (c) In `test_collect_child_reads_meta_and_reports_statuses`, `test_child_side_calls_restore_host_mutmut_config` and every other `_config =` site, the sentinel becomes `copy.copy(mutmut.configuration.config())`.
     - The six `SubprocessRunner` / INT-1 timing tests take the grace from `SubprocessRunner(grace=…)` and use child sleeps of ≤ 0.2 s, for ≤ 0.5 s per test, with unchanged assertions (ADR §2g RV3-2(a)).
     - Measure-test rigs: build each distinct fixture repository once per module under `tmp_path_factory`, and give each test a `shutil.copytree` of it (ADR §2g RV3-2(a2)). Report the measure file's wall time and `git` spawn count before and after.
     - The autouse `monkeypatch.chdir(tmp_path)` fixture goes into each of the four gate test modules (ADR §2g RV3-7(a)).
  5. `new_code_gate.py`: the post-run workspace-integrity check (§5.9 step 5.4, ADR §2g RV3-7(b)), with its pinned exclusion list.
  6. Tests, new: EQ-MAP, IMP-TRAMP, G-SRCREAD, G-MUTSTATE, ISO-DIAG, PHASE-SEC, SLC-1, WS-INTEG-1 to 3 (§9.3). NOGLOBAL's sentinel changes as in item 4(c).
  7. **Sweep before the redone run.** With `--keep-workspace`, rerun each gate module's mutmut stats stage until it is clean. List every test fixed.
  8. **Redo condition 6 (§5.19)** on the final head:
     - Use the full-suite `run_tests.sh` sidecar. If the sandbox kills the suite (R-23), the human runs both commands outside it.
     - Report per file: mutants, the five seconds fields, the score and the core count.
     - If the projection is still over 20 CI-minutes, stop. The architect's measurement makes that likely. It is ADR §2g RV3-H1, a human decision. Do not apply any of its options.
  9. Do not open the PR until condition 6 passes and the local run passes (condition 7's first proof).
- **Affected sign-offs and built code for the Q8 ruling [ruled 2026-11-11: Q8].**
  - *Should this have been settled in the initial technical design?* It was raised there, as §14 Q8, before any code was written. The TD applied a stated provisional reading (no carve-outs in NQ-1) and the coder built to it. So this is the resolution of a recorded open question, not a startup-artifact gap, and no `startup-artifact-gap` issue is opened. The `raise SystemExit` shape was likewise listed explicitly as a near-miss (§5.5.3), so building to that was correct at the time.
  - **Sign-offs:** none exist. No reviewer has signed off on any commit of this branch (there is no sign-off register for #2304; the review chain runs on the whole branch, §11). No sign-off is orphaned.
  - **Built code that no longer matches the contract (commit `b1a26e887`, S2a, `scripts/framework/new_code_gate_logic.py`).** Each must change in a follow-up commit, after the architect reviews this delta:
    - `_is_main_guard`: add shape (a2), `raise SystemExit(<call>)` (§5.5.3).
    - `has_decision_logic`: return true only for findings with `carve_out` `null` (§5.5.1). Today it returns `bool(findings)`.
    - `zero_mutant_reason`: judge, and list lines from, only findings with `carve_out` `null` (§5.10). Today it fires on any finding.
    - `unmutatable_gated_lines`: compute `logic_lines` from findings with `carve_out` `null` (§5.10). No output changes today, but the definition must be the shared one.
    - **New (architect Q8-review fix):** a public `is_decision_logic(finding)` (§5.5.4). The four functions above call it, and so does `decision_fail_reasons`: today its `module` filter is an inline `not f["carve_out"]` and its `nq2` / `klass` filters do not test `carve_out` at all. No output changes, because `carve_out` is non-`null` only in the `module` region; the change makes the single predicate literal rather than three hand copies.
    - `selection_reason(…, logic_free)` itself is unchanged. It has no caller yet; its caller in `new_code_gate.py` (§11 commit 4, not built) must pass `logic_free = not any(is_decision_logic(f) for f in findings)`, computed from the **same** findings list that it passes to `zero_mutant_reason` and `decision_fail_reasons` (equivalently `not has_decision_logic(...)` over the same source and gated statements). It must never pass `not findings`.
  - **Built tests that now assert the old contract (`tests/framework/test_new_code_gate_logic.py`, same commit):** the `raise SystemExit(main())` case in the main-guard near-miss parametrization (it must move to the pass cases, Q5-MAIN); `test_zero_mutant_reason_names_lines_and_ignores_carve_outs` (its expectation inverts, Q5-NQ1 and Q8-PRED: the carved `try` source now gives `None`; the test is renamed to say the carve-outs are applied, and gains a case where an uncarved `if` beside the carved `try` gives a message naming only the `if`'s line). `test_selection_reason_nq1_carve_out` stands unchanged (it takes `logic_free` as given). The `has_decision_logic` parametrizations (`test_has_decision_logic_each_node_type`, `test_no_decision_node_without_ifs_asserts_or_with`) hold no carved shape, so they stand. New tests: Q5-RAISE and Q8-PRED (logic), and the rewritten Q5-NQ1 (measure, built in §11 commit 4).
  - **Q5-SELF filters (both commits, test-only; architect Q8-review fix):** the `SELF_CHECK` programs in `tests/framework/test_new_code_gate_logic.py` (`b1a26e887`) and `tests/framework/test_new_code_gate_plugin.py` (`b14e062db`) each hand-copy the predicate as `(f["region"] in ("module", "class") and not f["carve_out"]) or (f["region"] == "function" and f["unmutatable_reason"])`. Each must call `ncg.is_decision_logic(f)` instead of reading `carve_out`, so that §9.3's claim that Q5-SELF "calls the same shared predicate" is true. Their expectations do not change.
  - **Otherwise not affected:** commit `b14e062db` (S2b: the plugin, the `repo_copy` marker and the guard test). The plugin has no main guard and no carved shape, and Q5-SELF's expectations for it are unchanged. `shell_logic_check.py`'s seam is unaffected (its guard stays uncarved and ungated, §5.19). The `decision_fail_reasons` Q5 / NQ-2 outputs already exclude carved findings, so they are unchanged; only its filters move onto `is_decision_logic` (above).
- **Affected sign-offs for the 2026-11-11 ruling changes (Q4 to Q7) [ruled 2026-11-11: Q5]:** none.
  - Should this have been settled in the initial technical design? It **was** raised there, as §14 Q5, and the human has now answered it. So it is the resolution of a recorded open question, not a startup-artifact gap.
  - No code has been written against the round-5 §5.5 / §5.10. On the branch, `8113f8ba0` and the docs commit are the only commits, and neither implements the gate.
  - The architect's round-5 approval stands for every section this revision does not change. The changed sections (§5.5, §5.10, §5.14, §5.15.2, §5.18's shape bullet, §5.19's Q5 bullet, §9.3's Q5 rows, §12 R-2 / R-8a / R-15) need the architect's review of the delta before the coder implements them.
- **Affected sign-offs for the round-4 changes (U1 to U7, ADR §2c):** none. They change the design contract before any code exists, so every one of them is a correction to the initial design, not a startup-artifact gap against built work. No code, test or sign-off was built against the round-2 text.
- **Affected sign-offs for the round-2 changes:** none. No code, test or sign-off was built against the round-1 TD (the coder had not started). AR-1 changes which commit is gated, but the existing `tests` job already tests that commit (F-18), so no existing `tests` result or sign-off is affected. This matches ADR §2b "Affected sign-offs".
- **`8113f8ba0` stands.** It changes only the committed `[tool.mutmut]`, which keeps `run_tests.sh --mutation` runnable. The gate never reads that table (§5.8). Nothing in this TD depends on it or invalidates it.
- **Existing sign-offs:**
  - `shell_logic_check.py`'s count, exemptions and output are unchanged (R-SLC proves it). Its earlier sign-offs (#314, #1241) stand.
  - The `tests` job's meaning and `fail_under` are unchanged, subject to the S1 equivalence evidence. #1244's ruling stands.
  - The `unit-test.md` and contract §4 changes remove an allowed value, which is structural and human-gated. Earlier register entries that recorded N/A for Python are historical. They are not re-audited, because no merged code is re-gated by this PR.
- **ADR-2101:** unaffected in S2. S5 adds `NCG:<path>` with blob binding (§5.12), which amends ADR-2101 AD-8 in the S5 PR.

## 14. Open questions

For the **architect**: Q1 to Q3 are **closed** [round 2: T10].
1. **ADR-A1 to A8.** DECIDED, all accepted (ADR §2b; A4 with the attribution constraint, A7 extended to pytest). Applied in §2.3.
2. **Trusted base for `verdict`.** DECIDED: no trusted base (ADR §2b Q2, AD-2, residual ADR R-6 = TD R-10).
3. **ADR-A4.** DECIDED: attributed → per-file fail (exit 1); unattributed → exit 3 (§5.9 step 6; renumbered in round 4).

For the **human** (Q4 to Q7 **RULED 2026-11-11** [ruled 2026-11-11: Q5]):
4. **`Match` in the decision-logic set** (§5.5). **RULED 2026-11-11: confirmed.** `Match` statements count as decision logic (§5.5.1).
5. **Module-level / class-level decision logic** in a file that has mutants or a non-empty selection. **RULED 2026-11-11, which changes the design:** this logic is **not** coverage-only. It fails with "move the logic into a function so it can be mutated", using the same mechanism and AST definition as NQ-1 and NQ-2. The only carve-outs are (a) `if __name__ == "__main__":` whose body is only a call, (b) `try: import X` / `except ImportError:` fallbacks, and (c) `if TYPE_CHECKING:` (§5.5.3, §5.10). This agent's earlier recommendation (keep it coverage-only) is withdrawn.
6. **Shell files without a `.sh` extension** (`bin/**`). **RULED 2026-11-11:** out of scope for this PR, and tracked in #2305 (R-13).
7. **CLAUDE.md row.** **RESOLVED 2026-11-11:** the top-level session authors the row as a protected-surface edit, not the human (§6.7; §10 row 25; §11 commit 8).

For the **human** (raised by applying Q5; **RULED 2026-11-11** [ruled 2026-11-11: Q8]):
8. **RULED 2026-11-11 [ruled 2026-11-11: Q8]: yes, and consistently.** NQ-1 and NQ-2 treat the three carved-out shapes as non-decision-logic, through one shared predicate (§5.5.4): a finding is decision logic if and only if its `carve_out` is `null`. A zero-mutant, empty-selection file whose only logic is carved now passes NQ-1 under its normal conditions (zero gated mutants and gated coverage ≥ 80%). NQ-2 outcomes do not change, because a carved shape is never function region (§5.5.4). The ruling also adds `raise SystemExit(<call>)` as an accepted main-guard body, exactly equivalent to `sys.exit(<call>)` (§5.5.3 (a2)); every other near-miss stays strict (Q5-RAISE). Effect: the Q5 population falls from 33 to 25 of 95 (§7.1a). Built code to change: §13.
   - **Reading to confirm in the PR review.** The ruling says carve-out (a) "accepts a body consisting only of a single `sys.exit(<call>)` or `raise SystemExit(<call>)` statement", "with the same strictness as before". Before Q8, (a) accepted **any** single `Expr(Call)` body, which includes a bare `main()` (19 production guards). This TD reads "same strictness as before" as keeping that, so (a1) is unchanged and (a2) is added. If the human meant to narrow (a1) to `sys.exit(<call>)` only, the 19 bare-`main()` guards would become Q5 findings and the population figure in §7.1a would rise from 25 to 39 of 95 (the same survey, with (a1) narrowed to `sys.exit(<call>)`). That would be a one-line change to `_is_main_guard` plus Q5-MAIN. **Architect ruling (2026-11-11): this TD's reading is upheld as the technical default** (see the Q8 review ruling below). Narrowing would add 14 files to Q5, but 13 of them are already PL files, so the combined first-touch population would move only from 65 to 66 of 95. The item stays open for the human's confirmation in the PR review.
   - The question as it was raised, kept for the record: **Do the Q5 carve-outs also apply to the NQ-1 check?** NQ-1 (ruled 2026-11-10) lets a zero-mutant, empty-selection file pass only when its gated lines hold no decision logic, and it names `Try` and `If` in that set. The Q5 ruling sets out the carve-outs for the module-level rule. It does not say that they relax NQ-1. **Until you rule, this TD applies NQ-1 unchanged, without the carve-outs** (§5.5.1, §5.10, Q5-NQ1). The effect is that a new `__init__.py` or constants module whose only logic is a carved-out `try: import …` / `except ImportError:` fallback (or a `TYPE_CHECKING` block or a call-only main guard) still fails NQ-1 with "move logic into a function so it can be mutated". It only gets through if some test's context selects it. **Recommendation:** apply the carve-outs to NQ-1 as well. None of the three shapes can be moved into a function in any meaningful way, and the narrowness of the shapes keeps that from loosening anything else. This is a loosening of a ruled item, so it is yours to decide, not this agent's.

### Architect review requested

Round 4 of 5, for the architect's round-5 confirmation of U1 to U7 (ADR §2c). Round 5 is the last round the loop allows: if the architect does not approve in round 5, this agent escalates to the human with the iteration count, the per-round changes and the unaccepted point, and does not start a sixth round. Revision notes are at `.claudetmp/design/technical-design-2304-<timestamp>.md`. Points this revision decided that the architect should check: (1) `-p no:cacheprovider` added to the R3-G collect argv (§5.6 step 3); (2) container IDs from name fallback are kept and deselected at run time, with residual R-14; (3) the short-summary parse reads the **last** section; (4) the no-test-case stop runs `_collect` with `expect_unrun = true` (all gated exit codes must be `null`); (5) plugin idempotency is per module copy, not global (§5.18); (6) R-S1b's literal is `[128 + k, 135 + k]` plus a content pin.

**Architect round-5 ruling: APPROVED.** All six points are accepted. (1) `-p no:cacheprovider` was verified: the exact argv gives rc 5 with "no tests collected (N deselected)" when every ID is deselected, rc 0 with IDs, a blank line and then the count otherwise, and rc 4 for an unknown node ID (→ exit 3). (2) R-14 is accepted as fail-closed. (3) Last section: pytest prints the header only when there are `-rfE` lines (`terminal.py:1427`), and mutmut dumps a stage's output only when that stage fails (`__main__.py:329-334, 988-995`), so the last section belongs to the failing stage. (4) This holds: a fresh workspace writes every key as `None` at generation (`__main__.py:205-215`). (5) Per-copy idempotency plus `uninstall()` is accepted. (6) Accepted: lines 128 and 135 and both content strings were verified at `8113f8ba0`.

### Architect review requested: the 2026-11-11 delta [ruled 2026-11-11: Q5]

The round-5 approval covered the TD as it stood on 2026-11-10. This delta applies the human's Q5 ruling, and it changes §5.5 and §5.10, so the architect must review it before the coder implements those sections. This is a new, ruling-driven revision, not a sixth round of the round-5 loop. Notes: `.claudetmp/design/technical-design-2304-20261111T000000Z.md`.

Points to check:
1. §5.5.2 assigns regions by AST containment (the `body` field only), so decorators, defaults and annotations take the enclosing scope's region.
2. There are two new unmutatable reasons, `non_top_level_function` and `definition_time_expression`. `decorated_function` now applies at any depth, matching `_skip_node_and_children`. Without these, "move it into a function" could move the logic into a function that mutmut still does not mutate.
3. Carve-outs are recognised only on direct children of `Module.body`, with the exact shapes and near-misses listed in §5.5.3.
4. A Q5 fail does not stop the mutation run.
5. NQ-1 is applied without the carve-outs until the human rules on §14 Q8.
6. Enum and single-line-class bodies are class region, so they get the Q5 code and not NQ-2.
7. Q5-SELF runs its analysis in a subprocess, so it is never selected and never reads a trampolined copy.
8. The plugin and gate-module shape constraints are in §5.18 and §5.19. They include no `@functools.wraps` on wrappers, and the `_STATE = _load_state(os.environ)` read, with P-ENV (b) adjusted to allow it.

**Architect ruling on the 2026-11-11 delta: APPROVED (with in-place fixes).** The coder may implement §5.5 and §5.10. All eight points were checked against the installed mutmut 3.8.1 `file_mutation.py`. (1) Correct: `OuterFunctionProvider` (150-178) marks only top-level defs and the statements of top-level indented class bodies; `combine_mutations_to_source` (412-453) trampolines only `FunctionDef` members of those, so module-level, class-body and nested-class mutations are dropped. Decorators (`cst.Decorator`, 353-354), annotations (`cst.Annotation`, 323-324) and non-simple `cst.Param` defaults (330-335) are skipped at any depth. (2) Both new reasons are right, and `decorated_function` at any depth matches 342-347, which is not limited to the top level. (3), (4), (6), (7) and (8) are accepted. (5) is coherent: see Q8 below. The architect applied three in-place fixes, each marked "architect delta-review fix". They make §5.5.2 copy mutmut's scope exactly, which R-15 already claims it does: `enum_body` and `never_mutate_name` are now defined precisely, and `never_mutate_name` now covers the `len` / `isinstance` call-argument skip (320), which has a real production instance. `definition_time_expression` now also covers `AnnAssign` annotations, lambda defaults and the f-string-is-simple case. Q5-DEC gains cases (x) to (xii). §7.1a now states the separate NQ-2 population. **Q8 (human's call; ruled 2026-11-11, see §14 Q8 and the Q8 review request below):** the provisional behaviour, NQ-1 without the carve-outs, is coherent and fail-closed. One predicate (`has_decision_logic`) decides it, so a ruling either way is a one-line change pinned by Q5-NQ1. The architect recommends applying the carve-outs to NQ-1. NQ-1 exists for import-time-only files that no test can select (AF-3). The three carved shapes are exactly the import-time constructs that cannot usefully be moved into a function. Under the strict reading, an `__init__.py` holding `if TYPE_CHECKING: from .x import Y` fails, and the only advice it gets cannot be acted on.

### Architect review requested: the Q8 delta [ruled 2026-11-11: Q8]

The human ruled Q8 on 2026-11-11, in line with the architect's recommendation above, and added one shape. This is a ruling-driven delta, not a new design round. The architect's approval of the 2026-11-11 Q5 delta stands for everything this delta does not change. Notes: `.claudetmp/design/technical-design-2304-20261111T120000Z.md`.

Points to check:
1. **One predicate** (§5.5, §5.5.1, §5.5.4): a finding is decision logic if and only if `carve_out` is `null`. NQ-1, NQ-2, Q5, `has_decision_logic` and the `unmutatable_gated_lines.has_decision_logic` field all use it.
2. **NQ-2 is unchanged in outcome**, because `carve_out` is non-`null` only in the `module` region and NQ-2 reads only `function`-region findings (§5.5.4, §5.10, Q8-PRED).
3. **Shape (a2)** (§5.5.3): `Raise(exc=Call(func=Name("SystemExit"), args=[<Call>], keywords=[]), cause=None)`, excusing the same nodes as (a1). The near-miss list and Q5-RAISE.
4. **The (a1) reading** (§14 Q8): a bare `main()` body stays accepted. Flagged to the human for confirmation.
5. **NQ-1 coverage still applies** (§5.10, §7.2): a small carved-only file can fail `coverage_below_threshold`, never `zero_mutant_decision_logic`. The Q5-NQ1 fixtures compute the 80% ratio instead of hard-coding it.
6. **Population** (§7.1a): Q5 falls from 33 to 25 of 95; PL plus Q5 is 65 of 95 (heuristic upper end). Not yet re-run independently.
7. **Built code** (§13): commit `b1a26e887` must change in four functions (`_is_main_guard`, `has_decision_logic`, `zero_mutant_reason`, and `unmutatable_gated_lines`' `logic_lines`) and two tests. `b14e062db` is unaffected. The not-yet-built `selection_reason` caller (commit 4) must use the new `has_decision_logic`.

**Architect ruling on the Q8 delta: APPROVED (with in-place fixes, each marked "architect Q8-review fix").** The coder may make the §13 follow-up commit, then build §11 commit 4.
1. **One predicate: accepted, and made literal.** The design said "one predicate" but the built code holds three hand copies of it (`decision_fail_reasons`' inline `not f["carve_out"]`, and the two Q5-SELF `SELF_CHECK` filters). §5.5.4 now names one public `is_decision_logic(finding)`, every consumer calls it, and Q8-PRED gains a static check that nothing else reads `carve_out`. Without that, the next carve-out change would have to be made in five places, and Q8-PRED's behavioural cases would not catch a missed one in a test filter.
2. **NQ-2 unchanged: verified.** In the built code, `carve_out` is set only in the `region == "module"` branch of `decision_logic_findings`, and `_carve_out_for` excuses only the top-level statement node itself and, for a main guard, its `test`. Both are module region by construction. Every node *inside* a carved statement that is in a def body (for example a fallback def in an `ImportError` handler, or a def under `if TYPE_CHECKING:`) is `function` region with `carve_out: null` and `non_top_level_function`, so it still fails NQ-2. That matches mutmut 3.8.1: `OuterFunctionProvider.visit_Module` (`file_mutation.py:166-177`) trampolines only direct `Module.body` `FunctionDef`s and the statements of direct `Module.body` indented `ClassDef`s, so nothing under a module-level `if` or `try` is ever mutated. A carved-header line can never be an `unmutatable_gated_lines` line either: a carved finding's `line` is a `Module.body` statement's first line, and no def-body statement can start on a compound header's line.
3. **Shape (a2): accepted.** Checked against `ast` on Python 3.14: `raise SystemExit(main()) from None` gives `cause=Constant(None)`, so the test must be `stmt.cause is None` (the Python value), which rejects it as the near-miss list requires. `Starred` and `**` arguments fall out of the `args[0]` is `Call` and empty-`keywords` tests. The (a1)/(a2) asymmetry (`sys.exit(1)` carved, `raise SystemExit(1)` not) follows from the ruling's wording and is fail-closed. It is now recorded in §5.5.3 so that nobody harmonises it without a ruling.
4. **The (a1) reading: technical-design's reading is upheld.** A bare `main()` body stays accepted. Reasons: (i) the controlling text for (a1) is the human's Q5 ruling, "body is only a call", with `sys.exit(main())` given as an *example*; (ii) Q8 is worded as an *addition* ("`raise SystemExit(<call>)` is added as an accepted main-guard body"), and "same strictness as before" says the pre-Q8 strictness is kept, not that it is newly narrowed; (iii) narrowing would be a tightening that nobody asked for, and it would add 14 files to the Q5 population (39 of 95, verified). The architect does not adopt a reading that changes ruled behaviour on an ambiguity. Consequence the human should know when confirming: of those 14 files, 13 (the `scripts/oversight/validators/*` CLIs) are already in Appendix A's PL population and fail on first touch anyway, so narrowing would move the combined first-touch population only from 65 to 66 of 95. The only file it would newly expose is `scripts/oversight/token_tracker.py`. The §14 Q8 confirmation item stays in the PR's CODEOWNER review, as flagged; this ruling is the technical default until the human says otherwise.
5. **NQ-1 "passes, but coverage still counts": accepted.** This is the ruled NQ-1 text itself (its carve-out has always been "zero gated mutants **and** gated coverage ≥ 80%"). It is also how the built `selection_reason` already treats a logic-free zero-mutant file such as Q5-NQ1 (viii), so Q8 makes carved files behave like logic-free ones and adds no new path. Reporting the under-80% case as `coverage_below_threshold` rather than `no_test_exercises` is correct: for a zero-mutant file coverage is the only real objection left, and it keeps the case ruling-eligible after S5, as it is for any logic-free file. The fixture must compute its 80% padding from `PythonParser.statements` (as written), because whether coverage counts the `try:` and `except` header lines is coverage's decision, not ours.
6. **Population: independently verified.** A separately written classifier (not the TD's script and not the built code) over the 95 files at `8113f8ba0` gives 33 → 25 of 95, the same node counts (18 `If`, 18 `Compare`, 14 `Try`, 4 `BoolOp`, 2 `GeneratorExp`, 1 `DictComp`, no class-level findings), the same 8 cleared files, a 65-of-95 union with Appendix A (17 overlap, the same 8 Q5-only files), and 39 under narrowed (a1). One miscount was fixed in §7.1a: there are also 2 carved `sys.exit(_main(sys.argv[1:]))` guards (58 of 64 guards are carved).
7. **Built code: confirmed, with two additions** (§13): `decision_fail_reasons` moves onto `is_decision_logic`, and the Q5-SELF filter in `test_new_code_gate_plugin.py`, which is in `b14e062db`, does too (test-only; S2b is otherwise unaffected). The commit-4 caller must compute `logic_free` from the same findings list and never as `not findings`.
- **R-16: accepted as worded.** It is the honest residual. It names what is now never mutated and never selected, and it is bounded by exact shapes plus H2 coverage.
- **Startup-gap:** this is the resolution of a recorded open question (§14 Q8), raised before code existed, and the code was built to the stated provisional reading. It is not a `startup-artifact-gap`. No sign-off exists against `b1a26e887` or `b14e062db`, so none is orphaned. The architect's earlier approvals stand for every section this delta does not change.

## Appendix A. First-touch module list (#2305 work list) [round 2: T5]

Produced by the architect's `survey.py` at `8113f8ba0`, re-run by this agent. `bare:<n>` = bare-imported by n test files through `tests/conftest.py`'s `sys.path` injection (AST-exact). `path:<n>` = path-loaded by n test files (literal-match heuristic; may over- or under-count). 95 tracked production `.py` files; 26 bare, 39 path, 8 both, 57 in the union. `shell_logic_check.py` is converted by this PR (§5.19).

| # | Module | Tags |
|---|---|---|
| 1 | `bin/lib/usage_pause.py` | path:2 |
| 2 | `bootstrap/lib/hos_tmp_root.py` | path:4 (shared harness, F-6) |
| 3 | `bootstrap/tmp_reaper.py` | path:2 (shared harness, F-6) |
| 4 | `scripts/automation/in_progress.py` | path:1 |
| 5 | `scripts/automation/lib/codeowners.py` | path:2 |
| 6 | `scripts/automation/lib/gate_compliance.py` | path:1 |
| 7 | `scripts/automation/lib/github.py` | path:1 |
| 8 | `scripts/automation/lib/observability.py` | path:1 |
| 9 | `scripts/automation/lib/probe.py` | path:1 |
| 10 | `scripts/automation/lib/triage.py` | path:2 |
| 11 | `scripts/automation/pr_review_cli.py` | path:1 |
| 12 | `scripts/framework/audit_predicate.py` | path:1 |
| 13 | `scripts/framework/gen_sandbox_config.py` | path:1 |
| 14 | `scripts/framework/require_human_approval.py` | path:3 |
| 15 | `scripts/framework/require_overseer_approval.py` | path:3 |
| 16 | `scripts/framework/require_tier_ceiling.py` | path:2 |
| 17 | `scripts/framework/rerun_gate_checks.py` | path:1 |
| 18 | `scripts/oversight/agents_static_logic.py` | path:1 |
| 19 | `scripts/oversight/change_classifier.py` | path:3 |
| 20 | `scripts/oversight/codeowners.py` | bare:1, path:2 |
| 21 | `scripts/oversight/lib/audit_log.py` | path:3 |
| 22 | `scripts/oversight/mcp_policy_logic.py` | path:2 |
| 23 | `scripts/oversight/panel_logic.py` | path:2 |
| 24 | `scripts/oversight/prompt_audit_logic.py` | path:2 |
| 25 | `scripts/oversight/record_agent_model.py` | bare:1 |
| 26 | `scripts/oversight/release_artifact_logic.py` | path:1 |
| 27 | `scripts/oversight/release_logic.py` | path:1 |
| 28 | `scripts/oversight/release_panel_logic.py` | bare:1, path:1 |
| 29 | `scripts/oversight/retry_rescue_logic.py` | bare:1, path:2 (shared harness, F-6) |
| 30 | `scripts/oversight/second_review_logic.py` | path:4 |
| 31 | `scripts/oversight/secret_scan_logic.py` | path:2 |
| 32 | `scripts/oversight/security_scan_logic.py` | path:1 |
| 33 | `scripts/oversight/signoff_gate.py` | path:1 |
| 34 | `scripts/oversight/suspension_manager.py` | path:2 |
| 35 | `scripts/oversight/validation_logic.py` | bare:2, path:5 |
| 36 | `scripts/oversight/validators/brownfield.py` | path:1 |
| 37 | `scripts/oversight/validators/complexity_metrics.py` | bare:2 |
| 38 | `scripts/oversight/validators/complexity_metrics_js.py` | bare:1 |
| 39 | `scripts/oversight/validators/diff_size.py` | bare:1, path:1 |
| 40 | `scripts/oversight/validators/function_metrics.py` | bare:1 |
| 41 | `scripts/oversight/validators/function_metrics_js.py` | bare:1 |
| 42 | `scripts/oversight/validators/hallucination_surface.py` | bare:3 |
| 43 | `scripts/oversight/validators/hallucination_surface_js.py` | bare:1 |
| 44 | `scripts/oversight/validators/ip_check.py` | bare:2 |
| 45 | `scripts/oversight/validators/issue_query.py` | bare:2 |
| 46 | `scripts/oversight/validators/migration_scorer.py` | bare:2 |
| 47 | `scripts/oversight/validators/n1_detector.py` | bare:1 |
| 48 | `scripts/oversight/validators/n1_detector_js.py` | bare:1 |
| 49 | `scripts/oversight/validators/portability_check.py` | bare:1 |
| 50 | `scripts/oversight/validators/prompt_audit_risk.py` | bare:2 |
| 51 | `scripts/oversight/validators/regions.py` | bare:7, path:1 |
| 52 | `scripts/oversight/validators/rn_calculator.py` | bare:1, path:1 |
| 53 | `scripts/oversight/validators/rn_calculator_js.py` | bare:1 |
| 54 | `scripts/oversight/validators/schema.py` | bare:8, path:4 |
| 55 | `scripts/oversight/validators/shell_logic_check.py` | bare:1 (converted in this PR) |
| 56 | `scripts/oversight/validators/static_analysis.py` | bare:2 |
| 57 | `scripts/oversight/validators/static_analysis_js.py` | bare:1 |

Not in this list, but in the same first-touch population and unquantified (§7.1): modules exercised only through a subprocess, modules whose selected tests need the real `.git` or `.claude/`, and modules whose selections exhaust the budget.
