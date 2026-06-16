# AGENT-IDENTITY.md — Agent actor identity via machine accounts (#152)

**Status:** spec for review. Once approved, the human creates the account(s) and the agent builds the tooling (task split in §10). **Release sizing:** machine accounts are a **significant release (minor bump, e.g. v0.2.0 — not a patch)** — they change the identity, authorization, and merge model, and require consumer action (creating accounts), so they ship as a deliberate version step, not a silent point fix.

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

### 5.2 Two boundaries, two enforcement strengths (under the two-account model, §7)

The worker/overseer/human structure creates **two** approval boundaries, and they are not equally strong:

- **overseer ↔ human** (HIGH/CRITICAL → human): forge-proof **server-side** — branch protection requires a human-identity approval on those paths, and the human's credentials are absent from the agent's environment. This is the determination-honesty gate above; it holds regardless of how the bots run.
- **worker ↔ overseer** (the worker class cannot approve): forge-proof **only if the two classes run in credentially-isolated contexts** — separate sessions/environments, each holding *only* its class's token. If a single orchestrator session holds *both* bot tokens, the worker/overseer split is *attributed but self-enforceable* (that session controls which token signs which action) — i.e. **accountability, not forge-proofing**, the same local-vs-server-side distinction one level down.

So: **pilot** = two accounts + the server-side human gate (a real win, and "who did what" is unambiguous via the distinct authors). **Hardened** = run the worker and overseer classes in separate credential contexts, so the worker truly cannot wield the overseer token. Record which one shipped (per the obligation above), for the worker/overseer boundary too.

## 6. The "reports-to" relationship (no first-class GitHub field — conventional schema)

| Dimension | Mechanism |
|---|---|
| **Ownership** | the human creates and holds account recovery for every bot → the bot "belongs to" that human |
| **Hierarchy** | an `hos-agents` org team; bot accounts are members, the human is the team **maintainer** |
| **Accountability** | CODEOWNERS + branch protection requiring a **human** approval on HIGH/CRITICAL paths (this is the Layer-3 gate, now mechanically enforced) |
| **Traceability** | commit trailers — keep `AI-Model:`/`AI-Risk:`, add **`Supervised-by: <human>`** linking the bot's work to its responsible human |

## 7. Account structure — two classes, not N accounts (decided 2026-06-14)

A per-agent account proliferation (tens of accounts to manage) is unwanted *and* unnecessary. The system already has exactly **two classes of agent**, so use **two machine accounts**, one per class:

