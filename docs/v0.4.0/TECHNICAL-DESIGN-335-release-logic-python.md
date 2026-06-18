# Technical Design — Issue #335: Extract Semver Bump, Authored-Notes Gate, and Asset Verification to Python

**Document type:** Technical design (contract for the coder)
**Status:** For architect review
**Issue:** #335
**Spec:** `docs/specs/SPEC-335-release-logic-python.md`
**Precedent:** `scripts/oversight/second_review_logic.py` (SPEC-331)
**Author:** technical-design agent
**Date:** 2026-06-17

---

## 0. Architect bindings (governing)

This design is constrained by the following ratified architect bindings. Where they
resolve a spec Open Question, the binding governs.

1. **New module** `scripts/oversight/release_logic.py` (resolves OQ-1: oversight
   subdirectory, matching the established extraction home — `panel_logic.py`,
   `second_review_logic.py`, `suspension_manager.py`).
2. **Shell integration is stdout capture** (resolves OQ-2 toward option (a), NOT a
   wrapper). Each decision is a separate Python invocation; the shell captures the
   result with command substitution. Per-requirement transport:
   - **R1 `bump-version`** — prints the new version string to stdout; shell captures
     via `$(...)`.
   - **R2 `check-notes`** — communicates via **EXIT CODE** (0 = pass, 1 = fail). It
     prints nothing to stdout; the shell branches on `$?`.
   - **R3 `verify-assets`** — prints the missing asset names, one per line, to
     stdout. Empty output = all present.
3. **Pre-release tag bump: strip suffix then increment** (resolves OQ-3). A
   pre-release suffix is discarded before arithmetic, then the requested field is
   incremented: `bump_version("v0.3.0-rc1", "patch")` → `"v0.3.1"`. A `ValueError`
   is raised on unparseable tags and bad bump types.
4. **`gh` stays in shell** (resolves OQ-4). Python never spawns `gh` or `git`. The
   shell runs `gh release view … -q '.assets[].name'` and passes the resulting asset
   names as argv to R3.
5. **`min_content_lines=5` stays as a function default** — not configurable via
   `config.sh` in this spec.
6. **Stdlib only.** No third-party imports. No subprocess, no network. R1 and R3 do
   NO file I/O (pure-computational). R2 reads the notes file by path (its only I/O)
   and is kept as a separately named I/O function.

---

## 1. Module contract — `scripts/oversight/release_logic.py`

### 1.1 Module-level conventions (match `second_review_logic.py`)

- Module docstring stating purpose, spec/issue, purity guarantees, and which
  function does I/O (only R2 + the `__main__` shim).
- `from __future__ import annotations` immediately after the docstring.
- Stdlib imports only: `argparse`, `re`, `sys`. No third-party imports.
- Module-level constants named with a leading underscore.
- All decision logic in named module-level functions; the `if __name__ ==
  "__main__"` shim is the only code that reads argv / writes stdout.

### 1.2 Constants

```
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
_BUMP_TYPES = {"major", "minor", "patch"}
_DEFAULT_MIN_CONTENT_LINES = 5
```

- `_SEMVER_RE` accepts an optional leading `v`, three non-negative integer fields,
  and an optional `-<prerelease>` suffix that is matched but NOT captured (it is
  discarded — binding 3). Anchored at both ends so a corrupted tag fails the match.
- `_BUMP_TYPES` is the closed set for R1 validation.

---

## 2. R1 — `bump_version(tag: str, bump_type: str) -> str`

**Signature:** `bump_version(tag: str, bump_type: str) -> str`

**Contract:**

- Inputs:
  - `tag` — the most recent release tag (e.g. `"v0.3.0"`, `"v0.3.0-rc1"`, or `""`).
    An empty or whitespace-only `tag` is treated as `"v0.0.0"` (spec R1; current
    shell `base="${LATEST_TAG:-v0.0.0}"`).
  - `bump_type` — one of `"major"`, `"minor"`, `"patch"`, **case-insensitive**
    (normalize with `.strip().lower()` before the membership check).
- Output: a string `"vMAJOR.MINOR.PATCH"` with non-negative integer fields and a
  literal leading `v`.

**Algorithm (exact):**

1. Normalize `bump_type = bump_type.strip().lower()`. If it is not in `_BUMP_TYPES`,
   raise `ValueError(f"invalid bump type: {bump_type!r}")`.
