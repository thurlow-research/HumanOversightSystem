# Finding: A Two-Key Enable — Separating Authorization From Activation — Prevents Autonomous System Self-Enablement

**Role:** oversight-mechanism — preventing unauthorized activation of autonomous AI agents

**First observed:** 2026-06-15–16, during the #254 unattended worker spec and Phase A implementation (R13.2, R13.4)

---

## The Finding

An autonomous AI agent that can read and execute governance configuration from a committed repository file can, in principle, construct the exact artifact that enables it — if enablement is a single condition controlled entirely within the system's reach. The HOS unattended worker addresses this with a **two-key enable**: the autonomous loop runs only when *two independent conditions simultaneously hold*, each of which the agent cannot satisfy unilaterally.

**Key 1 — Repo authorization:** `enabled: true` in `PROJECT/hos-coordination.yaml`, which is committed, CODEOWNERS-gated, and requires a human-approved PR to change. The agent cannot merge this change itself because: (a) it lacks the human approver's credentials, and (b) the `require-human-approval` CI check (running in GitHub Actions, outside the agent's environment) blocks any PR touching this file without a human approval from a non-bot account.

**Key 2 — Operator activation:** a per-machine file `~/.hos/<repo-id>/ACTIVE` containing a machine-binding token (the machine's hostname or a per-machine UUID). This file lives outside the repo, is never committed, and is never synced — it cannot travel with a clone. A fresh checkout, a CI environment, or any machine other than the one the operator explicitly activated is inert regardless of what Key 1 says.

Neither key alone is sufficient. Key 1 without Key 2: the governance config authorizes the loop, but no machine will run it (no ACTIVE file anywhere). Key 2 without Key 1: the operator has turned on a switch that does nothing because the governance config says `enabled: false`. An agent that could commit to the repo (Key 1 channel) cannot produce Key 2, because Key 2 lives on the operator's machine outside any repo surface. An agent that could write to the operator's machine (Key 2 channel) would be a much more fundamental security failure and is out of scope.

## Why This Matters

The two-key design is a concrete implementation of the principle that **authorization and activation are distinct concerns**. Authorization (Key 1) answers: "is this system sanctioned?" — an institutional, durable decision that belongs in committed, auditable state. Activation (Key 2) answers: "is this running here, now?" — an operational, ephemeral decision that belongs in non-repo, machine-local state. Conflating the two by making a single committed flag control both makes the flag a high-value target: anyone (or any agent) that can merge to the repo can activate the loop on any machine.

The design also provides three distinct controls for three distinct shutdown scenarios, each appropriate to its urgency:
- **Policy off** (`enabled: false`, committed) — "this repo is not sanctioned." Requires a PR; auditable; durable.
- **Operator off** (remove `ACTIVE` file) — "not running on this machine right now." One command; non-propagating; no review needed.
- **Emergency kill** (`hos-halt` file, committed and CODEOWNERS-gated) — "stop immediately." Fast; auditable; cannot be undone by the agent.

These are orthogonal: the emergency kill works even if the governance config still has `enabled: true`; the operator off works even during an active task (workers self-terminate at the next heartbeat).

## Evidence

- `scripts/automation/lib/activation.py` and `scripts/automation/lib/config_resolver.py` (this session) — the implementation. The unit tests (`test_activation.py`, `test_config_resolver.py`) verify that each key is independently required: `enabled: true` with no ACTIVE file → inert; ACTIVE file present with `enabled: false` in governance config → inert.
- `docs/specs/UNATTENDED-WORKER-PROTOCOL.md §13 / R13.2, R13.4` — the spec text articulating the AND-gate design and its rationale.
- The governance-layer narrow-only constraint: a runtime env var (`HOS_AUTO_ENABLED=true`) cannot widen past what the governance config established — a later layer can only narrow, never widen, the permitted scope. The unit tests verify this (`test_enabled_false_in_defaults_cannot_be_widened_by_env`).

## Implications for Research

1. **Authorization vs. activation is a generalizable decomposition.** Any autonomous AI system with a "should this run?" decision benefits from separating the institutional (committed, auditable, slow) and operational (local, ephemeral, fast) components. Conflating them produces either "too slow to turn on in an emergency" or "too easy to self-enable."
2. **The non-repo anchor is the key structural property of Key 2.** The ACTIVE file's value is not that it is hard to create, but that it *cannot travel with the repo* — a structural property, not a cryptographic one. A fresh clone is inert by construction, regardless of what any file in the repo says. This is easier to reason about and audit than a capability that depends on secrets or signatures.
3. **The emergency kill is the canary for the governance model's integrity.** If an autonomous agent could remove the `hos-halt` file without human approval, the entire two-key model collapses. That it cannot (branch protection + CODEOWNERS + `require-human-approval` CI gate) is the practical test of whether the governance model is actually enforced — not just stated.

## Related findings

- `actor-identity-vs-determination-honesty.md` — the complementary finding that actor identity (machine accounts) and determination honesty (server-side enforcement) are also two distinct guarantees; this finding adds the authorization-vs-activation dimension.
- `self-classification-cannot-gate-the-human-boundary.md` — the related principle that an agent cannot credibly certify its own boundary; the two-key design is the structural solution to this for autonomous activation.
- `the-safety-valve-must-be-more-trustworthy-than-the-gates.md` — the emergency-kill property: the kill switch must be outside the system's ability to remove.
