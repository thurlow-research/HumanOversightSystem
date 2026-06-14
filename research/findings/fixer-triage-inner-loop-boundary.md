# The fixer triage: one inner-loop boundary, instantiated everywhere

**Role:** oversight-mechanism — the inner-loop boundary of the fixer role

## The finding

A system that scales human oversight needs a single, consistent answer to one question, asked by every agent that can both *detect* and *correct* a problem: **do I fix this myself, or does a human (or another agent) need to see it?** The answer is the same boundary the `coder` already follows in its inner loop, and it should be codified once and reused, not re-invented per agent:

- **Mechanical / local / unambiguous → fix in place.** The correct fix is dictated by an authoritative source and is a local correction (typo, path mismatch, missing field, stale claim, doc made faithful to the definition it describes). Apply it and re-run; iterate to clean. **File nothing** — issues feed the risk score, so filing mechanical fixes is noise that degrades the signal.
- **Structural / design / judgment → file an issue, escalate, do not paper over.** The finding is a contradiction, a governance change, a missing capability, or anything whose fix is not a local correction. It must reach a human or the owning agent, and it must feed the risk score (design instability *is* risk).

## Why it matters for scalable oversight

Oversight scales only if human attention is spent on the things that actually need judgment. Two failure modes destroy that, and they are symmetric:

1. **Filing mechanical fixes** floods the issue tracker and the risk-history signal with noise, so the genuinely structural findings — the ones a human must see — are buried. The oversight budget is wasted on triage.
2. **Fixing structural findings in place** is worse: it silently disposes of exactly the findings the human-oversight boundary exists to surface. A "fix" that makes a doc match a buggy implementation, or relaxes a check to make a test pass, removes the signal entirely. The system looks clean precisely where it is broken.

The triage is the rule that keeps the two apart, so that "the queue of things humans must look at" stays equal to "the things that actually need a human."

## The direction guard (the ratchet, again)

A fix-in-place may only correct *toward* the authoritative source, and may never loosen governance or rewrite an authoritative artifact to match a downstream one. When a doc and an agent definition disagree, the **doc** is corrected to match the definition — never the reverse, unless a human rules the definition wrong. This directionality is what separates a safe mechanical fix from a structural change wearing a mechanical disguise: editing *up* the authority gradient (spec → doc) is structural and needs a human; editing *down* it (doc ← spec) is mechanical. Collapsing that distinction is how an automated fixer becomes an unaudited loosening mechanism.

## One boundary, many instances

This is not a new control — it is the recognition that several existing ones are the same control:

- the `coder`'s inner loop (fix locally; escalate spec questions),
- the self-review **capped-iterate** protocol (fix/file each finding; converge on zero-new; cap then escalate),
- `doc-validator`'s loop-exit (fix doc omissions; stop after N recurrences),
- the change-type classification (`additive` applied autonomously; `structural` to a human),
- `risk-assessor`'s tier floor (raise autonomously; lowering needs a human).

Each is "automation may resolve the mechanical case; the judgment case goes to a human, and the unsafe direction is never automated." Codifying it once (`contract/OVERSIGHT-CONTRACT.md` §6.0) means a new fixer agent inherits the boundary instead of approximating it — and the approximations are where the escapes live.

## Provenance

Surfaced when the Opus self-validator escalated a blocking finding at the 3-pass cap: `doc-validator` was documented as a fixer ("applies fixes directly, has Write access") but its frontmatter granted no write tool — so doc omissions had no agent that could both detect and apply the fix. The human decision was to make it a real fixer under an explicit triage rather than a reporter, which prompted codifying the triage as a shared rule (§6.0) instead of a per-agent instruction. See `DECISIONS.md` D35. Related: `ratchet-principle.md`, `self-classification-cannot-gate-the-human-boundary.md`.
