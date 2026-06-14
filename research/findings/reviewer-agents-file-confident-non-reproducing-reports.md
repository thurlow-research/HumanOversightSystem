# Finding: AI Reviewer Agents File Confident, Well-Evidenced Bug Reports That Do Not Reproduce

**Role:** oversight-mechanism — the reliability of the agents that *produce* oversight signals; a failure mode of AI review itself

**First observed:** 2026-06-13, session `2026-06-13-cps-pilot-triage-and-backlog.md`

---

## The Finding

In a single overnight triage pass, **three of four** framework field-reports filed by the consumer test agent (`[AI: cps-test]`, a Claude-based reviewer running the HOS pipeline against the CondoParkShare app) **did not reproduce against the shipped code.** The reports were not vague hunches — they were **confident, specific, and permalink-backed**, each describing a plausible design flaw that the actual code does not have.

| Report | Claim | Verdict on verification |
|---|---|---|
| #150 | `n1_detector` scores from raw ORM-call density, ignoring loop depth (1.00, 31 candidates, all `loop_depth: 0`) | **Non-reproducing.** The shipped detector only records candidates at `loop_depth ≥ 1` (byte-identical v0.1.0→v0.1.2), and scores the cited `parking/*.py` at **0.0 / candidate_count 0**. The reported `loop_depth: 0` findings are *structurally impossible* from the code. |
| #149 | `run_validators.sh` collapses to "1 file(s)" and fail-closes to CRITICAL above ~11 files | **Non-reproducing as described.** Correct on normal multi-arg calls (2/11/40/116 → LOW/LOW/MEDIUM/MEDIUM). The collapse only occurs when the *caller* passes every path as one whitespace-joined argument — a caller-side footgun, not a runner bug. |
| #155 | `n1_detector` + `complexity` flag healthy code high | **Partly debunked** (n1 half = #150), partly unverifiable (complexity needed an absent dependency). |
| #157 | No gate catches a deletion that orphans imports and breaks the suite on collection | **Reproduced — a genuine gap.** Built the gate. |

The reports' surface markers of credibility — exact file:line citations, GitHub permalinks, real ORM call sites, a confident severity — were **present in the false reports as much as in the true one.**

## Why This Matters

This is the **inverse and complement** of `cross-vendor-review-finds-real-bugs.md`. That finding establishes that independent AI review produces *real* signal. This one establishes that the same class of agent also produces **confident, well-evidenced false signal** — the *reviewer-hallucination* failure mode, occurring on the **reporting** side (distinct from the **builder**-side escape documented in the Step-10 operator-shadowing case). Both must be true at once for an honest account of AI oversight: reviewers find real bugs *and* fabricate plausible ones, and the two are not obviously separable at the point of reading the report.

The load-bearing consequence: **confidence and evidence are not reliability signals.** A permalink-backed, specifically-cited bug report from an AI reviewer has a non-trivial probability of being wrong in a way that *reads as authoritative*. Therefore an oversight pipeline cannot act on a reviewer's report at face value — there must be a **reproduction gate between "report" and "fix."** In this session the just-shipped "verify before you fix" discipline (`docs/HANDLING-FINDINGS.md`) caught **two would-be erroneous code edits** (#149, #150) within the same session it was written — the discipline is not theoretical.

## Evidence

- #150 reproduction: `python3 n1_detector.py parking/*.py` → `score 0.0, candidate_count 0`; `git diff v0.1.0 HEAD -- n1_detector.py` empty (loop-guard present since v0.1.0). Posted in full on issue #150.
- #149 reproduction: file-count sweep 2/11/40/116 all correct under bash word-splitting; "1 file(s)" only when the path list is passed as a single joined argument. Defensive re-split shipped (`fix/149-...`), #149 closed.
- #157 reproduction: `pytest --collect-only` on an orphaned import → collection error (exit 2); gate built (PR #164).

## Implications for Research

1. **A reproduction gate is mandatory for autonomous fixing.** If reviewers emit false reports at a meaningful base rate, a fixer that acts on reports without independent reproduction will *degrade* the codebase (it edits correct code to satisfy phantom findings). The verify-reproduction-before-fix step is not an optimization — it is what keeps an autonomous loop from being net-negative.
2. **Surface plausibility ≠ ground truth — a measurement caution.** Citation specificity and permalinks are *style*, not *correctness*. Any quantitative study of AI-review precision must score against reproduction, never against the report's self-presented confidence.
3. **The false-report rate is measurable and apparently high** (here 3/4; small n, but the effect is large and the reports were detailed, not sloppy). This rate is itself a research metric — distinct from the per-finding false-positive rate of a *correctly-running* validator.
4. **Connection to determination honesty.** A reviewer's "this is a bug" is a *determination*; like the human-approval determination, it is only trustworthy if independently verifiable, not if merely asserted. The reproduction gate is the determination-check for machine-authored findings.

## Related findings

- `cross-vendor-review-finds-real-bugs.md` — the complement: AI review produces real signal. This finding is its necessary counterweight.
- `actor-identity-vs-determination-honesty.md` — the same "an asserted determination must be independently verifiable" principle, applied to the human gate.
- `the-distrust-check-exempted-its-most-important-target.md` and the Step-10 operator-shadowing escape — builder-side failure modes; this is the reporting-side analog.
