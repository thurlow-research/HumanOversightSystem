# [your project] — Agent Pipeline

*Last updated: June 2026. Applies to the Spec 1 pilot build.*

This document describes the multi-agent pipeline used to build [your project]. It covers each agent's role, model, escalation paths, and the full pipeline sequence. It is written to allow recreation in another Claude Code environment.

---

## Design principles

The pipeline is organized around a single rule: **each agent owns one concern and escalates everything else**. No agent makes decisions outside its domain; disputes travel up a defined chain until they reach the right authority. This prevents agents from silently making product, architecture, or policy decisions that belong to a human or a specialized agent.

Four tiers of authority:

| Tier | Who | Decides |
|---|---|---|
| Human | You | Product vision, policy, unresolvable disputes |
| Architect | `architect` agent | All technical/architectural decisions |
| PM | `pm-agent` | All product/requirements decisions |
| UX Designer | `ux-designer` agent | All design system decisions — tokens, component patterns, copy rules, feedback states |

Every other agent operates within the bounds set by these four. `ux-designer` is a peer authority to `pm-agent` and `architect` within its domain: it can extend the design pack without human involvement for additive changes, and only escalates structural brand changes upward.

---

## Universal AI disclosure requirement

### Issues

**Every GitHub issue created by an AI agent must have the creating agent identified in the title:**

```
[AI: {agent-name}] {issue-type}: {description}
```

Examples:
- `[AI: spec-red-team] spec-gap: auth flow missing rate limiting`
- `[AI: security-reviewer] security-finding: SQL injection in parking/views.py`
- `[AI: red-team/codex] red-team-finding: session fixation in invite flow`
- `[AI: claude] feat: session summary pipeline`

The agent name is the agent that created the issue (e.g. `spec-red-team`, `security-reviewer`, `oversight-evaluator`, `claude` for a Claude Code session). This makes AI-created issues immediately recognisable in the issue list without having to open them.

**Every AI-created issue must also include a compact footer** at the end of the body:

```markdown
---
*🤖 Created by `{agent-name}` | Step: {N or "session"} | Branch: `{branch}` | {YYYY-MM-DD}*
```

The footer is lighter than the PR disclosure block — no model ID or structured table — because issues are log entries, not merge decisions. The step/branch fields provide the build context needed for triage and to understand whether the issue is still relevant if the branch is abandoned.

This requirement applies to all projects — HOS, CondoParkShare, and any other consumer repo. Omitting the `[AI: ...]` prefix or the footer is a protocol violation.

### Comments (PR + issue)

**Every comment an AI agent posts on a PR or issue — including review-thread replies — must open with an agent marker:**

```markdown
🤖 [AI: {agent-name}] …comment…
```

Agents run on a human's GitHub account (e.g. the HOS agent uses `ScottThurlow`), so without this marker an agent comment is *attributed to the human* and is indistinguishable from a human decision. This matters most for the **`needs-human` ⇄ `needs-ai` handoff**: a human's `Decision:` resolving a `needs-ai` issue must be visibly *not* agent text. The rule is therefore directional — the agent marks its own comments; a human comment (including a `Decision:`) is never prefixed by the agent. Omitting the marker is a disclosure violation, the same class as an unmarked AI-created issue or PR.

### Pull Requests

**Every PR opened by an AI agent — regardless of which agent, which tool, or which pipeline path — must include:**

1. **Title prefix:** `[AI: agent-name]` — e.g. `[AI: oversight-orchestrator]` or `[AI: claude]`
2. **Disclosure block** as the first section of the PR body:

```markdown
## 🤖 AI-Submitted Pull Request

This PR was **created and submitted by an AI agent**. A human did not manually write or submit this PR.

| | |
|---|---|
| **Agent** | `[agent-name]` |
| **Model** | `[model-id]` |
| **Submitted** | [YYYY-MM-DD] |
| **Step / context** | [build step N or session description] |

Human approval is required before merge.
```

3. **Commit trailers** on MEDIUM+ changes: `AI-Model:` and `AI-Risk:` in the commit message.

This requirement applies to every agent — `oversight-orchestrator`, `coder`, `Claude Code sessions`, and any other automated PR submission. Omitting it is a protocol violation. The PR template (`.github/PULL_REQUEST_TEMPLATE.md`) includes a reminder and the required format.

---

## Human handoff protocol — `needs-human` ⇄ `needs-ai`

Human review is **routed through labeled GitHub issues**, not by anyone watching the change stream. Every agent uses this two-state handoff so neither side has to guess whose court the ball is in:

**When YOU (an AI agent) need a human decision** — a spec/design/policy question outside your authority, a structural or CRITICAL authorization, a loosening request, anything you cannot resolve in your domain:
1. **File a GitHub issue** (with the AI-disclosure title prefix above) and apply the **`needs-human`** label. The label *is* the human's inbox.
2. State the decision needed precisely — ideally as a small set of options — so the human can answer in one pass. Then **halt the dependent work** and record the issue number where the escalating step expects it.

