# Finding: Behavioral Prohibition on Human Authorization Artifacts Is a Necessary But Insufficient Enforcement Mechanism

**Role:** oversight-mechanism — the limits of enforcing the human gate

**First observed:** 2026-06-12, issue #25 (pre-existing governance gaps from semantic validation)
**Documented in:** `oversight-evaluator.md`, `risk-assessor.md`, `DECISIONS.md` D30

---

## The Finding

The most critical human gates in HOS are represented by files that agents are instructed not to create. The CRITICAL step authorization file (`.claudetmp/oversight/step{N}-human-authorization.md`) and the risk tier override file (`human-tier-override.md`) can only be created by humans — but any agent with Write/Bash access could create them.

The current enforcement mechanism is **behavioral prohibition**: hard constraints in the agent files stating "you may not create or modify this file." This is the same mechanism used for the `contract/gate-suspension.md` suspension file. It relies on agent compliance, not mechanical enforcement.

---

## Why Stronger Enforcement Is Blocked

The natural stronger mechanism would be cryptographic: require authorization via a signed GitHub comment from the repo owner, or a commit signed with a human key. This would make the authorization mechanically unforgeability — an AI agent cannot produce a valid human signature.

However, this mechanism is currently impractical because **all PRs and commits from this project appear to come from the same GitHub account** regardless of whether they were AI- or human-submitted. The "human" identity is indistinguishable from the "AI" identity at the GitHub API level. A signed GitHub comment from the repo owner would be indistinguishable from a comment an AI agent posted on behalf of the owner.

This is a fundamental identity problem, not just an implementation gap. Until AI agents and humans can be authenticated separately against a trusted identity provider, signature-based enforcement of human gates will not work in this context.

---

## The Current State

The behavioral prohibition is not worthless — it encodes the intent clearly and creates a visible audit trail when violated. An agent that creates a human authorization file despite the prohibition is committing an observable protocol violation. The prohibition is:
1. Explicit in the agent files (hard to miss)
2. Auditable (git log shows who created the file)
3. Subject to the same validation framework that catches other protocol violations

But it is not mechanically unbeatable. A sufficiently motivated or malfunctioning agent could bypass it.

---

## Implications for Research

1. **The identity problem in AI governance.** When a human and an AI share an account, the governance mechanisms designed to distinguish them lose their mechanical teeth. This is a structural gap in current AI governance infrastructure — not unique to this framework.

2. **Behavioral constraints as a graduated response.** The choice to implement behavioral prohibition now and revisit mechanical enforcement later reflects a principled decision: imperfect enforcement is better than no enforcement. The prohibition creates an audit surface, sets a clear norm, and can be strengthened later when the identity problem is resolved.

3. **Mechanical enforcement requires a separate identity layer.** The long-term solution likely involves AI agents having distinct authenticated identities (OAuth tokens, API keys with limited scopes, or cryptographic keys) that are separate from the human developer's identity. PRs submitted by AI agents would be attributable to an AI identity, and human authorization would require authentication as a human identity. This is an unsolved problem at the tooling level as of 2026.

---

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — the general pattern; this is a specific case where the verification mechanism cannot yet be made fully mechanical
- `brownfield-governance-adoption.md` — the gate suspension mechanism faces the same identity problem for authorization
