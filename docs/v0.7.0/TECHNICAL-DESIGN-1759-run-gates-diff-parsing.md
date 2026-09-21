# TECHNICAL DESIGN — #1759: `run_gates.sh --diff` parsing, fail-closed gate argument grammar, and the empty-file-set audit

**Issue:** #1759 (`priority:critical`, milestone v0.7.0 — Quality)
**Slice:** issue scope items **1–4**. Item 5 and the "Related observation" (whole-file vs. hunk
scanning) are **out of scope** — see §11.
**Status:** REVISED — iteration 2, incorporating coordinator rulings **A–H** and the
three-case empty-set constraint (2026-09-21). One residual risk is flagged for decision in §13
(**RISK-1**); everything else is settled.
**Change classification:** `structural` for the gate argument grammar and exit-code contract
(§4.4, approved by Ruling B); `additive` for the remainder.

### Rulings applied (not re-litigated)

| Ruling | Effect on this document |
|---|---|
| **A** | Unknown-argument handling is split by *shape*: flag-shaped → fatal; path-shaped-but-missing → warn and drop, with the empty-set rule as the backstop. No CI workflow change in this slice. §3 TD-D13, §4.4. |
| **B** | Exit codes 2 (usage) and 3 (resolution) are **in scope**. §4.4. |
| **C** | `secret_scan`'s `--staged` extension filter is **not** removed here. §12. |
| **D** | No change to `pr_readiness.py`. §7 row 3 discloses the one branch where its *conclusion* still changes, and why that is AC-3 itself rather than a rider. |
| **E** | `run_validators.sh`'s stale `--step` header is not fixed here; the divergence is documented. §3 TD-D6, §12. |
| **F** | `--all` plus explicit paths is a **usage error**. Grep evidence in §3 TD-D11. |
| **G** | `collection_integrity`'s exemption is explicit and **tested**. §6 row 10, §9.3 TC-G8. |
| **H** | The `HOS_DETECT_SECRETS_BIN` seam is taken, off by default. §6 row 6, §9.4 TC-P5. |
| **I** | A missing path is **classified**, not uniformly dropped: tracked ⇒ deletion (drop, case-2 eligible); never tracked ⇒ fabricated (**fatal 3, immediately, on the first bad path**); shallow/undecidable ⇒ degraded drop. The decision lives in Python (§3 TD-D15, §4.4 R-EX). This closes RISK-1 **and** the Ruling-A typo residual. |
| **Three-case constraint** | §3 TD-D14 (**INV-SELECTOR**) and §4.6 name the three empty-`FILES` cases distinctly; §9.2 pins all three on the runner and on `lint_check`. |

---

## 0. Verification findings — probed, not assumed

Re-derived against the working tree at `worker-1759-run-gates-diff-parsing-260921081001-53070`.
Behavioural claims were run.

### TD-VF-1 — the bug is a one-line verbatim forward

`scripts/oversight/run_gates.sh:45-49`:

```bash
# ── Argument forwarding ───────────────────────────────────────────────────────
# All arguments are forwarded verbatim to each gate script.
# Each gate decides independently how to interpret them.
GATE_ARGS=("$@")
```

No parsing anywhere in the runner. `--diff` and `origin/main` reach `bash "$script" --diff
origin/main` at line 114 as two positional tokens.

### TD-VF-2 — this is the **second** recorded instance of verbatim forwarding producing a wrong answer

`DECISIONS.md:875` records the first, found 2026-09-11:

> `run_gates.sh --all` — which forwards `--all` verbatim to every gate script — pushed the literal
> string `--all` into `secret_scan.sh`'s own `FILES` array as a bogus filename. A non-empty `FILES`
> array meant the script's "no files specified" full-project-scan default … never triggered, so
> `detect-secrets scan --all` ran instead — `detect-secrets`'s own `--all` flag, not this script's —
> and fell through to scanning the entire working tree, including the gitignored
> `scripts/oversight/.venv/` … producing thousands of vendored-dependency false positives instead
> of the real ~15-finding baseline.

That was fixed by **adding a `--all` arm to one gate**. Nine months of the same design later, #1759
is the identical mechanism with a different flag and the opposite symptom (silence instead of
noise). Two point fixes to the same mechanism is the argument for a shared grammar (TD-D1): the
defect is not "`secret_scan` lacked `--all`" or "`run_gates` lacked `--diff`", it is that *no
component owns what a gate argument is*, so every gate independently decides that an unrecognised
token is a filename.

### TD-VF-3 — every file-list gate has the same loop and none has an unknown-flag arm

Seven gates parse argv; each recognises `--all` (plus `--staged` in `secret_scan`) and appends
**every other token** to `FILES`. No `-*)` arm anywhere. Three shapes:

| Shape | Gates |
|---|---|
| File-list (parses argv into `FILES`) | `lint_check`, `type_check`, `portability_check`, `secret_scan`, `security_scan`, `bash_check`, `template_refs_check` |
| No-argument (ignores argv entirely) | `collection_integrity`, `astro_check`, `django_check` |
| No-argument stub | `expensive_gates_stub` |

`check_suspension.sh` is sourced, not run (excluded by `run_gates.sh:85`).

### TD-VF-4 — the zero-argument contract is **pinned by #976** and must not move

`tests/oversight/test_scan_gates_empty_args.py` exists to stop `security_scan`/`secret_scan`
fail-opening on zero file args. The fix it pins is *"mirrors `lint_check.sh`: on empty `FILES` (and
no `--all`/`--staged`) default to a full-project scan."* Four assertions pin the literal string
`"no files specified — defaulting"` (`test_scan_gates_empty_args.py:69,88`,
`test_lint_check_js.py:77`, `test_type_check_ts.py:86`).

**Zero arguments therefore means *scan everything*, not *error*.** Any "an empty file set is an
error" rule that swallows this case reverts #976 and turns the suite red. This is why the design
carries an explicit selector flag rather than inferring intent from `${#FILES[@]}` (TD-D14).

### TD-VF-5 — git behaviours the design depends on (run in a throwaway repo under `/tmp`)

| Probe | Result |
|---|---|
| `git diff --name-only HEAD~1` with one deleted + one added file | prints **both**, rc 0 — deletions **are** in the list |
| `git diff --name-only --diff-filter=ACMRT HEAD~1` | prints only the added file — deletions excluded |
| `git diff --name-only nosuchref` | `fatal: ambiguous argument`, **rc 128** |
| `git diff --name-only sub` (where `sub/` is a directory, not a ref) | rc **0**, silently reinterpreted as a pathspec |
| `git diff --name-only sub --` | `fatal: bad revision 'sub'`, rc 128 — `--` forces revision interpretation |
| `git diff --name-only HEAD` on a clean tree | empty output, **rc 0** |
| `git diff --name-only ..HEAD --` (empty left side) | empty output, **rc 0** — an empty base silently yields zero files |
| `git diff --name-only HEAD~1 --` from a subdirectory | paths are **repo-root-relative**, so none of them exists relative to a subdir cwd |

The last three rows are each a fail-open shape and each gets an explicit rule in §4.

### TD-VF-6 — tools fail in **both** directions on a path that does not exist

Run against the repo's own oversight venv; the two exit-0 rows independently confirmed by the
coordinator:

| Invocation | rc | Behaviour |
|---|---|---|
| `detect-secrets scan --diff origin/main` | **2** | `error: unrecognized arguments: --diff` |
| `bandit -f json -lll --diff origin/main` | **2** | argparse usage error |
| `bandit -f json -lll nosuchfile.py` | **0** | **scans nothing, reports clean** |
| `detect-secrets scan nosuch.py` | **0** | **scans nothing, reports clean** |
| `flake8 nosuch.py` | 1 | `E902 FileNotFoundError` — spurious failure |
| `mypy nosuch.py` | 2 | `Cannot read file` — spurious failure |
| `black --check nosuch.py` | 2 | `Invalid value for 'SRC ...'` — spurious failure |

A non-existent path in a gate's argv is a **silent false-clean** in the two security gates and a
**spurious red** in the three style/type gates. This is the load-bearing justification for Ruling
A's drop rule *and* for its backstop — see TD-D13.

### TD-VF-7 — CI forwards deleted paths today

`.github/workflows/oversight-gates.yml` builds each file-scoped job's argv with
`git diff --name-only "origin/$GITHUB_BASE_REF...HEAD"` — **no `--diff-filter`** — then passes the
paths positionally. A PR deleting a `.py` file therefore hands `flake8`/`mypy`/`black` a missing
path today and goes red for a reason unrelated to its content. Not changed in this slice (Ruling A).

### TD-VF-8 — nothing in the repo invokes `run_gates.sh` programmatically

`grep -rn "run_gates.sh" --include=*.sh --include=*.py --include=*.md --include=*.yml --include=*.yaml .`
plus `grep -rn "run_gates" .claude/ bin/` returns **zero** executable call sites. Every reference is
documentation, a comment, a design doc, or a consumer of its output artifact. CI calls the gate
scripts **directly**. Full caller table in §7.

### TD-VF-9 — `run_validators.sh --step N` does **not** resolve a file list; its header says it does

`run_validators.sh:11` documents `--step 3    (reads step 3 changed files from git)`. The parser
(`:60-62`) only assigns `STEP="$2"`, which is used at `:413` (prompt-audit argv) and `:517-538`
(the committed `signoffs/validators/step{N}/summary.json` path). It **never** populates `FILES`, so
`run_validators.sh --step 3` alone falls into the `:125` empty branch and fail-closes to CRITICAL.
Divergence resolved by TD-D6; sibling not fixed here (Ruling E).

### TD-VF-10 — `get_step_range` resolves its data root from the **library's own location** unless told otherwise

`lib/audit_log.sh`'s `_audit_log_repo_root` walks up from `${BASH_SOURCE[0]}` looking for
`scripts/oversight/lib/audit_log.py`. `get_step_range <n> [root]` takes an optional explicit root
and passes it to `audit_read_stream`. **Consequence:** a `--step` resolution that omits the root
argument reads *the repo containing the library*, not the repo being gated. The design therefore
passes `"$(git rev-parse --show-toplevel)"` explicitly (§4.4). Probed: writing two synthetic
`step-head` events into a throwaway repo via `audit_write_event '<json>' "$ROOT"` and calling
`get_step_range 2 "$ROOT"` returns `<sha1>..<sha2>`; `get_step_range 1 "$ROOT"` returns
`..<sha1>` (empty base); `get_step_range 9 "$ROOT"` returns empty. **This closes OQ-7** — the
`--step` happy path is cheaply pinnable hermetically (§9.1 TC-R16).

### TD-VF-11 — shallowness: the survey's conclusion needs one correction, and the discriminator has a depth-independent tier

Ruling I's discriminator depends on history being present. Four probes, in increasing fidelity to
the real CI shape:

| # | Setup | `is_shallow` | `git rev-list -1 HEAD -- <tracked-but-deleted path>` |
|---|---|---|---|
| P1 | Full clone | `false` | returns a SHA ✔ |
| P2 | Full clone, then `git fetch origin main --depth=1`, **HEAD == the fetched tip** | **`true`** | **empty ✘** |
| P3 | Full clone, PR branch with its own commits, then `git fetch origin main --depth=1` (**the exact `oversight-gates.yml` shape**) | **`true`** | returns a SHA ✔ |
| P4 | Genuine `git clone --depth=1 file://…`, path deleted before the boundary | `true` | **empty ✘** |

