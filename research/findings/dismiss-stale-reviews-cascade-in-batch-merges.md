# Finding: `dismiss_stale_reviews_on_push` Creates a Cascade in Autonomous Batch Merges

**Role:** oversight-mechanism — reliability of autonomous merge sequences

**First observed:** 2026-06-16, CPS overnight run; issue #322

---

## The Finding

When multiple PRs target the same base branch and `dismiss_stale_reviews_on_push: true` is active in branch protection, merging any one PR advances the base branch. GitHub treats this advance as "new commits" on all sibling PRs and automatically dismisses their existing reviews — including any approval the overseer posted in the same cycle.

In a high-cadence autonomous batch merge this creates a re-approval cascade: the overseer approves PRs A, B, and C, merges A, and then finds that its approvals on B and C have been silently dismissed. Naively retrying the merge call for B will fail branch protection. Reposting approvals without re-running the tier-ceiling CI check posts an approval against a stale check state.

The fix is **not** to disable `dismiss_stale_reviews` — that is a security regression that allows prior approvals to persist across new commits, defeating the forge-proofing guarantee documented in `actor-identity-vs-determination-honesty.md`. The fix is to serialize merges and re-approve each PR immediately before its merge, after the tier-ceiling CI check has re-passed for that PR against its current base.

## Evidence

- CPS overnight run 2026-06-16 — the batch merge loop stalled after the first merge because GitHub dismissed overseer approvals on the remaining PRs in the queue.
- GitHub API behavior: `PUT /repos/{o}/{r}/pulls/{n}/merge` succeeds only if all required status checks have passed and the PR has a current (non-dismissed) approval. A dismissed approval is not a current approval.
- Issue #322 filed after the stall was observed and root-caused.

## The Protocol (implemented in overseer.md step 6b)

1. Sort candidate PRs by creation date (oldest first) to produce a deterministic merge order.
2. Before merging PR N, re-read its current reviews (`GET /repos/{o}/{r}/pulls/{n}/reviews`) to check whether the overseer's approval is still active.
3. If the approval was dismissed (as it will be for any PR after the first merge in a cycle), re-approve and wait for the tier-ceiling CI check to re-pass before issuing the merge call.
4. Merge PR N (squash). Log to ledger.
5. Proceed to PR N+1, returning to step 2 — the base branch just advanced again.

Never merge two PRs simultaneously against the same base branch in one orchestrator cycle.

## Implications

Any autonomous system that merges multiple PRs against the same base branch must choose one of three strategies:

1. **Serialize with re-approval** (the HOS approach): merge one at a time, re-check and re-approve before each merge. Preserves `dismiss_stale_reviews: true`. Adds latency proportional to CI re-run time per PR.
2. **Use GitHub's native merge queue**: enqueue PRs; GitHub handles serialization and re-validation automatically. Requires merge queue to be enabled on the repo and supported by the branch protection config. This is the preferred long-term option for high-volume repos.
3. **Set `dismiss_stale_reviews: false`**: allows stale approvals to persist across base-branch advances. This weakens the security model — an approval granted before a new commit is carried forward without re-evaluation. Do not do this.

The latency cost of option 1 is bounded: each PR waits for one CI run after base-branch advance. For the HOS pilot cadence (single-digit PRs per overnight cycle) this is acceptable. At higher cadence, option 2 is the right migration path.

## Related Findings

- `actor-identity-vs-determination-honesty.md` — the forge-proof approval guarantee that `dismiss_stale_reviews: true` protects; explains why weakening it is a security regression, not a convenience trade-off.
- `working-state-invariant.md` — the broader invariant that the base branch must remain in a known-good state; serialized merges preserve this by preventing concurrent untested base advances.
