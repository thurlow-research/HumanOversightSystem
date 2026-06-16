# Requirements Spec — v0.4.0 Installer and Consumer Compatibility

**Document type:** Requirements specification
**Status:** Approved for build
**Issues:** #238, #286, #287, #303 (Findings 4 and 5)
**Date:** 2026-06-16
**Author:** pm-agent

**Cross-reference:** Brownfield migration (#275) is specified in `SPEC-consumer-pack.md` (separate follow-on). Pack scaffolding for consumer PROJECT regions is also deferred to that spec.

---

## Problem Statement

Four CPS field reports and one unattended-worker session surfaced gaps in the v0.3.x installer that affect install correctness, agent runtime behavior, and suspension-lifecycle integrity:

1. **Version-skip (#238):** The installer computes a delta against the assumed-prior release rather than the consumer's actual installed version. When a consumer skips an intermediate upgrade, the resulting install is correctly manifested but content-incomplete, and `.hos-release` overstates what is installed.
2. **Internal-path citations (#286):** CORE agents shipped to consumers contain references to HOS-internal paths (`research/findings/`, `docs/SETUP.md`, `packs/`) that do not exist in consumer repos. An agent that cites a document the consumer cannot read degrades runtime reasoning quality silently.
3. **Pack placeholder paths (#287):** Django-pack agents reference example paths (`settings/base.py`, `tests/factories.py`) that are bare-relative and do not match the consumer's actual project layout. Agents that cite non-existent paths produce less precise reviews.
4. **Suspension control-line / table-row mismatch (#303 Finding 4):** The `SUSPENDED: <gate>` control line and the documentation table row in `gate-suspension.md` can be removed independently. HOS has no guard that catches an incomplete removal, leaving a gate logically unsuspended per the table but still suspended in practice (or vice versa).
5. **Suspension format parser mismatch (#303 Finding 5):** `suspension_manager.py` honors `[pinned]` and `review-by:` flags on a suspension line; `check_suspension.sh` does not parse them and treats a line with those flags as absent, silently disabling the suspension. This is a safety-relevant failure mode: the human believes a gate is suspended but the gate runs.

---

## §1 — Cumulative Upgrade on Version-Skip

### Background

The installer reads `.hos-release` in the consumer repo to determine what is currently installed, then applies the target release. Field report #238 demonstrates that when a consumer's `.hos-release` is more than one version behind the target (because an intermediate upgrade PR was abandoned), the installer produces a diff against the assumed-prior release rather than the actual installed content, resulting in a content-incomplete install.

**Decision (human-approved):** The installer must detect version-skip and either compute a cumulative diff against the actual installed version or hard-stop with a clear migration path message. The spec below selects the hard-stop approach with a `--full` override path, which is simpler, safer, and easier to audit than dynamic cumulative diff computation.

### Requirements

**REQ-U-01 — Installed-version detection.**
Before applying any upgrade, the installer must read `.hos-release` in the consumer target repo. If the file is absent, the installer treats the consumer as a fresh install (no `.hos-release` → no prior version assumption). If the file is present, its value is the consumer's installed version.

**REQ-U-02 — Version-skip detection.**
The installer must determine whether the consumer's installed version is exactly one version behind the target release (sequential upgrade) or two or more versions behind (version-skip). The installer uses the sorted release tag list fetched from the HOS GitHub releases API to determine adjacency. If the releases API is unavailable and `.hos-release` is present, the installer hard-stops with an explicit "cannot verify upgrade sequence — network required" message.

**REQ-U-03 — Hard-stop on version-skip.**
When a version-skip is detected, the installer must exit non-zero and emit a message in this exact form:

```
ERROR: version-skip detected.
  Installed: <installed-version>
  Target:    <target-version>
  Skipped:   <list of skipped versions, comma-separated>

  A non-sequential upgrade risks a content-incomplete install.
  Supported paths:
    (a) Re-run with --full to install <target-version> wholesale
        (overwrites all CORE and PACK regions; PROJECT regions are preserved).
    (b) Apply each intermediate version in sequence:
        <list of intermediate version install commands>

  Run with --full to proceed if you understand the implications.
```

The `--full` flag instructs the installer to treat the upgrade as a fresh install of the target release: it overwrites all CORE and PACK regions from the target release, preserves all PROJECT regions, and records the target version in `.hos-release`. It does not apply the intermediate-release deltas.

**REQ-U-04 — Sequential upgrade is unchanged.**
When the installed version is exactly one version behind the target (sequential upgrade), the installer proceeds as today. This requirement exists to confirm that the version-skip logic does not affect the common case.

**REQ-U-05 — Content-currency check.**
The installer must verify content currency against a `SHA256SUMS` file shipped with each release. This check supplements the manifest-presence check (`collection_integrity.sh`) by verifying that installed CORE and PACK region content matches the expected bytes for the declared installed version, not merely that the files are present.

The check runs after the upgrade is applied and before the success message. It reads the `SHA256SUMS` manifest shipped with the target release and compares each CORE and PACK region's installed bytes against the declared hash. A mismatch is a hard-stop error: the installer must not silently record a `.hos-release` tag that does not match installed content.

PROJECT regions are excluded from the content-currency check (they are consumer-owned and expected to diverge).

**REQ-U-06 — `SHA256SUMS` manifest.**
Each HOS release must ship a `SHA256SUMS` file listing the SHA-256 hash of each CORE and PACK region byte-string for every agent file, keyed by agent filename and region name. The format is:

```
<sha256hex>  <agent-filename>:<region-name>
```

Example:
```
a3f1...  security-reviewer.md:CORE
b8c2...  security-reviewer.md:PACK:django
```

This manifest is generated by the release-cut script and is part of the release artifact.

**REQ-U-07 — Migration path documentation.**
`docs/UPGRADE-PR-REVIEW-CHECKLIST.md` must be updated to include a section on version-skip scenarios: what to do when the `--full` flag is used, how to verify that PROJECT regions survived, and how to confirm the content-currency check passed.

**Acceptance criteria for §1:**

| ID | Criterion |
|---|---|
| AC-U-01 | Upgrading from v0.1.x to v0.3.0 (skipping v0.2.0 and v0.2.1) produces a hard-stop error listing the skipped versions. |
| AC-U-02 | `--full` flag applied to the same scenario installs the target release wholesale and records the correct `.hos-release` tag. |
| AC-U-03 | A sequential upgrade (v0.2.1 → v0.2.2) proceeds without the hard-stop. |
| AC-U-04 | After a `--full` upgrade, the content-currency check passes (all CORE and PACK region hashes match `SHA256SUMS`). |
| AC-U-05 | If a CORE region byte has been silently corrupted or omitted, the content-currency check catches it and exits non-zero before recording `.hos-release`. |
| AC-U-06 | PROJECT regions are not included in `SHA256SUMS` and are not checked for hash match. |
| AC-U-07 | When the releases API is unavailable and `.hos-release` is present, the installer exits non-zero with the "network required" message rather than proceeding silently. |

---

## §2 — Post-Install Path Cleanup

### Background

CORE agents shipped to consumers cite HOS-internal paths that consumers do not receive. These are rationale/citation references: prose that remains grammatically correct without the linked document, but where the cited path is a broken reference in the consumer's context. The human decision (#286) is to strip these lines on install.

### Requirements

**REQ-P-01 — Internal-path registry.**
The installer must read a file at `scripts/framework/installer-internal-paths.txt` to determine which path prefixes are considered HOS-internal and must be stripped from CORE regions in consumer copies. This file is the single source of truth for the strip list. The initial set of internal path prefixes is:

```
research/findings/
docs/SETUP
docs/CUSTOMIZATION
packs/
```

Each line is a path prefix. A line in a CORE region is internal if it contains any listed prefix as a substring.

**REQ-P-02 — Strip behavior.**
When the installer writes a CORE region to a consumer agent file, it must remove any line that contains an internal path as defined by `installer-internal-paths.txt`. "Remove" means the line is omitted entirely from the output; no placeholder comment is inserted. Adjacent blank lines must be collapsed to a single blank line to prevent blank-line accumulation.

**REQ-P-03 — Scope: CORE regions only.**
The strip pass applies only to content within `<!-- HOS:CORE:START -->` / `<!-- HOS:CORE:END -->` markers. PACK and PROJECT regions are not modified by the strip pass.

**REQ-P-04 — Idempotency.**
Running the strip pass twice on the same file must produce the same result as running it once.

**REQ-P-05 — Install-log notification.**
After stripping, the installer must emit one summary line to the install log for each agent file where lines were stripped, in the form:

```
[path-cleanup] <agent-filename>: removed <N> internal-path line(s)
```

This is informational and does not affect exit code.

**REQ-P-06 — Upgrade preservation.**
On a sequential or `--full` upgrade, the strip pass runs again against the newly written CORE region. PROJECT regions are never touched.

**Acceptance criteria for §2:**

| ID | Criterion |
|---|---|
| AC-P-01 | After a fresh consumer install, no agent file in `.claude/agents/` contains a line with `research/findings/`, `docs/SETUP`, `docs/CUSTOMIZATION`, or `packs/` within its CORE region. |
| AC-P-02 | A CORE region that contained three internal-path lines now contains none; adjacent blank lines from the removal have been collapsed. |
| AC-P-03 | PACK and PROJECT regions are unchanged by the strip pass. |
| AC-P-04 | The install log shows `[path-cleanup]` entries for each affected agent. |
| AC-P-05 | Adding a new prefix to `installer-internal-paths.txt` and re-running the install strips lines matching that prefix without affecting other lines. |
| AC-P-06 | Running the installer twice produces identical agent file content (idempotent strip). |

---

## §3 — Pack Placeholder Substitution

### Background

Django-pack agents reference illustrative example paths (`settings/base.py`, `tests/factories.py`) that are bare-relative and do not match the real project layout of any given consumer. The human decision (#287) is to substitute these with project-specific values from `config.sh` on pack injection.

### Placeholder token convention

Placeholder tokens use double-brace syntax: `{{TOKEN_NAME}}`. This syntax is chosen to be visually distinct, unlikely to appear in natural prose, and simple to replace with a single pass. Tokens must not be nested.

The following tokens are defined and must be present in `config.sh` (consumer copy) for pack substitution to work:

| Token | config.sh key | Meaning |
|---|---|---|
| `{{PROJECT_ROOT}}` | `PROJECT_ROOT` | Absolute path to the project root (e.g. `/app`) |
| `{{PROJECT_SETTINGS_MODULE}}` | `PROJECT_SETTINGS_MODULE` | Python module path to the settings directory (e.g. `parkshare/settings`) |
| `{{PROJECT_TESTS_DIR}}` | `PROJECT_TESTS_DIR` | Path to the tests directory relative to `PROJECT_ROOT` (e.g. `tests`) |
| `{{PROJECT_PACKAGE}}` | `PROJECT_PACKAGE` | Top-level Python package name (e.g. `parkshare`) |

### Requirements

**REQ-S-01 — Token substitution on pack injection.**
When the installer injects a PACK region into a consumer agent file, it must substitute all `{{TOKEN_NAME}}` occurrences in the injected text with the corresponding value from `config.sh`. Substitution applies only to PACK region content. CORE and PROJECT regions are not subject to token substitution.

**REQ-S-02 — Missing-key behavior.**
If a `config.sh` key corresponding to a token is absent or empty, the installer must:
1. Leave the token literal in the output (e.g. the string `{{PROJECT_SETTINGS_MODULE}}` remains).
2. Emit a warning to the install log in the form:
   ```
   [pack-substitution] WARNING: token {{PROJECT_SETTINGS_MODULE}} has no value in config.sh — left literal in <agent-filename>
   ```
The install must not fail on a missing token. The warning is informational.

**REQ-S-03 — Pack source files use tokens.**
In HOS pack source files (under `packs/<name>/`), illustrative paths must use tokens rather than bare example paths. For the django pack, `settings/base.py` becomes `{{PROJECT_SETTINGS_MODULE}}/base.py`, `tests/factories.py` becomes `{{PROJECT_TESTS_DIR}}/factories.py`, and so on. The pack author is responsible for tokenizing pack source files. The installer does not modify pack source files; it substitutes on injection only.

**REQ-S-04 — `config.sh` key documentation.**
The `config.sh` template generated by `scripts/framework/install.sh` must include the four pack-substitution keys with comments explaining their purpose, even if the consumer is not installing a pack. This ensures the keys are present by default and reduces the likelihood of a missing-key warning on first pack injection.

**REQ-S-05 — Install-log confirmation.**
After pack injection, if all tokens were substituted, the installer emits one line per agent file:
```
[pack-substitution] <agent-filename>: substituted <N> token(s)
```
If any tokens were left literal (§ REQ-S-02), the warning line counts as the log entry for that agent.

**Acceptance criteria for §3:**

| ID | Criterion |
|---|---|
| AC-S-01 | After a django-pack install with `PROJECT_SETTINGS_MODULE=parkshare/settings`, the `infra-reviewer` PACK region contains `parkshare/settings/base.py`, not `settings/base.py` or `{{PROJECT_SETTINGS_MODULE}}/base.py`. |
| AC-S-02 | If `PROJECT_TESTS_DIR` is absent from `config.sh`, the install completes, the token `{{PROJECT_TESTS_DIR}}` remains literal in the PACK region, and the install log shows a WARNING line. |
| AC-S-03 | CORE regions in the same agent file are not modified by token substitution. |
| AC-S-04 | PROJECT regions in the same agent file are not modified by token substitution. |
| AC-S-05 | The generated `config.sh` template includes all four pack-substitution keys with explanatory comments. |
| AC-S-06 | Re-running the installer after correcting a missing `config.sh` key substitutes the previously-literal token. |

---

## §4 — Suspension Control-Line / Table-Row Consistency Validation

### Background

`contract/gate-suspension.md` is the canonical suspension record. It has two structurally coupled components: the `SUSPENDED: <gate>` control lines that `check_suspension.sh` reads to determine which gates to skip, and a human-readable documentation table that records the same suspensions with context (reason, review-by date, author). CPS field report #303 Finding 4 showed that a PR can remove the table row without removing the control line (or vice versa), leaving the two components inconsistent. HOS has no guard that catches this.

### Canonical suspension record structure

For each suspended gate, `gate-suspension.md` must contain exactly one of each of the following:

1. A control line of the form:
   ```
   SUSPENDED: <gate-name>
   ```
   or with optional flags (see §5):
   ```
   SUSPENDED: <gate-name> [pinned]
   SUSPENDED: <gate-name> review-by: YYYY-MM-DD
   SUSPENDED: <gate-name> [pinned] review-by: YYYY-MM-DD
   ```

2. A table row in the documentation table with `<gate-name>` as the gate identifier.

A suspension is defined as a `(gate-name, control-line, table-row)` triple. All three must be present and consistent for the suspension to be valid.

### Requirements

**REQ-C-01 — `suspension_manager.py --check` consistency validation.**
The `--check` mode of `suspension_manager.py` must include a consistency sub-check that:
1. Parses all `SUSPENDED: <gate>` control lines from `gate-suspension.md`.
2. Parses all gate identifiers from the documentation table in `gate-suspension.md`.
3. Computes the symmetric difference: gates with a control line but no table row (orphan control lines), and gates with a table row but no control line (orphan table rows).
4. For each orphan found, emits a structured finding.

**REQ-C-02 — Output format on mismatch.**
When a mismatch is found, `suspension_manager.py --check` must emit to stdout one finding per orphan in this form:

```
SUSPENSION-MISMATCH: <gate-name>
  control-line: present | absent
  table-row:    present | absent
  file: contract/gate-suspension.md
```

followed by a summary line:
```
suspension-consistency: FAIL — <N> mismatch(es) found
```

When no mismatches are found, the summary line is:
```
suspension-consistency: OK
```

The exit code of `suspension_manager.py --check` must be non-zero when any mismatch is found.

**REQ-C-03 — Pipeline placement.**
The consistency check runs as part of the transition gate suite, after the inner loop completes and before the second review. It is invoked as:

```
python scripts/oversight/suspension_manager.py --check
```

The transition gate suite must treat a non-zero exit from this command as a gate failure with the same blocking semantics as any other transition gate.

**REQ-C-04 — Unattended mode behavior.**
In unattended (autonomous worker) mode, a suspension mismatch is a compliance failure that blocks the PR from being opened. The worker must not open a draft PR while a suspension mismatch exists.

**REQ-C-05 — Interactive mode behavior.**
In interactive mode, a suspension mismatch is a warning. The check must display the mismatch output and prompt the human to confirm before proceeding. It does not block automatically.

**Acceptance criteria for §4:**

| ID | Criterion |
|---|---|
| AC-C-01 | A `gate-suspension.md` with a `SUSPENDED: portability` control line and no corresponding table row causes `suspension_manager.py --check` to exit non-zero with a `SUSPENSION-MISMATCH: portability` finding. |
| AC-C-02 | A `gate-suspension.md` with a table row for `lint` and no corresponding `SUSPENDED: lint` control line causes `suspension_manager.py --check` to exit non-zero with a `SUSPENSION-MISMATCH: lint` finding. |
| AC-C-03 | A `gate-suspension.md` where every control line has a matching table row and every table row has a matching control line causes `suspension_manager.py --check` to exit zero with `suspension-consistency: OK`. |
| AC-C-04 | In unattended mode, a suspension mismatch blocks `gh pr create` from being invoked. |
| AC-C-05 | The transition gate suite invokes `suspension_manager.py --check` and treats a non-zero exit as a gate failure. |

---

## §5 — Suspension Format Parser Unification

### Background

CPS field report #303 Finding 5 confirms a parser mismatch already acknowledged in `contract/gate-suspension.md`. `suspension_manager.py` honors `[pinned]` and `review-by:` flags on a `SUSPENDED:` line. `check_suspension.sh` does not parse these flags and treats any line containing them as a non-match, effectively ignoring the suspension. The result: a human who writes `SUSPENDED: portability [pinned]` believes the gate is suspended, but `check_suspension.sh` runs the gate.

This is a safety-relevant failure mode. It is a correctness fix.

### Canonical suspension line format (authoritative)

A suspension control line must conform to this grammar:

```
SUSPENDED: <gate-name>[<flags>]
```

Where:
- `<gate-name>` is one or more non-whitespace, non-bracket characters (the gate identifier).
- `<flags>` is an optional, space-separated sequence of zero or more of the following, appearing after `<gate-name>` and any whitespace:
  - `[pinned]` — marks the suspension as pinned; auto-removal never applies.
  - `review-by: YYYY-MM-DD` — a recommended review date for the suspension.
- The flags may appear in any order.
- Everything after the gate name and before the end of the line is the flags section; unrecognized tokens in the flags section are ignored and do not invalidate the line.

Examples of valid suspension lines:
```
SUSPENDED: lint
SUSPENDED: portability [pinned]
SUSPENDED: security review-by: 2026-07-01
SUSPENDED: types [pinned] review-by: 2026-08-15
```

### Requirements

**REQ-F-01 — Canonical parser in `suspension_manager.py`.**
`suspension_manager.py` is the canonical parser for the suspension line format. Its parse logic must implement the grammar above. All other tools that need to parse suspension lines must delegate to `suspension_manager.py` or mirror its logic exactly using the same grammar.

**REQ-F-02 — `check_suspension.sh` alignment.**
`check_suspension.sh` must be updated to parse suspension lines using the canonical format. Specifically: when checking whether a given gate is suspended, `check_suspension.sh` must extract the gate name from the `SUSPENDED:` line before comparing, discarding any flags. The gate name is the first non-whitespace token after `SUSPENDED:` and before any `[` or `review-by:` occurrence.

The preferred implementation is for `check_suspension.sh` to invoke `suspension_manager.py --is-suspended <gate-name>` and interpret the exit code (0 = suspended, 1 = not suspended). This delegates parsing entirely to the canonical parser.

**REQ-F-03 — `--is-suspended` command.**
`suspension_manager.py` must expose a `--is-suspended <gate-name>` subcommand that:
1. Reads `contract/gate-suspension.md`.
2. Returns exit code 0 if `<gate-name>` appears as the gate identifier in any valid `SUSPENDED:` line (regardless of flags).
3. Returns exit code 1 otherwise.
4. Emits no output in normal operation (quiet mode).

**REQ-F-04 — `[pinned]` semantics enforcement.**
Both `suspension_manager.py` and any tool reading the suspension file must honor the `[pinned]` flag: a suspension with `[pinned]` must never be auto-removed by `--auto-remove`. This requirement was already specified; it is restated here to confirm it must be enforced by the canonical parser path, not assumed by a secondary parser.

**REQ-F-05 — `review-by:` semantics enforcement.**
The `review-by: YYYY-MM-DD` flag must be parsed by the canonical parser. `suspension_manager.py --census` must warn on any suspension whose `review-by` date is in the past (as it does today). The `check_suspension.sh` tool must not need to interpret `review-by:` — it delegates gate-name extraction to the canonical parser.

**REQ-F-06 — Regression test.**
A regression test must be added to the gate test suite that:
1. Creates a `gate-suspension.md` with `SUSPENDED: portability [pinned]`.
2. Invokes `check_suspension.sh` for the `portability` gate.
3. Asserts that the gate is reported as suspended (not running).

This test encodes the exact failure mode described in #303 Finding 5 and must remain in the suite permanently.

**Acceptance criteria for §5:**

| ID | Criterion |
|---|---|
| AC-F-01 | `check_suspension.sh portability` reports the gate as suspended when `gate-suspension.md` contains `SUSPENDED: portability [pinned]`. |
| AC-F-02 | `check_suspension.sh security` reports the gate as suspended when `gate-suspension.md` contains `SUSPENDED: security review-by: 2026-07-01`. |
| AC-F-03 | `suspension_manager.py --is-suspended portability` exits 0 when `SUSPENDED: portability [pinned]` is present. |
| AC-F-04 | `suspension_manager.py --is-suspended portability` exits 1 when `gate-suspension.md` has no `SUSPENDED: portability` line. |
| AC-F-05 | A gate marked `[pinned]` is not removed by `suspension_manager.py --auto-remove`. |
| AC-F-06 | The regression test for the `[pinned]` parser path is present in the gate test suite and passes. |
| AC-F-07 | `suspension_manager.py --census` warns when a suspension's `review-by` date is in the past. |

---

## Out of Scope

- **Brownfield migration (#275):** The `--brownfield` flag, duplicate-logic check, and consumer pack scaffolding are specified in `SPEC-consumer-pack.md`.
- **Empty PROJECT region stubs (#303 Finding 6):** Deferred; not part of this spec.
- **Gate self-test CI (#303 Finding 1):** Deferred; belongs to framework test infrastructure work.
- **Org migration checklist (#303 Finding 2):** Operational documentation, not installer behavior; out of scope for this spec.
- **Machine account naming config (#303 Finding 3):** Out of scope for this spec.

---

## Implementation Notes for Architect

These are observations from the field reports that the architect and technical-design roles should be aware of. They are not requirements — do not implement them without an architect decision.

- The `SHA256SUMS` per-region hash scheme requires the installer to serialize region content to bytes in a canonical way (e.g., strip trailing whitespace, normalize line endings) before hashing. The exact serialization must be defined by the architect and encoded in the release-cut script and the content-currency checker consistently.
- `suspension_manager.py --is-suspended` as a delegation target for `check_suspension.sh` has a subprocess overhead on every gate invocation. The architect may choose to mirror the canonical parser logic in bash instead, provided the implementation is derived directly from the `suspension_manager.py` grammar definition and a comment in `check_suspension.sh` identifies the corresponding `suspension_manager.py` function.
- The transition gate suite invocation point for `suspension_manager.py --check` (§4 REQ-C-03) must be defined by technical-design in relation to the existing gate-suite ordering.
