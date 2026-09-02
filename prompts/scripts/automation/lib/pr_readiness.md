# Prompt Artifact — pr_readiness.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/pr_readiness.py` |
| **Description** | REQ-W-01 must fail when self-heal leaves generated artifacts uncommitted |
| **Date** | 2026-09-02 |
| **Model** | claude-sonnet-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
On PR #1500 (fix(#1414): self-heal SCRIPTS-INDEX.md/CODEOWNERS drift before it
halts the worker), the overseer bot posted a review finding and the human
commented "Worker - please address feedback".

Overseer finding: `run_tests_inner_loop.sh` now runs `regen_all.sh` self-heal
in place immediately before pytest, in the same working tree that
`test_scripts_index.py`/`test_codeowners_current.py` check moments later.
Both tests read the on-disk file directly, so once self-heal has rewritten
the working copy, those tests compare the fix against itself and always pass
— regardless of whether the file that will actually be committed/merged was
stale. `pr_readiness.py::_check_inner_loop_tests` (REQ-W-01, the worker's own
pre-PR gate) only inspects the script's exit code, never stdout, so a PR
could ship with genuinely stale CODEOWNERS while REQ-W-01 still reports pass.

Three options were suggested: (a) make self-heal mode exit non-zero when
CHANGED>0, (b) run the freshness tests against `git show HEAD:<path>` instead
of the post-self-heal working tree, or (c) don't wire self-heal into the same
script the exit-code-only readiness gate depends on.

Implement the fix that closes this gap for the pr_readiness.py/REQ-W-01
integration path specifically (the overseer called that out as the one the
worker's own gate actually consumes), without changing regen_all.sh's
self-heal-exits-0 contract or the pytest freshness tests' general behavior
(both are still useful/correct for normal iterative development). Add tests.
```

## Constraints Specified

- Do not change `regen_all.sh`'s self-heal mode to exit non-zero — that would
  reintroduce the "adding a script halts the worker" failure #1414/#1413
  addressed self-heal for.
- Do not weaken or rewrite `test_scripts_index.py`/`test_codeowners_current.py`
  — they are correct for the ordinary local-dev self-heal-then-commit flow.
- Fix must live at the `pr_readiness.py` REQ-W-01 integration point the
  overseer specifically identified as the worker's own pre-PR gate.
- Must not require network access or `gh` calls (self-heal/readiness checks
  run offline against the local working tree only).

## Refinement History

<!-- If you iterated across multiple turns to get the right output, document the key changes:

v1: [initial prompt — what was wrong or missing]
v2: [what you changed and why]
vFinal: [what made it work]

Delete this section if first attempt worked.
-->

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/automation/lib/pr_readiness.py`
4. Note any drift in a new version artifact (`pr_readiness.v1.md`)
