# Findings index

The files in this directory are the **experiences** — concrete, dated, issue-numbered incidents from building and field-testing the Human Oversight System. Each is a standalone, citable record (claim → evidence → research implication), classified by a `**Role:**` header on the signal/oversight axis (see `../README.md` and `DECISIONS.md` D37).

The synthesis *over* these — the high-level observations each evidences — lives in `../OBSERVATIONS.md`. This README maps the two together, then lists every finding with a one-line description.

> **Status:** the observation layer is a FIRST DRAFT for Scott to refine for `../../VibeOversightDissertation`.

---

## Observations → evidencing findings

### O1 — AI can do the work but cannot self-certify it. `[core]`
- `reviewer-agents-file-confident-non-reproducing-reports.md` — confident, permalink-backed reports that don't reproduce; confidence ≠ reliability.
- `reviewer-overapplies-quality-rule-scope.md` — a *real* rule applied beyond its spec'd scope; sound citation, wrong applicability.
- `self-classification-cannot-gate-the-human-boundary.md` — the actor can't classify its own change; de-escalation must be re-derived.
- `cross-vendor-review-finds-real-bugs.md` — even the decorrelating reviewer is sometimes confidently wrong.
- `working-state-invariant.md` — unverified between prompts, agents build a "house of cards."

### O2 — Oversight is a layered system; blind to any dimension it has no layer for. `[core]`
- `gates-and-review-are-complementary.md` — gates caught defects four rounds of agent review approved.
- `design-review-catches-failclosed-invariants.md` — design-stage review caught whole-system fail-closed/atomicity bugs.
- `cross-vendor-review-finds-real-bugs.md` — decorrelated review catches same-vendor blind spots.
- `oversight-blindspot-documentation-discoverability.md` — every lane passed; the dimension with no lane was invisible.
- `explicit-na-audit-entries.md` — the layer set is complete only if every reviewer is accounted for.

### O3 — The cheap independent check gets skipped unless forced. `[core]`
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — the capable orchestrator does the work itself; independence collapses.
- `explicit-na-audit-entries.md` — without a forced entry, "skipped due to a bug" hides as "found nothing."
- `stamp-based-ci-enforcement.md` — a committed git-timestamp stamp makes validation non-bypassable.
- `feed-the-reviewer-its-own-issue-tracker.md` — inject the tracked-issue list into the prompt to force convergence.
- `cost-gating-autonomous-oversight-loops.md` — gate the expensive model call behind a cheap deterministic trigger.
- `unenforceable-rules-need-verification-mechanisms.md` — a rule with no checkable artifact is advisory.
- `convergence-ledger-must-persist.md` — the dedup ledger that defines a forced gate's reachable "pass" reset on every clone; commit it in-repo or the gate never converges.

### O4 — Oversight tooling must fail loudly. `[signal]`
- `tooling-drift-in-validation-pipelines.md` — a removed CLI flag fail-opened second review for two months.
- `oversight-gate-must-declare-its-deps-and-fail-loud.md` — a transitive dep crashed the gate 54× silently.
- `the-gate-must-time-out-its-own-dependencies.md` — an unbounded reviewer call hung and killed the gate.
- `a-gate-must-not-confuse-unreadable-with-unsafe.md` — "couldn't parse" collapsed into "error," discarding a real catch.
- `ci-is-blind-to-consumer-environment-failures.md` — a silently-downgraded secret scan announced a pass.
- `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` — the oversight-*disabling* valve had integrity bugs.

### O5 — Structuring an artifact *is* an audit. `[signal]`
- `refactor-to-reusable-is-a-quality-audit.md` — the layered "borg" extraction surfaced coupling and gaps at once.
- `self-governance-recursion.md` — running HOS on HOS found 4 real defects in an hour.
- `design-review-catches-failclosed-invariants.md` — structuring the control flow as a whole exposed the invariants.
- `chat-history-as-unreliable-artifact.md` — forcing decisions into committed files surfaced the doc/agent mismatch.
- `omission-class-documentation-bugs.md` — checking a doc against its authoritative source catches silent omissions.

