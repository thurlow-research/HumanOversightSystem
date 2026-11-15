# TECHNICAL-DESIGN-2287: the overseer cleans up its own branches (#2287, slice 2 of 3 of #2285)

**Status:** APPROVED by architect, round 1, with amendments applied in the body (see "Architect review — round 1" at the end).
**Binding input:** the #2287 issue body, which is the requirements spec (`priority:critical`). There is no separate REQ or ADR (spec proportionality, #2155). Slice 1's approved design, `docs/v0.7.0/TECHNICAL-DESIGN-2286-reap-orphans.md` (TD-2286), is binding where this TD extends it. Rule IDs below (N1–N5, G1, D1–D3, A1–A11) are TD-2286's.
**Change class:** additive. It adds one engine rule (D4), one protected-name rule (N2a), one content guard (N6), one new script and new overseer wiring. (The read-only `audit-branches` subcommand is deferred, per architect finding A9.) The behaviour changes to merged code are that some branches TD-2286 would reap are now kept (N2a, N6), and that branches matching `REVIEW_RE` that are no PR's `head.ref` and that TD-2286 kept as `unlanded-no-pr` may now be reaped under D4 (A11). See §9 for the startup-gap and sign-off analysis.
**Contract only.** This document contains no implementation.

```
RISK: HIGH
CONFIDENCE: MEDIUM
BLAST RADIUS: every clone that runs readopt.py reap-orphans (engine rules), the
  Overseer clone's ~95 local branches (wiring), and overseer review behaviour
  (overseer.md, overseer-cron-prompt.md, hos-review-pr.md).
```

## Human Review Required
- **Protected surfaces:** `bin/hos-cron`, `bootstrap/**`, `.claude/agents/overseer.md`. Human review at merge.
- **Deletion is human-gated:** overseer wiring ships with `dry-run` as the default (§6.2). Branches are deleted only after a human has reviewed the Overseer-clone dry run attached to the PR and set the mode to `on`.
- **Audit branches:** none are deleted in this slice (§4). §10 asks one non-blocking question about what happens to them next.

## 0. What already exists (search record, CLAUDE.md "search first")

I searched `scripts/` (recursively), `bootstrap/`, `bin/`, `scripts/automation/lib/`, `.claude/agents/overseer.md`, `bootstrap/overseer-cron-prompt.md` and `.claude/commands/hos-review-pr.md` for `refs/pull`, `worktree add`, `gh pr checkout` and `checkout`.

