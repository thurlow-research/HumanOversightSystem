# Finding: The safety valve must be more trustworthy than the gates it disables

**Role:** oversight-mechanism — the mechanism that *disables* oversight is the highest-stakes component, and it had integrity bugs

**First observed:** 2026-06-13, CondoParkShare real-world HOS test run (HOS#105, #106)

---

## The finding

HOS lets a human suspend an individual gate (the ratchet: a human may *add* a suspension; automation may only *remove* one after N passing runs — `ratchet-principle.md`). The CPS operator reached for this to run a deliberate "one gate at a time" remediation: disable the broken gate, fix it, let it auto-re-enable. Exercising the suspension mechanism *for real* exposed two correctness bugs in the safety valve itself:

1. **Two parsers, two grammars (#105).** The Python manager (`suspension_manager.py`, `_SUSPENDED_RE`) accepted a `SUSPENDED:` line with optional `[pinned]` / `review-by: YYYY-MM-DD` flags. The bash gate hook (`check_suspension.sh`, `is_suspended`) matched only the bare, end-anchored form `^SUSPENDED: <gate>$`. So a human who wrote the *documented* flagged form got a suspension the census reported as **active** while the gate **kept running** — the suspension silently did nothing. The operator only avoided it by noticing the trap and writing a bare line.
2. **A bypass with no audit trail (#106).** Skipping a suspended gate printed a console notice and exited 0 — but wrote **nothing** to the append-only `audit/oversight-log.jsonl`. A bypassed safety check left no durable record; only a manual census aggregate existed. After the fact, there was no way to ask the audit log "when, and on whose authority, did this gate not run?"

## Why it matters for scalable oversight

A gate-suspension facility is the one place in the system whose *entire purpose* is to turn oversight **off**. That makes it the highest-stakes component, and it inverts the usual trust calculus: a flaky *gate* fails toward more human attention (it blocks, someone looks); a flaky *suspension* fails toward less (a check the human believes is either suspended-and-tracked or active is actually neither). Both bugs here failed in the dangerous direction:

- #105 produced a **silent disagreement** about whether a gate is on — the operator believes "suspended, with a review date"; the pipeline believes "running"; reality is "running and crashing." Whichever way you read it, a human's explicit oversight decision did not take effect, and nothing said so.
- #106 made a deliberate **reduction of oversight invisible** to the one artifact (the append-only log) that exists to make oversight accountable. A suspension you can't audit is indistinguishable from an unauthorized bypass.

The rule: **the safety valve must be more trustworthy than the gates it disables, and every use of it must be more auditable than an ordinary pass.** Disabling a check is exactly when the audit trail matters most.

## The mechanism (the fix)

- **One grammar.** `is_suspended()` now matches the same `[pinned]` / `review-by:` grammar as `_SUSPENDED_RE`, with a comment binding the two to stay in sync. (The deeper fix — a single shared parser — is noted; until then, the two are explicitly cross-referenced and covered by a test.)
- **Audit every bypass.** `print_suspended()` (the documented skip path every gate uses) now emits a `gate-suspended` event — `{event, gate, authorized_by, timestamp}` — to `audit/oversight-log.jsonl` on every skip, mirroring the `validator-failure` event shape. A bypass is now a first-class, append-only audit record, not just a console line.

## What worked — the ratchet held

The same run also *validated* a core control. The CPS agent, asked to get a green gate, found that `suspension_manager.py` has no code path that writes a `SUSPENDED:` line and correctly concluded it could not self-suspend — it stopped and required human authorization. "Only a human may loosen oversight" held under real pressure from an autonomous agent trying to unblock itself (`self-classification-cannot-gate-the-human-boundary.md`). The bugs were in *how* a human suspension was honored and recorded, not in *who* may suspend — the asymmetric-authority guard did its job.

## The trap it avoids

The seductive failure is to treat the suspension file as "just a list a human edits" and parse it loosely in two places. Loose, divergent parsing of a control surface is how a human's "turn this off and remind me to revisit" silently becomes "this is still running" or "this was turned off and no one can tell." The control surface that disables oversight needs *tighter* spec discipline than the gates — one grammar, one audit event per use — because it is the place where a small ambiguity converts directly into unaccountable loss of oversight.

## Provenance

Observed 2026-06-13 during the CondoParkShare real-world HOS test, while the operator exercised gate suspension to start a one-gate-at-a-time remediation (the portability gate, HOS#101 — itself already fixed upstream in PR #108). Fixes: `check_suspension.sh` grammar aligned with `suspension_manager.py` (#105) and a `gate-suspended` audit event on every skip (#106). Related: `ratchet-principle.md` (the asymmetric authority that held), `self-classification-cannot-gate-the-human-boundary.md`, `unenforceable-rules-need-verification-mechanisms.md` (a documented format that the enforcer ignored), `ci-is-blind-to-consumer-environment-failures.md` (the sibling field-test findings from the same run).
