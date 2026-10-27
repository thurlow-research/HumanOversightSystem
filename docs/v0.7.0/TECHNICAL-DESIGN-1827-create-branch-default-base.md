# TECHNICAL DESIGN — #1827: `create_branch.sh` defaults its base to the default branch, not HEAD

Status: architect ruling (binding). Scope: `bootstrap/create_branch.sh` and its tests. Protected surface (`bootstrap/**`), so merging it needs human approval.

## 1. Ruling

**Option 1, plus a fail-closed guard and visible messages.** When `--from` is absent, the base is the repository's default branch and never `HEAD`. `--from <ref>` stays the only way to start a new branch anywhere else, and every use of it now prints a warning on stderr.

Why not Option 2: it does block the silent path, but then every cycle that starts parked on a pushed-but-unmerged branch would refuse to create a branch. That parking is deliberate (#1044 guard). The worker would either stall, or learn to pass `--from main` by reflex, which makes `--from` meaningless as an adoption signal. Option 1 removes the hazard by construction. The base no longer depends on where HEAD happens to sit.

Option 3 (recording the base in the ownership record and checking it in `submit_pr.sh`) is **deferred** to a follow-up issue. It is defence-in-depth, the issue does not require it, and it widens the change into the P2 refusal path. The worker should file the follow-up after this lands. This design does not file it.

## 2. Base resolution (new Step 4a — runs BEFORE the ownership record is written)

All refusals must happen before Step 4 (`hos_bo_write_record`). A refusal therefore never leaves a record behind and never moves HEAD.

1. **Default branch name `D`.** Use the same resolution as `bootstrap/hos_repo_sync.sh:115-120`:
   `git symbolic-ref --short refs/remotes/origin/HEAD`, then strip `origin/`, falling back to `main`.
   Do **not** run `git remote set-head origin -a`. It is a network call, and `hos_repo_sync.sh` has already run it at session start. Do not hardcode `main` anywhere except as that fallback.
2. **Base ref.**
   - If an `origin` remote is configured (`git remote get-url origin` succeeds), the base is `refs/remotes/origin/D`. `bin/hos-cron` fetches with `--prune` before every cycle (around line 1376), so this ref is fresh even when `hos_repo_sync.sh`'s fast-forward of local `D` failed (diverged or dirty tree). It also excludes stray local commits on `main` (the #1945 class).
   - If no `origin` remote exists (local-only repos and the test fixtures), the base is `refs/heads/D`.
   - If the selected ref does not resolve (`git rev-parse --verify -q "<ref>^{commit}"`), **refuse**:
     `create_branch.sh: default base '<ref>' does not exist — refusing to fall back to HEAD (#1827). Fetch origin, or pass --from <ref> to choose a base deliberately.`
     Never fall back from `origin/D` to local `D`, and never fall back to HEAD.
3. **Dirty tracked tree (default path only).** If `git status --porcelain --untracked-files=no` is non-empty, **refuse**:
   `create_branch.sh: tracked changes in the working tree would be carried onto the new branch from '<current branch|detached>' — refusing (#1827). Commit, stash, or discard them first.`
   Untracked files are ignored. Uncommitted `audit/log/**` records are always present (#1803), and `checkout -b` cannot silently move untracked files into a commit. The `--from` path keeps today's behaviour, so adoption semantics stay unchanged.
4. **HEAD position does not matter.** Detached HEAD, HEAD on `D`, and HEAD on a foreign branch all resolve to the same base. If `HEAD^{commit}` differs from the base commit, emit one informational stderr line:
   `create_branch.sh: HEAD is on '<branch|detached @ sha>', not the default base — new branch cut from '<base ref>' (#1827). Use --from to adopt other work.`

## 3. Branch creation (Step 5 changes)

- Default path: `git checkout --quiet --no-track -b "$BRANCH_NAME" "$BASE_REF"`.
  **`--no-track` is mandatory.** Git's default `branch.autoSetupMerge=true` would set the new branch's upstream to `origin/D` when the start point is a remote-tracking ref. That has two consequences:
  - The #1044 return-to-main guard keys on whether `@{u}` exists. With upstream set to `origin/D` it would never see the upstream as gone.
  - A bare `git push` would target `D`.
- `--from` path: unchanged invocation (`checkout -b "$BRANCH_NAME" "$FROM_REF"`). Before the checkout, emit:
  `create_branch.sh: --from '<ref>' — ADOPTING commits this cycle did not create. Adopted commits carry NO review status: the full review chain MUST be re-run in this cycle before any PR is opened (#967, #1827; see .claude/agents/worker.md).`
  The warning fires for every `--from` value, including `--from main`. The script does not try to judge intent.
- The rollback-on-failure block is unchanged. The `ok` line reports the actual base (`from '<BASE_REF or FROM_REF>'`).
- **Stdout contract is preserved:** the branch name stays the only stdout line. Every new message goes through `warn`/`err`, which write to stderr.
- Step 3 (idempotent re-entry) runs before base resolution, so it is unaffected. Re-entry checks out the cycle's own branch and does not cut a new one.

## 4. Tests (`tests/automation/test_branch_ownership.py`, new class `TestDefaultBase1827`)

Add a fixture helper that creates a bare `origin` (under `tmp_path`), pushes `main`, and sets `origin/HEAD` (`git remote set-head origin main`). Each test asserts exactly one stdout line equal to the branch name, wherever the call succeeds.

1. **Regression, parked on a foreign pushed branch:** with origin present, create `worker-1776-x`, commit to it, push it with upstream, and stay checked out on it. Call without `--from`. Assert the new branch tip equals `origin/main` and that the foreign commit is not an ancestor (`merge-base --is-ancestor` fails). Assert the HEAD-not-default info line is on stderr.
2. **`--from` adoption still works:** same setup, with `--from worker-1776-x`. Assert the tip equals the foreign tip and that stderr contains `ADOPTING` and `re-run`.
3. **No origin, HEAD on another local branch:** cut from local `main`, not HEAD.
4. **Detached HEAD:** cut from the default base.
5. **Non-`main` default:** `origin/HEAD` points to `trunk`. Assert the base is `origin/trunk`.
6. **Local `main` ahead of `origin/main`:** the base is `origin/main` and the stray local commit is not included.
7. **Missing default ref:** an origin exists but `origin/main` is absent, or there is no origin and no local `main`. Assert non-zero exit, no ownership record file, no new branch, HEAD unchanged, and stderr contains `does not exist`.
8. **Dirty tracked tree:** non-zero exit, no record, no branch, HEAD unchanged.
9. **Untracked files only:** succeeds.
10. **No upstream on the new branch:** `git rev-parse --abbrev-ref '@{u}'` fails on it.
11. **Existing suite stays green unmodified.** Fixtures have no origin and HEAD on `main`, so the base is `refs/heads/main`, the same commit HEAD pointed to before.

## 5. Documentation updates

- `bootstrap/create_branch.sh` header lines 36-41: replace "(default: current HEAD)" with the §2 resolution: the default branch from `origin/HEAD`, else `main`; `origin/<D>` when an origin exists, else local `<D>`; never HEAD; fail closed. State that the script never falls back to HEAD, and give the #1827 rationale in one or two sentences (the composition with the #1044 parking guard). Note that `--from` now prints the re-review obligation on stderr.
- `bootstrap/worker-cron-prompt.md:90` ("cut from current main") stays true, so no change. Line 110 also needs no change.
- `.claude/agents/worker.md`: **zero changes.** Line 133 (the signature) and line 447 (adoption via `--from`) remain accurate. The implementer must grep `worker.md` for any statement that the default base is HEAD and report it if one exists. Nothing found during this review.

## 6. Governance notes

- This narrows the ADR-037 / SPEC-967 R1 default for `--from` from HEAD to the default branch. It closes a path that was not intended. No previously reviewed behaviour that callers depend on is removed, so the #967 sign-offs stand. The change does need its own full review chain.
- Product-boundary check: the change is internal to the worker. It has no user-visible, cost, retention, or topology consequence, so it is not routed for PM or human clearance beyond the existing protected-surface merge gate.
