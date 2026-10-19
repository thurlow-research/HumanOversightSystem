# TECHNICAL DESIGN — #1796 slice S1: bare `needs-human` removal detector (L1 `bare_handback.py` + L2 `bare_handback_cli.py`)

**Status:** ARCHITECT APPROVED WITH CHANGES (round 1, 2026-10-19). Required changes RC-1 to RC-6 are applied in place and tagged `[RC-n]`. The OQ rulings are in §13, and the review is in §14. S1 may go to `coder`. ESC-1 (from OQ-1) does not block S1. It must be answered before the S2 PR merges.
**Change class:** **additive.** S1 adds two new, inert modules with no caller, one new `github.py` helper, and one backward-compatible keyword on an existing helper. Nothing that runs today changes behaviour until S2 wires `finalize` into `overseer.md`.
**Date:** 2026-10-19
**Author:** technical-design (autonomous worker cycle; no human present)
**Issue:** #1796 · **Milestone:** v0.7.0 · **Slice:** S1 only. S2 (`bootstrap/bare_handback.sh` and the `overseer.md` label sites) is out of scope. §8 describes only the interface S1 must serve for it.
**Binding inputs (on `main` at `76b367795`):**
- `docs/v0.7.0/REQUIREMENTS-1796-bare-handback-detect.md` (REQ-1 to REQ-10, with AM-1 to AM-8 applied)
- `docs/v0.7.0/ADR-1796-bare-handback-detect.md` (AD-1 to AD-8, AF-1 to AF-6, residuals R-1 to R-6; architect APPROVED WITH CHANGES; ESC-1 to ESC-3 take the defaults)
- Human ruling, 2026-10-02: option (a). Detect a bare removal and report it once, guess nothing. Purely additive.

**Not open to any answer in this document:** REQ-2 (fail closed to `UNDETERMINED`), REQ-4 (never re-apply over a human removal, never infer intent), and REQ-5 (exactly one report, trusted markers only).

**Tree read at:** `76b367795`. I re-read every `file:line` cited below at that commit.

---

## 0. Reuse search (CLAUDE.md item 1)

I searched `scripts/` recursively, `bootstrap/`, `bin/` and `scripts/automation/lib/*.py` for each capability S1 needs.

| Need | Found | Decision |
|---|---|---|
| GitHub transport (retry, backoff, rate limit, 30 s timeout) | `github._run_gh` (`scripts/automation/lib/github.py:38-156`). A 404 returns `None` (`:136-137`). An empty body also returns `None` (`:148-149`). | **Reused** as the only transport. No new HTTP client. |
| PR read | `github.get_pull` (`:336-345`) | **Reused.** |
| Head committer date | `github.get_commit` (`:405-415`). `merge_authority_cli._cmd_hold_directive` reads `commit.committer.date` from it (`scripts/automation/merge_authority_cli.py:516-523`). | **Reused**, with the same field path. |
| Issue-events reader | `probe._fetch_events_paginated` (`scripts/automation/lib/probe.py:265-300`) and `select_work_candidates._fetch_pages` (`scripts/framework/select_work_candidates.py:113,264`). Both are private and both stop at 10 pages. `github.py` has no public events reader. | **Pattern reused, code not.** ADR AD-6 requires a 100-page tripwire and a strict "page bound is not a determination" rule. FU-1 (ADR §8) covers consolidating them later. |
| Comment reader | `github.list_issue_comments` (`:215-238`) | **Rejected** (ADR AF-4). It treats a `None` page (404) as the end of the list (`:232-233`) and has no page bound (`:228`). |
| Comment post | `github.post_comment(verify=True)` (`:418-461`) | **Reused.** It gains one backward-compatible `retries` keyword (§4.2). |
| Single-comment read-back | Only inside `post_comment` (`:451`). It is not exposed, and `post_comment` returns the POST result, not the read-back. | New L1 fetch function `read_comment` over `_run_gh` (§3.10). |
| Label add | None in `github.py`. Inline `_run_gh` POSTs exist at `merge_authority.py:782,1312`. `bootstrap/edit_issue.sh:201-204` uses the same endpoint. | New `github.add_issue_labels` (§4.1), as AD-3 requires. |
| Bot classification | `require_human_approval.is_bot_reviewer` (`scripts/framework/require_human_approval.py:140-159`) and `requester_trust.load_bot_accounts` (`scripts/framework/requester_trust.py:301-322`). `probe.py:40` is the precedent for importing them from `scripts/automation/lib`. | **Reused.** |
| Trusted-marker rule | `bootstrap/escalate_to_human.sh:21-25,223-227`: author login matches case-insensitively, `user.type == "Bot"`, `updated_at == created_at`, and a whole line equals the marker. | **Rule reused** in Python (§3.9). |
| Config (overseer login, worker login, repo slug) | `merge_config.resolve_config` (`scripts/automation/lib/merge_config.py:64-114`) and `resolve_repo_slug` (`:117`) | **Reused** by L2 only. |
| L2 envelope, argparse, exit-code discipline | `merge_authority_cli.py:108-163,746-791`. Identity and scope guards are at `pr_review_cli.py:310-395,609-618`. | **Shape copied.** |
| Audit writer | `audit_log.write_event` (`scripts/oversight/lib/audit_log.py:126-157`). It is loaded by file path by `merge_authority._load_audit_log` (`merge_authority.py:1159-1174`), because `scripts/oversight/` has no `__init__.py`. | **Reused**, with the same by-path loader. |

**Found nothing** that classifies a label-history episode, renders a handback report, or deduplicates an undetermined outcome. Those are new.

---

## 1. Files in S1

| # | File | Kind |
|---|---|---|
| 1 | `scripts/automation/lib/bare_handback.py` | new: L1 (pure core plus strict fetch) |
| 2 | `scripts/automation/bare_handback_cli.py` | new: L2 |
| 3 | `scripts/automation/lib/github.py` | edit: add `add_issue_labels`; add a `retries` keyword to `post_comment` |
| 4 | `tests/automation/test_bare_handback_classify.py` | new |
| 5 | `tests/automation/test_bare_handback_fetch.py` | new |
| 6 | `tests/automation/test_bare_handback_report.py` | new |
| 7 | `tests/automation/test_bare_handback_cli.py` | new |
| 8 | `tests/automation/test_github.py` | extend |
| 9 | `tests/automation/fixtures/bare_handback/pr1792.json` | new |
| 10 | `research/findings/api-field-shape-verification.md` | extend: live probe of the `unlabeled` event shape (ADR §4 S1 row) |
| 11 | `SCRIPTS-INDEX.md` | regenerate with `scripts/framework/regen_all.sh` |

That is 11 files, within the 15-file cap. No protected surface is touched: `scripts/automation/**` is not listed in `scripts/framework/protected_surfaces.txt`. The slice does **not** touch `merge_authority.py`, `bin/hos-cron`, `.claude/agents/**`, `bootstrap/**` or `.github/workflows/**`.

---

## 2. Organizing rules (from the ADR, restated as checks the coder can verify)

1. **Purity boundary.** `classify`, `classify_population`, `parse_pr`, `match_reason`, `render_report`, `marker_line` and `find_trusted_marker` read no clock, no environment, no file and no network. `fetch_all` and `read_comment` are the only L1 functions that do I/O. L1 never writes anything.
2. **One seam for GitHub.** Every L1 and L2 network call reaches GitHub through `github._run_gh`, always called as the attribute `github._run_gh(...)`, never through `from ... import _run_gh`. Tests fake GitHub by monkeypatching that one attribute. `get_pull`, `get_commit`, `post_comment` and `add_issue_labels` already route through it.
3. **No determination from incomplete evidence.** `classify` accepts an events input only as a `FetchResult`, and only `status == COMPLETE` can lead to `NOT_BARE (never-labelled …)` or `BARE_REMOVAL`.
4. **No label write except on `NOT_BARE`.** In L2, the call to `github.add_issue_labels` sits on exactly one code path, the `NOT_BARE` branch of `finalize`. A test enforces this (T-CLI-LABELPLAN).
5. **L1 does not import `merge_authority`.** An import-graph test pins this (T-CLI-IMPORTS). The reason-table drift test reads `merge_authority.py` as **source text through `ast`**. It does not import the module.

---

## 3. L1: `scripts/automation/lib/bare_handback.py`

### 3.1 Imports (exhaustive)

- Standard library: `re`, `time`, `enum`, `dataclasses`, `datetime`, `typing`, `collections.abc`.
- `from scripts.automation.lib import github`
- `from scripts.framework.require_human_approval import is_bot_reviewer`

Nothing else. `load_bot_accounts` is called by L2 and passed in as data. The ADR's AD-1 lists it among L1's permitted imports. Not importing it narrows that list, and the allowed set in T-CLI-IMPORTS still includes it, so either choice passes.

### 3.2 Module constants

```
NEEDS_HUMAN = "needs-human"
NEEDS_AI = "needs-ai"
ROUTING_LABELS = frozenset({NEEDS_HUMAN, NEEDS_AI})   # compared after .casefold()
PAGE_SIZE = 100
PAGE_TRIPWIRE = 100                  # pages; 10,000 records (AD-6, #1923). Not a flag.
FETCH_WALL_CLOCK_BUDGET_SECONDS = 180  # per fetch_all call (§3.10; OQ-5)
MARKER_VERSION = 1
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
COMMIT_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]+(\[bot\])?$")          # AD-4 sanitization grammar
MARKER_RE = re.compile(
    r"^<!-- hos-bare-handback v=1 pr=(?P<pr>[1-9][0-9]{0,9}) "
    r"removed_at=(?P<removed_at>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z) "
    r"head=(?P<head>[0-9a-f]{40}) -->$"
)
```

### 3.3 Types

All dataclasses are `frozen=True`. Sequences are `tuple`, never `list`, so the inputs are hashable and cannot be mutated.

```
class Determination(str, Enum): NOT_BARE, BARE_REMOVAL, UNDETERMINED   # value == name
class Cause(str, Enum): (closed set, §3.5; value is the kebab-case string)
class FetchStatus(str, Enum): COMPLETE, FAILED, NON_LIST, TRIPWIRE

@dataclass(frozen=True)
class FetchResult:
    status: FetchStatus
    items: tuple[Mapping[str, Any], ...]   # empty unless COMPLETE
    pages: int                             # number of pages requested
    detail: str | None                     # fixed-template text only, e.g. "page=2" (never GitHub text)

@dataclass(frozen=True)
class PRSnapshot:
    number: int
    state: str              # "open" | "closed"
    draft: bool
    author_login: str
    labels: tuple[str, ...] # casefolded, sorted, de-duplicated
    head_sha: str           # 40 lowercase hex

@dataclass(frozen=True)
class Evidence:
    pr: PRSnapshot
    head_committed_at: str | None     # commit.committer.date verbatim, or None if unreadable
    events: FetchResult
    worker_login: str                 # BOT_WORKER_USERNAME
    bot_accounts: frozenset[str]      # from load_bot_accounts(); compared case-insensitively

@dataclass(frozen=True)
class Classification:
    determination: Determination
    cause: Cause
    pr_number: int
    head_sha: str | None
    removed_at: str | None        # set iff the removal event was located (steps 6-9)
    removed_by: str | None        # actor.login of that event
    removed_by_type: str | None   # actor.type verbatim ("" if absent)
    via_app: str | None           # performed_via_github_app.slug, or None (recorded only; §3.4 step 6)

@dataclass(frozen=True)
class ReasonRow:
    row_id: str
    source: str                   # "merge_authority.py:<line>"
    decision: str                 # "HUMAN_REQUIRED" | "PROPOSE_ONLY" | "AUTO_MERGE"
    pattern: re.Pattern[str]      # matched with fullmatch()
    category: str                 # "human-approval-satisfiable" | "other"
```

