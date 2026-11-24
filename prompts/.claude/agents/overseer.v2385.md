# Prompt Artifact — overseer.md step 4d, independent review lenses (v2385)

| Field | Value |
|---|---|
| **Generated file** | `.claude/agents/overseer.md`, `bootstrap/overseer-cron-prompt.md`, `docs/OVERSIGHT-RUNBOOK.md`, `METHODOLOGY.md` |
| **Description** | #2385 (INTERIM, maintainer decision 2026-11-17): the overseer dispatches every applicable review lens itself on every PR, until #1643 W7/W8 move it into code. |
| **Date** | 2026-11-19 |
| **Model** | claude-opus-5-5 (autonomous worker, top-level session) |
| **Risk level** | HIGH (protected surface: `.claude/agents/**`, cron prompt) |
| **Human review status** | ⬜ Pending |

---

## Authoring note

Per CLAUDE.md "Agent-definition edits (HOS source repo only)" (#1347), governance
edits to `.claude/agents/*.md` are authored directly by the top-level worker
session, not by the `coder` subagent. The control is the protected-surface human
approval gate (CODEOWNERS). The cron prompt and docs went in the same change so
the instruction surfaces stay consistent.

## Prompt (the issue's scope, as implemented)

Source: issue #2385 body, "Scope" items 1-7 and "Acceptance".

1. Which lenses: `bash scripts/framework/run_post_change_sweep.sh --json <changed files>`.
   Every applicable judgment dimension is required. No skipping by tier, no overseer
   judgement. A non-zero exit fails loud.
2. Dispatch the matching shipped reviewer agent through the Agent tool, and add the
   agents to `dispatches:` in `overseer.md`.
3. Independent inputs: the diff, the linked issue, the technical design, and the repo at
   the PR head. Never the worker's register entries, reviewer transcripts, or PR-body
   rationale (#700).
4. A blocking finding is a send-back via `bootstrap/merge_authority.sh route`, naming the
   lens, file, line and failure scenario. A clean worker register never outweighs it.
5. The verdict lists every required lens and its outcome. A failed or unparseable lens
   means `needs-human` and no approval. A lens is never claimed as run unless its output
   is quoted.
6. Composes with #2357, #2381 and #2327.
7. Marked `INTERIM (#2385)`, retired by #1643 W7/W8.

## Implementation decisions not spelled out in the issue

- The sweep runs from the **main checkout**, never the PR worktree, so a PR that edits
  the dimension registry cannot pick its own reviewers.
- A lens is required when any of its `plan` items is `kind: judgment`, `applicable: true`.
  Deterministic items (gates, validators) are covered by other steps.
- Findings use the existing `REVIEW_FINDING` class of `merge_authority.py` (path + slug +
  detail), so no code change was needed. The slug stays stable per finding per head, so a
  re-run does not spend another bounce.
- Reviewer output contract: four-field
  `FINDING: <blocking|suggestion> | <repo-relative path> | <line> | <defect and failure scenario>`
  lines at column 0. These are followed by a final `LENS-VERDICT: CLEAN|FINDINGS` line,
  where CLEAN is allowed only with no FINDING lines. A missing or unparseable line counts as
  failed to run. (The text in this section reflects the final contract; the review rounds
  below record how it got there.)
- Reviewers are told they are read-only: no register writes, no comments, issues or
  labels, and no stash or checkout. This draws on the reviewer-side-effect incidents.
- The step is placed after 4a/4c (procedural and CI bounces are cheaper) and before the
  pre-matrix gates and the matrix.
- The fail-loud path takes step 6's HUMAN_REQUIRED (other reasons) path: a `comment`
  verdict with Expected action OTHER, the CODEOWNERS human requested (#1668), and the label
  applied last.

## Round-1 review fixes (code-reviewer, security-reviewer, reliability-reviewer)

- **Consumer installs (maintainer to confirm):** `run_post_change_sweep.sh` is withheld from
  consumers until #1643 W7, so step 4d runs only where the script exists (the HOS source repo).
  Elsewhere every verdict says the lenses did not run. Without this, every consumer PR would
  fail loud to `needs-human`.
- File-list completeness: a `gh` failure, an empty list, a count different from the PR's
  `changed_files`, or a control character in a name is a failed lens run. Rename sources are
  included.
- Sweep set equality: the sweep's `changed_files` must equal the names passed. A `HEAD*` or
  `-*` name otherwise drops out silently. A `./` prefix was tested and rejected, because it
  stops `bin/hos-cron` matching the infra binding.
- Strict report parse: the verdict is the last line only. Contradictory or duplicate verdict
  lines are a failed lens run. Quoted file lines are indented. Findings are split on the first
  three ` | ` only.
- Fail-loud path: it now takes step 6's HUMAN_REQUIRED (other reasons) path as written, so
  the label goes last, with the section 8.2 thread and the audit event.
- Bounce path: the lens record goes in each finding's `detail` `lenses:` tail, since `route`
  posts no verdict review.
- Write check: it now also compares `git status --porcelain` of the main checkout before and
  after. A reviewer's GitHub writes remain a stated residual, closed by W7.
- Merge base: taken from the compare API. A worktree failure is a failed lens run. The slug
  keeps the line number, and colliding slugs are merged. `@` and closing keywords are stripped
  from routed text. A short cron budget defers the PR.

## Second-review fixes (agy round 1: 7 findings, all verified against the text and fixed; codex approved)

- The write check now runs first, as soon as the lenses return and before parsing, bouncing or
  cleanup. A failed check overrides every finding (HUMAN_REQUIRED). A changed main checkout also
  stops further PR reviews this cycle.
- Verdict line: `CLEAN` only with zero `FINDING:` lines, otherwise `FINDINGS`. A suggestion-only
  `FINDINGS` is non-blocking.
- The cron prompt's #2287 API/diff fallback no longer applies to the 4d lenses.
- The bounce `lenses:` tail carries the sweep digest and each lens's verdict line. The failure
  text is shortened before the tail.
- `<line>` must be a non-negative integer (0 for a whole-file finding). Basename collisions
  merge into one entry and name every file.
- A compare-API failure or a non-SHA response is a failed lens run. The budget check now runs
  before the worktree is created.
- `|` is escaped in quoted table cells.

## Second-review run 2 fixes (agy: 7 findings; codex: 1)

- agy: `-`/`HEAD` names, `<!--` names and control characters are rejected before the sweep.
  The set-equality check stays as defence in depth.
- agy: a file-count mismatch first re-reads `head.sha`, and restarts the review if the head
  moved.
- agy: when no lens applies, sub-steps 2-5 are skipped entirely.
- agy: the parse also fails an empty report, an invalid final line, and an empty path or
  defect field.
- agy: the slug uses `Path.stem`. A slug merge keeps the first changed-file `path`.
- agy: sanitization covers every PR- or reviewer-derived table cell, not just the quotes.
- agy: the stale contract text in this artifact is corrected.
- **codex (partially met, residual disclosed):** codex asked for filesystem or process
  isolation, which an instruction-level step cannot provide. That gap is the premise of the
  INTERIM label, and #1643 W7 closes it. Done instead: the main checkout must have no
  tracked modifications before dispatch (fail-closed). The text also states exactly what the
  status/HEAD check cannot see: content changes to already-untracked or ignored files, files
  under `audit/log/`, and GitHub writes.

## Second-review run 3 fixes (agy: 4 findings; codex: approve), plus reviewer suggestions

- agy: the Route success rule now carries step 4a's `at_cap` and `finalize_errors`
  conditions.
- agy: one sanitization procedure covers every derived text location, including the executive
  summary. Newlines are flattened.
- agy: a failure before the sweep has a defined one-row table (`(all)`, digest `none`).
- agy: the linked issue is optional when the PR names none. A failed read of a named issue is
  a failed lens run.
- security-reviewer: a GitHub-side post-check. The head is unchanged, the PR is not merged or
  closed, and no overseer-App review was submitted during dispatch. This applies because
  reviewer subagents hold this session's token. The isolation disposition is recorded as
  **partially met**, not met.
- reliability-reviewer: at most one restart per PR per cycle. A second head move defers the
  PR.

## Human ruling 2026-11-20 (Q1 A, Q2 C, Q3 fix all, Q4 A) — delta applied 2026-11-21

- **Q1 A:** no new code-review loop for the earlier `64a9c7bf1..f5d7728a4` delta. The ruling delta below is reviewed once, batched, by code-reviewer, security-reviewer and reliability-reviewer.
- **Q2 C:** on any PR where step 4d requires at least one lens for the head (every cycle that reviews it), an AUTO_MERGE matrix result takes the PROPOSE_ONLY path (request the human, `comment` verdict, Expected action APPROVE). Step 1a merges on the human's approval of the head. Empty lens sets and consumer installs are unaffected. Retired with W7.
- **Q3.1:** the "overseer review after dispatch" check compares against a pre-dispatch set of this App's review ids, not a timestamp.
- **Q3.2:** a PR merged or closed during dispatch stops its handling (no reviewer request, verdict, label or matrix), files one `needs-human` `priority:critical` issue via `create_issue.sh`, and ends PR review for the cycle.
- **Q3.3:** a main checkout already dirty before dispatch also ends PR review for the cycle, not just this PR's lenses.
- **Q3.4:** every `FAILED (<reason>)` is capped at 80 characters after sanitizing, wherever it appears.
- **Q4 A:** confirmed; the consumer-install exemption is unchanged.
- **Ruling-delta review (code-reviewer, security-reviewer, reliability-reviewer: all APPROVED at 92399a5eb), suggestions applied:** the Q2 C trigger is the non-empty required lens set (deterministic, holds on every cycle reviewing the head) rather than "dispatched this cycle"; merged/closed wins over the other write-check conditions; a `create_issue.sh` failure becomes the headline outcome; a human merge during dispatch is named as benign noise; residuals add cross-PR writes and deleted reviews; PROPOSE_ONLY wording covers the lens-withheld case. Deferred to a follow-up issue: lens re-dispatch each cycle while a PR waits on the human, a persistent dirty checkout throttling the queue, and the lens budget floor.

## Final second-review run 5 (2026-11-21, full range at d7ce9ae7a): agy 4 findings fixed; codex CWE-862 filed

- agy (high): the GitHub baseline records `id`, `state` and `body` of each overseer-App review, so an in-place body edit or a dismissal (same `id`) fails the write check.
- agy (medium): both main-checkout status commands use `--untracked-files=all`, so a new file inside an already-untracked directory is seen.
- agy (medium): a non-worker PR with a blocking lens finding takes HUMAN_REQUIRED (other reasons) with Expected action `REQUEST CHANGES`; `OTHER` stays reserved for a failed lens run.
- agy (low): step 5's AUTO_MERGE rule names the Q2 C exception.
- codex (critical, CWE-862): reviewer subagents hold the overseer token. This is the Q2 residual the human ruled on (C, not B, 2026-11-20). Dispositioned `filed:#1643` (W7 runs the lenses in code without the token).

## Final second-review run 6 (2026-11-21, full range at 769604a2b): 2 new agy findings fixed

- agy (high): a review by this App that changed during dispatch and is now `APPROVED` is dismissed before the HUMAN_REQUIRED handling (a later `comment` verdict does not revoke it); a failed dismissal is named first.
- agy (medium): a change to this App's reviews during dispatch is contained like a merged or closed PR: a `needs-human` issue is filed and no further PR is reviewed this cycle.
- The ledger's `logic-error → fixed` entry silenced both as `new=0`; they were found by reading the payload.

## Final second-review run 7 (2026-11-21, full range at ac7e9e3e8): 1 new agy finding fixed

- agy (medium, error-handling): the security issue for a changed App review is filed right after the dismissals and before sub-step 5, so a sub-step 5 halt cannot drop it; its body lists every failed dismissal (review id, exit code or HTTP status). codex repeated CWE-862 (ledgered `filed:#1643`).

## Human send-back 2026-11-21 (CHANGES_REQUESTED on PR #2433 at 5bc8cc87e)

Prompt (ScottThurlow, verbatim in substance): fix #2432 item 1 in this PR before
merge. Step 4d must not re-dispatch lenses or post a new verdict on an unchanged
head that already has this App's verdict and a pending human request; reuse the
recorded lens table. The code-review loop cap is reset for this change. Q2 C stands
for CWE-862, cross-PR writes included, until #1643 W7. #2432 items 2–3 stay deferred.

As implemented (step 4d sub-step 1, new "Unchanged head awaiting the human" bullet):
reuse when the required set is non-empty, this App has a review on `head_sha` with
the lens table, that table names this sweep's digest and exactly the required lenses,
`requested_reviewers`/`requested_teams` is non-empty, and nothing but this App's own
entries is newer than it in the comments+reviews union. Reuse = skip the PR for the
cycle (no dispatch, no verdict, no thread, no audit, no labels), one `LENS-REUSE:`
stdout line. 4a/4c bounces and step 1a's merge are unaffected. The #1215 "one dedup
authority" statements (step 5 and step 6 HUMAN_REQUIRED CRITICAL) name this as the
one exception. The cron prompt summarises it.

Send-back review round 1 (code-reviewer APPROVED, reliability-reviewer and
security-reviewer CONDITIONAL, no MUST_FIX), all SHOULD_FIX applied in one batch:
no `FAILED`/`(all)` row may be reused (a failed run is always retried); `recorded`
must not be `DISMISSED`; a recorded HUMAN_REQUIRED needs `needs-human` present (an
unfinished step 6 is finished by a full review); the human condition is
`HUMAN_REVIEWER` requested **or** having reviewed the head (a human comment or
approval costs one full review, then reuse resumes); the newer-entry union is
paginated and includes review-thread comments, ties count as newer, a failed read
discards partial output; the #1215 "every other step-6 action still runs" sentence
is scoped; residuals add the base-branch move and the App-token forgery (Q2 C, W7).

Send-back review round 2: security-reviewer and reliability-reviewer APPROVED;
code-reviewer APPROVED with one SHOULD_FIX, applied: the `needs-human` condition is
scoped to non-CRITICAL tiers (step 6's CRITICAL path applies no label, so the
condition would never hold there and re-dispatch every cycle). Step 5's exception
sentence now names `HUMAN_REVIEWER` requested-or-reviewed, matching sub-step 1.

Full-range second review at 4b5372eed (agy + codex, `--tier HIGH`): codex CWE-862
repeated (ledgered `filed:#1643`, Q2 C restated by the human). agy raised five new
findings, all applied: a "newest entry seen" line under the lens table so the
verdict after a human entry always differs and the wrapper posts it (no
re-dispatch loop); the CRITICAL `needs-human` exemption only for a CRITICAL-tier
`Expected action: **APPROVE**` record; a `DISMISSED`/`PENDING` human review does not
count; a comment's `updated_at` counts; the cron prompt states the non-empty set,
most-recent review and `LENS-VERDICT:` quote conditions.

Code review of the agy-fix delta (1 MUST_FIX, 2 SHOULD_FIX, all applied): the
reuse check and the "newest entry seen" line share one effective timestamp
(comment: later of `created_at`/`updated_at`; review: `submitted_at`), the line
always names the newest non-App entry and is re-read just before composing the
verdict; the sanitizer drops reviewer text containing `Expected action:` or
`**Decision:` so a quote cannot forge the reuse markers.

Full-range second review at 611b1d63a: codex CWE-862 repeated (ledgered). agy
raised three new findings, all applied. (1) high, TOCTOU: the watermark was
read after step 5, so an entry landing between step 5 and the post was
absorbed. It is now read immediately before step 5, and reuse requires the
current newest non-App entry to equal the one the watermark names (same list,
id and effective timestamp, with a deterministic tie-break), rather than
comparing against `recorded.submitted_at`. This also closes the same-second
tie. (2) `recorded` is the App's single most recent review on the head; it
qualifies only if it is not DISMISSED or PENDING, has a `submitted_at`, and
carries the table. It never falls back to an older review. (3) A failed
watermark read writes `unreadable (<list>)`, which is never reused.

Code review of 8a09abffa (1 MUST_FIX, applied; security and reliability APPROVED):
`post_review_thread.sh` submits an empty-body `COMMENT` review to carry each §8.2
thread, which would become the "latest review" and defeat reuse on every
HUMAN_REQUIRED PR. `recorded` is now the App's latest review with a non-empty body,
with no fallback behind a non-empty review that does not qualify.

Full-range second review at fa77a9bd2: the gate passed with `approve` (codex CWE-862
and an agy high `error-handling` silenced by the ledger). The silenced agy finding
was new content, so it and four more agy findings were read and applied:
- An unset `HOS_BOT_LOGIN` fails the pre-dispatch baseline (every lens failed),
  and the watermark becomes `unreadable (bot-login)`.
- A review's `state` is part of the watermark identity, so a dismissal ends reuse.
- `recorded` is ordered by the highest review id.
- The list tokens are fixed (`issue_comments`, `reviews`, `review_comments`), and
  the line has an exact format.
- Verdict paths that do not reach step 5 read the watermark just before composing.

Squashed send-back delta to 9527c89c9, then a full-range second review there.
codex CWE-862 is ledgered. agy raised three findings, all applied:
- The watermark records `dismissed=<n>` (dismissed non-App reviews), so
  dismissing a non-newest review ends reuse.
- The sanitizer also drops `Newest entry seen:` and `### Review lenses`.
- The tie-break order is explicit: `reviews`, then `review_comments`, then
  `issue_comments`, then highest id.
