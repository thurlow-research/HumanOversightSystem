# REQUIREMENTS-1958: Sanctioned manual-worker mode. Role comes from the clone, there is no silent identity fallback, and the session never shares the cron's checkout

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** This adds a new flow (a
human-run worker session that opens and updates PRs). It adds a new cycle-identity kind and a new
refusal (a cross-role act needs per-act authorization). It also changes documented identity
semantics (`docs/AGENT-IDENTITY.md` §8.1). The two governing principles are already human-ruled
(§1, R-1/R-2). Everything the rulings do not settle is an ESC item (§7). The architect may proceed
on the ESC defaults, but must not treat a default as ruled.
**Date:** 2026-10-08
**Author:** pm-agent (autonomous worker cycle; no human present)
**Source issues:** #1958 (open, `bug`/`needs-ai`/`priority:high`, v0.7.0 Quality). The binding
input is its body plus the 2026-10-03T20:30Z ruling comment. #1954 (open, `needs-ai`, the
human-proxy `--update-pr` gap; disposition in §5). #1945 (the shared-checkout incident). #967 /
ADR-037 (branch ownership). #1409 (role/clone check). #1415 / ADR-1415 (worktree hygiene). #1498
(zero-commit branch reap).
**Consumers:** `architect`, then `technical-design`. Every implementation surface is protected
(`bin/**`, `bootstrap/**`, `CLAUDE.md`, `docs/AGENT-IDENTITY.md`, `.claude/agents/**`), so the human
gate applies whatever the computed tier.
**Scope note:** This document covers WHAT and WHY. It does not choose between "launcher" and
"`create_branch.sh` flag", and it does not set the cycle-id grammar or the record format. The
exception is §2-E, where security constraints rule some mechanisms out.

---

## 0. Verification findings (working tree, branch base `51f2837a9`)

**VF-1. The worker PR path is cron-only, as #1958 says.** `create_branch.sh:96-99` refuses unless
`HOS_CYCLE_ID`, `HOS_CYCLE_TOKEN` and `HOS_CYCLE_ROLE=worker` are all set. `submit_pr.sh:165-182`
(open mode, `--app worker`) refuses with `no_cycle_id`, `no_record` or `wrong_cycle`.
`submit_pr.sh:128` makes `--update-pr` worker-only. `:226-244` checks server-side that
`.user.login == HOS_BOT_LOGIN` and that head and base match. Only `bin/hos-cron:350-365` mints the
identity, with the grammar `${ROLE}-${project}-${ts}-$$`.

**VF-2. An interactive worker launcher already exists, but it is incomplete.** `bin/hos-worker` runs
the #1409 role/clone check, preflight, `get_app_token.sh --app worker` and an identity guard, then
`exec claude --dangerously-skip-permissions`. It mints no cycle identity and creates no worktree.
It also uses `source <(...)`, which `bin/hos-human:87-89` itself names as a known inconsistency.
#1958 proposes a new `bin/hos-worker-interactive`. Its premise ("no launcher exists") is only half
true. A second launcher for the same clone and role would create two entry points (D41).

**VF-3. The governing docs contradict each other on who an interactive session is.**
`docs/AGENT-IDENTITY.md` §8.1 says: "When a human drives Claude live … Claude authenticates as the
human-proxy bot (not the worker bot …)". Its role-mapping table keys identity on *interactive vs
autonomous*. `.claude/agents/worker.md` INTERACTIVE mode (around line 186 and lines 395-404)
requires `HOS_BOT_LOGIN == hos-worker-hos[bot]` before any mutation. `CLAUDE.md` is tracked, so it
loads in every clone. Its "HOS: Human-proxy session identity" section opens with "You are the
human-proxy orchestrator". A session in the Worker clone therefore reads two documents telling it to
be the human-proxy and one telling it to be the worker. This, plus VF-1, is the root cause the R-1
ruling names.

