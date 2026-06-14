# Finding: Actor Identity and Determination Honesty Are Two Distinct Guarantees — Machine Accounts Close Only the First

**Role:** oversight-mechanism — the structure of a forge-proof human gate

**First observed:** 2026-06-13, session `2026-06-13-cps-pilot-triage-and-backlog.md` (during the #152 machine-accounts spec review); documented in `docs/AGENT-IDENTITY.md §5.1`

---

## The Finding

A human gate that an AI cannot forge requires **two distinct guarantees that are routinely conflated:**

- **Actor identity** — *who authenticated the operation?* Closed by giving the agent its own machine account, so the required human approver is a **different identity** than the agent.
- **Determination honesty** — *did the human's approval decision genuinely happen, and is it unforgeable?* This is the property the gate actually needs.

**Machine accounts close only the first.** Determination honesty is closed only when the approval check is enforced where the agent's environment **cannot control it** — i.e. **server-side** (e.g. branch protection requiring a review from a human identity), *not* by a **local** check the agent's own session runs (a script reading a committed authorization artifact). The two **compose**, and neither alone suffices:

- A **local** gate is self-satisfiable even with separate identities (the agent runs the check, so it can produce the artifact the check looks for).
- A **server-side** gate is forgeable without an identity split (if the agent can authenticate as the human, it can submit the approval).

So forge-proofing the human gate needs *both*: separate identities **and** server-side enforcement.

## Why This Matters

This resolves the open problem stated in `human-gate-enforcement-limits.md` — that the shared GitHub identity makes signature-based enforcement impossible — by separating the problem into its two real components. It also corrects a tempting but wrong inference: "we moved to machine accounts, therefore the gate is now forge-proof." Machine accounts are **necessary but not sufficient**. If the team ships machine accounts but leaves the human-approval check as a *local* HOS script, the gate is **not** closed — it is merely made *auditable* (the local content-hashed record of #127 is accountability, not forge-proofing).

The distinction is **easy to under-document because it feels obvious once stated**, and the mechanics ("we adopted machine accounts") are visible in the diff while the guarantee structure is not. Hence the build-time obligation recorded in the spec: **state explicitly whether the approval check is enforced server-side or locally**, because that single fact determines whether the gap is actually closed.

## Evidence

- `docs/AGENT-IDENTITY.md §5.1` (this session) — the spec text.
- Mapping to existing mechanisms: **#127**'s committed content-hashed authorization record is the *local* form → accountable but forgeable; **branch protection requiring a human review** is the *server-side* form → forge-proof. The identity split (#152) is what makes the server-side gate *mean* something (the required reviewer is provably not the bot).

## Implications for Research

1. **A precise threat-model vocabulary.** "Forge-proof human gate" decomposes into *actor identity* (authentication separation) and *determination honesty* (enforcement locus). Conflating them produces overclaims. This vocabulary generalizes to any AI–human approval boundary, not just GitHub.
2. **Enforcement locus is the decisive variable.** Whether a gate is closed or merely auditable turns on *where* it is checked (a place the agent controls vs. one it does not) — more than on cryptography or identity alone.
3. **Same principle as machine-authored findings.** An asserted *determination* — "a human approved this," or a reviewer's "this is a bug" — is only trustworthy if independently verifiable, never if merely asserted. (See `reviewer-agents-file-confident-non-reproducing-reports.md`.)

## Related findings

- `human-gate-enforcement-limits.md` — states the shared-identity problem this finding decomposes and resolves.
- `self-classification-cannot-gate-the-human-boundary.md` — a related "the controlled party cannot certify its own boundary" result.
- `reviewer-agents-file-confident-non-reproducing-reports.md` — the determination-must-be-verifiable principle applied to AI findings.
