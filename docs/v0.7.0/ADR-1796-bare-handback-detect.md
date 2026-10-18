# ADR-1796: A tested classifier in `scripts/automation/lib/` decides whether a worker PR is in a "bare `needs-human` removal" state. A single overseer-only wrapper `finalize` then either applies the label step 6 would have applied, or withholds it and posts one templated report per episode. The overseer stops writing these labels any other way

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-8 bind `technical-design`. The direction is human-ruled (option (a), 2026-10-02: detect and report once, guess nothing). This ADR does not reopen it. Options (b) `/park` and (c) "bare == handback" stay out of scope. REQ-2 (fail closed to UNDETERMINED), REQ-4 (never re-apply over a human removal, never infer intent) and REQ-5 (exactly once, trusted markers only) are not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-18
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #1796 (`process-gap`) · **Milestone:** v0.7.0 · **Risk tier:** MEDIUM computed. S2 is human-gated by surface: `.claude/agents/**` (`protected_surfaces.txt:16`) and `bootstrap/**` (`:27`). S1 is unprotected (`scripts/automation/**` is not listed in `protected_surfaces.txt:16-47`).
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1796-bare-handback-detect.md` (VF-1 to VF-7, REQ-1 to REQ-10, ESC-1 to ESC-3), commit `3d730260f`. Re-read at the working tree on branch `worker-1796-bare-handback-detect-design-261018220501-2960542` (base `37eca3777`): `.claude/agents/overseer.md:311-330,348-360,412-443,466-469,711`, `scripts/automation/lib/merge_authority.py:308-327,495-748`, `scripts/automation/lib/github.py:35-157,215-238,405,418-438`, `scripts/automation/lib/probe.py:28-45,260-300`, `scripts/automation/merge_authority_cli.py:1-60`, `bootstrap/merge_authority.sh:1-50`, `bootstrap/pr_review.sh:1-20`, `bootstrap/edit_issue.sh:1-40,199-224`, `scripts/framework/select_work_candidates.py:105-113,255-286`, `scripts/framework/require_human_approval.py:140-159`, `scripts/framework/requester_trust.py:45,285-326`, `scripts/framework/machine-accounts.env:29-39`, `scripts/framework/protected_surfaces.txt`, `scripts/oversight/lib/audit_log.sh:39-48`, `scripts/oversight/lib/audit_log.py:126`, `.github/workflows/label-swap.yml:35`, `bin/hos-cron:1171-1172,1202-1232,1347-1359,2081-2082`, `docs/v0.7.0/ADR-1357-merge-authority-execution.md` (AD-4, AD-5, slice table).
**Consumers:** `technical-design` → `coder` → review chain. `reliability-reviewer` is mandatory on S1, because the classifier is a GitHub-dependent read whose failure direction decides whether a label is written. `security-reviewer` is mandatory on S1: the report renders a GitHub login and a reason string into a PR comment, and the marker is a trust decision. S2 edits `.claude/agents/overseer.md`. Per CLAUDE.md (#1347) the top-level session authors that file directly, not `coder`.
**Explicitly does NOT re-litigate:** the 2026-10-02 ruling, `decide_merge_authority()` and its gates, the #1215 precheck predicate, #1839 (`prior_overseer_decision` stays unwired), #1847 / #1644 T3.0b worker routing, and ADR-1357's decision surface.

---

## 0. Verification findings

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `bin/hos-cron:1171-1172` (worker-authored open PRs), `:1202` dirty, `:1208-1209` draft+`needs-ai`, `:1222-1223` `needs-ai` without `needs-human`, `:1228` CR, `:1232` zero approvals → `needs-attention`, whose text is at `:2081-2082`.
- **VF-2 CONFIRMED.** `overseer.md:468` step (5): "label `needs-human` … idempotent, run every cycle". `:711`: a precheck-suppressed cycle "skip[s] straight to (4)", which is "finalize — label `needs-human`". `:441-443`: "Every other step-6 action for this PR also still runs as normal". The literal reading is a silent re-label over the human's removal.
- **VF-3 CONFIRMED.** `merge_authority.py:495` (`_HUMAN_GATE_LABELS`), `:558-567` (#756 guard, `lbl.lower()` at `:561`). The label-absent HUMAN_REQUIRED paths are at `:586-595`, `:605-613`, `:642-647`, `:690-695` and `:713-731`. Withholding a label relaxes no merge gate.
- **VF-4 CONFIRMED.** `label-swap.yml:35`: `if: ${{ !github.event.issue.pull_request && … }}`.
- **VF-5 CONFIRMED.** `select_work_candidates.py:113` (`EVENTS_PAGE_BOUND = 10`), `:264-286` (`_fetch_pages`). `probe.py:265-300` (`_fetch_events_paginated`, one `_run_gh` per page, `None` or a non-list response → failure). `require_human_approval.py:140-159` (`is_bot_reviewer`). `requester_trust.py:301-322` (`load_bot_accounts`, baseline unioned with the environment).
- **VF-6 CONFIRMED.** `bootstrap/worker-cron-prompt.md:76` (`<!-- hos-worker-merge-block -->`).
- **VF-7 CONFIRMED.** `bin/hos-cron:1347-1359` skips only dirty or draft PRs.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): REQ-1 clause 6 cannot be computed by a detector today. `decide_merge_authority()` has no mechanical invocation.**
- `overseer.md:311-330` tells the agent to "Apply the merge-authority matrix (`merge_authority.py:decide_merge_authority`)" and to thread about ten parameters into it. No shell entry point computes it. `bootstrap/merge_authority.sh:16-23` exposes eight read-only primitives (`gate`, `register`, `bounce-count`, `human-approval`, `hold-directive`, `protected-surface`, `security-surface`, `codeowners`). None of them is `decide`.
- The composed decision surface is ADR-1357 AD-4 (`bootstrap/overseer_decide.sh`, slice 2). It is unbuilt: `scripts/automation/` contains no `overseer_decide.py`.
- A detector that recomputed the disposition would be a second, divergent copy of the matrix, which is the duplicate-authority class ADR-1357 forbids.
- **Consequence (AD-2, AM-1):** the classifier computes clauses 1-5, which are pure label history. The disposition and its reason are **inputs** to `finalize`. The withhold-vs-relabel decision is still mechanical once the disposition is known. That disposition comes from the overseer's own matrix step, which is the subject of #1357 and not of this issue. FC-1 names the replacement once ADR-1357 slice 2 lands.

**AF-2 (HIGH): `labels_to_add` has no code consumer, so REQ-4's "no automated writer" is a prose-routing property.**
- `grep -rn labels_to_add scripts bootstrap bin .claude/agents`, excluding `merge_authority.py` and tests, returns nothing.
- Every overseer label write on a PR is an agent following a `bash bootstrap/edit_issue.sh --add-label …` instruction. On worker PRs there are four: `overseer.md:466` (AUTO_MERGE merge failure → `needs-human`), `:468` (5), `:469` (PROPOSE_ONLY → `needs-ai`) and `:711` (4).
- REQ-4's suppression therefore has to sit where those instructions point. AD-3 replaces all four with one wrapper.

**AF-3 (HIGH): posting the report would itself defeat the #1215 precheck for one cycle, which would produce a duplicate escalation.**
- The precheck (`overseer.md:424-432`) skips only when `latest`, the newest overseer-or-other entry since the head was pushed, is the overseer's own entry **and** contains `**Decision: HUMAN_REQUIRED**`.
- The report is posted last in the cycle (finalize). On the next cycle, `latest` is the report. If the report lacks that header, the precheck does not apply, and the full §8.2 escalation thread is re-posted once.
- REQ-9 forbids changing the precheck predicate. **AD-5 therefore puts the canonical `**Decision: HUMAN_REQUIRED**` header in the report body.** That is truthful, because a report posts only on a HUMAN_REQUIRED disposition (AD-4).
- No code consumer parses that header. Its only readers are the overseer prose at `overseer.md:349,369,383,428`.

**AF-4 (MEDIUM): `github.list_issue_comments` cannot be the marker read. It fails open, and its loop is unbounded.**
- `_run_gh` returns `None` on a 404 (`github.py:137`), and `list_issue_comments` treats a falsy batch as the end of the list (`:232-233`). A failed read therefore looks like "no marker", which produces a duplicate post.
- The loop has no page bound (`:228`).
- REQ-5 requires "comment read fails → nothing posted". AD-6 uses a strict per-page fetch for both events and comments. It reuses `github._run_gh`'s transport (retry, backoff, rate limit, 30 s timeout, `:35-157`), but none of `list_issue_comments`' end-of-list semantics.

**AF-5 (MEDIUM): REQ-7's "new head pushed after the removal" needs a defined clock. The issue events API does not record ordinary pushes.**
- AD-7 uses the head commit's committer date, which is the `head_committed_at` the #1215 precheck already uses (`overseer.md:413-414,422-424`). An episode ends when that date is after `removed_at`.
- The residual R-2 failure direction is safe. A pushed commit that carries an older committer date leaves the episode open, so the label stays withheld and no second report is posted.

**AF-6 (LOW): REQ-4 lists `record_pr_bounce()`, but a bounce is not reachable under REQ-1 as written, and it is not an inference of intent.**
- REQ-1 clause 6 restricts `BARE_REMOVAL` to a HUMAN_REQUIRED decision. A bounce is the DIRTY disposition, which is the overseer's own merits finding. It posts its own comment and converts the PR to draft (`overseer.md:712`).
- Gating `record_pr_bounce()` would mean editing `merge_authority.py`'s bounce path, which is #1538 territory and outside REQ-4's "decide_merge_authority() is not changed" spirit.
- AM-3 removes `record_pr_bounce()` from REQ-4's list and records the residual (R-3).

**Reuse search (CLAUDE.md item 1).** I searched `scripts/` (recursively), `bootstrap/`, `bin/` and `scripts/automation/lib/*.py` for an issue-events reader, a bot classifier, a trusted-marker check, an add-label helper and an audit writer.
- **Found, reused:**
  - `github._run_gh` (`github.py:38-157`) as the per-page transport;
  - `github.post_comment(verify=True)` (`:418-438`) for the report;
  - `github.get_commit` (`:405`) for the head committer date;
  - `require_human_approval.is_bot_reviewer` (`:140-159`) and `requester_trust.load_bot_accounts` (`:301-322`) for the actor test. The precedent for `scripts/automation/lib` importing these protected helpers is `probe.py:39-44`, and `requester_trust.py:45` itself imports `is_bot_reviewer`;
  - `scripts.oversight.lib.audit_log.write_event` (`audit_log.py:126`), the Python body behind `audit_write_event` (`audit_log.sh:39-48`).
- **Found, pattern reused but code not:** `probe._fetch_events_paginated` (`probe.py:268-300`) and `select_work_candidates._fetch_pages` (`:264-286`). Both are private, and both bound at 10 pages. That contradicts the #1923 human guidance relayed in this task (no practical cap, only a runaway tripwire), so AD-6 has its own fetch with a 100-page tripwire. FU-1 names consolidation.
- **Found, rejected:**
  - `github.list_issue_comments`, because it fails open (AF-4).
  - `bootstrap/edit_issue.sh` as the write path *from inside the classifier*, because it is a separate process with its own mint, which would add a re-entry point between deciding and acting (ADR-1357 AD-5). Its endpoint shape (`POST /issues/{n}/labels`, `edit_issue.sh:199-203`) is copied into a new `github.add_issue_labels`.
  - Extending `bootstrap/merge_authority.sh`, which is documented read-only (`:39-40`).
- **Found nothing** that classifies a label-history episode or renders a handback report.

---

## 1. Organizing principle

**One process decides and acts. The overseer supplies only what it already decided (the disposition and its reason) and never chooses whether to write the label.** The classifier is pure over fetched evidence. Every fetch is complete or the answer is `UNDETERMINED`. `UNDETERMINED` and `BARE_REMOVAL` both mean "add nothing". The only difference is whether a report posts. No branch of this design removes a label, changes a merge decision or routes the worker.

---

## 2. Decisions

### AD-1: Locus. `scripts/automation/lib/bare_handback.py` holds the pure core and the strict fetch. `scripts/automation/bare_handback_cli.py` is L2. `bootstrap/bare_handback.sh` is L3. (BINDING; REQ-1, REQ-3.)

- This follows the existing three-layer shape exactly: `merge_authority.py` / `merge_authority_cli.py` / `merge_authority.sh`, and `pr_review_cli.py` / `pr_review.sh`. L1 is pure and testable. L2 fetches, calls, acts and emits one JSON record. L3 mints the token and passes stdout and the exit code through verbatim.
- **Why not `scripts/framework/`.** ADR-2102 placed its digest there because a fail-open defect would hide the human's queue. Here the failure surface is bounded by VF-3: the worst case in either direction is a routing label that is withheld or re-applied, never a relaxed merge gate. `merge_authority.py` and `pr_review_cli.py`, which carry more consequence than this, already live under `scripts/automation/`. Keeping S1 unprotected lets it land without a human gate. The point at which this code gains authority over overseer behaviour is S2's protected L3 wrapper and overseer prose, which are human-gated.
- **Imports (L1).** The standard library, `scripts.automation.lib.github` (transport only), `scripts.framework.require_human_approval.is_bot_reviewer` and `scripts.framework.requester_trust.load_bot_accounts`. Nothing from `merge_authority.py`: the classifier is independent of the matrix (AF-1). An import-graph test pins this.
- **Not shipped to consumers in this issue.** `scripts/automation/**` is not in `framework_consumer_files.txt`, and neither are its siblings. The overseer role is HOS-repo-scoped today. If the overseer is shipped later, this goes with it.

### AD-2: L1 interface. `classify(evidence) -> Classification`, pure over five inputs. (BINDING; REQ-1 clauses 1-5, REQ-2, REQ-3, REQ-7, AF-1.)

- **Inputs**, as a frozen dataclass assembled by L2:
  - `pr`: state, draft, author login, label names and head SHA;
  - `head_committed_at`: the committer date of the head commit;
  - `events`: the complete issue-events list, or a fetch outcome that is not COMPLETE;
  - `worker_login`: `BOT_WORKER_USERNAME`;
  - `bot_accounts`: from `load_bot_accounts`.
- **Output:** `determination ∈ {NOT_BARE, BARE_REMOVAL, UNDETERMINED}`, plus `cause` (a closed enum), plus, for `BARE_REMOVAL`, `removed_at`, `removed_by` and `head_sha`.
- **Evaluation order. The first clause that settles the answer wins.** Each step names its `cause`.
  1. The PR is not open, is a draft, or its author is not `worker_login` → `NOT_BARE (out-of-population)`.
  2. Its labels include `needs-human` or `needs-ai`, compared case-insensitively → `NOT_BARE (labelled)`. **No events are read** (REQ-2).
  3. The events fetch is not COMPLETE → `UNDETERMINED (events-failed | events-tripwire | events-non-list)`.
  4. No `labeled` or `unlabeled` event for `needs-human` exists → `NOT_BARE (never-labelled)`.
  5. The last such event is `labeled` → `UNDETERMINED (labels-events-disagree)`, because the label is absent per step 2.
  6. The last such event is `unlabeled` and its actor is a bot (`is_bot_reviewer(login, type, bot_accounts)`) → `NOT_BARE (bot-removal)`. A missing actor gives `UNDETERMINED (actor-missing)`.
  7. A `labeled` event for `needs-ai` or `needs-human` follows that `unlabeled` event → `NOT_BARE (relabelled)`. This is defensive. Step 2 already covers the current-label case, but a later add followed by a later removal of `needs-ai` must not resurrect the earlier episode.
  8. `head_committed_at` is unreadable → `UNDETERMINED (head-unreadable)`. If it is later than `removed_at` → `NOT_BARE (new-head)` (ESC-1(A), AD-7).
  9. Otherwise → `BARE_REMOVAL`.
- **Events order.** The classifier sorts by `(created_at, id)` itself and does not trust page order. Ties are broken by event `id`.
- **Purity.** No clock, no environment read, no I/O. `head_committed_at` is an input, not "now". Every call on the same evidence gives the same output. This is REQ-3, and the #1792 fixture tests it.

### AD-3: L2/L3 interface. Two subcommands. `finalize` is the only way the overseer adds `needs-human` or `needs-ai` to a worker PR. (BINDING; REQ-4, AF-2.)

```
bash bootstrap/bare_handback.sh check    --pr <N> --app <worker|overseer|human> [--repo <o/r>]
bash bootstrap/bare_handback.sh finalize --pr <N> --app overseer \
     --label <needs-human|needs-ai> \
     --disposition <HUMAN_REQUIRED|PROPOSE_ONLY|MERGE_FAILED> \
     --reason-file <path> [--repo <o/r>]
```
(The line break above is for display only. The prose form in `overseer.md` is one line.)

- **`check`** is read-only and runs the classifier. It is for humans, debugging and tests.
- **`finalize`** classifies, then:
  - **`NOT_BARE` →** apply `--label` through `github.add_issue_labels` (new: `POST /issues/{n}/labels`, `retries=0`, the response label set verified to contain the label). This preserves today's behaviour exactly.
  - **`BARE_REMOVAL` →** apply **no** label. If `--disposition HUMAN_REQUIRED`, run AD-4. Otherwise print one stdout line (`withheld <label> on PR #<n>: bare needs-human removal by <actor> at <ts>; disposition <D> posts its own comment`) and do nothing more.
  - **`UNDETERMINED` →** apply no label, post nothing, print one stdout line naming the PR and the `cause`, and run AD-6's deduplicated event.
- **`--app` other than `overseer` on `finalize` is refused, exit 3.** The minted identity must equal `BOT_OVERSEER_USERNAME`, the `pr_review.sh` precedent.
- **Exit contract.** 0 means answered and done, whatever the determination (labelled, withheld, reported, already reported, or undetermined). 1 is an operational failure: auth, a label POST that failed or did not verify, a report post that failed or did not verify, or an audit write that failed. 2 is usage. 3 is refusal. stdout is exactly one JSON record from L2. The record includes `determination`, `cause`, `label_applied`, `report` (`posted|already|none`), `comment_url` and `evidence`.
- **The overseer halts on exit 1**, under the existing SPEC-378 halt-on-failure rule (`overseer.md:714`). Exit 0 with `label_applied: false` is a normal, correct outcome. It is not an error to work around.
- **Why a writing wrapper and not "run `check`, then decide".** The issue exists because the withhold-vs-relabel decision was per-cycle judgement. A read-only `check` followed by an agent-run `edit_issue.sh` leaves that judgement in place, and VF-2 shows the prose already contradicted itself once. With `finalize`, the agent has no decision left to make (ADR-1357 Q1's rule), and the overseer prose names no other label-write path for these four sites.

### AD-4: The report. One per episode, templated, posted then confirmed then audited. (BINDING; REQ-5, REQ-6, REQ-9, AF-3.)

- **Gate.** `BARE_REMOVAL` and `--disposition HUMAN_REQUIRED`.
- **Reason (no paraphrase).** `--reason-file` must hold exactly one line, which is `MergeAuthorityResult.reason`. L1 matches it against a **closed table** of compiled patterns, one per `reason=` literal returned by `decide_merge_authority()` (`merge_authority.py:566,576-580,590-593,608-611,619,628,637,645,672,693,701,710,726-729`, plus the AUTO_MERGE `merge_reason` at `:735-742`, which never reaches `finalize`). Each row carries a category: `human-approval-satisfiable` or `other`.
  - A reason that matches no row → no report, no label, cause `reason-unrecognized`, and AD-6's deduplicated event. A paraphrasing overseer therefore disables the report loudly. It never produces a guessed report.
  - **Drift test (BINDING).** An AST walk of `decide_merge_authority` extracts every `reason=` expression and asserts that each one has a row whose pattern matches a rendered sample. A new gate added without a row fails CI.
  - **Category assignment is technical-design's**, subject to one rule: a row is `human-approval-satisfiable` only if either `decide_merge_authority()` or `overseer.md` step 6 treats a human `APPROVED` review on the current head as clearing that reason. Examples: #757 (`:713-731`), protected surface (`:679-695`), security-relevant (`:657-673`), the CRITICAL path (`overseer.md:467` (3)). The TD enumerates the table and cites each row.
- **Body (templated, no model text).**
  - First line: `**Decision: HUMAN_REQUIRED**` (AF-3).
  - Then the REQ-5 content: "unrouted", who removed `needs-human` and when, the head SHA, the reason quoted verbatim inside a code span, and "the pipeline did not guess your intent and did not re-apply the label".
  - The PR actions honoured by the code (VF-4): apply `needs-ai`; re-apply `needs-human`; approve the current head, shown only when the category is `human-approval-satisfiable`; close the PR. The body never contains `/approve`, `/decline` or `/handoff`.
  - The marker as the last line: `<!-- hos-bare-handback v=1 pr=<n> removed_at=<ISO-8601 Z> head=<sha40> -->`.
  - Sanitization: the actor login must match `^[A-Za-z0-9-]+(\[bot\])?$`, or the report is refused with `actor-malformed` (UNDETERMINED). The reason is already constrained by the table.
- **Idempotency.** Read every comment through AD-6's strict fetch. A **trusted** marker satisfies all of:
  - `user.login` equals `BOT_OVERSEER_USERNAME`, case-insensitively, and `user.type == "Bot"`;
  - `updated_at == created_at`;
  - a whole line matches the marker grammar;
  - `pr` equals this PR.

  If a trusted marker exists with the same `removed_at`, the outcome is `report: already`. `head` is informational and not part of the key, so a re-run on a new head inside one episode cannot re-post. Under AD-7, though, a new head ends the episode anyway. A comment-read failure gives no post, cause `comments-failed`, and the UNDETERMINED event.
- **Ordering (SPEC-378, `overseer.md:707-715`).**
  1. Post (`github.post_comment(verify=True)`).
  2. Confirm by re-reading the created comment by id: the marker line is present and the author is the overseer.
  3. Write the `bare-handback-reported` event (`write_event`). Its fields: `pr`, `head_sha`, `removed_at`, `removed_by`, `reason`, `reason_category`, `comment_url`, `repo`.
  4. Exit 0.

  A failure at step 1 or 2 gives exit 1 and no event. A failure at step 3 gives exit 1. The comment then exists without its event. The next cycle sees `already` and does not re-post. The missing event is a known audit gap, and the exit-1 halt surfaces it at the time. It is the same shape as today's SPEC-378 "audit append failed" halt.
- **REQ-9.** The #1215 precheck's predicate and scope are unchanged. `finalize` runs on precheck-suppressed cycles too, because it replaces halt step (4). So the report posts on the first suppressed cycle as well.

### AD-5: Overseer wiring (S2). Four call sites, one wrapper, and the "run every cycle" re-label is removed. (BINDING on content; the wording is the TD's. REQ-4, REQ-9.)

| Site | Today | After |
|---|---|---|
| `overseer.md:466` AUTO_MERGE merge failure | `edit_issue.sh --add-label needs-human` | `bare_handback.sh finalize … --label needs-human --disposition MERGE_FAILED --reason-file <merge-failure line>` |
| `overseer.md:468` HUMAN_REQUIRED (other) (5) | `edit_issue.sh --add-label needs-human`, "idempotent, run every cycle" | `finalize … --label needs-human --disposition HUMAN_REQUIRED --reason-file <decide reason>`, run every cycle. The *wrapper* is what is idempotent, and it may withhold |
| `overseer.md:469` PROPOSE_ONLY | `edit_issue.sh --add-label needs-ai` | `finalize … --label needs-ai --disposition PROPOSE_ONLY --reason-file <decide reason>` |
| `overseer.md:711` halt (4) | "finalize — label `needs-human`" | "finalize — run `bare_handback.sh finalize` as in step 6 (5); `label_applied: false` is correct, not a failure" |

- **New text (one short paragraph, placed next to the #1215 precheck).** It says: what a bare removal is; that the overseer never adds `needs-human` or `needs-ai` to a worker PR except through `finalize`; that `BARE_REMOVAL` and `UNDETERMINED` mean no label; and that the merge decision is unaffected. It also says to never call `edit_issue.sh --add-label needs-human|needs-ai` on a worker PR.
- **The CRITICAL path (`:467`) applies no label today** and is unchanged.
- **Issue-targeted label writes are out of scope and unchanged:** `:163` process-gap issue and `:213` release-readiness ESCALATE.
- **Prompt-contract test (S2, BINDING).**
  - Every `--add-label needs-human` or `--add-label needs-ai` occurrence in `overseer.md` is either inside an allowlisted issue-targeted paragraph (`:163`, `:213`, anchored by unique text and not first-occurrence matching; memory: "test anchors use first occurrence") or absent.
  - The four sites name `bare_handback.sh finalize`.
  - The string "idempotent, run every cycle" no longer attaches to an `edit_issue.sh` label instruction.
  - The new paragraph names the detector and both no-label determinations.
- **Enforcement strength, stated plainly (R-1).** The *decision* is mechanical and tested. The *routing* (the agent calls `finalize` and does not call `edit_issue.sh` directly) is prose, pinned by the contract test. Two stronger options were considered and rejected:
  - **A guard inside `bootstrap/edit_issue.sh`.** That is the generic metadata writer for every role, issues and PRs alike (`edit_issue.sh:1-40`). Every label add would gain an events read, every caller would gain a new failure mode, and a PR-specific overseer policy would sit in a shared primitive. The blast radius is out of proportion to a routing label that guards no merge (VF-3).
  - **A server-side workflow that reverts a bot re-add after a human removal.** That is a new `.github/workflows/**` surface, a new trust boundary and label-fighting between automations. It is a product-visible operational change, so it would need routing, and nothing yet shows it is needed.

  FU-2 names a cheap after-the-fact detector instead.

### AD-6: Fetch, bounds, failure and deduplication of undetermined outcomes. (BINDING; REQ-2, REQ-6.)

- **Strict per-page fetch** (`_fetch_all(endpoint, tripwire)` in L1's fetch module):
  - one `github._run_gh([f"{endpoint}?per_page=100&page={k}"])` per page;
  - `None` (`github.py:137`, a 404) → FAILED;
  - a non-list response → FAILED (`non-list`);
  - `GitHubError` or `RateLimitError` → FAILED;
  - a page shorter than 100 → COMPLETE;
  - reaching the tripwire → TRIPWIRE.

  Only COMPLETE is a determination input.
- **Tripwire: 100 pages (10,000 records)** for events and for comments, as a module constant and not a flag. That is the "no practical cap, only an absurd runaway tripwire" guidance relayed from #1923. The constant 10 used by `probe.py` and the selector is deliberately not copied. A PR with more than 1000 events is implausible but not absurd, and stopping there would make that PR permanently `UNDETERMINED`.
- **Request cost.**
  - A labelled PR costs one PR read (L2 needs labels and head anyway).
  - An unlabelled HUMAN_REQUIRED PR costs the PR read, one commit read, roughly 1 events page and roughly 1 comments page. Comments are read only on the BARE path.
  - The first escalation of a never-labelled PR costs PR + events + commit, about 3 GETs, once.
- **`UNDETERMINED` event deduplication.** At most one `bare-handback-undetermined` event per `(pr, head_sha, cause)`. Seen keys are kept in `.claudetmp/bare-handback/undetermined-seen.json`: persistent, uncommitted and never reaped (contract §1 rule 2). Writes are atomic (temp file plus `os.replace`), and the file is pruned to keys whose PR is still open on each write.
  - A lost or corrupt file causes at most one repeat event per key. It never suppresses a label decision.
  - The audit trail is not scanned for this. A linear scan is the `bounce_count` cost that ADR-1357 noted.
  - The same store also deduplicates `reason-unrecognized`, `comments-failed` and `actor-malformed`.
- **`check` writes nothing**, including no state file and no event.

### AD-7: Episode boundaries. (BINDING; REQ-7, ESC-1(A), AF-5.)

- **Start:** a non-bot `unlabeled needs-human` event, keyed by its `created_at` (`removed_at`).
- **End**, any of:
  - a later `labeled` event for `needs-human` or `needs-ai` (AD-2 steps 2 and 7);
  - the PR closed, merged or converted to draft (step 1);
  - `head_committed_at > removed_at` (step 8).
- **After the end,** `finalize` returns `NOT_BARE` and default behaviour resumes. If the matrix still says HUMAN_REQUIRED, the label is applied again. This is ESC-1(A).
- **A later human removal** starts a new episode with a new `removed_at` and one new report.

### AD-8: Requirements amendments are applied to the requirements file in this commit (§5). REQ-8 stays as written: worker routing and `bin/hos-cron` are untouched, and S2 carries only a test.

---

## 3. Failure modes

| Failure | Behaviour | Direction |
|---|---|---|
| PR read fails | UNDETERMINED, no label, line + deduplicated event, exit 0 | No write; retried next cycle |
| Events page fails, 404, non-list, rate-limited | UNDETERMINED (`events-*`) | No write |
| 100-page tripwire | UNDETERMINED (`events-tripwire`) | No write; loud |
| Label absent but last event `labeled` (lag) | UNDETERMINED (`labels-events-disagree`) | No write |
| Head commit unreadable | UNDETERMINED (`head-unreadable`) | No write |
| Comments read fails on the BARE path | No report, no label (`comments-failed`) | Never a duplicate post |
| Reason does not match the table | No report, no label (`reason-unrecognized`) | Never a guessed report |
| Report post or verify fails | Exit 1, no event; the overseer halts (SPEC-378) | Loud |
| Audit write fails after the post | Exit 1, halt; next cycle `already` | Loud; one event gap |
| Label POST fails on NOT_BARE | Exit 1, halt | Today's behaviour, now with a halt |
| Untrusted or edited copy of the marker | Ignored; the report posts once | Closed (REQ-5) |
| Overseer bypasses `finalize` and calls `edit_issue.sh` | Not prevented at run time (R-1); the contract test pins the prose; FU-2 detects it after the fact | Stated |

**Residuals.**
- **R-1.** Routing to `finalize` is prose (AD-5).
- **R-2.** A push whose committer date is earlier than `removed_at` does not end the episode. The direction is safe (AF-5).
- **R-3.** A DIRTY bounce (`record_pr_bounce`) on a bare PR still writes `needs-ai`. It is the overseer's own merits disposition with its own comment, not an inference of the human's intent (AF-6).
- **R-4.** The disposition and reason passed to `finalize` come from the overseer's narrated matrix until ADR-1357 slice 2 lands (AF-1). The reason table stops a paraphrase from reaching the report, but a wrong-but-valid reason is not caught.
- **R-5.** The human-proxy App (`scottthurlow-claude[bot]`) removing `needs-human` counts as a bot removal, so the overseer re-applies the label. That is correct: the proxy is forbidden to remove `needs-human` (ADR-2102 AD-9(d)), and a human's intent arrives through their own account.
- **R-6.** On PROPOSE_ONLY and MERGE_FAILED the label is withheld with no handback report. Each disposition already posts its own comment, so the outcome is not silent.

---

## 4. Slices (each ≤15 files including tests, ≤10 commits, independently mergeable)

| # | Slice | Files (indicative) | Protected? | Depends on |
|---|---|---|---|---|
| **S1** | L1 + L2, inert (no caller): AD-1, AD-2, AD-3 L2, AD-4, AD-6, AD-7, plus `github.add_issue_labels`. | `scripts/automation/lib/bare_handback.py` (new), `scripts/automation/bare_handback_cli.py` (new), `scripts/automation/lib/github.py` (`add_issue_labels`), `tests/automation/test_bare_handback_classify.py` (new: table-driven clauses, ordering, #1792 regression), `tests/automation/test_bare_handback_fetch.py` (new: tripwire, 404, non-list, page-2 failure, no events read when labelled), `tests/automation/test_bare_handback_report.py` (new: body, marker trust, reason table + AST drift test, `/approve` absent), `tests/automation/test_bare_handback_cli.py` (new: finalize outcomes, exit contract, app refusal, ordering, undetermined dedup, import graph), `tests/automation/test_github.py` (extend), `tests/automation/fixtures/bare_handback/` (1-2 JSON), `research/findings/api-field-shape-verification.md` (live probe of the `unlabeled` event shape: `actor.type`, `label.name`, `created_at`, `performed_via_github_app`), `SCRIPTS-INDEX.md`: 11 | No | — |
| **S2** | Wiring: AD-3 L3 + AD-5. Every overseer-facing protected text in one PR. | `bootstrap/bare_handback.sh` (new, `merge_authority.sh` shape: mint for `--app`, exec L2, revoke, pass-through), `.claude/agents/overseer.md` (four sites + paragraph), `tests/automation/test_bare_handback_wrapper.py` (new: pass-through, no JSON literal in bash, mint only for the given role), `tests/framework/test_overseer_bare_handback_contract.py` (new: AD-5 assertions), `tests/automation/test_hos_cron.py` (extend: REQ-8, a label-free clean non-draft PR is not routed to `needs-fix*`), `SCRIPTS-INDEX.md`: 6 | **Yes**: `bootstrap/**`, `.claude/agents/**`. CODEOWNER review. The `overseer.md` edit is authored by the top-level session (#1347) | S1 |

**Order.** S1 → S2. **Codable now:** S1. **S2:** design now, merge after S1, human-gated by surface. Neither slice touches `merge_authority.py`, `bin/hos-cron`, `.github/workflows/label-swap.yml` or the #1215 precheck predicate.

**What `technical-design` must specify next.**
1. The reason table: every row, its pattern, its category and the cited line (AD-4).
2. The exact closed `cause` enum and the JSON record schema of L2 (AD-3).
3. The report template, byte for byte, and the marker grammar regex (AD-4).
4. The `add_issue_labels` contract, including verification and `retries=0` (AD-3).
5. The state file schema and pruning rule (AD-6).
6. The #1792 fixture. Reconstruct it from the issue body (`labeled` 2026-09-21T10:09:00Z by `hos-overseer-hos[bot]`, `unlabeled` 18:26:43Z by `ScottThurlow`, head unchanged), and, if S1 can read it live, replace the reconstruction with the real events page.
7. The S2 wording of the four `overseer.md` sites and the paragraph, plus the contract-test anchors (AD-5).
8. How the overseer writes `--reason-file`: a literal `/tmp/claude/…` path, one line, per CLAUDE.md shell rules.

---

## 5. Requirement amendments (applied to `REQUIREMENTS-1796-bare-handback-detect.md` in this commit)

- **AM-1 (REQ-1 clause 6, AF-1).** The disposition is no longer a predicate clause the detector computes. It is an input to `finalize`. Label suppression applies on `BARE_REMOVAL` for every overseer label add on a worker PR. The report requires `HUMAN_REQUIRED`. The AC's "decision AUTO_MERGE" case moves to the `finalize` tests.
- **AM-2 (REQ-2, AF-4, #1923).** The page bound is a 100-page runaway tripwire for events and for comments. The fetch is strict per-page, and `list_issue_comments` is not used. An unreadable head commit is added to the UNDETERMINED causes. A missing removal actor is UNDETERMINED.
- **AM-3 (REQ-4, AF-2, AF-6).** The suppression is enforced through the single `finalize` wrapper and the four `overseer.md` sites. `record_pr_bounce()` is removed from the list (R-3). `labels_to_add` has no code consumer, so it is covered by the prose routing.
- **AM-4 (REQ-5, AF-3).** The report's first line is `**Decision: HUMAN_REQUIRED**`. The reason must match the closed reason table, or no report posts. The marker gains `head=<sha>`, which is informational only. The trusted author is `BOT_OVERSEER_USERNAME` with `type == "Bot"`.
- **AM-5 (REQ-6).** UNDETERMINED deduplication uses `.claudetmp/bare-handback/undetermined-seen.json` and covers the non-UNDETERMINED no-report causes too.
- **AM-6 (REQ-7, AF-5).** "New head" means head committer date > `removed_at`. Draft conversion also ends the episode.
- **AM-7 (§5 slices).** S1 is L1 + L2 + `github.add_issue_labels`. S2 adds the protected `bootstrap/bare_handback.sh` and the `overseer.md` wiring.
- **AM-8 (§6).** ESC-1 to ESC-3 are resolved as the architect's defaults (§7). No residual human ESC.

Endorsed as written: REQ-3, REQ-8, REQ-9, REQ-10, §3 non-goals and §4 acceptance.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible behaviour.** The overseer stops re-applying `needs-human` after a human removal and posts one comment. That is the human-ruled direction (2026-10-02), so it is cleared. The ESC defaults below are within that ruling and land only through S2, which is CODEOWNER-gated, so the human sees them before they take effect.
- **Cost.** A few extra GETs per unlabelled HUMAN_REQUIRED worker PR per overseer cycle, on the overseer App's own limit.
- **Retention.** One small `.claudetmp/` JSON file of `(pr, sha, cause)` keys.
- **Operations.** No new service, credential, workflow or trust boundary.
- **Startup gap: no.** This is an operational defect (PR #1792) in a later-added step-6 rule, not a decision the initial architecture review should have settled.
- **Affected sign-offs.**
  - The #1215 precheck sign-off stands, because the predicate is unchanged.
  - The `overseer.md` step-6 text approved under #1207 / #1657 / SPEC-378 is re-reviewed in S2, because four instructions change.
  - `decide_merge_authority()`'s sign-offs stand, because it is unchanged.
  - No approved design or code is orphaned.
- **Forward constraint FC-1 → ADR-1357 slice 2/4.** When `overseer_decide.compute_decision` lands, `finalize` must take the disposition and reason from it in-process, and `--disposition`/`--reason-file` are removed. Any ADR-1357 slice-4 label-writing mutation wrapper must route `needs-human`/`needs-ai` adds on worker PRs through `bare_handback.classify`, not around it. This is recorded here, and the ADR-1357 owner must honour it.

---

## 7. ESC positions

| ESC | Architect | Reason |
|---|---|---|
| ESC-1 new head ends the episode | **Concur (A)**, defined by AD-7 | It matches the head-scoped staleness rule in #741 and #1215. In the #1792 shape the head never moves, so (A) changes nothing there. |
| ESC-2 where the report goes | **Concur (A): PR comment only** | It sits where the human acted, reuses the marker pattern, and adds nothing to a backlog of about 100 `needs-human` issues. |
| ESC-3 grace period | **Concur: none** | A delay recreates the silent window. A report that turns out unnecessary costs one comment. |

**Residual human ESC: none.** The human ruled on the direction. These three positions are technical calls inside that ruling, and the human can still overturn any of them at the S2 CODEOWNER review.

```yaml
adr: ADR-1796
issue: 1796
codable_now: [S1]
design_now_merge_after: {S2: [S1]}
hard_constraints_not_waivable: [REQ-2, REQ-4, REQ-5]
not_touched: [scripts/automation/lib/merge_authority.py, bin/hos-cron, .github/workflows/label-swap.yml, "#1215 precheck predicate"]
escalations: []
forward_constraints: [{id: FC-1, target: ADR-1357, rule: "finalize consumes compute_decision; slice-4 label wrappers route through classify"}]
```

---

## 8. Follow-ups (named, not filed here)

- **FU-1 → pm-agent.** Consolidate the per-page fetchers (`probe._fetch_events_paginated`, `select_work_candidates._fetch_pages`, this module, ADR-2102 FU-1) into one shared helper, with the #1923 tripwire semantics.
- **FU-2 → pm-agent (R-1).** Add a cheap, read-only after-the-fact check. In the events of a worker PR, an overseer `labeled needs-human` that follows a non-bot `unlabeled needs-human` with no intervening head change means the overseer bypassed `finalize`. It could sit in `oversight-evaluator` Phase 1 or a periodic sweep. File it only if bypasses are observed.
- **FU-3.** Option (b) `/park` remains the ruled follow-up if bare handbacks recur. The `bare-handback-reported` audit events are the recurrence measure.

## Escalation flag (CORE self-flag)

RISK: MEDIUM. The classifier is read-mostly and can only withhold a label or post one comment. It cannot relax a merge gate (VF-3). S2 changes four protected overseer instructions that run on every HUMAN_REQUIRED worker PR.
CONFIDENCE: HIGH on §0, where every citation was read this session at the stated lines, and on AF-1 to AF-4. MEDIUM on the events-API field shape for `unlabeled` actors (`actor.type`), which S1 probes live. MEDIUM on R-1's practical weight: the routing is prose until FC-1.
BLAST RADIUS: overseer label writes on open worker PRs only. No issue, worker-routing, merge, gate or workflow path changes.
Change classification: STRUCTURAL.

## Human Review Required

S2 edits `.claude/agents/overseer.md` and adds `bootstrap/bare_handback.sh`. Both are protected, and your own-account approval of that PR is the final gate. ESC-1 to ESC-3 take the pm-agent defaults, and I concur with each. Overturn any of them at that review if you disagree. S1 is unprotected and may be built now. REQ-2, REQ-4 and REQ-5 are not open to any answer.
