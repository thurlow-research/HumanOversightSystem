# Oversight Contract v1

This document defines what any compliant agent team must produce for the Human Oversight System (HOS) to evaluate it. The HOS oversight agents (evaluator, orchestrator, risk-assessor) program against this contract, not against any specific team's agent names or file paths.

---

## 1. Filesystem protocol

All files live relative to the project root. The HOS reads these locations; compliant teams must write to them.

```
audit/                               ← COMMITTED to project repo (not gitignored)
  oversight-log.jsonl               ← append-only audit trail; one JSON event per line
  step-{N}-summary.md               ← human-readable per-step report (generated at merge)
  escaped-defects.md                ← consolidated escaped-defect record

.claudetmp/                          ← ephemeral working state (gitignored)
  signoffs/
    step{N}-register.md          ← sign-off register for build step N
  reviews/
    {agent-role}-{step}-{ts}.md  ← iteration state per reviewer per step
  tests/
    unit-test-{step}-{ts}.md     ← unit test iteration state
    system-test-{step}-{ts}.md   ← system test iteration state
  design/
    architect-{step}-{ts}.md     ← architect design critique state
    technical-design-{step}-{ts}.md
  oversight/
    validators/
      summary.json               ← composite risk score (written by run_validators.sh)
      {dimension}.json           ← per-validator output
      risk-assessment.md         ← validated risk tier + inspection brief (written by
                                    risk-assessor agent, read by oversight-evaluator)
    step{N}-evaluation-{ts}.md   ← oversight-evaluator output
    step{N}-panel-context.md     ← external panel context (structural risk signals ONLY —
                                    no internal findings, no resolved vulnerabilities)
    step{N}-handoff.md           ← human/PR context (full picture: internal review
                                    summary, second review findings, human notes)
    step{N}-human-authorization.md ← CRITICAL steps only: human creates this file
                                    BEFORE running oversight-evaluator to authorize
                                    proceeding. Evaluator reads it during Phase 1.
                                    Required content: date + decision text.
    human-tier-override.md       ← created by human to authorize lowering a risk tier
                                    below the coder's declaration. Risk-assessor reads
                                    this before accepting a lower tier. Without it the
                                    declared tier is a hard floor.
  notifications/
    step{N}/
      {from}-to-{to}-{ts}.md     ← durable inter-agent notification artifact.
                                    Required fields:
                                      Step: N
                                      From: {agent-name}
                                      To: {agent-name}
                                      Changed: [list of files or spec sections changed]
                                      Reason: [why the receiving agent needs to act]
                                      Blocking: yes | no
                                      Required action: [what the receiving agent must do]
                                      Acknowledged: [left blank; receiving agent fills in]
                                    Use when: one agent changes a shared artifact
                                    (design pack, telemetry spec) that another agent
                                    must re-review. Prevents notifications from being
                                    lost in chat context.
  second-review/
    step{N}-{ts}.md              ← second review output (run_second_review.sh).
                                    Always written — for actual runs includes a
                                    machine-readable header then reviewer JSON blocks;
                                    contains verdict: skipped when below thresholds or
                                    when no diff content. Top-level fields:
                                      verdict: approve|request_changes|error|skipped
                                      highest_severity: critical|high|medium|low|none
                                      unresolved_findings: N
  red-team/
    checkpoint-{milestone}-{ts}.md ← red-team report
```

---

## 2. Self-flag format (authoring agents)

Any agent that produces code at MEDIUM risk or above must emit:

```
RISK: LOW | MEDIUM | HIGH | CRITICAL
CONFIDENCE: [0-100]% — [one sentence: what you're confident about and what you're not]
```

For destructive operations (migrations, auth changes, schema drops):
```
BLAST RADIUS: [what breaks if this is wrong]
Rollback: [how to undo]
```

For MEDIUM+ changes:
```
## Human Review Required
**[file:line]** — [why this needs human eyes, not just what it is]
```

Git commit trailers (every AI-generated commit):
```
Prompt-Artifact: [path to technical design section or prompts/ file]
AI-Model: [model id]
AI-Risk: [LOW|MEDIUM|HIGH|CRITICAL]
```

---

## 3. Sign-off register schema

