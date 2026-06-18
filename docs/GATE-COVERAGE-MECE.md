# HOS Gate Coverage — MECE Analysis

*Applies to HOS v0.4.0. Read alongside `METHODOLOGY.md` (pipeline overview) and `contract/OVERSIGHT-CONTRACT.md` (gate events).*

---

## How to read this document

**MECE** — Mutually Exclusive, Collectively Exhaustive — means every failure class appears in exactly one row, and together the rows span the full failure space the system is designed to detect or prevent. This analysis inventories which gate layers address each failure class, and where genuine gaps remain.

**Cell value legend:**

| Value | Meaning |
|---|---|
| **PRIMARY** | This gate layer is the first and primary detector for this class. It is where detection is expected and designed to happen. |
| **COVERS** | This layer independently catches the class; not the primary detector but a full backstop. A COVERS cell is defense-in-depth. |
| **PARTIAL** | This layer covers a subset or a specific variant of the class — not end-to-end. It provides signal, not a guarantee. |
| **NOT-COVERED** | This layer has no mechanism for this failure class. An absence of PRIMARY or COVERS across all columns is a genuine gap. |

Where a cell shows a 2–3 word rationale in parentheses, that is the key reason for the rating. Intentional overlaps (where two or more layers both show PRIMARY or COVERS) are the system's defense-in-depth; they are enumerated in the final section.

Column headers correspond to gate layers in pipeline order: deterministic validators run first; the human approval gate runs last.

---

## Coverage table

