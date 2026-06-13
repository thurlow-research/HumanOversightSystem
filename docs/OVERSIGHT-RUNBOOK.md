# [your project] — Oversight Pipeline Runbook

Complete guide to running the Human Oversight System for each build step.
Reference `contract/step-manifest.yaml` for per-step risk tiers and required sign-offs.

---

## Prerequisites

```bash
# Verify CLIs are authenticated
agy -p "hello"              # should respond
codex exec "hello"          # should respond
gh auth status              # should show authenticated
scancode --version          # should show version (Level 1 IP detection)

# Verify validators are ready
cd ~/[your project]
bash scripts/oversight/run_validators.sh parking/admin.py 2>/dev/null \
  && cat .claudetmp/oversight/validators/summary.json | python3 -m json.tool | head -5
```

---

## Brownfield Onboarding — Applying HOS to an Existing Codebase

> **For recommended gate re-enable order and strategic guidance**, see [`docs/BROWNFIELD-ONBOARDING.md`](BROWNFIELD-ONBOARDING.md). This section covers the mechanical steps; that document covers why and in what order.

When adding HOS gates to a codebase that was not built with them, everything will fail at once. The gate suspension mechanism lets you accept the existing technical debt, then eliminate it domain by domain while preventing new debt from accumulating in domains you've already cleaned up.

**Process:**

**1. Create the suspension manifest** (human only — agents may not create this):
```bash
cp contract/gate-suspension.template.md contract/gate-suspension.md
# Edit the file: fill in Authorized by, Date, Reason
# Add one SUSPENDED: line per gate/reviewer you're suspending
git add contract/gate-suspension.md
git commit -m "chore: add gate suspension for brownfield HOS onboarding"
```

**2. Verify gates are suspended:**
```bash
bash scripts/oversight/gates/lint_check.sh --all
# Should print: ⏸ GATE SUSPENDED: lint
```

**3. Work reviewer by reviewer.** Choose a domain (e.g., lint), fix all existing issues in that domain, verify the gate passes clean, then re-enable it:
```bash
# Fix all lint issues, then verify:
bash scripts/oversight/gates/lint_check.sh --all
# → GATE PASS: ...

# Re-enable: remove the SUSPENDED: lint line from contract/gate-suspension.md
# Add an entry to the Re-enable log, then commit:
git add contract/gate-suspension.md
git commit -m "chore: re-enable lint gate — all existing lint errors resolved"
```

**4. Repeat for each domain.** The invariant: once re-enabled, a gate stays on. Do not re-suspend a gate that has already been re-enabled — fix the regression instead.

**Gate name reference:**

| Gate script | Suspension name | Sign-off role name |
|---|---|---|
| `lint_check.sh` | `lint` | — |
| `type_check.sh` | `types` | — |
| `secret_scan.sh` | `secrets` | — |
| `security_scan.sh` | `security` | `security` |
| `template_refs_check.sh` | `template-refs` | — |
| `portability_check.sh` | `portability` | — |
| `django_check.sh` | `django` | — |
| security-reviewer sign-off | `security` | `security` |
| privacy-reviewer sign-off | — | `privacy` |
| ui-reviewer sign-off | — | `ui` |
| a11y-reviewer sign-off | — | `a11y` |
| infra-reviewer sign-off | — | `infra` |
| ops-reviewer sign-off | — | `ops` |
| reliability-reviewer sign-off | — | `reliability` |
| unit-test sign-off | — | `test-unit` |
| system-test sign-off | — | `test-system` |

**5. Delete the suspension file when done:**
```bash
rm contract/gate-suspension.md
git add -u && git commit -m "chore: remove gate suspension — all gates active"
```

---

## Project Start Sequence

Run this once before the first build step begins. These agents produce the documents that every subsequent agent reads.

```
1. pm-agent          → docs/pm/CONFIRMED-REQUIREMENTS.md
2. ux-designer        → docs/design/UX-DESIGN-READINESS.md  (pm-agent validates)
3. architect          → docs/architecture/ADR-001-pilot.md
4. ops-designer*      → docs/ops/TELEMETRY-SPEC.md  (architect validates)  *if ops configured
5. technical-design   → docs/design/TECHNICAL-DESIGN.md  (iterated with architect)
```

**Invoke in order:**