### O6 — The human's naïve use-question cuts to the real gate. `[core]`
- `oversight-blindspot-documentation-discoverability.md` — "is this installable yet?" surfaced the zero-doc blind spot.
- `self-classification-cannot-gate-the-human-boundary.md` — the actor can't classify whether the human should see its change.
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — the human nudge catches the silent bypass.
- `human-gate-enforcement-limits.md` — the human gate is behavioral-only until identities are separable.
- `actor-identity-vs-determination-honesty.md` — forge-proof needs separate identity + server-side enforcement.
- `cost-gating-autonomous-oversight-loops.md` — the human drew the deploy line the loop couldn't.
- `a-proxys-draft-of-the-humans-ruling-is-mistaken-for-the-humans-act.md` — the human gate also needs the *authorizer* to know which acts are theirs when an AI proxy drafts in their voice.
### O7 — Re-derive, never trust; ratchet (automation tightens, only a human relaxes). `[core]`
- `ratchet-principle.md` — the invariant was already implicit in three independently built mechanisms.
- `self-classification-cannot-gate-the-human-boundary.md` — de-escalation re-derived from the diff, never self-reported.
- `the-distrust-check-exempted-its-most-important-target.md` — the distrust check must cover *every* role, esp. its most important.
- `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` — the relaxing mechanism must be the most auditable.
- `fixer-triage-inner-loop-boundary.md` — a fixer may only edit *toward* the authoritative source.

