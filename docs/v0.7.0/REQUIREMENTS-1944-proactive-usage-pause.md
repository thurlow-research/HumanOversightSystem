# REQUIREMENTS-1944 — Proactive Claude usage-threshold pause for worker/overseer cron: read real `/usage` percentages over SSH loopback, pause before the hard limit, fail closed, resume automatically

**Status:** DRAFT for architect. This is the **second attempt** at a requirement ruled on 2026-08-17.
The first attempt (#1446 → PR #1450) followed a hedge in #1446's body ("Recommended v1 scope:
reactive tier only"). It shipped only the reactive backstop and left out the proactive check the
human actually asked for. **The proactive percentage check is the core, non-optional requirement of
this issue (FR-1).** Nothing here defers, softens, or re-scopes a ruled item. Every requirement
traces to a source in §7. Requirements this pass *derived* (implied by a ruling but not stated in
it) are marked **[DERIVED]** and listed for human confirmation in §8.
**Amendment 1 (2026-10-02, same day):** Adds four human rulings from the interactive session. Q1
(poll location) is resolved; `>=` comparison is confirmed; the status-file format is confirmed; the
#1450 reactive breaker is declared obsolete and out of scope. It also records three orchestrator
defaults as **[ASSUMED, pending human confirmation in ADR review]**. These are not rulings
(Q6, Q7, Q10 → AS-1..AS-3). Finally, it adds the #1944 2026-10-02T23:06:30Z addendum to the
Prometheus/Grafana traceability.
**Amendment 2 (2026-10-03, pm-agent):** Applies the two requirements changes requested by ADR-1944
Amendment 1 A1-3 and TD-1944 §9.1 (TD-O-3, TD-O-4). (1) **FR-11** is narrowed so that read success is
decided by output content, not by the `claude` process exit code; transport failures (ssh failure,
spawn failure, timeout) still fail the read regardless of content. (2) **AC-25** is reworded to a
checkable criterion, because the real success output has no `$0.0000` cost footer (TD-VF-8). §7 and
§8 are updated to match (C-6, C-7).
**Amendment 3 (2026-10-03, pm-agent):** Applies the human rulings D1–D19 from the interactive
decision walk-through of 2026-10-03 (cited as "human ruling, interactive session 2026-10-03, D<n>").
Three pause thresholds, including per-model weekly (D1, supersedes AS-1). In-flight behavior
confirmed (D2, AS-2). Fail-open files no issue; visibility is via Grafana alerting (D3, supersedes
AS-3). Invalid-settings rule (D4, resolves Q11). Forced-command `authorized_keys` with no `restrict`
and no environment unsetting (D5). One machine reading file, no per-role/project status files (D6,
resolves Q5). **No GitHub issue filing anywhere** (D7: FR-37/38/39, AC-14, AC-30 retired as
SUPERSEDED). Global, stateless pause separate from `hos-suspend` (D7b, resolves Q16). Single
`pause_condition` gauge (D8). Grafana file provisioning and monitrix sync (D9). Consumers ship
fail-closed (D10). FR-11 narrowing confirmed (D12, closes C-6). `--output-format json`, read
cost/token gauges, AC-25 rewritten, second fixture (D13). ESC-T1 accepted risk (D14). Grafana
alerting with an email + SMS contact point, shipped as a worked example, not a consumer requirement
(D17, D17b). Capped history log, export/backfill, and `last-raw`, recorded as a **clarification** of
"no ever-growing logs" (D18). No hardcoded thresholds (D19). New FR-51–FR-67 and AC-31–AC-52. §0,
§3, §5–§8 and the Human Review section are updated to match.
**Amendment 4 (2026-10-03, pm-agent):** Applies ADR-1944 Amendment 4 A4-9, the requirements side of
human rulings H-1, H-2, H-3, H-4 and H-7 (cited as "human ruling, interactive session 2026-10-03,
H-n"). H-1: each fail-open cycle without a usable reading writes one `cycle-usage-unchecked` audit
event, and the release notes, upgrade checklist and runbook carry a fixed warning sentence (FR-22,
FR-65, AC-9, AC-46). H-2: `contrib/monitoring/**` is **not** protected surface; a PR-required
required-alert test is the guard instead (new FR-68, AC-47, FR-62). H-3: alerting changes are
applied on monitrix by a root systemd path unit (FR-58, FR-62). H-4: AC-44 procedure confirmed
(AC-44). H-7: new AC-53, the S1 trip test, gates S2. Also rewords AC-40 (TD-O-16) and AC-35
(TD-O-22). §7, §8 and the Human Review section are updated to match.
**Date:** 2026-10-02 (Amendments 2, 3 and 4: 2026-10-03)
**Author:** pm-agent
**Source issues:** #1944 (open, `priority:critical`, v0.6.1. Its body is authoritative, and its
2026-10-02 "Design decisions ruled today" section governs wherever it conflicts with older material,
**except where the 2026-10-03 human rulings supersede it**);
#1446 (closed; comments 2026-08-17T05:17:05Z, 05:25:22Z, 07:47:00Z); PR #1450 (merged; comments
2026-08-17T07:46:46Z through 2026-08-18T04:20:43Z, including ScottThurlow's 08:08:39Z rejection);
human directive, interactive session 2026-10-02 (Prometheus and Grafana scope); human ruling,
interactive session 2026-10-02 (Amendment 1: poll location, `>=`, status-file format, reactive
breaker obsolete); #1944 addendum comment 2026-10-02T23:06:30Z (dashboard/exporter data shape,
relayed by the orchestrating session; this pass did not re-read it); **human rulings, interactive
session 2026-10-03, D1–D19** (Amendment 3); real `/usage` capture 2 (faberix, 2026-10-03,
`--output-format json`, jq-filtered to `{result, total_cost_usd, usage}`).
**Target:** pm-agent (this document) → `architect` → `technical-design` → implementation, run through
human-driven interactive worker sessions (#1944 "Process note"), with the overseer reviewing the PR(s).
**Consumers:** `architect` (next), then `technical-design`, `unit-test`, `system-test`.
**Scope note:** This document covers WHAT and WHY only. Where it gives a concrete value, that value is
a ruled default and must be configurable. It is not an implementation instruction. Mechanism, file
layout, and placement belong to `architect` (§6), except where a 2026-10-03 ruling fixes them (named
paths, gauge names, the `authorized_keys` line, the `contrib/monitoring/` location).

---

## 0. Verification findings: where the rulings meet the repo

All checks were made against the working tree on branch `interactive-1944-proactive-usage-pause-design`
(HEAD `9f6a4f05f`). Line numbers refer to that commit.

**Verification gaps.** (a) This session runs in a PID-namespaced sandbox, so it could not see a
running `node_exporter` or its textfile-collector directory. Q4 remains open. (b) Nothing was
run against the live cron, SSH loopback, or `claude`. (c) ~~No real `/usage` sample showing the
local-sessions breakdown section exists in any source (D-1).~~ *Amendment 3:* closed by real capture
2 (D13). That capture is jq-filtered, so the full JSON envelope is still unseen (D-4).

**VF-1: CONFLICTS WITH THE ISSUE'S PREMISE. The reactive backstop #1944 says to "keep as-is" is
currently disabled.** `bin/hos-cron:2090-2155`. The #1446 usage-limit breaker block has been
**commented out since 2026-09-01 at operator request**. The in-file reason is false positives: it
greps the session's *own* transcript, trips on the first match, and needs a manual
`hos-suspend --clear`, so *"documenting the breaker can trip the breaker."* Only its auto-close
half (`:2181-2202`) is still live. **Consequence:** right now no usage protection of any kind is
active on this host. **Resolved by Amendment 1:** the human ruled the #1450 reactive breaker
design **obsolete and out of scope** for #1944 (human ruling, interactive session 2026-10-02). The
proactive check *is* the protection. #1944 does not re-enable it, rely on it, or depend on it as a
backstop (FR-40, C-1).

**VF-2: The 09-01 false-positive lesson applies directly.** Any pause signal taken from free text
that an agent session might also print will trip on that text. The proactive check must read only
its own `/usage` invocation's output (FR-28).

**VF-3: `hos-suspend` is per-project, role-blind, date-granular, and has no owner field.**
`bin/hos-suspend:122-137` writes `{suspended_at, reason?, until?}` to `~/.hos/suspend/<project>`.
`--until` takes only `YYYY-MM-DD`. `bin/hos-cron:263-283` checks the marker **before** any role work
and exits 0. Two consequences. (i) If the proactive pause reuses this marker and the poll runs
inside `hos-cron` after this check, the poll never runs while paused and auto-resume is impossible
(a deadlock; FR-24). *Amendment 1:* the standalone poller (FR-50) is not gated by `hos-suspend`,
so the poll itself cannot deadlock. (ii) The marker has no field recording *who* set it, so an
automatic resume that clears it could also wipe a human's or the timeout breaker's suspension
(FR-25). *Amendment 3:* **resolved by D7b.** The pause is a new stateless mechanism that never
writes or clears suspend markers (FR-51), so neither consequence can arise.

**VF-4: The suggested settings location is a repo-committed, per-repo file, and `hos-cron` does not
read it.** #1944 suggests `scripts/framework/machine-accounts.env` "e.g.". That file is committed
in each consumer repo, and `bin/hos-cron` never sources it. The machine-level config directory
`bin/hos-cron` actually reads is `~/.config/hos/` (`projects.conf` at `:172`, `claude-auth.env` at
`:877`). #1944 asks for the location to be confirmed, not assumed (Q3). *Amendment 3:* the rulings
name the settings file `usage-pause.conf` (D4, D19). They do not name its directory.

**VF-5: The `#728` auth runbook is `docs/CRON-SETUP.md` §2, not `docs/MACHINE-ACCOUNTS-SETUP.md`.**
The `claude setup-token` / `claude-auth.env` steps are at `docs/CRON-SETUP.md:47-67`.
`MACHINE-ACCOUNTS-SETUP.md` covers GitHub App identity. #1944 Q2 says "likely" the latter. That is
input to Q2.

**VF-6: A literal `claude -p "/usage"` in `bin/`, `scripts/`, or `bootstrap/` fails an existing
enforced test.** `tests/framework/test_agent_invocation_migration.py:98-132` (T4.1, ADR-1643 AD-16)
asserts that the only raw `claude -p` / `claude --print` call sites are three named exemptions.
`/usage` is not an agent invocation and makes no model call. The ruled mechanism and the AD-16
single-invocation-site rule need reconciling (Q8). The Haiku fallback *is* a model invocation and
falls squarely under AD-16.

**VF-7: `write_status()` is plain truncate-and-write plus an ERR trap.**
`~/.local/bin/sync_human_clone.sh:120-133` (the operator's sync_human_clone.sh) writes `last_run`, `outcome`, `head`, and
`detail` with `>`, and installs `trap 'write_status crashed …' ERR` so an unexpected exit still
leaves a record. That is the pattern to mirror for the reading file (FR-31). A truncating write is
not atomic, so a reader can catch a half-written file. FR-36 requires such a file to be treated as
unreadable.

**VF-8 (historical; Amendment 3): The issue-filing pattern.** The live timeout breaker
(`bin/hos-cron:2056-2080`) and the disabled usage breaker (`:2132-2154`) share one pattern: one
`needs-human,needs-ai` issue under a stable title prefix, fail-closed dedup, auto-close on recovery.
~~That is the pattern to reuse (FR-37).~~ *Amendment 3:* #1944 files **no issues** (D7), so this
pattern is not reused. The 20-issue dedup bug in it (including the collapsed `_audit` at
`hos-cron:2054`) is filed separately as #1946.

**VF-9 (Amendment 3, host facts relayed with the 2026-10-03 rulings; not re-verified here):**
(a) Alerting is **not** set up on monitrix today: no Alertmanager and no sms-pager is running. So
fail-open is not safe on this host yet (FR-67), and the delivery ACs (AC-43, AC-44) need new setup.
(b) Prometheus retention on monitrix is verified at 90d / 12 GiB. (c) The HOS repo is public, and
monitrix needs no deploy key (D9). (d) A leftover crontab entry runs
`/tmp/diagnose_claude_usage_tty.sh` and appends forever to `/tmp/claude_usage_diag.log`. It is
**not part of this design**, and the human removes it. It would violate FR-34 if it were.

---

## 1. Context

Usage credits are enabled on this account. When a hard plan limit is reached, Anthropic does not
refuse. It keeps serving and bills real dollars (PR #1450, 2026-08-17T08:16:12Z). A breaker that
waits for a refusal may therefore **never fire** while spend runs past the included quota. Only a
proactive percentage check catches this, and only a proactive check keeps headroom for interactive
work, which was always the goal (PR #1450, 07:46:46Z).

The work stalled for seven weeks because `claude -p "/usage"` under the cron credential
(`CLAUDE_CODE_OAUTH_TOKEN` from `claude-auth.env`) returns a silent empty session. **That question is
closed** (#1944 "What's new today"). Running `claude -p "/usage"` over SSH loopback to self, without
sourcing `claude-auth.env`, uses the existing on-disk personal-login credential and returns real data.
This held under real unattended cron, even when SSH could not allocate a pty. The deciding variable
is the credential, never TTY or pty. The read costs $0 and makes no model call.

---

## 2. Functional requirements

### A. The proactive read (core)

- **FR-1: The proactive percentage check is mandatory and is the primary deliverable.** A delivery
  that ships only reactive or hard-limit detection, or that ships the proactive check disabled by
  default or behind a flag left off, does **not** satisfy this issue. If an unforeseen blocker
  prevents the proactive read, the build stops and escalates to `needs-human`, naming the blocker.
  It must not ship a lesser version (PR #1450, 07:46:46Z: *"Do not silently fall back to
  reactive-only again"*). (This is a build-process escalation. It is not runtime issue filing, which
  D7 removes.)
- **FR-2 [A3: D13]:** Usage is read by running `claude -p /usage --output-format json`. The
  threshold decision parses the **text in the JSON envelope's `result` field**. No other data source
  is used for the threshold decision. The direct `GET /api/oauth/usage` endpoint is explicitly
  non-viable (#1446, 05:17:05Z). Parsing must not depend on any envelope field not yet seen in a real
  capture. The fields seen so far are `result`, `total_cost_usd`, and `usage` (capture 2). A missing
  or unparseable envelope, or a missing `result`, is a FAILED read (FR-11).
  *Was:* ~~parsing the plain-text output~~ (superseded by D13).
- **FR-3 [A3: D5]:** The read runs over SSH loopback to the same user on the same host, using a
  dedicated keypair (`~/.ssh/hos_loopback`, no passphrase). Its `authorized_keys` entry is exactly
  `from="127.0.0.1,::1",command="<abs path to claude> -p /usage --output-format json"`
  (the faberix entry; the `claude` path is host-specific). The `command=` value must be an absolute
  path on the host (faberix's is the operator's `~/.local/bin/claude`), generated by
  `hos-usage-poll remote-cmd`, never hardcoded in HOS. It carries **no `restrict` option**. The
  remote command runs **without** sourcing `claude-auth.env`, so the existing personal-login
  credential is used. Swapping this line in place of an earlier entry is **not final until a real
  `--check` read returns real percentages** (AC-48).
- **FR-4 [A3: D5]:** The read path must not extract, copy, duplicate, re-store, or pass on any
  credential (#1359 least-privilege; #1944: *"does not extract, duplicate, or store a second copy of
  anything"*). The `claude` process doing the read runs in the **plain login environment** that the
  forced command gets. That environment never sources `claude-auth.env`. The read path does **not
  unset environment variables anywhere** (no `env -u` or equivalent), on the client or the server
  side. The ssh invocation does not forward the caller's credential variables.
  *Was:* ~~`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_AUTH_TOKEN` must not be set
  in the environment of the `claude` process doing the read, even if the caller has them
  exported.~~ The goal stands. D5 forbids unsetting as the means: the human called that path
  "notoriously fragile".
- **FR-5:** The read must not depend on a TTY or pty. It must succeed when SSH reports
  `Pseudo-terminal will not be allocated` (#1944 table, last row). The design must not add pty
  workarounds. They have been tested and do not matter.
- **FR-6:** The read must not depend on cron's minimal `PATH`. An earlier ad hoc crontab attempt
  failed with `claude: command not found` (#1446, 05:17:05Z).
- **FR-7:** The read must have a time bound. A timeout counts as a failed read (FR-21). The timeout
  value is open (Q9).
- **FR-8:** Poll interval is configurable, default **5 minutes** (#1944 10-02).
- **FR-9:** The primary read path makes no model call and adds no token cost. Verified per read by
  FR-56 and AC-25.

### B. Parsing and classification

- **FR-10:** Parsing reuses `usage-parse.sh` (#1446, 05:17:05Z), with grep-based parsing of the
  `result` text as the primary path. The reference script is a verified starting point, not reviewed
  production code. It must still go through normal review.
- **FR-11: A read counts as SUCCESSFUL only if it yields a numeric current-session percentage and a
  numeric all-models current-week percentage.** **[Amendment 2 — architect ruling A1-3; CONFIRMED,
  human ruling, interactive session 2026-10-03, D12]** Success is decided by the read's output
  **content**: both values parsed. It is **not** decided by the `claude` process exit code. A
  non-zero remote exit with both values present is a SUCCESSFUL read, and the exit code is recorded
  (FR-13). A read is **FAILED** if either value is missing or non-numeric, or the output is empty or
  garbled. It is also **FAILED, regardless of content**, on any transport failure: an SSH failure, a
  failure to spawn the read, or a timeout (FR-7). This is the reference parser's own success
  condition (`[[ -n "$session_pct" && -n "$weekly_all_pct" ]]`), which is content-only. A missing
  per-model line is **not** a failure (FR-16).
  *Original text (superseded, confirmed by D12; retained for history):*
  ~~Every other result is a **FAILED read**: missing either value, non-numeric, SSH failure,
  non-zero exit, timeout, or garbled output.~~
- **FR-12 [A3: D13]: The silent-empty-session shape is a FAILED read and must never be read as 0%
  usage.** That shape is a response with no `% used` lines. In plain text it appeared as
  `Total cost: $0.0000 … Usage: 0 input, 0 output, 0 cache read, 0 cache write` (PR #1450,
  07:48:32Z, Test 1). Under `--output-format json` it is a `result` with no `% used` lines.
  **A cost of 0 and token counts of 0 do not prove success.** The empty-session failure also costs 0
  (D13). Success is decided only by FR-11. This is the #1362 / #1369 "silently reports clean" failure
  class. Reading it as 0% would turn a broken check into "all clear", the worst possible outcome
  under credits billing.
- **FR-13:** Success is decided from the parsed content, never from the process exit code. The
  empty-session shape came back with no error text.
- **FR-14: The Haiku fallback must not be trusted until it has been verified end to end outside the
  #1370 nested-`claude` sandbox restriction.** It has never run successfully (#1446, 05:17:05Z;
  #1944 Reference). Until a verification record exists (AC-21), a grep miss is a FAILED read, and the
  fallback must not feed the threshold decision. Once verified, its output remains distinguishable
  (FR-15). Note: the fallback is a model call that spends the quota it measures and falls under
  AD-16 (VF-6, Q8, Q18).
- **FR-15:** Every successful reading records how it was parsed (`parsed_via`: grep or fallback).
- **FR-16 [A3: D1]:** Per-model weekly values (every `Current week (<model>)` line present, e.g.
  `Current week (Fable)`) are captured when present and recorded as absent when not present. They
  **feed the pause decision** (FR-19). A missing per-model line is **not** a read failure. Only the
  session and all-models lines are required (FR-11).
  *Was:* ~~**[ASSUMED]** (AS-1): they are exported as gauges only and do **not** feed the pause
  decision.~~ (superseded by D1).
- **FR-17 [A3: D13]: Local-session breakdown fields** ("Approximate, based on local sessions on this
  machine") are parsed when present (human directive, interactive session 2026-10-02). Capture 2
  shows the shape: one block per rolling window (`Last 24h`, `Last 7d`), each with
  subagent-heavy %, >150k-context %, 8h+-session %, and a "Top subagents" list. The figures are
  **rolling windows computed by Claude Code**, so they are exported as reported and not windowed or
  re-aggregated by HOS (FR-43). **Every breakdown line is individually optional.** Capture 2's
  `Last 7d` block has no 8h+-session line, while its `Last 24h` block does. A missing line is an
  **absent series, never 0** (FR-44). **These fields never affect the pause decision.** A missing,
  unparseable, or format-changed breakdown field must not turn a successful read into a failed one.

### C. The pause decision

- **FR-18 [A3: D1]:** Thresholds are configurable. There are **three**, each default **90%**:
  current session, weekly (all models), and weekly per-model. The per-model threshold applies to
  every `Current week (<model>)` line present. These defaults **supersede** the 85%/90% in the
  2026-08-17 final ruling (PR #1450 08:05:21Z and ScottThurlow 08:08:39Z). They also supersede the
  90%/95% in the 07:46:46Z and 07:47:00Z correction comments (#1944 10-02).
- **FR-19 [A3: D1]:** Pause if **any** of the three limits is `>=` its own threshold:
  `session_pct >= session_threshold`, **OR** `weekly_all_pct >= weekly_threshold`, **OR**, for any
  per-model line present, `weekly_model_pct >= weekly_model_threshold`. The comparison is **`>=`**,
  not `>`. Reaching the threshold pauses (human ruling, interactive session 2026-10-02, which
  confirms ScottThurlow 08:08:39Z *"either threshold"* and 07:46:46Z *"Suspend at 90%"*). The pause
  reason **names the limit**, for example `weekly_model:Fable 91% >= 90` (D1).
  *Was:* ~~two conditions (session OR weekly-all)~~ (extended by D1).
- **FR-20:** "Session window" means whatever window `/usage` reports as `Current session`. Its
  length (variously called 2h or 5h in the sources) must not be hard-coded or assumed.
- **FR-21:** Fail mode is configurable, default **fail-closed**. Under fail-closed, each of the
  following is treated exactly as "confirmed over threshold": a FAILED read (FR-11/12), or a missing,
  stale, or unreadable reading file at the consumer (FR-36). (#1944 10-02 affirms 08-17: *"can't
  confirm under threshold" treated the same as "confirmed over threshold."*) If the default
  misfires, the operator response is to flip the setting, not change the default. Invalid settings
  pause **regardless of fail mode** (FR-30).
- **FR-22 [A3: D3]:** Under fail-open, a failed read does not cause a pause. Cycles keep going and
  **no issue is filed**. The failure is still recorded in the reading file and in the health gauges,
  so a broken check is never invisible (#1446 05:25:22Z: *"the check is broken" is
  distinguishable*). The human is alerted by monitoring: Grafana alerting on the "reading failed"
  and "reading stale / poller dead" alerts (FR-62). Fail-open is only safe once alerting is live
  (FR-67).
  **[A4: H-1]** Each fail-open cycle that runs without a usable successful reading writes one
  `cycle-usage-unchecked` audit event (fields: role, project, cycle_id, reason, session_pct,
  weekly_all_pct, reading_age_s, fail_mode, settings; one `key=value` per argument). No block and no
  issue.
  *Was:* ~~**[ASSUMED]** (AS-3): after N consecutive failed polls in fail-open mode (N configurable),
  one deduped `needs-human` issue is filed.~~ (superseded by D3, D7).
- **FR-23 [A3: D1]: Auto-resume.** When a later successful read shows **all three** limits strictly
  below their thresholds (`<`, the complement of FR-19), cron work resumes with no human action
  (08:05:21Z; #1944). ScottThurlow's 08:08:39Z wording, *"pause until the offending window resets"*,
  is **recorded alongside and has the same effect**. Usage within a window only rises, so a reading
  drops below threshold only when the offending window resets. The rule for implementation is the
  read-driven one: resume on the first successful under-threshold read. The two wordings only differ
  when the operator changes a threshold mid-window. In that case the read-driven rule applies the
  new threshold at the next read. This is a clarifying reconciliation, recorded in §8.
- **FR-24 [DERIVED]: The pause must not stop the poll.** The poll keeps running and writing the
  reading file while cron work is paused. Otherwise FR-23 can never happen (VF-3 deadlock).
  *Amendment 1:* the standalone poller (FR-50) satisfies this structurally. The requirement stays as
  a constraint the design must not regress, for example by making the poller check a suspend marker.
- **FR-25 [A3: D7b]: The pause never touches `hos-suspend`.** Auto-resume must never clear a human
  `hos-suspend`, a timeout-breaker suspension, or a reactive-breaker suspension. D7b makes this
  structural: the pause mechanism **never writes or clears suspend markers** (FR-51). A
  `hos-suspend` marker keeps suspending its project whatever the reading says.
- **FR-26 [A3: D2, D6, D7b]:** The check gates **every worker and overseer cron cycle, in every
  project on the host, before any Claude session starts** in that cycle (#1944 title and Goal: pause
  *before* the hard limit). `bin/hos-cron` does this with a **cycle-start check that reads the
  machine reading file** (FR-31) and decides whether to skip the cycle (human ruling, interactive
  session 2026-10-02). It does not call `/usage` itself, and it **writes nothing** to the reading
  file (D6). **In-flight (CONFIRMED, D2):** the gate runs at cycle start only. A cycle already
  running finishes; the next cycle pauses. There is no mid-cycle kill.
  *Was:* ~~**[ASSUMED]** (AS-2) … bounded by `HOS_CRON_MAX_SECONDS`~~. D2 confirms AS-2 and does not
  restate the bound. This feature adds no bound of its own.
- **FR-27 [A3: D7b]:** The settings, the quota reading, and **the pause** are machine-level. The
  pause is **global**: every HOS project's worker **and** overseer on the host follows the same
  thresholds and the same reading (#1944 10-02: *"the underlying subscription quota is shared across
  whatever projects run on this box"*). Interactive sessions are never paused.
- **FR-28:** Pause state comes only from the dedicated `/usage` read. It is never inferred from a
  worker or overseer session transcript (VF-1/VF-2, `bin/hos-cron:2093-2100`).

### D. Settings

- **FR-29 [A3: D1, D4, D18, D19]:** All of these are configurable in the machine-level settings file
  `usage-pause.conf` and are never hard-coded: the three thresholds (FR-18), fail mode, poll
  interval, staleness window, `history_days` (default 90), and `history_max_mb` (default 100)
  (FR-52). The directory is confirmed by the architect (Q3; see VF-4). The location is
  **machine-level**. This supersedes 08:08:39Z's "project config" (#1944 10-02).
- **FR-30 [A3: D4]: Invalid settings.** A **missing** `usage-pause.conf` means the defaults apply.
  An **unreadable** file, an **invalid value**, an **unknown key**, or a **duplicate key**
  **pauses, regardless of fail mode**. Thresholds must be integers 1–100. Q11's examples count as
  invalid values: a non-numeric value, an unknown fail mode, and a staleness window ≤ the poll
  interval. The `hos-cron` log line and the reading file **name the bad key**. A
  `settings_valid` gauge is exported as 0. No issue is filed (D7). Invalid settings never quietly
  disable or loosen the check.
  *Was:* ~~[DERIVED] … What happens instead is open (Q11).~~ (ruled by D4).

### E. Reading file

- **FR-31 [A3: D6]:** There is **exactly one** machine reading file, `~/.hos/usage-pause/reading`.
  It is written **only by the poller** cron job and overwritten **in full** on every poll, failures
  included. This mirrors `sync_human_clone.sh` `write_status()` (#1276, VF-7), including the
  crash-still-writes behavior. `hos-cron` checks only **read** it and write nothing there. There are
  **no per-role or per-project status files**. Rationale (D6): fewer points of failure, and the
  per-cycle decisions are already in the `hos-cron` log and the audit events.
  *Was:* ~~One fixed-path status file **per role/project** (as ruled in #1446 05:25:22Z and #1944
  10-02, reconfirmed in Amendment 1)~~ (superseded by D6). The "last log entry" note from
  Amendment 1 still holds: the reading is the whole overwrite-in-place file.
- **FR-32:** A poll that cannot produce a usable reading still overwrites the reading file with that
  failure state and a reason. So "the check is broken" (failure record), "the check hasn't run since
  boot" (no file), and "the check is healthy" (success record) are all distinguishable.
- **FR-33 [A3: D1, D4, D13]:** The reading file contains at least: the run timestamp, outcome
  (success or failure plus a reason), session %, all-models weekly %, each per-model weekly % present,
  `parsed_via`, the read's `total_cost_usd` and token counts (FR-56), settings validity and any bad
  key (FR-30), and the resulting pause decision with its reason. The reason names the limit
  (`weekly_model:Fable 91% >= 90`), or the failure, or invalid settings. The reset text `/usage`
  reports may be included as-is (open: Q13).
- **FR-34 [A3: D18 — CLARIFICATION]:** **"No ever-growing logs" stands** (#1446 05:25:22Z;
  ScottThurlow 08:08:39Z *"we don't have ever growing log files"*). Nothing in this feature writes an
  **unbounded** file. That excludes a crontab `>>` redirect for the poller and per-poll records in
  `audit/log/`. The **only** per-poll history is the **capped** history log of FR-52, which D18
  makes **required**. Whether a single audit event on pause or resume is allowed is left to the
  architect (Q17). Per-poll audit events are not allowed.
  *Was:* ~~Nothing in this feature appends to a growing file, rotates files, or keeps per-poll
  history.~~ D18 clarifies that capped, rotated history is consistent with the principle. It
  supersedes the #1944 10-02 wording "Supersedes any append/CSV + size-based rotation approach".
- **FR-35 [A3: D18]:** The gate reads only the current reading file. The history log (FR-52) is a
  recovery path for monitoring data and never feeds a pause decision.
- **FR-36:** **Consumer contract.** A worker or overseer cycle reads the reading file. If its
  timestamp is within the **staleness window**, the cycle applies the threshold and fail-mode settings
  to that reading. If the file is stale, missing, truncated, or unparseable, the cycle applies the
  fail mode. The staleness window is configurable and must be **wider than the poll interval**.
  Default **15 minutes**, the issue's worked example, which allows two missed 5-minute polls (#1944
  10-02).

### F. Visibility (Amendment 3: issue filing removed)

- ~~**FR-37:** A proactive pause files a `needs-human` issue, reusing #1450's pattern (VF-8): a
  stable title prefix distinct from the reactive and timeout breakers, fail-closed dedup, and at most
  one open issue per pause episode, never one per poll. A failed issue filing does not prevent the
  pause.~~ **SUPERSEDED** (human ruling, interactive session 2026-10-03, D7): the gate files no
  issues of any kind. Visibility is via alerting (FR-60–FR-62). This supersedes the #1944 10-02
  ruling "Visibility on trip: reuse #1450's needs-human issue-filing pattern".
- ~~**FR-38:** On auto-resume, the open proactive-pause issue is auto-closed with a comment.~~
  **SUPERSEDED** (D7): no issue exists to close.
- ~~**FR-39:** The issue says why the pause happened: which window's reading was `>=` which
  threshold, and the reading, or that the check failed or went stale (with the failure reason) under
  fail-closed.~~ **SUPERSEDED** (D7): the "why" now lives in the pause reason in the reading file
  and the `hos-cron` log (FR-19, FR-33).
- **FR-57 (new, D7):** The poller and the gate make **no GitHub calls**: no issue filing, no dedup
  query, no auto-close, and no comments, labels, or `needs-human` in any case (pause, fail-closed,
  fail-open, degraded, invalid settings). (TD-O-2 is moot.)

### G. Reactive breaker (obsolete, out of scope; Amendment 1)

- **FR-40:** The #1450 reactive breaker design (commented out at `bin/hos-cron:2090` since
  2026-09-01) is **obsolete and out of scope** for #1944 (human ruling, interactive session
  2026-10-02; this supersedes 08:08:39Z *"If hard limit hit, pause too"* and #1944's "keep as
  backstop"). #1944 does not re-enable it, rely on it, or depend on it as a backstop. **The
  proactive check is the protection.** #1944 makes no change to that code, commented or live.
  Whether to delete it is not this issue's concern.

### H. Prometheus export (human directive, interactive session 2026-10-02)

- **FR-41:** Each poll also writes a Prometheus textfile-collector `.prom` file into the host's
  **existing** `node_exporter` textfile-collector directory. No new listening service, port, or
  exposure surface (#1944 10-02 Dashboarding). The mechanism and directory need confirming (Q4).
- **FR-42 [A3: D1, D4, D8, D13, D18, D19]:** Gauges. **Raw values:** current-session %; all-models
  weekly %; per-model weekly % (one series per model present); and per breakdown window (e.g. 24h,
  7d), each breakdown line present: subagent-heavy %, >150k-context %, 8h+-session %, and top-subagent
  %. **Read cost:** `hos_claude_usage_read_cost_usd` and `hos_claude_usage_read_tokens` (FR-56).
  **Configuration in use:** `hos_claude_usage_threshold_percent{limit=...}` for each of the three
  thresholds (FR-64), and `settings_valid` (FR-30). **Health:** `last_success_timestamp_seconds`,
  parse status, `history_write_ok` (FR-54), and **one** machine-level
  `hos_claude_usage_pause_condition`. That gauge is 1 when any limit is `>=` its threshold **or**
  fail-closed applies, and 0 otherwise. The pause alert fires on it (D8).
- **FR-43:** **Raw current values only.** No deltas, rates, cumulative transforms, or forecasts are
  computed in the exporter or the reading file. Those belong in PromQL/Grafana at query time.
- **FR-44 [A3: D8]:** A value the poll did not obtain is an **absent series, never 0**. This covers
  any breakdown line, any per-model weekly value, and session/weekly on a failed read. Health gauges
  are always emitted. Writing 0 for an unknown value would repeat the FR-12 "silently clean" failure
  on the dashboard. **The one deliberate exception (D8):** `last_success_timestamp_seconds` is **0**
  when no success is on record.
- **FR-45:** The `.prom` file is replaced in full on every run, and Prometheus must never scrape a
  half-written file (mechanism: Q4). Its write is best-effort and comes after the reading file
  (FR-54).

### I. Grafana dashboard (human directive, interactive session 2026-10-02)

- **FR-46 [A3: D8, D9, D19]:** Deliverable: a Grafana dashboard JSON, provisioned from files
  (FR-58), with:
  (1) session %, weekly-all %, and per-model weekly % sawtooth over time, with threshold lines taken
  from the `hos_claude_usage_threshold_percent` gauges, **never a literal 90** (FR-64), and pause
  events annotated from `hos_claude_usage_pause_condition`;
  (2) a `predict_linear`-based early-warning panel;
  (3) subagent attribution over time;
  (4) >150k-context % and 8h+-session % over time, for comparison against the sawtooth.
  All derived views are computed in PromQL (FR-43).

### J. Host setup

- **FR-47:** The SSH-loopback setup (keypair plus the forced-command `authorized_keys` entry, FR-3)
  is a documented one-time host-local manual step, like `#728`'s `claude setup-token`. It is **not**
  provisioned by `hos_install.sh` (#1944 Q2; runbook location Q14 / VF-5).
- **FR-48 [A3: D5, D13]:** An idempotent preflight check (the poller's `--check`) confirms the key
  exists and a loopback `/usage` read actually returns a SUCCESSFUL read (FR-11), rather than
  assuming setup was done. If the check fails, it says so plainly. The failure surfaces as a failed
  read, so fail mode applies, and is never silent. The **first** `--check` on a real host captures
  the **full, unfiltered JSON envelope** as a test fixture (D-4).

### K. Governance

- **FR-49:** Changes to `bin/hos-cron` (and anything else under `bin/**`) are protected surface and
  need human merge approval (CODEOWNERS). This is expected and not a blocker (#1944 Process note).
- **FR-68 (new, A4: H-2):** `contrib/monitoring/**` is not protected surface. Removing or weakening
  a required alert is guarded by the required-alert test (AC-47), and is visible to normal PR risk
  review. #1944 adds no entry of any kind to the protected-surface list. Human rationale (recorded):
  protected surfaces are already too broad (#1935), and human review must be restricted to what
  really matters.

### L. Poll placement and pause mechanism (Amendment 1; Amendment 3)

- **FR-50 [A3: D6, D18]:** The poll is a **separate, standalone cron job** that runs at the poll
  interval (default every 5 minutes, FR-8). It reads usage over SSH loopback (FR-3) and writes the
  reading file (FR-31), the `.prom` file (FR-41), the history line (FR-52), and `last-raw` (FR-55).
  It is **not** inside `bin/hos-cron` and is not gated by `hos-suspend` (human ruling, interactive
  session 2026-10-02). `bin/hos-cron` only reads the reading file (FR-26, FR-36). The standalone job
  must still meet FR-6 (no cron-`PATH` dependence) and FR-34 (its crontab entry must not add an
  unbounded log).
- **FR-51 (new, D7b): Global, stateless pause, separate from `hos-suspend`.** The pause is a
  **new** mechanism. It is **stateless**: each cycle start decides from the current reading file and
  settings, and the pause holds no state of its own. It never writes or clears `hos-suspend` markers.
  It applies to **all projects and all roles** (worker and overseer) on the machine. It takes effect
  only where the `hos-cron` copy that actually runs includes the gate. So the runbook must check
  **every scheduled `hos-cron` copy** on the host. Interactive sessions are never paused.

### M. Orchestrator-assumed defaults (Amendment 3: all three now ruled)

- ~~**AS-1 (Q6):** Only the current-session and all-models weekly windows trigger a pause. Per-model
  weekly values (e.g. Fable) are exported as gauges only.~~ **SUPERSEDED** by D1: per-model weekly
  is a third trigger (FR-16, FR-18, FR-19).
- **AS-2 (Q7): CONFIRMED** by D2. The check runs at cycle start. A cycle already running finishes.
  There is no mid-cycle kill (FR-26).
- ~~**AS-3 (Q10):** In fail-open mode, a check that keeps failing still files **one** deduped
  `needs-human` issue after N consecutive failed polls.~~ **SUPERSEDED** by D3 and D7: no issue;
  alerting instead (FR-22).

### N. History and recovery (Amendment 3, D18)

- **FR-52: Capped history log (required).** The poller keeps daily files
  `~/.hos/usage-pause/history/usage-YYYY-MM-DD.jsonl`, one JSON line per poll with the same fields as
  the reading file. On **every** poll it prunes to whichever limit is hit first: `history_days`
  (default 90) or `history_max_mb` (default 100 MB total; oldest deleted first). Its purpose is a
  recovery path if monitrix or the exporters go down.
- **FR-53: Export for backfill.** A `hos-usage-poll export --from --to` subcommand emits OpenMetrics
  **with timestamps** from the history log, suitable for
  `promtool tsdb create-blocks-from openmetrics`. The runbook covers the backfill procedure.
- **FR-54: Write order.** Each poll writes the **reading file first** (it holds the decision), then
  the `.prom` file, then the history line. The last two are **best-effort**: their failure never
  blocks or changes the reading file or the decision. A `history_write_ok` gauge reports whether the
  history write succeeded.
- **FR-55: `last-raw`.** The poller overwrites `~/.hos/usage-pause/last-raw` with the raw `/usage`
  output on every poll, for parse-failure debugging. It is one file, never appended.

### O. Read-cost verification (Amendment 3, D13)

- **FR-56:** Each read records `total_cost_usd` and the token counts from the JSON envelope. The
  poller exports them as `hos_claude_usage_read_cost_usd` and `hos_claude_usage_read_tokens`. An
  alert fires if **either is ever non-zero** (FR-62). Cost 0 is evidence for FR-9 only. It never
  establishes read success (FR-12).

### P. Monitoring delivery and alerting (Amendment 3, D9, D17, D17b, D19)

- **FR-58: Grafana file provisioning (D9).** The dashboard JSON, the alert rules, and the contact
  point are delivered by Grafana **file provisioning**, not UI import. They live in the HOS repo under
  `contrib/monitoring/` and are **not** shipped to consumers by `hos_install.sh`. `allowUiUpdates` is
  false. **[A4: H-3]** Grafana reloads provisioned dashboards on its own. Alert-rule and
  contact-point changes are applied by a root systemd path unit on the monitoring host, which
  restarts grafana-server when the provisioned alerting files change, with health check and rollback.
  *Was:* ~~Grafana reloads provisioned files on its own.~~ (false premise for alerting, identified in
  ADR-1944 A2-14; corrected by H-3).
- **FR-59: monitrix sync (D9).** monitrix holds a **read-only** clone of HOS over **anonymous
  HTTPS** (no deploy key), with sparse-checkout limited to `contrib/monitoring/`. A cron
  `git pull --ff-only` updates it. The sync job writes its own health gauges (last good pull
  timestamp, deployed commit) into monitrix's `node_exporter` textfile directory. A "dashboard sync
  stale" alert fires on them.
- **FR-60: Grafana alerting (D17).** Alerting uses **Grafana alerting**, not Alertmanager.
  `prometheus.yml`'s existing `alertmanager` stanza is left alone.
- **FR-61: Contact point (D17).** Every HOS alert goes to **one** contact point with **both** an
  email and an SMS integration. **Email:** a Grafana webhook to a Cloudflare Worker that sends the
  email, authenticated by a shared secret in an `Authorization` header. The secret lives **only** in
  Grafana's env file on monitrix and in the Worker's secrets. The Worker code lives **outside** HOS.
  **SMS:** a webhook to a relay that forwards to an SMS provider (e.g. the never-deployed
  condoparkshare `monitoring/sms-pager/sms_relay.py`, Grafana webhook → Twilio). No provider has been
  chosen, so the SMS integration is a **placeholder**. The repo carries **placeholders only**, never
  real endpoints or secrets.
- **FR-62: Required alerts (D17).** At minimum: pause condition (`hos_claude_usage_pause_condition`
  = 1); reading failed; reading stale / poller dead; metrics absent; `settings_valid` = 0; non-zero
  read cost or tokens; `history_write_ok` = 0; dashboard sync stale; **[A4: H-2/H-3]** read cost or
  tokens unknown on a successful read; alerting reload failed on the monitoring host.
- **FR-63: Worked example, not a requirement (D17b).** HOS ships this setup as a documented
  **worked example / "recommended setup"** in `contrib/monitoring/` plus a doc: faberix poller →
  `node_exporter` → monitrix Prometheus → Grafana alerting → Cloudflare Worker email + SMS relay.
  Each adopting project sets up its own alerting. **HOS guarantees only the poller, the gate, and
  the metrics contract.**
- **FR-64: No hardcoded thresholds (D19).** Every threshold is either a setting
  (`usage-pause.conf`) or a named value at the top of a rules file. The poller exports the thresholds
  it actually uses as `hos_claude_usage_threshold_percent{limit=...}`. Dashboard threshold lines and
  alert rules compare against those gauges, **never a literal 90**.

### Q. Rollout, consumers, and install path (Amendment 3, D3, D10, D14)

- **FR-65: Consumers ship fail-closed (D10, ESC-1 option (a)).** On a consumer host with no poller,
  every cycle pauses (fail-closed, no reading file) with a log line naming the reason. This lasts
  until the host sets up the poller or sets `fail_mode=open`. The release notes and the upgrade
  checklist carry the setup step. There is **no** consumer-default-off switch.
  **[A4: H-1]** The release notes, the upgrade checklist, and the runbook contain the sentence:
  'fail_mode=open without a running poller means no quota protection'.
- **FR-66: One install-path definition (D14).** The poller and gate install path is defined in
  **one** place (the runbook / crontab line), so #1276 changes one line. The design does not assume
  it runs from a git clone. The cross-clone writable-`bin/` risk (ESC-T1) is an **accepted
  near-term risk**, closed long-term by #1276 and v0.7.4 sandboxing. No separate issue is filed.
- **FR-67: Fail-open needs alerting (D3).** The runbook states that fail-open is safe **only once
  alerting is live** (FR-60–FR-62).

---

## 3. Dependencies

- **D-1: MET (Amendment 3).** A real captured `/usage` sample with the local-sessions breakdown
  section exists: capture 2 (D13). It shows two windows (`Last 24h`, `Last 7d`) and shows that
  breakdown lines are individually optional (FR-17). *Residual:* it does not show whether
  percentages can exceed 100 once credits are in use. The parser must still not clamp or reject them.
- **D-2: Haiku fallback end-to-end verification** outside the #1370 constraint (FR-14 / AC-21).
- **D-3: Confirmation of the textfile-collector mechanism and directory** on this host (Q4).
  Needed for FR-41. The sandbox could not observe it (verification gap a).
- **D-4 (new, D13):** The **full, unfiltered** JSON envelope, captured by the first real poller
  `--check` (FR-48). Until then, parsing uses only fields already seen (FR-2).
- **D-5 (new, D17):** An SMS provider choice. Until one exists, the SMS integration is a
  placeholder, and AC-43's SMS half is deferred.
- **D-6 (new, D17):** The Cloudflare email Worker endpoint and its shared secret, held outside the
  repo (FR-61). Needed for AC-43 and AC-44. Per VF-9(a), alerting is not set up on monitrix today.

---

## 4. Acceptance criteria

The `/usage` cases use captured fixtures or a stubbed SSH/`claude` boundary unless stated otherwise.
Every criterion applies to both the worker and overseer roles. *Amendment 3:* fixtures are JSON
envelopes whose `result` holds the captured text.

- **AC-1 [A3]:** A real-shape fixture (session 4%, weekly-all 29%, Fable 6%; #1446 05:17:05Z, as the
  `result` text) gives a SUCCESSFUL read and no pause. All three limits are evaluated. The reading
  file holds a success record with `parsed_via=grep`, and the matching gauges are present.
- **AC-2 (boundary):** session 90%, weekly 10% → pause. session 89%, weekly 89% → no pause.
- **AC-3 [A3: D1, D7]:** session 10%, weekly 90% → pause. The pause reason in the reading file and
  in the `hos-cron` log names the weekly (all-models) limit. *Was:* ~~The issue names the weekly
  window.~~
- **AC-4 (negative, #1362/#1369 class) [A3: D13]:** The silent-empty-session fixture (exact text from
  PR #1450 07:48:32Z, Test 1), and a JSON envelope whose `result` has no `% used` lines with cost 0
  and tokens 0 → FAILED read, with a reason that identifies the empty shape. Cost 0 is **not**
  treated as success. Under fail-closed → pause. The session/weekly gauges are **absent**, and **no
  artifact anywhere records 0%**.
- **AC-5 (negative):** Output with a session line but no weekly line, or the reverse → FAILED read.
- **AC-6 (negative):** Missing key, refused connection, or rejected `from=` (SSH failure) →
  FAILED read → fail mode.
- **AC-7 (negative):** A `claude` stub that hangs → FAILED read within the configured bound. The
  poll does not hang the cycle.
- **AC-8 (negative, consumer side) [A3: D6]:** Reading file older than the staleness window → fail
  mode. Missing file → fail mode. Truncated or garbled file → fail mode. Each case produces its own
  distinct reason.
- **AC-9 [A3: D3, D7] [A4: H-1]:** Fail-open setting plus empty-session fixture → no pause, no
  GitHub call, **and exactly one `cycle-usage-unchecked` audit event**. The reading file records the
  failure, and the parse-status health gauge shows the failure.
- **AC-10 (auto-resume) [A3: D1, D7]:** Paused at session 92%. The next read shows all three limits
  below threshold (e.g. 40% / 30% / Fable 10%) → the next cycle runs with no human action.
  *Was:* ~~… and the proactive-pause issue is auto-closed.~~
- **AC-11 (negative) [A3: D7b]:** A human `hos-suspend` marker (or a timeout-breaker one) exists. An
  under-threshold read does **not** remove it, and the cycle stays suspended. An over-threshold read
  does not create, modify, or remove any suspend marker.
- **AC-12 (no deadlock):** While paused, the poll keeps running and keeps overwriting the reading
  file. A pause can always end through FR-23.
- **AC-13 [A3: D6, D18]:** After N ≥ 3 polls mixing success and failure, exactly one reading file,
  one `.prom` file, and one `last-raw` file exist, each overwritten in place. A failure poll
  overwrites a previous success record. The only file that grows is the day's history file, by one
  line per poll, within FR-52's caps. No per-role/project status files exist. No new lines appear
  in `audit/log/` per poll. *Was:* ~~… one status file … for the scope … No new files or appended
  lines appear anywhere.~~
- ~~**AC-14:** Five consecutive over-threshold polls → exactly one open proactive-pause issue. If the
  dedup query fails → no issue is filed, and the pause is still applied.~~ **SUPERSEDED** (D7: no
  issue filing). Replaced by AC-35.
- **AC-15 (negative, credential) [A3: D5]:** (a) A static check confirms the read path never sources
  `claude-auth.env` and contains **no** environment unsetting (`env -u` or equivalent) on either side.
  (b) The ssh invocation forwards no credential variables. (c) The installed `authorized_keys` entry
  matches FR-3 and has no `restrict` option.
  *Was:* ~~With `CLAUDE_CODE_OAUTH_TOKEN` exported in the caller's environment, the `claude` process
  doing the read does not have it.~~
- **AC-16:** On a host with the loopback set up, a real unattended cron-context read without a pty
  gives a SUCCESSFUL read (a manual, recorded run is acceptable).
- **AC-17:** #1944 makes no change to the obsolete #1450 reactive-breaker code (`bin/hos-cron`
  `:2090-2155` and `:2181-2202`). No #1944 requirement or test depends on that code being active.
- **AC-18 [A3: D13]:** A fixture with no breakdown section → a SUCCESSFUL read with an unchanged
  decision, and the breakdown gauges are absent (not 0). Capture 2 as a fixture → the breakdown gauges
  for both windows are present with the raw values, the 7d 8h+-session series is **absent** (not 0),
  and the decision is unchanged.
- **AC-19 [A3: D19]:** The `.prom` output has only raw-value, read-cost, configuration (threshold,
  `settings_valid`), and health gauges, with no delta/rate/forecast/cumulative series. The change
  adds no listening socket.
- **AC-20 [A3: D9, D19]:** The dashboard JSON loads through Grafana **file provisioning** without
  errors and contains the four panels in FR-46. Its threshold lines come from
  `hos_claude_usage_threshold_percent`. Its early-warning panel uses `predict_linear`. Its pause
  annotations come from `hos_claude_usage_pause_condition`.
- **AC-21 (Haiku):** Until a verification record exists, a grep-miss fixture → FAILED read, and a
  stub confirms **no model call** was made. The verification record is a documented run outside the
  #1370 sandbox against real failed-grep input, showing the fallback's actual output. It is
  required before the fallback can feed the decision.
- **AC-22 [A3]:** The preflight `--check` run twice changes nothing on the second run. With the key
  removed, it reports the missing key plainly and exits non-zero.
- **AC-23 [A3: D7b]:** Changing the session threshold to 80 in `usage-pause.conf` → pause at 80%
  with no code change, and every project and role on the host picks it up.
- **AC-24 (negative, VF-2):** A worker transcript containing "usage limit reached" or any threshold
  wording, while `/usage` reads under threshold → no proactive pause.
- **AC-25 [A3: D13]:** A recorded real read on faberix shows `total_cost_usd` 0 and token counts 0,
  **and** the non-zero read cost/token alert exists (AC-41).
  *Amendment 2 text (superseded by D13):* ~~(a) the AC-21 stub test passes …; (b) a recorded `--check`
  run shows the forced command …; (c) two real reads taken 10 s apart … report the same
  `session_pct`.~~ *Original text:* ~~A primary-path read reports `$0.0000` / `0 input, 0 output`.~~
- **AC-26:** The existing suite (`scripts/framework/run_tests_inner_loop.sh`) passes, including
  T4.1 once Q8 is resolved.
- **AC-27 (Amendment 1, FR-50) [A3: D6]:** The `/usage` read happens only in the standalone poller.
  `bin/hos-cron` runs no `/usage` call and no SSH loopback, decides only from the reading file, and
  writes nothing to it. With a project suspended, the poller still runs on schedule and overwrites
  the reading file.
- **AC-28 (Amendment 1, FR-19 `>=`):** `session=90, weekly=0` → pause. `session=0, weekly=90` →
  pause. `session=89, weekly=89` → no pause. A test that treats exactly 90 as "not reached" fails.
- **AC-29 [A3: CONFIRMED, D2]:** A cycle already running when the reading file flips to
  over-threshold is not killed by this feature. The next cycle start is gated.
- ~~**AC-30 [ASSUMED, AS-3]:** Fail-open mode with N consecutive failed polls → exactly one open
  `needs-human` issue. N-1 failures → none. One success resets the count.~~ **SUPERSEDED** (D3, D7).
  Replaced by AC-35 and the alert criteria AC-47.

**New in Amendment 3:**

- **AC-31 (D1, per-model trigger):** session 10, weekly-all 10, Fable 90 → pause, and the reason is
  `weekly_model:Fable 90% >= 90`. Fable 89 (others low) → no pause. With two per-model lines, either
  one at threshold pauses.
- **AC-32 (D1, absent per-model line):** A fixture with session and all-models lines but no
  `Current week (<model>)` line → SUCCESSFUL read. The decision uses session and weekly-all only, and
  the per-model gauge is absent (not 0).
- **AC-33 (D4, invalid settings):** Missing `usage-pause.conf` → defaults apply (90/90/90,
  fail-closed). Each of these → pause under **both** fail modes, with the `hos-cron` log line and the
  reading file naming the bad key and `settings_valid` = 0: an unreadable file; a threshold of 0,
  101, or non-numeric; an unknown key; a duplicate key; an unknown fail mode; a staleness window ≤
  the poll interval. No GitHub call is made.
- **AC-34 (D7b, global stateless pause):** One over-threshold reading → the worker and overseer
  cycles of **every** configured project on the host skip. No `~/.hos/suspend/*` file is created,
  changed, or removed. An interactive session is not affected. The next under-threshold reading
  resumes all of them with no cleanup step.
- **AC-35 (D7, no GitHub calls) [A4: TD-O-22]:** With the GitHub boundary stubbed, a run covering an
  over-threshold pause, a fail-closed failure, a fail-open failure, invalid settings, and a resume
  shows that **a paused cycle makes zero network calls, and the gate adds none to a running cycle**
  (a running cycle's call list equals that of the same cycle with a plain under-threshold reading).
  The gate makes no issue, comment, label, or dedup call in any case.
  *Was:* ~~… makes **zero** GitHub calls (no issue, comment, label, or dedup query).~~ Read
  literally, that would forbid `hos-cron`'s ordinary work on running cycles (TD-O-22).
- **AC-36 (D18, history cap: days):** History files older than `history_days` are deleted on the
  next poll, even when the total size is under `history_max_mb`.
- **AC-37 (D18, history cap: size):** When the total history size exceeds `history_max_mb`, the next
  poll deletes the oldest files first until the total is within the cap, even when all files are
  younger than `history_days`. With both limits set, whichever is hit first governs.
- **AC-38 (D18, export/backfill round trip):** Given a history log covering a known range,
  `hos-usage-poll export --from --to` emits OpenMetrics with timestamps that
  `promtool tsdb create-blocks-from openmetrics` accepts without error. Querying the resulting blocks
  returns the same values at the same timestamps as the history lines, and absent values stay absent
  (not 0).
- **AC-39 (D18, write order):** With the `.prom` write or the history write made to fail, the
  reading file is still written correctly and the decision is unchanged. A history-write failure
  sets `history_write_ok` = 0. The reading file is written before either.
- **AC-40 (D18, `last-raw`) [A4: TD-O-16]:** After a success poll and then a parse-failure poll, the
  bytes after `last-raw`'s header line are exactly the second poll's raw output. Only one such file
  exists. *Was:* ~~`last-raw` holds exactly the second poll's raw output~~ (the header line is
  ADR-1944 A2-11's; TD-O-16).
- **AC-41 (D13, non-zero read cost alert):** The alert rule exists in `contrib/monitoring/`. It fires
  on a non-zero `hos_claude_usage_read_cost_usd` and, separately, on a non-zero
  `hos_claude_usage_read_tokens`. It does not fire when both are 0.
- **AC-42 (D9, sync-stale alert):** The sync job exports a last-good-pull timestamp and the deployed
  commit. With the timestamp older than the rule's named staleness value, the "dashboard sync stale"
  alert fires.
- **AC-43 (D17, test alert delivery):** A test alert sent through the HOS contact point is
  **received by email**. This is a recorded real run. Once an SMS provider exists (D-5), it is also
  received by SMS. Until then, the SMS integration is present as a placeholder.
- **AC-44 (D17, definition of done):** **#1944 is not done until a real pause alert has been
  delivered.** That means a recorded end-to-end run in which `hos_claude_usage_pause_condition` = 1
  produces an alert received by email through the contact point. **[A4: H-4]** (procedure: lower
  one threshold below current live usage, observe the pause and the email, record, restore; all
  autonomous work pauses for about 10–15 minutes and running cycles finish first)
- **AC-45 (D19, no hardcoded thresholds):** A static check finds no literal threshold in the
  dashboard JSON or the alert rules, outside named values at the top of a rules file. Changing a
  threshold in `usage-pause.conf` changes the matching `hos_claude_usage_threshold_percent` series,
  and the dashboard line and alert follow it with no file edit.
- **AC-46 (D10, consumer with no poller):** On a host with the gate installed but no poller, every
  worker and overseer cycle pauses (fail-closed), and the log line names the missing reading as the
  reason. With `fail_mode=open`, cycles run, each writing one `cycle-usage-unchecked` audit event
  naming the project and cycle_id; the release notes contain 'fail_mode=open without a running
  poller means no quota protection' **[A4: H-1]**. The release notes and the upgrade checklist contain the
  poller setup step. No setting exists that turns the gate off by default for consumers.
- **AC-47 (D17, required alerts and placeholders) [A4: H-2]:** Every alert in FR-62 exists in
  `contrib/monitoring/`, is enabled, and routes to the single contact point, which has both an email
  and an SMS integration. A test in the PR-required suite (`scripts/framework/run_tests_inner_loop.sh`)
  asserts each required alert by stable rule UID, and asserts both integrations. A static check finds no real endpoint URL or secret in the repo, only placeholders.
  `hos_install.sh` does not install `contrib/monitoring/`.
- **AC-48 (D5, forced-command line is final only after a real read):** After the FR-3 entry is
  installed, a real `--check` read returns real session and weekly percentages. The entry is not
  recorded as final until this run is recorded.
- **AC-49 (D13, full envelope fixture):** The first real `--check` run stores the full, unfiltered
  JSON envelope as a fixture. The parser's tests pass when fields outside `result`,
  `total_cost_usd`, and `usage` are removed from or added to that fixture.
- **AC-50 (D9, monitrix delivery):** The monitrix clone uses anonymous HTTPS with no deploy key, is
  sparse-checked-out to `contrib/monitoring/`, and updates only with `git pull --ff-only`. The
  provisioning config sets `allowUiUpdates: false`. A pushed change to `contrib/monitoring/` appears
  in Grafana without a UI import.
- **AC-51 (D3, D7b, D14, D18, runbook content):** The runbook states that fail-open is safe only
  once alerting is live. It lists a check of every scheduled `hos-cron` copy for the gate. It defines
  the poller/gate install path in exactly one place. It covers the export/backfill procedure.
- **AC-52 (D8, pause and health gauges):** `hos_claude_usage_pause_condition` is 1 when any limit is
  `>=` threshold, 1 on a fail-closed failed read, and 0 under fail-open on a failed read with no limit
  over. There is exactly one such series for the machine. With no success on record,
  `last_success_timestamp_seconds` is 0.

**New in Amendment 4:**

- **AC-53 (H-7):** **S1 trip test (recorded before S2 is built).** On faberix, with S1 deployed and
  no gate installed, a threshold in `usage-pause.conf` is temporarily set below the current live
  value of its limit. The next cron-fired poll writes `poll_pause_condition=1` to the reading file,
  with `poll_pause_reason` naming that limit, its value, and the lowered threshold.
  `bin/hos-usage-poll --check` reports `pause_condition=1` with the same reason. After the threshold
  is restored, the next poll writes `poll_pause_condition=0`. The run is recorded on #1944, and S2 is
  not built until it is.

---

## 5. Explicit non-goals

- Anything involving the obsolete #1450 reactive breaker: re-enabling, rewriting, deleting, or
  relying on it as a backstop (human ruling, interactive session 2026-10-02).
- Pausing interactive or human-proxy sessions. The purpose is to leave headroom *for* them (D7b).
- A cron-specific `/usage`-capable token, or any re-storing of the personal credential (rejected
  under #1359).
- Revisiting whether `/usage` works under `CLAUDE_CODE_OAUTH_TOKEN`, or TTY/pty theories. Closed.
- ~~Building a historical usage log. Prometheus TSDB provides history (#1944 10-02).~~ *Amendment 3:*
  a **capped** recovery history log is now required (FR-52, D18). An **unbounded** log remains a
  non-goal (FR-34).
- Provisioning SSH loopback through `hos_install.sh`.
- *Amendment 3:* Any GitHub issue filing, dedup, or auto-close by the poller or gate (D7). The
  #1450-pattern dedup bug is #1946's scope.
- *Amendment 3:* Reading, writing, or clearing `hos-suspend` markers (D7b).
- *Amendment 3:* Alertmanager, or any change to `prometheus.yml`'s `alertmanager` stanza (D17).
- *Amendment 3:* The Cloudflare email Worker's code, and choosing an SMS provider (D17).
- *Amendment 3:* Requiring consumers to adopt the worked-example alerting stack (D17b), or shipping
  `contrib/monitoring/` via `hos_install.sh` (D9).
- *Amendment 3:* A consumer-default-off switch for the gate (D10).

---

## 6. Open questions for the architect

From #1944 (carried over unchanged unless marked):
- **Q1: RESOLVED (human ruling, interactive session 2026-10-02).** A separate standalone cron job
  every 5 minutes does the read and writes the reading file. `bin/hos-cron` gains a cycle-start
  check that reads it (FR-50, FR-26). The architect still owns the poller's crontab and
  PATH handling (FR-6, FR-34).
- **Q2: SSH-loopback setup runbook plus the idempotent preflight check (FR-47/48).** Open.
- **Q3: PARTLY RESOLVED (D4, D19).** The settings file is `usage-pause.conf`. Its directory is still
  open. VF-4 is input: `machine-accounts.env` is a repo file that `hos-cron` does not read, while
  `~/.config/hos/` is the machine-level directory `hos-cron` does read.
- **Q4: The textfile-collector mechanism and directory on this host**, and how the `.prom` write is
  made atomic for scraping (FR-45). Open.

**From earlier passes:**
- **Q5: RESOLVED (human ruling, interactive session 2026-10-03, D6).** One machine reading file
  `~/.hos/usage-pause/reading`, written only by the poller. No per-role/project status files (FR-31).
- **Q6: RESOLVED (D1).** Per-model weekly is a third trigger, with its own threshold (FR-18/19). AS-1
  is superseded.
- **Q7: RESOLVED (D2).** Cycle start only. A running cycle finishes. No mid-cycle kill (FR-26). AS-2
  is confirmed.
- **Q8 (NEW):** How the `claude -p /usage` call site fits with ADR-1643 AD-16 / T4.1 (VF-6). Is it
  a named exemption, routed through `invoke_agent.sh`, or something else? The same question applies
  to the Haiku fallback. Open. *Note:* under D5 the actual `claude` command is fixed in the
  `authorized_keys` forced command, not in a repo script.
- **Q9 (NEW):** The default time bound for the `/usage` read (FR-7), and whether it is configurable.
  Open.
- **Q10: RESOLVED (D3, D7).** No issue under fail-open. Alerting instead (FR-22). AS-3 is superseded.
- **Q11: RESOLVED (D4).** FR-30.
- **Q12: RESOLVED (D5).** The forced `command=` is adopted, with `from=` and **no `restrict`**
  (FR-3).
- **Q13 (NEW):** Should reset times (the `/usage` reset text) go into the reading file and/or appear
  as gauges? The text has no year (`Oct 10, 12am (UTC)`). Open.
- **Q14 (NEW):** Runbook location. #728's auth runbook is `CRON-SETUP.md` §2, not
  `MACHINE-ACCOUNTS-SETUP.md` (VF-5). Open.
- **Q15: RESOLVED / MOOT (D7).** No issues are filed, so there is no per-project issue question.
- **Q16: RESOLVED (D7b).** The pause does not reuse the `hos-suspend` marker. It is a separate,
  stateless, global mechanism (FR-51). FR-25 holds structurally.
- **Q17 (NEW):** Is a single audit event per pause/resume transition wanted? Per-poll events are
  ruled out (FR-34). Open. (D6 mentions per-cycle decisions already being in "the audit events". See
  Human Review item 3.)
- **Q18 (NEW):** If the Haiku fallback is ever verified, which credential and quota does it run
  under, given that it spends the quota it measures? Open.
- **ESC-1: RESOLVED (D10), option (a).** FR-65.
- **ESC-T1: RESOLVED (D14), accepted near-term risk.** FR-66.
- **ESC-T3, TD-O-2: REMOVED (D7).** Both concerned GitHub issue filing in S2.

---

## 7. Traceability

| Req | Source |
|---|---|
| FR-1 | PR #1450 bot correction 2026-08-17T07:46:46Z; ScottThurlow 08:08:39Z; #1446 07:47:00Z; #1944 History |
| FR-2 | ScottThurlow 08:08:39Z; #1944 History; #1446 05:17:05Z (`/api/oauth/usage` non-viable); **human ruling, interactive session 2026-10-03, D13** (`--output-format json`, parse `result`, no unseen fields) |
| FR-3 | #1944 "What's new today (2026-10-02)"; **human ruling, interactive session 2026-10-03, D5** (forced command, no `restrict`, not final until a real `--check`) |
| FR-4 | #1944 "What's new" + History (#1359 rejection); **human ruling, interactive session 2026-10-03, D5** (no env unsetting; plain login environment) |
| FR-5 | #1944 empirical table, last row |
| FR-6 | #1446 05:17:05Z (`command not found`); #1944 Q1 |
| FR-7 | #1944 History restating 08-17 ("no reading, error, timeout") |
| FR-8 | #1944 10-02 "Poll interval" |
| FR-9 | #1944 "Confirmed separately: `/usage` costs nothing"; human ruling, interactive session 2026-10-03, D13 |
| FR-10 | #1944 Reference; #1446 05:17:05Z (`usage-parse.sh` `parse_grep`) |
| FR-11 | #1944 Reference; #1446 05:17:05Z (content-only success condition); ADR-1944 Amendment 1 A1-3, TD-1944 §9.1 TD-O-3; **human ruling, interactive session 2026-10-03, D12** (confirmed); D1 (per-model line not required) |
| FR-12, FR-13 | PR #1450 07:48:32Z Test 1; #1944 History; #1944 Related (#1362/#1369); **human ruling, interactive session 2026-10-03, D13** (cost 0 does not prove success) |
| FR-14 | #1944 Reference; #1446 05:17:05Z |
| FR-15 | #1446 05:17:05Z (`parsed_via`); #1446 05:25:22Z (status contents) |
| FR-16 | #1446 05:17:05Z (Fable optional, null when absent); **human ruling, interactive session 2026-10-03, D1** (per-model triggers; absent line not a failure) |
| FR-17 | Human directive, interactive session 2026-10-02; #1944 addendum 2026-10-02T23:06:30Z; **human ruling, interactive session 2026-10-03, D13** (capture 2; per-line optional) |
| FR-18 | #1944 10-02 "Thresholds" (supersedes PR #1450 08:05:21Z, ScottThurlow 08:08:39Z, 07:46:46Z, #1446 07:47:00Z); **human ruling, interactive session 2026-10-03, D1** (third threshold) |
| FR-19 | human ruling, interactive session 2026-10-02 (`>=`); ScottThurlow 08:08:39Z ("either"); PR #1450 07:46:46Z ("at 90%"); **human ruling, interactive session 2026-10-03, D1** (three triggers; reason names the limit) |
| FR-20 | #1944 ("2h"); ScottThurlow 08:08:39Z ("2 hour"); human directive 2026-10-02 ("2h/5h") |
| FR-21 | #1944 10-02 "Fail-open/fail-closed" + "consumption contract"; PR #1450 08:05:21Z; overseer 08:37:00Z; human ruling, interactive session 2026-10-03, D3 (default closed), D4 |
| FR-22 | #1446 05:25:22Z; **human ruling, interactive session 2026-10-03, D3** (no issue; alerting) |
| FR-23 | PR #1450 08:05:21Z; #1944 History; ScottThurlow 08:08:39Z; human ruling, interactive session 2026-10-03, D1 (all three below) |
| FR-24 | [DERIVED] FR-23 + VF-3; satisfied for the poll by human ruling, interactive session 2026-10-02 (standalone poller) |
| FR-25 | [DERIVED] FR-23 + VF-3; **human ruling, interactive session 2026-10-03, D7b** (never writes or clears suspend markers) |
| FR-26 | #1944 title + Goal; human ruling, interactive session 2026-10-02 (cycle-start check); **human ruling, interactive session 2026-10-03, D2** (in-flight), D6 (read-only), D7b (all projects/roles) |
| FR-27 | #1944 10-02 "Thresholds" (shared-quota rationale); **human ruling, interactive session 2026-10-03, D7b** (global pause) |
| FR-28 | `bin/hos-cron:2090-2107` (operator disable 2026-09-01) |
| FR-29 | #1944 10-02 "Thresholds" (machine-level); #1944 Q3; human ruling, interactive session 2026-10-03, D1, D4, D18, D19 |
| FR-30 | **human ruling, interactive session 2026-10-03, D4** (confirms Q11 minus issue filing) |
| FR-31 | #1446 05:25:22Z; `sync_human_clone.sh:120-133`; **human ruling, interactive session 2026-10-03, D6** (one machine reading file; supersedes per-role/project) |
| FR-32 | #1446 05:25:22Z; #1944 10-02 "Status file"; human ruling, interactive session 2026-10-03, D6 |
| FR-33 | #1446 05:25:22Z; human ruling, interactive session 2026-10-03, D1, D4, D13 |
| FR-34 | #1446 05:25:22Z; ScottThurlow 08:08:39Z; **human ruling, interactive session 2026-10-03, D18** (clarification; supersedes the 10-02 "supersedes any append/CSV + size-based rotation" wording) |
| FR-35 | #1446 05:25:22Z; human ruling, interactive session 2026-10-03, D18 |
| FR-36 | #1944 10-02 "consumption contract" + "Poll interval" |
| FR-37, FR-38, FR-39 | **SUPERSEDED** — human ruling, interactive session 2026-10-03, D7 (was: #1944 10-02 "Visibility on trip"; `bin/hos-cron:2056-2080, 2132-2154, 2181-2202`) |
| FR-40 | human ruling, interactive session 2026-10-02 (reactive breaker obsolete); VF-1 |
| FR-41 | #1944 10-02 "Dashboarding"; human directive 2026-10-02; #1944 addendum 2026-10-02T23:06:30Z |
| FR-42 | Human directive, interactive session 2026-10-02; #1944 addendum; **human ruling, interactive session 2026-10-03, D1, D4, D8, D13, D18, D19** |
| FR-43 | Human directive, interactive session 2026-10-02 |
| FR-44 | Human directive, interactive session 2026-10-02; **human ruling, interactive session 2026-10-03, D8** (`last_success_timestamp_seconds` = 0 exception), D13 |
| FR-45 | #1944 10-02 "Dashboarding"; human ruling, interactive session 2026-10-03, D18 (write order) |
| FR-46 | Human directive, interactive session 2026-10-02; #1944 addendum; human ruling, interactive session 2026-10-03, D8, D9, D19 |
| FR-47 | #1944 Q2; human ruling, interactive session 2026-10-03, D5 |
| FR-48 | #1944 Q2; human ruling, interactive session 2026-10-03, D5, D13 |
| FR-49 | #1944 Process note; overseer PR #1450 08:37:00Z |
| FR-50 | human ruling, interactive session 2026-10-02 (Q1); human ruling, interactive session 2026-10-03, D6, D18 |
| FR-51 | **human ruling, interactive session 2026-10-03, D7b** |
| FR-52, FR-53, FR-54, FR-55 | **human ruling, interactive session 2026-10-03, D18** |
| FR-56 | **human ruling, interactive session 2026-10-03, D13** |
| FR-57 | **human ruling, interactive session 2026-10-03, D7** |
| FR-58, FR-59 | **human ruling, interactive session 2026-10-03, D9** |
| FR-60, FR-61, FR-62 | **human ruling, interactive session 2026-10-03, D17** |
| FR-63 | **human ruling, interactive session 2026-10-03, D17b** |
| FR-64 | **human ruling, interactive session 2026-10-03, D19** |
| FR-65 | **human ruling, interactive session 2026-10-03, D10** (ESC-1 option (a)) |
| FR-66 | **human ruling, interactive session 2026-10-03, D14** (ESC-T1) |
| FR-67 | **human ruling, interactive session 2026-10-03, D3** |
| AS-1 | SUPERSEDED — human ruling, interactive session 2026-10-03, D1 |
| AS-2 | CONFIRMED — human ruling, interactive session 2026-10-03, D2 |
| AS-3 | SUPERSEDED — human ruling, interactive session 2026-10-03, D3, D7 |
| AC-1–AC-13, AC-15–AC-29 | Their FRs as above; "[A3: Dn]" tags cite human ruling, interactive session 2026-10-03, D<n> |
| AC-14, AC-30 | SUPERSEDED — human ruling, interactive session 2026-10-03, D7 (AC-30 also D3) |
| AC-25 | FR-9; Amendment 2 (TD-VF-8, TD-O-4); **human ruling, interactive session 2026-10-03, D13** (rewritten) |
| AC-31, AC-32 | human ruling, interactive session 2026-10-03, D1 |
| AC-33 | human ruling, interactive session 2026-10-03, D4 |
| AC-34 | human ruling, interactive session 2026-10-03, D7b |
| AC-35 | human ruling, interactive session 2026-10-03, D7 |
| AC-36–AC-40 | human ruling, interactive session 2026-10-03, D18 |
| AC-41 | human ruling, interactive session 2026-10-03, D13 |
| AC-42, AC-50 | human ruling, interactive session 2026-10-03, D9 |
| AC-43, AC-44, AC-47 | human ruling, interactive session 2026-10-03, D17 (AC-47 also D9) |
| AC-45 | human ruling, interactive session 2026-10-03, D19 |
| AC-46 | human ruling, interactive session 2026-10-03, D10 |
| AC-48 | human ruling, interactive session 2026-10-03, D5 |
| AC-49 | human ruling, interactive session 2026-10-03, D13 |
| AC-51 | human ruling, interactive session 2026-10-03, D3, D7b, D14, D18 |
| AC-52 | human ruling, interactive session 2026-10-03, D8 |
| FR-22, FR-65 (A4 additions) | **human ruling, interactive session 2026-10-03, H-1** (`cycle-usage-unchecked` event; fixed release-note sentence); ADR-1944 A4-1, A4-9 items 1–2 |
| FR-58 (A4 correction) | **human ruling, interactive session 2026-10-03, H-3** (root systemd path unit reload); ADR-1944 A2-14, A4-4, A4-9 item 8 |
| FR-62 (A4 additions) | **human ruling, interactive session 2026-10-03, H-2, H-3** (read cost/tokens unknown; alerting reload failed); ADR-1944 A4-3, A4-5, A4-9 item 6 |
| FR-68 | **human ruling, interactive session 2026-10-03, H-2** (protected surface rejected in favour of the required-alert test; rationale: protected surfaces already too broad, #1935; human review restricted to what really matters); ADR-1944 A4-2, A4-3, A4-9 item 7 |
| AC-9, AC-46 (A4 changes) | **human ruling, interactive session 2026-10-03, H-1**; ADR-1944 A4-9 items 3–4 |
| AC-35 (A4 rewording) | TD-1944 TD-O-22 (accepted by architect); ADR-1944 A2-4 intent |
| AC-40 (A4 rewording) | TD-1944 TD-O-16 (accepted by architect); ADR-1944 A2-11 header line |
| AC-44 (A4 procedure) | **human ruling, interactive session 2026-10-03, H-4**; ADR-1944 A4-6, A4-9 item 10 |
| AC-47 (A4 change) | **human ruling, interactive session 2026-10-03, H-2**; ADR-1944 A4-3, A4-9 item 5 |
| AC-53 | **human ruling, interactive session 2026-10-03, H-7**; ADR-1944 A4-7, A4-9 item 9 (architect wording, verbatim) |
| D-1 | Human directive 2026-10-02; #1944 addendum; **met** by capture 2 (human ruling, interactive session 2026-10-03, D13) |
| D-2 | #1944 Reference; #1446 05:17:05Z |
| D-3 | #1944 10-02 "Dashboarding" + Q4 |
| D-4 | human ruling, interactive session 2026-10-03, D13 |
| D-5, D-6 | human ruling, interactive session 2026-10-03, D17 |

---

## 8. Source conflicts and supersessions (how each was recorded)

- **S-1, thresholds:** 90/95 (PR #1450 07:46:46Z, #1446 07:47:00Z) → 85/90 (08:05:21Z, ScottThurlow
  08:08:39Z) → 90/90 (#1944 10-02) → **90/90/90, three limits (human ruling, interactive session
  2026-10-03, D1)**. Recorded in FR-18.
- **S-2, settings scope:** "project config" (08:08:39Z) → **machine-level (#1944 10-02)**. FR-29.
- **S-3, resume wording:** "pause until the offending window resets" (08:08:39Z) and "auto-resume on
  a subsequent under-threshold read" (08:05:21Z, #1944). Same effect, both recorded. The read-driven
  rule is the operative one (FR-23). Clarifying.
- **S-4, the credential question:** "did not work" (ScottThurlow 2026-08-18T04:20:43Z) and the
  retracted success report (07:57:29Z) → **closed by #1944 10-02 SSH loopback**. Not reopened.
- **C-1, RESOLVED by human ruling, interactive session 2026-10-02:** the #1450 reactive breaker is
  obsolete and out of scope (FR-40, AC-17).
- **C-2, settings location:** #1944's suggested `machine-accounts.env` is not machine-level in
  practice (VF-4). The file name is now ruled (`usage-pause.conf`, D4/D19). The directory is still
  Q3.
- **C-3, runbook location:** #1944 "likely `MACHINE-ACCOUNTS-SETUP.md`" vs the #728 runbook actually
  being `CRON-SETUP.md` (VF-5). Input to Q14.
- **C-4, governance:** The ruled raw `claude -p /usage` vs the AD-16 / T4.1 single-invocation-site
  rule (VF-6). Q8.
- **C-5, scoping tension: RESOLVED by D6.** The per-role/project status file has been replaced by one
  machine reading file (S-11).
- **S-5, poll location:** in-`hos-cron` (#1446 05:17:05Z) / open (#1944 Q1) → **standalone cron
  poller (human ruling, interactive session 2026-10-02)** (FR-50).
- **S-6, comparison operator:** "crosses" / "exceed" / "at 90%" → **`>=` (human ruling, interactive
  session 2026-10-02)** (FR-19).
- **S-7, "log file" wording:** the human's "log file / last log entry" (2026-10-02) was recorded as
  the overwrite-in-place file. It still describes the reading file (FR-31). The capped history of
  D18 is a separate artifact (FR-52).
- **A-1, assumed defaults: CLOSED by Amendment 3.** AS-1 superseded (D1), AS-2 confirmed (D2), AS-3
  superseded (D3, D7).
- **C-6, exit code vs content: RESOLVED.** Architect ruling A1-3 is **confirmed** (human ruling,
  interactive session 2026-10-03, D12). FR-11's narrowing is now the ruled requirement.
- **C-7, AC-25 unobservable (Amendment 2): SUPERSEDED by S-13.**

**Amendment 3 supersessions (all: human ruling, interactive session 2026-10-03):**

- **S-8 (D1):** AS-1 "per-model weekly is gauges-only" → per-model weekly is a third pause trigger,
  with its own threshold. FR-16, FR-18, FR-19, FR-23. Q6 closed.
- **S-9 (D3):** AS-3 and FR-22's issue clause (and the derived "dead-poller issue") → under
  fail-open no issue is filed, and the human is alerted by monitoring. FR-22, FR-67. AC-30 retired.
  Q10 closed.
- **S-10 (D7):** The #1944 10-02 ruling "Visibility on trip: reuse #1450's needs-human issue-filing
  pattern", FR-37, FR-38, FR-39, AC-14, Q15, the `[DEGRADED]` issue, and the invalid-settings issue
  → **no issue filing of any kind**. S2 makes no GitHub calls (FR-57). TD-O-2 is moot, and ESC-T3 is
  removed. The 20-issue dedup bug in the existing #1450 pattern (including the collapsed `_audit` at
  `hos-cron:2054`) is filed separately as **#1946**.
- **S-11 (D6):** "One fixed-path status file per role/project" (#1446 05:25:22Z; #1944 10-02;
  reconfirmed in Amendment 1) → **exactly one machine reading file**, written only by the poller.
  `hos-cron` is read-only. FR-31. Q5 and C-5 closed.
- **S-12 (D18), CLARIFICATION, not reversal:** "No ever-growing logs" (ScottThurlow 08:08:39Z)
  **stands**. Capped, rotated history is **required** and consistent with it. This supersedes the
  #1944 10-02 issue wording "Supersedes any append/CSV + size-based rotation approach", FR-34's
  original "no rotation, no per-poll history" text, and the §5 non-goal "Building a historical usage
  log". FR-34, FR-52–FR-55.
- **S-13 (D13):** Plain-text parsing → `--output-format json`, parsing `result` (FR-2). AC-25
  (Amendment 2 substitute) → a recorded faberix read with cost 0 / tokens 0, plus the non-zero alert.
  This also supersedes C-7.
- **S-14 (D5):** FR-4's "must not be set even if the caller exported it" (implicitly by unsetting),
  and the open security question Q12 → forced `command=` with `from=`, **no `restrict`**, **no
  environment unsetting** anywhere. FR-3, FR-4, AC-15.
- **S-15 (D7b):** Q16 (reuse the `hos-suspend` marker?) and the project-scoped framing → a global,
  stateless pause that never touches suspend markers. FR-25, FR-51.
- **S-16 (D8):** FR-44 "absent, never 0" → it still holds, with one deliberate exception:
  `last_success_timestamp_seconds` = 0 when no success is on record. The paused-state gauge is
  defined as a single machine-level `hos_claude_usage_pause_condition`.
- **S-17 (D19):** FR-46's "threshold line at the configured value (90% default)" → threshold lines
  and alert rules compare against exported threshold gauges, never a literal.
- **Confirmations (no supersession):** AS-2 (D2); Q11's conservative reading, minus issue filing
  (D4); architect ruling A1-3 (D12); ESC-1 option (a) (D10); ESC-T1 accepted risk (D14).

**Amendment 4 supersessions (all: human ruling, interactive session 2026-10-03, unless noted):**

- **S-18 (H-1):** Human Review item 8 (a consumer on fail-open with no poller and no alerting is
  silent) → resolved per the architect's recommendation: D10 kept as ruled; each fail-open cycle
  without a usable reading writes one `cycle-usage-unchecked` audit event; the release notes, upgrade
  checklist and runbook carry "fail_mode=open without a running poller means no quota protection".
  No block and no issue. FR-22, FR-65, AC-9, AC-46. The alternative (an explicit acknowledgement key)
  was not chosen.
- **S-19 (H-2), REJECTION:** ADR-1944 A2-14's proposal to make `contrib/monitoring/**` protected
  surface → **rejected**. Human rationale: protected surfaces are already too broad (#1935), and
  human review must be restricted to what really matters. Replacement control: the PR-required test
  `tests/framework/test_monitoring_required_alerts.py`, which asserts each required alert by stable
  rule UID plus both contact-point integrations. Accepted residual: one PR editing both the rules
  file and the test is not mechanically blocked, only review-visible. FR-68, AC-47, FR-62.
- **S-20 (H-3):** FR-58's "Grafana reloads provisioned files on its own" (false for alert rules and
  contact points; ADR-1944 A2-14) → dashboards only; alerting changes are applied by a root systemd
  path unit on the monitoring host with health check and rollback. FR-58, FR-62 (reload-failed alert).
- **S-21 (H-4), CONFIRMATION:** the AC-44 definition-of-done procedure (lower one threshold, observe
  pause and email, record, restore; ~10–15 minutes of paused autonomous work). AC-44 text added for
  clarity; no behavior change.
- **S-22 (H-7), NEW:** S2 is not built until the S1 trip test is recorded on #1944. AC-53.
- **S-23 (TD-O-16, clarifying; architect-accepted):** AC-40 "holds exactly the second poll's raw
  output" → "the bytes after the header line". The header is ADR-1944 A2-11's.
- **S-24 (TD-O-22, clarifying; architect-accepted):** AC-35's literal "zero GitHub calls" across
  running cycles → "a paused cycle makes zero network calls, and the gate adds none to a running
  cycle". The literal reading would forbid `hos-cron`'s ordinary work.

---

## Escalation flag (CORE self-flag)

RISK: HIGH. The feature gates every autonomous cycle on the host, now for all projects and roles
(D7b). It changes `bin/hos-cron` (protected). Under fail-closed, a defect stops all autonomous work.
Under fail-open with no live alerting (VF-9a), credits billing could continue silently.
CONFIDENCE: 80%. High confidence in the transcription of D1–D19 and in the grep-verified VF items.
Lower confidence in the host's exporter setup (Q4) and the full JSON envelope (D-4). Some rulings
leave points ambiguous (Human Review items 1–8). Those were recorded, not resolved.

Classification: Amendment 3 applies **human-ruled** changes, signed off in the interactive session
of 2026-10-03. Most are **structural** (new triggers, issue filing removed, global pause, new
alerting/history/export behavior, retired FRs/ACs). Human sign-off for them is the cited ruling.
D18 is recorded as a **clarification** of the "no ever-growing logs" principle, as the human ruled.
Terminology changes ("status file" → "reading file") are **clarifying**. No change in this amendment
goes beyond a ruling, apart from the points listed below as ambiguous.

Amendment 4 classification: H-1, H-2, H-3 and H-7 changes are **structural**, and each is
**human-ruled** (human ruling, interactive session 2026-10-03, H-1 / H-2 / H-3 / H-7); the ruling
is the sign-off. H-4 (AC-44 procedure text) and the AC-35 / AC-40 rewordings (TD-O-22, TD-O-16)
are **clarifying**: they make the existing intent checkable without changing behavior. Nothing in
Amendment 4 goes beyond ADR-1944 A4-9 or the cited rulings. RISK: HIGH (unchanged; H-2 replaces a
human merge gate with a test guard, by human ruling). CONFIDENCE: 90% on the transcription of A4-9.

## Human Review Required

Earlier items now ruled and removed: C-1; [DERIVED] FR-22, FR-25, FR-30 (D3, D7b, D4); AS-1/2/3
(D1, D2, D3); Q11 (D4); D-1 (capture 2); FR-11 / C-6 (D12).

**Resolved in Amendment 4 (human ruling, interactive session 2026-10-03):**
- **H-1: RESOLVED (confirmed as recommended).** Per-cycle `cycle-usage-unchecked` audit event plus
  the fixed release-note sentence; no block, no issue. This also resolves item 8 below (S-18).
- **H-2: RESOLVED (rejected, replaced).** `contrib/monitoring/**` is not protected surface; the
  PR-required required-alert test is the guard (FR-68, AC-47). Rationale: protected surfaces are
  already too broad (#1935), and human review must be restricted to what really matters (S-19).
- **H-3: RESOLVED (confirmed).** Root systemd path unit reload on monitrix (FR-58, S-20).
- **H-4: RESOLVED (confirmed).** AC-44 procedure (S-21).
- **H-7: RESOLVED (new ruling, applied).** S1 trip test gates S2 (AC-53, S-22).
- Not requirements rulings (tracked in ADR-1944 A4-8): H-5 (informational) and H-6 (human actions).

Still open:
1. **[DERIVED] FR-24** (the pause must not stop the poll): confirm. It is satisfied structurally by
   FR-50.
2. **D4 vs D6, who names the bad key in the reading file.** D4 says the reading file names the bad
   key, but D6 says only the poller writes that file. If `hos-cron` alone sees an invalid
   `usage-pause.conf` (e.g. edited between polls), only its log line can name the key. Also unruled:
   if the poller's recorded decision (and `pause_condition`) and `hos-cron`'s own evaluation of the
   current settings disagree, which one governs?
3. **D6 "per-cycle decisions are already in … the audit events"** implies one audit event per cycle
   decision exists or is wanted. Q17 (an audit event per pause/resume) is otherwise unruled.
4. **D4 scope of "invalid value":** FR-30 and AC-33 treat Q11's examples (a staleness window ≤ the
   poll interval, an unknown fail mode) as invalid, because D4 "CONFIRMS Q11". D4 does not list them
   explicitly.
5. **D5 `restrict` vs individual `no-*` options:** D5 bans `restrict` but does not say whether
   individual `no-pty` / `no-port-forwarding` options are also excluded. FR-3 specifies the ruled line
   exactly, with neither. D5 also forbids unsetting, so FR-4's original goal (no credential vars in
   the read's environment) now rests on sshd not forwarding the environment and on the login profile
   not exporting them. Nothing enforces it if a profile does.
6. **D13 "token counts":** which `usage` fields (input, output, cache read/creation, thinking), and
   whether `hos_claude_usage_read_tokens` is one summed series or labeled by type.
7. **D18 history "same fields as the reading":** whether the reading file (and so the history and
   the backfill export) carries the breakdown gauges, or only the decision fields. This decides
   whether a backfill can restore the breakdown dashboard panels.
8. **RESOLVED by H-1 (Amendment 4, S-18).** *Original:* **D10 vs D3/D17b:** a consumer may set `fail_mode=open` to get past the no-poller pause (D10), but
   alerting is a worked example the consumer need not adopt (D17b). Fail-open being safe only with
   alerting (D3) is runbook text only. Nothing prevents a consumer from running fail-open with no
   poller and no alerting, which is silent.
9. **FR-3 path:** the ruled `command=` uses the operator's `~/.local/bin/claude` (an absolute path on the host; shown as
   `<abs path to claude>` in FR-3). This document reads it
   as the faberix value, with the path host-specific on other hosts (and D14's single-definition
   rule). Confirm.
