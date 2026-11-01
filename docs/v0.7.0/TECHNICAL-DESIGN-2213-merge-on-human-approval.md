# TECHNICAL DESIGN — #2213 slice S1a: merge on a designated human's approval (code only, inert until S1b)

**Status:** APPROVED_WITH_EDITS by `architect`, iteration 1 (2026-10-31). The edits are listed in §12
and marked inline with "[AR-1 E<n>]". Coding may start. The architect approved it. Per the REQ and the ADR, the PR must not **merge** until the human answers ESC-1b, ESC-2,
ESC-3, ESC-4 and ARCH-ESC-5, or accepts their defaults (§9).
**Author:** `technical-design` (autonomous worker cycle; no human present)
**Date:** 2026-10-31
**Issue:** #2213 (milestone v0.7.0)
**Binding inputs:**
- `docs/v0.7.0/REQUIREMENTS-2213-merge-on-human-approval.md` (the REQ);
- `docs/v0.7.0/ADR-2213-merge-on-human-approval.md` (the ADR, AD-1 to AD-12), both at `9a68813fd`;
- TD-2174 D1, D5 and D6, for the marker, the latest-verdict rule and the designated set.

**Scope.** This is slice **S1a** only (ADR §4). It adds code that nothing calls yet. S1b does the wiring:
it adds the step-1 call and the step-0 branch to `overseer.md` and the cron prompt, deletes CRITICAL (3),
and updates contract §6a, `docs/LABELS.md` and `DECISIONS.md`. S1a edits **none** of these:
`.claude/agents/*.md`, `bootstrap/overseer-cron-prompt.md`, `contract/**`, `docs/LABELS.md`,
`DECISIONS.md`. So when S1a merges, no overseer behaviour changes. AUTO_MERGE stays exactly as
unreachable as it is today, and `decide_merge_authority()` is unchanged.

> This document specifies contracts, not code. A "must" is a requirement on the implementation. Where
> the ADR left a choice open, this document decides it and labels the decision **TD-D<n>** (§2).

---

## 0. Search-first findings and verified state

**Searched:** `scripts/automation/lib/*.py` (`github.py`, `merge_authority.py`, `merge_config.py`,
`probe.py`), `scripts/automation/*.py` (`merge_authority_cli.py`, `pr_review_cli.py`),
`scripts/framework/{require_overseer_approval,require_human_approval,requester_trust,select_work_candidates}.py`,
`scripts/oversight/lib/audit_log.py`, `bootstrap/{merge_authority,pr_review,post_review_thread,escalate_to_human}.sh`,
`bin/hos-cron`, and `bootstrap/lib/comment_format_check.sh`.

**Reused unchanged.** Each is called, never copied.

| Need | Reused symbol |
|---|---|
| Eligible approval (REQ-1) | `require_overseer_approval.designated_humans`, `eligible_human_approvals_on_head` |
| Overseer's latest verdict and marker | `require_overseer_approval.latest_overseer_verdict_on_head`, `valid_interim_signoff` |
| CODEOWNERS individual owners | `scripts.framework.requester_trust.codeowners_humans` (the one shared parser) |
| Bot test | `require_human_approval.is_bot_reviewer` (reached through `eligible_human_approvals_on_head`) |
| #902 hold | `merge_authority.detect_human_hold_directive`, `merge_authority._parse_iso` |
| Release (NG3b) | `merge_authority._is_release_related` |
| Authorship (R9.1.4) | `merge_authority._verify_authorship_separation` |
| Meta-gate set | `merge_authority._META_GATE_CHECKS` |
| Config (overseer, worker, human, bots, ceiling check name) | `merge_config.resolve_config`, `resolve_repo_slug` |
| GitHub reads/writes | `github.get_pull`, `get_repo`, `list_pull_files`, `list_pull_reviews`, `list_issue_comments`, `list_check_runs_for_ref`, `get_commit`, `post_comment`, `add_issue_label`, `remove_issue_label`, `_run_gh` |
| Audit | `scripts.oversight.lib.audit_log.write_event`, `read_stream` |
| CLI envelope, argparse error path, wrapper shape | `merge_authority_cli.py` / `bootstrap/merge_authority.sh` (read-only); `pr_review_cli.py` / `bootstrap/pr_review.sh` (mutating) |
| Secret scrubbing | `pr_review_cli._scrub_exc` (TD-D13) |

**Not reusable, so S1a builds a new one:**
- **Issue events.** `probe._fetch_events_paginated` stops silently at 10 pages and turns every
  error into `None`. For the "latest `labeled` event" question, a truncated list is the fail-open
  direction. AD-2 requires that hitting the page cap raises.
- **Review threads, ruleset detail, file contents, merge call.** No reader exists. The only
  `reviewThreads` use is a mutation in `post_review_thread.sh` (ADR AF-8).
- **Raw branch rules.** `get_ruleset_required_checks` returns only the contexts. AD-5 also needs
  the `pull_request` rule and each rule's `ruleset_id`.

**Live state, read 2026-10-31 with the worker App token. These reads were the source for the §7
fixture.**

| # | Fact |
|---|---|
| L1 | PR #2211: head `35a3b20382b1767b9789220bbe9b69a9735effd4`, author `hos-worker-hos[bot]`, base `main`, not draft. Title `[AI: hos-worker-hos[bot]] fix: pre-agent gh consumers check exit status; unknown PR routing (#2171 slice 3)`, which does not match `_RELEASE_TITLE_RE`. It was merged by `ScottThurlow` at 05:45:47Z. Merge commit `d5c03c880d5f146c9e772c9cec8a92feca03fe21`. |
| L2 | Reviews on the head: overseer `COMMENTED` `5702138899` at 10-29T17:27:54Z (non-empty, the verdict); overseer `COMMENTED` `5702142635` at 17:28:10Z (empty body, thread container); `ScottThurlow` `APPROVED` `5708492480` at 10-30T05:39:47Z (empty body); overseer `COMMENTED` `5708508520` at 05:42:18Z (the AF-5 churn verdict, *after* the approval); and seven empty worker `COMMENTED` containers between 17:04:20Z and 17:04:53Z. |
| L3 | Events: exactly one `labeled needs-human`, id `34614334737`, actor `hos-overseer-hos[bot]`, at 10-29T17:28:25Z. There is no `unlabeled` event. |
| L4 | Issue comments: one, `6515873383`, by `scottthurlow-claude[bot]` at 05:40:07Z. The head commit's committer date is 10-29T16:48:44Z. |
| L5 | All 28 check runs on the head are `completed/success`, and include `Agent static checks`. The meta gates are attached to the head, including the post-approval re-runs (`require-overseer-approval` `123912538529`, `require-human-approval` `123912536151`, `require-tier-ceiling` `123912531011`). |
| L6 | `rules/branches/main` returns `deletion`, `non_fast_forward`, `pull_request` and `required_status_checks`, all with `ruleset_id 18044233`. `pull_request` has `required_approving_review_count: 1`, `dismiss_stale_reviews_on_push: true`, `required_review_thread_resolution: true` and `allowed_merge_methods` ⊇ `squash`. The required contexts are `require-human-approval`, `require-tier-ceiling`, `require-overseer-approval`, `tests`, `oversight-gate-{repo-scoped,lint,type-check}` and `oversight-validator-{python,migration,shell,diff-size}`. |
| L7 | `rulesets/18044233`: `name main-protection`, `enforcement active`, `current_user_can_bypass "never"`, `bypass_actors null` (hidden from non-admins). |

**Verification needed in iteration 1.** L5 and L7 were read with the worker token. The coder does
not re-verify them, because the fixture fixes them. The S1b PR must still confirm one thing on a
live overseer run before it merges: that `current_user_can_bypass` reads `"never"` for the
**overseer** token. The check is the read-only twin's `gate_evaluated_as` field (§4.6).

---

## 1. Fail-closed defaults S1a is built on (all reversible)

The open escalations are encoded at their recommended, most restrictive defaults. Each one can be
loosened later by changing a single rule, with no change to the data model or the wiring:

| ESC | Encoded default | Rule | How to loosen it later |
|---|---|---|---|
| ESC-1b | The general gate stub is untouched. `_dep_ceiling_check_present()`, `detect_server_side_gate()`, the `gate` subcommand and AUTO_MERGE behaviour are unchanged. Only the stub's docstring gains a pointer to ESC-1b. | — | A separate issue swaps the stub's body for `verify_merge_gate_live` |
| ESC-2 | Only an overseer `APPROVED` verdict on the head, or a marker with `action=APPROVE`, qualifies | R7 | Widen R7's accepted action set |
| ESC-3 | Status quo: every review thread, including the overseer's own escalation thread, must be resolved by a human | R11 | Add a narrowly-identified exemption to R11 (ESC-3 A), or stop posting the thread (B, in S2) |
| ESC-4 | Release-related PRs are excluded | R4 | Delete R4 |
| ARCH-ESC-5 | Strict: any designated-human comment or `COMMENTED` review after the approval blocks | R10 | Relax R10, or delete it |

---

## 2. Decisions the ADR left open

