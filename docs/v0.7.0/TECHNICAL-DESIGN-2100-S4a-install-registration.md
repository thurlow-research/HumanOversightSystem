# TECHNICAL DESIGN — #2100 slice S4a: install-time registration, the read-only `status` read-back, fail-on-refusal (exit 77), and the v0.6.0 `HOS_TMP_ROOT` upgrade write

**Status: APPROVED (architect round 4).** Ready for `coder`. Revision 4 (design loop round 4 of 5), plus a
final wording-only pass. That pass:
- names follow-up #2148;
- records the REQ-11 scope;
- records the I-8 and I-9 confirmations.

Revision 4 applied the architect's binding arbitration of the inner-loop reviewer findings:
- the arbitration is `.claudetmp/design/architect-2100-S4a-reviewer-arbitration.md`, rulings (a)–(h);
- the findings are `.claudetmp/design/reviewers-2100-S4a-TD-round1.md`. The `code-reviewer`,
  `reliability-reviewer` and `infra-reviewer` lenses returned CHANGES_REQUIRED. The `security-reviewer`
  lens APPROVED, on condition that ruling (e) is applied.

Every accepted item is folded into the body, and §13 records each ruling and where it landed. Earlier
rounds:
- round 1: CHANGES_REQUIRED, RC-1 to RC-13;
- round 2: CHANGES_REQUIRED, 4 items.

All of those changes remain folded in. **The architect approved round 4**, including the I-8 and I-9
confirmations (§13.4).

REQ-11's clarification for I-6 is **recorded in REQUIREMENTS-2100 REQ-11**, scoped to "a run that reaches
the register/verify step" (commit `61fbeebc4`; code-review-7). Two human questions are open: Q-1 and Q-2. Both gate the v0.7.0 cut, and
neither gates S4a's merge (§11).

