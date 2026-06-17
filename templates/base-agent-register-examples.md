# Base Agent Sign-off Register Examples

When a target project installs the HOS framework, its base agents must write
sign-off entries to `.claudetmp/signoffs/step{N}-register.md` on approval.
These examples show the required format for each role type.

The oversight-evaluator reads these entries in Phase 1 compliance. Missing
required fields (Status, Agent, Artifact, Iterations) cause compliance failure.

---

## code-review entry
```
## code-review | parking/views.py, parking/models.py | 2026-06-11T14:30Z
Status: APPROVED
Agent: code-reviewer
Artifact: parking/views.py, parking/models.py, parking/managers.py
Iterations: 2
Critical_findings_resolved: false
Notes: Two blocking issues resolved in round 2: missing org scope on availability
  queryset (L84) and unused import. No remaining blocking issues.
```

## security entry (with critical finding)
```
## security | parking/views.py | 2026-06-11T15:10Z
Status: APPROVED
Agent: security-reviewer
Artifact: parking/views.py
Iterations: 3
Critical_findings_resolved: true
Notes: CRITICAL finding in round 1: TOTP replay window (CWE-294) at accounts/views.py:142.
  Resolved in round 2 by adding rate limiting. Round 3 verified rate limiting not bypassable
  via distributed requests. GitHub issue created: security-finding #47.
```

## privacy entry
```
## privacy | accounts/models.py | 2026-06-11T15:30Z
Status: APPROVED
Agent: privacy-reviewer
Artifact: accounts/models.py, accounts/views.py
Iterations: 1
Critical_findings_resolved: false
Notes: Clean review. Phone field is field-encrypted per ADR. No PII in log statements.
```

## test-unit entry (includes §4 test declaration fields inline)
```
## test-unit | tests/ | 2026-06-11T16:00Z
Status: APPROVED
Agent: unit-test
Artifact: tests/test_booking_gates.py, tests/test_horizon_metric.py
Iterations: 3
Critical_findings_resolved: N/A
Coverage_pct: 83
Mutant_score_pct: 77
Thresholds_met: true
Surviving_equivalents: 2
Equivalents_documented: true
collection_errors: 0
Notes: 80%/75% targets met after 3 rounds. Two surviving mutants documented as
  equivalent (see tests/test_booking_gates.py comments L234, L251).
  collection_errors: 0 — full suite collects cleanly (collection_integrity gate passed).
  Required on any build step that touches *.py files; omit only on non-Python steps.
```

## test-system entry (includes §4 test declaration fields inline)
```
## test-system | tests/system/ | 2026-06-11T16:30Z
Status: APPROVED
Agent: system-test
Artifact: tests/system/test_booking_flow.py, tests/system/test_auth.py
Iterations: 2
Critical_findings_resolved: N/A
Spec_flows_covered: [booking-flow, listing-flow, auth-totp, onboarding-invite]
All_passing: true
Notes: All §11 primary flows passing. PM signed off on test plan (process role).
```

## process entry (PM test plan sign-off)
```
## process | system-test-plan | 2026-06-11T13:00Z
Status: APPROVED
Agent: pm-agent
Artifact: system-test-plan for step 6 (booking gates)
Iterations: 1
Critical_findings_resolved: N/A
Notes: All §11 booking flows covered. PM requested addition of concurrent booking
  edge case — added to test_booking_flow.py before implementation.
```

## ESCALATED entry with human resolution
```
## security | auth/views.py | 2026-06-11T17:00Z
Status: ESCALATED
Agent: security-reviewer
Artifact: auth/views.py
Iterations: 5
Critical_findings_resolved: false
Human_resolution: 2026-06-11 — Reviewed 5-round loop with architect. Rate-limiting
  approach is sound; TOTP window tolerance at ±1 step is acceptable per RFC 6238.
  Proceeding with current implementation. Scott T.
Notes: 5-round loop exhausted on TOTP window tolerance dispute. Escalated to human
  per loop-exit protocol. Human resolution on record above.
```