**Correction to the survey.** "All six gate jobs check out with `fetch-depth: 0`, so the
discriminator is exact here" is right about the checkout and wrong about the end state: every one
of the six jobs then runs its own `git fetch origin "$GITHUB_BASE_REF" --depth=1` *before* invoking
the gate (workflow lines 113, 146, 179, 212, 245, 278). P2 and P3 show that fetch converts a
complete clone to a **shallow** one — `git rev-parse --is-shallow-repository` reports `true` in this
repo's CI at gate time, `fetch-depth: 0` notwithstanding.

What survives the conversion differs by shape: in P3 (a PR branch carrying its own commits, which is
every real PR) HEAD's own ancestry is untouched and `rev-list` still answers correctly; in P2 (HEAD
*is* the fetched tip) HEAD itself becomes the graft boundary and the walk stops dead. So this repo's
CI is *probably* fine in practice but reports as shallow, and a design that gates the degraded path
on `is_shallow` — which it must, because P4 is the consumer case — will take the degraded path here
too. **That is the right outcome and the design assumes it:** Ruling I's precise-mode benefit is
confined to full clones, and this repo's CI is not one of them at gate time.

**The depth-independent tier.** A *tree* lookup needs only the base commit object and its trees,
which even a `--depth=1` fetch provides in full. Probed in P3, under `is_shallow=true`:

```
git cat-file -e "origin/main:keep.txt"   → rc 0    (present in the base tree ⇒ a deletion)
git cat-file -e "origin/main:nosuch.txt" → rc 128  (absent from the base tree ⇒ fabricated)
```

Both answers are correct in a shallow repository. This is why TD-D15 classifies via the **ref**
whenever one is known (`--diff`/`--step`/`--staged`) and falls back to history only in `explicit`
mode, where no ref was supplied. `run_gates.sh --diff` is therefore precise even in a shallow
consumer CI; only a caller-supplied path list is exposed to the degradation.

### TD-VF-12 — the classification is one batched git call, not one per path

```
git log --format= --name-only -- keep.txt nosuch.txt doc.md   →  keep.txt, doc.md
git log --format= --name-only --diff-filter=D -- <same>       →  keep.txt
git ls-files -- keep.txt nosuch.txt doc.md                    →  doc.md
```

With a pathspec, `--name-only` prints only matching paths, so the union over the whole walk is
exactly the ever-tracked subset of the candidates — the fabricated path is absent from the output.
One history walk for N paths, not N walks. `git ls-files` likewise takes the whole set in one call
and prints the subset git currently tracks. Answers detail 2 (§13).

### Verification gaps I could not close

- **VG-1.** I did not reproduce the issue's original six-file changeset (that branch is gone). AC-1
  parity is pinned instead by the hermetic fixture in §9.4, reproducing the same *shape*: a
  changeset containing a Python file with genuine `black` and `mypy` findings.

---

## 1. What this slice delivers

1. A shared, sourced changeset-resolution library, `scripts/oversight/lib/changeset.sh`, owning
   **one** argument grammar for the runner and all seven file-list gates.
2. `run_gates.sh` parses `--diff <ref>`, `--step <n>`, `--staged`, `--all`, `--help` and explicit
   paths, resolves them to a concrete file list, and forwards **paths** — never a flag as a filename.
3. Fail-closed exits: `2` usage, `3` resolution — at the runner **and** at each file-list gate, so
   the issue's direct-invocation reproduction (`gates/lint_check.sh --diff origin/main`) is fixed too.
4. Three distinguishable empty-`FILES` cases (§4.6), in console output and in `gate-results.json`.
5. The per-gate audit (§6) with the required change for each of the eleven gates.
6. Regression tests (§9) pinning AC-1 parity and all three empty-set cases hermetically.

### What it deliberately does not deliver

- Diff-hunk scoping (issue item 5) and `portability_check`'s pre-existing-violation inheritance.
  §11 states the constraints on that work and what the implementer does when it fires on this PR.
- Any change to `run_validators.sh`, `pr_readiness.py`, `.github/workflows/oversight-gates.yml`, or
  `secret_scan`'s `--staged` filter. See §12.
- Any change to what a gate *checks*, or to which findings block.

---

## 2. Component map

| # | Component | Path | Kind |
|---|---|---|---|
| C1 | Changeset resolution library | `scripts/oversight/lib/changeset.sh` | NEW (sourced lib) |
| C1b | **Missing-path classifier (the Ruling I decision)** | `scripts/oversight/changeset_logic.py` | NEW (Python; §3 TD-D15) |
| C1c | **Shared shallow-clone detector** | `scripts/oversight/lib/git_depth.py` (NEW) + a 3-line delegation in `scripts/oversight/secret_scan_logic.py:447` | NEW + MODIFIED — one detector, not two (§3 TD-D15) |
| C2 | Gate runner | `scripts/oversight/run_gates.sh` | MODIFIED |
| C3 | File-list gates (7) | `scripts/oversight/gates/{lint_check,type_check,portability_check,secret_scan,security_scan,bash_check,template_refs_check}.sh` | MODIFIED |
| C4 | No-argument gates (4) | `scripts/oversight/gates/{astro_check,django_check,collection_integrity,expensive_gates_stub}.sh` | UNCHANGED — explicit, tested exemption (§6, Ruling G) |
| C5 | Tests | `tests/oversight/test_run_gates_changeset.py`, `test_run_gates_artifact.py`, `test_gate_arg_grammar.py`, `test_gate_diff_parity.py` | NEW |
| C6 | Existing test fixup | `tests/oversight/test_type_check_py_filter.py` (one assertion) | MODIFIED |
| C7 | Docs | `run_gates.sh` header/usage, `DECISIONS.md` entry | MODIFIED |

**`CLAUDE.md` is deliberately NOT a component (Ruling J).** Its entry-point row reads
`| Running blocking pre-review gates | scripts/oversight/run_gates.sh |` and names no flags, so it
is **already accurate** after this change. The only edit available would be a cosmetic `--diff`
mention, and it would (a) drag a protected surface into the PR and (b) make `portability_check` fire
on the pre-existing `CLAUDE.md:434` path, whose only in-PR remedy is *another* edit to the same
protected surface — the two compound into a known cycle deadlock. §11.

`scripts/oversight/` is synced wholesale by `bootstrap/hos_install.sh:1856-1877`, so C1 ships to
consumer projects with no installer change.

**Explicitly not components** (Rulings A, C, D): `.github/workflows/oversight-gates.yml`,
`scripts/automation/lib/pr_readiness.py`, `scripts/oversight/run_validators.sh`,
`secret_scan.sh`'s `--staged` extension filter.

---

## 3. Decisions

**TD-D1 — Shared library, not a runner-only fix.** (Issue item 2.) `scripts/oversight/lib/changeset.sh`,
sourced by the runner **and** the seven file-list gates. Three reasons, in order of weight:

1. **The mechanism, not the instance.** TD-VF-2 shows this is the second time verbatim forwarding
   into a gate produced a wrong answer, and the first was fixed by patching one gate. A third
   point fix leaves the mechanism intact.
2. The issue's own reproduction is a *direct gate invocation*, and CI invokes gates directly in six
   jobs (TD-VF-7) — a runner-only fix leaves the reported symptom and every CI job unguarded.
3. Seven copies of "what is a valid argument" disagree today (`--all` in six of them, `--staged` in
   exactly one — the precise asymmetry that caused `DECISIONS.md:875`).

**Migration cost, explicit:** seven gates, each swapping a 7–13 line `for arg in "$@"` loop for a
3-line call plus a summary line. The gates' *divergent* behaviour — each one's full-project
enumeration uses a different extension set — is **not** moved into the library (TD-D2), so the
migration is mechanical and no gate's scan scope changes. Net line count roughly flat. Three
no-argument gates and the stub untouched. One existing test assertion changes (§9.5). The
alternative, a runner-only fix, is ~40 lines in one file and addresses neither (1) nor (2).

**TD-D2 — The library owns *resolution*; each gate keeps its own *enumeration*.** `changeset.sh`
answers "which files did the caller select, and was the selection valid". It never enumerates the
project. `--all` and the no-selector default still resolve inside each gate with that gate's own
`find` (lint: `.py` + 7 JS extensions; `secret_scan`: 9 extensions minus two venv paths;
`bash_check`: `*.sh`; …). This is what keeps the migration risk-free and preserves the four
`"no files specified — defaulting"` strings #976 pinned (TD-VF-4).

**TD-D3 — Resolution is ref→working-tree, matching the sibling.** `--diff <ref>` resolves via
`git diff --name-only --diff-filter=ACMRT "<ref>" --`, the same two-dot ref-vs-worktree semantics as
`run_validators.sh:75`. A caller wanting CI's three-dot semantics passes the range as the ref
(`--diff "origin/main...HEAD"`), which `git diff` accepts as one token (probed).

**TD-D4 — Deletions never reach a gate, and the two routes to that differ.** The *internal*
`--diff`/`--step`/`--staged` resolution excludes deletions **at the source** with
`--diff-filter=ACMRT`, so a deleted path never becomes a "dropped path" internally and never
consumes the drop budget. CI, by contrast, computes its list **without** `--diff-filter` (TD-VF-7)
and passes it positionally, so its deletions arrive as path-shaped-but-missing and are removed by
TD-D13's drop rule instead. Both routes end at the same scannable set; only the mechanism differs.
CI is deliberately not changed in this slice (Ruling A / OQ-4) — the drop rule is what makes that
safe. The unfiltered count is still computed internally so the summary line can say
"6 changed file(s), 1 deletion excluded".

**TD-D5 — `--` terminator on every `git diff`.** Without it a ref that happens to name an existing
path is silently reinterpreted as a pathspec and returns a wrong-but-rc-0 list (TD-VF-5 row 4).

**TD-D6 — `--step N` is a real scope selector in `run_gates.sh`, resolved through `step_range.sh`
with an explicit root.** Given TD-VF-9, "matching the sibling" literally would mean accepting
`--step` and ignoring it, which in this grammar means `run_gates.sh --step 3` has *no selector* and
degrades to a whole-project scan of every gate — precisely the class of surprise this issue is
about. So: `get_step_range "$STEP" "$(git rev-parse --show-toplevel)"` → `BASE..HEAD` →
`git diff --name-only --diff-filter=ACMRT "BASE..HEAD" --`. The explicit root is mandatory
(TD-VF-10): omitting it reads the audit log of whichever repo contains the library. An **empty
range** (no step event) or an **empty BASE** (`..HEAD`, which probes rc 0 / zero files) is a
**fatal exit 3**, never a silent empty set. `--step` is additionally permitted *alongside* another
selector, in which case it is metadata and does not scope — so a cycle can pass the same
`--step N --diff REF` argv to both orchestrators. The sibling is not fixed here (Ruling E).

**TD-D7 — Four terminal states, one vocabulary.** `ok` / `unscoped` / `all` / `empty`, plus two
fatal classes. §4.4. Every gate and the runner use the same words in output and in
`gate-results.json`.

**TD-D8 — A legitimately empty resolved changeset is exit 0 but explicitly not a pass.** `--diff
HEAD` on a clean tree resolves validly to zero files. Making that non-zero would break the
convention CI already uses (`"No changed files … — skipping"`, exit 0) and would red-flag every
cycle that runs gates with nothing changed. Instead the runner does **not** print `GATE PASS: all
non-suspended gates passed`; it prints `GATE NOT RUN: … nothing was checked (this is not a pass)`
and records `"outcome":"not-checked"` per gate. An **unresolvable** ref is a different state: exit 3.

