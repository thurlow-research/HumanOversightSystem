# HumanOversightSystem — CLAUDE.md

This repo is the canonical home of the Human Oversight System (HOS): a portable framework for scaling human oversight of AI-generated code. Read this before any task.

---

## What this repo is

The HOS is simultaneously:
1. A **deployable framework** — install it into any project with `./scripts/setup_oversight.sh`
2. A **contract specification** — defines what any compliant agent team must produce
3. A **research instrument** — empirical substrate for studying AI code oversight at scale

It is not dissertation work itself; that lives in `../VibeOversightDissertation`. The two repos are siblings. This repo owns the framework; the dissertation repo owns the research.

---

## Repo layout

```
AGENTS.md              Layer 1 self-flagging protocol (stable governance doc)
DECISIONS.md           Design decision log — the history of the system
METHODOLOGY.md         End-to-end pipeline explainer
contract/
  OVERSIGHT-CONTRACT.md  What any compliant agent team must produce
  step-manifest.template.yaml  Project config template
.claude/agents/        Oversight layer agents (evaluator, orchestrator, risk-assessor, etc.)
scripts/
  install.sh → root-level, also at scripts/
  run_panel.sh           Outer loop: post-PR cross-vendor panel
  run_second_review.sh   Transition: pre-PR cross-vendor second review
  run_red_team.sh        Checkpoint: system-level adversarial red-team
  capture_prompt.sh      Prompt artifact capture
  prompt_audit.sh        Prompt provenance audit
  setup_oversight.sh     Install framework into a target project
  setup_clis.sh          Machine bootstrap (installs agent CLIs)
  oversight/
    validators/          Risk scoring scripts (Python, deterministic)
    gates/               Blocking pre-review checks (bash)
    run_validators.sh    Orchestrate all validators
    requirements.txt     Python dependencies
templates/             Files copied by setup_oversight.sh
```

---

## The two bootstraps

**Machine bootstrap** (`./scripts/setup_clis.sh`): installs agent CLIs (claude, codex, agy, gh) and their Node runtime onto the machine. Run once per machine.

**Project install** (`./install.sh` or `./scripts/setup_oversight.sh <path>`): installs the oversight protocol into a target project — AGENTS.md, scripts, PR template, branch protection. Run once per project.

---

## The contract

Any agent team that wants full oversight support must implement the contract defined in `contract/OVERSIGHT-CONTRACT.md`. The contract defines:
- **Filesystem protocol**: where sign-off register, temp files, and test declarations live
- **Self-flag format**: what code-producing agents must emit (RISK/CONFIDENCE/BLAST RADIUS)
- **Sign-off schema**: what reviewing agents must write to the register on approval
- **Role mappings**: which agent fills which oversight role (code-review, security, privacy, etc.)
- **Step manifest**: project config describing each build step, risk tier, and required sign-offs

Teams using the framework's own agent templates (see `.claude/agents/`) get contract compliance automatically.

---

## Oversight agents in this repo

These agents are invoked by the oversight pipeline, not by the base development team:

| Agent | Role | When invoked |
|---|---|---|
| `risk-assessor` | Scores code, directs reviewers, validates risk tier | After coder produces code, before review chain |
| `dep-mapper` | Django dependency/blast-radius analysis | Subagent of risk-assessor |
| `risk-historian` | Historical bug density from issues + git churn | Subagent of risk-assessor |
| `spec-red-team` | Adversarial spec review before coding | Per build step, pre-coding |
| `oversight-evaluator` | Compliance + quality check after internal review | After system tests pass |
| `oversight-orchestrator` | Acts on evaluator recommendation (opens PR, escalates) | After evaluator produces recommendation |

---

## Pipeline position of each script

```
SPEC PHASE
  spec-red-team agent  →  spec-gap issues

INNER LOOP (per build step)
  gates/*.sh           →  blocking (lint/type/secret/security-HIGH)
  run_validators.sh    →  risk scores fed to risk-assessor agent
  risk-assessor agent  →  composite score + inspection brief
  [internal review agents in the base project]
  sign-off register updated

TRANSITION (post inner loop, pre-PR)
  system tests
  run_second_review.sh  →  agy (MEDIUM+), codex (HIGH+)
  oversight-evaluator   →  PROCEED / CONDITIONAL / ESCALATE
  oversight-orchestrator → opens PR or escalates to human

OUTER LOOP (per PR)
  run_panel.sh          →  agy + codex + IP agent + Copilot
  PR thread resolution  →  human gate
  merge

CHECKPOINT (milestone: after steps 3, 6, 10, 11)
  run_red_team.sh       →  system-level adversarial + "not exploitable" attestation
```

---

## Working in this repo

- When writing or editing scripts, follow the conventions in `setup_clis.sh` (colours, idempotency, platform detection).
- Agent files in `.claude/agents/` follow the contract in `contract/OVERSIGHT-CONTRACT.md` — don't add base-project logic here.
- `DECISIONS.md` is append-only. New decisions go at the bottom with a date header.
- Do not commit `.claudetmp/`, `.ai-local/`, or any `.salt` files.