**VF-4. `--app human --confirmed` is the silent fallback R-2 forbids, and nothing ties it to a
clone.** `submit_pr.sh:136-139` checks only that the bare `--confirmed` flag is present. The model
supplies that flag itself. The script does not check which clone it runs in or which role the clone
implies. That is how #1949/#1953/#1956 were opened as the human-proxy from the Worker clone.

**VF-5. The cron already targets interactive branches. Only git's own refusal protects them.** The
ownership store is `<git-common-dir>/hos/branch-ownership/` (`branch_ownership.sh:25`). That one
store is shared by every worktree of the clone. The #1498 reaper (`hos-cron:1393-1457`) walks every
record and skips only the *main checkout's* current branch. The committed audit trail has
`cycle-branch-reap-failed` events for `interactive-1989-…` on 10-04, 10-07 and twice on 10-08
(`audit/log/2026/10/`). The delete failed only because git will not delete a branch checked out in
another worktree. If that worktree is removed or detached, a zero-commit interactive branch is
reaped. The #1044 return-to-main step (`:1340-1349`) and the ADR-1415 hygiene step act on
`REPO_ROOT`. The #1945 checkout collision came from #1044.

**VF-6. The ownership record is a correctness guard, not a security boundary.** ADR-037 AD-8 says
so explicitly: "An agent with shell access can write a record for any branch; that is accepted". It
endorses "no signing, no tamper-evidence". The real barrier against a model forging cron identity
today is the *absence of any sanctioned path*: `create_branch.sh` refuses and says why. A sanctioned
interactive mint would be the first documented, model-legible way to get worker PR authority outside
cron. §2-E exists so that this path does not become the thing a cron-run or injected model reasons
its way into.

**VF-7. The role/clone check is fail-open and covers only part of the space.**
`role_clone_check.sh` rejects only "this path is registered as the *other* cron role's root".
Unregistered clones pass. There is no `<project>_human_root` key. `hos-human` identifies the Human
clone as "a sibling of a registered Worker/Overseer". `submit_pr.sh` and `create_branch.sh` do not
check clone role at all.

**VF-8. A precedent exists, and it is not a design to reuse.** The 10-03 workaround had human
authorization for that session only. It hand-set `HOS_CYCLE_ID=worker-hos-interactive-<ts>-1944`, so
the trailing field is the *issue number* where `create_branch.sh:108` expects a PID. It used
`--prefix interactive`. That grammar passes the PID check by accident and is not unique if two
sessions work on the same issue in the same second. #1959 and #1986 merged this way.

**VF-9. Provenance of R-1/R-2.** The ruling comment was posted under `scottthurlow-claude[bot]` (the
human-proxy), headed "Human ruling (2026-10-03)". The cycle brief tells this pass to treat it as
binding, and it is treated as binding here. Under AGENT-IDENTITY §7, a human-proxy post is not by
itself a human act, so ESC-0 asks the human to confirm it.

## 1. Binding rulings

- **R-1.** Role is derived from the clone the session runs in: `Worker/` → worker, `Human/` →
  human-proxy, `Overseer/` → overseer. It does not depend on session mode or on judgment. Clone
  location is the primary, near-mechanical signal.
- **R-2.** A session never opens a PR under the human-proxy identity as a silent fallback. It may do
  so only with explicit, per-act human authorization that names the role. If a session cannot act
  under the role its clone implies, it must **stop and ask**. It never substitutes another identity.

## 2. Functional requirements

### A. Clone-derived role (R-1)

- **FR-1.** The installed tooling has one deterministic way to resolve the role a clone implies
  (worker / overseer / human-proxy / unresolved). The worker launcher, `create_branch.sh` and
  `submit_pr.sh` all use it. *AC:* every call site gets the same answer for the same path. Tests
  cover a registered Worker clone, a registered Overseer clone, the Human sibling clone and an
  unregistered clone.