| Account | Class | Members (examples) | May approve PRs? |
|---|---|---|---|
| **`hos-worker`** | agents that **do work** | coder, technical-design, architect, dep-mapper | **No** — opens PRs, never approves |
| **`hos-overseer`** | agents that **oversee & approve** | code/security/privacy/reliability/ops reviewers, risk-assessor, oversight-evaluator/orchestrator, Faberix | **Approves AND merges** safe (LOW) PRs end-to-end; **recommends-only** above (escalates to human) |
| *(human — personal account)* | the escalation ceiling | — | **Approves** HIGH/CRITICAL (and anything above the overseer's ceiling) before it can merge |

Within each class, every agent still **self-identifies which agent + mode it is** (`[AI: {agent-name}]`, the Layer-2 attribution) on commits/issues/PRs — so "exactly who did what" is preserved without an account per agent.

**Why two accounts beat both alternatives:**
- **vs. a single bot:** a single bot would *author **and** approve* — collapsing the **author ≠ reviewer independence** that is the entire point of HOS (the same role-absorption failure as #173). Two accounts restore that separation **at the identity layer**: the worker account literally cannot approve its own (or any) PR.
- **vs. per-agent (N accounts):** two accounts are manageable; per-agent is an *optional later refinement only* — Layer-2 attribution already records which agent acted, so a distinct account per agent is rarely worth the management cost.

**The three identity tiers map onto the three oversight layers:** worker (signal/build) → overseer (oversight/approve-within-risk) → human (the gate). The overseer's **risk-tiered approval ceiling *is* the Faberix R3 trust-ratchet (#167)**: overseer auto-approves LOW, *recommends* on MED/HIGH, human approves HIGH/CRITICAL — and the ceiling may ratchet up as trust is earned, never to HIGH.

Naming: `hos-worker` / `hos-overseer` (per repo/owner). Both owned/recovered by the human.

## 8. git/gh configuration (per agent environment)

The agent's checkout/session is configured to operate as the bot:
- `git config user.name "hos-agent"` / `user.email "<bot-email>"` (the bot's no-reply or a dedicated address).
- `gh auth` uses a **bot PAT** scoped to the repo (`repo`, `read:org`) — *not* the human's token.
- The human's personal credentials are **absent** from the agent's environment.
- Pushes go to feature branches; `main` is protected (merge requires human approval — §5).

### 8.1 Interactive sessions: Claude is the **worker**, not the human

§8 applies to **interactive** sessions too — not only the autonomous loop. When a human (e.g. Scott) drives Claude live in a chat session, **Claude still authenticates as the worker bot; the human's account is reserved for the irreducible human-only acts.** The load-bearing reframe:

> **"Interactive vs autonomous" is about whether a human is *present to direct* — NOT about which identity Claude wears.** A human present and directing *is* the human-in-the-loop, and that role is satisfied by their **review and authorization**, not by their account being the committer.

Role mapping that follows from this:

| Role | Interactive (human present) | Autonomous (no human) |
|---|---|---|
| **Worker** (writes code, opens PRs, never approves) | **Claude**, as the worker bot | Claude, as the worker bot |
| **Oversight** (approves within the §7 ceiling) | the **human**, reviewing live | the **overseer bot** (auto-approves ≤ ceiling) |
| **Human gate** (protected surface §9.0, above-ceiling, security, overrides) | the **human**, as themselves | escalated to the **human** |

**Why it must be this way.** If interactive-Claude keeps using the human's account, that account's history becomes a mix of genuine-human and bot actions — and the human gate becomes *unfalsifiable*: you could never prove a given action under the human's account was actually a human's, because some "human" actions were the bot's. **Reserving the human account for human-only acts is the single thing that makes every action under it provably a human decision** — the §5.1 actor-identity guarantee applied to the day-to-day. "You are actually me" is the bug this closes, not a property to preserve.

**Interim state (until the bot accounts are wired into a session):** an interactive session running under the human's credentials *is* the transitional case — its commits/PRs authenticate as the human, mitigated only by the `🤖 [AI: claude]` disclosure markers. Those fix the **attribution** layer ("the AI wrote this") but not the **actor** layer (which still says the human) — i.e. accountability, not forge-proofing (§5.1). Wiring the worker token into the session is what closes it.

**Tooling rule.** The session wraps `git`/`gh` to use the **worker token by default**; it switches to the **overseer token** only for an autonomous within-ceiling approval; and it uses the **human's token *never*** — except when the human personally performs a human-gate act. The AI-CLI/model auth stays under the human's subscription (§4 decoupling) — that is the unavoidable attribution layer; the **git committer + gh actor** are the bot.

## 9. Branch protection (the merge gate as forge-proofing) — settable as code

On the protected branch (`main`):
- **Require a pull request before merging**, with **≥1 approving review**, where the approver depends on risk tier:
  - **Normal/LOW paths:** the approval may come from **`hos-overseer`** (or a human) — **never from `hos-worker`** (the author class). Since `hos-worker` opens the PR, GitHub's own "no self-approval" rule plus the worker-can't-approve restriction means a worker PR needs an *overseer or human* review.
  - **HIGH/CRITICAL paths or above the overseer's ceiling:** the approval must come from a **human**. Enforce via (a) **CODEOWNERS** on the statically sensitive paths (require a human reviewer), and (b) a **required status check** that computes the PR's validated risk tier and *fails* if the tier exceeds the overseer's current ceiling — so a re-derived-CRITICAL change can't be overseer-approved. (The risk-tier→approver mapping is not natively dynamic in branch protection; the status check is what makes it server-side.)
- **Dismiss stale approvals** on new commits.
- **The `hos-overseer` is the merge actor for SAFE (LOW) PRs — it approves *and* merges them end-to-end, no human in the loop.** On higher-risk PRs it can neither approve nor merge: branch protection requires a human approval first, and the overseer escalates (it does not wait-and-merge on its own).
- `hos-worker` never approves and never merges — it opens PRs only.
- The admin-bypass (`--admin`) of the **human-required** gate is **disabled for both bot tokens** — so on a HIGH/CRITICAL (or above-ceiling) PR no bot can merge until a human has approved. (The overseer merging a *safe* PR is not a bypass; it's the gate being satisfied by an overseer approval, which the rules permit for that tier. The human retains admin.)

### 9.0 Protected surfaces — governance always needs a human, regardless of computed risk tier

The overseer's "approve/merge safe (LOW)" authority is gated on a **content-risk** score — but a change can be **mechanically LOW-risk and still touch a governance surface** (rewriting agent routing text, *weakening a reviewer obligation*, editing branch-protection or gate logic). Letting that auto-merge would let the system quietly loosen its own controls. So, overriding the risk tier:

**Any change matching a protected-surface path requires a *human* approval, regardless of computed risk tier — no bot may approve or merge it.** The list is **canonical glob paths** (so CODEOWNERS and the status check can match it precisely, not prose):

```
.claude/agents/**          AGENTS.md
contract/**                docs/AGENTS.md
docs/AGENT-IDENTITY.md     METHODOLOGY.md
docs/FABERIX-ROLES.md      docs/CROSS-REPO-CONDUCT.md
bootstrap/**               scripts/framework/**        (install, release, validation tooling)
scripts/oversight/gates/** scripts/oversight/run_validators.sh
scripts/oversight/validators/schema.py                 (weights / tier thresholds)
.github/CODEOWNERS         .github/workflows/**
```
(Anything that defines an agent's behavior, the contract, a gate/validator, the installer/release path, or the identity/authority model itself.)

This is the global backstop behind the overseer ceiling and the operator's risk-tiered merge grant: **the surfaces that define the controls can never be loosened on the controls' own say-so.** Enforce it server-side via CODEOWNERS on those paths (require a human reviewer) **plus** a required status check that fails any PR touching a protected surface without a human approval. (Surfaced by the v0.2.0 release gate; it tightens the LOW/MED auto-merge authority, not just the bots.)

### 9.1 Escalation must be legible to a context-free human

When the overseer escalates a PR or decision to the human, **assume the human has no prior context** — they did not follow the thread, the agent reasoning, or the build step. So every escalation must be **self-contained**:
- the **PR description** states what changed, why, the validated risk tier, the blast radius, and the specific question/decision the human must make;
- the linked **`needs-human` issue** restates the decision, the options, the recommendation, and the consequence of each — not "see above" or "as discussed."

A handoff the human can act on **without reconstructing context** is the difference between the gate scaling and the gate becoming the bottleneck (relates to #156, human-gate ergonomics). This is a hard requirement on the overseer/orchestrator, not a nicety.

I can apply the branch-protection rules via `gh api` once the accounts exist.

## 10. Build plan — human vs. agent task split

**You (human) do — these need github.com and cannot be automated by the agent:**
1. Create the **two** machine-user accounts — `hos-worker` and `hos-overseer` (distinct email each). Verify current GitHub ToS allows them (§11).
2. Generate a repo-scoped PAT for each bot; add `hos-worker` (write, no approve) and `hos-overseer` (write + review) as collaborators / to the respective teams.
3. *(decided — §7: two accounts by class; per-agent is a later option, not now.)* Confirm the overseer's starting approval ceiling = **LOW** (ratchets per #167).
4. Confirm the operational rule: the agent runs under bot creds; **you approve from your personal account in a separate context**.
5. Authorize me to configure branch protection (or do it yourself per §9).

**I (agent) build — once the accounts exist:**
1. `scripts/.../provision_agent_account.sh` — configures a checkout's `git` + `gh` to operate as a given bot (creds passed in; account creation stays manual). In the `setup_clis.sh` style (colours, idempotent, `doctor`).
2. `branch-protection` setup script (`gh api`) implementing §9, + a doc of the settings.
3. The `Supervised-by:` trailer convention, wired into the commit/PR templates and AGENTS.md disclosure.
4. Reframe **#151** → "achieved via the #152 identity split"; update the METHODOLOGY threat-model note (the human gate is now forge-proof via identity separation, with the residual being repo-config tampering — a loud, auditable act).
5. Update AGENTS.md to document the actor-identity layer alongside the existing attribution layer.

## 10a. This is for building HOS **and** for HOS consumers

The two-account identity model is needed in **both** contexts: HOS's own development *and* every project that installs HOS. So the deliverables are **framework-level, consumer-facing, and parameterized per repo/owner** — not one-off HOS-internal scripts:
- `provision_agent_account.sh` takes the class (`worker`/`overseer`), the bot's creds, and the target repo — so a consumer runs the same tool to wire up *their* two bots.
- A **setup guide** ("Create your two machine accounts and configure HOS"): the click-path to create `hos-worker`/`hos-overseer` on github.com, generate the PATs, set branch protection, and point each agent context at the right account. This ships in `docs/` and is referenced from QUICKSTART/SETUP, because account creation is the one manual step every consumer hits.
- The branch-protection-as-code script applies the §9 rules to *any* repo, so consumers get the tiered-approval gate without hand-configuring it.

Net: account *creation* stays manual (human, per §10), but everything downstream — config, branch protection, the tiered gate — is one tool + one doc that works the same for HOS and for consumers.

## 10b. Status — foundation built (2026-06-14)

The two HOS machine accounts exist: **worker = `hos_worker@tutelare.ai`**, **overseer = `hos_oversight@tutelare.ai`** (login emails; the GitHub *usernames* — which cannot contain `_` — are configured in `machine-accounts.env`, not assumed). Decisions confirmed by the human: **hosting-agnostic, defaulting to personal-repo + collaborators (no org yet)**; **overseer ceiling = LOW, with a one-line MEDIUM flip**.

Implemented (the load-bearing **server-side** half of §5.1 — the protected-surface human gate):
- `scripts/framework/protected_surfaces.txt` — the §9 list as a single machine-readable source of truth.
- `scripts/framework/require_human_approval.py` + `.github/workflows/require-human-approval.yml` — a status check (runs in CI, outside the agents' reach) that **fails any PR touching a protected surface without a human approval** (human = approver not in `BOT_ACCOUNTS`). Unit-tested in `tests/framework/test_require_human_approval.py`.
- `scripts/framework/gen_codeowners.sh` → `.github/CODEOWNERS` — the static half; protected surfaces → human owner, generated from the same list so the two can't drift. (Replaces the old blanket `* @OWNER`: non-protected paths may now be overseer-approved.)
- `scripts/framework/machine-accounts.env` — bot handles + `OVERSEER_CEILING`.
- `docs/MACHINE-ACCOUNTS-SETUP.md` — the §10a consumer-facing setup guide (accounts → PATs → collaborators → config → branch protection).

These ship **inert** — they enforce nothing until the human enables branch protection (setup guide Step 5). Still to build (#152 follow-ups): the **risk-tier-vs-ceiling** status check (the dynamic above-ceiling→human gate), `provision_agent_account.sh`, the branch-protection-as-code script, and the `Supervised-by:` trailer convention.

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
