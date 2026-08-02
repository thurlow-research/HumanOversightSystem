# Session: Tracing the Triage Mechanism, and the Drift It Uncovered

**Date:** 2026-08-02
**Role:** Human-proxy orchestrator (interactive), Human clone
**Duration:** ~2.5 hours
**Artifacts:** 12 issues filed (#1191–#1208), 1 closed as not-planned, 1 corrected

---

## What this session was

It began as a single question — *"the worker is doing the triage; where is it getting its instructions?"* — and ended with eleven open issues, most of them about controls that were not doing what they were believed to do.

No code was written. This was a diagnostic session; the output is issues, decisions, and the findings extracted alongside this log.

---

## What was built

Nothing shipped. Twelve issues were filed:

| # | Milestone | Subject |
|---|---|---|
| #1191 | v0.6.0 | `revoke_app_token.sh` — token revocation is structurally unallowlistable without it |
| #1192 | v0.6.0 | Committed read helper for issue/milestone queries |
| #1193 | v0.6.0 | Retire v0.5.1 as a triage target — the stale taxonomy |
| #1194 | v0.6.0 | Worker Step 0 records *why* it triaged as it did |
| #1195 | v0.7.0 | Operator dashboard — design loop first |
| #1196 | v0.6.0 | Remove the idle backoff; 10-minute deterministic work check |
| #1198 | v0.6.0 | Worker throughput serialised behind human merge |
| #1200 | v0.6.0 | Report clone drift loudly at session start |
| #1201 | v0.6.0 | Sync the Human clone via cron (parked pending #1202) |
| #1202 | v0.6.0 | Clone-sync design — assigned to the human |
| #1203 | v0.6.0 | Manual repair of a partial-pull state |
| #1204 | v0.6.0 | Commit the ad-hoc gh helper scripts |
| #1205 | v0.7.0 | Overseer requests Copilot review above a risk threshold |
| #1206 | v0.6.0 | Enable `required_review_thread_resolution` |
| #1207 | v0.6.0 | Overseer findings are conversation comments, not review threads |
| #1208 | — | **Closed not-planned** — bespoke disposition enforcement |

---

## Key decisions and the reasoning behind them

### Worker-driven triage is the default; override is the exception

The session opened by treating the worker's auto-triage as a hazard to be raced — file an issue, then set its milestone before the next cron cycle claims it. **That was backwards.** The human's position: worker triage is the system working as designed; human override is reserved for genuine urgency.

That inverted the fix. The problem was never that the worker triages; it was that the *criteria* it applies were stale. #1181 (`--milestone` on `create_issue.sh`) is the override path, not a remedy.

### The v0.6.0 test is "impacting ongoing work", not subject matter

Articulated mid-session and sharper than the written criteria. A topic-based table mis-routes issues whose topic and urgency point at different milestones — #1194 is *shaped* like autonomous-worker finalisation (v0.7.0) but is costing time now (v0.6.0).

### Sync the clone out-of-band rather than loosening the sandbox

Two prior sessions had disagreed about whether `Edit(./bin/**)` should exist. One said remove it (it breaks git); the next added it (it protects `bin/`). The disagreement dissolved once a third option appeared: **a cron job runs outside the sandbox**, so a trusted non-agent process can update the protected paths while the agent still cannot touch them.

The protection is kept in full; only its "and therefore can never be updated" side effect is removed. Recorded so the debate is not reopened.

### Leverage GitHub's native review roles rather than inventing authority rules

An early design tried to stop the overseer resolving the findings it raised — since it also holds merge authority, it would own both ends of the loop. The proposed remedy was a bespoke rule.

Mapping onto the platform's existing roles removed the need entirely: **worker = author (resolves), overseer = reviewer (approves).** Separation of duties by construction.

### Required thread resolution is a forced-*acknowledgement* control

Initially recorded as "stricter than human practice — removes the reviewer's judgement." **Wrong.** It does not constrain the outcome: the author may resolve without changing anything and still merge. It constrains *attention*. Resolution guarantees the author looked; approval guarantees the reviewer accepts the disposition. Two orthogonal instruments, not one stronger gate.

### Do not build a bespoke control for silent resolves — closed #1208

Having established that a silent resolve conveys nothing, the obvious next step was to build detection and withhold approval on it. The human declined, and was right: the overseer re-reviews the diff anyway and can simply withhold approval. Building detection would have required a GraphQL carve-out from the standing REST-only rule — **a cost that was a signal, not an obstacle to route around** — and would have contradicted the leverage-the-native-workflow principle decided moments earlier.

---

## Surprises

**The triage mechanism was a prompt file.** The prior handoff recorded milestone auto-assignment as "an unknown mechanism — nobody set them." It was Step 0 of `bootstrap/worker-cron-prompt.md`. Invisible to code search; absent from the dependency graph; unattributable in the audit trail.

**The stale criteria were stale in the canonical doc too.** The prompt duplicates `docs/planning/README.md`'s taxonomy twice — but all copies *agreed*. De-duplication alone would have changed nothing. The duplication was a maintenance bug; the staleness was the behavioural one. Separating them mattered.

**The clone could never sync itself.** `git pull` fails on `bin/**` and `.claude/agents/**` (read-only at the kernel sandbox layer), and the session-start sync is "best-effort, non-blocking" — so it had failed silently every session. Found at **8 commits behind**, discovered only because a line-number citation looked wrong.

**An attempted repair made it worse.** The pull rewrote the seven files it could and aborted, leaving HEAD unchanged and the tree mismatched — requiring a terminal outside the sandbox.

**`main` is governed by a ruleset, not branch protection.** `GET /branches/main/protection` returns 404 "Branch not protected". A reasonable check yields a confidently wrong answer.

**The documented human gate was never enforced.** `METHODOLOGY.md` lists "PR thread resolution → human gate" in the outer loop. `required_review_thread_resolution` was `false`.

**And enabling it would not have covered the overseer.** It posts findings as PR *conversation* comments; the setting gates *review threads*. The flag would have read as active while missing the most prolific automated source of findings on every PR.

---

## Learnings about the methodology

**Three confidently-written claims were falsified in one session**, each with a plausible conclusion resting on wrong reasoning:

1. "`Edit(./bin/**)` is partial — Bash can still write there." It cannot; the block is at the kernel layer.
2. "Removing the idle backoff eliminates a 30-minute latency." An inter-role wakeup ping-pong meant the backoff never bit while work flowed.
3. "Required thread resolution removes the reviewer's judgement." It constrains attention, not outcome.

In all three the *recommended action* stayed roughly right, which is why they survived review — and each had already been written into a handoff, where the next session would have inherited the reasoning rather than re-deriving it.

**Most of the session's findings share one shape:** a control that reports success, or reports nothing, while not doing what it is believed to do. None was detected by the mechanism that owned it; each was found incidentally, by following an unrelated thread.

Five such findings in a single session, all by accident, suggests the discovered set is a **sample, not a census**.

**Construction beats configuration at the permission boundary.** The same operation — mint, query, revoke — produced an unallowlistable prompt inline, and ran ~20 times with zero prompts once moved verbatim into a script invoked with literal arguments. Two discipline failures occurred before that lesson took (a token printed into the transcript; a chained command with `$GH_TOKEN`, `source`, and `cd`).

---

## Artifacts produced

- 12 issues (#1191–#1208), all milestoned and verified after filing
- #1185 corrected with the measured sandbox result
- `.claudetmp/HANDOFF.md` rewritten
- Findings extracted alongside this log — see `research/findings/`
- Five ad-hoc gh helper scripts under `/tmp/claude/`, attached as prototypes to #1204

## Follow-ups owed

- #1203 (repair) and #1206 (ruleset flag) are admin actions requiring a terminal outside the sandbox
- #1202 awaits a design handoff from the human, then the pm → architect → technical-design loop
- Line references filed this session were read from a tree 8 commits stale; verify before implementing
