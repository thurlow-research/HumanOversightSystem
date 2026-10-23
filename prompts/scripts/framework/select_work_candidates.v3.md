# Prompt Artifact — select_work_candidates.py (v3)

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/select_work_candidates.py`, `scripts/framework/check_agents_static.sh`, `bin/hos-cron`, `docs/LABELS.md`, `tests/framework/test_select_work_candidates_native.py` |
| **Description** | #2124: a dedicated `parked` label, excluded by work selection and reported with reason `parked` |
| **Date** | 2026-10-23 |
| **Model** | claude-opus-5-5 (orchestrating worker); `coder` subagent ran on `sonnet` (Claude Sonnet 5.5) |
| **Risk level** | MEDIUM (risk-assessor composite 0.52; protected surface: selector) |
| **Human review status** | ⬜ Pending |

---

## Prompt

The autonomous worker dispatched this brief to the `coder` subagent. The text below is exact:

```
You are implementing issue #2124 in the HOS repo at <repo root>, on branch `worker-2124-parked-label-261023175001-1134462` (already checked out; do not create or switch branches). Commit your work on this branch when done (one commit), with these trailers as ONE contiguous block at the end of the message (no blank line inside the block):

Prompt-Artifact: none (LOW risk)
AI-Model: claude-opus-5-5
AI-Risk: LOW
Supervised-by: ScottThurlow

(If you judge the risk to be MEDIUM or higher, say so in your self-flag. The orchestrator will adjust the trailer.) Commit subject: `feat(#2124): dedicated 'parked' label excluded by work selection`.

## Goal
Add a `parked` label that means "deliberately not selected; no human action pending." Today the only way to park non-core work is `needs-human`, which also means "question pending."

## Required changes (keep them minimal and use the surrounding idiom)

1. `scripts/framework/select_work_candidates.py`
   - Exclude issues labelled `parked` in `_apply_free_filters` (around line 517). Issues labelled `needs-human` are currently dropped silently via `EXCLUDED_LABELS`. Keep that behaviour unchanged.
   - When an issue carries `parked` and not `needs-human`, append `(number, "parked")` to `result.excluded`. It then shows up in the existing stderr `EXCLUDED` diagnostic as `#N(parked)`. It must not be counted in scanned/evaluated, and it must not affect completeness or the exit code. Do the check BEFORE the native-blocker verdict, so the reason is `parked` rather than a native reason.
   - Precedence: if an issue carries both `needs-human` and `parked` (the migration state), keep the existing silent needs-human drop.
   - Add a module constant for the label/reason (e.g. `PARKED_LABEL = "parked"`), placed next to `EXCLUDED_LABELS`.
   - The `EXCLUDED ... : reason_counts` line currently iterates `NATIVE_EXCLUSION_REASONS` only. Include the parked count too, without changing the existing native reason literals, which are ADR-binding. For example, iterate `(PARKED_LABEL,) + NATIVE_EXCLUSION_REASONS`, or append parked. Check the existing tests that assert on that line's exact text and keep them passing. If they assert exact text, appending at the end is safest.
   - Update the module docstring's D2 step line (line ~25) and the `_FreeFilterResult`/`_NativeVerdict` comments if they say that excluded reasons are only native.
2. `scripts/framework/check_agents_static.sh:170`: add `parked` to `KNOWN_LABELS`.
3. `bin/hos-cron` line ~2094: change the context header text `not needs-human` to `not needs-human/parked`. Check tests/automation/test_hos_cron.py for an assertion on that exact string and update it if present.
4. `docs/LABELS.md`: add a table row for `parked` in the same table as `needs-human` (line ~27 onward), using the same column format. The row says:
   - Writers: the human, or the human-proxy at the human's explicit instruction, by hand. No automation writes it. It is hand-created per `docs/MACHINE-ACCOUNTS-SETUP.md` Step 8.
   - Removed by: the human.
   - Control-flow effect: work-selection exclusion only. `select_work_candidates.py` excludes it like `needs-human`, but reports it with reason `parked` in the EXCLUDED diagnostic.
   - Notes: nothing else reads it. No notification, digest row, or escalation; the planned #2102 digest is to report parked items as a count only. It is not a merge block. During the #2119 migration, issues carry both labels, and `needs-human` takes precedence.
   Also update the `needs-ai` row's sentence "excludes any issue also carrying `needs-human`", and the priority row's "not-`needs-human`", to mention `parked`.
5. Tests: in the existing selector test files (`tests/framework/test_select_work_candidates*.py`, matching their fixture idiom), add:
   - an issue with `parked` + `needs-ai` is excluded and reported with reason `parked` (assert on `_apply_free_filters`' `excluded` and/or the stderr `#N(parked)` line);
   - an issue with `parked` + `needs-human` is silently dropped (not in `excluded`);
   - a parked issue does not reduce completeness / change the exit code relative to its absence.
   Also check for a test that pins `KNOWN_LABELS` content, and update it if one exists.

Do NOT touch any `.claude/agents/*.md` files. Do NOT implement the #2102 digest (it isn't built yet). Do NOT change any GitHub labels or issues.

## Verify
Run the narrow tests with `scripts/oversight/.venv/bin/python -m pytest tests/framework/ -q -k "select_work or static" ` and `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_hos_cron.py -q -k context` (or a relevant subset). Run `bash scripts/framework/check_agents_static.sh` too. Then commit.

When you report back, include the commit SHA, the files you changed, the test results, and your RISK/CONFIDENCE/BLAST RADIUS self-flag per AGENTS.md.
```

## Worker-session edits (not delegated)

- The risk-assessor raised the tier from LOW to MEDIUM, so the worker session reworded the commit trailers (`Prompt-Artifact`, `AI-Risk`) to match. The code is unchanged.
- This artifact file was written by the worker session.
