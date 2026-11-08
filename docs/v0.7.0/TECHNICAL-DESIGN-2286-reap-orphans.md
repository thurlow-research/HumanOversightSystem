# TECHNICAL-DESIGN-2286: `readopt.py reap-orphans` and remote-head deletion in `prune-attempts` (#2286 slice 1, child of #2285)

**Status:** DRAFT, awaiting architect review (round 1).
**Binding input:** the #2286 issue body, which is the requirements spec. It was filed by a human and is `priority:critical`. There is no separate REQ or ADR document (spec proportionality, #2155), so this is the only design document for the chain.
**Change class:** additive. This adds a new subcommand and a new remote step after an existing local delete. No code was built against an earlier contract, so no sign-off is affected and there is no startup gap.
**Contract only.** This document contains no implementation.

## 0. Slicing

| Slice | Scope |
|---|---|
| **1 (this TD)** | A new `readopt.py reap-orphans` subcommand covering local branches and remote `worker-*` heads. `prune-attempts` also deletes the remote head of each attempt it deletes (issue item 3, the readopt part). New `github.py` list helpers. Tests. A one-paragraph doc touch to `worker.md` §"Re-adopting a stalled branch". |
| **2 (later cycle)** | See the sketch below. |

**Slice 2 sketch (out of scope here):**
- `bin/hos-cron` runs `reap-orphans` after `reap-landed`, inside the same `_RO_BOUND` timeout wrapper (`bin/hos-cron:1708-1740`). It parses `REAPED … where=` lines into audit events. It passes `--max-deletions`, and treats exit 2 as a WARN and continues.
- The bounce re-entry close path deletes the closed PR's head branch, local and remote, in the same step.
- Item 4: find out why 9 merged `worker-*` remote heads survived auto-delete. Candidates are a re-push after merge, `create_branch.sh --from`, and the merge path used. Then fix the cause.
- #2282's `hos_local_branches` and `hos_remote_stray_branches` metric.
- Non-worker remote heads belong to #2288 (the slice 3 janitor).

## 1. Data acquisition (decision 1)

All GitHub reads go through `scripts/automation/lib/github.py`. A run makes a fixed number of list calls. It does not make one call per branch.

### 1.1 New helpers in `github.py`

Each helper follows the `list_check_suites_for_ref` pattern:
- It fetches pages with `?per_page=100&page=N`.
- It stops at the first page with fewer than 100 items.
- If a page is not a list, it raises `ListTruncatedError`. A `None` result on page 1 is a 404, and the helper raises `GitHubError`.
- If more than `max_pages` pages are full, it raises `ListTruncatedError`.
- It never returns a partial list.

| Helper | Endpoint | Default `max_pages` |
|---|---|---|
| `list_all_pulls(owner, repo, *, state="all", max_pages=40)` | `/repos/{o}/{r}/pulls?state={state}&sort=created&direction=asc` | 40 |
| `list_all_issue_states(owner, repo, *, max_pages=60)` | `/repos/{o}/{r}/issues?state=all&sort=created&direction=asc` | 60 |

- **`list_all_pulls`** returns the raw PR objects.
- **`list_all_issue_states`** returns `{number: "open" | "closed"}`. It includes PR numbers, which is harmless because the map is keyed by number.
- **Sort order:** `direction=asc` means an item created during pagination is appended after the existing ones. It can never shift an existing item off a page. PRs and issues cannot be deleted, so no existing item can disappear from the listing. Something created after the listing finishes is younger than the grace period anyway (§2).
- **Existing helper:** `list_pulls` is unchanged.

### 1.2 Fail-closed rule

The run builds every decision before it deletes anything. If any listing raises, the run prints `WARN: listing failed — nothing deleted: <reason>` and `SUMMARY … aborted=1`, then exits 2 with zero deletions. A partial PR list could hide an open PR.

The listings are:
- the PR listing;
- the issue-state listing (lazy: fetched only if some `worker-<N>-*` branch reaches rule D2);
- the remote-head listing (§3);
- the open-PR re-check (§2.4).

**Remote-phase exception:** when only the remote-head listing fails, the local phase still runs and the remote phase is skipped with a WARN.

### 1.3 Other inputs

