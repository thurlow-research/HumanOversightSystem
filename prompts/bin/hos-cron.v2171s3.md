# Prompt Artifact — hos-cron (#2171 slice 3)

| Field | Value |
|---|---|
| **Generated file** | `bin/hos-cron` (+ `tests/automation/test_hos_cron.py`) |
| **Description** | Pre-agent `gh` consumers check the exit status before using the output; static check that no `$(gh ...)` substitution carries an in-substitution `\|\|` fallback |
| **Date** | 2026-10-29 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

The spec is GitHub issue #2171, acceptance criterion 3 ("No `hos-cron` step
consumes `gh` output without checking its exit status (test or static
check)"), as deferred from slice 1 (code-review SHOULD_FIX-3 in
`.claudetmp/signoffs/step2171-register.md`). Slices 1 (PR #2207, post-agent
sites) and 2 (PR #2210, github.py 401 retry) are merged. Behavior 4
(agent-session refresh), ops-field additions on the refresh audit events, and
the SIGTERM mint-tempfile cleanup are OUT of scope.

Why it matters: `gh api --jq ...` on an HTTP error exits non-zero AND writes
the error JSON body to stdout, so `x=$(gh api ... || echo 0)` yields
`{ "message": "Bad credentials" ... }0` — the observed
`[[: ...: arithmetic syntax error` in #2171. Where it does not crash, the
fallback silently substitutes a fabricated value (e.g. a CHANGES_REQUESTED
count of 0) and routes the cycle on it.

### Sites to fix in `bin/hos-cron` (line numbers at origin/main 98c3f5570)

1. **Worker PR routing loop (~1270-1309).**
   - `_pr_detail=$(gh api .../pulls/N ... || echo '{...}')`,
     `_pr_cr=$(gh api .../reviews ... || echo "0")`,
     `_pr_ap=$(gh api .../reviews ... || echo "0")`.
   - Capture each call's status separately from its output: use the existing
     idiom `if x=$(gh ...); then` or `x=$(gh ...) && rc=0 || rc=$?`, which is
     safe under `set -e` (see the comment at ~1349).
   - Validate the CR/AP counts against `^[0-9]+$` before any arithmetic.
   - On any failed or malformed per-PR call, log
     `"$LOG_PREFIX WARN: PR #N state fetch failed — routing unknown"` and set a
     degraded flag. Continue to the remaining PRs, because a later PR may still
     yield a definite `needs-fix` / `needs-fix-bounce`, and those still `break`
     and win.
   - After the loop: if the flag is set and routing is still
     `awaiting-merge` or `needs-attention`, set `_PR_ROUTING="unknown"`, echo a
     log line and `_audit cycle-pr-state-unknown "pr_nums=..."`.
   - A failed call must never produce `awaiting-merge` (which posts a
     "nothing to fix" notice and wakes the overseer).
   - Add an explicit `unknown)` case to the New-work-directive `case` in
     `_build_context` (~2192). Its text says:
     - the state of at least one open PR could not be determined (a GitHub call
       failed), and this is NOT "nothing to fix";
     - read each listed PR's reviews and comments, and if one has
       CHANGES_REQUESTED, a conflict, or a human-applied `needs-ai`, fix and
       push, then STOP;
     - otherwise STOP and do not proceed to Step 2.
2. **Overseer pre-filter loop (~1425-1430).**
   - `_detail=$(gh api ... || echo '{"ms":"unknown","d":false}')`: check the
     status separately.
   - On failure, keep today's routing: treat the PR as actionable with
     `ms=unknown`. The overseer re-checks live state and the merge gates are
     independent. Log a WARN.
   - Never concatenate an error body with a fallback.
3. **`_build_context` "Open bot PRs" (~2153).**
   - `_ctx_prs=$(gh api ... || echo "")`: on failure, print
     `(fetch failed — the New work directive below is authoritative)` instead
     of `None.`.
   - Keep the function fail-open: never abort the launch.
4. Sweep the rest of `bin/hos-cron` for any other `$(gh ...)` substitution with
   an in-substitution `||` fallback and fix it the same way.
   - Sites that already use `if x=$(gh ...)` are fine.
   - `gh ... || echo "$LOG_PREFIX WARN..."` outside a substitution writes to the
     log, not to a variable, and is fine.

### Static check (tests/automation/test_hos_cron.py)

Add a test class (e.g. `TestNoUncheckedGhSubstitution`) that reads
`bin/hos-cron` and works as follows:
- Join backslash-continued lines into logical lines and ignore comment lines.
- Find every command substitution whose command starts with `gh`
  (`$(gh ...`). This includes a substitution that spans continuation lines.
- Assert that none contains a `||` before its matching close paren.
- The failure message names the line number.
- Include positive and negative fixture tests of the checker itself:
  - a bad snippet is flagged: `x=$(gh api foo || echo 0)`, including the
    multi-line continuation form;
  - good snippets pass: `if x=$(gh api foo); then`, `x=$(gh api foo) && rc=0 || rc=$?`,
    and `gh api -X PATCH foo || echo "WARN"`.

Add behavioral tests using the existing test harness and `gh` stubs in
`test_hos_cron.py`:
- a `/reviews` call that fails with a 401 body routes `unknown`, not
  `awaiting-merge`, and the directive text contains `routing=unknown`;
- a definite `needs-fix` on a later PR still wins over an earlier failed PR.

Match surrounding comment density. Reference `#2171` in new comments. Don't
change unrelated code. Don't touch protected files other than `bin/hos-cron`.