```bash
# 1. PM agent — spec review and human Q&A
# "Invoke pm-agent for initial spec review"
# Wait for pm-agent to complete its Q&A with you and write CONFIRMED-REQUIREMENTS.md

# 2. UX designer — design pack audit against full spec
# "Invoke ux-designer for initial design audit"
# ux-designer reads the spec + confirmed requirements, fills all design pack gaps,
# and writes UX-DESIGN-READINESS.md.
# pm-agent validates the design pack faithfully represents product intent.
# Answer any structural brand questions it surfaces before proceeding.

# 3. Architect — technical architecture
# "Invoke architect for initial architecture review"
# architect reads confirmed requirements + UX-DESIGN-READINESS.md,
# asks any technical questions, and writes ADR-001-pilot.md

# 4. Ops designer — telemetry spec (SKIP if project has no ops complexity)
# "Invoke ops-designer to produce the telemetry spec"
# ops-designer reads the spec + ADR, authors docs/ops/TELEMETRY-SPEC.md.
# architect signs off on the spec before any build step begins.
# Skip this step for CLI tools, libraries, or projects without background jobs,
# external integrations, or multi-service architecture.

# 5. Technical design — detailed spec
# "Invoke technical-design to produce the technical design"
# technical-design reads all documents above, iterates with architect,
# and writes TECHNICAL-DESIGN.md
```

**Gate:** Do not start build step 1 until TECHNICAL-DESIGN.md is architect-approved.

---

## Inner Development Loop (during coding — before the per-step pipeline)

The per-step pipeline below (PHASE 0–11) runs *once per build step*, after coding is complete. But coding itself is an incremental process — N sequential prompts, each building on the previous change. Without local verification between prompts, errors accumulate silently and become expensive to untangle.

**Rule: run cheap gates after every incremental change, before the next prompt.**

```bash
# After each agent-produced code change, before issuing the next prompt:
bash scripts/oversight/gates/lint_check.sh [changed files]
bash scripts/oversight/gates/type_check.sh [changed files]
python manage.py test [affected test module] --keepdb   # or your stack's equivalent
```

If any check fails: fix it before issuing the next prompt. Do not accumulate failures across prompts.

> **Why this matters:** AI agents have limited cross-prompt memory of codebase state. An agent asked to "add X" on a tree where Y is already broken produces code that looks correct but depends on a broken foundation. By the time PHASE 1 gates run (after coding is complete), the failure stack may span many prompts and require significant archaeology to untangle. Local verification after each prompt is the only reliable way to keep the codebase in a known-good state throughout development.

The PHASE 1 gate scripts below serve as a **safety net** — if the inner loop ran correctly, PHASE 1 should be green. A PHASE 1 failure on a gate that the inner loop should have caught (lint, type errors) is a signal that the inner loop was skipped.

---

## Per-Step Pipeline

Run this sequence for each build step (N = step number, e.g. 3).

---

### PHASE 0 — Spec Red-Team (before coding starts)

Invoke the `spec-red-team` Claude agent on the relevant spec section before any code is written. It uses agy adversarially to find gaming vectors, contradictions, and implicit assumptions.

```bash
# Open Claude Code in [your project] and invoke the agent:
# "Use spec-red-team to review the spec section for step N"
# The agent will call agy and create spec-gap GitHub issues for any findings.
# pm-agent must resolve open spec-gap issues before coder starts.
```

**Output:** `spec-gap` GitHub issues (if findings). Coder does not start until pm-agent confirms spec is clear.

---

### PHASE 1 — Gate Scripts (blocking, before review chain)

Run before coding is submitted for review. These fail fast and cheap.

```bash
cd ~/[your project]

# Lint + formatting
bash scripts/oversight/gates/lint_check.sh [changed files...]
# or: bash scripts/oversight/gates/lint_check.sh --all

# Type checking
bash scripts/oversight/gates/type_check.sh [changed files...]

# Secret detection
bash scripts/oversight/gates/secret_scan.sh [changed files...]
# or with staged files: bash scripts/oversight/gates/secret_scan.sh --staged

# Security scan (HIGH severity = blocking)
bash scripts/oversight/gates/security_scan.sh [changed files...]
```

All must exit 0 before proceeding. Fix any failures before the review chain.

---

### PHASE 2 — Risk Assessment

