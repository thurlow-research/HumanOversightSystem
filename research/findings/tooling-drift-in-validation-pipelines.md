# Finding: Validation Pipelines Are Vulnerable to Silent Failure from Tooling Drift

**First observed:** 2026-06-12, session `2026-06-12-ux-designer-validation-suite.md` (Part 2)

---

## The Finding

A validation pipeline that invokes external CLI tools can be silently disabled when those tools change their APIs. The failure mode is particularly insidious: the pipeline appears to run, the scripts produce output files, the final verdict is written — but the validation phase that depended on the changed tool produced no findings, because the tool invocation failed silently.

The concrete instance: all three `validate_*.sh` scripts used `codex --quiet < tmpfile`. When codex was updated to v0.139.0, the `--quiet` flag was removed and replaced with a subcommand interface (`codex exec`). The scripts called `codex --quiet` and captured the output via `|| result='{"error":"..."}'` — but since the flag change caused an argument error (not a total failure), the error was suppressed and the fallback error JSON was written to the output file. The phase appeared to complete with an error verdict, which was then read as "codex failed to invoke" and treated as infrastructure noise rather than a systemic validation failure.

The validation suite ran for multiple sessions producing "codex failed" results before the flag change was diagnosed.

---

## Why This Matters

**Silent validation failure is worse than no validation.** A validation step that consistently errors is noticed and investigated. A validation step that appears to complete but produces no real findings is treated as "nothing wrong" — which is the false negative scenario the oversight system is designed to prevent.

**CLI tools change their APIs independently of the validation code.** The `codex` CLI is maintained by OpenAI; the `agy` CLI is maintained by Antigravity/Google. Neither vendor coordinates their API changes with the HOS validation scripts. The validation scripts are a consumer of these CLIs, and consumers bear the maintenance burden of keeping up with upstream changes.

**The governance system's own tooling is subject to the same risks as any software dependency.** The HOS methodology flags hallucinated APIs and recently-changed behavior as risks in AI-generated code. The same risk applies to the oversight tooling itself.

---

## The "Always Diagnose" Rule

This finding prompted the establishment of a governance rule that was added to agent definitions and memory:

> **When a validation step fails, always diagnose why and correct if you can. Tooling failures must be fixed and the phase rerun — never skipped. Skipping any required validation step requires explicit human approval.**

Without this rule, the natural tendency is to treat a recurring `codex failed` error as infrastructure noise and proceed. With it, the failure becomes a blocking diagnostic task.

The rule has two parts that work together:
1. *Never skip* — prevents the validation gap from becoming normalized
2. *Always diagnose* — converts tool failures into maintenance tasks rather than shrugged-off anomalies

---

## Detection and Fix

Detection came from the user asking "should we try rerunning codex since it failed?" — prompting a diagnosis rather than accepting the failure. The fix was:
1. Run `codex --help` to discover the new subcommand interface
2. Replace `codex --quiet < "$tmpfile"` with `codex exec < "$tmpfile"` in three scripts
3. Confirm with a smoke test before rerunning the full suite

The diagnostic took under 5 minutes once the question was asked. The fix was a one-line change in each script. The risk was that it had been silently skipped for multiple sessions.

---

## Generalizations

**Pinning CLI versions would prevent this, at the cost of missing security updates.** A versioned install (e.g. `codex@0.138.0`) would have kept the `--quiet` flag working, but would also delay security patches. The right tradeoff depends on the project's risk profile.

**A canary smoke test for each external CLI would detect API changes immediately.** A minimal smoke test (`codex exec "return an empty JSON object"` checking for a parseable response) run at validation startup would fail fast on API changes rather than silently producing empty output.

**The fallback pattern `|| echo '{"error":"..."}' ` requires careful error classification.** The current fallback treats any tool failure as a non-finding ("codex failed" = skip this reviewer). An alternative would be to treat tool failures as blocking (fail the phase) unless explicitly marked as acceptable. The tradeoff: blocking on transient failures (rate limits, auth expiry) creates friction; silently accepting them creates the risk above.

---

## Evidence

From `research/sessions/2026-06-12-ux-designer-validation-suite.md` (Part 2):

> All three validate scripts used `codex --quiet < tmpfile`. This flag was removed in the latest codex CLI update, causing all codex invocations to fail silently. The phases appeared to run but codex produced no output, resulting in false "no findings" verdicts from codex. Diagnosed by running `codex --help`, identified the new `exec` subcommand.

---

## Implications for Research

1. **AI oversight tooling requires maintenance as a first-class concern.** A governance framework that depends on external tools is subject to the same maintenance burden as any software that has dependencies. The research literature on AI oversight rarely discusses the operational maintenance of oversight tooling itself.

2. **Validation pipeline health is itself a measurable governance metric.** Tracking the rate of "tool invocation failed" results over time would give an early signal of tooling drift before it causes a silent gap. This is analogous to monitoring test flakiness as a proxy for test suite health.

3. **The "always diagnose" norm as a governance primitive.** The behavioral norm that tool failures must be diagnosed rather than accepted is simple to state but requires explicit codification to be reliable. Without it, the natural tendency toward progress (keep moving, treat infrastructure noise as noise) overrides the diagnostic behavior.

---

## Related findings

- `cross-vendor-review-finds-real-bugs.md` — tooling reliability is a prerequisite for the findings in that document
- `unenforceable-rules-need-verification-mechanisms.md` — the "always diagnose" rule is itself an example of a governance rule requiring an enforcement mechanism
