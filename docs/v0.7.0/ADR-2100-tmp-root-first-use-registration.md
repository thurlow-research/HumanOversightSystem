# ADR-2100: Register a role temp dir before an untrusted writer can populate it. One shell export site, install-time pre-registration, a machine-copy wrapper for non-launcher sessions, a closed exact-name tool allowlist, and the persistent-refusal escalation delivered by #1928's condition primitive. The foreign-project guard is unchanged

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-5, AD-8 and AD-10 bind `technical-design`. AD-6, AD-7 and AD-9 are **PROVISIONAL**: each is drafted on the recommended option and names what changes under the alternative. REQ-5 (the guard) is not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-15
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2100 (follow-up to #2054 / PR #2061) · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice except S1 lands on protected surface: `bin/**` (`protected_surfaces.txt:26`), `bootstrap/**` (`:27`), `scripts/framework/**` (`:28`) and `CLAUDE.md` (`:19`). The human gate therefore applies whatever tier is computed.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2100-tmp-root-first-use-registration.md` (VF-1 to VF-8, REQ-1 to REQ-9, ESC-1 to ESC-4). Also `bootstrap/lib/hos_tmp_root.py`, `bin/hos-cron:376-391`, `bin/hos-human:113-127`, `scripts/framework/run_tests_inner_loop.sh:55-95`, `scripts/framework/install.sh:254-380`, `bootstrap/hos_install.sh:1723-1740`, `bootstrap/hos_bootstrap.sh:77-122`, `contract/sandbox-policy.template.json:155-185`, `scripts/automation/lib/cycle_log.py`, `tests/oversight/test_run_validators_preserves_gate_results.py:47-49`, `docs/v0.7.0/TECHNICAL-DESIGN-2054-tmp-quota-hygiene.md:697-705`, `docs/v0.7.0/ADR-1928-next-actor-assignment.md` (AD-2, AD-7, S6), `docs/CRON-SETUP.md:418-432`, `docs/SANDBOX-POLICY.md:175-200`, `CLAUDE.md:376`, and the machine-local `~/.config/systemd/user/claude-rc.service` and `~/Code/HumanOversightSystem/bin/claude-role` (read only).
**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S3 (the allowlist is a security guard's input set) and S4b (a new unsandboxed execution path for systemd units). `privacy-reviewer` is mandatory on S2 (new path-bearing audit fields). `reliability-reviewer` is mandatory on S2 (it rewrites the launch-time block of every cron cycle and every human session).
**Explicitly does NOT re-litigate:** the trust registry's location, format and authority; the reaper's delete-authority rule (registered path, role and inode only); `mark --reviewed` as the human's explicit adoption step; `HOS_TMP_ROOT` defaults and the `config.sh` grammar; #1928's attention-pass placement, counter or dedup design; #1146.

---

## 0. Verification findings (working tree at `52caa6f7d`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `hos_tmp_root.py:83-86` (`HOS_ONLY_RE`, `_PROJECT_NAMES`), `:466-485` (`adoption_problems`), `:538-542` (refusal before any chmod: the only side effects before it are `_make_dirs_0700(root)` and the `mkdir` attempt that hits `FileExistsError`). `bin/hos-cron:380-391` falls back and writes `cycle-tmp-root-fallback`. The latest event, `audit/log/2026/10/2026-10-15T090501Z-cycle-tmp-root-fallback-e7b78baa72ee.json`, names `'percommit-2054'`.
- **VF-2 CONFIRMED.** `bin/hos-human:120-127` prints to stderr only and writes no event.
- **VF-3, VF-5 accepted as stated.** I did not re-run the birth-time or grep evidence. Nothing in this ADR depends on who the writer was: every decision is written for an unknown first writer.
- **VF-4 CONFIRMED.** `CLAUDE.md:376`, `CRON-SETUP.md:422-428`, `SANDBOX-POLICY.md:185-195` all show static `Environment=` exports. The live `claude-rc.service` exports `TMPDIR` and `CLAUDE_CODE_TMPDIR` statically and its `ExecStart` is `~/Code/HumanOversightSystem/bin/claude-role`, which runs no resolver.
- **VF-6, VF-7, VF-8 CONFIRMED.** `registry_path()` uses the passwd home (`:136-137`, `:255-260`). `cycle-start` is at `bin/hos-cron:1946`.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): REQ-1 as worded cannot be met by a sandboxed caller, and is not meant to be.** The trust registry is under `~/.local/state`, which no sandbox may read (`sandbox-policy.template.json` denies `__HOME__/` and re-allows only `.local/bin` and `.local/share`, `:163-164`). Inside a sandbox, `read_registry` sees `ENOENT` (masked) and returns `[]`, so every existing role dir looks unregistered, and `register()` cannot write. That is why `run_tests_inner_loop.sh:63-69` first trusts an inherited `HOS_TMP_DIR` through `check-dir` (owner, mode 0700, not a symlink, not in the clone) **without** a registry lookup. That design is correct: the trust anchor is that an *unsandboxed launcher* registered the dir and then exported `HOS_TMP_DIR`. The consequence is that REQ-1 applies to code that **selects and exports** a role dir from outside a sandbox. Code that consumes `HOS_TMP_DIR` inside one does not need to call the resolver. It also means a **static** `HOS_TMP_DIR` export in a systemd unit (the `SANDBOX-POLICY.md:191-193` example) defeats the anchor: the inner loop then trusts a dir nobody registered. AD-1 and AD-7 close this by removing every static export (AM-1).

**AF-2 (HIGH): pointing a systemd unit at a clone's resolver adds an unsandboxed execution path for code an agent can write.** ESC-2(a) as drafted puts `ExecStartPre=python3 <clone>/bootstrap/lib/hos_tmp_root.py …` in a user unit. The sandbox grants write access to all three clones (`sandbox-policy.template.json:172-176`) and denies writes only to the clone's `bin/` (`:182-183`). `bootstrap/**` is therefore writable by a sandboxed agent in its working tree. The protected-surface gate stops it merging, not editing a local file. A unit with `Restart=always` would then run that edited file unsandboxed on the next restart. The operator has already guarded against this: `claude-role` sits outside every clone "so the agent can neither read nor modify it". `tmp_reaper.py` follows the same rule, as a machine copy at `~/.local/share/hos/` that the operator schedules (`hos_bootstrap.sh:77-122`), and `.local/share` is readable but not writable from a sandbox. AD-7 therefore requires a **machine copy** for anything a unit runs, and ESC-2 is re-posed with that constraint.

**AF-3 (MEDIUM): `semgrep-mcp` comes from HOS's own static-analysis validator, not from an MCP server.** `tests/oversight/test_run_validators_preserves_gate_results.py:47-49`: "semgrep (run by the static-analysis validator) creates `$TMPDIR/semgrep-mcp` at import time and nothing in its environment suppresses that." All three observed names come from tooling every HOS role runs: Node and Claude Code (`node-compile-cache`), Claude Code (`cc-socks`), and `run_validators.sh` → semgrep (`semgrep-mcp`). That puts all three inside REQ-4's "HOS and its required tooling" (AD-6).

**AF-4 (MEDIUM): the fallback event mislabels its role and carries no cycle identity.** `bin/hos-cron:390` passes only `reason=`. `cycle_log.log_event` defaults `"role": "worker"`, so an overseer fallback would be recorded as `role=worker`. The live event confirms the shape: `{"event","reason","role":"worker","timestamp"}`, with no `project` and no `cycle_id`. Nothing can join a fallback to its cycle. AD-2 fixes this along with REQ-8.

**AF-5 (MEDIUM): `cycle-start` is written after the cheap-skip exits.** `:1946` is reached only after `:1310`, `:1343` and `:1364` (ADR-1928 AF-1). A REQ-8 field placed only on `cycle-start` is absent for every cheap-skipped cycle. That is acceptable because those cycles do almost nothing under `TMPDIR`, but the failure path must be recorded unconditionally. The fallback event already is, at `:390`, before any exit (AD-2).

**AF-6 (MEDIUM): the resolve-and-export block is written three times, twice identically.** `bin/hos-cron:380-391`, `bin/hos-human:120-127` and (with a different precedence) `run_tests_inner_loop.sh:63-95` each run the resolver, run it again for the reason, strip the prefix and sanitise. REQ-7 and REQ-8 change two of the copies. REQ-2's wrapper would add a fourth. D41 requires one site (AD-1).

**AF-7 (LOW): REQ-7 is partly met already.** For the two refusals a human can fix (adoption, `:488-498`; re-point, `:351-358`) the reason line already embeds the remedy and `hos-human` prints it. The real gaps are no audit event, and no statement that the command must run unsandboxed. Other refusal classes (symlink, wrong owner, inside the clone) carry no remedy, and need none beyond the reason.

**AF-8 (LOW): the alternative of "use a fresh sibling dir when the role dir is refused" is closed by the sandbox.** The template grants exactly `__HOS_ROOT__/.tmp/__ROLE_DIR__` (`:162`, `:177`). A `Worker-2` dir would not be writable from sandboxed Bash, and `gen_sandbox_config.py:398-420` pins the root. This is recorded so it is not re-proposed.

**Reuse search (CLAUDE.md item 1).** I searched `bin/`, `bootstrap/`, `scripts/` and `scripts/automation/lib/` for an existing export helper, a unit wrapper, an install-time registration step, and a machine-copy installer.
- Found: `bootstrap/lib/hos_tmp_root.py resolve --create`, the single decision site. It is reused unchanged except for AD-4's message and AD-6's allowlist.
- Found: `hos_bootstrap.sh install_tmp_reaper` (`:77-122`), the machine-copy pattern AD-7 copies, including the `SHA256SUMS` corruption check.
- Found: `scripts/automation/lib/cycle_log.py`, reused for every new event.
- Found: ADR-1928 AD-7, the persistent-condition primitive. Its first registered key is already `tmp-root-fallback`, with the `mark --reviewed` command as its Action.
- Found nothing that exports the three temp variables from one place, wraps a non-launcher command, or registers role dirs at install.

---

## 1. Organizing principle

**Only an unsandboxed, HOS-authored, human-gated code path may decide that a dir is a role dir, and only the resolver decides it. Everything else either asks the resolver or consumes what a launcher exported.** Registration is pulled as early as possible, to the moment the root is created (install) and to the moment any session starts (launcher or wrapper). Nothing exports a role-dir path that the resolver did not return in that same process tree. When the resolver refuses, the refusal is recorded with full cycle identity and handed to #1928's condition primitive, which tells the human once. The guard's input set grows only by exact, producer-named tool names, and only on the human's ruling.

---

## 2. Decisions

### AD-1: One decision site, one export site. (BINDING; REQ-1, AF-1, AF-6, D41.)

- **Decision site (unchanged).** `bootstrap/lib/hos_tmp_root.py resolve --create` is the only code that creates, adopts or registers a role dir. `mark --reviewed` remains the only override. No other HOS file may `mkdir` a path under `HOS_TMP_ROOT`.
- **Export site (new).** `bootstrap/lib/hos_tmp_env.sh` defines one function, here called `hos_tmp_export <repo> <role>` (`technical-design` names it):
  - It runs the resolver once with `--create` and keeps stdout (the dir) and stderr (the reason) apart. Stdout and stderr are never mixed. A second run for the reason is allowed only if `technical-design` shows it is needed, and the resolver is idempotent, so it is harmless.
  - **On success** it exports `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` (all the role dir), and sets `HOS_TMP_SOURCE=resolver` and `HOS_TMP_ROOT_RESOLVED`.
  - **On failure** it exports nothing, sets `HOS_TMP_SOURCE=inherited`, and sets `HOS_TMP_REASON` to the last stderr line with the `hos_tmp_root: ` prefix removed, control bytes removed, and the line cut to 1200 characters (the current `:386-388` rule).
  - It never prints, never writes audit, and never returns non-zero to a `set -euo pipefail` caller. Logging is the caller's job, so each launcher keeps its own voice.
- **Callers.** `bin/hos-cron` and `bin/hos-human` source it and call it. AD-7's wrapper calls its machine copy. `run_tests_inner_loop.sh` keeps its own four-step precedence (`:55-95`) because it is a consumer inside a sandbox (AF-1). It is not an exporter of `CLAUDE_CODE_TMPDIR` or `HOS_TMP_DIR`, and it stays as it is.
- **Scope of REQ-1, restated (AM-1).** REQ-1 binds code that selects and exports a role dir from outside a sandbox. Sandboxed consumers trust `HOS_TMP_DIR` through `check-dir`, as today.
- **Invariant test (REQ-1 AC).** A static test over every shell and Python file under `bin/`, `bootstrap/` and `scripts/` asserts:
  - (1) no assignment or export of `CLAUDE_CODE_TMPDIR=` or `HOS_TMP_DIR=` outside `bootstrap/lib/hos_tmp_env.sh` (tests excluded);
  - (2) no `mkdir` or `os.mkdir`/`makedirs` whose argument mentions `HOS_TMP_ROOT`, `.tmp/` or a `ROLE_DIRS` value, outside `hos_tmp_root.py`;
  - (3) `bin/hos-cron` and `bin/hos-human` each call the export function exactly once.

  Anchors must not be first-occurrence string matches that a comment can satisfy (memory: "test anchors use first occurrence").

### AD-2: Every fallback carries cycle identity and the effective temp dir. `cycle-start` carries the effective temp dir. (BINDING; REQ-8, AF-4, AF-5.)

- **`cycle-tmp-root-fallback`** (`bin/hos-cron`, written where `:390` is now, before any exit) carries:
  - `role=$ROLE`, `project=$PROJECT` and `cycle_id=$HOS_CYCLE_ID`. Passing `role` explicitly fixes AF-4.
  - `tmpdir_source=inherited`.
  - `tmpdir=<inherited TMPDIR, or "unset">`.
  - `reason=` as today.
- **`cycle-start`** (`:1946`) gains `tmpdir_source=resolver|inherited` and `tmpdir=…`. Cheap-skipped cycles do not reach it (AF-5). That is accepted, because the fallback event already records every failing cycle unconditionally.
- **Path redaction.** In the two new `tmpdir` fields, a leading `$HOME` (passwd home) is written as `~`. The existing `reason=` field keeps absolute paths, because it carries the exact command the human must paste. Redacting it would break the remedy. This is `privacy-reviewer`'s to confirm on S2.
- **`cycle_log.py` docstring** lists the new fields. No code change in `cycle_log.py`.
- **Hand-off to #1928.** When ADR-1928 S6 lands, the `--observed tmp-root-fallback=<detail>` flag is derived from `HOS_TMP_SOURCE=inherited` and `HOS_TMP_REASON`, not by re-parsing the log line. Whichever of #2100 S2 and #1928 S6 lands second rebases onto the other's change to this block.

### AD-3: `hos-human` parity: the same event, the remedy, and the unsandboxed instruction. No escalation, and no in-launcher approval. (BINDING; REQ-7, AF-7. PROVISIONAL on escalation, ESC-3(ii).)

- On `HOS_TMP_SOURCE=inherited`, `bin/hos-human`:
  - writes **one** `cycle-tmp-root-fallback` event with `role=human`, `launcher=hos-human`, `tmpdir_source`, `tmpdir` and `reason`. There is no `cycle_id`, because an interactive session never has one (`bin/hos-cron:340-349`). The event name is reused, as REQ-7 asks, so that one query counts both launchers. The `launcher` field tells them apart.
  - prints the reason to stderr, followed by one fixed line: *"Run the remedy above in a normal terminal, outside any Claude session (it needs the unsandboxed registry). This session will use the inherited TMPDIR."*
- The audit write happens before `exec claude`, is best-effort (`|| true`), and never blocks the session.
- **Rejected:** having `hos-human` offer an interactive "review and type yes to mark" prompt. `hos-human` does run in the human's own terminal, but a launcher prompt trains a reflexive yes on a security step. `mark --reviewed` is deliberately a separate, typed command. This is not open to the agent side. If the human wants it, it is a new issue.
- **No REQ-6 escalation from `hos-human`** (ESC-3(ii) default). The human who launched the session is the reader.

### AD-4: The refusal message names the move, the mark command, and where to run them. (BINDING; REQ-6 content, REQ-7.)

`_remedy()` (`hos_tmp_root.py:488-498`) is reworded. This is a message change only. The blocker computation, the ordering and the exit code are untouched. The single line must carry:
- the absolute role-dir path;
- the blocking entries (the first five, plus a count, as today);
- the move alternative as a concrete command shape, `mv '<role_dir>/<entry>' <a dir outside HOS_TMP_ROOT>/`;
- the `python3 <abs>/bootstrap/lib/hos_tmp_root.py mark --repo <clone> --role <role> --reviewed` command, verbatim as today;
- the words "unsandboxed, in your own terminal".

The line stays a single line, because `bin/hos-cron` keeps only the last stderr line (`:385`). Existing assertions on the message in `test_hos_tmp_root.py` are updated in the same slice. Assertions on refusal, exit code and absence of side effects must not change (AD-5).

### AD-5: The guard, stated as invariants. Nothing in this ADR weakens it. (BINDING; REQ-5. Not open to any ESC or agent-side waiver.)

**Trust-boundary reasoning.** The guard defends one boundary: an **agent-writable `config.sh`** may point `HOS_TMP_ROOT` at someone else's directory, and adoption is the act that grants that directory two things:
- a chmod to 0700;
- **delete authority**: the reaper removes any top-level entry older than 24 h from a registered dir (TD-2054:701).

Registration is therefore an authority grant, and the guard is the rule that decides when it may be granted without a human. Two facts shape it:
- **What is outside the threat.** Sandboxed agents can already write anything into their own role dir (`sandbox-policy.template.json:177`). The guard is not a defence against an agent populating a HOS dir. An agent that does so can at most cause a refusal, which is a denial of service on itself that AD-9 makes visible.
- **What is the threat.** A *foreign* dir gets adopted. Every relaxation must therefore be judged by one question: *what would a foreign directory have to contain to be adopted, and what is lost if it is?*

**Invariants (each pinned by an existing test that must pass unchanged, plus new tests where noted):**
1. An unregistered dir is adopted without review only if every top-level entry is in the closed set (`HOS_ONLY_RE`, plus AD-6's names if ruled). No default-accept and no structural rule (ESC-1(B) is rejected below).
2. Any entry, allowlisted or not, that is a directory directly containing `.git`, `.claude` or `scripts` blocks adoption. **New tests:** each AD-6 name, as a dir holding each of the three, is refused.
3. A live (repo, role) key cannot be re-pointed without `mark --reviewed` (`:336-358`, `:516-520`).
4. A registered path whose inode differs is not registered (`:294-310`).
5. A different-letter-case dir is refused (`:525-526`).
6. A symlink, non-directory or non-owned root or role dir is refused (`:219-231`).
7. **Ordering.** Refusals 1 to 5 happen before any chmod, before registration and before the marker write. The only permitted earlier side effects are today's: creating a missing root (`:521`) and the role-dir `mkdir` attempt that fails with `FileExistsError` on a pre-existing dir.
8. Already-registered dirs are accepted whatever they hold (`:548-550`). This is unchanged, because it is what stops an agent locking its own role out.

AD-7's install-time pre-registration and wrapper call `resolve --create` only. They never call `mark` and never pass `force_mark`. A test pins that neither contains the string `--reviewed`.

### AD-6: Adoption policy: a separate, closed, exact-name set of tool entries, directory-only, still subject to the project-file check. (PROVISIONAL on ESC-1(A); REQ-4.)

- **Form.** A new constant in `hos_tmp_root.py`, for example `TOOL_ENTRY_NAMES = frozenset({...})`, separate from `HOS_ONLY_RE`, with one comment per name naming its producer:
  - `node-compile-cache`: Node's module compile cache under `os.tmpdir()`, enabled by Claude Code;
  - `cc-socks`: Claude Code's sandbox socket dir;
  - `semgrep-mcp`: semgrep, at import, run by `scripts/oversight/run_validators.sh` (AF-3).
- **Exact names only.** No prefixes or globs (`node-*`, `semgrep-*`). A new tool name is a reviewed one-line diff to a protected file, which is the point.
- **Stricter than the existing patterns.** A tool name is accepted only if `lstat` shows a **real directory**, not a symlink or a file. The existing `HOS_ONLY_RE` behaviour is left exactly as it is, so the existing guard tests pass unchanged (REQ-5 AC). The extra condition costs nothing, because all three producers create directories.
- **Invariant 2 applies.** Each tool name that is a dir directly holding `.git`, `.claude` or `scripts` blocks adoption.
- **`percommit-*` is not added.** I concur with pm-agent.
- **Trust reasoning for (A).** For (A) to adopt a foreign dir, that dir must sit at exactly `<HOS_TMP_ROOT>/<Worker|Overseer|Human|Local>`. Its every top-level entry must also be one of eleven HOS temp patterns or three tool-cache directory names, none holding project markers. Such a directory is itself somebody's temp dir. The worst loss is regenerable cache content older than 24 h. That is the same class of loss the existing `tmp*` and `pytest-of-*` patterns already accept. (B) has no such bound, as the requirements state: any non-git foreign folder with a role-dir name would be adopted, chmodded and reaped.
- **Under (C).** AD-6 is dropped, and S3 does not exist. Human and any freshly populated dir rely on AD-7 and AD-9 alone. `.tmp/Human` then stays refused until the human acts.

### AD-7: Non-launcher sessions: register at install, and launch through a machine-copy wrapper. No static role-dir exports anywhere in HOS docs. (PROVISIONAL on ESC-2; REQ-2, AF-1, AF-2.)

- **(b) Install-time pre-registration.**
  - **Where.** `bootstrap/hos_install.sh`, after `config.sh` is final, on **both** interactive and non-interactive paths. `scripts/framework/install.sh` runs only interactively (`hos_install.sh:1723-1729`), so it is the wrong site.
  - **What.** For each of `worker`, `overseer`, `human` and `local`, it runs `hos_tmp_root.py resolve --repo <target> --role <r> --create`.
  - **Failures.** A failure is printed with its remedy and is never fatal to the install. Under `--dry-run` it is skipped.
  - **Why all four from one clone.** The root and its four dirs are created together, which is exactly the VF-3 moment. A dir registered under another repo key is later accepted by each role's own clone without re-running adoption (`:544-547`). The resulting (installing clone, other role) keys are live but inert: no code resolves those roles from that clone. They are pruned when the clone disappears, and they count toward the 256-entry cap. This is stated, not hidden.
  - **Rejected: machine bootstrap as the site.** `hos_bootstrap.sh` knows no clone and no `config.sh`, so it cannot compute a root.
- **(d) Machine-copy wrapper.** This replaces the pm-agent's (a); see AF-2.
  - **What gets installed.** `hos_bootstrap.sh` installs, beside the reaper's machine copy in `~/.local/share/hos/`, a copy of `hos_tmp_root.py`, `hos_tmp_env.sh` and a small wrapper (here `hos-with-tmp`; `technical-design` names it). The same copy-and-checksum routine as `install_tmp_reaper` is used.
  - **What the wrapper does.** `hos-with-tmp --repo <clone> --role <role> -- <command…>` calls `hos_tmp_export` and then `exec`s the command. On refusal it prints the AD-4 line to stderr (the journal, for a unit) and execs **without** exporting. That is the same fail-open-without-export behaviour as `hos-human`. The availability of the human's remote-control channel outweighs reaper coverage of one dir, and nothing is ever exported that the resolver did not return.
  - **Unchanged invariant.** `hos_tmp_root.py` keeps its documented invariant that it never spawns a process (`:31`). The wrapper is shell.
  - **Docs.** `CLAUDE.md:376`, `CRON-SETUP.md:418-432` and `SANDBOX-POLICY.md:185-200` drop every `Environment=TMPDIR=`/`CLAUDE_CODE_TMPDIR=`/`HOS_TMP_DIR=` example for a role dir. They show instead `ExecStart=%h/.local/share/hos/hos-with-tmp --repo <clone> --role <role> -- <existing ExecStart>`, and `bin/hos-human` (or the wrapper) for a plain `claude`. The "one-time registration" paragraphs become "only needed if you cannot use the wrapper".
  - **Docs test.** No `Environment=` line in those three files assigns one of the three variables to a path under `.tmp/`.
- **Version skew (stated).** A unit's machine copy can lag the clone's resolver. Both write registry format v1, under the same lock, with the same keys. Skew can only make the two disagree on whether an unregistered dir is adoptable (AD-6), and the stricter copy wins in practice, because registration happens once. `hos_bootstrap.sh` refreshes the copies on each run.
- **The live `claude-rc.service` and `claude-role` are machine-local and are not edited by this build.** S4b's PR body carries the exact unit diff the human applies. That is an operational act for the human (§6).
- **Under (a) only.** Docs show `ExecStartPre=%h/.local/share/hos/hos_tmp_root.py resolve … --create` (the machine copy, never the clone's) and keep the static `Environment=` lines. AF-1's static-`HOS_TMP_DIR` hole stays open whenever the dir is deleted and recreated by a non-resolver writer. **Under (b) only.** Fresh installs are covered. Existing units and deleted-then-recreated dirs are not.

### AD-8: An unknown first writer gets one of two outcomes, adopt or refuse-and-escalate. No quarantine. (BINDING on the outcome set; REQ-3, ESC-4.)

- **Outcome (i).** Adopt and register: `resolve --create` succeeds, with today's code path.
- **Outcome (ii).** Refuse: the launcher falls back (AD-1), writes the AD-2 event, and passes `--observed tmp-root-fallback` to #1928's pass (AD-9).
- There is no third, silent outcome. After S2, every fallback carries cycle identity. After #1928 S6, every K-th consecutive one produces exactly one human item.
- **ESC-4: concur with rejection.** Moving entries into a `.hos-quarantine-<ts>/` inside an unregistered dir is a rename inside a dir whose ownership HOS has not established. That is precisely the side effect invariant 7 forbids. It would also turn the guard into a self-healing path that any `config.sh` edit could trigger against a foreign dir: rename its contents, then adopt and reap them. I recommend that the human confirm the rejection. It is not a decision I would take in the other direction under any circumstances short of a new threat model.
- **REQ-3 AC.** The mixed fixture (a `percommit-2054` dir plus a `node-compile-cache` dir) is refused under ESC-1 (A) and (C). It would be adopted only under (B), which is rejected. The test's "REQ-6 state change" half is asserted against the `--observed` hand-off until #1928 S6 exists, and against the filed item once it does (AM-3).

### AD-9: Escalation is #1928 AD-7's condition primitive. #2100 adds content, not a second filer. (PROVISIONAL on ESC-3(i); REQ-6.)

- **Ownership.** ADR-1928 AD-7 already binds: the counter per role-clone, K = 3, a marker-keyed fail-closed dedup, filing into the target milestone, auto-close after K clear cycles, a committed key registry whose first key is `tmp-root-fallback`, and an Action of the exact `mark --reviewed` command with the absolute clone path. That satisfies REQ-6's dedup, auto-close and duplicate-query rules by construction.
- **#2100's contribution (AM-2 to #1928).** The condition body must also carry:
  - the absolute role-dir path;
  - the blocking entries;
  - the AD-4 move alternative;
  - Who = "the human, unsandboxed, in your own terminal".

  The pass takes these from the `--observed` detail, which is `HOS_TMP_REASON` (AD-2), sanitised as today. The REQ-6 deterministic test (K-1, K, K+n, K clear) belongs in #1928 S6's suite, with a #2100 fixture.
- **Recommendation: no #2100 one-off.** I disagree with the requirement's fallback clause ("#2100 delivers a minimal one-off if #1928's primitive has not landed"). The reasons:
  - **(1) D41.** A second dedup-and-file implementation in `bin/hos-cron` would have to be deleted when #1928 S6 lands.
  - **(2) Double filing.** The one-off keys on a title prefix (the breaker idiom, `:2186-2206`) and #1928 keys on a body marker. Neither sees the other, so during any overlap both file a `needs-human` issue for the same condition.
  - **(3) A second unregistered key.** ADR-1928 AD-7 refuses unregistered keys precisely to avoid free-text conditions, and a hos-cron-local filer bypasses that registry.
  - **(4) The relief is not blocked on it.** The one live case is known and is in the human's hands now (§8 N-1). The interim visibility is S2's identity-bearing events.
- **If the human rules the one-off anyway (ESC-3(i) alternative).** It is S5′: a ≤3-file change to `bin/hos-cron` and its test, keyed on #1928's planned marker `<!-- hos-attention-condition v=1 key=tmp-root-fallback role=<role> project=<project> -->`, not on a title prefix. That way #1928 S6 adopts its open issue instead of duplicating it. It must be filed into the target milestone (ADR-1928 AF-2). #1928 S6 then carries the obligation to delete it.

### AD-10: Tests never write the real registry. The isolation is session-wide, and a guard proves it. (BINDING; REQ-9, VF-6.)

- **Default.** `tests/conftest.py` sets `HOS_TMP_REGISTRY_FILE` in `pytest_configure`, so the value is present before any test or fixture runs, to a session-owned path under the session temp dir. Subprocesses inherit it through `os.environ` and through `child_env()`.
- **Guard.** At session start, record the real registry's fingerprint (`lstat` presence, `st_ino`, `st_mtime_ns`, size and sha256) **if it is readable**. At session end, compare and fail the session on any change, naming the test-run window.
  - **Unreadable** (a sandboxed run sees `ENOENT`): the guard records "not observable" and passes. In that case the sandbox itself prevents the write.
  - The guard must not create the file or its directory.
- **Fix the leaking suite.** `tests/framework/test_hos_human_launcher.py` sets the override explicitly in the env it builds, rather than relying on inheritance. A fake `HOME` does not isolate, because `registry_path()` uses the passwd home.
- **Rejected:** making production `registry_path()` refuse the real path when `PYTEST_CURRENT_TEST` is set. That is test-awareness in a security module, and an environment variable an attacker can set.
- The stray `test_the_token_file_is_removed0` entry is pruned by `_live` on the next registration after its dir is reaped. No cleanup step.

---

## 3. Failure modes

| Failure | Behaviour | Direction |
|---|---|---|
| Resolver refuses (any reason) | No export. `HOS_TMP_SOURCE=inherited`. WARN plus a full-identity event. #1928 counts it. | Loud, never fatal |
| Resolver crashes (traceback) | As refused. The reason is the last line, sanitised. | Loud, never fatal |
| Export helper missing (partial install) | `source` fails. The launcher must treat this as refused and continue, never abort a cycle (`technical-design` pins the guard). | Fail-open on temp, loud |
| Install-time pre-registration fails | Printed with its remedy. The install continues. The first launcher retries. | Loud, non-fatal |
| Wrapper resolves but the command fails | Command exit status is passed through (`exec`). | Unchanged |
| Machine copy absent or stale | The unit's `ExecStart` fails if absent (systemd shows it). If stale, see AD-7 version skew. | Loud |
| A tool name planted as a symlink | Not a real dir, so it blocks adoption (AD-6). | Closed |
| An allowlisted name holding `.git`/`.claude`/`scripts` | Blocks adoption (invariant 2). | Closed |
| Audit write fails in `hos-human` | Ignored (`|| true`). The session starts. | Fail-open on audit, by design (interactive) |
| Real registry changed during tests | The session fails (AD-10). | Loud |

**Residuals (stated, not hidden).**
- **R-1.** A non-HOS writer that recreates a deleted role dir and populates it before any HOS launcher or wrapper runs still produces a refusal. AD-9 makes it visible within K worker cycles. It is not prevented.
- **R-2.** Until #1928 S6 lands, a persistent refusal is recorded in the audit trail and the cron log on every cycle, but no human item is filed (under the ESC-3 default).
- **R-3.** Sandboxed agents in the Worker, Overseer and Human clones can still edit their clone's `bootstrap/lib/hos_tmp_root.py`, which `bin/hos-cron` and `bin/hos-human` then run unsandboxed. This is the pre-existing posture (#1146) and is not widened here. AD-7 avoids extending it to systemd units.
- **R-4.** The (installing clone, other role) registry keys from AD-7(b) are inert but count toward the 256 cap.

---

## 4. Slices (each ≤15 files including tests; each independently mergeable)

| # | Slice | Files | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | REQ-9 test isolation (AD-10). | `tests/conftest.py`, `tests/framework/test_hos_human_launcher.py`, `tests/framework/test_registry_isolation.py` (new): 3 | **No** (tests only) | — | none (overseer-mergeable) |
| **S2** | Export site (AD-1), event identity and REQ-8 fields (AD-2), `hos-human` parity (AD-3), remedy text (AD-4), REQ-1 invariant test. | `bootstrap/lib/hos_tmp_env.sh` (new), `bin/hos-cron`, `bin/hos-human`, `bootstrap/lib/hos_tmp_root.py` (`_remedy` text only), `scripts/automation/lib/cycle_log.py` (docstring), `scripts/framework/framework_consumer_files.txt` (ship the helper), `tests/automation/test_hos_cron.py`, `tests/framework/test_hos_human_launcher.py`, `tests/framework/test_hos_tmp_root.py` (message assertions only), `tests/framework/test_hos_tmp_env.py` (new), `tests/framework/test_tmp_root_single_site.py` (new), `SCRIPTS-INDEX.md`: 12 | **Yes**: `bin/**`, `bootstrap/**`, `scripts/framework/**` | S1 (shared launcher test) | human approval only |
| **S3** | Adoption policy (AD-6) and the new invariant-2 tests (AD-5); REQ-3 mixed-fixture test (AD-8). | `bootstrap/lib/hos_tmp_root.py` (constant, `adoption_problems`, module docstring), `tests/framework/test_hos_tmp_root.py`, `tests/automation/test_hos_cron.py` (REQ-3 fixture), `docs/CRON-SETUP.md` (adoption list sentence): 4 | **Yes**: `bootstrap/**` | S2 (same file, same tests) | **ESC-1**. `security-reviewer` mandatory |
| **S4a** | Install-time pre-registration (AD-7(b)) and the REQ-2 simulation test for a fresh install. | `bootstrap/hos_install.sh`, `tests/…/test_hos_install_*` (the existing install suite, plus a new case), `tests/framework/test_tmp_root_first_writer.py` (new), `tests/framework/test_tmp_root_single_site.py` (no `--reviewed` in install): 4 | **Yes**: `bootstrap/**` | S2 | **ESC-2** (b) |
| **S4b** | Machine-copy wrapper (AD-7(d)), its installer, and the doc rewrite. | `bootstrap/hos-with-tmp` (new; bundle file), `bootstrap/hos_bootstrap.sh` (install the copies), the release-bundle file list pinned by `tests/framework/test_tmp_reaper_packaging.py`, `CLAUDE.md` (`:376`), `docs/CRON-SETUP.md`, `docs/SANDBOX-POLICY.md`, `tests/framework/test_hos_with_tmp.py` (new), `tests/framework/test_tmp_reaper_packaging.py` (or a sibling packaging test), `tests/framework/test_tmp_root_single_site.py` (docs assertion), `tests/framework/test_tmp_root_first_writer.py` (wrapper case), `SCRIPTS-INDEX.md`: ≤11 | **Yes**: `bootstrap/**`, `CLAUDE.md` | S2. S4a is optional. | **ESC-2** (d). `security-reviewer` mandatory (AF-2) |
| **S5** | REQ-6 content (AD-9): delivered as an amendment in ADR-1928 S6. No #2100 code. | none in #2100. #1928 S6 carries the fixture. | — | #1928 S6 | **ESC-3** |
| **S5′** | *Only if ESC-3 rules a one-off:* marker-keyed condition filer in `bin/hos-cron`. | `bin/hos-cron`, `tests/automation/test_hos_cron.py`: 2 | **Yes** | S2 | ESC-3 (alternative) |

**Order.** S1 → S2 → {S3, S4a, S4b in any order; S3 and S4a both touch tests that S2 created, so they rebase serially}.

**Codable before any human answer:** S1 and S2. Neither changes guard logic or depends on an ESC. S2 is the bulk of the visibility relief (REQ-7, REQ-8, AF-4).

**Design now, merge after:** S3 waits on ESC-1. S4a and S4b wait on ESC-2. S5 or S5′ waits on ESC-3.

**#1928 coordination.** #1928 S6 adds `--observed` at the block S2 rewrites. Whichever lands second rebases (AD-2).

### Test obligations (all deterministic; the registry is always the override, never the real file)

- **S1:**
  - a launcher test that previously leaked now writes only to the override;
  - the guard fails a planted test that writes the real-path fingerprint target;
  - the guard passes when the real registry is unreadable.
- **S2:**
  - success path: the three variables are exported, `HOS_TMP_SOURCE=resolver`, and `cycle-start` carries `tmpdir_source=resolver` with a `~`-redacted `tmpdir`;
  - fallback path: nothing is exported, and the event carries `role`, `project`, `cycle_id`, `tmpdir_source=inherited`, `tmpdir` and `reason`;
  - an overseer fallback records `role=overseer`;
  - a crashed resolver yields the last line;
  - control bytes are stripped;
  - the helper never exits non-zero under `set -euo pipefail`;
  - `hos-human` refusal writes exactly one event with `role=human`, `launcher=hos-human` and no `cycle_id`, prints the fixed unsandboxed line, and still reaches `exec`;
  - the REQ-1 static invariant;
  - the remedy line is a single line and contains the `mv` shape, the `mark` command and "unsandboxed".
- **S3:**
  - table: each tool name as a real dir is adopted;
  - each tool name as a symlink and as a file is refused;
  - each tool name holding `.git`, `.claude` or `scripts` is refused;
  - `src`, `docs`, `README.md`, `Makefile`, `package.json`, `percommit-2054`, `node-compile-cache-x` and `Node-Compile-Cache` are refused;
  - every pre-existing guard test passes byte-identically;
  - the mixed REQ-3 fixture is refused before any chmod, and the role dir's mode is unchanged.
- **S4a:**
  - a fresh install creates and registers four dirs (override registry);
  - the export-only plus third-party-write plus launcher sequence succeeds;
  - an install into a root holding a refused dir prints the remedy and exits 0;
  - `--dry-run` writes nothing;
  - the install never passes `--reviewed`.
- **S4b:**
  - the wrapper execs with the exports on success;
  - on refusal it execs without them, with the remedy on stderr;
  - the command's exit status is passed through;
  - bootstrap installs the copies with the checksum check and they are not under any clone;
  - the docs contain no static role-dir `Environment=` line.

---

## 5. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-1 scope, AF-1).** REQ-1 binds code that selects and exports a role dir from outside a sandbox. Sandboxed consumers (`run_tests_inner_loop.sh` step 1) trust `HOS_TMP_DIR` through `check-dir`, which is correct. "Already compliant" for the inner loop is true for its own selection. It was not true for the static `HOS_TMP_DIR` that non-launcher docs fed it, and AD-7 removes that.
- **AM-2 (REQ-6, ESC-3) → ADR-1928 AD-7.** The `tmp-root-fallback` condition body gains the role-dir path, the blockers, the `mv` alternative and "unsandboxed, in your own terminal", taken from the `--observed` detail. The REQ-6 deterministic test moves to #1928 S6's suite.
- **AM-3 (REQ-3 AC).** "REQ-6 state change" is asserted as the `--observed` hand-off until #1928 S6 lands, and as the filed item afterwards.
- **AM-4 (REQ-2 candidates, AF-2).** Candidate (a) must use a machine copy, never a clone's resolver. A new candidate (d), a machine-copy wrapper with no static exports, is added. "Machine bootstrap" is dropped as a pre-registration site.
- **AM-5 (VF-4 / REQ-4 attribution, AF-3).** `semgrep-mcp` is produced by semgrep at import, run by HOS's static-analysis validator, not by an MCP server.
- **AM-6 (REQ-8, AF-4, AF-5).** The fallback event also carries `role`, `project` and `cycle_id`. Cheap-skipped cycles record the effective temp dir only on the fallback path.
- **AM-7 (REQ-7, AF-7).** The remedy is already printed for adoption and re-point refusals. The requirement's real content is the audit event and the unsandboxed instruction.

Endorsed as written: REQ-3 (with AM-3), REQ-4 (with AM-5), REQ-5, REQ-9, and the §3 non-goals.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible, sanctioned by the requirements:**
  - a clearer refusal message;
  - `hos-human` audit;
  - new audit fields;
  - a `needs-human` item after K refusals (via #1928).
- **Routed, not sanctioned:**
  - **The guard's input set** grows by three names (ESC-1). This is a security-guard change.
  - **A new operational surface (ESC-2).** Machine copies of the resolver, helper and wrapper in `~/.local/share/hos/`, refreshed by `hos_bootstrap.sh`, and a **manual, machine-local edit to the human's `claude-rc.service`** to adopt the wrapper.
  - **The data-retention surface (ESC-2(b)).** Install now writes four registry entries per installing clone. The **delete-authority grant** that registration means is extended to four freshly created, empty dirs at install time, rather than at first launch.
  - **A new human-facing filing (ESC-3).** Its timing depends on #1928 S6.
- **Cost:** none (local file operations only). **New trust boundary:** none created. AD-7 deliberately avoids creating one (AF-2). Without AD-7, option (a) as drafted would have created one.
- **Startup gap: yes.** TD-2054:705 assumed the live role dirs held only HOS names, and that "the first launcher or inner-loop run registers them". It did not decide what registers a dir for non-launcher sessions, although it documented those sessions. That should have been settled in #2054's architecture. **Recommendation to the worker:** annotate #2100 (or open) a `startup-artifact-gap` issue against #2054. I have not filed it, per this task's instructions.
- **Affected sign-offs.**
  - **#2054 S2a resolver security review.** Its approval of the adoption allowlist covers `HOS_ONLY_RE` only. If ESC-1 is (A), the S3 `security-reviewer` sign-off must explicitly re-review the adoption rule as a whole, not only the diff. The registry, re-point, inode, case and ownership approvals stand, because they are untouched (AD-5).
  - **#2054 launcher design (TD §2A.3).** Superseded in shape by AD-1's single export site, not in behaviour. The S2 reviewers re-check fail-open behaviour against TD §2A.3.
  - **#2054 reaper sign-offs** stand, because the reaper is untouched.
  - **ADR-1928 AD-7** stands. AM-2 adds content to its body and does not change its mechanism.

---

## 7. Open human escalations

pm-agent's ESC-1 to ESC-4 stand. The architect's positions:

| ESC | Architect | Note | Gates |
|---|---|---|---|
| ESC-1 | **Recommend (A)**, with exact names, directory-only (AD-6). | **Security-guard change: your ruling.** (B) is rejected on the AD-5 reasoning. Under (C), S3 is dropped and `.tmp/Human` stays refused until you act. | S3 |
| ESC-2 | **Recommend (b) + (d)** (AD-7). (a) is acceptable only with a machine copy (AF-2). | It adds machine copies under `~/.local/share/hos/`, a manual unit edit by you, and install-time registration. **Operational and trust-surface ruling: yours.** | S4a, S4b |
| ESC-3 (i) | **Recommend: #1928 owns. No #2100 one-off** (AD-9). | This is a disagreement with REQ-6's fallback clause. Consequence: no human item for a persistent refusal until #1928 S6 merges (R-2). If you want one sooner, S5′ is marker-keyed so that it does not duplicate. | S5 / S5′ |
| ESC-3 (ii) | **Concur:** `hos-human` logs and audits, and does not escalate. | — | S2 |
| ESC-4 | **Concur: reject quarantine** (AD-8). | It would be a write into an unestablished dir, which the guard forbids. Please confirm explicitly. | none (rejection is the status quo) |

```yaml
adr: ADR-2100
issue: 2100
codable_now: [S1, S2]
design_now_merge_after: {S3: [ESC-1], S4a: [ESC-2], S4b: [ESC-2], S5: [ESC-3, "#1928 S6"], S5prime: [ESC-3]}
hard_constraints_not_waivable: [REQ-5, AD-5]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, options: {A: exact-tool-names, B: structural, C: unchanged}, recommended: A, gates: [S3], note: security guard input set}
  - {id: ESC-2, tier: hard-tradeoff, options: {a: execstartpre-machine-copy, b: install-preregister, c: a+b, d: machine-copy-wrapper}, recommended: b+d, gates: [S4a, S4b], note: operational surface + manual unit edit}
  - {id: ESC-3, tier: hard-tradeoff, options: {i-default: 1928-owns-no-oneoff, i-alt: marker-keyed-oneoff, ii: hos-human-no-escalation}, recommended: [i-default, ii], gates: [S5, S2]}
  - {id: ESC-4, tier: hard-tradeoff, options: {reject: refuse-and-escalate, accept: quarantine-then-adopt}, recommended: reject, gates: []}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **N-1 (out of scope, human act).** `.tmp/Worker` still needs the human to `mv` `percommit-2054` out, or run `mark --reviewed`, unsandboxed. `.tmp/Human` self-heals on its next `hos-human` launch only if ESC-1 is (A) and S3 has merged. Until then it also needs the human. No slice of this ADR performs either act.
- **N-2 → pm-agent.** `cycle_log.log_event` defaults `role` to `"worker"` for every event that omits it (AF-4). Other hos-cron events that omit `role=` (for example `cycle-start`) are mislabeled for the overseer. S2 fixes only the two temp events. A general fix is a separate issue.
- **N-3.** The `mktemp` rule (CLAUDE.md "Temp and working-state locations" rule 1) could name the failure mode ("a hand-named dir in `HOS_TMP_ROOT` blocks adoption"). That is optional, and if wanted it rides in S4b's `CLAUDE.md` edit.
- **FU-1.** If the attention pass (#1928) ever needs to diagnose without a fresh refusal, a read-only `hos_tmp_root.py diagnose` subcommand could emit the blockers as JSON. It is not needed now. AD-2's `HOS_TMP_REASON` suffices, and a second decision path invites drift.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every slice except S1 is on protected surface. S3 changes the input set of a guard that protects other projects' files from chmod and reaping. S4b adds an unsandboxed execution path for systemd units (made safe by machine copies, AF-2). S2 rewrites the launch block of every cron cycle and human session.
CONFIDENCE: HIGH on AF-1 (sandbox grants and `read_registry`'s `ENOENT` behaviour read in this session), AF-2 (`allowWrite` covers the clones; `denyWrite` covers only `bin/`), AF-3 (test comment), AF-4 (live event shape), and AD-5's invariants (each mapped to code lines read here). MEDIUM on AD-7's machine-copy version-skew argument, and on the exact interaction of S2 with #1928 S6's edit of the same block, which `technical-design` must sequence.
BLAST RADIUS: the temp-dir selection of every HOS cron cycle and human session (S2); the adoption decision for unregistered role dirs on every machine (S3); project installs (S4a); machine bootstrap and the operator's systemd units (S4b); the audit event schema for two events (S2). No gate, label, merge, approval or reaper path changes.
Change classification: STRUCTURAL. It adds a registration obligation at install and at session start for non-launcher sessions, adds a shared export site and machine copies, and may widen a security guard's accepted inputs (ESC-1).

## Human Review Required

ESC-1 (a security-guard change) and ESC-2 (an operational and trust-surface change that includes a manual edit to your machine-local unit) must be answered by you before S3, S4a and S4b merge. ESC-3 sets whether #2100 files anything itself, and my recommendation disagrees with the requirement's fallback clause. ESC-4 asks you to confirm a rejection. REQ-5 and AD-5 are not open to any answer. S1 and S2 may be built and reviewed now. For each protected slice, your own-account approval of the PR is the final gate.
