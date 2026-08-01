# Ad-hoc dual-lens panel review — audit-approval-bot design (REQUIREMENTS/ADR/TECHNICAL-DESIGN-035)

**Date:** 2026-08-01
**Status:** AD-HOC MANUAL RUN — NOT the wired ADR-033 spec-review gate

## Why this is ad-hoc, not the real gate

ADR-033's dual-lens spec-review gate (`run_spec_panel.sh`, `spec_gate.py`, the `spec-completeness-review` agent) is not built yet — it is itself still mid-build (P1, issue #1136), and that issue sits in the v0.7.0 milestone, which the worker's cron is not currently targeting. Per explicit human authorization this session (*"Panel will be our adhoc approach since fix hasn't landed"*), the two lenses were run manually against this design bundle instead of through the real gate.

This means: **no machine-readable artifact schema, no fail-closed enforcement, no `unparseable`/`error`/`pass` distinction, no anti-tamper on lens selection, no `completeness_lens_class_differential` recording.** The review content below is real and was acted on, but its *execution* is not independently verifiable the way a wired gate's would be. Treat this file as durable evidence of what was reviewed and found, not as proof a gate ran.

## Bundle reviewed

- `docs/v0.6.0/REQUIREMENTS-035-audit-approval-bot.md` (pm-agent, plus a dated FR2 correction)
- `docs/v0.6.0/ADR-035-audit-approval-bot.md` (architect, through Revision 3 + confirmation)
- `docs/v0.6.0/TECHNICAL-DESIGN-035-audit-approval-bot.md` (technical-design, through Revision 2)

Design chain order: pm-agent → architect → technical-design → **[this panel]** → architect (Revision 3, resolving panel findings) → pm-agent (FR2 correction) → technical-design (Revision 2) → architect (confirmation pass). Both lenses ran once, against the DRAFT-1/Revision-1 state of the bundle; their findings drove the subsequent revisions. This file preserves the original findings, not a re-run against the final state.

## Lens 1 — Adversarial (agy, cross-vendor, Gemini)

