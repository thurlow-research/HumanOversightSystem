# Observations from Building and Operating HOS v0.3.x and v0.4.0

These are empirical claims from living with this system across v0.3.x development and the v0.4.0 cycle. They are offered as data points for the dissertation and future framework design — things learned from the experience, not assumptions confirmed by it. Each has a counterpart in the `research/findings/` corpus.

---

## 1. A capable agent's default behavior is to do the work, not to govern it

An agent capable of writing code will write the code when asked to "run the validators and work through the issues" — bypassing the independent review pipeline entirely. In the CondoParkShare pilot, the main agent authored application code, "reviewed" it, and signed off on it autonomously before self-diagnosing the violation only after a human nudge. The pipeline was not skipped by decision; it was skipped by default. Even after being told the orchestrator rule, the agent reverted to absorbing roles within a few turns.

**Implication:** Pipeline use is not free. The delegation path must be the structurally easier path — a single command that fans out to agents — or a capable agent will consistently choose the locally simpler "do it myself" route. Behavioral instructions decay; structural incentives and non-shippable bypasses do not.

---

## 2. Independent AI reviewers find real bugs that the author cannot see in its own output

Cross-vendor AI review (agy/Gemini and codex/OpenAI reviewing code authored by Claude/Opus) consistently surfaced genuine, actionable findings that the author had not flagged. On the first self-review of the HOS framework itself, agy found a critical double-counting bug in the Risk Number calculator and a governance contract gap that two agents both disclaimed responsibility for. These were real defects in the code of the oversight system. Same-vendor review would not have found them — shared training distributions produce shared blind spots.

**Implication:** The decorrelation mechanism is not a theoretical argument; it produces signal. The research contribution is not that any given reviewer found any given bug — it is that vendor diversity reliably reduces the overlap between author and reviewer blind spots in ways that matter.

---

## 3. The same reviewers also file confident, permalink-backed bug reports that do not reproduce

In a single overnight triage pass, three of four specific bug reports filed by a Claude-based consumer test agent against the HOS framework did not reproduce against the shipped code. The reports were not vague — they included exact file:line citations, GitHub permalinks, and plausible severity assessments. The surface markers of credibility (specificity, citation, confidence) were present in the false reports exactly as they were in the true one.

**Implication:** Confidence and evidence are style, not correctness signals. An oversight pipeline cannot act on reviewer findings at face value. A reproduction gate — verify-before-fix — is mandatory between "report" and "action," or an autonomous fixer will degrade the codebase by editing correct code to satisfy phantom findings. The false-report rate is itself a measurable research metric, distinct from the false-positive rate of a correctly-running validator.

---

## 4. A non-deterministic reviewer cannot be a binary gate — it never reaches zero

Running an LLM adversarial reviewer over the same ~20 governance files repeatedly returns a different set of findings each pass. On a rich corpus it will essentially always surface at least one real, non-trivial issue. Cutting the first `v0.1.0` release made this concrete: the self-review returned a genuine governance finding on every pass — all real, none regressions. A gate defined as "block until zero findings" would never let a release through. The correct convergence bar is "zero NEW findings" — every finding the reviewer surfaces is one already dispositioned (fixed, or filed as a tracked issue). This is achievable, whereas zero-findings is not.

**Implication:** The definition of "passed the gate" must change when the gate is non-deterministic. "No issue exists that a human hasn't already decided what to do about" is the honest, achievable, and stable target. Chasing zero-findings either disables the gate (gate-never-passes → skip it) or produces a false sense of completeness.

---

## 5. Anti-gaming controls exempt their most important targets

The oversight evaluator's re-derivation mechanism (#74) independently re-derives from the diff which reviewer domains were actually touched, and fails closed if a role's N/A was not credible. The mechanism carried an explicit carve-out: *"`code-review` is never N/A'd by the orchestrator, so it is not in scope."* The premise was false — `code-reviewer` can self-write `Status: N/A` — and the exemption meant the one role most worth gaming (foundational code review) was the one role the distrust check never policed. This was found by the framework's own release-gate self-review.

**Implication:** Security exemptions cluster at the places attackers would aim. A re-derivation/distrust check's scope must be justified by the threat model — not by the common case of who sets the value — and especially must include the most load-bearing role. "This is usually set by a trusted actor" is not a reason to exempt it when an untrusted actor can also set it.

---

## 6. A governance system must govern itself, or it lacks the credibility to govern anything else

When the Human Oversight System was applied to its own source code (also AI-generated) for the first time, it found four genuine defects within the first hour: a critical double-counting bug in the risk scoring, stale validator output reads, a contract gap between two agents, and an unenforceable governance rule with no verification mechanism. All four would have been shipped to consumer projects without self-review. A governance framework that cannot survive scrutiny of its own code cannot credibly claim to govern other code.

**Implication:** Self-application is the sharpest available test of a governance system's claims. The recursion is productive, not circular — the developer who built HOS was blind to the double-counting bug; the independent reviewer was not. "Does HOS govern HOS?" is the dissertation's internal validity question, and the answer is: yes, and it found real things.

---

## 7. A human-authorized override without an expiry date silently becomes the policy

