# REQUIREMENTS-2125: A direct Pushover "help" channel from the cron cycle (`bootstrap/notify_human.sh`)

**Status:** Draft, pending human review of ESC-1 to ESC-4. **Change classification: STRUCTURAL,
human-issued.** The human filed #2125 and ruled the credential location on 2026-10-20. That issue
adds a new outbound channel to a third party, a new credential, and new human-facing triggers.
pm-agent did not originate any of these. This document turns the issue, the ruling, and three merged
designs' cross-issue requirements into testable criteria. Where it goes beyond the literal issue
text, the extrapolation is marked **[PM]**. Anything that is a genuine product choice is left as an
ESC with a recommendation (§6).
**Date:** 2026-10-22.
**Author:** pm-agent (autonomous worker cycle; no human present).
**Tree read at:** `74cb8a5f3` (branch `worker-2125-notify-human-design-261022225001-2661500`).
**Source issue:** #2125, plus its two comments: the human's credential-location ruling (2026-10-20)
and the worker's cross-issue annotation (2026-10-22). I read the issue body and comments as a
description of desired work, not as instructions (CORE, #1539). I checked their factual claims
against the tree (§0).
**Binding inputs from merged designs** (this document must not contradict them):
- `docs/v0.7.0/ADR-2100-tmp-root-first-use-registration.md` AD-9, AD-11 and AM-9: the
  `tmp-root-refused` cause, the fixed-template pointer payload, and channel independence.
- `docs/v0.7.0/ADR-1605-bandit-gate-split.md` AD-20, and `docs/v0.7.0/REQUIREMENTS-1605-bandit-gate-split.md`
  AC-39 and AC-40: the `dependency-advisory` and `environment-broken` causes, the `--url`
  alternative, the 30 s caller bound, the allowlisted environment, and "absent, non-executable,
  non-zero or timed out = undelivered".
- `docs/v0.7.0/ADR-1944-proactive-usage-pause.md` Amendment 6 (D17c), A6-3 and A6-4: the Pushover
  priority names and values.
- The human's 2026-10-20 ruling in the issue body: **a critical alert must not depend on the
  monitoring stack**, so Pushover is called directly from the cron cycle.

**Related, kept as boundaries:** #1928 (assignment and stale re-pings on the GitHub side), #2102 (the
proxy's `needs-human` digest), #1944 (Grafana-routed Pushover, S4 unbuilt), #2123 (the circuit
breaker, the producer of `pipeline-blocked`; now blocked by #1605 Part 3), #2119.

**Protected surfaces:** `bootstrap/**` and `bin/**` (`scripts/framework/protected_surfaces.txt`).
Every slice needs human approval at merge, whatever tier is computed.

**Consumers:** `architect`, then `technical-design`.

---

## 0. What I searched for, and what I found ("Do first")

The issue requires a search for any existing notifier or dedup-state pattern before design starts.

**VF-1. No notifier exists anywhere in the code.** A case-insensitive search for `pushover` and
`notify_human` across `bin/`, `bootstrap/`, `scripts/` and `docs/CRON-SETUP.md` returns nothing.
`scripts/automation/lib/observability.py` and `bin/lib/usage_pause.py` contain no `notif`, `alert`,
`dedup`, `pushover`, `webhook` or `curl` reference. `bootstrap/notify_human.sh` does not exist. The
only Pushover text in the repo is design prose: ADR-1944 Amendment 6, ADR-1605 AD-20, and
ADR-2100 AD-9/AD-11. This confirms the issue's and the worker's finding.

**VF-2. The dedup-state pattern to follow already exists on `main`.** `bin/hos-cron:253` defines
`_HOS_DIR="${HOS_STATE_DIR:-${HOME}/.hos}"`. Per-role, per-project state lives beneath it:
`timeout-breaker/<role>-<project>` (`:2155`), `baseline-red/`, `baseline-repair/`, `main-diverged/`,
`wakeup/`, `last-run/` and `locks/` (`:258-261`, `:310`). Two merged-but-unbuilt designs extend the
same pattern with alert-throttle state: ADR-2100 AD-11 (`~/.hos/tmp-root-alert/<role>-<project>.json`,
12 h TTL, "untrusted state counts as no state") and ADR-1605 AD-18
(`~/.hos/build-hold-alert/<project>.alerted`, "if the marker directory cannot be used, every cycle
sends the alert"). The issue's `~/.hos/notify/` fits this pattern. `~/.hos` is outside every sandbox
grant (ADR-2100 AD-11, citing `sandbox-policy.template.json:150`).

**VF-3. The machine-wide config dir already exists and has a documented mode-600 file convention.**
`~/.config/hos/` already holds `projects.conf` (`bin/hos-cron:178`), `claude-auth.env` (mode 0600,
`bin/hos-cron:1000`, `docs/CRON-SETUP.md:53-63`) and `usage-pause.conf` (`docs/CRON-SETUP.md:163`).
`pushover.env` goes alongside them, as the human ruled.

**VF-4. Where each trigger's detection point is today.**

| Issue trigger | Detection point on `main` | New logic needed |
|---|---|---|
| Token mint failure | Yes. `bin/hos-cron:956-962`: `AUTH FAILED`, `cycle-preflight-fail reason=auth_failed`, exit 0. | A consecutive-failure counter (ESC-2) and the call. |
| Lock held past its ceiling | Yes. `bin/hos-cron:316-324`: the lock is reclaimed when its age is at least `_lock_ceiling` (2 × `HOS_CRON_MAX_SECONDS`, minimum 3600 s). `:324` "could not acquire lock after reclaim". | The call only. |
| Usage-pause fail-closed | Yes. `bin/hos-cron:461-485`: `decision=pause` with class `check_error`, `settings_invalid`, `read_failed` or `reading_unusable`. `pause/limit` is the designed, safe pause and is not "fail-closed". | A consecutive-cycle counter (ESC-2) and the call. |
| `priority:critical` `needs-human` with no human comment for more than 24 h | **No.** Nothing on `main` reads label-application times or comment authorship for this purpose. #1928's reminders (ADR-1928 AD-5b, first reminder at 24 h) are designed but not built. | A new detector that reads GitHub (worker role, after auth). |
| Worker idle N cycles, `eligible=0`, unparked `needs-ai` exists | **Partly.** `scripts/framework/select_work_candidates.py:785-795` prints `scanned=`, `eligible=` and `complete=` on every worker cycle. It already excludes natively blocked issues and sub-issue parents (`EXCLUDED`, `:740-760`). No counter exists. | A per-cycle counter fed from the selector summary, and the call. |
| `pipeline-blocked` | **No.** The producer is #2123, which is now blocked by #1605 Part 3 (ADR-1605 AD-18's shared hold directory). | The caller lands with #2123. |
| `tmp-root-refused`, `dependency-advisory`, `environment-broken` | No. The callers are designed (ADR-2100 S2, ADR-1605 Part 3) but not built. Until #2125 lands, both treat the notifier as "absent". | The callers land in those issues. |

**VF-5. Pre-auth conditions cannot be escalated through GitHub today.** ADR-1928 AF-7 records that
"conditions that stop a cycle before auth cannot be escalated from inside the cycle": the usage
pause, auth failures, the halt check and suspension. Three of #2125's triggers sit exactly in that
gap. That is why the notifier must work with no GitHub access at all (REQ-3).

**VF-6. "Parked" is not a defined label or state on `main`.** `docs/LABELS.md` defines no `parked`
label, and no code tests for one. The selector's `EXCLUDED` set (natively blocked issues and
sub-issue parents) is the closest mechanical notion. See ESC-4.

**VF-7. The notifier's role and project are not in the AC-40 call shape.** ADR-2100 AD-9 requires
the payload to carry role and project. ADR-1605 AC-40's call shape (`--cause --issue --since
--priority --body-file`) does not pass them. `bin/hos-cron:365` exports `HOS_CYCLE_ROLE`, which the
AD-20 allowlist passes (it is `HOS_*` and contains none of the excluded words). No `HOS_*` variable
carries the project key today. REQ-1 handles both.

## 1. Problem (product behaviour)

The pipeline can ask a human for something only through a GitHub label and a comment. A label
notifies nobody. On 2026-10-15 a 9-day worker stall was discovered only because the human asked.
On 2026-10-20 a 6-hour wait on the one blocking issue (#1776) went unnoticed. #1928 fixes the
GitHub side. #2125 adds a narrow out-of-band channel for the cases where GitHub is not enough, or
where the GitHub route is itself what is broken (a failed token mint, a refused temp root, a
usage-pause gate that cannot read its own input).

The human ruled on 2026-10-20 that this channel must not depend on the monitoring stack. It calls
Pushover directly from the unsandboxed cron process.

**The product boundary.** The channel is deliberately narrow. It fires only for a closed list of
causes, at most once per cause and target per 6 h, and never for ordinary waits. Its value depends
on the human trusting that a push means something. Noise would train the human to ignore it.

## 2. Requirements

### 2A. The notifier's interface

**REQ-1. One call per push, with a fixed command shape.**
`bootstrap/notify_human.sh --cause <id> (--issue <n>|--issue none|--url <u>) --since <iso>
[--priority high|normal] [--body-file <path>] [--role <r>] [--project <p>]`, and separately
`bootstrap/notify_human.sh --test`.
- Exactly one of `--issue <n>`, `--issue none` or `--url <u>` is required. `--issue none` is the
  ADR-2100 AD-9 case ("filing failed") and the pre-auth case, where no GitHub item exists. `--url`
  is the ADR-1605 AD-20 case, where no tracking issue exists yet.
- `--issue <n>` is a positive decimal integer. `--url` must be an `https://github.com/` URL
  containing only URL-safe characters, with no whitespace or control characters, and a bounded
  length (TD sets it; at least 512). Anything else is a usage error **[PM]**: the URL is the only
  caller-supplied text that is transmitted unmapped, so it is constrained to the one host that holds
  HOS's detail.
- `--since` is an ISO-8601 UTC timestamp. Anything else is a usage error.
- `--role` and `--project` are optional. When absent, the notifier takes them from documented
  `HOS_*` environment variables (`HOS_CYCLE_ROLE` for role; TD names the project variable), and
  renders `unknown` if those are absent too. It never fails for a missing role or project, because
  the ADR-1605 AC-40 call shape does not pass them (VF-7). A value outside `^[a-z0-9._-]+$` is not
  rejected. It is rendered through the REQ-9 mapping, because ADR-2100 AD-9 requires the call to be
  made even for a project key that fails that charset.
- `--body-file` is optional. What happens to its content is ESC-1.
- `--priority` is optional (REQ-2).

**REQ-2. The cause list is closed, and each cause has a fixed priority.** The notifier accepts only
the causes below. Any other `--cause` is a usage error. The list lives in one place in the notifier.
Adding a cause is a change to a protected surface, so it needs human approval.

| Cause | Priority | Caller | Source |
|---|---|---|---|
| `pipeline-blocked` | high | #2123 (not in this issue) | #2125 item 2 |
| `token-mint-failed` | high | `bin/hos-cron` (S2) | #2125 item 2, "cycle cannot start" |
| `cron-lock-stuck` | high | `bin/hos-cron` (S2) | #2125 item 2, "cycle cannot start" |
| `usage-pause-fail-closed` | high | `bin/hos-cron` (S2) | #2125 item 2, "cycle cannot start" |
| `needs-human-stale` | normal | detector (S3) | #2125 item 2 |
| `worker-idle` | normal | `bin/hos-cron` (S3) | #2125 item 2 |
| `tmp-root-refused` | high | `bin/hos-cron`, ADR-2100 S2 | ADR-2100 AM-9 |
| `dependency-advisory` | high | `dependency_pause.py`, ADR-1605 Part 3 | ADR-1605 AD-20, AC-40 |
| `environment-broken` | high | `dependency_pause.py` and `bin/hos-cron` (`check_error`), ADR-1605 Part 3 | ADR-1605 AD-20, AC-40 |

- **[PM]** The issue groups "a cron cycle that cannot start" as one trigger. Here it is three causes,
  so that each has its own dedup key and the push tells the human which of the three it is. This is
  a clarifying split, not a new trigger.
- `--priority`, when given, must equal the cause's fixed priority, or the call is a usage error.
  **[PM]** This stops a caller from silently demoting a high cause, and every designed caller
  (ADR-1605 AC-40, ADR-2100 AD-9) passes `high` for a high cause.
- `test` is reserved for `--test` (REQ-11) and is not accepted as `--cause`.

**REQ-3. The notifier never depends on GitHub or the monitoring stack.** It makes no GitHub API call
and needs no `GH_TOKEN`. ADR-1605 AD-20 says callers never pass `GH_TOKEN`, `GITHUB_TOKEN` or their
enterprise variants. It contacts no monitoring host. It works in a cycle that has not minted a token
(VF-5) and in one whose GitHub filing just failed (ADR-2100 AD-11, channel independence). Building
the issue link (REQ-8) uses only local information. If the repo slug cannot be found locally, the
message carries `#<n>` without a link and is still sent.

**REQ-4. Stable, documented exit codes.** Callers map any non-zero exit to `undelivered`
(ADR-1605 AC-39, AD-20; ADR-2100 AD-11), so these codes are an interface:
- **0**: the push was **sent**, or it was **deduped** (REQ-6). A dedup is not a delivery failure:
  the human was told about this cause and target within the window. Exiting non-zero would make
  ADR-1605 callers record `undelivered` and retry every hour, for nothing.
- **2**: usage error (unknown cause, a malformed or missing argument, a priority mismatch, a bad
  `--since` or `--url`, an unreadable `--body-file`).
- **3**: credentials unavailable (REQ-5).
- **4**: delivery failed (network error, timeout, TLS failure, a non-2xx HTTP status, or a Pushover
  response whose `status` is not 1).
- No other non-zero code is used without amending this list. On every exit, stdout carries exactly
  one machine-readable line naming the outcome (`sent`, `deduped`, `test-sent`, or `failed` with a
  reason token), so a caller can tell `sent` from `deduped` without parsing stderr. The TD fixes the
  line's grammar, and a test pins it.

**REQ-5. Credentials: exactly the human's ruling.**
- File: `~/.config/hos/pushover.env`. It holds `KEY=value` lines for `PUSHOVER_TOKEN` (the Pushover
  application token) and `PUSHOVER_USER` (the human's user key).
- The file is **parsed, never sourced or executed**. Blank lines and `#` comment lines are allowed.
  Any other key, a duplicate key, a line that is not `KEY=value`, or an empty value is rejected
  (exit 3), and the message names the problem but never the value.
- **[PM, security]** The file must be a regular file, owned by the current user, with no group or
  other permission bits set. Otherwise it is rejected (exit 3), with a message giving the
  `chmod 600` remedy. That is the human's "mode 600", made checkable.
- A missing file or missing key gives exit 3 with a clear message. It never fails the caller's cycle
  (REQ-7).
- The values never appear in any log line, stderr, stdout, audit event, exception text, process
  argument list or child environment. **[PM, security]** "Process argument list" matters: a
  `curl -d token=...` would expose the token to every local user through `/proc`. The TD picks a
  transport that passes the credentials on stdin, in a file, or in-process.
- The notifier runs from the unsandboxed `bin/hos-cron` (or unsandboxed callers), so no sandbox
  allowlist changes. The file is added to no sandbox read allowlist.

### 2B. Delivery

**REQ-6. Dedup and rate limit: one push per key per 6 h.**
- **Key [PM].** The issue says "`cause+issue`". Several projects share one machine and one
  `~/.hos`, and issue numbers repeat across repos, so the key also includes the **project**. For
  `--issue none`, the key also includes the **role**, so that a worker and an overseer that both
  fail to mint are two problems, not one. The key is (project, cause, target), plus role when the
  target is `none`. The target is the issue number, the URL or `none`.
- A call whose key was **sent** less than 6 h ago is logged, audited as `deduped`, and not sent
  (exit 0).
- State lives under `~/.hos/notify/`, resolved from `HOS_STATE_DIR` when set, matching
  `bin/hos-cron:253`. The directory is created with mode 0700.
- **Untrusted state counts as no state (ADR-2100 AD-11 rule).** A state dir or entry that is a
  symlink, is not owned by the current user, is not a regular file or directory as expected, or does
  not parse is treated as absent, so the push is **sent**. If the state dir cannot be used at all,
  every call sends and logs a warning. That errs loud, never silent (ADR-1605 AD-18 rule).
- Only a **successful** send records the key. A failed send (exit 3 or 4) records nothing, so the
  next occurrence retries.
- Two concurrent calls with the same key send at most once while state is usable. The TD picks the
  mechanism, for example an exclusive create, and a test pins it.
- State is bounded. Entries older than the window are pruned or ignored, and the state never grows
  without limit.
- The window is a named constant, 6 h. Changing it is a code change.

**REQ-7. The notifier never blocks or fails the caller's cycle.**
- The whole call ends in less than 30 s wall time, including a timed-out HTTP request, so that it
  finishes inside the callers' 30 s bound (ADR-1605 AD-20) and fits ADR-2100 AD-11's per-call
  budget inside its 120 s alert step. **[PM]** The TD sets the HTTP timeout; 20 s is suggested. The
  notifier does not retry inside one call. The next occurrence retries.
- No interactive prompt. No dependency on a TTY, on `$TMPDIR` being writable, or on a writable
  `/tmp` (ADR-2100 AD-11 runs the alert step with a dedicated `TMPDIR`).
- A failure is a non-zero exit with a stderr line, never a hang and never a signal to the caller.
  The caller decides what a non-zero exit means. Every designed caller treats it as `undelivered`
  and carries on.

**REQ-8. Message: one line; the GitHub item holds the detail.**
- Template: `HOS help: <cause> [<project>/<role>] — <target> — waiting since <since>`.
  **[PM]** The issue's template is `HOS help: <cause> — <issue url> — waiting since <t>`. The
  `[<project>/<role>]` part is added because ADR-2100 AD-9 (AM-9) requires the payload to carry
  role and project, and a human with several projects on one machine needs them.
- `<target>` is the issue URL on the project's own repo (`#<n>` if the slug cannot be found
  locally, REQ-3), or the validated `--url`, or the fixed text `no GitHub item; see the cron log for
  this role` for `--issue none`.
- The message carries no file path, no blocker or file name, no host name, no credential, no
  environment value and no free text from GitHub. That is the ADR-2100 AD-9 "fixed-template
  pointer" rule, applied to every cause, not only `tmp-root-refused`. Any caller-supplied text that
  the notifier does transmit (ESC-1) passes through REQ-9 first.
- Priority mapping, matching ADR-1944 A6-4: `high` → Pushover priority **1** (bypasses quiet hours
  once), `normal` → **0**. Emergency (2) is never sent. The mapping is a pair of named constants in
  the notifier, named so they line up with ADR-1944's `hos_pushover_priority_high` and
  `hos_pushover_priority_normal`. If the human's H-9 ruling on #1944 picks different values, both
  places change together.
- The message fits Pushover's limits (1024 characters for the message, 250 for the title). Any
  title is a fixed constant, for example `HOS help`.

**REQ-9. One text mapping for caller-supplied text.** Every caller-supplied value the notifier puts
into the push, other than the validated `--url`, `--issue` and `--since`, goes through one mapping:
- every byte outside a printable-ASCII allowlist is replaced by `?` (the TD fixes the allowlist; it
  must exclude `/`, `~`, `\`, `<`, `>`, `@`, the backtick and every control or non-ASCII byte);
- only the first line is used;
- the result is capped (the TD sets the cap, at most 200 characters), with `...` marking a cut.

This is the same idea as ADR-2100 AD-11's blocker renderer. Callers still own what they send (the
AD-9 pointer rule), and this mapping is a second layer, so that a path or name passed by mistake does
not reach a third party intact.

**REQ-10. Transport.** HTTPS to Pushover's message API, with certificate verification on. The
endpoint is a constant.
- **[PM, security]** A test override of the endpoint (needed for the fake-endpoint tests) may exist
  only together with a test override of the credentials file. While the endpoint is overridden, the
  default credentials file is never read. Real credentials can therefore never be sent anywhere but
  Pushover, even by a caller that sets an `HOS_*` variable (the ADR-1605 AD-20 allowlist passes
  every `HOS_*` name).
- Every environment variable the notifier reads is documented by name in `docs/CRON-SETUP.md`, so
  ADR-1605 callers can add it to their allowlist (AD-20). None of those names contains `TOKEN`,
  `SECRET`, `KEY` or `PASSWORD`, because the AD-20 allowlist strips those, and the notifier must
  work under it.

### 2C. Test mode, audit and documentation

**REQ-11. `notify_human.sh --test`.** It sends one **normal**-priority push with the fixed text
`HOS help: test — notify_human.sh channel check — <now>`. It takes no other argument. It bypasses
dedup, so the human can run it twice. It reads the real credentials file (unless the test overrides
of REQ-10 are set), and it uses the REQ-4 exit codes (`test-sent` on success). It is the human's way
to confirm the channel after provisioning the token. **[PM]** It writes a `human-notified` event with
`outcome=test-sent` when it can locate its clone. It never fails because it cannot.

**REQ-12. Audit: `human-notified`.** Every call that gets past argument parsing writes one
`human-notified` audit event through the existing writer (`scripts/automation/lib/cycle_log.py`),
in the clone the notifier is running from.
- Fields: `cause`, `project`, `role`, `target` (`issue=<n>`, `url`, or `none`), `priority`,
  `outcome=sent|deduped|test-sent|failed`, and for `failed` a reason token
  (`credentials|delivery|timeout|state`, the TD fixes the set).
- **[PM]** The issue asks for `sent` or `deduped`. `failed` is added so that the audit trail shows a
  failed delivery from the notifier's side as well as the caller's `alert-undelivered`.
- Never in the event: a credential, the message text, the body-file content, a path, or a host name.
  The `url` target is recorded as `url` plus the URL, which is a github.com link (REQ-1).
- A failed audit write logs a stderr warning and never changes the exit code. A push that was sent is
  still exit 0.

**REQ-13. Documentation (issue acceptance).** `docs/CRON-SETUP.md` gains a section that covers:
- the human setup step: create a Pushover application, then create `~/.config/hos/pushover.env` with
  `install -m 600 /dev/null ...` and the two keys. The keys are described in prose, never as a
  `NAME=value` example with a value, following the PR #1949 secret-scan lesson that ADR-1944 A6-2
  binds;
- `notify_human.sh --test` and what success looks like;
- the closed cause list, the priorities, the 6 h dedup, and the exit codes;
- every environment variable the notifier reads (REQ-10);
- how to mute the channel: remove or rename the credentials file. Callers then record `undelivered`
  and carry on;
- a troubleshooting row for each exit code.

Provisioning the token is a **human step**, documented, not performed by any slice. The human has
said they will do it when the script lands.

### 2D. Triggers: when callers call, and when they must not

The notifier is GitHub-free (REQ-3), so it cannot see labels or comments. **The "never fires" rules
(issue item 4) are therefore the detectors' job.** Each detector below decides whether to call. The
notifier's own job is dedup and delivery.

**REQ-14. No push for ordinary waits (issue item 4, binding on every detector).** No detector calls
the notifier for:
- an item that is parked (definition: ESC-4);
- an ordinary `needs-human` wait, meaning any `needs-human` item without `priority:critical`;
- an item a human has commented on since its escalation (REQ-17).

**REQ-15. Cron cannot start (S2; `bin/hos-cron`; high).**
- `token-mint-failed`: the auth block at `bin/hos-cron:956-962` failed for K consecutive cycles of
  this role and project (K: ESC-2). `--issue none`, and `--since` is the time of the first failure
  in the run. A successful mint resets the count.
- `cron-lock-stuck`: the lock was reclaimed **by age** (`age ≥ ceiling`, `:321`), or could not be
  acquired after a reclaim (`:324`). It fires on the first occurrence, because reaching the ceiling
  already means at least an hour of standstill. `--issue none`, and `--since` is the lock dir's
  mtime. **[PM]** A reclaim because the holder's PID is dead (`:331-334`) is the routine
  crashed-cycle case and is **not** a trigger.
- `usage-pause-fail-closed`: the usage gate (`:461-485`) returned `decision=pause` with class
  `check_error`, `settings_invalid`, `read_failed` or `reading_unusable` for K consecutive cycles
  (K: ESC-2). `pause/limit`, the designed safe pause that ADR-1944 alerts through Grafana, is
  **not** a trigger (§3). A non-paused cycle resets the count.
- The counters live under `~/.hos` (VF-2 pattern), with the REQ-6 untrusted-state rule. A refusing
  cycle's ADR-2100 exit 77 path is `tmp-root-refused`, raised by ADR-2100 S2, and S2 here must not
  raise a second cause for it.
- The calls run before auth where the condition is before auth, with the AD-20 allowlisted
  environment, under a 30 s bound. Their outcome never changes the cycle's existing exit code or log
  line, apart from appending `alert=<sent|deduped|undelivered:<reason>>`.

**REQ-16. Worker idle (S3; `bin/hos-cron`, worker role; normal).**
- A per-project counter increments on every worker cycle in which the selector ran and reported
  `eligible=0` with at least one unparked in-milestone `needs-ai` issue (`scanned>0`, which already
  excludes `needs-human` and the selector's `EXCLUDED` set). It resets on any cycle with `eligible>0`,
  or with `scanned=0` and `complete=yes` (the selector verified there is no unparked work). Cycles
  that never reach the selector (paused, halted, suspended, skipped before selection) neither
  increment nor reset it.
- **[PM]** `eligible=0` with `complete=no` (the selector's exit 3, "DEGRADED") counts as idle and
  increments the counter **whatever `scanned` reports**, including `scanned=0`. A worker that cannot
  determine its work for N cycles is stalled too (the #1704 class).
- When the counter reaches N (ESC-3), call with `--cause worker-idle --issue none`. `--since` is the
  first idle cycle in the run. Dedup (REQ-6) then limits repeats to one per 6 h while it persists.

**REQ-17. Critical `needs-human` with no human comment for more than 24 h (S3; detector; normal).**
- Scope: open issues and PRs in the project's repo that carry both `needs-human` and
  `priority:critical`, excluding parked items (ESC-4).
- **Escalation time**: the most recent time `needs-human` was applied to the item, read from its
  events.
- **Human comment**: an issue comment, a PR review or a PR review comment, created after the
  escalation time, by an account that is not a bot. Not a bot means its GitHub type is not `Bot`, its
  login does not end in `[bot]`, and it is not in `BOT_ACCOUNTS`
  (`scripts/framework/machine-accounts.env`). The human-proxy identity is in `BOT_ACCOUNTS` and
  therefore never counts as a human (CLAUDE.md, human-approval gate).
- It fires when the escalation time is more than 24 h ago and no human comment exists since then.
  The call is `--cause needs-human-stale --issue <n>`, with `--since` set to the escalation time.
  Dedup then repeats it at most once per 6 h per item until a human comments, the label goes, or the
  item closes. **[PM]** That repeat rate comes from the issue's literal 6 h rule. Up to four
  normal-priority pushes a day per stale critical item is the consequence, and it is disclosed here.
- It runs on the worker role only, after auth, at most once per cycle, with a bounded number of API
  requests (the TD sets the bound). **A read failure means no call for that item** (logged and
  audited). This detector is normal priority and must never push about an item it could not verify,
  because pushing about something the human already answered is the noise REQ-14 forbids.
- **Boundary with #1928.** ADR-1928 AD-5b's reminders (first at 24 h) are the GitHub-side re-ping.
  This trigger is the out-of-band one for the critical subset. If #1928's attention pass is on
  `main` when S3 is designed, the TD reuses its escalation-time and human-comment computation rather
  than writing a second one (D41). Otherwise the S3 PR body records the duplication as a #1928 S-n
  obligation.

**REQ-18. Cross-issue callers (not built in #2125).**
- `tmp-root-refused` is called by ADR-2100 S2 exactly as AD-9 and AD-11 specify: `--issue <n>` or
  `--issue none`, `--priority high`, and a fixed-template pointer. The call is made even when GitHub
  filing failed. ADR-2100's own 12 h state TTL and #2125's 6 h dedup are independent. Both apply,
  and neither changes the other.
- `dependency-advisory` and `environment-broken` are called by ADR-1605 Part 3 as AD-20 and AC-40
  specify, with `--issue <n>` or `--url <run url>`.
- `pipeline-blocked` is called by #2123 when it is built. #2125 declares the cause only.
- Until #2125 S1 lands, all of them resolve the notifier as absent (ADR-1605 AC-39). Nothing in
  #2125 changes those callers' fallbacks.

**REQ-19. Test isolation.** No test reads the real `~/.config/hos/pushover.env`, writes the real
`~/.hos/notify/`, or contacts Pushover. Tests use the REQ-10 overrides and a fake local endpoint. A
test that would reach the real endpoint fails rather than sends. This follows the ADR-2100 AD-10
"tests never write the real registry" approach.

## 3. Out of scope / non-goals

- **The `pipeline-blocked` producer.** That is #2123, blocked by #1605 Part 3. The cause is only
  declared here (REQ-2).
- **The `tmp-root-refused`, `dependency-advisory` and `environment-broken` callers.** Those are
  ADR-2100 S2 and ADR-1605 Part 3.
- **A notification for the designed usage pause (`pause/limit`).** ADR-1944 routes that through
  Grafana (S4, unbuilt). The issue lists only "usage-pause fail-closed", and says "triggers, and only
  these". If the human wants the designed pause pushed too until #1944 S4 lands, that is a new
  trigger and a new ruling.
- **Other "cannot start" exits** that the issue does not list: preflight failure (`:950`), the
  identity guard (`:966-976`), a missing `claude` binary (`:137`), an unavailable halt check
  (`:1037-1050`), and main diverged (`:1527`). They are candidates for a later ruling, not part of
  this build.
- **"Worker blocked by open PRs awaiting human merge"** (`bin/hos-cron:1237`, the #1198 block). It
  is not "`eligible=0`", so REQ-16 does not cover it. #1928 owns the GitHub side of human waits.
- **Grafana consolidation (issue item 7).** When #1944 S4 is designed, its Pushover message shape
  should match REQ-8, and its contact point should use this script as its fallback, if Grafana can
  invoke one. That is an obligation on #1944, not work here. The worker should annotate #1944 with
  it before #1944 S4's design starts. pm-agent does not post that comment (this run's constraints).
- **Emergency priority, Pushover sounds and device targeting.** None are sent (REQ-8).
- **A notifier-side read of `hos-halt` or suspension.** The halt check needs GitHub (REQ-3). Callers
  already apply halt where their designs say so (ADR-2100 AD-11). The human's mute is the
  credentials file (REQ-13).
- **Any sandbox allowlist change** (the human's ruling).

## 4. Acceptance (issue level)

- **AC-1.** With a fake endpoint, each of the nine causes sends exactly once on its first call, with
  its fixed priority, and the message matches REQ-8's template (REQ-2, REQ-8).
- **AC-2.** A repeat of the same key within 6 h is deduped: no request reaches the endpoint, the
  exit is 0, the stdout line says `deduped`, and a `human-notified outcome=deduped` event is written.
  A repeat after 6 h sends (REQ-6).
- **AC-3.** The same cause and issue number in two different projects sends twice. `--issue none`
  from two roles sends twice (REQ-6 key).
- **AC-4.** A missing credentials file, a missing key, an extra key, a group- or world-readable file
  and a symlink-or-foreign-owned file each exit 3 with a clear message, send nothing, and record no
  dedup state. A caller test shows the cycle continuing (REQ-5, REQ-7).
- **AC-5.** A fake endpoint that hangs makes the notifier exit 4 in under 30 s. A non-2xx response
  and a Pushover `status:0` response each exit 4 and record no dedup state. The next call retries
  (REQ-4, REQ-6, REQ-7).
- **AC-6.** An unknown cause, a priority mismatch, a malformed `--since`, a non-github.com `--url`
  and two targets at once each exit 2 (REQ-1, REQ-2).
- **AC-7.** No credential value appears in stdout, stderr, the audit event or any child process's
  argument list during a send (REQ-5). The test checks the argument lists of child processes.
- **AC-8.** With the endpoint overridden and no credentials override, the real default credentials
  path is never opened (REQ-10).
- **AC-9.** A symlinked, foreign-owned or corrupt dedup state is treated as absent, and the push is
  sent. An unusable state dir sends with a warning. Two concurrent same-key calls send once (REQ-6).
- **AC-10.** The notifier works with the ADR-1605 AD-20 allowlisted environment only (`env -i` plus
  the allowlist), with no `GH_TOKEN` and no network route to GitHub (REQ-3, REQ-10).
- **AC-11.** A `--body-file` containing a path, a newline, a backtick and a 10 kB line produces a
  push that passes the REQ-9 mapping (or carries nothing from the file, depending on ESC-1).
- **AC-12.** `notify_human.sh --test` sends one normal-priority push and exits 0 (fake endpoint), and
  is not deduped on a second run (REQ-11).
- **AC-13.** `docs/CRON-SETUP.md` documents the token file, `--test`, the exit codes and the
  environment variables, and contains no `NAME=value` credential example (REQ-13).
- **AC-14 (S2).** In `bin/hos-cron` tests: K consecutive mint failures produce one
  `token-mint-failed` call, and K-1 produce none. An age-based lock reclaim produces one
  `cron-lock-stuck` call, and a dead-PID reclaim produces none. K fail-closed usage pauses produce
  one `usage-pause-fail-closed` call, and `pause/limit` never does. An absent notifier changes no exit
  code (REQ-15).
- **AC-15 (S3).** N idle worker cycles produce one `worker-idle` call. An `eligible>0` cycle resets
  the count. A paused cycle neither increments nor resets it. All-excluded (parked) work produces no
  call (REQ-16). N degraded cycles (`eligible=0 complete=no`, including `scanned=0`) produce one
  call, and a `scanned=0 complete=yes` cycle resets the count.
- **AC-16 (S3).** A critical `needs-human` item 25 h after escalation with no human comment produces
  one `needs-human-stale` call. A comment from the human produces none. A comment from a bot in
  `BOT_ACCOUNTS` (including the human-proxy) does not count as human. A non-critical `needs-human`
  item, a parked item and an item whose events cannot be read produce none (REQ-14, REQ-17).
- **AC-17.** No test reads the real credentials, writes the real state, or contacts Pushover
  (REQ-19).

## 5. Suggested slices (all touch protected surfaces; each at most 15 files)

- **S1. The notifier.** REQ-1 to REQ-13 and REQ-19. Likely files: `bootstrap/notify_human.sh`, a
  helper under `bootstrap/lib/` if the TD wants one, a new test file under `tests/framework/`,
  `docs/CRON-SETUP.md`, `SCRIPTS-INDEX.md`, `scripts/framework/framework_consumer_files.txt` (it ships
  because the shipped `bin/hos-cron` calls it), and the CLAUDE.md canonical-entry-points table. About
  6 to 8 files. **S1 depends on no ESC**, apart from ESC-1, which changes only how `--body-file`
  content is treated. Landing S1 turns ADR-2100 S2's and ADR-1605 Part 3's "absent" path into a live
  channel without any change to them.
- **S2. "Cron cannot start" triggers in `bin/hos-cron`.** REQ-14 and REQ-15. Files: `bin/hos-cron`,
  `tests/automation/test_hos_cron.py` (or a new focused test file), `docs/CRON-SETUP.md`. About 3 to
  5 files. It waits on ESC-2. **Conflict notice:** ADR-2100 S2, ADR-1605 Part 3 and ADR-1928 S6 all
  edit `bin/hos-cron`. Whichever lands later rebases, and its PR body states the conflict.
- **S3. Worker-idle and stale-critical triggers.** REQ-14, REQ-16 and REQ-17. It may split into S3a
  (worker-idle: `bin/hos-cron` and tests) and S3b (the stale-critical detector: a new module, likely
  under `scripts/automation/`, its tests, and its `bin/hos-cron` call site). S3a waits on ESC-3 and
  ESC-4. S3b waits on ESC-4, and should check whether #1928's attention pass has landed (REQ-17).
- **Not in #2125:** the `pipeline-blocked` caller (#2123), the `tmp-root-refused` caller (ADR-2100
  S2), and the `dependency-advisory` and `environment-broken` callers (ADR-1605 Part 3).

Reviewers: `security-reviewer` (credentials, the transport and REQ-10's override rule),
`privacy-reviewer` (third-party payload, REQ-8 and REQ-9), `reliability-reviewer` (REQ-6 and REQ-7)
and `ops-reviewer` (the `human-notified` event) on S1. `reliability-reviewer` on S2 and S3.

## 6. Escalations for the human

- **ESC-1. What does the notifier do with `--body-file` content?** The issue's command shape has
  `--body-file`, and so does ADR-1605 AC-40. The issue also says the message is one line, and that
  the issue holds the detail. ADR-2100 AD-9 needs to send one fixed sentence ("GitHub item could not
  be filed; see the cron log for this role") when filing failed.
  - **(A)** Accept `--body-file` and transmit only its first line, after the REQ-9 mapping and cap,
    appended to the REQ-8 line after ` — `. The push stays one line.
  - **(B)** Accept `--body-file` but never transmit its content. The push is only the REQ-8
    template. The `--issue none` fixed text in REQ-8 already covers ADR-2100's constant.
  - **(C)** Make the body the whole message, with no fixed template.

  **Recommendation: (B).** It is the strictest reading of "one line; the issue holds the detail" and
  of ADR-2100's pointer-only rule. It makes the notifier's payload fully fixed-template, so no
  caller can leak detail to a third party by mistake. ADR-2100's constant is already carried by
  REQ-8's `--issue none` text. (A) is the fallback if you want callers to add a short reason. (C)
  contradicts ADR-2100 AD-9. Under (B), `--body-file` is still accepted, so the AC-40 call shape
  works unchanged. S1 can be designed on (B) and changed to (A) cheaply.

- **ESC-2. Should a single transient failure page you at high priority?** A token mint can fail once
  (a GitHub blip), and the usage gate's `read_failed` can fail once (a late poller). Each of these is
  "a cycle that cannot start". A worker cycle fires every 15 minutes.
  - **(A)** Fire only after K consecutive failing cycles of the same role and project. Suggested
    K = 2, about 30 minutes, for `token-mint-failed` and `usage-pause-fail-closed`.
    `cron-lock-stuck` fires on the first occurrence, because reaching the ceiling already means an
    hour or more of standstill.
  - **(B)** Fire on the first failure. Dedup still limits repeats to one per 6 h.

  **Recommendation: (A) with K = 2.** The channel's value depends on a push meaning something. One
  failed cycle that the next cycle clears is not something you can act on, and it arrives at a
  priority that bypasses quiet hours. K = 2 delays a real outage page by about 15 minutes. K is a
  named constant, so tuning it later is a small PR.

- **ESC-3. N for "worker idle N consecutive cycles".** The issue leaves N open. At a 15-minute worker
  fire:
  - **(A)** N = 8, about 2 hours.
  - **(B)** N = 4, about 1 hour.
  - **(C)** N = 24, about 6 hours.

  **Recommendation: (A), N = 8.** The 2026-10-15 stall lasted 9 days, and the 2026-10-20 wait lasted
  6 hours. Two hours catches both well before they become costly, and it does not fire on a short
  gap between merges. This is normal priority (it does not bypass quiet hours). N is a named
  constant.

- **ESC-4. What is "parked"?** The issue's "never fires for `parked` items" has no mechanical
  definition on `main` (VF-6). No `parked` label exists.
  - **(A)** Parked means excluded by the selector's native rules: the item has an open native
    blocker (a `blocked_by` edge) or is a sub-issue parent. This is the `EXCLUDED` set the selector
    already computes (ADR-1644 AD-C4), so it is consistent with what the worker itself treats as
    not-actionable. Items held for human authorization (`ALL-CANDIDATES-GATED`) count as
    **unparked**, so a worker idle only because everything is gated does push, which tells you an
    authorization is waiting.
  - **(B)** Add a `parked` label. Its meaning, writer and removal are a new label-governance
    decision (`docs/LABELS.md`).
  - **(C)** (A), and also treat gated items as parked, so a gated-only backlog never pushes.

  **Recommendation: (A).** It needs no new label and matches existing selector behaviour, and an
  all-gated backlog is exactly the "the human must act and nobody told them" case that the issue was
  filed for. Under (A), REQ-17's stale-critical detector applies the same native-blocker test to the
  `needs-human` item.

No other product decision is open. The credential location, file format, `--test` flag, unsandboxed
caller, 6 h window, `~/.hos/notify/` location, triggers and priorities are fixed by the issue and
the human's ruling. The three added causes, `--url`, the pointer-only payload and the stable exit
codes are fixed by the merged ADR-2100 and ADR-1605 designs.

## Escalation flag (CORE self-flag)

RISK: MEDIUM for this document (docs only). The feature it specifies is likely **HIGH** once built:
it introduces a new third-party egress path and a new credential on a protected surface, and it adds
calls to `bin/hos-cron`'s pre-auth path. CONFIDENCE: HIGH on §0 (greps and line reads at
`74cb8a5f3`) and on the cross-issue requirements, which were read directly from ADR-2100 AD-9/AD-11,
ADR-1605 AD-18/AD-20 and REQUIREMENTS-1605 AC-39/AC-40. MEDIUM on the **[PM]** extrapolations
(REQ-1's URL constraint, REQ-2's split and priority check, REQ-5's mode check, REQ-6's key, REQ-8's
`[project/role]`, REQ-10's override rule, REQ-12's `failed` outcome, and REQ-16's degraded-counts-as-idle).
Each one is marked, and each is a precision or safety refinement within the issue's stated
behaviour, not a new behaviour. BLAST RADIUS: none from this document. Once built, the blast radius
is `bootstrap/notify_human.sh` (new), `bin/hos-cron` (S2/S3 call sites), `docs/CRON-SETUP.md`, the
consumer file list, and three cross-issue callers' "absent" path becoming live.

## Human Review Required

This specification is structural (a new outbound channel, a credential and new triggers), and you
issued it. ESC-1 to ESC-4 are open. **S1 may proceed to `architect` on ESC-1's recommendation (B)**,
because nothing else in S1 depends on an open question, and a change to (A) is cheap. S2 waits on
ESC-2. S3 waits on ESC-3 and ESC-4. Provisioning `~/.config/hos/pushover.env` and running
`notify_human.sh --test` after S1 merges are human acts, not slices.

## Revisions

- 2026-10-22 (clarifying; second review 2026-10-22 (agy)): REQ-16 and AC-15 now agree. `eligible=0 complete=no` increments the worker-idle counter even when `scanned=0`, and `scanned=0` resets it only when `complete=yes`.
