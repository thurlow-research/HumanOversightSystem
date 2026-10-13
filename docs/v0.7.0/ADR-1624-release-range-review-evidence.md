# ADR-1624 — Release-range review-evidence sweep (REQ-B5, re-homing G-e)

Issue: #1624 (bug, process-gap, priority:high, milestone v0.7.0). Parent: #1340.
Siblings: #1622 (REQ-B2/B3), #1623 (REQ-B4), #1625 (REQ-A13).
Author: architect. Date: 2026-10-13. Baseline: `0a2811d4f`.
Input: `docs/v0.7.0/REQUIREMENTS-1624-release-range-review-evidence.md` (pm-agent, committed at `0a2811d4f`).
Coordinates with: `docs/v0.7.0/ADR-1340-release-panel.md` (AD-2, AD-7, AD-9),
`docs/v0.7.0/ADR-1660-1662-changes-requested-semantics.md` (D1, D2, D4, Amendment A1) and
`docs/v0.7.0/TECHNICAL-DESIGN-1660-1662-S1-review-state.md` (§2.3–§2.5, §3.3).

**Verdict on the requirements: APPROVED_WITH_AMENDMENTS.** The goal is feasible, and the product framing is right: an aggregate sweep built only from durable GitHub state, blocking unless each change is evidenced or dispositioned by a human. Eleven amendments (AM-1..AM-11, §12) correct four factual premises and tighten the predicate. Three of those premises would have produced a gate that passes wrongly or never passes:
- `derive_range` refuses exactly the ranges this gate must flag (AF-1);
- the "reuse" predicates do not pin head or merge time (AF-2);
- a disposition comment can be edited by a principal other than its author (AF-4).

**Status: Accepted (technical).** ESC-1..ESC-6 stay with the human (§13). ARCH-ESC-1..3 are added. The slices that can be coded before any human answer are S0, S1 and S2 (§10).

---

## 0. Verification of the pm-agent's claims (re-derived at `0a2811d4f`)

