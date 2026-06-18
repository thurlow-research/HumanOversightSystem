# HOS Unattended Worker — Operator Enable/Disable Guide

**Spec:** `UNATTENDED-WORKER-PROTOCOL.md` (the normative reference)
**Status:** v1.0 — derived from the implemented spec. Do not edit the spec from here.

---

## Quick start (enable on this machine)

```bash
# 1. Ensure the governance config commits enabled: true in PROJECT/
cat PROJECT/hos-coordination.yaml   # must contain: enabled: true

# 2. Activate on this machine (creates ~/.hos/<repo-id>/ACTIVE)
./scripts/framework/provision_agent_account.sh worker --pat "$WORKER_PAT"
./scripts/automation/lib/activation.py  # or:
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.automation.lib.activation import activate
repo_id = activate()
print(f'Activated: {repo_id}')
"

# 3. Set up the cron (as the operator, not as root)
crontab -e
# Add:
# Worker — opens branches/PRs (as HOSWorkerTutelare)
0,30 * * * *  cd /path/to/repo && bash scripts/automation/hos_orchestrator.sh hos-orchestrator --class worker >> /tmp/hos-worker.log 2>&1
# Overseer — reviews/merges (as HOSOversightTutelare)  
15,45 * * * *  cd /path/to/repo && bash scripts/automation/hos_orchestrator.sh hos-orchestrator --class overseer >> /tmp/hos-overseer.log 2>&1
```

---

## Three controls

| Control | What it means | How to toggle |
|---|---|---|
| **Policy off** (`enabled: false`) | This repo is not sanctioned. Auditable, committed, durable. | Edit `PROJECT/hos-coordination.yaml` and merge a PR (CODEOWNERS-gated). |
| **Operator off** (no `ACTIVE` file) | Not running on this machine. Easy, local, non-propagating. | `python3 -c "from scripts.automation.lib.activation import deactivate; deactivate()"` |
| **Emergency kill** (`hos-halt` file) | Stops a running, authorized + activated worker immediately. | `touch PROJECT/hos-halt && git add PROJECT/hos-halt && git commit -m "halt" && git push` |

**Both Policy (enabled) AND Activation (ACTIVE file) must be true** for the loop to do anything.

---

## Disable (graceful)

```bash
# Stop new dispatch immediately; in-flight workers stop within 15m (one heartbeat)
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.automation.lib.activation import deactivate
repo_id = deactivate()
print(f'Deactivated: {repo_id}')
"
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
./scripts/framework/provision_agent_account.sh doctor
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.automation.lib.activation import check_activation, derive_repo_id
repo_id = derive_repo_id()
active = check_activation()
print(f'repo_id: {repo_id}')
print(f'active:  {active}')
"
```

---

## Relocating to a new machine

1. `deactivate` on the old machine (or `rm ~/.hos/<repo-id>/ACTIVE`)
2. Wait ≤15m for any in-flight workers to stop
3. `activate` on the new machine
4. Update the cron on the new machine
