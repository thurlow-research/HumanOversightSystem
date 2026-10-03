# TECHNICAL DESIGN — ADR-1944: proactive Claude usage-threshold pause. A loopback poller writes one reading, `hos-cron` gates every cycle on it, and the monitoring path can never touch the decision

**Status:** **Revision 2 (ADR A2) + Architect round 2 (2026-10-03): APPROVED WITH CHANGES.** The round-2 changes are applied inline, each tagged **"Architect round 2"**, and listed in §11.3. ADR Amendment 3 records the four ADR-level refinements (A3-1 to A3-5). **Human rulings H-1..H-4, H-7 (interactive session 2026-10-03; ADR Amendment 4) are applied inline, tagged "Human rulings H-1..H-4, H-7".** No human ruling is outstanding (§13).

**Coding gates (§8):**
- S1 may start.
- S2 starts only after S1 is deployed, its exit records are posted, and the **H-7 trip test** is recorded (§3.15).
- S3 follows S1, plus the §5.1 probe.
- S4 follows S3.
- S5 follows S4.

**Build mode:** #1944 is built in the human's interactive worker session, not by autonomous pickup (no `needs-ai`). Per ADR A4-10, `technical-design` does one consistency pass over the sections tagged "Human rulings H-1..H-4, H-7" before the S1 PR (for §3.10 item 10) and before S4 coding. (Round count: the amended sections opened at round 1 under A2-22; this is round 2 of 5.) Revision 1 (DRAFT-1 plus Architect round 1, "approved with changes", 2026-10-03) was built against ADR text that Amendment 2 supersedes: AD-3's per-role status file, AD-8's issue machinery, AD-5's `env -u` command, the two-threshold rule, plain-text parsing, and AD-12's slicing. This revision implements ADR-1944 Amendment 2 (A2-1 to A2-22) and Requirements Amendment 3 (human rulings D1–D19, interactive session 2026-10-03). Every section changed by this revision is headed or tagged **"Revision 2 (ADR A2)"**. Text that A2 removes is deleted. A one-line "Removed by Revision 2" note marks where it stood, and git history keeps the old text (commit `918fe1769`, `67769516b`). Material that Amendment 2 leaves standing is kept and tagged "unchanged".
**Date:** 2026-10-03 (Revision 1: 2026-10-02)
**Author:** technical-design
**Baseline:** worktree `interactive-1944-proactive-usage-pause-design`, HEAD `0603100b9` (ADR Amendment 2). `bin/hos-cron` is 2245 lines and every anchor cited below was re-read at this HEAD (TD-VF-14).
**Consumes:** `docs/v0.7.0/ADR-1944-proactive-usage-pause.md` (binding, incl. Amendments 1 and 2), `docs/v0.7.0/REQUIREMENTS-1944-proactive-usage-pause.md` (incl. Amendment 3), the human rulings D1–D19 (cited "D<n>"), the D-1 loopback capture (§1.9.1), the second real capture `usage-sample-2-json.txt` (§1.9.2), `bin/hos-cron`, `scripts/automation/lib/cycle_log.py`, `scripts/framework/{protected_surfaces,framework_consumer_files}.txt`, `contract/sandbox-policy.template.json`, `docs/CRON-SETUP.md`, `docs/UPGRADE-PR-REVIEW-CHECKLIST.md`, `docs/AGENT-IDENTITY.md` §9.0, `tests/automation/test_hos_cron.py`, `tests/framework/test_agent_invocation_migration.py`, and the live user crontab on faberix (read-only, TD-VF-16).
**Consumers:** `architect` (review), then the coder through **four code slices and one live-delivery slice** (S1 → S2; S1 → S3 → S4 → S5), plus `unit-test`, `system-test`, `security-reviewer` (§3.8, A2-9 residual), and `infra-reviewer` (§5–§7).
**Scope note:** This document says what the code must do: paths, function contracts, grammars, file formats, orderings, exit codes, configuration-file shapes, and test names. It contains no implementation.

---

## Revision 2 (ADR A2) — what changed, at a glance

| Area | Revision 1 | Revision 2 (ADR A2) | ADR |
|---|---|---|---|
| Status files | `reading.status` + one per-role/project file | exactly one file, `~/.hos/usage-pause/reading`, poller-written; `hos-cron` writes nothing there | A2-2, D6 |
| Visibility | `[PAUSED]`/`[DEGRADED]` issues, complete dedup, lock, auto-close, transition audit | **all removed**; one log line per gated cycle; one `cycle-usage-paused` audit event per paused cycle; Grafana alerting | A2-5, D7 |
| Thresholds | session, weekly-all | + `weekly_model_threshold` for every `Current week (<model>)` line; reason format fixed | A2-6, D1 |
| Read | plain text; `env -u …` remote command sent by the client | `--output-format json`; strict envelope parse of `result`, `total_cost_usd`, four `usage` fields; **client sends no command**; forced command `from=`+`command=` only; no unsetting anywhere | A2-7, A2-9, D5, D13 |
| Failure enum | 8 reasons incl. `claude_not_executable` | 9 reasons incl. `spawn_failed`, `envelope_invalid`; `claude_not_executable` is a `--check` item only | A2-7 |
| Gate placement | after git credentials (`:868`) | immediately after `_audit` (`:362-365`), before audit-log sync (`:367`) | A2-4 |
| Gate sentinel | — | `# HOS-USAGE-PAUSE-GATE schema=1`; `--check` verifies every scheduled `hos-cron` copy | A2-4, D7b |
| Settings | 8 keys incl. `failopen_issue_after` | 10 keys; `weekly_model_threshold`, `history_days`, `history_max_mb`; `failopen_issue_after` removed; single defaults block | A2-10 |
| Side paths | `.prom` | `.prom` (with re-render), daily JSONL history + prune, `export`, `last-raw` | A2-11 |
| Metrics | `threshold_percent{window}` | `threshold_percent{limit}`, + `staleness_seconds`, `read_cost_usd`, `read_tokens`, `history_write_ok` | A2-12 |
| monitrix | Prometheus rules file, Alertmanager | Grafana alerting (12 rules; 13 after H-3), contact point `hos` (email webhook + SMS placeholder), sparse anonymous clone, sync job, reload | A2-13, A2-14 |
| Slices | S1–S4 | S1–S4 + S5 (live delivery, AC-44 = definition of done) | A2-18 |
| **Human rulings H-1..H-4, H-7** | — | `cycle-usage-unchecked` per fail-open cycle plus exact release-note sentence (H-1); **no** protected-surface entry, and a required-alert guard test instead (H-2); systemd path unit + reload script with rollback, and rule 13 (H-3); AC-44 procedure confirmed (H-4); S1 trip test gates S2, plus a `--check` INFO 10 line (H-7) | A4-1 to A4-7 |

---

## Rulings taken as given, not re-litigated

Requirements Amendments 1–3 and ADR-1944 with Amendments 1 and 2 bind. In particular, the A2-n decisions are implemented here, not re-decided: standalone `*/5` poller (FR-50); SSH loopback with the personal-login credential and the exact forced command of D5 (FR-3); `>=` (FR-19); three thresholds, default 90 each (FR-18, D1); fail-closed default (FR-21); invalid settings pause regardless of fail mode (FR-30, D4); one reading file (FR-31, D6); no GitHub calls (FR-57, D7); global stateless pause separate from `hos-suspend` (FR-51, D7b); capped history (FR-52, D18); Grafana file provisioning and alerting (FR-58–FR-62, D9, D17); no hardcoded thresholds (FR-64, D19); consumers ship fail-closed (FR-65, D10); the #1450 reactive breaker is obsolete and untouched (FR-40). Where this design found an A2 decision unimplementable as worded, or had to add to it, the item is raised as a TD-O question in §11 with a binding interim. **No silent deviation.** ADR A2-20's "Human confirmation required" list is carried forward unchanged in §13.

---

## 0. Verification findings

### Kept from Revision 1 (unchanged unless noted)

- **TD-VF-1 (process).** Superseded by TD-VF-14 for every anchor this revision uses.
- ~~**TD-VF-2** (`query_issues.sh --list` is single-page).~~ **Removed by Revision 2 (ADR A2-5):** #1944 has no dedup query. The defect itself is tracked in #1946.
- ~~**TD-VF-3** (issue wrappers do not ship; raw `gh`).~~ **Removed by Revision 2 (ADR A2-5):** the gate makes no GitHub call.
- **TD-VF-4 (T4.2 ledger).** Stands as the reason for the in-process time bound (A1-2). The T4.2 ledger does not change.
- **TD-VF-5 (harness).** Stands in revised form: every `test_hos_cron.py` test that drives the launcher past `:365` would now pause unless the shared fixture writes a fresh reading. The Revision 1 `gh` stub case for the dedup query is **removed** (no dedup). Copied-launcher tests (`test_hos_cron.py:1790`, `:1794`, `:1839`) must also copy `bin/lib/usage_pause.py`. §4.7.
- **TD-VF-6 (`_audit` argv).** Stands: `cycle_log._parse_args` (`scripts/automation/lib/cycle_log.py:69-83`) splits each argv element on the first `=`; every new `_audit` call passes one `key=value` per element.
- ~~**TD-VF-7** (title prefix collision).~~ **Removed by Revision 2 (ADR A2-5):** no issue titles exist.
- ~~**TD-VF-8** (AC-25 unobservable).~~ **Resolved by D13:** the JSON envelope carries `total_cost_usd` and token counts on every read; AC-25 is a recorded real read showing 0/0 plus the alert's existence (§3.14).
- **TD-VF-9 (cross-clone `bin/` writable).** **Accepted near-term risk (D14, A2-16).** No separate issue. Closed long-term by #1276 and v0.7.4 sandboxing.
- **TD-VF-10 (node_exporter on faberix).** Stands: 1.10.2, `--collector.textfile.directory` repeatable, `User=prometheus`, `ARGS=""`. Symlink-follow still needs the root probe (§5.1).
- **TD-VF-11 (D-1 regexes).** Stands for the D-1 text (§1.9.1). TD-VF-15 adds capture 2.
- **TD-VF-12 (paused cycle consumed the wakeup file).** **Resolved by Revision 2 (ADR A2-4):** the gate now runs before the wakeup consume (`:808`), so a paused cycle leaves wakeup markers for the next running cycle.
- **TD-VF-13 (T4.1 matches deliberately).** **Superseded by S1 code-review round 1 (S5), §11.5 C-10:** `bin/lib/usage_pause.py` contains no `claude -p` / `claude --print` text anywhere (docstring included) and is **not** in the T4.1 exemption set; T4.1b pins the single `/usage` read line instead.

### New in Revision 2 (ADR A2)

**TD-VF-14 — gate anchors re-verified at HEAD `0603100b9`** (`bin/hos-cron`, 2245 lines):

