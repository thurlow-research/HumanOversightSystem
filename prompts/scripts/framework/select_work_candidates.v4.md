# Prompt Artifact — select_work_candidates.py (v4)

| Field | Value |
|---|---|
| **Generated file** | `scripts/framework/select_work_candidates.py`, `tests/framework/test_select_work_candidates_native.py`, `docs/v0.7.0/ADR-1644-stage-per-cycle.md` |
| **Description** | #2173: thin T3.3 — a closed blocker satisfied by a merge onto the default branch or by a verified CODEOWNER closure unblocks its dependent (ESC-3(a)) |
| **Date** | 2026-10-28 |
| **Model** | claude-opus-5-5[1m] (orchestrating worker and `coder` subagent) |
| **Risk level** | HIGH (validator tier_floor HIGH; protected surface: selector) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → `coder` subagent brief (verbatim except that the cwd/branch, test-command and trailer-block lines are elided):

```
You are implementing GitHub issue #2173 ("thin T3.3") in the HOS repo.

## Problem
scripts/framework/select_work_candidates.py (_native_verdict) excludes any issue whose
native issue_dependencies_summary has total_blocked_by > blocked_by (i.e. it has a CLOSED
blocker) with reason blocker-closed-unverified, forever. ADR-1644 (:306 and AD-C14 at
:651-662) says this holds "until T3.3 lands the paid satisfaction check". In practice closed
blockers hide their dependents indefinitely (#1776 hid 35 issues for 5 days; #1605 is hidden
by closed #2147). This issue pulls the satisfaction check alone into v0.7.0.

## Required behaviour (ESC-3(a), already decided — not a design question)
1. A blocked_by edge is SATISFIED iff the blocker is state=closed with
   state_reason=completed AND the closure is attributable either to (a) a merge onto the
   default branch, or (b) a verified individual human CODEOWNER (the closer).
2. not_planned, duplicate, any other state_reason, or an unattributable closure =>
   UNSATISFIED: the dependent stays excluded with the existing literal reason
   blocker-closed-unverified and is reported as today.
3. A dependent whose blockers are ALL closed-and-satisfied (blocked_by == 0, no sub-issues)
   is selectable. The edge is never deleted (the selector never writes to GitHub).
4. The check is PAID: every request counts against the existing _Budget; running out of
   budget is DEGRADED (unevaluated, complete=no), never a silent pass and never a silent
   exclusion-as-determined. Mirror how the D5 walk already handles a REFUSED events fetch.
5. Out of scope: T3.2 stage machinery, cycle detection, dangling edges, edge ⊇
   tracking-block checks.

## Evidence form (probed live 2026-10-28 — empirical)
- Blockers of N: repos/{repo}/issues/{N}/dependencies/blocked_by?per_page=100&page={p}
  via the existing _fetch_pages with a small constant page bound.
- Blocker's events: repos/{repo}/issues/{B}/events?per_page=100&page={p} via
  _fetch_pages(..., EVENTS_PAGE_BOUND, budget). Use the LAST closed event.
- Observed: when a PR with a closing keyword merges, the closed event has commit_id: null,
  and GitHub emits a referenced event with the SAME created_at whose commit_id is the merge
  commit SHA (#2147: closed 2026-10-25T23:43:49Z, referenced 7ada70a3ee… = PR #2181's
  merge_commit_sha). A direct-commit close may set commit_id on the closed event itself.
  Merge attribution = the last closed event's commit_id if non-null, else a referenced event
  with non-null commit_id and identical created_at; AND that commit is an ancestor of the
  default branch.
- Default-branch ancestry: check locally with the existing _git helper against the same
  origin/main ref _started_stages uses. Free. Any git failure / unknown object => not
  attributable via merge (fail-safe). Validate the sha is 40 hex chars first.
- CODEOWNER alternative: the last closed event's actor.login is in the codeowners-humans set
  and is not a bot (reuse is_bot_reviewer and the codeowners/bots sets _walk already
  receives). Write a small pure predicate (no network), unit-tested on its own.

## Where it fits
D2b stays free for every record it can already decide. A record that today gets
blocker-closed-unverified (blocked_by == 0, total_blocked_by > 0, sub-issues readable and 0)
is carried forward as "needs closed-blocker check" (ranked with the kept set). The paid
check runs in the walk when that record is reached, BEFORE the trust/authorization test (an
unsatisfied record is excluded blocker-closed-unverified and reported as today, never counted
as gated). blocked-by-open-issue and untracked-parent stay free and first. Keep the excluded
report, WARN line, exit codes (0/2/3) and complete= semantics consistent. A FAILED fetch is
treated like query_failed_issues. Emit `blocker-satisfied issue=#N blocker=#B
by=merge|codeowner` when satisfied.

Update the module docstring paragraph on native dependencies, ADR-1644 :306 and the slice
table (:901-902) to record T3.3-thin (#2173) as pulled into v0.7.0, standing alone without
T3.2. Keep doc edits minimal.

## Tests (required)
merge (referenced form) → selectable; commit_id on closed event → selectable; CODEOWNER
closer → selectable; not_planned → excluded; unverified actor → excluded; non-ancestor commit
→ excluded unless CODEOWNER; one open + one closed blocker → blocked-by-open-issue with zero
added requests; budget exhausted during the check → DEGRADED; two closed blockers, one
unsatisfied → excluded; existing zero-request test still holds. All existing selector tests
stay green.
```

