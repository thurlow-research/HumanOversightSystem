# HumanOversightSystem — CLAUDE.md

This repo is the canonical home of the Human Oversight System (HOS): a portable framework for scaling human oversight of AI-generated code. Read this before any task.

---

## What this repo is

The HOS is simultaneously:
1. A **deployable framework** — install it into any project with `./bootstrap/hos_install.sh` (from a validated release)
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
bootstrap/             The copy-to-machine bundle (the only thing you copy to a machine):
  hos_bootstrap.sh       MACHINE setup: Python/ScanCode/gh/pip; delegates to setup_clis.sh
  hos_install.sh         PROJECT install: fetches a validated RELEASE and scaffolds it into
                         a target repo (--release <tag> / --local). No sudo. Records
                         the installed tag at the target's .hos-release.
  setup_clis.sh          MACHINE bootstrap of agent CLIs (Node + claude/codex/agy + auth)
.claude/agents/        All shipped agents: 8 oversight layer agents (evaluator, orchestrator,
                       risk-assessor, etc.) + 16-agent base team (pm-agent, architect,
                       technical-design, coder, 8 reviewers, unit-test, system-test,
                       ops-designer, ux-designer). Each agent file is layered:
                       CORE (HOS-owned generic) / PACK:<name> (HOS-owned stack depth) /
                       PROJECT (consumer-owned). Region order is CORE → PACK → PROJECT.
packs/                 Stack-depth region bodies (body-only, no full agent files):
  <name>/              One directory per pack (e.g. packs/django/).
    <agent>.md         PACK:<name> region bodies for the agents that pack deepens.
    pack.toml          Pack metadata (name, version, supported agents).
scripts/
  run_panel.sh           Outer loop: post-PR cross-vendor panel (reads panel-context.md only)
  run_second_review.sh   Transition: pre-PR cross-vendor second review (machine-readable verdict)
  run_red_team.sh        Checkpoint: system-level adversarial red-team
  review_self.sh         Self-review: sends HOS to agy or codex (--reviewer flag)
  reverify_self.sh       Targeted re-review of fixes against original findings
  capture_prompt.sh      Prompt artifact capture
  prompt_audit.sh        Prompt provenance audit
  oversight/
    validators/          Risk scoring scripts (Python, deterministic):
      rn_calculator.py     Dai et al. Risk Number (nesting calibrated from bug data)
      complexity_metrics.py  Cyclomatic complexity (radon)
      function_metrics.py    Function length, param count, return paths
      n1_detector.py         Django N+1 query heuristic
      migration_scorer.py    Database migration risk classification
      static_analysis.py     bandit MEDIUM findings as scored risk signal
      diff_size.py           Change-size signal (review difficulty / blast radius); tier floor
      portability_check.py   Stack-specific portability signals (hardcoded paths, env assumptions)
      ip_check.py            IP/provenance: license gate (ScanCode) + prompt clean-room
                             + regurgitation stub (ai-gen-code-search, Level 3)
      prompt_audit_risk.py   Prompt ambiguity + fidelity surface scoring
      hallucination_surface.py  Version-sensitive API detection
      issue_query.py         Historical bug density from GitHub issues + git churn
      schema.py              Shared output schema, weights, tier thresholds (infra, not a dimension)
      regions.py             Shared region/parsing helpers (infra, not a dimension)
      brownfield.py          Brownfield scoring — present but NOT yet wired into run_validators.sh
    gates/               Blocking pre-review checks (bash)
    run_validators.sh    Orchestrate all validators (fail-closed CRITICAL if all fail)
    token_tracker.py     External CLI token usage tracking + subscription impact report
    requirements.txt     Python dependencies (ScanCode optional but recommended)
audit/                 Committed audit trail (oversight-log.jsonl + timestamped .md files)
contract/
  OVERSIGHT-CONTRACT.md       What any compliant agent team must produce
  step-manifest.template.yaml Project config template (includes UI/a11y + infra examples)
templates/
  base-agent-register-examples.md  Complete register entry examples for all 6 roles
