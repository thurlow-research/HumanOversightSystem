# Finding: A Reviewer Can Over-Apply a *Real* Quality Rule Beyond Its Spec'd Scope — 3 False Blockers to 1 True

**Role:** oversight-mechanism — a distinct failure mode of agent review, and fresh justification for verify-before-fix on the *citation*, not just the *claim*.

**First observed:** 2026-06-15, building HOS v0.3.0's base-agent team *with* HOS (the #176 dogfood). The new `code-reviewer` agent — itself a freshly-authored base-team core — reviewed the 16 base-agent CORE files against their spec.

---

## The Finding

The `code-reviewer` returned **REQUEST CHANGES** with four "blocking" findings. On verification against the spec each cited:

| Finding | Verdict |
|---|---|
| **B1** — every reviewer sign-off CORE dropped `CONDITIONAL` from the `Status:` enum | **TRUE** — spec §A6's canonical entry is literally `APPROVED \| ESCALATED \| CONDITIONAL \| N/A`. Precise, correct, real (10 files). |
| **B2** — `pm-agent` is missing the §A8 5-round cap | **FALSE** — §A8's iterating-role list is *"coder + all reviewers + test roles + design roles that iterate"*; pm-agent is omitted **on purpose**. Its flow is a single batched Q&A then *immediate* escalation, not a rounds-based convergence loop. |
| **B3** — `coder` is missing the §A8 loop temp-state file | **PARTIAL** — the coder *is* listed in §A8 and has the cap; its loop state is externalized to the reviewer temp files it reads (§A8's path table names no coder file). Closed with one clarifying clause, not a redundant file. |
| **B4** — `technical-design`'s routing hub has no round cap | **FALSE** — TD's *iterating* loop (architect critique) **is** capped + temp-stated; the routing hub is a single-pass router (revise-and-notify, or re-route), not a convergence loop. |

**Net: one true blocker, three false — and all three false ones share a single root cause:** reading §A8's *"iterating role"* too broadly, treating immediate-escalate (B2), externalized-state (B3), and single-pass routing (B4) as capped convergence loops that the spec's own enumeration and path table deliberately scope out.

## Why This Is a Distinct Failure Mode

This is **not** the non-reproducing-report failure (`reviewer-agents-file-confident-non-reproducing-reports.md`), where the cited defect doesn't exist. Here the rule (§A8) is real and the reviewer's knowledge of it was sound — it mis-judged the rule's **scope of application**. The defect is in the *citation→applicability* step, not the *claim*. That distinction is operationally load-bearing:

- A wrong **claim** is caught by re-reading the *code* ("does this bug reproduce?").
- A wrong **scope** is caught only by re-reading the *spec clause itself* ("does §A8 actually bind this role?"). Trusting the citation because the rule is real is exactly the trap.

## The self-checking asymmetry (the interesting part)

The same review **self-retracted** its *surface* errors mid-analysis — it recounted reviewer-lane lists (its initial B5/B6) and corrected them in place. But it did **not** self-correct the deeper *conceptual* scope-overreach (B2/B3/B4). Mechanical self-checking (recount, re-grep) worked; the judgment-level "does this rule even apply here?" check did not fire. A reviewer's visible rigor on the easy axis is **not** evidence of rigor on the hard one.

## Process correction it reinforces

Verify-before-fix (already standard from `reviewer-agents-file-confident-non-reproducing-reports.md` and the CPS-test false field reports) is here extended explicitly to **spec-citation findings**: when a review blocks on "violates §X", the orchestrator must read §X's *scope clause* (its enumeration, its path table, its "applies to…" list) and the target role's actual control flow — **not** accept the citation because §X exists. Had we mass-applied all four "one-line" blockers, we would have added a runaway-loop cap to a role that escalates immediately (B2), a redundant temp file duplicating the reviewer files (B3), and a cap to a single-pass router (B4) — three plausible-looking edits that degrade the cores. The cost of skipping the spec re-read is *negative* work that looks like diligence.

It also names a spec-hardening item: §A8's iterating-role **enumeration is the authority** and is deliberately narrow; the omission of pm-agent / coder-owned-file / TD-routing-hub is intentional and should be stated as such so the same false positive isn't re-raised on the next review.

## The dogfood angle

The reviewer here was the product's own newly-authored `code-reviewer` core, reviewing the product's own base team. The 3:1 false:true ratio on *blocking* findings, from one capable agent on its first real outing, is direct evidence for the methodology's claim that **agent review is a strong-but-not-sufficient signal that must clear an independent verification step before its findings drive edits** — the same lesson the gates-vs-review split teaches one layer down.

## Related findings

- `reviewer-agents-file-confident-non-reproducing-reports.md` — the *claim* is wrong (vs. here, the *scope* is wrong).
- `gates-and-review-are-complementary.md` — agent review is one fallible signal among layers.
- `orchestrator-absorbs-roles-pipeline-bypassed-by-default.md` — the inverse risk: an orchestrator that *rationalizes away* real findings to avoid work. Verify-before-fix must cut both ways — reject false blockers *with spec citations*, never by hand-wave.
