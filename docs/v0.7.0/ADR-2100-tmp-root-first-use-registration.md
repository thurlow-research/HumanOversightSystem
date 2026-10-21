# ADR-2100: Register a role temp dir before an untrusted writer can populate it, and fail closed for cron on refusal. One shell export site, install-time registration with a registry read-back verify, a machine-copy wrapper for non-launcher sessions, a closed exact-name tool allowlist, and a first-refusal alert (interim filer in S2, then #1928's condition primitive). The foreign-project guard is unchanged

**Status:** ACCEPTED FOR DESIGN, **AMENDED 2026-10-21** to record the human ruling of 2026-10-20 (see "Amendment — 2026-10-20" below). AD-1 to AD-13 now all bind `technical-design`. AD-6, AD-7 and AD-9 were PROVISIONAL and are now BINDING on the ruled options. AD-11 (cron fail-closed), AD-12 (install verify and v0.6.0 upgrade) and AD-13 (release gate) are new. REQ-5 (the guard) is not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-15 · **Amended:** 2026-10-21
**Author:** architect (autonomous worker cycle; no human present). The amendment was also written by architect in an autonomous worker cycle and records a human ruling; it does not originate one.
**Issue:** #2100 (follow-up to #2054 / PR #2061) · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice except S1 lands on protected surface: `bin/**` (`protected_surfaces.txt:26`), `bootstrap/**` (`:27`), `scripts/framework/**` (`:28`) and `CLAUDE.md` (`:19`). The human gate therefore applies whatever tier is computed.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2100-tmp-root-first-use-registration.md` (VF-1 to VF-8, REQ-1 to REQ-9, ESC-1 to ESC-4). Also `bootstrap/lib/hos_tmp_root.py`, `bin/hos-cron:376-391`, `bin/hos-human:113-127`, `scripts/framework/run_tests_inner_loop.sh:55-95`, `scripts/framework/install.sh:254-380`, `bootstrap/hos_install.sh:1723-1740`, `bootstrap/hos_bootstrap.sh:77-122`, `contract/sandbox-policy.template.json:155-185`, `scripts/automation/lib/cycle_log.py`, `tests/oversight/test_run_validators_preserves_gate_results.py:47-49`, `docs/v0.7.0/TECHNICAL-DESIGN-2054-tmp-quota-hygiene.md:697-705`, `docs/v0.7.0/ADR-1928-next-actor-assignment.md` (AD-2, AD-7, S6), `docs/CRON-SETUP.md:418-432`, `docs/SANDBOX-POLICY.md:175-200`, `CLAUDE.md:376`, and the machine-local `~/.config/systemd/user/claude-rc.service` and `~/Code/HumanOversightSystem/bin/claude-role` (read only). **Amendment inputs (2026-10-21):** the requirements as amended at `0949fc54b` (REQ-6, REQ-7, REQ-8 amended; REQ-10, REQ-11, REQ-12 added; ESC-1 to ESC-4 ruled), the human's verbatim ruling of 2026-10-20 18:34Z on #2100, `bin/hos-cron:376-391` (the resolve block sits before preflight and auth), ADR-1928 AF-7 and AD-2 (the attention pass runs after auth), `bootstrap/hos_install.sh:1715-1745` (the non-interactive config key append, and the interactive-only delegation to `install.sh`), `scripts/framework/install.sh:134-148, 254-275`, ADR-1605 AD-20/AC-39/AC-40 (the `bootstrap/notify_human.sh` seam of #2125, not yet on `main`), and #2059 (an unmerged `config.sh` injection fix to `bootstrap/hos_install.sh`).
**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S3 (the allowlist is a security guard's input set) and S4b (a new unsandboxed execution path for systemd units). `privacy-reviewer` is mandatory on S2 (new path-bearing audit fields and an alert body that leaves the machine). `reliability-reviewer` is mandatory on S2 (it rewrites the launch-time block of every cron cycle and every human session, and after the amendment it adds a new cycle-stopping failure mode) and on S4a (after the amendment, an install can now fail on a temp-dir refusal).
**Explicitly does NOT re-litigate:** the trust registry's location, format and authority; the reaper's delete-authority rule (registered path, role and inode only); `mark --reviewed` as the human's explicit adoption step; `HOS_TMP_ROOT` defaults and the `config.sh` grammar; #1928's attention-pass placement, counter or dedup design; #1146. *(Amended 2026-10-21.)* The amendment does not move #1928's pass or change its dedup design. It does ask #1928 for a per-key K and a pre-auth entry point for this one key (AM-8).

---

## Amendment — 2026-10-20 human ruling (recorded 2026-10-21)

**Ruling (ScottThurlow on #2100, 2026-10-20).** ESC-1 **A**. ESC-2 **b+d**. ESC-3 (i) **#1928 owns** the escalation primitive, and (ii) **concur** (`hos-human` logs and audits, and does not escalate). ESC-4 **rejected**. S4a (install-time registration) is wanted. Then, verbatim (18:34Z):

> *"Amend ADR-2100: tmp-root refusal is fail-closed for hos-cron roles (no cycle runs; first refusal alerts once via needs-human and #2125; a missing helper counts as refusal); hos-human/S4b stay fail-open with a banner. S4a must verify registration and fail the install on refusal, including the v0.6.0 upgrade path. v0.7.0 does not ship until the consumer-upgrade smoke test passes."*

#2137 is that consumer-upgrade smoke test.

**What this supersedes.** The original ADR made every refusal "loud, never fatal". A cron cycle fell back to the inherited `TMPDIR` (in practice `/tmp`), wrote `cycle-tmp-root-fallback`, and relied on #1928 to escalate after K = 3. For `bin/hos-cron` roles (worker, overseer) that is **superseded**. A refusal now stops the cycle. `hos-human` and the S4b wrapper keep the fail-open behaviour, now with a prominent banner. The superseded text is kept below, struck through in place or marked *Superseded 2026-10-20*, where its rationale still explains a surviving decision.

**Index of changes.**

| ID | Change |
|---|---|
| AF-9, AF-10, AF-11 | New findings that shape the amendment (§0.3). |
| §1 | Organising principle: the refusal outcome is now split by launcher. |
| AD-1 | The helper's contract is unchanged (it reports and never fails). The **caller's** policy is now split: fail-closed for cron (AD-11), fail-open for `hos-human` and the wrapper. The helper must be sourced under a guard, because a missing helper counts as a refusal. |
| AD-2 | For cron, `cycle-tmp-root-fallback` is superseded by `cycle-tmp-root-refused`, with full identity. `cycle-start` for cron is always `tmpdir_source=resolver`. |
| AD-3 | Now BINDING (ESC-3(ii) ruled). It adds the banner and covers a missing helper. |
| AD-6 | Now BINDING (ESC-1 A ruled). |
| AD-7 | Now BINDING (ESC-2 b+d ruled). Under (b), an install-time refusal is **fatal**, which supersedes "never fatal to the install". Under (d), the wrapper banner is fail-open and writes no clone audit (AF-11). |
| AD-8 | For cron, outcome (ii) is now "refuse, record, alert once, stop". |
| AD-9 | Now BINDING (ESC-3(i) ruled: #1928 owns). The "no #2100 one-off" recommendation is **superseded** by the ruling's first-refusal alert. S2 carries the marker-keyed interim filer (the former S5′ shape). K = 1 for this key. #2125 is a second channel. |
| AD-11 (new) | Cron fail-closed: the event, the exit, the audit-write policy, the alert step and the landing order. |
| AD-12 (new) | Install verify, and the `HOS_TMP_ROOT` write on the v0.6.0 upgrade path. |
| AD-13 (new) | Release gate: v0.7.0 does not ship until #2137 passes. |
| §3 | Failure table: four rows superseded, six added. R-2 superseded; R-5 and R-6 added. |
| §4 | Slices: S5′ is folded into S2. S2 now merges with or after S4a, and only once every live role dir resolves cleanly. The order is now S1 → S4a → S2. |
| §5 to §7 | Amendments AM-8 and AM-9 are added, and the affected-sign-offs analysis is redone. All ESCs are ruled. |
| Architecture review (2026-10-21) | Within the ruling, before any S2/S4a design: dedicated exit **77** with a selection rule, and breakers stated not to count it (AD-11 step 4); alert state and alert-step `TMPDIR` moved to `~/.hos`, and the two alert channels made independent (AD-11 step 3; R-5 closed, R-7 added); the landing-precondition check and the install verify replaced by a read-only `status` registry read-back, because `resolve` without `--create` checks nothing (AD-11, AD-12); install verify placed before the `.hos-release` stamp; #2059 made a non-blocking dependency (AD-12). |

**Not changed by the ruling:** AD-4 (message content), AD-5 (the guard), AD-10 (test isolation), and S1 (merged as PR #2140; tests only).

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

### 0.3 Amendment findings (2026-10-21; these shape AD-11 and AD-12)

**AF-9 (HIGH): the refusal is detected before auth, so #1928's in-cycle pass never sees a fail-closed refusal.** The resolve block is `bin/hos-cron:376-391`. That is before the low-space trigger, preflight, auth (`:950-1024`) and the halt check (`:1038-1055`). ADR-1928 AD-2 places the attention pass after the halt check, and ADR-1928 AF-7 already records that "conditions that stop a cycle before auth cannot be escalated from inside the cycle". Under the original ADR this did not matter, because the fallback cycle carried on and reached the pass. Under fail-closed it matters a great deal: a refusing cycle exits before the pass, so `--observed tmp-root-fallback` is never delivered and no human item is ever filed. AD-11 therefore gives the refusal path its own bounded alert step, with its own token mint. AM-8 asks #1928 S6 to expose a conditions-only entry point that this step can call once S6 lands.

**AF-10 (MEDIUM): `scripts/framework/install.sh` is the wrong place for the upgrade write.** It runs only interactively, and only when placeholders remain (`hos_install.sh:1724-1736`). A non-interactive upgrade from v0.6.0 never runs it. The non-interactive key-append step (`hos_install.sh:829-848`; `:1717` only prints its warning) does run on every upgrade. Today it appends **empty** values only (`printf '%s=""\n'`), so writing a computed value is an extension of that one writer, not a reuse of it as-is. *(Review note 2026-10-21.)* A missing or empty key is not a resolution failure: `read_config_value` falls back to `DEFAULT_VALUE` (`../.tmp`, `hos_tmp_root.py:80, 121-133`). The upgrade write matters because `install_default` (`:583-590`) gives a lone clone a per-project XDG dir instead of a shared `../.tmp`, and an un-upgraded lone clone would otherwise silently register dirs under its parent's `.tmp`. REQ-11 names `install.sh`. The binding content is "on the v0.6.0 upgrade path, `HOS_TMP_ROOT` is written before register-and-verify", so AD-12 puts the write where every upgrade passes through it. #2059 (unmerged) rewrites how `hos_install.sh` writes `config.sh` values, to fix shell injection. The new write must not be a fresh, second `printf >>` writer. AD-12 sets the rule (#2059's writer if merged, otherwise a charset-gated extension of the one existing append site).

**AF-11 (MEDIUM): the S4b wrapper cannot write the clone's audit log without breaking AF-2.** Audit events are written by the clone's `scripts/automation/lib/cycle_log.py`. If an unsandboxed systemd unit ran that file, it would be running agent-writable clone code, which is exactly the path AF-2 closes. So the S4b wrapper's "audit `|| true`" can only be the journal (stderr). No clone event is written. `hos-human` is different: it already runs clone code unsandboxed (R-3), so its best-effort audit write stays.

**Reuse search (amendment).** I searched `bin/`, `bootstrap/` and `scripts/automation/lib/` for a pre-auth alert path and a human-notifier.
- Found: `bootstrap/get_app_token.sh` (the mint) and `bootstrap/create_issue.sh` (filing).
- Found: the timeout breaker's fail-closed dedup and auto-close idiom (`bin/hos-cron:2179-2200`, `:2283-2322`).
- Found: ADR-1928 AD-7's planned body marker.
- `bootstrap/notify_human.sh` (#2125) is **not on `main`**. ADR-1605 AC-39 and AC-40 already set the "absent notifier = undelivered, never blocking" rule for it, and AD-11 reuses that rule unchanged.

---

## 1. Organizing principle

**Only an unsandboxed, HOS-authored, human-gated code path may decide that a dir is a role dir, and only the resolver decides it. Everything else either asks the resolver or consumes what a launcher exported.** Registration is pulled as early as possible, to the moment the root is created (install) and to the moment any session starts (launcher or wrapper). Nothing exports a role-dir path that the resolver did not return in that same process tree. ~~When the resolver refuses, the refusal is recorded with full cycle identity and handed to #1928's condition primitive, which tells the human once.~~ *(Superseded 2026-10-20.)* When the resolver refuses, what happens depends on who launched the session:
- **An unattended cron cycle stops.** It records the refusal with full cycle identity, tells the human once on the first refusal, and does no work. Nobody is present to notice a degraded run, so it must not run degraded.
- **A session a human started** (`hos-human`, or the wrapper) **continues**, with a banner, because that human is the one reading it.

The guard's input set grows only by exact, producer-named tool names, and only on the human's ruling.

---

## 2. Decisions

### AD-1: One decision site, one export site. (BINDING; REQ-1, AF-1, AF-6, D41.)

- **Decision site (unchanged).** `bootstrap/lib/hos_tmp_root.py resolve --create` is the only code that creates, adopts or registers a role dir. `mark --reviewed` remains the only override. No other HOS file may `mkdir` a path under `HOS_TMP_ROOT`.
- **Export site (new).** `bootstrap/lib/hos_tmp_env.sh` defines one function, here called `hos_tmp_export <repo> <role>` (`technical-design` names it):
  - It runs the resolver once with `--create` and keeps stdout (the dir) and stderr (the reason) apart. Stdout and stderr are never mixed. A second run for the reason is allowed only if `technical-design` shows it is needed, and the resolver is idempotent, so it is harmless.
  - **On success** it exports `TMPDIR`, `CLAUDE_CODE_TMPDIR` and `HOS_TMP_DIR` (all the role dir), and sets `HOS_TMP_SOURCE=resolver` and `HOS_TMP_ROOT_RESOLVED`.
  - **On failure** it exports nothing, sets `HOS_TMP_SOURCE=inherited`, and sets `HOS_TMP_REASON` to the last stderr line with the `hos_tmp_root: ` prefix removed, control bytes removed, and the line cut to 1200 characters (the current `:386-388` rule).
  - It never prints, never writes audit, and never returns non-zero to a `set -euo pipefail` caller. Logging is the caller's job, so each launcher keeps its own voice.
  - *(Amended 2026-10-21.)* The helper's contract is unchanged: it **reports**, and the **caller decides**. `bin/hos-cron` fails closed on `HOS_TMP_SOURCE=inherited` (AD-11). `bin/hos-human` and the wrapper fail open with a banner (AD-3, AD-7(d)). The helper also exports `HOS_TMP_ROLE_DIR`, the absolute role-dir path the resolver evaluated, so that the refusal event and alert can name it without parsing the reason. `technical-design` decides whether that value comes from a read-only resolver path computation or from the reason line, but it must not become a second decision path (FU-1). It is `unknown` if the helper is missing.
- **Guarded sourcing (added 2026-10-21; REQ-10 "a missing helper counts as refusal").** Each caller sources the helper under a guard. A missing file, a failed `source`, or an absent `hos_tmp_export` function after sourcing is treated as if the resolver had refused, with `HOS_TMP_SOURCE=inherited` and `HOS_TMP_REASON=export helper missing or broken: <path>`. Under `set -euo pipefail`, a bare `source` of a missing file would abort the cycle before any event or alert was written. That would be fail-closed, but **silently**, which the ruling forbids.
- **Callers.** `bin/hos-cron` and `bin/hos-human` source it and call it. AD-7's wrapper calls its machine copy. `run_tests_inner_loop.sh` keeps its own four-step precedence (`:55-95`) because it is a consumer inside a sandbox (AF-1). It is not an exporter of `CLAUDE_CODE_TMPDIR` or `HOS_TMP_DIR`, and it stays as it is.
- **Scope of REQ-1, restated (AM-1).** REQ-1 binds code that selects and exports a role dir from outside a sandbox. Sandboxed consumers trust `HOS_TMP_DIR` through `check-dir`, as today.
- **Invariant test (REQ-1 AC).** A static test over every shell and Python file under `bin/`, `bootstrap/` and `scripts/` asserts:
  - (1) no assignment or export of `CLAUDE_CODE_TMPDIR=` or `HOS_TMP_DIR=` outside `bootstrap/lib/hos_tmp_env.sh` (tests excluded);
  - (2) no `mkdir` or `os.mkdir`/`makedirs` whose argument mentions `HOS_TMP_ROOT`, `.tmp/` or a `ROLE_DIRS` value, outside `hos_tmp_root.py`;
  - (3) `bin/hos-cron` and `bin/hos-human` each call the export function exactly once.

  Anchors must not be first-occurrence string matches that a comment can satisfy (memory: "test anchors use first occurrence").

### AD-2: Every refusal carries cycle identity and the effective temp dir. `cycle-start` carries the effective temp dir. (BINDING; REQ-8, REQ-10, AF-4, AF-5. Amended 2026-10-21.)

- **`cycle-tmp-root-refused`** *(new 2026-10-21; replaces the next bullet for `bin/hos-cron`).* It is written by `bin/hos-cron` where `:390` is now, before any exit and before any other cycle work. It carries:
  - `role=$ROLE`, `project=$PROJECT`, `cycle_id=$HOS_CYCLE_ID` and `bot=<the role's expected bot login>`. Auth has not run yet, so `bot` is the configured identity, not a verified one, and the field says so (`bot_source=config`).
  - `clone=<REPO_ROOT>` and `role_dir=<HOS_TMP_ROLE_DIR>`.
  - `blockers=<the blocking entries, as the resolver lists them: the first five plus a count>`. The value is `unknown` for a missing helper or a non-adoption refusal (symlink, owner, re-point and so on). For those, `reason` carries the cause.
  - `reason=` as today, and `refusal_class=resolver|helper-missing|resolver-crash`.
  - `tmpdir_source=inherited`, plus `tmpdir=<inherited TMPDIR, or "unset">`. This records what the cycle **declined** to use. It is not a fallback.
  - `action=cycle-stopped`.
- ~~**`cycle-tmp-root-fallback`** (`bin/hos-cron`, written where `:390` is now, before any exit) carries:~~ *Superseded 2026-10-20 for `bin/hos-cron`.* The event name and the shape below survive **only** for `bin/hos-human` (AD-3), where the session still falls back. REQ-7 asks for that parity. The shape:
  - `role=$ROLE`, `project=$PROJECT` and `cycle_id=$HOS_CYCLE_ID`. Passing `role` explicitly fixes AF-4.
  - `tmpdir_source=inherited`.
  - `tmpdir=<inherited TMPDIR, or "unset">`.
  - `reason=` as today.
- **`cycle-start`** (`:1946`) gains `tmpdir_source=resolver|inherited` and `tmpdir=…`. Cheap-skipped cycles do not reach it (AF-5). That is accepted, because the refusal event already records every failing cycle unconditionally. *(Amended 2026-10-21.)* For `bin/hos-cron`, a cycle that reaches `cycle-start` has by construction resolved, so the value is always `resolver`. A test pins that `inherited` never appears on a cron `cycle-start`. The field is kept, not dropped, so that a future regression to fall-back shows up in the data.
- **Path redaction.** In the new `tmpdir`, `clone` and `role_dir` fields, a leading `$HOME` (passwd home) is written as `~`. That keeps the identity, which is all REQ-10 needs, without writing the home path. The existing `reason=` field keeps absolute paths, because it carries the exact command the human must paste. Redacting it would break the remedy. The alert body (AD-11) carries absolute paths for the same reason. This is `privacy-reviewer`'s to confirm on S2.
- **`cycle_log.py` docstring** lists the new fields and the new event. No code change in `cycle_log.py`.
- **Hand-off to #1928.** When ADR-1928 S6 lands, ~~the `--observed tmp-root-fallback=<detail>` flag is derived from `HOS_TMP_SOURCE=inherited` and `HOS_TMP_REASON`~~ *(amended 2026-10-21)* the refusal path's alert step (AD-11) calls #1928's conditions-only entry point (AM-8) with `tmp-root-fallback=<detail>`, where the detail is derived from `HOS_TMP_SOURCE`, `HOS_TMP_REASON` and `HOS_TMP_ROLE_DIR`, never by re-parsing the log line. The #1928 key keeps its registered name, `tmp-root-fallback`, even though the cron event is now `cycle-tmp-root-refused`. Renaming a registered key is #1928's call, and the name is only a cosmetic mismatch. **Conflict notice:** #2100 S2 and #1928 S6 both edit this block of `bin/hos-cron`. Whichever lands second rebases onto the other's change, and its PR body states the conflict.

### AD-3: `hos-human` parity: the same event, the remedy, and the unsandboxed instruction, behind a prominent banner. Fail-open. No escalation, and no in-launcher approval. (BINDING; REQ-7, AF-7. ESC-3(ii) ruled "concur", 2026-10-20.)

- **Fail-open stays (ruling: "hos-human/S4b stay fail-open with a banner").** A missing or broken helper (AD-1 guarded sourcing) is handled exactly like a refusal here. It shows the banner, and the session starts.
- **Banner (added 2026-10-21).** The stderr output below is framed as a banner, so that it cannot be missed in the scroll before `exec claude`: a blank line, a ruled header line such as `==== HOS TEMP DIR REFUSED — this session is using <inherited TMPDIR or /tmp> ====`, then the role dir, the blocking entries, the AD-4 remedy line and the fixed line below, then a closing rule. `technical-design` pins the exact text. A test asserts that the header, the role dir and the `mark` command all appear.
- On `HOS_TMP_SOURCE=inherited`, `bin/hos-human`:
  - writes **one** `cycle-tmp-root-fallback` event with `role=human`, `launcher=hos-human`, `tmpdir_source`, `tmpdir` and `reason`. There is no `cycle_id`, because an interactive session never has one (`bin/hos-cron:340-349`). The event name is reused, as REQ-7 asks, so that one query counts both launchers. The `launcher` field tells them apart.
  - prints the reason to stderr, followed by one fixed line: *"Run the remedy above in a normal terminal, outside any Claude session (it needs the unsandboxed registry). This session will use the inherited TMPDIR."*
- The audit write happens before `exec claude`, is best-effort (`|| true`), and never blocks the session.
- **Rejected:** having `hos-human` offer an interactive "review and type yes to mark" prompt. `hos-human` does run in the human's own terminal, but a launcher prompt trains a reflexive yes on a security step. `mark --reviewed` is deliberately a separate, typed command. This is not open to the agent side. If the human wants it, it is a new issue.
- **No REQ-6 escalation from `hos-human`** (ESC-3(ii), ruled "concur" 2026-10-20). The human who launched the session is the reader. A cron refusal for the same clone files its own alert (AD-11), so a Human-clone problem that also affects a cron role is still escalated. A refusal confined to `.tmp/Human` is reported only by the banner and the event.

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
- **What is outside the threat.** Sandboxed agents can already write anything into their own role dir (`sandbox-policy.template.json:177`). The guard is not a defence against an agent populating a HOS dir. An agent that does so can at most cause a refusal, which is a denial of service on itself that AD-9 makes visible. *(Amended 2026-10-21: under AD-11 that denial of service stops the cron role, rather than degrading it, and alerts at once. See R-6.)*
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

### AD-6: Adoption policy: a separate, closed, exact-name set of tool entries, directory-only, still subject to the project-file check. (BINDING; REQ-4. ESC-1 ruled **A**, 2026-10-20. Was PROVISIONAL on ESC-1(A).)

- **Form.** A new constant in `hos_tmp_root.py`, for example `TOOL_ENTRY_NAMES = frozenset({...})`, separate from `HOS_ONLY_RE`, with one comment per name naming its producer:
  - `node-compile-cache`: Node's module compile cache under `os.tmpdir()`, enabled by Claude Code;
  - `cc-socks`: Claude Code's sandbox socket dir;
  - `semgrep-mcp`: semgrep, at import, run by `scripts/oversight/run_validators.sh` (AF-3).
- **Exact names only.** No prefixes or globs (`node-*`, `semgrep-*`). A new tool name is a reviewed one-line diff to a protected file, which is the point.
- **Stricter than the existing patterns.** A tool name is accepted only if `lstat` shows a **real directory**, not a symlink or a file. The existing `HOS_ONLY_RE` behaviour is left exactly as it is, so the existing guard tests pass unchanged (REQ-5 AC). The extra condition costs nothing, because all three producers create directories.
- **Invariant 2 applies.** Each tool name that is a dir directly holding `.git`, `.claude` or `scripts` blocks adoption.
- **`percommit-*` is not added.** I concur with pm-agent.
- **Trust reasoning for (A).** For (A) to adopt a foreign dir, that dir must sit at exactly `<HOS_TMP_ROOT>/<Worker|Overseer|Human|Local>`. Its every top-level entry must also be one of eleven HOS temp patterns or three tool-cache directory names, none holding project markers. Such a directory is itself somebody's temp dir. The worst loss is regenerable cache content older than 24 h. That is the same class of loss the existing `tmp*` and `pytest-of-*` patterns already accept. (B) has no such bound, as the requirements state: any non-git foreign folder with a role-dir name would be adopted, chmodded and reaped.
- ~~**Under (C).** AD-6 is dropped, and S3 does not exist.~~ *Moot: ESC-1 was ruled A.* Retained for the record: under (C), Human and any freshly populated dir would have relied on AD-7 and AD-9 alone.
- **Interaction with fail-closed (added 2026-10-21).** Under AD-11, a cron role dir that S3 would adopt is, until S3 merges, a stopped cron role. S3 is therefore part of how the live dirs come to "resolve cleanly" before S2 merges (AD-11 landing order). The live Overseer dir holds all three tool names, but it is already registered (invariant 8), so it is unaffected either way.

### AD-7: Non-launcher sessions: register at install, and launch through a machine-copy wrapper. No static role-dir exports anywhere in HOS docs. (BINDING; REQ-2, REQ-11, AF-1, AF-2, AF-11. ESC-2 ruled **b+d**, 2026-10-20. Was PROVISIONAL on ESC-2.)

- **(b) Install-time pre-registration.**
  - **Where.** `bootstrap/hos_install.sh`, after `config.sh` is final, on **both** interactive and non-interactive paths. `scripts/framework/install.sh` runs only interactively (`hos_install.sh:1723-1729`), so it is the wrong site.
  - **What.** For each of `worker`, `overseer`, `human` and `local`, it runs `hos_tmp_root.py resolve --repo <target> --role <r> --create`.
  - ~~**Failures.** A failure is printed with its remedy and is never fatal to the install.~~ *Superseded 2026-10-20 ("S4a must verify registration and fail the install on refusal").* After registering all four, the install **verifies** each one, and it **exits non-zero** on any refusal (AD-12). Under `--dry-run` both steps are skipped, and the dry-run output says that they would run.
  - **Upgrade path (added 2026-10-21).** On a v0.6.0 → v0.7.0 upgrade, the existing `config.sh` may lack `HOS_TMP_ROOT`. The install writes it before registering (AD-12).
  - **Why all four from one clone.** The root and its four dirs are created together, which is exactly the VF-3 moment. A dir registered under another repo key is later accepted by each role's own clone without re-running adoption (`:544-547`). The resulting (installing clone, other role) keys are live but inert: no code resolves those roles from that clone. They are pruned when the clone disappears, and they count toward the 256-entry cap. This is stated, not hidden.
  - **Rejected: machine bootstrap as the site.** `hos_bootstrap.sh` knows no clone and no `config.sh`, so it cannot compute a root.
- **(d) Machine-copy wrapper.** This replaces the pm-agent's (a); see AF-2.
  - **What gets installed.** `hos_bootstrap.sh` installs, beside the reaper's machine copy in `~/.local/share/hos/`, a copy of `hos_tmp_root.py`, `hos_tmp_env.sh` and a small wrapper (here `hos-with-tmp`; `technical-design` names it). The same copy-and-checksum routine as `install_tmp_reaper` is used.
  - **What the wrapper does.** `hos-with-tmp --repo <clone> --role <role> -- <command…>` calls `hos_tmp_export` and then `exec`s the command. On refusal, or if the machine-copy helper is missing or broken, it prints the AD-3-style banner (header, role dir, blockers, AD-4 remedy line) to stderr, which for a unit is the journal. It then execs **without** exporting. That is the same fail-open-without-export behaviour as `hos-human`, and the ruling confirms it ("hos-human/S4b stay fail-open with a banner"). The availability of the human's remote-control channel outweighs reaper coverage of one dir, and nothing is ever exported that the resolver did not return.
  - **No clone audit event (added 2026-10-21; AF-11).** The wrapper never runs clone code, including the clone's `cycle_log.py`. Its "best-effort audit" is the journal line, and nothing else. If an S4b-launched session's refusal must reach the audit trail, the session's next `hos-human` or cron run records it. A machine-copy event writer is **rejected**: it would be a second implementation of `cycle_log`.
  - **Unchanged invariant.** `hos_tmp_root.py` keeps its documented invariant that it never spawns a process (`:31`). The wrapper is shell.
  - **Docs.** `CLAUDE.md:376`, `CRON-SETUP.md:418-432` and `SANDBOX-POLICY.md:185-200` drop every `Environment=TMPDIR=`/`CLAUDE_CODE_TMPDIR=`/`HOS_TMP_DIR=` example for a role dir. They show instead `ExecStart=%h/.local/share/hos/hos-with-tmp --repo <clone> --role <role> -- <existing ExecStart>`, and `bin/hos-human` (or the wrapper) for a plain `claude`. The "one-time registration" paragraphs become "only needed if you cannot use the wrapper".
  - **Docs test.** No `Environment=` line in those three files assigns one of the three variables to a path under `.tmp/`.
- **Version skew (stated).** A unit's machine copy can lag the clone's resolver. Both write registry format v1, under the same lock, with the same keys. Skew can only make the two disagree on whether an unregistered dir is adoptable (AD-6), and the stricter copy wins in practice, because registration happens once. `hos_bootstrap.sh` refreshes the copies on each run.
- **The live `claude-rc.service` and `claude-role` are machine-local and are not edited by this build.** S4b's PR body carries the exact unit diff the human applies. That is an operational act for the human (§6).
- **S4b remains conditional (ruling).** S4b ships in v0.7.0 only if it is ready. S4a and S2 do not depend on it.
- **Under (a) only** *(not chosen; kept for the record).* Docs show `ExecStartPre=%h/.local/share/hos/hos_tmp_root.py resolve … --create` (the machine copy, never the clone's) and keep the static `Environment=` lines. AF-1's static-`HOS_TMP_DIR` hole stays open whenever the dir is deleted and recreated by a non-resolver writer. **Under (b) only.** Fresh installs are covered. Existing units and deleted-then-recreated dirs are not.

### AD-8: An unknown first writer gets one of two outcomes, adopt or refuse-and-escalate. No quarantine. (BINDING on the outcome set; REQ-3, ESC-4.)

- **Outcome (i).** Adopt and register: `resolve --create` succeeds, with today's code path.
- ~~**Outcome (ii).** Refuse: the launcher falls back (AD-1), writes the AD-2 event, and passes `--observed tmp-root-fallback` to #1928's pass (AD-9).~~ *Superseded 2026-10-20.* **Outcome (ii), amended.** Refuse:
  - **`bin/hos-cron`** writes `cycle-tmp-root-refused` (AD-2), raises the alert on the first refusal (AD-11 alert step), and exits non-zero before any work. It never falls back.
  - **`bin/hos-human` and the wrapper** fall back, with the banner (AD-3, AD-7(d)).
- There is no third, silent outcome. ~~After #1928 S6, every K-th consecutive one produces exactly one human item.~~ *(Amended.)* After S2, every cron refusal carries cycle identity and stops the cycle, and the first one produces exactly one human item (K = 1).
- **ESC-4: concur with rejection.** *(Ruled "rejected", 2026-10-20.)* Moving entries into a `.hos-quarantine-<ts>/` inside an unregistered dir is a rename inside a dir whose ownership HOS has not established. That is precisely the side effect invariant 7 forbids. It would also turn the guard into a self-healing path that any `config.sh` edit could trigger against a foreign dir: rename its contents, then adopt and reap them. I recommend that the human confirm the rejection. It is not a decision I would take in the other direction under any circumstances short of a new threat model.
- **REQ-3 AC.** The mixed fixture (a `percommit-2054` dir plus a `node-compile-cache` dir) is refused under ESC-1 (A) and (C). It would be adopted only under (B), which is rejected. ~~The test's "REQ-6 state change" half is asserted against the `--observed` hand-off until #1928 S6 exists, and against the filed item once it does (AM-3).~~ *(Amended 2026-10-21.)* The test's "REQ-6 state change" half is asserted against S2's interim filer (one marker-keyed item, using a fake GitHub), and it also checks the non-zero exit with no work-stage side effect (REQ-10). Once #1928 S6 lands, it is asserted against S6's conditions-only entry point instead.

### AD-9: Escalation is #1928 AD-7's condition primitive. #2100 adds content, and carries a marker-keyed interim filer until S6 lands. (BINDING; REQ-6. ESC-3(i) ruled "#1928 owns", 2026-10-20. Was PROVISIONAL on ESC-3(i). Amended 2026-10-21 for K = 1 and the interim filer.)

- **Ownership.** ADR-1928 AD-7 already binds: the counter per role-clone, K = 3, a marker-keyed fail-closed dedup, filing into the target milestone, auto-close after K clear cycles, a committed key registry whose first key is `tmp-root-fallback`, and an Action of the exact `mark --reviewed` command with the absolute clone path. That satisfies REQ-6's dedup, auto-close and duplicate-query rules by construction.
- **#2100's contribution (AM-2 to #1928).** The condition body must also carry:
  - the absolute role-dir path;
  - the blocking entries;
  - the AD-4 move alternative;
  - Who = "the human, unsandboxed, in your own terminal".

  The pass takes these from the `--observed` detail, which is `HOS_TMP_REASON` (AD-2), sanitised as today. The REQ-6 deterministic test (K-1, K, K+n, K clear) belongs in #1928 S6's suite, with a #2100 fixture.
- **K = 1 for this key (amended 2026-10-21; ruling: "first refusal alerts once").** This overrides ADR-1928 AD-7's default K = 3 for `tmp-root-fallback` only. The clear count is also 1: one cycle that resolves cleanly auto-closes the item. Flapping is not a practical risk, because registration is sticky (invariant 8). Once the human remedies and the next cycle registers the dir, it stays accepted, unless the dir is re-pointed, its inode changes or it becomes a symlink. Each of those is a genuinely new condition, and deserves a new alert. AM-8 asks #1928 for a per-key K.
- **Second channel: #2125 (ruling: "alerts once via needs-human and #2125").** When the interim filer (or, later, S6) files a **new** item, the alert step also makes one call to `bootstrap/notify_human.sh` (#2125's seam, ADR-1605 AC-40 shape), with a cause of `tmp-root-refused`, the issue number, `--since` and `--priority high`, and the AD-11 body. Until #2125 lands, the call resolves to "absent": an `alert-undelivered` event is written, and the GitHub item is the only channel (ADR-1605 AC-39 rule, reused). Adding `tmp-root-refused` to #2125's closed trigger list is a cross-issue requirement (AM-9).
- ~~**Recommendation: no #2100 one-off.**~~ *Superseded 2026-10-20 by the ruling's first-refusal alert.* The recommendation is kept below because it explains why the interim filer is marker-keyed and must be deleted when S6 lands. Original text: I disagree with the requirement's fallback clause ("#2100 delivers a minimal one-off if #1928's primitive has not landed"). The reasons:
  - **(1) D41.** A second dedup-and-file implementation in `bin/hos-cron` would have to be deleted when #1928 S6 lands.
  - **(2) Double filing.** The one-off keys on a title prefix (the breaker idiom, `:2186-2206`) and #1928 keys on a body marker. Neither sees the other, so during any overlap both file a `needs-human` issue for the same condition.
  - **(3) A second unregistered key.** ADR-1928 AD-7 refuses unregistered keys precisely to avoid free-text conditions, and a hos-cron-local filer bypasses that registry.
  - **(4) The relief is not blocked on it.** The one live case is known and is in the human's hands now (§8 N-1). The interim visibility is S2's identity-bearing events.

  *Why (4) no longer holds:* under fail-closed, a refusal stops a cron role outright, and AF-9 means #1928's in-cycle pass never sees it. Without a filer of its own, a stopped worker would be visible only in the cron log. Reasons (1) to (3) still hold, and they set the interim filer's shape, below.
- **Interim filer (BINDING; was S5′, now folded into S2).** Until #1928 S6 lands, S2's AD-11 alert step files the item itself:
  - It is keyed on #1928's planned marker, `<!-- hos-attention-condition v=1 key=tmp-root-fallback role=<role> project=<project> -->`, not on a title prefix. That way #1928 S6 adopts the open issue instead of duplicating it (reason 2).
  - It is filed into the target milestone (ADR-1928 AF-2), so that it does not disable the #1395 cheap skip.
  - Dedup is a marker query that fails closed, using the breaker idiom (`:2179-2200`). If the query fails, nothing is filed, and the next refusing cycle tries again.
  - Auto-close happens on the first clean resolve. It runs at the breaker's post-auth auto-close site (`:2283-2322`), because a clean cycle reaches auth.
  - #1928 S6 carries the obligation to replace the filer's internals with a call to its conditions-only entry point (AM-8) and to delete the duplicate code (reason 1). The S2 PR body names that obligation.

### AD-10: Tests never write the real registry. The isolation is session-wide, and a guard proves it. (BINDING; REQ-9, VF-6.)

- **Default.** `tests/conftest.py` sets `HOS_TMP_REGISTRY_FILE` in `pytest_configure`, so the value is present before any test or fixture runs, to a session-owned path under the session temp dir. Subprocesses inherit it through `os.environ` and through `child_env()`.
- **Guard.** At session start, record the real registry's fingerprint (`lstat` presence, `st_ino`, `st_mtime_ns`, size and sha256) **if it is readable**. At session end, compare and fail the session on any change, naming the test-run window.
  - **Unreadable** (a sandboxed run sees `ENOENT`): the guard records "not observable" and passes. In that case the sandbox itself prevents the write.
  - The guard must not create the file or its directory.
- **Fix the leaking suite.** `tests/framework/test_hos_human_launcher.py` sets the override explicitly in the env it builds, rather than relying on inheritance. A fake `HOME` does not isolate, because `registry_path()` uses the passwd home.
- **Rejected:** making production `registry_path()` refuse the real path when `PYTEST_CURRENT_TEST` is set. That is test-awareness in a security module, and an environment variable an attacker can set.
- The stray `test_the_token_file_is_removed0` entry is pruned by `_live` on the next registration after its dir is reaped. No cleanup step.

### AD-11: `bin/hos-cron` fails closed on a tmp-root refusal: record, alert once, stop. Never fall back to `/tmp`. (BINDING; REQ-6, REQ-10, AF-9. New 2026-10-21, from the human's ruling.)

- **Trigger.** `HOS_TMP_SOURCE=inherited` after the guarded helper call (AD-1). That covers any resolver refusal, a crashed resolver, a missing `python3`, and a missing or broken helper. There is no other way to reach the trigger, and no way to bypass it. There is **no** environment-variable or config override that turns fail-closed back into fall-back. Adding one is a new human decision.
- **Sequence, in this order, all before the low-space trigger, preflight, auth, selection, any branch, any agent dispatch and any PR action:**
  1. **Log.** One `ERROR: HOS tmp root refused (<reason>) — cycle stopped; no work done` line, written to the cron log.
  2. **Audit, fail-closed.** Write `cycle-tmp-root-refused` (AD-2) by calling `cycle_log` directly, not through the `|| true` `_audit` wrapper, and keep its exit status. If the write fails, log `ERROR: audit write failed (rc=<n>)`, and the cycle still stops. "Fail-closed" here means that a failed audit can never turn into a cycle that continues. It does not mean that the alert is skipped.
  3. **Alert step, bounded.** This step runs under a hard timeout (`technical-design` sets it; it must be under the cron interval), and its own failure never changes step 4:
     - It reads a local alerted-state file, ~~`.claudetmp/tmp-root-alert-<role>.json`~~ *(amended in architecture review, 2026-10-21)* `$_HOS_DIR/tmp-root-alert/<role>-<project>.json` (`_HOS_DIR` is `${HOS_STATE_DIR:-$HOME/.hos}`, `bin/hos-cron:253`), beside the timeout breaker's `$_HOS_DIR/timeout-breaker/<role>-<project>` state. `.claudetmp/` is inside the clone and writable by the sandboxed agent of that role, so an agent could plant a "already alerted" state and suppress its own role's alert. `~/.hos` is outside every sandbox grant (`sandbox-policy.template.json:150`). The file is keyed by (clone, role, refusal fingerprint) and holds two independent flags, `filed` and `notified`.
     - **Alert-step temp location.** The alert step's subprocesses (`get_app_token.sh`, `create_issue.sh`, `post_comment.sh`, `notify_human.sh`; the first three each `mktemp` a token or body file) run with `TMPDIR` set to a dedicated `$_HOS_DIR/tmp-root-alert/tmp-<role>-<project>/` (0700, created by `bin/hos-cron`, emptied when the step ends), **never** the inherited `TMPDIR`. This is not under `HOS_TMP_ROOT`, so AD-1's single-`mkdir`-site invariant is untouched. It removes R-5's coupling: a refusal that coincides with a full `/tmp` (EDQUOT, the #2054 failure itself) no longer also blocks the alert, and the low-space trigger, which runs after the resolve block, cannot help because a refusing cycle never reaches it.
     - **If both flags say this refusal has already alerted:** no GitHub call, no notifier call. This is the "no duplicate alerts" path, and it is the steady state of every later refusing cycle.
     - **Otherwise:** mint the role's token through `bootstrap/get_app_token.sh` (never hand-rolled), and run the AD-9 interim filer (marker query, then file if absent). Set `filed` only after the item is confirmed (filed, or found already open). A failed query or failed filing leaves `filed` unset, so the next refusing cycle retries. If the item already existed (for example, the state file was lost), set both flags and **do not** notify again.
     - **The two channels are independent (amended in architecture review, 2026-10-21).** The #2125 call is made when `notified` is unset and either a new item was filed **or filing failed**. It is not conditional on GitHub success: a second channel that only fires after the first succeeds is not a second channel. If filing failed, the notifier body says the GitHub item could not be filed and carries the full AD-11 content itself. Set `notified` only on a delivered or `alert-undelivered`-recorded call (ADR-1605 AC-39: an absent notifier is recorded once, not retried every cycle). The mint is skipped when `filed` is already set, so a notifier-only retry costs no token.
     - **Fingerprint.** `refusal_class`, plus the sorted blockers, plus `role_dir`. A changed blocker set while the item is open adds one comment to the open item, through `bootstrap/post_comment.sh`. It does not open a second item, and it does not make a second #2125 call.
     - **Halt and kill switch.** If `hos-halt` (or #1928's AD-10 kill switch, once it exists) is set, the alert step skips all GitHub and notifier writes. The event and the exit still happen.
  4. **Exit non-zero.** ~~Exit with a dedicated code (`technical-design` picks it; 78/EX_CONFIG is suggested)~~ *(amended in architecture review, 2026-10-21)* Exit **77** (`EX_NOPERM`: the role dir's trust was refused). 78 is **not** dedicated: `bin/hos-cron` already exits 78 for a missing `claude` (`:137`), a missing auth env (`:157`), a malformed cycle id (`:359`), preflight failures (`:854`, `:990`, `:1004`, `:1014`, `:1108`, `:1116`) and a missing prompt file (`:2121`), and `tests/automation/test_hos_cron.py` pins 78 for those. **Selection rule:** the code must not appear in any other `exit` in `bin/hos-cron` (today it uses 0, 1, 75 and 78; the lock-held, suspended, cheap-skip and halt exits are all 0). A static test pins that `exit 77` occurs exactly once in `bin/hos-cron`, on this path. If a future change needs 77 elsewhere, it picks another unused code and amends this ADR. The `EXIT` trap still releases the lock. A test pins that no work-stage function runs.
     - **Breakers do not count it.** The timeout breaker keys on the Claude session's own exit 124 (`:2144`), the usage-limit breaker is commented out (`:2214`), and the diverged-main (`:1534`) and baseline-repair (`:1789`) counters run after preflight. A refusing cycle reaches none of them, so it neither increments nor resets any of them: their state persists unchanged across a refusal outage. That is correct, because no session and no preflight ran. AD-11's alert state is the only state this condition keeps.
- **Clear path.** A later cycle that resolves cleanly deletes the state file. Once it is past auth, it runs the interim auto-close (AD-9). An auto-close failure is logged and retried next cycle, and it never stops the cycle.
- **"Never fall back to `/tmp`", precisely.** No cycle work runs under an inherited `TMPDIR`. The only process that runs after a refusal is the bounded alert step, ~~whose token mint creates one small temp file in the inherited `TMPDIR`~~ *(amended in architecture review, 2026-10-21)* and it runs with `TMPDIR` pointed at its own `~/.hos` dir (step 3), so nothing in a refusing cycle writes to the inherited `TMPDIR`. A test pins this with an unwritable inherited `TMPDIR`: the alert is still filed.
- **Alert content (REQ-6).** Body and title name:
  - the role, the host and the absolute clone path;
  - the absolute role-dir path;
  - the blocking entries;
  - the exact AD-4 remedy (the `mv` shape, and the `python3 <abs>/bootstrap/lib/hos_tmp_root.py mark --repo <clone> --role <role> --reviewed` command);
  - that the remedy must run **unsandboxed, in your own terminal**;
  - that **this role is stopped** and does no work until the dir resolves.

  For `refusal_class=helper-missing`, the remedy is instead "re-run `bootstrap/hos_install.sh` for this clone, or restore `bootstrap/lib/hos_tmp_env.sh` from git". The `mark` command is not shown, because it would not help.
- **Overseer.** The same rule applies, under the overseer's own App identity. A stopped overseer merges nothing. That is the ruling's intent ("no cycle runs"), and the alert says so.
- **Landing order (ruling; not open to an agent-side waiver).** S2 merges **with or after S4a**, and **only after every live role dir on the dev machine resolves cleanly.**
  - Today that is false for Worker (`percommit-2054`, §8 N-1), and for Human until S3 merges or the human acts.
  - The agent side cannot verify this, because the registry is masked inside the sandbox (AF-1). The S2 PR body therefore carries the exact read-only commands for the human to run unsandboxed in their own terminal. The human's approval of the protected-surface PR is the attestation that they passed.
  - ~~(one `resolve` per clone and role, without `--create`)~~ *(Amended in architecture review, 2026-10-21.)* **`resolve` without `--create` is not a check.** It only computes `<root>/<RoleDir>` and prints it (`hos_tmp_root.py:501-508`, the whole body is under `if create:`). It never reads the registry, so it passes on a refused dir. The command is instead the read-only `status` subcommand that S4a adds (AD-12), one line per live (clone, role): Worker/worker, Overseer/overseer, Human/human and the Local entries. Every line must exit 0. `resolve --create` must not be offered as the check either: it would adopt as a side effect.
  - **Why human-attested is acceptable here, and stays so.** No mechanical check can run on the agent side, and a CI check would see a fresh runner, not the dev machine. A PR-body check that the output was pasted is gameable by the author. What bounds the risk is AD-11 itself: a false attestation produces a stopped cron role that alerts on its first cycle, which is loud and remediable, not silent. S2 must not add an agent-side bypass to compensate (the Trigger's "no override" rule).
  - The overseer may not merge S2 on its own authority. The path is protected, and the human gate applies anyway.

### AD-12: Install verifies every role dir, and fails on refusal, including the v0.6.0 upgrade path. (BINDING; REQ-11, AF-10. New 2026-10-21, from the human's ruling.)

- **Site.** `bootstrap/hos_install.sh`, after `config.sh` is final, on both the interactive and non-interactive paths. This is unchanged from AD-7(b).
- **Upgrade write.** If the target `config.sh` has no `HOS_TMP_ROOT` line (the v0.6.0 case), the install writes `HOS_TMP_ROOT=<default>` **before** registering:
  - `<default>` comes from `hos_tmp_root.py`, which owns the default and validation (`install.sh:254-275`). The installer does not compute it.
  - ~~The write goes through the same non-interactive key-append mechanism used for other new keys (`hos_install.sh:1717`), using #2059's injection-safe writer once #2059 merges. ... If S4a is built before #2059 merges, it rebases onto #2059, and the PR body states the dependency.~~ *(Amended in architecture review, 2026-10-21.)* S4a must not add a second `config.sh` writer, and it must not wait on #2059 either: #2059 is escalated and unmerged, and S4a → S2 → the v0.7.0 release would otherwise all hang on it. The rule:
    - **If #2059 has merged when S4a is built,** S4a uses #2059's writer.
    - **Otherwise,** S4a extends the existing key-append site (`hos_install.sh:829-848`) so it can append one value, and it writes `HOS_TMP_ROOT` only if the value from `install-default` passes `hos_tmp_root.py validate` **and** matches `^[A-Za-z0-9._/~-]+$`. A value outside that set fails the install non-zero (exit 77, below) with "set `HOS_TMP_ROOT` in `config.sh` by hand, then re-run". That is fail-closed, writes no unquotable byte, and needs no shell quoting at all. The S4a PR body names #2059 as the writer that later absorbs it, and #2059's rebase onto S4a is #2059's obligation.
  - An existing value, including one a human set in `install.sh`'s interactive prompt, is never overwritten.
  - REQ-11's phrase "`install.sh` writes it" is satisfied in substance. AF-10 explains why the site is `hos_install.sh`.
- **Register, then verify.**
  - **Register:** for each of `worker`, `overseer`, `human` and `local`, run `resolve --create` (AD-7(b)).
  - ~~**Verify:** for each one, a second, independent resolver call must return exit 0 **and** a stdout path equal to `<HOS_TMP_ROOT>/<RoleDir>`. This catches a registration that "succeeded" against a different path, which is what makes verification more than a repeat.~~ *(Amended in architecture review, 2026-10-21.)* That check was vacuous. `resolve_role_dir` always returns the computed `root / ROLE_DIRS[role]` (`hos_tmp_root.py:506-507, 552`), so the path comparison cannot fail, and a second `resolve --create` is only a repeat.
  - **Verify (binding):** a registry **read-back**. S4a adds a read-only `hos_tmp_root.py status --repo <clone> --role <role>` subcommand. It performs no `mkdir`, chmod, registration or marker write (a test pins all four). It reads the registry and reports, using the existing functions only (`resolve_root`, `_require_private_dir(tighten=False)`, `is_registered(role_dir, lstat, repo_real)`):
    - exit **0**: the dir exists, is a private owned real dir, and is registered for this (repo, role) at its live inode;
    - exit **1**: not registered. It prints whether the dir would be adopted, and if not, the `adoption_problems` blockers. This is reporting, not a decision: it grants nothing, and FU-1's "second decision path" concern does not apply, because the only caller that acts on it refuses;
    - exit **2**: structural (symlink, owner, wrong case, root invalid) or the registry is unreadable or masked (`ENOENT` from a sandbox is reported as "cannot verify; re-run unsandboxed", never as "not registered").
    The install's verify passes only if every role's `status` exits 0. The same subcommand is the S2 landing-precondition check (AD-11).
  - **Placement and the "complete-but-untrusted" state (amended in architecture review, 2026-10-21).** ~~S4a places register-and-verify after every other state-changing step, so that a failed verify leaves a complete install whose temp dirs are not yet trusted.~~ Register-and-verify runs after the agents and `.hos-manifest` are written and **immediately before the `.hos-release` commit point** (`hos_install.sh:2502-2511`), and so before the install-via-PR step. A failed verify exits **77** without stamping `.hos-release` and without opening the install PR. That reuses the installer's existing #277 rule ("the agents were written, but `.hos-manifest` / `.hos-release` are NOT stamped. Fix the cause and re-run", `:1703`). For automation (#2137, a consumer's upgrade script) the state is then unambiguous: the version stamp still says the old release, so "installed" means "installed and its temp dirs trusted", and a re-run takes the same upgrade path again. A complete-looking v0.7.0 stamp over untrusted dirs is never written.
  - **Refused:** any refusal makes the install print, for each refused dir, the role dir, the blocking entries and the exact AD-4 remedy, and that re-running after the remedy is safe (idempotent). Exit **77** is not used elsewhere in `hos_install.sh` (it uses 0, 1, 2, 4, 5 and signal codes), and the same selection rule as AD-11 step 4 applies.
  - Neither step ever passes `--reviewed` (AD-5).
- **Where it runs.** `hos_install.sh` runs in the human's own terminal, unsandboxed, so the registry is readable. If the registry is unreadable (for example, the installer was run from a sandboxed session), that is reported as a verify failure, with the instruction to re-run unsandboxed. It is **never** a pass.
- **`--dry-run`.** It writes nothing, registers nothing, and prints what it would do.

### AD-13: Release gate: v0.7.0 does not ship until the consumer-upgrade smoke test (#2137) passes. (BINDING; REQ-12. New 2026-10-21, from the human's ruling.)

- This is a release gate, not a slice. Cutting the v0.7.0 release requires #2137 to be green on the release candidate.
- **Recommended scope for #2137, for its owner to adopt (not filed here):**
  - a v0.6.0 consumer, with a `config.sh` lacking `HOS_TMP_ROOT`, upgraded to the candidate;
  - AD-12 writes the key, and registers and verifies all four dirs;
  - one worker and one overseer cron cycle resolve cleanly (`cycle-start` `tmpdir_source=resolver`);
  - a negative case: a planted non-allowlisted entry fails the install non-zero.

  If #2137's scope as built omits these, the release owner must state which REQ-11 AC it does not exercise.

---

## 3. Failure modes

*(Amended 2026-10-21.)* The four rows marked *Superseded* are kept so that the change in direction stays visible. The rows after them replace them.

| Failure | Behaviour | Direction |
|---|---|---|
| ~~Resolver refuses (any reason)~~ *Superseded 2026-10-20 for cron* | ~~No export. `HOS_TMP_SOURCE=inherited`. WARN plus a full-identity event. #1928 counts it.~~ | ~~Loud, never fatal~~ |
| ~~Resolver crashes (traceback)~~ *Superseded 2026-10-20 for cron* | ~~As refused. The reason is the last line, sanitised.~~ | ~~Loud, never fatal~~ |
| ~~Export helper missing (partial install)~~ *Superseded 2026-10-20 for cron* | ~~`source` fails. The launcher must treat this as refused and continue, never abort a cycle.~~ | ~~Fail-open on temp, loud~~ |
| ~~Install-time pre-registration fails~~ *Superseded 2026-10-20* | ~~Printed with its remedy. The install continues. The first launcher retries.~~ | ~~Loud, non-fatal~~ |
| `hos-cron`: resolver refuses, crashes, or `python3` is missing | `cycle-tmp-root-refused` with full identity, then the alert step (first refusal only), then a non-zero exit before any work. No export, and no fallback (AD-11). | **Fail-closed**, loud, alerted once |
| `hos-cron`: export helper missing or broken | The guarded source treats it as a refusal (`refusal_class=helper-missing`). The rest is as above, with the reinstall remedy (AD-1, AD-11). | **Fail-closed**, loud, alerted once |
| `hos-cron`: refusal audit write fails | `ERROR` is logged. The alert step still runs, and the cycle still exits non-zero (AD-11 step 2). | Fail-closed |
| `hos-cron`: alert step fails or times out (token, query, filing, notifier) | Logged. The unset flag (`filed` or `notified`) stays unset, so the next refusing cycle retries that channel only. A GitHub failure does not suppress the #2125 call (AD-11 step 3, channel independence). The exit is unchanged. A failed dedup query files nothing (breaker idiom). | Fail-closed on the cycle; at-least-once alert per channel, retried |
| `hos-cron`: both cron roles refuse **and** both alert channels fail (amended in architecture review, 2026-10-21) | Every cycle of both roles stops with exit 77, writes its event and logs `ALERT UNDELIVERED`, and retries both channels. Nothing reaches the human until a channel recovers (R-7). | Fail-closed, silent to the human until a channel recovers |
| `hos-cron`: repeated refusal while the item is open | Event only. No GitHub or notifier call (the state file holds). | No duplicate alert |
| `hos-cron`: #2125 notifier absent (until #2125 lands) | `alert-undelivered` event. The GitHub item is the channel (ADR-1605 AC-39 rule). | Loud, degraded channel |
| `hos-human`: refusal or missing helper | Banner, the `cycle-tmp-root-fallback` event (best-effort), then `exec` with the inherited `TMPDIR` (AD-3). | Fail-open, prominent |
| S4b wrapper: refusal or missing machine-copy helper | Banner to the journal, then `exec` without export. No clone audit (AF-11). | Fail-open, prominent |
| Install: verify refuses a role dir | Blockers and remedy printed. The install exits 77 before the `.hos-release` stamp and before the install PR, so the old version stamp stays. Re-running is idempotent (AD-12). | **Fatal to the install**, loud |
| Install: computed `HOS_TMP_ROOT` fails the charset gate (pre-#2059 writer) | Nothing is written. Exit 77 with "set it by hand" (AD-12). | Fatal, loud |
| Install: registry unreadable (run sandboxed) | Treated as a verify failure, with the "re-run unsandboxed" instruction (AD-12). | Fatal, loud |
| Upgrade: `config.sh` lacks `HOS_TMP_ROOT` | The resolver's default is written through the shared key-append writer, then the install registers and verifies (AD-12). | Self-healing |
| Wrapper resolves but the command fails | Command exit status is passed through (`exec`). | Unchanged |
| Machine copy absent or stale | The unit's `ExecStart` fails if absent (systemd shows it). If stale, see AD-7 version skew. | Loud |
| A tool name planted as a symlink | Not a real dir, so it blocks adoption (AD-6). | Closed |
| An allowlisted name holding `.git`/`.claude`/`scripts` | Blocks adoption (invariant 2). | Closed |
| Audit write fails in `hos-human` | Ignored (`|| true`). The session starts. | Fail-open on audit, by design (interactive) |
| Real registry changed during tests | The session fails (AD-10). | Loud |

**Residuals (stated, not hidden).**
- **R-1.** A non-HOS writer that recreates a deleted role dir and populates it before any HOS launcher or wrapper runs still produces a refusal. It is not prevented. ~~AD-9 makes it visible within K worker cycles.~~ *(Amended 2026-10-21.)* For a cron role, it now **stops** that role until the human acts, and it alerts on the first refusal (AD-11). That is the ruling's chosen trade: availability is given up so that the cycle never runs degraded. For `hos-human`, it shows the banner.
- ~~**R-2.** Until #1928 S6 lands, a persistent refusal is recorded in the audit trail and the cron log on every cycle, but no human item is filed (under the ESC-3 default).~~ *Superseded 2026-10-20.* S2's interim filer files on the first refusal (AD-9, AD-11).
- **R-3.** Sandboxed agents in the Worker, Overseer and Human clones can still edit their clone's `bootstrap/lib/hos_tmp_root.py`, which `bin/hos-cron` and `bin/hos-human` then run unsandboxed. This is the pre-existing posture (#1146) and is not widened here. AD-7 avoids extending it to systemd units.
- **R-4.** The (installing clone, other role) registry keys from AD-7(b) are inert but count toward the 256 cap.
- ~~**R-5 (added 2026-10-21).** The alert step's token mint writes one small temp file under the inherited `TMPDIR` (often `/tmp`) and removes it. ... If `/tmp` itself is full (EDQUOT), the mint fails, and the alert is retried on the next cycle.~~ *Closed in architecture review, 2026-10-21:* the alert step runs with its own `TMPDIR` under `~/.hos` (AD-11 step 3), so it writes nothing to the inherited `TMPDIR` and a full `/tmp` cannot block it. What remains: if `~/.hos` itself cannot be written (a full home filesystem), the alert step fails and retries, and the cron log records it.
- **R-7 (added in architecture review, 2026-10-21): both roles stopped and both channels down.** If the worker and the overseer both refuse (for example, one shared cause such as a re-pointed `HOS_TMP_ROOT`), and GitHub filing and #2125 both fail persistently (an App key revoked, #2125 not yet landed), HOS is fully stopped and the human is told nothing. Channel independence, per-cycle retry and the `~/.hos` temp location make this need two independent, persistent failures, not one. It is not eliminated: no in-process alert can survive the loss of every outbound channel. The backstop is out-of-process liveness (the human, or an external heartbeat, noticing no activity). That is FU-2, not this ADR.
- **R-6 (added 2026-10-21).** A refusal confined to `.tmp/Human` is never escalated (ESC-3(ii)). It is visible only in the banner and the event. A sandboxed agent can also cause a refusal of its own cron role (AD-5 "outside the threat"), for example by deleting and recreating its role dir, which changes the inode. Under fail-closed, that is now a denial of service that stops the role, rather than a degraded run. The alert makes it visible at once, and the remedy is the human's.

---

## 4. Slices (each ≤15 files including tests; each independently mergeable)

*(Amended 2026-10-21.)* Struck rows are superseded. S1 has merged (PR #2140).

| # | Slice | Files | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | REQ-9 test isolation (AD-10). **Merged (PR #2140).** | `tests/conftest.py`, `tests/framework/test_hos_human_launcher.py`, `tests/framework/test_registry_isolation.py` (new): 3 | **No** (tests only) | — | done |
| ~~**S2**~~ | ~~Export site (AD-1), event identity and REQ-8 fields (AD-2), `hos-human` parity (AD-3), remedy text (AD-4), REQ-1 invariant test.~~ *Superseded by the row below.* | — | — | — | — |
| **S2** *(amended)* | Export site with guarded sourcing (AD-1); `cycle-tmp-root-refused` and the REQ-8 fields (AD-2); **cron fail-closed** (AD-11), including the bounded alert step, the state file and the #2125 call; the **interim marker-keyed filer and auto-close** (AD-9, the former S5′); the `hos-human` banner and parity (AD-3); remedy text (AD-4); REQ-1 invariant test. | `bootstrap/lib/hos_tmp_env.sh` (new), `bin/hos-cron`, `bin/hos-human`, `bootstrap/lib/hos_tmp_root.py` (`_remedy` text only), `scripts/automation/lib/cycle_log.py` (docstring), `scripts/framework/framework_consumer_files.txt` (ship the helper), `tests/automation/test_hos_cron.py`, `tests/automation/test_hos_cron_tmp_root_refusal.py` (new: the REQ-10 matrix and the filer), `tests/framework/test_hos_human_launcher.py`, `tests/framework/test_hos_tmp_root.py` (message assertions only), `tests/framework/test_hos_tmp_env.py` (new), `tests/framework/test_tmp_root_single_site.py` (new), `SCRIPTS-INDEX.md`: 13 | **Yes**: `bin/**`, `bootstrap/**`, `scripts/framework/**` | S1 (merged). **S4a merged first, or in the same PR.** | Human approval, **plus the AD-11 landing precondition**: every live role dir resolves cleanly, as attested by the human in the PR. `reliability-reviewer` and `privacy-reviewer` mandatory. The PR states the conflict with #1928 S6 |
| **S3** | Adoption policy (AD-6) and the new invariant-2 tests (AD-5); REQ-3 mixed-fixture test (AD-8). | `bootstrap/lib/hos_tmp_root.py` (constant, `adoption_problems`, module docstring), `tests/framework/test_hos_tmp_root.py`, `tests/automation/test_hos_cron.py` (REQ-3 fixture), `docs/CRON-SETUP.md` (adoption list sentence): 4 | **Yes**: `bootstrap/**` | ~~S2~~ *(amended)* None for the guard change. The REQ-3 fixture's fail-closed half needs S2, so if S3 lands first, that half moves into S2's test file. | ESC-1 ruled A. `security-reviewer` mandatory |
| **S4a** *(amended)* | Install-time pre-registration (AD-7(b)), **verify and fail on refusal, and the v0.6.0 `HOS_TMP_ROOT` write** (AD-12), and the REQ-2 simulation test for a fresh install. | `bootstrap/hos_install.sh`, `tests/…/test_hos_install_*` (the existing install suite, plus clean, refused and v0.6.0-upgrade cases), `tests/framework/test_tmp_root_first_writer.py` (new), `tests/framework/test_install_tmp_root_verify.py` (new; it also asserts that the install contains no `--reviewed`, a check moved here from `test_tmp_root_single_site.py`, which S2 now creates later), and *(added in architecture review, 2026-10-21)* `bootstrap/lib/hos_tmp_root.py` (the read-only `status` subcommand only) and `tests/framework/test_hos_tmp_root.py` (`status` cases: exit 0/1/2, no side effects, masked registry is exit 2): 6 | **Yes**: `bootstrap/**` | ~~S2~~ *(amended)* None (it calls the resolver directly). It uses #2059's writer if #2059 has merged, and otherwise the charset-gated extension of the existing append site (AD-12); it does **not** wait on #2059. | ESC-2 ruled b. `reliability-reviewer` mandatory |
| **S4b** | Machine-copy wrapper (AD-7(d)) with the fail-open banner and no clone audit (AF-11), its installer, and the doc rewrite. **Conditional for v0.7.0 (ruling).** | `bootstrap/hos-with-tmp` (new; bundle file), `bootstrap/hos_bootstrap.sh` (install the copies), the release-bundle file list pinned by `tests/framework/test_tmp_reaper_packaging.py`, `CLAUDE.md` (`:376`), `docs/CRON-SETUP.md`, `docs/SANDBOX-POLICY.md`, `tests/framework/test_hos_with_tmp.py` (new), `tests/framework/test_tmp_reaper_packaging.py` (or a sibling packaging test), `tests/framework/test_tmp_root_single_site.py` (docs assertion), `tests/framework/test_tmp_root_first_writer.py` (wrapper case), `SCRIPTS-INDEX.md`: ≤11 | **Yes**: `bootstrap/**`, `CLAUDE.md` | S2 (helper). S4a is optional. | ESC-2 ruled d. `security-reviewer` mandatory (AF-2) |
| **S5** *(amended)* | REQ-6 content and K = 1 (AD-9, AM-2, AM-8), delivered in ADR-1928 S6, which replaces S2's interim filer. No further #2100 code. | none in #2100. #1928 S6 carries the fixture and deletes the interim filer. | — | #1928 S6 | ESC-3 ruled (i) |
| ~~**S5′**~~ | ~~*Only if ESC-3 rules a one-off:* marker-keyed condition filer in `bin/hos-cron`.~~ *Superseded 2026-10-20: folded into S2 (AD-9 interim filer).* | — | — | — | — |

~~**Order.** S1 → S2 → {S3, S4a, S4b in any order; S3 and S4a both touch tests that S2 created, so they rebase serially}.~~
**Order (amended 2026-10-21).** S1 (done) → S4a → S2 → S4b. S3 goes in any position, preferably before S2, because it self-heals `.tmp/Human` and so helps satisfy S2's landing precondition. S2 may instead ship in the same PR as S4a. It may **not** merge before S4a.

~~**Codable before any human answer:** S1 and S2.~~ *(Amended.)* All ESCs are ruled. S3, S4a and S2 are codable now. S4b is codable, but conditional for v0.7.0.

**Merge gates beyond the human approval of protected paths:**
- S2 is gated on the AD-11 landing precondition.
- The v0.7.0 release is gated on #2137 (AD-13).
- §8 N-1 (the Worker dir unblock) is a human act, and it is a practical prerequisite for S2.

**#1928 coordination.** #1928 S6 edits the same `bin/hos-cron` block as S2 (AD-2 conflict notice). Whichever lands second rebases. If S6 lands second, it replaces S2's interim filer with its conditions-only entry point (AM-8) and deletes the duplicate.

### Test obligations (all deterministic; the registry is always the override, never the real file)

- **S1:**
  - a launcher test that previously leaked now writes only to the override;
  - the guard fails a planted test that writes the real-path fingerprint target;
  - the guard passes when the real registry is unreadable.
- **S2:**
  - success path: the three variables are exported, `HOS_TMP_SOURCE=resolver`, and `cycle-start` carries `tmpdir_source=resolver` with a `~`-redacted `tmpdir`;
  - ~~fallback path: nothing is exported, and the event carries `role`, `project`, `cycle_id`, `tmpdir_source=inherited`, `tmpdir` and `reason`;~~ *(superseded for cron; see the REQ-10 matrix)*
  - ~~an overseer fallback records `role=overseer`;~~ *(amended)* an overseer refusal records `role=overseer` and stops the overseer;
  - a crashed resolver yields the last line;
  - control bytes are stripped;
  - the helper never exits non-zero under `set -euo pipefail`;
  - a missing helper file, and a helper that sources but defines no `hos_tmp_export`, both yield `HOS_TMP_SOURCE=inherited` through the guard, not a `set -e` abort;
  - **REQ-10 matrix** (fake GitHub, fake notifier, override registry; each case asserts that no work-stage function ran, using a sentinel stub on the first post-auth stage):
    - (a) refusal: non-zero exit with the dedicated code, one `cycle-tmp-root-refused` event with every AD-2 field, exactly one filed item (marker-keyed, into the target milestone), one notifier call, and the state file written;
    - (b) missing helper: identical, except for `refusal_class=helper-missing` and the reinstall remedy;
    - (c) second and third refusals: one event each, and no GitHub write and no notifier call;
    - (d) audit write fails: still a non-zero exit, no work, and the alert still attempted;
    - (e) a failed dedup query: nothing filed, no state file, and the next refusal retries;
    - (f) state file lost while the item is open: no second item and no second notifier call;
    - (g) a changed blocker set: one comment on the open item, and no new item;
    - (h) notifier absent: an `alert-undelivered` event, and the item is still filed;
    - (h2) filing fails but the notifier is present: the notifier is still called once, with the "GitHub item could not be filed" body; the next refusal retries filing only, and does not notify again;
    - (h3) an unwritable inherited `TMPDIR`: the alert is still filed, and nothing is written under the inherited `TMPDIR`;
    - (h4) a planted alert-state file under the clone's `.claudetmp/` has no effect (the state lives under `$_HOS_DIR`);
    - (h5) the exit code is 77, and `exit 77` appears exactly once in `bin/hos-cron`;
    - (i) halt set: the event and the exit, with no GitHub or notifier write;
    - (j) clean resolve after a refusal: the state file is removed, and the item auto-closes past auth;
    - (k) a cron `cycle-start` never carries `tmpdir_source=inherited`;
    - (l) no environment variable or config key turns fail-closed off (static assertion);
  - the alert body contains the role dir, the blockers, the `mv` shape, the `mark` command, "unsandboxed" and "this role is stopped";
  - `hos-human` refusal writes exactly one event with `role=human`, `launcher=hos-human` and no `cycle_id`, prints the **banner** (header, role dir, `mark` command) and the fixed unsandboxed line, and still reaches `exec`. The same holds with a missing helper, and the session still launches when the audit write fails;
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
  - a fresh install creates, registers **and verifies** four dirs (override registry), and exits 0;
  - the export-only plus third-party-write plus launcher sequence succeeds;
  - ~~an install into a root holding a refused dir prints the remedy and exits 0;~~ *(superseded 2026-10-20)* an install into a root holding a refused dir prints the blockers and remedy for that dir and **exits non-zero**, after completing every other step; a re-run after the remedy exits 0;
  - a verify against a different path than `<HOS_TMP_ROOT>/<RoleDir>` fails;
  - an unreadable registry fails the verify, with the "re-run unsandboxed" message;
  - **v0.6.0 upgrade:** starting from a `config.sh` with no `HOS_TMP_ROOT`, both the non-interactive and the interactive paths end with `HOS_TMP_ROOT` written once (through the shared writer) and all four dirs registered and verified. An existing `HOS_TMP_ROOT` value is never overwritten;
  - `--dry-run` writes nothing;
  - the install never passes `--reviewed`;
  - *(added in architecture review, 2026-10-21)* a failed verify exits 77 and leaves `.hos-release` at the old tag with no install PR opened; a registration planted in a different (override) registry than the one `status` reads fails the verify; `status` makes no `mkdir`, chmod, registration or marker write, and reports a masked registry as exit 2; a computed value outside the charset gate writes nothing and exits 77 (pre-#2059 writer only).
- **S4b:**
  - the wrapper execs with the exports on success;
  - on refusal, or with a missing machine-copy helper, it execs without them, with the **banner** and remedy on stderr, and it runs no clone file;
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

*(Amended 2026-10-21.)* pm-agent recorded the human ruling in the requirements at `0949fc54b` (REQ-6, REQ-7 and REQ-8 amended; REQ-10 to REQ-12 added). AM-2 and AM-3 are amended by AD-9 and AD-8 above. Two new amendments are cross-issue, not edits to REQUIREMENTS-2100:
- **AM-8 → ADR-1928 AD-7 / S6.**
  - (1) The `tmp-root-fallback` key has K = 1, both to open and to clear. That needs a per-key K, where AD-7 currently has one global K.
  - (2) S6 exposes a conditions-only entry point that `bin/hos-cron`'s pre-auth refusal path can call with its own minted token, outside the normal attention-pass placement. AF-9 is why: the refusing cycle never reaches the pass. This extends ADR-1928 AF-7's residual for this one key. It does not move the pass.
  - (3) S6 adopts S2's interim filer's open issue by marker, and deletes the filer.
  - (4) The Done-when becomes "the next cycle of that role resolves the dir" (it previously read "no longer emits `cycle-tmp-root-fallback`").
- **AM-9 → #2125.** Add `tmp-root-refused` to `notify_human.sh`'s closed trigger list. Dedup and rate limiting stay #2125's job. The S2 PR body discloses this.

**Inconsistencies with REQUIREMENTS-2100 as amended (recorded for pm-agent; this ADR does not edit the requirements):**
- **REQ-11** says "`install.sh` writes it". The binding behaviour is met in `hos_install.sh` (AF-10, AD-12), because `install.sh` never runs on a non-interactive upgrade.
- **REQ-7** groups S4b with `hos-human` under "the audit write here is best-effort". S4b writes no clone audit at all (AF-11). Its record is the journal banner.
- **REQ-6** (K-clear auto-close) is now K = 1 for clearing as well (AD-9). The requirement is consistent with that, because it reuses the same K.
- **REQ-10** lists `bot` in the identity. Before auth, only the configured bot login is known. The event marks it `bot_source=config` (AD-2).

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible, sanctioned by the requirements:**
  - a clearer refusal message;
  - `hos-human` audit;
  - new audit fields;
  - ~~a `needs-human` item after K refusals (via #1928).~~ *(Amended 2026-10-21.)* A `needs-human` item, plus a #2125 alert, on the **first** cron refusal (AD-9, AD-11), and the stopped cron role itself. The human sanctioned both in the 2026-10-20 ruling.
- **Routed, not sanctioned:**
  - **The guard's input set** grows by three names (ESC-1). This is a security-guard change.
  - **A new operational surface (ESC-2).** Machine copies of the resolver, helper and wrapper in `~/.local/share/hos/`, refreshed by `hos_bootstrap.sh`, and a **manual, machine-local edit to the human's `claude-rc.service`** to adopt the wrapper.
  - **The data-retention surface (ESC-2(b)).** Install now writes four registry entries per installing clone. The **delete-authority grant** that registration means is extended to four freshly created, empty dirs at install time, rather than at first launch.
  - **A new human-facing filing (ESC-3).** Its timing depends on #1928 S6.
- **Amendment (2026-10-21): the checkpoint was cleared by the human directly.** Fail-closed adds a user-visible failure mode: a cron role stops, and a merge-capable overseer stops merging. It also adds a new human-facing alert on the first refusal, a second alert channel (#2125), and a new install failure mode. Each of these would ordinarily be routed. Here the human ruled them on 2026-10-20 (verbatim above), so they bind as given. Two details are this ADR's technical choices within the ruling, and are disclosed rather than routed:
  - ~~the alert step's small token-file use of the inherited `TMPDIR` (R-5);~~ *(closed in architecture review, 2026-10-21: the alert step now uses its own `~/.hos` temp dir)*;
  - *(added in architecture review, 2026-10-21)* exit 77 for both a refusing cron cycle and a failed install verify; the #2125 call being made even when GitHub filing fails; a failed install verify leaving the old `.hos-release` stamp. Each is a reading of the ruling's own words ("alerts once via needs-human and #2125"; "fail the install on refusal"), and none adds a user-visible behaviour the ruling did not ask for;
  - the S4b journal-only audit (AF-11).

  If the human reads either as outside the ruling, it is a one-line change in technical design.
- **Cost:** none (local file operations only). **New trust boundary:** none created. AD-7 deliberately avoids creating one (AF-2). Without AD-7, option (a) as drafted would have created one.
- **Startup gap: yes.** TD-2054:705 assumed the live role dirs held only HOS names, and that "the first launcher or inner-loop run registers them". It did not decide what registers a dir for non-launcher sessions, although it documented those sessions. That should have been settled in #2054's architecture. **Recommendation to the worker:** annotate #2100 (or open) a `startup-artifact-gap` issue against #2054. I have not filed it, per this task's instructions.
- **Affected sign-offs.**
  - **#2054 S2a resolver security review.** Its approval of the adoption allowlist covers `HOS_ONLY_RE` only. If ESC-1 is (A), the S3 `security-reviewer` sign-off must explicitly re-review the adoption rule as a whole, not only the diff. The registry, re-point, inode, case and ownership approvals stand, because they are untouched (AD-5).
  - **#2054 launcher design (TD §2A.3).** Superseded in shape by AD-1's single export site, not in behaviour. The S2 reviewers re-check fail-open behaviour against TD §2A.3.
  - **#2054 reaper sign-offs** stand, because the reaper is untouched.
  - **ADR-1928 AD-7** stands. AM-2 adds content to its body and does not change its mechanism. *(Amended 2026-10-21.)* AM-8 **does** change AD-7's mechanism: it adds a per-key K and a pre-auth entry point. Any review of ADR-1928 AD-7 / S6 design must re-check against AM-8 before S6 is built. Nothing in S6 has been built, so no code approval is orphaned.
- **Affected sign-offs: the 2026-10-20 amendment (startup-gap recovery).** *Should this have been settled in the initial review?* Partly. The initial review chose fail-open for cron on availability grounds, without asking the human whether an unattended cycle may run degraded. That is a product question this ADR should have routed, and it is a `startup-artifact-gap` against this ADR itself. **Recommendation to the worker:** annotate #2100 with it. Not filed here, per this task's instructions.
  - **S1 (PR #2140, merged)** stands. It is tests only, and touches no launcher behaviour.
  - **The original ADR-2100 approvals, on AD-1, AD-2, AD-7(b) and AD-8's "loud, never fatal" direction,** are superseded. Any technical-design for S2 or S4a drafted against them must be re-reviewed against AD-11 and AD-12. No S2 or S4a code was built, so no code approval is orphaned.
  - **The #2054 launcher sign-offs (TD-2054 §2A.3, "never fatal")** cover code that **is built and live**: `bin/hos-cron:376-391` and `bin/hos-human:113-127`. Those approvals stand for the code as it is, but its cron behaviour is now deprecated by ruling. S2's reviewers must explicitly review the reversal of §2A.3's never-fatal rule for cron, not only the diff. `reliability-reviewer` owns that.
  - **#2059's approvals** (unmerged, local branch) stand. S4a adopts its `config.sh` writer if #2059 has merged; otherwise S4a's charset-gated append is absorbed by #2059 on its rebase (AD-12). Neither invalidates the other's approvals, but #2059's re-review on rebase must cover the absorbed `HOS_TMP_ROOT` write.

---

## 7. Open human escalations

*(Amended 2026-10-21.)* **All four are ruled (2026-10-20). None is open.** The rulings are recorded in the table below. The table itself is kept as the record of what was asked.

| ESC | Ruling (2026-10-20) |
|---|---|
| ESC-1 | **A**, matching the recommendation. AD-6 binds. |
| ESC-2 | **b + d**, matching the recommendation. AD-7 binds. Install-time registration also verifies and fails on refusal (AD-12). S4b is conditional for v0.7.0. |
| ESC-3 (i) | **#1928 owns**, matching the recommendation. The fail-closed ruling's first-refusal alert supersedes "no #2100 one-off": S2 carries a marker-keyed interim filer (AD-9). |
| ESC-3 (ii) | **Concur.** |
| ESC-4 | **Rejected**, matching the recommendation. |
| (new) fail-closed | Cron fail-closed (AD-11), install verify (AD-12), release gate on #2137 (AD-13). |

No new human escalation is opened by this amendment. The AD-11 landing precondition and the §8 N-1 unblock are human **acts**, not questions.

Original positions (2026-10-15), kept for the record:

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
amended: 2026-10-21
ruling: {by: ScottThurlow, date: 2026-10-20, ESC-1: A, ESC-2: b+d, ESC-3: {i: 1928-owns, ii: concur}, ESC-4: rejected, fail_closed_cron: true}
done: [S1]
codable_now: [S3, S4a, S2]
conditional: [S4b]
superseded: [S5prime]
order: [S1, S4a, S2, S4b]   # S3 anywhere, preferably before S2
merge_gates:
  S2: ["S4a merged or same PR", "every live role dir: hos_tmp_root.py status exits 0 (human-run, human-attested)", "human approval (protected)"]
exit_codes: {hos-cron_tmp_root_refused: 77, hos_install_verify_failed: 77}
  S5: ["#1928 S6 (AM-8)"]
release_gate: {v0.7.0: "#2137 green"}
hard_constraints_not_waivable: [REQ-5, AD-5, AD-11 landing order]
# Original escalation record (all ruled 2026-10-20):
escalations:
  - {id: ESC-1, tier: hard-tradeoff, options: {A: exact-tool-names, B: structural, C: unchanged}, recommended: A, gates: [S3], note: security guard input set}
  - {id: ESC-2, tier: hard-tradeoff, options: {a: execstartpre-machine-copy, b: install-preregister, c: a+b, d: machine-copy-wrapper}, recommended: b+d, gates: [S4a, S4b], note: operational surface + manual unit edit}
  - {id: ESC-3, tier: hard-tradeoff, options: {i-default: 1928-owns-no-oneoff, i-alt: marker-keyed-oneoff, ii: hos-human-no-escalation}, recommended: [i-default, ii], gates: [S5, S2]}
  - {id: ESC-4, tier: hard-tradeoff, options: {reject: refuse-and-escalate, accept: quarantine-then-adopt}, recommended: reject, gates: []}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **N-1 (out of scope, human act).** `.tmp/Worker` still needs the human to `mv` `percommit-2054` out, or run `mark --reviewed`, unsandboxed. `.tmp/Human` self-heals on its next `hos-human` launch only if ESC-1 is (A) and S3 has merged. Until then it also needs the human. No slice of this ADR performs either act. *(Amended 2026-10-21.)* ESC-1 is now ruled (A). Under AD-11 this is no longer cosmetic: if S2 merged with `.tmp/Worker` still refused, the worker would stop at once. N-1 is therefore a practical prerequisite of S2's landing precondition.
- **N-2 → pm-agent.** `cycle_log.log_event` defaults `role` to `"worker"` for every event that omits it (AF-4). Other hos-cron events that omit `role=` (for example `cycle-start`) are mislabeled for the overseer. S2 fixes only the two temp events. A general fix is a separate issue.
- **N-3.** The `mktemp` rule (CLAUDE.md "Temp and working-state locations" rule 1) could name the failure mode ("a hand-named dir in `HOS_TMP_ROOT` blocks adoption"). That is optional, and if wanted it rides in S4b's `CLAUDE.md` edit.
- **FU-1.** If the attention pass (#1928) ever needs to diagnose without a fresh refusal, a read-only `hos_tmp_root.py diagnose` subcommand could emit the blockers as JSON. It is not needed now. AD-2's `HOS_TMP_REASON` suffices, and a second decision path invites drift. *(Review note 2026-10-21.)* AD-12's `status` subcommand is not this: it reads the registry and reports; it never grants. If `diagnose` is ever wanted, it extends `status`, not a new subcommand.
- **FU-2 (added in architecture review, 2026-10-21).** An out-of-process liveness signal (for example, an external heartbeat that alerts when no cron cycle of a project has reached `cycle-start` in N hours) would close R-7. It is not scoped to #2100, and it is named here only.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every slice except S1 is on protected surface. S3 changes the input set of a guard that protects other projects' files from chmod and reaping. S4b adds an unsandboxed execution path for systemd units (made safe by machine copies, AF-2). S2 rewrites the launch block of every cron cycle and human session.
CONFIDENCE: HIGH on AF-1 (sandbox grants and `read_registry`'s `ENOENT` behaviour read in this session), AF-2 (`allowWrite` covers the clones; `denyWrite` covers only `bin/`), AF-3 (test comment), AF-4 (live event shape), and AD-5's invariants (each mapped to code lines read here). MEDIUM on AD-7's machine-copy version-skew argument, and on the exact interaction of S2 with #1928 S6's edit of the same block, which `technical-design` must sequence.
BLAST RADIUS: the temp-dir selection of every HOS cron cycle and human session (S2); the adoption decision for unregistered role dirs on every machine (S3); project installs (S4a); machine bootstrap and the operator's systemd units (S4b); the audit event schema for two events (S2). No gate, label, merge, approval or reaper path changes.
Change classification: STRUCTURAL. It adds a registration obligation at install and at session start for non-launcher sessions, adds a shared export site and machine copies, and may widen a security guard's accepted inputs (ESC-1).

**Amendment flag (2026-10-21).**
- RISK: HIGH, raised in substance. AD-11 adds a cycle-stopping failure mode to every worker and overseer cycle, a pre-auth GitHub write path, and a new install failure mode.
- CONFIDENCE: HIGH on AF-9 (the resolve block's position before auth was read in this session at `bin/hos-cron:376-391`, against ADR-1928 AF-7 and AD-2), and on AF-10 (`hos_install.sh:1715-1745`). MEDIUM on the alert step's bounded-timeout and state-file design, which `technical-design` must make concrete, and on the S2/#1928 S6 rebase in `bin/hos-cron`.
- BLAST RADIUS: added since the original ADR are the availability of every cron role (fail-closed), the success or failure of every project install and upgrade, and one new human-facing issue class.

## Human Review Required

~~ESC-1 (a security-guard change) and ESC-2 (...) must be answered by you before S3, S4a and S4b merge. ESC-3 sets whether #2100 files anything itself ... ESC-4 asks you to confirm a rejection.~~ *(Amended 2026-10-21.)* All ESCs were ruled by you on 2026-10-20, and this amendment records that ruling. What still needs you:
- **(1)** Your own-account approval of each protected slice's PR.
- **(2)** Before S2 merges: the N-1 unblock of `.tmp/Worker`, and your attestation in the S2 PR that every live role dir resolves cleanly. Run the read-only commands the PR body gives, unsandboxed.
- **(3)** The #2137 smoke test passing before v0.7.0 is cut.

REQ-5, AD-5 and the AD-11 landing order are not open to an agent-side waiver.
