# Requirements Spec — Issue #335: Move Semver Bump Arithmetic, Authored-Notes Gate, and Asset Verification from cut_release.sh to Python

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #335
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

`scripts/framework/cut_release.sh` contains three blocks of correctness-sensitive logic
implemented entirely in shell, in violation of the #314 policy ("prefer Python for logic,
shell for launch — establish testability as a code review criterion"):

**1. Semver bump arithmetic (lines 111–121):** The script splits the latest tag on `.` using
`IFS='.'`, increments the appropriate field, and rebuilds the version string. This logic has
a known fragility: a pre-release tag such as `v0.3.0-rc1` sets `PA="0-rc1"`, and the
subsequent `PA=$((PA+1))` coerces that to `1` by bash integer arithmetic — silently producing
`v0.3.1` from a `v0.3.0-rc1` base tag when a patch bump was intended. The final-string
semver validation on line 123 catches the reconstructed string but not the intermediate
field corruption, so the bug can only surface in parametric tests that cannot be written for
an inline shell block.

**2. Authored-notes gate (lines 131–132):** A `grep -cv '^[[:space:]]*$'` counts non-blank
lines in the release notes file and requires at least 5. The check is correct for normal
inputs, but: the `-cv` flag combination (invert-match + count) is easy to misread as
"count matching lines"; the minimum of 5 is an unnamed magic constant; and exercising the
check with corner-case inputs (empty file, file with only blank lines, file with exactly 4
or 5 non-blank lines) requires creating fixture files and running the full script.

**3. Asset verification loop (lines 256–263):** The script checks that uploaded GitHub
release assets are present by matching each expected name against a space-delimited string
built from `gh release view … -q '.assets[].name'`. The pattern match (`case " $got " in
*" $n "*`) is a list-membership test over structured data — exactly the kind of logic #314
classifies as belonging in Python, not shell.

All three blocks involve deterministic rules (version arithmetic, threshold comparison,
set-membership) that are directly unit-testable as Python functions. The shell script's
remaining work — checking preconditions, invoking `git`, invoking `gh`, managing draft/publish
state, building asset temp directories — is genuinely shell launch work and stays in shell.

---

## 2. Scope

### In scope

- Extract the **semver bump arithmetic** into a named Python function in a new module at
  `scripts/oversight/release_logic.py`.
- Extract the **authored-notes gate** into a named Python function in that same module.
- Extract the **asset-presence verification** into a named Python function in that same module.
- Update `cut_release.sh` to call the Python module for each of these three decisions; the
  shell script must not re-implement the logic.
- All three functions must be unit-testable with synthetic input without running
  `cut_release.sh`, invoking `git`, or invoking `gh`.

### Out of scope

- The precondition checks (branch detection, dirty-tree check, HEAD/remote sync check) —
  these invoke `git` directly and stay in shell.
- The validation gate invocation (`run_framework_validation.sh`) — stays in shell.
- The draft/publish flow (`gh release create`, `gh release edit`) — stays in shell.
- The SHA256 checksum computation and asset temp directory construction — stays in shell.
- The release notes file composition and `--generate-notes` fallback — stays in shell.
- The `--prerelease` / `--latest` flag logic for GitHub's `/releases/latest/` resolution —
  stays in shell.
- Threshold values or minimum-line constants are not added to any configuration file by this
  spec; if the architect decides constants should be configurable, that is a separate issue.

---

## 3. Requirements

### R1 — Semver bump function

The module must expose a function that, given a latest release tag string and a bump type
string, computes and returns the next version string. The function must accept:

- `latest_tag: str` — the most recent release tag (e.g., `"v0.3.0"`, `"v0.3.0-rc1"`, or
  `""` if no prior tag exists)
- `bump: str` — one of `"major"`, `"minor"`, `"patch"` (case-insensitive)

The function must return a string of the form `"vMAJOR.MINOR.PATCH"` where MAJOR, MINOR, and
PATCH are non-negative integers.

The behavior must match the current shell logic exactly for well-formed tags:
- A `""` or absent latest tag is treated as `"v0.0.0"`.
- `bump="patch"` increments PATCH, leaves MAJOR and MINOR unchanged.
- `bump="minor"` increments MINOR, resets PATCH to 0, leaves MAJOR unchanged.
- `bump="major"` increments MAJOR, resets MINOR and PATCH to 0.

