# AGENT-IDENTITY.md — Agent actor identity via machine accounts (#152)

**Status:** spec for review. Once approved, the human creates the account(s) and the agent builds the tooling (task split in §10).

---

## 1. The problem

The HOS agents run on the human's machine under the human's credentials, so every git commit, pull request, issue, **and approval** authenticates as the human (`ScottThurlow`). The framework solves *who wrote the content* (attribution: the `[AI:]` title prefix, the AI-disclosure block, the `AI-Model:`/`AI-Risk:` trailers, the comment marker) but not *who authenticated the operation* (actor identity). Everything still reads "Scott did it."

This is not cosmetic — it bounds the framework's core claim. The human gate (#127) is only real if a human action is *distinguishable* from an agent action. Today it isn't, which is why #127's pilot can only achieve *accountability* (a committed, content-hashed record), not *forge-proofing*. **Actor identity is the missing layer, and it is the clean fix.**

## 2. The two-layer model

| Layer | Question it answers | Mechanism | HOS status |
|---|---|---|---|
| **1 — Actor identity** | who *authenticated* this git/GitHub operation? | a separate **machine-user account** (or GitHub App) per agent | ❌ missing (all = the human) |
| **2 — Authorship attribution** | who/what *wrote* this content? | commit trailers, `Co-authored-by`, the `[AI:]` disclosure + comment marker | ✅ implemented |

Conflating the two is the source of the friction. #152 adds Layer 1; the existing disclosure work is Layer 2 and stays.

## 3. Decision: machine users, not GitHub Apps

GitHub Apps are more audit-friendly (App actions carry `actor_type: Bot`, queryable, structurally separate from any human PAT). But an App needs an installation + token-exchange auth flow that the cross-vendor CLIs (`agy`, `codex`, `claude`) — which run under **subscription** auth, not API keys — do not support. A **machine user** is just another credential set the agent's `git` + `gh` config points at. For this stack, machine users are the practical primitive. (Revisit Apps later if/when an API-key path exists and per-agent audit-log querying becomes worth the install flow.)

## 4. The decoupling that makes this achievable

Two auth surfaces that feel entangled are actually separate:

- **AI-CLI auth** (`claude`/`agy`/`codex` → their provider): stays under the human's subscription. Unavoidable, and it's Layer 2 — it doesn't touch actor identity.
- **git/gh identity** (commit author, PR/issue author, **approver**): fully swappable to a bot account, independent of the AI-CLI auth.

So #152 is a **git-config + gh-auth change**, not an AI-CLI change. The agent keeps talking to its model under your subscription; only its *git/GitHub actor* changes.

## 5. The forge-proof property — how this fixes #127/#151

With the agent authenticated as a bot and the human's personal account reserved for approvals:

- A **human authorization** = an action (a PR approval, or a commit/comment) from the human's **personal** account.
- An **agent action** = from the **bot** account.
- The agent's environment holds **only the bot's credentials**, so it **cannot produce** an action attributed to the human's personal account.
- **Branch protection** requires a review approval from a **human (non-bot) account** before merge → the merge gate is forge-proof: the agent literally cannot self-approve as the human.

This is forge-proofing **by construction** (separate identities), not by cryptographic add-ons. It **supersedes #151's out-of-band-proof (TOTP / hardware-key) approach** — that was a workaround for the shared identity; this removes the shared identity. The critical operational rule: **the human approves from a context the agent's session does not control** (the GitHub web UI, or the human's own terminal), so the separation is real.

`#127`'s committed content-hash record stays as the accountability layer underneath; `#151` is reframed (see §12).

### 5.1 Two guarantees, not one — actor identity vs. determination honesty

This is the conceptually load-bearing part, and the part easiest to under-document because it feels obvious once stated. The machine-accounts move delivers **actor identity** — *who authenticated an operation* — but the property the human gate actually needs is **determination honesty**: that a recorded human *determination* (the approval decision itself) genuinely happened, by the human, and **cannot be manufactured by the agent**. These are **two distinct guarantees, routinely conflated, and machine accounts close only the first.**

Actor identity is **necessary but not sufficient** for determination honesty. The second is closed only when the approval check is enforced in a place **the agent's environment does not control** — i.e. **server-side** (GitHub branch protection requiring a review from a human-identity reviewer), *not* by a **local** check the agent's own session runs (an HOS script reading a committed authorization artifact). The two **compose**, and neither alone suffices:

- **Machine accounts (actor identity)** ensure the required reviewer is a *different identity* than the agent.
- **Server-side enforcement** ensures the agent *cannot bypass or self-satisfy* the gate.
- A **local** gate is self-satisfiable even with separate identities (the agent runs the check). A **server-side** gate is forgeable if the agent can authenticate as the human (no identity split). You need **both**.

Mapping to existing work: **#127's committed content-hashed record is the *local* form → accountability** (auditable, but the agent could in principle produce it). **Branch protection requiring a human review is the *server-side* form → forge-proof.** The identity split is what makes the server-side gate *mean* something (the required reviewer is provably not the bot).

