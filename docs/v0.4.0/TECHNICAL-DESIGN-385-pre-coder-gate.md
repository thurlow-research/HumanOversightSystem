# Technical Design — Issue #385: check_pre_coder_gate.sh

**Document type:** Technical design
**Status:** Approved (architect bindings OQ-385-A..D applied)
**Issue:** #385
**Spec:** `docs/specs/SPEC-385-pre-coder-gate-script.md`
**Date:** 2026-06-16
**Author:** technical-design

---

## 0. Architect bindings applied

| Binding | Decision | Effect on design |
|---|---|---|
| OQ-385-A | Validate slug against `^[a-z0-9]+(-[a-z0-9]+)*$`. Exit 2 on violation. Do **not** normalize. | §3 slug validation; no lowercasing, no trimming. |
| OQ-385-B | `.claudetmp/design/` is always resolved relative to git root; not configurable. | §6 condition 3 path is `${ROOT}/.claudetmp/design/`. |
| OQ-385-C | Script is standalone. It is **not** invoked from `run_tests_inner_loop.sh`. The **unit test** is collected by the inner-loop runner. | §8 — no runner edit; test is a pytest file under `tests/framework/`. |
| OQ-385-D | Staged-but-not-committed counts as **not committed**; the gate fails. | §5/§6 — `git ls-files --error-unmatch` is the committed predicate (it returns 0 for tracked-and-committed; a never-committed staged add is still listed by `ls-files`, so see §5.1 for the exact predicate). |