**TD-D9 — The runner must never forward an empty argv in empty-changeset mode.** If it forwarded
nothing, every file-list gate would fall into its no-selector full-project default and scan the
whole repo. That is not merely surprising, it is *red*: `DECISIONS.md:792` and `:857-869` record
that a whole-repo run on unmodified `main` already fails — `bash_check` 2 findings, `lint_check`
flake8 findings across `scripts/automation/lib/`, `type_check` dozens of mypy errors,
`security_scan` 13 pip-audit findings. A caller who says "check this changeset" and gets a
whole-repo scan would therefore get a spurious hard red whenever their diff is empty for that gate.
The runner forwards the internal token `--empty-changeset`; the library recognises it and the gate
prints NOT CHECKED and exits 0 before any tool runs. This also keeps the runner's
directory-discovery design intact — it never needs a hard-coded list of which gates take files.

**TD-D10 — Selectors are mutually exclusive.** (Ruling F.) `--all` with explicit paths is today
silently resolved in `--all`'s favour by `lint_check` — the same "quietly does something other than
what you asked" shape as the bug. It becomes exit 2. **Grep evidence:** every `--all` gate
invocation in the repo passes it alone —
`tests/oversight/test_lint_check_js.py:48,58,68`, `docs/OVERSIGHT-RUNBOOK.md:124,131,291`, and
`tests/oversight/test_signoff_gate.py:247` (a different script). No invocation anywhere combines
`--all` with explicit paths.

**TD-D11 — A path argument beginning with `-` is a usage error, not a path.** `./-weird.py` is the
documented escape. This is what makes "a flag's value can never leak into a tool's argv" structural
rather than a case analysis.

**TD-D12 — `--help`/`-h` exists.** The gate layer had no usage surface at all, which is part of why
an invented flag looked plausible.

### TD-D13 — Ruling A: unknown arguments are split by *shape*, and the drop rule has a backstop

| Token shape | Rule | Rationale |
|---|---|---|
| Flag-shaped (leading `-`, not a known flag) | **Fatal, exit 2**, before anything runs | This is the reported bug. `--diff` is flag-shaped, so AC-2 is satisfied by this arm alone. |
| Path-shaped, exists | Forwarded | — |
| Path-shaped, does not exist | **Warn to stderr, drop** | A fatal here would break every deletion PR in all six CI jobs (TD-VF-7), whose blast radius dwarfs the bug. |
| …and dropping empties a non-empty selection | **Fatal, exit 3** (case 3 of §4.6) | The backstop. |

**The backstop is load-bearing — do not remove it and keep the drop.** `detect-secrets` and
`bandit` both exit **0 reporting clean** on a missing path (TD-VF-6, independently confirmed).
Dropping a nonexistent path is only safe *because* an emptied set becomes a hard error: without the
backstop, a fully-bogus path list would be dropped to nothing and the two security gates would
report a clean scan of zero files — this issue, re-created inside its own fix.

**The typo'd-path residual is closed by Ruling I (TD-D15), not accepted.** Iteration 2 of this
design accepted it: a *typo'd* path was dropped with nothing but a stderr warning, and a *partially*
typo'd list never failed at all (`lint_check.sh src/mian.py src/main.py` → checks one, warns about
the other, exit 0). Ruling I replaces the uniform drop with a classification, so a path git has
never tracked is now a **hard error on the first occurrence**, not a warning on the last. The
"drop" arm survives only for paths git *does* know about, and for the degraded case in TD-VF-11.

Against the probe evidence this matters most in the security gates specifically: `detect-secrets`
and `bandit` exit **0 reporting clean** on a missing path (TD-VF-6), so before Ruling I a fabricated
path was a *silent false-clean* there. Under Ruling I **a fabricated path can never reach a tool at
all** — it is rejected during resolution, before any gate is invoked.

### TD-D14 — INV-SELECTOR: scope intent is carried, never inferred

> **Invariant.** No code path in C1, C2 or C3 may infer scope intent from `${#FILES[@]}`. The only
> authority on "was a selector supplied, and what did it resolve to" is `HOS_CHANGESET_STATUS`.

This is the whole of the three-case constraint. Cases 1 and 2 of §4.6 both end with an empty file
array and today's code cannot tell them apart — that is why `lint_check --diff origin/main` printed
a full-project-scan message about a changeset, and why a "zero files is an error" rule would revert
#976 (TD-VF-4). Carrying the flag makes the three cases decidable rather than guessable.

### TD-D15 — Ruling I: the missing-path classifier

**Why an all-deletions changeset is not case 3.** AC-3's wording is "a gate that receives no files
*because the file list failed to resolve* exits non-zero". A PR that deletes a stale doc resolved
its list perfectly; the answer is legitimately "no scannable files". That is **case 2**. The
reclassification is not a weakening of AC-3, and it is what removes RISK-1 without making "all
paths missing" an untyped state (§13).

**Four states, one place.** For each path that is absent from disk:

| State | Meaning | Disposition |
|---|---|---|
| `deleted` | git tracks, or has tracked, this path | Drop, count separately as a deletion. If this empties the set → **case 2 / SKIP / exit 0**. |
| `fabricated` | git has never heard of this path | **Fatal, exit 3, immediately** — on the first such path, without waiting for the set to empty. |
| `shallow` | history is truncated, so the question cannot be answered | Degraded: drop with a louder warning, case-2 eligible, **never fatal** (TD-VF-11 P4). |
| `undecidable` | git could not be asked, or would not report its depth | Same degraded disposition as `shallow`, different remedy text. |

**Resolution tiers, in order.** Each is tried only if the previous cannot answer:

1. **Ref tree lookup — depth-independent.** When a ref is known (`--diff`, `--step`, `--staged`):
   `git cat-file -e "<REF>:<path>"` → rc 0 ⇒ `deleted`; non-zero ⇒ `fabricated`. Correct under a
   shallow clone (probed, TD-VF-11), so `run_gates.sh --diff` never reaches the degraded path.
2. **Index.** `git ls-files -- <paths>` (batched) → present ⇒ `deleted`. This is what catches a
   staged addition whose working-tree copy was removed (`git add f && rm f`), which history alone
   would misclassify — see detail 3 in §13.
3. **History.** `git log --format= --name-only -- <paths>` (batched, TD-VF-12) → the path appears
   in the output ⇒ `deleted`.
4. **Depth check, only for paths still unresolved.** `is_shallow()` → `true` ⇒ `shallow`; `None` ⇒
   `undecidable`; `false` ⇒ `fabricated` (a complete clone that has never tracked the path is a
   definitive answer).

**Caller-supplied paths only.** The `fabricated` state exists solely for `explicit` mode. In
`diff`/`step`/`staged` the candidate list came from git itself, so a vanished candidate is a racing
working tree, not a typo: those classify as `undecidable` and drop. A human or a script can make a
typo; `git diff` cannot.

**Placement — Python, not shell.** This is a four-state decision over three fallback tiers. As
shell it would be an untested multi-branch state machine in front of the blocking gate layer, which
is precisely what `shell_logic_check.py` scores as a risk signal, and it runs against the named
shell→Python migration direction (v0.7.4). So:

- `scripts/oversight/changeset_logic.py` (C1b) owns the decision, shaped like
  `secret_scan_logic.py`: a module-level entry point plus a CLI subcommand, pure where it can be,
  with the git calls behind one small wrapper. `changeset.sh` invokes it **once per run** with the
  whole missing-path set and reads back one line per path (`<state>\t<path>`). One subprocess, and
  inside it at most four batched git calls regardless of changeset size (detail 2, §13).
- Exit codes from the module: 0 = every path classified, none fabricated; 1 = at least one
  `fabricated` (the shell maps this to E-FABRICATED-PATH / exit 3); 2 = the module itself could not
  run (the shell treats this as `undecidable` for every path — degraded, never fatal, because a
  broken classifier must not become a new way to fail a green PR).

