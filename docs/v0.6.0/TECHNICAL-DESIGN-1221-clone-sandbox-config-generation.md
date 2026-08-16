# TECHNICAL DESIGN — #1221 Clone sandbox config generation

**Status:** DRAFT 1 — awaiting `architect` review. Do not hand to `coder` until the architect approves.
**Date:** 2026-08-04
**Author:** technical-design
**Issue:** #1221 · **Milestone:** v0.6.0 · **Risk tier: MEDIUM** (inherited, unchanged)
**Binding inputs (read in full, not relitigated):**
`docs/v0.6.0/SPEC-1221-clone-sandbox-config-generation.md` (FR-1…FR-14, AC1…AC7, E-1/E-2) and
`docs/v0.6.0/ADR-1221-clone-sandbox-config-generation.md` (**ACCEPTED — GO**; AD-1…AD-9 binding, VF-1…VF-11).
**Also read:** `contract/sandbox-policy.template.json` (all 205 lines), `docs/SANDBOX-POLICY.md`,
`bootstrap/validate_setup.sh` (all 83 lines), `bin/hos-human`, `scripts/framework/gen_codeowners.sh`,
`scripts/framework/require_human_approval.py`, `scripts/framework/strip_internal_paths.sh`,
`scripts/framework/installer-internal-paths.txt`, `scripts/framework/framework_consumer_files.txt`,
`scripts/framework/run_tests_inner_loop.sh`, `scripts/automation/lib/overseer_state.py`,
`tests/framework/test_require_human_approval.py`, `tests/conftest.py`, `pyproject.toml`, `.gitignore`.
**Consumer:** `coder`. This document is the implementation contract. It contains **no application code** —
every section states what the code must do, not how to write it.

**Scope of this document:** every decision AD-1…AD-9 deliberately left open. Exit-code integers, CLI flag
names, the values-sidecar format, the exact template diff, the `validate_setup.sh` hook shape, the module
layout, and the test-file layout. Where the ADR bound a decision, this document restates it as a constraint
and cites the AD number; it never re-argues it.

---

## 0. Two obligations the ADR placed on me, and how each is discharged

The ADR §5 placed two "empirical obligations on `technical-design`, to be discharged in the design document,
not assumed." **Neither can be discharged by reading, from this clone.** Both are discharged **by design**
instead — in a way that is strictly safer than a guess would have been. This section is load-bearing: the
`coder` must read it before building, and must not treat either item as a blocker.

### 0.1 — The two placeholders with no in-repo derivation (AD-5, VF-6)

`__HANDOFF_DIR__` and `__CLAUDE_PROJECT_STATE__` have no source of truth anywhere in this repository. AD-5
required me to "recover the ground-truth values from the live Human `.claude/settings.local.json`
(operator-assisted)".

**I did not recover them, and deliberately did not invent them.** The live Human clone's settings file is
outside this session's own sandbox boundary; a cross-clone read is not permitted here, and per `CLAUDE.md`
("Failing safely") a blocked read must be reported plainly rather than routed around. There is no operator
present in an autonomous cron cycle to assist.

**Design consequence — and it is the right one anyway:** both remain **required-explicit CLI flags with no
default** (`--handoff-dir`, `--claude-project-state`; §3.2). AD-5 already bound this. The `coder`'s job is to
make the two flags **required and validated**, and **never to hardcode, derive, or guess a value** — in
particular, **do not** derive `__CLAUDE_PROJECT_STATE__` from a path-mangling rule for
`~/.claude/projects/<mangled>`; that is an undocumented Claude Code internal and AD-5 forbids it until the
mangling is confirmed against a live directory.

