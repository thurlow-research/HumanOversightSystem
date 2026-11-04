# Finding: LLMs Belong Inside Deterministic Orchestration — Naming a Technique Is Not Applying It

**Role:** oversight-mechanism — the LLM supplies semantics and judgment; deterministic structure supplies control flow, coverage and conformance. An instruction that merely names the required behaviour is followed inconsistently.

**First observed:** cumulative in HOS (2026-08 onward); external corroboration added 2026-11-04 (Trong et al., 2026, below), at the human's request ("deterministic orchestration").

---

## The Finding

When an LLM is asked to *apply* a discipline (a testing technique, an output format, a governance rule) and the only guidance is the discipline's name or a prose instruction, its output tends to *look* compliant without *being* compliant. The reliable pattern is to orchestrate the LLM **inside deterministic structure**:

- deterministic components own navigation, ordering, combinatorics and coverage;
- schema and referential checks reject output that does not conform;
- the LLM is used for what it is good at, which is reading unstructured text and producing semantic content within those bounds.

## External evidence

**Trong, M. P., Son, N. T., Hai, L. N., Giang, V. T., Viet, B. H., & Tung, D. T. (2026). A Business Process-Centric Approach for LLM-Driven Functional Test Generation. *IEEE Access*, 14, 44120–44146. https://doi.org/10.1109/ACCESS.2026.3671629** (CC BY 4.0; code: github.com/Trongmp04/IntelliTest-Test-casegeneration-part, zenodo.org/records/18642171.) Zotero key `I2GKH6KF`.

- **"Hybrid" is defined as orchestration:** "the engineered orchestration of probabilistic components (LLMs for semantic comprehension) with deterministic components (graph theory for navigation and combinatorial algorithms for data optimization)". The paper calls the shift one "from 'stochastic inference' to 'engineered validation'."
- **The probabilistic versus deterministic conflict:** LLMs "are inherently probabilistic engines designed for plausibility, whereas functional testing … demands deterministic adherence to strict logic", producing suites that "'look correct' linguistically but fail mathematically, such as missing off-by-one boundary cases" (§II).
- **Naming a technique underperforms explicit procedure:** the baselines "often provide high-level instructions or simply mention the name of a testing technique, letting the model decide how to apply it autonomously". The hybrid "uses explicit rules and step-by-step guides … [and] Cartesian products and pairwise algorithms" (§V.A).
- **Deterministic integrity checks prevent hallucination:** for every step, the current and next screens must belong to the extracted screen set ("preventing model hallucinations", §III.A). A directed screen graph drives navigation.
- **Results:** average boundary value coverage above 88%, state transition coverage above 95%, semantic quality above 92%, at $1.41–$1.82 per regression suite.
- **Context bleed:** an "excessively long context history … can be counterproductive", leading to "redundant steps, irrelevant data, and significant hallucinations". The authors propose limiting context to the current process flow (§V.A). This corroborates `more-context-makes-llm-review-worse-not-better.md`.
- **Threats to validity (authors' own):** two web applications only; the authors wrote both the specifications and the human benchmarks used for grading; baselines were reimplemented from paper descriptions. Treat the numbers as case-study evidence, not benchmarks.

## HOS evidence (same pattern, governance domain)

- **Prose controls are followed about a third of the time.** The overseer's required escalation format appeared in 13 of 35 comments (37%) when only instructed (`research/sessions/2026-08-04-controls-that-never-fire.md`). Its remedy was "validate at the write path, not in the instructions". That is the governance analogue of the paper's referential-integrity checks.
- **Deterministic controls work; narrated ones do not** (AGENTS.md, "Use the Code, Don't Roll It Yourself": "every gate implemented as executing code has functioned; every gate specified only in prose has either never fired or fired inconsistently").
- **Live instance, 2026-11-04 (PR #2244):** an overseer verdict recommended approval in its body while appended text said it "recommends against merging". The human could not tell the verdict. The fix (#2245) is the paper's pattern: fixed templates (verdict first, escalation with options) plus a deterministic form check at the write path.
- **HOS's own architecture is this pattern.** `bin/hos-cron`, the selector, gates and validators are deterministic orchestration. The LLM agents do semantic work inside it.

## Implication for research

1. **"Deterministic orchestration" is a design principle, not a convenience.** Wherever conformance matters (coverage, format, governance), put the requirement in code that checks or generates it, and let the LLM fill content within it. Naming the requirement in a prompt is the weakest control.
2. **The failure is plausible-looking output, which is why it evades review.** Both domains show output that *reads* compliant: test suites missing boundaries, verdicts with contradictory text. Human reviewers working from the comment trail are exactly the audience that misses it, so the check has to be mechanical.
3. **Context should be scoped per unit of work.** This is independent corroboration of the HOS finding that more context makes LLM review worse, and relevant to Local Inference Lane design (#1455).

## What changed

- #2245 (v0.7.0): overseer Templates A/B plus a deterministic write-path format check, citing this finding.
- #2248 (v0.7.6): the `system-test` agent applies the paper's techniques (EP, BVA, pairwise, state transition, exception flows) as an explicit procedure, with a deterministic coverage report.

## Related findings

- `more-context-makes-llm-review-worse-not-better.md`: corroborated (context bleed)
- `unenforceable-rules-need-verification-mechanisms.md`: a rule without a checkable artifact is advisory
- `a-decision-records-intent-not-enforcement.md`: intent written down is not enforcement
- `gate-on-computed-signal-not-self-reported-verdict.md`: compute the verdict, do not trust the stated one
- `the-ratchet-counts-human-attention-as-free.md`: the human-load cost of controls that are not mechanised
