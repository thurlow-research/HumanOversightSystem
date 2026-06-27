# Finding: A convergence ledger that resets is a gate that never converges — the dedup state must persist in-repo

**Role:** oversight-mechanism — the persistence of the dedup ledger is what makes the non-deterministic gate's "zero-NEW" pass reachable in practice

**First observed:** 2026-06-27, fixing the v0.4.0 scripts-review non-convergence (HOS#686, #334)

---

## The finding

`operationalizing-a-nondeterministic-reviewer-as-a-gate.md` established that a non-deterministic (LLM/cross-vendor) reviewer can only be made into a hard gate by redefining "pass" as **zero-NEW** rather than zero — gate the verdict on a *dedup ledger* of dispositioned findings, not on the reviewer ever returning empty. That is mechanism (1) of the four-mechanism convergence architecture.

This finding is the corollary the v0.4.0 release exposed: **mechanism (1) is silently void unless the ledger persists across clones, machines, and releases.** The scripts-review ledger lived at a *gitignored* path (`.claudetmp/framework/`). On every fresh clone — every CI runner, every new machine, every release cut from a clean checkout — the ledger was empty, so the entire accumulated disposition history (everything previously triaged as `filed:#N` / `residual` / `noise`) was gone. "Zero-NEW" collapsed back to "zero," which a rich corpus never reaches. The observed cost: the v0.4.0 scripts-review gate failed to converge across **10+ attempts** and could only be shipped with `--skip-validation` — i.e. the gate was, in practice, off. The convergence architecture was fully implemented and still produced the exact failure it was built to prevent, purely because its state was ephemeral.

## Why it matters for scalable oversight

A dedup ledger is not an optimization on top of the gate — it *is* the gate's definition of "pass." If the ledger is the thing that distinguishes "every surfaced risk is dispositioned" (reachable) from "the reviewer found nothing" (unreachable), then **the durability of the ledger is a correctness property of the gate, not an implementation detail.** Storing it anywhere ephemeral — `/tmp`, a gitignored scratch dir, per-machine state — quietly reverts the gate to the unreachable bar, and the failure presents not as an error but as *non-convergence under load*: the gate keeps finding "new" issues that are actually already-triaged ones it has simply forgotten. The rational operator response to a gate that never passes is to disable it, which is precisely the worst outcome dressed as rigor (the same pressure documented in the parent finding).

The general rule: **any accumulator that defines a gate's terminating condition must be committed to the same repo as the code it gates, version-controlled and shared, so its state is identical on every machine that runs the gate.** State that the gate's convergence depends on cannot be local.

## The mechanism (the fix)

- Move the ledger from `.claudetmp/framework/` to the committed path `scripts/framework/scripts-review-ledger.jsonl`; dispositions now accumulate across machines and releases instead of resetting per clone.
- Commit an **empty** ledger as the baseline. An empty or missing ledger is an empty seen-set, so a clean checkout is **fail-closed-identical** to prior behavior — `load_ledger` only ever *adds* to the seen-set and can never manufacture an approve. Persistence can only make the gate *more* permissive over time as a human dispositions findings; it cannot weaken the fail-closed default. (The ratchet holds: automation accumulates, only a human adds a disposition.)
- `--reset` **truncates** the tracked file (empties the seen-set, keeps the file under version control) rather than deleting it, so the convergence state stays an auditable, diffable artifact.
- An env override (`HOS_SCRIPTS_REVIEW_LEDGER`) keeps tests hermetic without reintroducing an ephemeral production path.
- Deliberate asymmetry vs. the *agents/self* review ledgers, which remain ephemeral by design: those run against transient working state, the scripts-review ledger against the durable shipped corpus. The persistence decision is per-ledger, keyed to whether the reviewed artifact is durable.

## Provenance

Fixed 2026-06-27 (HOS#686 / SPEC-334) as improvement #5 of 6 in the scripts-review convergence work; structurally enables #6 (pre-seed). Root cause of the v0.4.0 non-convergence (10+ attempts, `--skip-validation` required). Direct extension of `operationalizing-a-nondeterministic-reviewer-as-a-gate.md` (mechanism 1, the dedup ledger) and `nondeterministic-review-gate-converges-on-zero-new.md` (the zero-NEW bar). Sibling to `chat-history-as-unreliable-artifact.md` (the same lesson — state a control depends on must be committed, not left somewhere transient).