| Failure class | Deterministic validators<br>(`run_validators.sh`) | Gates<br>(`check_suspension`, lint, bandit, etc.) | Risk assessor / dep-mapper | Code reviewer<br>(inner loop) | Security reviewer | Privacy reviewer | Other reviewers<br>(reliability, ops, ui, a11y, infra) | Evaluator conditions<br>(Phase 1 + Phase 2) | Second review<br>(agy / codex) | Panel<br>(Copilot + vendors) | Overseer ceiling gate | Human approval gate<br>(protected surfaces) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **C01 — Silent exception suppression / fail-soft returns** | PARTIAL (static bandit score) | PARTIAL (bandit HIGH blocks) | PARTIAL (complexity signal) | PRIMARY (logic correctness) | PARTIAL (security-relevant paths) | NOT-COVERED | PARTIAL (reliability: missing timeouts) | NOT-COVERED | COVERS (adversarial lens) | COVERS (panel adversary) | NOT-COVERED | NOT-COVERED |
| **C02 — Auth / permission bypass** | PARTIAL (bandit auth patterns) | PRIMARY (security-HIGH blocks) | PARTIAL (floor rules: auth/**) | COVERS (design adherence) | PRIMARY (OWASP, auth lens) | NOT-COVERED | NOT-COVERED | COVERS (Cond 10: new-permission signal) | COVERS (codex adversary HIGH+) | COVERS (adversarial pass) | NOT-COVERED | PARTIAL (protected surfaces require human) |
| **C03 — PII leakage** | PARTIAL (ip_check Level 2) | NOT-COVERED | PARTIAL (PII path floor rule) | NOT-COVERED | PARTIAL (data boundary) | PRIMARY (PII inventory, GDPR) | NOT-COVERED | PARTIAL (Cond 10: new-auth-state) | COVERS (agy MEDIUM+) | COVERS (panel pass) | NOT-COVERED | PARTIAL (PII paths trigger HIGH/CRITICAL) |
| **C04 — Scope drift / spec deviation** | PARTIAL (prompt ambiguity score) | NOT-COVERED | PRIMARY (prompt-fidelity subagent) | COVERS (design adherence check) | PARTIAL (threat-model gaps) | PARTIAL (PII boundary gaps) | NOT-COVERED | COVERS (Phase 2: convergence, second review) | COVERS (agy semantic lens) | COVERS (panel spec-verify) | NOT-COVERED | NOT-COVERED |
| **C05 — Gaming the oversight mechanism itself** | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Cond 9–11: N/A re-derivation, tier-floor re-derivation, structural-override re-derivation) | PARTIAL (independent verdict) | PARTIAL (blind-panel decorrelation) | PARTIAL (register completeness before merge-authority) | COVERS (human-only governance artifacts; branch protection) |
| **C06 — Stale / inaccurate documentation** | NOT-COVERED | NOT-COVERED | NOT-COVERED | PARTIAL (design adherence implies doc currency) | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Phase 1: definition of done — docs must reflect what was built) | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED |
| **C07 — Test coverage gaps** | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Phase 1: Thresholds_met required; All_passing required) | PARTIAL (second review may flag gaps) | PARTIAL (panel may flag gaps) | NOT-COVERED | NOT-COVERED |
| **C08 — Dependency / supply chain risk** | PRIMARY (ip_check Level 1+2: ScanCode license gate, clean-room) | PARTIAL (secrets scan) | PARTIAL (dep-mapper blast radius) | NOT-COVERED | PARTIAL (external deps) | NOT-COVERED | NOT-COVERED | COVERS (Cond 10: new-external-dependency structural signal) | PARTIAL (agy: new dep review) | COVERS (IP agent: Level 1+2 on every panel pass) | NOT-COVERED | PARTIAL (dependency manifests under protected surfaces) |
| **C09 — Prompt injection / adversarial framing** | PARTIAL (hallucination surface score) | NOT-COVERED | PRIMARY (prompt-fidelity: prompt-vs-code semantic check) | PARTIAL (detects unexplained additions) | PARTIAL (suspicious code patterns) | NOT-COVERED | NOT-COVERED | COVERS (Phase 2: unexplained additions flag) | COVERS (agy independent framing) | COVERS (independent panel) | NOT-COVERED | NOT-COVERED |
| **C10 — Incorrect risk tier (understated)** | PARTIAL (composite score raises floor) | PARTIAL (path-glob floor rules) | PRIMARY (risk-assessor validates and can only raise tier) | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Cond 11: independent tier-floor re-derivation via change_classifier.py) | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED |
| **C11 — Missing required sign-offs** | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Phase 1: required_signoffs union check; all fields validated) | NOT-COVERED | NOT-COVERED | PRIMARY (register-completeness bounce-back gate) | NOT-COVERED |
| **C12 — Outdated human authorization artifacts** | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PRIMARY (Phase 1 Cond 12: head_sha binding; per-step scope check; grandfathering expiry) | NOT-COVERED | NOT-COVERED | NOT-COVERED | COVERS (branch protection requires live human approval) |
| **C13 — Cross-repo scope violations** | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | NOT-COVERED | PARTIAL (out-of-scope commit detection via reviewer Out_of_scope_commits: field) | NOT-COVERED | NOT-COVERED | COVERS (overseer reads Out_of_scope_commits:; bounces or escalates) | NOT-COVERED |

---

## Coverage gaps

These failure classes have **no gate layer that shows PRIMARY or COVERS** — they are areas of genuine residual risk in the current HOS design.

### C06 — Stale / inaccurate documentation (partial gap)

The evaluator's "definition of done" rule (Phase 1) requires that documentation reflect what was built before a step is signed off. However, this is a self-reported check enforced by agent behavior, not by a deterministic re-derivation. There is no automated tool that diffs behavioral claims in docs against the running code. The `doc-validator` agent (framework-dev, not shipped to consumers) provides some coverage in the HOS source repo itself, but consumer projects rely entirely on the inner-loop discipline.

**Residual risk:** A build step's docs may pass the evaluator's existence check (the doc was updated) but still contain inaccurate behavioral claims that no gate verifies.

### C13 — Cross-repo scope violations (partial gap)

The `Out_of_scope_commits:` register field and the overseer's bounce logic detect commits that do not belong in a PR's stated scope. However, the detection is reviewer-initiated: a reviewer must identify and flag the commit. No deterministic tool scans the diff for commits whose issue traceback does not match the PR's stated issue. Detection depends on reviewers reading commit messages and issue links.

**Residual risk:** A scope violation is caught only if a reviewer notices it. Automated detection (e.g., a CI check that validates each commit's `Closes:` or `Fixes:` trailer against the PR's associated issue) does not exist.

### C05 — Gaming the oversight mechanism (residual gap)

The evaluator's anti-gaming conditions (9–11, 14) re-derive N/A waivers, tier floors, structural-override signals, and authorization-file authorship from the diff and git history. However, the authorship check is WARN-only (CONDITIONAL_PROCEED), not a hard FAIL. Under the current shared-identity worker/human setup, a bot commit on a human account cannot be cryptographically distinguished from a legitimate human action. Full forge-proofing of governance artifacts is a known open item (see `research/findings/human-gate-enforcement-limits.md`).

**Residual risk:** An agent operating on the human's account could theoretically create or modify a human-only governance artifact (authorization file, gate-suspension.md). This is auditable post-hoc via git history but not prevented in real time by the current controls.

---

## Intentional overlaps (defense in depth)

The following failure classes are covered by multiple independent gate layers. These overlaps are by design — they implement the "decorrelated judgment" principle described in METHODOLOGY.md §2.

### C02 — Auth / permission bypass (five-layer coverage)

Gates block bandit HIGH findings before any reviewer sees the code. Security reviewer independently applies an adversarial auth lens. Evaluator re-derives new-permission signals from the diff. Second review (codex at HIGH+) applies an independent adversarial pass. Panel runs an independent adversary at HIGH/CRITICAL. The overlap reflects the highest-consequence failure class: a single missed auth bypass in production is a security incident.

### C08 — Dependency / supply chain risk (four-layer coverage)

`ip_check.py` (Level 1+2) scores license risk and clean-room provenance as a deterministic validator. The evaluator's Condition 10 catches new-external-dependency signatures in the diff independently of how the authoring agent classified them. The panel IP agent re-runs Level 1+2 on every PR. Protected-surface globs (`bootstrap/**`, `scripts/oversight/**`, `contract/**`) require human approval on changes to the framework's own dependency management.

### C10 — Incorrect risk tier (three-layer coverage)

The composite score from `run_validators.sh` sets a deterministic floor. The path-glob floor rules (`auth/**`, `**/migrations/**`, etc.) in `risk-assessor` set a separate deterministic floor independently of the composite. The evaluator's Condition 11 re-derives the tier floor from the diff using `change_classifier.py` and fails closed if the validated tier is below the floor with no human override. Three independent mechanisms must all agree before a tier is accepted as too low.

### C05 — Gaming the oversight mechanism (layered anti-gaming)

The evaluator's Conditions 9–11 and 14 each independently re-derive a self-reported value that controls whether oversight fires: N/A waivers (Condition 9), structural-override signals (Condition 10), tier floor (Condition 11), and auth/permission modifications (Condition 14). Each operates in the loosening-direction-only ratchet — re-derivation is skipped when upstream asked for *more* oversight. The overseer's bounce-back gate then re-checks register completeness before exercising merge authority, providing a second independent check after the evaluator.

### C11 — Missing required sign-offs (two-layer coverage)

The evaluator's Phase 1 checks the required_signoffs union (manifest + dynamic list from risk-assessor) and validates all required fields. The overseer's register-completeness gate re-checks completeness before applying merge authority. The two checks are structurally independent: the evaluator runs pre-PR, the overseer runs post-PR when considering merge.

---

*This document was derived from: `METHODOLOGY.md`, `docs/AGENTS.md`, `contract/OVERSIGHT-CONTRACT.md` §3 and §6a, `.claude/agents/oversight-evaluator.md` (Conditions 1–14), and `scripts/framework/protected_surfaces.txt`. It should be updated whenever new gate layers are added or failure classes are reclassified.*
