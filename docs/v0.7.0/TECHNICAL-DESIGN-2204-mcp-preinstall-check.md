# TECHNICAL DESIGN — #2204 MCP policy checked before install (single slice, v0.7.0)

Status: APPROVED_WITH_CHANGES by architect 2026-10-30 (round 1; changes A1-A7 applied in place). Spec: issue #2204. Builds on
`docs/v0.7.0/TECHNICAL-DESIGN-2197-mcp-approved-list.md` (TD-2197). Its §8 said
"`ensure_venv.sh` is not modified". This design deliberately supersedes that line.

RISK: HIGH. The slice touches one protected surface (`scripts/oversight/mcp_policy_logic.py`)
and `ensure_venv.sh`, which every gate and validator sources, so a bug here can take down
every gate at once. CONFIDENCE: MEDIUM-HIGH. Change class: `additive`. It adds a refusal
before install, and the post-install gate stays as it is.

## Human Review Required
- Protected surface touched: `scripts/oversight/mcp_policy_logic.py` (CODEOWNER approval).
- Operational effect: building a venv now fails closed (no venv at all) when the pre-install
  check refuses or cannot run. That includes a fresh venv on a platform whose ensurepip pip
  lacks `pip._vendor.packaging` (see D2). Today, on the same platform, the venv builds and
  only `mcp_policy` fails. hos-cron's missing-venv self-heal then exits 78 (fail closed), so
  an unlisted MCP line on `main` stops autonomous cycles until it is fixed. That is intended.
