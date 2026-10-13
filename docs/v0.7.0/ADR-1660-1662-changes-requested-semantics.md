# ADR-1660/1662 — One meaning for CHANGES_REQUESTED: merge authority holds on it, worker routing stops livelocking on it

Issues: #1660 (merge authority is blind to CHANGES_REQUESTED) and #1662 (worker routing counts every
CHANGES_REQUESTED ever posted and livelocks). Both are bug, priority:high, milestone v0.7.0.
Author: architect. Date: 2026-10-13. Baseline: `a781632ba`.
Input: `docs/v0.7.0/REQUIREMENTS-1660-1662-changes-requested-semantics.md` (pm-agent, committed at `a781632ba`).
Coordinates with: `docs/v0.7.0/ADR-1644-stage-per-cycle.md` (Erratum 2) and
`docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0b-pr-classifier.md` (§2.5 R, §2.6 C5/C6, §7).

**Verdict on the requirements: APPROVED_WITH_AMENDMENTS.** The requirements are feasible and correctly
framed. Three questions, one signal, one shared definition is the right shape. Eleven amendments
(AM-1..AM-11, §6) fix internal contradictions, a trust gap and an under-specified definition. None of
them changes the intent.

**Status: Accepted (technical).** ESC-1, ESC-3, ESC-5 and ESC-6 are ruled here as architecture. ESC-2 is
split: its routing and merge halves are ruled, and its bound-counting half stays with the human as
**ESC-2b**. **ESC-4** stays with the human. S1, S2 and S3 can be coded now (§5).

---

## 0. Context, verified against the code (2026-10-13)

| Claim | Verified | Consequence |
|---|---|---|
| `detect_human_hold_directive()` reads issue comments only (`merge_authority.py:120-164`) | Yes | #1660 is real. The CR signal reaches no merge-authority input. |
| `decide_merge_authority()` has no CR handling (`:498-743`) | Yes | — |
| `reviews=None` defaults to `[]` (`:551-552`) | Yes. **The PM's stated hazard is narrower than claimed.** An empty list cannot produce AUTO_MERGE, because #757 (`:717-731`) needs an APPROVED review in that list. And AUTO_MERGE is unreachable today in any case: `_dep_ceiling_check_present()` returns `False` (`:192-194`), so `detect_server_side_gate()` always returns PROPOSE_ONLY. | **The real hazard is a partial list.** If page 1 holds a head-SHA approval and page 2 holds a later CR, a hold is missed. REQ-CR-32 stands, restated as AM-4. |
| The only production caller of `decide_merge_authority()` is overseer.md's prose (`overseer.md:310-410`). The overseer fetches reviews with a raw `GET …/reviews`. | Yes. That is one page at the default of 30, with no completeness proof. | A control that depends on a caller remembering an input is how #1253 broke (DECISIONS.md:606-608). The CR guard must fail closed when its input is absent (D3). |
| `bootstrap/merge_authority.sh hold-directive` goes to `merge_authority_cli.py:482-576`. Its `hold_active` field reflects the comment scan only, and `comments_scanned` counts comments. | Yes | REQ-CR-40 extends this payload. |
| `github.list_pull_reviews()` paginates at 100 (`github.py:351-372`) | Yes, but **it is not completeness-safe**. `_run_gh` returns `None` on a 404 (`github.py:~137`). The loop treats `None` as end-of-list, so a 404 on page *k* > 1 yields a silently truncated list. It also does not type-check pages: `extend()` on a dict page adds the dict's keys. And it has no page cap. | D2 hardens it (AM-10). |
| Worker routing reads CRs at `bin/hos-cron:1225-1228` with `[.[] \| select(.state=="CHANGES_REQUESTED")] \| length`, falling back to `\|\| echo "0"`, and repeats the read for APPROVED at `:1229-1232` | Yes. **It also reads only one page of 30**, because no `per_page` is set. | #1662 is real. There is also a second truncation, in addition to the read-failure fallback. |
| T3.0b §2.5: "on a read failure CR = false" | True, but **the PM's reading that this is fail-open is incomplete**. The same read failure sets `reviews_ok=False`, so C8 classifies the PR as overseer-pending and new work stays BLOCKED. Its text is still `needs-attention` ("not yet reviewed"), which REQ-CR-14 forbids. | Amendment AM-9 corrects the Sequencing text. The T3.0b erratum (§4) still has to change the token. |
| Branch protection (`setup_branch_protection.sh:165-173`): `dismiss_stale_reviews: true`, `require_code_owner_reviews: true`, `strict: false` | Yes. **On a push, GitHub dismisses only APPROVED reviews. A CHANGES_REQUESTED review stays until it is dismissed or the same reviewer supersedes it.** This answers the PM's first "Not determined here" item. | #1727's shape is the ordinary lifecycle, as the PM said. A head-SHA match alone cannot clear a CR. |
| No pipeline identity posts CHANGES_REQUESTED: `pr_review_cli.py:173` rejects it, and `post_review_thread.sh` always submits COMMENT (ADR-1657 AD-2) | Yes | Every CR the pipeline can see was posted by a human or by a third-party account. That bears on ESC-5 and AM-2. |
| #1925 (ARCH-ESC-1R, which gates T3.0b coding) | Open, `needs-human`, unanswered since 2026-10-02. **It has been re-milestoned to v0.7.10.** | T3.0b cannot be the vehicle for a v0.7.0 priority:high livelock fix. This decides the sequencing (§4). |

