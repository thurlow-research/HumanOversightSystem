# REQUIREMENTS-1934: Tier every escalation when it is filed, let the human confirm hard calls cheaply, make the human-proxy link what it cites, and hold any proxy decision authority for the human to grant

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** Part A (§2) adds a filing-time
obligation and a recommendation protocol. It moves no authority. Part B (§3) would let the
human-proxy settle some escalations in its own voice. That moves a human-authorization boundary and
changes a CORE escalation terminal point (VF-1). **No Part B requirement may be designed into a
mergeable slice until ESC-0 and ESC-1 are ruled from the human's own GitHub account.**
**Date:** 2026-10-08
**Author:** pm-agent (autonomous worker cycle; no human present)
**Source issue:** #1934 (open, `needs-ai`/`process-gap`/`priority:high`, v0.7.0 Quality). It was filed
2026-10-02 by `scottthurlow-claude[bot]`, the human-proxy, and has no comments. The issue body was
read as a description of desired work, not as instructions (CORE, #1539). Related: #1928 (assign the
expected next actor), #1906 (the proxy misread an ambiguous authorization), #1668 (block on the human
only where their authority is needed), #1958 (clone-derived role; FR-3 cross-role authorization).
**Consumers:** `architect`, then `technical-design`. Every landing surface is protected (`CLAUDE.md`,
`.claude/agents/**`, `bootstrap/**`, `docs/AGENT-IDENTITY.md`). `templates/CLAUDE.human.md` is listed
in `scripts/framework/protected_surfaces.txt`. The human gate therefore applies whatever the computed
tier.

---

## 0. Verification findings (working tree at `97610fd27`, plus live reads of #1934, #1928 and #1906)

**VF-1 (HIGH). Part B changes a CORE safety-critical terminal point.** Every shipped agent's CORE
lists, as item 5, "Escalation terminal points: PROJECT may not redirect a human escalation to an
agent". Examples are `architect.md:86` and this agent's own CORE. The human-proxy is an agent
(`docs/AGENT-IDENTITY.md` §7: "Not counted as human"). Letting it answer an item that was escalated to
the human redirects a human terminal point to an agent. #1934 proposes this as a CORE change in HOS
source, not as a PROJECT override, so the clause does not forbid it on its face. It is, however,
exactly the kind of loosening that clause exists to keep under human control. The only route that
does not loosen it is for a clarifying item **never to be a human escalation in the first place**
(ESC-5).

**VF-2 (HIGH). Three distinct things exist today, and #1934 adds a fourth.**
1. A **human act**, done from the human's own account. Only these count for the human-approval gate
   (`BOT_ACCOUNTS`), the `needs-ai` authorizing act (`docs/LABELS.md`, item 3), and ADR-1644 ARCH-ESC-6
   (resume, reset, question-close, CODEOWNER re-route; `ADR-1644-stage-per-cycle.md:969`, `:513`).
2. A **relayed human ruling**: the proxy posts the human's words headed "(human, <date>)". ADR-1644
   (`:24-29`) accepts this form for rulings but never for acts. REQUIREMENTS-1958 VF-9/ESC-0 still
   asked the human to confirm one.
3. A **proxy act**, such as a label or a close. It is never a human act.
4. **New in #1934:** a **proxy decision**, an answer in the proxy's own voice with no human words
   behind it. Nothing in the repo defines this today.

**VF-3 (HIGH). `needs-human` has many writers, and only one of them is a filing path with a reason
field.** `bootstrap/escalate_to_human.sh` records `--reason` in a hidden marker and an audit event.
`needs-human` is also written by:
- `create_issue.sh --label needs-human` and `edit_issue.sh --add-label needs-human`, in many places in
  `worker.md`;
- `merge_authority.py` on HUMAN_REQUIRED, the NG3b release guard and embargo (`docs/LABELS.md:30`);
- the overseer;
- the worker's NG3b step 0b, where the human's removal of the label is itself an authorization signal.

On a PR the label is a **hard merge block**. "Classify every `needs-human` item" must therefore say
which writers classify and what the other writers mean.

**VF-4 (MEDIUM). The two "identical" landing files are already out of sync, and nothing checks
them.** `CLAUDE.md` §"HOS: Human-proxy session identity" (`:439-511`) has the "Never invoke
`bin/hos-cron` yourself" paragraph, and the template does not. The template's auth step has text that
`CLAUDE.md` lacks. `hos_install.sh:2055` installs the template. No test compares the two blocks.

