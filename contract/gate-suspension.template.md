# Gate Suspension — Brownfield Remediation

<!--
  HUMAN ONLY. Agents must not create or modify this file.
  Creating this file without human authorization is a protocol violation.

  PURPOSE: Temporarily suspend enforcement of specific gates/reviewers while
  working through existing issues in a brownfield codebase. Use this when
  adding HOS to an existing project that doesn't yet pass all gates.

  PROCESS:
  1. Human copies this template to contract/gate-suspension.md
  2. Human fills in the authorization fields and lists suspended gates
  3. Commit the file — the suspension is now auditable in git history
  4. As each gate's issues are resolved, remove that line from "Currently suspended"
     and add an entry to "Re-enable log"
  5. When all gates are re-enabled, delete contract/gate-suspension.md entirely

  INVARIANT: Once a gate is re-enabled (removed from suspension), it stays on.
  Do not re-suspend a gate that has already been re-enabled — fix the regression instead.
-->

Authorized by: [Your name]
Date: [YYYY-MM-DD]
Reason: [Why enforcement is suspended — e.g., "Brownfield onboarding: applying HOS to existing CondoParkShare codebase. Gates suspended initially; re-enabling reviewer by reviewer as each domain is remediated."]

# Required if suspending security or privacy reviewer on HIGH-risk steps.
# Confirms you understand that HIGH-risk changes are proceeding without security review.
# Remove this line when security/privacy are re-enabled.
# security-suspension-acknowledged: yes

---

## Currently suspended

<!-- One line per suspended gate/reviewer. Remove a line to re-enable that gate. -->
<!-- Gate names match the role keys in contract/step-manifest.yaml role_mappings. -->
<!-- Script gate names: lint, secrets, security, types, template-refs, portability, django -->
<!-- Sign-off role names: code-review, security, privacy, ui, a11y, infra, ops, reliability, test-unit, test-system, process -->
<!--
  Optional per-line flags:
    SUSPENDED: lint review-by: 2026-07-01   ← validator warns once this date passes
    SUSPENDED: types [pinned]               ← never auto-removed; remove manually

  AUTO-REMOVAL (scripts/oversight/suspension_manager.py):
    Pure SCRIPT gates (lint, secrets, types, template-refs, portability, django)
    that pass SUSPENSION_AUTO_REMOVE_RUNS consecutive checks are auto-removed
    (config SUSPENSION_AUTO_REMOVE=true, default) — re-enabling is the safe
    direction (the RATCHET: automation may tighten, never loosen). Reviewer-role
    suspensions and `security` (which has a reviewer counterpart) are NEVER
    auto-removed — they can only be removed by a human. The manager has no code
    path that adds a SUSPENDED line.
-->

<!-- Example — remove the comment markers and adjust to your situation:
SUSPENDED: lint
SUSPENDED: types
SUSPENDED: security
SUSPENDED: privacy
SUSPENDED: ui
SUSPENDED: a11y
SUSPENDED: infra
SUSPENDED: ops
SUSPENDED: test-unit
SUSPENDED: test-system
-->

---

## Re-enable log

<!-- Document when each gate was re-enabled, why it was safe, and who authorized it. -->
<!-- This log is the evidence that remediation is progressing systematically. -->

| Gate / Reviewer | Re-enabled | Notes | Authorized by |
|---|---|---|---|
| *(none yet)* | | | |
