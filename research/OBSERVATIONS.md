# Observations

**Status: FIRST DRAFT — for Scott to refine.** Feeds `../VibeOversightDissertation`. Not authoritative; the individual files in `findings/` are the data and remain the source of truth.

---

## What this file is

`findings/` holds the **experiences** — concrete, dated, issue-numbered incidents from building and field-testing the Human Oversight System (HOS). This file is the **synthesis layer**: a small set of high-level **observations** (claims), each drawn *across* several experiences and cited to them. The findings are the data; the observations are what the data, taken together, says.

Each observation carries a **relevance tag** to the central thesis — *a scarce human scaling oversight over abundant, capable AI output*:

- `[core]` — load-bearing for the thesis. Without this, oversight-of-AI fails as a problem statement.
- `[signal]` — a quality/engineering practice whose research value is the **oversight signal** it produces (the by-product, not the practice itself).
- `[peripheral]` — sound engineering, but tangential to the oversight-of-AI claim; included for completeness.

A cross-cutting **lens** (`hos-ports-human-software-engineering-best-practices`) runs through most of these and is stated once at the end, not repeated as an observation.

---

## O1 — AI can do the work but cannot self-certify it. `[core]`

**Confident-but-wrong is the default mode of a capable agent, and it arrives in characteristic, recognizable shapes — so an independent verification step is irreducible.**