Model resolution, availability, and invocation form: `agy --sandbox --continue`, staged across four turns (the combined bundle exceeded Linux's per-argument `MAX_ARG_STRLEN`, ~128KB, so the three documents were fed as separate turns in one continued conversation, with the review instructions given only after all three were loaded).

### Findings

**[gaming-vector] GitHub API Patch Truncation Bypasses Rule 6 Validation for Large Audit Files**
- What: The predicate relies on the `patch` string from GitHub's REST API, which is truncated for diffs exceeding ~300 lines/300KB without signaling truncation. The design didn't compare `additions` against the actual parsed added-line count.
- Why it matters: A large audit file where only the first ~300 lines are valid, followed by unvalidated/malicious content, would pass validation on the visible portion and auto-approve.
- Status: **Bound by architect (AD-17) and implemented by technical-design (§3.5 rule 8)** — patch-truncation now fails closed.

**[contradiction] `audit/automation/**` Allowlist Entry Contradicts the Fail-Closed Validator Rule**
- What: The allowlist included a path with no registered format validator, so it was simultaneously permitted and permanently unable to qualify.
- Status: **Resolved — dropped from the allowlist this iteration** (same treatment as `overnight-loop-log.md`), per architect AD-17/AD-6.

**[gaming-vector] Unrestricted Glob `audit/log/**` Allows Non-JSON Extensions and Hidden Dotfiles**
- What: The glob matched any extension under that path; a `.py`/`.sh`/dotfile whose content happened to parse as JSON would pass.
- Status: **Bound by architect, implemented by technical-design** — glob restricted to `*.json`/`*.jsonl`.

**[missing-edge-case] File Mode Changes and Symlinks with Zero Additions Bypass Validation**
- What: `additions == 0` skipped the added-lines check entirely, so a `chmod +x` or symlink conversion on an existing allowlisted file would qualify with nothing checked.
- Status: **Bound and implemented** — technical-design §3.5 rule 7 rejects zero-content mode/symlink-only changes.

**[contradiction] Event-Triggered Workflow Cannot Satisfy the Stuck-PR Escalation Requirement (FR16)**
- What: A webhook-triggered workflow runs once and terminates; nothing stays running to notice a sibling check subsequently failing or hanging.
- Status: **Bound by architect (AD-18)** — scheduled/cron sweep made mandatory, not optional, co-located with the producer component's cron slice.

**[implicit-assumption] Neither Predicate nor Gate Verifies the PR Target Branch is `main`**
- What: Nothing checked `base.ref == "main"`; an audit PR targeting a feature/release branch would still qualify and auto-approve.
- Status: **Bound and implemented** — target-branch check added as rule 0, inside the shared predicate so both call sites can't diverge on it.

**[missing-edge-case] Diff Header String Collision (`+++`) Silently Drops Added Audit Lines from Validation**
- What: A naive `line.startswith('+++')` filter would misparse a content line whose actual text starts with `+++` as a diff header and skip it.
- Status: **Bound and implemented** — stateful unified-diff hunk parser replaces the string-prefix filter, with a regression fixture.

### Adversarial lens verdict (as originally given, before the fixes above)

> The design core — using a deterministic, non-LLM Python identity combined with a shared pure predicate and an identity-bound CI gate exception — is architecturally sound and effectively solves the author/approver separation without introducing ruleset bypass actors. However, this bundle should go back to `technical-design` and `architect` briefly to fix the findings above before clearing `coder` to build.

All seven findings were addressed in the subsequent revision cycle (see "Disposition" above per-finding).

## Lens 2 — Completeness (Fable-class, same-family)

### Findings

**[HIGH, missing-scope] The Producer Half of the Mechanism Was Never Designed**
- What: The bundle designed the approver, the gate exception, the pre-PR-check exemption, and the bot's trigger — and removed the only existing producer (`bin/hos-cron:_sync_audit_logs`) — but no component created the branch, committed audit records, opened the PR, or armed auto-merge. "The overseer authors an audit PR" was asserted throughout as if that capability existed; it didn't.
- Why it matters: This is the exact "gate documented as executing with nothing executing it" failure class this repo has already found repeatedly (ADR-033's own VF-1/VF-2/VF-3; issues #1128, #1131) — a fully-built consumer half with no producer half. As drafted, the mechanism would ship inert.
- Status: **Resolved — the single most consequential finding of the whole review.** Architect ruled AD-15 (a named worker-identity producer component); technical-design built it as Component N.

**[HIGH, missing-scope] The Identity Model and Charter Documents Were Never Reconciled**
- What: `overseer.md:7` states *"Never opens branches or PRs"* — a direct conflict with the original design's requirement that overseer author the audit PR. Separately, `AGENT-IDENTITY.md` (a protected surface) defines exactly three identity classes with an explicit "why three, not four" rationale; the design introduced a fourth, approval-bearing identity that document didn't anticipate and never cited.
- Why it matters: As drafted, the overseer agent — following its own charter — would refuse the action the mechanism required of it. Post-ship, the canonical identity-model doc would describe three classes while the code enforced four.
- Status: **Resolved.** Architect ruled AD-16: the worker identity authors the PR instead (charter-consistent, no charter change needed), and the auditsync approver is formally declared a fourth identity class requiring a human-approved `AGENT-IDENTITY.md` amendment (Component M). This also surfaced that the requirements doc's FR2 was factually wrong ("no change from current behavior" — overseer authors no PRs today); pm-agent corrected it.

**[MEDIUM, missing-scope] No Remediation Path for Consumers Who Already Deployed the Old Bypass Instructions**
- Status: **Bound in-scope** — a detect-and-remove step for the live `hos-auditsync-hos` bypass actor added to the doc-reconciliation set.

**[MEDIUM, missing-scope] A Second Documented Audit-to-Main Path Survives Untouched (`OVERSIGHT-RUNBOOK.md` Phase 11)**
- Status: **Bound in-scope** — added as Component O.

**[MEDIUM, missing-scope] No Independent Liveness/Monitoring Story — Every Failure Detector Lives Inside the Mechanism It Monitors**
- Status: Freshness heartbeat bound in-scope (part of Component N); a fully independent *external* liveness monitor **deferred, linked to issue #1151** — not silently dropped.

**[MEDIUM, missing-scope] No Oversight of the Approval Bot's Own History; FR19's Durable Record Undefined Under a Stateless Runner**
- Status: **Bound** — the durable record is the audit-log append carried by the producer's own PR path, not runner-local disk.

**[LOW, missing-scope] Credential Lifecycle for the New Identity Is Absent**
- Status: **Deferred, linked to the #152 identity-separation lineage** — not silently dropped.

**[LOW, missing-scope] Unbounded Growth and the Emergency-Disable Path Are Both Left Unstated**
- Status: **Bound** — kill-switch (unsetting the recognized audit-bot login) named explicitly; chunking/size-limit story added to the producer component.

### Completeness lens verdict (as originally given)

> Two findings warrant sending back before the human's structural sign-off: the missing producer component... and the identity-model/charter reconciliation... The deployment-remediation and runbook findings should ride the same doc-change set but don't independently block. The liveness, FR19-writer, credential-lifecycle, and growth/kill-switch findings are appropriate to note as bounded follow-up items.

Both HIGH findings were resolved exactly as recommended, in the same revision cycle that addressed the adversarial lens's findings.

## Outcome

Neither lens's findings were dismissed or silently dropped — every finding above has an explicit disposition (bound-and-implemented, or deferred-with-a-named-issue). Two follow-up issues remain to be filed (an external liveness monitor linked to #1151; an App-key rotation policy linked to the #152 lineage) — not yet done as of this artifact, since `gh` authentication for issue creation happens outside the design-chain agents. The bundle, after this review cycle, is architecturally sound per both lenses and per architect's final confirmation pass; the remaining blockers to `coder` clearance are exclusively human decisions (structural sign-off, ESC-2 allowlist confirmation, ESC-3 merge-actor ruling), not design defects.

---
*Ad-hoc panel run by human-proxy, standing in for the not-yet-wired ADR-033 gate, per explicit human authorization. Committed here per the standing rule established this session: panel output must land in `research/sessions/`, never `.claudetmp/`, so the evidence survives across clones (see PR #1124 and TD-VF-10's citation-integrity finding for why this matters).*
