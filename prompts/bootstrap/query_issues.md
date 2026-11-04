# Prompt Artifact — query_issues.sh

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/query_issues.sh` |
| **Description** | Paginate --comments/--comments-json; refuse to truncate (#2095) |
| **Date** | 2026-11-04 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

**Reconstructed after the fact.** The original 2026-10-14 coder dispatch was not
captured, because the change was LOW tier then and needed no artifact. Below is a
faithful summary of issue #2095's "Proposed" section (the requirement) and the
reviewed commit `c31c654a5`:

```
Fix GitHub issue #2095 (bug fix, no separate design doc).

bootstrap/query_issues.sh --comments <N> and --comments-json <N> each make one
gh api ".../issues/<N>/comments?per_page=100" call. The API returns comments oldest
first, so on an issue with more than 100 comments the newest ones are dropped
silently. Make both modes walk every page, the way the edge modes do, and refuse to
print a truncated list: exit non-zero with nothing on stdout, and a clear stderr
message, when the walk cannot complete. Keep each mode's per-comment output format
and order byte-identical. Add tests in tests/automation/test_query_issues.py that pin
the >100-comment behaviour (multi-page success, page-cap refusal, a non-array page,
a failed page read). Commit only the two changed files.
```

## Constraints Specified

- Bash plus `gh` and `jq` only, REST only (no `gh issue list` / `gh pr view --json`).
- Output format and comment order must not change; existing callers parse it.
- Must NOT print a partial list. Output is buffered and printed only after the walk completes.
- Page cap: 10 pages (1000 comments). Past that, fail closed.
- The issue's optional `id`/`updated_at` addition to `--comments-json` (#1632 F3) is out of scope and not done.

## Refinement History

First attempt worked. Code review APPROVED it in one iteration on 2026-10-14. The tier
went from LOW to MEDIUM on 2026-11-04 at re-adoption. Nothing in the code changed: the
`change_classifier.py --tier-floor` application-code rule matched the test `.py` file. The
worker added this artifact before the risk-assessor ran.

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
2. Paste the prompt above, unchanged
3. Compare key logic paths against `bootstrap/query_issues.sh`
4. Note any drift in a new version artifact (`query_issues.v1.md`)