**When picking work back up** — at the start of an agentic session, and continuously in the standing daily job (#131):
1. **Scan open issues labeled [`needs-ai`](../../labels)** — these are issues a human has decided and handed back to HOS.
2. Read the human's decision from the comment opener **`Decision: <choice>`** (also honor `Action:` / `Disposition:` if present). Act on exactly that decision — do not re-litigate it.
3. When done, **close the issue** (referencing the commit/PR that implemented the decision) — **EXCEPT in a repo you don't own**: per `docs/CROSS-REPO-CONDUCT.md`, you never close in someone else's repo; comment with completion evidence and return the label/state to the owner, who disposes. If you genuinely need more input, swap it back to `needs-human` with a specific follow-up question — never leave it ambiguous.

**The human's side of the contract** (documented for completeness): to respond, remove `needs-human`, add `needs-ai`, and comment `Decision: …`. The human's job is to keep the `needs-human` queue empty; HOS's job is to keep the `needs-ai` queue empty.

> Do **not** treat a bare comment as a resume signal — only the `needs-ai` label means "a human has decided, proceed." A `needs-human` issue with new comments but no label change is still waiting on the human. This keeps the resume condition unambiguous and prevents an agent from acting on a half-finished human thought.

---

## Pipeline overview

```
START
  1. pm-agent      — spec review, surface ambiguities, human Q&A
  2. ux-designer   — design pack audit against full spec; fill all gaps;
                     produce docs/design/UX-DESIGN-READINESS.md
  3. architect     — technical feasibility review, human Q&A
                     (reads confirmed requirements + design readiness doc)

DESIGN
  4. technical-design ↔ architect  — iterate until design approved
                     (reads confirmed requirements + ADR + design readiness doc)

SPEC REVIEW (before coding starts)
  spec-red-team    — adversarial spec review (using agy) to find gaps

PER FEATURE — INNER DEVELOPMENT LOOP (repeats per incremental change)
  (Prompt → coder makes change → VERIFY locally → next prompt)
  Rule: never issue the next prompt on a broken working tree.
  Verify after every change: lint · type-check · unit tests in scope
  Only when inner loop produces clean working state → move to outer pipeline

PER FEATURE — OUTER PIPELINE (once per logical change set)
  5. coder  [commit only after inner loop is clean]
       ↓  (design pack gap? → ux-designer fills it; then coder continues)
  risk-assessor    — score risk, validate tier, generate inspection brief
       ↓             (invokes prompt-fidelity, dep-mapper, risk-historian)
  6. code-reviewer
       ↓ approved
  7. security-reviewer  ─┐
  8. privacy-reviewer   ─┤ parallel
  9. ui-reviewer        ─┤ → ux-designer (design pack gap or ambiguity)
 10. a11y-reviewer      ─┤ → ux-designer (token contrast failure / missing token)
 11. ops-reviewer*          ─┤ → ops-designer (telemetry spec gap)   *optional
 12. reliability-reviewer*  ─┤ → architect (structural reliability)  *optional
 13. infra-reviewer         ─┘ (infra files only)
       ↓ all approved
 14. unit-test      — configurable coverage + mutant score (default 80% / 75%)
       ↓ targets met
 15. system-test    — spec functional validation
       ↓
  oversight-evaluator    — check compliance & quality; recommend proceed/escalate
       ↓
  oversight-orchestrator — open PR with AI attribution, write panel context
       ↓
  cross-vendor panel     — independent adversarial review (agy, codex, etc.)
       ↓
  human gate             — resolve panel threads; merge PR

DEPLOY
 16. deploy-verify  — infra checks + browser smoke tests against live prod

SUPPORT (available on demand throughout the build)
  ux-designer          — (1) proactive: invoked after pm-agent at project start to
                         audit and complete the design pack against the full spec;
                         (2) reactive: answers design questions and fills gaps
                         for coder, ui-reviewer, a11y-reviewer throughout the build
  post-change-sweep    — after any change: categorizes diff by domain, drives all
                         relevant agents in dependency order

FRAMEWORK VALIDATION (run before committing agent/doc changes)
  framework-validator        — runs static + AI review; acts on findings
  framework-setup-validator  — confirms installation is correct in a new repo
```

---

## Agents

### 1. `pm-agent` — Product Manager

**Model:** `claude-sonnet-4-6`
**Invoked:** At project start (first agent); anytime a product/requirements question arises during build.

**Role:** Owns the spec. Answers "what should the product do?" questions. Never answers implementation or architecture questions.

**At project start:**
Reads all five spec files (`SPEC.md`, `SPEC-1-pilot.md`, `SPEC-2-subscriptions.md`, `SPEC-3-exchange-economy.md`, `DESIGN.md`) and surfaces every ambiguity, gap, or underspecified behavior in a single numbered list to the human. Does not proceed until the human has answered. The confirmed answers become a requirements supplement that feeds the architect.

**During build:**
Answers product questions from `technical-design`, `unit-test`, `system-test`, and `ux-designer` agents, citing the spec section. If the spec is silent, escalates to the human with a precise single question.

**Mid-build `spec-gap` response protocol:**
When a `spec-gap` issue arrives mid-build (not just pre-coding), pm-agent must:
1. Read the issue — understand what agent raised it and what decision it is blocked on
2. Classify the gap (clarifying / additive / structural)
3. Apply the spec update following the change-type process below
4. Notify the agent that raised the issue (via the sign-off register or direct invocation) that the spec is updated and it may proceed
5. Notify `architect` and `technical-design` of any additive or structural change so they can assess downstream impact

Do not close a spec-gap issue without updating the spec and notifying the blocked agent.

**Spec update path:**
When build discoveries or human decisions require the spec to be amended, `pm-agent` classifies the change and applies it:

| Change type | Definition | Process |
|---|---|---|
| Clarifying | Adds precision without changing behavior — makes the implicit explicit within what the spec already requires | Update spec directly; notify architect and technical-design |
| Additive | Specifies behavior that was **always implied by the spec** but not yet written — filling a gap, not introducing new behavior. A new requirement that did not exist before is structural regardless of size. | Update spec; notify architect and technical-design |
| Structural | Changes existing behavior, introduces new behavior, changes scope, or introduces a new user obligation, permission, or decision point. **When in doubt, treat as structural.** | Draft the change, present to human for approval **before** writing |

Never updates the spec to rationalize code that doesn't meet the original spec — that is a spec falsification.

**Escalation out:** Human (spec silent or structural change required).
**Escalation in:** `spec-gap` issues from `architect`, `technical-design`, `ux-designer` (routed up the chain — no *implementation-phase* agent reaches pm-agent directly except through the design chain). **Exception — `spec-red-team`:** it operates in the **spec phase, before any technical-design or code exists**, so it has no implementation-design chain to route through; it creates `spec-gap` issues directly for pm-agent by design. To prevent an architectural/implementation-scope gap from being resolved as a pure product decision, a `spec-red-team` issue that pm-agent judges to be technical or architectural in scope must get `architect` confirmation before pm-agent resolves it (pm-agent does not unilaterally classify a technical gap as clarifying/additive).

---

### 2. `architect` — System Architect

**Model:** `claude-opus-4-8`
**Invoked:** At project start (after `pm-agent` completes Q&A); as final escalation for technical disputes.

**Role:** Makes all architecture and technical decisions. Decisions are binding and final. All other agents operate within the bounds the architect sets.

**At project start:**
Reads the spec, the PM's confirmed requirements, and the ux-designer's `docs/design/UX-DESIGN-READINESS.md`. Having the complete design system upfront informs technical decisions — particularly rendering strategy, HTMX partial scope, and which views require server-side state for UI conditions. Identifies technical risks and open decisions: GiST exclusion constraint design, availability computation strategy, earned-horizon calculation placement, multi-tenant ORM scoping, PII encryption library, TOTP storage, web push architecture, Django admin extension strategy, Docker/Caddy networking. Asks the human any questions in a single list. After receiving answers, writes an Architecture Decision Record (ADR) to `docs/architecture/ADR-001-pilot.md`. This ADR is the input for `technical-design`.

**Design critique loop:**
Reviews every draft of the technical design document. Critiques harshly and specifically — "this is fine" is not acceptable output. Names specific failure modes and what must change. Iterates with `technical-design` until the design is sound.

**Dispute arbitration:**
When escalated disputes arrive from `coder`, `code-reviewer`, `security-reviewer`, or `technical-design`: makes a decision, states it clearly, names which agent must change course. If the dispute is actually a product question, redirects to `pm-agent` via `spec-gap` issue.

**Spec-gap escalation:**
When `technical-design` or a reviewer escalates a spec-gap that cannot be resolved at the design level (requires a product/requirements decision): create a `spec-gap` issue for `pm-agent`, halt the dependent work, and notify the escalating agent of the issue number. Do not resolve product questions within architectural authority.

**Escalation out:** Human (unresolvable after architect, or product/policy decisions); `pm-agent` via `spec-gap` issue (product/requirements decisions that cannot be resolved architecturally).
**Escalation in:** From `technical-design`, `coder`, `code-reviewer`, `security-reviewer`, `privacy-reviewer`, `a11y-reviewer`, `ui-reviewer`, `ops-designer`, `ops-reviewer` (spec gap unresolved after 2 cycles), `reliability-reviewer` (structural reliability issue), `unit-test` (coder refuses a testability refactor).

---

### 3. `technical-design` — Technical Design

**Model:** `claude-opus-4-8`
**Invoked:** After architect completes initial ADR; when coder has design questions.

**Role:** Translates the product spec and architectural decisions into a detailed technical specification that a coder can implement without ambiguity. Does not write application code — writes the spec for it.

**Inputs (read before acting):** `docs/architecture/ADR-001-pilot.md`, `docs/pm/CONFIRMED-REQUIREMENTS.md`, and `docs/design/UX-DESIGN-READINESS.md`. The readiness doc defines which UI states exist for each feature — technical-design uses this when specifying view contracts and HTMX partial boundaries.

**Produces:** `docs/design/TECHNICAL-DESIGN.md`, covering:
- Django model field names, types, constraints, and indexes — including GiST exclusion constraint DDL
- Multi-tenant ORM scoping strategy (custom managers, middleware)
- URL structure (`urlpatterns` skeleton for every view)
- View and form contracts (name, methods, auth requirement, HTMX vs. full-page — no implementation)
- Availability computation algorithm (exact query/ORM equivalent)
- Earned-horizon metric algorithm (only elapsed past hours, 180-day rolling window)
- TOTP and recovery code flow
- Notification dispatch architecture
- Admin surface design (Django admin extension vs. custom views)
- Right-to-erasure cascade

**Iteration:** Submits drafts to `architect` for critique. Does not release the design to the coder until architect approves.

**During build:** Answers coder's design questions. If a question reveals a gap, updates `TECHNICAL-DESIGN.md` and notifies the architect.

**Spec-gap routing (first receiver in the chain):**
When `coder`, `security-reviewer`, or `privacy-reviewer` escalates a spec-related gap, `technical-design` is the first handler:
- Gap resolvable at the implementation design level → update `TECHNICAL-DESIGN.md`; notify the escalating agent
- Gap requires an architectural decision → escalate to `architect`
- Gap requires a product/requirements decision (architect confirms) → create `spec-gap` issue for `pm-agent`; halt the dependent work

Do not bypass this chain — agents below technical-design in the hierarchy do not create `spec-gap` issues directly.

**Loop exit:** Iteration with `architect` has a maximum of 3 rounds. After 3 rounds without approval, escalate to human with a summary of unresolved decisions and competing options.

**Escalation out:** `architect` (design disputes, architectural questions; max 3 rounds then human); `pm-agent` via `spec-gap` issue (product decisions architect confirms cannot be resolved at design level).
**Escalation in:** From `coder` (design questions, spec ambiguity), `security-reviewer` (spec doesn't cover a threat), `privacy-reviewer` (spec doesn't cover a compliance requirement), `reliability-reviewer` (undefined reliability contract), `unit-test` (untestable designs, spec ambiguities), `system-test` (spec interpretation a test surfaces — routed here, not to pm-agent directly).

---

### 4. `coder` — Implementation

**Model:** `claude-sonnet-4-6`
**Invoked:** After `technical-design` is architect-approved; iteratively per feature.

**Role:** Writes production Django code. Follows `TECHNICAL-DESIGN.md` and the ADR. Does not decide what to build.

**Process:**
1. Reads the relevant section of `TECHNICAL-DESIGN.md` before writing.
2. Batches all questions for a section and asks `technical-design` before writing — not mid-implementation.
3. Writes code following the spec's build order (§12 of SPEC-1).
4. Submits to `code-reviewer`. Once code-reviewer approves, `security-reviewer` and `privacy-reviewer` run in parallel. Does not mark a section complete until all reviewers have approved.

**Key invariants enforced in code:**
- Every ORM query through a tenant-scoped manager — no raw cross-tenant queries.
- `select_for_update()` around booking creation.
- Every privileged admin action writes an `AdminAuditLog` entry.
- No PII in logs. No secrets in source. All hex colors via CSS tokens only.

**Spec-gap behavior:** When implementation reveals an underdetermined spec — two valid interpretations with different behavioral consequences, or a required behavior the spec leaves implicit:
- Minor ambiguity with an obvious safer interpretation → proceed with safer choice; note explicitly in self-flag output
- Meaningful behavioral ambiguity → halt; escalate to `technical-design` with both interpretations and their implications; do not proceed on assumption

**Escalation out:** `technical-design` (implementation design questions, spec ambiguity — first receiver in the chain); `ux-designer` (missing design token, component class, or UX pattern); `architect` (disputes unresolvable at design level).
**Escalation in:** From `code-reviewer`, `security-reviewer`, `privacy-reviewer`, `unit-test`, `system-test`.

---

### 5. `code-reviewer` — Code Review

**Model:** `claude-sonnet-4-6`
**Invoked:** After each coder pass.

**Role:** Reviews Django code for correctness, design adherence, and quality. Does not cover security or privacy — those are separate agents.

**Checks:**
- Implementation matches `TECHNICAL-DESIGN.md` exactly (names every deviation)
- GiST exclusion constraint present in migration, not just asserted in model
- Availability computation and horizon metric are correct
- One-active-booking gate correctly defined
- Bookings are hour-aligned
- Every ORM query that touches tenant data goes through the scoped manager
- Django admin views are tenant-scoped
- No premature abstractions; no dead code; no hard-coded config values
- HTMX responses return partials for `HX-Request`; full pages for direct navigation

**Output:** Every finding includes file/line, severity (`blocking` or `suggestion`), what is wrong, and what it must change to. Sends all findings in one pass. Explicit approval statement when no blocking issues.

**Escalation out:** `technical-design` (design disputes); `architect` (architecture disputes).
**Escalation in:** From `coder`.

---

### 6. `security-reviewer` — Security Review

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves (in parallel with `privacy-reviewer`).

**Threat model:** A registered resident attacking other residents or escalating privileges; an HOA admin attacking another tenant; an unauthenticated external attacker.

**Checks:**
- TOTP verified on every view requiring 2FA, not just at login; rate-limited
- Recovery code consumption is atomic (cannot be used twice under concurrent requests)
- Session invalidated on logout, password change, and account block; no session fixation
- Login form does not reveal whether an email exists
- Invite tokens and recovery codes use `secrets.token_urlsafe()`, not `random`
- Every view verifies `instance.organization == request.user.organization` (IDOR prevention)
- Operator console unreachable by non-superusers
- No raw SQL with string formatting; no `|safe` on user-controlled data
- CSRF middleware active; HTMX requests include CSRF token
- No secrets in source, templates, or logs
- `DEBUG = False`, `ALLOWED_HOSTS` restrictive, security headers set
- TOTP secret stored encrypted per ADR; time window tolerance ≤ ±1 step

**Output:** Each finding includes severity (critical/high/medium/low), CWE class, file/function, attack scenario, and specific remediation.

**Spec-gap routing:** When a finding reveals the spec doesn't cover a required security property (threat model gap, missing auth requirement, unspecified data boundary):
- Do not route directly to `pm-agent` — the spec gap may be resolvable at the design level
- Escalate to `technical-design` with the specific gap; technical-design determines if it's an implementation design fix or requires architectural/product decisions
- Continue up the chain as needed: technical-design → architect → `spec-gap` issue for pm-agent

**Escalation out:** `coder` (code fixes); `technical-design` (spec doesn't cover a threat — first receiver in the chain).
**Escalation in:** From `coder` (re-review after fixes).

---

### 7. `privacy-reviewer` — Privacy & GDPR

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves (in parallel with `security-reviewer`).

**Applicable framework:** GDPR (target EU hosting; possible EU data subjects in pilot).
**Core principle from spec:** "Hash what you only verify; encrypt what you must read back; minimize collection."

**PII inventory reviewed:**

| Data | Required handling |
|---|---|
| Email | Volume encryption at rest; TLS in transit |
| Display name | Volume encryption at rest |
| Phone | Field-encrypted (reversible); optional |
| Password | Argon2 one-way hash; never recoverable |
| TOTP secret | Encrypted per ADR |
| Recovery codes | Hashed after generation; shown once only |

**Checks:**
- Phone field is field-encrypted, not just volume-encrypted
- No PII field is hashed instead of encrypted (breaks read-back)
- Encryption key from environment; key rotation path exists
- No PII fields beyond those the spec defines
- `delete_user_pii()` function scrubs email/name/phone, anonymizes booking references, deletes TOTP and recovery codes, logs erasure in audit log
- Consent/lawful-basis notice shown before account creation
- Any admin view rendering resident PII writes an `AdminAuditLog` entry
- No PII in log output; `DEBUG = False` in production

**Spec-gap routing:** Same chain as `security-reviewer` — when a finding reveals the spec doesn't cover a required compliance property (retention policy, PII boundary, consent requirement): escalate to `technical-design` first; do not route directly to pm-agent.

**Escalation out:** `coder` (code fixes); `technical-design` (spec doesn't cover a compliance requirement — first receiver in the chain).
**Escalation in:** From `coder` (re-review after fixes).

---

### 8. `ui-reviewer` — UI & Design Conformance

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves.

**Role:** Verifies Django templates faithfully implement the design pack (`DESIGN.md` + `tokens.css`). Not visual taste — spec compliance.

**Checks:**
- No hard-coded hex values; all colors via `var(--token)` or provided classes
- `--meadow` and `--clay` not used decoratively — only for availability state signals
- Spline Sans Mono (`.mono`, `.spot-id`, `.data`) appears **only** on: spot IDs, time windows, permit-like values — not headings, body copy, or navigation
- One `.btn-primary` per view maximum
- `.badge-available` and `.badge-booked` include text labels, not color only
- `.bay` motif used only for: available spot framing, empty states, or logo — not as generic borders
- Voice/tone: plain active labels ("Book this spot", not "Submit booking request"); sentence case; no "monetize", "asset", "module", "leverage"
- Error messages explain what to do next ("No spots open then. Try a wider window.")
- Empty states invite action ("List the first spot in your building.")

**Escalation out:** `ux-designer` (design pack gap — missing token, component, copy pattern); `coder` (implementation bugs).
**Escalation in:** From `coder` (re-review after fixes); from `ux-designer` (re-review notification after design pack extension).
**Loop protocol:** When escalating a gap to `ux-designer`, state the specific missing element. After ux-designer fills the gap and notifies, re-review against the updated design pack. Maximum 2 cycles; escalate to human if unresolved.

---

### 9. `ux-designer` — UX Design Authority

**Model:** `claude-sonnet-4-6`
**Invoked:** At project start (after `pm-agent` completes Q&A); reactively throughout the build whenever any agent encounters a design pack gap.

**Role:** Owns and extends the design pack (`DESIGN.md`, `tokens.css`, `style-guide.html`, `feedback-states.html`). Answers design questions directly rather than escalating to the human. The design pack is a living specification — this agent completes it at the outset and fills gaps as new features are built.

**At project start:**

Reads the full spec (`SPEC-1-pilot.md`) and the pm-agent's confirmed Q&A output. Walks every user-visible feature in the spec and checks whether the design pack covers all required UI states: spot card states, booking gate-blocked states, authentication screens, onboarding flows, notification copy, leaderboard/gamification display, HOA and operator portal views, error and empty states, right-to-erasure.

For each gap found: fills it directly (additive/clarifying) or surfaces to the human (structural). After all gaps are filled, writes **`docs/design/UX-DESIGN-READINESS.md`** — a feature-by-feature coverage table, a log of every addition made, any open structural questions and their answers. The architect and technical-design agent read this document before starting their own work.

**During build (reactive):**

| Invoker | Reason |
|---|---|
| `coder` | Missing token or component class during template implementation |
| `ui-reviewer` | Gap found during template review (missing class, undocumented pattern) |
| `a11y-reviewer` | Token fails contrast check; accessible alternative needed |
| `technical-design` | New feature needs a UX pattern spec before technical design is written |
| `pm-agent` | Product decision has UX implications |

**Change classification (mirrors pm-agent's taxonomy):**

| Type | Definition | Process |
|---|---|---|
| Clarifying | Adds precision to an existing rule without changing meaning | Updates design pack directly |
| Additive | New token, component variant, or copy pattern | Adds to design pack; consults pm-agent if it affects a user flow; notifies a11y-reviewer for new color tokens |
| Structural | Changes a core color, removes a component, or changes the design brief. **Also structural** (per `ux-designer.md`): any change that introduces a new user decision point, new blocked/permission state, new completion criterion, or new step in a user flow — even if it feels small. When in doubt, treat as structural. | Presents to human for approval before writing |

**Additive is the normal operating mode.** Missing error color palette, a new badge variant, a copy pattern for an empty state — all handled without human involvement. **But a change that alters a user flow — a new confirmation step, a new blocked state, a new completion criterion — is structural, not additive**, regardless of how small the visual change is; it requires human approval. This doc must not use a narrower structural definition than `.claude/agents/ux-designer.md` (the authoritative source); the `oversight-evaluator` independently re-derives the mechanical structural signatures (contract §2a) so a flow change mislabeled additive is caught.

**After extending the design pack:** Notifies the invoking agent with the exact change; notifies `a11y-reviewer` for new color tokens; notifies `ui-reviewer` so it can re-check template conformance. Appends a one-line entry to the `## Change log` section of `DESIGN.md`.

**Escalation out:** `pm-agent` (design addition affects a user-visible flow, or reactive gap-filling reveals a spec-scope question not in the original spec); human (structural brand change — modifying core palette tokens, typeface, or design brief).
**Escalation in:** From `pm-agent` (at project start); from `coder`, `ui-reviewer`, `a11y-reviewer`, `technical-design`, `pm-agent` (during build).
**Loop exit:** ui-reviewer and a11y-reviewer escalation cycles have a 2-round maximum. After 2 cycles without resolution, escalate to human.

---

### 10. `a11y-reviewer` — Accessibility

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves.

**Compliance target:** WCAG 2.1 AA. Treats the design pack's quality floor as a build gate: keyboard focus, color never the only signal, `prefers-reduced-motion`, mobile responsiveness, WCAG AA contrast.

**Audit approach:** Lighthouse audit via Chrome DevTools MCP on each primary view (if dev server is running); plus static template analysis (grep for missing `alt`, unlabeled inputs, `tabindex="-1"` on interactive elements) in all cases.

**Key checks:**
- Every interactive element reachable by Tab in logical order
- Focus ring visible on every focused element; not overridden anywhere
- `.badge-available` / `.badge-booked` have text labels, not color only
- `--meadow-ink` (not `--meadow`) used for colored text on light backgrounds; same for clay
- `--slate` on `--canvas` meets 4.5:1 contrast ratio
- No animations outside `@media (prefers-reduced-motion: reduce)` guard
- Every `<input>` has a programmatic `<label>` (not just placeholder)
- Error messages associated via `aria-describedby`
- Touch targets ≥ 44×44px; no horizontal scroll at 375px viewport

**Escalation out:** `ux-designer` (design system ambiguity or token contrast failure); `coder` (implementation bugs).
**Escalation in:** From `coder` (re-review after fixes).

---

### 11. `ops-designer` — Observability Authority *(optional — projects with ops complexity)*

**Model:** `claude-sonnet-4-6`
**Invoked:** At project start, after `architect` completes the ADR. Reactive during the build when `ops-reviewer` escalates a gap.

**Role:** Authors and maintains `docs/ops/TELEMETRY-SPEC.md` — the observability contract that `ops-reviewer` enforces. Covers structured logging conventions, metric naming, distributed tracing requirements, health check requirements per dependency type, and dashboard/alerting intent. Does not implement instrumentation — records the contract for the build to follow.

**Escalation out:** `architect` (architectural observability decisions); human (structural observability architecture changes — switching telemetry backends, changing trace propagation strategy).
**Escalation in:** From `ops-reviewer` (spec gaps); `architect` (observability ADR inputs).

**N/A for:** CLI tools, libraries, scripts, or projects without background jobs, external integrations, or multi-service architecture.

---

### 12. `ops-reviewer` — Observability Review *(optional — projects with ops complexity)*

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves, in parallel with `security-reviewer` and `privacy-reviewer`, when changes introduce new operations, external calls, background jobs, async tasks, or failure paths.

**Role:** Reviews code changes for conformance with `docs/ops/TELEMETRY-SPEC.md`. Asks: "Can you tell what's happening and debug it?" Withholds sign-off on silent failures and spec violations. Escalates spec gaps to `ops-designer` (not coder — coder cannot be held to an unspecified requirement). Loop exit: after 2 failed re-reviews for the same gap, escalate to `architect`.

**Scope boundary:** Does NOT cover security audit logging (`security-reviewer`), GDPR/data retention logging (`privacy-reviewer`), or deployment config (`infra-reviewer`).

**Escalation out:** `ops-designer` (spec gap); `architect` (gap unresolvable after 2 cycles).
**Escalation in:** From `post-change-sweep`, direct invocation.

**N/A for:** Same projects as `ops-designer`. If `docs/ops/TELEMETRY-SPEC.md` is absent on a project with ops complexity, block and invoke `ops-designer` first.

---

### 13. `reliability-reviewer` — Resilience Review *(optional — projects with external connections)*

**Model:** `claude-sonnet-4-6`
**Invoked:** After `code-reviewer` approves, in parallel with `security-reviewer` and `ops-reviewer`, when changes introduce or modify outbound connections (DB queries, HTTP calls, queue operations, cache reads/writes).

**Role:** Reviews code for resilience against external dependency failures. Asks: "What happens when an outbound connection fails, times out, or returns an error?" Distinct from `ops-reviewer` (observability) and `security-reviewer` (security). Complementary: a system can be well-observed and secure but still brittle.

**Review dimensions:** timeouts on all outbound connections, retry with exponential backoff and limit, no tight retry loops, non-idempotent operations protected from accidental retry, graceful degradation / fallback, no unbounded waits (thread pools, connection pools, queue consumers).

**Escalation out:** `technical-design` (retry/timeout policy not specified in technical-design — first receiver; does **NOT** create a `spec-gap` issue directly, same as `security-reviewer`/`privacy-reviewer`); `architect` (structural reliability design — sync vs async, circuit-breaker architecture). `technical-design` revises the contract or routes product-policy questions onward.
**Escalation in:** From `coder` (re-review after fixes).

**N/A for:** CLI tools, libraries, or any project without outbound connections to external dependencies.

---

### 14. `infra-reviewer` — Infrastructure Review

**Model:** `claude-sonnet-4-6`
**Invoked:** Independently of `code-reviewer` (it reviews infra config, not application code) when infrastructure files are modified: Compose, Caddyfile, backup scripts, `.env.example`. An infra-only diff runs `infra-reviewer` directly; `code-reviewer` returns N/A.

**Role:** Reviews deployment configuration against the spec's §2 deployment requirements. Does not review application code.

**Checks:**
- All three services present (`web`, `db`, `caddy`); all with `restart: unless-stopped`
- DB port **not** published to host; DB on internal network only
- Postgres data on a **named volume**, not a host-mount path
- No secrets in `environment:` blocks; all via `.env` / `${VAR}` references
- Caddy: canonical domain via DNS-01; HOA alias via HTTP-01; no `tls internal`
- Both canonical and HOA alias in `ALLOWED_HOSTS`
- `.env.example` contains all required variables; `DEBUG` defaults to `False`; `DATABASE_URL` uses internal service name
- `pg_dump` backup script exists; output to NAS/external volume; retention policy present
- Portability: can the stack move to a new host by copying `.env` + restoring `pg_dump` + repointing CNAME?

**Escalation out:** `architect` (architecture decisions); human (deployment policy).
**Escalation in:** From `coder`, `deploy-verify` (infra failures post-deploy).

---

### 15. `unit-test` — Unit Tests

**Model:** `claude-sonnet-4-6`
**Invoked:** After all reviewers (`code-reviewer`, `security-reviewer`, `privacy-reviewer`, `ui-reviewer`, `a11y-reviewer`, `infra-reviewer`) have approved.

**Gates (both must be met before advancing):**
- Code coverage ≥ 80% (`coverage run` + `coverage report`)
- Mutant score ≥ 75% killed (`mutmut run` — Python mutation testing)

**Priority test areas:**
1. **Booking gate logic** — all three gates tested at boundaries (horizon, one-active-booking, DB overlap constraint triggered directly)
2. **Earned-horizon metric** — elapsed hours only, 180-day window, formula, cold-start grace, zero-history baseline
3. **Availability computation** — window splitting, clipping, fully-booked window
4. **Model constraints** — hour-aligned bookings, duration cap, organization scoping
5. **Auth flows** — TOTP valid/invalid/expired/reused; recovery code single-use; invite token single-use/expiry
6. **Right-to-erasure** — all PII scrubbed, bookings anonymized, codes deleted
7. **Admin audit log** — every privileged action writes exactly one entry with all required fields

**Tooling:** `pytest-django`, `coverage`, `mutmut`, `factory_boy`, `freezegun` (for time-dependent tests).

**Escalation out:** `technical-design` (untestable designs, **and spec ambiguities — via the design chain, not `pm-agent` directly**); `architect` (coder refuses testability refactor).
**Escalation in:** From `coder` (fixes that re-run tests).

---

### 16. `system-test` — System & Functional Tests

**Model:** `claude-sonnet-4-6`
**Invoked:** After `unit-test` meets both targets.

**Role:** Validates the application meets the spec's functional requirements. Tests are based on the spec, not the code. Uses Django test client (not Selenium) against a real test database.

**Covers every primary flow from SPEC-1 §11:**
- Full booking flow: search → horizon gate → one-active-booking gate → overlap gate → confirm → notifications
- Listing flow: availability window creation, elapsed hours accumulation (with `freezegun`)
- Cancellation/release: borrower pre-start, early release, owner-cancel with penalty
- Onboarding Mode A (invite): single-use link, TOTP enrollment, recovery codes
- Onboarding Mode B (approve): pending → approved → active
- Authentication: TOTP required; recovery code consumption; locked-out sessions
- Earned-horizon advancement: baseline, cold-start grace, formula verification
- HOA portal tenant isolation: cannot see another building's residents
- Operator console: full cross-tenant access; HOA admin cannot reach it
- Right-to-erasure: PII scrubbed, bookings anonymized, audit log entry
- Admin audit log: admin-cancel, PII access, block/unblock all logged

**When a test fails:**
- Code bug (code doesn't match design) → report to `coder` with test name, expected vs. actual, spec citation
- Spec gap → escalate to `technical-design` (the design chain — **not** `pm-agent` directly, per the no-bypass rule) with the two possible interpretations and which the test assumes; `technical-design` routes it to `architect`/`pm-agent` as the gap requires

**Escalation out:** `technical-design` (spec interpretation, via the design chain) → `architect`/`pm-agent` as needed; `coder` (code bugs).
**Escalation in:** From `coder` (fixes).

---

### 17. `deploy-verify` — Deployment Verification & Production Smoke Tests

**Model:** `claude-sonnet-4-6`
**Invoked:** After `docker compose up` on `opus.[your-domain]`.

**Role:** Verifies the production instance is correctly configured and functionally operational. Last gate before announcing a deployment successful.

**Phase 1 — Infrastructure:**
Remote checks (SSH to `parkshare-agent@opus.[your-domain]`): Docker services up and healthy, backup file exists and is recent (< 48h old).
Local checks (run from wherever Claude Code is): DNS resolution for canonical URL and HOA alias, TLS certificate valid and not expiring within 30 days, HTTP security headers present (`Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Content-Security-Policy`), DB port 5432 not reachable externally, HTTP → HTTPS redirect working.

Requires three environment variables in `.env`: `AGENT_SSH_KEY` (path to `parkshare-agent` private key), `AGENT_COMPOSE_PATH` (path to compose file on opus), `AGENT_BACKUP_DIR` (path to backup directory on opus).

**Phase 2 — Browser smoke tests (Chrome DevTools MCP):**
1. App loads; login form present; no console errors
2. Hanken Grotesk font loaded; `tokens.css` loaded (`--pine` CSS variable defined)
3. Invalid login returns error state, not 500 or Django debug page
4. HOA alias redirects to HTTPS without certificate error
5. PWA manifest served as valid JSON with required fields
6. `tokens.css` static file returns 200
7. Django admin login page loads

**Phase 3 — Backup verification:**
- Backup cron is registered
- At least one backup file exists and is non-zero

**Output:** Structured pass/fail table per check, overall PASS/FAIL, and specific remediation steps for any failures.

**Escalation out:** `infra-reviewer` + human immediately (infrastructure failures); `coder` + `system-test` (functional failures); human immediately (missing backups — deployment is not complete without verified backup).

---

### 18. `spec-red-team` — Spec Red-Team

**Model:** `claude-sonnet-4-6`
**Invoked:** Before coding begins on a build step (after the technical design is approved).

**Role:** Adversarially reviews spec sections before coding. Finds gaming vectors, contradictions, implicit assumptions, and missing edge cases.

**Process:**
1. Formulates 5–10 adversarial questions based on the spec section and technical design.
2. Invokes `agy` (Gemini) with an adversarial prompt to ensure vendor-independent analysis.
3. Reviews findings and creates `spec-gap` GitHub issues for genuine problems.

**Escalation out:** `pm-agent` (to resolve spec gaps).
**Escalation in:** None.

---

### 19. `risk-assessor` — Risk Assessor

**Model:** `claude-sonnet-4-6`
**Invoked:** After the coder completes a build step, before the internal review chain starts.

**Role:** Evaluates code changes to establish a validated risk tier and produce a ranked inspection brief for reviewers.

**Constraints:**
- Can only raise the coder's self-declared risk tier, never lower it (unless a human tier override exists).
- Must produce a ranked inspection brief.

**Process:**
1. Applies deterministic floor rules (e.g. auth/PII changes force HIGH tier, booking gate forces CRITICAL).
2. Runs static and IP validators (`run_validators.sh`, `prompt_audit_risk.py`, `ip_check.py`).
3. For MEDIUM+ steps, invokes the `prompt-fidelity` subagent. For HIGH+ steps, invokes the `dep-mapper` and `risk-historian` subagents.
4. Synthesizes risk scores to determine the final validated tier.
5. Produces a ranked inspection brief.

**Escalation out:** None (writes output to `.claudetmp/oversight/validators/risk-assessment.md`).
**Escalation in:** None.

---

### 20. `risk-historian` — Historical Risk Analyst

**Model:** `claude-sonnet-4-6`
**Invoked:** Subagent of `risk-assessor` (runs only at HIGH+).

**Role:** Queries GitHub issues and git logs to build a historical risk profile of changed files.

**Process:**
1. Queries GitHub issues matching specific risk labels (e.g., bug, security-finding, design-concern, spec-gap), **excluding `duplicate`-labeled issues** (a re-filed finding must not inflate density).
2. Analyzes git log churn (commits in the last 90 days) and fix commit density (commits matching fix/bug/error in the last 180 days).
3. Returns **raw counts and issue references plus a `Data confidence` field** — it does **not** classify risk. `risk-assessor` performs all risk classification from this raw data (per DECISIONS.md D31; a Haiku/Sonnet retriever must not make the judgment call). A future implementation must not add LOW/MEDIUM/HIGH classification here — that would violate the subagent boundary.

**Escalation out:** `risk-assessor` (reports raw findings).
**Escalation in:** `risk-assessor`.

---

### 21. `dep-mapper` — Dependency Mapper

**Model:** `claude-sonnet-4-6`
**Invoked:** Subagent of `risk-assessor` (runs only at HIGH+).

**Role:** Maps the project's dependency graph for changed files (imports, references, and framework wiring) to assess the blast radius.

**Process:**
1. Checks direct imports and references across the codebase.
2. Identifies framework-level implicit wiring (signals, events, middleware, views, templates).
3. Classifies the blast radius category and applies risk multipliers.

**Escalation out:** `risk-assessor` (reports findings).
**Escalation in:** `risk-assessor`.

---

### 22. `prompt-fidelity` — Prompt Fidelity Validator

**Model:** `claude-sonnet-4-6`
**Invoked:** Subagent of `risk-assessor` (runs only at MEDIUM+).

**Role:** Performs semantic comparison of prompt artifacts against generated code to verify faithful implementation.
**Status:** Designed and stubbed — **NYI (Not Yet Implemented)**. The stub returns `Status: NYI` and does **not** block or escalate; `risk-assessor` records the coverage gap in the inspection brief. It does not perform a best-effort comparison — a stub that returns plausible results would create false confidence (see the agent file's stub-behavior rule).

**Process:**
1. Verifies positive fidelity (implements all requirements).
2. Verifies negative fidelity (adheres to negative constraints).
3. Catches scope creep and prompt-code discrepancies.

**Escalation out:** `risk-assessor` (reports fidelity gaps).
**Escalation in:** `risk-assessor`.

---

### 23. `oversight-evaluator` — Oversight Evaluator

**Model:** `claude-sonnet-4-6`
**Invoked:** After all internal reviewers approve a build step and system tests pass.

**Role:** Evaluates compliance and quality of the build step review process.

**Process:**
1. Phase 1 (Compliance): Checks the sign-off register against the step manifest's required list. Confirms prompt-artifact compliance and checks for human authorization on CRITICAL steps.
2. Phase 2 (Quality): Reviews convergence failures (long reviewer loops, overrides), resolved critical findings, confidence gaps, second review findings.
3. Produces a final recommendation (`PROCEED`, `CONDITIONAL_PROCEED`, or `ESCALATE`).

**Escalation out:** `oversight-orchestrator` (via recommendation output).
**Escalation in:** None.

---

### 24. `oversight-orchestrator` — Oversight Orchestrator

**Model:** `claude-sonnet-4-6`
**Invoked:** After `oversight-evaluator` produces its recommendation.

**Role:** Acts on the evaluator's recommendation to open PRs, prepare panel context, or escalate compliance/quality issues to the human.

**Process:**
1. On `PROCEED`: Writes panel context (excluding internal findings) and full handoff docs, opens the PR with AI-PR attribution, and prints the panel command.
2. On `CONDITIONAL_PROCEED`: Same as PROCEED, but appends the "Human Review Required Before Merge" section.
3. On `ESCALATE`: Blocks PR creation and outputs specific escalation details and instructions to the console.

**Escalation out:** Human (on `ESCALATE` or missing human authorization).
**Escalation in:** None.

---

### 25. `framework-validator` — Framework Validation

**Model:** `claude-sonnet-4-6`
**Invoked:** Before committing any change to `.claude/agents/`, `docs/AGENTS.md`, `docs/OVERSIGHT-RUNBOOK.md`, or `scripts/framework/`.

**Role:** Runs the full framework validation suite and acts on findings. Does not review code — validates the agent pipeline structure itself.

**Process:**
1. Runs `scripts/framework/check_agents_static.sh` — structural checks, no AI. Must pass before proceeding.
2. Runs `scripts/framework/validate_agents.sh` — agy (consistency/completeness) + codex (adversarial gaps). Reads output from `.claudetmp/framework/validation-*.md`.
3. Runs `scripts/framework/validate_docs.sh` — checks documentation coverage and addresses findings.
4. Runs `scripts/framework/validate_spec_compliance.sh` (the script) to verify governance requirements; the `spec-compliance-validator` agent triages failures when the human invokes it.
5. Synthesizes findings: cross-vendor findings (both reviewers) are treated as MUST_FIX; single-reviewer findings are investigated before acting.
6. Triages fixes per the fixer triage (`contract/OVERSIGHT-CONTRACT.md` §6.0): it has `Write`/`Edit`, so it **fixes mechanical path/escalation-target errors in agent files directly** (it owns those). It **cannot invoke other agents**, so for structural fixes it routes/reports: escalation-chain breaks → human immediately; scope-creep risk → architect; agent system-prompt content/behavior → the owning agent via the human; framework-script logic changes → human approval (mechanical script fixes it may apply).

**Escalation out:** Human immediately (broken escalation chain); `architect` (scope-creep or responsibility gaps); domain owner agents for content fixes.
**Escalation in:** Invoked before committing framework changes; also invoked by `post-change-sweep` when framework files are in the diff.

---

### 26. `framework-setup-validator` — Framework Installation Check

**Model:** `claude-sonnet-4-6`
**Invoked:** After running `scripts/framework/install.sh` in a new repo; when troubleshooting a framework installation.

**Role:** Confirms the framework is correctly installed — required directories exist, all agent files are present, scripts are executable, `config.sh` is populated with non-placeholder values, and external CLIs (`agy`, `codex`) are available.

**Output:** Structured pass/fail report with exact remediation commands for anything missing. If all checks pass: "Framework is correctly installed. Run `scripts/framework/run_framework_validation.sh` to validate agent consistency."

**Escalation out:** Human (missing agent files that cannot be auto-created; CLI authentication required).
**Escalation in:** Invoked by human after install or when setup is broken.

---

### 27. `doc-validator` — Documentation Coverage Validator

**Model:** `claude-sonnet-4-6`
**Invoked:** Before committing documentation changes; by the human or orchestrating session when `framework-validator`'s Phase 3 (`run_framework_validation.sh`) **reports** doc issues (`framework-validator` has no Agent/Task tool — it reports, it does not invoke this agent itself).

**Role:** Catches the omission class of documentation bug — where a doc describes an agent correctly as far as it goes, but silently omits a mode, role, or escalation path the agent file defines. The authoritative source for each agent's behavior is its agent file; every doc reference is checked against that source.

**What it checks:** Mode completeness (agent has two operating modes; doc describes only one); pipeline position accuracy (proactive startup agents shown as "on demand" only); description frontmatter completeness; stale behavioral claims; cross-doc consistency.

**Knowledge base:** Reads `scripts/framework/doc-patterns.md` (known bug patterns from prior sessions) and `scripts/framework/decisions.md` (verification criteria from design decisions) before running. This is the mechanism that makes prior session context durable — decisions recorded in those files are actively checked, not rediscovered.

**After finding issues:** Follows the fixer triage (`contract/OVERSIGHT-CONTRACT.md` §6.0). **Mechanical doc-accuracy gaps** (a missing mode, a stale claim, a wrong path, a numbering error) it fixes directly — it has `Write`/`Edit` and corrects the doc *toward* the authoritative agent file, never the reverse. **Structural findings** (the agent definition is itself inconsistent, two agent files disagree, a documented behavior needs a tool/permission the agent lacks) it does not edit — it files a GitHub issue and escalates. Records any new doc-bug pattern discovered to `doc-patterns.md` before closing.

**Escalation out:** Human / GitHub issue (when a finding is structural rather than a doc-accuracy gap — e.g. a stale claim that reflects a genuine design change not recorded as a decision, or a capability the agent is documented to have but lacks).
**Escalation in:** From `framework-validator` (Phase 3 failure); invoked directly by human.

---

### 28. `spec-compliance-validator` — Governance Requirements Compliance

**Model:** `claude-sonnet-4-6`
**Invoked:** Periodically as a health check; after significant agent or methodology changes; by the human or orchestrating session when `framework-validator`'s Phase 4 (`run_framework_validation.sh`) **reports** compliance issues (`framework-validator` has no Agent/Task tool — it reports, it does not invoke this agent itself).

**Role:** The system-test equivalent for the agent pipeline — verifies the pipeline implementation satisfies its own governance requirements. Not "are the files consistent?" but "does the pipeline actually do what its governance spec mandates?"

**Governance sources checked:**
- `METHODOLOGY.md` — cross-vendor independence constraint, risk-tiered thresholds, human gates, model tier assignments, fail-closed behavior
- `AGENTS.md` (root protocol) — five mandatory authoring behaviors (risk flag, Human Review Required, confidence, hallucination warning, blast radius)
- `scripts/framework/decisions.md` — each decision's `Verification:` criterion checked against its stated implementation files

**Key requirements:**
- REQ-001: No Claude model in the independent reviewer seat (agy/codex only)
- REQ-002: agy fires at MEDIUM+; codex at HIGH+; fail-closed when unavailable
- REQ-003: Human gate mandatory at CRITICAL steps
- REQ-004: Opus for high-judgment agents (architect, technical-design); Sonnet for reviewers
- REQ-005: All iterative loops have defined exit conditions
- REQ-006–007: Five self-flagging behaviors enforced; prompt capture expected for **AI-authored** MEDIUM+ changes — required (hard) at CRITICAL/high-risk, conditional (human-verified) otherwise, N/A for human-authored changes (#122)
- REQ-008–009: Each `implemented` decision satisfies its verification criterion

**Escalation out:** Human immediately (cross-vendor constraint violated; human gate missing; decision marked implemented but failing verification; **missing loop exit in a consumer-project agent** — never escalated down-tier). Fixes directly with `Write`/`Edit` (it owns these): missing loop exit in a *framework* agent, wrong model assignment, and mechanical framework-script fixes (logic changes need human approval).
**Escalation in:** From `framework-validator` (Phase 4 failure); invoked directly by human.

---

### 29. `post-change-sweep` — Post-Change Orchestrator

**Model:** `claude-sonnet-4-6`
**Invoked:** After any batch of changes, before committing. The single entry point that triggers all relevant reviews.

**Role:** Reads the git diff, categorizes changed files by domain, and drives agents in dependency order across independent parallel tracks.

**Domain routing:**

| Domain | File patterns | Track |
|---|---|---|
| framework | `.claude/agents/*.md`, `docs/AGENTS.md`, `docs/OVERSIGHT-RUNBOOK.md`, `scripts/framework/**` | 1 (independent) |
| application code | `**/*.py` (excl. tests/migrations/scripts) | 2 (sequential: code-reviewer → parallel reviewers) |
| migrations | `**/migrations/*.py` | 2 (sequential: code-reviewer → parallel reviewers) |
| templates | `**/templates/**/*.html` | 2 (parallel with security/privacy after code-reviewer) |
| infrastructure | `docker-compose.yml`, `Caddyfile`, `*.env.example` | 2 (parallel, independent of code-reviewer) |
| tests | `tests/**/*.py`, `conftest.py` | 3 (independent) |
| design pack | `Specs/**/*design*/**` | 4 (independent) |
| spec | `Specs/*.md` | 5 (independent) |
| admin audit | `**/admin*.py`, `**/audit*.py`, `**/operator_console/**` | 2 (sequential: code-reviewer → parallel reviewers) |

Track 2 dependency: `code-reviewer` must approve before `security-reviewer`, `privacy-reviewer`, `ui-reviewer`, and `a11y-reviewer` run. `privacy-reviewer` is triggered if changed files touch accounts, PII fields, erasure logic, or data retention paths.

**Shell entrypoint:** `scripts/framework/run_post_change_sweep.sh` — categorizes changed files and prints the routing plan. The agent reads this and invokes the listed agents.

**Escalation out:** Human (framework-validator blocks); `coder` (code-reviewer blocks); human immediately (security-reviewer critical).
**Escalation in:** Invoked by human after any batch of changes.

---

## Escalation map

```
Human
  ├── pm-agent          (product decisions, structural spec changes)
  │     └── receives from: technical-design, unit-test, system-test, ux-designer,
  │                        spec-red-team
  ├── architect         (technical decisions, final arbiter)
  │     └── receives from: technical-design, coder, code-reviewer,
  │                        security-reviewer, privacy-reviewer,
  │                        a11y-reviewer, unit-test
  └── ux-designer       (design decisions — structural brand changes only)
        └── receives from: pm-agent (project start + during build),
                           coder, ui-reviewer, a11y-reviewer, technical-design

ux-designer
  ├── at project start: reads spec + confirmed requirements →
  │                     fills design pack gaps →
  │                     writes docs/design/UX-DESIGN-READINESS.md →
  │                     architect + technical-design may proceed
  ├── escalates to:  pm-agent (design addition affects a user-visible flow),
  │                  human (structural brand change — core palette or brief)
  └── notifies after every additive change: invoking agent, a11y-reviewer,
                                            ui-reviewer

ops-designer  *(optional)*
  ├── at project start: reads spec + ADR →
  │                     authors docs/ops/TELEMETRY-SPEC.md →
  │                     architect signs off → build steps may proceed
  ├── during build: fills spec gaps escalated by ops-reviewer
  │     ├── additive (already-covered component): update spec directly
  │     └── structural (new component, new dependency): escalate to architect
  │                                                     + require human auth file
  ├── escalates to:  architect (architectural observability decisions; max 2 rounds),
  │                  human (structural arch change or unresolvable after 2 architect rounds)
  └── receives from: ops-reviewer (spec gaps)

ops-reviewer  *(optional)*
  ├── escalates to:  ops-designer (spec gap — do not hold coder accountable),
  │                  architect (gap unresolvable after 2 ops-designer cycles)
  └── receives from: post-change-sweep, direct invocation

technical-design
  ├── escalates to:  architect (technical), pm-agent (product)
  └── receives from: coder, unit-test

coder
  ├── escalates to:  technical-design (design questions),
  │                  ux-designer (missing design token or component),
  │                  architect (disputes with reviewers)
  └── receives from: code-reviewer, security-reviewer, privacy-reviewer,
                     ui-reviewer, a11y-reviewer, unit-test, system-test

deploy-verify
  ├── escalates to:  infra-reviewer (infra failures),
  │                  coder (functional failures),
  │                  human (missing backups, unresolvable)
  └── triggered by:  human (after docker compose up)

spec-red-team
  └── escalates to:  pm-agent (spec gaps)

risk-assessor
  ├── invokes:       prompt-fidelity (at MEDIUM+), dep-mapper (at HIGH+),
  │                  risk-historian (at HIGH+)
  └── receives from: prompt-fidelity, dep-mapper, risk-historian

prompt-fidelity
  └── escalates to:  risk-assessor (fidelity gaps), human (missing prompt artifact)

oversight-evaluator
  └── escalates to:  oversight-orchestrator (compliance/quality recommendation)

oversight-orchestrator
  ├── escalates to:  human (on ESCALATE or missing human authorization)
  └── receives from: oversight-evaluator
```

---

## Applying to another project

**The recommended path is `scripts/framework/install.sh`.** It handles directory creation, file copying, config generation, and verification in one interactive run. See `docs/SETUP.md` for the full walkthrough and `docs/CUSTOMIZATION.md` for guidance on adapting agents to your stack and project.

### Quick reference — what gets copied

All files from `.claude/agents/` are copied verbatim. Current agent list (29 agents):

**Pipeline agents** (core build pipeline):
`pm-agent`, `architect`, `technical-design`, `ux-designer`, `coder`, `code-reviewer`, `security-reviewer`, `privacy-reviewer`, `ui-reviewer`, `a11y-reviewer`, `ops-designer` *(optional)*, `ops-reviewer` *(optional)*, `reliability-reviewer` *(optional)*, `infra-reviewer`, `unit-test`, `system-test`, `deploy-verify`

**Oversight agents** (risk scoring, second review, cross-vendor panel):
`risk-assessor`, `risk-historian`, `dep-mapper`, `spec-red-team`, `prompt-fidelity`, `oversight-evaluator`, `oversight-orchestrator`

**Framework agents** (pipeline self-validation):
`framework-validator`, `framework-setup-validator`, `doc-validator`, `spec-compliance-validator`, `post-change-sweep`

All agent files are copied — including the framework agents. Any project using this pipeline will customize agents, and the framework agents validate those customizations.

### Framework scripts

`scripts/framework/` contains the validation suite that every project gets:

| Script | Purpose |
|---|---|
| `install.sh` | Interactive install/update. Run once to set up, re-run to pick up framework updates. |
| `check_agents_static.sh` | Fast structural checks (no AI). Run in pre-commit or CI. |
| `validate_agents.sh` | agy + codex semantic review. Run when framework files change. |
| `run_framework_validation.sh` | Runs both in sequence. The single command before committing framework changes. |
| `run_post_change_sweep.sh` | Categorizes changed files and prints the agent routing plan. |
| `config.sh` | Generated by `install.sh`. Holds all project-specific values. Never edit manually — re-run `install.sh`. |

### Agent file format

Each agent file is a self-contained Markdown file with YAML frontmatter:
```markdown
---
name: agent-name
description: When to invoke this agent (used for routing)
model: claude-sonnet-4-6
tools:
  - Read
  - Write
  - ...
---

System prompt content
```

### Available model IDs (as of June 2026)
- `claude-opus-4-8` — Opus (most capable; use for architect and technical-design)
- `claude-sonnet-4-6` — Sonnet (strong reasoning; use for all reviewer/test/framework agents)
- `claude-haiku-4-5-20251001` — Haiku (fast; suitable only for pure retrieval/lookup with no judgment calls)

### Invoking agents

In Claude Code, type `@agent-name` to invoke a specific agent, or describe what you need and Claude Code will route to the agent whose `description` field best matches. Agents are invoked by the orchestrating session — they are not autonomous background processes.

### Project-start sequence

Once installed and configured, invoke agents in this order before writing any code:

1. `pm-agent` → `docs/pm/CONFIRMED-REQUIREMENTS.md`
2. `ux-designer` → `docs/design/UX-DESIGN-READINESS.md`
3. `architect` → `docs/architecture/ADR-001-pilot.md`
4. `technical-design` (iterated with `architect`) → `docs/design/TECHNICAL-DESIGN.md`

Do not begin build step 1 until `docs/design/TECHNICAL-DESIGN.md` is architect-approved. See `docs/OVERSIGHT-RUNBOOK.md` § "Project Start Sequence" and `docs/SETUP.md` for exact commands.
