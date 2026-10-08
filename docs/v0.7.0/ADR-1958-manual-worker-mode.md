# ADR-1958: Sanctioned manual-worker mode. One clone-role resolver, a launcher-minted interactive cycle identity in its own namespace, a dedicated locked worktree the cron explicitly ignores, and a cross-role refusal at the single token-mint site

**Status:** ACCEPTED FOR DESIGN, **PROVISIONAL** where marked. This ADR binds `technical-design` on the decisions marked BINDING. Decisions marked **PROVISIONAL (ESC-n)** are drafted on the pm-agent default for that escalation. Each one names what changes if the human rules the alternative. No ESC item is treated as ruled. R-1 and R-2 are treated as binding, per the requirements. ESC-0 asks the human to confirm them (§8), and **every decision in this ADR rests on ESC-0**.
**Date:** 2026-10-08
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #1958 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every implementation surface is protected (`bin/**`, `bootstrap/**`, `CLAUDE.md`, `templates/CLAUDE.human.md`, `docs/AGENT-IDENTITY.md`, `.claude/agents/**`), so the human gate applies to every slice whatever its computed tier.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1958-manual-worker-mode.md` (pm-agent; FR-1 to FR-19, NFR-1 to NFR-3, ESC-0 to ESC-7). R-1 and R-2 are binding. Also `docs/v0.6.0/ADR-037-worker-branch-ownership.md` (AD-1 to AD-8 and §6), `docs/v0.7.0/ADR-1415-worktree-hygiene.md`, `docs/v0.7.0/ADR-1604-worker-self-split-isolation.md`, `docs/v0.7.0/ADR-1944-proactive-usage-pause.md` (AF-1/AF-2 placement pattern), `docs/AGENT-IDENTITY.md` §7/§8.1, `.claude/agents/worker.md`, `CLAUDE.md`, `templates/CLAUDE.human.md`, `docs/SANDBOX-POLICY.md`, `contract/sandbox-policy.template.json`. Code was read directly: `bin/hos-worker`, `bin/hos-human`, `bin/hos-overseer`, `bin/hos-cron`, `bootstrap/create_branch.sh`, `bootstrap/submit_pr.sh`, `bootstrap/get_app_token.sh`, `bootstrap/lib/branch_ownership.sh`, `bootstrap/lib/role_clone_check.sh`, `scripts/framework/framework_consumer_files.txt`, `bootstrap/hos_install.sh`, `scripts/framework/protected_surfaces.txt`, `scripts/framework/validate_self.sh`, `scripts/automation/dimension_sweep_cli.py`. Also the live ownership store, `git worktree list`, and `~/.config/hos/projects.conf`.
**Consumers:** `technical-design` (next), then `coder` and the standard review chain. `security-reviewer` is mandatory on S3 and S4. `infra-reviewer` is mandatory on S2 and S3.
**Does not re-open:** R-1 and R-2. ADR-037 AD-1 to AD-4, AD-6 to AD-8. ADR-1415's hygiene algorithm. #1954's disposition (requirements §5: a separate later slice).

---

## 0. Verification findings

Line numbers refer to the working tree at `69d997e5e` (branch base `51f2837a9`, plus the requirements commit).

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `create_branch.sh:96-99` refuses without all three of `HOS_CYCLE_ID`, `HOS_CYCLE_TOKEN` and `HOS_CYCLE_ROLE=worker`. `submit_pr.sh:166-183` runs the ownership refusal in `--app worker` open mode. `:128` makes `--update-pr` worker-only. `:240-248` is the server-side authorship check. The only identity mint is `bin/hos-cron:340-365`, with the grammar `${ROLE}-${_project_safe}-${_cycle_ts}-$$`.
- **VF-2 CONFIRMED.** `bin/hos-worker` (30 lines) does the #1409 check, preflight, `source <(get_app_token.sh --app worker)` and a literal identity guard, then `exec claude --dangerously-skip-permissions`. It mints no identity and creates no worktree.
- **VF-3, VF-4 CONFIRMED.** `submit_pr.sh:137-139` checks only that the bare `--confirmed` is present. `AGENT-IDENTITY.md` §8.1 keys identity on interactive vs autonomous. `templates/CLAUDE.human.md:1-64` is the *source* of the "Human-proxy session identity" block that is injected into `CLAUDE.md`. FR-19 must therefore edit the template as well as `CLAUDE.md`, or the next install re-injects the wrong text.
- **VF-5 CONFIRMED, and larger than stated.** The reaper (`hos-cron:1376-1458`) skips only `REPO_ROOT`'s current branch. This clone's `audit/log/2026/10/` (committed plus untracked) holds **177** `cycle-branch-reap-failed` events for `interactive-1989-…`. Only git's checked-out-elsewhere refusal saves that branch.
- **VF-6 to VF-8 CONFIRMED.** The live record `interactive-1989-…-1989.rec` carries `cycle_id=worker-hos-interactive-261005193700-1989`. That shape is the VF-8 grammar.

### 0.2 My own findings (these shape the decisions)

**AF-1: the interactive marker cannot live in `role=`.** `hos_bo_verify` (`branch_ownership.sh:259`) requires `role == "worker"`. FR-6(c) requires the *unchanged* ownership model, so the marker must be carried **in the cycle id**. Then the existing `wrong_cycle` comparison gives FR-6's cross-identity separation for free, in both directions.

**AF-2: the existing sibling heuristic misclassifies linked worktrees.** `/home/scott/Code/HumanOversightSystem/Worker-1989` is a *linked worktree of the Worker clone*. It sits in the same parent directory as `Worker/`, `Overseer/` and `Human/`. `bin/hos-human:51-63` treats any directory whose `dirname` matches a registered root's `dirname` as the Human clone, so it would call that worktree human-proxy. A resolver that keys on the path, not on the git common directory, contradicts R-1 for every worktree this ADR creates.

**AF-3: a worktree nested in `REPO_ROOT` would be destroyed.** ADR-1415 hygiene (`hos-cron:567-590`) enumerates every non-ignored untracked path in `REPO_ROOT`. A nested worktree shows up as an untracked directory and gets quarantined and deleted when hygiene is on. So the worktree must be outside `REPO_ROOT`. That is a hard constraint, not a preference.

**AF-4: audit events written from a worktree never reach the committed trail.** `_sync_audit_logs` (`hos-cron:447-500`) reads only `$REPO_ROOT/audit/log`. `hos_bo_audit_refusal` and `submit_pr.sh` write to `$SCRIPT_DIR/..`, which inside a worktree *is* the worktree. Events written there are orphaned. Because `audit/log/` is untracked and not ignored, a `git add -A` can also pick them up onto the PR branch. FR-12's "committed audit trail" AC fails unless the audit root is resolved to the clone's main worktree.