> **For MEDIUM+ steps: capture the prompt artifact BEFORE running this phase.** risk-assessor reads `Prompt-Artifact:` git trailers to invoke `prompt-fidelity`; if the artifact does not exist at assessment time, the fidelity check is silently skipped. Run `bash scripts/capture_prompt.sh` and commit with the trailer first, then proceed with Phase 2. (Phase 5 below is a record-keeping step for this artifact, not the trigger.)

Run after gates pass. Scores the code across 9 dimensions and produces an inspection brief for reviewers.

```bash
# Collect changed files (adjust pattern as needed)
CHANGED=$(git diff --name-only HEAD~1 -- '*.py' | tr '\n' ' ')

# Run all validators (includes ip_check, prompt_audit_risk, rn_calculator, etc.)
bash scripts/oversight/run_validators.sh $CHANGED

# Read results
cat .claudetmp/oversight/validators/summary.json | python3 -m json.tool
```

**Key outputs:**
- `composite_score` — 0.0–1.0
- `tier` — LOW / MEDIUM / HIGH / CRITICAL
- `successful_validators` — if 0, pipeline halted (fail-closed)
- Per-dimension scores in `.claudetmp/oversight/validators/*.json`

**IP check results** (from `ip_check.json`):
```bash
cat .claudetmp/oversight/validators/ip_check.json | python3 -m json.tool
# Level 1: dependency license findings (copyleft/unknown = HIGH)
# Level 2: prompt artifact clean-room analysis
# Level 3: regurgitation stub (not yet active)
```

**Prompt ambiguity results** (from `prompt_ambiguity.json`):
```bash
cat .claudetmp/oversight/validators/prompt_ambiguity.json | python3 -m json.tool
# High ambiguity score → spec was unclear → reviewer attention directed here
```

Then invoke the `risk-assessor` Claude agent:
```
"Run risk-assessor for step N on [changed files]. Score is [composite] (tier: [TIER])."
```

The agent reads all validator output, validates the risk tier (applying deterministic floor rules for auth, DB migrations, PII, booking gates, right-to-erasure, audit log, admin control), and writes `.claudetmp/oversight/validators/risk-assessment.md` containing the validated tier and inspection brief.

**Subagent Invocations based on Risk Tier:**
- **At MEDIUM+**: risk-assessor invokes `prompt-fidelity` subagent against prompt artifacts to perform semantic prompt-to-code comparison.
- **At HIGH+**: risk-assessor also invokes `dep-mapper` (to map direct imports and framework implicit wiring) and `risk-historian` (to analyze issue history and git churn).
- **At CRITICAL**: risk-assessor additionally performs spec-code fidelity checks and flags confidence-complexity mismatches.

---

### PHASE 3 — Internal Review Chain

Run the review agents in order, directed by the inspection brief from risk-assessor.

**Always required (every step):**
```
Invoke: code-reviewer
Input: inspection brief from risk-assessment.md
Output: sign-off register entry → .claudetmp/signoffs/stepN-register.md
```

**Required by step (check step-manifest.yaml):**

```bash
# See which reviewers are required for step N:
python3 -c "
import yaml
m = yaml.safe_load(open('contract/step-manifest.yaml'))
step = next(s for s in m['steps'] if s['id'] == N)
print('Required:', step['required_signoffs'])
print('System test:', step.get('system_test_applicable'))
print('Human gate:', step.get('human_gate_required'))
"
```

Run parallel reviewers (security + privacy run simultaneously after code-reviewer approves):
```
Invoke: security-reviewer  ← always for MEDIUM+
Invoke: privacy-reviewer   ← steps with PII: 3, 6, 9, 10, 11
Invoke: ui-reviewer        ← step 10 (templates)
Invoke: a11y-reviewer      ← step 10 (templates)
Invoke: infra-reviewer     ← steps 1, 11 (infrastructure)
Invoke: ops-reviewer          ← steps with background jobs, external integrations,
                                 or async work (if ops configured for this project)
Invoke: reliability-reviewer  ← steps introducing or modifying outbound connections
                                 (DB queries, HTTP calls, queue ops, cache reads/writes)
```

> **Note — `ux-designer` has two modes:**
> - **Project start (proactive):** invoked after `pm-agent` completes Q&A, before `architect`. Audits the design pack against the full spec, fills all gaps, and writes `docs/design/UX-DESIGN-READINESS.md`. The architect and technical-design agent read this document before starting their own work.
> - **During the build (reactive):** when `ui-reviewer` or `a11y-reviewer` finds a design pack gap (missing token, undocumented component, contrast failure), they invoke `ux-designer` rather than escalating to human. `ux-designer` extends the design pack and notifies both reviewers. This happens within the existing review iteration — it does not add a new pipeline phase.