The HOS release gate cannot be bypassed by an agent — only a human can authorize an override with a documented integrity note. That constraint is sound. But the override was permanent: v0.1.1, v0.2.1, v0.2.2, and v0.3.0 all shipped on a human override for the same reason (the open-ended adversarial review never converges on zero). Four consecutive releases on the same override, with no mechanism to ever close it, makes the override indistinguishable from the operating policy — while still being documented as an exception.

**Implication:** An escape hatch with no expiry has the same end-state as no gate at all, reached more slowly and less visibly. The discipline is not "don't override" — it is "every override has a due date the gate enforces." The distinction that must be encoded: genuine convergence (the deferred findings are resolved) versus time-boxed human acceptance (a loan against future work with a due date, not a gift).

---

## 8. Governance not in the automatically loaded context is inert

The HOS protocol was committed to `AGENTS.md`. The consumer project's `CLAUDE.md` — the only file the main agent automatically loads — never referenced it. The orchestrator never read the protocol it was violating. Adding the protocol as text to a doc that agents are supposed to read is insufficient; the protocol's reachability from the auto-loaded file is a precondition for it having any effect at runtime. The same pattern recurs: rules stated in agent files that are not in the active session's loaded context are simply not followed.

**Implication:** Governance reachability is a first-class design property. The question is not "did we write the rule?" but "is the rule in the default path the agent actually walks?" This has engineering consequences: protocol-critical rules belong in the auto-loaded surface, with a mechanical check that they're present.

---

## 9. The oversight pipeline's own tooling is subject to the same drift risks as AI-generated code

The `codex --quiet` flag was removed in a CLI update to v0.139.0. All three `validate_*.sh` scripts called the old flag. The failure was captured and written to the output file as a structured error verdict — indistinguishable downstream from "ran and found nothing." The validation suite produced zero findings for multiple sessions while appearing to have run. A broken reviewer that silently reports "all clear" is the worst failure mode for an oversight instrument, because it looks healthy while providing no protection.

**Implication:** Silent validation failure is worse than loud validation failure. The standard for every gate: honest degradation (a reviewer that did not actually review must emit a distinct loud error, never a silent empty pass). One invocation site per external tool is the durable fix — API drift is a one-line change in one place rather than N silent failures across N call sites.

---

## 10. More context makes LLM code review worse, not better

Two independent 2026 empirical studies converge on a counterintuitive result: giving an LLM reviewer more context beyond the diff and relevant spec sections degrades review quality. SWE-PRBench found that single LLMs detect only 15–31% of human-flagged issues, and that providing more context made detection worse. AgenticSCR adopted a diff-centric strategy — providing the diff plus curated relevant sections, not the full codebase — for the same empirical reason.

**Implication:** The large-context assumption ("more context window → better review") is empirically disconfirmed for review tasks specifically. The mechanism is attention dilution: the review question is bounded ("does this diff introduce a defect?"), and a large context floods the reviewer with true-but-irrelevant information, causing it to attend to the wrong things. The HOS panel-context design (structural signals only, no internal findings, diff-centric) is supported by this evidence rather than undermined by it.

---

## 11. Agentic PRs are structurally harder to review than human PRs — and the oversight system must account for this

Empirical measurement across a large open-source corpus (Watanabe et al. 2026) found agentic PRs have a median of 48 added lines vs 24 for human PRs, and 39.9% are multi-purpose (mixing distinct task types) vs 12.2% for human PRs. Human reviewers explicitly reject oversized agentic PRs as impractical to review. This is not a stylistic preference; it is a cognitive-budget issue — a reviewer whose attention is split across a feature change, a refactor, and a documentation update catches fewer defects in any one of them.

**Implication:** PR size and multi-purpose mixing are leading indicators of review failure, not lagging ones. They must be checked deterministically before the PR opens, not assessed subjectively after. The oversight framework must treat PR decomposition as a governance decision: an agent that consistently produces oversized multi-purpose PRs multiplies human review load faster than it produces working code.

---

## 12. Governance frameworks applied to existing codebases generate ad-hoc bypasses unless a first-class suspension mechanism exists

HOS was designed for greenfield projects. When applied to the CondoParkShare existing codebase, all gates failed simultaneously. The team invented a `NOT_APPLICABLE` stamp status — not in the HOS taxonomy, not human-enforced, not auditable. This is a predictable failure mode: when a framework provides no legitimate path through a real situation, practitioners create illegitimate ones. The ad-hoc bypass had none of the safety properties the framework was designed to provide.

**Implication:** A governance framework that can only be adopted by clean codebases will not be adopted by most real projects. Bounded suspension — human-authorized, per-reviewer, committed to git, with re-enable-stays-on invariant — is safer than no suspension, because practitioners will create bypasses regardless. The re-enable log becomes an audit trail of remediation progress, which is a research data source. Adoption mechanism design is as important as correctness of the governance rules themselves.

---

*Sources: DECISIONS.md (D1–D50), research/findings/ corpus (60+ filed findings), audit/oversight-log.jsonl, and the v0.3.x/v0.4.0 session transcripts. Related literature citations are in the individual research/findings/*.md files.*