The function must raise a named exception (not silently produce a wrong value) if:
- `latest_tag` is non-empty but cannot be parsed as `vMAJOR.MINOR.PATCH` or
  `vMAJOR.MINOR.PATCH-<prerelease>` (e.g., a corrupted tag).
- `bump` is not one of `"major"`, `"minor"`, `"patch"`.

For a tag with a pre-release suffix (e.g., `"v0.3.0-rc1"`), the function strips the suffix
before arithmetic — so `bump_version("v0.3.0-rc1", "patch")` returns `"v0.3.1"` (not `"v0.3.1"`
from coerced `"0-rc1"+1`). This is the current shell behavior restored correctly, not a new
behavior.

### R2 — Authored-notes gate function

The module must expose a function that checks whether a release notes file satisfies the
authored-notes requirement. The function must accept:

- `path: str` — filesystem path to the release notes file
- `min_content_lines: int` — minimum number of non-blank lines required (default: 5, matching
  the current shell threshold)

The function must return a boolean: `True` if the file exists, is non-empty, and contains at
least `min_content_lines` non-blank lines; `False` otherwise.

The function must handle the case where the file does not exist (return `False`), matching the
`[[ ! -s "$_notes_path" ]]` check on line 131 of the current script.

### R3 — Asset-presence verification function

The module must expose a function that checks which expected assets are missing from an
uploaded set. The function must accept:

- `uploaded: list[str]` — the asset names actually present on the GitHub release (as reported
  by `gh release view … -q '.assets[].name'`, one name per element)
- `expected: list[str]` — the asset names that must be present

The function must return a list of strings: the names from `expected` that are absent from
`uploaded`. An empty list means all expected assets are present.

The function must use exact string equality for membership testing — not substring or pattern
matching — resolving the space-delimited string fragility in the current shell loop.

### R4 — Shell calls Python for all three decisions

`cut_release.sh` must be updated to invoke the Python module for:

1. The semver bump (replacing lines 111–121): call the R1 function, receive the new version
   string, and set the shell `VERSION` variable to the result.
2. The authored-notes gate (replacing line 132): call the R2 function, and if it returns
   `False`, emit the current error messages and exit 1.
3. The asset-presence check (replacing lines 256–263): call the R3 function with the uploaded
   names and expected names, and if the result is non-empty, emit the current cleanup-and-exit
   behavior.

The shell script must not duplicate the logic. The Python module receives its inputs as
command-line arguments; it does not invoke `git` or `gh`.

### R5 — Unit-testable without a live release run

The functions introduced by R1, R2, and R3 must perform no subprocess calls, no network
calls, and no `git` or `gh` invocations. R1 and R3 must be purely computational (no file I/O).
R2 reads a local file by path but performs no subprocess or network calls.

All three functions must be importable and callable in a Python unit test with synthetic
inputs (fixture strings or temp files for R2).

A CLI shim (`if __name__ == "__main__"`) may be provided for the shell integration, but the
underlying logic functions must be pure with respect to the above constraints.

---

## 4. Acceptance Criteria

**AC1 — Patch bump from well-formed tag:** `bump_version("v0.3.2", "patch")` returns
`"v0.3.3"`. `bump_version("v0.3.2", "minor")` returns `"v0.4.0"`. `bump_version("v0.3.2",
"major")` returns `"v1.0.0"`.

**AC2 — Absent/empty latest tag:** `bump_version("", "patch")` returns `"v0.0.1"`.
`bump_version("v0.0.0", "minor")` returns `"v0.1.0"`.

**AC3 — Pre-release suffix stripped:** `bump_version("v0.3.0-rc1", "patch")` returns
`"v0.3.1"` (not `"v0.3.1"` from coerced arithmetic — the function must parse the numeric
fields cleanly before computing, which produces the same result but through correct logic).

**AC4 — Bad bump type raises:** `bump_version("v0.3.0", "hotfix")` raises a named exception
rather than silently producing a wrong value.

**AC5 — Authored-notes gate:** Given a file with 5 non-blank lines and 2 blank lines,
`check_authored_notes(path)` returns `True`. Given a file with 4 non-blank lines,
`check_authored_notes(path)` returns `False`. Given a non-existent path,
`check_authored_notes(path)` returns `False`.

**AC6 — Asset verification:** `verify_assets_present(["hos_install.sh", "SHA256SUMS"],
["hos_install.sh", "hos_bootstrap.sh", "SHA256SUMS"])` returns `["hos_bootstrap.sh"]`.
`verify_assets_present(["a", "b", "c"], ["a", "b", "c"])` returns `[]`.

