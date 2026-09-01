# Machine Accounts — Setup Guide

How to wire the HOS three-account identity model (`AGENT-IDENTITY.md` §7) so that
AI work is **attributable** (worker vs overseer vs human-proxy vs human) and the
human gate is **server-side enforced** (a bot cannot approve or merge what only a
human may).

This file covers the **worker and overseer** GitHub Apps. For the third account
(human-proxy), see `docs/HUMAN-SETUP.md`.

This is hosting-agnostic. The default path below is a **personal repo with two
GitHub Apps installed on it** (no GitHub org required) — the Apps authenticate
via installation tokens, not as collaborator accounts. If you later move to an
org, the same config works — you just install the Apps on the org's repo
instead of a personal one.

> **Nothing here changes behavior until you enable branch protection (Step 5).**
> The workflow + CODEOWNERS ship inert; Step 5 is the deliberate switch-on.

---

## The model in one paragraph

Three bot accounts, by class (not one per agent):
- **worker** — agents that *do work* (coder, technical-design, …). Opens PRs; **never approves**.
- **overseer** — agents that *review & approve* (reviewers, risk-assessor, evaluator, orchestrator, Faberix). **Approves + merges** SAFE/LOW non-protected PRs end-to-end; **recommends-only** above its ceiling (escalates to a human).
- **human-proxy** — interactive Claude sessions driven by the human. Opens PRs, posts comments; **NOT counted as human approval**. See `docs/HUMAN-SETUP.md`.

A **human** is required to approve: any **protected surface** (§9), any PR above the **overseer ceiling**, and any HIGH/CRITICAL change. Enforcement is server-side (GitHub Actions + branch protection), outside the agents' reach.

---

## Step 1 — Register the worker and overseer GitHub Apps  *(human; one-time)*

Register two GitHub Apps — one per role. Repeat for each:

1. Go to **https://github.com/settings/apps/new**
2. **GitHub App name**: any unique name, e.g. `hos-worker-<yourproject>` /
   `hos-overseer-<yourproject>`. GitHub appends `[bot]` to its login
   automatically (e.g. `hos-worker-yourproject[bot]`) — note the exact login,
   you need it in Step 2.
3. **Homepage URL**: your repo URL
4. **Webhook**: uncheck **Active**
5. **Repository permissions**: `Contents: Read & write`, `Pull requests: Read
   & write`, `Issues: Read & write`, `Metadata: Read-only`. The **overseer**
   App additionally needs `Administration: Read-only` (to inspect branch
   protection state at review time — never write). Neither App gets Admin —
   only the human keeps that, so only the human can `--admin`-bypass the gate.
6. **Where can this be installed**: `Only on this account`
7. Click **Create GitHub App**
8. Note the **App ID** shown on the next page
9. Scroll to **Private keys** → **Generate a private key** → save the `.pem`
   file
10. Click **Install App** → install on your account → **Only select
    repositories** → choose this repo → **Install**

## Step 2 — Store credentials in apps.env  *(human)*

Either run the guided setup script, or fill in the template by hand.

**Guided (recommended):**
```sh
cd <project-parent>                              # e.g. ~/Code/CPS — NOT inside a git repo
Worker/bootstrap/hos_setup_partner.sh \
  --repo-owner <org-or-user> \
  --worker-app-id <id> --worker-pem <path-to-worker.pem> --worker-bot-login '<worker-app>[bot]' \
  --overseer-app-id <id> --overseer-pem <path-to-overseer.pem> --overseer-bot-login '<overseer-app>[bot]' \
  --human-reviewer <your-github-login>
```
This creates `.config/hos/apps.env`, copies the `.pem` files with `chmod 600`,
and runs `validate_setup.sh` to confirm the setup.

**Manual:**
```sh
mkdir -p .config/hos
cp Worker/bootstrap/apps.env.template .config/hos/apps.env
chmod 600 .config/hos/apps.env
# edit .config/hos/apps.env — replace every <PLACEHOLDER>: HOS_WORKER_APP_ID,
# HOS_WORKER_PEM, HOS_WORKER_BOT_LOGIN, HOS_OVERSEER_APP_ID, HOS_OVERSEER_PEM,
# HOS_OVERSEER_BOT_LOGIN, HUMAN_REVIEWER
bash Worker/bootstrap/validate_setup.sh --repo Worker/
```

