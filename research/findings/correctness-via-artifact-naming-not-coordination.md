# Finding: Correctness in a Concurrent Autonomous System Can Be Achieved by Artifact Naming Rather Than Coordination

**Role:** oversight-mechanism — reliability of autonomous multi-instance loops

**First observed:** 2026-06-16, during the #254 unattended worker design and Phase A implementation (ADR-2 / `scripts/automation/lib/correlation.py`)

---

## The Finding

When multiple instances of an autonomous agent race to claim the same work item, the naive solution is mutual exclusion — a distributed lock. But distributed locks introduce exactly the failure modes they are meant to prevent: a lock holder that dies mid-work leaves a stale claim; a race to reacquire creates a thundering herd; and any state that lives only in the lock's memory is lost on crash.

The unattended worker design resolves this with a different principle: **make every artifact produced by a task deterministically named from the task's identity, not from the instance that claims it.** Concretely, the correlation-id is `sha256(canonical_issue_url + "#" + issue_number)[:12]` — a pure function of the work item. Two racing instances, computing the same cid from the same issue, produce the same branch name (`hos/auto/<cid>`). The second push to that branch is a no-op or fast-forward; it does not create a duplicate. The "duplicate work" failure mode is therefore **structurally eliminated at the artifact layer**, not prevented by coordination.

**The lock becomes a contention reducer, not a correctness mechanism.** A machine-global `mkdir` lock limits how many instances attempt a claim simultaneously — reducing wasted work — but the correctness guarantee (zero duplicate-work incidents, M1) does not depend on the lock holding. If two instances both win the lock race due to a clock skew, they still produce the same branch. The invariant is: "two instances produce the *same artifact*, so the second attempt is idempotent" — not "only one instance ever runs."

This also gives cold-start recovery for free: a new instance can reconstruct full task state by looking up the existing `hos/auto/<cid>` branch and any open PRs, without any instance-local state or a log it has to own.

## Why This Matters

The general principle is that **coordinating concurrent actors at the artifact level** (content-addressable naming, idempotent writes) is often simpler and more robust than coordinating at the execution level (locks, leader election, transactions). The content-addressability property — same input, same output name — is what makes this work. It requires the naming function to be deterministic across all instances and across time, which constrains the naming scheme but eliminates an entire class of distributed systems problems.

For autonomous AI oversight loops specifically, this matters because AI sessions are unreliable processes: they can die mid-task, be restarted by a cron on a different machine, or run concurrently without coordination. A lock-based correctness model breaks down in exactly these scenarios. A content-addressable artifact model is robust to all of them, at the cost of requiring the naming function to be stable and the artifact writes to be idempotent.

The design also surfaces a useful **operational definition of failure**: a "duplicate-work incident" is not "two instances attempted the same task" but "two instances produced *distinct* artifacts for the same task." A second push to the same branch is not an incident — it is the idempotency mechanism working correctly.

## Evidence

- `scripts/automation/lib/correlation.py` (this session) — the cid algorithm and the `already_exists()` precheck. The unit tests explicitly verify cid determinism across URL forms and instances (`test_correlation.py`).
- `scripts/automation/lib/machine_lock.sh` (this session) — the lock is explicitly documented as a "contention reducer" in a comment; `machine_lock.sh` carries the ADR-3 note that M1 correctness lives in `correlation.py`, not the lock.
- Design doc comment in tech design (§8): "claim.py must **not** be relied on for correctness (ADR-2). It reduces contention; M1 lives in correlation.py."

## Implications for Research

1. **Content-addressable naming as a distributed systems primitive for AI agents.** The principle transfers: any autonomous agent that creates artifacts should derive artifact names deterministically from the work item's identity, not from session IDs or random UUIDs. This is a design pattern, not a one-off choice.
2. **Separating "only one attempt" (lock) from "only one result" (naming).** Research on AI agent coordination often conflates these. The distinction matters: the former is expensive and fragile over unreliable networks; the latter is cheap and robust.
3. **Cold-start reconstructability as a correctness property.** Requiring that a new instance can reconstruct full task state from external artifacts alone (GitHub here) forces the architecture toward stateless, idempotent operations — a useful constraint that improves both correctness and auditability.

## Related findings

- `working-state-invariant.md` — the related problem of agents building interlocked-error chains; artifact-level idempotency prevents a different class of the same failure.
- `a-guard-that-doesnt-halt-is-not-a-guard.md` — the general principle that safety properties must be enforced at the right level (not bypassed by the layer below).
