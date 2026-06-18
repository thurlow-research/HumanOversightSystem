# Agent Misses PR Feedback Without Explicit Full-Review Read

**Source:** Observed during v0.4.0 PR cycle, 2026-06-18  
**Issues:** #411, #414

## Observation

The worker agent checked PR mergeability (`mergeable: CONFLICTING`) but did not read review bodies, review states other than APPROVED, or PR comments. This caused:

- PR #410: Overseer left a request to update validation stamps → worker waited 2+ hours without acting
- PR #413: Overseer filed REQUEST_CHANGES to split the PR (36 files → ≤25 per PR) → worker waited and missed it repeatedly

**Both failures had the same root cause:** Step 0 only checked `mergeable` status. It did not read `reviews[*].body`, `reviews[*].state == CHANGES_REQUESTED`, or `comments[*].body`.

## Pattern

The worker knew to check for conflicts (`mergeable: CONFLICTING`) because that was explicitly in the instructions. But CHANGES_REQUESTED reviews and action-required comments were not listed — so the worker didn't check them.

**Key insight:** A loop operating on shared artifacts (PRs) must actively poll ALL state dimensions, not just the ones that feel "obviously relevant." An agent defaults to the narrowest interpretation of "check the PR" that satisfies the surface-level instruction.

## Fix applied

Updated `worker.md` and issue #407 to explicitly require:
1. Read `statusCheckRollup` — any FAILURE → investigate
2. Read `reviews[*]` — read the BODY for all reviews regardless of state
3. Read `comments[*]` — read all non-worker comments for action requests
4. If CHANGES_REQUESTED or action-required comment: address IMMEDIATELY before other work

## Broader lesson

An autonomous agent loop must be given an explicit exhaustive list of what to check, not a conceptual description ("check the PR"). The gap between "what the human thought the agent would check" and "what the agent actually checked" was precisely the set of things not explicitly enumerated.

This is the same failure mode as the "silent no-op PASS" bug (#358) — the agent does the minimum interpretation that satisfies the instruction surface, not the maximum interpretation that serves the intent.
