# Finding: A standing autonomous worker re-does already-merged work unless a pre-PR guard re-derives what is already in main

**Role:** both — a software-quality benefit (no duplicate PRs) whose research weight is a failure mode unique to the *unattended* loop

**First observed:** 2026-06-24, autonomous worker producing stacked/redundant branches (HOS#850, #880)

---

## The finding

The unattended worker, running cycle after cycle without a human between runs, branched from a working tree that already contained commits absorbed into `main` (or into a sibling open PR that had not yet merged). The result was **stacked-branch duplication**: a new PR whose diff re-applied changes already shipped, because nothing in the loop re-checked, at PR-open time, whether the work it was about to propose was already done.

This is `working-state-invariant.md` projected onto the *git history* across cycles instead of the file tree within a cycle. A human developer re-bases before opening a PR and notices "oh, this is already in main"; the autonomous loop has no such reflex and no human turn in which to acquire one — it trusts its local branch state as authoritative the same way a capable agent trusts its own self-report (O1). It is also a clean instance of O9 (*the agent behaves like a human dev given the same mandate*) inverted: the failure is exactly the one a human avoids by habit, and the fix is exactly the habit, made into mechanism.

A second-order version of the same root cause: the worker committed the **append-only audit log** (`audit/oversight-log.jsonl`) onto a feature branch, shifting the PR HEAD past the validator artifact's recorded `head_sha` and tripping the overseer's freshness gate (§3b) — the recorder's own writes invalidating the recorded set again (`the-recorder-must-not-be-in-the-recorded-set.md`), here surfacing through the autonomous loop's branch hygiene.

## Why it matters for scalable oversight

A standing autonomous producer accumulates state *between* runs that a human-in-the-loop process never does, and that state can silently diverge from the source of truth (`main`). The oversight implication: **before an autonomous agent proposes work, it must re-derive whether that work is already done, from the authoritative history — not assume its local branch is the current frontier.** "Is this new?" is a question the loop must answer mechanically and fail-closed on, because the loop has no human turn in which the question is asked naturally. This is the same shape as the convergence ledger (`convergence-ledger-must-persist.md`): the autonomous loop's correctness depends on comparing its proposed output against durable shared state, never against its own ephemeral local view.

## The mechanism (the fix)

- `stale_commit_detector.py` + a pre-PR guard (`pre_pr_stale_check.py`) run before every PR open:
  - `git cherry` patch-id matching detects commits already absorbed by `main` (catches cherry-picks and direct stacks, not just identical SHAs);
  - a SHA-overlap check against all open PRs via the REST API handles the in-flight sibling-PR case before it merges;
  - redundant commits are stripped by rebasing HEAD onto `main` (rebase's patch-id logic naturally drops already-applied diffs), and a `pre-pr-stale-commits` audit event is emitted so the catch is loud, not silent.
- The audit-log guard exits 1 if `audit/oversight-log.jsonl` or `audit/overnight-loop-log.md` is committed to a non-`main` branch (compared against `origin/{base}` to avoid stale-local-ref false positives); the audit trail is instead synced to a dedicated `audit-log` branch (#861), keeping the recorder out of feature diffs entirely.
- The overseer's §3b staleness check moved from exact `head_sha == PR_HEAD` equality to an **ancestry-based** test (artifact commit is an ancestor of PR HEAD and no non-exempt files changed since), making it immune to non-code tail commits while still failing for genuinely stale artifacts.

## Provenance

Observed and fixed across 2026-06-24 in the autonomous loop: HOS#850 (pre-PR stale-commit guard, 33 unit tests) and HOS#880 (audit-commit guard + ancestry-based §3b check). Related: `working-state-invariant.md` (the within-cycle analogue), `ai-agent-scope-drift-mirrors-human-dev-behavior.md` / O9 (the agent reproducing a human dev's failure mode), `the-recorder-must-not-be-in-the-recorded-set.md` (the audit-commit second-order cause), `convergence-ledger-must-persist.md` (correctness via comparison to durable shared state).
