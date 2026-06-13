# Decision Log — the History of the System

A running, dated record of the design decisions behind this oversight system and *why* they were made. This is the committed, versioned counterpart to the session memory — "the history of the system." It complements [`METHODOLOGY.md`](METHODOLOGY.md) (what the system *is*) by recording *how and why we got here*.

> Convention: newest sections at the bottom. Each decision notes the rationale, and a status where relevant: **✅ implemented**, 🔧 **designed/planned**.

---

## 2026-05-28 — Foundations

### D1. Purpose: scale human oversight of vibe coding
The system exists to make AI-code oversight **scale**: route human attention by risk rather than reviewing everything or trusting blindly. Mechanism: checks and balances across multiple, independent AIs, escalating to a human as risk rises.

### D2. VibeOversightDissertation is the master; apps are learning vehicles
This repo is the **system** and its single source of truth. Real apps (`tutelare`, `bt-parkshare`) are both deliverables *and* sandboxes that exercise the methodology; lessons learned here inform the system. Tooling is proven in an app context, then promoted into this repo. The apps own their own history; **this repo owns the history of the system.**

### D3. Two layers of oversight
- **Layer 1 — self-flagging (single agent)** ✅: the author AI flags its own work per [`AGENTS.md`](AGENTS.md) (risk tier, human-review flags, confidence, hallucination warnings, blast radius).
- **Layer 2 — independent review (multiple agents)** 🔧: cross-vendor reviewers check the author's work, scaled by risk, ending in a human gate. Rationale: an AI is poor at catching its *own* class of mistakes — independence decorrelates errors.

### D4. The AIs and why cross-vendor
- Claude (Max 20×): Opus = author; Haiku = triage/cheap review; Sonnet = arbiter.
- OpenAI (ChatGPT Pro) via `codex`: independent reviewer / adversary at high risk.
- Google (Gemini Pro) via `agy` (Antigravity): independent cross-vendor reviewer + breadth lens.
- GitHub Copilot (free): supplemental native PR review at medium risk and up.

Rule: **Opus authors, so Opus never reviews its own output.** At the highest risk the *independent* votes must be cross-vendor; same-vendor Claude tiers assist but don't count as the independent check.

### D5. Subscriptions, not API → the panel runs locally
Max / ChatGPT Pro / Gemini Pro are **app/CLI subscriptions, not API keys.** To use the quota we pay for, each reviewer runs through its subscription-authenticated CLI. Those CLIs auth interactively (browser OAuth on the local machine), which CI can't hold — so the cross-vendor panel runs from a **local** command and posts findings to the PR, while CI handles deterministic gates + Copilot. Rejected: paying metered API to run the panel in CI (double-pays the subscriptions).

### D6. Risk model and the scrutiny dial
Risk levels LOW / MEDIUM / HIGH / CRITICAL (per `AGENTS.md`) set how much scrutiny a change gets (self-flag/spot-check → cross-vendor reviewer + Copilot → security lens + line-by-line → adversary + blast radius + mandatory human). A **deterministic floor** (path globs, dep-manifest changes, diff size, coverage) the author can *raise* but can only *lower* with a second agent's or the human's concurrence.

### D7. Pipeline ordering — cheap and deterministic first
prompt → author + self-flag → capture prompt artifact (MEDIUM+) → commit w/ provenance trailers → PR → cheap deterministic gates → triage → expensive gates (risk-gated) → AI panel (local, posts to PR) → arbiter → human gate (conversation-resolution enforced) → merge → archive. Rationale: never spend an expensive reviewer on something a linter would reject.

### D8. Prompts as source code
Prompts = the "C source", generated code = the "compiled artifact"; the prompt should regenerate the code. Unlike a normal build, **both** are committed/versioned (the analogy governs provenance, not VCS policy). 🔧 A finer-grained append-only **raw** turn log + regenerable **summaries** + a **watermark** (resumable across sessions) is designed, not built.

### D9. Bootstrap scope — oversight tooling only
The bootstrap installs only what the oversight system needs (agent CLIs, their Node runtime, `gh`) — never project frameworks/libraries. Those stay with each project's own setup. Keeps the bootstrap portable and repo-independent.