**AF-5: `git worktree prune` runs every cycle** (`hos-cron:472`, inside audit sync). It removes administrative data for worktrees whose directory is gone. A **locked** worktree is exempt.

**AF-6: `HOS_CYCLE_ROLE` already means "this is a cron cycle" to two tools.** `validate_self.sh:164` refuses keychain auth, and `dimension_sweep_cli.py:116` refuses W6, whenever `HOS_CYCLE_ROLE` is set. An interactive session that exports `HOS_CYCLE_ROLE=worker` (needed by `create_branch.sh:96` and `hos_bo_write_record:127`) inherits both vetoes. Both are one-direction refusals, so the effect is stricter, not looser.

**AF-7: `get_app_token.sh` is the single token-mint site.** All ten mutating `bootstrap/` scripts call it (`submit_pr`, `create_branch` indirectly via `submit_pr`, `post_comment`, `create_issue`, `edit_issue`, `edit_issue_edges`, `escalate_to_human`, `post_review_thread`, `pr_review`, `merge_authority`). So do `query_issues.sh`, all three launchers and `hos-cron:907`. "Refused before any token is minted" (FR-2) has exactly one natural chokepoint.

**AF-8: consumer shipping is uneven.** `framework_consumer_files.txt` ships `get_app_token.sh`, `create_branch.sh` and `branch_ownership.sh`. It does **not** ship `bin/hos-worker`, `bin/hos-overseer` or `bootstrap/lib/role_clone_check.sh`. Any library that `get_app_token.sh` starts sourcing **must** be added to that list in the same slice. Otherwise every consumer token mint fails after upgrade (NFR-3).

**AF-9: ESC-2's default cannot be built as written.** The default is "a role-naming argument … accepted only in an interactive TTY session". Scripts invoked from a Claude session have no controlling terminal: `tty` in this session prints `not a tty`. The chokepoint therefore cannot observe a TTY, and any argument it accepts is supplied by the model. That makes the argument the same thing as today's `--confirmed`: an assertion, not an authorization. See AD-7.

**AF-10: Worker and Overseer sessions are unsandboxed today.** They run with `bypassPermissions` (`SANDBOX-POLICY.md` table, row "Interactive worker"); sandboxing is #1146. Every file under the clone and under `~/.hos` is writable by a cron model. ADR-037 AD-8's standard ("a correctness guard, not a security boundary") therefore still governs. §3 states exactly what FR-14 achieves under that standard.

**AF-11: a fresh worktree lacks untracked tooling.** `scripts/oversight/.venv` (the Python tooling the agents use) and `.claude/settings.local.json` exist only in the main checkout.

**AF-12: the VF-8 legacy cycle id parses as a cron id.** `worker-hos-interactive-261005193700-1989` is a well-formed cron id for a project named `hos-interactive`. Cycle-id grammar alone cannot identify legacy interactive records. The branch prefix `interactive-` can.

---

## 1. Organizing principle

**Role is a property of the clone. Authority to open PRs is a property of a launcher-minted identity. Isolation is a property of the worktree.** The three are separate mechanisms and must not stand in for each other:

