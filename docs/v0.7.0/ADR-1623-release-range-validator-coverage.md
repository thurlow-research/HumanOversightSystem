# ADR-1623 — Release-range validator-coverage check (REQ-B4, re-homing G-d)

Issue: #1623 (milestone v0.7.0). Parent: #1340. Siblings: #1622 (REQ-B2/B3), #1624 (REQ-B5), #1625 (REQ-A13).
Author: architect. Date: 2026-10-13. Baseline: `5951256a8` (branch; `origin/main` = `112c56f8b`, an ancestor).
Input: `docs/v0.7.0/REQUIREMENTS-1623-release-range-validator-coverage.md` (pm-agent, REQ-C1..C13, ESC-1..5).
Coordinates with: `ADR-1340-release-panel.md` (AD-2, AD-9, AF-1), `ADR-1624-release-range-review-evidence.md` (AD-1, AD-2, AD-6, AD-7, ARCH-ESC-3), `ADR-1717-validators-not-scored-outcome.md` (D7, D8, D9), and the unmerged branches for #1752, #1630 and #1625.

**Verdict on the requirements: APPROVED_WITH_AMENDMENTS.** The product framing is right:
- one run over the release range;
- a denominator that is not self-reported;
- fail-closed on a bad range;
- release-only, so per-PR behaviour is unchanged.

Seven amendments (AM-1..AM-7, §9) close five premises the requirements missed. Three of them would have produced a gate that passes wrongly or can never pass:
- the result list cannot be keyed by dimension (AF-2);
- a pinned file list does not pin the content that is scored (AF-3);
- a release-sized run has no wall-clock budget, and no existing setting can raise its limits (AF-4).

**Status: Accepted (technical).** ESC-1..5 stay with the human (§10). ARCH-ESC-1 and ARCH-ESC-2 are added. S0, S1 and S2 can be done before any human answer (§8).

---

## 0. Verification of the pm-agent's claims (re-derived this session)

