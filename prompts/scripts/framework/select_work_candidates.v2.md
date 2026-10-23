# Prompt Artifact — select_work_candidates.py (v2)

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/select_work_candidates.py`, `bootstrap/worker-cron-prompt.md`, `AGENTS.md`, `tests/framework/test_select_work_candidates_started.py` |
| **Description** | #2155 WIP discipline: started-first (branch > design > none) ordering in work selection; prompt ordering/proportionality/definition of done |
| **Date** | 2026-10-23 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surfaces: selector + worker prompt) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` subagent (exact text of the brief file the dispatch pointed at):

```
You are implementing #2155 (WIP discipline in work selection) in the HOS repo at <repo root>, branch `worker-2155-wip-discipline-selection-261023073501-570555` (already checked out — do NOT create or switch branches, do NOT push, do NOT file issues, comment, or touch labels). Commit your work on this branch when done (one or two commits), with these trailers as ONE contiguous block after a blank line:

Prompt-Artifact: prompts/scripts/framework/select_work_candidates.v2.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

Do not put a closing keyword (closes/fixes/resolves #N) in any commit message; write "Refs #2155".

The issue explicitly says: implement directly, NO requirements/ADR/technical-design stage. Read it: `bash bootstrap/query_issues.sh --app worker --issue 2155 --full`. Its "Required behaviour" section is normative.

## What to build (this slice)

### 1. Selector: an "already started" signal + started-first ordering
File: `scripts/framework/select_work_candidates.py` (protected; read its module docstring — the algorithm order is a contract; keep every existing behaviour, exit code, stderr line, and budget accounting unchanged except as stated here).

Add a FREE (zero GitHub API requests; local git only, run against `_REPO_ROOT`, never a caller-supplied path — AD-13) classification of each kept candidate into a stage level:

- `branch` — "built work waiting to land": a local branch named `worker-<N>-*` (the `bootstrap/create_branch.sh` naming; check that script for the exact format) exists whose tip has at least one commit not reachable from `origin/main` AND `git cherry origin/main <branch>` shows at least one `+` (un-applied patch). Do not special-case the checked-out branch (selection runs before this cycle creates its own).
- `design` — "design merged, code not finished": `origin/main` contains a file under `docs/` whose basename starts with `TECHNICAL-DESIGN-<N>` or `ADR-<N>` followed by `-`, `.` or `_` (so #155 does not match ADR-1552; also match combined names such as `ADR-1660-1662-...` for both 1660 and 1662 — i.e. N appears as one of the hyphen-separated leading numeric components). Use one `git ls-tree -r --name-only origin/main -- docs` call per run (not per candidate).
- `none` — neither.
Precedence when both: `branch`.

Fail-safe: if git is unavailable, `origin/main` is missing, or any git subprocess fails/times out (use a short timeout), classify every candidate `none`, emit exactly one stderr line `select_work_candidates: WARN started-signal-unavailable` and otherwise behave exactly as today. The started signal must never cause an exit-code change or drop a candidate; it only reorders.

Ordering (strict, per the issue's "does not skip a level"): stage level sorts BEFORE priority. stage order: branch(0) < design(1) < none(2). Both the WALK order and the EMIT order gain the stage key in front: WALK = (stage, rank, -number), EMIT = (stage, rank, number). The walk order matters because the 5-candidate clamp (`_DEFAULT_MAX_CANDIDATES`) would otherwise drop a started low-priority issue.

Output line: started candidates get a marker after the priority: `#<n> [<priority>] [started:branch] <title>` / `[started:design]`; unstarted lines are byte-identical to today (`#<n> [<priority>] <title>`). Check every consumer of this stdout format (grep `bin/hos-cron`, `bootstrap/`, `scripts/`, `tests/` for the `#N [priority]` parsing, e.g. how hos-cron extracts candidate numbers, and `tests/framework/test_selection_call_sites.py`) and make sure none breaks.

Add a stderr summary line on every run that reaches emission: `select_work_candidates: STARTED branch=<count> design=<count>` (counts over the emitted candidates). Do not add it to fail-closed (exit 2) paths.

Update the module docstring's algorithm/ordering paragraph to describe the stage key (one short paragraph, cite #2155).