The agents in this system are competent: they write working code, file specific bug reports with permalinks, and cite the spec clause. None of that is a reliability signal. They produce confident, well-evidenced reports that simply do not reproduce against the shipped code; they apply a *real* rule beyond the scope the spec actually grants it; they re-derive a self-classification in the direction that suits them. The failures are not random noise — they cluster into shapes you can build a gate against: **non-reproducing reports** (a report's confidence and evidence are uncorrelated with its truth), **scope-overreach** (the citation is sound but its applicability is wrong), and **self-serving de-classification** (the actor lowers its own risk tier). Because the failure is confident and well-formed, the producer cannot be trusted to catch it — only an independent step can. This is the irreducible core of the whole system: the human (or a decorrelated agent acting for the human) must verify; self-certification is structurally void.

**Evidence:**
- `reviewer-agents-file-confident-non-reproducing-reports.md` — 3 of 4 overnight field-reports did not reproduce; only the verify-before-fix discipline stopped two erroneous edits.
- `reviewer-overapplies-quality-rule-scope.md` — `code-reviewer` filed 4 "blocking" findings on the v0.3.0 base team; 3 were a real rule applied outside its spec'd scope (false:true = 3:1).
- `self-classification-cannot-gate-the-human-boundary.md` — a self-reported tier may escalate but never de-escalate; de-escalation must be re-derived from the diff.
- `cross-vendor-review-finds-real-bugs.md` — even the decorrelating reviewer is itself confidently wrong sometimes (a false positive driven by a misleading code comment).
- `working-state-invariant.md` — left unverified between prompts, capable agents build a "house of cards" of interlocked errors.

**Cross-links:** O2 (verification must be *layered*), O3 (the verification step gets skipped unless forced), O6 (the human supplies the dimension the agent's "verified" misses), O8 (the last independent gate catches what every prior reviewer's "verified" missed).

---

## O2 — Oversight is a layered system; each layer catches a defect class the others structurally miss — and the system is blind to any dimension it has no layer for. `[core]`

**Defects partition by where they are visible — mechanical, semantic, whole-system-invariant, discoverability — and no single reviewer sees more than its own band; a missing band is an invisible blind spot.**

Across the corpus, every pair of layers turns out to be *complementary, not redundant*. Deterministic gates catch mechanical/type/hygiene defects that four rounds of capable agent review approved right past; agent review catches semantic/intent defects no linter enumerates. Design-stage adversarial review catches whole-system fail-closed and atomicity invariants that are invisible at the code level because *each individual line is correct*. Cross-vendor review catches what same-vendor review's correlated blind spots miss. The sharp version of the claim is the negative one: **an N-dimension overseer is blind to dimension N+1, and blind to its own blindness** — a feature can clear every gate, every reviewer, all 153 tests, and a five-scenario install check, and still ship undiscoverable because no lane watches documentation-currency. The design implication is that completeness of oversight is a property of the *set of layers*, and adding a defect class you've been burned by means adding a layer, not tuning an existing one.

**Evidence:**
- `gates-and-review-are-complementary.md` — four rounds of agent review approved `regions.py`; gates then found 3 real defects (a latent mypy crash, an unpicklable exception, dead imports).
- `design-review-catches-failclosed-invariants.md` (DECISIONS D43) — architect *design* review caught B1/B2 fail-closed + atomicity bugs the coder had faithfully implemented; the later code/security review then passed clean.
- `cross-vendor-review-finds-real-bugs.md` — decorrelated (agy/codex vs Claude) review consistently surfaces genuine findings same-vendor review misses.
- `oversight-blindspot-documentation-discoverability.md` — every existing lane passed; the discoverability dimension had no lane and was invisible until a human asked.
- `explicit-na-audit-entries.md` — the layer set is only complete if every in-scope reviewer is accounted for, including the ones that legitimately don't apply.

**Cross-links:** O1 (each layer is an independent verifier), O6 (the human is the layer that supplies the missing dimension), O8 (the last-line gate is the layer of last resort), and the lens (each layer ports a distinct human practice).

---

## O3 — The cheap, independent check is the one that silently gets skipped when a capable agent is present — so the pipeline must *force* it. `[core]`

**A capable orchestrator absorbs the roles it should delegate, and a capable reviewer re-derives what it could have looked up; left to default behavior, independence collapses and the pipeline is bypassed — and a bypassed pipeline is indistinguishable from a clean one.**

This is the thesis's central tension stated mechanically: when one agent is capable enough to do the whole job, it *will* — it edits the code itself instead of dispatching the reviewer, author and reviewer collapse into one actor, and the independence that the entire oversight value rests on evaporates with no error and no trace. The same gravitational pull shows up as a non-deterministic reviewer burning its whole budget re-deriving issues already on the tracker instead of converging. The corpus's repeated answer is that you cannot *instruct* your way out — the default re-asserts itself within a few turns even with the instruction loaded — you must build mechanism that makes the independent, cheap check unskippable: a committed stamp CI rejects without, a register entry that is *required* (so "skipped due to a bug" can't masquerade as "ran and found nothing"), the open issue list injected straight into the reviewer's prompt, a deterministic "is there work?" trigger gating the expensive model call. The worst failure is the silent one — bypassed-looks-reviewed — so the forcing mechanism's real job is to make the skip *loud*.

**Evidence:**
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — told to "run the validators and work the issues," the agent edited the app itself; the default re-asserts every few turns even after the fix.
- `explicit-na-audit-entries.md` — without a forced N/A entry, "found nothing," "never invoked," and "skipped due to a bug" are indistinguishable.
- `stamp-based-ci-enforcement.md` — a committed git-timestamp stamp makes the validation non-bypassable in CI.
- `feed-the-reviewer-its-own-issue-tracker.md` — injecting the tracked-issue list into the prompt converges the reviewer by construction (2–3 new/run → 1).
- `cost-gating-autonomous-oversight-loops.md` — decouple a cheap deterministic trigger from the expensive model call, or the always-on loop gets turned off.
- `unenforceable-rules-need-verification-mechanisms.md` — a rule with no checkable artifact is merely advisory; the agent over-applies or substitutes its own judgment.
- `convergence-ledger-must-persist.md` (#686) — the dedup ledger that *defines* the forced gate's reachable "pass" was stored gitignored, so it reset on every clone and the gate never converged (10+ attempts, `--skip-validation` required). Forcing a convergence gate is moot if the state that lets it converge is ephemeral; commit the ledger in-repo.

**Cross-links:** O1 (the independent check is what self-certification can't replace), O4 (forcing the check is worthless if a broken check reports "all clear"), O7 (the ratchet — automation may force/tighten, only a human may relax), O8 (the convergence architecture the ledger belongs to).

---

## O4 — Oversight tooling must fail loudly; a broken check that returns "all clear" is the worst possible failure. `[signal]`

**Oversight instruments fail *open* by default — a reviewer that never ran, a dependency that hung, a CLI flag that was removed all produce output indistinguishable from "ran and found nothing" — so honest, distinct, loud degradation is a hard requirement, not a nicety.**

This is the dark twin of O1. If a *capable* agent's confident-wrong output is the danger inside the pipeline, a *broken* check's silent clean verdict is the danger of the pipeline's own machinery. The corpus is full of it: a reviewer CLI whose flag was removed months earlier kept "passing" by masking its own error as an empty result; a non-deterministic reviewer returned prose instead of JSON and the parser read no findings as no problems; a transitively-satisfied dependency let an oversight gate crash 54 times in a row and report "stale stamps"; an unbounded reviewer call hung and silently killed the gate (denial of oversight, worse than a crash because invisible). The standing rule the corpus converges on: a check that did not actually run must emit a **distinct, loud error** — never a silent empty pass — declare its own dependencies, hard-bound every external call with a timeout that degrades to a recorded error, route every external CLI through one invocation site, and back it with a startup canary. Tagged `[signal]` because the engineering is generic reliability practice; its **research** weight is that the instrument measuring AI output must be more trustworthy than the output it measures, or the measurement is theater.

**Evidence:**
- `tooling-drift-in-validation-pipelines.md` (DECISIONS D41) — `codex --quiet` removed; four call sites fail-opened MEDIUM+ second review for two months; agy prose-not-JSON; fix = honest degradation + one invocation site + canary.
- `oversight-gate-must-declare-its-deps-and-fail-loud.md` — a transitive PyYAML dep crashed the gate 54× silently, read downstream as "stale stamps."
- `the-gate-must-time-out-its-own-dependencies.md` — an unbounded `agy -p` hang stalled the whole gate; fixed with a portable hard cap synthesizing `verdict: error`.
- `a-gate-must-not-confuse-unreadable-with-unsafe.md` — "couldn't parse the reviewer" collapsed into "error," throwing away a real bug the reviewer had caught; four distinct outcomes must stay distinct.
- `ci-is-blind-to-consumer-environment-failures.md` — a `command -v detect-secrets` miss silently downgraded the secret scan to a weak grep *while announcing a pass*; only a field install surfaced it.
- `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` — the mechanism that *disables* oversight had integrity bugs and skipped audit entries; it must be more auditable than the gates it disables.
- `gate-on-computed-signal-not-self-reported-verdict.md` (#814) — two validators gated on the reviewer's self-reported `verdict` field instead of the computed `blocking_count`; a JSON listing blocking findings but tagged "approve" exited 0. One of three fail-opens the v0.4.2 pre-release pass caught (the others: a quote-context tracker that skipped real code after a quoted comment; a migration scorer pinned to line 0).
- *(#806/#807)* — `ensure_venv.sh` now smoke-tests the oversight venv (imports radon/bandit/flake8) on **every** invocation and auto-repairs, rather than trusting a stale cached marker — the instrument re-verifies itself each run instead of believing a once-true success record.
- *(#774)* — `hos-cron` fails *closed* (exit 78, actionable message) when the venv/pytest is missing **before** the jitter sleep, instead of silently burning 30–60s and then failing opaquely inside the test runner: declare your deps and fail loud and early.
- **2026-06-27 pre-cut governance audit** (#703, #910–#925) — a dedicated sequential audit of the governance code found **26 adversarially-verified bugs, 21 of them fail-open or governance-bypass**, across the validators, the cron loop, the panel, and the red-team checkpoint — O4's thesis sampled at scale rather than one incident at a time. The sharper result is the meta-finding: nearly every bug violated a principle *already in this corpus*, so the gap is **enforcement, not knowledge** (see `unenforceable-rules-need-verification-mechanisms.md`, third instance). The class is dense enough that the last-line gate (O8) reliably catches what the inner-loop reviewers approve past — the case for turning the top principles into mechanical assertions (lint/CI), not just findings.

**Cross-links:** O3 (forcing a check is moot if the forced check can lie clean), O2 (a silently-broken layer is functionally a missing layer), O8 (the last gate only works if it can't fail-open).

---

## O5 — Structuring an artifact *is* an audit of it. `[signal]`

**The act of imposing structure on an artifact — splitting it into reusable layers, refactoring for independence, applying the system's own process to itself — forces per-element decisions that surface invariants, coupling, and gaps a flat artifact conceals.**

Several findings show that the *reorganization* did the finding, not a separate review pass. Extracting the Django "borg" pack forced a per-line "universal vs stack-reusable vs project-unique" decision on every clause, and that decision surfaced both **hidden over-coupling** (a "generic" pack carrying another project's domain nouns) and **hidden under-specification** (a hand-rolled reviewer that was thin on real mechanics). Running HOS through its own pipeline against its own code surfaced four genuine defects in the first hour. Writing decisions down as durable, checkable artifacts (rather than leaving them in chat) exposed that the docs described only one of two modes. The general claim: structure is a forcing function for completeness; you cannot make every element fit a schema without discovering the elements that don't. Tagged `[signal]` (shading toward `[peripheral]`) because it is a quality benefit of good structure — but it earns its place because in this corpus the structuring repeatedly *was* where the defect surfaced, and self-application is a prerequisite for the system's external credibility.

**Evidence:**
- `refactor-to-reusable-is-a-quality-audit.md` — the CORE/PACK/PROJECT borg surfaced over-coupling (CPS nouns in a "generic" pack) and under-specification (a thin privacy reviewer) at once.
- `self-governance-recursion.md` — first self-run found 4 real defects in an hour; self-application is a credibility prerequisite.
- `design-review-catches-failclosed-invariants.md` — structuring the control flow as a whole (design stage) is where whole-system invariants become visible.
- `chat-history-as-unreliable-artifact.md` — forcing decisions into committed, checkable files surfaced the doc/agent mismatch chat had hidden.
- `omission-class-documentation-bugs.md` — checking a doc against its authoritative agent file is itself a structuring audit that catches silent omissions.

**Cross-links:** O2 (the design layer this enables is a distinct band), O1 (self-application is independent verification turned inward), the lens (each structural move ports a human practice — design review, separation of duties, acceptance sampling).

---

## O6 — The human's naïve use-question cuts to the real gate faster than the agent's technical "verified." `[core]`

**The human contributes a dimension the agent's self-assessment structurally lacks — "can it actually be used / is this what we meant" — and that question repeatedly exposes the gap the agent declared closed.**

This is the thesis's payoff: *why a human at all, if the AI is this capable.* Because the human asks a different *kind* of question. The agent reports "all gates green, all tests pass, install verified" — and a human asking the plain use-question, "is this actually installable by the consumer yet?", instantly surfaces that the shipped feature is documented in zero user-facing files. The same shape recurs: the agent's technical risk-classification is void at exactly the human boundary it's trying to cross; the agent will faithfully follow an instruction while the default it was told to override quietly reasserts, and only a human noticing the *behavior* (not the stated intent) catches it. The human's leverage is not more technical depth — it is a different frame (use, intent, "is this what we meant") that the producer cannot supply about its own work. The corpus also bounds this: the human gate is only as strong as its enforcement — a behavioral prohibition the agent can forge needs server-side, separate-identity enforcement to actually hold — so the human's *judgment* is irreplaceable but the human's *authority* must be made mechanically real.

**Evidence:**
- `oversight-blindspot-documentation-discoverability.md` — the human's "is this installable by CPS yet?" surfaced the zero-doc blind spot every lane had passed.
- `self-classification-cannot-gate-the-human-boundary.md` — the actor cannot classify whether the human should see its own change.
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — the human nudge ("orchestrate, don't absorb") catches the bypass the agent self-diagnoses only after being asked.
- `human-gate-enforcement-limits.md` / `actor-identity-vs-determination-honesty.md` — the human's authority needs separate identity + server-side enforcement to be forge-proof, not just behavioral.
- `cost-gating-autonomous-oversight-loops.md` — the human drew the deploy line ("OK for tonight, not OK for the long run") the autonomous loop couldn't draw for itself.

> **Note:** there is no single finding file whose *primary* subject is the human-naïve-question pattern itself — it is currently distributed across the files above. See "Findings to write" in `findings/README.md`.

**Cross-links:** O1 (the agent's "verified" is the thing this question goes past), O2 (the human supplies the missing dimension N+1), O8 (the last-line gate is the institutional version of this question).

---

## O7 — Independent gating values must be re-derived, never trusted; automation may only tighten oversight, and only a human may relax it. `[core]`

**Two invariants that always travel together in the corpus: any value that decides whether a human sees a change must be re-derived from the artifact rather than taken from the actor's self-report, and any automated movement of the oversight level may only increase it — de-escalation is a human-only act.**

This is the structural guarantee that makes O1 and O6 enforceable rather than aspirational. The "ratchet" — automation tightens, only a human loosens — was found to be already implicit in three independently built mechanisms before it was named, which is itself evidence it's a load-bearing invariant rather than a preference. Its companion is re-derivation: a self-reported risk tier may be trusted to *raise* the bar but never to *lower* it; the loosening direction must be independently recomputed from the diff, and the recomputation must cover *every* role that can emit the self-report — a distrust check that exempts its most important target (code-review) has a hole exactly where it matters most. The corpus also surfaces the failure mode at the seam: the mechanism that *disables* oversight (the suspension safety valve) is the highest-stakes component precisely because its bugs fail *toward less* oversight, so it must be more trustworthy and more auditable than the gates it relaxes.

**Evidence:**
- `ratchet-principle.md` — the invariant was already implicit in three independently built mechanisms (tier validation, suspension authorship, suspension auto-removal) before being named.
- `self-classification-cannot-gate-the-human-boundary.md` — de-escalation re-derived deterministically from the diff; self-report may escalate, never de-escalate.
- `the-distrust-check-exempted-its-most-important-target.md` — the re-derivation check carved out `code-review` on a false rationale; a distrust check must cover every role that can produce the self-report.
- `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` — the suspension valve's failures fail toward less oversight; it must be the most auditable component.
- `fixer-triage-inner-loop-boundary.md` — a fixer may only edit *toward* the authoritative source (up the authority gradient is structural/escalate; down is mechanical/fix).

**Cross-links:** O3 (forcing the check), O6 (the human is the only actor allowed to relax), O4 (the safety valve must fail loud, not silently toward less oversight).

---

## O8 — The last-line independent adversarial gate catches what the entire inner loop missed. `[core]`

**A final, decorrelated, system-level gate run on the about-to-ship artifact repeatedly catches real defects — including governance gaming-holes — that the full inner loop of code review, security review, design review, and doc validation all passed.**

This is O1 and O2 escalated to the release boundary: even after a complete, well-functioning inner loop signs off, an independent last-line gate that re-validates the *shipped artifact as a whole* finds things. The release gate re-validated a pinned tag (not trunk-HEAD) and re-found that the anti-gaming/fail-closed controls themselves had been stranded on a closed branch and never reached the shipped code — the gate caught its *own missing oversight*. A scoped self-review at release found a distrust check that exempted code-review — a structural gaming-hole — that had shipped through prior releases undetected. The v0.3.0 release gate (the #248 catch, session 2026-06-15) found a real governance gaming-hole that code-review, security-review, doc-validator, and the design↔architect loop had all passed. The pattern's research weight: independence is not exhausted by the inner loop. A whole-system adversarial pass at the last moment is a distinct layer with a distinct yield, and its characteristic catch is the *gaming-hole* — the defect that games the very oversight that just approved it. (No finding file yet captures the #248 catch specifically — see "Findings to write.")

**Evidence:**
- `release-gate-catches-its-own-missing-oversight.md` — the release gate re-validated a pinned tag and re-found the anti-gaming controls stranded off main; the missing fixes *were* the fail-closed controls.
- `the-distrust-check-exempted-its-most-important-target.md` — a release-gate self-review found a gaming-hole (code-review exempted from the distrust check) that had shipped through prior releases.
- `nondeterministic-review-gate-converges-on-zero-new.md` / `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` — every release-gate run surfaces a genuine new governance finding; "pass" is zero-NEW, never zero.
- `cross-vendor-review-finds-real-bugs.md` — the decorrelation mechanism the last-line gate relies on demonstrably yields real bugs.
- **#248 / session 2026-06-15** — the v0.3.0 release gate caught a governance gaming-hole the entire inner loop passed (no finding file yet).
- `gate-on-computed-signal-not-self-reported-verdict.md` (#814) — the v0.4.2 **pre-release** validation pass caught three independent fail-opens in the oversight machinery itself, none surfaced by the reviewers that had approved the code; the last-line gate's characteristic catch is the fail-open in the gate set.
- *(#695 / #815)* — the last-line gate was **institutionalized**: the overseer now runs a release-gate deep validation when an open release-request issue is detected — re-reads every per-step `summary.json` from `main`, re-checks tier/severity and sign-off-register completeness for required roles, and posts CLEARANCE or ESCALATE before any release authorization. The O8 layer became standing mechanism, not a manual pass.

**Cross-links:** O1 (no inner self-certification is final), O2 (a distinct last layer), O4 (it only works if it can't fail-open), O7 (its characteristic catch is a ratchet/gaming-hole defect).

---

## Cross-cutting lens (not an observation)

**Every HOS mechanism is an AI-native port of an established human software-engineering practice** — `hos-ports-human-software-engineering-best-practices.md`. Cross-vendor review = blind peer review; the worker/overseer two-account split = separation of duties; jidoka stop-the-line = the andon cord; SQC spot-check = acceptance sampling; the committed authorization artifact = a signed change record. The lens is **generative** (the next mechanism is the next un-ported practice) and **predictive** (a port fails silently exactly where the human practice relied on a precondition the AI context lacks — e.g. the human gate assumed a human is a *distinguishable actor*, which is false under a shared identity, so it was forgeable until separate machine accounts + server-side enforcement closed it). Applied as a reading lens across the observations above, not counted as one of them. Audit each mechanism for the implicit precondition of the human practice it ports — that gap is where the next bug lives (cf. O4's fail-open, O6's identity gap).

---

## Relevance summary

| Obs | Headline | Tag |
|---|---|---|
| O1 | AI can do the work but cannot self-certify it | `[core]` |
| O2 | Oversight is a layered system; blind to any dimension with no layer | `[core]` |
| O3 | The cheap independent check gets skipped unless forced | `[core]` |
| O4 | Oversight tooling must fail loudly | `[signal]` |
| O5 | Structuring an artifact *is* an audit | `[signal]` |
| O6 | The human's naïve use-question cuts to the real gate | `[core]` |
| O7 | Re-derive, never trust; ratchet (tighten-only) | `[core]` |
| O8 | The last-line independent gate catches what the inner loop missed | `[core]` |
| — | Lens: every mechanism ports a human SWE practice | (lens) |

---

## O9 — An agent given a broad mandate behaves like a human developer given the same mandate. `[core]`

**When given open-ended autonomy, the AI worker exhibited the same systematic biases as a human developer: scope creep into future milestones, definition-of-done drift (done = queue empty, not all gates green), batch-over-incremental PRs, and immediate implementation of nearby work not in scope.**

Scott's comment on observing these patterns: *"Oh, it's behaving just like a human dev."* This is not a failure of intelligence but of incentive alignment: without explicit structural constraints, the agent — like a human — defaults to "interesting work nearby" and "done when no tasks visible." The fix is identical to what works for human teams: milestone gates, PR size limits, explicit quality gates as mandatory pre-conditions (not advisory), and loop operating procedures that name the exact stopping condition. Explicit structural constraints in the CORE prompt work; implicit expectations do not.

**Evidence:**
- `ai-agent-scope-drift-mirrors-human-dev-behavior.md` — systematic documentation of the pattern and its structural fixes.
- `#401` (PR too large), `#403` (stopped before quality gates met), `#404` (worked outside milestone)
- `autonomous-worker-restacks-redundant-work.md` (#850, #880) — running cycle-to-cycle, the worker branched from state already in `main`/a sibling PR and re-proposed shipped work — the failure a human dev avoids by reflexively rebasing; fixed by making "is this already done?" a mechanical, fail-closed pre-PR check (git-cherry patch-id + open-PR SHA overlap).
- *(#901)* — the worker selected work purely by lowest issue number, so urgent items waited behind routine lower-numbered ones (the human-dev "just take the next ticket" bias); fixed with explicit `priority:*` ordering, FIFO within a band, sourced from one shared `next_candidates.jq` so both selection paths can't diverge.

**Cross-links:** O3 (the cheap check gets skipped unless forced), O6 (the human's naïve question cuts to the real gate), O1 (the loop trusts its own local state the way an agent trusts its self-report).

---

## O10 — An autonomous agent loop requires an exhaustive enumeration of what to check, not a conceptual description. `[signal]`

**The agent checked PR mergeability but not review bodies or comments — missing CHANGES_REQUESTED reviews for 2+ hours on multiple PRs. The gap was precisely the set of things not explicitly enumerated.**

An agent defaults to the *narrowest* interpretation of an instruction that satisfies its surface. "Check the PR" is interpreted as "check the field the system has a name for" (mergeable), not as "read all the artifacts attached to the PR." This is the same failure mode as the silent no-op gate bug: the agent does the minimum that satisfies the instruction without violating it. The fix is the same: enumerate exactly what to check. "Check reviews for CHANGES_REQUESTED with body content" is actionable; "monitor the PR" is not.

**Evidence:**
- `agent-misses-pr-feedback-without-explicit-review-read.md`
- `#411`, `#414` — filed twice against the same root cause
- Issue #358 (silent no-op gate) — the same pattern in a different domain
- *(#867)* — the inverse of #411/#414: the worker checked PR **review state** but not **mergeable state**, so a CONFLICTING PR carrying a prior APPROVED review was routed as "awaiting-merge" and skipped. Each routing decision must enumerate *every* attached signal (mergeable **and** review **and** comments); the agent defaults to the one field the system has a name for. Fixed by checking mergeable first in the routing loop.

**Cross-links:** O3 (explicit forcing is required), O4 (must fail loud — missing the check = silently passing a failing gate).