- **FR-2.** Any GitHub-mutating act whose `--app` role differs from the clone-derived role is refused
  before any token is minted. This covers PR open, PR update, comments, issue creation and edits.
  The only exception is the per-act authorization in FR-3. *AC:* `submit_pr.sh --app human
  --confirmed` from the Worker clone is refused, with a message that names both roles and says
  "stop and ask the human" (R-2). Same-role acts behave exactly as before.
- **FR-3.** A cross-role act needs an authorization that **names the role**. A bare `--confirmed` is
  not enough. Every cross-role act, allowed or refused, writes an audit event recording the clone
  role, the requested role and the outcome. *AC:* the event is present for both outcomes. ESC-2
  decides what form the authorization takes and whether any cross-role exception survives at all.
- **FR-4.** When the clone role cannot be resolved, the act is refused with a diagnosable message.
  This is fail-closed, the reverse of today's fail-open #1409 behavior, and applies to mutating
  acts only. ESC-3 decides whether launchers keep failing open on unregistered clones.

### B. The manual-worker mode (#1958 Expected)

- **FR-5.** A human-run session in the Worker clone can go from "issue" to "PR open" as the worker
  bot through one sanctioned entry point. No hand-set environment variables, no `--app human`, no
  borrowed identity. If a second launcher is added, `bin/hos-worker` must not remain as a parallel
  path with different guarantees (VF-2).
- **FR-6.** That session gets a cycle identity that is (a) marked *interactive* by construction,
  (b) unable to collide with any cron cycle id or with another interactive session, including on
  the same issue in the same second (ADR-037 AD-3 and the §6 addendum), and (c) usable by the
  unchanged ownership model. That means `create_branch.sh` writes a record that `submit_pr.sh
  --app worker` accepts *only* within that same interactive identity. *AC:* the VF-8 grammar is not
  reproduced. A record written by an interactive identity fails `hos_bo_verify` under every cron
  identity, and the reverse also holds.
- **FR-7.** The session can push follow-ups to PRs it opened, using `submit_pr.sh --update-pr <N>
  --app worker`, with the existing server-side authorship check (ADR-037 AD-4) unchanged and no
  `--force`. ESC-5 decides whether an interactive session may also update PRs opened by cron
  cycles.
- **FR-8.** The interactive identity lives only as long as the session. Restarting or resuming
  produces a new identity. A new identity can never open a PR from a branch made under an earlier
  identity, except through ADR-037 `--from` adoption with the full review chain re-run. Updating an
  existing PR (FR-7) is unaffected, because it rests on authorship, not on the record.

### C. Isolation from the cron (#1945)

- **FR-9.** Every branch the manual-worker mode creates is created and worked in a dedicated
  worktree outside the cron's `REPO_ROOT` checkout. The mode refuses to create a branch in the
  cron's checkout. *AC:* at no point is the cron's `REPO_ROOT` HEAD an interactive branch.
- **FR-10.** The cron never checks out, returns-to-main, hygiene-sweeps, quarantines or reaps an
  interactive worktree or an interactive-owned branch or record. This must be stated **explicitly**,
  not left to git's worktree refusal (VF-5). Interactive records are also no longer reported as
  `cycle-branch-reap-failed`. Cleanup of interactive worktrees, branches and records belongs to the
  manual mode or the human (ESC-6). *AC:* with the interactive worktree removed and a zero-commit
  interactive branch left behind, a cron cycle leaves both the branch and its record in place.
- **FR-11.** Scripts and subagents run by the session act on the session's worktree, never the
  shared clone. That includes cwd-relative writes such as `.claudetmp` and register files.
  *AC:* register and `.claudetmp` writes from an interactive build land under the worktree.

### D. Audit and provenance

- **FR-12.** The ownership record, every `submit_pr.sh` / `create_branch.sh` audit event (including
  refusals) and a session-start event all carry the interactive marker and the interactive cycle
  id. *AC:* the committed audit trail can tell interactive worker activity from cron worker activity
  without reading prose.