Neither App is ever added as a repo **collaborator** or authenticated via a
personal access token. Each run mints a short-lived installation token from
the App ID + private key (`bootstrap/get_app_token.sh`), scoped to the repos
the App is installed on; the login returned by the mint is checked against
`GET /app` (#703), so a misconfigured or forged identity fails closed instead
of silently authenticating as the wrong bot.

## Step 3 — Tell HOS the bot handles  *(human edits config)*

Edit `scripts/framework/machine-accounts.env`:
```sh
BOT_WORKER_USERNAME="<worker-app-login>[bot]"      # e.g. hos-worker-yourproject[bot]
BOT_OVERSEER_USERNAME="<overseer-app-login>[bot]"  # e.g. hos-overseer-yourproject[bot]
OVERSEER_CEILING="LOW"      # raise to MEDIUM later — one line, deliberate decision
```
`BOT_ACCOUNTS` is derived from these; the status check uses it to tell a bot
approval from a human one. (While unset, the gate still requires *an* approval on
a protected surface — it just can't yet exclude bot approvals.)

## Step 4 — Point each agent context at the right account  *(per machine)*

Nothing to configure per working copy — there is no `git config user.email` /
`gh auth login` step. `bin/hos-cron --role worker|overseer` (and `bin/hos-human`
for the human-proxy) each mint their own short-lived installation token at the
start of every run, via `bootstrap/get_app_token.sh --app worker|overseer|human`,
reading the App ID + `.pem` from `.config/hos/apps.env` (Step 2). The minted
token authenticates `gh`/`git` for that run only and is never persisted to a
global `gh auth` state, so worker, overseer, and human-proxy sessions on the
same machine never share or clobber each other's identity. Each actor's
commits and approvals still carry its own bot identity, so the audit trail is
real — it's just resolved per-run instead of configured once per clone.

Verify a clone is wired correctly:
```sh
bash Worker/bootstrap/validate_setup.sh --repo Worker/
```

## Step 5 — Create the `hos-auditsync-hos` GitHub App  *(human; one-time per repo)*

Audit log files (`audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`) are gitignored from feature PRs and synced to main via a GitHub Actions workflow after each cron cycle. That workflow pushes directly to main, bypassing the PR requirement — which requires a dedicated app with a Ruleset bypass. A separate app (not the worker or overseer) is used to keep each bot's authority scoped to its own role. See #861 and #862.

### 5a — Create the app

1. Go to **https://github.com/settings/apps/new**
2. **GitHub App name**: `hos-auditsync-hos`
3. **Homepage URL**: your repo URL
4. **Webhook**: uncheck **Active**
5. **Repository permissions**: set **Contents** to `Read & write`; everything else `No access`
6. **Where can this be installed**: `Only on this account`
7. Click **Create GitHub App**
8. Note the **App ID** on the next page
9. Scroll to **Private keys** → **Generate a private key** → save the `.pem` file

### 5b — Install the app on the repo

1. On the app settings page, click **Install App**
2. Install on your account → **Only select repositories** → choose this repo → **Install**

### 5c — Store secrets

In the repo: **Settings → Secrets and variables → Actions**:
- `HOS_AUDIT_SYNC_APP_ID` — the numeric App ID from 5a
- `HOS_AUDIT_SYNC_PRIVATE_KEY` — the full `.pem` contents (including header/footer lines)

## Step 6 — Enable enforcement via Ruleset  *(human; the switch-on)*

Use a **Ruleset** rather than classic branch protection — Rulesets support installed GitHub Apps (like `hos-auditsync-hos`) in the bypass list, which classic rules do not.

**Settings → Rules → New ruleset → New branch ruleset:**

| Field | Value |
|---|---|
| Ruleset name | `main-protection` |
| Enforcement status | Active |
| Target branches | Include by pattern: `main` |

**Bypass list** → Add bypass → search `hos-auditsync-hos` → set mode **Always**.

**Rules** — enable:
- ☑ **Restrict deletions**
- ☑ **Require a pull request before merging**
  - Required approving reviews: **1**
  - ☑ Dismiss stale reviews on new commits
  - ☑ Require review from Code Owners
  - ☑ Require conversation resolution before merging
- ☑ **Require status checks to pass** → add `require-overseer-approval`, `require-human-approval`, `require-tier-ceiling`
- ☑ **Block force pushes**

Click **Create**, then delete the classic branch protection rule at **Settings → Branches**.

Result: every PR requires overseer approval; protected-surface or above-ceiling PRs require human approval. `hos-auditsync-hos` can push audit logs directly to main; all other actors go through the PR flow.

## Step 7 — Regenerate CODEOWNERS for your owner  *(consumers)*

```sh
./scripts/framework/gen_codeowners.sh @your-username   # defaults to the repo owner
```
This rewrites `.github/CODEOWNERS` from `scripts/framework/protected_surfaces.txt`
so the two never drift. Commit it.

---

## What enforces what

| Boundary | Mechanism | Strength |
|---|---|---|
| worker can't approve its own PR | GitHub "no self-approval" + worker has no approval grant | structural |
| **every PR → overseer must review** | `require-overseer-approval` status check (#621) | **server-side** |
| **protected surface → human** | `require-human-approval` status check **+** CODEOWNERS | **server-side (the §5.1 determination-honesty gate)** |
| above overseer ceiling → human | `require-tier-ceiling` status check | server-side |
| no bot `--admin` bypass | "Do not allow bypassing" + bots lack Admin | server-side |

The protected-surface gate is the load-bearing one: it's the place the controls
that define the controls (`AGENT-IDENTITY.md` §9) can't be loosened on the bots'
own say-so. See `research/findings/actor-identity-vs-determination-honesty.md`.

---

## Step 8 — Create the release-authorization labels *(human; one-time)*

```sh
gh label create release-request    --color B60205 \
  --description "Requests the worker prepare a release for human authorization"
gh label create release-authorized --color 0E8A16 \
  --description "Human authorized the release — paired with self-assignment by the same CODEOWNER"
```

These labels are part of the NG3b human-approval gate. `release-request` marks
a valid release-preparation request; `release-authorized` is one of the three
required authorization signals (add this label + remove `needs-human` + self-assign,
ALL by the same human CODEOWNER — GitHub Apps cannot be assigned to issues on this
repo, #1347, so the third signal is the CODEOWNER assigning the issue to
themselves, not to the worker). See `worker.md` Release authorization protocol.

---

## Step 9 — Configure cron schedules *(human; one-time per machine)* (#642)

Add the following entries to the operator's crontab (`crontab -e`). Both roles
share the single governed `bin/hos-cron` launcher (halt/suspend/overlap-lock/
timeout — see `docs/CRON-SETUP.md`); it resolves each role's repo path from
`~/.config/hos/projects.conf` by `--project` key, so one copy in the Worker
clone serves both roles. Do **not** hand-roll a per-role launcher — an earlier
generation of per-role scripts (`hos-worker-cron`/`hos-overseer-cron`) bypassed
every governance gate and was retired (#990).

```crontab
# HOS Worker — fires at :00, :15, :30, :45 of every hour
0,15,30,45 * * * * /path/to/project/Worker/bin/hos-cron --role worker --project <name> >> /tmp/hos-worker.log 2>&1

# HOS Overseer — fires at :07, :22, :37, :52 (offset 7 min from worker)
7,22,37,52 * * * * /path/to/project/Worker/bin/hos-cron --role overseer --project <name> >> /tmp/hos-overseer.log 2>&1
```

**Why the 7-minute offset:** The worker opens PRs; the overseer needs time to see them. A 7-minute gap gives the worker a window to complete its cycle before the overseer's next check, reducing empty overseer cycles.

**Replace `/path/to/project/`** with the actual project parent path (e.g. `/Users/you/Code/CPS`), and `<name>` with this project's key in `~/.config/hos/projects.conf` (e.g. `cps`) — see `docs/CRON-SETUP.md` §3. `bin/hos-cron` handles preflight, auth, and jitter automatically.

**Verify setup before adding to crontab:**
```bash
cd /path/to/project/Worker
bash bootstrap/validate_setup.sh --repo .
```

---

## apps.env template

A template with all required fields is provided at `bootstrap/apps.env.template`.
Copy it to the project-level config directory and fill in your values:

```bash
cd /path/to/project                          # project parent (e.g. ~/Code/CPS)
mkdir -p .config/hos
cp Worker/bootstrap/apps.env.template .config/hos/apps.env
chmod 600 .config/hos/apps.env
# Edit .config/hos/apps.env — replace all <PLACEHOLDER> values
bash Worker/bootstrap/validate_setup.sh --repo Worker/
```
