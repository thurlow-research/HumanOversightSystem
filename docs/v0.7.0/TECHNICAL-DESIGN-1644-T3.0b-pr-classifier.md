# TECHNICAL DESIGN — #1644 slice T3.0b: no-idle selection, PR side (`bin/hos-cron`'s PR routing moves into a tested Python classifier; H4 shapes stop blocking new work below the ARCH-ESC-1 bound; closes #1847)

**Status:** DRAFT-1, plus the architect's round-1 edits. **Architect verdict, round 1: APPROVED_WITH_EDITS**
(§9A). **`coder` handoff is BLOCKED** on the human's answer to **ARCH-ESC-1R** (ADR-1644 Erratum 2, which
replaces §9 H-1). Under ARCH-ESC-1R's recommended answers, the design needs no further change. Under
Q1(b) or Q3(b), it returns to `technical-design` for revision.
> **Superseded in part (2026-10-13), by ADR-1644 Erratum 3 =
> `ADR-1660-1662-changes-requested-semantics.md` §4.1 (E14–E18).** These parts are replaced:
> - §2.5 R, the CR rule, including "a full page containing a CR is a determination";
> - the §2.6 C5/C6 rows, and the CR handling in C7/C8;
> - fixtures C5 and T-FC10.
>
> Before `coder` handoff, this TD must be revised to match those items. That revision is in addition
> to the ARCH-ESC-1R gate.
**Date:** 2026-10-02
**Author:** technical-design
**Baseline:** `HEAD` = **`0eabb86852a64ebb1610177aeb23861d595f503f`**. Every `file:line` below refers to
that commit. GitHub reads (#1847, #1313, #1912, #1198) were made read-only through
`bootstrap/query_issues.sh --app worker`.
**Binding inputs:**
- `docs/v0.7.0/ADR-1644-stage-per-cycle.md`: AF-C2, AD-C3 step 2, AD-C6 (H4 row, T-NS5), §6 ARCH-ESC-1,
  §5 T3.0b row ("Behavior is preserved, except that H4 shapes no longer block new work. Closes #1847.
  T-NS5."), §11 (the `bin/hos-cron` PR-routing sign-off note), and §1's governing constraint ("every
  'unknown' … resolves to DEGRADED or escalation. It never resolves to 'not blocked'").
- `docs/v0.7.0/REQUIREMENTS-1644-AMENDMENT-2-esc1-pr-side.md` (PM-6, uncommitted at the baseline):
  REQ-C24, REQ-C25, REQ-C26, and AC-1 to AC-8. It encodes the human's ARCH-ESC-1 ruling (#1912,
  ratified by `ScottThurlow` at 2026-10-02T04:55:46Z): new work is allowed while fewer than 3 worker PRs
  are human-pending, blocked at 3 or more, and overseer-pending PRs keep blocking.
- `docs/v0.7.0/REQUIREMENTS-1643-1644-deterministic-agent-invocation.md` and
  `REQUIREMENTS-1644-AMENDMENT-1-stage-per-cycle.md` (ESC-8, REQ-C11, REQ-C18).
- The format of the two prior slice TDs: `TECHNICAL-DESIGN-1644-T3.0a-no-idle-selection.md` and
  `TECHNICAL-DESIGN-1644-T3.3a-edge-tooling.md`.

**Scope (the ADR's, nothing more):**
- move the worker PR routing at `bin/hos-cron:1042-1128` into `scripts/framework/classify_worker_prs.py`.
  The bash keeps only a thin call-site;
- move the rendering of the "New work directive" (`bin/hos-cron:1945-1966`) into the same module, so the
  directive text is produced and tested in one place;
- add REQ-C24's per-PR classes, REQ-C25's bound B = 3, and REQ-C26's visibility notice, which is a
  prompt-contract change;
- pin today's behavior with characterization tests **before** the move (§7.0), then pin T-NS5, the
  bound, the fail-closed rules, #1847's three states, and zero added requests.

**Explicitly out of scope:**
- the selector (`select_work_candidates.py`), which T3.0a/T3.2 own and this slice does not touch;
- the executor, reconcile and stage machinery (T3.1+);
- the overseer's own PR pre-filter at `bin/hos-cron:1193-1260`, which is a different role and a
  different list;
- `_build_context`'s display-only "### Open bot PRs" fetch (`:1911-1922`);
- `merge_authority.py`, `submit_pr.sh` (the #1162 guard, AC-7) and branch protection;
- a deterministic notice poster (§9 OQ-5).

This document says *what the code must do*. It contains no application code.

---

## 0. Verification, re-derived against `0eabb868`

### 0.1 Search for existing helpers (CLAUDE.md "Search first", required)

I searched `scripts/` (recursively), `bootstrap/`, `bin/` and `scripts/automation/lib/`.

| Looked for | Found | Consequence |
|---|---|---|
| An existing PR classifier, or any Python reader of `mergeable_state` + reviews for *worker routing* | **None.** The routing exists only as bash at `bin/hos-cron:1042-1128`. `merge_authority.py` classifies PRs for **merge** decisions (overseer side) and takes its inputs as arguments; it makes no `gh` calls of its own for routing. | The classifier is a new module, as ADR §5 states. It does **not** import `merge_authority.py`, because those are different decisions with a different authority. Its label vocabulary is cross-checked against it (§0.3 TD-F2). |
| A `gh api` subprocess pattern on the protected surface | `select_work_candidates.py::_run_gh` (`:230-256`): `["gh","api",endpoint]`, 30 s timeout, JSON parse, one failure type | **Copied, not imported.** The selector's helper is private and its failure type is selector-specific. The classifier gets its own `_run_gh` with the identical shape, so T-ZC2's static check (§7.3) can assert "`subprocess` only inside `_run_gh`" for this module too. |
| `scripts/automation/lib/github.py` (retry/backoff) | Present | **Not used, deliberately**, which follows the selector precedent (TD-1540 §2.2). Retries would change the request count that AC-8 pins, and a failed read here already resolves fail-closed within one cycle. |
| A launcher call-site pattern for a protected Python gate | `bin/hos-cron:1144-1166` (selector: `cmd && rc=0 \|\| rc=$?`, explicit `case`, stderr passthrough) | **Reused exactly** for the classifier call-site (§3). |
| An idempotent PR visibility notice | `worker-cron-prompt.md:76` and `worker.md:335-344` (`<!-- hos-worker-merge-block -->`, model-posted through `query_issues.sh --comments` + `post_comment.sh`) | **Reused**, with the same marker (§4). `escalate_to_human.sh` is not reusable: it refuses PR targets (T-ESC5) and applies `needs-human`. |
| A per-PR heterogeneous `gh` fake for `bin/hos-cron` tests | `CronEnv`'s inline stub (`tests/automation/test_hos_cron.py:163-270`) serves **one** global PR state to every PR (`HOS_TEST_PR_*`) | **Insufficient** for the multi-PR fixtures that T-NS5 and the bound need. A fixture-file fake is added (§7.1). The env-var mode is kept, so that existing tests run unmodified. |

### 0.2 Today's routing, which the characterization tests pin

**The list (`:1048-1055`).** There is one request, `repos/{slug}/pulls?state=open&per_page=20`, filtered
by `jq` to `.user.login == $HOS_BOT_LOGIN`. Order is the API's default order. If the call fails,
`_gate_pr_fetch_ok=0` and `_OPEN_PR_NUMS=""`.

**Per PR, in list order (`:1058-1110`).** The first match wins:

| Step | Request | Rule | Result |
|---|---|---|---|
| 1 | `pulls/{n}` (`--jq {ms,d,labels}`). **On failure**, the fallback is `{"ms":"unknown","d":false,"labels":[]}` | — | — |
| 2 | — | `ms == "dirty"` | `needs-fix`, **break** |
| 3 | — | `d == True` and `needs-ai` ∈ labels | `needs-fix-bounce`, **break** |
| 4 | — | `needs-ai` ∈ labels and `needs-human` ∉ labels | `needs-fix`, **break** |
| 5 | `pulls/{n}/reviews` (`--jq` count of `CHANGES_REQUESTED`). **On failure:** `0` | count > 0 | `needs-fix`, **break** |
| 6 | `pulls/{n}/reviews` **again** (`--jq` count of `APPROVED`). **On failure:** `0` | count == 0 | `needs-attention`. The loop **continues** |

**Aggregate.** The value starts as `awaiting-merge`. A `break` ends the loop, so later PRs are never
read. `needs-attention` does not break, so a later PR can still set `needs-fix`. The precedence is
therefore: the first worker-actionable PR in list order, then `needs-attention` if any PR has zero
approvals, then `awaiting-merge`.

**Requests per PR today:** 1 (stopped at steps 2–4), 2 (stopped at step 5), or 3 (reached step 6). The
total is 1 + Σ per PR.

**Side effects (`:1112-1127`).**
- `awaiting-merge`: a stdout line ("all N open PR(s) awaiting human merge …"),
  `_audit cycle-skip reason=awaiting-merge`, and an overseer wakeup file.
- `needs-attention`: a stdout line ("N open PR(s) unreviewed …") and
  `_audit cycle-needs-attention pr_nums=…`.
- Other values have no side effect.

**Directive (`:1945-1966`).** If `_OPEN_PR_NUMS` is non-empty, the block is `NEW WORK: BLOCKED`, then
`Reason: routing=<v> for open PR(s) #a, #b. <per-value text>`. The list is **every** open worker PR,
not only the PR that triggered the value. Otherwise the block is `NEW WORK: ALLOWED` /
`Reason: no open PRs authored by this worker.`. **A list-fetch failure therefore prints `ALLOWED`**
(VF-P4).

**Skip gate (`:1179-1189`).** `_gate_pr_fetch_ok=0` prevents the #1395 skip, and a non-empty
`_OPEN_PR_NUMS` also prevents it.

### 0.3 Findings that shape this design

- **TD-F1: an `hos-halt` PR already halts the whole cycle.** The halt check at `:918` queries
  `repos/{slug}/issues?state=open&labels=hos-halt` with no `pull_request` filter. GitHub's issues
  endpoint returns PRs too, so an open PR that carries `hos-halt` stops both roles at `:929-933`,
  **before** routing runs. The classifier sees an `hos-halt` PR only in the seconds-wide race between
  `:918` and `:1048`. PM Q2 is therefore a race-window question (§6 Q2).
- **TD-F2: label vocabulary.** `merge_authority.py:494` defines `_HUMAN_GATE_LABELS = {needs-human,
  hos-halt}` and lower-cases labels before comparing them. Today's bash compares labels exactly and is
  case-sensitive. The classifier keeps exact matching. A case variant such as `Needs-Human` is therefore
  **not** a carrier, which fails toward blocking (T-FC11).
- **TD-F3: stale approvals are already mostly dismissed.** `scripts/framework/setup_branch_protection.sh:183`
  sets `dismiss_stale_reviews: true`. `DECISIONS.md:654` makes an explicit `head_sha` check the primary
  control on the overseer side, with dismissal as "a second, independent line of defense". The PR detail
  (`head.sha`) and the reviews (`commit_id`) are **both already fetched**, so a head-SHA match costs zero
  requests (§6 Q4).
- **TD-F4: two list truncations exist today.**
  - The list is one page of 20 across **all** authors. If more than 20 PRs are open, the worker's own
    PRs on page 2 are invisible. That is fail-open toward `ALLOWED`.
  - Reviews are fetched with the default 30 per page, and fetched twice.
  - The classifier uses `per_page=100&page=1` for both reads and fetches reviews once. A **full** page is
    treated as unknown (§2.6). The request count does not increase (AC-8).
- **TD-F5: `bin/hos-cron` ships to consumers** (`scripts/framework/framework_consumer_files.txt:20`).
  The classifier must be listed there too. If it is not, every consumer's launcher hits the fail-closed
  fallback on every cycle (§3.4). `test_consumer_framework_files.py` enforces "listed ⇒ present". Nothing
  enforces the converse, so the listing is an explicit file-plan item.
- **TD-F6 (HIGH): the ARCH-ESC-1 inputs omitted #1313's blocking prerequisites.** ADR AF-C2 and §6
  name #1162 as "the prerequisite" and say it is present. `DECISIONS.md:656-664` (#1198, 2026-08-09)
  retained serialization and deferred *N = 2* to **#1313**. #1313 is open and labeled `needs-human`, and
  it is gated on three **blocking** prerequisites:
  - P1: close the force-push bypass in `worker-cron-prompt.md`'s conflict path. It is still present at
    `worker-cron-prompt.md:90`.
  - P2: set branch protection `required_status_checks.strict: true`. It is still `false` at
    `setup_branch_protection.sh:177`.
  - P5: a field observation of the #1162 guard firing.

  The ruling permits up to 3 human-pending PRs **plus** one overseer-pending PR. That is broader than
  #1313's N = 2. I do not re-litigate a human ruling. However, the record does not show that the human
  saw these three gates when ruling, so §9 H-1 asks for an explicit reconfirmation before coding.

  *Architect correction (round 1), with the full facts in ADR Erratum 2 E6 and E6a:*
  - **Count.** A cycle opens at most one PR (submit, then STOP), and overseer-pending PRs block. So the
    steady-state maximum is **3 open worker PRs in total**, not 3 + 1.
  - **#1313 lists more than P1, P2 and P5.** It also lists P4 (a post-merge control), a file-overlap
    refusal, predeclared abort criteria, and an approved-only shape.
  - **P1 is narrower than stated.** The force-push sits only in the "directive absent" fallback, and it
    contradicts `worker.md:411`. It is closed in this slice (§4.1).
  - **P5 has field evidence.** There are three `stale-base-merged` records from 2026-09-14. They are
    uncommitted (#1803).
- **TD-F7: an early stop leaves later PRs unclassified.** Today's `break` means that after a
  worker-actionable PR, the remaining PRs are never read. Keeping that behavior is what holds AC-8. The
  consequence for REQ-C26 is that in a `needs-fix` cycle, a human-pending PR listed *after* the
  actionable one gets no notice that cycle. It gets one in the next cycle that classifies it (§4.3,
  §9 OQ-6).
- **TD-F8: a second fail-open path exists.** When `_REPO_SLUG` is empty, the whole gate block at
  `:1017` is skipped, `_OPEN_PR_NUMS` stays unset, and the directive prints `ALLOWED`. §3.1 sets the
  directive's default to fail-closed, which closes this path too (D-1).
  *Architect correction (round 1):* **this path is unreachable.** `bin/hos-cron:913-916` already exits the
  cycle on an empty slug (the fail-closed halt check, #912), before `:1017`. §3.1's default stays, but
  only as defence-in-depth. It is not a live fail-open, and it has no consumer-visible effect.

---

## 1. Files (≤15; one PR)

| # | Path | Change | Surface |
|---|---|---|---|
| 1 | `scripts/framework/classify_worker_prs.py` | **New.** The classifier and directive renderer (§2). | protected |
| 2 | `bin/hos-cron` | **Modify.** Replace `:1042-1128` with the call-site (§3.2). Replace `_build_context`'s directive branch `:1946-1965` with a print of `_PR_DIRECTIVE` (§3.3). Add the fail-closed default (§3.1). | protected |
| 3 | `tests/framework/test_classify_worker_prs.py` | **New.** In-process unit tests: T-CL*, T-NS5*, T-BD*, T-FC*, T-1847*, T-DIR*, T-ZC*, T-CLI* (§7.3). | — |
| 4 | `tests/automation/gh_pulls_fixture.py` | **New.** A per-PR fixture fake for the pulls family. It serves both today's `--jq` call shapes and the classifier's raw shapes, and it logs each call (§7.1). | — |
| 5 | `tests/automation/test_hos_cron.py` | **Modify.** Stub delegation to #4. `TestPRRoutingCharacterization` (§7.2, commit 1). Three named expectation flips plus T-HC* (§7.4, commit 2). | — |
| 6 | `bootstrap/worker-cron-prompt.md` | **Modify.** Step 0.5's R2 token list and Step 1's bullets (§4). Remove the fallback's force-push instruction at `:90` (#1313 P1, ADR Erratum 2 E11; §4.1). | protected |
| 7 | `.claude/agents/worker.md` | **Modify.** The Step 1 bullets (`:323-349`) and R2's token list (`:576-580`), mirroring #6. **Authored by the top-level worker session, not `coder`** (CLAUDE.md, #1347). | protected |
| 8 | `scripts/framework/framework_consumer_files.txt` | **Modify.** Add `scripts/framework/classify_worker_prs.py` under the selection-gate block (TD-F5). | protected |
| 9 | `docs/LABELS.md` | **Modify.** Add the classifier as a reader in the `needs-human` row (a new PR-side meaning, which the row's own note requires recording), and re-point the `needs-ai` row's `bin/hos-cron:1085/~1094` references to the module. | — |
| 10 | `DECISIONS.md` | **Append.** One dated entry: #1198's serialization is relaxed to B = 3 under ARCH-ESC-1 (#1912). It cites the 2026-08-09 entry it amends, and it records the H-1 outcome. Without it, the log still says "serialization retained". | — |
| 11 | `SCRIPTS-INDEX.md` | **Regenerate** with `scripts/framework/gen_scripts_index.sh`. No hand edits. | — |

That is **11 files**. `scripts/framework/regen_all.sh --check` must be clean before the PR. CODEOWNERS
already covers `scripts/framework/**`, `bin/**` and `bootstrap/**` by glob.

**Not touched:**
- `select_work_candidates.py` and `requester_trust.py`, because nothing here is a selection or trust
  change;
- `merge_authority.py`;
- `submit_pr.sh` (AC-7);
- `setup_branch_protection.sh`, whose P2 is §9 H-1's subject, not this slice's;
- `research/findings/safety-serialization-makes-the-human-the-rate-limiter.md`, a historical record.

---

## 2. `scripts/framework/classify_worker_prs.py`

### 2.1 Placement and boundary

- It is protected L2 Python on `scripts/framework/**` (AD-C3 step 2), beside the selector. It is
  stdlib-only, because consumers receive it (TD-F5).
- **It is read-only.** It makes no writes to GitHub, no comments, no labels, no files and no cache. It
  re-derives everything from live state on every run, as the selector does under FR7/AD-4.
- **It reads no environment variables and no configuration file.** Its only inputs are its two flags and
  the `gh` responses. The `gh` subprocess inherits `GH_TOKEN` from the launcher, but the module never
  reads it. That is how "the bound cannot be raised by env/config" (REQ-C25, AC-7) holds by
  construction (T-BD4).
- **It never reads PR comments, events or timeline.** Its carriers are the label and the review list,
  which are already fetched (AC-8, REQ-C24 fail-closed rule). A `HUMAN_REQUIRED` inline verdict without
  the `needs-human` label is never seen, and therefore never counted (T-FC3).

### 2.2 CLI (exact)

```
python3 -m scripts.framework.classify_worker_prs --repo <owner/name> --author <login>
```

- **`--repo`** must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. This is the selector's `_REPO_RE`,
  re-declared rather than imported.
- **`--author`** must match `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$`.
- Both flags are required. **There are no other flags.** Any other argument, including a would-be
  `--bound`, is an argparse error: exit 2, empty stdout, and no `gh` call (T-CLI2, T-BD5).

### 2.3 Constants (module-level, not flags)

| Name | Value | Note |
|---|---|---|
| `HUMAN_PENDING_BOUND` | `3` | REQ-C25 B. A literal int. It is never derived. |
| `CARRIER_LABEL` | `"needs-human"` | REQ-C24 2(a) |
| `HALT_LABEL` | `"hos-halt"` | §6 Q2 |
| `BOUNCE_LABEL` | `"needs-ai"` | today's `:1085`, `:1099` |
| `LIST_PER_PAGE`, `REVIEWS_PER_PAGE` | `100` | TD-F4 |
| `LIST_MAX_PAGES` | `3` | ADR Erratum 2 E10. List pages are read only while the previous one was full. |
| `TRUSTED_APPROVER_ASSOCIATIONS` | `frozenset({"OWNER","MEMBER","COLLABORATOR"})` | ADR Erratum 2 E9 |
| `_GH_SUBPROCESS_TIMEOUT_SECONDS` | `30` | selector parity |
| `NOTICE_MARKER` | `"<!-- hos-worker-merge-block -->"` | REQ-C26. The directive does not print it. It exists so the prompt-contract tests and the module agree on one literal. |

### 2.4 Requests (the only three endpoint shapes)

| Id | Endpoint (argv is exactly `["gh","api",<endpoint>]`) | When |
|---|---|---|
| L | `repos/{repo}/pulls?state=open&per_page=100&page=<k>`, with *k* ∈ {1, 2, 3} | page 1 once. Page *k*+1 **only** if page *k* returned exactly 100 elements (ADR Erratum 2 E10). Constant `LIST_MAX_PAGES = 3`. |
| D | `repos/{repo}/pulls/{n}` | once per **evaluated** worker PR |
| R | `repos/{repo}/pulls/{n}/reviews?per_page=100&page=1` | once per evaluated PR that passes steps 2–4 |

The calls use no `--jq`, `--paginate`, `-f`/`-F` or `graphql`. A `gh` non-zero exit, a timeout, an
`OSError`, or output that is not JSON is a **read failure** for that request.

**Request budget per PR** is 1 (stopped at steps 2–4) or 2. Today it is 1, 2 or 3, so the classifier
is ≤ today for every fixture. It is strictly less whenever today reaches step 6 (§7.3 T-ZC1).
List pages 2 and 3 are read only when 100 or more PRs are open, which is a case where today's single
page of 20 is already wrong. No C-case fixture reaches them.

### 2.5 Parsing (what a successful read means)

- **L.**
  - The result must be a JSON array.
  - Every element must be an object with an `int` `number` > 0 and a `str` `user.login`.
  - **If any element fails that test, the whole list is unknown** (`list-unparseable`). Without
    `user.login`, the classifier cannot tell whether the PR is the worker's.
  - Worker PRs are the elements where `user.login == --author`, compared exactly and case-sensitively
    as today, kept in API order.
- **D.** This is `detail_ok` iff the result is an object with:
  - `draft` a `bool`;
  - `labels` a list of objects, each with a `str` `name`;
  - `mergeable_state` a `str` or `null`.

  `head.sha`, if it is a 40-hex `str`, is captured as `head_sha`, otherwise `None`. A `head_sha` of
  `None` alone does not unset `detail_ok`. It only disables carrier (b).

  **On a read failure or `detail_ok = False`**, the routing inputs take today's fallback values exactly
  (`ms = "unknown"`, `draft = False`, `labels = ∅`), so steps 2–4 behave as today, and the PR is marked
  `detail_ok = False`.
- **R.** This is `reviews_ok` iff the result is a JSON array of objects, each with a `str` `state`.
  `CR` is true iff some review has `state == "CHANGES_REQUESTED"`. `approved_on_head` is true iff some
  review has all of the following (ADR Erratum 2 E9):
  - `state == "APPROVED"`;
  - `commit_id == head_sha`, with `head_sha` not `None`;
  - `author_association` (a `str`) ∈ {`OWNER`, `MEMBER`, `COLLABORATOR`};
  - `user.login` is a `str` that does not end in `[bot]`.

  A missing or non-`str` `author_association` or `user.login` makes **that review** a non-carrier. It does
  not unset `reviews_ok`. `approved_untrusted` is true iff some review is `APPROVED` on head but fails
  the author test.
  - **A full page (100 reviews) with no `CHANGES_REQUESTED` sets `reviews_ok = False`**
    (`reviews-page-full`), because a CR on page 2 cannot be ruled out.
  - A full page that does contain a CR is a determination (CR = true).
  - **On a read failure**, CR = false (today's `|| echo 0`) and `reviews_ok = False`.

### 2.6 The algorithm (the order is part of the contract)

**A. Arguments.** Bad arguments give exit 2.

**B. The list.** Issue L.
- On a read failure: **DEGRADED**, cause `list-fetch-failed`.
- If L is unparseable: **DEGRADED**, cause `list-unparseable`.
- If a page returns exactly 100 elements, the next page is read, up to page 3. The pages are
  concatenated in order. A read failure or an unparseable result on **any** page is DEGRADED, with the
  cause above. A duplicate `number` across pages is `list-unparseable`. If page 3 also returns exactly
  100 elements: **DEGRADED**, cause `list-page-full`.
- **DEGRADED → the routing is `pr-state-unknown`.** The run renders that directive (§2.7) and exits 3.
  No D or R request is made.

**C. Per worker PR, in list order.** The first match wins. "Stop" means the run sets the aggregate
routing and **reads no later PR** (TD-F7, today's `break`).

| Step | Rule | Class | Per-PR reason token |
|---|---|---|---|
| C1 | Issue D (§2.5) | — | — |
| C2 | `ms == "dirty"` | worker-actionable, `needs-fix`, **stop** | `dirty` |
| C3 | `draft is True` and `needs-ai` ∈ labels | worker-actionable, `needs-fix-bounce`, **stop** | `bounce` |
| C4 | `needs-ai` ∈ labels and `needs-human` ∉ labels | worker-actionable, `needs-fix`, **stop** | `needs-ai` |
| C5 | Issue R (§2.5) | — | — |
| C6 | CR | worker-actionable, `needs-fix`, **stop** | `changes-requested` |
| C7 | **All** of: `detail_ok`, `reviews_ok`, `draft is False`, `hos-halt` ∉ labels; **and** (`needs-human` ∈ labels **or** `approved_on_head`) | **human-pending** | `needs-human` if the label is present, else `approved` |
| C8 | otherwise | **overseer-pending** | the first applicable of `detail-unreadable`, `reviews-unreadable`, `reviews-page-full`, `hos-halt`, `draft`, `approval-untrusted` (`approved_untrusted` and not `approved_on_head`), `approval-not-on-head` (an `APPROVED` exists, but none is on head, or `head_sha` is `None`), `no-approval` |

Steps C2–C6 are today's rules unchanged, in today's order (REQ-C24 item 1). C7 is REQ-C24 item 2,
narrowed by the fail-closed rule and by D-2, D-3 and D-4 (§6). C8 is REQ-C24 item 3.

**D. The aggregate (REQ-C25 table, evaluated in order).** Let *H* be the number of human-pending PRs.

| Condition | Routing | New work |
|---|---|---|
| list DEGRADED (B) | `pr-state-unknown` | BLOCKED |
| a stop happened | the stop's token (`needs-fix` / `needs-fix-bounce`) | BLOCKED |
| any PR is overseer-pending | `needs-attention` | BLOCKED |
| *H* ≥ `HUMAN_PENDING_BOUND` | `human-pending-bound` | BLOCKED |
| 1 ≤ *H* < `HUMAN_PENDING_BOUND` | `human-pending` | **ALLOWED** |
| zero worker PRs | `none` | ALLOWED |

When none of the first three conditions holds, every worker PR is human-pending. So under
`human-pending` and `human-pending-bound`, "the open PRs" and "the human-pending PRs" are the same set.

**Threshold.** The amendment reads the bound as ALLOWED iff *H* < 3 and BLOCKED iff *H* ≥ 3 (REQ-C25
§3). This design adopts that reading.

### 2.7 Directive text (exact)

Notation:
- `<list>` is every worker PR number in list order, rendered `#a, #b, #c`. This matches today's
  `tr`/`sed` rendering at `:1948`.
- `<hp>` is the human-pending PRs, rendered `#a (needs-human), #b (approved)`.
- `<H>` is a decimal number.

Each block is exactly two lines with no trailing newline. The caller adds one (§3.3).

**Unchanged (byte-identical to `:1949-1965` at the baseline; AC-7):**
- `none`:
  - `NEW WORK: ALLOWED`
  - `Reason: no open PRs authored by this worker.`
- `needs-fix`, `needs-fix-bounce` and `needs-attention`:
  - `NEW WORK: BLOCKED`
  - `Reason: routing=<tok> for open PR(s) <list>. ` followed by the token's text copied verbatim from
    `:1953`, `:1955` and `:1959` (without their trailing `\n`).
  - The characterization goldens (§7.2) are the authority on the bytes.

**New:**

```
human-pending:
NEW WORK: ALLOWED
Reason: routing=human-pending for open PR(s) <list>. <H> of 3 worker PRs are human-pending: <hp>. They are reviewed and are awaiting a human, not the worker — nothing to fix on them. This is below the bound of 3, so new work is allowed (ARCH-ESC-1): post the one-time visibility notice on each PR named, then proceed to Step 2.

human-pending-bound:
NEW WORK: BLOCKED
Reason: routing=human-pending-bound for open PR(s) <list>. <H> worker PRs are human-pending (bound 3): <hp>. They are reviewed and are awaiting a human, not the worker — nothing to fix on them. The bound is reached, so new work is blocked (ARCH-ESC-1): post the one-time visibility notice on each PR named. Step 0 triage still runs; STOP after it (do not proceed to Step 2).

pr-state-unknown:
NEW WORK: BLOCKED
Reason: routing=pr-state-unknown (<cause>). This worker's open PRs could not be determined this cycle — this is NOT "no open PRs". Do not re-derive the PR list yourself. Step 0 triage still runs; STOP after it (do not proceed to Step 2).
```

- `<cause>` is one of `list-fetch-failed`, `list-unparseable` or `list-page-full`. From bash it can also
  be `classifier-exit-<rc>`, `classifier-output-invalid` or `not-evaluated` (§3).
- None of the new texts contains `not yet reviewed` (T-1847c).
- The routing tokens `human-pending`, `human-pending-bound` and `pr-state-unknown` are distinct from
  `needs-attention` (REQ-C25 row 3).
- **`awaiting-merge` is retired as a directive token.** Every PR it covered is now either human-pending
  or, under D-2, D-3, D-4 and D-6, overseer-pending.

### 2.8 Output contract

**stdout.** The run prints exactly these lines, in this order, LF-terminated. Values contain only
`[a-z0-9:,-]`.

```
routing=<token>
open_prs=<n,n,...>                 (empty when none or DEGRADED)
human_pending=<n:carrier,...>      (empty when H = 0)
h=<H>
bound=3
new_work=allowed|blocked
cause=<cause>                      (empty unless pr-state-unknown)
directive:
<directive line 1>
<directive line 2>
```

**stderr.** Every line is prefixed `classify_worker_prs: `.
- One line per evaluated PR: `#<n> class=<worker-actionable|human-pending|overseer-pending> reason=<token>`.
- One `unevaluated=#a,#b` line when a stop left PRs unread.
- Exactly one final summary:
  `summary prs=<k> evaluated=<e> h=<H> bound=3 routing=<tok> api_requests=<r> complete=yes|no`.
  `complete` is `no` iff DEGRADED.

**Exit codes.**
- **0**: a determination. This includes per-PR read failures, which classify fail-closed under C8.
- **3**: DEGRADED (B). stdout still carries the full block, with `routing=pr-state-unknown`.
- **2**: an argument error. stdout is empty.
- **Any other exit**, such as an uncaught exception, is a defect. The caller treats it like 2.

**Docstring (the consumer-facing statement).** The docstring states the following:
- the three classes;
- that B = 3 is fixed, with no flag, environment variable or config;
- that a PR counts toward B only when the run positively read `needs-human` on it, or an `APPROVED`
  review on its current head commit from a non-bot `OWNER`, `MEMBER` or `COLLABORATOR`;
- that setting `HUMAN_PENDING_BOUND = 1` reproduces the pre-T3.0b serialization exactly. That is the
  predeclared revert path;
- that any unread state blocks new work;
- that a list failure blocks new work for that cycle ("this is not 'no open PRs'").

---

## 3. `bin/hos-cron`: the thin call-site

### 3.1 The fail-closed default (closes TD-F8)

Before the worker gate block at `:1017`, set `_PR_DIRECTIVE` unconditionally to the `pr-state-unknown`
text with cause `not-evaluated`, set `_PR_ROUTING=pr-state-unknown`, and set `_OPEN_PR_NUMS=""`. This
is a fixed literal, the only directive literal left in bash besides §3.2's fallback. Both are the same
template with a different cause.

### 3.2 The replacement for `:1042-1128`

1. Invoke the classifier with the selector's `set -e`-safe idiom (`:1155-1157`):
   `(cd "$REPO_ROOT" && python3 -m scripts.framework.classify_worker_prs --repo "$_REPO_SLUG" --author "$HOS_BOT_LOGIN")`,
   with stdout captured and stderr sent to a `mktemp` file, then `&& _cls_rc=0 || _cls_rc=$?`.
2. `cat` the stderr file to stderr (DEV-2 parity: nothing is swallowed), then remove it.
3. Run `case "$_cls_rc"`:
   - **0**: parse, then `_gate_pr_fetch_ok=1`;
   - **3**: parse, then `_gate_pr_fetch_ok=0`;
   - **`*`**: `_gate_pr_fetch_ok=0`, `_PR_ROUTING=pr-state-unknown`, and `_PR_DIRECTIVE` is the
     fallback template with cause `classifier-exit-<rc>`.
4. **Parse.** Read stdout line by line up to the `directive:` sentinel.
   - Accept only the keys `routing`, `open_prs`, `human_pending`, `h` and `cause`, through a `case` on
     the key. Ignore unknown keys. **Never `eval` or `source` anything.**
   - Everything after the sentinel is `_PR_DIRECTIVE`.
   - The parse is invalid if `routing` is empty, if `routing` is not one of the seven tokens, if `h` is
     not all digits, if `open_prs` is not `^([0-9]+(,[0-9]+)*)?$`, or if the first directive line is
     not exactly `NEW WORK: ALLOWED` or `NEW WORK: BLOCKED`. An invalid parse is handled as `*` with
     cause `classifier-output-invalid`.
   - `_OPEN_PR_NUMS` becomes `open_prs` with commas replaced by newlines. That preserves the variable's
     format for `:1185` and for the `_audit` `pr_nums=` expansion.
5. **Side effects, keyed on `_PR_ROUTING`.** These are the only remaining branch logic in bash:
   - `human-pending-bound`: echo `$LOG_PREFIX <h> open PR(s) human-pending (bound 3) — new work blocked, Step 0 triage still runs (ARCH-ESC-1)`;
     `_audit cycle-skip reason=human-pending-bound "pr_nums=<csv>" "h=<h>"`; write the overseer wakeup
     file exactly as `:1121-1123`.
   - `human-pending`: echo `$LOG_PREFIX <h> open PR(s) human-pending (<h> of 3) — new work allowed (ARCH-ESC-1)`;
     `_audit cycle-human-pending "pr_nums=<csv>" "h=<h>" "bound=3"`; write the same overseer wakeup.
     This preserves `awaiting-merge`'s side-effect condition: every open PR is waiting on someone other
     than the worker.
   - `needs-attention`: the echo and `_audit` are **unchanged**, byte for byte (`:1125-1126`).
   - `pr-state-unknown`: echo `$LOG_PREFIX open-PR state unknown (<cause>) — new work blocked, Step 0 triage still runs`;
     `_audit cycle-pr-state-unknown "cause=<cause>"`.
   - `needs-fix`, `needs-fix-bounce` and `none`: no side effect (as today).
6. `_pr_count` is gone. The new lines use `h`. The `needs-attention` line keeps its own count, which is
   the number of lines in `_OPEN_PR_NUMS`, computed as today.

### 3.3 `_build_context`

Replace the `if [[ -n "${_OPEN_PR_NUMS:-}" ]] … else … fi` at `:1947-1965` with one
`printf '%s\n' "$_PR_DIRECTIVE"`. The heading line `:1946` and the trailing `printf '\n'` at `:1966`
are unchanged. The command substitution strips the classifier's trailing newline, and this `printf`
restores exactly one. The section bytes are therefore identical to today's for every unchanged token
(T-DIR1, C-goldens).

### 3.4 What does not change

- The `#1395` skip condition (`:1179-1189`) is unchanged. A classifier exit of 3 or `*` sets
  `_gate_pr_fetch_ok=0`, which means "unknown, never skip", as today.
- The overseer path is unchanged.
- The display-only "### Open bot PRs" fetch is unchanged.
- The worker-only scoping of the directive (`:1944`) is unchanged.

---

## 4. Prompt contract and the visibility notice (REQ-C25 "one decision authority", REQ-C26)

### 4.1 `bootstrap/worker-cron-prompt.md`

- **Step 0.5, R2 deferral (`:59-63`).** Replace "For `awaiting-merge` or `needs-attention`, run R2
  normally" with "For `human-pending`, `human-pending-bound`, `needs-attention` or `pr-state-unknown`,
  run R2 normally". The `needs-fix` deferral and its wording are unchanged.
- **Step 1 (`:70-79`).** These bullets replace the `awaiting-merge`/`needs-attention` bullet:
  - `NEW WORK: ALLOWED`, reason cites `human-pending`: for **each** PR the reason names, post the
    visibility notice (§4.3). Then proceed to Step 2. Take no other action on those PRs.
  - `NEW WORK: BLOCKED`, reason cites `human-pending-bound`: post the notice on each PR named, then
    STOP after Step 0.
  - `NEW WORK: BLOCKED`, reason cites `needs-attention`: nothing to fix. STOP after Step 0, with **no**
    notice. This is the existing text minus `awaiting-merge`.
  - `NEW WORK: BLOCKED`, reason cites `pr-state-unknown`: nothing to fix. **Do not** list or read PRs
    yourself to second-guess it. STOP after Step 0.
  - `NEW WORK: ALLOWED` with any other reason: proceed to Step 2 (unchanged).
- The "Directive line absent" fallback (the strictest rule, where any open PR blocks) is **unchanged**,
  except for one point. It stays stricter than the directive, which is the intended direction.
- **The exception: P1 is closed (ADR Erratum 2 E11).**
  - In the fallback's `dirty` instruction (`:90`), delete the sentence that cherry-picks and
    "force-push[es] to the **same remote branch name**".
  - The instruction becomes: close the PR with a comment explaining the conflict; create a fresh branch
    from current `main` with `bootstrap/create_branch.sh`; cherry-pick only the unique commits; and open
    a new PR with `bootstrap/submit_pr.sh` (its #1162 merge-from-base guard applies).
  - No `--force` or force-push wording may remain anywhere in `worker-cron-prompt.md`. Add a static
    assertion **T-1847f** in §7.3 with a case-insensitive regex for `force-push`, `force push`, `--force`
    and `-f ` after `git push`.
- **Do not restate the bound or any re-blocking rule** in the prompt (REQ-C25, #1198 item 6). The
  prompt names tokens only.

### 4.2 `.claude/agents/worker.md`

The same changes apply to `:323-349` and `:576-580`. This file is a governance artifact, so it is
authored by the top-level worker session per CLAUDE.md's agent-definition rule (#1347), **not** by
`coder`. The coder's PR description must say which session authored it.

### 4.3 The notice (REQ-C26, #1847)

- **Marker.** The marker is unchanged: `<!-- hos-worker-merge-block -->`. Notices already posted on
  open PRs are therefore still recognized, and a PR that moves from one carrier to the other (for
  example from `needs-human` to `approved`) gets one notice per block, not two.
- **Mechanism.** The mechanism is unchanged and model-posted:
  1. Check `bash bootstrap/query_issues.sh --app worker --comments <n>` for the marker.
  2. If the marker is absent, post through `bash bootstrap/post_comment.sh --number <n> --body-file <path> --app worker`.
  3. Include the marker in the body.
- **Content.** The carrier comes from the directive's `(needs-human)` / `(approved)` tag:
  - **needs-human**: "This PR has been reviewed and is waiting on a human decision (`needs-human`). The
    worker will not act on it until a human resolves it."
  - **approved**: "This PR is approved and awaiting a human merge."
  - Both may add that new work continues while fewer than 3 PRs are waiting.
  - **Neither may say "not yet reviewed"** (REQ-C26).
- **Coverage.** The notice fires for the human-pending PRs the directive names, under **both**
  `human-pending` and `human-pending-bound` (REQ-C26 "whether or not new work is allowed").
  - Under `needs-attention`, the human-pending PRs are classified but not named in the directive
    text, so the worker cannot see them. That is because `needs-attention`'s text must stay
    byte-identical (AC-3, AC-7).
  - Under a `needs-fix` stop, later PRs are unread (TD-F7).
  - In both cases the notice is deferred to the first cycle whose directive names the PR. §9 OQ-6 asks
    the architect to accept this.

---

## 5. Docs and registration

- **`framework_consumer_files.txt`**: one line, added directly under `select_work_candidates.py`.
- **`docs/LABELS.md`**:
  - `needs-human` row, consumers column: add "**Worker PR routing.** On an open worker PR, `needs-human`
    (with no `hos-halt`, not draft, and both reads succeeding) makes the PR human-pending, which counts
    toward the bound of 3 instead of blocking new work (`scripts/framework/classify_worker_prs.py`,
    ARCH-ESC-1)."
  - `needs-ai` row: re-point `bin/hos-cron:1085` and `:~1094` to `classify_worker_prs.py` steps C3 and
    C4.
  - `hos-halt` row: add "on a PR it also disqualifies human-pending (race window only, since the
    `:918` check already halts the cycle)".
- **`DECISIONS.md`**: append a `## 2026-10-0x — Worker PR serialization relaxed to a human-pending
  bound of 3 (ARCH-ESC-1, #1912; amends 2026-08-09 #1198)` entry. It records the decision, the bound,
  that overseer-pending PRs still block, the fail-closed carriers, and the H-1 reconfirmation and its
  outcome. Its Scope line lists files 1–10. It also records:
  - #1313's P1 as closed by this PR;
  - the ARCH-ESC-1R answers on `strict` and on #1313's disposition;
  - the predeclared abort triggers (ADR Erratum 2, ARCH-ESC-1R Q2), with the revert being
    `HUMAN_PENDING_BOUND = 1`.
- **`SCRIPTS-INDEX.md`**: regenerate it.

---

## 6. Rulings on PM-6's open questions, and the deviation register

Every item below is **stricter** than the literal reading it replaces. None of them makes a PR count
toward *H* that the amendment would not count. Each needs architect approval (§9).

**Q1: T-NS5's wording.**
- **Decision:** adopt AC-1's restatement. This is a test clarification within design authority, and it
  needs architect confirmation as an ADR erratum.
- The ADR's three H4 *shapes* (HUMAN_REQUIRED, `needs-human` on the PR, awaiting a human merge) are
  carried by **two** carriers (VF-P2). A HUMAN_REQUIRED verdict reaches the PR as `needs-human`.
- One PR per *shape* would give *H* = 3, which the ruling blocks. That contradicts T-NS5's `ALLOWED`.
- The tests are therefore:
  - **T-NS5**: one PR per carrier (*H* = 2) plus an eligible issue gives `ALLOWED`;
  - **T-NS5-shapes**: each of the three ADR shapes **alone** gives `ALLOWED` with *H* = 1, which proves
    that every named shape is recognized;
  - **T-BD1**: three human-pending PRs give `BLOCKED`.
- Together these satisfy both the ADR's intent and the bound.

**Q2: `hos-halt` on a PR.**
- **Decision: blocks (D-2).** A PR carrying `hos-halt` is never human-pending (C7). It is
  overseer-pending, reason `hos-halt`, **even when** it also carries a carrier. That is stricter than
  REQ-C24 2(a)/(b) read literally, and it is consistent with AC-5's "`hos-halt` alone → blocks".
- **Why this is within design authority:**
  - per TD-F1, the case is reachable only in the race window between `:918` and `:1048`. In every other
    case the whole cycle halts first;
  - "halt" never releasing work is the only safe reading of a kill-switch label;
  - it changes nothing outside that window.
- The PM framed this as a human question ("whether a halted PR should count toward H"). I submit that
  TD-F1 makes the question moot in practice. The architect may still route it to the human.

**Q3: the list-failure fail-open.**
- **Decision: fail closed (D-1).** This is a **deliberate deviation** from the T3.0b row's "behavior is
  preserved", and it needs explicit architect approval.
- On a list read failure, an unparseable list, or a full list page, the classifier exits 3 and the
  directive is `NEW WORK: BLOCKED`, `routing=pr-state-unknown`. Today the directive is `ALLOWED`.
- The bash default (§3.1) and fallback (§3.2 `*`) extend the same rule to the empty-slug path (TD-F8)
  and to a classifier crash.
- **Why:**
  1. **ADR §1 governs this module.** "Every 'unknown' … never resolves to 'not blocked'". AD-C3 step 2
     names this classifier as part of the cycle that the constraint governs.
  2. **The ruling's bound is only a bound if unknown state cannot bypass it.** REQ-C25 makes B a fixed
     constant that "no environment variable, flag or config value can raise". A fail-open list read
     raises it to unbounded for that cycle. Today the same hole defeats the N = 1 serialization.
  3. **The cost is small and self-correcting.** It is one cycle with no new work. Step 0 and Step 0.5
     still run, the #1395 skip is still suppressed, and the next cycle re-reads.
  4. **TD-F4's truncation is the same hole**, and it is closed by the same rule.
- **If the architect rejects D-1:** the classifier still exits 3, but it renders today's
  `NEW WORK: ALLOWED` / `Reason: no open PRs authored by this worker.` for `list-fetch-failed`. The
  §3.1 default becomes that text, and a `spec-gap` goes to the human per PM Q3's recommendation. T-FC7
  to T-FC9 and T-HC3 flip accordingly. Nothing else changes.

**Q4: stale approvals.**
- **Decision: carrier (b) requires an approval on the current head commit (D-3).** That means an
  `APPROVED` review with `commit_id == head.sha`, at zero added requests (TD-F3). A PR whose only
  approvals are on older commits is overseer-pending, reason `approval-not-on-head`, because the
  overseer owes it a re-review.
- This is stricter than PM's preserve-and-flag default. It cannot release work that today's code would
  not release, since today nothing is released at all. It matches the overseer's own head-SHA control
  (`DECISIONS.md:654`).
- Under `dismiss_stale_reviews: true`, the case is rare.

**Additional precision points (my own, flagged):**

- **D-4: a draft PR is never human-pending.** A draft cannot be merged, so it is not "awaiting a human
  merge". The realistic case is a bounced draft left open after the worker cleared `needs-ai` (the
  bounce re-entry opens a new PR). Today such a draft blocks as `awaiting-merge` or `needs-attention`.
  Under D-4 it blocks as `needs-attention`.
- **D-5: list and reviews are read at 100 per page, and a full page is unknown** (TD-F4). The
  request count is unchanged or lower.
- **D-6: a detail or reviews read failure on a PR that today would be `awaiting-merge` now routes to
  `needs-attention`** (C8 `detail-unreadable` / `reviews-unreadable`). This is AC-5 applied literally.
  - It conflicts with a literal reading of AC-7 ("byte-identical for every fixture with no human-pending
    PR"). The fixture has no human-pending PR under the new rules, but today it renders the
    `awaiting-merge` text.
  - AC-5 is the stricter rule, so I let it govern. Both outcomes are BLOCKED, and only the reason token
    differs.
  - The characterization test C13 flips, and it is named in §8.

**Third-party approvals (D-7; superseded by the architect's ruling on §9 OQ-4).** The draft let carrier
(b) count an `APPROVED` review from any author. **The architect ruled against that** (ADR Erratum 2 E9):
- carrier (b) requires `author_association` ∈ `TRUSTED_APPROVER_ASSOCIATIONS` **and** a non-`[bot]`
  login (§2.5);
- an approval that fails the author test classifies the PR as overseer-pending, reason
  `approval-untrusted`;
- the cost is zero requests, because both fields are on each review object already fetched.

Without this, anyone able to post a review could release new work. It fails toward blocking.

---

## 7. Test plan

### 7.0 Commit order (characterize first, then move)

The PR has at least two commits, and reviewers verify the order:

1. **Commit 1** adds `gh_pulls_fixture.py`, the stub delegation, and `TestPRRoutingCharacterization`
   (§7.2), with **no change** to `bin/hos-cron`. The full `test_hos_cron.py` must be green at this
   commit. The PR description states the command that reproduces this:
   `git checkout <commit-1> && scripts/oversight/.venv/bin/pytest tests/automation/test_hos_cron.py -q`.
2. **Commit 2 and later** add the module, the call-site, the prompt/docs changes, and the new tests.
   They flip **exactly** the characterization cases marked FLIP below and the three existing tests in
   §8. Every other characterization case passes unedited (AC-7).

### 7.1 The fake: `tests/automation/gh_pulls_fixture.py`

This is an executable Python script. `CronEnv`'s `gh` stub delegates to it, as its first arm, for any
argv whose endpoint contains `/pulls`, when **either** `HOS_TEST_PR_FIXTURE` is set **or** the argv
carries no `--jq`. Every other call keeps today's stub arms, so the overseer's `--jq` calls and the
legacy env-var tests are unaffected.

- **Fixture mode** (`HOS_TEST_PR_FIXTURE=<path to JSON>`). The file is:

  ```
  {"list_fail": bool,
   "prs": [{"number", "author", "title", "ms", "draft", "labels", "head_sha",
            "detail_fail", "reviews_fail",
            "reviews": [{"state", "commit_id", "user", "author_association"}],
            "comments": [...]}]}
  ```

  The `comments` field is served by nothing, on purpose. It lets T-FC3 and T-1847 carry an inline
  HUMAN_REQUIRED verdict that must stay unread.
- **Env-var mode** (no fixture). It synthesizes the same structure from `HOS_TEST_OPEN_PR_NUMS`,
  `HOS_TEST_PR_MS`, `HOS_TEST_PR_DRAFT`, `HOS_TEST_PR_LABELS`, `HOS_TEST_PR_CR` and `HOS_TEST_PR_AP`
  (default `1`). Every PR is authored by the stub's bot login, has `head_sha = "a"*40`, and its
  approvals use that `commit_id`, `author_association: "OWNER"` and a non-`[bot]` user login. Existing
  tests therefore exercise the classifier with today's meaning.
- **List pages.** The fake serves `&page=<k>` by slicing the fixture's full PR list, foreign authors
  included, in steps of `per_page`. A page past the end is `[]`. Optional `"list_fail_pages": [k, ...]`
  gives exit 1 on those pages only.
- **Shapes served.**
  - Today's `--jq` shapes: the list filter → numbers of PRs by the given author; detail →
    `{"ms","d","labels"}`; the CR count; the AP count; and `_build_context`'s title line.
  - The classifier's raw L, D and R shapes: full JSON with `number`, `user.login`, `draft`, `labels`,
    `mergeable_state`, `head.sha`; reviews with `state`, `commit_id`, `user.login`.
  - `*_fail` gives exit 1.
- **Call log.** Each routing-family call (the list *without* `.title`, D, R, and today's CR/AP) appends
  one line, `<family> <n|-> <shape:jq|raw>`, to `HOS_TEST_PR_CALL_LOG` when that variable is set.

### 7.2 Characterization: `TestPRRoutingCharacterization` (commit 1, against unmodified `bin/hos-cron`)

Each case asserts:
- the **whole** "### New work directive" section, as bytes from the heading to the next `###` (the
  golden);
- the routing-related stdout line, or its absence;
- `TODAY_REQUESTS[<case>]`, the call-log line count.

Goldens and counts are module-level constants, so commit 2 can reuse them.

| Case | Fixture | Today's golden routing | After the move |
|---|---|---|---|
| C1 | no worker PRs | ALLOWED, `no open PRs …` | **unchanged** |
| C2 | 1 PR `dirty` | `needs-fix` | unchanged |
| C3 | 1 PR draft + `needs-ai` | `needs-fix-bounce` | unchanged (#1350) |
| C4 | 1 PR `needs-ai`, no `needs-human` | `needs-fix` | unchanged (#1522) |
| C5 | 1 PR with one CR review | `needs-fix` | unchanged |
| C6 | 1 PR, no reviews | `needs-attention`, plus stdout "unreviewed" | unchanged |
| C7 | 1 PR dirty + draft + `needs-ai` | `needs-fix` (order) | unchanged (#1350) |
| C8 | 1 PR `needs-ai` + `needs-human`, AP = 0 | `needs-attention` | **FLIP** → `human-pending`, ALLOWED, *H* = 1. #1526's "not `needs-fix`" still holds. |
| C9 | 1 PR AP = 1 | `awaiting-merge`, plus stdout "awaiting human merge" | **FLIP** → `human-pending`, ALLOWED |
| C10 | PRs [A unreviewed, B dirty, C AP = 1] | `needs-fix`, and **C is never read** (call log) | unchanged, and C still unread |
| C11 | PRs [A dirty, B unreviewed] | `needs-fix`, and B is never read | unchanged |
| C12 | [foreign-author AP = 0, bot AP = 0] | `needs-attention` listing only the bot PR | unchanged |
| C13 | 1 PR, detail fails, AP = 1 | `awaiting-merge` | **FLIP** → `needs-attention` (D-6) |
| C14 | 1 PR, reviews fail | `needs-attention` | unchanged |
| C15 | list fails | ALLOWED, `no open PRs …` | **FLIP** → BLOCKED `pr-state-unknown (list-fetch-failed)` (D-1) |
| C16 | the counts above | `TODAY_REQUESTS` exact | becomes: new count == `NEW_REQUESTS[case]` **and** ≤ `TODAY_REQUESTS[case]` (AC-8) |

### 7.3 Unit: `tests/framework/test_classify_worker_prs.py` (in-process)

`_run_gh` is monkeypatched to a stub that serves a per-endpoint dict (payload or failure) and records
calls in order. Records are built by helpers `_pr(...)`, `_detail(...)` and
`_review(state, commit_id, association="OWNER", login="human-reviewer")`.

**Classification (REQ-C24):**

| ID | Asserts |
|---|---|
| T-CL1 | Each of C2–C6 and C8 `no-approval` in isolation gives the expected class, token and per-PR reason. |
| T-CL2 | Order: dirty beats bounce, bounce beats needs-ai, and needs-ai beats CR. Each pair gives the earlier token. |
| T-CL3 | A stop reads no later PR: the calls contain no D or R for PRs after the stop, and stderr has `unevaluated=`. |
| T-CL4 | `needs-attention` does not stop: a later dirty PR gives `needs-fix`. |
| T-CL5 | A foreign-author PR is ignored: no D or R is made for it, and it is not in `open_prs`. |

**T-NS5 and the shapes (AC-1):**

| ID | Asserts |
|---|---|
| **T-NS5** | PR A has `needs-human`, one `COMMENTED` review by the overseer login, and **an inline HUMAN_REQUIRED comment in the fixture** (the #1845 shape). PR B has one `APPROVED` review on head and no labels. The result is `routing=human-pending`, `new_work=allowed`, `h=2`, `human_pending=A:needs-human,B:approved`, and the directive line 2 names both. |
| T-NS5a / T-NS5b | Each carrier alone gives ALLOWED with *h* = 1. |
| T-NS5-shapes | The three ADR shapes, each alone: (i) HUMAN_REQUIRED (`needs-human` + COMMENTED + inline verdict); (ii) `needs-human` only, with no reviews; (iii) approved on head. Each gives ALLOWED with *h* = 1. |

**The bound (AC-2, REQ-C25):**

| ID | Asserts |
|---|---|
| **T-BD1** | 3 human-pending PRs (a mix of 2 needs-human and 1 approved) give `human-pending-bound`, BLOCKED, `h=3`, and the text contains "reviewed and are awaiting a human" and "bound 3". |
| T-BD2 | 4 human-pending PRs give BLOCKED, `h=4`. |
| T-BD3 | 2 human-pending PRs give ALLOWED. This is the boundary below. |
| T-BD4 (static) | `HUMAN_PENDING_BOUND == 3`. The argparse parser has exactly `--repo` and `--author`. An AST walk finds no `os.environ`, `os.getenv`, `open(` or `Path.read_text`, and no imports beyond stdlib `argparse, json, re, subprocess, sys` (plus `typing`/`dataclasses`). |
| T-BD5 | `main(["--repo","o/r","--author","x","--bound","5"])` exits 2 with no `gh` call. |
| T-BD6 (revert path) | With `HUMAN_PENDING_BOUND` monkeypatched to `1`, `new_work` equals today's ALLOWED/BLOCKED outcome for every C1–C14 fixture: ALLOWED iff there are zero worker PRs. C15 is the D-1 exception. This pins the revert path that ARCH-ESC-1R Q2 predeclares. |

**Overseer-pending still blocks (AC-3):**

| ID | Asserts |
|---|---|
| T-OP1 (parametrized 0/1/2) | One unreviewed PR plus *k* human-pending PRs gives `needs-attention`. The directive equals the C6 golden with `<list>` substituted (today's text). |

**Worker-actionable precedence (AC-4):**

| ID | Asserts |
|---|---|
| T-WA1 (parametrized 4 triggers × 0/1/2 HP) | Gives today's token and text. Any HP PRs placed **before** the trigger in list order are classified, and none after it are read. |
| T-WA2 | `needs-human` plus each of dirty, CR, and draft + `needs-ai` gives worker-actionable. |

**Fail-closed (AC-5, D-1 to D-6):**

| ID | Asserts |
|---|---|
| T-FC1 | Detail fails on a PR with `needs-human` + approved gives overseer-pending, `detail-unreadable`. |
| T-FC2 | Reviews fail on a `needs-human` PR gives overseer-pending, `reviews-unreadable`. |
| T-FC3 | An inline HUMAN_REQUIRED comment with no label gives overseer-pending, and **no endpoint containing `/comments`, `/events` or `/timeline` is called**. |
| T-FC4 | `hos-halt` + `needs-human`, and `hos-halt` + approved, each give overseer-pending, `hos-halt`. |
| T-FC5 | Draft (no `needs-ai`) + approved, and draft + `needs-human`, each give overseer-pending, `draft`. |
| T-FC6 | An approval with `commit_id` ≠ head gives `approval-not-on-head`. Missing `head.sha` + approval gives the same. Missing `head.sha` + `needs-human` gives human-pending, because carrier (a) does not need the SHA. |
| T-FC7 | L fails: exit 3, `routing=pr-state-unknown`, `cause=list-fetch-failed`, BLOCKED, the exact §2.7 text, and zero D/R calls. |
| T-FC8 | L is not an array, or an element lacks `user.login`: exit 3, `list-unparseable`. |
| T-FC9 | Three full pages (300 PRs): exit 3, `list-page-full`, and exactly three L calls. 100 PRs: two L calls (page 2 is `[]`), and a determination. A worker PR at position 150 is classified. Page 2 failing after a full page 1: exit 3, `list-fetch-failed`. A duplicate number across pages: `list-unparseable`. |
| T-FC12 | An `APPROVED` review on head with `author_association` of `NONE`, `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` or missing, or with a `[bot]` login, gives overseer-pending, `approval-untrusted`. The same review with `OWNER` and a human login gives human-pending, `approved`. |
| T-FC10 | R returns 100 reviews with no CR: `reviews-page-full`. With a CR at index 99: `needs-fix`. |
| T-FC11 | The label `Needs-Human` (case variant) is not a carrier. |

**#1847's three states (AC-6):**

| ID | Asserts |
|---|---|
| T-1847a | Unreviewed gives `needs-attention`, with today's text (the C6 golden). |
| T-1847b | `COMMENTED` with no `needs-human` gives overseer-pending, BLOCKED, `needs-attention`. |
| T-1847c | `COMMENTED` + `needs-human` + inline HUMAN_REQUIRED gives human-pending. The directive does **not** contain `not yet reviewed`, and does contain `reviewed and are awaiting a human`. This holds for both the `human-pending` and `human-pending-bound` texts. |
| T-1847d (prompt contract, static) | `worker-cron-prompt.md` Step 1 has a bullet for `human-pending` **and** one for `human-pending-bound`. Each includes the literal `NOTICE_MARKER` (imported from the module), `query_issues.sh --app worker --comments`, and `post_comment.sh`. Both notice-content sentences are present. No line in those bullets contains `not yet reviewed`. The token `awaiting-merge` appears nowhere in Step 0.5 or Step 1. |
| T-1847e (static) | The same assertions as T-1847d against `.claude/agents/worker.md`. |
| T-1847f (static, P1) | `worker-cron-prompt.md` contains no force-push instruction (§4.1 regex). Its `dirty` fallback names both `create_branch.sh` and `submit_pr.sh`. |

**Directive rendering (AC-7):**

| ID | Asserts |
|---|---|
| T-DIR1 | For C1–C7, C10–C12 and C14, the module's rendered block equals the characterization golden with the heading stripped, byte for byte. The goldens are imported from one shared constants location, so they are not copied twice. |
| T-DIR2 | The `<list>` rendering for 1, 2 and 3 PRs equals `#a`, `#a, #b` and `#a, #b, #c`. |

**Zero added requests (AC-8):**

| ID | Asserts |
|---|---|
| T-ZC1 | Golden call lists. For example, C9's fixture gives `[L, D, R]` (3), against today's 4. For every C-case fixture, `len(calls) <= TODAY_REQUESTS[case]`. |
| T-ZC2 (static) | An AST walk finds that the only endpoint string templates are L (with its `page` parameter), D and R (§2.4). No string contains `--paginate`, `graphql`, `/comments`, `/events` or `/timeline`. `subprocess` is referenced only inside `_run_gh`. There are no imports of `urllib.request`, `http`, `requests`, `socket` or `scripts.automation.lib.github`. |

**CLI:**

| ID | Asserts |
|---|---|
| T-CLI1 | The stdout key order is exact. Values match `[a-z0-9:,-]*`. The `directive:` sentinel is present. The stderr summary line's fields are present, and `api_requests` equals the number of calls. |
| T-CLI2 | A bad `--repo` or a bad `--author` (a space, or 40+ characters) exits 2 with no `gh` call. |

### 7.4 Launcher integration: `tests/automation/test_hos_cron.py` (commit 2)

| ID | Asserts |
|---|---|
| **T-NS5-HC** | The ADR's literal T-NS5 under the real launcher: the T-NS5 fixture (2 PRs) **plus** `HOS_TEST_ISSUE_CANDIDATES_JSON` with one eligible issue and a milestone set. The context has `NEW WORK: ALLOWED` and `routing=human-pending`, and the candidate line is rendered. stdout has `human-pending (2 of 3)`. |
| T-HC-BD | 3 human-pending PRs: `NEW WORK: BLOCKED`, `routing=human-pending-bound`, the stdout line, and the overseer wakeup written. |
| T-HC-UNK | `HOS_TEST_PR_FETCH_FAIL=1` (env-var mode) gives `routing=pr-state-unknown (list-fetch-failed)`. Claude still runs, and there is **no** #1395 skip. |
| T-HC-CRASH | `HOS_TEST_BOT_LOGIN` = `HOS_TEST_EXPECTED_BOT` = `"bad login"`, so the identity guard passes and the classifier exits 2. The result is `pr-state-unknown (classifier-exit-2)` and BLOCKED. |
| T-HC-STDERR | stderr carries `classify_worker_prs: summary` (passthrough). |
| T-HC-2CYC (#1847, AC-6) | Two consecutive `cron.run`s with the T-1847c fixture. Both directives are identical and both name the PR with `(needs-human)`. Neither contains `not yet reviewed`. This pins the deterministic half of "exactly once across two cycles". The model-side marker check is T-1847d/e (§9 OQ-5). |

### 7.5 Traceability

| Clause | Tests |
|---|---|
| T3.0b row: routing moved into a tested Python classifier | C1–C16, T-CL*, T-DIR1 |
| Behavior preserved except H4 (AC-7) | C1–C7, C10–C12, C14 unchanged; T-DIR1 |
| H4 no longer blocks (AF-C2, ESC-8) | T-NS5, T-NS5a/b, T-NS5-shapes, T-NS5-HC, C8/C9 flips |
| AD-C6 T-NS5 | T-NS5, T-NS5-HC (with Q1's restatement) |
| REQ-C24 order: worker-actionable before human-pending | T-CL2, T-WA1, T-WA2, C7 |
| REQ-C24 fail-closed rule | T-FC1 to T-FC6, T-FC11, T-FC3 (no comment reads) |
| REQ-C25 bound, the threshold reading, no env/config | T-BD1 to T-BD5, T-HC-BD |
| REQ-C25 overseer-pending blocks (AC-3) | T-OP1 |
| REQ-C25 one decision authority | T-1847d/e (the `awaiting-merge` re-block is gone; tokens only) |
| REQ-C26 / #1847 notice | T-1847c/d/e, T-HC-2CYC |
| AC-8 zero added requests | C16, T-ZC1, T-ZC2 |
| ADR §1 unknown never "not blocked" (D-1) | T-FC7 to T-FC9, T-HC-UNK, T-HC-CRASH, C15 flip |
| #1350 / #1522 / #1526 sign-offs re-pinned | C3, C7 / C4 / C8 (not `needs-fix`) and T-WA2 |
| TD-F5 consumer shipping | the existing `test_consumer_framework_files.py`, with the new line listed |

---

## 8. Affected existing tests and sign-offs (the startup-gap analysis)

**Should this have been settled in the initial design?**
- **For the routing move: no.** T3.0b exists because of ARCH-ESC-1, which was ruled today.
- **For TD-F6: yes, at the ADR level.**
  - ADR AF-C2 named #1162 as the prerequisite and missed #1313's P1, P2 and P5 (`DECISIONS.md:662`).
  - That is a `startup-artifact-gap` in the ADR's verification. **I recommend that the architect open
    one.** I have not filed it, per this task's constraints.
  - No code has been built against T3.0b, so **no sign-off is orphaned** by it.

**Existing tests whose expectation changes (named; commit 2):**
1. `TestPRRoutingSkip::test_awaiting_merge_still_launches_claude_for_triage`. Rename it to
   `test_human_pending_pr_allows_new_work_and_launches_claude`. It now asserts `NEW WORK: ALLOWED`,
   `routing=human-pending`, and stdout `human-pending (1 of 3)`. Claude-launch is still asserted. This
   is the "awaiting-merge produces BLOCKED" test that ADR §11 flags.
2. `TestCycleContextBlock::test_context_block_present_when_awaiting_merge`. It now asserts
   `NEW WORK: ALLOWED` and that the context block is present.
3. `TestCycleContextBlock::test_context_block_needs_ai_and_needs_human_labels_falls_through_to_review_state`.
   It now asserts `routing=human-pending`. It keeps `"routing=needs-fix" not in context`, which is
   #1526's property. Its docstring adds "lands in human-pending (T3.0b, #1847)".

**Unchanged by design**, listed so a reviewer can check them rather than trust "suite green":
- `test_awaiting_merge_drops_overseer_wakeup` (docstring only: "human-pending");
- `test_awaiting_merge_stamps_last_run`;
- `test_no_open_prs_launches_claude`;
- `test_changes_requested_launches_claude`;
- `test_unapproved_pr_launches_claude`;
- both overseer-role routing tests;
- `TestActionableWorkGate::test_open_pr_alone_proceeds` (*H* = 1, so it still proceeds) and
  `test_query_failure_does_not_skip`;
- `TestSelectionGateCallerContract::test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip`;
- every `TestCycleContextBlock` needs-fix, needs-fix-bounce or needs-attention case;
- `TestReleaseRequestContextBlock`.

**Sign-offs:**
- **These stand, re-pinned against the classifier (ADR §11):** #1350 (C3, C7), #1522 (C4) and #1526
  (C8's "not `needs-fix`"), plus #791's "Claude still launches for triage", because the side-effect
  branches are preserved.
- **These are cleared by ARCH-ESC-1, subject to H-1:** #1198's serialization sign-off and the
  2026-08-09 `DECISIONS.md` entry, which file 10 amends.
- **These re-open for this PR's own review, not retroactively:** the directive's exact text and its
  single-authority rule (#1198 item 4). The routing logic moves from bash to Python, so `code-reviewer`
  and `security-reviewer` review §2.6's order and §3.2's parse (no `eval`, validated values).
  **No already-approved code is orphaned.**

---

## 9. Open questions

**H-1 (for the human, through the architect; it blocks `coder` handoff).** *Superseded by ARCH-ESC-1R in
ADR-1644 Erratum 2, which corrects the count and the prerequisite facts below and bounds the question.
That erratum is the text to file. The original is kept for the record.*

> ARCH-ESC-1 was ruled on ADR text stating that #1162, "the prerequisite", is present. `DECISIONS.md`
> (2026-08-09) and **#1313** (open, `needs-human`) hold *three further blocking* prerequisites for any
> worker concurrency above 1:
> - P1: close the force-push bypass in `worker-cron-prompt.md`'s conflict path, which is still present
>   at `:90`;
> - P2: set branch protection `required_status_checks.strict: true`, which is still `false`;
> - P5: a field observation of the #1162 guard firing.
>
> #1313 also flags that `dismiss_stale_reviews: true` can *increase* human work when sibling PRs merge.
> The ruled bound (3 human-pending plus 1 overseer-pending) exceeds #1313's N = 2.
>
> **Does the ruling knowingly supersede #1313's prerequisites, or must P1, P2 and P5 land first?**

My recommendation is that the architect put this to the human verbatim. The design is unaffected
either way. Only *when* it ships changes, along with `DECISIONS.md` entry 10's text and #1313's
disposition.

**OQ-1 (Q1).** Confirm the T-NS5 restatement (§6 Q1) and record it as an ADR erratum to AD-C6.

**OQ-2 (Q3, D-1).** Approve fail-closed on list failure, truncation, slug-empty and classifier crash,
as a deliberate deviation from "behavior preserved". The rejection path is specified in §6 Q3.

**OQ-3 (Q2, Q4, D-2 to D-6).** Approve the stricter narrowings. If you judge that Q2 must still go to
the human despite TD-F1, say so. The default stays "blocks".

**OQ-4 (third-party approvals).** Carrier (b) counts any author's `APPROVED`. A zero-cost restriction
exists: require the review's `author_association` ∈ {`OWNER`, `MEMBER`, `COLLABORATOR`} or
`user.login` == the overseer bot. However:
- I could not confirm the `author_association` that GitHub reports for App reviews, so the restriction
  might exclude the overseer's own approvals;
- the overseer login lives in `machine-accounts.env`, a config dependency that §2.1 avoids.

**Default in this draft: no restriction (today's behavior), recorded as a residual bounded by B.**
Rule whether to restrict now or defer to T3.2's trust work.

**OQ-5 (AC-6 "notice posted exactly once across two cycles").** The notice is model-posted (REQ-C26
says "the pattern … today"), so "exactly once" is a model-behavior property that no deterministic test
can pin. This draft pins:
- the deterministic half (T-HC-2CYC: a stable directive naming the PR every cycle);
- the prompt contract (T-1847d/e: marker check before post).

The alternative is a deterministic `bootstrap/` notice primitive with marker idempotency. It costs
comment reads per human-pending PR per cycle, a new write script and about three more files, and it
fits better with T3.7a's finalize step. **Rule: accept prompt-contract coverage for T3.0b, or require
the primitive** (which would make this TD a revision, not an edit).

**OQ-6 (notice coverage under `needs-attention` and `needs-fix`).** Accept that human-pending PRs get
their notice in the first cycle whose directive names them (§4.3), rather than adding them to the
`needs-attention` text, which would break AC-3 and AC-7 byte-identity.

---

## 9A. Architect rulings, round 1 (2026-10-02)

**Verdict: APPROVED_WITH_EDITS.** The edits are already applied in this document and recorded in
ADR-1644 Erratum 2. **`coder` handoff is gated on the human's answer to ARCH-ESC-1R.**

- **H-1: yes, the human must reconfirm before coding.**
  - The ruling on #1912 rests on ADR text, which I wrote, that called #1162 the only prerequisite. A
    prior human ratification (DECISIONS.md 2026-08-09) and an open `needs-human` issue (#1313) say
    otherwise.
  - Two open human decisions now conflict, and the product-boundary checkpoint has not been cleared for
    the facts the human was not shown.
  - ARCH-ESC-1R (Erratum 2) is the filed text: four bounded questions, each with a recommendation. The
    worker files it as a decision issue. ESC-2 to ESC-7 are unaffected.
  - The TD's own H-1 text overstated the exposure ("3 + 1") and understated #1313's controls. Both are
    corrected there.
- **OQ-1: confirmed.** This is now ADR Erratum 2 E7. T-NS5 uses two carriers (*H* = 2). T-NS5-shapes
  covers each of the three shapes alone, and T-BD1 covers *H* = 3.
- **OQ-2 (D-1): approved** as the one deliberate exception to "behavior preserved" (E8). TD-F8 is
  corrected: the empty-slug path is unreachable. The residual is accepted: a persistently failing list
  read means every cycle launches Claude with BLOCKED. That is visible through the
  `cycle-pr-state-unknown` audit event, and it costs the same per cycle as today's ALLOWED cycle.
- **OQ-3: each point ruled.**
  - **D-2 (`hos-halt`): approved. It is not routed to the human.** A halted PR that releases work is
    incoherent, and TD-F1 confines the case to a race window.
  - **D-3 (approval on head): approved.**
  - **D-4 (drafts never human-pending): approved.** It carries a forward constraint on T3.7 (E13).
  - **D-5: modified.** A full page is **not** unknown on the first page. The list is paginated to 3
    pages, and a full page 3 is DEGRADED (E10). As drafted, any consumer with 100 or more open PRs
    would have been permanently BLOCKED, which is a silent consumer-facing stall. The reviews keep
    single-page, full-page-unknown. That case blocks only while that one PR is open, and it is named
    in the PR's stderr reason.
  - **D-6: approved.** AC-5 governs AC-7 for read-failure fixtures (E12).
- **OQ-4: restrict now** (D-7, E9). The restriction is `author_association` ∈
  {`OWNER`,`MEMBER`,`COLLABORATOR`} plus a non-`[bot]` login. It costs nothing, needs no config, and
  fails toward blocking. Your concern that the overseer's approvals might be excluded is moot:
  excluding them only blocks (today's behavior), and under #1657 the overseer does not approve the PRs
  that wait on a human.
- **OQ-5: prompt-contract coverage is accepted for T3.0b.** The mechanism is today's, and "exactly once"
  is a model property today too. T3.7a must absorb the notice into its deterministic finalize step (E13).
  This TD does **not** add a notice primitive.
- **OQ-6: accepted.** The notice is visibility, not a gate. Deferring it while an overseer-pending or
  worker-actionable PR exists costs latency only. The human-pending PR already carries `needs-human`, or
  the human's own approval, which is visible to the human.
- **New: P1 is closed inside this slice** (E11, §4.1, T-1847f). **The revert path is pinned** (T-BD6).

**Still open, and for `technical-design` to confirm in its round-2 response (not blocking approval):**
1. Whether `test_hos_cron.py`'s env-var mode needs a `HOS_TEST_PR_REVIEW_ASSOC` knob, or whether a fixed
   `OWNER` suffices. The architect's reading is that a fixed `OWNER` suffices, because T-FC12 covers
   the variants in-process.
2. That §8's list of flipped existing tests is unchanged by E9 and E10. It should be, because env-var
   mode synthesizes trusted approvals and fewer than 100 PRs.

---

## Human Review Required

**RISK: HIGH.** This relaxes a deliberate safety serialization (#1198) on a protected surface
(`bin/hos-cron`, `scripts/framework/**`, the worker prompt and `worker.md`), and the relaxation changes
how many concurrent PRs the human faces. The relaxation itself is human-ruled (ARCH-ESC-1). This design
narrows it everywhere it had a choice:
- carriers count only on positive reads (D-2 to D-6);
- unknown state blocks (D-1);
- the bound is a literal with no knob.

The residual risks are:
- TD-F6/H-1 (prerequisites #1313 still lists as open);
- OQ-4 (third-party approvals can occupy a slot).

**CONFIDENCE: HIGH** on §0.2's characterization, which was read line by line from `0eabb868` and is
cross-checked by today's tests in `TestCycleContextBlock`. **HIGH** on AC-8, since per-PR requests go
from 1–3 to 1–2. **MEDIUM** on D-1 being accepted as within the slice. **MEDIUM** on OQ-5's coverage
being judged sufficient for #1847's "exactly once".

**BLAST RADIUS:**
- every worker cycle's new-work directive, on this repo and on every consumer (TD-F5);
- `worker-cron-prompt.md` Step 0.5/1;
- `worker.md` Step 1;
- `docs/LABELS.md`;
- `DECISIONS.md`.

The overseer path, the selector and `merge_authority.py` are untouched.

**Change classification: `additive`, within a human-ruled `structural` decision.**
- The structural change (relaxing #1198) is ARCH-ESC-1's, and the human has ruled it. This TD adds no
  new decision authority and no new state carrier. It chooses the stricter option at each precision
  point.
- **H-1 is escalated to the human** because the ruling's inputs omitted #1313. Until H-1 is answered,
  this design must not go to `coder`.
- **Status:** awaiting architect review, round 1 of 5. H-1 has been raised for human routing.
