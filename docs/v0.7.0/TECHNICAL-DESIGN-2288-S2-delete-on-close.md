# TECHNICAL-DESIGN-2288-S2: delete-on-close — closing a PR without merging removes its head (#2288 slice 2, child of #2285)

**Status:** APPROVED by architect, round 1 (2026-11-09), with the edits marked *[architect]*. The coder may start. Architect rulings on §10 are recorded inline there.
**Binding input:** issue #2288 item 2 and its acceptance test, "closing a PR without merging removes its head". The never-touch list comes from item 1 as built by TD-2288-S1 (`docs/v0.7.0/TECHNICAL-DESIGN-2288-S1-remote-janitor.md`, APPROVED) and TD-2286 (`docs/v0.7.0/TECHNICAL-DESIGN-2286-reap-orphans.md`, APPROVED) rule N2. Everything those two documents specify stays in force. This document adds to them and does not override them.
**Change class:** additive. It adds one new script and one new `readopt` subcommand, and changes the default of one existing flag path: `edit_issue.sh --state closed` on a **PR** now also deletes the PR's head. The behaviour for issues and for every other flag stays the same. See §9 for the startup-gap and sign-off analysis.
**Contract only.** This document contains no implementation.

```
RISK: HIGH — the design authorizes deleting remote branches from an existing canonical write path, and every role uses it.
CONFIDENCE: MEDIUM-HIGH — it reuses the approved TD-2286 deletion primitive and protected set. Open points are listed in §10.
```

## Human Review Required
- The default changes: closing a PR through `edit_issue.sh` now deletes its head branch unless the caller passes `--keep-branch` (§3). This is what item 2 asks for, but it changes the behaviour of an existing tool for the worker, the overseer and the human-proxy.
- All files touched under `bootstrap/**` are on the protected surface (`scripts/framework/protected_surfaces.txt`), so the PR needs CODEOWNER human approval no matter what tier it scores.

---

## 0. Scope

