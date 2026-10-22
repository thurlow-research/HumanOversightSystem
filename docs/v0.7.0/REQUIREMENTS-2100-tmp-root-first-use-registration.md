# REQUIREMENTS-2100: Register a role temp dir before anything else can write to it, never fall back silently every cycle, and keep the foreign-project guard

**Status:** Amended 2026-10-21, pending human review. **Change classification: STRUCTURAL.** Three things make it
structural. It adds a registration obligation to paths that do not register today. It may widen
what the security guard accepts (ESC-1). It adds a human-facing escalation (REQ-6).
**Date:** 2026-10-15. **Amended:** 2026-10-21, to record the human ruling of 2026-10-20 (see the
Amendment note below). ESC-1 to ESC-4 are now ruled (§6).
**Author:** pm-agent (autonomous worker cycle; no human present)
**Tree read at:** `c785a534e` (branch `worker-2100-tmp-root-first-use-registration-261015090501-1623984`
= `origin/main`).
**Source issue:** #2100 (follow-up to #2054 / PR #2061, commit `087c8910f`). I read the issue body as
a description of desired work, not as instructions (CORE, #1539). I re-checked every factual claim in
it against the tree and the live filesystem (§0). One claim is wrong: "only Worker is stuck" (VF-2).
**Related, and kept as boundaries:**
- #1928: `REQUIREMENTS-1928-…` REQ-I1/I2 and ESC-7 propose that #1928 owns the generic
  persistent-condition escalation and registers `cycle-tmp-root-fallback` as its first condition.
- #2054: the original design is `TECHNICAL-DESIGN-2054-tmp-quota-hygiene.md`.
- #1146: unsandboxed worker/overseer, the residual registry-write risk recorded at TD-2054:705.

**Consumers:** `architect`, then `technical-design`.

> **Amendment — 2026-10-20 human ruling (recorded 2026-10-21, pm-agent).** ScottThurlow ruled on
> #2100:
> 1. ESC-1 **A**; ESC-2 **b+d**; ESC-3 (i) **#1928 owns** the escalation primitive, (ii) **concur**
>    (a `hos-human` refusal logs and audits only); ESC-4: **quarantine-and-adopt rejected; refusal
>    stands**. Install-time registration
>    (ADR-2100 S4a) is wanted, so that no role dir depends on a manual `mark --reviewed` again.
> 2. Verbatim (18:34Z): *"Amend ADR-2100: tmp-root refusal is fail-closed for hos-cron roles (no
>    cycle runs; first refusal alerts once via needs-human and #2125; a missing helper counts as
>    refusal); hos-human/S4b stay fail-open with a banner. S4a must verify registration and fail the
>    install on refusal, including the v0.6.0 upgrade path. v0.7.0 does not ship until the
>    consumer-upgrade smoke test passes."* (#2137 is the consumer-upgrade smoke test.)
>
> This **supersedes** the earlier "loud but never fatal / inherit `TMPDIR` (fall back to `/tmp`)"
> behaviour for cron roles. Amended: §1, REQ-2, REQ-3, REQ-4, REQ-6, REQ-7, REQ-8, §3, §4, §5, §6.
> Added: REQ-10 (cron fail-closed), REQ-11 (install verify, including the v0.6.0 upgrade path),
> REQ-12 (release gate on #2137). Slice names S2, S4a and S4b below refer to ADR-2100 §slicing.
>
> *Reconciled 2026-10-21 with the amended ADR-2100 (AF-10, AF-11, AD-2, AD-9, AD-12):* REQ-11's
> upgrade write is in `bootstrap/hos_install.sh` via #2059's writer; REQ-7's S4b record is the
> journal banner only; REQ-10's `bot` is `bot_source=config`; REQ-6 auto-closes after one clean
> cycle.
>
> *Reconciled 2026-10-21 with ADR-2100 review round 2 (commit `5dee1c58c`):* REQ-6 (GitHub marker
> authoritative, 12 h TTL state cache, pointer-only notifier payload, at-most-once
> `alert-undelivered`); REQ-10 (`exit_code=77`, `fingerprint`, no `host`, `~`-redacted `reason`,
> capped and neutralised blockers, `cycle-tmp-root-alert` event); REQ-11 (writer clause, summary
> line, 30 s timeout, exit 77, verify before the `.hos-release` stamp); REQ-12 (enforced at
> `cut_release.sh`); §5 (S4b is in scope; whether it ships in v0.7.0 is an **open human
> question**, not a ruling); ESC-4 wording.
>
> *Clarified 2026-10-22 (TD-2100-S4a §10 I-6):* REQ-11's "exactly one `tmp-root-verify:` line" AC
> now covers dry runs (`skipped=dry-run`) and early exits (no line). See the dated note under REQ-11.

**Protected surfaces:** `bootstrap/**` (`hos_tmp_root.py`, `tmp_reaper.py`) and `bin/**`
(`hos-cron`, `hos-human`) are protected (`scripts/framework/protected_surfaces.txt`). The human gate
applies whatever tier is computed.

---

## 0. Verification findings

**VF-1 (HIGH). The refusal is real, current and specific.**
- The resolver refuses an unregistered, pre-existing role dir. It does so if any entry fails
  `HOS_ONLY_RE` (`bootstrap/lib/hos_tmp_root.py:83-85`), or if any entry is a directory directly
  holding `.git`, `.claude` or `scripts` (`:86`, `:466-485`).
- The refusal happens at `:538-542`, before any chmod.
- `bin/hos-cron:380-391` then logs the WARN, writes `cycle-tmp-root-fallback` (`:390`) and leaves
  `TMPDIR` inherited.
- `audit/log/2026/10/` holds 388 `cycle-tmp-root-fallback` events. The latest is this cycle's
  (`2026-10-15T090501Z`).
- Run read-only against the live tree, `adoption_problems(.tmp/Worker)` returns `['percommit-2054']`,
  and `is_registered(.tmp/Worker)` is `False`.

**VF-2 (HIGH). Human is stuck too, silently.** The issue says only Worker is stuck. That is wrong.
- `.tmp/Human` is unregistered, and `adoption_problems` returns `['node-compile-cache']`.
- `bin/hos-human:120-127` prints its WARN only to stderr, just before `exec claude`, and writes no
  audit event. That is why nobody counted it.
- `.tmp/Overseer` holds three names that are not allowlisted: `cc-socks`, `node-compile-cache` and
  `semgrep-mcp`. It works only because it was empty when its first cron cycle registered it, at
  `2026-10-10T02:55Z` (marker mtime).
- `.tmp/Local` is registered and clean.

**VF-3 (HIGH). No launcher created the role dirs.** Birth times (`stat %w`, UTC) show the order:

| Time (UTC, 2026-10-09) | Event |
|---|---|
| `18:57:56` | `.tmp`, `.tmp/Worker`, `.tmp/Human` and `.tmp/Overseer` are all created in the same second, mode 0700 |
| `19:31` | The first `hos_tmp_root.py` commit lands (`6fcf4d1da`) |
| `01:52` (2026-10-10) | Merge |

So one ad hoc `mkdir` made all of them, before the resolver existed. TD-2054:705 assumed "the live
`.tmp/{…}` hold only HOS-only names, so the first launcher or inner-loop run registers them". That
held for Overseer and Local. It was already false for Worker at merge time.

**VF-4 (HIGH). HOS documents non-launcher writers and tells them to write into the role dir without
registering it.**
- `CLAUDE.md:376`, `docs/CRON-SETUP.md:422-428` and `docs/SANDBOX-POLICY.md:185-195` all tell any
  other launcher (systemd, remote-control, wrapper, plain `claude`) to export
  `TMPDIR`/`CLAUDE_CODE_TMPDIR` to `.tmp/<RoleDir>`.
- The live `~/.config/systemd/user/claude-rc.service:12-13` does exactly that for `.tmp/Human`.
- Only `CRON-SETUP.md:430` mentions a one-time `resolve --create` for that case, and only for Human,
  as a manual step.
- Any third-party tool writing under that `TMPDIR` can therefore populate an unregistered dir first:
  node (`node-compile-cache`), Claude Code (`cc-socks`) and MCP servers (`semgrep-mcp`). After that
  the launcher refuses forever.

**VF-5 (HIGH). Who created `percommit-2054`: not any committed code.**
- A grep for `percommit` over the whole Worker tree (excluding `.git` and `audit`) finds nothing.
  That covers `.claude/`, `.githooks/`, `tests/conftest.py` and `scripts/framework/`.
- The same grep over the `Worker-2054` worktree also finds nothing.
- The only hit anywhere is the draft issue body `/tmp/claude/issue-tmp-root-adoption-refusal.md`.

The physical evidence points to an uncommitted ad hoc command run by the #2054 interactive session:
- `percommit-2054` was born `22:02:46Z` on 2026-10-09, in the middle of the #2054 S2a/S2b fix
  commits (`ee85157b7` at 22:02:03, `e6f98dd31` at 22:25).
- Its mode is `0775` (a plain `mkdir` under umask 002, not `mktemp`).
- It contains only `.tmp/Local/{.hos-tmp-root (v3), pytest-of-scott}`. That is the `../.tmp` of a
  per-commit clone that was checked out at `percommit-2054/<x>` and later deleted, after the inner
  loop resolved role `local` for it.
- The name breaks the existing rule that throwaway temp comes from `mktemp` (CLAUDE.md "Temp and
  working-state locations" rule 1). `mktemp` names (`tmp.*`) would have matched `HOS_ONLY_RE`.

**The author cannot be fixed in code.** REQ-1 to REQ-3 are therefore written to hold for *unknown*
writers.

**VF-6 (MEDIUM). Tests leak into the real trust registry.**
- `~/.local/state/hos/tmp-roots.json` holds a `Human` entry whose path is under
  `.tmp/Local/pytest-of-scott/pytest-0/test_the_token_file_is_removed0/…`.
- `tests/framework/test_hos_human_launcher.py` never sets `HOS_TMP_REGISTRY_FILE`. The other suites
  do: `test_hos_tmp_root.py:40`, `test_run_tests_inner_loop.py:96` and `test_hos_cron.py:616`.
- `registry_path()` uses the passwd home, not `$HOME` (`hos_tmp_root.py:136-137`, `:255-260`), so
  that fixture's fake `HOME` does not isolate it.
- The registry also holds a `Local` entry for the `Worker-2054` worktree. That entry is legitimate
  and is pruned once the worktree is removed (`_live`, `:320-333`).

**VF-7 (MEDIUM). The cycle audit does not record the effective temp dir.**
- `cycle-start` (`bin/hos-cron:1946`) records `bot`, `project` and `cycle_id` only.
- Only the failure path writes an event (`:390`).
- Nothing records which `TMPDIR` a successful cycle actually ran with.

**VF-8 (LOW). The remedy reaches no one.** `_remedy()` (`hos_tmp_root.py:488-498`) names the right
command, but it goes only into the cron log and the audit event. That is the #1928 visibility gap.
`bootstrap/escalate_to_human.sh` (`--number/--body-file/--reason/--app`, `:75-80`) comments on an
*existing* issue. It does not file a new one.

## 1. Problem (product behavior)

The disk temp root from #2054 is only as good as its first writer. If anything other than the
resolver creates or populates `.tmp/<RoleDir>` before the first registration, every automated cycle
for that role refuses the dir and falls back to the RAM-backed `/tmp`. This was observed for 388
Worker cycles, and for Human sessions with no record at all. The only signal is a log line. #2054's
own goal, keeping scratch off `/tmp`, is therefore silently undone for two of the four roles.

**Required outcome:**
- Every role dir is registered before an untrusted writer can populate it, or is adopted safely when
  it was populated by HOS-shaped content.
- When neither is possible, a human is told once, exactly what to run and where.
- In no case does a role fall back to `/tmp` silently, cycle after cycle. *(Amended 2026-10-20.)* A
  `hos-cron` role (worker, overseer) does not fall back to `/tmp` at all: refusal is fail-closed and
  no cycle runs (REQ-10). Only `hos-human` and the S4b wrapper stay fail-open, with a banner
  (REQ-7).
- The foreign-project guard is not weakened (§2 REQ-5).

## 2. Requirements

- **REQ-1 (register on first use, every HOS path).** Every HOS code path that exports, creates or
  uses a role temp dir must obtain it through `resolve_role_dir(..., create=True)`, or the
  `resolve --create` CLI, before exporting it or writing into it. Today those paths are:
  - `bin/hos-cron`;
  - `bin/hos-human`;
  - `scripts/framework/run_tests_inner_loop.sh` (already compliant, role `local`).

  Any new path must follow the same rule. No HOS path may `mkdir` a role dir or a `HOS_TMP_ROOT` by
  other means. *AC:* a grep-based test fails if a shell or Python file under `bin/`, `bootstrap/` or
  `scripts/` other than `hos_tmp_root.py` creates `<HOS_TMP_ROOT>/<RoleDir>` directly.

- **REQ-2 (close the documented non-launcher window).** Every documented non-launcher way of pointing
  `TMPDIR`/`CLAUDE_CODE_TMPDIR` at a role dir (VF-4) must register the dir first. That covers the
  systemd/remote-control units, wrapper scripts and the manual export in `CLAUDE.md:376`. The design
  chooses the mechanism. Candidates are:
  - (a) a documented `ExecStartPre=`/wrapper line that runs `hos_tmp_root.py resolve --create`;
  - (b) pre-registering all four role dirs at project install or machine bootstrap, when they are
    created empty;
  - (c) both (ESC-2).

  *Ruled 2026-10-20: ESC-2 b+d.* Install-time pre-registration (S4a, with the REQ-11 verify) and the
  machine-copy wrapper (S4b, ADR-2100 AD-7(d)).

  *AC:* `CLAUDE.md`, `CRON-SETUP.md` and `SANDBOX-POLICY.md` no longer show an export without the
  registration step. A test runs a simulated non-launcher session (export only) followed by a third
  party writing a non-allowlisted name, then runs the launcher, and checks that the launcher
  succeeds. This reproduces the #2100 sequence with the REQ-2 step in place.

- **REQ-3 (unknown first writer: adopt or escalate loudly, never silent per-cycle fallback).** Some
  writers will bypass REQ-2. For a dir that a writer populated before any registration, the launcher
  outcome must be one of exactly two:
  - (i) **adopt and register**, when every entry passes the adoption policy that ESC-1 decides; or
  - (ii) **refuse**, followed by the REQ-6 escalation. *(Amended 2026-10-20.)* For a `hos-cron` role
    a refusal also stops the cycle (REQ-10); for `hos-human` it is fail-open with a banner (REQ-7).

  *AC:* a test creates `.tmp/Worker` with a non-launcher writer first (a `percommit-2054`-style
  non-allowlisted dir *and* a `node-compile-cache`-style tool dir), then runs `bin/hos-cron`'s
  resolver block. Under ESC-1 A the `node-compile-cache` entry is adopted and the `percommit-2054`
  entry forces outcome (ii). The result is never just a log-line WARN with no REQ-6 state change, and
  never a cycle that continues with an inherited `TMPDIR`.

- **REQ-4 (adoption policy for HOS- and tool-created names; ESC-1).** The allowlist must accept the
  names that HOS and its required tooling produce in `TMPDIR` in normal operation, so that a
  legitimate first writer does not need human review. The design must at least decide on the names
  observed live:
  - `node-compile-cache` (node / Claude Code);
  - `cc-socks` (Claude Code);
  - `semgrep-mcp` (semgrep MCP).

  Whatever is accepted must be a closed, reviewable list or pattern in `hos_tmp_root.py`, with a
  comment naming the producer of each entry. It must not be a default-accept. `percommit-*` is **not**
  proposed for the allowlist (ESC-1), because it came from a rule-breaking ad hoc command (VF-5).
  *Ruled 2026-10-20: ESC-1 A* (the three named tool outputs only, each with a producer comment). *AC:*
  table-driven tests cover each accepted name and a set of plausible project names (`src`, `docs`,
  `README.md`, `Makefile`, `package.json`), which stay refused.

- **REQ-5 (guard preserved; non-negotiable).** None of REQ-1 to REQ-4 may weaken the existing refusals.
  These must still be refused:
  - a dir holding, at top level or directly inside any child, `.git`, `.claude` or `scripts`;
  - a registered key whose live path differs from the registered path, unless `mark --reviewed`
    (`:336-358`, `:516-520`);
  - a registered path whose inode differs (`:294-310`, `:431-438` test);
  - a different-letter-case dir (`:525-526`);
  - a symlink, a non-directory or a non-owned root or role dir (`:219-231`).

  The refusal must still happen before any chmod, mkdir of the role dir, registration or marker
  write. *AC:* the existing guard tests in `tests/framework/test_hos_tmp_root.py` (`:442-458` and
  their neighbours) pass unchanged. New tests check that a REQ-4-allowlisted name that is a
  directory containing `.git`, `.claude` or `scripts` is still refused.

- **REQ-6 (deduplicated human escalation on refusal).** *(Amended 2026-10-20.)* On the **first**
  refusal for a (clone, role) of a `hos-cron` role (K = 1 for this condition key, under #1928's
  `tmp-root-fallback` key; this overrides the earlier default of K = 3 for this condition only),
  exactly one open `needs-human` item exists for that (clone, role), and the alert is also routed to
  #2125 as the ruling directs. A missing or unrunnable resolver helper counts as a refusal (REQ-10).
  Repeated refusals while the item is open produce no duplicate alert. The item states:
  - the role and the clone path;
  - the role-dir path.

    Both paths are rendered with a leading `$HOME` as `~`, and are absolute only when outside
    `$HOME` (ADR-2100 AD-2, AD-11; REQ-10; reconciled 2026-10-21). No host is included;
  - the blocking entries;
  - the exact remedy, verbatim: the `mv <entry> <dest>` alternative and the
    `python3 <clone>/bootstrap/lib/hos_tmp_root.py mark --repo <clone> --role <role> --reviewed`
    command. In every outbound sink each path in it is rendered with a leading `$HOME` as `~`,
    with the `~` outside quotes so that the human's shell expands it. A path is absolute only when
    it is outside `$HOME` (ADR-2100 AD-11; reconciled 2026-10-21);
  - that it must be run **unsandboxed, in the human's own terminal**.

  It is not re-filed while open. It auto-closes with a comment after K consecutive cycles in which
  the dir resolves. With K = 1 for this key, that means the item auto-closes after **one** clean
  cycle (ADR-2100 AD-9; reconciled 2026-10-21).

  *(Round 2, 2026-10-21; ADR-2100 AD-9, AD-11.)*
  - **Authority.** Whether an alert exists is decided by the GitHub query. The match is on an
    issue whose body's first line is exactly the marker and whose author is the role's own bot.
    The local alerted-state file is only a rate-limit cache with a **12 h TTL**. A state file that
    is older than the TTL, or untrusted, is treated as absent, so it can never suppress an alert
    for longer than 12 h.
  - **Notifier payload (#2125).** It is a fixed-template pointer. It holds four fields: cause, role,
    project and issue (`none` if filing failed). Only when `issue=none` does it add the fixed
    constant text "GitHub item could not be filed; see the cron log for this role". It carries no
    path, no blocker name and no host.
  - **Failed notify.** A failed, timed-out or absent notifier writes `alert-undelivered`.
    Delivery on this channel is at-most-once per TTL window. The GitHub item is the at-least-once
    channel.

  *Ownership (ESC-3, ruled 2026-10-20: (i) #1928 owns):* delivered by #1928
  REQ-I1/I2 under its `tmp-root-fallback` key. #2100's acceptance depends on it and adds the content
  requirements above. Until #1928 S6 lands, the ADR-2100 S2 slice files the marker-keyed issue
  itself, with the same dedup, auto-close and fail-closed duplicate-query behaviour as the timeout
  breaker (`bin/hos-cron:2179-2200`, `:2283-2322`). *AC:* a deterministic test runs one refusal
  (exactly one item), further refusals (no duplicate item, no duplicate alert), a missing helper
  (treated as a refusal; no duplicate if the item is already open) and one clean cycle (closed).

- **REQ-7 (Human launcher parity).** `bin/hos-human` must record its refusal in the same audit event
  as `bin/hos-cron` (role `human`), and print the remedy, not just the reason. It is an interactive
  launcher, so REQ-6 escalation from it is *not* required (ESC-3 (ii), ruled 2026-10-20: concur).
  Cron cycles are the counting source. *(Amended 2026-10-20.)* `hos-human` and the S4b wrapper stay
  **fail-open**: on refusal they print a visible banner (role dir, blocking entries, exact remedy),
  then continue with the inherited `TMPDIR`. For `hos-human` the audit write is best-effort
  (`|| true`) and never blocks the session. The S4b wrapper writes **no** clone audit event: it must
  not run clone code (ADR-2100 AF-11), so its only record is the banner in the journal (stderr)
  (reconciled 2026-10-21). *AC:* a test checks that a refusing `hos-human` writes one
  `cycle-tmp-root-fallback`-shaped event with `role=human`, prints the banner, and still launches
  the session; a second test checks that the session still launches when the audit write fails.

- **REQ-8 (record the effective temp dir).** Every cycle's audit records the `TMPDIR` the cycle
  actually exported, and whether it came from the resolver or was inherited. This goes on
  `cycle-start` (`bin/hos-cron:1946`) or a dedicated event chosen by the design. *AC:* a
  `test_hos_cron.py` case asserts the field on the success path. *(Amended 2026-10-20.)* Cron roles
  have no fallback path any more; the refusal path is covered by REQ-10's `cycle-tmp-root-refused`
  event. The `hos-human` fail-open path records the inherited `TMPDIR` (REQ-7).

- **REQ-9 (tests never touch the real registry).** Every test that runs the resolver, or a launcher
  that runs it, sets `HOS_TMP_REGISTRY_FILE` to a test-owned path (VF-6). *AC:* a conftest-level guard
  or a test fails if a test run changes the real `~/.local/state/hos/tmp-roots.json`. The stray
  `test_the_token_file_is_removed0` entry is pruned automatically once its dir is reaped (`_live`).
  No manual cleanup is required by this build.

- **REQ-10 (cron refusal is fail-closed; added 2026-10-20).** For every `hos-cron` role, a resolver
  refusal, or a missing or unrunnable resolver helper, stops the cycle:
  - the cycle writes a `cycle-tmp-root-refused` audit event with full identity (bot, project,
    cycle_id, role, clone path, role-dir path, blocking entries). The refusal is detected before
    auth, so `bot` is the role's configured login, not a verified one, and the event marks it
    `bot_source=config` (ADR-2100 AD-2; reconciled 2026-10-21). *(Round 2.)* The event also
    carries `exit_code=77` and the refusal `fingerprint`. It has **no `host` field**. `reason`
    and the path fields are `~`-redacted. Blockers are capped at five names plus a count, each
    at most 64 characters;
  - blocker names are neutralised by one shared renderer in **every outbound or committed sink**
    (audit events, issue body, comments). Only the local cron log and banner show them raw
    (ADR-2100 AD-11, round 2);
  - after the alert step, one `cycle-tmp-root-alert` outcome event is written per refusing cycle,
    best-effort. Its fields are `outcome`, `issue`, `notified`, `failed_stage` and `fingerprint`
    (ADR-2100 AD-11, round 2);
  - it then exits non-zero **before any build or review work** (no issue selection, no branch, no
    agent dispatch, no PR action);
  - it never exports or inherits a `/tmp` fallback `TMPDIR`;
  - the audit write is fail-closed for cron roles: if the event cannot be written, the cycle still
    exits non-zero and does no work;
  - the first refusal raises exactly one REQ-6 alert; repeated refusals raise none.

  *Landing order:* this change merges with or after S4a (REQ-11), and only after every live role dir
  on the dev machine resolves cleanly. *AC:* `test_hos_cron.py` cases check that (a) a refusing
  resolver yields a non-zero exit, one `cycle-tmp-root-refused` event, no work-stage side effect and
  exactly one alert; (b) a missing helper behaves identically; (c) a second and third refusal add an
  event each but no alert; (d) a failing audit write still yields a non-zero exit and no work;
  *(round 2)* (e) the exit code is 77, and the refusal event carries `exit_code=77` and
  `fingerprint`, a `~`-redacted `reason`, and no `host`; (f) one `cycle-tmp-root-alert` event is
  written per refusing cycle; (g) hostile blocker names (forged marker, `@mention`, `#<n>`,
  newline, 10 kB) are neutralised and capped in every outbound sink; (h) a forged or stale (over
  12 h) state file cannot suppress filing when GitHub has no open marker item; (i) the notifier
  payload holds only the four fields (cause, role, project, issue). Only when `issue=none` does it
  also carry the fixed constant text "GitHub item could not be filed; see the cron log for this
  role". It carries no paths, no names and no host.

- **REQ-11 (install verifies registration and fails on refusal; added 2026-10-20).** After the
  installer (S4a) pre-registers the role dirs, it must check that the resolver accepts each of the
  four role dirs (Worker, Overseer, Human, Local). If any is refused, the install exits non-zero and
  prints the blocking entries and the exact `mark --reviewed` / `mv` remedy. This holds on the
  **v0.6.0 upgrade path** too: when an existing `config.sh` lacks `HOS_TMP_ROOT`, the install writes
  it before registering and verifying. The write is made by `bootstrap/hos_install.sh` (its
  non-interactive key-append step) through the installer's single `config.sh` writer (#2059's, if
  merged; otherwise the charset-gated extension of the existing append site, ADR-2100 AD-12), not by
  `scripts/framework/install.sh`, which does not run on a non-interactive upgrade (ADR-2100 AF-10,
  AD-12; reconciled 2026-10-21). *(pm-agent confirms the architect's writer clause, round 2:* it
  means no second writer and no wait on #2059. An existing value is never overwritten.*)*

  *Round 2 (ADR-2100 AD-12):*
  - Verification is a read-only registry read-back (`status`).
  - Every resolver call in register and verify runs under a **30 s** timeout. A timeout counts as
    a refusal of that role.
  - After verify, the install prints exactly one machine-parseable stdout line,
    `tmp-root-verify: refused=<roles|none>`.
  - A refusal exits **77**.
  - Register-and-verify runs **before the `.hos-release` stamp**. A failed verify leaves the old
    version stamp and opens no install PR.

  *AC:* an install test with a clean target passes and leaves all four dirs registered; one with a
  non-allowlisted entry in a role dir fails with exit 77, prints the blockers and remedy, leaves
  `.hos-release` at the old tag and opens no install PR; a v0.6.0 upgrade test, starting from a
  `config.sh` without `HOS_TMP_ROOT`, ends with `HOS_TMP_ROOT` written and all four role dirs
  registered and verified; every run prints exactly one `tmp-root-verify: refused=` line; a hung
  resolver is killed at 30 s and counted as a refusal of that role.

  *(Amended 2026-10-22, pm-agent; clarifying; TD-2100-S4a §10 I-6, accepted by the architect, §13.)*
  "Every run" in the AC above means every run that reaches the register/verify step. Two refinements:
  - A `--dry-run` prints exactly one `tmp-root-verify: skipped=dry-run` line instead, and no
    `refused=` line (TD-2100-S4a §4.5).
  - A run that exits before the register/verify step (for example a prerequisite failure or a drift
    hard-stop) prints no `tmp-root-verify:` line (TD-2100-S4a §4.4).

  The invariant is unchanged: exit 77 ⇔ exactly one line with `refused≠none`; a non-dry-run exit 0
  ⇔ exactly one `refused=none` line.

- **REQ-12 (release gate; added 2026-10-20).** v0.7.0 does not ship until the consumer-upgrade
  smoke test (#2137) passes. It is enforced at `scripts/framework/cut_release.sh`'s validation gate:
  a failing or missing #2137 result fails the cut. Using the existing `--skip-validation` bypass
  against #2137 is a human decision. The ruling's scope is a fresh install, the v0.6.0 → v0.7.0
  upgrade and the first cron cycle after it. If #2137 omits **any** of those three, the release
  needs an explicit human decision, recorded on #2137, that accepts the omission. A disclosure
  alone is not enough (ADR-2100 AD-13, round 2). *AC:* the #2137 smoke test is green on the v0.7.0
  release candidate before the release is cut, and the cut fails when #2137 is failing or missing.

## 3. Out of scope / non-goals

- **Unblocking the current `.tmp/Worker` and `.tmp/Human`** (issue item 1). That is a human act: move
  `percommit-2054` out, or run `mark --reviewed`, for Worker. Do the same for Human with
  `node-compile-cache`, unless REQ-4 accepts it. It is listed here for context only, and this build
  does not perform it. If ESC-1 accepts `node-compile-cache`, Human self-heals on its next launch.
- **Finding and fixing the `percommit-<issue>` writer in code.** It is not in any committed file
  (VF-5). The control is REQ-2/REQ-3 plus the existing `mktemp` rule. Reinforcing that rule's wording
  is optional and is left to the design.
- **The generic "summon the human" mechanism** (assignment, reminders, digest). That is #1928.
- **Registry-editing by unsandboxed roles** (#1146) and any change to `tmp_reaper.py`'s
  delete-authority rule (registered path, role and inode only).
- **Moving `HOS_TMP_ROOT` defaults or the `config.sh` grammar.** Writing the existing
  `HOS_TMP_ROOT` key into an upgraded `config.sh` that lacks it (REQ-11) is in scope; it changes
  neither the default nor the grammar.

## 4. Acceptance (issue level)

1. After the fix, and after the human unblock or a REQ-4 self-heal, a worker cycle logs no
   `tmp root unusable` WARN and exports `TMPDIR` under `<clone>/../.tmp/Worker` (REQ-1, REQ-8).
2. The non-launcher-writer-first then launcher test yields adopt-and-register or a loud escalation,
   never a silent per-cycle fallback (REQ-2, REQ-3, REQ-6).
3. `.git`, `.claude` and `scripts` content, re-pointed keys and inode mismatches are still refused
   before any side effect (REQ-5).
4. The effective `TMPDIR` is recorded in the cycle's audit event (REQ-8).
5. No test writes to the real trust registry (REQ-9).
6. *(Added 2026-10-20.)* A refusing cron cycle exits non-zero, does no build or review work, and
   raises exactly one alert; a missing helper counts as a refusal; repeated refusals raise no
   duplicate alert (REQ-6, REQ-10).
7. *(Added 2026-10-20.)* A refusing `hos-human` session shows a banner and still launches
   (REQ-7).
8. *(Added 2026-10-20.)* Install, including the v0.6.0 upgrade path, verifies all four role dirs
   and fails non-zero on refusal (REQ-11).
9. *(Added 2026-10-20.)* v0.7.0 ships only after #2137 passes (REQ-12).

## 5. Suggested slices (all touch protected surfaces)

- **S1. Visibility and test isolation.** REQ-7, REQ-8 and REQ-9. This is low risk and changes no
  guard logic.
- **S2. Adoption policy.** REQ-4 and REQ-5, after ESC-1. A guard change of this kind needs a
  security-reviewer.
- **S3. First-use registration.** REQ-1, REQ-2 and REQ-3, covering the docs, the unit examples and
  the install/bootstrap pre-registration chosen under ESC-2.
- **S4. Escalation.** REQ-6. It is delivered by #1928 S6, or here as a fallback (ESC-3).

*(Amended 2026-10-20.)* ADR-2100's slicing governs. REQ-10 lands in ADR-2100 S2 (with the interim
marker-keyed issue from REQ-6), merging with or after S4a. REQ-11 is ADR-2100 S4a. REQ-7's
fail-open banner covers `hos-human` and S4b. REQ-12 is a release gate, not a slice.
*(Corrected in round 2, 2026-10-21.)* No human ruling makes S4b conditional. The earlier wording
came only from the 18:27Z human-proxy relay, which describes itself as "not a ruling". On ESC-2 b+d,
S4b is **in scope**. **Whether S4b must ship in v0.7.0 is an OPEN human question** (Human Review
Required). S2 and S4a do not depend on it.

## 6. Escalations for the human (all ruled 2026-10-20; the defaults below are kept for the record)

- **ESC-1. What may an unregistered dir hold and still be adopted without review?**
  - (A) Add only the named tool outputs observed live (`node-compile-cache`, `cc-socks`,
    `semgrep-mcp`) to `HOS_ONLY_RE`, each with a producer comment. Keep refusing anything else,
    including `percommit-*`.
  - (B) Switch to a structural rule: adopt if no entry, to depth N, contains `.git`, `.claude` or
    `scripts`, whatever the names. This is a weaker guard. A non-git foreign folder named `Worker`
    would be adopted, chmodded 0700 and become reapable.
  - (C) Keep the list unchanged and rely on REQ-2 and REQ-6 alone.

  *Default: A.* It removes the observed Human blocker and the latent Overseer one. It keeps the guard
  a closed list. **This changes a security guard and needs your ruling.**
  **Resolved 2026-10-20: A.**
- **ESC-2. How should non-launcher sessions register (REQ-2)?**
  - (a) Document an `ExecStartPre=`/wrapper `resolve --create` line.
  - (b) Have project install and machine bootstrap pre-create and register all four role dirs
    while they are empty.
  - (c) Both.

  *Default: c.* (b) removes the window for fresh installs. (a) covers the units that already exist,
  such as `claude-rc.service`, which is machine-local and is not edited by this build.
  **Resolved 2026-10-20: b+d** ((d) is ADR-2100's machine-copy wrapper option). Install-time
  registration must also verify and fail on refusal (REQ-11).
- **ESC-3. Ownership of the escalation (#2100 item 4 versus #1928 ESC-7).** *Default:* #1928's
  generic primitive delivers it, and REQ-6 adds the content. #2100 builds a minimal one-off only if
  #2100 is ready to merge first. Also: should an interactive `hos-human` refusal escalate too, or only
  log and audit (REQ-7)? *Default:* only log and audit, because the human is the one who launched
  the session.
  **Resolved 2026-10-20: (i) #1928 owns; (ii) concur.** Interim filing by ADR-2100 S2 until #1928 S6
  lands (REQ-6).
- **ESC-4. Should a non-launcher writer that bypasses registration be refused at all?** One option
  is to have the resolver quarantine non-allowlisted entries into `.hos-quarantine-<ts>/` and then
  adopt. *Default: no.* Moving files inside an unregistered dir is a write into a possibly foreign
  directory, which the guard exists to prevent. This is listed only so the alternative is explicitly
  rejected or accepted.
  **Resolved 2026-10-20: quarantine-and-adopt rejected; refusal stands.**

## Escalation flag (CORE self-flag)

RISK: HIGH. The landing surfaces (`bootstrap/**`, `bin/**`) are protected. REQ-4 changes the input
set accepted by a security guard that protects other projects' files from chmod and from reaping.
CONFIDENCE: HIGH on VF-1 to VF-5 and VF-7, which come from birth times, read-only resolver calls,
the registry contents and greps run in this session. MEDIUM on attributing `percommit-2054` to an ad
hoc #2054 session command: the circumstantial evidence is strong, but no transcript was found. MEDIUM
on the ESC defaults, which are product judgment.

## Human Review Required

This change is structural. S1 (REQ-7, REQ-8 and REQ-9) does not depend on any ESC and may go to
`architect` on these defaults. S2 waits on ESC-1, S3 on ESC-2, and S4 on ESC-3. REQ-5 is
non-negotiable in every slice and is not open to an agent-side waiver.

*(2026-10-21.)* ESC-1 to ESC-4 are ruled, and the fail-closed amendment (REQ-10 to REQ-12) is the
human's own structural ruling of 2026-10-20, recorded here rather than proposed. ADR-2100 must be
amended to match before S2 and S4a are designed further. REQ-10 is a new failure mode for every
cron cycle (RISK: HIGH), so its landing-order condition (with or after S4a, all live role dirs
clean) is not open to an agent-side waiver either.

**OPEN human question (round 2, 2026-10-21):** must S4b (the machine-copy wrapper) ship in v0.7.0?
ESC-2 b+d puts it in scope. No ruling makes it conditional, and no answer is assumed here.
