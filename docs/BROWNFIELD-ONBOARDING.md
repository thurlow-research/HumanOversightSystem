# Brownfield HOS Onboarding — Recommended Approach

This guide is for teams applying HOS to an **existing codebase** that was built without it. When you add all gates at once, everything fails simultaneously. This guide provides a recommended order for clearing gates so you gain protection progressively without being blocked indefinitely.

See `docs/OVERSIGHT-RUNBOOK.md` — Brownfield Onboarding section for the mechanical steps (creating `contract/gate-suspension.md`, re-enabling gate by gate, etc.). This document covers **why** this order and what to expect at each stage.

---

## The principle

Re-enable gates in order of **risk severity, then mechanical ease**. The goal is:
1. Get the most critical protections in place first — prevent new vulnerabilities from accumulating while you work
2. Clear mechanical gates before review gates — static analysis is less subjective than reviewer judgment
3. Clear security-adjacent gates before coverage/style gates — a codebase with lint errors is annoying; one with security holes is dangerous

---

## Recommended re-enable order

### Stage 1 — Stop the bleeding (Day 1–2)

These protect against the most severe classes of new debt. Clear these before anything else.

**1. `secrets` gate (`secret_scan.sh`)**
Why first: hardcoded secrets committed during brownfield work are catastrophic and irreversible once pushed. Clear this immediately — audit for existing secrets, rotate any found, enable the gate.

**2. `security` gate — HIGH severity (`security_scan.sh`)**
Why early: HIGH-severity bandit findings (e.g. SQL injection, command injection) are the most exploitable issues. Clearing this early ensures no new critical vulnerabilities accumulate. Note: existing issues may be numerous — triage and fix the HIGH findings first, suppress with `# nosec` only where genuinely not exploitable.

If you must suspend `security-reviewer` sign-off during this stage, add `security-suspension-acknowledged: yes` to your suspension file to confirm you understand the exposure.

---

### Stage 2 — Static correctness (Day 3–5)

**3. `lint` gate (`lint_check.sh`)**
Why next: lint errors indicate code style debt but not security issues. Run the auto-formatter (black, isort) on the whole codebase in one commit — this is mechanical and low risk. Once done, enable the gate and it stays clean.

**4. `types` gate (`type_check.sh`)**
Why here: type errors surface logic bugs that may not be caught by tests. More work than lint but still mechanical — add type: ignore comments where fixing is out of scope, enable the gate.

**5. `template-refs` gate (`template_refs_check.sh`)**
Why here: missing templates cause runtime errors. Usually a quick fix — add missing templates or fix references.

---

### Stage 3 — Review gates (Week 2)

Once the mechanical gates are clean, enable the reviewer sign-offs one at a time.

**6. `code-review` sign-off**
The baseline review. Start with new code only — don't require retroactive code review of all existing code. Configure the step manifest to require code-review on new steps going forward.

**7. `security` sign-off (security-reviewer)**
Re-enable after Stage 1 security gate is clean and you're confident new code is being reviewed for security. At this point, remove `security-suspension-acknowledged` from the suspension file.

**8. `privacy` sign-off (privacy-reviewer)**
If your project handles PII, enable this alongside or immediately after security.

**9. `test-unit` sign-off**
Start with the configured threshold (default 80%/75%). If existing coverage is lower, set a lower initial threshold in `step-manifest.yaml` and raise it incrementally — but set a timeline and stick to it.

---

### Stage 4 — Advanced gates (Week 3+)

**10. `infra` sign-off (infra-reviewer)**
Enable when infrastructure config has been cleaned up and stabilized.

**11. `ops` sign-off (ops-reviewer)**
Enable after `TELEMETRY-SPEC.md` exists and the basic observability instrumentation is in place.

**12. `reliability` sign-off (reliability-reviewer)**
Enable when the codebase has been audited for timeout/retry patterns on outbound connections.

**13. `test-system` sign-off**
Enable when functional tests exist for the primary spec flows. This may require writing tests for existing behavior — plan accordingly.

---

## What to expect

**It will take longer than you think.** A codebase with 2 years of pre-HOS development may have 200+ lint errors, 50+ type errors, and multiple HIGH security findings. Budget time to fix these properly rather than suppressing them all.

**Don't suppress what you can fix.** `# nosec` and `# type: ignore` are acceptable where the issue is a genuine false positive or fixing is genuinely out of scope. They are not acceptable as a way to avoid doing the work.

**The re-enable invariant holds.** Once a gate is re-enabled, it stays on. If a regression occurs, fix it — don't re-suspend. The whole point of the staged approach is that once a domain is clean, it stays clean.

**Track progress visibly.** The re-enable log in `contract/gate-suspension.md` is your progress record. Each row represents a domain that is provably clean. This log is also research data — it shows how long brownfield HOS adoption takes in practice.

**Let the manager re-enable for you.** `scripts/oversight/suspension_manager.py` removes the manual bookkeeping burden:
- `--census` — prints active suspensions, warns on any past their optional `review-by:` date, and logs a `suspension-census` health metric (so "14 suspensions still open after 3 months" is visible, not buried).
- `--check` — runs each auto-checkable script gate (lint, secrets, types, template-refs, portability, django) and records pass/fail history.
- `--auto-remove` — when a pure script gate has passed `SUSPENSION_AUTO_REMOVE_RUNS` consecutive checks (default 3) it is removed automatically and logged. This handles the case where a busy human forgets to re-enable a gate that is already clean.

Two safety properties: a suspension marked `[pinned]` is never auto-removed (use it when you want a gate to stay suspended despite passing); and reviewer-role suspensions and `security` (which has a reviewer counterpart) are never auto-removed — a passing script can't stand in for a human review. The manager can only ever *remove* suspensions, never add one — the ratchet (`research/findings/ratchet-principle.md`). Set `SUSPENSION_AUTO_REMOVE=false` in `config.sh` to disable auto-removal and get nudges only.

---

## Security-specific note

If you must ship features during Stage 1 while the security gate is suspended:
1. Add `security-suspension-acknowledged: yes` to `contract/gate-suspension.md`
2. Manually review any new code that touches authentication, authorization, data access, or external calls
3. Document what you reviewed and where in the PR description
4. Make clearing the security gate the explicit top priority

The oversight-evaluator will issue a CONDITIONAL_PROCEED (not ESCALATE) on steps with suspended security review and the acknowledgment present, so work can continue while the risk is visible.

---

## See also

- `docs/OVERSIGHT-RUNBOOK.md` — mechanical steps for creating and managing the suspension file
- `contract/gate-suspension.template.md` — template to copy
- `docs/CUSTOMIZATION.md` — how to configure optional reviewers (ops, reliability)