- **Repo slug:** parsed with `parse_remote_url(git remote get-url origin)`.
- **Base:** `origin/main` as already fetched. `reap-orphans` does not fetch. The caller (cron) has already fetched. A stale `origin/main` only makes rule D3 more conservative.
- **Tip SHAs:** from `for-each-ref refs/heads/`.

### 1.4 Testability

Each of the following is an injectable parameter of `reap_orphans`, with the production default in parentheses:
- `pulls` (`list_all_pulls`);
- `issue_states` (`list_all_issue_states`);
- `remote_heads` (§3.1);
- `remote_delete` (§3.2);
- `git`;
- `now`.

The same pattern already exists as `PrMergedLookup` and `IssueStateLookup`.

## 2. Per-branch decision table (decisions 2 and 5)

Rules are evaluated **in order**, and the first match wins. Each outcome has exactly one reason token.

**PR index:** PRs are indexed by `head.ref`. Only PRs whose `head.repo.full_name` equals the slug are used, so fork PRs never match. Every rule below that says "PR" means a same-repo PR from this index.

### 2.1 NEVER (always KEEP)

| # | Condition | Reason |
|---|---|---|
| N1 | The name is not matched by `^[A-Za-z0-9._/@+-]+$`, or it starts with `-`. This keeps output parseable by the cron regex and rejects option-like names. | `unsafe-name` |
| N2 | `main`, `audit-log`, `release/*`, `audit/*` | `protected-name` |
| N3 | The current branch (`_current_branch`) | `current-branch` |
| N4 | The branch is checked out in any worktree (`_checked_out_in_worktree`, which fails safe). | `worktree` |
| N5 | Any **open** PR has `head.ref` equal to the branch name. This holds even if a closed PR also matches. | `open-pr` |

### 2.2 Grace

| # | Condition | Reason |
|---|---|---|
| G1 | `age < grace` (default **7 days**) | `grace` |

**Age** is `now` minus the newest of these three timestamps:
- the tip committer date;
- the mtime of any ownership record for the branch;
- the newest reflog entry for `refs/heads/B` (`git log -g -1 --format=%ct`), if one exists.

The reflog term protects a branch that `create_branch.sh --from` re-created from an old commit. If no timestamp can be read, the outcome is KEEP with reason `git-error`.

### 2.3 DELETE (first match)

| # | Condition | Reason | `pr=` |
|---|---|---|---|
| D1 | A merged PR has `head.ref == B` **and** `head.sha == tip`. | `pr-merged` | `#n` |
| D1' | A closed, unmerged PR has `head.ref == B` **and** `head.sha == tip`. | `pr-closed` | `#n` |
| D2 | `B` matches `^worker-(\d+)-` and that issue's server state is `closed`. | `issue-closed` | `-` |
| D3a | `git merge-base --is-ancestor tip origin/main` exits 0. | `landed-ancestor` | `-` |
| D3b | `git merge-tree --write-tree origin/main tip` exits 0 **and** its first line equals `origin/main^{tree}`. | `landed-content` | `-` |

**Tip equality in D1 and D1'** means a local tip with commits beyond the PR head is never lost. The PR's commits stay recoverable through `refs/pull/<n>/head`.

**D3b and conflicts:** the content test is the same one as in `_branch_has_unlanded_work`. A conflict (exit 1) is **not** "landed". Any other exit code gives KEEP with reason `git-error`.

**D2** does not apply to legacy branches (`fix/*`, `feat/*`, `docs/*`, `worker/*`, and so on). They use N, G, D1, D1' and D3 only, keyed by PR head name.

### 2.4 Otherwise KEEP

| Situation | Reason |
|---|---|
| Some PR has `head.ref == B` but no PR's `head.sha` equals the tip. This covers escalated branches with an earlier bounced PR. | `unlanded-pr-sha-mismatch` |
| A `worker-<N>-*` branch whose issue is open | `unlanded-open-issue` |
| Anything else | `unlanded-no-pr` |

**No automatic supersession.** `reap-orphans` never applies the "newer attempt for the same issue" rule. That stays an explicit `prune-attempts [--keep]` decision. This keeps ~30 parked or escalated local-only branches on open issues untouched by design.

**Open-PR re-check:** immediately before the deletion phase, the run lists `list_all_pulls(state="open")` again. Any branch that is now an open-PR head is changed to KEEP `open-pr`. This closes the window between listing and deleting.

