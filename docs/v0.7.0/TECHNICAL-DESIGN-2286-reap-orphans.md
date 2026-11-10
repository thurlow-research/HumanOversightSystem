# TECHNICAL-DESIGN-2286: `readopt.py reap-orphans` and remote-head deletion in `prune-attempts` (#2286 slice 1, child of #2285)

**Status:** APPROVED (architect, round 1, 2026-11-08), with the binding edits listed in §10 "Architect review" applied in place. §10 wins over any text it amends.
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
- **Sort order:** `direction=asc` means an item created during pagination is appended after the existing ones. It can never shift an existing item off a page. PRs cannot be deleted or transferred, so no PR can disappear from the PR listing. Something created after the listing finishes is younger than the grace period anyway (§2).
- **Issues can disappear** (an admin delete or a transfer), which shifts later items left by one and can skip one item. A skipped or missing number is therefore never treated as closed: a `worker-<N>-*` branch whose N is absent from the map is KEEP `issue-unknown` (§2.4, architect edit A3).
- **Empty PR listing is an error (architect edit A4):** `list_all_pulls(state="all")` returning zero items raises `ListTruncatedError`. This repo always has PRs, and an empty list would silently disable N5 and D1.
- **Existing helper:** `list_pulls` is unchanged.

### 1.2 Fail-closed rule

The run builds every decision before it deletes anything. If any listing raises, the run prints `WARN: listing failed — nothing deleted: <reason>` and `SUMMARY … aborted=1`, then exits 2 with zero deletions. A partial PR list could hide an open PR.

