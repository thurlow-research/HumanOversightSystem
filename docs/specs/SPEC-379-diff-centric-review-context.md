# SPEC-379 — Diff-Centric Review Context

**Issue:** #379
**Status:** Draft — for architect review
**Research basis:** Kumar 2026 (P7); Charoenwet et al. 2026 (SWE-PRBench); AgenticSCR diff-centric perception strategy
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

SWE-PRBench (Charoenwet et al. 2026) found that single models detect only 15–31% of
human-flagged issues in a code review task. Critically, providing the model with *more*
context made detection *worse*, not better. AgenticSCR adopted a diff-centric perception
strategy in direct response to this finding: anchor the reviewer on the diff, not the
repository.

The HOS pipeline currently passes context to reviewer agents and to the cross-vendor scripts
(`run_second_review.sh`, `run_panel.sh`) without an explicit ceiling or a diff-first
discipline. Reviewers may request full repository context — which the evidence shows
degrades their performance. There is no enforcement mechanism and no advisory signal
when oversized context is provided.

This spec introduces three complementary controls:
1. An explicit diff-centric instruction in every reviewer CORE prompt.
2. A `--diff-only` flag (default on) in `run_second_review.sh` and `run_panel.sh`.
3. An advisory log entry when full-file context is provided to a reviewer.

---

## 2. Scope

**In scope:**
- Additions to the CORE section of all eight reviewer agent files:
  `code-reviewer.md`, `security-reviewer.md`, `privacy-reviewer.md`,
  `reliability-reviewer.md`, `ops-reviewer.md`, `ui-reviewer.md`,
  `a11y-reviewer.md`, `infra-reviewer.md`.
- `--diff-only` flag in `run_second_review.sh` (default: on).
- `--diff-only` flag in `run_panel.sh` (default: on).
- Advisory log entry (not blocking) when a reviewer requests or receives full-file context.

**Out of scope:**
- Validator scripts (`run_validators.sh` and its child scripts). Validators operate on
  file lists and static analysis targets — not reviewer prompts. Their input is unchanged.
- The `spec-red-team` agent. Adversarial spec review intentionally operates with broader
  context to find specification gaps; the diff-centric constraint does not apply there.
- The `risk-assessor` and `prompt-fidelity` agents. They consume code artifacts as part of
  scoring, not as reviewers.
- Any change to what information is passed to the `oversight-evaluator` or
  `oversight-orchestrator`.
- Changes to how internal reviewer findings are stored or forwarded between steps.

---

## 3. Requirements

### R1 — Reviewer CORE prompt: diff-centric instruction

All eight reviewer agent files listed in §2 must include the following instruction block
in their CORE section, under their "Inputs" or equivalent preamble heading:

> **Diff-centric review (Kumar 2026 / Charoenwet et al. 2026 — SWE-PRBench):**
> Review the diff provided. The diff is the primary input. Do not request full repository
> context or ask for all files. If a specific definition, type, or symbol is needed to
> evaluate a changed line, name it explicitly so the caller can retrieve only that
> artifact — do not ask for the whole file or the whole repository. Providing more context
> than the diff has been shown empirically to reduce, not improve, issue-detection rates.

This is a prompt-layer constraint. It is additive to the existing CORE sections and does
not replace any existing instruction.

### R2 — `run_second_review.sh`: `--diff-only` flag, default on

`run_second_review.sh` must accept a `--diff-only` flag. The default behavior (when the
flag is not explicitly set to off) is `--diff-only` on.

When `--diff-only` is on:
- The script passes only the PR diff to the agy and codex invocations, not the full file
  tree or any unrequested full-file content.
- If a reviewer (agy or codex) returns a response that contains a request for full-file
  context (detected by the presence of language such as "show me the full file",
  "provide the entire", "give me all files", or similar patterns — see R4), the script
  logs an advisory finding and does not fulfill the full-context request in the same run.

When `--diff-only` is explicitly off (`--diff-only=off` or `--no-diff-only`):
- The script behaves as it does today (no restriction on context passed).
- The script logs a startup warning: `[WARN] --diff-only is off: full-file context
  is enabled. Evidence suggests this may reduce reviewer detection rates (Kumar 2026).`

### R3 — `run_panel.sh`: `--diff-only` flag, default on

`run_panel.sh` must accept a `--diff-only` flag with the same default-on behavior as R2.

When `--diff-only` is on:
- Cross-vendor reviewers (agy, codex) receive only the diff, not the full file tree.
- Full-file context requests from reviewers are handled per R4.

When `--diff-only` is explicitly off:
- The script logs the same startup warning as R2.

### R4 — Advisory log when full-context is requested

When `--diff-only` is on and a reviewer response contains a request for full-file or
full-repository context, the script must:
- Log an advisory entry to the second-review or panel output file (`.claudetmp/second-review/`
  or `.claudetmp/panel/` as appropriate) with severity ADVISORY (not blocking):
  ```
  [ADVISORY] Reviewer requested full-file context while --diff-only is on.
  Reviewer: <vendor>
  Request pattern: <matched text excerpt>
  Action: Full-context request not fulfilled. If a specific artifact is needed,
  re-invoke with the named file passed as targeted context.
  ```
