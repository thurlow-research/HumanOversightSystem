# REQUIREMENTS-2066: Project-configured milestones, scope and threat model for the checkpoint red-team

**Status:** Draft for architect review.
**Change classification: STRUCTURAL.** It removes existing behavior: the four built-in
milestones `auth | booking | admin | deploy`, with their scope and attack text. It also adds new
behavior: a project config file for milestones, a generic `--scope` / `--paths` mode, and a new
optional `config.sh` key. Under pm-agent CORE, adding or removing behavior is structural however
small the change is. The build should not start until a human has ruled on ESC-1, or accepted its
default.
**Date:** 2026-10-18
**Author:** pm-agent (autonomous worker cycle). No human was present, so open questions are
listed as ESC items.
**Tree read at:** `5216bf7c2` (branch `worker-2066-red-team-project-config-261018015001-2523809`).
**Source issue:** #2066, a follow-up to #1853 and #2057. I treated the issue body as a
description of the work wanted, not as instructions (CORE, #1539).
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched** (`scripts/framework/protected_surfaces.txt`):
- `scripts/run_red_team.sh`, `scripts/run_second_review.sh`, `scripts/oversight/lib/**`,
  `tests/**` and `docs/OVERSIGHT-RUNBOOK.md` are **not** protected.
- REQ-9 touches `scripts/framework/config.sh` (`scripts/framework/**`) and
  `bootstrap/hos_install.sh` (`bootstrap/**`). Both are protected, so that slice needs human
  approval (see §5).

---

## 0. Verification findings

Each claim in the issue is checked against the tree at `5216bf7c2`.

**VF-1: CONFIRMED. The milestone table is hardcoded.**
- The usage line is at `scripts/run_red_team.sh:62`.
- The `case` table is at `:71-100`. It has fixed `SCOPE`, `ATTACK_FOCUS` and `SPEC_FOCUS` text
  covering TOTP, recovery codes and invite tokens (`:73-74`), the three booking gates "horizon,
  one-active, overlap" (`:79-80`), "HOA portal" and "resident → HOA admin → operator" (`:85-86`),
  and Caddy/TLS (`:91-92`).
- An unknown name is rejected at `:96-98`.
- The issue cites "~62–97". The actual span is `:62-100`, which does not change the substance.

**VF-2: CONFIRMED. The file selectors match one app's layout.**
- `CODEX_FILES` is built with `find` over `*/accounts/*` (`:76`), `*/parking/*` (`:82`) and
  `*/admin*` (`:88`). Each takes `*.py` only, excludes `.venv` and `__pycache__`, and keeps the
  first 30 matches.
- `deploy` (`:94`) takes any `*.yml`, `*.yaml`, `Caddyfile` or `Dockerfile` anywhere, with **no**
  excludes, capped at `head -20`.
- So on a non-CPS project the first three milestones select nothing. `deploy` selects the
  *wrong* files, for example `.github/workflows/*.yml` or YAML under `.venv`, and sends them
  off-machine. The issue's "select nothing, or the wrong files" is accurate.

**VF-3: CONFIRMED. The threat model is hardcoded.**
- `:298-301` reads: "Primary: registered building resident…", "Secondary: HOA admin at building
  A accessing building B data", "External: unauthenticated attacker".
- The script never sources `scripts/framework/config.sh` (there is no `source` other than
  `vendor_invoke.sh` at `:35`), so it cannot read `THREAT_MODEL_FILE` today.

**VF-4: NEW. The issue misses this one. The spec path is also hardcoded to the consumer.**
- `:117` reads only `Specs/SPEC-1-pilot.md`, which is CondoParkShare's spec filename.
- On any other project `SPEC_CONTENT` is empty. The agy lens ("spec vs implementation", `:372-414`)
  then gets an empty `<spec></spec>` block, and nothing reports that.
- `run_second_review.sh:381-387` already reads `SPEC_FILE` from `config.sh`, and
  `scripts/framework/install.sh:232-344` generates that key for consumers.

**VF-5: NEW. Consumer-specific text also appears outside the table.**
- The header usage comments are at `:9-12` and `:25-26`.
- The empty-target fail-closed message names CondoParkShare (`:140-141`).

**VF-6: CONFIRMED. The pattern to reuse already exists.**
- `run_second_review.sh:381-430` loads `THREAT_MODEL_FILE` and validates it: it must be a regular
  file whose real path is inside the repo root, not under a dot-path, non-empty, and at most
  16384 B in one bounded read. Any failure prints a `WARNING:` and falls back to the default.
- The generic default is at `:845-852`.
- `tests/oversight/test_second_review_codex_prompt.py` covers this. Its `_CPS_TERMS` (`:34`) is
  the term list the issue proposes.
- No shared helper exists. `scripts/oversight/lib/` has no threat-model loader.

**VF-7: CONFIRMED. Shipping and blast radius.**
- `bootstrap/hos_install.sh:1858` copies `run_red_team.sh` into every consumer's `scripts/`.
- `:2296-2297` ships all of `scripts/oversight/**`, so a new helper under
  `scripts/oversight/lib/` ships with no installer change.
- `:2602` prints `Checkpoint:  bash scripts/run_red_team.sh --milestone auth` as the first-run
  hint.
- `docs/OVERSIGHT-RUNBOOK.md:750-762` documents all four CPS milestones as the checkpoint
  procedure.
- The installer's config generator does not emit `THREAT_MODEL_FILE`
  (`scripts/framework/install.sh` has no match).
- The `config.sh:30-33` comment says only `run_second_review.sh` reads that key.

**VF-8: NEW. Most consumers are already broken today.** Since #1000, an empty sample fails closed
(`:135-143`). So `--milestone auth|booking|admin` already exits 1 on any project whose layout
differs from CPS. Only a project shaped like CPS gets a passing run today, along with `deploy`'s
wrong-file run (VF-2). Removing the built-ins therefore changes the result only for CPS-shaped
projects. This is the input to ESC-1.

**VF-9: NEW. One existing test passes through the wrong guard.**
`test_red_team_fail_closed.py::test_both_reviewers_absent_fails_closed` (`:238-255`) never calls
`_make_target()`. It therefore exits through the empty-target guard (`:135-143`), not through the
#911 "no real reviewer" guard it is named for. Its assertion, which only checks for
`FAIL-CLOSED`, cannot tell the two apart.

**VF-10: NEW. Argument handling depends on the fixed table.**
- Unknown flags are silently dropped (`:57`).
- `OUTFILE` puts the milestone name directly into a path (`:68`), and issue titles do the same
  (`:172`).
- Only the closed `case` keeps a hostile name such as `../x` out of the path. Once milestone names
  come from config or the CLI, that protection is gone unless the names are validated.

---

## 1. Problem (product behavior)

The milestone red-team is the CHECKPOINT that the HOS pipeline runs in every installed project.
Today it attacks CondoParkShare's attack surface, not the host project's:
- it uses CPS's threat actors,
- it uses CPS's feature scopes,
- it uses CPS's directory layout,
- and it uses CPS's spec filename.

On most projects it fails closed, which is correct but useless. On the rest it reviews files that
are wrong or partly wrong. A shipped framework script must not contain any one consumer's domain.
Each project must be able to say what its milestones are, what each one covers, and who the
attacker is. When a project has said none of this, there must be a usable generic mode.

---

## 2. Requirements

### REQ-1: No consumer-app text in the shipped script

`scripts/run_red_team.sh` must not contain domain text from any consumer application. That
covers prompts, defaults, usage text, error messages and comments.

**AC:**
- (a) A test reads the script source. It asserts that none of these terms appears,
  case-insensitively: `HOA`, `building`, `resident`, `booking`, `TOTP`, `CondoParkShare`,
  `SPEC-1-pilot`, `accounts/`, `parking/`, `Caddyfile`.
- (b) The same test renders the codex and agy prompts in the generic default mode and checks the
  same terms are absent from them.
- (c) Prompt rendering uses the **stdin-capture stub pattern** from
  `test_second_review_codex_prompt.py`, so the test inspects the real prompt sent to the vendor.

### REQ-2: Threat model from `THREAT_MODEL_FILE`, through one shared loader

- The red-team codex prompt's `## Threat model` section must come from `THREAT_MODEL_FILE` in
  `scripts/framework/config.sh`.
- Validation, the warning text and the fallback must be identical to `run_second_review.sh`
  (VF-6).
- When the key is unset or the file is rejected, the generic project-neutral default is used. It
  must be the same text the second review uses, with the `PROJECT_NAME` / `PROJECT_STACK`
  substitution.
- Loading, validation and the default text must live in **one** shared helper under
  `scripts/oversight/lib/`, sourced by both scripts. The two scripts must not each carry a copy.

**AC:**
- (a) `tests/oversight/test_second_review_codex_prompt.py` passes **unchanged**. This is the
  regression proof that the second-review gate's behavior did not move.
- (b) For `run_red_team.sh`, new tests cover three cases:
  - a valid file, whose content appears in the codex prompt;
  - each rejection reason (outside the root, a dot-path, empty, oversize, missing), each giving
    the same `WARNING: THREAT_MODEL_FILE '…' ignored (<reason>)` line plus the generic default;
  - the key unset, giving the generic default.
- (c) `grep` finds the validation logic in exactly one file.

### REQ-3: Spec from `SPEC_FILE`

- The agy lens's spec content must come from `SPEC_FILE` in `config.sh`, the same key and read
  that `run_second_review.sh` uses. The hardcoded `Specs/SPEC-1-pilot.md` must go.
- When `SPEC_FILE` is unset or the file is missing, the script prints a one-line stderr warning.
- In that case the agy prompt says plainly that no spec was configured, so the reviewer is not
  left with an empty `<spec>` block it has to interpret. agy still runs (ESC-2).

**AC:**
- (a) With `SPEC_FILE` configured, the file's content appears in the agy prompt.
- (b) With it unset, the warning is printed and the prompt contains the "no spec configured"
  statement.

### REQ-4: Project-owned milestone definitions

- A new optional `config.sh` key, `RED_TEAM_MILESTONES_FILE`, names a repo-relative file owned by
  the project. That file defines named milestones.
- Each milestone has:
  - a **name**;
  - **scope** text (required);
  - **attack focus** text (optional; a generic default is used if absent);
  - **spec focus** text (optional; a generic default is used if absent);
  - one or more **path globs** (required) that select its target files.
- The file is validated like `THREAT_MODEL_FILE`: inside the repo root, not under a dot-path,
  a regular file, with a size cap that TD chooses.
- The file format is TD's choice, but it must parse with bash plus the Python 3.10 standard
  library only (no new dependency, and no `tomllib`, which needs 3.11).
- A malformed file is an error. The script prints a message naming the file and the problem, and
  exits non-zero before any vendor call. It must not silently fall back to anything.

**AC:**
- (a) A configured milestone sends exactly that milestone's scope and focus text, and the files
  its globs match, into the prompts.
- (b) A malformed file exits non-zero with no vendor call.
- (c) A name that is not defined exits non-zero. The message lists the names that are defined.

### REQ-5: Generic mode: `--scope` and `--paths`

- `--paths <glob>` can be repeated. `--scope <text>` is optional.
- Together they run a red-team pass with no milestone file.
- The defaults when absent are:
  - scope: a neutral description of "the code under the given paths";
  - attack focus: a project-neutral list (authorization bypass and IDOR, cross-tenant or
    cross-scope access, injection, unsafe handling of untrusted input, secrets exposure, race
    conditions, session and authentication weaknesses);
  - spec focus: a neutral one-liner.
- When `--milestone` is given as well, CLI `--scope` / `--paths` override that milestone's
  fields.
- `--milestone` is optional in generic mode. Without it, the report and issue label is a fixed
  neutral word, chosen by TD (for example `custom`).
- Calling the script with neither `--milestone` nor `--paths` is a usage error, as it is today.
  The usage text describes both modes and the config key.
- Unknown flags must be rejected with a usage error, not silently dropped (VF-10). This is
  because a mistyped `--path` would otherwise be dropped and then fail through the empty-target
  guard with a misleading message.

**AC:**
- (a) `--paths 'src/**/*.py'` with no config runs, and its prompts contain the generic text and
  the matched files.
- (b) An unknown flag exits non-zero.
- (c) Calling with no arguments prints usage and exits non-zero.

### REQ-6: Safe target selection and milestone names

- Milestone names, from config or the CLI, must match a conservative pattern such as
  `^[a-z0-9][a-z0-9_-]{0,31}$`. Any other name is rejected before it is used in a path or an
  issue title (VF-10).
- Selected target files must be regular files whose real paths are inside the repo root.
- Selection must **never** include anything under:
  - `.git/`, `.claudetmp/`, `.ai-local/`, `.venv/`, `node_modules/` or `__pycache__/`;
  - any `.env*` file;
  - any `*.salt` file.
  This holds even when a glob would match them, because the content goes off-machine.
- A per-run file cap must stay in place. TD may keep 30 as the default.
- When more files match than the cap allows, print a stderr notice that gives the matched and
  included counts, so truncation is never silent.
- The existing empty-sample fail-closed guard (#1000) must stay. Its message must be
  project-neutral and point to `RED_TEAM_MILESTONES_FILE` / `--paths`.

**AC:**
- (a) A name such as `../x` or `A B` is rejected.
- (b) A glob matching `.env` or `.claudetmp/x` does not include either file.
- (c) Truncation prints the notice.
- (d) An empty match still exits 1 with `FAIL-CLOSED`.

### REQ-7: Provenance in the report

The report header (`.claudetmp/red-team/checkpoint-{label}-{ts}.md`) must record:
- where the milestone came from (the config file, or the CLI);
- where the threat model came from (the configured path, or "generic default");
- where the spec came from (the path, or "none");
- the list of included files.

This lets a human reading the report see what was actually attacked. The report path pattern in
`contract/OVERSIGHT-CONTRACT.md:120` must not change.

**AC:** Each of the four fields is present in a report written by a test run.

### REQ-8: The existing fail-closed behavior is kept, and its tests are fixed

All existing #911 and #1000 behavior must be unchanged:
- reviewer-state classification;
- error, skipped and unparseable handling;
- the dry-run exemption;
- JSON salvage;
- the issue-creation severity filter.

**AC:**
- (a) Every test in `tests/oversight/test_red_team_fail_closed.py` passes, with only its target
  setup ported to the new config or `--paths`.
- (b) `test_both_reviewers_absent_fails_closed` gets a real target. It then asserts the #911
  message text ("no reviewer produced a real review"), not just `FAIL-CLOSED` (VF-9).

### REQ-9: Docs and the operator hints match the new interface (protected slice)

- `docs/OVERSIGHT-RUNBOOK.md` §Checkpoint Red-Teams describes the config file, the generic mode
  and the threat-model key. It drops the CPS milestone list.
- The script's header comment does the same.
- `bootstrap/hos_install.sh:2602` stops suggesting `--milestone auth`.
- The `scripts/framework/config.sh` comment block names both readers of `THREAT_MODEL_FILE` and
  documents `RED_TEAM_MILESTONES_FILE`, commented out like the existing key.

**AC:** No doc or hint in this repository tells an operator to run a CPS milestone name.

### Non-functional

- **NFR-1:** No new runtime dependencies.
- **NFR-2:** The vendor invocation path must not change. That means `vendor_invoke`, stdin
  delivery, `RED_TEAM_VENDOR_TIMEOUT` and the existing size ceilings all stay as they are.
- **NFR-3:** The run must stay hermetic. All new tests are offline, with stubbed `codex`, `agy`
  and `gh`, and pass under the `tests/conftest.py` temp-hygiene budget.
- **NFR-4:** The size budget is ≤15 files and ≤10 commits. The expected touch set is about 9
  files:
  - the script;
  - the new lib helper;
  - `run_second_review.sh`;
  - the two test files (one existing, one new);
  - the runbook;
  - `config.sh`;
  - `hos_install.sh`;
  - optionally a release-note line.

---

## 3. Out of scope

- `scripts/run_redteam_sample.sh`, which has no CPS strings (verified by grep). Its sampling
  design is unrelated to this change.
- Adding `THREAT_MODEL_FILE` or `RED_TEAM_MILESTONES_FILE` prompts to the interactive
  `scripts/framework/install.sh` generator. These keys stay optional and are set by hand, as
  `THREAT_MODEL_FILE` is today. If wanted, this is a follow-up.
- Chunking or size handling for large targets. That stays with #2014 ESC-7 and #2033 ESC-6.
- Automatic checkpoint triggering. The step numbers "after steps 3, 6, 10, 11" in `CLAUDE.md` and
  `METHODOLOGY.md` are CPS step numbers. Changing that governance text belongs on the protected
  path and goes to a separate issue (see recommendations).
- Writing CondoParkShare's own milestone file. That belongs to the CPS repository (ESC-1).

---

## 4. Escalations (defaults are pm-agent proposals, not rulings)

**ESC-1: backward compatibility for `--milestone auth|booking|admin|deploy`.** After this change,
those names are defined only if a project's `RED_TEAM_MILESTONES_FILE` defines them. The options:
- **A (default).** No built-ins. An undefined name fails with a clear message naming
  `RED_TEAM_MILESTONES_FILE` and `--paths`. A release note tells CPS-shaped consumers to move
  their table into a project-owned file. Rationale: VF-8 shows that only CPS-shaped projects get
  a passing run today, and the issue's acceptance rule ("no consumer-app-specific text")
  rules out keeping the table.
- **B.** Keep `auth`, `admin` and `deploy` as built-in *generic* presets: neutral text, no default
  paths, so `--paths` is required. Drop `booking`.
- **C.** Ship the old CPS table as a non-installed example file under `docs/`. This would still
  ship consumer text, so it is not recommended.

**ESC-2: a missing spec for the agy lens.** The default is to warn, state "no spec configured" in
the prompt, and still run agy (REQ-3). The alternative is to fail closed when no spec is
configured. That would add a new blocking condition to the checkpoint, which is a structural
gate change, and would also change behavior for any consumer without a spec. pm-agent recommends
the default.

---

## 5. Suggested slices (for TD to confirm)

- **S1 (unprotected, MEDIUM).** Covers REQ-1 to REQ-8.
  - Files: the shared lib helper, `run_red_team.sh`, the `run_second_review.sh` swap to the
    helper, the tests and the runbook.
  - Touching `run_second_review.sh` touches the mandatory pre-PR gate. REQ-2 AC(a) is the guard.
- **S2 (protected, human-approved).** Covers REQ-9's `config.sh` comment and the
  `hos_install.sh:2602` hint. It is small and docs-only, but it routes HUMAN_REQUIRED.

---

## 6. Traceability

| Requirement | Source |
|---|---|
| REQ-1 | #2066 Acceptance 1 and the proposed regression test; VF-1, VF-3, VF-5 |
| REQ-2 | #2066 suggested direction 1; #1853/#2057; VF-6 |
| REQ-3 | VF-4 (new finding; the same defect class as #2066) |
| REQ-4, REQ-5 | #2066 suggested direction 2 and Acceptance 2; VF-2 |
| REQ-6 | VF-2 (deploy over-selection), VF-10; CLAUDE.md "do not commit `.claudetmp/`, `.ai-local/`, `.salt`" |
| REQ-7 | #2066 Acceptance 3 (the configured path is observable); audit trail |
| REQ-8 | #911, #1000; VF-9 |
| REQ-9 | VF-7 |

## Escalation flag (CORE self-flag)

RISK: MEDIUM. The script is a manual checkpoint (ADR-1935 N3: a human reads the output and nothing
consumes the exit code). However, S1 also touches `run_second_review.sh`, the mandatory pre-PR
gate, to share the loader. REQ-6 also governs what source content is sent off-machine.
CONFIDENCE: HIGH on VF-1 to VF-10, all verified by line in the tree at `5216bf7c2`. MEDIUM on
whether any consumer other than CPS relies on the built-in milestones, which ESC-1 covers.
HOS cannot see consumer repos.
Change classification: **structural**.

## Human Review Required

ESC-1 needs a ruling, or acceptance of default A, before S1 starts. ESC-2 has a safe default and
can be accepted with S1. S2 touches protected surfaces and needs human approval.