**Date:** 2026-10-22 (rounds 1–4)
**Author:** technical-design (autonomous worker cycle; no human present)
**Baseline:** `HEAD` = `origin/main` = **`70ba746e1`** (the merge of PR #2146). Every file:line below refers
to that commit, unless it is marked as a v0.6.0 reference. §0.3 lists the drift from the line numbers the
ADR cites.

**Change classification: additive, inside a structural change the human has already ruled** (the ADR-2100
Amendment of 2026-10-20). The slice adds:
- one read-only subcommand;
- one install step, with one new failure mode (exit 77) that the ruling covers;
- one new prerequisite (exit 1);
- one operator environment variable;
- a per-test refinement of the S1 test isolation;
- a narrowing of `install_default`'s slug (ruling (e)).

**Binding inputs:**
- `docs/v0.7.0/ADR-2100-tmp-root-first-use-registration.md`, as amended. The relevant parts are AD-5 (the
  guard invariants, which nothing here may weaken), AD-7(b), AD-11 ("Where the blockers come from"),
  AD-12, the §3 *Install* rows, the §4 S4a row and its test obligations, and §8 TD-H5 and TD-H7. **The ADR
  governs.**
- `docs/v0.7.0/REQUIREMENTS-2100-tmp-root-first-use-registration.md`: REQ-2 (the install half), REQ-5,
  REQ-9 and REQ-11, as amended.
- The architect's round-1, round-2 and round-4 rulings (§13).

**Scope (the ADR's S4a row, plus ruling (e)).**
- `bootstrap/lib/hos_tmp_root.py`:
  - the read-only `status` subcommand;
  - a behaviour-preserving `adoption_blockers` core (I-1);
  - the dots-only slug fallback in `install_default` (ruling (e)).
- `bootstrap/hos_install.sh`:
  - the timeout prerequisite;
  - the `HOS_TMP_ROOT` upgrade write;
  - register-and-verify, immediately before the `.hos-release` commit point;
  - exit 77 and the summary line;
  - the install-time warnings (rulings (a), (b) and (h) infra-6).
- Tests, the test-isolation refinement, and the `docs/CRON-SETUP.md` §5a paragraph.

**Out of scope (do not touch):**
- `bin/hos-cron`, `bin/hos-human`, `bootstrap/lib/hos_tmp_env.sh` and `scripts/automation/lib/cycle_log.py`
  belong to S2.
- `_remedy()` and `_repoint_message()` wording belongs to S2: AD-4, and `shlex.quote` per security-5.
- `HOS_ONLY_RE` and `TOOL_ENTRY_NAMES` belong to S3.
- `bootstrap/hos_bootstrap.sh`, `CLAUDE.md`, `docs/SANDBOX-POLICY.md` and the unit-file doc rewrite belong
  to S4b.
- `scripts/framework/install.sh` belongs to #2059.
- `scripts/framework/gen_sandbox_config.py` and sandbox-policy regeneration belong to Q-2.
- `register()`'s write robustness belongs to the follow-up issue named in ruling (g).

This document says *what the code must do*. It contains no application code.

---

## 0. Verification against `70ba746e1`

### 0.1 Search for existing helpers (CLAUDE.md "Search first", required)

I searched `bin/`, `bootstrap/`, `scripts/` (recursively) and `scripts/automation/lib/`.
- **Registry read-back.** `is_registered` (`hos_tmp_root.py:294-310`) and `read_registry` (`:263-291`)
  exist, and no CLI exposes either. `is_registered` swallows every `TmpRootError` (`:300-301`).
  `read_registry` returns `[]` for a missing file (`:269-270`). Used alone, either would turn "cannot
  verify" into "not registered". `status` composes them (§2.3).
- **Blocker list.** `adoption_problems` (`:466-485`) returns *formatted* strings only (§2.6).
- **Bounded subprocess in bash.** There is a `timeout` → `gtimeout` → unbounded precedent at
  `bootstrap/edit_issue_edges.sh:144-149` and `bootstrap/query_issues.sh:163-170`. §4.1 reuses the lookup
  order but not the unbounded fallback (E-4 reversed), and adds a `--kill-after` probe (ruling (h)
  infra-5).
- **`config.sh` writer.** There is one non-interactive append site (`hos_install.sh:845-849`), plus
  `install.sh`'s interactive whole-file writer. §4.2 extends the former.
- **Install-time registration.** None found.

### 0.2 Findings that shape this design

- **F-1 (HIGH): presence-test grammar.** `_LINE_RE` is `^\s*(?:export\s+)?HOS_TMP_ROOT=`
  (`hos_tmp_root.py:92`). The append site tests `^${_n}=` (`hos_install.sh:846`). HOS's own `config.sh:44`
  is `export HOS_TMP_ROOT="../.tmp"`. Reusing the append-site test would append a second, overriding line.
  §4.2 uses `_LINE_RE`'s grammar.
- **F-2 (HIGH): the test suites would exhaust the registry and write into the real home.**
  - The existing suites make about 70 full installs × 4 keys, against one session registry. That is about
    280 entries, more than the 256 cap (`:313`).
  - `install-default` on a lone test clone yields `~/…`, which `expand` resolves against the **passwd** home
    (`:136-137`).
  - §5 fixes both.
- **F-3 (HIGH): #2054 D15.**
  - `gen_sandbox_config.check_tmp_root` (`scripts/framework/gen_sandbox_config.py:395-420`) accepts only
    `<clone parent>/.tmp`.
  - Writing `install-default`'s XDG value for a project not yet in `projects.conf` therefore makes a fresh
    `--human` install's sandbox generation warn (`:1838`).
  - That is ruled (E-1 (a), Q-1).
  - Ruling (a) adds the upgrade case: an *existing* `settings.local.json` is never regenerated (`:1797`).
    v0.6.0's template granted no `.tmp/<Role>` dir at all, so every upgraded consumer's sandboxed Human
    session cannot write its `TMPDIR`, whatever the root. That is §4.3's grant check, plus Q-2.
- **F-4 (MEDIUM): `--pr` mode.** The upgrade branch is created at `:707`, before scaffolding. A verify
  failure therefore leaves the staged upgrade on it, and a plain `--pr` re-run fails the clean-tree test at
  `:678`. E-2 is ruled; the recovery is in §4.7. `PR_BRANCH` is created by this run's `checkout -b` (`:707`),
  and nothing commits on it before `:2524`. It therefore never has commits of its own when the 77 path runs,
  so `branch -D` loses nothing that the stash does not hold (infra-7).
- **F-5 (MEDIUM): the remedy must name a surviving file.** `_remedy` and `_repoint_message` embed
  `os.path.abspath(__file__)` (`:352`, `:492`). In release mode `HOS_SOURCE` is deleted on `EXIT` (`:224`,
  `:411`). So:
  - §4.3 runs the **target's** copy, after a `cmp -s` against the source copy (security-1);
  - §4.2 runs `HOS_SOURCE`'s copy, because a v0.6.0 target has none yet, and its output embeds no path.
- **F-6 (LOW):** `os.listdir` names are surrogateescape `str`, and `os.fsencode` restores the raw bytes.
  This is the basis of §3.
- **F-7 (LOW):** Linux `NAME_MAX` is 255 bytes. The 10 kB round-trip is therefore tested on the serializer.
- **F-8 (MEDIUM; security-3): slug traversal.** `install_default` maps `[^a-z0-9._-]` to `-` (`:589`). A
  `PROJECT_NAME` of `..` therefore survives as the slug `..`. `~/.local/state/hos/tmp/..` passes both gates,
  and it normalises to the registry's own directory, a root shared across projects. §2.7 fixes this.
- **F-9 (MEDIUM; code-review-1, infra-3): the §4.2 failure timing.** The write site (`:845`) runs before
  the framework copy (`:1923`), the Phase-A drift stop (`exit 4`, `:1163`, `:1650`) and the manifest. The
  failure is therefore **deferred** to the §4.3 site (ruling (c)).

### 0.3 Line-number drift (ADR citation → `70ba746e1`)

| ADR cites | Actual | Note |
|---|---|---|
| `hos_install.sh:829-848` (key-append site) | `:828-849` (loop `:845-849`, `printf` `:847`, create `:841-844`, manifest guard `:830`) | minor drift |
| `hos_install.sh:2502-2511` (`.hos-release`) | `:2502-2512` | matches |
| `hos_install.sh:1703` (#277) | `:1703`, and repeated at `:2362` | matches |
| `hos_install.sh:1715-1745` | `:1712-1748` | matches |
| `install.sh:254-275` | `:254-282` | minor drift |
| `hos_tmp_root.py` citations (`:80`, `:121-133`, `:219-231`, `:294-310`, `:488-498`, `:501-508`, `:552`, `:583-590`) | same | no drift |
| "`hos_install.sh` uses 0, 1, 2, 4, 5 and signal codes" | 0, 1, 2, 4, 129, 130 and 143; there is no literal `exit 5` | immaterial; 77 is unused |

### 0.4 #2059 status

**Not merged.** The unmerged branch changes only the `hos_install.sh` *reads* (`_cfg_read`). S4a therefore
extends the existing append site (AD-12's "otherwise" branch). The PR body must name #2059 as the writer
that absorbs this one, and its re-review must also cover `install.sh:148`'s indented-key miss (I-5).

---

## 1. Files (≤15; one PR)

| # | File | Change | Protected |
|---|---|---|---|
| 1 | `bootstrap/lib/hos_tmp_root.py` | `status` (§2); the `adoption_blockers` core (§2.6); the dots-only slug fallback (§2.7); docstring | **yes** (`bootstrap/**`, `protected_surfaces.txt:27`) |
| 2 | `bootstrap/hos_install.sh` | §4: the prerequisite, the bounded invoker, the deferred upgrade write, register-and-verify, exit 77, the summary line, the warnings, the dry-run lines | **yes** |
| 3 | `tests/framework/test_hos_tmp_root.py` | `status` cases, `adoption_problems` parity, slug cases (§8.1) | no |
| 4 | `tests/framework/test_install_tmp_root_verify.py` (new) | install-level and extracted-function cases (§8.2) | no |
| 5 | `tests/framework/test_tmp_root_first_writer.py` (new) | the REQ-2 sequence (§8.3) | no |
| 6 | `tests/conftest.py` | per-attempt registry; session `HOS_INSTALL_TMP_ROOT` (§5) | no |
| 7 | `tests/tmp_hygiene.py` | `child_env` carries `HOS_INSTALL_TMP_ROOT` (§5) | no |
| 8 | `tests/framework/test_registry_isolation.py` | isolation cases (§8.4) | no |
| 9 | `docs/CRON-SETUP.md` | §5a: install registration, `status`, exit 77, the timeout prerequisite, the re-point steps, the sandbox-policy note, the privacy note (§6) | no |
| 10 | `SCRIPTS-INDEX.md` | **only if** `scripts/framework/regen_all.sh --check` reports drift | no |
| 11 | `tests/framework/test_install_tmp_root_warnings.py` (new, **optional**) | only if file 4 is split, to hold I-20 to I-23 | no |
| 12–15 | reserve | existing install-suite harnesses, **only if** §5 leaves one failing. A harness edit may add environment only, never weaken an assertion | no |

**Final count: 9 fixed files.** At most 15 if every conditional slot is used (10 for `SCRIPTS-INDEX.md`, 11
for the split, and 12–15 for four reserve harnesses). That is within the ≤15 budget.

**Reviewers.** `reliability-reviewer` and **`security-reviewer` are mandatory**:
- §2.6 rewrites the body of the guard's adoption check (RC-9);
- §2.7 narrows `install_default`, which was #2054's (ruling (e)).

---

## 2. `hos_tmp_root.py`

### 2.1 `status` CLI (exact)

```
hos_tmp_root.py status --repo <clone> --role <worker|overseer|human|local> [--json]
```
- `--role` uses `choices=sorted(ROLE_DIRS)`.
- `--json` adds the record on stdout (§3). Without it, stdout is **empty**.
- A usage error is argparse exit 2 with no JSON. A caller must treat "exit 2 and no parseable JSON" as
  "cannot verify".

### 2.2 Read-only guarantees (binding; pinned by S-12)

`status` never does any of these:
- creates, `mkdir`s, `chmod`s, renames or unlinks anything;
- calls `_make_dirs_0700`, `register`, `write_info_marker` or `_require_private_dir(..., tighten=True)`;
- opens a file with `O_CREAT`, `O_WRONLY` or `O_RDWR` (no `.lock`, and no flock).

It may only:
- read `config.sh` through `resolve_root`;
- `lstat` and `listdir` the root, the role dir and the role dir's children;
- `lstat` and read the registry through `read_registry`.

It never spawns a process (`:31`).

### 2.3 Algorithm (ordered; the first match decides)

`repo_real = realpath(repo)`.
1. `root = resolve_root(repo)`. A `TmpRootError` is exit **2**, `root-invalid`.
2. `role_dir = root / ROLE_DIRS[role]`.
3. Check the registry:
   - `os.lstat(registry_path())` raising `FileNotFoundError` is exit **2**, `registry-absent`. This covers
     both a masked sandbox and a machine where nothing was ever registered. It means "cannot verify", never
     "not registered".
   - Any other `OSError` is exit **2**, `registry-unreadable`.
   - `entries = read_registry(...)` raising `TmpRootError` is exit **2**, `registry-unreadable`.
4. If the root does not exist, go to step 9 as "absent". Otherwise `_require_private_dir(root,
   tighten=False)`; a `TmpRootError` is exit **2**, `root-invalid`.
5. Letter case, using the same expression as `:525`. If it fails, exit **2**, `structural`. An `OSError` from
   `listdir` is also exit 2, `structural` (I-2).
6. If the role dir does not exist, go to step 9.
7. `_require_private_dir(role_dir, tighten=False)`. A `TmpRootError` is exit **2**, `structural`.
8. `info = os.lstat(role_dir)`. If `is_registered(role_dir, info, repo_real)`:
   - if `info.st_mode & 0o077`, exit **2**, `structural`, with the reason "registered but accessible to
     group/other (mode <octal>); chmod 700 it, or let any launcher run tighten it" (I-3, `INVALID:`);
   - otherwise exit **0**, `registered`.
9. The dir is not registered for this key:
   - (a) a `_repoint_conflict(...)` hit is exit **1**, `repoint`, `adoptable=false`;
   - (b) a missing dir is exit **1**, `absent`, `adoptable=true`;
   - (c) a dir registered for another repo only is exit **1**, `unregistered-adoptable`, `blockers=[]`;
   - (d) otherwise `bl = adoption_blockers(role_dir)`. If it is empty, exit **1**, `unregistered-adoptable`;
     if not, exit **1**, `unregistered-blocked`, with **all** of `bl`.
10. Any other exception is exit **2**, `error`. `status` never returns 3 and never prints a traceback.

The order of step 9 matches `resolve_role_dir` (`:510-520`). `register` writes by rename (`:439`), so
`status` never sees a torn file in the normal case. FM-17 states the residual.

### 2.4 Human output (stderr; exactly one line, always)

The prefix is `hos_tmp_root: status <role>: `. Before printing, every `\r` and `\n` in the composed line is
replaced by the two characters `\r` or `\n` (code-review-10). Paths containing newlines can therefore never
break the one-line guarantee.

| class | Line after the prefix |
|---|---|
| `registered` | `OK: <role_dir> is registered for <repo_real>` |
| `absent` | `NOT REGISTERED: <role_dir> does not exist yet; the next resolve --create (installer or launcher) creates and registers it` |
| `unregistered-adoptable` | `NOT REGISTERED: <role_dir> holds only HOS-owned entries or is registered for another clone; the next resolve --create adopts and registers it` |
| `unregistered-blocked` | `NOT REGISTERED: ` + `_remedy(role_dir, role, repo, <formatted blockers>)` (the existing text: the first five, plus a count) |
| `repoint` | `NOT REGISTERED: ` + `_repoint_message(conflict, str(role_dir), repo, role)` |
| `registry-absent` / `registry-unreadable` | `CANNOT VERIFY: <reason>. Run it unsandboxed, in your own terminal — not inside a Claude session or any sandbox (a sandbox hides the trust registry)` |
| `root-invalid` / `structural` / `error` | `INVALID: <reason>. Fix the path or value named on this line` |

The prefixes form a closed set:

| Prefix | Exit | Remedy |
|---|---|---|
| `NOT REGISTERED:` | 1 | `mv` or `mark` |
| `CANNOT VERIFY:` | 2 | re-run unsandboxed |
| `INVALID:` | 2 | fix the named path or value; this line never says "unsandboxed" |

The installer (§4.4) selects its remedy by these prefixes.

### 2.5 Exit codes

| Exit | Classes |
|---|---|
| 0 | `registered` |
| 1 | `absent`, `unregistered-adoptable`, `unregistered-blocked`, `repoint` |
| 2 | `structural`, `root-invalid`, `registry-absent`, `registry-unreadable`, `error`, usage |

`main` dispatches `status` before the `try` that maps errors to 3. The docstring's exit-code paragraph gains
the `status` line.

### 2.6 `adoption_blockers`: the structured core (I-1; behaviour-preserving)

- **New** `adoption_blockers(role_dir) -> list[Blocker]`. `Blocker` is an immutable record of `kind`, `name`
  (a surrogateescape `str`, or `""`) and `detail`. The kinds are:
  - `name`: not on the allowlist;
  - `project-files`: an allowlisted dir that directly holds `.git`, `.claude` or `scripts`;
  - `unreadable-listing`: `name=""`, `detail=str(exc)`.

  The order, the `lstat`-failure skip (`:479-480`) and the rules are exactly today's body.
- `adoption_problems` becomes `[_format_blocker(b) for b in adoption_blockers(d)]`. Its output is
  **byte-identical** to today's: `repr(name)`, `f"{name!r} (it contains project files)"` and
  `f"an unreadable listing ({detail})"`. `resolve_role_dir` still calls it at `:540`, so AD-5 invariant 7
  is unchanged.
- **S3** adds its `TOOL_ENTRY_NAMES` rule inside `adoption_blockers`, with any new kind (for example
  `not-a-directory`). The PR body states this.

### 2.7 `install_default`: dots-only slug fallback (ruling (e); security-3)

After the existing computation (`slug = re.sub(r"[^a-z0-9._-]", "-", project_name.lower()) or "project"`,
`:589`), a slug made up **only of dots** (`.`, `..`, `...` and so on) becomes `project`. This is the only
change. It narrows #2054's default, so it can never produce a `.`/`..` path component. Every other slug is
unchanged.

| `--project-name` | slug | default |
|---|---|---|
| `""` | `project` | `~/.local/state/hos/tmp/project` (as today) |
| `.` / `..` / `...` | `project` | `~/.local/state/hos/tmp/project` |
| `../x` | `..-x` | `~/.local/state/hos/tmp/..-x`. This is a single safe component: `/` is already mapped to `-`. See I-8 in §10 |
| `My App` | `my-app` | as today |

---

## 3. TD-H5: the machine-readable blocker format, and how S2 consumes it

### 3.1 One JSON object per line, ASCII-only, with every byte-bearing field hex-encoded

With `--json`, `status` prints exactly one line, `json.dumps(record, ensure_ascii=True, sort_keys=True,
separators=(",", ":"))`, for exit 0, 1 and 2 alike:

| Key | Type | Value |
|---|---|---|
| `v` | int | `1` |
| `role` | str | the `--role` value |
| `exit` | int | 0, 1 or 2 |
| `class` | str | a §2.5 class |
| `adoptable` | bool or null | for exit 1 only |
| `role_dir_hex` | str or null | hex of `os.fsencode(str(role_dir))`; `null` if step 1 failed |
| `blocker_count` | int | `len(blockers)` |
| `blockers` | list | **all** of `{"kind", "name_hex"}`, in core order; `name_hex` is `""` for `unreadable-listing` |

The JSON carries no reason text and no path, except as hex.

**Why this format.**
- Hex is byte-safe by construction: newlines, control bytes, NULs and invalid UTF-8 all round-trip.
- Rejected: surrogate-escape JSON. `jq` and most other consumers map lone surrogates to U+FFFD, and the
  AD-11 fingerprint needs the raw bytes.
- Rejected: a NUL stream. It cannot carry `class`, `exit` or `kind` without a second convention.
- `status` never truncates the list. Capping is the consumer's job.

### 3.2 How S2 consumes it (binding on S2's TD)

- **Call.** `python3 -I <clone>/bootstrap/lib/hos_tmp_root.py status --repo <clone> --role <role> --json`,
  under S2's own per-call timeout (TD-H1).
- **Parse.**
  - Read stdout up to a cap; 4 MiB is recommended.
  - If the output is empty, over the cap, invalid, `v != 1`, or missing a key, the blockers are `unknown`
    (AD-2).
  - The exit code is informational only.
- **Use.**
  - The raw bytes are `bytes.fromhex(name_hex)`.
  - The fingerprint uses all of them, plus `refusal_class` and `role_dir` (which may come from
    `role_dir_hex`).
  - The renderer gets the same bytes, shows at most five, and adds `(+N more)`.
  - For any class other than `unregistered-blocked`, the blockers are `unknown`, and the reason comes from
    `HOS_TMP_REASON`.
- **No re-parsing.** S2 never parses names out of stderr or out of `reason`.
- **S2 hand-off (security-5).** The paths in `_remedy` and `_repoint_message` are unquoted. Applying
  `shlex.quote` to them is S2's AD-4 work.

---

## 4. `bootstrap/hos_install.sh`

### 4.0 Shape: orchestration in shell, decisions in Python (ruling (d))

Trust decisions stay in Python: `resolve` and `status`. The installer only orchestrates and reports. That is
a **declared exception** to code-review-5's "move it to Python" recommendation, and the PR body says so
(§9). Its conditions:
- each decision in the installer is **one named, column-0, self-contained shell function**. Each starts with
  `name() {` and ends with a column-0 `}`. Each uses only its arguments, local variables and
  `printf`/`[[ ]]`/`case`. Each reads no global except where noted, and calls no other installer function.
  That makes each one **extractable by a test**: the test `sed`s the function out of the file, sources it
  into `bash`, and calls it with arguments;
- the branch → test table in §8.6 maps every branch to a named test;
- the `scripts/oversight/validators/shell_logic_check.py` finding on `hos_install.sh` is **disclosed in the
  PR body and never suppressed**.

| Function | Decides | Signature (args → stdout, rc) |
|---|---|---|
| `_hos_tmp_classify_rc` | an rc → outcome | `<rc>` → `ok` (0), `timeout` (124 or 137: "timed out or was killed"), `fail` (anything else) |
| `_hos_tmp_prefix_of` | a `status` line → prefix class | `<line>` → `not-registered`, `cannot-verify`, `invalid` or `other` |
| `_hos_tmp_select_remedy` | which remedy bullets to print | `<has_nr> <has_cv> <has_inv> <config_path> <installed_tag>` → the bullet text (§4.4 step 2) |
| `_hos_tmp_verdict` | the per-role states → the refused CSV | `<state_worker> <state_overseer> <state_human> <state_local>` (each `pass` or `refused`) → `none` or the CSV in role order |
| `_hos_tmp_pr_recovery` | the `--pr` recovery text | `<target> <tag> <pr_branch> <orig_branch>` → the §4.7 text, with every value `printf %q`-quoted |
| `_hos_tmp_root_from_ok` | the root from an `OK:` line | `<role> <line>` → the root (display-only) or `""` |

The orchestration functions (`_hos_tmp_run`, `_hos_tmp_ensure_key`, `_config_append_kv`,
`_hos_tmp_register_and_verify`, `_hos_tmp_summary`, `_hos_tmp_fail_77`, `_hos_tmp_sandbox_grant_check`) call
these functions. They are covered by the install-level tests.

### 4.1 The timeout prerequisite and the bounded invoker (RC-3; ruling (h) infra-5, reliability-6/7)

**Prerequisite** (inside `hos_install.sh:552-577`, evaluated before `if ! $PREREQ_OK`):
- **Selection.** Pick the first of `timeout` and `gtimeout` that exists.
- **Probe.** Run `<bin> --kill-after=1s 1s true`. It must exit 0. This rejects BusyBox and other builds
  without `--kill-after`. **BusyBox `timeout` is unsupported.**
- **On success:** `ok "timeout present (<bin>, supports --kill-after)"`.
- **On failure** (neither binary exists, or the probe fails): `err "timeout with --kill-after (GNU
  coreutils) is required to bound temp-dir registration — install coreutils (Debian/Ubuntu: apt install
  coreutils; Fedora: dnf install coreutils; macOS: brew install coreutils, which provides gtimeout)"`, then
  `PREREQ_OK=false`. The existing block exits **1**, before any write and before the PR branch.
  `hos_bootstrap.sh` installs coreutils only for macOS-brew (`:267-281`), so the message names the package
  managers directly.
- **Under `--dry-run`** the same failure is a `warn "… a real install would stop here (exit 1)"`, and
  `PREREQ_OK` is left alone. In that case `_HOS_TMP_PREFIX` stays empty, and the §4.2 preview calls are
  skipped with `dry_run "Would compute and check HOS_TMP_ROOT (skipped: no usable timeout binary)"`.

**Prefix.** `_HOS_TMP_PREFIX=(<bin> --kill-after=5s <T>s)`.
- `<T>` is `30`. `HOS_INSTALL_TMP_VERIFY_TIMEOUT` may lower it to an integer from 1 to 30; any other value
  gives 30.
- `_hos_tmp_run` refuses to run with an empty prefix. It treats that as `timeout` with the reason "no timeout
  prefix", which is unreachable after the prerequisite. **There is no unbounded call path** (I-15).

**Capture forms (RC-8; exactly two):**
- **Diagnostic** (`resolve --create`, `status`, `validate`) captures stderr only:
  `_rc=0; _err="$("${_HOS_TMP_PREFIX[@]}" python3 -I "$helper" <args…> 2>&1 >/dev/null)" || _rc=$?`. Only the
  last line of `_err` is kept. `resolve`'s stdout is never read.
- **Value** (`install-default`) captures stdout only:
  `_rc=0; _val="$("${_HOS_TMP_PREFIX[@]}" python3 -I "$helper" install-default … 2>/dev/null)" || _rc=$?`.

No temp files are written. `_hos_tmp_classify_rc` interprets every rc. A `timeout` outcome is reported as
"did not answer within <T> s (timed out or was killed)", because 137 can also be the OOM killer.

**Fail-fast (ruling (f)).** Once a call made by §4.3 times out, **no further resolver calls are made in that
run**. Every role still undecided is refused with the reason `skipped after an earlier timeout`.

### 4.2 The `HOS_TMP_ROOT` upgrade write, with a deferred failure (AD-12; rulings (c), (h) reliability-2)

**Site.** `_hos_tmp_ensure_key`, called once, directly after the append loop (`:845-849`) and **outside**
the `placeholders.manifest` conditional (`:830`).

**One writer.** `_config_append_kv <name> <value>` replaces the `printf` at `:847`. The existing empty-key
loop and this write both call it. It does the following, in order:
1. `mkdir -p "$(dirname "$_subst_config")"` (code-review-4).
2. If the file is absent, create it with the existing header line (`:843`).
3. Build the **whole** line into one variable: an optional leading `\n` (when the file's last byte is not a
   newline), then `<name>="<value>"\n`.
4. Write it with **one** `printf '%s' "$_line" >> "$_subst_config"`, inside `if !` so that `set -e` cannot
   abort the run.
5. Return non-zero on any failure (`mkdir`, create or append).

It is byte-identical to today's `printf '%s=""\n'` for empty values. A static test pins that the only `>>
"$_subst_config"` appends are this helper's and the pre-existing `PACK` lines (`:1340-1350`).

**Presence test (F-1).** `grep -qE '^[[:space:]]*(export[[:space:]]+)?HOS_TMP_ROOT=' "$_subst_config"`:

| grep rc | Meaning | Action |
|---|---|---|
| 0 | present (including `HOS_TMP_ROOT=""`) | no write; `skip "… already set — left unchanged"` |
| 1, or the file is missing | absent | compute and write (below) |
| ≥ 2 | unreadable | **record a deferred failure**: "cannot read `<config.sh>`" |

**The value.**
- If `[[ -n "${HOS_INSTALL_TMP_ROOT:-}" ]]`, its value is used, with source `(from HOS_INSTALL_TMP_ROOT)`.
  **The empty string counts as unset** (ruling (h) code-review-2).
- Otherwise the value is the stdout of `<HOS_SOURCE>/bootstrap/lib/hos_tmp_root.py install-default --target
  "$TARGET_REPO" --project-name "<name>"`, with source `(resolver install-default)`. `<name>` is the
  `PROJECT_NAME` environment variable if set, otherwise the first `^PROJECT_NAME=` in `config.sh` (the
  idiom at `:858`), otherwise `""`.
- The installer never computes a default itself (AD-12).
- **Containment (RC-6).** Among non-test files under `bin/`, `bootstrap/`, `scripts/` and `.github/`, only
  `bootstrap/hos_install.sh` names `HOS_INSTALL_TMP_ROOT` (I-18). Docs may describe it.

**Gates, in order:**
1. `^[A-Za-z0-9._/~-]+$`;
2. `validate --repo "$TARGET_REPO" --value "<v>"` exits 0.

**On a gate or compute failure** (the helper is missing from `HOS_SOURCE`, `install-default` failed, timed
out or printed nothing, or a gate failed), **nothing is written**. The function records the deferred
failure, setting `_HOS_TMP_DEFERRED` to:

> `HOS_TMP_ROOT could not be written to config.sh: <cause>. Set HOS_TMP_ROOT in <config.sh> by hand, then re-run.`

It prints the same text immediately as a `warn`, and the install **continues** (ruling (c)).

**On a write failure** (`_config_append_kv` non-zero), the deferred message is:

> `HOS_TMP_ROOT could not be written to config.sh (<cause>). config.sh may now hold a partial HOS_TMP_ROOT line: fix or remove it by hand, then re-run.`

The next run's presence test then sees the partial line as present. `status` reports it as `INVALID:`
(ruling (h) reliability-2).

**On success:** `ok "config.sh: added HOS_TMP_ROOT=\"<v>\" <source>"`, the name is added to `_appended`, and
`_HOS_TMP_WRITTEN="<v>"` is set. The §4.4 warnings use that variable.

**Interactive path.** `install.sh` (`:1735`) later reads the line as existing (`install.sh:148`) and rewrites
`config.sh` with exactly one assignment. Register-and-verify reads the final file (I-5). If §4.2 recorded a
deferred failure, the interactive tool may still write a value itself. §4.3 exits 77 regardless, and the
re-run succeeds.

### 4.3 Register-and-verify (AD-7(b), AD-12)

**Site.** `_hos_tmp_register_and_verify`, called once, between the end of the `.hos-manifest` block (`:2500`)
and `.hos-release` (`:2502`). Earlier hard stops win and never reach it:
- a prerequisite failure (exit 1);
- a Phase-A drift or pack-injection stop (exit 4, `:1163`, `:1650`);
- a #277 manifest refusal (exit 1, `:1704`, `:2363`).

**Order inside the function:**
1. **Deferred §4.2 failure (ruling (c)).** If `_HOS_TMP_DEFERRED` is set, **skip both register and verify**.
   Go straight to the 77 path with that message, only the "Always" bullets, and
   `refused=worker,overseer,human,local`.
2. **Helper provenance (security-1).** `helper="$TARGET_REPO/bootstrap/lib/hos_tmp_root.py"`. It must be a
   regular file **and** `cmp -s "$HOS_SOURCE/bootstrap/lib/hos_tmp_root.py" "$helper"` must succeed.
   Otherwise all four roles are refused, with the reason "bootstrap/lib/hos_tmp_root.py in the target is
   missing, not a regular file, or differs from the release being installed (see the copy step above)",
   and the install takes the 77 path (code-review-8). In a `--local` self-install the two paths are the
   same file, and `cmp` passes trivially.
3. **Registry-override notice (RC-7).** If `[[ -n "${HOS_TMP_REGISTRY_FILE:-}" ]]`, print one `warn`:
   "HOS_TMP_REGISTRY_FILE is set (<path>): registration and verify use that file, NOT the real trust
   registry (~/.local/state/hos/tmp-roots.json); the reaper will not see these registrations." An empty
   value prints nothing. The resolver also treats an empty value as unset, and reads the real registry.
4. **Register.** For `worker overseer human local`, in that order, run `resolve --create` (the diagnostic
   capture form). Record each role's outcome:
   - `ok`;
   - `fail <line>`: the line is printed as `register:` in the report (RC-1);
   - `timeout`: `register: resolve --create did not answer within <T> s (timed out or was killed)`.

   On the first `timeout`, stop (fail-fast). Every remaining role gets
   `register: skipped after an earlier timeout`, and its verify is also skipped.
5. **Verify.** Skip it entirely if step 4 hit a timeout. Every role is then refused, and the roles not
   already marked get `verify: skipped after an earlier timeout`. Otherwise, for each role in order, run
   `status` (diagnostic form). A role passes **only** on rc 0. Its line is kept. On the first `status`
   timeout, stop; that role gets `verify: status did not answer within <T> s (timed out or was killed)`,
   and every later role gets `verify: skipped after an earlier timeout`.
6. **Verdict.** `_hos_tmp_verdict`. A refusal goes to the 77 path. `none` goes on to step 7.
7. **Success.** `_hos_tmp_summary none`, which prints the summary line and the §4.4 warnings. Then:
   - `ok "Role temp dirs registered and verified under <root>"`. `<root>` is
     `_hos_tmp_root_from_ok worker <Worker line>`: strip `hos_tmp_root: status worker: OK: `, cut at the
     first ` is registered for `, take the `dirname`. If that yields nothing, print `HOS_TMP_ROOT`. It is
     display-only;
   - the sandbox grant check (step 8);
   - return. The install continues to the `.hos-release` stamp.
8. **Sandbox grant check (ruling (a); `_hos_tmp_sandbox_grant_check`).** This runs only when `$ROLE_HUMAN`
   is set and `.claude/settings.local.json` exists. The file is checked as it stands after `:1797`, which
   never overwrites it. Let `H` be `_hos_tmp_root_from_ok human <Human line>` + `/Human`, the literal Human
   role-dir path. If `H` is empty, or `grep -qF -- "$H"` does not find it in the file, print one `warn`:

   > `The existing sandbox policy .claude/settings.local.json could not find the grant for this clone's Human temp dir (<H>): sandboxed sessions launched from this clone cannot write their TMPDIR. Remedy: move it aside (mv .claude/settings.local.json .claude/settings.local.json.bak-<UTC timestamp>) and re-run this installer, or regenerate it with: python3 scripts/framework/gen_sandbox_config.py --role human --clone-dir <target> --handoff-dir <absolute-path> --claude-project-state <absolute-path>`

   The command is the same one already printed at `:1844`, with `<target>` filled in. It is **non-fatal**,
   and false positives are accepted (for example, a symlinked path spelled differently). If `H` is found,
   nothing is printed.

**Forbidden.** No `mark` subcommand, no `--reviewed` and no `force_mark` anywhere in `hos_install.sh`. That
includes comments and messages (AD-5/AD-7, I-14).

### 4.4 Output contract and the 77 path

**Summary line.** `_hos_tmp_summary <csv>` prints it to stdout, uncoloured:

```
tmp-root-verify: refused=<none | roles in the order worker,overseer,human,local>
```

It matches `^tmp-root-verify: refused=(none|(worker|overseer|human|local)(,(worker|overseer|human|local))*)$`.
Exactly one line is printed by **every run that reaches §4.3**. A run that stops earlier prints none, even if
§4.2 recorded a failure. Those earlier stops are a prerequisite failure, a drift or pack stop, a #277
refusal, and `--help`. A dry run prints the `skipped` form (§4.5).

**Warnings printed by `_hos_tmp_summary`, after the summary line**, on both the success path and the 77
path:
- **Re-point guidance (ruling (b)).** It prints when `_HOS_TMP_WRITTEN` is non-empty **and** the root
  differs from `$(cd "$TARGET_REPO/.." && pwd -P)/.tmp`. The root is taken from the Worker `OK:` line. If
  that is unavailable (77 path), the comparison is made on the written value, which must be exactly
  `../.tmp`. The warning:

  > `HOS_TMP_ROOT was set to <value>. If this clone will run sandboxed sessions it must be ../.tmp; change it now, before first use. Once role dirs are registered, moving the root is a re-point: the installer and launchers refuse it and print the exact command to approve it. See docs/CRON-SETUP.md §5a.`

  It contains no `--reviewed` (I-14 stands).
- **Outside `$HOME` (ruling (h) infra-6).** It prints when `_HOS_TMP_WRITTEN` is non-empty **and** either the
  root (as above, or the expanded written value) or `realpath(target)` is not under `$HOME`:

  > `HOS_TMP_ROOT (<root>) or this clone (<target>) is outside $HOME, so its absolute path cannot be shortened to ~: it will appear as-is in the committed audit trail and in alert issues. config.sh, which is committed, now records HOS_TMP_ROOT=<value>.`

**The 77 path (`_hos_tmp_fail_77`).** It holds the file's only `exit 77` (I-13) and prints, in order:
1. **Per refused role.**
   - `err "Temp dir refused: <role> (<RoleDir>)"`.
   - Its `register:` line, if any: a failure, a timeout, or "skipped after an earlier timeout".
   - Its `verify:` line: the `status` line with its prefix, or the timeout, skipped or helper reason.

   Each is indented four spaces and printed as-is (local terminal only). For the deferred §4.2 failure,
   this whole step is replaced by the §4.2 message.
2. **The remedy, `_hos_tmp_select_remedy`.** `has_nr`, `has_cv` and `has_inv` are computed by applying
   `_hos_tmp_prefix_of` to the printed `verify:` lines.
   - **Only if `has_nr`:**
     > `Remedy for a NOT REGISTERED dir — run it unsandboxed, in your own terminal (not inside a Claude session; it needs the trust registry):`
     > `  • move each blocking entry out of the role dir:  mv '<role_dir>/<entry>' <a dir outside HOS_TMP_ROOT>/`
     > `  • or, after reviewing the dir yourself, run the mark command printed above for that role.`
   - **Only if `has_cv`:**
     > `CANNOT VERIFY: the trust registry could not be read. Re-run this installer unsandboxed, in your own terminal (not inside a Claude session).`
   - **Only if `has_inv`:**
     > `INVALID: fix the path or value named on that line (HOS_TMP_ROOT in <config.sh>, or the role dir itself).`
   - **Always:**
     > `Then re-run this installer with the same arguments. Re-running is safe (idempotent).`
     > `The install is NOT complete: .hos-release is unchanged (<INSTALLED_TAG or "none">) and no install PR was opened.`

   "Unsandboxed" appears only beside `NOT REGISTERED` and `CANNOT VERIFY`, and always with "not inside a
   Claude session" (infra-8). `<entry>` and `<a dir outside HOS_TMP_ROOT>` are literal placeholders.
3. If `PR_ACTIVE` is set, `_hos_tmp_pr_recovery …` (§4.7).
4. `_hos_tmp_summary <csv>`, which prints the summary line and the warnings above.
5. `exit 77`. The `EXIT` trap still runs.

### 4.5 `--dry-run`

- **§4.2.**
  - The presence test always runs.
  - The value computation and the gates run only if a usable timeout exists (§4.1).
  - Success prints `dry_run "Would append HOS_TMP_ROOT=\"<v>\" to config.sh <source>"`.
  - Failure prints `warn "Would FAIL the install (exit 77): <message>"`.
  - A dry run never exits 77.
- **§4.3.** No resolver call. The run prints `dry_run "Would register and verify the role temp dirs worker,
  overseer, human, local under HOS_TMP_ROOT (skipped in a dry run)"`, then exactly one
  `tmp-root-verify: skipped=dry-run`.
- **Nothing is created:** no root, role dir, registry, `.lock` or `config.sh` change (I-12).

### 4.6 `--local` and release installs

The flow is identical in both. §4.2 uses `HOS_SOURCE`'s helper. §4.3 uses the target's helper, after the
`cmp -s` against `HOS_SOURCE`'s.

### 4.7 `--pr` mode (E-2; RC-4; ruling (h) security-2)

On the 77 path with `PR_ACTIVE=true`:
- there is no commit, push or PR;
- the consumer stays on `PR_BRANCH`;
- the installer runs no git command of its own.

`_hos_tmp_pr_recovery <target> <tag> <pr_branch> <orig_branch>` prints the following. `Q(x)` means
`printf %q` of x. The stash message is quoted as **one** `%q` word, `Q("hos-upgrade <tag>")`:

> `The upgrade is staged, uncommitted, on branch Q(<pr_branch>) (you are on it). No PR was opened.`
> `The temp-dir remedy above (mv or mark) is machine-local: it changes the role dir or the trust registry, not this repository, so it works from any branch.`
> `To return to Q(<orig_branch>) and retry the PR install after the remedy, run:`
> `  git -C Q(<target>) stash push --include-untracked -m Q(hos-upgrade <tag>)`
> `  git -C Q(<target>) checkout Q(<orig_branch>)`
> `  git -C Q(<target>) branch -D Q(<pr_branch>)`
> `then re-run this installer with --pr. (The stash keeps the staged upgrade recoverable; drop it with 'git stash drop' once the new PR exists.)`

`<tag>` is `HOS_REF`. The text never suggests `git clean`, `git reset --hard` or `git checkout -- .`. Every
pasted command must be inert under hostile values: git ref names may contain `$`, `(`, `)`, backticks and
`;`. I-2b and I-2d pin this.

### 4.8 Idempotency

An unchanged re-run:
- leaves `config.sh` byte-identical;
- leaves the registry's entry set unchanged;
- exits 0 with `refused=none`.

A re-run after `mv` adopts the dir. A re-run after `mark --reviewed` accepts it. A re-run after a deferred
§4.2 failure behaves like a first run once `config.sh` is fixed.

---

## 5. Test isolation (F-2; refines AD-10; E-3 as conditioned)

Changes are made only in `tests/conftest.py` and `tests/tmp_hygiene.py`. S1's guard is unchanged.

- **`pytest_configure` (S1's hook).** After S1 sets `HOS_TMP_REGISTRY_FILE`:
  - it sets the module global `_SESSION_REGISTRY` to S1's session-owned path, or to **`None`** if S1 kept a
    caller-set override. It is always defined (code-review-9);
  - it saves the prior `HOS_INSTALL_TMP_ROOT` (which may be absent), then **always** sets
    `os.environ["HOS_INSTALL_TMP_ROOT"] = "../.tmp"`, overwriting any inherited value (RC-5).
    `pytest_unconfigure` restores the saved value, or deletes the variable if it was absent
    (code-review-9).
  - `../.tmp` resolves to `<target parent>/.tmp`. That is inside each test's own `tmp_path`, never in the
    passwd home, and it satisfies D15.
- **Autouse function-scoped fixture `_hos_per_test_registry(tmp_path_factory, monkeypatch)`**
  (ruling (h) reliability-1).
  - It acts only when `_SESSION_REGISTRY is not None` and `os.environ[REGISTRY_ENV] == _SESSION_REGISTRY`.
  - It then sets `REGISTRY_ENV` to `tmp_path_factory.mktemp("hos-registry") / "tmp-roots.json"`. `mktemp`
    gives a fresh numbered directory **per call**, so every attempt, including a `--reruns 1` retry
    (`scripts/framework/run_tests.sh:76`), gets its own registry. The directory is 0700; the file is not
    created.
  - A caller-set override, and a test's own `monkeypatch.setenv`, which runs later, are left alone.
  - **Fixture scope (RC-10).** Module- and session-scoped fixtures run before this one, so they use the
    session registry. In `test_install_registry_data.py` that is four module fixtures (`:117-139`) on four
    targets: 4 × 4 = **16 entries**, far below 256. A re-install into the same target replaces its keys
    and adds none. A conftest comment states this bound.
- **`child_env`.** The carried set becomes `("TMPDIR", "HOS_TMP_REGISTRY_FILE", "HOS_INSTALL_TMP_ROOT")`. A
  value the caller set is never overridden, **including the empty string**.
- **Requesting the real `install-default` (ruling (h) code-review-2).** Tests that need it (I-8, I-8b, I-9,
  I-11e) set `HOS_INSTALL_TMP_ROOT=""` in the env they pass. They do **not** pop it, because `child_env`
  would re-add it. The installer treats `""` as unset (§4.2).
- **Caveat for `HOS_TMP_REGISTRY_FILE` (I-19).** The resolver treats `HOS_TMP_REGISTRY_FILE=""` as unset,
  and would read the **real** registry (`registry_path()`, `:260`). A test that needs the installer to see no
  override (I-19's second case) passes `""` to the installer. It also routes every `python3` call through a
  shim that exports a **non-empty** per-test override before `exec`. S1's session guard is the backstop.

---

## 6. Docs: `docs/CRON-SETUP.md` §5a "Where HOS temp lives" (TD-H7; rulings (a), (b), (h))

Add one block after the bullet at `:421`. S3 and S4b also edit this file; whichever lands later rebases.
The block must state:
1. **Install-time registration.**
   - The installer creates and registers all four role dirs, then verifies them with the read-only
     `python3 bootstrap/lib/hos_tmp_root.py status --repo <clone> --role <role>`.
   - Exit 0 means registered.
   - Exit 1 is `NOT REGISTERED` (`mv` or `mark`).
   - Exit 2 is either `CANNOT VERIFY` (re-run unsandboxed, in your own terminal) or `INVALID` (fix the named
     path or value).
   - Any refusal fails the install with **exit 77**, before `.hos-release` and before any install PR. A
     re-run after the remedy is safe. The machine-readable line is `tmp-root-verify: refused=<roles|none>`.
2. **Prerequisite.** GNU `timeout` with `--kill-after` (coreutils; `gtimeout` on macOS) is required. Without
   it the installer exits 1 before writing anything. BusyBox `timeout` is not supported.
3. **Upgrade write.** The installer writes the resolver's default once, if `config.sh` lacks
   `HOS_TMP_ROOT`, and never changes an existing value. `HOS_INSTALL_TMP_ROOT=<value>` supplies a different
   value under the same checks. An empty value means "use the default".
4. **Changing `HOS_TMP_ROOT` after install (ruling (b)).** Moving the root once role dirs are registered is
   a re-point. The resolver refuses it until you approve it. Step by step, unsandboxed, in your own terminal:
   1. edit `HOS_TMP_ROOT` in `scripts/framework/config.sh`;
   2. run `status` for each role (`worker`, `overseer`, `human`, `local`); a re-point shows
      `NOT REGISTERED: refusing to re-point …`;
   3. run the `python3 <clone>/bootstrap/lib/hos_tmp_root.py mark --repo <clone> --role <role> --reviewed`
      command it prints, **once per registered (clone, role)**, in each clone whose `config.sh` changed;
   4. re-run the installer.

   For sandboxed sessions the value must be `../.tmp` (#2054 D15).
5. **Existing sandbox policy (ruling (a)).** An existing `.claude/settings.local.json` is never regenerated.
   If the installer warns that it "could not find the grant" for the Human temp dir, move the file aside
   and re-run the installer, or regenerate it with the `gen_sandbox_config.py` command the warning prints.
6. **Privacy (TD-H7; security-4, infra-6).** Paths under your home directory are written as `~/…` in the
   audit trail and alert issues. If the clone or `HOS_TMP_ROOT` is **outside** `$HOME`, its absolute path
   appears as-is in the committed audit trail (`audit/`), in alert issues filed in the project's GitHub
   repo, and, when it was set as an absolute value, in the committed `scripts/framework/config.sh`. The
   installer warns when it writes such a value. Keep both under `$HOME` if those paths are sensitive.

---

## 7. Failure modes of the new install steps (`reliability-reviewer`: mandatory)

| # | Failure | Behaviour | Direction | Test |
|---|---|---|---|---|
| FM-1 | A role dir holds a non-allowlisted entry | `status` exit 1 `unregistered-blocked`; the role is refused; the blockers and remedy are printed; exit 77; no stamp, no PR | fatal, loud | I-2 |
| FM-2 | Re-point (the key is registered at another live path) | `status` exit 1 `repoint`; the `_repoint_message` line names the `mark` command; exit 77; CRON-SETUP §5a gives the steps | fatal, loud | S-7, I-2c |
| FM-3 | Registry absent or masked (run sandboxed) | `status` exit 2 `registry-absent`, `CANNOT VERIFY`; exit 77; never a pass | fatal, loud | S-11, I-3b |
| FM-4 | Registry unreadable or malformed | `register` exit 3 (printed as `register:`); `status` exit 2 `registry-unreadable`; exit 77 | fatal, loud | S-11, I-3 |
| FM-5 | A resolver call hangs (NFS stall, a held flock) | Killed at `<T>` s, plus 5 s for KILL. **Fail-fast:** no further resolver calls, and the remaining roles are refused "skipped after an earlier timeout"; exit 77. A killed `register` can leave `tmp-roots.json.new.<pid>` (security-6). Worst case: §4.2's two calls plus one timed-out call, about 3 × 35 s. **Residual:** `timeout` cannot interrupt a process in uninterruptible sleep (D-state on a dead NFS mount). The KILL lands only when the syscall returns, and the install hangs until then. The remedy is to fix the mount | fatal, bounded (except D-state) | I-5, I-5b |
| FM-6 | No `timeout`/`gtimeout`, or no `--kill-after` support (BusyBox) | Prerequisite failure, exit 1 before any write or PR branch, naming coreutils and the package commands. A dry run warns and skips its resolver calls | fatal, loud, before any write | I-15, I-17, I-17b |
| FM-7 | `registry-full` | The `register:` line carries the resolver's `registry-full` remedy, before the `status` line; exit 77 | fatal, loud | I-16 |
| FM-8 | The target helper is missing, not a regular file, or differs from the source copy | All four roles refused, with the provenance reason; exit 77 | fatal, loud | I-14, I-14b |
| FM-9 | `python3` crashes in `resolve`/`status` | `status` maps every exception to exit 2 inside `main`. An interpreter crash is non-zero, so the role is refused | fatal, loud | S-13 |
| FM-10 | `install-default` or `validate` fails or times out, or the charset gate fails | Nothing written; the failure is deferred; register and verify are skipped; exit 77 with "Set HOS_TMP_ROOT … by hand"; `refused=worker,overseer,human,local`; agents and manifest written, no stamp, no PR | fatal, loud | I-11 |
| FM-11 | `config.sh` unreadable for the presence test | Deferred failure, "cannot read"; as FM-10 | fatal, loud | I-11c |
| FM-11b | The `config.sh` append fails (ENOSPC, EACCES, read-only) | The single `printf` is checked, never a `set -e` abort; deferred failure, "config.sh may now hold a partial HOS_TMP_ROOT line: fix or remove it by hand"; as FM-10. On the next run a partial line reads as present and is reported `INVALID:` | fatal, loud | I-11d |
| FM-12 | An existing `HOS_TMP_ROOT` is invalid | No write (never overwrite); `status` exit 2 `root-invalid`, with the `INVALID:` prefix and the INVALID bullet; exit 77 | fatal, loud | I-10c |
| FM-13 | Verify fails in `--pr` mode | No commit, push or PR; the consumer stays on `PR_BRANCH`, with the `%q`-quoted recovery commands (§4.7) | fatal, loud; recovery is manual (E-2) | I-2b, I-2d |
| FM-14 | A fresh install whose project is not yet in `projects.conf` (the normal order, `:2617`), or a lone clone | **E-1 (a): the ADR-literal XDG value is written.** On `--human` the sandbox generator warns (`:1838`); register and verify pass; exit 0. The §4.4 re-point warning tells the human to change the value **before first use**, and CRON-SETUP §5a gives the post-registration steps. The layout default is human question Q-1 | degraded, loud warnings; ruled | I-22 |
| FM-14b | An **upgrade** keeps an existing `.claude/settings.local.json` that lacks the Human role-dir grant (every v0.6.0 consumer, ruling (a)) | A non-fatal warning after verify passes, with the move-aside and regenerate remedy; exit 0. Regenerating automatically is human question Q-2 | degraded, loud warning; Q-2 | I-20 |
| FM-15 | Interrupted (HUP, INT, TERM) during register or verify | The traps exit 129, 130 or 143, no stamp, and a re-run is idempotent. The trap runs only after the foreground `timeout` child returns, which takes at most `<T>` + 5 s (reliability-8) | fail-safe | — |
| FM-16 | Parallel installer runs | `register` serialises on the flock (`:396-397`) | safe | — |
| FM-17 | The disk is full while `register` writes the registry | **Not claimed.** `register()` does not check short `os.write` results. It can rename a truncated file, which `status` then reports as `registry-unreadable`, with the "re-run unsandboxed" remedy, which is wrong for this cause. It can also leave `tmp-roots.json.new.<pid>`. Both are left to **follow-up #2148** (filed per ruling (g)). S4a guarantees only that the install exits 77 and does not stamp | not claimed | — |

**Partial state after a 77 exit** (AD-12's "complete-but-untrusted"):
- agents, `.hos-manifest` and the framework files are written;
- `.hos-release` holds the old tag, or is absent;
- no PR exists;
- after a verify refusal, the role dirs that did not refuse are registered (harmless; invariant 8), and
  `HOS_TMP_ROOT` was written this run if it was absent;
- after a deferred §4.2 failure, no `HOS_TMP_ROOT` line was written (or a partial one, FM-11b), and nothing
  is registered.

Earlier hard stops (exit 1 or 4) leave whatever state those paths already leave.

---

## 8. Tests

Every test uses the registry override, never the real file. A per-attempt registry is the default (§5). S1's
guard fails the session if the real registry changes.

### 8.1 `tests/framework/test_hos_tmp_root.py`

**Fixture rule (code-review-3).** S-1 to S-9, S-12 and S-13 seed the override with a valid **empty v1
registry**: mode 0600 in a 0700 dir, then any entries the case needs. Without that seed, `status` would
report `registry-absent`.

| ID | Case | Asserts |
|---|---|---|
| S-1 | registered, private | exit 0; `class=registered`, `blockers=[]`, `adoptable=null`; stdout empty without `--json` |
| S-2 | absent role dir; absent root | exit 1, `absent`, `adoptable=true`; both still absent afterwards |
| S-3 | unregistered, holding only `HOS_ONLY_RE` names | exit 1, `unregistered-adoptable` |
| S-4 | 7 blockers, one an allowlisted dir holding `.git` | exit 1, `unregistered-blocked`; `blocker_count == len(blockers) == 7`; one `project-files`; stderr has `mark --repo` and `and 2 more` |
| S-5 | on-disk names `b"a\nb"`, `b"\x01x"`, `b"\xff\xfe"` (skip on darwin), and a 255-byte name | each `bytes.fromhex(name_hex) == original`; one ASCII line. The **stderr line is still exactly one line**: the `\n` inside the name appears as the two characters `\n` (code-review-10) |
| S-6 | a serializer round-trip of a 10 240-byte name containing `\n`, `\x00`, `\x01` and `\xff` | byte-exact; one ASCII line |
| S-7 | re-point (the key at root A; config names root B; B's dir present, then absent) | exit 1, `repoint`; `refusing to re-point` |
| S-8 | registered for another repo only | exit 1, `unregistered-adoptable`, `blockers=[]` |
| S-9 | inode change | exit 1 |
| S-10 | symlink; regular file; wrong case (the `:766` monkeypatch); wrong owner (`os.getuid` monkeypatched); registered at mode 0755; root invalid; internal error | exit 2; classes `structural` ×5, `root-invalid` and `error`; the line starts `…: INVALID:` and contains `Fix the path or value named on this line`; it never contains `CANNOT VERIFY` or `unsandboxed` |
| S-11 | registry missing; a directory; mode 0644; malformed | exit 2, `registry-absent` then `registry-unreadable` ×3; the line starts `…: CANNOT VERIFY:` and contains `not inside a Claude session`; never `INVALID:`; a missing registry is **not created** |
| S-12 | no side effects, over the S-1, S-2, S-4, S-10 (0755) and S-11 (missing) states | the tree snapshot and the registry bytes are unchanged; no `.lock` and no marker. With `os.mkdir`, `os.makedirs`, `os.chmod`, `os.rename`, `os.unlink`, `register`, `write_info_marker` and `_make_dirs_0700` patched to raise, and `os.open` patched to raise on `O_CREAT`, `O_WRONLY` or `O_RDWR`, `main(["status", …])` still returns the expected code |
| S-13 | an invalid `--role`; `resolve_root` patched to raise `OSError` | exit 2 with no JSON; exit 2 `error`, no traceback; never 3 |
| S-14 | `adoption_problems` parity (the S-4 fixture, an unreadable listing, an empty dir) | literal expected strings; core and formatter agree; **every pre-existing guard test passes unchanged** |
| S-15 | `install_default` slug (ruling (e)): `""`, `.`, `..`, `...`, `../x`, `My App` | `…/tmp/project` ×4, `…/tmp/..-x`, `…/tmp/my-app`; no result has `.` or `..` as its last component; the multi-clone path is unchanged |

### 8.2 `tests/framework/test_install_tmp_root_verify.py`

These run the real `hos_install.sh --local` with `HOS_NO_CONFIG=1` and stdin `"\n"`, as at
`test_pack_install.py:40-62`.

**Shims.**
- A **`python3` shim** first on `PATH` logs argv. For `…/hos_tmp_root.py <sub>` it can set a per-subcommand
  `HOS_TMP_REGISTRY_FILE` (always non-empty), sleep while respecting TERM, sleep while ignoring TERM, or
  print a decoy on stdout. Otherwise it `exec`s the real interpreter.
- A **`cp` shim** (I-14b) appends one byte when its destination ends in `bootstrap/lib/hos_tmp_root.py`.
- **Extracted-function cases** `sed` a §4.0 function out of the installer, from `^name() {` to the first
  `^}`, source it into `bash -c`, and call it with arguments.

| ID | Case | Asserts |
|---|---|---|
| I-1 | fresh, clean | rc 0; exactly one `refused=none`; four dirs at 0700; 4 registry entries for `realpath(target)`; `status` 0 ×4; one `_LINE_RE` line, `HOS_TMP_ROOT="../.tmp"`; `(from HOS_INSTALL_TMP_ROOT)`; `.hos-release` written. **RC-8:** the shim's `resolve` stdout decoy `/decoy` appears nowhere, and the `ok` line names `realpath(<parent>/.tmp)`. The RC-7 notice names the per-attempt path. No re-point warning and no outside-`$HOME` warning |
| I-2 | refused: config `HOS_TMP_ROOT="<tmp>/root"`, `.hos-release`=`v0.6.0`, `root/Worker` holding `percommit-2054/` | rc 77; `refused=worker`; the output has `percommit-2054`, `mark --repo`, `not inside a Claude session` and `mv '`; `.hos-release` still `v0.6.0`; manifest and agents written; the other three registered. After `mv` and a re-run: rc 0, `refused=none`, `.hos-release` updated |
| I-2b | as I-2 with `--pr`, a bare `file://` origin and a logging `gh` stub | rc 77; no `pr create`; no remote `hos-upgrade/*`; on `PR_BRANCH`. The three `git -C … stash push --include-untracked -m …`, `checkout …` and `branch -D …` lines are present, `%q`-quoted, and the stash message is one word. The machine-local sentence is present. No `git clean`, `reset --hard` or `checkout -- .`. **Hostile original branch:** the consumer starts on `b;touch${IFS}PWNED` (a legal ref name). Running the printed `checkout` line with `bash -c` creates no `PWNED`, and git receives the literal name. **End to end:** run the three printed commands, `mv` the blocker, re-run with `--pr`. Expect rc 0, `refused=none`, one `pr create`, and the stash entry still present |
| I-2c | re-point: register Worker at root A, then config at root B | rc 77; `refusing to re-point` |
| I-2d | **extracted `_hos_tmp_pr_recovery`** with tag `v1$(touch PWNED)`, branch `` x`touch PWNED2` ``, and target `/t; touch PWNED3` | each printed `git` line, run via `bash -c` with `git` replaced by an argv-logging stub, creates no `PWNED*` file. The stub receives exactly the original strings, and `-m`'s value is `hos-upgrade v1$(touch PWNED)` |
| I-2e | mixed refusal: `root/Worker` holds a blocker; `root/Human` is a symlink | rc 77; `refused=worker,human`; both the NOT REGISTERED bullets and the INVALID bullet are printed; the CANNOT VERIFY bullet is not |
| I-3 | the registry is a directory | rc 77; refused all four; every `verify:` line is `CANNOT VERIFY:`; only the CANNOT VERIFY bullet and Always |
| I-3b | the shim gives `status` a missing registry and `resolve` a valid one | rc 77; refused all four; `CANNOT VERIFY` |
| I-4 | the shim gives `resolve` registry A and `status` registry B (an empty v1 document) | rc 77; refused all four |
| I-5 | **fail-fast** (ruling (f)): `HOS_INSTALL_TMP_VERIFY_TIMEOUT=2`; the shim sleeps (TERM-respecting) on `resolve --role overseer` and on `status --role worker` | rc 77; `refused=worker,overseer,human,local`; overseer `register: resolve --create did not answer within 2 s (timed out or was killed)`; human and local `register: skipped after an earlier timeout`; every role's `verify:` is `skipped after an earlier timeout`; the shim log shows **no `status` call** and no `resolve` for human or local; wall time under (2 + 5) + 60 s; no stray `sleep` survives |
| I-5b | as I-5, with the overseer `resolve` ignoring TERM | `timeout` sends KILL after 5 s (rc 137, classified `timeout`); the same output as I-5 |
| I-5c | **verify-phase fail-fast**: only `status --role overseer` sleeps (TERM-respecting), `HOS_INSTALL_TMP_VERIFY_TIMEOUT=2` | rc 77; `refused=overseer,human,local`; the worker passes; overseer `verify: status did not answer within 2 s (timed out or was killed)`; human and local `verify: skipped after an earlier timeout`; the shim log has all four `resolve` calls and no `status` for human or local |
| I-6 | idempotent re-run of I-1 | rc 0; `config.sh` byte-identical; still 4 entries |
| I-7 | argv audit (I-1, I-8) | subcommands only `install-default`, `validate`, `resolve --create` and `status`; never `mark` or `--reviewed` |
| I-8 | **v0.6.0 upgrade, non-interactive**: `.hos-release`=`v0.6.0`; v0.6.0 keys, no `HOS_TMP_ROOT`; no `bootstrap/lib/`; `HOS_INSTALL_TMP_ROOT=""`; a fake `HOME` whose `projects.conf` lists a sibling `<p>_worker_root` | rc 0; one line `HOS_TMP_ROOT="../.tmp"` `(resolver install-default)`; 4 registered and verified; stamp updated; a re-run is byte-identical |
| I-8b | lone clone, `--dry-run`, `HOS_INSTALL_TMP_ROOT=""`, no `projects.conf` | `Would append HOS_TMP_ROOT="~/.local/state/hos/tmp/<slug>" … (resolver install-default)`; nothing written |
| I-9 | **interactive v0.6.0 upgrade** (`slow`; a pty from `os.openpty()` pre-loaded with 60 `\n`, the master drained by a thread; `HOS_INSTALL_TMP_ROOT=""`; `projects.conf` as I-8) | rc 0; the final `config.sh` has one `_LINE_RE` match with §4.2's value; 4 verified; `refused=none` |
| I-10 | existing `export HOS_TMP_ROOT="../custom"`, `   HOS_TMP_ROOT=../custom`, and `HOS_TMP_ROOT=""` | `config.sh` byte-identical; dirs under `../custom` (`../.tmp` for the empty value) |
| I-10c | existing `HOS_TMP_ROOT="./inside"` | not rewritten; rc 77; a `verify:` line `INVALID:` with "inside the clone"; the INVALID bullet; **no** `mv`/`mark` bullets and no "unsandboxed" anywhere |
| I-11 | **deferred §4.2 failure** (ruling (c)): `HOS_INSTALL_TMP_ROOT="<tmp>/a+b"` (charset); `="./tmp"` (`validate`); the shim makes `install-default` exit 1 | each: rc 77; `Set HOS_TMP_ROOT in` and `by hand, then re-run`; no `HOS_TMP_ROOT` line; `refused=worker,overseer,human,local`; **`.hos-manifest` and agents written**; `.hos-release` unchanged; the shim log has **no `resolve` and no `status`**; only the Always bullets |
| I-11c | `config.sh` mode 000 (skip if euid 0) | rc 77, `cannot read`, as I-11 |
| I-11d | **write failure** (reliability-2): `config.sh` mode 0444, key absent (skip if euid 0) | rc 77; `config.sh may now hold a partial HOS_TMP_ROOT line`; no abort before the summary line (exactly one `refused=` line); as I-11 |
| I-11e | `PROJECT_NAME=..`, `HOS_INSTALL_TMP_ROOT=""`, lone clone, **`--dry-run`** (ruling (e); a real write would register under the passwd home) | `Would append HOS_TMP_ROOT="~/.local/state/hos/tmp/project"`; never `…/tmp/.."` |
| I-12 | `--dry-run`, fresh | rc 0; `Would register and verify`; exactly one `tmp-root-verify: skipped=dry-run`; no `refused=`; nothing created |
| I-13 | static | exactly one `exit 77` on non-comment lines |
| I-14 | static: no `--reviewed` anywhere, and no non-comment `hos_tmp_root.py … mark`. Dynamic: the target's helper path pre-created as a **directory** | rc 77; refused all four; "missing, not a regular file, or differs" |
| I-14b | **provenance** (security-1): the `cp` shim tampers with the target's helper copy | rc 77; refused all four; the same provenance reason; the shim log shows no `resolve`/`status` run from the target helper |
| I-15 | static: on non-comment lines, the `_hos_tmp_register_and_verify` call comes after the `.hos-manifest` write and before the `.hos-release` write, which comes before `if $PR_ACTIVE; then`. The default `30` and `--kill-after=5s`. Every `hos_tmp_root.py` invocation line starts with `"${_HOS_TMP_PREFIX[@]}"` (no unbounded path). The prerequisite check and the `--kill-after=1s 1s true` probe are inside the prerequisite block. Only the helper and `PACK` lines append `>> "$_subst_config"`. Only the two §4.1 capture forms are used. Each §4.0 decision function is column-0 and extractable | static |
| I-16 | **registry-full**: 256 live pre-seeded entries | rc 77; each role has a `register:` line containing `already holds 256 live temp roots`, before its `verify: … NOT REGISTERED` |
| I-17 | **no timeout binary**: `PATH` is a shim dir that symlinks every entry of the original `PATH` dirs (first match wins) except `timeout` and `gtimeout`; `python3` is a logging wrapper | rc **1**; `GNU coreutils`, `brew install coreutils`; nothing written. With `--dry-run`: rc 0; `a real install would stop here`; no `hos_tmp_root.py` invocation |
| I-17b | **BusyBox-like `timeout`**: as I-17, plus a fake `timeout` that rejects `--kill-after` | rc 1; the same message (the probe failed) |
| I-17c | **`gtimeout` selection**: as I-17, but the shim dir also holds a `gtimeout` entry that is a symlink to the real GNU `timeout` | rc 0; `timeout present (gtimeout, supports --kill-after)`; `refused=none` (the bounded calls ran through `gtimeout`) |
| I-18 | **containment**: `git ls-files` limited to `bin/`, `bootstrap/`, `scripts/` and `.github/` (if present), minus `tests/**`; grep the literal `HOS_INSTALL_TMP_ROOT` | the only hit is `bootstrap/hos_install.sh` |
| I-19 | **override notice**: (1) I-1; (2) the installer env has `HOS_TMP_REGISTRY_FILE=""`, and the `python3` shim exports a non-empty per-attempt override before `exec` | (1) exactly one `HOS_TMP_REGISTRY_FILE is set (<path>)` before the first `register:`/verify output; (2) none. S1's guard still passes |
| I-20 | **sandbox grant check** (ruling (a)): `--human`; a pre-existing `.claude/settings.local.json` **without** the Human dir path; then with it; then with no file; then without `--human` | (a) rc 0; one `could not find the grant` warning with `<H>`, the `mv … .bak-` remedy and the `gen_sandbox_config.py --role human --clone-dir <target>` command; (b) no warning; (c) no grant warning (the generator path runs as today); (d) no check |
| I-21 | **outside `$HOME`** (infra-6): `HOME` is a fake dir not containing `tmp_path`; `HOS_INSTALL_TMP_ROOT=<tmp>/abs-root` | rc 0; one warning naming the root and `config.sh, which is committed, now records HOS_TMP_ROOT=<tmp>/abs-root`. With the key pre-set (no write): no warning |
| I-22 | **re-point guidance** (ruling (b)): `HOS_INSTALL_TMP_ROOT=<tmp>/elsewhere` (≠ `<parent>/.tmp`) | rc 0; one warning `HOS_TMP_ROOT was set to … it must be ../.tmp; change it now, before first use … See docs/CRON-SETUP.md §5a`; no `--reviewed` in the output. In I-1 (`../.tmp`) and I-10 (no write): no warning |
| I-23 | **extracted decision functions** (ruling (d)) | `_hos_tmp_classify_rc` 0/124/137/1/3 → ok/timeout/timeout/fail/fail. `_hos_tmp_prefix_of` on each §2.4 line plus a timeout reason → not-registered, cannot-verify, invalid, other. `_hos_tmp_select_remedy` over all 8 `(nr, cv, inv)` combinations → exactly the bullets of §4.4, and Always every time. `_hos_tmp_verdict` on all-pass, one, two and all refused → `none`/CSV in role order. `_hos_tmp_root_from_ok` on a normal line, a path containing ` is registered for `, and garbage → root / first-cut root / `""` |

### 8.3 `tests/framework/test_tmp_root_first_writer.py`

| ID | Case | Asserts |
|---|---|---|
| W-1 | install, then an export-only session where a third party writes `node-compile-cache/` and `percommit-2054/`, then `resolve --repo <target> --role worker --create` | install rc 0; the resolver exits 0 and prints `<root>/Worker`; `status` exits 0 (invariant 8) |
| W-2 | control: a hand-made `mkdir -m 700` dir, with the same writes and the same call | exit 3, naming `percommit-2054`; nothing registered; contents unchanged |

S4b appends its wrapper case here later.

### 8.4 `tests/framework/test_registry_isolation.py` (additions)

- Two tests see different `HOS_TMP_REGISTRY_FILE` paths. Both are under the session basetemp, and neither
  is the real path.
- **Rerun (ruling (h) reliability-1).**
  - Setup: a `pytester` run with `-p rerunfailures --reruns 1`. One test records its registry path to a
    file, fails on its first attempt and passes on its second.
  - Expected: two different paths, and the run passes.
  - A second test registers 4 entries on each attempt; the second attempt sees exactly 4, not 8.
- A test's own `monkeypatch.setenv` override is kept. So is a caller-set override, in which case
  `_SESSION_REGISTRY is None`.
- `child_env({"PATH": …})` carries `HOS_INSTALL_TMP_ROOT == "../.tmp"`. `child_env({"HOS_INSTALL_TMP_ROOT":
  ""})` keeps `""`.
- **Inherited value replaced (RC-5).** A `pytester` run started with `HOS_INSTALL_TMP_ROOT=/abs/elsewhere`
  sees `../.tmp` inside, and after the run the outer value is restored (code-review-9).
- **Module scope (RC-10).** A module fixture sees the session path; a function test sees a per-attempt path.
- Every existing S1 test passes unchanged.

### 8.5 ADR S4a obligation → test map

| Obligation | Test(s) |
|---|---|
| A fresh install registers **and verifies** four dirs, then exits 0 | I-1 |
| Export-only, then a third-party write, then the launcher | W-1, W-2 |
| A refused dir: blockers and remedy, non-zero after every other step; the re-run passes | I-2, I-2e |
| Unreadable registry → "re-run unsandboxed" | I-3, I-3b, S-11 |
| v0.6.0 upgrade, non-interactive and interactive; never overwrite | I-8, I-9, I-10 |
| `--dry-run` writes nothing | I-12, I-8b, I-11e |
| Never `--reviewed` | I-14, I-7, I-22 |
| A failed verify exits 77, leaves the old stamp, opens no PR | I-2, I-2b, I-13 |
| A registration in a different registry fails | I-4 |
| `status` is read-only; a masked registry is exit 2 | S-12, S-11, S-2 |
| TD-H5: all blockers, byte-exact | S-4, S-5, S-6 |
| An out-of-gate value writes nothing and exits 77 | I-11 |
| Exactly one summary line (a run that reaches §4.3) | I-1, I-2, I-3, I-5, I-11, I-11d (and I-12's `skipped`) |
| A hang is killed and counted as a refusal | I-5, I-5b, I-15, I-17, I-17b |

### 8.6 Branch → test table (ruling (d); the `shell_logic_check` exception)

| Function / site | Branch | Test |
|---|---|---|
| prerequisite (§4.1) | `timeout` usable / `gtimeout` usable / neither / probe fails / dry-run without one | I-1, I-17c, I-17, I-17b, I-17 (dry-run) |
| `_hos_tmp_classify_rc` | 0 / 124 / 137 / other | I-23, I-5, I-5b, I-2 |
| `_hos_tmp_prefix_of` | NOT REGISTERED / CANNOT VERIFY / INVALID / other | I-23, I-2, I-3, I-10c, I-5 |
| `_hos_tmp_select_remedy` | each of `nr`/`cv`/`inv` alone; mixed; none (timeout or helper only) | I-23 (all 8), I-2, I-3, I-10c, I-2e, I-5 |
| `_hos_tmp_verdict` | none / one / several / all | I-23, I-1, I-2, I-2e, I-3 |
| `_hos_tmp_root_from_ok` | parse ok / fallback | I-23, I-1 |
| `_hos_tmp_pr_recovery` | quoting under hostile values | I-2d, I-2b |
| §4.2 `_hos_tmp_ensure_key` | present / absent + env / absent + install-default / env `""` = unset / charset fail / `validate` fail / `install-default` fail / unreadable / write fail / dry-run ok / dry-run fail / dry-run without a timeout binary | I-10, I-1, I-8, I-8, I-11, I-11, I-11, I-11c, I-11d, I-8b, I-11e (dots) and I-12, I-17 |
| §4.3 deferred failure | skip register and verify → 77 | I-11, I-11c, I-11d |
| §4.3 provenance | not a regular file / `cmp` mismatch / ok | I-14, I-14b, I-1 |
| §4.3 notice | set / empty / unset | I-1, I-19 |
| §4.3 register | ok / fail / timeout → fail-fast | I-1, I-16, I-5 |
| §4.3 verify | pass / refused / timeout → fail-fast / skipped after a register timeout | I-1, I-2, I-5c, I-5 |
| §4.3 grant check | `--human` with the file lacking / containing the grant / no file / not `--human` | I-20 |
| `_hos_tmp_summary` warnings | re-point yes/no; outside `$HOME` yes/no | I-22, I-1; I-21, I-1 |
| `_hos_tmp_fail_77` | plain / `PR_ACTIVE` / deferred | I-2, I-2b, I-11 |

`@pytest.mark.slow` (release only, `pyproject.toml:23`) applies to I-9 and I-2b. Every other case runs in the
PR-required suite.

---

## 9. Protected surface, reviewers, PR obligations

- **Protected.** Both `bootstrap/**` files fall under the human approval gate whatever the tier. The
  overseer may not merge them.
- **Reviewers.** `reliability-reviewer`, `security-reviewer` (RC-9 and ruling (e)) and `code-reviewer`.
- **The S4a PR body must state:**
  - **#2059** absorbs the §4.2 writer on rebase. Its re-review covers that writer and `install.sh:148`'s
    indented-key miss;
  - **S3** extends `adoption_blockers`;
  - **S2** consumes `status --json` (§3.2) and owns `shlex.quote` in `_remedy`/`_repoint_message`
    (security-5);
  - **Landing order:** S4a merges before S2 or with it;
  - **#2137's obligations (RC-6; ruling (h) infra-4).** #2137's v0.6.0-upgrade case must:
    - **not** set `HOS_INSTALL_TMP_ROOT`;
    - list the target with a **sibling** in a `projects.conf` (as I-8), so that `install-default` yields
      `../.tmp`;
    - set a non-empty `HOS_TMP_REGISTRY_FILE`, because `install-default` on a lone clone resolves `~`
      against the passwd home;
    - exercise a sandboxed Human session (Q-2);
  - **The declared `shell_logic_check` exception (ruling (d)).** The installer orchestrates and reports,
    while `resolve`/`status` make the trust decisions. Each decision is one extractable named function, and
    §8.6 maps every branch to a test. The `shell_logic_check.py` finding on `hos_install.sh` is reproduced
    in full and **not suppressed**;
  - **Follow-up #2148 (ruling (g))** for `register()`'s short-write and leftover `.new.<pid>` handling. FM-17
    is not claimed;
  - every item in §9.1.

### 9.1 PR-body disclosures (each is a behaviour a human will notice)

- **(a) The HOS dev machine.** Every real `hos_install.sh` run into a clone sharing `../.tmp` verifies all
  four role dirs. It therefore **exits 77 until `.tmp/Human` is fixed**, by S3 or by the human's own `mv`
  or `mark`. The disclosure lists the four read-only `status` commands to run first.
- **(b) E-1 and Q-1.**
  - Any fresh install whose project is not yet in `projects.conf` (the normal order, `:2617`) gets the
    ADR-literal `~/.local/state/hos/tmp/<slug>`. The value then reaches the other role clones through the
    committed `config.sh`.
  - On `--human`, sandbox generation warns.
  - The installer's re-point warning (ruling (b)) says to change the value to `../.tmp` **before first
    use**. After registration, moving it is a re-point that needs `mark` approvals for each (clone, role).
    CRON-SETUP §5a gives the steps.
  - Q-1 is open.
- **(c) New prerequisite.** GNU `timeout` with `--kill-after` (coreutils), or exit 1. BusyBox is
  unsupported.
- **(d) Existing sandbox policies (ruling (a), Q-2).**
  - An upgraded consumer's existing `.claude/settings.local.json` is never regenerated (#1221).
  - v0.6.0's template granted no `.tmp/<Role>` dir, so its sandboxed Human session cannot write `TMPDIR`.
    That holds whatever the root.
  - S4a warns, non-fatally, with the remedy. Automatic regeneration is Q-2.
- **(e) Slug narrowing (ruling (e)).** A `PROJECT_NAME` made up only of dots now defaults to `…/tmp/project`.

---

## 10. Interpretations (all accepted; current status)

- **I-1** (§2.6): accepted; `security-reviewer` is mandatory.
- **I-2** (§2.3 step 5): accepted.
- **I-3** (§2.3 step 8): accepted, with the `INVALID:` prefix.
- **I-4** (§4.4): accepted; the bullets depend on the prefixes.
- **I-5** (§4.2): accepted; the `install.sh:148` indented-key issue goes to #2059's re-review.
- **I-6** (§4.5): **recorded in REQUIREMENTS-2100 REQ-11**, scoped to "a run that reaches the
  register/verify step" (commit `61fbeebc4`; code-review-7). The scope exists because `--help` and earlier
  hard stops exit without a line. The invariant, for a run
  that reaches §4.3:
  - exit 77 ⇔ exactly one line with `refused≠none`;
  - exit 0 ⇔ exactly one `refused=none` line;
  - a dry run prints exactly one `skipped=dry-run`.
- **I-7** (F-7): accepted.
- **I-8** (§2.7): **accepted (architect round 4).** The arbitration listed `../x → x` among the slug tests.
  The ruled rule (dots-only → `project`) leaves `../x` as `..-x`, because `[^a-z0-9._-]` already maps `/` to
  `-`. `..-x` is a single safe path component. It cannot traverse, and it leaves no `.` or `..` component.
  S-15 therefore expects `..-x`. The architect confirmed that `..-x` is correct: `../x → x` was a slip. The
  bound is that no `.` or `..` component results, and leading-dot stripping is **rejected**.
- **I-9** (I-11e): **accepted (architect round 4).** The arbitration's "I-11 case `PROJECT_NAME=..` writes
  `~/.local/state/hos/tmp/project`" runs as **`--dry-run`**. A real install would then register under the
  passwd home (F-2). The assertion is the would-append line. I-11e stays a dry run.

---

## 11. Escalations and open questions

All round-1 escalations (E-1 to E-4) and every reviewer arbitration are **ruled** (§13). Open items:
- **Q-1 (human; gates the v0.7.0 cut, not S4a's merge).** What should the fresh-install layout default be?
  The recommendation is a #2054 follow-up that makes `install-default` recognise the Worker/Overseer/Human
  sibling layout.
- **Q-2 (human; before the v0.7.0 cut; does not block S4a).** An existing `settings.local.json` is never
  regenerated (#1221), so every upgraded consumer's sandboxed Human session breaks. The recommendation: on
  upgrade, when the existing policy lacks the role-dir grant, regenerate it, keeping a timestamped backup.
  That relaxes #1221. #2137 must exercise a Human sandbox session. Q-2 is also a `startup-artifact-gap`
  against #2054.
- ~~For the architect to confirm in round 4: I-8 and I-9 (§10).~~ **Confirmed (architect round 4).** I-8 is
  accepted: `..-x` is correct, the bound is no `.` or `..` component, and leading-dot stripping is rejected.
  I-9 is accepted: I-11e stays a dry run. See §13.4.

**Contradictions with the ADR:** none.

---

## 12. Startup-gap check and affected sign-offs

- **Startup gap: yes,** for F-3, E-1, Q-1 and Q-2, at #2054's architecture. `install-default`'s lone-clone
  value, D15's single accepted root, and #1221's never-regenerate policy were never reconciled. The
  recommendation is a `startup-artifact-gap` against #2054 that carries Q-1 and Q-2. It is not filed here.
- **The round-4 changes** are to an unbuilt design, so no code approval is orphaned.
- **Affected sign-offs:**
  - **#2054 S2a resolver security review.** It stands for the resolve path. §2.6 and §2.7 (the
    `install_default` narrowing) need the mandatory S4a `security-reviewer` sign-off.
  - **S1 (PR #2140).** It stands. §5 refines the conftest, and the guard is unchanged.
  - **The reviewer sign-offs on TD round 3** are **superseded** by round 4. The four lenses re-check the
    deltas:
    - `code-reviewer`: findings 1–4 and 6–10;
    - `security-reviewer`: findings 1–4;
    - `reliability-reviewer`: findings 1–8;
    - `infra-reviewer`: findings 1–8.
  - **No approved code is affected.** S4a is unbuilt.

---

## 13. Architect rulings

### 13.1 Round 1 (2026-10-22): CHANGES_REQUIRED, RC-1 to RC-13

| ID | Ruling | Lands in |
|---|---|---|
| E-1 | (a) build the ADR-literal `install-default` value in S4a. (b) is rejected as only a partial fix: `config.sh` is committed and shared, so a Worker-first install passes the XDG value to Human anyway. A resolver-side flag would satisfy AD-12, but would not fix that. The real fix is Q-1 | FM-14, §9.1(b) |
| Q-1 | Human question; gates the v0.7.0 cut, not S4a's merge | §11 |
| E-2 | Stay on `PR_BRANCH`, with exact stash/checkout/branch commands; never `clean` or `reset --hard`; the remedy is machine-local | §4.7 |
| E-3 | Accepted, on condition of RC-5 (always set), RC-6 (containment, source shown, #2137 must not set it) and RC-10 (scope bound) | §4.2, §5 |
| E-4 | Reversed: fail closed. A timeout binary is a prerequisite | §4.1 |
| I-1 to I-7 | Accepted (see §10) | §10 |

### 13.2 Round 2 (2026-10-22): CHANGES_REQUIRED, 4 items

1. FM-12 and FM-13 were restored to five columns, and their assertions moved into I-10c and I-2b.
2. A register timeout prints a `register:` line.
3. I-18 was scoped to code directories, with no document allowlist.
4. The E-1 (b) reason was corrected, and the disclosure was widened to every unlisted fresh install.

### 13.3 Round 4 (2026-10-22): reviewer arbitration (a)–(h)

| Ruling | Decision | Lands in |
|---|---|---|
| (a) infra-1 | The premise was corrected: v0.6.0's template had no `.tmp/<Role>` grant, so every upgrade that keeps `settings.local.json` breaks the sandboxed Human session. "Preserve the effective root" is rejected. S4a adds a non-fatal "could not find the grant" warning after verify on `--human`. **Q-2** is added | §4.3 step 8, FM-14b, I-20, §6, §9.1(d), §11 |
| (b) re-point trap | An installer warning when the written value ≠ `<parent>/.tmp` (no `--reviewed`); the existing `_repoint_message`; the CRON-SETUP §5a steps (the doc may name `--reviewed`) | §4.4, FM-14, I-22, §6 item 4 |
| (c) §4.2 timing | Deferred: record the failure and write nothing. §4.3 skips register and verify, prints the message and the Always bullets, `refused=` all four, exit 77. Earlier hard stops win | §4.2, §4.3, §4.4, FM-10/11/11b, §7, I-11 |
| (d) code-review-5 | Keep shell as a declared exception. Each decision is one named, extractable function; there is a branch → test table; the `shell_logic_check` finding is disclosed and never suppressed | §4.0, §8.6, I-23, §9 |
| (e) security-3 | A dots-only slug → `project`, in `install_default`. Unit tests, plus an installer `PROJECT_NAME=..` case | §2.7, S-15, I-11e, §9.1(e), §10 I-8/I-9 |
| (f) reliability-4 | Fail fast after the first timeout; the remaining roles are "skipped after an earlier timeout"; the D-state residual is stated | §4.1, §4.3, FM-5, I-5, I-5b, I-5c |
| (g) reliability-3 | FM-17 narrowed to "not claimed"; follow-up #2148 (filed) | FM-17, §9 |
| (h) others | A per-attempt registry via `tmp_path_factory.mktemp`, with a rerun test. `""` instead of pop, with the I-19 non-empty shim caveat. An atomic, checked `config.sh` append. The `--kill-after` probe (BusyBox unsupported; coreutils named). Helper `cmp -s`. `%q` on the tag and stash message, with hostile cases. The #2137 obligations. The outside-`$HOME` warning. The privacy note names `config.sh`. code-review 3, 4, 6, 8, 9, 10; security 5 (to S2) and 6; reliability 7 and 8; infra 7 and 8. code-review-7 goes to `pm-agent` | §4.1–§4.7, §5, §6, §7, §8, §9, §10 |

Security's APPROVED verdict stands, on condition of (e), which is applied.

### 13.4 Round 4 verdict (2026-10-22): APPROVED

| ID | Ruling | Lands in |
|---|---|---|
| I-8 | **Accepted.** `../x` → `..-x` is correct. The arbitration's `../x → x` was a slip. The bound is that no `.` or `..` component results. Leading-dot stripping is **rejected** | §2.7, S-15, §10 |
| I-9 | **Accepted.** I-11e (`PROJECT_NAME=..`) stays a `--dry-run` case | I-11e, §10 |
| Follow-up | `register()`'s short-write and leftover `.new.<pid>` handling is filed as **#2148** | FM-17, §9 |
| REQ-11 | The I-6 clarification is recorded in REQUIREMENTS-2100 REQ-11, scoped to "a run that reaches the register/verify step" (commit `61fbeebc4`) | §10 I-6 |

---

## Escalation flag (CORE self-flag)

RISK: HIGH. Both code files are protected (`bootstrap/**`). The slice touches every consumer's install path:
- a new fatal failure mode (exit 77);
- a new prerequisite (exit 1);
- install-time warnings that change what a human does next.

It also rewrites the body of the guard's adoption check (behaviour-preserving), narrows `install_default`,
and changes the test isolation that every test inherits.

CONFIDENCE:
- **HIGH:** the `status` contract; F-1, F-2, F-5, F-8 and F-9; the deferred-failure ordering; the placement
  relative to `.hos-release` and the PR block; the output contract and the extractable-function scheme.
- **MEDIUM:**
  - the pty test (I-9);
  - the I-16 fixture (256 live entries with real inodes);
  - I-17's PATH mirror on unusual CI images;
  - whether §5's central fix leaves zero existing harnesses to touch (the reserve slots cover it);

BLAST RADIUS:
- every HOS project install and upgrade (fresh, v0.6.0 → v0.7.0, `--pr`, `--dry-run`), with a new hard
  prerequisite;
- on the HOS dev machine, every install exits 77 until `.tmp/Human` is fixed;
- `hos_tmp_root.py`'s CLI and `install-default`;
- every test that runs the resolver or the installer;
- `docs/CRON-SETUP.md` §5a.

No gate, label, merge, reaper or launcher path changes.

Change classification: **additive**, inside the human-ruled structural change. The prerequisite and the slug
rule tighten existing behaviour; nothing is weakened.

## Human Review Required

- Your own-account approval of the S4a PR (protected `bootstrap/**`).
- **Q-1 (gates the v0.7.0 cut, not this merge).** What should the default `HOS_TMP_ROOT` be for a fresh
  install whose project is not yet in `projects.conf`? The architect recommends making `install-default`
  recognise the sibling-clone layout.
- **Q-2 (before the v0.7.0 cut; does not block S4a).** Should an upgrade regenerate an existing
  `.claude/settings.local.json` that lacks the role-dir grant, keeping a timestamped backup? That would
  relax #1221's never-overwrite rule. Without it, every upgraded consumer's sandboxed Human session cannot
  write its temp dir.
- Before installing S4a on the HOS dev machine: fix `.tmp/Human` (S3, or your own `mv` or `mark`), or every
  install there exits 77.