**Build-time obligation (don't leave it implicit in the diff):** when this ships, record **one explicit line** stating whether the human-approval check is enforced **server-side (GitHub branch protection)** or **by a local HOS script** — because that single fact is what determines whether the determination-honesty gap is *actually closed* (server-side) or merely made *auditable* (local). The mechanics of "we moved to machine accounts" will be obvious from the diff; this distinction will not be, and it is the one that matters.

## 6. The "reports-to" relationship (no first-class GitHub field — conventional schema)

| Dimension | Mechanism |
|---|---|
| **Ownership** | the human creates and holds account recovery for every bot → the bot "belongs to" that human |
| **Hierarchy** | an `hos-agents` org team; bot accounts are members, the human is the team **maintainer** |
| **Accountability** | CODEOWNERS + branch protection requiring a **human** approval on HIGH/CRITICAL paths (this is the Layer-3 gate, now mechanically enforced) |
| **Traceability** | commit trailers — keep `AI-Model:`/`AI-Risk:`, add **`Supervised-by: <human>`** linking the bot's work to its responsible human |

## 7. Account structure — pilot then full

- **Phase 0 (pilot): a single `hos-agent` machine user.** Buys the *entire* forge-proofing win (attribution + a real human gate) with one account. Recommended starting point.
- **Phase 2 (full): one machine user per authoring agent** (`hos-architect`, `hos-coder`, `hos-reviewer`, …) so the audit log shows *which* agent acted. A refinement, not a prerequisite.

Naming: `hos-<role>` (or `hos-agent` for the pilot). All owned/recovered by the human.

## 8. git/gh configuration (per agent environment)

The agent's checkout/session is configured to operate as the bot:
- `git config user.name "hos-agent"` / `user.email "<bot-email>"` (the bot's no-reply or a dedicated address).
- `gh auth` uses a **bot PAT** scoped to the repo (`repo`, `read:org`) — *not* the human's token.
- The human's personal credentials are **absent** from the agent's environment.
- Pushes go to feature branches; `main` is protected (merge requires human approval — §5).

## 9. Branch protection (the merge gate as forge-proofing) — settable as code

On the protected branch (`main`):
- **Require a pull request before merging**, with **≥1 approving review from a human reviewer** (CODEOWNERS or required-reviewers = the human, not any bot).
- **Dismiss stale approvals** on new commits.
- **Block author self-approval** (GitHub already prevents approving your own PR; with separate identities the bot's PR *needs* the human's approval).
- **Restrict who can push to `main`** to humans (the bot opens PRs; it does not push to main).
- The current admin-bypass merge protocol (`--admin`) must be **disabled for the agent's bot token** — the whole point is the agent can't bypass the human gate. (The human retains admin.)

I can apply these via `gh api` once the accounts exist.

## 10. Build plan — human vs. agent task split

**You (human) do — these need github.com and cannot be automated by the agent:**
1. Create the machine-user account(s): Phase 0 = one `hos-agent` (distinct email). Verify current GitHub ToS allows it (§11).
2. Generate a repo-scoped PAT for each bot; add the bot as a collaborator (or to the `hos-agents` team).
3. Decide: **single bot (pilot) vs per-agent (full)**.
4. Confirm the operational rule: the agent runs under bot creds; **you approve from your personal account in a separate context**.
5. Authorize me to configure branch protection (or do it yourself per §9).

**I (agent) build — once the accounts exist:**
1. `scripts/.../provision_agent_account.sh` — configures a checkout's `git` + `gh` to operate as a given bot (creds passed in; account creation stays manual). In the `setup_clis.sh` style (colours, idempotent, `doctor`).
2. `branch-protection` setup script (`gh api`) implementing §9, + a doc of the settings.
3. The `Supervised-by:` trailer convention, wired into the commit/PR templates and AGENTS.md disclosure.
4. Reframe **#151** → "achieved via the #152 identity split"; update the METHODOLOGY threat-model note (the human gate is now forge-proof via identity separation, with the residual being repo-config tampering — a loud, auditable act).
5. Update AGENTS.md to document the actor-identity layer alongside the existing attribution layer.

## 11. Open questions to resolve before Phase 0

1. **GitHub ToS / limits** — GitHub permits *machine accounts* for automation in addition to a personal account, but the exact rules on *multiple* bots under one owner, and per-account rate limits, should be verified against the current docs before standing up several.
2. **CLI auth under a bot git/gh identity** — confirm `claude`/`agy`/`codex` subscription auth has no friction when `git`/`gh` point at the bot (expected: none, since they're decoupled — but verify on first run).
3. **Approval context** — exactly how you approve from your personal account without your creds entering the agent's session (web UI is simplest; a separate terminal also works).
4. **Recovery chain** — you hold recovery for all bots; this is the "reports-to" anchor and must be documented.

## 12. Relationship to existing issues

- **#127** (pilot accountability — committed content-hashed `human-authorization` record): **stays** as the underlying audit layer. Forge-proofing is added *on top* by identity separation.
- **#151** (forge-proof via out-of-band proof): **reframed** — the identity split here is the cleaner, industry-standard path. Make #151 *depend on* #152, or close #151 in its favor once #152 ships.
- **AI-disclosure-on-comments** (shipped): the Layer-2 stopgap that made agent comments distinguishable on the shared account. #152 is the Layer-1 fix that makes the distinction *structural* rather than *conventional*.

---
*Spec drafted by the HOS agent for human review. Build begins after the account(s) exist and the §10 decisions are made.*
