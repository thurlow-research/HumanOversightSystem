# Prompt Artifact — scripts/automation/readopt.py + bin/hos-cron (#2401 prune-attempts archive cause, % in archive regexes)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/readopt.py` (`make_git`, `_archive_unlanded`, `prune_attempts`), `bin/hos-cron` (`_RB_ARCHIVED_RE`, `_RB_ARCHFAIL_RE`), `tests/automation/test_readopt.py`, `tests/automation/test_hos_cron.py` |
| **Description** | Per-branch archive-failure cause instead of the sticky runner-wide `first_error`; accept percent-encoded names in the hos-cron archive regexes; guard the dry-run `_tip_on_base`; exclude the checked-out branch from the shallow-clone count (#2401, follow-up of #2314) |
| **Date** | 2026-11-20 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surface `bin/hos-cron`) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with the brief below (bug fix,
no separate design chain: the issue's Problem + Acceptance criteria are the spec).

```
Fix #2401 on the current branch (worker-2401-prune-archive-cause-pct-regex-261120115002-77334).
Do NOT switch branches, git stash, checkout, reset or rebase. Use single Bash commands (no
&&/; chaining, no pipes into tail); redirect long output to .claudetmp/ and Read it.

1. Archive-failure cause (scripts/automation/readopt.py).
   Today prune_attempts (~L639) prints `git.first_error`, which make_git sets once per run at
   the first failing call, so an earlier unrelated failure is reported as the cause of every
   later archive failure.
   - make_git: keep `run.first_error` EXACTLY as it is (reap-orphans relies on it, ~L1497).
     ADD `run.window_error`: same capture rule (first `fatal:`/`error:` stderr line,
     case-insensitive, of a failing call), but it is a resettable window — it records only
     when currently empty, and callers reset it by assigning "". Initialise to "".
   - _archive_unlanded: immediately BEFORE calling _write_local_archive (i.e. after
     _tip_on_base), reset the window if the runner has it:
       if hasattr(git, "window_error"): git.window_error = ""
     Do NOT change _write_local_archive's signature or bool return (tests monkeypatch it).
   - prune_attempts: the archived-is-False cause becomes
       _one_line(getattr(git, "window_error", "") or "")
     Runners lacking the attribute still print no cause (keep the existing test at ~L3842
     passing). Update any existing test fakes that set first_error to exercise this cause so
     they set window_error instead (and reset semantics work on the fake).
   - Test (required by AC): one run where an EARLIER unrelated git call fails with a
     `fatal:` line (e.g. an earlier branch's merge-base or a prior call) and a LATER branch's
     archive write fails with a different `fatal:` line; assert the later WARN names the
     later cause and never the earlier one. Also a make_git-level test of window_error
     (records first in window, reset re-arms, first_error unaffected by reset).

2. Percent-encoded names (bin/hos-cron ~L1842-1843).
   readopt._printable_name percent-encodes any name failing _SAFE_NAME_RE, but
   _RB_ARCHIVED_RE and _RB_ARCHFAIL_RE accept only [A-Za-z0-9._/@+-]+ for the branch and ref
   tokens, so those lines are silently dropped. Add `%` to those character classes ONLY in
   these two regexes (other regexes are out of scope; #2336 covers the reap path). Keep the
   anchoring. Test in tests/automation/test_hos_cron.py next to the existing archive tests
   (~L4339): feed `ARCHIVED branch=worker-5-a%20b where=local ref=refs/archive/reap/worker-5-a%20b@<12hex> tip=<40hex>`
   and a `KEEP branch=worker-6-c%0Ad reason=archive-failed where=local tip=<40hex>` line and
   assert both audit events are emitted with the encoded names verbatim.

3. Dry-run unguarded (readopt.py prune_attempts ~L626-630).
   In dry run, wrap the _tip_on_base call: on exception print
     WARN: archive check of '<printable branch>' raised: <_one_line(exc)>
   and treat the tip as NOT on base (so the preview still shows archive=<ref>, the safe
   answer), then continue with the rest of the preview. Test: a runner raising on
   merge-base in dry run prints the WARN and still previews every branch.

4. Shallow-clone count (readopt.py ~L600-625).
   Exclude the checked-out branch from `doomed` for the shallow decision and count: compute
   the candidate list without `current` before `shallow = bool(...) and _is_shallow(git)`.
   The checked-out branch still prints its existing "is checked out — not deleting" WARN.
   Result: if the current branch is the only doomed attempt, no shallow WARN is printed, no
   archive_failed entry, CLI exit 0 (consistent: nothing was refused); if there are others,
   the WARN count and archive_failed (exit 3) cover only the others. Tests for both cases,
   including the CLI exit code.

5. Update the prune_attempts docstring (and the make_git docstring) to describe the new
   behaviour briefly. No other behaviour changes.

Run `bash scripts/framework/run_tests_inner_loop.sh > .claudetmp/tests-2401.log 2>&1` and
`scripts/oversight/.venv/bin/black --check scripts/automation/readopt.py tests/automation/test_readopt.py tests/automation/test_hos_cron.py`
(fix formatting with black if needed). Commit with this exact trailer block (one contiguous
block, no blank lines inside it):

Prompt-Artifact: prompts/scripts/automation/readopt.v2401.md
AI-Model: claude-opus-5-5
AI-Risk: HIGH
Supervised-by: ScottThurlow

Do not use closing keywords (closes/fixes/resolves #N) in commit messages; write "(#2401)".
Self-flag per AGENTS.md in your report.
```
