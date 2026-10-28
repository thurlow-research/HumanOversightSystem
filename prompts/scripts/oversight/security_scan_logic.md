# Prompt Artifact — security_scan_logic.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/security_scan_logic.py` (also `tests/oversight/test_security_scan_exemptions.py`, `scripts/oversight/requirements.txt`) |
| **Description** | #2194 mcp CVE-2026-116684/5/6 time-boxed exemptions + MCP-client premise test (earlier: #2147 certifi floor + black/otel exemptions) |
| **Date** | 2026-10-28 (earlier slices 2026-10-23, 2026-10-25) |
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
- v3 (2026-10-28, #2194): three mcp exemptions plus PR5b/PR5c, per the human ruling on #2194 (ScottThurlow, 2026-10-28T06:47:16Z):

  > Ruling: A, with changes. Add the three mcp exemptions (CVE-2026-116684/5/6), tracked in #2120, on the premise that HOS never imports mcp or runs an MCP client or server. Expiry 2026-12-31, or earlier as soon as semgrep allows a fixed mcp (1.30.0+), whichever comes first. Extend the PR4/PR5 premise tests to cover MCP clients (ClientSession, streamablehttp_client, sse_client). This matches mcp's install-only, never-run entry on the #2197 approved list.

  Worker prompt to `coder` (essential instructions): add three `mcp` `Exemption` records (fixed_in `1.30.0`, expires `2026-12-31`, tracking_issue 2120) after CVE-2026-59951, mirroring its shape, with reasons that state only verified facts and name their premise tests; the "earlier at 1.30.0+" clause is delivered by `fixed_in` (record goes inert once a fixed mcp is installed); add a RULINGS bullet; update R1 (eight records, separate `_EXPIRES_MCP_2194`); add a suppressed-at-1.29.0/kept-at-1.30.0 test; add a premise test scanning tracked scripts/bootstrap/bin/tests/workflows for `ClientSession|streamablehttp_client|sse_client` with narrow asserted exclusions, plus a pattern test; update the X5 docstring cliff; touch no other file. CVE-2026-59951 keeps its 2027-01-31 expiry.

## Human Review Notes

<!-- Filled in at CODEOWNERS review. -->