### 2.5 Deleting

- **Local:** a local delete uses the existing `_delete_branch(git, B, recs, tip)`. That is a compare-and-delete with `update-ref -d refs/heads/B <tip>`, plus a worktree re-check, plus record removal only after a successful delete. Records come from `read_records(store_dir(...))`.
- **Remote:** a remote delete has no record of its own.
- **Remote-only head with a local record:** the remote delete does not remove the record. Only a local delete does.

## 3. Remote `worker-*` heads (decision 3)

Slice 1 scope is only remote heads matching `refs/heads/worker-*`. Each remote head goes through the same table as a local branch, with these differences:
- the **tip** is the remote SHA;
- N3 and N4 do not apply;
- G1 age uses the committer date of the remote tip only.

**Missing objects:** if the remote tip object is not present locally (`git cat-file -e <sha>^{commit}` fails), the outcome is KEEP with reason `remote-tip-not-local`. The run does not fetch extra objects. Cron's `git fetch origin` normally brings them in.

**Independence:** local and remote decisions for the same name are made independently. For example, the local branch may be KEEP with `unlanded-pr-sha-mismatch` while the remote head is REAP with `pr-closed`, because their tips differ.

### 3.1 Listing remote heads

`git ls-remote <url> 'refs/heads/worker-*'` returns one authoritative read with no pagination. Here `<url>` is the **origin URL exactly as configured** (`git remote get-url origin`). This means:
- tests need no injection seam, because their `origin` is a local bare repo (the `repo` fixture in `tests/automation/test_readopt.py`);
- production uses `https://github.com/<slug>.git`.

### 3.2 Compare-and-swap delete

The remote delete is:

```
git push --porcelain --force-with-lease=refs/heads/B:<sha> <url> :refs/heads/B
```

- The expected old OID is sent in the receive-pack update command, so the server rejects the update if the ref has moved. That makes this a true CAS.
- A rejected push, or a non-zero rc, gives `REAP-FAILED … where=remote reason=cas-or-push-failed` and does not count as a deletion.
- **Rejected alternative:** a REST `GET ref` followed by `DELETE`. It is not atomic, because the ref can move between the two calls.

### 3.3 Token handling (CWE-532)

The token must **never** appear in argv, in the URL, in printed output, or in exception text. This differs from `submit_pr.sh:388`, which puts the token in the URL.

**Auth for an `https://github.com/` URL:** the git subprocess gets auth through its **environment only**:
- `GIT_CONFIG_COUNT=1`;
- `GIT_CONFIG_KEY_0=http.https://github.com/.extraheader`;
- `GIT_CONFIG_VALUE_0=AUTHORIZATION: basic <base64("x-access-token:" + GH_TOKEN)>`;
- `GIT_TERMINAL_PROMPT=0`, so missing credentials fail instead of hanging.

**Missing token:** if `GH_TOKEN` is unset for a github.com URL, the run prints `WARN: GH_TOKEN unset — remote phase skipped` and makes no remote calls. Any other URL scheme (the test bare repo, ssh) gets no auth environment.

**Output sanitizing:** all remote stderr and exception text passes through a new `_redact(text)` and then `_one_line` before printing. `_redact` replaces both the token literal and its base64 header form with `***`.

**Subprocess runner:** remote git calls use a new runner, `make_git_remote(repo, extra_env)`. It has the same `(rc, stdout)` signature and its own `timeout=60`. A timeout is reported as rc 124, and an rc of 124 is treated as a failure.

## 4. CLI and output (decision 4)

```
python3 -m scripts.automation.readopt reap-orphans [--dry-run] [--grace-days 7]
    [--local-only | --remote-only] [--max-deletions N]
```

**Argument validation:**
- `--grace-days` is an integer ≥ 0.
- `--max-deletions` is an integer ≥ 0, and 0 means no cap (the default). When the cap is reached, the remaining DELETE decisions are printed as `DEFERRED` and are not executed.
- The two `--*-only` flags are mutually exclusive in argparse.

**Output lines:**

