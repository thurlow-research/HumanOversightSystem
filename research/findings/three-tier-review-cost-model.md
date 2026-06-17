# Finding: Expensive Cross-Vendor Review Should Run at Transition Points, Not at Every Change — the Three-Tier Model

**Role:** oversight-mechanism — deployment economics of multi-vendor AI code review

**First observed:** 2026-06-16, session `2026-06-16-v040-unattended-worker.md` (issue #356, decision)

---

## The Finding

Running expensive vendor AI review (agy, codex, Copilot) on every code change is not viable at scale. Running it only at release creates a large batch of unreviewed work that the panel must process at once. The correct model is a three-tier structure that matches the cost of review to the significance of the transition:

| Tier | Trigger | What runs | Vendor cost |
|---|---|---|---|
| **Inner loop** | Per code change | Deterministic validators + reviewer agents | None |
| **Pre-PR** | Before opening a PR | Cross-vendor second review (agy at MEDIUM+, codex at HIGH+) | Low–Medium |
| **Release gate** | Per phase/release | Full panel (agy + codex + Copilot) | High |

The key insight: vendor model calls should be gated by **transition significance**, not by change frequency. A per-change vendor call burns budget on every typo fix; a release-only call lets months of work accumulate unseen. The "transition" model — pay for vendor review when work crosses a significant boundary (PR submission, release) — gives coverage without waste.

The pre-PR second review (run_second_review.sh) prevents debt accumulation: issues are caught at the PR boundary, not in a large batch at release. The release-gate panel is the final integrated check on the full phase diff — it sees combinations of changes that per-PR review could not.

## The Configurability Principle

The tier at which a reviewer fires should be configurable (per-repo, per tier) not hardcoded. A LOW-tier change probably doesn't need agy review before the PR; a HIGH-tier change might want the full panel per-PR, not just at release. The scripts (`run_review_chain.sh --tier MEDIUM`, `run_panel.sh --pr N`) provide this configurability. The default is the right starting point; operators tune based on their risk tolerance and budget.

## Why This Generalizes

Any system that uses expensive stochastic reviewers faces the same tension:
- Too frequent: cost prohibitive, disrupts the development flow, reviewers see noise
- Too infrequent: findings arrive too late to fix cheaply, debt accumulates

The three-tier model resolves this by observing that code review value is highest at *transition points* — moments where work moves from one phase to another (in-progress → PR, PR → release). Reviews at transition points are proportionate to the significance of the transition. Reviews at every commit are not.

This is the same insight as "shift left" in testing: finding a bug before it crosses a boundary is cheaper than finding it after. The tier model applies shift-left to the expensive AI review layer: shift vendor review to the PR boundary (cheaper than release-only) while keeping the release gate for final integrated verification.

## Evidence

- HOS v0.4.0 planning session (2026-06-16): confirmed three-tier model after iterating through per-PR panel (too expensive), release-only panel (too infrequent), and pre-PR second review (right balance)
- `run_review_chain.sh` implements the pre-PR tier: validators → agy (MEDIUM+) → codex (HIGH+) → open PR
- `run_panel.sh` implements the release tier: full panel on phase-review PR once per phase

## Implications for Research

1. **Review tier design is a first-class architectural decision.** "When does expensive review run?" should be in the system architecture, not an afterthought. The answer shapes development rhythm, cost structure, and debt accumulation patterns.

2. **Transition points are the natural review boundaries.** The moments when work crosses between actors (developer → reviewer, work → release) are where quality gates provide the most leverage. Reviews between those transitions are waste; reviews at them are investment.

3. **Batching panel calls to release does not reduce total review coverage.** It concentrates coverage at the right moment (before the work goes to users) while removing coverage at low-value moments (individual commits). The total number of issues caught does not decrease if the panel is well-placed.

## Related findings

- `cost-gating-autonomous-oversight-loops.md` — the related finding that standing autonomous loops must gate on work-found before invoking a model; this is the review-tier-specific instance
- `gates-and-review-are-complementary.md` — deterministic gates catch mechanical failures; vendor review catches semantic failures; the two tiers are complementary, not substitutes
