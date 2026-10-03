# ADR-1944: Proactive Claude usage-threshold pause. A standalone loopback poller writes one machine reading, `hos-cron` gates every worker/overseer cycle on it without touching `hos-suspend`, and Prometheus/Grafana get the raw values by a side path that can never affect the decision

**Status:** ACCEPTED FOR DESIGN. Binds `technical-design`. The proactive percentage check is the **core** of this ADR (AD-1 to AD-9). Nothing below defers it, softens it, or puts it behind a flag. Items that need the human are listed in §5 ("Human confirmation required") and §4 (escalations). **None of them blocks the proactive check from being designed or built.** Each one changes a default, a label, or an operator procedure. None changes whether the check exists.
**Status update (Amendment 4, 2026-10-03):** human rulings H-1 to H-4 and H-7 are applied. No human ruling is outstanding (A4-8). **Build mode:** #1944 is built in the human's interactive worker session, not by autonomous pickup. `needs-ai` is deliberately left off. The slice order and gates are in A4-7.
**Date:** 2026-10-02
**Author:** architect
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1944-proactive-usage-pause.md` (pm-agent, including Amendment 1). Its rulings are not reopened here. Also: #1944 body; #1446 comments 2026-08-17T05:17:05Z / 05:25:22Z / 07:47:00Z; PR #1450 thread; `bin/hos-cron`, `bin/hos-suspend`, `docs/CRON-SETUP.md`, `docs/SANDBOX-POLICY.md`, `contract/sandbox-policy.template.json`, `scripts/framework/machine-accounts.env`, `scripts/framework/protected_surfaces.txt`, `scripts/framework/framework_consumer_files.txt`, `bootstrap/hos_install.sh`, `tests/framework/test_agent_invocation_migration.py` (T4.1), `docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md` AD-16, `bootstrap/create_issue.sh`, `bootstrap/escalate_to_human.sh`, `~/.local/bin/sync_human_clone.sh` (readable; `write_status()` at `:120-133`). Also two inputs the coordinator relayed on 2026-10-02: **a verbatim `/usage` capture taken over the loopback (D-1, now resolved)** and the **verified faberix/monitrix host facts** (§0.3).
**Consumers:** `technical-design` (next), then `unit-test`, `system-test`, `security-reviewer` (AD-6), `infra-reviewer` (AD-10/AD-11).
**Explicitly does NOT re-litigate:** the standalone 5-minute poller (FR-50), SSH loopback with personal-login credential (FR-3), `>=` (FR-19), 90/90 defaults (FR-18), fail-closed default (FR-21), overwrite-in-place status file (FR-31), the #1450 reactive breaker being obsolete and untouched (FR-40), and raw-values-only export (FR-43).

---

## 0. Verification findings

Line numbers refer to the working tree on `interactive-1944-proactive-usage-pause-design` (HEAD `b750e258e`).

### 0.1 Confirming pm-agent

- **VF-3 CONFIRMED.** The `hos-suspend` marker is `{suspended_at, reason?, until?}` at `~/.hos/suspend/<project>`. It has no owner field and no role field. `bin/hos-cron:258-286` checks it before the lock and `exit 0`s.
- **VF-4 CONFIRMED, and sharpened.** `bin/hos-cron` never reads `machine-accounts.env`. It reads exactly two things under literal `$HOME/.config/hos/`: `projects.conf` (`:172`) and `claude-auth.env` (`:877`). **Trap for the TD:** `HOS_CONFIG_DIR` (`:181`) is *per-project* (`<project>_config_dir`, e.g. `$HOME/Code/HOS/.config/hos`). It is **not** the machine-level directory. A setting resolved through `HOS_CONFIG_DIR` would be per-project and would violate FR-27.
- **VF-6 CONFIRMED.** T4.1 (`test_agent_invocation_migration.py:98-132`) is a literal regex `claude -p|claude --print` over non-comment lines in `scripts/`, `bootstrap/`, `bin/`.
- **VF-7 CONFIRMED.** `write_status()` writes key=value lines with `>` and installs an `ERR` trap.
- **VF-8 CONFIRMED.** One more defect in it, see AF-3.

### 0.2 My own findings (these change the design)

**AF-1 (HIGH): the status file must not live where `sync_human_clone.sh` puts its file.** That script writes to `/tmp/hos-human-sync-<project>.status`. `contract/sandbox-policy.template.json:167-176` puts `/tmp` in the sandboxed sessions' `allowWrite`. `~/.hos/`, `~/.config/hos/`, `~/.ssh/` and `/var/lib/` are not in it, and `~/.ssh/**` is in `permissions.deny`. If the pause input sat in `/tmp`, a worker or overseer session running with `bypassPermissions` could write `session_pct=0` and unpause itself. **We mirror the pattern but not the location.** Every file on the decision path lives outside every sandboxed role's `allowWrite` (AD-3).

**AF-2 (HIGH): all code on the decision path must sit on protected surface.** `bin/**` is protected (`protected_surfaces.txt`, CODEOWNERS → HUMAN_REQUIRED). It is also OS-level `denyWrite` for sandboxed sessions (`SANDBOX-POLICY.md` §`denyWrite`). `scripts/automation/lib/` is neither. If the parser or decision logic lived there, the worker could weaken its own brake through an ordinary LOW-tier PR that the overseer may auto-merge. The poller, the parser/decision library, and the cycle check therefore all live under `bin/` (AD-2).

**AF-3 (MEDIUM, pre-existing defect, out of scope to fix): the #1435/#1446 dedup query is first-page only.** `bin/hos-cron:2066` (and `:2134`, `:2164`, `:2188`) dedups with `issues?state=open&labels=needs-human&per_page=20` and then filters by title prefix. pm-agent's VF-5 in ADR-1604 counted **56** open `needs-human` issues. Once more than 20 exist, an already-open breaker issue can fall off page 1, the filter returns 0, and **a duplicate is filed.** This "dedup" fails open. FR-37 says to *reuse #1450's pattern*. We reuse its *shape* (stable prefix, fail-closed on error, auto-close), and AD-8 binds a complete query. The existing sites are not changed by #1944. That needs its own issue (ESC-4).

**AF-4 (HIGH): `bin/hos-cron` ships to every consumer, so a fail-closed check would stop every consumer on upgrade.** `framework_consumer_files.txt` ships `bin/hos-cron`, and `hos_install.sh:1904-1916` copies it. A consumer host that upgrades without a poller has no status file. Under the ruled fail-closed default, every worker and overseer cycle on that host then pauses. That is correct by the ruling, and it is loud (AD-8 files an issue naming `poller_not_installed`). It is also a deployment-topology and operational-burden change for every consumer, which puts it under the product-boundary checkpoint (ESC-1). It does **not** change what ships on this host.

> Superseded in part by Amendment 2 A2-15: no issue is filed; the hos-cron log line names the reason (D7, D10).

**AF-5 (LOW): T4.1's regex cannot see a variable-path invocation.** `bin/hos-cron:899` and `:1849` run `"$CLAUDE_BIN" --print`, and T4.1 does not match either. A `/usage` call written as `"$claude_bin" -p /usage` would also pass T4.1 silently. AD-5 does not lean on that blind spot. It records the exemption explicitly.

**AF-6 (from the D-1 sample): the requirements' "subagent-breakdown %" is not a breakdown.** The real section says: *"Behaviors are independent characteristics, not a breakdown."* The three behavior lines (subagent-heavy, >150k context, 8+ hours) overlap. Summing or stacking them would invent a number. Only the "Top subagents" list is attribution, and it is **truncated** (`+2 more`). AD-4, AD-10 and AD-11 carry this through.

### 0.3 Verified host facts (coordinator, 2026-10-02; treated as ground truth)

- **D-1 RESOLVED.** Verbatim loopback capture (2026-10-02) has: line 1 `You are currently using your subscription to power your Claude Code usage`; `Current session: 6% used · resets Oct 3, 2:40am (UTC)`; `Current week (all models): 48% used · resets Oct 3, 12am (UTC)`; `Current week (Fable): 3% used · …` (the `·` is U+00B7). There is a breakdown section with two windows, `Last 24h · 2049 requests · 181 sessions` and `Last 7d · 13242 requests · 1442 sessions`. Each window has three behavior lines and a `Top subagents: name N%, …, +K more` line. The `usage-parse.sh` grep regexes match lines 3-5 exactly.
- **D-3 RESOLVED.** `prometheus-node-exporter` 1.10.2 (`1.10.2-1ubuntu0.26.04.1~esm1`) is **reinstalled** on faberix. monitrix reports `up{instance="faberix"}=1` and `node_scrape_collector_success{collector="textfile"}=1`. The textfile directory is `/var/lib/prometheus/node-exporter/`, `root:root 0755`, holding root-written `apt.prom`, `nvme.prom`, `smartmon.prom`. `/etc/default/prometheus-node-exporter` has `ARGS=""`. **Fragility:** this is an ESM build. The 10-01 release upgrade marked the previous ESM build "Foreign" and it was purged. A future release upgrade can remove it again (handled in AD-10/AD-11).
- **monitrix:** Prometheus job `linux_servers` (`scrape_interval: 15s`) already targets `192.168.1.12:9100` with labels `instance="faberix", role=server, os=ubuntu`. `rule_files` is commented out. Alertmanager is configured at `localhost:9093`. Grafana is 13.2.3, and its provisioning directories hold only `sample.yaml` (dashboards are managed in the UI today).

### 0.4 Verification gaps

> Extended by Amendment 2 A2-21 (new verification gaps).

- Whether node_exporter 1.10.2's textfile collector follows a **symlink** in its directory. AD-10 depends on this, and the TD must verify it on faberix before S3 is coded (AD-10 gives a fallback).
- Which Alertmanager receivers exist on monitrix. AD-11's alerts route wherever the existing config sends them.
- AC-16 (a successful read under **real cron**, not an interactive SSH) has not been recorded for the shipped poller. It is an S1 exit criterion.

---

## 1. Context: what this is after §0

Three processes share one fact: *how much quota is left*.
- A machine-level **poller** learns that fact, using a credential nothing else may touch.
- Each project's **worker and overseer** cycles act on it.
- **monitrix** displays it.

The design draws one line, and the August failure is what drew it. **The pause decision depends only on: the reading file, the settings file, and the clock.** It does not depend on Prometheus, Grafana, the audit trail, GitHub, a transcript, or the `hos-suspend` marker. Each of those can fail, and none of those failures can turn "can't confirm under threshold" into "run". Under the default, every failure mode on the decision path resolves to **pause, with a named reason**.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1: The proactive check is the core deliverable. It ships enabled, with no off switch. (BINDING; FR-1, FR-26, FR-50.)

> Superseded in part by Amendment 2 A2-1: the definition of done is now AC-44 (a real pause alert received by email), not "S1 and S2 merged". The no-off-switch rule stands.

- There is no `enabled=` setting, no env var, and no flag that bypasses the cycle-start check. The ruled operator lever is `fail_mode=open` (FR-21). Even in that mode, every failure is still recorded and surfaced (AD-8).
- The work is done only when **S1 and S2 are both merged** (AD-12). S3/S4 (dashboards) without S2 do not satisfy #1944.
- **If any blocker prevents a real `/usage` read in production** (for example, a CLI change that breaks the loopback read), the build **stops and escalates `needs-human`, naming the blocker** (FR-1). It does not ship a reactive or partial substitute. The #1450 block at `bin/hos-cron:2090-2155` and its live auto-close half at `:2181-2202` are not touched (FR-40, AC-17).

### AD-2: Component placement. Every file on the decision path lives under `bin/` (protected surface, sandbox `denyWrite`). (BINDING; AF-2, FR-49, FR-50.)

> Amended by Amendment 2 A2-9 (the call site becomes a forced-command template) and A2-16 (install path defined in one place; no clone assumption).

| Component | Path | Role |
|---|---|---|
| Poller entry point | `bin/hos-usage-poll` (bash) | Cron-invoked. Pins PATH, takes the lock, runs the bounded SSH read, calls the library, writes the reading file, then (best-effort) the `.prom`. `--check` = preflight (AD-6). `--print-setup` = prints the exact `authorized_keys` line, crontab line, and root commands (never mutates). |
| Parser / settings / decision library | `bin/lib/usage_pause.py` (Python 3, **stdlib only**) | Pure functions: `parse_usage(text)`, `load_settings(path)`, `evaluate(reading, settings, now)`, `read_status(path)`, `render_status(...)`, `render_prom(...)`. Also a small CLI used by both callers. |
| Cycle-start check | inline block in `bin/hos-cron` (AD-7) | Calls `usage_pause.py check …`, then does the bash side effects (audit, issue, log) in the existing hos-cron style. |

- **Python, not `grep -P`.** The `usage-parse.sh` *regexes and success condition* are reused unchanged in meaning (FR-10). They are ported to Python `re` because BSD `grep` (macOS, which `hos-cron` supports, `:118-131`) has no `-P`, and because the decision logic must be unit-testable without a shell harness. This is reuse of the verified asset (the patterns), not re-derivation.
- `bin/hos-usage-poll` and `bin/lib/usage_pause.py` are added to `scripts/framework/framework_consumer_files.txt` (they ship with `hos-cron`, which depends on them). See AF-4 / ESC-1 for consumer impact.
- **Version skew.** The poller runs from one clone and `hos-cron` from each project's clone. The reading file carries `schema=1`. A consumer that sees an unknown schema treats the file as unreadable (fail mode, reason `schema_unknown`).

*Rejected:* `scripts/automation/lib/` (not protected, so the worker could edit its own brake, AF-2). `bootstrap/` (protected, but it is the machine-setup bundle and is not copied wholesale by the installer. The poller is a cron entry point, and those live in `bin/` next to `hos-cron`/`hos-trim-logs`).

### AD-3: Status files. One machine-level **reading file** written by the poller, plus one fixed-path **per-role/project status file** written by each cycle check. Both are overwritten in full and never grow. (BINDING; FR-31-FR-36, FR-27, Q5, AF-1.)

> Superseded by Amendment 2 A2-2 and A2-3: exactly one reading file (`~/.hos/usage-pause/reading`); no per-role/project status file (D6).

**Reconciling Q5.** The 08-17 ruling's "one fixed-path status file per project/role" was written when the read was assumed to run inside each role's cycle. With one poller (FR-50) and a machine-wide quota (FR-27), the *reading* is a single fact. Writing N copies of it would add a failure mode (copies disagree after a partial run) and would couple the poller to `projects.conf`. The design keeps both rulings literally:

1. **Reading file (machine):** `${HOS_STATE_DIR:-$HOME/.hos}/usage-pause/reading.status`. One file, written by every poll, covering successes, failures and crashes.
2. **Per-role/project status file:** `${HOS_STATE_DIR:-$HOME/.hos}/usage-pause/<role>-<project>.status`. One file per role/project, rewritten in full by **every cycle check**. It holds that cycle's view: the reading it consumed (copied values, reading age), the **pause decision and reason** (FR-33), and episode memory (`paused_since`, open issue number). This is the "fixed path per role/project, overwritten every run" of the ruling, and it is what AD-8 uses for transition detection.

The intent ("fixed path, overwritten, never grows, consumers read only the current snapshot") holds for both. This reconciliation is listed for confirmation in §5 because Q5 asked for any ruling refinement to go back to the human.

**Format** (both files): `key=value` lines, as in `write_status()`. Every value is a single line, sanitized (CR/LF/control characters stripped, length-capped). The first line is `schema=1` and the last line is the sentinel `end=1`.

**Write discipline.** This uses `write_status()` semantics (full overwrite at a fixed path; failure states written; an `ERR`/`EXIT` trap writes `outcome=crashed`), made atomic. Content goes to a fixed sibling temp name (`<file>.tmp`, same directory), then `rename(2)`. A crash leaves at most one fixed-name temp file, so nothing grows. The sentinel is defence in depth: a reader that finds no `end=1` treats the file as truncated (FR-36, AC-8).

**Reading file keys (minimum):**
- `schema`, `run_at` (UTC ISO-8601), `run_epoch`
- `outcome` = `success|failure|crashed`, `reason` (closed enum, AD-4), `detail` (≤200 chars, sanitized, failure only)
- `session_pct`, `weekly_all_pct`, `weekly_model_<slug>_pct` (one per model line), `parsed_via=grep`
- `session_resets`, `weekly_all_resets`, `weekly_model_<slug>_resets` (raw text, **status file only**; Q13 ruling: no year in the source, so no metric)
- `subscription_marker=present|absent` (informational, AD-4)
- breakdown fields per window (AD-4)
- `consecutive_failures` (carried from the previous file; an unreadable previous file restarts it at 1 on a failure), `last_success_epoch` (carried)
- `machine_decision=pause|run` + `machine_decision_reason`, evaluated with the settings at poll time. **Informational only:** the consumer recomputes (AD-7).
- `settings_status=defaults|file|invalid:<key>`
- `end=1`

**Absent means absent.** A value the poll did not obtain is **omitted** from the file, never written as `0` or empty-as-zero (FR-12, FR-44, AC-4). A failed read writes no `session_pct`/`weekly_all_pct` at all.

**Location** is outside every sandboxed role's `allowWrite` and `allowRead` (AF-1). The TD adds a static test asserting that neither `~/.hos` nor `~/.config/hos/usage-pause.conf` appears in `contract/sandbox-policy.template.json` `allowWrite`.

### AD-4: Parser and read classification, pinned to the D-1 sample. No model fallback ships in v1. (BINDING; FR-10-FR-17, FR-9, FR-14, FR-15, D-1, D-2, Q18.)

> Amended by Amendment 2 A2-6 (per-model weekly is a pause trigger, D1) and A2-7 (`--output-format json`, parse `result`, revised failure enum, D13).

**Success criterion (FR-11, FR-13).** A read is SUCCESSFUL **only if** it yields an integer `session_pct` from the `Current session: N% used` line **and** an integer `weekly_all_pct` from the `Current week (all models): N% used` line. These are the reference regexes, last match wins, as in `tail -1`. Nothing else decides success: not the exit code, not stderr, not the line-1 subscription marker.

- *The marker is recorded, not required.* `subscription_marker` is captured for diagnosis. It is **not** part of the success criterion, because it is product copy that can change wording and its absence says nothing the % lines do not. The silent-empty shape already fails because it has no % lines. Requiring the marker would add a second way to fail on a harmless copy edit without catching anything new.
- **No clamping.** Percentages are `[0-9]+`, and values above 100 are accepted as-is (credits overflow, per D-1's note). A non-integer format (e.g. `48.5%`) does not match, so the read FAILS. That is loud and safe. The TD must not "helpfully" accept decimals without a captured sample showing them.
- **Decoding.** Input is read as bytes, decoded UTF-8 with `errors="replace"`, and ANSI escapes are stripped. Behavior must not depend on cron's locale (the `·` is U+00B7). Input is capped at 64 KiB.

**Failure reasons** (closed enum, stable for gauges and AC-8 distinctness):
- `ssh_failed`: ssh exit 255, key missing, `from=` rejected, connection refused
- `timeout`: outer bound hit
- `empty_session`: the FR-12 shape (contains `Total cost:` and/or `Usage: 0 input`, and no `% used` line). This shape **never** yields any numeric value anywhere.
- `missing_session` / `missing_weekly`: one of the two lines is absent (AC-5)
- `unparseable`: neither line, and not the empty shape
- `claude_not_executable`
- `no_timeout_binary`: neither `timeout` nor `gtimeout` exists. The read is **refused**, not run unbounded (FR-7).
- `lock_stale_reclaimed` (diagnostic only; the read still runs)
- `crashed`

**Per-model weekly (FR-16, AS-1).** Matches `Current week \(([^)]+)\): N% used`, excluding `all models`. The model name is slugified to `[a-z0-9_]`. These values are **gauges only and never feed the decision** (AS-1, pending confirmation).

**Breakdown (FR-17, AF-6).** Parsed per window `w ∈ {24h, 7d}` from the header `Last (24h|7d) · N requests · M sessions`:
- `requests_<w>`, `sessions_<w>`
- `subagent_heavy_pct_<w>` (`… came from subagent-heavy sessions`)
- `long_context_pct_<w>` (`… was at >150k context`)
- `long_session_pct_<w>` (`… sessions active for 8+ hours`)
- `top_subagents_<w>`: an ordered list of `name=pct` pairs, plus `top_subagents_more_<w>`, the `+K more` integer. When the line parsed and has no `+K more`, this is `0`, which is a *known* zero. It is absent when the line did not parse.

Every breakdown field is parsed **independently**. A miss, a format change, or an exception in any breakdown parse leaves that field absent and **cannot** change `outcome` (FR-17, AC-18). Breakdown fields **never** feed the decision.

**Fixture.** The TD pins every regex against the verbatim 2026-10-02 capture, committed as a test fixture (with the coordinator's path as provenance). The TD also adds the FR-12 empty-session text (PR #1450 07:48:32Z, Test 1) and the AC-1 real-shape values as fixtures. Regexes pinned to a paraphrase are not acceptable.

**Haiku fallback: not shipped in v1.** There is no code path for it, so a grep miss is a FAILED read (FR-14). AC-21 is met by a stub `claude` asserting it was invoked exactly once, with `/usage` and no model or prompt arguments. `parsed_via` is always `grep` in v1, and the field stays in the schema (FR-15) so a future verified fallback is distinguishable. *Rejected:* shipping it disabled. An unverified path in the tree is the "structurally correct, never run" class this repo has been bitten by (ADR-1604 AF-1). It would also be a bare-model call, which ADR-1643 AD-3/AD-16 do not admit (Q18 is moot until D-2, and any future fallback goes through `invoke_agent.sh` with a shipped agent).

### AD-5: The `/usage` call site is an on-the-record exemption from ADR-1643 AD-16. It is not routed through `invoke_agent.sh`. (BINDING; Q8, VF-6, AF-5, FR-9.)

> Superseded by Amendment 2 A2-9: the `claude` invocation lives only in the `authorized_keys` forced command (D5); no `env -u` (D5).

`/usage` invokes no model, has no agent, has no verdict, and must run under a credential `invoke_agent.sh` must never use (the personal login, reached by SSH). `invoke_agent.sh` exists to give *agent* invocations a deterministic envelope (ADR-1643 AD-16: "nothing else invokes `claude --agent` directly"). Routing a non-agent, non-model read through it would either fail its preconditions (no agent file) or force a bare-model escape hatch into the primitive, which AD-16 forbids. This mirrors the `setup_clis.sh` exemption: the call must not depend on the thing it is not.

How the exemption is recorded, so it cannot be silently widened:
1. `bin/hos-usage-poll` is the **only** file in `bin/`, `scripts/`, `bootstrap/` whose code invokes `claude` with `/usage`. Its remote command is exactly `env -u CLAUDE_CODE_OAUTH_TOKEN -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN <claude_bin> -p /usage`. There are no other arguments, no `--model`, and no stdin prompt.
2. **New test T4.1b** (`tests/framework/test_agent_invocation_migration.py`) asserts (1). It checks that this is the sole `/usage` call site and that the poller's claude argv is exactly that, so any added argument (a model, a prompt) fails the build.
3. If the invocation is written so that T4.1's literal regex matches (e.g. a literal `claude -p /usage` in the forced-command template the poller prints), then `bin/hos-usage-poll` is added to `_T4_1_EXPECTED_EXEMPTIONS` as `# EXEMPT (permanent, ADR-1944 AD-5): non-agent /usage read`. Either way, a comment in T4.1's exemption block names this ADR so the next reader sees the site. **The design must not depend on AF-5's regex blind spot to pass.**
4. A one-line comment at the call site cites this AD.

*Rejected:* routing through `invoke_agent.sh` (reasons above). A blanket "non-model calls are exempt" rule (unbounded, and it invites the next site to self-classify).

### AD-6: The SSH read: options, time bound, credential hygiene, and the forced-command recommendation. (BINDING except the `authorized_keys` options, which are a §5 recommendation; FR-3-FR-7, FR-47, FR-48, Q2, Q9, Q12, Q14.)

> Superseded in part by Amendment 2 A2-9 (forced command exactly `from=` + `command=`, no `restrict`, no env unsetting, client sends no remote command) and A2-16 (crontab line is the single install-path definition).

**Invocation** (from `bin/hos-usage-poll`, no shell `eval`, argv array):

```
<timeout_bin> --kill-after=5 <read_timeout_seconds> \
  ssh -n -i ~/.ssh/hos_loopback \
      -o BatchMode=yes -o IdentitiesOnly=yes -o RequestTTY=no \
      -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=yes -o LogLevel=ERROR \
      127.0.0.1 '<remote command from AD-5.1>'
```

- **`-n` and `RequestTTY=no`.** No stdin and no pty, explicitly. FR-5 says pty never mattered, so we request none and get no warning noise. This is not a pty workaround.
- **`StrictHostKeyChecking=yes`.** The runbook seeds `known_hosts` for `127.0.0.1` once. A changed host key is a FAILED read (`ssh_failed`), never an auto-accept.
- **`IdentitiesOnly=yes`.** Cron has no agent socket, and this stops an unrelated agent key from being offered.
- **Time bound (Q9).** `read_timeout_seconds` defaults to **60** and is configurable (AD-9). It must be `< poll_interval_seconds`. A timeout is a FAILED read (`timeout`, AC-7). Outer `--kill-after` guarantees termination. The poller's whole run is therefore bounded by about 75s plus local I/O, well inside the 300s interval.
- **Credential hygiene (FR-4, AC-15).** The poller never sources `claude-auth.env`. A static test greps `bin/hos-usage-poll` and `bin/lib/usage_pause.py` for `claude-auth.env`, `CLAUDE_CODE_OAUTH_TOKEN=` assignments, and `source`/`.` of any `~/.config/hos` file. The poller `unset`s the three variables in its own process. sshd does not forward them anyway (`SendEnv` is not used). The remote `env -u …` covers anything the remote shell's startup files set.
- **PATH / claude path (FR-6).** The poller pins `PATH` exactly as `hos-cron:118-131` does. `claude_bin` is an absolute path (setting, AD-9). When it is unset, `--check`/`--print-setup` resolve it with the pinned PATH and print it. At poll time an unset value resolves the same way, and failure is `claude_not_executable`. The value is baked into the printed `authorized_keys` line, so the forced command never relies on sshd's PATH.
- **Overlap.** The poller takes a non-blocking mkdir lock at `~/.hos/locks/usage-poll.lock`, with a 10-minute age ceiling (the `hos-cron` pattern). If the lock is held, it exits without writing. The other run writes.
- **Not gated by `hos-suspend` (FR-24, AC-12, AC-27).** The poller reads no suspend marker, no halt issue, and no project state. The TD adds a static test for this.

**`authorized_keys` entry, Q12 (recommendation; security-reviewer + human, §5).** The ruled minimum is `from="127.0.0.1,::1"`. **I recommend adding a forced command and `restrict`:**

```
restrict,from="127.0.0.1,::1",command="env -u CLAUDE_CODE_OAUTH_TOKEN -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN <abs path to claude> -p /usage" ssh-ed25519 AAAA… hos-loopback
```

- **Why.** As ruled, the key is a passphrase-less, cron-readable credential that grants **an arbitrary shell as scott** to anything able to reach loopback with it. With the forced command it grants exactly one read-only, zero-cost command. `restrict` (OpenSSH ≥ 7.2) adds no-pty, no port, agent or X11 forwarding, and no `~/.ssh/rc`. This is least privilege with no functional cost, since the poller only ever wants that one command. The forced command ignores the client's command (it goes to `SSH_ORIGINAL_COMMAND`), so the poller's explicit remote command (AD-5.1) works identically with or without the restriction. **The design is correct under both, and the human chooses.**
- **Cost of the recommendation.** If the claude install path moves, the `authorized_keys` line must be regenerated (`--print-setup`). `--check` detects the mismatch, because the read fails with `claude_not_executable` or `unparseable`.

**Runbook (Q14, FR-47).** A new `docs/CRON-SETUP.md` **§2a "Usage-pause poller (SSH loopback)"**, directly after §2 (the #728 auth runbook, VF-5). It covers:
- keypair generation (`ssh-keygen -t ed25519 -N '' -f ~/.ssh/hos_loopback`)
- the `authorized_keys` line, printed by `--print-setup`
- seeding `known_hosts`
- the settings file (AD-9)
- the crontab line (below)
- `bin/hos-usage-poll --check`

`MACHINE-ACCOUNTS-SETUP.md` gets a one-line pointer. `hos_install.sh` does **not** provision any of this (FR-47). In its post-install summary it **prints** the §2a pointer, the same way it already prints crontab suggestions (`hos_install.sh:2526-2533`).

**Crontab line (FR-50, FR-34).** The human adds it (sandboxed sessions are denied `crontab`, `sandbox-policy.template.json`):

```
*/5 * * * *  <HOS install>/bin/hos-usage-poll > ~/.hos/usage-pause/poll.last.log 2>&1
```

- **`<HOS install>` is a placeholder.** crontab does not expand `~` in the command path, so the installed absolute path is substituted at install time (A2-16).

- **`>`, not `>>`.** This is a fixed-path last-run log, overwritten every run (FR-34). The existing `hos-cron` lines' `>>` logs are pre-existing and out of scope.
- **One entry per host,** regardless of how many projects run there.
- `--print-setup` emits this line, with `*/N` derived from `poll_interval_seconds` (must be a whole number of minutes, AD-9).

**Preflight `--check` (FR-48, AC-22).** Read-only, idempotent, and writes **no** state: no reading file, no `.prom`. Runs from a terminal or the runbook. It checks, reporting each line as PASS/FAIL, and exits non-zero on any FAIL:
1. the key exists with mode 0600
2. `authorized_keys` carries a line for its public key with `from="127.0.0.1,::1"` (and reports whether `restrict`/`command=` are present)
3. `known_hosts` has `127.0.0.1`
4. the settings file is valid (or absent, meaning defaults)
5. exactly one crontab line invokes `hos-usage-poll`, at an interval matching `poll_interval_seconds`
6. **one real loopback read classifies as SUCCESSFUL** (FR-48; the read itself, not an assumption)
7. (S3) the `.prom` path is writable and the symlink resolves (AD-10)

A failure in production is still just a FAILED read, so the fail mode applies and it is never silent.

### AD-7: The cycle-start check in `bin/hos-cron`. It is a stateless gate re-evaluated every cycle. It never writes, reads-to-clear, or removes a `hos-suspend` marker. (BINDING; FR-19, FR-21, FR-23-FR-26, FR-28, FR-36, Q16, AS-2.)

> Amended by Amendment 2 A2-3 (hos-cron is the decider), A2-4 (global, stateless; earlier placement), A2-5 (no GitHub calls; per-paused-cycle audit event), A2-6 (three thresholds).

**Pause = this cycle exits 0 before any Claude session starts.** There is no pause marker. Every cycle re-derives the decision from the reading file, the settings, and the clock. Therefore:
- **Auto-resume (FR-23, AC-10)** is structural. The first cycle that sees a fresh successful reading with both windows `<` threshold runs. Nothing needs clearing.
- **FR-25 / AC-11 hold by construction.** The existing `hos-suspend` check (`:258-286`) still runs first, before the lock. A human or timeout-breaker marker still stops the cycle before this gate is reached, and this mechanism contains no code path that writes, edits, or deletes anything under `~/.hos/suspend/`. A static test asserts that the new block and `usage_pause.py` never reference `suspend/` or invoke `hos-suspend`.

*Rejected: reusing the `hos-suspend` marker* (Q16). It is project-keyed and role-blind and has no owner field (VF-3). Auto-clearing it would wipe human suspensions unless an owner field were added. That is a schema change to a shipped human control, made to solve a problem a stateless gate does not have. It would also make `hos-suspend --list` the place a usage pause shows up, rather than the issue queue the ruling chose.

**Placement in the cycle-start sequence.** Immediately **after** the deterministic git-credentials block (`:855-868`) and **before** the Claude subscription-auth block (`:870`):
- **after GitHub auth**, because AD-8's issue filing/closing needs `GH_TOKEN` and `_REPO_SLUG`;
- **before** `claude-auth.env` is sourced, before the optional model auth probe (`:895-904`, a model call), and before every later stage (halt check, milestone resolution, actionable-work gate, git sync, the worker baseline test run, the session). It is therefore before **any** Claude session in the cycle (FR-26), and it also skips the expensive sync/baseline on paused cycles;
- the same block serves **both roles**. There is no role branch before this point.

**Decision rule (evaluated by `usage_pause.py check --role R --project P`; the bash block acts only on its single-line verdict):**
1. **Load settings (AD-9).** If invalid, the verdict is **pause**, reason `settings_invalid:<key>`, **regardless of `fail_mode`** (Q11).
2. **Read the reading file.** The following are **unusable**, each with its own reason (AC-8):
   - missing: `status_missing`. If the conf file is also missing and `~/.ssh/hos_loopback` is absent, the more specific `poller_not_installed` is used (AF-4).
   - no `end=1`: `status_truncated`
   - unknown schema: `schema_unknown`
   - unparseable: `status_unreadable`
   - `run_epoch` older than `staleness_seconds`: `status_stale`
   - `run_epoch` more than 120s in the future: `status_future`
3. If the file is usable and `outcome=success`: **pause** iff `session_pct >= session_threshold` **or** `weekly_all_pct >= weekly_threshold` (FR-19, AC-2, AC-3, AC-28). The reason names the window(s), the value(s), and the threshold(s) (FR-39). Otherwise **run**.
4. If unusable, or `outcome≠success`: under `fail_mode=closed`, **pause** with the reason (`read_failed:<reason>` or the step-2 reason). Under `fail_mode=open`, **run**, recorded (AD-8 degraded path).
5. If the check helper itself crashes, prints nothing, or prints an unparseable verdict: **pause**, reason `check_error`, regardless of `fail_mode`. The fail mode cannot be trusted when the code that reads it has failed.

**The consumer recomputes from raw values and current settings.** It never trusts the reading file's `machine_decision`. A threshold change therefore applies at the next cycle with no new poll (AC-23), and a garbled decision field cannot unpause anything.

**FR-28 / AC-24.** No input to this decision comes from any session transcript, `last-claude-output`, or log. The test drives a transcript containing threshold wording with an under-threshold reading and asserts **run**.

**AS-2 (pending, §5).** The gate runs at cycle start only. A cycle already running finishes, bounded by `HOS_CRON_MAX_SECONDS`. There is no mid-cycle kill (AC-29).

**Per-role/project status file (AD-3.2)** is rewritten by every check, before the bash block acts.

**Paused-cycle output.** One log line per paused cycle on stdout (the existing cron log), e.g. `[PAUSED-USAGE] session 92% >= 90%`. **No** audit event per paused cycle (AD-8).

### AD-8: Visibility. One audit event per transition, and one deduped `needs-human` issue per **project repo** per episode, auto-closed on resume. The query is complete, and both dedup and filing fail closed. (BINDING; FR-34, FR-37-FR-39, FR-22, AS-3, Q15, Q17, AF-3.)

> **Removed** by Amendment 2 A2-5: no issue filing, dedup, auto-close, or transition memory of any kind (D7). Audit is one event per paused cycle.

**Transitions** are detected by comparing the new decision with the previous per-role/project status file (AD-3.2). If the previous file is unreadable, it counts as "run", so a fresh pause still files (dedup protects against repeats).

**Audit (Q17: yes, transitions only).** `_audit cycle-usage-pause "role=… reason=… session_pct=… weekly_pct=… reading_age=…"` on run→pause, and `_audit cycle-usage-resume "role=… paused_since=…"` on pause→run. There are no per-poll events and the poller emits no audit (FR-34, AC-13). **No decision reads an audit event** (the ADR-1604 AD-4 rule, for the same reason as its AF-2 lost-write finding).

**Pause issue (FR-37/38/39).**
- Title prefix, role-agnostic and project-scoped, distinct from both breakers: `[PAUSED] Claude usage threshold — autonomous cron paused on ${PROJECT}`. Worker and overseer of the same project therefore dedup against **one** issue.
- Label: `needs-human`. The TD confirms against `docs/LABELS.md`. `needs-ai` is **not** added, because no agent can act on it while paused, unlike the breakers' issues.
- Body: window(s) `>=` threshold with values, or the failure/stale reason and detail; the reading's `run_at`; the settings in force; and how to resume (nothing to do, it auto-resumes; or set `fail_mode=open` if the check itself is misfiring).
- **Filed** on a paused cycle when the per-role/project status file has no `issue_number` for the current episode. It is attempted on later paused cycles until it succeeds, which gives at most one issue per episode even if a human closes it mid-episode (the issue number is remembered).
- **Dedup must be complete (AF-3).** Either query by title across *all* open `needs-human` issues using a paginating reader that refuses truncated results (`bootstrap/query_issues.sh --list`, or the equivalent `gh api --paginate`), or use the search API scoped to the title prefix. A query error or a truncation means **no filing this cycle** (fail-closed, AC-14).
- **Cross-role race.** A mkdir lock at `~/.hos/locks/usage-pause-issue-${PROJECT}.lock` (non-blocking; on contention, skip this cycle) wraps query and create.
- **A filing failure never prevents the pause** (FR-37, AC-14). The pause is decided and applied before any GitHub call.
- **Auto-close (FR-38, AC-10):** on the pause→run transition, close every open issue with the prefix (same complete query), with a comment giving the resuming reading.

**Q15 recommendation: one issue per project repo.** Each repo's queue should explain why *its* cron went quiet. On this host that means one issue in each of the HOS and CPS repos per episode. A single machine-scoped issue would have to live in one repo, leaving the other repo's silence unexplained. Pending confirmation (§5).

**Degraded path (`fail_mode=open`; FR-22, AS-3).** A separate prefix: `[DEGRADED] Claude usage check failing — fail-open, cron NOT paused on ${PROJECT}`. It is filed with the same dedup and lock discipline when either:
- (a) the reading is `outcome≠success` with `consecutive_failures >= failopen_issue_after` (default **3**, i.e. 15 minutes at a 5-minute poll, matching the staleness window); AC-30: N-1 failures file nothing, and one success resets the count via the poller; or
- (b) **[DERIVED, §5]** the reading file is unusable (missing, stale, truncated, unknown schema) on a fail-open cycle.

(b) closes a hole AS-3 does not name. With fail-open plus a **dead poller**, there are no "failed polls" to count, the check is silently absent, and credits billing runs unwatched. That is exactly the #1362/#1369 class this feature exists to prevent. The issue auto-closes on the first fresh success. A degraded state also emits one `cycle-usage-degraded` audit event on entry.

### AD-9: Settings: `$HOME/.config/hos/usage-pause.conf`, key=value, **parsed, never sourced**. Missing file means the ruled defaults. Any invalid value means pause, loudly. (BINDING; recommendation on Q11 pending, §5; FR-8, FR-18, FR-21, FR-27, FR-29, FR-30, FR-36, AC-23.)

> Superseded in part by Amendment 2 A2-10 (new keys, removed `failopen_issue_after`, no issue on invalid settings).

**Location (Q3).** `$HOME/.config/hos/usage-pause.conf`, the machine-level directory `hos-cron` already reads (`projects.conf`, `claude-auth.env`). It is resolved from **literal `$HOME`**, never `HOS_CONFIG_DIR` (VF-4 trap). One file per host user means every project's worker and overseer, and the poller, read the same values (FR-27).

*Rejected:*
- `scripts/framework/machine-accounts.env`: committed per repo, never read by `hos-cron`, so it is per-project in practice (VF-4).
- `projects.conf` keys: that file's grammar is `<project>_<key>`, which is per-project by design.
- env vars: a crontab line could set them per project and silently diverge projects (FR-27). `HOS_STATE_DIR` and a `HOS_USAGE_PAUSE_CONF` path override exist **for tests only**. They are documented as such and are not mentioned in the runbook.

**Grammar.** `key=value`, `#` comments, no quoting, no expansion. It is read with a line parser, never `source`d (sourcing executes code from a file the poller reads on every run).