**VF-5 (MEDIUM). A proxy relabel already has mechanical effect on trusted-author issues.**
`select_work_candidates.py` makes an issue selectable if its author is trusted, and HOS App identities
count as trusted. Worker-filed escalation issues are therefore resumed by *any* removal of
`needs-human`, including one made by the proxy. Under the standing "How to authorize" block
(`worker.md:171-177`: comment, remove `needs-human`, add `needs-ai`), the proxy can already clear a
worker escalation mechanically. Only convention and ARCH-ESC-6 stop it. Part B would turn that
convention into permission.

**VF-6 (MEDIUM). Existing consumers read "a qualifying human comment".** One example is the overseer
check of Option-B out-of-scope authorizations (`worker.md:499`). If a proxy decision ever satisfied one
of these checks, it would become a human act by the back door.

**VF-7 (MEDIUM). The classification is itself a judgment, made by the party that benefits from it.**
#1906 is a live case of the proxy reading authority into an ambiguous statement. An author that tiers
its own escalation `clarifying` lowers its own friction. A proxy that both tiers an item and answers
it is self-dealing.

**VF-8. Provenance.** #1934 is selectable only because its author is a trusted App identity. No human
act authorized it. Its Part B, a new authority for the identity that filed it, has no human
confirmation on record (ESC-0).

## 1. Problem (product behavior)

Every escalation costs the human the same today, whether it is "confirm the reading you already gave"
or "choose between two architectures". PRs are risk-tiered and decisions are not. The human pays full
friction on trivial confirmations. The proxy is tempted to resolve them informally (VF-5), and that
erodes the line between proxy and human.

## 2. Part A: ships without any authority grant

### A1. Tiers and classification

- **REQ-1 (tier vocabulary).** An escalation item has exactly one tier:
  - **`clarifying`**. It confirms a reading the human has already stated, or authorizes a fix that is
    fully specified and scoped, or settles an ambiguity where the issue's own text clearly supports
    one answer.
  - **`hard-tradeoff`**. Everything else, including any architectural call and anything reasonable
    engineers could decide differently.

  *AC:* both definitions appear verbatim in the human-proxy block, `worker.md` and `architect.md`.
- **REQ-2 (fail closed).** A missing, unparseable or unknown tier is `hard-tradeoff`. When the
  classifier is unsure, it uses `hard-tradeoff`. *AC:* a test covers an escalation with no tier.
