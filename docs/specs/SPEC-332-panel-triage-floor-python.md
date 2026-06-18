# Requirements Spec — Issue #332: Move Panel Triage Floor and SQC Sampling Logic to Python

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #332
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

`scripts/run_panel.sh` contains two categories of deterministic logic that violate the #314
policy ("prefer Python for logic, shell for launch — establish testability as a code review
criterion"):

1. **Deterministic triage floor** (`det_floor` function, lines 266–274): a bash function
   that inspects changed file paths and the added-line count to determine the minimum risk
   tier floor. It uses `grep -qiE` pattern matching on file extensions, lock files, and
   path segments (auth, payment, etc.) to classify the change. This logic is not unit-
   testable without running the full shell script.

2. **SQC sampling decision** (lines 316–338): the statistical quality control random
   red-team audit logic that determines whether a lower-tier PR is selected for an extra
   adversarial reviewer pass. Currently implemented as inline bash: SHA256 hash of
   head-SHA + salt, modulo arithmetic, comparison against a tier-specific sample rate.
   This is deterministic and reproducible by design (a core property of the SQC mechanism),
   but the implementation is untestable in isolation.

Both functions implement rules that are meaningful to test independently — the triage floor
rules are specifically documented in `run_panel.sh` comments and `DECISIONS.md D15/D17/D18`
as the authoritative risk escalation policy; the SQC sampling is documented as reproducible
and non-gameable (DECISIONS.md D17). Bugs in either function silently affect the reviewer
roster and could under-staff a HIGH-risk PR or suppress the adversarial audit on a PR that
should have received it.

The shell script's remaining work — fetching the PR diff, resolving the PR number, calling
model CLIs, posting threads to GitHub — is genuinely shell/orchestration work and stays in
shell.

---

## 2. Scope

### In scope

- Extract the **deterministic triage floor** (`det_floor` bash function) into a named
  Python function in `scripts/oversight/panel_logic.py` (extending the module seeded by
  SPEC-376, per the #314 policy of extending rather than creating new modules for the same
  script's logic domain).
- Extract the **SQC sampling decision** (the `SAMPLED` / `ROLL` computation) into a named
  Python function in the same module.
- The shell script must be updated to call the Python module for these decisions; it must
  not re-implement the logic.
- Both functions must be unit-testable with synthetic input without running `run_panel.sh`
  or any live model.

### Out of scope

- The Haiku triage confirmation call (`call_model haiku`) — this invokes a live model CLI;
  it stays in shell. The Python module computes the deterministic floor only; Haiku confirms
  or raises it, as today.
- The `max_risk` / `rank` bash helpers — used by the shell to combine floor + author +
  Haiku results; stays in shell unless the architect decides otherwise (see OQ-1).
- Salt file creation and persistence (`$SALT_FILE`) — file I/O in shell; the Python
  sampling function receives the salt as an argument.
- The sample-log append (`.ai-local/panel/sample-log.jsonl`) — file I/O in shell; stays
  in shell.
- The reviewer roster assembly — stays in shell.
- Any change to the `SAMPLE_LOW` / `SAMPLE_MED` configurable rates; they remain
  environment-variable-configurable.

### SQC sampling — not yet added to `panel_logic.py`

At the time of this spec, `panel_logic.py` (SPEC-376) contains `count_corroboration`,
`reconcile_membership`, and `rank_findings`. The SQC sampling function is to be **added**
to the module by this issue's implementation. It does not exist there today.

---

## 3. Requirements

### R1 — Deterministic triage floor function

The module must expose a function that computes the deterministic risk floor for a given
PR, given:
- `changed_files: str` — newline-separated list of changed file paths (as produced by
  `gh pr diff --name-only`)
- `added_lines: int` — count of added lines in the diff

The function must return a risk tier string: one of `"LOW"`, `"MEDIUM"`, `"HIGH"`,
`"CRITICAL"`.

The tier determination must match the current `det_floor` bash function behavior exactly:
- Default floor: `LOW`.
- Any file matching source code extensions (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.go`,
  `.rb`, `.java`, `.cs`, `.php`, `.rs`, `.sh`) raises to `MEDIUM`.
- Any dependency manifest file (e.g., `package.json`, `package-lock`, `yarn.lock`,
  `pnpm-lock`, `requirements.txt`, `go.mod`, `Gemfile`, `Cargo.toml`, `composer.json`)
  raises to `MEDIUM`.
- `added_lines > SIZE_FLOOR` (default 500) raises to at least `MEDIUM`.
- Any file path matching auth/session/middleware/password/token/crypto/secret/API/routes/
  migrations/schema/db/sql path segments raises to `HIGH`.
- Any file path matching payment/billing/stripe/checkout/delete/destroy/drop_ path
  segments raises to `CRITICAL`.
- Each rule is applied as a floor ratchet (the result never decreases). Rules are applied
  in the order listed above.

The `SIZE_FLOOR` constant (currently 500 added lines) must be a parameter with a default
value, not a hardcoded constant inside the function, so tests can exercise the boundary.

### R2 — SQC sampling function

The module must expose a function that determines whether a PR is selected for a random
red-team audit, given:
- `head_sha: str` — the PR's head commit SHA
- `salt: str` — the secret audit salt
- `risk: str` — the current risk tier string (`"LOW"`, `"MEDIUM"`, `"HIGH"`, `"CRITICAL"`)
- `sample_low: int` — the LOW-tier sample rate (percentage, 0–100)
- `sample_med: int` — the MEDIUM-tier sample rate (percentage, 0–100)

The function must return a named result (dataclass or dict) containing:
- `sampled: bool` — whether this PR is selected for the red-team audit
- `roll: int` — the computed roll value (0–99), for logging and reproducibility audit
- `rate: int` — the applicable sample rate for the tier (0 if HIGH/CRITICAL, since those
  are always 100%)

The sampling logic must match the current shell behavior exactly:
- HIGH and CRITICAL tiers always produce `sampled=False, rate=0` from this function
  (they fire 100% regardless; the function does not control that — the shell handles it).
- For LOW and MEDIUM tiers: compute `SHA256(head_sha + salt)`, take the first 8 hex
  characters, interpret as a hex integer, compute `mod 100`. If the result is less than
  `sample_low` (LOW tier) or `sample_med` (MEDIUM tier), `sampled=True`.
- The function must use Python's `hashlib.sha256`, consistent with the shell's
  `sha256sum` / `shasum -a 256` pipeline.

### R3 — Shell calls Python for both decisions

The shell script must invoke the Python module for:
1. The triage floor decision: replacing the `det_floor` bash function (lines 266–274) with
   a call to the R1 function.
2. The SQC sampling decision: replacing the inline bash hash/modulo computation
   (lines 326–334) with a call to the R2 function.

The shell script must not duplicate the rule logic. File path lists, added-line counts,
head SHAs, and salt values are passed to the Python module as arguments.

### R4 — Unit-testable without a live model run

The functions introduced by R1 and R2 must perform no subprocess calls, no file I/O, and
no network calls. They must be importable and callable in a Python unit test with synthetic
inputs.

A CLI shim (`if __name__ == "__main__"`) may perform file I/O for the shell integration,
but the underlying logic functions must be pure.

---

## 4. Acceptance Criteria

**AC1 — Triage floor: source file escalation:** Given `changed_files="src/views.py"`,
`added_lines=10`, the R1 function returns `"MEDIUM"`.

**AC2 — Triage floor: auth escalation:** Given `changed_files="app/auth/login.py"`,
`added_lines=10`, the R1 function returns `"HIGH"`.

**AC3 — Triage floor: payment escalation:** Given `changed_files="billing/stripe.py"`,
`added_lines=10`, the R1 function returns `"CRITICAL"`.

**AC4 — Triage floor: size escalation:** Given `changed_files="README.md"`,
`added_lines=501`, `size_floor=500`, the R1 function returns `"MEDIUM"`.

**AC5 — Triage floor: multi-file max:** Given `changed_files="README.md\napp/auth/session.py"`,
`added_lines=5`, the R1 function returns `"HIGH"` (auth escalation wins).

**AC6 — SQC sampling: reproducibility:** Given the same `head_sha`, `salt`, `risk`, and
rate parameters, the R2 function returns the same `sampled` and `roll` values on every
invocation. This is the non-gameability guarantee (DECISIONS.md D17).

**AC7 — SQC sampling: threshold boundary:** Given a `roll` value of 24 with `sample_low=25`
for a LOW-tier PR, the R2 function returns `sampled=True`. Given `roll=25` with `sample_low=25`,
it returns `sampled=False`.

**AC8 — SQC sampling: HIGH/CRITICAL returns rate=0:** Given `risk="HIGH"`, the R2 function
returns `sampled=False, rate=0` (HIGH PRs are not sampled; they always fire the full roster
via a separate path in the shell).

**AC9 — Shell integration:** Running `run_panel.sh 42 --dry-run` (with a valid PR) produces
the same triage floor output as the current script for the same PR diff.

**AC10 — No logic duplication:** After this change, the `det_floor` bash function is removed
from `run_panel.sh`, and the inline hash/modulo computation is replaced with a Python call.

---

## 5. Non-Requirements

- **No behavior change.** The refactored script must produce identical triage decisions
  and SQC sampling outcomes to the current script for all inputs.
- **No new risk tiers or escalation rules.** This spec does not add new file path patterns,
  new tier levels, or new sampling strategies.
- **Shell still resolves the PR and fetches the diff.** The Python module receives already-
  computed values (file list, added-line count, head SHA) as arguments.
- **No change to salt file management.** The shell continues to create, read, and store the
  salt; the Python function only consumes it.
- **No change to the sample log format.** The `.ai-local/panel/sample-log.jsonl` write
  stays in shell, using the `roll` and `sampled` values returned by the Python function.

---

## 6. Open Questions

**OQ-1 — `max_risk` / `rank` helpers**
The bash `rank` and `max_risk` functions (lines 107–108) are used by the shell to combine
the deterministic floor, author-declared risk, and Haiku's triage output into a final risk
tier. They contain simple integer arithmetic. The architect should rule on whether these
belong in the Python module (making it the single source for all triage rules) or stay in
shell (keeping the combining logic next to the Haiku call that feeds it).

**OQ-2 — File path pattern source of truth**
The triage floor file path patterns (auth, payment, etc.) are currently embedded in the
`det_floor` bash function as regex strings. Once extracted to Python, they become Python
regex patterns. The architect should confirm whether these patterns should be configurable
(e.g., in `config.sh` or a project-level config) or remain hardcoded constants in the
module with comments directing consumers to the PROJECT region of the agent if they need
project-specific overrides.

**OQ-3 — `panel_logic.py` module size**
SPEC-376 seeded `panel_logic.py` with three functions (114 lines). SPEC-332 adds two more
functions; SPEC-333 adds further functions. The architect should assess whether `panel_logic.py`
is the right consolidation point for all panel deterministic logic, or whether the triage-
floor and SQC functions warrant a separate `panel_triage.py` module for organization.

---

## 7. Context for Architect

- The `det_floor` bash function is at `run_panel.sh` lines 266–274. It is called at line
  276 and its output combined with `AUTHOR_RISK` (line 281) and Haiku's output (line 302)
  using the `max_risk` helper.
- The SQC sampling block is at lines 316–338. The `SALT` is read or minted by the shell
  (lines 318–325) before the Python call; the Python function receives it as an argument.
  The result (`SAMPLED`, `ROLL`, `RATE`) feeds the sample-log write at lines 331–338 and
  the reviewer roster assembly at line 357.
- `panel_logic.py` currently contains `count_corroboration`, `reconcile_membership`, and
  `rank_findings` (SPEC-376). The module follows the purity binding: logic functions are
  pure; only the `main()` CLI shim performs I/O. New functions added by this spec must
  follow the same convention.
- Issue #314 is the policy driver. The pilot rates (`SAMPLE_LOW=25`, `SAMPLE_MED=50`) and
  the production targets (`5%` / `15%`) are documented at `run_panel.sh` lines 72–74 and
  `DECISIONS.md D17`; this spec does not change them.