| Key | Default | Valid |
|---|---|---|
| `session_threshold` | `90` | integer 1-100 |
| `weekly_threshold` | `90` | integer 1-100 |
| `fail_mode` | `closed` | `closed` \| `open` |
| `poll_interval_seconds` | `300` | integer multiple of 60, 60-3600 |
| `staleness_seconds` | `900` | integer `> poll_interval_seconds + read_timeout_seconds` |
| `read_timeout_seconds` | `60` | integer 5 to `poll_interval_seconds − 30` |
| `failopen_issue_after` | `3` | integer 1-100 |
| `claude_bin` | (unset → resolved) | absolute path |

Thresholds above 100 are invalid, not "effectively off". A typo must never become a silent disable.

**Invalid-settings rule (Q11, recommended):**
- **Missing file:** all defaults. This is not a loosening, because the defaults *are* the ruled values at full strength. Recorded as `settings_status=defaults`.
- **Present but unreadable, or any invalid value, unknown key, or duplicate key:** the cycle check **pauses regardless of `fail_mode`**, with reason `settings_invalid:<key>`, a pause issue naming the key and the rejected value, and a stderr line. **Unknown keys are invalid** because `sesion_threshold=80` would otherwise be ignored and leave the check looser than the operator intended.
- **Partial-default fallback is rejected** (an invalid `session_threshold=8O` falling back to 90 would be *looser* than the 80 the operator meant).
- **The poller keeps polling under invalid settings,** using defaults for its own `read_timeout_seconds`/`claude_bin` and recording `settings_status=invalid:<key>`. The reading stays fresh, so fixing the file resumes work at the next cycle.

