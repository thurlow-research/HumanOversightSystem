# Prompt Artifact — in_progress.py / hos-in-progress label

| Field | Value |
|---|---|
| **Generated files** | `scripts/automation/in_progress.py`, `scripts/automation/lib/github.py` (label helpers), `bootstrap/create_branch.sh`, `bin/hos-cron`, `docs/LABELS.md`, `bootstrap/worker-cron-prompt.md` |
| **Description** | #2157 make the worker's current pick visible: `hos-in-progress` label plus a greppable `WORKING ON` line in the cron cycle log |
| **Date** | 2026-10-23 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surfaces: `bin/hos-cron`, `bootstrap/create_branch.sh`, worker prompt) |
| **Human review status** | Pending |

---

## Prompt

Implemented directly (no requirements/ADR/TD stage). Design brief, summarized:

Goal: (1) a `hos-in-progress` label on the issue the autonomous worker is working on, (2) one line
`WORKING ON #<n> <title> branch=<branch>` in the cron cycle log. No heartbeat, no new protocol. The
label must NOT affect work selection (`scripts/framework/select_work_candidates.py` unchanged).

1. New module `scripts/automation/in_progress.py` (`python3 -m scripts.automation.in_progress`):
   - `mark --issue N --branch B`: ensure the label exists (GET, on 404 POST; 422 already_exists is
     success); remove it from every other open issue carrying it; add it to N; fetch N's title and emit
     the line to stderr and append it (UTC timestamp prefix) to the file named by `HOS_CYCLE_LOG` when
     that names an existing regular file (never create it). Title sanitized to one line, <= 100 chars.
   - `clear`: remove the label from every open issue carrying it (paginated); print
     `in-progress: cleared #a,#b` or `in-progress: none`.
   - Reuse `scripts/automation/lib/github.py` (`_run_gh` retry/backoff; small public label helpers added)
     and `merge_config.resolve_repo_slug`. DELETE 404 means already removed.
   - Always best-effort: any failure is a stderr warning and exit 0; exit 2 only for usage errors.
   - GitHub calls go through `github.*` functions so tests can monkeypatch them.
2. `bootstrap/create_branch.sh`: after Step 6 success (fresh create and idempotent re-entry), for
   `PREFIX=worker` only, run `mark` from the repo dir best-effort with stdout redirected to stderr, so the
   branch name stays the only stdout line.
3. `bin/hos-cron` (worker role only): export `HOS_CYCLE_LOG` from `readlink /proc/$$/fd/1` when it is a
   regular file; run `clear` at cycle start; extend the EXIT trap to run `clear` (bounded by `timeout 60`)
   before releasing the lock, armed only once the cycle has authenticated. SIGKILL leaves the label until
   the next cycle's start-clear; no timer.
4. `docs/LABELS.md`: document `hos-in-progress` in its own row; keep `hos-autowork-authorized` and
   `suppression-expired` in the unimplemented row.
5. `bootstrap/worker-cron-prompt.md` Step 2b: one sentence - the label and log line are automatic; do not
   add or remove the label by hand.
6. Tests: `tests/automation/test_in_progress.py` (mark/clear/404/422/best-effort/log-file/sanitization,
   create_branch stdout contract, hos-cron EXIT-trap source check).
