# Machine Accounts — Setup Guide

How to wire the HOS two-account identity model (`AGENT-IDENTITY.md` §7) so that
AI work is **attributable** (worker vs overseer vs human) and the human gate is
**server-side enforced** (a bot cannot approve or merge what only a human may).

This is hosting-agnostic. The default path below is a **personal repo +
collaborators** (no GitHub org required). If you later move to an org, the same
config works — you just manage the bots via a team instead of collaborators.

> **Nothing here changes behavior until you enable branch protection (Step 5).**
> The workflow + CODEOWNERS ship inert; Step 5 is the deliberate switch-on.

---

## The model in one paragraph

Two machine accounts, by class (not one per agent):
- **worker** — agents that *do work* (coder, technical-design, …). Opens PRs; **never approves**.
- **overseer** — agents that *review & approve* (reviewers, risk-assessor, evaluator, orchestrator, Faberix). **Approves + merges** SAFE/LOW non-protected PRs end-to-end; **recommends-only** above its ceiling (escalates to a human).

A **human** is required to approve: any **protected surface** (§9), any PR above the **overseer ceiling**, and any HIGH/CRITICAL change. Enforcement is server-side (GitHub Actions + branch protection), outside the agents' reach.

---

## Step 1 — Create the two accounts  *(human; one-time)*

Create two GitHub accounts, each with its own email. For this repo they are:
- worker → `hos_worker@tutelare.ai`
- overseer → `hos_oversight@tutelare.ai`

> GitHub **usernames** cannot contain `_`; the emails above are login addresses, not handles. Note each account's actual **username** — you need it in Step 3.

## Step 2 — PATs + collaborator access  *(human)*

For each bot, sign in and create a **fine-grained PAT** scoped to this repo:
- **worker** PAT: Contents=Read/Write, Pull requests=Read/Write. *No* admin.
- **overseer** PAT: Contents=Read/Write, Pull requests=Read/Write. *No* admin.

Add both bots as **collaborators** (Settings → Collaborators): worker = **Write**, overseer = **Write**. (Neither gets Admin — only the human keeps admin, so only the human can `--admin`-bypass the gate.)

## Step 3 — Tell HOS the bot handles  *(human edits config)*

Edit `scripts/framework/machine-accounts.env`:
```sh
BOT_WORKER_USERNAME="<worker-github-username>"
BOT_OVERSEER_USERNAME="<overseer-github-username>"
OVERSEER_CEILING="LOW"      # raise to MEDIUM later — one line, deliberate decision
```
`BOT_ACCOUNTS` is derived from these; the status check uses it to tell a bot
approval from a human one. (While unset, the gate still requires *an* approval on
a protected surface — it just can't yet exclude bot approvals.)

## Step 4 — Point each agent context at the right account  *(per machine)*

In the worker's working copy:
```sh
git config user.name  "hos-worker"   &&  git config user.email "hos_worker@tutelare.ai"
gh auth login --with-token < worker.pat        # worker PAT, not the human's token
```
In the overseer's working copy, the same with the overseer identity + PAT. The
human's own clone keeps the human identity. The point: each actor's commits and
approvals carry its own identity, so the audit trail is real.

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
  --description "Human authorized the release — paired with re-assignment to the worker"
```

These labels are part of the NG3b human-approval gate. `release-request` marks
a valid release-preparation request; `release-authorized` is one of the three
required authorization signals (add this label + remove `needs-human` + re-assign
to the worker, ALL by the same human CODEOWNER). See `worker.md` Release
authorization protocol.

---

## Step 9 — Configure cron schedules *(human; one-time per machine)* (#642)

Add the following entries to the operator's crontab (`crontab -e`):

```crontab
# HOS Worker — fires at :00, :15, :30, :45 of every hour
0,15,30,45 * * * * /path/to/project/Worker/bin/hos-worker-cron >> /tmp/hos-worker.log 2>&1

# HOS Overseer — fires at :07, :22, :37, :52 (offset 7 min from worker)
7,22,37,52 * * * * /path/to/project/Overseer/bin/hos-overseer-cron >> /tmp/hos-overseer.log 2>&1
```

**Why the 7-minute offset:** The worker opens PRs; the overseer needs time to see them. A 7-minute gap gives the worker a window to complete its cycle before the overseer's next check, reducing empty overseer cycles.

**Replace `/path/to/project/`** with the actual project parent path (e.g. `/Users/you/Code/CPS`). The `bin/` scripts handle preflight, auth, and jitter automatically.

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