### 2. Worker prompt: ordering, proportionality, definition of done
File: `bootstrap/worker-cron-prompt.md` (protected). Edit Step 2 and Step 3 only:
- Step 2: the list is now ordered started-work first ([started:branch], then [started:design]), then priority. State the five-level ordering from the issue (1 own-PR feedback — already Step 1; 2 land built branches; 3 finish code for merged designs; 4 new code needing no spec; 5 spec work, only for the next thing to build) and that the worker does not skip a level while a higher one is non-empty. For a `[started:branch]` pick: the existing branch was not created this cycle, so per #967 the worker does not continue on it — it cherry-picks the unique commits onto a fresh branch from `create_branch.sh` (that is the existing re-adoption pattern; reference #2126 for the full protocol). If the branch's work turns out already landed on `origin/main`, delete the stale local branch (`git branch -D`) so it stops ranking as started, and move to the next candidate.
- Step 3: spec proportionality — one high-level spec per design chain at the start (direction, constraints, interfaces, costly-to-reverse decisions); slice detail written in the cycle that builds the slice; no spec PR for a slice while built code from an earlier slice of the same chain is unlanded; review of risky code is unchanged. Definition of done: an issue is done when working code is merged; a merged spec is not done; the cycle summary reports merged code first.
Keep the edits tight — a few sentences/bullets each. Do not touch other steps.