- **TD-D1 (AD-4's loader move is replaced by a direct import).** `approval_merge.py` imports
  `scripts.framework.require_overseer_approval` and `scripts.framework.requester_trust` as modules
  of the `scripts.framework` namespace package. The precedent is `scripts/automation/lib/probe.py:39-41`,
  which already does this from the same directory. No file-path loader is needed, so no third copy
  of one exists. `pr_review_cli._load_require_overseer_approval` is left alone, because editing that
  file would add a twelfth S1a file and touches unrelated #2174 code. A follow-up (§10) can migrate
  it to the same import. AD-4's intent, "no third copy", is met.
- **TD-D2 (R2 also requires the base to be the default branch).** AF-9's CODEOWNERS pin and AD-5's
  ruleset read both name the default branch. If the PR targets another branch, those two reads
  would describe a branch the merge does not touch. That case gives `NOT_ELIGIBLE(base_not_default_branch)`.
- **TD-D3 (the mutating command takes no `--repo`).** The repo always comes from the clone's
  `origin` remote. This is stricter than AD-6's `[--repo]`. It removes the cross-repo write risk that
  `pr_review_cli._resolve_repo_or_fail` exists to guard (MUST_FIX 2, #1657), and with it the need to
  copy that guard. The read-only twin keeps `--repo`, like every other `merge_authority.sh`
  subcommand.
- **TD-D4 (a second, GitHub-side record that stops a retry).** The failure comment carries a
  machine marker (§4.5). R12 blocks when **either** a `merge-on-human-approval-failed` audit record
  **or** an overseer-authored comment with that marker exists for the head. Records under `audit/log/`
  in the overseer clone are local and uncommitted (#1803). Without this marker, a lost record or a
  failed audit write would let the merge retry every cycle.
- **TD-D5 (an ambiguous merge result is re-read, not recorded as a failure).** Examples are a
  timeout, a reset connection or a 5xx response. A retry is safe: the decision is recomputed from
  scratch and the SHA is pinned. So an unconfirmed, unmerged result gives exit 1 with no failure
  record, no comment and no label. Only a definite 4xx refusal takes the REQ-9 failure path.
- **TD-D6 (a 4xx is definite).** Any HTTP 400-499 from the merge call is a definite failure. That
  includes 403/429, which `_run_gh` raises as `RateLimitError` under `retries=0`, and a 401 after the
  re-mint. A permissions 403 then reaches the human as a failure comment, instead of a silent exit 1
  every cycle. **[AR-1 E1] Exception: a 401 is not definite.** `_run_gh` raises 401 only after its
  one re-mint has failed. That is a credential fault with this run, not a refusal of this PR. The
  comment and label writes would fail with the same credential, which would leave only a clone-local
  failure record. On a PR with no label to remove, that is a silent dead end. A 401 therefore takes
  the TD-D5 path: re-read, then `MERGE_UNCONFIRMED` and exit 1, with no failure record, no comment
  and no label. The next cycle's wrapper mints a fresh token. A retry is safe because GitHub rejected
  the request.
- **TD-D7 (gate function signature).** The signature is `verify_merge_gate_live(owner, repo, branch,
  *, tier_ceiling_check_name)`, not `(…, config)`. `merge_config` imports `merge_authority`, so a
  `MergeConfig` parameter would create an import cycle. The function returns `LiveGateResult`, a
  subclass of `GateDetectionResult`, so AD-5's return type still holds. It also carries the required
  contexts that R13 needs.
- **TD-D8 (what "the ruleset cannot be bypassed" means precisely).** Each AD-5 property must be
  supplied by at least one rule whose ruleset reads `enforcement == "active"` **and**
  `current_user_can_bypass == "never"`. The properties are: each meta context, the approving-review
  count, and stale-review dismissal. A ruleset that only adds unrelated rules is not consulted.
- **TD-D9 (R10 counts any `COMMENTED` review).** That includes an empty-bodied one on any commit.
  An inline reply inside an already-resolved thread creates exactly such a review, and R11 cannot
  see it.
- **TD-D10 (R9 reads the approval's own body).** "Approved, but hold off" blocks. The safe
  direction is accepted: `_HOLD_DIRECTIVE_RE` also matches words such as "revise", so a false
  positive delays a merge and never causes one.
- **TD-D11 (a read error is UNDETERMINABLE as a whole).** Any snapshot read error gives
  `UNDETERMINABLE(read:<what>)`, even if a later rule would have said NOT_ELIGIBLE. Both outcomes
  mean "normal review, no writes". There is one exception: a PR that is closed, merged or draft
  stops the fetch after `get_pull`, so AD-7's after-merge re-run makes exactly one read.
- **TD-D12 (`classify_bot_merge` takes the overseer login).** It gains an `overseer_login` parameter.
  The ADR's signature had no source for that value.
- **TD-D13 (scrubbing).** `overseer_merge_cli.py` imports `_scrub_exc` from
  `scripts.automation.pr_review_cli`, whose import performs no I/O by contract. A follow-up promotes
  it into `lib/` (§10). This avoids forking a function that #1657 hardened over four review rounds.
- **TD-D14 (CODEOWNERS source).** CODEOWNERS is read with the contents API at the default branch.
  A 404 means no file, and gives an empty owner set (TD-2174 D6: the set is then just
  `HUMAN_REVIEWER`). Any other read or decode error gives `UNDETERMINABLE(read:codeowners)`.
- **TD-D15 (when the stall clock starts).** It starts at the chosen approval's `submitted_at`, as in
  ADR R13.
- **TD-D16 (polling an unknown mergeability).** If `mergeable_state` is `null` or `"unknown"`, the
  snapshot re-reads the PR up to 3 more times, 2 s apart. The sleep is injectable for tests.
- **TD-D17 (rules reader).** `github.list_branch_rules` takes over the page loop.
  `get_ruleset_required_checks` is re-expressed over it, behaviour-identical. Its existing tests in
  `tests/automation/test_github.py` pin that, unchanged.
- **TD-D18 (which apps the wrapper mints for).** `overseer_merge.sh` mints a token only for
  `--app overseer`. It revokes only a token it minted itself, never an ambient `GH_TOKEN`.
  **[AR-1 E2]** On this irreversible path, a mint failure never falls back to an ambient token. If
  `HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1`, the CLI exits 1 before any network call, even when an
  ambient `HOS_BOT_LOGIN` equals the overseer login. An ambient token may be expired (it lasts 1 h),
  or it may not belong to that login. A successful mint is the only thing that binds `GH_TOKEN` to
  the `HOS_BOT_LOGIN` that R1 checks.
- **TD-D19 (the twin's gate is the caller's).** `current_user_can_bypass` describes the caller. The
  twin therefore reports whose answer it is (`gate_evaluated_as`). A human-proxy "would it merge?"
  query is accurate for every rule except R15's bypass clause. **[AR-1 E8]** The answer can also
  differ on R12's audit half. Audit records are clone-local (#1803), so a twin run in another clone
  cannot see the overseer clone's failure records. Only the comment marker is visible to every
  clone. The twin's answer is informational and is never an authorization.
- **TD-D20 (provenance of an unmerged PR).** `merge-provenance` on a PR that is not merged reports
  `classification: "not_merged"` and exits 0.

---

## 3. Files (S1a: 10 files; the PR carries 13 with the REQ, the ADR and this TD)

| # | File | New/Mod | Surface | Content |
|---|---|---|---|---|
| 1 | `scripts/automation/lib/approval_merge.py` | new | security (`scripts/automation/lib/**`) | §4.1-§4.3: data types, `fetch_snapshot`, `decide_merge_on_human_approval`, `_pre_merge_live_checks`, `classify_bot_merge` |
| 2 | `scripts/automation/lib/merge_authority.py` | mod | security | §4.4: `LiveGateResult`, `verify_merge_gate_live`, extraction of `_latest_check_runs_by_name`; the stub docstring only |
| 3 | `scripts/automation/lib/github.py` | mod | security | §4.7: `list_issue_events`, `list_review_threads`, `list_branch_rules`, `_required_contexts_from_rules`, `get_ruleset`, `get_file_text`, `merge_pull` |
| 4 | `scripts/automation/overseer_merge_cli.py` | new | — | §4.5: the L2 mutating CLI, mode `on-human-approval` |
| 5 | `bootstrap/overseer_merge.sh` | new | **PROTECTED** (`bootstrap/**`) | §4.5: the L3 wrapper |
| 6 | `scripts/automation/merge_authority_cli.py` | mod | — | §4.6: subcommands `approval-merge` and `merge-provenance` (read-only) |
| 7 | `bootstrap/merge_authority.sh` | mod | **PROTECTED** | §4.6: mint for the two new subcommands, and the header usage lines |
| 8 | `tests/automation/test_approval_merge.py` | new | — | §7.1-§7.3: decision rules, #2211 replay, `classify_bot_merge`, gate |
| 9 | `tests/automation/test_overseer_merge_cli.py` | new | — | §7.4-§7.6: CLIs, write order, idempotency, new `github.py` readers, wrapper |
| 10 | `SCRIPTS-INDEX.md` | regen | — | Run `scripts/framework/regen_all.sh`. `tests/framework/test_scripts_index.py` fails without it |

**Protected surfaces** (`scripts/framework/protected_surfaces.txt`): files 5 and 7 (`bootstrap/**`).
`require-human-approval` and CODEOWNERS approval therefore apply at merge. Files 1-3 are on the
**security** surface (`security_surfaces.txt`: `scripts/automation/lib/**`), so `security-reviewer` is
mandatory (ADR header). `.github/CODEOWNERS` needs no regeneration, because `protected_surfaces.txt`
is unchanged.

**Cut or merged relative to the ADR's ~13-file S1a:**
- **The shared loader move is dropped (TD-D1).** That removes `merge_config.py` and
  `pr_review_cli.py` from the slice.
- **All new GitHub readers go in the existing `github.py`.** No new reader module.
- **The decision, the snapshot fetch and `classify_bot_merge` share one new module,** so the two
  CLIs reuse one fetch path instead of each building their own.
- **Tests are consolidated into two new files.** The existing `test_github.py`,
  `test_merge_authority_cli.py`, `test_merge_authority_detection.py` and `test_required_checks_gate.py`
  ([AR-1 E9]) are **not edited**. They
  must pass unchanged: that is the behaviour-identity pin for TD-D17 and the
  `_latest_check_runs_by_name` extraction.

**Not touched in S1a:** `decide_merge_authority()` and its tests; `require_overseer_approval.py`;
`pr_review_cli.py`; `merge_config.py`; every file S1b owns.

---

## 4. Contracts

### 4.1 `approval_merge.py`: data types

Module docstring: names #2213, ADR-2213 AD-1/AD-3, and states that `decide_merge_on_human_approval`
and `classify_bot_merge` are pure while `fetch_snapshot` is the module's only I/O. Imports:
`from scripts.automation.lib import github, merge_authority, merge_config`;
`from scripts.framework import require_overseer_approval as roa`;
`from scripts.framework.requester_trust import codeowners_humans`. Every GitHub call goes through
the module attribute (`github.get_pull(...)`, `merge_authority.verify_merge_gate_live(...)`), so
tests patch `github.<fn>`, the same seam `test_merge_authority_cli.py` uses.

**Constants (module level, the single definition of each):**

| Name | Value |
|---|---|
| `NEEDS_HUMAN` | `"needs-human"` |
| `HOS_HALT` | `"hos-halt"` |
| `AGENT_STATIC_CHECK` | `"Agent static checks"` (the job `name:` in `agent-static-check.yml`, `overseer.md` step 2a) |
| `CHECK_STALL_SECONDS` | `7200` |
| `MERGEABLE_UNKNOWN_POLLS` | `3` |
| `MERGEABLE_POLL_SECONDS` | `2.0` |
| `EVENT_AUTHORIZED` | `"merge-on-human-approval-authorized"` |
| `EVENT_MERGED` | `"merged-on-human-approval"` |
| `EVENT_FAILED` | `"merge-on-human-approval-failed"` |
| `FAILURE_MARKER_RE` | `^<!-- hos:merge-on-human-approval-failed v=1 head=([0-9a-f]{40}) -->[ \t\r]*$`, with `re.MULTILINE`. [AR-1 E3] Trailing whitespace and CR are tolerated: this marker *blocks*, so a strict match fails open |
| `render_failure_marker(head)` | the one writer of that line. It raises `ValueError` unless `roa.SHA_RE` matches |

**`class ApprovalMergeOutcome(Enum)`:** `MERGE`, `DEFER`, `NOT_ELIGIBLE`, `UNDETERMINABLE`. The string
value of each member is its name.

**`@dataclass(frozen=True) class ApprovalMergeSnapshot`:** every input to the decision. A field is
`None` when it was not fetched, which is TD-D11's early stop.

| Field | Type | Source |
|---|---|---|
| `pr_number` | `int` | argv |
| `pull` | `dict` | final `get_pull` (after the TD-D16 polls) |
| `default_branch` | `str \| None` | `get_repo(...)["default_branch"]` |
| `changed_files` | `tuple[str, ...] \| None` | `list_pull_files` → `filename` |
| `reviews` | `tuple[dict, ...] \| None` | `list_pull_reviews` |
| `issue_comments` | `tuple[dict, ...] \| None` | `list_issue_comments` |
| `issue_events` | `tuple[dict, ...] \| None` | **new** `list_issue_events` |
| `review_threads` | `tuple[dict, ...] \| None` | **new** `list_review_threads` |
| `head_committed_at` | `str \| None` | `get_commit(head)["commit"]["committer"]["date"]` |
| `check_runs` | `tuple[dict, ...] \| None` | `list_check_runs_for_ref(head)` |
| `codeowners_owners` | `frozenset[str] \| None` | TD-D14 |
| `audit_events` | `tuple[dict, ...] \| None` | `audit_log.read_stream(repo_root)`, keeping records whose `event` is one of the three names and whose `pr == pr_number` |
| `gate` | `merge_authority.LiveGateResult \| None` | `verify_merge_gate_live`, read **last** |
| `now` | `datetime` (aware, UTC) | captured by the caller once, before the first read |

**`@dataclass(frozen=True) class ApprovalMergeDecision`:**

| Field | Type | Meaning |
|---|---|---|
| `outcome` | `ApprovalMergeOutcome` | |
| `rule` | `int` | the deciding rule's number, R2-R15 in §4.3 (`15` on MERGE, `0` for a snapshot read error) |
| `reason` | `str` | closed vocabulary (§4.3 table) |
| `detail` | `str` | free text for humans and logs; never parsed |
| `head_sha` | `str \| None` | |
| `approver` | `str \| None` | the R6 choice |
| `approving_review_id` | `int \| None` | |
| `approved_at` | `str \| None` | that review's `submitted_at` |
| `overseer_verdict_id` | `int \| None` | the R7 verdict |
| `verdict_kind` | `str \| None` | `"approved"` \| `"marker:HUMAN_REQUIRED"` \| `"marker:PROPOSE_ONLY"` |
| `label_provenance` | `dict \| None` | `{"labeled_event_id": int, "actor": str, "created_at": str}` or `{"absent": True}` |

It also has a `to_dict()` method that returns a JSON-safe mapping of every field, with `outcome` as
its name.

**`class SnapshotReadError(Exception)`:** attributes `what` (one of `pull`, `repo`, `files`, `reviews`,
`comments`, `events`, `threads`, `head_commit`, `check_runs`, `codeowners`, `audit`, `head_moved`) and
`message`, which is already scrubbed by the caller.

### 4.2 `fetch_snapshot` (the only I/O in the module)

```
fetch_snapshot(owner: str, repo: str, pr_number: int, config: merge_config.MergeConfig, *,
               repo_root: Path, now: datetime, sleep: Callable[[float], None] = time.sleep)
    -> ApprovalMergeSnapshot          # raises SnapshotReadError
```

The reads run in this order. A `GitHubError`, a `None` where an object is required, or a malformed
shape raises `SnapshotReadError(<what>)`. Nothing is swallowed.

1. `github.get_pull`. A `None` result raises `pull`.
2. If `pull["state"] != "open"`, or `pull.get("merged") is True`, or `pull.get("draft") is not False`,
   **return now**, with every other field `None` (TD-D11).
3. `github.get_repo` → `default_branch`. `None` or missing raises `repo`.
4. `list_pull_files`, `list_pull_reviews`, `list_issue_comments`, `list_issue_events`,
   `list_review_threads`. [AR-1 E6] If `len(files) != pull["changed_files"]` (an int, not a bool),
   raise `files`. GitHub's files endpoint stops silently at 3000 files, and an under-reported list
   lets R4's release check fail open.
5. `get_commit(head)` → committer date. A missing date raises `head_commit` (D-B: no library
   fail-safe on this path).
6. `list_check_runs_for_ref(head)`.
7. `github.get_file_text(owner, repo, ".github/CODEOWNERS", ref=default_branch)`.
   - `None` → `frozenset()`.
   - Otherwise, write the text to `<TemporaryDirectory>/.github/CODEOWNERS` (stdlib `tempfile`,
     so under `$TMPDIR`) and call `codeowners_humans(<tmpdir>)`. The directory is removed on exit.
   - The working-tree CODEOWNERS is never read (AF-9).
8. `audit_log.read_stream(str(repo_root))`, parsing each line with `json.loads`. A `RuntimeError`,
   `OSError` or `ValueError` raises `audit`.
9. **Mergeability polls (TD-D16).** While `pull["mergeable_state"]` is `None` or `"unknown"`, and
   fewer than `MERGEABLE_UNKNOWN_POLLS` re-reads have been made: call `sleep(MERGEABLE_POLL_SECONDS)`,
   then `get_pull`.
   - If `head.sha` changed, raise `head_moved`.
   - Otherwise, replace `pull` with the new read.
10. **Gate, last (REQ-8, AD-5):** `merge_authority.verify_merge_gate_live(owner, repo,
    pull["base"]["ref"], tier_ceiling_check_name=config.tier_ceiling_check_name)`. It never raises.

`fetch_snapshot` caches nothing and reads nothing from an earlier cycle.

### 4.3 `decide_merge_on_human_approval(snapshot, config) -> ApprovalMergeDecision` (pure)

The function performs no I/O. A test patches every `github.*` function to raise and the decision
still works. The rules are evaluated in order, and the **first rule that fails returns**. If a rule
needs a snapshot field that is `None`, it returns `UNDETERMINABLE("missing:<field>")`. Logins are
compared case-insensitively throughout. `head = pull["head"]["sha"]`, and it must match `roa.SHA_RE`;
otherwise the result is `UNDETERMINABLE("head_sha_invalid")`. Timestamps are parsed with
`merge_authority._parse_iso`, and `None` from it means the timestamp is unparseable.

`designated = roa.designated_humans({"HUMAN_REVIEWER": config.human_reviewer}, snapshot.codeowners_owners)`.
It is computed once, before R6.

R1, the identity check, is not in this function. It is the CLI's precondition (§4.5 step 3), because
the read-only twin evaluates the same rules for any caller.

| # | Rule: passes only if… | On failure (outcome, `reason`) | Data source |
|---|---|---|---|
| R2 | `state == "open"`, not merged, `draft is False`, **and** `base.ref == default_branch` (TD-D2) | NOT_ELIGIBLE `not_open_pr` / `draft` / `base_not_default_branch` | `pull`, `default_branch` |
| R3 | no label named `hos-halt`, whoever applied it | NOT_ELIGIBLE `hos_halt` | `pull.labels[].name` |
| R4 | `not merge_authority._is_release_related(pull.title, changed_files)` (ESC-4 A) | NOT_ELIGIBLE `release` | `pull.title`, `changed_files` |
| R5 | `pull.user.login` is non-empty (otherwise UNDETERMINABLE `pr_author_missing`) **and** `_verify_authorship_separation(author, config.overseer_handle, config.worker_handle)` | NOT_ELIGIBLE `self_authored` | `pull.user` |
| R6 | `designated` is non-empty (otherwise UNDETERMINABLE `no_designated_humans`) **and** `roa.eligible_human_approvals_on_head(list(reviews), set(config.bot_accounts), designated, head)` is non-empty. **Approver choice:** for each eligible login, take its latest `APPROVED` review on `head`, ordered by `(submitted_at, id)`. Choose the login whose review sorts latest. Record its `id` and `submitted_at`. An unparseable `submitted_at` gives UNDETERMINABLE `timestamp:approval` | NOT_ELIGIBLE `no_eligible_approval` | `reviews`, `codeowners_owners`, config |
| R7 | `v = roa.latest_overseer_verdict_on_head(list(reviews), config.overseer_handle, head)` is not `None` **and** either `v.state` (upper) `== "APPROVED"` (kind `approved`, AF-4), or `m = roa.valid_interim_signoff(v, head)` is not `None` with `m[1] == "APPROVE"` (kind `marker:<m[0]>`) (ESC-2 A) | NOT_ELIGIBLE `no_approve_signoff` | `reviews` |
| R8 | If a label named `needs-human` is present: take the latest event with `event == "labeled"` and `label.name` (lower) `== "needs-human"`, ordered by `(_parse_iso(created_at), id)`. [AR-1 E4] If any such event has an unparseable `created_at`, the result is UNDETERMINABLE `timestamp:label_event`. A raw string sort would put a missing `created_at` first, so an older overseer event could win. Its `actor.login` must equal `config.overseer_handle`. If no such event exists, the result is UNDETERMINABLE `label_event_missing`. If the label is absent, R8 passes, with provenance `{"absent": True}` (AD-11) | NOT_ELIGIBLE `foreign_needs_human` | `pull.labels`, `issue_events` |
| R9 | No hold directive (#902). Build `items` = every issue comment, plus every review on `head` by a designated login mapped to `{"user": r["user"], "body": r["body"], "created_at": r["submitted_at"]}`. That includes the approval itself (TD-D10). For **each** login in `designated`, `merge_authority.detect_human_hold_directive(items, login, cutoff)` must return `None`. [AR-1 E5, corrected in §12.4] If `head_committed_at` is earlier than the R6 `approved_at`, `cutoff` is `head_committed_at`, rendered as ISO-8601 UTC. Otherwise (`head_committed_at >= approved_at`) `cutoff` is `None`, so every matching hold counts. The committer date is set by the PR author. A forward-dated commit would otherwise make every hold "superseded". An honest head cannot be committed at or after its own approval, because the approved commit existed when it was approved, so such a date supersedes nothing. If `head_committed_at` is `None` or unparseable, the result is UNDETERMINABLE `missing:head_committed_at` | NOT_ELIGIBLE `hold_directive` | `issue_comments`, `reviews`, `head_committed_at` |
| R10 | `t0` = the parsed R6 `approved_at`. No issue comment by a designated login has `created_at > t0`, and no review in state `COMMENTED`, on any commit and with any body, by a designated login has `submitted_at > t0` (TD-D9; ARCH-ESC-5 strict). An unparseable timestamp on one of those items gives UNDETERMINABLE `timestamp:human_activity`. A `COMMENTED` review with no `submitted_at` (pending) is ignored | NOT_ELIGIBLE `human_comment_after_approval` | `issue_comments`, `reviews` |
| R11 | Every thread has `isResolved is True` (REQ-6; ESC-3 C, so the overseer's own thread counts too) | NOT_ELIGIBLE `unresolved_thread` (detail: the count) | `review_threads` |
| R12 | No **failure evidence** for `head` (TD-D4). Evidence is either (a) an audit event with `event == EVENT_FAILED`, `pr == pr_number` and `head_sha == head`, timestamped by its `timestamp`; or (b) an issue comment whose `user.login == config.overseer_handle`, whose `user.type == "Bot"`, and whose body has **at least one** `FAILURE_MARKER_RE` match naming `head` ([AR-1 E3]: this is blocking evidence, so "exactly one" would fail open), timestamped by its `created_at`. **Reset:** the evidence is cleared if an `unlabeled` event for `needs-human` exists whose `actor.login` is in `designated`, whose `actor.type != "Bot"`, and whose `created_at` is later than the latest evidence timestamp. Unparseable timestamps, on the evidence or on a candidate `unlabeled` event, give UNDETERMINABLE `timestamp:failure_evidence` [AR-1 E4] | NOT_ELIGIBLE `merge_failed_on_head` | `audit_events`, `issue_comments`, `issue_events` |
| R13 | Delegated to `_pre_merge_live_checks` (below) | see below | `gate.required_contexts`, `check_runs`, `now` |
| R14 | `pull.mergeable_state == "clean"` | `None` or `"unknown"` gives DEFER `mergeable_unknown`. A value in `{dirty, behind, blocked, unstable, has_hooks, draft}` gives NOT_ELIGIBLE `mergeable_<value>`. Anything else gives NOT_ELIGIBLE `mergeable_other` | `pull` |
| R15 | `gate.autonomous_capable is True` | NOT_ELIGIBLE `gate_failed` (detail: `gate.reason`) | `gate` |
| — | All pass | **MERGE** `approved_by_designated_human`, with `approver`, `approving_review_id`, `approved_at`, `overseer_verdict_id`, `verdict_kind`, `label_provenance` and `head_sha` set | |

**`_pre_merge_live_checks(snapshot, ctx) -> ApprovalMergeDecision | None` (AD-12 seam).** This is a
pure, module-private function. `decide` calls it for R13, R14 and R15, in that order, and it returns
the first failing decision or `None`. R9 and R11 stay inline, because they also need the R6/R7
context. When #2209's `merge-guard` lands, this function's body is the thing that changes. The
function owns R13:
- `required = set(gate.required_contexts) | {AGENT_STATIC_CHECK}`. If `gate.required_contexts` is
  empty, the result is UNDETERMINABLE `required_contexts_unavailable`. A passing gate always carries
  at least the three meta contexts, so this blocks only a vacuous pass.
- `latest = merge_authority._latest_check_runs_by_name(check_runs)`, the extracted helper (§4.4).
- For each name in `required`:
  - **absent**, or `status != "completed"` → *pending*;
  - `conclusion != "success"` → *failed*. That includes `neutral`, `skipped` and `None`.
- Any *failed* name → NOT_ELIGIBLE `check_not_success` (detail: the names). Failure takes
  precedence over pending.
- Otherwise, any *pending* name:
  - if `(now - t0).total_seconds() > CHECK_STALL_SECONDS` → NOT_ELIGIBLE `checks_stalled`;
  - else DEFER `checks_pending`.

**Not inputs, deliberately (AD-3):** tier, ceiling, protected/security/CODEOWNERS path matching, the
evaluator verdict label, `requested_reviewers`, `prior_overseer_decision`. GitHub's
`require_code_owner_review` is still enforced, through R14 and through GitHub itself at the merge
call.

**Closed reason vocabulary:**
- **R2-R15** use the codes in the table above. The `mergeable_<value>` codes take only the listed
  values.
- **MERGE** uses `approved_by_designated_human`.
- **UNDETERMINABLE** uses:
  - `read:<what>`;
  - `missing:<field>`;
  - `head_sha_invalid`, `pr_author_missing`, `no_designated_humans`, `label_event_missing`,
    `required_contexts_unavailable`;
  - `timestamp:{approval,human_activity,failure_evidence,label_event}` ([AR-1 E4] adds
    `label_event`).

Tests assert exact codes.

### 4.3a `classify_bot_merge` (pure, AD-9)

```
class BotMergeClass(Enum): AUTHORIZED_ON_HUMAN_APPROVAL, UNAUTHORIZED
@dataclass(frozen=True) class BotMergeProvenance:
    classification: BotMergeClass
    authorized_record: dict | None
    completion_record_present: bool
classify_bot_merge(pr_number: int, merged_head_sha: str, merged_by: str,
                   audit_events: Sequence[dict], overseer_login: str) -> BotMergeProvenance
```

The result is `AUTHORIZED_ON_HUMAN_APPROVAL` **only** if both of these hold:
- `merged_by` equals `overseer_login` (case-insensitive; not "any bot");
- an `EVENT_AUTHORIZED` record exists with `pr == pr_number` and `head_sha == merged_head_sha`.

Otherwise the result is `UNAUTHORIZED`. `completion_record_present` reports whether an `EVENT_MERGED`
record for the same `(pr, head)` exists. That field is informational, never a condition, because
the write-ahead record is the key (AD-9).

### 4.4 `merge_authority.py` additions

- **Imports:** add `_required_contexts_from_rules`, `get_ruleset` and `list_branch_rules` to the existing `from
  scripts.automation.lib.github import (...)` list. Tests patch `merge_authority.<name>`, the same
  seam the module's existing gate tests use.
- **`_latest_check_runs_by_name(runs: Sequence[dict]) -> dict[str, dict]`** is extracted verbatim
  from the loop and the `_run_id` closure in `check_required_content_checks` (`:1114-1130`):
  - non-dict runs and runs without a name are skipped;
  - the highest integer `id` wins (a `bool` is not an `int`);
  - a run with a missing or non-integer id loses.

  `check_required_content_checks` calls it. Its behaviour is unchanged, and its existing tests pin
  that.
- **`_required_contexts_from_rules(rules: Sequence[dict]) -> list[str]`** is a pure function. It
  holds the extraction loop from `get_ruleset_required_checks`: de-duplicated, first-seen order,
  malformed elements ignored. It lives in `github.py` (§4.7), next to its other caller, and
  `merge_authority` imports it from there.
- **`@dataclass class LiveGateResult(GateDetectionResult)`** has the fields
  `required_contexts: tuple[str, ...] = ()`, `ruleset_ids: tuple[int, ...] = ()` and
  `evidence: dict = field(default_factory=dict)`.
- **`verify_merge_gate_live(owner, repo, branch, *, tier_ceiling_check_name: str) -> LiveGateResult`**
  never raises. Each failure returns `autonomous_capable=False` with a named reason:
  1. `rules = list_branch_rules(owner, repo, branch)`. A `GitHubError` gives `"rules read failed: <exc>"`.
  2. `contexts = _required_contexts_from_rules(rules)`. Then
     `meta = (_META_GATE_CHECKS - {"require-tier-ceiling"}) | {tier_ceiling_check_name}`. Any member
     of `meta` missing from `contexts` gives `"required context missing: <name>"`.
  3. Find the qualifying `pull_request` rules: `type == "pull_request"`,
     `parameters.required_approving_review_count` an `int` (not a `bool`) `>= 1`, and
     `parameters.dismiss_stale_reviews_on_push is True`. If there is none, the result is
     `"no pull_request rule with >=1 approval and stale-review dismissal"`.
  4. **Bypass (TD-D8).** For each distinct `ruleset_id` that appears on a rule supplying a `meta`
     context or on a qualifying `pull_request` rule:
     - call `get_ruleset(owner, repo, id)` once, memoised within this call;
     - the ruleset *qualifies* iff the result is a dict with `enforcement == "active"` and
       `current_user_can_bypass == "never"`;
     - a missing or non-`int` `ruleset_id`, a `None` result or a `GitHubError` means that rule does
       not qualify, and the error goes into `evidence`.

     Each `meta` context needs at least one supplying rule whose ruleset qualifies, and so does the
     `pull_request` property. Otherwise the result is
     `"ruleset bypassable or unverifiable for: <property>"`.
  5. On a pass: `autonomous_capable=True`, `reason="ruleset gate verified (#2213 AD-5)"`,
     `required_contexts=tuple(contexts)`, `ruleset_ids=tuple(sorted(qualifying ids))`, and
     `evidence` holding the per-id `{enforcement, current_user_can_bypass}`.

  Classic protection is never consulted (AF-1).
- **Stub docstring only:** `_dep_ceiling_check_present` gains one sentence: *"Unchanged by #2213: the
  human-approval merge path uses `verify_merge_gate_live`; switching this stub to it is ESC-1b and
  needs its own issue."* Its body, `_PROPOSE_ONLY_DEP` and `detect_server_side_gate` are
  byte-identical.

### 4.5 Mutating surface: `overseer_merge_cli.py` (L2) and `bootstrap/overseer_merge.sh` (L3)

**argv:** `overseer_merge_cli.py on-human-approval --app {worker,overseer,human} --pr <N>`. There is
no `--repo` (TD-D3), and no `--force`, `--skip-*`, `--head-sha`, `--dry-run` or `--repo-root`
(ADR-1357 AD-2). Help is disabled, and argparse errors use the envelope-emitting parser.
`main(argv=None, *, repo_root=None, sleep=time.sleep) -> int` takes test-only keyword injections
that argv cannot reach. The module performs no I/O at import, and its `sys.path` bootstrap is
copied from `merge_authority_cli.py:35-38`.

**Envelope:** these keys: `schema_version` (1), `subcommand`, `computed_at`, `repo`, `repo_root`,
`pr`, `config_source`, `app_role`, `not_verified`, `error`. They are the same keys as
`merge_authority_cli._envelope`, and the payload is merged in. stdout is exactly one JSON line,
always.

**Payload keys:**
- `outcome`, one of `MERGED`, `MERGE_FAILED`, `MERGE_UNCONFIRMED`, `DEFER`, `NOT_ELIGIBLE`,
  `UNDETERMINABLE`, or `null` on a refusal or an operational error;
- `decision` (`ApprovalMergeDecision.to_dict()`, or `null`);
- `merge_commit_sha`;
- `audit_records`: `{authorized, merged, failed}`, each a relative path or `null`;
- `authorized_record_reused` (bool);
- `label_removed` (bool), `label_added` (bool);
- `failure_comment_url`, `http_status`;
- `recovered` (bool: the result came from the TD-D5 re-read);
- `refused` (bool) and `refusal_reason`.

**Steps:**
1. Parse argv. A usage error gives exit 2.
2. `merge_config.resolve_config(repo_root)`. A `ConfigError` gives exit 1.
3. **R1 identity (REQ-11), before any network call:**
   - if `--app` is not `overseer`: exit 3, `refusal_reason: "overseer_identity_required"`;
   - if `HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1`: exit 1, error naming the mint failure, whatever
     `HOS_BOT_LOGIN` holds ([AR-1 E2]);
   - if `HOS_BOT_LOGIN` is empty: exit 1, error naming the missing identity;
   - if `HOS_BOT_LOGIN` (case-insensitive) `!= config.overseer_handle`: exit 3,
     `"overseer_identity_mismatch"`.
4. `merge_config.resolve_repo_slug(repo_root)`. A `ConfigError` gives exit 1.
5. `now = datetime.now(timezone.utc)`. Then `snapshot = fetch_snapshot(..., sleep=sleep)`.
   A `SnapshotReadError` gives the decision `UNDETERMINABLE("read:<what>", rule 0)`, outcome
   `UNDETERMINABLE`, **exit 0, and no writes**.
6. `decision = decide_merge_on_human_approval(snapshot, config)`. AD-6 step 1: the decision is
   recomputed in this invocation, and the twin's answer is never trusted. If the decision is not
   MERGE: emit it, **exit 0, and no writes** (AD-7: DEFER posts nothing).
7. **Write-ahead.**
   - If `snapshot.audit_events` already holds an `EVENT_AUTHORIZED` record for `(pr, head)` **with
     the same `approving_review_id` and `overseer_verdict_id` as this decision**, reuse its path and
     set `authorized_record_reused: true` (AD-7 crash recovery). [AR-1 E7] If those ids differ
     (after a crash, another designated human approved, or the overseer re-verdicted), write a new
     record. A reused record must name the authorization that is actually being acted on. The new
     record has different content, so it gets its own path and causes no collision.
   - Otherwise, `audit_log.write_event(<authorized record>, root=str(repo_root))`. If that raises:
     exit 1, `outcome: null`, error `"write-ahead audit failed: …"`. **No merge call.**
8. `github.merge_pull(owner, repo, pr, head)`.
9. **Success:** the response has `merged is True`.
   - `merge_commit_sha = response["sha"]`.
   - If `needs-human` was in the snapshot labels, call `github.remove_issue_label(...)`. This is
     best effort: on failure, `label_removed: false` and a `not_verified` entry.
   - Write the `EVENT_MERGED` record, best effort: on failure, `audit_records.merged: null` and a
     `not_verified` entry.
   - `outcome: MERGED`, exit 0.
10. **Definite failure (TD-D6):** a `GitHubError` with `400 <= status_code <= 499` **other than
    401** ([AR-1 E1]: a 401 goes to step 11), or a 2xx
    response without `merged is True`, recorded as `http_status` 200. In order, each best effort,
    with failures recorded in `not_verified`:
    1. write the `EVENT_FAILED` record;
    2. `github.post_comment` with the failure body (below);
    3. if `needs-human` is absent, `github.add_issue_label(..., "needs-human")`.

    Then `outcome: MERGE_FAILED`, **exit 1**.
11. **Ambiguous or credential (TD-D5, [AR-1 E1]):** any other `GitHubError` (status `None`, 401, or
    ≥ 500). Re-read with `get_pull`.
    - If it shows `merged is True`, `head.sha == head` and a non-empty `merge_commit_sha`: run
      step 9 with `recovered: true`.
    - Otherwise: `outcome: MERGE_UNCONFIRMED`, exit 1. No failure record, no comment, no label.
    - A failed re-read is treated the same as "not merged".

**Exit codes (AD-6):**
- 0: decided (`MERGED`, `DEFER`, `NOT_ELIGIBLE`, `UNDETERMINABLE`);
- 1: operational (config, identity unresolvable, write-ahead failure, `MERGE_FAILED`,
  `MERGE_UNCONFIRMED`, an unhandled exception);
- 2: usage;
- 3: identity refusal.

`main` catches every other exception, emits the envelope with
`error: "unhandled <Type>: <scrubbed>"`, and returns 1. Every exception text that reaches the
envelope or an audit record passes through `_scrub_exc` (TD-D13). The GitHub `message` field is cut
to 300 characters.

**Audit records.** Each is written with `audit_log.write_event(event, root=str(repo_root))`, with the
module imported inside the helper. `timestamp` is the CLI's own `_now_iso()`. `actor` is
`HOS_BOT_LOGIN`. `cycle_id` is `HOS_CYCLE_ID` if it matches `^[A-Za-z0-9._-]+$`, else `null`.

| `event` | When | Fields (all also carry `event`, `repo`, `pr`, `head_sha`, `actor`, `cycle_id`, `timestamp`) |
|---|---|---|
| `merge-on-human-approval-authorized` | step 7, before the merge call | `approver`, `approving_review_id`, `approved_at`, `overseer_verdict_id`, `verdict_kind`, `label_provenance`, `gate` (`{reason, ruleset_ids, required_contexts}`) |
| `merged-on-human-approval` | step 9 | `merge_commit_sha`, `approver`, `approving_review_id`, `verdict_kind`, `label_removed`, `recovered`, `authorized_record` (its relative path) |
| `merge-on-human-approval-failed` | step 10 | `http_status`, `message` (scrubbed, ≤300 chars), `approver`, `approving_review_id` |

**Failure comment body.** The text is exact. `{sha12}`, `{status}` and `{message}` are filled in, and
`{message}` is scrubbed and cut to 300 characters. It follows the #1270 format (heading, one bolded
enum value, a not-verified clause) and #2170 (no script names):

```
**Executive summary:** The overseer tried to merge this PR on your approval of commit `{sha12}`, and GitHub refused the merge (HTTP {status}: {message}). Nothing was merged. Expected action: **OTHER**: merge the PR yourself on GitHub once the cause is fixed, or push a new commit. The overseer will not try to merge this commit again unless you remove the `needs-human` label. Not verified this run: nothing was skipped this run.

<!-- hos:merge-on-human-approval-failed v=1 head={full_sha} -->
```

**L3 wrapper `bootstrap/overseer_merge.sh`.**
- **Header usage:** `bash bootstrap/overseer_merge.sh on-human-approval --app overseer --pr <N>`.
  The header also states the exit codes above, "stdout is exactly one JSON object", "never
  suppress stderr (#1523)", and that this is the **only** HOS script that can merge a PR on human
  approval (ADR-1357 AD-1).
- **Structure.** It follows `pr_review.sh` in its `set -euo pipefail`, the ARCH-3a "extract, do not
  validate" pass over the subcommand and `--app` (both forms), the mint through
  `get_app_token.sh` into `mktemp`, the revocation through `revoke_app_token.sh` with the
  idempotency guard and the INT/TERM re-raise, and the verbatim
  `python3 "$REPO_ROOT/scripts/automation/overseer_merge_cli.py" "$@"` with the child's exit code
  passed through.
- **Deviations from `pr_review.sh` (TD-D18):**
  - it mints **only** when the subcommand is `on-human-approval` **and** `--app` is `overseer`;
  - on a mint failure it exports `HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1` and proceeds;
  - `revoke_token` revokes only when this script minted (`_MINTED=1`), never an inherited
    `GH_TOKEN`.
- **Prohibited:** no format check, no JSON literal, no `echo`/`printf` to stdout, and no
  re-derivation of any field. It must pass `shellcheck` (the `oversight-gate-bash-check` CI job).

### 4.6 Read-only twin: `merge_authority_cli.py` and `bootstrap/merge_authority.sh`

- **Two new subparsers**, each with the `common` parent (`--app`, `--repo`) and `--pr` (`_pr_type`).
  They are added to `SUBCOMMANDS`, `NETWORK_SUBCOMMANDS` and `_HANDLERS`. Neither may write, post,
  label or merge: the tests patch every write function to raise. Neither ever exits 3.
- **`approval-merge`:**
  - It resolves the repo as the existing handlers do, then calls
    `approval_merge.fetch_snapshot(..., repo_root=ctx.repo_root, now=<now>)` and `decide`.
  - A `SnapshotReadError` gives the UNDETERMINABLE decision with exit 0, as in §4.5 step 5.
  - **Payload:** the `decision` mapping (`ApprovalMergeDecision.to_dict()`), `would_merge`
    (`outcome == "MERGE"`), `gate_evaluated_as` (`HOS_BOT_LOGIN` or `null`, TD-D19), and [AR-1 E8]
    `gate`: `{autonomous_capable, reason, ruleset_ids, evidence}` from the snapshot's
    `LiveGateResult`, or `null` on an early stop. This is the observable that S1b's
    overseer-token confirmation reads (§0; §10 item 6).
  - **Exit codes:** 0 for every decision; 1 only for config or repo errors.
- **`merge-provenance`:**
  - It reads `github.get_pull`. A `None` result or a `GitHubError` gives exit 1. It then reads
    audit events through `audit_log.read_stream`, filtered as in §4.2 step 8; an audit read error
    gives exit 1.
  - If the PR is not merged: `classification: "not_merged"` (TD-D20).
  - Otherwise it calls `classify_bot_merge(pr, pull.head.sha, pull.merged_by.login, events,
    config.overseer_handle)`.
  - **Payload:** `classification` (`authorized_on_human_approval` | `unauthorized` | `not_merged`),
    `merged_by`, `head_sha`, `merge_commit_sha`, `authorized_record_present`,
    `completion_record_present`.
- **`merge_authority.sh`:** add `approval-merge|merge-provenance` to the `MINT_TOKEN` case list, and
  add two usage lines to the header. The "read-only … can merge nothing" header sentence stays true,
  and the exit-3 line stays as it is. The script body is otherwise unchanged.

### 4.7 `github.py` additions

Each docstring cites #2213. Every new list reader has a page cap and **raises `GitHubError` when the
cap is hit, or when the response has the wrong type** (AD-2 completeness).

| Function | Contract |
|---|---|
| `list_issue_events(owner, repo, issue_number) -> list[dict]` | `GET /repos/{o}/{r}/issues/{n}/events?per_page=100&page=k` for k = 1 to 10. A page shorter than 100 ends the read. A non-list response raises. A `None` (404) on page 1 raises `GitHubError(..., 404)`. Ten full pages raise. |
| `list_review_threads(owner, repo, pr_number) -> list[dict]` | GraphQL through `_run_gh(["graphql", "-f", f"query={Q}", "-f", f"owner={owner}", "-f", f"name={repo}", "-F", f"number={pr_number}"] + (["-f", f"cursor={c}"] if c else []))`. `Q` selects `repository.pullRequest.reviewThreads(first:100, after:$cursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated comments(first:1){nodes{author{login}}}}}`. It returns the node dicts, at most 10 pages. It raises on a non-empty `errors` key, on a `null` `pullRequest`, on a missing `pageInfo`, and when `hasNextPage` is still true after 10 pages. |
| `list_branch_rules(owner, repo, branch) -> list[dict]` | The page loop moved out of `get_ruleset_required_checks`: the same endpoint, the same `_RULES_MAX_PAGES`, the same non-list raise, and the same cap raise. It returns every rule object. |
| `_required_contexts_from_rules(rules) -> list[str]` | The extraction moved out of `get_ruleset_required_checks`. `get_ruleset_required_checks` becomes `return _required_contexts_from_rules(list_branch_rules(owner, repo, branch))`, behaviour-identical (TD-D17). |
| `get_ruleset(owner, repo, ruleset_id: int) -> dict \| None` | `GET /repos/{o}/{r}/rulesets/{id}`. A non-dict response raises. |
| `get_file_text(owner, repo, path, ref) -> str \| None` | `GET /repos/{o}/{r}/contents/{path}?ref={quote(ref, safe='')}`. A 404 returns `None`. It raises if the response is not a dict with `type == "file"` and `encoding == "base64"`, or if the base64/UTF-8 decode fails. |
| `merge_pull(owner, repo, pr_number, sha) -> dict` | It raises `ValueError` unless `sha` matches `^[0-9a-f]{40}$`. Then `_run_gh([f"/repos/{o}/{r}/pulls/{n}/merge", "--method", "PUT"], retries=0, stdin_json={"merge_method": "squash", "sha": sha})`. `None` raises `GitHubError(..., 404)`. The merge method is fixed and is **not a parameter**, so nothing can widen it. `retries=0` follows the same MUST_FIX D reasoning as `submit_pull_review`. |

---

## 5. Idempotency (AD-7, REQ-12)

| Re-run situation | Behaviour |
|---|---|
| After a merge | `get_pull` shows closed/merged → `NOT_ELIGIBLE(not_open_pr)` after **one** read, no writes |
| Unchanged head, still unapproved | `NOT_ELIGIBLE(no_eligible_approval)`, no writes |
| DEFER (checks pending, mergeable unknown) | No writes, no label change, nothing posted |
| Crash between the write-ahead record and the merge | The existing `-authorized` record is reused; no second record is written |
| Crash after the merge, before the completion record | The PR is closed → `not_open_pr`. Provenance keys on the write-ahead record, so it is authorized |
| After a definite failure on this head | R12 → `NOT_ELIGIBLE(merge_failed_on_head)`, even if the audit write failed (the comment marker) |
| After a failure, a designated human removes `needs-human` | R12 resets. R8 passes because the label is absent. One fresh attempt |
| After a new push | Every head-bound input moves: R6 and R7 fail on the new head (REQ-7) |

The REQ-12 bullet "a re-run after a removal whose merge was deferred" cannot happen in this design.
The label is removed only after a confirmed merge (AD-6).

---

## 6. Failure modes specific to S1a (beyond ADR §3)

| Fault | Outcome |
|---|---|
| `audit/log/` in the overseer clone is lost (it is uncommitted, #1803) | R12 still holds through the comment marker (TD-D4). AD-9 provenance would then misfile a legitimate merge as a process gap. That is the noise direction, and it is disclosed for S1b |
| An unrelated audit record is unparseable | `read:audit` → UNDETERMINABLE on every approval merge until it is fixed. Fail-closed and visible |
| The overseer token cannot read `rulesets/{id}` | R15 `gate_failed`. Nothing merges, and the twin's `gate_evaluated_as` names the identity |
| A required context is posted as a commit status, not a check run | Never seen by `list_check_runs_for_ref`. It DEFERs, then becomes `checks_stalled` after 2 h. Fail-closed. None of this repo's contexts are statuses (L5) |
| Squash is not allowed by the ruleset | The merge call fails with a 4xx, which takes the failure path. The human merges |
| `machine-accounts.env` is read from the clone's working tree | Same as every `merge_authority_cli` subcommand. The overseer clone runs on the default branch. Residual risk, disclosed (§10) |

---

## 7. Test plan

All tests are deterministic and make **no network calls**:
- **GitHub reads:** `github.*` is patched with `monkeypatch.setattr`, through the same seam as
  `test_merge_authority_cli.py:84-103`. `merge_authority.list_branch_rules` and `get_ruleset` are
  patched for the gate tests.
- **Audit writes:** they go to `tmp_path`.
- **The CODEOWNERS temp directory:** it comes from `tempfile`.
- **Wrapper runs:** they scrub `GH_TOKEN` and `GITHUB_TOKEN` from the child environment, so no
  ambient token can be revoked.

Tests follow `tests/conftest.py` temp hygiene.

### 7.1 The #2211 replay fixture (REQ-14), defined inline in `test_approval_merge.py`

`_snapshot_2211(**overrides)` builds an `ApprovalMergeSnapshot` from L1-L7, using the real ids and
timestamps, with bodies trimmed:
- **PR:** the open state of #2211 (`state "open"`, `merged false`, `draft false`, `base.ref "main"`,
  `mergeable_state "clean"`, labels `["needs-human"]`, L1 head and title, author
  `hos-worker-hos[bot]`), with `default_branch "main"`.
- **Reviews (L2) up to 05:39:47Z.** The 05:42:18Z review `5708508520` is **excluded**: under S1b
  wiring the approval path runs first, so that verdict is never posted.
  - Review `5702138899` gets the post-#2174 shape: its body ends with
    `render_interim_marker("HUMAN_REQUIRED", "APPROVE", <head>)`, it has `user.type "Bot"`, and it
    is `COMMENTED`.
- **Events (L3):** event `34614334737`.
- **Comments (L4):** comment `6515873383`, by the human-proxy, which is not designated.
- **Threads:** eight threads, all `isResolved: true` (VF-8).
- **Head committed at:** L4.
- **Check runs:** the 28 from L5.
- **CODEOWNERS owners:** `{"scottthurlow"}`.
- **Audit events:** `()`.
- **Gate:** a passing `LiveGateResult` with the L6 contexts and `ruleset_ids (18044233,)`.
- **Now:** `2026-10-30T05:44:00Z`.
- **Config:** a `MergeConfig` with this repo's values: overseer `hos-overseer-hos[bot]`, worker
  `hos-worker-hos[bot]`, human `ScottThurlow`, and the four-login `BOT_ACCOUNTS`.

| Test | Expectation |
|---|---|
| REPLAY-1 | `MERGE`, `approver "ScottThurlow"`, `approving_review_id 5708492480`, `head_sha` L1, `verdict_kind "marker:HUMAN_REQUIRED"`, `label_provenance.labeled_event_id 34614334737` |
| REPLAY-2 (human-added label) | The events' latest `labeled` actor is `ScottThurlow` → `NOT_ELIGIBLE foreign_needs_human` |
| REPLAY-2b (human-proxy-added) | The actor is `scottthurlow-claude[bot]` → `foreign_needs_human` |
| REPLAY-2c | The overseer labels, a human unlabels, then the human labels again → `foreign_needs_human` |
| REPLAY-3 (`hos-halt`) | Labels plus `hos-halt` → `NOT_ELIGIBLE hos_halt` |
| REPLAY-4 (stale-head approval) | The PR head becomes B (a new SHA); reviews unchanged → `NOT_ELIGIBLE no_eligible_approval` (REQ-7) |
| REPLAY-5 (AF-5 pin) | Add a 05:42:18Z overseer review with marker `action=OTHER` → `NOT_ELIGIBLE no_approve_signoff`. This documents why S1b keeps the expected action at `APPROVE` |
| REPLAY-6 | As REPLAY-5, but with `action=APPROVE` → `MERGE` |
| REPLAY-7 (protected, unmarked approve, AF-4) | The overseer verdict is `APPROVED` with no marker → `MERGE`, `verdict_kind "approved"` |
| REPLAY-8 (PROPOSE_ONLY, REQ-4b) | Marker `PROPOSE_ONLY/APPROVE`, no label, no events → `MERGE`, `label_provenance {"absent": true}` |

### 7.2 One negative per rule (each starts from REPLAY-1 and changes only that rule's input)

- **R2:** state `closed` → `not_open_pr`; `merged true` → `not_open_pr`; `draft true` → `draft`;
  `base.ref "release"` → `base_not_default_branch`.
- **R3:** see REPLAY-3.
- **R4:** title `"Release v0.7.0"` → `release`; changed file `docs/releases/x.md` → `release`.
- **R5:** author equals the overseer login → `self_authored`; empty author →
  `UNDETERMINABLE pr_author_missing`.
- **R6 (the REQ-1 table):**
  - designated `HUMAN_REVIEWER` on the head → passes;
  - an individual CODEOWNERS owner (`"alice"` in owners) on the head → passes, approver `"alice"`;
  - the approval on an older commit → `no_eligible_approval`;
  - a bot approval (`hos-worker-hos[bot]`), and a human-proxy approval → `no_eligible_approval`;
  - a non-designated collaborator → `no_eligible_approval`;
  - the approval followed by the same login's `CHANGES_REQUESTED` on the head →
    `no_eligible_approval`;
  - the approval followed by `DISMISSED` → `no_eligible_approval`;
  - an empty designated set (`human_reviewer ""` and no owners) →
    `UNDETERMINABLE no_designated_humans`;
  - two designated approvers → the one with the later review is chosen.
- **R7:**
  - no overseer verdict on the head → `no_approve_signoff`;
  - the latest overseer verdict is an unmarked non-empty `COMMENTED` → `no_approve_signoff`;
  - marker `action=DO_NOT_MERGE` → `no_approve_signoff`;
  - the overseer's later `DISMISSED` review → `no_approve_signoff`;
  - an empty-bodied overseer container after the marked verdict → still passes (F12).
- **R8:** see REPLAY-2, 2b, 2c. In addition: the label is present but there is no `labeled` event →
  `UNDETERMINABLE label_event_missing`.
- **R9:**
  - a designated issue comment "please hold off" after the head commit → `hold_directive`;
  - the same text before the head commit → passes;
  - the approval's own body "approved but do not merge yet" → `hold_directive`;
  - the hold text from a non-designated login → passes;
  - `head_committed_at None` → `UNDETERMINABLE missing:head_committed_at`.
- **R10:**
  - a designated issue comment "thanks" after the approval → `human_comment_after_approval`;
  - a designated empty-body `COMMENTED` review after the approval (an inline reply) →
    `human_comment_after_approval`;
  - the human-proxy comment at 05:40:07Z → passes (this is the replay itself);
  - an unparseable designated comment timestamp → `UNDETERMINABLE timestamp:human_activity`.
- **R11:** one thread `isResolved: false` → `unresolved_thread`; the overseer-authored unresolved
  thread → `unresolved_thread` (ESC-3 C).
- **R12:**
  - an `EVENT_FAILED` record for the head → `merge_failed_on_head`;
  - the same record for another head → passes;
  - an overseer `Bot` comment with the failure marker for the head → `merge_failed_on_head`;
  - the same marker in a human's comment → passes (not overseer-authored);
  - a later `unlabeled needs-human` by `ScottThurlow` → passes (reset);
  - the same `unlabeled` by the overseer → still `merge_failed_on_head`;
  - an unlabel *before* the failure → still blocked.
- **R13:**
  - `tests` `in_progress` and `now` 10 min after the approval → `DEFER checks_pending`;
  - the same with `now` 2 h 1 min after → `NOT_ELIGIBLE checks_stalled`;
  - `tests` `failure` → `check_not_success`;
  - `Agent static checks` absent → `DEFER checks_pending`;
  - a `neutral` conclusion → `check_not_success`;
  - an older `failure` run plus a newer, higher-id `success` with the same name → passes;
  - one failed and one pending → `check_not_success`;
  - `gate.required_contexts ()` → `UNDETERMINABLE required_contexts_unavailable`.
- **R14:** each of `dirty`, `behind`, `blocked`, `unstable` → `mergeable_<v>`; `"weird"` →
  `mergeable_other`; `"unknown"` and `None` → `DEFER mergeable_unknown`.
- **R15:** a gate with `autonomous_capable False` → `NOT_ELIGIBLE gate_failed`, with `detail` equal to
  the gate's reason.
- **[AR-1] additions:**
  - **R8:** a `needs-human` `labeled` event with `created_at "garbage"` →
    `UNDETERMINABLE timestamp:label_event` (E4).
  - **R9:** `head_committed_at` set to 2030-01-01 and a designated "please hold off" comment between
    the real push and the approval → `hold_directive` (E5: the head is not earlier than the approval,
    so no cutoff applies).
  - **R12:** an overseer `Bot` comment whose marker line ends in `\r` → `merge_failed_on_head`.
    Two marker lines for the head → `merge_failed_on_head` (E3).
  - **R12:** a designated `unlabeled` event with an unparseable `created_at` →
    `UNDETERMINABLE timestamp:failure_evidence` (E4).
- **Missing field:** `reviews None` with the PR open → `UNDETERMINABLE missing:reviews`.
- **Purity:** every `github.*` function and `merge_authority.verify_merge_gate_live` is patched to
  raise; `decide(REPLAY-1)` still returns `MERGE`.
- **First rule wins:** `hos-halt` together with an unresolved thread → `hos_halt`.

### 7.3 Gate and provenance (`test_approval_merge.py`)

- **GATE-1:** the L6/L7-shaped rules and ruleset pass. `required_contexts` equals the L6 list, and
  `ruleset_ids` is `(18044233,)`.
- **GATE-2:** each failure gives the named reason:
  - `require-overseer-approval` dropped from the contexts;
  - `tier_ceiling_check_name="custom-ceiling"` with only `require-tier-ceiling` present →
    `custom-ceiling` missing;
  - no `pull_request` rule;
  - count `0`;
  - count `True` (a bool);
  - `dismiss_stale_reviews_on_push false`;
  - `current_user_can_bypass` `"always"`, `"pull_requests_only"`, or missing;
  - `enforcement "evaluate"`;
  - `list_branch_rules` raises;
  - `get_ruleset` returns `None` or raises;
  - `ruleset_id` missing.
- **GATE-3:** two rulesets. The meta contexts come from a qualifying one, and an extra bypassable
  one adds only `lint` → passes (TD-D8). The only supplier of `require-human-approval` is bypassable
  → fails.
- **GATE-4:** `get_branch_protection` is patched to raise, and `verify_merge_gate_live` never
  calls it.
- **GATE-5:** `detect_server_side_gate` still returns `_PROPOSE_ONLY_DEP` (ESC-1b pin), and its
  reason string is unchanged.
- **PROV-1:** the replay's `-authorized` record, `merged_by` the overseer and the same head →
  `AUTHORIZED_ON_HUMAN_APPROVAL`, `completion_record_present` False, then True once an
  `EVENT_MERGED` record is added.
- **PROV-2:** a synthetic bot merge (`merged_by hos-worker-hos[bot]`, or the overseer with no
  record) → `UNAUTHORIZED`.
- **PROV-3:** a record for another head → `UNAUTHORIZED`; a human `merged_by` with a record →
  `UNAUTHORIZED`.

### 7.4 Mutating CLI (`test_overseer_merge_cli.py`)

Each test calls `overseer_merge_cli.main(argv, repo_root=<tmp repo with machine-accounts.env>,
sleep=lambda s: None)`. `merge_config.resolve_repo_slug` is patched to return `"o/r"`. The GitHub
layer returns the REPLAY-1 data. Every call to `merge_pull`, `post_comment`, `add_issue_label`,
`remove_issue_label` and `audit_log.write_event` is recorded in one ordered list.

| Test | Expectation |
|---|---|
| CLI-ID-1 | `--app worker` → exit 3 `overseer_identity_required`, and **zero** GitHub calls (REQ-11) |
| CLI-ID-2 | `--app human` → exit 3 |
| CLI-ID-3 | `--app overseer` with `HOS_BOT_LOGIN=hos-worker-hos[bot]` → exit 3 `overseer_identity_mismatch` |
| CLI-ID-4 | `--app overseer` with `HOS_BOT_LOGIN` unset → exit 1. With `HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1`, the error names the mint |
| CLI-ARGV-1 | `--repo o/r`, `--force`, `--head-sha x`, `--skip-gate`, a missing `--pr`, a non-numeric `--pr`, an unknown mode → exit 2, each with one envelope line |
| CLI-MERGE-1 | Replay → exit 0, `outcome MERGED`. The ordered calls are `write_event(authorized)`, `merge_pull("o","r",2211,<head>)`, `remove_issue_label(...,"needs-human")`, `write_event(merged)`. The `authorized` record's fields match §4.5. `merge_commit_sha` comes from the response |
| CLI-MERGE-2 | The `merge_pull` stub asserts that the PUT body is `{"merge_method":"squash","sha":<head>}` (it is exercised through a `_run_gh` fake in GH-MERGE-1) |
| CLI-409 | `merge_pull` raises `GitHubError(status_code=409)` → exit 1, `MERGE_FAILED`. The calls are `write_event(authorized)`, `merge_pull`, `write_event(failed)`, one `post_comment` (its body contains the exact marker and `**OTHER**`, and no `.sh`/`.py` string), then `add_issue_label("needs-human")` **not** called, because the label is already present. **Second run:** the recorded failure event and the posted comment are fed back into the mocks → `NOT_ELIGIBLE merge_failed_on_head`, with **no** `merge_pull` (REQ-9) |
| CLI-409b | The same failure with no label → `add_issue_label` called once |
| CLI-409c | The `-failed` audit write raises → the comment is still posted, `not_verified` names the failure, and the re-run is still blocked by the marker |
| CLI-WA-1 | `write_event(authorized)` raises → exit 1, and **no** `merge_pull` |
| CLI-WA-2 | The snapshot already holds an `-authorized` record for `(2211, head)` → no new authorized write, `authorized_record_reused true`, and the merge proceeds |
| CLI-POST-1 | `write_event(merged)` raises after a successful merge → exit 0, `MERGED`, `audit_records.merged null`, and a `not_verified` entry |
| CLI-POST-2 | `remove_issue_label` raises → exit 0, `label_removed false`, and a `not_verified` entry |
| CLI-AMB-1 | `merge_pull` raises `GitHubError(status_code=None)`; the re-read shows merged → exit 0, `MERGED`, `recovered true` |
| CLI-AMB-2 | The same, but the re-read shows not merged → exit 1, `MERGE_UNCONFIRMED`, and no `failed` write, no comment, no label |
| CLI-NOWRITE | DEFER (pending check), NOT_ELIGIBLE (no approval), and UNDETERMINABLE (`list_issue_events` raises) → exit 0 and an **empty** write list |
| CLI-IDEM-1 | The PR is closed → `NOT_ELIGIBLE not_open_pr`. `get_pull` is the **only** GitHub call. No writes |
| CLI-IDEM-2 | Unchanged head, unapproved, run twice → both runs make no writes |
| CLI-POLL | `mergeable_state` reads `unknown, unknown, clean` → MERGE after two polls. A head change during the polls → `UNDETERMINABLE read:head_moved` |
| CLI-SCRUB | A `GitHubError` message containing `ghs_` followed by 36 characters is redacted in both the envelope and the `-failed` record |
| CLI-401 [AR-1 E1] | `merge_pull` raises `GitHubError(status_code=401)`, and the re-read shows not merged → exit 1, `MERGE_UNCONFIRMED`, and no `failed` write, no comment, no label. The re-run is **not** blocked by R12 |
| CLI-403 | `merge_pull` raises `RateLimitError(status_code=403)` → the definite path (as CLI-409) |
| CLI-ID-5 [AR-1 E2] | `HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED=1` **and** `HOS_BOT_LOGIN` equal to the overseer → exit 1 that names the mint, and **zero** GitHub calls |
| CLI-WA-3 [AR-1 E7] | The snapshot holds an `-authorized` record for `(2211, head)` with a **different** `approving_review_id` → a new authorized record is written, `authorized_record_reused false`, then the merge |
| CLI-FILES [AR-1 E6] | `pull.changed_files` 5 while `list_pull_files` returns 4 → `UNDETERMINABLE read:files`, and no writes |

### 7.5 Read-only twin and the new GitHub readers (`test_overseer_merge_cli.py`)

- **TWIN-1:** `merge_authority_cli.main(["approval-merge","--app","human","--pr","2211","--repo","o/r"])`
  on the replay → exit 0, `would_merge true`, and the `decision` equals REPLAY-1's. All five write
  functions are patched to raise and are never called. The envelope keys equal
  `test_merge_authority_cli._ENVELOPE_KEYS`.
- **TWIN-2:** both new subcommands never exit 3 on any outcome. A `SnapshotReadError` → exit 0
  UNDETERMINABLE.
- **TWIN-3:** `merge-provenance`: authorized, unauthorized, and not merged (`not_merged`).
- **GH-EVENTS-1:** ten full pages → raises; a non-list → raises; a short page 2 → returns pages 1-2.
- **GH-THREADS-1:** two pages via the cursor (assert `-f cursor=<endCursor>` on the second call);
  `errors` present → raises; `pullRequest null` → raises; still `hasNextPage` after 10 pages →
  raises.
- **GH-MERGE-1:** a `_run_gh` fake asserts `--method PUT`, `retries=0`, and
  `stdin_json == {"merge_method":"squash","sha":<sha>}`. A bad SHA → `ValueError` with no call.
  `None` → `GitHubError`.
- **GH-FILE-1:** base64 content decodes; 404 → `None`; `type "dir"` → raises; invalid base64 →
  raises.
- **GH-RULESET-1:** `get_ruleset` returns the dict; a non-dict → raises.
- **GH-RULES-1:** `list_branch_rules` with ten full pages → raises. `get_ruleset_required_checks`
  over the same fake returns exactly the context list. The existing `test_github.py` cases are
  unchanged and must still pass.

### 7.6 Wrapper (`test_overseer_merge_cli.py`)

- **WRAP-1 (static):**
  - `bash -n` passes;
  - the script contains `overseer_merge_cli.py" "$@"`, `revoke_app_token.sh` and `trap`;
  - it contains no `echo`/`printf` to stdout outside the stderr warnings, and no `{"` JSON
    literal;
  - the mint `case` names only `on-human-approval` and `overseer`.
- **WRAP-2 (exec, no network):** run `bash bootstrap/overseer_merge.sh on-human-approval --app worker
  --pr 1` with `GH_TOKEN`/`GITHUB_TOKEN` removed from the environment → exit 3, exactly one JSON line
  on stdout, and `get_app_token.sh` never invoked. Assert this by pointing `PATH`/`HOME` so that a
  mint would fail loudly, or by asserting the absence of the mint warning on stderr.

### 7.7 Unchanged suites that must stay green

`tests/automation/test_github.py`, `test_merge_authority_cli.py`, `test_merge_authority_detection.py`,
`test_required_checks_gate.py` ([AR-1 E9]: it pins `check_required_content_checks`, the source of
the `_latest_check_runs_by_name` extraction, and it must pass **unedited**), every
`decide_merge_authority` test, `tests/framework/test_require_overseer_approval.py`,
`test_scripts_index.py`, `test_regen_all.py`. Run them with
`scripts/framework/run_tests_inner_loop.sh`.

---

## 8. Risk tier and how this PR merges

- **Self-assessed tier: HIGH.** The PR adds a code path that can merge PRs, plus the overseer's
  first GitHub merge primitive. It touches `bootstrap/**` (protected) and
  `scripts/automation/lib/**` (security). The `risk-assessor` decides the final tier.
- **Required review:** `security-reviewer` is mandatory. The cross-vendor second review applies.
- **Inert on merge.** Nothing calls `bootstrap/overseer_merge.sh` until S1b's prose lands. S1b also
  has to check that the overseer's permission allowlist matches the new literal command. If it does
  not, the overseer's unattended cycle denies the command silently (CLAUDE.md "Shell usage under the
  sandbox").
- **Self-application.** The human merges this PR under the old flow (REQ §5).
- **Change classification of this TD: additive.** It adds new, uncalled code. No existing contract or
  behaviour changes: `decide_merge_authority`, the gate stub, `require_overseer_approval.py` and
  every agent text are untouched. The structural decision this code serves is ADR-2213's, and it is
  already human-gated by the ADR's escalations (§9). This TD adds no new structural choice. Each
  TD-D decision either narrows a surface or fails closed.

---

## 9. Escalations (carried from the ADR; nothing new is escalated)

S1a builds on the defaults in §1. Before the PR merges, the human answers each of these or accepts
its default:
- **ESC-1b:** keep the stub, and file a separate issue.
- **ESC-2:** A.
- **ESC-3:** S1 ships C; B is recommended for S2.
- **ESC-4:** A.
- **ARCH-ESC-5:** strict.

The TD-D decisions in §2 are technical, and the architect accepts or rejects them in design review.
None of them is a product question.

---

## 10. Follow-ups (recommended; nothing is filed by this design)

1. Migrate `pr_review_cli._load_require_overseer_approval` to the direct namespace import (TD-D1).
2. Promote `_scrub_secrets` / `_scrub_exc` into `scripts/automation/lib/`, used by both CLIs (TD-D13).
3. For S1b: contract §6a gains the three events. Step 0 calls `merge-provenance` and warns, but does
   not file, on a missing completion record. LABELS.md gets the AD-11 meaning. A text pin covers
   the AD-11 "no overseer `unlabeled` is a resume" behaviour, in `worker.md`'s R5 check. The
   overseer allowlist must include the new command.
4. Pin `machine-accounts.env` to the default branch for this path too (AF-9 residual, §6).
5. #2209: `merge-guard` takes over `_pre_merge_live_checks`, and `latest_reviewer_act` reuses
   `eligible_human_approvals_on_head` (ADR AD-12).
6. **[AR-1 E10] S1b merge preconditions (binding on S1b, not optional):**
   - **Overseer-token gate.** Before S1b merges, its PR records one run of `approval-merge` under
     `--app overseer` on an open PR. That run must show `gate_evaluated_as` equal to the overseer
     login, `gate.autonomous_capable true`, and `current_user_can_bypass "never"` for every id in
     `gate.evidence`. If it shows anything else, S1b does not merge. That is the safe direction:
     R15 already fails closed.
   - **Keep the R12 reset path live.** After `NOT_ELIGIBLE(merge_failed_on_head)`, the normal
     review's expected action must stay `APPROVE`, under the same AF-5 rule as AD-8. If it switches
     to `OTHER`, R7 blocks forever after the human removes the label, and the failure comment's
     promise ("remove the label") is false.
   - **Human-proxy holds.** R9 reads designated humans only. `docs/LABELS.md` (S1b) tells the
     human-proxy to relay a human's hold with `hos-halt` or `needs-human`, never with a comment
     alone. R8 and R3 catch those. Extending R9 to the proxy login would need
     `BOT_HUMAN_USERNAME` in `MergeConfig`; that is a follow-up, not S1a.

---

## 11. Startup-gap check and affected sign-offs

- **Should this have been settled in the initial design?** Yes. That is already recorded in ADR §6
  (#1357 ESC-1 ruled 09-11; slices 2-6 never landed). This TD adds no new gap. The worker should
  annotate #2213 or open a `startup-artifact-gap` issue referencing #1357, as the ADR requests.
  This session may not file it.
- **Affected sign-offs:** none are invalidated by S1a.
  - `get_ruleset_required_checks` and `check_required_content_checks` are refactored with
    behaviour-identical extractions (TD-D17, §4.4), and their existing tests pin that. Their prior
    sign-offs stand on condition that those tests pass unmodified. If any of those tests needs an
    edit, that is a contract change and needs re-review.
  - The TD-2174 code (marker, G6, gate) is consumed unchanged, and its sign-offs stand.

---

## 12. Architect review (iteration 1, 2026-10-31): APPROVED_WITH_EDITS

The architect read this TD against ADR-2213 and REQ-2213 and checked its code claims against the tree
at `16b98c6e4`: `github._run_gh`'s status split and re-mint, `require_overseer_approval`'s predicates
and imports, `requester_trust.codeowners_humans`, `detect_human_hold_directive`,
`check_required_content_checks`, `get_ruleset_required_checks`, `audit_log.read_stream`/`write_event`,
`MergeConfig`, `pr_review.sh`'s mint path, and `protected_surfaces.txt`/`security_surfaces.txt`.

### 12.1 Rulings on §2

| Decision | Ruling | Why |
|---|---|---|
| TD-D1 (direct import instead of moving the loader) | **Accept.** It supersedes AD-4's "move the loader" | `probe.py:39-41` already imports `scripts.framework.requester_trust` as a namespace subpackage. `require_overseer_approval` has no import-time I/O, and it loads its own sibling (`require_human_approval.py`) by path. AD-4's real intent, "no third copy", is met |
| TD-D2 (base must be the default branch) | **Accept** | Both the CODEOWNERS pin and the ruleset read describe the default branch. A different base would make both reads irrelevant to the merge |
| TD-D3 (no `--repo` on the mutating command) | **Accept.** It supersedes AD-6's `[--repo]` | It removes a cross-repo write surface rather than guarding it |
| TD-D4 (failure marker comment for R12) | **Accept, with E3** | Audit records are clone-local (#1803), so a GitHub-side record is required for R12 to hold across a lost clone. E3: blocking evidence must be matched permissively ("at least one", CR-tolerant), the opposite of the strict matching used for authorizing markers |
| TD-D5 (ambiguous result: re-read, no failure record) | **Accept** | The SHA is pinned and the decision is recomputed, so a retry cannot merge an unapproved head. A persistent 5xx costs one exit 1 per cycle; that is liveness, not safety |
| TD-D6 (4xx is definite) | **Changed (E1): 401 is not definite** | `_run_gh` raises 401 only after its one re-mint has failed. The follow-up comment and label writes then fail with the same credential, which would leave a clone-local failure record and, on a PR without a label, nothing the human can act on. 403/429 stay definite: `_run_gh` cannot tell a rate-limit 403 from a permission 403, a persistent permission 403 must reach the human, and `post_comment` keeps its default retries with backoff |
| TD-D7 (gate signature without `config`) | **Accept** | Verified: `merge_config.py:24` imports `merge_authority`. A subclass return type keeps AD-5's contract |
| TD-D8 (per-property qualifying ruleset) | **Accept** | It is stricter than AD-5's wording. A bypassable ruleset that only adds unrelated rules can neither satisfy nor spoil the gate |
| TD-D9, TD-D10 (R10 counts any `COMMENTED`; R9 reads the approval's own body) | **Accept** | Both widen blocking. False positives delay a merge and never cause one |
| TD-D11 (a read error is UNDETERMINABLE as a whole; early stop on closed/draft) | **Accept** | It matches AD-2 and gives AD-7's one-read idempotency |
| TD-D12, TD-D13, TD-D20 | **Accept** | Necessary signature fix; reuse of `_scrub_exc` instead of a fork (verified at `pr_review_cli.py:144`, with no import-time I/O); a well-defined `not_merged` result |
| TD-D14 (CODEOWNERS via the contents API; 404 means an empty owner set) | **Accept.** This refines AD-4's "unreadable → UNDETERMINABLE" | A missing file *narrows* the designated set to `HUMAN_REVIEWER`, which is the safe direction. Any other read error still fails closed |
| TD-D15 (stall clock starts at the approval) | **Accept, as a deliberate divergence from step 2a** | Step 2a times from the run's `started_at` or the committer date. The committer date is author-controlled, and run-based clocks reset on re-runs, so either could extend DEFER indefinitely. DEFER skips the normal review entirely, so its bound must use a server timestamp that cannot move: the approval. The cost of firing early is one redundant normal review |
| TD-D16 (3 polls, 2 s apart, head-move check) | **Accept** | |
| TD-D17 (rules reader extraction) | **Accept** | Behaviour-identical, and pinned by unedited tests (E9 adds `test_required_checks_gate.py` to the pin) |
| TD-D18 (mint only for overseer; revoke only own token) | **Accept, tightened (E2)** | The irreversible path never falls back to an ambient token |
| TD-D19 (the twin's gate is the caller's) | **Accept, extended (E8)** | The twin payload carries the gate evidence, and R12's clone-locality is disclosed |

### 12.2 The specific checks requested

- **Fail-closed on every read.**
  - Every new reader raises on a cap, a wrong type or a GraphQL `errors` key.
  - The existing unbounded list helpers (`list_pull_reviews`, `list_issue_comments`,
    `list_pull_files`, `list_check_runs_for_ref`) have no page cap. AD-2 allows that.
  - One gap was found: GitHub's own 3000-file cap on `/pulls/{n}/files` truncates silently, and an
    under-reported file list fails R4 open. E6 closes it with a `changed_files` count check.
  - Check-run truncation hides only older runs, which reads as "absent", and absent means DEFER. That
    is fail-closed.
  - An absent `audit/log/` yields nothing. The comment marker covers R12 in that case.
- **Write order.**
  - The order is confirmed: write-ahead audit, then the pinned-SHA PUT, then the label removal and
    the completion record, best effort.
  - Every failure leaves either nothing changed or the label in place.
  - AD-9 keys on the write-ahead record, so a failed completion write cannot create a false process
    gap.
  - E7 keeps a reused write-ahead record truthful about which approval it records.
- **R12.** It is sound with E3 and E4, and the reset requires a non-Bot designated `unlabeled` event
  after the evidence.
  - Residual risk: if the failure path's label add also failed, there is no label to remove, so the
    human resets by pushing or by merging manually. The comment says "merge the PR yourself", so the
    human is not stranded.
  - Clock skew between the clone's audit `timestamp` and GitHub's `created_at` can only delay a
    reset, never cause a merge.
- **4xx versus timeout/5xx.** This split is the subject of E1 (see TD-D6 above).
- **R6 (approver choice).**
  - Correct, and it reuses `eligible_human_approvals_on_head`, which returns logins only. The TD
    re-derives the review id correctly.
  - With several designated approvers, choosing the latest makes R10's window start at the final
    approval. Comments before it were visible to that approver. Today the designated set is one
    person.
- **R8 (labeled-event actor).** Correct, and covers relabel sequences (REPLAY-2c). E4 removes a
  string-sort fail-open. The no-op re-add residual is disclosed in the ADR.
- **R9.** E5 closes a forward-dated-committer-date bypass of #902 on this path. (The general #902
  path has the same exposure. That path is outside this slice, but it is worth a separate issue.)
- **R15 and the overseer token.**
  - Whatever the bypass value is for the overseer, the outcome is safe: anything other than `"never"`,
    or a 403, gives `gate_failed` and nothing merges.
  - The open question is liveness only. E8 and §10 item 6 make the overseer-token confirmation a
    recorded precondition for S1b's merge.
  - S1a is inert, so this does not gate S1a.
- **Slice size and surfaces.**
  - 10 code files, plus the 3 already-committed design docs. No `.claude/agents/*.md`, no
    `overseer-cron-prompt.md`, no `contract/**`, no `DECISIONS.md`.
  - Protected surfaces touched: `bootstrap/overseer_merge.sh`, `bootstrap/merge_authority.sh`.
  - Security surfaces touched: `scripts/automation/lib/{approval_merge,merge_authority,github}.py`.
- **`decide_merge_authority()` is unchanged.**
  - It does not call `check_required_content_checks` or `get_ruleset_required_checks`. Its only gate
    call is `detect_server_side_gate`, which stays byte-identical, and GATE-5 pins that.
  - The two extractions sit in functions outside the matrix, and unedited suites pin both.
  - If any pinned test needs an edit, the approval is void for that function, and it goes back to
    re-review (§11).

### 12.3 Edits made

E1 (401 goes to the TD-D5 path), E2 (a mint failure is a hard exit 1), E3 (the failure marker is
matched permissively), E4 (timestamp handling for R8 and the R12 reset), E5 (R9 cutoff guarded
against a forward-dated head; the rule as built is in §12.4), E6 (file-list completeness), E7 (reuse requires the same authorization), E8 (twin gate
evidence; clone-local disclosure), E9 (`test_required_checks_gate.py` pinned), E10 (S1b merge
preconditions in §10 item 6). The tests for each are added in §7.2 and §7.4.

No MUST_FIX items remain for `technical-design`. Nothing here changes an ESC default or adds a
product-visible behaviour, so no new escalation is needed. The ADR's ESC-1b, ESC-2, ESC-3, ESC-4 and
ARCH-ESC-5 still gate the **merge** of the S1a PR, as stated in §9.

**Startup-gap check for this review:** no new gap. The edits refine S1a-internal contracts. Nothing
has been built against them yet, so no sign-off is orphaned.

### 12.4 Post-implementation correction (code review round 1)

The E5 rule as first written, `cutoff = min(head_committed_at, approved_at)`, contradicted its own
test. `detect_human_hold_directive` ignores any hold with `created_at <= cutoff`. With a
forward-dated head the formula gives `cutoff = approved_at`, which ignores a hold posted between the
real push and the approval. It would also ignore the approval's own body (TD-D10), whose timestamp
equals `approved_at`. The §7.4 E5 test expects `hold_directive` in that case.

The implementation (`approval_merge.py`, R9) uses the rule now stated in §4.3 R9. If
`head_committed_at < approved_at`, the cutoff is `head_committed_at`. Otherwise there is no cutoff.
A head dated at or after its own approval cannot be honest, so it supersedes no hold. Code review
ruled this correct and strictly safer: its cutoff is never later than the original formula's, so it
counts every hold the original counted and more. Classification: `clarifying` (the TD now matches the
intended and tested behaviour). No sign-off is affected: the code and the test already implement this
rule.

### 12.5 Second-review round 1 fix: pre-PUT re-read + post-merge base check; residual ms window disclosed

The merge PUT pins only the head SHA, so R2 (default-branch only) and the R15 gate, evaluated on the
earlier snapshot, could be outrun by a base retarget or a newly applied `hos-halt` / `needs-human`
(CWE-367). Two defences, both fail-closed. (1) After the write-ahead record and immediately before the
PUT, the CLI re-reads the PR once. It aborts with outcome `MERGE_ABORTED_STATE_CHANGED` (exit 1, no
failure marker, no label, an `not_verified` note) if base.ref differs from the snapshot's or the default
branch, the head SHA moved, the PR is not open, it is a draft, `hos-halt` is present, or `needs-human`
presence differs from the snapshot. A failed re-read aborts too. (2) After a confirmed merge (including a
recovered one) it re-reads the PR; a base other than the default branch writes a
`merge-on-human-approval-base-mismatch` audit record, comments, adds `needs-human`, and exits 1 with
outcome `MERGED_BASE_MISMATCH`. A failed post-merge read is noted in `not_verified` only. A window of
milliseconds between the re-read and the PUT remains by construction (GitHub offers no base pin on the
merge endpoint); the post-merge check is its detector. The pre-PUT re-read also covers reviews and issue comments (R6, R9, R10): any review or comment id not in the snapshot, any snapshot review whose state, body or submitted_at changed (for example dismissed or edited), any comment whose `updated_at` differs from the snapshot's or is missing or unparseable (an edited hold), or a failed re-read aborts with the same outcome, and the rules are not re-evaluated, so new activity simply defers to the next cycle; the only residual is the millisecond window between that re-read and the PUT, which is disclosed. Classification: `clarifying`.

---

## Escalation flag (CORE self-flag)

```
RISK: HIGH
CONFIDENCE: HIGH on the rule list, data sources and replay fixture (L1-L7 read live 2026-10-31);
  MEDIUM on current_user_can_bypass for the *overseer* token (read with the worker token; the
  S1b live check in §0 closes this) and on GraphQL reviewThreads pagination shape (documented API,
  not replayed here)
CHANGE CLASSIFICATION: additive (new uncalled code; parent decision structural and human-gated by
  ADR-2213's ESCs)
BLAST RADIUS: none at S1a merge (no caller); after S1b, every PR a designated human approves.
  Protected files: bootstrap/overseer_merge.sh, bootstrap/merge_authority.sh. Security surface:
  scripts/automation/lib/{approval_merge,merge_authority,github}.py
```

## Human Review Required

This design adds the overseer's first code path that can merge a PR, although nothing calls it until
S1b. It touches two protected `bootstrap/**` files and three security-surface `lib/` modules. Before
the S1a PR merges, the human must:
- answer ESC-1b, ESC-2, ESC-3, ESC-4 and ARCH-ESC-5, or accept the defaults in §1;
- approve the PR, which the human merges under the old flow.
