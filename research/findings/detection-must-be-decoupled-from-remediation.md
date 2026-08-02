# Finding: Detection Must Be Decoupled From Remediation

**Role:** oversight-mechanism — a system that cannot fix a condition can usually still detect it, and conflating the two turns a bounded failure into unbounded invisible drift

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

Self-maintenance tasks in an oversight system are typically implemented as a single capability: *try to fix the condition; if that fails, continue*. When the fix is structurally impossible — a permission boundary, a missing credential, an unreachable host — the failure recurs every cycle and is reported nowhere, because "best effort" was chosen deliberately so maintenance would not block work.

The result is not a bounded outage. It is **unbounded divergence with no discovery event**.

In most such cases, detection and remediation are separable, and detection survives the condition that broke remediation. Splitting them converts an invisible failure into a visible one at near-zero cost.

### The instance

The Human-proxy clone runs `bootstrap/hos_repo_sync.sh` at session start, documented as *"best-effort; a sync failure does not block the session."*

The session sandbox marks `bin/**` and `.claude/agents/**` read-only at the kernel level. Any `git pull` touching those paths fails:

```
error: unable to unlink old 'bin/hos-cron': Read-only file system
error: unable to unlink old '.claude/agents/worker.md': Read-only file system
```

So the sync had failed **every session, silently**. The clone was found **8 commits behind** `origin/main` — discovered not by any monitoring, but because a line-number citation in an issue looked wrong.

The consequences were not cosmetic. Analysis performed against the stale tree produced file and line references that had to be caveated across several filed issues. And an attempted repair from inside the sandbox made it worse: `git pull` rewrote the seven files it could write, aborted on the read-only ones, and left the working tree mismatched against `HEAD` — requiring a terminal outside the sandbox to resolve.

### The separable half

`git fetch` **succeeds** under exactly the same sandbox. It writes only inside `.git/`, never touching the protected working-tree paths. It was run successfully several times during the session that found the problem.

So `git rev-list --count HEAD..origin/main` was available at every one of those silent sessions. The system could always have known it was stale. It simply never asked, because "sync" was one capability and that capability had failed.

## The generalisation

The pattern to look for: **a maintenance operation whose write half is blocked but whose read half is not.** These are common, because permission boundaries are usually asymmetric — they restrict mutation, not observation.

- Cannot pull, but can fetch and compare refs.
- Cannot write config, but can read and diff it.
- Cannot rotate a credential, but can check its expiry.
- Cannot restart a service, but can query its health.

In each case the detection half is cheap and unblocked, and it is what an operator actually needs. Remediation can be deferred, delegated, or performed out-of-band.

## A second-order result: prefer relocating the actor over weakening the boundary

Once detection was separated, the remediation question narrowed usefully. Two prior sessions had argued about whether to remove the deny rule protecting `bin/` — one arguing it breaks git, the next arguing it protects a sensitive surface.

Separating the concerns exposed a third option neither had considered: run the sync from **cron**, which executes outside the session sandbox. A trusted non-agent process updates the protected paths; the agent still cannot touch them. The protection is preserved in full and only its side effect is removed.

**When a safety boundary blocks a legitimate operation, check whether a different, trusted actor can perform it before weakening the boundary.** The disagreement was not a genuine trade-off; it was a missing option.

## Implication for research

Oversight frameworks should treat "can I observe the invariant?" and "can I restore the invariant?" as distinct capabilities with distinct failure modes, and should never allow a remediation failure to suppress the corresponding observation. Best-effort remediation is defensible. Best-effort *detection* is how systems drift.

The stronger claim, supported by this session and by several sibling findings: the recurring failure shape in oversight systems is **a mechanism that reports success, or reports nothing, while not doing what it is believed to do**. Detection that survives its own remediation path is one of the few cheap defences against that class.

## What changed

- **#1200** — session start reports the behind-count loudly, and distinguishes *transient* sync failure (retry next session) from *structural* failure (will never succeed unattended; names the cause).
- **#1201 / #1202** — sync relocated to cron, outside the sandbox, preserving the write-protection.
- **#1203** — one-time manual repair of the partial-pull state, assigned to the human because it cannot be performed from inside the sandbox.
- **#1195** — the operator dashboard must degrade a missing or unreadable source to *"unknown"*, never to *"healthy"*.
