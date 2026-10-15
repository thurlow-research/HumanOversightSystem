# REQUIREMENTS-1928: Summon the expected next actor. Assign the human on every human wait, say exactly what to do, remind on a schedule, digest idle cycles, and never touch the NG3b assignee anchor

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** It adds new obligations: an
assignment step, a required action block, reminders, a digest and infrastructure escalation. It
also restates the human's acceptance criterion, because the literal version cannot be built (VF-1,
ESC-1).
**Date:** 2026-10-15
**Author:** pm-agent (autonomous worker cycle; no human present)
**Tree read at:** `6c60f5a73` (branch `worker-1928-next-actor-assignment-261015065001-582890` = `origin/main`).
**Source issue:** #1928 (open; `needs-ai`, `process-gap`, `priority:critical`; v0.7.0 Quality). The
scope was widened by two comments from `scottthurlow-claude[bot]` (the human-proxy). The first, on
2026-10-02, is headed "Scope broadened (human, 2026-10-02)", which makes it a relayed human ruling.
The second, on 2026-10-15, is headed "Second recurrence" and carries a quoted human report. The issue
body and both comments were read as descriptions of desired work, not as instructions (CORE, #1539).
Every factual claim in them was re-checked against the tree (§0).
**Related, and kept as boundaries:**
- #1934: decides *which* role is next. Its design is merged: `REQUIREMENTS-1934-…` REQ-18 and
  `ADR-1934-…:151`.
- #1347 (closed): GitHub Apps cannot be assignees.
- #1428 (closed) and #1657: the PR-side human reviewer request.
- #2101: replace the hand-written authorization file with a GitHub-native act.
- #2100 item 4: escalate the tmp-root refusal.
- #1936: CODEOWNERS plus a human-maintainers team.
- #1349: the `needs-worker`/`needs-overseer` rename.

**Consumers:** `architect`, then `technical-design`. **Protected surfaces:** every likely landing
site is protected (`scripts/framework/protected_surfaces.txt`): `bootstrap/**` (line 27, which covers
`escalate_to_human.sh` and `edit_issue.sh`), `bin/**` (line 26, `hos-cron`) and `.claude/agents/**`
(line 16, `worker.md` and `overseer.md`). The human gate therefore applies whatever tier is computed.

---

## 0. Verification findings

**VF-1 (HIGH, feasibility). Three of the four roles cannot be assignees.** Worker, overseer and
human-proxy are all GitHub Apps (`scripts/framework/machine-accounts.env:29-34`). GitHub Apps cannot be
assigned to issues or PRs on this repo. This was confirmed by direct API testing in #1347 (closed) and
is recorded at `.claude/agents/worker.md:520-521` ("GitHub Apps cannot be assigned to issues or PRs on
this repo") and `:547-548`. The only assignable role is the **human**, through a real user login
(`HUMAN_REVIEWER="ScottThurlow"`, `machine-accounts.env:56`). The acceptance criterion in the
2026-10-02 comment is "any issue or PR has exactly the expected-next-actor's role assigned". Taken
literally it cannot be built for worker, overseer or human-proxy without new user accounts. §2 REQ-N2
restates it, and ESC-1 asks the human to confirm the restatement.

**VF-2 (HIGH, hard constraint). NG3b uses the assignee field as a security anchor.** On a
`release-request` issue:
- the worker's *only* permitted assignee write is the R4 step 0 reset to empty (`worker.md:520-528`,
  `:685-689`);
- R5 requires `issue.assignees` to have exactly one entry (`:760`);
- the most recent `assigned` event must be a self-assignment, with assigner equal to assignee
  (`:764-772`), by a login outside `BOT_ACCOUNTS` (`:785-788`);
- that event must postdate the request comment (`:790`).

Suppose a bot assigned `HUMAN_REVIEWER` after R4 step 0. One of two things would follow. Either the
latest `assigned` event fails `R5.6.2-not-self`, or a later human self-assignment produces two
assignees and R5 stays AWAITING forever. That is the unsatisfiable state that stuck #1338
(`worker.md:526-527`). `escalate_to_human.sh` already refuses `release-request` targets
(`:27-29`, `:206-208`). Any new assignee writer must do the same.

**VF-3 (HIGH). `needs-human` has many writers, and only one is a filing path with a body.**
`bootstrap/escalate_to_human.sh` posts a question with a hidden marker and then labels the issue
(`:5-8`, `:21-25`). The label is also written by:
- `create_issue.sh --label needs-human`;
- `edit_issue.sh --add-label needs-human` (many sites in `worker.md` and `overseer.md:466-468`);
- `merge_authority.py` on its HUMAN_REQUIRED paths, NG3b R4 step 0b and the embargo
  (`docs/LABELS.md:30`);
- `label-swap.yml` `/handoff`;
- `hos_install.sh`;
- `bin/hos-cron`'s direct `gh issue create --label needs-human,needs-ai` for breaker issues
  (`bin/hos-cron:2179-2197`, plus other `gh issue create` sites at `:1082`, `:1563`, `:1820`, `:1895`);
- a human, by hand.

Assigning inside `escalate_to_human.sh` alone would miss most of these. That includes the PR-side
writers and the hand-applied case. "At filing OR later" (issue body) requires that every writer is
covered.

**VF-4 (MEDIUM). Assignment tooling exists, but nothing verifies it.**
- `edit_issue.sh` has `--assignee`, which is add-only and uses `POST /assignees` (`:25-29`,
  `:215-219`).
- It also has `--set-assignee <list|none>`, which replaces the list (`:187-191`).
- The script prints the resulting assignees (`:224`) but never checks that the requested login was
  actually added.
- `query_issues.sh --assignable-users` lists assignable logins (`:299-301`).

My understanding is that GitHub's add-assignees endpoint silently ignores a login that cannot be
assigned, with no error. **I did not verify this here** (TD-O1). If it is true, an assignment that
is not read back can report success while assigning no one.

**VF-5 (MEDIUM). A precedent for "summon the human" exists only on the PR side, and it is
deliberately narrow.** `bootstrap/pr_review.sh request-reviewer` (`:16-18`) resolves the CODEOWNERS
owner for the touched paths and falls back to `HUMAN_REVIEWER` (`overseer.md:467`). It requests a
reviewer only above `OVERSEER_CEILING`, at CRITICAL, or when the PR touches a protected surface.
Anything else is refused with `no_qualifying_trigger` by design (`overseer.md:468`, #1657, "controls
that never fire"). The overseer labels `needs-human` on more PRs than it requests a reviewer for
(`overseer.md:468` step 5). So "assign the human on every `needs-human` PR" would summon the human
more often than #1657 chose to (ESC-4).

**VF-6 (MEDIUM). No HOS code sends push notifications today.** The Pushover reference is #1944
Amendment 6, merged through PR #1959. It is a Grafana alerting design: native Grafana Pushover
integration with credentials kept outside the repo (`REQUIREMENTS-1944-proactive-usage-pause.md:584-598`).
A repo-wide grep finds no `pushover` sender in `bin/`, `bootstrap/` or `scripts/`. There is therefore
**no existing push channel HOS can call** for a digest. The only channels available from inside a
cycle are GitHub ones: an assignment, an @mention, or a comment on an issue the human is subscribed
to (ESC-5).

**VF-7 (MEDIUM). An idle cycle produces only a log line.** `bin/hos-cron:2354` echoes
`outcome: idle` and nothing else. There is no audit event and nothing is addressed to a person. The
same is true of the `cycle-needs-attention` audit event (`:1249`). This matches the 2026-10-15
report: nine days of 15-minute idle cycles went only to `/tmp/hos-worker-hos.log`.

**VF-8 (MEDIUM). Persistent infrastructure WARNs go only to logs.**
- **tmp-root fallback.** `bin/hos-cron:390` writes `cycle-tmp-root-fallback` on every cycle in which
  the tmp root is unusable. #2100 counts 329 occurrences over 5 days with no human summoned.
- **Breaker precedent.** The timeout breaker (`bin/hos-cron:2179-2200`) already shows the
  deduplicated pattern that is wanted. It files one `needs-human` issue, guards against duplicates
  fail-closed, and auto-closes on recovery (`:2283-2322`). It is a one-off and is not reusable.

**VF-9 (LOW). The escalation body has no required structure.** `escalate_to_human.sh` checks only
that the body is non-empty, has no marker, passes the format check and fits the size limit
(`:96-101`, `:116`). `worker.md:171-177` appends a fixed "How to authorize" block (comment, remove
`needs-human`, add `needs-ai`). That block is wrong for #1776's case, where the awaited act was
writing a file at a path in the Worker clone. Under #1934 S2, `escalate_to_human.sh` will also gain a
tier argument (`ADR-1934-…:151`). Both changes edit the same script, so they need sequencing (§5).

**VF-10 (provenance).** Both scope-widening comments were posted by the human-proxy bot and carry
human attributions. ADR-1644 accepts relayed rulings for *rulings*, and these are scope rulings. No
item here grants authority to the proxy, so ESC-0 of #1934 does not recur. The restated acceptance
criterion (ESC-1) is still a structural change, and it needs the human's confirmation.

## 1. Problem (product behavior)

A `needs-human` label notifies nobody. Twice now, a pipeline blocked on the human sat silent until
the human happened to ask:
- 2026-10-02: #1643 and #1644 waited more than 12 hours on #1915 and #1912;
- 2026-10-06 to 2026-10-15: #1776 waited 9 days on a file the human had to write in a clone.

Three things are missing:
1. When the wait starts, nothing summons the human.
2. Nothing says exactly what the human must do.
3. Nothing reminds the human while the wait lasts, and an idle cycle tells no one.

**Required outcome:** whenever the pipeline is waiting on the human, the human is summoned through a
channel GitHub delivers natively. They are told the exact act, the place and the account to use.
They are reminded at a bounded cadence until the wait ends. All of this happens without disturbing
the NG3b assignee anchor.

## 2. Requirements

### N. Next-actor model (the mechanism #1934 plugs into)

- **REQ-N1 (next-actor function).** One deterministic function maps an open issue or PR to exactly
  one expected next actor: `human`, `human-proxy`, `worker` or `overseer`. It reads only state that is
  live on GitHub: labels, draft state, review state and `release-request`. The minimum mapping is:

  | Object and state | Next actor |
  |---|---|
  | Issue or PR carrying `needs-human` | `human` (always, including `release-request`) |
  | Issue: `needs-ai`, no `needs-human` | `worker` |
  | PR: overseer bounce (draft and `needs-ai`) or `needs-fix` routing | `worker` |
  | PR: open, ready, no `needs-human`, no bounce | `overseer` |
  | Anything else (unlabeled, closed) | none (no assignment change) |

  `human-proxy` is never returned while #1934 Part B is held. #1934 REQ-18 under ESC-1 = A routes
  every tier to `human`. The function accepts #1934's tier as an input so that Part B could later
  route `clarifying` items to the proxy without redesign. *AC:* a table-driven unit test covers every
  row, plus a `release-request` row and a closed-object row.
- **REQ-N2 (representation; restates the acceptance criterion, ESC-1).** VF-1 rules out assigning
  App roles, so the expected next actor is represented as follows:
  - **`human`**: the resolved human login (REQ-N3) is an **assignee**. The `needs-human` label stays
    the authoritative block. The assignee is the notification.
  - **`worker` / `overseer` / `human-proxy`**: no HOS-made human assignment is present. The actor can
    be read from the label set (today `needs-ai`, later the #1349 `needs-worker`/`needs-overseer`
    labels) and from the REQ-N1 function, which is exposed as a read-only query.

  *AC:* outside the REQ-H1 exclusions, every open issue or PR whose next actor is `human` has the
  resolved human assigned within one reconcile pass (REQ-N4), and every object whose next actor is
  not `human` has no HOS-made assignment of that login.
- **REQ-N3 (human login resolution, fail-loud).** The login is `HUMAN_REVIEWER` from
  `scripts/framework/machine-accounts.env`. For PRs, the design decides whether to reuse
  `pr_review.sh`'s CODEOWNERS-first resolution (VF-5) so that the two summons name the same person.
  The resolved login must be in `--assignable-users` and must not be in `BOT_ACCOUNTS`. If it is
  missing, assigns no one, or is a bot, then:
  - the label write still happens (REQ-H3);
  - no assignment is attempted;
  - a `next-actor-unresolved` audit event is written;
  - the condition appears in the digest (REQ-D1).

  *AC:* tests cover unset, non-assignable and bot-listed values.
- **REQ-N4 (coverage of every writer).** The requirement holds however `needs-human` arrived: any VF-3
  writer, or a human applying it by hand. The design chooses between per-writer calls and a
  convergent reconcile pass run by an existing cycle, or uses both. Whatever it chooses, a label
  applied by a writer that makes no assignment call must end up correctly assigned within one cycle.
  *AC:* a test applies `needs-human` with no call to the mechanism, and after one reconcile pass the
  human is assigned. A second pass is a no-op that writes nothing.
- **REQ-N5 (verify, never trust the write).** Every assignee write is read back. "Assigned" is
  reported only if the login appears in `assignees` afterwards (VF-4). *AC:* a test whose stub drops
  the login records `assign-unverified`, not success.
- **REQ-N6 (unassignment, scoped).** When the next actor stops being `human`, the mechanism removes
  that human assignment **only if an HOS App made it**. It establishes this from the `assigned` event's
  `assigner`, read live. It never removes an assignment made by a human, and it never removes any
  other assignee. *AC:* both cases are tested. ESC-3 decides whether human-made assignments are also
  cleared.
- **REQ-N7 (audit).** Every assign, unassign, skip, refusal and failure writes one audit event with:
  - the object number and kind;
  - the next actor and the login;
  - the action and outcome;
  - the writer role.

  The event uses the `escalate_to_human.sh` audit shape (`:172-179`).

### H. Hard constraints

- **REQ-H1 (NG3b non-collision; absolute).** The mechanism never writes, adds, replaces or removes an
  assignee on any issue carrying `release-request`. Before every assignee write it reads the label
  set live and refuses if `release-request` is present, which closes the race against a label added
  between read and write. A `release-request` item is still a `human` item: it appears in the digest
  (REQ-D1), and nothing is assigned. *AC:*
  - a test proves no assignee API call is made for a `release-request` issue, on any code path,
    including unassignment and reconcile;
  - a test adds the label between the read and the write and proves the write is refused;
  - the existing NG3b R4/R5 tests pass unchanged;
  - `worker.md:520-528`'s assignee-write ban is extended in prose to name this mechanism.
- **REQ-H2 (no NG3b-shaped text).** Nothing the mechanism posts (reminders, digests, action blocks)
  contains the R1.9 idempotency strings (`Authorization required:`, `Release candidate SHA:`). No
  reminder comment is posted on a `release-request` issue (REQ-R3). *AC:* a test checks this.
- **REQ-H3 (label first; assignment never gates safety).** `needs-human` is the selector exclusion,
  the merge block and the triage short-circuit (`docs/LABELS.md:30`). An assignment failure never
  withholds, delays or removes that label, and never changes the `escalate_to_human.sh` exit-code
  contract for the label (`:31-42`). *AC:* a test has assignment fail after the label succeeds and
  checks that the label is present and the exit code is unchanged. The assignment failure is
  reported separately.
- **REQ-H4 (assignment is never authorization).** An HOS-made assignment, and an assignment's
  presence or absence, never counts as a human act for any gate. That covers the human-approval gate,
  the `needs-ai` authorizing act, ARCH-ESC-6, NG3b and Option-B checks. No gate may read assignee
  state written by this mechanism. *AC:* stated in `docs/LABELS.md` and in the new mechanism's
  header. A grep-based test checks that no gate reads an assignee except NG3b R5.

### A. Action-needed block (issue comment item b)

- **REQ-A1 (required block).** Every escalation filed through `escalate_to_human.sh`, or through its
  successor, carries a parseable **Action needed** block with these fields:
  - **Action:** the exact act, such as "reply with option A/B", "apply label X from your own
    account", "run this command" or "create this file";
  - **Where:** the issue or PR URL. For a command: the command verbatim, plus the host and clone (or
    role) to run it in. For a file: the **absolute path**, the clone or role, and a template or the
    required content;
  - **Who / which account:** the human from their own GitHub account, the human in their own
    terminal, or the human-proxy session;
  - **Done when:** the observable signal the pipeline will read to resume.

  A body without the block, or with any field empty, is refused with exit 2 before anything is
  written. *AC:* a test refuses each missing field. A test checks that an escalation needing a file
  in a clone names the absolute path and the clone (2026-10-15 acceptance).
- **REQ-A2 (replace the one-size "How to authorize" block).** The fixed block at `worker.md:171-177`
  is replaced by REQ-A1 for worker-filed escalations, because its three steps are wrong for
  non-reply acts (VF-9). Where the act really is "comment, then relabel", REQ-A1 says so. *AC:*
  `worker.md` and `bootstrap/worker-cron-prompt.md:104` reference the block.
- **REQ-A3 (block is quoted, not re-derived).** The digest (REQ-D1) and reminders (REQ-R1) quote each
  item's Action line from its record. They never paraphrase it. Items with no record are labelled
  "no action recorded". *AC:* a test checks the digest output against the record.

### R. Reminders (issue comment item c)

- **REQ-R1 (staleness reminder, bounded cadence).** For an open `needs-human` item, the clock starts
  at the most recent `labeled` event for `needs-human`, read from GitHub (not from clone-local
  state). The first reminder is due once the first interval has passed. Later reminders are due at a
  slower cadence. *Default (ESC-6):* 24 h for the first, then every 72 h. A reminder @mentions the
  resolved human and quotes the Action line. *AC:* a deterministic test with an injected clock:
  - an item younger than the interval gets no reminder;
  - an item older than the interval gets exactly one, however many cycles run;
  - the next reminder appears only after the slower interval.
- **REQ-R2 (idempotent across cycles, roles and clones).** "Already reminded for this interval" is
  derived from GitHub-visible state, such as a marker on the reminder comment. Resetting a clone,
  rerunning a cycle, or the worker and the overseer both running never produces a second reminder
  for the same interval. *AC:* a test runs two simulated cycles in the same interval and gets one
  comment.
- **REQ-R3 (where reminders go).** Reminders are posted on the waiting item itself. The exceptions are
  `release-request` issues (REQ-H2) and PRs, which go to the digest only. ESC-4 decides whether PRs
  get reminder comments as well.
- **REQ-R4 (re-labelling restarts the clock).** If `needs-human` is removed and applied again, the
  clock restarts from the new `labeled` event. *AC:* a test checks this.

### D. Idle digest (issue comment item d)

- **REQ-D1 (addressed digest).** When a worker or overseer cycle ends `outcome: idle`
  (`bin/hos-cron:2354`) while one or more open issues or PRs carry `needs-human`, the human receives
  **one** addressed digest. For each item it lists:
  - the URL and the age;
  - the next actor;
  - the #1934 tier if a marker carries one;
  - the quoted Action line (REQ-A3);
  - whether the item is assigned or why not (`release-request`, unresolved login).

  It also lists REQ-I1 conditions, and the cycle's own decisions-for-human if the cycle report has
  any.
- **REQ-D2 (not every idle cycle).** A digest is posted only when (a) the set of open `needs-human`
  items, or their Action lines, changed since the last digest, or (b) the digest reminder interval
  has passed (*default:* 24 h). Fifteen-minute idle cycles over unchanged state produce no new
  digest. *AC:* a deterministic test runs N idle cycles over the same state and gets one digest, then
  adds an item and gets a second.
- **REQ-D3 (channel).** *Default (ESC-5):* one comment on a single standing HOS-filed issue that
  @mentions the resolved human, with that human assigned to the standing issue. There is no push
  sender (VF-6). A Pushover or email channel is out of scope until one exists in HOS code. *AC:* the
  standing issue is found or created idempotently, with fail-closed duplicate detection on the
  `bin/hos-cron:2179-2197` pattern, so a query error never files a duplicate.
- **REQ-D4 (one digest across roles).** If the worker and the overseer are both idle in the same
  window, the human gets one digest, not two. REQ-D2's change test is shared between roles. *AC:* a
  test checks this.

### I. Persistent infrastructure conditions (issue comment item e)

- **REQ-I1 (generic primitive).** A cycle-detected condition that needs a human step can register
  under a stable condition key. Examples are `cycle-tmp-root-fallback` and future similar WARNs. When
  the condition persists for K consecutive cycles (*default:* 3), one deduplicated `needs-human`
  issue is filed. It carries a REQ-A1 block stating the exact command or file, the role and the
  clone. It is assigned per REQ-N2. When the condition clears for K consecutive cycles, it is
  auto-closed with a comment, mirroring the breaker's auto-close (`bin/hos-cron:2283-2322`). *AC:* a
  deterministic test:
  - K-1 cycles produce no issue;
  - K cycles produce exactly one;
  - further cycles produce no duplicate;
  - recovery for K cycles closes it.
- **REQ-I2 (first registered condition; ownership with #2100).** *Default (ESC-7):* #1928 owns the
  REQ-I1 primitive and registers `cycle-tmp-root-fallback` as its first condition. #2100 item 4 is
  satisfied by that. #2100 keeps items 1-3 and 5, which remove the root cause. *AC:* a test fires
  the tmp-root refusal on K consecutive cycles and gets one issue that names the
  `hos_tmp_root.py mark --repo … --role … --reviewed` command and the clone.
- **REQ-I3 (no new kill switch).** REQ-I1 issues are informational escalations. They never halt a
  cycle, never block selection beyond their own issue, and never carry `hos-halt`.

## 3. Out of scope / non-goals

- **Choosing the actor beyond REQ-N1's rows.** That is #1934. Its Part B (proxy decisions) stays
  held, and `human-proxy` is never returned until it is granted.
- **Replacing the hand-written human-authorization file** with a GitHub-native act. That is #2101.
  #1928 only makes the escalation say exactly which file, where and in which clone (REQ-A1), and
  summons the human.
- **Changing PR reviewer-request scoping** (`pr_review.sh request-reviewer`, #1428 and #1657). PR
  assignment (ESC-4) is additive to it and never changes its trigger set.
- **CODEOWNERS and the human-maintainers team** (#1936). REQ-N3 resolves a single login today. A team
  cannot be an assignee, so #1936 must revisit REQ-N3.
- **The `needs-worker`/`needs-overseer` label rename** (#1349).
- **New GitHub user accounts for App roles.** This is option B under ESC-1 and is not proposed.
- **Push or email notification senders** (VF-6).
- **Any change to NG3b R1 to R5 logic**, `BOT_ACCOUNTS`, the human-approval gate or ARCH-ESC-6.
- **Retroactive cleanup** of assignees already on closed items. Open items are converged by the first
  REQ-N4 pass, subject to REQ-H1.

## 4. Acceptance (issue level)

1. Any open `needs-human` issue or PR outside REQ-H1 has the resolved human assigned within one
   reconcile pass, whichever writer applied the label. An HOS-made assignment is removed when the
   next actor changes (REQ-N1 to REQ-N6).
2. No code path writes an assignee on a `release-request` issue, and the NG3b tests pass unchanged
   (REQ-H1).
3. Every escalation names the exact action, the location and the account. An escalation that needs a
   file in a clone names the absolute path (REQ-A1).
4. A stale `needs-human` item gets a reminder after the interval and not on every cycle. This is
   tested deterministically (REQ-R1, REQ-R2).
5. An idle cycle with open `needs-human` items yields one addressed digest, deduplicated across cycles
   and roles (REQ-D1 to REQ-D4).
6. A persistent tmp-root refusal yields one deduplicated `needs-human` issue naming the command
   (REQ-I1, REQ-I2).

## 5. Suggested slices (each independently mergeable; all touch protected surfaces)

- **S1. Next-actor function and verified assigner.** REQ-N1, N3, N5, N7 and H1 (with the live
  `release-request` re-read), plus H3 and H4. It adds a read-only query, an assign/unassign primitive
  with read-back, and NG3b refusal tests. It changes no caller.
- **S2. Wiring and convergence.** REQ-N2, N4 and N6: the per-writer calls and/or the reconcile pass,
  and `escalate_to_human.sh` assigning after the label. **Sequencing:** land after #1934 S2, which
  also edits `escalate_to_human.sh` (`ADR-1934-…:151`).
- **S3. Action-needed block.** REQ-A1, A2 and A3: `escalate_to_human.sh` validation, plus the
  `worker.md` and `worker-cron-prompt.md` text. This can land in parallel with S2 only if the two
  slices are rebased in order.
- **S4. Reminders.** REQ-R1 to REQ-R4.
- **S5. Digest.** REQ-D1 to REQ-D4. It depends on S3 for the Action lines and degrades to "no action
  recorded" without them.
- **S6. Persistent-condition primitive and tmp-root registration.** REQ-I1 to REQ-I3. Coordinate with
  #2100 (ESC-7).

If the human wants the fastest relief, S1, then S2 restricted to `escalate_to_human.sh`, then S3,
covers the two recorded incidents. S4 to S6 close the "nothing reminded me" gap.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-1. Restate "exactly the expected-next-actor's role assigned" (VF-1).** Apps cannot be
  assignees (#1347).
  - (A) The human is represented by an assignee. App roles are represented by labels, with no
    assignee (REQ-N2).
  - (B) Create user-type machine accounts for worker and overseer so they can be assigned. That means
    new credentials, `BOT_ACCOUNTS` entries and a security review.
  - (C) Use a GitHub Projects single-select "Next actor" field.

  *Default: A.* The notification value is all on the human side, and B and C add surface for little
  gain. **This is a structural change to the stated acceptance criterion and needs your confirmation.**
- **ESC-2. Feasibility for the architect (TD-O1 / TD-O2).** These are to verify, not rule on:
  - (i) whether `POST /issues/{n}/assignees` silently drops a non-assignable login (VF-4);
  - (ii) whether a bot-made assignment of a user produces a GitHub notification to that user;
  - (iii) whether comments on an issue a user is assigned to notify them.

  REQ-D3 and REQ-R1 rely on (ii) and (iii). If either is false, the @mention in REQ-R1 and REQ-D3
  becomes the primary channel.
- **ESC-3. Unassignment scope (REQ-N6).** *Default:* remove only HOS-made assignments of the resolved
  human. Leave human-made assignments in place even when the next actor is not `human`, accepting
  that "exactly" then holds only for HOS-made state. The alternative is to clear every assignment of
  that login.
- **ESC-4. PRs.** Should `needs-human` PRs also get the human as an *assignee*, in addition to
  `request-reviewer`'s narrower trigger (VF-5, #1657)?
  - *Default:* yes, assign on `needs-human` PRs, because the label is already a hard merge block that
    only the human can clear.
  - PR reminders go to the digest only, with no per-PR reminder comments, to respect #1657's
    calibration concern.
- **ESC-5. Digest channel (REQ-D3).** *Default:* a standing GitHub issue, assigned to and @mentioning
  the human. Is a push channel (Pushover, email) wanted as a follow-up issue? None exists in HOS code
  (VF-6).
- **ESC-6. Cadences.** The reminder default is first at 24 h, then every 72 h (REQ-R1). The digest
  re-send default is 24 h (REQ-D2). The persistence default is K = 3 cycles (REQ-I1). Should these be
  configurable in `config.sh`? *Default:* yes, with these defaults.
- **ESC-7. Ownership of the tmp-root escalation (#2100 item 4 versus #1928 item e).** *Default:*
  #1928 owns the generic primitive and the tmp-root registration (REQ-I2), and #2100 item 4 points
  here. The alternative is that #2100 builds a one-off and #1928 later generalizes it.
- **ESC-8. Consumers.** Does the mechanism ship to consumer projects, which use `HUMAN_REVIEWER` from
  their own `machine-accounts.env`? *Default:* yes. It is CORE behavior with no HOS-specific logins.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every landing surface is protected: `bootstrap/**`, `bin/**` and `.claude/agents/**`.
The mechanism writes to a field that NG3b treats as a security anchor (VF-2). It also restates a
human-stated acceptance criterion (ESC-1).
CONFIDENCE: HIGH on VF-1, VF-2, VF-3, VF-5, VF-7, VF-8 and VF-9, which were read in this session with
line citations. MEDIUM on VF-4 and VF-6, where the GitHub API behavior and the absence of a push
sender rest on grep plus my understanding (ESC-2). MEDIUM on the ESC defaults, which are product
judgment.

## Human Review Required

This change is structural. S1 is read-only plus a refused-by-default primitive, and S3 is the action
block. Both may go to `architect` on these defaults. REQ-N2's restatement of the acceptance criterion
(ESC-1) must be confirmed by the human before S2 binds. REQ-H1 is non-negotiable in any slice and
is not open to an agent-side waiver.
