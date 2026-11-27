# Finding: API Field Shapes Must Be Verified Against Live Responses — Documentation Assumptions Cause Silent Correctness Failures

**Role:** oversight-mechanism — correctness of machine-readable protocol parsing

**First observed:** 2026-06-16, `merge_authority.py` R5.6.2 implementation, issue #348

---

## The Finding

The release authorization protocol (worker.md R5.6.2) was implemented to check that the GitHub-API-verified actor who performed the re-assignment was a human CODEOWNER. The implementation read `actor.login` from the `assigned` event in `GET /repos/{o}/{r}/issues/{n}/events`.

During the first live run, `actor.login` returned `HOSWorkerTutelare` — the bot account, not the human who performed the assignment. The authorization check failed because the bot appeared to be self-assigning.

The actual GitHub Issues Events API structure:
- `actor`: the **assignee** (who was assigned TO)
- `assigner`: the **performer** (who did the assigning)

The field `assigner` is undocumented in some GitHub API references, or documented inconsistently. The implementation assumed `actor` = performer based on the common REST convention that `actor` means "who performed the action." For assignment events, GitHub uses `actor` differently.

**The broader pattern:** REST API field naming is not standardized across event types. An `actor` in a `labeled` event means the labeler (the performer). An `actor` in an `assigned` event means the assignee (the affected party). The same field name carries different semantics depending on the event type.

## Why It Matters for Automated Pipelines

A human reading the GitHub web UI sees the assignment correctly attributed. An automated pipeline reading `actor.login` will silently misread every assignment event, treating the assignee as the performer. The authorization check inverts: the bot (being assigned to) fails the "must be human CODEOWNER" check because it IS the bot — even though a human performed the assignment.

This failure mode is particularly dangerous because:
1. It passes in testing (the code runs without error)
2. It fails silently in production (the authorization check rejects valid authorizations)
3. The failure looks like a configuration problem or a permissions issue, not a field-name bug

## The Fix and the Verification Obligation

Fix: use `assigner.login` (the performer) not `actor.login` (the assignee) for assignment events.

The verification obligation in the technical design (SPEC-evaluator-re-derivation.md §6.4): *"Before relying on field paths, the coder must confirm against a live API response that the payload exposes the expected fields."* This is a standing obligation for any code that parses GitHub API event payloads — verify the field shape against a real response before writing the code that depends on it.

## Evidence

- Issue #348: `actor.login` vs `assigner.login` in R5.6.2 — discovered during the first live run of the release authorization protocol
- `merge_authority.py` R5 §6 condition 2: corrected to use `assigner.login`
- GitHub Issues Events API: the `assigned` event carries both `actor` (assignee) and `assigner` (performer); the `labeled` event carries only `actor` (labeler/performer); the semantics differ by event type

## Implications for Research

1. **Field name conventions are not a substitute for empirical verification.** `actor` conventionally means "who did the action" in most REST APIs. GitHub is an exception for certain event types. Conventions reduce the effort of reading documentation; they do not replace reading documentation.

2. **Silent correctness failures from API shape assumptions are worse than loud errors.** A misread that causes a crash is immediately visible. A misread that causes an authorization check to silently reject valid authorizations may go unnoticed for many cycles.

3. **Protocol implementations should include a live-response verification step in the testing suite.** A unit test that mocks the API cannot catch a wrong field name — it will mock the wrong field faithfully. An integration test against the live API (or a recorded fixture) would catch this class of bug.

4. **Event-type-specific field semantics should be explicitly documented in any spec that parses event payloads.** The SPEC-evaluator-re-derivation.md §6.4 "coder verification note" is the right pattern: name the expected fields, require verification, and provide a route-back path if the shape differs.

## Related findings

