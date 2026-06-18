# Validation Stamp Commit Anchoring Causes Merge Conflict Cascade

**Source:** Observed in practice during v0.4.0 PR series, 2026-06-18  
**Issue:** #422

## Observation

HOS uses committed validation stamps (`scripts/framework/validation-stamps/all-phases.stamp`) as CI gate anchors. The CI check (`check_validation_current.sh`) reads the git commit timestamp of the stamp and verifies it is newer than all changed files' commit timestamps.

**The cascade:** When multiple PRs are open simultaneously:
1. Every PR commits a stamp with a unique timestamp
2. Every merge to main updates main's stamp
3. Every subsequent merge immediately conflicts all other open PRs' stamps
4. Resolving one conflict produces another — the cascade is structurally unavoidable with the current design

In the v0.4.0 series (8 PRs open simultaneously), this required ~15 rounds of manual conflict resolution, repeated approval dismissals (via `dismiss_stale_reviews`), and re-approvals. Total overhead: >2 hours of wasted human and worker time.

## Root cause

The stamp anchoring mechanism conflates two concerns:
- **What was validated** (content: which phases ran, when)
- **When it was validated relative to the code** (timing: commit timestamp comparison)

Using a shared tracked file for this creates a write-conflict surface proportional to the number of concurrent PRs.

## Temporary workaround

Stamp directory added to `.gitignore`; CI check modified to skip (exit 0) when untracked. This eliminates conflicts but disables validation enforcement entirely.

## Design options (see #422)

| Option | Description | Trade-off |
|--------|-------------|-----------|
| A | Branch-scoped stamp paths (`validation-stamps/<branch>.stamp`) | Eliminates conflict; proliferation cleanup needed |
| B | SHA-anchored stamp (records HEAD SHA, not timestamp) | No timestamp comparison; no conflict; requires check redesign |
| C | PR metadata field (not a tracked file) | No git conflict; requires CI infrastructure change |

## Lesson for HOS design

CI artifact anchoring must account for concurrent PR workflows. A single shared tracked file is appropriate for sequential (one PR at a time) workflows but fails at scale. Stamp anchoring should use branch-scoped or PR-scoped artifacts, or anchor to immutable git object SHAs rather than mutable file timestamps.
