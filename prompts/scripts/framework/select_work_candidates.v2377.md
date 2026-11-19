# Prompt Artifact — select_work_candidates.py (v2377)

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/select_work_candidates.py`, `tests/framework/test_select_work_candidates_native.py` (and/or a new `tests/framework/test_graphql_literals.py`), `tests/fixtures/**` (real-capture GraphQL responses) |
| **Description** | #2377: the closer GraphQL query `_CLOSER_QUERY` has 11 `{` and 10 `}`; GitHub rejects every call, so every closed-blocker lookup is UNKNOWN and the selector exits 3. Fix the brace and add tests that would have caught it. |
| **Date** | 2026-11-19 |
| **Model** | claude-opus-5-5 (orchestrating worker and `coder` subagent) |
| **Risk level** | MEDIUM (classifier tier floor for `.py`; protected surface: selector) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → `coder` subagent brief:

```
Implement GitHub issue #2377 in the HOS repo (cwd /home/scott/Code/HumanOversightSystem/Worker,
branch worker-2377-closer-query-brace-261119002001-106675, already checked out — do NOT switch
branches, stash, or checkout other refs).

## Problem
`_CLOSER_QUERY` in scripts/framework/select_work_candidates.py (~line 743) has 11 '{' and 10 '}'.
GitHub rejects every call ("Expected NAME, actual: (none)"), so _fetch_closer_node always returns
None → blocker_closure_satisfied returns _UNKNOWN → candidate FAILED → selector exit 3.

## Required
1. Add the missing closing brace so the query is a balanced, valid GraphQL document. Change no
   other selection semantics.
2. Tests that would have caught it (they must FAIL against the current query and PASS on the fix):
   a. A structural check of _CLOSER_QUERY: balanced {} [] () with nesting never going negative,
      AND a check that it parses as GraphQL. graphql-core is NOT installed in
      scripts/oversight/.venv; do not add a dependency. Write a small, self-contained validator
      in the test (tokenizer skipping string literals and '#' comments; balanced delimiters;
      every selection set non-empty; ends at depth 0 with nothing trailing). Keep it in the
      tests tree, not production code.
   b. Real-capture-shaped fixtures of a `ClosedEvent` GraphQL response for (i) a PR closer
      (closer.__typename == "PullRequest", merged true, mergeCommit oid, baseRefName,
      baseRepository.nameWithOwner) and (ii) a manual close with `closer: null`. Shape them
      exactly as GitHub returns for this query ({"data":{"repository":{"issue":{"timelineItems":
      {"nodes":[{...}]}}}}}). Feed them through the existing _run_graphql/_fetch_closer_node
      path (mock subprocess.run at the gh boundary, as existing tests in
      tests/framework/test_select_work_candidates_native.py do) and assert the verdict:
      PR-merge closer onto default branch → satisfied; closer null by a non-CODEOWNER bot →
      UNSATISFIED (blocker-closed-unverified), NOT unknown/FAILED. Reuse existing helpers/
      fixtures in that test file; read it first.
   c. Apply the same structural check (2a) to the other GraphQL literals under scripts/ and
      bootstrap/: `_REVIEW_THREADS_QUERY` in scripts/automation/lib/github.py, the mutation in
      scripts/automation/lib/merge_authority.py (~line 2305-2316), and the inline query in
      bootstrap/post_review_thread.sh (~line 155; extract the single-quoted literal from the
      file text in the test). If any are unbalanced, report it back — do not silently fix
      code outside this issue; tell me.
3. Report the brace-balance result for each literal in your final message (I put it in the PR).

## Constraints
- Python, black-formatted (line length per repo config), ruff/mypy clean.
- Tests must not touch the network or real gh.
- Commit with exactly this trailer block (one contiguous block, after a blank line):
    Prompt-Artifact: prompts/scripts/framework/select_work_candidates.v2377.md
    AI-Model: claude-opus-5-5
    AI-Risk: MEDIUM
    Supervised-by: ScottThurlow
  Commit message subject: "fix(#2377): balance _CLOSER_QUERY braces; GraphQL literal + real-capture tests".
  Do NOT put a closing keyword (closes/fixes/resolves #N) in the commit message.
- Run tests with single commands redirecting to a file, e.g.
    scripts/oversight/.venv/bin/python -m pytest tests/framework/test_select_work_candidates_native.py -q > .claudetmp/t2377.log 2>&1
  then Read the log. No && chaining.
- Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final message.
```

## Iteration 2 (code-review SHOULD_FIX)

- (a) test_graphql_literals.py: write the invisible U+FEFF in the tokenizer whitespace set as the escape \ufeff.
- (b) Add a guard test scanning scripts/, bootstrap/ and bin/ for graphql call sites (api graphql or "graphql" argv) and asserting the file set equals the four files covered by _literals().
- (c) TestRealCaptureVerdicts verdict tests now assert the sent query= argv element equals "query=" + _CLOSER_QUERY and that the query passes validate_graphql.
