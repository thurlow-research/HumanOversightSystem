# SPEC: Evaluator Independent Re-derivation
**Issues:** #94, #121, #205, #220, #221, #261
**Target milestone:** v0.4.0 — Autonomous Worker
**Status:** DRAFT — 2026-06-16
**Audience:** technical-design (implementation contract), architect (open questions)

---

## Preamble — The Unifying Architectural Principle

The six issues in this spec are variants of one architectural gap: **loosening determinations are self-reported by the agents that benefit from them, not independently re-derived.**

The oversight evaluator already applies independent re-derivation in two places: it re-derives N/A waiver validity from the diff (condition 9, `change_classifier.py`) and re-derives structural-override signals from the diff (condition 10). The pattern is established and works. This spec extends it to the remaining loosening determinations:

| Loosening determination | Self-reported by | Issue |
|---|---|---|
| Risk tier (is this HIGH or CRITICAL?) | risk-assessor | #94 |
| Which subagents ran at HIGH+ | risk-assessor | #221 |
| Which reviewer lanes are required | risk-assessor | #261 |
| Whether a spec/design change modifies existing behavior | pm-agent / ux-designer | #121, #205 |
| This step's commit range (step-head anchor) | oversight-evaluator (at wrong time) | #220 |

The fix in every case follows the same pattern already in use for conditions 9–10:
- Re-derive the expected answer from the diff using deterministic rules
- Compare against the self-reported value
- Fail in the loosening direction only (never re-check when upstream asked for more oversight)
- Escalate to the human on mismatch

Each section below is a numbered requirement set with acceptance criteria. Each section concludes with a compliance-condition number (11 through 16) that extends the existing §7 compliance check in `contract/OVERSIGHT-CONTRACT.md`.

**Open questions for the architect are flagged inline as `[ARCH-Q-N]`.**

---

## §1 — Independent Tier Floor Re-derivation (#94)

### Background

`risk-assessor` computes a deterministic tier floor (auth paths → HIGH, booking/payment/financial paths → CRITICAL, migration patterns → HIGH, PII fields → HIGH) and records the validated tier in `.claudetmp/oversight/validators/risk-assessment.md`. The evaluator's existing human-gate check (contract §7, condition 7) reads that file to get the validated tier and re-derives the effective-human-gate requirement from it. But the tier itself is trusted from the self-reported file — a risk-assessor that under-computes the tier (drift, misconfiguration, or a forged artifact) causes the evaluator to derive the wrong human-gate requirement.

The primary human gate is `manifest.human_gate_required: true`, set by a human. The tier-floor path is defense-in-depth. A tier under-computation does not remove the primary gate but does remove the secondary guarantee.

### Requirements

