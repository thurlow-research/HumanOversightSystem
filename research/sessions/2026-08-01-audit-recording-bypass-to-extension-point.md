# Session note — 2026-08-01: audit recording, from bypass actor to extension point

**Role:** design-chain record — how the audit-to-`main` problem was reframed twice, and what each reframing cost and found

---

## What this session was

A single problem — *how do overseer's audit records reach `main`?* — went through three successive designs in one working session. Each was discarded not because it was wrong on its own terms, but because a better question was asked. The record matters because the discards were the productive part.

## The three designs

**1. Bypass actor (pre-existing, `DECISIONS.md` 2026-06-23).** Grant `hos-auditsync-hos` a branch-protection bypass so audit entries push straight to `main`. Never fully wired. Killed by the human ruling on #873: *"Nobody does direct to main. Ever."* Its real defect was not the open path but that **no code-level check ever ran** — content reached `main` on identity alone.

**2. Approval bot (`ADR-035`).** A dedicated deterministic (non-LLM) identity approves audit-only PRs; a narrow identity-bound exception is added to `require_overseer_approval.py`; one shared tested predicate decides qualification. Substantial: three agent passes, a dual-lens panel, three architect revisions. Discarded after the pivot below made most of it unnecessary.

**3. Extension point (`ADR-036`, current).** Audit recording becomes swappable behind a contract. HOS ships a prototype-grade default (local append → hourly sweep by a distinct transport identity → PR → **overseer approves** → merge to protected `main`); real deployments swap in WORM storage, a SIEM, or an append-only store with real RBAC.

## Why #3 was cheaper than #2, in a way nobody predicted

The pivot was proposed for architectural reasons — stop making git do something git is bad at, define the seam, ship an honest prototype default. The **structural sign-off collapsed as a side effect**.

Because the overseer *approves* rather than authors, `require_overseer_approval.py` is satisfied **natively** — its check is literally "does overseer have an APPROVED review." That deleted the gate exception, the approval-bearing fourth identity class, and the protected-surface modification that had been the largest blocking item in #2. Verified rather than assumed: `require_human_approval` passes N/A (`audit/**` is not protected) and `require_tier_ceiling` computes LOW for an audit-only diff against a HIGH ceiling — with the caveat that this holds only while `OVERSEER_CEILING >= LOW`.

**The lesson worth keeping:** #2 spent its effort designing machinery to satisfy a gate. #3 satisfied the gate by construction and deleted the machinery. When a design's cost is dominated by working around a control, that is evidence the design is fighting the control rather than fitting it.

## What each review layer actually caught

Recorded because the layers found **disjoint** classes, which is the empirical claim `ADR-033`'s dual-lens gate rests on:

| Layer | Found |
|---|---|
| Adversarial (`agy`, cross-vendor) | Six defects *inside* the artifact: GitHub patch-truncation bypass, unrestricted `audit/log/**` glob matching executables, mode/symlink changes bypassing validation entirely, a `+++`-prefixed content line silently skipped by a naive diff parser, no target-branch check, an event-only trigger that couldn't satisfy stuck-PR escalation |
| Completeness (fable-class) | Two HIGH *absences*: no component authored the PR at all (a fully-built approver with nothing to approve), and `overseer.md`'s charter forbade the mechanism's core action |
| `technical-design` (contracting) | The overseer's own review flow fail-closes every audit PR to `HUMAN_REQUIRED` — the mechanism verified at the CI layer, blocked at the agent layer |
| `pm-agent` (contract definition) | The audit log was silently doing double duty as control-flow store and audit-of-record |

**No layer found another layer's class.** The adversarial pass found nothing about other agents' behavior; the completeness pass found nothing about diff parsing. That is n=1 but it is a real design, not a synthetic exercise.

## Corrections made to my own claims during the session

Recorded because the error modes are more reusable than the conclusions:

- **Wrong endpoint, confident conclusion.** I queried `/pulls/{n}/reviews`, saw only human approvals, and stated overseer had not reviewed any human-proxy PR. Overseer *had* reviewed — via issue comments, a different endpoint — reaching `HUMAN_REQUIRED` on protected-surface matches. The human's recollection was right and my verification was wrong. Choosing the wrong verification method produces false claims that *feel* evidence-backed.
- **Stale-base reads.** Twice I read a file from a working tree ~10 commits behind `origin/main` and drew a conclusion that was true of the branch and false of `main` — once causing an unnecessary credential workaround for an already-landed fix. Verify tooling against `origin/main`, not the checkout.
- **Duplicate issue.** I filed #1146 (sandbox hang detection) without searching first; #1053 already covered it, and its `dontAsk` approach largely dissolved the premise. The repo has a finding about the worker doing exactly this (`autonomous-worker-restacks-redundant-work.md`).
- **Milestone counter drift.** The v0.4.0 milestone reported 27 open issues and had 1. GitHub's aggregate counters are not a reliable source.

## Operational discovery, unrelated but consequential

The worker had **zero eligible work** and was idling. `bin/hos-cron` resolves `target_release` to a *single* milestone and `next_candidates.jq` filters to it; the configured target (v0.6.0) had one open issue, not `needs-ai`. All 91 open `needs-ai` issues sat in other milestones, invisible to it. Fixed by rolling the v0.5.1 and v0.4.0 open issues forward into v0.6.0 — 17 → 20 eligible. **Single-milestone targeting means a stale `target_release` silently starves the worker**, and the failure presents as "idle," not as an error.

## State at end of session

`REQUIREMENTS-036` / `ADR-036` (rev 2) / `TECHNICAL-DESIGN-036` complete; `coder` not cleared, blocked only on human structural sign-off. Human decisions bound: producer identity = `hos-auditsync-hos` (*"auditee cannot touch audit records"*), failure semantics = visible-proceed with buffering deferred to official release, cadence = hourly, subtree designation = prototype-only and scoped to the default backend rather than the contract. Charter ruling changed late from a narrow carve-out to producer-agnostic once evidence showed `overseer.md:7` was already descriptively stale.
