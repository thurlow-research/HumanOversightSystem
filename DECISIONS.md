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
- Claude (subscription): Opus = author; Haiku = triage/cheap review; Sonnet = arbiter.
- OpenAI (ChatGPT) via `codex`: independent reviewer / adversary at high risk.
- Google (Gemini) via `agy` (Antigravity): independent cross-vendor reviewer + breadth lens.
- GitHub Copilot (free): supplemental native PR review at medium risk and up.

Rule: **Opus authors, so Opus never reviews its own output.** At the highest risk the *independent* votes must be cross-vendor; same-vendor Claude tiers assist but don't count as the independent check.

### D5. Subscriptions, not API → the panel runs locally
Claude / ChatGPT / Gemini are **app/CLI subscriptions, not API keys.** To use the quota we pay for, each reviewer runs through its subscription-authenticated CLI. Those CLIs auth interactively (browser OAuth on the local machine), which CI can't hold — so the cross-vendor panel runs from a **local** command and posts findings to the PR, while CI handles deterministic gates + Copilot. Rejected: paying metered API to run the panel in CI (double-pays the subscriptions).

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

**Reviewer roster by risk (Opus is author → never reviews; refined by D18):** MEDIUM → 1 cross-vendor reviewer = **`agy`** (Antigravity's large context + breadth lens; conserves scarce OpenAI subscription quota), lens: correctness. HIGH → `agy` (correctness) + `codex` (security) + `codex` (adversary/red-team), line-by-line. CRITICAL → same roster + blast-radius required + mandatory human gate. **Triage** = deterministic floor ∪ author `AI-Risk` trailer, confirmed/raised by **Haiku**; **arbiter** = **Sonnet** (synthesizes; not itself the independent check).

### D16. Copilot is the always-on baseline floor — on *every* PR (incl. LOW)

We want an AI code review on **all** PRs, not just MEDIUM+. The right tool for that floor is **GitHub Copilot**, not a Claude model:

- **Copilot reviews every PR automatically, in CI, for free of our subscription quotas.** It runs GitHub-native (repo ruleset / auto-request), so it covers even LOW changes that the local cross-vendor panel deliberately skips — without us driving it from `run_panel.sh` or spending Claude/ChatGPT/Gemini subscription quota. This *supersedes* the earlier "Copilot = supplemental, MEDIUM+ only" framing (D4): Copilot is now the **floor**, the cross-vendor panel is the **escalation**.
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

### D37. Signal layer vs. oversight layer — the research subject is acting on signals, not generating them (2026-06-13)

Issue #72 surfaced a comingling bug in the conceptual docs: software-quality checks (cyclomatic/cognitive complexity, N+1, function metrics, portability) were presented *alongside* the oversight machinery as if they were the research contribution. They are not. The fix is a framing, applied **in place** across the docs rather than extracted to a new document.

**The model.** HOS is a two-layer pipeline:
- **Signal layer** — validators and reviewers that *measure or detect* something about the AI-generated code and emit a signal (quality: complexity, N+1, coverage, reliability; plus security, correctness, IP/provenance, prompt-fidelity, hallucination).
- **Oversight layer** — *acts* on those signals: aggregates them into the composite, stratifies into tiers, routes human attention, gates merges, escalates, ratchets, audits.

**Decision:** the research subject is the **oversight layer** — how aggregated signals become *scaled human oversight*. Consequences locked into the docs:

- **Quality checks are a signal source and a benefit, not the research claim.** Running them makes the product better — a real byproduct — but the contribution is the routing-of-attention over the aggregate. Swap any quality proxy for another and the oversight contribution is unchanged. (METHODOLOGY §5 carries a `Signal type` column tagging all twelve dimensions; five are `quality`.)
- **The signal set is extensible (#80).** A project registers its own signal generators and the oversight layer consumes them unmodified. The framing must not hard-code the current twelve as definitional.
- **Count reconciliation.** The docs said "nine validators" in some places and "twelve" in others. The truth: **eleven validator scripts produce twelve scored dimensions** (`complexity_metrics.py` emits both cyclomatic and cognitive). All mentions standardized.
- **Findings carry a `Role:` header.** Each `research/findings/*.md` now declares `signal-generation` / `oversight-mechanism` / `both`, so the corpus is self-classifying about what is the research subject vs. an engineering benefit. Two findings (`install-time-placeholder-substitution`, `working-state-invariant`) are explicitly tagged engineering-benefit, not oversight-research.

**Precedent.** This is the same orthogonal-axis move as **D19** (IP/provenance is a first-class axis orthogonal to the risk tier): there we separated a distinct *signal* from the tier it doesn't belong to; here we separate the whole *signal layer* from the oversight layer that acts on it. The principle is consistent — name the axes, don't conflate the thing measured with the thing that acts on the measurement.

### D38. Oversight gates target the operator's environment: bash 3.2 floor + venv-resolved tools (2026-06-13)

The CPS real-world run showed the gates failing on a real operator machine while CI stayed green (HOS#101/#102, and the dep case #73/#74). CI runs a generous superset of the operator's environment (newer bash, all tools global), so it is structurally blind to absence-dependent failures. Standard for every gate/validator script going forward:

- **bash 3.2 portability floor.** macOS ships bash 3.2; the gates must run there. No `mapfile` or other bash-4-isms — use portable `while IFS= read -r` loops. The framework's own `portability_check.sh` is pointed at its own scripts.
- **Resolve tools through the oversight venv, never bare `PATH`.** Use `$VENV_BIN/<tool>` and `$OVERSIGHT_PYTHON` (source `ensure_venv.sh`). `command -v <tool>` finds CI's global install but not the operator's venv, silently downgrading the gate (e.g. `secret_scan.sh` fell back to a weak grep and reported a pass).
- **Declare every imported dependency** (D-adjacent to #73/#74): a transitively-present dep is an undeclared invariant.
- **A real-world install test is a first-class oversight checkpoint**, not an integration nicety — it is the only place this class of oversight-instrument failure is observable. See `research/findings/ci-is-blind-to-consumer-environment-failures.md`.

This is the same re-derive-don't-trust principle (D33/D37) applied to the gates' runtime: don't trust "green in CI" as evidence the instrument runs where the human runs it — prove it in the field.

### D39. Release-type-scoped self-validation — full corpus for major, incremental for minor/patch (2026-06-13)

The framework's release-gate self-review (`validate_self` + cross-vendor `validate_agents`) reviews the **entire governance corpus** adversarially. On a rich corpus an adversarial reviewer **converges on zero-NEW but never zero** (`research/findings/nondeterministic-review-gate-converges-on-zero-new.md`): it keeps surfacing *real, pre-existing* holes. Cutting v0.1.1 demonstrated this — ~14 genuine findings surfaced during the cut, **none of them regressions of the release's own diff**; several had shipped undetected through prior releases. Gating a **patch** on "zero findings across the whole corpus" therefore never passes.

**Decision:** scope the release-gate review by version bump.
- **MAJOR (X.0.0)** → full-corpus self-review + cross-vendor. A major release is the point to re-validate everything.
- **MINOR / PATCH** → incremental: `--changed-only --base <last release tag>`, so the gate reviews only the files the release changed. The correct convergence bar for a patch is **"zero-NEW since the release diff,"** not "zero in the corpus."

Implemented via a `--base <ref>` option threaded through `validate_self.sh`, `validate_agents.sh`, and `run_framework_validation.sh`; `cut_release.sh` selects the scope from `$BUMP`. The full-corpus sweep does not disappear — it moves **off the release critical path** to a continuous async backlog job (#131) that files NEW findings as tracked issues (ledger-deduped so the same finding is never re-filed). Trade-off (stated explicitly): incremental can miss a finding arising from an interaction with an *unchanged* file; the daily full sweep is the safety net. See #130/#131. This is the ratchet applied to validation cost — pay full re-validation when the blast radius is largest (major), pay incremental otherwise.

### D40. Missing risk-assessment is a hard COMPLIANCE FAIL, not WARN + auto-fallback (2026-06-14)

Corrects a stale entry earlier in this log (the §7 condition 7a description stating a missing `risk-assessment.md` "falls back to `max(manifest tier, MEDIUM)` and a COMPLIANCE WARN"). That auto-fallback was later hardened and the log was not updated. Per `contract/OVERSIGHT-CONTRACT.md §7a` and `.claude/agents/oversight-evaluator.md`: **absence of `risk-assessment.md` on a per-step build evaluation is a COMPLIANCE FAIL** — the evaluator cannot substitute for risk-assessor's deterministic floor, required-reviewers set, prompt-fidelity, dep-mapper, and risk-historian, so it **fails closed** (the safe/ratchet direction). The `max(manifest, MEDIUM)` fallback is permitted **only** under an explicit human-authorization artifact (brownfield/emergency — the same human-only class as `human-authorization.md`); without it, absence is a hard fail. Surfaced by the 2026-06-14 self/3p eval (agy), which caught the stale WARN+fallback wording contradicting the hardened contract (#180). Append-only log corrected here, not by editing the prior entry.

### D41. Oversight tooling must fail honestly and through one invocation site (2026-06-14)

The v0.2.0 release gate's final pass returned **zero findings that were a non-review** — both cross-vendor reviewers were silently non-functional (HOS#201). Two root causes, one shared failure signature:

- **codex (#199):** `run_second_review.sh` still called the long-removed `codex --quiet` (the CLI moved to `codex exec` months earlier, HOS#0612 fix). The call always failed; `2>/dev/null || echo '{…error…}'` masked it as an empty `verdict:error`.
- **agy (#113):** agy has no JSON-output mode and intermittently returns **prose narration** instead of JSON. Same masked-empty result.

In both cases **a broken reviewer produced output indistinguishable from a reviewer that ran and found nothing** — the worst failure mode for an oversight instrument (it silently reports "all clear"). Standard going forward:

1. **Honest degradation.** A reviewer that did not actually review must emit a **distinct, loud error** (`review NOT performed`), never a silent empty pass. The `|| echo '{"error":…,"findings":[]}'` idiom is banned where the "error" object is downstream-indistinguishable from "no findings." Implemented in `run_second_review.sh`: salvage the first balanced JSON object from any prose wrapper, retry agy once with a hard JSON-only reinforcement, then fail with a distinct error.
2. **Defensive parsing for non-deterministic CLIs.** Agentic CLIs (agy) have no contractual output format; you cannot pin your way out. Salvage + bounded retry is mandatory, not optional.
3. **One invocation site per external tool (the durable fix).** The drift recurred because `codex --quiet` lived at *many* call sites and each fix patched only the ones in front of it (the 2026-06-12 fix hit three `validate_*.sh`; #199 hit a fourth; an audit then found four more — `run_red_team.sh`, `run_redteam_sample.sh`, `capture_session.sh`, `framework/validate_scripts.sh`). Decentralized invocation turns one upstream API change into N independent *silent* failure sites. Target state: a shared `run_review_cli()` helper + a startup canary smoke test, so drift is a one-line fix in one place and fails fast and visibly. Tracked as the #201 follow-up.

See `research/findings/tooling-drift-in-validation-pipelines.md` (2026-06-14 update). This is the third member of the "looks reviewed, wasn't" family, alongside *reviewer is wrong* and *pipeline is unused*.

### D42. The v0.3.0 base-agent team is authored, and §A8's iterating-role scope is deliberately narrow (2026-06-15)

HOS v0.3.0 ships a canonical **base-agent team** as layered CORE/PACK/PROJECT files — 15 roles across 16 files (`pm-agent`, `architect`, `technical-design`, `coder`; the eight reviewers `code/security/privacy/reliability/ops/ui/a11y/infra`; `unit-test` + `system-test`; `ops-designer` + `ux-designer`). They were authored **spec-first** (pm-agent wrote `docs/v0.3.0/BASE-AGENTS-SPEC.md`, human-resolved O1–O4) and **dogfood-built** by HOS's own borrowed pipeline, then run through the deterministic gates (`regions.py validate` + `--placeholder-keys`, `check_agents_static.sh`) and the product's own new `code-reviewer`. `scripts/framework/consumer_agents.txt` grows to the full 24-agent shipped roster (8 oversight + the base team); its prior note that base-team agents are "consumer-owned, never shipped" is now obsolete and was corrected.

The code-review surfaced a scope question that this entry settles so it is not re-litigated. **§A8's iterating-role enumeration — *"coder + all reviewers + test roles + design roles that iterate"* — is the authority, and its narrowness is intentional:**

- **`pm-agent` is correctly excluded.** Its flow is a single batched Q&A then *immediate* escalation when the spec is silent — not a rounds-based convergence loop. A 5-round cap on a loop that doesn't exist is noise.
- **The `coder` owns no temp-state file** despite being listed: §A8's path table names files for reviewers/design/tests only, and the coder's loop state is externalized to the reviewer temp files it reads. Made explicit in `coder.md`; no redundant coder file.
- **`technical-design`'s routing hub is single-pass** (revise-and-notify, or re-route), not a capped loop; TD's *actual* iterating loop (architect critique) carries the §A8 cap + temp-state.

The `code-reviewer` posted three "blocking" findings against these three (plus one true one — every reviewer CORE had dropped `CONDITIONAL` from the §A6 `Status:` enum, now fixed). Verifying each citation against §A8's scope clause — not accepting it because §A8 exists — rejected the three false blockers with spec grounding. Also normalized the `## Project Extensions` divider to sit *before* `PROJECT:START` (HOS-owned per D8) across all 16, fixing 4 outliers. See `research/findings/reviewer-overapplies-quality-rule-scope.md` (a distinct review-failure mode: a real rule applied beyond its spec'd scope; verify-before-fix extended to spec-citation findings).

### D43. The pack install/selection mechanism (ADR-031) — built, and the design↔architect loop caught the fail-closed bugs (2026-06-15)

The v0.3.0 pack mechanism is implemented per **ADR-031** (`docs/v0.3.0/ADR-pack-selection.md`) and its companion design (`docs/v0.3.0/TECHNICAL-DESIGN-pack-mechanism.md`): `--pack <name>`/`--no-pack` selection recorded in `config.sh PACK=`, `packs/<name>/<agent>.md` body-only files, one additive `regions.py inject-pack` verb (parse→append `PACK:<name>` region→compose→re-validate; zero change to the merge/plan/manifest functions), and the A1b install staging that injects the pack body into the staged template before `plan`. Upgrade/switch/strip all flow through the *existing* three-way merge + removed-region sweep with no new merge logic. `core + <pack>` is a complete standalone install; multi-pack permit-but-warn; `--no-pack` reconciles the S1-error-vs-#237-warn tension.

**This step is the cleanest evidence yet for keeping the design↔architect loop** (the human reversed an initial "skip it, go to coder" with *"keep the loop — flush out as many bugs as we can"*). The adversarial **architect review of the design** caught two blocking **fail-closed invariant** bugs the coder had faithfully implemented — **B1** (`--no-pack` silently ignored when `config.sh` recorded a `PACK=` → a passed flag did nothing) and **B2** (an inject failure let Phase B write all other agents + manifest + release before exiting → a partial install, violating decide-all-then-act) — plus a **latent pre-existing twin (A4)** in code the change didn't even touch. The subsequent inner-loop code-review and security-review then APPROVED with **zero blocking findings** (only 3 minor hardening items). The lesson, recorded as `research/findings/design-review-catches-failclosed-invariants.md`: whole-system fail-closed/atomicity invariants are best caught by adversarial review of the *control flow as a whole* (design stage), because at the code level each line looks correct — a complementary layer to per-file code review, the same way gates and review are complementary. Decisions: single additive verb (no parallel mechanism); shared `exit 4` fail-closed gate with *distinct* per-cause messages (`_any_blocked`/`_any_inject_fail`/`_any_plan_fail`); `pack.toml` name≠dir is a consumer-install WARN (directory authoritative) but a hos-dev-CI hard-fail for authors; and PACK-can-override-CORE is the documented pilot trust boundary (in-repo HOS-authored packs only — a content-review gate becomes mandatory if/when fetched/third-party packs land; ADR-031 open-seams). The pre-existing A4 half-write is fixed here as a side-effect of B2's gate and tracked as its own issue.

### D44. The django-pack borg is complete at the CPS-equivalence bar — 12 packs + 4 deliberately CORE-only (2026-06-15)

The `packs/django/` borg (the Q4 "absorb everything reusable from CPS's agents") is done: **12 of 16 base-team agents carry a `PACK:django` region**, each authored by extracting the Django-reusable depth from its CPS counterpart and **independently equivalence-verified** (coverage diff: every distinctive CPS Django check present in the composed `core+pack`; CPS-unique items deferred to PROJECT; no CPS proper-noun leak in any PACK body). Capstone: all 16 base agents compose+validate clean under a simulated `--pack django` install (12 → CORE+PACK:django+PROJECT, 4 → CORE+PROJECT). **CPS can adopt v0.3.0 by clean install and lose nothing** (the acceptance bar, project memory [[project-django-pack-borg-equivalence]]).

The packed 12: `security-reviewer`, `unit-test`, `coder`, `code-reviewer`, `system-test`, `a11y-reviewer`, `privacy-reviewer`, `architect`, `technical-design`, `ui-reviewer`, `ux-designer`, `infra-reviewer` (the last folds CPS's `infra-reviewer` + `deploy-verify`).

**The 4 CORE-only are deliberate, not omissions:**
- `pm-agent` — assessed and confirmed **stack-neutral**: it answers "what should the product do?", which lives above the stack; everything CPS's version added was PROJECT-unique (domain/scope flags) or stack-neutral (already in CORE). Stack-awareness belongs to `architect`/`technical-design`, not requirements. A pm-agent has no reason to know it's Django.
- `ops-reviewer`, `ops-designer`, `reliability-reviewer` — **HOS-native additions (spec §B/O1); CPS never had them**, so there is no CPS depth to borg. They ship CORE-only and gain a `PACK:django` later only if a Django consumer needs telemetry/resilience stack-depth.

Two borg-conventions confirmed in practice (flagged to the human): (a) where a CPS agent was **thin** (`privacy-reviewer` had almost no reusable Django mechanics), the pack **fills it to a complete Django standard** rather than cloning the gap — the spec's rich-pack intent, a floor not a ceiling; (b) PACK bodies must stay **consumer-generic** — the `architect`/`technical-design` packs initially leaked CPS-domain example nouns (`Booking`, `earned-horizon`, `HOA`, `operator console`, `AuditLog`) and were generalized, because a "generic Django pack" that carries another project's domain examples is noise for stack #2.

### D45. v0.3.0 is cut, and validation overrides are now time-boxed, never permanent (2026-06-15)

v0.3.0 shipped (tag `v0.3.0`, release published) integrating the three escalated blockers — machine-accounts foundation (#152), 3 human-gate-boundary fixes (#253), CWE-117 reviewer fix (#250) — via an integration cut PR (#270). Two decisions came out of the release gate:

**(a) The release gate earns its keep on the *shipped surface*, and the same pilot-contamination class D44(b) flagged for PACK bodies also lived in CORE.** The gate's Opus self-review caught two *shipped consumer* agents still naming the pilot: `spec-red-team`'s `agy` prompt literally said *"a parking spot sharing application called CondoParkShare"*, and `post-change-sweep` hardcoded pilot file patterns (`operator_console`, `Specs/`, `Caddyfile`). These were de-piloted in the cut (#262). Lesson: D44(b)'s "PACK bodies must stay consumer-generic" generalizes — **every shipped region (CORE included) must be product-neutral**, and the contamination hides in *invocation prompts and path tables*, not just example nouns. The cut diff itself introduced zero findings; everything the gate raised was pre-existing.

**(b) A human-authorized validation override (`HOS_ALLOW_UNVALIDATED`) is now *time-boxed* — overrides must expire so deferred work is forced, not forgotten.** The open-ended cross-vendor adversarial review will never converge to zero (the [#208](../../issues/208) stopping problem: an adversary over 30 governance files always finds the next prose-vs-enforceable-artifact gap; it surfaced 3 HIGH + 5 medium pre-existing governance findings, filed as the recurring-class epic #269). Prior releases (v0.1.1/v0.2.1/v0.2.2) resolved this with a human override + integrity note — but those overrides were **permanent**, which silently normalizes the deferral. New mechanism: the stamp carries an `override_expires:` field, and `check_validation_current.sh` **fails CI fail-closed once it lapses** (absent → no override; malformed/past → fail). v0.3.0's override expires **2026-06-22** (one week). After that, any PR to `main` fails until #269 is resolved or a human re-authorizes. The override is thus a *loan against future work with a due date*, not a waiver. The mechanism distinguishes the two legitimate ways the gate reaches green — genuine convergence (clean stamp) vs. time-boxed human acceptance (override stamp) — and makes only the first permanent.

### D46. `--pr` is fail-closed — a safety path must halt the unsafe action, not just log a refusal (v0.3.1, 2026-06-15)

`hos_install.sh --pr` (apply an upgrade on a branch + open a PR, base untouched) could silently degrade to an **in-place** mutation of the consumer's working tree when PR setup failed (#272, ship-stopper). Root cause: `fail() { err "$*"; ERRORS=$((ERRORS+1)); }` does **not** exit — it records an error inspected only at end-of-run. So the eligibility "guard" (`fail "--pr requested but not possible…"`) printed a refusal and then execution **continued into the in-place scaffolding**, with the non-zero exit arriving *after* the writes. A guard that reads like a guard but doesn't halt.

**Decision:** under an explicit `--pr`, every pre-scaffold PR-setup failure (ineligible repo — dirty tree / no `origin` / no `gh` / detached HEAD — or branch-creation failure) **hard-stops (`exit 1`) before any filesystem write**. `--pr` means *PR-or-nothing*; there is no in-place fallback when it was explicitly requested. Post-scaffold push/PR-create failures keep the deferred-error path (`fail` → non-zero exit) — correct there, because the work is already isolated on the branch and the base is untouched; only the false exit-0 needed fixing. The load-bearing distinction: **`exit` where an irreversible action would otherwise follow; a deferred counter only where the damage is already safely contained and you merely owe an honest exit code.** First patch on the `release/v0.3.x` line; lesson recorded in `research/findings/a-guard-that-doesnt-halt-is-not-a-guard.md`. This is also the first real exercise of the v0.3.x patch line and the branch model (main = next minor, release/v0.3.x = patch line).

### D47. The installer must not swallow a subprocess crash — a degraded install that prints "Done" is the worst failure (v0.3.2, 2026-06-15)

Sibling to D46, different mechanism. `hos_install.sh` ran several `regions.py` calls as `… 2>/dev/null` and then **silently fell back** on failure (#276): a crash left a region unwrapped, used a raw `cp` as the composed "disk" image, or yielded empty `base-shas={}` — and the install still stamped success. The traceback was *eaten by `2>/dev/null`*, which is why a real consumer's "python crash in the terminal" was unattributable. Where D46 was a guard that didn't halt, this is a failure that was never surfaced at all — the same fail-open family from the opposite direction (D46 swallowed the *control*, this swallowed the *signal*).

**Decision:** regions.py calls with no legitimate non-zero exit (`migrate` on a grep-confirmed-flat file; `base-shas`) run through `_regions_strict`, which captures stderr and on **any** non-zero **surfaces the traceback and `exit 1` in Phase A — before Phase B writes any agent, manifest, or version stamp.** A crash now fails closed (nothing written) instead of degrading silently. The two calls that already failed closed via the decide-all-then-act gate (`inject-pack`, `plan`) now surface their stderr too — a fail-closed abort must never be blind. The triage line (from the review): **`exit` where an irreversible/integrity-degrading action would otherwise follow; the deferred-error counter only where the damage is already contained.** Bundled with #273 (the `--pr` commit-swallow) under one theme: *the installer never reports success over a swallowed failure.* Post-Phase-B manifest-assembly swallows (deferred-impact, same class) filed as #277 for a follow-up.

### D48. The version stamp is the commit point — write it last (v0.3.5, #277, 2026-06-15)

Completing D47's theme into the manifest path: the two post-Phase-B manifest-assembly calls now fail closed (surface stderr + `exit 1`) on a crash, distinguished from a genuine *regions.py-absent* degraded-but-warned fallback. But the adversarial review of the first cut caught a sharper, structural bug: **`.hos-release` (the version stamp) was written several steps *before* the manifest block**, so a manifest crash left a new version stamped over a stale/missing `.hos-manifest` — exactly the integrity gap #277 targets, the D41 "looks like it ran" failure mode at the install level.

**Decision:** `.hos-release` is written **last**, only after the agents AND the manifest are on disk. The version marker is the *commit point* of the install — the one artifact that says "this install is complete and at version X" — so it must be the final write, and any earlier failure (agents, manifest) must precede it. Generalizes beyond the installer: **whatever artifact downstream consumers treat as "this completed at version X" is the commit point and must be written last, after everything it attests to.** A commit point that outruns the work it attests to is a lie the next reader believes. (Caught only because the fix was adversarially reviewed — the first cut's own error message falsely claimed `.hos-release` was not stamped.)

### D49 — 2026-06-16: Consolidate to two named runtime agents with interactive/autonomous modes (#305, #306)

**Problem.** No named agent served as the human entry point. The cron invoked shell scripts with no governing spec. Interactive and autonomous behavior had no shared specification — they were described in different places with no relationship stated.

**Decision.** Two agents: `worker.md` (human entry point + autonomous build agent, `hos_orchestrator.sh --class worker`) and `overseer.md` (oversight console + autonomous review/merge agent, `hos_orchestrator.sh --class overseer`). Each has explicit INTERACTIVE and AUTONOMOUS behavioral sections in one spec file. Mode is determined by invocation context, not by which file was loaded.

**Rationale.** Interactive and autonomous modes share the same routing logic, tool set, and artifact-naming contracts. What changes is: who initiates work, which gates apply instead of human approval, and which credentials are active. Splitting into two files requires maintaining two specs for one role and creates drift risk — a routing change must be applied to both files and divergence is invisible until something breaks. One spec with explicit mode sections is easier to validate and documents the relationship clearly.

**Consequences.** `worker` is the correct agent to invoke for any new session. `overseer` answers PR/risk questions and is the autonomous review agent. The specialist agents (coder, reviewers, etc.) remain; worker and overseer are the orchestration layer above them, not replacements.

### D50 — 2026-06-16: PROJECT carve-out clause replaces the unconditional "PROJECT governs" footer (#291)

**Problem.** Every CORE agent file ended with: *"Where the PROJECT section below conflicts with anything above, PROJECT governs."* That unconditional clause allows a consumer's PROJECT section to override any CORE behavior, including human approval gates, risk-tier thresholds, reviewer independence requirements, loop-exit caps, and escalation terminal points — exactly the safety-critical behaviors the oversight system is designed to enforce.

**Decision (architect-approved hybrid A+B).** Replace the unconditional clause with an enumerated carve-out that:
- Permits PROJECT to extend CORE with app-specific context, routing hints, and *stricter* checks.
- Permanently protects five named safety classes from PROJECT override: (1) human approval gates, (2) risk-tier thresholds and required sign-offs, (3) reviewer independence and cross-vendor requirements, (4) loop-exit conditions and round caps, (5) escalation terminal points.
- States that PROJECT may only ever make these stricter, never looser.
- Adds mechanical enforcement: `check_agents_static.sh` section 6 fails any CORE file that lacks the carve-out text.

**Status:** Implemented 2026-06-16 — carve-out clause applied to all 18 CORE agent files; `check_agents_static.sh` section 6 enforcement added.

### D51 — 2026-06-17: Confidence asymmetry rule — agent-declared confidence excluded from automated routing

Agent self-reported confidence is excluded from automated routing decisions. High confidence may never lower the scrutiny tier; low confidence may raise it.

**Rationale:** Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610) shows that 99.9% of agent PRs self-rate confidence 8–10, and defect rates are flat at 3.16–3.96% across that range. The signal is saturated and empirically uninformative as a discriminator. Using it to route lighter review imports a measurably false signal — one that would apply lighter treatment uniformly rather than selectively. Confidence is retained as a calibration prior for the human reader; it is removed from any path where it could cause a tier downgrade. See `research/findings/agent-confidence-is-uninformative-for-defect-prediction.md`.

### D52 — 2026-06-17: Deterministic gate non-override invariant

An LLM arbiter, reviewer, or any agent component may not suppress, dismiss, or override a finding produced by a deterministic scanner. Deterministic findings reach the human gate verbatim, regardless of any agent's assessment that they are false positives.

**Rationale:** Parris 2026 (AIRA) documents LLM masking of deterministic scanner failures — an arbiter adjudicating a scanner finding as acceptable removes the finding from the human-visible record, converting a detectable defect into a silent pass. The combination of "scanner ran and flagged X" with "agent decided X is fine" is indistinguishable at the output from "scanner ran and found nothing." The correct resolution is to always surface deterministic findings and let the human decide on disposition. An agent may *annotate* a finding (context, severity assessment, suggested disposition) but may not *suppress* it from the human-visible record. This is the same principle as D41's "honest degradation" applied to findings rather than reviewer availability. See `research/findings/gates-and-review-are-complementary.md`.

### D53 — 2026-06-17: Reviewer framing guard — author-supplied NL framing is untrusted input in all reviewer prompts

Author-supplied natural-language framing (PR title, description, commit message, inline code comments written by the author) is treated as untrusted input in all reviewer agent prompts. An explicit anti-framing instruction is added to the CORE regions of code-reviewer, security-reviewer, and privacy-reviewer: reviewers evaluate the diff on its own merits; the author's prose description of what the change does does not constitute evidence that the change does it.

**Rationale:** Mitropoulos et al. 2026 (Zotero X7EN6DXZ) demonstrated a 100% attack success rate at getting vulnerability-reintroducing PRs accepted across 17 CVEs in 10 real open-source projects by adversarially crafting PR framing. The attacker refines locally against a clone of the pipeline (asymmetric advantage); redacting PR metadata and adding an anti-framing instruction restored correct detection in all cases. The defense is cheap (a prompt instruction and a context-construction choice) but must be explicit — without it, reviewer agents are vulnerable to this class of attack by default. This is a supply-chain attack on the oversight mechanism itself: a reviewer that can be socially engineered through author-supplied prose weakens every other correctness guarantee at the boundary where a human would have relied on it most. See `research/findings/adversarial-framing-attack-on-reviewer-agents.md`.

### D54 — 2026-06-17: Agent front-matter is fully HOS-canonical on upgrade (#240)

**Problem.** On upgrade, `hos_install.sh` replaces agent file front-matter with the HOS-template version. This silently reverts any consumer edits to fields like `model` or `tools`.

**Decision.** Agent front-matter is **fully HOS-canonical**. Consumers must not edit agent front-matter.

**Rationale.** Front-matter fields interact; `model` and `tools` affect correctness; consumers should use PROJECT region or packs. Simplicity wins.

**Consequences.** Document in `docs/CUSTOMIZATION.md` that agent front-matter must not be edited by consumers.

---

## 2026-06-21 — Cron runs headless Claude on the user's Claude subscription via OAuth token (#728)

**Decision.** `bin/hos-cron` authenticates headless `claude --print` against the user's
Claude subscription using an explicit `CLAUDE_CODE_OAUTH_TOKEN`, sourced from a 0600 env
file at `~/.config/hos/claude-auth.env` (generated by `claude setup-token`). The
wrapper unsets `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` before invoking claude.

**Misdiagnosis corrected.** An earlier brief concluded headless `claude --print`
*must* bill pay-as-you-go API credits and that the subscription only covers interactive use.
That was wrong. Headless runs on the subscription when given an OAuth token. The
"Credit balance is too low" failure was the cron resolving to API-key billing
(against an empty API account) because: (a) the live OAuth credential lives in the
macOS keychain, which cron cannot reach (non-login session, locked keychain); and
(b) absent an explicit token, resolution falls through to API-key mode. An exported
`ANTHROPIC_API_KEY` also outranks the OAuth token, so the wrapper unsets it.

**Why the env file, not the keychain.** The keychain is exactly what cron cannot
reach — that is the root cause. A 0600 env file is deterministically readable by
cron running as the user, the documented headless/CI path, and consistent with how
`apps.env` already stores cron credentials. The OAuth-token approach also makes the
wrapper independent of `~/.claude/.claude.json` (which kept getting stripped of
`oauthAccount`).

**Also fixed.** Portable mkdir overlap-lock (macOS has no `flock`) with PID-liveness
stale reclaim; a latent `set -e` bug where `_claude_exit=$?` could never capture a
real claude failure; opt-in auth probe (`HOS_CRON_AUTH_PROBE=1`, default off to
respect the weekly subscription rate limit).

**Rejected.** Adding API credits / setting `ANTHROPIC_API_KEY` in crontab (pays
off-subscription, unnecessary). Rewriting the worker to call the Anthropic API/SDK
directly (a custom client on subscription creds is a third-party app, hard-blocked
from subscription limits). Passing `--bare` (ignores the OAuth token, demands an API key).

**Consequences.** Token from `claude setup-token` is valid ~1 year and does not
auto-refresh; expiry surfaces as a claude non-zero exit with a refresh hint in the
log. Headless fires draw from the same weekly subscription rate limit as interactive use, so
idle-backoff suppression (#628) is load-bearing for cost control.

---

## 2026-06-23 — Audit log sync bot: dedicated `hos-auditsync-hos` GitHub App

**Decision.** Audit log files (`audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`) are gitignored from feature PRs and synced to main via a GitHub Actions workflow using a dedicated `hos-auditsync-hos` GitHub App. The app holds the Ruleset bypass for direct push to main.

**Rejected alternatives.**
- *`hos-overseer-hos` bypass*: expands the overseer's authority beyond its intended scope; the overseer's merge authority should always flow through the PR review process.
- *`hos-worker-hos` bypass*: same concern.
- *`github-actions[bot]`*: does not appear in either classic branch protection or Ruleset bypass UI.
- *PAT*: commits would show as the human owner, muddying the audit trail.

**Naming.** `hos-auditsync-hos` follows the `hos-*-hos` convention so each consumer repo gets its own scoped app instance.

**Consequences.** The app needs `Contents: read & write` on the target repo only. Secrets `HOS_AUDIT_SYNC_APP_ID` and `HOS_AUDIT_SYNC_PRIVATE_KEY` must be stored per-repo. The workflow uses `actions/create-github-app-token` to generate a short-lived installation token each run. The cron machine pushes audit files to the unprotected `audit-log` branch; the workflow reads from there and commits only those two files to main.

## 2026-06-27 — Scripts-review dedup ledger committed in-repo (#686)

**Decision.** The scripts-review convergence ledger moves from gitignored `.claudetmp/framework/scripts-review-ledger.jsonl` to the **committed** path `scripts/framework/scripts-review-ledger.jsonl`. Dispositions (`fixed`/`filed:#N`/`residual`/`noise`) now accumulate across machines and releases instead of resetting on every fresh clone. **✅ implemented** (root cause #5 of #686).

**Why.** The Phase 1.6 scripts-review gate never converged at the v0.4.0 cut (10+ attempts, `--skip-validation` required). A primary driver: the ledger lived in a gitignored temp dir, so every machine/checkout started with an empty seen-set and re-litigated already-triaged findings. Committing the ledger gives the gate a durable baseline — the same mechanism that lets `validate_self.sh` converge — and structurally enables release-time pre-seeding (#686 improvement #6: the committed ledger *is* the baseline the next release starts from).

**Fail-closed preservation.** An empty/missing ledger is an empty seen-set, so a clean checkout behaves identically to before. The ledger only ever *adds* to the seen-set, which can convert un-ledgered blocking findings into known ones — never the reverse. The verdict=error / hung-or-empty-reviewer path (#669/#670) is independent of ledger contents, so nothing here lets a failed reviewer converge to PASS.

**`--reset` semantics.** Because the file is now tracked, `validate_scripts.sh --reset` **truncates** the ledger (clears the seen-set, keeps the tracked file) and clears the per-run pass counter, rather than deleting the file. To clear the shared baseline for everyone, commit the emptied file; otherwise `git restore` it after a local run. `HOS_SCRIPTS_REVIEW_LEDGER` overrides the path (used by tests so they never touch the committed baseline).

**Ledger asymmetry (intentional).** Only the scripts-review ledger is persistent. `validate_agents.sh` / `validate_self.sh` keep their ephemeral `.claudetmp/` ledgers and their delete-on-`--reset` behavior — they review the (smaller, more stable) agent/contract surface and have not exhibited the cross-machine convergence failure. Persisting them is deferred; touching them would re-open the shared `--reset` idiom and balloon the blast radius.

**Deferred (filed as follow-ups to #686).** Semantic/embedding dedup (#1), scoping the gate to product scripts via an infra-exclusion list (#2), a convergence criterion replacing the fixed 3-pass cap (#3), 2-of-3 reviewer agreement before a finding counts as new (#4), and automated release-time pre-seeding (#6). Each carries its own fail-open surface and is a separate design.

## 2026-06-28 — Risk-tier model escalation for reviewers, designed (#63)

**Decision.** Four review-path agents — `risk-assessor`, `security-reviewer`, `code-reviewer`, `oversight-evaluator` — escalate from Sonnet 4.6 to **Opus 4.8 when the governing risk tier is HIGH or CRITICAL**; on LOW/MEDIUM they stay on their #895 static-split default (Sonnet). 🔧 **designed/planned** — see [`docs/specs/TECHNICAL-DESIGN-63-model-escalation.md`](specs/TECHNICAL-DESIGN-63-model-escalation.md). Owner-approved direction (#63, 2026-06-26).

**Why.** This is the *dynamic* complement to the #895 *static* split (D-COST §4): keep the common LOW/MEDIUM path cheap on Sonnet while guaranteeing Opus-grade scrutiny exactly where an escaped defect is most expensive. Tier-triggered, deterministically — explicitly **not** a "second opinion when the agent feels stuck" heuristic.

**Mechanism.** Agent `model:` frontmatter is static and HOS-managed, so escalation is applied at *invocation* by overriding `--model claude-opus-4-8`, never by editing agent definitions. A pure resolver `select_review_model(agent, governing_tier)` (new `scripts/oversight/model_escalation.py`) is the single source of truth for the policy. `risk-assessor` keys off the deterministic triage floor (`compute_triage_floor`, SPEC-332) since it *produces* the validated tier; the other three key off `max(triage_floor, validated_tier)`.

**Fail-safe.** Escalation is **monotonic** — it only upgrades Sonnet→Opus, never below the #895 floor. An unknown/garbled tier degrades to the Sonnet default (cost, not safety, is at risk; the deterministic floor independently guarantees ≥ Sonnet-grade review). Reviewer independence and the cross-vendor requirement at high risk (D4) are untouched — only the Claude tier changes, not which vendors vote.

**Scope.** Design only; no behavioral code lands with the design PR. Implementation (resolver + tests, then callsite wiring into the `claude --agent` oversight loop) is a separate MEDIUM+ slice requiring the full reviewer panel and human authorization.
