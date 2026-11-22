# Prompt Artifact — bin/hos-cron (#2405 reap abort audit + shallow-clone escalation)

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (overseer `reap-orphans` block, worker `reap-landed` block), `scripts/automation/readopt.py` (`reap_orphans` SUMMARY fields), `tests/automation/test_hos_cron.py`, `tests/automation/test_readopt*.py`, `docs/CRON-SETUP.md` |
| **Description** | Audit every non-dry-run reap outcome (summary + loud abort event), escalate a shallow clone once per state change, mark shallow dry-run previews `shallow=1` (#2405, child of #2287) |
| **Date** | 2026-11-19 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (protected surface `bin/hos-cron`) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with the brief below (bug fix,
no separate design chain: the issue's "Required" section is the spec).

```
Fix #2405 on the current branch. Do NOT switch branches, stash, checkout, reset or rebase.

A. scripts/automation/readopt.py reap_orphans(): APPEND two fields to the SUMMARY line
   (append-only convention; existing consumers match leading fields by name):
     shallow=<0|1|->   (- only when the run aborted before the shallow check could run)
     abort_reason=<none|shallow-clone|git-error|listing-failed>
   Evaluate shallowness once. Keep every existing exit code and line unchanged. In a shallow
   DRY run also print a WARN that the preview is unreliable.
B. bin/hos-cron overseer reap block (#2287):
   1. Parse reaped_local/reaped_remote/kept/failed/aborted/shallow/abort_reason from SUMMARY.
   2. mode=on: emit ONE cycle-branch-reap-summary event per run (role, mode, counts, aborted,
      shallow, rc). When aborted=1, rc!=0, or no SUMMARY line was parsed, ALSO emit a distinct
      cycle-branch-reap-aborted event (role, mode, rc, reason: abort_reason, or timeout /
      no-summary) and a loud WARN line naming the reason.
   3. dry-run: the existing cycle-branch-reap-dry-run event gains shallow=<v>; when shallow=1
      log a WARN that the preview is unreliable and must not justify switching to on.
   4. Shallow clone (either non-off mode): escalate once per state change, modelled on the
      #1510 diverged-main block (fail-CLOSED title-prefix dedup query; raw gh issue create
      with needs-human + priority:high as that block does). A state file under
      $_HOS_DIR/branch-reap/ marks "escalated"; write it only after a successful file or a
      confirmed existing open issue; remove it when a run reports shallow=0 so a later
      recurrence escalates again. Audit cycle-branch-reap-shallow-escalated. Do NOT run
      git fetch --unshallow (it changes the clone; a human decides). Body suggests it.
   5. Keep the stamp-after-every-attempt behaviour (the escalation, not the stamp, removes the
      silence).
C. bin/hos-cron worker reap-landed block: when rc != 0, also emit
   cycle-branch-reap-aborted role=worker reason=<rc=N[ timeout]> (same gap, both roles).
D. Tests: on-mode abort produces the summary + aborted events; shallow dry run carries
   shallow=1; shallow escalation files once, not again on the next run, and re-arms after a
   shallow=0 run; failed dedup query files nothing; readopt SUMMARY fields. Tests clean up
   their own temp.
E. docs/CRON-SETUP.md audit-event table: document the new events/fields.

Commit trailers: Prompt-Artifact: prompts/bin/hos-cron.v2405.md, AI-Risk: HIGH. "Part of #2405".
```

## Fix round (reliability)
1. Both shallow-escalation gh calls (paginated dedup query, `gh issue create`) are wrapped in a
   `_RB_GH_BOUND` timeout (30 s, kill-after 5; `gtimeout` fallback); a timeout falls into the
   query-failed / file-failed branches (fail closed, no marker). Test added for rc 124.
2. Dedup query `per_page` raised 30 -> 100; still no label filter.
3. `gh issue create` stderr is captured; on failure its first line (control chars stripped, 200
   chars) is appended to the WARN only, never to the audit event.
4. Docs/issue body: `<clone>` is the overseer clone; the reap re-runs after unshallow only when the
   24 h stamp expires (delete it to force a re-check); the marker clears itself on a full-clone run.
