# Prompt Artifact — changeset.sh

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/lib/changeset.sh` |
| **Description** | Fail closed on option-shaped git-sourced changeset names; NUL-delimited diff parsing (#2097; bandit -- landed separately via #1605) |
| **Date** | 2026-10-14 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (risk-assessor raised from MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Round 1 (worker -> coder), core text:

Implement GitHub issue #2097. When a gate is run with a git-sourced selector
(--diff, --step, --staged), scripts/oversight/lib/changeset.sh resolves
candidates from `git diff --name-only` in _hcs_resolve_via_diff -> _hcs_apply_rex.
That path only checks [[ -e "$c" ]], so a committed top-level file named e.g.
`--output=x.py` lands in HOS_CHANGESET_FILES. security_scan.sh then runs
`bandit -f json -lll "${FILES[@]}"` with no `--`, so --output=/dev/null yields
a false GATE PASS.

1. changeset.sh: in _hcs_apply_rex (shared by explicit/diff/step/staged), before
   the existence filter, fail closed if ANY candidate begins with '-':
   _hcs_fatal "$label" 3 "<message naming the path>"; return 1. Keep the library
   contract: no exit, bash 3.2 compatible, guarded array expansions.
2. security_scan.sh: insert `--` before "${FILES[@]}" in the bandit invocation.
3. Regression tests (pytest, tmp_path, no temp leaks): committed --output=x.py /
   --baseline=x.py under --diff HEAD~1 must not print GATE PASS and must exit 3;
   same for --staged; explicit-argv '-x' still exits 2; nested sub/-x.py is not
   rejected; security_scan passes `--` before the file list.

Round 2 (worker -> coder, after code-review SHOULD_FIX 1-3):

1. Switch both `git diff --name-only` calls in _hcs_resolve_via_diff to `-z` and
   read NUL-delimited output (bash 3.2: `while IFS= read -r -d '' x`), so
   core.quotepath quoting ("-\303\251.py") can no longer hide a leading '-'
   or drop a non-ASCII/tab-named file as undecidable (silently unscanned).
   Add tests: dash+non-ASCII name refused; plain non-ASCII name resolved and
   forwarded (not NOT CHECKED).
2. Add a --step regression test (or drop the --step claim).
3. Replace the static `--` test with a behavioural one: a stub bandit that
   records its argv, asserting `--` precedes the file list.
4. Amend trailers: Prompt-Artifact: prompts/scripts/oversight/lib/changeset.md,
   AI-Risk: HIGH.
```

## Constraints Specified

- Runtime: bash 3.2 compatible; sourced library (no `exit`, no `set -e`, guarded array expansions).
- Security: fail closed (exit 3) on any option-shaped git-sourced name; never forward it to a tool.
- Must NOT: change explicit-argv behaviour (still exit 2); touch pip-audit invocation; leak temp files.

## Refinement History

<!-- If you iterated across multiple turns to get the right output, document the key changes:

v1: [initial prompt — what was wrong or missing]
v2: [what you changed and why]
vFinal: [what made it work]

Delete this section if first attempt worked.
-->

Re-adoption (2026-11-04, worker -> coder): after merging origin/main, #1605
had already added `--` before bandit's file list (SEC-M2), so the branch's
security_scan.sh hunk and its static `--` test were dropped in favour of
main's. #1605's TC-S16 pinned the pre-#2097 behaviour (git-sourced
`--baseline=x.py` forwarded after `--`, exit 0); the coder was asked to
update it in place to pin the refusal: exit 3, the SB-9 bandit stub never
invoked, "begins with '-'" on stderr, no OK/GATE PASS. This closes
TD-1605 residual R-6.

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
2. Supply the prompt above as the task
3. Compare key logic paths against `scripts/oversight/lib/changeset.sh`
4. Note any drift in a new version artifact (`changeset.v1.md`)