> **OQ-385-D precision (design-critical, resolves a spec ambiguity).** `git ls-files`
> lists files in the **index**, which includes a staged-but-never-committed `git add`.
> So `git ls-files --error-unmatch <path>` alone returns 0 for a staged-only file and
> would *wrongly pass*. To honor OQ-385-D ("staged-but-not-committed = not committed,
> gate fails") the committed predicate must verify the path exists **in the committed
> tree of HEAD**, not merely in the index. The design uses
> `git ls-tree -r --name-only HEAD -- <path>` (see §5.1). This is a refinement of the
> spec's `git ls-files` wording, made to satisfy the binding; it is recorded as a
> `clarifying` change.

---

## 1. Contract summary

`scripts/framework/check_pre_coder_gate.sh <feature-slug>`

| Exit | Meaning | Stream |
|---|---|---|
| 0 | All three conditions satisfied. One `[GATE PASS]` line. | stdout |
| 1 | One or more conditions unmet. One `[GATE FAIL]` line per unmet condition; **all three** evaluated before exit. | stderr |
| 2 | Usage error: no args / >1 positional arg / unknown flag / malformed slug / not in a git repo. | stderr |
| 0 | `--help` / `-h`: prints usage, exits 0. | stdout |

The script honors `set -euo pipefail` semantics but **must not** let an expected non-zero
from a probe (e.g. `git ls-tree` finding nothing) abort the script — each probe is captured
and its status inspected explicitly (see §5.1). The script must evaluate all three conditions
even when the first fails (REQ-385-06): use a per-condition `fail` accumulator, not early `exit`.

---

## 2. File-level structure (what the script must contain, not the code)

Ordered top-to-bottom:

1. Shebang `#!/usr/bin/env bash` (REQ-385-03).
2. `set -euo pipefail`.
3. A `usage()` function emitting the interface block from §1 to stdout.
4. Argument/flag parsing (§3).
5. Slug validation (§3).
6. Git-root resolution (§4).
7. Three condition checks, each appending to a `failures` array (§5, §6).
8. Result emission and exit (§7).

The script is self-contained — no sourcing of `config.sh` or other framework files
(OQ-385-C standalone). It uses only `git`, bash builtins, and `grep`/`tail` for §6.

---

## 3. Argument & flag handling

**Inputs:** the positional `$@`.

Algorithm (must honor REQ-385-07, 08, 02; OQ-385-A):

1. If `$1` is `--help` or `-h` → print `usage()` to **stdout**, exit 0.
2. If `$1` begins with `-` (any other flag, e.g. `--foo`, `-x`) → error `[USAGE] unknown flag: <flag>` to stderr, exit 2.
3. If the count of positional arguments `!= 1` (zero, or two-or-more) → error `[USAGE] expected exactly one <feature-slug> argument` to stderr, exit 2.
4. Let `slug="$1"`. Validate `slug` against the anchored regex `^[a-z0-9]+(-[a-z0-9]+)*$`
   (bash `[[ "$slug" =~ ... ]]`). On no match → error
   `[USAGE] invalid slug '<slug>' (must match ^[a-z0-9]+(-[a-z0-9]+)*$)` to stderr, exit 2.
   **Do not normalize** (no lowercasing, no trimming) — reject as-is (OQ-385-A).

**Boundary the script must honor:** the regex forbids `/`, spaces, leading/trailing/double
hyphens, uppercase, and the empty string. This makes the glob-injection surface in §6 inert
(slug can never contain a glob metacharacter or path separator).

---

## 4. Git root resolution (REQ-385-22, 23; OQ-385-B)

1. `ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"`.
2. If that command failed (non-zero) or `ROOT` is empty → error
   `[USAGE] not inside a git repository` to stderr, exit 2.
3. `cd "$ROOT"` so every subsequent path and git invocation is git-root-relative,
   regardless of the caller's cwd. (This is what makes the REQ-385-27 "invoked from a
   subdirectory" case pass.)

All three conditions below assume cwd == git root.

---

## 5. Committed-status predicate (shared by conditions 1 & 2)

### 5.1 The predicate

A path P is **committed** iff it appears in the tree of `HEAD`:

```
git ls-tree -r --name-only HEAD -- <P>   →  non-empty stdout
```

- Empty stdout (or non-zero exit) ⇒ **not committed** (covers: absent, untracked,
  staged-only/never-committed). This satisfies OQ-385-D: a staged-only file is in the
  index but **not** in `HEAD`'s tree, so it reads as not committed and the gate fails.
- For condition 2 the argument to `ls-tree` is a **pathspec glob**
  `docs/v*/TECHNICAL-DESIGN-<slug>.md`; `ls-tree -r ... -- <glob>` expands against the
  committed tree and prints each committed match. ≥1 line ⇒ committed match exists.

**Edge — no commits yet (unborn HEAD):** `git ls-tree HEAD` fails when HEAD has no commit.
Treat a failed `ls-tree` as "not committed" (empty result), not as a script error. Capture
status explicitly so `set -e` does not abort:
`out="$(git ls-tree -r --name-only HEAD -- "$P" 2>/dev/null || true)"`.

### 5.2 Disk-presence predicate

Condition 1 (REQ-385-09) and condition 2 (REQ-385-12) also require **disk presence** and the
error message (REQ-385-14) must distinguish absent vs present-but-uncommitted.

- Condition 1 disk check: `[[ -f "docs/specs/SPEC-<slug>.md" ]]`.
- Condition 2 disk check: glob `docs/v*/TECHNICAL-DESIGN-<slug>.md` expands (via bash, with
  `shopt -s nullglob` set locally) to ≥1 existing file. `nullglob` ensures a non-matching
  glob yields an empty array rather than a literal pattern.

---

## 6. Condition algorithms

For each condition the script computes a boolean and, on failure, appends one or more
`[GATE FAIL]` lines (exact format in §7) to the `failures` array. **No early exit.**

### Condition 1 — Spec committed (REQ-385-09..11)

- `SPEC="docs/specs/SPEC-<slug>.md"`.
- disk = §5.2 file test on `SPEC`.
- committed = §5.1 predicate on `SPEC`.
- **Pass** iff `disk && committed`. (Disk presence is implied by committed, but the spec
  requires the on-disk check explicitly and it drives the error wording.)
- Fail line: `[GATE FAIL] SPEC: <SPEC> not found or not committed`.

### Condition 2 — Technical design committed (REQ-385-12..14)

- `TD_GLOB="docs/v*/TECHNICAL-DESIGN-<slug>.md"`.
- disk_matches = expansion of `TD_GLOB` under `nullglob` → array.
- committed = §5.1 predicate using `TD_GLOB` as the `ls-tree` pathspec → ≥1 line.
- **Pass** iff `committed` (≥1 committed match). Per REQ-385-12, ≥1 disk match is required;
  but since "committed" implies "on disk in the committed tree", a committed match is the
  controlling condition. The disk array drives the absent-vs-uncommitted error wording.
- Fail lines (REQ-385-14 — state which):
  - if `disk_matches` empty: `[GATE FAIL] TECH-DESIGN: no file matching <TD_GLOB> (absent)`.
  - else (on disk but not committed): `[GATE FAIL] TECH-DESIGN: <TD_GLOB> present on disk but not committed`.

### Condition 3 — No open REQUEST_CHANGES (REQ-385-15..19; OQ-385-B)

- `AR_GLOB=".claudetmp/design/architect-<slug>-*.md"` (relative to git root — OQ-385-B;
  not configurable, do **not** also probe `.claudetmp/` directly).
- matches = expansion of `AR_GLOB` under `nullglob`.
- **If matches is empty → condition 3 PASSES** (REQ-385-18). No fail line.
- For each matching file F:
  1. Extract the **last** line whose trimmed content matches `status:` case-insensitively
     on the key. Algorithm:
     `last="$(grep -iE '^[[:space:]]*status:' "$F" | tail -n 1)"`.
     - `grep -i` makes the key match case-insensitive; anchoring `^[[:space:]]*status:`
       avoids matching `status:` appearing mid-line in prose.
     - `tail -n 1` selects the **last** such line (REQ-385-16 / AC-385-07 last-line semantics).
     - If no `status:` line exists in F, F contributes no failure (it carries no verdict).
  2. Parse the value: strip the `status:` key, trim surrounding whitespace, compare the
     value **case-insensitively** to `request_changes`.
     (e.g. lowercase the value via `${val,,}` and compare to `request_changes`.)
  3. If the value equals `request_changes` → append
     `[GATE FAIL] ARCHITECT: <F> has status: REQUEST_CHANGES`.
- **Condition 3 fails** iff ≥1 matching file yields a REQUEST_CHANGES last-status (REQ-385-17).
  A file whose last status is `APPROVED` passes even if an earlier line said REQUEST_CHANGES
  (AC-385-07).

**Boundary the script must honor:** condition 3 reads only files under
`.claudetmp/design/`; it must not read arbitrary paths. The slug regex (§3) guarantees the
glob cannot escape that directory.

---

## 7. Result emission & exit (REQ-385-04..06, 20, 21)

- If `failures` array is empty:
  - stdout: `[GATE PASS] pre-coder gate satisfied for slug: <slug>`
  - exit 0.
- Else:
  - Print every element of `failures` to **stderr**, one per line, in condition order
    (SPEC, then TECH-DESIGN, then ARCHITECT). Each begins with `[GATE FAIL]` (REQ-385-20).
  - exit 1.

Usage errors (§3, §4) print `[USAGE] ...` to stderr and exit 2 — these are distinct from
`[GATE FAIL]` and short-circuit before condition evaluation.

---

## 8. worker.md CORE edit (REQ-385-24, 25)

The current worker.md CORE has **no** prose pre-coder checkbox list; the only pre-coder
prose is the clean-working-tree precheck at build-chain step 8. Per REQ-385-24/25 the
gate invocation is added there as a sibling sub-bullet, immediately after the clean-tree
precheck and **before** any coder dispatch. This is an **additive** CORE edit (it adds a
mechanical gate; it removes no existing safety behavior).

New sub-bullet under step 8 (CORE region):

> - **Pre-coder gate (mechanical — blocks coder dispatch).** Before dispatching coder for
>   `<feature-slug>`, run `bash scripts/framework/check_pre_coder_gate.sh <feature-slug>`.
>   If exit != 0: read the `[GATE FAIL]` lines and dispatch the missing pipeline agent —
>   `pm-agent` for a missing/uncommitted spec, `technical-design` for a missing/uncommitted
>   technical design, `architect` for an open `REQUEST_CHANGES` verdict — then re-run the
>   gate. Do **not** dispatch coder until the gate exits 0.

The edit lands inside `<!-- HOS:CORE:START --> ... <!-- HOS:CORE:END -->` and ships in the
same commit as the script (REQ-385-25, AC-385-13).

---

## 9. Unit test design (REQ-385-26..28; OQ-385-C)

**Location:** `tests/framework/test_pre_coder_gate.py` (collected by
`run_tests_inner_loop.sh` via pytest; the script itself is NOT added to the runner — OQ-385-C).

**Mechanism (REQ-385-28):** each test builds an isolated temporary git repo in a `tmp_path`
fixture and shells out to the script via `subprocess.run`. No test may depend on the real
working tree. Pattern per test:

1. `git init` in `tmp_path`; set `user.email`/`user.name` (or pass `-c` config) so commits
   succeed in CI.
2. Create the relevant `docs/specs/`, `docs/vX/`, `.claudetmp/design/` files.
3. To make a file "committed": `git add` + `git commit`. To make it "staged only":
   `git add` and **do not commit** (exercises OQ-385-D). To make it "absent": skip creation.
4. Invoke `subprocess.run(["bash", SCRIPT, slug], cwd=<repo or subdir>, capture_output=True,
   text=True)`.
5. Assert on `returncode` and on substrings of `stdout`/`stderr` (`[GATE PASS]`,
   `[GATE FAIL] SPEC`, etc.).

`SCRIPT` is resolved as `Path(__file__).resolve().parents[2] / "scripts" / "framework" /
"check_pre_coder_gate.sh"` (mirrors the existing `test_require_human_approval.py` pattern).

**Required cases (REQ-385-27, AC-385-11), one test function each:**

| Test | Setup | Assert |
|---|---|---|
| all pass | spec committed, TD committed, no architect file | rc 0, `[GATE PASS]` |
| C1 absent | no spec; TD committed | rc 1, `[GATE FAIL] SPEC` |
| C1 staged-only | spec `git add` only; TD committed | rc 1, `[GATE FAIL] SPEC` (OQ-385-D) |
| C2 no glob match | spec committed; no TD file | rc 1, `[GATE FAIL] TECH-DESIGN` |
| C2 staged-only | spec committed; TD `git add` only | rc 1, `[GATE FAIL] TECH-DESIGN` |
| C3 REQUEST_CHANGES last | spec+TD committed; architect file last status REQUEST_CHANGES | rc 1, `[GATE FAIL] ARCHITECT` |
| C3 APPROVED-after-RC | architect file with `status: REQUEST_CHANGES` then later `status: APPROVED` | rc 0, `[GATE PASS]` (last-line semantics) |
| C3 no architect file | spec+TD committed, no architect file | rc 0 |
| no args | invoke with `[]` | rc 2 |
| subdir invocation | make a subdir, run with `cwd=subdir`, gate otherwise passes | rc 0 (git-root resolution) |

**Additional cases (recommended, not spec-mandated but cheap and load-bearing):**

| Test | Assert |
|---|---|
| invalid slug (`Foo Bar`, `a/b`, `--`) | rc 2 (OQ-385-A; one test, parametrized) |
| two positional args | rc 2 |
| unknown flag `--nope` | rc 2 |
| not a git repo (tmp dir without `git init`) | rc 2 |
| all-three-fail reports all 3 lines | rc 1 and stderr contains SPEC + TECH-DESIGN + ARCHITECT lines (REQ-385-06 no short-circuit) |
| `--help` | rc 0, usage on stdout |

Mark none `@slow`/`@integration` — these run in the inner loop (AC-385-12).

---

## 10. Traceability

| Requirement | Where satisfied |
|---|---|
| REQ-385-01..03 | §2 |
| REQ-385-04..06 | §1, §6 (accumulator), §7 |
| REQ-385-07, 08 | §3 |
| REQ-385-09..11 | §6 C1, §5 |
| REQ-385-12..14 | §6 C2, §5 |
| REQ-385-15..19 | §6 C3 |
| REQ-385-20, 21 | §7 |
| REQ-385-22, 23 | §4 |
| REQ-385-24, 25 | §8 |
| REQ-385-26..28 | §9 |
| OQ-385-A | §3 |
| OQ-385-B | §6 C3 |
| OQ-385-C | §8 note, §9 |
| OQ-385-D | §0 note, §5.1 |

---

## Human Review Required

**Change classification:** `clarifying` — the design adds one detail beyond the spec
(the §5.1 committed predicate uses `git ls-tree HEAD` instead of the spec's literal
`git ls-files`) solely to honor binding OQ-385-D; all other content is a direct
restatement of the spec's contract. The worker.md edit is `additive` (adds a gate,
removes no safety behavior). No `structural` change → no pre-write human escalation
required.

**RISK:** LOW — single standalone read-only shell script + one additive CORE prose
bullet + an isolated unit test. No production data path, no network, no credential
surface. The only non-obvious decision (ls-tree vs ls-files) is bound by the architect.

**CONFIDENCE:** HIGH — all four open questions are resolved by architect bindings; the
test matrix exercises each binding directly.
