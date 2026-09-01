# ADR-038 — The execution-copy boundary: an executed-set closure, an install-record trust anchor, a journalled fast-forward state machine, and a lock-primary sync

**Status:** ACCEPTED FOR DESIGN — **not cleared to build.** AD-1 … AD-16 bind `technical-design` against FR1–FR36 of REQUIREMENTS-038. The six points in REQUIREMENTS-038 §4 (Q1–Q6) are **NOT bound here** — each is absorbed by a named seam (§3.1) so whichever way the human rules, the mechanism changes a configured value or a single resolver, never its shape. Three items are **new escalations I raise** (§3.2): **ESC-A** (the copy set "all of `bin/`" is measurably insufficient to deliver P1's property — HIGH, human's, it changes install footprint), **ESC-B** and **ESC-C** (two REQUIREMENTS-038 acceptance criteria that are unsatisfiable as written → back to `pm-agent`). One decision is a **hard dependency I bind and must state plainly**: for the Worker and Overseer roles the execution-copy boundary is **not enforced by relocation alone** (AD-2) — it is enforced by a path-allowlisting sandbox that those two roles do not currently have, so P4's generated settings (FR27) is a *prerequisite* of FR1's property, not a parallel workstream.
**Date:** 2026-08-05
**Author:** architect
**Source issue:** #1202 — "design: Human clone sync via cron — cadence, repair pass, and drift-safety markers."
**Inputs:** pm-agent REQUIREMENTS-038 (P1–P5 bound premises; FR1–FR36; VF-038-1 … VF-038-9; §4 Q1–Q6); my own re-verification against the working tree and the live machine (§0).
**Consumers:** `technical-design` (next), then a `needs-ai` issue to the autonomous `worker`.
**Related:** #1200 (shipped — a dependency, FR36/AD-9), #1201 (to be re-scoped as the implementation of this design or closed as superseded), #1146 + #1183 (own the Worker/Overseer sandboxing that AD-2 makes load-bearing), #1162 (stale-base PR guard — adjacent, not this).
**Protected surfaces touched by the implementation:** `bin/**`, `bootstrap/**`, `scripts/framework/**`, `.claude/agents/**` (only if a launcher contract is documented there), plus a new template and a new declaration file that MUST be added to `scripts/framework/protected_surfaces.txt` (AD-1, AD-14). The implementation PR is human-approved at merge regardless of computed tier.

---

## 0. Verification findings — what I re-measured, and the four that change the requirements

pm-agent's nine VFs all **hold**; I re-ran the load-bearing ones rather than inheriting them. Nine findings of my own follow. **AF-038-1, AF-038-2, AF-038-4 and AF-038-5 change the design**; the rest constrain it.

**AF-038-1 — HIGH, decisive: copying "all of `bin/`" does NOT deliver P1's property. `bin/hos-cron` executes at least seven clone-resident artifacts, as the user, outside any agent session and outside any sandbox.** P1's security property is *"changing what cron executes requires a human-run install."* Measured against `bin/hos-cron` in this tree, the cron launcher — after the copy, still — would reach back into the agent-writable clone for:

| Line | Clone-resident artifact executed / consumed | Why it is in the pre-session control path |
|---|---|---|
| 476 | `$REPO_ROOT/bootstrap/validate_setup.sh` | preflight; runs before the session |
| 485 | `$REPO_ROOT/bootstrap/get_app_token.sh` | **mints a GitHub App installation token** |
| 329, 358 | `$REPO_ROOT/scripts/oversight/ensure_venv.sh` | creates/rebuilds the venv the cycle runs in |
| 678 | `$REPO_ROOT/scripts/framework/run_tests_inner_loop.sh` | baseline-repair test run |
| 240 | `python3 -m scripts.automation.lib.cycle_log` (cwd `$REPO_ROOT`) | audit event emission |
| 917 | `$REPO_ROOT/bootstrap/${ROLE}-cron-prompt.md` | **the prompt text the unattended cycle is launched with** |
| 978 | `$REPO_ROOT/scripts/automation/lib/next_candidates.jq` | issue-selection query |

Two of these are worse than "a script runs": the token minter (arbitrary code with app-key access, unsandboxed) and the **cron prompt file** (an agent edit changes the instructions the next unattended cycle obeys — a self-directed-instruction path that no code review sees, because nothing merges). FR3 already states the correct rule in words — *"each launcher runs from a clean environment with no reference back into a clone for its own dependencies"* — but VF-038-1 framed the ship-set as "all of `bin/`", and `bin/` is not the closure. **Consequence:** the declaration FR4 requires is a *closure*, not a directory listing (AD-1), and how far to take the closure in the first implementation is a scope/footprint decision I escalate (ESC-A).
*Command:* `grep -nE 'source|\bbash |python3|\./' bin/hos-cron | grep -E 'REPO_ROOT'`; `sed -n '900,925p' bin/hos-cron`

**AF-038-2 — HIGH, and it reframes the whole change: relocation is not, by itself, a boundary. For Worker and Overseer it is currently obscurity.** `REPO_ROOT` is resolved from `~/.config/hos/projects.conf` (`bin/hos-cron:111`, `_conf_val ${ROLE}_root`), not from the launcher's own location — so relocating the launcher is *path-safe* (good), but it also means the clone stays fully reachable from the relocated copy. What actually prevents an agent session from writing the execution root is the **sandbox's path allowlist**, which is kernel-enforced (`CLAUDE.md`: *"Filesystem and network boundaries are enforced by the kernel"*). Re-measured this session: `Human/.claude/settings.local.json` exists (45 deny rules, `permissions.additionalDirectories` = 6 entries); **`Worker/.claude/settings.local.json` and `Overseer/.claude/settings.local.json` do not exist.** With no allowlist in force, a Worker/Overseer session runs as the same uid as cron and can write any path that uid can write — including any execution root under `$HOME`. **Consequence:** FR1's verify line (*"a write probe to that path from inside an agent session fails"*) is satisfied for the Human role by its existing sandbox and is **not satisfiable for Worker/Overseer by this change alone**. P4's per-role generated settings (FR27) is therefore the *enforcement mechanism* for FR1 on two of three roles — a prerequisite, not a sibling (AD-2, AD-8).
*Commands:* `grep -n "REPO_ROOT=" bin/hos-cron`; per-clone `json.load(...settings.local.json)` existence + key dump

**AF-038-3 — CONFIRMED: the install-record mechanism the currency check needs already exists in embryo.** `bootstrap/hos_install.sh:290` defines a portable `_sha256()` (sha256sum/shasum), and `.hos-manifest` is written at schema v2 as `path\tWHOLE\t<sha256>` rows (`:2118–2331`), already used for obsolete-file detection and unmodified-since-install pruning (`:2287–2299` compares a current sha against the recorded one). **Consequence:** AD-5's install record is an *extension of an existing, exercised pattern* — content-addressed, install-written, sha-compared — not new machinery. It differs in exactly one respect that matters: it must live **outside** the clone.
*Command:* `grep -n "hos-manifest\|_sha256" bootstrap/hos_install.sh`

**AF-038-4 — NEW, blocks FR17 as written: the three interactive launchers end in `exec claude`, so a shell `trap … EXIT` can never fire.** `bin/hos-human:56`, `bin/hos-worker:25`, `bin/hos-overseer:20` all `exec` the CLI, replacing the launcher process image. Any lock registered by the launcher and released by an EXIT trap would be released **immediately at exec** (or never, depending on where the trap sits) — so FR17's *"released on every exit path"* is unimplementable while `exec` stands. `bin/hos-cron` does not have this problem: it runs `claude` in a subshell (`:903–908`) and its `trap 'rm -rf "$_LOCK_DIR"' EXIT` (`:207`) works. **Consequence:** AD-10 binds dropping `exec` in the three interactive launchers (run as a child, propagate the exit code, forward signals) — a small but real behavioural change to the session-start path that `technical-design` must specify, not a detail.
*Command:* `cat bin/hos-human bin/hos-worker bin/hos-overseer`

**AF-038-5 — NEW, constrains FR26 hard: `permissions.additionalDirectories` grants a *working directory* (read AND write), and today's sync state already sits inside one.** The Human clone grants `/tmp` — and `bootstrap/hos_repo_sync.sh:33` defaults its state dir to `/tmp/hos-repo-sync`, so the sync's own state is **session-writable today**. Worse in the other direction: `bin/hos-cron:484` does `mktemp -p "$_HOS_DIR"` for the **installation token**, i.e. the state root holds live credentials. **Consequence:** FR26's "readable from inside a sandboxed session" MUST NOT be satisfied by granting `$_HOS_DIR`. The marker needs its own dedicated subtree (AD-13), the state root and the execution root must **never** appear in `additionalDirectories`, and the read-only half of FR26 is only as strong as a deny rule (advisory under a same-uid sandbox) — which is why the marker is a *backstop signal* and never a control (P3 already says this; AD-13 makes it structural).
*Commands:* `python3 -c "…additionalDirectories…"` on `Human/.claude/settings.local.json`; `sed -n '30,35p' bootstrap/hos_repo_sync.sh`; `grep -n "_HOS_DIR" bin/hos-cron`

**AF-038-6 — NEW: today's cleanliness precondition would make sync skip *permanently* in the clone that most needs it.** `hos_repo_sync.sh:137` gates the pull on `[ -z "$(git status --porcelain)" ]`, and `--porcelain` reports **untracked** files. The Worker clone's `git status` in this session lists dozens of untracked `audit/log/**` records and `.claude/worktrees/`. Under a cron syncer with that precondition, every attempt records a skip forever, and FR32's escalation fires on a condition that is normal operation rather than a fault. **Consequence:** AD-12 redefines the precondition on *tracked* modifications + index state, permits untracked files, and relies on git's own pre-flight refusal ("untracked working tree file would be overwritten") as a clean, atomic abort.
*Command:* `git status` (session start), `sed -n '133,150p' bootstrap/hos_repo_sync.sh`

**AF-038-7 — NEW: FR18's prohibition list forbids the only primitive that can satisfy FR20.** FR18 says the mechanism must contain *"no merge, no rebase, no **reset**, no force, no stash, no checkout"*; FR20 says on failure *"the tree MUST be restored to the recorded pre-state."* Restoring a tracked-file tree to a recorded commit is `git reset --hard <pre-commit>` (or `git checkout --force`, also on the prohibited list). Read literally the two requirements cannot both be met. The intent is plainly separable — FR18 constrains the **sync path** (what may introduce content), FR20 the **repair path** (what may remove content that was never gated) — but the text does not say so. AD-11 binds the reconciliation; ESC-C routes the wording back to `pm-agent`.