- Not block the pipeline. The advisory is informational; it surfaces context-bloat
  as a signal for future review-quality analysis, not a gate.
- Include the advisory count in the oversight-evaluator's input so Phase 2 quality
  review can consider it.

---

## 4. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-379-1 | All eight reviewer CORE sections contain the diff-centric instruction block verbatim (R1). |
| AC-379-2 | `run_second_review.sh --help` (or usage output) documents `--diff-only` and its default. |
| AC-379-3 | `run_second_review.sh` with default flags does not pass full-file content to agy or codex. |
| AC-379-4 | `run_panel.sh --help` (or usage output) documents `--diff-only` and its default. |
| AC-379-5 | `run_panel.sh` with default flags does not pass full-file content to cross-vendor reviewers. |
| AC-379-6 | Passing `--diff-only=off` to either script causes a startup warning to be printed to stderr. |
| AC-379-7 | When a reviewer requests full-file context and `--diff-only` is on, an ADVISORY entry appears in the output directory for that run. |
| AC-379-8 | The ADVISORY entry does not cause either script to exit non-zero or block the pipeline. |
| AC-379-9 | `bash -n run_second_review.sh` and `bash -n run_panel.sh` pass after the flag additions. |
| AC-379-10 | `spec-red-team.md` does not receive the diff-centric instruction block (non-requirement boundary preserved). |

---

## 5. Non-Requirements

- **Does not apply to `spec-red-team`.** Adversarial spec review deliberately operates
  with broader context to surface specification gaps. The diff-centric constraint is
  a reviewer-performance optimization and is inappropriate for an adversarial agent whose
  value comes from considering the system as a whole.
- **Does not change validator input.** `run_validators.sh` and all child validator scripts
  receive file lists for static analysis. That input is unaffected by this spec.
- **Does not change what the risk-assessor or prompt-fidelity agents receive.** Those
  agents score code as part of risk assessment, not review. The diff-centric constraint
  is scoped to the reviewer role.
- **Does not impose a hard token/line limit.** The constraint is behavioral (diff as
  primary input; explicit naming of needed artifacts) not a mechanical truncation. Token
  or line limits are an implementation concern for the architect.
- **Does not change the sign-off register format or fields.** Reviewer sign-off entries
  are unchanged.
- **Does not change the independence requirement** in `run_second_review.sh`. The existing
  prohibition on passing internal reviewer findings to agy/codex is orthogonal and
  unchanged.

---

## 6. Open Question for Architect

**OQ-379-1 — Default-on vs. opt-in for `--diff-only`.**

This spec proposes `--diff-only` default on, based on the SWE-PRBench evidence that more
context reduces detection rates. The alternative is opt-in (default off), which makes
the behavior change explicit and avoids breaking existing invocations that may rely on
full-file context being passed.

Recommended position (pm-agent): **default on**. The evidence is the design rationale;
a default-off flag would make the evidence-based behavior the exception rather than the
norm, and most pipeline invocations do not explicitly control context today. Making the
safe default the out-of-box experience is consistent with the principle that HOS should
fail toward more oversight, not less.

Counter-consideration: operators who have tuned their workflows around full-file context
will be silently affected on upgrade. The startup warning (R2/R3) when opting out mitigates
this but does not eliminate it.

Architect should confirm: default on or default off? If default off, revise R2, R3, and
AC-379-3, AC-379-5 accordingly.

**OQ-379-2 — Full-context request detection pattern.**

R4 specifies advisory detection when a reviewer's response requests full-file context.
The detection is based on natural-language pattern matching (e.g. "show me the full file",
"provide the entire", "give me all files"). The complete pattern list is an implementation
detail.

Architect should confirm: is pattern-based detection sufficient for v1, or should this be
a structured signal emitted by the cross-vendor reviewer invocation rather than post-hoc
text matching on the response?

---

## 7. Cross-References

- Kumar 2026 (P7) — SLR finding on diff-centric review strategy
- Charoenwet et al. 2026 — SWE-PRBench: 15–31% detection rate; more context = worse detection
- AgenticSCR — diff-centric perception strategy adopted in response to the above findings
- SPEC-381 — Reviewer Framing Guard (companion prompt-layer constraint on reviewer inputs)
- `run_second_review.sh` — cross-vendor second review script (R2)
- `run_panel.sh` — cross-vendor panel script (R3)
- Reviewer CORE agent files: `code-reviewer.md`, `security-reviewer.md`, `privacy-reviewer.md`,
  `reliability-reviewer.md`, `ops-reviewer.md`, `ui-reviewer.md`, `a11y-reviewer.md`,
  `infra-reviewer.md`

---

*Spec authored by pm-agent. Change class: additive (fills a gap the research finding
implies was always a requirement — diff-centric review discipline was implied by the
quality obligations of the pipeline; this spec makes it explicit and enforceable).*
