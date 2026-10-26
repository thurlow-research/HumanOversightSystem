# Prompt Artifact — security_scan_logic.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/security_scan_logic.py` (also `tests/oversight/test_security_scan_exemptions.py`, `scripts/oversight/requirements.txt`) |
| **Description** | #2147 certifi floor + black/otel time-boxed exemptions |
| **Date** | 2026-10-25 (first slice built 2026-10-23) |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending (CODEOWNERS review of the PR) |

---

## Prompt

The specification is the #2147 issue body (2026-10-23) together with the human ruling on #2147 (ScottThurlow, 2026-10-25T22:05:14Z):

> Q1: A — add a fifth time-boxed exemption for opentelemetry-api CVE-2026-114603 (expires 2027-01-31) with a tracking issue and a premise test. Q2: A — the certifi floor is authorized by this comment; open the PR. Please also file a follow-up so floors on already-installed transitive packages do not trip Condition 10.

Worker prompt to `coder` for the 2026-10-25 slice. These are the essential instructions, quoted:

```
In scripts/oversight/security_scan_logic.py SUPPRESSIONS, add an `Exemption` for
package `opentelemetry-api`, advisory_id `CVE-2026-114603`, fixed_in `1.45.1`,
expires 2027-01-31, tracking_issue 2179. Mirror the existing mcp CVE-2026-59951
record exactly in shape and tone (a `# What:` comment plus a `reason=` that states
exactly what was checked). VERIFY each fact yourself before writing it, and say
only what you verified: [TraceState.from_header O(N^2) on inbound tracestate;
HOS never imports opentelemetry; arrives only via semgrep; semgrep pins
opentelemetry-api~=1.37.0; semgrep's only propagate.extract call carries only
traceparent; no server-side instrumentation]. Name the premise test(s) in the
reason as the mcp record does with PR4/PR5. Add a ruling bullet to THE RULINGS.

In tests/oversight/test_security_scan_exemptions.py add premise tests in the style
of PR4/PR5 enforcing at least: (a) no tracked .py file imports `opentelemetry`
(narrow, asserted exclusions only); (b) no tracked file calls propagate.extract /
TraceContextTextMapPropagator or sets up opentelemetry server instrumentation.
Update any test that asserts the number of roster records. Each new test must
fail if its premise is broken.

Do not change the black cap, the requirements floors, or anything outside these
two files.
```

## Constraints Specified

- Exemptions are visible, individually justified, time-boxed (2027-01-31) and tracked (#1961 for black, #2179 for opentelemetry-api). Nothing is permanent or silent.
- The black cap (`black>=24.0,<25.0`, #103) is unchanged.
- certifi is cleared by a requirements floor, not an exemption.
- Every exemption premise is enforced by a test.

## Refinement History

- v1 (2026-10-23): certifi floor, black CVE-2026-114134 record, PR3 widened, PR3b. The opentelemetry-api floor turned out to be uninstallable (semgrep pin), so it was escalated as Q1.
- v2 (2026-10-25): opentelemetry-api exemption plus PR6/PR6b/PR7, per the Q1=A ruling.

## Human Review Notes

<!-- Filled in at CODEOWNERS review. -->
