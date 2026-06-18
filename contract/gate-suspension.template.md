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
# reason_category — required in new suspension files (SPEC-378 R2). One of:
#   EMERGENCY            — a blocking production issue requires bypassing the gate; expected very short-lived.
#   PLANNED_MAINTENANCE  — a known, scheduled window where the gate would produce expected failures (migration, transient outage).
#   FALSE_POSITIVE       — the gate consistently triggers on a known non-issue here; a fix/gate-rule update is planned.
#   OTHER                — anything else; the prose Reason: above must make it unambiguous.
# Files created before SPEC-378 without this field are grandfathered (oversight-evaluator emits COMPLIANCE WARN, not FAIL).
reason_category: [EMERGENCY | PLANNED_MAINTENANCE | FALSE_POSITIVE | OTHER]

# Required if suspending security or privacy reviewer on HIGH-risk steps.
# Confirms you understand that HIGH-risk changes are proceeding without security review.
# Remove this line when security/privacy are re-enabled.
# security-suspension-acknowledged: yes

# ── Per-step authorization for HIGH-tier security-relevant steps (SPEC-83) ──
# A blanket security/privacy suspension is NOT sufficient for a HIGH-tier step that
# touches security-relevant surfaces (auth, payments, migrations, PII). Such a step
# requires EITHER per-step scoping here OR a per-step override at
# contract/tier-overrides/step{N}-human-tier-override.md (HUMAN ONLY).
# These fields are human-set; agents must not create or modify this file.
#
# per_step_scope (boolean, default false when absent — blanket, backward compatible):
#   When true, the security/privacy suspension applies ONLY to the steps listed in
#   `steps:` below. A HIGH-tier security-relevant step NOT listed is not covered.
#   security-suspension-acknowledged: yes is still required alongside per-step scoping.
# per_step_scope: false
#
# steps (required when per_step_scope: true — a non-empty list of step IDs that match
#   the `id:` field in contract/step-manifest.yaml; exact string match). Block-list or
#   inline form both accepted. Empty/absent while per_step_scope: true → COMPLIANCE FAIL.
# steps:
#   - step-3
#   - step-4
#
# grandfathered_until (optional, YYYY-MM-DD, human-set): transition deadline for the
#   blanket-suspension deprecation. Absent → no grandfathering (FAIL applies on a
#   HIGH-tier security-relevant step). Future date → COMPLIANCE WARN + CONDITIONAL_PROCEED.
#   Past/today → grandfathering period over → COMPLIANCE FAIL.
# grandfathered_until: 2026-12-31

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