| # | Claim | Verified | Consequence |
|---|---|---|---|
| 1 | `2abe9919b` removed the register read, so G-e is unchecked | **Yes.** `2abe9919b` (2026-09-14) is on `origin/main`. The overseer's section `.claude/agents/overseer.md:170-215` now runs only step discovery, then present/tier/finding/coverage checks over `signoffs/validators/step{N}/summary.json` (`:188-195`). No line reads a register or any per-role evidence. | F1 stands. The REQ-B8 "no window" ordering is already overtaken. The window is acknowledged under ESC-1(b), not closed by this design. |
| 2 | `release_panel_logic.derive_range` can be reused | **Partly. See AF-1.** `derive_range` (`release_panel_logic.py:183-233`) is the hardened derivation: SHALLOW → NO_TAG → base/head unresolvable → **NO_CONTENT after the panel exclusion list** (`:208-220`). The first three steps are exactly what this gate needs. The fourth is wrong for it. | AD-2 extracts the first three steps into a shared function. The sweep never applies panel exclusions. |
| 3 | `github.py` has no commit→PR helper, and `list_pulls` is single-page | **Yes.** No `commits/{sha}/pulls` or `associatedPullRequests` read exists anywhere in `scripts/`, `bootstrap/` or `bin/`. `list_pulls` (`github.py:192-213`) makes one `_run_gh` call with no `per_page` (30 by default). **Also:** `list_pull_reviews` (`:348-372`) and `list_issue_comments` (`:215-238`) share ADR-1660 AM-10's defect. `_run_gh` returns `None` on a 404 (`:137-138`), the loop reads `if not batch: break`, so a 404 on page *k* > 1 returns a short list. Neither has a page cap or a type check. | Neither is usable on this gate's correctness path as it stands (AD-4). |
| 4 | Review-object shape since #1657 and identity config | **Yes.** Since `f6a1aceb3` (#1849, 2026-09-24), every overseer disposition posts exactly one review via `pr_review.sh submit-verdict --event approve\|comment` (`overseer.md:570-618`). `REQUEST_CHANGES` is unavailable to the overseer. `approve` is posted **only** when all five conditions at `:582-591` hold. The second condition is "tier ≤ `OVERSEER_CEILING`", and protected-surface/CODEOWNERS PRs that are sound on the merits **do** get `approve` (`:587-590`, `:603-608`). Identities: `machine-accounts.env:30` `BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"`, `:34` `BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"`, `:39` `BOT_ACCOUNTS` (worker, overseer, human-proxy, Copilot), `:56` `HUMAN_REVIEWER="ScottThurlow"`. | **AF-7:** at or below the ceiling, an overseer COMMENT now means a merits-type blocker, not "a human signature is missing". That changes the reading of E-OVERSEER+HUMAN (ARCH-ESC-2). |
| 5 | worker.md NG3b R2 table and R3 quoting | **Yes.** R2 table `worker.md:647-653`, PATCH promotion `:654-655` ("all five suites"). R1.9 check 3 anchors suites by script path (`:584-600`) and forces a fresh run after any non-`BOT_ACCOUNTS` comment (`:602-606`). R3 line format `- <suite-script-path>: PASS\|FAIL (exit <code>) at <UTC timestamp>` plus a fenced **first-line** excerpt (`:663-666`). The table has no argument column. | The suite needs one stable path and a fixed argument set (`--issue <n>`). Line 1 must carry the whole enumeration (AD-6). R3 maps exits 1 and 2 to `FAIL`, so the INDETERMINATE/FLAGGED distinction has to live on line 1. |
| 6 | `require_overseer_approval.py` (#621) semantics | **Yes, with a gap the requirements gloss over.** `overseer_has_approved` (`:120-133`) is "any APPROVED by the overseer login". It has **no head-SHA pin and no time pin** and relies on `dismiss_stale_reviews` (docstring `:123-126`). The #1426 bypass (`:180-202`) requires: the overseer posted any review, **and the recomputed tier exceeds `OVERSEER_CEILING`**, and `human_approval_present` (any non-bot approver, not specifically `HUMAN_REVIEWER`). | The gate's predicate is neither head-pinned nor merge-time-pinned. **R4's E-OVERSEER+HUMAN has no tier condition**, so it is broader than #1426 on tier and narrower on the human. That is a policy difference, not a reuse (ARCH-ESC-2). |
| 7 | Reuse ADR-1660's "latest decisive review per reviewer" | **Yes. It is binding here.** `scripts/framework/review_state.py` is **not yet on main**. Its ADR and S1 TD are on main (`27178858d`), and S1 is approved for coding. `effective_states` (TD §2.5) is the system's single definition of a reviewer's decisive state. `assemble_pages` (§2.4) is its single completeness rule. `resolve_machine_accounts` (§3.3) is its single identity resolver. | AD-5 builds "approved at final head" on these, and does not use `_find_human_approval` / `overseer_has_approved` (AF-2). The sweep's logic slice therefore depends on ADR-1660 S1 (§10, S0). |

Other premises re-checked:
- **F2** is confirmed: `cut_release.sh:200` passes `--manifest` only if `contract/step-manifest.yaml` exists, and `contract/` holds only the template.
- **F4** is confirmed: `overseer.md:152-164`.
- **F5** is confirmed and measured: `v0.6.0..origin/main` = **428 commits, 250 first-parent, 96 merges**, and the clone is not shallow. `ad16c85b1`, `56aafb02c` and `bbeef2617` are single-parent and bot-authored and bot-committed. The first two are an audit-log commit and its exact revert.

### Architect's findings (these change the design)

**AF-1 (CRITICAL): `derive_range` refuses the very ranges this gate must flag.** Its NO_CONTENT step diffs `base..head` and subtracts `release_panel_exclusions.txt`, which excludes `audit/log/**` (ADR-1340 AD-3). There are two failure modes:
- **(a)** A release whose only post-tag changes are bot audit-log commits gives NO_CONTENT (exit 2, "refusal"). Those are precisely ESC-4's unattributed commits, which this gate exists to flag.
- **(b)** A range whose commits net to zero diff, such as `ad16c85b1` followed by its revert `56aafb02c`, has commits but no files.

For this gate, "empty" means **zero commits**, never zero files. The panel's exclusions are a review-*content* policy, and applying them to review-*evidence* would exempt bot pushes from the gate by path. ESC-4's recommended default explicitly refuses that ("no path-based auto-exemption").

**AF-2 (HIGH): the predicates R13 names cannot express R4.**
- `overseer_has_approved` has no head or time pin (row 6). After a merge `dismiss_stale_reviews` never fires again, and the setting itself can differ across the range's history. So an approval at a non-final head that was never dismissed would read as evidence.
- `_find_human_approval` (`merge_authority.py:44-64`) returns the **first** APPROVED. ADR-1660 fixture (k) is APPROVED-then-CHANGES_REQUESTED by the same human on the same head; `_find_human_approval` reads that as approved.
- R4's "`submitted_at <= merged_at`" cannot be applied to either predicate without a pre-filter, and filtering a `ReviewList` is not representable under the ADR-1660 S1 type discipline (TD §2.3: `ReviewList` is constructed only by `_assemble`).

AD-5 and erratum E-1624-2 resolve this.

**AF-3 (HIGH): there is no completeness-safe reader for three of the four lists this gate reads.** These are commit→PR association, PR reviews and issue comments. All three existing paginators silently truncate (row 3). R9 forbids a partial read from producing a verdict. ADR-1660 D1.1 has already ruled that `assemble_pages` is *the* completeness rule. A third paginator would violate that ruling (and D41).

**AF-4 (HIGH, ESC-2 option A): an issue comment's author is not the author of its current text.** Under GitHub's permission model, an account with write access to issues can edit *another user's* issue comment. In this repo that includes collaborators and, under its `issues:write` permission, the worker App. `user.login` on the comment object stays the original author. So "a comment by `HUMAN_REVIEWER`" whose body a bot appended `Disposition: #1234` to reads as a human disposition. R8.1's "no bot can disposition" is then false as implemented. AD-7 closes this with the unedited rule.

**AF-5 (MEDIUM, ESC-2): options (B) and (C) cannot disposition an unattributed commit.** An unattributed commit has no PR, so there is no PR to review (B) or to label (C). Under (B) or (C), every ESC-4 commit would need a second mechanism, which in practice is (A). The human should see this before choosing.

**AF-6 (MEDIUM): call cost and wall clock.** A naive per-commit association read costs 428 calls. Adding a PR read and a reviews read for about 150 PRs gives about 730 sequential `gh api` subprocesses, at an estimated 0.4–1.0 s each. That is 5–12 minutes inside one worker Bash call, whose ceiling is 600 s, and it uses about 15% of the worker App's 5,000/h budget on every run. AD-3 cuts the association reads to first-parent commits (250) without losing coverage. AD-4 bounds concurrency and wall clock.

**AF-7 (MEDIUM):** see row 4. Since #1657 Part 2, a protected-surface PR at or below the ceiling that is sound on the merits gets an overseer `approve`. E-OVERSEER+HUMAN without a tier condition therefore also admits "the overseer COMMENTED on the merits, and the human approved and merged over it". That may well be the right policy (overseer.md:154: "human merge authority supersedes"), but it is policy, so it goes to ARCH-ESC-2.

**AF-8 (LOW): exit-code collision.** An uncaught Python exception exits **1**, which is R10's FLAGGED code. A crash would then be reported as "here is the flagged list", and the list it shows is whatever was printed before the crash. AD-6 closes this.

---

## 1. Module layout

### AD-1: one Python module carries all the logic, behind a thin shell wrapper at a stable path

- **`scripts/oversight/release_review_evidence.py`** holds all of the decision logic and has two layers:
  - **Pure core**: `classify(range_facts, pr_facts, accounts, dispositions) -> SweepResult` and `render(SweepResult) -> (lines, exit_code)`. It does no I/O.
  - **Collector**: `collect(...)`, which reads git through AD-2's seam and GitHub through AD-4's surface, and builds the facts the core consumes.
  - **CLI**: `main(argv)`.

  The module is not on the protected-surface list today (ARCH-ESC-3).
- **`scripts/oversight/release_review_evidence.sh`** is the **R2 path**. It is thin: resolve `REPO_ROOT`, `cd` there, `exec python3 -m scripts.oversight.release_review_evidence "$@"`, and map any exit code outside {0,1,2} to 2. It contains no logic, loops or `gh` calls (shell→Python policy, SPEC-333).
  - A `.sh` path is chosen because every existing R2 row is a `.sh` path, and the sandbox allowlists `bash scripts/...`.
  - Fixed invocation: `bash scripts/oversight/release_review_evidence.sh --issue <release-request issue #>`.
  - `--issue` is constant for a given release request, so R1.9's anchor walk stays unambiguous (ADR-1340 §1 item 4).
- **No new file under `scripts/framework/`** apart from the two `review_state.py` errata (§5). No stamp, register or cache file anywhere (R7).
- **Rejected: adding a mode to `run_release_panel.sh --verify`.** The two answer different questions with different evidence and different exit semantics. R1.9 anchors **by path**, so a shared path would merge two suites' carry-forward state.

## 2. Range and attribution

### AD-2: range derivation is shared up to base and head. "Empty" means zero commits.

- **Extraction (behaviour-preserving).** Lift `derive_range`'s first three steps (`release_panel_logic.py:184-206`) into `derive_base_head(*, cwd) -> RangeResult`. It returns `state ∈ {OK, SHALLOW, NO_TAG}` with base_ref, base_sha and head_sha, the existing reason and remediation text, and the same precedence.
  - `derive_range` calls it and then does its file and exclusion step unchanged.
  - The existing `test_release_panel_logic.py` derive_range tests (12 references) must pass unmodified. That is the byte-identity proof.
- **The sweep calls `derive_base_head` only.** It never loads `release_panel_exclusions.txt` (AF-1).
- **Its own emptiness check.** `git rev-list --count base..head == 0` gives refusal `NO_COMMITS` (exit 2). A diff that nets to zero with commits present is **not** empty.
- **One git seam.** Every git read the sweep makes goes through `release_panel_logic.run_git`, called by module attribute (`rpl.run_git(...)`) so one monkeypatch covers both modules. The calls are `rev-list --first-parent --parents`, `rev-list --count`, `rev-list <M> ^<M^1> ^<base>` and `log -1 --format=%s`. There is no second subprocess site.
- **Head** is `git rev-parse HEAD` of the clone that runs R2, the same SHA R3/R4 record as `Release candidate SHA:`. A local commit not on the remote default branch has no PR association, so it is flagged UNATTRIBUTED. That is correct.

### AD-3: first-parent attribution with local, total accounting (amends R2 by mechanism, not by coverage)

1. **Walk** `git rev-list --first-parent --parents base..head`, giving the first-parent set *F* (250 commits on the measured range).
2. **For each c ∈ F**, read the commit→PR association (AD-4). Keep PRs with `merged_at` set and `base.ref == default_branch`. `default_branch` is read once from `get_repo()`, never hard-coded. Call the kept set P(c).
   - **P(c) empty** → `UNATTRIBUTED(c)`. It is never reclassified from the commit message (R2).
   - **Fields.** For every distinct PR p, `get_pull(p)` is authoritative for `merged_at`, `merged_by.login`, `head.sha`, `base.ref` and `merge_commit_sha`. The association list contributes **PR numbers only**. One cached read per PR.
3. **Binding rules.** A commit that fails either rule is flagged `MERGE_UNBOUND(c)`.
   - **B1:** if c has exactly 2 parents, some p ∈ P(c) must satisfy `p.merge_commit_sha == c` **and** `c^2 == p.head.sha`. This ties the merge to the exact head that was reviewed.
   - **B2:** for every p ∈ P(c), `p.merge_commit_sha ∈ F`.
   - A commit with more than 2 parents (an octopus merge) is always `MERGE_UNBOUND`.
4. **Non-first-parent commits** are those reachable only through a first-parent merge M. Each one is accounted to M **locally**: `rev-list M ^M^1 ^base` minus M. If M is PR-attributed and passes B1, those commits are in the reviewed diff of `p.head.sha`, so p's evidence covers them. If M is UNATTRIBUTED or MERGE_UNBOUND, they are listed under M's flag with a count.
5. **Totality (R9).** |F| + Σ |covered(M)| must equal `rev-list --count base..head`, and every c ∈ F must carry exactly one class. Any mismatch gives `INDETERMINATE: commit-accounting-mismatch`.
6. Every p ∈ P(c) must be evidenced (R2's "attributed to each one"), so a commit with several PRs is flagged unless all of them are evidenced.

**Why first-parent (AF-6), and why this is not weaker.** A second-parent commit Y is reachable only through a merge M. If M is bound by B1 to p's reviewed head, Y lies in `merge-base..p.head.sha`, which is p's reviewed diff. Querying Y's association adds API cost and no evidence. If M is not bound, M is flagged and Y is shown under it. B1 is *stronger* than per-commit association: it proves the merge took exactly the reviewed head, which per-commit association never checks.

**Residual, stated.** For squash and rebase commits, attribution rests on GitHub's association for that commit plus B2. An account able to push directly to the default branch (an admin bypass) is outside what any review-evidence gate can bound. ESC-4's flagging covers its *unattributed* pushes. AD-11's out-of-band demonstration run must confirm that each of the four F5 shapes attributes as expected against the live API before arming. If B2 fails on any legitimate shape, the TD returns to the architect; it must not weaken B2 on its own authority.

## 3. GitHub read surface

### AD-4: endpoints, completeness, failure and identity

| Read | Endpoint | Pages | Calls (measured range) |
|---|---|---|---|
| default branch | `GET /repos/{o}/{r}` (`github.get_repo`) | 1 | 1 |
| commit→PR | `GET /repos/{o}/{r}/commits/{sha}/pulls?per_page=100&page=k`, **new** `github.list_commit_pulls` | ≤ 2 | ≈ 250 |
| PR object | `GET /repos/{o}/{r}/pulls/{n}` (`github.get_pull`) | 1 | ≈ distinct PRs (~150) |
| reviews | `GET …/pulls/{n}/reviews?per_page=100&page=k` | ≤ 10 (ADR-1660 merge-authority cap) | ≈ distinct PRs |
| dispositions (ESC-2 = A) | `GET …/issues/{n}/comments?per_page=100&page=k` | ≤ 10 | 1–2 |

**Not read: check runs, the audit trail, the Search API and GraphQL.**
- Check runs are omitted in v1 (AM-6). The audit trail is excluded by F3. The Search API is forbidden by `github.py`'s header.
- GraphQL `associatedPullRequests` would batch the association reads, but it would add a second transport and parser to `github.py` and save about 4 minutes. Rejected for v1. It is an optimisation follow-up if AD-4's budget proves tight (FU-3).

**Completeness: one rule, not a third paginator (AF-3).**
- A new `github.fetch_raw_pages(endpoint, per_page, max_pages) -> list[page | review_state.FetchFailure]` implements ADR-1660 TD §3.4's fetcher contract on `_run_gh`, which keeps its retries, backoff and rate-limit handling.
  - A `None` (404) on any page becomes `FetchFailure`.
  - It fetches page *k*+1 only after a full page *k*.
- Pages are assembled **only** by `review_state`'s completeness rule:
  - `assemble_pages` for reviews;
  - E-1624-1's public generic assembler for association lists and comments.
- ADR-1660 S2's D2 rebuild of `list_pull_reviews` must reuse `fetch_raw_pages`. That is a coordination note; both slices must not each write a fetcher.
- `list_pulls`, `list_pull_reviews` (pre-S2) and `list_issue_comments` are **not** called by this module.
- An item check failure is `unparseable`:
  - association items: `number` int > 0; `merged_at` str|None; `base.ref` str.
  - comments: `id` int; `user.login` str; `user.type` str; `created_at` str; `updated_at` str; `body` str.

**Failure means INDETERMINATE, never a shorter list (R9).** Each of the following ends the run with exit 2 and line 1 `INDETERMINATE: <cause> (<call> <subject>)`. **No** class list is printed.
- `GitHubError` or `RateLimitError` from `_run_gh` (including a 401 from an expired token: `_run_gh` raises on a non-zero `gh` exit, which is the right direction);
- any assembler `Unknown`;
- a PR missing `merged_at`, `head.sha`, `base.ref` or `merge_commit_sha`;
- a non-PENDING review missing `commit_id`, `user`, `state` or a parseable `submitted_at` (E-1624-2);
- unresolved identities (AD-5);
- accounting mismatch (AD-3);
- budget exhaustion.

The first failure wins. Its cause token and call are named, and the run makes no further GitHub calls.

**Concurrency and budget (AF-6).**
- Reads run in a bounded `ThreadPoolExecutor` with `MAX_CONCURRENCY = 4`, a module constant.
- GitHub's secondary rate limit surfaces as 403 → `RateLimitError` → INDETERMINATE. It is retried next cycle and never slept through beyond `_run_gh`'s own retries.
- A wall-clock budget `WALL_CLOCK_BUDGET_S = 420` (below the 600 s Bash ceiling, leaving headroom for R3) gives `INDETERMINATE: budget-exhausted (<n>/<m> reads complete)`.
- Results are assembled in deterministic order regardless of completion order.

**Auth identity.**
- The sweep only reads. It uses whatever `gh` is authenticated as, which in a worker cycle is the worker App installation token (`GH_TOKEN`).
- It never mints a token, never writes to GitHub, and never posts a comment. R3 does the posting.
- The repo slug comes from `merge_config.resolve_repo_slug(repo_root)` (the `origin` remote), with an optional validated `--repo`. It is not re-parsed here.

## 4. Evidence predicate

### AD-5: "approved at final head, before merge" is computed from ADR-1660's effective state, as of `merged_at`

**Identities.**
- `review_state.resolve_machine_accounts(repo_root)` supplies `HUMAN_REVIEWER` and `BOT_ACCOUNTS`.
- `BOT_OVERSEER_USERNAME` comes from `require_tier_ceiling.load_env` on the same file. That is the parser `resolve_machine_accounts` uses. No third env parser (ADR-1357 AD-9).
- Any of the three unresolved or empty → `INDETERMINATE: identity-unresolved:<key>` (R9).
- Logins are compared case-insensitively.

**Per merged PR p**, with `h = p.head.sha` and `t = p.merged_at`:
1. `R = assemble_pages(fetch_raw_pages(reviews of p))`. An `Unknown` result → INDETERMINATE.
2. `R_t = review_state.as_of(R, t)` (E-1624-2). This drops PENDING reviews and every review submitted after `t`. A non-PENDING review with an unparseable `submitted_at` → INDETERMINATE.
3. `S = effective_states(R_t)`. That is the latest decisive APPROVED or CHANGES_REQUESTED per reviewer, with DISMISSED treated as removal (ADR-1660 AM-3).

**E-OVERSEER:** `S[overseer]` exists, its state is APPROVED, and its deciding review's `commit_id == h`.

**E-OVERSEER+HUMAN** (R4 as written, pending ARCH-ESC-2) requires both legs:
- **Overseer leg:** some review in `R_t` by the overseer login, in any state other than PENDING, has `commit_id == h`.
- **Human leg:** `S[HUMAN_REVIEWER]` exists, its state is APPROVED, its deciding review's `commit_id == h`, and `require_human_approval.is_bot_reviewer(login, user.type, BOT_ACCOUNTS)` is false. That rejects `scottthurlow-claude[bot]` three ways (R5, AC-7).

**Effective state, not "any APPROVED".** An APPROVED followed by a CHANGES_REQUESTED from the same human at head before merge is **not** human approval (ADR-1660 fixture (k)). An overseer approval at a non-final head that was never dismissed is not evidence, because its deciding review's `commit_id ≠ h`.

**Outstanding CR at merge (ARCH-ESC-1).** Suppose some `review_state.outstanding_crs(R_t, head_sha=h)` item has `holds_merge` true. Then p merged over a write-access reviewer's standing objection. **Interim value: flag the PR as `MERGED_OVER_CR`**, even when it is otherwise evidenced. The value is the constant `FLAG_MERGED_OVER_CR = True`. The gate is unarmed until S4, so the interim value's only effect is on the demonstration run.

**Never evidence (R5, R6).** Comment bodies, PR descriptions, trailers, labels, the head commit's author, check-run conclusions and the audit trail. The pure core's inputs contain **no** check-run or audit fields, so AC-6 and AC-8 are true by construction, and a test asserts the signature.

**Classes** (exactly one per flagged item; deterministic order on line 1):
- for PRs: `UNEVIDENCED`, `HUMAN_MERGE_NO_OVERSEER` (ESC-3: no overseer review at all in `R_t`, and `merged_by.login == HUMAN_REVIEWER`), `MERGED_OVER_CR`;
- for SHAs: `UNATTRIBUTED`, `MERGE_UNBOUND`;
- for both: `DISPOSITIONED` (counted on line 1 and itemised below).

If both `UNEVIDENCED` and `HUMAN_MERGE_NO_OVERSEER` apply, the more specific class `HUMAN_MERGE_NO_OVERSEER` wins.

## 5. Errata to ADR-1660 / S1 TD (binding on whoever codes `review_state.py`)

**E-1624-1: the completeness rule becomes reusable.**
- TD §2.4's private `_assemble(pages, per_page, max_pages, prefix, validate_item, id_of)` gets a public generic entry point. It returns a validated tuple, or `Unknown` with cause `read-failed`, `unparseable` or `page-cap`, combined with a caller-supplied prefix from a closed set extended by `pulls` and `comments`.
- T-ST8's cause-token set gains `pulls-read-failed`, `pulls-unparseable`, `pulls-page-cap`, `comments-read-failed`, `comments-unparseable` and `comments-page-cap`.
- `assemble_pages` and `assemble_commit_pages` stay byte-identical in behaviour, and the T-AP tests are unchanged.
- `technical-design` names the function.

**E-1624-2: `as_of(reviews: ReviewList, cutoff: datetime) -> ReviewList | Unknown`.**
- It drops PENDING reviews and every review whose aware `submitted_at` is later than `cutoff`.
- A non-PENDING review whose `submitted_at` is missing, unparseable or naive gives `Unknown("reviews-unparseable")`.
- T-ST6 is amended: `ReviewList(` is constructed only inside `_assemble` **and `as_of`**.

**Rationale.** Without E-1624-1 this gate needs a third paginator (AF-3). Without E-1624-2, R4's merge-time cutoff cannot be applied to a `ReviewList` without breaking ADR-1660's "a partial list is unrepresentable" property.

**Applying the errata.**
- **If ADR-1660 S1 is not yet coded,** its coder includes both errata. That costs one function and about 6 tests, with no change to S1's behaviour.
- **If S1 has merged,** this issue's S0 adds them. `review_state.py` is in `scripts/framework/**`, so CODEOWNERS human approval is required either way.

**Affected ADR-1660 sign-offs.** The S1 TD's round-1 approval stands for every existing function. Only the two additions need review, and no code exists to orphan.

## 6. Output contract

### AD-6: line 1 carries everything R3 can quote. Exit codes are disjoint and crash-safe.

**Line 1** is a single line with no embedded newline. It contains identifiers and counts only, never a title or commit subject, because those are attacker-influenced text that the worker model reads.
```
RELEASE-REVIEW-EVIDENCE PASS: 152 PRs evidenced, 0 flagged, 3 dispositioned (base v0.6.0@<sha12>, head <sha12>)
RELEASE-REVIEW-EVIDENCE FLAGGED: UNEVIDENCED: #1234, #1240; HUMAN_MERGE_NO_OVERSEER: #1301; MERGED_OVER_CR: #1310; UNATTRIBUTED: ad16c85b1c3e, 56aafb02c9d1; MERGE_UNBOUND: none; DISPOSITIONED: 2 (base v0.6.0@<sha12>, head <sha12>)
RELEASE-REVIEW-EVIDENCE INDETERMINATE: reviews-page-cap (reviews #1402) — no evidence verdict produced
RELEASE-REVIEW-EVIDENCE REFUSED: range-derivation-failed: shallow clone — remediation: git fetch --unshallow --tags
```

- Every flagged identifier appears, sorted: PRs ascending, SHAs in range order. There is no length cap and no "and N more" (AC-14).
- SHAs on line 1 are 12 characters.
- **Later lines** hold:
  - the full table, one line per flagged or dispositioned item: class, identifier with the **full 40-hex SHA** (needed by R8.2), a reason token, a sanitised subject or title (control characters and newlines stripped, at most 80 characters, quoted), and for dispositioned items the record URL;
  - the accounting line `commits: <total> (first-parent <|F|>, covered-by-merge <n>)`;
  - the identities used.
- **Exit codes:** `0` PASS; `1` FLAGGED; `2` INDETERMINATE, REFUSED or a usage error.
  - `main` wraps everything in `try/except BaseException` and turns any unexpected exception into exit 2 with an `INDETERMINATE: internal-error:<ExceptionType>` line 1. `KeyboardInterrupt` and `SystemExit` with codes 0, 1 or 2 pass through.
  - The wrapper maps any other code to 2. An uncaught crash can never present as FLAGGED (AF-8).
- **stderr** carries diagnostics only. R3 quotes stdout line 1.

## 7. Disposition read path

### AD-7: dispositions are a pluggable input to the pure core. The default shape is (A) with the unedited rule.

- **The core takes the dispositions as plain data:** `dispositions: Mapping[item_id, DispositionRecord(url, author, created_at)]`.
- **Exactly one reader is wired, selected by a module constant** `DISPOSITION_SOURCE ∈ {"none", "issue-comment", "post-merge-review", "label-event"}`.
  - **S2 ships `"none"`.** No item is ever dispositioned, so every flag blocks. That is fail-safe and inert until arming.
  - **S3 wires the ruled source.**

**Under ESC-2 = (A), the recommended default:**
- **Source.** Comments on the `--issue` release-request issue, read with strict pagination (AD-4).
- **Author.** A comment counts only if all of these hold:
  - `user.login` equals `HUMAN_REVIEWER` (case-insensitive);
  - `user.type == "User"`;
  - `is_bot_reviewer(...)` is false.
- **Unedited rule (AF-4).** A comment whose `updated_at != created_at` is **not honoured**. It is listed on a later output line as `DISPOSITION_IGNORED_EDITED <url>`, and the human re-posts. Edit history is not readable over REST, and a GraphQL `userContentEdits` read is rejected as a second transport.
- **Grammar.** Each line that matches `^Disposition:\s+(?P<items>…)\s+(—|--)\s+(?P<reason>\S.*)$` counts. Items are a comma-separated list of `#<digits>` or a **40-hex** SHA. Short SHAs, ranges, wildcards and "all" do not match, so the line is ignored and listed as `DISPOSITION_IGNORED_MALFORMED <url>` (R8.2). An empty reason does not match.
- **Scope.** A record dispositions an item only if it names that item exactly. One record may list many items.
- **Visibility.** A dispositioned item stays visible as DISPOSITIONED (R8.4).
- **Scope across releases.** A disposition naturally does not carry across releases, because it lives on that release's request issue (R8.5).
- **Interaction with R1.9.** A disposition comment is a non-`BOT_ACCOUNTS` comment, so R1.9 check 3 forces a fresh run. No R1.9 change is needed.

**Under (B):** the per-PR reviews are already read. A `HUMAN_REVIEWER` APPROVED review with `submitted_at > merged_at` dispositions that PR. It is never used as R4 evidence: `as_of` drops it before `effective_states`. That costs 0 extra calls. (A) is still needed for SHAs (AF-5).

**Under (C):** one `GET /issues/{n}/events` read per flagged PR. The `labeled` event's `actor.login` must equal `HUMAN_REVIEWER`, and a later `unlabeled` event revokes it. (A) is still needed for SHAs (AF-5).

## 8. ESC-3..6 interim defaults

### AD-8: ESC-3..6 interim defaults are isolated constants

| Constant | Interim (= pm-agent's recommended default) | Effect of the other answer |
|---|---|---|
| `CLASS_HUMAN_MERGE_NO_OVERSEER = True` (ESC-3) | flag under its own class | `False` → a third evidence class: human APPROVED at head before merge, with no overseer review. One branch in `classify`. |
| `UNATTRIBUTED_EXEMPT_GLOBS = ()` (ESC-4) | no exemptions | ruled globs, read from a **committed, hashed** list. Not recommended. |
| check runs (ESC-5) | not read (AM-6) | a separate reader plus the attribution checks (GitHub Actions App, completed before `merged_at`). That is a new slice. |
| `LEGACY_COMMENT_VERDICT_BEFORE = None` (ESC-6) | no legacy class | the cut-over SHA `f6a1aceb3`'s merge time. Accept an overseer-App-authored **unedited** comment carrying `**Decision: …**` on PRs merged before it. That adds a comments read per affected PR. |
| `FLAG_MERGED_OVER_CR = True` (ARCH-ESC-1) | flag | `False` → informational column |
| `E_OVERSEER_HUMAN_REQUIRES_ABOVE_CEILING = False` (ARCH-ESC-2) | R4 as written | see ARCH-ESC-2 |

## 9. Test strategy

### AD-9: fixtures at two seams, no live API, and the pure core tested separately

- **Seams.**
  - `release_panel_logic.run_git` (monkeypatched) returns canned `rev-list` and `log` output.
  - `github._run_gh` (monkeypatched) returns canned pages keyed by endpoint, plus injected `GitHubError` / `RateLimitError` / `None` (404).
  - No other `subprocess` site exists in the module. A static test asserts that.
- **Fixtures.** `tests/fixtures/release_review_evidence/*.json` hold scenario files: commits with their parents, association pages, PR objects, review pages and comment pages, with SHAs derived from aliases (the ADR-1660 `sha(alias)` idiom).
- **Acceptance criteria.** AC-1..AC-15 and AC-17 map one-to-one to tests. AC-16's grep test is kept and must be deleted by REQ-B7's PR. Its docstring says so, so it does not become a ratchet against #1340.
- **Added tests (binding):**
  - **T-A1:** an audit-log-only range, and a commit-plus-revert range, both give exit 1 with both SHAs flagged. Neither gives exit 2 or NO_CONTENT (AF-1).
  - **T-A2:** an APPROVED followed by a CR by `HUMAN_REVIEWER` at head before merge → not E-OVERSEER+HUMAN (AF-2, fixture k).
  - **T-A3:** an overseer APPROVED at h1, never dismissed, then a push to h2 and a merge → flagged.
  - **T-A4:** a 404 on reviews page 2 after a full page 1 → INDETERMINATE `reviews-read-failed`. The same for association and comments (AF-3).
  - **T-A5:** a merge commit whose `^2 ≠ p.head.sha` → MERGE_UNBOUND. An octopus merge → MERGE_UNBOUND. A PR whose `merge_commit_sha` is outside F → MERGE_UNBOUND (B1, B2).
  - **T-A6:** second-parent commits under an attributed merge are accounted but not queried. The `_run_gh` call log shows no association read for them. An accounting mismatch → INDETERMINATE.
  - **T-A7:** an edited `HUMAN_REVIEWER` disposition → ignored, still exit 1 (AF-4). A short-SHA disposition → ignored as malformed.
  - **T-A8:** `main` with an injected `ValueError` deep in `classify` → exit 2 with `INDETERMINATE: internal-error:ValueError`, never exit 1 (AF-8). The wrapper maps exit 3 to 2.
  - **T-A9:** budget exhaustion (a fake clock) → INDETERMINATE.
  - **T-A10:** the `derive_range` byte-identity (the existing tests, unmodified), plus `derive_base_head` returning SHALLOW / NO_TAG with the identical refusal text. The sweep never opens `release_panel_exclusions.txt` (spy on `open`).
  - **T-A11:** a 30+-item flagged list with the line-1 identity check. Line 1 contains no title or subject bytes, even when a fixture title contains `\n` or `RELEASE-REVIEW-EVIDENCE PASS`.
  - **T-A12:** a `classify` signature test: no parameter carries check-run or audit data (AC-6, AC-8 by construction).
- **Inner loop.** `scripts/framework/run_tests_inner_loop.sh` must pass (AC-17). The `/tmp` hygiene rules apply: no leaked temp, no files written (AC-15).

## 10. Slicing

### AD-10: five slices, each ≤ 15 files; arming is last

| Slice | Content | Files (approx.) | Codable before human answers? |
|---|---|---|---|
| **S0** | E-1624-1 and E-1624-2 in `scripts/framework/review_state.py` plus tests. **Folded into ADR-1660 S1 if that is not yet coded.** Otherwise a standalone PR. Protected surface. | 2–3 | **Yes.** CODEOWNERS human approval to merge. |
| **S1** | `release_panel_logic.derive_base_head` extraction (no behaviour change). `github.fetch_raw_pages` and `github.list_commit_pulls` (strict, via S0's assembler). Tests. `SCRIPTS-INDEX.md` regenerated. | ~6 | **Yes**, after S0 is on main. Not protected. |
| **S2** | `release_review_evidence.py` (core, collector, CLI; AD-2..AD-6, AD-8 constants, `DISPOSITION_SOURCE = "none"`), `release_review_evidence.sh`, fixtures, tests (AC-1..12, 14..17, T-A1..A12), `SCRIPTS-INDEX.md`. Nothing invokes it, so its blast radius is nil. | ~10 | **Yes.** Its predicate is a *necessary* condition under any ESC-1 answer, so it is not wasted if ESC-1(a) is "no". Mergeable while inert. |
| **S3** | The disposition reader for the ruled ESC-2 option (AD-7), AC-13, T-A7, fixtures. Under (B) or (C) it also includes the (A) reader for SHAs. | ~4 | **No. Waits for ESC-2.** |
| **S4** | **Arming.** Authored by the top-level session (CLAUDE.md #1347), never by `coder`. `.claude/agents/worker.md` gets the R2 row `scripts/oversight/release_review_evidence.sh --issue <n>`, required at both PATCH and MINOR/MAJOR (R11). The PATCH-promotion sentence is reworded from "all five suites" to "every suite in the MINOR/MAJOR column", which removes the count that ADR-1340 PR 2 also edits, so the two cannot conflict. `DECISIONS.md` gets the ESC-1 reduction and the F1 acknowledgement. `docs/OVERSIGHT-RUNBOOK.md` gets the disposition procedure. If ARCH-ESC-3 is answered yes, `protected_surfaces.txt` and the CODEOWNERS regeneration go here too. | 4–6 | **No.** Waits for ESC-1..6, ARCH-ESC-1..3, S2+S3 merged, **and** a demonstrated out-of-band run (AD-11). |

**Merge order:** S0 → S1 → S2 → S3 → S4. S1 and S2 may share one PR if the file count allows.

## 11. Protected surfaces and arming

### AD-11: arming is a separate, human-gated step after a demonstrated run

- **Protected files.** S0 (`scripts/framework/**`) and S4 (`.claude/agents/**`) are protected. S1, S2 and S3 are not, unless ARCH-ESC-3 makes them so.
- **Demonstration run before S4** (ADR-1340 AD-9 precedent: never arm an unexecuted suite). S4 must not open until the sweep has been run once out-of-band against the live range. That run is read-only, so the human can run it in their terminal with the worker or their own token. Its output, line 1 plus the accounting line, is attached to the S4 PR. It must show:
  - each F5 merge shape attributed (AD-3 residual);
  - a zero accounting mismatch;
  - a measured wall clock under `WALL_CLOCK_BUDGET_S`.
- **Expected first-run outcome.**
  - **FLAGGED.** This covers the pre-`f6a1aceb3` PRs (ESC-6) and at least `ad16c85b1`, `56aafb02c` and `bbeef2617` (ESC-4).
  - **Product consequence:** arming S4 makes the next v0.7.0 release request block until the human dispositions those items. That is a new release-blocking condition and new operational work for the human, so S4 is product-boundary. It is cleared through ESC-1..6 and the CODEOWNERS gate, never by an agent.
- **Shipped scope.** `scripts/oversight/` ships to consumer installs by rsync, and `worker.md` ships via `consumer_agents.txt`. The sweep reads identities only from the consumer's own `machine-accounts.env` and never hard-codes logins, so it is portable. Whether consumers should run it at all is #1621's question. This ADR does not decide it.
- **Overseer section.** This work does not touch `overseer.md:170-215` (R12, REQ-B8).

---

## 12. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (R1).** Reuse `derive_range`'s base/head derivation through the extracted `derive_base_head`, not `derive_range` itself. "Empty range" means **zero commits** (`NO_COMMITS`), not zero files. Panel exclusions never apply (AF-1). AC-12 is amended accordingly, and T-A1 is added.
- **AM-2 (R2).** "Every commit is accounted for" stands. *How* is amended: first-parent commits are attributed through the API, and second-parent commits are accounted locally under their merge, with merge binding B1/B2 (AD-3). The new flag class `MERGE_UNBOUND` is added.
- **AM-3 (R4).** "APPROVED at head" means the reviewer's **effective state as of `merged_at`** (ADR-1660 `effective_states` over `as_of(R, merged_at)`), with the deciding review's `commit_id == head.sha`. It does not mean "some APPROVED review exists" (AF-2).
- **AM-4 (R13, F7).** `overseer_has_approved` and `_find_human_approval` are **not** reused for evidence; they cannot express R4 (AF-2). The reused definitions are instead:
  - `review_state` (`assemble_pages`, `effective_states`, `outstanding_crs`, `resolve_machine_accounts`, plus E-1624-1/2);
  - `require_human_approval.is_bot_reviewer`;
  - `require_tier_ceiling.load_env`;
  - `merge_config.resolve_repo_slug`.
- **AM-5 (R9).** The list is extended with:
  - a 404 on a later page;
  - a non-list page;
  - a PR missing `merge_commit_sha`;
  - a wall-clock budget overrun;
  - an internal exception.

  Each is INDETERMINATE (exit 2). An uncaught exception must never exit 1 (AF-8).
- **AM-6 (R6).** Check runs and the audit trail are **not read** in v1, not even as information. Reading them costs about 150 more calls and adds no evidence, and if they are never read, AC-6 and AC-8 hold by construction. ESC-5 = yes would add them in a new slice.
- **AM-7 (R8.2 vs R11's example).** Dispositions require the **full 40-hex SHA**. Line 1 prints 12-character SHAs, and later lines print full SHAs for copying. The requirements' example `ad16c85b1` is illustrative only.
- **AM-8 (R8, option A).** A disposition comment must be unedited (`updated_at == created_at`). An edited one is ignored and reported (AF-4).
- **AM-9 (ESC-2 framing).** Options (B) and (C) cannot disposition SHAs, so each must be paired with (A) (AF-5).
- **AM-10 (R11).** The R2 invocation is `release_review_evidence.sh --issue <n>`. The PATCH-promotion sentence is reworded so it does not count suites (S4).
- **AM-11 (new flag class).** `MERGED_OVER_CR` is added, pending ARCH-ESC-1.

**Nothing in the requirements is rejected outright.** R7 (no new artifact), R11 (every tier) and R12 (do not touch the overseer section) are endorsed as written.

---

## 13. Escalations

### Human (pm-agent's, unchanged; the architect does not rule on these)

| ESC | Question | Gates | Architect's note |
|---|---|---|---|
| ESC-1 (a) | Is G-e's per-role element formally reduced to "passed the overseer gate"? | S4 | **Technical consequence of "no":** no durable per-role source exists that is not a stamp or register, and R7 and the #1594 ruling forbid one. "No" therefore means a new attestation mechanism, which is a different issue. S0–S2 remain valid as a *necessary* condition. |
| ESC-1 (b) | Acknowledge that G-e has been unchecked since `2abe9919b` | S4 (DECISIONS entry) | Confirmed: the window exists today (row 1). |
| ESC-2 | Disposition mechanism: A / B / C | S3 | Option A needs the unedited rule (AF-4). B and C each need A as well for SHAs (AF-5). The architect concurs with A. |
| ESC-3 | Human-merged PR with no overseer review | S4 binding; interim constant | — |
| ESC-4 | Unattributed commits: flag all, no exemption list | S4 binding | AF-1 shows why a path exemption would be the panel's exclusion list by another name. The architect concurs. |
| ESC-5 | Check runs required per PR? | S4 binding | AM-6 |
| ESC-6 | The pre-#1657 backlog: dispositions vs `LEGACY_COMMENT_VERDICT` | S4 binding | If legacy comments are accepted, they must be overseer-App-authored **and unedited** (AF-4 applies to the App's own comments as well). |

### ARCH-ESC (added by the architect; product-boundary checkpoint)

- **ARCH-ESC-1: should a PR merged over an outstanding write-access CHANGES_REQUESTED be flagged even when it is otherwise evidenced?**
  - The ADR-1660 D3 hold says such a PR should never have merged without the human's re-review or a dismissal. Flagging it adds a release-blocking class, which is a user-visible gate change.
  - **Recommended: yes** (interim `FLAG_MERGED_OVER_CR = True`).
  - Gates: S4.
- **ARCH-ESC-2: does E-OVERSEER+HUMAN need a tier condition?**
  - Since #1657 Part 2, an overseer COMMENT at or below the ceiling is a merits-type withholding (AF-7). R4 as written lets the human's APPROVED at head override it. The server gate (#1426) instead requires recomputed tier > ceiling.
  - Recomputing each historical PR's tier at release time is **not technically sound**. The tier depends on validator artifacts and configuration as they stood at that time. So the real options are:
    - **(a)** accept R4 as written, because the human's identity-bound approval at the reviewed head is the decision (overseer.md:154). **Recommended.**
    - **(b)** flag such PRs as a distinct class, `HUMAN_OVERRODE_OVERSEER`, for bulk disposition.
  - Gates: S4.
- **ARCH-ESC-3: should `scripts/oversight/release_review_evidence.{py,sh}` be added to `protected_surfaces.txt`?**
  - A release gate the worker can weaken without human review is a governance hole. `release_panel_logic.py` has the same hole today, and should be added with it.
  - It adds human-review load on future edits to these files only.
  - **Recommended: yes.**
  - Gates: S4 (the list edit is itself protected).

---

## 14. Follow-ups (named, not filed here)

- **FU-1:** the overseer's per-PR merged-by-bot check (`overseer.md:158-164`) flags the overseer's own auto-merges, because `BOT_ACCOUNTS` includes `BOT_OVERSEER_USERNAME` (F4). This is out of scope (non-goal).
- **FU-2:** `github.list_issue_comments` and `list_check_runs_for_ref` have the later-page-404 truncation defect (AF-3). Their existing callers are not fixed here. ADR-1660 S2 fixes `list_pull_reviews` only.
- **FU-3:** a GraphQL batched association read, if the S4 demonstration run's measured wall clock is within 25% of the budget.
- **FU-4:** add `release_panel_logic.py` to `protected_surfaces.txt` (ARCH-ESC-3's sibling).

## 15. Affected sign-offs (startup-gap analysis)

- **Should this have been settled in the initial review?** Yes for the ADR-1340 side.
  - ADR-1340 recorded REQ-B8's "never a window" ordering as binding, while `2abe9919b`, on the same day, had already opened the window. Neither document reconciled the two.
  - This is a `startup-artifact-gap` in #1340's sequencing. **Recommended:** the orchestrator annotates #1340, or files a gap issue. Per this cycle's constraints the architect files nothing.
- **These sign-offs stand:**
  - ADR-1340 AD-2. `derive_range`'s behaviour is unchanged, and the extraction is pinned by its existing tests.
  - ADR-1660 D1–D9 and the S1 TD's approval for all existing functions.
- **These are re-opened:** the ADR-1660 S1 TD, **for E-1624-1 and E-1624-2 only**. No S1 code exists, so no approved code is orphaned.
- **No #1624 design or code exists**, so this ADR orphans nothing of its own.

---

## Human Review Required

**RISK: HIGH.** This is a release gate, and a release gate that passes wrongly is worse than none. Three ways it could have passed wrongly are closed positively above:
- a deciding review at a stale head (AF-2 → AD-5);
- a truncated review list (AF-3 → AD-4);
- a bot-edited human disposition (AF-4 → AD-7).

Two ways it could have failed uselessly are also closed:
- refusing audit-only ranges (AF-1 → AD-2);
- timing out (AF-6 → AD-3, AD-4).

**CONFIDENCE.**
- **High** on §0. Every row was re-derived from the tree or from git at `0a2811d4f`.
- **High** on AD-1, AD-2, AD-4, AD-5 and AD-6.
- **Medium** on AD-3's B2 for rebase merges, and on GitHub's association behaviour for rebased commits. I could not probe the live API this cycle, which is why AD-11 makes the demonstration run a precondition of arming.
- **Medium** on AF-4's exact permission surface: whether the worker App's installation can edit a user's issue comment. The unedited rule is cheap and correct whatever the answer.

**BLAST RADIUS.**
- S0: `review_state.py`, shipped and protected.
- S1: `release_panel_logic.py` (behaviour-preserving) and `github.py` (additive).
- S2/S3: a new, inert module.
- S4: the release gate at every tier, and the human's disposition workload on the first armed release.

**Change classification: STRUCTURAL.** It adds a new required release gate, a new human disposition step, and a protected-surface edit. Per the product-boundary checkpoint, ESC-1..6 and ARCH-ESC-1..3 must clear before S4 binds. S0–S2 may proceed now.