### 3.4 `parse_pr(obj: object) -> PRSnapshot | None` (pure)

This returns `None`, which L2 maps to `UNDETERMINED (pr-unreadable)`, unless all of the following hold:
- `obj` is a dict;
- `number` is a positive `int`;
- `state` is `"open"` or `"closed"`;
- `draft` is a `bool`;
- `user.login` is a non-empty `str`;
- `labels` is a list of dicts, each with a non-empty `str` `name`;
- `head.sha` matches `SHA_RE`.

Labels are casefolded, de-duplicated and sorted. A merged PR has `state == "closed"`, so it needs no separate field.

### 3.4a `classify_population(pr: PRSnapshot, worker_login: str) -> Classification | None` (pure)

This is ADR AD-2 steps 1 and 2. L2 calls it **before** any events request (REQ-2).
1. If `pr.state != "open"`, or `pr.draft`, or `pr.author_login.casefold() != worker_login.casefold()`, return `NOT_BARE`, cause `out-of-population`.
2. If `ROUTING_LABELS & set(pr.labels)` is non-empty, return `NOT_BARE`, cause `labelled`.
3. Otherwise return `None`, meaning "events needed".

The returned `Classification` has `head_sha = pr.head_sha`, and every removal field is `None`.

### 3.4b `classify(ev: Evidence) -> Classification` (pure, total)

**Evaluation order.** The first step that settles the answer wins. The step numbers match ADR AD-2.

1-2. `r = classify_population(ev.pr, ev.worker_login)`. If `r` is not `None`, return `r`.

3. **Events completeness.**
   - `ev.events.status == FAILED` → `UNDETERMINED (events-failed)`.
   - `NON_LIST` → `UNDETERMINED (events-non-list)`.
   - `TRIPWIRE` → `UNDETERMINED (events-tripwire)`.

