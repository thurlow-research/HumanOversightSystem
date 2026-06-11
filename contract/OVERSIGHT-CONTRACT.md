# Oversight Contract v1

This document defines what any compliant agent team must produce for the Human Oversight System (HOS) to evaluate it. The HOS oversight agents (evaluator, orchestrator, risk-assessor) program against this contract, not against any specific team's agent names or file paths.

---

## 1. Filesystem protocol

All files live relative to the project root. The HOS reads these locations; compliant teams must write to them.

```
.claudetmp/
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
    step{N}-evaluation-{ts}.md   ← oversight-evaluator output
    step{N}-handoff.md           ← context for external panel
  second-review/
    step{N}-{ts}.md              ← second review output (run_second_review.sh)
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

Every agent that approves or escalates a build step writes one entry to `.claudetmp/signoffs/step{N}-register.md`:

```markdown
## {role} | {artifact} | {ISO-8601 datetime}
Status: APPROVED | ESCALATED | CONDITIONAL
Agent: {agent-name}
Artifact: {what was reviewed — file paths or description}
Iterations: {N}
Critical_findings_resolved: true | false | N/A
Notes: {one paragraph: what was found and how resolved. Empty if clean.}
```

**Required fields:** Status, Agent, Artifact, Iterations.

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
| `risk-assessment` | Risk tier validation (never lowers) |

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

Compliant agents create GitHub issues at defined trigger points. The HOS evaluator checks for issue existence as part of its compliance evaluation.

| Trigger | Label(s) | Who creates |
|---|---|---|
| Spec silent/ambiguous → human escalation | `spec-gap` | pm-agent or equivalent |
| Design loop → 5-round escalation | `design-concern` | architect or equivalent |
| Unit test loop exhausted | `test-resistance` | unit-test agent |
| System test fails after fix iterations | `bug` | system-test agent |
| Security finding (crit/high) resolved pre-merge | `security-finding`, `resolved-in-review` | security reviewer |
| Privacy finding (blocking) resolved pre-merge | `privacy-finding`, `resolved-in-review` | privacy reviewer |
| Second review finds crit/high | `second-review-finding` | run_second_review.sh |
| Panel finds something internal team missed | `escaped-defect` | panel arbiter |
| Red-team finds exploitable issue | `red-team-finding` | run_red_team.sh |

---

## 7. Compliance check

The `oversight-evaluator` agent checks compliance before quality evaluation. Compliance fails if:

1. Sign-off register is missing or has no entries for a required role
2. Any required role shows `Status: ESCALATED` without human resolution on record
3. `test-unit` declaration is missing `Thresholds_met: true`
4. `test-system` declaration is missing when `system_test_applicable: true` for this step
5. `process` sign-off is missing when `system_test_applicable: true` (PM must sign off on test plan)
6. `human_gate_required: true` and no human authorization on record (CRITICAL steps)

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