| Found | Use here |
|---|---|
| Nothing anywhere fetches or checks out a PR head. None of the three overseer docs say how to get a PR's code locally. | This is the root cause: the model improvises `pr-N` / `pr-N-review` / `pr-N-check` branches. §2 adds the sanctioned entry point. |
| `bin/hos-cron` `_sync_audit_logs` (~590–625) uses a detached `git worktree add --detach` under `mktemp -d "${TMPDIR:-/tmp}/…"`, an EXIT-trap `worktree remove --force` and `git worktree prune`. | Reused as the pattern for §2. |
| `scripts/automation/readopt.py reap-orphans` (slice 1). It scans every `refs/heads/*`, makes all decisions before deleting, fails closed and prints REAPED lines with a `tip=` field. | Extended (§3, §4). No new reaper. |
| `github.list_all_pulls` (paginated, fail-closed) | Reused. D4 indexes the same listing by number, so it adds no API call. |
| `scripts/oversight/lib/audit_log.py` `record_relpath` and `canonical_bytes` (the canonical writer #888 uses) | Used by the §1 probe; reused by the §5 deterministic audit check in the later slice that builds it (deferred, A9). |
| `scripts/migrate_audit_log_to_dir.sh` (#888 P4) | Not run here. It is the mechanism behind option A in §10. |
| `bin/hos-cron` worker `reap-landed` block (~1707–1740: `_RO_BOUND`, `_RO_EVENT_RE`, `_audit cycle-branch-reap`) | Overseer wiring mirrors it, with its own bound, regex and cadence (§6). |

## 1. Measured inventory (Overseer clone, read-only, 2026-11-08)

| Group | Count | Finding |
|---|---|---|
| `pr-N`, `pr-N-review`, `pr-N-check`, `prN*`, `pr-N-new` | 44 | Every commit is authored by the PR's author (`hos-worker-hos[bot]` or `ScottThurlow-Claude[bot]`). The overseer authored none of them, so they are PR heads or older versions of them. 22 have landed by ancestry or content (D3 already reaps those). The other 22 need a name-to-PR rule (D4). |
| `audit/overseer-cycle-*` (4), `chore/audit-overseer-cycle-*` (16), `chore/overseer-audit-*` (12) | 32 | Each one changes **only** `audit/oversight-log.jsonl`, the single-file log retired by #888 P5 on 2026-06-28. That file is on neither `origin/main` nor `origin/audit-log`. Branch dates are 2026-06-22 to 06-28. |
| Legacy: `worker-N-*` (3), `worker/N-*`, `fix/*` (2), `feat/*` (2), `human-…-research-log-session` | 9 | Handled by TD-2286's D1, D1', D2 and D3 unchanged. |
| `main` | 1 | Current branch, and the only worktree. No `refs/pull/*` refs are present locally. |

**Audit-record probe (read-only).** I mapped every JSONL line each audit branch adds relative to its merge-base with `origin/main` through `record_relpath` and `canonical_bytes`. I then looked for that path with an identical blob OID on `origin/audit-log` or `origin/main`. Result: 1,436 added lines. 72 are present, 1,270 are missing, 94 cannot be parsed (invalid JSON or no `timestamp`), and none were present with different content. Three branches pass completely:
- `chore/overseer-audit-2026-06-23T02Z`, which adds 0 lines;
- `chore/overseer-audit-2026-06-23T2130Z`, with 17 of 17 lines present;
- `chore/audit-overseer-cycle-2026-06-23T2014Z`, with 4 of 4 lines present.

The other 29 hold records that exist nowhere else. Deleting them is exactly the #1255 hazard.

**Engine gap in slice 1 (the #1255 hazard is live in merged code).** TD-2286's N2 protects only `audit/*`. The two `chore/…` audit patterns are unprotected. In any clone, a `chore/audit-overseer-cycle-*` branch that was the head of a closed PR, or an ancestor of main, matches D1' or D3 today. In addition, an audit-record branch with any other name can match D1' or D2 (closed PR or closed issue) while holding unsynced records. §4 closes both gaps in the engine.

## 2. Reviewing a PR without a local branch: `bootstrap/review_worktree.sh` (issue item 1)

The script was renamed (from its earlier "checkout"-style name) to `review_worktree.sh` per human ruling C on #2287 (2026-11-09); behaviour unchanged.

Every call is a single command with literal arguments, so it fits the `claude --print` allowlisting rules: no `$(…)`, no variables, no chaining.

```
bash bootstrap/review_worktree.sh --pr <N> --expect-sha <sha40> [--repo <path>]
bash bootstrap/review_worktree.sh --cleanup --pr <N> [--repo <path>]
bash bootstrap/review_worktree.sh --cleanup-all [--older-than-mins <M>] [--repo <path>]
```

### 2.1 Contract for `--pr`

| Step | Requirement |
|---|---|
| Validate | `<N>` must match `^[1-9][0-9]{0,6}$`. `<sha40>` must match `^[0-9a-f]{40}$` and is **required**. It pins the review to the head SHA the verdict will be posted against, which the overseer already reads for `check_pr_reviewed.sh`. Any bad argument exits 2. |
| Resolve repo (A5) | `--repo` defaults to the cwd. Whatever is given, the script operates on the **main worktree** of that repository: the parent of `git rev-parse --path-format=absolute --git-common-dir`. Run from inside a review worktree, it therefore still targets the main checkout and never nests a worktree inside a worktree or removes its own cwd. If `--repo` is not inside a git repository, exit 2. |
| Scratch location (A6) | Resolve `root = ${TMPDIR:-/tmp}` to an absolute, symlink-resolved path. Refuse with exit 5 and a one-line stderr message naming `TMPDIR` when `root` is inside the main worktree (this covers `.claudetmp/`) or is `/tmp/claude` or below it. A repo copy inside the tree would be scanned by validators and `git status`; `/tmp/claude` is for small command artifacts only. |
| Idempotent | Run the `--cleanup --pr <N>` logic first, so at most one review worktree exists per PR. |
| Fetch | `git -C <main> fetch --no-tags --no-recurse-submodules --refmap= --quiet origin refs/pull/<N>/head`. The refspec has no destination, and the empty `--refmap=` (A4) disables the opportunistic remote-tracking update that a configured `remote.origin.fetch` (for example `+refs/pull/*/head:refs/remotes/origin/pr/*`) would otherwise perform. So **no local ref of any kind is created**; only `FETCH_HEAD` is written. A failed fetch exits 3. |
| Pin | `git rev-parse FETCH_HEAD^{commit}` must equal `<sha40>`. Otherwise exit 4 (`head-moved`) and create nothing. Every later step uses `<sha40>`, never the name `FETCH_HEAD`. |
| Create | `scratch = mktemp -d "<root>/hos-review-pr<N>.XXXXXX"`, then write `<sha40>` to `<scratch>/expected-head` (A3), then `git worktree add --detach --quiet <scratch>/wt <sha40>`. On failure, remove `<scratch>` and exit 5. The detached worktree's HEAD keeps the object alive against gc. |
| Report | Stdout gets exactly two lines: `WORKTREE=<abs path>` and `HEAD=<sha40>`. Errors go to stderr as one line each. |

**Invariant:** the output of `git for-each-ref refs/heads/` is byte-identical before and after every mode of this script.

**Location:** worktrees live only under `$TMPDIR`. They never go in `.claudetmp/` or in `/tmp/claude/` (CLAUDE.md, "Temp and working-state locations").

### 2.2 Contract for `--cleanup` and `--cleanup-all`

A worktree is a **review worktree** only when all of the following hold in `git worktree list --porcelain`:
- the entry has a `detached` line, so no `branch` line;
- it is not the main worktree;
- its path matches `*/hos-review-pr<digits>.<suffix>/wt`, where `<suffix>` matches `[A-Za-z0-9]{6,}`;
- for `--cleanup`, `<digits>` equals `<N>`.

No other worktree is ever touched.

For each review worktree:
1. **Commit guard (A3).** Read the entry's `HEAD` line from the porcelain listing and `<scratch>/expected-head`. If the file is missing or unreadable, or the two SHAs differ, do **not** remove anything: print `KEPT-WORKTREE pr=<digits> path=<path> reason=head-moved` to stderr and continue. A moved detached HEAD means a commit was made in the worktree, and `--force` removal plus `worktree prune` would leave it with no ref and no reflog. Uncommitted files are not protected; they are throwaway by definition.
2. Run `git worktree remove --force <path>`. Review worktrees are throwaway; validators may leave files in them.
3. Remove the parent `hos-review-pr<digits>.<suffix>` directory only if its basename matches that pattern.
4. Print `REMOVED-WORKTREE pr=<digits> path=<path>`.

After the loop, run `git worktree prune`. This also clears entries whose directory `tmp_reaper.py` has already deleted.

`--older-than-mins M` (for `--cleanup-all`; default 0) skips any worktree whose scratch directory mtime is younger than M minutes.

Exit codes: 0, including when nothing was found. 2 for a usage error. A `remove` that fails prints a WARN, the loop continues, and the script exits 0. This is hygiene; it is never a gate.

### 2.3 Overseer instructions (docs)

**`.claude/agents/overseer.md`.** Add a new subsection under "Shell usage (both modes)", titled **"Getting a PR's code locally (#2287)"**. It must say:
- Prefer API and diff reads (`gh api …/pulls/<n>/files`, `git diff` against fetched SHAs). They need no local tree.
- When a local tree is needed, the **only** sanctioned way to get one is `bash bootstrap/review_worktree.sh --pr <n> --expect-sha <head_sha>`. Use the printed `WORKTREE=` path literally.
- When you are done with that PR, run `bash bootstrap/review_worktree.sh --cleanup --pr <n>` **in the same PR's handling, whether the review succeeded, failed, deferred or was skipped.**
- Never create a local branch. That rules out `git checkout -b`, `git switch -c`, `git branch <x>`, `gh pr checkout`, `git fetch origin pull/<n>/head:<name>`, and checking out a PR head in the main checkout.
- The cycle-end safety net (§6.3) catches a missed cleanup. It does not replace the cleanup step.
- **If the script exits non-zero (A7),** do not retry it with a different method. Review from API and diff reads only, and say in the verdict that no local tree was available and why (the exit code and stderr line). Never fall back to a local branch, `gh pr checkout` or a checkout in the main checkout. Exit 4 (`head-moved`) means the PR moved; re-read `head_sha` and start the review again.
- **The worktree is read-only review input (A8, ruling on R5).** Never commit, amend or stash in it; the overseer authors no commits (the §2.2 commit guard will refuse to clean up a worktree whose HEAD moved, and the human must then inspect it). Run every HOS tool (gates, validators, `run_second_review.sh`, `check_*` scripts, `readopt.py`) **from the main checkout's copy**, by its path in the main checkout, passing worktree file paths as arguments. Never invoke a script by a worktree path (`bash <WORKTREE>/scripts/...`), and never run `python3 -m ...` with the worktree as cwd, because that imports the PR's copy of the package. Reason: a PR that modifies a gate or validator must not be judged by its own modified copy. Executing the PR's own code (for example its tests) is unchanged current practice, and is out of scope here; for a PR whose head repository is not this repository (a fork), execute nothing from the worktree.

**`bootstrap/overseer-cron-prompt.md`.** Add one bullet to Step 1 with the same two literal commands, the never-branch rule and the run-tooling-from-main rule, pointing to the overseer.md subsection.

**`.claude/commands/hos-review-pr.md`.** Add one step that uses the same two commands, and add "never create a local branch" and "run HOS tooling from the main checkout, never from the worktree" to the Safety constraints.

**Boundary:** this design sanctions no new execution of PR-head code. The A8 rule narrows current practice: HOS tooling runs from main. See risk R5 in §10.

## 3. Engine rule D4: review-named branches (issue item 2)

**Name rule:** `REVIEW_RE = ^pr-?([1-9][0-9]{0,6})(?:-(?:review|check|new|[0-9]+))?$`. Group 1 is the PR number. This covers all 44 measured names, including `pr1830-809`, which maps to #1830 because the leading number wins. Any other `pr…` name, such as `pr-7-foo`, is not D4 and gets the legacy rules.

**Order:** D4 is evaluated in `_decide_rest` **after D3** and before the KEEP table. As a result:
- N1–N5 and G1 are unchanged and apply first. That includes `open-pr` by `head.ref`.
- Landed review branches keep the more informative `landed-*` reasons.

**Precondition (A1):** D4 applies only when the ref is **not the `head.ref` of any PR** (the same-repo `head.ref` index has no entry for the name; in code, `plan["prs"]` is empty). A real PR head literally named `pr-7` or `pr-123-review` therefore keeps TD-2286 semantics completely: D1, D1', D3, then the legacy KEEP table (for example `unlanded-pr-sha-mismatch`). It is never reinterpreted as a review copy of a different-numbered PR. D4 is a rule for names nobody opened a PR from, and only those.

**PR index:** a second index over the **same** `pulls("all")` listing, keyed by `number`. It accepts any head repo, because a fork PR's head is still stored at `refs/pull/N/head` in this repo. It adds no API calls. A number missing from the listing is not treated as closed (TD-2286 A3 reasoning).

| # | Condition (the ref matches `REVIEW_RE` and reached D4) | Outcome | `pr=` |
|---|---|---|---|
| D4-u | PR #N is not in the listing | KEEP `review-pr-unknown` | – |
| D4-s | `_covers(PR #N, tip)` is false. The tip has commits beyond the PR head, or the head object is not local. | KEEP `review-pr-sha-mismatch` | – |
| D4-g | N6 (§4.2) fires | KEEP `audit-content` | – |
| D4-d | PR #N `state == closed`, whether merged or not and whatever its base | **REAP `review-pr-done`** | `#N` |
| D4-o | PR #N `state == open`. G1 has already passed, so the age is ≥ grace. | **REAP `review-stale`** | `#N` |

**Why this is safe:**
- D4 requires that the PR head covers the tip, so every local commit is in the PR. This is what makes name collisions harmless: whatever the name was meant to mean, a branch is deleted only when PR #N's current head contains every one of its commits. Authorship is deliberately not checked; containment is the stronger property.
- GitHub keeps `refs/pull/N/head` for open, closed and merged PRs, so the content stays recoverable without #2293. The `tip=` SHA also goes into a durable audit event (§6.2).
- D4-o deletes only a copy of a PR head that has not been touched for 7 days. The overseer can re-materialize it with §2 whenever it needs to.
- N3 and N4 still protect a branch that is checked out.

D4 applies in every clone. The Worker clone has 0 matching names today.

## 4. Audit records are never deleted in this slice (issue item 3)

### 4.1 N2a: audit-branch names (always KEEP)

N2a is evaluated right after N2 and before G1, so it costs no API calls. It matches `chore/audit-overseer-cycle-*` and `chore/overseer-audit-*`, and the outcome is KEEP `audit-branch`.

`audit/*` stays under N2 as `protected-name`. TD-2286's output for it is unchanged.

The patterns match exact prefixes, not the substring "audit". The Worker clone has about 25 branches with "audit" in the name, such as `worker-1517-audit-sync-liveness-*`. Those are ordinary feature branches and must stay reapable.

### 4.2 N6: record-path content guard (defence in depth, every clone)

N6 runs before any **unlanded** deletion: D1' (local or remote), D2 and D4-d/D4-o.
- Compute `mb = git merge-base <base> <tip>`.
- If `git diff --name-only <mb> <tip> -- audit/log audit/oversight-log.jsonl audit/overnight-loop-log.md` is non-empty, the outcome is KEEP `audit-content`.
- If either git call fails, the outcome is KEEP `git-error`.

N6 does not apply to D1 (a merged PR into `main` that covers the tip) or to D3 (ancestor or identical content). In both cases the records are on main.

**Effect:** audit records on a branch with any name are deleted only when they have provably landed. Unsynced audit branches stay KEEP whatever their PR or issue state. That holds for the 29 measured unsynced branches, and for any future branch that adds records.

### 4.3 Deletion of audit branches is out of scope here

No rule in this slice deletes an N2a, N2 `audit/*` or N6 branch. The deterministic check (§5) is **not built in this slice** (A9). The slice that deletes audit branches builds it as its deletion gate, after the §10 ruling.

## 5. Deterministic audit check: `readopt.py audit-branches` (read-only) — DEFERRED, not built in this slice

**Architect ruling A9:** this section is a non-binding draft contract for the slice that deletes audit branches. Nothing below is implemented, tested or attached in #2287. Reasons: it gates no decision in this slice (N2/N2a keep every audit branch whatever it reports); the §1 probe already supplies the evidence the §10 question needs; and its exact semantics depend on the §10 ruling (under option B no sync check is needed at all, and under option A the definition of `synced` must match what the migration writes). That slice re-validates this draft against the ruling before building it.

```
python3 -m scripts.automation.readopt [--repo <path>] audit-branches [--branch <name>]
```

**Scope:** every local branch that matches N2 `audit/*` or N2a, or the single branch given with `--branch`.

**References:** `origin/audit-log` and `origin/main`, as already fetched. The subcommand does not fetch. If `origin/audit-log` does not resolve, it prints `WARN: origin/audit-log missing — comparing against origin/main only`.

For each branch, let `mb = merge-base(origin/main, tip)`, then count:

| Count | Rule |
|---|---|
| `records` | (a) each `audit/log/**` path the branch adds (`A`) relative to `mb`; plus (b) each non-empty `+` line in `git diff --unified=0 <mb> <tip> -- audit/oversight-log.jsonl` |
| `present` | (a) the same path on either reference has the identical blob OID. (b) The line parses as a JSON object with a `timestamp` that `normalize_ts` accepts, and `audit/log/<record_relpath(event, ts)>` on either reference has blob OID equal to `git hash-object` of `canonical_bytes(event)`. |
| `unparseable` | A (b) line that fails to parse |
| `missing` | `records − present − unparseable` |
| `other` | Any `M`/`D` of an `audit/log/**` path (records are write-once), or any change to `audit/overnight-loop-log.md` |

**Output:**
- One line per branch: `AUDIT branch=<b> verdict=synced|unsynced records=<n> present=<n> missing=<n> unparseable=<n> other=<n> tip=<sha40>`.
- `verdict=synced` if and only if `missing == unparseable == other == 0`.
- A last line: `SUMMARY synced=<n> unsynced=<n>`.

**Exit codes:** 0, or 2 on a git error. It makes no ref, file or network changes, and no GitHub calls.

`audit_log` is imported lazily, inside this subcommand only.

**Trustworthiness:** a record path is content-addressed (a sha256 prefix of the canonical bytes) and the comparison is by blob OID. So `present` means byte-identical content on the reference, not just a matching name. The check is conservative: an unparseable line or a modified record counts against `synced`. It reproduces the §1 numbers.

## 6. Overseer wiring in `bin/hos-cron`

### 6.1 Placement

The new block is an `if [[ "$ROLE" == "overseer" && -f "$REPO_ROOT/scripts/automation/readopt.py" ]]` block, placed next to the worker `reap-landed` block. That puts it after `fetch origin --prune` and the #1044 return-to-main, and before Claude is invoked. Cycles that exit early with no actionable PRs do not run it. That is acceptable because of the daily cadence.

### 6.2 Mode, cadence, bound, output

| Item | Contract |
|---|---|
| Mode | `HOS_OVERSEER_BRANCH_REAP` env, then `<project>_overseer_branch_reap` (via `_conf_val`), then default **`dry-run`**. Allowed values are `off`, `dry-run` and `on`. An invalid value means `off`, plus `WARN` and `_audit cycle-branch-reap-config-invalid value=<v>` (the same shape as the #1415 hygiene config handling). `projects.conf` is operator-owned. No agent sets it. |
| Cadence | Once per 24 h, gated by the stamp `$_HOS_DIR/branch-reap/overseer-${PROJECT}.last` (directory created with `mkdir -p`; a stamp that cannot be written is a WARN, and the block then runs again next cycle — bounded, read-mostly, acceptable). The stamp is written after **every** attempt, including failures, so a failing API cannot cost about 35 calls per cycle. A failure prints a WARN and retries the next day. |
| Command | `python3 -u -m scripts.automation.readopt reap-orphans --local-only --max-deletions 100`, with `--dry-run` added unless the mode is `on`. `--local-only` is required: the overseer never deletes remote heads, which belong to the worker under its own identity (#2286). The worker's remote `worker-*` heads stay with #2286 slice 2 and #2288. Grace is TD-2286's default of 7 days. |
| Bound | Its own `_RB_BOUND=(timeout --kill-after=10 300)` (or `gtimeout`). It is not shared with `reap-landed`'s 120 s. Estimate for the first run: about 95 branches × 4 git calls (about 5 s), ≤ 13 PR pages, ≤ 20 per-issue reads (3 `worker-N` branches plus their `#refs`) and 1 open re-check, so ≤ 34 calls at 1–2 s each, about 70 s. **Steady state after cleanup:** only N2/N2a/N3 branches remain, nothing is pending, TD-2286 A9's short-circuit applies, and the run makes **0 API calls**. |
| Log | Every output line is echoed as `$LOG_PREFIX readopt-overseer: <line>`. That gives one cycle-log line per REAPED, REAP-FAILED, WOULD-REAP, DEFERRED and KEEP decision (KEEP only in dry-run). #2282 consumes these. |
| Audit | `_RB_EVENT_RE='^(REAPED\|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=([a-z-]+) where=(local\|remote)( pr=(#[0-9]+\|-))? tip=([0-9a-f]{40})$'` is anchored, as the CWE-117 guard requires. Each `\|` here is a Markdown table escape for a plain `|`; the regex itself contains no backslashes. Capture groups (A10): `BASH_REMATCH[1]` kind, `[2]` branch, `[3]` reason, `[4]` where, `[6]` pr (empty when absent, as on `REAP-FAILED`), `[7]` tip. A match produces `_audit cycle-branch-reap` (or `…-failed`) with `role=overseer branch=<b> reason=<r> where=<w> pr=<pr or -> tip=<sha>`. The `pr=` field is the handle for recovery from `refs/pull/<N>/head`. These records sync to `audit-log`, which gives every deleted tip a durable recovery handle. #2313 adds: a dry run writes one `cycle-branch-reap-dry-run` event (`would_reap`, `would_local`, `would_remote`, `kept`, `aborted`, `items`), and a `WARN: git-error KEEPs=<n> exceeds <t> — first stderr: …` line from `readopt.py` writes `cycle-branch-reap-git-error` (`count`, `threshold`, `cause`). |
| Failure | Output lines are parsed and audited on **both** paths, including rc 124/137 (A10), exactly as the worker `reap-landed` block does, so a REAPED line printed before a timeout kill is still audited. Then, if rc ≠ 0: `WARN: readopt reap-orphans (overseer) failed (rc=<n>[ timeout]) — continuing`. The engine guarantees zero deletions on any listing failure (TD-2286 §1.2). The block never exits the cycle. |

### 6.3 Cycle-end safety net

Placement: unconditionally for `ROLE == overseer`, right before `_sync_audit_logs "$REPO_ROOT"`, so it also runs after a failed or timed-out Claude run.

Command: `bash "$REPO_ROOT/bootstrap/review_worktree.sh" --repo "$REPO_ROOT" --cleanup-all --older-than-mins 60`, bounded by `timeout 60`.

Each `REMOVED-WORKTREE` line (stdout) and `KEPT-WORKTREE` line (stderr; A3) is echoed to the cycle log, and `_audit cycle-review-worktree-cleanup removed=<n> kept=<k>` is written when n + k > 0, plus one `cycle-review-worktree-kept pr=<n> path=<sanitized, capped> reason=<r>` per kept worktree (#2313, anchored regex). A `kept` count above 0 means a commit was made in a review worktree, which the overseer must never do (A8); a human inspects it.

The 60-minute floor protects a concurrent interactive overseer session in the same clone. A missed cleanup from the cycle therefore lingers until the next cycle that comes at least 60 minutes later. This is fail-open hygiene.

### 6.4 First-run precondition and dependencies

- **Human-reviewed dry run:** the PR attaches the full output of `python3 -m scripts.automation.readopt --repo <Overseer clone> reap-orphans --local-only --dry-run`, run from the PR branch. It is read-only. After merge, wiring stays in `dry-run` and logs a daily WOULD-REAP set. **No agent flips the mode.**
- **First real run is attended, then `on` (A2; reconciles TD-2286 §9.1 and its "do not merge slice 2's cron wiring before a human has reviewed slice 1's first real run").** Merging this wiring is allowed because in its default `dry-run` mode it deletes nothing unattended, which is the hazard TD-2286's condition guards. Deletion is enabled in this order only:
  1. A human runs the real command once, attended, in their own terminal (never an agent session; CLAUDE.md "Never invoke `bin/hos-cron` yourself" applies by analogy): `python3 -m scripts.automation.readopt --repo <Overseer clone> reap-orphans --local-only --max-deletions 100` from a main checkout that contains this slice, and reviews its REAPED lines against the attached dry run.
  2. Only after that does the human set the mode to `on`.
  The PR body states this order. The first unattended deleting run is therefore never the first deleting run of the extended engine. This slice does not depend on the Worker-clone run in TD-2286 §9.1: the overseer wiring is separate, and it cannot touch the Worker clone or remote heads.
- **#2293 (archive refs before unlanded deletes): independent.**
  - D4 deletions are recoverable from `refs/pull/N/head` plus the audited `tip=`.
  - The overseer clone's legacy D2 candidates (3 `worker-N` branches) carry TD-2286's accepted D2 residual, and every one of them is visible in the reviewed dry run.
  - When #2293 lands, its archive step covers D4 automatically, provided it hooks the shared delete path.

## 7. Files (14 of the 15 allowed; plan ≤ 6 commits)

| # | File | Change |
|---|---|---|
| 1 | `scripts/automation/readopt.py` | `REVIEW_RE` and D4 (with the A1 precondition), N2a, N6, docstring (Usage/Safety). No `audit-branches` subcommand and no `audit_log` import (A9). |
| 2 | `bootstrap/review_worktree.sh` | new (§2) |
| 3 | `bin/hos-cron` | §6.1–6.3 |
| 4 | `.claude/agents/overseer.md` | §2.3. Authored by the top-level session, not `coder` (#1347). |
| 5 | `bootstrap/overseer-cron-prompt.md` | §2.3 |
| 6 | `.claude/commands/hos-review-pr.md` | §2.3 |
| 7 | `tests/automation/test_readopt.py` | R1–R8, R10, R11 (R9 removed with A9) |
| 8 | `tests/automation/test_review_worktree.py` | new, C1–C10 |
| 9 | `tests/automation/test_hos_cron.py` | H1–H6 |
| 10 | `SCRIPTS-INDEX.md` | regenerate with `scripts/framework/regen_all.sh` |
| 11 | `prompts/bootstrap/review_worktree.md` | prompt artifact |
| 12 | `prompts/bin/hos-cron.v2287.md` | prompt artifact |
| 13 | `prompts/scripts/automation/readopt.v2287.md` | prompt artifact |
| 14 | this TD | |

`CLAUDE.md`'s canonical-entry-points table is **not** edited, because it would make 15 files. `overseer.md` is the authority for overseer behaviour. A one-row follow-up can be filed later.

## 8. Tests (pytest; real temp repos via TD-2286's `repo` fixture; fake `pulls` and `issue_states`)

**`test_readopt.py`**

| # | Test | Expect |
|---|---|---|
| R1 | `pr-7-review`, `pr7`, `pr7-check`, `pr-7-new` and `pr7-12`, all aged and at tip == PR #7 `head.sha` (`head.ref=worker-x`, merged) | Each REAPED `review-pr-done pr=#7`, and the refs are gone |
| R2 | The same with PR #7 closed and unmerged; also with PR #7 merged into a non-main base | REAPED `review-pr-done` |
| R3 | PR #7 open, branch aged and covered; then the same within grace | REAPED `review-stale`; then KEEP `grace` |
| R4 | Tip beyond PR #7 head; PR #9 absent; `pr-7-foo` with no PR | KEEP `review-pr-sha-mismatch`; KEEP `review-pr-unknown`; `pr-7-foo` gets legacy KEEP `unlanded-no-pr` (not D4) |
| R5 | **Audit patterns are never touched.** For each of `audit/x`, `chore/audit-overseer-cycle-x` and `chore/overseer-audit-x`, build branches that would otherwise be reaped: landed-ancestor, landed-content, head.ref of a merged PR, head.ref of a closed PR, a `pr-`-style closed cover, and aged past grace. Run a real run, a run with `--max-deletions 1` and a dry run. | All are KEEP `protected-name` / `audit-branch`. The `refs/heads` snapshot is byte-identical before and after each run. No WOULD-REAP line names them. |
| R6 | N6: `fix/x` at a closed PR's head that adds `audit/log/2026/06/…json`; `fix/y` that modifies `audit/oversight-log.jsonl`; `worker-5-x` on closed issue 5 (D2) that adds a record; `pr-7-review` (D4-d) that adds a record; the same record content on a merged-into-main PR branch (D1) | The first four are KEEP `audit-content`. The D1 case is REAPED `pr-merged`. |
| R7 | `--dry-run` with D4 candidates | WOULD-REAP `review-pr-done`; no ref deleted |
| R8 | `pulls` raises with D4 candidates present | Exit 2, `aborted=1`, zero deletions |
| R9 | (removed: `audit-branches` deferred, A9) | – |
| R10 | A real-run `REAPED … reason=review-pr-done where=local pr=#7 tip=<sha>` line and a `REAP-FAILED` line | Both match `_RB_EVENT_RE`, copied verbatim from `bin/hos-cron` with a pointer comment (the TD-2286 T24 pattern), and the A10 group indices extract kind/branch/reason/where/pr/tip correctly |
| R11 | **Name collision (A1).** `pr-123-review` is the `head.ref` of closed, unmerged PR #456, has one commit beyond #456's head, and its tip is an ancestor of PR #123's head; also `pr-7` as the `head.ref` of open PR #9 | The first is the legacy KEEP `unlanded-pr-sha-mismatch` (never D4, never `review-pr-done`); the second is KEEP `open-pr` |

**`test_review_worktree.py`** (bare origin with `refs/pull/7/head` pushed into it)

| # | Test | Expect |
|---|---|---|
| C1 | **A review via `refs/pull/7/head` creates no branch** | Exit 0. `WORKTREE=` is under the test's `TMPDIR` and is detached at the SHA. The `for-each-ref refs/heads/` output is identical before and after. No ref other than `FETCH_HEAD` changes (`for-each-ref` over all refs). |
| C2 | `--cleanup --pr 7` | The worktree and its scratch dir are gone, `worktree list` shows only the main worktree, and `refs/heads` is unchanged |
| C3 | `--expect-sha` that does not match | Exit 4, no worktree, no scratch dir left |
| C4 | `--pr 0`, `--pr -1`, `--pr 7;x`, a missing or short `--expect-sha` | Exit 2 |
| C5 | Run `--pr 7` twice | Exactly one review worktree for PR 7 |
| C6 | `--cleanup-all` when a branch-holding worktree, a detached worktree outside the pattern, and review worktrees for PR 7 and PR 8 all exist | Only the PR 7 and PR 8 review worktrees are removed |
| C7 | `--cleanup-all --older-than-mins 60` with one fresh and one back-dated review worktree | Only the back-dated one is removed |
| C8 | **Commit guard (A3).** Make a commit inside a review worktree, then run `--cleanup --pr 7` and `--cleanup-all` | The worktree is kept, `KEPT-WORKTREE … reason=head-moved` is on stderr, the commit is still reachable from the worktree HEAD, exit 0 |
| C9 | **Scratch location (A6).** `TMPDIR` set to a directory inside the repo, and to a fake `/tmp/claude`-prefixed path (the prefix check is unit-tested by injecting the root) | Exit 5, nothing created, `refs/heads` unchanged |
| C10 | **Repo resolution (A5) and refmap (A4).** Run `--pr 8` with cwd inside the PR 7 review worktree; separately, configure `remote.origin.fetch` with `+refs/pull/*/head:refs/remotes/origin/pr/*` and run `--pr 7` | The PR 8 worktree is created under `TMPDIR`, not nested, and both are listed by the main worktree; with the extra refspec, `for-each-ref` over **all** refs is unchanged |

All of these run inside the `TMPDIR` that `tests/conftest.py` provides and must leave zero temp leaks.

**`test_hos_cron.py`** (behavioural through the existing `cron` fixture where it reaches the post-sync section; static otherwise)

| # | Test | Expect |
|---|---|---|
| H1 | Overseer role in default mode | `reap-orphans --local-only … --dry-run` is invoked; the stamp is written |
| H2 | Mode `on`, mode `off`, an invalid mode | No `--dry-run`; not invoked; not invoked plus WARN and a config-invalid audit event |
| H3 | Stamp younger than 24 h | Not invoked |
| H4 | Worker role | The overseer block is not invoked; the worker `reap-landed` block is unchanged |
| H5 | Overseer cycle end, including when the Claude exit is non-zero | `review_worktree.sh --cleanup-all --older-than-mins 60` is invoked before `_sync_audit_logs` |
| H6 | **Audit on the failure path (A10).** A stub `readopt` prints one `REAPED … pr=#7 tip=<sha>` line, then exits 124 | One `cycle-branch-reap` event with `role=overseer` and `pr=#7`, plus the timeout WARN |

## 9. Startup-gap and affected sign-offs

**Should this have been settled in TD-2286? Partly, yes.**
- N2 protected `audit/*` without inventorying the `chore/…` audit patterns, which exist only in the Overseer clone.
- N2 also had no content guard against unsynced records under other names.
- That is a `startup-artifact-gap` against TD-2286. I was told not to file or annotate issues, so the worker should annotate #2286 or #2285 with a pointer to §1 and §4 of this TD.

**No harm occurred:** slice 1 runs nowhere automatically, and the Worker clone has no branch that matches either chore pattern.

**Affected sign-offs:**
- TD-2286's sign-offs and slice 1's code review **stand**. N2a and N6 only turn some REAP outcomes into KEEP (two new KEEP reasons, `audit-branch` and `audit-content`), and D4 adds REAP outcomes only for names that reached slice 1's KEEP table and are no PR's `head.ref` (A1). No existing REAP becomes a different REAP, no KEEP becomes a REAP for any name outside `REVIEW_RE`, and the REAPED/KEEP line format is unchanged. (Corrected by A11: the earlier wording "no existing outcome changes" was inaccurate.)
- **Re-review needed:** the human review of TD-2286 §9.1's Worker-clone first real run, if it happens after this merges, must use a dry run taken with the extended engine.

## 10. Residual risks and the one human question

| # | Risk | Mitigation |
|---|---|---|
| R1 | Acceptance item 1 ("only main plus audit branches") may be partly unmet. D4-s/D4-u KEEPs (PR head object not local) and legacy `unlanded-no-pr` branches with human-authored commits (`feat/1035-…`, `fix/986-…`) are kept by the never-delete rule. | Same ruling as TD-2286 A10: the safety rule wins. The PR uses `Part of #2287` unless the dry run shows only `main` plus audit branches, and it lists every residual KEEP with its reason. |
| R2 | A PR force-pushed so that `refs/pull/N/head` no longer contains an old review tip | D4 needs `covers` against the **current** head, so an orphaned older tip is D4-s KEEP and never deleted |
| R3 | Up to 7 days of D4-o lag for review branches of open PRs | Accepted. §2 stops new ones from being created, so this only drains legacy branches. |
| R4 | A concurrent interactive session in the Overseer clone loses its review worktree | 60-minute floor (§6.3). A lost worktree can be recreated with one command. |
| R5 | The overseer might run scripts from an untrusted PR-head worktree with its token | Not introduced here: today's improvised branches already put PR-head code on disk, and in the main checkout. **Ruled by A8:** overseer.md requires HOS tooling to run from the main checkout's copy, with worktree paths as arguments; nothing is executed from a fork PR's worktree. Executing a same-repo PR's own tests stays current practice and is not decided here. |
| R6 | `FETCH_HEAD` is shared state | Pinned by the required `--expect-sha`. The overlap lock means one cron cycle per clone. |

**Human question (non-blocking for this slice; it gates the slice that deletes audit branches).** 29 Overseer audit branches hold about 1,270 pre-#888 overseer cycle events, appended to the retired `audit/oversight-log.jsonl` between 2026-06-22 and 06-28, that exist nowhere in `audit-log` or `main`. Another 94 lines cannot be parsed. What should happen to them?
- **A:** migrate them into `audit-log` through the existing canonical writer, using `scripts/migrate_audit_log_to_dir.sh` per branch. Lines it cannot parse need B. Then delete each branch once the deterministic check (§5, built in that slice) reports `synced`.
- **B:** discard them deliberately. Record the reason ("pre-#888 overseer cycle logs, never synced, superseded by per-entry records") as an audit event that names each branch and its tip SHA, then delete.
- **C:** keep them indefinitely, which also keeps them out of every reap.

Until this is ruled on, they stay KEEP under N2 and N2a. This slice is complete without the ruling.

## Architect review — round 1

**Reviewer:** architect. **Date:** 2026-11-08. **Inputs:** this TD; TD-2286; `scripts/automation/readopt.py` (`reap_orphans`, `_decide_rest`, `_covers`, `_index_pulls`, `_fmt`); `bin/hos-cron` (overseer pre-filter ~1507–1565, worker `reap-landed` block ~1711–1740, cycle end ~2377–2608); `.claude/agents/overseer.md` "Shell usage (both modes)" and the #1217 inner-loop paragraph; `docs/SANDBOX-POLICY.md` §`sandbox.filesystem`.

Every amendment below is already applied in the body above, so the document reads self-consistently without this section. This section records why.

### What is right, and what could still go wrong

- **No local ref is created by §2.** The design avoids `gh pr checkout` and destination refspecs, pins to a required `--expect-sha`, and uses the existing `_sync_audit_logs` detached-worktree pattern. This is the right root-cause fix: the model improvised branches because no sanctioned path existed. What could still go wrong was an opportunistic remote-tracking update (A4), a nested worktree (A5), a worktree inside the repo tree (A6), and a silent fallback to branching when the script fails (A7). All four are closed.
- **D4's safety rests on `_covers`, not on the name.** I checked `_covers`: `head.sha == tip`, or the head object is local and `tip` is its ancestor. A tip with a single commit beyond the PR head is never covered, so a force-pushed PR orphaning an older review tip is KEEP (R2 in §10 is correct). Recovery from `refs/pull/N/head` is real for open, closed and merged PRs. The remaining name-semantics hole was a real PR head whose name matches `REVIEW_RE` (A1).
- **N2a and N6 close a real slice-1 gap.** I confirmed in `reap_orphans` that the protected-name check is `name in ("main", "audit-log") or name.startswith(("release/", "audit/"))`, so `chore/audit-overseer-cycle-*` is reapable by D1'/D3 today. The analysis in §1 is correct, and the startup-gap analysis in §9 is honest.
- **The output format is consistent with slice 1.** `_fmt` emits `KIND branch= reason= where=[ pr=] tip=`, with `pr=` only on REAP lines, and REAP-FAILED omits it. `_RB_EVENT_RE` with an optional `pr` group matches both. `_printable_name` percent-encodes unsafe names, but those are always KEEP `unsafe-name` and never reach a REAPED line, so `%` correctly does not need to be in the character class.

### Findings

| # | Severity | Finding | Resolution (applied) |
|---|---|---|---|
| A1 | MUST_FIX | **Name-collision data path in D4.** "Order" claimed that a real PR head named `pr-7` keeps TD-2286 semantics through D1 and D1'. That is false for the case that matters: a PR head with **unpushed local commits** is covered by no PR, so it fails D1 and D1', falls through D3, and reaches D4. There it would be judged against a *different* PR, the one whose number happens to be in its name. Containment in that PR's head still prevents content loss, but the rule silently reinterprets someone's branch, and with `review-stale` it could delete a real PR head's local copy because an unrelated open PR contains it. | §3 adds a precondition: D4 applies only when the name is no PR's `head.ref` (`plan["prs"]` empty). Test R11 is added. |
| A2 | MUST_FIX | **Conflict with binding TD-2286.** TD-2286's slice-split note says "do not merge slice 2's cron wiring before a human has reviewed slice 1's first real run (§9.1)". This TD declared itself independent of it. A dry-run attachment is not a real run, and once `on` is set the first deleting run of the extended engine would be unattended. | Merging the dry-run-default wiring is allowed, because in that mode it deletes nothing unattended, which is the hazard the condition guards. Enabling `on` requires a prior attended, human-run real invocation in the Overseer clone (§6.4). TD-2286's condition is thereby satisfied in substance for this clone. |
| A3 | MUST_FIX | **Overseer-authored commit loss in cleanup.** `git worktree remove --force` followed by `git worktree prune` destroys a commit made on a detached review worktree: no ref and no reflog survive. The brief asked about overseer-authored commits specifically, and this was the one route the design left open. | §2.1 writes `<scratch>/expected-head`. §2.2 refuses to remove a worktree whose HEAD differs from it (or whose marker is missing) and prints `KEPT-WORKTREE … reason=head-moved`. §6.3 audits a `kept` count. Test C8 is added. *Residual:* `tmp_reaper.py` will still delete such a directory after 24 h. That is accepted, because A8 forbids committing there and the `kept` audit event surfaces it to a human first. |
| A4 | SHOULD_FIX | **The "no ref of any kind" claim depended on config.** `git fetch origin <src>` with a configured `remote.origin.fetch` that matches `refs/pull/*` performs an opportunistic remote-tracking update. That violates C1's all-refs invariant, though not the `refs/heads` one. | `--refmap=` (empty) and `--no-recurse-submodules` are added to the fetch. Test C10 covers a configured pull refspec. |
| A5 | SHOULD_FIX | **`--repo` defaulted to `--show-toplevel` of the cwd.** Run from inside a review worktree, that resolves to the worktree itself: `--pr` nests a worktree, and `--cleanup` tries to remove its own cwd. | The script always operates on the main worktree, derived from `--git-common-dir`. Test C10 is added. |
| A6 | SHOULD_FIX | **"Worktrees never go in `.claudetmp/` or `/tmp/claude/`" was stated but not enforced.** `${TMPDIR:-/tmp}` honours whatever `TMPDIR` is, and sandboxed Bash without `CLAUDE_CODE_TMPDIR` sets it to `/tmp/claude`. | The script refuses (exit 5) a scratch root inside the repo or under `/tmp/claude`. Test C9 is added. |
| A7 | MUST_FIX | **No fail-closed instruction for script failure.** An LLM whose sanctioned path exits non-zero will improvise, and improvising a branch is the exact root cause of #2287. | overseer.md must say: on non-zero exit, review from API and diff only, disclose it in the verdict, never fall back to a branch, and treat exit 4 as "re-read head_sha" (§2.3). |
| A8 | MUST_FIX | **Ruling on R5: yes, HOS tooling runs from the main checkout.** Since #1217 the overseer re-runs gates, validators and reviewer checks on the PR. Running the PR head's copy of `run_gates.sh`, `run_validators.sh` or `python3 -m scripts.oversight…` (cwd in the worktree puts the PR's package first on `sys.path`) lets a PR that edits a gate grade itself. Today's improvised checkouts in the main checkout make that unavoidable; the separate worktree is what makes the rule enforceable now. | §2.3: run every HOS tool by its main-checkout path, with worktree paths as arguments. Never invoke by a worktree path, never `-m` with the worktree as cwd, never commit in the worktree, and execute nothing from a fork PR's worktree. Executing a same-repo PR's own tests remains current practice and is explicitly not decided here. **Product-boundary check:** this narrows a trust boundary. It changes no user-visible behaviour, cost, topology, retention or operational burden, so no PM or human checkpoint is required beyond the protected-surface human review that `overseer.md` already gets at merge. **Startup-gap check:** this should arguably have been settled when #1217 restored overseer re-runs. Nothing has been built or approved against a contrary rule, so no sign-offs are orphaned. The worker should note this on #2285 alongside the §9 note. |
| A9 | SHOULD_FIX | **Ruling on `audit-branches`: cut from this slice.** It gates no decision here, because N2/N2a keep every audit branch regardless. The §1 probe already gives the human the numbers for §10. And its definition of `synced` depends on the §10 answer (under B it is unnecessary; under A it must match what the migration writes). Building it now means code, an `audit_log` import and test R9 that may have to be redone. | §5 is kept only as a non-binding draft for the audit-deletion slice. It is removed from §4.3, §6.4, §7 and §8. The file count is unchanged (readopt.py is still touched), but the slice is smaller and has no speculative surface. |
| A10 | MUST_FIX | **Audit parsing on the failure path was unspecified.** On rc 124/137 after deletions, REAPED lines must still be audited, or the `tip=` recovery handle that §3's safety argument relies on is lost. The worker block does this ("Process the output on BOTH paths"); the overseer block must as well. The `pr=` field was also dropped from the audit event, although it is the `refs/pull/N/head` recovery key. | §6.2 states parse-on-both-paths, the `BASH_REMATCH` indices and `pr=` in the event. Test H6 is added, and R10 checks the indices. |
| A11 | NOTE | The "change class" and §9 wording said no existing outcome changes and that only REAP→KEEP occurs. D4 also turns some `unlanded-no-pr` KEEPs into REAPs. | Wording corrected in the header and §9. The sign-off conclusion (TD-2286 sign-offs stand) is unchanged and correct, because D4's new REAPs are confined to `REVIEW_RE` names that are no PR's head, and they are contained in a PR head. |
| A12 | NOTE | **N6 is correct and conservative.** It runs before every unlanded REAP (D1' local and remote, D2, D4), fails closed to `git-error`, and is skipped only for D1/D3, where the content is on `origin/main`. Its cost is over-keeping: a worker branch that ever committed an `audit/log` record is never reaped by D1'/D2. That is the right trade. One subtlety for the coder: insert N6 *before* the early `return` in the D1' branch of `_decide_rest`, and before the D2 `return`, not only before D4. | No change. Test R6 already covers D1', D2 and D4. |
| A13 | NOTE | **D4-d on a closed PR whose issue is still open** does not violate TD-2286 A1 ("never delete open-issue work on a closed PR"). A1 protects the worker's re-adoption branch. A `pr-N` copy is not that branch, and its content is in `refs/pull/N/head`. **Race:** a PR force-pushed between the listing and the CAS delete could make a deleted tip no longer contained. The window is seconds, the deletion is audited with `tip=`, and the objects stay in the local object store until gc. Accepted. | No change. |
| A14 | NOTE | **Cron.** The placement after the overseer pre-filter's early exits is acceptable at a daily cadence. Note that in `dry-run` nothing drains, so the ≈34 API calls per day persist until a human sets `on`. The "steady state 0 API calls" claim holds only after `on`. `--max-deletions 100` is accepted: it is effectively uncapped for about 95 branches, but every candidate is in the human-reviewed dry run and the attended first real run (A2), and deletions are local refs only (`--local-only`). The mode is operator-owned (`projects.conf`/cron env), and the overseer session cannot set it for a future cron cycle. | Stamp directory creation and the stamp-write failure path are specified in §6.2. |
| A15 | NOTE | **Sandbox callability verified.** Every agent-facing call is one command with literal arguments; the agent copies the printed `WORKTREE=` path literally. The script's own writes (`.git/FETCH_HEAD`, `.git/worktrees/`, objects) fall under the project-tree `allowWrite`, and the scratch falls under the role's own `.tmp/<RoleDir>` grant (SANDBOX-POLICY §`sandbox.filesystem`). `bin/hos-cron`'s own calls use variables, which is fine because they are not agent Bash calls. | No change. |
| A16 | NOTE | **Scope.** 14 of 15 files and ≤ 6 commits; within limits after A9. Nothing else should be cut: the script, D4, N2a/N6 and the dry-run wiring are each needed for the issue's acceptance or its safety. Deferring the CLAUDE.md entry-point row is acceptable, because overseer.md is the authority for overseer behaviour. | No change. |

### Affected sign-offs

None beyond §9. No design or code has been approved against any rule these findings change.

**Status: APPROVED** (all MUST_FIX findings resolved by the amendments above; iteration 1 of 5).
