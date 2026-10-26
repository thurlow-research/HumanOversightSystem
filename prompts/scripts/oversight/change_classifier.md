# Prompt Artifact — change_classifier.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/change_classifier.py` (+ `tests/oversight/test_change_classifier.py`) |
| **Description** | #2031: drop bare propagat stem from new-observability-instrumentation signature |
| **Date** | 2026-10-08 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM (coder self-declared LOW; raised by risk-assessor — composite 0.3028, module feeds Condition-10 gating) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Initial prompt from the worker to the `coder` subagent (verbatim except for the commit-message block):

```
Issue #2031 (bug fix, LOW/MEDIUM risk, scoped): in `scripts/oversight/change_classifier.py`,
ADDED_LINE_SIGNATURES entry "new-observability-instrumentation" (~line 117-121) contains the
bare alternative `propagat`, which matches English prose ("propagates", "propagation") in added
.md lines, e.g. "`main()` lets `_Interrupted` propagate." — producing a false structural signal
and a false Condition-10 ESCALATE.

Required change (minimal, do not widen scope):
1. Replace the bare `propagat` alternative with tokens specific to tracing-context propagation
   code, e.g. `\bpropagators?\b|\bpropagate\.(inject|extract)\b|TextMapPropagator|...`. Make sure
   "propagate", "propagates", "propagation", "propagated" in plain prose no longer match, while
   propagate.inject/extract, propagator objects and TraceContextTextMapPropagator() still match.
   Update the comment above the entry noting why (#2031, word-boundary lesson like #117/#1889).
2. Do NOT change prose-file (.md) scanning scope or other signals.
3. Add regression tests (prose negatives incl. the exact #1968 line; OTel propagation positives).
4. Run pytest on the test file; black/flake8 clean.
```

## Constraints Specified

- Narrow only the `new-observability-instrumentation` signature; every other compiled rule must stay
  byte-identical (verified mechanically by security-reviewer, origin/main vs HEAD).
- Do not change `.md` scanning scope (issue asked to *consider* it; deferred as a gate-scope design question).
- Real OpenTelemetry propagation code must still be detected, with tests.
- Lines ≤ 100 cols (flake8), black-clean; all gates clean in touched files.

## Refinement History

- v1 (704c6a17a): bare `propagat` → `\bpropagators?\b|propagate\.(inject|extract)\b|TextMapPropagator`.
- code-review r1 (ef3c09c7f): E501 re-splits (behavior-neutral); isolated positive tests; `os` import cleanup.
- security r1 (15b89ccd5): old stem incidentally caught non-OTel vendor imports (ddtrace, opencensus) —
  added an import-anchored `propagation` token so narrowing does not loosen the gate for them.
- worker tightening (933d30b8a): anchor that token to line start so mid-sentence prose does not match.
- code-review r3 (a5fa82e2f): require real import-statement syntax (`from … import`, `import …` with a
  `,`/`as`/end terminator) so hard-wrapped prose lines starting "from propagation …" do not match.
- unit-test (7358e2d57): manual mutation check (16 mutants) → added negatives/positives until 16/16 killed.

- v-next (2026-10-26): bounded the dotted-name quantifiers in both import-anchored `propagation`
  alternatives per human ruling 2026-10-15 (security finding CWE-1333: `[\w.]*` adjacent to
  `(?:\.\w+)*` backtracked quadratically, ~3.85s on a 40KB non-matching line). Bounds: `{0,200}`/`{1,200}`
  name runs, `{0,8}` tail segments of `{1,100}` chars. Regression test added (<0.5s on ~40KB).

Final alternatives replacing `propagat`:

```
\bpropagators?\b | propagate\.(inject|extract)\b
^\s*from\s+[\w.]{0,200}\bpropagation\b[\w.]{0,200}\s+import\b
^\s*(from\s+[\w.]{1,200}\s+)?import\s+\(?[\w.]{0,200}\bpropagation\b(?:\.\w{1,100}){0,8}\)?\s*(,|\s+as\b|$)
TextMapPropagator
```

Accepted residuals (security NIT): non-first names in multi-name vendor imports, multi-line
parenthesised imports, trailing `# comment` after a vendor import, `importlib.import_module(...)`.
OTel usage is still caught on its import line by the `opentelemetry` token. Prose "propagator" still
matches `\bpropagators?\b` (accepted as OTel-specific).

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
3. Compare key logic paths against `scripts/oversight/change_classifier.py`
4. Note any drift in a new version artifact (`change_classifier.v1.md`)