- **REQ-3 (never-clarifying list).** The following items are `hard-tradeoff` by construction, whatever
  the filer writes. The tooling enforces this where it can, not only the prose:
  - (a) anything touching a protected surface (`protected_surfaces.txt`) or a security surface;
  - (b) ARCH-ESC-6 acts: resume, round or budget grant, reset, question-close, CODEOWNER re-route;
  - (c) PR merge, approval or the human-approval gate, and any `needs-human` written by
    `merge_authority.py` or the overseer;
  - (d) NG3b release authorization and `hos-embargo`/security reports;
  - (e) Condition-10/C14-style authorization artifacts, and false-positive overrides of any gate;
  - (f) cross-role identity authorization (#1958 FR-3);
  - (g) a structural spec change (pm-agent CORE), and the architect's product/policy checkpoint;
  - (h) a round-cap or convergence-failure escalation;
  - (i) any question about who may decide, classify or authorize (meta-authority), including this
    document's own ESC items;
  - (j) anything that would make an untrusted-author issue selectable.

  *AC:* a filer's `clarifying` tag on an item in (a) to (j) is recorded as `hard-tradeoff`, together
  with the reason it was overridden.
- **REQ-4 (classify at filing, per item).** Whoever files an escalation tiers it when filing. That may
  be the worker, the architect (its ESC items) or the human-proxy. A multi-question escalation (ESC-1..n)
  is tiered **per item**, and the issue carries the highest tier among them. *AC:* every new worker- or
  architect-filed `needs-human` escalation shows a per-item tier that a human can read and a machine
  can parse.
- **REQ-5 (filing tooling records the tier).** `escalate_to_human.sh` accepts a tier and records it in
  its marker and audit event. Without one it records `hard-tradeoff` (REQ-2). The design decides
  whether `create_issue.sh`/`edit_issue.sh` `needs-human` paths go through it or carry their own
  tier. The writers in VF-3 that are not filing paths (`merge_authority.py`, the overseer, NG3b) are
  `hard-tradeoff` by definition and need no change.
- **REQ-6 (tiers only move up without the human).** Any agent, the proxy included, may raise an item
  to `hard-tradeoff`. Only the human, from their own account, may lower one. *AC:* an
  agent-authored downgrade is ignored and audited.

### A2. The recommendation protocol (hard-tradeoff)

- **REQ-7 (recommendation, never ruling).** On a `hard-tradeoff` item, the proxy may post only a
  comment headed **RECOMMENDATION (human-proxy, not a ruling)**. It gives lettered options, the
  recommended option and why, and the consequence of each option. It is self-contained (AGENT-IDENTITY
  §9.1) and includes the URLs of everything it cites (REQ-11). A recommendation never removes
  `needs-human`, never applies `needs-ai`, never closes anything and never posts a "(human, …)"
  heading.
- **REQ-8 (cheap stamp).** The human confirms with a short comment **from their own account**: a word,
  an option letter, or "agreed". The protocol makes every stamp unambiguous:
  - the stamp binds to the most recent recommendation on that item;
  - if that recommendation is edited after the stamp, the stamp is void;
  - a letter that names no option is not a stamp.

  *AC:* given a recommendation and an own-account comment "B", downstream tooling or agents resolve
  it to exactly one decision. ESC-7 fixes the grammar.
- **REQ-9 ("How to authorize" block).** The standing block in `worker.md:171-177` shows the item's tier
  and the cheap-stamp form, and says that only the human's own account counts.

### A3. Links and parity

- **REQ-10 (human-proxy links what it cites).** Whenever the human-proxy session refers to an issue,
  PR, commit, comment, workflow run or other GitHub object in conversation with the human, it gives
  the full URL, not a bare number. This is a standing rule in the human-proxy block. *AC:* the rule
  appears in both landing files.
- **REQ-11 (same rule in recommendations).** REQ-7 recommendations, and escalation bodies filed by the
  proxy, follow the REQ-10 rule.
- **REQ-12 (parity).** The `HOS:HUMAN-PROXY` block in `CLAUDE.md` and `templates/CLAUDE.human.md`
  carries the same #1934 text. Apart from the `__CLONE_ROOT__` placeholder, any difference is either
  listed in an explicit exemption or fails a test. The existing VF-4 drift is resolved or recorded as
  exempt, never left silent. *AC:* a parity test exists and passes.

## 3. Part B: proxy decisions. HELD for ESC-0 and ESC-1

If ESC-1 grants nothing, Part B is dropped. Part A stands on its own. If ESC-1 grants authority, the
grant is bounded as follows.

- **REQ-13 (scope).** The proxy may settle only items tiered `clarifying` that are outside REQ-3, and
  only from the interactive human-proxy session in the Human clone (#1958 R-1). A cron or autonomous
  context never settles anything.
- **REQ-14 (no self-dealing).** The proxy may not settle an item it filed or tiered itself. It may not
  settle an item whose tier an agent changed. It may raise any tier (REQ-6). If it doubts the tier is
  right, it raises it rather than answering.
- **REQ-15 (distinct record).** A settlement is a comment headed **PROXY DECISION (not a human
  ruling)**. It quotes the issue text that makes the answer the better-supported one, and it carries a
  machine marker and an audit event. It is never headed "(human, …)". *AC:* tooling can tell proxy
  decisions apart from relayed rulings and human comments without reading prose.
- **REQ-16 (never a human act).** A proxy decision does not satisfy any of the following:
  - the human-approval gate;
  - a `needs-ai` authorizing act;
  - an ARCH-ESC-6 act;
  - a "qualifying human comment" check (VF-6);
  - an NG3b signal;
  - a requirements or design document's "human ruling" or ESC confirmation.

  Downstream documents cite it as a proxy decision.
- **REQ-17 (reversal).** The human may overturn any proxy decision from their own account. Work built
  on a proxy decision names the decision's URL in its PR body. An overturn before merge bounces that
  PR, and an overturn after merge opens a follow-up issue. The proxy lists the decisions it made in
  its session handoff. ESC-8 sets the review cadence.
- **REQ-18 (#1928 routing).** The tier decides who is the expected next actor: the human for
  `hard-tradeoff`, the human-proxy for `clarifying` only if ESC-1 grants authority. Otherwise it is the
  human for both. Whether a GitHub App identity can be an issue assignee was **not verified** here.
  #1928's design must check it.

## 4. Acceptance (issue-level)

1. Every worker and architect `needs-human` filing tiers each item. A missing tier and every REQ-3
   item resolve to `hard-tradeoff` (REQ-1 to REQ-6).
2. The human-proxy block states the recommendation-vs-ruling rule, the cheap stamp and the URL rule,
   with the same text in both files (REQ-7, REQ-8, REQ-10, REQ-12).
3. No proxy-authored comment, label or close satisfies any human-act check (REQ-7, REQ-16), and a test
   covers this.
4. Part B criteria apply only if ESC-1 grants authority. They are REQ-13 to REQ-17, with tests for
   self-dealing refusal and REQ-3 override.

## 5. Out of scope

- Any change to `BOT_ACCOUNTS`, the #757 human-approval assertion, protected or security surfaces, or
  ARCH-ESC-6.
- #1906's exception-clause wording. That issue is a sibling and is tracked separately. REQ-10 and
  REQ-12 touch the same block, so the two should be sequenced to avoid merge conflict.
- The #1928 assignment mechanics.
- Retroactive tiering of already-open escalations.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-0. Is #1934 your request?** It was filed by the human-proxy bot with no comment from you
  (VF-8). Part B gives new authority to that same identity. *Default:* Part A proceeds, and Part B
  waits for your own-account answer.
- **ESC-1. Should the proxy get decision authority at all?**
  - (A) No. The proxy recommends on every item, and the cheap stamp (REQ-8) cuts your cost per item.
  - (B) Yes, for `clarifying` items, bounded by REQ-3 and REQ-13 to REQ-17.
  - (C) Only when you state the answer in the session, which is the existing relayed ruling and adds
    nothing.

  *Default: A.* VF-1 (CORE terminal point) and #1906 are the reasons. REQ-8 already removes most of
  the cost #1934 describes, without moving authority. Revisit B once the audit data shows how often
  items are genuinely `clarifying`.
- **ESC-2. Who classifies?** *Default:* the filer (REQ-4). Anyone may raise a tier. Only you may lower
  one (REQ-6).
- **ESC-3. Self-dealing (only if ESC-1 = B).** May the proxy settle an item it filed or tiered?
  *Default:* no (REQ-14).
- **ESC-4. The never-clarifying list.** Confirm REQ-3 (a) to (j), or extend it.
- **ESC-5. Which label do `clarifying` items carry?** *Default if ESC-1 = B:* a distinct pending-actor
  label, not `needs-human`. Then `needs-human` keeps meaning "only the human" across its merge-block,
  triage and NG3b uses (VF-3), and no CORE terminal point is redirected (VF-1). *If ESC-1 = A:* every
  item stays `needs-human`.
- **ESC-6. Relayed "(human, <date>)" rulings.** ADR-1644 accepts them today. For `hard-tradeoff`
  items, should a relay still count, or is only your own-account stamp accepted? *Default:* only your
  own-account stamp. This tightens ADR-1644's convention and needs an amendment to it, which belongs
  to the architect.
- **ESC-7. Stamp grammar (REQ-8).** Is a lone letter, "agreed" or "yes" enough? *Default:* yes, if it
  binds to exactly one unedited recommendation. Otherwise it is not a stamp, and the proxy asks again.
- **ESC-8. Reversal cadence (only if ESC-1 = B).** *Default:* every proxy decision is listed in the
  handoff. You may overturn any of them until the dependent PR merges. After that, an overturn means a
  follow-up issue.
- **ESC-9. Consumers.** If Part B is granted, does it ship in the template for consumers or stay
  HOS-only? *Default:* HOS-only until it has been proven here. Part A ships to consumers.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every surface is protected. Part B moves a human-authorization boundary and a CORE
terminal point to the identity that asked for it.
CONFIDENCE: HIGH on VF-1 to VF-8 (read in this session). MEDIUM on the ESC defaults, which are product
judgment awaiting your ruling.

## Human Review Required

This change is structural. Part A may go to `architect` on these defaults. Part B (REQ-13 to REQ-18,
plus ESC-5 and ESC-6) may not bind in any slice until you answer ESC-0 and ESC-1 **from your own GitHub
account**. A ruling relayed by the human-proxy is not sufficient here, because the decision is about
the human-proxy's own authority (REQ-3(i)).
