# AIRA: Deterministic Scanner for AI-Code Failure Patterns

**Source:** Parris, W.M. (2026). *AIRA: AI-Induced Risk Audit — A Structured Inspection Framework for AI-Generated Code.* BDB Labs. arXiv:2604.17587  
**Zotero key:** 3SU9QZ6F  
**Session:** 2026-06-18 (v0.5.0 triage from issue #431)

## Core finding

AIRA is a deterministic static analysis tool specifically calibrated for *failure untruthfulness* — the pattern where AI-generated code returns success signals while silently violating internal guarantees. General-purpose linters (SonarQube, Semgrep) are not calibrated for this failure class.

In a matched-control study of 955 AI-attributed vs. 955 human-authored files:
- AI files: 0.435 HIGH-severity findings/file
- Human files: 0.242 HIGH-severity findings/file
- **1.80× excess** consistent across JavaScript, Python, TypeScript

AIRA's deterministic scanner surfaced findings at a **44:1 ratio** vs. an LLM evaluator applied to the same code. LLMs exhibit the same suppression pattern in *evaluation* that AI coding tools exhibit in *generation* — they rate fail-soft code as acceptable.

## The 15 AIRA checks (highest-frequency first)

| Check | Name | Severity | Description |
|-------|------|----------|-------------|
| C01 | Success Integrity | HIGH | `return {"status": "ok"}` inside an `except` block after a failed critical operation |
| C02 | Audit/Evidence Integrity | HIGH | Audit log write can fail silently without halting execution |
| C03 | Broad Exception Suppression | HIGH/MED | `try/except` blocks that log and continue without re-raising |
| C13 | Confidence Misrepresentation | MED | Degraded output returned with no indication it is degraded |
| C04 | Distributed Fallback | LOW | Fallback logic scattered across functions rather than centralized |
| C14 | Test Coverage Asymmetry | HIGH/MED | Happy-path tests present, failure-path tests absent |

## Co-occurrence failure profiles

Certain combinations describe characteristic failure profiles and should trigger escalation:

| Co-occurrence | Profile |
|---------------|---------|
| C03 + C01 | Explicit failure concealment — escalate, block merge |
| C04 + C09 | Environment-shaped degraded assurance |
| C02 + C10 | System reports readiness despite losing audit guarantees |
| C13 (alone) | Makes other failures invisible to downstream consumers |

## Implications for HOS

1. **AIRA as CI gate** — deterministic, open-source, directly installable (`pip install aira-scanner`). Belongs in the gates layer alongside bandit and flake8.
2. **Validates existing HOS principle** — deterministic gates beat LLM votes 44:1 for this failure class. LLM agents are appropriate for semantic/intent review, not silent exception handling.
3. **Adds structure to reviewer checklist** — C01, C02, C03 align directly with HOS's existing "silent failure" concerns (issues #358, #411, #403).

## Related HOS findings
- `llm-reviewer-can-mask-deterministic-scanner-failures.md` — complementary finding
- `gates-and-review-are-complementary.md`