> **Note — `ops-designer` has two modes (optional — projects with background jobs, external integrations, or multi-service architecture):**
> - **Project start (proactive):** invoked after `architect` completes the ADR. Authors `docs/ops/TELEMETRY-SPEC.md` — the observability contract covering logging conventions, metric naming, tracing requirements, health checks, and dashboard/alerting intent. `architect` signs off on the spec before any build step begins.
> - **During the build (reactive):** when `ops-reviewer` finds a gap not covered by the spec, it escalates to `ops-designer` who fills the gap (additive: already-covered component only) or escalates to architect + human (structural: new component, new dependency, new instrumentation class). This happens within the existing review iteration — it does not add a new pipeline phase.

**Unit tests (iterate with coder until 80%/75%):**
```
Invoke: unit-test
Target: 80% coverage, 75% mutant score
Issues: creates test-resistance GitHub issue on 5-round loop exhaustion
```

**Sign-off register** — each agent writes one entry. Format:
```
## security | parking/views.py | 2026-06-11T15:10Z
Status: APPROVED
Agent: security-reviewer
Artifact: parking/views.py, parking/models.py
Iterations: 2
Critical_findings_resolved: false
Notes: Clean review. select_for_update() present. No cross-tenant leaks.
```

---

### PHASE 4 — System Tests (if applicable for this step)

```bash
# Check if system tests apply for this step:
# system_test_applicable: true in step-manifest.yaml

# Run system tests
cd ~/[your project]
python manage.py test tests/system/ --keepdb

# pm-agent must have signed off on the test plan before tests run.
# Invoke: system-test agent (runs tests + writes register entry)
```

Persistent failures after 5 rounds → `bug` GitHub issue filed → escalate to architect.

---

### PHASE 5 — Prompt Artifact Capture (MEDIUM+ steps)

For steps where risk tier is MEDIUM or above, capture the prompt artifact. If you haven't already done so before Phase 2 (see note at Phase 2), do it now and amend the commit with the `Prompt-Artifact:` trailer.

```bash
# Capture prompt artifact (mirrors src/ structure into prompts/)
bash scripts/capture_prompt.sh parking/views.py "Booking gate logic for step 6"

# Add Prompt-Artifact trailer to commit message:
git commit -m "Add booking gate view

Implements three-gate booking creation: horizon check, one-active check,
and GiST exclusion constraint for overlap safety.

Prompt-Artifact: prompts/parking/views.md
AI-Model: claude-sonnet-4-6
AI-Risk: CRITICAL"
```

---

### PHASE 6 — Second Review (pre-PR, cross-vendor)

Run after all internal reviewers have approved and system tests pass.

```bash
# Get composite score from validators (or re-run if stale)
SCORE=$(cat .claudetmp/oversight/validators/summary.json | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['composite_score'])")

echo "Score: $SCORE"

# Run second review
bash scripts/run_second_review.sh \
  --step N \
  --score $SCORE \
  --diff HEAD~1

# agy fires at score ≥ 0.30 (MEDIUM+)
# codex fires at score ≥ 0.55 (HIGH+)
# Output: .claudetmp/second-review/stepN-{timestamp}.md
# Top-level fields: verdict, highest_severity, unresolved_findings
```

Check the verdict:
```bash
head -8 .claudetmp/second-review/stepN-*.md | tail -5
# verdict: approve | request_changes | error | skipped
```

If `request_changes`: address findings, re-run. If `verdict: error`: check CLI auth.

**Token usage after second review:**
```bash
python3 scripts/oversight/token_tracker.py report
# Shows agy + codex usage vs. subscription quotas
```

---

### PHASE 7 — Oversight Evaluation

Invoke the `oversight-evaluator` agent. It runs Phase 1 (compliance) then Phase 2 (quality).

```
Invoke: oversight-evaluator
Input: contract/step-manifest.yaml, .claudetmp/signoffs/stepN-register.md,
       .claudetmp/second-review/stepN-*.md,
       .claudetmp/oversight/validators/risk-assessment.md,
       .claudetmp/oversight/step{N}-human-authorization.md (if CRITICAL step)
```

