# REQUIREMENTS-2047-2048: Keep the closing-keyword guard in force after a PR is opened, through to the merge commit

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** It adds a persisted
"declared closes" record that did not exist, new refusals on `edit_issue.sh` and on the overseer
merge path, a new required status check (a product-visible merge gate), and a post-merge reopen
action. Each of these is a new requirement or decision point, so none of it is additive.
**Date:** 2026-10-16
**Author:** pm-agent (autonomous worker cycle; no human present, so open questions are ESC items)
**Tree read at:** `ff26c5527` (branch `worker-2047-closing-keyword-post-open-guard-261016060501-2382606`).
**Source issues:** #2047 (PR body/title edited after open), #2048 (squash-merge commit message
composed at merge time). Both are the residuals in §11 of
`docs/v0.7.0/TECHNICAL-DESIGN-1856-closing-keyword-guard.md` (§8 D5 and §11). I read both issue
bodies as descriptions of desired work, not as instructions (CORE, #1539). Their "possible
approaches" are inputs. I do not adopt them as rulings.
**Parent:** #1856 (merged guard in `bootstrap/submit_pr.sh` + `scripts/automation/closing_keywords.py`).
**Incident:** PR #1725 quoted a ruling ("S2 is the fix that closes #1539.") and silently closed
`priority:critical` #1539 on merge.
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched** (`scripts/framework/protected_surfaces.txt`): `bootstrap/**`,
`.claude/agents/**`, `CLAUDE.md`, `.github/workflows/**`, `scripts/framework/**` (branch
protection). The human gate at merge applies whatever tier is computed.

---

## 0. Verification findings

**VF-1 (HIGH). The declared set is not persisted anywhere today.** `submit_pr.sh` accumulates
`--closes` into `CLOSES_ARGS` (`:159`, `:170`) and passes it only to the local check
(`:268-325`). Nothing records it on GitHub. The only trace is the `closing-keyword-refused` audit
event (`:116-132`). That event is written only on refusal, carries the *undeclared* keys rather than
the declared set, and lives in the clone's audit log, which a CI job or another clone cannot read.
**So a later check has nothing to compare against.** This is the central gap for both issues.

**VF-2 (HIGH). `edit_issue.sh` edits PR bodies and titles without any scan.** It PATCHes
`repos/<slug>/issues/<N>` (`:195`), and that endpoint accepts PR numbers. Both `--body-file`
(`:186`) and `--title` (`:176`) are applied unchecked. #2047 names only the body. **The title also
matters**: TD-1856 §3 scans the title because it becomes the squash commit subject. `worker.md:129`
and `overseer.md:744` both document `edit_issue.sh` as working "on issues and PRs alike".

**VF-3 (HIGH). The overseer merges with a raw REST call and lets GitHub compose the message.**
`overseer.md:466` (AUTO_MERGE) and `:772` say `PUT /repos/{o}/{r}/pulls/{n}/merge` with
`{"merge_method":"squash"}` and nothing else. No `commit_title`, `commit_message` or `sha` is sent.
So the repository's squash-message default decides what lands on `main`. That default can be PR
title+body, the list of branch commit messages, or blank. **I did not verify which setting this
repo uses** (TD-O1). `bootstrap/merge_authority.sh` is read-only and "can merge nothing" (`:42`).

**VF-4 (HIGH). The planned merge wrapper does not exist yet.** ADR-1357 AD-5/AD-7 define
`bootstrap/overseer_merge.sh` as recompute, then approve, then `PUT .../merge (squash)`, as one unit
(`ADR-1357:176-206`). Slice 4 is "Blocked on ESC-1" (`:329`). TD-1538 requires the slice-4 wrappers
to land after #1538 S1 and call `append_event(required=True)` (`TD-1538:246`, `:1400`).

**VF-5 (MEDIUM). A trusted server-side check pattern already exists.** The `require-*` workflows
run under `pull_request_target`. The workflow and its gate script come from the base branch, and PR
content is read as data (`require-tier-ceiling.yml` header). `closing_keywords.py` is stdlib-only
(`:9`), so it can run in that job. **But** these workflows use the default trigger types
(`require-human-approval.yml:36-38`). Those are `opened`, `synchronize` and `reopened`. They do
**not** include `edited`, so a body or title edit does not re-run them. Branch protection lists
required contexts in `setup_branch_protection.sh:164` plus `hos_required_contexts.txt` for
HOS-only contexts (#1981).

**VF-6 (MEDIUM). GitHub has three closing sources, not one.**
- (a) Closing keywords in the PR body, and manual "Development" links. Both appear in GraphQL
  `closingIssuesReferences` and close on merge.
- (b) Closing keywords in any commit message that reaches the default branch. For a squash merge,
  that means the composed squash message.
- (c) The branch's own commits never reach `main` under squash. They reach it only through (b) when
  the repo default copies them into the message.

Whether `closingIssuesReferences` also reflects title or commit-message keywords was **not
verified** (TD-O2). A manual Development link is invisible to any text scan.

**VF-7 (LOW). The refusal report is hard-coded to one caller.** `closing_keywords.py:133` prints
"✘ submit_pr.sh: …" and tells the reader to "pass --closes". From `edit_issue.sh`, a CI job or a
merge step, that text would be wrong.

**VF-8 (LOW). This is HOS-repo scope only.** `submit_pr.sh` and `scripts/automation/` are not in
the consumer ship-set (TD-1856 §11a). `edit_issue.sh` *is* in `bootstrap/` and may ship. TD must
confirm this (TD-O3).

**VF-9 (LOW). Trusted-marker precedent.** `bootstrap/escalate_to_human.sh:22-25,99` uses an HTML
marker in a comment. The marker counts only when the comment is bot-authored and unedited
(`updated_at == created_at`). A body that already carries the marker is refused, so a quotation
cannot forge a record.

## 1. Problem (product behavior)

The #1856 guard checks the text only when the PR passes through `submit_pr.sh`. After that, the
text that actually closes issues can change in four ways:

1. **P1:** an agent edits the PR body or title with `edit_issue.sh`.
2. **P2:** a human edits the body or title in the GitHub UI, or adds a manual Development link.
3. **P3:** the overseer merges, and GitHub composes the squash message from the repo default.
4. **P4:** a human merges in the UI and types or keeps a squash message.

In addition, **P5**: a PR opened outside `submit_pr.sh` (by a human, or by any other tool) was never
checked at all.

None of the five is re-checked, and the declared intent the guard was enforcing is thrown away
(VF-1). Only P1 and P3 run HOS code that can refuse *before* the change. P2 and P5 can be caught
only server-side, before merge. **P4 cannot be prevented by anything HOS runs**, because the human
types the message inside GitHub's merge dialog. It can only be detected after merge and repaired.

## 2. Requirements

### A. The declared-closes record

- **REQ-1 (one authoritative, server-side record per PR).**
  - Every PR has at most one *effective* declared-closes record. It lives on GitHub, so that
    `edit_issue.sh`, a CI job, the overseer and a post-merge job can all read the same thing.
  - `submit_pr.sh` writes the record in open mode **every time, including an explicitly empty set**
    when no `--closes` was passed. In `--update-pr` mode it writes a new record only when
    `--closes` is passed.
  - The record format and location are ESC-1. *Default:* a PR comment posted by the opening HOS bot
    identity that carries `<!-- hos-closes v=1 refs=<sorted comma-joined normalized keys> -->`.
    Keys are normalized per TD-1856 §3. The latest *trusted* record governs.
  - The record must not itself be a closing source. Comments never close issues, and the marker
    holds no closing keyword.
  - *AC:* after a `submit_pr.sh` open with `--closes 12`, a reader gets `{12}`. With no `--closes`,
    the reader gets `{}` (empty), not "absent". After `--update-pr --closes 12,13` the reader gets
    `{12,13}`.

- **REQ-2 (trust rule).** A record counts only if:
  - its author is a HOS bot identity (`machine-accounts.env`), or the configured human CODEOWNER
    (ESC-2; one CODEOWNER only until #1936); and
  - it is unedited (`updated_at == created_at`).

  Every other copy of the marker is ignored. That includes quoted copies, edited copies and copies
  in the PR body.

  `post_comment.sh` and `escalate_to_human.sh` refuse any body that contains the marker string. This
  mirrors VF-9, so an agent quoting another PR's record cannot declare by accident.

  *AC:* a marker inside an edited comment, a non-trusted author's comment, or the PR body → ignored.
  `post_comment.sh` with a body containing `<!-- hos-closes` → refused, nothing posted.

- **REQ-3 (absent is not empty).** A PR with no trusted record has an **undeclared** set. Every check
  below then treats every closing reference it finds as undeclared, and fails closed. An absent
  record is never read as "declares nothing, so nothing to check".
  *AC:* a PR with no record and a body containing "fixes #5" → every check in B–D refuses or fails.
  The same PR with no closing references → passes.

- **REQ-4 (PRs not opened through `submit_pr.sh`).** Human-authored PRs and PRs from other tools are
  in scope (P5). They declare through the same record (REQ-1/REQ-2). How a human declares is ESC-2.
  *Default:* the CODEOWNER posts the marker comment. A documented one-line recipe is given in the
  refusal text. No HOS script is required. Until a record exists, the required check (REQ-7)
  reports the undeclared refs.
  *AC:* a human PR containing "closes #9", with no record → REQ-7 fails and names #9. After the
  CODEOWNER posts the `refs=9` marker → REQ-7 passes on re-run.

### B. Edit-time guard on the sanctioned path (#2047, P1)

- **REQ-5 (`edit_issue.sh` scans PR body/title edits before writing).** When `--body-file` or
  `--title` is given:
  - `edit_issue.sh` determines server-side whether `<N>` is a PR (the issue object's
    `pull_request` field). A read failure refuses; it never falls back to "it's an issue".
  - For a PR, it scans the **resulting** title and body with `closing_keywords.py check`. The
    resulting title is the new title or, if none was given, the current title. The resulting body
    is built the same way. The scan compares against the effective declared set (REQ-1..3), and
    happens before the PATCH.
  - An undeclared ref → refuse, PATCH nothing, write an audit event (REQ-12, `phase: edit`).
  - The body is snapshotted once, and the scanned bytes are the PATCHed bytes. This is the same
    TOCTOU rule as `submit_pr.sh:203-213`.
  - Issue (non-PR) edits and label/milestone/assignee/state-only edits keep their current behavior.

  *AC:* `edit_issue.sh --number <PR> --body-file` with the #1725 fixture and no declaration → exit
  non-zero, body unchanged, stderr names `#1539` and the body line. `--title "fix: closes #42"` on a
  PR → refused. The same body on an *issue* number → applied.

- **REQ-6 (`edit_issue.sh --closes`).**
  - `--closes <n>[,<n>...]` is accepted only together with `--body-file`/`--title` on a PR. It is
    rejected on an issue.
  - Passing it writes a new declaration record (REQ-1) **after** the PATCH succeeds and the scan
    has passed with the new set.
  - It never bypasses the scan. Only `--closes` changes the outcome, and `--confirmed` has no
    effect, as in TD-1856 §5.7.

  *AC:* the fixture with `--closes 1539` → body applied, and the record becomes `{…,1539}`. With
  `--closes` on an issue number → usage error, no network writes.

### C. Server-side pre-merge check (#2047 complete coverage: P1, P2, P5)

- **REQ-7 (required status check `closing-keyword-guard`).** A `pull_request_target` workflow
  (trusted base copy, PR read as data, per VF-5) computes the **actual closing set** of the PR. That
  set is the union of:
  - (a) a `closing_keywords.py` scan of the current title, current body and the PR's commit
    messages; and
  - (b) GitHub `closingIssuesReferences`, which covers manual Development links (VF-6).

  The check fails if any member is outside the effective declared set.
  - It runs on `opened`, `edited`, `synchronize` and `reopened`. VF-5: `edited` is not in today's
    defaults.
  - It also re-runs when a declaration record is posted (by an `issue_comment` trigger or the
    existing rerun mechanism; TD's choice).
  - Any API or parse error → failure, never success.
  - It is added to branch protection as a HOS-only required context (`hos_required_contexts.txt`;
    ESC-6).

  Because branch protection gates **every** merge, this one check covers UI edits (P2), human PRs
  (P5) and `edit_issue.sh` edits that bypassed REQ-5. REQ-5 stays as the early, local failure for
  agents.
  *AC:* a UI body edit adding "resolves #77" → the check re-runs and fails, naming #77. A manual
  Development link to #78 → fails, naming #78. An API failure fetching `closingIssuesReferences` →
  fails.

### D. Merge-time guard (#2048, P3)

- **REQ-8 (the overseer composes, scans and pins the merge commit).** The overseer merge path never
  relies on the repo-default squash message. Immediately before merging it:
  - (a) composes `commit_title` and `commit_message` explicitly (content: ESC-3);
  - (b) scans exactly that text with `closing_keywords.py check` against the effective declared set;
  - (c) re-reads `closingIssuesReferences` and checks it against the same set; and
  - (d) sends the merge with the scanned `commit_title`/`commit_message` and the head `sha` it
    evaluated, so a later push makes the merge fail rather than merge unscanned content.

  If (b) or (c) finds an undeclared ref, or any read fails → no merge, a refusal audit event
  (`phase: merge`), and the existing merge-failure handling (`overseer.md:466`: comment +
  `needs-human`) with the refs named.
  *AC:* a PR whose title gains "closes #5" after its last check run → the overseer refuses to merge
  and labels `needs-human`. A clean PR → the merge request carries explicit
  `commit_title`/`commit_message`/`sha`, asserted by test.

- **REQ-9 (one implementation, two call sites over time).**
  - REQ-8's check is a read-only primitive that can be called today. A stable argv makes it
    allowlistable.
  - The current AUTO_MERGE step in `overseer.md` calls it, and uses its composed message, until
    #1357 slice 4 lands.
  - `overseer_merge.sh` (#1357 slice 4) then calls the same function **in-process** as part of its
    AD-5 recompute. That wrapper must not have a second copy of the logic. Sequencing is ESC-4.

  *AC:* a test asserts that the overseer AUTO_MERGE instruction names the primitive. When slice 4
  lands, a test asserts that `overseer_merge.sh` imports it.

### E. Post-merge backstop (#2048 P4, and anything missed)

- **REQ-10 (detect and repair after merge).**
  - A workflow on PR `closed` with `merged == true` lists the issues GitHub actually closed through
    that merge. That means issue `closed` events whose closer is the merge commit or the PR.
  - It compares them with the PR's effective declared set.
  - For each undeclared issue it (per ESC-5) reopens the issue, posts a comment naming the PR, the
    merge commit and the matching text, and applies `needs-human`.
  - It writes an audit event (`phase: post-merge`). Any read failure makes the workflow run fail
    visibly.

  This is the **only** control for P4. It detects and repairs; it does not prevent.
  *AC:* a test merge whose UI-typed message contains "fixes #88", undeclared → #88 is reopened with a
  comment and `needs-human`. With #88 declared → no action.

### F. Shared

- **REQ-11 (one grammar, caller-neutral report).**
  - Every check in A–E uses `scripts/automation/closing_keywords.py`. There is no second regex.
  - The refusal report names the actual caller and the remedy that fits it:
    - rephrase;
    - `--closes` (scripts);
    - the marker recipe (humans); or
    - escalate when the text is already pushed or merged.
  - Today's hard-coded `submit_pr.sh` prefix (VF-7) goes. `submit_pr.sh`'s output stays as it is
    now.

  *AC:* the existing TD-1856 §10 tests still pass. Each new caller's report names that caller.

- **REQ-12 (audit and fail-closed).**
  - Each refusal writes `closing-keyword-refused` with a `phase` of `edit`, `ci`, `merge` or
    `post-merge`, the PR number, the undeclared keys and the declared set.
  - The audit is best-effort until #1538 S1 lands, then `append_event(required=True)` per
    TD-1538. An audit failure never masks a refusal.
  - Missing `python3` or a missing module refuses, in every call site (TD-1856 §5.2).

- **REQ-13 (docs).** Each of these documents the guard:
  - the `submit_pr.sh` and `edit_issue.sh` headers;
  - the `edit_issue.sh` rows in `worker.md:129` and `overseer.md:744`;
  - `overseer.md` AUTO_MERGE (`:466`) and Merge (`:772`);
  - `CLAUDE.md` "What to do instead" item 5 (`edit_issue.sh` on a PR is now scanned); and
  - `docs/LABELS.md` if REQ-10 adds a label use.

  `TECHNICAL-DESIGN-1856` §8 D5 and §11 get a dated note pointing here.

- **REQ-14 (tests).** Each of REQ-1..12 has at least one test. These are mandatory:
  - the #1725 fixture through REQ-5, REQ-7 and REQ-8;
  - absent-vs-empty (REQ-3);
  - a forged or edited marker (REQ-2);
  - `edited` triggers the CI check (REQ-7);
  - a manual Development link (REQ-7);
  - the merge request carries `sha` and an explicit message (REQ-8); and
  - API failure → refuse, in every call site.

## 3. Coverage matrix (which requirement covers which path)

| Path | Prevent (before effect) | Backstop |
|---|---|---|
| P0 open via `submit_pr.sh` | #1856 (existing) + REQ-1 record | REQ-7, REQ-8, REQ-10 |
| P1 `edit_issue.sh` body/title on PR | REQ-5/REQ-6 (local) | REQ-7 (server) |
| P2 GitHub UI body/title edit, manual link | REQ-7 only (client-side cannot intercept) | REQ-8, REQ-10 |
| P3 overseer squash merge | REQ-8 (+ REQ-7 via branch protection) | REQ-10 |
| P4 human UI merge, typed message | **none possible** | REQ-10 only |
| P5 PR opened outside `submit_pr.sh` | REQ-7 + REQ-4 | REQ-8, REQ-10 |

## 4. Non-goals

- **NG-1:** changing the TD-1856 §3 grammar, or adding exemptions, allowlist files or suppression
  markers (TD-1856 §8 D4 stands; the REQ-1 record is a declaration, not a suppression).
- **NG-2:** scanning issue bodies or any comments, since neither closes issues (TD-1856 D5).
- **NG-3:** preventing P4 before it happens. GitHub offers no hook into the merge dialog.
- **NG-4:** shipping any of this to consumer projects (VF-8). That needs its own requirement.
- **NG-5:** any change to the #1357 decision matrix, AD-5 recompute semantics or AD-6 staleness bar.
  REQ-8 adds a merge precondition and a request shape only.
- **NG-6:** retroactively auditing past merges for silently closed issues. That could be a
  follow-up issue (ESC-7).

## 5. Suggested slices

1. **S1:** REQ-1/2/3 record, written by `submit_pr.sh`, plus a reader library, plus the REQ-2
   refusals in `post_comment.sh`/`escalate_to_human.sh`, plus REQ-11.
2. **S2:** REQ-5/6 in `edit_issue.sh`.
3. **S3:** REQ-7 workflow and branch protection (needs ESC-6).
4. **S4:** REQ-8/9 primitive plus the interim `overseer.md` wiring (needs ESC-3, ESC-4).
5. **S5:** REQ-10 (needs ESC-5).

REQ-12/13/14 go with each slice. S1 must merge first, because every other slice reads its record.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-1. Where the declared set lives (REQ-1).**
  - *Default:* an unedited, bot-authored PR comment marker; the latest trusted one governs.
  - Alternatives:
    - (b) a marker in the PR body. Rejected: any body edit can drop or forge it, and it would land
      in the squash message.
    - (c) a label per issue. Rejected: label noise, and anyone with triage rights can set one.
    - (d) the clone-local audit log. Rejected: CI and other clones cannot read it (VF-1).
- **ESC-2. Human and outside PRs (REQ-2/REQ-4).**
  - *Default:* the human CODEOWNER declares by posting the marker. Until they do, REQ-7 blocks the
    merge.
  - Alternative: exempt human-authored PRs (warning only). That would leave P5 open for exactly the
    actor who merges in the UI.
- **ESC-3. Composed squash message (REQ-8a).**
  - *Default:* title `<PR title> (#<N>)`, message = the PR body. This keeps today's history format,
    and the whole text is scanned.
  - Alternative: a minimal message (title only, plus one `Closes #n` line per declared key), so
    quoted body text never reaches `main`. That is safer, but history loses PR context.
- **ESC-4. Sequencing against #1357 slice 4 (REQ-9).**
  - *Default:* build the primitive now and wire it into `overseer.md` prose. Slice 4 adopts it
    in-process.
  - Alternative: wait for slice 4, which is blocked on its own ESC-1. That leaves P3 open
    indefinitely. #1538 S1 changes only the audit call (REQ-12), not this ordering.
- **ESC-5. Post-merge repair (REQ-10).**
  - *Default:* auto-reopen, comment, and `needs-human`. Reopening restores the state the human never
    approved changing, and the human can re-close.
  - Alternative: comment and `needs-human` only, leaving the issue closed.
- **ESC-6. New required status check (REQ-7).** It blocks every merge, including human merges, while
  any closing ref is undeclared.
  - *Default:* yes, as a HOS-only required context.
  - Alternative: run it as a non-required (advisory) check. P2 and P5 are then covered only by
    REQ-8 (overseer merges) and REQ-10.
- **ESC-7. Retroactive sweep (NG-6).**
  - *Default:* out of scope. File a follow-up only if the human wants past silent closures found.

## 7. Open technical questions for TD (not product questions)

- **TD-O1:** this repo's squash-merge default message setting (VF-3). This matters only for the
  interim, before REQ-8 lands.
- **TD-O2:** whether `closingIssuesReferences` includes title or commit-message keywords (VF-6).
  The answer decides whether REQ-7(a) or REQ-7(b) alone suffices. REQ-7 requires both regardless.
- **TD-O3:** whether `edit_issue.sh` ships to consumers. If it does, REQ-5 needs a consumer-safe
  path, since `closing_keywords.py` is not shipped.
- **TD-O4:** how REQ-7 re-runs on a new record comment without reintroducing the #972/#1299
  PR-head-execution and duplicate-check-run hazards.

## 8. Traceability

| Requirement | Source |
|---|---|
| REQ-1, REQ-2, REQ-3 | VF-1; #2047 and #2048 both need a declared-set comparison; VF-9 precedent |
| REQ-4 | P5; issue asks what happens to non-`submit_pr.sh` PRs |
| REQ-5, REQ-6 | #2047 approach 1; VF-2 (body **and** title) |
| REQ-7 | #2047 approach 2; VF-5, VF-6; only complete coverage for UI edits |
| REQ-8, REQ-9 | #2048 approaches 1 and 2; VF-3, VF-4; ADR-1357 AD-5/AD-7 |
| REQ-10 | #2048 human UI merge (P4); TD-1856 §1 incident (#1725 → #1539) |
| REQ-11 | VF-7; TD-1856 §3/§6 |
| REQ-12 | TD-1856 §7; TD-1538 §3 / :1400 |
| REQ-13, REQ-14 | TD-1856 §9/§10 conventions |

## Escalation flag (CORE self-flag)

RISK: MEDIUM. The work changes the shared edit path, the merge path and branch protection. A false
refusal could halt merges, and a fail-open defect would re-expose the #1725 class.
CONFIDENCE: HIGH on the gap analysis (VF-1..5 verified in the tree). MEDIUM on GitHub semantics
(VF-6, TD-O1/O2, unverified this session).
Change classification: **structural**.

## Human Review Required

ESC-1..7 need a human ruling or acceptance of the defaults before S1 starts. REQ-7 (ESC-6) and
REQ-10 (ESC-5) change what blocks merges and what happens to closed issues. All slices touch
protected surfaces.
