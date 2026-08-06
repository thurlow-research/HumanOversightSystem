# TECHNICAL DESIGN — ADR-038 the execution-copy boundary, the currency anchor, and the journalled fast-forward syncer

**Status:** DRAFT 1 — awaiting `architect` review, and **not cleared to build**, for two independent
reasons. (1) ADR-038 is itself *"ACCEPTED FOR DESIGN — not cleared to build"*: its §5 requires the human to
rule **ESC-A** (closure scope) and **Q1–Q6**, and `pm-agent` to restate **ESC-B** and **ESC-C**, before a
`coder` is cleared. None of that has happened; this document does not change it and binds none of it.
(2) This document raises **four new escalations of its own** (§15.1) — one of them HIGH — that route back to
`architect` and `pm-agent`. **A human must rule Q1–Q6 and ESC-A/B/C, and the architect must resolve
TD-ESC-1…4, before implementation may begin.** Like the ADR, this is a design artifact; it contains no
application code.
**Date:** 2026-08-06
**Author:** technical-design
**Consumes:** `docs/v0.6.0/REQUIREMENTS-038-human-clone-sync.md` (P1–P5, FR1–FR36, VF-038-1…9, §4 Q1–Q6);
`docs/v0.6.0/ADR-038-human-clone-sync.md` (AD-1…AD-16, AF-038-1…9, §3.1 seams, §3.2 ESC-A/B/C, §3.4
follow-ups). Both are read as binding; nothing in either is re-litigated here.
**Consumer:** a `needs-ai` issue carrying §14's build order — **only after** the clearances above.
**Method note (this repo's standing rule, REQUIREMENTS-038 §0):** *a design document that asserts current
configuration state must carry the command that produced the assertion.* Every state claim below was
re-measured in this session (2026-08-06) against the working tree at
`/home/scott/Code/HumanOversightSystem/Worker`, with the command recorded inline. Nothing is inherited from
the thread, from REQUIREMENTS-038, or from the ADR without re-running it.
**Protected surfaces the implementation touches:** `bin/**`, `bootstrap/**`, `scripts/framework/**`,
`contract/**`, `.claude/agents/**` (only if a launcher contract is documented there). Per ADR-038 §5 the
implementation PR is human-approved at merge regardless of computed tier.

---

## 0. Verification findings — every load-bearing premise re-measured

The ADR's AF-038-1 … AF-038-9 and pm-agent's VF-038-1 … VF-038-9 **all re-verify as stated** where I re-ran
them (recorded per finding below). The findings numbered `TD-VF-038-n` are mine; they do not collide with
either upstream set. **TD-VF-038-1, -2, -3 and -5 change this design**; the rest constrain or simplify it.

### TD-VF-038-1 — HIGH, and it adds a component AD-3 does not have: the three interactive launchers resolve `REPO_ROOT` from **their own location**, so relocating them does not merely move them — it breaks them.

AF-038-2 established that `bin/hos-cron` resolves `REPO_ROOT` from `~/.config/hos/projects.conf`
(`hos-cron:111`, `_conf_val ${ROLE}_root`) and concluded *"relocating the launcher is path-safe (good)."*
**That conclusion is true of `hos-cron` and `hos-suspend` only.** Measured:

| Launcher | Line | How it finds the repo | Relocatable as-is? |
|---|---|---|---|
| `bin/hos-cron` | 111 | `_conf_val ${ROLE}_root` from `~/.config/hos/projects.conf` | **yes** |
| `bin/hos-suspend` | 20 | `PROJECTS_CONF="${HOME}/.config/hos/projects.conf"` | **yes** (no `REPO_ROOT` at all) |
| `bin/hos-trim-logs` | — | no repo reference; globs `/tmp/hos-*.log` | **yes** (trivially) |
| `bin/hos-human` | **22** | `REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"` | **NO** |
| `bin/hos-worker` | **10** | identical expression | **NO** |
| `bin/hos-overseer` | **8** | identical expression | **NO** |

Copied to an execution root outside every clone, `$(dirname "$0")/..` resolves to the execution root's
parent — the state root — which is not a git working tree, so `git rev-parse --show-toplevel` fails and
`set -euo pipefail` aborts the launcher at line 8/10/22. If the execution root ever *were* placed under a
git tree, the failure is worse than an abort: the launcher silently adopts **the wrong repo** as
`REPO_ROOT` and then preflights, authenticates and syncs against it.

**Consequence — three additions to the design.** (a) The three interactive launchers must become
**registry-driven**, resolving `REPO_ROOT` the way `hos-cron` does. (b) They currently take **no**
`--project` argument (`grep -n '\-\-project' bin/hos-human bin/hos-worker bin/hos-overseer` → no matches),
so AD-3's resolver needs a **companion reverse-resolver**: clone path → project key, read from the same
`projects.conf`, with an explicit `--project` override for the ambiguous case. (c) This is user-visible
(a human who types `hos-human` from an arbitrary directory gets different behaviour) and joins AD-10 (3)'s
`exec` removal as a `pm-agent` notification (TD-ESC-3). Components **D** and **L** exist because of this
finding.
*Commands:* `grep -n 'REPO_ROOT=\|^exec claude' bin/hos-human bin/hos-worker bin/hos-overseer`;
`grep -nE 'REPO_ROOT|dirname|projects.conf|_conf_val' bin/hos-trim-logs bin/hos-suspend bin/lib/git-credentials.sh`;
`sed -n '95,135p' bin/hos-cron`

### TD-VF-038-2 — HIGH: AD-14's "add a template" is largely already built, by other work, in a different file than FR27 names. `contract/sandbox-policy.template.json` exists, is already a protected surface, and is owned by #1146.

AD-14 specifies a three-part change — *untrack `.claude/settings.json`; add a **template**; generate per
role at install* — as if the template were new. Measured: **the template exists.**

- `contract/sandbox-policy.template.json`, 6,683 bytes, mtime **2026-08-05 04:44** (one day before ADR-038
  was authored). Top-level keys: `model`, `hooks`, `permissions`, `sandbox`. It is path-templated with
  `__HOS_ROOT__`, `__PROJECT_ROOT__`, `__CONFIG_DIR__`, `__HANDOFF_DIR__`, `__HOME__`, `__ROLE__`,
  `__CLAUDE_PROJECT_STATE__`.
- It is **already protected**: `contract/**` is line 17 of `scripts/framework/protected_surfaces.txt`. So
  FR28/AD-14's *"add its path to `protected_surfaces.txt` and regenerate CODEOWNERS"* is **already
  satisfied** if the template stays where it is — a simplification, not a gap.
- It is **not wired to anything**: `grep -rn "sandbox-policy.template.json" bootstrap/ scripts/` returns
  **zero** hits. `docs/SANDBOX-POLICY.md:11-13` states this in terms: *"It is not yet installed by
  `hos_install.sh`, and it is not yet applied to `worker` or `overseer`. Both of those are v0.7.0 work,
  tracked at **#1146**."*

**But it templates a different file than FR27 names, and that distinction is load-bearing.** FR27/P4 is
about `.claude/settings.json` — tracked (`git ls-files --error-unmatch .claude/settings.json` → present),
carrying `permissions.allow` (9 entries) and the `hooks.SubagentStop` → `python3
scripts/oversight/record_agent_model.py` block. The *sandbox posture* — the `permissions.deny` list,
`permissions.additionalDirectories`, and the `sandbox.filesystem.{allowRead,allowWrite,denyRead,denyWrite}`
lists that AD-2's negative rule and AD-13's marker grant are expressed in — lives in
`.claude/settings.local.json`, which is **gitignored** (`.gitignore:40`) and is what
`sandbox-policy.template.json` templates. **FR26's "grant read access to the marker location" and AD-2's
"MUST NOT appear in any role's `additionalDirectories`" are therefore not expressible in the file FR27
names.** Two payload classes, two files, one ADR decision that does not separate them → **TD-ESC-1**
(architect), and Component **I** is specified in §8 as two classes accordingly.
*Commands:* `ls -la contract/`; `python3 -c "import json;d=json.load(open('contract/sandbox-policy.template.json'));print(list(d.keys()))"`;
`grep -n "contract/" scripts/framework/protected_surfaces.txt`; `grep -rn "sandbox-policy.template.json" bootstrap/ scripts/`;
`git ls-files --error-unmatch .claude/settings.json`; `grep -n "settings.local" .gitignore`; `sed -n '1,15p' docs/SANDBOX-POLICY.md`

### TD-VF-038-3 — resolves the ADR's own stated LOWER-confidence item: **read-only is expressible, kernel-enforced, and already in use.** `sandbox.filesystem` has separate `allowRead` / `allowWrite` / `denyRead` / `denyWrite` lists.

ADR-038's confidence statement flags *"whether `permissions.additionalDirectories` (or its successor key)
can express read-only in the current CLI — AD-13 is designed to be correct either way but the mechanism's
strength depends on it."* Measured on the live Human profile and on the checked-in template: it can, and
`additionalDirectories` is not the mechanism to use.

`Human/.claude/settings.local.json` (mtime 2026-08-05 23:31) carries **both**
`permissions.additionalDirectories` (6 entries — a *working* directory grant, read **and** write, exactly as
AF-038-5 says) **and** a top-level `sandbox` block whose `filesystem` key holds four **separate** lists.
`docs/SANDBOX-POLICY.md:129-140` states the semantics and the confirmation: *"`denyWrite` is enforced by the
OS-level sandbox itself, so it applies regardless of which tool or command performs the write … `denyWrite`
is a supported sibling of `denyRead`/`allowRead`/`allowWrite` in the filesystem sandbox schema — confirmed
present in the Claude Code binary."*

**Consequence — AD-13 gets stronger than it was designed to be.** The marker subtree is granted via
`sandbox.filesystem.allowRead` **and deliberately omitted from `allowWrite` and from
`additionalDirectories`**. That is a *kernel-enforced* read-only grant, not the "grant + an advisory deny"
compromise AD-13 settles for. AD-13's residual (*"the marker is a backstop signal, never a control"*)
still stands and is still written into the deliverable — the marker's worst case is unchanged in kind —
but the mechanism is materially better than the ADR assumed, and §9.4 binds the stronger form.
*Commands:* `python3 -c "…json.load(...Human/.claude/settings.local.json)…permissions.keys(), sandbox['filesystem']"`;
`sed -n '120,141p' docs/SANDBOX-POLICY.md`

### TD-VF-038-4 — CONFIRMED and sharpened by direct probe: for Worker there is no filesystem boundary of any kind, and the boundary is absent **at the exact candidate location for the execution root**.

VF-038-6 probed `Worker/bin/`. I probed the thing AD-2's property actually depends on — a path outside
every clone, under `$HOME`, which is where AD-3's recommended execution root lives. From inside this
sandboxed autonomous Worker session:

- `touch /home/scott/.hos-td038-writeprobe` → **succeeded** (file created, 0 bytes, then removed).
- Cross-clone reads succeed: I read `/home/scott/Code/HumanOversightSystem/Human/.claude/settings.local.json`
  and `/home/scott/.claude/settings.json` from the Worker session.
- `Worker/.claude/settings.local.json` and `Overseer/.claude/settings.local.json` **do not exist**; there is
  no `/etc/claude-code/managed-settings.json`; `/home/scott/.claude/settings.json` contains only `model`,
  `tui`, `skipDangerousModePermissionPrompt`, `agentPushNotifEnabled` — **no `sandbox` key, no
  `permissions` key**.

**Consequence:** AD-2 is not merely correct, it is *demonstrated at the destination*. Until #1146/#1183
land a posture for Worker and Overseer, a relocated execution root under `$HOME` is writable by those
sessions and the relocation is hygiene, not a boundary. AD-2 requires that sentence in the implementation's
own documentation; §12.3 makes it a named deliverable with this measurement attached.
*Commands:* `touch /home/scott/.hos-td038-writeprobe && ls -la … && rm -f …`;
`ls -la /home/scott/.claude/settings.json /etc/claude-code/managed-settings.json`;
`python3 -c "…for c in ['Human','Worker','Overseer']: os.path.exists(...settings.local.json)"`

### TD-VF-038-5 — the state root exists, is mode **0775**, and holds live credentials in its root. The install must harden it, and AD-13's credential invariant has a concrete move.

`$HOS_STATE_DIR` defaults to `$HOME/.hos` (`bin/hos-cron:123`) and `hos-cron:131` creates
`wakeup/ last-run/ locks/ validation-cache/ suspend/ test-clean/` under it. Measured: `/home/scott/.hos` is
`drwxrwxr-x` — **group-writable** — and contains those six plus `setup-validation/`. `hos-cron:484` does
`_auth_tmp=$(mktemp -p "$_HOS_DIR")` for the **installation token**, i.e. a live credential lands in the
state root's own directory, which is exactly what AD-13 (ii) asks be made structural.

**Consequence:** (a) the install creates every new subtree with mode `0700` and **hardens `$HOS_STATE_DIR`
itself to `0700`**, refusing to proceed if it cannot (a group-writable state root makes every boundary below
it advisory); (b) the `hos-cron:484` mktemp moves to a dedicated, never-granted `auth/` subtree — folded
into this design at P3 rather than deferred, per AD-13 (ii)'s *"SHOULD move that mktemp"*, and also filed
(§15.2 ISSUE-2) so it is not lost if the P3 slice is descoped.
*Commands:* `ls -la /home/scott/.hos/`; `grep -nE '_HOS_DIR|mktemp' bin/hos-cron`

### TD-VF-038-6 — CONFIRMED: the ship-set is exactly three `bin/` entries, `hos-human` is copied by a second code path, and the installer's own comment is wrong.

`grep -n "^bin/" scripts/framework/framework_consumer_files.txt` returns exactly `bin/hos-cron`,
`bin/hos-trim-logs`, `bin/lib/git-credentials.sh` (lines 20–22 of a 69-line file). `bin/hos-human` is copied
by a separate block at `hos_install.sh:2013-2027` (`cp "$_human_launcher" "$TARGET_REPO/bin/hos-human"`).
`hos_install.sh:1822` still reads *"Covers: all of bin/ (incl. bin/lib/)"*. `bin/hos-worker`,
`bin/hos-overseer` and `bin/hos-suspend` reach consumers by neither path. VF-038-1 holds verbatim.
*Commands:* `grep -n "^bin/" scripts/framework/framework_consumer_files.txt`; `sed -n '1815,1840p' bootstrap/hos_install.sh`;
`sed -n '2010,2030p' bootstrap/hos_install.sh`; `ls -la bin/ bin/lib/`

### TD-VF-038-7 — CONFIRMED: the installer's human-confirmation idiom is `read -r … </dev/tty`, which is exactly the primitive AD-4 needs, and it is already used twice.

AD-4 requires the copy step be reachable only from an interactive/human-confirmed invocation. The installer
already has the idiom: `hos_install.sh:963` (`read -r _scaffold_ans </dev/tty`) and `:2240` (`read -r
_stale_ans </dev/tty`). A read from `/dev/tty` fails in a cron/`claude --print` context rather than
defaulting — which is the fail-closed direction. `bootstrap/submit_pr.sh` supplies the second half of the
pattern: an explicit `--confirmed` flag that *asserts* human authorization (`submit_pr.sh:105`). §7.3 binds
both together (tty-present **and** explicit flag), so neither an inherited tty nor a stray flag alone
opens the path.
*Commands:* `grep -n "read -r\|/dev/tty" bootstrap/hos_install.sh | head`; `grep -n "confirmed" bootstrap/submit_pr.sh`

### TD-VF-038-8 — CONFIRMED: the install record's pattern exists at `hos_install.sh:290` (`_sha256`) and `:2150` (`path\tWHOLE\t<sha256>` rows under a `# hos-manifest-schema: 2` header, `:2186`). AD-5 is an extension of exercised machinery, not new machinery. `.hos-manifest` lives in the target repo and stays there.
*Command:* `grep -n "_sha256\|hos-manifest" bootstrap/hos_install.sh | head -40`

### TD-VF-038-9 — CONFIRMED: `hos_repo_sync.sh` state defaults to `/tmp/hos-repo-sync` (`:33`), which the Human profile grants (`/tmp` is in `additionalDirectories` **and** in `sandbox.filesystem.allowWrite`); it writes `last_sync_epoch` unconditionally at `:180-186` including on the pull-failure path; it gates on `git status --porcelain` at `:137` (untracked-sensitive); it uses `pull --ff-only` at `:138`; and it reads its own state back with `grep -o` on JSON at `:60`. All four defects the ADR names are present. The `mktemp`+`mv` atomic-write precedent at `:180-186` is sound and is reused (with an added `fsync`).
*Command:* `cat bootstrap/hos_repo_sync.sh`

### TD-VF-038-10 — the agent-session environment markers AD-15 requires be verified empirically, measured in this session.

AD-15 refuses to name them and requires `technical-design` to verify. Measured inside this
`claude --print` autonomous Worker cycle: **`CLAUDECODE`**, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_EXECPATH`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_PID`. Also present:
`HOS_CYCLE_ID`, `HOS_CYCLE_ROLE`, `HOS_CYCLE_TOKEN` — **confirming AD-15's warning**: keying the refusal on
`HOS_CYCLE_ID` would make the syncer refuse itself when invoked from `hos-cron` after minting
(`hos-cron:220-236`). §11 binds the marker list, its precedence, and the re-verification obligation.
*Command:* `env | grep -iE '^claude|^CLAUDE|^HOS_' | sed 's/=.*/=<redacted>/'`

### TD-VF-038-11 — live crontab and `.envrc`, re-measured for AD-7 and AD-8.

Crontab: five in-clone launcher entries across **two** projects (`HumanOversightSystem/{Worker,Overseer}/bin/hos-cron`,
`CondoParkShare/{Worker,Overseer}/bin/hos-cron`, `HumanOversightSystem/Worker/bin/hos-trim-logs`) plus
`/home/scott/.config/hos/worker-unstick.sh` — an out-of-clone script already on a timer. `.envrc` is
**tracked** (`git ls-files --error-unmatch .envrc` → present), does `PATH_add bin` (line 8), and *also*
derives `HOS_CONFIG_DIR` from its own location (line 13) — so AD-7's `.envrc` change must repoint `PATH`
without disturbing the `HOS_CONFIG_DIR` export, which is a clone-relative value and correctly stays so.
Ten files under `docs/` reproduce a launcher path and are in AD-7's scope.
*Commands:* `crontab -l | grep -i hos`; `cat .envrc`; `git ls-files --error-unmatch .envrc`;
`grep -rln "bin/hos-" docs/ *.md`

---

## 1. Terminology (binding — use these terms; no coined substitutes)

| Term | Meaning in this design |
|---|---|
| **State root** | `$HOS_STATE_DIR`, default `$HOME/.hos` (`bin/hos-cron:123`). The existing machine-local, out-of-every-clone, env-overridable root. Parent of everything below. |
| **Execution root** | The per-project subtree of the state root holding the copied executed set. **The thing cron and launchers execute.** Written only by a human-run install (AD-4). Never granted to any session. |
| **Executed set** | The AD-1 *closure*: every file an out-of-band launcher executes, sources, or interprets as instruction **outside** an agent session — transitively. Not a directory. |
| **Declaration** | `scripts/framework/executed_set.txt` — the single file naming the executed set. Read by the copy step, the install record, and the currency check. |
| **Residual register** | `scripts/framework/executed_set_residual.txt` — the *registered, reasoned, tested* accepted in-clone references (AD-1 rule 2c). A silent partial closure is prohibited; this file is the honest form. |
| **Install record** | The out-of-clone, content-addressed record of what the install placed at the execution root and what it generated in-clone. **The integrity trust anchor** (AD-5/AD-6). Never granted. |
| **Currency check** | The run-time, execution-site verifier. Two anchors: integrity vs. the install record; currency vs. the *committed* clone source. **Never writes to the execution root** (FR8). |
| **Syncer** | The single component performing every fast-forward on a clone (AD-9). Runs from the execution root, from cron and from launcher startup. |
| **Session registry** | Multi-holder, clone-keyed record of live sessions (AD-10). Distinct from `hos-cron`'s exclusive overlap mutex, which is unchanged. Never granted. |
| **Journal** | Short-lived, durable *intent* written before the one tree-modifying step (AD-11). Never read by a session. Never granted. |
| **Marker** | Durable *outcome* plus counters and clocks, one atomic replace (AD-13). **The only granted subtree**, and granted **read-only**. |
| **Outbox** | The durable escalation record: write → attempt delivery → mark delivered (AD-16). Lives in the marker subtree so a session can surface it. |
| **Granted** | Present in a role's generated sandbox posture. Read-granted = `sandbox.filesystem.allowRead`. Write-granted = `allowWrite` and/or `permissions.additionalDirectories`. |

**The organizing rule (ADR-038 §1 — quote it wherever the boundary is documented):**

> The install is the only writer of everything the machine executes out-of-band; every runtime component is
> a reader of it.

**The residual sentence (AD-2 — required deliverable, must appear in the implementation's own docs, §12.3):**

> After migration, the Worker and Overseer clones' `bin/` remains agent-writable, and — until #1146/#1183
> land a sandbox for those roles — so does any execution root on the same machine. For those two roles this
> change is sequencing and hygiene; the boundary becomes real only when their sandbox does.

---

## 2. The state-root layout (one figure; every component below refers to it)

Existing entries are marked; everything else is new. Grant column is the **binding** input to §8's generated
posture: `R` = read-granted, `—` = granted to no role, ever (AD-2's negative rule).

```
$HOS_STATE_DIR/                          (default $HOME/.hos; mode 0700 — hardened at install, TD-VF-038-5)
├── locks/            EXISTING  —   hos-cron overlap mutex; UNCHANGED (hos-cron:180)
├── wakeup/           EXISTING  —   UNCHANGED
├── last-run/         EXISTING  —   UNCHANGED
├── suspend/          EXISTING  —   UNCHANGED
├── validation-cache/ EXISTING  —   UNCHANGED
├── test-clean/       EXISTING  —   UNCHANGED
├── setup-validation/ EXISTING  —   UNCHANGED
├── auth/             NEW       —   hos-cron:484's token mktemp moves here (AD-13 ii, TD-VF-038-5)
├── exec/<project>/   NEW       —   THE EXECUTION ROOT. Mirrors declared repo-relative paths.
│     ├── bin/…                       (whatever executed_set.txt declares — a path list, not a directory)
│     └── bootstrap/…
├── installs/<project>/ NEW     —   THE INSTALL RECORD (AD-5). Integrity anchor. Never granted.
│     ├── record.tsv
│     ├── record.meta.tsv
│     └── INSTALL-IN-PROGRESS          (sentinel; present only during an install)
├── sessions/<clone>/ NEW       —   SESSION REGISTRY (AD-10). Multi-holder. Never granted.
│     └── <pid>-<launcher>.json
├── sync/<clone>/     NEW       —   JOURNAL + failure clocks (AD-11/AD-12). Never granted.
│     ├── journal.json                 (present only while a sync is non-terminal)
│     └── attempt.json
└── marker/<clone>/   NEW       R   THE ONLY GRANTED SUBTREE — read-only (TD-VF-038-3)
      ├── sync.json                    (the marker: outcome + counters + clocks)
      └── outbox/<id>.json             (escalation outbox, AD-16)
```

**`<project>`** is the `projects.conf` project key (`--project` for `hos-cron`; resolved by §6.2's
reverse-resolver for the interactive launchers). **`<clone>`** is a clone key: the `hos-cron:303-307` hash
idiom (`md5sum` → `md5` → `cksum` fallback) of the clone's absolute path, **suffixed with the clone's
basename** for human legibility, and every record inside carries the **plaintext clone path** so a hash
collision is detectable rather than silent.

**Bound invariants over this figure:**
1. `exec/`, `installs/`, `sessions/`, `sync/`, `auth/`, and the state root itself appear in **no** role's
   `additionalDirectories`, `allowRead`, or `allowWrite`. (AD-2. Tested — §14 T-P2-3.)
2. `marker/` appears in `allowRead` **only**. Never `allowWrite`, never `additionalDirectories`
   (which grants both — AF-038-5, re-measured TD-VF-038-3).
3. `marker/` contains no credential material and nothing integrity-bearing. (AD-13 (ii)/(iii).)
4. All new subtrees are created mode `0700`; the install hardens `$HOS_STATE_DIR` to `0700` and **refuses
   to proceed** if it cannot (TD-VF-038-5).

---

## 3. Component map, in AD-8 phase order

AD-8's P0→P6 ordering is **strict and preserved** in this table, in §§5–13's section order, and in §14's
build order. No component may be built before every component of its predecessor phase is *verified by
measurement*, not merely merged.

| # | Artifact | Kind | Phase | Binds | Protected? |
|---|---|---|---|---|---|
| **A** | `scripts/framework/executed_set.txt` | NEW declaration | **P0** | AD-1 (1) | yes (`scripts/framework/**`) |
| **B** | `scripts/framework/executed_set_residual.txt` | NEW register | **P0** | AD-1 (2c) | yes |
| **C** | `tests/framework/test_executed_set.py` — both-direction + closure guards | NEW tests | **P0** | AD-1 (2), FR4 | no |
| **C2** | `bootstrap/hos_install.sh` — retire the `bin/hos-human` second copy path; ship-set reads A | EDIT | **P0** | AD-1 (1), VF-038-1 | yes (`bootstrap/**`) |
| **D** | `bootstrap/lib/hos_paths.sh` — **the** execution-root resolver + clone→project reverse-resolver + clone key | NEW lib | **P1** | AD-3, TD-VF-038-1 | yes |
| **E** | `bootstrap/hos_install.sh` — `_install_execution_root()` copy step behind the human gate | EDIT | **P1** | AD-1 (3), AD-4 | yes |
| **F** | `bootstrap/hos_install.sh` — `_write_install_record()` + torn-install sentinel | EDIT | **P1** | AD-5 | yes |
| **G** | `tests/framework/test_exec_root_install.py` — copy wholeness, perms, record shape, **no automated copy path** | NEW tests | **P1** | AD-4, AD-5 | no |
| **H** | `bootstrap/hos_verify_exec_copy.sh` — the currency check (self-verifies first) | NEW | **P2** | AD-6 | yes |
| **I** | `scripts/framework/gen_role_settings.py` + `contract/sandbox-policy.template.json` (**existing**) + a new `contract/role-settings.template.json` | NEW generator + EXISTING template + NEW template | **P2** | AD-14, AD-2, TD-VF-038-2 | yes (`contract/**`, `scripts/framework/**`) |
| **J** | `bootstrap/lib/hos_marker.sh` — marker + outbox read/write (atomic, fsync) | NEW lib | **P3** | AD-13, AD-16 | yes |
| **K** | `bin/lib/hos_session_registry.sh` — register / release / reclaim / query | NEW lib | **P3** | AD-10 | yes (`bin/**`) |
| **L** | `bin/hos-human`, `bin/hos-worker`, `bin/hos-overseer` — registry-driven `REPO_ROOT`, no `exec`, register, sync-before-lock | EDIT | **P3** | AD-9, AD-10 (3), TD-VF-038-1 | yes |
| **M** | `bootstrap/hos_sync_clone.sh` — the syncer + state machine + clocks + agent-env guard | NEW | **P3** | AD-9, AD-11, AD-12, AD-15 | yes |
| **M2** | `bin/hos-cron` — register in the session registry; move `:484` token mktemp to `auth/` | EDIT | **P3** | AD-10 (1), AD-13 (ii) | yes |
| **N** | `bin/lib/hos_selfloc.sh` — self-location shim (warn mode) | NEW lib | **P4** | AD-7 | yes |
| **O** | `hos_install.sh:2450-2458` + `hos_setup_partner.sh:215-220` crontab emitters + the ten `docs/` files | EDIT | **P4** | AD-7, AD-15 (FR31) | yes / no |
| **P** | `.envrc` — repoint `PATH_add` at the execution root | EDIT | **P4** | AD-7 (FR14) | no (tracked) |
| **Q** | `scripts/framework/verify_exec_migration.sh` — the P5 gate, measured | NEW | **P5** | AD-8 | yes |
| **R** | Per-clone protection changes (§13 table) | CONFIG/ADMIN | **P6** | AD-8, FR13 | n/a |

**Explicitly NOT built:** no self-heal, repair, patch, copy, or permission-fix in the currency path (FR8,
prohibited three times — §7.4); no crontab writer (VF-038-2 — detect-and-report only); no "sync anyway
after N skips" escape hatch (AD-10 (6)); no second derivation of the execution root anywhere (AD-3); no
second copy path for any launcher (AD-1 (1)); no cache of the currency result (AD-6 — a cache is a second
trust anchor); no retry loop against a quarantined clone (AD-11 (7)).

---

## 4. Held-decision seam register (Q1–Q6) — build the seam, bind nothing

Per ADR-038 §3.1 every held ruling must change **a configured value or one function body**, never a shape.
This is the complete, exhaustive list of what the implementation must expose, with the exact artifact. **No
default below is a design choice; each is either the ADR's own stated recommendation carried forward, or a
placeholder explicitly marked HELD.**

| Q | Seam artifact | Exact form | What a ruling changes | Shipped value |
|---|---|---|---|---|
| **Q1** | none in code | AD-8's per-clone table (§13) has a row; AD-2's residual sentence is written either way | Whether an interim posture lands before P1. Zero mechanism change. | n/a — sequencing only |
| **Q2** | `config.sh` key `HOS_SYNC_INTERVAL_SECONDS` + env override `HOS_SYNC_INTERVAL_SECONDS` + floor constant `HOS_SYNC_INTERVAL_FLOOR` | Effective = `max(floor, config-or-env)`. Clamp narrows only; no input may go below the floor. | Two numbers + their documentation at the config site. Acceptance: changing cadence requires **no** mechanism edit. | **HELD** — ship with the key present and unset; unset ⇒ refuse to run with a named "cadence not configured" escalation rather than a silent guess |
| **Q3** | `config.sh` key `HOS_EXEC_STALE_POLICY` ∈ {`warn`, `halt`} consumed by **one** function, `_stale_response()` in Component H | The check always *emits* the classification; only `_stale_response()` selects run-vs-refuse. `UNRECOGNISED` is **not** routed through it and is **not** configurable. | One configured default. | **HELD** — key present; if unset the launcher emits the loud report and **proceeds** (the ADR's stated recommendation), and additionally records a "stale policy unset" note in the outbox so the unset state is visible rather than assumed |
| **Q4** | `hos_exec_root()` in Component D — **one function body, one call site** | Signature fixed (§6.1); body is the only place a path is composed | One function body. Every consumer (installer, four launchers, checker, shim, `.envrc`, two emitters, docs generator) follows with no edit. | **HELD** — body ships implementing pm-agent's §4-Q4 recommendation (`$HOS_STATE_DIR/exec/<project>`) **marked in-file as the unbound default**; ADR §5 (2) says Q4 **cannot** ship deferred, so P1 does not start until it is ruled |
| **Q5** | `_maybe_gitignore_exec_root()` — one conditional, called at exactly one install site, **empty body** | Invoked only when `hos_exec_root()` returns a path inside a git working tree | One conditional's behaviour. | **HELD** — moot under the Q4 recommendation; the hook exists so it is not a structural change if Q4 goes the other way |
| **Q6** | `config.sh` keys `HOS_SYNC_SKIP_ESCALATE_AT`, `HOS_SYNC_FAIL_ESCALATE_AT`; channel selector `HOS_ESCALATION_CHANNEL` ∈ {`issue`, `session`, `both`} consumed by **one** function, `_deliver_escalation()` in Component J | Two integers, one selector. Counters are per-class and durable in the marker regardless. | Two numbers and one selector. | **HELD** — keys present and unset; unset ⇒ the outbox still **records** durably (never lost) and `_deliver_escalation()` reports "channel not configured" at next session start. Recording is never conditional on the seam |

**Bound rule over the whole table:** a HELD key that is unset must never degrade into a silent default that
*does less*. Where a safe conservative behaviour exists (Q3, Q6) it is the loud one; where it does not (Q2,
Q4) the mechanism refuses and says so. No seam may be implemented as `value = config or <my guess>`.

---

## 5. P0 — Components A, B, C, C2: the executed-set closure, declared once, guarded both ways

### 5.1 Component A — `scripts/framework/executed_set.txt` (NEW; protected)

Same shape as `scripts/framework/framework_consumer_files.txt` (69 lines, path-per-line, `#` comments —
`grep -c "" scripts/framework/framework_consumer_files.txt`): **repo-relative paths, one per line, blank
lines and `#` comments ignored**, parsed with the installer's existing idiom (`_fc="${_fc%%#*}"; _fc="$(echo
"$_fc" | xargs)"`, `hos_install.sh:1834-1835`). Deliberately **not** a directory listing — AD-1's whole
point.

**Membership is ESC-A's, not mine.** The file's *contents* are the human's ruling on closure scope
(ADR §3.2 ESC-A options a/b/c). What this design binds is everything except the membership:

- The file exists, is the **only** declaration, and is read by all three consumers: the copy step (E), the
  install-record enumeration (F), and the currency check (H).
- Its header comment states the membership rule verbatim: *executed, sourced, or interpreted as instruction
  **outside** an agent session → in the set; executed **inside** a session → not* (AD-1 rule 5), and names
  ESC-A as the authority for the current membership.
- Adding a path is a protected-surface change (`scripts/framework/**`, line 26 of
  `protected_surfaces.txt`) — human-approved at merge.
- **The three unshipped launchers** (`bin/hos-worker`, `bin/hos-overseer`, `bin/hos-suspend`, TD-VF-038-6)
  join the set at P0 regardless of the ESC-A ruling — that is the "ship-set correction only, no behaviour
  change" P0 is defined as.

### 5.2 Component B — `scripts/framework/executed_set_residual.txt` (NEW; protected)

AD-1 rule 2c's *accepted in-clone reference register*. Three tab-separated columns plus a `#`-comment
header, so it is greppable and diffable and needs no parser:

```
# hos-executed-set-residual-schema: 1
# <referrer>  <in-clone target>  <reason — why this reference is accepted, and what closes it>
```

- `<referrer>` — a path in Component A that makes the reference.
- `<in-clone target>` — the `$REPO_ROOT`-relative path it reaches. Wildcards permitted for a family
  (e.g. `scripts/oversight/**`) but each family needs its own reasoned row.
- `<reason>` — free text, MUST name why the reference is acceptable *and* the issue or phase that closes
  it. An empty reason is a test failure.

Under ESC-A option (b) or (c) this file is non-empty at P1 and shrinks over time; under option (a) it is
empty and the closure test enforces that it stays empty. **Either way, a reference not in Component A and
not in Component B is a test failure** — that is the "silent partial closure is not acceptable" rule made
mechanical.

### 5.3 Component C — `tests/framework/test_executed_set.py` (NEW)

Three guards. The natural home is alongside `tests/framework/test_consumer_framework_files.py`, whose
existing assertions I read (`grep -n "def test" …` → `test_list_exists_and_nonempty`,
`test_every_listed_file_exists_in_source`, `test_bin_lib_git_credentials_present`,
`test_installer_reads_list_on_both_sides`, +4 more) — direction (a) is already covered there for the
consumer list and is mirrored, not shared, for this one.

| Guard | Assertion | Basis |
|---|---|---|
| **(a) listed → exists** | every path in A exists in the source tree and is a regular file | AD-1 (2a) |
| **(b) present in `bin/` → listed** | every file under `bin/` (recursively, incl. `bin/lib/`) appears in A. **This is FR4's stated test and does not exist today.** | AD-1 (2b), AF-038-8 |
| **(c) closure** | for each path in A, scan for invocations that resolve into a clone and fail on any target that is neither in A nor in B | AD-1 (2c) |

**Guard (c)'s scan contract — stated precisely, because a vague scan is a guard that passes by accident.**
The scan is a *lexical, deliberately over-broad* pattern match over each declared file, reporting a
candidate for **every** hit; a hit is cleared only by presence in A or B. Patterns, derived from what
`bin/hos-cron` actually does (the AF-038-1 table, re-measured with `grep -nE '\$REPO_ROOT|python3 -m scripts' bin/hos-cron`
→ 30 hits at lines 115, 240, 264, 303–307, 323, 329, 358, 425–467, 476, 485, 587, 592, 614, 664–678, 897–921,
978, 1050):

1. `$REPO_ROOT/<path>` and `"$REPO_ROOT/<path>"` in any position — the dominant form (`:329`, `:476`,
   `:485`, `:587`, `:678`, `:917`, `:978`).
2. `python3 -m <dotted.module>` anywhere, and any command inside a `cd "$REPO_ROOT" && …` subshell
   (`:240`, `:904`, `:907`) — the module path maps to a clone-resident file.
3. `git -C "$REPO_ROOT"` — **explicitly NOT a closure member.** Operating on the clone as *data* is the
   syncer's whole job. The scan must classify these as data access, not execution, or guard (c) reports
   ~20 false positives on `hos-cron` alone and gets disabled. This distinction is bound: **execute /
   source / interpret-as-instruction is in the closure; read-as-data is not.**
4. A path read as **instruction** even though nothing executes it — `$REPO_ROOT/bootstrap/${ROLE}-cron-prompt.md`
   (`:917`). This is AF-038-1's second-worst item and the one a naive "does it run a script?" scan misses
   entirely. The pattern is: any `$REPO_ROOT`-rooted path consumed into a prompt, a `--jq` expression
   (`:978`), or a command list.

**Failure output must name the referrer, the line, the target, and the remediation** ("add to
`executed_set.txt`, or register in `executed_set_residual.txt` with a reason"). A guard whose failure does
not say what to do gets suppressed.

### 5.4 Component C2 — installer edits at P0

1. **Delete the `bin/hos-human` second copy path** (`hos_install.sh:2013-2027`) and let `hos-human` reach
   consumers through the declaration like everything else. AD-1 (1): *no launcher may be copied by a second
   code path.* A test asserts no `cp` of a `bin/` file exists in `hos_install.sh` outside the
   declaration-driven loop.
2. **Correct the false comment** at `hos_install.sh:1822` (*"Covers: all of bin/ (incl. bin/lib/)"*), which
   is wrong today and would be wrong in a new way afterwards.
3. The consumer ship-set (`framework_consumer_files.txt`) and the executed set (A) are **different
   questions** — what a consumer *receives* vs. what the machine *executes out-of-band* — and stay two
   files. A test asserts every path in A that is consumer-relevant also appears in
   `framework_consumer_files.txt`, so a consumer can never be installed missing something its execution
   root needs.

**P0 exit criterion (measured):** guards (a), (b), (c) green; `bin/hos-worker`, `bin/hos-overseer`,
`bin/hos-suspend` present in a fresh consumer install; **zero behaviour change** — no execution root exists,
no launcher moved, no crontab touched.

---

## 6. P1 — Component D: the one resolver, the one call site

### 6.1 `bootstrap/lib/hos_paths.sh` (NEW; protected; sourced, never re-implemented)

Shell is canonical because every consumer except the settings generator is shell. **Any Python consumer
invokes this file as a subprocess and parses its stdout** — it does not re-derive the path. That is what
makes "one derivation" (AD-3) true rather than aspirational.

| Function | Inputs | Output (stdout) | Exit | Contract |
|---|---|---|---|---|
| `hos_state_root` | env `HOS_STATE_DIR` | absolute path | 0 | `${HOS_STATE_DIR:-$HOME/.hos}` — **identical** expression to `hos-cron:123`. Does **not** create. |
| `hos_exec_root <project>` | project key | absolute path | 0 / 2 | **Q4's single seam.** The only place an execution-root path is composed. Ships as `$(hos_state_root)/exec/<project>` marked as the unbound default. Exit 2 on empty/invalid project key — never a path with an empty segment. |
| `hos_exec_root_status <project>` | project key | `migrated` \| `unmigrated` | 0 | AD-3's required boolean. `migrated` iff the execution root exists **and** its install record exists and is not torn (no `INSTALL-IN-PROGRESS`). Presence of the directory alone is **not** migrated — a half-copy must read as unmigrated. |
| `hos_install_record_dir <project>` | project key | absolute path | 0 | `$(hos_state_root)/installs/<project>` |
| `hos_clone_key <clone-path>` | absolute clone path | `<hash>-<basename>` | 0 / 2 | `hos-cron:303-307` hash idiom (`md5sum` → `md5` → `cksum`), suffixed with basename. Exit 2 if the path is not absolute. |
| `hos_marker_dir <clone-path>` | absolute clone path | absolute path | 0 | `$(hos_state_root)/marker/$(hos_clone_key …)` — **the only path this library returns that any session may read** |
| `hos_session_dir <clone-path>` | absolute clone path | absolute path | 0 | `$(hos_state_root)/sessions/$(hos_clone_key …)` |
| `hos_sync_dir <clone-path>` | absolute clone path | absolute path | 0 | `$(hos_state_root)/sync/$(hos_clone_key …)` |
| `hos_auth_dir` | — | absolute path | 0 | `$(hos_state_root)/auth` (TD-VF-038-5) |
| `hos_project_for_clone <clone-path>` | absolute clone path | project key | 0 / 1 / 3 | **TD-VF-038-1's reverse-resolver.** Scans `~/.config/hos/projects.conf` for any `<key>_<role>_root=<path>` whose value resolves (via `readlink -f`) to the given clone. Exit 1 = no match; **exit 3 = more than one match** (ambiguous — the caller must require `--project`, never pick one). |
| `hos_repo_root_for <project> <role>` | project key, role | absolute path | 0 / 1 | `_conf_val`-equivalent read of `<project>_<role>_root`. This is what makes the interactive launchers relocatable (TD-VF-038-1). |
| `hos_maybe_gitignore_exec_root <path>` | absolute path | — | 0 | **Q5's seam. Empty body, called from exactly one install site**, guarded by "is this path inside a git working tree?". Documented as HELD. |

**Bound rules.**
- **No path composition outside this file.** A test greps every component in Component A plus
  `hos_install.sh`, `hos_setup_partner.sh`, the four launchers, `.envrc`, and `docs/**` for a literal
  `.hos/exec`, `/exec/`, or an `HOS_STATE_DIR`-rooted string and fails on any hit outside `hos_paths.sh`
  (§14 T-P1-1).
- **The library is a member of the executed set** (it is under `bootstrap/`) and is verified by the currency
  check like everything else.
- **It creates nothing.** Directory creation belongs to the install (E) and to the syncer's own state dirs;
  a resolver that creates is a resolver that can be tricked into creating.
- **`readlink -f` everywhere** before comparing paths, so a symlinked clone or execution root cannot make
  two components disagree about identity (the same defence AD-7 applies to `$0`).

### 6.2 The reverse-resolver's role in launcher startup (TD-VF-038-1)

Project-key resolution order for `hos-human` / `hos-worker` / `hos-overseer`, bound:

1. `--project <key>` if given (new flag; the escape hatch for every ambiguous case).
2. Otherwise `hos_project_for_clone "$(readlink -f "$PWD")"` walked up to the enclosing git toplevel.
3. Exit 1 (no match) or exit 3 (ambiguous) ⇒ **refuse to start** with a message naming the resolved clone,
   the `projects.conf` path, and the `--project` remedy. **Never guess.** A launcher that guesses its
   project authenticates as the wrong role against the wrong repo.

`hos-cron` is unaffected — it already requires `--project` (`hos-cron:96`).

---

## 7. P1 — Components E, F, G: copy-on-install, the install record, and the human-only gate

### 7.1 Component E — `_install_execution_root()` (EDIT `bootstrap/hos_install.sh`)

**Contract — what the code must do, in this order:**

1. Resolve the project key (installer already knows it) and `hos_exec_root "$project"` (D). **If Q4 is
   unruled, refuse** with a named escalation — ADR §5 (2) states Q4 cannot ship deferred.
2. Ensure `$(hos_state_root)` exists and is mode `0700`, owned by the invoking uid. **Refuse and report if
   it is group- or world-writable and cannot be hardened** (TD-VF-038-5 measured 0775 today). Apply the
   same ownership guard `hos_repo_sync.sh:44-50` already uses (`stat -c '%u'` with a `stat -f` fallback,
   empty ⇒ unverifiable ⇒ refuse).
3. Write the `INSTALL-IN-PROGRESS` sentinel into `installs/<project>/` **before** the first byte is copied
   (AD-5 (2)).
4. **Stage, then swap.** Copy every path in Component A into a sibling staging directory
   `exec/<project>.staging-<pid>`, preserving the repo-relative path and the executable bit
   (`cp -p`; the installer's existing `case` on `_fc` for chmod at `hos_install.sh:1839+` is the precedent).
   On success, atomically rename the staging directory into place and remove the previous one. **A partial
   copy must never be reachable as an execution root** — this is why staging exists and why
   `hos_exec_root_status` keys on the record, not the directory.
5. Write the install record (F) covering the staged content **and** the generated in-clone artifacts (I).
6. Remove the sentinel. Only now is the install "complete" and `hos_exec_root_status` = `migrated`.
7. Call `hos_maybe_gitignore_exec_root` (Q5's empty seam) exactly once.

**Wholeness (FR3/AD-1 (3)):** the copy is all-or-nothing. A file in A that is missing from the source is a
**hard failure**, not the `warn … skipping` the current ship-set loop does (`hos_install.sh:1836`) — the
consumer-file loop may degrade; the execution root may not, because a launcher that starts with a missing
dependency is exactly the split-directory state FR3 prohibits.

### 7.2 Component F — the install record (AD-5)

Two files under `installs/<project>/`, both TSV so the currency check reads them in shell with `awk`/`cut`
and **no JSON parsing in the hot path** — deliberately avoiding the `grep -o` JSON fragility of
`hos_repo_sync.sh:60`.

**`record.tsv`** — one row per artifact; fixed 7 columns; empty string for N/A; schema comment header
mirroring `.hos-manifest`'s `# hos-manifest-schema: 2` (`hos_install.sh:2186`):

```
# hos-install-record-schema: 1
# kind  declared-path  installed-abs-path  sha256  mode  template-sha256  role
EXEC        bin/hos-cron        /home/u/.hos/exec/hos/bin/hos-cron   <sha>  755  <empty>  <empty>
EXEC        bootstrap/lib/hos_paths.sh  …                            <sha>  644  <empty>  <empty>
GENERATED   .claude/settings.json  /home/u/Code/P/Worker/.claude/settings.json  <sha>  644  <tsha>  worker
GENERATED   .claude/settings.local.json  …                           <sha>  600  <tsha>  worker
```

- `kind` ∈ {`EXEC`, `GENERATED`}. `EXEC` rows are at the execution site; `GENERATED` rows are in-clone
  (AD-5's second bullet) and drive AD-14's **warn-only** drift response, never fail-closed.
- `sha256` via the installer's existing portable `_sha256()` (`hos_install.sh:290`) — reused, per AD-5 (4)'s
  *"MAY share the row schema and the `_sha256` helper; MUST NOT share the file."*
- `mode` is recorded so FR3's "executable bit preserved" is *verifiable*, not merely intended.

**`record.meta.tsv`** — install-level provenance, `key<TAB>value`:

| Key | Value |
|---|---|
| `release_tag` | contents of the target's `.hos-release` |
| `source_commit` | `git -C <source> rev-parse HEAD` at install time |
| `source_dirty` | `true` if the source tree had tracked modifications (a dirty-source install is legal but must be recorded — otherwise "currency" is measured against a commit that never contained the installed bytes) |
| `installed_at` | ISO-8601 UTC |
| `installed_by` | `id -un` + `id -u` |
| `clone_path` | the plaintext clone path (collision detection, §2) |
| `declaration_sha256` | sha of `executed_set.txt` as installed — so a changed *declaration* is itself a currency signal |
| `record_schema` | `1` |

**Bound properties (AD-5):** written atomically (`mktemp` + `fsync` + `rename` on the same filesystem — the
`hos_repo_sync.sh:180-186` precedent plus the fsync AD-13 requires); a torn record is detectable via the
sentinel; **the record is the trust anchor, not git** (§7.4); it is **never** granted to any session (§2
invariant 1); and it is **not** `.hos-manifest` (which stays in the target repo doing its existing job —
TD-VF-038-8).

### 7.3 Component E's human gate (AD-4 — FR2's entire strength)

**Two independent conditions, both required**, per TD-VF-038-7:

1. **A tty-backed confirmation**, using the installer's existing `read -r <var> </dev/tty` idiom
   (`hos_install.sh:963`, `:2240`). No tty ⇒ the read fails ⇒ **refuse**, never default.
2. **An explicit `--confirmed`-class assertion** in the invocation, mirroring
   `bootstrap/submit_pr.sh:105`'s *"a human has approved THIS push"* semantics.

Plus:
- A `--dry-run`/plan path **may** report what would change and **may not** write (AD-4). The installer
  already has `$DRY_RUN` and a `dry_run` reporter — reuse them.
- **Component G's negative test** greps `.github/workflows/**`, `bin/**`, `scripts/**`, `bootstrap/**`
  (excluding `hos_install.sh` itself) and the agent prose in `.claude/agents/**` for an invocation of the
  copy entry point, and **fails on any hit**. AD-4 names the regression precisely: *"someone will automate
  the install for convenience"* silently deletes FR2.
- **FR2's acceptance, executable:** merge a change to a declared source file → the execution copy is
  byte-identical before and after → the currency check reports **STALE** → only a human-run install changes
  the bytes.

---

## 8. P2 — Components H and I: the currency check and per-role settings

### 8.1 Component H — `bootstrap/hos_verify_exec_copy.sh` (NEW; protected; member of the executed set)

**Invocation:** first thing in every launcher, before preflight, before auth, before the syncer.
`hos_verify_exec_copy.sh --project <key>` → classification on stdout, human-readable report on stderr,
exit code carrying the decision.

**Order of operations, bound (AD-6):**

1. **Self-verify first.** Hash `$0` (via `readlink -f`) and compare to its own `EXEC` row. Mismatch,
   missing row, unreadable record, or `INSTALL-IN-PROGRESS` present ⇒ **UNRECOGNISED**, refuse, escalate.
   A checker that verifies everything but itself has a one-file blind spot (AD-6).
2. **Integrity, anchored on the install record.** For every `EXEC` row: file present, `sha256` equal, mode
   equal. Then the reverse: no file exists under the execution root that has no row (an *extra* file is as
   much a tamper signal as a changed one). Any failure ⇒ **UNRECOGNISED**.
3. **Currency, anchored on the committed clone source.** Resolve the clone via
   `hos_repo_root_for <project> <role>`; for every `EXEC` row compute the sha of
   `git -C <clone> show <default-branch>:<declared-path>` — **committed, never the working tree** (AD-6:
   an uncommitted local edit must not demand a reinstall, and the drift signal must track *merged*,
   PR-gated change). Compare against the recorded `sha256`. Also compare `declaration_sha256` against the
   committed `executed_set.txt`, so a *new* declared file registers as drift even though it has no row.
4. **Classify** into exactly the ADR's four outcomes and respond:

| Outcome | Condition | Response | Exit |
|---|---|---|---|
| **CURRENT** | integrity OK; every recorded sha == committed sha; declaration unchanged | silent; proceed | 0 |
| **STALE** | integrity OK; ≥1 committed source sha differs, or the declaration moved | **loud stderr report in the #1200 register** — naming each drifted file and *"re-run the install"* — plus an outbox record; run-vs-refuse decided by `_stale_response()` (**Q3 seam, HELD**) | 0 (`warn`) / 4 (`halt`) |
| **CURRENCY-UNKNOWN** | integrity OK; the clone is unreadable / unreachable / not a git tree / the ref does not resolve | warn on stderr; **proceed**. Integrity is intact and an unrelated repo problem must not halt the machine (AD-6) | 0 |
| **UNRECOGNISED** | integrity fails: sha mismatch, missing row, missing/extra file, mode mismatch, unreadable or torn record | **fail closed — refuse to run**; immediate outbox escalation. **Not configurable**; no input may widen what runs | 5 |

5. **The #1200 report register, matched not re-implemented (FR36/AD-9).** The STALE report reuses
   `hos_repo_sync.sh:163-176`'s shape verbatim: a blank line, a single `<component>: STALE — …` line on
   stderr naming the concrete condition, then a cause line. This is a *different* staleness (copy vs.
   source, not HEAD vs. origin) and must say so in its own words — it must not be mistakable for the
   sync's report, and it must not replace it.

**The FR8 prohibition, made structurally checkable (AD-6, prohibited three times).** Bound:
- The script contains **no** write, copy, move, `chmod`, `install`, redirect, or `mktemp` whose destination
  resolves under the execution root or the install record. Its only writes are to the marker/outbox subtree.
- A test (§14 T-P2-2) asserts the executed copy is **byte-identical** (sha and mode) after a *detected*
  drift of each class.
- A lexical guard fails the build on any of `cp `, `mv `, `install `, `rsync`, `chmod`, `>`, `>>`, `tee`,
  `sed -i` appearing in this file with an execution-root-derived destination.
- The script's own header states the prohibition and why: *a check that repairs itself from a source an
  agent can write is an automated path from an agent edit to unsandboxed execution.*

**Honest-scope statement, required in the header (AD-6):** the check is tamper-**evidence conditional on
the sandbox**, never tamper-**proofing**. Against an actor who can write the execution root it provides
nothing — they rewrite the record too. Per TD-VF-038-4 that actor exists today for Worker and Overseer.

**Cost:** N sha256 + N `git show` per launcher start, N = the declared set. At the measured 10-minute cron
cadence (`crontab -l | grep -i hos`) this is negligible. **No caching** — a cache is a second trust anchor
(AD-6).

### 8.2 Component I — per-role settings generation (AD-14, split into two payload classes per TD-VF-038-2)

TD-VF-038-2 establishes that FR27's file and FR26's grant live in **different files**. Until TD-ESC-1 is
ruled, this design specifies both classes and the boundary between them; **the generator is one component
with two outputs, not two components.**

| | **Class A — role settings** | **Class B — sandbox posture** |
|---|---|---|
| Output file | `<clone>/.claude/settings.json` | `<clone>/.claude/settings.local.json` |
| Tracked today? | **yes** (`git ls-files --error-unmatch .claude/settings.json`) → **untracked** by this change (P4's three-part change) | **no** — `.gitignore:40` |
| Template | **NEW** `contract/role-settings.template.json` | **EXISTS** `contract/sandbox-policy.template.json` (TD-VF-038-2) |
| Protected? | yes — `contract/**`, already (`protected_surfaces.txt:17`). **No new entry needed.** | yes — same, already |
| Carries | `permissions.allow` (9 entries today), `hooks.SubagentStop` → `record_agent_model.py` | `permissions.deny` (45), `additionalDirectories`, `sandbox.{enabled,network,filesystem}` |
| Carries the **marker read grant** (FR26)? | **no — it cannot** | **yes** — `sandbox.filesystem.allowRead` |
| Carries AD-2's **negative rule**? | no | **yes** — absence from `allowWrite`/`allowRead`/`additionalDirectories` |
| Owner | this change | **#1146** (`docs/SANDBOX-POLICY.md:11-13`) — this change *consumes* it and adds two entries |
| Drift response | **warn only** (AD-14: an in-clone file the role can edit must never fail the machine closed) | warn only, same reason |

**`scripts/framework/gen_role_settings.py` contract:**

- **Signature:** `generate(template_path, role, substitutions) -> str` — a **pure function**: same inputs,
  byte-identical output (FR29). No clock, no randomness, no environment read inside the function; the
  caller supplies every substitution.
- **Substitutions** come from Component D and from the installer, never from a second derivation. The
  existing template's placeholders (`docs/SANDBOX-POLICY.md:230-240`) are `__HOS_ROOT__`,
  `__PROJECT_ROOT__`, `__CONFIG_DIR__`, `__HANDOFF_DIR__`, `__HOME__`, `__ROLE__`,
  `__CLAUDE_PROJECT_STATE__`; this change adds **`__MARKER_DIR__`** (from `hos_marker_dir`).
- **Fail closed on an unsubstituted placeholder.** `docs/SANDBOX-POLICY.md:200-205` (§4 item 6) already
  requires this and names the failure mode (#1114): a surviving `__NAME__` produces a policy that silently
  denies what it meant to allow. Bind: any `__` surviving in the output ⇒ hard failure, nothing written.
- **Required content assertions (FR27/AD-2), checked by the generator itself, not only by a test:**
  1. `__MARKER_DIR__`'s resolved value appears in `sandbox.filesystem.allowRead`.
  2. It appears in **neither** `allowWrite` **nor** `permissions.additionalDirectories`.
  3. `hos_exec_root`, `hos_install_record_dir`, `hos_session_dir`, `hos_sync_dir`, `hos_auth_dir` and
     `hos_state_root` appear in **none** of `allowRead`, `allowWrite`, `additionalDirectories`.
  4. Violation of any of these ⇒ the generator **refuses to write**. *A role cannot be configured into a
     state where its backstop is unreadable — nor into one where its boundary is void* (AD-14).
- **Provenance is authoritative in the install record** (`GENERATED` rows carry `template-sha256` + `role`,
  §7.2). An in-file `_hos` provenance key is permitted **only** if the implementer empirically verifies the
  CLI tolerates unknown top-level keys (AD-14 — *"do not design around an assumption here"*). Evidence that
  it may: the live Human profile carries top-level `model`, `hooks`, `permissions`, `sandbox` and nothing
  else, so no unknown key is currently exercised. **Treat as unverified.**
- **Untracking `.claude/settings.json`** is a `git rm --cached` + `.gitignore` entry + an installer change
  so an upgrade regenerates rather than merges. The current merge block (`hos_install.sh:1719-1757`) —
  which python-merges three `permissions.allow` entries into an existing file and only copies wholesale
  when none exists — is **replaced**, not extended: it is not template generation and AD-14 requires
  generation.

---

## 9. P3 — Components J, K, L, M, M2: the syncer, the registry, the marker, the outbox

### 9.1 Component K — the session registry (AD-10)

A **multi-holder, clone-keyed** structure, deliberately **not** `hos-cron`'s exclusive mutex, which is
unchanged (`hos-cron:180-208`).

**Layout:** `sessions/<clone-key>/<pid>-<launcher>.json`, one file per live session, created `0600`.
Registration is a create-exclusive write (`set -o noclobber` or `mkdir`-then-write) so two launchers
starting at the same instant cannot collide.

**Entry fields (AD-10 (1) — "at minimum"):**

| Field | Type | Purpose |
|---|---|---|
| `pid` | int | liveness via `kill -0` |
| `role` | string | `human` \| `worker` \| `overseer` \| future |
| `clone_path` | absolute path, plaintext | collision detection against the clone key |
| `launcher` | string | which launcher registered (`hos-human`, `hos-cron`, …) |
| `start_epoch` | int | age-based reclamation |
| `project` | string | the resolved project key (§6.2) |

**Function contracts (`bin/lib/hos_session_registry.sh`):**

| Function | Contract |
|---|---|
| `hos_session_register <clone> <role> <launcher> <project>` | Writes the entry atomically; echoes the entry path; installs nothing (the caller owns the trap). Exit non-zero if the registry dir is not writable — a launcher that cannot register **must still start**, but must record an outbox escalation, because an unregistered session is a session the syncer cannot see. |
| `hos_session_release <entry-path>` | Idempotent removal. Safe to call twice, safe on a path already gone. |
| `hos_session_any_live <clone>` | Exit 0 if any holder is live **after reclamation**, 1 if none. The syncer's skip predicate. |
| `hos_session_reclaim <clone>` | Applies the rules below; returns the count reclaimed; each reclamation writes an outbox record (FR17 requires reclamation be recorded). |

**Reclamation rules, reusing `hos-cron`'s hard-won #1002 logic verbatim in shape (`hos-cron:176-206`):**

1. **Age ceiling** — reclaim regardless of pid liveness once age ≥ ceiling. Ceiling derived as `hos-cron`
   does: `max(2 × session cap, 3600s)`, so a disabled or tiny cap cannot collapse it to an instant reclaim.
2. **`kill -0` liveness** — a dead pid is reclaimed below the ceiling.
3. **Both, not either** — PID reuse makes liveness alone a permanent standstill; an age ceiling alone races
   an in-flight registrant. This is the exact reasoning in `hos-cron:176-179`.
4. **Ambiguity resolves toward skipping the sync** (AD-10 (4)). An entry with no readable `pid` is
   "registrant in flight" ⇒ **treat as held**. Note this is the *opposite* default from `hos-cron:195-197`
   (which exits rather than proceeding) — and it lands in the same safe direction for a different reason:
   there, ambiguity means don't run a cycle; here, it means don't touch the tree.

### 9.2 Component L — launcher startup, bound order (AD-9, AD-10, TD-VF-038-1)

For **all four** launchers, in this exact order — the ordering is AD-9's and is not negotiable, because
syncing after the lock deadlocks the launcher against its own registration:

```
1. resolve project key            (--project, else hos_project_for_clone; refuse on ambiguity — §6.2)
2. resolve REPO_ROOT              (hos_repo_root_for <project> <role>  — replaces $(dirname "$0")/..)
3. currency check                 (Component H; UNRECOGNISED ⇒ exit 5, never start)
4. self-location shim             (Component N, P4; warn mode)
5. preflight                      (validate_setup.sh — from the EXECUTION ROOT, not the clone)
6. auth                           (get_app_token.sh — from the EXECUTION ROOT; token temp into auth/)
7. SYNCER                         (Component M — before the lock, so the session starts current)
8. register session lock          (Component K; trap release on EXIT/INT/TERM)
9. surface undelivered outbox     (Component J; alongside the #1200 report)
10. start the CLI as a CHILD      (NOT exec — AD-10 (3))
11. propagate exit code; release  (trap fires; forward INT/TERM to the child)
```

**Step 10 is AF-038-4's blocker resolved.** `bin/hos-human:53`, `bin/hos-worker:24`, `bin/hos-overseer:20`
all end in `exec claude…`, which replaces the process image so an EXIT trap can never fire. Bound
replacement contract:

- Run the CLI as a child; capture its pid.
- `trap` on `EXIT`, `INT`, `TERM`: forward the signal to the child, `wait` for it, then release the
  registry entry. Release must be idempotent (`hos_session_release`) because both the signal handler and
  the EXIT trap can reach it.
- **Propagate the child's exit status as the launcher's own**, including the `128+N` signal-death
  convention. Anything that today reads a launcher's exit status must see no change.
- `hos-worker` and `hos-overseer` pass `--dangerously-skip-permissions` and `hos-cron` passes
  `--permission-mode bypassPermissions` (`docs/SANDBOX-POLICY.md:43-47`); those arguments are **unchanged**
  by this component — changing them is #1146's, not this change's.
- **User-visible** (exit codes, signal handling, and now cwd-sensitivity from step 1) ⇒ **TD-ESC-3** to
  `pm-agent`, extending AD-10 (3)'s existing notification.

`hos-cron` gains step 8 only (it already does 1, 2, 5, 6 and has its own overlap mutex) plus the
`:484` token-mktemp move to `auth/` (M2).

### 9.3 Component M — the syncer's state machine (AD-11), exact sequence

`bootstrap/hos_sync_clone.sh --clone <path> [--project <key>]`. Runs from the execution root. States:
`IDLE → PRECHECK → FETCHED → JOURNALLED → MERGING → VERIFYING → {OK | RESTORING → {RESTORED | QUARANTINED}}`.

**Step 0 — the not-an-agent-role guard (AD-15, §11).** Before anything else, before any git command.

**PRECHECK**
1. Acquire the **sync mutex** — `mkdir "$(hos_sync_dir <clone>)/mutex.lock"`, the same create-exclusive
   primitive `hos-cron:188` uses, with the same age-ceiling reclamation. Failure ⇒ record `skipped`
   (reason `sync-in-progress`), exit.
2. `hos_session_reclaim` then `hos_session_any_live` (K). Live ⇒ **skip** (reason `session-live`, listing
   holders), record, exit. *Optionally* perform the ref-only fetch of step FETCHED.1 first — see AD-10 (5)
   and §9.6.
3. **Non-terminal journal present?** ⇒ take the **recovery path** (below). Not the normal path.
4. **Cleanliness precondition (AD-12/AF-038-6).** `git -C <clone> status --porcelain --untracked-files=no`
   must be empty. **Untracked files are permitted and are not a skip reason** — measured this session, the
   Worker clone's `git status` lists dozens of untracked `audit/log/**` records plus `.claude/worktrees/`,
   so today's `--porcelain` gate (`hos_repo_sync.sh:137`) would skip forever and escalate on normal
   operation. Not-clean ⇒ record `skipped` (reason `tracked-modifications`), exit.
5. Determine the default branch exactly as `hos_repo_sync.sh:110-117` does (`symbolic-ref
   refs/remotes/origin/HEAD`, `remote set-head -a` retry, fall back to `main`) and the checked-out branch.
6. **Cadence clock check (Q2 seam, AD-12).** Proceed only if `now - last_success_epoch ≥ effective
   interval`, **or** the failure-retry floor has elapsed since `last_attempt_epoch`. A *skip* advances
   neither clock.

**FETCHED**
1. `git -C <clone> fetch origin` — **before** the journal, **outside** the journalled window (AF-038-9).
   Fetch writes refs and objects, never the worktree or index; it is idempotent and safely retryable.
2. Failure ⇒ record `failed` (reason from the classifier), advance `last_attempt_epoch` and
   `consecutive_failures`, exit. **No journal was written and no tree was touched — there is nothing to
   repair.** Reuse `hos_repo_sync.sh:88-90`'s `_is_structural_failure()` classifier verbatim (structural =
   `read-only file system|permission denied|unable to unlink|unable to create`; else transient) so the
   marker and #1200's report cannot disagree (FR36).
3. Compute `behind` = `git rev-list --count <default>..origin/<default>`. Zero ⇒ record `ok`, advance
   `last_success_epoch`, exit (nothing to do; the existing `hos_repo_sync.sh:130-133` up-to-date path).

**JOURNALLED (FR19)** — written **durably and atomically before the first command that can modify the
tree**: `mktemp` in the same directory → write → `fsync` the file **and its parent directory** → `rename`.
The `hos_repo_sync.sh:180-186` `mktemp`+`mv` precedent is correct and is reused; the `fsync` is the
addition, and it is what makes "durable across a kill at any point" true rather than probable.

| Journal field | Value |
|---|---|
| `schema` | `1` |
| `clone_path` | plaintext absolute path |
| `pre_commit` | `git rev-parse HEAD` — **the restore target** |
| `branch` | checked-out branch |
| `default_branch` | resolved default |
| `target_commit` | `git rev-parse origin/<default>` — resolved **before** the merge, so the target cannot move under the operation |
| `cleanliness` | the exact predicate verified in PRECHECK.4 and its result |
| `mode` | `merge-ff` \| `ref-only` (see MERGING) |
| `timestamp` | ISO-8601 UTC |
| `pid` | the syncer's pid |
| `recovery_attempted` | `false` — set `true` at most once, ever (AD-11 (7)) |

**MERGING** — exactly one tree-modifying command, and only in one of the two cases:

- **Default branch checked out:** `git -C <clone> merge --ff-only <target_commit>`. The *only*
  tree-modifying step in the whole mechanism. Note it merges the **already-fetched ref**, not `origin/…`
  re-resolved — AF-038-9's split, made concrete.
- **Default branch not checked out:** `git -C <clone> fetch origin <default>:<default>` — git permits this
  only as a fast-forward and it **does not touch the working tree at all**. Journal `mode` = `ref-only`;
  the machine reduces to fetch-and-record and there is nothing to restore.
- **Prohibited in this path, on correctness grounds (FR18/AD-9):** no `merge` other than `--ff-only`, no
  `rebase`, no `reset`, no `--force`, no `--force-with-lease`, no `stash`, no `checkout` of another branch,
  no `clean`. A lexical guard test asserts their absence from the sync path (§14 T-P3-4). The justification
  is not style: *a fast-forward from the upstream default branch introduces only commits that already
  passed the PR gate*, and that sentence is the entire argument for permitting an unreviewed automated
  change to a clone.
- **The one real hazard** — an incoming commit adding a path that collides with an untracked file — is
  handled by git itself: `merge --ff-only` refuses **before** touching anything ("untracked working tree
  file would be overwritten"), a clean abort recorded as a failure, never a partial state (AD-12).

**VERIFYING (FR21)** — success is asserted, never assumed. **Both** must hold:
1. `git rev-parse HEAD` == `target_commit`.
2. The tree is clean **under the same predicate used in PRECHECK.4** (`--untracked-files=no`) — same
   predicate, not a similar one, or "verified clean" means something different at the two ends.

Any discrepancy ⇒ **RESTORING**, and the outcome is recorded as **failure**. *"Reported successful" and
"actually at the new commit with a clean tree" are the same condition.*

**RESTORING (FR20, and AF-038-7/ESC-C's reconciliation)** — exactly **one** primitive:
`git -C <clone> reset --hard <journal.pre_commit>`.
- MUST NOT run `git clean` — untracked files are not this mechanism's to delete (AD-12 permits them).
- MUST NOT touch any other branch, MUST NOT fetch, MUST NOT consult the network.
- **This does not violate FR18's intent** (AD-11 (6)): FR18 constrains the *sync* path — what content may
  be introduced; FR20 governs the *repair* path — removing content that was never gated and returning to a
  commit already present. The requirement text does not say so, which is why the ADR raises **ESC-C**;
  until `pm-agent` restates it, the implementer must read AD-11 (6), not FR18 literally. **The header of
  this component must carry that reconciliation in full**, or the next reader re-derives the contradiction.

**Terminal states**
- **RESTORED:** record `failed` + `restored`, clear the journal, advance `last_attempt_epoch` and
  `consecutive_failures`, escalate via the outbox.
- **QUARANTINED:** restore itself failed, or the tree cannot be verified at `pre_commit`. **Retain the
  journal**, perform **no further git operation on that clone, ever**, and re-escalate on every subsequent
  invocation. Recovery is attempted **at most once** (`recovery_attempted`); there is no retry loop that
  can grind a damaged tree (AD-11 (7)).

**Recovery path (FR22 + FR23 reconciled — AD-11 (8)).** On finding a non-terminal journal at PRECHECK.3:
1. **Automatically restore** to `journal.pre_commit` — target derived from the journal *at run time*, no
   hand-authored commit-specific procedure. This is exactly FR23, and exactly what the thread's decaying
   four-step manual repair failed at.
2. Then **refuse to perform any new sync in this invocation** and escalate. This is exactly FR22.
3. *Repair yes; new work no.* Set `recovery_attempted = true` before attempting; if it is already `true`,
   go straight to QUARANTINED.

### 9.4 Component J — the marker and the outbox (AD-13, AD-16)

**Marker ≠ journal (AD-13).** The journal is in-flight intent, short-lived, never read by a session, in the
never-granted `sync/` subtree. The marker is durable outcome, read by humans and sessions, in the
read-granted `marker/` subtree. Conflating them is the exact defect `hos_repo_sync.sh`'s single state file
has today (its `last_sync_epoch` means neither — TD-VF-038-9).

**`marker/<clone>/sync.json` — one document, one atomic replace.** JSON, because humans and sessions read
it; written and read via `python3` (already a hard prerequisite of every launcher path — `hos-cron:240`),
**not** via `grep -o`, which is how `hos_repo_sync.sh:60` reads its own state and is fragile. If `python3`
is unavailable the marker writer **refuses and appends a plain-text line to the outbox** rather than
silently skipping the record.

| Field | Type | Required | Source |
|---|---|---|---|
| `schema` | int | always | `1` |
| `state` | enum | always | `running` \| `ok` \| `skipped` \| `failed` \| `quarantined` (FR24 + AD-11's terminal) |
| `timestamp` | ISO-8601 UTC | always | write time |
| `clone_path` | string | always | plaintext (collision detection) |
| `commit_before` | sha \| null | always | `pre_commit`; null only when no operation was attempted |
| `commit_after` | sha \| null | always | post-state; null when skipped/failed |
| `reason` | string | **when `skipped`, `failed`, or `quarantined`** | FR24's conditional field |
| `cause_class` | enum | when `failed` | `structural` \| `transient` — the `_is_structural_failure()` classifier, shared with #1200 (FR36) |
| `consecutive_skips` | int | always | AD-13 counters |
| `consecutive_failures` | int | always | AD-13 counters |
| `last_success_epoch` | int | always | AD-12 clock |
| `last_attempt_epoch` | int | always | AD-12 clock |

**Well-formedness rule (FR24):** a marker missing any always-required field, or missing `reason` in a
`skipped`/`failed`/`quarantined` state, is **malformed** and any reader must say so rather than treat
absence as "fine." A reader that silently tolerates a missing field reproduces the originating incident.

**Atomicity (FR25):** `mktemp` in the same directory → write → `fsync` file → `rename` → `fsync` parent
directory. **Never** truncate-and-rewrite. A reader sampling continuously must never observe a partial
document.

**Counters in the marker, not beside it (AD-13):** one document, one replace, so a reader can never see
counters inconsistent with the outcome they belong to. `consecutive_skips` resets on a verified success;
`consecutive_failures` resets on a verified success; a skip advances **neither clock** (AD-12) — a skip did
no work and must not be able to mask staleness.

**The `attempt.json` split.** `sync/<clone>/attempt.json` holds only the *retry-floor bookkeeping* the
syncer needs before it has decided anything (`last_attempt_epoch`, `consecutive_failures`, `backoff_until`,
`latched`). It is a duplicate of marker fields **by design**: the marker is the read-granted public record
and must not be the syncer's control input, or a session could influence the syncer by influencing what it
reads. **The syncer reads `attempt.json`; it only ever writes the marker.** (This is the one place I add
structure beyond the ADR; the alternative — the syncer trusting a session-readable file — reintroduces the
"marker as control" the ADR forbids in AD-13's last bullet.)

**The outbox (AD-16), `marker/<clone>/outbox/<id>.json`.** Two-phase by construction:

1. **Record durably first** — atomic write, `delivered: false`, with `id` = `<epoch>-<class>-<short-hash>`
   so it is stable and de-duplicable.
2. **Attempt delivery second** — via `_deliver_escalation()` (**Q6's channel seam**).
3. **Mark delivered third** — a second atomic write setting `delivered: true, delivered_at: …`.

**There is no code path in which an escalation is attempted, fails, and is discarded** (FR33). Undelivered
items resurface at the next session start (launcher step 9, §9.2), printed alongside the #1200 report.

| Outbox field | Purpose |
|---|---|
| `id`, `schema`, `created_at` | identity |
| `class` | `unrecognised-copy` \| `sync-quarantined` \| `sync-latched` \| `skip-threshold` \| `fail-threshold` \| `lock-reclaimed` \| `in-clone-launcher` \| `config-unset` |
| `clone_path`, `project`, `role` | scope |
| `detail` | human-readable, must name the remediation |
| `delivered`, `delivered_at`, `delivery_attempts` | the two-phase state |

**All AD-16 escalation sources route here, and only here:** UNRECOGNISED currency (H), QUARANTINED sync
(M), latched failures (M), reclaimed stale locks (K), in-clone launcher execution (N), plus the
`config-unset` class this design adds for the HELD seams (§4).

### 9.5 Component M — clocks and latching (AD-12)

- `last_success_epoch` advances **only** on a verified success (VERIFYING passed). The cadence interval is
  measured from it, and from nothing else.
- `last_attempt_epoch` + `consecutive_failures` advance on failure; the next attempt is gated by a **short
  retry floor with bounded backoff**, never by the full cadence interval.
- **A skip advances neither.** (It advances `consecutive_skips`.)
- **Latch:** after a configured number of consecutive failures the mechanism stops attempting and keeps
  escalating. An unbounded retry against a structurally broken clone (the #1183 read-only-sandbox class,
  which the `_is_structural_failure()` classifier already recognises) is a busy loop, not resilience.
- **The bound negative test — the regression that already happened once (AD-12):** after an induced
  failure, the next scheduled invocation MUST attempt again rather than report *"skipped, last synced Ns
  ago."* Today `hos_repo_sync.sh:180-186` runs unconditionally, including on the pull-failure path
  (`:143-146`), silencing retries for the full 900s default. That is the FR22 bug, and this is its test.

### 9.6 Composition with #1200 (FR36/AD-9)

- The syncer's **non-success output is #1200's report, preserved in behaviour and wording** — the
  `STALE — HEAD is N commit(s) behind origin/<branch>` line and the structural-vs-transient cause line. It
  is not re-implemented and not softened.
- Marker and report derive from the **same git facts** (`behind`, HEAD, the shared classifier), so they
  cannot disagree.
- **Detection (#1200) and remediation (this design) stay separate concerns.** A session that holds the lock
  and therefore never syncs is *told it is stale* — that is P3 working as designed, not a bug, and
  **no "sync anyway after N skips" escape hatch may be added** (AD-10 (6)).
- **The ref-only fetch while a session is live (AD-10 (5)):** permitted, and useful, because it is what
  lets the in-session #1200 report say *how* stale the session is. AD-10 (5) requires the implementer to
  **confirm** that a fetch cannot perturb a concurrent session (it writes refs and objects, not the
  worktree or index) **and** to make it skippable by configuration if that confirmation is not clean. Bind
  both: the confirmation is an explicit implementation task with a recorded result, and the config key
  `HOS_SYNC_FETCH_WHILE_SESSION_LIVE` exists with a documented default of **off** until the confirmation is
  recorded. Off is the conservative direction: the cost is a less precise staleness number, not a
  correctness loss.
- `bootstrap/hos_repo_sync.sh` itself is **not deleted by this design.** It is #1200's shipped artifact and
  `bin/hos-human:50` calls it. Its retirement — and the removal of its session-writable `/tmp` state
  (AF-038-5) — is §15.2 ISSUE-3, sequenced after the syncer is verified, so no phase of this work leaves
  the machine with neither mechanism.

---

## 10. P3 — the credential-locality fix (M2)

`hos-cron:484` (`_auth_tmp=$(mktemp -p "$_HOS_DIR")`) moves to `$(hos_auth_dir)`, created `0700`, which is
in the never-granted set (§2 invariant 1). This makes AD-13's *"the marker subtree holds no credential
material"* **structural rather than incidental**: the state root's own directory no longer holds live
installation tokens at all, so no future widening of a grant can expose one by accident. Also filed
independently (§15.2 ISSUE-2) so it survives a descoping of P3.

---

## 11. P3 — Component M step 0: the not-an-agent-role guard (AD-15)

**One named list, one refusal predicate, fail-closed.** Defined as a single constant in the syncer with an
explanatory comment, so there is one place to update when the CLI's variables change.

Marker variables, **measured this session** (TD-VF-038-10), most-specific first:

```
CLAUDECODE
CLAUDE_CODE_SESSION_ID
CLAUDE_CODE_ENTRYPOINT
CLAUDE_CODE_EXECPATH
CLAUDE_CODE_CHILD_SESSION
CLAUDE_PID
```

**Bound rules:**
- **Any** marker present (non-empty) ⇒ **refuse**, exit without a single git operation, and say which
  variable triggered the refusal.
- **Do NOT key on `HOS_CYCLE_ID`** (AD-15, confirmed by measurement — it is present in this session).
  `hos-cron:220-236` mints and exports it *before* launching the session, so a syncer invoked from
  `hos-cron` after minting would refuse itself.
- **Belt and braces:** the launcher invokes the syncer at step 7 (§9.2) — **before** any cycle identity is
  minted and before the CLI child starts.
- **Prefix-matching is not sufficient on its own.** `CLAUDE_*` as a glob would also catch operator-set
  variables like the `CLAUDE_EFFORT` present in this session; the list is explicit for that reason, and a
  comment records that a *new* CLI variable will not be caught until the list is updated. The
  implementation task includes re-running the measurement command and recording the date.
- **A test runs the syncer under a simulated session environment** and asserts zero git operations
  (§14 T-P3-6).

---

## 12. P4 — Components N, O, P: migration detection, emissions, `.envrc`

### 12.1 Component N — the self-location shim (AD-7/FR12)

`bin/lib/hos_selfloc.sh`, sourced first by every launcher (step 4, §9.2).

1. Resolve the launcher's own real path: `readlink -f "$0"` (or a portable equivalent) — **to defeat
   symlink games**, per AD-7.
2. Compare against `hos_exec_root <project>`.
3. **Executing from inside a clone while a valid execution root exists** ⇒ (a) **still do the job** (FR10 —
   nothing breaks), and (b) emit a loud stderr report naming **the exact invocation path it was started
   from** and **the exact replacement path**, and write an `in-clone-launcher` outbox record so it also
   surfaces at the next session start.
4. **No execution root exists** (pre-migration install) ⇒ **silent**. No nagging at installations that have
   not yet been offered the mechanism.
5. **Warn mode only at P4.** The escalation to *refuse* is a later phase (AD-8), at which point in-clone
   `bin/` is provably not an execution path and FR6 has its enforcement.
6. **Stated honestly in the header:** the shim is a migration aid, not a control. In Worker/Overseer an
   agent could delete the warning — which changes nothing, because that path is already open (TD-VF-038-4).

### 12.2 Component O — emitted instructions (FR11) and the cron-entry invariant (FR31)

Both emitters take the path from Component D — never a composed literal:

- `bootstrap/hos_install.sh:2450-2458` — the `echo` block inside "Next steps" (worker line `:2452`,
  overseer `:2456`, trim `:2459`).
- `bootstrap/hos_setup_partner.sh:215-220` — the `printf` block headed *"Suggested crontab entries (run:
  crontab -e)"*.
- The ten `docs/` files that reproduce a launcher path (TD-VF-038-11): `HUMAN-SETUP.md`,
  `OVERSIGHT-RUNBOOK.md`, `CUSTOMIZATION.md`, `CRON-SETUP.md`, `AGENTS.md`, `MACHINE-ACCOUNTS-SETUP.md`,
  `SANDBOX-POLICY.md`, `COST-MANAGEMENT.md`, `AGENT-IDENTITY.md`, plus `docs/planning/README.md`.

**A test greps installers and `docs/**` for an in-clone launcher path and fails on any hit outside a
clearly-marked historical/migration section** (§14 T-P4-1) — the same shape as the FR4 guard.

**FR31 — the invariant at the cron entry itself.** The emitters produce, verbatim, above the sync entry:

> `# This entry runs no agent, launches no model, and makes no decisions — it is not a human cron role.`

and the syncer's own header states the same. A reviewer reading only the crontab can tell why the entry is
not a governance violation. **AD-7's emitters are the single place this text is produced** — it is not
duplicated into docs by hand.

**A new crontab entry is an operational obligation on every machine** (ADR §3.3). Its schedule is Q2.

### 12.3 The AD-2 residual, as a named deliverable (FR6)

FR6 requires *a written statement of the residual that matches measurement*, and AD-2 requires that
statement be part of the deliverable. Bound: the residual sentence (§1) plus the per-clone table (§13)
land in **`docs/SANDBOX-POLICY.md` §2** — which already carries the honest "current reality this policy does
*not* yet describe" framing and the measured posture table (`sed -n '39,64p' docs/SANDBOX-POLICY.md`) — and
are re-measured at implementation time. **A residual that overstates the protection is worse than none**
(AD-2). The measurement to attach is TD-VF-038-4's write probe, re-run.

### 12.4 Component P — `.envrc` (FR14/AD-7): repoint, do not drop

Measured (TD-VF-038-11): `.envrc` is tracked, line 8 is `PATH_add bin`, line 13 exports `HOS_CONFIG_DIR`
from the file's own location.

- **`PATH_add` takes the execution root**, never the clone's `bin/`.
- **If the resolver reports `unmigrated`, add nothing.** Typing `hos-human` then fails with "not found" —
  the correct, loud failure — rather than silently running the source copy that must never be executed.
- **`HOS_CONFIG_DIR` (line 13) is unchanged.** It is a clone-relative value and correctly stays so; only
  the `PATH` entry moves. Conflating the two is an easy and damaging mistake.
- `.envrc` is per-clone and consumer-editable: ship the corrected form and name it in the migration steps.

---

## 13. P5 and P6 — the verification gate and the protection changes

### 13.1 Component Q — `scripts/framework/verify_exec_migration.sh` (P5; measured, not assumed)

AD-8's P5 is a **gate**, and a gate that is asserted rather than measured is not a gate. The script reports
per project and exits non-zero on any failure:

| Check | Method |
|---|---|
| No crontab entry names an in-clone launcher | parse `crontab -l`; compare each executed path against `hos_exec_root` |
| No systemd unit does | scan user + system unit files where readable; **report "could not read" as a failure, not a pass** |
| No `.envrc` does | scan each registered clone's `.envrc` |
| No doc step does | the Component O grep |
| No script does | grep `bin/**`, `scripts/**`, `bootstrap/**` |
| Currency check green | run Component H per project; require `CURRENT` |
| Sync marker healthy for a stated observation window | read each marker; require `state == ok`, `consecutive_failures == 0`, and `last_success_epoch` within the window |

**Unreadable ⇒ failure.** Per CLAUDE.md, a blocked read surfaces as `No such file or directory`, so
"absent" and "masked" are indistinguishable; a gate that treats them alike passes on the masked case. The
script must report *which* check could not be performed and why.

### 13.2 P6 — the per-clone protection table (FR13's required deliverable)

**Re-measured 2026-08-06 in this session** (commands in TD-VF-038-3, -4). This table MUST be re-measured
again at implementation time; it is not a historical record.

| Clone / role | Protection today (measured 2026-08-06) | What changes | After which **verified** step | Owner |
|---|---|---|---|---|
| **Human** | `.claude/settings.local.json` present (9,229 bytes, mtime 2026-08-05 23:31). `permissions.deny` = **45** entries incl. `Edit(./bin/**)` and `Edit(//…/Human/bin/**)`. `permissions.additionalDirectories` = 6 (`…/Worker`, `…/Overseer`, `…/.config/hos`, `…/.local/handoff/human`, `/tmp/claude`, `/tmp`). `sandbox.enabled=true`, `failIfUnavailable=true`, `allowUnsandboxedCommands=false`. `sandbox.filesystem.denyRead` includes `~/`; `allowWrite` = 8 entries incl. `/tmp`. **`sandbox.filesystem.denyWrite` is NOT present live** (the template has it — see below) | **Removal** of the two `bin/` deny rules (they would then protect a source-only directory and mislead); `additionalDirectories` and `sandbox.filesystem.{allowRead,allowWrite}` narrowed to exclude the execution root, install record, session registry, journal and state root; **marker subtree added to `allowRead` only** | **P5** | this change |
| **Worker** | **No `settings.local.json`.** No user-level or managed sandbox config (`/home/scott/.claude/settings.json` has no `sandbox`/`permissions` key; no `/etc/claude-code/managed-settings.json`). Write probe **into `$HOME`** succeeded; cross-clone reads succeeded (TD-VF-038-4). Cron executes `Worker/bin/hos-cron` unsandboxed under `--permission-mode bypassPermissions` (`docs/SANDBOX-POLICY.md:43-47`) | **Addition** of a posture — nothing to remove. Until it lands, AD-2's residual applies and relocation is hygiene, not a boundary | belongs to **#1146/#1183**; P2's generated Class-B settings is the vehicle | #1146/#1183 |
| **Overseer** | Identical to Worker: absent | Identical to Worker | as Worker | #1146/#1183 |
| **Consumer** (`CondoParkShare/{Worker,Overseer}`, live in the crontab) | Same shape; cron executes clone-internal launchers | Inherits P0–P6 as a framework property (FR34) through the same installer path | as HOS's own | this change |

**Two additions to AD-8's version of this table, both from measurement:**

1. **`sandbox.filesystem.denyWrite: ["__PROJECT_ROOT__/bin"]` exists in `contract/sandbox-policy.template.json`
   and is a *second* `bin/` protection AD-8's removal row does not name.** `docs/SANDBOX-POLICY.md:131-140`
   explains why it exists: `Edit(./bin/**)` blocks only the Edit tool, not a Bash-level write, and
   `denyWrite` is OS-enforced regardless of tool. **P6's removal set must therefore be three entries, not
   two** — and removing the OS-enforced one is a strictly larger change than removing the two advisory
   ones. → **TD-ESC-4** (architect).
2. **The live Human profile and the template already diverge** on this point (live has no `denyWrite`;
   template does), which is `docs/SANDBOX-POLICY.md` §4 item 7's *"live-vs-template reconciliation is not
   fully closed."* P6 cannot be executed against an assumed posture; it must be executed against a
   re-measurement.

**Q1 (interim mitigation for the measured Worker/Overseer exposure) is the human's and is not bound.** The
table has a row for it; whichever way it is ruled changes only whether an interim posture lands before P1.

---

## 14. Build order and PR split — AD-8's phases, preserved exactly

**No slice may start before every slice of its predecessor phase is verified by measurement.** This is
AD-8's rule, and it is the reason FR13 exists.

| # | Slice | Components | Phase | Depends on |
|---|---|---|---|---|
| S1 | Declaration + residual register + both guards + closure guard | A, B, C | **P0** | ESC-A ruled (membership) |
| S2 | Installer: retire the second copy path; fix the false comment | C2 | **P0** | S1 |
| S3 | The resolver library + the no-second-derivation guard | D | **P1** | **Q4 ruled**; P0 verified |
| S4 | Copy-on-install (staged + swapped) + state-root hardening | E | **P1** | S3 |
| S5 | Install record + torn-install sentinel | F | **P1** | S4 |
| S6 | Human-only gate + the no-automated-copy guard | E-gate, G | **P1** | S4 |
| S7 | Currency check (self-verify → integrity → currency → 4 outcomes) | H | **P2** | P1 verified |
| S8 | Settings generator + Class-A template + Class-B wiring | I | **P2** | S7; **TD-ESC-1 ruled**; coordinated with #1146 |
| S9 | Marker + outbox libraries | J | **P3** | P2 verified |
| S10 | Session registry library | K | **P3** | S9 |
| S11 | Syncer: guard → state machine → clocks → recovery | M | **P3** | S9, S10 |
| S12 | Launcher edits: registry-driven root, no `exec`, register, order | L, M2 | **P3** | S10, S11; **TD-ESC-2/3 ruled** |
| S13 | Sync cron entry + the FR31 invariant comment | O (partial) | **P3** | S11; **Q2 ruled or the refuse-if-unset seam accepted** |
| S14 | Self-location shim (warn mode) | N | **P4** | P1 verified |
| S15 | Emitters + the ten docs + `.envrc` | O, P | **P4** | S3 |
| S16 | P5 verification gate script; run it | Q | **P5** | S7, S13, S15 |
| S17 | Per-clone protection changes | R | **P6** | S16 **green, measured** |
| S18 | Issues filed (§15.2) | — | any | — |

**PR-size split** (`docs/PR-SIZE-POLICY.md`: >15 files or >10 commits → split; 25 hard ceiling). This work
touches five protected surfaces and well over 25 files, so the whole thing is human-gated regardless of
tier and must split. Recommended seams, each independently green:

- **PR-A (P0):** S1, S2 — declaration, guards, ship-set correction. **Zero behaviour change.**
- **PR-B (P1):** S3–S6 — resolver, copy, record, human gate. *In-clone launchers keep working, untouched.*
- **PR-C (P2):** S7, S8 — currency check + settings generation. **The phase that makes P1 a boundary for
  Worker/Overseer** (AD-2), and the one coupled to #1146.
- **PR-D (P3):** S9–S13 — the syncer and everything it needs. The largest slice; split further at the
  library/consumer seam (S9+S10 | S11 | S12+S13) if it exceeds the ceiling.
- **PR-E (P4):** S14, S15 — migration detection, emissions, `.envrc`, docs.
- **PR-F (P5/P6):** S16, then S17 **as a separate PR** — AD-8 and FR13 explicitly prohibit bundling a
  protection change with the mechanism.

**The pivot slice is S8 (Component I).** Per AD-2, until the per-role posture exists, P1's relocation is a
file move for two of three roles. A build that ships PR-B and stops has *not* delivered FR1 for Worker or
Overseer and **must not be documented as having done so.**

---

## 15. Test plan, escalations, issues, and startup-gap analysis

### 15.1 Test plan

Conventions follow this repo's: pure logic → `tests/framework/` or `tests/oversight/` importing directly;
shell → drive the real script as a subprocess in `tmp_path`; framework invariants → `tests/framework/`
(`ls tests/` → `automation/ framework/ oversight/ spec_374/`). **Nothing requires a live model, network, or
authenticated `gh`.** Every test below is hermetic against a synthetic state root
(`HOS_STATE_DIR=<tmp_path>`) and a synthetic clone.

| id | Slice | Assertions |
|---|---|---|
| **T-P0-1** | S1 | Guard (a) listed→exists; guard (b) **every file under `bin/` is listed** — the FR4 test that does not exist today; adding a new file to `bin/` without listing it **fails**. |
| **T-P0-2** | S1 | Guard (c): a declared file referencing `$REPO_ROOT/x` where `x` is in neither A nor B **fails**, with the referrer, line, target and remediation in the message; the same reference registered in B with a reason **passes**; registered with an **empty** reason **fails**; `git -C "$REPO_ROOT"` (data access) does **not** trip the guard; a `$REPO_ROOT`-rooted **prompt/instruction** path (`hos-cron:917` shape) **does**. |
| **T-P0-3** | S2 | No `cp` of a `bin/` file exists in `hos_install.sh` outside the declaration loop; a consumer install contains `hos-worker`, `hos-overseer`, `hos-suspend`. |
| **T-P1-1** | S3 | **No second derivation:** a grep of A's members + both installers + four launchers + `.envrc` + `docs/**` for an `HOS_STATE_DIR`-rooted or `/exec/` literal returns hits only inside `hos_paths.sh`. `hos_project_for_clone` returns exit 3 (not a guess) on two matching `projects.conf` entries. `hos_exec_root ""` exits 2. |
| **T-P1-2** | S4/S5 | Copy wholeness: every declared file present, **mode preserved**; a source file missing from the declaration set makes the install **fail**, not warn. A staged-but-not-swapped tree is **never** reachable as an execution root. `hos_exec_root_status` returns `unmigrated` when `INSTALL-IN-PROGRESS` exists, even with a fully-populated directory. Record rows round-trip; `record.meta.tsv` carries all eight keys; a group-writable state root that cannot be hardened makes the install **refuse**. |
| **T-P1-3** | S6 | **FR2, executable:** change a declared source file → execution copy byte-identical (sha + mode) → currency reports STALE → only the install changes it. **AD-4 negative:** a grep of `.github/workflows/**`, `bin/**`, `scripts/**`, `bootstrap/**` (minus the installer) and `.claude/agents/**` for the copy entry point returns **zero** hits. A non-tty invocation of the copy step **refuses**. |
| **T-P2-1** | S7 | All four outcomes: CURRENT silent/exit 0; STALE (committed source moved) loud + outbox, `_stale_response()` selects run vs. refuse; CURRENCY-UNKNOWN (clone absent / not a git tree) warns and **proceeds**; UNRECOGNISED (byte changed, mode changed, row missing, extra file, torn record) **refuses**, exit 5, escalates. **Self-verify first:** a tampered checker refuses **before** verifying anything else. **ESC-B's shape:** a copy hand-set to a prior committed revision classifies **UNRECOGNISED**, not STALE — the ADR's stated correct behaviour and the one whose FR9 acceptance criterion is unsatisfiable as written. **An uncommitted working-tree edit does NOT produce STALE.** |
| **T-P2-2** | S7 | **FR8, the load-bearing negative:** after a detected drift of each class, every file under the execution root is byte- and mode-identical to before. Lexical guard: no write primitive with an execution-root destination appears in the file. |
| **T-P2-3** | S8 | Generation is byte-deterministic for the same (template, role, substitutions). A surviving `__PLACEHOLDER__` ⇒ **hard failure, nothing written**. **The four required-content assertions** (§8.2) each cause a **refusal** when violated — marker subtree absent from `allowRead`; marker subtree present in `allowWrite`; marker subtree present in `additionalDirectories`; any of exec root / install record / session registry / journal / auth / state root present in any of the three lists. A hand-edited generated file is reported as **diverged with a warning**, never fail-closed (AD-14). |
| **T-P3-1** | S9 | Marker: each of the five states produces every mandatory field; `reason` absent in a `skipped`/`failed`/`quarantined` marker is detected as **malformed**. Atomicity: a reader sampling across many writes never observes a partial document. Counters and clocks are consistent with the outcome in the same document. |
| **T-P3-2** | S9 | Outbox: record-then-deliver-then-mark; with delivery forced to fail, the record persists `delivered: false` and is **printed at the next launcher start**. No path attempts, fails, and discards. |
| **T-P3-3** | S10 | Registry: multiple concurrent holders in one clone; release on normal exit, on `INT`/`TERM`, and — via reclamation — after `kill -9`; an entry with no `pid` is treated as **held** (skip), not reclaimed; every reclamation writes an outbox record. |
| **T-P3-4** | S11 | **FR18 lexical guard:** `rebase`, `reset` (outside RESTORING), `--force`, `--force-with-lease`, `stash`, `checkout <branch>`, `clean` absent from the sync path. **AD-12 cleanliness:** a clone with dozens of untracked files **syncs**; one with a tracked modification **skips**. |
| **T-P3-5** | S11 | **The state machine.** Kill at each of PRECHECK/FETCHED/JOURNALLED/MERGING/VERIFYING: the journal is durable and correct where one should exist and absent where none should. Induced merge failure ⇒ tree at `pre_commit`, no file differs except pre-existing untracked paths, outcome recorded **failed**. Induced verify discrepancy ⇒ RESTORING and recorded **failed**, never success. Failed restore ⇒ **QUARANTINED**, journal retained, **no further git operation**, re-escalates each invocation, recovery attempted **at most once**. Recovery path: a pre-existing non-terminal journal ⇒ auto-restore **and refuse new work** in the same invocation. |
| **T-P3-6** | S11 | **AD-15:** the syncer under each simulated marker variable performs **zero** git operations and names the variable. With `HOS_CYCLE_ID` set but no CLI marker, it **runs** (the self-refusal regression). |
| **T-P3-7** | S11 | **AD-12's bound negative — the regression that already happened:** after an induced failure the next scheduled invocation **attempts again**; it does not report "skipped, last synced Ns ago". A skip advances neither clock. A success resets both counters. Latching stops attempts after the configured count and keeps escalating. |
| **T-P3-8** | S12 | Launchers: startup order is sync-then-register (a registered lock at sync time would deadlock); the CLI runs as a **child**; exit status propagates including `128+N`; `INT`/`TERM` forward and the entry is released; `REPO_ROOT` resolves from `projects.conf`, and a launcher started from an unregistered directory **refuses** rather than guessing. |
| **T-P4-1** | S14/S15 | Shim: in-clone execution with a valid execution root ⇒ still runs **and** warns naming both paths **and** writes an outbox record; with no execution root ⇒ **silent**. Grep: no emitted or documented crontab line names an in-clone path outside a marked historical section. `.envrc` puts the execution root on `PATH` when migrated and **nothing** when not; `HOS_CONFIG_DIR` is unchanged. The emitted sync entry carries the FR31 invariant comment. |
| **T-P5-1** | S16 | The gate fails on each seeded condition (an in-clone crontab entry; a non-`CURRENT` currency result; a marker with `consecutive_failures > 0`; an **unreadable** unit directory). It passes only when every check is affirmatively measured. |
| **T-MANUAL** | — | Not hermetic, and must be performed by a human: one real install on a real machine; one real cron sync cycle; the AD-10 (5) fetch-inertness confirmation with its result recorded; the AD-14 unknown-top-level-key empirical check; the `docs/SANDBOX-POLICY.md` §4 item 7 double-slash glob-semantics check (unresolved and load-bearing for the generated posture's path entries); and the P6 re-measurement of all three clones. |

### 15.2 Escalations and issues

**Escalations (technical-design → other roles). None of these are mine to settle.**

| id | To | Question | Blocks |
|---|---|---|---|
| **TD-ESC-1** | **architect** | **TD-VF-038-2 (HIGH).** AD-14 specifies "generate `.claude/settings.json` per role from a template," but FR26's marker read-grant and AD-2's negative rule are expressible **only** in `.claude/settings.local.json` / `contract/sandbox-policy.template.json` — a *different* file, already built, already protected, and **owned by #1146**. Confirm the two-payload-class factoring (§8.2), and rule the ownership boundary: does this change *author* Class B, or *consume and extend* #1146's template with two entries? AD-2 makes Class B a prerequisite of FR1 for two of three roles, so this is on the critical path, not a detail. | Component I, slice S8, and PR-C |
| **TD-ESC-2** | **architect** | **TD-VF-038-1 (HIGH).** AF-038-2 concluded relocation is "path-safe"; that holds for `hos-cron`/`hos-suspend` only. `hos-human:22`, `hos-worker:10`, `hos-overseer:8` resolve `REPO_ROOT` from `$(dirname "$0")/..` and **break on relocation**. Confirm the fix: they become registry-driven, AD-3's resolver gains a clone→project reverse-resolver (`hos_project_for_clone`, exit 3 on ambiguity), and the launchers gain `--project`. | Components D, L; slices S3, S12 |
| **TD-ESC-3** | **pm-agent** | User-visible session-start change, **extending** AD-10 (3)'s existing `exec`-removal notification: beyond exit codes and signal handling, an interactive launcher becomes **cwd-sensitive** (it resolves its project from the current directory) and **refuses to start** when the project is ambiguous or unregistered. Confirm this is acceptable operator-facing behaviour, or specify an alternative. | Component L |
| **TD-ESC-4** | **architect** | **AD-8's P6 removal set is incomplete.** The per-clone table names `permissions.deny`'s two `bin/` rules and `additionalDirectories`, but `contract/sandbox-policy.template.json` also carries `sandbox.filesystem.denyWrite: ["__PROJECT_ROOT__/bin"]` — the **OS-enforced** `bin/` protection (`docs/SANDBOX-POLICY.md:131-140`), and one the live Human profile does **not** yet have. Confirm P6's removal set is three entries, and rule whether removing an OS-enforced protection changes P6's sequencing or its approval requirement. | Slice S17 |

**Issues to file — separately, not folded in.**

| id | Title | Basis |
|---|---|---|
| **ISSUE-1** | `harden: $HOS_STATE_DIR is created group-writable (measured 0775); create at 0700 and refuse to proceed if it cannot be hardened` | TD-VF-038-5. A group-writable state root makes every boundary beneath it advisory. |
| **ISSUE-2** | `move hos-cron:484's installation-token mktemp out of $_HOS_DIR's root into a never-granted auth/ subtree` | ADR §3.4 item 2 / AD-13 (ii). Folded into P3 (§10) **and** filed, so it survives a descoping. |
| **ISSUE-3** | `retire bootstrap/hos_repo_sync.sh's /tmp/hos-repo-sync state (session-writable) once the syncer is verified; remove the old path rather than leaving it behind` | ADR §3.4 item 3 / AF-038-5, re-measured (`hos_repo_sync.sh:33`; `/tmp` is in the Human profile's `additionalDirectories` **and** `allowWrite`). |
| **ISSUE-4** | `scripts/oversight/record_agent_model.py executes from the clone via the settings hooks block, and scripts/oversight/** is not a protected surface` | ADR §3.4 item 1 / AD-14 residual. Pre-existing; the template does **not** close it. Confirmed: `protected_surfaces.txt` lists only `scripts/oversight/gates/**`, `run_validators.sh`, `validators/schema.py`. |
| **ISSUE-5** | `SANDBOX-POLICY §4 item 7: double-slash vs single-slash permission-glob semantics are unverified, and the generated posture's path entries depend on the answer` | `docs/SANDBOX-POLICY.md:216-227`. The live profile uses `//home/...`; template substitution produces `/home/...`. Route to the #1146 chain; **do not guess at security-relevant glob semantics.** |
| **ISSUE-6** | `hos_install.sh:1822's "Covers: all of bin/ (incl. bin/lib/)" comment is false today` | TD-VF-038-6. Fixed by S2; filed so the falsehood is on the record independently of this design landing. |

### 15.3 Startup-gap analysis and affected sign-offs

*Should any of this have been settled in an initial technical design, before code was written against it?*

- **This is a new mechanism, not a correction to already-built work.** No execution root, no install record,
  no syncer, no session registry, no marker exists. Every finding here was caught **in design, before any
  build**, so **all prior sign-offs stand** and no already-approved code is left unaudited against a changed
  contract.
- **The one late-correction-shaped item is TD-VF-038-2**, and it is genuinely startup-gap-shaped: AD-14
  specifies authoring a template that **already exists** (`contract/sandbox-policy.template.json`, landed
  2026-08-05 under #1183/#1185, one day before ADR-038), is already protected, and belongs to #1146.
  Building AD-14 literally would have produced a **second, competing template** for the same security
  posture — the classic duplicate-authority defect. **Affected-sign-offs analysis:** the sign-offs on
  #1183/#1185 that shipped the template **stand** — nothing about them is invalidated; what changes is that
  ADR-038's AD-14 must be re-pointed at the existing artifact rather than creating a rival. No code has been
  written against AD-14, so nothing is orphaned. This is recorded as **TD-ESC-1** rather than absorbed.
- **Two upstream acceptance criteria are known-unsatisfiable and are already escalated by the architect**:
  **ESC-B** (FR9's stale test — a copy hand-set to a prior revision is correctly UNRECOGNISED under the
  install-record anchor, not STALE) and **ESC-C** (FR18 vs. FR20). T-P2-1 and §9.3 are written against the
  ADR's binding, not the requirement text, and **a correct implementation will fail the FR9 and FR20
  acceptance criteria as currently written.** `pm-agent` must restate both before the test suite can be
  reconciled with the requirements — ADR §5 (3) already makes this a clearance condition.
- **One adjacent coupling to watch:** #1201 (v0.7.2) is to be re-scoped as this design's implementation or
  closed as superseded; #1146/#1183 own the Worker/Overseer posture that AD-2 makes load-bearing for FR1 and
  that TD-ESC-1 now makes load-bearing for Component I. **P6 depends on that work for two of three roles;
  this design does not absorb it and MUST NOT be read as delivering it.**

---

## Human Review Required

This document authors the implementation contract for a change to the trust boundary around what cron
executes as the user, unsandboxed, so per my role I self-flag.

**RISK: MEDIUM–HIGH, and the direction matters.** The design *reduces* standing risk — it closes a path from
an agent working-tree write to unsandboxed execution that I measured as open in this very session
(TD-VF-038-4: a write probe into `$HOME`, the candidate execution-root parent, **succeeded** from inside a
sandboxed autonomous Worker cycle). Residual risk is concentrated in five places. **(1) FR8/AD-6:** a
currency check that self-heals from repo source rebuilds the exact escalation path the design removes, and
it is the convenient thing to implement — §8.1 prohibits it structurally, with a lexical guard and a
byte-identity test, and T-P2-2 is the test that must never be weakened. **(2) AD-2, sharpened by
TD-VF-038-2:** the enforcement half lives in a file this ADR does not name and another issue owns; if
Component I ships as AD-14 literally reads, the relocation is a file move documented as a security fix —
the worst outcome available here. **(3) AD-8/FR13:** removing the Human clone's `bin/` protections before
the P5 gate is *measured* opens the path for real, and TD-ESC-4 shows the removal set is larger than the
ADR's table states. **(4) AD-1/ESC-A:** shipping "all of `bin/`" satisfies every stated FR4 test while
leaving the token minter and the cron prompt file executing from an agent-writable clone. **(5)
TD-VF-038-1:** the interactive launchers break outright on relocation, so a P1 that copies them without
Component D's reverse-resolver produces a migration that appears to succeed and leaves three launchers
non-functional.

**CONFIDENCE: HIGH** on everything I re-measured this session with the commands recorded inline: the six
`bin/` launchers' root-resolution and `exec` lines; `hos-cron`'s `projects.conf` resolution, state root,
lock reclamation, token mktemp and clone-resident invocation set; `hos_repo_sync.sh` in full (unconditional
state write, `/tmp` default, `--porcelain` gate, `pull --ff-only`, `grep -o` state read, the atomic-write
precedent); the ship-set list and the `hos-human` second copy path; the installer's `_sha256`,
`.hos-manifest` schema-v2 rows, settings-merge block, crontab emissions, and `</dev/tty>` confirmation
idiom; `protected_surfaces.txt` in full; `test_consumer_framework_files.py`'s assertion set; `.envrc`; the
live crontab; the per-clone `settings.local.json` state including the `sandbox.filesystem` four-list schema;
`contract/sandbox-policy.template.json`'s keys and placeholders; `docs/SANDBOX-POLICY.md`; the live
agent-session environment markers; and the `$HOME` write probe. **LOWER** on: whether Claude Code's
permission-glob matcher treats `//path` and `/path` alike (`SANDBOX-POLICY` §4 item 7 — ISSUE-5, and I did
not guess); whether the CLI tolerates unknown top-level settings keys (AD-14 refuses to assume and so do
I); whether `git fetch` is *provably* inert with respect to a concurrent session (§9.6 ships the config
escape defaulted **off** rather than asserting it); and anything about consumer deployments beyond the one
consumer project visible in this machine's crontab.

**BLAST RADIUS:** what cron executes as the user, unsandboxed, on every HOS machine and every consumer
machine running the pipeline; the sandbox posture of all three roles; the session-start path of all four
launchers (exit codes, signal handling, and now cwd-sensitivity); the installer's ship-set, its generated
artifacts, and its emitted setup instructions; and the crontabs of every existing installation, which
operators must migrate by hand. Five protected surfaces (`bin/**`, `bootstrap/**`, `scripts/framework/**`,
`contract/**`, and `.claude/agents/**` if a launcher contract is documented there), so the implementation PR
is human-approved at merge regardless of computed tier. A migration executed out of order (AD-8) affects
running production installations, not only new ones.

**Change classification: STRUCTURAL.** It specifies a new trust boundary, a new installer obligation
(copy-on-install, an install record, per-role settings generation), a new runtime component (a journalled
syncer), a new lock contract for interactive sessions, a new cron entry, a user-visible change to
session-start behaviour, and a new user obligation (crontab migration). Per the CORE product-boundary
checkpoint I escalate rather than write through it: **the four TD-ESC items above go to `architect` and
`pm-agent` before this design binds.**

**This document is not a clearance to build, and it is not the merge-time human approval the implementation
PR will require.** Per ADR-038 §5, a `coder` is cleared only after (1) the human rules **ESC-A**; (2) the
human rules **Q1–Q6** — noting **Q4 and Q1 cannot ship deferred**, and that §4 here ships Q2/Q3/Q6 as
present-but-unset seams that refuse or report rather than guess; (3) `pm-agent` restates **ESC-B** and
**ESC-C**, whose current acceptance criteria a correct implementation will fail; and (4) the **P5
verification gate is measured** before any P6 protection change. To that list this document adds
**TD-ESC-1…4**.

**Next step:** `architect` review of this DRAFT 1 — in particular **TD-ESC-1** (the two-payload-class
factoring and the #1146 ownership boundary, the one finding that changes the component set) and
**TD-ESC-2** (the launchers are not relocatable as written) — then, only after the human rulings above, a
`needs-ai` issue carrying §14's build order and PR split.
