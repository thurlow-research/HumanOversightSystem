# TECHNICAL-DESIGN-2288-S3: `hos_repo_sync.sh` prunes merged/closed local branches in the Human clone (#2288 slice 3, child of #2285)

**Status:** APPROVED (coder may start), architect round 1, 2026-11-09. *[architect]* This approval covers the draft plus the binding edits marked *[architect]*: gate P4b (§4.1), the rc-capture note (§4.4), T-S14 and the T-S7/HH1 tightenings (§7), the R2 text (§10), and the §12 rulings. All §1 citations were checked against `b728b9e75` and are accurate.
**Binding input:** issue #2288 item 3, verbatim: "**Human clone:** `bootstrap/hos_repo_sync.sh` prunes local branches whose PR is merged or closed (the human-proxy cleaned all 24 by hand on 2026-11-08)." The issue-wide acceptance "counts stay at zero across a week of cycles" applies. The decision table is TD-2286 §2 (`docs/v0.7.0/TECHNICAL-DESIGN-2286-reap-orphans.md`, APPROVED). TD-2288-S1 and TD-2288-S2 (both APPROVED) stay in force. This document adds to all three and overrides none of them.
**Change class:** additive. `hos_repo_sync.sh` gets a prune step that is **off by default** and only `bin/hos-human` turns on. `readopt reap-orphans` gets one opt-in narrowing flag whose default is today's behaviour. No existing caller changes behaviour unless it opts in. See §11 for the startup-gap and sign-off analysis.
**Contract only.** This document contains no implementation.

```
RISK: HIGH — the design adds automatic local-branch deletion to a session-start
      script on the protected bootstrap/** surface, and adds a flag to the
      approved reaper's decision table.
CONFIDENCE: MEDIUM-HIGH — it reuses the approved TD-2286 engine without changing
      its decisions. The only new decision text is the narrowing flag in §3.
      Open points are in §12.
BLAST RADIUS: local refs in the Human clone only (gated in §4.1). No remote
      writes and no GitHub writes. The inputs are read-only GitHub PR and issue
      listings. The callers are bin/hos-human (the only one that opts in), the
      in-session human-proxy sync and the worker tool row (both stay prune-off).
```

## Human Review Required
- **A new automatic deletion.** Every `bin/hos-human` session start now deletes local Human-clone branches whose PR is merged or closed, or whose content is already on `main`, once they are more than 1 day old (§4). The opt-out is `HOS_REPO_SYNC_PRUNE=0`.
- **Protected surface.** `bootstrap/hos_repo_sync.sh` and `bin/hos-human` are both protected (`scripts/framework/protected_surfaces.txt`: `bootstrap/**`, `bin/**`). The PR needs CODEOWNER human approval at any tier.
- **First-run evidence (as in TD-2286 §9.1).** The PR must attach a `--dry-run` from the **Human clone** using exactly the §4.3 flags plus `--dry-run`, with every KEEP and WOULD-REAP line, so a human sees the delete set before merge.

---

## 0. Scope

