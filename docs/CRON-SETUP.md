# Autonomous Cron Setup — Worker & Overseer

How to run the HOS worker and overseer as unattended cron agents on the user's
Claude subscription. Works on **macOS** (development) and **Ubuntu/Linux** (unattended
ops). Platform differences are called out inline.

The launcher is `bin/hos-cron`. One wrapper drives every role and project; it
pins its own environment, so the crontab lines stay minimal.

---

## 1. Prerequisites (once per machine)

Run the machine bootstrap, which installs Python, gh, the agent CLIs, and the
`timeout` binary used to bound each cron fire:

```bash
./bootstrap/hos_bootstrap.sh
```

Then confirm the `claude` CLI is installed and on your PATH:

```bash
command -v claude    # e.g. ~/.local/bin/claude
```

**`timeout` binary (per-fire wall-clock cap):**

- **Ubuntu/Linux:** `timeout` ships with coreutils in the base system — nothing to do.
- **macOS:** needs `gtimeout` from coreutils. The bootstrap installs it; or manually:
  ```bash
  brew install coreutils
  ```
  Without it, sessions run unbounded (the wrapper warns but still runs).

---

## 2. Claude subscription auth (the critical step)

Headless `claude --print` runs on your **Claude subscription** only when given an
explicit OAuth token. Without it, cron falls through to pay-per-token API billing
and fails with *"Credit balance is too low."* (See `DECISIONS.md`, 2026-06-21.)

**Generate a long-lived token** (needs a browser — do this interactively):

```bash
claude setup-token
```

Copy the printed `sk-ant-oat01-…` token into a `0600` env file:

```bash
install -m 600 /dev/null ~/.config/hos/claude-auth.env
# add exactly this line (no spaces, no quotes), then save:
#   CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
vi ~/.config/hos/claude-auth.env
```

Verify without printing the token:

```bash
awk -F= '/CLAUDE_CODE_OAUTH_TOKEN/{print length($2)" chars"}' ~/.config/hos/claude-auth.env
grep -c ' ' ~/.config/hos/claude-auth.env    # must be 0
```

The token is valid ~1 year and does **not** auto-refresh. When it expires, cron
logs a clear "refresh the token" hint; re-run `claude setup-token`.

> Override the path with `HOS_CLAUDE_AUTH_ENV` if you keep it elsewhere. One token
> file per machine is shared across all projects.

---

## 2a. Usage-pause poller (SSH loopback)