**For CRITICAL steps (3 and 6) — human authorization required FIRST:**
```bash
# Before running oversight-evaluator on steps 3 or 6:
mkdir -p .claudetmp/oversight
cat > .claudetmp/oversight/stepN-human-authorization.md << EOF
Authorized: $(date -I)
Decision: [your explicit decision to proceed]
Reviewed: [what you personally reviewed]
Authorized by: Scott Thurlow
EOF
```

**Evaluator outputs:**
- `PROCEED` → orchestrator opens PR
- `CONDITIONAL_PROCEED` → PR opens with "Human Review Required Before Merge" section
- `ESCALATE` → PR does NOT open; specific question surfaced to human

For ESCALATE, read the escalation items, address them, then re-run.

---

### PHASE 8 — Orchestrator (open PR)

Invoke the `oversight-orchestrator` agent after evaluator recommends PROCEED or CONDITIONAL.

```
Invoke: oversight-orchestrator
Input: .claudetmp/oversight/stepN-evaluation-{ts}.md
```

The orchestrator acts on the evaluator's recommendation:
- **On `PROCEED`**:
  1. Writes `panel-context.md` — structural risk signals only (no internal findings).
  2. Writes `handoff.md` — full picture for human/PR body (with AI-PR attribution).
  3. Opens the PR: `gh pr create --title "[AI: oversight-orchestrator] Step {N}: {name}" --body "$(cat .claudetmp/oversight/stepN-handoff.md)"`.
  4. Prints the panel command.
- **On `CONDITIONAL_PROCEED`**:
  - Same as PROCEED, but appends a "Human Review Required Before Merge" section listing confidence gaps and resolved critical findings.
- **On `ESCALATE`**:
  - PR is NOT opened. Outputs a formatted escalation box to the console listing compliance/quality issues that must be addressed, along with specific remediation instructions.

---

### PHASE 9 — Cross-Vendor Panel (post-PR)

Run after the PR is open. This is the outer loop — adversarial, independent.

```bash
# Get the PR number from the orchestrator output or:
PR=$(gh pr view --json number -q .number)

# Run the full panel
bash scripts/run_panel.sh $PR

# Panel uses: agy (correctness), codex (security + adversary), IP agent, Copilot
# Reads: .claudetmp/oversight/stepN-panel-context.md (structural signals only)
# Posts: one PR thread per finding
# Creates: escaped-defect GitHub issues for new findings
```

**Monitor panel output:**
```bash
# Panel logs to .ai-local/panel/pr{N}-{date}/
ls .ai-local/panel/
```

**Token usage after panel:**
```bash
python3 scripts/oversight/token_tracker.py report
```

---

### PHASE 10 — Human Gate

Review and resolve all PR threads before merging.

```bash
# List open threads
gh pr view $PR --json reviewThreads

# Each finding must be explicitly addressed:
# - Fix the code and push → thread resolves on re-review
# - Respond with explanation if you disagree → thread resolves when reviewer agrees
# Merge is blocked until ALL threads are resolved (branch protection setting)

# Merge when clean
gh pr merge $PR --squash
```

---

### PHASE 11 — Audit Log Entry

After merge, append the step summary to the audit trail.

```bash
cd ~/[your project]

# Quick entry (full entry generated by orchestrator at PR open time)
python3 -c "
import json
from datetime import datetime, timezone
entry = {
    'ts': datetime.now(timezone.utc).isoformat(),
    'event': 'merge',
    'step': N,
    'pr': $PR,
    'commit': '$(git rev-parse HEAD)',
    'tier': 'HIGH',  # replace with actual tier from summary.json
}
with open('audit/oversight-log.jsonl', 'a') as f:
    f.write(json.dumps(entry) + '\n')
print('Audit entry written')
"

git add audit/
git commit -m "Step N: audit log entry — merge PR $PR"
git push origin build
```

---

## Cross-Role Feedback Loops

When work mid-build reveals a gap in the spec, design pack, or telemetry spec, agents route through a defined chain rather than jumping directly to pm-agent or human. The universal principle: **enter at the lowest authority that can resolve it; escalate only if that level cannot.**

### Spec-gap chain (requirements and design gaps)

```
coder / security-reviewer / privacy-reviewer
  → technical-design    (can it be resolved at the implementation design level?)
      → architect        (does it require an architectural decision?)
          → spec-gap issue for pm-agent   (only if it requires a product decision)
```

