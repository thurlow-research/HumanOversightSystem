# TECHNICAL DESIGN — #2100 slice S4a: install-time registration, the read-only `status` read-back, fail-on-refusal (exit 77), and the v0.6.0 `HOS_TMP_ROOT` upgrade write

**Status:** REVISION 2, in reply to **architect round 1: CHANGES_REQUIRED** (13 required changes; ruling at
`.claudetmp/design/architect-2100-S4a-2026-10-22T083613Z.md`). All 13 are folded into the body, and §13
records the rulings. **Awaiting the architect's round-2 check, so not yet ready for `coder`.** Each change
lands in these sections:

| Change | Where |
|---|---|
| RC-1 (register failure printed) | §4.3, §4.4, I-16 |
| RC-2 (`CANNOT VERIFY` vs `INVALID`) | §2.4, §4.4, S-10, S-11, I-3, I-10c |
| RC-3 (timeout fail-closed) | §4.1, FM-6, §6, I-15, I-17 |
| RC-4 (`--pr` recovery commands) | §4.7, I-2b |
| RC-5 (conftest unconditional) | §5, §8.4 |
| RC-6 (variable containment) | §4.2, I-18, §9 |
| RC-7 (registry-override warn) | §4.3, I-19 |
| RC-8 (capture method) | §4.1, §4.3, I-1 |
| RC-9 (`security-reviewer` mandatory) | §1, §9 |
| RC-10 (fixture scope) | §5 |
| RC-11 (PR-body disclosures) | §9.1 |
| RC-12 (I-6 for `pm-agent`) | §10 |
| RC-13 (E-1 ruling) | FM-14, §9, §11, §13 |