- **FR-13.** A PR opened or updated in manual-worker mode says so in a machine-detectable way, so
  the overseer and the human can tell which mode authored it. The mode grants no review, risk or
  merge privilege: overseer handling, tiers and gates are identical to cron PRs.

### E. Security constraints (the #967 bypass risk)

- **FR-14. A model cannot mint an interactive identity.** No tool, script or flag that a model
  session can call (cron or interactive) may mint or self-assert an interactive cycle identity.
  Minting happens before or outside the model session, as `hos-cron` minting does (ADR-037 AD-5).
  This rules out a bare `create_branch.sh --interactive` flag that mints on demand. Such a flag may
  exist only if it is inert without an identity minted outside the model.
- **FR-15. A human must be present at mint time.** The mint requires a signal that a human is
  present and started the session. At minimum: a controlling terminal on the launcher, and refusal
  when any cron context is present (`HOS_CYCLE_*` already set, or invocation from or under
  `bin/hos-cron`). ESC-1 decides whether that is enough or whether an explicit typed human
  confirmation is also required.
- **FR-16. No branch adoption.** The mode records ownership only for branches it creates itself. It
  never writes, rewrites or re-keys a record for an existing branch, whether cron-owned, foreign or
  hand-made. Taking over commits is possible only through ADR-037 `--from` (new branch, full
  re-review), and ESC-4 decides whether even that applies to branches a live cron cycle owns.
- **FR-17. Worker clone only.** The mode refuses unless the clone-derived role (FR-1) is worker. It
  never runs in the Human or Overseer clone.
- **FR-18. No new widening.** Nothing in this change relaxes any existing refusal for cron cycles. No
  config key, environment escape or install flag turns the mode on, off or wider (ADR-037 AD-6).

### F. Documentation (#1958 Acceptance)

- **FR-19.** `docs/AGENT-IDENTITY.md` §8.1 is rewritten so identity is keyed on clone, not on
  interactive vs autonomous (R-1). It describes manual-worker mode and states R-2. `CLAUDE.md`
  scopes its "Human-proxy session identity" section to the Human clone only and points Worker-clone
  sessions to the manual-worker mode. `worker.md` INTERACTIVE mode is brought in line, including its
  `source <(...)` guidance. *AC:* no shipped doc tells a Worker-clone session to act as the
  human-proxy.

## 3. Non-functional requirements

- **NFR-1.** Cron behavior is unchanged except for FR-10's explicit exclusion. The existing
  branch-ownership tests (T1-T11) still pass.
- **NFR-2.** Every refusal names its reason and the next action, and none of them says "fall back to
  another identity" (ADR-037 AD-6, R-2).
- **NFR-3.** The launcher and the chokepoint ship and upgrade together (ADR-037 VF-7). A version
  mismatch refuses with a diagnosable message; it never fails open.

## 4. Acceptance (issue-level, all must hold)

1. A manual Worker-clone session opens a PR and pushes a follow-up, both with `--app worker` and
   with no `--app human`, under a cycle id minted by the sanctioned entry point.
2. Its ownership record and audit events carry the interactive marker (FR-12).
3. Across a full cron cycle that runs during the session, the session's branch, worktree and record
   are not touched (FR-9, FR-10).
4. `--app human --confirmed` from the Worker clone is refused (FR-2).
5. A model-callable route cannot produce a valid interactive identity, and neither can a process
   started under `bin/hos-cron` (FR-14, FR-15). The tests cover both.
6. FR-19's documents are consistent.

## 5. Disposition of #1954: **keep it a separate, later slice**, constrained by this document