### Register header (commit range)

The first lines of `.claudetmp/signoffs/step{N}-register.md` record the commit range the step covers, so the oversight-evaluator knows exactly which commits to check (e.g. for prompt-artifact compliance) without guessing:

```markdown
# Sign-off Register — Step {N}
base_sha: {SHA the step started from — previous step's head_sha, or merge-base with the default branch}
head_sha: {current HEAD when the evaluator runs}
```

The oversight-evaluator writes/updates this header when it runs. `base_sha` is taken from the previous step's recorded `head_sha` (via the audit log) or, for the first step, the merge-base of the current branch with the default branch. The definitive commit range for the step is `git log base_sha..head_sha`. This range also feeds the reactive re-run mechanism so each step's commits are unambiguous.

### Sign-off entries

Every agent that approves or escalates a build step writes one entry below the header:

```markdown
## {role} | {artifact} | {ISO-8601 datetime}
Status: APPROVED | ESCALATED | CONDITIONAL | N/A
Agent: {agent-name}
Artifact: {what was reviewed — file paths or description}
Iterations: {N}
Critical_findings_resolved: true | false | N/A
Human_resolution: {ISO date} — {decision text}   ← required when Status: ESCALATED
Notes: {one paragraph: what was found and how resolved. Empty if clean.}
```

**Required fields:** Status, Agent, Artifact, Iterations.

**`Critical_findings_resolved`** is required for `security` and `privacy` roles; optional (N/A) for all others. When `true`, it signals that the evaluator should add the finding to the conditional-items list for human review before merge — it is a Phase 2 quality signal, not a Phase 1 compliance check.

**`Human_resolution`** is required only when `Status: ESCALATED`. Format: `{ISO date} — {decision text}`. The oversight-evaluator reads this field to confirm human resolution is on record before clearing the compliance check. Example: `Human_resolution: 2026-06-11 — Reviewed 5-round loop; architect decision is sound, proceed`.

**`Status: CONDITIONAL`** passes Phase 1 compliance but automatically causes the oversight-evaluator to recommend at least `CONDITIONAL_PROCEED` — a human must verify the conditional item before merge.