### D10. Two distinct bootstraps
- `setup_oversight.sh` ✅ — bootstraps the protocol **into a repo** (AGENTS.md, CODEOWNERS, PR template, permissions, capture/audit, branch protection).
- `setup_clis.sh` ✅ — repo-**independent machine** bootstrap of the agent CLIs (install/auth/smoke/doctor). "Drop it in any repo, run it, it just works."

### D11. Antigravity migration
Google is retiring the Gemini CLI (consumer shutoff **2026-06-18**) in favor of the Antigravity CLI (`agy`). `setup_clis.sh` installs `agy` via Google's official installer (native Go binary, no Node). Auth is a **device-code flow** (`agy` has no `auth` subcommand; first interactive run triggers Google Sign-In); `-p/--print` verified for headless smoke.

### D12. PR policy — comments must be resolved to merge
`required_review_thread_resolution` enabled on protected `main` (in addition to ≥1 approval). This is what turns panel findings into review threads a human must address before merge — the human-attention routing mechanism.

### D13. Worked example — correct escalation on `curl | bash`
The agent tried to run the `agy` installer (`curl … | bash`); the repo's own `.claude/settings.json` policy **blocked** it and escalated to the human, who reviewed the (checksum-verified, user-scoped, no-sudo) installer and decided: **trust the vendor, keep autoupdate on for security patches.** A clean demonstration of a deterministic gate routing a genuine trust decision to a human, with the AI informing — not replacing — the call.

### D14. History/memory split
Oversight-**system** history lives with this repo (its session memory + this `DECISIONS.md`); **app** repos keep only app/user memory. Rationale: session memory is keyed by working directory, so the system's design history must live where the system is developed, for continuity.

---

## 2026-05-28 — Multi-agent panel design resolved

### D15. The panel (`run_panel.sh`) — four design decisions locked

The cross-vendor review panel (Layer 2, pipeline steps 7–10) is now specified. Four open questions resolved:

- **D15a — Diff handling: whole-diff, cap→chunk.** Send the whole PR diff to each reviewer by default; if it exceeds a token cap, split by file into chunks, review per-chunk, and merge findings. Keeps cross-file context in the common case; degrades gracefully on large PRs. Rejected: per-file-always (burns quota, loses whole-diff context) and changed-hunks-only (too little context for correctness review).
- **D15b — PR posting: a thread per finding + an arbiter summary.** Every finding becomes its **own line-level review thread**; the arbiter also posts one **summary comment** per run. Rationale: the panel is **adversarial**, so a finding isn't "done" when posted — it's done when the **author responds and the thread resolves**. A summary-only comment makes the author's responses untraceable; line-level threads (under `required_review_thread_resolution` on `main`, D12) force each finding to be addressed before merge. Noise is a non-issue because the panel only runs at **MEDIUM+** — LOW changes never reach it. This *supersedes* the earlier lean (summary always + threads only at HIGH/CRITICAL).
- **D15c — Trigger: manual first, hook later.** Ship as a manual local command (`./scripts/run_panel.sh [PR#]`); add an automatic trigger (git hook / `gh` alias / post-push) once the flow is proven. Lets us iterate without surprise CLI spend.
- **D15d — Findings I/O: best-effort JSON now, retry if flaky.** Ask each reviewer for a JSON findings schema and parse best-effort (tolerate prose wrapping); add re-prompt-on-parse-failure only if it proves unreliable in practice.

