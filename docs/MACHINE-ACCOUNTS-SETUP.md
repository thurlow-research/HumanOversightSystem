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

## Step 5 — Enable enforcement in branch protection  *(human; the switch-on)*

Settings → Branches → protect `main`:
- ☑ **Require a pull request before merging** → **≥1 approving review**
- ☑ **Dismiss stale approvals** on new commits
- ☑ **Require review from Code Owners**  ← makes `.github/CODEOWNERS` (protected surfaces → human) binding
- ☑ **Require status checks to pass** → add **`require-human-approval`** (and your existing checks, e.g. `Validation stamps current`)
- ☑ **Do not allow bypassing the above settings** *(this disables `--admin` for the bots; the human, as the only Admin, retains it)*

Result: a worker PR needs an overseer-or-human approval; a **protected-surface or above-ceiling** PR needs a **human** approval that no bot can provide.

## Step 6 — Regenerate CODEOWNERS for your owner  *(consumers)*

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
| worker PR needs overseer/human | branch protection: ≥1 approving review | server-side |
| **protected surface → human** | `require-human-approval` status check **+** CODEOWNERS | **server-side (the §5.1 determination-honesty gate)** |
| above overseer ceiling → human | risk-tier status check *(next increment — #152 follow-up)* | server-side |
| no bot `--admin` bypass | "Do not allow bypassing" + bots lack Admin | server-side |

The protected-surface gate is the load-bearing one: it's the place the controls
that define the controls (`AGENT-IDENTITY.md` §9) can't be loosened on the bots'
own say-so. See `research/findings/actor-identity-vs-determination-honesty.md`.

---

## Step 7 — Create the release-authorization labels *(human; one-time)*

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

## Step 8 — Configure cron schedules *(human; one-time per machine)* (#642)

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
