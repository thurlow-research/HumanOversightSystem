# Finding: Jidoka Applied to AI Pipeline Re-runs — Automate Until a Defect Requires Human Judgment

**First observed:** 2026-06-13, discussion of prompt-fidelity re-entry path and Make-style dependency tracking  
**Theoretical basis:** Lean Manufacturing — Jidoka (Toyota Production System, Ohno 1988); see README.md Theoretical Basis

---

## The Finding

The HOS pipeline currently runs each step once. If an input to an earlier step changes after it ran — a prompt artifact is added, a design pack is updated, a spec is amended — the earlier step's output is stale but nothing detects or corrects this. The pipeline proceeds on outdated analysis.

The Make build system solves an analogous problem in software compilation: if a source file changes, recompile only the affected targets, not everything. The dependency graph is explicit; Make checks timestamps and re-runs only what is stale.

The same principle applies to the HOS pipeline. Each step has known inputs. If those inputs change after the step ran, the step should re-run.

---

## The Jidoka Layer

Make is purely reactive — it rebuilds until the build succeeds. Applied to HOS, pure reactivity would mean automatically re-running any step whose inputs changed, including expensive LLM steps, potentially indefinitely.

Jidoka adds the stopping condition: **automate until a defect requires human judgment, then stop the line and signal.**

The combined principle:

> **Re-run automatically when inputs change. Stop and signal the human when the re-run produces a new finding that requires human decision.**

"Requires human decision" is already well-defined in HOS:
- A NEW HIGH/CRITICAL finding that wasn't in the previous run
- A tier increase (risk went up)
- A structural change flag (new behavior, new user decision, new scope)
- A CRITICAL authorization gate

Everything else — a re-run that produces the same result, a lower-tier finding, a tier decrease — continues automatically. The human is only involved when the machine detects something it cannot resolve.

---

## The Dependency Graph

```
prompt artifact      → risk-assessor (prompt-fidelity subagent)
design pack update   → technical-design, ui-reviewer, a11y-reviewer
telemetry spec update → ops-reviewer
spec update          → spec-red-team (on affected sections)
code fix             → the reviewer that found the original issue
validator input      → run_validators.sh (all validators)
dep-mapper configured → risk-assessor at HIGH+ (blast-radius analysis)
```

When any of these left-side artifacts change, the right-side steps should re-run.

---

## The Practical Trigger

The most common case: a human adds a prompt artifact after risk-assessor ran without one. Currently: risk-assessor logged `Status: NYI`, pipeline proceeded with a coverage gap. Under Make+Jidoka: risk-assessor re-runs automatically with the new artifact, prompt-fidelity runs for real this time. If the fidelity check finds nothing new → pipeline continues. If it finds a scope-creep addition that wasn't in the prompt → stop and signal.

---

## Key Difference from Compilation

In Make, re-running a step is deterministic and cheap (compilation is idempotent). In HOS, LLM steps are:
- **Non-deterministic:** a re-run may produce different output even with the same inputs
- **Expensive:** each re-run consumes token budget

This means pure automation of re-runs is more expensive than in Make, but the Jidoka principle still holds. The practical implementation may use tiered re-run cost:
- **Cheap/deterministic steps** (validators, gates): always re-run automatically
- **LLM reviewer steps** (risk-assessor, code-reviewer, etc.): re-run automatically, but log the re-run and its delta from the previous run for human review
- **Project-start steps** (ux-designer, ops-designer, architect): don't auto-re-run; these are expensive and their outputs are foundational — require explicit human trigger

---

## The Three-State Audit Taxonomy

This finding motivates a complete audit event taxonomy for steps that don't produce APPROVED entries:

| Event | Meaning | Who generates it |
|---|---|---|
| `gate-suspended` | Human decided not to run this (brownfield, acknowledged gap) | Human via gate-suspension.md |
| `gate-na` | Orchestrator determined not applicable for this diff | post-change-sweep |
| `validator-failure` | Tried to run, failed after retries | run_validators.sh / run_with_retry.sh |
| `gate-rerun` | Step re-run because inputs changed | pipeline re-run mechanism |

Currently the audit log only records `validator-failure`. The other three states are invisible. A complete audit trail requires all four.

---

## Implications for Research

1. **Make-style dependency tracking is applicable to AI governance pipelines.** The abstraction transfers: steps have inputs, inputs have change timestamps, stale steps should re-run. The non-determinism of LLM steps is a cost factor, not a disqualifier.

2. **Jidoka as a stopping condition for automation.** The question "when should a human be involved?" has a precise answer in Jidoka terms: when the machine detects a defect it cannot resolve autonomously. This is more precise than "always review HIGH+ findings" — it focuses human attention on *new* findings that emerged from changed inputs, not on findings that were already known and accepted.

3. **The prompt artifact gap is an instance of a general input-staleness problem.** Any step that ran without a complete set of inputs will produce incomplete analysis. The fix is not "run the step again manually" — it is "detect that inputs changed and re-run automatically." This applies to prompt artifacts, design pack updates, spec changes, and any other pipeline input.

4. **Automation with Jidoka creates a higher-trust pipeline than full automation.** Full automation (re-run everything, always continue) removes human oversight. Full manual control (human decides every re-run) is too slow. The Jidoka middle path — automate until a defect, then stop — gives the pipeline higher throughput while preserving meaningful human gates.

---

## Related findings

- `stamp-based-ci-enforcement.md` — the stamp/timestamp mechanism is a primitive form of staleness detection; this finding generalizes it to the full pipeline
- `unenforceable-rules-need-verification-mechanisms.md` — the re-run mechanism is the enforcement mechanism for "steps must have complete inputs"
- `brownfield-governance-adoption.md` — gate suspension is the human-authorized override for the Jidoka stop condition
