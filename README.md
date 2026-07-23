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
Toyota's principle of "automation with a human touch": machines run autonomously but stop and signal the moment they detect a defect. Applied here, AI agents run autonomously but are required to surface their own uncertainty, flag risk, and halt before destructive operations — not wait to be caught. The critical transfer is that quality responsibility belongs to the *producer*, not the downstream inspector: Ohno's formulation makes the machine an active participant in defect detection rather than a passive output source. For AI agents, this means self-flagging is a first-class output requirement, not a best-effort courtesy (Ohno, *Toyota Production System: Beyond Large-Scale Production*, Productivity Press, 1988).

**Statistical Quality Control**
Cobb & Mills' Cleanroom method applied to code: not every unit needs 100% inspection. Risk-stratified sampling allocates human attention proportionally — low-risk changes get spot checks, critical changes get exhaustive review. The escaped-defect rate becomes a measurable signal, not just a feeling. Cleanroom was the first software methodology to demonstrate that escaped-defect rates can be *predicted* from process signals rather than discovered after deployment — teams that certify their own statistical process can contract against a defect rate, not just hope for one. Risk tier declarations in this framework serve the same function: they are the process signal that determines sampling intensity and makes oversight empirically accountable (Cobb & Mills, "Engineering Software Under Statistical Quality Control," *IEEE Software*, vol. 7, no. 6, 1990).

**Signal Detection Theory**
Human reviewers have a prior. AI confidence declarations (explicit uncertainty + basis) are an input to that prior, not a replacement for it. The system is designed to calibrate human attention, not eliminate it. This matters because unaided human oversight doesn't scale: when a system is mostly correct and defects are rare, human monitoring performance degrades substantially — reviewers miss more, grow complacent, and allocate attention uniformly rather than to risk. Parasuraman et al. formalize this as a structural property of human-automation interaction, not a failure of diligence (Parasuraman, Sheridan & Wickens, "A Model for Types and Levels of Human Interaction with Automation," *IEEE Transactions on Systems, Man, and Cybernetics*, 2000). Risk-stratified review and explicit AI uncertainty signals are a direct response to this limitation.

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
- **Working-state verification**: after every incremental change, run lint + type-check + unit tests before the next prompt. Never accumulate unverified changes.

This is not optional commentary. It is a structured output contract. See [`AGENTS.md`](AGENTS.md) for the full protocol.

> **The self-declared risk tier is an *input* to oversight, not the authoritative tier.** Jidoka requires the producer to surface risk first — but self-attestation is deliberately not trusted. Downstream, an independent `risk-assessor` re-derives the tier from the change itself and may only **raise** it, never lower it without explicit human concurrence (see Layer 2 / Pipeline Flow). The self-rating calibrates attention; it does not set the gate.

### Layer 2 — Multi-Agent Review Panel

Independent reviewers cover orthogonal risk axes. Cross-vendor decorrelation (Claude as author, agy/Gemini and codex/OpenAI as reviewers) reduces correlated failure modes. Each reviewer holds a specific lens:

| Lens | Concern | Signal type |
|---|---|---|
| Correctness | Logic errors, spec conformance, test coverage | correctness |
| Security | Injection, auth, multi-tenant isolation, credential handling | security |
| Privacy | PII handling, GDPR obligations, data minimization | privacy |
| IP / Provenance | License exposure, attribution, regurgitation risk | provenance |
| Maintainability | Coupling, abstraction altitude, future-reader clarity | quality |

Each lens is a **signal generator** for the oversight layer; *Maintainability* is a software-quality lens (a benefit and a signal source), the others are AI-code risk axes. An arbiter — the oversight layer acting on those signals — synthesizes findings into a structured verdict posted as PR review threads. Threads block merge until resolved — each finding requires a human decision, not just acknowledgment.

**Agent authority tiers** — four domains of delegated authority, each with a defined escalation ceiling:

| Tier | Agent | Decides | Escalates to |
|---|---|---|---|
| Human | — | Product vision, policy, unresolvable disputes | — |
| Architect | `architect` | All technical/architectural decisions | Human |
| PM | `pm-agent` | All product/requirements decisions | Human |
| UX Designer | `ux-designer` | All design system decisions — tokens, components, copy, feedback states | Human (structural brand changes only) |

`ux-designer` runs proactively at project start (audits the design pack against the full spec) and reactively during the build (fills gaps for coder, ui-reviewer, a11y-reviewer without requiring human escalation for additive changes).

