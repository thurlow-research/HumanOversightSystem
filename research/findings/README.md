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
- *(#248 / session 2026-06-15 — not yet captured as a finding; see below.)*
- *(#695 / #815 — the O8 layer institutionalized as overseer release-gate deep validation; not yet a standalone finding.)*

### O9 — An agent given a broad mandate behaves like a human developer given the same mandate. `[core]`
- `ai-agent-scope-drift-mirrors-human-dev-behavior.md` — scope creep, definition-of-done drift, batch-over-incremental PRs.
- `autonomous-worker-restacks-redundant-work.md` — the worker re-proposes already-merged work (the rebase reflex a human has, the loop lacks); #850/#880.
- *(#901 — lowest-issue-number work selection bias, fixed with explicit priority; not yet a standalone finding.)*

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
2. **The v0.3.0 release-gate gaming-hole catch (O8, #248).** The session 2026-06-15 catch — the release gate finding a governance gaming-hole that code-review, security-review, doc-validator, and the design↔architect loop all passed — has no finding file (#247/#248 are unreferenced in the corpus). The closest existing evidence is `release-gate-catches-its-own-missing-oversight.md` and `the-distrust-check-exempted-its-most-important-target.md`, but the #248 incident is its own data point and the cleanest single instance of "last-line gate beats the whole inner loop." Worth its own file.
3. **Institutionalizing the last-line gate (O8, #695/#815).** The overseer now runs a standing release-gate deep validation (re-reads every per-step `summary.json` from main, re-checks tier/severity and sign-off completeness, posts CLEARANCE/ESCALATE before release authorization). This turns the O8 "manual last-line pass" into continuous mechanism — a finding about *operationalizing* the last-line gate as a role responsibility, distinct from the convergence-architecture finding.
4. **The graceful safety valve (O7, #778).** `hos-suspend` lets a human pause a project's cron cycle via an auditable JSON marker (fail-closed: marker present ⇒ exit 0) instead of editing crontab. A clean instance of `the-safety-valve-must-be-more-trustworthy-than-the-gates` and `brownfield-governance-adoption` (bounded suspension as a first-class mechanism); currently only evidence, no dedicated file.

---

## All findings (flat list)

| File | Role | One-line description |
|---|---|---|
| `a-gate-must-not-confuse-unreadable-with-unsafe.md` | oversight-mechanism | A gate has four outcomes (approve/request-changes/unparseable/error); collapsing "unparseable" into "fail-closed" discards real independent judgment (a Postgres NULL-sort bug). |
| `actor-identity-vs-determination-honesty.md` | oversight-mechanism | A forge-proof human gate needs two guarantees — actor identity (separate account) *and* determination honesty (server-side enforcement); machine accounts close only the first. |
| `autonomous-worker-restacks-redundant-work.md` | both | A standing autonomous worker re-proposes work already in main/a sibling PR (the rebase reflex the loop lacks); needs a fail-closed pre-PR "is this already done?" check (git-cherry patch-id + open-PR SHA overlap). |
| `brownfield-governance-adoption.md` | oversight-mechanism | Governance onto existing code needs a first-class bounded-suspension mechanism, or teams invent unsafe ad-hoc bypasses. |
| `chat-history-as-unreliable-artifact.md` | oversight-mechanism | Decisions made in chat but not committed to checkable files are invisible to validators and silently forgotten. |
| `ci-is-blind-to-consumer-environment-failures.md` | oversight-mechanism | CI runs in a superset of the operator's environment, so absence-dependent bugs are invisible until a real install test. |
| `convergence-ledger-must-persist.md` | oversight-mechanism | The dedup ledger that defines a non-deterministic gate's reachable "zero-NEW" pass was gitignored, so it reset on every clone and the gate never converged (10+ attempts, `--skip-validation`); commit it in-repo. |
| `cost-gating-autonomous-oversight-loops.md` | oversight-mechanism | Standing autonomous oversight must gate the expensive model call behind a cheap deterministic "is there work?" trigger, or it gets turned off. |
| `cross-vendor-review-finds-real-bugs.md` | oversight-mechanism | Cross-vendor (agy/codex vs Claude) review consistently finds genuine bugs same-vendor review misses; the contribution is the decorrelation mechanism. |
| `design-review-catches-failclosed-invariants.md` | oversight-mechanism | Adversarial *design-stage* review catches whole-system fail-closed/atomicity bugs that per-file code review is structurally weakest on. |
| `explicit-na-audit-entries.md` | oversight-mechanism | A skipped reviewer must emit an explicit, audited N/A entry, or "ran/found nothing," "never invoked," and "skipped by a bug" are indistinguishable. |
| `feed-the-reviewer-its-own-issue-tracker.md` | oversight-mechanism | Inject the open tracker into a non-deterministic reviewer's prompt ("already tracked — don't re-report") so it converges by construction. |
| `fixer-triage-inner-loop-boundary.md` | oversight-mechanism | One shared triage rule for any detect-and-correct agent: mechanical→fix; structural→escalate; only ever edit *toward* the authoritative source. |
| `gate-on-computed-signal-not-self-reported-verdict.md` | oversight-mechanism | A gate must recompute its verdict from the findings (`blocking_count`), never trust the reviewer's self-reported `verdict` field; a JSON listing blocking findings but tagged "approve" exited 0. |
| `gates-and-review-are-complementary.md` | oversight-mechanism | Deterministic gates and agent review catch different defect classes; neither subsumes the other (gates found 3 defects review approved). |
| `hos-ports-human-software-engineering-best-practices.md` | oversight-mechanism | Every HOS mechanism is an AI-native port of an established human SWE practice; the lens is generative and predictive. |
| `human-gate-enforcement-limits.md` | oversight-mechanism | A behavioral prohibition on forging human-authorization files can't be made mechanically unbeatable until AI/human identities are separable. |
| `install-time-placeholder-substitution.md` | signal-generation | Framework files carrying project-specific content silently corrupt every non-reference install; substitution is an invariant, not a one-time step. |
| `issue-vs-pr-thread-routing.md` | oversight-mechanism | "Would a human file a GitHub issue for this?" correctly routes findings between issues (project-level) and PR threads (inner-loop). |
| `jidoka-reactive-pipeline.md` | oversight-mechanism | Make-style dependency tracking + Jidoka: auto-re-run steps when inputs change, but stop for the human only on a NEW finding. |
| `nondeterministic-review-gate-converges-on-zero-new.md` | oversight-mechanism | An LLM reviewer converges on "zero-NEW" (all dispositioned), never "zero findings"; that is its definition of "pass." |
| `omission-class-documentation-bugs.md` | both | Omission-class doc bugs (a doc covers a subset of an agent's behavior) are invisible to contradiction checkers; check against the authoritative source. |
| `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` | oversight-mechanism | Making an adversarial LLM reviewer shippable as a hard gate needs a 4-mechanism convergence architecture; the composition is the contribution. |
| `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` | oversight-mechanism | A capable orchestrator absorbs roles it should delegate; the pipeline is bypassed by default and a bypassed pipeline looks reviewed. |
| `oversight-blindspot-documentation-discoverability.md` | oversight-mechanism | A code-correctness pipeline is structurally blind to discoverability — every lane passes while the feature ships undiscoverable. |
| `oversight-gate-must-declare-its-deps-and-fail-loud.md` | oversight-mechanism | An oversight gate must declare its own deps and fail loud; a transitively-satisfied dep is a silent time-bomb (54 silent crashes). |
| `ratchet-principle.md` | oversight-mechanism | Automation may only tighten oversight; reducing it always requires an explicit human decision — the core safety invariant. |
| `refactor-to-reusable-is-a-quality-audit.md` | oversight-mechanism | Refactoring an artifact into a reusable/layered form audits the original — it surfaces hidden coupling and hidden gaps. |
| `release-gate-catches-its-own-missing-oversight.md` | oversight-mechanism | Ship a pinned, re-validated tag, not trunk-HEAD; the release gate re-found the anti-gaming controls stranded off main. |
| `reviewer-agents-file-confident-non-reproducing-reports.md` | oversight-mechanism | AI reviewers file confident, specific, permalink-backed reports that don't reproduce; a reproduction gate is mandatory before any fix. |
| `reviewer-overapplies-quality-rule-scope.md` | oversight-mechanism | A reviewer over-applies a *real* rule beyond its spec'd scope; caught only by re-reading the spec clause, not the code. |
| `self-classification-cannot-gate-the-human-boundary.md` | oversight-mechanism | The classification deciding whether a human sees a change can't be done by the actor; de-escalation must be re-derived from the diff. |
| `self-governance-recursion.md` | oversight-mechanism | A framework built with the process it governs must be run against its own code; doing so immediately reveals real defects. |
| `spec-gap-routing-chain.md` | oversight-mechanism | Spec-gap escalation enters at the lowest capable authority (technical-design → architect → pm-agent), not short-circuit to pm. |
| `stamp-based-ci-enforcement.md` | oversight-mechanism | A committed git-*commit*-timestamp stamp bridges local validation and CI, proving validation ran current to the changes. |
| `the-distrust-check-exempted-its-most-important-target.md` | oversight-mechanism | An anti-gaming re-derivation check carved out code-review — its most important target; coverage must be scoped by threat model. |
| `the-gate-must-time-out-its-own-dependencies.md` | oversight-mechanism | Every external call an oversight gate makes must be hard-bounded; a hung dependency is a dead gate (invisible denial of oversight). |
| `the-recorder-must-not-be-in-the-recorded-set.md` | oversight-mechanism | The artifacts a control writes about a step must be excluded from the changed-file set the step is re-validated against. |
| `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` | oversight-mechanism | The mechanism that *disables* oversight must be more trustworthy and auditable than the gates it disables — its failures fail toward less oversight. |
| `tooling-drift-in-validation-pipelines.md` | both | Validation pipelines calling external CLIs fail OPEN on tooling drift; needs honest degradation + one invocation site + a canary. |
| `unenforceable-rules-need-verification-mechanisms.md` | oversight-mechanism | A rule requiring human action is advisory unless it provides a concrete observable artifact the agent can check. |
| `working-state-invariant.md` | signal-generation | Incremental AI development must verify a working state (lint+types+tests) between prompts, or agents build a "house of cards." |