**Reviewer roster by risk (Opus is author → never reviews; refined by D18):** MEDIUM → 1 cross-vendor reviewer = **`agy`** (Antigravity's large context + breadth lens; conserves scarce ChatGPT Pro quota), lens: correctness. HIGH → `agy` (correctness) + `codex` (security) + `codex` (adversary/red-team), line-by-line. CRITICAL → same roster + blast-radius required + mandatory human gate. **Triage** = deterministic floor ∪ author `AI-Risk` trailer, confirmed/raised by **Haiku**; **arbiter** = **Sonnet** (synthesizes; not itself the independent check).

### D16. Copilot is the always-on baseline floor — on *every* PR (incl. LOW)

We want an AI code review on **all** PRs, not just MEDIUM+. The right tool for that floor is **GitHub Copilot**, not a Claude model:

- **Copilot reviews every PR automatically, in CI, for free of our subscription quotas.** It runs GitHub-native (repo ruleset / auto-request), so it covers even LOW changes that the local cross-vendor panel deliberately skips — without us driving it from `run_panel.sh` or spending Max/ChatGPT/Gemini quota. This *supersedes* the earlier "Copilot = supplemental, MEDIUM+ only" framing (D4): Copilot is now the **floor**, the cross-vendor panel is the **escalation**.
- **Why not Sonnet as the everyday reviewer?** Reaffirming D4: Opus is the author, so **no Claude model can be the independent check** — same-vendor review correlates errors. Sonnet stays **arbiter-only** (synthesizes the cross-vendor reviews; never casts one). The independent votes remain `agy` / `codex`.
- **Plan/cost (pilot):** **Copilot Pro at $10/mo** includes automatic code review on all PRs (Pro or Pro+ required; in an enabled repo Copilot reviews PRs regardless of author license). The metered constraint — not the $10 — is the premium-request quota: from **2026-06-01** each review costs a **13× multiplier** (~13 premium requests) and consumes GitHub Actions minutes, so Pro's ~300/mo allowance ≈ **~20+ PR reviews/month** (ample for a solo pilot; Pro+ at $39/mo if it ever exceeds that). Sources: GitHub Copilot docs/pricing + the 2026-04-27 changelog.

Net stack: **Copilot (all PRs, free-in-quota floor) → cross-vendor panel agy→codex→adversary (MEDIUM/HIGH/CRITICAL escalation) → Sonnet arbiter (synthesis) → human gate.**

### D17. Random red-team audit of lower-tier PRs (Statistical Quality Control)

In *addition* to the 100% adversary pass at CRITICAL, a **random sample of LOWER-tier PRs** (LOW/MEDIUM) gets an adversarial red-team pass. This operationalizes the SQC construct AGENTS.md already names ("CRITICAL gets 100% review, LOW gets spot-checked") — until now asserted but not enforced. Why it earns its place:

- **Audits the auto-pass lane.** The chief failure of risk-stratified review is a genuinely risky change *mis-triaged* low that then slips through on light scrutiny. Random deep review of low tiers catches — and *measures* — that tier leakage.
- **Produces an escaped-defect-rate metric.** Sampling the "we chose not to scrutinize" population yields an empirical estimate of surviving defects — the number that tells us whether the tier thresholds are calibrated. A dissertation finding, not just a feature.
- **Deters risk under-declaration.** If LOW is not a guaranteed free pass, the author AI can't reliably dodge scrutiny by under-calling risk.

**Selection — salted deterministic hash:** `selected ⇔ SHA256(head_sha + secret REPO_SALT) mod 100 < tier_rate`. Reproducible (an auditor holding the salt can prove a PR was/wasn't sampled — fits the provenance ethos) and non-gameable (salt is secret, so an author can't grind commit hashes to dodge it). Rejected: plain unsalted hash (author-computable → gameable) and pure per-run randomness (no auditable record). Salt lives in gitignored `.ai-local/sample.salt`; every decision is appended to `.ai-local/panel/sample-log.jsonl` (the SQC ledger / metric denominator).

**Rates:** production target **LOW 5% / MEDIUM 15%**. For the **pilot**, elevated to **LOW 25% / MEDIUM 50%** so the audit actually fires at low PR volume and we can observe the mechanism work end-to-end; dial back to 5/15 once proven (env-overridable via `OVERSIGHT_SAMPLE_LOW`/`OVERSIGHT_SAMPLE_MED`; `--no-sample` disables). Honest caveat: at pilot volume this is more deterrent + audit than a statistically powered estimate — the escape rate gains power as PR volume accumulates.

A sampled PR adds the `codex:adversary` lens and is transparently labelled in the PR summary ("🎲 Selected for random red-team audit"). Implemented in `run_panel.sh`.

### D18. Red-team is always-on at HIGH+ (not CRITICAL-only)

The initial roster (D15) gave the adversary/red-team pass only at CRITICAL — leaving **HIGH with correctness + security but no agent actively trying to break it.** That conflated scrutiny *volume* (HIGH already has two reviewers) with the *adversarial lens* specifically, and HIGH is exactly the tier defined by auth / input-handling / persistence / external-APIs — where adversarial thinking pays off most. Fixed: **the adversary pass now runs at HIGH and CRITICAL unconditionally.** This yields a clean monotonic ladder:

- **Red-team is _guaranteed_ at HIGH+** (always-on `codex:adversary`).
- **Red-team is _probabilistic_ below** (the D17 SQC sample at LOW/MEDIUM).

CRITICAL is no longer distinguished by *whether* a red-team runs (HIGH has one too) but by **blast-radius required + mandatory human approval**. Cost: one extra `codex` call per HIGH PR — acceptable, as HIGH is comparatively rare and the adversarial lens is highest-value there.

## 2026-06-02 — IP/provenance as a fourth risk axis

### D19. IP/provenance is a first-class panel agent (`ipcheck`), orthogonal to the risk tier

Vibe coding carries an **intellectual-property** risk the panel didn't cover: an LLM can emit code that is a verbatim/near-verbatim lift of copyrighted training data, drag copyleft (GPL/AGPL) or unknown-license code into a proprietary tree, or strip the attribution permissive licenses require. Crucially this is **invisible to every existing lens** — correctness/security/maintainability all read the code for *defects*, and IP-tainted code can be perfectly correct and secure. The cleaner and more idiomatic the output, the *more* likely it was regurgitated rather than synthesized — so good-looking code is a weak signal in the wrong direction.

**Decision:** add an **IP/provenance agent** to the panel as a peer reviewer (lens `ip`). Design choices locked:

- **A LOCAL built-in agent, not a vendor CLI.** Dispatched through `call_model` as `ipcheck`, backed by a function (`ip_agent`) we own — so its brain can grow without re-wiring the panel. It emits the same `{"findings":[...]}` schema every reviewer uses, flowing through the existing arbiter → thread machinery for free.
- **Runs on every panel invocation** (MEDIUM+, and LOW when sampled). IP exposure is *orthogonal* to the security/correctness tier, so it isn't gated by it. (Future: extend to LOW too, which the panel currently exits before reaching — noted, not yet built.)
- **Ships as a deliberate placeholder (`IP_STUB=1`).** v0 performs no analysis and returns a clean verdict — "start stupid, says it's ok." To prevent false assurance, a no-op clean result is **explicitly flagged in the panel summary as NOT an IP clearance.** A stub that quietly looks like a green light would be worse than no agent.
- **Growth path (function-local, interface stable):** (1) deterministic license gate on changed dependency manifests + vendored files (copyleft/unknown → tier1/tier2); (2) attribution check for copied permissive-licensed code; (3) similarity/LLM regurgitation lens. Flip `IP_STUB=0` once a real step lands to drop the caveat.
- **The pipeline surfaces IP exposure; it does not adjudicate it.** Like security risk, an ELEVATED finding routes to a human — and specifically to *counsel*. This is not legal advice. The **prompt-as-source artifact (D8) doubles as clean-room counter-evidence**: code regenerable from a spec that never said "copy library X" is documentary provenance.

### Still open / pending
- **IP agent Level 3** 🔧 — regurgitation lens via ai-gen-code-search (D20); activate once API access obtained.
- **Raw archive + watermark** 🔧 — the append-only turn log + regenerable summaries (D8).
- **`risk_tier_resolver.py`** 🔧 — deterministic script that validates final risk tier vs. coder declaration and manifest baseline; enforces "never lowers" invariant mechanically (D22).
- Windows support in `setup_clis.sh`.

---

## 2026-06-11 — HOS Framework Bootstrap

### D20. IP agent activation — Levels 1 and 2 now functional; Level 3 architecture clarified

`IP_STUB=0` is now the default. `scripts/oversight/validators/ip_check.py` implements:
- **Level 1 ✅**: dependency license gate. Uses ScanCode Toolkit (full text comparison against license database) when installed; falls back to PyPI/npm API. ScanCode is auto-installed by `install.sh` with platform-aware system deps (libmagic).
- **Level 2 ✅**: prompt clean-room verification. Reads captured prompt artifacts (`Prompt-Artifact:` git trailers → `prompts/` directory). Flags attribution triggers ("based on", "copy from"); notes clean-room signals (spec-only sourcing).
- **Level 3 🔧**: regurgitation stub. ai-gen-code-search (AboutCode) is **not** a standalone pip install — it requires deploying PurlDB + MatchCode + ScanCode.io as a service stack. A hosted evaluation system exists; research API access requested via hello@aboutcode.org. The stub is an explicit placeholder with `integration_active: False`.

ScanCode is the right tool for Level 1; ai-gen-code-search is the right tool for Level 3 because it uses LSH to match against a FOSS code index — the open, auditable instantiation of the oversight control point this research studies.

### D21. Prompt artifact integration as a first-class risk dimension

Prompt artifacts (DECISIONS.md D8) are now integrated into the validation pipeline at three points:

1. **Evaluator compliance** (Phase 1): MEDIUM+ commits must have `Prompt-Artifact:` git trailers. Missing trailers → COMPLIANCE WARN; missing referenced file → COMPLIANCE FAIL.
2. **Panel context / authoring intent** (oversight-orchestrator): `step{N}-panel-context.md` now includes an "Authoring Intent" section — what the code was *asked* to build. Panel reviewers use this to check intent vs. implementation independently.
3. **Risk-assessor Phase 2**: `prompt_audit_risk.py` scores prompt ambiguity (question density, hedging language, TBDs, process signals) and fidelity surface (code/prompt ratio, unmentioned functions). `prompt-fidelity` subagent (semantic) runs at MEDIUM+.

Rationale: the prompt is the "C source" (D8); the generated code is the compiled artifact. Auditing the prompt for ambiguity and comparing it to the code for fidelity are the two dimensions no existing static analysis tool covers for AI-generated code.

### D22. Panel context / handoff split — independence invariant enforced in code

The oversight-orchestrator now writes two distinct files:
- `step{N}-panel-context.md` — structural risk signals only (RN scores, probe targets, spec sections, authoring intent). No internal reviewer findings.
- `step{N}-handoff.md` — full picture for the human/PR: internal review summary, second review findings, human authorization notes.

`run_panel.sh` loads ONLY `panel-context.md`. Falling back to `handoff.md` is explicitly blocked (was previously a warning; now fails closed with a message). The section label in the reviewer prompt is "## Structural Panel Context" — not "handoff" — to prevent psychological anchoring.

Rationale: if cross-vendor reviewers see what the internal team found and resolved, they anchor to it and lose their independence value. The whole point of cross-vendor review is decorrelated judgment.

### D23. Audit trail design — current branch, dual format

The committed audit trail (`audit/`) lives on the **current branch** rather than a separate audit branch. Evidence about code travels with the code through git history. Two complementary formats:
- `oversight-log.jsonl` — append-only, one JSON event per line, machine-queryable via `jq`. Never too large at project scale (~50KB for a full 11-step build).
- `YYYY-MM-DD-step-{N}-{name}-{TIER}.md` — timestamped human-readable per-step summaries. Browsable by `ls`; tier in filename for instant visual scan.

Research value: the JSONL is the longitudinal empirical substrate for the dissertation — escaped-defect rate, sign-off patterns, risk tier accuracy, human escalation frequency.

### D24. Self-review tooling — cross-vendor validation of the framework itself

`review_self.sh` and `reverify_self.sh` implement a two-vendor review loop:
- `review_self.sh --reviewer agy|codex` — sends the full HOS context bundle (~37k tokens) to agy or codex for independent review
- `reverify_self.sh --reviewer agy|codex` — sends a targeted diff + original findings + rebuttals (~5k tokens) for re-verification

The framework was reviewed by both agy and codex before the initial PR, with findings iterated to resolution. This is the methodology applied to itself: cross-vendor, independent, decorrelated review of the oversight system that performs cross-vendor review.

Token cost for two full rounds: agy ~4% of $20/month; codex ~45% of $20/month reserve. Worth noting the codex reserve is meaningfully consumed by self-review and should be budgeted as a one-time framework cost.

### D29. Gate suspension for brownfield onboarding — human-only manifest, per-reviewer granularity (2026-06-12)

When HOS is applied to an existing codebase, all gates fail simultaneously. A blanket bypass would defeat the governance purpose; no bypass would make HOS unusable for brownfield adoption. The resolution: a bounded, human-authorized suspension with a re-enable-one-at-a-time discipline.

Key decisions:
- **Human-only manifest** (`contract/gate-suspension.md`) — same flag-file pattern as human-authorization files. Agents cannot create or modify it. Creating it without authorization is a protocol violation.
- **Per-reviewer granularity** — suspend exactly the reviewers that fail, not all reviewers. This matches how remediation actually works: you fix one domain, re-enable that reviewer, move to the next.
- **Committed to git** — the suspension file is in version control. The git log shows exactly when each gate was suspended, when it was re-enabled, and who authorized it.
- **Invariant: re-enabled gates stay on** — once a reviewer is re-enabled, it must not be re-suspended. Any failure after re-enablement is a regression that must be fixed, not bypassed.
- **Same names as role_mappings** — gate script names (`lint`, `security`, etc.) match the step-manifest `required_signoffs` role keys where applicable, so one suspension entry covers both the script gate and the sign-off gate for the same domain.

Rationale: the mechanism's value is not just that it unblocks brownfield projects — it's that it creates a forcing function for systematic debt elimination. Each re-enable records that a domain is clean. The re-enable log becomes an audit trail of remediation progress.

### D25. Observability review follows the ux-designer / ui-reviewer pattern — separate spec authorship from spec enforcement (2026-06-12)

Two new agents added: `ops-designer` (spec author) and `ops-reviewer` (spec enforcer). This mirrors the ux-designer / ui-reviewer pattern exactly:

| Concern | Spec author | Spec validator | Per-PR enforcer | Spec artifact |
|---|---|---|---|---|
| UX / interaction | `ux-designer` | `pm-agent` | `ui-reviewer`, `a11y-reviewer` | `UX-DESIGN-READINESS.md` |
| Observability | `ops-designer` | `architect` | `ops-reviewer` | `TELEMETRY-SPEC.md` |

Rationale: a human architect confirms observability coverage is adequate at the architectural level — trust boundaries instrumented, critical paths observable — but does not author the granular event taxonomy, metric naming conventions, or dashboard specifications. That level of detail belongs to dedicated observability expertise.

Both agents are optional — N/A for projects without background jobs, external integrations, or multi-service architecture.

### D26. AI disclosure enforcement — from rule-in-prose to template + constraint (2026-06-12)

The AI PR disclosure requirement (`[AI: agent-name]` title prefix + `## 🤖 AI-Submitted Pull Request` block) was defined in `oversight-orchestrator.md` but violated in practice: CondoParkShare's Claude submitted PRs without it. Root cause: the rule existed only in the orchestrator agent file and was invisible to other PR-creation paths.

Fix: three-layer enforcement — PR template (visible at PR creation point), `docs/AGENTS.md` universal rule, `oversight-orchestrator.md` non-negotiable constraint.

Rationale: rules that are not mechanically surfaced to the agents that must follow them will be missed. The template is the mechanism — any agent opening a PR via `gh pr create` will encounter it.

### D27. Install-time placeholder substitution — perl for cross-platform in-place edit (2026-06-12)

Agent files contain `{SPEC_FILE}`, `{DESIGN_PACK_DIR}`, and `{PROJECT_NAME}` placeholders. `install.sh` now substitutes them after copying agent files using `perl -i`, chosen over `sed -i` because `sed -i` has different syntax on macOS vs. Linux. Substitution only touches files containing at least one placeholder (grep check before perl), making it safe to run idempotently.

### D28. Self-directing agent prompts over static content replication (2026-06-12)

`ux-designer.md` contained a hardcoded CondoParkShare feature audit list. Instead of replacing with a `{FEATURE_AUDIT_LIST}` placeholder, the instruction was changed to "walk every user-visible feature in `{SPEC_FILE}`" — the agent derives the list at runtime. Self-directing instructions are more durable than static content: they track the spec as it evolves, require no substitution, and produce more thorough audits.

### D30. Human authorization artifacts are agent-read-only (2026-06-12)

All human authorization artifacts (`.claudetmp/oversight/step{N}-human-authorization.md`, `human-tier-override.md`) may only be created or modified by a human. Agents are explicitly prohibited from creating or modifying these files, even to unblock a pipeline stall. The prohibition is stated as a hard constraint in `oversight-evaluator.md` and `risk-assessor.md`.

This decision was originally deferred as "behavioral enforcement only" with a note to revisit mechanical enforcement. The stronger mechanical approach (signed GitHub comments, protected branch approvals) is desirable but blocked by the current limitation that all PRs appear to come from the same GitHub account regardless of whether they were AI- or human-submitted — making signature-based verification impractical until that identity problem is resolved. Tracking as an open design issue for future revision.

### D31. risk-historian is a raw data retriever — risk-assessor classifies (2026-06-12)

risk-historian previously produced a LOW/MEDIUM/HIGH classification in its output, which violated REQ-004 (no Haiku for judgment calls). Split into two concerns: risk-historian retrieves raw counts and issue references (upgraded to Sonnet for better retrieval quality); risk-assessor applies the risk classification using that data. risk-historian output now includes a `Data confidence` field (HIGH/MEDIUM/LOW) covering pagination completeness and rename history tracking.

### D32. Notification artifacts for inter-agent communication (2026-06-12)

Inter-agent notifications ("notify ui-reviewer", "notify ops-reviewer") previously relied on chat context, which is lost when sessions end or context windows are exceeded. Added a durable notification artifact protocol to `contract/OVERSIGHT-CONTRACT.md`: agents write `.claudetmp/notifications/step{N}/{from}-to-{to}-{ts}.md` with required fields (Step, From, To, Changed, Reason, Blocking, Required action, Acknowledged). The receiving agent fills in the Acknowledged field when it has acted. This makes notifications session-boundary-safe.

### D33. Independent re-derivation of loosening determinations — the self-classification gate cannot be policed by the classifier (2026-06-13)

Two upstream determinations could *loosen* oversight without a human: an authoring agent classifying its own change `additive`/`clarifying` (only `structural` escalates), and post-change-sweep writing `Status: N/A` to waive a reviewer. In both cases the actor being governed is also the judge, and nothing audited the judgment (issues #74, #75). Tightening the prose definitions — done repeatedly — treats the symptom; the structural fix is an *independent* re-derivation from the diff.

Added `scripts/oversight/change_classifier.py` (deterministic, stdlib-only): it reports which reviewer domains a diff actually touched (#74) and detects mechanical **structural-override signatures** — new external dependency, new permission/auth state, new user-facing surface/route, new user-facing state enum (#75, contract §2a). The `oversight-evaluator` runs it in Phase 1: an N/A for a domain the diff touched fails compliance; a structural-override signature with no covering human-authorization artifact fails compliance and escalates. Self-classification is now auditable — mislabeling a structural change as additive no longer bypasses the human gate.

Two deliberate design choices:
- **Verify only in the loosening direction** (the ratchet applied to verification cost). If upstream asked for *more* review — a real sign-off, an `ESCALATED` status, a `structural` label with authorization, a cleared human gate — there is nothing to guard against, so the evaluator skips the re-derivation entirely. We pay the cost only when a determination would reduce scrutiny.
- **Bias the detector to over-detect.** The signatures are a floor; a false positive merely sends a benign change to a human (safe), while a false negative is the only real failure. Projects may extend the signatures for their stack but may not narrow the base set.

Escapes are logged as audit events (`na-invalidated`, `structural-override`, the latter even when the human gate caught it) so the misclassification rate becomes measurable research data rather than a silently-blocked event.

### D34. Self-review-driven hardening of the re-derivation work, and a parser-robustness fix (2026-06-13)

The Opus self-validator, run on the #74/#75 PR before any external budget was spent, surfaced five findings — proof the pre-external self-review earns its place. Four were acted on in the same PR (the fifth, the shared-identity ratchet limitation, was filed as #82 because it needs the separate-identity work D30 tracks):

- **The CRITICAL human gate was keyed off the mutable manifest flag `human_gate_required`, not re-derived from the validated tier** (blocking). `risk-assessor` ratchets the tier but nothing ratcheted the flag, so a re-derived-CRITICAL step with `human_gate_required: false` would skip the hard human gate. Fixed: the evaluator now fires the gate on `manifest.human_gate_required OR validated_tier == CRITICAL` (contract §7 condition 7). This is the same anti-gaming principle as conditions 9–10 — the most important loosening determination must itself be re-derived, not trusted.
- **The tier-gated compliance layer silently no-ops if `risk-assessment.md` is absent.** Added a check (§7 condition 7a): a missing assessment falls back to `max(manifest tier, MEDIUM)` and a COMPLIANCE WARN, so an undetermined tier can never downgrade the MEDIUM+ checks to nothing.
- **The agent prompts over-claimed coverage** ("it will be caught"). The mechanical re-derivation only detects structural changes that *add* a §2a signature; a change that *modifies existing behavior* adds none and is not caught. Scoped the claim honestly in ux-designer, ops-designer, and contract §2a (residual-coverage note) — those changes rely on honest classification plus reviewer/panel detection.

Separately, a **parser-robustness fix in `validate_self.sh`**: the finalize step matched findings with a strict `​```json{...}​```` regex, which failed when the model emitted prose inside the fence (an adversarial-review preamble), misreporting a review-with-findings as `verdict=error`. Replaced with a string-aware balanced-brace extractor that tolerates prose and ignores braces inside JSON strings (finding descriptions contain literals like `step{N}-...`). Without this, every self-review whose model wrapped its JSON in commentary would silently lose its findings.

### D35. doc-validator is a fixer, and the fix-in-place/file-an-issue triage is codified once (2026-06-13)

The Opus self-validator escalated a blocking finding at the 3-pass cap: `doc-validator` was documented as a fixer ("applies fixes directly — you have Write access to doc files") but its frontmatter granted only `Read, Bash, Grep, Glob`. At runtime it could write nothing, and since `framework-validator` "cannot directly invoke doc-validator," a MUST_FIX doc omission had no agent that could both detect and apply the fix — a dead end.

Human decision (the cap escalated to a human by design): make `doc-validator` a real fixer that **iterates and fixes like the coder**, under an explicit triage, rather than a report-only validator. Granted it `Write` + `Edit` (matching `ux-designer`, which edits the docs it owns).

Rather than write the triage into one agent, codified it once as **contract §6.0 — the fixer triage** — the rule every detect-and-correct agent shares:
- **Mechanical / local / unambiguous → fix in place, file nothing** (issues feed risk scoring; mechanical fixes would be noise). This is the inner loop.
- **Structural / design / judgment → file an issue and escalate** (design instability is real risk; it must reach a human or owning agent).
- **Direction guard (ratchet):** a fix may only correct *toward* the authoritative source (doc ← agent definition), never *up* the authority gradient or in a loosening direction — those are structural by definition.
- **Cap:** bounded fix-and-rerun cycles (default 3); recurrence past the cap escalates to a human.

This is one boundary the system already instantiated in several places (coder inner loop, self-review capped-iterate, doc-validator loop-exit, change-type classification, risk-assessor tier floor); §6.0 names it so a new fixer inherits it instead of approximating it. See `research/findings/fixer-triage-inner-loop-boundary.md`. This was itself a case of the pipeline working: the pre-external self-review caught the contradiction, the cap routed the design choice to a human, and the resolution generalized.

### D36. Install from a validated release, and split machine-bootstrap from project-install (2026-06-13)

Two coupled decisions about the installer, driven by the move to batched validation (main is now an integration trunk, not a guaranteed-shippable artifact — see the release-branch/tag discussion).

**1. Install from a release, not the local working copy.** `bootstrap/hos_install.sh` now fetches a **validated release** by default (latest GitHub release, or `--release <tag>`) and scaffolds the target from that, rather than copying whatever happens to be in the local tree. With batched validation the local copy is not guaranteed shippable, so a release is the reproducible, known-good artifact — important because HOS is a research instrument: a CPS experiment must run against a *defined* framework version. Fetch order: local `git archive` of the tag (fast/offline) → GitHub tarball via `gh`/`curl`. `--local` installs the working copy for development (clearly flagged unvalidated). The installed tag is recorded at the target's `.hos-release`. If no release exists yet, the installer refuses (pointing to `--local`) rather than silently installing an unvalidated tree.

**2. Split machine bootstrap from project install, in a `bootstrap/` folder.** The uber `install.sh` did two jobs with different lifecycles (once-per-machine vs once-per-project), privileges (sudo vs none), and frequencies — the `--machine-only`/`--project-only` flags were the tell. Split into:
- `bootstrap/hos_bootstrap.sh` — machine prerequisites (Python, ScanCode, gh, pip) + agent CLIs (delegates to `bootstrap/setup_clis.sh`). May need sudo. Once per machine.
- `bootstrap/hos_install.sh` — project install from a release. **No sudo, no system installs**; it *checks* prerequisites and points back to the bootstrap if any are missing, keeping the privilege boundary clean.

`bootstrap/` is the copy-to-machine bundle — the only thing a user copies to a machine; everything else (agents, validators, contract, docs) is fetched from the release. The SQC sampling salt (`.ai-local/sample.salt`) moved from the HOS repo into the *target* project, where it is actually used (fixing a pre-existing quirk). `setup_clis.sh` moved from `scripts/` into `bootstrap/`; references in installed scripts (`reverify_self.sh`, `framework-setup-validator`) were generalized since a target project does not carry the machine bootstrap. The legacy `scripts/setup_oversight.sh` is superseded by `hos_install.sh` (full reconciliation tracked separately).