| # | Claim | Verdict | Evidence read this session |
|---|---|---|---|
| 1 | R2/R3 consumes only the suite's exit code, plus a first-line excerpt on FAIL | **Stands** | `worker.md:645-651` (R2 table, with no argument column); `:662-664` (R3 line `PASS\|FAIL (exit <code>)` plus a fenced first-line excerpt). |
| 2 | `run_validators.sh` exits non-zero only on: no files, tool preflight failure, or zero successful validators. Every validator is optional | **Stands** | `run_validators.sh:135-148`, `:181-192`, `:465-483`. Every call site passes `false` (`:307-424`). `run_with_retry` returns 2 for an optional unit (`run_with_retry.sh:122-126`), which `:257-261` counts as SKIPPED. `VALIDATOR_FAILED` therefore stays 0, and `:429-431` is dead. |
| 3 | `validator_count` counts only parseable result files, so a vanished dimension drops out of both counts | **Stands, with one refinement.** The count is of parseable **dict** files. A JSON list or scalar is also dropped (`:452-454`). | `:445-454` (non-JSON is silently `continue`d), `:507-513`. A missing script writes no outfile (`:222-226`). An exit-0 run with non-JSON output is counted as *succeeded* on the console (`:244-253`) but dropped by the aggregator. |
| 4 | `--diff <ref>` compares against the working tree, not `<tag>..HEAD` | **Stands** | `:85` `git diff --name-only "$DIFF_REF" … \|\| true`. A failure becomes an empty list, which leads to the "no files" exit 1 at `:135-148`. **Note:** a two-dot argument `A..B` passes through verbatim and *is* commit-to-commit. The defect is the argument the worker composes, not `--diff` itself. |
| 5 | `diff_size` ignores `--diff` | **Stands** | `:355-364`: the base is `merge-base HEAD origin/main`, then the tag, then `HEAD~1`. On a synced `main` the base is HEAD, so `:371-376` measures only working-tree dirt. The validator still runs with `0/0` (`:388-391`) and "succeeds". (ADR-1340 AF-1's table says this case is *skipped*. That is wrong; see FU-4.) |
| 6 | `derive_range` exists and is reusable | **Stands. Line range corrected.** It is `release_panel_logic.py:183-243`, not `:183-230`. Order: SHALLOW → NO_TAG → base/head unresolvable (→ NO_TAG) → NO_CONTENT after exclusions. Also reusable: `apply_exclusions` (`:258`), `changed_files` (two-dot, `:114`) and `run_git` (`:85`, the single subprocess seam). | Measured: `derive_range()` → `OK v0.6.0`. In range: 8,207 files, of which 7,752 are excluded and **455 reviewed** (186 `.py`, 55 `.sh`). `RUN_VALIDATORS_FILELIST_ONLY=1 … --diff v0.6.0` → 8,207 `ALL_FILES` and 185 `PY_FILES` (one in-range `.py` is deleted). The one-file difference from pm's 8,206 is the requirements commit on this branch. |
| 7 | `OUT_DIR` is hard-coded into `.claudetmp/`, so a release run would clobber per-step state | **Stands, and it is hard-coded twice.** | `:35` `OUT_DIR=".claudetmp/oversight/validators"`, and **separately** `:439` inside the aggregator heredoc. `:199` deletes every `*.json` there except `gate-results.json`. An override must change both places. |
| 8 | F1: `origin/main` has two `signoffs/validators/step*/summary.json` files | **Stands** | `git ls-tree origin/main signoffs/validators/` → `step1` and `step1754` only. `overseer.md:195` is check 5. |
| 9 | F6: this clone is not shallow; tag `v0.6.0`; 430 commits | **Stands** | `--is-shallow-repository` → `false`; `describe` → `v0.6.0`; `rev-list --count v0.6.0..origin/main` → 430. |
| 10 | F3: "no input files" emitters | **Stands, with a sharper condition (AF-7).** | `migration_scorer.py:184-193`, `ip_check.py:515-525` and `issue_query.py:240-249` emit it only when **every** argv path is absent from disk. |

**Searched for reuse (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/`.

What I found:
- `release_panel_logic.{derive_range, apply_exclusions, changed_files, run_git}`: reused (AD-3).
- `lib/changeset.sh` (#1759): a fail-closed file-list grammar for gates. **Rejected here.** It filters out non-existent paths and deleted files, which would change `ALL_FILES` for the full-file lanes and break REQ-C10 byte-identity (FU-3).
- `lib/git_depth.py`: shallow detection only, already covered by `derive_range`.
- `second_review_logic.py:998,1022`: the only other in-tree reader of `validator_count`, and it only passes it through.

What does not exist yet:
- no existing coverage computation anywhere;
- `validator_outcome.py` (#1717 S1a) is designed, not built;
- `derive_base_head` (ADR-1624 AD-2) is designed, not built.

### Architect's findings (these change the design)

**AF-1 (HIGH): `run_validators.sh` is itself a protected surface.** It is listed at `scripts/framework/protected_surfaces.txt:30`. The requirements flag only `worker.md` as protected. Any runner change in this issue therefore needs CODEOWNERS human approval to merge. The `coder` may author it, because it is not an agent definition. This shapes the slice plan: the runner change is kept minimal and isolated (S1).

**AF-2 (HIGH): you cannot count coverage from `summary.json`, because a validator's `dimension` is not its identity.**
- The runner names a validator by its `run_validator NAME`. The outfile is `$OUT_DIR/<NAME>.json` (`:220`).
- The self-reported `dimension` differs from that name: runner `hallucination` emits `"hallucination_surface"` (`hallucination_surface.py:203`).
- **Every JS-lane validator emits the same `dimension` as its Python twin.** For example, `complexity_metrics_js.py:240` emits `"complexity"`, and the same holds for `n1_queries`, `function_metrics`, `risk_number`, `static_analysis` and `hallucination_surface`.
- The retry-exhausted stub writes `dimension` = the runner name (`:256`), which is a third convention.
- `summary.results` carries no runner name. #1717's `validator_outcomes` is keyed by `dimension`, with `#2` suffixes on collision (TD-1717 §2.4).

So "which expected validators scored" cannot be answered from the summary on a mixed-language range. `expected` and `scored` must both key on the **runner name**, read from a runner-written dispatch record plus the per-name outfiles (AD-2).

**AF-3 (HIGH): pinning the file list does not pin the content.** Every validator reads file **contents from the working tree**:
- `Path(f).exists()` filters at `migration_scorer.py:184`, `ip_check.py:515` and `issue_query.py:240`;
- PY/SH lane membership uses `-f` (`run_validators.sh:129-132`).

If the release clone has an uncommitted tracked modification to an in-range file, that file is *listed* from `base..head` but *scored* from the working tree. AC-8 as written ("the modified file is not scored") only holds for files that are outside the range. Fix: refuse a dirty tracked tree (AD-3).

**AF-4 (HIGH): there is no wall-clock budget, and no existing setting can raise release limits.**
- A worker R2 suite runs in one Bash call. The foreground ceiling for a Bash call is 600 s (ADR-1624 AF-6 precedent).
- The per-attempt timeouts for the 13 dimensions dispatched on this range add up to **810 s** (`:307-424`). The worst case is ×3 attempts (`VALIDATOR_RETRIES=2`, `:61`).
- If the runner is killed by the Bash ceiling, it prints no line 1. R3 then records a bare `FAIL (exit 124/143)` with no signature, which the human cannot tell apart from a real failure.
- **`VALIDATOR_TIMEOUT` is dead config.** It is only the default for `run_validator`'s third parameter (`:215`), and every call site passes that parameter explicitly. No other file reads it (grep of `scripts/`, `bootstrap/`, `bin/`). REQ-C9's "raised limit, release only" therefore has no existing setting to use (FU-1).

**AF-5 (MEDIUM): the `timeout` class is not observable today.** `run_with_retry` collapses every exhausted optional unit to return 2 (`run_with_retry.sh:122-126`). Its `last_error` is a local variable that is gone when it returns. The exhausted stub hard-codes `"validator exhausted retries"` (`:256`). AC-5's `timeout` class needs the last attempt's return code captured inside the runner's own unit function (`_validator_unit`, `:236-239`). `run_with_retry.sh` is shared with the gates and must not change (AD-2).

**AF-6 (MEDIUM): pm's verification gap can be closed without code.** `OUT_DIR` is relative (`:35`). A full release-scale run inside a **throwaway local clone** (`git clone --local` into `mktemp -d` under `$TMPDIR`) writes only to that clone's `.claudetmp/`, and leaves this clone's state alone. REQ-C9's measurement can therefore happen before any design is fixed (S0).

**AF-7 (LOW): N/A cannot happen at release scale except in a deletion-only range.** As row 10 shows, the three full-file validators report "no input files" only when every path is absent from disk. The PY/SH lanes already require `-f`. On any range that touches an existing file, no full-file validator returns N/A. Deferring #1717's N/A recognition is therefore safe and conservative (AM-3, FU-2).

**AF-8 (LOW): exit-code collision.** An uncaught Python exception exits 1, which would be read as DEGRADED. This is the same defect as ADR-1624 AF-8, and AD-5 adopts the same cure.

---

## 1. Where the check lives

### AD-1: a new Python checker behind a thin `.sh` at a stable path. `run_validators.sh` gains only an opt-in release mode (it produces data, it does not judge).

- **`scripts/oversight/release_validator_coverage.py`** holds every decision:
  - range derivation and preconditions;
  - invoking the runner;
  - classification;
  - the verdict;
  - rendering line 1.

  It has a pure core, `classify(manifest, outfiles, range) -> CoverageResult` and `render(result) -> (lines, exit_code)`, a collector, and `main(argv)`.
- **`scripts/oversight/release_validator_coverage.sh`** is the R2 path. Like ADR-1624 AD-1, it resolves `REPO_ROOT`, does `exec python3 -m scripts.oversight.release_validator_coverage "$@"`, and maps any exit code outside {0,1,2} to 2. It contains no logic (SPEC-333). It takes **no arguments**: the range is derived internally, so R1.9's path anchor is unambiguous.
- **Rejected: putting the coverage verdict inside `run_validators.sh`.**
  - It would add judgment logic to a protected bash file (AF-1, SPEC-333).
  - It would need `derive_range` (Python) to be called from bash.
  - It would mix a release verdict into a per-PR producer whose exit contract REQ-C10 freezes.
- **Rejected: a checker that reads only `summary.json`.** AF-2 makes that impossible on mixed-language ranges.

## 2. How `expected` and `scored` are derived

### AD-2: a dispatch manifest is written by the runner, in release mode only. Per-name outfiles are the result source. There is no second copy of the lane rules.

In release mode (AD-3), `run_validator` appends to `$OUT_DIR/dispatch.tsv`. This is not a `*.json` file, so the aggregator's glob (`:445`) never sees it, and `summary.json` is unchanged:

```
dispatched<TAB><name>                      # first statement of run_validator, before the script-exists check
outcome<TAB><name><TAB><class><TAB><rc>    # class ∈ ok | missing | timeout | failed
dispatch-complete                          # after the last run_validator call (:425), before the aggregator
```

- **`expected`** = the set of `dispatched` names. It comes from the runner's own routing as it actually executed (`:304-425`), not from any validator's output (REQ-C3). There is no second copy of the lane rules (REQ-C13).
- **Integrity.** These all give **INDETERMINATE** (`manifest-incomplete`):
  - the `dispatch-complete` line is missing;
  - a `dispatched` name has no `outcome` line;
  - a name is duplicated;
  - a line is malformed.

  A runner that dies part-way through dispatch therefore cannot shrink the denominator.
- **`timeout` class (AF-5).** `_validator_unit` records its own return code in a global, `_RV_LAST_RC`, before returning. An exhausted unit is `timeout` if `_RV_LAST_RC == 124` and `failed` otherwise. `run_with_retry.sh` is not touched.
- **Per name**, `scored` is decided from the `outcome` line plus `$OUT_DIR/<name>.json`. Exactly one class applies:

  | Condition | Class |
  |---|---|
  | outcome `missing` | `missing` (script absent; counted in `expected`, AC-2) |
  | outcome `timeout` / `failed` | `timeout` / `failed` |
  | outcome `ok`, file absent, not JSON, or not a dict | `unparseable` (AC-3) |
  | outcome `ok`, dict, `error` present and not `None` (including `""`, `False` and `"no input files"`) | `errored` |
  | outcome `ok`, dict, `error` absent or `None`, `score` a non-bool finite number in [0, 1] | **scored** |
  | anything else | `unparseable` |

- **#1717 alignment (REQ-C13).**
  - If `scripts/oversight/validator_outcome.py` (#1717 S1a) is on `main` when S2 is coded, the checker calls `validator_outcome.classify(result) == "scored"` for the last two rows instead.
  - Otherwise S2 ships the table above, plus a test asserting it is **no looser than** TD-1717 §2's rows. A follow-up swaps it in (FU-2).
  - `not_applicable` is **not scored, and stays in `expected`** in v1 (AM-3).
- **#1752 alignment (REQ-C13).**
  - #1752 adds `DISPATCHED_NAMES` / `SKIPPED_NAMES` at the same hook in `run_validator`. If it lands first, S1 writes the manifest from that hook and adds **no** summary fields.
  - The manifest is not a parallel `summary.json` field. It carries the two things #1752's lists lack: the `timeout` class and the `dispatch-complete` sentinel.

## 3. Range, scope, content, isolation

### AD-3: the checker pins the range. The runner's release mode takes the range and the file list explicitly and fails closed.

**Checker, in order.** Each failure is INDETERMINATE (exit 2) with the reason; no later step runs:
1. **Range.** `rr = release_panel_logic.derive_range()`. `SHALLOW`, `NO_TAG` and `NO_CONTENT` are refusals, carrying `rr.reason` and `rr.remediation`. There is never a fallback to `HEAD~1`, `origin/main` or the working tree (REQ-C5, AC-7). The file set is `rr.reviewed` under interim `SCOPE = "reviewed"` (ESC-5).
   - Under ESC-5 = full, the set is `changed_files(base, head)` over ADR-1624's `derive_base_head`. That makes this path depend on ADR-1624 S1. Emptiness is then zero files → INDETERMINATE.
2. **Content pin (AF-3).** `git status --porcelain --untracked-files=no` must be empty → otherwise `dirty-tree`. `rev-parse HEAD` must equal `rr.head_sha` → otherwise `head-moved`. Untracked files are ignored: no lane reads a path that is not in the list.
   - All git calls go through `release_panel_logic.run_git`, called as a module attribute, so one monkeypatch covers both modules (the ADR-1624 AD-2 seam).
3. **Isolation.** `OUT = .claudetmp/oversight/validators-release/`. The checker deletes and recreates it, then writes `OUT/files.txt` (the file set, one path per line, sorted).
   - It never touches `.claudetmp/oversight/validators/` (per-PR state) or `signoffs/` (REQ-C8, AC-11).
   - The directory survives the run as evidence for the human, and as #1622's input (FU-5).
4. **Run.** `bash scripts/oversight/run_validators.sh --release-range <base40>..<head40> --files-from OUT/files.txt --out-dir OUT`, in its own process group, under the wall-clock budget (AD-4).

**Runner release mode (S1, protected).** All of this is reachable only when `--release-range` is given. The default argv path is byte-identical (REQ-C10, AC-12).
- **Flags.** `--release-range`, `--files-from` and `--out-dir` are all required together. They are mutually exclusive with `--diff`, `--step` and positional files.
  - Both SHAs must be 40-hex and resolve via `rev-parse --verify <sha>^{commit}`.
  - `--out-dir` must be a relative path under `.claudetmp/` and must not equal the default `OUT_DIR`.
  - Any violation → exit 2, with no summary written.
  - **No `--step`** means the `#555` `signoffs/` write at `:528-565` can never fire.
- **Files.** `FILES` = the lines of `--files-from`. Lane routing at `:127-133` is unchanged.
- **diff_size (F5).** `DS_BASE_REF = <base40>`.
  - `numstat` and the file list come from `git diff --numstat|--name-only <base40> <head40> -- "${FILES[@]}"`. That is commit-to-commit and restricted to the same set every other lane sees. Under ESC-5 = full the pathspec is a no-op.
  - A git failure → exit 2. The release mode has no `|| true`.
- **Output dir.** `OUT_DIR` = the flag's value. The aggregator's hard-coded path (`:439`) becomes `Path(os.environ["_RV_OUT_DIR"])`, and the script always exports `_RV_OUT_DIR="$OUT_DIR"` for that one invocation. In default mode the string is identical, so the output is byte-identical.
- **Limits (REQ-C9, AF-4).** Release mode only:
  - the effective timeout is the call-site timeout × `RELEASE_TIMEOUT_SCALE`;
  - retries are `RELEASE_RETRIES`.

  Both are runner constants. The interim values are `1` and `1`. Technical-design sets the final values from S0's measurement, subject to: Σ over dispatched (timeout × scale × (retries + 1)) for the *healthy* path ≤ 0.8 × `WALL_CLOCK_BUDGET_S`. A timeout is never excused (REQ-C9).
- **Manifest** (AD-2).

**Why the runner, not the checker, computes diff_size inputs.** The runner already owns that git call (`:349-392`, "Git runs HERE"). Moving it to the checker would fork the diff_size invocation between per-PR and release paths.

## 4. Budget, threshold, verdict

### AD-4: wall-clock budget and threshold constants

- `WALL_CLOCK_BUDGET_S = 540`, which is below the 600 s Bash ceiling and leaves room for R3.
  - On expiry, the checker sends `killpg(SIGTERM)` to the runner's process group, then SIGKILL after 10 s. Line 1 is `INDETERMINATE: budget-exhausted (<k>/<n> dispatched dimensions finished; pending: <names>)`, read from the partial manifest.
  - The runner's own TERM trap (`:31`) cleans up its temp files.
- **Threshold (ESC-2), as isolated constants:**
  - `TOLERANCE = 2` (option A);
  - `MUST_SCORE: frozenset[str] = frozenset()` (option C: a name in `MUST_SCORE ∩ expected` that is not scored → DEGRADED, whatever the tolerance);
  - option B = `TOLERANCE = 0`.

  The ruling is a constant flip plus one test.
- **Verdict** (pure core):
  - INDETERMINATE (exit 2) if any precondition, manifest, summary or budget check fails. The summary check: `OUT/summary.json` must exist and parse as a dict with a `results` list (AC-9). The runner's exit code is accepted as normal only if it is in {0, 1}. Exit 1 is its all-failed path, which is still a valid manifest.
  - DEGRADED (exit 1) if `scored < expected − TOLERANCE`, or if `MUST_SCORE` is violated.
  - PASS (exit 0) otherwise.
  - `expected == 0` is INDETERMINATE (`nothing-dispatched`). It is unreachable on any non-empty range, because four validators are dispatched unconditionally (`:347`, `:385-391`, `:395`, `:399`), but it is guarded.

### AD-5: output and exit contract (mirrors ADR-1624 AD-6)

Line 1 is a single line made of identifiers, counts and SHAs only. File paths never appear on it, because they are attacker-influenced. Format:
```
RELEASE-VALIDATOR-COVERAGE PASS 12/13 — not scored: ip_check(timeout) — range v0.6.0@<sha12>..<sha12> — files 455 (excluded 7752)
RELEASE-VALIDATOR-COVERAGE DEGRADED 9/13 — not scored: historical_density(timeout), ip_check(timeout), shell_logic(missing), static_analysis(errored) — range v0.6.0@<sha12>..<sha12> — files 455 (excluded 7752)
RELEASE-VALIDATOR-COVERAGE INDETERMINATE: range-derivation-failed: shallow clone — remediation: git fetch --unshallow --tags
```
- Every not-scored name appears, sorted, with no cap and no "and N more" (REQ-C7, AC-10). A PASS line still lists any not-scored names, so a PASS with tolerated losses is visible.
- Later lines hold one line per expected name (`<name> <class> rc=<rc>`), the `OUT` path, and the runner's exit code.
- Exit codes: `0` PASS, `1` DEGRADED, `2` INDETERMINATE or a usage error. `main` wraps `try/except BaseException`, and an unexpected exception gives `INDETERMINATE: internal-error:<Type>` and exit 2 (AF-8). The wrapper maps every other code to 2.

## 5. R2 integration (protected-surface edit)

### AD-6: replace the existing R2 row in place; do not add a row

The change in `worker.md:649` is from:

`| \`scripts/oversight/run_validators.sh\` (diff since last tag) | required | required |`

to:

`| \`scripts/oversight/release_validator_coverage.sh\` (validator coverage over the release range; no arguments) | required | required |`

- **Replace, not add.** The new suite *runs* `run_validators.sh` over the range (AD-3), so the old row is fully subsumed. The old row's only check was "≥ 1 validator succeeded", which is strictly weaker than AD-4.
- **Suite count.** Replacing keeps the count at five, so the PATCH-promotion sentence (`:653-655`, "all five suites") does not change. Nothing here conflicts with ADR-1340 PR 2 ("five" → "six") or with ADR-1624 S4 (which rewords the sentence so it does not count suites).
- **R1.9 carry-forward.** Check 3 anchors on the new path. No prior anchors exist on it, so the first armed run is always fresh.
- **Who authors it.** The top-level session, never `coder` (CLAUDE.md #1347). It needs the CODEOWNERS gate, sits in its own slice (S4), and is armed only after a demonstration run (AD-7).

## 6. Test strategy

### AD-7: two seams, hermetic, plus a demonstration run before arming

- **Runner (S1).** Use `tests/oversight/run_validators_harness.py` `hermetic_run` (a throwaway git repo plus the `validator_python_shim.py` `PYTHON`).
  - Release-mode tests:
    - a manifest for each class, including a shim that sleeps past a scaled timeout (rc 124);
    - a missing script;
    - exit-0 non-JSON output;
    - `dispatch-complete` present;
    - the `--step` + `--release-range` conflict → exit 2;
    - an out-dir equal to the default → exit 2;
    - diff_size receives `base..head` numstat with a dirty tracked file present (AC-8 at runner level);
    - `signoffs/` is never created.
  - The existing `test_run_validators_*` files must pass **unmodified** (AC-12).
- **Checker (S2).** Seams: `release_panel_logic.run_git` (monkeypatched) and a `run_runner` callable injected into `main` that writes canned `OUT/` trees. No other `subprocess` site exists; a static test asserts that.
  - AC-1..AC-11, AC-13 and AC-14 map one-to-one to tests. AC-13's grep test must be deleted by REQ-B7's PR, and its docstring says so.
  - **Added (binding):**
    - **T-1:** Python and JS twins both dispatched; the JS one errors → that **runner name** is reported, and is not collapsed into the shared `dimension` (AF-2).
    - **T-2:** a dirty tracked file in range → `dirty-tree` INDETERMINATE (AF-3).
    - **T-3:** a fake clock past the budget → `budget-exhausted` naming the pending dimensions, never PASS or DEGRADED (AF-4).
    - **T-4:** a manifest without `dispatch-complete` → INDETERMINATE (AD-2).
    - **T-5:** an injected `ValueError` → exit 2, never 1 (AF-8).
    - **T-6:** `MUST_SCORE={"ip_check"}` with 12/13 and `ip_check` not scored → DEGRADED.
    - **T-7:** a spy proves `.claudetmp/oversight/validators/` and `signoffs/` are never opened.
- **Demonstration run (before S4; ADR-1340 AD-9 precedent).** One real run of the S2 checker on the live range, with line 1, the per-name lines and the wall clock attached to the S4 PR. It must PASS or be explained.

## 7. REQ-B8 ordering

- This issue does not touch `overseer.md:170-220` (REQ-C12). AC-13 pins that.
- **G-d is re-homed only when S4 merges (armed), not when S2 merges (inert).** #1340's REQ-B7 removal must therefore wait for #1623 **S4**, together with #1622's and #1624's arming slices. "Landed" in REQ-B8 means *armed*.
- Until S4, G-d remains as pm F1 describes it: effectively unchecked. That is ESC-1(b)'s acknowledgement, and this design does not close the gap earlier.

## 8. Slice plan

| Slice | Content | Files | Codable before human answers? |
|---|---|---|---|
| **S0** | **Measurement, no code.** A full run of today's `run_validators.sh` over the 455 reviewed files of `v0.6.0..origin/main`, as explicit positional files, inside a `git clone --local` under `mktemp -d` (AF-6), under `timeout 1800`. It records per-validator wall clock and outcome, and is repeated once with the full 8,207-file set (for ESC-5). It is attached to the TD. It is read-only toward this clone. Network use is `gh` and PyPI, which the cycle already has. | 0 | **Yes.** It is a precondition of fixing `RELEASE_TIMEOUT_SCALE` / `RELEASE_RETRIES` and of ARCH-ESC-1. |
| **S1** | `run_validators.sh` release mode (AD-2, AD-3), header docs, runner tests. **Protected (AF-1):** `coder` may author it; merge needs CODEOWNERS approval. | ~4 | **Yes.** It does not depend on any ESC: scope arrives as `--files-from`. Rebase onto whichever of #1752, #1717 S2 or #1630 lands first. All of them edit `:73-86`, `:212-264`, `:349-392` and `:427-483`, so textual conflicts are expected (§11). |
| **S2** | `release_validator_coverage.{py,sh}`, tests (AC-1..14, T-1..7), `SCRIPTS-INDEX.md` regenerated. Interim constants: `SCOPE="reviewed"`, `TOLERANCE=2`, `MUST_SCORE=∅`, `OVERRIDE_SOURCE="none"`. Nothing invokes it. | ~5 | **Yes**, after S1 is on `main`. Inert. If ESC-5 = full, the `full` path also waits for ADR-1624 S1 (`derive_base_head`). |
| **S3** | ESC-3 override reader. It **reuses ADR-1624 AD-7's reader** (the unedited-comment rule and strict pagination), with grammar `Disposition: validator:<name>[, validator:<name>] @<head sha40> — <reason>`. It is pinned to the release-candidate head, because coverage is a property of one run (ESC-3 note). | ~3 | **No.** It waits for ESC-3 and for #1624 S3's reader. It is dropped if ESC-3 = no override. |
| **S4** | **Arming.** Authored by the top-level session only. The `worker.md` R2 row replacement (AD-6); `DECISIONS.md` (ESC-1 reduction plus the F1 acknowledgement); `docs/OVERSIGHT-RUNBOOK.md` (reading line 1, and the remediation per class). If ARCH-ESC-2 = yes, `protected_surfaces.txt` plus the CODEOWNERS regeneration. | 3–5 | **No.** It waits for ESC-1..5, ARCH-ESC-1..2, S1+S2 (and S3 if ruled) merged, and the demonstration run (AD-7). |

Merge order: S1 → S2 → (S3) → S4. S0 runs first and gates technical-design's constants, not S1's structure.

## 9. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-C3, REQ-C4).** `expected` and `scored` are keyed by **runner name** (the `run_validator NAME`), never by the result's `dimension` (AF-2). The source of truth is the release-mode dispatch manifest plus the per-name outfiles, not `summary.json`.
- **AM-2 (REQ-C5, AC-8).** "Pinned" also covers content: the tracked working tree must be clean and HEAD must equal `head_sha`. Otherwise the result is INDETERMINATE (`dirty-tree` / `head-moved`) (AF-3). AC-8 is restated: an uncommitted tracked modification gives INDETERMINATE, and diff_size receives `base..head` restricted to the scored set.
- **AM-3 (REQ-C4, AC-6).** In v1, `not_applicable` is **not scored and stays in `expected`**, even after #1717 lands (AF-7). This is stricter than REQ-C4. Removing a confirmed-deletion N/A from `expected` is FU-2 and needs #1717 S2's path facts. AC-6's post-#1717 half moves to FU-2.
- **AM-4 (REQ-C6).** INDETERMINATE also covers: an incomplete manifest, budget exhaustion, a dirty tree, a moved head, a runner exit code outside {0, 1}, and an internal exception (never exit 1).
- **AM-5 (REQ-C9).** The release limits are `RELEASE_TIMEOUT_SCALE` and `RELEASE_RETRIES` in the runner's release mode, plus the checker's `WALL_CLOCK_BUDGET_S = 540`. `VALIDATOR_TIMEOUT` is not a usable setting (AF-4).
- **AM-6 (REQ-C11).** The R2 row is **replaced** by `release_validator_coverage.sh` (AD-6). No row is added, so the suite count stays the same.
- **AM-7 (§7 / Human Review).** `run_validators.sh` is a protected surface too (AF-1). Merging S1 is human-gated.

Endorsed as written: REQ-C1, C2, C7, C8, C10, C12 and C13.

## 10. Escalations

### Human (pm-agent's; the architect gives a recommended default and does not rule)

| ESC | Architect's recommended default | Rationale / technical note | Gates |
|---|---|---|---|
| ESC-1 (a)+(b) | **Accept both**, as pm recommends | Two artifacts exist on `main` (row 8), so nothing real is lost. The window stays open until S4 (§7). | S4 |
| ESC-2 | **(A) `expected − 2`**, and revisit (C) with `MUST_SCORE={ip_check}` after the S0 run | `ip_check` (ScanCode, 120 s) is the dimension most likely to time out at release scale. If (C) is chosen before S0 shows it scores reliably, the gate risks never passing (REQ-C9). Each answer is a constant flip (AD-4). | S4 binding; S2 interim |
| ESC-3 | **An override exists**, reusing #1624's disposition reader, **pinned to the release-candidate head SHA** | A disposition for one candidate's timeout must not carry over to a later candidate's run. ADR-1624 AF-4 (edited comments) applies, so the unedited rule is reused. Interim `OVERRIDE_SOURCE="none"`: DEGRADED blocks. | S3 |
| ESC-4 | **Accept** | Measured not shallow (row 9). Remediation stays with ADR-1340 ESC-1 / #1630. | S4 |
| ESC-5 | **The reviewed set** | Measured: 455 reviewed vs 8,207 in range (94.5% excluded, row 6). It gives one definition of "the release" across the panel and this gate, and is the likeliest way to satisfy REQ-C9. Cost: the exclusion list, which is not yet protected (ADR-1624 FU-4), now also scopes the validators. That is another reason for ARCH-ESC-2. | S4 binding; S2 interim |

### ARCH-ESC (added by the architect; product-boundary checkpoint)

- **ARCH-ESC-1: if S0 shows a healthy release run cannot fit the 540 s budget in one worker Bash call, how is the gate executed?**
  - Options:
    - **(a)** The worker runs the suite as a background Bash job within the cycle, with a raised budget bounded by `HOS_CRON_MAX_SECONDS`. That is a longer cron cycle and a cost/latency change.
    - **(b)** The human runs it out-of-band and R2 checks the result, as in the ADR-1340 panel model. That is a new operational obligation.
    - **(c)** Narrow the scope further.
  - **Recommended: decide only after S0. If the measured run is ≤ 432 s (0.8 × budget), no question arises. Otherwise (a).**
  - This is product-boundary: it changes release latency and operating cost.
  - Gates: S4.
- **ARCH-ESC-2: add `scripts/oversight/release_validator_coverage.{py,sh}` (and `release_panel_exclusions.txt`) to `protected_surfaces.txt`?**
  - Without it, a release gate the worker can weaken without human review is a governance hole. `run_validators.sh`, which it drives, is already protected.
  - **Recommended: yes**, decided together with ADR-1624 ARCH-ESC-3 and FU-4.
  - Gates: S4.

## 11. Coordination with unmerged work on the same script

| Work | Overlap with S1 | Ruling |
|---|---|---|
| #1752 (`worker-1752-…-844742`, head `2d302e653`, unpushed) | It adds `DISPATCHED_NAMES` / `SKIPPED_NAMES` in `run_validator`, and summary fields in the aggregator (`:427-483`). | No functional dependency. If it lands first, S1 hooks the manifest at its `DISPATCHED_NAMES` site and adds no fields (AD-2). Its `HOS_REQUIRED_VALIDATORS` is **not** used by the release mode: that would turn an optional failure into an exit 1 with a summary, which the checker already reads correctly. |
| #1717 S2 (designed) | Aggregator `validator_outcomes` keyed by `dimension`; `--diff` source changes to `--name-status -z` (D9). | `validator_outcomes` is not consumed (AF-2). D9's `--diff` change does not affect the release mode, which uses `--files-from`. |
| #1630 (`worker-1630-…-1388163`, head `b201c520d`, unpushed) | Moves the diff_size block earlier and bases it on `--diff`. | Compatible. The release mode sets `DS_BASE_REF` before #1630's chain. S1 must not depend on #1630, and #1630 does not satisfy F5 for the reviewed set, because it diffs everything and runs against the working tree. |
| #1625 (`worker-1625-…-1934807`) | It edits `worker.md:380` (step 8.4) and `run_review_chain.sh`, not the R2 table and not `run_validators.sh`. | No conflict with S1 or S4. |

## 12. Follow-ups (named, not filed here)

- **FU-1:** `VALIDATOR_TIMEOUT` is dead config (`run_validators.sh:60,215`; every call site passes an explicit timeout). Either remove it, or make it a real per-PR override. The header documents a setting that does nothing.
- **FU-2:** N/A at release. Once #1717 S1a and S2 land, a `not_applicable` result on a path whose path fact is `deleted_*` is removed from `expected`, and the checker uses `validator_outcome.classify`. This restores REQ-C4's post-#1717 half and AC-6's second half.
- **FU-3:** per-PR `--diff` still swallows git failure (`:85` `|| true`). Evaluate adopting `lib/changeset.sh`'s fail-closed grammar without changing `ALL_FILES`' deleted-path semantics. Check whether #1630's CWE-88 work already covers part of this.
- **FU-4:** an ADR-1340 AF-1 table erratum. On an empty list, diff_size is run with `0/0` (`:388-391`), not skipped.
- **FU-5 (#1622 coordination):** tier and findings at release should read `.claudetmp/oversight/validators-release/summary.json` from this run. They should not start a second release-scale run. The checker leaves `OUT/` in place.
- **FU-6:** `release_panel_logic.changed_files` uses default `core.quotepath`. A path with unusual bytes comes back quoted, fails `-f`, and silently leaves the PY/SH lanes (shared with #1717 D9). It should be `-c core.quotepath=false -z`, and it affects the panel too.
- **FU-7:** the shared `dimension` across JS and Python lanes (AF-2) also makes per-PR `summary.results` and #1717's `validator_outcomes` ambiguous for any reader on a mixed-language PR.

## 13. Affected sign-offs (startup-gap analysis)

- **Should this have been settled in the initial review?** Partly.
  - The R2 row "(diff since last tag)" never had a defined invocation, and its diff_size leg never measured the range. That is ADR-1340 AF-1 / FU-3's `startup-artifact-gap`, already recorded there, and not a new one.
  - No #1623 design or code exists, so this ADR orphans nothing of its own.
- **These sign-offs stand:**
  - ADR-1340 AD-2: `derive_range` is reused unchanged.
  - ADR-1624 AD-1..AD-7: this ADR reuses AD-6's exit discipline and AD-7's reader, and changes neither.
  - ADR-1717 D1..D9: nothing here alters the producer contract.
- **Re-review on rebase:** whichever of #1752, #1717 S2, #1630 or #1623 S1 merges second must re-run code review on its rebase delta in `run_validators.sh`. Each one's approval stands only for its own behaviour.
- **One approved claim is re-opened:** ADR-1340 AF-1's table row on diff_size (FU-4). It is a documentation claim only; no code relies on it.

---

## Human Review Required

**RISK: HIGH.** This is a release gate at every tier. It changes a protected bash file (S1, AF-1) and a protected agent file (S4).

Three ways it could have passed wrongly are closed positively:
- vanished dimensions dropping out of the denominator (manifest-based `expected`, AD-2);
- lane collapse by `dimension` (AF-2 → runner-name keying);
- scoring uncommitted content (AF-3 → `dirty-tree`).

Two ways it could have failed uselessly are closed:
- an unbounded run killed without a signature (AF-4 → budget + INDETERMINATE);
- scoring 7,752 audit records (ESC-5's recommended default).

**CONFIDENCE: 85%.**
- High on §0. Every row was read or measured this session, including the 455/8,207 split and 13 dispatched dimensions.
- High on AD-1, AD-2, AD-5 and AD-6.
- **Medium on AD-3/AD-4's limits.** No release-scale run has executed. S0 measures before any constant is fixed, and ARCH-ESC-1 holds the contingency.
- Medium on S1's merge cost, because of three concurrent textual conflicts in the same file.

**BLAST RADIUS.**
- S1: `run_validators.sh` (shipped and protected). The default path must be byte-identical, which the existing tests pin unmodified (AC-12). The release mode is reachable only through a new flag.
- S2/S3: a new inert module.
- S4: whether any release may be cut (every tier), plus the human's override workload if ESC-3 = yes.

**Change classification: STRUCTURAL.** It adds a new blocking condition at every tier and a formal guarantee reduction (ESC-1(a)), and edits protected surfaces. Per the product-boundary checkpoint, ESC-1..5 and ARCH-ESC-1..2 must clear before S4 binds. S0–S2 may proceed now.
