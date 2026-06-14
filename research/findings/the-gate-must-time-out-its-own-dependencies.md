# Finding: The oversight gate must time out its own dependency calls — or a hang is a denial of oversight

**Role:** oversight-mechanism — the gate enforces timeouts on the code it reviews, but its own reviewer call had none

**First observed:** 2026-06-13, framework validation runs (the agy hang)

---

## The finding

The framework's release gate runs cross-vendor AI review by shelling out to external CLIs: `agy -p "$prompt"` and `codex exec < "$prompt"`, each captured via command substitution with no time bound. When agy hung (it did, more than once), the command substitution blocked **forever** — and because the gate is a linear pipeline, the entire release validation stalled indefinitely with no error, no timeout, no recovery. A hung dependency in the gate is not a slow gate; it is a **dead** gate.

The bug is sharpened by what the framework *itself enforces*: it ships a `reliability-reviewer` whose whole job is to flag "outbound connections without timeouts, unbounded waits, no graceful degradation" in the code under review — and a `with_timeout` helper in `run_with_retry.sh` that every *validator* uses. Yet the gate's own outbound call to a hangable dependency had none of that. The overseer held the code to a standard it didn't apply to itself.

## Why it matters for scalable oversight

An oversight gate's availability *is* its value: a gate that can hang is one an operator learns to bypass ("it's stuck again, just `--skip-validation`"). The failure mode is worse than a crash, because a crash is visible and a hang is not — it looks like work in progress until someone notices the clock. And the dependency here is an LLM CLI, which is *exactly* the kind of thing that hangs unpredictably (network, rate limits, a wedged subprocess). Building a gate on an unbounded call to a non-deterministic, hang-prone dependency guarantees the gate inherits that dependency's worst latency — which is infinity.

The rule: **every call the gate makes to an external dependency must be hard-bounded, and a timeout must degrade to a recorded error, not a stall.** This is the reliability discipline the framework already preaches, applied recursively to the framework's own tooling. A timed-out reviewer becomes `verdict: error` (the convergence ledger and the human see "agy did not complete"), the gate continues, and the missing review is visible — strictly better than an invisible infinite wait.

## The mechanism (the fix)

- A portable `run_capped <secs> <outfile> <cmd…>`: prefer `timeout`/`gtimeout` when present, else a background-poll-and-kill fallback (macOS ships no `timeout`, so the fallback is the common path). Escalates `TERM` → `KILL` at the cap; returns `124` on timeout. Verified: a 30s hang under a 4s cap is killed in ~8s, not 30.
- Wrap **both** `agy` and `codex` in it (`AI_REVIEW_TIMEOUT`, default 300s). On timeout, synthesize the same `verdict: error` JSON the existing failure path already produces, log a `WARN`, and continue. No new failure semantics — just a bounded path to the one that already existed.
- A standalone **watchdog** (kill a stalled reviewer from outside) is a useful operational backstop, but it is not the fix: the *gate itself* must own its timeouts, so every consumer who runs `cut_release` is protected without remembering to start a babysitter.

## The trap it avoids

"It usually responds in a minute" is not a bound. An unbounded call sized by a typical case is fine until the atypical case — a wedged process, a hung socket — arrives, and then it is unbounded in the literal sense. For a gate, that converts a transient dependency hiccup into a permanent outage of oversight. The discipline is not "make it fast"; it is "make its worst case finite, and make the worst case a *recorded* outcome."

## Provenance

Observed 2026-06-13 across framework validation runs: agy hung with no cap, stalling the release gate. We first deployed an external watchdog to unstick the in-flight run, then put the permanent fix in `validate_agents.sh` (the `run_capped` wrapper around both reviewers). Related: `oversight-gate-must-declare-its-deps-and-fail-loud.md` (the gate's deps must be present *and* loud), `ci-is-blind-to-consumer-environment-failures.md` (macOS lacking `timeout` is exactly the consumer-environment gap that makes the portable fallback necessary), and the `reliability-reviewer` agent (whose own discipline the gate was failing to apply to itself).
