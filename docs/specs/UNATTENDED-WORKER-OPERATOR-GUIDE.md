# Unattended Worker Operator Guide

This guide covers deploying and operating an HOS unattended worker: a machine
that runs `hos_orchestrator.sh` on a cron schedule without a human logged in.

---

## Prerequisites

- Phase C of the project build is complete (i.e. `scripts/automation/hos_orchestrator.sh`
  exists and is executable).
- The machine bootstrap has been run (`bootstrap/hos_bootstrap.sh`).
- `hos activate` has succeeded for this repo.

---

## Quick start

### 1. Activate the worker

```bash
cd /path/to/repo
hos activate
```

This writes `~/.hos/<repo-id>/ACTIVE`. If `scripts/automation/hos_orchestrator.sh`
is missing or not executable the command will fail with a clear error — build
Phase C first, or use `hos activate --no-verify` during the build phase.

### 2. Install cron entries

Open the crontab for the service account (`crontab -e`) and add:

```cron
# Worker — runs every 15 minutes
*/15 * * * *  cd /path/to/repo && [ -x scripts/automation/hos_orchestrator.sh ] && bash scripts/automation/hos_orchestrator.sh hos-orchestrator --class worker >> /tmp/hos-worker.log 2>&1

# Overseer — runs every 30 minutes
0,30 * * * *  cd /path/to/repo && [ -x scripts/automation/hos_orchestrator.sh ] && bash scripts/automation/hos_orchestrator.sh hos-orchestrator --class overseer >> /tmp/hos-overseer.log 2>&1
```

The `[ -x scripts/automation/hos_orchestrator.sh ]` guard ensures the cron
silently skips rather than generating spurious failure output if the script is
temporarily absent (e.g. during a mid-build deployment).

### 3. Verify

```bash
tail -f /tmp/hos-worker.log
```

---

## Dead-man switch

The overseer checks for a heartbeat file written by the worker. If no heartbeat
is seen within 6 hours the overseer pages the on-call contact configured in
`config.sh` (`ONCALL_EMAIL`).

---

## Deactivating a worker

```bash
cd /path/to/repo
hos deactivate
```

Remove the cron entries manually after deactivating.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `hos activate` fails with "not found or not executable" | Phase C not built | Build Phase C or use `--no-verify` |
| Cron fires but nothing happens | `ACTIVE` file missing | Run `hos activate` |
| Overseer pages after < 6 h | Worker cron not installed | Check `crontab -l` |