The listings are:
- the PR listing;
- the issue-state listing (lazy: fetched only if some `worker-<N>-*` branch reaches rule D1' or D2);
- the remote-head listing (§3);
- the open-PR re-check (§2.4).

**Remote-phase exception:** when only the remote-head listing fails, the local phase still runs and the remote phase is skipped with a WARN. The PR, issue-state and open-PR re-check listings have no such exception: any of them failing aborts both phases.

**API economy (architect edit A9):**
- **No-candidate short-circuit:** if, after N1–N4 and G1 are evaluated locally for every local branch and every remote head, no branch is left to decide, the run makes **zero** GitHub calls and prints `SUMMARY … api_calls=0`. N5 needs the PR listing, so this applies only when nothing at all is left.
- **Issue states:** count the distinct issue numbers needed, meaning the branch issue numbers that reach D1' or D2 plus every A2 `#ref` from those D2 candidates' commits. When that count is 20 or fewer, read them with per-issue `get_issue` calls. Otherwise use `list_all_issue_states`. Any failure aborts the run either way. A `None` (404) result means `issue-unknown`, which is KEEP.
- **Steady state is not free:** the ~30 parked branches on open issues stay outside the grace window and need N5, so every run after the first still costs about 12 PR pages plus up to 20 issue reads. Slice 2 must pick the cron cadence and bound from the dry run's measured `api_calls` and wall time. Running it once per N cycles, gated by a stamp, is acceptable.

### 1.3 Other inputs

- **Repo slug:** parsed with `parse_remote_url(git remote get-url origin)`. It is resolved only when a production default helper needs it. Tests inject `slug` (§1.4), because their `origin` is a local bare path that `parse_remote_url` cannot parse.
- **Base:** `origin/main` as already fetched. `reap-orphans` does not fetch. The caller (cron) has already fetched. A stale `origin/main` only makes rule D3 more conservative.
- **Tip SHAs:** from `for-each-ref refs/heads/`.

### 1.4 Testability

Each of the following is an injectable parameter of `reap_orphans`, with the production default in parentheses:
- `pulls` (`list_all_pulls`);
- `issue_states` (`list_all_issue_states`);
- `remote_heads` (§3.1);
- `remote_delete` (§3.2);
- `git`;
- `now`;
- `slug` (parsed from origin, §1.3).

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
| D1 | A merged PR with `base.ref == "main"` has `head.ref == B` **and** its `head.sha` *covers* the tip (see below). | `pr-merged` | `#n` |
| D1' | A closed, unmerged PR has `head.ref == B` **and** its `head.sha` covers the tip. **Local side only:** a `worker-<N>-*` branch whose issue N is open (or unknown) does not match D1'. It falls through, and normally ends as KEEP `closed-pr-open-issue` (A1). | `pr-closed` | `#n` |
| D2 | `B` matches `^worker-(\d+)-`, issue N's server state is `closed`, **and** every `#<digits>` issue reference in the subjects and bodies of `git log origin/main..tip` is also `closed` in the state map (A2). A reference that is open or missing from the map blocks D2, with KEEP reason `issue-closed-batch-open`. | `issue-closed` | `-` |
| D3a | `git merge-base --is-ancestor tip origin/main` exits 0. | `landed-ancestor` | `-` |
| D3b | `git merge-tree --write-tree origin/main tip` exits 0 **and** its first line equals `origin/main^{tree}`. | `landed-content` | `-` |

**"Covers" in D1 and D1'** means one of two things (architect edit A5):
- `head.sha == tip`; or
- the `head.sha` object is present locally (`cat-file -e <sha>^{commit}`) and `git merge-base --is-ancestor tip head.sha` exits 0. That is, the local tip is behind the PR head, so every local commit is in the PR.

A local tip with commits beyond the PR head never matches, so it is never lost. The PR's commits stay recoverable through `refs/pull/<n>/head`. The ancestor form adds no API calls. It catches attempts that were pushed further than the local tip before a squash-merge, which is the selector mis-rank case. **`base.ref == "main"`:** a PR merged into another branch has not landed. It falls through to D3.

**D3b and conflicts:** the content test is the same one as in `_branch_has_unlanded_work`. A conflict (exit 1) is **not** "landed". Any other exit code gives KEEP with reason `git-error`.

**D2** does not apply to legacy branches (`fix/*`, `feat/*`, `docs/*`, `worker/*`, and so on). They use N, G, D1, D1' and D3 only, keyed by PR head name.

### 2.4 Otherwise KEEP

| Situation | Reason |
|---|---|
| A local `worker-<N>-*` branch on an open or unknown issue whose tip is covered by a closed, unmerged PR (A1: the never-delete rule for open-issue work beats the closed-PR rule. Supersession stays with `prune-attempts` and slice 2's bounce close path.) | `closed-pr-open-issue` |
| Some PR has `head.ref == B` but no PR's `head.sha` covers the tip. This covers escalated branches with an earlier bounced PR. | `unlanded-pr-sha-mismatch` |
| D2 blocked by a batched open or missing reference (A2) | `issue-closed-batch-open` |
| A `worker-<N>-*` branch whose N is absent from the state map (A3) | `issue-unknown` |
| A `worker-<N>-*` branch whose issue is open | `unlanded-open-issue` |
| Anything else | `unlanded-no-pr` |

**No automatic supersession.** `reap-orphans` never applies the "newer attempt for the same issue" rule. That stays an explicit `prune-attempts [--keep]` decision. This keeps ~30 parked or escalated local-only branches on open issues untouched by design.

**Open-PR re-check:** immediately before the deletion phase, the run lists `list_all_pulls(state="open")` again. Any branch that is now an open-PR head is changed to KEEP `open-pr`. This narrows the window between listing and deleting to the deletion phase itself. A PR opened in that remaining window, on a head that is otherwise deletable (landed, closed PR or closed issue), would have its remote head deleted, which GitHub shows as the PR closing. That is recoverable by re-pushing and reopening, and only one worker cycle runs at a time. It is accepted as residual.

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

**Allowed URL forms (architect edit A7):** the remote phase runs only when the origin URL is one of these:
- `https://github.com/…` with `GH_TOKEN` set, which gets the §3.3 auth env;
- a local path or `file://` URL, which gets no auth (tests).

Any other form (`git@github.com:`, `ssh://`, other hosts) skips the remote phase with `WARN: remote phase skipped — unsupported origin URL scheme`. An ssh URL would otherwise push with whatever ambient key the host has, which may be a human's identity rather than the worker App. `ls-remote` uses the same runner and the same auth env as the push, because the repo is private.

### 3.2 Compare-and-swap delete

The remote delete is:

```
git push --porcelain --force-with-lease=refs/heads/B:<sha> <url> :refs/heads/B
```

- The expected old OID is sent in the receive-pack update command, so the server rejects the update if the ref has moved. That makes this a true CAS.
- A rejected push, or a non-zero rc, gives `REAP-FAILED … where=remote reason=cas-or-push-failed` and does not count as a deletion.
- **Rejected alternative:** a REST `GET ref` followed by `DELETE`. It is not atomic, because the ref can move between the two calls.

**One batched push (architect edit A6):** all remote deletes of a run go in **one** non-atomic `git push --porcelain --no-verify`, with one `--force-with-lease=refs/heads/B:<sha>` and one `:refs/heads/B` refspec per branch. Do not pass `--atomic`, so one stale lease cannot block the rest.
- Each ref is still CAS'd individually by receive-pack.
- The porcelain output is parsed **per ref**. Only a line whose flag is `-` (deleted) for `:refs/heads/B` counts as REAPED. Every other line (`!` rejected / stale info), and any requested ref missing from the output, is REAP-FAILED. A non-zero rc does not override a per-ref `-` line, and a zero rc does not override a missing one.
- The batched push has a 120 s timeout, and `--max-deletions` still applies. This replaces up to 20 serial 60 s pushes, which could not fit any cron bound.
- `--no-verify` is used because a pre-push hook has no business on a branch delete and could stall unattended.

### 3.3 Token handling (CWE-532)

The token must **never** appear in argv, in the URL, in printed output, or in exception text. This differs from `submit_pr.sh:388`, which puts the token in the URL.

**Auth for an `https://github.com/` URL:** the git subprocess gets auth through its **environment only**:
- `GIT_CONFIG_COUNT=2`;
- `GIT_CONFIG_KEY_0=http.https://github.com/.extraheader`;
- `GIT_CONFIG_VALUE_0=AUTHORIZATION: basic <base64("x-access-token:" + GH_TOKEN)>`;
- `GIT_CONFIG_KEY_1=credential.helper`, `GIT_CONFIG_VALUE_1=` (empty) (architect edit A7). The empty value resets the helper list. This matters because `GH_TOKEN` expires after about 1 h. A rejected header would otherwise make git fall back to any configured helper (for example `gh auth git-credential` under a human login) and push as a different identity;
- `GIT_TERMINAL_PROMPT=0`, so missing credentials fail instead of hanging;
- `GIT_TRACE`, `GIT_TRACE_CURL`, `GIT_TRACE_PACKET` and `GIT_CURL_VERBOSE` are **removed** from the child environment, so no inherited trace setting can log the header.

**Missing token:** if `GH_TOKEN` is unset for a github.com URL, the run prints `WARN: GH_TOKEN unset — remote phase skipped` and makes no remote calls. Any other URL scheme (the test bare repo, ssh) gets no auth environment.

**Output sanitizing:** all remote stderr and exception text passes through a new `_redact(text)` and then `_one_line` before printing. `_redact` replaces both the token literal and its base64 header form with `***`.

**Subprocess runner:** remote git calls use a new runner, `make_git_remote(repo, extra_env)`. It has the same `(rc, stdout)` signature, plus a per-call timeout: 60 s for `ls-remote` and 120 s for the batched push. A timeout is reported as rc 124, and an rc of 124 is treated as a failure. For the push, a timeout means every ref in the batch is REAP-FAILED, which is a correct conservative report even though some refs may have been deleted. The next run sees them as absent.

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
| Dry-run, every branch considered | `KEEP branch=<b> reason=<r> where=local\|remote tip=<sha40>` or `WOULD-REAP branch=<b> reason=<r> where=… pr=#<n>\|- tip=<sha40>` |
| Real run, each deletion | `REAPED branch=<b> reason=<r> where=local\|remote pr=#<n>\|- tip=<sha40>` |
| Real run, a failed deletion | `REAP-FAILED branch=<b> reason=<delete-failed\|cas-or-push-failed> where=… tip=<sha40>` |
| Real run, cap reached | `DEFERRED branch=<b> reason=<r> where=… tip=<sha40>` |

**Field order is binding (architect edit A8):** `branch=` then `reason=` first, then the other fields. The existing `_RO_EVENT_RE` (`^(REAPED|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=`) requires ` reason=` to follow the branch name directly. The draft order `branch=… where=… reason=` would not have matched. `tip=` records the deleted SHA in the cycle log, which is the only recovery handle for never-pushed D2 work (§9.2).
| Always, last line | `SUMMARY reaped_local=<n> reaped_remote=<n> kept=<n> failed=<n> deferred=<n> api_calls=<n> aborted=0\|1 archived=<n>` (`archived=` appended by #2293) |
| Real run, before deleting an unlanded (D2) tip (#2293) | `ARCHIVED branch=<b> where=local\|remote ref=refs/archive/reap/<b>@<tip12> tip=<sha40>`; REAPED/REAP-FAILED lines are unchanged; a failed archive prints `KEEP … reason=archive-failed` |

- A real run does not print KEEP lines, which keeps the cron log small.
- Every interpolated value is a branch name that passed N1, a fixed reason token, an integer, or `_one_line(_redact(...))` text in WARN lines. Nothing else is interpolated (CWE-117).
- The line shape stays compatible with `_RO_EVENT_RE` in `bin/hos-cron:1719` (field order above), which slice 2 extends to capture `where=`.

**Exit codes:**
- **0:** the run completed, including runs with KEEP, WARN or REAP-FAILED lines.
- **2:** a listing failure (nothing deleted), a `GitError` resolving the store or slug, or a usage error.

The module docstring's Subcommands, Usage and Safety text is updated. The line "unrecorded leftover branches … never touched here" becomes scoped to `reap-landed`.

## 5. `prune-attempts` remote delete (decision 6)

**When it runs:** after each **successful** local `_delete_branch` of attempt `B` with tip `T`. It is not run on `--dry-run` and not run for skipped branches.

**What it does:**
1. Make one `ls-remote <url> refs/heads/worker-<issue>-*` call per invocation, done lazily on the first local delete.
2. If the remote has `refs/heads/B` at SHA `T`, check `list_pulls(owner, repo, head=f"{owner}:{B}", state="open")`. This existing helper costs one call per candidate, and the candidates are few.
3. If the check returns no open PR, run the §3.2 CAS push. The §3.1 allowed-URL rule and the §3.3 auth env, credential-helper reset and redaction all apply unchanged (A7).

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

**git calls:** about 4 local calls per branch (rev-parse, reflog, is-ancestor, merge-tree), so about 1,500 local calls in roughly 20–40 s, plus at most one `git log` per D2 candidate. There is also 1 `ls-remote` (60 s cap) and **one** batched push (120 s cap, A6).

**First run must be manual:** with the API calls (~37 sequential `gh` calls, each 1–2 s), the first run can take 2–3 minutes. That does not fit `reap-landed`'s current `_RO_BOUND` of 120 s. The first real run is the human-reviewed manual run in §9.1. Slice 2 gives `reap-orphans` its **own** bound, sized from the measured dry-run wall time, and does not share `reap-landed`'s 120 s.

Ordering that matters under a kill:
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
| T18 (A1) | `worker-<N>-x` on an **open** issue N whose tip equals a closed, unmerged PR's head; the same branch's remote head | Local: KEEP `closed-pr-open-issue`. Remote: REAPED `pr-closed`. A legacy `fix/y` at a closed PR's head is REAPED `pr-closed` |
| T19 (A2) | `worker-<N>-x` with issue N closed, but a commit on `origin/main..tip` that references an open `#M`; then the same branch with M missing from the map | KEEP `issue-closed-batch-open` both times |
| T20 (A3, A4) | Issue N absent from the state map; `pulls` returns `[]` | KEEP `issue-unknown`; exit 2 `aborted=1` with zero deletions |
| T21 (A5) | Local tip is a strict ancestor of a merged PR's `head.sha` (object present); then with the object absent | REAPED `pr-merged`; then KEEP `unlanded-pr-sha-mismatch`. A merged PR whose `base.ref` is not `main` does not match D1 |
| T22 (A6) | Batched push of 3 remote deletes where one lease is stale | 2 REAPED, 1 REAP-FAILED `cas-or-push-failed`. Exactly one push invocation is made |
| T23 (A7) | Origin `git@github.com:o/r.git`; `GH_TOKEN` set | Remote phase skipped with a WARN, no remote runner calls. For the github.com URL case, the runner env holds `credential.helper` reset to empty and no `GIT_TRACE*` / `GIT_CURL_VERBOSE` keys |
| T24 (A8) | A real-run `REAPED` and `REAP-FAILED` line | Each matches `bin/hos-cron`'s `_RO_EVENT_RE` verbatim (copy the regex into the test with a pointer comment) |
| T25 (selector, #2285 test 4) | Issue N whose only local branch is a squash-landed attempt with a merged PR at tip, and whose files have since changed on main so that `merge-tree` conflicts | Before reap: `select_work_candidates._started_stages(str(repo), [N])` returns stage 0 for N. After reap: N is absent |

The issue's **selector check** (a `select_work_candidates` dry run before and after, #1990) is also PR evidence, alongside T25. Squash-landed attempts whose content conflicts with today's main are removed by D1, either at the tip or through the ancestor form (A5). Any open issue that keeps stage 0 afterwards does so because of a branch the never-delete rule protects (`unlanded-pr-sha-mismatch`, `closed-pr-open-issue`, `unlanded-open-issue`). The PR must list each such issue from the dry run. Changing how the selector ranks *protected* stale branches is **out of scope** for #2286. It is deferred to #2285's remaining scope, and this is stated in the PR body.

## 9. Residual risk

1. **The first real run deletes about 300 local branches.** It happens the first time a human (or slice 2's cron) runs `reap-orphans` without `--dry-run`. The PR **must** attach the full dry-run output from the Worker clone, every KEEP and WOULD-REAP line, so a human reviews the delete set before merge. Slice 1 does not wire the subcommand into cron.
2. **D2 can delete local-only unlanded work.** It deletes `worker-<N>-*` branches with unlanded, never-pushed work on a **closed** issue. The issue requires this, and the existing `prune-attempts --issue-closed` deletes closed-issue attempts in the same way (since #2291 it applies the same A2 `#ref` check). A2 narrows it to branches whose commits reference no open issue.
   - *Correction (architect):* `update-ref -d` deletes the branch's own reflog, so the branch reflog is **not** a recovery path.
   - What remains: the `tip=` SHA in the cycle log (A8), plus `HEAD`'s reflog if the branch was ever checked out (unreachable entries expire after `gc.reflogExpireUnreachable`, default 30 days). `git branch <name> <sha>` recovers the work within that window.
   - The dry run makes every D2 candidate visible before the first real run.
   - *Known, not fixed here (resolved in #2291):* `prune-attempts --issue-closed` had the same batched-branch hazard that A2 closes for D2. The §10 follow-up was filed as #2291, which applies the A2 `#ref` check: an attempt whose `origin/main..tip` commit messages reference any other issue not verified `closed` (open, unknown, failed lookup, or a git error reading the refs) is kept with a WARN naming that issue.
3. **Recovery for D1 and D1' deletions.** Content deleted under D1 or D1' remains at `refs/pull/<n>/head`.
4. **Protected surfaces.** `.claude/agents/worker.md` puts this PR on a protected surface, so it gets human review at merge.
5. **Acceptance item 1 is not fully met by design (architect ruling A10).** #2286's acceptance says the clone ends with only `main`, the current branch and open-PR heads. Its own never-delete rule protects unlanded work on open issues, which is about 30 parked or escalated branches, and the safety rule wins. The PR therefore:
   - uses `Part of #2286`, never `Closes`, since slice 2 remains in any case;
   - attaches the full KEEP list with reasons;
   - states that the residual set is the protected parked set. It shrinks as those issues are ruled on and land, or through explicit `prune-attempts` decisions.

   The same applies to "remote has no `worker-*` head without an open PR": a remote head with unlanded work on an open issue and no PR is kept.

No open question needs a human ruling for slice 1.

## 10. Architect review (round 1, 2026-11-08): APPROVED with binding edits

**Verified against:** #2286 and #2285 bodies; `readopt.py` (`_delete_branch` CAS, `_checked_out_in_worktree` fail-safe, `_one_line`, `prune_attempts`); `github.py` (`ListTruncatedError`, the `list_check_suites_for_ref` pagination pattern, and `list_pulls`, which is unpaginated and so acceptable for the single-head query in §5); `select_work_candidates._branch_has_unlanded_work` (D3b is the same test, with conflict counted as unlanded, which is correct); and `bin/hos-cron:1708-1740` (`_RO_EVENT_RE`, `_RO_BOUND`=120 s).

**What was already right, and why:**
- All decisions are built before any delete, and a failed listing aborts everything. This is the correct fail-closed shape.
- Tip-equality (now "covers") on D1/D1' means a local tip ahead of the PR head is never reaped.
- No automatic supersession. This is the rule that protects the parked set.
- The force-with-lease delete is a real server-side CAS. A REST GET then DELETE is correctly rejected as non-atomic.
- Moving the token out of argv and URL into `GIT_CONFIG_*` env is correct. The env is readable only by the same uid; argv is readable by all.
- The 3-way `merge-tree` identity is a sound "no unlanded content" test. A conflict or any branch-only change yields a tree that differs from main.

**Binding edits applied in place:**

| # | Finding (failure mode) | Change |
|---|---|---|
| A1 | **Data loss on open issues.** D1' would delete a local `worker-<N>-*` branch on an open issue at a bounced or closed PR's head. That is unlanded work on an open issue, which the issue's never-list forbids, and re-adoption (`create_branch.sh --from <local>`) depends on it. | D1' is local-side blocked on open or unknown issues, giving KEEP `closed-pr-open-issue`. Remote closed-PR heads are still reaped (the #2285 target; content is kept in `refs/pull/N/head`). T18. |
| A2 | **Batched branches.** Branch names carry only the primary issue (for example the `worker-2151-*` branch holds #2101 S1 work, and the same holds for `worker-2073-*`, `worker-1549-*` and `worker-1660-*`). D2 on a closed primary would delete open-issue work. | D2 requires every `#ref` in `origin/main..tip` commit messages to be closed. Otherwise KEEP `issue-closed-batch-open`. This is over-conservative by design. T19. |
| A3 | **Partial issue listing.** "Issues cannot be deleted" is false: admin deletes and transfers happen, and a removal during ascending pagination skips one item. | A missing number gives KEEP `issue-unknown`. T20. |
| A4 | **Silent empty PR list** (a 200 with `[]`) would disable N5 and D1 while D3 and D2 still delete. | Zero PRs from the `state=all` listing raises, so the run aborts. T20. |
| A5 | **Selector acceptance is under-served.** A local tip that is an ancestor of the merged PR head (the PR was pushed further, then squashed) stays as an "unlanded" stale branch, which is exactly the stage-0 mis-rank. A PR merged into a non-main base is not landed. | "Covers" adds the ancestor form, with no API cost. D1 requires `base.ref == main`. T21. |
| A6 | **Budget and time.** Up to 20 serial pushes at 60 s each cannot fit any cron bound. | One batched, non-atomic, per-ref-lease push, parsed per ref, with `--no-verify` and a 120 s cap. T22. |
| A7 | **Identity confusion and token leakage.** After the ~1 h token expiry, a rejected extraheader falls back to any configured credential helper, which could be a human's identity. An ssh origin would push with an ambient key. Inherited `GIT_TRACE*` settings could log the header. | Reset `credential.helper` to empty via `GIT_CONFIG_KEY_1`, strip trace vars, and allow only https://github.com (with token) or local/`file://` URLs. T23. |
| A8 | **Cron regex mismatch.** The draft line `REAPED branch=<b> where=… reason=` does **not** match `_RO_EVENT_RE` (`branch=(…) reason=`). Slice 2's audit events would have been silently empty. There was also no recovery handle for never-pushed D2 work. | Field order is binding (`branch=`, `reason=`, then the rest), plus a `tip=<sha40>` field. T24. |
| A9 | **Steady-state API cost** was described as if the clean state were free. The parked set keeps every run at about 30 calls. | Zero-candidate short-circuit; per-issue reads when 20 or fewer distinct issues are involved; slice 2 owns cadence and bound from measured numbers. |
| A10 | **Acceptance honesty.** Acceptance item 1 contradicts the never-delete rule for the parked set. | The safety rule wins (a technical safety call, not a product change: nothing the human protected is deleted). The PR is `Part of #2286` and lists the residual KEEP set. §9.5. |
| A11 | **Test seam.** Slug parsing fails on the test fixture's bare-path origin. | `slug` is injectable and resolved lazily (§1.3, §1.4). |

**Slice split:** coherent. Slice 1 delivers the deletion engine plus the `prune-attempts` close-path delete, and runs nothing automatically. Slice 2 owns everything that runs unattended: cron wiring with its own bound and cadence, bounce close-path deletion, item 4's root cause and the metric. Do not merge slice 2's cron wiring before a human has reviewed slice 1's first real run (§9.1).

**Follow-up to file (worker, not this reviewer):** `prune-attempts --issue-closed` has the A2 batched-branch hazard. Either apply the same `#ref` check there, or document the hazard in `worker.md`. [Filed and resolved as #2291: the same `#ref` check is applied in `readopt.py prune-attempts --issue-closed`.]

**No human ruling required.**

**Post-review note (worker, fix round 1):** the remote-head grace (§2.2) is measured from the tip *commit* date, not the push time. Git exposes no push timestamp for a remote head, so a recently pushed old commit is judged old and can be reaped without waiting out the grace. Accepted as a residual: deletion still requires every other rule (no open PR, landed or closed-issue, tip compare-and-swap), and the content stays in `refs/pull/N/head` where a PR existed. Behaviour is unchanged; the limit is documented in the `readopt.py` module docstring.