**Rules:**
- `coder` halts on meaningful behavioral ambiguity → escalates to `technical-design` with both interpretations
- `security-reviewer` / `privacy-reviewer` with a spec gap → escalate to `technical-design`, not pm-agent directly
- `technical-design` handles the gap or escalates up; it is the first receiver for all spec-gap routes below it
- `architect` creates the `spec-gap` issue when it confirms a product decision is needed; it does not route directly to pm-agent for implementation questions
- `pm-agent` receives `spec-gap` issues, updates the spec, notifies the blocked agent and architect/technical-design of the change

### Design pack loop (UX gaps)

```
ui-reviewer / a11y-reviewer
  → ux-designer    (fill the gap)
      → re-notify invoking reviewer to re-review
          → if still unresolved after 2 cycles: escalate to human
```

**Rules:**
- `ui-reviewer` states the specific missing element when escalating; `ux-designer` fills and notifies back
- `a11y-reviewer` escalates contrast failures; `ux-designer` adds accessible token and notifies back
- `ux-designer` consults `pm-agent` when reactive gap-filling reveals a product-scope question not in the original spec; if pm-agent confirms it's out of scope, creates a `spec-gap` issue and halts
- Maximum 2 cycles before human escalation

### Telemetry spec loop (observability gaps) — projects with ops configured

```
ops-reviewer
  → ops-designer    (fill the spec gap)
      → re-notify ops-reviewer to re-review
          → if still unresolved after 2 cycles: escalate to architect, then human
```

See ops-designer and ops-reviewer agent files for additive vs. structural classification rules.

### What pm-agent does when it receives a spec-gap mid-build

1. Read the issue — understand what agent raised it and what it is blocked on
2. Classify: clarifying / additive / structural
3. Update the spec (structural changes require human approval first)
4. Notify the blocked agent (via issue comment) and `architect` + `technical-design` of the change
5. Close the issue only after the spec is updated and the blocked agent is unblocked

---

## Checkpoint Red-Teams

Run at steps 3, 6, 10, 11 (after those steps are merged):

```bash
# After step 3 — auth system
bash scripts/run_red_team.sh --milestone auth

# After step 6 — booking gates
bash scripts/run_red_team.sh --milestone booking

# After step 10 — admin portals
bash scripts/run_red_team.sh --milestone admin

# After step 11 — live deployment
bash scripts/run_red_team.sh --milestone deploy
```

Each red-team:
- Reads the full codebase (not just a diff)
- Uses codex (adversarial attack chains) + agy (spec vs. implementation gap)
- Requires "not exploitable" attestations — a clean finding list without them is invalid
- Creates `red-team-finding` GitHub issues for critical/high findings
- Output: `.claudetmp/red-team/checkpoint-{milestone}-{ts}.md`

---

## IP Check Details

IP checking runs automatically as part of `run_validators.sh`. But you can run it standalone:

```bash
# Check changed dependency files + prompt artifacts
python3 scripts/oversight/validators/ip_check.py \
  --prompts-dir prompts/ \
  requirements.txt parking/views.py

# Level 1: License check (ScanCode Toolkit — full text comparison)
# Level 2: Prompt artifact clean-room analysis
# Level 3: Regurgitation stub — awaiting AboutCode API access
```

**If Level 1 finds copyleft/unknown licenses:**
```bash
cat .claudetmp/oversight/validators/ip_check.json | \
  python3 -c "
import json, sys
d = json.load(sys.stdin)
for f in d.get('findings', []):
    if f.get('severity') in ('high', 'medium'):
        print(f['message'])
"
```

Address copyleft findings before the PR opens. Unknown licenses → legal review before shipping.

---

## Useful Queries

```bash
# Token burn today
python3 scripts/oversight/token_tracker.py report

# Token burn all-time
python3 scripts/oversight/token_tracker.py report --all

# All escaped defects
jq 'select(.event=="panel-run") | {step, escaped_defects}' \
  audit/oversight-log.jsonl

# All security findings filed
gh issue list --label security-finding --state all

# Sign-off register for step N
cat .claudetmp/signoffs/stepN-register.md

# Second review verdict for step N
head -10 .claudetmp/second-review/stepN-*.md

# Risk tier history
jq 'select(.event=="risk-assessment") | {step, tier, score}' \
  audit/oversight-log.jsonl
```

