# Finding: Wrong Rationale Outlives Wrong Conclusions

**Role:** oversight-mechanism — handoff artifacts transmit reasoning, and the next agent reasons from it rather than re-deriving

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

When an agent records a conclusion together with its reasoning, an error in the *reasoning* is more durable and more damaging than an error in the *conclusion*.

A wrong conclusion tends to be caught by the next action that depends on it — the command fails, the file is not there, the number does not match. A wrong rationale attached to a roughly-correct conclusion produces no such friction. It is inherited, cited, and built upon. Downstream agents reason *from* it rather than re-deriving, so the error propagates into decisions the original author never contemplated.

In a single session, three confidently-written claims were falsified. In all three the recommended action remained approximately right, which is precisely why they survived review:

| Claim as recorded | What measurement showed |
|---|---|
| "`Edit(./bin/**)` is a partial fix — `Edit()` gates the Edit tool only, so Bash can still write there via `sed -i`, `cp`, `mv`, `tee`, `>`" | `bin/` is read-only at the **kernel sandbox** layer. A `git pull` — ordinary Bash — failed with `Read-only file system`. |
| "Removing the idle backoff eliminates a 30-minute latency on all work" | An inter-role wakeup ping-pong meant each completed cycle woke the other role, so the backoff never bit while work was flowing. The real gap was cold-start only. |
| "Required thread resolution is stricter than human practice — it removes the reviewer's ability to approve over non-blocking comments" | It does not constrain the outcome at all. The author may resolve without changing anything and still merge. It constrains *attention*. |

Each had already been written into a handoff document. Each would have been inherited by the next session as established fact.

The second is the clearest case. "Remove the idle backoff" was the right action for the right *outcome* — the human wanted deterministic 10-minute polling — but the stated justification described a latency that did not exist. An agent inheriting that rationale would have concluded the change was urgent and high-impact, and would have mis-prioritised the genuinely dominant throughput constraint sitting one function away in the same file.

## Why this is not simply "be more careful"

The failure has a structural cause. Handoff documents, audit trails, and issue bodies are optimised to carry *decisions* compactly. Evidence is bulky, so it is compressed to a claim. The compression is lossy in a specific direction: it preserves what was concluded and discards what would let a reader falsify it.

Once compressed, the claim reads with the same authority as a measured one. Nothing in the artifact distinguishes "I tested this" from "I inferred this from the code" from "the previous handoff said so."

## Implication for research

Oversight systems that pass state between agent sessions need artifacts that record **the basis of a claim, not only the claim** — and that mark the basis type. The minimum viable distinction is *measured* versus *inferred* versus *inherited*, attached to each load-bearing assertion.

This generalises the existing finding [`unenforceable-rules-need-verification-mechanisms`](unenforceable-rules-need-verification-mechanisms.md): there, a rule the agent could not verify became advisory. Here, a *claim* the next agent cannot re-verify becomes axiomatic. Both stem from state that cannot be checked against reality at the point of use.

It also connects to the SLR's verdict–rationale contradiction work, where flagging contradictions matters because *most contradictions are misleading approvals* (Jin & Chen, 2026, `A5WDGC7J`). Observed here outside any review verdict, in ordinary diagnostic prose — suggesting the phenomenon is a property of AI-generated justification generally, not of review decisions specifically.

## What changed

- Handoff convention: load-bearing claims are marked measured versus inferred, with the measurement quoted where it exists.
- #1194 — the autonomous worker records *why* it triaged an issue as it did, at decision time. Filed after a prior session recorded the worker's milestone assignments as "an unknown mechanism", having inherited a conclusion with no basis attached.

## Open question

Three falsifications in one session, all found incidentally while following unrelated threads, is not a rate that suggests thorough detection. The methodological question is whether unfalsified rationale can be audited systematically — and if so, at what cost relative to simply re-deriving.
