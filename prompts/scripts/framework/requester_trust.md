# Prompt Artifact — requester_trust.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/requester_trust.py` |
| **Description** | #2202 CODEOWNERS parsers strip inline comments; stale #1426 bypass text rewritten |
| **Date** | 2026-11-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

Coder brief for issue #2202 (condensed; orchestrator-authored, single dispatch):

```
Part 1 — CODEOWNERS inline comments (GitHub treats `#` as the start of a
comment anywhere on a line). Four parsers skip only lines that START with `#`,
so `/docs/ @alice # docs team` yields owners alice, #, docs, team. The
designated-human set for the require-overseer-approval merge gate is built
from one of them. Fix each to truncate the line at the first `#` BEFORE
stripping/tokenising (then skip if empty):
  1. scripts/framework/requester_trust.py codeowners_humans() (shared parser;
     docstring: inline comments stripped (#2202); `\#` escapes not supported —
     treated as comment start, the fail-safe direction: can only drop owners).
  2. scripts/automation/lib/merge_authority.py _codeowners_humans_from_text()
     — must stay byte-equivalent in behaviour to #1.
  3. scripts/automation/lib/codeowners.py (entries parser).
  4. scripts/oversight/codeowners.py (entries parser).
Minimal and identical across all four: line = line.split("#", 1)[0].strip().
Tests: inline-comment cases in tests/framework/test_requester_trust.py
(expect exactly {"alice","scottthurlow"}; `/only/a/path # @mallory` yields no
mallory); CO_CASES in tests/automation/test_route_pr.py (parity tests); one
case each for the two codeowners modules' existing test files.

Part 2 — Stale #1426 "above-ceiling bypass" text. #2174 retired it. Rewrite,
comments/docs/assertion messages only, so none describes #1426 as current:
.github/workflows/require-overseer-approval.yml header; .github/workflows/
require-tier-ceiling.yml lines 16-21; tests/framework/test_require_tier_ceiling.py
section comment; tests/framework/test_overseer_verdict_artifact.py ~287
assertion message (logic unchanged); docs/MACHINE-ACCOUNTS-SETUP.md ~174 and
its "What enforces what" table. Authoritative current rule: the module
docstring of scripts/framework/require_overseer_approval.py.

Do NOT edit .claude/agents/* (orchestrator authors those directly — two
sentences in overseer.md that cited the #1426 bypass), do not stash/checkout/
reset, do not commit, do not file issues or change labels.
```

## Constraints Specified

- Python 3.10+, stdlib only; no behaviour change beyond comment truncation.
- Security: the parser change may only shrink the trusted-human set, never grow it.
- Must NOT: implement `\#` escape handling; change YAML keys/steps; edit agent definitions.

## Refinement History

v1: accepted; orchestrator re-wrapped one overlong comment line in
require-overseer-approval.yml.
v2 (gate fix, second coder dispatch): the whole-file gates were red on two
legacy test files the v1 cases were appended to (tests/automation/test_phase_b.py,
tests/oversight/test_codeowners.py: pre-existing flake8/black/isort, a
detect-secrets false positive, a transitive mypy error). Brief: revert both to
origin/main; re-home the two inline-comment cases as test_t_co_3_* in
tests/automation/test_route_pr.py; narrow `_SPEC`/`_SPEC.loader` with an assert
in tests/framework/test_require_tier_ceiling.py (pre-existing mypy errors). The
coder also ran black on that file (pre-existing format drift) so lint_check
passes. All 13 gates green after v2.
v3 (code-review round 1 suggestions, third coder dispatch): (1) a fifth
CODEOWNERS parser on the /approve|/decline authorisation path,
.github/workflows/label-swap.yml's awk `NF && !/^#/`, had the same defect
(`/x @alice # @mallory` authorised mallory; verified against the old program).
Brief: strip from the first '#' before the field loop (`{ sub(/#.*/, "") } NF`),
with a new test (tests/framework/test_label_swap_codeowners_parse.py) that
extracts and runs the real awk program. (2) v1's "re-wrap" of the
require-overseer-approval.yml header had in fact merged two lines into a
~115-column line; re-wrapped properly. (3) codeowners_humans docstring: the
"byte-identical" provenance note reworded as historical.

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
3. Compare key logic paths against `scripts/framework/requester_trust.py`
4. Note any drift in a new version artifact (`requester_trust.v1.md`)
