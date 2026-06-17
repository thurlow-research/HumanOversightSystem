# Cross-repo conduct — how HOS agents work in repos they don't own

When an HOS agent (the oversight loop, Faberix, the oversight agent — any agent acting beyond its home repo) operates in a repo it **does not own** — a consumer project, an upstream dependency, anyone else's repo — it is a **guest**. Guests advise, file, and *offer*; they do not merge, approve, or decide. These rules are mandatory for every agent.

## The cardinal rule

**You never merge, approve, or close in a repo you don't own. The owner holds every approval.** You open PRs, file issues, comment, and flag — the owner disposes. A PR or a recommendation from us is a *proposal*, never a decision.

## Three cases

### 1. The issue is a bug **we** must fix (it's our framework, not their code)

A consumer-reported problem that reproduces in **HOS itself** — a scanner, gate, installer, or agent bug — is ours.

1. **File an issue in the HOS repo** for the fix.
2. **Cross-reference it from the owner's issue**: comment "🤖 [AI: claude] tracked upstream as `ScottThurlow/HumanOversightSystem#NN`."
3. **Fix it in HOS** (our pipeline, our merge).
4. **When fixed, comment on the owner's issue** so they know to follow up, **and add the `upgrade-hos` label** to it — the label that means *"fixed in HOS upstream; upgrade to the latest release to pick it up."* The owner can then list every issue waiting on an HOS upgrade with one label filter.
5. The owner upgrades (`hos_install.sh --force`) on **their** schedule; that closes their issue. We do not close it for them.

### 2. We have advice — or a fix — for **their** code

A problem in the owner's own application code, where we can help.

- **Put the advice in their issue and flag it for their attention** — a clear `🤖 [AI: claude] — recommendation` comment (the decision, options, recommendation, consequence).
- **If the change is LOW risk — or MEDIUM with only judgment calls — open a PR in their repo with the recommended fix, for *their* review.** Link it on the issue. Keep it small and self-contained.
- **They own the PR approval and the merge. We never merge in their repo.**
- **HIGH risk, or a design/policy/brand/privacy/spec decision → advice only (a decision brief), no PR.** The owner (or their architect) decides. Don't pre-empt a judgment call with code.

### 3. It doesn't reproduce, or we need more information

- **Add the specifics to their issue** — the exact reproduction attempt (command + output) that *failed*, or precisely what information is missing — and **flag it for them to look at.**
- **Never change code on a non-reproducing report** (verify-first — see `docs/HANDLING-FINDINGS.md`; on 2026-06-13, 3 of 4 consumer field reports did not reproduce).

## Always

- **Self-identify on every comment** (`🤖 [AI: {agent-name}]`) — you are a guest; say so. (You may be posting from a shared account.)
- **Verify reproduction before any fix** — theirs *or* ours.
- **Make every handoff self-contained** — assume the owner has no prior context (the escalation-legibility rule from `AGENT-IDENTITY.md §9.1`).
- The owner's repo, the owner's gates, the owner's merge button. When in doubt, advise and ask — do not act.

---

## Consumer-to-framework engagement

These rules govern how a consumer worker session may interact with the HOS framework repo (`thurlow-research/HumanOversightSystem`).

**Allowed:**
- Filing issues in the HOS repo with the `field-report` label. One issue per distinct observation; minor observations batched into one issue.
- Commenting on existing HOS issues when the comment is directly relevant.

**Not allowed:**
- Cloning the HOS repo, creating branches in HOS, committing to HOS, or opening PRs in HOS — from a consumer worker session. Consumer workers are guests of the framework, not contributors to it.

**Implementation channel:** Consumer workers file issues; the HOS worker picks them up and implements. Consumer workers do not self-implement HOS framework changes — even when the fix appears obvious.

**Per-session cap:** A consumer worker session should file at most 5 issues per session to avoid flooding the HOS tracker. Minor related observations belong in a single batched issue.

**Escalation:** If a consumer worker disagrees with framework behavior, file an issue only. No self-implementation. Route the issue; do not route around the process.

---
*Applies to all HOS agents (overnight loop, Faberix R2/R3, the oversight agent). Companion to `docs/HANDLING-FINDINGS.md` (verify-before-fix) and the `needs-human` ⇄ `needs-ai` handoff in `docs/AGENTS.md`.*
