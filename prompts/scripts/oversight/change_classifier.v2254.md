# Prompt Artifact — change_classifier.py (#2254)

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/change_classifier.py` (+ `tests/oversight/test_change_classifier.py`) |
| **Description** | #2254: `new-user-flow-or-route` signature no longer matches the prose plural `path(s)` / `url(s)` / `Route(s)` |
| **Date** | 2026-11-06 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | MEDIUM (coder self-declared LOW; `change_classifier --tier-floor` → MEDIUM, application-code file; module feeds Condition-10 gating) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Prompt from the worker to the `coder` subagent. It is verbatim except that the boilerplate (branch name, no-git-write rules, self-flag request) is summarized:

```
Problem: scripts/oversight/change_classifier.py:107-111, the `new-user-flow-or-route` entry in
ADDED_LINE_SIGNATURES, has alternatives `\bpath\(`, `\burl\(` and `\bRoute\(`. They also match
English prose plurals like `path(s)`, `url(s)`, `Route(s)`. Real false positive: a test line in
tests/oversight/test_gate_arg_grammar.py:
    assert "changeset = 1 file(s) from 1 explicit path(s)" in res.stdout
raises a Condition-10 signal and forces a false human gate (same class as #2201 / #2031).

Required change (conservative; do not narrow real detection):
1. Exclude ONLY the prose-plural form for `path(`, `re_path(` (harmless), `url(` and `Route(`,
   using a negative lookahead such as `\bpath\((?!s\))`. Do NOT require a string-literal first
   argument: `path(route_var, view)` must still match. Keep `<Route\b`, `@app.route`, the router
   alternatives and `createBrowserRouter` unchanged. Add a short comment in the style of the
   #2201/#2031 comments (#2254). No backtracking hazard (fixed-length lookahead).
2. Do NOT add any tests/ path exemption (out of scope, design decision).

Regression tests in tests/oversight/test_change_classifier.py:
- path(s)/url(s)/Route(s) in a Python test string (the exact #2230 assert line under
  tests/oversight/test_gate_arg_grammar.py) and in Markdown prose -> no route signal.
- Still structural in app/urls.py: path("new/", views.home), path(route, view),
  re_path(r"^x/$", v), url(r'^x/$', v), Route("/a", handler).
- Boundaries: path(sx, view) and path(s, view) still match; path(s). and path(s) and -> no signal.
```

## Constraints Specified

- Narrow only the `new-user-flow-or-route` signature, and only by the literal `(s)` form. Every other compiled rule stays byte-identical.
- No string-literal requirement on the first argument (that would miss `path(route_var, view)`).
- No `tests/` added-line exemption (the issue's proposed item 2): widening a Condition-10 exemption is a design decision, and the acceptance criteria are met without it.

## Refinement History

- v1: `(?!s\))` lookahead on `path(`, `re_path(`, `url(`, `Route(`; comment citing #2254; two parametrized tests (8 negatives, 7 positives). Replay: main's classifier raises `new-user-flow-or-route` on the #2230 branch diff (`tests/oversight/test_gate_arg_grammar.py`); the fixed classifier raises none.
- v2 (unit-test agent, tests only): hand mutation of the four lookaheads (drop; `(?!s)`; `(?!\))`) left 5 of 12 mutants alive, so three tests were added: `re_path(s)` prose, `sx`/`s`-argument calls for `re_path`/`url`/`Route`, and the unchanged alternatives (`@app.route`, `router.get(`, `@router.post`, `<Route `, `createBrowserRouter(`). All 12 mutants are now killed. Source unchanged.

Accepted residual: a real route call written literally as `path(s)` (single bare argument named `s`) is no longer flagged. Django's `path()` and `url()` take at least two arguments (route, view), so the excluded form cannot be a real route registration in those frameworks.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->
