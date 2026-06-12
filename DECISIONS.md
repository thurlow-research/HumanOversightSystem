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
- **IP agent — make it functional** 🔧 — implement growth step 1 (license gate) so `ipcheck` does real work; then flip `IP_STUB=0` (D19).
- **Raw archive + watermark** 🔧 — the append-only turn log + regenerable summaries (D8).
- `.antigravitycli/` into `setup_oversight.sh`'s emitted `.gitignore`; Windows support in `setup_clis.sh`.