3a. **Shape check** (TD refinement of step 3; it is part of REQ-2's "no determination from unusable evidence").
   - Any item that is not a dict → `UNDETERMINED (events-malformed)`.
   - A **relevant** event is a dict whose `event` is `"labeled"` or `"unlabeled"` and whose `label.name`, casefolded, is in `ROUTING_LABELS`. Every relevant event must have an `int` `id` and a `created_at` matching `TS_RE`. If any does not → `UNDETERMINED (events-malformed)`.
   - **[RC-1]** A dict whose `event` is `"labeled"` or `"unlabeled"` but whose `label` is not a dict, or whose `label.name` is not a non-empty `str` → `UNDETERMINED (events-malformed)`. Such an event may be a `needs-human` event that cannot be seen. Ignoring it as "irrelevant" could hide the true last event, and that fails open.
   - Irrelevant dict events are ignored, whatever their fields. An event is irrelevant when its `event` is not `"labeled"`/`"unlabeled"`, or when it is one of those and its well-formed `label.name` is not a routing label.

   Sort the relevant events ascending by `(created_at, id)`. `TS_RE` is fixed-width UTC, so lexical order equals time order. The classifier never trusts page order (AD-2).

4. Let `H` be the relevant events whose label is `needs-human`. If `H` is empty → `NOT_BARE (never-labelled)`.

5. Let `last = H[-1]`. If `last.event == "labeled"` → `UNDETERMINED (labels-events-disagree)`. Step 2 has already established that the label is absent.

6. `last.event` is `"unlabeled"`, so it is the candidate removal.
   - Let `actor = last.get("actor")`. If `actor` is not a dict, or `actor.login` is not a non-empty `str` → `UNDETERMINED (actor-missing)`.
   - `login = actor["login"]` and `utype = actor.get("type")`. If `utype` is not a `str`, use `""`.
   - If `is_bot_reviewer(login, utype, set(ev.bot_accounts))` is true → `NOT_BARE (bot-removal)`.
   - If `LOGIN_RE.fullmatch(login)` is `None` → `UNDETERMINED (actor-malformed)`. Classifying the grammar here, rather than at render time (AD-4), means `check` and the withhold path see the same answer. The outcome still adds no label either way.
   - `performed_via_github_app` does **not** enter the bot test. The actor's identity alone decides. If that field is non-null, its `slug` (a `str` or `None`) is copied into `via_app` as evidence. Why: treating an app-mediated human action as a bot removal would re-apply `needs-human` over a possible human act, which is the REQ-4 failure direction. Treating it as human costs at most one report (OQ-6).
   - Record `removed_at = last["created_at"]`, `removed_by = login`, `removed_by_type = utype`.

7. If any relevant event `e` with `e.event == "labeled"` sorts **after** `last` → `NOT_BARE (relabelled)`. Because `last` is the newest `needs-human` event, in practice `e` is a `needs-ai` add. This is ADR AD-2 step 7 as written. OQ-1 covers the lag case.

8. **Head clock (AD-7).**
   - If `ev.head_committed_at` is `None` or does not match `COMMIT_TS_RE` → `UNDETERMINED (head-unreadable)`.
   - Parse both timestamps to aware UTC datetimes (`datetime.fromisoformat(s.replace("Z", "+00:00"))`).
   - If `head_committed_at > removed_at` (strictly greater) → `NOT_BARE (new-head)`. Equal does **not** end the episode.

9. Otherwise → `BARE_REMOVAL (bare-removal)`, with `removed_at`, `removed_by`, `removed_by_type`, `via_app` and `head_sha` set.

On every return from steps 6 to 9, the removal fields carry what was located, as evidence. `determination` and `cause` alone are the answer.

### 3.5 Closed `Cause` enum (AD-3 item 2)

| Determination | Cause values |
|---|---|
| `NOT_BARE` | `out-of-population`, `labelled`, `never-labelled`, `bot-removal`, `relabelled`, `new-head` |
| `UNDETERMINED` | `pr-unreadable`, `events-failed`, `events-non-list`, `events-tripwire`, `events-malformed`, `labels-events-disagree`, `actor-missing`, `actor-malformed`, `head-unreadable` |
| `BARE_REMOVAL` | `bare-removal` |

`pr-unreadable` is produced by L2 when `get_pull` raises or `parse_pr` returns `None`, because `classify` cannot run without a `PRSnapshot`. L1 exports a constructor helper, `undetermined_pr_unreadable(pr_number) -> Classification`, so that L1 alone owns the enum.

A separate, closed **report-stage** enum is owned by L2 (§5.6): `not-human-required`, `reason-unrecognized`, `comments-failed`. Report-stage causes never change `determination`.

### 3.6 Reason table (`REASON_TABLE: tuple[ReasonRow, ...]`, AD-4)

There is one row per `reason=` expression in `decide_merge_authority` (`merge_authority.py:498-743`). The ceiling expression has two rows, split by category. Every pattern is matched with `fullmatch` against the single reason line. `—` is U+2014, as in the source. `LOGIN` means `[A-Za-z0-9-]{1,39}`, and `TIER` means `(?:SAFE|LOW|MEDIUM|HIGH|CRITICAL)`. Inside the table cells, `\|` is Markdown escaping only. The compiled regex uses a plain `|`.

| row_id | source | decision | pattern (fullmatch) | category | Why that category |
|---|---|---|---|---|---|
| `label-guard-756` | `:566` | HUMAN_REQUIRED | `PR carries blocking label\(s\) \[(?:hos-halt\|needs-human)(?:, (?:hos-halt\|needs-human))?\] — human authorization required \(#756\)` | other | The #756 guard fires before any approval lookup (`:560-567`). On a bare PR only `hos-halt` can appear here. |
| `prior-decision-761` | `:576-579` | HUMAN_REQUIRED | `Prior overseer decision was HUMAN_REQUIRED; no qualifying human approval found on head SHA — escalating to LOGIN \(#761\)` | human-approval-satisfiable | `:573` clears it when `_find_human_approval(reviews, human_reviewer, head_sha)` succeeds. |
| `requested-reviewer-761` | `:590-593` | HUMAN_REQUIRED | `PR has an outstanding review request from LOGIN — human review is pending \(#761\)` | other | `:586-595` reads only `requested_reviewers`. Neither the code nor step 6 treats an approval as clearing it (OQ-4). |
| `hold-directive-902` | `:608-611` | HUMAN_REQUIRED | `Unaddressed human hold/bounce-back directive from LOGIN on the current head — withholding approval; human authorization required \(#902\)` | other | `:605-613` does not consult reviews. |
| `release-ng3b` | `:619` | HUMAN_REQUIRED | `Release-related PR — autonomous releases are prohibited \(NG3b\)` | other | Autonomous release is prohibited. An approval does not clear it. |
| `worker-class` | `:628` | PROPOSE_ONLY | `agent_class=worker — worker opens PRs only, never merges` | other | This is never a HUMAN_REQUIRED decision, so it never reports (§5.5). |
| `oversight-verdict` | `:637` | HUMAN_REQUIRED | `Oversight verdict is [A-Z_]{1,32} — escalating` | other | `:633-639` does not consult reviews. |
| `tier-ceiling-critical` | `:645` | HUMAN_REQUIRED | `Tier CRITICAL exceeds overseer ceiling TIER` | human-approval-satisfiable | `overseer.md:467` (3): a CODEOWNER approval on the current head gives "merge immediately". |
| `tier-ceiling-other` | `:645` | HUMAN_REQUIRED | `Tier (?:SAFE\|LOW\|MEDIUM\|HIGH) exceeds overseer ceiling TIER` | other | Step 6 HUMAN_REQUIRED (other) (`overseer.md:468`) has no merge-on-approval step. |
| `security-relevant` | `:672` | HUMAN_REQUIRED | `Security-relevant change — human approval required` | human-approval-satisfiable | `:658-668` clears it on approval. |
| `protected-surface` | `:693` | HUMAN_REQUIRED | `PR touches a protected surface — human approval required` | human-approval-satisfiable | `:679-689` clears it on approval. |
| `authorship-backstop` | `:701` | HUMAN_REQUIRED | `PR author \(LOGIN(?:\[bot\])?\) == overseer — self-approval blocked` | other | `:698-703` does not consult reviews. |
| `gate-not-detected` | `:710` | PROPOSE_ONLY | `Server-side gate not detected \([^\n\x60]{1,500}\)` | other | It is never rendered (PROPOSE_ONLY). `\x60` is a backtick. |
| `universal-approval-757` | `:726-729` | HUMAN_REQUIRED | `Merge requires verified human approval on current head SHA — none found \(#757\)` | human-approval-satisfiable | `:717-722` clears it on approval. |
| `auto-merge` | `:733-742` | AUTO_MERGE | `Auto-merge approved: tier=TIER, ceiling=TIER, verdict=PROCEED, gate=detected; merged by overseer under human authorization \(approval by LOGIN(?:\[bot\])? on (?:[0-9a-f]{7,40}\|unknown)\)` | other | It never reaches `finalize` with HUMAN_REQUIRED. It exists so that the drift test is total. |

No captured group in any HUMAN_REQUIRED row can contain a backtick, a newline, `<`, `>` or `@`. A reason that matches such a row is therefore safe inside a single-backtick code span (§3.8). T-REP-SAFE pins this.

### 3.7 `match_reason(reason: str) -> ReasonRow | None` (pure)

- Return `None` if `reason` is empty, contains `"\n"` or `"\r"`, or is longer than 1000 characters.
- Otherwise collect the rows whose `pattern.fullmatch(reason)` succeeds.
- Return the row if exactly one matches. Return `None` if none or more than one match. More than one match is a table defect, and the drift test prevents it.

### 3.8 `render_report(pr_number: int, c: Classification, reason: str, row: ReasonRow) -> str` (pure)

**Preconditions.** If any of these fails, raise `ValueError`. L2 never violates them, and the tests do on purpose.
- `c.determination == BARE_REMOVAL`;
- `match_reason(reason) is row`;
- `row.decision == "HUMAN_REQUIRED"`;
- `LOGIN_RE.fullmatch(c.removed_by)` succeeds;
- `c.removed_at` matches `TS_RE`;
- `c.head_sha` matches `SHA_RE`.

**Template, byte for byte.** Lines are joined with `"\n"`. There is no trailing newline after the marker. `{…}` marks a substitution, and nothing else in the template varies. The line marked `[S]` is emitted **only** when `row.category == "human-approval-satisfiable"`. Otherwise it is omitted along with its line break.

```
**Decision: HUMAN_REQUIRED**

**This PR is unrouted.** A human removed `needs-human` and no routing label replaced it, so neither the worker nor the overseer will act on this PR until a human does.

- Removed by: @{removed_by} at {removed_at}
- Current head: `{head_sha}`
- Outstanding blocker (quoted verbatim from the merge-authority decision): `{reason}`

The pipeline did not guess your intent and did not re-apply the label.

To route this PR, do one of the following:
- Apply `needs-ai` from your own account to hand it to the worker.
- Re-apply `needs-human` to park it as human-pending.
[S] - Approve the current head (`{head_sha}`) from your own account with a GitHub review.
- Close the PR.

{marker_line(pr_number, removed_at, head_sha)}
```

(`[S] ` is a notation prefix only. It is not emitted.)

- The first line is the canonical `**Decision: HUMAN_REQUIRED**` header (AM-4, AF-3).
- The body never contains `/approve`, `/decline` or `/handoff`. T-REP-NOCMD checks this with the regex `/(approve|decline|handoff)\b`, case-insensitive. The template deliberately contains no `/` immediately before those words. `hold/bounce-back` inside a quoted reason does not match.
- `@{removed_by}` mentions the human who removed the label. Notifying them is the purpose of the report. The login is grammar-constrained (§3.4b step 6), and a bot login never reaches this point.

`marker_line(pr: int, removed_at: str, head_sha: str) -> str` returns `f"<!-- hos-bare-handback v=1 pr={pr} removed_at={removed_at} head={head_sha} -->"`, and `MARKER_RE` must fullmatch the result. `removed_at` is the event's `created_at` **verbatim**. It is already canonical through `TS_RE`, so no re-formatting happens and none can drift.

### 3.9 `find_trusted_marker(comments, *, pr_number: int, removed_at: str, overseer_login: str) -> Mapping | None` (pure)

Scan `comments` in the order given and return the first comment `c` that satisfies **all** of these (AD-4; the same rule as `escalate_to_human.sh:223-227`):
1. `c` is a dict, and `c.user` is a dict;
2. `str(c.user.login).casefold() == overseer_login.casefold()`;
3. `c.user.type == "Bot"` (exact);
4. `c.created_at` and `c.updated_at` are both `str` and are equal;
5. some line `L` of `str(c.body)`, from **`str(c.body).split("\n")`** with no other stripping, satisfies `MARKER_RE.fullmatch(L)`, with `int(m["pr"]) == pr_number` and `m["removed_at"] == removed_at`.

`head` is ignored (informational, AM-4). Return `None` if no comment qualifies.

**[RC-2]** Lines are split on `"\n"` only, never with `splitlines()`. That is exact parity with `escalate_to_human.sh:227` (jq `split("\n")`). `splitlines()` also breaks on `\r`, `\x0b`, `\x0c`, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029. That would make the "whole line" test looser than the rule it claims to copy: `"x\r<!-- hos-bare-handback … -->"` would count as a whole-line marker. The §5.5 C7 confirm uses the same split. T-REP adds `inline-after-cr` to `test_marker_untrusted`.

### 3.10 Strict fetch (I/O; AD-6)

`fetch_all(endpoint: str) -> FetchResult`. `endpoint` is a path such as `/repos/{o}/{r}/issues/{n}/events`, with no query string.

```
deadline = time.monotonic() + FETCH_WALL_CLOCK_BUDGET_SECONDS
items = []
for k in 1 .. PAGE_TRIPWIRE:
    if k > 1 and time.monotonic() > deadline: return FAILED(detail=f"wall-clock-budget page={k}")
    try: batch = github._run_gh([f"{endpoint}?per_page=100&page={k}"])
    except github.GitHubError: return FAILED(detail=f"page={k}")   # RateLimitError is a subclass
    if batch is None: return FAILED(detail=f"page={k} none")       # 404 or empty body
    if not isinstance(batch, list): return NON_LIST(detail=f"page={k}")
    items.extend(batch)
    if len(batch) < PAGE_SIZE: return COMPLETE(items=tuple(items), pages=k)
return TRIPWIRE(pages=PAGE_TRIPWIRE)
```

- A page of exactly 100 followed by an empty `[]` page is COMPLETE after 2 pages. `json.loads("[]")` is a list, not `None`.
- `pages` is the number of pages requested. `items` is empty unless the status is COMPLETE.
- `detail` holds only the fixed templates shown. It never contains exception text or response text.
- Worst-case wall clock: `_run_gh` allows up to 4 attempts of 30 s each plus backoff per page, so one page can take about 127 s. The budget is checked between pages, so one fetch is bounded by about 180 s plus one page (OQ-5).

`read_comment(owner: str, repo: str, comment_id: int) -> Mapping | None` calls `github._run_gh([f"/repos/{owner}/{repo}/issues/comments/{comment_id}"])`. It returns the dict, or `None` on `None`, a non-dict response, or `GitHubError`.

---

## 4. `scripts/automation/lib/github.py` changes

### 4.1 New: `add_issue_labels(owner, repo, issue_number, labels) -> list[dict]`

- **Validation.** `labels` must be a non-empty `list[str]`. Each element must be non-empty and contain no `,`, `"\n"` or `"\r"`. Otherwise raise `ValueError`.
- **Call.** `_run_gh([f"/repos/{owner}/{repo}/issues/{issue_number}/labels", "--method", "POST"], retries=0, stdin_json={"labels": labels})`. The body goes through stdin JSON, never `--field` (#752; compare `merge_authority.py:782-789`, which uses `--field`). `retries=0` per AD-3.
- **Result.** `None` raises `GitHubError("add_issue_labels: no response")`. A non-list raises `GitHubError("add_issue_labels: unexpected payload")`. Otherwise return the list. It is the issue's full resulting label set.
- **Verification is the caller's job.** L2 checks that the requested label, casefolded, is among the returned `name`s (§5.5). The helper only returns the set.
- Docstring: cite #1796 AD-3, and say why `retries=0` (the ADR binding) even though the endpoint is idempotent.

### 4.2 Edit: `post_comment(..., *, verify=True, retries=3)`

- Add a keyword-only `retries: int = 3` and pass it to the POST's `_run_gh` call only. The read-back GET keeps its default.
- The default is unchanged, so every existing caller is unaffected.
- `bare_handback_cli` passes `retries=0`. This is the `submit_pull_review` MUST_FIX D precedent (`github.py:486-498`): a timed-out or connection-reset POST may already have landed, and `_run_gh`'s retry loop would then create a duplicate report. That duplicate would break REQ-5's "exactly one". With `retries=0`, an ambiguous failure exits 1 (§5.5). The next cycle's trusted-marker read then finds the comment if it landed, and posts once if it did not. See OQ-2: the ADR names `post_comment(verify=True)` without the keyword.

---

## 5. L2: `scripts/automation/bare_handback_cli.py`

### 5.1 Module shape

This copies `merge_authority_cli.py`:
- the `sys.path` bootstrap (`:33-38`);
- `SCHEMA_VERSION = 1`;
- an `_EnvelopeArgumentParser` whose `error()` prints one envelope and raises `_UsageExit(2)`;
- `add_help=False` everywhere;
- `main(argv=None, *, repo_root=None) -> int`, which never calls `sys.exit`. `repo_root` is a test-only keyword.

Importing the module does no I/O.

Imports:
- L1 `bare_handback`, `github`, `merge_config`;
- `scripts.framework.requester_trust.load_bot_accounts`;
- the audit writer, loaded by path exactly as in `merge_authority._load_audit_log` (`merge_authority.py:1159-1174`).

The audit writer is loaded lazily, inside the function that writes an event, so that importing the module stays I/O-free.

### 5.2 argv

```
bare_handback_cli.py check    --pr <N> --app <worker|overseer|human> [--repo <owner/repo>]
bare_handback_cli.py finalize --pr <N> --app <worker|overseer|human> --label <needs-human|needs-ai>
                              --disposition <HUMAN_REQUIRED|PROPOSE_ONLY|MERGE_FAILED>
                              --reason-file <path> [--repo <owner/repo>]
```

- `--pr` uses `^[0-9]+$` and must be positive. `--repo` uses `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`. Both are copied from `merge_authority_cli.py:71-102`.
- `--app` accepts all three roles on both subcommands, so that the refusal on `finalize` (exit 3) is distinguishable from a usage error (exit 2).
- No other flags exist: no `--force`, no `--head-sha`, no `--dry-run`, no `--repo-root`.

**`--reason-file` contract** (checked before any network call; a violation is exit 2). **[RC-3]** The contract depends on `--disposition`:
- **`HUMAN_REQUIRED`:**
  - the file exists and is readable;
  - it decodes as UTF-8 (strict);
  - it is at most 1000 bytes;
  - after removing **one** optional trailing `"\n"`, it contains no `"\n"` or `"\r"` and is non-empty.

  The resulting string is `reason`. It is passed through unmodified, with no `.strip()`. Every HUMAN_REQUIRED `reason=` in `decide_merge_authority` is a single line by construction (§3.6), so a violation means the overseer misused the wrapper. Exit 2 is the loud, correct outcome.
- **`PROPOSE_ONLY` and `MERGE_FAILED`:** the file must exist and be a regular file. Its **content is not read, not validated, not stored and not logged**, and `reason` is `None`. These reasons are free text by construction. `Server-side gate not detected ({gate.reason})` embeds `Protection API read failed: {exc}` (`merge_authority.py:252`), and a merge-failure line embeds `gh` error text. Either can be multi-line or longer than 1000 bytes. No code path in S1 uses a non-HUMAN_REQUIRED reason, because §5.5 C1 exits before `match_reason`. Validating it would turn a routine `NOT_BARE` label add into an exit-2 halt over a field that nothing reads.

Why: under the single contract in the round-1 draft, a PROPOSE_ONLY PR whose gate-read exception text contained a newline could never be labelled `needs-ai`. That is a regression against today on the `NOT_BARE` path, which REQ-4 says must be unchanged. Tests: `test_reason_file_contract_exit2[...]` runs with `--disposition HUMAN_REQUIRED`. New `test_reason_file_free_text_ignored_for_non_human_required[propose_only-multiline, merge_failed-5000-bytes, non-utf8]` asserts that a `NOT_BARE` PR gets the label, exit 0, and that the content does not appear in stdout, stderr or any event. New `test_reason_file_missing_exit2_any_disposition`.

### 5.3 Preamble order (both subcommands; the first failure wins)

1. Parse argv. A failure → exit 2.
2. Read `--reason-file` (`finalize` only). A violation → exit 2.
3. `merge_config.resolve_config(repo_root)`. `ConfigError` → exit 1.
4. **`finalize` only:** `--app != "overseer"` → exit 3, `refusal_reason: "finalize_requires_overseer_app"`.
5. Resolve the repo with `merge_config.resolve_repo_slug(repo_root, explicit=args.repo)`. `ConfigError` → exit 1. **`finalize` only:** if `--repo` was given and differs (casefolded) from the `origin` slug → exit 3, `refusal_reason: "repo_scope_mismatch"`. This copies `pr_review_cli.py:326-347`, because `finalize` writes.
6. **`finalize` only:** `HOS_BOT_LOGIN` from the environment, stripped.
   - If it is empty → exit 1. The error text distinguishes a mint failure, when `HOS_BARE_HANDBACK_TOKEN_MINT_FAILED=1`, from misconfiguration. This copies `pr_review_cli.py:362-391`.
   - If it differs (casefolded) from `config.overseer_handle` → exit 3, `refusal_reason: "finalize_requires_overseer_identity_match"`.
7. `bot_accounts = frozenset(load_bot_accounts(str(repo_root)))`.

### 5.4 `check` flow (read-only; AD-3, AD-6 "check writes nothing")

1. `get_pull`. `GitHubError`, `None` or `parse_pr → None` → `UNDETERMINED (pr-unreadable)`.
2. `classify_population`. If it settles the answer, stop. No events or commit requests are made.
3. `events = fetch_all(f"/repos/{o}/{r}/issues/{n}/events")`.
4. `head_committed_at` comes from `get_commit(o, r, head_sha)` → `commit.committer.date`. A `GitHubError`, `None` or missing field gives `None`.
5. `classify(Evidence(...))`.
6. Emit the record. Exit 0 for every determination.

`check` never reads comments, never posts, never adds a label, never writes the state file and never writes an audit event.

### 5.5 `finalize` flow

Steps 1 to 5 of §5.4 run first, unchanged. Then:

**A. `NOT_BARE`** (every cause):
- Call `add_issue_labels(o, r, n, [args.label])`.
- If it raises (`GitHubError` or `ValueError`), or no returned `name`, casefolded, equals `args.label` → exit 1, `label_applied: false`.
- Otherwise `label_applied: true`, exit 0.

This is today's behaviour, now with verification (AD-3).

**B. `UNDETERMINED`:**
- No label. No comment read. No post.
- Run §6 `record_undetermined(pr, head_sha, cause)`.
- Exit 0, or exit 1 if the §6 audit or state write fails.

**C. `BARE_REMOVAL`** (no label on any branch below; REQ-4):
1. If `args.disposition != "HUMAN_REQUIRED"`, then `report: "none"`, `report_cause: "not-human-required"`, exit 0. No event and no comment read (AM-1, R-6).
2. `row = match_reason(reason)`. If `row is None` **or** `row.decision != "HUMAN_REQUIRED"`, then `report: "none"`, `report_cause: "reason-unrecognized"`, run §6 with cause `reason-unrecognized`, exit 0 (or 1 if §6 fails).
3. `comments = fetch_all(f"/repos/{o}/{r}/issues/{n}/comments")`. If the status is not COMPLETE, then `report: "none"`, `report_cause: "comments-failed"`, run §6 with cause `comments-failed`, exit 0 (or 1).
4. If `find_trusted_marker(comments.items, pr_number=n, removed_at=c.removed_at, overseer_login=config.overseer_handle)` returns a comment, then `report: "already"`, `comment_url` set to that comment's `html_url`, exit 0. No event.
5. `body = render_report(n, c, reason, row)`.
6. **Post.** `github.post_comment(o, r, n, body, verify=True, retries=0)`. A `GitHubError`, or a response with no `int` `id`, → exit 1, `report: "none"`, no event.
7. **Confirm** (AD-4 ordering step 2). `rc = read_comment(o, r, id)`. If `rc is None`, or `rc.user.login` (casefolded) is not `config.overseer_handle` (casefolded), or no line of `str(rc.body).split("\n")` [RC-2] equals `marker_line(n, c.removed_at, c.head_sha)` → exit 1, `report: "none"`, `comment_url` set from the POST response, no event.
8. **Audit.** Write `bare-handback-reported` (§7.1). Failure → exit 1, `report: "posted"`. The next cycle reports `already` and the event is a known gap (AD-4).
9. `report: "posted"`, exit 0.

`finalize` does not consult the #1215 precheck in any form (REQ-9). A prior overseer `**Decision: HUMAN_REQUIRED**` entry without this marker does not suppress the report (T-CLI-REQ9).

**Uncaught exception.** `main` wraps handler dispatch in `except Exception as exc`. It emits the envelope with `error: f"internal: {type(exc).__name__}"` (the type name only, never the message) and exits 1. stdout is therefore one JSON record on every path.

### 5.6 Output record (stdout: exactly one JSON object, one line, `json.dumps(..., sort_keys=True)`)

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `subcommand` | str or null | `check` / `finalize`; null only for a top-level usage error |
| `computed_at` | str | L2 clock, `%Y-%m-%dT%H:%M:%SZ`. The only clock-derived field. |
| `repo`, `pr`, `app_role` | str/int/str or null | as resolved |
| `error` | str or null | operational or usage error text. Never contains GitHub response bodies. |
| `refused`, `refusal_reason` | bool, str or null | exit-3 cases (§5.3) |
| `determination` | str or null | the `Determination` value; null if the run never reached classification |
| `cause` | str or null | the `Cause` value |
| `label_requested` | str or null | `--label` (`finalize`) |
| `disposition` | str or null | `--disposition` (`finalize`) |
| `label_applied` | bool | true only on a verified add (§5.5 A) |
| `report` | str | `posted` / `already` / `none` |
| `report_cause` | str or null | `not-human-required` / `reason-unrecognized` / `comments-failed`; null otherwise |
| `reason_row`, `reason_category` | str or null | set when §5.5 C2 matched |
| `comment_url` | str or null | the posted comment or the existing trusted one |
| `audit_event` | str or null | the path written, relative to `audit/log` |
| `undetermined_event` | str or null | `written` / `deduplicated`; null when §6 did not run |
| `summary` | str | the one human line (§5.7) |
| `evidence` | object | `head_sha`, `head_committed_at`, `labels` (sorted, casefolded), `removed_at`, `removed_by`, `removed_by_type`, `via_app`, `events_pages`, `events_status`, `comments_pages`, `comments_status`, `fetch_detail` |
| `not_verified` | list[str] | diagnostics, as in `merge_authority_cli` |

### 5.7 The one-line summary (REQ-4 "logs one stdout line"; OQ-3)

L2 writes the exact `summary` string to **stderr** and also includes it in the record. stdout stays exactly one JSON record (AD-3). In S2 the overseer echoes `summary` to its own cycle stdout. The fixed templates are:

| Outcome | `summary` |
|---|---|
| A applied | `applied <label> to PR #<n> (<cause>)` |
| C1 | `withheld <label> on PR #<n>: bare needs-human removal by <actor> at <ts>; disposition <D> posts its own comment` (verbatim from AD-3) |
| C2 | `withheld <label> on PR #<n>: bare needs-human removal; reason not in the merge-authority reason table; no report posted` |
| C3 | `withheld <label> on PR #<n>: bare needs-human removal; comments unreadable; no report posted this cycle` |
| C4 | `withheld <label> on PR #<n>: bare needs-human removal by <actor> at <ts> already reported (<url>)` |
| C9 | `withheld <label> on PR #<n>: reported bare needs-human removal by <actor> at <ts> (<url>)` |
| B | `undetermined on PR #<n>: <cause>; no label applied, no report posted; retry next cycle` |
| check | `check PR #<n>: <determination> (<cause>)` |
| exit 1/2/3 | `error on PR #<n>: <error or refusal_reason>` |

`<actor>` here is always `LOGIN_RE`-valid, because outcomes C1 to C9 require `BARE_REMOVAL`.

### 5.8 Exit codes (AD-3)

| Code | When |
|---|---|
| 0 | `check`: any determination. `finalize`: label applied and verified; `BARE_REMOVAL` with report `posted`/`already`/`none`; `UNDETERMINED` with its event written or deduplicated. |
| 1 | config error; repo unresolvable; `HOS_BOT_LOGIN` empty; label POST failed or not verified; report POST failed; confirm failed; audit write failed; state-file write failed; internal exception |
| 2 | usage, including the `--reason-file` contract |
| 3 | `finalize_requires_overseer_app`, `finalize_requires_overseer_identity_match`, `repo_scope_mismatch` |

---

## 6. Undetermined-outcome deduplication (AD-6, AM-5, REQ-6)

**File.** `<repo_root>/.claudetmp/bare-handback/undetermined-seen.json`. It is persistent, uncommitted and never reaped (contract §1 rule 2). The directory is created if absent.

**Schema.**
```
{"schema_version": 1,
 "keys": [{"pr": <int>, "head_sha": "<sha40>" | null, "cause": "<cause>", "first_seen": "<%Y-%m-%dT%H:%M:%SZ>"}]}
```

**Causes it covers:** every `UNDETERMINED` cause, plus `reason-unrecognized` and `comments-failed`. `actor-malformed` is already an `UNDETERMINED` cause.

**`record_undetermined(pr, head_sha, cause)`, in this order:**
1. **Load.** A missing file, invalid JSON, a wrong `schema_version` or a malformed entry means an empty key set. Add a `not_verified` note when the file existed. Never raise.
2. If `(pr, head_sha, cause)` is in the set → `undetermined_event: "deduplicated"`. Stop. Nothing is written.
3. Write the `bare-handback-undetermined` event (§7.2). Failure → exit 1. The state is not updated.
4. **Prune, then add the key.** Prune rules (OQ-7):
   - (a) drop every key for this `pr` whose `head_sha` differs from the current one, when the current one is non-null;
   - (b) if the PR snapshot exists and `state != "open"`, drop every key for this `pr`. **[RC-6]** Through `finalize` this rule is unreachable: a closed PR is `NOT_BARE (out-of-population)` at §3.4a step 1 and never reaches `record_undetermined`. Keep it as a defensive rule. The docstring must say it is unreachable through `finalize` today, and `test_state_prune_rules` must exercise it by calling `record_undetermined`'s prune helper directly, not through `main`. Do not add a PR read to make it reachable. In practice the only bound on stale keys is the 1000-key cap in (c);
   - (c) if more than 1000 keys remain, drop the oldest by `first_seen` until 1000 remain.
5. **Write atomically.** Write the JSON to a temp file in the same directory (`tempfile.NamedTemporaryFile(dir=..., delete=False)`), `flush` and `os.fsync`, then `os.replace` onto the target. Failure → exit 1, with `undetermined_event: "written"` (the event exists). The next cycle may repeat the event once per key, which the ADR accepts ("a lost or corrupt file causes at most one repeat event per key").

The store never influences `determination`, `label_applied` or `report`. It only gates the event.

Overseer cycles are serialized by the cron lock, so a single writer is assumed. `os.replace` keeps a concurrent reader from ever seeing a torn file.

---

## 7. Audit events (REQ-6; writer `audit_log.write_event(event, root=str(repo_root))`)

### 7.1 `bare-handback-reported` (once per posted report, after confirm)

```
{"event": "bare-handback-reported", "timestamp": <L2 clock>, "repo": "<o/r>", "pr": <int>,
 "head_sha": "<sha40>", "removed_at": "<ts>", "removed_by": "<login>", "reason": "<reason line>",
 "reason_row": "<row_id>", "reason_category": "<category>", "comment_url": "<html_url>",
 "comment_id": <int>, "writer": "scripts/automation/bare_handback_cli.py:finalize"}
```

### 7.2 `bare-handback-undetermined` (at most once per key)

```
{"event": "bare-handback-undetermined", "timestamp": <L2 clock>, "repo": "<o/r>", "pr": <int>,
 "head_sha": "<sha40>" | null, "cause": "<cause>", "detail": "<FetchResult.detail>" | null,
 "label_requested": "<label>", "disposition": "<D>",
 "reason": "<reason line>"   # only when cause == "reason-unrecognized"
 , "writer": "scripts/automation/bare_handback_cli.py:finalize"}
```

- `writer` is included now because TD-1538 (DRAFT) proposes it as provenance. `write_event` accepts arbitrary keys today. When TD-1538's `append_event` lands, this call site migrates under that design's writer inventory. It is listed here so that design can find it.
- `reason` is the overseer's own one-line, length-bounded text, stored as a JSON string. It is recorded so that a paraphrasing overseer (R-4) can be diagnosed.
- No GitHub-supplied free text goes into either event, apart from `removed_by` (grammar-checked) and `comment_url` (GitHub's `html_url`).

---

## 8. Interface S1 must serve for S2 (no S2 internals designed here)

- S2's `bootstrap/bare_handback.sh` (protected) has these duties: mint a token for `--app`; export `GH_TOKEN` and `HOS_BOT_LOGIN`; on a mint failure, export `HOS_BARE_HANDBACK_TOKEN_MINT_FAILED=1` and still run L2; exec `python3 scripts/automation/bare_handback_cli.py "$@"`; revoke; and pass stdout and the exit code through verbatim. S1 depends on nothing else from L3.
- The overseer supplies `--reason-file` as one line holding `MergeAuthorityResult.reason` verbatim (§5.2). ADR §4 items 7 and 8 (the four site wordings, the paragraph, the literal `/tmp/claude/…` path, and the contract-test anchors) are **deferred to the S2 technical design**.
- REQ-8 (the `bin/hos-cron` routing test) and the prompt-contract half of REQ-4 and REQ-9 are S2 tests.

---

## 9. Failure modes (S1 behaviour; extends ADR §3)

| Failure | Determination / outcome | Label | Post | Event | Exit |
|---|---|---|---|---|---|
| PR GET fails or is malformed | UNDETERMINED `pr-unreadable` | no | no | dedup | 0 |
| Events page error, 404, rate limit, wall-clock budget | UNDETERMINED `events-failed` | no | no | dedup | 0 |
| Events page not a list | UNDETERMINED `events-non-list` | no | no | dedup | 0 |
| 100 full pages | UNDETERMINED `events-tripwire` | no | no | dedup | 0 |
| Relevant event missing `id`/`created_at`, or a non-dict item | UNDETERMINED `events-malformed` | no | no | dedup | 0 |
| Last `needs-human` event `labeled`, label absent | UNDETERMINED `labels-events-disagree` | no | no | dedup | 0 |
| Removal actor absent / malformed login | UNDETERMINED `actor-missing` / `actor-malformed` | no | no | dedup | 0 |
| Commit GET fails, or no committer date | UNDETERMINED `head-unreadable` (only if step 8 is reached) | no | no | dedup | 0 |
| BARE, disposition not HUMAN_REQUIRED | BARE `not-human-required` | no | no | none | 0 |
| BARE, reason not in the table or row not HUMAN_REQUIRED | BARE `reason-unrecognized` | no | no | dedup | 0 |
| BARE, comments fetch not COMPLETE | BARE `comments-failed` | no | no | dedup | 0 |
| POST fails (no retry) | BARE | no | maybe landed | none | 1 |
| Confirm fails | BARE | no | landed | none | 1 |
| Audit write fails after confirm | BARE | no | landed | missing (known gap) | 1 |
| Label POST fails or not verified | NOT_BARE | maybe | no | none | 1 |
| State file unwritable | (unchanged) | (unchanged) | (unchanged) | written | 1 |

---

## 10. Test plan (REQ-10; all in the PR-required suite via `scripts/framework/run_tests_inner_loop.sh`)

**Shared fakes.**
- `tests/automation/test_bare_handback_*` use one router fake installed with `monkeypatch.setattr(github, "_run_gh", fake)`. The fake maps `(args[0], method)` to a response, or to an exception class to raise, and records every call (endpoint, `retries`, `stdin_json`).
- L2 tests call `main(argv, repo_root=tmp_path)`, with a copied `scripts/framework/machine-accounts.env` and a fake `git remote get-url origin`, using the same approach as `tests/automation/test_merge_authority_cli.py`.
- `HOS_BOT_LOGIN` is set with `monkeypatch.setenv`.

**Fixture.** `tests/automation/fixtures/bare_handback/pr1792.json` is an object with these keys:
- `provenance`: `"reconstructed from #1796 issue body"`, until the coder's live probe (file 10) captures the real page. The coder then replaces `events` with the real page and changes `provenance` to `"live: GET /repos/thurlow-research/HumanOversightSystem/issues/1792/events, <date>"`.
- `pr`: number 1792, `state` `"open"`, `draft` false, author `hos-worker-hos[bot]`, labels `[]`, and a placeholder 40-hex `head_sha`;
- `head_committed_at`: `2026-09-21T09:58:00Z` (reconstructed; earlier than the label);
- `events`: `[{"id": 1001, "event": "labeled", "actor": {"login": "hos-overseer-hos[bot]", "type": "Bot"}, "label": {"name": "needs-human"}, "created_at": "2026-09-21T10:09:00Z"}, {"id": 1002, "event": "unlabeled", "actor": {"login": "ScottThurlow", "type": "User"}, "label": {"name": "needs-human"}, "created_at": "2026-09-21T18:26:43Z"}]`, plus one irrelevant `"event": "review_requested"` item;
- `reason`: `"PR touches a protected surface — human approval required"` (reconstructed);
- `golden_report`: the exact expected `render_report` output.

### 10.1 `test_bare_handback_classify.py`

| Test | Asserts | REQ |
|---|---|---|
| `test_1792_regression_bare_and_deterministic` | the fixture gives `BARE_REMOVAL`, `removed_by == "ScottThurlow"`, `removed_at == "2026-09-21T18:26:43Z"`. Two `classify` calls are `==`, and two `render_report` calls are byte-identical and equal `golden_report`. | REQ-3, REQ-10 |
| `test_clause_flip[...]` (parametrized from the #1792 baseline, one mutation per case) | closed → `out-of-population`; draft → `out-of-population`; author `ScottThurlow` → `out-of-population`; label `needs-human` → `labelled`; label `Needs-AI` → `labelled` (case-insensitive); no `needs-human` events → `never-labelled`; removal by `hos-overseer-hos[bot]` → `bot-removal`; by `github-actions[bot]` → `bot-removal`; by a PAT login in `bot_accounts` with `type: "User"` → `bot-removal`; by `type: "Bot"` without a suffix → `bot-removal`; a later `labeled needs-ai` → `relabelled`; head after removal → `new-head` | REQ-1, REQ-7 |
| `test_human_removed_then_human_readded_is_not_bare` | label present → `labelled`. An events-only variant with a later human `labeled needs-human` gives `labels-events-disagree` when the label is absent (lag). | REQ-1 |
| `test_human_removed_then_needs_ai_added_and_removed_is_relabelled` | step 7 does not resurrect the episode | REQ-1, REQ-7 |
| `test_event_label_name_case_insensitive` | `label.name == "Needs-Human"` counts | REQ-1 |
| `test_last_needs_human_labeled_but_absent_is_undetermined` | `labels-events-disagree` | REQ-2 |
| `test_fetch_status_maps_to_cause[FAILED,NON_LIST,TRIPWIRE]` | `events-failed` / `events-non-list` / `events-tripwire` | REQ-2 |
| `test_events_malformed[non-dict,missing-id,bad-created_at]` | `events-malformed`; an irrelevant malformed dict is ignored | REQ-2 |
| `test_actor_missing_is_undetermined` / `test_actor_malformed_is_undetermined` | `actor-missing` (no actor, or empty login) / `actor-malformed` (`"bad login"`) | REQ-2, AD-4 |
| `test_head_unreadable_is_undetermined` | `head_committed_at=None` and `"garbage"` → `head-unreadable` | REQ-2 |
| `test_head_equal_to_removed_at_does_not_end_episode` | equal → `BARE_REMOVAL` | REQ-7 |
| `test_head_offset_timestamp_compared_in_utc` | `+02:00` form compared correctly | REQ-7 |
| `test_events_sorted_by_created_at_then_id` | reversed page order gives the same answer; equal `created_at` is ordered by `id` | REQ-3 |
| `test_episode_end_relabel` / `_closed` / `_merged` / `_draft` / `_new_head` | each → `NOT_BARE` with its cause | REQ-7 |
| `test_rearm_second_removal_new_removed_at` | removed → re-added → removed again gives `BARE_REMOVAL` with the second `removed_at` | REQ-5 re-arming |
| `test_performed_via_app_recorded_not_bot` | a human actor with non-null `performed_via_github_app` gives `BARE_REMOVAL` and `via_app` set | REQ-1, OQ-6 |
| `test_classify_is_pure` | **[RC-4]** With `github._run_gh`, `bare_handback.time.time` and `bare_handback.time.monotonic` patched to raise, the module-level name `bare_handback.datetime` replaced by a `datetime` subclass whose `now`/`utcnow`/`today` raise (so `fromisoformat` still works; step 8 needs it), and `os.environ` replaced by a mapping that raises on access, `classify` still returns. Do not patch `datetime` wholesale. `classify` legitimately calls `fromisoformat`, and the C type's attributes cannot be monkeypatched. The test must still pass if `bare_handback` is reloaded. | REQ-3 |
| `test_events_malformed_label_on_label_event[labeled-no-label, unlabeled-label-not-dict, unlabeled-empty-name]` | **[RC-1]** `events-malformed`. A `review_requested` event with no `label` is still ignored. | REQ-2 |
| `test_population_settles_without_events` | `classify_population` returns non-None for labelled, closed, draft and foreign-author PRs | REQ-2 |

### 10.2 `test_bare_handback_fetch.py`

| Test | Asserts | REQ |
|---|---|---|
| `test_single_short_page_complete` | COMPLETE, pages=1, one call with `?per_page=100&page=1` | REQ-2 |
| `test_full_page_then_empty_page_complete` | COMPLETE, pages=2 | REQ-2 |
| `test_page2_github_error_failed` | FAILED, detail `page=2`, items empty | REQ-2 |
| `test_page_none_is_failed` | a 404 or empty-body `None` → FAILED | REQ-2, AF-4 |
| `test_rate_limit_is_failed` | `RateLimitError` → FAILED | REQ-2 |
| `test_non_list_page` | a dict page → NON_LIST | REQ-2 |
| `test_tripwire_at_100_pages` | 100 full pages → TRIPWIRE after exactly 100 calls; no 101st call | REQ-2, AM-2 |
| `test_wall_clock_budget_failed` | patched `time.monotonic` past the deadline after page 1 → FAILED, detail starts `wall-clock-budget` | REQ-2 |
| `test_detail_never_contains_exception_text` | an exception message `"SECRET"` does not appear in `detail` | security |
| `test_no_events_request_when_pr_labelled` | `finalize` and `check` on a `needs-human` or `needs-ai` PR make no `/events` and no `/commits/` call | REQ-2 AC |
| `test_read_comment_none_on_error` | `GitHubError` / `None` / non-dict → `None` | AD-4 |

### 10.3 `test_bare_handback_report.py`

| Test | Asserts | REQ |
|---|---|---|
| `test_first_line_is_decision_header` | `body.split("\n")[0] == "**Decision: HUMAN_REQUIRED**"` | REQ-5 AM-4 |
| `test_required_content_present` | "unrouted"; `@ScottThurlow`; `removed_at`; `head_sha`; `` `<reason>` `` verbatim; "did not guess your intent and did not re-apply the label" | REQ-5 |
| `test_actions_present_issue_commands_absent` | the `needs-ai`, `needs-human` and close lines are present; regex `/(approve\|decline\|handoff)\b` (case-insensitive) finds nothing | REQ-5, VF-4 |
| `test_approve_line_only_for_satisfiable[row]` | parametrized over HUMAN_REQUIRED rows: the approve line is present iff the category is `human-approval-satisfiable` | REQ-5, AD-4 |
| `test_last_line_is_marker_and_roundtrips` | `MARKER_RE.fullmatch(last_line)`; the groups equal the inputs | REQ-5 |
| `test_render_preconditions_raise` | each §3.8 precondition violated alone raises `ValueError` | REQ-5 |
| `test_trusted_marker_found` | an overseer, `type` Bot, unedited comment with a matching line is returned | REQ-5 |
| `test_marker_untrusted[wrong-author,human-type,edited,other-pr,other-removed_at,inline-not-whole-line,inline-after-cr,author-case-variant-accepted]` ([RC-2]) | ignored in each case, except the case variant, which is accepted | REQ-5 |
| `test_marker_head_differs_still_trusted` | `head` is not part of the key | REQ-5 AM-4 |
| `test_reason_table_drift_every_reason_has_one_row` | **AST drift test** (below) | REQ-5 AM-4 |
| `test_reason_table_no_dead_rows` | every row matches at least one rendered sample | AM-4 |
| `test_reason_row_decision_matches_source` | each row's `decision` equals the `decision=MergeDecision.X` of the call it matches | AD-4 |
| `test_match_reason_rejects[paraphrase,trailing-space,newline,empty,1001-chars,two-rows]` | `None` | REQ-5 |
| `test_reason_groups_render_safe` | for each HUMAN_REQUIRED row, a sample with a backtick, `<`, `>` or `@` inserted into a capture group fails `fullmatch` | security |

**AST drift test algorithm.**
1. Parse `scripts/automation/lib/merge_authority.py` with `ast` and locate `FunctionDef decide_merge_authority`.
2. Collect every `ast.Call` whose `func` is `Name("MergeAuthorityResult")`, and from each take the `reason` keyword and the `decision` keyword (`Attribute` → `attr`).
3. Render each reason:
   - A `Constant` is its value.
   - A `JoinedStr` is rendered by substituting each `FormattedValue` with every sample in `SAMPLES[ast.unparse(fv.value)]`, taking the cartesian product. `SAMPLES = {"label_str": ["hos-halt", "hos-halt, needs-human"], "human_reviewer": ["ScottThurlow"], "oversight_verdict": ["ESCALATE", "CONDITIONAL_PROCEED"], "risk_tier.name": ["CRITICAL", "HIGH"], "overseer_ceiling.name": ["HIGH", "MEDIUM"], "pr_author": ["hos-overseer-hos[bot]"], "gate.reason": ["Branch protection not enabled on main"]}`.
   - `Name("merge_reason")` maps to a fixed AUTO_MERGE sample string defined in the test.
   - Any other node type, or an expression missing from `SAMPLES`, **fails** the test, with a message telling the author to add a row and a sample.
4. Assert that each rendered sample is matched by exactly one row, and that the row's `decision` equals the call's decision.

### 10.4 `test_bare_handback_cli.py`

| Test | Asserts | REQ |
|---|---|---|
| `test_finalize_not_bare_applies_label_verified` | one POST `/labels`, `retries=0`, `stdin_json={"labels":["needs-human"]}`; `label_applied: true`; exit 0 | REQ-4 (NOT_BARE unchanged) |
| `test_finalize_label_post_fails_exit1` / `_label_missing_from_response_exit1` | exit 1, `label_applied: false` | AD-3 |
| `test_finalize_label_plan_empty_for_bare_and_undetermined[...]` | across every BARE outcome and every UNDETERMINED cause: zero `/labels` calls (T-CLI-LABELPLAN) | REQ-4 AC |
| `test_finalize_bare_human_required_posts_once` | one POST `/comments` with `retries=0`; read-back by id; one `bare-handback-reported` event; `report: posted` | REQ-5, REQ-6 |
| `test_finalize_second_cycle_already` | state from the previous test (the comment is now in the fake's list): zero POSTs, zero new events, `report: already` | REQ-5 |
| `test_finalize_untrusted_marker_copy_still_posts` | a marker copy by `ScottThurlow` is ignored; one post | REQ-5 |
| `test_finalize_comments_failed_no_post` | page 1 error → zero POSTs, `report_cause: comments-failed`, one undetermined event | REQ-5 |
| `test_finalize_new_removal_after_readd_posts_new_report` | an old trusted marker with the old `removed_at` → one new post | REQ-5 re-arm |
| `test_finalize_bare_propose_only_and_merge_failed_withhold_no_report` | no label, no comment read, no post, `report_cause: not-human-required`, `summary` per §5.7 C1 | AM-1, REQ-4 |
| `test_finalize_reason_unrecognized_no_label_no_report` | paraphrased reason → zero `/labels`, zero `/comments` calls, dedup event with `reason` | AM-4 |
| `test_finalize_reason_row_not_human_required_is_unrecognized` | the `worker-class` reason with disposition HUMAN_REQUIRED → `reason-unrecognized` | AD-4 |
| `test_finalize_post_failure_no_event_exit1` | POST raises → exit 1, no audit file | REQ-5 ordering |
| `test_finalize_confirm_failure_no_event_exit1[none,wrong-author,no-marker]` | exit 1, no audit file | AD-4 |
| `test_finalize_audit_failure_exit1_then_already` | `write_event` raises → exit 1; the next run gives `already` and no second post | AD-4 |
| `test_reported_event_fields` | exact key set and values (§7.1) | REQ-6 |
| `test_undetermined_event_dedup_across_two_cycles` | two runs → one event; second run `undetermined_event: deduplicated` | REQ-6 |
| `test_undetermined_new_head_writes_new_event` | the same cause on a new head → a second event | REQ-6 |
| `test_state_file_corrupt_treated_empty` | invalid JSON → event written, file rewritten valid, `not_verified` note | AD-6 |
| `test_state_file_atomic_replace` | `os.replace` called with a temp file in the same directory; no partial file on simulated failure | AD-6 |
| `test_state_prune_rules` | rules (a), (b), (c) of §6 | AD-6 |
| `test_state_write_failure_exit1` | an unwritable directory → exit 1, `undetermined_event: written` | AD-6 |
| `test_finalize_refuses_non_overseer_app` | `--app worker` → exit 3 `finalize_requires_overseer_app`, zero network calls | AD-3 |
| `test_finalize_refuses_identity_mismatch` | `HOS_BOT_LOGIN=hos-worker-hos[bot]` → exit 3 | AD-3 |
| `test_finalize_hos_bot_login_unset_exit1[mint-failed,unset]` | exit 1, distinct error texts | AD-3 |
| `test_finalize_repo_scope_mismatch_exit3` | `--repo other/repo` → exit 3, zero network calls | security |
| `test_reason_file_contract_exit2[missing,empty,two-lines,cr,1001-bytes,non-utf8]` | exit 2, zero network calls | §5.2 |
| `test_trailing_newline_reason_file_accepted` | `"…(#757)\n"` → reason without `\n` | §5.2 |
| `test_usage_errors_one_record_exit2` | unknown flag, missing `--label`, `-h` | AD-3 |
| `test_stdout_exactly_one_json_line_all_paths` | parametrized over every exit path | AD-3 |
| `test_summary_on_stderr_and_in_record` | stderr line == `record["summary"]` | REQ-4, OQ-3 |
| `test_check_read_only` | `check` on a BARE PR: no POST, no `/comments` call, no `.claudetmp/bare-handback/` file, no `audit/log` file | AD-6 |
| `test_check_allows_any_app` | `--app worker` / `human` / `overseer` → exit 0 | AD-3 |
| `test_finalize_posts_despite_prior_human_required_entry` | a prior overseer comment containing `**Decision: HUMAN_REQUIRED**` without a marker → still exactly one post (T-CLI-REQ9) | REQ-9 (S1 half) |
| `test_pr_unreadable_undetermined_exit0` | `get_pull` → `None` → UNDETERMINED `pr-unreadable`, dedup event with `head_sha: null` | REQ-2 |
| `test_internal_exception_one_record_exit1` | a handler raising `KeyError("x")` → `error == "internal: KeyError"`, exit 1 | AD-3 |
| `test_import_graph_l1` | AST of `bare_handback.py`: imports ⊆ {stdlib, `scripts.automation.lib.github`, `scripts.framework.require_human_approval`, `scripts.framework.requester_trust`}; no `merge_authority` anywhere (T-CLI-IMPORTS) | AD-1 |
| `test_import_has_no_side_effects` | importing L2 with `_run_gh` patched to raise does not raise | §5.1 |

### 10.5 `test_github.py` (extend)

- `test_add_issue_labels_posts_stdin_json_retries_zero`
- `test_add_issue_labels_none_raises`
- `test_add_issue_labels_non_list_raises`
- `test_add_issue_labels_validates_input` (empty list, comma, newline)
- `test_post_comment_default_retries_unchanged` (the POST call receives `retries=3`)
- `test_post_comment_retries_zero_passed_to_post_only` (the read-back GET keeps its default)

---

## 11. Traceability

| REQ / ADR item | Design section | Tests |
|---|---|---|
| REQ-1 clauses 1-5 | §3.4a, §3.4b steps 1-7 | §10.1 `test_clause_flip`, `*_readded_*`, `*_relabelled`, `*_case_insensitive` |
| REQ-1 clause 6 (AM-1) | §5.5 C1 | `test_finalize_bare_propose_only_and_merge_failed_withhold_no_report` |
| REQ-2 | §3.4b steps 3, 3a, 5, 6, 8; §3.10; §5.4 step 2 | §10.1 `*_undetermined`, `test_fetch_status_maps_to_cause`; §10.2 all; `test_no_events_request_when_pr_labelled` |
| REQ-3 | §2 rule 1, §3.4b sort, §3.8 | `test_1792_regression_bare_and_deterministic`, `test_classify_is_pure`, `test_events_sorted_*` |
| REQ-4 (S1 half: label plan) | §2 rule 4, §5.5 A/B/C | `test_finalize_label_plan_empty_*`, `test_finalize_not_bare_applies_label_verified` |
| REQ-4 (overseer prose) | §8, deferred to S2 | S2 |
| REQ-5 rendering, actions, header | §3.6, §3.7, §3.8 | §10.3 |
| REQ-5 idempotency, trust, re-arm, ordering | §3.9, §5.5 C3-C9, §4.2 | §10.3 marker tests; §10.4 `*_posts_once`, `*_already`, `*_untrusted_*`, `*_comments_failed_*`, `*_new_removal_*`, `*_post_failure_*`, `*_confirm_failure_*` |
| REQ-5 reason gate (AM-4) | §3.6, §3.7, §5.5 C2 | drift tests, `test_match_reason_rejects`, `test_finalize_reason_*` |
| REQ-6 | §6, §7 | `test_reported_event_fields`, `test_undetermined_event_dedup_*`, `test_state_*` |
| REQ-7 / AD-7 / ESC-1(A) | §3.4b steps 1, 2, 7, 8 | `test_episode_end_*`, `test_head_equal_*`, `test_head_offset_*` |
| REQ-8 | none (S2 test) | S2 |
| REQ-9 | §5.5 last paragraph; header in §3.8 | `test_finalize_posts_despite_prior_human_required_entry`; prompt-contract half in S2 |
| REQ-10 | §10 | all, in `run_tests_inner_loop.sh` |
| AD-1 locus and imports | §1, §3.1, §5.1 | `test_import_graph_l1` |
| AD-3 L2 contract | §5 | §10.4 |
| AD-4 table, body, trust, ordering | §3.6-§3.9, §5.5 | §10.3, §10.4 |
| AD-6 fetch, tripwire, dedup | §3.10, §6 | §10.2, §10.4 state tests |
| ADR §4 "TD must specify" items 1-6 | 1 → §3.6; 2 → §3.5, §5.6; 3 → §3.8, §3.2; 4 → §4.1; 5 → §6; 6 → §10 fixture | n/a |
| ADR §4 items 7-8 | deferred to the S2 TD (§8) | S2 |

---

## 12. Startup-gap check and affected sign-offs

- **Should this have been settled in the initial technical design?** No. This is the first technical design for #1796, and the ADR records "startup gap: no" (ADR §6).
- **Affected sign-offs:** none. No code exists against any prior #1796 contract. The `github.post_comment` keyword (§4.2) is additive with an unchanged default, so the sign-offs on existing callers stand. A test pins the default. **[RC-5]** The existing callers are `merge_authority.route_embargo` (`merge_authority.py:816`) and `merge_authority.record_pr_bounce` (`:1292`). `pr_review_cli` does not call `post_comment`, and the round-1 draft named it in error. Neither caller passes `retries`, so both keep `retries=3`.

---

## 13. Open questions (for the architect unless marked otherwise)

- **OQ-1 (architect; must be answered before S2 merges; S1 is not blocked).** One of the PR actions the report offers can be silently undone. The report tells the human to "apply `needs-ai` … to hand it to the worker". After they do, the PR is `NOT_BARE (labelled)`. If the matrix still says HUMAN_REQUIRED, which it will for every human-approval gate, the next overseer cycle's `finalize --label needs-human` adds `needs-human`. With both labels present, `bin/hos-cron:1222` no longer routes `needs-fix` (#1526). The human's handback then works only if a worker cycle runs before the next overseer cycle. This is today's behaviour too, and the ADR preserves it on `NOT_BARE`. But REQ-5 now *advertises* the action as honoured (VF-4). Options:
  - (a) In `finalize`, also withhold `needs-human` when `needs-ai` is present and its latest `labeled` event is by a non-bot actor. This is not inference, because the human explicitly acted.
  - (b) Drop the `needs-ai` line from the report.
  - (c) Accept the race and document it.

  The TD implements REQ-5 as written. If the architect considers (a) a product change, it routes to `pm-agent`. A related lag case is not covered either: a `labeled needs-ai` event present while the label is still absent from the PR's label list gives `NOT_BARE (relabelled)` under ADR step 7, not `UNDETERMINED`. I recommend leaving it as is, because it matches today's behaviour.
- **OQ-2 (architect).** §4.2 adds `retries` to `post_comment` and calls it with `retries=0`. AD-4 names `post_comment(verify=True)` only. Without the change, an ambiguous POST retry can create a second trusted report, which breaks REQ-5's "exactly one". I believe this is within AD-4's intent, but it edits a shared helper's signature, so it needs a ruling.
- **OQ-3 (architect).** AD-3 says both "print one stdout line" and "stdout is exactly one JSON record". The TD resolves the conflict with stderr plus a `summary` field that the overseer echoes in S2 (§5.7). Please confirm.
- **OQ-4 (architect).** Row `requested-reviewer-761` is classified `other`. GitHub removes a reviewer from `requested_reviewers` when that reviewer submits a review, so an approval would in practice clear the gate. But neither `decide_merge_authority()` nor `overseer.md` step 6 says so, and AD-4's rule requires one of them to. The report therefore omits the approve line for this reason.
- **OQ-5 (architect / reliability-reviewer).** The ADR sets no wall-clock bound. The TD adds `FETCH_WALL_CLOCK_BUDGET_SECONDS = 180` per fetch, failing to `events-failed` / `comments-failed`. Without it, 100 pages × about 127 s worst case is unbounded in practice.
- **OQ-6 (architect / security-reviewer).** `performed_via_github_app` is recorded but does not make a removal a bot removal (§3.4b step 6). That is the REQ-4-safe direction. The live probe (file 10) should confirm how the field appears for the web UI, for `gh` with a personal token, and for an App installation token.
- **OQ-7 (architect).** AD-6 says to prune "to keys whose PR is still open". Taken literally, that needs a PR read per stored key. The TD uses read-free rules instead (§6 (a), (b), (c)). The worst case is a stale key for a PR that closed without another `finalize` run, bounded by the 1000-key cap.
- **ESC: none.** Each point above is a technical call inside the 2026-10-02 ruling. OQ-1 becomes an ESC only if the architect and `pm-agent` judge option (a) to be outside that ruling.

### 13.1 Architect rulings (2026-10-19, binding on S1)

- **OQ-1 → ESC-1 for the human. S1 default: (c). S1 is not blocked.**
  - **The premise is verified.** At `bin/hos-cron:1222`, `needs-ai` routes to `needs-fix` only when `needs-human` is absent. `overseer.md:468` (5) re-adds `needs-human` every cycle on any HUMAN_REQUIRED PR, and nothing exempts a PR that carries a human-applied `needs-ai`. The advertised handback therefore survives only if a worker cycle runs before the next overseer cycle.
  - **This defect predates #1796 and is wider than it.** The documented resume signal (remove `needs-human`, add `needs-ai`; `docs/OVERSIGHT-RUNBOOK.md` "Intervening" #1) is undone the same way on *every* still-HUMAN_REQUIRED worker PR today, bare or not. REQUIREMENTS-1796 VF-4 states that the code honours this action. That is only partly true.
  - **Why this is not mine to settle alone.** (a) changes `NOT_BARE` behaviour, which REQ-4 pins as "unchanged". It also changes what users see on PRs that were never in a bare episode, so it is a requirements change with a product consequence (CORE product-boundary checkpoint) and is outside the 2026-10-02 ruling, which covers bare removals only. (b) removes an action that REQ-5 lists by name. (c) keeps REQ-5 as written, but the report then advertises an action that the overseer can silently undo. All three options amend or knowingly accept a gap in a pm-verified requirement, so the choice goes to the human. The S2 CODEOWNER review is the natural point to answer it.
  - **S1 builds (c).** The template stays as §3.8 specifies. Changing to (b) later means deleting one template line and one test assertion. Changing to (a) means adding one `finalize` branch. Neither choice changes the S1 contracts (enum, record, marker), so building S1 now orphans no work.
  - **Lag sub-case.** A `labeled needs-ai` event that is present while the label list does not yet show it gives `NOT_BARE (relabelled)`, as ADR AD-2 step 7 says. I accept this, because it matches today's behaviour. It belongs to the same class as ESC-1 and is resolved by whichever ESC-1 answer the human picks.
- **OQ-2 → APPROVED.** `post_comment` gains a keyword-only `retries: int = 3`, applied to the POST only, and `bare_handback_cli` passes `retries=0`. This is within AD-4's intent: REQ-5's "exactly one" cannot hold if the transport retries an ambiguous non-idempotent POST. The `submit_pull_review` MUST_FIX D precedent (`github.py:486-498`) is the right model. I verified at `github.py:38-156` that `_run_gh` retries the "no status, rc≠0" connection-reset case. Two notes for the coder:
  - `post_comment(verify=True)` raises `GitHubError` when its *read-back* fails, and by then the comment has landed. §5.5 C6 maps that to exit 1, `report: none`, no event. That is correct: the next cycle's trusted-marker read finds the comment and reports `already`. `comment_url` is unavailable on that path, so record it as `null`.
  - The new keyword is a signature change to a shared helper. Pin the default with `test_post_comment_default_retries_unchanged`, as the TD already does.
- **OQ-3 → APPROVED.** stdout carries exactly one JSON record. The human line goes to stderr and into the record's `summary` field. In S2 the overseer echoes `summary`. This satisfies both AD-3 sentences without a second stdout line that would break machine parsing.
- **OQ-4 → APPROVED: `requested-reviewer-761` stays `other`.** AD-4's category rule is grounded in our code (`decide_merge_authority` or `overseer.md` step 6), not in GitHub platform behaviour. Omitting the approve line is the safe direction, because the report never advertises an action the code does not back. **Residual R-7 (for the S2 TD):** step 6 (1) `request-reviewer` makes the overseer itself create the review request, so on later cycles `decide_merge_authority` can return the `requested-reviewer-761` reason, which comes earlier in its order, instead of the underlying protected-surface or #757 reason. On such PRs the report quotes the review-request reason and leaves out the approve line, even though an approval is exactly what would unblock the PR. The S2 TD must state this in the overseer prose. It must not "fix" it by reordering the matrix, which REQ-4 does not allow.
- **OQ-5 → APPROVED: `FETCH_WALL_CLOCK_BUDGET_SECONDS = 180` per `fetch_all`, as a module constant and not a flag.** Without a wall-clock bound, a 100-page tripwire is not a time bound. Failing to `events-failed`/`comments-failed` is the REQ-2 direction. The budget is soft: a `Retry-After` sleep inside `_run_gh` can push one page past it. The worst case for one `finalize` (PR + events + commit + comments + post + confirm) is on the order of 10 to 15 minutes. That is acceptable only because it requires pathological GitHub behaviour, and the per-cycle backstop is `HOS_CRON_MAX_SECONDS` (#1146). `reliability-reviewer` must confirm this arithmetic against the configured cycle cap.
- **OQ-6 → APPROVED.** `performed_via_github_app` is recorded in `via_app` and does not enter the bot test. Our own Apps act as `*[bot]` actors with `type: "Bot"`, so `is_bot_reviewer` classifies them by identity without the field. A human acting through a third-party app is still a human act, and treating it as a bot removal would re-apply over it, which REQ-4 forbids. The live probe (file 10) must record how the field appears for (i) the web UI, (ii) `gh` with a personal token and (iii) an App installation token. If (iii) ever shows a *human* `actor` with an App in `performed_via_github_app` for one of **our** Apps, stop and escalate. Do not adjust the classifier inside S1.
- **OQ-7 → APPROVED: read-free pruning with rules (a) and (c), and (b) as a defensive rule ([RC-6]).** AD-6's "prune to keys whose PR is still open" is hereby refined: no PR read is spent on pruning. A stale key costs a few bytes and can at worst suppress one repeat event for a PR that is no longer evaluated. It can never change a label or a report decision, because the store gates only the event (§6, last paragraph).

---

## Escalation flag (CORE self-flag)

RISK: MEDIUM. This inherits ADR-1796's computed tier for the code this contract governs. The document itself is documentation-only, and S1 is inert until S2 is wired in.
CONFIDENCE: HIGH on §0 and §3.6, which come from file reads at `76b367795` with line citations. MEDIUM on the events-API actor shape (`actor.type`, `performed_via_github_app`), which the S1 live probe confirms. MEDIUM on OQ-1's practical weight.
BLAST RADIUS: none at merge time, because S1 has no caller. After S2: overseer label writes and one comment per episode on open worker PRs.
Change classification: additive.

## Human Review Required

- No human gate applies to S1: the surface is unprotected and the slice is inert. The architect review of this TD is the next gate.
- OQ-1 must be resolved before the S2 PR (CODEOWNER-gated) merges. It decides whether the report's "apply `needs-ai`" action can be silently undone by the overseer's next cycle.
- REQ-2, REQ-4 and REQ-5 are not waivable, and nothing here relaxes them.

---

## 14. Architect review (round 1, 2026-10-19)

**Verdict: APPROVED WITH CHANGES.** RC-1 to RC-6 are applied in place. With them, the design is sound for S1, and it may go to `coder`. Round count: 1 of 5. No loop state is carried forward.

### 14.1 Claims verified against the tree (`76b367795`)

- **`github._run_gh` (`github.py:38-156`).**
  - A 404 returns `None` (`:136-137`), and so does an empty body (`:148-149`).
  - 403 and 429 retry, then raise `RateLimitError`, a subclass of `GitHubError` (`:23`).
  - A "no status, rc≠0" result is retried, which is the connection-reset-after-send case. That is why OQ-2 is required, not cosmetic.
  - Per-attempt timeout 30 s, with 4 attempts and backoff 1+2+4. The TD's ~127 s per page is correct, excluding `Retry-After`.
  - `json.loads("[]")` gives a list, so the full-page-then-empty-page COMPLETE case holds.
- **`list_issue_comments` (`:215-238`)** breaks on a falsy batch and has no bound. The rejection (AF-4) stands.
- **`post_comment` (`:418-461`)** has no `retries` parameter today. Its read-back raises after the POST has landed. Both behaviours are handled (§13.1 OQ-2).
- **`get_commit` (`:405-415`)** returns the raw commit, and `commit.committer.date` is the right field.
- **`merge_authority.decide_merge_authority` (`:498-743`).** Every `reason=` cited in §3.6 is at the stated line. Each pattern matches its source literal, including the implicit string concatenation at `:576-579`, `:590-593`, `:608-611` and `:726-729`, which `ast` folds into one `JoinedStr`. The `FormattedValue` set is exactly `label_str`, `human_reviewer`, `oversight_verdict`, `risk_tier.name`, `overseer_ceiling.name`, `pr_author` and `gate.reason`, which matches the `SAMPLES` keys. `RiskTier` names are SAFE, LOW, MEDIUM, HIGH and CRITICAL (`:293-298`), which matches `TIER`.
- **Category assignments.** Each one meets the AD-4 rule.
  - `security-relevant` (`:657-673`), `protected-surface` (`:679-695`) and `universal-approval-757` (`:713-731`) consult `_find_human_approval`.
  - `prior-decision-761` (`:573`) consults it as well. It is unwired (#1839), so it is unreachable today, but the category is correct.
  - `tier-ceiling-critical` is backed by `overseer.md:467` (3), "merge immediately" on a CODEOWNER approval. Note that the CRITICAL path applies no label today (ADR AD-5), so this row is reachable through `finalize` only if S2 routes the CRITICAL path through it. That is the S2 TD's call.
  - Every other row does not consult reviews.
- **Trusted-marker rule** (`escalate_to_human.sh:21-25,223-227`): case-insensitive login, `type == "Bot"`, `updated_at == created_at`, whole line via `split("\n")`. The TD matched this except for the line split, which RC-2 fixes.
- **`is_bot_reviewer` (`require_human_approval.py:140-159`)** and **`load_bot_accounts` (`requester_trust.py:301-322`)** behave as the TD uses them. The baseline is unioned with the environment. L2 uses `load_bot_accounts`, not `merge_config`'s `bot_accounts`, which is strictly stricter and therefore correct.
- **`merge_config`** imports `merge_authority.RiskTier`. That import is L2-only, so T-CLI-IMPORTS (L1 only) is unaffected, and AD-1 constrains only L1. Correct.
- **`audit_log.write_event` (`audit_log.py:126-157`)** takes its filename timestamp from `event["timestamp"]`. The §7 events supply it, so the shard path comes from the L2 clock exactly once. Correct.

### 14.2 Required changes (applied)

| RC | Where | Failure mode in the round-1 draft | Change |
|---|---|---|---|
| RC-1 | §3.4b step 3a; §10.1 | A `labeled`/`unlabeled` event with a missing or malformed `label` was "irrelevant" and silently skipped. If it was the true last `needs-human` event, the classifier would answer from incomplete evidence. That fails open and violates REQ-2. | Such an event → `events-malformed`. New test. |
| RC-2 | §3.9 cond. 5; §5.5 C7 | `splitlines()` splits on `\r` and other separators that jq's `split("\n")` does not, so the "same rule" claim was false and the whole-line test was looser. | `split("\n")`. New untrusted case `inline-after-cr`. |
| RC-3 | §5.2 | The single-line, ≤1000-byte reason contract applied to every disposition. PROPOSE_ONLY and MERGE_FAILED reasons embed exception and `gh` text (`merge_authority.py:252,710`), so a multi-line reason would exit 2 and block a `NOT_BARE` label that is applied today. That is a REQ-4 "NOT_BARE unchanged" regression. | The contract is enforced for HUMAN_REQUIRED only. For other dispositions the file must exist, and its content is never read. New tests. |
| RC-4 | §10.1 `test_classify_is_pure` | "`datetime` access monkeypatched to raise" would break `fromisoformat`, which step 8 requires. The test as written was either unimplementable or vacuous. | Patch only the clock entry points through a module-level subclass. |
| RC-5 | §12 | The affected-sign-off list named `pr_review_cli` as a `post_comment` caller, which it is not, and left out `route_embargo` (`merge_authority.py:816`). | Citation corrected. The conclusion (sign-offs stand) is unchanged. |
| RC-6 | §6 rule (b) | The prune rule is unreachable through `finalize` (a closed PR is `out-of-population`), so the test as written would pass vacuously. | Kept as a defensive rule. Documented, and tested directly. |

### 14.3 What is right, and what could still go wrong

- **The purity boundary and the single `_run_gh` seam (§2)** are right. Every fail-closed claim becomes testable with one fake. *Risk:* a coder writes `from scripts.automation.lib.github import _run_gh`, which bypasses the patch so tests hit the network or pass vacuously. T-CLI-IMPORTS should also assert that no `from … github import _run_gh` appears in L1 or L2. The coder should add that assertion; it is a one-line extension of an existing test, not a design change.
- **The label-write site (§2 rule 4, T-CLI-LABELPLAN)** is right. It is the mechanical half of REQ-4. *Risk:* none in S1. R-1, the prose routing, is S2's.
- **The `(created_at, id)` sort and `TS_RE` lexical ordering** are right for GitHub's fixed-width `Z` timestamps. *Risk:* GitHub changes the timestamp format. `TS_RE` then rejects every relevant event, and the result is `events-malformed`, which fails closed. That is the correct direction.
- **Strict `>` at step 8** is right. A same-second commit does not end the episode, so the failure direction is to keep withholding, which is safe (R-2).
- **The reason table** is right, and the AST drift test is the correct guard. *Risk:* `test_reason_table_drift` passes, but someone edits a literal so that it still matches a *different* row. That is caught by "exactly one row" plus `test_reason_row_decision_matches_source`.
- **Report rendering.** The precondition `match_reason(reason) is row` is an identity check. It works only because `REASON_TABLE` rows are module singletons. The coder must not rebuild rows per call.

### 14.4 Escalations for the human

- **ESC-1 (from OQ-1). Should the report keep advertising "apply `needs-ai`", given that the next overseer cycle can silently undo it?** S1 is not blocked by this. Answer it before or at the S2 CODEOWNER review.
  - **(a)** `finalize` also withholds `needs-human` when `needs-ai` is present and its latest `labeled` event is by a non-bot actor. This fixes the general resume-signal race (bare or not). It changes `NOT_BARE` behaviour (REQ-4 amendment) and is user-visible.
  - **(b)** Drop the `needs-ai` line from the report. The report is then honest, but the human loses the one-click handback it advertises (REQ-5 amendment).
  - **(c)** Keep REQ-5 as written. The race stays as it is today, and the report advertises an action that holds only if a worker cycle runs before the overseer's next one.
  - **Architect recommendation:** (c) for #1796, plus a separate requirements issue (via `pm-agent`) for the general defect "overseer re-adds `needs-human` over a human-applied `needs-ai`", with (a) as its likely design. The defect predates this issue and is wider than it, so fixing it inside #1796 would widen a human-ruled, purely additive change. S1 builds (c) either way, and switching later is a one-branch or one-line change.

### 14.5 Startup-gap and affected sign-offs

- **Startup gap: no.** These rulings refine the ADR's own open items (AD-4 categories, AD-6 pruning) or correct the TD. No prior decision is superseded.
- **Affected sign-offs: none.** No code exists against this TD. The ADR-1796 approval stands. The AD-6 pruning wording is refined by the OQ-7 ruling, not reversed.
