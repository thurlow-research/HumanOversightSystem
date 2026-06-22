# HOS Unattended Worker — Operator Enable/Disable Guide

**Spec:** `UNATTENDED-WORKER-PROTOCOL.md` (the normative reference)
**Status:** v1.0 — derived from the implemented spec. Do not edit the spec from here.

---

## Quick start (enable on this machine)

See `docs/CRON-SETUP.md` for the complete setup guide (`bin/hos-cron` is the launcher).
The abbreviated flow:

```bash
# 1. Ensure the governance config commits enabled: true in PROJECT/
cat PROJECT/hos-coordination.yaml   # must contain: enabled: true

# 2. Set up the cron (as the operator, not as root)
crontab -e
# Add (see docs/CRON-SETUP.md §4 for the full crontab block):
# Worker — opens branches/PRs (as hos-worker-hos[bot])
1,6,11,...,56 * * * *  $HOME/Code/HOS/Worker/bin/hos-cron --role worker  --project hos >> /tmp/hos-worker-hos.log 2>&1
# Overseer — reviews/merges (as hos-overseer-hos[bot])
4,9,14,...,59 * * * *  $HOME/Code/HOS/Worker/bin/hos-cron --role overseer --project hos >> /tmp/hos-overseer-hos.log 2>&1
```

---

## Three controls

| Control | What it means | How to toggle |
|---|---|---|
| **Policy off** (`enabled: false`) | This repo is not sanctioned. Auditable, committed, durable. | Edit `PROJECT/hos-coordination.yaml` and merge a PR (CODEOWNERS-gated). |
| **Cron off** | Not running on this machine. Easy, local, non-propagating. | Remove or comment out the cron lines (`crontab -e`). |
| **Emergency kill** (`hos-halt` file) | Stops a running, authorized worker at its next check. | `touch PROJECT/hos-halt && git add PROJECT/hos-halt && git commit -m "halt" && git push` |

**Policy (enabled) must be true** for the loop to do meaningful work; removing the cron lines stops firing.

---

## Disable (graceful)

```bash
# Stop new fires immediately — remove the cron entries
crontab -e   # comment out or delete the hos-cron lines
# In-flight Claude sessions finish their current turn then stop naturally.
```

## Emergency stop (immediate)

```bash
# Creates a committed file that stops the loop at its next heartbeat (≤15m)
echo "halted $(date -u)" > PROJECT/hos-halt
git add PROJECT/hos-halt && git commit -m "chore: emergency hos-halt" && git push
```

Remove the halt when ready to resume:
```bash
git rm PROJECT/hos-halt && git commit -m "chore: remove hos-halt" && git push
```

---

## Verify status

```bash
# Verify the governance config is enabled
cat PROJECT/hos-coordination.yaml | grep enabled

# Run the launcher by hand (idle-backoff disabled so it actually fires)
HOS_IDLE_INTERVAL=0 $HOME/Code/HOS/Worker/bin/hos-cron --role worker --project hos
# Expected: "Authenticated as hos-worker-hos[bot] — starting worker cycle"
```

---

## Relocating to a new machine

1. Remove the cron entries on the old machine (`crontab -e`)
2. Wait for any in-flight Claude sessions to finish
3. Set up the new machine (see `docs/CRON-SETUP.md`)
4. Add the cron entries on the new machine