| When | Line |
|---|---|
| Dry-run, every branch considered | `KEEP branch=<b> where=local\|remote reason=<r>` or `WOULD-REAP branch=<b> where=… reason=<r> pr=#<n>\|-` |
| Real run, each deletion | `REAPED branch=<b> where=local\|remote reason=<r> pr=#<n>\|-` |
| Real run, a failed deletion | `REAP-FAILED branch=<b> where=… reason=<delete-failed\|cas-or-push-failed>` |
| Always, last line | `SUMMARY reaped_local=<n> reaped_remote=<n> kept=<n> failed=<n> deferred=<n> api_calls=<n> aborted=0\|1` |

- A real run does not print KEEP lines, which keeps the cron log small.
- Every interpolated value is a branch name that passed N1, a fixed reason token, an integer, or `_one_line(_redact(...))` text in WARN lines. Nothing else is interpolated (CWE-117).
- The line shape stays compatible with `_RO_EVENT_RE` in `bin/hos-cron:1719`, which slice 2 extends to capture `where=`.

**Exit codes:**
- **0:** the run completed, including runs with KEEP, WARN or REAP-FAILED lines.
- **2:** a listing failure (nothing deleted), a `GitError` resolving the store or slug, or a usage error.

The module docstring's Subcommands, Usage and Safety text is updated. The line "unrecorded leftover branches … never touched here" becomes scoped to `reap-landed`.

## 5. `prune-attempts` remote delete (decision 6)

**When it runs:** after each **successful** local `_delete_branch` of attempt `B` with tip `T`. It is not run on `--dry-run` and not run for skipped branches.

**What it does:**
1. Make one `ls-remote <url> refs/heads/worker-<issue>-*` call per invocation, done lazily on the first local delete.
2. If the remote has `refs/heads/B` at SHA `T`, check `list_pulls(owner, repo, head=f"{owner}:{B}", state="open")`. This existing helper costs one call per candidate, and the candidates are few.
3. If the check returns no open PR, run the §3.2 CAS push.

**Output and failure handling:**
- Success prints `DELETED branch=B where=remote`.
- A dry-run prints `WOULD-DELETE branch=B where=remote` when the remote head exists at the local tip. That is a read only, and the open-PR check is skipped.
- Each of the following prints a WARN and **never** fails or undoes the local delete, and the exit code stays 0:
  - the remote SHA differs from `T` (`remote head moved`);
  - there is an open PR;
  - a lookup or push fails;
  - the token is missing.
- The existing local `DELETED branch=B` / `WOULD-DELETE branch=B` lines are unchanged for back-compat. The remote lines are additional.

## 6. Runtime and API budget (decision 7)

Measured clone: 382 local branches, 22 remote heads, about 2,300 issues and PRs.

**GitHub REST calls:**

| Call | Count |
|---|---|
| PR listing (about 1,100 PRs) | ≤ 12 |
| Issue-state listing | ≤ 24 |
| Open-PR re-check | 1 |
| **Total** | **≤ 37 per run** |

The page caps (40 and 60) fail closed at about 1.7× current size. Raising a cap is a one-line change, and a run that hits a cap deletes nothing.

**git calls:** about 4 local calls per branch (rev-parse, reflog, is-ancestor, merge-tree), so about 1,500 local calls in roughly 20–40 s. There is also 1 `ls-remote` and at most 18 pushes, each capped at 60 s. Slice 2 wraps the whole command in `_RO_BOUND`. Ordering that matters under a kill:
- No deletion happens before every listing has completed.
- Local deletes run before remote ones.
- A kill mid-delete leaves at worst some branches undeleted.

## 7. Files (decision 9)

| File | Change |
|---|---|
| `scripts/automation/readopt.py` | `reap_orphans`, `make_git_remote`, `_redact`, a remote step in `prune_attempts`, CLI, docstring |
| `scripts/automation/lib/github.py` | `list_all_pulls`, `list_all_issue_states` |
| `tests/automation/test_readopt.py` | the §8 tests |
| `tests/automation/test_github.py` | pagination, truncation and non-list tests for the two helpers (mock `_run_gh`) |
| `.claude/agents/worker.md` | step 7 of §"Re-adopting a stalled branch" (see below) |
| this TD | |