Setup for the proactive usage pause (#1944). One poller per host. The cycle-start
gate that consumes its reading ships in a later step; until it is installed, this
poller only records readings. Later steps add sections 2a.0, 2a.8 and 2a.11 and
`--check` item 9; they are absent here, so the numbering has gaps. Work through
2a.1a to 2a.7 in order: `--check` ends `RESULT: FAIL` until every step is done, and
that is expected part-way through.

### 2a.1 What it is

One poller per host runs every 5 minutes. It reads `/usage` under your **personal
login** over SSH loopback and never touches `claude-auth.env`. Every worker and
overseer cycle on the host (all projects, both roles) pauses at cycle start when
**session, weekly (all models), or any weekly per-model** usage is `>=` its
threshold (default 90 each), or when the reading is missing, stale or failed
(fail-closed). It resumes on its own. Interactive sessions are never paused. This
is separate from `hos-suspend`.

### 2a.1a State directory (do this before anything else)

The crontab redirect in 2a.6 writes `poll.last.log` into this directory, and the
shell fails before the poller starts if it does not exist. Create it first
(block 1 of `--print-setup`):

```bash
mkdir -p ~/.hos/usage-pause && chmod 700 ~/.hos/usage-pause
```

Leave `HOS_STATE_DIR` unset in the crontab environment. If you must set it, the
redirect's parent directory has to be the same `$HOS_STATE_DIR/usage-pause`, and the
`hos-cron` crontab lines must carry the same value; otherwise the gate looks in a
different place from the poller. `--check` item 12 verifies the directory (and
honours `HOS_STATE_DIR` when it is set in your shell).

### 2a.2 Key

Generate the loopback key (block 2 of `bin/hos-usage-poll --print-setup`):

```bash
ssh-keygen -t ed25519 -N '' -C hos-loopback -f ~/.ssh/hos_loopback
```

### 2a.3 authorized_keys

Append the one line printed by `bin/hos-usage-poll --print-setup` (block 3) to
`~/.ssh/authorized_keys`. It has exactly two options, `from=` and `command=`:

```text
from="127.0.0.1,::1",command="<abs claude> -p /usage --output-format json" ssh-ed25519 <blob> hos-loopback
```

The line is **not final until a real `--check` read returns real percentages**.
If `claude` moves, regenerate the line (`bin/hos-usage-poll remote-cmd`); `--check`
item 2 detects the drift. Do not add `restrict` and do not add environment
unsetting: both were ruled fragile.

### 2a.4 known_hosts

Seed it from the on-disk host key (block 4 of `--print-setup`). Do not use
`ssh-keyscan` and do not accept-new.

### 2a.5 Settings (optional)

`~/.config/hos/usage-pause.conf`, one `key=value` per line, `#` comment lines
allowed. The file is parsed, never sourced. Missing = defaults; any invalid value,
unknown key or duplicate key (including the history keys) pauses every cycle
until fixed, regardless of `fail_mode`; the cron log line names the key.

| Key | Default | Valid |
|---|---|---|
| `session_threshold` | 90 | integer 1-100 |
| `weekly_threshold` | 90 | integer 1-100 |
| `weekly_model_threshold` | 90 | integer 1-100 |
| `fail_mode` | `closed` | exactly `closed` or `open` |
| `poll_interval_seconds` | 300 | integer multiple of 60, 60-3600 |
| `staleness_seconds` | 900 | integer greater than `poll_interval_seconds + read_timeout_seconds + 10`, at most 7200 |
| `read_timeout_seconds` | 60 | integer 5 to `poll_interval_seconds - 30` |
| `history_days` | 90 | integer 1-3650 |
| `history_max_mb` | 100 | integer 1-10240 |
| `claude_bin` | resolved from `PATH` | absolute path, no `.` or `..` segment, not ending in `/` |

### 2a.6 Crontab: the one install-path line

```cron
*/5 * * * *  $HOME/<path-to>/bin/hos-usage-poll > $HOME/.hos/usage-pause/poll.last.log 2>&1
```

This line is the single place the poller's install path is defined. When the path
changes (for example, #1276), change this line. Use `>`, not `>>`. One entry per
host. `--print-setup` prints it with your paths filled in.

### 2a.7 Verify

First run `bin/hos-usage-poll --check --capture-fixture ~/hos-usage-envelope-<YYYYMMDD>.json`
(keep the file and attach it to #1944), then `bin/hos-usage-poll --check`, which
must end `RESULT: PASS`. `--check` item 8 checks every scheduled `hos-cron` copy
for the gate: **item 8 must be green after every upgrade of any project on the
host.** Item 10 is informational: it shows whether the current read would pause
under the current settings. Item 11 shows the reading the cron-fired poller has
actually written (age, outcome, reason, `consecutive_failures`) and FAILs when the
crontab check passed but there is no reading, or the reading is older than
`staleness_seconds`. Item 12 checks the state directory exists, is writable and is
mode 0700. `--capture-fixture` refuses a target whose parent directory is not yours
or is group- or world-writable.

### 2a.9 Fail-open

`fail_mode=open` is safe **only once alerting is live** (`contrib/monitoring/`,
AC-43 and AC-44 recorded). On faberix it is forbidden until the live-delivery
record exists. fail_mode=open without a running poller means no quota protection.

### 2a.10 Reading the state

- `cat ~/.hos/usage-pause/reading`: raw values; `poll_*` keys are the poller's own view.
- `cat ~/.hos/usage-pause/last-raw`: the latest raw output, for parse-failure debugging.
- `cat ~/.hos/usage-pause/poll.last.log`: the last poll's output.

No GitHub issue is ever filed by this feature.

**Reading the keys.**
- `consecutive_failures`: failed polls in a row; `0` after a success.
- `last_success_epoch`: Unix time of the last successful poll; absent means it has never succeeded.
- `--check` item 11 prints the reading's age, outcome, reason and `consecutive_failures`.
- If a poll finds another poll holding the lock it exits without changing the reading and writes `another poll holds the lock (pid N, age Ns)` to `poll.last.log`. A lock whose PID is dead, or that is older than the read limit plus 60 s, is reclaimed (`diagnostics=lock_stale_reclaimed`).

**Reason to action.** `reason=` in the reading, and `FAILED reason=` in `--check` item 7:

| Reason | Meaning | What to do |
|---|---|---|
| `ssh_failed` | ssh exited 255, or the key file is missing | `--check` items 1 to 3; `cat ~/.hos/usage-pause/last-raw` for the ssh error (host key, key mode, `authorized_keys`) |
| `timeout` | the read did not finish within `read_timeout_seconds` | run `claude` by hand; check load; raise `read_timeout_seconds` within its bounds |
| `spawn_failed` | `ssh` could not be started | check `ssh` is installed and on the poller's `PATH` |
| `envelope_invalid` | stdout was not the expected JSON envelope | `cat last-raw`; usually the forced command is missing or wrong: `--check` item 2, regenerate the line |
| `empty_session` | the read succeeded but showed no usage | the forced command may be running under an API-key or expired login: re-run `claude` login as the key's user |
| `missing_session` / `missing_weekly` | one of the two required limits was absent | `cat last-raw`: the `/usage` text changed shape |
| `unparseable` | no recognisable usage text | `cat last-raw`: the `/usage` text changed shape |
| `crashed` | the poller itself failed; `detail` names the step | read `poll.last.log`; run `python3 bin/lib/usage_pause.py poll-params` by hand |

---

## 3. Project registry

`bin/hos-cron` resolves each project's repo paths and config dir from a
machine-local registry. Create `~/.config/hos/projects.conf`:

```ini
# <project>_<key>=<value>   — keys: config_dir, worker_root, overseer_root, target_release, max_seconds
hos_config_dir=/home/scott/Code/HumanOversightSystem/.config/hos
hos_worker_root=/home/scott/Code/HumanOversightSystem/Worker
hos_overseer_root=/home/scott/Code/HumanOversightSystem/Overseer
hos_target_release=v0.4.2

cps_config_dir=/home/scott/Code/CondoParkShare/.config/hos
cps_worker_root=/home/scott/Code/CondoParkShare/Worker
cps_overseer_root=/home/scott/Code/CondoParkShare/Overseer
cps_target_release=v1.0.0
```

Use real absolute paths — this file is not shell-sourced, so `$HOME` is not
expanded; write the full path. `chmod 600` it.

### Active target release (`target_release`)

The `<project>_target_release` key tells the worker which GitHub milestone is
currently active. `bin/hos-cron` resolves the milestone **number** from the
milestone **title** via the REST API, so the number is never stored or duplicated.

**To roll to the next release:** change the one `target_release` line in
`projects.conf` — no prompt edits required.

```ini
# Before (working on v0.4.2):
hos_target_release=v0.4.2

# After rolling to v0.4.3:
hos_target_release=v0.4.3
```

The launcher will look up `v0.4.3`'s milestone number at the next cron fire and
substitute it into the worker prompt automatically. A `FATAL: milestone not found`
error means either the release title doesn't match a GitHub milestone title exactly,
or the milestone hasn't been created yet.

**Override without changing the file** (useful for testing):
```bash
HOS_TARGET_RELEASE=v0.4.3 bin/hos-cron --role worker --project hos
```

Set `HOS_TARGET_MILESTONE_NUMBER` alongside to skip the REST lookup entirely.

Each project also needs its GitHub App credentials at `<config_dir>/apps.env`
(see `docs/MACHINE-ACCOUNTS-SETUP.md`).

---

## 4. Crontab entries

The wrapper pins its own PATH, so **no `PATH=` prefix is required**. Schedule
each role; offset projects so they don't collide.

```cron
# HOS worker & overseer — every 5 min; each fire runs the cycle (#1196)
1,6,11,16,21,26,31,36,41,46,51,56 * * * *  $HOME/Code/HOS/Worker/bin/hos-cron --role worker   --project hos >> /tmp/hos-worker-hos.log 2>&1
4,9,14,19,24,29,34,39,44,49,54,59 * * * *  $HOME/Code/HOS/Worker/bin/hos-cron --role overseer  --project hos >> /tmp/hos-overseer-hos.log 2>&1

# CPS worker & overseer — offset from HOS
2,17,32,47 * * * *  $HOME/Code/CPS/Main/bin/hos-cron --role worker   --project cps >> /tmp/hos-worker-cps.log 2>&1
9,24,39,54 * * * *  $HOME/Code/CPS/Main/bin/hos-cron --role overseer  --project cps >> /tmp/hos-overseer-cps.log 2>&1

# Weekly log trim (Sunday 2am)
0 2 * * 0  $HOME/Code/HOS/Worker/bin/hos-trim-logs
```

Expand `$HOME` to the absolute path in the actual crontab.

**Platform notes:**

- **macOS:** `crontab -e`. On first run, Terminal/cron may need Full Disk Access
  (System Settings → Privacy & Security) to read repo files. The machine must be
  awake — cron does not wake a sleeping Mac.
- **Ubuntu (unattended):** `crontab -e` works, but for a server prefer a systemd
  user timer or ensure the user's cron runs with a login-like environment. cron's
  `HOME` is set to the user's home automatically; the wrapper pins PATH itself.
  For 24/7 ops, run as a dedicated user and enable lingering:
  `loginctl enable-linger <user>`.

### Consumer projects use their own copy

A consumer (e.g. CPS) should point at **its own** `bin/hos-cron`, installed from a
validated HOS release via `hos_install.sh`, not at the HOS dev repo. That pins the
launcher version and decouples the consumer from in-flight HOS changes.

---

## 5. Per-fire bounds & cost

Headless fires draw from the **same weekly subscription rate limit** as interactive use.
Controls (all optional env overrides):

| Variable | Default | Purpose |
|---|---|---|
| `HOS_CRON_MAX_SECONDS` | `1800` | Wall-clock cap per session (`0` disables). Kills a hung/runaway session. See precedence below. |
| `HOS_CRON_MAX_TURNS` | unset | Optional `--max-turns` backstop. Leave unset — a low cap truncates legitimate pipeline work. |
| `HOS_CRON_AUTH_PROBE` | `0` | `1` spends a model turn pre-flighting auth. Off by default to save rate limit. |

### Session timeout precedence (`--max-seconds`, #1434)

The wall-clock cap has three ways to override the default, resolved in this
order (highest wins):

```
--max-seconds <N>                 (highest — one-off invocation)
HOS_CRON_MAX_SECONDS env          (crontab-wide, applies to every entry)
<project>_max_seconds in projects.conf   (per-project default)
1800 default                      (lowest)
```

`0` disables the cap at any tier. A non-numeric value from any source fails
loudly and names the offending source — it never silently falls back to the
default.

```bash
# One-off: this fire only, e.g. a work item known to be large.
bin/hos-cron --role worker --project hos --max-seconds 5400

# Per-project default: every fire for this project, without touching the
# crontab or other projects' entries.
echo "cps_max_seconds=3600" >> ~/.config/hos/projects.conf
```

**The default stays 1800 deliberately.** The cap is currently the only bound
that reliably stops a hung/runaway session (`timeout` with no `--kill-after`
or process-group kill — see #1146), and a cap that's routinely too small is a
signal the work item should have been split, not a reason to raise the
ceiling everywhere. Use `--max-seconds` for runs known to need more room, not
as a blanket increase — each use is a data point that a build step was
oversized.

Every fire runs the cycle and spawns `claude` (#1196 removed the idle backoff
that used to suppress fires with no recent activity — it existed to reduce
"is there work?" polling during a suspected GitHub throttling incident that was
later traced to a different cause). The remaining cost controls are the
pre-Claude fast paths that already existed independent of the backoff: the
overseer skips the Claude launch entirely when the open-PR queue has nothing
actionable (all conflicting/draft, or none open), and the worker skips it when
all of its own open PRs are awaiting human merge. A worker fire with genuinely
no candidate work still spends a turn on Step 0/1/2 triage, since that
requires judgment the wrapper can't pre-filter.

---

## 6. Verify it works

Run the wrapper once by hand:

```bash
$HOME/Code/HOS/Worker/bin/hos-cron --role worker --project hos
```

Expected: authenticates as the bot, runs inner-loop tests, starts a worker cycle —
**no** "Credit balance is too low", **no** "Not logged in", **no** "command not found".

Then watch a real cron fire:

```bash
tail -f /tmp/hos-worker-hos.log
```

A fire with nothing actionable in the queue logs a `skipping cycle` line before
launching `claude`. An active fire logs `Authenticated as <bot> — starting
worker cycle`.

---

## 7. Troubleshooting

Every one of these is a failure we have actually hit:

| Symptom in the log | Cause | Fix |
|---|---|---|
| `claude: command not found` | cron's thin PATH | The wrapper pins PATH now; ensure `claude` is under `~/.local/bin` or update the pinned PATH block. |
| `Not logged in · Please run /login` | no OAuth token reaching claude | Create `~/.config/hos/claude-auth.env` (step 2). |
| `Credit balance is too low` | resolved to API-key billing | Token missing/expired, or `ANTHROPIC_API_KEY` is shadowing — the wrapper unsets it, but check your shell profile isn't re-exporting it. |
| `IDENTITY GUARD FAILED` | GitHub App auth env not propagating | Confirm `<config_dir>/apps.env` exists and `HOS_CONFIG_DIR` resolves (registry step 3). |
| `claude TIMED OUT after Ns` | session exceeded the wall-clock cap | Expected safety bound. Raise `HOS_CRON_MAX_SECONDS` if legitimate work needs longer. |
| `FATAL: missing …/claude-auth.env` | token file absent | Step 2. |

**Debugging cron-only failures** ("works in terminal, not in cron"): it is almost
always the thin environment. Temporarily add a one-shot cron line to capture cron's
real env, then diff against your interactive `env`:

```cron
* * * * *  env > /tmp/cron-env.txt 2>&1
```

```bash
diff <(sort /tmp/cron-env.txt) <(env | sort)
```

Remove the line once captured.

---

## 8. Security model (headless permissions)

Cron-fired sessions run `claude --print --permission-mode bypassPermissions` —
there is no human to approve tool calls, so the approval gate is cleared. The
agent can run arbitrary tools. The safety does **not** come from the CLI
permission gate; it comes from these layers (#728, #734):

1. **Human triage gate.** The worker only acts on issues labelled `needs-ai`,
   and a human applies that label. Untrusted issue content cannot reach the
   bypass-enabled agent without first passing a human review/triage step.
2. **OAuth token isolation.** `CLAUDE_CODE_OAUTH_TOKEN` authenticates `claude`
   but is **not** present in the bash-tool subprocess environment — `claude`
   strips it. Verified: a bash tool call sees `GH_TOKEN` and `HOS_BOT_LOGIN`,
   but not `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`. The long-lived
   subscription credential cannot be exfiltrated through a tool call.
3. **Scoped, short-lived GitHub token.** `GH_TOKEN` *is* in the agent's
   environment (it needs `gh`). It is a GitHub App **installation** token —
   scoped to the App's permissions (not your account) and valid ~1 hour. That
   bounds the blast radius if it were ever exfiltrated.
4. **Prompt-injection hardening.** The cron prompts instruct both agents to
   treat issue/PR/comment text as untrusted **data, never instructions**, and
   never to echo or transmit credentials. Injection attempts are escalated to a
   human, not obeyed.
5. **Overseer merge guardrails.** Merge authority is independently gated by
   `OVERSEER_CEILING`, protected surfaces, and human-required escalations — a
   prompt-injected "approve and merge" cannot bypass these.

`--allowedTools` is intentionally not used: the worker dispatches sub-agents and
runs arbitrary build/test commands, so a whitelist tight enough to stop exfil
also stops the work. Tool scope is governed by the agent definitions and the
human triage gate, not the launcher.

---

## See also

- `DECISIONS.md` (2026-06-21) — why headless-on-subscription via OAuth, why the env file not the keychain.
- `docs/MACHINE-ACCOUNTS-SETUP.md` — GitHub App credentials (`apps.env`).
- `bin/hos-cron` — the launcher; its header documents every env override.