Supplying the correct production values is an **operator action taken when the generator is first run
against the live Human clone** — already routed as ADR §4 **N1** ("first `--force` run needs the operator
present"), explicitly *not* a design gate. The operator reads the two paths out of the live
`additionalDirectories` / `sandbox.filesystem.allowRead` entries at that moment and passes them on the command
line. Because the two flags are required, an operator who omits them gets a usage error at exit code `2`
before anything is read or written — the failure is loud, immediate, and impossible to confuse with success.
Because a wrong value would still be *substituted*, the AD-4 echo-back (§3.5) prints every resolved value
before any write, so the operator sees the wrong path rather than inferring it from later tool failures.

**Fail-closed twice over, as AD-5 states:** no value → the flag is required → usage error; and if that were
ever bypassed, the placeholder survives substitution → FR-6/AD-3 hard-fails before any write.

### 0.2 — The AC4 fixture (AD-9)

AD-9 required "a sanitized, path-templated snapshot of the pre-existing live Human file as a test fixture."
**The same sandbox boundary prevents capturing it**, and — separately — committing a capture of the real
machine's file is exactly what `scripts/framework/strip_internal_paths.sh` /
`scripts/framework/installer-internal-paths.txt` exist to prevent.

**Design consequence:** the AC4 fixture is a **synthetic-but-representative reconstruction**, not a capture of
production. It is built from the already-committed `contract/sandbox-policy.template.json` with the seven
placeholders substituted for **clearly non-production fixture values** (§7.2), then modified to encode exactly
the pre-reconciliation live state the §5 deltas describe:

- the FR-11 `bin/**` absolute spellings **absent** (only `Edit(./bin/**)` present),
- the two live-only force-push spellings **present**, the template's `Bash(git push * --force*)` /
  `Bash(git push * -f)` / `Bash(git push -f *)` / `Bash(git push* +*)` **present**,
- the values-sidecar deny **absent** (it did not exist before this PR),
- the live-only allow `Bash(claude *)` **present** (FR-13's removal).

This **fully exercises AC4's property** — "generated output is a semantic superset of the pre-existing live
file: every live deny present, plus exactly the FR-11/FR-12 additions, minus exactly the FR-13 removal", and
the delta table computed from it is a real, reviewable computation over a committed artifact. It simply does
not literally reproduce the real Human clone's edit history. **The `coder` must not block waiting on operator
access to build it**, and must state the synthetic provenance in the fixture's own header and in the test
module docstring so no future reader mistakes it for a production capture.

The literal AC1b/AC4 evidence against the *real* clone remains what AD-9 said it was: a **manual transcript
pasted into the PR body** by the operator, not a test.

---

## 1. What is being built (file manifest)

| # | Path | Action | Owner section |
|---|---|---|---|
| 1 | `scripts/framework/gen_sandbox_config.py` | **new** | §2–§6 |
| 2 | `contract/sandbox-policy.template.json` | **edit** (reconciliation, FR-14) | §8 |
| 3 | `bootstrap/validate_setup.sh` | **edit** (opt-in `--role` hook, AD-6) | §9 |
| 4 | `bin/hos-human` | **edit** (one argument, AD-6.2) | §9.4 |
| 5 | `.gitignore` | **edit** (two entries, AD-5/VF-8) | §5.4 |
| 6 | `tests/framework/test_gen_sandbox_config.py` | **new** | §10 |
| 7 | `tests/framework/fixtures/sandbox/pre-existing-live-human.json` | **new** (synthetic, §0.2) | §7.2 |
| 8 | `tests/framework/fixtures/sandbox/README.md` | **new** (provenance statement) | §7.3 |
| 9 | `docs/SANDBOX-POLICY.md` | **edit** (status + §4 item 6 + §5 table) | §11 |
| 10 | `docs/v0.6.0/TECHNICAL-DESIGN-1221-…md` | this document | — |
| 11 | `DECISIONS.md` | **append** one dated entry | §11.3 |

Plus the PR body: the AC4 delta table (§8.4) and the AC1b manual transcript (§0.1). Eleven files — within the
≤15 files / ≤10 commits budget (`docs/PR-SIZE-POLICY.md`).

**Not touched, deliberately:** `bootstrap/hos_install.sh`, `bootstrap/hos_setup_partner.sh`, `bin/hos-worker`,
`bin/hos-overseer`, `bin/hos-cron`, `.claude/settings.json` (E-1), any CI workflow (FR-10),
`scripts/framework/framework_consumer_files.txt` (§9.6).

---

## 2. Component 1 — `scripts/framework/gen_sandbox_config.py`

Python 3.10+, stdlib only (`argparse`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`,
`datetime`, `pathlib`, `typing`). Shebang `#!/usr/bin/env python3`, executable bit set, invoked directly —
**no `.sh` wrapper** (AD-2). No new `requirements.txt` entry.

### 2.1 The one invariant that governs the whole module (AD-1)

> **Generate mode is a pure function of (template text, resolved values). Nothing else may influence the
> bytes it produces.**

Made structural, not merely intended, by three rules the `coder` must honor:

1. **`render(template_text, values) -> str` takes no path argument of any kind.** There is no parameter
   through which the live file, the clone directory, or the values sidecar could enter. §10 asserts this by
   signature introspection.
2. **Generate mode reads exactly one file to produce output: the template.** It does not read the live file
   and it does not read the values sidecar (§5.3 explains why the sidecar is check-mode-only).
3. The only contact generate mode has with the live file is (a) an **existence test** (`Path.exists()` — a
   stat, not a read) for the FR-7 overwrite gate, and (b) a **backup copy** taken *after* the output content
   is already fully determined and serialized. Both happen after `render()` has returned.

Get this wrong and `--check` can only ever pass (VF-4) — a control that reports green forever.

### 2.2 Module docstring — required content

The module docstring must state, at minimum:

- what the script does (template → a clone's `.claude/settings.local.json`; `--check` compares);
- the AD-1 purity invariant in one sentence;
- the full exit-code table (§4), verbatim — AD-4 makes header documentation of the codes a requirement;
- both usage forms (generate and check), copy-pasteable.

### 2.3 Reconciliation comment block — required, in the source, not the JSON (AD-7, AD-8)

JSON carries no comments, so FR-11's mandated "the redundancy is deliberate" note lives here. Immediately
after the docstring, a comment block titled `# Template reconciliation notes (FR-11 / FR-12 / AD-8)` must
record:

- **the three `bin/**` deny spellings** (relative, single-slash absolute, double-slash absolute) and that the
  redundancy is deliberate because Claude Code's permission-glob matching of relative-vs-absolute and
  single-vs-double-slash is **unverified** (`docs/SANDBOX-POLICY.md` §4 item 7). It costs zero capability and
  **may be pruned once #1146 verifies the matcher**;
- **the six force-push deny spellings** (§8.2), including that `Bash(git push* +*)` is the `+refspec` form
  that VF-5 caught FR-12 dropping, and that `--force-with-lease` matches `*--force*` and is therefore denied —
  intended, not a regression (VF-11);
- **the three values-sidecar deny spellings** and why the sidecar must be non-agent-editable (AD-5: it steers
  the generation of the policy).

### 2.4 Module-level constants

| Name | Value / derivation |
|---|---|
| `REPO_ROOT` | `Path(__file__).resolve().parents[2]` |
| `TEMPLATE_PATH` | `REPO_ROOT / "contract" / "sandbox-policy.template.json"` |
| `TEMPLATE_RELPATH` | `"contract/sandbox-policy.template.json"` (for git + messages) |
| `LIVE_RELPATH` | `".claude/settings.local.json"` |
| `VALUES_RELPATH` | `".claude/hos-sandbox.values"` |
| `VALUES_VERSION` | `"1"` |
| `KNOWN_ROLES` | `("human", "worker", "overseer")` — `argparse choices=` |
| `SUPPORTED_ROLES` | `("human",)` — everything else → exit 3 (FR-5) |
| `PLACEHOLDERS` | ordered tuple: `("ROLE", "PROJECT_ROOT", "HOS_ROOT", "CONFIG_DIR", "HOME", "HANDOFF_DIR", "CLAUDE_PROJECT_STATE")` |
| `REQUIRED_EXPLICIT` | `("HANDOFF_DIR", "CLAUDE_PROJECT_STATE")` |
| `PATH_PLACEHOLDERS` | all of `PLACEHOLDERS` except `"ROLE"` |
| `PLACEHOLDER_RE` | `re.compile(r"__[A-Z][A-Z0-9_]*__")` |
| `BLOCKING_ISSUE` | `"#1146"` |
| exit-code constants | §4 |

`PLACEHOLDERS` is the **single source of truth** for the placeholder set. Flags, sidecar keys, echo-back
order, and the sidecar-completeness check all derive from it — adding an eighth placeholder must require
editing exactly one tuple plus its flag metadata.

### 2.5 Exceptions

Three module-level exception classes, each carrying a human-readable message; `main()` maps them to codes:

| Exception | Exit code | Raised for |
|---|---|---|
| `UsageError` | `2` | bad/conflicting/missing flags, bad `--clone-dir`, a supplied value that is not an absolute path or contains a `__NAME__` token |
| `UnsupportedRole` | `3` | `--role worker` / `--role overseer` (FR-5) |
| `HardFailure` | `5` | malformed template, surviving placeholder, malformed/incomplete/wrong-version values sidecar, unexpected internal error |

---

## 3. CLI contract (AD-4)

```
scripts/framework/gen_sandbox_config.py
    --role {human|worker|overseer}          REQUIRED
    --clone-dir PATH                        REQUIRED
    [--check]
    [--force]
    [--project-root PATH]
    [--hos-root PATH]
    [--config-dir PATH]
    [--home PATH]
    [--handoff-dir PATH]                    REQUIRED in generate mode
    [--claude-project-state PATH]           REQUIRED in generate mode
```

### 3.1 Required inputs

- **`--role`** — `argparse` `choices=KNOWN_ROLES`. No default, no inference from cwd or directory name
  (FR-2). An unknown string (e.g. `--role admin`) is an `argparse` usage error → exit `2`; a *known but
  unsupported* role is the explicit gate → exit `3`. AD-4 requires those two to be distinguishable, which is
  why `choices=` alone is insufficient.
- **`--clone-dir`** — no default, **no cwd fallback**. Validated (in this order, after the role gate):
  `realpath`-resolved; must exist; must be a directory; must contain a `.claude/` **directory**. Any failure →
  `UsageError` → exit `2`. The generator never creates `.claude/`.

### 3.2 The seven placeholders → flags (this table is the answer AD-4/AD-5 left to me)

| Placeholder | Flag | Type | Default | Status |
|---|---|---|---|---|
| `__ROLE__` | *(none — value comes from `--role`)* | choice | — | required via `--role` |
| `__PROJECT_ROOT__` | `--project-root` | abs path | `realpath(--clone-dir)` | derived, overridable |
| `__HOS_ROOT__` | `--hos-root` | abs path | `realpath(--clone-dir).parent` | derived, overridable |
| `__CONFIG_DIR__` | `--config-dir` | abs path | `${HOS_CONFIG_DIR:-$HOME/.config/hos}` | derived, overridable |
| `__HOME__` | `--home` | abs path | `$HOME` | derived, overridable |
| `__HANDOFF_DIR__` | `--handoff-dir` | abs path | **none** | **required-explicit** (§0.1) |
| `__CLAUDE_PROJECT_STATE__` | `--claude-project-state` | abs path | **none** | **required-explicit** (§0.1) |

Notes the `coder` must honor:

- **`__ROLE__` gets no flag of its own.** A second way to set the role is a second way to get it wrong.
- `--config-dir`'s default **reuses `bootstrap/validate_setup.sh:58`'s precedence exactly**
  (`${HOS_CONFIG_DIR:-$HOME/.config/hos}`). AD-5: do not invent a second precedence rule.
- `$HOME` unset or empty, when needed for a default, is a `UsageError` naming the flag that would fix it
  (`--home` / `--config-dir`) — never a silent `""` that renders `/.config/hos`.
- Deriving `__PROJECT_ROOT__`/`__HOS_ROOT__` from an explicitly supplied `--clone-dir` is **not** the
  inference FR-2 forbids (AD-5): FR-2 forbids guessing *which role and which clone*; both are on the command
  line.

### 3.3 Value normalization and validation (applies to all six path values)

Applied identically to derived, env-sourced, flag-supplied, and sidecar-read values:

1. Strip trailing `/` (except a bare `/`, which is rejected — see 3). Prevents `__HOS_ROOT__/Worker` →
   `/srv/hos//Worker`.
2. Must be **absolute**: begins with exactly one `/`. A value beginning `//` is a `UsageError` — the template
   deliberately builds double-slash spellings as `/__PLACEHOLDER__/…` (§8.1), so a value that already carries
   a leading `//` would render `///…`.
3. `/` alone, `""`, and any value containing a newline are `UsageError`.
4. Must not match `PLACEHOLDER_RE` — a value containing e.g. `__HOME__` is a `UsageError` naming the flag,
   **not** a `HardFailure`. This keeps the two failure classes clean: bad *input* → `2`, bad *template* → `5`.
5. No `~` expansion, no environment expansion, no relative-path resolution beyond `realpath` on `--clone-dir`.
   A value is used literally.

`__ROLE__`'s value is validated only as one of `KNOWN_ROLES` (already enforced by `argparse`).

### 3.4 Mode flags

- **`--check`** implies **absolutely no write of any kind** (AD-4) — not the policy file, not the values
  sidecar, not a backup, not a temp file.
- **`--check --force` is a `UsageError` (exit 2)**, not a silent precedence rule (AD-4).
- `--force` without `--check` permits overwriting an existing live file (FR-7); without it, an existing live
  file → exit `4` (§4).

### 3.5 Echo-back (AD-4 — mandatory, both modes)

Before any write, and also in `--check`, print to **stdout** every resolved placeholder → value pair **in
`PLACEHOLDERS` order**, each annotated with its **source**, one of `[flag]`, `[values-file]`, `[derived]`,
`[env]`. Example shape (illustrative, not a format contract beyond "one line per placeholder, name, value,
source"):

```
Resolved values (role=human, clone=/srv/hos/Human):
  ROLE                  = human                                   [flag]
  PROJECT_ROOT          = /srv/hos/Human                          [derived]
  HOS_ROOT              = /srv/hos                                [derived]
  CONFIG_DIR            = /srv/hos/.config/hos                    [env]
  HOME                  = /home/hosuser                           [env]
  HANDOFF_DIR           = /srv/hos/handoff/human                  [flag]
  CLAUDE_PROJECT_STATE  = /home/hosuser/.claude/projects/-srv-hos-Human   [flag]
```

Rationale is AD-4's and it is the whole point of the feature: silent substitution of a wrong path is the
#1114 failure class. The operator must be able to *see* a wrong value, not infer it from later tool failures.

### 3.6 Provenance (AD-7 — reported, never embedded)

On **both** generate and `--check`, print to stdout:

- the template's git blob SHA — `git rev-parse HEAD:contract/sandbox-policy.template.json`, run with `cwd=REPO_ROOT`;
- whether the working-tree template is **dirty** — `git status --porcelain -- contract/sandbox-policy.template.json`
  producing any output.

When dirty, print a **loud warning**: the template being generated from is not the reviewed committed one.
AD-7's rationale is a real finding, not tidiness: a sandboxed agent may edit the template (no deny covers it)
and regenerate with `--force`, rewriting the policy that constrains it — a new link in the #1183 escalation
chain. The structural fix is #1146's (ADR §4 **N2**), not this PR's.

**`git` failures are non-fatal.** If `git` is absent, `REPO_ROOT` is not a work tree, or either command exits
non-zero, print `template provenance: UNAVAILABLE (git: <reason>)` and continue. Use
`subprocess.run(..., capture_output=True, text=True)` with `check=False`; never let a provenance failure
change an exit code.

**Do not inject any provenance key, comment, or `_generated_by` field into the output JSON** (AD-7). Unknown
keys in a settings file are a compatibility gamble, and any such key would need excluding from the `--check`
comparison — a special case in the one code path that must be trustworthy.

---

## 4. Exit codes — **confirmed and extended** (the decision AD-4 left to me)

AD-4 named six classes and suggested `0`–`5`, binding only distinctness and header documentation. **I confirm
`0`–`5` as suggested and add one seventh code**, because AD-5 requires a *seventh* distinguishable outcome
("values file absent") that AD-4's list does not contain. AD-4 says "at minimum", so this is a refinement, not
a departure.

| Code | Constant | Meaning | Mode |
|---|---|---|---|
| `0` | `EXIT_OK` | generate: written successfully. `--check`: live file **matches** a fresh generation. | both |
| `1` | `EXIT_DIVERGENT` | `--check` only: live file **diverges** (incl. live file missing, live file unparseable, live file containing a surviving `__NAME__`). | check |
| `2` | `EXIT_USAGE` | usage error: bad/missing/conflicting flags, bad `--clone-dir`, invalid value. Matches `argparse`'s own exit code. | both |
| `3` | `EXIT_UNSUPPORTED_ROLE` | `--role worker` / `--role overseer` — refused, message names **#1146** (FR-5). | both |
| `4` | `EXIT_REFUSE_OVERWRITE` | generate only: live file exists and `--force` was not given (FR-7). | generate |
| `5` | `EXIT_HARD_FAIL` | surviving placeholder, malformed template, malformed/incomplete/wrong-version values sidecar, **any unexpected internal error**. | both |
| `6` | `EXIT_NOT_ENROLLED` | `--check` only: **no values sidecar** — this clone was never generated; it is hand-maintained (AD-5). | check |

**Three properties the `coder` must guarantee, each independently testable:**

1. **All seven are distinct**, and `1` is reserved for divergence alone. This matters because an unhandled
   Python exception exits `1` by default — which the `validate_setup.sh` hook would read as "divergent" when
   the truth is "the checker is broken". **`main()` must therefore wrap its whole body in a top-level
   `except Exception` that prints the traceback to stderr and returns `EXIT_HARD_FAIL` (5).** No path may
   leak a bare `1`.
2. **`6` is never conflated with `1`** (AD-5). "You have drifted" and "you were never enrolled" are different
   operator situations with different next actions.
3. **Exit `3` happens before any filesystem access** (AD-4/AC2): the role gate is the first thing `main()`
   does after `argparse` returns — before the template is opened, before `--clone-dir` is validated, before
   provenance is queried, before any temp file could exist. AC2's "neither writes any file" is then
   structural, not incidental.

---

## 5. Component 1a — the values sidecar (AD-5; the decision this design turns on)

VF-7: `--check`, invoked from `validate_setup.sh` (which knows only `--repo`), has no way to reproduce the
substitution used at generate time and would report permanent spurious divergence. The sidecar closes it.

### 5.1 Path and lifecycle

- **Exact path:** `<clone-dir>/.claude/hos-sandbox.values`
- **Written:** by generate mode only, **after** the policy file has been successfully `os.replace`d — so a
  sidecar never exists describing a generation that did not land.
- **Read:** by `--check` mode only.
- **Never read by generate mode** (§5.3).
- Written under the same AD-3 atomic discipline (`write_atomic`, §6.7).
- Untracked and machine-local; `.gitignore` entry ships in this PR (§5.4, VF-8).

### 5.2 Format — exact schema

Plain text, UTF-8, LF line endings, trailing newline. Lines are `KEY=VALUE`.

```
# hos-sandbox.values — GENERATED by scripts/framework/gen_sandbox_config.py (#1221)
# Machine-local, untracked, not a secret. Records the placeholder values used to
# generate .claude/settings.local.json so `--check` can reproduce them.
# NEVER sourced by a shell — parsed only. Do not hand-edit; regenerate instead.
META_VALUES_VERSION=1
META_GENERATED_AT=2026-08-04T15:30:12Z
META_GENERATOR=scripts/framework/gen_sandbox_config.py
META_TEMPLATE_BLOB_SHA=3f2a1c9e0b7d4a5f6c8b9a0d1e2f3a4b5c6d7e8f
ROLE=human
PROJECT_ROOT=/srv/hos/Human
HOS_ROOT=/srv/hos
CONFIG_DIR=/srv/hos/.config/hos
HOME=/home/hosuser
HANDOFF_DIR=/srv/hos/handoff/human
CLAUDE_PROJECT_STATE=/home/hosuser/.claude/projects/-srv-hos-Human
```

**Key namespace.** Exactly two classes:
- the **seven placeholder keys** — the bare `PLACEHOLDERS` names (no leading/trailing underscores);
- **`META_*`** metadata keys — `META_VALUES_VERSION`, `META_GENERATED_AT` (UTC, `%Y-%m-%dT%H:%M:%SZ`),
  `META_GENERATOR`, `META_TEMPLATE_BLOB_SHA` (the literal string `unavailable` when git could not be queried).

**Write order (deterministic):** header comment block, then `META_*` keys sorted alphabetically, then the
seven placeholder keys **in `PLACEHOLDERS` order**.

**Parse rules — strict, because this file steers a security boundary:**

1. Strip each line; skip empty lines and lines beginning `#`.
2. Split on the **first** `=`. No `=` → `HardFailure`.
3. Key must match `^[A-Z][A-Z0-9_]*$` → else `HardFailure`.
4. Value is taken **literally**: no quote stripping, no backslash escapes, no `$` expansion, no `~` expansion.
5. A duplicate key → `HardFailure`.
6. A non-`META_` key not in `PLACEHOLDERS` → `HardFailure` (catches typos rather than silently ignoring them).
7. Any of the seven placeholder keys **missing** → `HardFailure` with the message "values file is incomplete —
   regenerate" (exit `5`, **not** `6`: the file exists, so the clone *was* enrolled; it is corrupt).
8. `META_VALUES_VERSION != "1"` → `HardFailure` naming the found version.
9. Every parsed path value is re-run through the §3.3 normalization/validation. A sidecar containing a
   relative path is corrupt → `HardFailure`.
10. `ROLE` in the sidecar **must equal** `--role`. A mismatch is a `HardFailure` naming both — it means the
    clone was generated for a different role, which is precisely the FR-2 hazard.

**This file is never sourced by a shell.** State it in the file's own header (as above) and in the parser's
docstring. A shell `source` of a file containing `HOME=…` would be catastrophic; the rule is defensive and
must be explicit so no future script "conveniently" sources it.

**The sidecar is not byte-deterministic** (`META_GENERATED_AT` changes per run). AC5's byte-identity property
applies to the **policy output only**; `--check` compares the policy file and **never** compares sidecar bytes.

### 5.3 Precedence, and why generate mode does not read the sidecar

Uniform precedence for every placeholder value: **flag > sidecar (`--check` mode only) > derived/env default >
required-error.**

**Decision (mine; the ADR left it open): generate mode does NOT read the sidecar.** Three reasons:

1. **AD-1 purity.** Reading in-clone state at generate time is the same class of mistake as reading the live
   file. It makes the output a function of untracked local state.
2. **It keeps the two no-default placeholders an explicit, echoed operator act on every regeneration** —
   which is the entire mitigation for §0.1's unverified values.
3. It makes an otherwise-fuzzy invariant crisply testable: **generate mode opens exactly one file for
   reading — the template.**

The cost — the operator re-supplies `--handoff-dir` and `--claude-project-state` on every regenerate — is paid
down by two things: the sidecar holds both values in plain text for the operator to read, and **on success the
generator prints the exact, fully-flagged command line that reproduces this generation** (a copy-pasteable
`… --force` line). Print that same line as part of the FR-8 divergence report too (§6.5).

`--check` accepts value flags as overrides (useful in tests and for diagnosing a corrupt sidecar); the
echo-back's `[flag]` vs `[values-file]` annotation makes the source visible. A flag and the sidecar disagreeing
is **not** an error — the flag wins, visibly.

### 5.4 `.gitignore` (VF-8, AD-5)

Two entries, appended to the existing "Claude Code machine-local settings" block (currently `.gitignore:39-48`,
immediately after `.claude/settings.local.json` on line 40):

```
.claude/hos-sandbox.values
.claude/settings.local.json.bak-*
```

The second is **mine, not the ADR's**, and is in-remit for the same reason as the first: this PR *causes* those
backup files to exist (§6.8), `.gitignore:40` matches only the exact filename, and a timestamped copy of a
machine-specific security config landing in `git status` will eventually be committed by accident. Both are
additive ignore entries; nothing existing is loosened.

---

## 6. Module layout — functions, responsibilities, contracts

Ordered as they should appear in the file. Type hints throughout (`from __future__ import annotations`), in
keeping with `require_human_approval.py`.

| # | Function | Signature (shape) | Responsibility |
|---|---|---|---|
| 1 | `build_parser()` | `() -> argparse.ArgumentParser` | Declares §3's flags. `choices=KNOWN_ROLES`. No `required=True` on the two explicit-value flags (their absence must be reportable as a *values* error with the §0.1 explanation, not a bare argparse message). |
| 2 | `gate_role(role)` | `(str) -> None` | AD-4's explicit gate. Raises `UnsupportedRole` for any role not in `SUPPORTED_ROLES`, message naming **#1146** and stating that per-role rule content is that issue's work. **First call in `main()` after parsing; performs no I/O.** |
| 3 | `validate_clone_dir(raw)` | `(str) -> Path` | §3.1 checks; returns the resolved path. Raises `UsageError`. |
| 4 | `normalize_path(raw, flag_name)` | `(str, str) -> str` | §3.3 rules. Raises `UsageError` naming `flag_name`. |
| 5 | `resolve_values(args, env, sidecar)` | `(Namespace, Mapping[str,str], dict[str,str] \| None) -> tuple[dict[str,str], dict[str,str]]` | Returns `(values, sources)` keyed by `PLACEHOLDERS`. Applies §5.3 precedence, §3.3 validation. Raises `UsageError` for a missing required-explicit value, with a message that names the flag **and** points at §0.1's "ask the operator; never guess". Pure w.r.t. the filesystem — the caller supplies `sidecar`. |
| 6 | `load_template(path)` | `(Path) -> str` | Reads the template as text. Missing/unreadable → `HardFailure`. Returns **text**, not a parsed object — parsing belongs to `render()` so `render` is self-contained and unit-testable from a string. |
| 7 | `substitute(node, values)` | `(Any, dict[str,str]) -> Any` | Recursive walk of the parsed document. Replaces `__NAME__` in **every string, keys and values alike**, for each name in `values`. Lists and dicts rebuilt, not mutated in place. |
| 8 | `find_surviving_placeholders(s)` | `(str) -> list[str]` | `sorted(set(PLACEHOLDER_RE.findall(s)))`. Run on the **serialized output string** (AD-3), so it catches placeholders anywhere — including inside the `SessionStart` hook command (`contract/sandbox-policy.template.json:9`), which a per-key walk would miss. |
| 9 | `render(template_text, values)` | `(str, dict[str,str]) -> str` | **The pure core (§2.1).** `json.loads` (JSONDecodeError → `HardFailure`); reject a non-object top level; `substitute`; `json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)` + `"\n"`; `find_surviving_placeholders` on the result → non-empty ⇒ `HardFailure` listing them and naming #1114. **Takes no path parameter of any kind.** |
| 10 | `canonicalize(node)` | `(Any) -> Any` | Comparison-only normal form (§6.4). Never used to produce output. |
| 11 | `compare(generated_text, live_text)` | `(str, str) -> list[Divergence]` | §6.5. Rule-level, order-insensitive for string arrays. |
| 12 | `format_divergences(findings, ctx)` | `(list[Divergence], dict) -> str` | §6.5's report text. |
| 13 | `read_values_file(path)` | `(Path) -> dict[str,str] \| None` | `None` iff the file does not exist (→ caller returns exit `6`). Otherwise §5.2's strict parse; raises `HardFailure`. |
| 14 | `write_values_file(path, values, meta)` | `(Path, dict, dict) -> None` | §5.2 write order, via `write_atomic`. |
| 15 | `write_atomic(path, content)` | `(Path, str) -> None` | §6.7. |
| 16 | `backup_live(live, now)` | `(Path, datetime) -> Path` | §6.8. Returns the backup path. |
| 17 | `template_provenance(repo_root)` | `(Path) -> tuple[str \| None, bool \| None]` | §3.6. `(blob_sha, dirty)`; `(None, None)` when git is unavailable. Never raises. |
| 18 | `echo_values(values, sources, role, clone_dir, out)` | `(...) -> None` | §3.5. |
| 19 | `regenerate_command(values, clone_dir, force)` | `(...) -> str` | The copy-pasteable command line (§5.3). |
| 20 | `run_generate(args, clone_dir, values, rendered, provenance)` | `(...) -> int` | §6.6 generate sequence. Returns an exit code. |
| 21 | `run_check(args, clone_dir, values, rendered, provenance, sidecar_found)` | `(...) -> int` | §6.6 check sequence. Returns an exit code. |
| 22 | `main(argv=None)` | `(list[str] \| None) -> int` | §6.6 orchestration + §4's exception→code mapping + the top-level `except Exception → 5`. |
| — | `if __name__ == "__main__": sys.exit(main())` | | matches `require_human_approval.py:262-263`. |

`Divergence` is a small dataclass or `NamedTuple`: `path: str` (dotted JSON path, e.g.
`permissions.deny`), `kind: str` (one of `MISSING`, `EXTRA`, `CHANGED`, `MISSING_KEY`, `EXTRA_KEY`),
`expected: Any`, `actual: Any`.

### 6.4 Canonical form and determinism (AC5)

- **Output serialization:** `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` plus a trailing
  newline. `sort_keys=True` is what makes AD-9's "stable under a shuffled template key order" assertion true:
  two templates differing only in key order produce **byte-identical** output.
- **Arrays are never reordered on output.** They are ordered JSON values and the template's grouping is
  meaningful to a human reader of the generated file. Shuffling an *array* in the template is a semantic edit,
  not a formatting one; only *key* order is normalized.
- **`canonicalize()` is comparison-only:** recursively sorts dict keys; converts a list whose elements are all
  strings into a sorted multiset representation (a sorted list, duplicates preserved); leaves lists containing
  objects positional. This is why `--check` does not cry wolf on a reordered `allow` list — AD-2's stated
  reason for choosing Python over a bash byte-diff.

### 6.5 `compare()` — the FR-8 rule-level comparison

Both sides are parsed with `json.loads`. Then, recursively:

- **Objects:** key present in generated but not live → `MISSING_KEY`; present in live but not generated →
  `EXTRA_KEY`; shared keys recursed.
- **Arrays of strings** (`permissions.allow`, `permissions.deny`, `additionalDirectories`, every
  `sandbox.filesystem.*` list, `allowedDomains`, `excludedCommands`, `ask`): compared as **multisets**. Items
  in generated but not live → `MISSING`; items in live but not generated → `EXTRA`. No index in the path.
- **Arrays containing objects** (`hooks.SessionStart`): compared **positionally** after canonicalization;
  path carries the index (`hooks.SessionStart[0].hooks[0].command`).
- **Scalars:** inequality → `CHANGED` carrying both values.

Three special cases resolved here, each mapping to exit `1`, **not** `5` — because in all three the policy is
knowably wrong and regeneration is the fix, whereas exit `5` would make the hook say "status unknown":

1. **Live file absent** (sidecar present) → one `Divergence` with a dedicated message: "policy file is missing
   entirely although this clone is enrolled".
2. **Live file is not valid JSON** → dedicated message: "live file is not valid JSON — the policy is not in
   effect as written".
3. **Live file contains a surviving `__NAME__`** (FR-6's `--check` half) → an explicit, separately-labelled
   line listing the placeholders and naming **#1114**, *in addition to* whatever multiset differences result.

Report shape (illustrative; the contract is "grouped by JSON path, rule-level, never a raw byte diff", and it
must end with the regenerate command):

```
SANDBOX POLICY DIVERGENT
  clone:    /srv/hos/Human
  live:     /srv/hos/Human/.claude/settings.local.json
  template: contract/sandbox-policy.template.json (blob 3f2a1c9, clean)

  permissions.deny — 2 expected entries missing from live:
      - Bash(git push* +*)
      - Edit(/srv/hos/Human/bin/**)
  permissions.allow — 1 entry in live that the template does not define:
      + Bash(claude *)
  permissions.defaultMode — value differs: expected "auto", live "acceptEdits"

  Regenerate:
    python3 scripts/framework/gen_sandbox_config.py --role human \
      --clone-dir /srv/hos/Human \
      --handoff-dir /srv/hos/handoff/human \
      --claude-project-state /home/hosuser/.claude/projects/-srv-hos-Human --force
```

The report goes to **stdout** from the generator (it is the generator's normal output). The
`validate_setup.sh` hook is what re-emits it on **stderr** (§9.2) — that is where FR-9's "loudly on stderr"
obligation lives.

### 6.6 `main()` — exact order of operations

Ordering is load-bearing for AC2 and AC3; the `coder` must not reorder.

1. `argparse` parse (bad flags → argparse's own exit `2`).
2. **`gate_role(args.role)`** — no I/O yet. → exit `3` for worker/overseer.
3. Mode-conflict check: `--check --force` → `UsageError` → exit `2`.
4. `validate_clone_dir(args.clone_dir)` → exit `2` on failure.
5. `template_provenance(REPO_ROOT)`; print provenance + dirty warning (§3.6).
6. `sidecar = read_values_file(clone_dir / VALUES_RELPATH)` **if `--check`**, else `None`.
   In `--check`, `sidecar is None` ⇒ print the "not enrolled" message and **return `6` immediately** — before
   value resolution, because without the sidecar there is nothing to reproduce.
7. `resolve_values(args, os.environ, sidecar)` → exit `2` on a missing/invalid value.
8. `echo_values(...)`.
9. `load_template(TEMPLATE_PATH)` → exit `5` on failure.
10. `rendered = render(template_text, values)` → exit `5` on malformed template or surviving placeholder.
    **Nothing has been written at this point, in either mode. AC3 is satisfied by construction (AD-3): there is
    no cleanup path to get wrong and no window in which a partial file exists.**
11. Dispatch: `run_check(...)` or `run_generate(...)`.

**`run_generate`:**

1. `live = clone_dir / LIVE_RELPATH`.
2. `live.exists()` (a stat, not a read) and not `--force` → print the refusal naming `--force` → return `4`.
   **The file is not touched.**
3. If `live.exists()` and `--force`: `backup_live(live, utcnow())` (§6.8) — the **only** read of the live file,
   and it happens after `rendered` is already final.
4. `write_atomic(live, rendered)`.
5. `write_values_file(clone_dir / VALUES_RELPATH, values, meta)` — **after** step 4, so a sidecar never
   describes a generation that did not land.
6. Print: the output path; the backup path and the **exact restore command** (`cp <backup> <live>`) if a backup
   was taken (AD-3.3); the sidecar path; the `regenerate_command(...)` line; and "restart the session for the
   new policy to take effect".
7. Return `0`.

**`run_check`:** read `live` (absent/unparseable → §6.5 special cases); `compare(rendered, live_text)`; empty →
print "current" and return `0`; non-empty → print `format_divergences(...)` and return `1`. **Writes nothing —
no temp file, no backup, no sidecar.**

### 6.7 `write_atomic` (AD-3.2, precedent `scripts/automation/lib/overseer_state.py:48-63`)

`tempfile.mkstemp(dir=path.parent, prefix=".tmp-hos-sandbox-")` — **in the target's own directory, never
`/tmp`**, because `os.replace` is not atomic across filesystems and `/tmp` is frequently a separate mount.
Write via `os.fdopen(fd, "w")`; `flush()`; `os.fsync(f.fileno())`; then `os.replace(tmp, path)`. On any
exception, `os.unlink(tmp)` inside a `try/except OSError: pass`, then re-raise — exactly the precedent's shape.
Set the final file's mode to `0o600` (it is a machine-local security config; `mkstemp` already creates `0o600`,
so this is a no-op guard that must not be "helpfully" widened).

### 6.8 `backup_live` (FR-7, AD-3.3)

- Name: `<live>.bak-<UTC compact ISO>`, i.e. `.claude/settings.local.json.bak-20260804T153012Z`
  (`datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")`). Colons are deliberately absent — the repo's
  existing audit filenames use the same colon-free convention.
- Taken with `shutil.copy2` **before** `os.replace`, and it is a copy of the **pre-existing** live file. A
  backup that could ever contain generator output is not a backup (AD-3.3).
- If the backup path already exists (same-second re-run), append `-1`, `-2`, … rather than overwriting.
- The restore command is printed verbatim on success.

---

## 7. Fixtures

### 7.1 Directory

New: `tests/framework/fixtures/sandbox/`. (`tests/framework/fixtures/` already exists —
`sample_agent_three_region.md`, `packs/testpack/`.)

### 7.2 `pre-existing-live-human.json` — the AC4 baseline (synthetic; see §0.2)

Built as: `contract/sandbox-policy.template.json` **at its pre-reconciliation state** (i.e. today's committed
content, before §8's edits), with the seven placeholders substituted for the fixture values below, then the one
live-only allow added.

**Fixture values — deliberately non-production, and no real operator path appears anywhere:**

| Placeholder | Fixture value |
|---|---|
| `ROLE` | `human` |
| `HOS_ROOT` | `/srv/hos` |
| `PROJECT_ROOT` | `/srv/hos/Human` |
| `CONFIG_DIR` | `/srv/hos/.config/hos` |
| `HOME` | `/home/hosuser` |
| `HANDOFF_DIR` | `/srv/hos/handoff/human` |
| `CLAUDE_PROJECT_STATE` | `/home/hosuser/.claude/projects/-srv-hos-Human` |

Deltas from the substituted pre-reconciliation template, encoding the live state §5 describes:

- `permissions.allow` **gains** `"Bash(claude *)"` (the live-only allow FR-13 declines to carry over).
- `permissions.deny` **gains** `"Bash(git push* -f*)"` and `"Bash(git push*--force*)"` (the two live-only
  force-push spellings).
- Everything else identical — so the fixture has only `Edit(./bin/**)` (no absolute `bin` spellings), no
  values-sidecar deny, and does carry `Bash(git push* +*)`.

These fixture values are also what §10's tests pass as flags, and what a generated fixture sidecar contains.

### 7.3 `tests/framework/fixtures/sandbox/README.md`

Short, and required. Must state: **this is a synthetic reconstruction, not a capture of any real machine's
`.claude/settings.local.json`**; how it was derived (§7.2); that the fixture path values are invented; and that
the real-clone evidence for AC1b/AC4 is the manual transcript in PR #1221's body. Without this note a future
reader will reasonably assume it is a production capture.

### 7.4 Fixtures built in-test, not committed

To keep the file count down, these are constructed inside `tmp_path` by the tests rather than committed:
a minimal template, a template with a deliberately misspelled placeholder (AC3), a malformed-JSON template,
a shuffled-key-order copy of the real template (AC5), and every values sidecar.

---

## 8. Component 2 — `contract/sandbox-policy.template.json` reconciliation (FR-14, AD-1, AD-8)

**This is a one-time, human-reviewed edit to the tracked template. It is *not* generator behavior** (AD-1).
There is **no merge mode, no `--preserve-live-denies` flag, and no "union in on first run"** (AD-1's
corollary). Line numbers below are the current committed file.

### 8.1 `permissions.deny` — `bin/**` (FR-11) and the values sidecar (AD-5)

Current lines 103-110 become (additions marked `+`; **nothing is removed**):

```
      "Edit(./.claude/settings.json)",
      "Edit(./.claude/settings.local.json)",
+     "Edit(./.claude/hos-sandbox.values)",
+     "Edit(__PROJECT_ROOT__/.claude/hos-sandbox.values)",
+     "Edit(/__PROJECT_ROOT__/.claude/hos-sandbox.values)",
      "Edit(./.claude/hooks/**)",
      "Edit(./.envrc)",
      "Edit(./bin/**)",
+     "Edit(__PROJECT_ROOT__/bin/**)",
+     "Edit(/__PROJECT_ROOT__/bin/**)",
      "Edit(__CONFIG_DIR__/**)",
      "Edit(__HOS_ROOT__/Worker/**)",
      "Edit(__HOS_ROOT__/Overseer/**)",
```

**FR-11's three spellings, worked through** so the `coder` cannot mis-render the double-slash form. With
`__PROJECT_ROOT__ = /srv/hos/Human`:

| Template entry | Renders to | FR-11 role |
|---|---|---|
| `Edit(./bin/**)` | `Edit(./bin/**)` | relative — the spelling `CLAUDE.md` refers to; **retained** (FR-14, #1202 sequencing) |
| `Edit(__PROJECT_ROOT__/bin/**)` | `Edit(/srv/hos/Human/bin/**)` | single-slash absolute — natural substitution output |
| `Edit(/__PROJECT_ROOT__/bin/**)` | `Edit(//srv/hos/Human/bin/**)` | double-slash absolute — the live, production-proven form |

The leading literal `/` in the third spelling is what produces the double slash, because every path value is
validated to begin with exactly one `/` (§3.3 rule 2). This is the same literal-double-slash idiom the template
already uses at lines 78-80 (`Read(//tmp/**)`, `Edit(//tmp/**)`, `Write(//tmp/**)`).

**Values-sidecar deny — three spellings, and this is my decision, not the ADR's.** AD-5 bound *that* the values
file must join the deny family; it did not bind the spelling. I apply FR-11's reasoning: this is a **new**
entry added under the same unverified glob semantics, and it guards a file that steers the generation of the
policy itself. One spelling would leave exactly the gap FR-11 exists to close. Three spellings is strictly
safer and costs no capability.

**Two things I deliberately do not do, and the reviewer should see them as omissions on purpose:**

- I do **not** add absolute spellings for the existing `Edit(./.claude/settings.json)` /
  `Edit(./.claude/settings.local.json)` denies. They have the same latent single-spelling gap, but widening
  them is outside FR-14's stated remit (which is the §5 reconciliation plus what this PR creates). **Route to
  #1146** alongside ADR §4 N2, in the same `docs/SANDBOX-POLICY.md` §4 note (§11.1).
- I do **not** add a `sandbox.filesystem.denyWrite` entry for `.claude/` or `contract/`. That is the
  structural fix the architect explicitly declined to absorb (ADR §4 N2, #1146).

### 8.2 `permissions.deny` — the six force-push spellings (FR-12 + AD-8/VF-5)

Current lines 122-125 become six entries. **This is the complete, explicit list AD-8 required me to state:**

| # | Entry | Provenance |
|---|---|---|
| 1 | `"Bash(git push* -f*)"` | **added** — live-only spelling (FR-12) |
| 2 | `"Bash(git push*--force*)"` | **added** — live-only spelling (FR-12) |
| 3 | `"Bash(git push * --force*)"` | **retained** — template line 122 |
| 4 | `"Bash(git push * -f)"` | **retained** — template line 123 |
| 5 | `"Bash(git push -f *)"` | **retained** — template line 124 |
| 6 | `"Bash(git push* +*)"` | **RETAINED — template line 125.** The `+refspec` form. FR-12's "union of all five" omitted it; VF-5/AD-8 make retaining it mandatory. A deny is only ever added, never subtracted. |

Emit them in the order above (added first, then the four retained in their existing template order), so the
diff reads as a pure insertion of two lines with no reordering churn.

Accepted consequence, recorded rather than discovered later (FR-12, confirmed by VF-11): `--force-with-lease`
matches `*--force*` and is therefore denied. Already true of the live config, so not a regression, and
intended — a lease-guarded force push is still a force push. VF-11 confirms the string appears nowhere in this
repo's scripts, so it costs nothing operationally.

### 8.3 `permissions.allow` — unchanged (FR-13)

**No edit.** `Bash(claude *)` is live-only and is intentionally **not** carried over: an allow is not
monotonic, and importing a live-only allow grants capability no reviewer approved (§5's asymmetry, confirmed by
AD-8). Whether nested-`claude` invocation belongs in the shared profile is #1146's
(`docs/SANDBOX-POLICY.md` §4 item 7). Impact is low: with `autoAllowBashIfSandboxed: true` the allow list is
advisory, not enforcing.

**Everything else in the template is unchanged**: `model`, `hooks`, `additionalDirectories`, `ask`,
the whole `sandbox` block, `allowedDomains`.

### 8.4 The AC4 delta table — must appear in the PR body

Computed by a test from §7.2's fixture (not asserted by hand). Shape:

| Change | Entry | List | Reason |
|---|---|---|---|
| **+** | `Edit(__PROJECT_ROOT__/bin/**)` | deny | FR-11 single-slash absolute |
| **+** | `Edit(/__PROJECT_ROOT__/bin/**)` | deny | FR-11 double-slash absolute |
| **+** | `Edit(./.claude/hos-sandbox.values)` | deny | AD-5 values sidecar |
| **+** | `Edit(__PROJECT_ROOT__/.claude/hos-sandbox.values)` | deny | AD-5, FR-11 spelling reasoning |
| **+** | `Edit(/__PROJECT_ROOT__/.claude/hos-sandbox.values)` | deny | AD-5, FR-11 spelling reasoning |
| **−** | `Bash(claude *)` | allow | FR-13 — live-only allow, deliberately not carried |
| **=** | `Bash(git push* -f*)` | deny | live spelling, now tracked |
| **=** | `Bash(git push*--force*)` | deny | live spelling, now tracked |
| **=** | `Bash(git push * --force*)` · `Bash(git push * -f)` · `Bash(git push -f *)` · `Bash(git push* +*)` | deny | retained — **six** force-push spellings total (AD-8) |
| **=** | every other live `allow` and `deny` | — | present unchanged |

Read against the §7.2 fixture, `+` = "in generated, absent from the pre-existing live file", `−` = "in the
pre-existing live file, absent from generated", `=` = "present in both". **The one and only `−` is
`Bash(claude *)`, and it is an `allow`. There is no `−` in `deny`** — that is the semantic-superset property
AC4 asserts, and the test must assert it as a property ("no deny entry is ever removed"), not just as a list.

---

## 9. Component 3 — the `validate_setup.sh` hook (AD-6)

VF-2/VF-3 make the naive FR-9 reading unsafe: `validate_setup.sh` is shared by all three roles, by
`bin/hos-cron:471` (which discards stderr **and** aborts the cycle on non-zero), and by
`bootstrap/hos_setup_partner.sh`. **Opt-in, default-skip.**

### 9.1 Argument parsing change

`bootstrap/validate_setup.sh` currently declares `QUIET=false` / `REPO_ROOT=""` (lines 14-15) and parses in a
`while` loop (lines 17-23) whose `*)` arm prints usage and exits 1.

- Add `SANDBOX_ROLE=""` beside the existing two.
- Add one case arm: `--role) SANDBOX_ROLE="$2"; shift 2 ;;`
- Update the usage string (line 21) to `Usage: $0 [--quiet] [--repo PATH] [--role ROLE]`.
- Update the header comment block (lines 7-10) with a fourth usage line documenting that `--role` enables the
  sandbox-policy currency check and that **omitting it skips the check entirely**.

`bin/hos-worker`, `bin/hos-overseer`, `bin/hos-cron` and `bootstrap/hos_setup_partner.sh` are **not modified**;
with no `--role` their behavior is byte-identical to today (AD-6.1). That keeps the VF-3 cron path structurally
out of reach.

### 9.2 The check function — signature, exact contract, and the `set -e` hazards

**Signature:** `sandbox_config_check() { … }`, taking two positional arguments — `$1` = role, `$2` = repo root.
No globals read beyond what it is passed. **Returns** `0` when the policy is current, non-zero otherwise;
**never calls `exit`**.

**Three hard constraints (AD-6.3), each of which the `coder` must be able to point at in the diff:**

1. **It must not use the existing `fail()` helper** (`validate_setup.sh:27`) — `fail()` calls `exit 1` and
   would abort the preflight, which is exactly the FR-9 violation E-2 defers.
2. **It must contain no bare failing command.** `validate_setup.sh` runs under `set -euo pipefail`, and `set
   -e` is *not* disabled inside a function body merely because the call site is a conditional — only the
   function's own final status is protected. Every command that can fail must sit inside a conditional or be
   `|| true`-guarded.
3. **The command-substitution capture must not be combined with `local`.** `local out="$(cmd)"` makes `$?` the
   exit status of `local`, silently discarding the generator's exit code — this is the single most likely bug
   in the whole component. Declare first, assign second:

   ```
   local out rc
   out="$(python3 "$gen" --role "$role" --clone-dir "$repo" --check 2>&1)" && rc=0 || rc=$?
   ```

   The `&& rc=0 || rc=$?` form is safe under `set -e` because the whole statement is an AND-OR list, and `$?`
   at the `||` arm is the command substitution's status (the `&&` arm did not run).

**Body sequence:**

1. `local gen="$repo/scripts/framework/gen_sandbox_config.py"`.
2. If `[[ ! -f "$gen" ]]`: print the **broken-checker** message (class D below) and `return 1`. This test comes
   first so that a missing generator can never be confused with `python3`'s own exit `2`.
3. Capture `out`/`rc` as above. `2>&1` folds the generator's stderr into the captured text so nothing is lost;
   the function decides what reaches the terminal.
4. `case "$rc" in` → the four message classes:

| `rc` | Class | Output | Return |
|---|---|---|---|
| `0` | current | `ok "Sandbox policy current (contract/sandbox-policy.template.json)"` — uses the existing `ok()` helper, so `--quiet` is honored | `0` |
| `1` | **divergent** | **Loud, on stderr**: a `WARN: SANDBOX POLICY DIVERGENT` headline, then `$out` verbatim (it already contains the diverging rules and the regenerate command, §6.5), then "session continues — this is a warning, not a block". | `1` |
| `6` | **not enrolled** | One line on stderr: "note: this clone's sandbox policy was never generated — it is hand-maintained (no `.claude/hos-sandbox.values`). Enroll with: `scripts/framework/gen_sandbox_config.py --role <role> --clone-dir <repo> …`". | `1` |
| `2`,`3`,`4`,`5`, and **anything else** (incl. `126`/`127`) | **broken checker** | On stderr: "WARN: sandbox config CHECK FAILED (exit `$rc`) — the check did not run. **Policy status is UNKNOWN — this does not mean the policy is fine.**" then `$out`. | `1` |

Class D's wording is not decoration. AD-6.4: "silence on a broken checker is how a control becomes
decorative", and a message implying the policy is fine when the checker crashed is worse than none. The
catch-all arm is also why §4 requires `main()` to never leak a bare `1` from an unhandled exception — a
traceback exiting `1` would be reported as *divergence* instead of *broken*.

### 9.3 Insertion point

Immediately **after** the existing `── 4. Git repo sanity ──` block (ends at `validate_setup.sh:80`) and
**before** `echo "=== Preflight PASSED ==="` (line 82). New section header comment
`# ── 5. Sandbox policy currency (opt-in: --role) ──`.

Call site — AD-6.3's literal shape:

```
if [[ -n "$SANDBOX_ROLE" ]]; then
  if ! sandbox_config_check "$SANDBOX_ROLE" "$REPO_ROOT"; then
    echo "  WARN: sandbox policy check reported a problem (see above) — session continues." >&2
  fi
fi
```

The function definition goes next to the other helpers (after `ok()` on line 28) or immediately above the
section; either is acceptable, but it must be defined before use.

**`=== Preflight PASSED ===` and the terminating `exit 0` are unchanged** (AD-6.5). E-2 stays deferred: a
stale sandbox config does **not** block session start.

### 9.4 `bin/hos-human`

One argument added at line 25-26. Current:

```
bash "$REPO_ROOT/bootstrap/validate_setup.sh" --repo "$REPO_ROOT" \
  || { echo "Preflight failed -- fix setup before starting a session"; exit 1; }
```

becomes the same two lines with `--role human` appended to the first. Nothing else in the launcher changes.
This is a **declaration** by the one launcher that is definitionally the Human launcher — not an inference, so
FR-2 holds (AD-6.2). Add a one-line comment above it saying the flag enables the opt-in sandbox-policy
currency check and that a divergence warns without blocking.

### 9.5 Rollback

Revert the single `--role human` on `bin/hos-human:25`. The hook then never runs anywhere. Stated in the PR
body per the ADR's rollback note.

### 9.6 Consumer-projection note (verified, and deliberately left as-is)

`bootstrap/validate_setup.sh` **is** installed into consumer projects
(`bootstrap/hos_install.sh:1814-1815`), so the new `--role` argument ships. `gen_sandbox_config.py` is **not**
added to `scripts/framework/framework_consumer_files.txt` — #1221 is HOS-operational, not a consumer feature
(SPEC §2). Consumer behavior is byte-identical because nothing consumer-side passes `--role`; and a consumer
who passed it anyway would get class D's non-blocking "generator missing / status unknown" warning, never a
failed preflight. Recorded so a reviewer does not read the omission as an oversight.

---

## 10. Component 4 — tests

**One test file:** `tests/framework/test_gen_sandbox_config.py`.

Conventions to follow (from `tests/framework/test_require_human_approval.py:6-18`): load the module via
`importlib.util.spec_from_file_location` + `module_from_spec` + `exec_module`, resolving the path as
`Path(__file__).resolve().parents[2] / "scripts" / "framework" / "gen_sandbox_config.py"`. Use `tmp_path` for
every filesystem test. Call `mod.main([...])` directly for exit-code assertions (fast, coverage-visible);
reserve `subprocess` for the `validate_setup.sh` tests, which are inherently shell. **No test may be marked
`slow` or `integration`** — the whole file must run in `run_tests_inner_loop.sh`. Module docstring must state
the §0.2 synthetic-fixture provenance.

Helper fixtures inside the file: `_fixture_values()` (§7.2's seven values as a dict), `_clone(tmp_path)`
(makes `<tmp>/clone/.claude/`), `_gen_args(clone, **overrides)` (builds the flag list), `_write_template(text)`.

| # | Test function | Asserts | AC / AD |
|---|---|---|---|
| 1 | `test_check_detects_divergence_then_passes_after_generate` | On a clone with a stale live file + a generated sidecar: `--check` → `1`; run generate `--force`; `--check` → `0`. **The criterion that actually matters** — proves the check can fail. | AC1a, VF-4 |
| 2 | `test_role_worker_refused_naming_1146` | exit `3`; captured stdout/stderr contains `#1146`. | AC2, FR-5 |
| 3 | `test_role_overseer_refused_naming_1146` | exit `3`; `#1146` present. | AC2, FR-5 |
| 4 | `test_unsupported_role_exits_before_any_filesystem_access` | `--role worker` with a **nonexistent** `--clone-dir` still exits `3` (not `2`), and an `open` audit records no file opened. | AD-4 |
| 5 | `test_unknown_role_is_usage_error_not_unsupported_role` | `--role admin` → `2`, distinct from `3`. | AD-4 |
| 6 | `test_surviving_placeholder_hard_fails_and_writes_nothing` | Misspelled placeholder in the template → exit `5`; **no live file exists**; **no `.tmp-hos-sandbox-*` remains** in the target dir; no sidecar. | AC3, AD-3 |
| 7 | `test_malformed_template_hard_fails_and_writes_nothing` | Invalid JSON template → `5`, nothing written. | AC3 |
| 8 | `test_missing_required_value_is_usage_error` | Omit `--handoff-dir` → `2`; message names the flag; nothing written. | AD-5, §0.1 |
| 9 | `test_generated_is_semantic_superset_of_pre_existing_live` | Every `deny` in `pre-existing-live-human.json` appears in generated output. **No deny is ever removed.** | AC4 |
| 10 | `test_delta_table_matches_expected` | Computed additions/removals equal §8.4 exactly: 5 deny additions, exactly one removal (`Bash(claude *)`, an `allow`), zero deny removals. | AC4, AD-8 |
| 11 | `test_fixtures_contain_no_operator_paths` | No fixture under `tests/framework/fixtures/sandbox/` contains `/home/scott`, `HumanOversightSystem`, or any prefix listed in `scripts/framework/installer-internal-paths.txt`. | AD-9 sanitization |
| 12 | `test_generate_twice_is_byte_identical` | Two generates → identical bytes. | AC5 |
| 13 | `test_shuffled_template_key_order_produces_identical_output` | Template with recursively shuffled dict keys → byte-identical output. | AC5, AD-9 |
| 14 | `test_array_order_is_preserved_not_sorted` | A template array's order survives into the output verbatim. | §6.4 |
| 15 | `test_overwrite_without_force_refuses_and_leaves_file_unmodified` | Pre-existing live file → exit `4`; its bytes and mtime unchanged; no backup created. | AC6, FR-7 |
| 16 | `test_overwrite_with_force_creates_backup_of_prior_content` | After `--force`, a `settings.local.json.bak-*` exists whose content equals the **prior** file, not the new output. | AC6, AD-3.3 |
| 17 | `test_check_with_force_is_usage_error` | `--check --force` → `2`. | AD-4 |
| 18 | `test_render_has_no_live_path_parameter` | `inspect.signature(mod.render)` has exactly `(template_text, values)` — no path parameter exists through which the live file could enter. | AD-1, AD-9 |
| 19 | `test_generate_output_independent_of_live_file` | Two clones, identical flags; one has a live file with extra allow+deny entries, the other has none → byte-identical generated output. | AD-1, AD-9 |
| 20 | `test_generate_does_not_read_live_file_when_absent` | Patch `builtins.open` to record paths; generate into a clone with no live file → the live path is never opened. | AD-1, AD-9 |
| 21 | `test_values_file_absent_is_distinct_from_divergence` | `--check` with no sidecar → exit `6`, **not** `1`; message says "never generated"/"hand-maintained". | AD-5 |
| 22 | `test_values_file_written_with_all_seven_keys_and_meta` | After generate: sidecar exists; all seven placeholder keys present with the expected values; `META_VALUES_VERSION=1`; keys in `PLACEHOLDERS` order. | AD-5 |
| 23 | `test_check_needs_no_value_flags` | `--role human --clone-dir <c> --check` alone (no value flags) exits `0` on a freshly generated clone — the property AD-6 depends on. | AD-5, VF-7 |
| 24 | `test_incomplete_values_file_is_hard_failure_not_not_enrolled` | Sidecar missing one key → `5`, not `6`. | §5.2 rule 7 |
| 25 | `test_values_file_role_mismatch_is_hard_failure` | Sidecar `ROLE=worker` with `--role human` → `5`. | §5.2 rule 10 |
| 26 | `test_check_reports_live_file_missing_as_divergence` | Sidecar present, live file deleted → `1` with the dedicated message. | §6.5 |
| 27 | `test_check_reports_surviving_placeholder_in_live_file` | Live file containing `__HANDOFF_DIR__` → `1`; report names `#1114`. | FR-6 |
| 28 | `test_echo_back_prints_every_placeholder_with_source` | All seven names appear in stdout, each with a `[flag]`/`[derived]`/`[env]`/`[values-file]` tag. | AD-4 |
| 29 | `test_exit_codes_are_distinct` | The seven exit-code constants are pairwise distinct and equal `0..6`. | AD-4 |
| 30 | `test_module_docstring_documents_exit_codes` | The docstring names all seven codes — AD-4 makes header documentation a requirement, so it is asserted. | AD-4 |
| 31 | `test_template_has_six_force_push_denies` | The committed template's `deny` contains exactly §8.2's six spellings. | AD-8 |
| 32 | `test_template_retains_plus_refspec_deny` | `Bash(git push* +*)` present — a named regression guard for VF-5. | AD-8 |
| 33 | `test_template_has_three_bin_deny_spellings` | All three §8.1 `bin` spellings present. | FR-11 |
| 34 | `test_template_denies_values_sidecar_all_spellings` | All three values-sidecar spellings present. | AD-5 |
| 35 | `test_template_does_not_allow_bash_claude` | `Bash(claude *)` absent from `allow`. | FR-13 |
| 36 | `test_template_substitutes_with_no_surviving_placeholders` | Rendering the **committed** template with the fixture values leaves no `__NAME__`. Guards a future template edit that adds an eighth placeholder without a flag. | FR-6 |
| 37 | `test_gitignore_covers_values_file_and_backups` | `.gitignore` contains both §5.4 entries. | VF-8 |
| 38 | `test_validate_setup_role_human_reports_divergence_and_exits_zero` | `bash bootstrap/validate_setup.sh --repo <tmp clone> --role human` on a prepared divergent tree: **stderr contains the divergence report AND the exit code is 0.** Both halves — asserting only the code would pass on a hook that prints nothing. | AC7, AD-9 |
| 39 | `test_validate_setup_without_role_does_not_run_check` | Same tree, no `--role`: exit `0`, and stderr contains **no** sandbox text — proving default-skip and that the worker/overseer/cron paths are untouched. | AD-6.1 |
| 40 | `test_validate_setup_reports_not_enrolled_distinctly` | Clone with no sidecar → stderr says "never generated"/"hand-maintained", **not** "divergent"; exit `0`. | AD-6.4 |
| 41 | `test_validate_setup_reports_broken_checker_distinctly` | Generator file absent → stderr says the **check** failed and status is UNKNOWN; must **not** contain any wording implying the policy is current; exit `0`. | AD-6.4 |

Tests 38-41 need a tmp tree that satisfies the four pre-existing preflight sections (agents dir with the nine
required agent files, an executable `bootstrap/get_app_token.sh` stub, an `apps.env` reachable via
`HOS_CONFIG_DIR`, a git repo with an `origin` remote). Build it with a single module-level helper
`_preflight_tree(tmp_path)` so the four tests share it; `git init` + `git remote add origin <url>` is
sufficient and fast.

---

## 11. Documentation and record-keeping

### 11.1 `docs/SANDBOX-POLICY.md`

Three edits, all required by the ADR's startup-gap analysis:

1. **Status block (lines 6-13):** add that the template is now **generatable for `human`** via
   `scripts/framework/gen_sandbox_config.py`, and that `bin/hos-human`'s preflight warns (non-blocking) when
   the live file diverges. **Keep** the existing sentence "It is not yet installed by `hos_install.sh`, and it
   is not yet applied to `worker` or `overseer`" — both remain true (AD-1 does not touch the installer; FR-5
   refuses the other two roles).
2. **§4 item 6 ("Placeholder substitution must fail closed"):** mark **discharged by #1221 / AD-3** — the
   generator hard-fails on a surviving `__` before any filesystem write. **§4 item 7 stays open** (glob
   semantics remain unverified); append a note that the reconciliation now emits three `bin/**` and six
   force-push spellings precisely *because* item 7 is unresolved, and that the redundancy may be pruned when
   #1146 verifies the matcher. Add the §8.1 observation about the `settings*.json` deny spellings as a new
   item routed to #1146.
3. **§5 Placeholders table (lines 230-238):** add a third column giving each placeholder's generator flag and
   default/required status (§3.2), so the glossary and the CLI cannot drift.

### 11.2 PR body

Must carry: the §8.4 delta table (computed by test 10, showing **six** force-push denies); the AC1b manual
transcript from the live Human clone (§0.1, operator-supplied at first `--force` run); the §9.5 rollback line;
and an explicit statement that the AC4 fixture is synthetic (§0.2).

### 11.3 `DECISIONS.md`

One dated, appended entry (the file is append-only, new entries at the bottom) recording the design decisions
this document locks in that a future reader would otherwise have to reverse-engineer: the seven exit codes; the
values sidecar as the mechanism that makes `--check` reproducible without flags; and **generate mode not
reading the sidecar** (§5.3), which is the non-obvious one.

---

## 12. Traceability

| Requirement | Where satisfied |
|---|---|
| FR-1 single entry point, two modes | §2, §3 |
| FR-2 role + clone explicit, no inference | §3.1, §3.2 note, §9.4 |
| FR-3 no setup-script wiring | §1 "not touched" |
| FR-4 role-driven substitution only | §3.2, §6 (`substitute`) |
| FR-5 worker/overseer fail closed naming #1146 | §2.4 `SUPPORTED_ROLES`, §6 `gate_role`, exit `3`, tests 2-3 |
| FR-6 surviving `__` hard-fails, no partial file | §6 `render`/`find_surviving_placeholders`, §6.6 step 10, §6.5 case 3, tests 6, 27, 36 |
| FR-7 refuse overwrite; backup on `--force` | §3.4, §6.6 `run_generate` 2-3, §6.8, tests 15-16 |
| FR-8 `--check` non-zero + rule-level divergence | §6.5, exit `1`, tests 1, 26 |
| FR-9 preflight warns loudly, does not block | §9, tests 38-41 |
| FR-10 no CI workflow | §1 "not touched" |
| FR-11 three `bin/**` spellings + source comment | §2.3, §8.1, test 33 |
| FR-12 force-push union | §8.2, test 31 |
| FR-13 `Bash(claude *)` not carried | §8.3, test 35 |
| FR-14 template is the tracked source of truth | §8 (whole) |
| AD-1 pure function; never reads live file | §2.1, §5.3, §6.6, tests 18-20 |
| AD-2 Python, no wrapper, stdlib | §2 |
| AD-3 validate-before-write + atomic + backup | §6.6 step 10, §6.7, §6.8 |
| AD-4 CLI shape, exit classes, echo-back | §3, §4 |
| AD-5 values, defaults, sidecar, `.gitignore`, deny | §0.1, §3.2, §5, §8.1 |
| AD-6 opt-in `--role` hook | §9 |
| AD-7 provenance reported not embedded | §3.6 |
| AD-8 six force-push spellings | §8.2 |
| AD-9 re-specified ACs + fixture | §0.2, §7, §10 |

---

## Human Review Required

**RISK: MEDIUM** — inherited from SPEC-1221 and ADR-1221, unchanged. The artifact under design is a security
boundary, and the residual risk is concentrated in the **under-blocking** direction, where failure is
invisible: a `--check` that can only pass (closed by §2.1/§5.3 and tests 18-20), a hook that reports nothing
(closed by §9.2 class D and tests 38-41), and a crash misreported as divergence (closed by §4's rule that
`main()` never leaks a bare exit `1`).

**CONFIDENCE: HIGH** on everything read against this working tree: `contract/sandbox-policy.template.json` in
full (all 205 lines, line numbers cited), `bootstrap/validate_setup.sh` in full, `bin/hos-human`,
`scripts/automation/lib/overseer_state.py:48-63`, `scripts/framework/require_human_approval.py`,
`strip_internal_paths.sh` + `installer-internal-paths.txt`, `framework_consumer_files.txt`,
`hos_install.sh:1814-1815`, `run_tests_inner_loop.sh`, `pyproject.toml`, `tests/conftest.py`,
`tests/framework/test_require_human_approval.py`, `.gitignore:39-48`.
**LOWER**, and deliberately so, on two points — both **designed around rather than guessed at**:
(a) the ground-truth `__HANDOFF_DIR__` / `__CLAUDE_PROJECT_STATE__` values, which I could not read from this
clone and have therefore left as required-explicit operator input (§0.1, ADR N1); and (b) the AC4 fixture,
which is a synthetic reconstruction rather than a production capture (§0.2). Both deviations from the ADR's
literal instruction are stated on the record here rather than papered over. Glob-matching semantics remain
unverified (`docs/SANDBOX-POLICY.md` §4 item 7) and every decision above is chosen to be safe under that
uncertainty.

**BLAST RADIUS:** the Human clone's live sandbox config; one new stderr path at Human session start; a
reconciled tracked template. No consumer project (§9.6), no autonomous role, no cron path (AD-6.1). Rollback is
§9.5 plus the FR-7 backup.

**Change classification: ADDITIVE.** A new generator, a new optional argument on an existing preflight, two
additive `.gitignore` entries, and additive-only deny entries in an already-tracked template. Nothing existing
changes behavior except `bin/hos-human`, which gains one argument. The two structural questions (E-1
`settings.json` generation, E-2 blocking session start) remain deferred to the human exactly as pm-agent and
the architect left them; **nothing in this design pre-empts either.**

**Startup-gap analysis (CORE discipline).** This is the **initial** technical design for #1221. No prior
technical design covers this surface and **no design or code sign-off exists against any superseded contract —
no sign-off is orphaned and none requires re-review.** Three decisions in this document extend the ADR rather
than restate it, and are flagged here so the architect can accept or reject them explicitly: **(1)** a seventh
exit code `6` for "not enrolled", which AD-5 requires as a distinct outcome but AD-4's six-class list does not
contain; **(2)** three deny spellings for the values sidecar rather than one, applying FR-11's reasoning to the
file AD-5 requires be denied; **(3)** generate mode does **not** read the values sidecar (§5.3), making the
sidecar strictly check-mode state. Each is stricter or narrower than the alternative; none loosens an ADR
constraint.

**Requested next step:** `architect` review of this draft (iteration 1 of a 5-round cap). Not to be handed to
`coder` until approved.