2. If `tag` is empty or whitespace-only, set `tag = "v0.0.0"`.
3. Match `tag` against `_SEMVER_RE`. If no match, raise
   `ValueError(f"unparseable tag: {tag!r}")`. The match **discards** any pre-release
   suffix (binding 3) — only the three numeric capture groups are read.
4. Bind `major, minor, patch = int(g1), int(g2), int(g3)`.
5. Apply the bump:
   - `major` → `major + 1`, `minor = 0`, `patch = 0`
   - `minor` → `minor + 1`, `patch = 0` (major unchanged)
   - `patch` → `patch + 1` (major, minor unchanged)
6. Return `f"v{major}.{minor}.{patch}"`.

**Boundaries:**

- MUST NOT spawn `git`/`gh` or read any file. Pure function of its two arguments.
- MUST raise `ValueError` (the named exception, spec R1/AC4) on bad bump type and on
  unparseable non-empty tags. It MUST NOT silently coerce a malformed field (this is
  the exact bug the spec corrects — `"0-rc1"` must never become `1`).
- The output is NOT re-validated against the suffix grammar; R1 always emits the
  clean `vX.Y.Z` form. The shell's existing line-123 semver assertion still runs and
  will pass.

**Acceptance mapping:** AC1 (well-formed patch/minor/major), AC2 (empty → `v0.0.1`,
`v0.0.0`+minor → `v0.1.0`), AC3 (`v0.3.0-rc1`+patch → `v0.3.1`), AC4 (bad type raises).

---

## 3. R2 — `check_authored_notes(notes_path: str, min_lines: int = 5) -> bool`

**Signature:** `check_authored_notes(notes_path: str, min_lines: int = _DEFAULT_MIN_CONTENT_LINES) -> bool`

**Contract:**

- Inputs:
  - `notes_path` — filesystem path to the release-notes file.
  - `min_lines` — minimum number of non-blank lines required; default `5`
    (binding 5; spec R2; mirrors the shell `-lt 5`).
- Output: `True` iff the file exists, is readable, and contains **at least
  `min_lines` non-blank lines**; `False` otherwise.

**Algorithm (exact):**

1. Attempt to open and read `notes_path` (UTF-8). On any `OSError` (including file
   not found), return `False` — this reproduces the shell `[[ ! -s "$_notes_path" ]]`
   miss-or-empty behavior (spec R2, AC5 non-existent → `False`).
2. A line is "non-blank" iff it contains at least one non-whitespace character —
   i.e. `line.strip() != ""`. This matches the shell `grep -cv '^[[:space:]]*$'`
   (count lines that are NOT entirely whitespace).
3. Count non-blank lines; return `count >= min_lines`.

**Boundaries:**

- This is the ONLY logic function that performs file I/O (binding 6) — named
  distinctly so its I/O is explicit.
- MUST NOT spawn a subprocess (no `grep`).
- An empty file and a missing file both yield `False` (the shell's `-s` test fails
  for both).

**Acceptance mapping:** AC5 (5 non-blank + 2 blank → `True`; 4 non-blank → `False`;
non-existent → `False`).

---

## 4. R3 — `verify_assets_present(uploaded: list[str], expected: list[str]) -> list[str]`

**Signature:** `verify_assets_present(uploaded: list[str], expected: list[str]) -> list[str]`

**Contract:**

- Inputs:
  - `uploaded` — asset names actually present on the release (from
    `gh release view … -q '.assets[].name'`, one name per element).
  - `expected` — asset names that must be present.
- Output: the list of names from `expected` that are absent from `uploaded`,
  **preserving the order of `expected`**. An empty list means all present.

**Algorithm (exact):**

1. Build `present = set(uploaded)`.
2. Return `[name for name in expected if name not in present]`.

**Boundaries:**

- Membership is **exact string equality** via the set (binding 4 / spec R3) — NOT
  substring/pattern matching. This fixes the space-delimited `case " $got " in
  *" $n "*` fragility.
