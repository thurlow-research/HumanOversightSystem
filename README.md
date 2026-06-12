# Human Oversight System

A framework for scaling human oversight of AI-generated code — grounded in lean manufacturing principles, statistical quality control, and multi-agent system design.

This is both a working system and active doctoral research — Doctor of Technology program, Purdue University. The research sits at the intersection of engineering management, software quality assurance, and AI governance.

---

## The Problem

AI coding assistants are fast. They are also confidently wrong in ways that are hard to detect. The instinct is to review everything carefully — but that doesn't scale. The instinct is to trust the model — but that introduces invisible risk.

The core tension: **review bandwidth is finite; AI output is not.**

Existing approaches treat this as a binary — either review everything, or review nothing. This framework treats it as a quality control problem.

---

## Theoretical Basis

The framework draws from three traditions:

**Lean Manufacturing — Jidoka**
Toyota's principle of "automation with a human touch": machines run autonomously but stop and signal the moment they detect a defect. Applied here, AI agents run autonomously but are required to surface their own uncertainty, flag risk, and halt before destructive operations — not wait to be caught.

**Statistical Quality Control**
Cobb & Mills' Cleanroom method applied to code: not every unit needs 100% inspection. Risk-stratified sampling allocates human attention proportionally — low-risk changes get spot checks, critical changes get exhaustive review. The escaped-defect rate becomes a measurable signal, not just a feeling.

**Signal Detection Theory**
Human reviewers have a prior. AI confidence declarations (explicit uncertainty + basis) are an input to that prior, not a replacement for it. The system is designed to calibrate human attention, not eliminate it.

---

## Framework Overview

The framework operates on three layers:

### Layer 1 — Self-Flagging (Single Agent)

Every non-trivial AI code generation must produce:

- **Risk classification**: `LOW | MEDIUM | HIGH | CRITICAL`
- **Human Review Required** section: specific lines or patterns, and *why* (correctness vs. security vs. IP)
- **Confidence declaration**: percentage + explicit basis for uncertainty
- **Hallucination surface warnings**: flagged for any version-sensitive API, undocumented behavior, or library assumption
- **Blast radius assessment**: for destructive operations — what breaks, and how to undo it

This is not optional commentary. It is a structured output contract.

### Layer 2 — Multi-Agent Review Panel

Independent reviewers cover orthogonal risk axes. Cross-vendor decorrelation (e.g., Claude as author, different model families as reviewers) reduces correlated failure modes. Each reviewer holds a specific lens:

| Lens | Concern |
|---|---|
| Correctness | Logic errors, spec conformance, test coverage |
| Security | Injection, auth, multi-tenant isolation, credential handling |
| Privacy | PII handling, GDPR obligations, data minimization |
| IP / Provenance | License exposure, attribution, regurgitation risk |
| Maintainability | Coupling, abstraction altitude, future-reader clarity |

An arbiter synthesizes findings into a structured verdict posted as PR review threads. Threads block merge until resolved — each finding requires a human decision, not just acknowledgment.

### Layer 3 — Risk-Stratified Human Gates

Human attention is allocated by risk tier, not uniformly:

| Risk | Gate |
|---|---|
| LOW | Automated CI gates + statistical spot-check audit |
| MEDIUM | ≥1 cross-vendor reviewer; human reviews flagged items |
| HIGH | Security adversary always-on; human reviews line-by-line |
| CRITICAL | Blast radius required; human approval mandatory before merge |

The statistical spot-check on LOW-tier changes is not theater — it provides an ongoing escaped-defect rate, which is the primary feedback signal for calibrating the tier thresholds over time.

---

## Prompts as Artifacts

AI-generated code has a provenance problem: the prompt that produced it is usually invisible.

This framework treats prompts as first-class source artifacts, version-controlled alongside the code they produce. Git commit trailers encode AI provenance:

```
Prompt-Artifact: prompts/auth/middleware.md
AI-Model: claude-sonnet-4-6
AI-Risk: HIGH
```

This makes the full AI contribution queryable (`git log --grep="Prompt-Artifact:"`), auditable, and reproducible — which matters for research, for IP review, and for any future regulatory context.

---

## Pipeline

```
PROMPT → AUTHOR + SELF-FLAG → CAPTURE PROMPT ARTIFACT → COMMIT (with trailers)
  ↓
PR (protected branch: code owner review required)
  ↓
CHEAP GATES (lint, types, build, tests, secret scan)
  ↓
RISK TRIAGE
  ↓
EXPENSIVE GATES (gated by risk tier: e2e, coverage, mutation testing)
  ↓
AI REVIEW PANEL (cross-vendor, role-based lenses)
  ↓
ARBITER SYNTHESIS → PR threads
  ↓
HUMAN GATE (mandatory at HIGH / CRITICAL; threads block merge)
  ↓
MERGE → ARCHIVE
```

The pipeline is designed *cheap-first*: inexpensive automated gates run before expensive panel reviews. Human attention is the most expensive resource and runs last.

---

## Multi-Agent Architecture Patterns

Several patterns have emerged across the empirical work:

**Separation of Concerns** — Each agent owns exactly one decision domain. All other decisions escalate. This prevents agents from reasoning outside their competence and makes failures legible.

**Bounded Iteration with Escalation** — Review cycles have a hard iteration limit (typically 5 rounds). Non-convergence is not an error state — it is a signal that the decision requires human judgment. The andon cord gets pulled.

**Spec as Source of Truth** — All inter-agent disputes are resolved by re-reading the specification with citation. Agents are explicitly prohibited from "spec falsification" — rationalizing code that doesn't meet the spec by reinterpreting the spec.

**Temp State Checkpointing** — Long-running pipelines write timestamped checkpoint files. Stale files (>24h) auto-delete. This prevents infinite loops and makes pipeline state inspectable without running the pipeline.

**Confidence Declarations as Calibration Signals** — Explicit uncertainty from the AI is an input to the human reviewer's prior. A fluent, confident output and a hedged output carry different review weights.

---

## Research Context

This framework is the subject of doctoral research examining how human oversight of AI-generated code can be made both rigorous and scalable. The empirical substrate is real software built under the framework — not a controlled lab setting.

The research draws on a systematic literature review of ~1,000 papers on AI code governance, multi-agent systems, and software quality assurance.

**Dissertation committee includes:**
- Paul J. Thomas (Purdue) — IT systems, project management, cybersecurity
- Linda Naimi (Purdue) — Technology law, IP, ethics, generative AI legal implications
- Hancheng Cao (Emory Goizueta) — Computational social science, AI in development teams
- Kyubyung Kang (Purdue) — Machine learning and AI governance in safety-critical systems
- David Pistrui (Purdue) — Organizational transformation, Industry 4.0

---

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full agent roster, pipeline diagrams, feedback loops, and sign-off accountability map. It covers:

- The two-layer protection model (self-flagging + independent cross-vendor review)
- All 6 oversight agents with roles and models
- Full pipeline flowchart across all 5 phases with per-phase sequence diagrams
- The feedback loops diagram: how issues feed back into risk scoring over time
- Risk stratification showing which external reviewers fire at which composite scores

---

## Status

This system is under active development. Current state is honest:

- Self-flagging layer: implemented and in use
- Multi-agent panel: prototype (run on a small number of PRs)
- IP / provenance agent: stub
- Statistical spot-check sampling: designed, not yet automated
- Cheap/expensive gate pipeline: partially implemented

Contributions, critique, and collaboration welcome.

---

## License

MIT License — see [LICENSE](LICENSE). Copyright Scott Thurlow 2026.

Attribution is required for distributions. The research framing and framework design are Scott Thurlow's original work; collaboration and derivative builds are encouraged.
