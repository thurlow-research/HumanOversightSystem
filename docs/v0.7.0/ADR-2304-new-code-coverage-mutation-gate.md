# ADR-2304: A deterministic `new-code-gate` holds new and changed Python to 80% line coverage and a 75% mutant score. Tests are chosen from per-test coverage contexts. Mutation runs in a fresh `git archive` workspace (never `.claude/`) with a generated mutmut config, gated mutants only, one run per file. The gate is three jobs: measure, verdict and ingest. The overseer ingests the records into the audit trail. There is no exception path until the one shared human-authorization verifier exists

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-12 bind `technical-design`. AD-13 recorded the provisional strictest defaults for OQ-H1 to OQ-H5 and NQ-1 to NQ-3. It is now **superseded by AD-13a**, the human rulings of 2026-11-10, which are final. Lines changed to apply those rulings carry `[ruled 2026-11-10]`. The product-boundary checkpoint in §5 must clear before AD-9 (a new overseer App permission and a new overseer obligation) binds. NQ-3 is unruled, because S3 is out of scope for the first PR. **Amended 2026-11-10 (architect, TD-2304 round 1):** AD-1, AD-2, AD-3, AD-4, AD-5, AD-6, AD-7 and AD-12 change per §2b (ADR-A1 to A9 and AR-1). Changed lines carry `[amended 2026-11-10]`. Those amendments are technical corrections, not rulings, and change no ruled behaviour. **Amended again 2026-11-10 (architect, TD-2304 round 3):** §2c (R3-A to R3-H), with changed lines tagged `[amended 2026-11-10, round 3]`. These are also technical corrections only. **Clarified 2026-11-10 (architect, TD-2304 round 5):** §2d (R5-A), with no ruling changed. TD-2304 was APPROVED in round 5. **Ruled 2026-11-11 (human, TD-2304 §14 Q4 and Q5):** two new AD-13a rows, plus R-2. These lines carry `[ruled 2026-11-11: Q5]` / `[ruled 2026-11-11: Q4]`. **Ruled 2026-11-11 (human, TD-2304 §14 Q8):** one new AD-13a row, recording the ruling only, tagged `[ruled 2026-11-11: Q8]`.
**Date:** 2026-11-10
**Author:** architect, dispatched from the human-proxy session. The human (ScottThurlow) stated rulings R1 to R8 directly in that session. This ADR treats them as confirmed. It does not originate them.
**Issue:** #2304 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** The gate is new required merge-gate code. It lands on protected surfaces: `.github/workflows/**`, `scripts/framework/**`, `.claude/agents/**` and `contract/**`.
**Inputs:**
- `docs/specs/SPEC-2304-new-code-coverage-mutation-gate.md` (REQ-1 to REQ-35, AC-1 to AC-34, OQ-A1 to OQ-A8, OQ-H1 to OQ-H5).
- `.github/workflows/tests.yml` and `.github/workflows/require-human-approval.yml` (trusted-base pattern).
- `.github/workflows/rerun-gate-checks.yml`, `scripts/framework/run_tests.sh` and `scripts/framework/hos_required_contexts.txt`.
- `pyproject.toml` (`[tool.coverage.*]`, and `[tool.mutmut]` as of `8113f8ba0`) and `scripts/oversight/requirements.txt:71-84`.
- From the installed mutmut 3.8.1 package: `mutmut/configuration.py`, `mutmut/__main__.py:114-238`, `mutmut/mutation/file_mutation.py:86-147` and `mutmut/mutation/diff_apply.py`.
- `scripts/oversight/codeowners.py`, `scripts/oversight/lib/audit_log.py` and `bin/hos-cron:573` (`_sync_audit_logs`).
- `docs/v0.7.0/REQUIREMENTS-1803-audit-trail-commit.md` (VF-4 to VF-6, the #1538 R4 trail-of-record ruling).
- `docs/v0.7.0/ADR-2101-github-native-human-authorization.md` (AD-1 to AD-5).
- `docs/v0.6.0/ADR-035-audit-approval-bot.md` (the history of the auditsync identity).
**Consumers:** `technical-design` → `coder` → the review chain.
- `security-reviewer` is mandatory on S2 (a new required gate that reads PR-authored data and runs PR-authored tests), S3 (an overseer ingest of CI-produced bytes, plus a new App permission) and S5 (exception verification).
- `reliability-reviewer` is mandatory on S1 (it changes the existing required `tests` job) and S2 (budget and timeout behaviour).
- `privacy-reviewer` is mandatory on S3 (new audit events carrying logins and URLs).
- The `.claude/agents/**` edits in S4 are written by the top-level session, never by `coder` (CLAUDE.md, #1347).
**Explicitly does NOT re-litigate:** R1 to R8; the targets; the suite-wide `fail_under = 78` (REQ-8); #1538 R4 (the trail of record is `origin/audit-log`, and there is no audit PR); ADR-2101's verifier design; #2305's scope.

---

## 0. Verification findings (working tree at `8113f8ba0`)

### 0.1 Confirming the spec and the relayed facts

- **VF-1 CONFIRMED.** mutmut 3.8.1 reads config from `./pyproject.toml` `[tool.mutmut]` in the current directory. Only when that table is absent does it fall back to `./setup.cfg` (`configuration.py:61-107`). It always copies `tests/`, `pyproject.toml` and `setup.cfg` into `mutants/`, plus each `also_copy` entry (`:184-195`). So the "selection per run" problem is a property of the **cwd**. A gate that runs mutmut in its own workspace can give it its own config without touching the committed `pyproject.toml`.
- **VF-2 CONFIRMED: stale-mutant reuse is mtime-based.** `create_mutants_for_file` (`__main__.py:155-172`) reuses a mutant file when the source is older than the existing `mutants/<path>`. A leftover `mutants/` therefore silently survives a source change that preserves mtimes, for example a checkout or an archive extract with old timestamps. REQ-19 is real.
- **VF-3 CONFIRMED: `only_mutate` exists and copies non-matching files unmutated** (`configuration.py:283-292`, `__main__.py:139-143`). Directory `source_paths` can therefore stay broad while mutation is restricted to one file.
- **VF-4 CONFIRMED: mutmut 3.x mutant keys are per-function, not per-line.** A key is `<module>.x_<func>__mutmut_<n>`. A `Mutation` carries the original and mutated CST nodes (`file_mutation.py:86-91`). `MutantLineSpans` records spans in the **generated** file, not the source. The only line-accurate mapping is to apply the mutant to the original module and diff, which is what `apply_mutant` does (`diff_apply.py:164-186`).
- **VF-5 CONFIRMED.** `[tool.coverage.run] source` is `scripts/oversight`, `scripts/automation/lib` and `scripts/framework`, with `branch = true`. `run_tests.sh:75-82` passes the same three `--cov=` flags. `bootstrap/*.py` and top-level `scripts/automation/*.py` are not measured today (REQ-7's premise).

### 0.2 Architect findings (these change the design)

- **AF-1 (HIGH): mutmut is not pinned to 3.8.1.** `requirements.txt:84` is `mutmut>=3.6,<4.0`. AD-4 depends on mutmut internals (`mutate_file_contents`, the CST apply, the key format, the "trampoline hits" message). A minor bump could silently change the key format or the mapping. The gate must pin `mutmut==3.8.1` and assert the installed version at runtime, failing closed on a mismatch. `coverage` (7.17.2 installed) and `pytest-cov` (7.1.0) are also floating. The gate pins them the same way, because the context table format and `COVERAGE_CORE` behaviour are part of its input contract.
- **AF-2 (HIGH): the spec's "executable statement line" definition lets a change escape the gate.** coverage.py attributes a multi-line statement to its **first** line. A PR that edits only the second line of a multi-line call, or a continuation line of a condition, changes no line that coverage calls a statement. Under §3 as drafted, that change has zero gated lines and is not gated at all. AD-3 maps each changed line to the statement that contains it. This is a correction to the spec's definition (§7, D-1).
- **AF-3 (HIGH): R2's "empty selection fails" falsely fails import-time-only files.** Lines run during pytest collection are recorded under the **empty** context, not under any test, because collection is not a test phase. A new `__init__.py` holding only re-exports, or a constants-only module, can be 100% covered with zero mutants and still have an empty context selection. The name fallback then usually finds nothing, so REQ-16 fails it. No test can fix this, because the module is already imported (and cached) by collection before any test context starts. This is a defect in the ruling as applied, not a design choice. It was raised as NQ-1 (§6) and is now ruled (AD-13a): the carve-out applies only when the gated lines hold no decision logic.
- **AF-4 (HIGH): code exercised only through a subprocess earns neither coverage nor kills.** `--cov-context=test` attributes in-process execution only. A child process gets no test context, and no coverage at all without `COVERAGE_PROCESS_START`. mutmut records which tests hit which function trampoline in-process, so a mutant reached only by a subprocess is "no tests", which is not killed. CLI-style tests that run `python scripts/x.py` therefore count for nothing. That is consistent with R1 and R2, and the fix is to test `main(argv)` in-process. But it is a product consequence: some honest PRs that touch subprocess-tested code will fail. It is stated in the §5 checkpoint, and `pyproject.toml:35-39` already records the same blind spot for `require_human_approval.py`.
- **AF-5 (MEDIUM): mutmut skips whole classes of code by design.** Decorated functions (other than `staticmethod` and `classmethod`), enum bodies, single-line classes and default arguments produce no mutants (`file_mutation.py:327-352`). Gated lines inside them yield zero mutants and pass under REQ-12 on coverage alone. That is a loophole the spec does not name. AD-4 makes it visible: the record carries `unmutatable_gated_lines` (gated statements that lie inside functions or classes but on which mutmut generated no mutant). The gate does not fail on it. Whether it should is NQ-2.
- **AF-6 (MEDIUM): REQ-26's "committed audit log (`audit/log/…`)" names the wrong location.** Under #1538 R4 the trail of record is `origin/audit-log`. Records are never committed to `main`, and there is no audit PR (REQUIREMENTS-1803 VF-4, VF-6, §2). Both cron roles already push to `audit-log` every cycle through `bin/hos-cron:_sync_audit_logs`. The route in AD-9 lands records there. pm-agent must amend REQ-26 to say "trail of record" (§7, D-4).
- **AF-7 (MEDIUM): the spec's interim exception rule is not CI code.** §3 says verified rulings use "the evaluator's CODEOWNER-comment rule until [#2219 lands]". That rule is agent prose in `oversight-evaluator.md`, so a CI gate cannot execute it, and R1 forbids agent attestation. ADR-2101 AD-2 binds **one** verifier, `scripts/framework/human_authorization.py`, and says every consumer calls it. It is not built (`git grep` finds no such module). Building a gate-local comment parser would create a second human-authorization trust predicate, which AD-2 forbids for good reason. AD-10 follows from this.
- **AF-8 (MEDIUM): the gate cannot be tamper-proof against the PR's own tests, and must not claim to be.** The `tests` job runs PR-authored tests in the process that writes `.coverage`. A test can monkeypatch coverage, write the data file, or patch the gate's plugin hooks. The same is true of the existing `tests` gate. The gate's integrity model is "deterministic and honest-input": it stops lazy or mistaken agents from passing untested code, and it stops N/A attestations. It does not stop an adversary who writes tests that tamper with measurement. That class is caught by review of `tests/**`. The gate's own code is under `scripts/framework/**`, which is protected. This is stated so no reviewer reads the gate as a security boundary (§3, R-4).
- **AF-9 (LOW): name fallback rarely changes a pass/fail result.** If no test context executed any gated line, gated-line coverage is 0% unless the lines ran at collection time (AF-3), and mutants inside functions have no killers. Name fallback only matters for the AF-3 import-time case. It is kept because R2 requires it, and the record shows `selection_method` so its effect can be seen.

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` for a diff-to-changed-lines helper, a coverage-context reader, a CI-artifact-to-audit ingest, a mutmut wrapper and a ruling verifier.
- Found: `scripts/oversight/validators/shell_logic_check.py`, reused unchanged for REQ-21 (AD-8).
- Found: `scripts/oversight/codeowners.py` and `scripts/framework/require_human_approval.is_bot_reviewer`. These are inputs to ADR-2101's verifier, not to a new one.
- Found: `scripts/oversight/lib/audit_log.write_event` and `bin/hos-cron:_sync_audit_logs`, reused by AD-9.
- Found: `run_tests.sh --mutation`. It runs the whole suite per mutant (its own header says so) and parses `mutmut results` with regexes. It is **not** reused. It stays as the developer-only whole-repo mutation path, untouched.
- Not found: any CI-artifact ingest, a coverage-context reader, or a changed-line mapper. These are new.

---

## 1. Organising principle

The gate turns two numbers per gated file into a pass or a fail. Every input to them is pinned, every step is recomputed from git, coverage data and mutmut output, and every gap fails closed. Measurement is expensive and runs once per head. Judgement (thresholds plus exceptions) is cheap, pure and can be re-run. Recording is a separate, idempotent step that happens off the PR's read-only token. Those three concerns run as three separate units, so none of them has to compromise for another.

---

## 2. Decisions

### AD-1 — One entry point, two phases. (BINDING; REQ-1, REQ-3, REQ-4; OQ-A2 in part.)

- **Module layout.** All logic goes under the protected `scripts/framework/`, importable canonically. The gate's own tests must import it that way (R4 applies to the gate too).
  - `scripts/framework/new_code_gate.py`: the CLI. `measure`, `verdict` and `run` (= measure then verdict, for local use).
  - `scripts/framework/new_code_gate_logic.py`: pure functions. These are diff to gated lines, contexts to selection, mutant mapping, record schema and `decide(records, rulings, thresholds) -> outcomes`.
  - `scripts/framework/new_code_gate_pytest_plugin.py`: the in-workspace tripwire plugin (AD-6, AD-7).
- **There is no shell wrapper.** Callers run `scripts/oversight/.venv/bin/python -m scripts.framework.new_code_gate <phase> …`. A wrapper would itself be shell with decision logic, and REQ-21 would then fail it.
- **CI and local runs use the same phases.** CI runs `measure` and `verdict` in separate jobs (AD-2). Local runs use `run`, which calls the same two functions in-process in sequence. AC-30's static test asserts that the workflow invokes `-m scripts.framework.new_code_gate measure` and `… verdict`, and nothing else.
- **Exit contract (both phases).** 0 means the phase completed and, for `verdict`, every gated file is `pass` or `excepted`. 1 means a decided fail on complete data. 3 means could not decide (any REQ-4 internal error), and the cause is named on stderr and in the record. 2 means a usage error. **Every caller treats non-zero as fail.** The workflow step simply propagates the exit code.
- **Test-caused failures are decided fails, not internal errors [amended 2026-11-10, ADR-A4].** A selected test that fails when run alone in the workspace, or an unmarked repo copy caught by the tripwire, is a per-file `fail` with a named reason: `measure` records it and exits 0, and `verdict` exits 1. These come from the PR's own tests and have a named, deterministic fix. Keeping them per-file also keeps the other files' results in the table. The constraint is **attribution**. The classification applies only when the failure is attributed: either the failing node IDs are parsed from mutmut's output and are a subset of the file's selection, or a tripwire or path-load event names the node. An unattributed clean-run failure is exit 3 ("clean run failed and no selected test could be identified"). It is never reported as a test failure with "see log". Neither class is ever ruling-eligible.
- **Measure exits 0 even when files fall below target.** The `measure` phase **measures, it does not judge**. Thresholds are applied only by `verdict`, so a ruling can be re-applied without re-measuring.
- **Local-run precondition.** `run` gates the `HEAD` commit, not the working tree. It refuses with exit 3 if `git status --porcelain --untracked-files=no` shows any modified tracked `.py` or `.sh` file. It also refuses if the coverage sidecar (AD-2) names a different head or a dirty tree. Coverage data from an uncommitted tree cannot be matched to a commit, so it is not evidence.
- **Not shipped.** None of these files goes in `framework_consumer_files.txt` (spec §6).

### AD-2 — Workflow placement: extend `tests` to produce context data, and add two jobs, `new-code-measure` and `new-code-gate`. Only `new-code-gate` is a required context. (BINDING; OQ-A2, REQ-2, REQ-13, REQ-29.)

**`tests` (existing job; modified in S1).**
- `run_tests.sh` gains context recording on its single normal run. There is **one** full-suite run per head, and R2 says contexts come from "the normal coverage run".
  - It sets `COVERAGE_CORE=ctrace` explicitly. CI uses Python 3.12, where ctrace is already coverage's default core, so the pin costs nothing there. It also stops a future default change (sysmon) from silently dropping contexts.
  - It adds `--cov-context=test`.
- **Measured surface [amended 2026-11-10, ADR-A3].** The run measures every top-level directory that holds production Python, so REQ-7's files outside `source` are measured.
  - It keeps the three current `--cov=` roots **as explicit sources** and adds `--cov=scripts --cov=bootstrap --cov=bin`.
  - `--cov=.` is rejected. coverage.py's unexecuted-file discovery (`files.find_python_files`) prunes any subdirectory below a source root that lacks `__init__.py`. `scripts/oversight/` and `scripts/framework/` have none, so a walk from `.` would drop their never-imported files. The suite-wide total would then rise, which silently loosens REQ-8.
  - Run-time `omit` drops `*/__init__.py`, `*/test_*` and `*/conftest.py` and adds `mutants/*`, so a new non-empty `__init__.py` is measured.
  - The suite-wide report re-applies today's omit list verbatim with `--omit`. The gate's own scope filter (AD-3) is what excludes tests.
  - The constant `MEASURED_SOURCES` lists the six roots and is recorded in the sidecar. A gated file outside it fails `not_measured` with a named fix, never 0%-and-silent.
- **The suite-wide threshold is computed unchanged, from the same data.** It is a second command, `coverage report --include='scripts/oversight/*,scripts/automation/lib/*,scripts/framework/*' --fail-under=78`, which replaces `--cov-fail-under` on the pytest line.
- **S1 equivalence obligation (REQ-8).** Before the switch, `technical-design` shows on `main` that the old and new commands report the **same total to two decimal places** over the same file set. The evidence must show the same file count as well as the same total [amended 2026-11-10]. If they differ, S1 stops and escalates to me. `fail_under` is never adjusted to absorb the difference.
- **Artifacts.** The job uploads `.coverage` (contexts included) and a sidecar `coverage-meta.json` as the artifact `coverage-contexts`, with `retention-days: 7`. The sidecar holds the head SHA, `HEAD^{tree}`, a clean-tree flag, the pinned tool versions and `COVERAGE_CORE`.
- **Measurement obligation (S1).** `technical-design` records the job's wall time on CI before and after enabling contexts, along with the data-file size. If the job exceeds **22 minutes** of its 30, S1 escalates to me before merging. Raising `timeout-minutes` is a reliability and cost decision, not a silent tweak.

**`new-code-measure` (new; not required).**
- `needs: tests`, `if: always()`. `timeout-minutes: 30`.
- It checks out the same commit as `tests` with `fetch-depth: 0`, builds the venv the same way as `tests`, downloads `coverage-contexts`, and runs `measure`.
- **The gated commit is the `pull_request` merge commit, `github.sha` [amended 2026-11-10, AR-1].** Under `pull_request`, `actions/checkout`'s default ref, which the `tests` job uses (`tests.yml:57`), is the synthetic merge commit `refs/pull/<n>/merge` at `github.sha`. It is not `pull_request.head.sha`. The coverage data therefore describes the merge tree, and its line numbers are merge-tree line numbers. So all three jobs check out `github.sha`, and the gate measures that tree:
  - **gated SHA** = `github.sha`, which the sidecar records as `HEAD` in `tests`;
  - **diff base** = `<gated>^1` (the base-branch parent of the merge commit), so gated lines are exactly what the PR adds to the current base;
  - **guard:** `<gated>^2` must equal `github.event.pull_request.head.sha`, or exit 3 ("merge commit does not contain the PR head");
  - the record carries `gated_sha`, `pr_head_sha` and `base_sha` (= `<gated>^1`). S3 matches merged PRs on `pr_head_sha`.
  - Local `run` is unchanged: gated = `HEAD`, base = `merge-base(<base>, HEAD)`.
- **It fails closed with exit 3 in each of these cases:**
  - `needs.tests.result != 'success'`, because the suite must be green;
  - the artifact is missing;
  - the sidecar's head differs from `github.sha`, or the AR-1 parent guard fails [amended 2026-11-10];
  - the sidecar's `tool_versions` differ from the measure job's installed versions for any pinned tool (AD-4 step 1) [amended 2026-11-10].
- It uploads `new-code-records` (the REQ-24 records, with measured numbers and no outcome) with `retention-days: 90`.
- **Why a separate job and not more steps in `tests`.** The suite is about 15 minutes and contexts add overhead. Mutation adds up to a 25-minute budget (AD-11). Both cannot fit in one 30-minute job without either cutting the mutation budget to about 10 minutes or raising the existing required job's timeout. A separate job gets its own timeout, leaves `tests`' timeout and meaning alone, and reuses the one suite run through the artifact, as R2 requires. Re-running the suite in the measure job instead was rejected: it would double the cost and the result would no longer be the normal run.

**`new-code-gate` (new; the one required context).**
- `needs: new-code-measure`, `if: always()`. `timeout-minutes: 5`.
- Permissions are `contents: read` only in S2 [amended 2026-11-10]. `pull-requests: read`, and `issues: read` if ADR-2101's fetcher needs issue-side acts, are added in S5, when something first reads PR data.
- **Code source: the same commit as the other two jobs, not the trusted base [amended 2026-11-10, TD Q2].** Under a `pull_request` trigger the workflow YAML is itself PR-controlled. A base checkout of the verdict code therefore defends nothing: the PR can edit the step. A genuinely trusted verdict would need `pull_request_target` or `workflow_run` consuming PR-produced artifacts. That is the artifact-poisoning shape AD-9 rejects. It would also break REQ-35 for the introducing PR and for `release/v*` bases cut before the gate. The control on gate weakening is CODEOWNER human review of `scripts/framework/**` and `.github/workflows/**`, which are protected surfaces. This is residual R-6.
- It downloads `new-code-records` and runs `verdict`. It fails closed with exit 3 if the measure job did not succeed or the artifact is missing.
- It writes the REQ-25 per-file table to `$GITHUB_STEP_SUMMARY`. It uploads `new-code-verdict` (records plus outcomes plus ruling references) with `retention-days: 90`. AD-9 ingests that artifact.
- **Why this job is the required context.** It is the only job whose result is the final judgement. If a ruling is posted later, a human re-runs **only this job**, which takes seconds. The measure job is not re-run. S2 verifies on GitHub that re-running a single job can download artifacts from an earlier attempt of the same run. If it cannot, S2 escalates to me. The fallback is a full re-run, which is slower but correct.
- **Skipped-means-success trap.** A job skipped because its `needs` failed reports as skipped, and branch protection treats a skipped required check as satisfied. `if: always()` on both new jobs, plus their explicit `needs.*.result` checks, closes that trap. A static test asserts both `if: always()` lines exist (extending AC-30).
- **Context registration.** `new-code-gate` is added to `hos_required_contexts.txt` with a provenance comment (REQ-2, AC-31). The concurrency group stays per-PR with `cancel-in-progress: true`, inherited from the workflow.

### AD-3 — Gated lines: changed lines map to the statement that contains them. Pragmas on gated lines are ignored. (BINDING; REQ-5 to REQ-7, §3 definitions; AF-2.)

- **The diff.** `git -c diff.algorithm=myers -c core.quotePath=true diff --no-ext-diff --no-textconv --no-color -M --unified=0 <diff base> <gated>` is parsed for gated-side added and modified lines. In CI, `<gated>` is `github.sha` and `<diff base>` is `<gated>^1`. Locally, `<gated>` is `HEAD` and `<diff base>` is `merge-base(<base>, HEAD)` (AR-1) [amended 2026-11-10]. The pinned options follow ADR-2101 AD-5, so a hostile `.gitconfig` cannot change the result.
  - A pure rename (`R100`) is not new and has no changed lines.
  - A rename with edits is a changed file, and only its edited lines count.
  - An added file (`A`) is new.
- **Statement mapping.** A changed line is a gated line if it falls anywhere inside the line range of an executable statement. That includes continuation lines of a multi-line statement and lines inside a decorator. The gated unit is the statement's **first line**, as coverage reports it. Use coverage.py's own `PythonParser` (`first_line()` and the multiline map) from the pinned version. Do not write a second parser.
  - A changed line that is only a comment, blank or a docstring is not gated.
  - A changed `def` or `class` header line is gated (coverage counts it as a statement).
- **Pragmas (H2) [ruled 2026-11-10].** Statements are computed with **no exclusion regexes**, so `# pragma: no cover` and the `exclude_lines` config do not remove gated statements from the denominator. The coverage data still records excluded lines as executed, because exclusion is applied at report time. Unchanged lines in a changed file are not gated, so pre-existing pragmas there have no effect, as the spec requires.
- **Coverage of a gated file.** Executed gated statements divided by gated statements, read from the `coverage-contexts` data. "Executed" means the line appears under any context, the empty collection context included. That is line semantics. Branch arcs are not gated, because the spec target is line coverage.
- **Paths.** Coverage data stores absolute runner paths. The gate maps them to repo-relative paths by stripping the checkout root recorded in the sidecar. A gated file the data does not know about at all is 0% covered. That is not an error, because the file was simply never imported.
- **Scope filter (§3).** `tests/**`, `**/conftest.py`, `mutants/**` and venv directories are excluded. `[tool.coverage.run] source` and `[tool.mutmut] source_paths` play no part in scope. Neither does `.coveragerc`.

### AD-4 — Mutant-to-line mapping is computed in-process, before the run, with pinned mutmut's own mutation code. Only gated mutants run. A cross-check after the run fails closed on drift. (BINDING; OQ-A3, REQ-9 to REQ-12; VF-4, AF-1, AF-5.)

1. **Version guard [amended 2026-11-10, ADR-A7].** `importlib.metadata.version` must equal the pin, or exit 3, for each of `mutmut` (3.8.1), `coverage`, `pytest-cov`, **`libcst`** and **`pytest`**. libcst performs the CST mutation and rendering, so a floating libcst can change the mutant set. pytest produces the node IDs that the coverage contexts and the mutmut selection must agree on. S2 pins all five with `==` in `requirements.txt`, and a static test asserts the pins equal the gate's constants. The `tests` and `new-code-measure` jobs build their venvs independently, minutes apart, so `measure` also asserts that the sidecar's `tool_versions` (written in `tests`) equal its own installed versions for all five tools, and that the Python major.minor matches. A mismatch is exit 3.
2. **Enumerate [amended 2026-11-10, A9].** Call `mutmut.mutation.file_mutation.mutate_file_contents(path, source, covered_lines=None, coverage_excluded_lines=None)` on the gated file's stripped **workspace** source (step 3), and take its `mutant_names`. A raw count from `create_mutations` is wrong: `combine_mutations_to_source` drops mutations outside top-level functions and methods of top-level classes. mutmut's `config()` is a process-global cache (`configuration.py:304-313`), so enumeration and mapping (step 4) for each file run in a **subprocess of the pinned venv Python with cwd = that file's workspace**, which returns JSON. They never run in the `measure` process, where a cached config from an earlier workspace would silently apply.
3. **Pragmas (H2) [ruled 2026-11-10; mechanism amended 2026-11-10, ADR-A8].** No pragma or "documented equivalent" claim added in the PR reduces the counts. Before enumeration, the gate removes **every** `# pragma: no mutate…` comment token (bare, `block`, `start`, `end`, `class`, `function`) from the workspace copy of the gated file. It does this with `tokenize`, never with a regex over source text, and leaves every line otherwise byte-identical. Removing a comment does not change semantics. Gated-lines-only stripping was rejected for two reasons. A pre-existing `block` or `start`/`end` region on an unchanged line would otherwise shield new gated lines (`pragma_handling.py`). And a partial strip can unbalance a `start`/`end` pair into a `PragmaParseError`. Stripping on ungated lines only adds ungated mutants, which are never run or counted, so the counted result is exactly the ruling's. `coverage_excluded_lines` is `None` and `do_not_mutate_patterns` is `[]`.
4. **Map.** For each mutant, build the mutated module in memory (original module with the mutated node substituted, the same CST operation as `apply_mutant`). Diff it against the original with `difflib`, collect the changed original-side lines, and normalise them to statement first lines (AD-3). A mutant is **gated** if that set intersects the gated statements. For a new file, every mutant is gated.
5. **Run.** `mutmut run <gated keys…>` runs in the workspace (AD-5) as an argv list, never through a shell. If there are zero gated keys, no run happens. The record then says `mutation_ran: true, total: 0` only if enumeration completed without error (REQ-12, AC-27).
6. **Cross-check (drift guard).** After the run, read the exit codes mutmut recorded for the file through `mutmut.mutation.data.SourceFileMutationData`. The set of keys mutmut generated for the file must **equal** the enumerated set, and every gated key must have a recorded result. Any mismatch is exit 3, "mutant enumeration drift". The guard is what makes relying on mutmut internals safe: any behaviour change shows up as a closed failure, never as a silently wrong score.
7. **Classify.** Use mutmut's own exit-code-to-status table. `killed` counts as killed. `survived`, `no tests`, `suspicious`, `skipped`, `not checked` and segfault do not. `timeout` counts as **killed** (H3) [ruled 2026-11-10].
8. **Visibility for AF-5.** The record carries `unmutatable_gated_lines`. These are gated statements in code that mutmut does not mutate (decorated functions, enums). They pass on coverage only if they contain no decision logic. Decision logic in them fails the file with "move the logic into an undecorated helper so it can be mutated" (NQ-2) [ruled 2026-11-10].

**Rejected alternatives.**
- Running all of a file's mutants and filtering by `mutmut show` diffs afterwards gives the same result. But it spends budget on ungated legacy mutants in changed files.
- `mutate_only_covered_lines` only accepts lines covered by coverage, not an arbitrary line set.
- Editing `[tool.mutmut]` per PR is forbidden by OQ-A3 itself.

### AD-5 — Each gated file gets a fresh workspace exported with `git archive` (never `.claude/`) and a generated, round-trip-verified mutmut config. The repo's `mutants/` is never used. There is no cache in v1. (BINDING; OQ-A6, REQ-11, REQ-17, REQ-19, REQ-20, REQ-28; R5, R6.)

- **Workspace.** For each gated file, in sorted path order, `mktemp -d` under `$TMPDIR` (CLAUDE.md temp rules; `$RUNNER_TEMP` in CI). Fill it with `git archive --format=tar <gated> -- . ':(exclude,glob)**/.claude/**'`, unpacked with `tarfile` and `filter="data"`, not a shell pipe [amended 2026-11-10, ADR-A1]. That gives exactly the committed gated tree, with no `.venv`, no `mutants/`, no `.claude/` at any depth and no untracked files.
  - **Why the glob.** `prompts/.claude/agents/overseer.v1..v4.md` is tracked, and the original `':(exclude).claude'` removes only the top-level directory. Verified at `8113f8ba0`: it leaves 6 `prompts/.claude` entries in the archive, so the assertion below would exit 3 on every run. The glob form leaves 0 at any depth, top level included. No test reads `prompts/.claude/`.
  - **Assertions after extraction.** No path component named `.claude` exists anywhere in the workspace (AC-19). `mutants/` is absent. If a PR ever tracks `mutants/`, the assertion fails with exit 3.
  - The workspace is deleted when the file's run ends, pass or fail, unless `--keep-workspace` is passed locally for debugging. CI never passes it.
- **Generated config.** The workspace's `pyproject.toml` is the head's file with the `[tool.mutmut]` table cut out. A new `[tool.mutmut]` table is appended. The gate then re-parses the result with `tomllib` and asserts two things. Every other table must be **equal** to the head's, so pytest and coverage config are intact. The mutmut table must equal the intended dict. Either mismatch is exit 3. The table holds:
  - `source_paths`: the sorted top-level tracked directories that contain `.py` files outside `tests/` (today `bin/`, `bootstrap/` and `scripts/`; `bin/lib/usage_pause.py` is tracked) [amended 2026-11-10], plus the gated file itself if it is at the top level. Directories are safe here because the archive holds no `.venv` (the reason the committed config lists files one by one, `pyproject.toml:46-50`, does not apply).
  - `only_mutate`: `[<gated file>]`.
  - `also_copy` [amended 2026-11-10, ADR-A2]: every other top-level tracked **directory** as a directory entry, plus every top-level tracked **regular file** as a file entry, except `pyproject.toml` and `setup.cfg` (mutmut copies those itself, and `pyproject.toml` must stay the generated one).
    - **Nested file entries stay forbidden (R6).** In mutmut 3.8.1, `copy_also_copy_files` (`utils/file_utils.py:66-77`) does `shutil.copy2(path, mutants/path)` with no parent `mkdir`. A top-level file lands in `mutants/`, which `_run` has already created (`__main__.py:954`). A nested file fails unless its parent happens to exist.
    - `.claude/` is never included, and it is not in the workspace to copy.
  - `pytest_add_cli_args` [amended 2026-11-10, ADR-A6]: `["--no-header", "-p", "no:cacheprovider", "-p", "_ncg_tripwire", "-m", "not repo_copy"]`. There is no `--reruns`: a flaky test is a `suspicious` mutant, which is not killed.
    - **Plugin placement.** The gate copies `new_code_gate_pytest_plugin.py` from the checkout to `<run tmp>/ncg-plugin/_ncg_tripwire.py`. That directory is a **sibling** of the workspace, never inside it. The gate prepends it to the mutmut subprocess's `PYTHONPATH`.
    - **Why.** Loaded from the workspace, the plugin is itself a gated file in the gate's own PR and in any later PR that edits it. mutmut would then mutate the tripwire that guards the run.
    - **Assertion.** The plugin logs its own resolved `__file__` at session start. If that path is inside the workspace, or the log line is absent, the result is exit 3.
    - The plugin's own tests load it canonically, so its mutants are still killable.
  - `pytest_add_cli_args_test_selection`: the file's selected node IDs (AD-6).
  - `use_git_change_detection = false`, since the workspace has no `.git`.
  - `mutate_only_covered_lines = false`.
  - Timeout settings at mutmut's defaults, written explicitly so the config fingerprint is stable.
  - TOML strings are emitted with an escaper that the round-trip check verifies. `setup.cfg` was rejected because `ConfigParser` interpolation breaks on `%` in parametrised node IDs.
- **One mutmut invocation per gated file.** This is what makes REQ-17 and AC-15 exact. A single run over the union of selections would let a test selected for file B kill a mutant in file A.
- **Staleness guarantee (REQ-19).** A fresh directory per run, plus the "`mutants/` absent" assertion, means mutmut's mtime reuse (VF-2) has nothing to reuse. The repo's own `mutants/` (from `run_tests.sh --mutation`) is never read or deleted by the gate. Not deleting it is deliberate: the gate never writes outside its workspace.
- **No cache (REQ-28 is permissive).** A sound cache key must cover everything the selected tests can observe. That includes the gated file, each selected test module, every `conftest.py` on their path, every helper and source module they import, the generated config, and the pinned tool versions. Honestly computed, that collapses to `HEAD^{tree}` plus versions, which only ever hits on a re-run of an identical head. AD-2's verdict-only re-run already covers that case for free. A cache would add a poisoning surface (a `pull_request` cache is writable by the PR) for no benefit. If measured budgets later need one, it needs a new ADR amendment, keyed on the full tree hash.

### AD-6 — Test selection: node IDs from per-test contexts, the name fallback only when that set is empty, `repo_copy` tests removed, and an empty result fails. (BINDING; REQ-13 to REQ-17; R2, R3. Soundness confirmed in §4.)

1. **Context selection.** For every gated statement, the gate takes `CoverageData.contexts_by_lineno(file)[line]` and strips the `|setup`, `|run` or `|teardown` phase suffix with `rpartition("|")` (node IDs can contain `|`). The empty context is dropped. The union across the file's gated statements is the selection, as sorted pytest node IDs. Node IDs are used, not files, because they are smaller and AC-13 needs per-test precision.
2. **Name fallback.** Only if step 1 is empty: every tracked `tests/**/test_<stem>.py`, as whole modules, recorded as `selection_method: name_fallback`.
3. **Repo-copy removal.** Any selected test carrying the `repo_copy` marker (AD-7) is removed and listed in `removed_repo_copy`. The set is computed by `pytest --collect-only -q -m repo_copy <selection>` in the workspace, which is deterministic, and the same `-m "not repo_copy"` filter is applied in the run.
4. **Empty after step 3.** The file fails as `no test exercises its gated lines` (REQ-16). The one exception is NQ-1 [ruled 2026-11-10]: a file with zero gated mutants and gated coverage of at least 80% passes without a selection, but only if its gated lines contain no decision logic (AST `If`/`For`/`While`/`Try`/`BoolOp`/`Compare`/`IfExp`, or a comprehension with an `if`). Otherwise it fails with "move logic into a function so it can be mutated". Every other empty selection fails.
5. **Clean-run failure.** mutmut first runs the selection unmutated. If a selected test fails in isolation (order dependence, or a missing non-copied input such as `.claude/`), mutmut errors. The file fails `selected_test_fails_in_isolation` (exit 1 from `verdict`) with the failing node IDs and the hint "this test fails when run alone in the mutation workspace". That message names what to fix. It is never a pass. If no selected node ID can be attributed, the result is exit 3 (AD-1, ADR-A4) [amended 2026-11-10].

### AD-7 — Repo-copying tests carry a `repo_copy` marker, and a runtime tripwire in the workspace catches unmarked ones. There is no hand list. (BINDING; OQ-A4, REQ-15; R3.)

- **The marker is authoritative for exclusion.** S2 registers `repo_copy` in `[tool.pytest.ini_options] markers` and turns on `--strict-markers` if it is not already set. S2 marks the existing repo-copying tests, for example `tests/automation/test_agent_invoke_wrapper.py`, found by the scan below.
- **A runtime tripwire is what makes the marker trustworthy.** `new_code_gate_pytest_plugin` is loaded only into the mutation run, by `-p _ncg_tripwire`, from outside the workspace (AD-5, ADR-A6) [amended 2026-11-10]. A tripwire event is an attributed per-file fail, `unmarked_repo_copy` (exit 1 from `verdict`, AD-1, ADR-A4) [amended 2026-11-10]. It wraps `shutil.copytree`, plus `subprocess` launches whose argv is `git clone`, `git worktree add` or `git archive`, so that any call whose source resolves to, or contains, the workspace root raises a named error. The error names the test node ID and tells the author to "mark it `@pytest.mark.repo_copy`". A test that copies the repo without the marker therefore fails the run, and the file fails `unmarked_repo_copy` with that message (verdict exit 1, ADR-A4) [amended 2026-11-10, round 3].
  - So dropping or forgetting the marker can never silently put a repo copy into a mutation run.
  - The only effect of removing a marker is a closed failure. That is why the marker itself, which lives in unprotected `tests/**`, does not need to be a protected surface. The tripwire does, and it is under `scripts/framework/**`.
- **Static guard (cheap, early).** A repo test (`tests/framework/test_repo_copy_marker_guard.py`) scans every test module's AST for `shutil.copytree`, `git clone`, `git worktree add` and `git archive` calls whose source argument is a repo-root name (`REPO_ROOT`, `repo_root`, `Path(__file__).parents[n]`, and `git rev-parse --show-toplevel` output). It fails if the module or the test is not marked. This is a heuristic and is allowed to miss. The tripwire is the backstop. **Who maintains it:** whoever adds a repo-copying test, prompted by the guard or the tripwire. There is no list for anyone to keep current.
- **Rejected:** a hand-maintained list, because it goes stale silently and R3 and the spec ask for deterministic identification. Detection-only exclusion was also rejected, because an over-broad static match would remove legitimate fixture-copying tests and empty selections, giving false fails.

### AD-8 — Shell: reuse `shell_logic_check.py` on base and head content. (BINDING on mechanism; REQ-21. Scope ruled 2026-11-10: every existing `shell_logic_check.py` exemption applies, the file-level `bootstrap/hos_bootstrap.sh` one included, and an edited line on which a counted construct opens counts as added logic (H4). Decision logic fails with "move decision logic into tested Python", and there is no shell harness (H1).)

- For each gated `.sh` file, run `shell_logic_check.py`'s counting function (imported, not shelled out to) on the base and head blobs. The file fails if either holds: a counted decision construct opens on a head-side added or modified line, or the head count is greater than the base count.
- No second shell parser.
- REQ-21's "move to tested Python" message is emitted, naming `scripts/automation/lib` as the recommended home.

### AD-9 — Records reach the trail of record through overseer ingest of the `new-code-verdict` artifact. The CI token stays read-only. (BINDING on the route; **gated by the §5 checkpoint** for the App permission. OQ-A1, REQ-24 to REQ-26; AF-6.)

- **In CI (S2).**
  - The verdict job writes the full records as JSON (REQ-24 fields, plus PR number, `gated_sha`, `pr_head_sha`, `base_sha` (AR-1) [amended 2026-11-10, round 3], gate version, the workflow run ID and attempt, and `records_sha256`).
  - It writes the human-readable table to the step summary (REQ-25).
  - It uploads `new-code-verdict` with `retention-days: 90`.
  - Nothing in CI writes to git.
  - The `PR_NUMBER` tag stays as the workflow already sets it.
- **Ingest (S3).** This is a new deterministic module, `scripts/automation/lib/new_code_gate_ingest.py`, called from the overseer's cron cycle in `bin/hos-cron`, not from agent prose. It runs in two places:
  - **On merge.** When the overseer merges a PR, it ingests that PR's verdict for the merged head.
  - **Sweep.** Every overseer cycle, it ingests every PR merged in the last 14 days that has no ingest record yet. This covers human-merged PRs, which the overseer never merges, and so meets "at least every merged PR".
  - **Unmerged PRs are best effort.** The overseer ingests when it evaluates them, but this is not required.
- **What ingest verifies before writing.** CI output is untrusted data, so ingest checks all of these:
  - The workflow run's `path` is `.github/workflows/tests.yml` in **this** repo, not a fork.
  - The run's `head_sha` equals the merged PR's head SHA.
  - The `new-code-gate` job concluded, and its conclusion matches the artifact's computed verdict.
  - The artifact is at most 5 MiB and parses against the record schema.
  - `records_sha256` matches.
  - All fields are strings, numbers or booleans with bounded lengths. No artifact value is ever used as a path or as shell input.
- **What ingest writes.** One `new-code-gate` event per (PR, head SHA), with the per-file records array, the run URL and the artifact digest, written through `audit_log.write_event`. The existing `_sync_audit_logs` pushes it to `origin/audit-log`. **Idempotency.** Before writing, ingest looks for an existing event with the same `(pr, head_sha, records_sha256)`, both locally and on the fetched `origin/audit-log`. `write_event` file names embed a timestamp, so they do not dedup on their own.
- **Failure handling.**
  - A missing or expired artifact, a verification failure or an API error writes a `new-code-gate-ingest-failed` event with the cause.
  - After 3 consecutive failures for the same PR, ingest escalates through `bootstrap/escalate_to_human.sh`.
  - Ingest never blocks a merge (it is recording, not gating) and never retries forever. The sweep window bounds it.
- **Permission (product-boundary item).** Listing a run's artifacts and downloading them needs **`actions: read`** on the overseer App. S3 checks whether the App already has it. If not, granting it is a human App-settings change that widens a trust boundary, so it goes through §5. The same applies if the human prefers the worker App instead.
- **Why not a `workflow_run` job with `contents: write` pushing to `audit-log`.** That is the classic artifact-poisoning pattern: a privileged workflow consuming bytes produced by PR-controlled code. It would also give CI a new write path into the trail. The overseer already pushes the trail every cycle, so ingest adds a reader, not a writer.
- **Generalisation, noted and not done here.** The same ingest shape fits the `tests.yml` retry-rescue gap (`tests.yml:79-87`). The schema is versioned (`schema: new-code-gate/1`) so a later `ci-artifact-ingest` can absorb both. That is a follow-up issue, not this ADR.

### AD-10 — Exceptions: no gate-local ruling parser. The gate consumes ADR-2101's single verifier through one seam, and until that verifier exists the gate has no exception path. (BINDING; OQ-A7, REQ-22, REQ-23; AF-7.)

- **One seam.** `new_code_gate_logic.decide(records, rulings, thresholds)` is pure. `rulings` comes from one function, `fetch_rulings(pr, head, paths)`, the only place the gate touches exception input.
- **After S5.** `fetch_rulings` runs `scripts/framework/human_authorization.py verify --consumer new-code-gate --require NCG:<path>[,…] --base <base sha> --head <head sha> --pr <n> --json` as a subprocess. That gives the gate ADR-2101's rules in full:
  - the CODEOWNERS humans set is read from the **default branch**, never the PR head;
  - bots are refused by every layer (`is_bot_reviewer` and `BOT_ACCOUNTS` ∪ the default-branch baseline);
  - edited comments are refused;
  - fetching is bounded and fails closed;
  - every verdict is audited.
- **Item kind.** `NCG:<path>` (one per failing file) is added to ADR-2101's closed item set. That is an amendment to ADR-2101 AD-8 and lands with S5. The ruling's reason is free text after the `---` separator (ADR-2101 AD-1). The gate records the act URL, author and reason (REQ-23).
- **Exit handling.** Any non-zero exit from the verifier means no ruling, and the file's outcome stays `fail`. A verifier exit 3 is reported as REQ-4's "exception verification lookup failed", with the verifier's `error` quoted.
- **Until S5 lands (that is, until #2101 S1, or #2219 if it supersedes it).** `fetch_rulings` returns empty, and the record says `exception_path: unavailable (ADR-2101 verifier not present)`. The gate does **not** implement "the evaluator's CODEOWNER-comment rule", because that rule is agent prose (AF-7). This is stricter than the spec's interim wording. Until S5, the human's override is an admin merge (`enforce_admins: false`, REQUIREMENTS-1803 VF-9), which GitHub records in its own audit trail. That consequence is in §5.
- **Switch-over to #2219.** If #2219 produces a different verifier, the switch is a one-line change of the subprocess target, inside `fetch_rulings`, made in #2219's PR. The gate never accepts two ruling forms at once.
- **Workflow permissions** for `new-code-gate` are `contents: read` in S2; **from S5** [amended 2026-11-10, round 3] they add `pull-requests: read`, plus `issues: read` only if the verifier reads issue-side acts (S5 decides). No secrets are used.
- **Binding [ruled 2026-11-10, H5].** A ruling is bound to the **content** of the named file: the git blob of `<path>` at the time of the ruling, not the head SHA. It is void as soon as that file's content changes, which aligns with #2219 and #2101. The blob is taken from the gated merge tree (§2b, AR-1) [amended 2026-11-10]. A ruling covers only that file's coverage and mutant-score **thresholds**. It never covers path-load, shell, timeout or internal-error failures. Until S5 there is no in-gate exception path, and a human admin merge is the only override.
- **AC-21 enforcement.** `decide` takes no environment, labels, config or pragma input. A static test asserts that `new_code_gate_logic` does not read `os.environ`. Exceptions are never computed in `measure`.

### AD-11 — Wall-clock budget: 25 minutes for `measure` inside a 30-minute job. A deadline is enforced per subprocess by killing the process group. A timeout is only ever a fail. (BINDING; OQ-A8, REQ-29.)

- **The budget is not configurable from PR content.** `measure` gets a hard deadline of **25 minutes** from its own start. That leaves about 5 minutes of the 30-minute job for checkout, venv, artifact transfer and upload. The budget constant lives in `new_code_gate_logic` and is not read from env or config (AC-21).
- **How the deadline is enforced.**
  - Files are processed in sorted path order.
  - Each child process (mutmut, the collect-only call) is started with `start_new_session=True`. It is given the **remaining** budget as its timeout. On expiry the gate sends `killpg(SIGTERM)`, waits 10 seconds, then sends `killpg(SIGKILL)`.
  - The file in progress and every file not yet started are recorded as `mutation_ran: false, reason: timeout`, and the message suggests splitting the PR.
  - The records are still uploaded, so the verdict and the table show what finished.
- **Cheap work runs first.** Coverage, selection and shell checks, which need no mutmut, run for **every** file before any mutation starts. So a mutation timeout never hides a coverage failure.
- **If the job timeout itself is hit**, the job is cancelled, the records artifact is missing, and `new-code-gate` fails closed (AD-2).
- **Per-mutant timeouts** are mutmut's own (`timeout_multiplier × baseline + constant`, at defaults). They count as **killed** (H3) [ruled 2026-11-10]. A whole-gate budget or job timeout still fails closed.
- **Rough capacity, for design only.** The measured `claim*` run was 225 mutants in 55.7 seconds, about 0.25 seconds per mutant including setup. With 4 vCPUs that suggests a few thousand gated mutants per PR fit in the budget, when the selected tests are fast. A PR with slow selected tests fails on budget and must be split. That is the intended pressure, consistent with `docs/PR-SIZE-POLICY.md`. S2 must record real CI timings for its own files.
- **Determinism (AC-29).** A timeout depends on time, so a PR near the boundary can flip between fail and pass across runs. The invariant that holds is the one REQ-29 needs: **a pass is never produced by timing**, because every timeout path ends in fail.

### AD-12 — Path-loaded modules: a static pre-check, a runtime recorder and translation of mutmut's error, all producing one named message. (BINDING; OQ-A5, REQ-18; R4.)

1. **Static pre-check (before mutation, to save budget).** For each selected test module and every `conftest.py` on its path, the gate parses the AST for calls to:
   - `importlib.util.spec_from_file_location`;
   - `importlib.machinery.SourceFileLoader` and `SourcelessFileLoader`;
   - `runpy.run_path`;
   - `imp.load_source`.

   A call is a finding when its path argument resolves statically to the gated file, or contains the gated file's path or stem as a string literal. The finding names the test file, the module path and the fix "convert to a canonical `scripts....` import in this PR". The file then fails without running mutmut.
2. **Runtime recorder (authoritative).** The plugin (AD-7) wraps the same loaders. Any call that loads a path resolving to the gated file under a module name other than its canonical dotted name records the calling test's node ID. The recorder fails the clean run with the same named message. This catches the dynamic paths the static scan cannot resolve.
   - **Bare `sys.path` imports are the same defect, and the larger population [amended 2026-11-10, ADR-A5].** `tests/conftest.py` inserts `scripts/oversight` and `scripts/oversight/validators` into `sys.path`. As a result, 31 test files import 26 production modules by bare name (architect re-count at `8113f8ba0` matches TD F-5).
   - **Why the recorder must catch them.** mutmut's trampoline records `orig.__module__`, so hits on a bare-imported copy never match the path-derived key. A bare-loaded copy also never activates the mutant under test, because the prefix differs. mutmut stops with its message only when **no** recorded key matches (`__main__.py:820-865`). A mix of canonical and bare importers therefore silently undercounts kills with no message. That fails in the safe direction, but without the REQ-18 fix named.
   - **How.** The recorder also installs a **passive** `sys.meta_path` observer, plus a `sys.modules` alias scan at session start, after each module's collection and after each test. The scan flags any module whose resolved `__file__` is the workspace copy of the gated file, under a non-canonical name.
   - **Passive means passive.** The observer always returns `None` and never alters resolution. A static test asserts it.
   - The static pre-check (step 1) also flags `import <stem>` / `from <stem> import` when the gated file's directory is one of the conftest-inserted directories. That list is a logic constant, and a test pins it to `conftest.py`.
3. **mutmut's error.** If mutmut still exits with "tests recorded trampoline hits but none match any mutant key", the gate translates it. Matching uses the exact string of the pinned version, so it is covered by the AD-4 version guard. The translation names the tests from steps 1 and 2. If neither step found anything, it names the gated file and lists every selected test module as a candidate. It is always the REQ-18 message and fail, never raw output and never a pass (AC-17).

### 2b. Round-1 amendments from TD-2304 review [amended 2026-11-10]

These are technical corrections. They follow from verification against mutmut 3.8.1, coverage 7.17.2 and `tests.yml` at `8113f8ba0`. No ruling is changed.

| # | Decision | Where | Evidence |
|---|---|---|---|
| ADR-A1 | **Accepted.** `':(exclude,glob)**/.claude/**'` | AD-5 | Archive at `8113f8ba0`: the old exclude leaves 6 `prompts/.claude` entries, the glob leaves 0 at any depth |
| ADR-A2 | **Accepted.** Top-level file entries go in `also_copy`; nested file entries stay forbidden | AD-5 | `file_utils.py:66-77`, `__main__.py:954` |
| ADR-A3 | **Accepted.** Explicit roots replace `--cov=.`; run-time omit narrowed; report-time omit is today's, verbatim | AD-2 | `coverage/files.py:553-581` prunes non-package subdirectories; `scripts/oversight/` and `scripts/framework/` have no `__init__.py` |
| ADR-A4 | **Accepted, with an attribution constraint.** An attributed test-caused failure is a per-file fail (exit 1). An unattributed one is exit 3 | AD-1, AD-6, AD-7, §3 | — |
| ADR-A5 | **Accepted.** Passive meta-path observer and `sys.modules` alias scan; the static scan covers bare imports | AD-12 | `__main__.py:820-865` (stops only when no key matches); re-count: 26 modules, 31 test files |
| ADR-A6 | **Accepted.** Plugin loaded as `_ncg_tripwire` from a sibling directory, with a location assertion | AD-5, AD-7 | — |
| ADR-A7 | **Accepted and extended.** pytest pinned as well, plus a sidecar-vs-measure version equality check | AD-4 step 1 | Two jobs build their venvs independently |
| ADR-A8 | **Accepted.** Strip every `no mutate` form in the gated file | AD-4 step 3 | `pragma_handling.py:98-210` (`block`, `start`/`end`, parse errors on imbalance) |
| A9 | **New (from TD F-3).** Enumerate with `mutate_file_contents(...).mutant_names`, in a per-file subprocess | AD-4 step 2 | `file_mutation.py:105-147, 380-462`; `configuration.py:304-313` (global config cache) |
| AR-1 | **New, blocking.** Gate the `pull_request` merge commit `github.sha` with diff base `^1`, and guard that `^2` is the PR head | AD-2, AD-3, §3 F-2 | `tests.yml:57` uses the default checkout ref; under `pull_request` that is `refs/pull/<n>/merge`, so the sidecar head could never equal `pull_request.head.sha` |
| Q2 | **Decided: no trusted base.** The verdict runs from the same commit as the other two jobs | AD-2, R-6 | `require-human-approval.yml` is safe only because it uses `pull_request_target` and runs no PR code |

**H5 binding under AR-1.** S2 records two blobs per file: `blob_sha`, the blob in the **gated** (merge) tree, and `pr_head_blob_sha`. S5 binds a ruling to `blob_sha`, the content that was actually gated. A change to the file from either the PR or the base therefore voids the ruling. That is the strict reading of H5. When the base did not touch the file, the two blobs are equal.

**REQ-35 self-gating plan: sound, under these conditions (binding on TD and coder).**
1. **Production `.py` set.** The introducing PR changes only the three new gate modules and `shell_logic_check.py`. Any other production `.py` file is a design change that comes back through `technical-design`.
2. **`shell_logic_check.py` diff evidence.** Today's loop body (`shell_logic_check.py:94-170`) stays byte-identical and in place, so no loop line is gated. The PR body attaches the `--unified=0` hunk list for the file.
   - `decision_lines` returns the counted line numbers sorted, **duplicates preserved**, so `_scan_file`'s count is unchanged.
   - `_scan_file` returns `(len(d), min(d) if d else None)`.
   - The TD's `min(d) or None` is wrong: `min([])` raises.
3. **No other non-canonical importer.** `tests/oversight/test_shell_logic_check.py:13` is the only non-canonical importer of `shell_logic_check` (architect grep: no path loader, no production importer), and it is converted in the same PR.
4. **No in-process gate code in the e2e module.** `tests/framework/test_new_code_gate_e2e.py` must not import any `scripts.framework.new_code_gate*` module in-process. A static test asserts this.
   - It is what keeps the e2e tests out of every context selection, so real mutmut is never nested inside a per-mutant run.
   - "Marked `slow`" alone does not guarantee that.
5. **Stdlib-only imports at module level.** `new_code_gate.py` and `new_code_gate_logic.py` import only the stdlib at module level, and a static test asserts it. `verdict` runs on the runner's system Python with no venv. Any coverage, mutmut or libcst use is a lazy import inside the measure path, or inside the per-file subprocess (A9).
6. **Self-budget evidence before the PR opens.** Run `run` locally on the final branch head over every gated file. Record mutants and seconds per file. If the projected 4-vCPU CI time (local seconds × local cores ÷ 4) exceeds 20 minutes, return to the architect. The budget is not raised, and the gate's files are not exempted.
7. **Green on its own final head (AC-34).** The PR's own `new-code-gate` must pass on its final head, with no exemption.

**First-touch population.** The figure the PR states must be honest about its method.
- **Lower bound.** The exact figure, from an AST survey, is **26 modules** (bare `sys.path` imports). The architect's independent re-count matches.
- **Path-load count.** It is heuristic. The TD's own survey must compute it; "per the brief" is not an acceptable source. The architect's looser literal-match heuristic gives 39 path-loaded modules and a union of **57**, so the TD's "at most 54" is not a ceiling.
- **Statement for the PR.** "At least 26 and an estimated 40 to 57 of the 95 tracked production `.py` files (about half)". The module list goes in a TD appendix, to serve as #2305's work list.
- **Other first-touch classes.** The statement must also say that other first-touch failure classes are additional and unquantified:
  - modules whose tests exercise them only through a subprocess (AF-4);
  - selected tests that need the real `.git` or `.claude/`;
  - slow selections that exhaust the budget.

**Affected sign-offs.** None. No design, code or sign-off was built on the superseded text. These amendments land before TD approval.

### 2c. Round-3 rulings from TD-2304 review [amended 2026-11-10, round 3]

Technical corrections from verification against the installed mutmut 3.8.1 and pytest 9.2.0. No ruling changes.

| # | Decision | Evidence |
|---|---|---|
| R3-A | **Accepted:** `_enumerate` is a hidden phase of `new_code_gate.py`, run as `<venv python> -P -m scripts.framework.new_code_gate _enumerate` with cwd = workspace and `PYTHONPATH=<checkout>`. Added: the child reports its own resolved `__file__`, and `measure` requires it to be under the checkout and not under the workspace (exit 3 otherwise) | `configuration.py:304-313` |
| R3-B | **Extended:** the mutmut-side read-back (the `.meta` exit codes and `status_by_exit_code`) also runs in a hidden per-file subprocess (`_collect`), never in `measure`. `mutmut.stats` imports `mutmut.configuration.config` at module level | `stats.py:10-13` |
| R3-C | **Corrected:** a selected test failing in isolation first surfaces in mutmut's **stats** run (`failed to collect stats. runner returned <n>`), before the clean run. Attribution applies to both messages. mutmut's "could not find any test case for any mutant" stop records every gated mutant as `no tests` (killed 0), exactly as a normal run would | `__main__.py:319-357, 658-700, 975-995` |
| R3-D | **Accepted, with explicit `-rfE`:** attribution parses pytest's short-summary section. The generated args pass `-rfE` explicitly instead of relying on the default. pytest's `short_test_summary` is gated only by `--no-summary` and the report chars, not by verbosity, so mutmut's `-q` plus `addopts -q` does not suppress it | `_pytest/terminal.py:79, 1031-1050, 1320` |
| R3-E | **Accepted:** an `observer_error` event comes before every attribution rule and gives exit 3 | — |
| R3-F | **Accepted:** `also_copy` also excludes `setup.cfg`, and is computed from the extracted workspace so it never lists `.claude/` | `file_utils.py:66-77` |
| R3-G | **Decided:** the repo-copy collect-only runs in the checkout (the same merge tree), not the workspace. That supersedes AD-6 step 3's "in the workspace". It runs without the tripwire and with `-o addopts=`; pytest exit 5 means an empty set | the workspace does not exist yet at selection time |
| R3-H | **New:** the tripwire plugin reads `NCG_*` once into module state and removes those variables from `os.environ`, so neither the tests nor a canonically loaded copy of the plugin can activate from inherited env | the plugin's own tests load it canonically inside a mutation run |

**Affected sign-offs.** None. These land before TD approval.

### 2d. Round-5 clarification [amended 2026-11-10, round 5]

| # | Decision | Evidence |
|---|---|---|
| R5-A | In AD-7 and AD-12, "the workspace root" and "the workspace copy of the gated file" are both **sets**. The roots are `<workspace>` and `<workspace>/mutants`. The copies are `<workspace>/mutants/<rel>` and `<workspace>/<rel>`. Inside a mutation run the tests see `mutants/` as the repository root, and `mutants/` lies inside the workspace. A check against `<workspace>` alone therefore misses every real repo copy and every real path load | `mutmut/utils/file_utils.py:50-92` (`copy_src_dir`, `setup_source_paths`); `runners/harness.py` (`--rootdir=.` under `change_cwd("mutants")`) |

**Affected sign-offs.** None. This lands at TD approval, before any code exists.

---

## 3. Failure modes

| # | Failure | Detection | Result |
|---|---|---|---|
| F-1 | `tests` job red or cancelled | `needs.tests.result` | `new-code-measure` exits 3. `new-code-gate` fails |
| F-2 | Coverage artifact missing, sidecar head ≠ `github.sha`, or `<gated>^2` ≠ PR head [amended 2026-11-10] | download step / sidecar check | exit 3, "coverage data missing/stale" |
| F-3 | mutmut, coverage, pytest-cov, libcst or pytest version ≠ pin, or ≠ the sidecar's versions [amended 2026-11-10] | AD-4 step 1 | exit 3 |
| F-4 | Mutant enumeration ≠ mutmut's generated set | AD-4 step 6 | exit 3, "enumeration drift" |
| F-5 | Generated config does not round-trip | AD-5 | exit 3 |
| F-6 | `.claude` or `mutants/` present in workspace | AD-5 | exit 3 |
| F-7 | Selected test fails in isolation | mutmut clean run | file `fail` with node IDs (verdict exit 1). Unattributed → exit 3 [amended 2026-11-10, ADR-A4] |
| F-8 | Unmarked repo-copying test | AD-7 tripwire | file `fail`, "mark it `repo_copy`" (verdict exit 1) [amended 2026-11-10, ADR-A4] |
| F-9 | Path-loaded gated module | AD-12 | file `fail`, REQ-18 message |
| F-10 | Budget exhausted | AD-11 | `reason: timeout`. Verdict fails |
| F-11 | Job timeout | job cancelled, no artifact | `new-code-gate` fails closed |
| F-12 | Ruling lookup error (after S5) | verifier exit 3 | file stays `fail`, cause named |
| F-13 | Verdict artifact expired before ingest | AD-9 | `new-code-gate-ingest-failed`, escalation after 3 |
| F-14 | Skipped required job read as success | `if: always()` + result checks | closed by construction |

**Residual risks (accepted and stated).**
- **R-1.** Subprocess-only test exercise counts for nothing (AF-4).
- **R-2.** Decorated-function and enum code is unmutatable, so it is checked by coverage, and decision logic in it fails (AF-5, NQ-2) [ruled 2026-11-10]. Module-level and class-level code is also unmutatable. Decision logic in it on gated lines fails too, except for the three TD-Q5 carve-outs (AD-13a). What remains coverage-only is the carved-out statements and module-level or class-level statements that hold no decision node [ruled 2026-11-11: Q5].
- **R-3.** A deletion-only change has no gated lines (§3 of the spec, by design).
- **R-4.** The gate is not a defence against tests written to tamper with measurement (AF-8).
- **R-5.** A PR near the budget can flip between fail and pass on timing. It never produces a timing-made pass (AD-11).
- **R-6 [amended 2026-11-10].** The gate's code and workflow run from the PR's own commit (AD-2), so a PR can weaken its own verdict. The control is CODEOWNER human review of the protected surfaces `scripts/framework/**` and `.github/workflows/**`, not the gate itself.

---

## 4. Test-selection rules: soundness check (as requested)

The rules are **sound for their purpose, with three qualifications.** None of the qualifications loosens a rule.

1. **Selection by gated-line execution loses no killing power.** mutmut 3 mutates only inside function and method bodies, and a mutation on line L changes behaviour only when L executes. So the tests that can kill a gated mutant are a subset of the tests that executed a gated line, and that is exactly the context selection. mutmut then narrows further, per mutant, to the tests that hit that function's trampoline. **Sound.**
2. **Name match as fallback only, not as a union.** Sound and correct. A union would add tests that never execute the gated code: they cost budget and can kill nothing. As AF-9 notes, the fallback almost never changes an outcome. It matters only for import-time lines.
3. **Empty selection fails.** Sound against its target, the "no tests → N/A → pass" path. **Qualification (AF-3):** it falsely fails import-time-only files that have zero mutants, and no test can repair them. That is NQ-1, now ruled (AD-13a): the carve-out applies only when the gated lines contain no decision logic.
4. **Repo-copying tests never in a mutation run.** Sound. Inside the workspace a repo copy copies `mutants/` with its trampolines, which is slow and can confuse the stats. AD-7 makes the rule enforceable rather than a convention.
5. **Never the whole suite per mutant.** Sound, and it follows from 1. One mutmut run per file (AD-5) makes it exact.
6. **`COVERAGE_CORE=ctrace` with `--cov-context=test`.** Correct, and the pin is needed. **Qualification (AF-4):** contexts are in-process only, so subprocess-exercised code is neither selected nor credited.
7. **Path-loaded modules fail closed with no exemption list.** Sound. A path-loaded module under an ad-hoc name means the test exercises a copy that mutmut's trampoline keys cannot see, so any kill count would be fiction. **Qualification:** the same AST scan is heuristic. That is why AD-12 makes the runtime recorder authoritative.

One more point: the spec's §3 statement-line definition would have let continuation-line edits escape the gate (AF-2). That is a definitions defect, not a selection defect, and AD-3 corrects it.

---

## 5. Product-boundary checkpoint (must clear before AD-9 and the S2 required-context flip bind)

These decisions carry consequences outside architecture. They go to the **human**, with pm-agent informed of the user-visible items.

1. **Cost.** Each PR adds a second CI job of up to 30 runner-minutes and a 5-minute verdict job. Each PR also gains the context-recording overhead on `tests`, which S1 measures.
2. **User-visible behaviour.**
   - PRs whose new or changed code is tested only through subprocesses will fail until the tests call `main(argv)` in-process (AF-4).
   - New `__init__.py` or constants-only files pass under NQ-1 when they contain no decision logic (AF-3) [ruled 2026-11-10].
   - Large PRs fail on budget and must be split.
3. **Trust boundary.** The overseer App needs `actions: read` for ingest (AD-9). This is a GitHub App permission change, and only the human can make it.
4. **Operational obligation.** The overseer cycle gains an ingest step and a 14-day sweep. A failed ingest escalates to the human.
5. **Exceptions.** Until ADR-2101's verifier lands (S5), there is **no** in-gate exception path. The human's only override is an admin merge (AD-10).

---

## 6. Human questions

**OQ-H1 to OQ-H5** come from the spec. **NQ-1 to NQ-3** are new questions raised by this ADR. AD-13 below is history. The rulings in AD-13a govern, and NQ-3 is still open.

### AD-13 — Provisional strictest defaults. These are not decisions. Each one changes only a named constant or branch.

| Q | Provisional default | Where it is applied | My recommendation for the ruling |
|---|---|---|---|
| OQ-H1 shell path | Shell decision logic fails. Move it to Python | AD-8 | Python (concur with pm-agent) |
| OQ-H2 pragmas and equivalent mutants | Pragmas on gated lines are ignored for both coverage and mutation. The denominator is every gated mutant, and the 25% slack absorbs equivalent mutants | AD-3, AD-4 step 3 | Keep strict. A verified ruling, after S5, is the only exclusion |
| OQ-H3 per-mutant timeout | **Not killed** | AD-4 step 7 | Count it as **killed** (mutmut's convention). A mutant that makes the tests hang has been detected. The strict default risks failures caused by CI slowness |
| OQ-H4 shell scope | **Editing** an existing decision line counts as adding logic. The guard-clause and flag-parse exemptions apply, because AC-8 pins them. The **file-level `hos_bootstrap.sh` exemption does not apply** | AD-8 | Keep the edit rule. Decide the file-level exemption explicitly |
| OQ-H5 exception scope | Rulings apply **only** to the coverage and mutant-score thresholds. They do not apply to path-load, shell, timeout or internal-error failures, each of which has a mechanical fix. `contract/gate-suspension.md` does **not** apply to this gate. Binding is **`head:<sha>`** (ADR-2101 AD-5's stricter alternative) until ADR-2101 ESC-3 is ruled, after which the gate inherits it | AD-10, `decide` | Thresholds only. Inherit ADR-2101's binding whatever it is ruled to be |
| NQ-1 empty selection on zero-mutant files (AF-3) | Fail (R2 literal) | AD-6 step 4 | Amend R2: a file with **zero gated mutants and gated coverage of at least 80%** needs no selection, recorded as `selection_method: not_required_zero_mutants` |
| NQ-2 unmutatable gated code (AF-5) | Informational only (`unmutatable_gated_lines`) | AD-4 step 8 | Keep it informational for v0.7.0. Have #2305 decide |
| NQ-3 overseer `actions: read` (AD-9) | S3 does not merge until it is granted | AD-9 | Grant it on the overseer App |

> The table above is **superseded by AD-13a** [ruled 2026-11-10]. It is kept as history.

### AD-13a — Human rulings, 2026-11-10 (FINAL; supersede AD-13)

These rulings come from the human (ScottThurlow). They reached `technical-design` through the human-proxy session. The PR's CODEOWNER human review records them as confirmed.

| Q | Ruling | Applied in |
|---|---|---|
| OQ-H1 | Shell decision logic fails closed with "move decision logic into tested Python". There is no shell harness. | AD-8 |
| OQ-H2 | No `# pragma: no cover`, `# pragma: no mutate` or "documented equivalent" added in the PR reduces the counts. The 25% headroom covers real equivalents. `unit-test.md` changes to match. | AD-3, AD-4 step 3 |
| OQ-H3 | A per-mutant test timeout counts as **killed** (mutmut's convention). The whole-gate CI timeout still fails closed. | AD-4 step 7, AD-11 |
| OQ-H4 | Every existing `shell_logic_check.py` exemption applies, including the file-level `bootstrap/hos_bootstrap.sh` exclusion. An edited `if` line counts as added logic. | AD-8 |
| OQ-H5 | A verified human ruling covers only a named file's coverage and mutation **thresholds**. It does not cover path-load, shell or timeout failures. It is bound to the file's **content** (blob hash), not the head SHA, and is void if that file changes after the ruling. There is no in-gate exception path until S5. A human admin merge is the only override. S5 depends on #2101. | AD-10 |
| NQ-1 | The empty-selection carve-out (zero gated mutants and gated coverage ≥ 80%) applies only if the gated lines contain no decision logic (AST `If`/`For`/`While`/`Try`/`BoolOp`/`Compare`/`IfExp`, or a comprehension with an `if`). Otherwise the file fails with "move logic into a function so it can be mutated". Every other empty selection fails. | AD-6 step 4 |
| NQ-2 | Unmutatable gated lines (decorated functions, enums) are reported as `unmutatable_gated_lines`. They pass on coverage only if they contain no decision logic, under the same AST definition. Otherwise the file fails with "move the logic into an undecorated helper so it can be mutated". | AD-4 step 8 |
| Selection | Confirmed sound as in AD-6 and §4. | AD-6 |
| Path-load | Fail closed with a named fix and no exemption list. Most existing gated modules will fail on first touch until #2305 converts their tests. The introducing PR touches only gate files whose tests use canonical imports. | AD-12; TD-2304 §5.19, §7.1 |
| Scope | The first PR is S1 + S2 + S4. S3 and S5 are separate issues. Artifact retention is the maximum, and the CI token stays `contents: read`. | §8 |
| NQ-3 | Not ruled. S3 is out of scope for the first PR. | AD-9 |
| TD-Q4 (2026-11-11) [ruled 2026-11-11: Q4] | `Match` statements count as decision logic, in the NQ-1, NQ-2 and Q5 definition alike. | TD-2304 §5.5.1 |
| TD-Q5 (2026-11-11) [ruled 2026-11-11: Q5] | Module-level or class-level decision logic on gated lines is **not** coverage-only. It fails with "move the logic into a function so it can be mutated", using the same mechanism and AST definition as NQ-1 and NQ-2. Narrow carve-outs only, and nothing else: (a) `if __name__ == "__main__":` whose body is only a call (e.g. `sys.exit(main())`); (b) `try: import X` / `except ImportError:` fallbacks (import-only `try` bodies and `ImportError` handlers); (c) `if TYPE_CHECKING:`. | AD-4 step 8 (alongside NQ-2); TD-2304 §5.5, §5.10 |
| TD-Q8 (2026-11-11) [ruled 2026-11-11: Q8] | Apply the TD-Q5 carve-outs consistently: NQ-1 (the empty-selection rule) and NQ-2 (unmutatable lines) treat the three carved-out shapes as non-decision-logic too, so a file whose only logic is carved passes NQ-1 under its normal conditions (zero gated mutants and gated line coverage ≥ 80%). Carve-out (a) also accepts `raise SystemExit(<call>)` as the guard's single body statement, exactly equivalent to `sys.exit(<call>)`. Every other near-miss stays strict. | NQ-1, NQ-2 rows above; TD-2304 §5.5.3, §5.5.4, §5.10 |

---

## 7. Disagreements with the spec (for pm-agent; this ADR does not edit the spec)

- **D-1 (§3 gated lines).** "Changed lines that are executable statement lines" must become "changed lines that fall within an executable statement, attributed to that statement" (AF-2, AD-3). Otherwise continuation-line edits are not gated.
- **D-2 (REQ-16 / R2).** The import-time false fail (AF-3) needs a human ruling (NQ-1). The spec should state the outcome either way.
- **D-3 (§3 verified ruling, REQ-22).** Delete "the evaluator's CODEOWNER-comment rule until then". It is not executable CI code (AF-7). The interim state is "no exception path" (AD-10).
- **D-4 (REQ-26).** "Committed audit log (`audit/log/…`)" becomes "the trail of record (`origin/audit-log`, per #1538 R4)" (AF-6). The route is AD-9.
- **D-5 (REQ-28).** No cache in v1 (AD-5). That meets the requirement as written, since it says "may", and AC-25 becomes vacuous. pm-agent should mark AC-25 "not applicable while no cache exists", with a static test that the gate has no cache step.
- **D-6 (REQ-6 / "line coverage").** The gate uses statement (line) coverage only and ignores branch arcs, although `branch = true` is configured. The spec should say so explicitly.
- **D-7 (§7 constraints).** Add "mutmut, coverage and pytest-cov pinned exactly" (AF-1). Today only a major-series range is pinned.

---

## 8. Slices (each ≤15 files including tests; each independently mergeable)

| Slice | Content | Depends on | Notes |
|---|---|---|---|
| **S1** | `run_tests.sh`: `COVERAGE_CORE=ctrace`, `--cov-context=test`, the six explicit `--cov=` roots (ADR-A3; not `--cov=.`) [amended 2026-11-10, round 3], split suite-wide report, sidecar. `tests.yml`: artifact upload. Omit-list update. Equivalence test and the timing record | — | Changes the existing required job. A reliability-reviewer review is mandatory. It does not change `fail_under` |
| **S2** | `new_code_gate.py`, `_logic.py`, `_pytest_plugin.py`. The two new jobs. Exact tool pins. `repo_copy` marker, its guard test and marking the existing tests. `hos_required_contexts.txt` entry. AC-1 to AC-23 and AC-26 to AC-31, AC-34, with fixture repos only | S1 | Required from this PR (REQ-35). Its own new files must pass it. §5 items 1, 2 and 5 clear before merge |
| **S3** | `new_code_gate_ingest.py` + the `bin/hos-cron` overseer hook + sweep. AC-24 | S2; §5 item 3 (NQ-3) | Ingests S2-era artifacts retroactively within the 90-day retention |
| **S4** | `unit-test.md` CORE, contract §4, `templates/base-agent-register-examples.md`, `BASE-AGENTS-SPEC.md`, the evaluator's Phase 1 check, the worker loop wording (REQ-30 to REQ-33; AC-32, AC-33) | S2 | Top-level session authors the `.claude/agents/**` edits. The numbers it requires come from S2's output |
| **S5** | `fetch_rulings` → ADR-2101 verifier. `NCG:<path>` item kind (amends ADR-2101 AD-8). AC-20, AC-22's excepted case | #2101 S1 (or #2219) | Security-reviewer is mandatory |

---

## 9. Startup-gap and affected sign-offs

- **This is the initial architecture review for #2304.** No design, code or sign-off has been built against an earlier version, so no sign-off is orphaned.
- **The one pre-existing commit is `8113f8ba0`.** It changed `also_copy` and `source_paths` in the committed `[tool.mutmut]`, and it **stands**. It keeps `run_tests.sh --mutation` runnable. The gate does not read the committed mutmut table, so nothing in this ADR depends on it or invalidates it.
- **Amendment to ADR-2101.** AD-10 adds an item kind to ADR-2101 AD-8's closed set and a fourth consumer. ADR-2101's existing sign-offs are unaffected: it is unbuilt, and the change is additive and lands in S5. The S5 PR must cite this ADR.

## Escalation flag (CORE self-flag)

```
RISK: HIGH — new required merge gate on protected surfaces; changes the existing required `tests` job (S1); proposes a GitHub App permission (AD-9).
CONFIDENCE: MEDIUM-HIGH on AD-1..AD-12 (mutmut and coverage behaviour verified against the installed 3.8.1 / 7.17.2 sources); MEDIUM on AD-2's runtime numbers (S1 must measure) and on single-job re-run artifact access (S2 must verify).
Change classification: structural.
```

## Human Review Required

- §5 product-boundary items 1 to 5. Item 3 (`actions: read` on the overseer App) blocks S3.
- §6: OQ-H1 to OQ-H5, NQ-1 and NQ-2 were ruled on 2026-11-10 (AD-13a). The human confirms them on record in the PR's CODEOWNER review. NQ-3 is open and blocks S3 only.
- §2b: the architect's round-1 amendments are technical, not rulings. AR-1 changes which commit is gated (the `pull_request` merge commit, which is what the existing `tests` job already tests). It changes no ruled behaviour.