---

## 1. The shared definition (binding; REQ-CR-01, REQ-CR-02)

### D1 — One stdlib module computes review state: `scripts/framework/review_state.py`

The module is new, stdlib-only, protected (`scripts/framework/**`), and listed in
`framework_consumer_files.txt`. Its pure functions do no I/O. Every consumer calls them:
- the `bin/hos-cron` routing (through the module's CLI, §3);
- the T3.0b classifier, by import, once T3.0b lands;
- `merge_authority.decide_merge_authority()`;
- `merge_authority_cli.py hold-directive`.

Pure API (`technical-design` fixes the exact names):

1. **`assemble_pages(pages, per_page, max_pages) -> ReviewList | Unknown(cause)`.** This is the only
   completeness rule, and both fetchers feed raw pages into it:
   - every page must be a JSON array of objects;
   - each review must have a `str` `state` and an `int` `id`;
   - pages are read only while the previous page was full;
   - a full page at `max_pages` gives `Unknown("reviews-page-cap")`;
   - a fetch failure on any page, including a 404 on a page after the first, gives
     `Unknown("reviews-read-failed")`;
   - a malformed page gives `Unknown("reviews-unparseable")`;
   - a duplicate `id` gives `Unknown("reviews-unparseable")`.

   The routing CLI reads at most `max_pages = 3` (300 reviews). The merge-authority fetcher reads at most
   10. **A full page that contains a CR is no longer a determination**, because a later page can hold the
   APPROVED that supersedes it (REQ-CR-02 and fixture (i)).
2. **`effective_states(reviews) -> {reviewer_key: EffectiveState}`**, with these rules:
   - **State-bearing reviews are `APPROVED` and `CHANGES_REQUESTED` only.** `COMMENTED`, `PENDING`
     **and `DISMISSED`** do not set a reviewer's effective state (AM-3).
   - **A dismissal removes a review. It never acts as a new verdict.** GitHub reports a dismissed review
     as `state: DISMISSED` and does not expose the review's original state. If a later dismissal could
     supersede an earlier CR, then a dismissed *APPROVED* would clear the CR that preceded it. That case
     happens on every push under `dismiss_stale_reviews: true`. Treating dismissal as removal fails
     safe: the earlier CR resurfaces, and #757 already needs a fresh approval on that head.
   - **Order** is by `submitted_at`. A tie, or a missing or unparseable `submitted_at`, orders a CR as
     latest and any other review as earliest. That is the PM's fail-safe tie-break, made total.
   - **`reviewer_key`** is `user.login`. A review with `user: null` (a deleted account) gets the key
     `ghost:<review id>` and is untrusted (D4).
3. **`outstanding_crs(reviews, head_sha) -> [OutstandingCR]`.** Each item carries:
   - `review_id`, `commit_id`, `submitted_at`, `html_url` and `login`;
   - `trusted_human: bool` (D4);
   - `head_current: bool`, which is `commit_id == head_sha`. A `commit_id` of `None` is **not**
     head-current.

   **Every consumer agrees on this list.** Each consumer filters it by `trusted_human` itself (AM-1).
4. **`acted_on(cr, pr_commits) -> ACTED | NOT_ACTED | Unknown(cause)`.** The mechanism is D5.
5. **`noop_notice_covers(cr, head_sha, comments, author) -> bool`.** This is ESC-4's carrier (D6). It is
   **inert until ESC-4 is ruled** and is not called before S4.

The module never returns the review `body` to any routing caller (§3, security note).

### D4 — Who is trusted (ESC-5 ruled; AM-1, AM-2)

`trusted_human` is true iff **either** of the following holds:
- `author_association` ∈ {`OWNER`, `MEMBER`, `COLLABORATOR`} **and** `user.login` does not end in
  `[bot]`. This is the same test as ADR-1644 Erratum 2 E9.
- `user.login` equals `HUMAN_REVIEWER` (case-insensitive), whatever its association.

**Merge authority** holds only on trusted-human CRs.

**Worker routing** acts only on trusted-human CRs too. This is **AM-2**, a deliberate narrowing of
REQ-CR-10's "any reviewer, human or bot":
- On `needs-fix` the worker reads the CR's review text and acts on it (`worker-cron-prompt.md:75`).
  Routing on an untrusted CR therefore hands control of the worker to anyone able to post a review.
  On a public consumer repository, that is anyone. This is the same injection class that the #1540
  requester-trust gate and E9 already close for issues and approvals.
- No pipeline identity posts CRs (§0), so this removes no pipeline signal.
- An untrusted outstanding CR is **not invisible**:
  - it appears in the REQ-CR-15 audit record and in the hold-directive evidence as `untrusted_outstanding`;
  - GitHub branch protection still enforces it wherever the account has write access.
- This is stricter on trust and changes nothing for any human with write access. It is not routed to
  the human.

---

## 2. Merge authority (#1660)

### D2 — A completeness-carrying review fetch

`github.list_pull_reviews()` is rebuilt on `assemble_pages` with a 10-page cap. A read failure, a 404
on a page after the first, a malformed page, or the cap now **raises** `GitHubError`; none of them
returns a short list. This only ever fails closed for its existing caller, `human-approval` (AM-10).

A new `list_pull_reviews_snapshot()` returns a frozen `ReviewSnapshot(reviews, complete=True)`. It is
the only constructor of a *complete* snapshot.

### D3 — The CR guard in `decide_merge_authority()` (REQ-CR-30..33)

1. **New keyword parameter `review_snapshot: Optional[ReviewSnapshot] = None`.**
   - **`None` means "not supplied". It is never read as "read and empty".**
   - `[]`, wrapped in a complete snapshot, means "read, no reviews".
   - The type tells the two apart. No sentinel value is involved. This settles REQ-CR-32's "the
     architect decides".
2. **Position.** The guard comes immediately after the #902 guard (`:605-613`) and before the release,
   worker-class, verdict and ceiling guards. It sits in the same band as #756, #761 and #902.
3. **Outcomes:**

| Input | Decision | Reason prefix | `labels_to_add` |
|---|---|---|---|
| snapshot `None` | HUMAN_REQUIRED | `REVIEW_STATE_UNKNOWN: review list not supplied (#1660)` | `[]` |
| snapshot not complete (cannot be constructed; defensive) | HUMAN_REQUIRED | `REVIEW_STATE_UNKNOWN: …` | `[]` |
| complete; ≥ 1 `trusted_human` outstanding CR | HUMAN_REQUIRED | `CHANGES_REQUESTED_HOLD: <login> <html_url> on <commit_id[:12]> (head-current: yes/no) (#1660)`, one clause per CR | `["needs-human"]` |
| complete; none | continue | — | — |

4. **Why `REVIEW_STATE_UNKNOWN` adds no label.** An unreadable list is usually transient. Adding
   `needs-human` would put a human on every API blip. The decision is still HUMAN_REQUIRED, so nothing
   merges and nothing is approved. The overseer records the condition and re-reads next cycle (D7).
5. **Nothing clears the hold except the trusted human's own effective state** (ESC-1, ESC-3):
   - a later APPROVED or CR from **that** reviewer;
   - dismissal of the CR.

   A push, a later APPROVED from a different reviewer, or any agent judgement does not clear it. The
   APPROVED-then-CR case on the same head (fixture (k)) is held even though `_find_human_approval`
   would find the earlier approval.
6. **#757, `_find_human_approval` and the `reviews` parameter are unchanged** (REQ-CR-31, non-goal).
   The overseer passes `reviews=snapshot.reviews`, so both checks see one list.

### D7 — Overseer behavior (REQ-CR-34, and the approve rule for REQ-CR-32)

These are amendments to `.claude/agents/overseer.md` §5/§6, authored by the top-level session
(CLAUDE.md, #1347):
- **Fetch.** The overseer obtains the CR evidence through `bash bootstrap/merge_authority.sh
  hold-directive` (D8). It passes a snapshot built by `list_pull_reviews_snapshot()` to
  `decide_merge_authority()`. It does not hand-roll the reviews GET.
- **On `CHANGES_REQUESTED_HOLD`:**
  - the verdict event is `comment`, never `approve`;
  - step 6(3)'s dismissal of the overseer's **own** standing APPROVED fires, exactly as for #902;
  - the overseer never dismisses, and never asks anyone to dismiss, the human's CR;
  - it may say that the findings appear addressed.
- **On `REVIEW_STATE_UNKNOWN`:**
  - the verdict event is not `approve`;
  - no dismissal;
  - no `needs-human` label;
  - write a `review-state-unknown` audit event;
  - do not post a findings comment (the #1215 duplicate-verdict discipline applies);
  - re-evaluate next cycle.

  If the state is still unknown on the **third** consecutive cycle for the same head, escalate as
  HUMAN_REQUIRED (`needs-human`) with cause "reviews unreadable". It must not stay silent indefinitely.
- **APPROVE-eligibility** (overseer.md § Verdict events) gains a clause: neither reason is "only a
  human signature is missing".

### D8 — `hold-directive` output (REQ-CR-40; AM-5 resolves its internal contradiction)

The payload is additive. Every existing field keeps its value and type, **except `hold_active`, whose
meaning widens from "comment directive" to "any hold signal"**.

REQ-CR-40 asks both for "existing field names keep their meaning" and for "`hold_active` true if
either signal fires". Those cannot both hold. The safety property wins: a consumer reading
`hold_active` must never miss a CR.

New fields:
- `comment_hold_active` (bool): the old meaning;
- `cr_review_read`: `ok` or `unknown:<cause>`;
- `cr_hold_active`: `true`, `false` or `null`. It is `null` iff the read is unknown;
- `cr_outstanding`: a list of `{login, review_id, html_url, commit_id, head_current, trusted_human}`;
- `reviews_scanned` (int);
- `hold_sources`: a subset of `["comment", "cr", "cr-unknown"]`.

Rules:
- `hold_active = comment_hold_active OR cr_hold_active is not false`.
- **A reviews-read failure is exit 0** with `cr_review_read: unknown:…`, `hold_active: true` and
  `"cr-unknown"` in `hold_sources`. It is not exit 1. Unknown is an answer this primitive can state.
- A comments-read failure keeps today's exit 1.
- Dismissal (D7) keys on `"cr"` ∈ `hold_sources` or `comment_hold_active`. It never keys on
  `"cr-unknown"`.

---

## 3. Worker routing (#1662)

### D5 — How routing tells that the worker "acted" (the base-merge open question)

**Mechanism.** One read of `GET repos/{r}/pulls/{n}/commits?per_page=100&page=k`, with *k* ≤ 3, paginated
only while the previous page was full. Each commit object carries `parents[]`.

- **Why this endpoint.** It contains only commits on the head branch that are not on the base. Main's
  own commits, brought in by a base merge, are excluded. `compare/{cr}...{head}` would include them, and
  they are single-parent commits that would falsely read as "acted".
- **Rule.** Let *S* be the PR commit SHAs, and let *A* be the ancestors of the CR's `commit_id` within
  *S*, found by walking `parents` inside *S*.
  - **`ACTED`** iff some commit in *S* − *A* − {cr} has **exactly one parent**.
  - A merge commit (two or more parents) is never "acting", whichever branch it merged and even if it
    resolved conflicts. That is the conservative direction: the worker re-checks.
- **The CR commit is not in *S*** (history rewritten or rebased). The result is **`NOT_ACTED`**, with
  audit branch `history-rewritten`.
  - A rebase onto main is exactly the "moved the head without addressing the review" case of
    REQ-CR-13.
  - The worker re-checks the CR. The REQ-CR-20 notice, and ESC-4, bound the repeat.
- **`Unknown`.** Any of the following gives `Unknown`, which REQ-CR-14 routes as a blocking class:
  - a read failure;
  - a malformed page;
  - 250 or more commits. GitHub caps this list at 250, so a list that long may be silently truncated.
- **Cost.** The read is made only for a PR that has a trusted outstanding CR that is not head-current.
  That is +1 request in exactly the case that today produces the livelock, and 0 otherwise.
- **The proxy's limit (ESC-2, ruled):** a single-parent commit does not prove that the review was
  addressed. That is accepted:
  - the human's re-review is the real check;
  - merging stays held by D3, #757 and branch protection.

### D6 — The ESC-4 carrier (designed now, enabled by S4 only)

If ESC-4 is ruled yes, a CR is acted-on when **all** of the following hold:
- an issue comment authored by exactly the `--author` login (the worker App) exists;
- it contains `<!-- hos-worker-cr-noop pr=<n> cr=<id>[,<id>…] head=<sha40> -->`;
- its `cr` list includes that CR's id;
- its `head` equals the current head.

Comments from any other author are ignored. The read is made only for a trusted outstanding CR that is
not acted-on by D5, so it adds +1 request on that path only.

The notice itself (REQ-CR-20) does not depend on ESC-4. It is model-posted in S3 through the existing
`query_issues.sh --comments` / `post_comment.sh` path, under its own marker. The marker is distinct from
`hos-worker-merge-block`, so the two notices never suppress each other.

### D9 — Routing outcomes, per PR, after today's C2–C4 equivalents (REQ-CR-10..15)

| Determination (trusted CRs only) | Per-PR outcome | Aggregate token | Breaks the loop? |
|---|---|---|---|
| reviews `Unknown`, or acted-on `Unknown` | blocked, cause named | **`review-state-unknown`** (new) | no |
| ≥ 1 head-current outstanding CR, not covered by the ESC-4 notice | worker-actionable | `needs-fix` (unchanged token) | **yes** |
| ≥ 1 outstanding CR that is `NOT_ACTED` (base merge only, or history rewritten) | worker-actionable | `needs-fix` | **yes** |
| every outstanding CR is acted-on | waiting on the reviewer | **`awaiting-human-cr`** (new) | no |
| no outstanding trusted CR | today's APPROVED-count logic, unchanged | `needs-attention` / `awaiting-merge` | no (as today) |

**Aggregate precedence:** `needs-fix` / `needs-fix-bounce` (first in list order, as today) >
`review-state-unknown` > `awaiting-human-cr` > `needs-attention` > `awaiting-merge`.

**Directive texts** (exact bytes are for `technical-design`):
- `awaiting-human-cr`: `NEW WORK: BLOCKED`, then a sentence that names, for each such PR, the PR, the
  reviewer login and the review URL. It says the worker has pushed since that review, that the PR awaits
  that reviewer's re-review or dismissal, and that there is nothing to fix. Then STOP after Step 0.
  **It never says "not yet reviewed".**
- `review-state-unknown`: `NEW WORK: BLOCKED`, `reviews unreadable (<cause>)`, then "do not re-derive,
  do not fix". STOP after Step 0.
- `needs-fix` when it was triggered by a CR: today's text, plus the PR, the reviewer and the review URL.

**Security note (binding).**
- Values the CLI passes to bash are validated: login `^[A-Za-z0-9-]{1,39}(\[bot\])?$`, URL
  `^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+#pullrequestreview-[0-9]+$`, ids and
  SHAs as digits and hex.
- The review **body** never enters the cycle context or the directive. The worker reads it itself on
  `needs-fix`, as today.
- Bash parses the CLI's output with a `case` over known keys, never with `eval` or `source`. That is
  T3.0b §3.2's discipline.

**Audit (REQ-CR-15).** Each CR-grounds decision emits `_audit cycle-routing-cr` with:
- `pr`, `head`;
- `branch` ∈ {`head-current`, `acted-on`, `not-acted`, `history-rewritten`, `superseded`, `unknown`};
- `crs=<login>:<review_id>:<commit_id12>,…`;
- `untrusted=<count>`;
- `cause` when the branch is unknown.

### The CLI that bash calls in S3

```
python3 -m scripts.framework.review_state route --repo <o/r> --pr <n> --head <sha40> --author <login>
```

- It has its own `_run_gh` (`["gh","api",endpoint]`, 30 s timeout). That is the selector precedent;
  it does not use `github.py`'s retries.
- Reviews are read at `per_page=100` with ≤ 3 pages, then commits only per D5 (ESC-4's comments read
  arrives in S4).
- It prints `key=value` lines: `cr_route`, `branch`, `crs`, `untrusted`, `cause`.
- **Exit codes:** 0 is a determination, including `cr_route=unknown`; 2 is a usage error; anything else
  is a defect, which bash treats as `review-state-unknown` with cause `cli-exit-<rc>`.
- `--head` comes from the PR detail call that bash already makes. Add `head: .head.sha` to the `--jq`
  at `:1194`, which adds zero requests.
- **The CLI replaces only `:1225-1228`.** The APPROVED-count read at `:1229-1232` is unchanged, so S3
  does not perturb the `needs-attention` / `awaiting-merge` characterization. The duplicate reviews
  fetch is retired by T3.0b, which reads reviews once.

---

## 4. Sequencing against T3.0b (REQ-CR-60, ESC-6)

**Ruling: the routing half lands in `bin/hos-cron` ahead of T3.0b, with the logic in Python
(`review_state.py`), and T3.0b inherits it through Erratum 3 (§4.1). The CR change is not folded
into T3.0b.**

**Rationale:**
1. **T3.0b cannot ship this in v0.7.0.** Its coding is gated on #1925 (ARCH-ESC-1R). That issue has
   had no answer for 11 days and has been re-milestoned to v0.7.10. #1662 is a priority:high livelock
   that stalls the whole `needs-ai` queue. Folding it into T3.0b ties a bug fix to an unrelated policy
   question about the concurrency bound.
2. **REQ-CR-01 is satisfied by putting the definition in Python, not by its call site.** The bash change
   is a call-site swap of about 10 lines. The two-implementations risk the PM was guarding against (#550)
   comes from logic duplicated in bash and jq, and this ruling forbids that.
3. **T3.0b's design discipline still holds.** It characterizes whatever `bin/hos-cron` does at its
   baseline (§7.0 commit 1). After S3, that baseline *is* the new CR semantics. "Behavior preserved"
   then preserves the right behavior, and AC-8's "≤ today's requests" is measured against a today that
   already includes D5's conditional read.
4. **The split is safe in either order** (REQ-CR-61):
   - routing alone only re-labels blocked PRs; nothing merges as a result;
   - merge authority alone only adds holds.

### 4.1 Erratum 3 to ADR-1644 / T3.0b (binding on the T3.0b TD revision; T3.0b `coder` handoff now also requires it)

- **E14.** §2.5 **R** is replaced as follows:
  - reviews are parsed through `review_state.assemble_pages` (≤ 3 pages, following a page only when the
    previous one was full);
  - CR facts come from `review_state.outstanding_crs`, filtered to `trusted_human`;
  - "a full page containing a CR is a determination" is **withdrawn**;
  - `|| echo 0` was already gone. A read failure stays `reviews_ok=False`.
- **E15.** §2.6 **C5/C6** are replaced by D9's table. Each worker-actionable row keeps its stop
  (`break`) semantics, and the request budget gains D5's conditional commits read (and D6's comments
  read after S4).
  - A reviews-unknown or acted-unknown PR is **not** C8 `needs-attention`. It gets the new aggregate
    `review-state-unknown` (REQ-CR-14: never "not yet reviewed").
- **E16.** **C7/C8 for `awaiting-human-cr` PRs depends on ESC-2b:**
  - **if yes:** a PR whose outstanding trusted CRs are all acted-on, and which is otherwise C7-eligible
    (detail ok, reviews ok, not draft, no `hos-halt`), is **human-pending with carrier (c)
    `changes-requested`**;
  - **if no:** it is a blocking non-carrier that renders `awaiting-human-cr`.

  Either way, **a PR with any outstanding trusted CR is never carrier (b) `approved`.** The CR row
  precedes C7, so an approval from another reviewer cannot make it "awaiting merge".
- **E17.** Fixtures C5 and T-FC10 are revised to REQ-CR-50, and the revisions are listed explicitly in
  the PR (REQ-CR-53). REQUIREMENTS-1644-AMENDMENT-2 REQ-C24 item 1's "`CHANGES_REQUESTED` > 0 …
  unchanged" is superseded **for the CR rule only** by REQ-CR-10..14. pm-agent records this as an
  amendment note (AM-11).
- **E18.** The classifier imports `scripts.framework.review_state`, which is stdlib-only, so T3.0b's
  stdlib-only constraint holds. The routing CLI subcommand is retired from `bin/hos-cron` when T3.0b
  replaces the call site. The module's `route` subcommand may stay, as an operator diagnostic.

---

## 5. Slices (each ≤ 15 files)

| Slice | Content | Codable now? | Gated on |
|---|---|---|---|
| **S1** | `scripts/framework/review_state.py`: D1's pure API, D4, D5 and the `route` CLI. D6's `noop_notice_covers` is written but not called. Shared fixtures `tests/fixtures/review_state/*.json` covering REQ-CR-50 (a)–(j) plus (k)–(p) below. Unit and CLI tests. `framework_consumer_files.txt`. `SCRIPTS-INDEX.md` regenerated. No consumer is wired, so there is no behavior change. Protected surface. | **Yes** | — |
| **S2** | **#1660 merge authority.** `github.py` (D2: `assemble_pages`-based pagination, raise on truncation, `list_pull_reviews_snapshot`). `merge_authority.py` (D3). `merge_authority_cli.py hold-directive` (D8). `.claude/agents/overseer.md` §5/§6 (D7), authored by the top-level session. The library and the prose ship in **one PR**: D3's `None` default would otherwise turn every overseer evaluation into HUMAN_REQUIRED. Tests: the fixture parity run (REQ-CR-01), REQ-CR-51, the D8 envelope, the D2 truncation cases, and the existing `test_phase_b.py` matrix tests updated to pass a complete snapshot (named in the PR). DECISIONS.md entry. | **Yes**, after S1 merges | — |
| **S3** | **#1662 routing.** First commit: characterization tests of today's CR routing against unmodified `bin/hos-cron` (the T3.0b §7.0 discipline). Then: `bin/hos-cron` replaces `:1225-1228` with the CLI call and adds `head` to the `:1194` jq, the D9 tokens, directive texts and `_audit cycle-routing-cr`. `bootstrap/worker-cron-prompt.md` and `.claude/agents/worker.md` Step 1/R2 get the new tokens plus the REQ-CR-20 notice instruction (marker per D6, keyed on (PR, CR ids, head)); `worker.md` is authored by the top-level session. Tests: REQ-CR-50 through the CLI and the launcher, REQ-CR-52 (prompt contract), and REQ-CR-53 (the #867, #1350 and #1522/#1526 tests unchanged). | **Yes**, after S1 merges. Independent of S2. | — |
| **S4** | Routing consumes the ESC-4 notice as "acted" (D6): the conditional comments read, a new D9 row, and tests. | No | **ESC-4** |
| **T3.0b** (existing slice) | Built from the T3.0b TD as revised by Erratum 3 (§4.1). | No | **ARCH-ESC-1R (#1925)**, as today. **ESC-2b** fixes E16's branch. The TD revision text itself can be written now. |

**Additional fixtures (binding on S1; they extend REQ-CR-50):**
- **(k)** APPROVED, then CR, by the same human on the same head. Outstanding. Merge authority holds even
  though `_find_human_approval` matches the earlier approval.
- **(l)** CR on c1, APPROVED on c2, then a push to c3 that dismisses the approval. The approval is
  removed (AM-3), so the CR resurfaces as outstanding and acted-on. Routing gives `awaiting-human-cr`;
  merge authority gives HUMAN_REQUIRED.
- **(m)** CR from an untrusted association, and CR from a `[bot]`. Not routed, no hold, counted in
  `untrusted`.
- **(n)** The CR commit is absent from the PR commits (rewrite). `needs-fix`, branch `history-rewritten`.
- **(o)** 250 PR commits, or a failed commits read. `review-state-unknown`.
- **(p)** A `user: null` CR. Untrusted.

**Merge order:** S1 → (S2 ∥ S3) → S4 → T3.0b. S2 and S3 may merge in either order (REQ-CR-61). S1 may
be combined with S3 in one PR if the file count allows.

---

## 6. Requirement amendments (for pm-agent to record; the PM's file is not edited here)

- **AM-1 (REQ-CR-01 vs REQ-CR-10 / ESC-5).** The consumers agree on one outstanding-CR **list**, with
  each item tagged `trusted_human`. Each consumer applies its own filter. As written, the "consumers
  agree on the set" requirement and per-consumer reviewer scopes contradict each other.
- **AM-2 (REQ-CR-10).** "Any reviewer, human or bot" becomes **trusted human only** (D4). Untrusted
  CRs are audited, never routed.
- **AM-3 (Definitions, state-bearing).** `DISMISSED` is not state-bearing. A dismissal removes the
  dismissed review, and the reviewer's effective state falls back to their latest remaining APPROVED or
  CR. Fixture (f) still holds (a dismissed CR is not outstanding) unless an earlier, undismissed CR
  from the same reviewer exists. That CR is then outstanding, and it is visible with its URL.
- **AM-4 (REQ-CR-32 premise).** Restate the hazard. `reviews=None` cannot produce AUTO_MERGE today
  (#757), and AUTO_MERGE is currently unreachable (the PROPOSE_ONLY stub). The binding hazard is a
  **partial** list. The not-supplied/empty distinction is D3's typed `ReviewSnapshot`.
- **AM-5 (REQ-CR-40).** `hold_active` widens to "any hold signal". The comment-only meaning moves to
  `comment_hold_active`. "Existing field names keep their meaning" is waived for `hold_active` alone
  (D8).
- **AM-6 (Definitions, acted-on).** "A commit after the CR's `commit_id`" is defined by D5:
  - the PR-commits graph;
  - a single-parent commit not in the CR's ancestry;
  - merges never count;
  - a CR commit absent from the PR commits counts as `NOT_ACTED`;
  - 250 or more commits, or a failed read, is unknown.
- **AM-7 (REQ-CR-20).** The notice marker is
  `<!-- hos-worker-cr-noop pr=<n> cr=<ids> head=<sha40> -->`, authored by the worker App. There is one
  notice per (PR, head) listing every outstanding CR id it covers. A new CR id or a new head re-arms it.
- **AM-8 (REQ-CR-14 / REQ-CR-32).** An unknown review state is HUMAN_REQUIRED **without** `needs-human`
  on its first two cycles, and escalates on the third consecutive cycle on the same head (D7). Routing
  has its own token, `review-state-unknown`.
- **AM-9 (Sequencing text).** Correct the description of T3.0b. Its read failure is not fail-open:
  `reviews_ok=False` leads to C8, which blocks. Its defect is the "not yet reviewed" text, together
  with the any-CR and full-page rules.
- **AM-10 (REQ-CR-02, implementation surface).** `github.list_pull_reviews()` is in scope (D2). It
  silently truncates on a later-page 404 and on a malformed page.
- **AM-11 (REQUIREMENTS-1644-AMENDMENT-2).** Add an amendment note: REQ-C24 item 1's CR clause is
  superseded by REQ-CR-10..14 (E17). Whether item 2 gains carrier (c) waits for ESC-2b.

---

## 7. ESC dispositions

| ESC | Disposition | Ruling / recommended default | Gates |
|---|---|---|---|
| **ESC-1** (does a later review from the same reviewer clear a CR?) | **Ruled (architecture)** | Yes, for every consumer, via effective state. COMMENTED does not supersede. DISMISSED is removal (AM-3). This is GitHub's own semantics, and it loosens nothing: it is the human speaking again, and #757 still applies. | — |
| **ESC-2** (does commit-staleness clear a CR?) | **Split** | **(a) Routing: ruled.** An acted-on CR is `awaiting-human-cr`, not `needs-fix`. This fixes the bug: before T3.0b every open PR blocks new work anyway, so only the false fix instruction changes. **(b) Merge authority: ruled.** Staleness never clears a CR (D3). **(c) The acted-on proxy: ruled** (D5), with its limit accepted. | — |
| **ESC-2b** (does an `awaiting-human-cr` PR count as a human-pending carrier under the ARCH-ESC-1 bound?) | **Human** | **Recommended: yes**, as carrier (c), on a positive read only (E16). It is "reviewed and awaiting a human", which is what the bound measures. Saying yes releases new work while such PRs wait, so it is product-boundary (it relaxes #1198's serialization further). It should be asked together with #1925. | E16's branch of the T3.0b revision. It does not gate S1–S4. |
| **ESC-3** (does a demonstrably fixed CR still hold merge?) | **Ruled (architecture)** | Yes. Only the human's re-review or a dismissal clears it (D3, D7). This is the governing constraint, and it matches GitHub. | — |
| **ESC-4** (does the "nothing to fix" notice count as acting?) | **Human** | **Recommended: yes**, via D6's worker-authored, head-keyed marker. Saying yes lets the worker's own judgement move a human's CR out of the worker's queue (and, under ESC-2b yes, free a bound slot). That is a policy call, not a technical one. **If no:** the notice is visibility only, and a head-current CR with nothing fixable keeps routing `needs-fix` until the human acts. That livelock is visible but persists. | **S4** |
| **ESC-5** (whose CR holds merge?) | **Ruled (architecture)** | Trusted human (D4), which includes `HUMAN_REVIEWER`. This is broader than #902, so it is stricter, and it mirrors GitHub, where a write-access CR blocks merge under required reviews. Bot and untrusted CRs add no hold. Routing uses the same trust test (AM-2). | — |
| **ESC-6** (amending REQ-C24 item 1 and T3.0b §2.5; which vehicle?) | **Ruled (architecture)** | Bash first, Python logic (§4). Erratum 3 binds T3.0b. Item 1's "unchanged" was a behavior-preservation constraint, not part of the human's #1912 ruling, which set the bound. Superseding it for the CR rule is a bug fix within a filed bug. The only part that touches the human's ruling is the carrier question, which is ESC-2b. | — |

**Product-boundary check on the rulings above.**
- S2 adds holds that GitHub already enforces, and adds no label on unknown state.
- S3 changes only the text and action on already-blocked PRs.
- Neither changes cost, topology, retention, or the human's gate load in the direction of more merges.
- ESC-2b and ESC-4 do change user-visible queue behavior, so they stay with the human.

---

## 8. Affected sign-offs (startup-gap analysis)

- **Should this have been settled in the initial review?** For ADR-1644 / T3.0b, **partly, yes.**
  - T3.0b deliberately preserved "any CR ever ⇒ needs-fix" as today's behavior, and so preserved a
    livelock that was filed before T3.0b was designed (#1662 predates 2026-10-02).
  - That is a `startup-artifact-gap` in T3.0b's TD and in ADR-1644 Erratum 2. **Recommended:** the
    orchestrator files one or annotates one. Per this cycle's constraints, the architect files nothing.
- **These sign-offs stand:**
  - ADR-1644 Erratum 2's E6–E13, and the T3.0b TD apart from §2.5 R, §2.6 C5/C6/C8-for-CR, and fixtures
    C5 and T-FC10;
  - #1357's `hold-directive` envelope, extended additively except for `hold_active` (AM-5), which its
    reviewers must re-check in S2;
  - #902, #757 and #1251, all unchanged.
- **These are re-opened:**
  - the T3.0b TD's architect approval (round 1, APPROVED_WITH_EDITS), **for the rows E14–E17 name
    only**. No T3.0b code exists, so no approved code is orphaned;
  - REQUIREMENTS-1644-AMENDMENT-2 REQ-C24 item 1, for its CR clause (AM-11).
- **Not orphaned:** no CR-semantics code has been built or approved.

---

## 9. Follow-ups (not in these slices)

- **F-1.** `require_human_approval.py` (the `require-human-approval` CI check) does not consult
  outstanding CRs. GitHub enforces write-access CRs natively, so this is defense-in-depth only. File
  it if no existing issue covers it.
- **F-2.** T3.7a's deterministic finalize step should absorb the REQ-CR-20 notice, as E13 already
  requires for `hos-worker-merge-block`.
- **F-3.** An overseer `decide` subcommand on `merge_authority.sh`, so that the matrix itself is a shell
  command and not a prose Python call. This is the #1357 lesson. Until it exists, D3's fail-closed
  default is what makes the CR guard robust to the prose drifting.