**REQ-TIER-1.** `change_classifier.py` must implement a `detect_tier_floor(name_status, added) -> str` function that returns one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` using the path/pattern rules below. This function is the authoritative, independently-executed tier floor.

**REQ-TIER-2.** Path/pattern rules that determine the floor (apply in order; the highest tier wins):

| Tier floor | Trigger |
|---|---|
| CRITICAL | A changed file whose path matches any of: `**/payment*`, `**/billing*`, `**/financial*`, `**/checkout*`, `**/subscription*`, `**/invoice*`, `**/stripe*`, `**/braintree*`, `**/paypal*` |
| CRITICAL | An added line matching PCI/financial API patterns: `stripe.`, `braintree.`, `PaymentIntent`, `charge(`, `Card(`, `ACH`, `IBAN`, `account_number` |
| HIGH | A changed file whose path matches any of: `**/auth*`, `**/login*`, `**/logout*`, `**/session*`, `**/token*`, `**/credential*`, `**/password*`, `**/mfa*`, `**/totp*`, `**/oauth*`, `**/sso*`, `**/jwt*` |
| HIGH | A changed file matching the migration pattern: `**/migrations/00*.py` or `**/migrations/*.py` |
| HIGH | An added line matching PII field patterns: `EmailField`, `first_name`, `last_name`, `date_of_birth`, `ssn`, `national_id`, `phone_number`, `address`, `personal_data` |
| HIGH | A changed file whose path matches: `**/pii*`, `**/gdpr*`, `**/privacy*`, `**/consent*` |
| MEDIUM | A changed file matching general application logic patterns (`.py`, `.js`, `.ts`, `.jsx`, `.tsx`) not covered by a higher tier |
| LOW | All other changes |

**REQ-TIER-3.** `change_classifier.py` must accept a `--tier-floor` flag that emits `{"tier_floor": "<TIER>", "evidence": [{"rule": "...", "file": "...", "pattern": "..."}]}` to stdout. It does not emit domains or structural signals when this flag is used.

**REQ-TIER-4.** The oversight evaluator, during Phase 1 compliance check, must:
1. Run `change_classifier.py --tier-floor --base <base_sha> --head <head_sha>` using the register header's commit range.
2. Read the `tier_floor` from the result.
3. Read the `validated_tier` from `risk-assessment.md`.
4. If `validated_tier` is below `tier_floor` AND no `human-tier-override.md` exists → **COMPLIANCE FAIL** (condition 11): report the re-derived floor, the self-reported tier, and the evidence list. The fail message must include the specific files/patterns that triggered the floor.

**REQ-TIER-5.** This check runs **only in the loosening direction**: if `validated_tier >= tier_floor`, no check is performed. If `human-tier-override.md` exists (human explicitly authorized a lower tier), no check is performed regardless of floor.

**REQ-TIER-6.** A new audit event `tier-floor-mismatch` must be appended to `audit/oversight-log.jsonl` when condition 11 fires. Required fields: `step`, `re_derived_floor`, `self_reported_tier`, `evidence` (array), `timestamp`.

### Acceptance Criteria

- A diff containing only auth-path changes with `validated_tier: MEDIUM` in `risk-assessment.md` → condition 11 fires, evaluation escalates.
- A diff containing only auth-path changes with `validated_tier: HIGH` → condition 11 does not fire.
- A diff containing auth-path changes where `human-tier-override.md` exists → condition 11 does not fire.
- `change_classifier.py --tier-floor --explain` produces human-readable output listing each triggered rule.
- The tier floor rules produce no false positives against the HOS framework tooling tree (use the existing `FRAMEWORK_TOOLING` exemption pattern).

**[ARCH-Q-1]** The tier floor rule set above is deliberately conservative (few path patterns, high precision). Should the full set of file-path globs from `rn_calculator.py` or the migration scorer be ported into `change_classifier.py` as well, or should those remain separate validator signals feeding the composite score? The concern is duplication vs. coherence: if the composite score already drives tier elevation for migrations, adding a path-based floor for migrations may double-count. Recommend the architect review the overlap boundary.

---

## §2 — Mandated Subagent Compliance Check (#221)

### Background

At HIGH+ steps, risk-assessor is expected to invoke dep-mapper, risk-historian, and prompt-fidelity as subagents. These subagents populate fields that feed the evaluator's compliance checks (dep-mapper findings feed `blocking_findings`, prompt-fidelity findings feed `prompt_fidelity_score`). If the orchestrating session never invokes a subagent, risk-assessor simply omits its findings — no low-confidence finding is recorded, and Phase 1 passes as if the analysis ran clean. The evaluator has no way to distinguish "ran clean" from "never ran."

### Requirements

**REQ-SUB-1.** `risk-assessment.md` must include a `subagents_run:` YAML list field in its header block, alongside the existing `base_sha`, `head_sha`, `files_assessed`, and `blocking_findings` fields. The field lists the subagents that were actually invoked during this assessment run.

Required header format (additions in bold):

```yaml
base_sha: <sha>
head_sha: <sha>
files_assessed: [list of files]
validated_tier: HIGH
**subagents_run: [dep-mapper, risk-historian, prompt-fidelity]**
blocking_findings:
  - ...
```

**REQ-SUB-2.** The subagent names in `subagents_run:` must use the canonical role keys: `dep-mapper`, `risk-historian`, `prompt-fidelity`. An empty list `[]` is valid only when `validated_tier` is LOW or MEDIUM. A missing field is treated as `[]`.

**REQ-SUB-3.** Subagent applicability by tier:

| Validated tier | dep-mapper required | risk-historian required | prompt-fidelity required |
|---|---|---|---|
| LOW | No | No | No |
| MEDIUM | No | No | Yes (if a prompt artifact exists for this step) |
| HIGH | Yes | Yes | Yes (if a prompt artifact exists for this step) |
| CRITICAL | Yes | Yes | Yes (if a prompt artifact exists for this step) |

"Required" means: if the subagent is applicable and its name is absent from `subagents_run:` → **COMPLIANCE FAIL** (condition 12).

**REQ-SUB-4.** The prompt-fidelity requirement is conditioned on whether a prompt artifact exists for this step (i.e., any `Prompt-Artifact:` git trailer in the commit range points to an existing file). If no prompt artifact exists, prompt-fidelity is Not Applicable and need not appear in `subagents_run:`. The evaluator checks the commit range for `Prompt-Artifact:` trailers to determine applicability — it does not trust the absence of prompt-fidelity in `subagents_run:` as a signal that no artifact exists.

**REQ-SUB-5.** The compliance fail message for condition 12 must list: the validated tier, which subagents were required but absent, and the `subagents_run:` value that was found.

**REQ-SUB-6.** A new audit event `subagent-skipped` must be appended to `audit/oversight-log.jsonl` when condition 12 fires. Required fields: `step`, `validated_tier`, `required_subagents`, `reported_subagents`, `missing`, `timestamp`.

**REQ-SUB-7.** `risk-assessor` agent instructions must be updated to require writing `subagents_run:` in the assessment header, listing each subagent actually invoked. This is an update to the risk-assessor agent CORE region.

### Acceptance Criteria

- `risk-assessment.md` with `validated_tier: HIGH` and `subagents_run: [risk-historian, prompt-fidelity]` (dep-mapper absent) → condition 12 fires.
- `risk-assessment.md` with `validated_tier: HIGH` and `subagents_run: [dep-mapper, risk-historian, prompt-fidelity]` → condition 12 does not fire.
- `risk-assessment.md` with `validated_tier: MEDIUM` and `subagents_run: []` and no prompt artifact in the commit range → condition 12 does not fire.
- `risk-assessment.md` with `validated_tier: MEDIUM` and a prompt artifact exists and `subagents_run: []` (prompt-fidelity absent) → condition 12 fires.
- A missing `subagents_run:` field is treated as `[]` and evaluated under the same rules.

**[ARCH-Q-2]** risk-assessor currently has no Agent/Task tool and delegates subagent invocation to the orchestrating session. Should `subagents_run:` be written by risk-assessor itself (trusting that it was the orchestrating session that ran the subagents and risk-assessor names them) or should each subagent write a record to a separate artifact that risk-assessor collects into the header? The latter is stronger (independent attestation) but requires each subagent to write a completion stamp. Recommend architect decide before technical-design.

---

## §3 — Required-Reviewer SET Re-derivation (#261)

### Background

risk-assessor determines which reviewer lanes are warranted (ops, reliability, security, etc.) and records the required set in `risk-assessment.md` or implicitly through the sign-off register. The evaluator checks that each required lane has a sign-off, but it derives "required" from the same artifact it is evaluating. If risk-assessor under-detects a warranted lane (e.g., a new un-timeout'd HTTP call on an existing dependency where the `new-external-dependency` signal did not fire), that lane is never required and nothing catches the gap.

The evaluator already re-derives domains from the diff to invalidate N/A waivers (conditions 9, `change_classifier.py --domains-only`). This section closes the analogous gap in the positive direction: the evaluator re-derives which lanes are *warranted* and checks that warranted lanes are present — not just that present lanes have valid sign-offs.

### Requirements

**REQ-REV-1.** `change_classifier.py` domain detection (the existing `detect_domains` function) already identifies whether the diff touches the `ops` and `reliability` domains. This section defines **mandatory lane triggers**: when a domain is detected as touched by the diff, the corresponding reviewer lane is warranted and must appear in the sign-off register with a non-N/A status.

**REQ-REV-2.** Mandatory lane triggers (deterministic, derived from the diff):

| Domain detected by `change_classifier.py` | Warranted lane |
|---|---|
| `reliability` (outbound HTTP calls, external service calls, DB calls) | `reliability` |
| `ops` (background jobs, async tasks, queue interactions, external integrations) | `ops` |
| `security` (any `.py`, `.html`, `.js`, `.ts` change) | `security` |
| `privacy` (PII paths or field patterns) | `privacy` |
| `ui` or `a11y` (template/component changes) | `ui` and `a11y` |
| `infra` (deployment config changes) | `infra` |

**REQ-REV-3.** The evaluator must compare warranted lanes against the sign-off register. For each warranted lane:
- If the register contains an entry for the lane with `Status: APPROVED` or `Status: CONDITIONAL` → pass.
- If the register contains an entry with `Status: ESCALATED` and a `Human_resolution:` field → pass.
- If the register contains an entry with `Status: N/A` → this is handled by the existing condition 9 (independent N/A re-derivation). The evaluator need not apply condition 13 separately when condition 9 already covers it. Condition 9 takes precedence: if condition 9 fires (N/A waiver invalid), report it under condition 9, not condition 13.
- If the register contains **no entry at all** for the lane → **COMPLIANCE FAIL** (condition 13): the warranted lane is absent from the register entirely.

**REQ-REV-4.** Condition 13 runs **only in the loosening direction**: if the register has an entry for a lane the diff did not warrant (risk-assessor added a lane the classifier did not detect), that entry is accepted as-is. The evaluator can only add lanes; it cannot waive lanes that risk-assessor required.

**REQ-REV-5.** The compliance fail message for condition 13 must list: the warranted lane, the domain evidence that triggered it (file path or added-line match), and the `Status: N/A` or absent-entry finding.

**REQ-REV-6.** A new audit event `warranted-lane-absent` must be appended to `audit/oversight-log.jsonl` when condition 13 fires. Required fields: `step`, `lane`, `domain`, `evidence`, `finding` (`"absent"` or `"na"`), `timestamp`.

**REQ-REV-7.** Projects that opt-out of a lane (e.g., a project with `role_mappings` that does not include `reliability`) are not subject to condition 13 for that lane. The evaluator checks warranted lanes only against the lanes that appear in the step manifest's `role_mappings`. A lane not in `role_mappings` is not a compliance gap — it is a project-level scope decision.

### Acceptance Criteria

- A diff adding `requests.get(url)` with no timeout and no `reliability` entry in the register → condition 13 fires.
- A diff adding `requests.get(url)` with a `reliability` entry of `Status: APPROVED` → condition 13 does not fire.
- A diff adding `requests.get(url)` with a `reliability` entry of `Status: N/A` → condition 9 fires (not condition 13). The evaluator does not double-report.
- A diff with a `reliability` entry added by risk-assessor but no `requests.` calls in the diff → condition 13 does not fire (only in the loosening direction).
- A project whose `role_mappings` omits `reliability` → condition 13 never fires for the `reliability` lane regardless of the diff.

---

## §4 — Modification Detection for Structural Override (#121)

### Background

The structural-override check (contract §2a, `change_classifier.py`, conditions 9–10) detects structural changes that **add** a new artifact: new dependency, new auth check, new route, new user-facing state, new template file. It does not detect a structural change that **modifies existing behavior** without adding a signature: widening an existing permission scope, altering an existing flow's completion criterion, weakening an existing gate condition, changing an existing auth requirement.

The existing limitation is documented (contract §2a "Residual coverage gap") as a known floor-vs-coverage gap relying on honest self-classification plus reviewer detection. This spec narrows that gap for one specific, detectable class: edits to existing structural sections in committed design/spec documents.

### Requirements

**REQ-MOD-1.** `change_classifier.py` must implement a `detect_doc_modifications(name_status, added, removed) -> list[dict]` function that identifies potentially-structural edits to existing sections of committed design and spec documents.

**REQ-MOD-2.** Document scope for modification detection:

| Document pattern | Structural section markers |
|---|---|
| `docs/specs/SPEC-*.md`, `docs/v*/SPEC-*.md` | Any section containing the words: `permission`, `authorization`, `auth`, `approval`, `gate`, `required`, `must`, `shall`, `deny`, `block`, `restrict` |
| `docs/v*/TECHNICAL-DESIGN-*.md`, `TECHNICAL-DESIGN-*.md` | Any section containing the words: `permission`, `authorization`, `auth`, `gate`, `access control`, `security`, `input validation`, `sanitiz` |
| `docs/v*/DESIGN*.md`, `DESIGN.md` | Any section containing the words: `permission`, `authorization`, `auth`, `gate`, `access control` |
| `TELEMETRY-SPEC.md`, `docs/ops/TELEMETRY-SPEC.md` | Any section header |

**REQ-MOD-3.** A "modification to an existing structural section" is defined as: a diff that both removes at least one line (modified, not purely added) from a structural section of a tracked document AND adds at least one line to the same section. A purely additive change to a structural section (lines added, none removed) is an extension, not a modification, and does not trigger condition 14.

**REQ-MOD-4.** `change_classifier.py` must track removed lines (lines beginning with `-` in the unified diff, excluding `---` headers) per file, symmetrically to how it tracks added lines. The `collect_diff` function must return `removed_lines_by_file` alongside `added_lines_by_file`.

**REQ-MOD-5.** `change_classifier.py` must accept a `--modifications-only` flag that emits `{"doc_modifications": [{"file": "...", "section": "...", "evidence": "..."}]}` to stdout.

**REQ-MOD-6.** The oversight evaluator, during Phase 1 compliance check, must:
1. Run `change_classifier.py --modifications-only --base <base_sha> --head <head_sha>`.
2. For each detected `doc_modification`, check whether a covering human-authorization artifact exists: `.claudetmp/oversight/step{N}-human-authorization.md` or a domain-specific structural auth file (`.claudetmp/oversight/step{N}-spec-structural-auth.md`).
3. If any modification is not covered → **COMPLIANCE FAIL** (condition 14).

**REQ-MOD-7.** Condition 14 runs only in the loosening direction: if the change was already classified `structural` by the authoring agent AND a human-authorization artifact exists, no check is performed.

**REQ-MOD-8.** The compliance fail message for condition 14 must list: the document file, the section title or nearest header, and the evidence (removed line and added line that characterize the modification).

**REQ-MOD-9.** A new audit event `doc-modification-uncovered` must be appended to `audit/oversight-log.jsonl` when condition 14 fires. Required fields: `step`, `file`, `section`, `evidence`, `timestamp`.

### Acceptance Criteria

- A diff that changes an existing `## Authorization` section in `TECHNICAL-DESIGN.md` by removing one permission requirement and adding a different one → condition 14 fires.
- A diff that adds a new `## Authorization` section (no lines removed) → condition 14 does not fire (purely additive; condition 10 / new-permission-or-auth-state handles this if applicable).
- A diff that changes `TELEMETRY-SPEC.md` by replacing an existing metric definition → condition 14 fires.
- A diff covered by `step{N}-human-authorization.md` → condition 14 does not fire.
- Changes to documents outside the tracked set (e.g., `README.md`, `DECISIONS.md`) → condition 14 does not fire.

**[ARCH-Q-3]** The "structural section" detection based on keyword presence in section content is heuristic and will produce false positives (a spec section that mentions "auth" in an example will be flagged). The alternative is to enumerate specific section headers (e.g., `## Authentication`, `## Permissions`) as the structural surface rather than scanning content. Recommend architect decide: keyword scan vs. header enumeration, and whether the false-positive rate is acceptable given that a false positive only sends a benign change to a human.

---

## §5 — Spec-Change Laundering Prevention (#205)

### Background

pm-agent (and ux-designer) can label a mid-build spec change `Additive` by claiming it was "always implied by the approved spec." The coder then implements the newly-documented behavior as spec-compliant. New user-visible behavior — new messages, new states, new policy outcomes, new user obligations — can enter the product without hitting the human gate if the classification is accepted at face value.

The evaluator cannot reliably determine from the diff alone whether a behavior is "new user-visible" vs. "always implied." This is partly semantic (~MEDIUM-HIGH difficulty). The spec adopts Option A from the issue: require the authoring agent to record what changed, and have the evaluator check that a human authorization artifact exists when the record claims new user-visible behavior or new obligations were introduced.

### Requirements

**REQ-SPEC-1.** When pm-agent (or ux-designer) makes an additive or structural classification on a spec/design change, it must write a `behavior-delta:` field to its sign-off register entry under the `process` role. The field lists each new or changed behavior in the diff.

Required register entry format (additions in bold):

```markdown
## process | SPEC-{feature}.md | {ISO-8601 datetime}
Status: APPROVED
Agent: pm-agent
Artifact: docs/specs/SPEC-{feature}.md
Iterations: 1
Change_classification: additive | structural | clarifying
**Behavior_delta:**
**  - [new | modified | removed] {one-line description of the user-visible behavior or obligation}**
**  - [new | modified | removed] {next behavior}**
Notes: ...
```

**REQ-SPEC-2.** `Behavior_delta:` is required whenever the pm-agent sign-off register entry covers a change to a committed spec or design document (any file matching `docs/specs/*.md`, `docs/v*/*.md`, `TELEMETRY-SPEC.md`, `UX-DESIGN-READINESS.md`). For changes that are purely clarifying (no behavior change), the field may contain a single line: `- [clarifying] no behavior change`.

**REQ-SPEC-3.** The oversight evaluator, during Phase 1 compliance check, must:
1. Read the `process` sign-off register entry.
2. If `Behavior_delta:` is absent and the step's diff includes changes to any tracked spec/design document → **COMPLIANCE FAIL** (condition 15, missing behavior delta).
3. If `Behavior_delta:` contains any `[new]` or `[modified]` entry that describes a user-visible behavior (not purely clarifying) AND `Change_classification:` is `additive` → the evaluator checks whether a human-authorization artifact exists (`.claudetmp/oversight/step{N}-human-authorization.md` or `.claudetmp/oversight/step{N}-spec-structural-auth.md`). If no authorization artifact exists → **COMPLIANCE FAIL** (condition 15, new behavior without human gate).

**REQ-SPEC-4.** "User-visible behavior" for the purposes of condition 15 means any of:
- A new user-facing message, notification, or email
- A new user obligation or consent requirement
- A new policy outcome (approval, denial, escalation state)
- A new flow step a user must complete
- A new permission or access restriction applied to a user

Clarifying changes (restating existing behavior with precision, fixing a typo, making an implicit requirement explicit without extending scope) are exempt. pm-agent is the classifier; condition 15 enforces that a human authorization artifact accompanies any claimed-additive change where behavior-delta says `[new]` or `[modified]`.

**REQ-SPEC-5.** The compliance fail message for condition 15 must distinguish the two failure modes: (a) `Behavior_delta:` absent entirely, (b) new/modified user-visible behaviors without a human authorization artifact. For case (b), list the specific `[new]` or `[modified]` delta entries.

**REQ-SPEC-6.** A new audit event `spec-change-behavior-delta` must be appended to `audit/oversight-log.jsonl` when condition 15 fires. Required fields: `step`, `failure_mode` (`"missing_field"` or `"new_behavior_unauthed"`), `file`, `delta_entries` (array), `timestamp`.

**REQ-SPEC-7.** pm-agent and ux-designer agent instructions (CORE regions) must be updated to require writing `Behavior_delta:` and `Change_classification:` in the `process` sign-off register entry whenever they change a tracked spec/design document.

### Acceptance Criteria

- pm-agent changes `docs/specs/SPEC-booking.md` to add a new denial message, classifies as `Additive`, `Behavior_delta: - [new] denial email sent to user when application rejected`, no human authorization artifact → condition 15 fires (new behavior unauthed).
- Same change with `step{N}-human-authorization.md` present → condition 15 does not fire.
- pm-agent changes a spec to fix a typo in an example, `Behavior_delta: - [clarifying] no behavior change`, `Change_classification: clarifying` → condition 15 does not fire.
- pm-agent changes a spec but `Behavior_delta:` is absent entirely → condition 15 fires (missing field).
- A step where no tracked spec/design doc is in the diff → condition 15 is not checked.

**[ARCH-Q-4]** The spec allows pm-agent to self-classify `[clarifying]` and bypass the human gate. An agent that classifies all of its changes as `[clarifying]` can still launder them past. The evaluator cannot reliably detect this without semantic analysis. Should condition 15 be extended to: (a) always require human authorization for ANY pm-agent spec change in an unattended run, or (b) require a second agent (architect?) to co-sign the `Change_classification: clarifying` on spec changes during unattended builds? Option B would close the residual gap without requiring human involvement for genuine clarifications. Escalate to human if Option A or B is preferred.

---

## §6 — Step-Head Timing Correction (#220)

### Background

The `step-head` event in `audit/oversight-log.jsonl` is currently written by the oversight evaluator at Phase 7 (pre-PR evaluation) with `head_sha = branch HEAD at evaluation time`. But the pipeline continues through Phase 9 (panel) and Phase 10 (human gate), where panel-fix commits may land on the branch. These commits are made after `step-head` was written. The next step uses `grep step-head | tail -1` to find its `base_sha`. Therefore, panel-fix commits made during step N's human gate are attributed to step N+1's diff range — never risk-assessed under step N (its PR already merged) and mis-scoping step N+1.

### Requirements

**REQ-HEAD-1.** The `step-head` event in `audit/oversight-log.jsonl` must be written **at Phase 11 (post-merge)**, not at Phase 7. It must be written after the PR is merged and must use the actual merged commit SHA, not the pre-PR branch head.

**REQ-HEAD-2.** The `step-head` event schema must include the following fields:

```json
{
  "event": "step-head",
  "step": N,
  "base_sha": "<SHA that was this step's base — previous step's head_sha>",
  "head_sha": "<actual merged commit SHA>",
  "merged_at": "<ISO-8601 timestamp of merge>",
  "pr_number": "<PR number if applicable>",
  "timestamp": "<ISO-8601 timestamp of this log entry>"
}
```

`base_sha` and `head_sha` together anchor the definitive commit range for the completed step. `merged_at` distinguishes when the merge happened from when this log entry was written.

**REQ-HEAD-3.** The agent or script responsible for writing `step-head` post-merge must be `oversight-orchestrator` (which currently manages the post-evaluation/pre-PR flow). The oversight-orchestrator must write the `step-head` event as part of the `16. MERGE → AUDIT` phase, after confirming the PR merged.

**[ARCH-Q-5]** The oversight-orchestrator currently operates pre-PR. Writing `step-head` post-merge requires the orchestrator (or a new post-merge script) to have access to the merge commit SHA. In the unattended worker model, the worker machine merges the PR and then needs to write the `step-head` event. Recommend architect decide: (a) oversight-orchestrator is extended to run post-merge as a cleanup step, (b) a new `post-merge-audit.sh` script writes the event, or (c) the overseer agent writes it as part of merge execution. This is a pipeline orchestration question, not a product requirement.

**REQ-HEAD-4.** The oversight evaluator, when computing its own `base_sha` for the current step, must read `head_sha` from the previous step's `step-head` event in `audit/oversight-log.jsonl`. This is the existing behavior. The change is upstream: the event that populates `head_sha` must now carry the post-merge SHA rather than the pre-PR branch head.

**REQ-HEAD-5.** During the transition period (steps that completed before this spec was implemented may have pre-PR `step-head` entries), the evaluator must tolerate older entries. No compliance check is added for historical entries. New entries must conform to the §6 schema.

**REQ-HEAD-6.** The sign-off register header (`base_sha` / `head_sha`) continues to be written by the evaluator at Phase 7 for its own Phase 1 compliance window. These register-header SHAs cover the evaluator's assessment scope. The `step-head` audit event is separate: it anchors the next step's base after the full pipeline (including panel-fix commits) completes. Both exist for different purposes and are not redundant.

### Acceptance Criteria

- After PR merge, `audit/oversight-log.jsonl` contains a `step-head` event for step N with `head_sha` equal to the actual merged commit SHA (which may differ from the pre-PR branch head if panel-fix commits were pushed).
- The oversight evaluator for step N+1 reads the step N `step-head` entry and uses its `head_sha` as `base_sha` for step N+1's assessment range.
- A `step-head` event written before the spec's effective date (missing `base_sha` or `merged_at`) does not cause the evaluator to fail — it uses the available `head_sha` and logs a warning.

---

## Compliance-Condition Summary

This spec adds six new Phase 1 compliance conditions (11–16) to `contract/OVERSIGHT-CONTRACT.md` §7:

| Condition | What it checks | Failure direction | Source |
|---|---|---|---|
| **11** | Re-derived tier floor vs. self-reported validated tier | Loosening only | #94 |
| **12** | Mandated subagents (dep-mapper, risk-historian, prompt-fidelity) present in `subagents_run:` | Loosening only | #221 |
| **13** | Warranted reviewer lanes present in sign-off register (via domain re-derivation) | Loosening only | #261 |
| **14** | Modifications to existing structural sections in design/spec docs covered by human authorization | Loosening only | #121 |
| **15** | pm-agent `Behavior_delta:` present when spec changes occur; new behaviors require human auth | Loosening only | #205 |
| **16** | `step-head` event written post-merge with actual merged SHA (timing, not a compliance fail for existing steps) | N/A (timing correction) | #220 |

All conditions 11–15 enforce the same anti-gaming pattern as existing conditions 9–10: independently re-derived from the diff, only in the loosening direction, escalate to human on failure.

Condition 16 is a timing correction with no new compliance gate. It changes when and how the `step-head` event is written, which indirectly affects the correctness of condition 7b (risk-assessment scope check) for future steps.

---

## Artifact Changes Required

The following existing artifacts must be updated by technical-design and implementation:

| Artifact | Change |
|---|---|
| `scripts/oversight/change_classifier.py` | Add `detect_tier_floor()`, `detect_doc_modifications()`, track removed lines in `collect_diff()`, add `--tier-floor` and `--modifications-only` CLI flags |
| `contract/OVERSIGHT-CONTRACT.md` | Add conditions 11–16 to §7; add `subagents_run:` to §7b; add `Behavior_delta:` and `Change_classification:` to §3 sign-off schema; add new audit events to §6a; update `step-head` timing in §6a |
| `.claude/agents/oversight-evaluator.md` | Add Phase 1 checks for conditions 11–15; update step-head timing notes |
| `.claude/agents/oversight-orchestrator.md` | Add post-merge step-head event write responsibility |
| `.claude/agents/risk-assessor.md` | Add `subagents_run:` field requirement to risk-assessment.md header |
| `.claude/agents/pm-agent.md` | Add `Behavior_delta:` and `Change_classification:` requirement to process sign-off entries |
| `.claude/agents/ux-designer.md` | Same `Behavior_delta:` and `Change_classification:` requirement |
| `audit/oversight-log.jsonl` event catalog | Add: `tier-floor-mismatch`, `subagent-skipped`, `warranted-lane-absent`, `doc-modification-uncovered`, `spec-change-behavior-delta` |

---

## Open Questions for the Architect

| ID | Question | Blocking? |
|---|---|---|
| ARCH-Q-1 | Tier floor rule set overlap with composite validators (migrations, RN score) — port or keep separate? | No (default: keep separate, re-evaluate after first implementation) |
| ARCH-Q-2 | Subagent completion attestation model — risk-assessor self-reports vs. each subagent writes a stamp | Yes for §2 implementation — decide before technical-design |
| ARCH-Q-3 | Modification detection: keyword-scan vs. header-enumeration for structural section identification | No (default: header-enumeration, lower false-positive rate) |
| ARCH-Q-4 | Residual spec-change laundering via `[clarifying]` self-classification — require architect co-sign or human auth for all additive spec changes in unattended mode? | No (default: ship as-is, file a follow-on issue for the residual gap) |
| ARCH-Q-5 | Post-merge step-head writer — extend oversight-orchestrator, new post-merge-audit.sh, or overseer agent? | Yes for §6 implementation — decide before technical-design |