### AD-10: Prometheus export on faberix: a best-effort side path through a scott-owned file, symlinked into the root-owned textfile directory. It can never affect the pause. (BINDING; FR-41-FR-45, Q4, D-3.)

> Amended by Amendment 2 A2-11 (write order, history, last-raw) and A2-12 (metrics contract).

**Isolation (binding).** The poller writes the reading file **first**. Only then does it render and write the `.prom`, inside an error-swallowing step whose failure is logged to `poll.last.log` and nothing else. **No code on the decision path reads the `.prom`, node_exporter, or Prometheus.** A test makes the `.prom` path unwritable and asserts that the reading file and the decision are byte-identical to the writable case.

**Write path (least privilege).** The textfile directory is `root:root 0755` and holds root-written files. `rename(2)` into it needs directory write permission, which scott must not get: that would let scott replace `apt.prom`/`smartmon.prom`. **One-time root step** (human, documented in the §2a runbook; sudo is denied to sessions):

```
sudo install -d -o scott -g scott -m 0755 /var/lib/hos-usage
sudo ln -sfn /var/lib/hos-usage/hos_claude_usage.prom /var/lib/prometheus/node-exporter/hos_claude_usage.prom
```

- The poller writes `/var/lib/hos-usage/.hos_claude_usage.prom.tmp`, then `rename`s it to `/var/lib/hos-usage/hos_claude_usage.prom`. The rename is atomic in a directory scott owns. The symlink always resolves to a complete file, so Prometheus never scrapes a half-written file (FR-45). The temp name lacks the `.prom` suffix and sits outside the collector directory, so it is never scraped.
- **Outside `$HOME` on purpose.** Ubuntu home directories are 0750, and node_exporter (user `prometheus`) cannot traverse them.
- What scott gains is exactly one metrics file's content. It is also outside every sandboxed role's `allowWrite`.
- **Precondition the TD must verify on faberix before coding S3:** node_exporter 1.10.2's textfile collector follows a symlinked `*.prom` entry. Check by hand with a symlinked test file and `curl -s localhost:9100/metrics | grep`. **Fallback if it does not:**
  - (i) if 1.10.2 accepts a repeated `--collector.textfile.directory`, add `/var/lib/hos-usage` via `ARGS` in `/etc/default/prometheus-node-exporter` (human, root);
  - otherwise (ii) escalate. **Do not** fall back to in-place writes into a pre-created file in the root directory. A torn read there can turn `92` into `9`, a silently wrong value.
  - Either way, S1/S2 (the pause) are unaffected.
- *Rejected:*
  - making the textfile directory group-writable (exposes the root-written files);
  - in-place writes to a pre-created file (torn reads, above);
  - a root-run copier timer (more privileged machinery than one symlink);
  - a new listening exporter (FR-41: no new service or port).

**Metrics** (all `gauge`, each with `# HELP`/`# TYPE`). Raw current values only: no deltas, rates, cumulative transforms or forecasts (FR-43, AC-19). Absent when not obtained, never 0 (FR-44).

| Metric | Labels | Present when |
|---|---|---|
| `hos_claude_usage_session_percent` | — | successful read |
| `hos_claude_usage_weekly_all_models_percent` | — | successful read |
| `hos_claude_usage_weekly_model_percent` | `model` | per model line present |
| `hos_claude_usage_window_requests` / `_window_sessions` | `window`=`24h`\|`7d` | header parsed |
| `hos_claude_usage_subagent_heavy_percent` | `window` | line parsed |
| `hos_claude_usage_long_context_percent` (>150k) | `window` | line parsed |
| `hos_claude_usage_long_session_percent` (8h+) | `window` | line parsed |
| `hos_claude_usage_top_subagent_percent` | `window`, `subagent` | name in that window's top list |
| `hos_claude_usage_top_subagents_more` | `window` | Top line parsed (`0` = known none) |
| `hos_claude_usage_threshold_percent` | `window`=`session`\|`weekly` | always (configured value) |
| `hos_claude_usage_pause_condition` | — | always: 1 iff AD-7's rule, applied to this reading with current settings, says pause |
| `hos_claude_usage_read_ok` | — | always (1/0) |
| `hos_claude_usage_read_failure` | `reason` (AD-4 enum) | value 1, on failure only |
| `hos_claude_usage_poll_timestamp_seconds` | — | always |
| `hos_claude_usage_last_success_timestamp_seconds` | — | always; **0 = no success on record** |
| `hos_claude_usage_fail_mode_closed` | — | always (1/0) |

Binding notes:
- **`last_success_timestamp_seconds = 0`** is the one deliberate zero. FR-44 forbids 0 for unknown *usage values*, because 0% reads as "all clear". For a timestamp, 0 (1970) reads as *maximally stale*, which is the safe direction. It is also how "always emitted" health gauges (FR-44) can exist on a fresh host. This interpretation is flagged in §5.
- **`pause_condition` is machine-level.** FR-42 asks for "paused state". Per-role/project paused state is **not exported**. Exporting it would need one writable `.prom` per role/project (more root symlinks) or would make `hos-cron` write to a file shared with the poller. The machine condition is the same fact all consumers act on (FR-27). The difference is consumer-side staleness, and when the poller dies the `.prom` freezes and AD-11's staleness alert fires. Per-role/project state stays in AD-3.2's status files. Flagged in §5 as a partial reading of FR-42.
- **Label hygiene.** `subagent` and `model` values are sanitized to `[A-Za-z0-9_.:-]` with a length cap. Cardinality is bounded by the CLI's top list.
- **Truncated top list (AF-6).** A subagent that drops out of a window's top list becomes an **absent** series, not 0. The dashboard says so (AD-11).

### AD-11: monitrix configuration: scrape unchanged, a small alert-rules file, a file-provisioned dashboard. All human-applied. Artifacts live in `contrib/monitoring/` and are never shipped to consumers. (BINDING; FR-41, FR-46, AC-20; human scope addition 2026-10-02.)

> Superseded in part by Amendment 2 A2-13 (Grafana alerting replaces the Prometheus rules file and Alertmanager routing) and A2-14 (monitrix sparse clone + sync job).

**(1) Prometheus scrape config: no change (a decision, not an omission).** Job `linux_servers` already scrapes `192.168.1.12:9100` every 15s with `instance="faberix"`. Textfile-collector metrics come out of the same `/metrics` endpoint, so `hos_claude_usage_*` series arrive with the existing labels automatically. A 15s scrape of a file that changes every 5 minutes adds no information loss. A separate job would duplicate the target and add a second `up` series to reason about.

**(2) Prometheus alert rules: ship `contrib/monitoring/prometheus/hos-claude-usage.rules.yml` (recommended).** The pause itself needs none of this. These alerts exist because the *dashboard's* failure modes are otherwise invisible, especially the ESM purge recurring on a release upgrade (§0.3).

| Alert | Expression (TD finalizes) | for | Purpose |
|---|---|---|---|
| `HosClaudeUsageMetricsAbsent` | `absent(hos_claude_usage_poll_timestamp_seconds{instance="faberix"})` | 15m | node_exporter removed or purged, symlink broken, or S3 never applied |
| `HosClaudeUsagePollStale` | `time() - hos_claude_usage_poll_timestamp_seconds > 900` | 5m | poller dead while the exporter is alive (the `.prom` freezes) |
| `HosClaudeUsageReadFailing` | `hos_claude_usage_read_ok == 0` | 15m | the check is broken |
| `HosClaudeUsageTextfileError` | `node_textfile_scrape_error{instance="faberix"} > 0` | 15m | collector cannot read a file |
| `HosClaudeUsagePauseCondition` (info) | `hos_claude_usage_pause_condition == 1` | 0m | visibility |
| `HosClaudeUsageWeeklyTimeToThreshold` (warning, optional) | `predict_linear(hos_claude_usage_weekly_all_models_percent[6h], 86400) >= on(instance) hos_claude_usage_threshold_percent{window="weekly"}` | 30m | early warning (forecast at query time, FR-43) |

To enable it, a human on monitrix:
1. copies the file to `/etc/prometheus/rules/`;
2. uncomments `rule_files:` in `/etc/prometheus/prometheus.yml` with `- /etc/prometheus/rules/*.yml`;
3. runs `promtool check rules …` and `promtool check config /etc/prometheus/prometheus.yml`;
4. reloads with `sudo systemctl reload prometheus` (SIGHUP);
5. verifies at `/rules` and `/alerts` in the Prometheus UI.

Alerts route through the existing Alertmanager at `localhost:9093`. Which receivers fire is a §0.4 gap, recorded in the README.