- Pure: no file I/O, no subprocess. MUST NOT spawn `gh`.
- Order of the returned missing list follows `expected` (deterministic for the
  shell's per-line consumption and for AC6).

**Acceptance mapping:** AC6 (`["hos_install.sh","SHA256SUMS"]` vs the 3-name expected
→ `["hos_bootstrap.sh"]`; all present → `[]`).

---

## 5. CLI shim — `if __name__ == "__main__"` (binding 2)

`argparse` with three subcommands. The shim is the only place that reads argv and
writes stdout / sets exit codes.

### 5.1 `bump-version`

- Args: `--tag <str>` (default `""`), `--bump <str>` (required).
- Action: call `bump_version(tag, bump)`. On success print the version string to
  stdout and exit 0. On `ValueError`, print the message to **stderr** and exit 2
  (usage/tooling error — matches the shell's `exit 2` for invalid bump on line 119
  and the version-format `exit 2` on line 123).

### 5.2 `check-notes`

- Args: `--path <str>` (required), `--min-lines <int>` (optional, default 5).
- Action: call `check_authored_notes(path, min_lines)`. Print **nothing** to stdout.
  Exit 0 if `True`, exit 1 if `False` (binding 2 — exit-code transport). The shell
  emits the user-facing error text and does the `exit 1`; Python only signals the
  boolean via its exit code.

### 5.3 `verify-assets`

- Args: `--expected <name> [<name> ...]` (required, nargs+), `--uploaded <name>
  [<name> ...]` (optional, nargs*, default empty — an empty upload set is valid input
  meaning "nothing uploaded", and every expected name is then missing).
- Action: call `verify_assets_present(uploaded, expected)`. Print each missing name
  on its own line to stdout (binding 2). Empty output = all present. Always exit 0
  (the shell decides what to do with a non-empty list); a non-empty missing list is a
  data result, not a CLI error.

### 5.4 `main(argv: list[str] | None = None) -> int`

Builds the parser, dispatches via `set_defaults(func=...)`, returns the int exit
code. `if __name__ == "__main__": raise SystemExit(main())`.

---

## 6. Shell integration — `scripts/framework/cut_release.sh` (R4)

The Python module is invoked via the repo's Python (prefer the oversight venv if
present, else `python3`, matching `run_tests_inner_loop.sh`'s resolution). Define a
helper near the top of the script:

```
PYBIN="$REPO_ROOT/scripts/oversight/.venv/bin/python"
[[ -x "$PYBIN" ]] || PYBIN="python3"
RELEASE_LOGIC="$REPO_ROOT/scripts/oversight/release_logic.py"
```

### 6.1 Semver bump (replaces lines 111–121)

The inline `IFS='.'` block is replaced by a stdout capture. On a Python error
(`ValueError` → exit 2), the `$(...)` capture is empty and `$?` non-zero; preserve
the script's invalid-bump exit-2 semantics:

```
if [[ -z "$VERSION" ]]; then
  if ! VERSION="$("$PYBIN" "$RELEASE_LOGIC" bump-version --tag "${LATEST_TAG:-}" --bump "$BUMP")"; then
    err "invalid --bump: $BUMP"; exit 2
  fi
fi
```

Line 123's `[[ "$VERSION" =~ ^v[0-9]+\.… ]]` semver assertion and line 124's
tag-exists check are UNCHANGED (they validate a `--version`-supplied value too).

### 6.2 Authored-notes gate (replaces line 132's grep test)

The `[[ ! -s … ]] || [[ "$(grep -cv …)" -lt 5 ]]` compound test becomes a call whose
exit code is the gate. The surrounding `if [[ "$BUMP" == "minor" || … \.0$ ]]`
condition and the three `err` lines + `exit 1` are UNCHANGED:

```
if ! "$PYBIN" "$RELEASE_LOGIC" check-notes --path "$_notes_path"; then
  err "minor/major release ${VERSION} requires AUTHORED release notes at ${_notes_path}"
  err "  (it is missing or too short). Write them, commit, and re-run."
  err "  Patch releases may use GitHub auto-generated notes."
  exit 1
fi
```

### 6.3 Asset-presence check (replaces lines 256–263)

The `got="$(gh release view …)"` call STAYS in shell (binding 4). Its output is split
into argv and passed to `verify-assets`. The `case " $got " in *" $n "*` loop is
replaced by capturing the missing list:

```
mapfile -t got < <(gh release view "$VERSION" --json assets -q '.assets[].name' 2>/dev/null)
missing="$("$PYBIN" "$RELEASE_LOGIC" verify-assets \
  --expected "${ASSET_NAMES[@]}" SHA256SUMS \
  --uploaded ${got[@]+"${got[@]}"})"
if [[ -n "$missing" ]]; then
  gh release delete "$VERSION" --yes --cleanup-tag 2>/dev/null || true
  err "asset(s) missing after upload: $(echo "$missing" | tr '\n' ' ')— cleaned up draft + tag. Re-run."
  exit 1
fi
```

Note: `mapfile` requires bash 4; the rest of the script is bash-3.2-portable. The
coder MUST use a bash-3.2-safe read loop to populate `got` (e.g. a `while IFS= read`
loop) to honor the script's stated portability, OR confirm with the architect that
this call site may rely on bash 4. **Open for coder: prefer the portable read loop.**
The `--expected` list is `"${ASSET_NAMES[@]}" SHA256SUMS` — the same expected set the
original loop iterated (`"${ASSET_NAMES[@]}" SHA256SUMS`).

### 6.4 AC9 — no logic duplication

After this change `cut_release.sh` MUST contain: no `IFS='.'` semver split, no
`grep -c`/`grep -cv` notes threshold check, and no inline `python3 -c` fragment. The
`case " $got " in` membership loop is removed.

---

## 7. Tests — `tests/oversight/test_release_logic.py`

Match the import shim used by `test_second_review_logic.py` (`importlib.util` load
by absolute path so the test does not depend on package layout).

Required cases:

- **R1:** AC1 (patch/minor/major from `v0.3.2`), AC2 (empty → `v0.0.1`, `v0.0.0`
  minor → `v0.1.0`), AC3 (`v0.3.0-rc1` patch → `v0.3.1`; also assert it is NOT the
  coerced `v0.3.2`), AC4 (`hotfix` raises `ValueError`), case-insensitive bump
  (`"Patch"`, `"MINOR"`), unparseable tag (`"garbage"`, `"v1.2"`) raises `ValueError`.
- **R2:** AC5 (tmp file 5 non-blank + 2 blank → `True`; 4 non-blank → `False`;
  non-existent path → `False`), empty file → `False`, custom `min_lines`.
- **R3:** AC6 (one missing → `["hos_bootstrap.sh"]`; all present → `[]`), empty
  `uploaded` → all expected returned in order, order preservation.

These are pure / temp-file unit tests (no `git`, no `gh`, no live release run) — they
run in the inner-loop tier.

---

## 8. Parity / no-behavior-change checklist (spec §5)

| Behavior | Old | New | Same? |
|---|---|---|---|
| empty latest tag | `v0.0.0` base | `tag=""` → `v0.0.0` base | yes |
| patch/minor/major arithmetic | shell case | R1 case | yes |
| `v0.3.0-rc1`+patch | **buggy** `v0.3.1` via coercion | `v0.3.1` via clean parse | yes (value), corrected mechanism |
| invalid `--bump` | `exit 2` | R1 `ValueError` → shell `exit 2` | yes |
| notes missing/empty | `False` → `exit 1` | R2 `False` → `exit 1` | yes |
| notes < 5 non-blank | `exit 1` | R2 `False` → `exit 1` | yes |
| asset missing | cleanup + `exit 1` | non-empty missing → cleanup + `exit 1` | yes |
| user-visible text | unchanged | unchanged (emitted by shell) | yes |

---

## 9. Self-flag

**RISK:** LOW — refactor of three deterministic, already-tested-by-behavior shell
blocks into pure Python with parity ACs; the only intended behavior change is the
correction of the documented pre-release coercion bug (spec-sanctioned).
**CONFIDENCE:** HIGH — sibling extraction (`second_review_logic.py`) is the exact
precedent; contract is fully specified by spec ACs + architect bindings.
**Change class:** additive (new module) + clarifying (shell call sites).
No `## Human Review Required` block required (LOW risk, not structural).

---

## 10. Request for architect review

Bindings 1–6 are reflected verbatim. One coder-facing item is flagged in §6.3 (the
bash-3.2-portable read loop vs. `mapfile`) — recommend the portable read loop to
preserve the script's stated bash-3.2 support; not an architecture decision, but
noted so the coder does not silently introduce a bash-4 dependency.