**`worker.md` change:** step 7 gains one sentence. `readopt reap-orphans` (human-authorized by #2286) also covers unrecorded branches and remote `worker-*` heads by PR, issue and content state after a 7-day grace. It never touches open-PR heads or unlanded work on open issues. This is a protected surface, so the edit is authored by the top-level worker session, not `coder` (CLAUDE.md, #1347).

## 8. Test plan (decision 8)

**Setup:** real temp repos built with the existing `repo` fixture, whose `origin` is a local bare repo. Remote heads are created with `git push origin <b>`. PR and issue data come from fake `pulls` and `issue_states` callables. `now` is injected to place branches outside the grace period.

| # | Test (issue acceptance item) | Expect |
|---|---|---|
| T1 | Current branch, a branch checked out in another worktree, `main`, `audit-log`, `release/x` (skips the current branch) | KEEP with the N-reason, all still exist |
| T2 | A branch that is an open-PR head, also with a closed PR on the same ref (skips open-PR heads) | KEEP `open-pr`, local and remote |
| T3 | Merged PR with `head.sha == tip`, local and remote (deletes merged-PR branches) | REAPED `pr-merged` for both `where=` values, record removed |
| T4 | Closed unmerged PR with `head.sha == tip` (deletes closed-PR branches) | REAPED `pr-closed` |
| T5 | Ancestor of main; squash-landed content with no PR (deletes landed branches) | `landed-ancestor`; `landed-content` |
| T6 | `worker-<N>-x` where N is closed, with unlanded content | REAPED `issue-closed`; a legacy `fix/x` with no PR stays KEEP `unlanded-no-pr` |
| T7 | Tip has a commit beyond the merged PR's `head.sha` | KEEP `unlanded-pr-sha-mismatch` |
| T8 | A conflicting stale branch on an open issue with no PR | KEEP `unlanded-open-issue` (merge-tree exit 1 is not landed) |
| T9 | Inside the grace period: a young tip, or an old tip with a fresh record or a fresh reflog | KEEP `grace` |
| T10 | `--dry-run` (`--dry-run` deletes nothing) | Every branch has a KEEP or WOULD-REAP line, and the ref sets on both sides are unchanged |
| T11 | `pulls` raises, `issue_states` raises, or the open re-check raises | Exit 2, `aborted=1`, zero refs deleted |
| T12 | The remote head moves between listing and push (CAS) | REAP-FAILED `cas-or-push-failed`, remote ref still at its new SHA |
| T13 | Token is never printed: `GH_TOKEN=SENTINEL` is set; a fake remote runner returns stderr containing `SENTINEL` and its base64 form; the remote URL is a fake `https://github.com/o/r.git` | `SENTINEL` and its base64 never appear in captured stdout or stderr, nor in the argv passed to the runner. The auth environment is present for github.com and absent for the bare-repo URL |
| T14 | `prune-attempts` on a superseded attempt with a remote head at the same tip (a superseded PR leaves no head branch) | Local and remote both gone, plus `DELETED … where=remote`. When the remote is at a different SHA: WARN, remote kept, local still deleted, exit 0 |
| T15 | `--max-deletions 1` with 3 candidates | 1 REAPED, 2 DEFERRED |
| T16 | `--local-only` / `--remote-only` | The other side is untouched; giving both flags exits 2 |
| T17 | Names that fail N1, such as an option-like `-x` | KEEP `unsafe-name`; no git argument starts with `-` |

The issue's **selector check** (a `select_work_candidates` dry run before and after) is PR evidence, not a unit test. Squash-landed attempts whose content conflicts with today's main are removed by D1 (merged PR at tip). Any that remain, because their tip is past the PR head, stay KEEP and are listed in the dry run.

## 9. Residual risk

1. **The first real run deletes about 300 local branches.** It happens the first time a human (or slice 2's cron) runs `reap-orphans` without `--dry-run`. The PR **must** attach the full dry-run output from the Worker clone, every KEEP and WOULD-REAP line, so a human reviews the delete set before merge. Slice 1 does not wire the subcommand into cron.
2. **D2 can delete local-only unlanded work.** It deletes `worker-<N>-*` branches with unlanded, never-pushed work on a **closed** issue. The issue requires this, and the existing `prune-attempts --issue-closed` already does the same. Once deleted, that work is unrecoverable except through the reflog or gc window. The dry run makes it visible.
3. **Recovery for D1 and D1' deletions.** Content deleted under D1 or D1' remains at `refs/pull/<n>/head`.
4. **Protected surfaces.** `.claude/agents/worker.md` puts this PR on a protected surface, so it gets human review at merge.

No open question needs a human ruling for slice 1.
