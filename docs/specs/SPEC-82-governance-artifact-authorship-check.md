# SPEC-82: Retrospective Audit of Governance-Artifact Authorship

**Status:** Revised — ready for architect re-review
**Issue:** #82
**Author:** pm-agent
**Date:** 2026-06-17

---

## 1. Problem Statement

Several governance artifacts in the HOS pipeline may only be written by
humans. The oversight-evaluator's Phase 1 check confirms their existence and
validates their required fields (contract §7, conditions 7 and 12). What it
does not do is verify that the last commit touching each artifact was actually
made by a human rather than an AI agent.

The specific artifacts and their human-only status:

- `.claudetmp/oversight/step{N}-human-authorization.md` — human must create
  this before the evaluator runs on CRITICAL steps (§7 condition 7)
- `.claudetmp/oversight/human-tier-override.md` — human-only; evaluator reads
  it but may never create it (§7 condition 11)
- `contract/gate-suspension.md` — "Must be created by a human (agents may not
  create or modify it)" (§3)
- `contract/tier-overrides/step{N}-human-tier-override.md` — SPEC-83; "HUMAN
  ONLY — agents must not create or modify any file here"

The evaluator's Human Authorization File Integrity section (oversight-evaluator
agent definition) acknowledges this gap explicitly: "As of now this is enforced
behaviorally, not mechanically — the same identity limitation documented in
`research/findings/human-gate-enforcement-limits.md` (AI and human commits
share one account, so signature-based enforcement isn't yet possible). The
prohibition is explicit and auditable (git history shows who created the file);
a mechanical guard is an open item."

This spec closes a portion of that open item. Because AI agents and humans
currently share git identity in the unattended worker setup (a single account
is used), full cryptographic proof of human authorship is not achievable within
the evaluator's reach. However, the worker introduces named bot accounts
(`OVERSIGHT_ACCOUNT`, `WORKER_ACCOUNT`, and related machine-account identities)
whose email addresses are known to the framework at evaluation time. A commit
made by one of those accounts touching a human-only governance artifact is a
credible tampering signal. Detecting it and surfacing it as a COMPLIANCE WARN
— rather than a COMPLIANCE FAIL — is the proportionate response: it is
accountability and tamper-evidence (the audit trail flags the anomaly for human
attention) without overclaiming cryptographic certainty.

---

## 2. Scope

This spec covers:

1. **Authorship-check logic in oversight-evaluator Phase 1**: for each
   human-only governance artifact that exists for the current step, the
   evaluator runs a `git log` check to determine whether the last commit
   touching that file carries an email address matching a known bot account.

2. **Known bot account list**: the set of email addresses the evaluator treats
   as bot-authored. The bot account usernames are sourced from `BOT_ACCOUNTS`
   in `scripts/framework/machine-accounts.env` (a space-separated list of
   GitHub usernames). The corresponding commit email addresses are carried in
   `BOT_WORKER_EMAIL` and `BOT_OVERSEER_EMAIL` in that same file. If those
   email fields are absent or empty, the check is skipped (fail-open).

3. **COMPLIANCE WARN (not FAIL) outcome**: a governance artifact whose last
   commit was authored by a known bot account produces a COMPLIANCE WARN and
   forces CONDITIONAL_PROCEED. It does not by itself produce a COMPLIANCE FAIL
   or ESCALATE, because the shared-identity limitation means the absence of a
   bot commit is not positive proof of human authorship, and the presence of a
   bot email may reflect an authorized machine-account action that was later
   misidentified.

4. **Audit event**: a new `governance-artifact-bot-commit` event emitted to
   `audit/oversight-log.jsonl` when the check fires.

This spec does NOT cover:

- Cryptographic signing or out-of-band human-identity verification. That
  remains an open item per `research/findings/human-gate-enforcement-limits.md`
  and is not in scope here.
- Expanding the human-only artifact list beyond the four artifacts named above.
  Additional artifacts (e.g., future governance files) may be added to the
  list via a spec update; this spec establishes the mechanism only for the
  existing set.
- Retroactive checking of governance artifacts from prior steps that have
  already merged. The check applies only to artifacts present and read during
  the current evaluator run.
- Changing the severity from WARN to FAIL. The boundary acknowledgment from
  SPEC-83 (accountability + tamper-evidence, not cryptographic forge-proofing)
  governs. Upgrading to FAIL would require resolving the shared-identity
  limitation first; that is a separate work item.
- Blocking or modifying what the bot accounts are permitted to commit. This
  spec only reads git history; it does not change access controls.
- The `.claudetmp/notifications/` or `.claudetmp/reviews/` directories — those
  are ephemeral working files that agents may write, not governance artifacts.

---

## 3. Requirements

### R1 — Known bot account resolution

**R1.1** The evaluator must resolve the bot account identifiers at runtime
from `scripts/framework/machine-accounts.env`. It must not hardcode any
account identifiers. The variable to read for bot usernames is `BOT_ACCOUNTS`
(a space-separated list of GitHub usernames). The variables to read for bot
commit email addresses are `BOT_WORKER_EMAIL` and `BOT_OVERSEER_EMAIL`.

**R1.2** The evaluator constructs the known-bot email set from `BOT_WORKER_EMAIL`
and `BOT_OVERSEER_EMAIL` as defined in `machine-accounts.env`. These are the
email addresses that appear in `git log --format="%ae"` for commits made by
the bot accounts. The requirement is that the set is non-empty when at least
one of those email variables is defined and non-empty.

**R1.3** If `BOT_WORKER_EMAIL` and `BOT_OVERSEER_EMAIL` are both undefined or
empty in `machine-accounts.env` (e.g., a project whose bot commit emails have
not yet been configured), the authorship check is **skipped entirely** for
that evaluation run. A project without configured bot email addresses has no
credible way to distinguish bot commits from human commits by email, so the
check is a no-op rather than a noise source. The evaluator must note:
"Authorship check skipped — no bot commit emails configured in
machine-accounts.env (BOT_WORKER_EMAIL and BOT_OVERSEER_EMAIL are unset)."

**R1.4** `BOT_ACCOUNTS` (the space-separated username set in
`machine-accounts.env`) is the canonical bot-identity list used by other
framework tooling (e.g. `require_human_approval.py`). The evaluator sources
the same file to stay consistent with the rest of the framework's bot
detection, but uses the `_EMAIL` fields — not usernames — for the `git log`
author-email comparison, since `git log --format="%ae"` returns email
addresses, not GitHub usernames.

### R2 — Artifact list and per-artifact check

**R2.1** The evaluator runs the authorship check for each of the following
artifacts if and only if the artifact exists at evaluation time:

| Artifact path | Variable/step substitution |
|---|---|
| `.claudetmp/oversight/step{N}-human-authorization.md` | `N` = current step |
| `.claudetmp/oversight/human-tier-override.md` | (none) |
| `contract/gate-suspension.md` | (none) |
| `contract/tier-overrides/step{N}-human-tier-override.md` | `N` = current step |

**R2.2** For each artifact that exists, the evaluator runs:

```bash
git log --follow --format="%ae %an" -- {artifact-path} 2>/dev/null | head -1
```

This returns the email and name of the author of the most recent commit that
touched the artifact. "Most recent commit" means the commit with the newest
author date that appears in `git log` output for that path, which `git log`
returns first by default.

**R2.3** If the command returns no output (the file exists on disk but has no
git history — i.e., it is untracked or was never committed), the evaluator must
emit a **COMPLIANCE WARN**:
"Governance artifact `{path}` exists but has no git commit history. It may
have been created without being committed (untracked working-tree file) or
may have been added to the index but not yet committed. Human-only artifacts
must be committed to be auditable."

This is a separate warn from the bot-email warn and targets the case where an
agent created the file in the working tree without committing it, which is the
simpler form of unauthorized authorship.

**R2.4** If the most recent commit's author email (`%ae`) is in the known-bot
email set (case-insensitive comparison against `BOT_WORKER_EMAIL` and
`BOT_OVERSEER_EMAIL`), the evaluator must emit a **COMPLIANCE WARN**:
"Governance artifact `{path}` — most recent commit authored by known bot
account `{bot_email}` (`{name}`). Human-only artifacts must be committed by a
human. Flagging for human verification. Commit: {git log output, abbreviated}."

**R2.5** If the most recent commit's author email is NOT in the known-bot set,
the evaluator records: "Governance artifact `{path}` — authorship check
passed (last commit: `{email}`, not a known bot account)." No compliance item
is emitted.

**R2.6** The authorship check must run **after** the existence and field-
validation checks for each artifact (i.e., after conditions 7 and 12 in Phase
1). It is a supplementary check on an artifact that already exists and already
passed field validation. If an artifact does not exist and its absence is
already a COMPLIANCE FAIL, the authorship check does not run for that artifact
(there is nothing to check).

### R3 — Outcome severity

**R3.1** Any authorship check warn (bot-email or untracked) from §R2 produces
a **COMPLIANCE WARN, not a COMPLIANCE FAIL.** This is the proportionate
response given the shared-identity limitation acknowledged in the evaluator's
existing Human Authorization File Integrity section.

**R3.2** A COMPLIANCE WARN from the authorship check forces the recommendation
to at minimum **CONDITIONAL_PROCEED**, with a conditional item requiring the
human to confirm the artifact was not created by an AI agent. The conditional
item text must name the artifact path and the suspicious commit author.

**R3.3** If the human-authorization file itself (`step{N}-human-authorization.md`)
triggers an authorship warn, the conditional item text must explicitly note
that the entire human-gate requirement for the step may not have been satisfied
by a human: "The CRITICAL step authorization artifact may have been authored by
a bot account. The human-gate requirement for step {N} may not have been
satisfied. Please confirm you created this file."

**R3.4** Multiple authorship warns on the same evaluation run (e.g., both
`gate-suspension.md` and `human-tier-override.md` carry bot commits) each
produce a separate conditional item. They do not merge into a single item.

### R4 — Audit event

**R4.1** When R2.4 fires (bot email detected), the evaluator must append one
audit event per artifact to `audit/oversight-log.jsonl`:

```json
{
  "event": "governance-artifact-bot-commit",
  "step": N,
  "artifact": "{path}",
  "bot_email": "{email}",
  "bot_name": "{name}",
  "commit_sha": "{abbreviated SHA}",
  "timestamp": "{ISO-8601}"
}
```

**R4.2** When R2.3 fires (untracked file), the evaluator must append:

```json
{
  "event": "governance-artifact-untracked",
  "step": N,
  "artifact": "{path}",
  "timestamp": "{ISO-8601}"
}
```

**R4.3** These events are appended to the audit log regardless of the final
recommendation (PROCEED, CONDITIONAL_PROCEED, or ESCALATE). They are research
records of the tamper-evidence mechanism firing, distinct from the compliance
outcome.

---

## 4. Acceptance Criteria

**AC1 — Bot account not configured: check skipped.**
Given `scripts/framework/machine-accounts.env` has no `BOT_WORKER_EMAIL` or
`BOT_OVERSEER_EMAIL` defined (or both are empty), when the evaluator runs
Phase 1, the authorship check is skipped and a note is emitted. No compliance
item is added.

**AC2 — Human-authored governance artifact passes.**
Given `contract/gate-suspension.md` exists, was last committed by a git email
not in the known-bot email set (i.e., not matching `BOT_WORKER_EMAIL` or
`BOT_OVERSEER_EMAIL`), and those email fields are configured in
`machine-accounts.env`, when Phase 1 runs, the artifact's authorship check
emits no warn and no conditional item.

**AC3 — Bot-authored governance artifact emits COMPLIANCE WARN.**
Given `contract/gate-suspension.md` exists and was last committed by an email
matching `BOT_WORKER_EMAIL` in `machine-accounts.env`, when Phase 1 runs, the
evaluator emits exactly one COMPLIANCE WARN naming the artifact and the bot
email, and the recommendation is at minimum CONDITIONAL_PROCEED. A
`governance-artifact-bot-commit` audit event is appended.

**AC4 — Untracked governance artifact emits COMPLIANCE WARN.**
Given `.claudetmp/oversight/step3-human-authorization.md` exists on disk but
`git log --follow -- {path}` returns no output (untracked), when Phase 1 runs,
the evaluator emits a COMPLIANCE WARN about the missing git history. No
`governance-artifact-bot-commit` event is emitted; a `governance-artifact-
untracked` event is emitted instead.

**AC5 — Bot-authored human-authorization file produces a named conditional item.**
Given `.claudetmp/oversight/step3-human-authorization.md` was last committed
by an email matching `BOT_WORKER_EMAIL` or `BOT_OVERSEER_EMAIL`, when Phase 1
runs, the conditional item text explicitly mentions that the CRITICAL step
authorization may not have been satisfied by a human (R3.3). The item names
the step number and the artifact path.

**AC6 — Authorship check does not run on a non-existent artifact.**
Given `contract/gate-suspension.md` does not exist (normal project — no
suspension needed), when Phase 1 runs, no authorship check is performed for
that artifact and no compliance item is emitted related to it.

**AC7 — Authorship check runs after field-validation checks.**
Given `.claudetmp/oversight/step5-human-authorization.md` exists but is
missing the required `Authorized by:` field (field-validation FAIL under
condition 7), when Phase 1 runs, the authorship check does not run for that
artifact (there is already a COMPLIANCE FAIL; authorship is moot). The field-
validation FAIL stands as the primary finding.

**AC8 — Multiple bot-authored artifacts produce separate conditional items.**
Given both `contract/gate-suspension.md` and
`.claudetmp/oversight/human-tier-override.md` were last committed by known bot
emails, when Phase 1 runs, two separate COMPLIANCE WARNs and two separate
conditional items are emitted — one per artifact.

---

## 5. Non-Requirements

**NR1 — No cryptographic signing.** This spec does not require GPG signatures,
SSH signing, or any out-of-band identity proof. The check is entirely within
git log author email and is acknowledged as tamper-evident rather than tamper-
proof.

**NR2 — No FAIL upgrade.** The severity is fixed at WARN for this spec.
Upgrading to FAIL is deferred until the shared-identity limitation is resolved.
See `research/findings/human-gate-enforcement-limits.md`.

**NR3 — No retroactive scan of merged history.** The check is applied only to
artifacts present during the current evaluator run. Prior steps that already
merged are not rescanned.

**NR4 — No change to what agents may or may not create.** The existing
prohibition on agents creating human-only artifacts is behavioral and unchanged
by this spec. This spec only adds detection, not enforcement.

**NR5 — No check on the content of the commit message.** The evaluator checks
only the author email, not the commit message, commit body, or any git trailer.
A bot account could in principle commit with a misleading message; email is the
simplest reliable signal available without external identity infrastructure.

**NR6 — No check on intermediate commits.** Only the most recent commit
touching the artifact is checked. A human who amends a bot-authored commit or
commits on top of it would pass this check. The check detects the most common
case (an agent creates the file de-novo); it does not detect all cases.

**NR7 — Squash-merge false positive is intentional fail-safe behavior.** Under
squash-merge workflows, the bot that performs the squash-merge becomes the
recorded commit author for all files in the merged branch, including any
human-only governance artifacts that were last touched by the human in the
feature branch. This produces a false-positive COMPLIANCE WARN: the artifact
was human-authored, but the squash commit carries the bot's email. This
false-positive is acceptable — WARN forces CONDITIONAL_PROCEED and requires
human confirmation, which is the correct fail-safe direction. The human's
confirmation resolves it. Projects that squash-merge regularly will see this
pattern and should expect it; suppressing it would require comparing against
the pre-squash branch history, which is out of scope for this spec.

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `.claude/agents/oversight-evaluator.md` Phase 1 | Additive | Add R2 authorship check after existing artifact existence/field-validation checks; add R3 conditional-item generation |
| `contract/OVERSIGHT-CONTRACT.md` §7 | Additive | Document authorship check as a new Phase 1 element (COMPLIANCE WARN severity; CONDITIONAL_PROCEED when fires); note known-bot-set resolution from `BOT_WORKER_EMAIL`/`BOT_OVERSEER_EMAIL` in `machine-accounts.env` |
| `contract/OVERSIGHT-CONTRACT.md` §6a | Additive | Add `governance-artifact-bot-commit` and `governance-artifact-untracked` event types to the audit-log event catalog |
| `scripts/framework/machine-accounts.env` | Additive | Document `BOT_WORKER_EMAIL` and `BOT_OVERSEER_EMAIL` fields used by the evaluator's authorship check (R1.1–R1.4) |

No existing required fields are renamed or removed. The evaluator's existing
Human Authorization File Integrity section is updated to note that a partial
mechanical guard now exists (bot-email detection), while preserving the
acknowledgment that full cryptographic forge-proofing remains an open item.

---

*Status: Revised — ready for architect re-review*
*Author: pm-agent | 2026-06-17*