**Reuse the existing shallow detector — do not write a second one.** `secret_scan_logic.py:447`
already implements exactly the tri-state this needs (`True` / `False` / `None` for "could not be
asked"), cached so it is asked at most once, over `git rev-parse --is-shallow-repository`, with
operator remedy text at `:361-375`. A second, subtly-different detector in the same gate layer is
how two mechanisms drift apart. **Plan:** extract the tri-state to `scripts/oversight/lib/git_depth.py`
as `is_shallow_repository(timeout=15) -> bool | None` (byte-identical logic, moved), make
`GitShaVerifier._is_shallow` a 3-line delegation to it that keeps its own caching, and import it
from `changeset_logic.py`. `scripts/oversight/lib/` already hosts Python (`audit_log.py`), and
`secret_scan_logic.py` is **not** under the protected `scripts/oversight/gates/**` glob.
The *detector* is shared; the *remedy strings* are not — `UNDECIDABLE_REMEDY`'s wording is about a
missing commit object for a SHA exemption and does not describe a missing path. `changeset_logic.py`
carries its own, in the same operator-facing register.

This is the one component reaching outside the slice's natural boundary. It is a behaviour-preserving
move of a function that landed yesterday in `033c1382`, taken because the alternative the ruling
explicitly forbids is a second detector. If the orchestrator would rather not touch a just-landed
file, the only other option is for `changeset_logic.py` to import a private method off
`GitShaVerifier`, which is worse; there is no zero-edit path.

---

## 4. C1 — `scripts/oversight/lib/changeset.sh` (the contract)

### 4.1 File-level rules

- Line 1 is `#!/usr/bin/env bash` (required by `bash_check.sh`'s shebang invariant).
- **Sourced only.** No `set -e`/`set -u`, no top-level side effects, safe to source repeatedly (same
  contract as `lib/step_range.sh`). Callers run under `set -euo pipefail`; nothing may rely on that
  and nothing may leave it changed.
- Bash 3.2: no `mapfile`, no `declare -A`, no `${v^^}`/`${v,,}`; every array expansion guarded as
  `${arr[@]+"${arr[@]}"}`.
- **Never calls `exit`.** It returns non-zero and sets `HOS_CHANGESET_EXIT`, so the runner can write
  its artifact before exiting (§5 step 2).

### 4.2 Public surface

```
hos_changeset_parse <label> [arg ...]
```
Parses argv, resolves the selector, populates §4.3.
Returns **0** on any terminal state in {`ok`, `unscoped`, `all`, `empty`}.
Returns **1** on a fatal, having set `HOS_CHANGESET_EXIT` to `2` (usage) or `3` (resolution) and
written a diagnostic plus the usage block to **stderr**.
`<label>` is the caller's name (`run_gates`, `lint_check`, …) and prefixes every message.

```
hos_changeset_summary <label>
```
Prints the one-line changeset summary (§4.5) to **stdout**. Every file-list gate and the runner call
it exactly once, immediately after a successful parse, before any tool runs. This line is the "the
file list arrived" evidence whose absence made this bug invisible.

```
hos_changeset_not_checked <label>
```
Prints the NOT CHECKED line (§4.5). Called when `HOS_CHANGESET_STATUS == empty`, immediately before
`exit 0`.

```
hos_changeset_skip_kind <label> <kind> <matched_count>
```
Prints the zero-of-kind SKIP line (§4.5), for a gate whose per-language subset came out empty from a
**non-empty** changeset.

```
hos_changeset_usage <label>
```
Prints the usage block. Called by the `--help` arm and by every fatal.

### 4.3 Globals set by `hos_changeset_parse`

| Global | Type | Meaning |
|---|---|---|
| `HOS_CHANGESET_STATUS` | string | `ok` \| `unscoped` \| `all` \| `empty` — **the sole authority on scope intent (INV-SELECTOR)** |
| `HOS_CHANGESET_MODE` | string | `none` \| `all` \| `explicit` \| `diff` \| `step` \| `staged` \| `empty-changeset` |
| `HOS_CHANGESET_FILES` | array | Existing, repo-root-relative paths. Empty unless `STATUS=ok`. |
| `HOS_CHANGESET_RAW_COUNT` | int | Paths the selector produced **before** the existence filter |
| `HOS_CHANGESET_DROPPED` | int | Paths dropped because they are not on disk |
| `HOS_CHANGESET_DELETED` | int | Paths excluded by `--diff-filter=ACMRT` (diff/step/staged only) |
| `HOS_CHANGESET_REF` | string | Raw `--diff` ref / resolved `BASE..HEAD` / empty |
| `HOS_CHANGESET_STEP` | string | The `--step` value, or empty |
| `HOS_CHANGESET_SOURCE` | string | Human-readable selector description (§4.5) |
| `HOS_CHANGESET_EXIT` | int | Set only on a fatal: `2` or `3` |

All are reset at the top of every `hos_changeset_parse` call.

### 4.4 The argument-parsing state machine

**Grammar**

```
argv     := item*
item     := "--all"
          | "--staged"
          | "--empty-changeset"
          | "--help" | "-h"
          | "--diff" REF
          | "--step" N
          | PATH                      ; any token not beginning with "-"
```

**Scan** — left to right, one pass, no reordering.

| # | Token | Action |
|---|---|---|
| S1 | `--help` \| `-h` | usage to stdout, `HOS_CHANGESET_EXIT=0`, return 1 (caller exits 0 immediately; **no artifact written**) |
| S2 | `--all` | selector `all`; if a selector is already set → **E-CONFLICT** |
| S3 | `--staged` | selector `staged`; if already set → **E-CONFLICT** |
| S4 | `--empty-changeset` | selector `empty-changeset`; if already set → **E-CONFLICT** |
| S5 | `--diff` | no next token, or next token begins with `-` → **E-MISSING-VALUE**; `--diff` already seen → **E-DUP**; selector already set → **E-CONFLICT**; else consume two tokens, selector `diff`, `HOS_CHANGESET_REF=<value>` |
| S6 | `--step` | no next token, or it does not match `^[0-9]+$` → **E-MISSING-VALUE**; already seen → **E-DUP**; else consume two tokens, `HOS_CHANGESET_STEP=<n>`. **Not** a selector conflict — see S6a |
| S7 | any other token beginning with `-` | **E-UNKNOWN** (Ruling A, flag-shaped arm) |
| S8 | anything else | append to the explicit path list; if a non-`explicit` selector is already set → **E-CONFLICT** (TD-D10) |

- **S6a.** After the scan: if `--step` was given **and** no other selector was, the selector becomes
  `step`; otherwise `--step` is metadata only.
- Argument order is irrelevant: `--step 3 --diff X` ≡ `--diff X --step 3`.

**Resolve** — by selector.

| Selector | Resolution |
|---|---|
| none | `STATUS=unscoped`, `MODE=none`, `FILES=()`. **Legacy path, byte-compatible** — the gate falls back to its own project default (#976, TD-VF-4). |
| `all` | `STATUS=all`, `MODE=all`, `FILES=()`. Gate enumerates. |
| `empty-changeset` | `STATUS=empty`, `MODE=empty-changeset`. |
| `explicit` | `RAW_COUNT=<n>`; apply R-EX. |
| `diff` | G1–G2; `git diff --name-only "$REF" --` → unfiltered count; `git diff --name-only --diff-filter=ACMRT "$REF" --` → candidates; `DELETED = unfiltered − candidates`; apply R-EX. |
| `step` | G1–G2; `get_step_range "$STEP" "$(git rev-parse --show-toplevel)"` (explicit root — TD-VF-10). Empty range → **E-STEP-NORANGE**. Range whose text before `..` is empty → **E-STEP-NOBASE**. Else `REF=<range>` and proceed exactly as `diff`. |
| `staged` | G1–G2; `git diff --cached --name-only --diff-filter=ACMRT --`; apply R-EX. |

**Git preconditions G1–G2** (diff / step / staged only)

- **G1.** `git rev-parse --show-toplevel` must succeed → else **E-NOTREPO**.
- **G2.** `cd "$(git rev-parse --show-toplevel)" && pwd -P` must equal `pwd -P` → else **E-NOTROOT**.
  Justified by TD-VF-5: git emits repo-root-relative paths regardless of cwd, so from a
  subdirectory every resolved path would be a non-existent path. `-P` on both sides so a symlinked
  temp dir does not produce a false mismatch.
- Any `git diff` exiting non-zero → **E-BADREF**, carrying git's own stderr verbatim.

**R-EX — the existence filter** (applies to `explicit`, `diff`, `step`, `staged`):

1. Each candidate that exists (`-e`) is appended to `HOS_CHANGESET_FILES`.
2. The absent candidates — and **only** those; a run with none skips this entirely — are passed as
   one batch to `changeset_logic.py` (C1b, TD-D15), which returns a state per path.
   - any `fabricated` → **E-FABRICATED-PATH**, fatal 3, **immediately**, naming every fabricated
     path. Does not wait for the set to empty.
   - `deleted` → counted in `HOS_CHANGESET_DROPPED`, reported once to stderr as
     `<label>: path not on disk (deleted), excluded: <path>`.
   - `shallow` / `undecidable` → counted in `HOS_CHANGESET_DROPPED` and reported to stderr as
     `<label>: path not on disk and history is truncated (<cause>) — cannot tell a deletion from a
     typo; excluded: <path>`, followed once by the operator remedy.
3. `RAW_COUNT == 0` (the selector genuinely produced nothing) → `STATUS=empty` — **case 2**.
4. `RAW_COUNT > 0` and the surviving list is empty → `STATUS=empty` — **case 2**, with the summary
   line reporting how many paths were dropped and why. Reaching here means every absent path was
   `deleted`, `shallow` or `undecidable`: an all-deletions changeset resolved correctly and the
   honest answer is "no scannable files" (TD-D15). A fabricated path never reaches this step — it
   already failed at 2.
5. Otherwise → `STATUS=ok`.

Steps 3 and 4 converging on case 2 is Ruling I's whole point: the *reason* a path is absent is
established at step 2, so the empty set no longer has to carry that meaning by itself.

**Error classes → exit codes**

| Class | Exit | Message (stderr, prefixed `<label>: `) |
|---|---|---|
| E-UNKNOWN | **2** | `unknown option '<tok>' — refusing to treat it as a filename` + usage |
| E-MISSING-VALUE | **2** | `--diff requires a <ref> argument` / `--step requires a non-negative integer` + usage |
| E-DUP | **2** | `--diff given more than once` (likewise `--step`) |
| E-CONFLICT | **2** | `'<a>' and '<b>' are mutually exclusive selectors` |
| E-NOTREPO | **3** | `--diff/--step/--staged require a git repository; none found at <pwd>` |
| E-NOTROOT | **3** | `must be run from the repository root (<toplevel>); cwd is <pwd>` |
| E-BADREF | **3** | `cannot resolve '<ref>': <git stderr>` |
| E-STEP-NORANGE | **3** | `step <n> has no step-head audit event — cannot scope a changeset; pass --diff <ref>` |
| E-STEP-NOBASE | **3** | `step <n> has no base commit (range '<range>') — cannot scope a changeset; pass --diff <ref>` |
| E-FABRICATED-PATH | **3** | `path(s) git has never tracked and which are not on disk: <paths> — refusing to report a result on a file list that names files that do not exist` (Ruling I / TD-D15) |

**Exit-code contract, complete** (runner and every file-list gate; Ruling B):

| Code | Meaning |
|---|---|
| 0 | The gate ran and found nothing blocking, **or** had nothing of its kind to check, **or** the changeset resolved to zero files. In the latter two cases stdout carries a SKIP/NOT CHECKED line and never `GATE PASS`. |
| 1 | The gate ran and found a blocking problem. **Unchanged.** |
| 2 | **Usage error.** Nothing ran; the argv was malformed. |
| 3 | **Resolution error.** Nothing ran; the changeset could not be determined. |

`124` (timeout, from `with_timeout`) is untouched and still surfaces through each gate's retry handling.

### 4.5 Exact output strings

`HOS_CHANGESET_SOURCE`:

| Mode | SOURCE |
|---|---|
| `diff` | `--diff <ref>` |
| `step` | `--step <n> (<base>..<head>)` |
| `staged` | `--staged` |
| `explicit` | `<n> explicit path(s)` |
| `all` | `--all (project enumeration)` |
| `none` | `no selector (project enumeration)` |
| `empty-changeset` | `an empty changeset resolved by the runner` |

Lines (`printf`, no colour — these are parsed by tests; colour stays reserved for the runner's
existing PASS/FAIL lines):

```
<label>: changeset = <N> file(s) from <SOURCE>
<label>: changeset = <N> file(s) from <SOURCE> (<D> deletion(s) excluded)
<label>: changeset = <N> file(s) from <SOURCE> (<D> deletion(s) excluded, <M> path(s) not on disk)
<label>: NOT CHECKED — <SOURCE> resolved to 0 scannable file(s). Nothing was checked; this is not a pass.
<label>: SKIP — 0 of <N> changeset file(s) are <kind> (nothing for this gate to check).
```

### 4.6 The three empty-`FILES` cases (issue item 3), named distinctly

| Case | Trigger | `STATUS` | Behaviour | Exit | Output discriminator |
|---|---|---|---|---|---|
| **1 — no selector** | `run_gates.sh` / `<gate>.sh` with no arguments | `unscoped` | **Full-project scan**, exactly as #976 pinned. The runner forwards nothing; each gate enumerates with its own extension set. | gate's own | `<gate>: no files specified — defaulting to …` (**string preserved verbatim**) |
| **2 — selector resolved to zero** | `--diff HEAD` on a clean tree; a changeset with no files of this gate's kind; **an all-deletions changeset** (TD-D15); runner-supplied `--empty-changeset` | `empty` | **SKIP.** Never falls through to case 1 (TD-D9). No tool runs. | **0** | `NOT CHECKED — … resolved to 0 scannable file(s)` or `SKIP — 0 of <N> changeset file(s) are <kind>`; runner prints `GATE NOT RUN`, never `GATE PASS` |
| **3 — resolution failed** | unresolvable ref, not a repo, wrong cwd, step with no range/base, flag-shaped junk, **a path git has never tracked** | (fatal) | **Error.** No tool runs; no result is reported. | **2** or **3** | stderr diagnostic + usage; runner writes `[]` to `gate-results.json` |

Cases 1 and 2 both end with an empty file array; only `HOS_CHANGESET_STATUS` separates them
(INV-SELECTOR, TD-D14). Pinned by §9.2 on the runner and on `lint_check`.

---

## 5. C2 — `run_gates.sh`

Order of operations (replacing current lines 45–49 and extending the loop):

1. Resolve `$PYTHON` (unchanged, lines 34–43).
2. `source "$SCRIPT_DIR/lib/changeset.sh"`; `hos_changeset_parse run_gates "$@"`.
   - `HOS_CHANGESET_EXIT == 0` (the `--help` arm): exit 0. **No artifact written.**
   - Fatal (2 or 3): `mkdir -p "$OUT_DIR"`; `printf '[]' > "$OUT_FILE"`; exit `$HOS_CHANGESET_EXIT`.
     Writing `[]` is deliberate: it clears any stale `gate-results.json` from a previous run, and
     `gate_compliance.load_gate_results` + `pr_readiness._check_gates` already treat an empty array
     as "gates_required=true but gate-results.json is absent" → COMPLIANCE FAIL. A resolution
     failure therefore fail-closes downstream instead of leaving last run's evidence in place. See
     §7 row 3 for the Ruling-D disclosure about this.
3. `hos_changeset_summary run_gates`.
4. **Testability seam** (modelled on `RUN_VALIDATORS_FILELIST_ONLY`, #981): if `RUN_GATES_RESOLVE_ONLY`
   is non-empty, print the block below and exit 0 **before** the tool preflight and before any gate runs.
   ```
   MODE\t<HOS_CHANGESET_MODE>
   STATUS\t<HOS_CHANGESET_STATUS>
   SOURCE\t<HOS_CHANGESET_SOURCE>
   FILE\t<path>        (repeated, one per resolved file)
   FORWARD\t<token>    (repeated, one per token that would be passed to each gate)
   ```
5. `tool_preflight_or_fail` (unchanged, lines 74–77).
6. Gate discovery (unchanged, lines 79–91).
7. Build `GATE_ARGS` **from `HOS_CHANGESET_STATUS` only** (INV-SELECTOR):

   | STATUS | `GATE_ARGS` |
   |---|---|
   | `unscoped` | `()` — forward nothing (case 1, legacy behaviour preserved exactly) |
   | `all` | `("--all")` |
   | `ok` | `("${HOS_CHANGESET_FILES[@]}")` |
   | `empty` | `("--empty-changeset")` (case 2; TD-D9) |

   `--step` is never forwarded (no gate consumes it).
8. Gate loop unchanged (`bash "$script" ${GATE_ARGS[@]+"${GATE_ARGS[@]}"}`), except for the two new
   record fields in §8.
9. Final line:
   - `STATUS != empty` → unchanged (`GATE PASS: …` / `GATE FAIL: …`).
   - `STATUS == empty` → `GATE NOT RUN: <SOURCE> resolved to 0 scannable files — nothing was checked (this is not a pass)`, exit 0. The string `GATE PASS` must **not** appear.

Header/usage block updated to document `--diff`, `--step`, `--staged`, `--all`, `--help`, paths, the
three cases, and the exit codes.

---

## 6. C3/C4 — the per-gate audit (issue item 4)

**Eleven gates audited. Seven affected — all seven file-list gates, not the three the issue
identified by comparison.** Five fail silently; two fail loudly but misleadingly.

"Today, empty `FILES`" describes pre-fix code. "Junk-argv symptom" is what `--diff origin/main`
produces today. The `bash_check` row was independently reproduced by the coordinator
(`GATE PASS`, exit 0, zero files read).

| # | Gate | Shape | Today, empty `FILES` | Junk-argv symptom (`--diff origin/main`) | Affected | Required change |
|---|---|---|---|---|---|---|
| 1 | `lint_check` | file-list | `:72-82` full-project default; project-empty → SKIP exit 0 | `FILES=(--diff origin/main)`; neither is `.py`/JS → `:95-98` `no Python or JS/TS files in changeset — SKIP`, **exit 0** | **YES (silent)** | Adopt C1. Keep `:72-82` verbatim (case 1, #976 string). Replace `:95-98` with `hos_changeset_skip_kind lint_check "Python or JS/TS" 0`. `hos_changeset_summary` after parse. `STATUS=empty` → `hos_changeset_not_checked`, exit 0. |
| 2 | `type_check` | file-list | `:63-70` full-project default | `PY_FILES` empty → `:86` `SKIP: no Python files found in project` — a false statement about a changeset containing a `.py` file (the issue quotes this line); tsc lane also SKIPs → **`GATE PASS: no type errors`, exit 0** | **YES (silent)** | Adopt C1. Split `:86`: case 1/`all` → keep `SKIP: no Python files found in project`; changeset modes → `hos_changeset_skip_kind type_check "Python" 0`. `STATUS=empty` → NOT CHECKED, exit 0, **before** the tsc lane. Requires §9.5. |
| 3 | `portability_check` | file-list | `:41-49` full-project default (py/sh/toml/cfg/ini); `:51-54` `no files to check` exit 0 | `FILES` non-empty → the inline Python opens two non-existent paths, `except Exception: pass`, `HITS` empty → **`GATE PASS: no machine-specific paths found`, exit 0** | **YES (silent)** | Adopt C1 (R-EX makes the silent-open-failure path unreachable). `STATUS=empty` → NOT CHECKED. Explicit-mode any-extension behaviour unchanged — §11. |
| 4 | `bash_check` | file-list | `:48-57` full-project default; `:59-62` `no .sh files to check` exit 0 | `FILES` non-empty → loop at `:71` skips both non-`.sh` tokens → `ERRORS=0` → **`GATE PASS: all shell scripts use bash shebang and Bash-3.2-safe constructs`, exit 0**, zero files read | **YES (silent)** | Adopt C1. Count files actually examined; zero-of-kind → `hos_changeset_skip_kind bash_check ".sh" 0`; the PASS line must state the count (`GATE PASS: <n> shell script(s) …`). `STATUS=empty` → NOT CHECKED. |
| 5 | `template_refs_check` | file-list | `:44-47` non-Django → SKIP (honest, repo-level); `:49-58` full-project default | On a Django project the inline Python `except OSError: continue`s over both tokens → **`GATE PASS: all referenced templates exist`, exit 0**. Non-Django projects SKIP first, which is why this was never observed | **YES (silent, Django-only)** | Adopt C1, keeping the `manage.py` SKIP first. PASS line must report how many source files were read. `STATUS=empty` → NOT CHECKED. |
| 6 | `secret_scan` | file-list | `:46-63` full-project default. **Second, narrower hole:** `FILES` emptied by the `:93-102` stamp filter → `:148` `No files to scan` → **`GATE PASS: no secrets detected`, exit 0** | `detect-secrets scan --diff origin/main` → **rc 2** → `run_with_retry` exhausts → `GATE FAIL: detect-secrets did not complete after retries` — reads as flakiness (AC-4) | **YES (loud, misleading + a narrow silent hole)** | Adopt C1 (bad argv can no longer reach the tool — AC-4 primary). Replace `:148` with `secret_scan: NOT CHECKED — all <n> supplied file(s) are stamp-exempt; nothing was scanned` (exit 0, not `GATE PASS`). **AC-4 defence-in-depth (Ruling H):** `_run_detect_secrets` records its rc in `DS_LAST_RC`; on retry exhaustion with `DS_LAST_RC == 2`, print `GATE FAIL: detect-secrets rejected its arguments (exit 2 — a usage error, not tool flakiness). Nothing was scanned; do not retry.` Resolve the binary through `${HOS_DETECT_SECRETS_BIN:-<existing resolution>}` — off by default, inert in the real pipeline, present only so §9.4 TC-P5 can pin the branch. **`--staged` extension filter unchanged** (Ruling C). |
| 7 | `security_scan` | file-list | `:41-56` full-project default; zero-`.py` project → honest bandit SKIP, pip-audit still runs | `bandit … --diff origin/main` → **rc 2** → retries exhausted → `GATE FAIL: bandit did not complete after retries` — same misleading shape. Separately `bandit <nonexistent>.py` exits **0 with empty results** → a stale path yields `OK: no HIGH severity findings` | **YES (loud, misleading + a silent false-clean on stale paths)** | Adopt C1. Same `BANDIT_LAST_RC == 2` message split as row 6 (**no seam** — §12). `STATUS=empty` → NOT CHECKED **and skip the pip-audit lane too** (nothing changed ⇒ nothing to gate; keeps the empty path fast and side-effect-free). Report the count of files bandit received. |
| 8 | `astro_check` | no-arg | N/A — ignores argv | Runs its normal repo-scoped check | no | **None.** Exempt: the runner forwards the changeset to every gate by design and this gate must keep ignoring it. |
| 9 | `django_check` | no-arg | N/A | Runs `manage.py check` | no | **None** (same exemption). |
| 10 | `collection_integrity` | no-arg | N/A — derives its own change set from `git merge-base HEAD origin/<base>` at `:55-69` | Unaffected by argv | no | **None — explicit, tested exemption (Ruling G).** It is a whole-repo *integrity* check: it asks "does the full suite still import", so file scoping is meaningless for it and `--diff <ref>` must not narrow it. Its `:38-42` comment already says the guard controls *when* it runs, not *what* it checks. Add one line to that comment recording the exemption, and pin it with §9.3 TC-G8 so a later reader does not "fix" it. |
| 11 | `expensive_gates_stub` | no-arg | N/A — no argv parsing, no suspension check | Runs the static container check | no | **None** (same exemption). |

**Common shape for all seven modified gates** (the mechanical migration):

```
source <check_suspension.sh>            # unchanged, stays FIRST — a suspended gate exits 0 regardless of argv
is_suspended "<name>" && { print_suspended "<name>"; exit 0; }
source <../lib/changeset.sh>
hos_changeset_parse <name> "$@" || exit $HOS_CHANGESET_EXIT
hos_changeset_summary <name>
case "$HOS_CHANGESET_STATUS" in                     # INV-SELECTOR: switch on STATUS, never on ${#FILES[@]}
  empty)        hos_changeset_not_checked <name>; exit 0 ;;   # case 2
  all|unscoped) <gate's own existing project enumeration — unchanged> ;;   # case 1
  ok)           FILES=("${HOS_CHANGESET_FILES[@]}") ;;
esac
```

Suspension deliberately precedes argument validation: a suspended gate is bypassed wholesale today
and that must not change.

---

## 7. Caller impact

| # | Caller | How it calls | Impact | Action |
|---|---|---|---|---|
| 1 | `.github/workflows/oversight-gates.yml` — 6 file-scoped jobs | `bash gates/<g>.sh "${FILES[@]}"` where `FILES` is `git diff --name-only "origin/$BASE...HEAD"` (no `--diff-filter`), skipping when empty | Explicit existing paths behave identically. Deleted paths are now **dropped with a warning** instead of crashing flake8/mypy/black — fixes a latent false red (TD-VF-6/7). **Residual:** a PR whose diff is *entirely* deletions supplies an all-missing list → case 3 → exit 3. See **RISK-1** (§13). | **None in this slice** (Ruling A / OQ-4) |
| 2 | `.github/workflows/oversight-gates.yml` — `oversight-gate-repo-scoped` | `bash gates/<g>.sh` with no args | None — all three are exempt no-arg gates. | None |
| 3 | `scripts/automation/lib/pr_readiness.py` `_check_gates` (`:359-370`) | Reads `gate-results.json` via `load_gate_results` | **No code change (Ruling D).** Its conclusion is identical to today for every case except one: on a **resolution failure** the runner now writes `[]`, which `_check_gates:362` reads as "gate-results.json is absent" → FAIL, where today a bad ref produced a fresh all-green array → "gates pass". That change *is* AC-3 ("a gate that receives no files because the file list failed to resolve exits non-zero"), not a rider: the only alternatives are leaving a stale array (fail-open on last run's evidence) or deleting the file (identical conclusion). Every other path — no args, `--all`, explicit, `ok`, `empty` — concludes exactly as today. | None |
| 4 | `scripts/automation/lib/gate_compliance.py` | Reads `gate`, `exit_code`, `suspended` | None — the two new fields are additive and read via `.get`; array shape preserved. | None |
| 5 | `contract/OVERSIGHT-CONTRACT.md` §65, §534 (REQ-GATE-NN-16) | Specifies the artifact's existence and non-emptiness | Unchanged semantics; the schema gains two optional fields. | Documentation note only (§8) |
| 6 | `CLAUDE.md:345` "Running blocking pre-review gates" | Names the entry point, no flags | **Already accurate** — the row needs no edit. | **None (Ruling J).** The usage surface lands in `run_gates.sh`'s own header instead. |
| 7 | `docs/OVERSIGHT-RUNBOOK.md:124,131,291` | `lint_check.sh --all` | None — `--all` alone is unchanged. | None |
| 8 | `.github/workflows/oversight-validators.yml:71`, `DECISIONS.md`, `docs/CI-EXECUTION-INVENTORY.md:37`, `docs/v0.4.0/TECHNICAL-DESIGN-375-*.md`, `docs/v0.7.0/ADR-1643-*.md` | Prose | None. Note `TECHNICAL-DESIGN-375` §100/§350 already specified `[--staged | --all | <file> ...]` — this design implements the `--staged` half that was never built. | None |
| 9 | `tests/oversight/test_scan_gates_empty_args.py`, `test_lint_check_js.py`, `test_type_check_ts.py`, `test_secret_scan_validator_artifact.py`, `test_astro_check.py`, `test_expensive_gates_binary_check.py` | Drive gates with `--all`, no args, or existing explicit paths | **None** — all three shapes are preserved verbatim, which is why TD-D2 keeps enumeration in the gates and why case 1 is untouched. | None |
| 10 | `tests/oversight/test_type_check_py_filter.py:39` | Asserts `"SKIP: no Python files found in project"` for an explicit **non-`.py`** argument | **Breaks by design** — that message is the one the issue quotes as a false statement. | **C6:** §9.5 |
| 11 | Humans / agents at a prompt | `bash scripts/oversight/run_gates.sh …` | `--diff` starts working; a typo'd flag errors instead of silently passing. | None |

**No executable caller passes zero arguments** (TD-VF-8), and case 1 is preserved exactly regardless.
Item 3's "do not make no-argument invocation newly fail" is satisfied structurally by INV-SELECTOR.

### Protected-surface status — checked against `scripts/framework/protected_surfaces.txt`

**This PR does touch a protected surface, and it is unavoidable: `scripts/oversight/gates/**` is
listed, and C3 modifies seven files under it.** That is the first-order subject of issue items 2–4 —
the direct-invocation half of the bug cannot be fixed without editing the gates. **A human approval
is therefore required on this PR regardless of computed risk tier**, and the overseer may not
approve or merge it.

Every other component was checked against the actual glob list, not assumed:

| Component path | Protected? |
|---|---|
| `scripts/oversight/gates/{7 gates}.sh` (C3) | **YES** — `scripts/oversight/gates/**` |
| `scripts/oversight/lib/changeset.sh` (C1), `lib/git_depth.py` (C1c), `changeset_logic.py` (C1b), `secret_scan_logic.py` (C1c) | No — only `gates/**`, `run_validators.sh` and `validators/schema.py` are listed under `scripts/oversight/` |
| `scripts/oversight/run_gates.sh` (C2) | No — see the note below |
| `tests/oversight/*` (C5, C6) | No |
| `DECISIONS.md`, `docs/v0.7.0/*` (C7, this doc) | No — only `docs/releases/**` is listed |
| `.claude/agents/**`, `contract/**`, `bin/**`, `bootstrap/**`, `scripts/framework/**`, `.github/workflows/**` | **Not touched at all** |

**Observation, not a proposal:** `scripts/oversight/run_validators.sh` is a protected surface and
its sibling `scripts/oversight/run_gates.sh` is not, though both are orchestrators of the same
blocking layer. That asymmetry is pre-existing and out of scope here — changing the protected-surface
list is a governance change, not a bug fix — but it is worth someone's attention, and this slice
does not depend on it either way (C3 already forces the human gate).

**Ruling J's reason 1 is therefore already satisfied by C3** — human approval is forced regardless,
so avoiding `CLAUDE.md` buys nothing there. Ruling J's reasons 2 and 3 (the `portability_check`
compounding and the known cycle deadlock) stand on their own and are the operative ones.

---

## 8. `gate-results.json` schema delta

Shape stays a JSON **array** of per-gate objects (anything else breaks
`gate_compliance.load_gate_results`, which returns `[]` for a non-list). Two additive fields:

```json
{"gate":"lint_check","exit_code":0,"suspended":false,"script":"…","ts":"…",
 "changeset_mode":"diff","files_forwarded":6,"outcome":"checked"}
```

| Field | Values | Derivation |
|---|---|---|
| `changeset_mode` | `none` \| `all` \| `explicit` \| `diff` \| `step` \| `staged` \| `empty-changeset` | `HOS_CHANGESET_MODE` (constant across the array) |
| `files_forwarded` | integer, or `null` for `none`/`all` | `${#HOS_CHANGESET_FILES[@]}`. Named *forwarded*, not *checked*: the runner hands the same list to every gate and cannot know how many each examined. |
| `outcome` | `checked` \| `unscoped` \| `all` \| `not-checked` | `checked` when STATUS=`ok`; `not-checked` when STATUS=`empty` (case 2); else the status name |

`ts`, `gate`, `exit_code`, `suspended`, `script` unchanged, in that order, so positional and
string-matching consumers keep working. `outcome` is written now so the deferred consumer change
(§12) has data to read; nothing consumes it in this slice.

---

## 9. Test plan

All new tests are hermetic, modelled on `tests/oversight/test_run_validators_diff_filelist.py`: a
throwaway `git init` repo under `tmp_path` via its `_git`/`_init_repo` helpers (`:38-54`), driven
through the real script by a seam that exits before any heavy work. Never this repo's live state.
Gates resolve `VENV_BIN` from their own absolute location, so a tmp cwd still uses the real
oversight venv (how `test_scan_gates_empty_args.py` already works); tool-dependent assertions are
`skipif`-guarded on presence, mirroring the existing files.

### 9.1 `tests/oversight/test_run_gates_changeset.py` — resolution (via `RUN_GATES_RESOLVE_ONLY`)

Parses the `MODE/STATUS/SOURCE/FILE/FORWARD` block; no gate runs, so no tool or network needed.

| ID | Case | Assertion |
|---|---|---|
| TC-R1 | `--diff HEAD~1` on a 3-file commit | `MODE=diff`, `STATUS=ok`, the three paths in `FILE` |
| TC-R2 | **AC-1 (structural)** — `FORWARD` from `--diff HEAD~1` vs. the same paths passed explicitly | equal lists, same order |
| TC-R3 | Changeset with one deletion | deleted path absent from `FILE`; summary says `1 deletion(s) excluded` |
| TC-R4 | `--diff HEAD` on a clean tree | `STATUS=empty`, `FORWARD == ["--empty-changeset"]`, rc 0, no `GATE PASS` |
| TC-R5 | `--diff nosuchref` | rc **3**, stderr carries git's `fatal:`, `gate-results.json == []` |
| TC-R6 | `--dif HEAD`, `--diff-ref X`, `-x` (parametrised) | rc **2**, `unknown option`, usage printed |
| TC-R7 | `--diff` with no value | rc **2** |
| TC-R8 | `--diff --all` | rc **2** (value is flag-shaped) |
| TC-R9 | no arguments | `STATUS=unscoped`, `FORWARD` empty — **case 1 guard** |
| TC-R10 | `--all` | `FORWARD == ["--all"]` |
| TC-R11 | explicit existing paths | `FORWARD` == those paths, verbatim |
| TC-R12 | explicit paths, **none** existing, all **fabricated** | rc **3**, `git has never tracked` — Ruling I |
| TC-R13 | explicit paths, **one** missing and **fabricated**, one live | rc **3** — fails on the first bad path without waiting for the set to empty (the Ruling-A residual, now closed) |
| TC-R14 | explicit paths, **one** missing but **committed-deleted**, one live | rc 0; live path forwarded; stderr says `(deleted)`; summary reports `1 path(s) not on disk` |
| TC-R15 | explicit paths, **all** missing, **all committed-deleted** (the deletion-only PR) | rc **0**, `STATUS=empty`, `NOT CHECKED` — **the RISK-1 regression guard**; must never be rc 3 |
| TC-R15b | one missing path that is **staged then removed from the working tree** (`git add f && rm f`) | rc 0, classified `deleted` via the index tier — detail 3 |
| TC-R16 | `--step 3` in a repo with no audit events | rc **3**, `no step-head audit event` |
| TC-R17 | `--step 1` where step 1 exists but step 0 does not (empty base) | rc **3**, `has no base commit` |
| TC-R18 | `--step 2` with two synthetic `step-head` events | `STATUS=ok`, files from `<sha1>..<sha2>`. Fixture writes events with `audit_write_event '<json>' "$tmp"` from `lib/audit_log.sh` — **use the writer, do not hand-roll the on-disk record format**. Probed working (TD-VF-10). **This test must fail if the explicit root argument is dropped from `get_step_range`** — see TC-R18b. |
| TC-R18b | **TD-VF-10 guard** — `--step 2` in a fixture repo whose events name commits that exist *only* in that repo, run while the HOS repo also has (different or no) step events | `STATUS=ok` with the **fixture's** shas. If the coder writes `get_step_range "$STEP"` without the root argument, the call reads the HOS repo's `audit/log/` instead and this test fails — either by resolving the wrong range or by finding no events at all. Without this case TC-R18 could pass by accident when both repos are empty of events; with it the argument is load-bearing. |
| TC-R17 | `--step abc` | rc **2** |
| TC-R18 | `--diff X --step 3` | `MODE=diff` — step is metadata, does not scope |
| TC-R19 | `--diff HEAD~1` outside any git repo | rc **3**, `require a git repository` |
| TC-R20 | `--diff HEAD~1` from a subdirectory | rc **3**, `must be run from the repository root` |
| TC-R21 | `--staged` with one staged file | `MODE=staged`, that file in `FILE` |
| TC-R22 | `--help` | rc **0**, usage on stdout, **`gate-results.json` not created** |
| TC-R23 | `--all extra.py` | rc **2** (Ruling F / TD-D10) |

### 9.2 Three-case tests (the coordinator's constraint) — runner **and** `lint_check`

Each case is asserted on both, so the invariant is pinned at the layer that resolves and the layer
that consumes.

| ID | Case | Runner assertion | `lint_check` assertion |
|---|---|---|---|
| TC-3C-1 | **no selector** | `STATUS=unscoped`, `FORWARD` empty | `no files specified — defaulting` present; project scan engaged |
| TC-3C-2 | **selector → zero files** | `STATUS=empty`; `GATE NOT RUN` present; `GATE PASS: all non-suspended gates passed` **absent**; no gate printed `no files specified — defaulting` (proves no fallthrough to case 1) | `--empty-changeset` → `NOT CHECKED` present, `no files specified — defaulting` **absent**, `GATE PASS` **absent**, rc 0 |
| TC-3C-3 | **resolution failed** | `--diff nosuchref` → rc 3, `gate-results.json == []` | `--diff nosuchref` → rc 3, no tool output |

### 9.3 `tests/oversight/test_gate_arg_grammar.py` — parametrised over all 7 file-list gates

| ID | Case | Assertion |
|---|---|---|
| TC-G1 | `<gate>.sh --nope` | rc **2**, `unknown option` |
| TC-G2 | **the issue's reproduction** — `<gate>.sh --diff HEAD~1` in a tmp repo | rc != 2; summary names `--diff HEAD~1` with a non-zero count; for `lint_check` the string `no Python or JS/TS files in changeset` is **absent** when the changeset contains a `.py` |
| TC-G3 | `<gate>.sh --empty-changeset` | rc 0; `NOT CHECKED` present; `no files specified — defaulting` and `GATE PASS` absent |
| TC-G4 | `<gate>.sh` with no args, for the four gates carrying the string | `no files specified — defaulting` still present — #976 guard |
| TC-G5 | `lint_check.sh only.md` / `bash_check.sh only.md` / `type_check.sh only.md` | rc 0 and `SKIP — 0 of 1 changeset file(s) are <kind>`; the bare old wording gone |
| TC-G6 | `<gate>.sh --all` in a tmp project | unchanged behaviour (project enumeration engaged) |
| TC-G7 | `<gate>.sh -h` | rc 0, usage printed |
| TC-G8 | **Ruling G** — `collection_integrity.sh a.py b.py` and `… --diff HEAD~1` | identical output and rc to `collection_integrity.sh` with no args; the gate never narrows to the supplied paths. Pins the exemption as deliberate. |

### 9.4 `tests/oversight/test_gate_diff_parity.py` — AC-1 and AC-4, real tools

Fixture: tmp git repo; commit 1 = clean seed; commit 2 = `bad.py` carrying **both** a `black`
violation and a `mypy` error, plus `notes.md` and `helper.sh`.

| ID | Case | Assertion |
|---|---|---|
| TC-P1 | `lint_check.sh --diff HEAD~1` vs `lint_check.sh bad.py notes.md helper.sh` | identical rc (1); finding lines from `=== flake8 ===` onward identical |
| TC-P2 | `type_check.sh`, same two invocations | identical rc; identical mypy finding lines |
| TC-P3 | `portability_check.sh`, same two invocations, with a planted machine-specific home-directory path (build the string by concatenation in the test so the test file does not itself trip the gate) | identical rc (1); identical `HITS` block |
| TC-P4 | `secret_scan.sh --diff HEAD~1` with a planted AWS-style key | rc 1, `potential secret`, and **never** `did not complete after retries` (AC-4 primary) |
| TC-P5 | **Ruling H** — `HOS_DETECT_SECRETS_BIN` points at a stub that exits 2 | rc 1; stdout says `rejected its arguments (exit 2 — a usage error, not tool flakiness)`; `did not complete after retries` **absent** (AC-4 defence-in-depth) |
| TC-P6 | `HOS_DETECT_SECRETS_BIN` unset | the real binary resolution is used — the seam is inert by default |

Skip-guards: TC-P1 needs `flake8`+`black`, TC-P2 `mypy`, TC-P4 `detect-secrets`; TC-P5/P6 need
neither (the stub is a two-line shell script).

### 9.5 Existing-test fixup

`tests/oversight/test_type_check_py_filter.py:39` — change
`assert "SKIP: no Python files found in project" in res.stdout` to the new
`SKIP — 0 of 1 changeset file(s) are Python` wording. The test's actual subject (a non-`.py` arg
must not reach mypy; no `Invalid syntax`; rc 0) is unchanged and must keep asserting exactly that.
Add a docstring line recording that the message changed under #1759 because the old wording claimed
the *project* had no Python when only the *changeset* did not.

No other existing assertion changes — verified by grepping every `SKIP:` / `GATE PASS` /
`defaulting` / `No files` assertion under `tests/` (§7 row 9).

### 9.6 AC → test mapping

| AC | Pinned by |
|---|---|
| 1 — `--diff` reports the same failures as the explicit list | TC-R2 (tokens), TC-P1/P2/P3 (real findings) |
| 2 — unrecognised argument ⇒ usage error, non-zero, never forwarded | TC-R6/R7/R8/R23, TC-G1 |
| 3 — empty file set not a silent PASS; causes distinguishable | TC-3C-1/2/3 (runner **and** gate), TC-R4/R5/R12/R13, TC-A1/A2, TC-G3/G5 |
| 4 — `secret_scan` exit-2 no longer reads as retry exhaustion | TC-G1 (secret_scan param), TC-P4 (primary), TC-P5 (defence-in-depth) |

### 9.7 `tests/oversight/test_run_gates_artifact.py` — the artifact (gates actually run)

| ID | Case | Assertion |
|---|---|---|
| TC-A1 | Stale `gate-results.json` present, then `--diff nosuchref` | overwritten with `[]`, rc 3 |
| TC-A2 | `--diff HEAD` on a clean tmp repo | rc 0; every record has `"outcome":"not-checked"`, `exit_code 0`; `GATE NOT RUN` present; `GATE PASS: all non-suspended gates passed` absent; no gate printed `no files specified — defaulting` |
| TC-A3 | `--diff HEAD~1` with a real changeset | every record carries `"changeset_mode":"diff"` and `files_forwarded == <n>` |

---

## 10. Boundaries

- **C1 must not** enumerate the project, know any gate's extension set, or call `exit`.
- **C1 must not** assume `set -e` is active in the caller, nor leave it changed.
- **C2 must not** hard-code which gates take file arguments (what `--empty-changeset` buys).
- **C3 must not** change what its tool scans or which findings block — only the argv it receives and
  the sentences it prints about an empty set.
- **C3 must not** move its `is_suspended` check after argument parsing.
- **Nothing may** branch on `${#FILES[@]}` to decide scope (INV-SELECTOR).
- **Nothing may** remove the case-3 backstop while keeping the drop rule (TD-D13).
- The two new environment variables (`RUN_GATES_RESOLVE_ONLY`, `HOS_DETECT_SECRETS_BIN`) may only
  *stop early* or *redirect a binary in a test*; neither may cause a gate to report a result it
  would not otherwise report, and both are inert when unset.

---

## 11. Item 5 (deferred): constraints, and what the implementer does when it fires on **this** PR

**Constraints on the later hunk-scoping work**

- `HOS_CHANGESET_REF` is exposed precisely so hunk extraction has the ref without re-parsing argv.
  Hunk scoping should add a **second** output (e.g. `HOS_CHANGESET_HUNKS`, a `path:start-end` list)
  and must not change `HOS_CHANGESET_FILES`, whose whole-file semantics five gates depend on.
- Hunk logic must live in C1, not in individual gates — seven divergent copies is the defect this
  slice removes.

**What happens on this PR, and what the implementer must do**

Fixing `--diff` makes `portability_check` receive files it never saw in that mode, including `.md`.
`CLAUDE.md:434` contains a literal absolute developer home-directory path — exactly the shape the
gate's regex matches — so `run_gates.sh --diff <ref>` on any changeset touching `CLAUDE.md` would
fail the portability gate on a pre-existing violation. **The finding is true**: a machine-specific
absolute path committed to a governance document is precisely what that gate exists to catch. It
was invisible only because the gate was never given the file.

**Ruling J makes this unreachable by construction, not by luck.** `CLAUDE.md` is not a component of
this PR (§2), and `portability_check` is file-scoped, so the gate cannot fire on a file the PR does
not touch. That is the operative path, and it holds by design rather than by the implementer
remembering to check.

Two supporting facts, both verified rather than assumed:

- Every file this PR *does* touch was scanned with the gate's own regex and is **currently clean**:
  `DECISIONS.md`, `run_gates.sh`, `secret_scan_logic.py`, all seven gate scripts, and
  `test_type_check_py_filter.py`. So `portability_check --diff` on this PR is expected to report no
  findings at all.
- The implementer must keep it that way: any new or edited file must be free of machine-specific
  absolute paths, and a test fixture that *needs* such a string must build it by concatenation so
  the test file does not trip the gate (already specified in TC-P3).

The remaining options are **contingencies that should not arise**, kept for the case where the
implementer finds an unavoidable reason to touch `CLAUDE.md`:

1. **Preferred — don't.** Confirm with `git diff --name-only origin/main...HEAD` that `CLAUDE.md`
   is absent from the changeset. Under Ruling J it should be.
2. **If it is unavoidably touched and the gate fires, fix the offending line in the same PR.**
   Rewrite the path portably (a placeholder or `$HOME`-relative form) — it is a documentation path,
   not executable configuration, and the surrounding prose survives the edit.
3. **If that fix is genuinely not available**, **stop and escalate to the orchestrator** with the
   exact line and why. Splitting the `CLAUDE.md` fix into its own PR ahead of this one is an
   acceptable resolution for the orchestrator to choose.

**Ruling J is not a licence to dodge the gate.** If some *other* file in this PR trips
`portability_check` on a genuine finding, that gets fixed, not excluded. And `CLAUDE.md:434` remains
a real, open finding — recorded in **#1791** (§12), not buried.

**Explicitly forbidden:** suspending `portability_check` via `contract/gate-suspension.md`; adding a
path/file exemption to the gate; narrowing its extension filter in explicit mode; or weakening the
`--diff` resolution to exclude `.md`. Every one of those is arguing the gate down to keep a true
finding quiet, which is the failure mode this whole issue is about.

Note also the pre-existing asymmetry left deliberately unchanged: `portability_check` applies its
`py/sh/toml/cfg/ini` extension filter in `--all` mode but **not** in explicit-path mode. CI already
runs it in explicit mode over `.md` files, so narrowing it here would both break AC-1 parity and
mask findings.

---

## 12. Deferred — needs a follow-up issue (coordinator to file; I have filed nothing)

| # | Item | Why it is out of this slice | What closes it |
|---|---|---|---|
| D1 | **`secret_scan`'s `--staged` extension filter** — direct and runner-mediated `--staged` will disagree (the runner resolves the full staged list; the gate's own `--staged` still filters to 9 extensions) | Ruling C. Behaviour change to what gets scanned, with no caller in this repo. | Remove the gate-local filter so both routes scan the same set, or move the filter into the lib as a documented staged-mode policy. |
| D2 | **`outcome":"not-checked"` has no consumer** — a run where every gate was `not-checked` still reads as "gates pass" to `pr_readiness._check_gates` | Ruling D. Compliance-semantics change, must not ride inside a bug fix. | Teach `_check_gates` (and/or `gate_compliance.check_gate_compliance`) that an all-`not-checked` array does not satisfy REQ-W-02 when `gates_required`. The field is written by this slice so the data is already there. |
| D3 | **`run_validators.sh:11`'s `--step` header is false** — it claims to read changed files from git; the flag only selects the artifact path (TD-VF-9) | Ruling E. | Either implement file resolution there (matching TD-D6) or correct the header. The two orchestrators' `--step` semantics diverge until then, which is documented in `run_gates.sh`'s header by this slice. |
| D4 | **`bandit`'s exit-2 branch is unpinned** — `security_scan` gets the same message split as `secret_scan`, but no seam, so the branch has no test | Ruling H approved one seam, for AC-4, which names `secret_scan`. | An `HOS_BANDIT_BIN` seam mirroring `HOS_DETECT_SECRETS_BIN`, plus a TC-P5 twin. |
| D5 | **A shallow clone disables Ruling I's precise classification for caller-supplied path lists**, so a fabricated path degrades to a warning there instead of a hard error (TD-VF-11 P4). This is the *consumer* exposure — `actions/checkout@v4` defaults to `fetch-depth: 1` — and, per TD-VF-11's correction, it also applies in this repo's own CI, because each gate job's `git fetch --depth=1` converts the clone to shallow before the gate runs. | The degraded path is **required** (Ruling I), not a gap to close under time pressure: failing closed there would export the RISK-1 regression to every consumer using default checkout settings. | Callers that pass a pre-computed list could pass the base ref too (or use `--diff`), which routes classification through the depth-independent tree tier (TD-D15 tier 1) and restores precision under any clone depth. That is the same CI migration OQ-4 deferred. |
| D6 | **Diff-hunk scoping + `portability_check` inheriting pre-existing violations** — **filed as #1791** | Issue item 5, split out. | §11. **`CLAUDE.md:434` is the concrete instance waiting there**: a true, currently-unreported portability finding that only becomes visible once `--diff` works, and that hunk-scoping is the right fix for. |

---

## 13. RISK-1 (resolved), and the three details worked

### RISK-1 — RESOLVED by Ruling I. Reasoning trail kept, because the resolution is not the obvious one.

**What was found (iteration 2).** Ruling A's drop rule plus the case-3 backstop composed to a fatal
when *every* supplied path was missing, and that is reachable from CI: a PR whose diff consists
**entirely of deletions** gives all six file-scoped jobs a list in which every path is missing →
case 3 → exit 3 → red, where today `lint_check`, `portability_check`, `bash_check`,
`template_refs_check` and `secret_scan` are green. The green→red flip was confined to deletion-only
PRs that delete no Python file (a `.py` deletion is already red today via `mypy` rc 2 / `flake8`
E902), e.g. removing a stale doc.

**Why neither obvious option was taken.** Keeping it accepted a CI regression; the "minimal
deviation" I proposed (treat all-missing as case 2) removed the regression but got the right answer
for the wrong reason, leaving "all paths missing" an untyped state that could not tell a deletion
from a typo.

**The resolution.** An all-deletions changeset was being filed under case 3 and does not belong
there — case 3 is *the file list failed to resolve*, and a PR deleting a stale doc resolved its list
perfectly. Ruling I supplies the missing discriminator (TD-D15): classify *why* a path is absent,
rather than inferring it from the set emptying. Deletion ⇒ case 2, exit 0 (**regression gone**);
never-tracked ⇒ fatal on the first bad path (**the Ruling-A typo residual is closed too, and closed
earlier than the backstop would have caught it**); shallow/undecidable ⇒ degraded drop
(**consumer regression prevented**).

**Status: RISK-1 closed; the Ruling-A residual closed.** Guarded by TC-R15 (deletion-only must be
rc 0) and TC-R13 (one fabricated path among live ones must be rc 3).

### Detail 1 — shallow clones: the degraded path is required, and one survey premise needed correcting

Measured, four setups (TD-VF-11). `git rev-list -1 HEAD -- <path>` is **not** reliable under
shallowness: in a genuine `--depth=1` clone a path that git genuinely tracks but deleted before the
boundary returns empty, which would classify a real deletion as fabricated and hard-fail every
deletion PR in every consumer using default checkout settings. So the degraded branch is mandatory,
exactly as ruled.

**Correction to the survey:** "all six jobs check out with `fetch-depth: 0`, so the discriminator is
exact here" is right about the checkout and wrong about the end state. Each of the six jobs then
runs its own `git fetch origin "$GITHUB_BASE_REF" --depth=1` **before** invoking the gate (workflow
lines 113, 146, 179, 212, 245, 278), and that converts a complete clone to a shallow one —
`git rev-parse --is-shallow-repository` reports `true` at gate time in this repo's CI. Whether
history survives depends on the shape: with a PR branch carrying its own commits (every real PR)
`rev-list` still answers correctly; when HEAD *is* the fetched tip, HEAD becomes the graft boundary
and the walk stops dead. Since the design must gate the degraded path on `is_shallow` — because the
consumer case demands it — **this repo's CI takes the degraded path too.** That is the correct trade
as ruled (precision confined to full clones), but it is not the "exact here" the survey assumed, and
the design is written against the measured behaviour.

**What recovers precision without risk:** a *tree* lookup needs only the base commit object, which
even a `--depth=1` fetch provides in full. Probed under `is_shallow=true`:
`git cat-file -e "origin/main:<deleted path>"` → rc 0, `…:<fabricated path>` → rc 128 — both
correct. Hence TD-D15's tier 1: whenever a ref is known (`--diff`/`--step`/`--staged`), classify
against the ref's tree and never consult history at all. Only a caller-supplied path list
(`explicit` mode, which is CI's shape) falls through to history and thence to degradation. D5 records
that passing a base ref would close even that.

**Reuse, not re-derivation:** `secret_scan_logic.py:447` already implements the needed tri-state
(`True`/`False`/`None`), cached, over `git rev-parse --is-shallow-repository`. TD-D15 extracts it to
`scripts/oversight/lib/git_depth.py` and has both callers import it, rather than writing a second
detector. That is the one edit this slice makes to a file outside its natural boundary, and §3
records why there is no zero-edit alternative.

### Detail 2 — cost: bounded, and it does not scale with changeset size

The classifier fires **only for paths already absent from disk**, which is the rare branch in all
four modes:

- `diff` / `step` / `staged`: candidates come from `git diff --diff-filter=ACMRT … --`, i.e.
  ref→working-tree, so every candidate exists by construction. An absent one means the tree mutated
  mid-run — effectively never, and classified `undecidable` rather than fatal (TD-D15).
- `explicit`: absent = deletions + typos. The pathological input is a 6,000-deletion PR.

That case is bounded by **batching, not by luck**: `changeset.sh` invokes `changeset_logic.py`
**once per run** with the whole missing set, and inside it the git work is at most four batched
calls — `ls-files -- <all paths>`, `log --format= --name-only -- <all paths>`, one cached
`rev-parse --is-shallow-repository`, and tier-1 `cat-file` only when a ref is known. Probed
(TD-VF-12): with a pathspec, `--name-only` prints only matching paths, so one history walk returns
the ever-tracked subset of N candidates and the fabricated path is simply absent from the output.
There is no per-file loop over git in any mode.

### Detail 3 — a path git never tracked that legitimately does not exist yet

Reachable in exactly one shape, and handled:

- **`diff`/`step`/`staged` — unreachable by construction.** Those lists come from git, not from a
  caller, so a vanished candidate cannot be a typo. TD-D15 classifies them `undecidable`, never
  `fabricated`. The `fabricated` state exists **only for caller-supplied paths**.
- **`explicit`, staged addition removed from the working tree** (`git add f && rm f`) — git tracks
  `f` in the index though it was never committed, so history alone returns empty and would
  misclassify it. This is the one real case, and it is why TD-D15 consults the **index before
  history** (tier 2). Probed: `git ls-files -- <committed-deleted> <fabricated> <live>` prints only
  the live path, so the index tier adds the staged case without disturbing the deletion case.
  Pinned by TC-R15b.
- **`explicit`, a path computed against a different checkout state** (another branch or worktree) —
  that *is* fabricated relative to this tree, and failing is the correct answer, not a false positive.
- **A file the PR adds** — present in the working tree, so never absent, so the classifier never
  sees it. No real caller passes a path for a file that does not exist yet; nothing in this repo does.

### Superseded — the original RISK-1 text (iteration 2), kept for the reasoning trail

**RISK-1 — the rulings, composed, can turn a currently-green CI run red in one narrow case.**

Ruling A's standing constraint is that this slice must not turn a green CI run red for reasons
unrelated to the bug. Ruling A's drop rule achieves that for the *common* deletion case (a PR that
deletes some files and changes others: the deletions are dropped with a warning, the rest are
checked). But Ruling A's backstop and the three-case constraint both make **all** paths missing a
case-3 fatal, and that is reachable from CI today:

> A PR whose diff consists **entirely of deletions** makes all six file-scoped jobs pass a list in
> which every path is missing → case 3 → exit 3 → red.

Today that PR is **green** in `lint_check`, `portability_check`, `bash_check`, `template_refs_check`
and `secret_scan` (a missing path is a SKIP or a silent clean — TD-VF-6). It is already red in
`type_check`/`lint_check` if a `.py` was deleted (`mypy` rc 2, `flake8` E902), so the green→red flip
is confined to **deletion-only PRs that delete no Python file** — e.g. removing a stale doc.

I implemented it as ruled, because:
- the backstop is what makes the drop rule safe at all (TD-D13), and weakening it re-creates this
  very issue inside its own fix;
- "all of the paths you gave me are missing" is a genuinely correct thing to refuse to report on;
- the scenario is narrow and the fix, if it ever fires, is one line per job (D5).

*(Superseded.)* The minimal deviation offered at this point — treat all-missing in `explicit` mode
as case 2 — was **not** taken. Ruling I supersedes it: classifying *why* a path is absent achieves
the same regression fix without leaving "all paths missing" untyped, and closes the typo residual
as well. Nothing above this line is live design; it is kept so the next reader can see that the CI
flip was found before it shipped, and why the resolution is not the obvious one.

### Accepted observations (confirmed by the orchestrator; not disagreements)

- **On Ruling D:** there is one branch where `pr_readiness`'s *conclusion* still changes without
  touching its code — the `[]` write on a resolution failure (§7 row 3). I believe that is AC-3
  itself rather than a rider, and every alternative is worse (stale array = fail-open). Flagging it
  so it is your decision and not my silent one.
- **On Ruling H:** taking the seam for `detect-secrets` but not `bandit` leaves `security_scan`'s
  identical branch untested (D4). That is consistent with AC-4's wording, which names `secret_scan`
  only, so I have not extended it — but the asymmetry is deliberate rather than an oversight.

---

## Self-flag

**RISK:** MEDIUM — the design changes a *contract* (gate argv grammar and exit codes) that live CI
jobs depend on, and it changes five gates' output strings. Blast radius is bounded by TD-VF-8 (no
programmatic caller of the runner), by TD-D2 (no gate's scan scope changes), and by case 1 being
preserved verbatim (#976 stays green). The two residual risks are named and quantified: **RISK-1**
(§13) and the `portability_check`/`CLAUDE.md` finding (§11), the latter being a true finding with a
prescribed, non-negotiable response.

**CONFIDENCE:** HIGH on §0 (every behavioural claim probed, including the `--step` fixture and the
`git` disambiguation rules), §4, §5, §6, §7, §9.

**Change classification:** `structural` (gate argument grammar + exit-code contract, approved under
Ruling B), `additive` remainder.

**Human Review Required:** **yes, and it is unavoidable** — C3 modifies seven files under
`scripts/oversight/gates/**`, a protected surface, so a human must approve this PR regardless of
computed risk tier and the overseer may not merge it (§7). That is a property of the fix, not a
discretionary expansion: the direct-invocation half of the bug cannot be fixed without editing the
gates. No *open design question* remains: RISK-1 is resolved by Ruling I, and the three items
flagged in earlier iterations were settled by Rulings C, D and I.
