# TECHNICAL DESIGN — Evaluator Independent Re-derivation

**Spec:** `docs/specs/SPEC-evaluator-re-derivation.md`
**Issues:** #94, #121, #205, #220, #221, #261
**Target milestone:** v0.4.0 — Autonomous Worker
**Status:** DRAFT — 2026-06-16 — awaiting architect review
**Audience:** coder (implementation contract)

---

## Self-flag (authoring)

RISK: MEDIUM (changes to `change_classifier.py` and the evaluator's Phase 1 compliance loop alter what passes and what fails — a false positive blocks valid work; a false negative misses a governance gap)
CONFIDENCE: HIGH
Change classification: **additive** (new conditions 11–16, new functions, new CLI flags, new fields; no existing condition, function, or field is removed or weakened)

### Human Review Required

- **What changed:** six new Phase 1 compliance conditions (11–16) and the functions/flags/fields they depend on. Conditions 11–15 are new compliance gates; condition 16 is a timing correction (no new gate).
- **Why a human should look:** conditions 11–15 each add a way for Phase 1 to FAIL. The dominant residual risk is a false-positive floor (condition 11 tier floor, condition 13 warranted-lane, condition 14 doc-modification) over-firing and blocking valid work. The design biases every new check to the loosening direction only and to fail toward the human, consistent with conditions 9–10, but the keyword/path heuristics in §1 and §4 are the calibration surface a human should sanity-check.
- **RISK:** MEDIUM · **CONFIDENCE:** HIGH · **Change class:** additive

This is an additive MEDIUM change. It does not require human authorization to author (only structural changes do), but the self-flag block is emitted per the authoring contract.

---

## 0. Architect rulings consumed (binding — not relitigated)

| Ruling | Effect on this design |
|---|---|
| **ARCH-Q-2** (resolved) | Each subagent (dep-mapper, risk-historian, prompt-fidelity) writes a **`.stamp` file** on completion. The evaluator reads stamps as authoritative for condition 12. It does **NOT** trust a self-reported `subagents_run:` field. (This supersedes spec REQ-SUB-1/2/5/7's reliance on a `subagents_run:` header field as the *compliance* source. See §2 note.) |
| **ARCH-Q-5** (resolved) | The **overseer** writes the `step-head` event **post-merge** using the actual merged commit SHA, in its merge-confirmation step. The oversight-orchestrator is **NOT** the writer. (This supersedes spec REQ-HEAD-3, which named oversight-orchestrator.) |
| ARCH-Q-1 | Default stands: tier-floor rules in `change_classifier.py` are kept **separate** from composite validators. No port. Re-evaluate after first implementation. |
| ARCH-Q-3 | Default stands per spec, refined here: §4 modification detection uses a **chunk-level both-removed-and-added** test gated to a tracked document path set, not free keyword scanning of section content. See §4 for the precise definition that keeps the false-positive rate bounded. |
| ARCH-Q-4 | Default stands: ship as-is. The residual `[clarifying]` self-classification laundering gap is documented in §5 as a known limitation; a follow-on issue is recommended (see §5 Open Questions). |

No open blocking question remains for the coder. Two **non-blocking** clarifications are raised for the architect at the end (§9).

---

## 1. Component map

| File | Change type | Summary |
|---|---|---|
| `scripts/oversight/change_classifier.py` | new functions + CLI flags + diff-collection change | `detect_tier_floor()`, `detect_warranted_lanes()`, `detect_structural_modifications()`; `collect_diff()` returns removed lines; `--tier-floor`, `--warranted-lanes`, `--modifications-only` flags |
| `.claude/agents/oversight-evaluator.md` | new Phase 1 checks (CORE) | Conditions 11–15; remove the Phase-1 `step-head` write (moved to overseer); read stamps for condition 12 |
| `.claude/agents/overseer.md` (or the overseer agent file) | new merge-confirmation step (CORE) | Writes `step-head` post-merge with `merged_sha` (condition 16 / §6) |
| `.claude/agents/risk-assessor.md` | new subagent-stamp instruction (CORE) | Subagents write `.stamp` files; risk-assessor still records `subagents_run:` informationally |
| `.claude/agents/dep-mapper.md`, `risk-historian.md`, `prompt-fidelity.md` | new completion-stamp step (CORE) | Each writes its own `.stamp` on completion |
| `.claude/agents/pm-agent.md` | new sign-off fields (CORE) | `Behavior_delta:` + `Change_classification:` in `process` register entries on spec/design changes |
| `.claude/agents/ux-designer.md` | new sign-off fields (CORE) | Same `Behavior_delta:` + `Change_classification:` requirement |
| `contract/OVERSIGHT-CONTRACT.md` | spec additions | Conditions 11–16 in §7; stamp-file contract in §7b; `Behavior_delta:`/`Change_classification:` in §3; new audit events in §6a; `step-head` timing + `merged_sha` in §6a |
| `audit/oversight-log.jsonl` event catalog | new events | `tier-floor-mismatch`, `subagent-skipped`, `warranted-lane-absent`, `doc-modification-uncovered`, `spec-change-behavior-delta`; `step-head` gains `merged_sha`/`merged_at` |

**Boundary that every component must honor:** all five new compliance conditions (11–15) run **only in the loosening direction** and **fail toward the human**, exactly mirroring conditions 9–10. No new check may fire when upstream asked for *more* oversight (a higher self-reported tier, a present sign-off, an existing human-authorization artifact). A check that cannot prove loosening must pass, not fail.

---

## 2. `change_classifier.py` — exact contracts

All three new detection functions are pure: they take diff-derived inputs and return a value with no side effects, no git calls, no file writes. Git access stays in `collect_diff()`/`resolve_range()`. This keeps the functions unit-testable from synthetic `name_status`/`added`/`removed` fixtures.

### 2.1 `collect_diff()` — track removed lines (REQ-MOD-4)

**Current signature:**
```python
def collect_diff(base: str, head: str) -> tuple[list[tuple[str, str]], dict[str, list[str]]]:
    # returns (name_status, added_lines_by_file)
```

**New signature:**
```python
def collect_diff(base: str, head: str) -> tuple[
    list[tuple[str, str]],   # name_status: (status_letter, path)
    dict[str, list[str]],    # added_by_file: path -> added content lines (no leading '+')
    dict[str, list[str]],    # removed_by_file: path -> removed content lines (no leading '-')
]:
```

**Behavior the coder must implement:**
- Parse the same `git diff --unified=0 base..head` output already parsed for added lines.
- Track the current file from `--- a/<path>` header lines symmetrically to the existing `+++ b/<path>` handling. A diff chunk's removed lines are attributed to the `a/` path.
- A removed content line begins with `-` and is **not** a `---` file header. Strip the leading `-`.
- Populate `removed_by_file[path]` per chunk.

**Boundary — must not break existing callers:** `detect_domains()` and `detect_structural()` take `(name_status, added)` today. Update all call sites in `main()` to unpack the third value. The two existing functions keep their current signatures (they do not need `removed`). Do not change their behavior.

### 2.2 `detect_tier_floor()` (REQ-TIER-1/2, §1)

**Exact signature:**
```python
def detect_tier_floor(name_status: list[tuple[str, str]],
                      added: dict[str, list[str]]) -> dict:
    """Return the deterministic tier floor and the evidence that set it.

    Returns:
      {
        "tier_floor": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
        "evidence": [ {"rule": "<rule-name>", "file": "<path>",
                       "pattern": "<matched-pattern-or-line>"}, ... ],
      }
    """
```

> **Note on the task-brief signature.** The task brief gives `detect_tier_floor(changed_files: list[str]) -> str`. This design widens it to accept `(name_status, added)` and return a dict, for two binding reasons: (a) the spec REQ-TIER-2 CRITICAL/HIGH triggers include **added-line** patterns (`stripe.`, `PaymentIntent`, `EmailField`, …) that a file-path-only list cannot detect; (b) REQ-TIER-3/4 require an `evidence` array in the output and the fail message. A path-only `-> str` cannot satisfy the spec. The coder implements the dict-returning form. The `--tier-floor` CLI flag emits the dict as JSON (REQ-TIER-3).

**Rule table — evaluate ALL rules; the HIGHEST resulting floor wins.** Tier rank from `schema.py` ordering: `SAFE=0, LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4`. (Note: `schema.py` `score_to_tier()` returns `LOW` as its lowest tier; `SAFE` is rank 0 reserved but not produced by this function — this function's lowest output is `LOW`.)

| Floor | Channel | Trigger (rule name) |
|---|---|---|
| CRITICAL | path | `payment-path`: any changed file matching `**/payment*`, `**/billing*`, `**/financial*`, `**/checkout*`, `**/subscription*`, `**/invoice*`, `**/stripe*`, `**/braintree*`, `**/paypal*` |
| CRITICAL | added-line | `financial-api`: any added line matching `stripe\.`, `braintree\.`, `PaymentIntent`, `\bcharge\(`, `\bCard\(`, `\bACH\b`, `\bIBAN\b`, `account_number` |
| HIGH | path | `auth-path`: any changed file matching `**/auth*`, `**/login*`, `**/logout*`, `**/session*`, `**/token*`, `**/credential*`, `**/password*`, `**/mfa*`, `**/totp*`, `**/oauth*`, `**/sso*`, `**/jwt*`, `**/permission*` |
| HIGH | path | `migration`: any changed file matching `**/migrations/*.py` |
| HIGH | path | `prod-settings`: any changed file matching `**/settings/production*` |
| HIGH | path | `privacy-path`: any changed file matching `**/pii*`, `**/gdpr*`, `**/privacy*`, `**/consent*` |
| HIGH | added-line | `pii-field`: any added line matching `EmailField`, `first_name`, `last_name`, `date_of_birth`, `\bssn\b`, `national_id`, `phone_number`, `\baddress\b`, `personal_data` |
| MEDIUM | path | `app-logic`: any changed file matching `\.(py|js|ts|jsx|tsx)$`, OR any `.sh` file under `scripts/oversight/gates/`, not already matched by a higher tier |
| LOW | — | `default`: everything else |

**Boundaries the coder must honor:**
- **Framework-tooling exemption.** Re-use the existing `FRAMEWORK_TOOLING` regex (`(^|/)scripts/(oversight|framework)/.*\.py$`). The **added-line** rules (`financial-api`, `pii-field`) MUST skip files matching `FRAMEWORK_TOOLING` — those patterns appear in the classifier's own source as literal definitions and would self-match (HOS#117). The **path** rules also skip `FRAMEWORK_TOOLING` files for `app-logic` and `migration`. The explicit exception, matching existing precedent: dependency-manifest and new-template signals still apply everywhere — but those are not tier-floor rules, so for `detect_tier_floor()` the rule is simply: skip `FRAMEWORK_TOOLING`-matching `.py` files for all path and added-line rules.
- **`migrations/*.py` vs. financial migrations.** The task brief splits migrations into "adds/modifies a table with financial columns → CRITICAL" vs. "non-financial → HIGH". This design implements the simpler, spec-faithful form: **all `**/migrations/*.py` → HIGH floor**, and a migration that *also* matches a `payment-path` or `financial-api` trigger independently raises the floor to CRITICAL via those rules. The coder does NOT parse migration column semantics. (Rationale: column-level financial detection is a separate `migration_scorer.py` concern per ARCH-Q-1's keep-separate ruling; double-counting is avoided by letting the path/line rules do the elevation.)
- Glob patterns (`**/payment*`) are matched against the full path. Implement with `fnmatch.fnmatch(path, pattern)` over `**`-normalized patterns, or compile to regex — coder's choice, but matching MUST be case-insensitive and MUST match a path segment anywhere (e.g. `app/payment/views.py` matches `**/payment*`).
- The function returns the highest floor with its first triggering evidence per rule; `evidence` lists one entry per *fired* rule (deduplicate by rule name; first file/line that fired it).

### 2.3 `detect_warranted_lanes()` (REQ-REV-1/2, §3)

**Exact signature:**
```python
def detect_warranted_lanes(name_status: list[tuple[str, str]],
                           added: dict[str, list[str]]) -> dict:
    """Return reviewer lanes the diff deterministically warrants.

    Returns:
      {
        "warranted": { "<lane>": {"by": "path"|"added-line",
                                  "file": "<path>", "evidence": "<...>"}, ... }
      }
    """
```

**Implementation — reuse `detect_domains()`.** The spec (REQ-REV-1) is explicit: warranted lanes ARE the domains `detect_domains()` already computes. The coder MUST NOT introduce a parallel pattern set. `detect_warranted_lanes()` is a thin wrapper:
```
domains = detect_domains(name_status, added)   # existing function, all roles
warranted = { role: ev for role, ev in domains.items() }  # lane name == role key
```
The mapping lane↔domain is identity for `security`, `privacy`, `ops`, `reliability`, `ui`, `a11y`, `infra` — the keys in `DOMAIN_RULES`. The task brief's bespoke trigger lists (`requests\.`, `@shared_task`, `password`/`token`/`secret`) are already encoded in `DOMAIN_RULES` (`reliability`, `ops`, `security`). Re-deriving them in a second place would create drift; this design routes everything through `DOMAIN_RULES` (single source of truth).

**Boundary:** `detect_warranted_lanes()` reports a lane as warranted iff `detect_domains()` reports its domain touched. No lane is invented beyond `DOMAIN_RULES` keys. The evaluator (not this function) intersects warranted lanes with the project's `role_mappings` (REQ-REV-7) — the classifier reports all detected lanes; project scoping is an evaluator-side filter.

### 2.4 `detect_structural_modifications()` (REQ-MOD-1/2/3, §4)

**Exact signature:**
```python
def detect_structural_modifications(name_status: list[tuple[str, str]],
                                    added: dict[str, list[str]],
                                    removed: dict[str, list[str]]) -> dict:
    """Detect non-additive edits to existing sections of tracked governance docs.

    Returns:
      {
        "doc_modifications": [
          {"file": "<path>", "section": "<nearest-header-or-'(unknown)'>",
           "evidence": {"removed": "<one removed line>", "added": "<one added line>"}},
          ...
        ]
      }
    """
```

> **Note on the task-brief signature.** The brief gives `detect_structural_modifications(diff_text: str) -> list[str]`. This design takes `(name_status, added, removed)` and returns a dict, because (a) §4 must distinguish *which file* and *which section* (REQ-MOD-8 fail message requires file + section + removed/added evidence), and (b) reusing the already-parsed `added`/`removed` per-file maps avoids a second raw-diff parse. The `--modifications-only` flag emits the dict as JSON (REQ-MOD-5).

**Tracked-document path set (REQ-MOD-2).** A file is in scope iff its path matches any of:
- `docs/specs/SPEC-*.md`, `docs/v*/SPEC-*.md`
- `docs/v*/TECHNICAL-DESIGN-*.md`, `TECHNICAL-DESIGN-*.md`
- `docs/v*/DESIGN*.md`, `DESIGN.md`
- `contract/OVERSIGHT-CONTRACT.md`
- `.claude/agents/*.md`
- `TELEMETRY-SPEC.md`, `docs/ops/TELEMETRY-SPEC.md`

**"Structural modification" definition (REQ-MOD-3 — the ARCH-Q-3 resolution).** For a tracked file, a modification is reported iff the file has **both** at least one removed line AND at least one added line in the diff (`removed[file]` non-empty AND `added[file]` non-empty). This is the per-file both-sides test. The design deliberately does **NOT** keyword-scan section content (the ARCH-Q-3 false-positive risk): any non-additive edit to a governance/spec/design/contract/agent doc is a candidate, because those documents are structural by location. A purely additive change (`removed[file]` empty) is an extension, never a modification — it does not fire.

- **`section`** is best-effort: the nearest preceding Markdown header (`^#{1,6} `) to the first changed line. Implement by scanning the file's diff hunk headers (`@@ ... @@` carry the enclosing function/section context git emits with `--unified`). If unavailable, emit `"(unknown)"`. Section identification is informational for the fail message; it is NOT load-bearing for whether the condition fires.
- **`evidence.removed`/`evidence.added`** are the first removed and first added line for the file (trimmed to 120 chars), matching the existing evidence-string convention.

**Boundary:** the both-sides test is per-file, not per-chunk, to keep the implementation simple and the false-positive direction safe (over-detect → human looks). A file with removals in one section and additions in a different section still fires — acceptable, because both are edits to a governance doc and a human glance is the only cost. Pure additions never fire.

### 2.5 CLI flags (REQ-TIER-3, REQ-MOD-5, §3)

Add three flags to `main()`, each emitting only its own payload as JSON (mirroring `--domains-only`/`--structural-only`):

| Flag | Output JSON |
|---|---|
| `--tier-floor` | `{"base","head","tier_floor","evidence":[...]}` |
| `--warranted-lanes` | `{"base","head","warranted":{...}}` |
| `--modifications-only` | `{"base","head","doc_modifications":[...]}` |

- Each flag is mutually composable with `--explain` (human-readable form) and `--base`/`--head`.
- When `--tier-floor` / `--warranted-lanes` / `--modifications-only` is set, the default combined output (`domains_touched` + `structural_signals`) is suppressed, identical to how `--domains-only`/`--structural-only` scope the output today.
- Exit code stays `0` always (reporter; the evaluator decides), `2` on git error — unchanged.

---

## 3. Evaluator compliance checks — exact specifications

All conditions run in **Phase 1**, after the existing conditions 1–10, using the register-header `BASE_SHA`/`HEAD_SHA` commit range already established at the top of Phase 1. Each condition that fires → **COMPLIANCE FAIL** → `ESCALATE` (per contract §7 closing line), and appends its audit event.

### Condition 11 — Tier floor re-derivation (§1, #94)

| Field | Value |
|---|---|
| **Inputs** | `validated_tier` from `.claudetmp/oversight/validators/risk-assessment.md` header; `detect_tier_floor()` via `change_classifier.py --tier-floor --base $BASE_SHA --head $HEAD_SHA` |
| **Read note** | Read the tier with `grep -i '^validated_tier:'` — **NOT** `^tier:`. (The self-validation finding 20260615T160517 documents that `^tier:` cannot match the artifact's `validated_tier:` field; this condition must not repeat that bug.) |
| **Rank map** | `SAFE=0, LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4` (schema.py ordering) |
| **Fail condition** | `rank(validated_tier) < rank(tier_floor)` AND no `.claudetmp/oversight/step{N}-human-tier-override.md` exists |
| **Pass conditions** | `rank(validated_tier) >= rank(tier_floor)` (conservative is fine — loosening-direction only); OR a `human-tier-override.md` artifact exists (human explicitly authorized a lower tier) |
| **Fail message** | `"Self-reported tier {validated_tier} is below the deterministic floor {tier_floor} for these changed files: {evidence}"` — list the specific files/patterns from the `evidence` array |
| **Audit event** | `tier-floor-mismatch` — `{step, re_derived_floor, self_reported_tier, evidence[], timestamp}` |

### Condition 12 — Mandated subagent stamps (§2, #221) — **per ARCH-Q-2: stamp-based**

| Field | Value |
|---|---|
| **Authoritative source** | **`.stamp` files**, NOT the `subagents_run:` header field (ARCH-Q-2). The evaluator globs the stamp directory; it does not parse `subagents_run:` for the compliance decision. |
| **Stamp path glob** | `.claudetmp/oversight/subagents/<subagent-name>-<step>-*.stamp` |
| **HIGH+ required** | `dep-mapper-{N}-*.stamp` AND `risk-historian-{N}-*.stamp` must each glob-match at least one file |
| **MEDIUM+ required (conditional)** | `prompt-fidelity-{N}-*.stamp` must match **iff** a prompt artifact exists for the step — i.e. the commit range carries a `Prompt-Artifact:` git trailer pointing to an existing file. The evaluator re-derives applicability from the commit range, NOT from any self-reported absence (REQ-SUB-4). |
| **Applicability by tier** | LOW/MEDIUM: dep-mapper, risk-historian NOT required. MEDIUM: prompt-fidelity required iff prompt artifact exists. HIGH/CRITICAL: dep-mapper + risk-historian required; prompt-fidelity required iff prompt artifact exists. (Per spec REQ-SUB-3 table.) |
| **Fail condition** | A required stamp glob matches zero files |
| **Fail message** | `"Required subagent {name} did not complete for step {N} — stamp file absent. Validated tier {tier}; stamps found: {list}."` |
| **Stamp content** | Informational only — **no schema validation** for compliance (ARCH-Q-2). Existence is the check. |
| **Audit event** | `subagent-skipped` — `{step, validated_tier, required_subagents[], present_stamps[], missing[], timestamp}` |

**Boundary:** the evaluator MUST NOT trust `subagents_run:` in `risk-assessment.md` for this check. `subagents_run:` remains in the header as an informational/cross-reference field (risk-assessor still writes it), but condition 12 reads stamps. If `subagents_run:` and the stamp set disagree, the stamps win and condition 12 is decided by stamps alone.

### Condition 13 — Warranted reviewer-lane SET (§3, #261)

| Field | Value |
|---|---|
| **Inputs** | `detect_warranted_lanes()` via `change_classifier.py --warranted-lanes --base $BASE_SHA --head $HEAD_SHA`; the sign-off register; the step manifest `role_mappings` |
| **Project scoping** | Intersect warranted lanes with `role_mappings` (REQ-REV-7). A lane not in `role_mappings` is out of scope — never a compliance gap. |
| **Per-lane evaluation** | For each in-scope warranted lane: entry `Status: APPROVED`/`CONDITIONAL` → pass; `Status: ESCALATED` with `Human_resolution:` → pass; `Status: N/A` → **defer to condition 9** (do NOT report under 13); **no entry at all** → **FAIL** |
| **Precedence vs. condition 9** | Condition 9 owns the N/A case. If a warranted lane has an N/A entry, condition 9 re-derives its validity; condition 13 does not double-report. Condition 13 fires only when the register has **no entry whatsoever** for the warranted lane. |
| **Fail condition** | An in-scope warranted lane has no register entry (absent, not N/A) |
| **Direction** | Loosening only: a register entry for a lane the diff did NOT warrant is accepted as-is (REQ-REV-4) — the evaluator can add lanes, never waive lanes risk-assessor required |
| **Fail message** | `"Warranted reviewer lane '{lane}' has no sign-off register entry. Diff triggered it via {evidence.by}: {evidence.file} «{evidence.evidence}»."` |
| **Audit event** | `warranted-lane-absent` — `{step, lane, domain, evidence, finding:"absent", timestamp}` |

### Condition 14 — Structural document modifications (§4, #121)

| Field | Value |
|---|---|
| **Inputs** | `detect_structural_modifications()` via `change_classifier.py --modifications-only --base $BASE_SHA --head $HEAD_SHA`; human-authorization artifacts |
| **Coverage check** | For each detected `doc_modification`, a covering artifact must exist: `.claudetmp/oversight/step{N}-human-authorization.md` OR `.claudetmp/oversight/step{N}-spec-structural-auth.md` (non-empty) |
| **Fail condition** | `doc_modifications` non-empty AND no covering authorization artifact exists |
| **Direction** | Loosening only: if the change was already classified `structural` by the authoring agent AND a human-authorization artifact exists → no check (REQ-MOD-7). Pure additions never appear in `doc_modifications` (handled in `detect_structural_modifications`). |
| **Fail message** | `"Structural modification to {file} (section '{section}') has no covering human authorization. Removed: «{evidence.removed}» / Added: «{evidence.added}»."` — list every uncovered modification |
| **Audit event** | `doc-modification-uncovered` — `{step, file, section, evidence, timestamp}` |

### Condition 15 — Spec-change behavior delta (§5, #205)

| Field | Value |
|---|---|
| **Trigger scope** | A `process` sign-off entry (pm-agent or ux-designer) is present AND the step diff touches a tracked spec/design doc (`docs/specs/*.md`, `docs/v*/*.md`, `docs/v*/TECHNICAL-DESIGN-*.md`, `TELEMETRY-SPEC.md`, `UX-DESIGN-READINESS.md`) |
| **Required fields** | `Behavior_delta:` and `Change_classification:` in the `process` entry |
| **Fail mode (a) — missing field** | Trigger scope met AND `Behavior_delta:` absent or malformed → **FAIL**: `"pm-agent/ux-designer sign-off missing required Behavior_delta field for spec change to {file}."` |
| **Fail mode (b) — unauthed behavior** | `Behavior_delta:` contains any `[new]` or `[modified]` entry AND `Change_classification:` is `additive` (or `new`/`modified`) AND no human-authorization artifact (`step{N}-human-authorization.md` or `step{N}-spec-structural-auth.md`) exists → **FAIL**: list the specific `[new]`/`[modified]` delta entries |
| **Pass** | `Behavior_delta:` present with only `[clarifying]`/`[removed]`/`none` entries, OR `Change_classification: clarifying`/`none`, OR a covering human-authorization artifact exists |
| **Audit event** | `spec-change-behavior-delta` — `{step, failure_mode:"missing_field"|"new_behavior_unauthed", file, delta_entries[], timestamp}` |

> **Field-value reconciliation.** The spec REQ-SPEC-1 enumerates delta markers `[new | modified | removed]` plus a `[clarifying]` line; the task brief gives `Behavior_delta: [new | modified | clarifying | none]`. This design accepts the **union**: a `Behavior_delta:` entry marker is one of `new`, `modified`, `removed`, `clarifying`, `none`. Only `new` and `modified` trigger the human-auth requirement in fail mode (b). `Change_classification:` is one of `additive`, `structural`, `clarifying`, `none` (REQ-SPEC-1). The pm-agent/ux-designer CORE updates must document this closed value set.

### Condition 16 — Step-head timing (§6, #220) — **not a compliance gate**

Condition 16 is a timing correction, not a Phase-1 FAIL. See §5 below. The evaluator's only change for condition 16 is to **stop writing the `step-head` event at Phase 1** (current evaluator line ~59) and tolerate older pre-PR `step-head` entries (REQ-HEAD-5). The post-merge write moves to the overseer.

---

## 4. Stamp file contract (§2, ARCH-Q-2)

**Path convention:**
```
.claudetmp/oversight/subagents/<subagent-name>-<step>-<ts>.stamp
```
- `<subagent-name>` ∈ `{dep-mapper, risk-historian, prompt-fidelity}` (canonical role keys)
- `<step>` is the integer step number
- `<ts>` is an ISO-8601 compact timestamp (e.g. `20260616T142233`) for uniqueness across re-runs

**Content (one-line JSON):**
```json
{"subagent": "<name>", "step": "<step>", "cid": "<cid>", "completed_at": "<ISO-8601>"}
```

**Writer responsibility:** each subagent writes its **own** stamp as the final action on successful completion. The CORE region of `dep-mapper.md`, `risk-historian.md`, and `prompt-fidelity.md` gains a "write completion stamp" step. risk-assessor does NOT write stamps on behalf of subagents (independent attestation — the entire point of ARCH-Q-2).

**Reader responsibility:** the evaluator globs `.claudetmp/oversight/subagents/<name>-{N}-*.stamp` for existence only. Content is informational; no schema validation gates compliance. If multiple stamps match (re-runs), any one satisfies existence.

**Directory creation:** subagents `mkdir -p .claudetmp/oversight/subagents` before writing. The directory is under `.claudetmp/` and is not committed (per CLAUDE.md gitignore rules).

---

## 5. Step-head timing — overseer post-merge write (§6, ARCH-Q-5)

**Removed:** the evaluator's Phase-1 `step-head` append (current evaluator instruction line ~59). The evaluator no longer writes `step-head`. It continues to *read* the previous step's `step-head` `head_sha` as its `base_sha` (REQ-HEAD-4, unchanged).

**Added — overseer merge-confirmation step (the overseer's autonomous step 6, after AUTO_MERGE success):** append one line to `audit/oversight-log.jsonl`:
```json
{"event": "step-head", "step": N, "base_sha": "<prev step head_sha>", "head_sha": "<merged_sha>", "merged_sha": "<merged_sha>", "merged_at": "<ISO-8601>", "merged_by": "hos-overseer-hos[bot]", "pr_number": "<n>", "timestamp": "<ISO-8601>"}
```

**Contract on the SHA:** `merged_sha`/`head_sha` is the **actual merged commit SHA** after the squash merge — obtained from the merge result (`gh pr merge` output or `git rev-parse <branch>` post-merge), NOT the pre-PR branch head. `base_sha` is the previous step's `head_sha`. `merged_at` is when the merge happened; `timestamp` is when this log line was written.

**Idempotency / supersession (REQ-HEAD-1):** this post-merge `step-head` for step N **replaces** any prior `step-head` written for the same step pre-PR. The next step uses `grep step-head | <select step N> | tail -1` — the last-written entry wins, so the post-merge entry must be appended after any historical one. The evaluator MUST NOT also write a competing `step-head` (that's why its Phase-1 write is removed).

**Schema field:** `merged_sha` is the new field named in the task brief; `head_sha` carries the same value for backward-compatibility with the existing reader (`sed -n 's/.*"head_sha":"\(...\)".*/\1/p'`). Both are present; readers keyed on `head_sha` keep working unchanged.

**Backward tolerance (REQ-HEAD-5):** the evaluator tolerates older `step-head` entries missing `base_sha`/`merged_at`/`merged_sha`; it uses the available `head_sha` and logs a warning. No compliance check fires on historical entries.

---

## 6. Sign-off register field additions (§5, #205)

Added to the `process`-role sign-off entry written by pm-agent or ux-designer **whenever the entry covers a change to a tracked spec/design document**:

```markdown
## process | SPEC-{feature}.md | {ISO-8601 datetime}
Status: APPROVED
Agent: pm-agent
Artifact: docs/specs/SPEC-{feature}.md
Iterations: 1
Change_classification: additive | structural | clarifying | none
Behavior_delta:
  - [new | modified | removed | clarifying | none] {one-line description of the user-visible behavior or obligation}
  - [new | modified | removed | clarifying | none] {next behavior}
Notes: ...
```

- **`Change_classification:`** — closed value set `{additive, structural, clarifying, none}`.
- **`Behavior_delta:`** — a YAML/markdown list; each item begins with a bracketed marker from `{new, modified, removed, clarifying, none}`. For a purely clarifying change, a single line `- [clarifying] no behavior change` is valid.
- Required only when the entry covers a tracked spec/design doc change (REQ-SPEC-2). Not required for non-spec process sign-offs.

The contract §3 sign-off schema gains both field definitions; the pm-agent and ux-designer CORE regions gain the requirement to write them.

---

## 7. Contract (`OVERSIGHT-CONTRACT.md`) edits

| Section | Edit |
|---|---|
| §7 | Add conditions 11–15 (full text per §3 above); add condition 16 as a timing note (no gate). Extend the "Conditions 9–10 are anti-gaming" paragraph to "9–15". |
| §7b | Add the **stamp-file contract** (§4 above) as the authoritative source for condition 12; note `subagents_run:` is informational only. |
| §3 | Add `Change_classification:` and `Behavior_delta:` field definitions (§6 above). |
| §6a (audit events) | Add `tier-floor-mismatch`, `subagent-skipped`, `warranted-lane-absent`, `doc-modification-uncovered`, `spec-change-behavior-delta`; update `step-head` to carry `base_sha`/`head_sha`/`merged_sha`/`merged_at`/`pr_number`/`merged_by`, written **post-merge by the overseer**. |
| §2a | Reference condition 14 as the new narrow closure of the documented "Residual coverage gap" for modifications to existing structural sections of tracked governance docs. |

---

## 8. Test surface the coder must enable (for unit-test / system-test roles)

Each detection function is pure and unit-testable from synthetic fixtures (no git). The coder must keep them so. Minimum acceptance fixtures (mirroring the spec's acceptance criteria — restated here as the testable contract):

**`detect_tier_floor()`:**
- auth-path-only diff → `tier_floor == "HIGH"`.
- payment-path diff → `tier_floor == "CRITICAL"`.
- added line `stripe.PaymentIntent.create(...)` in a non-framework file → `CRITICAL`.
- `**/migrations/0002_x.py` → `HIGH`.
- a `.py` file outside all higher rules → `MEDIUM`.
- a `scripts/oversight/*.py` file containing `EmailField` (the classifier's own source) → does NOT raise floor (FRAMEWORK_TOOLING exempt).
- a `README.md`-only diff → `LOW`.

**Condition 11 (evaluator):** `validated_tier: MEDIUM` + auth-path diff → fires; `validated_tier: HIGH` + auth-path diff → does not fire; `human-tier-override.md` present → does not fire.

**`detect_warranted_lanes()`:** `requests.get(url)` added → `reliability` warranted; `@shared_task` added → `ops`; password handling in non-test `.py` → `security`.

**Condition 13:** `requests.get` + no `reliability` entry → fires; `Status: APPROVED` reliability entry → no fire; `Status: N/A` reliability entry → condition 9 owns it (13 does not fire); reliability entry but no `requests.` in diff → no fire; `role_mappings` omits `reliability` → never fires for that lane.

**`detect_structural_modifications()`:** a chunk in `TECHNICAL-DESIGN.md` removing one line + adding another in an existing section → reported; a purely additive new `## Authorization` section (no removals) → NOT reported; a `README.md` modification → NOT reported (out of tracked set).

**Condition 14:** detected modification + no auth artifact → fires; same + `step{N}-human-authorization.md` present → no fire.

**Condition 15:** `[new]` delta + `additive` + no auth → fires (mode b); `Behavior_delta:` absent + spec touched → fires (mode a); `[clarifying]` + `clarifying` → no fire; no tracked spec/design doc in diff → not checked.

**Condition 12:** HIGH step, dep-mapper stamp absent → fires; all three stamps present → no fire; MEDIUM + no prompt artifact + no stamps → no fire; MEDIUM + prompt artifact present + prompt-fidelity stamp absent → fires.

**Step-head (overseer):** post-merge `step-head` has `head_sha == merged_sha == actual merged commit`; next step reads it as `base_sha`; an old entry missing `merged_at` does not break the reader.

---

## 9. Open questions for the architect (non-blocking)

Both blocking questions (ARCH-Q-2, ARCH-Q-5) are resolved and consumed. Two clarifications surfaced during design — neither blocks the coder; flagged for the architect's awareness:

1. **`subagents_run:` field retention.** ARCH-Q-2 makes stamps authoritative and the `subagents_run:` header field informational. Should the field be **kept** (cross-reference / human-readable convenience, accepting it can disagree with stamps) or **removed** (single source of truth, less drift surface)? This design keeps it as informational. If the architect prefers removal, REQ-SUB-1/7 in the spec and the risk-assessor CORE edit drop the field entirely. Default: keep.

2. **`detect_warranted_lanes()` as a thin wrapper over `detect_domains()`.** This design routes lane detection through the existing `DOMAIN_RULES` rather than the task brief's separate trigger lists, to avoid a second pattern set that would drift from condition 9's domain re-derivation. The architect should confirm this single-source-of-truth choice is preferred over a distinct lane-trigger set. Default: wrapper over `detect_domains()`.

---

## 10. Iteration status

**Status: AWAITING ARCHITECT REVIEW.** Per the technical-design contract this design is NOT to be handed to the coder until the architect approves. Iteration 1. Revision notes will be written to `.claudetmp/design/technical-design-evaluator-re-derivation-<ISO-timestamp>.md` on architect feedback.
