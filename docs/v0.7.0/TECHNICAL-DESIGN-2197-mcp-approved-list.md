# TECHNICAL DESIGN — #2197 MCP approved list (single slice, v0.7.0)

Status: ARCHITECT-REVIEWED 2026-10-28 (APPROVED_WITH_CHANGES; D3 withdrawn into ESC-1). The spec is the issue body plus the binding
ruling (ScottThurlow, CODEOWNER, 2026-10-28). Out of scope (#2199): reporting unlisted MCP
software a human installed, and `.mcp.json` / `mcpServers` registrations.

RISK: HIGH. This slice adds a blocking gate, changes the contract and the installer, and
touches protected surfaces. CONFIDENCE: MEDIUM-HIGH. Change class: `additive`. It adds a
rule and a gate and loosens nothing.

## Human Review Required
- Protected surfaces touched: `contract/**`,
  `scripts/oversight/gates/**`, `scripts/framework/protected_surfaces.txt`,
  `.github/CODEOWNERS`, `docs/AGENT-IDENTITY.md`, plus two new protected files (§1).
- Operational effect: once this merges, any existing oversight venv whose semgrep or mcp is
  not at the listed version fails the new gate (CRITICAL, with the re-sync command printed)
  until someone re-syncs it by hand (§4, ESC-1). That covers every consumer venv on a
  rsync-path upgrade. (The installer's cp fallback already deletes the target `.venv`, so
  those upgrades rebuild from the new pins.) Main's clones resolve semgrep 1.179.0 /
  mcp 1.29.0 today, so they pass.

## Decisions (made within the ruling; no ESC needed)
- **D1. Pin exactly.** `requirements.txt` changes `semgrep>=1.50` to `semgrep==1.179.0` and
  adds `mcp==1.29.0`, with a comment saying it is install-only and must never be imported.
  1.179.0 is what main's oversight venv resolves today, and its METADATA was checked:
  `Requires-Dist: mcp==1.29.0`. It also meets the existing `pyjwt>=2.15.0` floor
  (semgrep 1.179.0 requires `pyjwt[crypto]>=2.15.0,<3`). Without an exact pin, a fresh
  install would resolve the newest semgrep and fail the check. Architect check
  (2026-10-28): 1.179.0's METADATA has no `certifi` edge (certifi arrives via `requests`,
  whose floor is far below 2026.10.19), and `click~=8.4.2`, `tomli~=2.4.0`,
  `typing-extensions~=4.2` and `jsonschema~=4.25.1` don't conflict with any other floor in the
  file. So the pin and the existing floors resolve together. The coder **must reword two
  stale comments**: the pyjwt block ("this floor also resolves semgrep to >=1.179.0" no
  longer has any effect once semgrep is pinned) and the certifi block ("Latest semgrep
  itself requires certifi>=2026.10.19" describes a semgrep version HOS no longer installs;
  keep the floor and its #2147 reason). Declaring `mcp` explicitly
  has two effects: the static check can see it, and if a future semgrep needs a different
  `mcp`, the conflict shows up as a pip resolution error rather than as silent drift. The
  coder may choose 1.181.0 instead, but only if `security_scan` requires it, and only after
  re-reading that version's METADATA for the same conflicts. The list entry and the pin
  must always match.
- **D2. Govern HOS's dependency closure only.** `ensure_venv.sh` also installs the
  consumer's own root `requirements*.txt` into the same venv (#956). So the installed-tree
  check governs only the closure reachable from HOS's own requirement files. An MCP
  distribution outside that closure is printed as a non-blocking NOTE. Treating it any
  other way is #2199's job, so v0.7.0 does not pre-empt it. If a consumer dependency
  changes the version of an `mcp` that is inside HOS's closure, the gate still fails,
  because HOS's dependency changed.
- **D3. WITHDRAWN by architect → ESC-1 (see "Open questions").** This slice does not
  change `hos_install.sh`. An existing venv on upgrade is handled by the gate failing
  closed (CRITICAL), with the printed remediation (§4). Whether the installer should
  itself run `pip install` into an existing consumer venv is a product-boundary decision,
  not an architecture one: it would mutate a venv the consumer shares with its own
  requirements (#956), it could downgrade consumer packages to HOS's exact pins, it adds
  a network-dependent mutation to an installer that runs no pip today, and in `--pr`
  mode it would change the environment before the upgrade PR is approved.
- **D4. Standalone gate, not part of security_scan.** The new gate needs no network and
  no file list. Keeping it separate means a pip-audit outage or a bandit finding can never
  mask it, and it cannot mask them. Being on the list does not exempt a package from
  `security_scan` (#2194 handles mcp's advisories separately).
- **D5. Mode semantics.** `mode` describes what HOS may *execute*. semgrep is `run`, as the
  CLI scanner, with `forbidden_subcommands: ["mcp"]`. mcp is `install-only` with
  `modules: ["mcp"]`. The never-run tests read these fields (§6). They are not duplicated
  as constants.

## 1. Files (13; 14 if ESC-1 = B)

| # | File | Change |
|---|---|---|
| 1 | `scripts/oversight/mcp_approved_list.json` | NEW. The list (§2). |
| 2 | `scripts/oversight/mcp_policy_logic.py` | NEW. List loader, detection, checks, CLI (§3). |
| 3 | `scripts/oversight/gates/mcp_policy.sh` | NEW. Thin gate wrapper (§4). `run_gates.sh` finds it automatically because it discovers `gates/*.sh`. |
| 4 | `scripts/oversight/requirements.txt` | D1 pins. |
| 5 | `scripts/framework/protected_surfaces.txt` | Add exact paths for #1 and #2, using the same per-file style as `security_scan_logic.py`. |
| 6 | `.github/CODEOWNERS` | Regenerate with `scripts/framework/regen_all.sh`. Never hand-edit. |
| 7 | `SCRIPTS-INDEX.md` | Regenerate with `regen_all.sh`. |
| 8 | `docs/AGENT-IDENTITY.md` | §9 code block: add #1 and #2 (this doc must stay in sync with #5). |
| 9 | `contract/OVERSIGHT-CONTRACT.md` | New §9 (§7). |
| 10 | ~~`bootstrap/hos_install.sh`~~ | Not changed unless ESC-1 = B (§5). |
| 11 | `scripts/oversight/smoke_test.sh` | One required `check` line (§5). |
| 12 | `tests/oversight/test_mcp_policy.py` | NEW (§6). |
| 13 | `tests/oversight/test_security_scan_exemptions.py` | Derive PR4/PR5 from the list (§6). |
| 14 | `tests/oversight/test_gate_arg_grammar.py` | Only if a gate-enumerating test there requires every gate to be listed. Coder checks. |

## 2. List file: format and schema

JSON (Python 3.10 has no `tomllib`; strict parsing suits fail-closed). Exact shape:

```
{"schema_version": 1,
 "entries": [
  {"package": "semgrep", "version": "1.179.0", "mode": "run",
   "forbidden_subcommands": ["mcp"],
   "reason": "<CLI scanner for the JS/TS lint pass; its built-in MCP server is never started>",
   "approved_pr": <N>},
  {"package": "mcp", "version": "1.29.0", "mode": "install-only", "modules": ["mcp"],
   "reason": "<required by semgrep at this exact version; never imported or executed by HOS>",
   "approved_pr": <N>}]}
```

`<N>` is the number of the PR that implements this issue. The coder writes it in a commit
on the same branch after `submit_pr.sh` returns the number, before review. The CODEOWNER
approval on that PR is what makes the entry valid. The protected-surface gate enforces
that approval. This checker does not and cannot.

`load_list(path)` raises `ListError`, and the CLI exits 2, on any of the following. The
list fails closed:
- The file is unreadable, or the JSON is invalid.
- The top level is not an object with exactly the keys `schema_version` and `entries`.
- `schema_version != 1`.
- `entries` is missing, empty, or not a list.
- An entry is missing a required key or has an unknown key. Required keys: `package`,
  `version`, `mode`, `reason`, `approved_pr`. Optional keys, valid only for their mode:
  `modules` (install-only) and `forbidden_subcommands` (run).
- `package` is not a string equal to `packaging.utils.canonicalize_name(package)`.
- `version` does not parse with `packaging.version.Version`.
- `mode` is not one of `install-only` or `run`.
- `reason` is empty or whitespace.
- `approved_pr` is not an `int` greater than 0. `bool` is rejected.
- An `install-only` entry has no `modules`. `modules` must be a non-empty list of dotted
  Python identifiers.
- `modules` appears on a `run` entry.
- `forbidden_subcommands` is not a list of `^[a-z0-9][a-z0-9-]*$` strings.
- A canonical package name appears twice.

## 3. Detection and check algorithms (`mcp_policy_logic.py`)

Use `packaging` (a declared dependency) for names, versions, requirements and markers.
Reuse `canonicalize_name`; do not write a new canonicaliser. `canon(n)` means
`canonicalize_name(n)`. `has_mcp_token(s)` is true iff `"mcp"` is one of the pieces of
`re.split(r"[^a-z0-9]+", s.lower())`. Under that rule `mcp-server-git`, `semgrep-mcp` and
`mcp.cli` match, while `fastmcp` and `smcp` do not. Those two are caught by R3 if they
depend on mcp.

**`is_mcp_dist(name, requires, entry_points)`** is true iff any rule holds:
- R1: `canon(name) == "mcp"`.
- R2: `has_mcp_token(canon(name))`.
- R3: any `Requires-Dist` entry whose requirement name satisfies R1 or R2. This holds
  **regardless of markers or extras**. It is deliberately conservative, so an optional
  `mcp` extra counts.
- R4: any entry point, in any group, where `has_mcp_token(ep.name)` is true or
  `has_mcp_token` is true of the module part of `ep.value` (before `:`). Example:
  `mcp.cli:app`.

An unparseable `Requires-Dist` line in the metadata raises `CheckError` (exit 2).

**Static check, `check_requirements(files, approved)`.** HOS requirement files are
`scripts/oversight/requirements.txt` plus any other `requirements*.txt` under `scripts/`,
`bootstrap/` or `bin/`. The consumer's root requirement files are never included. For each
line:
1. Strip `#` comments (at line start or after whitespace) and skip blank lines.
2. A line starting with `-` (`-r`, `-c`, `--index-url`, …) raises `CheckError` (exit 2).
   Options are unsupported in HOS files, which have none today.
3. Parse the line with `Requirement`. Failure raises `CheckError`.
4. If the name is on the list, the specifier set must be exactly one `==` specifier with
   no wildcard, and `Version(spec.version) == Version(entry.version)`. Anything else is a
   violation: `<file>:<line> <name><spec> — listed version is ==<v>`.
5. If the name is not on the list but satisfies R1 or R2, it is a violation:
   `unlisted MCP package`.

Static reading cannot see R3 or R4 without metadata. The installed check below covers
those.

**Installed check, `check_installed(dists, root_reqs, approved)`.** `dists` is an iterable
of `Dist(name, version, requires: list[str], entry_points: list[(group,name,value)])`.
The CLI adapter builds it from `importlib.metadata.distributions()` (or from `path=[...]`
when `--site-path` is given, which only tests do).
1. Index the dists by `canon(name)`. A duplicate canonical name raises `CheckError`.
2. Walk the closure. The queue starts with `(canon(r.name), r.extras)` for every root
   requirement from the static files. For a dist `d` with requested extras `E`, follow
   each `Requires-Dist r` iff `r.marker is None` or `r.marker.evaluate({"extra": e})` is
   true for some `e` in `E ∪ {""}`. A followed edge whose target is not installed raises
   `CheckError("venv inconsistent: <parent> requires <r> but it is not installed")`.
   A root requirement that is not installed raises the same `CheckError`, with `<parent>`
   set to the requirement file. A root requirement whose own marker is false for the
   running interpreter is skipped. HOS's files carry no root markers today.
   Re-visit a dist only when it brings newly requested extras.
3. For every `d` in the closure where `is_mcp_dist(d)` is true, the package must be on the
   list and `Version(d.version)` must equal the listed version. Violations:
   `unlisted MCP package <n>==<v> (via <parent chain>)` or
   `<n>==<v> installed, list says ==<listed>`.
4. For every MCP dist **outside** the closure, print
   `NOTE (not gated until #2199): <n>==<v> is an MCP package outside HOS's dependency closure`.
   This line never affects the exit code.

**CLI.** `python -I mcp_policy_logic.py --list <path> --requirements <file>... [--installed] [--site-path <dir>]`.
Exit codes: 0 = clean, 1 = one or more violations (each printed on its own line), 2 =
cannot check (`ListError` / `CheckError`, with the message printed). The script is
read-only: it writes no files and makes no network calls. The default `--requirements`
set is the HOS-file discovery rule above, rooted at the repo root derived from
`__file__`.

## 4. Gate (`gates/mcp_policy.sh`)

Follow the `security_scan.sh` conventions: `set -euo pipefail`, source `ensure_venv.sh`,
`check_suspension.sh` (gate name `mcp_policy`) and `lib/changeset.sh`, then call
`hos_changeset_parse mcp_policy "$@"`.
- `STATUS=empty` → `hos_changeset_not_checked mcp_policy`, then exit 0. This is the
  shared convention; the output says it is not a pass.
- `unscoped`, `all`, `ok` → run the full check. Print `mcp_policy: dependency-tree check
  — changeset file list not used`. Drift can arrive without any diff, so the check is
  never narrowed to the changed files.
- `$OVERSIGHT_PYTHON` is not executable after sourcing → print
  `GATE FAIL [CRITICAL]: oversight venv unavailable — MCP policy NOT CHECKED (this is not a pass)`
  and exit 1.
- Run `PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" -I <logic> --list <list> --installed`.
  - rc 0 → `OK: mcp_policy — all MCP packages in HOS's closure are listed at listed versions`, exit 0.
  - rc 1 → `GATE FAIL [CRITICAL]: unapproved MCP software — see violations above`, then
    print the remediation (update the list through a CODEOWNER-approved PR, or re-sync:
    `scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt`),
    exit 1.
  - Any other rc → `GATE FAIL [CRITICAL]: MCP policy could not be checked — failure to check, not a clean result`, exit 1.
- The wrapper never passes `--site-path` and offers no environment override for the list
  path. An override would be a route to disabling the gate.

## 5. Installer and smoke test

- **`hos_install.sh` — only if ESC-1 = B.** Default (ESC-1 = A): no installer change.
  The v0.6.0→v0.7.0 upgrade acceptance is then verified by #2137's smoke test. That test
  performs the documented re-sync after its upgrade step (the same command the gate
  prints) and then runs the check below. Option B's design, kept so it can be added
  without another design round: right after the `scripts/oversight/` sync block (around
  line 1893).
  If `$TARGET_REPO/scripts/oversight/.venv/bin/pip` exists, run
  `pip install --quiet -r scripts/oversight/requirements.txt` in that venv.
  - Use the installer's `run` / `dry_run` conventions.
  - On failure, `warn` with the exact manual command and say that `mcp_policy` will fail
    until the venv is re-synced. The install itself continues: a network failure must not
    abort an upgrade, and the gate fails closed anyway.
  - Do nothing when no venv exists. `ensure_venv.sh` builds a fresh one from the
    just-pinned file.
  - Do not install the consumer's project requirements here.
- **`smoke_test.sh`**, under "Oversight venv scanners", inside the
  `if source ensure_venv.sh` branch:
  `check "mcp approved list" true "$VENV_BIN/python3" -I "$SCRIPT_DIR/mcp_policy_logic.py" --list "$SCRIPT_DIR/mcp_approved_list.json" --installed`.
  This is read-only, so it is safe in the Human sandbox. #2137 (the install/upgrade smoke
  test) is **still open, not landed** (checked 2026-10-28). This slice does not build
  #2137. When it lands, it calls `smoke_test.sh` or the same CLI after its fresh install
  and after its v0.6.0→v0.7.0 upgrade. The coder posts a comment on #2137 naming that
  command. No label changes.

## 6. Test plan

Unit tests use synthetic `Dist` tuples, or fake `.dist-info` directories under
`tmp_path`. They never use the real venv. The temp files must follow the zero-leak rule.

`tests/oversight/test_mcp_policy.py`:
- `test_real_list_loads_with_ruling_entries`: exactly two entries. semgrep is `run` with
  `forbidden_subcommands == ["mcp"]`. mcp is `install-only` with `"mcp" in modules`. Both
  have `approved_pr > 0`.
- `test_real_requirements_pin_listed_versions`: the static check on the real HOS files
  returns no violations, and the semgrep and mcp pins equal the list.
- `test_list_schema_rejects[...]`, parametrized over each §2 rule (11 or more cases). Each
  case asserts `ListError` and CLI exit 2.
- `test_is_mcp_dist[...]`. Positive cases: R1 `mcp`; R2 `mcp-server-git`; R3 semgrep with
  `mcp==1.29.0`; R3 `mcp; extra == "ai"`; R4 entry point value `mcp.server:run`; R4 entry
  point name `my-mcp`. Negative cases: `requests`, `fastmcp` with no mcp dependency,
  `smcp`, and a dependency on `mcpclient`.
- `test_static_unlisted_mcp_requirement_fails`, an **acceptance** case: adding
  `mcp-server-git==1.0` produces exit 1.
- `test_static_floating_listed_pin_fails`: `semgrep>=1.50` produces exit 1.
- `test_static_semgrep_bump_fails_until_list_updated`, an **acceptance** case:
  `semgrep==1.181.0` against the current list produces exit 1. With the list entry
  updated it produces exit 0.
- `test_static_option_line_and_garbage_fail_closed`: `-r x.txt` and an unparseable line
  each produce exit 2.
- `test_installed_clean_closure_passes`.
- `test_installed_semgrep_pins_new_mcp_fails`, an **acceptance** case: semgrep 1.181.0
  requiring `mcp==1.30.0`, with mcp 1.30.0 installed and the list unchanged, gives two
  violations. With both entries updated it passes.
- `test_installed_transitive_unlisted_fails`, an **acceptance** case: root `foo` → `bar`
  → `mcp`. Here `bar` is flagged through R3, and the violation names the chain.
- `test_installed_outside_closure_is_note_only`: a consumer-only `mcp-server-x` produces
  the NOTE line and exit 0.
- `test_marker_false_edge_not_followed` and `test_extra_edge_followed_only_when_requested`.
- `test_installed_missing_dep_duplicate_dist_bad_metadata_fail_closed`: three cases, each
  exit 2.
- `test_cli_reads_fake_dist_info_dirs`: writes `METADATA` and `entry_points.txt` under
  `tmp_path`, runs the CLI with `--site-path`, and asserts exit codes 0 and 1.
- `test_gate_empty_changeset_not_checked`: `gates/mcp_policy.sh --empty-changeset` exits 0
  and prints `NOT CHECKED`.
- `test_gate_source_invariants`: the gate script uses `-I`, contains no `--site-path`,
  defines no environment override for the list path, and maps every non-zero rc to exit 1.
- `test_bootstrap_pip_sites_install_no_mcp`: in tracked `*.sh` files under `bootstrap/`,
  `bin/` and `scripts/`, no `pip install` line names a token satisfying R1 or R2. Also
  asserts that `hos_bootstrap.sh`'s `ANALYSIS_PKGS` contains no MCP name.
- `test_protected_surfaces_cover_list_and_logic`: both exact paths appear in
  `protected_surfaces.txt`. The existing `tests/framework/test_codeowners_current.py`
  covers CODEOWNERS.
- `test_contract_states_mcp_rule`: `contract/OVERSIGHT-CONTRACT.md` contains the §9
  anchor sentence.

`tests/oversight/test_security_scan_exemptions.py` keeps the PR4/PR5 coverage and makes
the list its source:
- PR4: the forbidden patterns are built from every `run` entry's `forbidden_subcommands`
  by `_invocation_pattern(pkg, sub)`. This generalises the current `_SERVE_MCP` regex.
  `test_pr4b` keeps its cases but runs them against `_invocation_pattern("semgrep","mcp")`.
- PR5: the banned modules are the union of `modules` across all `install-only` entries.
  The AST walk is unchanged.
- PR5b (the MCP-client regex) is unchanged.
- NEW `test_pr5d_list_keeps_mcp_never_run`: asserts the list still marks `mcp`
  install-only with module `mcp`, and still forbids `semgrep mcp`. The failure message is
  `_PREMISE_59951` / `_PREMISE_2194`. Without this test, flipping the list would silently
  weaken the premise of the #2194 exemption.

The PR's acceptance mapping: an unlisted MCP dependency fails CRITICAL (static and
transitive tests); a semgrep bump fails until the list is updated (static and installed
tests); a `semgrep mcp` invocation or `import mcp` fails (PR4/PR5); the contract states the
rule (contract test).

## 7. Contract wording (new `## 9. MCP software (approved list)`)

> HOS installs MCP software only if it is on the approved list,
> `scripts/oversight/mcp_approved_list.json`. "MCP software" is any distribution that is
> the `mcp` package, depends on it, or provides an MCP server or client entry point
> (detection rule: `scripts/oversight/mcp_policy_logic.py`). Each entry names the exact
> package and version, the reason, the mode (`install-only` or `run`) and the approving PR.
> HOS executes only entries marked `run`, and never a subcommand an entry forbids. HOS
> never imports or starts an `install-only` entry. The list is a protected surface: an
> entry is added or changed only through a PR approved by a CODEOWNER. The `mcp_policy`
> gate fails (CRITICAL) when HOS's requirement files or its resolved dependency closure
> contain MCP software that is not listed, or listed at another version. Being on the list
> does not exempt a package from `security_scan`. Unlisted MCP software outside HOS's
> closure and Claude Code MCP server registrations are governed by #2199.

## 8. Boundaries
- The logic module must not use the network, write files, or import `mcp` or semgrep.
- No `.mcp.json` or settings handling in this slice. That is #2199.
- `ensure_venv.sh` is not modified. `hos_install.sh` is not modified unless ESC-1 = B.
- Do not file issues or change labels. The only exception is the informational comment on
  #2137 described in §5.

## Open questions for a human
**ESC-1 (architect, 2026-10-28). Should the installer re-sync an existing consumer venv on
upgrade?** This must be answered before merge, not before coding.
- **A (default; the coder builds this):** no installer change. After an upgrade, a stale
  venv fails `mcp_policy` CRITICAL and the failure prints the one-line re-sync command.
  The acceptance "a v0.6.0→v0.7.0 upgrade contains exactly the listed packages" is then
  read as "after the documented re-sync step". #2137's smoke test runs that step. This is
  the smaller change and consistent with #2164.
- **B:** `hos_install.sh` runs `pip install -r scripts/oversight/requirements.txt` into an
  existing target venv (§5). The upgrade meets the acceptance with no manual step. In
  exchange the installer gains network-dependent mutation of a venv the consumer shares,
  with possible downgrades of consumer packages to HOS's exact pins, including during
  `--pr` mode before approval.
If B is chosen, add file #10 (§5) on this branch before merge. Nothing else changes.
