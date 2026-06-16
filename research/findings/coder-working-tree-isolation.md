Title: Coder Subagents Require a Clean Working Tree — Contamination and Rebase Overwrites Are Predictable Without It
Role: oversight-mechanism — correctness of autonomous build chain
Finding: Two predictable failure modes occur when coder subagents are not isolated to clean working trees: (1) uncommitted changes from a prior task bleed into a new task on a different branch; (2) a rebase without a prior pull overwrites commits already pushed to origin by a prior subagent. Both are preventable with two rules: verify clean working tree before each dispatch, and git pull --ff-only before any rebase. These are not edge cases — they are the default outcome when a single working directory is used for sequential subagent dispatches without explicit isolation.
Evidence: CPS overnight run 2026-06-16, issues #323 and #324.
Implications: Autonomous build chains must enforce working-tree cleanliness as a pre-dispatch gate, not as a recommendation. The pull-before-rebase rule should be in every coder spec that uses git rebase.
Related: working-state-invariant.md
