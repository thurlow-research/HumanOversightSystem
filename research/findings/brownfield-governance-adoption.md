# Finding: Governance Frameworks Applied to Existing Codebases Require a Bounded Suspension Mechanism

**First observed:** 2026-06-12, issue #22 (raised by CondoParkShare brownfield experience)
**Documented in:** `contract/gate-suspension.template.md`, `docs/OVERSIGHT-RUNBOOK.md` — Brownfield Onboarding

---

## The Finding

HOS was designed for greenfield projects — a clean codebase that passes all gates from the first commit. When applied to an existing codebase (brownfield), all gates fail simultaneously. This creates a paradox:

- Without any bypass: the team cannot commit anything until every existing violation is fixed at once — which may be weeks of work with no intermediate commits
- With a blanket bypass: governance is meaningless while the bypass is active — no prevention of new debt accumulation
- With no mechanism at all: teams invent ad-hoc bypasses (the CondoParkShare `NOT_APPLICABLE` stamp) that lack human authorization and leak back into the permanent framework

The finding: **governance frameworks need a first-class bounded suspension mechanism, or they will generate ad-hoc bypasses that lack the safety properties the framework was designed to provide.**

---

## The Brownfield Problem

CondoParkShare described the experience: HOS gates were added to an existing codebase, and everything failed at once. The team needed to work through the issues systematically, but had no framework-blessed way to do so. Their interim solution — a custom `NOT_APPLICABLE` stamp status — was:
- Not in the HOS sign-off taxonomy
- Not human-enforced by the gate (an agent could self-apply it)
- Not auditable in the same way as normal sign-offs

This is a clear instance of the "governance rules without verification mechanisms" pattern: when the framework doesn't provide a legitimate path, practitioners create illegitimate ones that lack the safety guarantees.

---

## The Resolution Pattern

The suspension mechanism that resolves this has five key properties:

1. **Human-only authorization.** The suspension file cannot be created by an agent. An agent discovering that a gate is failing cannot suspend it — only a human can. This preserves the "agents cannot weaken their own oversight" guarantee.

2. **Per-reviewer granularity.** Suspend exactly what fails, not everything. This matches how brownfield remediation actually proceeds: you fix one domain (e.g., lint), verify it's clean, re-enable that reviewer, then move to the next. If you suspend everything, you lose the protection of reviewers in domains you've already cleaned up.

3. **Re-enable one at a time.** The invariant "re-enabled gates stay on" is the mechanism that prevents brownfield remediation from becoming permanent permission to accumulate debt. Once a domain is clean and its gate is re-enabled, any future failure in that domain is a regression that must be fixed.

4. **Auditable in git.** The suspension file is committed to version control. The git log shows exactly when each gate was suspended, when it was re-enabled, and who authorized each change. This makes the remediation process observable and auditable.

5. **Re-enable log as remediation evidence.** The template includes a re-enable log table. Each entry records that a domain was cleaned up, when, and by whom. This log is the empirical record that brownfield adoption is progressing systematically rather than using suspension as permanent permission.

---

## Implications for Research

1. **Governance adoption is a staged process, not a binary.** A framework that can only be adopted by clean codebases will not be adopted by projects with existing technical debt — which is most real projects. The adoption mechanism must account for staged compliance.

2. **Bounded suspension is safer than no suspension.** A framework with a well-designed suspension mechanism (human-authorized, per-reviewer, auditable, time-bounded by domain) produces better outcomes than a framework with no mechanism — because practitioners will create bypasses anyway, and ad-hoc bypasses lack safety properties.

3. **The re-enable invariant creates a forcing function.** "Once re-enabled, stays on" is not just a rule — it's a governance property that makes the suspension mechanism useful. Without it, the suspension becomes a permanent permission to ignore the gate. With it, the suspension becomes a bounded remediation window with a clear endpoint.

4. **Brownfield adoption as an empirical test.** Applying HOS to CondoParkShare's existing codebase is an empirical test of the framework's adoptability claims. The friction encountered (everything fails at once, ad-hoc bypass invented) is data about where the framework's greenfield assumptions break down. The gate suspension mechanism is a direct response to that empirical observation.

---

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — the `NOT_APPLICABLE` ad-hoc bypass was an unverifiable rule; the suspension mechanism is the framework-blessed alternative with proper verification
- `stamp-based-ci-enforcement.md` — related pattern: committed artifacts as enforcement primitives; the suspension file is a committed artifact that proves human authorization