**AC7 — Shell integration — version bump:** Running `cut_release.sh --dry-run --bump minor`
with a repo whose latest tag is `v0.3.2` produces output showing `"release version: v0.4.0"`,
identical to the current script output.

**AC8 — Shell integration — authored-notes blocking:** Running `cut_release.sh --bump minor`
with a missing `docs/releases/v0.4.0.md` exits 1 and emits the current error text about
authored release notes, identical in behavior to the current script.

**AC9 — No logic duplication:** `cut_release.sh` contains no inline `python3 -c` fragments,
no `IFS='.'` semver splits, and no `grep -c` authored-notes threshold checks after this
change.

---

## 5. Non-Requirements

- **No behavior change.** The refactored script must exit with the same codes and produce the
  same user-visible output as the current script for all inputs within the existing contract.
- **No new release features.** This spec does not add new bump types (e.g., `rc`, `alpha`),
  new note authorship checks (e.g., bot-detection beyond line count), or new asset types.
- **No change to the release notes minimum.** The 5-line threshold is extracted as-is; it
  becomes the default for `min_content_lines`. Changing the threshold value is out of scope.
- **No change to configuration surface.** Thresholds do not move to `config.sh` or any
  environment variable; they remain function defaults unless the architect decides otherwise
  in an open question below.
- **No change to `--skip-validation` or `HOS_ALLOW_UNVALIDATED` behavior.** Those are shell
  concerns and stay in shell.

---

## 6. Open Questions

**OQ-1 — Module placement**
This spec names the new module `scripts/oversight/release_logic.py` for consistency with the
`scripts/oversight/` home of other extracted Python logic (`panel_logic.py`,
`suspension_manager.py`, etc.). The issue body suggested `scripts/framework/release_logic.py`.
The architect should confirm whether the oversight subdirectory or the framework subdirectory
is the correct home, given that `cut_release.sh` lives in `scripts/framework/`.

**OQ-2 — Shell integration interface for R1 and R3**
The R1 and R3 functions return a string and a list respectively. The shell script could call
the module as: (a) a CLI that prints the result to stdout (shell captures via command
substitution), or (b) a module imported by a thin Python wrapper that the shell invokes once
for all three decisions. Option (a) is a natural fit for the current per-decision call sites;
option (b) reduces the number of Python subprocess invocations per release cut but requires
the wrapper to handle all three use cases. The architect should rule on the preferred interface.

**OQ-3 — Pre-release tag behavior**
The spec requires that `bump_version("v0.3.0-rc1", "patch")` returns `"v0.3.1"`. This
matches the corrected intent (strip suffix, increment clean fields). However, an argument can
be made that bumping from a pre-release tag should increment to the same version with no
suffix (i.e., `"v0.3.0-rc1"` + patch = `"v0.3.0"`, promoting the pre-release to a full
release). The architect should rule on which behavior is correct for HOS; this spec defaults
to the "strip suffix, increment" interpretation which is a straightforward correction of the
current coercion bug.

**OQ-4 — Asset verification and `gh` output format**
The R3 function receives `uploaded` as a list of strings. In the shell integration, that list
is populated from `gh release view … -q '.assets[].name'` output. The architect should
confirm whether the shell integration should parse this with a Python call (e.g.,
`subprocess.check_output(["gh", ...])`) or whether the shell populates the list and passes it
to Python as arguments, keeping the `gh` call in shell.

---

## 7. Context for Architect

- The logic being extracted is at lines 111–121 (semver), 131–132 (authored-notes gate), and
  256–263 (asset verification) of `scripts/framework/cut_release.sh`.
- The `scripts/oversight/` directory already contains `panel_logic.py`,
  `suspension_manager.py`, `signoff_gate.py`, and others — the extraction pattern is well
  established in this codebase.
- Issue #314 is the policy driver. Issues #331 through #334 and #337–#338 are sibling
  refactors that apply the same pattern to other scripts (`run_second_review.sh`,
  `run_panel.sh`, `run_framework_validation.sh`, etc.).
- The `--dry-run` path in `cut_release.sh` currently prints what it _would_ do without
  executing `git` or `gh` commands; the Python module must work correctly for dry-run inputs
  (the semver bump is called regardless of dry-run; the authored-notes gate is called
  regardless of dry-run).
- The `check_authored_notes` function's `min_content_lines` default is 5. If the architect
  decides this should be configurable via `scripts/framework/config.sh`, that is an additive
  change requiring a spec update before implementation.
