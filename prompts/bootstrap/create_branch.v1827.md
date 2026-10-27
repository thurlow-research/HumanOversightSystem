# Prompt Artifact — create_branch.sh (#1827)

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/create_branch.sh` (+ `tests/automation/test_branch_ownership.py`) |
| **Description** | #1827 default base = repository default branch, never HEAD; `--from` validated, warned, `--no-track` |
| **Date** | 2026-10-11 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (coder declared MEDIUM; risk-assessor raised — operator-access-control seam, #967/#1044) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` subagent (exact text, initial build):

```
Implement HOS issue #1827 exactly per the approved technical design at docs/v0.7.0/TECHNICAL-DESIGN-1827-create-branch-default-base.md (read it fully first). Repo: <Worker clone root> (machine path redacted for the portability gate), branch worker-1827-create-branch-default-base-261011073501-1192418 (already checked out — do not create or switch branches).

Scope:
- bootstrap/create_branch.sh: change default base from HEAD to the default branch as the design specifies (origin/<D> when origin exists, else local <D>; resolve <D> the same way bootstrap/hos_repo_sync.sh does without network calls); fail closed if the ref is missing; all checks BEFORE the ownership record is written; refuse on dirty tracked files when no --from (ignore untracked); `--no-track` when cutting from origin/<D>; stderr notice when HEAD was elsewhere; stderr adoption warning whenever --from is used; branch name stays the ONLY stdout line. Rewrite the header comment lines 36-41 accordingly. Follow the existing script's style (err/warn/ok helpers, set -euo pipefail).
- tests/automation/test_branch_ownership.py: add the test cases the design lists (parked-on-foreign-pushed-branch regression using a real bare `origin` remote in tmp_path, --from adoption + warning, no remote, detached HEAD, non-`main` default, local main ahead of origin, missing ref refusal leaving no record/branch, dirty tracked refusal, untracked-only allowed, new branch has no upstream). Do not modify existing tests' assertions. Tests must clean up their temp files (use pytest tmp_path).
- grep .claude/agents/worker.md and bootstrap/worker-cron-prompt.md for any claim that the default base is HEAD; report findings but do NOT edit .claude/agents/ files.

Run: `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_branch_ownership.py -q` and also `-q tests/automation/test_hos_cron.py -k branch` if relevant; also `shellcheck bootstrap/create_branch.sh` if available. All must pass.

Commit your work (one or two commits) with message trailers: [Prompt-Artifact / AI-Model / AI-Risk / Supervised-by / Co-Authored-By]

Do NOT use the words closes/fixes/resolves followed by an issue number in commit messages. Do not push, file issues, create labels, or post comments. Emit your AGENTS.md self-flag (RISK/CONFIDENCE/BLAST RADIUS) at the end, plus the test output summary.
```

## Refinement History

Commits are cited by subject, not SHA: the branch's commit messages were rewritten (message-only, tree unchanged) to fix an unparseable trailer block, which changed every SHA.

1. **lint_check gate (black)** — coder asked to run black/isort/flake8 on the test file only; commit `style: black-format TestDefaultBase1827 tests` (style only).
2. **code-reviewer SHOULD_FIX (tests)** — add: origin remote with `origin/HEAD` unset falls back to `origin/main`; same with `origin/main` absent refuses with no record/branch/HEAD change; `--from` with a dirty tracked tree still succeeds and warns. Commit `test: cover unset origin/HEAD and --from with dirty tree ...`.
3. **security-reviewer SHOULD_FIX + NIT** — exact request: validate `--from` before the ownership record (refuse a leading `-`, refuse unless `git rev-parse --verify -q "${FROM_REF}^{commit}"` resolves); pass `--no-track` on the `--from` checkout too; make the dirty-tracked `git status` check fail closed on a non-zero exit. `--from` with a dirty tracked tree must still succeed (design keeps today's `--from` behaviour). Tests for each. Commit `fix: validate --from, --no-track on --from, fail closed on git status`.
4. **Inner-loop failure (pinned metric)** — `tests/oversight/test_shell_logic_check.py` pinned `create_branch.sh` at 0 decision constructs ("thin launcher"). After this change the validator genuinely counts 3 (the base-selection `if/else` branches; score 0.3). Exact request: do NOT restructure the script to dodge the metric (gaming); rename the test to reflect the genuine base-selection logic, assert count 3 / score 0.3, and document that guard clauses remain exempt. Touch nothing else. This is the one file edited outside the initial prompt's scope, by explicit worker request.

Reviewer sign-offs are in the step 1827 sign-off register and the PR thread.

## Constraints Specified

- Binding spec: `docs/v0.7.0/TECHNICAL-DESIGN-1827-create-branch-default-base.md` (architect ruling: Option 1; Option 3 deferred).
- Never fall back to HEAD; every refusal before `hos_bo_write_record`; stdout = branch name only.
- Must NOT edit `.claude/agents/**`; must NOT push, file issues, label, or comment.

## Human Review Notes

<!-- After human review, record findings here. -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `bootstrap/create_branch.sh`
4. Note any drift in a new version artifact
