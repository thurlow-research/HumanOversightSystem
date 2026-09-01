# Finding: a closed policy without a mechanical signal is remembered discipline, not enforcement

**Role:** oversight-mechanism — the shell-vs-Python instance of "the rule existed, was correct, and simply was not run"

**First observed:** 2026-08-03, verification pass against `main` for #314 (HOS#1241)

---

## The finding

#314 ("policy: prefer Python for logic, shell for launch — establish testability as a code
review criterion") was closed with four acceptance criteria. Three of the four were never
delivered: `code-reviewer.md` carried no such criterion, `METHODOLOGY.md` carried no such
principle, and no validator existed to detect shell scripts carrying decision logic. Only
the informal, one-off "CPS coder is informed" item — unverifiable and non-mechanical by
construction — had actually happened.

The policy was nonetheless *treated as settled* in the meantime: #1167 cites it as given,
#1174 describes conversion work it motivated. A closed issue with an unenforced rule reads,
to everyone downstream, identically to a closed issue with an enforced one — there is no
signal that distinguishes "this is now true of the codebase" from "this was agreed and
nothing acted on it."

## Why it matters for scalable oversight

This is the same failure mode recorded in
[`gate-on-computed-signal-not-self-reported-verdict.md`](gate-on-computed-signal-not-self-reported-verdict.md)
and
[`unenforceable-rules-need-verification-mechanisms.md`](unenforceable-rules-need-verification-mechanisms.md),
one level up: there a *gate* trusted a self-reported verdict instead of the underlying
findings; here the *governance process* trusted an issue's closed state instead of checking
its acceptance criteria against the tree. Closing an issue is itself a kind of self-report —
"this is done" — and it is exactly as unreliable as any other self-report when nothing
re-derives it from the artifacts.

The fix delivered here (HOS#1241) follows the established pattern precisely: a prose
criterion in `code-reviewer.md` (a human/agent-legible rule) *plus* a deterministic validator
(`shell_logic_check.py`, a `quality` signal in the composite score) that computes the same
thing mechanically. The prose alone is what #314 already had and it was not enough — the
validator is what converts "the reviewer should catch this" into "the pipeline measures it
on every diff that touches shell."

## The carve-outs are load-bearing, not decoration

A validator for this class of rule fails in the *opposite* direction if it is naive: flagging
every `if` in every script would bounce `bootstrap/hos_bootstrap.sh` (which must be shell — it
installs the Python the policy wants everything else written in) and the canonical fixed-flag
parsing loop (`while [[ $# -gt 0 ]]; do case "$1" in ... esac; done`) that nearly every
`bootstrap/*.sh` entry point uses precisely *because* the sandbox's allowlisting requires a
fixed argv shape (`CLAUDE.md`, "Shell usage under the sandbox"). A mechanical check that
punishes the pattern the sandbox itself requires would train the next contributor to route
around the validator instead of the underlying policy — the same "quietly routed around"
failure `CLAUDE.md`'s "Failing safely" section warns against, just self-inflicted by the
check instead of the agent.

## Provenance

Filed from a human-proxy session on 2026-08-03 (#1241), with the concrete criteria and
carve-outs supplied by human ruling on 2026-08-13/2026-08-14 (see #1241 comments).
Implemented 2026-09-01: `code-reviewer.md` CORE criterion, `METHODOLOGY.md` principle +
validator table row, `shell_logic_check.py` validator, wired into `run_validators.sh` and
`schema.py`. Generalizes
[`gate-on-computed-signal-not-self-reported-verdict.md`](gate-on-computed-signal-not-self-reported-verdict.md)
(compute, don't trust a self-report) to the governance-process layer: a closed issue's
acceptance criteria are as much a claim to verify as a reviewer's summary verdict. Relates to
#1123 (documentation-reality drift) — a general mechanism to catch *any* closed issue whose
acceptance criteria never landed is that issue's scope, not duplicated here; this finding is
one confirmed instance of the class it targets.