### 3. Standing statement
`AGENTS.md`: add one short paragraph (new `## Core Principle: Finish What's Started` section placed after "Use the Code, Don't Roll It Yourself") stating: working merged code is the measure of progress; spec only what is needed, just in time; finish started work before starting new; given a choice between finishing code and writing a spec, finish the code (#2155). 4–6 lines max. If any test pins AGENTS.md headings/anchors or line counts, keep it passing.

### 4. Tests
Add `tests/framework/test_select_work_candidates_started.py` using the existing test patterns in `tests/framework/test_select_work_candidates.py` (fixtures, gh fakes). Use a real temporary git repo (under pytest's tmp_path — temp hygiene is enforced; clean up) or monkeypatch the git-reading helper — your choice, but at least one test must exercise real git for the branch/cherry and ls-tree logic. Cover:
- a started:branch low-priority issue emits before an unstarted critical one (the "lower level not chosen while a higher one is non-empty" enforcement);
- design beats none; branch beats design; within a level priority then number order holds;
- the walk order admits a started issue even when >5 higher-priority unstarted issues exist;
- a branch whose patches are all already on origin/main (cherry shows only `-`) is NOT started;
- ADR-number boundary matching (ADR-1552 does not mark #155; ADR-1660-1662 marks both);
- git failure → every candidate `none`, the WARN line once, exit code and candidate set unchanged;
- unstarted output lines byte-identical to the pre-change format; STARTED summary line present.
Also add a check that `bootstrap/worker-cron-prompt.md` states the ordering (a simple anchor-text test, e.g. that it mentions `[started:branch]` and "does not skip a level") — put it next to existing prompt-text tests if there are any (grep tests/ for worker-cron-prompt.md).

### 5. Validation
Run `bash scripts/framework/run_tests_inner_loop.sh` and make it green (fix pre-existing failures only if in files you touched). Then run the gates on your changed files: `bash scripts/oversight/run_gates.sh <changed files>`. Use scripts/oversight/.venv/bin/python if you need Python tooling. Report: files changed, commit SHAs, test results (counts), gate results, your self-flag (RISK/CONFIDENCE/BLAST RADIUS per AGENTS.md), and anything you were unsure about.

Out of scope (do NOT build): cycle metrics / spec-to-code ratio (that is #2131's per-cycle metrics — leave it), the hos-in-progress label (#2157), changes to bin/hos-cron beyond what is strictly needed for the new output format to keep parsing.
```

## Round 2 (after code-review CHANGES_REQUESTED: M1, S1, S2, S3, N1, N3)

Dispatched by the autonomous worker to the `coder` subagent (exact text of the brief file):

```
Round 2 for #2155 on branch `worker-2155-wip-discipline-selection-261023073501-570555` in <repo root> (checked out; do NOT switch branches, push, file issues, comment or touch labels). The round-1 brief is in prompts/scripts/framework/select_work_candidates.v2.md and your round-1 commit is 5072d4a6a. Code review returned CHANGES_REQUESTED. Fix exactly the following, then commit (one commit, "Refs #2155", no closing keywords) with this contiguous trailer block after a blank line:

Prompt-Artifact: prompts/scripts/framework/select_work_candidates.v2.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

Work efficiently: you have about 8 minutes of wall time. Run only the targeted test files while iterating; the worker will run the full suite afterwards.

1. (S1, the cause) Replace the `git cherry` landed test in `scripts/framework/select_work_candidates.py` with a CONTENT-level test that handles squash merges: for each matching branch, run `git merge-tree --write-tree refs/remotes/origin/main <full refname>` (git 2.53 is installed). The branch is `branch`-stage (unlanded work) iff the merge exits 1 (conflict) OR the result tree OID (first stdout line) differs from `git rev-parse refs/remotes/origin/main^{tree}` (resolve that once per run). An exit code other than 0/1, or a timeout, is a `_GitFailure` (existing fail-safe). Merging a branch whose changes are already on main yields main's tree exactly, whatever the merge mode (squash, rebase, cherry-pick, merge). Update the docstring/comments accordingly.
   (N3) Enumerate with `%(refname)` (full ref) and derive the issue number from the stripped name, instead of `%(refname:short)`.
   Tests: replace/extend `test_branch_already_landed_is_not_started` with (a) single-commit cherry-pick landed → not started, (b) multi-commit branch squash-merged onto main as ONE commit → not started (this is the regression case), (c) branch landed and main has since changed other files → not started, (d) branch conflicting with main → started.

2. (M1) `bootstrap/worker-cron-prompt.md` Step 2: REMOVE the instruction to `git branch -D` a branch. Replace with: the selector only marks a branch started when merging it into `origin/main` would change something, so a `[started:branch]` pick has real unlanded work; re-adopt it onto a fresh `create_branch.sh` branch per #967/#2126; if it cannot be landed this cycle (e.g. it is blocked on a human ruling), record that with `bootstrap/escalate_to_human.sh` (which applies `needs-human` and so removes it from selection) rather than leaving it to re-rank every cycle. Never delete a worker branch by hand.

3. (S3) `design` stage requires a `TECHNICAL-DESIGN-<N>` file; an `ADR-<N>` alone (or REQUIREMENTS) does NOT mark `design` — its next step is still a spec. Update the regex/helper, tests (ADR-only → none; TD → design; combined `TECHNICAL-DESIGN-1660-1662-x` marks both), and add a one-line code comment noting that legacy low-numbered docs (e.g. TECHNICAL-DESIGN-63) can collide with old issue numbers, which is harmless unless that issue is open and needs-ai.

4. (N1) Add a clamp test where a `design`-stage low-priority issue sits behind more than 5 higher-priority unstarted issues and is still emitted.

5. (S2) `bin/hos-cron`: change the "Next work candidates" header text at ~line 2094 from "highest priority first" to "started work first, then highest priority", and fix the comment at ~2095-2101 that says it emits in "(rank, number ASC)" order to "(stage, rank, number ASC)" citing #2155. Check `tests/automation/test_hos_cron.py` for an assertion on that header text and update it consistently if one exists. Also update `bootstrap/worker-cron-prompt.md` wherever it quotes that header (it refers to the "Next work candidates" block).

6. `docs/LABELS.md` priority row (~line 49): the emission order now ranks started stage first (branch > design > none, #2155), then priority, then lowest number. One clause; keep the rest of the row.

Do NOT edit `.claude/agents/worker.md` (agent definition — the worker session handles it).

Then run: the three select_work_candidates test files + test_select_work_candidates_started.py + tests/framework/test_selection_call_sites.py + the relevant tests/automation/test_hos_cron.py tests (-k for the context/header ones), and the gates on your changed files (`bash scripts/oversight/run_gates.sh <files>`). Report: commit SHA, files, test counts, gate results, anything unsure.
```

## Worker-session edit (not delegated)

`.claude/agents/worker.md` "Select by priority, then number" bullet updated to the started-first ordering by the top-level worker session directly, per CLAUDE.md "Agent-definition edits (HOS source repo only)" (#1347); `coder` may not write agent definition files.
