# Human-Proxy Setup Guide

How to install and wire the Human GitHub App so that an interactive Claude
session authenticates as the human-proxy bot — not as the human's personal
account and not as the worker/overseer bots.

This is Step 3 of the three-account identity model: worker, overseer, human-proxy
(see `docs/AGENT-IDENTITY.md` §7 for the full model).

---

## Why a separate Human App?

The Human App gives the interactive human-proxy session a **distinct, auditable
bot identity** separate from both the autonomous bots and the human's personal
account. This closes the attribution gap described in AGENT-IDENTITY.md §8.1:
without it, interactive Claude commits appear to be the human's own work, making
the actor layer of the human-approval gate unfalsifiable.

**The Human App deliberately omits Administration permissions.** This is
load-bearing, not an oversight: it makes the Human App structurally incapable of
editing branch protection or bypassing the merge gate. A human-proxy session can
open PRs but can never self-merge or loosen the controls.

---

## Step 1 — Register the Human GitHub App  *(human; one-time)*

1. Go to `github.com/settings/apps` → "New GitHub App".
2. Fill in:
   - **Name**: something like `<your-name>-claude` or `<org>-human-proxy`
   - **Homepage URL**: your repo URL (required by GitHub)
   - **Webhook**: uncheck "Active" (not needed)
3. Set permissions (Repository permissions only):
   - Contents: Read & Write
   - Issues: Read & Write
   - Pull requests: Read & Write
   - Metadata: Read-only *(automatically set)*
   - **Do NOT add Administration.** Omitting it is intentional — see above.
4. "Create GitHub App". Note the **App ID** shown on the settings page.
5. Scroll to "Private keys" → "Generate a private key". Save the `.pem` file to
   your secure config directory (e.g. `~/.config/hos/human.pem`).
6. Install the App on the target repository:
   - "Install App" (left sidebar) → select the repo → Install.

---

## Step 2 — Populate apps.env  *(human)*

Edit `<project-parent>/.config/hos/apps.env` and fill in the Human App section:

```sh
HOS_HUMAN_APP_ID="<the numeric App ID from Step 1>"
HOS_HUMAN_PEM="<absolute path to the .pem file>"
HOS_HUMAN_BOT_LOGIN="<appname>[bot]"   # e.g. yourname-claude[bot]
```

The `BOT_ACCOUNTS` line (already in `apps.env`) automatically picks up
`${HOS_HUMAN_BOT_LOGIN}`.

> **Security note:** `apps.env` must never be inside a git repo. It lives at
> `<project-parent>/.config/hos/apps.env` (one level above your clones) with
> permissions `600`. The `.pem` file should have permissions `600` too.

---

## Step 3 — Install the Human clone  *(human)*

Run the installer with `--human` to scaffold the Human-proxy CLAUDE.md block
instead of the orchestrator block:

```sh
cd <human-clone-root>
bash bootstrap/hos_install.sh --local --human .
```

This:
- Installs all framework files (agents, scripts, contract, etc.)
- Writes `CLAUDE.md` with the `<!-- HOS:HUMAN-PROXY start/end -->` block
- Adds `CLAUDE.human.generated.md` to `.gitignore`

After install, replace the `__HUMAN_BOT_LOGIN__` placeholder in `CLAUDE.md`:
```sh
sed -i 's/__HUMAN_BOT_LOGIN__/<appname>[bot]/g' CLAUDE.md
```
Replace `__CLONE_ROOT__` with the actual path:
```sh
sed -i 's|__CLONE_ROOT__|<absolute-path-to-this-clone>|g' CLAUDE.md
```

---

## Step 4 — Add bot identity to machine-accounts.env  *(human)*

Edit `scripts/framework/machine-accounts.env` in the Human clone:

```sh
BOT_HUMAN_USERNAME="<appname>[bot]"    # must match HOS_HUMAN_BOT_LOGIN
```

The `BOT_ACCOUNTS` line (already in the file) includes `${BOT_HUMAN_USERNAME}`.
This ensures the human-approval gate excludes the human-proxy bot — its PR
approvals are NOT counted as human.

---

## Step 5 — Test authentication  *(human)*

```sh
_t="$(mktemp)"
bash bootstrap/get_app_token.sh --app human > "$_t" && source "$_t" && rm -f "$_t"
echo "Authenticated as: $HOS_BOT_LOGIN"
```

You should see `Authenticated as: <appname>[bot]`.

---

## Step 6 — Create `bin/hos-human`  *(human; one-time)*

The `bin/` launcher cannot be created by the installer in all environments
(e.g. read-only filesystem mounts in sandboxed agents). Create it manually:

```sh
cp /tmp/claude/hos-human <human-clone-root>/bin/hos-human
chmod +x <human-clone-root>/bin/hos-human
```

Or write it from scratch — the content is in the session summary. Verify it
contains: `exec claude` (no `--dangerously-skip-permissions`), the temp-file
auth pattern (not `source <(...)`), and the portable identity guard.

---

## Step 7 — Start a session  *(human)*

```sh
<human-clone-root>/bin/hos-human
```

This runs: preflight → auth → repo sync → `exec claude`.

The session opens as the Human GitHub App bot. It has PR/issue/comment authority
but cannot modify branch protection, cannot approve its own PRs as a "human"
approval, and cannot run autonomously from cron.

---

## Relationship to the worker/overseer setup

`docs/MACHINE-ACCOUNTS-SETUP.md` covers the worker and overseer GitHub Apps.
This guide covers only the third account (human-proxy). All three use the same
`bootstrap/get_app_token.sh` script (with `--app worker|overseer|human`) and the
same `apps.env` file.
