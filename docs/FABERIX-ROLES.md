# FABERIX-ROLES.md — Faberix, the autonomous HOS maintainer (roles + operating spec)

**Status:** spec for review. **Hard prerequisite: #152 (machine accounts) is live before *any* role runs autonomously.** Build sequencing in §8.

---

## 0. What Faberix is (and isn't)

Faberix is an **autonomous maintainer** for the HOS repo (and, by extension, HOS-governed consumer repos). It runs on a schedule under its **own machine account**. It is **not** a developer that builds features — it is a **janitor + first-line reviewer + triager** that keeps the system healthy and the queues clean, and **escalates anything it shouldn't decide alone**. Three roles:

- **R1** — pay down validator tech-debt (daily).
- **R2** — triage incoming items (fix what it can, escalate what it can't).
- **R3** — review PRs from others (approve what it can, escalate what it can't).

The design principles that bound all three — identity (§1), cost-gating (§2), and the won't-fix→validator feedback loop (§6) — matter more than the role mechanics, which are mostly already prototyped (tonight's overnight loop is R2).

## 1. Hard prerequisite — machine accounts (#152)

Faberix **must not go autonomous until #152 ships.** Every role produces *attributable determinations* — commits, won't-fix rulings, PR approvals — that must be:
- **distinguishable from human actions** (actor identity), and
- **bounded so Faberix cannot forge a human determination** (determination honesty — see `AGENT-IDENTITY.md §5.1`).

Concretely: Faberix authenticates as the `hos-agent` bot; its PR approvals are *bot* approvals; branch protection requires a **human** approval on HIGH/CRITICAL paths, so Faberix **structurally cannot self-approve** a risky change or a won't-fix on a security finding. Running Faberix under the shared human identity would make its audit trail meaningless and its approvals forgeable — which is the whole reason #152 exists. **→ This is a gate, not a nice-to-have.**

## 2. Cross-cutting principle — cost-gating (no model spend without work)

The user constraint: *scripts must not invoke the models (and run up bills) unless there is work to do.* Every Faberix activation is **two stages**:

1. **Cheap deterministic trigger (NO model):** a pure bash/python precheck answering "is there work?" — count open `validator-debt` items, list issues/PRs updated since the last run, diff the suppression ledger against current findings. Costs ≈ nothing (git/gh/file reads only).
2. **Expensive model work (only if stage 1 found work):** invoke the agent CLIs (`claude`/`agy`/`codex`).

If stage 1 finds nothing, Faberix **exits before any model call**. This is a hard rule. Each role below names its stage-1 trigger. Faberix writes a one-line **heartbeat** to a log on every activation (even idle ones) so a quiet night is still auditable — "checked, nothing to do" is a recorded decision, not silence.

> **Honest note:** tonight's prototype loop (`cron 98204cb6`) does *not* yet have this separation — it spins a full model session each hour and checks for work *inside* the session, which costs tokens on idle ticks. Faberix's §2 is the fix: a deterministic trigger script that gates the model invocation. Promoting the prototype to a real role means adding the stage-1 gate.

## 3. Role R1 — daily validator tech-debt paydown

**Cadence:** once per day.
**Stage-1 trigger:** the open validator-debt queue is non-empty (issues labeled `validator-debt`/`scanner-fp`, or entries in a debt ledger). Empty → exit, no model spend.

For each debt item, exactly **one of three dispositions** (this mirrors how a human engineer triages a debt backlog, and implements **#133**):

- **Fix** — clear, safe, and *worth it* → fix via the merge protocol, **verifying reproduction first** (`HANDLING-FINDINGS.md`; tonight 3 of 4 field reports didn't reproduce — see `[[project-cps-test-false-field-reports]]`).
- **Won't-fix** — *not worth fixing*: fix-risk > finding-severity, cosmetic, or the validator is simply over-sensitive here. Record a **won't-fix ruling with rationale** AND write a **suppression entry** (§6) so the validator stops re-reporting it. This is the queue-cleaning move the user called out — following human practice, not everything gets fixed.
- **Escalate** — needs a human decision (policy, design, a security/privacy finding Faberix may not wave off) → `needs-human`, don't guess.

**Convergence:** *fix* + *won't-fix-with-suppression* together drive the debt queue toward zero. A debt item is **never** left to silently re-appear next run — it's either gone (fixed) or suppressed-with-reason (won't-fix) or owned by a human (escalated). This is the non-deterministic-gate convergence architecture (METHODOLOGY.md) applied to validator debt.

## 4. Role R2 — incoming-item triage

**Cadence:** periodic (hourly), event-driven where possible.
**Stage-1 trigger:** issues/field-reports updated since the last run. None → exit.

**Pipeline:** verify-reproduction-first → prioritize → **fix what it can** (merge protocol) / **escalate with questions what it can't** (`needs-human`). This is exactly tonight's overnight loop, formalized as a standing role. Non-reproducing reports get an evidence comment + escalation, **not** a code change. Governance/gate/contract changes are never auto-merged — they become review-PRs (R3 territory).

## 5. Role R3 — PR review (approve / escalate)

**Cadence:** event-driven (on PR open/update).
**Stage-1 trigger:** open PRs awaiting review. None → exit.

Faberix reviews PRs from others and either:
- **Approves** what it can — LOW risk-tier, within policy, tests green, **no** governance/contract/gate/security/privacy surface. The approval is a **bot** approval (attributable, audit-trailed).
- **Escalates** what it can't — HIGH/CRITICAL tier, governance/gate/contract/security/privacy changes, or anything ambiguous → request human review (`needs-human`), **do not approve**.

**Determination-honesty boundary (`AGENT-IDENTITY.md §5.1`):** branch protection requires a **human** approval before merge on protected paths, so even a Faberix "approve" on a risky PR **cannot satisfy the merge gate** — by construction. On those paths Faberix's approval is *necessary-not-sufficient*; the human's is required. This is precisely why R3 is gated on #152.

## 6. The won't-fix → validator suppression mechanism (closing the loop)

The user's key point: *a won't-fix must stop the validator re-reporting it, or the queue never stays clean.* So won't-fix is not just an issue label — it writes back to the validators.

- **Suppression ledger:** `scripts/oversight/validators/suppressions.yaml` — append-only, each entry keyed by `{dimension, file, locator (line|symbol|pattern), rationale, ruled_by, date, source_issue}`.
- **Validators consult it:** `run_validators.sh` (or each validator) filters findings that match a suppression — they are recorded as **`suppressed`** (with the rationale carried through), **not scored**. This is **not a silent gag**: suppressed findings stay visible-but-excluded, with who/why/when attached.
- **Accountability:** a suppression entry *is* a determination (who ruled won't-fix). Under #152 it carries the bot-or-human identity; over-broad suppressions are reviewable because the ledger is committed and diffed. A human can require that security/privacy suppressions be human-ruled only.
- **Scope discipline:** suppress the **narrowest** thing that kills the false report (a specific `file:pattern`, not a whole dimension). A recurring *category* false-positive is a **`scanner-fp`** → fix the heuristic upstream, don't blanket-suppress (`HANDLING-FINDINGS.md §3`). Suppression is for *this instance isn't worth it*; scanner-fp is for *the detector is wrong*.
- **Precedent:** mirrors the existing `PROJECT_NON_AGENT_TOKENS` suppression in `config.sh` (CUSTOMIZATION.md) — same idea (accountable, committed, narrow), extended from the static agent-checker to the risk validators.

## 7. Relationship to existing work

| Item | Relationship |
|---|---|
| **#152** machine accounts | **Prerequisite** — identity, accountability, the R3 approval boundary |
| **#131** daily scheduled self-review | R1's **finding source** (the debt the daily run surfaces) |
| **#133** triage/accept (stop fixing when fix-risk > severity) | **Implemented by** R1's won't-fix disposition (§3) + the suppression ledger (§6) |
| **#78** generalize the convergence ledger | Sibling of the suppression ledger; both are dedup/accountability ledgers |
| `HANDLING-FINDINGS.md` | The triage discipline R1/R2 follow; scanner-fp-vs-suppress boundary |
| Overnight loop (`98204cb6`) | The **R2 prototype** (needs the §2 cost-gate to become R2 proper) |

## 8. Build sequencing

1. **#152 live** (gate — nothing autonomous before this).
2. **Suppression ledger + validator consumption** (§6) — this is what makes won't-fix *mean something*; build it first because R1 depends on it.
3. **R1** daily debt paydown (cost-gated per §2).
4. **R2** triage — promote the overnight-loop prototype, add the stage-1 cost gate.
5. **R3** PR review — needs #152 branch-protection wiring (§5).

Each role ships **behind its stage-1 cost gate** and **under the bot identity**. None ships before #152.

---
*Spec drafted by the HOS agent for human review. Open questions for the review: (a) is the suppression ledger per-repo or shared across consumers? (b) which finding classes are **human-ruled-only** for won't-fix (security/privacy/license)? (c) what risk-tier ceiling may Faberix auto-approve at in R3 (proposed: LOW only)?*