**(3) Grafana: file provisioning (recommended) over UI import.** AC-20 requires the JSON to "load through Grafana provisioning without errors". Provisioning also makes the repo the source of truth, so a UI edit cannot silently drift the threshold line or the annotation query.
- Ship `contrib/monitoring/grafana/provisioning/hos.yaml`, a dashboards provider: `folder: HOS`, `allowUiUpdates: false`, `path: /var/lib/grafana/dashboards/hos`.
- Ship `contrib/monitoring/grafana/dashboards/hos-claude-usage.json` with a fixed `uid`, no `__inputs`, and a **`datasource`-type template variable** (`query: prometheus`). That form works under both provisioning and UI import (`${DS_…}` `__inputs` work only for UI import).
- An `instance` variable defaults to `faberix`.
- Human steps: copy the provider yaml to `/etc/grafana/provisioning/dashboards/`, copy the JSON to the provider path, `sudo systemctl restart grafana-server`, then confirm the dashboard appears under folder HOS with no provisioning errors in the Grafana log.
- *Rejected:* UI import (matches today's practice, but fails AC-20 as written and drifts).

**Panels (FR-46).** Every derived view is PromQL:
1. **Sawtooth.** Session % and weekly-all %, with the threshold line from `hos_claude_usage_threshold_percent` (it follows config, AC-20). Pause annotations come from `hos_claude_usage_pause_condition == 1`, **labelled "pause condition (machine)"**. They are not labelled "cycles paused", because AD-10 explains the difference.
2. **Early warning.** `predict_linear(...[1h], 3600)` for session and `[6h], 86400` for weekly, against the threshold.
3. **Subagent attribution.** `hos_claude_usage_top_subagent_percent` by `subagent`, one panel per window. Stacking is allowed, with a panel description: *"Top-N only and truncated (`+K more`, also plotted). A subagent leaving the list appears as a gap, not zero. Not a complete breakdown."*
4. **Behaviors.** Long-context % and 8h+-session % (plus subagent-heavy %) per window, **unstacked lines, never summed**. Panel description: *"Independent characteristics, not a breakdown; values overlap"* (AF-6). Shown alongside the sawtooth.

**(4) Artifact location: `contrib/monitoring/`** (new, with a `README.md` runbook). The repo has no existing convention for host-infra artifacts; I searched for existing `contrib/`, `ops/`, `monitoring/`, `dashboards/` dirs and found none outside the venv. `contrib/` is not listed in `framework_consumer_files.txt` and is not copied by `hos_install.sh`. A test asserts that no `contrib/` path ever appears in that list. Host-specific values (monitrix IP, `instance="faberix"`) live only in the README and in variable defaults, never in code. The README's verification steps on monitrix:
- query `hos_claude_usage_poll_timestamp_seconds{instance="faberix"}` (present, advancing every ~5 minutes);
- query `hos_claude_usage_read_ok` = 1;
- query `node_textfile_mtime_seconds{file=~".*hos_claude_usage.prom"}`;
- check the rules are loaded;
- check the dashboard renders.

The README also states: **"A release upgrade can purge the ESM `prometheus-node-exporter` build (it did on 2026-10-01). `HosClaudeUsageMetricsAbsent` and the absence of `hos_*` series on monitrix are how you notice. Reinstall, then re-run `bin/hos-usage-poll --check`."** The `--check` symlink/writability line (AD-6 item 7) also catches it from faberix.

### AD-12: Build slicing and risk tiers. (BINDING.)

> Superseded by Amendment 2 A2-18, which is itself amended by Amendment 4 A4-2 (S4 tier/merge) and A4-7 (S1 trip test gates S2).

| Slice | Contents | Tier | Merge |
|---|---|---|---|
| **S1: Poller + parser + reading file + settings + runbook** | `bin/hos-usage-poll` (poll, `--check`, `--print-setup`); `bin/lib/usage_pause.py` (parse, settings, evaluate, status I/O); D-1 + empty-session + AC-1 fixtures; T4.1b + T4.1 comment; static credential/suspend tests; `framework_consumer_files.txt`; CRON-SETUP §2a; MACHINE-ACCOUNTS pointer. **Exit criterion:** AC-16 recorded, meaning a real cron-fired poll on faberix produced `outcome=success`. | **HIGH** (credential-adjacent; feeds every pause decision) | HUMAN_REQUIRED (`bin/**`) |
| **S2: `hos-cron` cycle-start gate + visibility** | AD-7 block; per-role/project status file; AD-8 audit, pause issue, degraded issue, complete dedup, lock, auto-close. | **HIGH** (gates every autonomous cycle on every host; protected) | HUMAN_REQUIRED (`bin/**`, FR-49) |
| **S3: `.prom` export on faberix** | `render_prom` + the isolated write in the poller; `--check` item 7; root-step runbook; symlink verification (AD-10 precondition). | MEDIUM | HUMAN_REQUIRED (`bin/**`) |
| **S4: monitrix artifacts** | `contrib/monitoring/` rules, provider yaml, dashboard JSON, README; `promtool` lint test and dashboard JSON schema/panel test in CI; human applies on monitrix. | LOW-MEDIUM | normal (`contrib/` is not protected), with an infra-reviewer pass |

**Ordering.**
- S1 → S2 (S2 consumes S1's file contract).
- S1 → S3 → S4 (S4 needs metric names).
- **Deploy S1 (crontab installed, `--check` green) before S2 merges.** Otherwise the first post-merge cycle on faberix pauses with `poller_not_installed`. That is correct fail-closed behavior, but avoidable noise.
- **#1944 is satisfied by S1+S2.** S3/S4 deliver the dashboard scope.
- **If S2 is blocked for any reason, the issue stays open and escalates (AD-1). S3/S4 landing never closes it.**
- Each slice's PR states its dependencies on both sides.

---

## 3. Traceability (every ruled requirement)

| Req | Satisfied by | Note |
|---|---|---|
| FR-1 | AD-1, AD-12 | no off switch; S1+S2 required; blocker → escalate |
| FR-2 | AD-4, AD-6 | `claude -p /usage` text only |
| FR-3 | AD-6 | key, `from=`, no `claude-auth.env` |
| FR-4 | AD-5.1, AD-6 | `env -u` + static test (AC-15) |
| FR-5 | AD-6 | `-n`, `RequestTTY=no`; no pty workaround |
| FR-6 | AD-6 | pinned PATH + absolute `claude_bin` |
| FR-7 | AD-6, AD-4 | `timeout --kill-after`; no timeout binary → refuse |
| FR-8 | AD-9, AD-6 | `poll_interval_seconds` → crontab `*/N` via `--print-setup`; `--check` detects drift |
| FR-9 | AD-4, AD-5 | no model call; AC-25 via `$0.0000` on real read |
| FR-10 | AD-2, AD-4 | reference regexes ported to Python (interpretation flagged §5) |
| FR-11-FR-13 | AD-4 | content-decided; `empty_session` reason |
| FR-14 | AD-4 | fallback not shipped; AC-21 stub |
| FR-15 | AD-3, AD-4 | `parsed_via=grep` |
| FR-16 | AD-4, AD-10 | gauges only (AS-1) |
| FR-17 | AD-4, AD-10, AD-11 | pinned to D-1 sample; independent; never decides |
| FR-18, FR-19 | AD-7, AD-9 | 90/90, `>=` |
| FR-20 | AD-4 | window length never parsed or assumed |
| FR-21 | AD-7, AD-9 | default closed |
| FR-22 | AD-8 | degraded issue (+ DERIVED stale case, §5) |
| FR-23 | AD-7 | stateless gate; first fresh under-threshold read runs |
| FR-24 | AD-6 | poller never reads suspend/halt (static test) |
| FR-25 | AD-7 | no marker write/clear (static test); AC-11 |
| FR-26 | AD-7 | placed before `claude-auth.env`, probe, and every session |
| FR-27 | AD-3, AD-9 | one reading, one machine conf from literal `$HOME` |
| FR-28 | AD-7 | inputs exclude transcripts; AC-24 |
| FR-29, FR-30 | AD-9 | location decided; invalid → pause (Q11 pending) |
| FR-31-FR-33 | AD-3 | reading file + per-role/project status (Q5 confirm) |
| FR-34, FR-35 | AD-3, AD-6, AD-8 | `>` cron log; transition-only audit; no history |
| FR-36 | AD-7 | staleness 900 > 300+60; distinct reasons |
| FR-37-FR-39 | AD-8 | complete dedup (AF-3); per-project issue (Q15 confirm) |
| FR-40 | AD-1 | #1450 code untouched (AC-17) |
| FR-41 | AD-10 | existing node_exporter; no new port |
| FR-42 | AD-10 | **partial:** paused state exported machine-level only (§5) |
| FR-43 | AD-10, AD-11 | raw only; forecasts in PromQL |
| FR-44 | AD-3, AD-10 | absent not 0; `last_success=0` interpretation (§5) |
| FR-45 | AD-10 | rename in owned dir + symlink; **depends on symlink verification** (fallback/escalation in AD-10) |
| FR-46 | AD-11 | four panels, provisioning |
| FR-47, FR-48 | AD-6 | CRON-SETUP §2a; `--check` |
| FR-49 | AD-12 | HUMAN_REQUIRED stated |
| FR-50 | AD-2, AD-6 | standalone `*/5` crontab poller |
| AS-1 / AS-2 / AS-3 | AD-4 / AD-7 / AD-8 | carried as assumptions (§5) |
| D-1 | AD-4 | **resolved** (2026-10-02 capture) |
| D-2 | AD-4 | not shipped; remains open, not a v1 dependency |
| D-3 | §0.3, AD-10 | **resolved** (node_exporter reinstalled) |
| AC-1-AC-30 | AD-4 (1,4,5,18,21,25), AD-6 (6,7,15,16,22,27), AD-7 (2,3,8,10,11,23,24,28,29), AD-8 (9,10,14,30), AD-3 (12,13), AD-10/11 (19,20), AD-1 (17), AD-5 (26) | AC-16 is an S1 exit criterion |

**Unsatisfied ruled requirements: none.** **Partially satisfied, flagged:** FR-42 ("paused state" exported only at machine level). **Conditional:** FR-45 depends on a symlink precondition with a defined fallback. This never affects the pause.

---

## 4. Escalations

### Bound here, not escalated
- Placement under `bin/` (AF-2).
- Stateless gate, not `hos-suspend` reuse (Q16).
- The `/usage` exemption mechanics (Q8).
- Python port of the reference regexes.
- Haiku not shipped.
- Complete dedup (AF-3).
- Scrape config unchanged.

### ESC-1: Consumers get the fail-closed gate on upgrade (product boundary: pm-agent + human). AF-4.

> Resolved by Amendment 2 A2-15: option (a) (D10).

`bin/hos-cron` ships to consumers. After upgrading, a consumer host with no poller pauses every cycle (`poller_not_installed`, with an issue) until it does the §2a setup or sets `fail_mode=open`. Consumers on API-key billing have no subscription `/usage` at all, and for them only `fail_mode=open` plus a permanent `[DEGRADED]` issue is available. **This ADR does not add an off switch (FR-1).** The human decides between:
- (a) ship as designed, with a release note and an upgrade-checklist step; or
- (b) a consumer-only escape hatch.

(b) would need a new human ruling, because it is the "flag" FR-1 forbids, applied to installs other than this host. **This does not block S1/S2 on faberix.** It must be decided before the next release that ships S2 to consumers.

### ESC-2: monitrix and faberix root steps are human actions.

> Amended by Amendment 2 A2-14 and A2-20 (the monitrix step list changes; still human actions).

- faberix: the `/var/lib/hos-usage` + symlink step.
- monitrix: rules + `rule_files`, Grafana provider + JSON.

Sessions are denied `sudo` and do not reach monitrix. These are documented, not automated, and they gate only S3/S4 verification.

### ESC-3: The fail-open dead-poller case (AD-8 (b)) is DERIVED. Confirm, §5.

> Removed by Amendment 2 A2-19 (D3, D7).

### ESC-4: AF-3 (the existing breakers' first-page dedup) needs its own issue.

> Resolved by Amendment 2 A2-19: filed as #1946.

I am design-only this session and have not filed it. The orchestrating session should file it. #1944 does not depend on the fix, because AD-8 binds its own complete query.

---

## 5. Human confirmation required

> Superseded by Amendment 2 A2-20, which carries the current list.

1. **AS-1:** only session and all-models weekly trigger a pause. Per-model weekly values are gauges only.
2. **AS-2:** gate at cycle start only. A running cycle finishes, bounded by `HOS_CRON_MAX_SECONDS`. No mid-cycle kill.
3. **AS-3:** fail-open files one deduped `[DEGRADED]` issue after **N=3** consecutive failed polls (architect's proposed default). **Plus the DERIVED extension:** under fail-open, also file it immediately when the reading file is missing or stale (dead poller), AD-8 (b).
4. **Q11 (recommended rule):** missing conf → ruled defaults. Unreadable conf, invalid value, unknown key, or duplicate key → **pause regardless of `fail_mode`**, with a `needs-human` issue naming the key. No per-key fallback to defaults. Thresholds limited to 1-100.
5. **Q12 (recommended, security-reviewer to concur):** the `authorized_keys` entry should carry `restrict,from="127.0.0.1,::1",command="env -u … <abs claude> -p /usage"`, not `from=` alone. That limits the passphrase-less key to one read-only command. The design works either way.
6. **Q5 reconciliation:** one machine **reading** file (poller) plus one fixed-path **per-role/project status** file (each cycle check), both overwritten in full. Confirm this meets the per-role/project ruling.
7. **Q15:** one pause issue per **project repo** per episode (role-agnostic title), not one machine-wide issue.
8. **FR-42 / FR-44 interpretations:** "paused state" is exported as a machine-level `pause_condition` gauge (per-role/project state stays in status files). `last_success_timestamp_seconds=0` means "none on record".
9. **Grafana:** file provisioning (`allowUiUpdates: false`) rather than UI import.
10. **ESC-1:** consumer-upgrade behavior (option a or b).
11. **Human actions (not confirmations), when each slice lands:**
    - generate the loopback key, add the `authorized_keys` line, seed `known_hosts`, add the poller crontab line, run `--check` (S1);
    - the `/var/lib/hos-usage` + symlink root step on faberix (S3);
    - the rules, `rule_files`, and Grafana provisioning on monitrix (S4).

*Removed as done:* the node_exporter reinstall (verified 2026-10-02, §0.3) and the D-1 `/usage` sample capture (2026-10-02, §0.3).

---

## 6. Startup-gap analysis and affected sign-offs

Nothing for #1944 has been designed or built before this ADR, so **no prior sign-off is orphaned.** The #1450 breaker code and its sign-offs stand untouched (FR-40). AF-3's defect affects shipped breaker code, but #1944 does not change it, so ESC-4 carries it separately. One requirements correction for the TD: the requirements' "subagent-breakdown %" (FR-17/FR-42) is, per the D-1 sample, the **subagent-heavy behavior %**, an overlapping characteristic. Attribution comes only from the truncated Top-subagents list (AF-6). Build against AD-4/AD-10's names, not the requirements' wording.

---

## Human Review Required

**RISK: HIGH.** The gate sits in front of every autonomous cycle on every host that runs `hos-cron`. Under the fail-closed default, a defect stops all autonomous work. Under fail-open, a defect lets credits billing continue unwatched. The design handles both. Every decision-path failure resolves to a *named* pause (AD-7). Fail-open can never be silent, even with a dead poller (AD-8 (b)). The only inputs to the decision are three things a sandboxed session cannot write (AF-1, AF-2).
**CONFIDENCE: HIGH** on §0 (re-derived from the tree), AD-1 to AD-9, and AD-12. **MEDIUM-HIGH** on AD-10, which depends on the symlink precondition (fallback defined), and on AD-11's alert routing (receivers unknown).
**BLAST RADIUS:** `bin/hos-cron` cycle start (both roles, every project, every consumer on upgrade); new `bin/hos-usage-poll` + `bin/lib/usage_pause.py`; user crontab; `~/.ssh/authorized_keys`; `~/.hos/usage-pause/`; `~/.config/hos/usage-pause.conf`; `/var/lib/hos-usage` + one symlink in node_exporter's textfile directory; monitrix Prometheus rules and Grafana provisioning.
**Change classification: STRUCTURAL.** A new gate on every autonomous cycle, a new credential-bearing host path, and new host-infra artifacts. ESC-1 must clear the product-boundary checkpoint before S2 ships to consumers. S1/S2 on faberix may proceed on `technical-design` completion.

---

## Amendment 1 (2026-10-03, architect, TD review round 1)

These revisions come out of reviewing `TECHNICAL-DESIGN-1944-proactive-usage-pause.md`, DRAFT-1 (§9.1 there). They are appended; the text above is not rewritten. Where they conflict, this amendment governs. Startup-gap check: every item corrects a premise before any code exists, and the only artifact built against the superseded text is the TD, which was updated in the same round. **No sign-off is orphaned.**

- **A1-1 (AD-5, call site).** The sole `/usage` call site is **`bin/lib/usage_pause.py`**, not `bin/hos-usage-poll`.
  > Superseded in part by Amendment 2 A2-9: the template is now the forced-command text only.
  - It holds the remote command as one constant, `REMOTE_CMD_TEMPLATE`, and that constant is also the source of the `--check`/`--print-setup` forced-command text.
  - The T4.1 exemption is `bin/lib/usage_pause.py`, matched deterministically through its docstring.
  - T4.1b pins the template line and the sole call site.
  - AD-5.1's exact remote command is unchanged.
- **A1-2 (AD-6, time bound; AD-4 enum).** The `<timeout_bin> --kill-after=5 <t>` prefix is replaced by an in-process bound in Python: `Popen(start_new_session=True)`, `wait(read_timeout_seconds)`, then process-group SIGTERM, a 5 s grace, then SIGKILL.
  - The ssh argv and options are otherwise exactly as AD-6.
  - `no_timeout_binary` is removed from the failure enum, which now has eight reasons.
  - Timeout is observed directly, not inferred from exit code 124/137.
  - **Why:** a bash `_TIMEOUT_BIN` would be a permanent fourth entry in ADR-1643 AD-16.6's T4.2 ledger, which exists for AI-review timeout copies. The Python form is no more complex, removes the macOS coreutils dependency, and cannot mistake a remote exit code for a timeout.
  - FR-7 still holds: the read is always bounded.
- **A1-3 (AD-4, success criterion vs FR-11).** AD-4 stands: content decides. A transport failure (ssh exit 255, spawn failure, timeout) is a FAILED read whatever the content. Any other remote exit code is recorded as `remote_exit` and does not by itself fail the read.
  - This **overrides FR-11's literal "non-zero exit" item**. FR-11's own cited source (the reference parser's content-only condition) and FR-13 both support the override.
  - **Requirements amendment required:** pm-agent rewords FR-11. The human confirms, because the change narrows a failure list in the less-pausing direction.
  - pm-agent also rewords AC-25, which cannot be observed on the real success shape (TD §3.13 item 3 is the substitute).
- **A1-4 (AD-9, bounds).** `staleness_seconds` must be `> poll_interval_seconds + read_timeout_seconds` **and `≤ 7200`**. The upper bound stops a typo from becoming a near-disable, and 7200 keeps the range non-empty at the maximum interval. `claude_bin` must match `^/[A-Za-z0-9._+/-]{1,254}$` with no `/./` or `/../` segment, because it is interpolated into a remote command and an `authorized_keys` line.
- **A1-5 (AD-10, metrics).** `hos_claude_usage_threshold_percent` is emitted **only when settings are valid**. A new always-present gauge, `hos_claude_usage_settings_valid` (1/0), is added. Under invalid settings, `pause_condition` is 1.
  > Amended by Amendment 2 A2-12 (`limit` label, three thresholds).
- **A1-6 (AD-12, S4).** "A `promtool` lint test in CI" becomes: structural YAML/JSON and metric-name tests in CI, plus an `integration`-marked `promtool check rules` test that is skipped when `promtool` is absent. The human's `promtool check` output on monitrix is the recorded evidence. S4 does not touch `.github/workflows/**`.
  > Amended by Amendment 2 A2-18 (S4 now holds Grafana alerting files, not Prometheus rules).
- **A1-7 (AF-2, statement correction).** The OS-level half of AF-2 is narrower than stated. `denyWrite` covers only each role's **own** clone's `bin/`, while `allowWrite` covers all three clones, so a sandboxed Overseer or Human session can write `Worker/bin/*`. AF-2's governance half (CODEOWNERS → HUMAN_REQUIRED) and AF-1 (decision *data* outside every `allowWrite`) are unaffected.
  - This is a **pre-existing gap outside #1944's scope** (TD ESC-T1). #1944 neither widens it nor depends on closing it.
  - The fix (adding the three clones' `bin/` to `denyWrite`) is protected `contract/**` surface and needs security-reviewer review plus human approval.

**Confirmed without change** (clarifications the TD made under AD-3/AD-4/AD-8, now binding):
- exact-title dedup and auto-close, not prefix (AD-8);
- the complete query through `gh api --paginate … --jq` under `_REPO_SLUG`, using raw `gh` rather than the bootstrap wrappers, which do not ship to consumers (AD-8);
- one `key=value` per `_audit` argv element (AD-8);
- `lock_stale_reclaimed` as a `diagnostics` key, not a failure reason (AD-4);
- close-pending retry memory, the corrupt-previous-file close sweep, and the check-error flag (AD-8).

**Human confirmation added to §5:**
- 12: FR-11 narrowing (A1-3);
- 13: AC-25 rewording;
- 14: the A1-7 cross-clone `denyWrite` gap, a finding outside #1944's scope;
- 15: widening ESC-4 to every single-page dedup site in `bin/hos-cron` (`:954`, `:1430`, `:1682`, `:1760`, `:1801`, `:2063`, `:2167`, `:2191`) and `query_issues.sh --list`;
- 16: the collapsed `_audit` call at `bin/hos-cron:2054`.

Items 1–11 of §5 are unchanged and unresolved.

---

## Amendment 2 (2026-10-03, human rulings D1-D19)

**Source.** Human rulings, interactive session 2026-10-03, D1–D19 (cited "D<n>"), as transcribed by pm-agent into `REQUIREMENTS-1944-proactive-usage-pause.md` Amendment 3, plus the second real capture (`usage-sample-2-json.txt`, faberix, `--output-format json`, jq-filtered to `{result, total_cost_usd, usage}`). The rulings are authoritative. Where this amendment conflicts with the text above or with Amendment 1, **this amendment governs**. Each superseded AD carries an inline pointer. Earlier text is not rewritten.

**Startup-gap check.** Every item here is a human ruling or follows from one, and each lands before any code exists. The only artifacts built against the superseded text are this ADR and `TECHNICAL-DESIGN-1944-proactive-usage-pause.md` (DRAFT, not approved). Affected sign-offs: §A2-22.

### A2-1: Core deliverable and definition of done (supersedes AD-1's "done when S1 and S2 merged"; D7, D17, AC-44)

- AD-1 stands as written in these respects: the proactive check ships enabled, there is no off switch, and a blocker that prevents a real read stops the build and escalates.
- **#1944 is done only when a real pause alert reaches the human by email.** That means a recorded end-to-end run in which a real reading produces `hos_claude_usage_pause_condition = 1` on faberix, the Grafana alert fires, and the email arrives through the HOS contact point (AC-44). Merged code does not satisfy #1944 until that run is recorded. Neither do a test alert (AC-43) or a stubbed alert.
- **S2 may merge, and run on faberix, before alerting is live.** Under the default `fail_mode=closed`, a pause nobody is alerted to is safe: autonomous work stops and no credits are spent. The cost is lost throughput, not lost money. **`fail_mode=open` must not be set on faberix until A2-18's S5 is recorded.** Fail-open is safe only once alerting is live (D3, FR-67), and the runbook says so.
- *(Procedure confirmed by human ruling H-4; see Amendment 4 A4-6.)* Procedure for the AC-44 run (TD to finalize; the human performs it): set `session_threshold` to a value at or below the current session % in `usage-pause.conf`, wait for one poll, confirm the email arrives, then restore the setting. This is a real pause from real data. Every autonomous cycle on the host skips while the threshold is lowered, which is intended.

### A2-2: Exactly one reading file (supersedes AD-3's per-role/project status file; D6)

- There is one file, **`${HOS_STATE_DIR:-$HOME/.hos}/usage-pause/reading`** (renamed from `reading.status`). Only the poller writes it. Every poll overwrites it in full, failures and crashes included.
- **`hos-cron` only reads it. It writes nothing under `~/.hos/usage-pause/`.** No per-role or per-project status file exists. A static test asserts that the `hos-cron` gate block and `usage_pause.py check` contain no write to that directory.
- The following parts of AD-3 stand:
  - format: `key=value`, `schema=1` first, `end=1` sentinel last, sanitized single-line values;
  - atomic write: fixed `.tmp` sibling, then `rename(2)`;
  - an `ERR`/`EXIT`-equivalent crash path still writes `outcome=crashed`;
  - absent values are omitted, never written as 0;
  - the location stays outside every sandboxed role's `allowWrite`/`allowRead` (AF-1).
- Also removed: episode memory (`paused_since`, issue number), and with it all transition detection inside `hos-cron` (A2-5).

### A2-3: Who decides; what the reading file holds (P1; supersedes AD-3's `machine_decision` and AD-7's per-role status write; D4, D6, FR-33)

- **`hos-cron` is the decider.** Each cycle, `usage_pause.py check` loads and validates the **current** `usage-pause.conf` itself and computes the decision from that conf, the reading file's raw values and read status, and the clock. AD-7's "the consumer recomputes" rule now has no exceptions.
- **The reading file holds the poller's raw reading and read status.** That covers every parsed field (A2-7, A2-8), `outcome`/`reason`/`detail`, `remote_exit`, `consecutive_failures`, `last_success_epoch`, and `diagnostics`.
- **It also holds the poller's view, marked informational:** `poll_settings_status=valid|defaults|invalid:<key>`, `poll_pause_condition=0|1`, and `poll_pause_reason`. *Departure from the P1 default, with reason:* FR-33 (from D1/D4) requires the reading file to carry "the resulting pause decision with its reason", and D4 requires it to "name the bad key". These fields are also what the `pause_condition`/`settings_valid` gauges and the history backfill are rendered from (A2-11). Keeping the decision authority in `hos-cron` and the poller's view in clearly named `poll_*` keys meets both rulings.
- **Binding:** `usage_pause.py check` never reads any `poll_*` key. A static test asserts this. A test with a reading that says `poll_pause_condition=0` and an over-threshold `session_pct` asserts **pause**.
- **Disagreement.** The poller and `hos-cron` can disagree when the conf is edited between polls. When they do, `hos-cron`'s per-cycle evaluation governs the pause, and the gauges catch up at the next poll (at most `poll_interval_seconds`). The `hos-cron` log line names the bad key: `[PAUSED-USAGE] settings_invalid:<key> (fail_mode ignored)`. The poller validates the conf only to set `poll_settings_status`, `settings_valid`, and the threshold gauges.

### A2-4: Global, stateless pause, separate from `hos-suspend`; gate placement (amends AD-7; D7b, D2)

- **Scope.** All projects and both roles on the host consume the same reading and the same machine conf, and each decides the same way. That makes the pause global with no shared mutable state. It is **stateless**: the pause has no marker, no state file, and no memory. Each cycle decides from scratch (AD-7). Interactive sessions are never gated. The gate exists only in `hos-cron`.
- **Separate from `hos-suspend`.** AD-7's rule and its static test stand: no read, write, or clear of `~/.hos/suspend/`, and no call to `hos-suspend`. The existing suspend check still runs first.
- **"Only where the running `hos-cron` copy has the gate" (D7b).** The gate code carries a fixed sentinel comment, `# HOS-USAGE-PAUSE-GATE schema=1`. `hos-usage-poll --check` adds a read-only item: for every user-crontab line that invokes a `hos-cron`, it resolves the invoked file and reports PASS if the sentinel is present and FAIL naming the path if not. The runbook requires a green result after every upgrade of any project.
- **Placement (supersedes AD-7's "after git credentials").** That placement existed only because AD-8 needed `GH_TOKEN`, and D7 removed that dependency. The gate now goes **immediately after the audit helper is defined (`bin/hos-cron` :361-366), with the overlap lock held, and before audit-log sync (:367)**. It therefore runs before worktree hygiene, the dependency check, jitter, wakeup handling, the GitHub App token mint (:834), `claude-auth.env` (:877), and every GitHub or Claude call. The benefits:
  - a paused cycle makes **zero network calls of any kind**, so AC-35 is testable at the whole-cycle level, not just for the gate block;
  - wakeup markers are left for the next running cycle;
  - a paused cycle costs milliseconds.

  The TD fixes the exact line and confirms nothing in :334-366 that the gate needs is missing. A missing `python3` is caught here as `check_error`, which pauses (AD-7 rule 5).
- **In-flight (D2, P9).** AD-7's cycle-start-only rule is confirmed. **This feature adds no in-flight bound of its own.** The existing per-fire cap (`HOS_CRON_MAX_SECONDS`) applies unchanged. No test or code in #1944 depends on that cap's value.

### A2-5: No GitHub calls; AD-8 removed; what visibility remains (supersedes AD-8 entirely; D7, D3, Q17, P2)

> Amended by Amendment 4 A4-1: "no event on a running cycle" no longer holds for fail-open cycles that run without a usable successful reading. Each emits one `cycle-usage-unchecked` event (H-1).

- **Removed:**
  - the `[PAUSED]` and `[DEGRADED]` issues;
  - the invalid-settings issue;
  - dedup, the issue lock, and auto-close;
  - `failopen_issue_after`;
  - transition detection;
  - the `cycle-usage-pause`/`cycle-usage-resume`/`cycle-usage-degraded` transition events.
- `usage_pause.py` and the gate block contain no `gh`, no `curl`, and no GitHub URL. A static test enforces this, and AC-35 enforces it at runtime with a stubbed `gh` that fails the test if called. TD-O-2 and ESC-T3 are moot.
- **Per-cycle log line (binding).** Every gated cycle prints exactly one line to the existing cron log:
  - `[PAUSED-USAGE] <reason>` on a pause;
  - `[USAGE-OK] <summary>` on a run with a fresh successful reading;
  - `[USAGE-UNCHECKED] fail_mode=open <reason>` on a fail-open run without a usable successful reading.
- **Audit (P2 overridden, with reason).** P2 recommended audit events on pause/resume transitions only. D6 removed the only place `hos-cron` could remember the previous decision, and a stateless gate cannot detect a transition without reintroducing exactly the per-role state D6 removed. D6's own rationale is that "per-cycle decisions are already in the hos-cron log **and the audit events**". So:
  - **one `cycle-usage-paused` audit event per paused cycle**, with fields `role`, `reason`, `session_pct`, `weekly_all_pct`, `reading_age_s`, `fail_mode`, `settings`, one `key=value` per `_audit` argv element (A1 confirmation);
  - **no event on a running cycle**. The existing `cycle-start` event (:1823) records it;
  - resume is visible as a `cycle-start` with no preceding `cycle-usage-paused`.

  Growth is bounded by cycle cadence and is lower than a running cycle's (a running cycle emits `cycle-start` plus several subagent events). This is not per-poll (FR-34). **No decision reads an audit event** (ADR-1604 AD-4 rule, unchanged).
- **Human visibility** is now: Grafana alerting (A2-13) on faberix; the cron log line everywhere else. A2-15 covers what that means for consumers.

### A2-6: Three pause thresholds (amends AD-4 per-model, AD-7 rule 3, AD-9; D1)

- **Decision rule 3 becomes:** on a usable `outcome=success` reading, **pause iff** `session_pct >= session_threshold` **or** `weekly_all_pct >= weekly_threshold` **or**, for **any** per-model line present, `weekly_model_pct >= weekly_model_threshold`. The comparison is `>=` everywhere.
- **Resume** happens when all present limits are `<` their thresholds.
- One `weekly_model_threshold` applies to every model line.
- **A missing per-model line is not a failure** and contributes nothing. Only the session and all-models lines are required (FR-11 unchanged).
- **Reason format (binding, stable for log greps).** Every limit at or over threshold is listed, in the fixed order session, `weekly_all`, then `weekly_model:<Name>` sorted by name, joined by `; `, and capped at 200 chars. Example: `weekly_model:Fable 91% >= 90`. `<Name>` is the raw model name with control characters stripped, length-capped. The gauge label uses the sanitized form (AD-10).
- The AD-4 per-model sentence "gauges only and never feed the decision" is superseded.

### A2-7: `--output-format json`; parse `result`; revised failure classification (amends AD-4; D13, D12)

- **The read returns a JSON envelope.** The poller parses **all of stdout** as one JSON object, using strict `json.loads` on the decoded, 64 KiB-capped bytes. It never scans for a JSON fragment inside other text.
- The threshold text is the envelope's `result` field, which must be a string. AD-4's regexes, last-match-wins rule, no-clamping rule, integer-only rule, ANSI stripping, and U+00B7 handling all apply to `result`.
- **No unseen field is depended on (D13, FR-2).** The parser reads exactly three fields: `result`, `total_cost_usd`, and `usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`. Every other field is ignored, and adding or removing other fields changes nothing (AC-49).
- **Success (FR-11, D12/A1-3 confirmed)** is unchanged: both `% used` lines parsed from `result`. A non-zero remote exit with both lines parsed is a success, with `remote_exit` recorded. ssh, spawn, and timeout failures fail regardless of content. **Cost 0 / tokens 0 never establishes success** (D13).
- **Failure enum (supersedes AD-4 and A1-2's list; closed, stable):**
  - `ssh_failed`
  - `timeout`
  - `spawn_failed`
  - `envelope_invalid`: stdout is not one JSON object, or `result` is missing or not a string
  - `empty_session`: valid envelope, and `result` is empty/whitespace or contains the legacy `Total cost:` / `Usage: 0 input` markers, with no `% used` line
  - `missing_session`
  - `missing_weekly`
  - `unparseable`: non-empty `result` with neither line, not the empty shape
  - `crashed`

  `claude_not_executable` is **removed** from the poll-time enum. The client no longer names the binary (A2-9), so a bad path shows up as `envelope_invalid`. It survives only as a `--check` line item. The TD pins the JSON empty-session fixture synthetically until a real one is captured. The capture-2 envelope becomes the second real fixture.
- **Breakdown (AD-4, FR-17) is reconfirmed under capture 2.** Every breakdown line is **individually optional**. Capture 2's `Last 7d` window has no `8+ hours` line, and that series is absent, not 0 (AC-18). Window headers are matched generically as `Last (\S+) · N requests · M sessions`, with the window label sanitized. The parser does not assume only `24h`/`7d` exist.
- **`--check` captures the full envelope (D13, AC-49).** This is a narrow exception to AD-6's "`--check` writes no state". `--check --capture-fixture <path>` writes the unfiltered stdout of its real read to the operator-named path, and nowhere else. Plain `--check` still writes nothing. The captured file is committed as a fixture by a later PR.

### A2-8: Read-cost gauges (P5, D13)

- **`read_cost_usd`** = the envelope's `total_cost_usd` (float, ≥ 0 as reported).
- **`read_tokens`** = **one summed value**: `input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens`. `output_tokens_details.thinking_tokens` is **not** added, because it is a sub-count of output and adding it would double-count.
- The reading file and history also carry each of the four token counts separately (A2-11). Only the sum is a gauge.
- Each value is recorded whenever the envelope parsed, **including on a failed read** (`empty_session` is exactly when a stray model call would show). If any of the four token fields is missing or non-numeric, `read_tokens` is **absent**, not a partial sum. The same applies to cost.
- **Any non-zero value fires the alert** (A2-13). An absent cost or token value on a successful read also fires (`HosClaudeUsageReadCostUnknown`), so a CLI change that drops the field cannot silently disable the FR-9 check.

### A2-9: The forced command; the call site; credential hygiene (supersedes AD-5's command text and AD-6's `authorized_keys` recommendation and client-side unsets; amends A1-1; D5, P4, P8)

- **The `authorized_keys` line is exactly** `from="127.0.0.1,::1",command="<abs claude_bin> -p /usage --output-format json" ssh-ed25519 AAAA… hos-loopback`. It has those two options and **no others**: no `restrict`, and no `no-pty`/`no-port-forwarding`/`no-agent-forwarding`/`no-X11-forwarding`/`no-user-rc` (P4; the human ruled against `restrict` as fragile, and the individual options carry the same risk).
- **No environment unsetting anywhere.** There is no `env -u`, no `unset`, no `os.environ.pop`/`del`, and no curated `env=` for the ssh subprocess. The poller passes its inherited cron environment through, apart from AD-6's pinned `PATH`, which sets a variable and removes none.
- The AD-6 "the poller `unset`s the three variables in its own process" sentence is superseded. AC-15's static test now asserts the **absence** of every unsetting form on both sides, as well as the absence of `claude-auth.env` sourcing.
- **The client sends no remote command.** The ssh argv ends at the host (`… 127.0.0.1`). sshd runs the forced command for the session request. *Reason:* if the client also sent `claude -p /usage …`, a line that had lost its `command=` would still produce a successful read while granting an unrestricted shell, and nobody would notice. With no client command, a missing forced command gives a login shell on `/dev/null` stdin, which produces no JSON (`envelope_invalid`). D5's restriction therefore becomes a precondition of every successful poll, not just of `--check`. AD-6's other ssh options stand.
- **The claude path is host-specific (P8).** It is never hardcoded in HOS. `hos-usage-poll remote-cmd` prints the forced-command text, built from `claude_bin` (setting, or resolved with the pinned PATH), and `--print-setup` embeds that output. The only `claude … /usage` string in the tree is the template constant in `bin/lib/usage_pause.py` (A1-1's `REMOTE_CMD_TEMPLATE`, now `"{claude_bin} -p /usage --output-format json"`), and it is never executed by HOS code.
- **T4.1b** pins:
  - that template exactly (no `--model`, no prompt, no other flag);
  - that it is the sole `/usage` string under `bin/`, `scripts/`, `bootstrap/`;
  - that the poller's ssh argv has no element after the host.

  A1-1's T4.1 exemption mechanics stand. The exemption reason becomes "non-agent `/usage` forced-command template; executed by sshd, not HOS (ADR-1944 A2-9)".
- **`--check` line 2 (amended):** the `authorized_keys` line for the key must be byte-equal, in its options and command, to the `remote-cmd` output. A difference fails the check and names the difference.
- **Residual risk, recorded and ACCEPTED (D5; human ruling "notoriously fragile").**
  - **Environment.** Nothing scrubs the server-side environment. Correctness relies on (i) the login environment never exporting `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_*`, and (ii) sshd's `AcceptEnv` and the client's `SendEnv` not carrying them (the Ubuntu defaults carry only `LANG LC_*`). **Detector:** `/usage` under the OAuth token returns the empty-session shape, so the leak shows up as a failed read (`empty_session`). That pauses under fail-closed and fires the read-failed alert. It is caught by `--check`'s real read at setup and by every later poll.
  - **No `restrict`.** Without it, the key holder can request port forwarding and a pty. The key is mode 0600 and owned by scott, and `from=` admits loopback only, so anyone able to use it is already scott on faberix. There is no escalation. security-reviewer reviews this residual in S1.
- **AD-12/AC-48:** the swapped-in line is not final until a real `--check` read returns real percentages. That run is an S1 exit criterion.

### A2-10: Settings (supersedes AD-9's table and its issue clause; D1, D4, D18, D19, P3)

| Key | Default | Valid |
|---|---|---|
| `session_threshold` | `90` | integer 1-100 |
| `weekly_threshold` | `90` | integer 1-100 |
| `weekly_model_threshold` | `90` | integer 1-100 (new, D1) |
| `fail_mode` | `closed` | `closed` \| `open` |
| `poll_interval_seconds` | `300` | integer multiple of 60, 60-3600 |
| `staleness_seconds` | `900` | integer `> poll_interval_seconds + read_timeout_seconds`, ≤ 7200 (A1-4) |
| `read_timeout_seconds` | `60` | integer 5 to `poll_interval_seconds − 30` |
| `history_days` | `90` | integer 1-3650 (new, D18) |
| `history_max_mb` | `100` | integer 1-10240 (new, D18) |
| `claude_bin` | unset → resolved | absolute path matching A1-4's pattern; used only by `remote-cmd`/`--print-setup`/`--check` |

- **Removed:** `failopen_issue_after`. Because unknown keys are invalid, a conf still carrying it pauses with `settings_invalid:failopen_issue_after`. No host has such a conf today.
- **P3 confirmed.** `staleness_seconds ≤ poll_interval_seconds` is invalid (A1-4's bound is stricter and implies it), and an unknown `fail_mode` is invalid.
- **D4 confirmed.** A missing file means the defaults. Any of the following **pauses regardless of `fail_mode`** with `settings_invalid:<key>`: an unreadable file, an invalid value, an unknown key, or a duplicate key. That **includes the history keys**: D4 makes no exception, so a typo in `history_days` pauses all autonomous work. This is safe-direction, and it is recorded so it is not a surprise.
- **No issue is filed** (D7). The bad key is named in the `hos-cron` log line (authoritative, A2-3), in the reading file's `poll_settings_status` (as of the last poll), and through the `settings_valid=0` gauge and alert.
- **The poller under invalid settings** keeps polling with **defaults for its own operational keys only** (`read_timeout_seconds`, `history_*`). It records `poll_settings_status=invalid:<key>`, emits `settings_valid=0` and `poll_pause_condition=1`, and emits no threshold gauges (A1-5 stands).
- **No hardcoded thresholds (D19).** Every numeric limit the poller or gate compares against comes from this table. The defaults live in one named constant block at the top of `usage_pause.py`. A static test asserts that no other numeric literal in the module equals a default threshold within a comparison.

### A2-11: History log, `last-raw`, export, write order (extends AD-10 isolation; D18, P6, FR-52-FR-55)

- **History.** One JSON object per poll is written to `~/.hos/usage-pause/history/usage-YYYY-MM-DD.jsonl` (the UTC date of `run_epoch`). **The line carries every key in the reading file** (P6): raw percentages, per-model values, every breakdown field, cost, the four token counts, outcome/reason, and the `poll_*` fields. A backfill can therefore restore every dashboard panel, including the pause annotations and the threshold lines.
  - The line is written as **one `write(2)` with `O_APPEND`** and is ≤ 16 KiB (oversized optional fields are dropped first, breakdown before core).
  - A torn final line from a crash is skipped by `export`, which counts and reports it, never fatally.
  - Directory mode 0700, files 0600.
- **Pruning** runs on every poll, **after** the history append. It deletes files whose date is older than `history_days`, then deletes the oldest remaining files until the total is ≤ `history_max_mb`. Whichever limit is hit first governs, and today's file is never deleted. Only names matching `usage-\d{4}-\d{2}-\d{2}\.jsonl` in that directory are ever touched, which stops a bad config from deleting anything else. Pruning failure counts as a history-write failure.
- **`last-raw`.** `~/.hos/usage-pause/last-raw` (0600) holds the full raw stdout of this poll's read (capped at 64 KiB) plus a header line with `run_epoch`, the ssh exit, and the timeout flag. It is overwritten each poll, atomically through `.tmp` + rename. On a transport failure it holds the stderr tail instead. It is debugging data, and nothing reads it for a decision.
- **Write order (binding, D18):**
  1. the reading file (the decision input);
  2. the `.prom`;
  3. the history line plus pruning;
  4. `last-raw`.

  Steps 2-4 are each independently best-effort. Each is wrapped so that a failure is logged to `poll.last.log` and changes nothing earlier in the sequence.
- **`history_write_ok` vs the order.** The `.prom` is written before the history attempt, so it cannot carry that attempt's result. **Resolution:** after step 3, the poller **re-renders and atomically replaces the `.prom` once more** with this poll's `history_write_ok`. The first render omits the gauge, so for milliseconds it is absent, never a false 1. The re-render is itself best-effort. This keeps D18's order, since the reading file is still first and untouched. The isolation test (AD-10) extends to all three best-effort steps.
- **Export (FR-53).** `hos-usage-poll export --from <ISO|epoch> --to <ISO|epoch>` reads the history files and writes OpenMetrics to stdout. Each history line yields its gauges with the line's `run_epoch` as the sample timestamp, using **the same metric names, labels, and absent-not-zero rules as `render_prom`**: one renderer, two clocks. The output ends with `# EOF`. It is read-only and takes no lock. The runbook covers `promtool tsdb create-blocks-from openmetrics` and moving the blocks into monitrix's TSDB. AC-38 is the round-trip test.

### A2-12: Metrics contract (amends AD-10's table and A1-5; D8, D13, D19)

The table changes are:
- **`hos_claude_usage_threshold_percent{limit}`**: `limit` is `session` \| `weekly_all` \| `weekly_model` (replaces the `window` label). It is present only when settings are valid (A1-5).
- **New: `hos_claude_usage_staleness_seconds`.** The staleness window the poller is using. It is **always present**, and under invalid settings it is the default value, so the poll-stale alert can still fire while `settings_valid=0`. It exists so the poll-stale alert compares against config, not a literal (D19).
- **New: `hos_claude_usage_read_cost_usd` and `hos_claude_usage_read_tokens`** (A2-8). Present whenever the envelope yielded them, success or failure.
- **New: `hos_claude_usage_history_write_ok`** (A2-11).
- **`hos_claude_usage_settings_valid`** (A1-5, now D4-ruled).
- **`hos_claude_usage_pause_condition`**: one machine-level series (D8). It is 1 iff, by the poller's evaluation, any of the three limits is at or over threshold, **or** the read failed under `fail_mode=closed`, **or** settings are invalid. Otherwise 0. It is the poller's view (A2-3). `hos-cron` may disagree for up to one poll interval after a conf edit, and when the poller is dead the series freezes. The stale alert covers that case.
- **`hos_claude_usage_last_success_timestamp_seconds = 0`** when none is on record. This is the D8-ruled exception, and AD-10's interpretation is now confirmed.
- **Breakdown series** take a generic `window` label (A2-7).

Everything else in AD-10 stands: absent-not-zero, raw values only, label hygiene, the scott-owned `/var/lib/hos-usage` plus symlink, and the symlink-verification precondition and its fallback.

### A2-13: Grafana alerting, contact point, worked example (supersedes AD-11 (2) and its Alertmanager routing; amends AD-11 (3); D17, D17b, D19)

> Amended by Amendment 4 A4-3 (a required-alert guard test pins the rules that are the human's only signal, plus the contact point's two integrations) and A4-5 (a 13th rule, `HosMonitoringAlertingReloadFailed`).

- **Grafana alerting, not Prometheus rules or Alertmanager.** `prometheus.yml` is untouched: `rule_files` stays commented and the `alertmanager` stanza is left alone. AD-11's `hos-claude-usage.rules.yml` is not shipped. Scrape config: AD-11 (1) stands.
- **Provisioned files** are all under `contrib/monitoring/grafana/provisioning/`:
  - `dashboards/hos.yaml` (AD-11 (3) stands; `allowUiUpdates: false`);
  - `alerting/hos-rules.yaml` (folder `HOS`, one rule group);
  - `alerting/hos-contact-point.yaml`.
- **Rules route by rule-level notification settings** (simplified routing: each rule names the receiver `hos`). They do **not** provision a notification-policy tree, because provisioning policies replaces the whole tree on monitrix, which could clobber anything else configured there. The TD verifies that Grafana 13.2.3 supports rule-level `notification_settings.receiver` in file provisioning. **Fallback if it does not:** escalate. Do not provision the policy tree without a human ruling.
- **Required alert rules (FR-62, D17), each comparing against a gauge or a named value, never a literal threshold:**

| Rule | Condition (TD finalizes PromQL) |
|---|---|
| `HosClaudeUsagePauseCondition` | `hos_claude_usage_pause_condition == 1` |
| `HosClaudeUsageReadFailing` | `hos_claude_usage_read_ok == 0` |
| `HosClaudeUsagePollStale` | `time() - hos_claude_usage_poll_timestamp_seconds > on(instance) hos_claude_usage_staleness_seconds` |
| `HosClaudeUsageMetricsAbsent` | `absent(hos_claude_usage_poll_timestamp_seconds{instance=~"$instance"})` (NoData handled explicitly) |
| `HosClaudeUsageSettingsInvalid` | `hos_claude_usage_settings_valid == 0` |
| `HosClaudeUsageReadCostNonzero` | `hos_claude_usage_read_cost_usd > 0` |
| `HosClaudeUsageReadTokensNonzero` | `hos_claude_usage_read_tokens > 0` (separate rule, AC-41) |
| `HosClaudeUsageReadCostUnknown` | read_ok == 1 and either cost/token series absent (A2-8) |
| `HosClaudeUsageHistoryWriteFailing` | `hos_claude_usage_history_write_ok == 0` |
| `HosClaudeUsageTextfileError` | `node_textfile_scrape_error > 0` (AD-11, retained) |
| `HosMonitoringSyncStale` | A2-14 |
| `HosClaudeUsageWeeklyTimeToThreshold` (warning, optional) | `predict_linear(...) >= on(instance) hos_claude_usage_threshold_percent{limit="weekly_all"}` |

  - `== 0`/`== 1`/`> 0` against boolean or must-be-zero gauges are semantics, not thresholds.
  - Pending durations (`for:`) and the sync-stale bound are **named values at the top of the rules file**: a YAML-anchor block such as `x-hos-named-values:` with `&hos_for_default 15m`. The TD verifies that Grafana's provisioning parser accepts anchors. **Fallback:** a header table of named values, plus a static test that every duration in the file appears in that table (AC-45).
  - NoData and Error states are set per rule so that a missing series fires **only** `MetricsAbsent`/`SyncStale`, not every rule at once.
- **Contact point `hos`** has two integrations (D17):
  - **email**: a webhook to the Cloudflare Worker, with `authorization_scheme: Bearer` and the credential taken from a Grafana provisioning env-var reference;
  - **SMS**: a webhook to an SMS relay, URL from an env var.

  **The repo carries only variable names** (`HOS_ALERT_EMAIL_WEBHOOK_URL`, `HOS_ALERT_EMAIL_WEBHOOK_SECRET`, `HOS_ALERT_SMS_WEBHOOK_URL`) and the README documents setting them in Grafana's env file on monitrix (`/etc/default/grafana-server`, mode 0640 root:grafana). A static test rejects any `https?://` other than placeholders or documentation hosts, and any token-shaped string, under `contrib/monitoring/` (AC-47). Until an SMS provider exists (D-5), the SMS URL is a documented non-routable placeholder. The TD verifies that a failing SMS integration does not suppress the email integration. Grafana delivers per integration, and AC-43 proves it.
- **Datasource reference.** Alert rules reference the Prometheus datasource by UID through an env var or a documented README substitution. They never hardcode monitrix's UID.
- **Worked example, not a requirement (D17b).** `contrib/monitoring/README.md` plus `docs/MONITORING-WORKED-EXAMPLE.md` (TD may merge the two) present faberix poller → node_exporter → monitrix Prometheus → Grafana alerting → Worker email + SMS relay as **"our recommended setup"**. HOS guarantees only three things: the poller, the gate, and the metrics contract (A2-12's names, labels, and absent-not-zero semantics). The metrics contract is therefore versioned with the reading-file `schema`, and a rename is a breaking change recorded in release notes.

### A2-14: monitrix delivery: sparse anonymous clone, sync job, sync health (supersedes AD-11's "human copies files" steps; D9)

> Superseded in part by Amendment 4:
> - **A4-2 / A4-3:** the bullet "`contrib/monitoring/**` becomes protected surface" is **withdrawn** (H-2 rejected). Its threat model ("the alerts could be removed by the agent they watch") still stands. The control becomes the required-alert guard test.
> - **A4-4 / A4-5:** the reload mechanism is ruled (H-3), a root systemd path unit. The alerting provisioning files are **copied** by the reload service, not symlinked into the clone. The sync job no longer writes a reload sentinel.

- **Clone.** On monitrix, a dedicated unprivileged user (`hos-sync`, human-created) owns `/opt/hos-monitoring` (0755, readable by `grafana`). It holds an anonymous-HTTPS clone of the public HOS repo, `--filter=blob:none --sparse`, with sparse-checkout `contrib/monitoring/`. There is no deploy key and no credential.
- **Grafana points at the clone.** The dashboard provider `path` points into the clone. The alerting provisioning files are symlinked from `/etc/grafana/provisioning/alerting/` into the clone (one-time root step; the TD verifies Grafana follows those symlinks, with copying-at-sync as the fallback).
- **Sync job.** It runs from `hos-sync`'s crontab every 5 minutes (named value), as a script **installed outside the clone** at `/usr/local/bin/hos-monitoring-sync` by the human. A pull can therefore never change the code that performs the pull (the D14 principle, applied to monitrix). It runs `git -C /opt/hos-monitoring pull --ff-only` and nothing else that mutates the clone. A non-fast-forward fails and leaves the old content in place. Its output goes to a fixed-path, overwritten log.
- **Sync health gauges** are written with AD-10's owned-dir + symlink pattern into monitrix's node_exporter textfile directory (root step on monitrix, mirroring faberix):
  - `hos_monitoring_sync_last_success_timestamp_seconds` (0 if none);
  - `hos_monitoring_sync_ok` (1/0);
  - `hos_monitoring_sync_deployed_commit_info{commit="<sha>"} 1`;
  - `hos_monitoring_sync_stale_after_seconds` (named value in the installed script's header).
- **`HosMonitoringSyncStale`** fires on `time() - last_success > on() stale_after` or `sync_ok == 0`.
- **D9 premise correction: Grafana reloads provisioned dashboards on its own, but not alert rules or contact points.** Alerting provisioning is read at startup or through the admin reload API. Without a reload, a pushed rule change would show up in `deployed_commit` while Grafana kept running the old rules, and no gauge would notice. **Binding:** after a pull that changed anything under `grafana/provisioning/alerting/`, the sync job triggers an alerting reload. The mechanism is a human checkpoint (A2-20 item H-3) because it adds a privilege on monitrix. **Recommended:** the sync job touches a sentinel file, and a root-owned, human-installed systemd `.path` unit restarts `grafana-server` on it. This needs no new credential and runs no repo code as root. The alternative is a Grafana service-account token used for `POST /api/admin/provisioning/alerting/reload`. Until it is ruled, the README says "restart grafana-server after any alerting change" and AC-50's evidence includes a restart.
- **`contrib/monitoring/**` becomes protected surface (new, binding).** With issues gone (D7), these alert rules are the **only** human-facing signal of a pause, a broken check, or a non-zero read cost. Under AD-11 they sat in unprotected `contrib/`. A worker PR could then delete `HosClaudeUsagePauseCondition` or the cost alert at LOW tier, the overseer could auto-merge it, and monitrix would pull it within 5 minutes. That is the agent weakening its own alarm: AF-2's failure class, moved from the brake to the alarm. S4 adds `contrib/monitoring/**` to `scripts/framework/protected_surfaces.txt` (→ CODEOWNERS → HUMAN_REQUIRED). This is stricter, so it needs no product ruling, but it is itself a protected-surface edit that the human approves in S4's PR.
- `hos_install.sh` never ships `contrib/` (AD-11 (4) test stands).

### A2-15: Consumers (resolves ESC-1 as option (a); amends AF-4; D10)

> The "Open: P7" bullet is resolved by Amendment 4 A4-1 (H-1 confirmed: a per-cycle `cycle-usage-unchecked` audit event plus explicit release-note text; no block, no issue).

- **Option (a), as ruled.** A consumer host with the gate and no poller pauses every cycle (fail-closed) with `[PAUSED-USAGE] reading_missing` in the cron log. The log uses `poller_not_installed` when the reading file, `usage-pause.conf`, and `~/.ssh/hos_loopback` are all absent. This lasts until the host runs the §2a setup or sets `fail_mode=open`. There is no issue and no consumer-default-off switch.
- **Release notes and the upgrade checklist** (TD names the files) carry:
  - the setup step;
  - the fact that an upgrade without it stops autonomous work;
  - for API-key-billed consumers (who have no subscription `/usage`), the fact that `fail_mode=open` is their only route, and that it means **no usage protection**.
- **Open: P7** (A2-20 H-1). A consumer can run fail-open with no poller and no alerting. That is silent, and this amendment does not decide it.

### A2-16: Install path defined in one place (amends AD-2, AD-6 crontab; D14)

- **The single definition** of where the poller runs from is the **poller crontab line**. `--print-setup` generates it from the poller's own resolved path (`realpath` of argv[0]), and the runbook shows it as the one line to change.
- `hos-usage-poll` finds `usage_pause.py` relative to **its own resolved location** (`<dir>/lib/usage_pause.py`). The `hos-cron` gate finds it relative to `$_HOS_CRON_DIR`.
- No HOS code computes a clone path, calls `git rev-parse`, or assumes it runs inside a git work tree. A static test greps the poller and library for `git ` and `.git`.
- The `authorized_keys` line contains only the claude path, never an HOS path.
- When #1276 vendors `bin/` outside the tracked trees, exactly one crontab line changes (plus each project's `hos-cron` lines, which #1276 owns).
- **ESC-T1 / A1-7 cross-clone writable `bin/`** is an ACCEPTED near-term risk (D14). There is no separate issue. It is closed long-term by #1276 and v0.7.4 sandboxing.
- AD-2's version-skew rule stands: `schema=1`, and an unknown schema is unusable.

### A2-17: In-flight (P9, D2)

Restated for the TD as a single binding line: **this feature adds no in-flight bound of its own.** The gate decides only at cycle start (AD-7, D2), the existing cycle cap applies unchanged, and no #1944 code reads or sets `HOS_CRON_MAX_SECONDS`.

### A2-18: Slicing, tiers, and definition of done (supersedes AD-12 and A1-6's S4 wording)

> Amended by Amendment 4 A4-7: S2 coding starts only after the S1 trip test is recorded (H-7).
> Amended by Amendment 4 A4-2: S4 no longer edits `protected_surfaces.txt`. It is an ordinary MEDIUM slice with no human-merge requirement unless its diff touches `bin/` or another existing protected path.

| Slice | Contents | Tier | Merge |
|---|---|---|---|
| **S1: Poller read path** | `bin/hos-usage-poll` (poll, `remote-cmd`, `--print-setup`, `--check` incl. `--capture-fixture` and the every-`hos-cron`-copy item); `bin/lib/usage_pause.py` (JSON envelope parse, AD-4 regexes on `result`, three-threshold evaluate, settings incl. history keys, reading file I/O, cost/token fields); `last-raw`; fixtures (capture 2 envelope, synthetic JSON empty-session, AC-1 shape); T4.1b + T4.1 exemption; static tests (no unsetting, no `claude-auth.env`, no `suspend/`, no GitHub, no `git`, no `poll_*` read by `check`); `framework_consumer_files.txt`; CRON-SETUP §2a. **Exit:** AC-16 (real cron-fired success), AC-48 (forced-command line final), AC-49 (full envelope captured), AC-25 (recorded cost 0 / tokens 0) all recorded on faberix. | **HIGH** | HUMAN_REQUIRED (`bin/**`) |
| **S2: `hos-cron` gate** | A2-4 placement and sentinel; AD-7 rules with A2-3/A2-6; per-cycle log line; `cycle-usage-paused` audit; AC-34/AC-35 whole-cycle tests (stub `gh`, stub `claude`, zero calls). | **HIGH** | HUMAN_REQUIRED (`bin/**`, FR-49) |
| **S3: Metrics side path** | `render_prom` (A2-12) with re-render; history append + prune; `export`; isolation tests for all best-effort steps; `--check` `.prom` item; faberix root step runbook (symlink verification precondition, AD-10). | MEDIUM | HUMAN_REQUIRED (`bin/**`) |
| **S4: Monitoring worked example** | `contrib/monitoring/` dashboard JSON, dashboard provider, Grafana alert rules, contact point (placeholders), sync script + its README install steps, worked-example doc; `protected_surfaces.txt` += `contrib/monitoring/**` (+ CODEOWNERS regen); static tests (no literal thresholds AC-45, no secrets/endpoints AC-47, not installed by `hos_install.sh`, metric names match `render_prom`, YAML/JSON structure); `integration`-marked `promtool`/Grafana-lint tests skipped when the tool is absent. | **MEDIUM** (raised from LOW-MEDIUM: these alerts are now the only human signal) | HUMAN_REQUIRED (protected surface after this PR; the PR itself edits `protected_surfaces.txt`) |
| **S5: Live delivery (no code)** | Human applies the monitrix steps (sync user, clone, provisioning symlinks, env file secrets, textfile symlink, reload mechanism) and the faberix S3 root step. Recorded evidence: AC-42, AC-43 (email; SMS deferred to D-5), AC-50, then **AC-44, a real pause alert received by email**. | n/a | Recorded on #1944 |

- **Ordering.** S1 → S2. S1 → S3 → S4 → S5. S2 may merge and run as soon as S1 is deployed and `--check` is green, before S3-S5 (A2-1).
- **Definition of done.** #1944 closes only when S1-S4 are merged **and** S5's AC-44 run is recorded. S3/S4 landing without S2 never closes it, and neither does S2 without S5. A blocker on any slice keeps the issue open and escalates (AD-1).
- **Fail-open gate.** `fail_mode=open` on faberix is forbidden until S5's AC-43 and AC-44 are recorded. The runbook states this.

### A2-19: Escalations, updated

- **ESC-1:** resolved, option (a) (D10, A2-15).
- **ESC-2:** still human actions. The list is now: faberix S1 key/`authorized_keys`/`known_hosts`/crontab; the faberix S3 root step; and monitrix S5 (A2-14).
- **ESC-3:** removed (D3, D7). There is no dead-poller issue. The poll-stale and metrics-absent alerts replace it.
- **ESC-4:** resolved. The single-page dedup defect and the collapsed `_audit` at `hos-cron:2054` are filed as **#1946**. #1944 no longer has any dedup code, so it has no dependency on the fix.
- **ESC-T1:** accepted risk (D14, A2-16).
- **ESC-T3, TD-O-2:** removed (D7).

### A2-20: Human confirmation required (supersedes §5 and Amendment 1's §5 additions)

> Superseded by Amendment 4 A4-8. H-1, H-3 and H-4 are confirmed. H-2 is rejected and replaced. Only H-5 (informational) and H-6 (human actions) remain.

**Resolved by D1-D19**, so these are no longer open:
- §5.1 AS-1: superseded by D1, three triggers.
- §5.2 AS-2: confirmed, D2.
- §5.3 AS-3 + derived dead-poller issue: superseded by D3/D7, alerting.
- §5.4 Q11: confirmed, D4, minus issue filing.
- §5.5 Q12: D5, forced command without `restrict`.
- §5.6 Q5: D6, one reading file.
- §5.7 Q15: moot, D7.
- §5.8 FR-42/FR-44 interpretations: D8.
- §5.9 Grafana provisioning: D9.
- §5.10 ESC-1: D10 (a).
- A1 §12 FR-11 narrowing: D12.
- A1 §13 AC-25: D13.
- A1 §14 cross-clone `denyWrite`: D14, accepted.
- A1 §15 and §16: filed as #1946.

**Decided here as design-level (P-rulings), for the human's awareness. No action needed unless the human disagrees:**
- P1: `hos-cron` decides. The reading file holds the raw reading plus an informational `poll_*` view, which is a deliberate partial departure from the default (A2-3).
- P2: **overridden.** There is one audit event per paused cycle, not per transition, because a stateless gate cannot detect transitions (A2-5).
- P3: confirmed (A2-10).
- P4: exactly `from=` + `command=`. The residual is accepted, and the detector is the real read (A2-9).
- P5 (A2-8).
- P6 (A2-11).
- P8: host-specific path from `remote-cmd` (A2-9).
- P9 (A2-17).

**Still requiring the human:**
- **H-1 (P7, product boundary). A consumer running `fail_mode=open` with no poller and no alerting is silent.** Every cycle runs with no usage protection, and the only trace is a `[USAGE-UNCHECKED]` line in a cron log nobody reads. D10 allows `fail_mode=open` as the way past the no-poller pause, and D17b makes alerting optional, so nothing in the rulings prevents this. **Architect recommendation:** keep D10 as ruled. Do **not** narrow fail-open to exclude a missing reading file, because that would leave API-key-billed consumers, who have no `/usage`, permanently paused with no lever. Add two things: (i) one `cycle-usage-unchecked` audit event per fail-open cycle that runs without a fresh successful reading, so the consumer's audit trail records every unwatched cycle; and (ii) release-note and runbook text stating plainly that "fail-open without a poller = no usage protection". The alternative is to require a separate explicit acknowledgement key (e.g. `usage_check=unavailable_acknowledged`) before fail-open applies to a *missing* reading file. That is stricter, but it adds a setting D10 did not ask for. **Human chooses: recommendation, the alternative, or accept as-is.**
- **H-2 (new, governance): `contrib/monitoring/**` → protected surface** (A2-14). This is binding as a stricter control, but it extends the protected-surface list and so needs the human's approval on the S4 PR. Confirm that this is wanted rather than kept as normal-tier.
- **H-3 (new, operational obligation on monitrix): the alerting-reload mechanism** (A2-14). Grafana does not hot-reload alert rules or contact points, contrary to D9's premise, which holds for dashboards only. Options:
  - **recommended:** a root `systemd .path` unit that restarts `grafana-server` on a sentinel the sync job touches;
  - a Grafana service-account token for the admin reload API (a new credential on monitrix);
  - a manual restart after each alerting change.
- **H-4 (new, AC-44 procedure).** The definition-of-done run lowers `session_threshold` to force a real pause, which pauses all autonomous work on the host for one or more poll intervals. Confirm the procedure, or name another way to produce a real `pause_condition=1`.
- **H-5 (new, informational, safe direction).** Under D4, an invalid `history_days`/`history_max_mb` pauses all autonomous work, just as a bad threshold does. Recorded so it is not a surprise. A ruling is needed only if the human wants operational keys exempted, which would loosen D4.
- **H-6 (carried human actions, not confirmations):**
  - faberix S1: keypair, the `remote-cmd` `authorized_keys` line, `known_hosts`, the poller crontab line, `--check --capture-fixture`;
  - faberix S3: the `/var/lib/hos-usage` + symlink root step;
  - monitrix S5: the `hos-sync` user, clone, provisioning symlinks, Grafana env file with the Worker URL/secret, the textfile symlink, and the reload mechanism (H-3);
  - removing the leftover `/tmp/diagnose_claude_usage_tty.sh` crontab entry. It is not part of the design, and it appends forever to `/tmp/claude_usage_diag.log`.
- **Still open, not blocking (from requirements §6):** Q13 (reset text) stays as AD-3 had it, reading file only with no gauge. Q14 (runbook location) stays at CRON-SETUP §2a. Q18 is moot until D-2.

### A2-21: New verification gaps (extends §0.4; each blocks only the slice named)

> Amended by Amendment 4 A4-4: item 1's "follows symlinks in `provisioning/alerting/`" is moot, because the alerting files are now copied. Two gaps are added (A4-4).

1. Grafana 13.2.3 file provisioning, all S4/S5:
   - accepts rule-level `notification_settings.receiver` (A2-13);
   - accepts YAML anchors in alerting files (A2-13);
   - follows symlinks in `provisioning/alerting/` (A2-14);
   - interpolates env vars in contact-point settings (A2-13).
2. Whether monitrix's own node_exporter is scraped by its Prometheus, and whether its textfile collector follows symlinks. The sync gauges depend on both (S5).
3. The real JSON empty-session envelope shape (A2-7). The synthetic fixture stands in until one is captured. It is not blocking.
4. The full unfiltered envelope (D-4, AC-49): S1 exit.

### A2-22: Affected sign-offs

- **TD-1944 (DRAFT):** built against AD-3's per-role status file, AD-8's issue machinery, AD-5's `env -u` command, the two-threshold rule, plain-text parsing, and AD-12's slicing. **It must be revised by `technical-design` against this amendment before any approval.** No TD sign-off exists yet, so none is orphaned. Architect review of the revised TD restarts at round 1 for the amended sections.
- **Amendment 1 rulings:** A1-1 amended (A2-9), A1-2 stands (the in-process timeout; enum per A2-7), A1-3 confirmed (D12), A1-4 stands, A1-5 amended (A2-12), A1-6 amended (A2-18), and A1-7 accepted (D14). The "confirmed without change" AD-8 clarifications (exact-title dedup, `gh api --paginate`, close-pending memory) are **void** along with AD-8.
- **No code, test, or review sign-off exists for #1944.** The #1450 breaker code and its sign-offs remain untouched (FR-40, AC-17).

**Self-flag.** RISK: HIGH, unchanged. The gate fronts every autonomous cycle on every host. Visibility now depends on host monitoring rather than GitHub. CONFIDENCE: HIGH on A2-1 to A2-12 and A2-15 to A2-18. MEDIUM on A2-13/A2-14 until the A2-21 Grafana gaps are verified. BLAST RADIUS: as §Human Review, minus GitHub issue traffic, plus `~/.hos/usage-pause/history/`, `last-raw`, monitrix `/opt/hos-monitoring`, a `hos-sync` user, Grafana provisioning, and `protected_surfaces.txt`. Change classification: STRUCTURAL (human-ruled). H-1 to H-4 must clear before the slice each one touches ships.

## Amendment 3 (2026-10-03, architect, TD review round 2)

**Source.** Architect review round 2 of `TECHNICAL-DESIGN-1944-proactive-usage-pause.md` Revision 2 (§11.3 there, verdict APPROVED WITH CHANGES). Each item refines the wording of an A2 decision that the TD found unimplementable or internally inconsistent as written. **No human ruling (D1–D19) is changed. No product, cost, retention, topology, or operational consequence is added**, so no product-boundary checkpoint is needed. **Startup-gap check:** no code, test, or review sign-off exists for #1944, so nothing is orphaned. The TD is the only artifact affected, and round 2 applies these items to it.

- **A3-1 (refines A2-13, `HosClaudeUsageMetricsAbsent`).** The condition is `absent(hos_claude_usage_poll_timestamp_seconds)`, with no instance selector. A2-13's `{instance=~"$instance"}` cannot work: alert rules have no dashboard variables, and Grafana's provisioning env interpolation would expand `$instance` to an empty string. This is exact for one poller. With several pollers, each host needs its own rule (worked-example documentation).
- **A3-2 (refines A2-6, reason format).** In the gate's verdict line, the cron log line, and the audit event, every non-ASCII character in `<Name>` is folded to `?`. The fold happens once, in `usage_pause.py check`, before the 200-character cap. The reading file keeps the raw name. *Reason:* the gate matches its verdict under `LC_ALL=C`, so a non-ASCII byte would otherwise turn a correct pause into `check_error`.
- **A3-3 (adds to A2-5, `cycle-usage-paused` fields).** Adds `project` and `cycle_id`. Each element is still one `key=value` per argv element, and `role` is passed explicitly.
- **A3-4 (resolves an A2-11 conflict, pruning).** When today's history file alone exceeds `history_max_mb`, pruning stops. Today's file is kept, a WARN is logged, and `history_write_ok` stays 1. "Today's file is never deleted" takes precedence over the size cap.
- **A3-5 (confirms A2-5; TD-O-18).** Paused cycles keep writing one `cycle-usage-paused` record each. They do **not** sync on the paused path, which would break A2-4's zero-network rule. They also do not deduplicate against earlier audit records, which would reintroduce the transition state that D6 removed. The records are delayed, not lost: the first running cycle's `_sync_audit_logs` pushes them. Volume is bounded by cron cadence. The residual is the existing #1803 sync gap, and #1803 owns the fix.

## Amendment 4 (2026-10-03, human rulings H-1 to H-4 and H-7)

**Source.** Human rulings from the interactive session of 2026-10-03, cited "human ruling, interactive session 2026-10-03, H-n":
- H-1 confirmed as recommended.
- H-2 rejected and replaced by a test-based control.
- H-3 confirmed.
- H-4 confirmed.
- H-7 is new: an S1 trip test gates S2.

The rulings are authoritative. Where this amendment conflicts with earlier text, **it governs**. Each superseded section carries an inline pointer, and earlier text is not rewritten.

**Startup-gap check.** Every item lands before any code exists. The only artifact built against the superseded text is `TECHNICAL-DESIGN-1944-proactive-usage-pause.md`, which is updated in the same change and tagged "Human rulings H-1..H-4, H-7". Affected sign-offs are listed in A4-10.

**Product-boundary check.** The items with product, operational or governance consequences are:
- A4-1: consumer visibility;
- A4-2: governance;
- A4-4: a monitrix operational obligation;
- A4-6: autonomous downtime during the definition-of-done run;
- A4-7: build order.

Each is a human ruling, so the boundary is cleared. A4-3, A4-5 and A4-9 implement those rulings and add no new consequence beyond the one the human ruled on, with one exception. A4-5 adds a 13th alert rule and one extra gauge file on monitrix, and the reason for both is given there. They are additive, they raise the alert count by one, and they create no new credential, service exposure or human gate.

### A4-1: Fail-open with no valid reading: one `cycle-usage-unchecked` audit event per cycle, plus release-note text (human ruling, interactive session 2026-10-03, H-1; resolves A2-15 "Open: P7"; amends A2-5)

- **Event.** Every gated cycle whose verdict is `class=failopen` emits exactly one `_audit cycle-usage-unchecked` event. That verdict means `fail_mode=open` and the cycle runs without a usable successful reading: the read failed, or the reading is missing, stale, truncated, unreadable, of unknown schema, or future-dated.
  - The event has the same argv as `cycle-usage-paused` (A2-5 + A3-3), one `key=value` per argument, in this order: `role`, `project`, `cycle_id`, `reason`, `session_pct`, `weekly_all_pct`, `reading_age_s`, `fail_mode`, `settings`.
  - A running cycle with `class=ok` emits no usage event. A2-5's "no event on a running cycle" now holds only for `class=ok`.
- **No block and no issue** (H-1). D10 stands: `fail_mode=open` still runs every cycle. Because the event is written before audit-log sync (A2-4 placement) on a cycle that goes on to run, that cycle's own `_sync_audit_logs` pushes it. The A3-5 delay does not apply.
- **Release-note text (exact, binding).** The sentence **"fail_mode=open without a running poller means no quota protection"** appears verbatim in three places, and a static test asserts it in each:
  - the release notes' Upgrade notes (`docs/releases/v0.7.0.md`, TD-O-19 retarget rule);
  - the upgrade checklist §H;
  - the runbook (CRON-SETUP §2a.0 and §2a.9).
- **No decision reads the event** (ADR-1604 AD-4 rule).

### A4-2: `contrib/monitoring/**` is NOT protected surface; S4 is an ordinary MEDIUM slice (human ruling, interactive session 2026-10-03, H-2; withdraws A2-14's protected-surface bullet; amends A2-18 S4 row)

- **Withdrawn:** adding `contrib/monitoring/**` to `scripts/framework/protected_surfaces.txt`, along with the matching `docs/AGENT-IDENTITY.md` §9.0 entry and the CODEOWNERS regeneration. **No new entry of any kind** is added to `protected_surfaces.txt` by #1944.
- **Human rationale (recorded):** protected surfaces are already too broad (#1935, "too broad (directory-level)"), and human review must be restricted to what really matters.
- **The threat model still stands. Only its control changes.** A2-14 said the alert rules are the human's only signal of a pause, a broken check, or a non-zero read cost, so the alerts could be removed by the agent they watch. That remains true. The control is no longer a human merge gate. It is now A4-3's guard test, which makes removing a required alert a visible test edit, plus the overseer's normal risk review of that edit.
  - **Residual, accepted by H-2:** a single PR that edits both the rules file and the guard test is not mechanically blocked. It is review-visible.
- **S4 tier and merge:** MEDIUM, with an infra-reviewer pass and no human-merge requirement. The one exception: if S4's diff touches `bin/` or any other path already in `protected_surfaces.txt`, the existing CODEOWNERS rule applies unchanged. The decision-path code under `bin/` keeps its existing protection (AF-2, FR-49).

### A4-3: Required-alert guard test in the PR-required suite (human ruling, interactive session 2026-10-03, H-2 replacement control; amends A2-13)

- **File:** `tests/framework/test_monitoring_required_alerts.py`.
  - It is collected by `scripts/framework/run_tests_inner_loop.sh`, which `.github/workflows/tests.yml` runs, so it is PR-required.
  - It carries **no** `slow`, `integration`, `skip` or `xfail` marker.
  - A missing rules or contact-point file is a **failure, not a skip**.
  - PyYAML is pinned in `scripts/oversight/requirements.txt`, so an import failure is an error, not a skip.
  - The module docstring cites H-2 and says that removing or weakening an entry is a change to the human's alerting coverage and must be stated in the PR.
- **The required set is a literal inside the test file, never imported from `contrib/`.** It is keyed by stable rule UID and maps each UID to one metric anchor. It is reconciled against the 13 rules (A2-13 + A4-5). Every rule that is the human's **only** signal for its failure mode is required:

| UID | Human's only signal for | Metric anchor |
|---|---|---|
| `hos-pause-condition` | a pause | `hos_claude_usage_pause_condition` |
| `hos-read-failing` | read failed | `hos_claude_usage_read_ok` |
| `hos-poll-stale` | reading stale / poller dead | `hos_claude_usage_poll_timestamp_seconds` |
| `hos-metrics-absent` | metrics absent (exporter purged, symlink broken) | `hos_claude_usage_poll_timestamp_seconds` |
| `hos-settings-invalid` | settings invalid | `hos_claude_usage_settings_valid` |
| `hos-read-cost-nonzero` | non-zero read cost | `hos_claude_usage_read_cost_usd` |
| `hos-read-tokens-nonzero` | non-zero read tokens (separate, AC-41) | `hos_claude_usage_read_tokens` |
| `hos-read-cost-unknown` | the FR-9 cost check silently disabled by a CLI that drops the fields (A2-8) | `hos_claude_usage_read_cost_usd` |
| `hos-history-write-failing` | `history_write_ok=0` | `hos_claude_usage_history_write_ok` |
| `hos-monitoring-sync-stale` | dashboard sync stale | `hos_monitoring_sync_ok` |
| `hos-monitoring-alerting-reload-failed` | repo alert rules not live on monitrix (A4-5) | `hos_monitoring_alerting_reload_ok` |

  These cover the eight items the human listed. Three rules are added because each is likewise the only signal for its case: `hos-read-cost-unknown`, the split of cost and tokens into two rules (AC-41), and A4-5's reload rule.
  - **Not required, with reasons.**
    - `hos-textfile-error` is redundant for HOS. A malformed `hos_claude_usage.prom` makes node_exporter drop that file's series, so `hos-metrics-absent` fires.
    - `hos-weekly-time-to-threshold` is an optional early warning. `hos-pause-condition` is the signal.
    - Both stay in the rules file.
- **Assertions:**
  1. Each required UID exists exactly once.
  2. Each required rule has `isPaused: false`, `notification_settings.receiver == "hos"`, and `condition == "C"`. Pausing or re-routing an alert counts as removing it.
  3. Each required rule's refId `A` expression contains its metric anchor, so swapping in a different query is caught. Exact expressions remain pinned by `test_rule_exprs_exact`.
  4. Contact point `hos` exists with **both** integrations:
     - `hos-email-webhook`: `type: webhook`, `url: ${HOS_ALERT_EMAIL_WEBHOOK_URL}`, `authorization_scheme: Bearer`;
     - `hos-sms-webhook`: `type: webhook`, `url: ${HOS_ALERT_SMS_WEBHOOK_URL}`.
- **Why one dedicated small file:** a diff that removes a UID is then unmistakable to the overseer's risk review. Spread across `test_contrib_monitoring.py`, it would be easy to miss.

### A4-4: Alerting reload: a root systemd path unit watching the provisioned alerting files (human ruling, interactive session 2026-10-03, H-3; supersedes A2-14's sentinel recommendation and its alerting symlinks)

- **Units** (installed **by copy** into `/etc/systemd/system/` by the human; never symlinked into the clone):
  - `hos-grafana-alerting-reload.path`: two `PathChanged=` lines, one for each provisioned alerting source file in the clone (`/opt/hos-monitoring/contrib/monitoring/grafana/provisioning/alerting/hos-rules.yaml` and `…/hos-contact-point.yaml`), plus `Unit=hos-grafana-alerting-reload.service` and `WantedBy=multi-user.target`.
  - **`PathChanged=`, not `PathModified=`.** `PathChanged` fires when a writer *closes* the file, and on create, move or delete. `git pull` replaces a changed file (unlink, create, write, close), so each changed file triggers exactly once and never mid-write. `PathModified` would also fire on each `write(2)`.
  - **Nothing fires when nothing changed.** Dashboard-only pulls do not touch these files.
  - `hos-grafana-alerting-reload.service`: `Type=oneshot`, `ExecStart=/usr/local/sbin/hos-grafana-alerting-reload`, `TimeoutStartSec=` a named value, and `StartLimitIntervalSec=0` in `[Unit]`.
    - **Why the start limit is disabled:** if systemd's start limit were hit, the path unit would enter `failed` and silently stop watching.
    - Flapping cannot occur from the sync job. Its lock and 5-minute cadence bound triggers to one burst per pull.
- **Reload script** `contrib/monitoring/monitrix/hos-grafana-alerting-reload` (bash; the human installs it by copy to `/usr/local/sbin/`, root 0755, outside the clone). A pull can therefore never change code that runs as root. It runs these steps in order:
  1. **Settle** for a named number of seconds (debounce). The two files of one pull are written within milliseconds, and a trigger that arrives while the oneshot is activating is merged into the running job by systemd.
  2. **Stage.** Read each source file **as `hos-sync`** (`runuser -u hos-sync -- cat --`), capped at a named size, into a root-owned staging directory. Reading as the unprivileged clone owner means a symlink committed into the repo can never make root copy a file `hos-sync` could not already read.
  3. **No-op if unchanged.** If every staged file byte-equals the installed copy, do not restart; record success. This makes the script idempotent against spurious triggers.
  4. **Back up** the installed copies.
  5. **Install** each file with `install -m 0640 -o root -g grafana` into `/etc/grafana/provisioning/alerting/` through a temp name that Grafana ignores, then rename it into place.
  6. **Restart** grafana-server with `systemctl restart grafana-server.service`, then poll `http://127.0.0.1:3000/api/health` until a named timeout passes.
  7. **On health failure, roll back.** Restore the backups, restart again, and record failure.
  8. **Write gauges** (A4-5) atomically.
- **Restart during an alert evaluation is acceptable (binding analysis).** Restarts happen only when the alerting files change, which means a merged PR touching them, so they are rare.
  1. An evaluation killed mid-flight makes no state transition. The next evaluation runs within one group interval after start.
  2. Grafana unified alerting persists alert-instance state and the notification log in its database and restores them at startup. Pending `for:` timers and firing state carry over, so the restart produces no duplicate. If 13.2.3 does not restore them (verification gap V-R1), the worst case is that a firing alert re-fires after its `for`, which is 0 s for the critical pause, settings and cost rules. The result is one duplicate email or a delay of one `for` per restart. Both fail in the safe direction, and neither suppresses an alert.
  3. A notification in flight when Grafana stops may be lost. The alert is still firing and is re-sent at the repeat interval. Residual: a delay of at most one repeat interval, only for an alert that fires inside the restart window.
  4. Downtime is roughly 10–60 s. A pause that starts in that window is evaluated at the first evaluation after start.
  5. **A bad pushed file cannot leave Grafana down.** Grafana refuses to start on an invalid alerting provisioning file. The health check catches that and rolls back to the last installed set, and `hos_monitoring_alerting_reload_ok=0` fires A4-5's rule through the restored Grafana.
     - Residual: if Grafana fails even with the restored set, the fault is not the pushed change, and monitrix's own Grafana liveness is outside HOS. The worked example lists it as a known fragility.
- **Copy, not symlink.** The alerting provisioning files are copies made by the reload script. This moots A2-21 item 1's alerting symlink-follow gap. The dashboard provider symlink is unchanged.
- **The sync job no longer writes a reload sentinel.** `HOS_SYNC_RELOAD_SENTINEL` is removed. When alerting files change, the sync job only logs that the path unit will restart grafana.
- **New verification gaps (block S5 only):**
  - V-R1: alert-instance state and the notification log are restored across a restart in 13.2.3;
  - V-R2: `PathChanged=` on the clone paths fires on a real `git pull` on monitrix. Evidence: `journalctl -u hos-grafana-alerting-reload.service` in the AC-50 record.
  - V-R3: Grafana 13.2.3 fails to start, or fails `/api/health`, on an invalid alerting provisioning file. The rollback depends on this.
- **Runbook.** The worked-example runbook (`contrib/monitoring/README.md` and `docs/MONITORING-WORKED-EXAMPLE.md`) documents this as a **human-run install step**:
  - install the script and both units by copy;
  - `systemctl daemon-reload`;
  - `systemctl enable --now hos-grafana-alerting-reload.path`;
  - one initial `systemctl start hos-grafana-alerting-reload.service`, which performs the first copy and restart;
  - verify with `systemctl status` and `journalctl`.

### A4-5: Reload-health gauges and a 13th rule (follows from A4-4; additive)

- The reload script writes `/var/lib/hos-grafana-reload/hos_grafana_alerting_reload.prom`, using AD-10's owned-dir + symlink pattern into monitrix's textfile directory (one more root symlink, done in the same S5 step as the sync gauges). It holds two gauges:
  - `hos_monitoring_alerting_reload_ok`: 1/0, the result of the last attempt;
  - `hos_monitoring_alerting_reload_last_success_timestamp_seconds`: 0 if none.
- **Rule 13** `hos-monitoring-alerting-reload-failed` / `HosMonitoringAlertingReloadFailed`: `hos_monitoring_alerting_reload_ok == bool 0`, `for` immediate, noData OK, severity critical.
  - **Reason:** without it, a pushed alert change that Grafana rejected would leave `deployed_commit` advancing while monitrix runs the old rules, and no signal would say so.
  - It is in A4-3's required set.

### A4-6: AC-44 live test procedure (human ruling, interactive session 2026-10-03, H-4; confirms A2-1)

The AC-44 procedure is confirmed as specified, and it remains S5's definition of done:
1. Temporarily lower one threshold in `usage-pause.conf` below the current live value of its limit. Equal also trips, since the comparison is `>=`. Never use a value below 1.
2. Observe the pause and the email (and the SMS once D-5 exists).
3. Record the run.
4. Restore the threshold.

**All autonomous work pauses for about 10–15 minutes:**
- `hos-cron` reads the current conf every cycle (AC-23), so the next cycle start pauses at once;
- the alert needs one poll (at most 5 minutes) plus one evaluation;
- after restore, cycles resume at the next cycle start, and the alert resolves at the next poll.

**Running cycles finish first** (D2; there is no mid-cycle kill).

### A4-7: S1 trip test gates S2; build order; build mode (human ruling, interactive session 2026-10-03, H-7; amends A2-18)

- **Order:** S1 is built **and deployed on faberix**, its exit records (AC-16, AC-48, AC-49, AC-25) are posted, **then** the S1 trip test runs and is recorded, and **only then is S2 built**. The gate is on starting S2 coding, not just on merging it.
- **Trip test (human-run on faberix; no autonomous work pauses, because no gate exists yet):**
  1. Back up `usage-pause.conf`, or note that it is absent.
  2. Set one threshold below the current live value of its limit (≥ 1). If `session_pct` is 0, use `weekly_threshold`.
  3. After the next cron-fired poll, the reading file shows:
     - `poll_pause_condition=1`;
     - `poll_pause_reason` naming that limit, its value, and the lowered threshold in A2-6 format (e.g. `session 7% >= 5`);
     - `poll_settings_status=valid`.
  4. `--check` reports the same condition and reason. This needs one new S1 output line, described below.
  5. Restore the conf, or delete it if it was absent.
  6. The next poll shows `poll_pause_condition=0`.
  7. Record all of it on #1944.
- **New S1 `--check` line (needed for step 4).** After item 7's real read, `--check` prints `INFO 10 pause_condition=<0|1> reason=<poll_pause_reason-format text>`. It evaluates that read against the current settings with the same function the poller uses for `poll_pause_condition`. It is informational and never fails the check: a pause condition is not a setup fault. Under invalid settings it prints `pause_condition=1 reason=settings_invalid:<key>`.
- **S2 gates, in full:**
  - S1 merged and deployed;
  - S1 exit records posted;
  - **trip-test record posted (H-7)**;
  - H-1 is no longer a gate (ruled).
- **The H-4 end-to-end test (A4-6) remains S5's definition of done.** The trip test does not replace it.
- **Build mode.** #1944 is built in the human's interactive worker session, not by autonomous pickup, and `needs-ai` is deliberately left off. Review is unchanged:
  - S1, S2 and S3 are HUMAN_REQUIRED (`bin/**`);
  - S4 is overseer-mergeable at MEDIUM (A4-2);
  - S5 is a record.

### A4-8: Human confirmation required (supersedes A2-20's open list)

**Resolved (human ruling, interactive session 2026-10-03):**
- H-1: confirmed (A4-1).
- H-2: rejected, replaced by A4-3 (A4-2).
- H-3: confirmed (A4-4).
- H-4: confirmed (A4-6).
- H-7: new, applied (A4-7).

**Remaining (none blocks design or coding):**
- **H-5 (informational, safe direction).** Under D4, an invalid `history_days`/`history_max_mb` pauses all autonomous work. A ruling is needed only if the human wants these keys exempted, which would loosen D4.
- **H-6 (human actions, not confirmations):**
  - faberix S1: keypair, `authorized_keys` line, `known_hosts`, poller crontab line, `--check --capture-fixture`;
  - faberix, after S1 exit: **the H-7 trip test**;
  - faberix S3: `/var/lib/hos-usage` + symlink;
  - monitrix S5: the `hos-sync` user, clone, sync script, dashboard provider symlink, Grafana env file, sync and reload textfile symlinks, **and install of the reload script plus both units (A4-4)**;
  - the AC-44 run (A4-6);
  - removing the leftover `/tmp/diagnose_claude_usage_tty.sh` crontab entry.
- **Dependencies, not confirmations:** D-5 (SMS provider) defers only the SMS half of AC-43/AC-44. Q13, Q14 and Q18 are unchanged and not blocking.

### A4-9: Requirements changes for pm-agent (architect does not edit REQUIREMENTS)

1. **FR-22 (H-1):** append "Each fail-open cycle that runs without a usable successful reading writes one `cycle-usage-unchecked` audit event (fields: role, project, cycle_id, reason, session_pct, weekly_all_pct, reading_age_s, fail_mode, settings; one `key=value` per argument). No block and no issue."
2. **FR-65 (H-1):** append "The release notes, the upgrade checklist, and the runbook contain the sentence: 'fail_mode=open without a running poller means no quota protection'."
3. **AC-9 (H-1):** "→ no pause, no GitHub call, **and exactly one `cycle-usage-unchecked` audit event**."
4. **AC-46 (H-1):** after "With `fail_mode=open`, cycles run" insert ", each writing one `cycle-usage-unchecked` audit event naming the project and cycle_id; the release notes contain 'fail_mode=open without a running poller means no quota protection'".
5. **AC-47 (H-2):** replace its first sentence with "Every alert in FR-62 exists in `contrib/monitoring/`, is enabled, and routes to the single contact point, which has both an email and an SMS integration. A test in the PR-required suite (`scripts/framework/run_tests_inner_loop.sh`) asserts each required alert by stable rule UID, and asserts both integrations."
6. **FR-62 (H-2/H-3):** append to the minimum list "read cost or tokens unknown on a successful read; alerting reload failed on the monitoring host".
7. **New governance FR, next to FR-49 (H-2):** "`contrib/monitoring/**` is not protected surface. Removing or weakening a required alert is guarded by the required-alert test (AC-47), and is visible to normal PR risk review."
8. **FR-58 (H-3; corrects a false premise A2-14 already identified):** replace "Grafana reloads provisioned files on its own" with "Grafana reloads provisioned dashboards on its own. Alert-rule and contact-point changes are applied by a root systemd path unit on the monitoring host, which restarts grafana-server when the provisioned alerting files change, with health check and rollback."
9. **New AC (H-7; pm-agent assigns the number, next free after AC-52):** "**S1 trip test (recorded before S2 is built).** On faberix, with S1 deployed and no gate installed, a threshold in `usage-pause.conf` is temporarily set below the current live value of its limit. The next cron-fired poll writes `poll_pause_condition=1` to the reading file, with `poll_pause_reason` naming that limit, its value, and the lowered threshold. `bin/hos-usage-poll --check` reports `pause_condition=1` with the same reason. After the threshold is restored, the next poll writes `poll_pause_condition=0`. The run is recorded on #1944, and S2 is not built until it is."
10. **AC-44 (H-4, optional clarity):** append "(procedure: lower one threshold below current live usage, observe the pause and the email, record, restore; all autonomous work pauses for about 10–15 minutes and running cycles finish first)".

Items 1–4 and 9 should land before the S2 PR is reviewed. Items 5–8 should land before the S4 PR is reviewed. None blocks coding.

### A4-10: Affected sign-offs

- **TD-1944** carries Revision 2 plus Architect round 2 (APPROVED WITH CHANGES). Round 2 stated: "no further architect round is needed unless the human's H-1 to H-4 answers change a section."
  - H-1 and H-4 change only text that round 2 had already specified conditionally, and that approval stands.
  - H-2, H-3 and H-7 change §6, §7, §8 and §9 (S4/S5 design, slicing, test plan, and the new S1 `--check` line). Those sections were authored here by the architect from the rulings.
  - **To keep author and critic separate, `technical-design` should do one consistency pass over the sections tagged "Human rulings H-1..H-4, H-7"** before S4 coding (and before S1's PR, for the small `--check` INFO 10 addition). S1's other sections and S2 are unaffected.
- **No code, test, or review sign-off exists for #1944.** Nothing is orphaned. The #1450 breaker and its sign-offs remain untouched.

**Self-flag.** RISK: HIGH, unchanged overall. A4-2 lowers S4's merge gate by human ruling and puts a test guard in its place. A4-4 adds root automation on monitrix, which is constrained to data copies read as `hos-sync`, has health-checked rollback, and runs no repo code as root. CONFIDENCE: HIGH on A4-1, A4-2, A4-3, A4-6, A4-7 and A4-9. MEDIUM-HIGH on A4-4 until V-R1/V-R2 are verified on monitrix. BLAST RADIUS: same as A2, minus `protected_surfaces.txt`, AGENT-IDENTITY and CODEOWNERS; plus `/usr/local/sbin/hos-grafana-alerting-reload`, two systemd units, `/var/lib/hos-grafana-reload`, and one textfile symlink on monitrix. Change classification: STRUCTURAL (human-ruled).
