# REQUIREMENTS-2100: Register a role temp dir before anything else can write to it, never fall back silently every cycle, and keep the foreign-project guard

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** Three things make it
structural. It adds a registration obligation to paths that do not register today. It may widen
what the security guard accepts (ESC-1). It adds a human-facing escalation (REQ-6).
**Date:** 2026-10-15
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
- In no case does a role fall back to `/tmp` silently, cycle after cycle.
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

  *AC:* `CLAUDE.md`, `CRON-SETUP.md` and `SANDBOX-POLICY.md` no longer show an export without the
  registration step. A test runs a simulated non-launcher session (export only) followed by a third
  party writing a non-allowlisted name, then runs the launcher, and checks that the launcher
  succeeds. This reproduces the #2100 sequence with the REQ-2 step in place.

- **REQ-3 (unknown first writer: adopt or escalate loudly, never silent per-cycle fallback).** Some
  writers will bypass REQ-2. For a dir that a writer populated before any registration, the launcher
  outcome must be one of exactly two:
  - (i) **adopt and register**, when every entry passes the adoption policy that ESC-1 decides; or
  - (ii) **refuse**, followed by the REQ-6 escalation.

  *AC:* a test creates `.tmp/Worker` with a non-launcher writer first (a `percommit-2054`-style
  non-allowlisted dir *and* a `node-compile-cache`-style tool dir), then runs `bin/hos-cron`'s
  resolver block. The result is (i) or (ii), as ESC-1 decides, and is never just a log-line WARN with
  no REQ-6 state change.

- **REQ-4 (adoption policy for HOS- and tool-created names; ESC-1).** The allowlist must accept the
  names that HOS and its required tooling produce in `TMPDIR` in normal operation, so that a
  legitimate first writer does not need human review. The design must at least decide on the names
  observed live:
  - `node-compile-cache` (node / Claude Code);
  - `cc-socks` (Claude Code);
  - `semgrep-mcp` (semgrep MCP).

  Whatever is accepted must be a closed, reviewable list or pattern in `hos_tmp_root.py`, with a
  comment naming the producer of each entry. It must not be a default-accept. `percommit-*` is **not**
  proposed for the allowlist (ESC-1), because it came from a rule-breaking ad hoc command (VF-5). *AC:*
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

- **REQ-6 (deduplicated human escalation on persistent refusal).** When the resolver refuses for the
  same (clone, role) on K consecutive cycles (*default* K = 3, shared with #1928 REQ-I1), exactly one
  open `needs-human` item exists for that (clone, role). It states:
  - the role and the absolute clone path;
  - the absolute role-dir path;
  - the blocking entries;
  - the exact remedy, verbatim: the `mv <entry> <dest>` alternative and the
    `python3 <abs>/bootstrap/lib/hos_tmp_root.py mark --repo <clone> --role <role> --reviewed`
    command;
  - that it must be run **unsandboxed, in the human's own terminal**.

  It is not re-filed while open. It auto-closes with a comment after K consecutive cycles in which
  the dir resolves. *Ownership (ESC-3):* by default this is delivered by #1928 REQ-I1/I2. #2100's
  acceptance depends on it and adds the content requirements above. If #1928's primitive has not
  landed when #2100 ships, #2100 delivers a minimal one-off with the same dedup, auto-close and
  fail-closed duplicate-query behaviour as the timeout breaker (`bin/hos-cron:2179-2200`,
  `:2283-2322`). *AC:* a deterministic test runs K-1 refusals (no item), K refusals (one item),
  further refusals (no duplicate) and K successes (closed).

- **REQ-7 (Human launcher parity).** `bin/hos-human` must record its refusal in the same audit event
  as `bin/hos-cron` (role `human`), and print the remedy, not just the reason. It is an interactive
  launcher, so REQ-6 escalation from it is *not* required unless ESC-3 says otherwise. Cron cycles
  are the counting source. *AC:* a test checks that a refusing `hos-human` writes one
  `cycle-tmp-root-fallback`-shaped event with `role=human`.

- **REQ-8 (record the effective temp dir).** Every cycle's audit records the `TMPDIR` the cycle
  actually exported, and whether it came from the resolver or was inherited. This goes on
  `cycle-start` (`bin/hos-cron:1946`) or a dedicated event chosen by the design. *AC:* a
  `test_hos_cron.py` case asserts the field on both the success and the fallback path.

- **REQ-9 (tests never touch the real registry).** Every test that runs the resolver, or a launcher
  that runs it, sets `HOS_TMP_REGISTRY_FILE` to a test-owned path (VF-6). *AC:* a conftest-level guard
  or a test fails if a test run changes the real `~/.local/state/hos/tmp-roots.json`. The stray
  `test_the_token_file_is_removed0` entry is pruned automatically once its dir is reaped (`_live`).
  No manual cleanup is required by this build.

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
- **Moving `HOS_TMP_ROOT` defaults or the `config.sh` grammar.**

## 4. Acceptance (issue level)

1. After the fix, and after the human unblock or a REQ-4 self-heal, a worker cycle logs no
   `tmp root unusable` WARN and exports `TMPDIR` under `<clone>/../.tmp/Worker` (REQ-1, REQ-8).
2. The non-launcher-writer-first then launcher test yields adopt-and-register or a loud escalation,
   never a silent per-cycle fallback (REQ-2, REQ-3, REQ-6).
3. `.git`, `.claude` and `scripts` content, re-pointed keys and inode mismatches are still refused
   before any side effect (REQ-5).
4. The effective `TMPDIR` is recorded in the cycle's audit event (REQ-8).
5. No test writes to the real trust registry (REQ-9).

## 5. Suggested slices (all touch protected surfaces)

- **S1. Visibility and test isolation.** REQ-7, REQ-8 and REQ-9. This is low risk and changes no
  guard logic.
- **S2. Adoption policy.** REQ-4 and REQ-5, after ESC-1. A guard change of this kind needs a
  security-reviewer.
- **S3. First-use registration.** REQ-1, REQ-2 and REQ-3, covering the docs, the unit examples and
  the install/bootstrap pre-registration chosen under ESC-2.
- **S4. Escalation.** REQ-6. It is delivered by #1928 S6, or here as a fallback (ESC-3).

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

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
- **ESC-2. How should non-launcher sessions register (REQ-2)?**
  - (a) Document an `ExecStartPre=`/wrapper `resolve --create` line.
  - (b) Have project install and machine bootstrap pre-create and register all four role dirs
    while they are empty.
  - (c) Both.

  *Default: c.* (b) removes the window for fresh installs. (a) covers the units that already exist,
  such as `claude-rc.service`, which is machine-local and is not edited by this build.
- **ESC-3. Ownership of the escalation (#2100 item 4 versus #1928 ESC-7).** *Default:* #1928's
  generic primitive delivers it, and REQ-6 adds the content. #2100 builds a minimal one-off only if
  #2100 is ready to merge first. Also: should an interactive `hos-human` refusal escalate too, or only
  log and audit (REQ-7)? *Default:* only log and audit, because the human is the one who launched
  the session.
- **ESC-4. Should a non-launcher writer that bypasses registration be refused at all?** One option
  is to have the resolver quarantine non-allowlisted entries into `.hos-quarantine-<ts>/` and then
  adopt. *Default: no.* Moving files inside an unregistered dir is a write into a possibly foreign
  directory, which the guard exists to prevent. This is listed only so the alternative is explicitly
  rejected or accepted.

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