### O8 — The last-line independent gate catches what the inner loop missed. `[core]`
- `release-gate-catches-its-own-missing-oversight.md` — re-validating the pinned tag re-found the stranded anti-gaming controls.
- `the-distrust-check-exempted-its-most-important-target.md` — a release-gate self-review found a gaming-hole shipped through prior releases.
- `nondeterministic-review-gate-converges-on-zero-new.md` — "pass" is zero-NEW, never zero; every run surfaces a genuine finding.
- `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` — the full convergence architecture that makes a last-line LLM gate shippable.
- `cross-vendor-review-finds-real-bugs.md` — the decorrelation the last-line gate relies on yields real bugs.
- `gate-on-computed-signal-not-self-reported-verdict.md` — the v0.4.2 pre-release pass caught three fail-opens in the gate set itself; the last-line gate's catch is the fail-open the inner loop's reviewers approved past.
- `convergence-ledger-must-persist.md` — what makes the last-line convergence gate actually reachable across releases (the ledger must persist).
- `release-gate-caught-governance-hole-the-inner-loop-passed.md` — the v0.3.0 release gate (#248, session 2026-06-15) caught a governance gaming-hole the entire inner loop had passed.
- *(#695 / #815 — the O8 layer institutionalized as overseer release-gate deep validation; not yet a standalone finding.)*

### O9 — An agent given a broad mandate behaves like a human developer given the same mandate. `[core]`
- `ai-agent-scope-drift-mirrors-human-dev-behavior.md` — scope creep, definition-of-done drift, batch-over-incremental PRs.
- `autonomous-worker-restacks-redundant-work.md` — the worker re-proposes already-merged work (the rebase reflex a human has, the loop lacks); #850/#880.
- *(#901 — lowest-issue-number work selection bias, fixed with explicit priority; not yet a standalone finding.)*
- `a-blocked-gate-redirects-autonomous-work-instead-of-stopping-it.md` — told to "make progress", the worker routed around a blocked gate into design work; throughput looked healthy while merged code was zero (2026-10).

### O10 — An autonomous loop needs an exhaustive enumeration of what to check, not a concept. `[signal]`
- `agent-misses-pr-feedback-without-explicit-review-read.md` — checked mergeable, not review bodies (#411/#414).
- *(#867 — the inverse: checked review state, not mergeable state, so a CONFLICTING+APPROVED PR was skipped; not yet a standalone finding.)*

---

## Lens (cross-cutting, not an observation)

`hos-ports-human-software-engineering-best-practices.md` — every HOS mechanism is an AI-native port of an established human SWE practice (peer review, separation of duties, andon cord, acceptance sampling). Generative (the next mechanism is the next un-ported practice) and predictive (a port fails where the human practice's implicit precondition is absent in the AI context). Read as a lens *across* the observations, not as one of them.

---

## Findings to write (gaps Scott may want to fill)

These are experiences referenced by the observations that do **not** yet have a primary finding file. The synthesis currently leans on adjacent findings; a dedicated file would strengthen the citation.

1. **The human's naïve use-question (O6, primary).** The pattern — a plain "can it actually be used / is this what we meant" exposing a gap the agent declared closed — is currently distributed across `oversight-blindspot-documentation-discoverability.md`, `orchestrator-absorbs-roles-...`, and the human-gate files. No file names *the pattern itself* as its subject. A finding generalizing it (the human supplies a frame, not more depth) would make O6 first-class.
2. **~~The v0.3.0 release-gate gaming-hole catch (O8, #248).~~ Written:** `release-gate-caught-governance-hole-the-inner-loop-passed.md` (now cited under O8). Original note: The session 2026-06-15 catch — the release gate finding a governance gaming-hole that code-review, security-review, doc-validator, and the design↔architect loop all passed — has no finding file (#247/#248 are unreferenced in the corpus). The closest existing evidence is `release-gate-catches-its-own-missing-oversight.md` and `the-distrust-check-exempted-its-most-important-target.md`, but the #248 incident is its own data point and the cleanest single instance of "last-line gate beats the whole inner loop." Worth its own file.
3. **Institutionalizing the last-line gate (O8, #695/#815).** The overseer now runs a standing release-gate deep validation (re-reads every per-step `summary.json` from main, re-checks tier/severity and sign-off completeness, posts CLEARANCE/ESCALATE before release authorization). This turns the O8 "manual last-line pass" into continuous mechanism — a finding about *operationalizing* the last-line gate as a role responsibility, distinct from the convergence-architecture finding.
4. **The graceful safety valve (O7, #778).** `hos-suspend` lets a human pause a project's cron cycle via an auditable JSON marker (fail-closed: marker present ⇒ exit 0) instead of editing crontab. A clean instance of `the-safety-valve-must-be-more-trustworthy-than-the-gates` and `brownfield-governance-adoption` (bounded suspension as a first-class mechanism); currently only evidence, no dedicated file.
5. **A possible new observation: a disclosed escalation is not a delivered one (proposed 2026-10-20).** The *buried-disclosure* and *escalation-channel-shared-with-parking* findings together suggest that an escalation's channel semantics and salience are part of the oversight loop, separate from its correctness. Both are listed under "Not yet mapped" below until Scott decides.

---

## All findings (flat list)

| File | Role | One-line description |
|---|---|---|
| `a-blocked-gate-redirects-autonomous-work-instead-of-stopping-it.md` | oversight-mechanism | An environment-scoped gate red on every code PR did not stop the worker; it substituted design work (12 of 13 merged PRs were documents, ~45 code branches parked) and raised human escalation load while merged code was zero. |
| `a-confidently-wrong-error-message-costs-more-than-no-message.md` | diagnostic-surface | A Confidently Wrong Error Message Costs More Than No Message |
| `a-decision-records-intent-not-enforcement.md` | oversight-mechanism | A Decision Records Intent, Not Enforcement |
| `a-gate-must-not-confuse-unreadable-with-unsafe.md` | oversight-mechanism | A gate has four outcomes (approve/request-changes/unparseable/error); collapsing "unparseable" into "fail-closed" discards real independent judgment (a Postgres NULL-sort bug). |
| `a-guard-that-doesnt-halt-is-not-a-guard.md` | framework-installer | A guard that records an error but doesn't halt is not a guard — it's a comment |
| `a-proxys-draft-of-the-humans-ruling-is-mistaken-for-the-humans-act.md` | oversight-mechanism | A relay comment quoting the human's paste-ready ruling made the human believe they had posted it; relays must carry no ruling text, and "done" must be verified against the human's own-account comment. (Single incident.) |
| `a-suspension-conditioned-on-external-state-never-lifts.md` | oversight-mechanism | A Suspension Conditioned on External State Never Lifts |
| `a-textual-grep-clears-the-pattern-not-the-class.md` | audit-scope | A Textual Grep Clears the Pattern, Not the Class |
| `actor-identity-vs-determination-honesty.md` | oversight-mechanism | A forge-proof human gate needs two guarantees — actor identity (separate account) *and* determination honesty (server-side enforcement); machine accounts close only the first. |
| `adversarial-framing-attack-on-reviewer-agents.md` | oversight-mechanism | Adversarial Framing Attack on Reviewer Agents |
| `agent-availability-is-a-setup-property-not-a-runtime-property.md` | *(none)* | Agent Availability Is a Setup Property, Not a Runtime Property |
| `agent-confidence-is-uninformative-for-defect-prediction.md` | oversight-mechanism | Agent Self-Reported Confidence Is Uninformative for Defect Prediction |
| `agent-misses-pr-feedback-without-explicit-review-read.md` | *(none)* | Agent Misses PR Feedback Without Explicit Full-Review Read |
| `agentic-prs-are-larger-and-more-multipurpose-than-human-prs.md` | oversight-mechanism | Agentic PRs are larger and more multi-purpose than human PRs — both are leading indicators of review failure |
| `ai-agent-scope-drift-mirrors-human-dev-behavior.md` | *(none)* | AI Agent Scope Drift Mirrors Human Developer Behavior |
| `aira-deterministic-scanner-for-ai-code-failures.md` | *(none)* | AIRA: Deterministic Scanner for AI-Code Failure Patterns |
| `an-enabled-control-can-still-not-cover-its-target.md` | oversight-mechanism | An Enabled Control Can Still Not Cover Its Target |
| `an-escalation-channel-shared-with-parking-loses-its-meaning.md` | oversight-mechanism | `needs-human` meant both "answer this" and "do not work this"; it passed 100 items, notified nobody, and hid a 9-day idle worker. Split parking into its own label, then summon by tiers (assignee, re-ping, narrow push). |
| `an-override-must-expire-or-it-becomes-the-policy.md` | oversight-mechanism | A human-authorized gate override must expire — a permanent override silently becomes the policy |
| `api-field-shape-verification.md` | oversight-mechanism | API Field Shapes Must Be Verified Against Live Responses — Documentation Assumptions Cause Silent Correctness Failures |
| `attention-guarantees-not-fix-mandates.md` | oversight-mechanism | The Countermeasure for AI-Authored Code Is an Attention Guarantee, Not a Fix Mandate |
| `attestation-displaces-the-execution-it-attests-to.md` | oversight-mechanism | Attestation Displaces the Execution It Attests To |
| `autonomous-worker-restacks-redundant-work.md` | both | A standing autonomous worker re-proposes work already in main/a sibling PR (the rebase reflex the loop lacks); needs a fail-closed pre-PR "is this already done?" check (git-cherry patch-id + open-PR SHA overlap). |
| `brownfield-governance-adoption.md` | oversight-mechanism | Governance onto existing code needs a first-class bounded-suspension mechanism, or teams invent unsafe ad-hoc bypasses. |
| `buried-disclosure-fails-like-no-disclosure.md` | oversight-mechanism | A correctly-disclosed escalation still fails if it isn't salient — buried disclosure fails like no disclosure |
| `charter-and-flow-must-both-be-checked-for-cross-agent-dependencies.md` | oversight-mechanism | A new mechanism that depends on an existing agent must be checked against that agent's charter *and* its actual flow — these fail separately, and three passes missed both |
| `chat-history-as-unreliable-artifact.md` | oversight-mechanism | Decisions made in chat but not committed to checkable files are invisible to validators and silently forgotten. |
| `ci-is-blind-to-consumer-environment-failures.md` | oversight-mechanism | CI runs in a superset of the operator's environment, so absence-dependent bugs are invisible until a real install test. |
| `cleanroom-sqc-and-lean-applied-to-hos-consumer-projects.md` | *(none)* | Cleanroom SQC and Lean Principles Applied to Consumer Projects via HOS |
| `coder-working-tree-isolation.md` | oversight-mechanism | Coder Subagents Require a Clean Working Tree — Contamination and Rebase Overwrites Are Predictable Without It |
| `convergence-ledger-must-persist.md` | oversight-mechanism | The dedup ledger that defines a non-deterministic gate's reachable "zero-NEW" pass was gitignored, so it reset on every clone and the gate never converged (10+ attempts, `--skip-validation`); commit it in-repo. |
| `correctness-via-artifact-naming-not-coordination.md` | oversight-mechanism | Correctness in a Concurrent Autonomous System Can Be Achieved by Artifact Naming Rather Than Coordination |
| `corroboration-ranked-review-reduces-noise-without-losing-coverage.md` | oversight-mechanism | Corroboration-ranked review raises precision and cuts volume without suppressing findings |
| `cost-gating-autonomous-oversight-loops.md` | oversight-mechanism | Standing autonomous oversight must gate the expensive model call behind a cheap deterministic "is there work?" trigger, or it gets turned off. |
| `cross-artifact-drift-survives-per-artifact-review.md` | oversight-mechanism | Cross-artifact referential drift survives per-artifact review — every document can be internally coherent while the set is wrong |
| `cross-vendor-review-finds-real-bugs.md` | oversight-mechanism | Cross-vendor (agy/codex vs Claude) review consistently finds genuine bugs same-vendor review misses; the contribution is the decorrelation mechanism. |
| `delete-the-conditional-rather-than-conditioning-it-better.md` | oversight-mechanism | Delete the Conditional Rather Than Conditioning It Better |
| `deployment-authoring-not-execution.md` | oversight-mechanism | The Deployment Translation Is Author-the-Artifact, Not Execute-the-Action — and Its Missing Precondition Is Author/Executor Separation |
| `design-review-catches-failclosed-invariants.md` | oversight-mechanism | Adversarial *design-stage* review catches whole-system fail-closed/atomicity bugs that per-file code review is structurally weakest on. |
| `detection-must-be-decoupled-from-remediation.md` | oversight-mechanism | Detection Must Be Decoupled From Remediation |
| `dismiss-stale-reviews-cascade-in-batch-merges.md` | oversight-mechanism | `dismiss_stale_reviews_on_push` Creates a Cascade in Autonomous Batch Merges |
| `documentation-currency-as-safety-property.md` | oversight-mechanism | Stale documentation in an oversight framework is an operational failure, not a cosmetic gap |
| `dogfooding-inflates-the-measured-intervention-rate.md` | research-validity | Dogfooding an oversight framework on itself systematically inflates the measured human-intervention rate |
| `enforcement-gate-scope-gap.md` | oversight-mechanism | Enforcement Gates Scoped to One Execution Path Do Not Cover All Paths — Direct API Calls Bypass PR-Level Guards |
| `explicit-na-audit-entries.md` | oversight-mechanism | A skipped reviewer must emit an explicit, audited N/A entry, or "ran/found nothing," "never invoked," and "skipped by a bug" are indistinguishable. |
| `feed-the-reviewer-its-own-issue-tracker.md` | oversight-mechanism | Inject the open tracker into a non-deterministic reviewer's prompt ("already tracked — don't re-report") so it converges by construction. |
| `fixer-triage-inner-loop-boundary.md` | oversight-mechanism | One shared triage rule for any detect-and-correct agent: mechanical→fix; structural→escalate; only ever edit *toward* the authoritative source. |
| `gate-on-computed-signal-not-self-reported-verdict.md` | oversight-mechanism | A gate must recompute its verdict from the findings (`blocking_count`), never trust the reviewer's self-reported `verdict` field; a JSON listing blocking findings but tagged "approve" exited 0. |
| `gates-and-review-are-complementary.md` | oversight-mechanism | Deterministic gates and agent review catch different defect classes; neither subsumes the other (gates found 3 defects review approved). |
| `governance-config-currency-gap.md` | oversight-mechanism | An Autonomous Loop That Reads Governance Config From a Local Checkout Has a Currency Gap |
| `hos-design-choices-validated-by-slr.md` | research provenance | HOS Design Choices Independently Validated by the Systematic Literature Review |
| `hos-ports-human-software-engineering-best-practices.md` | oversight-mechanism | Every HOS mechanism is an AI-native port of an established human SWE practice; the lens is generative and predictive. |
| `hos-scores-severity-and-controllability-but-never-exposure.md` | *(none)* | HOS scores severity and controllability but never exposure |
| `human-approval-model-design.md` | *(none)* | Human Approval Model Design — HOS Merge Authority |
| `human-gate-enforcement-limits.md` | oversight-mechanism | A behavioral prohibition on forging human-authorization files can't be made mechanically unbeatable until AI/human identities are separable. |
| `install-time-placeholder-substitution.md` | signal-generation | Framework files carrying project-specific content silently corrupt every non-reference install; substitution is an invariant, not a one-time step. |
| `interactive-vs-autonomous-mode-in-same-agent-spec.md` | oversight-mechanism | One agent spec, two behavioral modes — the case against splitting interactive and autonomous into separate agent files |
| `interface-definition-reveals-hidden-coupling.md` | oversight-mechanism | Defining an extension point is itself a discovery mechanism — it forces hidden coupling into the open |
| `issue-vs-pr-thread-routing.md` | oversight-mechanism | "Would a human file a GitHub issue for this?" correctly routes findings between issues (project-level) and PR threads (inner-loop). |
| `jidoka-reactive-pipeline.md` | oversight-mechanism | Make-style dependency tracking + Jidoka: auto-re-run steps when inputs change, but stop for the human only on a NEW finding. |
| `llm-reviewer-can-mask-deterministic-scanner-failures.md` | oversight-mechanism | An LLM synthesis layer can mask a deterministic scanner failure with a plausible "this is fine" summary |
| `maintenance-class-changes-carry-higher-agentic-risk-than-generation.md` | oversight-mechanism | Maintenance-Class Changes Carry Higher Agentic Risk Than Generation |
| `more-context-makes-llm-review-worse-not-better.md` | oversight-mechanism | More context makes LLM code review worse, not better — the large-context assumption is empirically disconfirmed |
| `nondeterministic-review-gate-converges-on-zero-new.md` | oversight-mechanism | An LLM reviewer converges on "zero-NEW" (all dispositioned), never "zero findings"; that is its definition of "pass." |
| `omission-class-documentation-bugs.md` | both | Omission-class doc bugs (a doc covers a subset of an agent's behavior) are invisible to contradiction checkers; check against the authoritative source. |
| `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` | oversight-mechanism | Making an adversarial LLM reviewer shippable as a hard gate needs a 4-mechanism convergence architecture; the composition is the contribution. |
| `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` | oversight-mechanism | A capable orchestrator absorbs roles it should delegate; the pipeline is bypassed by default and a bypassed pipeline looks reviewed. |
| `oversight-blindspot-documentation-discoverability.md` | oversight-mechanism | A code-correctness pipeline is structurally blind to discoverability — every lane passes while the feature ships undiscoverable. |
| `oversight-gate-must-declare-its-deps-and-fail-loud.md` | oversight-mechanism | An oversight gate must declare its own deps and fail loud; a transitively-satisfied dep is a silent time-bomb (54 silent crashes). |
| `post-pr-behavior-gap-in-agent-specs.md` | oversight-mechanism | Agent Specs That Gate Before an Action Often Leave Post-Action Behavior Undefined — the Agent Fills the Gap with the Most Salient Available Action |
| `prompt-resident-governance-is-unattributable.md` | oversight-mechanism | Governance That Lives in Prompt Text Produces Unattributable Decisions |
| `ratchet-principle.md` | oversight-mechanism | Automation may only tighten oversight; reducing it always requires an explicit human decision — the core safety invariant. |
| `refactor-to-reusable-is-a-quality-audit.md` | oversight-mechanism | Refactoring an artifact into a reusable/layered form audits the original — it surfaces hidden coupling and hidden gaps. |
| `release-gate-catches-its-own-missing-oversight.md` | oversight-mechanism | Ship a pinned, re-validated tag, not trunk-HEAD; the release gate re-found the anti-gaming controls stranded off main. |
| `release-gate-caught-governance-hole-the-inner-loop-passed.md` | oversight-mechanism | The v0.3.0 Release Gate Caught a Governance Gaming-Hole That the Entire Inner Loop Had Passed |
| `reviewer-agents-file-confident-non-reproducing-reports.md` | oversight-mechanism | AI reviewers file confident, specific, permalink-backed reports that don't reproduce; a reproduction gate is mandatory before any fix. |
| `reviewer-output-contract.md` | oversight-mechanism | Reviewer Subagents Must Return Findings in Response Text, Not Just Write to Disk |
| `reviewer-overapplies-quality-rule-scope.md` | oversight-mechanism | A reviewer over-applies a *real* rule beyond its spec'd scope; caught only by re-reading the spec clause, not the code. |
| `richer-ai-explanations-may-increase-overreliance-not-reduce-it.md` | *(none)* | Richer AI explanations may increase human overreliance, not reduce it |
| `safety-serialization-makes-the-human-the-rate-limiter.md` | oversight-mechanism | Safety Serialization Silently Makes the Human the Rate Limiter |
| `self-classification-cannot-gate-the-human-boundary.md` | oversight-mechanism | The classification deciding whether a human sees a change can't be done by the actor; de-escalation must be re-derived from the diff. |
| `self-governance-recursion.md` | oversight-mechanism | A framework built with the process it governs must be run against its own code; doing so immediately reveals real defects. |
| `shell-as-launcher-not-logic-container.md` | oversight-mechanism | A closed policy without a mechanical signal is remembered discipline, not enforcement |
| `spec-gap-routing-chain.md` | oversight-mechanism | Spec-gap escalation enters at the lowest capable authority (technical-design → architect → pm-agent), not short-circuit to pm. |
| `stamp-based-ci-enforcement.md` | oversight-mechanism | A committed git-*commit*-timestamp stamp bridges local validation and CI, proving validation ran current to the changes. |
| `state-assertions-decay-faster-than-their-documents.md` | oversight-mechanism | State Assertions Decay Faster Than the Documents That Carry Them |
| `structured-fault-explanation-drives-developer-action.md` | *(none)* | Structured Fault Explanation Drives Developer Action (vs. Bare Flags) |
| `the-1point7x-defect-rate-claim-has-a-precise-empirical-source.md` | research provenance / citation hygiene | The 1.7× agentic defect rate claim has a precise empirical source — cite it correctly or the premise weakens |
| `the-distrust-check-exempted-its-most-important-target.md` | oversight-mechanism | An anti-gaming re-derivation check carved out code-review — its most important target; coverage must be scoped by threat model. |
| `the-gate-must-time-out-its-own-dependencies.md` | oversight-mechanism | Every external call an oversight gate makes must be hard-bounded; a hung dependency is a dead gate (invisible denial of oversight). |
| `the-recorder-must-not-be-in-the-recorded-set.md` | oversight-mechanism | The artifacts a control writes about a step must be excluded from the changed-file set the step is re-validated against. |
| `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` | oversight-mechanism | The mechanism that *disables* oversight must be more trustworthy and auditable than the gates it disables — its failures fail toward less oversight. |
| `three-tier-review-cost-model.md` | oversight-mechanism | Expensive Cross-Vendor Review Should Run at Transition Points, Not at Every Change — the Three-Tier Model |
| `tooling-drift-in-validation-pipelines.md` | both | Validation pipelines calling external CLIs fail OPEN on tooling drift; needs honest degradation + one invocation site + a canary. |
| `two-key-enable-for-autonomous-systems.md` | oversight-mechanism | A Two-Key Enable — Separating Authorization From Activation — Prevents Autonomous System Self-Enablement |
| `unenforceable-rules-need-verification-mechanisms.md` | oversight-mechanism | A rule requiring human action is advisory unless it provides a concrete observable artifact the agent can check. |
| `unexplained-pr-rejection-is-a-transparency-gap-in-agentic-systems.md` | oversight-mechanism | 64% of rejected agentic PRs are closed with no explanation — a transparency gap that makes the system unauditable |
| `validation-stamp-merge-conflict-cascade.md` | *(none)* | Validation Stamp Commit Anchoring Causes Merge Conflict Cascade |
| `working-state-invariant.md` | signal-generation | Incremental AI development must verify a working state (lint+types+tests) between prompts, or agents build a "house of cards." |
| `wrong-rationale-outlives-wrong-conclusions.md` | oversight-mechanism | Wrong Rationale Outlives Wrong Conclusions |

Rows added on 2026-10-20 use the finding's own title as the description. 10 findings have no `**Role:**` header yet and show *(none)*: `agent-availability-is-a-setup-property-not-a-runtime-property.md`, `agent-misses-pr-feedback-without-explicit-review-read.md`, `ai-agent-scope-drift-mirrors-human-dev-behavior.md`, `aira-deterministic-scanner-for-ai-code-failures.md`, `cleanroom-sqc-and-lean-applied-to-hos-consumer-projects.md`, `hos-scores-severity-and-controllability-but-never-exposure.md`, `human-approval-model-design.md`, `richer-ai-explanations-may-increase-overreliance-not-reduce-it.md`, `structured-fault-explanation-drives-developer-action.md`, `validation-stamp-merge-conflict-cascade.md`.

---

## Not yet mapped to an observation

59 of 100 findings are not cited under any observation above. Most postdate the observation draft. Mapping them is Scott's synthesis call; listed here so the gap is visible.

- `a-confidently-wrong-error-message-costs-more-than-no-message.md`
- `a-decision-records-intent-not-enforcement.md`
- `a-guard-that-doesnt-halt-is-not-a-guard.md`
- `a-suspension-conditioned-on-external-state-never-lifts.md`
- `a-textual-grep-clears-the-pattern-not-the-class.md`
- `adversarial-framing-attack-on-reviewer-agents.md`
- `agent-availability-is-a-setup-property-not-a-runtime-property.md`
- `agent-confidence-is-uninformative-for-defect-prediction.md`
- `agentic-prs-are-larger-and-more-multipurpose-than-human-prs.md`
- `aira-deterministic-scanner-for-ai-code-failures.md`
- `an-enabled-control-can-still-not-cover-its-target.md`
- `an-escalation-channel-shared-with-parking-loses-its-meaning.md`
- `an-override-must-expire-or-it-becomes-the-policy.md`
- `api-field-shape-verification.md`
- `attention-guarantees-not-fix-mandates.md`
- `attestation-displaces-the-execution-it-attests-to.md`
- `brownfield-governance-adoption.md`
- `buried-disclosure-fails-like-no-disclosure.md`
- `charter-and-flow-must-both-be-checked-for-cross-agent-dependencies.md`
- `cleanroom-sqc-and-lean-applied-to-hos-consumer-projects.md`
- `coder-working-tree-isolation.md`
- `correctness-via-artifact-naming-not-coordination.md`
- `corroboration-ranked-review-reduces-noise-without-losing-coverage.md`
- `cross-artifact-drift-survives-per-artifact-review.md`
- `delete-the-conditional-rather-than-conditioning-it-better.md`
- `deployment-authoring-not-execution.md`
- `detection-must-be-decoupled-from-remediation.md`
- `dismiss-stale-reviews-cascade-in-batch-merges.md`
- `documentation-currency-as-safety-property.md`
- `dogfooding-inflates-the-measured-intervention-rate.md`
- `enforcement-gate-scope-gap.md`
- `governance-config-currency-gap.md`
- `hos-design-choices-validated-by-slr.md`
- `hos-scores-severity-and-controllability-but-never-exposure.md`
- `human-approval-model-design.md`
- `install-time-placeholder-substitution.md`
- `interactive-vs-autonomous-mode-in-same-agent-spec.md`
- `interface-definition-reveals-hidden-coupling.md`
- `issue-vs-pr-thread-routing.md`
- `jidoka-reactive-pipeline.md`
- `llm-reviewer-can-mask-deterministic-scanner-failures.md`
- `maintenance-class-changes-carry-higher-agentic-risk-than-generation.md`
- `more-context-makes-llm-review-worse-not-better.md`
- `post-pr-behavior-gap-in-agent-specs.md`
- `prompt-resident-governance-is-unattributable.md`
- `reviewer-output-contract.md`
- `richer-ai-explanations-may-increase-overreliance-not-reduce-it.md`
- `safety-serialization-makes-the-human-the-rate-limiter.md`
- `shell-as-launcher-not-logic-container.md`
- `spec-gap-routing-chain.md`
- `state-assertions-decay-faster-than-their-documents.md`
- `structured-fault-explanation-drives-developer-action.md`
- `the-1point7x-defect-rate-claim-has-a-precise-empirical-source.md`
- `the-recorder-must-not-be-in-the-recorded-set.md`
- `three-tier-review-cost-model.md`
- `two-key-enable-for-autonomous-systems.md`
- `unexplained-pr-rejection-is-a-transparency-gap-in-agentic-systems.md`
- `validation-stamp-merge-conflict-cascade.md`
- `wrong-rationale-outlives-wrong-conclusions.md`
