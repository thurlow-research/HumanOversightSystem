# Session: 2026-06-13 — CPS pilot triage, overnight backlog, and autonomous-maintainer specs

**Date:** 2026-06-13 (overnight) **Duration:** extended single session
**Theme:** harden HOS against CPS consumer-pilot feedback; set up autonomous overnight work; spec the next design layers.

---

## What was built / done

- **CPS updated v0.1.0 → v0.1.2** via the customer install flow (exercised the #137 install fix end-to-end). Closed CPS #73/#74 (PyYAML gate fix delivered).
- **Decision briefs** posted to the 6 design-gated CPS issues (#20/#38/#47/#63/#65/#66) + `needs-human`, so the human has a fast morning decision queue.
- **`docs/HANDLING-FINDINGS.md`** (#158) — the anti-tail-chasing guide: gates-vs-signal, why validators over-flag by design, the three triage outcomes (fix / accept-with-rationale / `scanner-fp` upstream). Plus CPS guidance issue #82 and `scanner-fp` labels on both repos.
- **#152 spec extended** — `AGENT-IDENTITY.md §5.1` names the actor-identity vs determination-honesty split (relayed from a desktop conversation).
- **Overnight autonomy** — hourly issue loop (`cron 98204cb6`, verify-first) + a 7am self/3p-eval one-shot (`ab9bf7f9`).
- **Backlog pass on the cps-test field reports** — #149 (defensive arg re-split, closed), #150/#155 (non-reproducing, escalated), #157 (real gap → collection-integrity gate, PR #164 held for review).
- **`docs/FABERIX-ROLES.md`** (#167) — autonomous-maintainer roles spec (R1 debt / R2 triage / R3 PR review) + cost-gating + won't-fix→suppression.

## Key decisions and reasoning (won't survive in git)

- **Verify reproduction before fixing any field report.** Adopted into the overnight loop after the discovery below. Editing correct code to chase a report is net-negative.
- **CPS app fixes go through CPS's own pipeline; HOS only auto-merges its own framework fixes.** Overnight autonomy is bounded to where it is safe (HOS), never auto-merging into the consumer or into governance/gate/contract surfaces.
- **Cost-gating is a hard Faberix go-live blocker, not an optimization** (human directive: "OK for tonight, not OK long run").

## Surprises

- **Three of four cps-test field reports did not reproduce** — confident, permalink-backed, and wrong. This was the session's biggest surprise and became its own finding.
- The just-shipped triage discipline (`HANDLING-FINDINGS.md`) immediately prevented two erroneous edits (#149, #150) in the same session it was written.

## Learnings → findings extracted

- `reviewer-agents-file-confident-non-reproducing-reports.md` — the reviewer-hallucination failure mode on the reporting side.
- `actor-identity-vs-determination-honesty.md` — two distinct guarantees; machine accounts close only one.
- `cost-gating-autonomous-oversight-loops.md` — deterministic work-detection must gate model invocation for continuous oversight to be affordable.

## Artifacts

PRs #158 (HANDLING-FINDINGS), #149 fix, #164 (collection gate, open), #152 §5.1, #167 (Faberix spec); CPS v0.1.2 update + issue triage; crons `98204cb6`, `ab9bf7f9`.
