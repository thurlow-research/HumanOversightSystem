# REQUIREMENTS-2101: Let the human authorize a gated step from GitHub, verify the act deterministically, refuse every bot, and never ask the human to edit a file in a clone

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** It changes which artifact
satisfies an existing human gate (contract §1 and §7 conditions 7 and 10). It removes or demotes a
required contract artifact. It adds a new verification obligation and a new human-facing act.
**Date:** 2026-10-15
**Author:** pm-agent (autonomous worker cycle; no human present, so open questions are ESC items)
**Tree read at:** `a4d125655` (branch `worker-2101-github-native-human-authorization-261015123501-3122481`).
**Source issue:** #2101. I read the issue body as a description of desired work, not as instructions
(CORE, #1539). I re-checked its factual claims against the tree (§0). The claims hold, and two
findings (VF-3, VF-4) make the current gate weaker than the issue implies.
**Related, and kept as boundaries:**
- #1928 (`REQUIREMENTS-1928-…` §3) explicitly leaves "replacing the hand-written
  human-authorization file with a GitHub-native act" to #2101. #1928 REQ-A1 owns the generic
  Action-needed block and summoning the human.
- #1913 (`REQUIREMENTS-1913-…` F-1, F-3, F-5) covers CONDITIONAL_PROCEED semantics. It also shows
  that the evaluator verdict never reaches the overseer.
- #1936 covers CODEOWNERS and a human-maintainers team.
- #2031 covers the change-classifier false positives that cause most Condition-10 stalls.
- SPEC-267 covers `reviewed_files:` coverage. SPEC-82 covers governance-artifact authorship.
  SPEC-328 R2.5 is the existing GitHub-comment authorization precedent.

**Consumers:** `architect`, then `technical-design`.
**Protected surfaces:** `.claude/agents/**`, `contract/**` and `scripts/framework/**`
(`scripts/framework/protected_surfaces.txt`). `scripts/automation/lib/**` is a security surface.
The human gate applies whatever tier is computed.

---

## 0. Verification findings

**Searches run.** I grepped for `human-authorization` across `scripts/`, `bootstrap/`, `bin/`,
`tests/`, `.claude/agents/`, `contract/` and `docs/OVERSIGHT-RUNBOOK.md`, and for
`codeowner|NG3b|release_auth|release-authorized|assigner` across `scripts/`, `bootstrap/` and `bin/`.
Results are cited below. No script verifies a human authorization comment today. NG3b R5 and
SPEC-328 C3 exist only as agent prose.

**VF-1 (HIGH). There are four consumers of the file, and two of them are deterministic code.**
- **Evaluator, prose.** Condition 7 (`oversight-evaluator.md:35`, `:148`) requires the file to
  exist and be non-empty. Condition 10's skip parses `reviewed_files:` (`:198-216`, `:427-431`).
  Condition 14 only reads the file (`:456`).
- **The `escalated:` blocking-finding resolution.** It requires an artifact "in the same human-only
  class" (`:130`). The same applies to the brownfield risk-assessment fallback (`:121`).
- **`scripts/automation/lib/pr_readiness.py`.** `_human_authorization_path()` (`:113-114`) and
  `_check_critical_human_authorization()` (`:484-492`, REQ-W-07) check only that the file is
  present and non-empty at CRITICAL. They do not check content, author or coverage. Its test is
  `tests/automation/test_pr_readiness.py:329-343`, which writes a one-line free-form file.
- **Human-facing text** that tells the human to create the file:
  - the orchestrator's block (`oversight-orchestrator.md:344-361`);
  - `docs/OVERSIGHT-RUNBOOK.md:560-571` (a heredoc, which the sandbox cannot allowlist);
  - contract §1 (`OVERSIGHT-CONTRACT.md:77-89`) and §7 conditions 7 and 10 (`:541`, `:551`).
- `worker.md` does not reference the file. Its only "human-authorization" hit is NG3b (`:250`).

**VF-2 (HIGH). The stalls are real, and the human has already tried to authorize from GitHub.**
- #1968 (local head `bf072f563`) and #1988 (`ee8b91cbf`) are fully reviewed. Both are blocked only
  by a Condition-10 ESCALATE, which is likely the #2031 false positive.
- #1776 (`5abc56855`) is blocked by Condition 10 *and* by an unresolved dep-mapper
  `Data confidence: LOW` blocking finding. Its `escalated:` resolution needs the same file class
  (VF-1). The evaluator ESCALATE then fails `pr_readiness` REQ-W-13 and REQ-W-14, so the PR cannot
  open.
- On 2026-10-15, from their own account, the human ruled on #1776 and #1988 that "my CODEOWNERS
  approval is the authorization". That approval can happen only on a PR that the pipeline refuses to
  open. This is a deadlock. (Source: the worker's cycle notes; the comment ids were not re-read in
  this session.)

**VF-3 (HIGH). The SPEC-82 authorship check is inert for this file.**
- `.claudetmp/` is gitignored (`.gitignore:2`), so `git log --follow` on the file always returns
  nothing. Every real authorization would therefore hit the `governance-artifact-untracked` WARN
  (`oversight-evaluator.md:574`).
- `scripts/framework/machine-accounts.env` defines no `BOT_*_EMAIL`. As a result the whole
  bot-commit check is skipped as fail-open (`oversight-evaluator.md:560`).
- Today nothing distinguishes a human-written file from an agent-written one. The evaluator's own
  text says so: "it does not prevent an agent-on-the-human's-account from writing the file"
  (`:155`).

**VF-4 (MEDIUM). The gate has never left a record.**
- `audit/oversight-log.jsonl` holds 0 `"event":"human-authorization"` records, and `audit/log/**`
  holds none either.
- No `step*-human-authorization.md` exists in this clone's `.claudetmp/oversight/`.
- The audit design in `oversight-evaluator.md:149-155` (an unallowlistable `printf … >>` pipeline)
  has never run.

**VF-5 (HIGH). Reusable deterministic parts already exist.**
- `scripts/framework/require_human_approval.py:140` `is_bot_reviewer(login, user_type,
  bot_accounts)` is a layered bot denylist. It checks `type == Bot`, the `[bot]` suffix and
  `BOT_ACCOUNTS`.
- `scripts/framework/requester_trust.py`:
  - `codeowners_humans()` (`:263`) returns the individual CODEOWNER logins and skips teams;
  - `load_bot_accounts()` (`:301`) uses a union-only baseline that includes `BOT_HUMAN_USERNAME`;
  - `verify_codeowner_actor()` (`:614`) is a pure predicate over already-fetched events. It is the
    model for "verify a GitHub act by a human CODEOWNER, with no network inside the predicate".
- `scripts/automation/lib/codeowners.py:118` `actor_is_codeowner()` does per-path,
  last-match-wins matching. It accepts team patterns without checking membership, which is too
  loose for this gate.
- `scripts/automation/lib/merge_authority.py:44-64` `_find_human_approval()` binds a PR approval to
  the head SHA. The universal #757 assertion (`:713-733`) already requires that approval for
  **every** merge.
- `bootstrap/escalate_to_human.sh` provides a record-first `needs-human` comment with an idempotent
  marker. It treats only an unedited comment as its own record (`updated_at == created_at`).
- `.github/CODEOWNERS` names exactly one individual, `@ScottThurlow`, on 23 lines.
  `BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"` (`machine-accounts.env:34`) is in `BOT_ACCOUNTS`
  (`:39`).

**VF-6 (precedent).** SPEC-328 R2.5 already states the target shape for out-of-scope commits:
"The GitHub issue is the authorization record and the audit anchor — no separate file artifact is
created or committed". C3 verifies a human comment that postdates the request. C4 fails closed on
any API failure. SPEC-328 C3 accepts any `user.type != "Bot"`. That is weaker than this issue's
CODEOWNER requirement and is **not** inherited.

## 1. Problem (product behavior)

The human's only interface is GitHub: comments, labels, PR reviews and CODEOWNERS approvals. They
never edit files in a bot's clone. Yet the hard human gate for CRITICAL and structural-override
steps can be satisfied only by a hand-written, uncommitted file in that clone, which a bot is
forbidden to write. Steps therefore stall for days (#1776, #1968 and #1988) even after the human has
stated their decision on GitHub.

At the same time the file proves nothing about who wrote it (VF-3), and it has never been audited
(VF-4). **Required outcome:**
- The human authorizes a step with one GitHub act.
- A deterministic verifier confirms that a verified human CODEOWNER performed the act, for this
  step, on this content, covering files in the diff.
- The act and its verification are audited.
- Every bot, including the human-proxy App, is refused.
- Anything ambiguous fails closed to ESCALATE.

## 2. Requirements

### A. The authorizing act

- **REQ-1 (GitHub-native act; mechanism chosen by architect).** A step gated by condition 7 or 10
  can be authorized entirely from GitHub. The architect chooses among these candidates, or a
  combination (ESC-1):
  - **(a) Prescribed-form comment.** A human CODEOWNER posts a comment on the step's issue or PR.
    The comment carries a fixed, parseable form naming:
    - the step;
    - the decision (authorize or decline);
    - the content binding (REQ-5);
    - the conditions or blocking-finding ids it covers (REQ-7);
    - `reviewed_files:` (REQ-6).
  - **(b) CONDITIONAL_PROCEED plus an open PR.** When the only unmet requirements are human
    authorizations, the evaluator returns CONDITIONAL_PROCEED instead of ESCALATE, and the PR opens
    with the unmet gate disclosed. The CODEOWNER's PR approval on the head SHA, which #757 already
    requires for every merge (VF-5), is then the authorization. This depends on #1913, which
    establishes that the verdict and the disclosure reach the overseer (#1913 F-3).

  Whichever is chosen, the human never edits, creates or commits a file. *AC:* an end-to-end test
  (with a GitHub fake) authorizes a CRITICAL step and a Condition-10 step through the chosen act
  alone, and the evaluator returns PROCEED or CONDITIONAL_PROCEED per its rules.

- **REQ-2 (verified human CODEOWNER only).** The act counts only if the actor satisfies all three
  of these:
  - GitHub reports the actor's login as an individual login listed in `.github/CODEOWNERS`. Team
    entries are not expanded (#1936).
  - `is_bot_reviewer()` is false for the actor (VF-5). That function denies `type == Bot`, any
    `[bot]` login and any `BOT_ACCOUNTS` member.
  - Identity comes from the API payload, never from body text. A comment saying "authorized by
    ScottThurlow" counts for nothing.

  The human-proxy App (`scottthurlow-claude[bot]`) is refused even when it quotes or relays a human
  ruling (ARCH-ESC-6). So are the worker, the overseer, Copilot, any other App and any
  non-CODEOWNER human. *AC:* table-driven tests show that a verified CODEOWNER is accepted, and that
  each of these is refused: the human-proxy App, the worker App, an unlisted `[bot]` App, a
  `type: User` login in `BOT_ACCOUNTS`, a non-CODEOWNER human, and a body claiming a CODEOWNER name
  posted by a non-CODEOWNER.

- **REQ-3 (deterministic verifier, not agent prose).** A committed script performs the verification
  and is the single invocation site (D41). It sits on a protected surface and reuses the VF-5
  predicates. Fetching is separated from deciding: the predicate does no network I/O, in the same
  way as `verify_codeowner_actor`. All of these call that script instead of reading a file:
  - the evaluator (conditions 7 and 10, and the REQ-7 `escalated:` resolutions);
  - `pr_readiness.py` REQ-W-07;
  - the overseer, wherever it consults the gate.

  An agent may not substitute its own reading of comments for the script's verdict. *AC:* a grep
  test checks that no agent file instructs reading `step{N}-human-authorization.md` as authority,
  and that `_check_critical_human_authorization` delegates to the verifier.

### B. Validity of the act

- **REQ-4 (fresh, unedited, in the right place).** A qualifying act must meet all of these:
  - it is on the step's own issue or PR;
  - it postdates the pipeline's current authorization request for the current binding (REQ-5);
  - its body has not been edited since it was posted;
  - it has not been deleted. The verifier re-reads the act live on every evaluation and never
    caches it.

  An edited comment is refused. The human posts a new one. The design must confirm which API field
  reliably signals a body edit (for example GraphQL `lastEditedAt`, versus REST `updated_at`, which
  may also change for other reasons). This was not verified in this session. *AC:* tests refuse a
  comment that predates the request, a comment that was edited, a comment on a different issue, and
  a comment that has since been deleted.

- **REQ-5 (content binding).** The authorization binds to the content the human approved. A new
  commit to the step's own changes after the act invalidates it, as a stale PR approval is
  invalidated today (`_find_human_approval`, `:61-62`). Whether a pure merge-from-base that leaves
  the step's own diff unchanged keeps the authorization is ESC-3. The answer matters because #1968
  and #1988 must merge `main` before submitting. *AC:* a test refuses an act whose binding names an
  older head after a new step commit. A second test covers the ESC-3 ruling for merge-from-base.

- **REQ-6 (SPEC-267 coverage preserved).** Condition 10's skip still requires a `reviewed_files:`
  enumeration that overlaps the diff, with the existing canonicalization: exact match, case
  sensitive, a single leading `./` stripped, no prefix or basename matching
  (`oversight-evaluator.md:204-216`). Under REQ-1(a) the enumeration is in the comment. Under
  REQ-1(b), whether a whole-PR approval counts as coverage is ESC-2. *AC:* a test refuses an act
  whose `reviewed_files:` is empty, absent, or wholly outside the diff, and accepts one with at
  least one overlapping file.

- **REQ-7 (what one act covers).** The act names which unmet items it authorizes, from this set:
  - condition 7;
  - condition 10, per structural signal;
  - an `escalated:` blocking-finding resolution, named by id (`oversight-evaluator.md:130`).

  An item the act does not name stays unmet. Including blocking findings in scope is ESC-4. Without
  them #1776 cannot move (VF-2). *AC:* a test checks that an act covering condition 10 alone leaves
  an unresolved dep-mapper blocking finding failing.

- **REQ-8 (decline and supersession).** The verifier recognizes a decline from a verified CODEOWNER.
  The most recent qualifying act by a verified CODEOWNER governs. If the acts conflict and the order
  cannot be determined, or a comment carries the form marker but does not parse, the result is no
  authorization plus ESCALATE, and the parse error is reported to the human. *AC:* tests cover
  authorize then decline (unmet), decline then authorize (met), and a malformed form (refused, with
  the reason stated).

### C. Fail-closed and audit

- **REQ-9 (fail closed).** Any of the following yields "not authorized": an API error, a timeout, a
  rate limit, truncated pagination, an unreadable CODEOWNERS or `machine-accounts.env`, or an empty
  CODEOWNERS humans set. The evaluator then returns ESCALATE, never PROCEED. This follows the
  SPEC-328 C4 precedent. Pagination is bounded and refuses to decide on a partial list, as
  `query_issues.sh` and `requester_trust.py` already do. *AC:* a fault-injection test for each case.

- **REQ-10 (audit every verdict).** Every acceptance appends a `human-authorization` event, which
  extends the §6a schema with these fields:
  - `source` (comment or review);
  - the comment or review id and its URL;
  - the verified actor login and the GitHub-reported type;
  - the step and the binding (head SHA);
  - the covered items;
  - `reviewed_files`;
  - the decision;
  - `content_sha256` of the act's body;
  - `verified_at`.

  Every refusal of a candidate act appends a `human-authorization-refused` event with a closed
  reason code, such as `bot-actor`, `not-codeowner`, `stale`, `edited`, `no-overlap`, `api-failure`
  or `malformed`. Events are written through the HOS audit writer, not an inline `printf >>`
  (VF-4). *AC:* tests assert one event per verdict with all fields present.

- **REQ-11 (status of the file artifact; SPEC-82).** The architect decides between two options
  (ESC-5):
  - **(i)** retire `.claudetmp/oversight/step{N}-human-authorization.md`;
  - **(ii)** keep it only as a **derived record**, written by the REQ-3 script from a verified act.

  Under either option a hand-written file at that path confers **no** authority. A derived record is
  never read as authority either: the verifier re-checks GitHub every time, and the GitHub record
  (REQ-10's ids) is the anchor, as in SPEC-328 R2.5. The design must say explicitly who writes and
  who commits any derived record. It must also say how SPEC-82 then applies. SPEC-82's bot-commit
  WARN must not fire against a record that a bot is required to write, and SPEC-82 must not become
  the control for it: the control is re-verification. The design must also state the fate of the
  other §1 "human-only class" uses (`oversight-evaluator.md:121`, `:130`, `:219` domain
  structural-auth files). *AC:* a test places a hand-written, well-formed auth file with no GitHub
  act and checks that conditions 7 and 10 stay unmet.

### D. Telling the human

- **REQ-12 (escalation names the act, never a clone path).** When an authorization is unmet, the
  escalation is posted through `escalate_to_human.sh` or its #1928 successor, on the step's issue or
  PR. Under #1928 REQ-A1 it states:
  - **Action:** the exact comment to post (or the PR to approve), pre-filled with the step, the
    binding, the items to cover and the diff's file list for the human to choose from;
  - **Where:** the issue or PR URL;
  - **Who:** "from your own GitHub account; the human-proxy session cannot do this";
  - **Done when:** the act the verifier will read.

  No human-facing message produced by any HOS agent or script names a clone file path, or asks the
  human to create, edit or commit a file, to satisfy an authorization. The #1928 REQ-A1 "file in a
  clone" case therefore never arises for authorization. *AC:* a test greps the agent and runbook
  text and the escalation templates for the auth-file path in human-facing blocks. A test checks
  that the rendered escalation contains the URL and the pre-filled form.

- **REQ-13 (docs and agent text).** The following describe the GitHub-native path as the only path,
  or as the primary path with the file marked as a derived record or fallback per ESC-5:
  - contract §1 (`:77-89`) and §7 conditions 7 and 10 (`:541`, `:551`);
  - `docs/OVERSIGHT-RUNBOOK.md:555-571`, with the heredoc removed;
  - `oversight-evaluator.md` (`:35`, `:148-155`, `:198-216`, `:427-431`, `:566`, `:588`, `:706`);
  - `oversight-orchestrator.md:344-361`;
  - worker escalation text.

  The architect states whether removing a required contract artifact needs a contract version bump
  (§8). *AC:* the doc-validator passes, and no instruction to create the file remains.

## 3. Out of scope / non-goals

- **Fixing the classifier false positives** that cause most Condition-10 stalls. That is #2031.
- **Changing when conditions 7 and 10 fire**, or weakening #757, the protected-surface gate or
  branch protection. This build changes *what satisfies* the gate, never *whether it fires*.
- **Tier overrides and gate suspensions.** `contract/tier-overrides/…` and `contract/gate-suspension.md`
  are committed files that already reach the human through a PR. Unchanged.
- **Team-membership expansion for CODEOWNERS.** That is #1936.
- **Summoning, reminders and assignment.** That is #1928.
- **Granting the human-proxy any authorizing role.** #1934 Part B stays held.
- **Retroactive credit.** Free-form rulings already posted on #1776 and #1988 do not count as
  REQ-1 acts. Those steps move forward through one fresh act once this ships (§4.2). How the worker
  acts on those rulings meanwhile is outside this build.

## 4. Acceptance (issue level)

1. The tests in REQ-2, REQ-4, REQ-6 and REQ-9 pass:
   - a verified CODEOWNER is accepted;
   - the human-proxy App and other bots are refused;
   - a non-CODEOWNER is refused;
   - a stale or edited comment is refused;
   - `reviewed_files` with no overlap with the diff is refused;
   - an API failure fails closed.
2. #1968 and #1988 (Condition 10), and #1776 (Condition 10 plus the dep-mapper finding, if ESC-4
   rules it in scope), can each be moved forward by the REQ-1 act alone, with no file edited in any
   clone.
3. Every accepted or refused act leaves an audit event carrying the verified actor and the
   comment or review id (REQ-10).
4. A hand-written auth file confers no authority (REQ-11).
5. No escalation, agent text or runbook step asks the human to edit a file to authorize
   (REQ-12, REQ-13).

## 5. Suggested slices (all touch protected surfaces)

- **S1. Verifier and audit.** REQ-2, REQ-3 (the script only), REQ-4, REQ-5, REQ-6, REQ-8, REQ-9 and
  REQ-10, as a pure predicate plus a bounded fetcher, with tests. It wires nothing. It needs a
  security-reviewer.
- **S2. Wiring.** The REQ-3 consumers (evaluator, `pr_readiness` REQ-W-07, overseer), REQ-7 and
  REQ-11, after ESC-1, ESC-4 and ESC-5.
- **S3. Human-facing text.** REQ-12 and REQ-13. This is sequenced with #1928 REQ-A1, because both
  edit `escalate_to_human.sh` and worker escalation text.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-1. Which act authorizes?**
  - (A) A prescribed-form comment only (REQ-1(a)).
  - (B) CONDITIONAL_PROCEED plus PR approval only (REQ-1(b)).
  - (C) Both: (A) for condition 7 (CRITICAL, gated before the PR) and for any step, and (B) allowed
    for condition 10 on non-CRITICAL steps.

  *Default: A.* It works before a PR exists, which is the state #1776, #1968 and #1988 are in. It
  matches the SPEC-328 R2.5 and NG3b precedents. It keeps the CRITICAL gate ahead of the outer loop.
  It does not depend on #1913 delivering the verdict to the overseer. (B) moves the gate after the
  PR opens, and `pr_review.sh request-reviewer` would not even request the human on a
  non-protected MEDIUM step. **This choice decides where a human gate sits and needs your ruling.**
- **ESC-2. Under (B) or (C), does a whole-PR approval satisfy SPEC-267 coverage?** *Default: no.*
  The approval must be accompanied by a `reviewed_files:` list in the review body. An approval alone
  proves a click, not which files were read.
- **ESC-3. Does a merge-from-base keep the authorization?** *Default: yes,* if and only if the
  step's own diff (`git diff <merge-base>..HEAD`, compared by patch-id) is unchanged. Any other new
  commit invalidates it. A stricter alternative is to bind to the exact head SHA and require a fresh
  act after every merge.
- **ESC-4. Should the act also resolve `escalated:` blocking findings (REQ-7)?** *Default: yes*,
  each named by id. Without this, #1776 cannot meet acceptance item 2 (VF-2).
- **ESC-5. What happens to the file artifact?**
  - (i) Retire it.
  - (ii) Keep it as a derived record written by the verifier, gitignored and non-authoritative.
  - (iii) Keep the hand-written file as an interactive-only fallback for consumer projects without
    GitHub issues.

  *Default: ii.* A derived record keeps the existing readers (the evaluator report and
  `pr_readiness` messages) informative, and authority stays with GitHub. (iii) is not recommended:
  it preserves the unverifiable path that VF-3 describes.

## Escalation flag (CORE self-flag)

RISK: HIGH. The change replaces the artifact behind the hardest human gate in the pipeline, on
protected surfaces (`contract/**`, `.claude/agents/**`, `scripts/framework/**`). If the verifier is
wrong, the result is a bot-satisfiable gate.
CONFIDENCE: HIGH on VF-1 and VF-3 to VF-6, which come from file reads and greps in this session.
MEDIUM on VF-2's details, which come from the worker's cycle notes and were not re-read from
GitHub. MEDIUM on the ESC defaults, which are product judgment.

## Human Review Required

This change is structural. S1 depends on no ESC beyond confirming REQ-2's actor rule, and may go to
`architect` on these defaults. S2 waits on ESC-1, ESC-4 and ESC-5. S3 waits on S2 and on #1928
sequencing. REQ-2 (no bot, including the human-proxy, ever authorizes) and REQ-9 (fail closed) are
non-negotiable in every slice. No agent may waive them.