| In (this slice) | Out |
|---|---|
| A `readopt delete-head --pr <N>` subcommand that deletes one PR's remote head | Item 1, the remote janitor (S1, merged) |
| A new `bootstrap/delete_branch.sh` wrapper with token mint and revoke | Item 3, `hos_repo_sync.sh` local prune |
| `edit_issue.sh --state closed` deletes the head of a PR by default, with a `--keep-branch` opt-out | Item 4, the branch-count metrics |
| Moving the protected-name set into one shared definition (behaviour-identical) | Cron wiring of any reaper |
| The `worker-cron-prompt.md:91` instruction text | Local-branch deletion in any clone |
| Tests | Edits to `.claude/agents/*.md` (§5) |
| `SCRIPTS-INDEX.md` regeneration | Explaining why 9 merged `worker-*` heads survived (#2285) |

## 1. Inventory of PR-closing paths (verified 2026-11-09)

I searched `bootstrap/`, `bin/`, `scripts/` (including `scripts/automation/` and `scripts/automation/lib/github.py`), `.claude/agents/`, `templates/` and `docs/LABELS.md` for: `gh pr close`, any PATCH to `/pulls/`, `state=closed` / `state: "closed"` sent in a write, and prose such as "close the PR", "close it", "superseded" and "bounce … close".

| # | Location | Kind | What it does |
|---|---|---|---|
| P1 | `bootstrap/edit_issue.sh:85,107,177,194-196` (verify GET at 223-225) *[architect: line cites corrected; 190-192 is `--set-assignee`]* | **Mechanism (the only one)** | `--state closed` sends PATCH `repos/{slug}/issues/{N}` with `{state: closed}`. The issues endpoint also closes PRs. This is the single place where a canonical tool closes a PR. |
| P2 | `bootstrap/worker-cron-prompt.md:91` | Instruction (worker) | On an unrecoverable conflict: "close the PR with a comment explaining the conflict and open a fresh PR". It names no tool, so in practice it means P1. |
| P3 | `.claude/agents/worker.md:484-485` | Instruction (worker, protected) | Re-entry step 6: "If a superseded PR is still open for the same issue, close it first (#1781 ruling)." Also P1 in practice. |
| P4 | `.claude/agents/worker.md:129`, `.claude/agents/overseer.md:843` | Tool tables (protected) | Both list `edit_issue.sh … [--state open\|closed]`. The overseer row says "on issues and PRs alike". The overseer has no PR-close instruction of its own, so P1 is its only path. |
| P5 | `CLAUDE.md`, "What to do instead" item 5 | Tool docs (human-proxy, protected) | Lists `edit_issue.sh … [--state open\|closed]`. P1 is the human-proxy's canonical path. |
| — | `.claude/agents/worker.md:933` | Not a PR path | Closes an **issue** (`edit_issue.sh --state closed`). The new behaviour does nothing for issues (§3.3). |

**Not found:** any `gh pr close`; any PATCH to `/pulls/{n}` in `lib/github.py`, `scripts/automation/*.py`, `bin/` or `bin/lib/`; any close in the bounce path (overseer bounces post reviews and comments and never close a PR); and any close in `readopt prune-attempts`, which deletes branches but never closes PRs and already refuses open-PR heads.

**Conclusion:** P1 is the one mechanism. P2 to P5 are instructions or docs that route to it. Making P1 delete by default therefore covers the worker, the overseer and the human-proxy with a single code change (§3). Closes made outside canonical tooling (the GitHub UI, ad-hoc `gh pr close`) are not covered. The backstop for those is S1's `reap-orphans --remote-scope all` rule D1' (`pr-closed`).

**The 2026-11-08 one-off:** I could not find the human-proxy's one-off in the repo or in `/tmp/claude/`. The #2285 draft records what it did: it deleted non-worker remote heads whose PR was closed or merged, or whose content was fully on main. This design covers the PR-addressed half of that, deleting by PR number. The "no PR, content on main" half is already in S1 (`reap-orphans --remote-scope all`, D3a/D3b). That is why the new script has no delete-by-name mode (§2.1).

## 2. `readopt delete-head`, the deletion contract

### 2.1 Interface

- **CLI:** `python3 -m scripts.automation.readopt [--repo <path>] delete-head --pr <N>`. `--pr` is required and must be a positive integer (argparse `type=int`). Zero or a negative value is a usage error.
- **Function:** `delete_head(repo: Path, pr_number: int, *, git: GitRunner, get_pull=None, open_pulls_for=None, remote_heads=None, remote_delete=None, slug=None) -> int`. The keyword seams follow the `_PruneRemote` / `reap_orphans` style.
  - `get_pull: (int) -> Optional[dict]`. Defaults to `github.get_pull(owner, repo, n)`.
  - `open_pulls_for: (branch) -> list[dict]`. Defaults to `github.list_pulls(owner, repo, head=f"{owner}:{branch}", state="open")`, the same call `_PruneRemote._has_open_pr` makes.
  - `remote_heads` and `remote_delete` use the existing `RemoteHeads` / `RemoteDelete` types. They default to `_ls_remote` / `_push_delete` over `_remote_ops(git, repo)`.
  - `slug` defaults to `_slug_from_origin(git)`.
- **No delete-by-name mode.** A by-name delete has no server-side record of the SHA that should be there, so it cannot do a meaningful compare-and-swap. The by-name cases (a head with no PR whose content is on main) belong to `reap-orphans --remote-scope all`.
- **Remote only.** This command never touches a local branch, an ownership record or a worktree. Local clean-up stays with each role's reaper (item 3 and TD-2286).

### 2.2 Shared protected set (required refactor)

`readopt.py:1006` defines the never-touch list inline. This slice moves it into module-level definitions:

- `PROTECTED_BRANCH_NAMES = ("main", "audit-log")`
- `PROTECTED_BRANCH_PREFIXES = ("release/", "audit/")`
- `is_protected_branch(name: str) -> bool`, which is true when `name` is in `PROTECTED_BRANCH_NAMES` or starts with one of the prefixes.

`reap_orphans` rule N2 must call `is_protected_branch`, and its behaviour must stay byte-identical (the existing N2 tests keep passing unchanged). `delete_head` uses the same function. No other copy of the list may exist.

### 2.3 Algorithm (deterministic; the first matching rule decides)

| Step | Check | Outcome |
|---|---|---|
| 1 | `get_pull(N)` returns None (404, or the number is an issue) or a non-dict | `ERROR` "PR #N not found", exit 2 |
| 2 | `pr.base.repo.full_name` (case-insensitive) differs from `f"{owner}/{repo}"` built from `slug` *[architect: slug is an (owner, repo) tuple]* | `ERROR` "PR is not in this repository", exit 2 |
| 3 | `pr.state != "closed"` | `KEPT reason=pr-open`, exit 3 |
| 4 | `pr.head.repo` is null (the fork was deleted), or `pr.head.repo.full_name` (case-insensitive) differs from `slug` | `KEPT reason=fork`, exit 3 |
| 5 | `pr.head.ref` is not a string, fails `_SAFE_NAME_RE`, or starts with `-` | `KEPT reason=unsafe-name`, exit 3 |
| 6 | `is_protected_branch(ref)`, or `ref == pr.base.repo.default_branch` | `KEPT reason=protected-name`, exit 3 |
| 7 | `pr.head.sha` does not match `_SHA_RE` | `ERROR` "PR head SHA unreadable", exit 2 |
| 8 | Remote phase unavailable: `_remote_ops` returns None (no origin, unsupported scheme per A7, or `GH_TOKEN` unset) | `ERROR`, exit 2 |
| 9 | `remote_heads(f"refs/heads/{ref}")`, keeping only entries whose name **equals** `ref`. ls-remote patterns are tail-matched, so `x/refs/heads/<ref>`-style names must be discarded. If nothing remains | `ALREADY-GONE`, exit 0 |
| 10 | Remote SHA ≠ `pr.head.sha` | `KEPT reason=moved`, exit 3. After a PR closes, GitHub stops updating its `head.sha`, so a mismatch means someone pushed after the close or recreated the name. *[architect: the safety of this step does not depend on that GitHub behaviour. If GitHub did update `head.sha`, the pushed commit would also be at `refs/pull/N/head`, so a delete would still be recoverable.]* |
| 11 | `open_pulls_for(ref)` contains any PR whose `head.repo.full_name` equals the slug | `KEPT reason=open-pr`, exit 3. Another open PR shares this head; this is the server-side open-PR check. A lookup that is not a genuine list (404, empty body, non-list payload) is `KEPT reason=pr-lookup-indeterminate`, exit 3 *[#2298]*. |
| 11b | `open_pulls_based_on(ref)` (`github.list_pulls_strict(base=ref, state=open)`) is non-empty | `KEPT reason=base-of-open-pr`, exit 3. Deleting the branch would auto-close a stacked PR. A failing lookup is an `ERROR`; a non-list answer is `KEPT reason=pr-lookup-indeterminate`, exit 3 *[#2298]*. *[round 2: security-reviewer]* |
| 12 | `remote_delete([(ref, sha)])`, the existing `--force-with-lease=refs/heads/<ref>:<sha>` CAS push | `True` gives `DELETED`, exit 0. `PUSH_TIMEOUT` gives `ERROR` "outcome unknown", exit 2. |
| 13 | The push returned `False`: re-list once as in step 9 | If absent, `ALREADY-GONE` (another deleter won the race), exit 0. Otherwise `ERROR` "push rejected" (CAS lost or branch protection), exit 2. |

- **Merged PRs** pass step 3, because a merged PR has `state: closed`. Deleting a merged PR's surviving head is allowed and safe, because the content is on the base branch and in `refs/pull/N/head`. `delete_branch.sh --pr <merged>` works, which makes it usable on the 9 survivors #2285 found. *[architect: corrected. `edit_issue.sh --state closed` on an already-merged PR is a no-op PATCH whose verified state is `closed`, so it **does** call the delete. That is intended and harmless. It is covered by DH16.]*
- **Failing closed:** any `github.GitHubError` / `RateLimitError`, any `GitError` and any exception from a seam is caught inside `delete_head` and returns `ERROR`, exit 2, with nothing deleted. No traceback may escape for this subcommand. A failing step 11 lookup is an error. It is never read as "no open PR".
- **Token hygiene:** the TD-2286 §3.3 rules apply unchanged: env-only auth, credential-helper reset, trace-variable strip, and `_redact` on every printed exception (A7).

### 2.4 Output (stdout, exactly one result line; diagnostics on stderr)

```
DELETED pr=#<N> branch=<name> tip=<sha>
ALREADY-GONE pr=#<N> branch=<name>
KEPT pr=#<N> branch=<name> reason=<pr-open|fork|unsafe-name|protected-name|moved|open-pr|base-of-open-pr>  (moved also carries expected=<sha> tip=<sha>)
ERROR pr=#<N> reason=<short text>
```

`branch=` goes through `_printable_name`. For `unsafe-name` and `fork` the name is printed percent-encoded, so a hostile ref name can never reach the terminal raw. Any `WARN:` lines that `_remote_ops` prints may come before the result line. *[architect: the result line must be the **last** stdout line. `edit_issue.sh` passes all of `delete_branch.sh`'s stdout through unchanged. Callers parse only the last line.]*

### 2.5 Exit codes (added to the module docstring)

| Code | Meaning |
|---|---|
| 0 | The head is gone: `DELETED` or `ALREADY-GONE` (idempotent; re-running is safe) |
| 2 | Error or uncertainty; nothing was deleted, or the outcome is unknown after a push timeout. The caller can retry. |
| 3 | Refused by a safety rule (`KEPT`). This is a valid outcome, not a failure. |

## 3. Close-path integration: `edit_issue.sh` deletes by default

### 3.1 Decision and justification

**Decision:** put the default in `edit_issue.sh`, the one mechanism (§1), and do not add a dedicated close script.
- **Coverage:** one change covers the worker, the overseer and the human-proxy, because every instruction already routes there (P2 to P5).
- **No allowlist churn:** Worker and Overseer run under `claude --print`, where an unmatched command is silently denied (CLAUDE.md). The existing `bash bootstrap/edit_issue.sh …` invocation stays the same, so no new allowlist rule is needed for the default path to work.
- **Less agent-file editing:** a separate `close_pr.sh` would mean rewriting the tool tables in `.claude/agents/*.md` (protected surface; under CLAUDE.md the top-level session must author those edits, not `coder`) and could still be bypassed with `edit_issue.sh --state closed`.

**About the `--delete-branch` wording:** item 2 says "Add a `--delete-branch` default". This design reads that as "deleting the branch is the default", so the opt-out flag is `--keep-branch`. It adds no `--delete-branch` flag. A flag whose only value is the default would invite the misreading that leaving it out means keep. *Clarifying interpretation; architect or PM may overrule.*

### 3.2 Contract

- **New flag:** `--keep-branch` (boolean). It is valid only together with `--state closed`; any other use is a usage error (exit 1, the script's `err` convention), raised before a token is minted. It counts as an edit flag only in combination with `--state closed`, so the "at least one edit flag" rule stays as it is.
- **Verify step:** the existing verify GET of `repos/{slug}/issues/{N}` fetches the JSON **once**, without `--jq`. Two values are derived from that same JSON with local `jq`:
  - `RESULT`, using exactly today's filter. The printed line must stay **byte-identical** (existing tests assert it).
  - `IS_PR`, computed as `.pull_request != null`.
- **Delete condition (all four must hold):** `STATE == closed` was requested, `--keep-branch` is absent, `IS_PR == true`, and the **verified** `.state == "closed"`. If the close did not take, nothing is deleted.
- **Order:** PATCH, then labels and assignees (unchanged), then verify, then `echo "$RESULT"`, then revoke this script's token, then `bash "$SCRIPT_DIR/delete_branch.sh" --pr "$PR_NUMBER" --app "$APP_ROLE"`. *[architect: `PR_NUMBER` is the verified `.number` taken from the same verify JSON, not the raw `--number`. `edit_issue.sh` accepts `0` and leading zeros (`*[!0-9]*`), but `delete_branch.sh` requires `^[1-9][0-9]*$`. Passing the raw value would turn a successful close into a spurious exit 4.]* The delete script mints its own token and revokes it. That costs one extra mint per PR close, which is accepted so that each script fully owns its token's lifetime and none is passed between scripts.
- **rc capture under `set -euo pipefail`** *[architect]*: both scripts must capture the child rc explicitly (`rc=0; bash … || rc=$?` in `edit_issue.sh`, and the same around the `python3` call in `delete_branch.sh`), so that `set -e` cannot exit before the mapping or the revoke runs. Exit 4 is a literal `exit 4` after the `warn`, never `err`, because `err` exits 1.
- **Mapping the delete script's exit code:**

  | `delete_branch.sh` rc | `edit_issue.sh` behaviour | `edit_issue.sh` exit |
  |---|---|---|
  | 0 | Pass its result line through to stdout | 0 |
  | 3 | Pass its `KEPT …` line through, plus a stderr `warn` that the head was kept | 0 |
  | anything else | A stderr `warn` giving the recovery command `bash bootstrap/delete_branch.sh --pr <N> --app <role>` | **4**. The close itself succeeded. Re-running the close and the delete is safe, because both are idempotent. |

- **Header doc:** the usage block and the header comment document `--keep-branch`, delete-by-default for PRs, the no-op for issues and exit code 4. The header must also say that a closed PR whose head was deleted cannot be reopened until the branch is restored (GitHub "Restore branch" on the PR), and that `--keep-branch` is for a close where the PR will be reopened or its head reused.

### 3.3 Issues

When `IS_PR` is false the delete step does not run at all: no extra call, no extra output, the same exit code. Every existing `edit_issue.sh` test keeps passing unchanged.

## 4. `bootstrap/delete_branch.sh` (new canonical delete script)

- **Usage:** `bash bootstrap/delete_branch.sh --pr <N> --app <worker|overseer|human>`. It has no body, so there is no `--body-file`. Any other flag, including `--branch`, is a usage error, and so is passing `--keep-branch` here.
- **Validation:** the same style as `edit_issue.sh`. `--pr` must match `^[1-9][0-9]*$`, and `--app` must be in the role set. Both are checked before minting.
- **Flow:** mint a token through `get_app_token.sh` into a `mktemp` file, source it, delete the file at once (the #549 pattern with an EXIT trap). Then run `(cd "$REPO_DIR" && python3 -m scripts.automation.readopt --repo "$REPO_DIR" delete-head --pr "$PR")` with `REPO_DIR="$SCRIPT_DIR/.."`, the same pattern as `create_branch.sh:133`. Capture its rc, revoke the token (best-effort, warning on failure, as in `edit_issue.sh`) and exit with **the Python rc unchanged** (§2.5). A failed mint exits 2.
- **Header:** state that this is the canonical way to delete a PR's head (#2288 item 2), that it is remote-only, that it acts by PR number only, and that `reap-orphans` handles heads with no PR. Point out that `edit_issue.sh --state closed` calls it automatically for PRs.
- **Index:** add the script to `SCRIPTS-INDEX.md` through `scripts/framework/regen_all.sh` (CI runs `--check`). CODEOWNERS needs no change, because `bootstrap/**` is already covered.

## 5. Doc and prompt updates

| File | Change |
|---|---|
| `bootstrap/worker-cron-prompt.md:91` | Replace "close the PR with a comment explaining the conflict" with: post the comment through `bootstrap/post_comment.sh`, **then** close with `bash bootstrap/edit_issue.sh --number <PR> --state closed --app worker`, which also deletes the PR's head branch. The fresh branch must already exist locally (it is cut via `create_branch.sh` and cherry-picked) before the close, because the close deletes the remote copy of the old head. The old commits stay at `refs/pull/<PR>/head`. |

**Deliberately not edited in this slice:**
- `.claude/agents/worker.md:129,484-485` and `.claude/agents/overseer.md:843` are protected, top-level-authored files. No edit is needed for correctness, because the instructions already route to `edit_issue.sh` and pick up the new default automatically. The tool-table rows stay accurate, since `--keep-branch` is an optional opt-out. A row update that mentions `--keep-branch` can follow as a separate top-level-authored change, and I recommend it but do not require it.
- `CLAUDE.md` (human-owned, protected) is in the same position.

## 6. Tests (pytest, no network, mocked gh and git or a local bare origin)

### 6.1 `tests/automation/test_readopt.py`: `delete_head`

Use the existing `repo` fixture (a real temp repo with a bare `file://` origin, allowed under A7), inject `get_pull` / `open_pulls_for` / `slug`, and use the real `_ls_remote` / `_push_delete` against the bare origin unless the row says otherwise.

| ID | Setup | Expected |
|---|---|---|
| DH1 (acceptance) | Push `fix/x` to the origin. `get_pull` returns closed, `merged_at: null`, head `fix/x` at the pushed tip, same-repo | `DELETED`, exit 0, and `git ls-remote` on the bare origin no longer lists `refs/heads/fix/x` |
| DH2 | The same as DH1, run twice | Second run: `ALREADY-GONE`, exit 0 |
| DH3 | The head was never pushed | `ALREADY-GONE`, exit 0, no push attempted (spy on `remote_delete`) |
| DH4 (parametrized) | Head ref is `main`, `audit-log`, `release/0.5.x` or `audit/overseer-cycle-x` (pushed), and separately head ref == `base.repo.default_branch` | `KEPT reason=protected-name`, exit 3, the ref is still on the origin, and `remote_heads` / `remote_delete` are never called |
| DH5 | `state: open` | `KEPT reason=pr-open`, exit 3, nothing deleted |
| DH6 | Closed, but `open_pulls_for` returns another same-repo open PR | `KEPT reason=open-pr`, exit 3, the ref is still present |
| DH7 | Closed, the origin tip was advanced after the PR's `head.sha` | `KEPT reason=moved`, exit 3, the ref is still present |
| DH8 | `head.repo` null, and separately `head.repo.full_name` is another owner's | `KEPT reason=fork`, exit 3 |
| DH9 | `get_pull` returns None, and separately it raises `GitHubError` | `ERROR`, exit 2, nothing deleted, no traceback |
| DH10 | `open_pulls_for` raises | `ERROR`, exit 2, the ref is still present (fails closed) |
| DH7b | Closed, `open_pulls_based_on` returns an open PR; and separately it raises | `KEPT reason=base-of-open-pr`, exit 3, ref present; lookup failure gives `ERROR`, exit 2 *[round 2: security-reviewer]* |
| DH11 | Injected `remote_delete` returns `PUSH_TIMEOUT` | `ERROR`, exit 2 |
| DH12 | Injected `remote_delete` returns `False`, then the re-list shows the ref gone | `ALREADY-GONE`, exit 0 |
| DH13 | The origin also holds `x/refs/heads/fix/x`-style tail-match noise | Only the exact `fix/x` is considered and deleted, and the noise ref survives |
| DH14 | `is_protected_branch` unit test | True for the four forms, false for `mainline`, `release`, `audit-logs`, `fix/release/x` |
| DH15 | CLI: `delete-head --pr 0`, `--pr -1`, `--pr abc` | argparse usage error, exit 2 |
| DH16 *[architect]* | The same as DH1, but `merged_at` is set (a merged PR, `state: closed`) | `DELETED`, exit 0 (§10 point 5) |

The existing N2 tests for `reap_orphans` must pass unchanged. They are the regression proof for the §2.2 refactor.

### 6.2 `tests/automation/test_edit_issue.py`: the close path

Extend the harness:
- A stub `bootstrap/delete_branch.sh` copied into the harness bootstrap dir. It records its argv to `CAPTURE_FILE`, prints `$DELETE_STUB_OUT` and exits `$DELETE_STUB_RC` (default 0).
- The gh stub's GET `issues/<N>` reads `GH_ISSUE_STATE` (default `open`) and, when `GH_IS_PR=1`, adds `"pull_request":{"url":"…"}`.

| ID | Case | Expected |
|---|---|---|
| EC1 (acceptance) | `--state closed` on a PR (`GH_IS_PR=1`, `GH_ISSUE_STATE=closed`) | `delete_branch.sh --pr <N> --app worker` is invoked **after** the token revoke, its line is passed through, exit 0 |
| EC2 | The same, with `--keep-branch` | `delete_branch.sh` is not invoked, exit 0 |
| EC3 | `--state closed` on an issue (`GH_IS_PR` unset) | Not invoked, stdout byte-identical to today, exit 0 |
| EC4 | `--state closed` on a PR, but the verified state is `open` | Not invoked |
| EC5 | `--state open` on a PR | Not invoked |
| EC6 | Stub rc 3 | `KEPT` line passed through, a stderr warning, exit 0 |
| EC7 | Stub rc 2 | A stderr warning containing `delete_branch.sh --pr <N> --app worker`, exit 4 |
| EC8 | `--keep-branch` without `--state closed` | Usage error before any `GET_APP_TOKEN_CALLED_WITH` |
| EC9 *[architect]* | `--number 0042` on a PR whose verified `.number` is 42 | `delete_branch.sh` gets `--pr 42` |

### 6.3 `tests/automation/test_delete_branch.py` (new)

Use the same harness style as test_edit_issue: a copied script, a stubbed `get_app_token.sh` / `curl`, and a stub `python3` on PATH that records argv and exits `$PY_RC`.

| ID | Case | Expected |
|---|---|---|
| DB1 | Valid call | `python3` called with `-m scripts.automation.readopt --repo <dir> delete-head --pr <N>`, the token is revoked, the exit code equals `$PY_RC` for 0, 2 and 3 |
| DB2 | Missing or invalid `--pr` (`0`, `abc`) or `--app`, or an unknown flag (`--branch`) | Usage error, no mint |
| DB3 | Mint fails | Exit 2, no `python3` call |

## 7. Files the coder touches (8 files, all under the 15-file cap)

| File | Kind | Est. changed lines |
|---|---|---|
| `scripts/automation/readopt.py` | `is_protected_branch` refactor, `delete_head`, subparser, docstring and exit codes | ~120 |
| `bootstrap/delete_branch.sh` | new | ~75 |
| `bootstrap/edit_issue.sh` | `--keep-branch`, single-fetch verify, delete call, header | ~40 |
| `bootstrap/worker-cron-prompt.md` | line 91 | ~2 |
| `tests/automation/test_readopt.py` | DH1 to DH15 | ~190 |
| `tests/automation/test_edit_issue.py` | harness extension plus EC1 to EC8 | ~95 |
| `tests/automation/test_delete_branch.py` | new | ~80 |
| `SCRIPTS-INDEX.md` | regenerated | ~1 |
| **Total** | | **~600** (code ~235, tests ~365), plus this TD (~250) if it is committed on the same branch |

**This will exceed the 400-line `diff_size` floor**, so the PR scores at least HIGH. I don't think that changes the outcome. The slice deletes remote refs through a canonical write path, and it touches `bootstrap/**` (protected surface, human-gated), so HIGH with CODEOWNER review is the right treatment anyway. I would rather not cut tests to fit under the floor. **The split option for the architect:** S2a is `readopt delete-head`, `delete_branch.sh` and their tests (~465). S2b is the `edit_issue.sh` default, the prompt line and their tests (~135). S2a on its own changes nothing that already exists. Each part alone still exceeds 400 or is trivially small, so I recommend one slice.

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | A wrong head is deleted: a moved branch, or a name reused for new work | Step 10 compares the remote tip to the closed PR's frozen `head.sha`, and step 12 is a server-side CAS (`--force-with-lease`). A recreated or advanced name is KEPT. |
| R2 | The head of another open PR is deleted (GitHub would then auto-close that PR) | The step 11 server-side check fails closed on error. A residual TOCTOU window remains between step 11 and the push. It is the same one TD-2286 accepted and is not closable without a lock GitHub does not offer. |
| R3 | A protected or default branch is deleted | One shared `is_protected_branch`, plus the base repo's `default_branch` check, applied before any remote call (DH4). |
| R4 | A closed PR whose head was deleted cannot be reopened | Documented. `--keep-branch` covers it, GitHub "Restore branch" recovers it, and the content stays at `refs/pull/N/head`. |
| R5 | The changed default surprises an agent that closes a PR it means to reopen | The `--keep-branch` doc. No existing instruction closes a PR to reopen it (§1). |
| R6 | A fork head is touched | Refused at step 4, since the bot cannot push to a fork anyway. A deleted fork (`head.repo` null) is refused too. |
| R7 | Partial failure: the PR is closed but the head survives | Exit 4 plus the exact recovery command. S1 `reap-orphans --remote-scope all` (D1') is the backstop. |
| R8 | Token leakage | The TD-2286 A7 env-only auth and redaction are reused unchanged. The token is never in argv. |
| R9 | Closes outside canonical tooling (GitHub UI, raw `gh pr close`) | Out of scope by design. The S1 janitor backstop catches them. |

## 9. Startup-gap and sign-off analysis

- **Should this have been settled in the initial design?** No. Delete-on-close is a new requirement from #2288 (2026-11-08). It is not a missing edge case in an approved contract, so no `startup-artifact-gap` issue is needed.
- **Affected sign-offs:**
  - TD-2286 and TD-2288-S1 still stand. The §2.2 refactor keeps N2 byte-identical, and the existing N2 tests prove it.
  - Prior `edit_issue.sh` sign-offs still stand for the issue path. The PR-close path gains new behaviour, which this slice's review chain covers in full.
  - No code already approved against an old contract is left orphaned.

## 10. Open points for architect review

1. Should this be one slice or the S2a/S2b split (§7)?
2. Is the `--keep-branch` reading of "`--delete-branch` default" acceptable (§3.1)? If the architect reads it as a product question, it goes to `pm-agent`.
3. `edit_issue.sh` returns exit 4 on delete failure after a successful close. The alternative is exit 0 with only a warning. I prefer 4, because a silent leftover is exactly the "cowpat" #2285 is about.
4. `delete_branch.sh` mints a second token instead of inheriting the caller's (§3.2).
5. Should merged PRs be accepted by `delete_branch.sh` (§2.3)? I propose yes, as a manual remedy for the merged heads that survived.

### Architect rulings (round 1, 2026-11-09) *[architect]*

1. **One slice. The S2a/S2b split is rejected.** Splitting buys nothing. S2a alone is still above the 400-line floor. S2b alone is a small default change whose correctness depends entirely on S2a's contract, so reviewing it apart from S2a weakens that review. Both halves touch `bootstrap/**`, so both would get CODEOWNER review anyway. HIGH is the correct tier on the merits (a default-on remote deletion in a write path every role uses), not just an artefact of the floor. Do not cut tests to get under the floor.
2. **`--keep-branch` only; no `--delete-branch` flag.** This is an interface choice, not a product question. #2288 item 2 (Scott, priority:critical) asks for deletion **by default** in every canonical close path. The opt-out spelling implements that exactly. A `--delete-branch` flag would be a no-op flag that makes "omitted means keep" look right. A caller who passes it anyway gets a visible usage error (exit 1), not silent behaviour. **Product-boundary checkpoint:** the changed default is user-visible behaviour, and it is cleared by the human's own requirement in #2288 together with the CODEOWNER gate on `bootstrap/**`. The "Human Review Required" section must stay in the PR body so the CODEOWNER sees the default change explicitly.
3. **Exit 4 on a delete failure after a successful close.** Agreed. A silent leftover is the failure #2285 exists to remove. Exit 4 is safe because no script caller of `edit_issue.sh --state closed` exists (verified by grep across `bin/`, `scripts/` and `bootstrap/`), and both operations are idempotent. Exit 3 (`KEPT`) stays exit 0, because a safety refusal is a correct outcome. The `warn` must name the reason so the leftover is still visible in the cycle log.
4. **A second token, minted by `delete_branch.sh`.** Agreed. Each script owns its token's whole lifetime, and no token ever crosses a process boundary as an argument or a file. The extra mint per PR close is negligible. `delete_branch.sh` must not rely on any inherited `GH_TOKEN`, which `edit_issue.sh` has already revoked. It sources its own mint before running `python3`, and a failed mint exits 2 before `python3` runs (DB3).
5. **Merged PRs are accepted.** The content is on the base branch and at `refs/pull/N/head`, and steps 10 to 12 still apply. DH16 covers it.

**Remaining risk the reviewers should check (not blocking):** a local branch whose remote head this deletes will show "upstream gone". The re-adoption and parked-branch flows check `origin/<branch>` (see the stale-upstream lessons). Code review must confirm that no flow treats "remote head absent" as "unpushed, push it" for a branch whose PR is closed, because that would recreate the stray. Local clean-up itself stays out of scope (item 3).

**Startup-gap check (§9):** concur. This is a new requirement (2026-11-08), not a gap in an approved contract. TD-2286 and TD-2288-S1 sign-offs stand. The N2 refactor is behaviour-identical and its existing tests prove it.