**`Status: N/A`** passes Phase 1 compliance and means the role had no applicable changes in this diff (the reviewer's domain was not touched). Written by `post-change-sweep` on behalf of skipped reviewers (with a `Reason:` field), or by `code-reviewer` itself when there is no application code to review. An explicit N/A entry distinguishes "considered, not applicable" from a missing entry — see `research/findings/explicit-na-audit-entries.md`. Each N/A entry corresponds to a `gate-na` audit event (§6a).

**Test agents additionally write the §4 test declaration fields** (Coverage_pct, Mutant_score_pct, Thresholds_met, All_passing) inline in their register entry. The oversight-evaluator reads these fields directly from the register; §4 defines the schema those fields must follow.

**Roles** (the HOS checks for these roles, not agent names):

| Role key | Meaning |
|---|---|
| `code-review` | Correctness, design adherence, idioms |
| `security` | Security vulnerabilities, OWASP |
| `privacy` | PII handling, GDPR compliance |
| `test-unit` | Unit test coverage + mutant score |
| `test-system` | Functional spec conformance |
| `process` | PM sign-off on test plan or spec section |
| `infra` | Infrastructure / deployment config |
| `ui` | Design system / template conformance |
| `a11y` | Accessibility (WCAG AA) |
| `ops` | Observability / telemetry spec conformance (optional — projects with ops complexity) |
| `reliability` | Resilience review — timeouts, retry, graceful degradation (optional — projects with external connections) |
| `risk-assessment` | Risk tier validation — note: risk-assessor writes to `.claudetmp/oversight/validators/risk-assessment.md`, NOT to the sign-off register. Do not include `risk-assessment` in `required_signoffs` — it is a validator artifact, not a sign-off role. |

**Gate suspension (brownfield remediation):**
A project may temporarily suspend specific gates/roles during brownfield onboarding by creating `contract/gate-suspension.md` (see `contract/gate-suspension.template.md`). Suspended gates exit 0 instead of blocking; suspended sign-off roles are treated as WAIVED by the oversight-evaluator. The suspension file:
- Must be created by a human (agents may not create or modify it)
- Must include `Authorized by:` and `Date:` fields
- Lists suspended gates as `SUSPENDED: {role-name}` lines
- Is committed to git — the suspension is auditable

Gate script names for suspension: `lint`, `security`, `secrets`, `types`, `template-refs`, `portability`, `django`
Sign-off role names match `required_signoffs` in `step-manifest.yaml`

---

## 4. Test declaration schema

Test agents append a declaration to the sign-off register:

```markdown
## test-unit | test-results | {datetime}
Status: APPROVED | ESCALATED
Agent: unit-test
Coverage_pct: 83
Mutant_score_pct: 77
Thresholds_met: true
Surviving_equivalents: 2
Equivalents_documented: true
Iterations: 3
Notes: ...
```

```markdown
## test-system | test-results | {datetime}
Status: APPROVED | ESCALATED
Agent: system-test
Spec_flows_covered: [list of §11 flows covered]
All_passing: true
Iterations: 2
Notes: ...
```

---

## 5. Step manifest schema

Each project provides a step manifest at `contract/step-manifest.yaml` (copy from `contract/step-manifest.template.yaml`). The oversight-evaluator reads this to know what is required for each step.

```yaml
contract_version: "1"
project: my-project
role_mappings:
  code-review:    code-reviewer      # agent name → role key
  security:       security-reviewer
  privacy:        privacy-reviewer
  test-unit:      unit-test
  test-system:    system-test
  process:        pm-agent
  infra:          infra-reviewer

steps:
  - id: 1
    name: "Scaffold"
    risk_tier: LOW
    required_signoffs: [code-review, infra]
    system_test_applicable: false

  - id: 3
    name: "Auth + TOTP"
    risk_tier: CRITICAL
    required_signoffs: [code-review, security, privacy, test-unit, test-system, process]
    system_test_applicable: true
    human_gate_required: true          # CRITICAL: human must authorize before PR opens
```

---

## 6. Issue creation rules

Compliant agents create GitHub issues at defined trigger points. Issue creation is enforced by agent instructions and is auditable via `gh issue list`. The evaluator does NOT query GitHub to verify issue existence — it trusts the sign-off register which agents update after creating issues. The issue trail is a research and audit artifact, not a blocking compliance check.

**AI issue title convention:** Every issue created by an AI agent must begin with `[AI: {agent-name}]`:

```
[AI: {agent-name}] {issue-type}: {description}
```

**AI issue footer convention:** Every AI-created issue must include this footer at the end of the body:

```markdown
---
*🤖 Created by `{agent-name}` | Step: {N or "session"} | Branch: `{branch}` | {YYYY-MM-DD}*
```

Both requirements apply to all projects that install this framework.

| Trigger | Label(s) | Who creates | Example title prefix |
|---|---|---|---|
| Spec silent/ambiguous → human escalation | `spec-gap` | pm-agent or equivalent | `[AI: spec-red-team] spec-gap:` |
| Design loop → 5-round escalation | `design-concern` | architect or equivalent | `[AI: architect] design-concern:` |
| Unit test loop exhausted | `test-resistance` | unit-test agent | `[AI: unit-test] test-resistance:` |
| System test fails after fix iterations | `bug` | system-test agent | `[AI: system-test] bug:` |
| Security finding (crit/high) resolved pre-merge | `security-finding`, `resolved-in-review` | security reviewer | `[AI: security-reviewer] security-finding:` |
| Privacy finding (blocking) resolved pre-merge | `privacy-finding`, `resolved-in-review` | privacy reviewer | `[AI: privacy-reviewer] privacy-finding:` |
| Second review finds crit/high | `second-review-finding` | run_second_review.sh | `[AI: second-review/agy] second-review-finding:` |
| Panel finds something internal team missed | `escaped-defect` | panel arbiter | `[AI: panel-arbiter] escaped-defect:` |
| Red-team finds exploitable issue | `red-team-finding` | run_red_team.sh | `[AI: red-team/codex] red-team-finding:` |
| Startup artifact missing a case | `startup-artifact-gap` | any downstream agent | `[AI: ui-reviewer] startup-artifact-gap:` |

---

## 6a. Audit-log event catalog

`audit/oversight-log.jsonl` is an append-only log, one JSON object per line, each with an `"event"` field and an ISO-8601 `"timestamp"`. The catalog below is canonical — every line written to the log uses one of these event types. The log distinguishes the states that an absent register entry otherwise conflates (ran-and-clean vs. never-ran vs. intentionally-skipped vs. failed).

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `step-head` | Records a step's HEAD SHA so the next step finds its base | oversight-evaluator | `step`, `head_sha` |
| `validator-failure` | A validator/gate exhausted retries (timeout or crash) | run_with_retry.sh | `validator`, `required`, `attempts`, `final_outcome` (failed\|skipped), `last_error` |
| `gate-suspended` | A required role/gate was waived because it is suspended | oversight-evaluator | `gate`, `step`, `authorized_by`, `suspension_file` |
| `gate-na` | An orchestrator determined a reviewer is not applicable to the diff | post-change-sweep | `gate`, `step`, `reason`, `determined_by` |
| `gate-rerun` | A step was re-run because one of its inputs changed | reactive re-run mechanism | `gate`, `step`, `trigger`, `previous_run` |
| `gate-auto-reenabled` | A suspended gate was auto-removed after consistent passes | suspension auto-removal | `gate`, `step`, `consecutive_passes` |
| `suspension-census` | Per-run count of active suspensions (health metric) | oversight-evaluator | `active_suspensions`, `suspended_gates` |
| `sampling-audit` | A statistical sampling red-team run completed | run_redteam_sample.sh | `pool_size`, `sample_size`, `tier_escapes`, `escape_rate_pct` |

**Why this matters (ratchet + audit completeness):** the three "non-APPROVED" states — `gate-suspended` (human chose to skip), `gate-na` (not applicable), `validator-failure` (tried and failed) — are genuinely different and currently invisible if not logged. A complete audit trail records all of them. Note the ratchet: `gate-suspended` requires a human (`authorized_by`); `gate-auto-reenabled` does not (re-enabling is the safe direction). See `research/findings/ratchet-principle.md` and `research/findings/explicit-na-audit-entries.md`.

---

## 7. Compliance check

The `oversight-evaluator` agent checks compliance before quality evaluation. Compliance fails if:

1. Sign-off register is missing or has no entries for a required role
2. Any required role entry is missing required §3 fields (`Status`, `Agent`, `Artifact`, `Iterations`)
3. Any required role shows `Status: ESCALATED` without a `Human_resolution:` field in that entry
4. `test-unit` declaration is missing `Thresholds_met: true`
5. `test-system` declaration is missing when `system_test_applicable: true`
6. `process` sign-off missing when `system_test_applicable: true` (PM must sign off on test plan)
7. `human_gate_required: true` (CRITICAL steps): `.claudetmp/oversight/step{N}-human-authorization.md` must exist and be non-empty BEFORE the evaluator runs; if missing, compliance fails immediately
8. MEDIUM+ commits missing `Prompt-Artifact:` git trailer → **COMPLIANCE WARN** (not hard fail — add to conditional items; human confirms intent was captured another way). If the trailer references a path that does not exist → **COMPLIANCE FAIL**

**MEDIUM fail-closed (second review):** when composite score ≥ `OVERSIGHT_AGY_THRESHOLD` (default 0.30) but below `OVERSIGHT_CODEX_THRESHOLD` (default 0.55) and `agy` is unavailable, `run_second_review.sh` exits non-zero. This is intentional fail-closed behavior — a MEDIUM+ step cannot proceed without cross-vendor review. If codex is also unavailable at HIGH+, the script also exits non-zero. Document this in project runbooks.

Compliance failure → `ESCALATE` regardless of content evaluation.

---

## 8. Extension points

The contract is versioned (`contract_version`). Extensions:
- Add new role keys (backward compatible — old teams just won't have them, evaluator notes missing)
- Add new required sign-offs to the step manifest
- Add new issue labels (issue_query.py queries by label)
- Add new validator dimensions (uniform output schema, register in run_validators.sh)

Breaking changes (increment contract version):
- Changing the sign-off register file path or format
- Changing required field names in the schema
- Changing the filesystem protocol locations
