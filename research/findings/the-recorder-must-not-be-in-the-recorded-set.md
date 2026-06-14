# Finding: The recorder must not be in the recorded set — an audit trail can't invalidate the sign-offs it records

**Role:** oversight-mechanism — a self-referential flaw where the act of auditing destroys the thing audited

**First observed:** 2026-06-13, CondoParkShare real-world HOS test run (HOS#112)

---

## The finding

The sign-off gate enforces a freshness invariant: every required sign-off stamp must be newer than every changed source file, so you can't sign, then change code, and still pass. It computes this as `min(stamp_commit_time) >= max(changed_file_commit_time)`.

The bug: the "changed files" set included `audit/oversight-log.jsonl` — the **append-only audit trail the oversight system writes about itself**. `suspension_manager.py` (suspension-census), `run_second_review.sh`, and `oversight-orchestrator` all append to it, and they do so *after* reviewers sign. So the sequence that any normal pipeline produces —

1. reviewers sign (stamps committed at T)
2. the orchestrator appends a step/PR audit event (committed at T+1)

— made the gate compute `max(changed) = T+1 > min(stamps) = T` and declare **all nine sign-offs stale**. The system's own bookkeeping perpetually invalidated the very sign-offs it was bookkeeping. The only way to pass was to re-sign every role as the literal last action — and again if anything appended after.

## Why it matters for scalable oversight

This is a **self-reference flaw**: a monitor that counts its own act of monitoring as a change to be re-monitored. It is the audit-trail analogue of a logger that logs that it logged, forever. For an oversight system the failure mode is specific and bad: the freshness check exists to make "these sign-offs reflect the current code" trustworthy, but by folding the audit log into "the current code," it converts a *successful, fully-signed* step into a *permanently-failing* one. Faced with that, an operator's rational move is to disable or route around the gate — so a self-referential bug in a safety check doesn't just annoy, it actively pushes people to defeat the check.

The general rule: **the artifacts a control writes about a step are not inputs the step must be re-validated against.** The recorder must be excluded from the recorded set — sign-off stamps already were (`signoffs/`); the audit trail and ephemeral agent state (`audit/`, `.claudetmp/`) have exactly the same character and must be too. Sign-off freshness tracks *source* changes, not the system's narration of itself.

## The mechanism (the fix)

- Generalize the single-purpose `is_signoff_path()` (which excluded only `signoffs/`) into `is_oversight_artifact()`, excluding a declared set of oversight-generated prefixes: `signoffs/`, `audit/`, `.claudetmp/`. Apply it in both places the changed-file set is built (the committed-diff path and the dirty-working-tree path).
- **Prefix discipline matters.** Match `audit/` (trailing slash), not `audit` — so `audit_helper.py` and a project's own nested `src/audit/…` source remain in the recorded set. Excluding too much would punch a hole in the freshness check (you could edit a real file under a matching name and the gate would ignore it). The exclusion is for *root* oversight artifacts only.

## The trap it avoids

Two opposite errors bracket the fix. Include the audit log (the original bug) → the control destroys its own passing state and gets disabled. Exclude too broadly (e.g. anything containing `audit`) → real source changes slip past the freshness check unsigned. The correct line is narrow: exactly the root-level artifacts the oversight tooling itself authors, matched as path prefixes so no project source is caught.

## Provenance

Observed 2026-06-13 during the CondoParkShare real-world HOS test: all nine step-7 sign-offs reported STALE after a `suspension_manager.py --census` appended to `audit/oversight-log.jsonl`. Fixed in `signoff_gate.py` by excluding `audit/` and `.claudetmp/` alongside the already-exempt `signoffs/`. Related: `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` and `oversight-gate-must-declare-its-deps-and-fail-loud.md` (sibling oversight-instrument bugs from the same run), `self-governance-recursion.md` (the system applying its controls to itself — here the controls collided with themselves).