**AF-038-8 — CONFIRMED: FR4's guard is genuinely new, and it has an obvious home.** `tests/framework/test_consumer_framework_files.py` asserts *listed → exists in source* (`test_every_listed_file_exists_in_source`) and spot-checks specific members (`test_bin_lib_git_credentials_present`), but nothing asserts the FR4 direction: *present in `bin/` → must be listed*. Adding it there is a few lines. The closure direction (AF-038-1) is the hard half.
*Command:* `grep -n "def test" tests/framework/test_consumer_framework_files.py`

**AF-038-9 — NEW, small but it makes the state machine tractable: `git pull --ff-only` conflates a network step with a tree step.** `hos_repo_sync.sh:138` uses `pull --ff-only`, which is fetch+merge in one command; a failure cannot be attributed to either half, and the fetch (no tree effect, idempotent, safely retryable) becomes as risky as the merge (tree effect, the only step needing a journal). AD-11 binds splitting them: fetch first, outside the journalled window; then, and only then, `merge --ff-only` against the already-fetched remote ref inside it.

**Live-state re-measurement (for AD-8's per-clone table).** Crontab: 5 in-clone launcher entries across **two** projects — `HumanOversightSystem/{Worker,Overseer}/bin/hos-cron`, `CondoParkShare/{Worker,Overseer}/bin/hos-cron`, `HumanOversightSystem/Worker/bin/hos-trim-logs` — plus `/home/scott/.config/hos/worker-unstick.sh`, an out-of-clone script already executing on a timer (VF-038-9's precedent, confirmed). This corroborates VF-038-6's "framework property, not a three-clone problem" (FR34).
*Command:* `crontab -l | grep hos`

---

## 1. Context — three boundaries, not one

REQUIREMENTS-038 reads as one change but is three, and conflating them is how a design of this shape goes wrong:

1. **The execution boundary — *what* runs.** An out-of-clone copy executes; the repo is source. Bought by AD-1 … AD-4. Its security value is entirely conditional on an agent session being unable to write the execution root (AD-2), which is a *sandbox* property, not a *filesystem-layout* property.
2. **The currency boundary — *which version* the thing that runs is.** The cost of (1) is drift, and CI cannot see it (VF-038-7). Bought by AD-5 … AD-7 with an install-record trust anchor and a run-time, execution-site check that never writes.
3. **The mutation boundary — *when* a clone's tree may change.** Lock-primary skip (P3), fast-forward only, journalled, verify-or-restore. Bought by AD-9 … AD-13.

They share exactly two artifacts — the machine-local state root (locks, journal, marker, install record, escalation outbox) and the install step — and they must not share more. In particular: **the currency check must never write, and the sync must never touch the execution root.** Wiring (2) to repair (1) is the single most attractive and most destructive thing an implementer could do here (FR8), and it is prohibited three times below for that reason.

The organizing rule I bind for the whole ADR: **the install is the only writer of everything the machine executes out-of-band; every runtime component is a reader of it.**

---

## 2. Decisions

### AD-1 — The shipped/copied set is an **executed-set closure**, declared once, and guarded in both directions. (BINDING — FR1, FR2, FR3, FR4, FR34. The declaration file is a new protected surface.)

**The set is defined by behaviour, not by directory:** the closure of everything an out-of-band launcher **executes, sources, or interprets as instruction outside an agent session** — transitively. A directory listing ("all of `bin/`") is not that set (AF-038-1) and a design that ships it will satisfy every FR4 test while leaving seven unsandboxed clone-resident execution paths open, including the token minter and the cron prompt.

Bound rules:

1. **One declaration.** Exactly one file — the same shape as `scripts/framework/framework_consumer_files.txt` and `consumer_agents.txt`, path-per-line, comments allowed — is read by (a) the install copy step, (b) the `.hos-manifest`/install-record enumeration, and (c) the currency check. **No launcher may be copied by a second code path** — this kills the `hos_install.sh:2019–2025` special case for `bin/hos-human` (VF-038-1). The list spans directories (`bin/`, `bootstrap/`, and whatever else the closure reaches); it is a list of *paths*, and the fact that it is not a directory is the point.
2. **Guard both directions.** (a) *listed → exists* (already present, `test_consumer_framework_files.py`); (b) **new**: *present in `bin/` → listed* (FR4's stated test); (c) **new and load-bearing**: *closure* — a test that scans each declared launcher for invocations resolving into a clone (`$REPO_ROOT/…`, `python3 -m scripts.…`, `cd "$REPO_ROOT"`) and **fails on any target not itself declared or not explicitly registered as an accepted in-clone reference** with a written reason. The accepted-reference register is the honest form of a partial closure; a silent partial closure is not.
3. **Wholeness and permissions.** Copy is atomic-per-install and whole: every declared file present, executable bit preserved, and a launcher started from a clean environment resolves every *control-path* dependency inside the execution root (FR3).
4. **`bin/**` stays tracked and stays a protected surface (FR5, P5).** The new declaration file, being under `scripts/framework/**`, is protected automatically; if `technical-design` places it elsewhere it MUST be added to `protected_surfaces.txt` explicitly and `gen_codeowners.sh` re-run.
5. **What is *not* in the closure.** Work the agent performs *inside* its own session against its own clone (validators, gates, review scripts) stays in the clone and is out of scope — it is sandboxed by construction and gating it is the sandbox's job. The line is: **executed outside a session → in the closure; executed inside a session → not.**

**Scope of the first implementation is ESC-A (human's)**: full closure now (larger install footprint, `bootstrap/**` largely moves into the execution set) versus `bin/` + the credential/prompt path now with the remainder in a named, registered residual. I do not bind it because it changes the install footprint and the operational surface. What I **do** bind: whichever is chosen, the residual is *registered with reasons and tested*, never implicit.

### AD-2 — The execution boundary is enforced by the sandbox path allowlist, not by relocation. For Worker and Overseer, FR27's generated settings is a **prerequisite** of FR1, not a parallel workstream. (BINDING — FR1, FR6; ties P4 to P1.)

This is the decision that, gotten wrong, ships a change that *reads* as a security fix and *is* a file move. Stated plainly:

- Relocation moves the executed bytes out of the clone. It does **not** make them unwritable: cron and the agent session run as the **same uid** (AF-038-2), and `hos_install.sh` is explicitly a no-sudo tool (`CLAUDE.md`), so no unix-permission boundary is available.
- What *is* available and *is* kernel-enforced is the Claude Code sandbox's allowed-working-directory list. A path outside every allowed directory is genuinely unreachable — that is why the Human clone's posture is real and why VF-038-6's write probe **succeeded** in the Worker clone, which has no such list.
- **Therefore:** FR1's property holds for a role **iff** that role's sandbox configuration (i) allowlists the clone (and whatever else it needs) and (ii) does **not** allowlist the execution root, the install record, or the state root. That configuration is exactly FR27's generated per-role settings. AD-14 is load-bearing for AD-1, and AD-8's phase order reflects it.
- **Bound negative rule:** the execution root, the install record, and `$_HOS_DIR` itself MUST NOT appear in any role's `permissions.additionalDirectories` (or its successor key). Only the marker subtree may (AD-13). A design that grants the state root to make the marker readable **destroys the boundary and leaks installation tokens** (AF-038-5).
- **FR6's residual, stated as required:** after migration, the Worker and Overseer clones' `bin/` remains agent-writable, and — until #1146/#1183 land a sandbox for those roles — **so does any execution root on the same machine**. For those two roles, this change is *sequencing and hygiene*, and the boundary becomes real only when their sandbox does. That sentence, or its measured equivalent, MUST appear in the implementation's own documentation; FR6 requires a written residual that matches measurement, and a residual that overstates the protection is worse than none.

### AD-3 — One execution-root **resolver**, one call site; the value is the human's (Q4/Q5). (BINDING on shape — FR35, FR34; value HELD.)

Every component that needs the execution location — installer, launchers, currency check, the migration shim, `.envrc`, the crontab emitter, the docs generator — obtains it from **one resolver function in one place**. No second derivation, no path composed inline, no environment-specific branch. The resolver's contract:

- **Inputs:** the existing env-overridable machine-local state root (`HOS_STATE_DIR`, default `$HOME/.hos` — `bin/hos-cron:123`), a project key, and a role where relevant. It MUST work for a single-repo consumer with no parent-project directory (FR35).
- **Output:** one absolute path, plus a boolean "does it exist / is this install migrated."
- **Recommended default, NOT bound:** a per-project subtree of the state root (pm-agent's §4-Q4 recommendation). It satisfies FR1/FR34/FR35 with one rule for both layouts and dissolves Q5 entirely.
- **Q4 is the human's.** Because the resolver is the only derivation, a different Q4 ruling (inside the consumer repo, or a required parent-directory layout) changes **one function body** and, if the copy lands inside a repo, adds the Q5 gitignore step at exactly one install call site. `technical-design` MUST include that conditional hook and leave its behaviour unbound.

### AD-4 — A **human-run install** is the sole writer of the execution root; no automated or agent path may invoke the copy step. (BINDING — FR2.)

FR2's property ("a merge changes nothing until a human installs") is only as strong as the absence of an automated installer path. Bound:

- The copy step MUST be reachable only from an interactive/human-confirmed install invocation, using the established explicit-confirmation idiom (`bootstrap/submit_pr.sh --app human` requires `--confirmed`; `CLAUDE.md`). A `--dry-run`/plan path may report what *would* change; it may not write.
- No workflow, cron entry, agent prose, or script in the repo may invoke the copy step. A test MUST assert this (grep the workflow set, `bin/`, `scripts/`, and the agent prose for an invocation of the installer's copy entry point) — the same shape as the FR4 guard, because the "someone will automate the install for convenience" regression is exactly the one that silently deletes FR2.
- **Acceptance (FR2):** merge a change to a declared source file; the execution copy is byte-identical before and after; a currency check reports **stale**; only a human-run install changes the bytes.

### AD-5 — The **install record** is the trust anchor: content-addressed, written by the install, stored outside every clone, never granted to any session. (BINDING — FR7, FR29.)

At install time, for every file in the AD-1 declared set *and* every generated artifact (per-role settings, AD-14), the installer writes one record containing at minimum:

- the artifact's **path at the execution site** (or, for generated in-clone artifacts, its clone-relative path),
- its **content hash** as installed (`_sha256`, AF-038-3),
- the **source provenance**: release tag (`.hos-release`), the source commit the install was performed from, and for generated artifacts the **template hash + role**,
- the **install timestamp** and the identity that ran it.

Bound properties:

1. **Location:** alongside the execution root, outside every clone, under the state root. **Never** in any `additionalDirectories` grant (AD-2).
2. **Written atomically** and as a unit with the copy: a torn install must be detectable as such (an install-in-progress marker, cleared on completion), because a half-written record would classify healthy files as unrecognised and halt the machine.
3. **It is the trust anchor, not git.** Integrity is judged against *this record*, never against repository history — see AD-6.
4. **It is not `.hos-manifest`.** `.hos-manifest` lives in the target repo and is agent-writable; it keeps its existing job. This record is its out-of-clone sibling. `technical-design` MAY share the row schema and the `_sha256` helper; it MUST NOT share the file.

### AD-6 — The currency check: run-time, execution-site, **integrity from the install record / currency from the committed source**, four outcomes, never a write. (BINDING — FR7, FR8, FR9. Stale *response* is Q3-HELD.)

VF-038-7 is right that the `gen_codeowners.sh` → CODEOWNERS CI-diff pattern cannot transfer: both of its sides are in-repo and CI can see neither the execution copy nor the machine. The check therefore runs **at the execution site, at launcher start**, and is defined as follows.

**Two independent comparisons, deliberately anchored differently:**

| Comparison | Question | Anchor | Trust |
|---|---|---|---|
| **Integrity** | Are the executed bytes what the install put there? | the **install record** (AD-5) | trusted — outside every clone, human-install-written |
| **Currency** | Has the source moved since the install? | the **committed** source in the clone (`git show <ref>:<path>`), not the working tree | untrusted input; used only to decide *stale vs current* |

**Why the anchors differ, and why this is the crux.** The obvious design — "does the copy match some committed state of its source?" (FR9's literal wording) — makes **repository content the integrity anchor**, and the repository working tree is agent-writable in two of three roles today (VF-038-6). Under that design an actor who can write the repo can manufacture a matching blob and launder a modified copy into "recognised." Anchoring integrity on the install record removes the repo from the tamper decision entirely: the only way to change what is *recognised* is to run an install, which is FR2. Currency, by contrast, is not a security judgement — it is a maintenance signal — so a spoofable input is acceptable there, and using the **committed** source rather than the working tree means (a) an uncommitted local edit does not demand a reinstall and (b) the drift signal tracks *merged*, PR-gated change, which is exactly what "a human should reinstall" means.

**Four outcomes, bound:**

| Outcome | Condition | Response |
|---|---|---|
| **CURRENT** | integrity OK; recorded source hash == committed source hash | silent, proceed |
| **STALE** | integrity OK; committed source has moved since install | **loud** stderr report per the #1200 standard, naming each drifted file and the remediation (re-run the install); escalate on persistence; **run/halt is Q3, HELD** — the check emits the classification, a configured policy chooses the response, default HELD |
| **CURRENCY-UNKNOWN** | integrity OK; the source repo is unreadable/unreachable/not a git tree | warn, proceed. Integrity is intact; absence of a maintenance signal is not a tamper signal, and failing closed here would let an unrelated repo problem halt the machine |
| **UNRECOGNISED** | integrity FAILS — executed bytes ≠ install record, or a declared file is missing/extra, or the record itself is unreadable/torn | **fail closed: refuse to run**, escalate immediately (AD-16). Not configurable — no knob may widen what runs (the `min(trusted_baseline, clamp(env,0,1))` idiom, `run_second_review.sh`) |

**Further bound rules:**

- **Never self-heals (FR8), structurally.** The check performs **no write to the execution root, ever** — not a copy, not a patch, not a permission fix. `technical-design` MUST make this checkable by inspection (the drift path contains no write call with an execution-root destination) and MUST include a test asserting the executed copy is byte-identical after a detected drift. This is the prohibition most likely to be "helpfully" violated during implementation; it is the one that would rebuild the exact agent-edit → unsandboxed-execution path the whole ADR removes.
- **The checker is a member of the executed set and verifies itself first.** A checker living in the clone would be agent-writable and could be neutered; a checker that verifies everything but itself has a one-file blind spot. Bind the order: self-hash against the install record → refuse on mismatch → then verify the rest.
- **Honest statement of what it does not do.** The check's soundness rests entirely on AD-2's write boundary. Against an actor who can write the execution root it provides nothing (they rewrite the record too). It MUST NOT be documented as tamper-*proofing*; it is tamper-*evidence* conditional on the sandbox.
- **Cost:** hashing the declared set plus one `git show` per file, per launcher start (≈5-minute cron cadence). Negligible; no caching, because a cache is a second trust anchor.

**Rejected alternatives.** (a) *Symlink the in-clone paths at the execution root* — a symlink inside an agent-writable clone can be replaced by a regular file, so it provides no protection while creating the appearance of it. (b) *Verify the copy against git history* — see above; makes the repo the integrity anchor. (c) *A CI test in the `gen_codeowners.sh` shape* — VF-038-7; CI cannot see the artifact. (d) *Periodic background verification instead of at-launch* — leaves a window in which a tampered copy executes, and needs a scheduler that is itself part of the executed set.

### AD-7 — Migration detection is the **launcher's own self-location check**, plus updated emissions and an explicitly resolved `.envrc`. (BINDING — FR11, FR12, FR14, FR10.)

VF-038-2 is correct that nothing writes crontabs, so migration is detect-and-report. Bound:

- **Self-location shim (FR12).** Every launcher, at start, resolves its own real path (`readlink -f "$0"` or equivalent, to defeat symlink games) and compares it against AD-3's resolver output. If it is executing **from inside a clone while a valid execution root exists**, it (a) still does its job (FR10 — nothing breaks), and (b) emits a loud stderr report naming *the exact invocation path it was started from* and *the exact replacement path*, and records an escalation (AD-16) so it also surfaces at the next session start. If no execution root exists (pre-migration install), it is **silent** — no nagging at installations that have not yet been offered the mechanism.
- This gives FR12 detection at the precise site with no new component, and gives FR6 its enforcement path: in a later phase (AD-8) the shim escalates from *warn* to *refuse*, at which point in-clone `bin/` is provably not an execution path. The shim is a migration aid, not a control — in Worker/Overseer an agent could delete the warning, which changes nothing, because that path is already open.
- **Emitted instructions (FR11).** Both emitters — `hos_install.sh:2452/2456/2459` and `hos_setup_partner.sh:212–221` — plus every doc that reproduces a crontab line MUST take the path from AD-3's resolver. A test greps installers and docs for an in-clone launcher path and fails on any hit outside a clearly-marked historical/migration section.
- **`.envrc` (FR14) — resolved, not left ambiguous: repoint, do not drop.** `PATH_add bin` currently makes a human's shell find the *source* copy — after migration, the one thing that must never be executed. Bind: `.envrc` puts the **execution root** on `PATH` and never the clone's `bin/`. If the resolver reports no execution root (unmigrated), it adds **nothing** — typing `hos-human` then fails with "not found," which is the correct, loud failure, rather than silently running the unexecuted source copy. `.envrc` is per-clone and consumer-editable; ship the corrected form and name it in the migration steps.

### AD-8 — Implementation phases, strictly ordered, with a per-clone protection table. (BINDING — FR13, FR10, FR6. This is the sequencing decision FR13 demands, and it is stated as an architectural decision, not a work plan.)

**No protection change is scheduled before its stated predecessor is *verified by measurement*.** The rule that makes this non-negotiable: removing the Human clone's `bin/` deny rules before copy-on-install and crontab migration are verified opens, for real, the path the original handoff mistakenly believed was already closed (REQUIREMENTS-038's own RISK statement, second item).

| Phase | Content | Predecessor (must be **verified**, not merely merged) |
|---|---|---|
| **P0** | AD-1 declaration + both guard tests + the closure test/residual register. Ship-set correction only; **no behaviour change** (the three unshipped launchers begin reaching consumers) | — |
| **P1** | Copy-on-install to the AD-3 execution root + AD-5 install record + AD-4 human-only gate. In-clone launchers keep working, untouched (FR10) | P0 |
| **P2** | AD-6 currency check (fail-closed on UNRECOGNISED from day one; STALE response defaults per Q3) + AD-14 per-role settings generation. **AD-14 is in this phase, not later** — per AD-2 it is what makes P1's relocation a boundary for Worker/Overseer | P1 |
| **P3** | AD-9 … AD-13: the syncer, session-lock contract, journalled state machine, marker. Cron entry for the sync added, naming the execution root from the start | P1 (execution root exists), P2 (marker readability granted) |
| **P4** | AD-7: emitted crontab instructions, docs, `.envrc`, self-location shim in **warn** mode. Operators migrate their crontabs by hand | P1 |
| **P5** | **Verification gate, measured, not assumed:** no crontab entry, systemd unit, `.envrc`, doc step, or script invokes an in-clone launcher on any machine in scope; currency check green; sync marker healthy for a stated observation window | P2, P3, P4 |
| **P6** | Protection changes — per-clone table below. **Never bundled with P1** (FR13's explicit prohibition) | P5 |

**Per-clone protection table (FR13's required deliverable). "Today" is measured this session and MUST be re-measured at implementation time.**

| Clone / role | Protection today (measured 2026-08-05) | What changes | After which verified step | Owner |
|---|---|---|---|---|
| **Human** | `.claude/settings.local.json` exists, 45 deny rules, incl. `Edit(./bin/**)` and the absolute-path variant; `additionalDirectories` = 6 entries | **Removal** of the two `bin/` deny rules (they now protect a source-only directory and mislead), and `additionalDirectories` narrowed to exclude the execution root / state root, plus the marker subtree added | **P5** | this change |
| **Worker** | **No `settings.local.json` at all.** Write probe into `Worker/bin/` from a sandboxed session **succeeded**. Cron executes `Worker/bin/hos-cron` unsandboxed | **Addition** of a sandbox posture — there is nothing to remove. Until it lands, AD-2's residual applies and relocation is hygiene, not a boundary | belongs to **#1146/#1183**, not this change; P2's generated settings is the vehicle | #1146/#1183 |
| **Overseer** | Identical to Worker: absent | Identical to Worker | as Worker | #1146/#1183 |
| **Consumer (e.g. `CondoParkShare/{Worker,Overseer}`)** | Same shape; cron executes clone-internal launchers (measured in the live crontab) | Inherits P0–P6 as a framework property (FR34) via the same installer path | as HOS's own | this change |

**Interim mitigation for the measured Worker/Overseer exposure is Q1 — the human's, and I do not bind it.** The table has a row for it; whichever way it is ruled changes only whether an interim posture lands before P1.

### AD-9 — **One syncer component, two call sites**, one mutex; #1200's report is preserved as the syncer's non-success output. (BINDING — FR15, FR18, FR36.)

- **One component performs every fast-forward on a clone**, invoked from (a) the new cron entry (the out-of-band cadence this issue exists for) and (b) interactive launcher startup, *before* the session lock is registered and before the CLI is started. Two independent git paths would race on the index lock and produce exactly the partial states FR19–FR22 exist to prevent.
- **Launcher startup order is bound:** preflight → auth → **syncer** → **register session lock** (AD-10) → start the CLI. Syncing before the lock is what lets a session start current; syncing after would deadlock the launcher against its own lock.
- **The syncer is a member of the executed set (AD-1)** and executes from the execution root. It is not run from a clone.
- **#1200 is composed with, not re-implemented (FR36).** The existing `STALE — HEAD is N commit(s) behind …` report and its structural-vs-transient classification are the syncer's non-success output, preserved in behaviour and wording. Detection (#1200) and remediation (this design) remain separate concerns; the marker (AD-13) and the report derive from the same git facts and therefore agree.
- **Cadence is a configured parameter (FR15), value HELD (Q2).** Bind the *shape*: a named configuration key (the `config.sh` idiom, alongside `PACK=`/`AUDIT_BACKEND=`), an environment override for operators, and a **floor** the configuration may not undercut (clamp; knobs may only narrow). The shipped default and the floor are the human's; both MUST be documented at the point a deployer configures them. Changing the cadence MUST require no mechanism edit — the acceptance test is a config-only change.
- **Fast-forward only, and nothing else (FR18).** No merge (other than `--ff-only`), rebase, reset, force, force-with-lease, stash, or branch checkout in the sync path. When the default branch is not checked out, the update is `git fetch origin <d>:<d>`, which git permits only as a fast-forward and which does not touch the working tree at all. The argument this rests on — *a fast-forward from the upstream default branch introduces only PR-gated commits* — is the entire justification for an unreviewed automated change to a clone, so any operation that could introduce un-gated content is prohibited on **correctness** grounds, not style.

### AD-10 — The session-lock contract: a **multi-holder, clone-keyed session registry**, distinct from `hos-cron`'s exclusive overlap mutex; `exec` must go. (BINDING — FR16, FR17.)

VF-038-4 is right that no interactive launcher registers anything today. The fix is not to reuse `hos-cron`'s lock: they are different structures for different questions.

| | `hos-cron` overlap lock (exists) | Session registry (new) | Sync mutex (new) |
|---|---|---|---|
| Keyed by | (role, project) | **clone path** | clone path |
| Cardinality | exclusive, one holder | **multi-holder** — several sessions may be live in one clone | exclusive |
| Question | "is another cycle of this role running?" | "is any session live in this tree?" | "is another sync touching this tree?" |
| Read by | `hos-cron` | **the syncer** (skip decision, FR16) | the syncer |

Bound:

1. **Every session registers** — `hos-cron` (in addition to its existing overlap mutex, which it keeps), `hos-human`, `hos-worker`, `hos-overseer`, and any future launcher. Registration records at minimum: pid, role, clone path, launcher, start epoch. Location: a dedicated subtree of the state root (**not** the marker subtree — sessions must not be able to forge or clear their own lock; per AD-2 the registry subtree is not granted to any session).
2. **Release on every exit path (FR17).** Trap-based release on normal and signalled exit, **plus** liveness/age reclamation as the backstop for `kill -9`.
3. **`exec claude` MUST be replaced (AF-038-4)** in `hos-human`, `hos-worker`, `hos-overseer`: run the CLI as a child, propagate its exit status, forward `INT`/`TERM`, release in the trap. Without this, FR17 is unimplementable in exactly the three launchers it was written for. `technical-design` specifies signal handling and exit-code propagation; this is a user-visible change to session-start behaviour and MUST be called out to `pm-agent` if it alters anything an operator observes.
4. **Reclamation, reusing `hos-cron`'s hard-won rules (#1002).** Liveness by `kill -0` **and** an age ceiling (PID reuse makes liveness alone a permanent standstill; an age ceiling alone races an in-flight registrant). **Ambiguity resolves toward skipping the sync**, never toward proceeding: an entry with no recorded pid is "registrant in flight" → treat as held. Every reclamation is recorded (FR17) via the marker/escalation path.
5. **Skip is the primary control (FR16, P3).** With any live holder, the syncer performs **no git operation that changes the working tree** and records a skip with its reason. A fetch that updates only remote-tracking refs is permitted while a session is live (it cannot change the tree) — and is useful, because it is what lets the in-session #1200 report say *how* stale the session is. `technical-design` MUST confirm the fetch cannot perturb a concurrent session (it writes refs and objects, not the worktree/index) and MUST make it skippable by configuration if that confirmation is not clean.
6. **A session that consequently never syncs is not a bug (P3).** It is told it is stale by #1200. Do not add a "sync anyway after N skips" escape hatch — that is precisely the mid-session mutation P3 forbids.

### AD-11 — The sync state machine: **journal first, fetch outside the window, one tree-modifying step, verify-or-restore, latch on unrecoverable.** (BINDING — FR19, FR20, FR21, FR23.)

States, bound: `IDLE → PRECHECK → FETCHED → JOURNALLED → MERGING → VERIFYING → {OK | RESTORING → {RESTORED | QUARANTINED}}`.

1. **PRECHECK.** Acquire the sync mutex; check the session registry (AD-10) — held ⇒ skip, record, exit. Check for a non-terminal journal from a previous run ⇒ **recovery path** (below). Evaluate the cleanliness precondition (AD-12).
2. **FETCHED.** `git fetch` **before** the journal is written and **outside** the journalled window (AF-038-9). Fetch has no working-tree effect, is idempotent, and is safely retryable; folding it into `pull --ff-only` makes every network failure look like a tree risk. If the fetch fails, record a failure and exit — no journal was written, no tree was touched, nothing to repair.
3. **JOURNALLED — FR19.** Before the first command that can modify the tree, write **durably and atomically** (mktemp + fsync + rename, same filesystem — the `hos_repo_sync.sh:180–186` precedent, which is already correct) a journal containing: clone path, pre-operation commit SHA, checked-out branch, target commit SHA, the cleanliness assertion that was verified, timestamp, pid. Durability across a kill at any point is the requirement; a journal written after the merge starts is worthless.
4. **MERGING.** Exactly one tree-modifying command: `git merge --ff-only <remote-tracking-ref>` on the checked-out default branch. In the "default branch not checked out" case there is **no** tree-modifying step at all (`git fetch origin <d>:<d>` updates a ref), so the journal covers a no-op and the machine reduces to fetch-and-record.
5. **VERIFYING — FR21.** Success is asserted, never assumed: HEAD == the target commit **and** the tree is clean under the same predicate used in PRECHECK. "Reported successful" and "actually at the new commit with a clean tree" are the same condition. Any discrepancy ⇒ RESTORING, and the outcome is recorded as **failure**.
6. **RESTORING — FR20, and the FR18 reconciliation (AF-038-7).** The repair path uses exactly **one** primitive: `git reset --hard <journalled pre-commit>`, restricted to tracked files. It MUST NOT run `git clean` (untracked files are not this mechanism's to delete — AD-12 permits them), MUST NOT touch any other branch, and MUST NOT fetch. This does not violate FR18's intent: FR18 constrains what the **sync** may introduce (only PR-gated fast-forward content); restoration *removes* content that was never gated and returns the tree to a commit that was already there. ESC-C asks `pm-agent` to say so in the text.
7. **Terminal states.** On successful restore: record failure + restored, clear the journal, escalate per AD-16. On failed restore or a tree that cannot be verified at the pre-state: **QUARANTINED** — the journal is retained, the mechanism performs **no further git operation on that clone, ever**, and every subsequent invocation re-escalates. Bounded: recovery is attempted **at most once**; there is no retry loop that can grind a damaged tree.
8. **Recovery is code, not a runbook — FR22 + FR23 reconciled.** The two requirements read as contradictory (FR22: *refuse to proceed and escalate*; FR23: *repair by code, deriving the target at run time*). Bound reconciliation: on finding a non-terminal journal the mechanism **automatically restores to the journalled pre-state** — the target is derived from the journal at run time, no hand-written commit-specific procedure, which is exactly FR23's requirement and exactly what the thread's decaying four-step manual repair failed at — and then **refuses to perform any new sync in that invocation** and escalates, which is FR22. Repair yes; new work no.

### AD-12 — Preconditions and clocks: cleanliness on **tracked** state only; success and failure keep **separate clocks**; failures back off and latch. (BINDING — FR18, FR22.)

- **Cleanliness precondition (AF-038-6).** Defined on modifications to **tracked** files and index state (`--untracked-files=no`, or equivalent). Untracked files are permitted and are **not** a skip reason — otherwise the Worker clone, with its dozens of untracked `audit/log/**` records, skips forever and FR32 escalates on normal operation. The one real hazard, an incoming commit adding a path that collides with an untracked file, is handled by git itself: `merge --ff-only` refuses **before** touching anything, which is a clean abort recorded as a failure, not a partial state.
- **Local uncommitted edits survive (FR18).** Guaranteed structurally: the only tree-modifying step runs under a verified no-tracked-modifications precondition, so there are none to lose; and restoration never touches untracked paths.
- **Two clocks, not one — the FR22 bug fix.** Today `hos_repo_sync.sh` writes `last_sync_epoch` on the pull-failure path (`:180–186` runs unconditionally), so one failure silences retries for the whole interval. Bind:
  - `last_success_epoch` — advanced **only** on a verified success (AD-11 step 5); it is what the cadence interval is measured from.
  - `last_attempt_epoch` + `consecutive_failures` — advanced on failure; the next attempt is gated by a **short retry floor with bounded backoff**, never by the full cadence interval.
  - A **skip advances neither** — a skip did no work and must not be able to mask staleness. (It does advance the skip counter, AD-16.)
  - After a stated number of consecutive failures the mechanism **latches**: stop attempting, keep escalating. An unbounded retry against a structurally broken clone (#1183's read-only sandbox class) is a busy loop, not resilience.
- **Bound negative test (this is the regression that already happened once):** after an induced failure, the next scheduled invocation MUST attempt again rather than report "skipped, last synced Ns ago."

### AD-13 — The marker: **distinct from the journal**, one atomic replace carrying outcome *and* durable counters, in a dedicated read-granted subtree that holds no credentials and no integrity-bearing artifact. (BINDING — FR24, FR25, FR26.)

- **Marker ≠ journal.** The journal (AD-11) is in-flight *intent*, short-lived, never read by a session. The marker is durable *outcome*, read by humans and sessions. Conflating them is the defect `hos_repo_sync.sh`'s single state file already has (it records a timestamp that means neither). Two artifacts, two lifecycles.
- **Fields (FR24), as data — serialization is `technical-design`'s:** state ∈ {running, ok, skipped, failed} (plus the AD-11 terminal `quarantined`), timestamp, commit-before, commit-after, and — when skipped or failed — the reason. A marker missing a mandatory field MUST be detectable as malformed by its own well-formedness rule.
- **Counters live in the marker (FR32's durability requirement).** `consecutive_skips`, `consecutive_failures`, `last_success_epoch`. One document, one atomic replace, so a reader can never observe counters inconsistent with the outcome they belong to.
- **Atomic write (FR25):** mktemp + fsync + rename on the same filesystem; never truncate-and-rewrite. The existing `hos_repo_sync.sh:180–186` pattern is the precedent and is already sound — reuse it, add the fsync.
- **Location (FR26) — the constraint AF-038-5 imposes.** A **dedicated subtree of the state root**, disjoint from the execution root, the install record, the session registry, and the journal. Bound invariants: (i) **only this subtree** is granted to a role's sandbox (AD-2); (ii) it MUST NOT contain credential material — `hos-cron:484`'s `mktemp -p "$_HOS_DIR"` installation-token file stays out of it, and `technical-design` SHOULD move that mktemp into an explicitly non-granted subtree so the invariant is structural rather than incidental; (iii) it holds nothing integrity-bearing (the install record's trust depends on being ungrantable).
- **Read/write asymmetry, honestly stated.** `permissions.additionalDirectories` grants a *working* directory, so grant + a write **deny** rule is the strongest available same-uid form. Under the OS sandbox the grant is the kernel-enforced part and the deny is advisory (`CLAUDE.md`). Bind the residual: **the marker is a backstop signal, never a control.** Its worst-case compromise is a session deceiving itself about its own staleness; the controls are AD-2's write boundary and AD-10's lock. This is consistent with P3, which already makes the marker the backstop.
- **Not destroyed by the thing it describes (FR26):** it lives outside every clone, so the fast-forward it reports cannot overwrite it.

### AD-14 — Per-role settings generation: template as a **protected surface**, deterministic generation, provenance and drift through AD-5/AD-6's single mechanism. (BINDING — FR27, FR28, FR29; load-bearing for AD-2.)

- **Three-part change (VF-038-8), all three required:** untrack `.claude/settings.json`; add a **template**; generate per role at install. Shipping any two is a regression: untracking without a protected template converts a reviewed artifact that *executes code outside the sandbox* (`hooks.SubagentStop` → `python3 scripts/oversight/record_agent_model.py`) into an unreviewed one — the inversion P4's own caveat forbids.
- **The template is a protected surface (FR28).** Add its path to `scripts/framework/protected_surfaces.txt` and regenerate CODEOWNERS (`templates/CLAUDE.human.md` is listed individually, so a template under `templates/` needs an explicit entry; one under `scripts/framework/**` is covered by the existing glob). A PR touching it requires human approval.
- **Generation is deterministic (FR29):** the output is a pure function of (template, role, resolved paths, release). Regenerating from the same inputs yields an identical file.
- **Provenance and drift ride AD-5/AD-6 — one mechanism, two payload classes.** The install record carries template hash + role + release for each generated file; the currency check reports a hand-edited generated settings file as diverged. **Difference bound:** a generated settings file lives *inside* the clone and is therefore agent-writable, so its drift response is **warn**, never fail-closed — a role cannot be prevented from editing its own settings, only observed doing it. `technical-design` MUST NOT reuse UNRECOGNISED's fail-closed response here; that would let an in-clone edit halt the machine.
- **In-file provenance is contingent.** JSON has no comments, and it is not established that the CLI tolerates unknown top-level keys. Bind: provenance is authoritative **in the install record**; an in-file `_hos`-style provenance key is permitted **only** if `technical-design` verifies empirically that the CLI ignores unknown keys. Do not design around an assumption here.
- **Required content (FR27):** each role's generated file MUST grant read of the marker subtree (FR26) and MUST NOT grant the execution root, the install record, the session registry, or the state root (AD-2). A role cannot be configured into a state where its backstop is unreadable — nor into one where its boundary is void.
- **Residual, named because P4 creates it and this ADR must not hide it:** the template governs *which* command the hook runs; the hook's target (`scripts/oversight/record_agent_model.py`) lives in the clone and `scripts/oversight/**` is **not** a protected surface (only `gates/**`, `run_validators.sh`, and `validators/schema.py` are). So an agent can still change *what the hook does* without a human approval, even with a perfectly protected template. That is pre-existing, not introduced here, and it is out of scope — **file it as an issue**; do not silently inherit it as though the template closed it.

### AD-15 — The not-an-agent-role guard is **environmental and enforced**, and the invariant is stated at the cron entry. (BINDING — FR30, FR31.)

- The syncer refuses to run when its process environment carries markers present **only inside a launched agent session**. Bind the *shape*: **one named list** of marker variables, one refusal predicate, fail-closed (any marker present ⇒ refuse, exit without a single git operation, say why), and a test that runs the syncer under a simulated session environment.
- **Do not key on `HOS_CYCLE_ID`.** `hos-cron` mints and exports it in its own process (`:220–236`) *before* launching the session, so a syncer invoked from `hos-cron` after minting would refuse itself. Key on variables the **CLI** injects into the session (`CLAUDECODE` / `CLAUDE_CODE_*` class), verified empirically by `technical-design`, and — belt and braces — invoke the syncer from a launcher **before** any cycle identity is minted.
- **FR31:** the emitted crontab line carries the invariant as a comment (*this entry runs no agent, launches no model, and makes no decisions — it is not a human cron role*), and the mechanism's own header states it. A reviewer reading only the crontab can tell why the entry is not a governance violation. AD-7's emitters are the single place this text is produced.

### AD-16 — Escalation is a **durable outbox**: record → attempt delivery → mark delivered. Never attempt-and-discard. (BINDING — FR32, FR33; thresholds and channel are Q6-HELD.)

- **Two-phase by construction.** The escalation is written durably **first** (atomic write, in the marker subtree so a session can surface it), delivery is attempted **second**, and the record is marked delivered **third**. There is no code path in which an escalation is attempted, fails, and is discarded — that path is what reproduced the originating incident.
- **Undelivered items resurface at the next session start (FR33):** launchers read the outbox and print anything undelivered, alongside the #1200 staleness report. An escalation channel outage becomes loud at the next human contact rather than silent forever.
- **Counters and classes (FR32).** Consecutive **skips** and consecutive **failures** are counted separately and treated as qualitatively different: a skip means the mechanism deliberately did nothing (a session was live, the tree was dirty) — benign individually, pathological in accumulation; a failure means it tried and could not. A successful sync resets the skip counter. Counters are durable across process restarts (AD-13).
- **Thresholds and channel are Q6 — HELD.** pm-agent's recommendation (3 consecutive skips, 1 failure, reset on success) is not bound here. Bind only: both thresholds are **configuration**, both classes have one, and the escalation **channel** is a single seam (a tracked issue, a loud session-start report, or both) selected by configuration — so Q6 changes values and one selector, never the mechanism.
- **Escalation sources, all routed here:** UNRECOGNISED currency (AD-6), QUARANTINED sync (AD-11), latched failures (AD-12), reclaimed stale locks (AD-10), and in-clone launcher execution detected by the shim (AD-7).

---

### FR coverage

| FR | Bound by | FR | Bound by |
|---|---|---|---|
| FR1 | AD-1, AD-2, AD-3 | FR19 | AD-11 (3) |
| FR2 | AD-4 | FR20 | AD-11 (6) |
| FR3 | AD-1 (1,3) | FR21 | AD-11 (5) |
| FR4 | AD-1 (1,2) | FR22 | AD-11 (8), AD-12 |
| FR5 | AD-1 (4) | FR23 | AD-11 (8) |
| FR6 | AD-2, AD-7, AD-8 | FR24 | AD-13 |
| FR7 | AD-5, AD-6 | FR25 | AD-13 |
| FR8 | AD-6 | FR26 | AD-13, AD-2, AD-14 |
| FR9 | AD-6 (Q3 seam) | FR27 | AD-14 |
| FR10 | AD-7, AD-8 (P1/P4) | FR28 | AD-14 |
| FR11 | AD-7 | FR29 | AD-5, AD-6, AD-14 |
| FR12 | AD-7 | FR30 | AD-15 |
| FR13 | AD-8 | FR31 | AD-15, AD-7 |
| FR14 | AD-7 | FR32 | AD-16, AD-13 |
| FR15 | AD-9 (Q2 seam) | FR33 | AD-16 |
| FR16 | AD-10 (5) | FR34 | AD-1, AD-3, AD-8 |
| FR17 | AD-10 (1–4) | FR35 | AD-3 (Q4/Q5 seam) |
| FR18 | AD-9, AD-11, AD-12 | FR36 | AD-9 |

---

## 3. What is NOT bound here

### 3.1 The six held decisions, and the seam that absorbs each

I designed the mechanism so that every §4 ruling changes a **value or a single function body**, never a shape. Stated explicitly so `technical-design` builds the seam and not the answer:

| Q | The held decision | The seam that absorbs it | What changes when it is ruled |
|---|---|---|---|
| **Q1** | Interim mitigation for the measured Worker/Overseer exposure | AD-8's per-clone table has a row for it; AD-2 states the residual either way | Whether an interim posture lands before P1. No mechanism change. Note: AD-2 raises the stakes — until #1146/#1183 land, relocation is hygiene for those roles |
| **Q2** | Cadence value and floor | AD-9: named config key + env override + clamp-to-floor | Two numbers in configuration and their documentation. Acceptance test is that changing them requires no mechanism edit |
| **Q3** | Stale response: warn-and-escalate vs halt | AD-6: the check emits a *classification*; a configured **policy** selects the response | One configured default. UNRECOGNISED stays fail-closed and non-configurable regardless |
| **Q4** | Consumer execution-copy location | AD-3: **one resolver, one call site** | One function body. Every consumer (installer, launchers, checker, shim, `.envrc`, emitters, docs) follows without edit |
| **Q5** | Consumer gitignore (only if Q4 places the copy in-repo) | AD-3: a conditional install hook at exactly one call site | One conditional's behaviour. Moot under pm-agent's Q4 recommendation |
| **Q6** | Escalation thresholds and channel | AD-16: thresholds are configuration; channel is one selector | Two numbers and one selector |

### 3.2 New escalations I raise

**ESC-A — HIGH, the human's: how far does the executed-set closure go in the first implementation? (AF-038-1, AD-1.)** "All of `bin/`" leaves at least seven clone-resident artifacts executing unsandboxed outside the agent session, including the **installation-token minter** and the **cron prompt file the unattended cycle obeys**. This does not re-open P1 — P1's *property* is right, and the closure is what delivers it — but it materially changes the install footprint (most of `bootstrap/**` joins the execution set) and the operational surface, which is squarely the product-boundary checkpoint. **Options:** (a) full closure in P1; (b) `bin/` plus the credential and prompt paths in P1, remainder in a registered, tested residual with a named follow-up; (c) `bin/` only in P1 with the full gap registered. **My recommendation:** (b) — the token minter and the prompt file are the two that convert a working-tree write into unsandboxed execution *with credentials* and into *self-authored instructions*, and neither is expensive to include. **Whatever is chosen, the residual is registered with reasons and tested (AD-1 rule 2c); an implicit partial closure is not acceptable.** Also route to `pm-agent`: FR3's wording ("no reference back into a clone for its own dependencies") is already correct and stricter than VF-038-1's "all of `bin/`" framing — the two should be reconciled in the requirements text.

**ESC-B — `pm-agent`: FR9's first acceptance criterion is unsatisfiable under the only sound anchoring.** FR9 verifies *"a copy set to a prior committed revision of its source is classified **stale** and the launcher still runs."* Under AD-6, integrity is anchored on the **install record**, so a copy hand-set to a prior revision **without an install** does not match its record and is classified **UNRECOGNISED** (fail closed) — correctly, because "someone changed the executed bytes outside the install path" is exactly the tamper signal, and the alternative (anchoring on git history) makes agent-writable repository content the integrity authority. Requested restatement: *stale is produced by installing from an older source, not by hand-editing the copy to an older revision; any content the install did not place is unrecognised.* The FR9 *intent* (old-but-reviewed ≠ tampered) survives intact; only the test does not.

**ESC-C — `pm-agent`: FR18 and FR20 are literally contradictory.** FR18 forbids `reset`; FR20 requires restoring a tree to a recorded pre-state, for which `reset --hard <recorded commit>` (or the equally-prohibited `checkout --force`) is the only primitive. AD-11 (6) binds the reconciliation — FR18 governs the **sync path** (what content may be introduced), FR20 the **repair path** (removing content that was never gated, returning to a commit already present) — but the requirement text should say so, or an implementer will read FR18 literally and ship FR20 unimplemented.

### 3.3 Product-boundary items routed before these bind

Per the CORE product-boundary checkpoint, the following carry consequences beyond architecture and do **not** bind until cleared:

- **ESC-A** (install footprint / operational surface) — human.
- **AD-8's P6 protection changes** (deployment topology, trust boundary) — human; the Worker/Overseer half belongs to #1146/#1183.
- **AD-10 (3), removing `exec` from the three interactive launchers** — user-observable session-start behaviour (exit codes, signal handling) — noted to `pm-agent`.
- **AD-14's untracking of `.claude/settings.json`** — P4 already carries the human's sign-off; the *template path and its protected-surface entry* are a protected-surface change requiring human approval at merge regardless of tier.
- **A new cron entry** (AD-9) — an operational obligation on every machine running the pipeline; the cadence is Q2.

### 3.4 Follow-up issues to file (named, not designed here)

1. **`scripts/oversight/record_agent_model.py` executes from the clone via the settings `hooks` block and `scripts/oversight/**` is not a protected surface** (AD-14 residual). Pre-existing; the template does not close it.
2. **`hos-cron:484` mktemps an installation token into `$_HOS_DIR`'s root** (AF-038-5). Move it to an explicitly non-granted subtree so AD-13's "no credentials in a granted subtree" invariant is structural.
3. **`bootstrap/hos_repo_sync.sh` defaults its state dir to `/tmp/hos-repo-sync`, which the Human clone grants as an additional directory** (AF-038-5) — session-writable sync state. Subsumed by AD-13 if the syncer's state moves to the state root; file it so the old path is actually removed rather than left behind.

---

## 4. Where pm-agent was right, where I differ, and what I sharpened

- **Confirmed:** all nine VFs (I re-ran VF-038-1, -2, -4, -6, -7, -9 rather than inheriting them); the "detect-and-report, never silently rewrite a crontab" conclusion (AD-7); the state root as the marker's natural home (AD-13); the single-declaration requirement (AD-1); that the `gen_codeowners.sh` CI-diff shape cannot transfer (AD-6); that FR8, FR13 and FR28 are the three that must not be softened — I have made each structural rather than exhortative (AD-6's no-write-in-the-drift-path, AD-8's verified-predecessor phase gate, AD-14's protected template).
- **Differed — the load-bearing one: relocation is not the boundary (AD-2).** REQUIREMENTS-038 reads throughout as though moving the files out of the clone *is* the protection ("the location MUST be one an agent session cannot write"). On this machine, for two of three roles, no such location exists: same uid, no sandbox, no sudo at install. The boundary is the sandbox path allowlist, which makes P4's generated settings a **prerequisite** of P1's property rather than a sibling decision — and makes the honest statement of the Worker/Overseer residual (AD-2, AD-8) part of the deliverable rather than a footnote.
- **Differed — the currency check's anchor (AD-6, ESC-B).** FR9 defines recognised/unrecognised by reference to *committed state of the source*. That makes agent-writable repository content the integrity authority. I anchor integrity on the install record and use the repository only for the staleness signal.
- **Differed — the copy set (AD-1, ESC-A).** "All of `bin/`" satisfies every stated FR4 test and does not deliver P1. The set is a closure.
- **Sharpened:** the journal/marker separation (AD-13) — pm-agent's FR19 and FR24 read as one artifact and `hos_repo_sync.sh` already demonstrates the defect of conflating them; the two-clock fix (AD-12), which is the precise form of the FR22 bug; the cleanliness predicate (AD-12), which as written today would make the syncer skip forever in the Worker clone and escalate on normal operation; the fetch/merge split (AD-11); the multi-holder session registry as a structure distinct from `hos-cron`'s exclusive mutex (AD-10); and `exec claude` as a concrete blocker for FR17 (AD-10, AF-038-4).

---

## 5. Cleared-to-design

**`technical-design` MAY proceed now** against AD-1 … AD-16, building every Q1–Q6 seam per §3.1 and binding none of the values.

**`coder` is NOT cleared** until:
1. the human rules **ESC-A** (closure scope) — it determines what P0/P1 actually ship;
2. the human rules **Q1–Q6**, or explicitly defers the ones whose seams allow a shipped placeholder (Q2, Q3, Q6 can ship as configuration with a documented conservative default and be re-set later; **Q4 cannot** — the resolver's value must exist before any copy is written; **Q1 cannot** — it gates whether P1 lands before or after an interim posture);
3. `pm-agent` restates **ESC-B** and **ESC-C**, whose current acceptance criteria would fail a correct implementation;
4. the **P5 verification gate** is measured before any P6 protection change, per AD-8.

Independently: the implementation touches `bin/**`, `bootstrap/**`, `scripts/framework/**`, and adds a protected template — the implementation PR requires human approval at merge regardless of computed tier. **This ADR is not that approval.**

---

## 6. Startup-gap discipline and affected sign-offs

**Should any of this have been settled in an earlier architecture review?** Two items, and I record both rather than absorbing them:

- **AF-038-1 (the closure) and AF-038-2 (the sandbox dependency) are architecture-review-class findings against the *thread's* premise, not against a prior ADR of mine.** #1202's design handoff and its amendment both asserted "copy all of `bin/`" as the mechanism, and the amendment's own premise about the installer was stale (VF-038-1). pm-agent caught the ship-set half; the *closure* half and the *enforcement* half survived to this review. There is no prior ADR-038 to revise, so this is a first-pass finding, not a late correction.
- **Affected sign-offs: none orphaned.** No design or code sign-off has been issued against any ADR-038 decision — this is the first. REQUIREMENTS-038 is DRAFT-for-architect and unmerged. AD-2 and AD-6 revise premises for paths **never built**, so prior sign-offs stand vacuously. Nothing requires re-review.
- **One adjacent coupling to watch:** #1201 (v0.7.2) is to be re-scoped as this design's implementation or closed as superseded, and #1146/#1183 own the Worker/Overseer sandbox that AD-2 makes load-bearing for FR1. **AD-8's P6 depends on that work for two of three roles**; this ADR does not absorb it and MUST NOT be read as delivering it.

---

## 7. Architect rulings on technical-design's escalations (2026-08-06)

**Addendum, append-only.** Nothing in §0–§6 is withdrawn or rewritten. Numbered §7 rather than inserted after §3 so no existing section is renumbered. TD-ESC-1, TD-ESC-2 and TD-ESC-4 (TECHNICAL-DESIGN-038 §15.2) are mine; **TD-ESC-3 is `pm-agent`'s and is not ruled here.** New bindings are **AD-17 … AD-20** and extend §2 with the same force.

Per this repo's convention I re-measured every claim rather than inheriting it. **All three findings hold.** One proposed fix is confirmed with a correction that changes its scope, one is confirmed in shape but **insufficient as specified** (it would break `hos-human` on every machine today), and one is **reversed** — the change technical-design proposes would reduce the boundary this ADR exists to create.

### 7.0 Re-verification of technical-design's factual claims

| Claim | Verdict | What I measured |
|---|---|---|
| `contract/sandbox-policy.template.json` exists, 6,683 b, top keys `model`/`hooks`/`permissions`/`sandbox` | **CONFIRMED** | `ls -la contract/sandbox-policy.template.json`; `python3 -c "json.load(...)"` → keys as stated; `sandbox.filesystem` = `denyRead`/`allowRead`/`allowWrite`/`denyWrite` |
| It is already a protected surface, needs no new entry | **CONFIRMED** | `grep -n "contract/" scripts/framework/protected_surfaces.txt` → `17:contract/**` |
| It is wired to nothing | **CONFIRMED** | `grep -rn "sandbox-policy.template.json" bootstrap/ scripts/` → zero hits; `docs/SANDBOX-POLICY.md:10-13` says so in terms and assigns it to #1146 |
| FR27's file and FR26's grant are different files | **CONFIRMED** | `git ls-files .claude/` → `.claude/settings.json` tracked; `grep -n "settings.local" .gitignore` → `40:.claude/settings.local.json` |
| `hos-human:22`, `hos-worker:10`, `hos-overseer:8` resolve `REPO_ROOT` from `$(dirname "$0")/..` | **CONFIRMED, verbatim at those lines** | `grep -n 'REPO_ROOT=' bin/hos-human bin/hos-worker bin/hos-overseer` → all three `git -C "$(dirname "$0")/.." rev-parse --show-toplevel`; `bin/hos-cron:111` is `_conf_val ${ROLE}_root`; `bin/hos-suspend:20` reads `projects.conf` and has no `REPO_ROOT` |
| The template carries `sandbox.filesystem.denyWrite: ["__PROJECT_ROOT__/bin"]`; the live Human profile does not | **CONFIRMED** | template `denyWrite = ['__PROJECT_ROOT__/bin']`; live `Human/.claude/settings.local.json` `sandbox.filesystem` keys = `allowWrite`, `denyRead`, `allowRead` — **no `denyWrite` key at all** |

**AF-038-10 — NEW, and it invalidates technical-design's TD-ESC-2 fix as specified: `projects.conf` has no Human entry, so a registry-driven `hos-human` cannot resolve anything.** The live registry holds `<key>_config_dir`, `<key>_worker_root`, `<key>_overseer_root`, `<key>_target_release` for two projects — **and no `_human_root` for either.** `hos_repo_root_for <project> human` (TECHNICAL-DESIGN §6.1) therefore returns empty on every existing machine, and `hos_project_for_clone <Human clone>` (which scans for a `_<role>_root` value matching the clone) returns **exit 1, no match** for the very clone `hos-human` runs in. Shipped as designed, slice S12 makes `hos-human` **refuse to start** everywhere — a regression against FR10, in the one launcher whose clone this issue is named after.
*Commands:* `sed -n '1,40p' ~/.config/hos/projects.conf`; `grep -rn "human_root" ~/.config/hos/projects.conf bin/ bootstrap/ scripts/ docs/` → **zero hits**

**AF-038-11 — NEW: the `bin/` write protections are not three entries in one place; they are three rule *shapes* split across two artifacts, and neither artifact holds all three.** Measured: live `Human/.claude/settings.local.json` `permissions.deny` holds exactly two `bin/` entries (`Edit(./bin/**)`, `Edit(//home/scott/Code/HumanOversightSystem/Human/bin/**)`) and **no** `denyWrite`; `contract/sandbox-policy.template.json` `permissions.deny` holds exactly **one** (`Edit(./bin/**)`, no absolute-path variant) **plus** the OS-enforced `denyWrite`. A count is the wrong instrument here (§7.3).

### 7.1 TD-ESC-1 — RULING: the two-payload-class factoring is **correct and confirmed**. This change **consumes and extends** #1146's Class-B template; it does not author it. Enforcement of AD-2 moves out of the template and into the generator. (AD-17)

**Where AD-14 was wrong.** AD-14 read FR27 literally and specified "add a template" as though one file carried both the `hooks`/`allow` payload and the sandbox posture. It does not, and I did not measure it. Technical-design's §8.2 split is right; I bind it.

**AD-17 (BINDING — extends AD-14; FR26, FR27, FR28, FR29; load-bearing for AD-2).**

1. **Two payload classes, one generator, two outputs — confirmed as §8.2 specifies.** Class A: `<clone>/.claude/settings.json` from a **new** `contract/role-settings.template.json` (`permissions.allow`, `hooks.SubagentStop`) — **owned by this change**. Class B: `<clone>/.claude/settings.local.json` from the **existing** `contract/sandbox-policy.template.json` (`permissions.deny`, `additionalDirectories`, `sandbox.*`) — **owned by #1146**.
2. **AD-14's rule "add the template path to `protected_surfaces.txt` and regenerate CODEOWNERS" is superseded: place both templates under `contract/**` and the requirement is already met** (`protected_surfaces.txt:17`). An explicit entry plus a `gen_codeowners.sh` run is required **only** if `technical-design` places Class A's template outside `contract/**`. FR28 is satisfied by placement, not by a new list entry.
3. **Ownership: consume-and-extend, not author.** This change **MUST NOT** re-author, restructure, re-scope or reformat `contract/sandbox-policy.template.json`. Its only permitted edit is **additive**: adding `__MARKER_DIR__` to `sandbox.filesystem.allowRead`. Rationale: the file is a protected security artifact whose open design questions (`docs/SANDBOX-POLICY.md` §4 — the `bypassPermissions` conflict at `:83`, the unresolved glob semantics at `:216-227`) belong to an issue that is not this one. Forking a security posture across two issues is how two half-reviewed postures ship. The edit is cross-referenced in both #1202 and #1146.
4. **AD-2's negative rule is enforced in the generator, not in the template — and this is the reason the ownership split is safe.** Technical-design's §8.2 required-content assertions (marker subtree present in `allowRead`; absent from `allowWrite` and `additionalDirectories`; execution root / install record / session registry / journal / auth dir / state root absent from all three) are **elevated from an implementation detail to the load-bearing control**, and their failure mode is bound: **the generator refuses to write.** A template owned by another issue can change without this change's review; a generator that verifies the posture it emits is correct regardless. Do not move these checks into the template, and do not downgrade any of them to a test — a test that runs in CI does not run at install time on an operator's machine.
5. **Class B generation is enabled per role by an install-time selector that defaults to Human only, until #1146 lands.** This change ships the **vehicle**; #1146 rules **when it is enabled for Worker and Overseer.** Generating a posture for a live autonomous role whose sandbox design is unresolved would ship an untested security control under this issue's review.
6. **Correction to technical-design §14's "the pivot slice is S8":** S8 delivers the *vehicle*, not the boundary. A build that ships S8 has **not** delivered FR1 for Worker or Overseer, and — per AD-2's residual, which stands unchanged — must not be documented as having done so. AD-8's per-clone table already said the Worker/Overseer rows belong to #1146/#1183; §14's sentence must be brought into line with it.

**Not changed by this ruling:** AD-14's warn-never-fail-closed drift response for both classes; AD-14's refusal to assume the CLI tolerates unknown top-level keys; the AD-14 residual on `record_agent_model.py` (§3.4 item 1 / TD ISSUE-4).

### 7.2 TD-ESC-2 — RULING: the fix is **confirmed in shape and insufficient as specified.** Registry-driven resolution is right; it cannot ship without a registry key that does not exist, and three further corrections. (AD-18)

AF-038-2 said "relocating the launcher is path-safe." That was measured on `hos-cron` and stated about launchers in general. **It is wrong for the three interactive launchers, exactly as TD-VF-038-1 finds, at exactly the lines it names.** The conclusion stands corrected.

**AD-18 (BINDING — extends AD-3 and AD-10; FR1, FR10, FR34).**

1. **Confirmed:** the three interactive launchers become registry-driven, `hos_paths.sh` gains the reverse-resolver `hos_project_for_clone`, ambiguity is **exit 3 and never a guess**, and the launchers gain `--project`. I bind technical-design §6.1 and §6.2 as written on those points.
2. **Correction A — the registry key is a prerequisite, not a detail (AF-038-10).** `<project>_human_root` does not exist in `projects.conf` and is written by nothing. Bound: (a) `hos_install.sh` and `hos_setup_partner.sh` — the two writers of `projects.conf` — MUST write `<project>_human_root`; (b) a documented one-line migration for already-registered machines; (c) `hos_repo_root_for` MUST distinguish *key absent* from *value empty* and refuse on both, naming the exact `projects.conf` line to add; (d) **registry population moves into P1 as a prerequisite of S12**, not into S12 itself. A launcher slice that lands before the key exists is a launcher slice that bricks `hos-human`.
3. **Correction B — self-location survives as a bounded fallback, or FR10 breaks.** FR10 requires already-installed, in-clone launchers to keep working *throughout* migration. Bind the resolution order: (i) `--project`; (ii) registry reverse-resolution from `readlink -f "$PWD"` walked to the git toplevel; (iii) **fallback to the legacy `$(dirname "$0")/..` derivation iff `readlink -f "$0"` lies under `<derived-toplevel>/bin/` and the derived toplevel is not the execution root** — i.e. the launcher is demonstrably still an in-clone source copy — and, when it fires, it emits AD-7's shim warning; (iv) otherwise **refuse**, naming the clone, `projects.conf`, and `--project`. The fallback's guard is what preserves TD-VF-038-1's real finding: a launcher sitting at the execution root can never take path (iii), so it can never silently adopt the wrong repo. The fallback is retired when AD-7's shim moves from warn to refuse (P6).
4. **Correction C — the reverse-resolver MUST verify the role, not only the project, and the launcher MUST print what it resolved.** Resolving the project from cwd and then taking `REPO_ROOT` from `<project>_<role>_root` silently changes behaviour: `hos-worker` typed inside the Human clone today runs against the Human clone and after this change runs against the Worker clone. The new behaviour is *better*, and it is still a change a human will observe. Bind: the launcher prints the resolved `(project, role, clone path)` on stderr before starting, and this joins TD-ESC-3's `pm-agent` notification rather than riding along unannounced.
5. **Unchanged:** AD-10 (3)'s removal of `exec claude` (`hos-human:53`, `hos-worker:24`, `hos-overseer:20` — re-measured, all three present) and AD-9's bound startup order.

### 7.3 TD-ESC-4 — RULING: the finding is right, "three entries" is the wrong instrument, and the answer to the question asked is **no — the OS-enforced protection is not removed by this change at all.** (AD-19, AD-20)

The finding is correct and material: `denyWrite: ["__PROJECT_ROOT__/bin"]` is a real, kernel-enforced control that AD-8's removal row does not name, and `docs/SANDBOX-POLICY.md:129-137` states exactly why it exists — `Edit(./bin/**)` blocks the Edit *tool* only, not `sed -i`/`cp`/`tee`/`>` under a sandbox whose `allowWrite` covers the whole project tree.

**AD-19 (BINDING — supersedes AD-8's P6 "Human" row; FR6, FR13).**

1. **The removal set is a predicate, not a count.** Bind: *"every rule in the target artifact whose effect is to deny writes to that clone's `bin/`, enumerated by re-measurement of that artifact at execution time."* Today the union across both artifacts is three shapes and **neither artifact holds all three** (AF-038-11): live profile = 2 advisory `Edit(...)` rules, no `denyWrite`; template = 1 advisory rule + the OS-enforced `denyWrite`. P6 executed against a fixed list of N would remove the wrong things on both. Component Q MUST fail if the measured set differs from the recorded expectation, rather than removing what it finds.
2. **The OS-enforced `denyWrite` in `contract/sandbox-policy.template.json` is NOT removed by this change.** Three reasons, any one sufficient:
   - **Scope.** The live profile is machine-local and un-shipped; the template is **framework-wide** (FR34) and installs on every consumer machine. P5's gate is measured *on the machine that runs it* and can never be evidence about another machine's crontab. A framework-wide removal cannot be gated by a machine-local measurement, so it cannot satisfy AD-8's rule that no protection change precedes a **verified** predecessor.
   - **The removal argument does not apply to it.** AD-8's stated justification is that the rules *"protect a source-only directory and mislead."* That is true of the two advisory `Edit(...)` rules — they claim a control that a Bash-level write walks straight past (`SANDBOX-POLICY.md:131-134`). It is **false** of `denyWrite`, which is not misleading: it is the control it appears to be.
   - **It is load-bearing for AD-4 (see AD-20).** After migration, in-clone `bin/` is not merely source — it is the **source the install copies from** under `--local`. Removing the only OS-enforced write protection on it re-opens agent-write → executed-bytes with one extra step.
3. **P6 splits in two, and only the first half belongs to this change.** **P6a** — the two advisory `Edit(...)` removals from the live `Human/.claude/settings.local.json`, plus narrowing `additionalDirectories`/`allowRead`/`allowWrite` per AD-2 and adding the marker subtree to `allowRead` only. **P6b** — any change to the template's `bin/` posture: **out of scope, routed to #1146** with AD-19 (2) as the architect's position. Note for that chain, not settled here: an OS-enforced `denyWrite` on `<clone>/bin` would also stop the `coder` agent editing `bin/**` in the Worker clone, which is a capability question #1146 must answer, not a reason to drop the rule under this issue.
4. **Yes, the approval requirement changes — and the sharper problem is that no code-review gate exists for P6a at all.** `.claude/settings.local.json` is **gitignored** (`.gitignore:40`), so a P6a edit is a machine-local operator action that reaches no PR, no CODEOWNERS entry, and no reviewer. Bind: (a) P6a is **performed by the human**, never by an agent or a script this change ships; (b) before/after measurements of the file are recorded in the audit trail; (c) Component Q re-runs after and must be green; (d) an AD-4-shaped negative test asserts **no path in `bin/**`, `bootstrap/**`, `scripts/**`, `.github/workflows/**` or `.claude/agents/**` writes any clone's `settings.local.json`** — measured today, a Worker session has no filesystem boundary (TD-VF-038-4) and can write the Human clone's profile, so the prohibition needs a test rather than a convention. P6a is routed to the human at the product-boundary checkpoint (trust boundary + operational obligation) as **ESC-E**.

**AD-20 (BINDING — NEW; extends AD-4 and AD-5; FR2, FR7). The human-install gate covers the install's *invocation*; it does not cover the install's *source*, and under `--local` that is a live path from an agent working-tree write to recognised executed bytes.**

Measured: `hos_install.sh:211-212` sets `HOS_SOURCE="$HOS_REPO_ROOT"` and `:97` `--local` keeps it — the working copy, uncommitted content included. Technical-design's AD-4 gate (§7.3) is `read -r </dev/tty` **plus** an explicit `--confirmed` flag; neither compares the copied bytes against committed state. So: agent writes `<clone>/bin/hos-cron` → a human later runs a `--local` install → the edited bytes land at the execution root → AD-5's record hashes them → AD-6 classifies them **CURRENT**. The install record launders the edit into "recognised," which is precisely the property AD-6 exists to deny. Consumer installs are safe by default (`:211` — a fetched, validated release), but HOS's own three clones are exactly the `--local` case.

Bound:

1. **A `--local` install MUST refuse to copy any file in the AD-1 declared set whose working-tree content differs from its committed content**, naming each divergent file. Overridable only by a second, explicit, per-invocation confirmation that names the divergence — never by a config value or an environment variable (the "no knob may widen what runs" idiom, AD-6).
2. **The install record (AD-5) MUST carry the source mode** — `release:<tag>` vs `local:<commit>` vs `local-dirty:<commit>` — and the currency check MUST report a `local-dirty` provenance in its output, so a laundered install is visible after the fact even if the refusal was overridden.
3. **This is why AD-19 (2) holds.** With `denyWrite` on `<clone>/bin` in force, step one of that chain does not happen at all. AD-20 is defence in depth for the case where it is not in force — which is every clone today, since no live profile carries `denyWrite`.

### 7.4 New escalations these rulings raise

- **ESC-D — `pm-agent`: FR27's acceptance criterion is unsatisfiable for the file FR27 names.** FR27 requires the generated `.claude/settings.json` to *"grant read access to the marker location"* (FR26). Measured, that grant is expressible only in `.claude/settings.local.json`'s `sandbox.filesystem.allowRead`. Requested restatement: *the per-role sandbox posture — whichever file carries it — grants read of the marker location; `.claude/settings.json`'s generation and untracking is a separate obligation of the same install step.* The FR26/FR27 **intent** survives intact; only the file identity in the acceptance test is wrong. Parallel in kind to ESC-B and ESC-C.
- **ESC-E — human: P6a's approval route.** Per §7.3 (4), the Human-profile protection removals reach no review gate because the file is gitignored. My ruling is that they are human-performed, measured before and after, and recorded. Confirm, or specify a different gate. This is a trust-boundary and operational-obligation item, so it is routed rather than bound.
- **Note to #1146, not an escalation:** AD-19 (2) is the architect's position that the template's `denyWrite` stays; the Worker-clone capability question it raises (§7.3 (3)) is that chain's to answer.

### 7.5 Startup-gap discipline and affected sign-offs for this addendum

*Should any of this have been settled in the initial architecture review?*

- **AD-17 — yes, partly. `startup-artifact-gap`.** AD-14 asserted "add a template" without measuring whether one existed. `contract/sandbox-policy.template.json` predates ADR-038 by one day (mtime 2026-08-05 04:44) and `docs/SANDBOX-POLICY.md` states its ownership plainly. I re-measured nine other things and not this one. Recorded, not absorbed.
- **AD-18 — yes. `startup-artifact-gap`.** AF-038-2 generalised a measurement of one launcher to all launchers. The command that would have caught it (`grep -n 'REPO_ROOT=' bin/hos-*`) is the same command I ran for `hos-cron`, with a wider glob.
- **AD-20 — yes, and it is the one that matters most.** AD-4 bound the install's *invocation* and never asked what the install *copies from*. FR2's property ("a merge changes nothing until a human installs") is stated about merges; the gap is that a non-merge — an uncommitted working-tree edit — reaches the execution root through the install. That is an architecture-review-class question about the trust anchor and it should have been asked in §2.
- **Affected sign-offs: none orphaned, all prior sign-offs stand.** No code exists for any AD-038 decision; no execution root, install record, syncer, registry, marker or generator has been built. The only downstream artifact is TECHNICAL-DESIGN-038, which is itself unapproved and carries these escalations open. AD-17 … AD-20 revise decisions for paths **never built**, so no approved design or code is left unaudited against a changed contract. Nothing requires re-review. `technical-design` must absorb AD-17 … AD-20 into Components D, E, F, I, L and R before it can be approved.

### 7.6 Effect on technical-design's build order

| Slice | Effect of these rulings |
|---|---|
| **S3** (resolver) | Add `<project>_human_root` writing to both `projects.conf` writers + the migration note (AD-18 (2)); add the bounded self-location fallback and its guard (AD-18 (3)) |
| **S4/S5** (copy, record) | Add AD-20's dirty-source refusal and the `release`/`local`/`local-dirty` provenance field |
| **S8** (settings) | Unblocked by AD-17. Class A authored here; Class B additively extended by one `allowRead` entry only; the four required-content assertions are the control, not a test; Class B enablement defaults to Human only |
| **S12** (launchers) | Unblocked by AD-18, **but S12 now depends on the S3 registry work**, and the resolved-`(project, role, clone)` print line joins TD-ESC-3 |
| **S17** (P6) | **Splits.** S17a = the live Human profile only, human-performed, measured before/after, plus the negative test of AD-19 (4d). S17b = the template's `bin/` posture — **removed from this change's scope**, routed to #1146 |

**This addendum does not clear anything to build.** §5's conditions stand: ESC-A and Q1–Q6 are the human's, ESC-B and ESC-C are `pm-agent`'s, and ESC-D and ESC-E are now added to that list.

---

## Human Review Required

**RISK: MEDIUM–HIGH, and the direction matters.** The design *reduces* standing risk — it closes a path from an agent working-tree write to unsandboxed execution that is measurably open right now in two of three HOS roles and in at least one consumer project. Residual risk is concentrated in four places. **(1) AD-6/FR8:** a currency check that self-heals from repo source would rebuild the exact escalation path this design removes, and it is the convenient thing to implement; it is prohibited three times and made structurally checkable. **(2) AD-2:** if the Worker/Overseer sandbox does not follow, the relocation is hygiene, not a boundary — and the greatest danger is that the change *reads* as a security fix and is documented as one. The residual statement is a required deliverable for that reason. **(3) AD-8/FR13:** removing the Human clone's `bin/` deny rules before the P5 verification gate opens the path for real. **(4) AD-1/ESC-A:** shipping "all of `bin/`" satisfies every stated acceptance test while leaving the token minter and the cron prompt file executing from an agent-writable clone.

**CONFIDENCE: HIGH** on the findings I re-measured this session with the commands recorded inline: `bin/hos-cron`'s clone-resident invocations and its `REPO_ROOT`-from-`projects.conf` resolution; the three interactive launchers' `exec claude`; the per-clone `settings.local.json` state and the `additionalDirectories` grant shape; `hos_repo_sync.sh`'s pull-failure state write, its `/tmp` state default, and its `--porcelain` cleanliness gate; `hos_install.sh`'s `_sha256` + `.hos-manifest` schema-v2 rows, its settings-merge block, its ship-set loop and crontab emissions; `protected_surfaces.txt`; `test_consumer_framework_files.py`'s assertion set; and the live crontab. **HIGH** on AD-1, AD-2, AD-5, AD-6, AD-10, AD-11, AD-12, AD-13. **LOWER** on: whether `permissions.additionalDirectories` (or its successor key) can express read-only in the current CLI — AD-13 is designed to be correct either way but the mechanism's strength depends on it; whether the CLI tolerates unknown top-level settings keys (AD-14 explicitly refuses to assume); the exact agent-session environment markers (AD-15 requires empirical verification rather than naming them); and whether a `git fetch` is provably inert with respect to a concurrent session (AD-10 (5) requires that confirmation or a configuration escape).

**BLAST RADIUS:** what cron executes as the user, unsandboxed, on every HOS machine and every consumer machine running the pipeline; the sandbox posture of all three roles; the installer's ship-set, its generated artifacts, and its emitted setup instructions; the session-start path of all four launchers; and the crontabs of every existing installation, which operators must migrate by hand. A migration executed out of order (AD-8) affects running production installations, not only new ones.

**Change classification: STRUCTURAL.** It changes the trust boundary around what cron executes, adds a new installer obligation (copy-on-install, an install record, per-role settings generation), a new runtime component (an out-of-band syncer with a journalled state machine), a new lock contract for interactive sessions, a new cron entry, and a new user obligation (crontab migration). The four bound premises P1–P5 carry the human's sign-off and are not re-opened. Q1–Q6 are **not bound here** and each has a named seam. **ESC-A, ESC-B, and ESC-C are new and are mine to raise, not to settle.**