```

---

## The two bootstraps

Both live in `bootstrap/` — the copy-to-machine bundle. Everything else is fetched from a release.

**Machine bootstrap** (`./bootstrap/hos_bootstrap.sh`): installs the machine prerequisites (Python 3.10+, ScanCode, gh, pip analysis packages) and — via `bootstrap/setup_clis.sh` — the agent CLIs (claude, codex, agy) + Node runtime. May need sudo. Run once per machine.

**Project install** (`./bootstrap/hos_install.sh [<path>]`): installs the full agent pipeline — AGENTS.md, all 26 shipped agents (oversight layer + base team), scripts, contract, PR template — into a target project. By default it installs from a **fetched, validated release** (not the local working copy); use `--release <tag>` to pin a version or `--local` for a dev install. Pass `--pack <name>` (e.g. `--pack django`) to inject stack-depth PACK regions into the relevant agents; `--no-pack` to install bare CORE only. The installed pack is recorded in `config.sh` as `PACK=` and re-applied on upgrades. No sudo — it checks prerequisites and points back to `hos_bootstrap.sh` if any are missing. Records the installed tag at the target's `.hos-release`. Run once per project (and on release bumps). On an interactive install it delegates project configuration to `scripts/framework/install.sh` (the `config.sh` generator), so one run produces a fully-configured project (#87). The install performs a **three-way region merge**: CORE and PACK regions are always taken from HOS (hard-stop on drift unless `--squash`); PROJECT regions are preserved as-is (consumer-owned, never overwritten).

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

## Agents in this repo

`.claude/agents/` contains **26 shipped agents** in two groups — the oversight layer (10 agents) and the base development team (16 agents). As of v0.3.0 HOS ships the canonical base team; the consumer no longer hand-rolls it. The canonical agent list is `scripts/framework/consumer_agents.txt` (single source of truth for the installer + `.hos-manifest`, #225). Every agent file is layered: **CORE** (HOS-owned generic) / **PACK:\<name\>** (HOS-owned stack depth) / **PROJECT** (consumer-owned). Stack depth for a given stack lands in `packs/<name>/` as body-only region files injected during install.

### Oversight layer (10 agents — invoked by the pipeline, not the base team)

| Agent | Role | When invoked |
|---|---|---|
| `worker` | Single human entry point for building work **and** the autonomous build agent. Routes implementation/design/review to specialists — never does that work itself. Two modes: INTERACTIVE (human-driven) and AUTONOMOUS (`bin/hos-cron --role worker` picks up `needs-ai` issues, builds, opens a PR) | Interactive session start, or per cron cycle |
| `overseer` | Autonomous PR review + merge authority. Evaluates what the worker built and decides what may merge; auto-merges up to `OVERSEER_CEILING` (default `HIGH`) when checks are green, routes `CRITICAL`/protected-surface to HUMAN_REQUIRED. Never opens branches or PRs | `bin/hos-cron --role overseer` per cron cycle, or interactive PR-status queries |
| `risk-assessor` | Scores code, directs reviewers, validates risk tier. Calls `prompt_audit_risk.py` + `ip_check.py` in Phase 2; calls `prompt-fidelity` at MEDIUM+ | After coder produces code, before review chain |
| `dep-mapper` | Dependency/blast-radius analysis (generic; projects override with stack-specific version) | Subagent of risk-assessor at HIGH+ |
| `risk-historian` | Historical bug density from GitHub issues + git churn | Subagent of risk-assessor |
| `prompt-fidelity` | Semantic prompt-vs-code comparison: unexplained additions, missing specs, loose interpretations | Subagent of risk-assessor at MEDIUM+ when prompt artifact exists |
| `spec-red-team` | Adversarial spec review before coding (uses agy for independence) | Per build step, pre-coding |
| `oversight-evaluator` | Phase 1: compliance (sign-off register, §3 required fields, prompt artifacts, human authorization). Phase 2: quality (convergence failures, resolved findings, confidence gaps) | After system tests pass |
| `oversight-orchestrator` | Acts on evaluator recommendation. Writes two separate files: `panel-context.md` (structural signals only, for panel) and `handoff.md` (full picture, for human/PR) | After evaluator produces recommendation |
| `post-change-sweep` | Orchestrates the full review suite after a change set — categorizes the diff, dispatches the right agents in dependency order | After any batch of changes, before commit |

### Base development team (16 agents — shipped by HOS, used by the consumer project)

| Agent | Role |
|---|---|
| `pm-agent` | Requirements and acceptance criteria |
| `architect` | Architecture decisions and ADRs |
| `technical-design` | Detailed technical design per build step |
| `coder` | Implementation (self-flags per AGENTS.md) |
| `code-reviewer` | General code quality review |
| `security-reviewer` | Security lens |
| `privacy-reviewer` | Privacy and data-handling lens |
| `reliability-reviewer` | Resilience to external-dependency failures |
| `ops-reviewer` | Telemetry-spec conformance (enforces `TELEMETRY-SPEC.md`) |
| `ui-reviewer` | UI/UX conformance review |
| `a11y-reviewer` | Accessibility review |
| `infra-reviewer` | Infrastructure and deployment review |
| `unit-test` | Unit test authoring and coverage |
| `system-test` | System/e2e test authoring |
| `ops-designer` | Observability/telemetry authority; produces `TELEMETRY-SPEC.md` |
| `ux-designer` | UX design authority; produces `UX-DESIGN-READINESS.md` |

> The framework-dev validators (`framework-validator`, `doc-validator`, `spec-compliance-validator`, `framework-setup-validator`) are **not** shipped to consumers — they belong to the planned `hos-dev-pack` (v0.3.0 dogfooding). They live in `.claude/agents/` in this source repo only.

---

## Pipeline position of each script

```
SPEC PHASE
  spec-red-team agent  →  spec-gap issues (uses agy for independence)