---

## Post-Change Sweep

Run before committing any batch of changes. The sweep agent categorizes your diff and drives all relevant reviews automatically.

```bash
# Step 1 — see routing plan (no AI, instant)
bash scripts/framework/run_post_change_sweep.sh

# Step 2 — invoke the sweep agent in Claude Code
# "Run post-change sweep"
# The agent reads the routing plan and invokes all listed agents in order.
```

**Framework-only changes** (agent files, docs, framework scripts):
```bash
# Fast path — static + AI review of framework files only
bash scripts/framework/run_framework_validation.sh

# Or static-only (no AI, for quick pre-commit check):
bash scripts/framework/run_framework_validation.sh --static-only
```

**What the sweep agent drives, by domain:**

| Domain changed | Agents invoked |
|---|---|
| `.claude/agents/`, `docs/AGENTS.md`, `scripts/framework/` | `framework-validator` |
| `*.py` app code (application-code) | `code-reviewer` → (parallel) `security-reviewer`, `privacy-reviewer`, `ops-reviewer`* |
| `**/migrations/*.py` (migrations) | `code-reviewer` → (parallel) `security-reviewer`, `privacy-reviewer` |
| `templates/*.html` (templates) | `ui-reviewer`, `a11y-reviewer` (after `code-reviewer` approves) |
| `docker-compose.yml`, `Caddyfile` (infrastructure) | `infra-reviewer` |
| `tests/**` (tests) | `unit-test` |
| `Specs/*design*/**` (design-pack) | `ux-designer` → `ui-reviewer` |
| `Specs/*.md` (spec) | `pm-agent` |
| `**/admin*.py`, `**/audit*.py`, `**/operator_console/**` (admin-audit) | `code-reviewer` → (parallel) `security-reviewer`, `privacy-reviewer` |

*\* `ops-reviewer` runs when the change introduces background jobs, external API calls, async tasks, or new failure paths AND `docs/ops/TELEMETRY-SPEC.md` exists. If spec is absent but ops complexity is present, `ops-designer` is invoked first.*

> **Note on `ux-designer`:** Has two modes. **At project start** it is invoked proactively (after `pm-agent`, before `architect`) to audit the design pack against the full spec and write `docs/design/UX-DESIGN-READINESS.md` — see the Project Start Sequence above. **During the per-step pipeline** it is reactive: when `ui-reviewer` or `a11y-reviewer` finds a design pack gap, they invoke `ux-designer` rather than escalating to human. `ux-designer` extends the design pack and notifies both reviewers within the existing review iteration, without adding a new phase.

> **Note on `ops-designer` / `ops-reviewer`:** Optional pair for projects with ops complexity. **At project start** `ops-designer` produces `docs/ops/TELEMETRY-SPEC.md` after `architect` completes the ADR; `architect` signs off. **During the per-step pipeline** `ops-reviewer` enforces the spec; gaps escalate to `ops-designer` (additive changes) or `architect` + human (structural changes). N/A for projects without background jobs, external integrations, or multi-service architecture.

---

## Quick Reference — Which Reviewers for Which Steps

| Step | Risk | code | security | privacy | ui/a11y | infra | test-unit | test-system | process | human gate | red-team |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 Scaffold | LOW | ✓ | | | | ✓ | | | | | |
| 2 Multi-tenant | HIGH | ✓ | ✓ | | | | ✓ | | | | |
| 3 Auth | CRITICAL | ✓ | ✓ | ✓ | | | ✓ | ✓ | ✓ | ✓ | auth |
| 4 Data model | HIGH | ✓ | ✓ | | | | ✓ | | | | |
| 5 Availability | HIGH | ✓ | ✓ | | | | ✓ | ✓ | ✓ | | |
| 6 Booking gates | CRITICAL | ✓ | ✓ | ✓ | | | ✓ | ✓ | ✓ | ✓ | booking |
| 7 Horizon | MEDIUM | ✓ | ✓ | | | | ✓ | ✓ | ✓ | | |
| 8 Cancellation | MEDIUM | ✓ | ✓ | | | | ✓ | ✓ | ✓ | | |
| 9 Notifications | MEDIUM | ✓ | ✓ | ✓ | | | ✓ | ✓ | ✓ | | |
| 10 Admin portals | HIGH | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ | | admin |
| 11 Deploy | HIGH | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ | | | deploy |
