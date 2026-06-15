# Finding: A guard that records an error but doesn't halt is not a guard — it's a comment

**Role:** framework-installer — the `--pr` safety path's "guard" printed a refusal, then executed the thing it refused

**First observed:** 2026-06-15, the CPS v0.3.0 upgrade prep (#272, fixed in v0.3.1)

---

## The finding

`hos_install.sh --pr` promises the safe, reversible upgrade path: apply the change on a new branch, open a PR, leave the consumer's base branch untouched. When PR setup failed, the code did this:

```sh
fail() { err "$*"; ERRORS=$((ERRORS + 1)); }   # prints, counts — does NOT exit
...
elif [[ "$PR_MODE" == "on" ]]; then
  fail "--pr requested but not possible: $_pr_why. Resolve it, or use --no-pr."
fi
# ... execution continues, and scaffolds the upgrade IN PLACE ...
```

The line *reads* like a guard: an explicit check, a refusal message naming the exact problem. But `fail()` doesn't exit — it increments a counter inspected only at end-of-run. So the script printed "I refuse to do this," then **did it anyway**, mutating the consumer's working tree in place, and reported the error *after* the writes were on disk. The control flow contradicted the message. A consumer who asked for the safe path got the unsafe one, with a reassuring error in the log.

## Why it matters for scalable oversight

This is the **fail-open** failure mode wearing fail-closed's clothes — the most dangerous kind, because it passes a casual read. A reviewer (human or AI) scanning for "is the `--pr`-impossible case handled?" sees a named check with a refusal string and ticks the box. The defect lives entirely in a property *not visible at the check site*: whether `fail()` halts. You cannot judge a guard by what it prints; you can only judge it by what executes next.

For a system whose entire purpose is overseeing change safely, an installer that silently performs an unrequested, irreversible in-place mutation is the worst possible bug — it violates the one promise (`--pr` = reversible) the consumer relied on, in the one tool (the installer) that touches their code directly. The blast radius is "every consumer who hit an ineligible state while trying to be careful."

The rule: **a safety guard must terminate the unsafe path before any irreversible action, and the termination must be local and unmistakable (`exit`/`return`/`raise`), not a flag a distant epilogue might honor.** A deferred error counter is fine for *accumulating* non-fatal warnings; it is never the mechanism for *preventing* a specific dangerous action.

## The mechanism (the fix)

- Under explicit `--pr`, every pre-scaffold PR-setup failure (ineligible repo, branch-creation failure) now `err …; exit 1` — a hard stop *before* the first filesystem write, so nothing is mutated. `--pr` means PR-or-nothing; no in-place fallback exists when it was explicitly requested.
- Post-scaffold push / PR-create failures keep using the deferred-error path (`fail`) — and that is *correct* there, because at that point the work is isolated on a branch and the base is untouched; the only thing wrong was a false exit-0, which `fail` (exit ≠ 0 at end) fixes.
- The distinction is the whole lesson: `exit` where an irreversible action would otherwise follow; counter where the damage is already safely contained and you only owe an honest exit code.

## The trap it avoids

"There's a check for that" is not the same as "that can't happen." A check that detects the condition but doesn't *stop* on it is strictly worse than no check, because it manufactures false confidence — in the log, in code review, and in the next engineer who greps for the guard and moves on. When auditing fail-closed behavior, never stop at the guard's existence or its message; trace the next executed statement on the failure branch and confirm it is a halt.

## Provenance

Observed 2026-06-15 while writing the runbook for a real consumer's `--pr` upgrade to v0.3.0; the human flagged it immediately ("--pr means PR. If it can't do a PR, it fails. Don't F up the customer's code") and called it a ship-stopper. Fixed in v0.3.1 on the `release/v0.3.x` patch line; recorded as DECISIONS.md D46. Related: `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` (the override path's integrity) and `unenforceable-rules-need-verification-mechanisms.md` (a rule with no enforcement is a suggestion — here, a guard with no halt was exactly that).