INNER LOOP (per build step)
  gates/*.sh           →  blocking (lint/type/secret/security-HIGH)
  run_validators.sh    →  12 signal dimensions (12 scripts, one each); fail-closed CRITICAL if all validators fail
                          includes: rn_calculator, complexity, N+1, migrations, diff_size,
                          portability_check,
                          ip_check (ScanCode license gate + prompt clean-room),
                          prompt_audit_risk (ambiguity score + fidelity surface)
  risk-assessor agent  →  composite score + inspection brief;
                          calls prompt-fidelity subagent at MEDIUM+
  [base-team review agents: code-reviewer, security-reviewer, privacy-reviewer,
   reliability-reviewer, ops-reviewer, ui-reviewer, a11y-reviewer, infra-reviewer]
  sign-off register updated (all entries must include Status/Agent/Artifact/Iterations)

TRANSITION (post inner loop, pre-PR)
  system tests
  run_second_review.sh  →  agy (MEDIUM+), codex (HIGH+); machine-readable verdict
                           header; fail-closed when agy unavailable at MEDIUM+
  oversight-evaluator   →  Phase 1: compliance; Phase 2: quality → PROCEED / CONDITIONAL / ESCALATE
  oversight-orchestrator → writes panel-context.md (structural signals only)
                           and handoff.md (full picture for human)
                           → opens PR or escalates to human

OUTER LOOP (per PR)
  run_panel.sh          →  reads panel-context.md only (no internal findings);
                           agy + codex + IP agent (ip_check.py, Level 1+2 active) + Copilot
  PR thread resolution  →  human gate
  audit/oversight-log.jsonl  ← append-only event log committed on each merge

CHECKPOINT (milestone: after steps 3, 6, 10, 11)
  run_red_team.sh       →  system-level adversarial + "not exploitable" attestations required
```

---

## Working in this repo

- When writing or editing scripts, follow the conventions in `bootstrap/setup_clis.sh` (colours, idempotency, platform detection).
- Agent files in `.claude/agents/` follow the contract in `contract/OVERSIGHT-CONTRACT.md`. CORE and PACK regions are HOS-owned — consumer project logic belongs only in PROJECT regions. Stack depth belongs in `packs/<name>/`, not in the base agent files.
- `DECISIONS.md` is append-only. New decisions go at the bottom with a date header.
- Do not commit `.claudetmp/`, `.ai-local/`, or any `.salt` files.
