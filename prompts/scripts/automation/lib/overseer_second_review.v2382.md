# Prompt Artifact — overseer_second_review.py (v2382)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/overseer_second_review.py`, `tests/automation/test_overseer_second_review.py` |
| **Description** | #2382: `_read_json_dict` opens state files `O_RDONLY \| O_NOFOLLOW` without `O_NONBLOCK`, so a FIFO planted at a record/counter/raise/pending path blocks `open()` indefinitely — including under `head_lock` via `_refresh_raise_locked` (CWE-400). Add `O_NONBLOCK` so the existing `fstat` + `S_ISREG` check rejects the FIFO fail-closed. |
| **Date** | 2026-11-20 |
| **Model** | claude-opus-5-5 (orchestrating worker and `coder` subagent) |
| **Risk level** | MEDIUM (classifier tier floor for `.py`) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → `coder` subagent brief:

```
Implement GitHub issue #2382 in the HOS repo (cwd <Worker clone root>,
branch worker-2382-state-read-o-nonblock-261120125001-827874, already checked out — do NOT
switch branches, stash, or checkout other refs).

## Problem
`_read_json_dict` in scripts/automation/lib/overseer_second_review.py (~line 267) opens with
`os.O_RDONLY | os.O_NOFOLLOW` and only checks `S_ISREG` after open() returns. A FIFO planted
at any path it reads (record, counter, raise, pending) makes open() block forever when no
writer is present. Since TD-2357-S1a P6 the raise file is re-read inside head_lock
(`_refresh_raise_locked`), so the block would hold the per-head lock.

## Required
1. Add `os.O_NONBLOCK` to the os.open flags in `_read_json_dict`. The existing fstat/S_ISREG
   check then returns None (invalid, fail-closed). Do not clear O_NONBLOCK afterwards
   (POSIX regular-file reads ignore it); say so in a one-line comment. Update the docstring
   to mention FIFOs are refused without blocking. No other behaviour change for regular files.
2. Tests in tests/automation/test_overseer_second_review.py (read the file first; reuse its
   harness `h`, `_race`, `_write_raise_file`, `_review_tiers` helpers):
   a. Unit: a FIFO with NO writer at a path passed to `_read_json_dict` returns None promptly.
      The test must not hang the suite against the unfixed code: run the call in a daemon
      thread and join with a timeout (e.g. 5s), asserting the thread finished and the result
      is None; in a finally, release any blocked opener with a non-blocking O_WRONLY/O_RDONLY
      open as the existing FIFO test does.
   b. Under the lock: add "fifo" as a kind to the existing parametrized
      `test_t31b_an_invalid_raise_that_appears_counts_as_high` (hook plants os.mkfifo at
      osr._raise_path(h.root, PR, HEAD)), OR a sibling test with the same assertions
      (tier HIGH, vendors agy+codex, raise None, exactly one "raise-invalid" in defaulted).
      It must also be hang-safe against the unfixed code (thread + join timeout, or a
      SIGALRM guard restored in finally) — pick whichever fits the harness; explain why.
   c. Confirm the existing `test_read_json_dict_refuses_a_non_regular_file_even_when_small`
      still passes and still kills its mutant.
3. Run: scripts/oversight/.venv/bin/python -m pytest tests/automation/test_overseer_second_review.py -q > .claudetmp/t2382.log 2>&1
   then Read the log. Also verify your new tests FAIL (time out / assert) with O_NONBLOCK
   removed, then restore it — report that result.

## Constraints
- Python, black-formatted (repo config), ruff/mypy clean.
- One command per Bash call; no && chaining; redirect output to .claudetmp/ and Read it.
- Commit with exactly this trailer block (one contiguous block, after a blank line):
    Prompt-Artifact: prompts/scripts/automation/lib/overseer_second_review.v2382.md
    AI-Model: claude-opus-5-5
    AI-Risk: MEDIUM
    Supervised-by: ScottThurlow
  Subject: "fix(#2382): open state files O_NONBLOCK so a planted FIFO cannot block under head_lock".
  Do NOT put a closing keyword (closes/fixes/resolves #N) in the commit message.
- Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final message.
```