#1954's observed incident (#1949 replaced by #1953) happened in the **Worker** clone. Under R-1 that
session was the worker, so #1958 (FR-7) fully resolves it. #1954's *premise*, "interactive sessions
open PRs as human-proxy (§8.1)", is the premise R-1 overturns. What remains is real but narrower:
the Human clone's stuck-worker exception (AGENT-IDENTITY / CLAUDE.md) opens PRs as the human-proxy
and has no update path. It is kept separate because (a) it involves a different identity, clone and
authorization flow (`--confirmed`, which FR-3 is already redefining); (b) folding it in would widen
a protected-surface change already rated HIGH; and (c) its design depends on FR-1 to FR-3 landing
first. When built, #1954 **must**: run only where the clone role is human-proxy (FR-1); require the
per-act, role-naming authorization (FR-3), with no bare `--confirmed`; keep the server-side
authorship, head and base check and no `--force`; and audit every push. #1954's body should be
re-scoped to the Human clone. Recommendation only: this cycle does not edit issues.

## 6. Out of scope

- Signing or tamper-evidence for ownership records (ADR-037 AD-8 stands; VF-6).
- Interactive overseer mode, and any change to overseer merge authority.
- Fixing `hos-cron`'s PID-namespace lock issue (#1616). The manual mode does not invoke `hos-cron`.
- Bulk cleanup of existing `interactive-*` branches and records from the VF-8 workaround (ESC-6).
- Rewriting Human-clone behavior beyond the R-2 refusal and the doc scoping in FR-19.

## 7. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-0.** Confirm that R-1/R-2 as posted on #1958 by the human-proxy bot (VF-9) are your ruling.
- **ESC-1. Human-present signal (FR-15).** Is "controlling TTY plus no cron context at launch"
  enough, or must the human also type a confirmation at mint time? *Default:* TTY plus no cron
  context plus a typed confirmation. A TTY can be faked with `script(1)`, but a cron model cannot
  answer a prompt it never sees.
- **ESC-2. Cross-role authorization (FR-3).** What form must "explicit, per-act, names the role"
  take, given any flag is model-supplied? *Default:* a role-naming argument (e.g. authorizing
  "human-proxy" by name) plus a mandatory audit event, accepted only in an interactive TTY session.
  Alternative: no cross-role exception from the Worker clone at all, so a hard stop is final.
- **ESC-3. Unregistered clones.** Should mutating acts fail closed (FR-4 default) and launchers
  fail open as today, or should both fail closed?
- **ESC-4. `--from` across modes.** May an interactive session `--from` a branch whose record a cron
  cycle wrote? *Default:* refused while the cron record is younger than the cron's max cycle time,
  allowed after that with a full re-review.
- **ESC-5. Updating cron PRs.** May an interactive session `--update-pr` a PR a cron cycle opened?
  Authorship allows it, because the bot is the same, and that can race a live bounce. *Default:*
  allowed, with an audit event, but refused while a cron cycle holds the worker lock.
- **ESC-6. Interactive debris.** Who cleans up interactive worktrees, branches and records,
  including those from the VF-8 workaround? *Default:* the manual mode at session end, plus a
  documented manual runbook line. Never the cron.
- **ESC-7. Launcher shape (FR-5).** Extend `bin/hos-worker` (default; one entry point per D41), or
  add `bin/hos-worker-interactive` and retire `hos-worker`?

## Escalation flag (CORE self-flag)

RISK: HIGH. Every surface touched is protected. It reopens ADR-037's identity hinge (AD-5), it
changes the documented identity model, and a mistake in either direction either locks out worker
delivery or creates a sanctioned route to worker PR authority outside cron.
CONFIDENCE: HIGH on VF-1 to VF-8 (all read in this session from the working tree, the audit trail
and #1954/#1958). MEDIUM on the ESC defaults, which are product judgment awaiting human ruling.

## Human Review Required

Structural change (new flow, identity kind, refusal, and a rewritten §8.1). The R-1/R-2 principles
are human-ruled; ESC-0 to ESC-7 need a human answer before `technical-design` binds the
corresponding FRs (FR-3, FR-4, FR-5, FR-7, FR-10, FR-15, FR-16). The architect may draft the ADR
on the defaults in parallel.