| In (this slice) | Out |
|---|---|
| A prune step in `bootstrap/hos_repo_sync.sh`. It is off by default and gated to the Human clone (§4). | Item 4: metrics and the count line |
| `bin/hos-human` turns it on for its session-start call (§5) | Cron wiring of any reaper |
| `readopt reap-orphans --no-issue-closed`, a narrowing flag (§3) | Remote deletion of any kind (`--local-only` is fixed) |
| Tests (§7) | Worker or Overseer clone pruning (TD-2286 §9.1 still gates the Worker clone's first real run) |
| | Edits to `CLAUDE.md` and `.claude/agents/*.md` (§9, deferred) |

## 1. Verified facts (2026-11-09, against `a779b8fd6`)

| # | Claim | Evidence |
|---|---|---|
| F1 | `reap_orphans(do_remote=False)` never builds remote ops. `_remote_ops`, `ls-remote` and push are all inside `if do_remote:`. A local-only run makes no git network calls and needs no push token. | `readopt.py:972` (block 972-996), CLI `do_remote=not args.local_only` at `:1471` |
| F2 | Local decisions follow the TD-2286 table. N1-N4 and G1 are evaluated with no GitHub calls (`:1012`). D1, D1' (with A1 at `:1214`), D2 (`:1219`) and D3a/b are in `_decide_rest`, and the open-PR re-check runs before any delete (`:1127`). | `readopt.py:1012-1141`, `:1203-1258` |
| F3 | Fail-closed: a PR, issue or re-check listing failure, or a `GitError` on the slug or base, prints `WARN: listing failed — nothing deleted` and returns 2 with zero deletions. A zero-PR listing aborts too (A4, `:1071`). | `readopt.py:1138-1141`, `:959-962` |
| F4 | The base is hardcoded to `origin/main` (the `base` parameter is not on the CLI), and D1 requires `base.ref == "main"`. | `readopt.py:924`, `:1094` |
| F5 | GitHub reads go through `gh api` (`github._run_gh`). `gh` authenticates with `GH_TOKEN` if set. Otherwise it falls back to the `gh` CLI's stored login, and with no login at all it fails. A failure is retried with backoff and then raised as `GitHubError`, which becomes `_Abort` and exit 2 with nothing deleted. On a 401 the token is re-minted once, using `HOS_TOKEN_APP_ROLE`. Each call has a 30 s timeout. | `lib/github.py:138-289`, `:44`, `:101-135` |
| F6 | `scripts/automation/` is not shipped to consumers. A grep of `hos_install.sh` for `scripts/automation` or `readopt` finds nothing. `hos_repo_sync.sh` **is** shipped. | `bootstrap/hos_install.sh:1903` |
| F7 | `bin/hos-human` runs the sync unsandboxed and best-effort (`\|\| true`), straight after the Human App mint, so `GH_TOKEN`, `HOS_BOT_LOGIN` and `HOS_TOKEN_APP_ROLE=human` are all exported. It does not `cd`, so the sync acts on the cwd's repo. | `bin/hos-human:94-112`, `bootstrap/get_app_token.sh:211-219` |
| F8 | `bin/hos-cron` never calls the sync. It runs `readopt reap-landed` itself, guarded by `-f scripts/automation/readopt.py` and bounded by `timeout`/`gtimeout` with `--kill-after=10`. | `bin/hos-cron:1712-1738` |
| F9 | `worker.md:134` lists the sync as a worker tool, and CLAUDE.md "Session start" step 4 has the human-proxy run it in-session (sandboxed). | `.claude/agents/worker.md:134`, `CLAUDE.md:520` |
| F10 | The sync's final exit status today is the status of the state-file `mv`. The interval-skip path exits 0 at `:64-68` and the fetch-failure path exits 1 at `:103-113`, both before the state write. | `bootstrap/hos_repo_sync.sh:64-68`, `:103-113`, `:178-186` |
| F11 | The Human clone's local branches today are `main` plus three `human/*` branches. Human-proxy branches are `human/*`, which `_WORKER_RE` (anchored `worker-(\d+)-`) never matches. | `git -C …/Human for-each-ref refs/heads/` (read-only), `readopt.py:812` |
| F12 | The existing `test_hos_repo_sync.py` harness runs the **real** script against temp clones whose default branch is `trunk`, with `cwd` set to the clone. | `tests/automation/test_hos_repo_sync.py:28,42-56,63` |

## 2. Reuse decision and the reason set

**Decision: reuse `readopt reap-orphans --local-only` and write no new decision logic in the shell.** The sync is only a caller. Every keep/delete decision, CAS delete, grace check and fail-closed rule stays in the approved engine.

Here is each local REAP reason, judged against the item text ("whose PR is merged or closed") and against whether a delete loses anything:

| Reason | In item text? | Lossless? | S3 ruling |
|---|---|---|---|
| D1 `pr-merged` | Yes | Yes. "Covers" (A5) means every local commit is in the merged PR, so on `main` and in `refs/pull/N/head`. | **Allowed** |
| D1' `pr-closed` (A1 still keeps a `worker-*` branch on an open issue) | Yes | Recoverable. Every local commit is in `refs/pull/N/head`. | **Allowed** |
| D3a `landed-ancestor` / D3b `landed-content` | No, but this is the squash-merged PR case where the local tip differs from `head.sha` (a local rebase after merge), and it is #2288's "content fully on main" rule | Yes. The content is on `main` by definition. | **Allowed.** It keeps "counts stay at zero" achievable without changing the engine. |
| D2 `issue-closed` | **No.** It fires with **no** covering PR. | **No.** It deletes unlanded, possibly never-pushed commits. The only recovery handle is the `tip=` SHA plus `HEAD`'s reflog (TD-2286 §9.2). | **Excluded** through `--no-issue-closed` (§3) |

**Why narrow D2 instead of accepting it:** D2 is the only reason that can destroy content that exists nowhere else, and it is outside the item's wording. The Human clone is where hand-authored work lives. That includes the CLAUDE.md exception path, where a human-proxy may commit onto a checked-out `worker-*` branch before pushing. Today D2 is unreachable in the Human clone because there are no `worker-*` branches (F11). That is a property of current usage, though, not something the code guarantees. The cost is one boolean and about 15 lines in `readopt.py`, which is a filter on an existing rule, not a new rule. The no-flag alternative is §12 Q1.

## 3. `readopt reap-orphans --no-issue-closed` (narrowing flag)

- **CLI:** `--no-issue-closed` (`store_true`, default off) on the `reap-orphans` subparser. It is valid with `--local-only`, `--remote-only` or neither, and applies to every side that runs. Add it to the module docstring's Usage line.
- **Function:** `reap_orphans(..., issue_closed: bool = True)`. The CLI passes `issue_closed=not args.no_issue_closed`. `_decide_rest` receives the same value.
- **Semantics when `issue_closed=False`:**
  1. Rule D2 is **not evaluated**. In `_decide_rest`, the D2 block (`:1219-1226`) is skipped as a whole, so `d2_blocked` and `d2_git_error` stay false.
  2. Evaluation continues to D3a/D3b exactly as today. A landed branch on a closed issue is still REAPED as `landed-ancestor` or `landed-content`.
  3. If D3 does not match, the KEEP reason is the **new** token `issue-closed-unlanded`. It is selected by one new `elif issue is not None and state == "closed"` placed **after** `elif d2_blocked` and **before** `elif issue is not None and state is None` (`:1245-1249`). That position can only be reached when D2 was suppressed. Every earlier KEEP reason (`closed-pr-open-issue`, `unlanded-pr-sha-mismatch`) keeps precedence.
  4. `_commit_issue_refs` is **not** called, and the commit `#refs` are **not** added to `needed` (`:1109-1111`), because only D2 uses them. The branch's own issue number still goes into `needed`, because A1 (`:1214`) needs its state.
  5. Nothing else changes: N1-N5, G1, D1, D1' with A1, D3, the re-check, the CAS delete, the output format (A8 field order), the SUMMARY fields and the exit codes.
- **Default:** byte-identical to today. Every existing `test_readopt.py` test must pass unchanged.

## 4. `bootstrap/hos_repo_sync.sh` prune step

### 4.1 Gates, evaluated in this order. The first failing gate decides.

| # | Gate | If it fails |
|---|---|---|
| P0 | The script reached the prune step. A normal sync reaches it after the state-file write, and the recent-sync (interval-skip) path reaches it before its `exit 0` (#2322). The fetch-failure path does **not** prune, because a stale base makes `landed-*` decisions less trustworthy: with `HOS_REPO_SYNC_PRUNE=1` it prints `prune skipped — fetch failed`, otherwise it is silent. The not-a-repo and state-dir-ownership paths exit earlier and never prune. | Fetch failure: one line (`prune skipped — fetch failed`) when `HOS_REPO_SYNC_PRUNE=1`, else silent. Not-a-repo and state-dir ownership: nothing runs. The sync exit status is unchanged on every path. |
| P1 | `HOS_REPO_SYNC_PRUNE` is exactly `1` | **Silent** (no line). This is the default for every caller except `bin/hos-human`, so worker sessions and consumer installs see no noise. |
| P2 | `HOS_TOKEN_APP_ROLE` is exactly `human` | One line: `prune skipped — not the human role`. This is a scoping backstop, not a security control. A stray global `HOS_REPO_SYNC_PRUNE=1` must never start the Worker clone's first real `reap-orphans` run, because TD-2286 §9.1 requires a human-reviewed dry run before that. |
| P3 | `<script_root>/scripts/automation/readopt.py` is a regular file, where `script_root` is the parent of the script's own directory, resolved with `pwd -P` from `${BASH_SOURCE[0]}` | One line: `prune skipped — scripts/automation/readopt.py not present` (the consumer case, F6) |
| P4 | `repo_root`, resolved with `pwd -P`, **equals** `script_root`. The script prunes only the clone it ships in. | One line: `prune skipped — not this script's own clone`. Without this rule, running the sync from an arbitrary cwd would execute that repo's `scripts/automation/readopt.py`, which is a new code-execution path from repo content. |
| P4b *[architect]* | `repo_root` is **not** a registered Worker or Overseer root. Read `${HOME}/.config/hos/projects.conf` only if it is a regular file. For each line matching `^[A-Za-z0-9_]+_(worker\|overseer)_root=`, take the value, strip one trailing `/`, resolve it with `pwd -P` if it is a directory (otherwise compare it literally), and compare it to the physical `repo_root`. If the registry is absent or unreadable, the gate **passes**. That is safe because `bin/hos-cron` runs only in registered roots, so an unregistered clone is never a cron Worker or Overseer clone. Do **not** add an env-var override for the registry path. | One line: `prune skipped — clone is a registered worker/overseer root`. Reason: P2 identifies the *launcher*, not the clone. `bin/hos-human` mints `--app human` in whichever clone it lives in, so `Worker/bin/hos-human` would pass P2 and P4 and trigger the Worker clone's first real reaper run, with a 1-day grace instead of the approved 7. That run would bypass TD-2286 §9.1. This gate is what makes "Human clone only" true. |
| P5 | `default_branch` (as resolved at `:115-120`) is `main`, and `refs/remotes/origin/main` resolves | One line: `prune skipped — default branch is not main` (F4: the reaper is hardcoded to `main`) |
| P6 | `timeout` or `gtimeout` is on PATH (the same detection as `bin/hos-cron:1715-1716`) | One line: `prune skipped — no timeout(1) available`. Runtime must be bounded at session start (§12 Q4). |

Every skip line goes to stdout and starts `hos-repo-sync: `. None of them changes the exit status.

**P0 note on the "successful sync" condition.** The gate is a **successful fetch**, not `sync_ok`. The reaper reads only `origin/main` (TD-2286 §1.3), and the fetch has just refreshed it. Whether the local default branch fast-forwarded makes no difference to any decision, since local `main` is N2-protected. Gating on `sync_ok` would also suppress the prune whenever `main` is behind and the tree is dirty, and untracked `audit/log/**` records make every clone dirty (`TECHNICAL-DESIGN-1538-out-of-band-audit-logging.md:160-163`). The prune would then rarely run.

### 4.2 Placement and exit status

- The prune step runs **after** the state-file write (`:178-186`), so a Ctrl-C or kill during the prune still records the sync.
- The script captures the state-write status as `sync_rc`, runs the prune step, then exits with `exit "$sync_rc"`. **The prune can never change the exit status.** This holds for any reaper rc, a timeout, a missing interpreter or a gate skip.
- The prune step must stay correct under the script's `set -uo pipefail` with no `-e` (`:30`). Capture the reaper rc explicitly. No unset-variable reference may abort the script. This applies in particular to `HOS_REPO_SYNC_PRUNE`, `HOS_TOKEN_APP_ROLE` and `HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS`, so use the `${VAR:-}` form.

### 4.3 Invocation (fixed argv; no other flags)

From `repo_root` (already the cwd after `:70`):

```
<timeout-bin> --kill-after=10 <T> python3 -u -m scripts.automation.readopt \
    --repo <repo_root> reap-orphans --local-only --grace-days 1 --max-deletions 25 --no-issue-closed
```

| Element | Decision and reason |
|---|---|
| `python3` from PATH, not the oversight venv | `readopt` and its imports (`lib/github`, `pre_pr_stale_check`, `lib/stale_commit_detector`, `lib/cycle_log`) are stdlib-only. This matches `bin/hos-cron:1721`, `create_branch.sh:133` and `delete_branch.sh:141`. No `-I`, because `-m` needs the cwd (the repo root) on `sys.path`. P4 guarantees that root is the script's own clone. |
| `-u` | Lines already printed survive a timeout kill (same reason as `hos-cron:1720`). |
| `--local-only` | No remote reads or writes (F1). Remote clean-up belongs to S1 and S2. Passing `--remote-scope` would be a usage error (TD-2288-S1 §4), so it must not be passed. |
| `--grace-days 1` | The TD-2286 7-day grace exists for concurrent worker cycles and re-created branches. The Human clone has no cron (`hos-cron --role human` is rejected). One day still protects a branch created at `main` and not yet committed to, because the reflog's newest entry is the creation time. Without that, D3a would delete it immediately. Seven days would leave every merged human branch present for up to a week, which contradicts "counts stay at zero". See §12 Q2. |
| `--max-deletions 25` | Bounds the blast radius of an unforeseen bug to about the 24 branches the human cleaned by hand. The surplus is printed as `DEFERRED` and handled at the next session. |
| `--no-issue-closed` | §2 and §3. |
| `<T>` | `HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS` if it is a positive integer, otherwise **90**. The default comes from TD-2286 §6: about 13 PR pages at 1-2 s each plus local git calls, roughly 20-40 s, with headroom. The zero-candidate short-circuit (TD-2286 A9) makes most runs 0 API calls. The env var is also the test seam (T-S10). |
| Token | No token is passed or minted. `gh` uses the inherited `GH_TOKEN` (F5, F7). With no `GH_TOKEN`, `gh` may read with the operator's own `gh` login. That is acceptable because this path performs **reads only**, and the decisions do not depend on who reads. With no usable auth, the reaper exits 2 and deletes nothing. |

### 4.4 Output

- Every line the reaper writes to stdout or stderr is merged, then re-emitted on stdout with the prefix `hos-repo-sync: prune: `, in order. Streaming is preferred, but capturing and then emitting is acceptable provided lines printed before a timeout kill are still emitted. A real run prints only `REAPED` / `REAP-FAILED` / `DEFERRED` / `WARN:` lines and the final `SUMMARY` (TD-2286 §4), so the output stays small.
- *[architect]* If the output is piped through a prefixer (for example `… 2>&1 | sed …`), take the reaper rc from `PIPESTATUS[0]`, the timeout/python process, and never from the prefixer. Under `pipefail`, `$?` is the status of the rightmost non-zero stage, so a prefixer failure would be reported as the reaper's rc and could also mask the `(timeout)` classification. T-S9 and T-S10 assert the exact rc in the WARN line, so they catch a wrong capture.
- No reformatting and no summarising. The `SUMMARY` line is item 4's future input and must reach the log verbatim.
- If the reaper rc is non-zero, emit one extra line on **stderr**: `hos-repo-sync: prune: WARN: readopt reap-orphans exited <rc>[ (timeout)] — branches were deleted only where a REAPED line appears above; sync result unaffected`. `(timeout)` is added for rc 124 or 137 (the same classification as `hos-cron:1736`).
- Line safety: branch names in the reaper's output have already passed N1 or been percent-encoded, and WARN text goes through `_one_line` (CWE-117, TD-2286 §4). The sync adds only the fixed prefix.

### 4.5 Header doc

The header comment gains a short paragraph covering:
- the prune exists, is off unless `HOS_REPO_SYNC_PRUNE=1`, and `bin/hos-human` turns it on;
- Human clone only (gates P2, P4 and P4b *[architect]*);
- `--local-only`, and the four allowed reasons;
- opt-out `HOS_REPO_SYNC_PRUNE=0`, and the timeout variable;
- the prune never changes the exit status;
- a pointer to this TD.

The usage block gains the two env vars. Header line 2, the index one-liner, gets " (Human clone: also prunes merged/closed local branches, #2288)" only if `scripts/framework/regen_all.sh --check` stays consistent once the index is regenerated in the same commit.

## 5. `bin/hos-human`

Change only line 112 so that the session-start call sets the variable **for that one command**, defaulting to on and keeping an operator opt-out:

- The call becomes `HOS_REPO_SYNC_PRUNE="${HOS_REPO_SYNC_PRUNE:-1}" bash "$REPO_ROOT/bootstrap/hos_repo_sync.sh" || true`.
- It must **not** `export` the variable. That keeps the in-session human-proxy sync (F9) prune-off, so no prune runs inside the sandbox or with a token that has expired after an hour.
- Update the comment above the call to say it also prunes merged/closed local branches (#2288 S3) and that `HOS_REPO_SYNC_PRUNE=0` opts out.

## 6. Sandbox behaviour

- **Expected path:** none. Only `bin/hos-human` opts in, and it runs unsandboxed before `exec claude` (F7).
- **If an operator exports `HOS_REPO_SYNC_PRUNE=1` globally:** `hos-human`'s `${…:-1}` keeps it, `exec claude` inherits it, and an in-session sync then prunes inside the sandbox. This is benign:
  - If the sandbox blocks writes under `.git`, the fetch itself fails, so the script exits 1 before P0 and nothing prunes.
  - If `.git` is writable, deletes go through `update-ref -d <ref> <sha>`, a CAS ref transaction that uses lock files. A blocked lock fails the transaction cleanly. The reaper prints `REAP-FAILED … reason=delete-failed`, leaves the ref and any record in place, and exits 0 (`readopt.py:1173-1177`, `_delete_branch:287-309`).
  - A blocked or expired GitHub read gives exit 2 with nothing deleted (F3, F5).
- None of these cases changes the sync's exit status (§4.2).

## 7. Tests (pytest; no network; no real `gh`)

### 7.1 `tests/automation/test_hos_repo_sync.py`

**Harness extension.** Add a helper that copies `bootstrap/hos_repo_sync.sh` into `<clone>/bootstrap/` and runs that copy with `cwd=<clone>`, so that P4 holds. A second helper writes a **stub** `<clone>/scripts/__init__.py`, `<clone>/scripts/automation/__init__.py` and `<clone>/scripts/automation/readopt.py`. The stub:
- appends its `sys.argv[1:]` and `os.getcwd()` as one JSON line to `$PRUNE_CAPTURE`;
- prints `$PRUNE_STUB_OUT` lines;
- sleeps `$PRUNE_STUB_SLEEP` seconds (default 0);
- exits `$PRUNE_STUB_RC` (default 0).

It imports only the stdlib. The stub makes no network or `gh` call, which is the PR #2270 lesson. Set `PYTHONDONTWRITEBYTECODE=1`. Prune tests use `RepoEnv(default_branch="main")`. `_run_script` (the existing helper) must **remove** `HOS_REPO_SYNC_PRUNE` and `HOS_TOKEN_APP_ROLE` from the inherited env, so the existing tests cannot be affected by the developer's shell. The prune helper sets them explicitly.

| ID | Setup | Expected |
|---|---|---|
| T-S1 (acceptance) | `PRUNE=1`, `ROLE=human`, stub present, `interval=0` | Stub invoked exactly once. argv is `--repo <clone realpath> reap-orphans --local-only --grace-days 1 --max-deletions 25 --no-issue-closed`, cwd is the clone, exit 0 |
| T-S2 | As T-S1, run twice with `interval=900` | *[Amended by #2322]* Stub invoked twice: the second run takes the skip path and still prunes |
| T-S3 | As T-S1, origin set to a nonexistent path (fetch fails) | Exit 1 (unchanged), stub not invoked, `prune skipped — fetch failed` printed *[#2322]* |
| T-S4 | `PRUNE` unset, then `PRUNE=0`, with `ROLE=human` and the stub present | Not invoked, no `prune` text in the output, exit 0 |
| T-S5 | `PRUNE=1`, `ROLE=worker`, then `ROLE` unset | Not invoked, `not the human role` line, exit 0 |
| T-S6 (module absent) | `PRUNE=1`, `ROLE=human`, no stub | Exactly one `prune skipped — scripts/automation/readopt.py not present` line, exit 0 |
| T-S7 (own clone) | Stub present in clone A. Run **the real repo `SCRIPT`**, not a copy, with `cwd=` clone A | `not this script's own clone` line, the stub is not invoked, exit 0. The HOS repo's real readopt does not run, because the gate precedes invocation. Assert that by having the stub's capture stay empty, and by `PRUNE_CAPTURE` being set only in this env. *[architect]* Also assert that no line containing `SUMMARY ` appears in stdout or stderr. The real readopt always prints `SUMMARY`, so this catches a P4 regression that silently ran the real engine. The stub-capture check alone cannot see that. |
| T-S8 | `RepoEnv(default_branch="trunk")`, stub present, gates otherwise open | `default branch is not main` line, not invoked |
| T-S9 (exit isolation, parametrized) | Stub rc 1, rc 2, rc 3 | Sync exit 0 every time. stderr contains `WARN: readopt reap-orphans exited <rc>` and `sync result unaffected` |
| T-S10 (timeout) | `PRUNE_STUB_SLEEP=10`, `HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS=1`, and the stub prints one line before sleeping. Skip if neither `timeout` nor `gtimeout` exists. | Exit 0 in under 15 s. The pre-sleep line appears with the `hos-repo-sync: prune: ` prefix, and stderr contains `(timeout)` |
| T-S11 (pass-through) | Stub prints `REAPED branch=human/x reason=pr-merged where=local pr=#5 tip=<40 hex>` and a `SUMMARY …` line | Both appear verbatim after the `hos-repo-sync: prune: ` prefix, in order |
| T-S12 (dirty tree, behind) | `advance_remote()`, dirty `README.md` on `main`, gates open | The STALE report is unchanged, the stub **is** invoked (P0 is fetch success, §4.1), exit 0 |
| T-S14 (P4b) *[architect]* | Gates otherwise open, stub present, `HOME` set to a temp dir whose `.config/hos/projects.conf` holds `x_worker_root=<clone>/` (trailing slash), then `x_overseer_root=<clone>`. A third case uses a registry listing only an unrelated path. | First two: `clone is a registered worker/overseer root` line, stub not invoked, exit 0. Third: stub invoked once. All other prune tests also set `HOME` to a temp dir with no registry, so the developer's real `projects.conf` can never affect them. |
| T-S13 (P6) | Gates open, with `PATH` restricted to a directory holding only `git`, `python3` and the coreutils the script needs, and no `timeout`/`gtimeout`. Skip if that cannot be built portably. | `no timeout(1) available` line, not invoked, exit 0 |

All existing tests must pass unchanged. They run the real script against temp clones, so P1 (with the env stripped) keeps them prune-silent.

### 7.2 `tests/automation/test_readopt.py`: `--no-issue-closed`

Use the existing `repo` fixture and `reap(...)` helper, passing `issue_closed=False`.

| ID | Setup | Expected |
|---|---|---|
| NI1 | The T6 setup (`worker-30-x`, unlanded, issue 30 closed) with the flag set | `KEEP branch=worker-30-x reason=issue-closed-unlanded` in dry-run, and the branch survives a real run. Without the flag the result is unchanged: REAPED `issue-closed` (T6 still passes). |
| NI2 | `worker-31-x` on closed issue 31 whose content is squash-landed on main, with the flag | REAPED `landed-content` |
| NI3 | With the flag: a `worker-32-x` local tip at a closed PR's head with issue 32 open, and a `fix/y` at a merged PR's head | `KEEP … reason=closed-pr-open-issue` (A1 still applies); REAPED `pr-merged` |
| NI4 | With the flag: `worker-33-x` on closed issue 33 with a commit message referencing `#99`, and a recording `issue_states` fake | The fake receives `{33}`, not `{33, 99}` (§3 point 4) |
| NI5 | CLI: `reap-orphans --local-only --no-issue-closed --dry-run` via `main([...])` with the fakes patched in the way the existing CLI tests do | Exit 0, and the flag reaches `reap_orphans` as `issue_closed=False` |

### 7.3 `tests/automation/test_hos_human_launcher.py`

| ID | Case | Expected |
|---|---|---|
| HH1 | Static source check | The sync line matches `HOS_REPO_SYNC_PRUNE="${HOS_REPO_SYNC_PRUNE:-1}" bash "$REPO_ROOT/bootstrap/hos_repo_sync.sh" \|\| true`, and no non-comment line contains `export HOS_REPO_SYNC_PRUNE`. *[architect]* Both checks consider **non-comment lines only**. The updated comment above the call may quote the variable name, and a first-occurrence match on a comment would pass for the wrong reason (the test-anchor trap). Assert exactly one non-comment line invokes `hos_repo_sync.sh`. |

## 8. Files the coder touches (6 or 7 files, under the 15-file cap)

| File | Kind | Est. changed lines |
|---|---|---|
| `bootstrap/hos_repo_sync.sh` | Prune step (gates, invocation, output, exit), header | ~55 |
| `bin/hos-human` | Line 112 plus comment | ~3 |
| `scripts/automation/readopt.py` | `--no-issue-closed` flag, parameter, `_decide_rest` change, docstring | ~15 |
| `tests/automation/test_hos_repo_sync.py` | Harness plus T-S1 to T-S13 | ~170 |
| `tests/automation/test_readopt.py` | NI1 to NI5 | ~60 |
| `tests/automation/test_hos_human_launcher.py` | HH1 | ~10 |
| `SCRIPTS-INDEX.md` | Regenerated only if header line 2 changes | 0-1 |
| **Total** | | **~315** (code ~75, tests ~240), plus this TD (~230) if it is committed on the same branch |

The code and tests stay under the 400-line `diff_size` floor. Committing this TD on the same branch would push the total past it. The test files are the bulk, so the coder must land the tests in the **same** commit as the code they cover, not as a later re-tiering commit (S1's lesson). Suggested commits, at most 4: (1) readopt flag plus NI tests; (2) sync prune plus T-S tests; (3) hos-human plus HH1; (4) index regen, if any. Domains are `scripts`, `bootstrap` and `other` (`bin/`, `tests/`), so the R2 split advisory fires. It is advisory only and accepted, because the three parts are one feature.

## 9. Doc rows: deferred (protected and top-level-authored)

| File:line | Suggested change | Who edits |
|---|---|---|
| `CLAUDE.md:363` ("Repo sync" row) | Append: "; when started by `bin/hos-human`, also prunes local branches whose PR is merged/closed or whose content is on main (#2288 S3; `HOS_REPO_SYNC_PRUNE=0` opts out)" | **Human only** (human-owned, protected) |
| `CLAUDE.md:520` (Session start step 4) | The same note in brief | **Human only** |
| `.claude/agents/worker.md:134` | **No change needed.** The worker never prunes (P1, P2), so the row stays accurate. | n/a. A top-level session could add "(prune is Human-clone only)". This is optional. |

This slice designs none of these edits in. All are optional for correctness.

## 10. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | A human branch with unpushed work is deleted | D2 is excluded (§3). The remaining reasons require a covering merged or closed PR, or content on `main`. A tip with commits beyond the PR head is KEEP `unlanded-pr-sha-mismatch` (TD-2286 A5). |
| R2 | The Worker clone's first real reaper run is triggered outside TD-2286 §9.1 | P4b *[architect]* (not a registered Worker/Overseer root) is the gate that carries this. P2 (role `human`) and P4 (own clone) cannot carry it alone, because `Worker/bin/hos-human` satisfies both. The default is off (P1), and the worker tool row and the in-session syncs stay prune-off. Residual: an unregistered Worker clone running `bin/hos-human`. No cron runs there, and every allowed reason is lossless or recoverable (§2). |
| R3 | Session start hangs on a GitHub stall | P6 plus the 90 s timeout with `--kill-after=10`. The zero-candidate short-circuit applies, and a kill mid-delete leaves at worst some branches undeleted (TD-2286 §6). |
| R4 | Code execution from an arbitrary repo's `scripts/automation/` | P4: only the script's own clone runs, which is the same trust as the script itself. |
| R5 | A just-created branch at `main` is deleted (D3a) | The 1-day grace, because the reflog creation time is the newest timestamp. It is also lossless, since the branch content is `main`. |
| R6 | A read under an unintended `gh` identity (no `GH_TOKEN`) | Reads only (F1). The decisions are identity-independent, and no write path exists. |
| R7 | A closed PR the human means to reopen loses its local branch | Only after the 1-day grace from the last commit or reflog entry. Recovery is `git fetch origin pull/<N>/head:<name>`. Opt-out is `HOS_REPO_SYNC_PRUNE=0`. |
| R8 | The output prefix breaks a downstream parser | No parser consumes the sync output today. Item 4 can strip the fixed prefix. |

## 11. Startup-gap and sign-off analysis

- **Should this have been settled in the initial design?** No. Item 3 is a new requirement from #2288 (2026-11-08). TD-2286 deliberately left non-worker and Human-clone clean-up to #2288. This is not a missing edge case in an approved contract, so no `startup-artifact-gap` issue is needed.
- **Affected sign-offs:**
  - TD-2286, TD-2288-S1 and TD-2288-S2 stand. `--no-issue-closed` is opt-in, its default path is byte-identical, and every existing `reap_orphans` test proves that.
  - Earlier `hos_repo_sync.sh` sign-offs (#1200 and so on) stand. The prune is off by default (P1) and placed after every existing path, and all existing tests are unchanged.
  - Earlier `bin/hos-human` sign-offs stand. The only change is a per-command env assignment on the existing best-effort line.
  - No code already approved against an old contract is left orphaned.

## 12. Open points for architect review

1. **D2 narrowing (§2, §3).** The alternative is no new flag, accepting `issue-closed` in the Human clone on the grounds that F11 makes it currently unreachable. That saves about 75 lines (code and tests) but leaves a lossy reason outside the item text that only usage habits keep unreachable. My recommendation is the flag.
2. **Grace of 1 day instead of `DEFAULT_GRACE_DAYS` (7) (§4.3).** 0 would delete freshly created, uncommitted branches. 7 would contradict "counts stay at zero". Is there a reason to keep 7 in the Human clone?
3. **Opt-in model (§4.1 P1/P2, §5).** The design uses a script default of off, a per-command default of on in `bin/hos-human`, and a hard role gate on `HOS_TOKEN_APP_ROLE=human`. The alternative is a script default of on with only an opt-out. That is simpler, but every sync caller would then prune, including the worker tool row and the sandboxed in-session sync, and P2 would carry the whole Worker-clone safety. Is relying on `HOS_TOKEN_APP_ROLE`, which `get_app_token.sh` exports, acceptable as a scoping marker?
4. **No `timeout`/`gtimeout` (P6).** Skip, or run unbounded? I chose skip so session start stays bounded. On stock macOS that means the prune never runs until coreutils is installed.
5. **P0 uses fetch success, not `sync_ok` (§4.1 note).** The brief said "after a successful sync". I read that as "fresh `origin/main`", because gating on `sync_ok` would suppress the prune in every dirty-tree session.
6. **`--max-deletions 25`.** Is a fixed cap acceptable, or should it be configurable?

### 12.1 Architect rulings *[architect]*, 2026-11-09

1. **Keep `--no-issue-closed`.** D2 is the only lossy reason, and the item text does not cover it. F11's "unreachable" is a fact about how the clone is used today, not something the code guarantees. The CLAUDE.md exception path puts `worker-*` branches into this clone on purpose. The flag is a filter on an existing rule: it adds no decision, its default is byte-identical, and `test_readopt.py` proves that. I also checked that the new KEEP token is necessary, not cosmetic. With D2 suppressed, a `worker-*` branch on a closed issue that has not landed and has no PR falls through the `:1239-1252` chain to the `else`, which reports `unlanded-no-pr`. That is wrong whenever the branch has a non-covering PR or a known issue. Insert `issue-closed-unlanded` at the position given in §3 point 3. The cost is about 75 lines, and that is accepted.
2. **Grace 1 day is accepted.** The 7-day grace exists for concurrent cron cycles and re-created branch names. Neither applies in a clone with no cron, and P4b now keeps this argument from leaking into clones where they do apply. G1 takes the newest of the committer date, the reflog and the record mtime (`readopt.py:1030-1049`), so a branch freshly created at `main` is protected. Zero is rejected for the reason §4.3 gives.
3. **Accepted, with P4b added.** The gate is live. `get_app_token.sh:219` exports `HOS_TOKEN_APP_ROLE`, `bin/hos-human:99` sources it, and the sync runs at `:112`. `human` is also in `lib/github.py:51` `_REMINT_ROLES`, so a 401 re-mint works on this path. However, P2 identifies the token role, which means the launcher, and not the clone. `bin/hos-human` hard-codes `--app human` regardless of which clone it is in, and nothing in it refuses a Worker clone, so P2 and P4 together do not deliver "Human clone only" or R2. P4b closes that with the registry `hos-cron` already treats as authoritative. "Script default off, per-command on" is the right model. Script-default-on is rejected because it would make P2 and P4b the only things standing between the worker tool row and a real reap.
4. **Skip is accepted.** This deliberately differs from `hos-cron:1715-1721`, which runs unbounded when no timeout binary exists. The difference is justified because session start is interactive and the prune is hygiene. A missed prune costs nothing and the next session catches up. Because `scripts/automation/` is not shipped (F6, P3), stock-macOS consumers are unaffected either way.
5. **Fetch success is accepted.** The decisions depend only on the freshly fetched `origin/main`, and local `main` is N2-protected. Gating on `sync_ok` would turn the prune off in nearly every session, because of the untracked audit records. T-S12 pins this behaviour.
6. **The fixed cap of 25 is accepted. Do not add a knob.** The cap limits the damage an unforeseen bug can do. A configurable cap invites someone to raise it to silence `DEFERRED`, which is exactly when the cap matters. The surplus drains on the next session.

**Size check.** 7 code and test files plus this TD makes 8 files, and the ≤4 code commits plus the TD commit make 5. Both are within ≤15/≤10. P4b and T-S14 add about 15 code lines and 30 test lines to files already listed, and no new files. `diff_size` will floor at HIGH because this TD is on the branch. That is accepted, and the protected-surface CODEOWNER gate applies regardless.
**Protected agent/CLAUDE.md surface.** None is designed in. The §9 rows are deferred to a human or top-level session and are optional for correctness. `bin/hos-human` and `bootstrap/hos_repo_sync.sh` are protected (`bin/**`, `bootstrap/**`) but are not agent definitions, so the coder may edit them under the CODEOWNER gate.
**Startup gap (§11).** I agree: this is not a startup-artifact gap. P4b adds no reach beyond what was approved, and the S1/S2/TD-2286 sign-offs stand.

No human ruling is needed beyond the CODEOWNER review of the protected surfaces and the first-run dry-run evidence.
