# ADR-1574 — One surface-glob grammar for the CI gate, the overseer and CODEOWNERS

Issue: #1574 (milestone v0.7.0). Author: architect. Date: 2026-10-14.
Baseline: `f29d04d8d` (branch; `origin/main` = `cf1ca09ee`, its parent; the only delta is the requirements doc).
Input: `docs/v0.7.0/REQUIREMENTS-1574-surface-matcher-unify.md` (pm-agent, F1–F11, REQ-U1..U10, ESC-1..7).
Coordinates with: the #559 architect ruling pinned in `tests/automation/test_phase_b.py::TestKnownDivergenceFromOversightCodeowners`; ADR-1657 AD-3 (`pr_review_cli.evaluate_reviewer_trigger`); ADR-1340 AD-3 (release-panel exclusions and their sha256 binding); ADR-035 AD-2/AD-5 (`audit_allowlist.txt`, "exactly one glob dialect").

**Verdict on the requirements: APPROVED WITH CONDITIONS.** The product framing is right:
- one documented answer to "is this path on a surface?";
- no silent narrowing of any deny-direction gate, and no silent widening of any allow-direction list;
- a hand-written GitHub oracle rather than an implementation-derived expectation;
- the trusted-base and ship-set constraints on the CI gate.

The measured facts stand (§0). Ten amendments (AM-1..AM-10, §11) correct the design. Three of them would otherwise have shipped a defect:
- **ESC-1 (B)'s hidden "protect" mode cannot be applied to the CODEOWNERS model** because over-matching is not monotone-safe under last-match-wins (AF-2). It also cannot make CODEOWNERS equal to the CI gate. This ADR replaces the mode split with nesting written explicitly in the list text, which gives one predicate with no modes (AD-2).
- **Writing a `**/` line into a surface list before both legacy matchers are retired is a live fail-open.** M3 drops root matches for `**/x/**` (F4's own mechanism), so `**/bin/**` would stop protecting `bin/hos-cron` at the overseer (AF-5). The slice order is made binding (AD-9).
- **`regen_all.sh --check` regenerates CODEOWNERS in a temp tree** that would not contain the new module, so the check would go permanently red the moment `gen_codeowners.sh` depends on it (AF-6).

**Status: Accepted (technical).** ESC-1..7 stay with the human (§12). ARCH-ESC-1..3 are added. S0 and S1 can proceed before any human answer (§10).

---

## 0. Verification of the pm-agent's claims (re-derived at `f29d04d8d`)

All four file-loadable matchers were loaded by path, read-only, and run over `git ls-files` (8,895 paths: pm's 8,894 plus the requirements doc) and a probe set. The scratch script lived under `mktemp -d` and was not committed.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | F1: five matchers | **Stands.** No sixth matcher consumes a surface list. | M1 `require_human_approval.py:53-91`. M2 `scripts/oversight/codeowners.py:78-121`. M3 `merge_authority.py:402-470`. M4 `merge_authority.py:364-382`. M5 `scripts/automation/lib/codeowners.py:69-96`. `secret_scan_logic.py` and `change_classifier.py` use hard-coded regexes, not list globs, so they are out of scope. |
| 2 | F1: "eight call sites" | **Undercounted. See AM-1.** | M3 is also called per file at `merge_authority_cli.py:601` and `pr_review_cli.py:1165`, and by `pr_review_cli.evaluate_reviewer_trigger` (`:915`, ADR-1657 AD-3). M2's `get_owners_for_path` is also consumed by `resolve_human_reviewer` (`pr_review_cli.py:1034`). That caller is neither allow- nor deny-direction: it **routes** (it picks which human to request), and it is last-match-wins sensitive. |
| 3 | F1: M5 has no production callers | **Stands.** | `grep actor_is_codeowner\|find_owners` outside the module: no hits. |
| 4 | F2: headers contradict code | **Stands, plus one more.** | `protected_surfaces.txt:13-14` ("a plain path = that exact file"); `security_surfaces.txt:26-28`. **Additional parser divergence:** `gen_codeowners.sh:44` strips inline `#` comments (`${line%%#*}`), but `load_globs` (`:41-50`) and M3 do not. A line `bin/** # tools` would generate a correct CODEOWNERS line while the CI gate compiled a literal that never matches, which is fail-open. No such line exists today (AF-7). |
| 5 | F3: M3 = 220, M1 = 213, strict superset; adopting M2 narrows the overseer by 5 protected and 6 security files | **Stands exactly.** | Measured: M1 213, M2 215, M3 220, M5 213. M3−M1 = the 7 listed files. M3−M2 = the 5 `prompts/` mirrors. Security: M3 30 vs M1/M2 24; the 6 extras are all `prompts/scripts/automation/lib/*.md`. |
| 6 | F4: M3 misses root-level `auth/` and similar | **Stands.** | Probe `auth/login.py` vs `**/auth/**`: M1=1, M2=1, M3=0, M5=0. |
| 7 | F5: M1/M2 `**/` eats the separator | **Stands, and M1 has the defect too.** | `oauth/x` vs `**/auth/**`: M1=1, M2=1. `NOTAGENTS.md` vs `AGENTS.md`: M2=1 only. `NOT.hos-release`: M2=1 only. M1 does not consume `security_surfaces.txt`, so M1's instance only matters for allow lists. Today no allow-list line starts with `**/`. |
| 8 | F6: class table; the allow lists give identical sets under M1/M2/M3 | **Stands.** | Exclusions: 7,975 under every matcher. Allowlist: 7,927 under every matcher. `release/v1/a/b` vs `release/v*`: M3=1, M1=M2=0. Correction for ESC-4: `CHANGELOG*` also matches `CHANGELOG.d/x` and `x/CHANGELOG.d/y` under M4, so a lossless rewrite needs `**/CHANGELOG*/**` too (AM-4). |
| 9 | F7: CODEOWNERS is generated root-anchored | **Stands.** | `gen_codeowners.sh:47-51`. The committed `.github/CODEOWNERS` has 22 lines, all `/`-anchored. Under the M2 model its set is 215 (M1 plus `prompts/AGENTS.md` and `templates/AGENTS.md`), but GitHub's real set for `/AGENTS.md` is root-only. That is exactly why the oracle must be hand-written. |
| 10 | F8: ship set | **Stands, plus two gaps.** | `framework_consumer_files.txt:70,72,81-83`; `hos_install.sh:1882-1887` rsyncs `scripts/oversight/`. **Gap 1:** the install loop *warns and skips* a listed file that is missing from the source (`hos_install.sh:1926`, and `cp_framework_file:621-624`). A missing module therefore ships a broken required check with no install failure. The ship-set test is the only guard (AD-6). **Gap 2:** `regen_all.sh:110-114` (AF-6). |
| 11 | F10: fail behaviour | **Stands, with one correction.** | M1 exits 2 on a missing list. But M1 has **no top-level exception handler**: any uncaught exception (a future module-load failure, for example) exits **1**, which reads as "protected, no human approval", not "tooling error". REQ-U4's "exit 2, never 0 or 1" therefore needs a new wrapper (AM-7). M3 missing-list returns False (`:412-413`), and `merge_authority_cli.py:611-616` already discloses this as "the library's permissive default". |
| 12 | F11: trusted base and the sibling-load idiom | **Stands.** | Workflow `require-human-approval.yml:63-79` (checkout `base.sha`, runs `python3 scripts/framework/require_human_approval.py`). `require_overseer_approval.py:49-59`; `audit_predicate.py:45-55`. `release_panel_logic.py:43-49` mutates `sys.path`. |

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` for an existing CODEOWNERS-grammar implementation or a shared by-path loader.
- Found: four private `_load_sibling_module` / `_load_codeowners_module` copies (`require_overseer_approval.py`, `audit_predicate.py`, `merge_authority_cli.py:659`, `pr_review_cli.py:475`).
- No shared loader exists, and none can exist for the trusted-base gate: a loader module would itself have to be loaded somehow. Each caller therefore keeps a ~6-line private loader (AD-5).
- No existing implementation of the GitHub grammar exists; M2 is the closest, and it is defective (F5).

### Architect's findings (these change the design)

**AF-1 (HIGH): ESC-1 (B)'s widening of the CI gate reaches consumers for P1/P2, not only P3.** F9/ESC-7 cover nested `AGENTS.md`/`CLAUDE.md`. Under (B), the shipped CI gate would also protect every nested `bin/`, `bootstrap/`, `contract/`, `scripts/framework/` and `.github/workflows/` directory in a consumer repo. In a Node or Python monorepo `packages/*/bin/` is ordinary, so every PR touching one would need a human. In HOS, the only nested copies that (B) preserves are the 11 `prompts/` mirrors. Those are prompt-artifact records (`prompts/bin/hos-cron.md` describes `bin/hos-cron`), not controls. **The fallback's measured protective value is ~0. Its consumer cost is real and unmeasured.**

**AF-2 (HIGH): over-matching is not monotone-safe under last-match-wins.** `get_owners_for_path` keeps the **last** matching CODEOWNERS entry, and both `check_pr_files` and `resolve_human_reviewer` read it. Example:
- CODEOWNERS: `/scripts/ @human`, then `docs @bot`.
- Today M2 matches `scripts/mydocs` with the later `docs` line (F5), so the model says "bot-owned, no human required".
- GitHub says `@human`.

So over-matching in a last-match-wins resolver can turn a human-owned path into a non-human-owned one. **No over-matching mode may ever be used inside CODEOWNERS resolution.** This kills ESC-1 (B)'s premise that a "protect" mode is the safe choice for every deny-direction caller. It also means M2's F5 defect is a latent fail-open in the model today, not only a harmless over-match. GitHub still enforces CODEOWNERS server-side, so the real effect is a wasted auto-merge attempt rather than a bypass.

**AF-3 (HIGH): (B) cannot reach equality, and an explicit `**/` line can.** Under (B), CODEOWNERS ⊊ CI gate unless the generator invents `**/` lines (ESC-3). If nesting is written into the list text instead (`**/bin/**`), the CI gate, the overseer and the generated CODEOWNERS line (`**/bin/`) all read the same text under one grammar, and they are **equal by construction**. Equality, not ⊆, is the issue's product outcome. AD-2 adopts this.

**AF-4 (MEDIUM): a committed real-tree path snapshot rots.** REQ-U9's superset test compares today's sets against a committed path list. Any later deletion or rename of a protected file (removing a `bin/` script, say) drops a snapshot path from the new set, and the test fails with no defect present. AD-8 replaces the snapshot with **frozen legacy reference matchers** in `tests/`, evaluated on the current tree at test time (AM-5).

**AF-5 (HIGH): writing a `**/` line too early is fail-open.** Legacy M3 evaluates `fnmatch(f, "**/bin/**")`, which is `.*/bin/.*`, and its fallback `**/**/bin/**`. Neither matches root `bin/hos-cron` (the F4 mechanism). Legacy M1 compiles `**/bin/**` to `^.*bin/.*$`, which matches `robin/x`. **Binding:** no `**/`-prefixed line may be added to `protected_surfaces.txt` or `security_surfaces.txt` while either legacy matcher still reads that list. In practice such a rewrite lands in the same PR as, or after, the last caller of that list moves to the new module (AD-9).

**AF-6 (MEDIUM): `regen_all.sh --check` copies only `gen_codeowners.sh` and the list** into `$TMP_CHECK/codeowners/scripts/framework/` (`:110-114`). If `gen_codeowners.sh` calls the module through `$SCRIPT_DIR`, the check fails permanently. The fix is to copy the module there too (S4).

**AF-7 (MEDIUM): three list parsers, three comment rules.** Covered by row 4. The module owns the single line parser. It rejects inline `#` and internal whitespace instead of guessing, and the generator and every caller use it.

**AF-8 (LOW): `gen_codeowners.sh` truncates `.github/CODEOWNERS` before writing it** (`{ … } > "$OUT"` under `set -e`). Once a Python step can fail mid-stream, a failure leaves a truncated CODEOWNERS on disk, which is a protected file. S4 writes to a temp file in the same directory and uses `mv`.

**AF-9 (LOW): M4 needs no special mode.** M4's patterns all end in `*` or `**`. For a trailing `*`, fnmatch's slash-crossing `p*` is exactly `p[^/]*` ∪ `p[^/]*/**`. With M3's `**/` fallback written explicitly, the M4 list is reproduced losslessly in the one grammar. Case-insensitivity is reproduced by the **caller** lowercasing the path, as it does today. The module gets no case option (AD-4).

---

## 1. Module

### AD-1: `scripts/framework/surface_glob.py`: stdlib-only, by-path loadable, one translator

**Location.**
- `scripts/framework/` is required. It is on the protected surface, so a PR that edits the grammar is human-gated by the grammar already on base (REQ-U5).
- It is also the CI gate's sibling directory, which is what makes the by-path load possible.
- The name `surface_glob.py` says what it is: the grammar for surface-list globs. It is not the CODEOWNERS file parser (that stays in `scripts/oversight/codeowners.py`).

**Constraints (binding; enforced by tests in S1).**
1. **Stdlib only.** It imports from `re`, `sys`, `pathlib`, `argparse` and `typing` only, and never imports a repo package. An AST test enumerates its imports.
2. **Loadable by `spec_from_file_location` without registration in `sys.modules`.** No `@dataclass` (see the `Resolution` note at `scripts/oversight/codeowners.py:235-245`). Results are plain tuples.
3. **No I/O except `load_pattern_file` and `main`.** No subprocess, no network, no environment reads.
4. **Exactly one translator.** The function is named `glob_to_regex`, so REQ-U8's `def glob_to_regex` grep finds exactly this one.

**Public API (binding signatures; technical-design may add private helpers only).**

```python
GRAMMAR_ID = "hos-surface-glob/1"          # quoted in list headers and DECISIONS

class SurfaceGrammarError(ValueError): ...  # pattern/line rejected; message names line and reason

def normalize_path(path: str) -> str | None
    # strip surrounding whitespace, then one leading "./" or "/"; "" -> None

def glob_to_regex(pattern: str) -> "re.Pattern[str]"
    # the ONE translator (AD-3). Raises SurfaceGrammarError. Use with .fullmatch().

def parse_pattern_lines(text: str, *, source: str = "<text>") -> tuple[str, ...]
    # blank and full-line '#' comments skipped; every remaining line validated by
    # glob_to_regex; inline '#' or internal whitespace -> SurfaceGrammarError (AF-7)

def load_pattern_file(path) -> tuple[str, ...]
    # FileNotFoundError if absent (never an empty tuple); else parse_pattern_lines

def compile_patterns(patterns) -> tuple[tuple[str, "re.Pattern[str]"], ...]
    # all-or-nothing: the first bad pattern raises; never a partial list

def first_match(path: str, compiled) -> str | None
    # normalize_path, then the first pattern whose regex fullmatches; None for an empty path

def match_paths(paths, compiled) -> list[tuple[str, str]]
    # (normalized_path, pattern) for every path with a match; empty paths skipped

def to_codeowners_pattern(pattern: str) -> str
    # AD-7. Raises SurfaceGrammarError.

def main(argv=None) -> int
    # --codeowners-lines <list-file> <@owner> : print the generated body lines
    # (formatted '%-42s %s'), exit 0; any error -> stderr + exit 2.
```

**No mode parameter.** The matching semantics are identical for every caller. A caller differs only in what it does on an **error** (AD-4). This is the #559 "opposite fail directions" requirement, put where it belongs: in the error path, not in the grammar. A grammar that is exactly GitHub's neither over- nor under-matches, so neither direction needs a skewed matcher. #559's "a shared matcher cannot serve both" was true of the *skewed* matchers M2 and M5. It is not true of an exact one. M5 nonetheless stays out (ESC-2, §12).

## 2. Where nesting lives

### AD-2: nesting is written in the list, never added by the matcher (replaces ESC-1 (B)'s mode split)

- The grammar is REQ-U1 exactly: GitHub CODEOWNERS path semantics. A pattern containing a non-trailing `/` is root-anchored. A pattern with no such `/` matches at any depth.
- If a list wants "this directory wherever it appears", it says `**/bin/**`. The pm's ESC-1 (B) becomes **(B′): rewrite the affected list lines with a `**/` prefix**, decided per list and per line by the human.
- Under (A) the lines stay as written, and the 11 measured `prompts/` mirrors lose overseer protection.
- In both cases the CI gate, the overseer and CODEOWNERS are **equal** (AF-3), and the list text documents what is protected (F2's complaint is resolved by construction).
- Rejected: **a `protect` mode with an implicit nested fallback.**
  1. It cannot be used in CODEOWNERS resolution (AF-2).
  2. Its behaviour is invisible in the list.
  3. It makes CI ≠ CODEOWNERS a permanent, documented residual (ESC-3).
  4. It widens consumers' CI gate for P1/P2 without the list ever saying so (AF-1).

## 3. Grammar → regex

### AD-3: translation (binding; each rule has oracle rows, and technical-design cites GitHub per row)

Input pattern `p`, after `strip()`:
1. **Reject:** an empty pattern; any whitespace; `#`; `!`; `[`; `]`; `\`; `?` (pending AM-9); `***`; a `**` that is not a whole segment (`a**`, `**b`); and a pattern that is only `/`.
2. **Anchoring.** A leading `/` sets `anchored` and is stripped.
3. **Directory.** A trailing `/` is stripped, and `/**` is appended.
4. **Depth.** If not `anchored`, and the pattern (after step 2, before step 3) contains no `/`, prefix `**/`. Otherwise the pattern is root-anchored.
5. **Tokens**, emitted for `re.fullmatch`:
   - a leading `**/` becomes `(?:.+/)?` (zero or more whole directories, never a name suffix: fixes F5);
   - a medial `/**/` becomes `/(?:.+/)?`;
   - a trailing `/**` becomes `/.+` (everything under the directory, not the directory itself);
   - a pattern that is exactly `**` becomes `.+`;
   - `*` becomes `[^/]*`;
   - every other character is `re.escape`d.
6. **Path side.** `normalize_path` is applied once, by `first_match` and `match_paths`. Matching is case-sensitive. Callers never pre-strip.

`fullmatch` is required. M1 uses `.match` with `$`, and `$` also matches before a trailing newline.

## 4. Callers and failure direction

### AD-4: per-caller wiring and the error path (REQ-U4)

| Caller | Direction | Grammar use | On missing list | On `SurfaceGrammarError` / load failure / any exception |
|---|---|---|---|---|
| CI gate `require_human_approval.main` | deny | `load_pattern_file` + `match_paths` | exit 2 (unchanged) | **exit 2** (new top-level wrapper, AM-7) |
| `touches_protected_surface` | deny | same | ESC-5. Interim: unchanged (False). Recommended: True | True (unchanged contract) |
| `touches_security_surface` | deny | same | False (unchanged; ESC-5 keeps it) | True |
| `_matches_release_path` (M4) | deny | module-level patterns compiled once; the **caller** lowercases the path; patterns are stored lowercase | n/a (constant) | True (new: today an exception propagates) |
| `oversight/codeowners.get_owners_for_path` → `check_pr_files` | deny (CODEOWNERS model) | `glob_to_regex` per entry, exact grammar, last-match-wins | "no CODEOWNERS file" (unchanged) | **ARCH-ESC-2.** Recommended: `check_pr_files` returns `(True, [], "CODEOWNERS unparseable: <line>")` |
| `resolve_human_reviewer` | routing | same as above | unchanged | falls back to `human_reviewer` with `note="CODEOWNERS unparseable"`, never a guessed owner |
| `release_panel_logic.apply_exclusions` | allow | `load_pattern_file` + `first_match` | raises `FileNotFoundError` (unchanged) | raises (nothing excluded silently) |
| `audit_predicate` rule 2 | allow | `compile_patterns` | not-an-audit-PR | not-an-audit-PR (`reason="allowlist-unparseable"`) |
| `gen_codeowners.sh` | generator | `main --codeowners-lines` | exit 2 (unchanged) | exit 2, and the committed CODEOWNERS is left untouched (AF-8) |

**M4 list (AF-9; lossless with respect to M3, verified by AD-8's legacy relation):**
`**/docs/releases/**`, `**/.hos-release`, `**/.hos-release/**`, `**/changelog*`, `**/changelog*/**`, `**/release/v*`, `**/release/v*/**`.
The `/**` forms reproduce fnmatch's slash-crossing trailing `*`. `**/.hos-release` is equivalent to the no-slash `.hos-release` and is written that way for uniformity. The comment that says to keep the list in sync with `protected_surfaces.txt` stays.

## 5. Loading

### AD-5: every caller loads the module by file path from its own location. The CI gate keeps no `sys.path` mutation.

- **`require_human_approval.py`:**
  - At module level: `try: _sg = _load_sibling_module("surface_glob.py")`, `except Exception as e: _sg, _SG_ERR = None, e`. The loader is a copy of `require_overseer_approval.py:49-59`, using `Path(__file__).with_name`, so the sibling of the **running** file in the base checkout is loaded, never cwd and never `PYTHONPATH`.
  - The assignment `glob_to_regex = _sg.glob_to_regex if _sg else _raise_unavailable` keeps the attribute that `audit_predicate`, `release_panel_logic` and the existing tests import. It is an assignment, not a `def`, so AC-1's grep still finds one definition.
  - `load_globs` and `matched_surfaces` keep their signatures and delegate to the module.
  - `main` checks `_sg` first, then runs its whole body inside `try/except Exception → print, return 2` (AM-7).
- **`audit_predicate.py`:** loads `surface_glob.py` directly through its existing `_load_sibling_module`. It no longer loads the module via `require_human_approval.py`.
- **`release_panel_logic.py`:** keeps its existing `sys.path` idiom (it is not a trusted-base gate, so this adds no new idiom) and imports `glob_to_regex, load_pattern_file` from `scripts.framework.surface_glob`.
- **`scripts/oversight/codeowners.py`:** a by-path load of `Path(__file__).resolve().parents[1] / "framework" / "surface_glob.py"`. It is shipped via rsync, and its target is shipped via the list (AD-6).
- **`merge_authority.py`:** a **lazy** by-path load of `Path(__file__).resolve().parents[3] / "scripts/framework/surface_glob.py"`, cached, and performed **inside** each `touches_*`'s existing `try`. A load failure therefore returns True and is never an import-time crash of the overseer's library.
- **Module identity.** Different callers may hold distinct module objects, because a by-path load and a package import produce different identities. So `SurfaceGrammarError` raised by one load is not `isinstance` of another load's class. **Binding:** callers catch `Exception` on the fail-closed path (they already do), never `SurfaceGrammarError` alone.
- **Transition safety.** The PR that makes `require_human_approval.py` depend on the module is gated by base's *self-contained* M1, because the workflow checks out `base.sha`. After it merges, base carries both files. `test_gate_checkout_pinned_base.py` is not touched.

## 6. Shipping

### AD-6: shipped in S1, before any dependant, and guarded by a ship-set test

- S1 adds `scripts/framework/surface_glob.py` to `framework_consumer_files.txt`. That is **earlier** than REQ-U5's "same PR". Shipping an unused stdlib module is harmless, and it removes the window in which a release could be cut between the dependant and the list edit. `.hos-manifest` follows automatically.
- **Ship-set test (S1, binding):**
  - scan every `.py` that is listed in `framework_consumer_files.txt`, plus every `.py` under `scripts/oversight/`;
  - find each by-path load target: a `_load_sibling_module("<x>")` literal, a `.with_name("<x>")` literal, or a `/ "framework" / "<x>"` chain;
  - assert each target is either listed in `framework_consumer_files.txt` or lives under `scripts/oversight/`;
  - a non-literal load argument fails the test.
- The installer's warn-and-skip on a missing listed file (row 10) is **not** fixed here. Changing it affects every listed file, so it is FU-2.

## 7. CODEOWNERS

### AD-7: `to_codeowners_pattern` is the single translation. P1/P2 output stays byte-identical. Only no-slash lines change.

| List line | Emitted | Reason |
|---|---|---|
| `dir/**` (root-anchored) | `/dir/` | unchanged bytes; GitHub-equivalent |
| `a/b/file` (root-anchored) | `/a/b/file` | unchanged bytes |
| `/x` (explicitly anchored) | `/x` | unchanged |
| `NAME` (no slash) | `NAME` | **changed** from `/NAME`. GitHub any-depth now equals the CI gate (ESC-3) |
| `**/dir/**` | `**/dir/` | only under ESC-1 (B′) |
| `**/name` | `**/name` | only under (B′) |
| any other `**` or `*` placement | `SurfaceGrammarError` | the generator refuses anything it cannot prove equal. A new shape needs an AD-7 row and an oracle citation first |

Under (A) with the ESC-3 recommendation, the S4 CODEOWNERS diff is exactly 4 lines: `AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md` and `.hos-release` lose their leading `/`.

`gen_codeowners.sh` keeps its header `echo`s and its owner resolution. It replaces the `while` loop with `python3 "$SCRIPT_DIR/surface_glob.py" --codeowners-lines "$SURFACES" "$OWNER"` and writes through `mktemp "$OUT.XXXXXX"` + `mv` (AF-8). `regen_all.sh --check` also copies `surface_glob.py` into `$FW_DIR` (AF-6).

## 8. Tests

### AD-8: test strategy

- **T-1 GitHub oracle** (`tests/framework/fixtures/surface_glob_oracle.tsv`; hand-written, S0).
  - Columns: `pattern`, `path`, `expected`, `source`, `note`.
  - `source` is a GitHub CODEOWNERS documentation example (cited by section) or `rule:<AD-3 step>` where no example exists.
  - Required rows:
    - every REQ-U9 edge case;
    - every line of all four lists, at root, one-deep, deep, nested under `n/`, and as a suffix/prefix/sibling lookalike;
    - GitHub's documented `docs/*` row (one level only);
    - `apps/` (any depth);
    - `/build/logs/` (anchored);
    - `**/logs`;
    - a case row (`agents.md` ≠ `AGENTS.md`);
    - a literal-as-directory row (`/docs` vs `docs/x`), with `expected` = **unknown** until technical-design cites GitHub (TD-O1);
    - rejected-syntax rows, with `expected` = `reject`.
  - The `expected` column is never computed.
- **T-2 module unit tests (S1):** the oracle against `glob_to_regex` and `first_match`; `parse_pattern_lines` rejecting inline `#` and whitespace; `compile_patterns` being all-or-nothing; `to_codeowners_pattern` for every AD-7 row.
- **T-3 cross-caller equivalence** (`tests/framework/test_surface_equivalence.py`). Grown slice by slice: each wiring slice adds its caller's column, and a caller not yet wired is listed as `pending:<slice>`, never silently skipped. Each caller runs the oracle through its real entry point:
  - `matched_surfaces`;
  - `touches_protected_surface` / `touches_security_surface`, against a `tmp_path` repo root holding a one-line list;
  - `get_owners_for_path`, over a CODEOWNERS fixture generated by `to_codeowners_pattern`;
  - `apply_exclusions`;
  - `audit_predicate` rule 2;
  - `_matches_release_path`, using M4's own list.
- **T-4 legacy relation** (replaces REQ-U9's path snapshot; AF-4, AM-5).
  - `tests/framework/legacy_surface_matchers.py` holds **verbatim** copies of M1, M2, M3 and M4 at `cf1ca09ee`. Its header records the sha256 of each source blob, and a test asserts those hashes against `git show cf1ca09ee:<path>`, so the copies cannot drift.
  - For every currently listed pattern, over `git ls-files` plus the F6 probe set:
    - deny callers: new ⊇ legacy;
    - allow callers: new ⊆ legacy.
  - Ruled exceptions are **predicates**, not path lists: for example "the F5 suffix lookalike: legacy-only match where the path's matching segment ≠ the pattern's literal segment", or "(A): a slash-containing pattern matched only under a non-root prefix". Each predicate cites its DECISIONS entry by date header. A failure prints the offending paths.
  - S0 lands the copies, the hash pin and a characterization test (legacy == current production code). Each later slice switches its caller's relation on.
- **T-5 trusted base and loading (S1, and S3 for the gate).**
  - `test_gate_checkout_pinned_base.py` is unchanged.
  - A grep test asserts no `sys.path` in `require_human_approval.py`.
  - The module loads under `spec_from_file_location` with `sys.modules` left untouched (constraint 2).
  - The AST import allowlist (constraint 1).
  - **Hostile-sibling simulation:** copy `require_human_approval.py`, `surface_glob.py` and `protected_surfaces.txt` into `tmp/a/scripts/framework/`; put a `surface_glob.py` that `sys.exit(0)`s in `tmp/` (as cwd) and on `PYTHONPATH`; run the gate with a protected changed file and no reviews. It must exit 1 (the real module was used).
  - With `surface_glob.py` deleted from the copy, the gate must exit 2.
- **T-6 fail-closed (AC-5).**
  - Unreadable list → True / exit 2.
  - The list line `src/[ab].py` → True / exit 2 / `apply_exclusions` raises / audit not-qualifying.
  - The M4 compile path raising → True.
  - A CODEOWNERS fixture with a `[` line → per ARCH-ESC-2.
- **T-7 last-match-wins (AF-2):** the fixture `/scripts/ @human` plus a later `docs @bot` gives `scripts/mydocs` → `@human` and required.
- **T-8 generator:**
  - P1/P2 output is byte-identical to the committed CODEOWNERS;
  - `regen_all.sh --check` is green;
  - a failing emitter leaves the existing CODEOWNERS byte-identical (AF-8);
  - a `bin/** # x` list line → exit 2 (AF-7).
- **T-9 single definition (REQ-U8, S5):**
  - exactly one `def glob_to_regex` under `scripts/ bootstrap/ bin/`;
  - no `fnmatch` token in `merge_authority.py`;
  - `scripts/automation/lib/codeowners.py::_fnmatch_codeowners` is exempted **by name**, with a pointer to ESC-2.
- **Unchanged pins (REQ-U10):**
  - `test_require_human_approval.py`, including `test_near_misses_do_not_match`. Every row there still holds under the grammar: `AGENTS-GUIDE.md` is not `AGENTS.md`;
  - `tests/oversight/test_codeowners.py`. Any row that pins the F5 over-match is changed only in the slice whose DECISIONS entry rules it, and the PR names the row;
  - `TestKnownDivergenceFromOversightCodeowners`, untouched. Its rows describe M5, which is unchanged. Its M2-side comments become stale; a docstring note is allowed, an assertion edit is not;
  - `test_release_panel_logic.py`;
  - the inner loop.

## 9. Order

### AD-9: binding merge order

S0 → S1 → S2 → S3 → S4 → S5. S2 may merge in parallel with S3/S4 once S1 is in.

Constraints:
- (a) No `**/` line is added to a surface list before S5 (AF-5).
- (b) Each behaviour-changing slice appends its own DECISIONS.md entry before or with its change (AM-8).
- (c) Between S3 and S5, the CI gate runs the new grammar while the overseer runs legacy M3. They disagree only in M3's safe direction (M3 ⊇ new). The F4 root-`auth/` hole persists until S5, as it does today.

## 10. Slices

| Slice | Content | Files | Protected? | Codable before human answers? |
|---|---|---|---|---|
| **S0** | Tests only. `legacy_surface_matchers.py` (verbatim plus a hash pin), the oracle TSV with GitHub citations (TD-O1 rows marked unknown), and the legacy-characterization test. | 3 | no | **Yes** |
| **S1** | `surface_glob.py` (AD-1/AD-3/AD-7 API, `main`); T-2; T-5 loading/import tests (minus the gate run); the ship-set test (AD-6); `framework_consumer_files.txt` +1 line; `SCRIPTS-INDEX.md` regenerated. Nothing calls the module. | 6 | yes (`scripts/framework/**`) | **Yes.** `?` is rejected until TD-O2 resolves. |
| **S2** | Allow-direction callers: `audit_predicate.py` (direct load), `release_panel_logic.py` (import switch), `release_panel_exclusions.txt` (`/SCRIPTS-INDEX.md`, `/.hos-manifest`, grammar header), `audit_allowlist.txt` (header only); T-3/T-4/T-6 allow columns; a DECISIONS entry (grammar, ESC-6, ARCH-ESC-3). | ~8 | `audit_predicate.py` and the allowlist, yes | **No.** Needs ESC-6 and ARCH-ESC-3. |
| **S3** | CI gate: `require_human_approval.py` (AD-5 load, exit-2 wrapper, delegate); `protected_surfaces.txt` header only; T-3/T-4 CI columns; T-5 gate simulation; T-6 exit-2 rows; a DECISIONS entry (P3 widening: `templates/AGENTS.md`, `prompts/AGENTS.md`; the F5 lookalike drop). | ~6 | yes | **No.** Needs ESC-7 and ESC-1's lookalike sub-question. It does **not** need the ESC-1 (A)/(B′) choice. |
| **S4** | CODEOWNERS: `scripts/oversight/codeowners.py` (grammar via by-path load; ARCH-ESC-2 error path); `gen_codeowners.sh` (emitter, atomic write); `regen_all.sh` (copy the module); `.github/CODEOWNERS` regenerated; T-3 CODEOWNERS column; T-7; T-8; `tests/oversight/test_codeowners.py` rows named in the PR; a DECISIONS entry. | ~8 | yes | **No.** Needs ESC-3 and ARCH-ESC-2. Under (B′), S4 must merge before S5. |
| **S5** | Overseer: `merge_authority.py` (`touches_*` and M4 via the lazy load, M4 list per AD-4, ESC-5); `merge_authority_cli.py` (the `not_verified` text if ESC-5 flips); the `security_surfaces.txt` header (plus `**/` rewrites under (B′)); under (B′) also `protected_surfaces.txt` rewrites and a regenerated CODEOWNERS; T-3/T-4 overseer and M4 columns; T-6; T-9; a DECISIONS entry (ESC-1 option with the exact lost or gained paths, ESC-2/4/5, the #559 relationship). If `overseer.md` prose describes the missing-list default, that edit is made by the top-level session only (CLAUDE.md #1347). | ≤13 | yes (and a security surface) | **No.** Needs ESC-1, ESC-2, ESC-4, ESC-5, and ARCH-ESC-1 if (B′). |

Every slice runs `scripts/framework/run_tests_inner_loop.sh` and `regen_all.sh --check`.

## 11. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (F1).** The caller inventory adds `merge_authority_cli.py:601` (per file), `pr_review_cli.py:915` (`evaluate_reviewer_trigger`, ADR-1657 AD-3), `pr_review_cli.py:1165`, and `resolve_human_reviewer` (`pr_review_cli.py:1034`). The last is a **routing** caller (it picks which human to request), and REQ-U2/U3 do not classify it. Add: "its resolved owner for every oracle row equals GitHub's."
- **AM-2 (ESC-1, REQ-U9).** Strike (B)'s `protect`/`exact` modes. Replace them with (B′): nesting is expressed as `**/` lines in the list, per line, and the matcher has one behaviour (AD-2, AF-2, AF-3). REQ-U9's "expected value per mode" becomes "per list text".
- **AM-3 (F9, ESC-7).** Under (B)/(B′), the consumer CI gate also widens for every nested P1/P2 directory (`**/bin/**`, `**/bootstrap/**`, `**/contract/**`, `**/scripts/framework/**`, `**/.github/workflows/**`, …), not only for P3 (AF-1). That is ARCH-ESC-1.
- **AM-4 (ESC-4).** A lossless M4 rewrite needs the `**/` forms *and* `CHANGELOG*/**` (row 8, AD-4). Case-insensitivity comes from the caller lowercasing its input, not from a matcher option.
- **AM-5 (REQ-U9 real-tree check).** Replace "a committed snapshot of today's sets" with frozen, hash-pinned legacy reference matchers evaluated on the live tree (AF-4, T-4).
- **AM-6 (REQ-U5/U6).** Add: `regen_all.sh --check` copies the module into its temp tree (AF-6), and the generator writes atomically (AF-8). Record that `hos_install.sh` warn-skips missing listed files, so the ship-set test is the only guard (FU-2).
- **AM-7 (REQ-U4, F10).** The CI gate today exits **1**, not 2, on any uncaught exception. REQ-U4 therefore requires a new top-level wrapper in `main`, not just preserving today's behaviour.
- **AM-8 (REQ-U7).** One DECISIONS entry per behaviour-changing slice (S2..S5), each listing the pattern deltas *that slice* causes. A single entry would either precede rulings it cannot know or postdate behaviour changes it should gate.
- **AM-9 (REQ-U1 rejected syntax).** GitHub documents `!`, `[ ]` and `\` escaping as unsupported in CODEOWNERS. It does **not** document `?` as unsupported, and gitignore supports it. Technical-design must cite GitHub on `?` (TD-O2). If supported, the grammar implements `?` as `[^/]`, because rejecting it would fail-close every consumer whose CODEOWNERS uses it (ARCH-ESC-2). Add to REQ-U1: inline `#` and internal whitespace are rejected (AF-7).
- **AM-10 (new, REQ-U2).** Add the ordering constraint: no `**/` line in a surface list while a legacy matcher reads it (AF-5, AD-9a).

Endorsed as written: REQ-U3, REQ-U5 (except that shipping moves earlier to S1, which is stricter), REQ-U6, REQ-U8 and REQ-U10.

## 12. Escalations

### Human (pm-agent's; the architect gives a recommended default and does not rule)

| ESC | Architect's recommendation | Technical note | Gates |
|---|---|---|---|
| ESC-1 | **(A): the lists as written, root-anchored, GitHub grammar.** This **differs from pm's (B).** The human is also asked to accept the F5 lookalike drop (concur with pm). | (A) and (B′) produce the same code. Only the list text differs, so the human can change their mind later with a list edit. (A) gives exact equality (CI = overseer = CODEOWNERS = 215/24 on today's tree) and no consumer P1/P2 widening. Its cost is 5 protected + 6 security `prompts/` mirror files (records, not controls; §0 row 5) and future nested P1/P2 copies, which carry no control meaning in HOS because the installer writes controls only at root. If the human wants zero narrowing, (B′) for **`security_surfaces.txt` only** is a free middle path: that file is HOS-only (not shipped), so `**/scripts/automation/lib/**` has no consumer effect. | S5 (S3 only for the lookalike part) |
| ESC-2 | **Exempt M5 by name; retire it separately.** Concur. | AD-1 shows #559's premise does not hold for an exact grammar, so M5 *could* share the module later. That is the retirement issue's argument to make, with the product-boundary checkpoint its docstring requires. | S5 |
| ESC-3 | **No-slash lines emitted unanchored. No invented `**/` lines.** Concur. | Under (A) and AD-2 there is **no residual**: CODEOWNERS equals the CI gate exactly. The pm's "CODEOWNERS ⊆ CI" acceptance is moot. | S4 |
| ESC-4 | **In scope. AD-4's lossless list. Caller-side lowercasing.** Concur, with AM-4. | No matcher option is needed (AF-9). | S5 |
| ESC-5 | **Missing `protected_surfaces.txt` → protected.** Concur. Keep the security variant as is. | The effect reaches `evaluate_reviewer_trigger` (a human reviewer is requested) and `decide_merge_authority` (HUMAN_REQUIRED). `merge_authority_cli`'s "permissive default" note is rewritten. Technical-design enumerates the tests that build a repo root without the list (51 `decide_merge_authority(` call sites, all in `tests/automation/test_phase_b.py`, plus the `surfaces_file_present` rows in `test_merge_authority_cli.py:760-791`). | S5 |
| ESC-6 | **Anchor `/SCRIPTS-INDEX.md` and `/.hos-manifest`.** Concur, with ARCH-ESC-3. | It keeps one grammar and identical match sets. | S2 |
| ESC-7 | **Accept P3 widening and state it in the release notes.** Concur. | Under (A) this is the whole consumer change. Under (B′) for `protected_surfaces.txt`, ARCH-ESC-1 applies as well. | S3 |

### ARCH-ESC (added by the architect; product-boundary checkpoint)

- **ARCH-ESC-1: if the human picks (B′) for `protected_surfaces.txt`, accept that every consumer's required CI check and CODEOWNERS also gate nested `bin/`, `bootstrap/`, `contract/`, `scripts/framework/`, `scripts/oversight/gates/`, `.github/workflows/`, `docs/releases/` and similar directories?**
  - This is user-visible gating and consumer gate load (AF-1), and it is unmeasured for any real consumer.
  - **Recommended: do not.** Choose (A) for `protected_surfaces.txt`.
  - Gates: S5. Only asked if ESC-1 = (B′) for the protected list.
- **ARCH-ESC-2: a consumer CODEOWNERS line the grammar rejects → `check_pr_files` returns HUMAN_REQUIRED (`reason="CODEOWNERS unparseable: <line>"`), and `resolve_human_reviewer` falls back to `human_reviewer`?**
  - GitHub itself skips invalid lines. The model cannot know what GitHub concluded about a line it cannot parse, and skipping one line in a last-match-wins resolver can mis-attribute ownership (AF-2).
  - This is a consumer-visible tightening for any consumer whose CODEOWNERS uses `[`, `!` or `\` (or `?`, if TD-O2 finds it unsupported).
  - **Recommended: yes.**
  - Gates: S4.
- **ARCH-ESC-3: S2's edit to `release_panel_exclusions.txt` changes its sha256, which ADR-1340 AD-3 binds into every release-panel verdict.** Every prior verdict is invalidated, even though the excluded set is identical.
  - **Recommended:** accept, and merge S2 only when no release request is between panel run and authorization.
  - This is product-boundary because it affects release latency.
  - Gates: S2.

### Technical-design obligations (not human items)

- **TD-O1:** cite GitHub for whether a literal, non-glob, non-trailing-slash pattern (`/docs`) also owns `docs/x`. If it does, the CODEOWNERS model (only) adds `p/**` for literal entries, because GitHub-truth there is wider and REQ-U6 requires fidelity. No HOS list is affected: the generator emits no such line.
- **TD-O2:** cite GitHub on `?` (AM-9).
- **TD-O3:** enumerate the tests affected by ESC-5, and every `tests/oversight/test_codeowners.py` row pinning an F5 over-match.

## 13. Follow-ups (named, not filed here)

- **FU-1:** retire M5 (ESC-2).
- **FU-2:** `hos_install.sh` should fail, not warn-skip, when a file listed in `framework_consumer_files.txt` is absent from the source (row 10). This is a protected installer change and affects every listed file.
- **FU-3:** `packs/**` is on no surface list. PACK region bodies become installed agent text in consumers ("CORE and PACK regions are HOS-owned"), yet a worker PR can edit them with only overseer review. It needs a human ruling on adding `packs/**` to `protected_surfaces.txt` (out of scope here per §4).
- **FU-4:** the stale `docs/AGENT-IDENTITY.md` §9.0 list (F2; pm's out-of-scope note).
- **FU-5:** whether the CI gate's `gh pr diff --name-only` reports the *source* path of a rename out of a protected directory is unverified here. If it does not, moving a file out of `bin/` would not be protected-matched. Verify before relying on the gate for renames.

## 14. Affected sign-offs (startup-gap analysis)

- **Should this have been settled in the initial review?** Yes, partly. ADR-035 AD-2 ("exactly one glob dialect") and SPEC-303b B4 ("reuses the glob_to_regex translation semantics") each *declared* a single dialect. Neither tested it, and #1253 then added M3 with a third. This is a `startup-artifact-gap` of the "declared single source, unenforced" family. **Recommended:** the orchestrator annotates #1574 with that label. Per this cycle's constraints, the architect files nothing.
- **These sign-offs stand:**
  - ADR-035 AD-2/AD-5. They are realised by S2; their stated intent is unchanged.
  - ADR-1340 AD-3. The exclusions semantics are unchanged; the hash binding works as designed (ARCH-ESC-3).
  - ADR-1657 AD-3. The trigger predicate is unchanged; only its input matcher changes.
- **These need re-review when their slice lands (built code whose matcher changes):**
  - the SPEC-303b / #396 approvals of `scripts/oversight/codeowners.py` B4. B4's "conservative over-match" rationale is withdrawn by AF-2. Re-checked in S4;
  - the #1253 approval of `touches_security_surface`. Its matcher had the F4 hole. Re-checked in S5;
  - the #559 ruling's *rationale*, not its pinned rows. ESC-2 keeps the rows.

---

## Human Review Required

**RISK: HIGH.** This changes the predicate behind the server-side human-approval gate, the overseer's protected, security and release routing, and CODEOWNERS, in HOS and in every consumer. Every touched production file is on a protected or security surface.

Closed positively:
- the F4 root-`auth/` fail-open (S5);
- the F5 lookalike over-match (S3/S4);
- the last-match-wins mis-attribution (AF-2, S4);
- a premature `**/` line silently disabling root protection (AF-5, AD-9);
- a parser divergence on inline comments (AF-7);
- a consumer CI break from an unshipped module (AD-6, shipped first);
- a permanently red `regen_all.sh --check` (AF-6);
- a truncated CODEOWNERS (AF-8);
- an exception read as "protected, no approval" instead of "tooling error" (AM-7).

**CONFIDENCE: 85%.**
- High on §0: every row was read or measured this session.
- High on AD-1, AD-4..AD-6 and AD-9.
- **Medium on three GitHub oracle edges:** literal-as-directory (TD-O1), `?` (TD-O2), and trailing `/**` on the bare directory path. They are marked `unknown` in the oracle until cited, and none of them affects a current HOS list line.

**BLAST RADIUS.**
- S1: none (inert).
- S2: release-panel exclusions (same set, new hash) and the audit allowlist (same set).
- S3: every PR's `require-human-approval` result, in HOS and in consumers (P3 widening).
- S4: `.github/CODEOWNERS` (4 lines under (A)) and the overseer's CODEOWNERS model and reviewer routing.
- S5: overseer auto-merge eligibility (protected, security and release), plus a fail-closed flip (ESC-5).

**Change classification: STRUCTURAL.** It changes which paths existing controls treat as protected: the CI gate widens; under ESC-1 (A) the overseer narrows by 11 measured record files. It changes consumer-visible gating (ESC-7, ARCH-ESC-1/2) and adds a fail-closed condition (ESC-5). Per the product-boundary checkpoint, ESC-1..7 and ARCH-ESC-1..3 must clear before the slice each one gates. S0 and S1 may proceed now.