- the resolver answers "who may this clone act as" (R-1);
- the cycle identity answers "may this session open a PR for this branch" (ADR-037, extended);
- the worktree answers "can this session disturb the cron's checkout" (#1945).

One rule from ADR-037 carries over unchanged: **an identity's absence is the fail-closed hinge.** The interactive identity adds a second minting site. It does not add a second meaning of "valid".

---

## 2. Decisions

### AD-1: One clone-role resolver, `bootstrap/lib/clone_role.sh`. It resolves through the git common directory, never the path. (BINDING; FR-1, FR-17, AF-2, AF-7.)

A sourced library with no side effects, in the style of `branch_ownership.sh`. It lives on protected surface (`bootstrap/**`), as ADR-1944 AF-2 requires of code on a decision path. One function:

`hos_clone_role <path>` sets `HOS_CLONE_ROLE` ∈ {`worker`, `overseer`, `human-proxy`, `unresolved`}, `HOS_CLONE_PROJECT` (the registry key prefix, or empty), `HOS_CLONE_MAIN_ROOT` and `HOS_CLONE_REASON`.

Algorithm (order is binding):
1. `main_root` = the main worktree of the repository containing `<path>`. Derive it from `git rev-parse --path-format=absolute --git-common-dir`, then `realpath`. A linked worktree therefore resolves to its clone (AF-2). If this is not a git repository, the result is `unresolved`.
2. Exact match of `main_root` (realpath on both sides, trailing `/` stripped) against `<p>_worker_root` gives `worker`. Against `<p>_overseer_root` it gives `overseer`. More than one match gives `unresolved`, reason `ambiguous`.
3. Otherwise, if `dirname(main_root)` equals `dirname` of a registered root for exactly one project, **and** `main_root` is not itself a registered root, the result is `human-proxy`. This is today's `hos-human` sibling rule, applied to `main_root`. **The heuristic can only ever yield `human-proxy`. It can never yield `worker` or `overseer`.**
4. Otherwise `unresolved`. This includes a missing or unreadable `projects.conf`.

It reads only `$HOME/.config/hos/projects.conf`: parsed, never sourced, same as `role_clone_check.sh`. There is no override flag and no environment escape (ADR-037 AD-6). App-role names map as `--app worker` → `worker`, `--app overseer` → `overseer`, `--app human` → `human-proxy`.

Every call site uses it: `role_clone_check.sh` becomes a thin wrapper, so `bin/hos-overseer` keeps its API. Also `bin/hos-worker` (AD-3), `bin/hos-human` (it refuses when the clone resolves to `worker` or `overseer`, which closes R-1's reverse direction), `get_app_token.sh` (AD-7) and the mutating scripts (AD-7). `bin/hos-human`'s separate `config_dir` lookup may reuse `HOS_CLONE_PROJECT`, but that is `technical-design`'s call. This ADR adds **no** `<p>_human_root` registry key. Adding one would be a narrowing change and stays available for later.

### AD-2: The interactive cycle identity: its own namespace, launcher-minted, verified by the unchanged ownership model. (BINDING on the namespace and invariants; exact regex is `technical-design`'s within these constraints. FR-6, FR-8, FR-12, FR-14, AF-1.)

**Grammar:** `HOS_CYCLE_ID=interactive-worker-<project_safe>-<ts12>-<pid>`
- `<project_safe>` is `HOS_CLONE_PROJECT`, sanitized exactly as `hos-cron:355` does.
- `<ts12>` is `date -u +%y%m%d%H%M%S`, also exported as `HOS_CYCLE_TOKEN`.
- `<pid>` is the **launcher's** `$$`. Under AD-3 the launcher stays alive as the parent of `claude` for the whole session.
- `HOS_CYCLE_ROLE=worker`.

No new exported variable is introduced. ADR-037 §6 forbids widening the minted set.

Why this satisfies FR-6:
- **(a) Interactive by construction.** The first field is `interactive`. `hos-cron` only accepts `--role worker|overseer` and puts `$ROLE` first, so no cron id can start with `interactive-`. The two namespaces are disjoint on the first field. Unlike the VF-8 shape, this does not depend on how project names happen to parse (AF-12).
- **(b) No collisions.** Against cron: different first field. Against other interactive sessions, including the same issue in the same second: each launcher's PID stays alive for its whole session, so two live sessions cannot hold the same PID. A later session in the same second would need PID reuse within one second, which is the same bound ADR-037 AD-5 accepted for cron. The timestamp covers reuse across reboots.
- **(c) Unchanged ownership model.** `create_branch.sh` still extracts the trailing numeric PID field. The record is still `schema=1`, `role=worker`, `cycle_id=<id>`. `hos_bo_verify` is not modified. A record written by an interactive identity fails `wrong_cycle` under every cron identity, and the reverse also holds, because the strings differ. **The AC holds by construction, and S3's tests must prove it rather than assume it.**

**Branch namespace:** under an interactive identity, `create_branch.sh` forces the branch prefix to `interactive`: `interactive-<issue>-<slug>-<ts12>-<pid>`. Passing `--prefix` with any other value is refused. Under any **non-interactive** identity, `--prefix interactive` is refused. That reserves the `interactive-*` namespace (S2). This is a narrowing for cron, permitted under FR-18.

**The grammar is defined in one place:** `hos_bo_is_interactive_cycle_id <id>` and `hos_bo_is_interactive_record <path>` in `branch_ownership.sh`. A record counts as interactive if its `cycle_id` matches the new grammar **or** its `branch=` starts with `interactive-`. The second clause catches the VF-8 legacy records (AF-12). No other file parses the grammar.

**Lifetime (FR-8):** the identity is valid only while its **session record** (AD-4) is live. `claude --resume`, a relaunch, or any new `hos-worker` run mints a new identity. Under the unchanged `wrong_cycle` rule, a new identity cannot open a PR for an earlier identity's branch. The only route is ADR-037 `--from` with the full review chain re-run.

### AD-3: Launcher: extend `bin/hos-worker`. It mints only for a human-present, non-cron, non-model invocation, then supervises the session. (PROVISIONAL (ESC-7) on the file name; PROVISIONAL (ESC-1) on the typed confirmation; everything else BINDING. FR-5, FR-14, FR-15, FR-17, FR-18.)

`bin/hos-worker` **becomes** the manual-worker launcher. The old mode (a worker-token session in `REPO_ROOT` with no identity) is **removed, not kept beside it**. That old mode is exactly the #1945 hazard, and keeping it would be the parallel path FR-5 forbids. There is one entry point (D41). The launcher takes no argument that supplies, overrides or skips identity, worktree, role or any check (FR-18). Any pass-through to `claude` (for example `--resume`) is `technical-design`'s call within that constraint.

**Mint preconditions.** All of these must hold before anything is minted, and any failure refuses with a diagnosable message and an `interactive-mint-refused` audit event (NFR-2):
1. `hos_clone_role "$REPO_ROOT"` is exactly `worker` (FR-17). `unresolved` refuses whatever ESC-3 rules, because FR-17 requires a *resolved* worker clone.
2. No `HOS_CYCLE_ID`, `HOS_CYCLE_ROLE` or `HOS_CYCLE_TOKEN` is set.
3. No model-session marker is set (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`). A session cannot launch a nested manual-worker session.
4. Standard input and output are TTYs, and `/dev/tty` opens.
5. **Positive-evidence ancestry check:** no ancestor process is `bin/hos-cron` or a `claude` process. On Linux, walk `/proc/<pid>/stat` parents. Elsewhere, use `ps -o ppid=,command=`. This check refuses only on *positive* evidence. An unreadable ancestor is not treated as evidence.
6. **PROVISIONAL (ESC-1, default):** a typed confirmation read from `/dev/tty`, never from stdin. The launcher prints a random short challenge plus the clone, project and resulting identity, and the human types the challenge back. *If ESC-1 rules TTY-only:* step 6 is deleted. Nothing else changes, and the session record's `confirmation=` field records `tty-only`.

**Then, in order:**
- `git fetch origin` (refuse on failure);
- create the worktree (AD-4);
- write the session record (AD-4);
- mint the worker token through the temp-file pattern (`hos-human:90-99`), replacing `source <(…)` (VF-2);
- run the identity guard against `HOS_EXPECTED_BOT_LOGIN`, not a literal;
- emit `interactive-session-start` (AD-6);
- `cd` into the worktree;
- run `claude` **as a child process, not via `exec`**.

The launcher stays the parent so that it can retire the identity and clean up when the session ends (AD-4, ESC-6). It traps `EXIT`, `HUP`, `INT` and `TERM`. The launcher **never** invokes `bin/hos-cron` and never takes or touches the cron lock (#1616).

**Version lockstep (NFR-3).** The launcher runs from `REPO_ROOT`, while the chokepoint scripts the session will call run from the worktree, which is checked out at `origin/main`. Before writing the session record, the launcher probes the worktree's `bootstrap/lib/branch_ownership.sh` and `bootstrap/lib/clone_role.sh` for a protocol constant (`HOS_INTERACTIVE_PROTOCOL=1`, defined in `branch_ownership.sh`). If the constant is absent or different, the launcher refuses, names both versions, and removes the worktree. It never fails open.

*If ESC-7 rules the alternative* (`bin/hos-worker-interactive`): the same content ships under the new name, and `bin/hos-worker` is **deleted in the same slice**. It is not kept as an alias with weaker guarantees. Nothing else changes.

**Consumer shipping (AF-8):** `bin/hos-worker`, `bootstrap/lib/clone_role.sh`, `bootstrap/lib/role_clone_check.sh` and `bootstrap/lib/interactive_session.sh` are added to `framework_consumer_files.txt`. This is a product-visible addition for consumers: a new launcher. It is routed under ESC-7.

### AD-4: The dedicated worktree and the session record. (BINDING; FR-8, FR-9, FR-11, FR-14, AF-3, AF-5, AF-11.)

**Worktree.** `git worktree add --detach --lock --reason "hos interactive <cycle_id>" <wt> origin/main`. Constraints on `<wt>` (exact path is `technical-design`'s):
- It is outside `REPO_ROOT`, and is neither nested in nor a parent of any registered root (AF-3).
- It is not under `~/.hos` (a future #1146 sandbox may deny writes there).
- It is deterministic from the cycle id and unique per session.
- It is not named like a sibling clone (AF-2). The indicative shape is `<parent-of-clone>/.hos-worktrees/<project>/<cycle_id>/`.

`--lock` protects it from the cron's `git worktree prune` (AF-5). The launcher refuses if `<wt>` already exists. Branches are created *inside* this worktree by `create_branch.sh` (AD-5). The launcher creates none. **At no point does the launcher change `REPO_ROOT`'s HEAD, index or working tree** (FR-9 AC).

The session's cwd is `<wt>`, so cwd-relative writes (`.claudetmp/`, the sign-off register, subagent output) land in the worktree (FR-11). **Obligation on `technical-design` (AF-11):** establish how the session gets `scripts/oversight/.venv` and any required `settings.local.json` content without writing into `REPO_ROOT` and without committing them. Symlinking, or a launcher-run venv bootstrap, are both acceptable. Copying secrets is not.

**Session record:** `<git-common-dir>/hos/interactive-sessions/<cycle_id>.session`. It is clone-scoped and needs no environment escape, which mirrors ADR-037 AD-7's store reasoning. Strict `key=value` with no comments, written atomically, never sourced:

`schema=1`, `cycle_id`, `state=live|ended`, `worktree=<realpath>`, `main_root`, `launcher_pid`, `launcher_start=<proc start time>`, `boot_id=</proc/sys/kernel/random/boot_id or platform equivalent>`, `tty=<device>`, `confirmation=typed|tty-only`, `created_at`, `ended_at`.

A new library, `bootstrap/lib/interactive_session.sh`, owns the write, verify and retire functions. `hos_is_verify_session <repo_dir>` passes only if **all** of these hold:
- `HOS_CYCLE_ID` has the interactive grammar;
- the record exists, is well-formed and has `state=live`;
- `boot_id` matches the current boot;
- if `/proc/<launcher_pid>` is visible, its start time equals `launcher_start` (positive evidence only, so a PID namespace that hides it is not a failure);
- `realpath(git -C <repo_dir> rev-parse --show-toplevel)` equals `worktree`, and that toplevel is a **linked** worktree (`--git-dir` ≠ `--git-common-dir`);
- the AD-3 step-5 ancestry check finds no `bin/hos-cron` ancestor.

On exit the launcher sets `state=ended` and `ended_at`. A launcher killed with SIGKILL leaves `state=live`, but the PID and start-time check (where visible) and the `boot_id` check bound how long that stale record stays usable.

### AD-5: Chokepoint behaviour under an interactive identity. Same scripts, one extra predicate, no new flag. (BINDING; FR-6, FR-7, FR-9, FR-14, FR-16.)

- **`create_branch.sh`.** If `HOS_CYCLE_ID` has the interactive grammar, the script requires `hos_is_verify_session "$REPO_DIR"`, or it refuses with the reason class (for example `session_not_live`, `not_session_worktree`, `main_checkout`, `cron_ancestor`) plus an audit event. It then forces the `interactive` prefix (AD-2). This is the FR-9 refusal: run against the cron's checkout, including by absolute path to `REPO_ROOT/bootstrap/create_branch.sh`, the toplevel is the main worktree and the script refuses. Steps 3 to 6 are unchanged: it re-enters only on a record valid for this identity and never adopts an existing branch (FR-16 already holds). There is **no `--interactive` flag**. The mode is selected only by an identity the launcher minted (FR-14).
- **`submit_pr.sh` open mode, `--app worker`.** The same session predicate runs before `hos_bo_verify`, and the ownership check itself is unchanged.
- **`submit_pr.sh --update-pr`.** It needs no session record (FR-8: update rests on authorship). The server-side authorship, head and base check (ADR-037 AD-4) is unchanged, and `--force` is still never used (FR-7). The only additions are the ESC-5 guard (AD-9) and the FR-13 marker (AD-6).
- **The cron path is unchanged** except for the AD-7 clone-role check and S2's reservation of the `interactive` prefix. ADR-037 T1 to T11 must still pass (NFR-1).

### AD-6: Audit and provenance. (BINDING; FR-12, FR-13, AF-4.)

**Audit root.** Every event this ADR adds or changes is written through `audit_write_event` with repo_dir set to `HOS_CLONE_MAIN_ROOT`, the clone's main worktree, not `$SCRIPT_DIR/..`. Under cron that is identical (`$SCRIPT_DIR/..` *is* the main worktree), so cron output does not change. Under an interactive session it routes events into the directory `_sync_audit_logs` actually reads, and keeps them off the PR branch (AF-4). `technical-design` must inventory the other audit writers reachable from a session (for example `cycle_log`) and either route them the same way or list them as a known gap.

**Events.** Every event carries `mode=interactive|cron` (derived via `hos_bo_is_interactive_cycle_id`) and `cycle_id`:
- `interactive-session-start` and `interactive-session-end` (clone role, project, worktree, tty, confirmation kind, protocol version; for end, also branches created, cleanup result);
- `interactive-mint-refused` (reason);
- `branch-ownership-refused` (existing, now with a `mode` field);
- `clone-role-refused` (AD-7);
- a submit event for every interactive open and update.

The ownership record carries the marker inside its `cycle_id` (AD-2). The record schema does not change.

**PR marker (FR-13).** In open mode under an interactive identity, `submit_pr.sh` appends a script-authored footer to a temp copy of the body file: an HTML comment `<!-- hos:authoring-mode=interactive cycle_id=<id> -->` plus one visible line. On every interactive `--update-pr` push it posts one PR comment carrying the same machine marker and the new head SHA.

**The marker cannot be forged through a body:** `submit_pr.sh` refuses, in every mode and for every identity, a body file that already contains `hos:authoring-mode`. Absence of the marker means "cron-authored". The marker is **informational only**. It grants no review, risk or merge privilege, and nothing in overseer, risk or gate logic may branch on it (FR-13). The one exception is AD-9's ESC-5 guard, which uses it only to *narrow* behaviour.

**Why the markers carry real weight:** §8.1's stated reason for giving interactive sessions a separate bot was to make human-directed work auditable. Under R-1 the worker bot does both kinds of work, so these markers are now the **only** thing that tells the two apart. They are not optional decoration.

### AD-7: Cross-role refusal at the token-mint site, with no cross-role exception. (PROVISIONAL (ESC-2) on "no exception"; PROVISIONAL (ESC-3) on fail-closed for unresolved; PROVISIONAL (ARCH-ESC-1) on including reads; the placement is BINDING. FR-2, FR-3, FR-4, AF-7, AF-9.)

**Placement (BINDING).** Two layers, sharing one library function, `hos_require_clone_role <requested-app> <act> <path>` in `clone_role.sh`:
1. **`get_app_token.sh`** resolves the clone of its own location. **If the resolved role is not `unresolved` and differs from `--app`, it refuses before minting**, emits `clone-role-refused`, and names both roles plus "stop and ask the human" (R-2, NFR-2). This one check covers every bootstrap script, every launcher, `hos-cron`, and any hand-built `get_app_token.sh --app human` route. An `unresolved` clone is *not* refused at this layer, so first-install and unregistered-clone flows keep working: `hos_setup_partner.sh:228` prints exactly such a test command.
2. **Each mutating script** (the ten in AF-7) calls `hos_require_clone_role` before its mint, passing an act name. That emits a per-act audit event for both outcomes (FR-3). It also applies the fail-closed rule for `unresolved` (FR-4), and refuses when the clone of `$PWD` and the clone of the script both resolve but differ, so one clone's scripts cannot be driven from another clone's session.

**No cross-role exception (PROVISIONAL, ESC-2 alternative recommended).** AF-9 shows the default ("role-naming argument, TTY only") cannot be built: a chokepoint script never sees a TTY, and any argument is model-supplied, which is the VF-4 defect over again. Under R-1 with manual-worker mode in place, I find **no legitimate cross-role act**:
- the Worker clone acts as worker;
- the Human clone's stuck-worker exception is a *same-role* `--app human` act (that is #1954's territory and unchanged here).

So the refusal is a hard stop with no flag. `--confirmed` keeps its existing meaning for same-role `--app human` from the Human clone. It no longer has any effect on a cross-role act. *If the human rules the default (an exception must exist):* the only mechanism I will accept is a **server-side, human-authored artifact**. That means a comment on the target issue or PR, by an account that is not in `BOT_ACCOUNTS`, that names the role, the act and the target. The script verifies it through the API and consumes it once. A model holding only bot tokens cannot forge that. It would be an additive later slice on top of S4. A flag-based exception is rejected as architecture whatever ESC-2 rules.

**Unresolved (PROVISIONAL, ESC-3 default).** Mutating acts fail closed (layer 2). Launchers keep today's fail-open behaviour, except `hos-worker`, which fails closed under FR-17 whatever ESC-3 rules. *If ESC-3 rules "both fail closed":* `hos-overseer` and `hos-human` also refuse when unresolved, which is one predicate per launcher. Note for the human: under either answer, a consumer's unregistered clone loses mutating bootstrap scripts until it is registered.

**Reads (PROVISIONAL, ARCH-ESC-1).** Because layer 1 sits in `get_app_token.sh`, a positive role mismatch also refuses **reads** (`query_issues.sh --app human` from the Worker clone). That is stricter than FR-2, which names only mutating acts. I include reads because minting another role's token at all is acting as that role, and because excluding reads would need a read/write discriminator the model supplies itself. *If the human rules reads out:* layer 1 moves out of `get_app_token.sh` into the mutating scripts only. A hand-built mint then bypasses the refusal, and that residual has to be stated in the docs.

### AD-8: The cron explicitly excludes interactive branches, records and worktrees. (BINDING; FR-10, FR-9 AC, NFR-1, AF-3, AF-5, AF-12. ESC-6's "never the cron" is common to every option, so this AD does not depend on ESC-6.)

All changes are in `bin/hos-cron` and `branch_ownership.sh`. All of them key on `hos_bo_is_interactive_record` or `hos_bo_is_interactive_cycle_id`, never on git's checked-out-elsewhere refusal:
1. **Reaper (#1498).** Interactive records are skipped *before* any other test, on both deletion paths (zero-commit branch and missing-branch record). Skipped records emit **no** event, so `cycle-branch-reap-failed` stops firing for them. If `branch_ownership.sh` lacks the predicate (version skew), the reaper skips the **whole sweep**. That extends the existing "library absent, skip" guard and fails toward never deleting.
2. **The 30-day prune in `hos_bo_write_record`.** Interactive records are excluded. `find -delete` becomes a per-record loop.
3. **Cycle start.** If `REPO_ROOT`'s HEAD is an `interactive-*` branch, the invariant is violated: a human session may be live in the shared checkout (#1945). The cron then **skips the cycle before hygiene, #1044 return-to-main and the reaper**. It emits `cycle-skipped-interactive-checkout` and writes a log line every cycle, and exits 0. Silent halts are the ADR-037 §10 mode-2 risk, so this event must be visible. `technical-design` may add a deduped escalation through an existing primitive, but must not invent a new one.
4. **Hygiene (ADR-1415) and #1044** act only on `REPO_ROOT`. AD-4 places interactive worktrees outside it, and item 3 covers the violated-invariant case. No change to the hygiene algorithm. A test proves that a hygiene run with a live interactive worktree elsewhere leaves that worktree unchanged.
5. **`git worktree prune`.** Covered by `--lock` (AD-4). No cron change.

### AD-9: Cross-mode guards. (PROVISIONAL (ESC-4), PROVISIONAL (ESC-5); FR-7, FR-16.)

- **ESC-5 default.** An interactive `--update-pr <N>` for a PR **not** opened by this identity (that is, its body lacks this `cycle_id` in the AD-6 marker) is refused while `${HOS_STATE_DIR:-$HOME/.hos}/locks/hos-cron-worker-<project>.lock` exists. The lock directory's *existence* counts as "held". `kill -0` is never used (#1616). Every such update emits an event. PRs opened by this identity are never lock-checked; otherwise multi-hour cron cycles would block the session's own follow-ups. *If ESC-5 rules "never update cron PRs":* the condition becomes an unconditional refusal for PRs not opened by this identity. *If "always allowed":* the lock check is dropped and the event kept.
- **ESC-4 default.** An interactive `create_branch.sh --from <ref>` is refused when `<ref>` names a branch whose record has a **non-interactive** `cycle_id` and either the worker lock exists or the record is younger than `<p>_max_seconds` (default `HOS_CRON_MAX_SECONDS`' 1800). The record is read only to refuse, never to authorize (ADR-037 AD-2). The full re-review obligation after `--from` is unchanged. *If ESC-4 rules "never":* the refusal becomes unconditional for cron-recorded refs. *If "always":* the guard is dropped.

### AD-10: Session end and debris. (PROVISIONAL (ESC-6); FR-10.)

On exit the launcher:
1. retires the session record;
2. for each branch whose record carries this `cycle_id`: if the branch has zero commits ahead of `origin/main` and has no upstream, it deletes the branch and the record;
3. if the worktree is clean and its HEAD has no unpushed commits, it unlocks and removes the worktree; otherwise it leaves the worktree locked and prints one runbook line (path, branch, and the exact `git worktree unlock/remove` and `git branch -D` commands);
4. emits `interactive-session-end` with the result.

The VF-8 legacy debris (`Worker-1989`, its branch and its record) is protected from the cron by AD-8. Cleaning it up is a human runbook step, documented in S6. It is never automated by this change (requirements §6). *If ESC-6 rules "the human only":* steps 2 and 3 become report-only.

### AD-11: Documentation (S6). (BINDING; FR-19, AF-6.)

`docs/AGENT-IDENTITY.md` §8.1 is rewritten:
- identity is keyed on clone (R-1); the role-mapping table becomes clone × mode;
- it states R-2 verbatim in substance;
- it describes manual-worker mode and the AD-6 markers as the replacement for the distinction §8.1's "Why the human-proxy bot" paragraph relied on;
- §7's table row for human-proxy becomes "sessions in the Human clone".

`CLAUDE.md` **and** `templates/CLAUDE.human.md` scope the "Human-proxy session identity" block to the Human clone, with a short pointer telling Worker-clone sessions to use `bin/hos-worker`. `.claude/agents/worker.md` INTERACTIVE mode:
- replaces `source <(…)` and the literal-login guard (`:395-404`);
- says that branches come only from `create_branch.sh` inside the session worktree;
- says that cross-role refusals mean **stop and ask**.

Code-comment truth also has to be restored:
- `create_branch.sh:30-34` (it claims interactive sessions create branches with git);
- `submit_pr.sh:40-46` and `:174`;
- `hos-cron:340-347` (it says hos-cron is "the ONLY place" identity is minted).

`docs/v0.6.0/ADR-037` gets a dated pointer note: **AD-5 is amended by this ADR**. There is now a second minting site with a disjoint namespace, and its absent-value semantics are unchanged. `docs/CRON-SETUP.md` documents the AD-8 exclusion. `docs/SANDBOX-POLICY.md`'s "Interactive worker" row is updated. The docs also state AF-6 plainly: manual-worker sessions are treated as cron cycles by `validate_self.sh` and `dimension_sweep_cli.py`. That is accepted as the stricter direction (FR-18), and the docs give the operator workaround of running those tools from a plain shell, not from the session.

---

## 3. What FR-14 and FR-15 do and do not guarantee (security-reviewer: read this first)

Under AF-10, ADR-037 AD-8 governs. The ownership record and session record are correctness guards, and a model with full shell access can write any file this design reads. The design therefore guarantees four things:

1. **No sanctioned, documented or model-legible path mints an interactive identity.** No flag on any script does it (no `--interactive`). The launcher refuses any invocation from a model session (AD-3 items 2, 3, 4 and 5 are four independent signals, and items 4 and 6 need a terminal no model has).
2. **A process started under `bin/hos-cron` cannot get a valid identity by any documented route.** The launcher refuses it (HOS_CYCLE_* is set, there is no TTY, and `hos-cron` is an ancestor). The chokepoint refuses an interactive id when `hos-cron` is an ancestor (AD-4), and it refuses without a live session record bound to a linked worktree.
3. **Every remaining route is deliberate forgery against an explicit refusal.** A cron model would have to overwrite its own `HOS_CYCLE_ID`, hand-write a well-formed live session record with a matching boot id, *and* leave the `hos-cron` process tree. That is the "route around a boundary" behaviour `CLAUDE.md` forbids, not a path a model can reason itself into. The VF-6 concern is addressed at the level ADR-037 itself set.
4. **Visibility.** Every interactive PR carries a script-authored marker. Every protected-surface PR still needs a human.

**Not guaranteed:** resistance to a model that deliberately forges files while unsandboxed. Making that structurally impossible requires #1146 (sandboxing the cron worker) together with moving the session store to a location the cron sandbox denies writes to. That is noted to #1146 (§7, N-2) and is not built here (requirements §6 excludes signing and tamper-evidence).

---

## 4. Slices (ordered; each independently mergeable, each ≤15 files including tests)

| # | Slice | Files (indicative) | Depends on | Hangs on |
|---|---|---|---|---|
| **S1** | **Clone-role resolver adopted by launchers; no new refusals in mutating scripts** (AD-1). `role_clone_check.sh` delegates to it. `hos-human` refuses in a Worker or Overseer clone. Ship the libraries to consumers. | `bootstrap/lib/clone_role.sh` (new), `bootstrap/lib/role_clone_check.sh`, `bin/hos-human`, `bin/hos-overseer` (only if the API changes), `scripts/framework/framework_consumer_files.txt`, `tests/automation/test_clone_role.py` (new), `tests/automation/test_role_clone_check.py`: about 7 files | — | ESC-0, ESC-3 (launcher half) |
| **S2** | **Cron exclusion and namespace reservation** (AD-8; AD-2 reservation). Reaper skip, prune skip, interactive-HEAD cycle skip, `--prefix interactive` refused for non-interactive ids, grammar predicates and `HOS_INTERACTIVE_PROTOCOL`. Stops the 177-event spam today. | `bin/hos-cron`, `bootstrap/lib/branch_ownership.sh`, `bootstrap/create_branch.sh`, `tests/automation/test_hos_cron.py`, `tests/automation/test_branch_ownership.py`, plus at most 1 fixture helper: about 6 files | — (independent of S1) | ESC-0 |
| **S3** | **Manual-worker mode** (AD-2 mint, AD-3, AD-4, AD-5, AD-6 audit and PR marker, AD-10). | `bin/hos-worker`, `bootstrap/lib/interactive_session.sh` (new), `bootstrap/create_branch.sh`, `bootstrap/submit_pr.sh`, `bootstrap/lib/branch_ownership.sh` (audit `mode` field and audit root), `scripts/framework/framework_consumer_files.txt`, `tests/automation/test_hos_worker_launcher.py` (new), `tests/automation/test_interactive_session.py` (new), `tests/automation/test_branch_ownership.py`, `tests/automation/test_submit_pr.py`, plus at most 2 fixtures: about 12 files | S1, S2 | ESC-0, ESC-1, ESC-6, ESC-7 |
| **S6** | **Documentation** (AD-11). Must merge **after S3 and before S4**, so that no shipped doc tells a Worker-clone session to act as human-proxy once the refusal is live, and none points to a mode that does not exist yet. | `docs/AGENT-IDENTITY.md`, `CLAUDE.md`, `templates/CLAUDE.human.md`, `.claude/agents/worker.md`, `docs/v0.6.0/ADR-037-worker-branch-ownership.md` (pointer note only), `docs/CRON-SETUP.md`, `docs/SANDBOX-POLICY.md`, the code-comment fixes from AD-11 if not already done in S2/S3, and a doc-consistency test: about 10 files | S3 | ESC-0, ESC-2 (wording of the R-2 section) |
| **S4** | **Cross-role refusal chokepoint** (AD-7). Layer 1 in `get_app_token.sh`; layer 2 in the ten mutating scripts. `technical-design` may split it as S4a (`get_app_token.sh`, `submit_pr.sh`, `create_branch.sh`, `post_comment.sh`, `create_issue.sh`, plus tests) and S4b (the other six, plus tests) if the file count exceeds 15. **Ordering requirement:** S4 merges after S3, so that the Worker clone has a sanctioned path before its fallback is removed. Otherwise there is a window in which a Worker-clone session can open no PR at all. | `bootstrap/get_app_token.sh`, `bootstrap/lib/clone_role.sh`, 10 mutating scripts, `tests/automation/test_clone_role_refusal.py` (new), plus updates to existing script tests' fixtures (a registered temporary `projects.conf`): 14 files or more, so split | S1; merge after S3 and S6 | ESC-0, ESC-2, ESC-3, ARCH-ESC-1 |
| **S5** | **Cross-mode guards** (AD-9). | `bootstrap/submit_pr.sh`, `bootstrap/create_branch.sh`, `tests/automation/test_submit_pr.py`, `tests/automation/test_branch_ownership.py`: about 4 files | S3 | ESC-4, ESC-5 |

The issue-level acceptance (requirements §4) holds after S1 + S2 + S3 + S6 + S4. S5 completes FR-7/FR-16's cross-mode edges. #1954 is not in any slice.

### Test strategy per slice

All tests go in the PR-required suite (`scripts/framework/run_tests_inner_loop.sh`). Shell under test runs against temporary git repositories with linked worktrees and a temporary `HOME` holding a fixture `projects.conf`. Nothing touches the real registry, the network or a real token. Token minting is stubbed at `get_app_token.sh`'s boundary in the same way as the existing `test_submit_pr.py`.

- **S1.** A resolver table test covering:
  - a registered Worker clone, a registered Overseer clone, a Human sibling and an unregistered clone;
  - **a linked worktree of the Worker clone placed as a sibling**, which must resolve to `worker` (AF-2);
  - an ambiguous registry, a missing registry, and trailing-slash and symlinked roots;
  - a non-git path.

  Also a property check that the heuristic never yields `worker` or `overseer`. FR-1's AC is checked by asserting the same answer through `role_clone_check.sh`, `hos-human`'s check and a direct call. Existing `test_role_clone_check.py` cases pass unchanged.
- **S2.**
  - Reaper: with interactive records (new grammar **and** the VF-8 legacy shape), zero-commit interactive branches, a removed worktree and an aged record, the branch and record survive and no `cycle-branch-reap-failed` event appears. **This is FR-10's AC, verbatim.**
  - A cron record in the same store is still reaped (NFR-1).
  - Version skew: a `branch_ownership.sh` without the predicate makes the reaper skip the sweep entirely.
  - The 30-day prune leaves an aged interactive record in place.
  - A `REPO_ROOT` on `interactive-*` skips the cycle before hygiene and return-to-main, and emits the event.
  - `--prefix interactive` under a cron id is refused.
  - ADR-037 T1 to T11 pass unchanged.
- **S3.**
  - **Launcher refusal matrix**, run under a pseudo-terminal harness where a TTY is needed, one test per AD-3 precondition: HOS_CYCLE_* set; `CLAUDECODE` set; no TTY; a fake `hos-cron`-named ancestor (requirements acceptance #5, both halves); wrong confirmation (ESC-1); non-worker and unresolved clones; protocol mismatch.
  - **Happy path:** the worktree is created locked and outside `REPO_ROOT`, `REPO_ROOT`'s HEAD, index and status are byte-identical before and after, the session record is written, the start event lands under the main root's `audit/log`, and `claude` is replaced by a stub that runs `create_branch.sh` and then `submit_pr.sh` (stubbed network) from the worktree.
  - **FR-6 AC in both directions:** an interactive record fails `hos_bo_verify` under a cron id, and a cron record fails under an interactive id.
  - **FR-9:** `create_branch.sh` called by absolute path from `REPO_ROOT` under an interactive id is refused (`main_checkout`). An interactive id with no, ended, wrong-boot or wrong-worktree session record is refused.
  - **FR-8:** after the launcher exits, the same id is refused.
  - **FR-13:** the open-mode body gains the marker; a body that already contains `hos:authoring-mode` is refused (also tested under a cron id); an update posts the marker comment.
  - **AD-10:** a zero-commit session branch and clean worktree are removed at exit; a dirty worktree is left in place and the runbook line is printed.
- **S6.** A doc-consistency test: no shipped doc (`CLAUDE.md`, the template, `AGENT-IDENTITY.md`, `worker.md`) tells a Worker-clone session to use `--app human` or to "be the human-proxy"; `source <(` no longer appears in `worker.md`'s INTERACTIVE guidance; the ADR-037 pointer note exists. Matching is by anchored phrase, and the test must not be anchored on the first occurrence of a string that comments also quote.
- **S4.**
  - A matrix of {Worker, Overseer, Human, unresolved} clone × {worker, overseer, human} app × {mutating script, `get_app_token.sh` direct, read script}, asserting refuse or allow, **no mint performed on refusal** (the stub records calls), the audit event on both outcomes, and the message text containing both roles and "stop and ask".
  - The explicit FR-2 AC: `submit_pr.sh --app human --confirmed` from the Worker clone is refused.
  - A clone mismatch between `$PWD` and the script location is refused.
  - **Cron lockout guard:** a full simulated cron cycle's mint, run from the registered Worker root and from the registered Overseer root, still succeeds. This is ADR-037 §10 mode 2, so the slice must prove that worker delivery cannot halt.
- **S5.** The ESC-4 and ESC-5 tables: lock present or absent × record age × PR opened by this identity or by another, under the ruled option.

---

## 5. Traceability

| Requirement | Decision | Slice |
|---|---|---|
| FR-1 | AD-1 | S1 |
| FR-2, FR-3, FR-4 | AD-7 | S4 |
| FR-5 | AD-3 | S3 |
| FR-6 | AD-2, AD-5 | S2 (predicate), S3 |
| FR-7 | AD-5, AD-9 | S3, S5 |
| FR-8 | AD-2, AD-4 | S3 |
| FR-9 | AD-4, AD-5, AD-8.3 | S3, S2 |
| FR-10 | AD-8, AD-10 | S2, S3 |
| FR-11 | AD-4 | S3 |
| FR-12, FR-13 | AD-6 | S3 |
| FR-14, FR-15 | AD-3, AD-4, §3 | S3 |
| FR-16 | AD-5, AD-9 | S3, S5 |
| FR-17 | AD-1, AD-3 | S3 |
| FR-18 | AD-3, AD-5, AD-7 | all |
| FR-19 | AD-11 | S6 |
| NFR-1 | AD-5, AD-8 | S2, S4 tests |
| NFR-2 | AD-3, AD-7 | S3, S4 |
| NFR-3 | AD-3 protocol probe, AF-8 shipping | S1, S3 |

---

## 6. Product-boundary checkpoint, startup gap and affected sign-offs

**Product and policy consequences routed to the human (§8), not decided here:**
- user-visible launcher behaviour: a typed confirmation, a worktree instead of the clone, and no `exec` (ESC-1, ESC-7);
- consumers receive a new launcher (ESC-7);
- the cron skips cycles while the shared checkout sits on an interactive branch (AD-8.3, an operational change I treat as entailed by FR-10, but it is listed under ESC-6 so the human sees it);
- reads become role-restricted (ARCH-ESC-1);
- consumers' unregistered clones lose mutating scripts (ESC-3);
- a cleanup obligation for the human (ESC-6).

Under R-1 the worker bot authors interactive PRs. That makes them eligible for overseer auto-merge up to its ceiling, exactly like cron PRs (FR-13 already rules "identical"), whereas they were previously human-proxy PRs. ESC-0 covers that consequence.

**Startup gap.** This is not a `startup-artifact-gap`. ADR-037 excluded interactive sessions on purpose (AD-5's absent-value semantics). Manual-worker mode is a new requirement (#1958). ADR-037 AD-5 is **amended, not superseded**: there is a second minting site, in a disjoint namespace, with unchanged absent-value semantics.

**Affected sign-offs.**
- #967 code sign-offs stand. The cron path is unchanged apart from S2's narrowing and S4's same-role check, and T1 to T11 must pass.
- ADR-1415 sign-offs stand: the algorithm is unchanged, and the cycle skip runs before it.
- The #1498 reaper sign-off is **re-reviewed within S2**, because its record-walk predicate changes.
- The #1409 `role_clone_check.sh` sign-off is **re-reviewed within S1**, because its implementation is replaced while its API is kept.

No approved design is orphaned.

---

## 7. Notes routed (non-blocking)

- **N-1 → pm-agent.** The cron selector may pick the same issue a manual session is working on. Ownership prevents cross-submission, but duplicate work is possible. This is not in #1958's requirements. Consider a follow-up (for example an issue-level claim marker set by the session).
- **N-2 → #1146.** When the cron worker is sandboxed, move `interactive-sessions/` to a location in the cron sandbox's `denyWrite` set. §3 point 3 then becomes structural.
- **N-3 → technical-design.** It must empirically confirm AF-9 (no controlling terminal) for an *interactive* Claude session's Bash tool. I confirmed it only in print mode. AD-7 does not depend on it, but the S6 wording does.
- **N-4 → #1954 (later).** Its design must call `hos_require_clone_role` with clone role `human-proxy`, and must **not** introduce a flag-based authorization (AD-7).

---

## 8. Open human escalations

1. **ESC-0.** Confirm that R-1 and R-2, as posted on #1958 by the human-proxy bot, are your ruling. This includes the consequence that interactive work now arrives as worker-bot PRs, eligible for overseer handling identical to cron PRs. **Every slice hangs on this.**
2. **ESC-1 (human-present signal).** TTY + no cron context + no model-session marker + no `hos-cron`/`claude` ancestor, **plus** a typed challenge read from `/dev/tty` (the default, as drafted in AD-3)? Or TTY-only (delete AD-3 step 6)? Blocks S3.
3. **ESC-2 (cross-role authorization).** **Architect recommends the alternative:** no cross-role exception at all, so the hard stop is final, because the default's TTY clause cannot be built (AF-9) and a model-supplied argument is today's `--confirmed` defect. If you require an exception, it will be a server-side, human-authored comment artifact (AD-7), built later on top of S4, never a flag. Blocks S4 (and S6's wording).
4. **ESC-3 (unresolved clones).** Mutating acts fail closed and launchers stay fail-open (default; `hos-worker` fails closed regardless under FR-17)? Or both fail closed? Either way, consumers' unregistered clones lose mutating bootstrap scripts until registered. Blocks S4; the launcher half blocks S1.
5. **ESC-4 (`--from` across modes).** Default as drafted in AD-9: refused while the worker lock exists or the cron record is younger than `max_seconds`. Blocks S5 only.
6. **ESC-5 (updating cron PRs).** Default as drafted in AD-9: allowed with an event, refused while the worker lock exists, except PRs opened by this identity. Blocks S5 only.
7. **ESC-6 (interactive debris).** Default as drafted in AD-10: the launcher cleans up at session end, plus a runbook line; never the cron. Also confirm that the cron **skipping its cycle** while `REPO_ROOT` is on an `interactive-*` branch (AD-8.3) is acceptable. Blocks S3's cleanup step; S2 does not depend on it.
8. **ESC-7 (launcher shape).** Extend `bin/hos-worker` (default; the old mode is removed) or `bin/hos-worker-interactive` with `hos-worker` deleted? Also confirm that the launcher ships to consumers (AF-8). Blocks S3.
9. **ARCH-ESC-1 (new; product boundary).** The cross-role refusal lives in `get_app_token.sh`, so it also refuses cross-role **reads** (for example `query_issues.sh --app human` from the Worker clone). That is stricter than FR-2. Include reads (the architect's default), or restrict the refusal to mutating scripts and accept that a hand-built mint bypasses it? Blocks S4.

---

## Escalation flag (CORE self-flag)

**RISK: HIGH.** Every surface is protected. This ADR adds a second identity-minting site to ADR-037's design, changes the documented identity model, and puts a refusal on the single token-mint path that the whole autonomous loop depends on. A defect in one direction halts worker delivery invisibly (ADR-037 §10 mode 2: S4's clone check mis-resolving a registered root). A defect in the other direction creates a sanctioned route to worker PR authority outside cron (the S3 launcher guards).
**CONFIDENCE: HIGH** on §0. Every citation was read in this session from the working tree, the live ownership store, `git worktree list`, the registry and the audit log. **MEDIUM** on the AD-3 ancestry check's portability (macOS `ps` path, PID namespaces) and on AF-11's tooling resolution. Both are explicit obligations on `technical-design`. **MEDIUM** on the ESC defaults, which are product judgment awaiting the human.
**BLAST RADIUS:**
- the worker's ability to open PRs at all, on every deployment (S4 layer 1 sits in `get_app_token.sh`, which `hos-cron` calls every cycle);
- the cron's reaper and cycle-start path (S2);
- every human-run Worker-clone session (S3);
- consumer installs (new shipped files: AF-8).

**Rollback:** each slice reverts on its own. S4 reverts at two call sites. The S2 predicates are inert if removed (the reaper falls back to skipping the sweep). Session records and worktrees are inert if unread.

**Change classification: STRUCTURAL.**

## Gate for technical-design

- **May design now, on the ESC defaults, with every PROVISIONAL item carried forward as a marked assumption:**
  - **S1** (pending ESC-0, ESC-3 launcher half);
  - **S2** (pending ESC-0 only; the smallest, least ESC-dependent slice, and it stops a live defect: recommended first);
  - **S3** (pending ESC-0, ESC-1, ESC-6, ESC-7; every alternative is a local change, as AD-3 and AD-10 state).
- **May design, but must not finalize wording until ESC-2 is ruled:** **S6**.
- **Wait:**
  - **S4** waits on ESC-2, ESC-3 and ARCH-ESC-1. Its placement (AD-7 layers 1 and 2) is binding and may be designed. The refusal set may not be finalized until those three are ruled.
  - **S5** waits on ESC-4 and ESC-5.
- **No slice may be coded before ESC-0 is confirmed.** No slice may merge without the human protected-surface approval. S4 may not merge before S3 and S6.