- Accepted residual (D7): an unlisted MCP package pulled in *transitively* is still installed
  before it is detected. Detection is post-install. A wheel can ship a `.pth` file that runs at
  every later interpreter start in that venv, so "installed but not yet trusted" is not the same
  as "inert". Closing this waits on the lockfile decision (#2180 ESC-1). The CODEOWNER approving
  this PR is accepting that residual; contract §9 is amended to state it (file 5).

## Problem
`ensure_venv.sh::_create_venv` runs `pip install -r scripts/oversight/requirements.txt`, then
the consumer's root requirements. The `mcp_policy` gate checks the policy afterwards.
So if someone adds an unlisted MCP package to the requirements file, it is installed first,
and any sdist build hooks run, before the gate fails. This is CWE-863, authorization after
the action.

## Decisions

- **D1. Where and when the check runs.** In `_create_venv`, right after
  `python3 -m venv "$VENV"` succeeds. That is **before** the pip self-upgrade and before
  every `pip install`. `python3 -m venv` runs only stdlib code and ensurepip's bundled pip
  wheel, and installs nothing from any requirements file. The smoke-test rebuild path also
  calls `_create_venv`, so both the create path and the re-create path are covered, and
  there is a single call site.
- **D2. Interpreter and imports.** The check runs under the new venv's own interpreter:
  `PYTHONSAFEPATH=1 "$VENV_BIN/python3" -I <logic> ...`. This is the same isolation the
  gate uses. It is not run under the bootstrap `python3`, whose site-packages vary and may
  not contain `packaging`. *Deviation from the issue text (architect A1):* #2204 Required-1
  says "under the bootstrap interpreter". The fresh venv's interpreter is the bootstrap
  interpreter plus ensurepip's local pip wheel. Nothing from any requirements file and nothing
  from the network has been installed at that point, so the acceptance criterion ("no package
  from that file is installed") still holds, and the import surface is deterministic.
  `mcp_policy_logic.py` replaces its three top-level `packaging`
  imports with a fallback chain:
  1. `packaging.*`. This is present in the fully built venv, because it is a declared
     requirement.
  2. `pip._vendor.packaging.*`. This is present in a fresh ensurepip venv.
  The choice is **atomic per source** (architect A2): try all three `packaging` imports in one
  `try`; on `ImportError` only, try all three `pip._vendor.packaging` imports in one `try`.
  Never mix modules from the two sources, since `Version` and the specifier objects must come
  from the same library. Catch `ImportError`, never a bare `except`.
  3. If neither imports, print `mcp_policy: cannot check: packaging unavailable (neither
     packaging nor pip._vendor.packaging importable)` to stderr and `sys.exit(2)`.
     A traceback must never escape here.
  Verified 2026-10-30 on this machine: a fresh `python3 -m venv` (Python 3.14.4, pip
  25.1.1) imports `pip._vendor.packaging` 25.0, including `requirements`, `utils` and
  `version`, under `-I`, and has no top-level `packaging`. `pip._vendor` is not a public
  pip API, which is why step 3 fails closed: if a future pip, or a debundled distro pip,
  drops it, the result is a loud refusal, never a bypass.
  - *Alternative rejected: a stdlib-only static mode.* It would need a second PEP 508
    name parser and canonicaliser next to `packaging`. Any disagreement between that parser
    and the one pip uses would itself be a bypass route. Using `pip._vendor.packaging` means
    the check reads the requirement with the same library pip uses to interpret the file.
    TD-2197 §3 also forbids writing a new canonicaliser.
  - *Accepted residual:* the self-upgraded pip that does the real install may vendor a
    newer `packaging` than the one the check used. Both are `packaging`, and the
    post-install gate catches any drift (D6).
- **D3. Scope: only the file `_create_venv` is about to install.** The check passes
  `--requirements "$_ENSURE_VENV_DIR/requirements.txt"` explicitly. It does not use
  `discover_requirement_files()`. Reasons:
  - The rule is "authorize the thing about to be installed". The other discovered files
    under `scripts/`, `bootstrap/` and `bin/` are not installed by `ensure_venv.sh`, so
    they stay the gate's concern.
  - On a consumer repo, discovery would also walk consumer-owned `scripts/**/requirements*.txt`.
    Those may contain `-r` lines, which raise `CheckError`, and that would block every
    venv build. Today it only fails one gate.
  - `scripts/oversight/requirements.txt` is framework-owned (synced WHOLE by `hos_install.sh`)
    and has no option lines. An option line in it is refused (exit 2), which is correct.
  - The consumer root requirements (`_install_project_requirements`) are **not**
    pre-checked. They are outside HOS's policy scope (TD-2197 D2; #2199 owns
    outside-closure). They commonly use `-r` and `-c` lines, and the gate only prints a
    NOTE for them anyway. The pre-check runs before the oversight install, which in turn
    runs before the consumer install, so a refusal also prevents the consumer install.
- **D4. Bash contract (`_create_venv`).**
  - First, **before `python3 -m venv`** (architect A3): if `mcp_policy_logic.py` or
    `mcp_approved_list.json` is missing next to `ensure_venv.sh`, emit the fail-closed message
    and `return 1`. There is no venv yet, so nothing needs removing.
  - Capture the exit code explicitly: `local rc=0; <check> >&2 || rc=$?`. This is needed
    because some callers source this file under `set -euo pipefail` (for example
    `gates/mcp_policy.sh`) and others under no options. `_create_venv` is always called
    from an `if !` context, where errexit is suppressed, so the code must neither depend
    on `set -e` firing nor be killed by it. The checker's stdout (the `VIOLATION:` lines)
    goes to stderr, so `--quiet` and stdout-capturing callers still show it.
  - `rc=0`: carry on with the self-upgrade and the installs, unchanged.
  - `rc=1`: `_evenv_err "MCP policy: refusing to install oversight requirements — unapproved MCP software (see above); update scripts/oversight/mcp_approved_list.json via a CODEOWNER-approved PR"`.
  - Any other rc (2, the 2 Python returns for a missing script or an argparse error, 126,
    127, and so on): `_evenv_err "MCP policy could not be checked — refusing to install (fail closed)"`.
  - On any non-zero rc: `rm -rf "$VENV"`, then `return 1`. No pip command of any kind has
    run at that point.
- **D5. Refusal cannot loop and is never treated as ready.**
  - Create path: `_create_venv` fails, the script exits 1, and `.venv` is gone. The next
    invocation sees no `python3` and runs the create path again, which refuses again.
    Each invocation does exactly one check.
  - Smoke path: the script removes `.venv`, `_create_venv` refuses, "Venv rebuild
    failed", and the script exits 1. There is no retry.
  - In both paths the marker file is never written, because it is written only after a
    smoke test passes, and `OVERSIGHT_PYTHON` is not executable. So any gate that
    somehow continued would hit its own "venv unavailable" fail-closed branch.
  - Removing `.venv` prevents a later invocation from seeing a bare ensurepip venv as an
    existing one. If it did, the smoke test would rebuild it, which is safe but noisy.
- **D6. The post-install gate is unchanged** (`gates/mcp_policy.sh --installed`). It
  remains the drift control and the only transitive control (D7). It also covers existing
  venvs, which `ensure_venv.sh` never re-syncs.
- **D7. Transitive enforcement before install: DEFERRED (recorded decision).** The
  candidate is `pip install --dry-run --report <f> --only-binary=:all: -r requirements.txt`
  (pip ≥ 22.2), then feeding the report's resolved metadata to `is_mcp_dist`. It is not
  adopted, for these reasons:
  1. Without `--only-binary=:all:`, resolution builds sdists to get their metadata, and
     that runs the very build hooks this issue is about.
  2. With it, resolution fails for any distribution in the closure that has no wheel for
     the running platform. The closure is 116 distributions in the current oversight venv, including platform-wheel
     packages: `semgrep`, `tree-sitter*`, `black`, `mypy`. Whether every one has a wheel on
     every platform HOS supports was not verified, and a gap would turn a policy check into
     a venv-build outage.
  3. It adds a network round trip and a second resolution. Between the dry run and the
     real install the index can change (TOCTOU), so the resolved set is not guaranteed to
     be the installed set unless the install is pinned to the report, with hashes. Pinning
     to the report is in effect a lockfile.
  4. Installing a wheel runs no build hook, which removes the issue's main threat (sdist
     build hooks). *Correction (architect A4):* this does not make the wheel inert. A wheel can
     ship a `.pth` file. `site` executes `import` lines in it at every later interpreter start
     in that venv, including the smoke test and the post-install gate itself (`-I` does not
     disable `site`). This residual is accepted, not eliminated. It needs a change to a
     dependency that a CODEOWNER does not review (a floor-pinned package's new release pulls
     in an MCP package). HOS's whole venv build already trusts those releases for non-MCP code
     in the same way. It is recorded under Human Review Required and in contract §9.

  Recommendation: the closure is enforced statically before install once a hashed lockfile
  exists, because then every transitive package is a direct, pinned line that the D3 check
  already reads. That fits with the open lockfile question (#2180 ESC-1). The worker should
  record this deferral on #2204, or file a follow-up issue. This design files nothing.

## Files (one slice, 5 files plus this doc)

| # | File | Change |
|---|---|---|
| 1 | `scripts/oversight/ensure_venv.sh` | D1, D4 pre-install check in `_create_venv`. Add a header comment naming #2204 and the fact that the post-install gate is still the drift control. |
| 2 | `scripts/oversight/mcp_policy_logic.py` | D2 import fallback. Update the docstring: the module may run in a fresh ensurepip venv. No other behaviour change. PROTECTED. |
| 3 | `tests/oversight/test_mcp_policy.py` | New tests (below). |
| 4 | `tests/automation/test_ensure_venv.py` | Harness changes and new tests (below). |
| 5 | `contract/OVERSIGHT-CONTRACT.md` §9 | (architect A5) Append two sentences: "`ensure_venv.sh` checks the oversight requirements file against the list before it installs anything and refuses to build the venv on a violation or when the check cannot run. MCP software that arrives only as a transitive dependency is detected after install by the `mcp_policy` gate, not prevented: a transitively installed package's wheel `.pth` may already have run by then, and consumer root `requirements*.txt` files are not pre-checked (outside the policy closure, #2199) (#2204)." PROTECTED; the PR already needs CODEOWNER approval for file 2. |

`requirements.txt`, the list, the gate and `hos_install.sh` are unchanged.
The installer already syncs `scripts/oversight/` WHOLE, so consumers receive the logic
file and the list next to `ensure_venv.sh`. Not regenerating `SCRIPTS-INDEX.md` is fine
unless the first header line of file #1 changes. If it does, run `regen_all.sh`.

## Test plan (no network; all temp under `tmp_path`, zero-leak rule)

`tests/oversight/test_mcp_policy.py`:
- `test_packaging_fallback_to_pip_vendor`: run the CLI in a subprocess
  (`sys.executable -I -c ...`) that first sets `sys.modules["packaging"] = None` (and the
  three submodules), then calls `runpy.run_path(logic, run_name="__main__")` with
  `--list <real list> --requirements <tmp file>`. Assert exit 1 for
  `mcp-server-git==1.0` and exit 0 for `mcp==1.29.0`. Skip if
  `pip._vendor.packaging` cannot be imported in the test interpreter.
- `test_no_packaging_fails_closed`: the same, but also block `pip._vendor.packaging*`.
  Assert exit 2, the `packaging unavailable` message on stderr, and no `Traceback`.
- Existing tests are unchanged and must still pass on the top-level `packaging` path.

`tests/automation/test_ensure_venv.py`:
- Harness: write a placeholder `mcp_policy_logic.py` and `mcp_approved_list.json` into
  `script_dir`, so the D4 file-presence check passes. In the stub `python3`, when the args
  contain `mcp_policy_logic.py`, append to a separate `HOS_TEST_POLICY_CALL_LOG`, echo
  `VIOLATION: test` when `HOS_TEST_POLICY_EXIT=1`, and exit with
  `${HOS_TEST_POLICY_EXIT:-0}`. This branch goes **before** the stub's catch-all fallback
  (architect A6). The check's argv starts with `-I`, so without that ordering it would reach
  the pip-logging fallback. Do not write to the pip log, so existing pip-call
  assertions are unaffected. All existing tests must pass unchanged.
- `test_policy_violation_refuses_install`: `HOS_TEST_POLICY_EXIT=1` on a fresh build.
  Assert rc ≠ 0, `VIOLATION` and `refusing` in stderr, an empty pip log (no self-upgrade,
  no `-r`), `.venv` absent, and no marker.
- `test_policy_cannot_check_refuses_install[2,127]`: the same assertions, with the
  fail-closed message.
- `test_policy_missing_logic_file_refuses`: delete the placeholder. Assert refusal and an
  empty pip log.
- `test_policy_runs_before_any_pip_call`: a clean run with a project `requirements.txt`.
  The policy log has exactly one call, which includes
  `--requirements <script_dir>/requirements.txt` and does not include the project file.
- `test_smoke_rebuild_refusal_no_loop`: a pre-existing fake venv, a failing smoke test and
  `HOS_TEST_POLICY_EXIT=1`. Assert rc ≠ 0, exactly one policy call, `.venv` absent, and no
  marker.
- `test_acceptance_real_interpreter_refuses_unlisted_mcp` (**acceptance**): use the real
  system `python3`, with no stub on PATH. Copy the real `ensure_venv.sh`, the logic file
  and the list into `tmp_path/repo/scripts/oversight/`, and write a requirements file
  containing `mcp-server-git==1.0`. Run the script. Assert rc ≠ 0, a `VIOLATION ...
  unlisted MCP package mcp-server-git` line in stderr, and `.venv` absent. The refusal
  happens before any pip call, so the test needs no network. It exercises the real
  `pip._vendor` fallback. Skip if `python3 -I -c "import ensurepip, venv"` fails. Do not
  probe by building a second venv. A fresh venv is about 13 MB and the refusal removes it, so
  the run stays inside the temp budget. The listed-package
  "still installs normally" half of the acceptance is covered by the stubbed
  `rc=0` tests plus the existing creation tests. A real install needs the network and is
  out of scope for unit tests.
- **Real "listed packages still install" evidence (architect A7):** CI already builds a fresh
  venv with `bash scripts/oversight/ensure_venv.sh` on Python 3.12 (`tests.yml` and
  `oversight-gates.yml`). That runs the real pre-check with the real requirements file and
  ensurepip's real pip, then the real install. The implementing PR must cite those green steps
  as the evidence for the second acceptance bullet. A red venv step there is a blocking defect
  in this slice, not flake.

## Boundaries
- The checker stays read-only. It makes no network calls, writes no files, and never
  imports `mcp` or `semgrep`. The fallback imports only `pip._vendor.packaging`; it must
  not import `pip._internal`.
- The check has no environment override, no skip flag, and no `--site-path`. That matches
  the gate (TD-2197 §4). `HOS_SKIP_PROJECT_REQUIREMENTS` does not affect the pre-check.
- Do not change how the consumer root requirements are installed, and do not pre-check
  them (D3).
- Do not file issues or change labels (D7 is reported back to the worker).