### Layer 3 — Risk-Stratified Human Gates

Human attention is allocated by risk tier, not uniformly:

| Risk | Gate |
|---|---|
| LOW | Automated CI gates + statistical spot-check audit |
| MEDIUM | ≥1 cross-vendor reviewer; human reviews flagged items |
| HIGH | Security adversary always-on; human reviews line-by-line |
| CRITICAL | Blast radius required; human approval mandatory before merge |

The statistical spot-check on LOW-tier changes is not theater — it provides an ongoing escaped-defect rate, which is the primary feedback signal for calibrating the tier thresholds over time.

### Pipeline Flow

The three layers are not simultaneous — they operate in a defined sequence across two nested loops.

**Inner loop (per build step):** Blocking gates run first (lint, type-check, secret scan, security-HIGH). If gates pass, twelve **signal dimensions** score the change — complexity, N+1 queries, migration risk, IP/provenance, prompt fidelity, and others (some are software-quality proxies, some are AI-code-specific risk signals; the set is extensible — #80). The risk-assessor agent — the first stage of the oversight layer — aggregates these signals into a composite score and directs the internal review panel. It also **validates the coder's self-declared risk tier**: it reads the self-rating as untrusted input, independently re-derives the tier from the signals and the change, and can only **raise** it — never lower it without human concurrence. Its output records both sides of that judgment (`VALIDATED TIER: X (coder declared: Y, raised because: …)`), so an under-stated self-rating is corrected, not inherited. Each reviewer appends a structured sign-off to a shared register; the register is machine-readable and checked for completeness before the step advances.

**Transition (pre-PR):** Once all build steps pass system tests, a cross-vendor second review runs (agy at MEDIUM+, codex at HIGH+) producing a machine-readable verdict. The oversight-evaluator checks compliance (did all required sign-offs happen?) and quality (convergence failures, unresolved critical findings, confidence gaps), then issues one of three recommendations — PROCEED, CONDITIONAL_PROCEED, or ESCALATE. As an anti-gaming ratchet, the evaluator **independently re-derives the tier floor** (`change_classifier.py --tier-floor`) and fails compliance if the validated tier sits below it with no human override — so an under-computed tier is caught a second time. Both re-derivations run **only in the loosening direction**: raising the tier is always allowed; lowering it is guarded twice. The oversight-orchestrator acts on that recommendation and writes two separate outputs: `panel-context.md` (structural signals only, no internal findings) and `handoff.md` (full picture for the human). It then opens the PR or surfaces bounded questions to the human.

**Outer loop (per PR):** The cross-vendor panel reads `panel-context.md` only — deliberately isolated from internal review findings to prevent anchoring. The panel posts independent findings as PR review threads. Each thread blocks merge until it receives a human decision, not just an acknowledgment. The resolved audit trail is committed to `audit/oversight-log.jsonl` on merge.

For the full pipeline with script-level detail, see [METHODOLOGY.md](METHODOLOGY.md).

---

## Prompts as Artifacts

AI-generated code has a provenance problem: the prompt that produced it is usually invisible.

This framework treats prompts — and their summaries — as first-class source artifacts, version-controlled alongside the code they produce. Git commit trailers encode AI provenance:

```
Prompt-Artifact: prompts/auth/middleware.md
AI-Model: claude-sonnet-4-6
AI-Risk: HIGH
```

This makes the full AI contribution queryable (`git log --grep="Prompt-Artifact:"`), auditable, and reproducible — which matters for research, for IP review, and for any future regulatory context.

**Session summaries** are a second artifact class beyond individual prompt files. They serve two purposes. First, human comprehension: a reviewer should be able to read a summary and form a genuine judgment about whether a session did what it was supposed to do — without replaying every turn. Second, reproducibility: a well-formed summary is precise enough to serve as a one-shot prompt that regenerates the session's outputs, making AI-generated work reproducible in the same way source code is. A summary that diverges from the actual generated code is a provenance failure, not a documentation gap.

---

## Pipeline

The pipeline has three phases with different cadences:

### Inner Loop (repeats per incremental change)

```
PROMPT → AUTHOR + SELF-FLAG → BLOCKING GATES (lint · types · secret scan)
    └──── fix failures before next prompt ──────────────────────────────┘
         ↓
    RISK VALIDATORS (12 dimensions: complexity, N+1, migrations, IP, ...)
         ↓
    RISK-ASSESSOR AGENT → composite score + inspection brief
         ↓
    INTERNAL REVIEW PANEL → sign-off register
         ↓
    CAPTURE PROMPT ARTIFACT (MEDIUM+)
    └──── only proceed to next prompt on a clean, signed-off working tree ┘
```

Never prompt for the next incremental change on a broken working tree. Each prompt builds on the output of the last; unverified failures compound into a "house of cards" that is expensive to unwind.

### Transition Phase (once per feature, pre-PR)

```
COMMIT (with Prompt-Artifact / AI-Model / AI-Risk trailers)
  ↓
SYSTEM TESTS (gated by risk tier: e2e, coverage, mutation testing)
  ↓
SECOND REVIEW (agy at MEDIUM+, codex at HIGH+ — machine-readable verdict)
  ↓
OVERSIGHT-EVALUATOR
  Phase 1: compliance (sign-offs complete? prompt artifacts captured?)
  Phase 2: quality (convergence failures? unresolved critical findings?)
  → PROCEED / CONDITIONAL_PROCEED / ESCALATE
  ↓
OVERSIGHT-ORCHESTRATOR
  writes panel-context.md  (structural signals only — no internal findings)
  writes handoff.md        (full picture for human/PR)
  → opens PR  ·or·  surfaces bounded questions to human
```

### Outer Loop (once per PR)

```
PR (protected branch: ≥1 approval + all review threads resolved)
  ↓
CI CHEAP GATES (lint, types, build, tests, secret scan)
  ↓
AI PANEL (reads panel-context.md only — cross-vendor: agy + codex)
  ↓
ARBITER SYNTHESIS → PR threads
  ↓
HUMAN GATE (mandatory at HIGH / CRITICAL; threads block merge)
  ↓
MERGE → audit/oversight-log.jsonl (append-only)
```

---

## Framework Validation Suite

The framework validates its own agent definitions, documentation, and governance compliance before any commit. Four phases, run locally:

| Phase | Script | What it checks |
|---|---|---|
| 1 — Static | `check_agents_static.sh` | Agent file existence, path references, escalation targets — no AI, fast, CI-safe |
| 2 — Agents | `validate_agents.sh` | agy: consistency + completeness; codex: adversarial gaps |
| 3 — Docs | `validate_docs.sh` | Documentation coverage — omissions where agent file says X and Y but docs say only X |
| 4 — Spec Compliance | `validate_spec_compliance.sh` | Governance requirements vs. implementation: cross-vendor independence, risk tiers, human gates, model assignments |

Run all phases before committing:
```bash
bash scripts/framework/run_framework_validation.sh
```

Each successful run writes a timestamp to `scripts/framework/validation-stamps/`. The PR pipeline checks that the stamp is newer than all changed files — enforcing that validation ran locally without re-running AI models in CI.

---

## Multi-Agent Architecture Patterns

Several patterns have emerged across the empirical work:

**Separation of Concerns** — Each agent owns exactly one decision domain. All other decisions escalate. This prevents agents from reasoning outside their competence and makes failures legible.

**Bounded Iteration with Escalation** — Review cycles have a hard iteration limit (typically 5 rounds). Non-convergence is not an error state — it is a signal that the decision requires human judgment. The andon cord gets pulled.

**Spec as Source of Truth** — All inter-agent disputes are resolved by re-reading the specification with citation. Agents are explicitly prohibited from "spec falsification" — rationalizing code that doesn't meet the spec by reinterpreting the spec.

**Temp State Checkpointing** — Long-running pipelines write timestamped checkpoint files. Stale files (>24h) auto-delete. This prevents infinite loops and makes pipeline state inspectable without running the pipeline.

**Confidence Declarations as Calibration Signals** — Explicit uncertainty from the AI is an input to the human reviewer's prior. A fluent, confident output and a hedged output carry different review weights.

**Decisions as Artifacts** — Design decisions made in chat sessions are recorded in `scripts/framework/decisions.md` with verification criteria. Without this, decisions exist only in the session transcript and are invisible to future validation runs.

---

## Applying to a Project

**[CondoParkShare](https://github.com/ScottThurlow/CondoParkShare)** is the reference implementation — a real parking management app for condo communities, built to exercise HOS against genuine complexity (multi-tenant auth, booking logic, admin portals) while delivering something useful to an actual user community. It is the canonical example of what a HOS-governed project looks like end-to-end.

HOS installs into any project repository **from a validated release** — never from an arbitrary working copy. **Fast path: [docs/QUICKSTART.md](docs/QUICKSTART.md)** (three commands). Full walkthrough, customization, and project-start sequence: **[docs/SETUP.md](docs/SETUP.md)**.

**Get the bootstrap scripts** (one small folder; everything else is fetched from the release):

```bash
# Pull the latest release's bootstrap scripts to a fresh machine:
mkdir -p hos-bootstrap && cd hos-bootstrap
for f in hos_bootstrap.sh setup_clis.sh hos_install.sh; do
  curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/$f
done && chmod +x *.sh
# (optional) verify what you downloaded:
curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/SHA256SUMS
shasum -a 256 -c SHA256SUMS    # or: sha256sum -c SHA256SUMS
```

**Two steps** — machine once, then per project:

```bash
./hos_bootstrap.sh                                       # once per machine: Python/ScanCode/gh/pip + agent CLIs
./hos_install.sh --pack django /path/to/your-project     # installs the LATEST release + django stack pack
#   no stack depth:  ./hos_install.sh --no-pack          /path/to/your-project
#   pin a version:   ./hos_install.sh --release v0.3.0 --pack django /path/to/your-project
#   dev install:     ./hos_install.sh --local --pack django /path/to/your-project   (unvalidated)
```

`hos_install.sh` fetches the validated release and scaffolds a **full layered base agent team** (16 agents: pm-agent, architect, coder, the 8 reviewers, test, ops, ux) plus the oversight agents, validators, gates, and contract into the target. Each agent file has three regions — CORE (HOS-owned, stack-neutral), PACK (HOS-owned, stack-specific depth), and PROJECT (yours, never overwritten) — so your customizations survive upgrades. The installed version and selected pack are recorded at the target's `.hos-release` and `scripts/framework/config.sh`. If you have the repo cloned, run the same scripts from `bootstrap/`. For the region model and what to put where, see **[docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)**.

> Releases are cut with `scripts/framework/cut_release.sh`, which gates on the full validation suite before tagging and publishing the bootstrap assets.

**Contributing back.** If your project surfaces a framework gap — a missing feedback path, an agent behavior that doesn't hold for your stack, a contract requirement that conflicts with real usage — open an issue or PR here. Consumer projects are the empirical test of the framework; findings from real deployments improve the contract for everyone.

---

## Documentation

| Document | What it covers |
|---|---|
| **[METHODOLOGY.md](METHODOLOGY.md)** | Full methodology — theoretical basis, two-layer model, pipeline, risk model, tooling inventory |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Agent roster, pipeline diagrams, feedback loops, sign-off accountability map |
| **[AGENTS.md](AGENTS.md)** | Self-flagging protocol — the 5 mandatory behaviors every authoring agent must produce |
| **[docs/AGENTS.md](docs/AGENTS.md)** | Full pipeline agent documentation — all roles, models, escalation paths |
| **[docs/OVERSIGHT-RUNBOOK.md](docs/OVERSIGHT-RUNBOOK.md)** | Operational runbook — step-by-step commands for running the pipeline on each build step |
| **[docs/QUICKSTART.md](docs/QUICKSTART.md)** | Quickstart — three commands to get a project running |
| **[docs/SETUP.md](docs/SETUP.md)** | Installation guide — full walkthrough, configuration, project-start sequence |
| **[docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)** | Customization guide — adapting agents to a different stack or project |
| **[docs/COST-MANAGEMENT.md](docs/COST-MANAGEMENT.md)** | Cost & token-efficiency strategy — the deliberate decisions that control token spend, and the trade-off each one carries |
| **[research/](research/)** | Session logs and findings — the empirical record of what was built, what failed, and what was learned |

---

## Research Context

This framework is the subject of doctoral research examining how human oversight of AI-generated code can be made both rigorous and scalable. The empirical substrate is real software ([CondoParkShare](https://github.com/ScottThurlow/CondoParkShare)) built under the framework — not a controlled lab setting. The system is simultaneously the tool being studied and the instrument conducting the study.

The research draws on a systematic literature review of ~1,000 papers on AI code governance, multi-agent systems, and software quality assurance, and is grounded in three theoretical traditions described in the [Theoretical Basis](#theoretical-basis) section above.

**Core research constructs:**

**Escaped-defect rate** is the primary empirical measure. For any given risk tier, what fraction of changes that passed the full oversight pipeline contained a real defect? A falling escaped-defect rate over time is evidence that oversight calibration is working. A tier whose escaped-defect rate is consistently high indicates the tier thresholds are miscalibrated. This makes the oversight system empirically accountable rather than merely procedurally compliant.

**Risk-stratified attention allocation** is the central design hypothesis: human reviewers are most effective when their attention is routed by risk rather than applied uniformly. The research construct is the **allocation mechanism**, not the metrics that feed it — the framework operationalizes it by *aggregating* twelve signal dimensions into a composite risk score, applying deterministic floor rules for high-risk file patterns, and gating a tiered pipeline that escalates scrutiny proportionally. The signal dimensions themselves are replaceable inputs (several are ordinary software-quality proxies; the set is extensible — #80); the contribution is what the oversight layer *does* with them. The hypothesis is testable: does stratified allocation produce equivalent or better defect detection than uniform exhaustive review at lower human cost?

**Automation complacency as a structural constraint.** The framework is designed with the assumption that human monitoring performance degrades on low-signal repetitive tasks — a well-documented property of human-automation interaction (Parasuraman et al., 2000) rather than a failure of individual diligence. Risk stratification and explicit AI uncertainty declarations are direct responses to this constraint: they ensure that when a human reviewer's attention is required, it is required for a specific, bounded reason.

**Cross-vendor decorrelation** is the mechanism that makes multi-agent review genuinely independent rather than redundant. Different training distributions produce different failure modes. The empirical question is whether cross-vendor panels find defects that same-vendor review misses at a statistically significant rate — and whether that rate varies by defect type (correctness vs. security vs. spec drift).

**The self-governance property.** A governance framework for AI-generated code must itself be governed by that framework. This creates a recursive structure with practical implications: the framework's own agents, documentation, and pipeline are subject to the same oversight protocol as any other project. Findings from governing the framework feed back into the framework's design — a research instrument that improves itself.

Current empirical findings are documented in [`research/findings/`](research/findings/), including:
- Self-governance recursion (a governance system must govern itself)
- Omission-class documentation bugs (structurally invisible to contradiction checkers)
- Working-state invariant (inner-loop verification as a necessary property of incremental AI development)
- Tooling drift in validation pipelines (CLI API changes can silently disable validation)
- Stamp-based CI enforcement (committed artifacts as a bridge for local-only validation tools)
- Issue vs. PR thread routing (audit trail design as a data pipeline requirement)

**Dissertation committee:**
- Paul J. Thomas (Purdue) — IT systems, project management, cybersecurity
- Linda Naimi (Purdue) — Technology law, IP, ethics, generative AI legal implications
- Hancheng Cao (Emory Goizueta) — Computational social science, AI in development teams
- Kyubyung Kang (Purdue) — Machine learning and AI governance in safety-critical systems
- David Pistrui (Purdue) — Organizational transformation, Industry 4.0

---

## Status

| Component | Status |
|---|---|
| Self-flagging layer (Layer 1) | ✅ Implemented and in active use |
| Inner development loop (working-state invariant) | ✅ Implemented in agent protocol |
| Framework validation suite (4 phases) | ✅ Implemented — static + agy + codex + spec compliance |
| Validation stamp CI enforcement | ✅ Implemented — GitHub Actions, git commit timestamps |
| Cross-vendor review panel (agy + codex) | ✅ Operational — run on multiple PRs |
| Prompt artifacts and provenance | ✅ Implemented |
| IP / provenance agent (prompt-fidelity) | 🔧 Stub — semantic comparison not yet fully implemented |
| Statistical spot-check sampling | 🔧 Designed, sampling not yet automated |
| Expensive gate pipeline (e2e, coverage, mutation) | 🔧 Per-project; gates exist, automation varies |

Contributions, critique, and collaboration welcome.

---

## License

Dual-licensed by content type. Copyright Scott Thurlow 2026.

- **Code** (framework, scripts, tooling) — MIT License, see [LICENSE](LICENSE).
- **Documentation** (architecture/design docs, decision records, runbooks, planning and research notes) — [CC BY 4.0](LICENSE-DOCS): reuse and adapt freely with attribution.

Attribution is required for distributions. The research framing and framework design are Scott Thurlow's original work; collaboration and derivative builds are encouraged.
