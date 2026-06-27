# Finding: A gate must recompute its verdict from the findings, never trust the reviewer's self-reported verdict field

**Role:** oversight-mechanism — extends the "self-classification cannot gate" rule from the *actor* to the *reviewer's own summary verdict*

**First observed:** 2026-06-24, v0.4.2 pre-release validation pass (HOS#814)

---

## The finding

Two oversight scripts — `validate_docs.sh` and `validate_spec_compliance.sh` — gated their pass/fail on the reviewer's **self-reported `verdict` field** ("approve" / "request-changes") instead of on the **computed `blocking_count`** derived from the findings the reviewer itself listed. The consequence: a reviewer JSON that *enumerated blocking findings* but self-reported `"verdict": "approve"` exited 0. The gate's terminating signal and the gate's evidence pointed in opposite directions, and the gate believed the signal.

This is the same fail-open class as the self-reported risk tier (`self-classification-cannot-gate-the-human-boundary.md`), but one level up the stack: there the *actor* could not be trusted to classify its own change; here the *reviewer's summary verdict* cannot be trusted to summarize its own findings. The non-determinism of the LLM reviewer makes the summary verdict and the findings list independently generated — the model can list three blocking issues and still tag the whole thing "approve." The sibling script `validate_agents.sh` already did the right thing (gate on `blocking_count`); these two had drifted to the easier-to-read field. The inconsistency is itself the tell: when three sister gates compute the same verdict three different ways, at least one is wrong.

It was caught not by the inner loop that shipped it but by the **pre-release validation pass** (`run_framework_validation.sh`, the last-line gate), alongside two other fail-opens in the same run — a quote-context tracker that skipped real code after a quoted comment, and a migration scorer pinned to line 0. Three independent fail-opens, all surfaced at the release boundary, none by the reviewers that approved the code.

## Why it matters for scalable oversight

A gate's verdict is the one thing that must be *derived*, never *reported*. The whole value of producing a structured findings list is lost if the gate then ignores it and reads a summary field that a non-deterministic producer can set inconsistently with the list. The rule generalizes the re-derivation invariant (O7): **the loosening direction — "approve" / "no blocking findings" — must be recomputed by the gate from the raw findings, because the producer (actor *or* reviewer) cannot be trusted to assert the permissive verdict about its own output.** A reviewer may *raise* an alarm in its prose; it may not *clear* the gate by self-declaring "approve" when its own findings say otherwise.

Two corollaries:
1. **Compute, don't read.** When a structured reviewer emits both a findings list and a summary verdict, the gate consumes the *findings* and computes the verdict; the self-reported verdict is at most a cross-check (and a *disagreement* between the two is itself a finding worth surfacing, not silently resolving in the permissive direction).
2. **One verdict-computation, one site.** Three sister gates computing the verdict three ways is how the drifted one fails open undetected — the same single-invocation-site discipline that `tooling-drift-in-validation-pipelines.md` prescribes for external CLI calls applies to verdict derivation.

## The mechanism (the fix)

- `validate_docs.sh` and `validate_spec_compliance.sh` now gate on the computed `blocking_count`, matching `validate_agents.sh`; the reviewer's self-reported `verdict` is no longer the pass/fail signal.
- Shipped as one of three fail-open closures from the v0.4.2 pre-release validation pass — evidence that the last-line gate's characteristic catch is the *fail-open in the oversight machinery itself*.

## Provenance

Found 2026-06-24 by Opus during `run_framework_validation.sh` while validating v0.4.2; fixed in HOS#814 (PR #884) together with the `bash_check.sh` quote-context and `migration_scorer.py` line-0 fail-opens. Generalizes `self-classification-cannot-gate-the-human-boundary.md` and `the-distrust-check-exempted-its-most-important-target.md` (don't trust the producer's permissive self-report) to the reviewer-verdict layer; a fail-open instance per `tooling-drift-in-validation-pipelines.md` and the O4 family; caught by the last-line gate per `release-gate-catches-its-own-missing-oversight.md` (O8).