| Anchor | Line(s) | Exact text (prefix) |
|---|---|---|
| `set -euo pipefail` | `:116` | |
| pinned `PATH` | `:126` | `export PATH="$HOME/.local/bin:/opt/homebrew/bin:…` |
| `_HOS_CRON_DIR` | `:141` | `_HOS_CRON_DIR="$(dirname "${BASH_SOURCE[0]}")"` |
| `ROLE`/`PROJECT` parsed | `:156-170` | |
| `REPO_ROOT` | `:181` | |
| `LOG_PREFIX` | `:244` | |
| `_HOS_DIR` | `:247` | `_HOS_DIR="${HOS_STATE_DIR:-${HOME}/.hos}"` |
| suspend check | `:258-286` | |
| overlap lock, EXIT trap | `:304-332` (trap `:332`) | |
| cycle identity | `:334-359` | `_project_safe` `:349`, `HOS_CYCLE_ID` `:350` |
| **audit helper header** | **`:361`** | `# ── Audit helper ──…` |
| **`_audit()`** | **`:362-365`** | `_audit() {` … `}` |
| **blank** | **`:366`** | |
| **audit-log sync header** | **`:367`** | `# ── Audit log sync (#861, updated #1303) ──…` (function definition; its only call is `:2234`) |
| worktree hygiene section | `:429` | |
| pre-jitter deps check call | `:737` | `_pre_jitter_deps_check` |
| jitter / env validation / wakeup | `:739` / `:746` / `:766` (consume `:808`) | |
| repo slug / preflight | `:819` / `:823` | |
| token mint | `:834` | `"$REPO_ROOT/bootstrap/get_app_token.sh" --app "$ROLE"` |
| git credentials | `:855-868` | |
| claude-auth.env | `:870` header, `:877` `_CLAUDE_AUTH_ENV=…` | |
| model auth probe | `:899` | `"$CLAUDE_BIN" --print --max-turns 1` |
| halt check | `:906` | |
| `cycle-start` audit | `:1823` | `_audit cycle-start "bot=… project=… cycle_id=…"` (collapsed single argv; #1946) |
| session launch | `:1849` | `_claude_cmd=("$CLAUDE_BIN" --print …)` |
| #1446 breaker (commented) | `:2090-2155` | `# ── DISABLED 2026-09-01 (operator request)` |
| post-cycle bookkeeping | `:2157` | |
| #1446 live auto-close half | `:2181-2202` | |
| audit-log sync call | `:2234` | `_sync_audit_logs "$REPO_ROOT"` |

Everything the gate needs is defined before `:366`: `ROLE`, `PROJECT`, `_HOS_CRON_DIR`, `REPO_ROOT` (for `_audit`), `LOG_PREFIX`, `_HOS_DIR`, `HOS_CYCLE_ID`, the pinned `PATH` and `set -euo pipefail`. Nothing in `:334-366` that the gate needs is missing. A missing `python3` surfaces as `check_error` (pause, §4.4).

**TD-VF-15 — every §3.3 regex was run against capture 2's `result`** (scratch script; fixture §1.9.2, 1621 bytes, 26 lines, sha256 `c72987a8fda5a146cf30b1ca31d0a19b33423d20b4ee58432773b06f250b4de5`):
- `session=11` (resets `Oct 3, 2:40am (UTC)`), `weekly_all=1`, models `[all models → excluded, Fable=0]`, marker present, three `% used` lines.
- `24h`: `2290/175`, behaviors `67/41/30`, top `technical-design 10, architect 6, pm-agent 2, coder 1`, more `0`.
- `7d`: `13401/1433`, subagent-heavy `49`, long-context `29`, **long-session absent** (no `8+ hours` line), top list of 8 items, more `1`.
- `total_cost_usd=0`; the four token fields sum to `0`.
- `result` carries U+00B7 seven times and U+2014 once, raw UTF-8 in the file (not `\u` escapes).

**TD-VF-16 — two scheduled `hos-cron` copies on faberix today.** The live user crontab runs `…/Worker/bin/hos-cron --role worker` and `…/Overseer/bin/hos-cron --role overseer` (two different files). `docs/CRON-SETUP.md:136-141` shows the `$HOME/…/bin/hos-cron` form. The `--check` sentinel item (§3.10 item 8) therefore must expand `$HOME`/`${HOME}`/leading `~/` and must check each distinct file. This is the concrete D7b case: the overseer copy pauses only if the Overseer clone also carries the gate. The leftover `/tmp/diagnose_claude_usage_tty.sh` entry is currently commented out (crontab line 76); its removal stays a human action (H-6).

**TD-VF-17 — Grafana provisioning interpolates `$` in every provisioning file.** Grafana expands `$VAR`/`${VAR}` from the environment in provisioning YAML, and a literal `$` must be written `$$`. Two consequences:
- Alert-annotation templates must write `{{ $$labels.instance }}`, not `{{ $labels.instance }}` (§6.3). Verified from Grafana's documented behavior, not on monitrix: added to the A2-21 verification list (§6.9).
- A2-13's `HosClaudeUsageMetricsAbsent` condition `absent(…{instance=~"$instance"})` cannot work in an alert rule: alert rules have no dashboard variables, and `$instance` would be env-expanded to an empty string. Raised as **TD-O-12**.

**TD-VF-18 — paused-cycle audit records are not synced until the next running cycle.** `_audit` writes under `REPO_ROOT/audit/log/` (`cycle_log.py:57-66`), and the only push is `_sync_audit_logs` at `:2234`, which a paused cycle never reaches. During a long pause, records accumulate in the clone. Informational, **TD-O-18**.

**TD-VF-19 — protected-surface edits come in threes.** `scripts/framework/protected_surfaces.txt` (header) must stay in sync with `docs/AGENT-IDENTITY.md` §9.0 and the generated `.github/CODEOWNERS` (`tests/framework/test_codeowners_current.py`). ~~S4's `contrib/monitoring/**` entry (A2-14, pending H-2) therefore edits all three.~~ **Human rulings H-1..H-4, H-7:** H-2 is rejected, so #1944 edits none of the three (ADR A4-2). The finding stands as a fact about the repo.

**TD-VF-20 — `cycle_log.log_event` defaults `role` to `"worker"`** (`cycle_log.py:58-62`) and overrides it from kwargs. Every usage-pause event must pass `role=$ROLE` explicitly or overseer events are mislabelled.

### Verification gaps I could not close (Revision 2)

- Symlink-follow in faberix's textfile collector (root probe, §5.1; gates S3 coding).
- The A2-21 Grafana gaps, extended (§6.9).
- Whether monitrix's node_exporter is scraped and follows symlinks (A2-21 #2; gates S5).
- The full unfiltered envelope (D-4, AC-49): S1 exit.
- The real JSON empty-session envelope (A2-21 #3): synthetic fixtures stand in.

---

## 1. Canonical names, grammars and formats (binding — nothing below may re-spell these)

### 1.1 Paths — Revision 2 (ADR A2)

`$STATE` = `${HOS_STATE_DIR:-$HOME/.hos}`. The poller resolves it itself. The gate passes `--state-dir "$_HOS_DIR"` (the same expression, `hos-cron:247`), so both always agree. If an operator set `HOS_STATE_DIR` on the `hos-cron` crontab lines but not on the poller's, the gate would see `reading_missing` and pause: safe direction, documented in §3.13.
`HOS_USAGE_PAUSE_CONF`, `HOS_USAGE_PROM_PATH` and `HOS_USAGE_KEY_PATH` are **test-only overrides**, named only in the module docstring and the tests (static test S1-ST7).

| Path | Writer | Readers | Notes |
|---|---|---|---|
| `$STATE/usage-pause/` | poller (creates, mode 0700) | — | **`hos-cron` creates and writes nothing here** (A2-2) |
| `$STATE/usage-pause/reading` | poller only | gate (`check`), `--check`, `write-prom` | §1.3 |
| `$STATE/usage-pause/reading.tmp` | poller | — | transient, fixed name |
| `$STATE/usage-pause/last-raw` (+ `last-raw.tmp`) | poller | human | §1.6, S1 |
| `$STATE/usage-pause/history/usage-YYYY-MM-DD.jsonl` | poller | `export`, human | dir 0700, files 0600; §5.4, S3 |
| `$STATE/usage-pause/poll.stdout.tmp`, `poll.stderr.tmp` | poller | `poll-record`, `last-raw` | deleted at the end of every poll |
| `$STATE/usage-pause/poll.last.log` | the crontab `>` redirect | human | FR-34 |
| `$STATE/locks/usage-poll.lock/` | poller | poller | mkdir lock, 600 s ceiling |
| `$HOME/.config/hos/usage-pause.conf` | human | poller, gate, `--check` | literal `$HOME`, never `HOS_CONFIG_DIR` (VF-4) |
| `$HOME/.ssh/hos_loopback{,.pub}` | human | ssh (`-i`), `--check` | |
| `/var/lib/hos-usage/hos_claude_usage.prom` (+ `.hos_claude_usage.prom.tmp`) | poller (S3) | node_exporter via symlink | §5 |

~~`<role>-<project>.status`, `check-error-…flag`, `issue-body-…md`, `locks/usage-pause-issue-…lock`~~ **Removed by Revision 2 (ADR A2-2, A2-5).**

**Directory bound (AC-13).** After any number of polls and cycles, `$STATE/usage-pause/` holds only `reading`, `last-raw`, `poll.last.log` and `history/`. `history/` holds only `usage-YYYY-MM-DD.jsonl` files within the §5.4 caps. No `*.tmp` survives a completed poll.

### 1.2 Enums and reason vocabulary — Revision 2 (ADR A2)

**Read-failure reasons** (A2-7; closed and stable; `reason=` in the reading file and the `reason` label of `hos_claude_usage_read_failure`). Exactly nine:
`ssh_failed`, `timeout`, `spawn_failed`, `envelope_invalid`, `empty_session`, `missing_session`, `missing_weekly`, `unparseable`, `crashed`.
- `claude_not_executable` is **not** a poll-time reason; it is `--check` item 6 only (A2-7).
- `lock_stale_reclaimed` stays a `diagnostics` value, never a reason (TD-O-11, unchanged).

**Reading-unusable reasons** (gate side, AD-7 step 2). Exactly seven:
`poller_not_installed`, `reading_missing`, `reading_truncated`, `schema_unknown`, `reading_unreadable`, `reading_stale`, `reading_future`.
*Revision 2:* Revision 1's `status_*` tokens are renamed `reading_*` to match the renamed file and A2-15's `reading_missing`. `schema_unknown` keeps its AD-2 name (TD-O-15).

**Limit names** (A2-6): `session`, `weekly_all`, `weekly_model:<Name>`.

**Decision classes and reasons** (the gate's verdict, §4.3):

| class | decision | `reason` text (≤ 200 chars) |
|---|---|---|
| `ok` | run | summary: `session 11% < 90, weekly_all 1% < 90, weekly_model:Fable 0% < 90 (reading age 42s)` |
| `limit` | pause | A2-6 format, e.g. `weekly_model:Fable 91% >= 90`; several joined by `; ` in the order session, `weekly_all`, then `weekly_model:<Name>` sorted by name |
| `read_failed` | pause (closed) | `read_failed:<read-failure reason>`; an unknown stored reason becomes `read_failed:unknown` |
| `reading_unusable` | pause (closed) | the reading-unusable reason |
| `settings_invalid` | pause (any fail mode) | `settings_invalid:<key>` |
| `failopen` | run (open) | the `read_failed:<r>` or reading-unusable reason |
| (bash) `check_error` | pause (any fail mode) | `check_error` |

Each limit token is `<limit> <pct>% >= <threshold>` on pause and `<limit> <pct>% < <threshold>` in the OK summary. `<Name>` is the raw model name with control characters stripped and capped at 64 characters. **In the verdict line, log line and audit event, any non-ASCII character in `<Name>` is replaced by `?`** (TD-O-14); the reading file keeps the raw name.

`<key>` (settings) is one of the ten A2-10 keys, a sanitized unknown key (`[a-z0-9_]`, ≤ 40 characters), `line_<n>` for a malformed line, or `file_unreadable`.

### 1.3 Reading file — `$STATE/usage-pause/reading` (poller-written only) — Revision 2 (ADR A2)

**Framing (unchanged from Revision 1):** UTF-8, LF, every line `key=value`, keys `^[a-z0-9_]+$`, no characters `< 0x20` or `0x7f` in values, leading and trailing whitespace stripped. Caps: `detail` and `poll_pause_reason` ≤ 200; `*_resets` and `*_name` ≤ 100; every other value ≤ 200. **Line 1 is exactly `schema=1`; the last line is exactly `end=1` followed by `\n`.** Each key at most once. Absent values are **omitted**, never written empty or `0` (FR-44, AC-4).

Key order (absent keys skipped; one key per line in the real file):

```
schema=1
kind=reading
run_at=<UTC ISO-8601 YYYY-MM-DDTHH:MM:SSZ>
run_epoch=<int>
outcome=success|failure|crashed
reason=<read-failure reason>                  # outcome≠success only
detail=<sanitized, ≤200>                      # outcome≠success only
diagnostics=lock_stale_reclaimed              # only when it happened
remote_exit=<int>                             # only when ssh exited (any code)
parsed_via=grep                               # success only
subscription_marker=present|absent            # envelope parsed only
session_pct=<int>                             # success only
session_resets=<raw text>                     # success, when matched
weekly_all_pct=<int>                          # success only
weekly_all_resets=<raw text>
weekly_model_<slug>_name=<raw name, control-stripped, ≤64>   # success; per model line, source order
weekly_model_<slug>_pct=<int>
weekly_model_<slug>_resets=<raw text>
requests_<w>=<int>                            # success; per window <w>, source order; each line optional
sessions_<w>=<int>
subagent_heavy_pct_<w>=<int>
long_context_pct_<w>=<int>
long_session_pct_<w>=<int>
top_subagents_<w>=<name>=<pct>,<name>=<pct>,…  # source order
top_subagents_more_<w>=<int>                  # 0 = top line parsed with no "+K more"
cost_usd=<decimal>                            # envelope parsed and value valid (§3.2), success OR failure
input_tokens=<int>                            # same rule, each field independently
output_tokens=<int>
cache_creation_input_tokens=<int>
cache_read_input_tokens=<int>
read_tokens=<int>                             # only when all four token fields are present
consecutive_failures=<int>
last_success_epoch=<int>                      # absent = never succeeded
poll_settings_status=valid|defaults|invalid:<key>     # informational (A2-3)
poll_fail_mode=closed|open                            # in-force at poll time (default when invalid)
poll_session_threshold=<int>                          # only when poll_settings_status ∈ {valid, defaults}
poll_weekly_threshold=<int>                           # same
poll_weekly_model_threshold=<int>                     # same
poll_staleness_seconds=<int>                          # always (default when invalid; A2-12)
poll_pause_condition=0|1                              # informational (A2-3)
poll_pause_reason=<decision reason text, ≤200>        # informational
end=1
```

- `<slug>` (model): lowercase, `[^a-z0-9]+` → `_`, strip `_`, cap 32; an empty slug skips the line; a duplicate slug keeps the last line.
- `<w>` (window, A2-7 generic): the header's window label lowercased, `[^a-z0-9]+` → `_`, strip `_`, cap 16; an empty slug skips the block. At most **8 windows**; further windows are ignored (cardinality bound).
- **Per-model, breakdown and `parsed_via` keys are written only on `outcome=success`** (AC-4: no artifact records 0% for a failed read). Cost and token keys are written whenever the envelope parsed, **including on failure** (A2-8).
- **`poll_*` keys are the poller's informational view (A2-3). `usage_pause.py check` never reads any `poll_*` key** (static test S2-ST8, behavior test `test_check_ignores_poll_view`).
- ~~`settings_status`, `machine_decision`, `machine_decision_reason`~~ **Removed by Revision 2:** replaced by `poll_settings_status`, `poll_pause_condition`, `poll_pause_reason` (A2-3).

**Carry-over (unchanged).** "Previous" is the existing `reading` when `read_reading()` returns `ok`.
- `consecutive_failures`: success → `0`; failure or crash → previous + 1, or `1` when the previous file is not `ok` or lacks the key.
- `last_success_epoch`: success → `run_epoch`; failure → the previous value if present, else omitted.

**Bash crash fallback (§3.7 P12).** A minimal file with only `schema`, `kind`, `run_at`, `run_epoch`, `outcome=crashed`, `reason=crashed`, `detail`, `end`. No `.prom`, history or `last-raw` step runs after a bash fallback: the `.prom` freezes, so `HosClaudeUsagePollStale` fires (§6.3).

### 1.4 ~~Per-role/project status file~~ — Removed by Revision 2 (ADR A2-2, D6)

There is no per-role or per-project status file. `hos-cron` keeps no state of its own for this feature.

### 1.5 Write discipline (unchanged; applies to `reading`, `last-raw` and the `.prom`)

1. Render the full content in memory.
2. Open `<file>.tmp` (same directory) `O_WRONLY|O_CREAT|O_TRUNC`, mode `0600` (`0644` for the `.prom`). Write, flush, `fsync`, close.
3. `os.replace(<file>.tmp, <file>)`, then best-effort directory `fsync`.

The bash crash fallback follows the same steps with `printf … > <file>.tmp; mv -f`. **No writer ever appends, except the history writer** (one `O_APPEND` write per poll, §5.4).

### 1.6 `last-raw` — Revision 2 (ADR A2-11; S1)

`$STATE/usage-pause/last-raw`, mode 0600, overwritten every poll in which P6 ran (§1.5). Content:
- line 1: `# hos-usage-poll last-raw run_epoch=<int> read=<exited|timeout|spawn_failed> rc=<int|-> stream=<stdout|stderr> bytes=<int>`;
- then the raw bytes, capped at 65536.

`stream=stdout` (the full raw stdout) when `read=exited`; `stream=stderr` (the stderr tail: the **last** 65536 bytes) on `timeout`, `spawn_failed`, or `exited` with `rc=255`. Nothing reads `last-raw` for a decision. **AC-40 is asserted on the bytes after line 1** (TD-O-16).

**Architect round 2 (A2-11 "overwritten each poll").** A poll that wrote a reading but never reached P6 (P4 or P5 refusal) still overwrites `last-raw`, with the header only: `read=none rc=- stream=none bytes=0`. The header grammar's `read` and `stream` sets gain `none`. *Reason:* in Revision 2 a key-missing poll left the previous poll's raw output in place, so an operator debugging `read_failed:ssh_failed` would read an unrelated, older capture. A lock-held exit (P3) is not a poll and writes nothing. Test: `test_last_raw_no_read_header_only`.

### 1.7 Audit events — Revision 2 (ADR A2-5)

~~Transition events `cycle-usage-pause`, `cycle-usage-resume`, `cycle-usage-degraded`~~ **Removed by Revision 2.**

| Event | Emitted by | When | argv, **one `key=value` per element**, in this order |
|---|---|---|---|
| `cycle-usage-paused` | gate | every paused cycle, including `check_error` | `role=$ROLE` `project=$PROJECT` `cycle_id=$HOS_CYCLE_ID` `reason=<reason text>` `session_pct=<n\|->` `weekly_all_pct=<n\|->` `reading_age_s=<n\|->` `fail_mode=<closed\|open\|->` `settings=<valid\|defaults\|invalid:<key>\|->` |
| `cycle-usage-unchecked` | gate | **Human rulings H-1..H-4, H-7 (H-1 confirmed, ADR A4-1):** every cycle whose verdict is `class=failopen` (fail-open, runs without a usable successful reading). Never on `class=ok`. No block, no issue. | same fields, same order, one `key=value` per argument (incl. `project`, `cycle_id`) |

- `project` and `cycle_id` are additive to A2-5's field list (TD-O-21).
- `-` means "unknown"; `cycle_log` stores it as the string `"-"`.
- No usage event on a `class=ok` running cycle; the existing `cycle-start` (`:1823`) records it. A `failopen` cycle's `cycle-usage-unchecked` is written before audit-log sync and pushed by that same cycle. Resume is visible as a `cycle-start` with no preceding `cycle-usage-paused` (A2-5).
- The poller emits no audit (FR-34). **No decision reads an audit event.**

### 1.8 Settings — `$HOME/.config/hos/usage-pause.conf` — Revision 2 (ADR A2-10)

**Grammar (unchanged).** Parsed, never sourced. Missing (`ENOENT` only) → defaults, `poll_settings_status=defaults`. Any other open/read error, a directory, size > 64 KiB, or invalid UTF-8 → `invalid:file_unreadable`. Strip one trailing `\r`; after stripping whitespace, empty and `#`-leading lines are ignored. Every other line must match `^([a-z_]+)=(.*)$` (value right-stripped; no inline comments, quotes or expansion), else `invalid:line_<n>`. Unknown key → `invalid:<key>`; duplicate key → `invalid:<key>`. Integers match `^(0|[1-9][0-9]*)$`, ASCII only.

| Key | Default | Valid |
|---|---|---|
| `session_threshold` | 90 | integer 1–100 |
| `weekly_threshold` | 90 | integer 1–100 |
| `weekly_model_threshold` | 90 | integer 1–100 (new, D1) |
| `fail_mode` | `closed` | exactly `closed` \| `open` |
| `poll_interval_seconds` | 300 | integer multiple of 60, 60–3600 |
| `staleness_seconds` | 900 | integer `> poll_interval_seconds + read_timeout_seconds` and `≤ 7200` (A1-4) |
| `read_timeout_seconds` | 60 | integer 5 to `poll_interval_seconds − 30` |
| `history_days` | 90 | integer 1–3650 (new, D18) |
| `history_max_mb` | 100 | integer 1–10240 (new, D18); 1 MB = 1,048,576 bytes |
| `claude_bin` | unset → resolved | `^/[A-Za-z0-9._+/-]{1,254}$`, no `/./` or `/../` segment, not ending in `/`; used only by `remote-cmd`, `--print-setup`, `--check` |

- **Removed:** `failopen_issue_after`. A conf still carrying it pauses with `settings_invalid:failopen_issue_after` (A2-10).
- **Cross-field checks** run after the per-key checks, using in-file values or defaults: `read_timeout_seconds`, then `staleness_seconds`. The failing key is named. Report the **first** violation only, in file-line order, cross-field violations last.
- **Under invalid settings** the gate pauses with `settings_invalid:<key>` regardless of `fail_mode` (D4). That includes the history keys (H-5). The poller keeps polling with **defaults for its operational keys only** (`read_timeout_seconds`, `history_days`, `history_max_mb`), writes `poll_settings_status=invalid:<key>`, `poll_pause_condition=1`, `poll_staleness_seconds=<default>`, and no `poll_*_threshold` keys.
- `claude_bin` resolution when unset: `shutil.which("claude")` against the poller's pinned PATH.

**The single defaults constant block (binding, A2-10/D19).** At the top of `bin/lib/usage_pause.py`, between the exact comment lines `# ── BEGIN SETTINGS DEFAULTS AND BOUNDS (ADR-1944 A2-10; the only place these numbers appear) ──` and `# ── END SETTINGS DEFAULTS AND BOUNDS ──`, the module defines, and nowhere else spells:
- `DEFAULT_SESSION_THRESHOLD = 90`, `DEFAULT_WEEKLY_THRESHOLD = 90`, `DEFAULT_WEEKLY_MODEL_THRESHOLD = 90`, `DEFAULT_FAIL_MODE = "closed"`, `DEFAULT_POLL_INTERVAL_SECONDS = 300`, `DEFAULT_STALENESS_SECONDS = 900`, `DEFAULT_READ_TIMEOUT_SECONDS = 60`, `DEFAULT_HISTORY_DAYS = 90`, `DEFAULT_HISTORY_MAX_MB = 100`;
- the bounds: `THRESHOLD_MIN = 1`, `THRESHOLD_MAX = 100`, `POLL_INTERVAL_MIN = 60`, `POLL_INTERVAL_MAX = 3600`, `POLL_INTERVAL_STEP = 60`, `STALENESS_MAX = 7200`, `READ_TIMEOUT_MIN = 5`, `READ_TIMEOUT_MARGIN = 30`, `HISTORY_DAYS_MIN = 1`, `HISTORY_DAYS_MAX = 3650`, `HISTORY_MAX_MB_MIN = 1`, `HISTORY_MAX_MB_MAX = 10240`;
- `DEFAULTS: Mapping[str, int|str|None]`, built from the names above (`claude_bin: None`).

Static test S1-ST10 (AC-45 for code): (a) the block markers appear exactly once each; (b) **no `ast.Compare` node anywhere in the module has a numeric `Constant` operand other than `0` or `1`** — every other number used in a comparison must be a named module-level constant; (c) **(Architect round 2, replaces the Revision 2 wording)** inside any function or class body, no numeric `Constant` equals `90`, `300`, `900`, `60` or `100`. Outside the block, those values may appear only as the whole right-hand side of a module-level `UPPER_CASE = <int>` assignment whose name does not start with `DEFAULT_` (e.g. `RESETS_CAP_CHARS = 100`, which §1.3's `*_resets ≤ 100` cap needs). *Reason:* the Revision 2 wording banned every `100` outside the block, so the §1.3 format caps could not be named at all; the test would have pushed format caps into the settings block. D19 targets thresholds, and (b) already enforces it for comparisons.

### 1.9 Fixtures (byte-exact) — Revision 2 (ADR A2) adds §1.9.2 and §1.9.4

#### 1.9.1 The D-1 capture (unchanged; plain text, now used as a `result` value)

Provenance: SSH loopback on faberix, 2026-10-02, relayed by the coordinator. 1091 bytes, 20 lines, trailing LF, no CR, sha256 `c8d52b0ace496176dded36c78b13b587a2c378cd9d2f6a5acbfdf63266196683`. `·` is U+00B7 (lines 3, 4, 5, 10, 16); `—` on line 8 is U+2014; lines 2, 6, 9, 15 empty; lines 11–14 and 17–20 start with two spaces.

```
You are currently using your subscription to power your Claude Code usage

Current session: 6% used · resets Oct 3, 2:40am (UTC)
Current week (all models): 48% used · resets Oct 3, 12am (UTC)
Current week (Fable): 3% used · resets Oct 3, 12am (UTC)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine — does not include other devices or claude.ai. Behaviors are independent characteristics, not a breakdown.

Last 24h · 2049 requests · 181 sessions
  61% of your usage came from subagent-heavy sessions
  36% of your usage was at >150k context
  34% of your usage came from sessions active for 8+ hours
  Top subagents: technical-design 6%, architect 3%, pm-agent 2%, coder 1%

Last 7d · 13242 requests · 1442 sessions
  48% of your usage came from subagent-heavy sessions
  28% of your usage was at >150k context
  10% of your usage came from sessions active for 8+ hours
  Top subagents: coder 14%, technical-design 3%, architect 2%, code-reviewer 2%, unit-test 1%, general-purpose 1%, oversight-evaluator 1%, risk-assessor 1%, +2 more
```

Under Revision 2 the poll path parses a JSON envelope, so D-1 is used through a **derived** fixture, `d1-envelope-derived.json`: `{"result": <the 1091-byte text above, without its final LF>, "total_cost_usd": 0, "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}`, written by `json.dumps(…, ensure_ascii=False, indent=2) + "\n"`. Its `README.md` row records that derivation.

#### 1.9.2 Capture 2 — the second real capture, JSON envelope (new, D13)

Provenance: captured by the human on 2026-10-03 on faberix (personal login, direct terminal) with `claude -p "/usage" --output-format json | jq '{result, total_cost_usd, usage}'`. Relayed as `usage-sample-2-json.txt`; the fixture is that file's JSON body (its lines 6–31). **It is jq-filtered:** fields outside `result`, `total_cost_usd` and `usage` are not present, and jq re-indented the output (2 spaces). The **full, unfiltered envelope is captured by the first real `bin/hos-usage-poll --check --capture-fixture <path>` run** (§3.10, AC-49, S1 exit) and committed by a later PR.

Fixture file `capture2-envelope-2026-10-03.json`: 1621 bytes, 26 lines, LF only, final LF, sha256 `c72987a8fda5a146cf30b1ca31d0a19b33423d20b4ee58432773b06f250b4de5`. `·` (U+00B7, 7 occurrences) and `—` (U+2014, 1) are raw UTF-8 inside the `result` string; line breaks inside `result` are JSON `\n` escapes. Notable: the `Last 7d` window has **no** `8+ hours` line (every breakdown line is individually optional; that series is absent, not 0).

```json
{
  "result": "You are currently using your subscription to power your Claude Code usage\n\nCurrent session: 11% used · resets Oct 3, 2:40am (UTC)\nCurrent week (all models): 1% used · resets Oct 10, 12am (UTC)\nCurrent week (Fable): 0% used · resets Oct 10, 12am (UTC)\n\nWhat's contributing to your limits usage?\nApproximate, based on local sessions on this machine — does not include other devices or claude.ai. Behaviors are independent characteristics, not a breakdown.\n\nLast 24h · 2290 requests · 175 sessions\n  67% of your usage came from subagent-heavy sessions\n  41% of your usage was at >150k context\n  30% of your usage came from sessions active for 8+ hours\n  Top subagents: technical-design 10%, architect 6%, pm-agent 2%, coder 1%\n\nLast 7d · 13401 requests · 1433 sessions\n  49% of your usage came from subagent-heavy sessions\n  29% of your usage was at >150k context\n  Top subagents: coder 13%, technical-design 4%, architect 3%, code-reviewer 2%, unit-test 1%, oversight-evaluator 1%, risk-assessor 1%, pm-agent 1%, +1 more",
  "total_cost_usd": 0,
  "usage": {
    "output_tokens_details": {
      "thinking_tokens": 0
    },
    "input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 0,
    "server_tool_use": {
      "web_search_requests": 0,
      "web_fetch_requests": 0
    },
    "service_tier": "standard",
    "cache_creation": {
      "ephemeral_1h_input_tokens": 0,
      "ephemeral_5m_input_tokens": 0
    },
    "inference_geo": "",
    "iterations": [],
    "speed": "standard",
    "fallback_credit": null
  }
}
```

#### 1.9.3 Empty-session plain text (unchanged; PR #1450 2026-08-17T07:48:32Z, Test 1)

Five lines, each ending in LF, 207 bytes, sha256 `f14701ef896ab3a117bcf623c9ba55b80054f3daa4b524f366154fdf26339d14`:

```
Total cost:            $0.0000
Total duration (API):  0s
Total duration (wall): 1s
Total code changes:    0 lines added, 0 lines removed
Usage:                 0 input, 0 output, 0 cache read, 0 cache write
```

#### 1.9.4 Synthetic JSON empty-session envelopes (new; A2-7, A2-21 #3)

Until a real one is captured, two synthetic fixtures stand in. Both carry `"total_cost_usd": 0` and the four token fields at `0`:
- `empty-session-envelope-blank.json`: `"result": ""`;
- `empty-session-envelope-legacy-text.json`: `"result"` = the §1.9.3 text.

Each must classify `empty_session`, and AC-4's "cost 0 is not success" is asserted on both.

---

## 2. Component map — Revision 2 (ADR A2)

| # | Path | New/changed | Purpose | Slice | Protected? |
|---|---|---|---|---|---|
| A | `bin/lib/usage_pause.py` | new | envelope + text parser, settings, reading I/O, decision (`evaluate_cycle`), CLI (S1); `check` (S2); `render_prom`, history, prune, `export` (S3). Python 3, **stdlib only**, 3.9-compatible syntax (`from __future__ import annotations`, no `match`) | S1, S2, S3 | yes (`bin/**`) |
| B | `bin/hos-usage-poll` | new, `+x` | cron entry point: poll, `--check [--capture-fixture <path>]`, `--print-setup`, `remote-cmd`, `export`, `--help` | S1, S3 | yes |
| C | `bin/hos-cron` | changed | §4 gate block (sentinel included) + one header paragraph | S2 | yes |
| D | `scripts/framework/framework_consumer_files.txt` | changed | add `bin/hos-usage-poll`, `bin/lib/usage_pause.py` under the `bin/` heading (`:19-22`) | S1 | yes |
| E | `bootstrap/hos_install.sh` | changed | post-install summary prints one §2a pointer line (provisions nothing, FR-47) | S1 | yes |
| F | `tests/framework/test_agent_invocation_migration.py` | changed | T4.1b (A2-9); T4.1 exemption set unchanged (S1 code-review round 1 (S5), §11.5 C-10); T4.2 unchanged | S1 | no |
| G | `tests/automation/fixtures/usage/` | new | §1.9 fixtures + `README.md` provenance (S3 adds golden `.prom` and history fixtures) | S1, S3 | no |
| H | `tests/automation/test_usage_pause_{envelope,parse,settings,reading,decision}.py` | new | units | S1 | no |
| I | `tests/automation/test_hos_usage_poll.py` | new | poller integration (stub ssh/crontab) | S1, S3 | no |
| J | `tests/framework/test_usage_pause_static.py` | new | static guards | S1, S2, S3 | no |
| K | `tests/framework/test_consumer_framework_files.py` | changed | assert D | S1 | no |
| L | `docs/CRON-SETUP.md` | changed | new §2a; §7 rows | S1, S2, S3 | no |
| M | `docs/MACHINE-ACCOUNTS-SETUP.md` | changed | one-line pointer to §2a | S1 | no |
| N | `SCRIPTS-INDEX.md` | regenerated | `scripts/framework/regen_all.sh` | S1, S4 | no |
| O | `tests/automation/test_usage_pause_check_cli.py` | new | `check` verdict | S2 | no |
| P | `tests/automation/test_hos_cron.py` | changed | §4.7 harness + `TestUsagePauseGate` | S2 | no |
| Q | `docs/UPGRADE-PR-REVIEW-CHECKLIST.md` | changed | new §H "Usage-pause gate (#1944)" | S2 | no |
| Q2 | `docs/releases/v0.7.0.md` | changed/created | "Upgrade notes" paragraph (TD-O-19) | S2 | yes (`docs/releases/**`) |
| R | `tests/automation/test_usage_pause_{prom,history,export}.py` | new | render, history, prune, export | S3 | no |
| S | `contrib/monitoring/**` | new | §6 layout: dashboards, provisioning, alert rules, contact point, monitrix sync script, reload script and units, README | S4 | **no** (H-2 rejected; ADR A4-2) |
| T2 | `tests/framework/test_monitoring_required_alerts.py` | new | required-alert guard (§9.4a; H-2 replacement control, ADR A4-3) | S4 | no |
| T3 | `tests/framework/test_grafana_alerting_reload.py` | new | reload script and units (§6.6; H-3) | S4 | no |
| S2' | `docs/MONITORING-WORKED-EXAMPLE.md` | new | "recommended setup" doc (§6.8) | S4 | no |
| T | `tests/framework/test_contrib_monitoring.py`, `tests/framework/test_monitoring_sync.py` | new | structure, PromQL, no-literal, no-secret, sync behavior | S4 | no |
| ~~U~~ | ~~`scripts/framework/protected_surfaces.txt`, `docs/AGENT-IDENTITY.md` §9.0, `.github/CODEOWNERS`~~ | **not changed** | **Human rulings H-1..H-4, H-7:** H-2 rejected; no protected-surface entry is added (ADR A4-2) | — | — |

~~`docs/LABELS.md` writer row~~ **Removed by Revision 2 (ADR A2-5):** the gate writes no label.

Not touched by any slice: `bin/hos-suspend`, the #1446 breaker block and auto-close half (`:2090-2155`, `:2181-2202`), `TestUsageLimitBreaker` (stays `@skip`), every existing dedup site (#1946), `prometheus.yml` on monitrix (A2-13).

---

## 3. S1 — poller read path, parser, settings, reading file, `last-raw`, runbook — Revision 2 (ADR A2)

### 3.1 `bin/lib/usage_pause.py` — module API (S1 part)

No function on the decision path raises; every failure is a value. Only the CLI wrappers and the named I/O helpers do I/O.

```text
SCHEMA_VERSION: int = 1
READ_FAILURE_REASONS: frozenset[str]       # §1.2, exactly nine
UNUSABLE_REASONS: frozenset[str]           # §1.2, exactly seven
GATE_SENTINEL: str = "# HOS-USAGE-PAUSE-GATE schema=1"     # §4.2; used by --check item 8
REMOTE_CMD_TEMPLATE: str = "{claude_bin} -p /usage --output-format json"
    # One code line, trailing comment exactly
    # "# ADR-1944 A2-9: forced-command template; executed by sshd, never by HOS (T4.1b)".
    # The single source for remote-cmd, --print-setup, and --check item 2. Never executed by HOS.
    # The exact line, with "# noqa: E501" placed before that comment: §11.5 C-9.
SSH_OPTIONS: tuple[str, ...]               # AD-6's -o list, verbatim, in AD-6 order
KILL_GRACE_SECONDS: int = 5
INPUT_CAP_BYTES: int = 65536
HISTORY_LINE_CAP_BYTES: int = 16384
MAX_WINDOWS: int = 8
STALE_FUTURE_TOLERANCE_SECONDS: int = 120
CHECK_READ_KEYS: frozenset[str]            # the only reading keys check may read (§4.3); none start with "poll_"
(the §1.8 defaults-and-bounds block)

read_usage(*, key_path: Path, timeout_s: int, stdout_path: Path, stderr_path: Path) -> ReadOutcome
    argv = ["ssh", "-n", "-i", str(key_path), *SSH_OPTIONS, "127.0.0.1"]
        # A2-9: NO remote command after the host. sshd runs the forced command.
    Popen(argv, stdin=DEVNULL, stdout=<fh>, stderr=<fh>, start_new_session=True)
        # env NOT passed: the child inherits the poller's environment unchanged (A2-9, D5).
    wait(timeout_s); on TimeoutExpired: killpg SIGTERM, wait(KILL_GRACE_SECONDS), then killpg SIGKILL, wait().
    ReadOutcome(kind: "exited"|"timeout"|"spawn_failed", rc: int|None, detail: str|None); OSError from Popen → spawn_failed.
remote_cmd(claude_bin: str) -> str          # REMOTE_CMD_TEMPLATE.format(...)
decode_result_text(s: str) -> str           # ANSI (OSC, CSI) stripped, '\r' deleted; locale-independent
parse_envelope(raw: bytes) -> EnvelopeResult        # §3.2; never raises
parse_usage(text: str) -> ParseResult               # §3.3–3.4; never raises
classify_transport(outcome: ReadOutcome) -> str | None   # §3.4
load_settings(path: Path) -> SettingsResult         # §1.8; never raises
read_reading(path: Path) -> ReadingRead             # §3.6; never raises
evaluate_cycle(reading: ReadingRead, settings: SettingsResult, now: float, *,
               poller_artifacts_present: bool) -> Decision     # §3.6; pure; the ONLY decision rule
build_reading(...) -> list[tuple[str, str]]         # §1.3 order, incl. the poll_* view (§3.7 P7)
render_reading(fields) -> str                        # framing, sanitizing, ordering
write_atomic(path: Path, data: bytes, mode: int) -> None   # raises OSError only; §1.5
main(argv: list[str]) -> int
```

Data types (frozen dataclasses):
- `EnvelopeResult(ok: bool, reason: str|None, result_text: str|None, cost_usd: float|None, tokens: Mapping[str,int]` (only the valid ones of the four)`, read_tokens: int|None)`.
- `ParseResult(ok, reason, session_pct, session_resets, weekly_all_pct, weekly_all_resets, models: tuple[ModelWeekly, ...], windows: tuple[WindowBreakdown, ...], subscription_marker)`; `ok ⇔ reason is None`; `models` and `windows` populated only when `ok`.
- `ModelWeekly(name: str, slug: str, pct: int, resets: str|None)`.
- `WindowBreakdown(window_label: str, slug: str, requests: int|None, sessions: int|None, subagent_heavy_pct: int|None, long_context_pct: int|None, long_session_pct: int|None, top_subagents: tuple[tuple[str,int],...]|None, top_subagents_more: int|None)`.
- `SettingsResult(values: Mapping[str, int|str|None], status: str, invalid_key: str|None, invalid_value: str|None)`; `status ∈ {"valid", "defaults", "invalid:<key>"}`; `values` always complete (file values when valid, defaults otherwise).
- `ReadingRead(state: str, fields: Mapping[str,str])`; `state ∈ {ok, missing, truncated, schema_unknown, unreadable}`.
- `Decision(decision: "run"|"pause", klass: str, reason: str, session_pct: int|None, weekly_all_pct: int|None, reading_age_s: int|None, fail_mode: str, settings: str, unchecked: bool)`.

### 3.2 JSON envelope parsing — Revision 2 (ADR A2-7, A2-8, D13)

`parse_envelope(raw)`:
1. `raw[:INPUT_CAP_BYTES]`, decoded UTF-8 with `errors="replace"`. An over-cap stdout is therefore truncated JSON and fails at step 2. Never scan for a JSON fragment inside other text.
2. `json.loads(text, object_pairs_hook=<hook>, parse_constant=<reject>)`. The hook raises on a duplicate key among `result`, `total_cost_usd`, `usage`, and the four token keys inside `usage` (other duplicates are ignored, since those fields are never read). `NaN`/`Infinity` are rejected. Any exception → `envelope_invalid`.
3. The top level must be a JSON object, else `envelope_invalid`.
4. `result` must be present and a `str`, else `envelope_invalid`. `result_text = decode_result_text(result)`.
5. **Read exactly these fields and nothing else:** `result`, `total_cost_usd`, `usage.input_tokens`, `usage.output_tokens`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`. Every other field, including `usage.output_tokens_details.thinking_tokens`, is ignored. Adding or removing any other field changes nothing (AC-49).
6. **Cost:** `total_cost_usd` must be an `int` or `float` (not `bool`), finite and `>= 0`. Otherwise `cost_usd` is absent. Rendered in the reading as the shortest round-trip decimal (`repr(float(v))` with a trailing `.0` removed; `0` stays `0`).
7. **Tokens:** each of the four must be an `int` (not `bool`) `>= 0`; an invalid one is absent. `read_tokens` = the sum of all four, **only when all four are present**; otherwise absent (never a partial sum). `thinking_tokens` is never added (A2-8).
8. A missing or non-object `usage` makes all four token fields absent. It does **not** fail the read.

Cost/tokens never decide success (D13). A negative or non-finite cost is absent, so `HosClaudeUsageReadCostUnknown` fires on a successful read (A2-8).

### 3.3 Regexes over `result_text` (pinned against D-1, TD-VF-11, and capture 2, TD-VF-15)

Python `re` with `re.ASCII`; `[0-9]`, never `\d`; `·` written `·`. "Last match wins" = the final `finditer` match.

| Field | Pattern | Rule |
|---|---|---|
| `session_pct` | `Current session: ([0-9]+)% used` | last match |
| `session_resets` | `Current session: [0-9]+% used · resets (.*)` | last match; strip; cap 100 |
| `weekly_all_pct` | `Current week \(all models\): ([0-9]+)% used` | last match |
| `weekly_all_resets` | `Current week \(all models\): [0-9]+% used · resets (.*)` | last match |
| per-model | `Current week \(([^)]+)\): ([0-9]+)% used(?: · resets (.*))?` | every match whose group 1 ≠ `all models`; `name` = group 1, control-stripped, cap 64; slug per §1.3 |
| marker | `^You are currently using your subscription to power your Claude Code usage\s*$` (`re.M`) | informational |
| any `% used` | `[0-9]+% used` | empty-shape test only |
| empty markers | `Total cost:` (substring) or `Usage:\s+0 input` | |

Uncapped integers (`150` accepted); `48.5%` does not match, so the read fails (AD-4).

**Breakdown — Revision 2 (ADR A2-7): generic windows; every line individually optional.** Line by line, only when `ok`:
- **Header:** `^\s*Last (\S+) · ([0-9]+) requests · ([0-9]+) sessions\s*$`. Opens a block for window label group 1 (slug per §1.3). The parser does not assume `24h`/`7d`.
- **Block extent:** to the next header, the next empty line, or end of text.
- **Behavior lines** (each optional):
  - `^\s*([0-9]+)% of your usage came from subagent-heavy sessions\s*$` → `subagent_heavy_pct_<w>`
  - `^\s*([0-9]+)% of your usage was at >150k context\s*$` → `long_context_pct_<w>`
  - `^\s*([0-9]+)% of your usage came from sessions active for 8\+ hours\s*$` → `long_session_pct_<w>`
- **Top line** (optional): `^\s*Top subagents: (.+?)\s*$`, split on `", "`. The last item may match `^\+([0-9]+) more$` (`more = K`, else `0`). Every other item must match `^(\S(?:.*\S)?) ([0-9]+)%$`; a duplicate sanitized name or any bad item makes `top_subagents_<w>` and `top_subagents_more_<w>` both absent.
- **Ambiguity → absent.** A window slug seen twice makes all of that window's fields absent. A behavior or top line seen twice in one block makes that field absent.
- **Isolation.** Each extraction runs in its own `try/except Exception`; a failure leaves only that field absent and can never change `ok`/`reason` (FR-17, AC-18).

### 3.4 Read classification — Revision 2 (ADR A2-7)

`poll-record` decides `outcome`/`reason` in this order:
1. **Pre-ssh refusal** (`--transport-reason`): `ssh_failed` (key missing) or `crashed`.
2. **Transport** (`classify_transport`): `kind=timeout` → `timeout`; `kind=spawn_failed` → `spawn_failed`; `kind=exited, rc=255` → `ssh_failed`. Stdout is not parsed for the decision then (cost/tokens are not recorded either).
3. **Envelope:** `parse_envelope(stdout)`; not ok → `envelope_invalid`.
4. **Content** over `result_text` (A1-3/D12, unchanged): session **and** weekly-all → success; no `[0-9]+% used` anywhere **and** (`result_text.strip() == ""` or an empty marker matches) → `empty_session`; session only → `missing_weekly`; weekly only → `missing_session`; otherwise → `unparseable`.

`remote_exit` is recorded whenever ssh exited; any code other than 255 never fails the read by itself. `detail` on failure: the first 200 sanitized characters of stderr (transport, envelope) or of `result_text` (content), prefixed `stderr:`/`result:`. A missing forced command yields a login shell on `/dev/null` stdin, so no JSON → `envelope_invalid` (A2-9).

### 3.5 Settings

As §1.8. CLI path: `HOS_USAGE_PAUSE_CONF` (test-only) or `Path(os.environ["HOME"]) / ".config/hos/usage-pause.conf"`. Never `HOS_CONFIG_DIR` (S1-ST3).

### 3.6 `read_reading` and `evaluate_cycle` — the decision table — Revision 2 (ADR A2-3, A2-6)

**`read_reading(path)`** (unchanged rules from Revision 1's `read_status`): `ENOENT` → `missing`; other `OSError`, > 65536 bytes, invalid UTF-8 → `unreadable`; empty, or last line ≠ `end=1` → `truncated`; first line not `schema=<digits>` → `unreadable`; schema ≠ 1 → `schema_unknown`; any line not matching `^[a-z0-9_]+=[^\x00-\x1f\x7f]*$`, a duplicate key, or `schema`/`end` elsewhere → `unreadable`; else `ok`.

**`evaluate_cycle(reading, settings, now, *, poller_artifacts_present)`** reads only keys in `CHECK_READ_KEYS` = `{kind, run_epoch, outcome, reason, session_pct, weekly_all_pct}` ∪ every `weekly_model_<slug>_name` / `weekly_model_<slug>_pct` key. First matching row wins. `ST`, `WT`, `MT` are the **current** conf's thresholds.

| # | Condition | decision | class | reason |
|---|---|---|---|---|
| R1 | `settings.status` starts `invalid:` | pause | `settings_invalid` | `settings_invalid:<key>` |
| R2 | `missing` and not `poller_artifacts_present` | U | | `poller_not_installed` |
| R3 | `missing` | U | | `reading_missing` |
| R4 | `truncated` / `schema_unknown` / `unreadable` | U | | `reading_truncated` / `schema_unknown` / `reading_unreadable` |
| R5 | `kind ≠ reading`, `run_epoch` not `^[0-9]+$`, or `outcome ∉ {success, failure, crashed}` | U | | `reading_unreadable` |
| R6 | `now − run_epoch < −120` | U | | `reading_future` |
| R7 | `now − run_epoch > staleness_seconds` (exactly equal is fresh) | U | | `reading_stale` |
| R8 | `outcome=success` and (`session_pct` or `weekly_all_pct` missing/not `^[0-9]+$`, or any `weekly_model_*_pct` not `^[0-9]+$`, or a `_pct` without its `_name`) | U | | `reading_unreadable` |
| R9 | success, and the over-list (`session` if `s >= ST`; `weekly_all` if `w >= WT`; each model with `m >= MT`) is non-empty | pause | `limit` | A2-6 format (§1.2) |
| R10 | success otherwise | run | `ok` | OK summary (§1.2) |
| R11 | `outcome ∈ {failure, crashed}` | F | | `read_failed:<reason or unknown>` |
| R12 | U or F under `fail_mode=closed` | pause | `reading_unusable` / `read_failed` | the U/F reason |
| R13 | U or F under `fail_mode=open` | run | `failopen` | the U/F reason; `unchecked=True` |

- `poller_artifacts_present` = the conf file exists **or** `$HOME/.ssh/hos_loopback` exists (`exists` only; the key is never opened). R2 needs the reading, the conf and the key all absent (A2-15).
- Breakdown and cost fields never enter this table (FR-17, FR-35).
- **Resume** is R10: every present limit `<` its threshold (FR-23). There is no state to clear.

The poller's informational view uses **the same function** (§3.7 P7), so the poll view and the gate cannot drift in rule, only in inputs (conf edited between polls, A2-3).

### 3.7 `bin/hos-usage-poll` — CLI and poll procedure — Revision 2 (ADR A2)

```
hos-usage-poll                                   # one poll (crontab)
hos-usage-poll --check [--capture-fixture PATH]  # preflight (§3.10)
hos-usage-poll --print-setup                     # prints setup; never mutates (§3.11)
hos-usage-poll remote-cmd                        # prints the forced-command text (A2-9)
hos-usage-poll export --from T --to T [--label NAME=VALUE]...   # S3, §5.5
hos-usage-poll --help                            # first description line, verbatim:
  "Reads Claude subscription usage (/usage) over SSH loopback (ADR-1944); the read itself is bin/lib/usage_pause.py read-usage."
```
`bin/hos-usage-poll` must not contain the literal `claude -p` or `-p /usage` (T4.1/T4.1b). Neither may `bin/lib/usage_pause.py` contain `claude -p` / `claude --print` (S1 code-review round 1 (S5), §11.5 C-10).

**Exit codes.** Poll: `0` = reading written or lock held; `1` = no reading could be written (crash path attempted); `64` = usage error. `--check`: `0` all PASS/SKIP/INFO, `1` any FAIL, `64` usage error (incl. `--capture-fixture` target already exists). `--print-setup`: `0`, or `1` with a `MISSING:` line when the `.pub` is absent. `remote-cmd`: `0`, or `1` when no `claude_bin` resolves. `export`: §5.5.

**Poll procedure** (`set -uo pipefail`, no `-e`; every step explicit):
- **P1. Environment.** HOME fallback and `export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"`, exactly as `hos-cron:126`. **No `unset`, no `env -u`, nothing removed from the environment** (A2-9, D5). The poller never sources, reads or names `claude-auth.env` (AC-15).
- **P2. Self-location (A2-16).** `_SELF` = the resolved path of `$0` (`realpath "$0"`, falling back to `cd -P "$(dirname "$0")" && pwd -P` + basename when `realpath` is absent). `_LIB="$(dirname "$_SELF")/lib/usage_pause.py"`. `_STATE="${HOS_STATE_DIR:-$HOME/.hos}"`. `mkdir -p "$_STATE/usage-pause" "$_STATE/locks"`; `chmod 700 "$_STATE/usage-pause"`. No `git`, no clone-path computation.
- **P3. Lock** (unchanged): `mkdir "$_STATE/locks/usage-poll.lock"`; held and < 600 s → log `another poll holds the lock — exiting`, exit 0, no write; ≥ 600 s → reclaim, `_DIAG=lock_stale_reclaimed`; `trap _on_exit EXIT`.
- **P4. Parameters.** `python3 "$_LIB" poll-params` prints exactly two lines, `read_timeout_seconds=<int>` and `settings_status=<…>`, read with `while IFS='=' read -r k v` + `case`. Never `eval`/`source`. Other output or `rc≠0` → `_TRANSPORT_REASON=crashed`, `detail="poll-params failed"`, go to P7.
- ~~P5 timeout binary; P6 claude executable~~ **Removed** (A1-2; A2-7: the client never names claude).
- **P5. Key.** `${HOS_USAGE_KEY_PATH:-$HOME/.ssh/hos_loopback}` not a readable regular file → `_TRANSPORT_REASON=ssh_failed`, `detail="loopback key missing"`, go to P7.
- **P6. The read.** `python3 "$_LIB" read-usage --timeout "$_READ_TIMEOUT" --key <key> --stdout "$_STATE/usage-pause/poll.stdout.tmp" --stderr "$_STATE/usage-pause/poll.stderr.tmp"`. Prints exactly one line `^read=(exited|timeout|spawn_failed) rc=([0-9]+|-)$`, exit 0; anything else → `_TRANSPORT_REASON=crashed`, `detail="read-usage failed"`.
- **P7. Step 1 of the write order — the reading.** `python3 "$_LIB" poll-record --state-dir "$_STATE" [--read K --rc N --stdout F --stderr F] [--transport-reason R] [--detail D] [--diagnostics "$_DIAG"]`:
  - classifies (§3.4), parses (§3.2–3.3), builds the reading with carry-over (§1.3);
  - loads the current conf and computes the **poll view** by calling `evaluate_cycle(<the reading being built>, settings, now=run_epoch, poller_artifacts_present=True)`: `poll_pause_condition = 1` iff decision is pause, `poll_pause_reason` = its reason; plus `poll_settings_status`, `poll_fail_mode`, `poll_*_threshold` (valid/defaults only), `poll_staleness_seconds`;
  - writes `reading` atomically (§1.5);
  - prints `[hos-usage-poll] <iso> outcome=<o> [reason=<r>] [session=<n> weekly_all=<n>] [cost=<c> tokens=<t>] pause_condition=<0|1> (<reason>)`;
  - exit 0 on a successful write (`_WROTE=1`), else 1.
- **P8. (S3) Step 2 — the `.prom`.** If `_WROTE=1`: `python3 "$_LIB" write-prom --state-dir "$_STATE" || echo "… WARN: prom export failed (ignored; never affects the pause)"`. The first render omits `history_write_ok` (A2-11).
- **P9. (S3) Step 3 — history + prune.** If `_WROTE=1`: `python3 "$_LIB" history-append --state-dir "$_STATE"` prints exactly `history_write_ok=0|1` and exits 0. Anything else → `_HWO=0` and a WARN line.
- **P10. (S3) Re-render.** If `_WROTE=1`: `python3 "$_LIB" write-prom --state-dir "$_STATE" --history-write-ok "$_HWO" || WARN`.
- **P11. Step 4 — `last-raw`** (S1). If P6 ran: `python3 "$_LIB" last-raw --state-dir "$_STATE" --read K --rc N --stdout F --stderr F --run-epoch <from reading or now> || WARN`. **Architect round 2:** if P6 did not run but P7 was reached, `python3 "$_LIB" last-raw --state-dir "$_STATE" --read none --run-epoch <…> || WARN` (header only, §1.6).
- **P12. `_on_exit` (EXIT trap).** `rm -f` both `poll.*.tmp`; `rm -rf` the lock; if `_WROTE≠1`, try `poll-record --transport-reason crashed --detail "exit=<code> at <step>"`; if that also fails, write the §1.3 minimal crash file in bash (§1.5); never re-raise.

Steps P8–P11 are each independently best-effort: a failure is logged to `poll.last.log` (the crontab redirect) and changes nothing earlier in the order (FR-54). S1 ships P1–P7, P11, P12; S3 inserts P8–P10 in place.

**No step reads `$STATE/suspend/`, a `hos-halt` issue, `projects.conf`, or project state** (FR-24, AC-12, AC-27; S1-ST2). No network call apart from the loopback `ssh`. No audit event (FR-34).

### 3.8 SSH, credential hygiene, time bound — Revision 2 (ADR A2-9)

- **argv:** `ssh -n -i <key> <SSH_OPTIONS> 127.0.0.1`, a Python list, no local shell, **no element after the host**. `SSH_OPTIONS` are AD-6's: `BatchMode=yes`, `IdentitiesOnly=yes`, `RequestTTY=no`, `ConnectTimeout=10`, `ServerAliveInterval=10`, `ServerAliveCountMax=3`, `StrictHostKeyChecking=yes`, `LogLevel=ERROR`.
- **Forced command** (human-installed, §3.11): `from="127.0.0.1,::1",command="<abs claude_bin> -p /usage --output-format json" <type> <blob> hos-loopback`. **Exactly those two options**; no `restrict`, `no-pty`, `no-port-forwarding`, `no-agent-forwarding`, `no-X11-forwarding`, `no-user-rc`.
- **No environment unsetting anywhere** (D5): no `env -u`, no `unset`, no `os.environ.pop`/`del`/`os.unsetenv`, and no `env=` argument to `Popen` (S1-ST1). The `claude` process runs in sshd's plain login environment, which never sources `claude-auth.env`.
- **Time bound** (A1-2, unchanged): `read_timeout_seconds` + SIGTERM + 5 s + SIGKILL on the process group; worst case ≈ 75 s.
- **Residual risk accepted (A2-9):** server-side environment is not scrubbed (detector: a leaked OAuth token yields `empty_session` → fail-closed pause + `ReadFailing` alert); no `restrict` (the key holder is already scott on faberix). security-reviewer reviews this residual in S1.

### 3.9 ~~Revision 1 §3.7 remote `env -u` line~~ — Removed by Revision 2 (ADR A2-9, D5)

### 3.10 `--check` — Revision 2 (ADR A2) (FR-48, AC-22, AC-48, AC-49, A2-4)

Read-only and idempotent. Takes no lock and writes nothing under `$STATE` or `/var/lib/hos-usage`. Its one real read goes to a `mktemp -d` under `${TMPDIR:-/tmp}`, removed on exit. **The only exception (A2-7):** `--capture-fixture PATH` writes the real read's **unfiltered stdout bytes** to `PATH` (mode 0600, via `PATH.tmp` + rename) and nowhere else; an existing `PATH` is refused before any check runs (exit 64). Output: one line per item, `PASS|FAIL|SKIP|INFO  <n>  <text>[ — <remedy>]`, then `RESULT: PASS` or `RESULT: FAIL (<k> failed)`.

1. `~/.ssh/hos_loopback` exists, mode exactly `0600` (`python3 "$_LIB" stat-mode <path>`).
2. **`authorized_keys` line (A2-9).** `~/.ssh/hos_loopback.pub` exists; exactly one line of `~/.ssh/authorized_keys` contains its base64 blob; that line's option list, parsed with OpenSSH quoting rules, is **exactly** `from="127.0.0.1,::1"` and `command="<remote-cmd output>"` and nothing else, byte-equal. A difference FAILs and names it (`extra option: restrict`, `command mismatch: expected '…' got '…'`, `missing from=`). Two lines with the blob → FAIL.
3. `ssh-keygen -F 127.0.0.1 -f ~/.ssh/known_hosts` exits 0.
4. `python3 "$_LIB" check-settings` → `valid`/`defaults` PASS; invalid → FAIL naming key and value.
5. Crontab: exactly one non-comment `crontab -l` line contains `hos-usage-poll`; schedule `*/N * * * *` with `N*60 == poll_interval_seconds` (or `0 * * * *` for 3600); no `>>`; the invoked path (after `$HOME`/`${HOME}`/`~/` expansion) resolves to `_SELF`. `crontab` absent or failing → FAIL.
6. `claude_bin` resolves and is executable (`-x`) — the only home of `claude_not_executable` (A2-7). FAIL text: `claude_not_executable: <path> — set claude_bin or fix PATH, then regenerate the authorized_keys line`.
7. **One real loopback read** (`read-usage` into the temp dir, then `python3 "$_LIB" classify …`), printing `SUCCESS session=<n> weekly_all=<n>[ <model>=<n>…] cost_usd=<c|absent> read_tokens=<t|absent>` or `FAILED reason=<r> detail=<…>`. PASS iff `SUCCESS` **and** `cost_usd=0` **and** `read_tokens=0` (TD-O-20: non-zero or absent → FAIL `read cost not zero/unknown — FR-9`). INFO `stderr non-empty (<k> bytes)`. With `--capture-fixture`, INFO `captured <bytes> bytes to <PATH>`.
8. **Every scheduled `hos-cron` copy carries the gate (A2-4, D7b).** For each non-comment crontab line, tokenize with POSIX shell rules (`shlex.split`, after splitting off the five schedule fields; `@reboot`-style lines have one). Every token whose basename is exactly `hos-cron` is an invoked copy. Expand a leading `$HOME`/`${HOME}`/`~/`. Then per distinct resolved file:
   - relative path → FAIL `cannot resolve relative hos-cron path '<tok>' — use an absolute path`;
   - missing or unreadable → FAIL naming the path;
   - no line equal (after stripping trailing whitespace) to `GATE_SENTINEL` → FAIL `<path>: no usage-pause gate — this copy's cycles are NOT paused; upgrade it`;
   - `<dir>/lib/usage_pause.py` missing beside it → FAIL `<path>: gate present but lib/usage_pause.py missing — every cycle will pause with check_error`;
   - else PASS `<path>: gate present`.
   No `hos-cron` line at all → INFO `no hos-cron scheduled in this user's crontab`. **The runbook requires item 8 green after every upgrade of any project** (A2-4).
9. (S3) Export path, unchanged from Revision 1 item 7: `/var/lib/hos-usage` absent → SKIP; else writable, and exactly one of (symlink resolves to the file) / (`ARGS` has the second textfile directory); both → FAIL; neither → FAIL with the ESM-purge remedy.
10. **Human rulings H-1..H-4, H-7 (H-7, ADR A4-7; S1).** Runs after item 7 and only when item 7 printed `SUCCESS`; otherwise `SKIP 10 no successful read`. It evaluates the item-7 read against the **current** settings with the same function the poller uses for `poll_pause_condition`/`poll_pause_reason` (§3.6, poll view), then prints `INFO 10 pause_condition=<0|1> reason=<text>`. The text is in exactly the `poll_pause_reason` format (§1.2), e.g. `INFO 10 pause_condition=1 reason=session 7% >= 5`. Under invalid settings it prints `INFO 10 pause_condition=1 reason=settings_invalid:<key>`. **Always INFO, never FAIL:** a pause condition is not a setup fault, and `RESULT:` is unaffected. Item 10 writes nothing (the read-only rule holds). It is the `--check` half of the trip-test evidence (§3.15).

### 3.11 `--print-setup` — Revision 2 (ADR A2-9, A2-16)

Prints, in order, with headings:
1. `mkdir -p ~/.hos/usage-pause && chmod 700 ~/.hos/usage-pause`
2. `ssh-keygen -t ed25519 -N '' -C hos-loopback -f ~/.ssh/hos_loopback`
3. The **one** `authorized_keys` line: `from="127.0.0.1,::1",command="<remote-cmd output>" <type> <blob> hos-loopback`. ~~Recommended `restrict,…` / ruled-minimum `from=`-only alternatives~~ **removed** (D5).
4. `known_hosts` seeding from the on-disk host key (unchanged).
5. **The crontab line — the single install-path definition (A2-16):** `*/N * * * *  <_SELF> > <abs $HOME>/.hos/usage-pause/poll.last.log 2>&1` (or `0 * * * *` for 3600).
6. (S3) The two root commands of §5.1.
7. `<_SELF> --check --capture-fixture <abs $HOME>/hos-usage-envelope-<YYYYMMDD>.json` (first run, AC-49), then plain `--check`.

### 3.12 Shipping and T4.1 / T4.1b / T4.2 — Revision 2 (ADR A2-9)

- **Shipping (unchanged):** S1 adds `bin/hos-usage-poll` and `bin/lib/usage_pause.py` to `framework_consumer_files.txt`; `hos_install.sh` copies and `chmod +x`'s them. `contrib/` is never listed (S4 test).
- **T4.1 (S1 code-review round 1 (S5), §11.5 C-10 — supersedes the earlier file-level exemption):** `_T4_1_EXPECTED_EXEMPTIONS` is **unchanged**; `bin/lib/usage_pause.py` is **not** exempt. Neither `bin/lib/usage_pause.py` (docstring included) nor `bin/hos-usage-poll` may contain `claude -p` / `claude --print`, so a raw call added anywhere in either file fails T4.1. The template line (`{claude_bin} -p ...`) does not match T4.1's pattern.
- **`test_T4_1b_usage_read_has_one_call_site`:** over code lines of `scripts/`, `bootstrap/`, `bin/`, `(?:-p|--print)\s+["']?/usage\b` matches only in `bin/lib/usage_pause.py`, and there on **exactly one** code line, which starts with `REMOTE_CMD_TEMPLATE` (the C-9 line). No code line of `bin/lib/usage_pause.py` or `bin/hos-usage-poll` matches `claude\s+(-p|--print)` (S1 code-review round 1 (S5), §11.5 C-10).
- **`test_T4_1b_remote_command_template_is_exact`:** exactly one code line matches `^REMOTE_CMD_TEMPLATE\s*=`; stripped of its trailing comment it equals `REMOTE_CMD_TEMPLATE = "{claude_bin} -p /usage --output-format json"`. Neither file has a code line matching `--model|--json-schema|--agent|env -u`.
- **`test_T4_1b_ssh_argv_ends_at_host`:** the `read_usage` argv (built with a stub `Popen`) ends with `"127.0.0.1"`.
- **T4.2: no change.**

### 3.13 Runbook — `docs/CRON-SETUP.md` §2a "Usage-pause poller (SSH loopback)" — Revision 2 (ADR A2)

Outline (S1 writes all except 2a.8, which S3 adds; S2 adds 2a.0 and the §7 rows):
- **2a.0 Upgrade note (S2).** "A release containing the usage-pause gate pauses every worker/overseer cycle on this host (fail-closed, `[PAUSED-USAGE] reading_missing` or `poller_not_installed`) until the poller below is set up and `--check` is green, or `fail_mode=open` is set. **fail_mode=open without a running poller means no quota protection**" (exact sentence, **Human rulings H-1..H-4, H-7**: H-1, ADR A4-1). Also: "each such cycle writes one `cycle-usage-unchecked` audit event". Plus API-key-billed consumers: `fail_mode=open` is their only route (A2-15).
- **2a.1 What it is.** One poller per host, every 5 min. Reads `/usage` under your personal login over SSH loopback, never `claude-auth.env`. Every worker/overseer cycle on the host — all projects, both roles — pauses at cycle start when **session, weekly (all models), or any weekly per-model** usage is `>=` its threshold (default 90 each), or the reading is missing, stale or failed (fail-closed). Auto-resumes. Interactive sessions are never paused. Separate from `hos-suspend`.
- **2a.2 Key.** As printed by `--print-setup` block 2.
- **2a.3 authorized_keys.** Append the one printed line. It is **not final until a real `--check` read returns real percentages** (AC-48). If `claude` moves, regenerate (`remote-cmd`); `--check` item 2 detects drift. No `restrict`, no env unsetting (D5; the human ruled both fragile).
- **2a.4 known_hosts.** The printed on-disk seeding command.
- **2a.5 Settings (optional).** The §1.8 table verbatim plus: "missing = defaults; any invalid value, unknown key or duplicate key (including the history keys) pauses every cycle until fixed, regardless of `fail_mode`; the cron log line names the key".
- **2a.6 Crontab — the one install-path line (A2-16, AC-51).** "This line is the single place the poller's install path is defined. When the path changes (e.g. #1276), change this line." Use `>`, not `>>`. One entry per host.
- **2a.7 Verify.** First run `--check --capture-fixture …` (keep the file; attach it to #1944), then `--check` → `RESULT: PASS`. **Item 8 must be green after every upgrade of any project on the host** — it checks every scheduled `hos-cron` copy for the gate (AC-51).
- **2a.8 (S3) Metrics export on faberix.** Root step (§5.1), symlink verification, fallback, ESM-purge note.
- **2a.9 Fail-open (FR-67, AC-51).** "`fail_mode=open` is safe **only once alerting is live** (`contrib/monitoring/`, AC-43 and AC-44 recorded). On faberix it is forbidden until S5 is recorded (A2-18). fail_mode=open without a running poller means no quota protection." (exact sentence, H-1)
- **2a.10 Reading the state.** `cat ~/.hos/usage-pause/reading` (raw values, `poll_*` = the poller's view); `cat ~/.hos/usage-pause/last-raw` (parse-failure debugging); `[PAUSED-USAGE]` / `[USAGE-OK]` / `[USAGE-UNCHECKED]` lines in `/tmp/hos-<role>-<project>.log`; `cycle-usage-paused` and (fail-open, H-1) `cycle-usage-unchecked` audit records. No GitHub issue is ever filed (D7). **Architect round 2 (TD-O-18):** "A paused cycle never pushes audit records. They stay in the clone's `audit/log/` and are pushed by the first running cycle after the pause ends. During a long pause (e.g. waiting for the weekly reset) the cron log is the up-to-date record; the audit branch catches up on resume."
- **2a.11 (S3) History and backfill (AC-51).** Daily JSONL under `~/.hos/usage-pause/history/`, pruned every poll to `history_days`/`history_max_mb`. Backfill: §5.5 procedure, verbatim.
- **§7 rows (S2):** `reason=poller_not_installed|reading_missing|reading_stale` → `--check`, `crontab -l`, `cat poll.last.log`; `settings_invalid:<key>` → fix the conf; `check_error` → run `python3 <bin>/lib/usage_pause.py check --state-dir ~/.hos` by hand; `read_failed:envelope_invalid` → `cat last-raw`, check the forced command (item 2).

`MACHINE-ACCOUNTS-SETUP.md`: one line, "Claude usage-pause poller (SSH loopback): see `docs/CRON-SETUP.md` §2a." `hos_install.sh` prints `"       d. Claude usage-pause poller (required before cycles run): see docs/CRON-SETUP.md §2a"` inside the existing worker/overseer cron block.

### 3.14 S1 exit criteria — Revision 2 (ADR A2-18) (all recorded on faberix before S2 merges)

1. The PR suite is green, incl. T4.1/T4.1b/T4.2 (AC-26).
2. **AC-48:** the `remote-cmd` `authorized_keys` line is installed and a real `--check` returns real session and weekly percentages (item 7 `SUCCESS`). Only then is the line recorded as final.
3. **AC-49:** `--check --capture-fixture` ran once; the file is attached to #1944 (and committed as a fixture by a later PR).
4. **AC-16:** at least one **cron-fired** poll produced `outcome=success` (`crontab -l | grep hos-usage-poll`; `reading` with a `run_at` on a `*/5` boundary; `poll.last.log`; `--check` `RESULT: PASS`).
5. **AC-25:** the same record shows `cost_usd=0` and `read_tokens=0` from a real read. (The alert half of AC-25 is S4: `HosClaudeUsageReadCostNonzero`/`…TokensNonzero` exist.)

The record is a #1944 comment posted by the human or the orchestrating session.

### 3.15 S1 trip test — Human rulings H-1..H-4, H-7 (H-7, ADR A4-7; recorded after §3.14, **before S2 is built**)

This test is run by the human on faberix once the S1 exit records are posted. **No autonomous work pauses**, because no gate exists yet. Steps:
1. **Back up the conf.** If `~/.config/hos/usage-pause.conf` exists, `cp` it to `usage-pause.conf.trip-backup`; otherwise note that it is absent.
2. **Lower one threshold.** Read the current `session_pct` (`S`) from `~/.hos/usage-pause/reading`. Set `session_threshold` to a value ≥ 1 and below `S`; equal also trips, since the comparison is `>=`. If `S` is 0 or 1, use `weekly_threshold` against `weekly_all_pct` the same way. The conf must stay valid: all other keys unchanged, no duplicates.
3. **Check the next cron-fired poll.** Wait for it (at most `poll_interval_seconds`), then record that the `reading` file shows:
   - `poll_settings_status=valid`;
   - `poll_pause_condition=1`;
   - `poll_pause_reason=<limit> <pct>% >= <lowered threshold>`, for example `session 7% >= 5`.
4. **Check `--check`.** Run `bin/hos-usage-poll --check` and record its `INFO 10 pause_condition=1 reason=…` line, which must name the same limit and threshold (the percentage may differ by one poll). `RESULT:` stays `PASS`.
5. **Restore the conf.** Copy the backup back, or delete the conf if it was absent.
6. **Check the following poll.** Record `poll_pause_condition=0` and `--check` `INFO 10 pause_condition=0`.
7. **Post** steps 2–6 (`reading` excerpts, `--check` output, times) as one #1944 comment.

**Gate:** S2 coding does not start until this comment exists (§8). The test proves, on live data, the exact evaluation S2 will consume. It does **not** replace AC-44 (§7.2 item 4), the end-to-end S5 definition of done.

---

## 4. S2 — the `bin/hos-cron` cycle-start gate — Revision 2 (ADR A2-3, A2-4, A2-5, A2-6)

### 4.1 Exact insertion point (A2-4)

The block is inserted **between `:366` (the blank line after `_audit()`'s closing `}` at `:365`) and `:367` (`# ── Audit log sync (#861, updated #1303) ──…`)**: after `:366`, the block, then one blank line, then the existing `:367`. Surrounding lines verbatim at HEAD `0603100b9`:

```
361  # ── Audit helper ──────────────────────────────────────────────────────────────
362  _audit() {
363    local event="$1"; shift
364    (cd "$REPO_ROOT" && python3 -m scripts.automation.lib.cycle_log "$event" "$@") 2>/dev/null || true
365  }
366
     <gate block here>
367  # ── Audit log sync (#861, updated #1303) ──────────────────────────────────────
```

- The block's first line is the begin anchor `# ── Usage-threshold pause gate (#1944, ADR-1944 AD-7/A2-4) ──────────`; its **second line is exactly the sentinel `# HOS-USAGE-PAUSE-GATE schema=1`**; its last line is the end anchor `# ── end usage-threshold pause gate (#1944) ──`. Each of the three strings appears exactly once in `bin/hos-cron`, unquoted anywhere else.
- One header paragraph (≤ 5 lines) goes after the crontab example at `:112-114`, describing the gate and pointing to CRON-SETUP §2a.

**Runs before the gate:** PATH pin, args, registry, timeout resolution, state dirs, suspend check (`:258-286`), overlap lock (`:304-332`), cycle identity (`:334-359`), `_audit` definition. None invokes Claude or the network.
**Runs after the gate:** audit-log sync definition, worktree hygiene, deps check (`:737`), jitter, env validation, wakeup (`:766`, consume `:808`), repo slug, preflight, token mint (`:834`), identity guard, git credentials, `claude-auth.env` (`:877`), model probe (`:899`), halt check (`:906`), all later stages, `cycle-start` (`:1823`), session (`:1849`). **A paused cycle therefore makes zero network calls of any kind, starts no Claude process, leaves wakeup markers alone, and costs milliseconds** (A2-4, FR-26, AC-35).

### 4.2 The sentinel (A2-4, D7b)

`GATE_SENTINEL` in `usage_pause.py` and the second line of the block are the same string. It carries `schema=1` so a future incompatible gate can bump it; `--check` item 8 then FAILs older copies. A static test (S2-ST7) asserts that, under `bin/`, the sentinel appears as a full line only in `bin/hos-cron`, exactly once.

### 4.3 Python side — `usage_pause.py check --state-dir DIR` (S2)

Steps: `load_settings(<conf>)` → `read_reading(DIR/usage-pause/reading)` → compute `poller_artifacts_present` → `evaluate_cycle(…, now=time.time())` → print the verdict line → exit 0. **It writes nothing anywhere** (A2-2; behavior test runs it against a read-only state tree and asserts an unchanged tree hash). Any exception → nothing on stdout, a one-line summary on stderr, exit **70**.

**Verdict line** (exactly one line; the bash side matches it with this exact ERE under `LC_ALL=C`):

```
^USAGE_PAUSE v=2 decision=(run|pause) class=(ok|limit|read_failed|reading_unusable|settings_invalid|failopen) fail_mode=(closed|open) settings=(valid|defaults|invalid:[a-z0-9_]{1,40}) session_pct=([0-9]+|-) weekly_all_pct=([0-9]+|-) reading_age_s=(-?[0-9]+|-) reason=([ -~]{1,200})$
```

`BASH_REMATCH[1..8]` map in order. `reason` is printable ASCII (non-ASCII model-name characters folded to `?`, TD-O-14) and is the last field, so it may contain spaces, `=`, `%`, `;`, `:`. Under invalid settings `fail_mode` prints the default.

~~Revision 1 `check --role --project`, `record`, `issue-body`, the 14-group verdict, transitions and episode memory (§4.2, §4.4, §4.5)~~ **Removed by Revision 2 (ADR A2-2, A2-5).**

### 4.4 The bash block — contract (steps G1–G5)

- **G1. Bound.** **Architect round 2:** the block's first statements after the sentinel are the two named values `_UP_CHECK_TIMEOUT_S=60` and `_UP_CHECK_KILL_AFTER_S=5`, each with a one-line comment; they are the only numeric literals in the block other than `0`/`1` (S2-ST5 asserts this). *Reason:* D19 asks for named values at the top. These are time bounds on the helper, not usage thresholds, but the bare `5 60` was the only unnamed number left on the decision path. Then `_UP_BOUND=()`; if `timeout` exists `_UP_BOUND=(timeout --kill-after="$_UP_CHECK_KILL_AFTER_S" "$_UP_CHECK_TIMEOUT_S")`, else if `gtimeout` exists the same with `gtimeout`. Every expansion is written `${_UP_BOUND[@]+"${_UP_BOUND[@]}"}` (bash 3.2 `set -u` safety; unchanged from Architect round 1). Not a `_TIMEOUT_BIN=` assignment. **No `mkdir`, `touch`, redirect or any write under `$_HOS_DIR/usage-pause/`** (A2-2).
- **G2. Ask.** Inside an `if` (so `set -e` cannot fire), `_UP_LINE="$(${_UP_BOUND[@]+"${_UP_BOUND[@]}"} python3 "$_HOS_CRON_DIR/lib/usage_pause.py" check --state-dir "$_HOS_DIR")"`, recording `rc`. Python's stderr goes to the cron log. Match `_UP_LINE` against §4.3's ERE inside a helper function whose first statement is `local LC_ALL=C`. **Also reject** a match whose `decision`/`class` pair is inconsistent (`run` with a class other than `ok`/`failopen`, or `pause` with `ok`/`failopen`).
  - **If `rc≠0`, no match, or inconsistent:** synthesize `decision=pause`, `reason=check_error`, all other fields `-`. **The pause stands regardless of `fail_mode`** (AD-7.5). A missing `python3` or `bin/lib/usage_pause.py` lands here.
- **G3. Log — exactly one line per gated cycle** (A2-5):
  - pause, `class=settings_invalid`: `$LOG_PREFIX [PAUSED-USAGE] <reason> (fail_mode ignored)`
  - pause, `check_error`: `$LOG_PREFIX [PAUSED-USAGE] check_error (rc=<rc>; fail_mode ignored)`
  - any other pause: `$LOG_PREFIX [PAUSED-USAGE] <reason>`
  - run, `class=ok`: `$LOG_PREFIX [USAGE-OK] <reason>`
  - run, `class=failopen`: `$LOG_PREFIX [USAGE-UNCHECKED] fail_mode=open <reason>`
- **G4. Audit.** On pause only: `_audit cycle-usage-paused "role=$ROLE" "project=$PROJECT" "cycle_id=$HOS_CYCLE_ID" "reason=<reason>" "session_pct=<…>" "weekly_all_pct=<…>" "reading_age_s=<…>" "fail_mode=<…>" "settings=<…>"` (§1.7). **Human rulings H-1..H-4, H-7 (H-1 confirmed, ADR A4-1):** on `class=failopen` (run), exactly one `_audit cycle-usage-unchecked "role=$ROLE" "project=$PROJECT" "cycle_id=$HOS_CYCLE_ID" "reason=<reason>" "session_pct=<…>" "weekly_all_pct=<…>" "reading_age_s=<…>" "fail_mode=<…>" "settings=<…>"`, then fall through. On `class=ok`, no usage event. No block, no issue, no GitHub call.
- **G5. Act.** Pause → `exit 0` (the EXIT trap at `:332` frees the overlap lock; no `_LAST_RUN_FILE`, no wakeup consume, no audit sync). Run → fall through to `:367`.

**The block contains no:** `suspend`, `hos-suspend`, `.prom`, `node_exporter`, `ssh`, `/usage`, `last-claude-output`, `gh`, `curl`, `github`, `poll_`, `HOS_CRON_MAX_SECONDS`, `mkdir`, `touch`, `rm`, `mv`, `cp`, or any `>`/`>>` redirect into a file (S2-ST1). It reads no file except through `usage_pause.py check` (FR-25, FR-28, FR-35, FR-57, AC-11, AC-24, AC-27). No in-flight bound of its own (A2-17).

### 4.5 Consumers and rollout (A2-15, D10)

A consumer host with the gate and no poller pauses every cycle with `[PAUSED-USAGE] reading_missing` (or `poller_not_installed` when reading, conf and key are all absent). No issue, no off switch. `fail_mode=open` runs every cycle with `[USAGE-UNCHECKED] fail_mode=open reading_missing`. The release-note and upgrade-checklist text (TD-O-19):
- `docs/UPGRADE-PR-REVIEW-CHECKLIST.md`, new section **H. Usage-pause gate (#1944)**: three checkboxes: (1) the poller is set up per CRON-SETUP §2a and `--check` is green **before** the upgrade PR merges, or every cycle pauses; (2) after merge, `--check` item 8 is green for every scheduled `hos-cron` copy; (3) API-key-billed: `fail_mode=open` is the only route and means **no usage protection**.
- `docs/releases/v0.7.0.md`, section "Upgrade notes": the same three facts in prose.
- **Human rulings H-1..H-4, H-7 (H-1, ADR A4-1).** Checklist item (3), the release-note paragraph, and CRON-SETUP §2a.0/§2a.9 each contain verbatim: **"fail_mode=open without a running poller means no quota protection"**. Each also states that every such cycle writes one `cycle-usage-unchecked` audit event. S2-ST9 and S2-ST10 assert the exact sentence.
- **Architect round 2 (TD-O-19).** The target is v0.7.0: `hos_target_release=v0.7.0` in the human's `projects.conf`, no `v0.7.0` tag exists, and `docs/releases/v0.7.0.md` does not exist yet (S2 creates it). **Retarget rule:** if `v0.7.0` is tagged before S2 merges, the S2 PR moves the paragraph and S2-ST9's path to the release file for the then-current `hos_target_release`. code-reviewer checks this at S2 review time. #1944 has no milestone; the orchestrating session should put it on the v0.7.0 milestone (a tracker action, not a design change).

### 4.6 ~~`_usage_pause_visibility`, dedup, lock, transitions~~ — Removed by Revision 2 (ADR A2-5, D7)

### 4.7 Test-harness changes in `tests/automation/test_hos_cron.py` — Revision 2

1. **`CronEnv.write_usage_reading(**overrides)`** writes `self.state/"usage-pause"/"reading"` (§1.3). Defaults: `outcome=success`, `session_pct=6`, `weekly_all_pct=48`, `weekly_model_fable_name=Fable`, `weekly_model_fable_pct=3`, `consecutive_failures=0`, `run_epoch=int(time.time())`, `poll_settings_status=defaults`. `None` omits a key; `raw=<bytes>` writes arbitrary content. Also `write_usage_conf(text)` and `remove_usage_reading()`.
2. **`CronEnv.run()`** writes the default reading fresh before every invocation unless the test opted out (`set_usage_reading_managed()`), so every pre-existing test sees "run". Because the gate now precedes worktree hygiene, deps check, jitter and wakeup, this covers tests of those stages too.
3. **Network boundary recording.** The existing `gh` stub records argv. For AC-35 the harness also records invocations of `get_app_token.sh` and `curl` stubs. ~~Revision 1 `--paginate` dedup case, `HOS_TEST_USAGE_PAUSE_ISSUES`, `HOS_TEST_GH_ISSUE_CREATE_FAIL`~~ **removed**.
4. **Copied-launcher tests** (`:1790-1794`, `:1839`, plus any `shutil.copy(HOS_CRON` site found by grep): also copy `bin/lib/usage_pause.py` into the copy's `bin/lib/` and write a fresh reading under that test's `HOS_STATE_DIR`. The fix belongs in the harness, never in the gate.
5. **Two-project registry** helper for AC-34: `projects.conf` with `hos` and `hos2`.

---

## 5. S3 — metrics side path: `.prom`, history, prune, export — Revision 2 (ADR A2-11, A2-12)

### 5.1 Precondition — symlink-follow verification on faberix (unchanged)

A human runs the probe and records it in the S3 PR **before** S3 is coded:

```
sudo install -d -o scott -g scott -m 0755 /var/lib/hos-usage
printf '# HELP hos_symlink_probe probe\n# TYPE hos_symlink_probe gauge\nhos_symlink_probe 1\n' > /var/lib/hos-usage/hos_symlink_probe.prom
sudo ln -sfn /var/lib/hos-usage/hos_symlink_probe.prom /var/lib/prometheus/node-exporter/hos_symlink_probe.prom
curl -s localhost:9100/metrics | grep -E '^hos_symlink_probe |^node_textfile_scrape_error |node_textfile_mtime_seconds\{file=.*hos_symlink_probe'
printf '# HELP hos_symlink_probe probe\n# TYPE hos_symlink_probe gauge\nhos_symlink_probe 2\n' > /var/lib/hos-usage/.probe.tmp
mv -f /var/lib/hos-usage/.probe.tmp /var/lib/hos-usage/hos_symlink_probe.prom
curl -s localhost:9100/metrics | grep -E '^hos_symlink_probe '
sudo rm /var/lib/prometheus/node-exporter/hos_symlink_probe.prom
rm /var/lib/hos-usage/hos_symlink_probe.prom
```

PASS = `… 1`, then `… 2` after the rename, `node_textfile_scrape_error 0`, an mtime series. Then `sudo ln -sfn /var/lib/hos-usage/hos_claude_usage.prom /var/lib/prometheus/node-exporter/hos_claude_usage.prom`. FAIL → fallback (i): `ARGS="--collector.textfile.directory=/var/lib/prometheus/node-exporter --collector.textfile.directory=/var/lib/hos-usage"`, restart, no symlink. If (i) also fails → escalate (AD-10 ii). Never write in place into the root-owned directory.

### 5.2 Metrics contract — Revision 2 (ADR A2-12)

`render_prom(fields: Mapping[str,str], *, history_write_ok: bool|None) -> list[Sample]` is a **pure function of the reading's key/value fields**, so live render and export are one renderer with two clocks (A2-11). `format_textfile(samples)` (no timestamps) and `format_openmetrics(samples_with_ts)` are the two serializers.

Format (textfile): Prometheus text 0.0.4, LF, final newline; families in table order; each present family preceded by `# HELP` and `# TYPE <name> gauge`; an empty family is omitted entirely; **no sample timestamps**; labels sorted by name; label values sanitized to `[A-Za-z0-9_.:-]` (others → `_`), cap 64, first wins on a sanitized collision. Integers render as integers; `read_cost_usd` as the reading's decimal string.

| # | Metric | Labels | Present when (source key) | HELP |
|---|---|---|---|---|
| 1 | `hos_claude_usage_session_percent` | — | success (`session_pct`) | Current-session usage % reported by /usage (raw; may exceed 100) |
| 2 | `hos_claude_usage_weekly_all_models_percent` | — | success (`weekly_all_pct`) | Current-week all-models usage % (raw) |
| 3 | `hos_claude_usage_weekly_model_percent` | `model` | success, per model line (`weekly_model_*`) | Current-week usage % for one model (a pause trigger, D1) |
| 4 | `hos_claude_usage_window_requests` | `window` | header parsed (`requests_<w>`) | Requests in the rolling window, as reported (local sessions) |
| 5 | `hos_claude_usage_window_sessions` | `window` | header parsed | Sessions in the rolling window, as reported |
| 6 | `hos_claude_usage_subagent_heavy_percent` | `window` | line parsed | % of usage from subagent-heavy sessions (independent; overlaps others) |
| 7 | `hos_claude_usage_long_context_percent` | `window` | line parsed | % of usage at >150k context (independent) |
| 8 | `hos_claude_usage_long_session_percent` | `window` | line parsed | % of usage from sessions active 8+ hours (independent) |
| 9 | `hos_claude_usage_top_subagent_percent` | `subagent`, `window` | name in that window's top list | % attributed to a top-N subagent (truncated list) |
| 10 | `hos_claude_usage_top_subagents_more` | `window` | top line parsed (0 = known none) | Subagents omitted from the top list ("+K more") |
| 11 | `hos_claude_usage_read_cost_usd` | — | `cost_usd` present (success or failure) | total_cost_usd of the last /usage read (must be 0) |
| 12 | `hos_claude_usage_read_tokens` | — | `read_tokens` present | input+output+cache_creation+cache_read tokens of the last read (must be 0) |
| 13 | `hos_claude_usage_threshold_percent` | `limit` (`session`\|`weekly_all`\|`weekly_model`) | `poll_*_threshold` present (settings valid/defaults) | Pause threshold % in use |
| 14 | `hos_claude_usage_staleness_seconds` | — | always (`poll_staleness_seconds`) | Staleness window in use (default when settings invalid) |
| 15 | `hos_claude_usage_settings_valid` | — | always | 1 if usage-pause.conf is valid or absent |
| 16 | `hos_claude_usage_fail_mode_closed` | — | always | 1 if fail_mode=closed |
| 17 | `hos_claude_usage_pause_condition` | — | always | 1 iff any limit >= threshold, or a fail-closed failure, or invalid settings (machine-level poller view) |
| 18 | `hos_claude_usage_read_ok` | — | always | 1 if the last poll was a successful read |
| 19 | `hos_claude_usage_read_failure` | `reason` (§1.2 enum) | failure only, value 1 | Reason the last poll failed |
| 20 | `hos_claude_usage_poll_timestamp_seconds` | — | always (`run_epoch`) | Unix time of the last poll |
| 21 | `hos_claude_usage_last_success_timestamp_seconds` | — | always; **0 = none on record** (D8) | Unix time of the last successful read |
| 22 | `hos_claude_usage_history_write_ok` | — | only on the P10 re-render (never in the first render, never in export) | 1 if this poll's history append and prune succeeded |

- `pause_condition` is rendered from `poll_pause_condition`; when the key is absent it renders `1` (conservative). `settings_valid` = 1 iff `poll_settings_status ∈ {valid, defaults}` (absent → 0). `fail_mode_closed` from `poll_fail_mode` (absent → 1).
- ~~`threshold_percent{window}`~~ **Revision 2:** `{limit}`.
- The module exports `METRIC_NAMES` (this table, in order); S4 tests import it.
- **Raw values only** (FR-43, AC-19); absent, never 0 (FR-44), except #21.

### 5.3 `write-prom` (S3)

`write-prom --state-dir DIR [--history-write-ok 0|1]`: `read_reading(DIR/usage-pause/reading)` must be `ok` (else exit 1, no write) → `render_prom` → write `HOS_USAGE_PROM_PATH` (test-only) or `/var/lib/hos-usage/hos_claude_usage.prom` via `.hos_claude_usage.prom.tmp` + `fsync` + `chmod 0644` + `os.replace`. Parent directory absent → exit 0, stdout `prom export not configured`. **Never touches `reading`.** Nothing on the decision path reads its output.

### 5.4 History log and pruning (A2-11, D18, FR-52)

`history-append --state-dir DIR`:
1. `read_reading` must be `ok`, else `history_write_ok=0`.
2. **Line** = a JSON object of **every reading key except `end`, in reading order, values as the reading's strings** (lossless; the renderer takes the same mapping). Serialized `json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n"`.
3. **Size cap** `HISTORY_LINE_CAP_BYTES` (16384, incl. the newline). Over the cap, drop keys in this order until it fits: every `top_subagents_<w>`; every `*_resets`; every other breakdown key (`requests_`, `sessions_`, `*_pct_<w>`, `top_subagents_more_`); `detail`. Core keys are never dropped. Still over → write nothing, `history_write_ok=0`.
4. **Append:** `mkdir -p DIR/usage-pause/history` (mode 0700); `os.open(path, O_WRONLY|O_APPEND|O_CREAT, 0o600)`; **one `os.write`** of the whole line; a short write counts as failure. File = `usage-<UTC date of run_epoch>.jsonl`.
5. **Prune** (after the append, every poll): consider only names matching `^usage-([0-9]{4})-([0-9]{2})-([0-9]{2})\.jsonl$` that are regular files directly in `history/` (never follow symlinks, never recurse, never touch anything else). `today` = UTC date of `run_epoch`.
   - **Days:** delete every file whose date `d` satisfies `(today − d).days >= history_days` (keeps exactly `history_days` calendar days including today). A file dated in the future is kept.
   - **Size:** then, while the total size of remaining files exceeds `history_max_mb × 1,048,576` bytes, delete the oldest remaining file **other than today's**.
   - If today's file alone still exceeds the cap, stop; that is not a failure, and a WARN line is logged (TD-O-17).
6. Print `history_write_ok=1` iff steps 1–5 completed without `OSError`; else `0`. Exit 0 either way.

A torn final line (crash mid-write) is tolerated by `export` (§5.5). Whichever cap is hit first governs (AC-36, AC-37).

### 5.5 `export` — OpenMetrics for backfill (A2-11, FR-53)

`hos-usage-poll export --from T --to T [--label NAME=VALUE]...` (bash delegates to `python3 "$_LIB" export --state-dir "$_STATE" …`). Read-only, takes no lock.
- `T` is an epoch integer or `YYYY-MM-DDTHH:MM:SSZ`. `from > to`, a bad `T`, or a bad label → exit 64.
- `--label`: `NAME` matches `^[a-zA-Z_][a-zA-Z0-9_]*$` and must not be any label the renderer uses (`model`, `window`, `subagent`, `limit`, `reason`), else exit 64; `VALUE` is label-sanitized. These add the scrape-time target labels (`instance`, `job`, …) so backfilled series match the live ones.
- Files read: names matching the §5.4 pattern with date in `[date(from), date(to)]`, ascending. Lines: `json.loads`; non-object, unparseable, or lacking an integer `run_epoch` → counted as `torn`, skipped. Lines with `from ≤ run_epoch ≤ to` are rendered with `render_prom(fields, history_write_ok=None)`, timestamp = `run_epoch`. A duplicate `run_epoch` keeps the later line (counted `duplicates`).
- **Output (stdout):** OpenMetrics 1.0 text. Families in `METRIC_NAMES` order, **each family exactly once** (never interleaved), `# HELP` + `# TYPE <name> gauge`, then its samples sorted by label set, then by timestamp ascending, as `name{labels} value timestamp` (integer seconds). Ends with `# EOF\n`. Absent values produce no sample (absent stays absent).
- stderr: `export: files=<n> lines=<n> torn=<k> duplicates=<d> samples=<s>`. Exit 0; exit 1 if the history directory is missing.

**Backfill runbook (CRON-SETUP §2a.11, AC-51), verbatim steps:**
1. On faberix: `bin/hos-usage-poll export --from <start> --to <end> --label instance=faberix --label job=linux_servers --label role=server --label os=ubuntu > hos-backfill.om` (use the exact target labels the live series carry on monitrix).
2. Copy to monitrix. `promtool tsdb create-blocks-from openmetrics hos-backfill.om ./hos-blocks`.
3. Move the blocks into Prometheus's data directory as the `prometheus` user (the path from `--storage.tsdb.path`), then `sudo systemctl restart prometheus`.
4. Data older than the retention (90 d on monitrix) is dropped at the next compaction; backfill only within retention.
5. Verify with a range query that the backfilled range shows the history values.

### 5.6 Poller and `--check` changes in S3

P8–P10 (§3.7); `--check` item 9; `--print-setup` block 6; CRON-SETUP §2a.8 and §2a.11.

---

## 6. S4 — `contrib/monitoring/` worked example — Revision 2 (ADR A2-13, A2-14)

### 6.1 Layout

```
contrib/monitoring/
  README.md                                        # monitrix operator runbook (§6.7)
  grafana/
    dashboards/hos-claude-usage.json               # §6.5
    provisioning/
      dashboards/hos.yaml                          # §6.2
      alerting/hos-rules.yaml                      # §6.3 (13 rules; H-3 adds rule 13)
      alerting/hos-contact-point.yaml              # §6.4
  monitrix/
    hos-monitoring-sync                            # §6.6; installed BY COPY to /usr/local/bin
    hos-grafana-alerting-reload                    # §6.6a (H-3); installed BY COPY to /usr/local/sbin
    hos-grafana-alerting-reload.path               # §6.6a (H-3); installed BY COPY to /etc/systemd/system
    hos-grafana-alerting-reload.service            # same
docs/MONITORING-WORKED-EXAMPLE.md                  # §6.8 "recommended setup"
```

~~`contrib/monitoring/prometheus/hos-claude-usage.rules.yml`~~ **Removed by Revision 2 (ADR A2-13):** no Prometheus rules file; `prometheus.yml` is not touched (`rule_files` stays commented; the `alertmanager` stanza is left alone).

**Placeholders only** (D17, AC-47): the repo carries env-var names and `.invalid`/`example.invalid` placeholders, never a real endpoint, secret, or datasource UID.

### 6.2 `grafana/provisioning/dashboards/hos.yaml`

```yaml
apiVersion: 1
providers:
  - name: hos
    orgId: 1
    folder: HOS
    type: file
    disableDeletion: true
    allowUiUpdates: false
    updateIntervalSeconds: 60
    options:
      path: /opt/hos-monitoring/contrib/monitoring/grafana/dashboards
      foldersFromFilesStructure: false
```

`path` points into the sparse clone (A2-14); `/opt/hos-monitoring` is the worked-example location, documented in the README.

### 6.3 `grafana/provisioning/alerting/hos-rules.yaml` — the 13 rules (A2-13, D17, D19; rule 13 per Human rulings H-1..H-4, H-7 / ADR A4-5)

**File structure (top to bottom):**
1. **Named-values header** (comment table; TD-O-13). Every duration and every PromQL range/horizon literal in the file is listed here with its meaning:

   | Name | Value | Used by |
   |---|---|---|
   | `hos_eval_interval` | `1m` | group `interval` |
   | `hos_for_immediate` | `0s` | PauseCondition, SettingsInvalid, ReadCostNonzero, ReadTokensNonzero, AlertingReloadFailed |
   | `hos_for_default` | `15m` | ReadFailing, MetricsAbsent, ReadCostUnknown, HistoryWriteFailing, TextfileError |
   | `hos_for_stale` | `5m` | PollStale |
   | `hos_for_sync` | `10m` | MonitoringSyncStale |
   | `hos_for_forecast` | `30m` | WeeklyTimeToThreshold |
   | `hos_forecast_range` | `6h` | WeeklyTimeToThreshold PromQL range |
   | `hos_forecast_horizon_s` | `86400` | WeeklyTimeToThreshold PromQL horizon |
   | `hos_query_range_s` | `600` | every query's `relativeTimeRange.from` |

2. **Anchors block** (primary mechanism, pending A2-21 verification): a top-level mapping `x-hos-named-values:` defining `&hos_eval_interval 1m`, `&hos_for_immediate 0s`, `&hos_for_default 15m`, `&hos_for_stale 5m`, `&hos_for_sync 10m`, `&hos_for_forecast 30m`, `&hos_query_range_s 600`. Every `for:`, `interval:` and `relativeTimeRange.from` is an alias (`*hos_for_default`, …). **PromQL strings cannot use anchors** (a YAML alias is a whole scalar), so `6h`/`86400` stay literal inside the forecast expression and are covered by the header table. Fallback if Grafana rejects anchors: inline values plus the header table, and the static test then checks every duration against the table (AC-45).
3. `apiVersion: 1`, then `groups:` with **one** group: `orgId: 1`, `name: hos-claude-usage`, `folder: HOS`, `interval: *hos_eval_interval`, `rules:`.

**Per-rule shape** (every rule):
- `uid`: the fixed uid below; `title`: the rule name; `condition: C`; `isPaused: false`.
- `data`: `A` = the Prometheus query (`datasourceUid: ${HOS_PROMETHEUS_DS_UID}`, `relativeTimeRange: {from: *hos_query_range_s, to: 0}`, `model: {refId: A, expr: <PromQL>, instant: true}`); `C` = `datasourceUid: __expr__`, `model: {refId: C, type: threshold, expression: A, conditions: [{evaluator: {type: gt, params: [0]}}]}`.
- **Every PromQL returns `1` (or a positive value) when firing and `0` or no series otherwise** (`bool` modifiers), so the one condition `C: A > 0` serves every rule and no rule carries a threshold literal (AC-45).
- `noDataState` / `execErrState` per the table, so a missing series fires **only** MetricsAbsent or MonitoringSyncStale (A2-13).
- `labels: {hos_alert: "true", severity: <sev>}`; `annotations: {summary: <text>, description: <text>}`. Templates in annotations must write `$$` for every literal `$` (`{{ $$labels.instance }}`, TD-VF-17). No URL anywhere.
- `notification_settings: {receiver: hos}` (rule-level simplified routing; **no notification-policy tree is provisioned**, A2-13).

| # | uid / title | PromQL `A` (exact) | for | noData / execErr | sev |
|---|---|---|---|---|---|
| 1 | `hos-pause-condition` / `HosClaudeUsagePauseCondition` | `hos_claude_usage_pause_condition == bool 1` | `*hos_for_immediate` | OK / KeepLast | critical |
| 2 | `hos-read-failing` / `HosClaudeUsageReadFailing` | `hos_claude_usage_read_ok == bool 0` | `*hos_for_default` | OK / KeepLast | warning |
| 3 | `hos-poll-stale` / `HosClaudeUsagePollStale` | `(time() - hos_claude_usage_poll_timestamp_seconds) > bool on(instance) hos_claude_usage_staleness_seconds` | `*hos_for_stale` | OK / KeepLast | critical |
| 4 | `hos-metrics-absent` / `HosClaudeUsageMetricsAbsent` | `absent(hos_claude_usage_poll_timestamp_seconds)` (TD-O-12) | `*hos_for_default` | **OK** (present ⇒ empty) / **Error** | critical |
| 5 | `hos-settings-invalid` / `HosClaudeUsageSettingsInvalid` | `hos_claude_usage_settings_valid == bool 0` | `*hos_for_immediate` | OK / KeepLast | critical |
| 6 | `hos-read-cost-nonzero` / `HosClaudeUsageReadCostNonzero` | `hos_claude_usage_read_cost_usd > bool 0` | `*hos_for_immediate` | OK / KeepLast | critical |
| 7 | `hos-read-tokens-nonzero` / `HosClaudeUsageReadTokensNonzero` | `hos_claude_usage_read_tokens > bool 0` | `*hos_for_immediate` | OK / KeepLast | critical |
| 8 | `hos-read-cost-unknown` / `HosClaudeUsageReadCostUnknown` | `((hos_claude_usage_read_ok == 1) unless on(instance) hos_claude_usage_read_cost_usd) or ((hos_claude_usage_read_ok == 1) unless on(instance) hos_claude_usage_read_tokens)` | `*hos_for_default` | OK / KeepLast | warning |
| 9 | `hos-history-write-failing` / `HosClaudeUsageHistoryWriteFailing` | `hos_claude_usage_history_write_ok == bool 0` | `*hos_for_default` | OK / KeepLast | warning |
| 10 | `hos-textfile-error` / `HosClaudeUsageTextfileError` | `node_textfile_scrape_error > bool 0` | `*hos_for_default` | OK / KeepLast | warning |
| 11 | `hos-monitoring-sync-stale` / `HosMonitoringSyncStale` | `(((time() - hos_monitoring_sync_last_success_timestamp_seconds) > bool on(instance) hos_monitoring_sync_stale_after_seconds) + on(instance) (1 - hos_monitoring_sync_ok)) or absent(hos_monitoring_sync_ok)` | `*hos_for_sync` | OK / **Error** | warning |
| 12 | `hos-weekly-time-to-threshold` / `HosClaudeUsageWeeklyTimeToThreshold` (optional, warning) | `predict_linear(hos_claude_usage_weekly_all_models_percent[6h], 86400) >= bool on(instance) hos_claude_usage_threshold_percent{limit="weekly_all"}` | `*hos_for_forecast` | OK / KeepLast | warning |

- `== bool 1`, `== bool 0`, `> bool 0` against boolean or must-be-zero gauges are semantics, not thresholds. Every comparison against a configurable limit is against a gauge (`staleness_seconds`, `threshold_percent`, `sync_stale_after_seconds`). **No literal `90` anywhere** (D19).
- `1 - hos_monitoring_sync_ok` maps `ok=0` to `1`; rule 11's sum is ≥ 1 when stale or failed; `or absent(…)` fires when the sync job never wrote.
- Rule 8 implements A2-8's "read_ok == 1 and either cost/token series absent".

| # | uid / title | PromQL `A` (exact) | for | noData / execErr | sev |
|---|---|---|---|---|---|
| 13 | `hos-monitoring-alerting-reload-failed` / `HosMonitoringAlertingReloadFailed` | `hos_monitoring_alerting_reload_ok == bool 0` | `*hos_for_immediate` | OK / KeepLast | critical |

**Human rulings H-1..H-4, H-7 (H-3, ADR A4-5).** Rule 13 fires when the last reload attempt failed and was rolled back (§6.6a). Without it, a pushed alerting change that Grafana rejected would leave `deployed_commit` advancing while monitrix runs the old rules, and nothing would signal it.

**Required set (H-2 replacement control, ADR A4-3).** Rules 1–9, 11 and 13 are each the human's only signal for their failure mode, and `tests/framework/test_monitoring_required_alerts.py` asserts them by UID (§9.4a). Two rules are not required:
- rule 10 (TextfileError) is redundant for HOS: a malformed HOS `.prom` drops its series, so rule 4 fires;
- rule 12 is an optional early warning, and rule 1 is the signal.

Both stay in the file.

### 6.4 `grafana/provisioning/alerting/hos-contact-point.yaml` (A2-13, D17)

`apiVersion: 1`; `contactPoints:` with one entry, `orgId: 1`, `name: hos`, and two receivers:

| uid | type | settings |
|---|---|---|
| `hos-email-webhook` | `webhook` | `url: ${HOS_ALERT_EMAIL_WEBHOOK_URL}`, `httpMethod: POST`, `authorization_scheme: Bearer`, `authorization_credentials: ${HOS_ALERT_EMAIL_WEBHOOK_SECRET}`; `disableResolveMessage: false` |
| `hos-sms-webhook` | `webhook` | `url: ${HOS_ALERT_SMS_WEBHOOK_URL}`, `httpMethod: POST`; `disableResolveMessage: false` |

- **Email** goes to the human's Cloudflare Worker, which validates the Bearer secret and sends the mail. The Worker's code lives **outside HOS**; the README documents only that it receives Grafana's standard webhook JSON.
- **SMS is a placeholder** until D-5. The README sets `HOS_ALERT_SMS_WEBHOOK_URL=https://sms-relay.example.invalid/hook` (RFC 6761 `.invalid`: DNS fails fast, so the integration errors immediately). The env var **must** be set to that placeholder rather than left empty, because an empty webhook URL may fail contact-point provisioning entirely (§6.9 gap). **The SMS integration must not block email:** Grafana delivers each integration of a contact point independently; S5's AC-43 run is performed with the placeholder in place, so the email's arrival is the proof.
- The secrets live **only** in Grafana's env file on monitrix (`/etc/default/grafana-server`, 0640 root:grafana) and the Worker's secrets.

### 6.5 `grafana/dashboards/hos-claude-usage.json` — specification (FR-46, AC-20) — Revision 2

**Top level:** classic dashboard JSON; `uid: "hos-claude-usage"`; `title: "HOS — Claude usage (proactive pause)"`; `tags: ["hos"]`; `editable: false`; `schemaVersion: 39`; `refresh: "1m"`; `time: {from: "now-7d", to: "now"}`. **No `__inputs`, no `__requires`, no `${DS_` string.**

**Templating:**
- `datasource`: `type: "datasource"`, `query: "prometheus"`.
- `instance`: `type: "textbox"`, default `faberix`.
- `window`: `type: "query"`, `query: "label_values(hos_claude_usage_window_requests{instance=\"$instance\"}, window)"`, `multi: true`, `includeAll: true`, `refresh: 2` (generic windows, A2-7).

Every panel/target: `"datasource": {"type": "prometheus", "uid": "${datasource}"}`.

**Every panel's `fieldConfig.defaults.thresholds`** is `{"mode": "absolute", "steps": [{"color": "green", "value": null}]}` and `custom.thresholdsStyle.mode` is `"off"`: Grafana's default `80` step must not appear (AC-45). Threshold lines come only from the gauge.

**Annotation** (besides the built-in): `name: "pause condition (machine)"`, `enable: true`, `iconColor: "red"`, `expr: hos_claude_usage_pause_condition{instance="$instance"} == 1`, `step: "60s"`, `titleFormat: "pause condition (machine)"`. Never "cycles paused".

**The four FR-46 panels:**

| # | Title / gridPos | Options | Targets (`expr` → `legendFormat`) | Description (exact) |
|---|---|---|---|---|
| 1 | `Usage sawtooth vs pause thresholds` / `{x:0,y:0,w:12,h:9}` | timeseries; unit `percent`; `min: 0`, no `max`; `spanNulls: false`; stacking `none`; overrides by refId D/E/F: dashed line, width 1 | A `hos_claude_usage_session_percent{instance="$instance"}` → `session %`; B `hos_claude_usage_weekly_all_models_percent{instance="$instance"}` → `weekly (all models) %`; C `hos_claude_usage_weekly_model_percent{instance="$instance"}` → `weekly {{model}} %`; D `hos_claude_usage_threshold_percent{instance="$instance",limit="session"}` → `session threshold`; E `…{limit="weekly_all"}` → `weekly (all) threshold`; F `…{limit="weekly_model"}` → `weekly per-model threshold` | "Raw values from claude -p /usage. Threshold lines are the configured values (hos_claude_usage_threshold_percent). Red annotations = pause condition (machine-level), not per-role cycle state. Gaps = failed reads." |
| 2 | `Early warning (predict_linear)` / `{x:0,y:9,w:12,h:8}` | timeseries; unit `percent`; stacking `none` | A `predict_linear(hos_claude_usage_session_percent{instance="$instance"}[1h], 3600)` → `session % +1h`; B `predict_linear(hos_claude_usage_weekly_all_models_percent{instance="$instance"}[6h], 86400)` → `weekly (all) % +24h`; C `predict_linear(hos_claude_usage_weekly_model_percent{instance="$instance"}[6h], 86400)` → `weekly {{model}} % +24h`; D/E/F as panel 1 | "Forecasts computed at query time; nothing derived is exported. Unreliable just after a window reset." |
| 3 | `Subagent attribution — top-N, $window` / `{x:0,y:17,w:12,h:9}`, `repeat: "window"`, `repeatDirection: "h"` | timeseries; stacking `normal` (attribution may stack); unit `percent`; override for B: unit `none`, right axis, stacking `none`, dashed | A `hos_claude_usage_top_subagent_percent{instance="$instance",window="$window"}` → `{{subagent}}`; B `hos_claude_usage_top_subagents_more{instance="$instance",window="$window"}` → `+K more (count)` | **Exactly:** "Top-N only and truncated (`+K more`, also plotted). A subagent leaving the list appears as a gap, not zero. Not a complete breakdown." |
| 4 | `Behaviors (independent, overlapping)` / `{x:12,y:0,w:12,h:9}` (alongside panel 1) | timeseries; **stacking `none` in `defaults.custom.stacking` and in every override**; `fillOpacity: 0`; unit `percent`; `spanNulls: false` | A `hos_claude_usage_subagent_heavy_percent{instance="$instance",window=~"$window"}` → `{{window}} subagent-heavy %`; B `hos_claude_usage_long_context_percent{…}` → `{{window}} >150k context %`; C `hos_claude_usage_long_session_percent{…}` → `{{window}} 8h+ sessions %` | **Exactly:** "Independent characteristics, not a breakdown; values overlap. Never sum or stack these. A missing line is a gap, not zero." |

**Additional panel 5** (not one of the four; health): `Check health and read cost` / `{x:12,y:9,w:12,h:8}`, stat panel: `hos_claude_usage_read_ok`, `time() - hos_claude_usage_poll_timestamp_seconds` vs `hos_claude_usage_staleness_seconds`, `time() - hos_claude_usage_last_success_timestamp_seconds` (huge = none on record), `hos_claude_usage_settings_valid`, `hos_claude_usage_history_write_ok`, `hos_claude_usage_read_cost_usd`, `hos_claude_usage_read_tokens`, `hos_claude_usage_read_failure` → `{{reason}}`.

No `rate(`, `increase(`, `delta(`, `deriv(`, `sum(` over behavior series. Only `predict_linear` and `time() -` (query-time).

### 6.6 monitrix sync job and reload units (A2-14, D9)

**`contrib/monitoring/monitrix/hos-monitoring-sync`** (bash; Linux only; installed by the human with `sudo install -m 0755 -o root -g root contrib/monitoring/monitrix/hos-monitoring-sync /usr/local/bin/hos-monitoring-sync`, **outside the clone**, so a pull can never change the code doing the pull). It runs as the unprivileged `hos-sync` user from that user's crontab:
`*/5 * * * *  /usr/local/bin/hos-monitoring-sync > /var/lib/hos-monitoring-sync/sync.last.log 2>&1` (the interval is the worked-example value; `>` not `>>`).

**Named values at the top of the script** (the only place they appear; each overridable by an env var of the same name, documented test-only):
`HOS_SYNC_REPO_URL=https://github.com/thurlow-research/HumanOversightSystem.git`, `HOS_SYNC_CLONE_DIR=/opt/hos-monitoring`, `HOS_SYNC_STATE_DIR=/var/lib/hos-monitoring-sync`, `HOS_SYNC_SPARSE_PATH=contrib/monitoring`, `HOS_SYNC_TIMEOUT_SECONDS=120`, `HOS_SYNC_STALE_AFTER_SECONDS=1800`. ~~`HOS_SYNC_RELOAD_SENTINEL=…`~~ **Removed (Human rulings H-1..H-4, H-7: H-3, ADR A4-4).** The path unit watches the alerting files themselves, so no sentinel is needed.

**Procedure** (`set -uo pipefail`, no `-e`):
- **Y1.** `PATH=/usr/local/bin:/usr/bin:/bin`; `umask 022`; `export GIT_TERMINAL_PROMPT=0`.
- **Y2.** mkdir lock `$HOS_SYNC_STATE_DIR/lock`, 600 s ceiling (the `hos-cron` idiom); held → exit 0.
- **Y3. Preconditions (read-only):** the clone is a git work tree; `git -C "$CLONE" config --get remote.origin.url` equals `HOS_SYNC_REPO_URL` and matches `^https://[^@]+$` (anonymous HTTPS, no credential in the URL); `git -C "$CLONE" sparse-checkout list` prints exactly `contrib/monitoring`. Any failure → `ok=0`, reason logged, go to Y7 (no mutation).
- **Y4.** `old=$(git -C "$CLONE" rev-parse HEAD)`.
- **Y5.** `timeout --kill-after=10 "$HOS_SYNC_TIMEOUT_SECONDS" git -c credential.helper= -C "$CLONE" pull --ff-only --quiet`. **This is the only command that mutates the clone.** Non-zero (incl. a non-fast-forward) → `ok=0`; the old content stays.
- **Y6.** On success: `new=$(git -C "$CLONE" rev-parse HEAD)`, `ok=1`, `last_success=now`. If `old≠new` and `git -C "$CLONE" diff --name-only "$old" "$new" -- contrib/monitoring/grafana/provisioning/alerting/` is non-empty, log `alerting files changed at $new — hos-grafana-alerting-reload.path will restart grafana-server`. The sync job writes nothing else for this (H-3: the path unit is triggered by `git pull` replacing the files).
- **Y7. Health gauges** → `$HOS_SYNC_STATE_DIR/hos_monitoring_sync.prom` via `.hos_monitoring_sync.prom.tmp` + rename (0644): `hos_monitoring_sync_ok` (1/0); `hos_monitoring_sync_last_success_timestamp_seconds` (carried from `$HOS_SYNC_STATE_DIR/state`'s `last_success_epoch=`; `0` if none); `hos_monitoring_sync_deployed_commit_info{commit="<HEAD sha>"} 1` (current HEAD, success or failure; omitted if HEAD cannot be read); `hos_monitoring_sync_stale_after_seconds` = `HOS_SYNC_STALE_AFTER_SECONDS`. All `gauge`, with HELP/TYPE. The state file is rewritten atomically.
- **Y8.** One summary line to stdout.

The gauges reach Prometheus through monitrix's own node_exporter textfile directory by the AD-10 owned-dir + symlink pattern (root step, §7.1; A2-21 #2 verifies scrape and symlink-follow).

### 6.6a Alerting reload: systemd path unit, service, reload script — Human rulings H-1..H-4, H-7 (H-3 confirmed, ADR A4-4, A4-5)

**Ruling:** a root systemd path unit on monitrix watches the provisioned alerting files and restarts grafana-server on change. All three files are installed **by copy** by the human: the units go to `/etc/systemd/system/` (mode 0644), and the script goes to `/usr/local/sbin/` (root, 0755). None of them is ever symlinked into the clone, so a pull can never change code that runs as root.

**`hos-grafana-alerting-reload.path`** (exact content):
```
[Unit]
Description=HOS: watch provisioned Grafana alerting files (ADR-1944 A4-4)

[Path]
PathChanged=/opt/hos-monitoring/contrib/monitoring/grafana/provisioning/alerting/hos-rules.yaml
PathChanged=/opt/hos-monitoring/contrib/monitoring/grafana/provisioning/alerting/hos-contact-point.yaml
Unit=hos-grafana-alerting-reload.service

[Install]
WantedBy=multi-user.target
```
- **`PathChanged=`, not `PathModified=`.** `PathChanged` fires when a writer **closes** the file, and on create, move or delete in the watched path's directory. `git pull` replaces a changed file (unlink, create, write, close), so each changed file triggers once, after it is complete. `PathModified=` would also fire on every `write(2)`, which means mid-file.
- A dashboard-only pull touches neither file and triggers nothing.
- These two `PathChanged=` lines are the **only** clone paths in either unit (`test_reload_units_reference_no_clone_path`).

**`hos-grafana-alerting-reload.service`** (exact content):
```
[Unit]
Description=HOS: copy alerting provisioning and restart grafana-server (ADR-1944 A4-4)
After=grafana-server.service
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hos-grafana-alerting-reload
TimeoutStartSec=300
```
- **Why `StartLimitIntervalSec=0`:** if systemd's start limit were hit, the path unit would go `failed` and silently stop watching. Flapping cannot occur, because the sync job's lock and 5-minute cadence bound triggers to one burst per pull.
- **Triggers during a run:** a trigger that arrives while the oneshot is activating is merged into the running job by systemd.
- **Why `TimeoutStartSec=300` is enough:** it must exceed settle plus two restart and health-check rounds: 15 + 2 × (restart + 120) s.

**`hos-grafana-alerting-reload`** (bash; Linux only; `set -uo pipefail`, no `-e`). **Named values at the top** (the only place they appear; each overridable by an env var of the same name, documented as test-only):
- `HOS_RELOAD_SOURCE_DIR=/opt/hos-monitoring/contrib/monitoring/grafana/provisioning/alerting`
- `HOS_RELOAD_FILES="hos-rules.yaml hos-contact-point.yaml"`
- `HOS_RELOAD_TARGET_DIR=/etc/grafana/provisioning/alerting`
- `HOS_RELOAD_SOURCE_USER=hos-sync`
- `HOS_RELOAD_STATE_DIR=/var/lib/hos-grafana-reload`
- `HOS_RELOAD_SETTLE_SECONDS=15`
- `HOS_RELOAD_MAX_BYTES=1048576`
- `HOS_RELOAD_HEALTH_URL=http://127.0.0.1:3000/api/health`
- `HOS_RELOAD_HEALTH_TIMEOUT_SECONDS=120`
- `HOS_RELOAD_GRAFANA_UNIT=grafana-server.service`

Procedure:
- **R1.** `PATH=/usr/sbin:/usr/bin:/sbin:/bin`; `umask 022`. Take the mkdir lock `$HOS_RELOAD_STATE_DIR/lock` with a 600 s ceiling; if it is held, exit 0 (the running job will see the final content after its settle).
- **R2. Settle (debounce).** `sleep "$HOS_RELOAD_SETTLE_SECONDS"`, so both files of one pull are complete.
- **R3. Stage.** For each file, run `runuser -u "$HOS_RELOAD_SOURCE_USER" -- cat -- "$HOS_RELOAD_SOURCE_DIR/<f>"` piped through `head -c $((HOS_RELOAD_MAX_BYTES+1))` into `$HOS_RELOAD_STATE_DIR/staged/<f>`.
  - Fail and make **no change** if any of these holds: non-zero exit, empty output, more than `HOS_RELOAD_MAX_BYTES`, or no line matching `^apiVersion: 1$`. Then go to R8 with `ok=0`.
  - **Why read as `hos-sync`:** a symlink committed into the repo can never make root copy a file the unprivileged clone owner could not already read.
- **R4. Idempotence.** If every staged file is byte-equal (`cmp -s`) to `$HOS_RELOAD_TARGET_DIR/<f>`, then: no restart, `ok=1`, `last_success=now`, go to R8. This covers spurious triggers and the initial run on an already-installed host.
- **R5. Back up.** Copy each existing installed file to `$HOS_RELOAD_STATE_DIR/prev/<f>`. Record which files were absent.
- **R6. Install.** For each file, `install -m 0640 -o root -g grafana staged/<f> "$HOS_RELOAD_TARGET_DIR/.<f>.hos-tmp"`, then `mv -f` it to `<f>`. The temp name does not end in `.yaml`/`.yml`, so Grafana's provisioning reader ignores it.
- **R7. Restart and check.** Run `systemctl restart "$HOS_RELOAD_GRAFANA_UNIT"`. Then, until `HOS_RELOAD_HEALTH_TIMEOUT_SECONDS` elapses, poll `curl -fsS --max-time 5 "$HOS_RELOAD_HEALTH_URL"` every 5 s. Healthy means HTTP 200, a body containing `"database": "ok"`, and `systemctl is-active` = `active`.
  - Healthy → `ok=1`, `last_success=now`.
  - Not healthy → **roll back**:
    1. restore each `prev/<f>` the same way as R6, and remove any file that was absent before;
    2. restart again and run the same health loop;
    3. set `ok=0` whatever the outcome;
    4. log to the journal whether the rollback restart was healthy.
- **R8. Gauges.** Write `$HOS_RELOAD_STATE_DIR/hos_grafana_alerting_reload.prom` (via `.hos_grafana_alerting_reload.prom.tmp` + rename, 0644). It holds `hos_monitoring_alerting_reload_ok` (1/0, last attempt) and `hos_monitoring_alerting_reload_last_success_timestamp_seconds` (carried from `$HOS_RELOAD_STATE_DIR/state`; `0` if none), both `gauge` with HELP/TYPE. Rewrite the state file atomically.
- **R9.** Print one summary line. Exit 0 if `ok=1`, 1 otherwise. Because start limiting is disabled, a failed run never disables the path unit.
- The script never runs `git`, never executes or sources anything under `/opt/hos-monitoring`, and writes only under `$HOS_RELOAD_STATE_DIR` and `$HOS_RELOAD_TARGET_DIR`.

The gauge file reaches Prometheus through monitrix's textfile directory by the AD-10 owned-dir + symlink pattern. The human creates `/var/lib/hos-grafana-reload` (root, 0755) and runs `ln -sfn /var/lib/hos-grafana-reload/hos_grafana_alerting_reload.prom <monitrix textfile dir>/`.

**Restart during an alert evaluation: why it is acceptable (ADR A4-4, binding).** Restarts happen only when a merged change touches the alerting files.
1. An evaluation killed mid-flight makes no state transition, and the next evaluation runs within one `hos_eval_interval` of start.
2. Grafana persists alert-instance state and the notification log and restores them at startup (V-R1), so `for:` timers and firing state carry over without a duplicate. If 13.2.3 does not restore them, the worst case is one duplicate email, or a delay of one `for`. That is 0 s for rules 1, 5, 6, 7 and 13. Both are safe-direction, and neither suppresses an alert.
3. A notification in flight at stop may be lost. The alert is still firing and is re-sent at the repeat interval. Residual: a delay of at most one repeat interval, only for an alert that fires inside the restart window.
4. Downtime is about 10–60 s. A pause that starts in the window is evaluated at the first post-start evaluation.
5. A bad pushed file cannot leave Grafana down: R7 rolls back, and rule 13 fires through the restored Grafana.
   - Residual: if Grafana fails even with the restored set, the fault is not the pushed change. Grafana liveness on monitrix is outside HOS (§6.8 item 11).

**Copy, not symlink (H-3 consequence).** The alerting files in `/etc/grafana/provisioning/alerting/` are R6 copies, so §6.9 gap 3 no longer applies to alerting. The dashboard provider (`/etc/grafana/provisioning/dashboards/hos.yaml`) remains a symlink into the clone (§6.7).

### 6.7 `contrib/monitoring/README.md` — monitrix runbook outline

1. **Purpose and boundary.** Worked example only (D17b). Never affects the pause. Not shipped by `hos_install.sh`. **Not protected surface** (Human rulings H-1..H-4, H-7: H-2 rejected). The required alerts are guarded by `tests/framework/test_monitoring_required_alerts.py` in the PR-required suite. Removing or weakening one means editing that test, and the PR must say so.
2. **Prerequisites.** S3 applied on faberix; `bin/hos-usage-poll --check` item 9 PASS; Prometheus job `linux_servers` already scrapes faberix (AD-11 (1), unchanged).
3. **One-time root steps on monitrix (human):**
   - create the `hos-sync` user (no login shell, no sudo);
   - `install -d -o hos-sync -g hos-sync -m 0755 /opt/hos-monitoring /var/lib/hos-monitoring-sync`;
   - as `hos-sync`: `git clone --filter=blob:none --sparse https://github.com/thurlow-research/HumanOversightSystem.git /opt/hos-monitoring` then `git -C /opt/hos-monitoring sparse-checkout set contrib/monitoring`;
   - install the sync script by copy (§6.6); add the `hos-sync` crontab line;
   - textfile gauges: `ln -sfn /var/lib/hos-monitoring-sync/hos_monitoring_sync.prom <monitrix textfile dir>/hos_monitoring_sync.prom` (after the §5.1-style probe on monitrix);
   - Grafana dashboard provider symlink: `ln -sfn /opt/hos-monitoring/contrib/monitoring/grafana/provisioning/dashboards/hos.yaml /etc/grafana/provisioning/dashboards/hos.yaml`. The alerting files are **not** symlinked: the reload script copies them (§6.6a);
   - Grafana env file `/etc/default/grafana-server` (0640 root:grafana): `HOS_PROMETHEUS_DS_UID=<uid of the Prometheus datasource>`, `HOS_ALERT_EMAIL_WEBHOOK_URL=<Worker URL>`, `HOS_ALERT_EMAIL_WEBHOOK_SECRET` (set to the shared secret; value never committed), `HOS_ALERT_SMS_WEBHOOK_URL=https://sms-relay.example.invalid/hook`;
   - **alerting reload: human-run install step (Human rulings H-1..H-4, H-7: H-3, §6.6a):**
     - `sudo install -d -o root -g root -m 0755 /var/lib/hos-grafana-reload`;
     - `sudo install -m 0755 -o root -g root contrib/monitoring/monitrix/hos-grafana-alerting-reload /usr/local/sbin/hos-grafana-alerting-reload`;
     - `sudo install -m 0644 -o root -g root contrib/monitoring/monitrix/hos-grafana-alerting-reload.{path,service} /etc/systemd/system/`;
     - `sudo systemctl daemon-reload`;
     - `sudo systemctl enable --now hos-grafana-alerting-reload.path`;
     - `sudo systemctl start hos-grafana-alerting-reload.service`. This first run copies the alerting files and restarts grafana-server; it replaces a manual restart;
     - `ln -sfn /var/lib/hos-grafana-reload/hos_grafana_alerting_reload.prom <monitrix textfile dir>/`;
     - verify `systemctl status hos-grafana-alerting-reload.path` is `active (waiting)`, and that `journalctl -u hos-grafana-alerting-reload.service` shows `ok=1`.
     - Re-run the three `install` lines by hand after any HOS change to these three files. The sync never updates them, by design.
4. **Verify** (the AC-20 / AC-50 record): dashboard in folder HOS; `journalctl -u grafana-server` shows no provisioning errors; the 13 rules under Alerting → folder HOS; `hos_monitoring_alerting_reload_ok == 1`; contact point `hos` with two integrations; Prometheus queries `hos_claude_usage_poll_timestamp_seconds{instance="faberix"}` (advancing ~5 min), `hos_claude_usage_read_ok == 1`, `hos_monitoring_sync_ok == 1`.
5. **Test alert (AC-43):** Contact points → `hos` → Test; record the email; SMS deferred (D-5).
6. **ESM purge note** (AD-11, verbatim sentence).
7. **Upgrading HOS on monitrix:** nothing to do for dashboards and alert rules. The sync pulls, and the path unit restarts grafana-server when an alerting file changes (H-3). If `HosMonitoringAlertingReloadFailed` fires, the pushed alerting change was rejected and rolled back; read `journalctl -u hos-grafana-alerting-reload.service`. Changes to the reload script, its units, or the sync script need the human re-install step (item 3).
8. **Host-specific values** (`faberix`, `/opt/hos-monitoring`, the monitrix textfile path) appear only in this README, the dashboard `instance` default, the provider `path`, and the sync script's named values.

### 6.8 `docs/MONITORING-WORKED-EXAMPLE.md` — "recommended setup" outline (A2-13, D17b, FR-63)

1. **What HOS guarantees vs what is an example.** Guaranteed: the poller, the gate, the metrics contract (§5.2 names, labels, absent-not-zero, versioned with reading `schema=1`; a rename is a breaking change recorded in release notes). Example: everything else.
2. **The chain:** faberix poller → `.prom` → node_exporter → monitrix Prometheus → Grafana alerting → contact point `hos` → Cloudflare Worker email + SMS relay (placeholder).
3. **faberix:** CRON-SETUP §2a (poller), §2a.8 (export).
4. **monitrix:** `contrib/monitoring/README.md`.
5. **Email Worker contract** (code outside HOS): accepts Grafana webhook JSON via POST, requires `Authorization: Bearer <secret>`, sends one email per notification; secret held only in the Worker and Grafana's env file.
6. **SMS relay** (D-5 open): e.g. a Grafana-webhook → Twilio relay; placeholder until chosen.
7. **Alert catalog:** the 13 rules, what each means, first response; which ones the required-alert guard test pins (§6.3).
8. **Fail-open warning (FR-67):** `fail_mode=open` is safe only once AC-43 and AC-44 are recorded. fail_mode=open without a running poller means no quota protection (H-1).
9. **Recovery:** history log and `export` backfill (§5.5).
10. **Adapting it:** other hosts (`instance` defaults, per-host `absent` rules, TD-O-12), other alerting stacks (consume the metrics contract directly).
11. **Known fragilities:** ESM node_exporter purge; Grafana alerting reload. The path unit, health check and rollback are in §6.6a, and rule 13 covers a rejected change. Grafana liveness itself is outside HOS: if Grafana is down, no alert fires at all, so add an external uptime check.
12. **Verification records:** AC-42, AC-43, AC-44, AC-50 (§7).
13. **Alerting reload install (H-3):** the human-run step from `contrib/monitoring/README.md` item 3, restated with the restart-acceptability summary (§6.6a).

### 6.9 Grafana verification gaps (A2-21 #1, extended; each blocks S5 only)

1. Rule-level `notification_settings.receiver` in file provisioning (A2-13).
2. YAML anchors and an unknown top-level `x-hos-named-values` key accepted (A2-13; fallback §6.3).
3. ~~Symlinks followed in `provisioning/alerting/`~~ **Moot for alerting** (H-3: the files are copied, §6.6a). The symlink question remains for `provisioning/dashboards/hos.yaml`.
4. Env interpolation in contact-point settings and `datasourceUid` (A2-13).
5. **New:** `$$` escaping in annotation templates (TD-VF-17).
6. **New:** an empty webhook URL's effect on provisioning (§6.4); the README mandates the `.invalid` placeholder regardless.
7. **New:** `execErrState: KeepLast` supported in 13.2.3 file provisioning; fallback `OK`.
8. **V-R1 (H-3):** alert-instance state and the notification log are restored across a grafana-server restart in 13.2.3. If they are not, the residual is one duplicate email or a delay of one `for` (§6.6a), which is acceptable. Record which one occurred.
9. **V-R2 (H-3):** `PathChanged=` on the clone paths fires on a real `git pull` on monitrix (AC-50 evidence: the service's journal entry after the trivial alerting change).
10. **V-R3 (H-3):** Grafana 13.2.3 exits non-zero, or fails `/api/health`, on an invalid alerting provisioning file. Rollback depends on this. Verify once with a deliberately broken copy on monitrix, outside the sync path.

### 6.10 Alarm-integrity control — Human rulings H-1..H-4, H-7 (H-2 rejected; ADR A4-2, A4-3)

~~S4 adds `contrib/monitoring/**` to `scripts/framework/protected_surfaces.txt`, AGENT-IDENTITY §9.0, and CODEOWNERS.~~ **Withdrawn.** #1944 adds **no** protected-surface entry.
- **Human rationale:** protected surfaces are already too broad (#1935), and human review must be restricted to what really matters.

**The threat still stands.** The alert rules are the human's only signal of a pause, a broken check, or a non-zero read cost, and they could be removed by the agent they watch. **The control is now a test**, `tests/framework/test_monitoring_required_alerts.py` (§9.4a), which runs in the PR-required suite. Removing, pausing, re-routing or re-querying a required alert requires a visible edit to that file, and the overseer's normal risk review catches it.
- **Residual, accepted by H-2:** a PR that edits both the rules and the guard test is not mechanically blocked. It is review-visible.

**S4 tier and merge:** MEDIUM, with an infra-reviewer pass and no human-merge requirement. The exception: if S4's diff touches `bin/` or any path already in `protected_surfaces.txt`, the existing CODEOWNERS rule applies. S4 as specified touches only `contrib/monitoring/**`, `docs/MONITORING-WORKED-EXAMPLE.md` and `tests/framework/**`, none of which is protected. The `bin/` decision code keeps its protection (AF-2, FR-49).

---

## 7. S5 — live delivery (no code) — Revision 2 (ADR A2-1, A2-18)

### 7.1 Human steps

On faberix: the S3 root step (§5.1). On monitrix: everything in §6.7 step 3. Then the records below, each posted on #1944.

### 7.2 Records, in order

1. **AC-50 (monitrix delivery):** `git -C /opt/hos-monitoring remote get-url origin` (https, no `@`); `git -C /opt/hos-monitoring sparse-checkout list` = `contrib/monitoring`; no deploy key on monitrix; `allowUiUpdates: false`; then a trivial pushed change under `contrib/monitoring/grafana/dashboards/` (e.g. a panel description) appears in Grafana within one sync interval + `updateIntervalSeconds`, with no UI import. **Human rulings H-1..H-4, H-7 (H-3):** next, a trivial pushed change under `contrib/monitoring/grafana/provisioning/alerting/` (e.g. one annotation description) must show:
   - the path unit fired: a `journalctl -u hos-grafana-alerting-reload.service` entry with `ok=1` (V-R2);
   - grafana-server restarted once;
   - the changed text visible under Alerting;
   - `hos_monitoring_alerting_reload_ok == 1`.

   Record V-R1: whether alert state survived the restart. Record V-R3: one deliberately invalid copy, tested by hand outside the sync path, rolls back and sets `reload_ok=0`. Then restore and confirm `reload_ok=1`.
2. **AC-42 (sync stale):** stop the sync (comment the `hos-sync` crontab line) for longer than `HOS_SYNC_STALE_AFTER_SECONDS` + `hos_for_sync`; `HosMonitoringSyncStale` fires and the email arrives; restore.
3. **AC-43 (test alert):** Contact point `hos` → Test, with the SMS placeholder in place; the email arrives (this also proves the SMS integration does not block email). SMS half deferred to D-5.
4. **AC-44 (definition of done; procedure confirmed by Human rulings H-1..H-4, H-7: H-4, ADR A4-6).** All autonomous work on faberix pauses for about 10–15 minutes, and running cycles finish first (D2). This is distinct from the S1 trip test (§3.15), which ran before any gate existed and paused nothing.
   - Preconditions: S1–S4 merged; records 1–3 done; `fail_mode=closed`; `HosClaudeUsagePauseCondition` loaded.
   - Read the current `session_pct` from `~/.hos/usage-pause/reading` (`S`). If `S = 0` no valid `session_threshold` (min 1) can trigger; wait until `S ≥ 1`, or use `weekly_threshold` against `weekly_all_pct` the same way.
   - `cp ~/.config/hos/usage-pause.conf ~/.config/hos/usage-pause.conf.ac44-backup` (if present); set `session_threshold=S` (or lower, ≥ 1).
   - Wait for the next poll (≤ `poll_interval_seconds`). Record: `reading` showing `poll_pause_condition=1` and `poll_pause_reason=session S% >= S`; a `[PAUSED-USAGE] session S% >= S` line in a `hos-cron` log; one `cycle-usage-paused` audit record; Grafana's alert-state history for `HosClaudeUsagePauseCondition`; **the email**, with its receipt time.
   - Restore the conf (or delete it if it was absent). Wait for the next poll: `poll_pause_condition=0`, the resolved notification email, and the next cycle's `[USAGE-OK]`.
   - Every autonomous cycle on faberix skips while the threshold is lowered (intended; H-4). `hos-cron` reads the current conf every cycle (AC-23), so cycles pause at the next cycle start. The alert follows one poll (at most `poll_interval_seconds`) plus one evaluation. After restore, cycles resume at the next cycle start.
   - SMS: record it in this same run once D-5 provides a provider. Until then the email alone satisfies AC-44.
5. **Fail-open gate:** only after records 3 and 4 may `fail_mode=open` ever be set on faberix (A2-18).

#1944 closes only when S1–S4 are merged **and** record 4 is posted.

---

## 8. Slices — Revision 2 (ADR A2-18)

| Slice | Contents | Tier | Merge | Depends on |
|---|---|---|---|---|
| **S1: Poller read path** | A (parse, envelope, settings incl. history keys, reading I/O, `evaluate_cycle`, poll view, `remote-cmd`, `last-raw`), B (poll P1–P7/P11/P12, `--check` items 1–8 **and 10** incl. `--capture-fixture`, `--print-setup`, `remote-cmd`), D, E, F, G (capture 2, D-1 derived, synthetic empty envelopes, AC-1 shape), H, I, J (S1-ST*), K, L §2a (minus 2a.0/2a.8/2a.11), M, N. **Exit:** AC-16, AC-48, AC-49, AC-25 recorded (§3.14), **then the H-7 trip test recorded (§3.15)**. | **HIGH** | HUMAN_REQUIRED (`bin/**`) | — |
| **S2: `hos-cron` gate** | C (§4 block at `:366/:367`, sentinel, log lines, `cycle-usage-paused`, **`cycle-usage-unchecked` (H-1)**), A `check`, O, P, J (S2-ST*), L §2a.0 + §7 rows, Q, Q2 (both carrying the exact H-1 sentence). AC-34/AC-35 whole-cycle tests. | **HIGH** | HUMAN_REQUIRED (`bin/**`, `docs/releases/**`; FR-49) | S1 merged and deployed; §3.14 exit records posted; **§3.15 trip-test record posted before S2 coding starts (H-7)**. H-1 is ruled and no longer a gate. |
| **S3: Metrics side path** | A `render_prom`/`write-prom`/history/prune/`export`, B P8–P10 + `--check` item 9 + `export`, R, golden `.prom` + history fixtures, isolation tests for all best-effort steps, L §2a.8 + §2a.11. **Precondition:** §5.1 probe recorded. | **MEDIUM** | HUMAN_REQUIRED (`bin/**`) | S1 |
| **S4: Monitoring worked example** | S (§6.1 layout incl. §6.6a reload script and units), S2', T, **T2 (required-alert guard, H-2)**, **T3 (reload tests, H-3)**, N. Static tests (AC-45, AC-47, never shipped, metric names match `METRIC_NAMES`, YAML/JSON structure); `integration`-marked promtool tests. ~~U~~ dropped (H-2). | **MEDIUM** | **Normal: overseer may merge** after an infra-reviewer pass. HUMAN_REQUIRED only if the diff touches `bin/` or another existing protected path (H-2, ADR A4-2). | S3 (metric names). H-2/H-3 ruled; no human-ruling gate. |
| **S5: Live delivery (no code)** | §7: monitrix steps incl. the §6.6a reload install, faberix S3 root step; records AC-50 (incl. V-R1/V-R2/V-R3), AC-42, AC-43, **AC-44** (H-4 procedure). | n/a | recorded on #1944 | S4 merged. H-4 ruled; no human-ruling gate. |

**Ordering (Human rulings H-1..H-4, H-7):** S1 is built, merged and deployed, then the §3.14 exit records, then **the §3.15 trip test (H-7)**, then S2 is built. Separately, S1 → S3 → S4 → S5. S2 may merge and run before S3–S5 (A2-1; fail-closed without alerting is safe), but S2 is never *built* before the trip-test record exists. **Build mode:** #1944 is built in the human's interactive worker session, not by autonomous pickup (`needs-ai` deliberately off). Review and merge rules are as in this table. **Definition of done:** S1–S4 merged **and** AC-44 recorded. A blocker on any slice keeps #1944 open and escalates (AD-1). `fail_mode=open` on faberix is forbidden until AC-43 and AC-44 are recorded.

---

## 9. Test plan — Revision 2 (ADR A2)

Every test runs in the PR suite (`not slow and not integration`) unless marked. Fixtures live in `tests/automation/fixtures/usage/`; `README.md` records each file's provenance and, for derived fixtures, the exact edit.

| Fixture | Content |
|---|---|
| `d1-loopback-2026-10-02.txt` | §1.9.1 verbatim (sha256 asserted) |
| `d1-envelope-derived.json` | §1.9.1 derivation |
| `capture2-envelope-2026-10-03.json` | §1.9.2 verbatim (sha256 asserted) |
| `capture2-plus-fields.json` | capture 2 with added top-level `type`, `subtype`, `is_error`, `session_id`, `duration_ms`, `num_turns` and a `usage.extra` key (AC-49 "added") |
| `empty-session-pr1450-test1.txt` | §1.9.3 verbatim |
| `empty-session-envelope-blank.json`, `empty-session-envelope-legacy-text.json` | §1.9.4 |
| `ac1-real-shape-envelope.json` | envelope whose `result` is D-1 lines 1–5 with AC-1 values (session 4, weekly 29, Fable 6), no breakdown |
| `envelope-session-only.json` / `envelope-weekly-only.json` / `envelope-no-model.json` / `envelope-two-models.json` | capture 2 with the weekly / session / Fable line removed / a second `Current week (Opus)` line added |
| `envelope-not-json.txt`, `envelope-result-missing.json`, `envelope-result-number.json`, `envelope-array.json`, `envelope-duplicate-result.json`, `envelope-nan-cost.json`, `envelope-negative-cost.json`, `envelope-tokens-partial.json` | §3.2 negative cases |
| `envelope-decimal-percent.json`, `envelope-over-100.json`, `envelope-ansi-crlf.json`, `envelope-breakdown-garbled.json`, `envelope-top-bad-item.json`, `envelope-third-window.json` (adds `Last 30d · …`) | parser edge cases |
| `expected-capture2.prom` (S3) | golden `render_prom` for capture 2, default settings |
| `history-*.jsonl` (S3) | multi-day history for prune/export |

### 9.1 S1 tests

**`test_usage_pause_envelope.py`** (A2-7, A2-8)
- `test_capture2_fixture_is_verbatim` (sha256, 1621 bytes).
- `test_capture2_envelope_ok_reads_three_fields` — `result` text, cost `0`, tokens 0/0/0/0, `read_tokens=0`.
- `test_extra_fields_ignored` (`capture2-plus-fields.json`) and `test_unknown_usage_fields_ignored` (AC-49 "added").
- `test_not_json_envelope_invalid`, `test_result_missing_envelope_invalid`, `test_result_not_string_envelope_invalid`, `test_top_level_array_envelope_invalid`, `test_duplicate_result_key_envelope_invalid`, `test_over_cap_envelope_invalid`, `test_no_fragment_scanning` (valid JSON embedded in text → `envelope_invalid`).
- `test_cost_nan_negative_bool_absent`, `test_tokens_partial_sum_absent`, `test_thinking_tokens_not_added`.
- `test_cost_recorded_on_failed_read` (`empty-session-envelope-*`, A2-8).

**`test_usage_pause_parse.py`**
- `test_d1_fixture_is_verbatim`; `test_d1_success_values` (6, 48, resets, marker); `test_d1_breakdown_*` (TD-VF-11).
- `test_capture2_success_values` — 11, 1, Fable 0, marker (TD-VF-15).
- `test_capture2_breakdown_24h` — 2290/175, 67/41/30, top list, more 0.
- `test_capture2_breakdown_7d_long_session_absent` — 13401/1433, 49/29, **no `long_session_pct_7d`**, top list of 8, more 1 (AC-18, D13).
- `test_generic_third_window_parsed` (A2-7), `test_window_cap_8`.
- `test_ac1_shape_success_no_breakdown` (AC-1, AC-18).
- `test_empty_session_envelopes_failed` — both §1.9.4 fixtures → `empty_session`, every numeric pct field None, cost 0 recorded (AC-4, FR-12, D13).
- `test_missing_weekly`, `test_missing_session` (AC-5); `test_unparseable_nonempty_result`.
- `test_decimal_percent_fails`, `test_over_100_accepted_unclamped`, `test_last_match_wins`, `test_ansi_crlf_stripped`, `test_unicode_digits_rejected`, `test_marker_absent_still_success`.
- `test_breakdown_line_garbled_isolated`, `test_breakdown_exception_isolated` (AC-18); `test_duplicate_window_absent`; `test_top_list_bad_item_whole_line_absent`.
- `test_no_model_line_success_absent` (AC-32); `test_two_models_parsed`.
- `test_model_name_raw_kept_control_stripped`.
- `test_window_length_never_parsed` (FR-20).
- `test_classify_transport` — timeout / spawn_failed / exited 255 → reasons; exited 0/1/2/124/127 → None (AC-6, AC-7).
- `test_read_usage_timeout_kills_process_group`, `test_read_usage_spawn_failed` (FR-7, AC-7).
- `test_read_usage_argv_ends_at_host` (A2-9).
- `test_read_usage_inherits_env_unchanged` — a sentinel variable set in the caller reaches the child; nothing is removed (D5, A2-9).

**`test_usage_pause_settings.py`**
- `test_missing_file_defaults` (90/90/90, closed, 300, 900, 60, 90, 100; FR-18, FR-29, AC-33).
- `test_each_key_valid_bounds` (both edges, all ten keys).
- `test_each_key_invalid` — 0, 101, `8O`, `090`, `+90`, `90 # c`, empty, Unicode digit, `fail_mode=Closed`, interval 90/3660, staleness 360/7201, timeout 4/271, `history_days=0`/`3651`, `history_max_mb=0`/`10241`, relative or `/../` `claude_bin` (FR-30, AC-33).
- `test_failopen_issue_after_now_unknown_key` (A2-10).
- `test_unknown_key_invalid`, `test_duplicate_key_invalid`, `test_malformed_line_invalid_line_n`, `test_unreadable_file`, `test_directory_path`, `test_non_utf8_file`, `test_first_violation_reported`, `test_never_raises`, `test_conf_path_never_from_hos_config_dir`.

**`test_usage_pause_reading.py`**
- `test_render_read_roundtrip`; `test_missing`; `test_truncated_*`; `test_schema_2_unknown`; `test_garbled_line_unreadable`; `test_duplicate_key_unreadable`; `test_oversize_unreadable`; `test_values_sanitized`; `test_atomic_write_no_tmp_left`.
- `test_failure_reading_has_no_pct_keys` (AC-4); `test_failure_reading_keeps_cost_tokens` (A2-8).
- `test_carryover_consecutive_and_last_success` (FR-32).
- `test_bash_crash_file_parses`.
- `test_poll_view_keys_present` — `poll_settings_status`, `poll_fail_mode`, thresholds, `poll_staleness_seconds`, `poll_pause_condition`, `poll_pause_reason` (A2-3, FR-33).
- `test_poll_view_invalid_settings` — `invalid:<key>`, `poll_pause_condition=1`, no `poll_*_threshold`, default staleness (A2-10).

**`test_usage_pause_decision.py`** — table-driven over §3.6 R1–R13:
- `test_session_90_pauses`, `test_weekly_90_pauses`, `test_89_89_runs`, `test_exact_90_is_reached` (AC-2, AC-28).
- `test_weekly_only_reason_names_weekly_all` (AC-3).
- `test_model_90_pauses_reason_exact` → `weekly_model:Fable 90% >= 90`; `test_model_89_runs`; `test_either_of_two_models_pauses` (AC-31).
- `test_absent_model_uses_two_limits` (AC-32).
- `test_reason_order_and_join` — session; weekly_all; models sorted; `; `; cap 200 (A2-6).
- `test_non_ascii_model_name_folded_in_verdict_only` (TD-O-14).
- `test_resume_all_below` (AC-10 unit, FR-23).
- `test_threshold_80` (AC-23 unit); `test_model_threshold_independent`.
- `test_stale_boundary_900_fresh_901_stale`, `test_future_boundary` (FR-36, AC-8).
- `test_missing_vs_poller_not_installed` (A2-15); `test_each_unusable_reason_distinct` (AC-8).
- `test_failure_closed_pauses`, `test_failure_open_runs_unchecked` (FR-21, FR-22, AC-9).
- `test_invalid_settings_pause_even_open` (AC-33).
- `test_success_missing_pct_is_unreadable`; `test_model_pct_without_name_unreadable`.
- `test_poll_view_equals_cycle_rule` — `poll_pause_condition` = `evaluate_cycle(now=run_epoch)` for every fixture (AC-52).

**`test_hos_usage_poll.py`** — real `bin/hos-usage-poll`, temp `HOME`/`HOS_STATE_DIR`, stubs in `$HOME/.local/bin`:
- `ssh` stub: records argv and env; **emulates sshd's forced command**: runs `$HOS_TEST_FORCED_COMMAND` if set (the `claude` stub path with its args), else prints nothing (a login shell on `/dev/null`); exits per `HOS_TEST_SSH_EXIT`.
- `claude` stub: records argv/env, prints a fixture file, optional sleep/exit code.
- `crontab` stub; `hos-cron` copies (with/without sentinel) under a temp dir.

Tests:
- `test_poll_success_writes_reading` (AC-1, FR-31, FR-33).
- `test_poll_ssh_argv_ends_at_host` (A2-9); `test_forced_command_argv_exact` — the claude stub saw exactly `-p /usage --output-format json` (AC-21, FR-2, FR-9, FR-14).
- `test_poll_no_forced_command_envelope_invalid` (A2-9).
- `test_poll_env_passed_through` — a caller-exported marker variable reaches the claude stub; P1 removed nothing (D5, AC-15 b by construction).
- `test_poll_ssh_255_ssh_failed`, `test_poll_key_missing_ssh_failed` (AC-6); `test_poll_spawn_failed` (ssh absent).
- `test_poll_needs_no_timeout_binary`; `test_poll_timeout` (**slow**, AC-7).
- `test_poll_remote_124_is_not_timeout`; `test_poll_nonzero_remote_exit_content_decides` (FR-11, FR-13, D12).
- `test_poll_failure_overwrites_success` (FR-32, AC-13).
- `test_poll_dir_bounded` — mixed outcomes; `$STATE/usage-pause` holds only §1.1's set (AC-13, FR-34).
- `test_poll_runs_while_project_suspended` (AC-12, AC-27, FR-24).
- `test_poll_lock_held_exits_without_write`, `test_poll_stale_lock_reclaimed_diagnostic`.
- `test_poll_lib_missing_bash_crash_file` (FR-32).
- `test_poll_invalid_settings_still_polls` (A2-10).
- `test_poll_emits_no_audit` (FR-34).
- `test_last_raw_success_then_failure` — after a success then an `unparseable` poll, `last-raw` bytes after line 1 equal the second poll's raw stdout; exactly one `last-raw` (AC-40, TD-O-16).
- `test_last_raw_transport_failure_holds_stderr_tail`.
- `test_last_raw_no_read_header_only` — **Architect round 2:** a success poll, then a key-missing poll → `last-raw` is the header only, `read=none … bytes=0`, and none of the first poll's bytes remain (A2-11).
- `test_last_raw_unwritable_reading_identical` (isolation, FR-54).
- `test_check_all_pass` (FR-48); `test_check_idempotent_writes_nothing` (AC-22); `test_check_missing_key_fails_nonzero` (AC-22); `test_check_key_mode_0644_fails`.
- `test_check_authorized_keys_exact_pass`; `test_check_restrict_option_fails` (AC-15 c); `test_check_command_mismatch_fails`; `test_check_two_lines_fail`.
- `test_check_crontab_append_fails`, `test_check_crontab_interval_mismatch_fails`, `test_check_crontab_path_not_self_fails` (FR-8, FR-34, FR-66).
- `test_check_claude_not_executable_item6`.
- `test_check_read_failure_fails`; `test_check_nonzero_cost_fails`; `test_check_absent_tokens_fails` (TD-O-20).
- `test_check_capture_fixture_writes_unfiltered_stdout` (byte-equal to the stub output; nothing else written) and `test_check_capture_fixture_refuses_existing_path` (AC-49).
- `test_check_gate_sentinel_all_copies` — two copies with sentinel + lib → PASS each; `test_check_gate_missing_in_one_copy_fails_naming_path`; `test_check_gate_lib_missing_fails`; `test_check_gate_home_expansion`; `test_check_gate_relative_path_fails`; `test_check_no_hos_cron_info` (A2-4, FR-51, AC-51).
- **Human rulings H-1..H-4, H-7 (H-7, §3.10 item 10):** `test_check_item10_over_threshold_info_pause_1` — the stub read is `session 7%`, the conf has `session_threshold=5`, and the output has `INFO 10 pause_condition=1 reason=session 7% >= 5` with `RESULT: PASS`. `test_check_item10_under_threshold_info_pause_0`. `test_check_item10_reason_equals_poll_view` — for the same read and conf, item 10's reason is byte-equal to the `poll_pause_reason` a real poll writes. `test_check_item10_invalid_settings` — `pause_condition=1 reason=settings_invalid:<key>`. `test_check_item10_skip_on_failed_read`. `test_check_item10_never_fails_result`.
- **Trip test (H-7) is a manual record, not a pytest** (§3.15). It is the gate on starting S2.
- `test_print_setup_never_mutates`; `test_print_setup_one_authorized_keys_line_no_restrict`; `test_print_setup_crontab_matches_interval_and_self` (FR-8, FR-66).
- `test_remote_cmd_output` (A2-9, P8).

**`tests/framework/test_usage_pause_static.py` (S1)**
- `S1-ST1 test_no_credential_sourcing_or_unsetting` — code lines of `bin/hos-usage-poll` and `bin/lib/usage_pause.py`: no `claude-auth.env`, no assignment to `CLAUDE_CODE_OAUTH_TOKEN` (the variable name immediately followed by `=`), no `source`/`.` of `~/.config/hos`, no `env -u`, no `unset `, no `os.environ.pop`, no `del os.environ`, no `unsetenv`, no `env=` keyword in any `Popen`/`run` call (AC-15 a/b, D5).
- `S1-ST2 test_poller_and_lib_never_reference_suspend_or_halt` (FR-24, AC-27).
- `S1-ST3 test_lib_never_uses_hos_config_dir`.
- `S1-ST4 test_lib_stdlib_only` — imports ⊆ `{__future__, argparse, dataclasses, datetime, json, math, os, pathlib, re, shlex, shutil, signal, stat, subprocess, sys, time, typing}`.
- `S1-ST5 test_sandbox_allowwrite_excludes_decision_inputs` — `/h/.hos/usage-pause/reading`, `/h/.config/hos/usage-pause.conf`, `/var/lib/hos-usage/x` (AF-1).
- `S1-ST6 test_consumer_files_list_both`.
- `S1-ST7 test_test_only_overrides_absent_from_runbook`.
- `S1-ST8 test_one_ssh_call_site` — no `ssh` invocation in `bin/hos-usage-poll`; one `Popen` call in the module; no `_TIMEOUT_BIN`, `timeout`, `gtimeout` in either.
- `S1-ST9 test_staleness_range_nonempty_for_every_interval`.
- `S1-ST10 test_defaults_block_single_and_no_threshold_literals` (§1.8; A2-10, D19).
- `S1-ST11 test_no_git_or_clone_assumption` — no `git ` / `.git` / `rev-parse` in the poller or the module (A2-16, FR-66).
- `S1-ST12 test_no_github_or_network` — no `gh `, `curl`, `github`, `urllib`, `http.client`, `socket` in the poller or module (FR-57).

**`test_agent_invocation_migration.py`:** T4.1 (exemption set unchanged; `usage_pause.py` not exempt — S1 code-review round 1 (S5), §11.5 C-10), `test_T4_1b_usage_read_has_one_call_site` (exactly one matching line, no `claude\s+(-p|--print)`), `test_T4_1b_remote_command_template_is_exact`, `test_T4_1b_ssh_argv_ends_at_host`; T4.2 unchanged (AC-26).
**`test_consumer_framework_files.py`:** `test_usage_pause_files_shipped`.

### 9.2 S2 tests

**`test_usage_pause_check_cli.py`**
- `test_verdict_line_matches_bash_ere` — the ERE is extracted from `bin/hos-cron` at test time (anchor extraction), so the two cannot drift; every class and a 200-char reason.
- `test_check_writes_nothing` — read-only state tree; tree hash unchanged (A2-2).
- `test_check_ignores_poll_view` — `poll_pause_condition=0` + `session_pct=95` → pause; `poll_pause_condition=1` + all under → run; `poll_settings_status=invalid:x` with a valid conf → run (A2-3).
- `test_check_uses_current_conf_not_poll_view` (AC-23).
- `test_check_crash_exit_70_no_stdout`.
- `test_reason_ascii_only_in_verdict` (TD-O-14).

**`test_hos_cron.py::TestUsagePauseGate`** — real launcher, §4.7 harness; worker and overseer parametrized:
- `test_under_threshold_runs_usage_ok_line` (AC-1 consumer side).
- `test_session_90_pauses_before_anything` — exit 0, one `[PAUSED-USAGE] session 90% >= 90` line, claude stub never ran (AC-2, AC-28, FR-26).
- `test_89_89_runs` (AC-2, AC-28).
- `test_weekly_90_reason_names_weekly_all` (AC-3).
- `test_model_90_pauses_reason_names_model` (AC-31).
- `test_no_model_line_runs` (AC-32).
- `test_empty_session_reading_pauses_closed` (AC-4).
- `test_failopen_failure_runs_unchecked_line` (AC-9, FR-22).
- `test_unusable_reasons_distinct` — stale / missing / poller_not_installed / truncated / garbled / schema / future (AC-8).
- `test_auto_resume_next_cycle` — paused at 92, then 40/30/Fable 10 → runs; no cleanup step (AC-10, FR-23).
- `test_human_suspend_marker_untouched` — marker + any reading → `[SUSPENDED]`, no `[PAUSED-USAGE]`, marker byte-identical; and over-threshold with no marker creates no file under `suspend/` (AC-11, FR-25, FR-51).
- `test_global_pause_all_projects_both_roles` — two projects × two roles, one over reading → four paused; `suspend/` tree unchanged; under reading → four run (AC-34, FR-27, FR-51).
- `test_paused_cycles_make_zero_network_calls` — over-threshold, fail-closed failure, invalid settings, `check_error`: no `gh`, `curl` or `get_app_token.sh` stub invocation at all (AC-35, FR-57).
- `test_running_cycles_gate_adds_no_github_calls` — fail-open failure and resume: the recorded `gh` argv list equals the list for the same scenario with a plain under-threshold reading; no `issue create/comment/edit`, no `needs-human`, no `[PAUSED]`/`[DEGRADED]` (AC-35, TD-O-22).
- `test_threshold_80_applies_without_new_poll_all_projects` (AC-23, FR-27).
- `test_transcript_wording_never_pauses` (AC-24, FR-28).
- `test_running_cycle_not_killed` — the claude stub rewrites the reading to 95% mid-session; the cycle completes; the next cycle pauses (AC-29, D2).
- `test_gate_precedes_token_mint_and_claude_auth` — `claude-auth.env` removed and `get_app_token.sh` stub set to fail + over reading → exit 0 paused, no mint attempted (FR-26, A2-4).
- `test_gate_precedes_deps_jitter_wakeup` — a wakeup file present + pause → the wakeup file still exists afterwards; deps-check stub not invoked (A2-4, TD-VF-12).
- `test_check_error_pauses_even_failopen` — lib missing from a copied launcher; `fail_mode=open` → `[PAUSED-USAGE] check_error (rc=…; fail_mode ignored)` (AD-7.5).
- `test_invalid_settings_pause_even_failopen_log_names_key` (AC-33, A2-3).
- `test_one_log_line_per_cycle` — exactly one of `[PAUSED-USAGE]`/`[USAGE-OK]`/`[USAGE-UNCHECKED]` per cycle (A2-5).
- `test_paused_cycle_audit_event_fields` — one `cycle-usage-paused` record per paused cycle, each field separate, `role` correct for overseer (A2-5, TD-VF-6, TD-VF-20).
- `test_running_cycle_no_usage_audit_event` (A2-5; `class=ok` only — H-1).
- `test_gate_writes_nothing_under_usage_pause` — the dir's tree hash is unchanged across paused and running cycles (A2-2, FR-26).
- `test_consumer_no_poller_pauses_reading_missing` and `test_consumer_no_poller_failopen_runs` (AC-46, FR-65).
- `test_gate_runs_on_bash_without_timeout` (bash 3.2 `set -u`).
- **Human rulings H-1..H-4, H-7 (H-1):** `test_failopen_unchecked_audit_event` — fail-open with each of `read_failed`, `reading_missing`, `reading_stale`, and `poller_not_installed` gives exactly one `cycle-usage-unchecked` record per cycle. Its fields are separate and in the §1.7 order, with `project` and `cycle_id` present and `role` correct for the overseer, and the cycle still runs. `test_ok_run_emits_no_unchecked_event`. `test_unchecked_event_synced_same_cycle` — the record is written before the `_sync_audit_logs` stage of the same cycle (ordering recorded by the harness).

**`test_usage_pause_static.py` (S2)**
- `S2-ST1 test_gate_block_clean` — §4.4's forbidden-token list (FR-25, FR-28, FR-57, AC-11, AC-27).
- `S2-ST2 test_gate_placement` — begin anchor after `_audit()`'s closing `}` and before `# ── Audit log sync`, `get_app_token.sh`, `_CLAUDE_AUTH_ENV=`, `_pre_jitter_deps_check` invocation, and the wakeup section (A2-4).
- `S2-ST3 test_reactive_breaker_code_unchanged` — unchanged from Revision 1 (AC-17, FR-40).
- `S2-ST4 test_check_invoked_once`.
- `S2-ST5 test_up_bound_expansions_set_u_safe`; **Architect round 2:** also asserts `_UP_CHECK_TIMEOUT_S=`/`_UP_CHECK_KILL_AFTER_S=` are defined once at the top of the block and that no other numeric literal except `0`/`1` appears in the block (D19).
- `S2-ST6 test_gate_never_reads_max_seconds` — no `HOS_CRON_MAX_SECONDS` in the block or the module (A2-17).
- `S2-ST7 test_sentinel_unique_and_second_line` (A2-4).
- `S2-ST8 test_check_never_reads_poll_keys` — no element of `CHECK_READ_KEYS` starts with `poll_`; the AST of `evaluate_cycle` and the `check` command handler contains no string constant starting with `poll_`; the gate block contains no `poll_` (A2-3).
- `S2-ST9 test_upgrade_checklist_and_release_note_present` — `docs/UPGRADE-PR-REVIEW-CHECKLIST.md` §H and `docs/releases/v0.7.0.md` "Upgrade notes" carry the setup step, the "upgrade stops autonomous work" fact, and the API-key fail-open statement (AC-46, FR-65). **H-1:** each also contains the exact sentence `fail_mode=open without a running poller means no quota protection`.
- `S2-ST10 test_runbook_content` — CRON-SETUP §2a has the fail-open-needs-alerting sentence, the exact H-1 sentence in §2a.0 and §2a.9, the every-copy check, the single install-path line, and (after S3) the backfill procedure (AC-51).

### 9.3 S3 tests

**`test_usage_pause_prom.py`**
- `test_capture2_golden` (FR-41, FR-42).
- `test_failure_render_absent_values` — no usage families; `read_ok 0`; `read_failure{reason="empty_session"} 1`; cost/tokens present (AC-4, AC-9, FR-44, A2-8).
- `test_no_breakdown_absent_not_zero`; `test_7d_long_session_absent` (AC-18).
- `test_never_succeeded_last_success_zero` (AC-52, D8).
- `test_threshold_limit_label_three_series`; `test_invalid_settings_no_threshold_settings_valid_0_staleness_default` (A2-12, AC-33).
- `test_pause_condition_from_poll_view` — closed failure 1, open failure 0, limit 1, invalid settings 1 (AC-52).
- `test_history_write_ok_only_on_rerender`.
- `test_gauge_only_no_counters_rates`, `test_no_sample_timestamps`, `test_label_sanitization` (AC-19, FR-43).
- `test_metric_names_constant_matches_table`.

**`test_usage_pause_history.py`**
- `test_line_has_every_reading_key` (A2-11); `test_line_single_write_o_append`; `test_line_cap_drop_order`; `test_file_modes_0700_0600`.
- `test_prune_days` — files older than `history_days` deleted though under the size cap (AC-36).
- `test_prune_size_oldest_first` — over cap with all files young → oldest deleted until within cap (AC-37); `test_whichever_first_governs`.
- `test_prune_never_today`; `test_prune_only_matching_names` (a `notes.txt` and a symlink survive).
- `test_history_write_ok_0_on_failure` (AC-39).

**`test_usage_pause_export.py`**
- `test_export_roundtrip_values_and_timestamps` — parse the output; every value and timestamp equals the history lines; absent stays absent (AC-38).
- `test_export_families_not_interleaved_ascending_ts`; `test_export_eof`; `test_export_torn_line_skipped_counted`; `test_export_duplicate_epoch_last_wins`; `test_export_labels_added_and_collision_rejected`; `test_export_range_inclusive`; `test_export_read_only`.
- `test_export_promtool_create_blocks` — **integration**: `promtool tsdb create-blocks-from openmetrics` succeeds; skipped when `promtool` is absent (AC-38).

**`test_hos_usage_poll.py` (S3 additions)**
- `test_write_order_reading_prom_history_rerender_lastraw` — recorded timestamps/ordering (FR-54, AC-39).
- `test_prom_unwritable_reading_and_decision_identical`, `test_history_unwritable_reading_and_decision_identical`, `test_prune_failure_history_write_ok_0` (AC-39, A2-11).
- `test_prom_dir_absent_not_configured`; `test_prom_atomic_no_tmp_left`; `test_two_polls_one_prom` (AC-13, FR-45).
- `test_check_item9_*` (symlink / fallback / both / neither / skip).
- `S3-ST1` (static): no `socket`, `http.server`, `listen`, `bind` (AC-19).

### 9.4 S4 tests — `tests/framework/test_contrib_monitoring.py`, `tests/framework/test_monitoring_sync.py`

- `test_rules_yaml_parses_one_group_thirteen_rules` — exact uids and titles, rule 13 included (FR-62, AC-47; H-3).
- `test_every_rule_receiver_hos_no_policy_tree` (AC-47, A2-13).
- `test_every_rule_condition_c_gt_0_and_bool_expr` (§6.3).
- `test_rule_exprs_exact` — each `expr` equals §6.3.
- `test_no_literal_threshold_in_rules` — in every `expr`, a comparison operator's literal operand ∈ {0, 1}; no `90` anywhere; `threshold` nodes only `gt 0` (AC-45, FR-64).
- `test_named_values_header_covers_every_duration` — every `for`, `interval`, `relativeTimeRange.from`, and every PromQL range/horizon literal appears in the header table (AC-45, TD-O-13).
- `test_nodata_error_states` — per §6.3 (A2-13).
- `test_dollar_escaping` — every `$` in the alerting YAML is `$$` or a `${HOS_[A-Z0-9_]+}` reference from the allowed set (TD-VF-17).
- `test_contact_point_two_webhooks_env_refs` — `hos-email-webhook` (Bearer, URL and secret env refs) and `hos-sms-webhook` (URL env ref) (FR-61, AC-47).
- `test_no_real_endpoints_or_secrets` — under `contrib/monitoring/` and `docs/MONITORING-WORKED-EXAMPLE.md`: no `https?://` except `https://github.com/thurlow-research/HumanOversightSystem.git` (public clone URL) and `*.invalid`/`example.invalid` placeholders; no token-shaped strings (`[A-Za-z0-9+/_-]{32,}`, `ghp_`, `sk-`, `Bearer [A-Za-z0-9]`) (AC-47, D17).
- `test_rules_and_dashboard_metric_names_exist` — every `hos_claude_usage_*` token is in `METRIC_NAMES`; every `hos_monitoring_sync_*` token is in the sync script's gauge list.
- `test_alert_exprs_promtool` — **integration**: wrap each `expr` in a synthetic Prometheus rule file and run `promtool check rules` (PromQL syntax); skipped when absent.
- `test_provider_yaml` — `allowUiUpdates: false`, path into the clone (AC-50, FR-58).
- `test_dashboard_json_parses_fixed_uid_no_inputs` (AC-20).
- `test_dashboard_variables` — datasource, instance (default faberix), window (query, multi).
- `test_four_panels_exact_exprs` (FR-46, AC-20).
- `test_threshold_lines_from_gauge_three_limits`; `test_no_threshold_steps_with_values` (AC-20, AC-45).
- `test_predict_linear_panel` (AC-20).
- `test_pause_annotation_machine` (AC-20).
- `test_subagent_panel_repeat_by_window_truncation_text` (AF-6).
- `test_behaviors_panel_three_unstacked_text` — panel and every override `stacking.mode == "none"`, `fillOpacity == 0`, exact description (AF-6).
- `test_no_rate_increase_delta` (FR-43).
- `test_contrib_never_shipped` — no `framework_consumer_files.txt` entry starts with `contrib/`; `hos_install.sh` has no `contrib` token (AC-47, FR-58).
- `test_reload_units_reference_no_clone_path` (A2-14; H-3) — the only clone paths in either unit are the path unit's two `PathChanged=` lines; the service's `ExecStart` is `/usr/local/sbin/hos-grafana-alerting-reload`.
- ~~`test_protected_surface_entry`~~ **Removed** (H-2 rejected). In its place: `test_contrib_monitoring_not_protected` — no `protected_surfaces.txt` line matches `contrib/` (this records the H-2 ruling, so a later re-add is a visible change).
- `test_host_values_only_where_allowed` (§6.7 item 8).
- **`test_monitoring_sync.py`** (local bare repo + clone, `file://` URL via the test-only override, `HOS_SYNC_*` overrides into a temp dir): `test_ff_pull_updates_and_gauges` (ok 1, commit info = new HEAD, stale_after); `test_non_ff_refused_content_kept` (ok 0, old HEAD kept, last_success carried); `test_alerting_change_logged_no_sentinel` (H-3: no sentinel or other file written for reload) / `test_dashboard_only_change_no_reload_log`; `test_wrong_remote_or_sparse_refuses_without_mutation`; `test_credential_in_url_refused`; `test_first_run_last_success_zero`; `test_only_pull_mutates` (static: no `git` subcommand other than `pull`, `rev-parse`, `diff`, `config --get`, `sparse-checkout list`) (AC-42 structure, AC-50, FR-59).

### 9.4a Required-alert guard — `tests/framework/test_monitoring_required_alerts.py` — Human rulings H-1..H-4, H-7 (H-2 replacement control, ADR A4-3)

This file is in the PR-required suite (`scripts/framework/run_tests_inner_loop.sh`, run by `.github/workflows/tests.yml`).
- **No markers.** It has no `slow`, `integration`, `skip` or `xfail` marker. A missing rules or contact-point file **fails**; it does not skip. PyYAML is a pinned requirement, so an import failure is an error.
- **Docstring.** It cites H-2, says that removing or weakening an entry changes the human's alerting coverage, and says the PR must say so.
- **`REQUIRED_ALERTS`** is a literal dict in this file, never imported from `contrib/`. It maps each UID to its metric anchor (§6.3 required set; ADR A4-3 table): `hos-pause-condition`, `hos-read-failing`, `hos-poll-stale`, `hos-metrics-absent`, `hos-settings-invalid`, `hos-read-cost-nonzero`, `hos-read-tokens-nonzero`, `hos-read-cost-unknown`, `hos-history-write-failing`, `hos-monitoring-sync-stale`, `hos-monitoring-alerting-reload-failed`.

Tests:
- `test_required_alert_rules_present_by_uid` — each required UID appears exactly once in `hos-rules.yaml`.
- `test_required_alert_rules_enabled_and_routed` — each required rule has `isPaused: false`, `notification_settings.receiver == "hos"`, and `condition == "C"`. Pausing or re-routing counts as removal.
- `test_required_alert_rules_query_their_metric` — the refId `A` `expr` contains the anchor metric name. Exact expressions stay pinned by `test_rule_exprs_exact`.
- `test_contact_point_has_email_and_sms_integrations` — contact point `hos` has `hos-email-webhook` (`type: webhook`, `url: ${HOS_ALERT_EMAIL_WEBHOOK_URL}`, `authorization_scheme: Bearer`) **and** `hos-sms-webhook` (`type: webhook`, `url: ${HOS_ALERT_SMS_WEBHOOK_URL}`).

### 9.4b Reload script and units — `tests/framework/test_grafana_alerting_reload.py` — Human rulings H-1..H-4, H-7 (H-3, §6.6a)

Runs the real script with `HOS_RELOAD_*` overrides into a temp dir. `runuser`, `systemctl` and `curl` are PATH stubs that record their argv. Settle is 0 in tests.
- `test_unchanged_files_no_restart` (R4) and `test_changed_files_installed_and_restarted`, which checks mode 0640, the temp-name-then-rename install, and exactly one restart.
- `test_source_read_as_source_user` — every source read goes through `runuser -u hos-sync -- cat --`, and nothing reads the source directly as root.
- `test_oversize_or_empty_or_no_apiversion_refused_no_change`.
- `test_health_fail_rolls_back_and_ok_0` — the previous copies are restored byte-equal, two restarts occur, and `reload_ok 0` is written.
- `test_rollback_removes_previously_absent_file`.
- `test_gauges_atomic_and_last_success_carried`.
- `test_lock_held_exits_0_no_change`.
- `test_never_runs_git_or_clone_code` (static).
- `test_path_unit_pathchanged_exact_two_files`, `test_service_oneshot_start_limit_disabled`, and `test_named_values_only_at_top` (static).

**AC-20, AC-42, AC-43, AC-44, AC-50 live halves are S5 records (§7).**

---

## 10. Traceability — every FR and AC — Revision 2 (ADR A2)

| Req | TD § | Test(s) / record |
|---|---|---|
| FR-1 | §3–§8 (no off switch; S1–S5; AC-44 = done) | whole suite; §3.14, §7 records |
| FR-2 | §3.2, §3.3, §3.8 | `test_forced_command_argv_exact`, `test_capture2_envelope_ok_reads_three_fields`, `test_extra_fields_ignored` |
| FR-3 | §3.8, §3.10 item 2, §3.11 | `test_check_authorized_keys_exact_pass`, AC-48 record |
| FR-4 | §3.7 P1, §3.8 | S1-ST1, `test_poll_env_passed_through`, `test_read_usage_inherits_env_unchanged` |
| FR-5 | §3.8 (`-n`, `RequestTTY=no`) | `test_poll_ssh_argv_ends_at_host` |
| FR-6 | §3.7 P1 | `test_poll_success_writes_reading` (minimal PATH) |
| FR-7 | §3.1 `read_usage`, §3.8 | `test_read_usage_timeout_kills_process_group`, `test_poll_timeout`, `test_poll_needs_no_timeout_binary` |
| FR-8 | §1.8, §3.10 item 5, §3.11 | `test_check_crontab_interval_mismatch_fails`, `test_print_setup_crontab_matches_interval_and_self` |
| FR-9 | §3.2, §3.10 item 7, §6.3 rules 6–8 | `test_forced_command_argv_exact`, `test_check_nonzero_cost_fails`, AC-25 record |
| FR-10 | §3.3 | `test_usage_pause_parse.py` |
| FR-11 | §3.4 | `test_missing_weekly`, `test_missing_session`, `test_poll_nonzero_remote_exit_content_decides` |
| FR-12 | §3.4 step 4, §1.9.4 | `test_empty_session_envelopes_failed` |
| FR-13 | §3.4 | `test_poll_remote_124_is_not_timeout`, `test_poll_nonzero_remote_exit_content_decides` |
| FR-14 | §3.4 (no fallback path) | `test_forced_command_argv_exact` |
| FR-15 | §1.3 `parsed_via` | `test_poll_success_writes_reading` |
| FR-16 | §3.3, §3.6 R9 | `test_two_models_parsed`, `test_no_model_line_success_absent`, `test_model_90_pauses_reason_exact` |
| FR-17 | §3.3 breakdown | `test_capture2_breakdown_*`, `test_breakdown_*_isolated`, `test_generic_third_window_parsed` |
| FR-18 | §1.8 | `test_missing_file_defaults` |
| FR-19 | §3.6 R9, §1.2 | `test_exact_90_is_reached`, `test_reason_order_and_join`, `test_model_90_pauses_reason_exact` |
| FR-20 | §3.3 | `test_window_length_never_parsed` |
| FR-21 | §3.6 R12 | `test_failure_closed_pauses`, `test_empty_session_reading_pauses_closed` |
| FR-22 | §3.6 R13, §4.4 G3, G4 (H-1) | `test_failure_open_runs_unchecked`, `test_failopen_failure_runs_unchecked_line`, `test_failopen_unchecked_audit_event` (H-1) |
| FR-23 | §3.6 R10 | `test_resume_all_below`, `test_auto_resume_next_cycle` |
| FR-24 | §3.7 | `test_poll_runs_while_project_suspended`, S1-ST2 |
| FR-25 | §4.4 | `test_human_suspend_marker_untouched`, S2-ST1 |
| FR-26 | §4.1, §4.4 | `test_session_90_pauses_before_anything`, `test_gate_precedes_token_mint_and_claude_auth`, `test_gate_writes_nothing_under_usage_pause`, S2-ST2 |
| FR-27 | §1.1, §1.8, §4.3 | `test_global_pause_all_projects_both_roles`, `test_threshold_80_applies_without_new_poll_all_projects`, `test_conf_path_never_from_hos_config_dir` |
| FR-28 | §4.4 | `test_transcript_wording_never_pauses` |
| FR-29 | §1.8 | `test_usage_pause_settings.py` |
| FR-30 | §1.8, §3.6 R1, §4.4 G3 | `test_each_key_invalid`, `test_invalid_settings_pause_even_failopen_log_names_key`, `test_poll_view_invalid_settings` |
| FR-31 | §1.1, §1.3, §1.5 | `test_render_read_roundtrip`, `test_gate_writes_nothing_under_usage_pause` |
| FR-32 | §1.3, §3.7 P12 | `test_poll_failure_overwrites_success`, `test_poll_lib_missing_bash_crash_file` |
| FR-33 | §1.3 (incl. `poll_*`) | `test_poll_view_keys_present`, `test_poll_success_writes_reading` |
| FR-34 | §1.1 bound, §1.7, §3.10 item 5, §5.4 | `test_poll_dir_bounded`, `test_poll_emits_no_audit`, `test_check_crontab_append_fails` |
| FR-35 | §3.6 (`CHECK_READ_KEYS`), §5.4 | S2-ST8, `test_check_ignores_poll_view` |
| FR-36 | §3.6 R2–R8 | `test_stale_boundary_*`, `test_unusable_reasons_distinct` |
| FR-37 | **SUPERSEDED (D7)** — no issue filing | covered negatively by AC-35 tests |
| FR-38 | **SUPERSEDED (D7)** | — |
| FR-39 | **SUPERSEDED (D7)** — the "why" is the reason (§1.2) | `test_reason_order_and_join` |
| FR-40 | §2 "not touched" | S2-ST3 |
| FR-41 | §5.1–§5.3 | `test_capture2_golden`, §5.1 record |
| FR-42 | §5.2 | `test_capture2_golden`, `test_threshold_limit_label_three_series`, `test_pause_condition_from_poll_view` |
| FR-43 | §5.2, §6.5 | `test_gauge_only_no_counters_rates`, `test_no_rate_increase_delta` |
| FR-44 | §1.3, §5.2 | `test_failure_render_absent_values`, `test_7d_long_session_absent`, `test_never_succeeded_last_success_zero` |
| FR-45 | §5.1, §5.3 | `test_prom_atomic_no_tmp_left`, `test_prom_unwritable_reading_and_decision_identical` |
| FR-46 | §6.5 | `test_four_panels_exact_exprs` |
| FR-47 | §3.11, §3.13, §2 E | `test_print_setup_never_mutates` |
| FR-48 | §3.10 | `test_check_*` |
| FR-49 | §8 tiers/merge, §6.10 | CODEOWNERS (`bin/**`); `contrib/monitoring/**` deliberately not protected (H-2): `test_contrib_monitoring_not_protected`, §9.4a guard |
| FR-50 | §3.7, §3.11 | `test_poll_*`, `test_print_setup_crontab_matches_interval_and_self` |
| FR-51 | §4, §3.10 item 8 | `test_global_pause_all_projects_both_roles`, `test_human_suspend_marker_untouched`, `test_check_gate_*` |
| FR-52 | §5.4 | `test_usage_pause_history.py` |
| FR-53 | §5.5 | `test_usage_pause_export.py` |
| FR-54 | §3.7 P7–P11 | `test_write_order_reading_prom_history_rerender_lastraw`, isolation tests |
| FR-55 | §1.6, §3.7 P11 | `test_last_raw_success_then_failure` |
| FR-56 | §3.2, §5.2 #11–12 | `test_capture2_envelope_ok_reads_three_fields`, `test_cost_recorded_on_failed_read` |
| FR-57 | §4.4, §4.6 (removed) | `test_paused_cycles_make_zero_network_calls`, S1-ST12, S2-ST1 |
| FR-58 | §6.2–§6.5, §6.6a (H-3 reload) | `test_provider_yaml`, `test_contrib_never_shipped`, `test_grafana_alerting_reload.py`, AC-50 record (incl. V-R1–V-R3); requirement text to be corrected by pm-agent (ADR A4-9 item 8) |
| FR-59 | §6.6 | `test_monitoring_sync.py`, AC-50 record |
| FR-60 | §6.1, §6.3 | `test_rules_yaml_parses_one_group_thirteen_rules` |
| FR-61 | §6.4 | `test_contact_point_two_webhooks_env_refs`, `test_no_real_endpoints_or_secrets`, AC-43 record |
| FR-62 | §6.3, §9.4a (H-2) | `test_rules_yaml_parses_one_group_thirteen_rules`, `test_rule_exprs_exact`, `test_required_alert_rules_present_by_uid`, `test_required_alert_rules_enabled_and_routed`, `test_required_alert_rules_query_their_metric` |
| FR-63 | §6.8, §6.7 | doc review (S4) |
| FR-64 | §1.8 block, §6.3, §6.5 | S1-ST10, `test_no_literal_threshold_in_rules`, `test_no_threshold_steps_with_values` |
| FR-65 | §4.5 (incl. H-1 sentence) | `test_consumer_no_poller_*`, S2-ST9 (exact H-1 sentence) |
| FR-66 | §3.7 P2, §3.11 block 5 | S1-ST11, `test_check_crontab_path_not_self_fails` |
| FR-67 | §3.13 2a.9, §7.2 item 5 | S2-ST10 |
| AC-1 | §3.3, §3.6, §5.2 | `test_ac1_shape_success_no_breakdown`, `test_poll_success_writes_reading`, `test_under_threshold_runs_usage_ok_line` |
| AC-2 | §3.6 | `test_session_90_pauses`, `test_89_89_runs` (unit + gate) |
| AC-3 | §3.6, §4.4 G3 | `test_weekly_only_reason_names_weekly_all`, `test_weekly_90_reason_names_weekly_all` |
| AC-4 | §3.4, §1.3, §5.2 | `test_empty_session_envelopes_failed`, `test_failure_reading_has_no_pct_keys`, `test_failure_render_absent_values`, `test_empty_session_reading_pauses_closed` |
| AC-5 | §3.4 | `test_missing_weekly`, `test_missing_session` |
| AC-6 | §3.4, §3.7 P5 | `test_poll_ssh_255_ssh_failed`, `test_poll_key_missing_ssh_failed` |
| AC-7 | §3.1, §3.8 | `test_poll_timeout` (slow), `test_read_usage_timeout_kills_process_group` |
| AC-8 | §3.6 | `test_each_unusable_reason_distinct`, `test_unusable_reasons_distinct` |
| AC-9 | §3.6 R13, §4.4 G4, §5.2 | `test_failopen_failure_runs_unchecked_line`, `test_failopen_unchecked_audit_event` (H-1), `test_failure_render_absent_values`, `test_paused_cycles_make_zero_network_calls` |
| AC-10 | §3.6 R10 | `test_auto_resume_next_cycle` |
| AC-11 | §4.1, §4.4 | `test_human_suspend_marker_untouched` |
| AC-12 | §3.7 | `test_poll_runs_while_project_suspended` |
| AC-13 | §1.1, §5.4 | `test_poll_dir_bounded`, `test_two_polls_one_prom`, `test_gate_writes_nothing_under_usage_pause` |
| AC-14 | **SUPERSEDED (D7)**, replaced by AC-35 | — |
| AC-15 | §3.8, §3.10 item 2 | S1-ST1 (a), `test_poll_env_passed_through` (b), `test_check_restrict_option_fails` (c) |
| AC-16 | §3.14 item 4 | manual record (S1 exit) |
| AC-17 | §2 | S2-ST3 |
| AC-18 | §3.3 | `test_ac1_shape_success_no_breakdown`, `test_capture2_breakdown_7d_long_session_absent`, `test_7d_long_session_absent` |
| AC-19 | §5.2 | `test_gauge_only_no_counters_rates`, S3-ST1 |
| AC-20 | §6.5, §6.7 step 4 | `test_four_panels_exact_exprs`, `test_threshold_lines_from_gauge_three_limits`, `test_predict_linear_panel`, `test_pause_annotation_machine`, S5 provisioning record |
| AC-21 | §3.4, §3.8 | `test_forced_command_argv_exact` |
| AC-22 | §3.10 | `test_check_idempotent_writes_nothing`, `test_check_missing_key_fails_nonzero` |
| AC-23 | §4.3 (current conf) | `test_threshold_80`, `test_check_uses_current_conf_not_poll_view`, `test_threshold_80_applies_without_new_poll_all_projects` |
| AC-24 | §4.4 | `test_transcript_wording_never_pauses` |
| AC-25 | §3.14 item 5, §6.3 rules 6–7 | AC-25 record + `test_rules_yaml_parses_one_group_thirteen_rules` |
| AC-26 | §3.12 | full PR suite incl. T4.1/T4.1b/T4.2 |
| AC-27 | §3.7, §4.4 | `test_poll_runs_while_project_suspended`, S1-ST2, S2-ST1, T4.1b |
| AC-28 | §3.6 | `test_exact_90_is_reached`, `test_session_90_pauses_before_anything` |
| AC-29 | §4.4 (cycle start only) | `test_running_cycle_not_killed`, S2-ST6 |
| AC-30 | **SUPERSEDED (D3, D7)**, replaced by AC-35/AC-47 | — |
| AC-31 | §3.6 R9 | `test_model_90_pauses_reason_exact`, `test_either_of_two_models_pauses`, `test_model_90_pauses_reason_names_model` |
| AC-32 | §3.3, §3.6 | `test_absent_model_uses_two_limits`, `test_no_model_line_runs` |
| AC-33 | §1.8, §3.6 R1 | `test_each_key_invalid`, `test_invalid_settings_pause_even_failopen_log_names_key`, `test_invalid_settings_no_threshold_settings_valid_0_staleness_default` |
| AC-34 | §4 | `test_global_pause_all_projects_both_roles` |
| AC-35 | §4.1, §4.4 | `test_paused_cycles_make_zero_network_calls`, `test_running_cycles_gate_adds_no_github_calls` |
| AC-36 | §5.4 | `test_prune_days` |
| AC-37 | §5.4 | `test_prune_size_oldest_first`, `test_whichever_first_governs` |
| AC-38 | §5.5 | `test_export_roundtrip_values_and_timestamps`, `test_export_promtool_create_blocks` (integration) |
| AC-39 | §3.7, §5.4 | `test_write_order_reading_prom_history_rerender_lastraw`, `test_history_unwritable_reading_and_decision_identical`, `test_history_write_ok_0_on_failure` |
| AC-40 | §1.6 | `test_last_raw_success_then_failure` (TD-O-16) |
| AC-41 | §6.3 rules 6, 7 | `test_rule_exprs_exact` (separate rules; `> bool 0` is 0 at cost 0) |
| AC-42 | §6.3 rule 11, §6.6, §7.2 item 2 | `test_monitoring_sync.py`, S5 record |
| AC-43 | §6.4, §7.2 item 3 | S5 record |
| AC-44 | §7.2 item 4 | S5 record (definition of done; procedure confirmed, H-4) |
| AC-45 | §1.8, §6.3, §6.5 | S1-ST10, `test_no_literal_threshold_in_rules`, `test_named_values_header_covers_every_duration`, `test_no_threshold_steps_with_values` |
| AC-46 | §4.5 | `test_consumer_no_poller_pauses_reading_missing`, `test_consumer_no_poller_failopen_runs`, `test_failopen_unchecked_audit_event` (H-1), S2-ST9 |
| AC-47 | §6.3, §6.4, §9.4a (H-2) | `test_required_alert_rules_*`, `test_contact_point_has_email_and_sms_integrations` (PR-required guard), `test_every_rule_receiver_hos_no_policy_tree`, `test_no_real_endpoints_or_secrets`, `test_contrib_never_shipped` |
| AC-48 | §3.14 item 2 | S1 record |
| AC-49 | §3.10, §1.9.2 | `test_check_capture_fixture_*`, `test_extra_fields_ignored`; "removed" half runs once the full envelope is committed (S1 exit + later PR) |
| AC-50 | §6.2, §6.6, §7.2 item 1 | `test_provider_yaml`, `test_monitoring_sync.py`, S5 record |
| AC-51 | §3.13 | S2-ST10 |
| AC-52 | §5.2 #17, #21 | `test_pause_condition_from_poll_view`, `test_poll_view_equals_cycle_rule`, `test_never_succeeded_last_success_zero` |
| AC-(H-7) *(pm-agent to number; ADR A4-9 item 9)* | §3.10 item 10, §3.15, §8 | `test_check_item10_*`; S1 trip-test record on #1944 (gates S2 build) |
| AS-1 / AS-2 / AS-3 | superseded by D1 / confirmed by D2 / superseded by D3, D7 | `test_model_90_*` / `test_running_cycle_not_killed` / — |
| D-1 / D-2 / D-3 / D-4 / D-5 / D-6 | §1.9.1 / no fallback / §5.1 / §3.10, AC-49 / §6.4 placeholder / §6.7 env file | fixtures / AC-21 test / §5.1 record / S1 exit / AC-43 deferred / S5 |

---

## 11. Questions for the architect (TD-O) — Revision 2 (ADR A2)

### 11.1 Revision 1 items, status after Amendment 2

- **TD-O-1:** overridden in round 1 (Python time bound); stands (A1-2).
- ~~**TD-O-2** (raw `gh` in the gate).~~ **Removed — moot (D7, A2-5, A2-19).**
- **TD-O-3:** resolved, D12 (content decides).
- **TD-O-4:** resolved, D13 (AC-25 rewritten).
- **TD-O-5:** stands (A1-4).
- **TD-O-6:** amended by A2-12 (`limit` label; three thresholds; `settings_valid`).
- **TD-O-7:** stands, extended: promtool tests stay `integration`-marked (§9.3, §9.4).
- ~~**TD-O-8, TD-O-9**~~ **void with AD-8 (A2-22).**
- **TD-O-10:** stands (one `key=value` per argv element).
- **TD-O-11:** stands.

### 11.2 New in Revision 2. Each has a binding interim, so none blocks coding.

- **TD-O-12 (A2-13, unimplementable as worded).** `HosClaudeUsageMetricsAbsent` is specified as `absent(hos_claude_usage_poll_timestamp_seconds{instance=~"$instance"})`. Grafana alert rules have no dashboard variables, and Grafana's provisioning env interpolation would expand `$instance` to an empty string (TD-VF-17), so the selector cannot work. *Interim:* unscoped `absent(hos_claude_usage_poll_timestamp_seconds)`. It fires when no host exports the metric, which is exact for the one-poller worked example. A multi-poller deployment adds one rule per host (documented in §6.8 item 10).
- **TD-O-13 (A2-13, partly unimplementable).** YAML anchors can name whole scalars (`for:`, `interval:`, `relativeTimeRange.from`), but a PromQL expression is one string and cannot splice an alias. *Interim:* anchors for every whole-scalar duration (fallback: inline values), **plus** a mandatory named-values header table that lists every duration and every PromQL range/horizon literal (`6h`, `86400`). The static test checks every literal against the table. Configurable thresholds are never literals; they are always gauges.
- **TD-O-14 (A2-6 reason format vs the bash ERE).** A2-6 keeps the raw model name in the reason. The gate matches the verdict under `LC_ALL=C` with a printable-ASCII class, and a non-ASCII byte would turn a valid pause into a spurious `check_error`. *Interim:* the reading file keeps the raw name; the verdict, log line and audit event fold non-ASCII characters to `?`. All captured model names so far are ASCII.
- **TD-O-15 (clarifying).** Reading-unusable tokens are renamed `status_*` → `reading_*` to match the renamed file and A2-15's `reading_missing`; `schema_unknown` keeps AD-2's name.
- **TD-O-16 (A2-11 vs AC-40 wording).** A2-11 gives `last-raw` a header line; AC-40 says it "holds exactly the second poll's raw output". *Interim:* keep the header; AC-40 is asserted on the bytes after line 1. pm-agent may reword AC-40.
- **TD-O-17 (A2-11 edge).** "Today's file is never deleted" can leave the total above `history_max_mb` when one day's file alone exceeds it (e.g. `history_max_mb=1` at ~2 KB × 288 polls). *Interim:* stop pruning; not a failure (`history_write_ok` stays 1); log a WARN.
- **TD-O-18 (informational; A2-5 + TD-VF-18).** Paused-cycle `cycle-usage-paused` records are written into `REPO_ROOT/audit/log/` and pushed only by the next running cycle's `_sync_audit_logs` (`:2234`). A multi-day weekly pause on this host (2 roles × 2 projects) leaves on the order of a thousand unsynced records per day in the clones, compounding known gap #1803. *Interim:* as ruled. Raised so the architect can decide whether a follow-up is wanted.
- **TD-O-19 (A2-15, file naming).** The release-note target is `docs/releases/v0.7.0.md` (created with only an "Upgrade notes" section if absent; protected, but S2 is HUMAN_REQUIRED anyway) plus a new §H in `docs/UPGRADE-PR-REVIEW-CHECKLIST.md`. Confirm v0.7.0 is the release that first ships S2.
- **TD-O-20 (additive, stricter).** `--check` item 7 FAILs on a non-zero **or absent** cost/token value. That is the setup-time mirror of `ReadCostNonzero`/`ReadCostUnknown` and supplies AC-25's evidence. *Interim:* binds.
- **TD-O-21 (additive).** The `cycle-usage-paused` event also carries `project` and `cycle_id`, since the pause is global and each event is per cycle. *Interim:* binds.
- **TD-O-22 (AC-35 interpretation).** On running cycles (fail-open, resume) `hos-cron`'s ordinary flow makes GitHub calls by design. AC-35 is therefore asserted as "zero calls of any kind on paused cycles" plus "the gate adds zero calls on running cycles" (call list identical to a plain run). *Interim:* binds.

**No A2 decision is contradictory.** Two are unimplementable as literally worded (TD-O-12, TD-O-13), and each has a faithful interim. S2 is additionally gated on H-1 by A2-20 (§4.4 G4). *(Superseded: H-1 is ruled; S2 is now gated on the H-7 trip test, §3.15.)*

### 11.3 Architect round 2 — rulings (2026-10-03, binding)

**Verdict: APPROVED WITH CHANGES.** The changes below are applied inline in this document, tagged "Architect round 2". No further architect round is needed unless the human's H-1 to H-4 answers change a section. ADR Amendment 3 records the ADR-level refinements.

| Item | Ruling | Reason |
|---|---|---|
| TD-O-12 | **ACCEPT** the unscoped `absent(hos_claude_usage_poll_timestamp_seconds)`. ADR A3-1. | Alert rules have no dashboard variables, and `$instance` would be env-expanded to an empty string. With one poller, unscoped is exact. A per-host literal would put `faberix` into the rules file, which §6.7 item 8 forbids. Limitation: with several pollers, one host going silent does not fire this rule (§6.8 item 10). It is a worked-example limit, not a contract limit. |
| TD-O-13 | **ACCEPT** (anchors for whole scalars, plus a header table and static test covering every duration and PromQL range/horizon literal). | A2-13 already names the header table as the fallback. `6h`/`86400` are query windows, not thresholds. D19 applies to thresholds, and every threshold comparison is against a gauge. |
| TD-O-14 | **ACCEPT**, ADR A3-2. Folding happens once, in `usage_pause.py check`, *before* the 200-char cap; the bash side never re-encodes. | A non-ASCII byte must not turn a correct pause into `check_error`. The reason's purpose is stable greps, and the folding keeps them stable. The raw name survives in the reading file. The gauge label is sanitized anyway (AD-10). |
| TD-O-15 | **ACCEPT**. | Naming only. |
| TD-O-16 | **ACCEPT**. pm-agent may reword AC-40 to "the bytes after the header line"; this does not block. | The header is A2-11's. The AC's intent ("the second poll's raw output, nothing else") is what the test asserts. |
| TD-O-17 | **ACCEPT**, ADR A3-4. | A2-11's "never delete today" and "≤ `history_max_mb`" cannot both hold when one day exceeds the cap. Keeping today's file (the recovery data closest to now) is the correct winner. Only a pathological setting (`history_max_mb=1`) reaches this, so a WARN, not a failure, is enough. |
| TD-O-18 | **ACCEPT THE GAP. A2-5 stands unchanged** (one `cycle-usage-paused` per paused cycle, no sync on the paused path). ADR A3-5. | See below. |
| TD-O-19 | **v0.7.0**, with the retarget rule in §4.5. | `projects.conf` has `hos_target_release=v0.7.0`. No `v0.7.0` tag exists, and `docs/releases/v0.7.0.md` does not exist yet. #1944 has **no milestone**. **Recommendation:** the orchestrating session puts #1944 on the v0.7.0 milestone. |
| TD-O-20 | **ACCEPT** (stricter). | It is the setup-time mirror of `ReadCostNonzero`/`ReadCostUnknown`. A CLI that drops the fields must fail S1 exit, not pass it silently. |
| TD-O-21 | **ACCEPT**, ADR A3-3. | With a global pause, per-cycle records are only useful if they can be attributed to a project and a cycle. The change is additive, and no decision reads it. |
| TD-O-22 | **ACCEPT**. pm-agent may reword AC-35 to match; this does not block. | The literal reading ("no GitHub calls on running cycles") would forbid `hos-cron`'s normal work. A2-4's intent is that a paused cycle makes zero network calls and the gate adds none. |

**TD-O-18 in full.** Three options were weighed:
1. **Sync on the paused path.** Rejected. `_sync_audit_logs` (`:374-427`) does `git fetch` and `git push`. That breaks A2-4/AC-35 (a paused cycle makes zero network calls). It also does network work exactly when the host is supposed to be idle, and makes a paused cycle's cost depend on GitHub's reachability.
2. **Emit an event only when the pause reason changes**, comparing against the newest `cycle-usage-paused` record on disk. Rejected. In practice this is transition detection with the audit log as its memory, which D6 and A2-5 removed on purpose ("minimise points of failure"). The gate block would have to read files other than through `check` (breaking S2-ST1), and the result would be coupled to `cycle_log`'s on-disk format. The audit content would then depend on earlier audit content, against the spirit of ADR-1604 AD-4. The new failure modes include a corrupt or partial newest record, a month directory thousands of files deep (#1803), and separate clones per role. Each one either suppresses evidence or needs its own fail-safe. Finally, "reason changes" has odd semantics: a percentage creeping from 91% to 92% counts as a change.
3. **Accept the gap.** Chosen. The records are **delayed, not lost.** `_sync_audit_logs` is a bulk, idempotent catch-up. It pushes every `audit/log/**/*.json` not already on the `audit-log` branch, and it already handles a backlog thousands of files deep (`:411-413`). The first running cycle after the pause pushes them all. Volume is bounded by cron cadence: at the observed ~10-minute cadence, about 144 records per role/project per day. That is fewer per cycle than a running cycle writes. A2-5 already accepted this volume. The up-to-date per-cycle record during a pause is the cron log line, which is unaffected. The gap is not new: it is the existing #1803 sync and commit gap, applied to idle cycles. Fixing it there (for example, a sync that does not need a running cycle) covers both cases. Fixing it here would add state to a stateless gate.
- **TD change:** runbook §2a.10 gains one sentence (applied). No code change.
- **For the orchestrating session (not filed by me):** annotate #1803 that paused cycles add records which sync only on resume. After a multi-day pause, the first sync carries roughly 144 × (role/project pairs) × days records in one commit.

**Additional round-2 findings (applied inline):**
- **R2-A (§1.8, S1-ST10 (c)).** The Revision 2 wording banned every literal `100` outside the settings block. That made it impossible to name §1.3's `*_resets ≤ 100` cap at all. (c) is narrowed to function bodies plus non-`DEFAULT_` module constants; (b) still guarantees D19 for every comparison.
- **R2-B (§1.6, §3.7 P11, §9.1).** A2-11 says `last-raw` is "overwritten each poll". Revision 2 skipped the overwrite when P6 did not run, which left a stale capture from an earlier poll. Fixed with a header-only `read=none` record and a new test.
- **R2-C (§4.4 G1, S2-ST5).** The gate's `timeout --kill-after=5 60` were the only unnamed numbers on the decision path. They are now named values at the top of the block (D19 hygiene; these are time bounds, not thresholds).

**Verification performed this round:**
- **A2-1 to A2-22 faithfulness:** checked section by section. Every A2 item is implemented. The only departures are the ones ruled above (TD-O-12, -14, -17, -21, each recorded in ADR A3) and R2-B, which brings the TD *into* line with A2-11.
- **S1/S2 have no TBDs.** The only open items are human gates: H-1 governs S2's G4 second branch, and both branches are fully specified. S1's exit records are human actions (H-6).
- **Traceability:** every FR and AC ID in the requirements (119 IDs) has a §10 row, checked mechanically. Superseded IDs are marked.
- **D19 (no literal thresholds):** no PromQL in §6.3 or §6.5 compares against a configurable value except through a gauge (`threshold_percent{limit}`, `staleness_seconds`, `sync_stale_after_seconds`). The only literals in comparisons are the `0`/`1` semantic constants. Range/horizon literals (`6h`, `86400`; on the dashboard, `1h`/`3600`) are query windows and are listed in the header table for the rules file. Dashboard threshold steps carry no value. No `90` appears.

---

### 11.4 Human rulings H-1..H-4, H-7 — applied (2026-10-03, ADR Amendment 4)

| Ruling | Effect on this TD | Sections |
|---|---|---|
| H-1 confirmed | `cycle-usage-unchecked` on every `class=failopen` cycle (no block, no issue). The exact sentence "fail_mode=open without a running poller means no quota protection" appears in the release note, checklist §H, and CRON-SETUP §2a.0/§2a.9. | §1.7, §3.13, §4.4 G4, §4.5, §6.8, §9.2, §10 |
| H-2 rejected | No protected-surface entry. The required-alert guard test is in the PR-required suite. S4 is MEDIUM with normal merge. | §0 TD-VF-19, §2, §6.3, §6.7, §6.10, §8, §9.4, §9.4a, §10, Human Review |
| H-3 confirmed | Path unit (`PathChanged=` on the two clone alerting files), oneshot service (start limit off), and reload script (settle, stage as `hos-sync`, idempotence, copy, restart, health check, rollback, gauges). Rule 13. Alerting files are copied, not symlinked. Sync sentinel removed. Restart acceptability analysis. V-R1–V-R3. | §6.1, §6.3, §6.6, §6.6a, §6.7, §6.8, §6.9, §7.2, §9.4, §9.4b |
| H-4 confirmed | AC-44 procedure final; about 10–15 min of paused autonomous work; running cycles finish first. | §7.2 item 4 |
| H-7 new | S1 trip test (§3.15) gates S2 build. New `--check` item 10 (INFO, never FAIL). | §3.10, §3.15, §8, §9.1, §10 |

**For `technical-design` (ADR A4-10):** do one consistency pass over the sections tagged "Human rulings H-1..H-4, H-7", before the S1 PR (item 10) and before S4 coding (§6.6a, §9.4a/b). This is not a new critique round. The round count stays at 2 of 5.

### 11.5 S1 coder clarifications (2026-10-03, technical-design rulings on the S1 implementation)

Classification: **clarifying**, except C-6 (**additive**: one more case in the `top_subagents_more_<w>` value) and C-9 (the §3.1 comment rule restated). No architecture changes. Startup-gap check: C-2, C-6 and C-9 were contract gaps that the initial TD should have closed. No code had been approved against the old wording, so no sign-off is orphaned. The architect's round-2 TD approval stands, and the S1 reviewers review against this section.

- **C-1 (§3.7, §3.10, §3.11) `--check` and `--print-setup` live in Python.** `bin/hos-usage-poll` checks its arguments and then `exec`s `usage_pause.py check-setup --self-path <_SELF> [--capture-fixture P]` or `print-setup --self-path <_SELF>`. This replaces the bash orchestration (`mktemp -d`, `stat-mode`, `classify` helpers). The temp read directory is `os.mkdir(<${TMPDIR:-/tmp}>/hos-usage-check-<pid>-<12 hex>, 0700)`, removed in `finally`. It counts as the §3.10 "`mktemp -d`" because S1-ST4 bars `tempfile`. Output grammar, item numbering, exit codes and the read-only rule are unchanged. **Two further requirements:** (a) `--print-setup` exits `1` whenever it prints **any** `MISSING:` line, including "claude not found", because block 3 is then not printed. (b) In `--check`, an `OSError` while writing the `--capture-fixture` target prints `FAIL  7  capture failed: <error>` and the run continues to `RESULT:`. It must not raise a traceback.
- **C-2 (§9.1 S1-ST8).** "No `timeout`" means no `timeout`/`gtimeout` **command invocation**. The reason string `timeout`, `read_timeout_seconds` and `--timeout` stay mandatory. The test must also reject, in the module AST, any list or tuple literal whose first element is the string constant `"timeout"` or `"gtimeout"`. Without that check, an argv passed to `subprocess.run` would get past the bash-form regexes.
- **C-3 (§1.2, TD-O-14).** The reading's `poll_pause_reason` and `weekly_model_<slug>_name` keep the raw name. `ascii_fold()` is public, and S2's `check` folds once, before the 200-character cap. The poll log line folds as well. `--check` item 10 prints the raw `poll_pause_reason` text, which is human-facing and not parsed.
- **C-4 (§1.8).** Only blank lines and lines whose first non-whitespace character is `#` are ignored. Matching uses the line with its trailing whitespace stripped. A line with leading whitespace before `key=` is `invalid:line_<n>`. `--check` item 4 names the line, and the decision is the normal `settings_invalid` pause.
- **C-5 (§1.3).** The breakdown keys are grouped **per window**, windows in source order. Within each window the order is `requests_`, `sessions_`, `subagent_heavy_pct_`, `long_context_pct_`, `long_session_pct_`, `top_subagents_`, `top_subagents_more_`.
- **C-6 (§1.3, §3.3).** The 200-character cap on `top_subagents_<w>` drops whole trailing items, never part of an item. **Change required:** `top_subagents_more_<w>` = K (the source's "+K more", else 0) **plus the number of items dropped**. Otherwise a truncated list would read as "0 = none omitted". If not even the first item fits, both keys are absent, as before.
- **C-7 (§3.2 step 6).** `cost_usd` is rendered with `repr(float)`, exponent form included (`1e-30`, `1e+16`), so a nonzero cost is never shown as `0`. Any later consumer (S2 `check` if it ever reads cost, S3 `.prom`/history) must accept `[0-9.e+-]` forms. The Prometheus text format already does.
- **C-8 (§9.1).** `test_poll_spawn_failed` is asserted at the library/CLI level (`read_usage` with an absent binary, and `read-usage` printing `read=spawn_failed rc=-`). The poller's pinned `PATH` always reaches `/usr/bin/ssh`, and execvp skips non-executable stubs. The poller's `rc=-` branch is exercised through the poller by the timeout test.
- **C-9 (§3.1, T4.1b).** The `REMOTE_CMD_TEMPLATE` line is 149 characters and exceeds flake8 E501. The line is exactly `REMOTE_CMD_TEMPLATE = "{claude_bin} -p /usage --output-format json"  # noqa: E501  # ADR-1944 A2-9: forced-command template; executed by sshd, never by HOS (T4.1b)`. The `noqa` goes **before** the mandated comment. The line therefore still **ends with** the mandated comment byte for byte. `split("  # ")[0]` still gives the template, so T4.1b passes unchanged. Verified under flake8 at 100 and 120 and under black at 100. No per-file ignore (the gate passes CLI flags and does not read `pyproject.toml`), and no rewording of the comment.
- **C-10 (§3.12, TD-VF-13, §9.1; S1 code-review round 1 (S5)).** **Clarifying, stricter.** The file-level T4.1 exemption for `bin/lib/usage_pause.py` was broader than needed: its only `claude -p` text was the module docstring, so a second raw call anywhere in the file would have passed T4.1. The docstring is reworded to contain no `claude -p`, and `bin/lib/usage_pause.py` is **removed** from `_T4_1_EXPECTED_EXEMPTIONS` (the set is unchanged from pre-#1944). T4.1b now asserts exactly one code line of the file (the C-9 `REMOTE_CMD_TEMPLATE` line) matches the usage-read pattern, and no code line of `bin/lib/usage_pause.py` or `bin/hos-usage-poll` matches `claude\s+(-p|--print)`. Supersedes §3.12's and TD-VF-13's docstring-exemption wording. Startup-gap check: the initial TD should have specified this; the change only tightens a test and was made within the S1 review loop, so no prior sign-off is orphaned beyond the in-flight S1 review, which already covers it.

## 12. Escalations — Revision 2

- **ESC-T1** (cross-clone `bin/` writable): **accepted risk** (D14, A2-16). No issue.
- **ESC-T2, ESC-T4** (single-page dedup sites; collapsed `_audit` at `:2054`): **filed as #1946** (A2-19). Add to #1946: the `cycle-start` `_audit` at `:1823` is collapsed the same way (TD-VF-14). Not filed by me (design-only); for the orchestrating session.
- ~~**ESC-T3**~~ closed (round 1; A2-19).
- **New, none.** The human-owned items are in §13.

---

## 13. Human confirmation required — Human rulings H-1..H-4, H-7 (ADR A4-8; supersedes the A2-20 carry-forward)

**Resolved by D1–D19:** as listed in ADR A2-20 (AS-1/2/3, Q11, Q12, Q5, Q15, FR-42/44, Grafana provisioning, ESC-1, FR-11, AC-25, cross-clone `denyWrite`, #1946).

**Resolved by human ruling, interactive session 2026-10-03:**
- **H-1 confirmed:** per-cycle `cycle-usage-unchecked` plus the exact release-note sentence; no block, no issue (§4.4 G4, §4.5).
- **H-2 rejected:** no protected-surface entry. The replacement control is the required-alert guard test (§6.10, §9.4a).
- **H-3 confirmed:** root systemd path unit restarting grafana-server (§6.6a).
- **H-4 confirmed:** the AC-44 procedure (§7.2 item 4).
- **H-7 (new):** the S1 trip test gates S2 (§3.15, §8).

**P-rulings (design-level, for awareness):** P1–P6, P8, P9, unchanged (ADR A2-20).

**Remaining. None blocks design or coding:**
- **H-5 (informational, safe direction).** Under D4, an invalid `history_days`/`history_max_mb` pauses all autonomous work. A ruling is needed only if the human wants those keys exempted, which would loosen D4.
- **H-6 (human actions, not confirmations):**
  - faberix S1: keypair, `remote-cmd` `authorized_keys` line, `known_hosts`, poller crontab line, `--check --capture-fixture`;
  - faberix after S1 exit: **the H-7 trip test (§3.15)**;
  - faberix S3: `/var/lib/hos-usage` + symlink;
  - monitrix S5: `hos-sync` user, clone, sync script, dashboard provider symlink, Grafana env file, sync and reload textfile symlinks, **the reload script and both units (§6.7 item 3)**, then the V-R1–V-R3 checks;
  - the AC-44 run;
  - removing the leftover `/tmp/diagnose_claude_usage_tty.sh` crontab entry. TD-VF-16 found it commented out at crontab line 76.
- **Dependencies, not confirmations:** D-5 (SMS provider) defers only the SMS half of AC-43/AC-44. Q13, Q14 and Q18 are unchanged and not blocking.
- **Orchestrator actions (not human rulings):** put #1944 on the v0.7.0 milestone (TD-O-19); hand the ADR A4-9 requirement rewording to pm-agent.

---

## 14. Startup-gap analysis and affected sign-offs — Revision 2 (ADR A2)

**"Should this have been settled in the initial technical design, before any code was written against it?"** Amendment 2 is a set of human rulings (D1–D19) that land before any code exists, so the question is answered for each revision: yes, they belong in the design, and they are being settled now, still before any code.
- **Affected artifact:** only this TD. Revision 1 carried an Architect round 1 "approved with changes" status. **That approval is orphaned for every section marked Revision 2** and must be re-given: architect review restarts at round 1 for the amended sections (A2-22). Sections tagged "unchanged" keep their round-1 standing.
- **Code / test / review sign-offs:** none exist for #1944. None orphaned. No `startup-artifact-gap` issue is warranted, because the initial review cycle is still open.
- **Shipped code:** the #1450 breaker and its sign-offs stand untouched (FR-40, S2-ST3). TD-VF-14's note on `:1823` is a cosmetic defect in shipped code, routed to #1946; its sign-off stands (no decision reads that record).

---

## Human Review Required

**RISK: HIGH.** The contract gates every autonomous cycle on every host running `hos-cron`, and S2 changes a shipped launcher. If it is wrong it either stops all autonomous work (fail-closed) or lets usage run unwatched (fail-open). Closures, each with named tests:
- Every decision-path failure, including the helper crashing, resolves to a *named* pause (`check_error` ignores `fail_mode`).
- The gate runs before any network call or Claude process, writes nothing, and holds no state, so a paused cycle cannot leak or corrupt anything.
- A failed read can never record 0% anywhere (§1.3, §5.2). Cost 0 never establishes success.
- With issues gone, the alert rules are the only human-facing signal. They compare only against exported gauges and carry no literal threshold. Per H-2 they are not protected surface: a PR-required guard test pins every required alert by UID, plus the contact point's email and SMS integrations, so removing one is a visible test edit (§6.10, §9.4a). A rejected alerting change rolls back and fires rule 13 (H-3).
- Fail-open is never silent in the audit trail: every unchecked cycle writes `cycle-usage-unchecked` (H-1).
- A forced command that goes missing yields `envelope_invalid`, never a silent success (client sends no command).

**CONFIDENCE: HIGH** on §0–§4 (anchors re-read at `0603100b9`; regexes executed against both real captures; envelope fields taken only from capture 2). **MEDIUM-HIGH** on §5 (symlink probe pending; fallback verified available). **MEDIUM** on §6–§7 until the §6.9 Grafana gaps are checked on monitrix; two A2-13 details were unimplementable as worded and carry interims (TD-O-12, TD-O-13).

**BLAST RADIUS:** `bin/hos-cron` cycle start (both roles, every project, every consumer on upgrade); new `bin/hos-usage-poll` and `bin/lib/usage_pause.py`; `framework_consumer_files.txt`; `hos_install.sh` summary text; T4.1b tests (T4.1 ledger untouched: §11.5 C-10); the shared `CronEnv` fixture; `~/.ssh/authorized_keys`; the user crontab; `~/.hos/usage-pause/` (incl. `history/`, `last-raw`); `~/.config/hos/usage-pause.conf`; `/var/lib/hos-usage` + one symlink; monitrix `/opt/hos-monitoring`, a `hos-sync` user, `/usr/local/bin/hos-monitoring-sync`, Grafana provisioning and env file, two systemd units, `/usr/local/sbin/hos-grafana-alerting-reload`, `/var/lib/hos-grafana-reload`; `docs/releases/v0.7.0.md`. (`protected_surfaces.txt`, AGENT-IDENTITY §9.0 and CODEOWNERS are no longer touched: H-2.)

**Change classification: STRUCTURAL.** The structure was set by the human's rulings (D1–D19), which pre-authorize it. The design-level additions here are `additive` or `clarifying` (TD-O-14 to TD-O-22) or unimplementable-as-worded interims (TD-O-12, TD-O-13), all listed for the architect. **Human rulings H-1..H-4, H-7:** no human ruling is outstanding. S2 waits on the S1 trip-test record (H-7); S4 and S5 wait only on their predecessor slices and the S5 human steps.