- `reviewer-agents-file-confident-non-reproducing-reports.md` — a different class of silent failure (reports that don't reproduce); the common thread is that confident-looking output can be wrong without any error signal
- `working-state-invariant.md` — implementation assumptions about external state that don't hold; this is the API-field-specific instance

---

## 2026-10-22 probe: comment edit signal (#2101, ADR-2101 AD-4)

**Question.** Which REST field on an issue comment reliably signals that a human's authorization body was edited after posting? ADR-2101 AD-4 rejects any edited comment as an authorization act, so the verifier needs a field that moves on a body edit and, ideally, on nothing else.

### Method

Read-only: no comment was created, edited, hidden or reacted to.

1. **All comments in this repo.** `GET repos/thurlow-research/HumanOversightSystem/issues/comments?per_page=100&sort=created&direction=asc&page=1…25` returned 2,440 comments, from 2026-06-12 to 2026-10-22. For each I recorded `id`, `user.login`, `user.type`, `created_at`, `updated_at`, `reactions.total_count` and `html_url`.
2. For every comment with `updated_at != created_at`: `GET …/issues/comments/{id}` for its `node_id`, then a GraphQL **query** (no mutation) for `createdAt`, `updatedAt`, `lastEditedAt`, `includesCreatedEdit`, `reactions.totalCount` and `userContentEdits(first:5){editedAt editor{login}}`.
3. **Reactions.** This repo has no reacted comments, so the same method was applied to public repos. I took pages 2 to 11 of `GET repos/{cli/cli, microsoft/vscode}/issues/comments?sort=created&direction=desc` and kept every comment with `reactions.total_count > 0`. For each reacted comment whose timestamps differed, I ran the GraphQL query above, plus `isMinimized`, `minimizedReason` and the `createdAt` of each reaction.
4. **Contents-API shape.** `GET repos/…/contents/.github/CODEOWNERS?ref=main` gives `{type:"file", encoding:"base64", content, sha, size}`. A missing path gives HTTP 404 with the error JSON on stdout, and `gh` exits with rc=1 (probed: `contents/.github/NOPE` gives `rc=1`). A caller must therefore check the return code before parsing stdout.

### Results

| Population | n | `updated_at == created_at` | `updated_at != created_at` | Cause of every `!=` |
|---|---|---|---|---|
| HOS repo, all comments | 2,440 | 2,426 | 14 | **14/14 real body edits.** GraphQL `lastEditedAt == updated_at` and `userContentEdits` ≥ 2 in every case. Editors: `ScottThurlow` ×8, `hos-worker-hos` ×4, `hos-overseer-hos` ×2. Each App edited only its own comments. |
| Public, reacted comments | 151 | **129** | 22 | 16 real body edits (`lastEditedAt == updated_at`). **5 hidden (minimized)**: `isMinimized=true` (spam ×4, low-quality ×1), `lastEditedAt=null`, no edits. 1 unexplained (`cli/cli` 5693523114: last edit 09-16T07:14:44Z, `updated_at` 09-17T09:13:48Z, not minimized now, no reaction at that instant). |

**Reaction timing.** In several comments reactions were added **after** `updated_at` and did not move it:
- `vscode` 6308694016: reaction at 05:21:32, `updated_at` 05:21:24;
- `cli/cli` 5921072446: reactions on 10-05, `updated_at` 10-01;
- `cli/cli` 5693523114: reactions on 09-18 and 09-19, `updated_at` 09-17.

### Conclusion

- **Reactions do not bump REST `updated_at`.** Evidence: 129/151, plus timestamped reactions later than `updated_at`.
- **Every observed body edit bumps it,** and equals GraphQL `lastEditedAt`: 30/30.
- **Hiding (minimizing) a comment bumps `updated_at` without an edit**, and one unexplained non-edit bump exists.

**Design decision.** The REST rule `updated_at == created_at` is the **sole** pass condition. The GraphQL `lastEditedAt` alternative pass condition that AD-4 permits is **not adopted**: it would accept a *hidden* comment (`lastEditedAt` null), which is not the direction we want for a forgery control, and it would add a POST-transport GraphQL fetch to the trust path for no observed benefit. Any non-edit bump, such as a hide or the unexplained case, is an over-refusal: the human posts a new comment. This is AD-4's stated fail-closed direction, now backed by evidence.

**Residual R-S1-1.** REST timestamps have one-second resolution. An edit landing in the same wall-clock second as creation would leave `updated_at == created_at`. Exploiting it needs a bot to observe and rewrite a human's comment within one second of posting. This is judged negligible and is not mitigated in v1 (accepted by the architect, ARCH-Q7).

### Implications

- `updated_at` is an *any-change* signal, not an *edit* signal. Using it as an edit detector is safe only in the fail-closed direction, and any consumer that treats `updated_at != created_at` as proof of a body edit (rather than as "refuse") is wrong for hidden comments.

---

## 2026-10-30 probe: comment-deletion signal (#2151, TD-2101 R-A1 option (a), R-S1-5)

**Question.** Can the verifier see that someone deleted a human's issue or PR conversation comment? If it can, which fields are exposed: the deleted comment's author, its creation time, and the deletion time? R-A1 asks for the REST issue timeline first. GraphQL is allowed only if REST lacks the signal.

### Method

Read-only. No comment, reaction, label or issue was created, edited, hidden or deleted. REST reads were `gh api <GET endpoint>`. The GraphQL reads were `gh api graphql` **queries**. They travel as a POST, but no mutation was ever sent. The authenticated identity was the HOS worker App.

1. **REST, this repo.** `GET repos/thurlow-research/HumanOversightSystem/issues/{n}/timeline?per_page=100&page=k` for every `n` in 1900–2220 (321 numbers, all pages; 2 numbers do not exist and gave rc≠0).
2. **GraphQL, locate real deletions.** `repository.{issues|pullRequests}(first:100, orderBy:UPDATED_AT DESC)`, up to 10 pages per repo. Each node asked for `timelineItems(itemTypes:[COMMENT_DELETED_EVENT]){filteredCount nodes{... on CommentDeletedEvent{databaseId createdAt actor{login __typename} deletedCommentAuthor{login __typename}}}}`. Issues were scanned in `cli/cli`, `microsoft/vscode`, `home-assistant/core` and `nodejs/node`. PRs were scanned in those four plus `DefinitelyTyped/DefinitelyTyped`, `pytorch/pytorch`, `rust-lang/rust`, `kubernetes/kubernetes` and `flutter/flutter`. The same query was also run on the last 100 issues and 100 PRs of this repo.
3. **REST cross-check.** For every thread found in step 2: all pages of `GET …/issues/{n}/timeline` and of `GET …/issues/{n}/events`. Each `event == "comment_deleted"` item was matched to GraphQL by id. For every event GraphQL had and REST did not list: `GET repos/{o}/{r}/issues/events/{id}`.
4. **Shape of the design query** (§10.4 of TD-2101). The query `issueOrPullRequest(number:){__typename … on Issue|PullRequest{number timelineItems(itemTypes:[COMMENT_DELETED_EVENT], first:100, after:$after){filteredCount pageInfo{hasNextPage endCursor} nodes{…}}}}` was run on an Issue (HOS #2101), on a PR (DefinitelyTyped #74968), and on a nonexistent number (999999).

### Results

| Population | Threads with a deletion | `CommentDeletedEvent`s (GraphQL) | Listed by REST `/timeline` | Listed by REST `/events` |
|---|---|---|---|---|
| HOS repo #1900–#2220 (REST), and the last 100 issues + 100 PRs (GraphQL) | 0 | 0 | 0 (the 95 items matching `delet` were all `head_ref_deleted`) | — |
| Public issues | 12 | 18 | **18/18** | 18/18 |
| Public PRs | 24 | 40 | **29/40** | 29/40 |
| **Total** | 36 | 58 | **47/58** | 47/58 |

- **Ids and times agree.** On every listed event, GraphQL `databaseId` equals the REST event `id`, and GraphQL `createdAt` equals REST `created_at`.
- **REST omits some events without any signal.** All 11 unlisted events sit in two PR threads: `rust-lang/rust#112049` (1) and `kubernetes/kubernetes#113883` (10). In both, the REST listings otherwise look complete. For example, on `rust#112049` REST lists 2,466 `commented` items and GraphQL `comments.totalCount` is 2,466, and the listing's tail reaches 2026-10-21, after the deletion (2025-11-07T22:13:35Z). Yet `GET …/issues/events/{id}` returns each missing event, with `event: "comment_deleted"` and the right `issue.number`. So REST **stores** these events but does **not list** them. The cause was not determined. Two candidates: the deleted comment was a review comment, or its author account was deleted (all 10 `k8s` events have `deletedCommentAuthor: null`). Neither could be verified read-only.
- **REST fields** (one key set across all 47): `actor`, `commit_id`, `commit_url`, `created_at`, `event`, `id`, `node_id`, `performed_via_github_app`, `url`. `actor` is the **deleter**, and `created_at` is the **deletion** time. No field gives the deleted comment's author, id or creation time.
- **GraphQL fields:** `actor` (the deleter), `createdAt` (the deletion time), `databaseId`, and `deletedCommentAuthor`, which was `null` in 17/58 events. Neither transport exposes the deleted comment's id or creation time.
- **The attack shape is recorded.** A GitHub App deleting a `User` account's comment appears in 5/5 DefinitelyTyped PRs, on both transports. REST shows `actor.login = typescript-automation[bot]` with `type = Bot`. GraphQL shows `deletedCommentAuthor = typescript-bot`, a `User`.
- **Self-deletion was not observed.** In the 41 events with a known author, the deleter was never the author (0/41). Testing whether GitHub records a self-deletion would need a write, so it was not tested.
- **Query mechanics.** `timelineItems.totalCount` ignores `itemTypes`; `filteredCount` is the filtered count. `endCursor` is `null` when there are no items. A GraphQL-level error, such as a nonexistent number, makes `gh` exit 1 with the error JSON on stdout (`{"data":{…:null},"errors":[{"type":"NOT_FOUND",…}]}`). This matches the REST 404 behaviour above, so the return code must be checked before parsing.

### Conclusion

- REST **has** the deletion signal, but its listings are **not complete**: 47/58 events were listed, and the 11 missing ones cluster in 2 of 36 threads, both PRs, with no marker. A REST-only detector would miss those deletions silently, in the fail-open direction.
- GraphQL returned every event REST listed, plus the 11 REST did not. It also names the deleted comment's author. Caveat: GraphQL was the discovery source, so this sample cannot measure GraphQL's own misses.
- Neither transport gives the deleted comment's creation time. A sound rule must therefore compare the **deletion** time with the governing act: a comment deleted before the act was created before it, so only deletions at or after the act's creation time can have removed a newer comment.

**Design consequence.** TD-2101 §10.4 (S1b) adds refusal reason `deleted-later`. It recommends the GraphQL read, as a fail-closed input. That is a second transport on the trust path, so it goes to the architect as `ARCH-Q-S1b`. The REST-only alternative is specified there too, with its residual.

### Implications

- "The REST API has event type X" does not mean "the REST listing returns every X". Here an event retrievable by id was absent from both per-issue listings. A detector built on a listing must check its completeness against an independent count (here, GraphQL `filteredCount`), or it fails open.
- A deletion event's `actor` is the **deleter**, not the author of the deleted comment. This is the same trap as the `assigned`-event `actor` finding at the top of this file: the field name does not say whose identity it carries.

## 2026-11-25 probe: GraphQL lastEditedAt edit probe (#2151 bounce F3)

**Question.** The REST comment fields `created_at` and `updated_at` have one-second resolution, so an edit made in a comment's creation second looks unedited (R-S1-1, ARCH-Q7). Does GraphQL `IssueComment.lastEditedAt` cover that gap, and can one fixed query page the comments of an Issue and of a PullRequest with the same ids as REST? Context: the PR #2459 bounce, finding F3, and the ruling "2151 bounce Q1 A Q2 A".

### Method

Read-only. No comment was created, edited, hidden or reacted to. The exact `EDITS_QUERY` of TD-2101 §10.5.2(a) was run with `gh api graphql` (a query, no mutation) against HOS #2151 (an Issue, 17 comments) and HOS PR #2459 (a PullRequest, 5 comments). The REST side was `GET repos/{o}/{r}/issues/{n}/comments`.

### Results

- `comments.totalCount` equalled the REST comment count on both: 17 and 5.
- Every `fullDatabaseId` equalled a REST `id`, as a decimal string. `databaseId` is above 2^31 for current comments (for example 7118361785), which overflows GraphQL `Int`, so the query uses `fullDatabaseId`.
- `lastEditedAt` was non-null on exactly the 2 comments where REST `updated_at != created_at`, and it equalled `updated_at`.
- A second page (`after` = page 1's `endCursor`) returned 0 nodes, `hasNextPage` false, `endCursor` null, and the same `totalCount` (17).

### Conclusion and design consequence

GraphQL `lastEditedAt` agreed with REST on 2 of 2 edits, and the two transports list the same comment ids. TD-2101 §10.5.2 adds it as read 7, ANDed with the REST rule: a comment is unedited only if `updated_at == created_at` and the probe returned its id with `lastEditedAt` null. Residuals R-F3-1 and R-F3-2 are in the module docstring of `human_authorization.py`. R-F3-1: whether GraphQL could lag a same-second edit that REST already shows cannot be tested read-only, and was not observed. R-F3-2: `totalCount` is a same-source count, so it checks pagination integrity and does not prove completeness.
