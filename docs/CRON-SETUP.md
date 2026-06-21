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

## 3. Project registry

`bin/hos-cron` resolves each project's repo paths and config dir from a
machine-local registry. Create `~/.config/hos/projects.conf`:

```ini
# <project>_<key>=<value>   — keys: config_dir, worker_root, overseer_root
hos_config_dir=$HOME/Code/HOS/.config/hos
hos_worker_root=$HOME/Code/HOS/Worker
hos_overseer_root=$HOME/Code/HOS/Overseer

cps_config_dir=$HOME/Code/CPS/.config/hos
cps_worker_root=$HOME/Code/CPS/Main
cps_overseer_root=$HOME/Code/CPS/Main
```

Use real absolute paths (expand `$HOME` yourself — this file is not shell-sourced
for expansion). `chmod 600` it.

Each project also needs its GitHub App credentials at `<config_dir>/apps.env`
(see `docs/MACHINE-ACCOUNTS-SETUP.md`).

---

## 4. Crontab entries

The wrapper pins its own PATH, so **no `PATH=` prefix is required**. Schedule
each role; offset projects so they don't collide.

```cron
# HOS worker & overseer — every 5 min, wakeup/backoff suppresses idle fires
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
| `HOS_CRON_MAX_SECONDS` | `1800` | Wall-clock cap per session (`0` disables). Kills a hung/runaway session. |
| `HOS_CRON_MAX_TURNS` | unset | Optional `--max-turns` backstop. Leave unset — a low cap truncates legitimate pipeline work. |
| `HOS_IDLE_INTERVAL` | `1800` | Idle-backoff threshold. Fires with no work and a recent run exit immediately (zero cost). |
| `HOS_CRON_AUTH_PROBE` | `0` | `1` spends a model turn pre-flighting auth. Off by default to save rate limit. |

Idle-backoff (#628) is the main cost control: idle fires never spawn `claude`.
Only active cycles (real work) consume the subscription.

---

## 6. Verify it works

Run the wrapper once by hand (idle-backoff disabled so it actually runs):

```bash
HOS_IDLE_INTERVAL=0 $HOME/Code/HOS/Worker/bin/hos-cron --role worker --project hos
```

Expected: authenticates as the bot, runs inner-loop tests, starts a worker cycle —
**no** "Credit balance is too low", **no** "Not logged in", **no** "command not found".

Then watch a real cron fire:

```bash
tail -f /tmp/hos-worker-hos.log
```

A healthy idle fire logs `idle backoff — …s since last run`. An active fire logs
`Authenticated as <bot> — starting worker cycle`.

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

## See also

- `DECISIONS.md` (2026-06-21) — why headless-on-subscription via OAuth, why the env file not the keychain.
- `docs/MACHINE-ACCOUNTS-SETUP.md` — GitHub App credentials (`apps.env`).
- `bin/hos-cron` — the launcher; its header documents every env override.
