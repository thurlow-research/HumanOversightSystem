# Prompt Artifact — validation_logic.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/validation_logic.py` |
| **Description** | #1799 slice 1: ledger-silenced audit trail + placeholder-CWE fail-closed |
| **Date** | 2026-10-11 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` agent (prompt text, task-relevant body):

```
### Part A — audit trail of silenced findings (the main deliverable)
Nothing records WHICH finding the ledger silenced. Implement:
1. `compute_verdict` additionally returns a key `"silenced"`: a list, one entry per
   blocking finding counted in `dedup_count` (i.e. blocking, non-degenerate,
   fingerprint in `seen`), each a dict `{"fingerprint": <fingerprint string>,
   "severity": <normalized severity>, "summary": <one-line summary>}`. Summary: first
   non-empty string among the finding's `finding`, `title`, `description`, `why` keys;
   collapse whitespace to single spaces; truncate to 160 chars (append "…" if
   truncated); "" if none. Existing return keys and their values must be unchanged;
   `len(silenced) == dedup_count` must always hold (add a test asserting it).
2. `_cmd_process`: after computing the result, if `silenced` is non-empty, print to
   stderr one header line `validation_logic process: ledger silenced <N> blocking
   finding(s) — verify each disposition actually covers it (#1799):` then one line per
   entry `  silenced [<severity>] <fingerprint> — <summary>`. Every interpolated value
   MUST go through the existing `_safe_log` (CWE-117: reviewer text is
   diff-influenceable). Print nothing extra when nothing is silenced. Stdout output and
   the header rewrite behaviour must be unchanged.

### Part B — malformed / placeholder CWE fails closed
When the class is sourced from the `cwe` field (i.e. `category` and `type` are both
empty/absent) and the normalized value does NOT match canonical `cwe-<digits>`,
`_class_of_finding` returns "" so `_is_degenerate` treats it as degenerate: it can
never be silenced and always counts as NEW blocking. Must become degenerate:
`CWE-XXX`, `CWE-N/A`, `n/a`, `79`. Must stay valid: `CWE-89`, `cwe-0703` (→ `cwe-703`),
`CWE-79: XSS`. Do NOT change `category`/`type` handling (agy's `other` is out of scope).

Do NOT change the fingerprint format or add a content-hash discriminator — that is an
open human design decision. `test_same_file_same_class_still_collides_known_limit`
must keep passing unchanged.
```

## Constraints Specified

- Python 3, no new dependencies; module is shared with `second_review_logic.py` via `is_ledger_resolved`.
- Security: every reviewer-derived value in the stderr report goes through `_safe_log` (CWE-117).
- Must NOT: change the fingerprint format, add a discriminator, touch `category`/`type` handling, or alter counts/verdict for any non-placeholder input.
- No branch/PR/issue/label actions by the coder.

## Refinement History

v1: Parts A and B as above (commit 867e86242).
v2: Gate cleanup in touched files — unused imports, black reformat, mypy `ModuleSpec | None` assert, docstring rewrap (db5bfd10c).
vFinal: security-reviewer SHOULD_FIX (CWE-400) — in the stderr report only, truncate the fingerprint to `_REPORT_FP_MAX = 200` chars and list at most `_REPORT_MAX_ENTRIES = 50` entries plus a "… and N more" line; returned `silenced` keeps full fingerprints (59eb4c88c).

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
3. Compare key logic paths against `scripts/oversight/validation_logic.py`
4. Note any drift in a new version artifact (`validation_logic.v1.md`)