**Date:** 2026-10-22 (round 1); revised 2026-10-22 (round 2)
**Author:** technical-design (autonomous worker cycle; no human present)
**Baseline:** `HEAD` = `origin/main` = **`70ba746e1`** (the merge of PR #2146, the ADR-2100 fail-closed amendment).
Every file:line below refers to that commit. §0.3 lists the drift from the line numbers the ADR cites.
**Change classification:** **additive**, inside a structural change the human has already ruled. The
fail-closed install, the v0.6.0 upgrade write and the release gate were ruled on 2026-10-20 (ADR-2100
Amendment). This slice adds:
- one read-only subcommand;
- one install step, with one new failure mode (exit 77) that the ruling already covers;
- one operator environment variable (§4.2, E-3);
- a per-test refinement of the S1 test isolation (§5, E-3).

**Binding inputs:**
- `docs/v0.7.0/ADR-2100-tmp-root-first-use-registration.md` as amended 2026-10-21. The relevant parts are
  AD-5 (the guard invariants, which nothing here may weaken), AD-7(b), AD-11 ("Where the blockers come
  from", which S2 consumes), AD-12 (all of it), the §3 failure rows marked *Install*, the §4 S4a row and S4a
  test obligations, and §8 TD-H5 and TD-H7. **The ADR governs.** Where this document had to interpret it,
  §10 says so.
- `docs/v0.7.0/REQUIREMENTS-2100-tmp-root-first-use-registration.md`: REQ-2 (install half), REQ-5,
  REQ-9, REQ-11.

**Scope (the ADR's S4a row, and nothing more):**
- `bootstrap/lib/hos_tmp_root.py`: the read-only `status` subcommand. It also needs a behaviour-preserving
  structured core under `adoption_problems` (§2.6, flagged as I-1);
- `bootstrap/hos_install.sh`: the `HOS_TMP_ROOT` upgrade write at the existing key-append site;
  register-and-verify of all four role dirs immediately before the `.hos-release` commit point; exit 77;
  the summary line;
- tests, the test-isolation refinement, and one doc paragraph (TD-H7).

**Explicitly out of scope** (do not touch these):
- `bin/hos-cron`, `bin/hos-human`, `bootstrap/lib/hos_tmp_env.sh`, `scripts/automation/lib/cycle_log.py`
  (S2);
- `_remedy()` wording (AD-4 is S2's; see I-4);
- `HOS_ONLY_RE` and `TOOL_ENTRY_NAMES` (S3);
- `bootstrap/hos_bootstrap.sh`, `CLAUDE.md`, `docs/SANDBOX-POLICY.md`, the unit-file doc rewrite (S4b);
- `scripts/framework/install.sh` (AF-10: it is the wrong site; #2059 owns its writer);
- `scripts/framework/gen_sandbox_config.py` (see E-1).

This document says *what the code must do*. It contains no application code.

---

## 0. Verification against `70ba746e1`

### 0.1 Search for existing helpers (CLAUDE.md "Search first", required)

I searched `bin/`, `bootstrap/`, `scripts/` (recursively) and `scripts/automation/lib/`.
- **Registry read-back.** I searched for a read-only registry check. I found `is_registered` (`hos_tmp_root.py:294-310`)
  and `read_registry` (`:263-291`), and no CLI exposes either. Neither is usable alone: `is_registered`
  swallows every `TmpRootError` and returns `False` (`:300-301`), and `read_registry` returns `[]` for a
  missing file (`:269-270`). Each would turn "cannot verify" into "not registered". `status` composes them
  (§2.3).
- **Blocker list.** I found `adoption_problems` (`:466-485`). It returns *formatted* strings
  (`repr(name)`, `"<repr> (it contains project files)"`, `"an unreadable listing (<exc>)"`), so it cannot give
  back raw names. See §2.6.
- **Bounded subprocess in bash.** I found the `timeout` → `gtimeout` → unbounded-with-one-warning precedent at
  `bootstrap/edit_issue_edges.sh:144-149` and `bootstrap/query_issues.sh:163-170`. §4.1 reuses the binary lookup but, per the round-1 ruling (E-4 reversed), not the unbounded fallback.
- **`config.sh` writer.** I found one non-interactive append site (`hos_install.sh:845-849`) and the
  interactive `install.sh` writer (`scripts/framework/install.sh:316-377`). §4.2 extends the former.
- **Install-time registration.** I found nothing, as ADR §0.2 also reports.

### 0.2 Findings that shape this design

- **F-1 (HIGH): The resolver's `HOS_TMP_ROOT` line grammar accepts `export` and leading whitespace. The
  installer's existing key test does not.**
  - `_LINE_RE` is `^\s*(?:export\s+)?HOS_TMP_ROOT=` (`hos_tmp_root.py:92`).
  - The append site's presence test is `grep -qE "^${_n}="` (`hos_install.sh:846`).
  - HOS's own `scripts/framework/config.sh:44` reads `export HOS_TMP_ROOT="../.tmp"`.
  - Reusing the append site's test unchanged would therefore append a second assignment. The resolver reads
    the *last* one, so that would silently **overwrite** a human's value, which AD-12 forbids. §4.2 pins a
    presence test equal to `_LINE_RE`.
- **F-2 (HIGH): The existing install suites would exhaust the 256-entry registry, and some would write into
  the real home.**
  - Full (non-dry-run) `hos_install.sh` invocations: `test_pack_install.py` 19 call sites,
    `test_install_registry_data.py` 19, `test_install_sandbox_config.py` 11, `test_requires_closure.py` 9.
    Adding this slice's own tests gives about 70 installs per session.
  - Each install registers four keys. S1's override is one file per session (`tests/conftest.py:72-81`).
    About 280 entries is more than `REGISTRY_MAX_ENTRIES = 256` (`:313`). Entries are pruned only once the
    repo dir disappears (`_live`, `:320-333`), and pytest keeps `tmp_path` for the whole session. The later
    installs in a session would therefore fail with `registry-full` → exit 77.
  - A lone test target has no sibling in `projects.conf`, so `install-default` returns
    `~/.local/state/hos/tmp/<slug>` (`:583-590`). `expand` resolves `~` against the **passwd** home
    (`:136-137`, `:149-150`), not `$HOME`. The test install would then create real dirs in the developer's
    home. Inside the Worker sandbox that write is denied, so the install would exit 77.
  - §5 fixes both, in one central place.
- **F-3 (HIGH): The install's `--human` sandbox-policy step requires `HOS_TMP_ROOT` to resolve to `<clone
  parent>/.tmp`.**
  - `gen_sandbox_config.check_tmp_root` (`scripts/framework/gen_sandbox_config.py:395-420`) refuses any
    other root ("single-clone and moved roots are not generatable").
  - The installer runs it at `hos_install.sh:1831-1839`, which is *after* the upgrade write. Its failure is
    a warning only.
  - For a **lone** `--human` clone, the value AD-12 tells S4a to write (`install-default` → the XDG path)
    therefore turns today's working sandbox generation into "Sandbox policy generation failed". Today the
    key is absent, so `../.tmp` is the effective default and generation works.
  - The interactive `install.sh` path already has this conflict today (it writes the same default at
    `install.sh:266-272`, before `:1790`). This is a pre-existing #2054 inconsistency that S4a would extend
    to non-interactive installs. **Escalated as E-1; ruled (a) with human question Q-1 (§13).**
- **F-4 (MEDIUM): In `--pr` mode the upgrade branch already exists, with the staged upgrade on it, when
  verify runs.**
  - The branch is created before any scaffolding (`:675-733`).
  - A verify failure therefore leaves the consumer on `PR_BRANCH` with uncommitted changes.
  - A plain re-run with `--pr` then fails the "working tree not clean" eligibility test (`:678`). That
    breaks AD-12's "a re-run takes the same upgrade path again" for `--pr`.
  - **Escalated as E-2; accepted with exact recovery commands (§4.7, §13).**
- **F-5 (MEDIUM): A remedy command must name a file that still exists after the install.**
  - `_remedy` and `_repoint_message` embed `os.path.abspath(__file__)` (`:352`, `:492`).
  - In release mode, `HOS_SOURCE` is a `mktemp -d` staging dir removed on `EXIT` (`:221-224`, `:411`).
  - Register and verify must therefore run the **target's** copy, `bootstrap/lib/hos_tmp_root.py`. It is
    shipped through `framework_consumer_files.txt:45` and copied at `:1923-1933`, before the manifest. The
    upgrade write runs earlier (`:845`), when a v0.6.0 target has no copy yet, so it uses `HOS_SOURCE`'s
    copy. That is safe because its output embeds no script path.
- **F-6 (LOW): `adoption_problems` lists blockers in `sorted(os.listdir(...))` order, as `str` with
  surrogateescape.** `os.fsencode` restores the raw bytes exactly. That is what makes the hex encoding in §3
  lossless.
- **F-7 (LOW): Linux `NAME_MAX` is 255 bytes.** A 10 kB **file name** cannot exist on disk. The ADR's
  "10 kB" round-trip obligation is therefore tested on the serializer, and the 255-byte maximum is tested
  on disk (I-6).

### 0.3 Line-number drift (ADR citation → `70ba746e1`)

| ADR cites | Actual | Note |
|---|---|---|
| `hos_install.sh:829-848` (key-append site) | `:828-849`. The append loop is `:845-849` (the `printf` is at `:847`); `config.sh` is created at `:841-844`; the manifest guard is `:830` | minor drift; the whole site is inside `else` of `[[ ! -f "$_manifest" ]]` |
| `hos_install.sh:2502-2511` (`.hos-release` commit point) | `:2502-2512` | matches; the closing `fi` is `:2512` |
| `hos_install.sh:1703` (#277 rule) | `:1703`, and repeated at `:2362` | matches |
| `hos_install.sh:1715-1745`, `:1717`, `:1723-1736` | `:1712-1748`; warn at `:1717`; delegation `:1722-1747` | matches |
| `install.sh:254-275` | `:254-282` | minor drift |
| `hos_tmp_root.py` `:80`, `:121-133`, `:219-231`, `:294-310`, `:488-498`, `:501-508`, `:506-507`, `:552`, `:583-590` | same | no drift |
| "`hos_install.sh` uses 0, 1, 2, 4, 5 and signal codes" | it uses 0, 1, 2, 4, 129, 130 and 143; there is no literal `exit 5` (`:1540` is a comment about a sub-tool) | immaterial: 77 is unused, so the AD-12 selection rule holds |

### 0.4 #2059 status

**Not merged.** `git log --oneline origin/main | grep -i 2059` is empty. The unmerged branch
`worker-2059-install-config-injection-261012072001-3372215` changes `hos_install.sh` *reads* only (a
`_cfg_read` helper). Its writer changes are in `scripts/framework/install.sh`. AD-12's "otherwise" branch
therefore applies. S4a extends the existing append site with a charset-gated single-value append (§4.2). It
adds no second writer and does not wait on #2059. The S4a PR body must name #2059 as the writer that later
absorbs this one, and say that #2059's `_cfg_read` would replace §4.2's `PROJECT_NAME` read when it rebases.

---

## 1. Files (≤15; one PR)

| # | File | Change | Protected |
|---|---|---|---|
| 1 | `bootstrap/lib/hos_tmp_root.py` | `status` subcommand (§2); `adoption_blockers` structured core, with `adoption_problems` re-expressed over it byte-identically (§2.6); module docstring usage and exit-code lines | **yes** (`bootstrap/**`, `protected_surfaces.txt:27`) |
| 2 | `bootstrap/hos_install.sh` | §4: bounded invoker, upgrade write, register-and-verify, exit 77, summary line, dry-run lines | **yes** |
| 3 | `tests/framework/test_hos_tmp_root.py` | `status` unit and CLI cases; `adoption_problems` parity (§8.1) | no |
| 4 | `tests/framework/test_install_tmp_root_verify.py` (new) | install-level cases (§8.2) | no |
| 5 | `tests/framework/test_tmp_root_first_writer.py` (new) | REQ-2 install sequence (§8.3) | no |
| 6 | `tests/conftest.py` | per-test registry refinement; session `HOS_INSTALL_TMP_ROOT=../.tmp` (§5) | no |
| 7 | `tests/tmp_hygiene.py` | `child_env` also carries `HOS_INSTALL_TMP_ROOT` (§5) | no |
| 8 | `tests/framework/test_registry_isolation.py` | per-test refinement cases (§8.4) | no |
| 9 | `docs/CRON-SETUP.md` | §5a: install-time registration, `status`, exit 77, and the TD-H7 privacy note (§6) | no |
| 10 | `SCRIPTS-INDEX.md` | **only if** `scripts/framework/regen_all.sh --check` reports drift | no |
| 11–14 | reserve | at most four existing install-suite harnesses, **only if** §5's central fix leaves one failing. A harness edit may only add environment; it may not weaken an assertion | no |

Total: 9 to 14. The two `bootstrap/**` files put the whole PR behind the human approval gate.
`reliability-reviewer` is **mandatory** (ADR §4 S4a row). `security-reviewer` is **mandatory** (architect
round 1, RC-9): the §2.6 refactor rewrites the body of the guard's adoption check, so AD-5 invariants 1 and
2 must be re-reviewed as a whole, not only as a diff.

---

## 2. `hos_tmp_root.py status` (AD-12 "Verify (binding)")

### 2.1 CLI (exact)

```
hos_tmp_root.py status --repo <clone> --role <worker|overseer|human|local> [--json]
```
- `--repo` and `--role` are required. `--role` uses the same `choices=sorted(ROLE_DIRS)` as `resolve`.
- `--json` adds the machine-readable record on stdout (§3). Without it, stdout is **empty**.
- A usage error is argparse's exit 2, with no JSON. Callers must treat "exit 2 and no parseable JSON" as
  "cannot verify".

### 2.2 Read-only guarantees (binding; each is pinned by a test, §8.1 S-12)

`status` must not, on any path:
- create, `mkdir`, `chmod`, rename or unlink anything;
- call `_make_dirs_0700`, `register`, `write_info_marker` or `_require_private_dir(..., tighten=True)`;
- open any file with `O_CREAT`, `O_WRONLY` or `O_RDWR`. That includes the registry's `.lock` file:
  `status` takes no flock.

`status` may only:
- read `config.sh` through `resolve_root`;
- `lstat` and `listdir` the root and the role dir;
- `lstat` and read the registry through `read_registry`;
- `lstat` the children of the role dir (through the adoption core).

It never spawns a process (module invariant, `:31`).

### 2.3 Algorithm (ordered; the first match decides)

The inputs are `repo` and `role`. `repo_real = realpath(repo)`. Each step names its `class` (§3) and exit
code.

1. **Root.** `root = resolve_root(repo)`. On `TmpRootError`: exit **2**, class `root-invalid`. `role_dir`
   is unknown.
2. `role_dir = root / ROLE_DIRS[role]`.
3. **Registry observable.**
   - `os.lstat(registry_path())` raises `FileNotFoundError`: exit **2**, class `registry-absent`. This is
     the masked-sandbox case, and also "nothing has ever been registered on this machine". Both are
     "cannot verify", never "not registered" (AD-12).
   - Any other `OSError`: exit **2**, class `registry-unreadable`.
   - Then `entries = read_registry(registry_path())`. A `TmpRootError` (not a private regular file we own,
     or malformed) gives exit **2**, class `registry-unreadable`.
4. **Root present?** If `not os.path.lexists(root)`, go to step 9 with "role dir absent". Otherwise
   `_require_private_dir(root, tighten=False)`. A `TmpRootError` gives exit **2**, class `root-invalid`.
5. **Letter case.** This is the same expression `resolve_role_dir` uses at `:525`:
   `os.path.lexists(role_dir) and ROLE_DIRS[role] not in os.listdir(root)`. If it is true: exit **2**, class
   `structural`. An `OSError` from `listdir` also gives exit 2, class `structural`. (The expression is
   repeated rather than shared; see I-2.)
6. **Role dir absent?** If `not os.path.lexists(role_dir)`, go to step 9.
7. **Role dir structure.** `_require_private_dir(role_dir, tighten=False)`. A `TmpRootError` (symlink,
   not a directory, wrong owner) gives exit **2**, class `structural`.
8. **Registered for this (repo, role)?** `info = os.lstat(role_dir)`. If
   `is_registered(role_dir, info, repo_real)`:
   - if `info.st_mode & 0o077`: exit **2**, class `structural`, reason "registered but accessible to
     group/other (mode <octal>); chmod 700 it, or let any launcher run tighten it". The line uses the
     `INVALID:` prefix. AD-12 defines exit 0 as "a private owned real dir"; see I-3;
   - otherwise: exit **0**, class `registered`.
9. **Not registered for this key.**
   - (a) **Re-point:** `_repoint_conflict(entries, repo_real, ROLE_DIRS[role], os.path.realpath(role_dir))`
     returns an entry. Exit **1**, class `repoint`, `adoptable=false`.
   - (b) **Absent:** the role dir does not exist (from step 4 or 6). Exit **1**, class `absent`,
     `adoptable=true`.
   - (c) **Registered for another repo:** `is_registered(role_dir, info)` with no repo. Exit **1**, class
     `unregistered-adoptable`, `adoptable=true`, `blockers=[]`. This mirrors `:544-547`: `resolve --create`
     would add this key without running the adoption checks.
   - (d) Otherwise, `bl = adoption_blockers(role_dir)` (§2.6):
     - if `bl` is empty: exit **1**, class `unregistered-adoptable`, `adoptable=true`;
     - otherwise: exit **1**, class `unregistered-blocked`, `adoptable=false`, `blockers=bl`, **all of
       them**.
10. Any other exception escaping steps 1 to 9 (`OSError`, `TmpRootError`): exit **2**, class `error`.
    `status` never returns 3, and never lets a traceback escape `main`.

Step 9's order matches `resolve_role_dir`, which checks a re-point first (`:510-520`). An absent dir under a
re-point conflict is therefore `repoint`, not `absent`. That is correct, because `resolve --create` would
refuse it.

`is_registered` re-reads the registry, so `status` reads it twice. The window between the two reads only
matters if registration happens in between, and the result then still reflects a real registry state.
`register` writes atomically with a rename (`:439`), so `status` can never see a torn file.

### 2.4 Human output (stderr; exactly one line, always)

The prefix is `hos_tmp_root: status <role>: `, matching the existing `hos_tmp_root: ` prefix at `:663`. The
line is single so that callers that keep only the last stderr line still get all of it.

| class | Line after the prefix |
|---|---|
| `registered` | `OK: <role_dir> is registered for <repo_real>` |
| `absent` | `NOT REGISTERED: <role_dir> does not exist yet; the next resolve --create (installer or launcher) creates and registers it` |
| `unregistered-adoptable` | `NOT REGISTERED: <role_dir> holds only HOS-owned entries or is registered for another clone; the next resolve --create adopts and registers it` |
| `unregistered-blocked` | `NOT REGISTERED: ` + `_remedy(role_dir, role, repo, <formatted blockers>)`. The existing text is reused; it shows the first five plus a count (AD-4's wording is S2's, I-4) |
| `repoint` | `NOT REGISTERED: ` + `_repoint_message(conflict, str(role_dir), repo, role)` (existing text) |
| `registry-absent` / `registry-unreadable` | `CANNOT VERIFY: <reason>. If this runs inside a Claude session or any sandbox, re-run it unsandboxed, in your own terminal (the sandbox hides the trust registry)` |
| `root-invalid` / `structural` / `error`, including I-3's registered-but-loose-mode case | `INVALID: <the TmpRootError/OSError text>. Fix the path or value named on this line` |

**The three prefixes are a closed set, and they mean different things (RC-2):**
- `NOT REGISTERED:` is exit 1. The remedy is `mv` or `mark`.
- `CANNOT VERIFY:` is **only** the two registry classes. The remedy is to re-run unsandboxed.
- `INVALID:` is every other exit-2 class. The remedy is to fix the named path or value. A re-run without a
  sandbox would not help, so this line never says to do that.

The installer (§4.4) selects its remedy text by these prefixes, so they are part of the contract.

### 2.5 Exit codes (binding)

| Exit | Meaning | Classes |
|---|---|---|
| 0 | exists, private, owned, real dir, registered for this (repo, role) at its live inode | `registered` |
| 1 | not registered for this key; reporting only, grants nothing | `absent`, `unregistered-adoptable`, `unregistered-blocked`, `repoint` |
| 2 | structural, root invalid, or the registry cannot be read (masked, absent, malformed); also a usage error | `structural`, `root-invalid`, `registry-absent`, `registry-unreadable`, `error` |

`main` dispatches `status` before the existing `try` that maps errors to `EXIT_INVALID` (3), so that mapping
can never apply to `status`. The module docstring's "Exit codes" paragraph gains the line
`status: 0 registered; 1 not registered; 2 cannot verify (structural, root invalid, registry masked or unreadable, usage)`.

### 2.6 `adoption_blockers`: the structured core (behaviour-preserving refactor; I-1)

`status` needs the raw blocker names, and `adoption_problems` only returns formatted strings (§0.1). A second
copy of the predicate in `status` would be the "second decision path" that FU-1 warns about, and it would
drift as soon as S3 adds `TOOL_ENTRY_NAMES`. Instead:
- **New** `adoption_blockers(role_dir) -> list[Blocker]`. `Blocker` is an immutable record of
  `kind: str`, `name: str` (surrogateescape `str` from `os.listdir`, or `""`) and `detail: str`.
  - `kind="name"`: the name fails the allowlist.
  - `kind="project-files"`: an allowlisted dir that directly holds `.git`, `.claude` or `scripts`.
  - `kind="unreadable-listing"`: `name=""`, `detail=str(exc)`.
  - The iteration order, the `lstat` failure skip (`:479-480`) and the rules are **exactly**
    `adoption_problems`' current body.
- **`adoption_problems(role_dir)`** becomes `[_format_blocker(b) for b in adoption_blockers(role_dir)]`,
  where `_format_blocker` produces exactly:
  - `repr(name)`;
  - `f"{name!r} (it contains project files)"`;
  - `f"an unreadable listing ({detail})"`.

  Its output must be **byte-identical** to today's for every input. `resolve_role_dir` keeps calling
  `adoption_problems` at the same point (`:540`), so AD-5's ordering (invariant 7) is unchanged.
- **S3 coordination.** S3's `TOOL_ENTRY_NAMES` rule (directory-only, invariant 2) is added inside
  `adoption_blockers`. A tool name that is a symlink or a file becomes a new kind, for example
  `kind="not-a-directory"`, that S3 defines. The S4a PR body states this hand-off.

---

## 3. TD-H5: the machine-readable blocker format, and how S2 consumes it

### 3.1 Choice: one JSON object per line, ASCII-only, with every byte-bearing field hex-encoded

With `--json`, `status` prints **exactly one line** to stdout, for exit 0, 1 and 2 alike. It is
`json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))` followed by `\n`:

| Key | Type | Value |
|---|---|---|
| `v` | int | `1` (schema version) |
| `role` | str | the `--role` value |
| `exit` | int | the process exit code (0, 1 or 2) |
| `class` | str | one of the §2.5 classes |
| `adoptable` | bool or null | `true`/`false` for exit 1; `null` for 0 and 2 |
| `role_dir_hex` | str or null | lowercase hex of `os.fsencode(str(role_dir))`; `null` when step 1 failed |
| `blocker_count` | int | `len(blockers)` |
| `blockers` | list | **all** blockers, in `adoption_blockers` order: `{"kind": <kind>, "name_hex": <lowercase hex of os.fsencode(name)>}`. `name_hex` is `""` for `unreadable-listing`. Empty for every class except `unregistered-blocked` |

No reason text, and no path except as hex, goes into the JSON. The reason is on stderr (§2.4).

**Why this format and not the others** (TD-H5 requires one justified choice):
- **Byte-safe by construction.** Hex has no escaping rules to get wrong. Newlines, control bytes, a NUL in
  a constructed serializer input, and invalid UTF-8 all round-trip through `bytes.fromhex`, byte for byte.
- **Rejected: JSON with surrogate escapes** (`ensure_ascii=True` over surrogateescape `str` yields
  `\udcff`). It round-trips only through Python's lone-surrogate handling. `jq` and most other JSON
  consumers map lone surrogates to U+FFFD, which is lossy. The fingerprint (AD-11) needs the raw bytes.
- **Rejected: a NUL-separated stream.** It carries names, but not `class`, `exit`, `adoptable` or `kind`,
  without inventing a second record convention. NUL-delimited output is also awkward to parse safely
  under bash `set -u`.
- One line of ASCII survives any pipe, log or `$(…)` capture intact. Its size is bounded only by the
  listing. A 255-byte name costs 510 hex characters.
- `status` never truncates. "All blockers" is binding (TD-H5). Capping is the consumer's job (§3.2).

### 3.2 How S2 consumes it (binding on S2's TD; restated here so S2 has no ambiguity)

- **Call.** S2's alert step calls `python3 -I <clone>/bootstrap/lib/hos_tmp_root.py status --repo <clone>
  --role <role> --json` under its own per-call timeout. That budget is set by S2's TD-H1, within the 120 s
  alert-step cap.
- **Parse.**
  - Read all of stdout, up to a cap S2 chooses (4 MiB is recommended).
  - If stdout is empty, over the cap, not valid JSON, `v != 1`, or missing a required key, the blockers are
    `unknown` (AD-2's value). The refusal still proceeds.
  - The exit code is informational only. S2 never treats `status` exit 0 at alert time as "no refusal": the
    refusal was decided by the export helper.
- **Use.**
  - The raw blocker bytes are `bytes.fromhex(b["name_hex"])` for each entry.
  - The AD-11 **fingerprint** uses all of them (sorted bytewise, NUL-separated, together with
    `refusal_class` and `role_dir`). `role_dir`'s bytes may come from `role_dir_hex`.
  - The AD-11 **blocker renderer** receives the same raw bytes. It renders at most five, plus
    `(+<blocker_count - 5> more)`.
  - For classes other than `unregistered-blocked`, AD-2's `blockers=unknown` applies, and `reason` comes
    from `HOS_TMP_REASON`, never from `status`.
- **No re-parsing.** S2 never parses blocker names out of the stderr line or the one-line `reason` (AD-11).

---

## 4. `bootstrap/hos_install.sh`

### 4.1 The bounded invoker (used by every resolver call S4a adds)

- **A timeout binary is a prerequisite (RC-3; E-4 reversed: fail closed).** The prerequisite check
  (`hos_install.sh:552-577`) gains one more check, placed with the others and evaluated before
  `PREREQ_OK` is tested:
  - if `timeout` exists, it is `ok "timeout present"`;
  - otherwise, if `gtimeout` exists, it is `ok "gtimeout present (coreutils)"`;
  - otherwise it is `err "timeout (coreutils) missing — needed to bound temp-dir registration"`, and
    `PREREQ_OK=false`.

  The existing block then exits **1**, before any write and before the PR branch. It points to
  `hos_bootstrap.sh`, which already installs coreutils (`hos_bootstrap.sh:267-281`). That covers a real
  install and a `--pr` install alike.
- **Dry run without a timeout binary.** A `--dry-run` must not stop on a missing prerequisite it never
  needs. When neither binary exists under `--dry-run`, the check prints
  `warn "timeout (coreutils) missing — a real install would stop here (exit 1); run hos_bootstrap.sh"`
  instead of `err`. It does not set `PREREQ_OK=false`. The §4.2 preview calls (`install-default`,
  `validate`) are then **skipped**, with
  `dry_run "Would compute and check HOS_TMP_ROOT (skipped: no timeout binary)"`, so the dry run still makes
  no unbounded call.
- **Timeout prefix.** It is computed once, right after the prerequisite check:
  - `(timeout --kill-after=5s <T>s)`;
  - or `(gtimeout --kill-after=5s <T>s)`.

  **There is no empty-prefix path.** The invoker refuses to run if the prefix array is empty: it is
  unreachable after the prerequisite check, but a defensive `err` and the 77 path cover it.
  §8.2 I-15 pins that no code path calls the helper without the prefix.
- **`<T>`** is `30`. The environment variable `HOS_INSTALL_TMP_VERIFY_TIMEOUT` may only **lower** it: an
  integer from 1 to 30 is used; anything else (absent, non-integer, 0, above 30) gives 30. This exists so the
  hang test does not take 35 s. It mirrors `HOS_TEST_TMP_BUDGET_MB`'s "lowerable, never raisable" rule. A
  static test pins the default of 30 and the kill-after of 5 (§8.2 I-15).
- **Invocation and capture (RC-8, exact).** The helper is run as
  `"${_prefix[@]}" python3 -I "$helper" <args…>`, with `python3` looked up on `PATH` like the rest of the
  installer. There are two capture forms, and no other:
  - **Diagnostic calls** (`resolve --create`, `status`, `validate`) capture **stderr only**, with stdout
    discarded:

    `_rc=0; _err="$("${_prefix[@]}" python3 -I "$helper" <args…> 2>&1 >/dev/null)" || _rc=$?`

    The redirection order is deliberate. `2>&1` points stderr at the substitution, then `>/dev/null`
    discards stdout. `resolve`'s printed path is therefore never read. The install reports the root from
    `status`'s `OK:` line instead (§4.3).
  - **The value call** (`install-default`) captures **stdout only**, with stderr discarded:

    `_rc=0; _val="$("${_prefix[@]}" python3 -I "$helper" install-default … 2>/dev/null)" || _rc=$?`

    On failure the cause is reported as `install-default exited <rc>`.
  - No temp file is written, so nothing lands in `TMPDIR`. `TMPDIR` may itself be a role dir if the
    installer is run from a `hos-human` shell.
  - `_err` keeps only its **last** line (`${_err##*$'\n'}`), which matches the resolver's one-line
    convention.
  - Return code **124** or **137** means "timed out" (TERM, then KILL after 5 s).

### 4.2 The `HOS_TMP_ROOT` upgrade write (AD-12 "Upgrade write"; REQ-11)

- **Site.** Directly after the placeholder append loop (`:845-849`), and **outside** the
  `[[ ! -f "$_manifest" ]]` conditional (`:830`), so it runs even when a source lacks
  `placeholders.manifest`. It is one function, called once.
- **One writer (AD-12, pre-#2059).** The append idiom at `:847` is turned into one helper,
  `_config_append_kv <name> <value>`. Both the existing empty-key loop and this write call it. It:
  - creates `config.sh` with the existing header line (`:843`) if the file is absent;
  - adds a `\n` first if the file's last byte is not a newline (the `ensure_line` guard at `:648`). This
    also fixes a latent bug in the empty-key loop, which today can glue a key onto an unterminated last
    line;
  - appends `<name>="<value>"\n`, which is byte-identical to today's `printf '%s=""\n'` when the value is
    empty.

  No other `>> "$_subst_config"` may be added by S4a. A static test pins that the only appends to
  `_subst_config` in the file are the helper's and the pre-existing `PACK` lines (`:1340-1350`), which are
  outside this slice.
- **Presence test (F-1).** The key is present if
  `grep -qE '^[[:space:]]*(export[[:space:]]+)?HOS_TMP_ROOT=' "$_subst_config"` matches. This is
  `_LINE_RE`'s grammar.
  - grep's rc 0 means present: no write, and `skip "config.sh: HOS_TMP_ROOT already set — left unchanged"`.
    This covers `HOS_TMP_ROOT=""`, which keeps the resolver's `../.tmp` default (`:133`). "An existing
    value … is never overwritten" (AD-12) includes an empty one.
  - rc 1 means absent.
  - rc ≥2 (unreadable file) goes to the **77 path** with "cannot read `<config.sh>`".
  - A missing `config.sh` counts as absent.
- **The value.**
  - If `HOS_INSTALL_TMP_ROOT` is set and non-empty, its value is used. This is an operator override, and
    the test isolation in §5 uses it. It is otherwise just "the human typed it", and it passes exactly the
    same gates. See E-3.
  - **Containment (RC-6).** `bootstrap/hos_install.sh` is the only non-test file that reads or names
    `HOS_INSTALL_TMP_ROOT`. The only other non-test file that names it is `docs/CRON-SETUP.md`. §8.2 I-18
    pins this. #2137's upgrade case must **not** set it, because #2137 has to exercise the real
    `install-default` (§9.1).
  - Otherwise, the value is the stdout of `<HOS_SOURCE>/bootstrap/lib/hos_tmp_root.py install-default
    --target "$TARGET_REPO" --project-name "<name>"` (F-5: the source copy, because a v0.6.0 target has
    none yet).
  - `<name>` is the environment variable `PROJECT_NAME` if set, otherwise the first `^PROJECT_NAME=` value
    in `config.sh`, read and stripped of quotes with the idiom at `:858`, otherwise `""`. `install-default`
    maps `""` to `project`.
  - `--projects-conf` is not passed. The resolver's own default, `$HOME/.config/hos/projects.conf`, applies.
  - The installer never computes a default itself (AD-12).
- **Gates.** Both must pass, in this order:
  1. the value matches `^[A-Za-z0-9._/~-]+$` (bash `=~`; this is AD-12's set, deliberately without the `+`
     that `ALLOWED_VALUE_RE` and `install.sh:365` allow);
  2. `hos_tmp_root.py validate --repo "$TARGET_REPO" --value "<v>"` exits 0, through §4.1.
- **On any failure** (the helper is missing from `HOS_SOURCE`; `install-default` or `validate` is non-zero
  or timed out; empty output; the charset gate fails), nothing is written. The install goes to the **77
  path** (§4.4) with refused roles `worker,overseer,human,local` and this message:

  > `HOS_TMP_ROOT could not be written to config.sh: <cause>. Set HOS_TMP_ROOT in <config.sh> by hand, then re-run.`

  `<cause>` is the gate that failed and, for `validate`, its stderr line.
- **On success:** `_config_append_kv HOS_TMP_ROOT "<v>"`, then
  `ok "config.sh: added HOS_TMP_ROOT=\"<v>\" <source>"`. `<source>` is exactly
  `(from HOS_INSTALL_TMP_ROOT)` or `(resolver install-default)` (RC-6). The dry-run line in §4.5 carries the
  same suffix. The value is also added to `_appended`, so the warning at `:1717` lists it.
- **Interactive path.** When `install.sh` is later delegated to (`:1735-1742`), it reads this line as
  `EXISTING_HOS_TMP_ROOT` (`install.sh:148`), offers "Enter to keep", rewrites `config.sh` whole and writes
  one `HOS_TMP_ROOT=` line (`install.sh:362-377`). The final file still holds exactly one assignment, and
  register-and-verify reads the final file. See I-5.

### 4.3 Register-and-verify (AD-7(b), AD-12)

- **Site.** One function, called once. It sits between the end of the `.hos-manifest` block (`:2500`) and
  the `.hos-release` block (`:2502`). That puts it after the agents and the manifest are written, and before
  the stamp and the install-via-PR block (`:2515`).
- **Helper.** `"$TARGET_REPO/bootstrap/lib/hos_tmp_root.py"` (F-5). If it is not a regular file (for
  example, the copy at `:1927` failed and `fail()` only counted it), all four roles are refused, with the
  reason `bootstrap/lib/hos_tmp_root.py is missing from the target (see the copy errors above)`, and the
  install takes the 77 path.
- **Roles.** Always all four, in this fixed order: `worker overseer human local`. The `--worker`,
  `--overseer` and `--human` flags do not change the set (AD-7(b) "Why all four from one clone").
- **Registry-override notice (RC-7).** If `HOS_TMP_REGISTRY_FILE` is set and non-empty in the installer's
  environment, one line is printed before the register step:

  > `warn "HOS_TMP_REGISTRY_FILE is set (<path>): registration and verify use that file, NOT the real trust registry (~/.local/state/hos/tmp-roots.json); the reaper will not see these registrations."`

  The run continues. The override is the resolver's test hook, and the installer neither blocks it nor
  hides it.
- **Register.** For each role: `resolve --repo "$TARGET_REPO" --role <r> --create`, through §4.1's
  diagnostic form (stderr only).
  - The outcome is recorded but **does not decide** the verdict, except that a **timeout** marks that role
    refused ("resolve --create did not answer within <T> s; killed").
  - **A non-zero, non-timeout exit keeps its stderr line (RC-1).** That line is **printed in the refusal
    report** (§4.4), directly before the role's `status` line. That way a `status` line such as "the next
    resolve --create creates and registers it" is never the only explanation when `resolve --create` has
    just failed. Examples are `registry-full`, a disk-full write, and a lock failure.
- **Verify.** After all four registers, for each role: `status --repo "$TARGET_REPO" --role <r>` (no
  `--json`), through §4.1's diagnostic form (stderr only).
  - A role passes **only** on exit 0.
  - Exit 1 or 2, any other exit code, or a timeout marks it refused.
  - The status stderr line is kept for the report.
  - `status` runs even for a role whose register timed out, so the human gets its diagnosis. If `status`
    also times out, the reason is the timeout.
- **Forbidden.** No `mark` subcommand, no `--reviewed`, and no `force_mark` anywhere in `hos_install.sh`.
  That includes comments and message strings: the literal `--reviewed` must not appear in the file
  (AD-5/AD-7, §8.2 I-14). The `mark` command the human needs comes from the resolver's own message.
- **Verdict.**
  - If no role is refused, the summary line (§4.4) is `refused=none`, followed by
    `ok "Role temp dirs registered and verified under <root>"`, and the install proceeds to stamp.
  - **Where `<root>` comes from (RC-8).** It comes from the **Worker `status` `OK:` line**, never from
    `resolve`'s stdout, which is discarded:
    1. strip the fixed prefix `hos_tmp_root: status worker: OK: `;
    2. cut at the first ` is registered for ` (`${x%% is registered for *}`);
    3. take the `dirname`.

    The value is display-only. If parsing yields an empty string, the line prints `under HOS_TMP_ROOT`
    instead. It never fails the install.
  - Otherwise, the 77 path.

### 4.4 Output contract and the 77 path

- **Summary line (exactly one per run that reaches §4.2's failure or §4.3).** It goes to **stdout**, with
  no colour codes and no indentation:

  ```
  tmp-root-verify: refused=<none | comma-separated roles in the order worker,overseer,human,local>
  ```

  It must match `^tmp-root-verify: refused=(none|(worker|overseer|human|local)(,(worker|overseer|human|local))*)$`.
  One function prints it, and both sites call that function. A run that exits before §4.2 or §4.3 (for
  example a prerequisite failure (exit 1) or a drift hard-stop (exit 4)) prints no line. A dry run prints
  the `skipped` form (§4.5).
- **The 77 path.** One function, which holds the file's **only** `exit 77` (a static test pins exactly one
  occurrence, the same selection rule as AD-11 step 4). It prints, in this order:
  1. For each refused role, on stdout:
     - `err "Temp dir refused: <role> (<RoleDir>)"`;
     - then, **if that role's `resolve --create` exited non-zero for a reason other than a timeout
       (RC-1)**, its kept stderr line, indented four spaces and labelled `register: `;
     - then the role's kept `status` stderr line (or the timeout or helper-missing reason), indented four
       spaces and labelled `verify: `.

     These lines are printed as-is (local terminal only). The `status` line already carries the `NOT
     REGISTERED:`, `CANNOT VERIFY:` or `INVALID:` prefix (§2.4). It already names the role dir, the blockers
     (the first five and a count, as `repr` text, so control bytes are escaped) and, for adoption and
     re-point refusals, the exact `mark` command.
  2. Once, the installer-owned remedy block (I-4). **Its bullets are selected by the prefixes that actually
     appeared (RC-2):**
     - **Only if some role printed `NOT REGISTERED:`:**

       > `Remedy for a NOT REGISTERED dir — run it unsandboxed, in your own terminal (not inside a Claude session; it needs the trust registry):`
       > `  • move each blocking entry out of the role dir:  mv '<role_dir>/<entry>' <a dir outside HOS_TMP_ROOT>/`
       > `  • or, after reviewing the dir yourself, run the mark command printed above for that role.`
     - **Only if some role printed `CANNOT VERIFY:`:**

       > `CANNOT VERIFY: the trust registry could not be read. Re-run this installer unsandboxed, in your own terminal (not inside a Claude session).`
     - **Only if some role printed `INVALID:`:**

       > `INVALID: fix the path or value named on that line (HOS_TMP_ROOT in <config.sh>, or the role dir itself).`
     - **Only if a role timed out, or the helper was missing:** its reason line, already printed in step 1,
       is enough. No extra bullet is printed.
     - **Always:**

       > `Then re-run this installer with the same arguments. Re-running is safe (idempotent).`
       > `The install is NOT complete: .hos-release is unchanged (<INSTALLED_TAG or "none">) and no install PR was opened.`

     The words "unsandboxed, in your own terminal" therefore appear only beside `NOT REGISTERED` (the
     `mark`/`mv` remedy needs the registry) and `CANNOT VERIFY`, never as the remedy for `INVALID`.
     `<entry>` and `<a dir outside HOS_TMP_ROOT>` are literal placeholders, never filled-in names (the same
     rule as AD-11's renderer). `INSTALLED_TAG` is the variable already set at `:451-452`.
     For the §4.2 failure path, step 1 is replaced by the §4.2 message, and no bullet but "Always" is
     printed.
  3. If `PR_ACTIVE` is set, the §4.7 lines.
  4. The summary line.
  5. `exit 77`.

  The `EXIT` trap (`cleanup`, `:223-224`) still runs, as for every other exit.

### 4.5 `--dry-run` (AD-12; AD-7(b) "the dry-run output says that they would run")

- **§4.2.** The presence test, the value computation and both gates run, because they are read-only.
  - If they succeed: `dry_run "Would append HOS_TMP_ROOT=\"<v>\" to config.sh <source>"`, with §4.2's
    `<source>` suffix.
  - If no timeout binary exists, the calls are skipped (§4.1), and only the presence test runs.
  - If any of them fails: `warn "Would FAIL the install (exit 77): <message>"`, and the dry run continues.
    A preview never exits 77.
  - If the key is present: the same `skip` line as §4.2.
- **§4.3.** No resolver call at all. The output is
  `dry_run "Would register and verify the role temp dirs worker, overseer, human, local under HOS_TMP_ROOT (skipped in a dry run)"`,
  then exactly one stdout line, `tmp-root-verify: skipped=dry-run`. See I-6 for why it is not
  `refused=none`.
- A dry run creates no root, no role dir, no registry file, no `.lock` file and no `config.sh` change
  (§8.2 I-12).

### 4.6 `--local` and release installs

The flow is identical in both modes. Only `HOS_SOURCE` differs: the working copy (`:219`) or the staged
release (`:411`).
- §4.2 runs `HOS_SOURCE`'s helper.
- §4.3 always runs the target's helper.

For a self-install of the HOS repo into its own clone, the two copies are the same file. Nothing in S4a
reads `HOS_REF`, except that the 77 message reports `INSTALLED_TAG`.

### 4.7 `--pr` mode (F-4; E-2 accepted, with the exact recovery commands of RC-4)

When the 77 path runs with `PR_ACTIVE=true`:
- there is no commit, no push and no `gh pr create`. The verify runs before `:2515`, so this follows from
  the placement;
- the installer does **not** check out `PR_ORIG_BRANCH`. #993's reason applies: the staged changes would
  follow onto the base branch;
- the installer runs no git command of its own on this path;
- it prints exactly the following, with `<target>`, `<tag>`, `<PR_BRANCH>` and `<PR_ORIG_BRANCH>` filled in.
  `<target>` and the branch names are printed shell-quoted with `printf %q`:

  > `The upgrade is staged, uncommitted, on branch '<PR_BRANCH>' (you are on it). No PR was opened.`
  > `The temp-dir remedy above (mv or mark) is machine-local: it changes the role dir or the trust registry, not this repository, so it works from any branch.`
  > `To return to '<PR_ORIG_BRANCH>' and retry the PR install after the remedy, run:`
  > `  git -C <target> stash push --include-untracked -m "hos-upgrade <tag>"`
  > `  git -C <target> checkout <PR_ORIG_BRANCH>`
  > `  git -C <target> branch -D <PR_BRANCH>`
  > `then re-run this installer with --pr. (The stash keeps the staged upgrade recoverable; drop it with 'git stash drop' once the new PR exists.)`

  `<tag>` is `HOS_REF`. The text must **never** suggest `git clean`, `git reset --hard` or
  `git checkout -- .`. §8.2 I-2b pins both rules.

### 4.8 Idempotency (AD-12 "re-running after the remedy is safe")

A second run with an unchanged state must:
- leave `config.sh` byte-identical (the key is present, so nothing is written);
- leave the registry's entry set unchanged. `resolve --create` on a registered dir only re-writes a missing
  marker and tightens the mode (`:548-552`). For an entry registered to another repo, it adds that repo's
  own key once (`:544-547`);
- exit 0 with `refused=none`.

A re-run after a remedy behaves as follows:
- after `mv`, the dir becomes adoptable and is adopted by §4.3's register step;
- after `mark --reviewed`, the dir is registered and is accepted.

Either way the install exits 0 and stamps.

---

## 5. Test isolation (F-2; refines AD-10; see E-3)

The changes are made only in `tests/conftest.py` and `tests/tmp_hygiene.py`. S1's guard and its
session-start fingerprint are unchanged.

- **`pytest_configure` (S1's hook).** After setting `HOS_TMP_REGISTRY_FILE` as today:
  - it records the session-owned default path in a module global, `_SESSION_REGISTRY`;
  - it **always** sets `os.environ["HOS_INSTALL_TMP_ROOT"] = "../.tmp"`, overwriting any inherited value
    (RC-5). An absolute value inherited from a developer's shell or CI must never steer test installs. This
    is unlike the registry override, where a caller-set value is respected.

  `../.tmp` resolves against each target's realpath, to `<target's parent>/.tmp`. Every existing harness
  creates its target inside its own `tmp_path`, so this:
  - keeps every test install inside its own `tmp_path`, never in the passwd home;
  - matches the effective default those tests ran under before S4a (the key was absent, so the resolver
    used `../.tmp`);
  - satisfies `gen_sandbox_config`'s D15 rule, so the `--human` happy-path test keeps passing.
- **New function-scoped autouse fixture** (for example `_hos_per_test_registry`). If
  `os.environ[REGISTRY_ENV] == _SESSION_REGISTRY`, it uses `monkeypatch.setenv` to set it to
  `<basetemp>/hos-registry/t-<first 16 hex of sha256(request.node.nodeid)>.json`.
  - `<basetemp>` is `tmp_path_factory.getbasetemp()`, a public API.
  - It does not create the file or its directory; `register` creates them on demand (`:377`).
  - A caller-set override is left alone (S1's rule). So is a test's own `monkeypatch.setenv`, which runs
    after this fixture.
  - Each test therefore has its own registry, so the 256 cap is reached per test, never per session.
  - **Fixture scope (RC-10).** Module- and session-scoped fixtures run **before** this function-scoped
    autouse fixture, so they use the **session** registry. For example, `test_install_registry_data.py`
    has four module-scoped fixtures (`:117-139`), each installing into its own `tmp_path_factory` target.
    That is intended, and it is bounded: 4 targets × 4 keys = **16 entries**, far below 256. A second
    install into the same target, as in `django_then_astro`, replaces that repo's keys and adds none. Any future module- or session-scoped install fixture
    adds to the same session file. The coder must keep the session total far below the cap; the bound is
    stated in a conftest comment beside the fixture.
- **`child_env` (`tests/tmp_hygiene.py:89-107`).** The carried set becomes
  `("TMPDIR", "HOS_TMP_REGISTRY_FILE", "HOS_INSTALL_TMP_ROOT")`, under the same "never override a value the
  caller set" rule.
- **What still uses the real `install-default`.** The tests that exercise it (§8.2 I-8, I-8b, I-9) `pop`
  `HOS_INSTALL_TMP_ROOT` from the env they build. They supply a fake `HOME` holding a `projects.conf` that
  makes the target multi-clone, so the computed value is `../.tmp`, inside `tmp_path`. The lone-clone value
  is exercised only under `--dry-run` (I-8b), because writing it would touch the passwd home.

---

## 6. Docs: `docs/CRON-SETUP.md` §5a "Where HOS temp lives" (TD-H7)

S4a touches no other install doc, so per TD-H7 the note goes here. Add one paragraph after the existing
bullet at `:421`. S3 and S4b also edit this file, in other paragraphs; whichever lands later rebases. The
paragraph must state:
- the installer (`bootstrap/hos_install.sh`) creates and registers all four role dirs, then verifies them
  with the read-only `python3 bootstrap/lib/hos_tmp_root.py status --repo <clone> --role <role>`. Exit 0
  means registered, 1 `NOT REGISTERED`, and 2 either `CANNOT VERIFY` (re-run unsandboxed) or `INVALID` (fix
  the named path or value);
- the installer now **requires `timeout`** (or `gtimeout` from coreutils on macOS). Without one, it stops
  with exit 1 before writing anything; `hos_bootstrap.sh` installs it (RC-3);
- any refusal fails the install with **exit 77**, before `.hos-release` is stamped and before any install
  PR. The output names the blockers and the remedy, and a re-run after the remedy is safe. The
  machine-readable line is `tmp-root-verify: refused=<roles|none>`;
- on an upgrade from a release whose `config.sh` lacks `HOS_TMP_ROOT`, the installer writes the
  resolver's default once, and never changes an existing value. `HOS_INSTALL_TMP_ROOT=<value>` supplies a
  different value for a non-interactive install, under the same checks;
- **(TD-H7, privacy):** *"Paths under your home directory are written as `~/…` in the audit trail and in
  any alert issue. If the clone or `HOS_TMP_ROOT` is **outside** `$HOME` (for example under `/srv`), its
  absolute path cannot be shortened, and it **will** appear as-is in the committed audit trail
  (`audit/`) and in alert issues filed in the project's GitHub repo. Keep both under `$HOME` if those
  paths are sensitive."*

---

## 7. Failure modes of the new install steps (`reliability-reviewer`: mandatory)

| # | Failure | Behaviour | Direction | Test |
|---|---|---|---|---|
| FM-1 | A role dir holds a non-allowlisted entry | `status` exit 1 `unregistered-blocked`; the role is refused; the blockers and remedy are printed; exit 77; no stamp, no PR | fatal, loud | I-2 |
| FM-2 | Re-point (the key is registered at another live path) | `status` exit 1 `repoint`; the `_repoint_message` line names the `mark` command; exit 77 | fatal, loud | S-7, I-2c |
| FM-3 | Registry absent or masked (the installer was run sandboxed) | `status` exit 2 `registry-absent`; "CANNOT VERIFY … re-run unsandboxed"; exit 77. Never a pass | fatal, loud | S-11, I-3b |
| FM-4 | Registry unreadable, malformed, loose mode or not a regular file | `register` refuses (exit 3, kept for diagnostics); `status` exit 2 `registry-unreadable`; exit 77 | fatal, loud | S-11, I-3 |
| FM-5 | A resolver call hangs (NFS stall, a held registry flock) | Killed at `<T>` s, plus 5 s for KILL; that role is refused with the timeout reason; the other roles still run; exit 77. The worst-case total is 8 × 35 s = 280 s | fatal, bounded | I-5 |
| FM-6 | No `timeout` or `gtimeout` binary | **Fail-closed prerequisite (RC-3).** The prerequisite check exits **1** before any write or PR branch, pointing to `hos_bootstrap.sh`. A `--dry-run` warns that a real install would stop there, and skips its resolver calls. There is no unbounded call path | fatal, loud, before any write | I-15 (static), I-17 |
| FM-7 | `registry-full` (256 live keys) | `register` exits 3 with its `registry-full` remedy. That line is **printed** as `register:` (RC-1), so `status`'s `NOT REGISTERED` "next resolve --create creates it" line is never the only explanation. Exit 77 | fatal, loud | I-16 |
| FM-8 | The target helper is missing (the copy failed) | All four roles refused, with the missing-helper reason; exit 77 | fatal, loud | I-14 |
| FM-9 | `python3` crashes (a traceback) in `resolve` or `status` | `status` maps every exception to exit 2 inside `main` (§2.3 step 10). An interpreter-level crash is a non-zero exit, so the role is refused | fatal, loud | S-13 |
| FM-10 | `install-default` or `validate` fails, times out, or yields a value outside the charset | Nothing is written; exit 77 with "Set HOS_TMP_ROOT … by hand, then re-run"; `refused=worker,overseer,human,local` | fatal, loud | I-11 |
| FM-11 | `config.sh` cannot be read for the presence test | exit 77, "cannot read `<config.sh>`" | fatal, loud | I-11c |
| FM-12 | An existing `HOS_TMP_ROOT` is invalid (an unterminated quote, inside the clone, inside a work tree) | No write (never overwrite); `status` exit 2 `root-invalid` with the `INVALID:` prefix; the INVALID bullet (fix the named value); exit 77 | fatal, loud | I-10c | an existing invalid value (`HOS_TMP_ROOT="./inside"`) | not rewritten; rc 77; the resolver's "inside the clone" reason is in an `INVALID:` line; the INVALID bullet is printed; neither the `mv`/`mark` bullets nor any "unsandboxed" text appears (RC-2) |
| FM-13 | Verify fails in `--pr` mode | No commit, push or PR; the consumer stays on `PR_BRANCH`, with the recovery text (§4.7) | fatal, loud; recovery is manual (E-2) | I-2b | as I-2, with `--pr`: a bare `file://` origin and a `gh` stub on `PATH` that logs its argv | rc 77; the `gh` log has no `pr create`; `git ls-remote origin` has no `hos-upgrade/*` branch; the checked-out branch is `PR_BRANCH`; the output contains, verbatim (with the values filled in), the three lines `git -C <target> stash push --include-untracked -m "hos-upgrade <tag>"`, `git -C <target> checkout <PR_ORIG_BRANCH>` and `git -C <target> branch -D <PR_BRANCH>`, plus the sentence that the remedy is machine-local; the output contains none of `git clean`, `reset --hard` or `checkout -- .`. **Then** executing exactly those three printed commands, the remedy (`mv`), and a `--pr` re-run gives rc 0 and opens a PR (the `gh` log has one `pr create`) |
| FM-14 | Lone `--human` clone: the written XDG root fails `gen_sandbox_config`'s D15 rule | **Ruled E-1 (a): build the ADR-literal value in S4a.** The sandbox step warns (the existing non-fatal path, `:1838`); register and verify still pass; exit 0. The fresh-install layout default is the human question **Q-1**, which gates the v0.7.0 cut, not S4a's merge (§13). Disclosed in the PR body (§9.1) | degraded, loud warning; known and ruled | none in S4a (the behaviour is the ADR's) |
| FM-15 | The installer is interrupted (HUP, INT or TERM) during register or verify | The existing traps exit 129, 130 or 143; no stamp; a re-run is idempotent | fail-safe | — |
| FM-16 | A second installer run in parallel on the same machine | `register` serialises on the registry flock (`:396-397`); each `status` reads an atomically renamed file | safe | — |
| FM-17 | The disk is full while `register` writes the registry | `register` raises before the rename (`:428-439`); the old registry is intact; `status` shows the role unregistered; exit 77 | fatal, loud | — |

**Partial state left by a 77 exit** (AD-12's "complete-but-untrusted"):
- agents, `.hos-manifest`, the framework files and a possibly appended `HOS_TMP_ROOT` are on disk;
- `.hos-release` still holds the old tag, or is absent;
- role dirs that did not refuse are created and registered. That is harmless and sticky (invariant 8);
- no PR exists.

---

## 8. Tests

Every test uses the registry override, never the real file. §5 makes the override per-test by default, and
S1's session guard still fails the run if the real registry changes. A test that needs a particular registry
sets its own `HOS_TMP_REGISTRY_FILE`.

### 8.1 `tests/framework/test_hos_tmp_root.py` (`status`, in-process and through the CLI)

| ID | Case | Asserts |
|---|---|---|
| S-1 | registered, private | exit 0; JSON `class=registered`, `blockers=[]`, `adoptable=null`; stdout empty without `--json` |
| S-2 | absent role dir; also an absent root | exit 1, `absent`, `adoptable=true`; the root and role dir **still absent** afterwards |
| S-3 | unregistered, holding only `HOS_ONLY_RE` names (`tmp.x`, `pytest-of-u`, `.hos-x`) | exit 1, `unregistered-adoptable` |
| S-4 | unregistered with 7 blockers, including one allowlisted dir holding `.git` | exit 1, `unregistered-blocked`; `blocker_count == 7` and `len(blockers) == 7` (**all**, not 5); one entry has `kind=project-files`; the stderr line contains `mark --repo` and `and 2 more` |
| S-5 | byte round-trip on disk: names `b"a\nb"`, `b"\x01x"`, `b"\xff\xfe"` (skip on darwin), and a 255-byte name | for each, `bytes.fromhex(name_hex) == original`; stdout is exactly one line and pure ASCII |
| S-6 | serializer round-trip (F-7): a constructed report with a 10 240-byte name holding `\n`, `\x00`, `\x01` and `\xff` bytes, through the pure JSON function | round-trips byte for byte; one line; ASCII |
| S-7 | re-point: the key is registered at root A; `config.sh` now names root B (B's role dir present, and also absent) | exit 1, `repoint`, `adoptable=false`; the stderr line contains `refusing to re-point` |
| S-8 | registered for another repo only | exit 1, `unregistered-adoptable`, `blockers=[]` |
| S-9 | inode change: registered, then `rmdir` and `mkdir` at the same path | exit 1 (not registered: invariant 4) |
| S-10 | structural: role dir is a symlink; a regular file; wrong letter case (the `lexists` monkeypatch of the existing test at `:766`); wrong owner (in-process, with `os.getuid` monkeypatched); registered but mode 0755 (I-3); root invalid (a forbidden character in `config.sh`); an internal error (S-13) | exit 2; classes `structural` ×5 and `root-invalid`; the stderr line starts `hos_tmp_root: status <role>: INVALID:` and contains `Fix the path or value named on this line`; it does **not** contain `CANNOT VERIFY` or `unsandboxed` (RC-2) |
| S-11 | registry absent (the override points at a missing path); the registry is a directory; mode 0644; malformed JSON | exit 2: `registry-absent` for the first, `registry-unreadable` for the rest; the stderr line starts `…: CANNOT VERIFY:` and contains `re-run it unsandboxed`, and never `INVALID:` (RC-2); in the absent case the file and its directory are **not created** |
| S-12 | **no side effects**, over the states of S-1, S-2, S-4, S-10 (mode 0755) and S-11 (absent) | (a) a tree snapshot (`lstat` mode, inode, mtime_ns and size of every path under `tmp_path`, plus the registry's bytes) is identical before and after; no `.lock` and no marker created. (b) In-process, with `os.mkdir`, `os.makedirs`, `os.chmod`, `os.rename`, `os.unlink`, `register`, `write_info_marker` and `_make_dirs_0700` monkeypatched to raise, and `os.open` monkeypatched to raise on `O_CREAT`, `O_WRONLY` or `O_RDWR`, `main(["status", …])` completes with the expected code |
| S-13 | CLI edges: an invalid `--role`; a forced internal exception (monkeypatch `resolve_root` to raise `OSError`) | exit 2 with no JSON for the usage error; exit 2 `class=error` with no traceback for the other; `status` never returns 3 |
| S-14 | `adoption_problems` parity: the S-4 fixture, an unreadable listing (a mode-000 dir; skip as root), and an empty dir | the output equals literal expected strings in today's format; `[_format_blocker(b) for b in adoption_blockers(d)] == adoption_problems(d)`; **every pre-existing guard test passes unchanged** (REQ-5 AC) |

### 8.2 `tests/framework/test_install_tmp_root_verify.py` (new; real `hos_install.sh --local`, `HOS_NO_CONFIG=1`, stdin `"\n"`, as `test_pack_install.py:40-62` does)

Several cases use a **`python3` PATH shim**: a test-written script placed first on `PATH`. It appends its
argv to a log. For an invocation of `…/hos_tmp_root.py <sub>`, it can (a) switch `HOS_TMP_REGISTRY_FILE` by
subcommand, or (b) `sleep` for a configured (sub, role). In every other case it `exec`s the real interpreter
path, captured at test time.

| ID | Case | Asserts |
|---|---|---|
| I-1 | fresh install, clean | rc 0; exactly one stdout line matching the §4.4 regex, and it is `refused=none`; `<parent>/.tmp/{Worker,Overseer,Human,Local}` exist with mode 0700; the per-test registry has 4 entries with `repo == realpath(target)`; `status` exits 0 for each role; `config.sh` holds exactly one `_LINE_RE` match, `HOS_TMP_ROOT="../.tmp"`; the `ok` line ends `(from HOS_INSTALL_TMP_ROOT)`; `.hos-release` is written. **RC-8:** the success line names `realpath(<parent>/.tmp)`, and through the shim, `resolve` prints a decoy path on stdout (`/decoy`) that appears nowhere in the installer output, which proves `resolve`'s stdout is discarded and the root is taken from `status`'s `OK:` line; the registry-override `warn` (RC-7) is present, naming the per-test path |
| I-2 | refused: `config.sh` pre-seeded with `HOS_TMP_ROOT="<tmp>/root"` and `.hos-release` = `v0.6.0`; `<tmp>/root/Worker` is 0700 and holds `percommit-2054/` | rc **77**; `refused=worker`; the output contains `percommit-2054`, `mark --repo`, `unsandboxed, in your own terminal` and `mv '`; `.hos-release` is still `v0.6.0`; `.hos-manifest` and `.claude/agents/*.md` were written (every other step completed); Overseer, Human and Local are registered. **Then** `mv` `percommit-2054` out and re-run: rc 0, `refused=none`, `.hos-release` updated |
| I-2b | as I-2, with `--pr`: a bare `file://` origin and a `gh` stub on `PATH` that logs its argv | rc 77; the `gh` log has no `pr create`; `git ls-remote origin` has no `hos-upgrade/*` branch; the checked-out branch is `PR_BRANCH`; the §4.7 text is printed |
| I-2c | re-point: register Worker at root A, then pre-seed `config.sh` with root B | rc 77; `refused=worker` (plus any other role whose key re-points); `refusing to re-point` is in the output |
| I-3 | `HOS_TMP_REGISTRY_FILE` is a directory | rc 77; `refused=worker,overseer,human,local`; every `verify:` line has the `CANNOT VERIFY:` prefix; the CANNOT VERIFY bullet (`re-run this installer unsandboxed`) is printed; the NOT REGISTERED `mv`/`mark` bullets and the INVALID bullet are **absent** (RC-2) |
| I-3b | masked: the shim gives `status` a non-existent registry path, and `resolve` the real override | rc 77; refused all four; `CANNOT VERIFY` and `re-run` are in the output |
| I-4 | registration planted in a different registry: the shim gives `resolve` registry A and `status` registry B (an empty, valid v1 document) | rc 77; refused all four. This proves the verify reads the registry and does not repeat `resolve` |
| I-5 | hang: `HOS_INSTALL_TMP_VERIFY_TIMEOUT=2`; the shim sleeps 600 s on `status --role worker` and on `resolve --role overseer` | rc 77; `refused=worker,overseer`; the wall time is under 2 × (2 + 5) + 60 s; the output names the timeout; no stray `sleep` survives (the process group is gone) |
| I-6 | idempotent re-run of I-1 | rc 0; `config.sh` byte-identical; the registry entry count is unchanged (4) |
| I-7 | argv audit (the shim log from I-1 and I-8) | every `hos_tmp_root.py` subcommand is in {`install-default`, `validate`, `resolve`, `status`}; every `resolve` has `--create`; no argv contains `mark` or `--reviewed` |
| I-8 | **v0.6.0 upgrade, non-interactive**: `.hos-release` = `v0.6.0`; `config.sh` has v0.6.0's keys and **no** `HOS_TMP_ROOT`; no `bootstrap/lib/` in the target; `HOS_INSTALL_TMP_ROOT` popped; a fake `HOME` whose `projects.conf` lists a sibling `<p>_worker_root` | rc 0; exactly one `_LINE_RE` line, `HOS_TMP_ROOT="../.tmp"` (the computed `install-default`); 4 registered and verified; `.hos-release` updated. A re-run leaves `config.sh` byte-identical |
| I-8b | lone-clone default, dry run only: as I-8, without `projects.conf`, with `--dry-run` | the output contains `Would append HOS_TMP_ROOT="~/.local/state/hos/tmp/<slug>"`; nothing written (see I-12) |
| I-9 | **v0.6.0 upgrade, interactive path** (`@pytest.mark.slow`): as I-8, plus unresolved placeholders, `HOS_NO_CONFIG` unset, stdin a pty from `os.openpty()` pre-loaded with 60 `\n`, and the master drained by a reader thread; timeout 180 s | rc 0; the final `config.sh` (rewritten by `install.sh`) holds exactly one `_LINE_RE` match, with the value from §4.2; 4 registered and verified; `refused=none` |
| I-10 | existing value never overwritten, as `export HOS_TMP_ROOT="../custom"`, as `   HOS_TMP_ROOT=../custom`, and as `HOS_TMP_ROOT=""` | `config.sh` byte-identical (no second line); the dirs are created under `../custom` (or `../.tmp` for the empty case) |
| I-10c | an existing invalid value (`HOS_TMP_ROOT="./inside"`) | not rewritten; rc 77; the resolver's "inside the clone" reason is in the output |
| I-11 | charset gate: `HOS_INSTALL_TMP_ROOT="<tmp>/a+b"` (passes `validate`, fails AD-12's set); `HOS_INSTALL_TMP_ROOT="./tmp"` (fails `validate`); the shim makes `install-default` exit 1 | rc 77 each time; `Set HOS_TMP_ROOT in` and `by hand, then re-run` are in the output; no `HOS_TMP_ROOT` line in `config.sh`; `refused=worker,overseer,human,local` |
| I-11c | `config.sh` mode 000 (skip when the euid is 0) | rc 77, `cannot read` |
| I-12 | `--dry-run` on a fresh target | rc 0; `Would register and verify` and exactly one `tmp-root-verify: skipped=dry-run` line; no `refused=` line; no `<parent>/.tmp`, no registry file, no `.lock`; `config.sh` unchanged or absent |
| I-13 | `exit 77` appears exactly once in `hos_install.sh` (a regex over non-comment lines) | static |
| I-14 | `--reviewed` occurs nowhere in `hos_install.sh`, and no non-comment line runs `hos_tmp_root.py` with a `mark` argument; dynamically, a target whose `bootstrap/lib/hos_tmp_root.py` is pre-created as a **directory** (so the copy fails) | static; rc 77, refused all four, the missing-helper reason |
| I-15 | static ordering and constants: on non-comment lines, the register-and-verify call comes after the line that writes `.hos-manifest` (`printf … > "$_manifest_file"`) and before the line that writes `.hos-release`, which comes before `if $PR_ACTIVE; then` (anchor regexes that match code, never comment text); the default timeout is `30` and the kill-after is `5s`; **every** non-comment line that runs `hos_tmp_root.py` starts with the timeout prefix array (no empty-prefix or bare `python3 … hos_tmp_root.py` path, RC-3); the timeout-prerequisite check sits inside the prerequisite block (before `if ! $PREREQ_OK`); the only `>> "$_subst_config"` appends are the helper's and the `PACK` lines; the two capture forms of §4.1 are the only ones used (RC-8) | static |
| I-16 | **registry-full (RC-1):** the per-test registry is pre-seeded with 256 live entries (256 real dirs under `tmp_path`, each with a distinct live repo dir, written as a valid v1 document with the right inodes) | rc 77; for every role, the output has a `register:` line containing the resolver's `registry-full` text (`already holds 256 live temp roots`), printed before that role's `verify: … NOT REGISTERED` line |
| I-17 | **no timeout binary (RC-3):** `PATH` holds a shim dir with `python3`, `git`, `gh` and the other prerequisites symlinked, and neither `timeout` nor `gtimeout` | rc **1**; the output contains `timeout (coreutils) missing` and `hos_bootstrap.sh`; nothing written (no `.gitignore` change, no `config.sh`, no `.tmp`, no registry). With `--dry-run`: rc 0; `a real install would stop here`; no `hos_tmp_root.py` invocation in the shim log |
| I-18 | **containment (RC-6):** `git ls-files` minus `tests/**`; grep for the literal `HOS_INSTALL_TMP_ROOT` | it appears only in `bootstrap/hos_install.sh` and `docs/CRON-SETUP.md` (this TD's own file under `docs/v0.7.0/` is allowlisted by exact path as a design doc). Also, a run with the variable popped (I-8) prints `(resolver install-default)` |
| I-19 | **registry-override notice (RC-7):** I-1's run, and a run with `HOS_TMP_REGISTRY_FILE` removed from the env but registry reads redirected by the shim (so the installer's own env has no override) | the first prints exactly one `HOS_TMP_REGISTRY_FILE is set (<path>)` warn before the first `register:`/verify output; the second prints none |

### 8.3 `tests/framework/test_tmp_root_first_writer.py` (new; REQ-2 AC; ADR S4a "the export-only plus third-party-write plus launcher sequence succeeds")

| ID | Case | Asserts |
|---|---|---|
| W-1 | Run `hos_install.sh --local --no-pack` into a target whose parent has no `.tmp`. Then simulate the non-launcher session: only an export of `TMPDIR=<root>/Worker` (no resolver call), and a third party writing `node-compile-cache/` and `percommit-2054/` into it. Then run the launcher's resolver step exactly as `bin/hos-cron` calls it: `resolve --repo <target> --role worker --create` | install rc 0; the resolver exits 0 and prints `<root>/Worker`; `status` exits 0. A dir registered at install is accepted whatever it later holds (invariant 8) |
| W-2 | Control, without the install: `mkdir -m 700 <root>/Worker` by hand, the same third-party writes, the same resolver call | the resolver exits 3, naming `percommit-2054`; nothing is registered; the mode and contents are unchanged. This is the #2100 sequence without the REQ-2 step |

S4b later appends its wrapper case to this file (ADR §4 S4b row).

### 8.4 `tests/framework/test_registry_isolation.py` (additions)

- Two tests in the same module see different `HOS_TMP_REGISTRY_FILE` values. Both are under
  `<basetemp>/hos-registry/`, and neither is the real path.
- A test that sets its own override with `monkeypatch.setenv` keeps it.
- `child_env({"PATH": …})` carries `HOS_INSTALL_TMP_ROOT == "../.tmp"` and the per-test registry.
- **Inherited value replaced (RC-5).** A `pytester` (or subprocess `pytest`) run is started with
  `HOS_INSTALL_TMP_ROOT=/abs/elsewhere` in its environment. Inside it, a test asserts
  `os.environ["HOS_INSTALL_TMP_ROOT"] == "../.tmp"`.
- **Module-scope behaviour (RC-10).** A module-scoped fixture sees the session registry path, and a
  function-scoped test in the same module sees a per-test path. Both differ from the real registry.
- Every existing S1 test passes unchanged.

### 8.5 ADR S4a obligation → test map

| ADR §4 S4a obligation | Test(s) |
|---|---|
| fresh install creates, registers **and verifies** four dirs, exits 0 | I-1 |
| export-only + third-party write + launcher succeeds | W-1 (W-2 control) |
| a refused dir: blockers and remedy printed, **exits non-zero** after every other step; a re-run after the remedy exits 0 | I-2 |
| an unreadable registry fails the verify, with "re-run unsandboxed" | I-3, I-3b, S-11 |
| v0.6.0 upgrade, non-interactive **and** interactive: written once, four registered and verified; existing value never overwritten | I-8, I-9, I-10 |
| `--dry-run` writes nothing | I-12 |
| the install never passes `--reviewed` | I-14, I-7 |
| a failed verify exits 77, leaves `.hos-release` at the old tag, opens no install PR | I-2, I-2b, I-13 |
| a registration in a different registry than `status` reads fails the verify | I-4 |
| `status`: no `mkdir`, chmod, registration or marker write; a masked registry is exit 2 | S-12, S-11, S-2 |
| TD-H5: **all** blockers; byte-for-byte round-trip (newline, control byte, 10 kB, invalid UTF-8) | S-4, S-5, S-6 |
| a computed value outside the charset gate writes nothing and exits 77 | I-11 |
| exactly one `tmp-root-verify: refused=<roles|none>` line | I-1, I-2, I-3, I-5, I-11 (and I-12's `skipped` form) |
| a hanging resolver stub is killed at 30 s and counted as a refusal of that role | I-5 (lowered timeout), I-15 (30 s default pinned; no unbounded path), I-17 (no timeout binary → exit 1) |
| *(round 2)* register failure printed; prefix-selected remedy; `--pr` recovery commands; variable containment; override notice; capture method | I-16; S-10, S-11, I-3, I-10c; I-2b; I-18; I-19; I-1 |

`@pytest.mark.slow` runs at release only (`pyproject.toml:23`). Only I-9 (pty) and I-2b (bare remote plus
`gh` stub) are marked slow. Every other case runs in the PR-required suite. #2137 (AD-13) independently
exercises the real upgrade at the release cut.

---

## 9. Protected surface, reviewers, PR obligations

- **Protected.** `bootstrap/hos_install.sh` and `bootstrap/lib/hos_tmp_root.py` match `bootstrap/**`
  (`protected_surfaces.txt:27`). Human approval is required whatever tier is computed. The overseer may not
  merge it.
- **Reviewers.** `reliability-reviewer` is **mandatory** (§7). `security-reviewer` is **mandatory** (RC-9):
  §2.6 rewrites the body of the guard's adoption check, so AD-5 invariants 1 and 2 must be re-reviewed
  whole. `code-reviewer` is required as usual.
- **The S4a PR body must state:**
  - #2059 (unmerged) absorbs the §4.2 writer when it rebases, and that re-review is #2059's obligation. It
    must also cover `install.sh:148`'s presence grep, which misses an indented key (I-5 ruling);
  - S3 extends `adoption_blockers` (§2.6);
  - S2 consumes `status --json` per §3.2;
  - landing order: S4a merges before S2, or in the same PR (AD-11). S2's landing attestation uses this
    slice's `status`;
  - **#2137's v0.6.0-upgrade case must not set `HOS_INSTALL_TMP_ROOT`** (RC-6). It must exercise the real
    `install-default`;
  - every item in §9.1.

### 9.1 PR-body disclosures (RC-11; each is a behaviour a human will notice)

- **(a) The HOS dev machine.** Every real `hos_install.sh` run into a clone that shares `../.tmp` (Worker,
  Overseer, Human) verifies **all four** role dirs. It therefore **exits 77 until `.tmp/Human` is fixed**,
  either by S3 (which adopts `node-compile-cache`) or by the human's own `mv` or `mark --reviewed` (ADR §8
  N-1). The `.tmp/Worker` unblock is reported done, and is re-verified by `status`. The disclosure gives the
  four read-only `status` commands to check first.
- **(b) The E-1 ruling and Q-1.** S4a writes the ADR-literal `install-default` value. So a lone `--human`
  clone gets `~/.local/state/hos/tmp/<slug>`, and its sandbox-policy generation warns instead of succeeding
  (FM-14). The interactive path already behaves this way since #2054. Q-1, the fresh-install layout default,
  is an open **human** question that gates the v0.7.0 cut, not this merge (§13).
- **(c) New prerequisite.** `hos_install.sh` now requires `timeout` (or `gtimeout`). Without one it stops
  with exit 1 before writing anything, and points to `hos_bootstrap.sh` (RC-3).

---

## 10. Interpretations (all accepted by the architect in round 1, with the notes shown)

- **I-1 (§2.6), accepted.** The ADR scopes S4a's `hos_tmp_root.py` edit to "the read-only `status`
  subcommand only". §2.6 also moves `adoption_problems`' body into `adoption_blockers`, byte-identically.
  The resolve path's behaviour and ordering are unchanged, and pinned by S-14. Consequence:
  `security-reviewer` is mandatory (RC-9).
- **I-2 (§2.3 step 5), accepted.** The letter-case expression is repeated in `status`; S-10 pins the parity.
- **I-3 (§2.3 step 8), accepted.** A registered dir with group or other bits set is exit 2, with the
  `INVALID:` prefix (RC-2), never `CANNOT VERIFY:`.
- **I-4 (§4.4), accepted.** The installer prints its own AD-4 remedy block. Its bullets are now
  **conditional on the prefixes printed** (RC-2).
- **I-5 (§4.2), accepted.** `install.sh:148` greps `^(export )?HOS_TMP_ROOT=`, which misses an indented key
  that `_LINE_RE` accepts. That belongs to #2059's re-review, not to S4a.
- **I-6 (§4.5): pm-agent to record before merge.** This is a refinement, not yet satisfied. It refines
  REQ-11's AC "every run prints exactly one `tmp-root-verify: refused=` line". A dry run prints
  `tmp-root-verify: skipped=dry-run`, and runs that exit before the step (prerequisites, drift) print
  nothing. The invariant kept is: **exit 77 ⇔ exactly one line with `refused≠none`; a non-dry exit 0 ⇔
  exactly one `refused=none` line.** **`pm-agent` must record this clarification in
  REQUIREMENTS-2100 REQ-11 before S4a merges.** Until then, the REQ-11 AC is not claimed as met for dry
  runs or early exits.
- **I-7 (F-7), accepted.** The 10 kB round-trip is tested on the serializer, and the 255-byte name on disk.

---

## 11. Escalations

All four round-1 escalations are **ruled** (§13). The only item still open is **Q-1**, a **human** question
that gates the v0.7.0 release cut, not S4a's merge. It was raised by the architect and is routed via
`pm-agent` and the worker.

**Contradictions with the ADR:** none that this design resolves by diverging. F-3 (AD-12 against #2054
D15) is resolved by the E-1 ruling: build the ADR-literal value (a), and leave Q-1 open.

---

## 12. Startup-gap check and affected sign-offs

- *Should this have been settled before code was written?*
  - F-3/E-1/Q-1: **yes**, at #2054's architecture. `install-default`'s lone-clone value and D15's single
    accepted root were never reconciled. **Recommendation to the worker:** annotate #2100, or open a
    `startup-artifact-gap` against #2054, carrying Q-1. I have not filed it, per this task's instructions.
  - F-1 and F-2 are ADR-level gaps found at TD time. No S4a code exists, so no code approval is orphaned.
- **Round-2 changes.** Each is a change to an unbuilt design, so no sign-off is invalidated.
- **Affected sign-offs:**
  - **#2054 S2a resolver security review.** It stands for the resolve path. The §2.6 refactor needs the
    mandatory S4a `security-reviewer` sign-off to re-review the adoption check whole.
  - **S1 (PR #2140).** It stands. §5 adds to its conftest and does not change its guard. S1's tests must
    pass unchanged (§8.4).
  - **#2054 install tests** (`test_install_tmp_root.py`, for `install.sh`) are unaffected. `install.sh`
    reads only the environment variable `HOS_TMP_ROOT`, never `HOS_INSTALL_TMP_ROOT`.
  - **No approved code is affected.** S4a is unbuilt.

---

## 13. Architect rulings (round 1, 2026-10-22)

Source: `.claudetmp/design/architect-2100-S4a-2026-10-22T083613Z.md`. The verdict was **CHANGES_REQUIRED**,
with 13 required changes (RC-1 to RC-13), all folded in above.

| ID | Ruling | Effect in this TD |
|---|---|---|
| **E-1** | **(a): build the ADR-literal `install-default` value in S4a.** Option (b) (choosing `../.tmp` for `--human`) is **rejected**: AD-12 forbids the installer from computing a value | FM-14, §9.1(b) |
| **Q-1** (new, human) | Fresh installs not yet listed in `projects.conf` get `~/.local/state/hos/tmp/<slug>`, which #2054 D15 sandboxes cannot use. **Recommendation:** a #2054 follow-up that makes `install-default` recognise the Worker/Overseer/Human sibling-clone layout. **Gates the v0.7.0 cut, not S4a's merge.** Routed to the human via `pm-agent` and the worker | §9.1(b), §11 |
| **E-2** | Accepted: stay on `PR_BRANCH`. The recovery text must give the exact `stash push --include-untracked` / `checkout` / `branch -D` commands, and must never suggest `git clean` or `reset --hard`. It must state that the remedy is machine-local | §4.7, I-2b |
| **E-3** | Accepted, with three conditions: the conftest sets the variable unconditionally (RC-5); the variable is contained, its source is shown, and #2137 must not set it (RC-6); fixture-scope bound stated (RC-10) | §4.2, §5, I-18, §8.4, §9 |
| **E-4** | **Reversed: fail closed.** `timeout`/`gtimeout` is a prerequisite (exit 1 before any write); a dry run warns. There is no unbounded path | §4.1, FM-6, §6, I-15, I-17 |
| I-1 to I-7 | All accepted. I-3 uses `INVALID:`; I-4's bullets depend on the prefixes; I-5's indented-key issue goes to #2059; I-6 goes to `pm-agent` | §10 |

---

## Escalation flag (CORE self-flag)

RISK: HIGH. Both code files are protected (`bootstrap/**`). The slice adds a new fatal install and upgrade
failure mode (exit 77) and a new prerequisite (exit 1 without `timeout`) on every consumer's install path.
It rewrites the body of the guard's adoption check (behaviour-preserving) and changes the test isolation
that every test inherits.
CONFIDENCE: HIGH on the `status` contract, on F-1, F-2 and F-5, on the placement relative to
`.hos-release` and the PR block, and on the round-2 output contract (the prefixes, the capture forms and
the recovery text). MEDIUM on the pty interactive test's stability (I-9), on the I-16 fixture (256 live
entries with real inodes), and on whether §5's central fix leaves zero existing harnesses to touch (the
reserve slots cover that).
BLAST RADIUS:
- every HOS project install and upgrade (fresh, v0.6.0 → v0.7.0, `--pr`, `--dry-run`), including a new
  hard prerequisite;
- on the HOS dev machine, every install exits 77 until `.tmp/Human` is fixed (§9.1(a));
- the `hos_tmp_root.py` CLI surface;
- every test that runs the resolver or the installer;
- `docs/CRON-SETUP.md` §5a.

No gate, label, merge, reaper or launcher path changes.
Change classification: **additive**, inside the human-ruled structural change. The timeout prerequisite
tightens, and does not weaken, existing behaviour.

## Human Review Required

- Your own-account approval of the S4a PR (protected `bootstrap/**`).
- **Q-1 (gates the v0.7.0 cut, not this merge):** should a fresh install not yet listed in `projects.conf`
  default to the per-project `~/.local/state/hos/tmp/<slug>`, which #2054 D15 sandboxes cannot use? The
  architect recommends a #2054 follow-up that makes `install-default` recognise the
  Worker/Overseer/Human sibling-clone layout. It reaches you via `pm-agent` and the worker.
- Before installing S4a on the HOS dev machine: fix `.tmp/Human` (S3, or your own `mv` or `mark`), or every
  install there exits 77 (§9.1(a)).
