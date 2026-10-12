# Prompt Artifact — validation_logic.py (#2062)

| Field | Value |
|---|---|
| **Generated files** | `scripts/oversight/validation_logic.py`, `scripts/oversight/second_review_logic.py`, `scripts/run_second_review.sh` (comment only), `tests/oversight/test_validation_logic_extraction_2062.py`, `tests/oversight/test_second_review_extraction_2062.py` |
| **Description** | #2062: reviewer-JSON extraction fails closed (duplicate keys, fence-first masking, nested review objects) |
| **Date** | 2026-10-12 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` agent (task text, abridged):

```
Implement GitHub issue #2062. The approved technical design is
docs/v0.7.0/TECHNICAL-DESIGN-2062-extract-json-fail-closed.md — read it in full,
including section 10 "Architect review" whose conditions C1-C5 are binding (C6 is
the worker's job). Implement exactly what it specifies: the changes to
scripts/oversight/validation_logic.py and scripts/oversight/second_review_logic.py,
the comment-only edit to scripts/run_second_review.sh, and the two new test files
with every listed test case (including the four the architect added).
compute_verdict must not change. If the design is ambiguous, pick the fail-closed
reading and note it in the report.

C3: replay the 255 retained outputs in .claudetmp/second-review/ and
.claudetmp/framework/ with the old and new extractor; report files scanned, count
previously approve -> now non-approve, and the reason for each flip. If flips
exceed 5% of previously-approved files or any flip is unexplained, STOP.
```

## Constraints Specified

- Python 3 stdlib only; `compute_verdict`, `validate_*.sh` and `agent_invoke_cli.py` unchanged.
- Fail-closed direction: review-shaped text the extractor cannot read blocks (one synthetic `verdict: error` block per text); reviewer text never copied into the diagnostic (CWE-117).
- No branch, PR, issue or label actions by the coder; no edits to `.claude/agents/**`.

## Refinement History

v1: implementation per the design and architect conditions C1-C5, plus a C3 corpus replay.

v2 (review round 2): `_aggregate_full` in second_review_logic.py now routes `RecursionError` from `loads_strict` to the same error branch as `DuplicateKeyError`, so a deeply nested `verdict: approve` body can no longer fall into the prose classifier. The other two `loads_strict` call sites (envelope unwrap, salvage) skip the candidate but are covered by `review_text_unreadable`; regression tests added to test_second_review_extraction_2062.py. Round-2 prompt: "Route RecursionError to the same error branch as DuplicateKeyError; restore the num_turns sanitizer assertion; record the test edit and deviations in this artifact."

## Disclosed Deviations and Test Edits

- tests/oversight/test_vendor_prompt_consumption_guard.py::test_forged_fence_in_num_turns_cannot_mint_a_verdict was edited. The forged-num_turns case previously expected approve (exit 0) with only the genuine review; the forged nested `verdict` is review-shaped unreadable text outside the genuine review, so the extractor now fails closed: expectation changed approve -> error (exit 1, `verdict: error`). The CWE-74 assertion that the advisory block's `num_turns` is sanitized to None is retained (the advisory is still emitted on the error path).
- Same-length masking: the unreadable-text detector masks spans with same-length replacements so offsets stay stable. This differs from a literal removal reading of the design and is a disclosed deviation.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings:
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

1. Open a fresh Claude Code session
2. Paste the prompt above together with the technical design
3. Compare key logic paths against `scripts/oversight/validation_logic.py`
