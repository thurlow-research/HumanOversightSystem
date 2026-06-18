# PR Size Policy

*Authoritative source for PR size limits referenced by `worker.md` and `overseer.md` (CORE). Applies to all PRs opened by HOS agents. (#450)*

---

## The limits

| Metric | Recommended | Hard ceiling |
|---|---|---|
| Files changed | ≤ 15 | 25 |
| Commits | ≤ 10 | — |

**Recommended limit (15 files / 10 commits):** the range where PRs review fastest without causing reviewer fatigue. Empirically, 8–11 file PRs receive the most thorough feedback; above 15, review quality degrades measurably.

**Hard ceiling (25 files):** above this threshold, merge conflicts compound faster than reviews complete. The worker must split before opening a PR; the overseer bounces unconditionally without attempting review.

---

## Rationale

These numbers are derived empirically from this project's review history, not from a theoretical model:

- PRs in the 8–11 file range receive complete, high-quality feedback in the shortest elapsed time.
- PRs in the 12–15 file range are still reviewable but require more reviewer context-switching.
- PRs with 20+ files consistently cause reviewer fatigue — findings cluster in the first few files and tail off in later ones, creating a systematic coverage gap.
- Above 25 files, rebasing and merge-conflict resolution routinely consume more time than the review itself, producing a net negative for delivery velocity.

The commit ceiling (≤ 10) keeps history readable and rebases manageable. A long commit list also makes bisection harder when a regression is introduced.

---

## How to split a large PR

When a planned change would exceed 15 files, split by logical sub-group and open sequential PRs. Common split axes:

| Axis | Example |
|---|---|
| **Layer** | docs / lib / tests |
| **Feature area** | auth changes / data model changes / UI changes |
| **Type** | migrations / application code / configuration |
| **Phase** | scaffolding (new files, no logic) / implementation / cleanup |

**Rules for sequential PRs:**

1. Each PR must be independently reviewable — it must not leave the codebase in a broken state.
2. Open PRs in dependency order (foundation first, consumers after).
3. Each PR title and description must state its position in the sequence: "Part 1 of 3 — …".
4. Reference the related PRs in the description so reviewers have context.

**When a split is genuinely impossible** (a single atomic migration + its application code, for example), file a `needs-human` issue explaining why the change cannot be split and await explicit human authorization before exceeding the limit.

---

## Enforcement

- **Worker (both modes):** does not open a PR that would exceed 15 files or 10 commits without first splitting. See `worker.md` CORE "What you do NOT do."
- **Overseer (autonomous mode):** upon reading PR state, checks file count and commit count before applying the merge-authority matrix. PRs exceeding 15 files or 10 commits receive a "request changes" response with a suggested split. PRs exceeding 25 files are bounced unconditionally. See `overseer.md` CORE step 3a.
- **Human gate:** the limits do not prevent a human from merging a large PR when explicitly authorized. Human authorization overrides the agent-level enforcement (but not the intent of the policy).

---

*Last updated: June 2026. Derived from review-history analysis in this project. Revisit if project velocity or team size changes significantly.*