## Refinement iterations

Round 1 (code-reviewer MUST_FIX): cross-repo blocker guard. `blocked_by` can return issues from other
repositories; a blocker is now UNSATISFIED unless its `repository_url` ends in exactly `/repos/{repo}`
(case-insensitive, host-agnostic; missing or malformed is unsatisfied), checked before any events fetch,
so a foreign blocker is never judged on this repository's events. Docstring and ADR note the rule.

Round 2 (reliability/ops SHOULD_FIX): ancestry is tri-state (`_is_default_branch_ancestor` returns True / False /
None; a git failure is UNKNOWN, not "not an ancestor"). UNKNOWN with no CODEOWNER satisfaction makes the blocker
FAILED (unevaluated:query-failed), never UNSATISFIED. A per-walk FAILED marker stops a shared blocker's events
fetch being repeated per dependent. The query-failed WARN for a closed-blocker-check failure carries
` check=closed-blocker`; the D5 events-authorization line is unchanged.

Round 4 (second-review CWE-863 + malformed records): the same-second `referenced`-event fallback is
deleted (it was forgeable: any commit that mentions `#N` and later reaches main, plus a same-second close,
counted as a merge; and it never fired on real merges, where the `closed` event has no commit). Merge
attribution is now GitHub's recorded cause. Order, cheapest first: (1) the last `closed` event's non-null
`commit_id` that is an ancestor of origin/main; (2) a human, non-bot CODEOWNER closer; (3) otherwise ONE
GraphQL read of `ClosedEvent.closer` (`_run_graphql`, a literal query, variables as separate `gh`
arguments, counted against the request budget, injected into the pure predicate as a callable): a PR that
is merged, based on the default branch (named from the same constant as `_DEFAULT_BRANCH_REF`), in THIS
repo, whose merge commit is an ancestor of origin/main; or a Commit closer that is such an ancestor. The
node's `createdAt` must equal the REST closed event's `created_at`, else UNKNOWN. A closer of null, any
failed field, or a non-ancestor is UNSATISFIED; any transport/shape failure or ancestry UNKNOWN is FAILED
(unevaluated); the budget stop at the lookup is REFUSED. No actor check on path 3: the closer is the cause,
so a bot merger is legitimate. Probed live (#1666, #2194, bot-merged #1532, manual #2196, commit-closed
#1236). Separately, a `blocked_by` record that is not a dict, or whose `number` is not a positive non-bool
int, makes the whole record FAILED before any free rejection or events fetch (previously non-dict records
were silently dropped, which could yield SATISFIED on a list that was not fully readable).
