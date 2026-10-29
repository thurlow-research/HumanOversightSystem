# Prompt Artifact — hos-cron (#2171 slice 1)

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (+ `tests/automation/test_hos_cron.py`, `docs/CRON-SETUP.md`) |
| **Description** | Refresh the cycle GitHub App token before post-agent steps; never parse a failed `gh` call's output as data |
| **Date** | 2026-10-29 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

The spec is GitHub issue #2171, required behaviors 1 and 3 only:

```
1. Refresh before expiry. hos-cron re-mints the cycle token before its
   post-agent steps (EXIT trap, audit push, label clear, breaker queries), or
   whenever the token is older than about 50 minutes. Use
   bootstrap/get_app_token.sh; never hand-build a JWT (CLAUDE.md).
3. Never parse an error as data. Post-cycle steps check the gh exit status
   before using its output; a failed call is reported, not fed to arithmetic
   or comparisons.
```

Behaviors 2 (`github.py` retry once on 401) and 4 (agent-session refresh) are
out of scope for this slice.

The first commit was built by a worker cycle that was stopped before it could
open a PR. Its exact `coder` dispatch text was not kept. The issue text above is
the authoritative spec it was built against. This cycle adopted the branch with
`bootstrap/create_branch.sh --from`, per worker.md §"Re-adopting a stalled
branch".

## Constraints Specified

- The refresh is age-gated by `HOS_TOKEN_REFRESH_AGE_SECS` (default 3000 s) and
  best-effort: on any failure it keeps the current token, logs a `WARN`, emits
  `cycle-token-refresh-fail`, and never aborts the cycle.
- A refreshed token is accepted only if its identity matches the one this cycle
  passed its guard with. The token value is never logged.
- The token mint goes through `bootstrap/get_app_token.sh` only.

## Refinement History

1. `54be6e071`: the initial slice (refresh function, post-agent and EXIT-trap
   call sites, checked did-work queries, tests).
2. Code-review iteration 1 (`.claudetmp/signoffs/step2171-register.md`):
   - SHOULD_FIX-1: pin the identity check to the live guard and source the
     token file once.
   - SHOULD_FIX-2: move the EXIT-trap refresh below the consumer-install guard
     and bound the mint (`HOS_TOKEN_REFRESH_TIMEOUT_SECS`, default 90 s).
   - NIT-2: document the knobs and the audit event in `docs/CRON-SETUP.md`.
   The stopped cycle left these as uncommitted edits; this cycle committed them.
3. Applied `black` formatting to the test file.

Deferred: SHOULD_FIX-3 (the pre-agent `|| echo 0` sites, plus a static check)
and NIT-3 (retrying a transient mint failure) belong to the later slices.

## Human Review Notes

Protected surface (`bin/hos-cron`): this needs CODEOWNERS human approval.

## Reproducibility Check

Covered by the `TestMidCycleTokenRefresh` tests in `tests/automation/test_hos_cron.py`.
