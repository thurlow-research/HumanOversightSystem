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

## Design options (see #552)

| Option | Description | Trade-off |
|--------|-------------|-----------|
| A | Branch-scoped stamp paths (`validation-stamps/<branch>.stamp`) | Eliminates conflict; proliferation cleanup needed |
| B | Content-hash-anchored stamp (filename = SHA256 of validated files) | No conflict; no rebase invalidation; requires check redesign |
| C | PR metadata field (not a tracked file) | No git conflict; requires CI infrastructure change |

## Chosen approach — Option B (content-hash anchoring) (#552)

**Decision recorded 2026-06-19.** Implemented as `#552` in v0.5.0.

Stamp filename = `validation-stamps/phase1-<sha256>.stamp` where the hash covers
all `.claude/agents/*.md` files. The CI check recomputes the current hash and
checks whether that named stamp file is tracked in git.

**Why this eliminates both problems:**
1. **Conflict**: identical content → identical filename → git sees no conflict (both
   branches have the same file). Different content → different filenames → different
   files → no conflict by definition.
2. **Rebase invalidation**: hash depends on file *contents*, not commit timestamps.
   Rebased commits have new timestamps but unchanged content → same hash → same
   stamp filename → stamp still valid.

**Known tradeoff:** Non-agent-file PRs (e.g. pure validator script changes) pass CI
without re-validating agent structure. Accepted as correct — agent structure did not
change. Confirmed by architect before implementation per #552.

**Cleanup:** Old stamp files accumulate as agent content evolves. A step in
`cut_release.sh` removes all stamps except the current one.

## Lesson for HOS design

CI artifact anchoring must account for concurrent PR workflows. A single shared tracked file is appropriate for sequential (one PR at a time) workflows but fails at scale. Stamp anchoring should use content-addressed artifacts: identical content produces identical identifiers, so concurrent PRs validating the same state never conflict, and PRs validating different states produce independent artifacts that coexist without collision.
